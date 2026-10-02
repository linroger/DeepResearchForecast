"""
图谱构建服务
接口2：使用Zep API构建Standalone Graph
"""

import os
import re
import uuid
import time
import json
import hashlib
import math
import unicodedata
import logging
import threading
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass

from .graphiti_client import Zep
from .graphiti_client import EpisodeData, EntityEdgeSourceTarget

from ..config import Config
from ..models.task import TaskManager, TaskStatus
from ..utils.security import UnsafeIdError, contained_child
from ..utils.zep_paging import fetch_all_nodes, fetch_all_edges
from ..utils.actors import (
    ACTOR_INTELLIGENCE_SCHEMA_VERSION,
    extract_actor_rows,
    extract_relationship_rows,
    actor_briefing,
    normalize_name,
    REL_EDGE_NAME,
    entity_archetype,
    entity_simulation_tier,
    salience_score,
    relation_valence,
    relation_polarity,
)
from .actor_role_prompt import (
    UNSAFE_RESEARCH_TEXT_REPLACEMENT,
    delimit_untrusted_research_text,
    sanitize_untrusted_research_text,
)
from .text_processor import TextProcessor

logger = logging.getLogger("mirofish.graph_builder")

# 研究 actor.type → 图谱节点标签（自定义实体类型；未知归到通用 Entity）。
# Media/Government/Platform 都落到 Organization（与本体生成器的类型口径一致）。
ACTOR_TYPE_TO_LABEL = {
    "Person": "Person",
    "Organization": "Organization",
    "Media": "Organization",
    "Government": "Organization",
    "Platform": "Organization",
}

# Zep 保留属性名，不能作为节点属性名（与 set_ontology 内的同名集合一致）。
RESERVED_ATTR_NAMES = {'uuid', 'name', 'group_id', 'name_embedding', 'summary', 'created_at'}


# R2-KG-5: betweenness/articulation are O(V*E); skip the prior computation above this
# node count so a pathologically large graph can never stall the (gated) post-build pass.
# KG-3: 仅作 Config.GRAPH_CHOKEPOINT_MAX_NODES 缺失/非法时的兜底值（真正的旋钮在 Config）。
_CHOKEPOINT_MAX_NODES = 1500

_ACTOR_GRAPH_SEED_SCHEMA_VERSION = "actor-graph-seed/v1"
_ACTOR_GRAPH_SEED_MANIFEST_VERSION = "actor-graph-seed-manifest/v1"
_ACTOR_GRAPH_SEED_READBACK_VERSION = "actor-graph-seed-readback/v1"
_RELATIONSHIP_CAUSAL_KEYS = (
    "valence",
    "polarity",
    "sign",
    "strength",
    "grade",
    "since",
    "until",
    "lag",
)


class ActorGraphSeedError(RuntimeError):
    """A sealed actor-intelligence graph seed could not be written exactly."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_causal_attributes(
    value: Dict[str, Any],
    *,
    location: str,
) -> Dict[str, Any]:
    """Mirror the admitted producer's causal identity normalization exactly."""
    out: Dict[str, Any] = {}
    for key in _RELATIONSHIP_CAUSAL_KEYS:
        raw = value.get(key)
        if raw in (None, ""):
            continue
        if isinstance(raw, str):
            normalized = " ".join(unicodedata.normalize("NFKC", raw).split())
            if normalized:
                out[key] = normalized
            continue
        if isinstance(raw, bool):
            out[key] = raw
            continue
        if isinstance(raw, (int, float)):
            if not math.isfinite(float(raw)):
                raise ActorGraphSeedError(
                    f"{location} causal attribute {key} is non-finite"
                )
            out[key] = raw
            continue
        raise ActorGraphSeedError(
            f"{location} causal attribute {key} is not a scalar"
        )
    return out


def _seed_uuid(graph_id: str, kind: str, identity: str) -> str:
    """Return a deterministic Graphiti UUID without conflating graph tenants."""
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"deepresearchforecast:{graph_id}:{kind}:{identity}",
    ))


def _current_actor_seed_contract(actors: Optional[Dict[str, Any]]) -> bool:
    """Select the strict v1 boundary while keeping unversioned inputs legacy.

    A top-level seal is authoritative.  The row-level check is retained only as
    a migration seam for early v1 artifacts that carried the actor marker before
    the top-level contract was added.  Any explicit unknown version fails closed.
    """
    if not isinstance(actors, dict):
        return False
    contract = actors.get("actor_intelligence_contract")
    root_version = str(
        contract.get("schema_version") if isinstance(contract, dict) else ""
    ).strip()
    row_versions = {
        str((row.get("intelligence") or {}).get("schema_version") or "").strip()
        for row in (actors.get("actors") or [])
        if isinstance(row, dict) and isinstance(row.get("intelligence"), dict)
    }
    row_versions.discard("")
    explicit_versions = ({root_version} if root_version else set()) | row_versions
    unsupported = explicit_versions - {ACTOR_INTELLIGENCE_SCHEMA_VERSION}
    if unsupported:
        raise ActorGraphSeedError(
            "unsupported actor-intelligence graph seed schema: "
            + ", ".join(sorted(unsupported))
        )
    return ACTOR_INTELLIGENCE_SCHEMA_VERSION in explicit_versions


def _strict_identity_text(value: Any, *, field: str, max_chars: int = 240) -> str:
    """Sanitize structural identity without silently changing hostile identities."""
    raw = str(value or "").strip()
    clean = sanitize_untrusted_research_text(raw, max_chars=max_chars).strip()
    clean = " ".join(clean.split())
    if not clean:
        raise ActorGraphSeedError(f"current actor seed {field} is empty")
    if UNSAFE_RESEARCH_TEXT_REPLACEMENT in clean:
        raise ActorGraphSeedError(
            f"current actor seed {field} contains instruction-like text"
        )
    return clean


def _delimited_seed_record(label: str, value: Any, *, max_chars: int = 30000) -> str:
    """Sanitize the complete record, then mark it as non-executable model data."""
    whole_document = _canonical_json(value)
    # JSON escaping must not turn a directive split across research lines into
    # an opaque ``\\n`` token before the whole-document detector sees it.
    whole_document = (
        whole_document.replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\\r", "\n")
    )
    sanitized = sanitize_untrusted_research_text(
        whole_document,
        max_chars=max_chars,
    )
    block = delimit_untrusted_research_text(
        label,
        sanitized,
        max_chars=max_chars,
    )
    if not block:
        raise ActorGraphSeedError(f"current actor seed {label} rendered empty")
    return block


def _validated_source_support(value: Any, *, location: str) -> List[Dict[str, Any]]:
    """Require the quote/span/receipt/content identity of an admitted v1 claim."""
    if not isinstance(value, list) or not value or any(
        not isinstance(row, dict) for row in value
    ):
        raise ActorGraphSeedError(f"{location} source support is missing or malformed")
    rows: List[Dict[str, Any]] = []
    for support_index, row in enumerate(value):
        quote = str(row.get("supporting_quote") or "").strip()
        span = row.get("supporting_span")
        receipt_id = str(row.get("receipt_id") or "").strip()
        content_sha256 = str(row.get("content_sha256") or "").strip().lower()
        source_identity = str(
            row.get("source_id") or row.get("source_ref") or ""
        ).strip()
        try:
            start = int(span.get("start")) if isinstance(span, dict) else -1
            end = int(span.get("end")) if isinstance(span, dict) else -1
        except (TypeError, ValueError):
            start = end = -1
        if (
            not source_identity
            or not quote
            or start < 0
            or end <= start
            or not receipt_id
            or not re.fullmatch(r"[0-9a-f]{64}", content_sha256)
        ):
            raise ActorGraphSeedError(
                f"{location} source support is not quote/receipt bound: "
                f"{support_index}"
            )
        rows.append(row)
    return rows


def _source_bound_actor_claims(actor: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Project only canonical, source-bound v1 dimension claims.

    Flat role/description/stance/memory fields are intentionally unreachable
    from this function.  Nested evidence is retained in a deterministic shape so
    it can be written as provenance attributes as well as sanitized model text.
    """
    intelligence = actor.get("intelligence")
    if not isinstance(intelligence, dict) or str(
        intelligence.get("schema_version") or ""
    ).strip() != ACTOR_INTELLIGENCE_SCHEMA_VERSION:
        raise ActorGraphSeedError(
            f"actor {actor.get('actor_id') or actor.get('name')} lacks canonical v1 intelligence"
        )
    dimensions = intelligence.get("dimensions")
    if not isinstance(dimensions, dict):
        raise ActorGraphSeedError(
            f"actor {actor.get('actor_id') or actor.get('name')} dimensions are not an object"
        )
    if any(not isinstance(dimension, str) for dimension in dimensions):
        raise ActorGraphSeedError("actor intelligence dimension names are not strings")
    projected: List[Dict[str, Any]] = []
    for dimension in sorted(dimensions):
        raw_claims = dimensions[dimension]
        if not isinstance(raw_claims, list):
            raise ActorGraphSeedError(
                f"actor {actor.get('actor_id') or actor.get('name')} dimension {dimension} is not a list"
            )
        for claim_index, claim in enumerate(raw_claims):
            if not isinstance(claim, dict):
                raise ActorGraphSeedError(
                    f"actor claim is not an object: {dimension}[{claim_index}]"
                )
            claim_text = str(claim.get("claim") or "").strip()
            raw_source_refs = claim.get("source_refs")
            if not isinstance(raw_source_refs, list):
                raise ActorGraphSeedError(
                    f"actor claim source_refs are not a list: {dimension}[{claim_index}]"
                )
            source_refs = [
                str(item).strip()
                for item in raw_source_refs
                if isinstance(item, str) and item.strip()
            ]
            if not claim_text or not source_refs:
                raise ActorGraphSeedError(
                    f"actor claim is not source-bound: {dimension}[{claim_index}]"
                )
            source_support = _validated_source_support(
                claim.get("source_support"),
                location=f"actor claim {dimension}[{claim_index}]",
            )
            payload = {
                "dimension": str(dimension),
                "claim": claim_text,
                "evidence_type": str(claim.get("evidence_type") or ""),
                "claim_valid_at": str(
                    claim.get("claim_valid_at") or claim.get("as_of_date") or ""
                ),
                "horizon": str(claim.get("horizon") or ""),
                "status": str(claim.get("status") or ""),
                "confidence": str(claim.get("confidence") or ""),
                "source_refs": source_refs,
                "source_support": source_support,
                "dependencies": claim.get("dependencies") or [],
                "contradictions": claim.get("contradictions") or [],
                "qualifiers": claim.get("qualifiers") or {},
                "causal_attributes": _canonical_causal_attributes(
                    claim,
                    location=f"actor claim {dimension}[{claim_index}]",
                ),
            }
            claim_sha256 = str(claim.get("claim_sha256") or "").strip().lower()
            claim_id = str(claim.get("claim_id") or "").strip()
            if not re.fullmatch(r"[0-9a-f]{64}", claim_sha256) or not claim_id:
                raise ActorGraphSeedError(
                    f"actor claim identity is not sealed: {dimension}[{claim_index}]"
                )
            payload["claim_sha256"] = claim_sha256
            payload["claim_id"] = claim_id
            projected.append(payload)
    return projected


def _actor_seed_manifest_from_plan(
    graph_id: str,
    contract: Dict[str, Any],
    actor_records: Dict[str, Dict[str, Any]],
    operations: List[tuple[str, tuple[Any, ...], Dict[str, Any]]],
) -> Dict[str, Any]:
    """Describe the exact physical seed state independently of DB readback."""
    nodes_by_uuid: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    def add_node(
        *,
        node_uuid: str,
        name: str,
        label: str,
        summary: str,
        attributes: Dict[str, Any],
    ) -> None:
        entry = {
            "uuid": node_uuid,
            "name": name,
            "required_labels": sorted({"Entity", label} - {""}),
            "summary_sha256": hashlib.sha256(
                str(summary or "").encode("utf-8")
            ).hexdigest(),
            "seed_kind": str(attributes.get("seed_kind") or ""),
            "required_attributes": dict(attributes),
            "required_attributes_sha256": _canonical_sha256(attributes),
        }
        existing = nodes_by_uuid.get(node_uuid)
        if existing is not None and existing != entry:
            raise ActorGraphSeedError(
                f"seed plan maps node UUID {node_uuid} to conflicting identities"
            )
        nodes_by_uuid[node_uuid] = entry

    for operation_id, args, kwargs in operations:
        add_node(
            node_uuid=kwargs["source_uuid"],
            name=str(args[1]),
            label=str(kwargs.get("source_label") or "Entity"),
            summary=str(kwargs.get("source_summary") or ""),
            attributes=dict(kwargs.get("source_attributes") or {}),
        )
        add_node(
            node_uuid=kwargs["target_uuid"],
            name=str(args[3]),
            label=str(kwargs.get("target_label") or "Entity"),
            summary=str(kwargs.get("target_summary") or ""),
            attributes=dict(kwargs.get("target_attributes") or {}),
        )
        edge_attributes = dict(kwargs.get("edge_attributes") or {})
        edges.append({
            "operation_id": operation_id,
            "uuid": kwargs["edge_uuid"],
            "name": str(args[2]),
            "source_node_uuid": kwargs["source_uuid"],
            "target_node_uuid": kwargs["target_uuid"],
            "fact_sha256": hashlib.sha256(
                str(args[4] or "").encode("utf-8")
            ).hexdigest(),
            "seed_kind": str(edge_attributes.get("seed_kind") or ""),
            "required_attributes": edge_attributes,
            "required_attributes_sha256": _canonical_sha256(edge_attributes),
        })

    edge_uuids = [entry["uuid"] for entry in edges]
    if len(edge_uuids) != len(set(edge_uuids)):
        raise ActorGraphSeedError("seed plan contains duplicate edge UUIDs")
    nodes = sorted(nodes_by_uuid.values(), key=lambda row: row["uuid"])
    edges.sort(key=lambda row: row["uuid"])

    actor_nodes = [row for row in nodes if row["seed_kind"] == "actor"]
    alias_nodes = [row for row in nodes if row["seed_kind"] == "actor_alias"]
    entity_type_nodes = [
        row for row in nodes if row["seed_kind"] == "entity_type"
    ]
    identity_edges = [
        row for row in edges if row["seed_kind"] == "actor_identity"
    ]
    alias_edges = [row for row in edges if row["seed_kind"] == "actor_alias"]
    relationship_edges = [
        row for row in edges if row["seed_kind"] == "relationship"
    ]

    actor_index = {
        row["required_attributes"]["actor_id"]: row for row in actor_nodes
    }
    actors_projection = [{
        "actor_id": actor_id,
        "name": record["name"],
        "node_uuid": actor_index[actor_id]["uuid"],
        "seed_record_sha256": record["attributes"]["seed_record_sha256"],
        "canonical_claims_sha256": record["attributes"][
            "canonical_claims_sha256"
        ],
        "actor_intelligence_sha256": record["attributes"][
            "actor_intelligence_sha256"
        ],
    } for actor_id, record in sorted(actor_records.items())]
    aliases_projection = [{
        "actor_id": row["required_attributes"]["actor_id"],
        "alias": row["required_attributes"]["alias"],
        "node_uuid": row["uuid"],
        "edge_uuid": next(
            edge["uuid"] for edge in alias_edges
            if edge["target_node_uuid"] == row["uuid"]
        ),
    } for row in alias_nodes]
    relationships_projection = [{
        "relationship_id": row["required_attributes"]["relationship_id"],
        "edge_uuid": row["uuid"],
        "source_actor_id": row["required_attributes"]["source_actor_id"],
        "target_actor_id": row["required_attributes"]["target_actor_id"],
        "source_node_uuid": row["source_node_uuid"],
        "target_node_uuid": row["target_node_uuid"],
        "claim_sha256": row["required_attributes"]["claim_sha256"],
        "seed_record_sha256": row["required_attributes"]["seed_record_sha256"],
        "provenance_sha256": _canonical_sha256({
            key: row["required_attributes"].get(key)
            for key in (
                "source_refs_json",
                "source_support_json",
                "supporting_quotes_json",
                "supporting_spans_json",
                "receipt_ids_json",
                "content_sha256s_json",
            )
        }),
    } for row in relationship_edges]
    aliases_projection.sort(key=lambda row: (row["actor_id"], row["alias"]))
    relationships_projection.sort(key=lambda row: row["relationship_id"])

    payload: Dict[str, Any] = {
        "schema_version": _ACTOR_GRAPH_SEED_MANIFEST_VERSION,
        "strict": True,
        "graph_id": graph_id,
        "actor_intelligence_schema_version": ACTOR_INTELLIGENCE_SCHEMA_VERSION,
        "source_contract": {
            key: contract.get(key)
            for key in (
                "report_sha256",
                "dossier_sha256",
                "sources_sha256",
                "actor_ids_sha256",
                "actor_ids_ordered_sha256",
                "actor_ids_multiset_sha256",
                "claim_projection_multiset_sha256",
                "relationships_sha256",
            )
            if contract.get(key) not in (None, "")
        },
        "actors": actors_projection,
        "aliases": aliases_projection,
        "identity_edges": [{
            "actor_id": row["required_attributes"]["actor_id"],
            "edge_uuid": row["uuid"],
            "source_node_uuid": row["source_node_uuid"],
            "target_node_uuid": row["target_node_uuid"],
            "seed_record_sha256": row["required_attributes"][
                "seed_record_sha256"
            ],
        } for row in identity_edges],
        "relationships": relationships_projection,
        "seed_nodes": nodes,
        "seed_edges": edges,
        "expected_counts": {
            "actor_nodes": len(actor_nodes),
            "alias_nodes": len(alias_nodes),
            "entity_type_nodes": len(entity_type_nodes),
            "seed_nodes": len(nodes),
            "identity_edges": len(identity_edges),
            "alias_edges": len(alias_edges),
            "relationship_edges": len(relationship_edges),
            "seed_edges": len(edges),
            "required_writes": len(operations),
        },
    }
    payload["seed_nodes_sha256"] = _canonical_sha256(nodes)
    payload["seed_edges_sha256"] = _canonical_sha256(edges)
    payload["manifest_sha256"] = _canonical_sha256(payload)
    return payload


def build_actor_graph_seed_manifest(
    graph_id: str,
    actors: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the immutable expected seed manifest used by parent orchestration."""
    if not _current_actor_seed_contract(actors):
        payload = {
            "schema_version": "actor-graph-seed-manifest/legacy-unversioned",
            "strict": False,
            "graph_id": graph_id,
        }
        payload["manifest_sha256"] = _canonical_sha256(payload)
        return payload
    service = GraphBuilderService.__new__(GraphBuilderService)
    plan = service._prepare_actor_intelligence_v1_seed(
        graph_id,
        actors,
        valid_at=None,
    )
    return plan["manifest"]


def _brandes_betweenness(adj: Dict[Any, set]) -> Dict[Any, float]:
    """R2-KG-5: unweighted betweenness centrality (Brandes' algorithm) on an
    undirected adjacency map. O(V*E); caller caps V before invoking. Returns raw
    (un-normalized) scores; the undirected pair double-count is halved here."""
    import collections

    CB: Dict[Any, float] = dict.fromkeys(adj, 0.0)
    for s in adj:
        S: List[Any] = []
        P: Dict[Any, list] = {w: [] for w in adj}
        sigma = dict.fromkeys(adj, 0.0)
        sigma[s] = 1.0
        dist = dict.fromkeys(adj, -1)
        dist[s] = 0
        Q = collections.deque([s])
        while Q:
            v = Q.popleft()
            S.append(v)
            for w in adj[v]:
                if dist[w] < 0:
                    Q.append(w)
                    dist[w] = dist[v] + 1
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    P[w].append(v)
        delta = dict.fromkeys(adj, 0.0)
        while S:
            w = S.pop()
            for v in P[w]:
                if sigma[w]:
                    delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != s:
                CB[w] += delta[w]
    for v in CB:
        CB[v] /= 2.0  # undirected: each shortest path counted from both endpoints
    return CB


def _articulation_points(adj: Dict[Any, set]) -> set:
    """R2-KG-5: articulation points (cut vertices) via iterative Tarjan DFS — nodes
    whose removal disconnects the graph (structural chokepoints). Iterative to avoid
    Python recursion limits on large graphs."""
    visited: set = set()
    disc: Dict[Any, int] = {}
    low: Dict[Any, int] = {}
    ap: set = set()
    timer = 0
    for start in adj:
        if start in visited:
            continue
        root_children = 0
        stack = [(start, None, iter(adj[start]))]  # frames: (node, parent, neighbor_iter)
        visited.add(start)
        disc[start] = low[start] = timer
        timer += 1
        while stack:
            node, parent, it = stack[-1]
            pushed = False
            for nb in it:
                if nb == parent:
                    continue
                if nb not in visited:
                    visited.add(nb)
                    disc[nb] = low[nb] = timer
                    timer += 1
                    if node == start:
                        root_children += 1
                    stack.append((nb, node, iter(adj[nb])))
                    pushed = True
                    break
                else:
                    low[node] = min(low[node], disc[nb])
            if not pushed:
                stack.pop()
                if stack:
                    par = stack[-1][0]
                    low[par] = min(low[par], low[node])
                    if par != start and low[node] >= disc[par]:
                        ap.add(par)  # non-root articulation condition
        if root_children > 1:
            ap.add(start)
    return ap


def safe_attr_name(attr_name: str) -> str:
    """把保留名称转换为安全的节点属性名（与 set_ontology 内的局部实现口径一致）。

    C8（ONTOLOGY 富 schema）：种子节点的 archetype/simulation_tier/salience 等本体属性
    需要一个稳定的、避开 Zep 保留字的属性名空间。set_ontology 用同样的规则给实体类型
    的属性改名，这里抽到模块级供 seed_actors 复用，避免规则漂移。
    """
    if attr_name and attr_name.lower() in RESERVED_ATTR_NAMES:
        return f"entity_{attr_name}"
    return attr_name


def fold_priors_with_aliases(
    priors: Optional[Dict[str, float]],
    actors: Optional[Any],
) -> Dict[str, float]:
    """KG-7: 按 actors.json 的「策展别名组」折叠中心度先验，防止同一现实 actor 的
    表面形（"TSM"/"TSMC"、"Trump"/别名）把影响力信号打碎成任意小的分片。

    规则（GRAPH_PRIORS_ALIAS_FOLD，默认开）：
    * 只认策展别名组 = actor 行的 name + aliases[]（归一名**精确**相等才算组员）。
      刻意不做包含/启发式配对——"IEEEPA" vs "IEEPA-based tariffs"、"Trump"(人) vs
      "Trump Administration"(机构) 在本体上是不同实体，MAX 折叠会错误抬高它们。
    * 组内取 MAX，写回每个组员名下。ADD-only：已有键只升不降，别名缺键则补键，
      旧消费者（simulation_manager 按归一名查 [0,1] 值）不受影响。
    * 开关关闭 / 无 actors / 无先验时原样返回拷贝（degrade-safe）。
    """
    out: Dict[str, float] = dict(priors or {})
    if not out or not getattr(Config, "GRAPH_PRIORS_ALIAS_FOLD", True):
        return out
    rows = extract_actor_rows(actors)
    if not rows:
        return out
    # 归一名 → 原始 prior 键列表（同一归一名可能对应多个原始键，全部一起抬升）。
    norm_index: Dict[str, List[str]] = {}
    for k in out:
        if isinstance(k, str):
            nk = normalize_name(k)
            if nk:
                norm_index.setdefault(nk, []).append(k)
    for row in rows:
        members: List[str] = [str(row.get("name") or "")]
        raw_aliases = row.get("aliases")
        if isinstance(raw_aliases, list):
            members.extend(a for a in raw_aliases if isinstance(a, str))
        norm_members = {normalize_name(m) for m in members}
        norm_members.discard("")
        if len(norm_members) < 2:
            continue  # 无别名 → 无可折叠
        group_max = 0.0
        for nm in norm_members:
            for k in norm_index.get(nm, ()):
                v = out.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    group_max = max(group_max, float(v))
        if group_max <= 0.0:
            continue  # 组内无人带先验，无需补键
        seen_norms: set = set()
        for m in members:
            nm = normalize_name(m)
            if not nm or nm in seen_norms:
                continue
            seen_norms.add(nm)
            keys = norm_index.get(nm)
            if keys:
                for k in keys:
                    v = out.get(k)
                    cur = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0
                    out[k] = max(cur, group_max)
            else:
                # 缺键的组员补键（消费者按 actor 名/别名查表时不再落空）。
                mk = m.strip() or m
                out[mk] = group_max
                norm_index.setdefault(nm, []).append(mk)
    return out


# ============================================================
# W10-COST：cast 相关性 chunk 预过滤（GRAPH_CAST_CHUNK_FILTER，默认开）。
# 实测（2026-07 forensic audit）：graph 阶段 8h37m 占一次 run 的 62%，dossier_only
# 466 chunk 有 278（60%）在烧完整套重试阶梯后才被跳过，而抽取产出的大部分节点又被
# 剪枝砍回 GRAPH_MAX_ENTITIES——不含任何 cast 名的 chunk 根本不该进 LLM 抽取。
# 纯函数 + 模块级，便于离线单测（与本文件其余 Wave9 纯函数同一范式）。
# ============================================================

def cast_filter_terms_from_actors(actors: Optional[Any]) -> List[str]:
    """从 actors.json 提取归一化 cast 匹配词表：actor 名 + aliases + 关系端点。

    与 seed_actors 种入图谱的 cast 完全同源；normalize_name（NFKC/小写/去空白标点）
    保证与 chunk 侧同规归一。丢弃归一后 <2 字符的词（单字符匹配一切，无过滤价值）。
    """
    terms: List[str] = []
    seen: set = set()

    def _add(raw: Any) -> None:
        if not isinstance(raw, str):
            return
        t = normalize_name(raw)
        if len(t) >= 2 and t not in seen:
            seen.add(t)
            terms.append(t)

    for row in extract_actor_rows(actors):
        _add(row.get("name"))
        aliases = row.get("aliases")
        if isinstance(aliases, list):
            for a in aliases:
                _add(a)
    for rel in extract_relationship_rows(actors):
        _add(rel.get("source"))
        _add(rel.get("target"))
    return terms


def chunk_mentions_cast(chunk: str, terms: List[str]) -> bool:
    """chunk 是否提及任一 cast 词（双方 normalize_name 归一后子串匹配）。

    归一化剥掉空白/常见标点，"Elon  Musk"/"elon-musk" 均命中 "elonmusk"；CJK 名
    天然无词边界，子串匹配即正确语义。误报（把无关 chunk 判为提及）只是少过滤一个
    chunk，安全；词表为空时恒 True（不过滤）。
    """
    if not terms:
        return True
    norm = normalize_name(chunk)
    if not norm:
        return False
    return any(t in norm for t in terms)


# ============================================================
# Wave9-KG：UI 子图 / TTL 缓存 / 布局预计算 / 陈旧图谱 GC 的纯函数与模块级设施。
# 模块级（而非实例方法）是刻意的：graph_pruner 无需构造 GraphBuilderService/Zep
# 客户端即可复用布局与缓存失效；纯函数可离线单测。
# ============================================================

_UI_CACHE: Dict[str, Any] = {}          # cache_key -> (monotonic_ts, payload)
_UI_CACHE_LOCK = threading.Lock()


def _ui_cache_ttl() -> float:
    try:
        return max(0.0, float(getattr(Config, "GRAPH_UI_CACHE_TTL_S", 60) or 0))
    except (TypeError, ValueError):
        return 60.0


def _ui_cache_get(key: str) -> Optional[Any]:
    ttl = _ui_cache_ttl()
    if ttl <= 0:
        return None
    with _UI_CACHE_LOCK:
        entry = _UI_CACHE.get(key)
        if entry is None:
            return None
        ts, payload = entry
        if (time.monotonic() - ts) >= ttl:
            _UI_CACHE.pop(key, None)
            return None
        return payload


def _ui_cache_put(key: str, payload: Any) -> None:
    if _ui_cache_ttl() <= 0:
        return
    with _UI_CACHE_LOCK:
        _UI_CACHE[key] = (time.monotonic(), payload)


def invalidate_graph_cache(graph_id: str) -> None:
    """图谱内容变化（剪枝/删除/增量落库）后使该图的 UI 缓存失效。"""
    prefix = f"{graph_id}|"
    with _UI_CACHE_LOCK:
        for key in [k for k in _UI_CACHE if k.startswith(prefix)]:
            _UI_CACHE.pop(key, None)


def compute_node_degrees(edges_data: List[Dict[str, Any]]) -> Dict[str, int]:
    """按（去重后的）边列表计算节点度数；自环计 1。纯函数，供子图/布局/剪枝复用。"""
    degree: Dict[str, int] = {}
    for e in edges_data or []:
        s = e.get("source_node_uuid")
        t = e.get("target_node_uuid")
        if s:
            degree[s] = degree.get(s, 0) + 1
        if t and t != s:
            degree[t] = degree.get(t, 0) + 1
    return degree


def filter_subgraph(
    nodes_data: List[Dict[str, Any]],
    edges_data: List[Dict[str, Any]],
    top_k: Optional[int] = None,
    min_degree: Optional[int] = None,
) -> tuple:
    """UI 子图筛选：先按 min_degree 过滤，再按度数取 top-K，最后取导出边。

    两个参数都为 None 时原样返回（全量行为不变）。返回 (nodes, edges)。
    """
    if top_k is None and min_degree is None:
        return list(nodes_data or []), list(edges_data or [])
    degree = compute_node_degrees(edges_data)
    kept = list(nodes_data or [])
    if min_degree is not None and min_degree > 0:
        kept = [n for n in kept if degree.get(n.get("uuid"), 0) >= min_degree]
    if top_k is not None:
        k = int(top_k)
        if k <= 0:  # top_k=0/负 = 「用配置默认上限」（前端可传 top_k=0 表示默认收敛视图）
            k = max(1, int(getattr(Config, "GRAPH_UI_MAX_NODES", 400) or 400))
        # 度数降序，同度按名字升序（确定性排序，前端刷新不抖动）。
        kept = sorted(
            kept,
            key=lambda n: (-degree.get(n.get("uuid"), 0), str(n.get("name") or "")),
        )[:k]
    kept_ids = {n.get("uuid") for n in kept}
    induced = [
        e for e in (edges_data or [])
        if e.get("source_node_uuid") in kept_ids and e.get("target_node_uuid") in kept_ids
    ]
    return kept, induced


# slim 模式保留的字段（heavy 字段 summary/attributes/fact/episodes 走 detail 接口）。
# W10-COST/前端时间维度：valid_at/invalid_at 是双时态轴（前端 temporal dimming 的门控
# 字段），体积可忽略，必须随 slim 边下发——剥掉它们会让默认列表视图无法按时间淡显。
_SLIM_NODE_KEYS = ("uuid", "name", "labels")
_SLIM_EDGE_KEYS = (
    "uuid", "name", "fact_type",
    "source_node_uuid", "target_node_uuid", "source_node_name", "target_node_name",
    "valid_at", "invalid_at",
)


def slim_graph_payload(
    nodes_data: List[Dict[str, Any]], edges_data: List[Dict[str, Any]]
) -> tuple:
    """slim=true：剥掉 UI 列表用不到的重字段（summary/fact/episodes/attributes 等）。"""
    nodes = [{k: n.get(k) for k in _SLIM_NODE_KEYS} for n in (nodes_data or [])]
    edges = [{k: e.get(k) for k in _SLIM_EDGE_KEYS} for e in (edges_data or [])]
    return nodes, edges


# --------------------------- 布局预计算（positions.json） ---------------------------
def layout_positions_path(graph_id: str) -> str:
    """positions.json 紧邻图谱工件（GRAPHITI_DATA_DIR/layouts/<graph_id>/positions.json）。

    INFRA-10：graph_id 经 contained_child 校验（非法/逃逸 id 抛 UnsafeIdError）。
    """
    layout_dir = contained_child(os.path.join(Config.GRAPHITI_DATA_DIR, "layouts"), graph_id, "graph")
    return os.path.join(layout_dir, "positions.json")


def load_layout_positions(graph_id: str) -> Dict[str, List[float]]:
    """读预计算布局；缺失/损坏/非法 id 返回 {}（前端退回客户端力导布局，degrade-safe）。"""
    import json

    try:
        path = layout_positions_path(graph_id)
    except UnsafeIdError:
        return {}
    try:
        if not os.path.isfile(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        out: Dict[str, List[float]] = {}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, (list, tuple)) and len(v) >= 2:
                try:
                    out[k] = [float(v[0]), float(v[1])]
                except (TypeError, ValueError):
                    continue
        return out
    except Exception as exc:  # noqa: BLE001 — 布局是增强，绝不让读取失败影响主数据
        logger.warning("[%s] load_layout_positions failed: %s", graph_id, exc)
        return {}


def compute_layout_positions(
    nodes_data: List[Dict[str, Any]], edges_data: List[Dict[str, Any]]
) -> Dict[str, List[float]]:
    """计算 {uuid: [x, y]}（坐标域约 [0, 1000]²）。

    优先 networkx spring_layout（seed 固定，确定性）；networkx 不可用/失败时退化为
    确定性的「按度数径向」布局：度数最高的节点靠近圆心，向外做黄金角螺旋。
    """
    ids = [n.get("uuid") for n in (nodes_data or []) if n.get("uuid")]
    if not ids:
        return {}
    try:
        import networkx as nx

        G = nx.Graph()
        G.add_nodes_from(ids)
        id_set = set(ids)
        for e in edges_data or []:
            s, t = e.get("source_node_uuid"), e.get("target_node_uuid")
            if s in id_set and t in id_set and s != t:
                G.add_edge(s, t)
        pos = nx.spring_layout(G, seed=42, iterations=60)
        # spring_layout 输出 ~[-1,1]²；线性映射到 [0,1000]²。
        return {
            str(k): [round(float(p[0]) * 500.0 + 500.0, 2),
                     round(float(p[1]) * 500.0 + 500.0, 2)]
            for k, p in pos.items()
        }
    except Exception as exc:  # noqa: BLE001 — 含 ImportError：退化为径向布局
        logger.info("spring layout unavailable (%s); falling back to radial-by-degree", exc)
        import math

        degree = compute_node_degrees(edges_data)
        ordered = sorted(ids, key=lambda u: (-degree.get(u, 0), u))
        golden = math.pi * (3.0 - math.sqrt(5.0))  # 黄金角 ≈ 2.39996
        out: Dict[str, List[float]] = {}
        for i, uid in enumerate(ordered):
            r = 16.0 * math.sqrt(i)
            theta = i * golden
            out[uid] = [round(500.0 + r * math.cos(theta), 2),
                        round(500.0 + r * math.sin(theta), 2)]
        return out


def store_layout_positions(graph_id: str, positions: Dict[str, List[float]]) -> str:
    """原子写 positions.json，返回路径。"""
    import json
    import tempfile

    path = layout_positions_path(graph_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(positions, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


# --------------------------- 陈旧图谱 GC（纯规划 + 引用扫描） ---------------------------
# 终态之外的 pipeline 状态一律视为「活动中」（running/pending/cancelling/…）。
_TERMINAL_PIPELINE_STATUSES = {"completed", "failed", "cancelled", "error"}


def _collect_graph_ids(obj: Any, out: set) -> None:
    """递归收集 JSON 结构里所有 "graph_id" 字符串值（顶层与各阶段结果都可能带）。"""
    if isinstance(obj, dict):
        gid = obj.get("graph_id")
        if isinstance(gid, str) and gid.strip():
            out.add(gid.strip())
        for v in obj.values():
            _collect_graph_ids(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_graph_ids(v, out)


def referenced_graph_ids() -> tuple:
    """扫描 uploads/pipelines/*/pipeline_state.json 与 uploads/projects/ 的项目档案，
    返回 (referenced: set, active_pipelines_without_graph: int)。

    后者 > 0 表示有活动管线尚未把 graph_id 写进状态——此时 GC 必须整体跳过
    （新建图谱可能暂时无引用，误删不可逆）。
    """
    import glob
    import json

    referenced: set = set()
    active_without_graph = 0
    pipeline_glob = os.path.join(Config.PIPELINE_DATA_DIR, "*", "pipeline_state.json")
    for path in glob.glob(pipeline_glob):
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception as exc:  # noqa: BLE001 — 坏状态文件：保守起见视为活动且无图
            logger.warning("GC: unreadable pipeline state %s (%s) — treating as active", path, exc)
            active_without_graph += 1
            continue
        before = len(referenced)
        _collect_graph_ids(state, referenced)
        status = str(state.get("status") or "").strip().lower()
        if status not in _TERMINAL_PIPELINE_STATUSES and len(referenced) == before:
            active_without_graph += 1
    # 项目档案（/graph/build 的独立项目路径）也持有 graph_id。
    projects_glob = os.path.join(Config.UPLOAD_FOLDER, "projects", "*", "*.json")
    for path in glob.glob(projects_glob):
        try:
            with open(path, "r", encoding="utf-8") as f:
                _collect_graph_ids(json.load(f), referenced)
        except Exception:  # noqa: BLE001 — 项目档案坏了不阻断（管线引用已覆盖主路径）
            continue
    return referenced, active_without_graph


def plan_graph_gc(
    all_ids: List[str],
    referenced: set,
    recency: Dict[str, Optional[str]],
    retain: int,
) -> tuple:
    """纯规划：返回 (keep: set, victims: list)。

    keep = 被引用的图 ∪ 未引用中最新的 retain 个（按 recency ISO 串降序；未知视为最旧）。
    """
    keep = {g for g in all_ids if g in referenced}
    others = [g for g in all_ids if g not in keep]
    others.sort(key=lambda g: (recency.get(g) or "", g), reverse=True)
    retain = max(0, int(retain))
    keep |= set(others[:retain])
    victims = list(others[retain:])
    return keep, victims


@dataclass
class GraphInfo:
    """图谱信息"""
    graph_id: str
    node_count: int
    edge_count: int
    entity_types: List[str]
    # KG cookbook 结构完整性信号（均可选，ADD-only，旧消费者不受影响）：
    # components = 弱连通分量数（≈1 表示实体已良好合并；远多于预期 = 实体欠合并）；
    # top_hubs = 度数最高的若干节点名（枢纽合理性 sanity check）。
    components: int = 0
    top_hubs: Optional[List[str]] = None
    # NEXTSTEPS P3-7：归一度数中心度先验 node_name→[0,1]（复用上面已算出的 degree，此前丢弃）。
    # 高中心度比原始提及数更能反映"谁是关键节点"——一个便宜且接地的影响力先验，供 salience 融合。
    centrality: Optional[Dict[str, float]] = None
    # R2-KG-5（GRAPH_CHOKEPOINT_PRIORS，默认关）：度数中心度只看"邻居多不多"，看不出
    # "谁卡在传导路径的咽喉"。betweenness = 归一化介数中心度 node_name→[0,1]；chokepoints =
    # 介数高位 ∪ 关节点（移除即断图的桥接节点）。两者均为可选 ADD-only，关闭时为空。
    betweenness: Optional[Dict[str, float]] = None
    chokepoints: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "entity_types": self.entity_types,
            "components": self.components,
            "top_hubs": self.top_hubs or [],
            "centrality": self.centrality or {},
            "betweenness": self.betweenness or {},
            "chokepoints": self.chokepoints or [],
        }


class GraphBuilderService:
    """
    图谱构建服务
    负责调用Zep API构建知识图谱
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY 未配置")
        
        self.client = Zep(api_key=self.api_key)
        self.task_manager = TaskManager()
        # KG-5: 最近一次 add_text_batches 的落库记账（total/failed/succeeded），供编排器
        # 把「部分文本块被跳过」写进 pipeline_state/health。None = 尚未跑过建图。
        self.last_ingest_stats: Optional[Dict[str, Any]] = None
        self.last_actor_graph_seed_manifest: Optional[Dict[str, Any]] = None
        # W10-COST: graph_id → 归一化 cast 词表（seed_actors 时登记；add_text_batches
        # 的 cast 相关性预过滤按此匹配）。未登记的 graph_id 不过滤（degrade-safe）。
        self._cast_chunk_terms: Dict[str, List[str]] = {}
    
    def build_graph_async(
        self,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str = "MiroFish Graph",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        batch_size: int = 3
    ) -> str:
        """
        异步构建图谱
        
        Args:
            text: 输入文本
            ontology: 本体定义（来自接口1的输出）
            graph_name: 图谱名称
            chunk_size: 文本块大小
            chunk_overlap: 块重叠大小
            batch_size: 每批发送的块数量
            
        Returns:
            任务ID
        """
        # 创建任务
        task_id = self.task_manager.create_task(
            task_type="graph_build",
            metadata={
                "graph_name": graph_name,
                "chunk_size": chunk_size,
                "text_length": len(text),
            }
        )
        
        # 在后台线程中执行构建
        thread = threading.Thread(
            target=self._build_graph_worker,
            args=(task_id, text, ontology, graph_name, chunk_size, chunk_overlap, batch_size)
        )
        thread.daemon = True
        thread.start()
        
        return task_id
    
    def _build_graph_worker(
        self,
        task_id: str,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str,
        chunk_size: int,
        chunk_overlap: int,
        batch_size: int
    ):
        """图谱构建工作线程"""
        try:
            self.task_manager.update_task(
                task_id,
                status=TaskStatus.PROCESSING,
                progress=5,
                message="开始构建图谱..."
            )
            
            # 1. 创建图谱
            graph_id = self.create_graph(graph_name)
            self.task_manager.update_task(
                task_id,
                progress=10,
                message=f"图谱已创建: {graph_id}"
            )
            
            # 2. 设置本体
            self.set_ontology(graph_id, ontology)
            self.task_manager.update_task(
                task_id,
                progress=15,
                message="本体已设置"
            )
            
            # 3. 文本分块
            chunks = TextProcessor.split_text(text, chunk_size, chunk_overlap)
            total_chunks = len(chunks)
            self.task_manager.update_task(
                task_id,
                progress=20,
                message=f"文本已分割为 {total_chunks} 个块"
            )
            
            # 4. 分批发送数据
            episode_uuids = self.add_text_batches(
                graph_id, chunks, batch_size,
                lambda msg, prog: self.task_manager.update_task(
                    task_id,
                    progress=20 + int(prog * 0.4),  # 20-60%
                    message=msg
                )
            )
            
            # 5. 等待Zep处理完成
            self.task_manager.update_task(
                task_id,
                progress=60,
                message="等待Zep处理数据..."
            )
            
            self._wait_for_episodes(
                episode_uuids,
                lambda msg, prog: self.task_manager.update_task(
                    task_id,
                    progress=60 + int(prog * 0.3),  # 60-90%
                    message=msg
                )
            )
            
            # 6. 获取图谱信息
            self.task_manager.update_task(
                task_id,
                progress=90,
                message="获取图谱信息..."
            )
            
            graph_info = self._get_graph_info(graph_id)

            # Wave9-KG（布局预计算）：建图完成即算一次弹簧布局并持久化 positions.json，
            # 前端首屏免跑客户端力导仿真。失败只告警（compute_layout 内部已兜）。
            if getattr(Config, "GRAPH_LAYOUT_PRECOMPUTE", True):
                self.compute_layout(graph_id)

            # 完成
            self.task_manager.complete_task(task_id, {
                "graph_id": graph_id,
                "graph_info": graph_info.to_dict(),
                "chunks_processed": total_chunks,
            })
            
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            self.task_manager.fail_task(task_id, error_msg)
    
    def create_graph(self, name: str) -> str:
        """创建Zep图谱（公开方法）"""
        graph_id = f"mirofish_{uuid.uuid4().hex[:16]}"
        
        self.client.graph.create(
            graph_id=graph_id,
            name=name,
            description="MiroFish Social Simulation Graph"
        )
        
        return graph_id
    
    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        """设置图谱本体（公开方法）"""
        import warnings
        from typing import Optional
        from pydantic import Field
        from .graphiti_client.ontology import EntityModel, EntityText, EdgeModel
        
        # 抑制 Pydantic v2 关于 Field(default=None) 的警告
        # 这是 Zep SDK 要求的用法，警告来自动态类创建，可以安全忽略
        warnings.filterwarnings('ignore', category=UserWarning, module='pydantic')
        
        # Zep 保留名称，不能作为属性名
        RESERVED_NAMES = {'uuid', 'name', 'group_id', 'name_embedding', 'summary', 'created_at'}
        
        def safe_attr_name(attr_name: str) -> str:
            """将保留名称转换为安全名称"""
            if attr_name.lower() in RESERVED_NAMES:
                return f"entity_{attr_name}"
            return attr_name
        
        # 动态创建实体类型
        # F-3-1: 本体来自 LLM（不可信边界），且 resume/复用路径会直接喂入持久化本体而不再
        # 校验。任一 entity/attr/edge 缺 "name" 不能让整个 GRAPH 阶段崩溃——用 .get() 取名、
        # 跳过无名条目，并 per-item try/except 隔离单个坏类型（与 seed_actors 的逐项保护一致）。
        entity_types = {}
        for entity_def in ontology.get("entity_types", []):
            name = entity_def.get("name")
            if not name:
                logger.warning("skipping entity_def without name: %r", entity_def)  # F-3-1
                continue
            try:
                description = entity_def.get("description", f"A {name} entity.")

                # 创建属性字典和类型注解（Pydantic v2 需要）
                attrs = {"__doc__": description}
                annotations = {}

                for attr_def in entity_def.get("attributes", []):
                    raw_attr_name = attr_def.get("name")
                    if not raw_attr_name:  # F-3-1: 跳过无名属性而非 KeyError
                        continue
                    attr_name = safe_attr_name(raw_attr_name)  # 使用安全名称
                    attr_desc = attr_def.get("description", attr_name)
                    # Zep API 需要 Field 的 description，这是必需的
                    attrs[attr_name] = Field(description=attr_desc, default=None)
                    annotations[attr_name] = Optional[EntityText]  # 类型注解

                attrs["__annotations__"] = annotations

                # 动态创建类
                entity_class = type(name, (EntityModel,), attrs)
                entity_class.__doc__ = description
                entity_types[name] = entity_class
            except Exception as e:  # F-3-1: 单个坏类型不得中断整批
                logger.warning("skipping malformed entity type %s: %s", name, e)
                continue

        # 动态创建边类型
        edge_definitions = {}
        for edge_def in ontology.get("edge_types", []):
            name = edge_def.get("name")
            if not name:
                logger.warning("skipping edge_def without name: %r", edge_def)  # F-3-1
                continue
            try:
                description = edge_def.get("description", f"A {name} relationship.")

                # 创建属性字典和类型注解
                attrs = {"__doc__": description}
                annotations = {}

                for attr_def in edge_def.get("attributes", []):
                    raw_attr_name = attr_def.get("name")
                    if not raw_attr_name:  # F-3-1: 跳过无名属性而非 KeyError
                        continue
                    attr_name = safe_attr_name(raw_attr_name)  # 使用安全名称
                    attr_desc = attr_def.get("description", attr_name)
                    # Zep API 需要 Field 的 description，这是必需的
                    attrs[attr_name] = Field(description=attr_desc, default=None)
                    annotations[attr_name] = Optional[str]  # 边属性用str类型

                attrs["__annotations__"] = annotations

                # 动态创建类
                class_name = ''.join(word.capitalize() for word in name.split('_'))
                edge_class = type(class_name, (EdgeModel,), attrs)
                edge_class.__doc__ = description

                # 构建source_targets
                source_targets = []
                for st in edge_def.get("source_targets", []):
                    source_targets.append(
                        EntityEdgeSourceTarget(
                            source=st.get("source", "Entity"),
                            target=st.get("target", "Entity")
                        )
                    )

                if source_targets:
                    edge_definitions[name] = (edge_class, source_targets)
            except Exception as e:  # F-3-1: 单个坏边类型不得中断整批
                logger.warning("skipping malformed edge type %s: %s", name, e)
                continue
        
        # 调用Zep API设置本体
        if entity_types or edge_definitions:
            self.client.graph.set_ontology(
                graph_ids=[graph_id],
                entities=entity_types if entity_types else None,
                edges=edge_definitions if edge_definitions else None,
            )
    
    def seed_actors(
        self,
        graph_id: str,
        actors: Optional[Dict[str, Any]],
        valid_at: Any = None,
    ) -> int:
        """T2.2: 在文本抽取前，把研究确认的 actors + relationships 直接种入图谱。

        每条 ``relationships[]`` 写成一条 typed 边（``type`` 即边名）；落单的高信号 actor
        写成 ``IS_A``→类型 的节点（让没有关系边的关键 actor 也进图谱）。``add_triplet`` 按
        名字+embedding dedup，所以后续文本抽取会「富化」这些种子节点而非重复创建。
        返回写入的边数。幂等：重复种同一三元组不会产生重复（T2.7 依赖此性质）。
        """
        # W10-COST: 登记本图的 cast 词表（names+aliases+关系端点，归一化），供
        # add_text_batches 的 cast 相关性预过滤使用。登记失败绝不影响种子写入；
        # __new__ 构造的实例（测试/工具路径）无 _cast_chunk_terms 时就地补建。
        try:
            registry = getattr(self, "_cast_chunk_terms", None)
            if registry is None:
                registry = {}
                self._cast_chunk_terms = registry
            registry[graph_id] = cast_filter_terms_from_actors(actors)
        except Exception as exc:  # noqa: BLE001 — 词表是过滤增强，绝不阻断种子
            logger.debug("[%s] cast filter term registration failed: %s", graph_id, exc)
        if _current_actor_seed_contract(actors):
            return self._seed_actor_intelligence_v1(
                graph_id,
                actors,
                valid_at=valid_at,
            )
        rows = extract_actor_rows(actors)
        rels = extract_relationship_rows(actors)
        if not rows and not rels:
            return 0
        # C8（ONTOLOGY 富 schema 开关）：控制是否把 archetype/simulation_tier/salience 与
        # 关系 valence/polarity 折进种子节点/边。默认开启；但所有新写入都另有「字段存在」
        # 守卫，故无新字段的旧档案即便开关为真也逐字节不变（degrade-safe）。
        rich_schema = getattr(Config, "ONTOLOGY_RICH_SCHEMA", True)
        label = {a["name"]: ACTOR_TYPE_TO_LABEL.get(str(a.get("type") or ""), "Entity") for a in rows}
        # 每个 actor 的一句话消歧 summary（KG cookbook：描述是实体解析的关键信号）。
        # 优先用研究给的 description，回退到 role；喂给 add_triplet 的端点 summary，
        # graphiti 的 LLM 去重器读 node.summary 来区分同名异体。
        summ = {a["name"]: (str(a.get("description") or a.get("role") or "").strip()[:200]) for a in rows}
        n = 0
        seeded_names: set = set()
        for r in rels:
            typ = str(r.get("type", "")).upper()
            etype = REL_EDGE_NAME.get(typ)
            if typ == "OTHER" or not etype:
                # OTHER / 未知类型：优先用研究给的 relation_label 清洗成具体边名（如
                # SUPPLIES/CO_INVESTS_IN_CAPACITY），保留语义；没有 label 才落到 RELATES_TO。
                # 绝不丢边（旧逻辑这里 continue，会静默丢弃所有非 7 类边）。
                rl = str(r.get("relation_label", "") or "").strip()
                sanitized = re.sub(r"[^0-9A-Za-z_]+", "_", rl).strip("_").upper() if rl else ""
                etype = sanitized or etype or "RELATES_TO"
            src, tgt = r.get("source"), r.get("target")
            # 把 sign/strength/grade 折进事实文本：边自带可检索的极性/强度/定级，无需改 Graphiti schema。
            fact = str(r.get("basis") or f"{src} {etype} {tgt}")
            sign, strength, grade = r.get("sign"), r.get("strength"), r.get("grade")
            # R2-KG-3: fold the relationship's transmission LAG into the fact text so
            # the seeded edge carries a retrievable lag the multi-hop traversal can
            # surface+sum (a causal spine needs "how long until it propagates", not
            # just "does it"). Only appended when the research row carries it, so
            # rows without lag stay byte-identical.
            lag = r.get("lag")
            extra = [p for p in (
                (f"sign={sign}" if sign else None),
                (f"strength={strength}" if strength else None),
                (f"grade={grade}" if grade else None),
                (f"lag={lag}" if lag not in (None, "") else None),
            ) if p]
            # C8（ONTOLOGY 富 schema）：把关系的价(valence)/极性(polarity)也折进事实文本，
            # 让种子边自带「盟友 != 对手 != 供应商」的可检索语义。仅在关系行**显式携带**
            # valence/polarity 时才追加——绝不据 type 反推，以保证旧档案（无新字段）的种子
            # 事实文本与今天逐字节一致（gated by ONTOLOGY_RICH_SCHEMA）。
            if rich_schema and isinstance(r, dict) and \
                    (r.get("valence") is not None or r.get("polarity") is not None):
                extra.append(f"valence={relation_valence(r)}")
                extra.append(f"polarity={relation_polarity(r):.2f}")
            if extra:
                fact = f"{fact}（{'，'.join(extra)}）"
            try:
                self.client.graph.add_triplet(
                    graph_id, src, etype, tgt,
                    fact,
                    valid_at=valid_at,
                    source_label=label.get(src, "Entity"),
                    target_label=label.get(tgt, "Entity"),
                    source_summary=summ.get(src, ""),
                    target_summary=summ.get(tgt, ""),
                )
                n += 1
                seeded_names |= {src, tgt}
            except Exception as e:  # one bad edge must never abort seeding
                logger.warning("[%s] seed edge skipped (%s-%s-%s): %s", graph_id, src, etype, tgt, e)
        for a in rows:  # isolated high-signal actors (no relationship edge)
            name = a["name"]
            if name in seeded_names:
                continue
            try:
                # F-3-3: add_triplet 会把 target 物化为一个节点；过去 target_label 缺省为
                # "Entity"，使类型字符串（"Person"/"Organization"…）成了仅带 "Entity" 标签的
                # 孤儿污染节点。这里显式给 target_label 打上正确的实体类型标签，让该合成端至少
                # 是一个合法分型的概念节点（彻底去除 IS_A 端节点需 runtime.add_node 节点级 upsert，
                # 跨文件改动，见 skipped）。
                actor_type = a.get("type") or "Entity"
                # 把 role/stance/influence/动机/记忆摘录折进种子节点事实，让规范 actor 节点
                # 自带调研属性，而不是只挂一个空壳 role 字符串。
                fact = str(a.get("role") or name)
                brief = actor_briefing(a, max_memory_chars=300)
                if brief:
                    body = brief.split("\n", 1)[-1].replace("\n", "；").strip()
                    if body:
                        fact = f"{fact}；{body}" if fact else body
                # C8（ONTOLOGY 富 schema）：把本体分类属性 archetype/simulation_tier/salience
                # 作为「节点属性」折进种子节点事实文本（旧版未封存路径不提供 attributes，
                # 故沿用本文件既有「把调研属性折进 fact」的范式）。属性键经 safe_attr_name 规范，
                # 避开 Zep 保留字。仅在 actor **显式携带**这些字段时追加，否则逐字节不变。
                node_attrs: List[str] = []
                if rich_schema and isinstance(a, dict):
                    if str(a.get("archetype", "") or "").strip():
                        node_attrs.append(f"{safe_attr_name('archetype')}={entity_archetype(a)}")
                    if a.get("simulation_tier") is not None:
                        node_attrs.append(
                            f"{safe_attr_name('simulation_tier')}={entity_simulation_tier(a)}")
                    if a.get("salience") is not None:
                        node_attrs.append(
                            f"{safe_attr_name('salience')}={salience_score(a):.2f}")
                if node_attrs:
                    fact = f"{fact}（{'，'.join(node_attrs)}）" if fact else \
                        "（" + "，".join(node_attrs) + "）"
                self.client.graph.add_triplet(
                    graph_id, name, "IS_A", actor_type,
                    fact,
                    valid_at=valid_at,
                    source_label=label.get(name, "Entity"),
                    target_label=ACTOR_TYPE_TO_LABEL.get(str(a.get("type") or ""), "Entity"),
                    source_summary=summ.get(name, ""),
                )
                n += 1
            except Exception as e:
                logger.warning("[%s] seed node skipped (%s): %s", graph_id, name, e)
        # 别名桥（KG cookbook 别名解析）：为带 aliases 的 actor 显式播一条 ALSO_KNOWN_AS 边，
        # 让后续 prose 抽取里以别名出现的提及能去重到同一规范节点，而非另起孤儿节点。
        for a in rows:
            name = a["name"]
            aliases = a.get("aliases")
            if not isinstance(aliases, list):
                continue
            for al in aliases:
                if not (isinstance(al, str) and al.strip()):
                    continue
                if normalize_name(al) == normalize_name(name):
                    continue
                try:
                    self.client.graph.add_triplet(
                        graph_id, name, "ALSO_KNOWN_AS", al,
                        f"{name} 亦称 {al}",
                        valid_at=valid_at,
                        source_label=label.get(name, "Entity"),
                        target_label=label.get(name, "Entity"),
                        source_summary=summ.get(name, ""),
                        target_summary=summ.get(name, ""),
                    )
                    n += 1
                except Exception as e:
                    logger.warning("[%s] seed alias skipped (%s~%s): %s", graph_id, name, al, e)
        return n

    def _seed_actor_intelligence_v1(
        self,
        graph_id: str,
        actors: Dict[str, Any],
        *,
        valid_at: Any = None,
    ) -> int:
        plan = self._prepare_actor_intelligence_v1_seed(
            graph_id,
            actors,
            valid_at=valid_at,
        )
        operations = plan["operations"]
        expected_count = len(operations)
        written = 0
        for operation_id, args, kwargs in operations:
            try:
                edge_uuid = self.client.graph.add_triplet(*args, **kwargs)
            except Exception as exc:
                raise ActorGraphSeedError(
                    f"required current actor graph seed failed: {operation_id}: {exc}"
                ) from exc
            if not edge_uuid:
                raise ActorGraphSeedError(
                    f"required current actor graph seed returned no edge: {operation_id}"
                )
            written += 1
        if written != expected_count:
            raise ActorGraphSeedError(
                f"current actor graph seed count mismatch: {written}/{expected_count}"
            )
        self.last_actor_graph_seed_manifest = plan["manifest"]
        return written

    def validate_actor_graph_seed_readback(
        self,
        graph_id: str,
        manifest: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Strictly validate the physical seed after build, resolve, or reuse.

        Alias bridge nodes may be intentionally collapsed into their canonical
        seeded actor by entity resolution.  Every actor/type node, actor identity
        edge, and canonical relationship edge remains exact; relationship UUIDs,
        endpoints, and provenance attributes are never optional.
        """
        if not isinstance(manifest, dict):
            raise ActorGraphSeedError("actor graph seed manifest is not an object")
        supplied_digest = str(manifest.get("manifest_sha256") or "")
        digest_payload = {
            key: value for key, value in manifest.items()
            if key != "manifest_sha256"
        }
        expected_digest = _canonical_sha256(digest_payload)
        if supplied_digest != expected_digest:
            raise ActorGraphSeedError("actor graph seed manifest_sha256 mismatch")
        if manifest.get("graph_id") != graph_id:
            raise ActorGraphSeedError("actor graph seed manifest graph_id mismatch")
        if manifest.get("strict") is False:
            return {
                "schema_version": _ACTOR_GRAPH_SEED_READBACK_VERSION,
                "status": "ok",
                "strict": False,
                "graph_id": graph_id,
                "manifest_sha256": supplied_digest,
                "expected_counts": {},
                "observed_counts": {},
            }
        if manifest.get("schema_version") != _ACTOR_GRAPH_SEED_MANIFEST_VERSION:
            raise ActorGraphSeedError("unsupported actor graph seed manifest schema")

        try:
            state = self.client.graph.actor_graph_seed_state(graph_id=graph_id)
        except Exception as exc:
            raise ActorGraphSeedError(
                f"actor graph seed readback failed: {exc}"
            ) from exc
        if not isinstance(state, dict):
            raise ActorGraphSeedError("actor graph seed readback is not an object")
        observed_nodes = state.get("nodes")
        observed_edges = state.get("edges")
        if not isinstance(observed_nodes, list) or not isinstance(observed_edges, list):
            raise ActorGraphSeedError(
                "actor graph seed readback lacks node/edge lists"
            )

        errors: List[str] = []
        node_rows: Dict[str, List[Dict[str, Any]]] = {}
        edge_rows: Dict[str, List[Dict[str, Any]]] = {}
        for row in observed_nodes:
            if not isinstance(row, dict) or not row.get("uuid"):
                errors.append("observed_seed_node_invalid")
                continue
            node_rows.setdefault(str(row["uuid"]), []).append(row)
        for row in observed_edges:
            if not isinstance(row, dict) or not row.get("uuid"):
                errors.append("observed_seed_edge_invalid")
                continue
            edge_rows.setdefault(str(row["uuid"]), []).append(row)
        for node_uuid, rows in node_rows.items():
            if len(rows) != 1:
                errors.append(f"duplicate_seed_node_uuid:{node_uuid}")
        for edge_uuid, rows in edge_rows.items():
            if len(rows) != 1:
                errors.append(f"duplicate_seed_edge_uuid:{edge_uuid}")

        expected_nodes = {
            str(row.get("uuid") or ""): row
            for row in (manifest.get("seed_nodes") or [])
            if isinstance(row, dict) and row.get("uuid")
        }
        expected_edges = {
            str(row.get("uuid") or ""): row
            for row in (manifest.get("seed_edges") or [])
            if isinstance(row, dict) and row.get("uuid")
        }
        if len(expected_nodes) != len(manifest.get("seed_nodes") or []):
            errors.append("manifest_seed_node_uuid_collision")
        if len(expected_edges) != len(manifest.get("seed_edges") or []):
            errors.append("manifest_seed_edge_uuid_collision")

        actor_by_id = {
            row["actor_id"]: row
            for row in (manifest.get("actors") or [])
            if isinstance(row, dict) and row.get("actor_id")
        }
        alias_by_node_uuid = {
            row["node_uuid"]: row
            for row in (manifest.get("aliases") or [])
            if isinstance(row, dict) and row.get("node_uuid")
        }
        collapsed_alias_nodes: set[str] = set()
        collapsed_alias_edges: set[str] = set()

        def validate_required_attributes(
            kind: str,
            identity: str,
            expected: Dict[str, Any],
            observed: Dict[str, Any],
        ) -> None:
            attrs = observed.get("attributes")
            attrs = attrs if isinstance(attrs, dict) else {}
            for key, value in (expected.get("required_attributes") or {}).items():
                if attrs.get(key) != value:
                    errors.append(f"{kind}_attribute_mismatch:{identity}:{key}")

        for node_uuid, expected in expected_nodes.items():
            observed_group = node_rows.get(node_uuid) or []
            if expected.get("seed_kind") == "actor_alias" and not observed_group:
                alias = alias_by_node_uuid.get(node_uuid) or {}
                actor = actor_by_id.get(alias.get("actor_id")) or {}
                actor_rows = node_rows.get(str(actor.get("node_uuid") or "")) or []
                actor_attrs = (
                    actor_rows[0].get("attributes")
                    if len(actor_rows) == 1 and isinstance(actor_rows[0], dict)
                    else {}
                )
                try:
                    aliases = json.loads(str(actor_attrs.get("aliases_json") or "[]"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    aliases = []
                if alias.get("alias") not in aliases:
                    errors.append(f"collapsed_alias_not_preserved:{node_uuid}")
                else:
                    collapsed_alias_nodes.add(node_uuid)
                    collapsed_alias_edges.add(str(alias.get("edge_uuid") or ""))
                continue
            if len(observed_group) != 1:
                errors.append(f"seed_node_missing_or_duplicate:{node_uuid}")
                continue
            observed = observed_group[0]
            if observed.get("name") != expected.get("name"):
                errors.append(f"seed_node_name_mismatch:{node_uuid}")
            required_labels = set(expected.get("required_labels") or [])
            if not required_labels.issubset(set(observed.get("labels") or [])):
                errors.append(f"seed_node_labels_mismatch:{node_uuid}")
            summary_sha = hashlib.sha256(
                str(observed.get("summary") or "").encode("utf-8")
            ).hexdigest()
            if summary_sha != expected.get("summary_sha256"):
                errors.append(f"seed_node_summary_mismatch:{node_uuid}")
            validate_required_attributes("seed_node", node_uuid, expected, observed)

        for edge_uuid, expected in expected_edges.items():
            observed_group = edge_rows.get(edge_uuid) or []
            if edge_uuid in collapsed_alias_edges and not observed_group:
                continue
            if len(observed_group) != 1:
                errors.append(f"seed_edge_missing_or_duplicate:{edge_uuid}")
                continue
            observed = observed_group[0]
            for key in ("name", "source_node_uuid", "target_node_uuid"):
                if observed.get(key) != expected.get(key):
                    errors.append(f"seed_edge_{key}_mismatch:{edge_uuid}")
            fact_sha = hashlib.sha256(
                str(observed.get("fact") or "").encode("utf-8")
            ).hexdigest()
            if fact_sha != expected.get("fact_sha256"):
                errors.append(f"seed_edge_fact_mismatch:{edge_uuid}")
            validate_required_attributes("seed_edge", edge_uuid, expected, observed)

        allowed_node_uuids = set(expected_nodes) - collapsed_alias_nodes
        unexpected_nodes = set(node_rows) - allowed_node_uuids
        if unexpected_nodes:
            errors.append(
                "unexpected_seed_node_uuids:" + ",".join(sorted(unexpected_nodes))
            )
        allowed_edge_uuids = set(expected_edges) - collapsed_alias_edges
        unexpected_edges = set(edge_rows) - allowed_edge_uuids
        if unexpected_edges:
            errors.append(
                "unexpected_seed_edge_uuids:" + ",".join(sorted(unexpected_edges))
            )

        relationship_ids: Dict[str, List[str]] = {}
        for edge_uuid, rows in edge_rows.items():
            for row in rows:
                attrs = row.get("attributes")
                if not isinstance(attrs, dict) or attrs.get("seed_kind") != "relationship":
                    continue
                relationship_ids.setdefault(
                    str(attrs.get("relationship_id") or ""), []
                ).append(edge_uuid)
        for relationship_id, uuids in relationship_ids.items():
            if not relationship_id or len(uuids) != 1:
                errors.append(
                    f"duplicate_or_empty_relationship_id:{relationship_id}"
                )

        if errors:
            raise ActorGraphSeedError(
                "actor graph seed readback mismatch: " + "; ".join(errors)
            )
        expected_counts = dict(manifest.get("expected_counts") or {})
        return {
            "schema_version": _ACTOR_GRAPH_SEED_READBACK_VERSION,
            "status": "ok",
            "strict": True,
            "graph_id": graph_id,
            "manifest_sha256": supplied_digest,
            "expected_counts": expected_counts,
            "observed_counts": {
                "seed_nodes": len(observed_nodes),
                "seed_edges": len(observed_edges),
                "collapsed_alias_nodes": len(collapsed_alias_nodes),
                "collapsed_alias_edges": len(collapsed_alias_edges),
                "relationship_edges": len(relationship_ids),
            },
        }

    def _prepare_actor_intelligence_v1_seed(
        self,
        graph_id: str,
        actors: Dict[str, Any],
        *,
        valid_at: Any = None,
    ) -> Dict[str, Any]:
        """Prepare an admitted actor-intelligence/v1 seed without graph I/O.

        It preflights the complete sealed roster and returns both the exact write
        plan and immutable readback manifest.  Seeding and parent reuse checks
        therefore derive identity from one implementation rather than parallel
        projections that can drift.
        """
        raw_rows = actors.get("actors")
        if not isinstance(raw_rows, list) or not raw_rows:
            raise ActorGraphSeedError(
                "current actor-intelligence graph seed has zero actors"
            )
        if any(not isinstance(row, dict) for row in raw_rows):
            raise ActorGraphSeedError(
                "current actor-intelligence graph seed contains a non-object actor"
            )
        contract = actors.get("actor_intelligence_contract")
        contract = contract if isinstance(contract, dict) else {}
        if "actor_count" in contract and contract.get("actor_count") != len(raw_rows):
            raise ActorGraphSeedError(
                "current actor-intelligence actor_count does not match roster"
            )

        actor_records: Dict[str, Dict[str, Any]] = {}
        endpoint_index: Dict[str, str] = {}
        canonical_name_index: Dict[str, str] = {}
        claim_count = 0
        for row_index, actor in enumerate(raw_rows):
            actor_id = _strict_identity_text(
                actor.get("actor_id"), field=f"actors[{row_index}].actor_id"
            )
            name = _strict_identity_text(
                actor.get("name"), field=f"actors[{row_index}].name"
            )
            if actor_id in actor_records:
                raise ActorGraphSeedError(f"duplicate actor_id in seed: {actor_id}")
            name_key = normalize_name(name)
            if not name_key or name_key in canonical_name_index:
                raise ActorGraphSeedError(f"duplicate actor name in seed: {name}")
            actor_type = _strict_identity_text(
                actor.get("type") or "Entity",
                field=f"actors[{row_index}].type",
                max_chars=80,
            )
            claims = _source_bound_actor_claims(actor)
            claim_count += len(claims)
            aliases_raw = actor.get("aliases", [])
            if aliases_raw is None:
                aliases_raw = []
            if not isinstance(aliases_raw, list):
                raise ActorGraphSeedError(
                    f"current actor seed aliases are not a list: {actor_id}"
                )
            aliases: List[str] = []
            seen_aliases: set[str] = set()
            for alias_index, alias_raw in enumerate(aliases_raw):
                if not isinstance(alias_raw, str):
                    raise ActorGraphSeedError(
                        f"current actor seed alias is not text: "
                        f"actors[{row_index}].aliases[{alias_index}]"
                    )
                alias = _strict_identity_text(
                    alias_raw,
                    field=f"actors[{row_index}].aliases[{alias_index}]",
                )
                alias_key = normalize_name(alias)
                if not alias_key or alias_key == name_key or alias_key in seen_aliases:
                    continue
                seen_aliases.add(alias_key)
                aliases.append(alias)
            projection = {
                "seed_schema_version": _ACTOR_GRAPH_SEED_SCHEMA_VERSION,
                "kind": "actor",
                "actor_id": actor_id,
                "name": name,
                "aliases": aliases,
                "type": actor_type,
                "simulation_tier": actor.get("simulation_tier"),
                "archetype": actor.get("archetype"),
                "canonical_claims": claims,
            }
            summary = _delimited_seed_record(
                f"actor graph seed {actor_id}", projection
            )
            attrs = {
                "seed_schema_version": _ACTOR_GRAPH_SEED_SCHEMA_VERSION,
                "seed_kind": "actor",
                "actor_id": actor_id,
                "actor_name": name,
                # Keep the established synthetic-entity lookup keys as aliases
                # while exposing the canonical v1 names above.
                "dossier_actor_id": actor_id,
                "dossier_actor_name": name,
                "actor_type": actor_type,
                "aliases_json": _canonical_json(aliases),
                "canonical_claim_count": len(claims),
                "canonical_claims_json": _canonical_json(claims),
                "canonical_claims_sha256": _canonical_sha256(claims),
                "actor_intelligence_sha256": _canonical_sha256(
                    actor.get("intelligence")
                ),
                "actor_seed_record_json": _canonical_json(projection),
                "seed_record_sha256": _canonical_sha256(projection),
                "source_report_sha256": str(contract.get("report_sha256") or ""),
                "source_dossier_sha256": str(contract.get("dossier_sha256") or ""),
                "source_sources_sha256": str(contract.get("sources_sha256") or ""),
            }
            actor_records[actor_id] = {
                "actor_id": actor_id,
                "name": name,
                "name_key": name_key,
                "type": actor_type,
                "label": ACTOR_TYPE_TO_LABEL.get(actor_type, "Entity"),
                "aliases": aliases,
                "summary": summary,
                "attributes": attrs,
            }
            canonical_name_index[name_key] = actor_id

        if (
            "claim_projection_count" in contract
            and contract.get("claim_projection_count") != claim_count
        ):
            raise ActorGraphSeedError(
                "current actor-intelligence claim count does not match contract"
            )

        # Canonical names win first; aliases may resolve an endpoint only when
        # they do not collide with a different sealed identity.
        endpoint_index.update(canonical_name_index)
        for actor_id, record in actor_records.items():
            for alias in record["aliases"]:
                alias_key = normalize_name(alias)
                existing = endpoint_index.get(alias_key)
                if existing is not None and existing != actor_id:
                    raise ActorGraphSeedError(
                        f"ambiguous actor alias in current seed: {alias}"
                    )
                endpoint_index[alias_key] = actor_id

        raw_relationships = actors.get("relationships", [])
        if raw_relationships is None:
            raw_relationships = []
        if not isinstance(raw_relationships, list) or any(
            not isinstance(row, dict) for row in raw_relationships
        ):
            raise ActorGraphSeedError(
                "current actor-intelligence relationships are not a list of objects"
            )
        if (
            "relationship_count" in contract
            and contract.get("relationship_count") != len(raw_relationships)
        ):
            raise ActorGraphSeedError(
                "current actor-intelligence relationship_count does not match rows"
            )

        # Each tuple is (human-readable identity, positional args, keyword args).
        # Building this complete operation list is the preflight: no malformed
        # actor/claim/relationship can leave a half-seeded graph.
        operations: List[tuple[str, tuple[Any, ...], Dict[str, Any]]] = []
        for actor_id, record in actor_records.items():
            type_record = {
                "seed_schema_version": _ACTOR_GRAPH_SEED_SCHEMA_VERSION,
                "kind": "entity_type",
                "name": record["type"],
            }
            type_block = _delimited_seed_record(
                "actor graph entity type", type_record, max_chars=2000
            )
            edge_attrs = {
                "seed_schema_version": _ACTOR_GRAPH_SEED_SCHEMA_VERSION,
                "seed_kind": "actor_identity",
                "actor_id": actor_id,
                "seed_record_sha256": record["attributes"]["seed_record_sha256"],
            }
            operations.append((
                f"actor:{actor_id}",
                (graph_id, record["name"], "IS_A", record["type"], record["summary"]),
                {
                    "valid_at": valid_at,
                    "source_label": record["label"],
                    "target_label": record["label"],
                    "source_summary": record["summary"],
                    "target_summary": type_block,
                    "source_attributes": record["attributes"],
                    "target_attributes": {
                        "seed_schema_version": _ACTOR_GRAPH_SEED_SCHEMA_VERSION,
                        "seed_kind": "entity_type",
                        "entity_type": record["type"],
                    },
                    "edge_attributes": edge_attrs,
                    "source_uuid": _seed_uuid(graph_id, "actor", actor_id),
                    "target_uuid": _seed_uuid(
                        graph_id, "entity_type", record["type"]
                    ),
                    "edge_uuid": _seed_uuid(graph_id, "actor_identity", actor_id),
                    "source_model_text": record["summary"],
                    "target_model_text": type_block,
                    "fact_model_text": record["summary"],
                    "deterministic_seed": True,
                },
            ))
            for alias in record["aliases"]:
                alias_record = {
                    "seed_schema_version": _ACTOR_GRAPH_SEED_SCHEMA_VERSION,
                    "kind": "actor_alias",
                    "actor_id": actor_id,
                    "canonical_name": record["name"],
                    "alias": alias,
                }
                alias_block = _delimited_seed_record(
                    f"actor alias seed {actor_id}", alias_record, max_chars=3000
                )
                alias_key = normalize_name(alias)
                operations.append((
                    f"alias:{actor_id}:{alias_key}",
                    (
                        graph_id,
                        record["name"],
                        "ALSO_KNOWN_AS",
                        alias,
                        alias_block,
                    ),
                    {
                        "valid_at": valid_at,
                        "source_label": record["label"],
                        "target_label": record["label"],
                        "source_summary": record["summary"],
                        "target_summary": alias_block,
                        "source_attributes": record["attributes"],
                        "target_attributes": {
                            "seed_schema_version": _ACTOR_GRAPH_SEED_SCHEMA_VERSION,
                            "seed_kind": "actor_alias",
                            "actor_id": actor_id,
                            "dossier_actor_id": actor_id,
                            "canonical_name": record["name"],
                            "alias": alias,
                        },
                        "edge_attributes": {
                            "seed_schema_version": _ACTOR_GRAPH_SEED_SCHEMA_VERSION,
                            "seed_kind": "actor_alias",
                            "actor_id": actor_id,
                            "alias": alias,
                            "seed_record_sha256": _canonical_sha256(alias_record),
                        },
                        "source_uuid": _seed_uuid(graph_id, "actor", actor_id),
                        "target_uuid": _seed_uuid(
                            graph_id, "actor_alias", f"{actor_id}:{alias_key}"
                        ),
                        "edge_uuid": _seed_uuid(
                            graph_id, "actor_alias_edge", f"{actor_id}:{alias_key}"
                        ),
                        "source_model_text": record["summary"],
                        "target_model_text": alias_block,
                        "fact_model_text": alias_block,
                        "deterministic_seed": True,
                    },
                ))

        seen_relationship_ids: set[str] = set()
        seen_relationship_edge_uuids: set[str] = set()
        for relationship_index, relationship in enumerate(raw_relationships):
            source_key = normalize_name(str(relationship.get("source") or ""))
            target_key = normalize_name(str(relationship.get("target") or ""))
            source_actor_id = endpoint_index.get(source_key)
            target_actor_id = endpoint_index.get(target_key)
            if source_actor_id is None or target_actor_id is None:
                raise ActorGraphSeedError(
                    f"relationship endpoint is not in sealed roster: {relationship_index}"
                )
            supplied_source_id = str(
                relationship.get("source_actor_id") or source_actor_id
            )
            supplied_target_id = str(
                relationship.get("target_actor_id") or target_actor_id
            )
            if (
                supplied_source_id != source_actor_id
                or supplied_target_id != target_actor_id
            ):
                raise ActorGraphSeedError(
                    f"relationship actor identity mismatch: {relationship_index}"
                )
            source = actor_records[source_actor_id]
            target = actor_records[target_actor_id]
            relation_type = _strict_identity_text(
                str(relationship.get("type") or "OTHER").upper(),
                field=f"relationships[{relationship_index}].type",
                max_chars=64,
            )
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", relation_type):
                raise ActorGraphSeedError(
                    f"relationship type is not canonical: {relationship_index}"
                )
            edge_type = REL_EDGE_NAME.get(relation_type)
            if relation_type == "OTHER" or not edge_type:
                relation_label = _strict_identity_text(
                    relationship.get("relation_label") or "RELATES_TO",
                    field=f"relationships[{relationship_index}].relation_label",
                    max_chars=64,
                )
                edge_type = re.sub(
                    r"[^0-9A-Za-z_]+", "_", relation_label
                ).strip("_").upper()
                if not edge_type:
                    raise ActorGraphSeedError(
                        f"relationship label is empty: {relationship_index}"
                    )
            claim = str(
                relationship.get("basis") or relationship.get("claim") or ""
            ).strip()
            raw_source_refs = relationship.get("source_refs")
            if not isinstance(raw_source_refs, list):
                raise ActorGraphSeedError(
                    f"relationship source_refs are not a list: {relationship_index}"
                )
            source_refs = [
                str(item).strip()
                for item in raw_source_refs
                if isinstance(item, str) and item.strip()
            ]
            source_support = _validated_source_support(
                relationship.get("source_support"),
                location=f"relationship[{relationship_index}]",
            )
            if (
                not claim
                or not source_refs
            ):
                raise ActorGraphSeedError(
                    f"relationship claim is not canonical and source-bound: {relationship_index}"
                )
            relationship_projection = {
                "seed_schema_version": _ACTOR_GRAPH_SEED_SCHEMA_VERSION,
                "kind": "relationship",
                "source_actor_id": source_actor_id,
                "target_actor_id": target_actor_id,
                "source": source["name"],
                "target": target["name"],
                "type": relation_type,
                "relation_label": str(relationship.get("relation_label") or ""),
                "direction": str(
                    relationship.get("direction") or "source_to_target"
                ),
                "claim": claim,
                "claim_id": str(relationship.get("claim_id") or ""),
                "claim_sha256": str(relationship.get("claim_sha256") or ""),
                "evidence_type": str(relationship.get("evidence_type") or ""),
                "claim_valid_at": str(
                    relationship.get("claim_valid_at")
                    or relationship.get("as_of_date")
                    or ""
                ),
                "horizon": str(relationship.get("horizon") or ""),
                "status": str(relationship.get("status") or ""),
                "confidence": str(relationship.get("confidence") or ""),
                "source_refs": source_refs,
                "source_support": source_support,
                "qualifiers": relationship.get("qualifiers") or {},
            }
            causal_attributes = _canonical_causal_attributes(
                relationship,
                location=f"relationship[{relationship_index}]",
            )
            relationship_projection["causal_attributes"] = causal_attributes
            relationship_projection["causal_tokens"] = (
                "，".join(
                    f"{key}={value}" for key, value in causal_attributes.items()
                )
                + ("，" if causal_attributes else "")
            )
            if not re.fullmatch(
                r"[0-9a-f]{64}", relationship_projection["claim_sha256"]
            ) or not relationship_projection["claim_id"]:
                raise ActorGraphSeedError(
                    f"relationship claim identity is not sealed: {relationship_index}"
                )
            identity_payload = {
                "source_actor_id": source_actor_id,
                "target_actor_id": target_actor_id,
                "type": relation_type,
                "relation_label": relationship_projection["relation_label"],
                "claim_sha256": relationship_projection["claim_sha256"],
                "causal_attributes": causal_attributes,
            }
            expected_relationship_id = (
                "relation_" + _canonical_sha256(identity_payload)[:20]
            )
            relationship_id = str(relationship.get("relationship_id") or "")
            if relationship_id and relationship_id != expected_relationship_id:
                raise ActorGraphSeedError(
                    f"relationship_id is not canonical: {relationship_index}"
                )
            relationship_id = relationship_id or expected_relationship_id
            relationship_edge_uuid = _seed_uuid(
                graph_id, "relationship", relationship_id
            )
            if relationship_id in seen_relationship_ids:
                raise ActorGraphSeedError(
                    f"duplicate relationship_id in current seed: {relationship_id}"
                )
            if relationship_edge_uuid in seen_relationship_edge_uuids:
                raise ActorGraphSeedError(
                    "duplicate relationship edge UUID in current seed: "
                    f"{relationship_edge_uuid}"
                )
            seen_relationship_ids.add(relationship_id)
            seen_relationship_edge_uuids.add(relationship_edge_uuid)
            relationship_projection["relationship_id"] = relationship_id
            fact_block = _delimited_seed_record(
                f"relationship graph seed {relationship_id}",
                relationship_projection,
            )
            quotes = [
                row.get("supporting_quote")
                or row.get("exact_quote")
                or row.get("quote")
                or ""
                for row in source_support
            ]
            spans = [
                row.get("supporting_span") or row.get("span") or {}
                for row in source_support
            ]
            receipt_ids = [
                str(row.get("receipt_id") or "") for row in source_support
            ]
            content_hashes = [
                str(row.get("content_sha256") or "") for row in source_support
            ]
            quote_hashes = [
                hashlib.sha256(str(quote).encode("utf-8")).hexdigest()
                for quote in quotes
            ]
            edge_attrs = {
                "seed_schema_version": _ACTOR_GRAPH_SEED_SCHEMA_VERSION,
                "seed_kind": "relationship",
                "relationship_id": relationship_id,
                "source_actor_id": source_actor_id,
                "target_actor_id": target_actor_id,
                "source_actor_name": source["name"],
                "target_actor_name": target["name"],
                "relationship_type": relation_type,
                "relationship_label": relationship_projection["relation_label"],
                "direction": relationship_projection["direction"],
                "claim": claim,
                "claim_id": relationship_projection["claim_id"],
                "claim_sha256": relationship_projection["claim_sha256"],
                "evidence_type": relationship_projection["evidence_type"],
                "claim_valid_at": relationship_projection["claim_valid_at"],
                "horizon": relationship_projection["horizon"],
                "status": relationship_projection["status"],
                "confidence": relationship_projection["confidence"],
                "qualifiers_json": _canonical_json(
                    relationship_projection["qualifiers"]
                ),
                "causal_attributes_json": _canonical_json(causal_attributes),
                "source_refs_json": _canonical_json(source_refs),
                "source_support_json": _canonical_json(source_support),
                "supporting_quotes_json": _canonical_json(quotes),
                "supporting_quote_sha256s_json": _canonical_json(quote_hashes),
                "supporting_spans_json": _canonical_json(spans),
                "receipt_ids_json": _canonical_json(receipt_ids),
                "content_sha256s_json": _canonical_json(content_hashes),
                "relationship_record_json": _canonical_json(
                    relationship_projection
                ),
                "seed_record_sha256": _canonical_sha256(
                    relationship_projection
                ),
            }
            edge_attrs.update(causal_attributes)
            operations.append((
                f"relationship:{relationship_id}",
                (
                    graph_id,
                    source["name"],
                    edge_type,
                    target["name"],
                    fact_block,
                ),
                {
                    "valid_at": valid_at,
                    "source_label": source["label"],
                    "target_label": target["label"],
                    "source_summary": source["summary"],
                    "target_summary": target["summary"],
                    "source_attributes": source["attributes"],
                    "target_attributes": target["attributes"],
                    "edge_attributes": edge_attrs,
                    "source_uuid": _seed_uuid(
                        graph_id, "actor", source_actor_id
                    ),
                    "target_uuid": _seed_uuid(
                        graph_id, "actor", target_actor_id
                    ),
                    "edge_uuid": relationship_edge_uuid,
                    "source_model_text": source["summary"],
                    "target_model_text": target["summary"],
                    "fact_model_text": fact_block,
                    "deterministic_seed": True,
                },
            ))

        if not operations:
            raise ActorGraphSeedError(
                "current actor-intelligence graph seed has no required writes"
            )
        manifest = _actor_seed_manifest_from_plan(
            graph_id,
            contract,
            actor_records,
            operations,
        )
        return {"operations": operations, "manifest": manifest}

    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None,
        reference_time: Any = None,
    ) -> List[str]:
        """分批添加文本到图谱，返回所有 episode 的 uuid 列表。

        ``reference_time``（T2.3）会写入每个 chunk 的双时态 valid 锚点（缺省 = 落库时刻）。

        W10-COST（GRAPH_CAST_CHUNK_FILTER，默认开）：提交 LLM 抽取前先按 seed_actors
        登记的 cast 词表过滤——零 cast 命中的 chunk 不发任何 LLM 调用，计入
        ``skipped_cast_filter``（与 LLM 失败 skip 分开记账；``total``/``skip_ratio``
        只算实际提交的 chunk，故 GRAPH_MAX_SKIPPED_RATIO 告警分母随之收窄，不会把
        故意过滤误报成抽取降级）。
        """
        episode_uuids = []
        input_chunks = len(chunks)
        cast_filtered = 0
        if getattr(Config, "GRAPH_CAST_CHUNK_FILTER", True):
            terms = (getattr(self, "_cast_chunk_terms", None) or {}).get(graph_id) or []
            if terms:
                kept = [c for c in chunks if chunk_mentions_cast(c, terms)]
                if kept:
                    cast_filtered = input_chunks - len(kept)
                    chunks = kept
                    if cast_filtered:
                        logger.info(
                            "[%s] cast chunk filter: skipped %d/%d chunks with zero "
                            "cast mentions (%d cast terms), submitting %d to extraction",
                            graph_id, cast_filtered, input_chunks, len(terms), len(kept))
                elif input_chunks:
                    # 全量被过滤 = 词表与语料错配的信号（例如另一种文字/转写）。此时
                    # 绕过过滤、全量提交，绝不静默产出只剩种子的空图谱（degrade-safe）。
                    logger.warning(
                        "[%s] cast chunk filter matched 0/%d chunks (%d terms) — "
                        "suspected term/corpus mismatch, bypassing the filter",
                        graph_id, input_chunks, len(terms))
        total_chunks = len(chunks)
        failed_chunks = 0

        for i in range(0, total_chunks, batch_size):
            batch_chunks = chunks[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (total_chunks + batch_size - 1) // batch_size
            progress = (i + len(batch_chunks)) / total_chunks

            if progress_callback:
                progress_callback(
                    f"发送第 {batch_num}/{total_batches} 批数据 ({len(batch_chunks)} 块)...",
                    progress
                )
            
            # 构建episode数据（T2.3: 统一锚定 reference_time）
            episodes = [
                EpisodeData(data=chunk, type="text", reference_time=reference_time)
                for chunk in batch_chunks
            ]
            
            # 发送到Zep
            try:
                batch_result = self.client.graph.add_batch(
                    graph_id=graph_id,
                    episodes=episodes
                )

                # 收集返回的 episode uuid（add_batch 现已逐 episode 隔离失败：返回的条数
                # 可能少于发送条数，差额即被跳过的坏 chunk）。
                added = 0
                if batch_result and isinstance(batch_result, list):
                    for ep in batch_result:
                        ep_uuid = getattr(ep, 'uuid_', None) or getattr(ep, 'uuid', None)
                        if ep_uuid:
                            episode_uuids.append(ep_uuid)
                            added += 1
                failed_chunks += max(0, len(batch_chunks) - added)

                # T2.6: 本地 FalkorDB 同步落库，无需限流停顿（纯死延迟）。仅远程后端保留。
                if Config.GRAPHITI_REMOTE:
                    time.sleep(1)

            except Exception as e:
                # RESILIENCE: 一整批失败（罕见——单 episode 失败已在 add_batch 内隔离）也不再
                # 中断整个建图阶段：跳过该批、记账、继续。仅当「全部 chunk 都失败」时才在循环后
                # 显式硬失败（见下），避免静默产出空图谱。
                failed_chunks += len(batch_chunks)
                logger.warning("[%s] 批次 %d/%d 抽取失败，已跳过: %s",
                               graph_id, batch_num, total_batches, str(e)[:160])
                if progress_callback:
                    progress_callback(f"批次 {batch_num} 跳过(失败): {str(e)[:80]}", progress)
                continue

        # KG-5: 记账落到实例（不改签名/返回值）：只丢一条 WARNING 时，30% 语料丢失的图谱
        # 在 pipeline_state 里显示为全绿。编排器读 last_ingest_stats 即可量化 ingest 丢失
        # （MiniMax 内容过滤 422 + claude-cli 兜底耗尽是当前主要失败形态）。
        # Wave9-KG（抽取加固审计）：从 runtime 取走本图累计的 episode skip 原因分布
        # （schema_echo / schema_validation / rate_limit / …）与 skip 比例，一并入账——
        # 「为什么 48-60% 的 chunk 被跳过」从此可量化归因，而非只有一行 warning。
        skip_reasons: Dict[str, int] = {}
        try:
            from .graphiti_client.runtime import get_runtime

            skip_reasons = get_runtime().pop_ingest_skip_reasons(graph_id)
        except Exception as exc:  # noqa: BLE001 — 审计增强绝不影响建图主流程
            logger.debug("[%s] pop_ingest_skip_reasons failed: %s", graph_id, exc)
        # W10-COST: cast 预过滤计数以独立标签并入 skip 原因分布（与 schema_echo/
        # rate_limit 等 LLM 失败原因可区分）；``total``/``skip_ratio`` 只覆盖实际
        # 提交 LLM 的 chunk（编排器的 GRAPH_MAX_SKIPPED_RATIO 告警读 failed/total）。
        if cast_filtered:
            skip_reasons["skipped_cast_filter"] = (
                skip_reasons.get("skipped_cast_filter", 0) + cast_filtered)
        self.last_ingest_stats = {
            "total": total_chunks,
            "failed": failed_chunks,
            "succeeded": len(episode_uuids),
            "skip_ratio": round(failed_chunks / total_chunks, 4) if total_chunks else 0.0,
            "skip_reasons": skip_reasons,
            "input_chunks": input_chunks,
            "skipped_cast_filter": cast_filtered,
        }
        if skip_reasons:
            logger.warning("[%s] episode skip reasons: %s", graph_id,
                           ", ".join(f"{k}={v}" for k, v in sorted(skip_reasons.items())))

        # 硬护栏：所有文本块都抽取失败 → 不能静默产出空图谱（下游 prepare/模拟/报告会退化）。
        # 明确失败，给出可诊断信息（最常见诱因：模型 JSON 输出异常/回显 schema）。
        if total_chunks > 0 and not episode_uuids:
            raise ValueError(
                f"图谱构建失败：{total_chunks} 个文本块全部抽取失败（疑似模型 JSON 输出异常，"
                f"如回显 schema）。请检查 LLM 提供方/模型是否能稳定产出结构化 JSON。"
            )
        if failed_chunks:
            logger.warning("[%s] 建图完成但跳过了 %d/%d 个文本块（抽取失败）",
                           graph_id, failed_chunks, total_chunks)

        return episode_uuids
    
    def _wait_for_episodes(
        self,
        episode_uuids: List[str],
        progress_callback: Optional[Callable] = None,
        timeout: int = 600
    ):
        """T2.6: 本地 Graphiti 同步落库——``add_batch`` 返回时 episode 已抽取完毕，
        shim 的 ``episode.get`` 恒返回 ``processed=True``，原轮询循环是空转（且占用
        65→98% 进度带）。这里直接收尾，保留签名以兼容调用点；远程后端如需异步处理
        状态轮询可在此恢复（gate on ``Config.GRAPHITI_REMOTE``）。
        """
        if progress_callback:
            n = len(episode_uuids)
            progress_callback(
                f"文本块已处理完成（{n} 个）" if n else "无需等待（没有 episode）",
                1.0,
            )
    
    def build_communities(self, graph_id: str) -> List[Dict[str, Any]]:
        """T2.4: best-effort 社区发现（派系/联盟），返回 [{uuid,name,summary}]；失败返回 []。

        永不让社区发现的失败影响建图（catch+log）。重跑会清空旧社区（graphiti 语义）。
        """
        try:
            return self.client.graph.build_communities(graph_id) or []
        except Exception as e:
            logger.warning("[%s] build_communities skipped: %s", graph_id, e)
            return []

    def _get_graph_info(self, graph_id: str) -> GraphInfo:
        """获取图谱信息"""
        # 获取节点（分页）
        nodes = fetch_all_nodes(self.client, graph_id)

        # 获取边（分页）
        edges = fetch_all_edges(self.client, graph_id)

        # 统计实体类型
        entity_types = set()
        for node in nodes:
            if node.labels:
                for label in node.labels:
                    if label not in ["Entity", "Node"]:
                        entity_types.add(label)

        # KG cookbook 第4步：结构完整性检查。弱连通分量数（stdlib 并查集，无第三方依赖）
        # 是实体解析质量信号——分量数≈1 表示实体已良好合并；远多于预期 = 实体欠合并（重复孤点）。
        # 另统计度数最高的枢纽节点做 sanity check。纯内存计算，复用已取的 nodes/edges，无额外 IO。
        node_ids = {getattr(n, "uuid_", None) for n in nodes}
        node_ids.discard(None)
        parent: Dict[Any, Any] = {nid: nid for nid in node_ids}

        def _find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def _union(a, b):
            ra, rb = _find(a), _find(b)
            if ra != rb:
                parent[ra] = rb

        degree: Dict[Any, int] = dict.fromkeys(node_ids, 0)
        for e in edges:
            s = getattr(e, "source_node_uuid", None)
            t = getattr(e, "target_node_uuid", None)
            if s in parent and t in parent and s != t:
                _union(s, t)
                degree[s] += 1
                degree[t] += 1
        num_components = len({_find(nid) for nid in node_ids}) if node_ids else 0
        name_by_id = {getattr(n, "uuid_", None): (getattr(n, "name", "") or "") for n in nodes}
        top_hubs = [name_by_id.get(nid, "") for nid, _ in
                    sorted(degree.items(), key=lambda kv: -kv[1])[:5] if name_by_id.get(nid)]
        logger.info("[%s] graph integrity: nodes=%d edges=%d components=%d top_hubs=%s",
                    graph_id, len(nodes), len(edges), num_components, top_hubs)
        try:
            warn_ratio = float(getattr(Config, "GRAPH_COMPONENT_WARN_RATIO", 0.5))
        except (TypeError, ValueError):
            warn_ratio = 0.5
        # KG-8: 旧的整数截断比较（> max(1, int(n*ratio))）在真实图上几乎永不触发（30 分量
        # /132 节点已明显碎裂却只发 INFO）。改浮点比较，保留 >1 下限（单分量=完全连通不告警）。
        # 阈值语义：分量数超过节点数×ratio 即告警；默认 ratio 仍偏松，建议经
        # GRAPH_COMPONENT_WARN_RATIO 调低（0.2 可让上述 30/132 触发）。
        if node_ids and num_components > 1 and num_components > len(node_ids) * warn_ratio:
            # 附带最大的 3 个分量的枢纽名（分量内度数最高节点），让操作者看见「什么被断开了」。
            comp_members: Dict[Any, List[Any]] = {}
            for nid in node_ids:
                comp_members.setdefault(_find(nid), []).append(nid)
            top_comps = sorted(comp_members.values(), key=len, reverse=True)[:3]
            comp_hubs = [
                f"{name_by_id.get(max(m, key=lambda x: degree.get(x, 0)), '?')}(n={len(m)})"
                for m in top_comps
            ]
            logger.warning(
                "[%s] possibly UNDER-MERGED entities: %d components over %d nodes; "
                "largest components' hubs: %s",
                graph_id, num_components, len(node_ids), comp_hubs)

        # P3-7: 把已算出的度数转成 [0,1] 归一中心度先验（node_name→centrality），此前被丢弃。
        max_deg = max(degree.values()) if degree else 0
        centrality: Dict[str, float] = {}
        if max_deg > 0:
            for nid, d in degree.items():
                nm = name_by_id.get(nid, "")
                if nm and d > 0:
                    centrality[nm] = max(centrality.get(nm, 0.0), round(d / max_deg, 4))

        # R2-KG-5（GRAPH_CHOKEPOINT_PRIORS，默认关）：在已取的 nodes/edges 上算介数中心度 +
        # 关节点，得到"谁卡在传导咽喉"的结构先验。纯内存、复用上面构造的连通信息；O(V*E) 故对
        # 大图设节点上限（GRAPH_CHOKEPOINT_MAX_NODES，默认 1500）保护，超限则跳过（degrade-safe）。
        betweenness: Dict[str, float] = {}
        chokepoints: List[str] = []
        if getattr(Config, "GRAPH_CHOKEPOINT_PRIORS", False) and node_ids and edges:
            try:
                # KG-3: O(V*E) 上限从 Config 读（GRAPH_CHOKEPOINT_MAX_NODES，默认 1500）——
                # 此前注释声称可调但实际是模块常量；非法/缺失/非正值兜底到常量。
                try:
                    cap = int(getattr(Config, "GRAPH_CHOKEPOINT_MAX_NODES",
                                      _CHOKEPOINT_MAX_NODES) or _CHOKEPOINT_MAX_NODES)
                except (TypeError, ValueError):
                    cap = _CHOKEPOINT_MAX_NODES
                if cap <= 0:
                    cap = _CHOKEPOINT_MAX_NODES
                if len(node_ids) <= cap:
                    adj: Dict[Any, set] = {nid: set() for nid in node_ids}
                    for e in edges:
                        s = getattr(e, "source_node_uuid", None)
                        t = getattr(e, "target_node_uuid", None)
                        if s in adj and t in adj and s != t:
                            adj[s].add(t)
                            adj[t].add(s)
                    raw = _brandes_betweenness(adj)
                    max_bc = max(raw.values()) if raw else 0.0
                    if max_bc > 0:
                        for nid, bc in raw.items():
                            nm = name_by_id.get(nid, "")
                            if nm and bc > 0:
                                betweenness[nm] = max(betweenness.get(nm, 0.0), round(bc / max_bc, 4))
                    aps = _articulation_points(adj)
                    # chokepoints = 介数高位 ∪ 关节点（节点名，去重，按介数降序）
                    choke_ids = set(aps) | {nid for nid, _ in
                                            sorted(raw.items(), key=lambda kv: -kv[1])[:10]}
                    seen: set = set()
                    for nid in sorted(choke_ids, key=lambda x: -raw.get(x, 0.0)):
                        nm = name_by_id.get(nid, "")
                        if nm and nm not in seen:
                            seen.add(nm)
                            chokepoints.append(nm)
                    logger.info("[%s] chokepoint priors: betweenness_nodes=%d articulation=%d",
                                graph_id, len(betweenness), len(aps))
                else:
                    logger.info("[%s] chokepoint priors skipped: %d nodes over cap %d",
                                graph_id, len(node_ids), cap)
            except Exception as exc:  # noqa: BLE001 — priors are best-effort, never fail the build
                logger.warning("[%s] chokepoint prior computation skipped: %s", graph_id, exc)

        return GraphInfo(
            graph_id=graph_id,
            node_count=len(nodes),
            edge_count=len(edges),
            entity_types=list(entity_types),
            components=num_components,
            top_hubs=top_hubs,
            centrality=centrality,
            betweenness=betweenness or None,
            chokepoints=chokepoints or None,
        )
    
    def _fetch_graph_raw(self, graph_id: str, use_cache: bool = True) -> Dict[str, Any]:
        """取全量 nodes/edges 明细 dict（TTL 缓存，Wave9-KG）。

        前端 10s 轮询打在 /graph/data 上，此前每次都重分页读库（~30 次上游调用）；
        缓存原始明细（60s TTL，GRAPH_UI_CACHE_TTL_S），各参数组合的派生视图在内存里
        便宜地现算。图谱变更（剪枝/删除/建图完成）走 invalidate_graph_cache。
        """
        cache_key = f"{graph_id}|raw"
        if use_cache:
            cached = _ui_cache_get(cache_key)
            if cached is not None:
                return cached

        nodes = fetch_all_nodes(self.client, graph_id)
        edges = fetch_all_edges(self.client, graph_id)

        # 创建节点映射用于获取节点名称
        node_map = {}
        for node in nodes:
            node_map[node.uuid_] = node.name or ""

        nodes_data = []
        for node in nodes:
            # 获取创建时间
            created_at = getattr(node, 'created_at', None)
            if created_at:
                created_at = str(created_at)

            nodes_data.append({
                "uuid": node.uuid_,
                "name": node.name,
                "labels": node.labels or [],
                "summary": node.summary or "",
                "attributes": node.attributes or {},
                "created_at": created_at,
            })

        edges_data = []
        for edge in edges:
            # 获取时间信息
            created_at = getattr(edge, 'created_at', None)
            valid_at = getattr(edge, 'valid_at', None)
            invalid_at = getattr(edge, 'invalid_at', None)
            expired_at = getattr(edge, 'expired_at', None)

            # 获取 episodes
            episodes = getattr(edge, 'episodes', None) or getattr(edge, 'episode_ids', None)
            if episodes and not isinstance(episodes, list):
                episodes = [str(episodes)]
            elif episodes:
                episodes = [str(e) for e in episodes]

            # 获取 fact_type
            fact_type = getattr(edge, 'fact_type', None) or edge.name or ""

            edges_data.append({
                "uuid": edge.uuid_,
                "name": edge.name or "",
                "fact": edge.fact or "",
                "fact_type": fact_type,
                "source_node_uuid": edge.source_node_uuid,
                "target_node_uuid": edge.target_node_uuid,
                "source_node_name": node_map.get(edge.source_node_uuid, ""),
                "target_node_name": node_map.get(edge.target_node_uuid, ""),
                "attributes": edge.attributes or {},
                "created_at": str(created_at) if created_at else None,
                "valid_at": str(valid_at) if valid_at else None,
                "invalid_at": str(invalid_at) if invalid_at else None,
                "expired_at": str(expired_at) if expired_at else None,
                "episodes": episodes or [],
            })

        raw = {"nodes": nodes_data, "edges": edges_data}
        if use_cache:
            _ui_cache_put(cache_key, raw)
        return raw

    def get_graph_data(
        self,
        graph_id: str,
        top_k: Optional[int] = None,
        min_degree: Optional[int] = None,
        slim: bool = False,
    ) -> Dict[str, Any]:
        """
        获取图谱数据（包含详细信息）。

        Args:
            graph_id: 图谱ID
            top_k: （Wave9-KG，可选）按度数排名只返回前 K 个节点及其导出边；
                   传 0/负值 = 用 Config.GRAPH_UI_MAX_NODES（默认 400）。缺省 None = 全量。
            min_degree: （可选）只保留度数 ≥ 该值的节点。缺省 None = 不过滤。
            slim: True 时剥掉 summary/fact/episodes/attributes 等重字段
                  （明细走 /graph/data/<id>/node|edge/<uuid> 接口）。

        Returns:
            包含nodes和edges的字典；不传任何新参数时行为与旧版一致（全量+全字段），
            另附 total_node_count/total_edge_count/truncated 与（若已预计算）positions。
        """
        raw = self._fetch_graph_raw(graph_id)
        nodes_data, edges_data = raw["nodes"], raw["edges"]
        total_nodes, total_edges = len(nodes_data), len(edges_data)

        nodes_out, edges_out = filter_subgraph(nodes_data, edges_data, top_k, min_degree)

        # 布局预计算（positions.json）：只带返回节点的坐标；文件缺失时不带该键。
        positions = load_layout_positions(graph_id)
        if positions:
            kept_ids = {n.get("uuid") for n in nodes_out}
            positions = {k: v for k, v in positions.items() if k in kept_ids}

        if slim:
            nodes_out, edges_out = slim_graph_payload(nodes_out, edges_out)

        result: Dict[str, Any] = {
            "graph_id": graph_id,
            "nodes": nodes_out,
            "edges": edges_out,
            "node_count": len(nodes_out),
            "edge_count": len(edges_out),
            "total_node_count": total_nodes,
            "total_edge_count": total_edges,
            "truncated": len(nodes_out) < total_nodes or len(edges_out) < total_edges,
        }
        if positions:
            result["positions"] = positions
        return result

    def get_node_neighborhood(
        self, graph_id: str, node_uuid: str, depth: int = 1, slim: bool = True
    ) -> Dict[str, Any]:
        """Wave9-KG（点击展开）：返回某节点 depth 跳内的邻域子图（默认 slim）。

        基于 TTL 缓存的全量明细做 BFS，节点数上限 Config.GRAPH_UI_MAX_NODES。
        """
        depth = max(1, min(int(depth or 1), 3))
        raw = self._fetch_graph_raw(graph_id)
        nodes_data, edges_data = raw["nodes"], raw["edges"]
        adj: Dict[str, set] = {}
        for e in edges_data:
            s, t = e.get("source_node_uuid"), e.get("target_node_uuid")
            if s and t and s != t:
                adj.setdefault(s, set()).add(t)
                adj.setdefault(t, set()).add(s)

        max_nodes = max(1, int(getattr(Config, "GRAPH_UI_MAX_NODES", 400) or 400))
        visited = {node_uuid}
        frontier = {node_uuid}
        for _ in range(depth):
            nxt: set = set()
            for u in frontier:
                for v in adj.get(u, ()):
                    if v not in visited:
                        nxt.add(v)
            visited |= nxt
            frontier = nxt
            if len(visited) >= max_nodes or not frontier:
                break

        nodes_out = [n for n in nodes_data if n.get("uuid") in visited]
        if len(nodes_out) > max_nodes:
            # 超限时按度数保留最重要的邻居（中心节点恒保留）。
            degree = compute_node_degrees(edges_data)
            nodes_out.sort(key=lambda n: (n.get("uuid") != node_uuid,
                                          -degree.get(n.get("uuid"), 0),
                                          str(n.get("name") or "")))
            nodes_out = nodes_out[:max_nodes]
        kept_ids = {n.get("uuid") for n in nodes_out}
        edges_out = [
            e for e in edges_data
            if e.get("source_node_uuid") in kept_ids and e.get("target_node_uuid") in kept_ids
        ]
        positions = load_layout_positions(graph_id)
        if positions:
            positions = {k: v for k, v in positions.items() if k in kept_ids}
        if slim:
            nodes_out, edges_out = slim_graph_payload(nodes_out, edges_out)
        result: Dict[str, Any] = {
            "graph_id": graph_id,
            "center_uuid": node_uuid,
            "depth": depth,
            "nodes": nodes_out,
            "edges": edges_out,
            "node_count": len(nodes_out),
            "edge_count": len(edges_out),
        }
        if positions:
            result["positions"] = positions
        return result

    def get_node_detail(self, graph_id: str, node_uuid: str) -> Optional[Dict[str, Any]]:
        """Wave9-KG（详情面板）：单节点全字段（slim 列表剥掉的字段从这里取）。"""
        raw = self._fetch_graph_raw(graph_id)
        for n in raw["nodes"]:
            if n.get("uuid") == node_uuid:
                return dict(n)
        return None

    def get_edge_detail(self, graph_id: str, edge_uuid: str) -> Optional[Dict[str, Any]]:
        """Wave9-KG（详情面板）：单边全字段（fact/episodes/attributes/时间戳）。"""
        raw = self._fetch_graph_raw(graph_id)
        for e in raw["edges"]:
            if e.get("uuid") == edge_uuid:
                return dict(e)
        return None

    def compute_layout(self, graph_id: str, persist: bool = True) -> Dict[str, List[float]]:
        """Wave9-KG（布局预计算）：对当前图算一次弹簧布局并持久化 positions.json。

        建图完成/剪枝完成后调用；失败只告警（布局是增强，绝不影响建图结果）。
        """
        try:
            raw = self._fetch_graph_raw(graph_id, use_cache=False)
            positions = compute_layout_positions(raw["nodes"], raw["edges"])
            if persist and positions:
                path = store_layout_positions(graph_id, positions)
                logger.info("[%s] layout precomputed: %d positions -> %s",
                            graph_id, len(positions), path)
            invalidate_graph_cache(graph_id)
            return positions
        except Exception as exc:  # noqa: BLE001 — 布局失败不阻断建图
            logger.warning("[%s] layout precompute failed: %s", graph_id, exc)
            return {}

    def gc_stale_graphs(self, retain: Optional[int] = None) -> Dict[str, Any]:
        """Wave9-KG（陈旧图谱 GC）：回收不再被任何管线/项目引用的历史图谱。

        保留：所有被 uploads/pipelines/*/pipeline_state.json 或项目档案引用的图 +
        未引用图中最新的 ``retain`` 个（缺省 Config.GRAPH_RETAIN_COUNT=5）。
        护栏：存在「尚未写出 graph_id 的活动管线」时整体跳过（新图可能暂时无引用，
        删除不可逆）。返回审计 dict。
        """
        if retain is None:
            retain = int(getattr(Config, "GRAPH_RETAIN_COUNT", 5) or 5)
        from .graphiti_client.runtime import get_runtime

        rt = get_runtime()
        all_ids = rt.list_graph_ids()
        audit: Dict[str, Any] = {
            "total": len(all_ids), "retain": retain,
            "kept": [], "deleted": [], "failed": [], "skipped_reason": None,
        }
        if not all_ids:
            audit["skipped_reason"] = "backend returned no graph list (enumeration unsupported or empty)"
            return audit

        referenced, active_without_graph = referenced_graph_ids()
        if active_without_graph:
            audit["skipped_reason"] = (
                f"{active_without_graph} active pipeline(s) without a recorded graph_id — "
                "GC skipped to avoid deleting an in-flight graph"
            )
            logger.warning("[GC] %s", audit["skipped_reason"])
            return audit

        # 只为未引用的图取 recency（避免为已保留的图做无谓查询）。
        unreferenced = [g for g in all_ids if g not in referenced]
        recency = {g: rt.graph_last_created_at(g) for g in unreferenced}
        keep, victims = plan_graph_gc(all_ids, referenced, recency, retain)
        audit["kept"] = sorted(keep)

        for gid in victims:
            try:
                self.delete_graph(gid)
                invalidate_graph_cache(gid)
                audit["deleted"].append(gid)
            except Exception as exc:  # noqa: BLE001 — 单图删除失败不中断 GC
                logger.warning("[GC] delete_graph %s failed: %s", gid, exc)
                audit["failed"].append(gid)
        logger.info("[GC] stale graphs: total=%d kept=%d deleted=%d failed=%d",
                    len(all_ids), len(keep), len(audit["deleted"]), len(audit["failed"]))
        return audit

    def delete_graph(self, graph_id: str):
        """删除图谱"""
        self.client.graph.delete(graph_id=graph_id)
        invalidate_graph_cache(graph_id)  # Wave9-KG：同时清 UI 缓存，避免读到幽灵图
