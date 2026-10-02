"""LLM-assisted entity resolution / canonical-alias merge after graph build
(EXECPLAN2 I-1-4).

Graphiti's add_episode dedups by name+embedding *during* ingestion, but the same
real entity surfacing under different surface forms across research prose, seeded
actors, and simulation feedback ('OpenAI' / 'OpenAI 公司' / 'OpenAI, Inc.' /
'@OpenAI') can still produce duplicate nodes — splitting search recall, under-
counting centrality, and spawning personas for phantom nodes. This pass clusters
near-duplicate entity nodes (reusing actors.normalize_name + bidirectional
containment AND an embedding-cosine gate) and merges non-canonical surface forms
INTO the actors.json canonical name, then emits an audit (entity_merges.json).

OPTIONAL-DEGRADE: only runs when Config.GRAPH_RESOLVE_ENTITIES is true (default
off → never invoked → graph is byte-identical to today).

Over-merge guardrails (the spec's "Medium-High" risk): merge only WITHIN the same
primary label; require BOTH a normalized-name match (exact or containment) AND
embedding cosine ≥ threshold; never merge two actors.json canonicals into each
other; always pick the canonical as survivor; log every merge for audit/rollback.

The planning logic (clustering, survivor selection) is pure / side-effect-free so
it is unit-tested offline; only execute_merges touches the graph (best-effort,
per-merge isolated, serialized on the runtime's per-graph write lock).
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

from ..utils.actors import extract_actor_rows, normalize_name

logger = logging.getLogger("mirofish.entity_resolver")

_ACTOR_GRAPH_SEED_SCHEMA_VERSION = "actor-graph-seed/v1"


def _seed_kind(node: Dict[str, Any]) -> str:
    attrs = node.get("attributes") if isinstance(node, dict) else None
    if not isinstance(attrs, dict):
        return ""
    if attrs.get("seed_schema_version") != _ACTOR_GRAPH_SEED_SCHEMA_VERSION:
        return ""
    return str(attrs.get("seed_kind") or "")


def _seed_survivor_priority(node: Dict[str, Any]) -> int:
    """Canonical actor seed wins; alias seed may collapse into that actor."""
    kind = _seed_kind(node)
    if kind == "actor":
        return 0
    if kind == "actor_alias":
        return 2
    return 1


# ----------------------------------------------------------------- pure helpers
def canonical_norm_set(actors: Any) -> set:
    """Normalized names of the researched actors.json canonicals."""
    return {normalize_name(r.get("name", "")) for r in extract_actor_rows(actors)
            if normalize_name(r.get("name", ""))}


def actor_alias_map(actors: Any) -> Dict[str, str]:
    """2026-07-03 live-surfaced: normalized alias name -> normalized canonical name,
    built directly from actors.json's ``aliases`` field (the AUTHORITATIVE ground
    truth the research/dossier stage already extracted), independent of whether the
    graphiti-extracted GRAPH NODE itself carries any alias attribute.

    Why this is needed in addition to ``_node_aliases``/``_alias_match``: those read
    alias metadata off the graph node's own ``attributes`` dict, which only gets
    populated if graphiti's per-chunk LLM extractor happened to fill an ``aliases``
    attribute for that entity type — in practice it usually doesn't (each chunk sees
    isolated prose, not the dossier's curated alias list). A real forecast run
    produced 6 separate un-merged nodes ("China"/"CCP"/"Beijing"x2/"MOFCOM"/
    "Government of the People's Republic of China") for ONE actors.json record whose
    ``aliases`` field already correctly listed all five — this map lets plan_merges
    treat any of those exact alias strings as high-precision merge signals even when
    the graph node carries zero alias metadata of its own.

    INFRA-11 (ACTOR_NAME_MATCH_STRICT, default on): an alias claimed by two different
    actors — listed by both, or one actor's alias equal to another actor's canonical name —
    is excluded and logged instead of resolving to whichever row came last.  Without a
    collision the map is identical to the legacy one; flag off = legacy last-writer-wins.
    """
    out: Dict[str, str] = {}
    claims: Dict[str, set] = {}
    for row in extract_actor_rows(actors):
        canon = normalize_name(row.get("name", ""))
        if not canon:
            continue
        raw_aliases = row.get("aliases")
        if not isinstance(raw_aliases, list):
            continue
        for al in raw_aliases:
            if isinstance(al, str):
                na = normalize_name(al)
                if na and na != canon:
                    out[na] = canon
                    claims.setdefault(na, set()).add(canon)
    from ..config import Config
    if not getattr(Config, "ACTOR_NAME_MATCH_STRICT", True):
        return out
    canonicals = canonical_norm_set(actors)
    contested = [alias for alias, owners in claims.items()
                 if len(owners) > 1 or alias in canonicals]
    for alias in contested:
        del out[alias]
    if contested:
        logger.info("actor_alias_map: %d alias(es) claimed by two different actors excluded: %s",
                    len(contested), ", ".join(
                        f"{alias}→{'/'.join(sorted(claims[alias] | ({alias} & canonicals)))}"
                        for alias in contested[:8]))
    return out


def actor_alias_norms(actors: Any) -> set:
    """Every normalized alias surface in actors.json (other than the row's own canonical),
    contested ones included: the graph pruner protects all of them, whichever actor an
    ambiguous alias denotes (``actor_alias_map`` drops those under INFRA-11)."""
    out: set = set()
    for row in extract_actor_rows(actors):
        canon = normalize_name(row.get("name", ""))
        raw_aliases = row.get("aliases")
        if not canon or not isinstance(raw_aliases, list):
            continue
        for al in raw_aliases:
            if isinstance(al, str):
                na = normalize_name(al)
                if na and na != canon:
                    out.add(na)
    return out


def _cosine(a: Optional[List[float]], b: Optional[List[float]]) -> Optional[float]:
    """Cosine similarity, or None if either vector is missing/empty."""
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return None
    return dot / (na * nb)


def _name_match(norm_a: str, norm_b: str) -> bool:
    """Exact normalized match, or bidirectional containment with ≥2-char overlap
    (mirrors actors.match_actor — avoids 'AI'-style short-name noise)."""
    if not norm_a or not norm_b:
        return False
    if norm_a == norm_b:
        return True
    shorter = norm_a if len(norm_a) <= len(norm_b) else norm_b
    longer = norm_b if shorter is norm_a else norm_a
    return len(shorter) >= 2 and shorter in longer


def _primary_label(node: Dict[str, Any]) -> str:
    labels = [str(x) for x in (node.get("labels") or []) if x and str(x) != "Entity"]
    return labels[0] if labels else "Entity"


def _node_aliases(node: Dict[str, Any]) -> set:
    """R2-KG-8: normalized alias set for a graph node (best-effort, defensive).

    Aliases let us merge surface forms with ZERO character overlap ('MSFT' vs
    'Microsoft', '马斯克' vs 'Musk') that name-containment can never catch. We look
    for an explicit ``aliases`` list on the node and on ``attributes`` (graphiti
    stores extracted entity attributes there). Absent/garbage data → empty set, so
    this branch is fully inert (no behavior change) on graphs without alias data.
    """
    out: set = set()
    if not isinstance(node, dict):
        return out
    candidates: List[Any] = []
    raw = node.get("aliases")
    if isinstance(raw, list):
        candidates.extend(raw)
    attrs = node.get("attributes")
    if isinstance(attrs, dict):
        a2 = attrs.get("aliases")
        if isinstance(a2, list):
            candidates.extend(a2)
        a3 = attrs.get("alias")
        if isinstance(a3, str):
            candidates.append(a3)
    for a in candidates:
        if isinstance(a, str):
            na = normalize_name(a)
            if na:
                out.add(na)
    return out


def _alias_match(norm_a: str, norm_b: str, aliases_a: set, aliases_b: set) -> bool:
    """R2-KG-8: explicit-alias equality between two nodes (all exact, no containment).

    True iff one node's normalized name equals a curated alias of the other, or the
    two nodes share a curated alias. Exactness keeps this high-precision so it can
    serve as the 'exact signal' fallback when embeddings are unavailable.
    """
    if norm_a and aliases_b and norm_a in aliases_b:
        return True
    if norm_b and aliases_a and norm_b in aliases_a:
        return True
    if aliases_a and aliases_b and (aliases_a & aliases_b):
        return True
    return False


def _labels_mergeable(label_a: str, label_b: str) -> bool:
    """R2-KG-8: same primary label, OR one side is the generic 'Entity' (an untyped
    duplicate of a typed node). Two DISTINCT typed labels are never directly
    mergeable (over-merge guard); transitive bridging is blocked separately."""
    if label_a == label_b:
        return True
    return "Entity" in (label_a, label_b)


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def plan_merges(nodes: List[Dict[str, Any]], embeddings: Optional[List[List[float]]],
                canonical_norms: set, threshold: float,
                alias_map: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Pure: cluster near-duplicate nodes and choose survivors. No graph access.

    Returns [{survivor_uuid, survivor_name, primary_label, cross_label,
    victims:[{uuid,name,similarity,label}]}].
    A pair is mergeable iff: labels mergeable (same primary label OR one is the
    generic 'Entity') AND (name-match exact/containment OR explicit-alias match OR
    dossier-alias match) AND (embedding cosine ≥ threshold when both embeddings
    exist, else exact-norm / exact-alias match as a safe fallback) AND not both
    DISTINCT canonical.
    R2-KG-8: a generic-'Entity' bridge can never transitively merge two DISTINCT
    typed labels (per-root typed-label set guard). Components with ≥2 canonicals are
    split so each canonical anchors its own cluster (never merge two canonicals).
    2026-07-03: ``alias_map`` (normalized alias -> normalized canonical, built from
    actors.json by ``actor_alias_map``) is an additional exact-signal match,
    independent of whatever alias metadata the graph node itself carries — see
    ``actor_alias_map``'s docstring for why this is necessary.
    """
    n = len(nodes)
    if n < 2:
        return []
    emb = embeddings if (embeddings and len(embeddings) == n) else [None] * n
    norms = [normalize_name(nd.get("name", "")) for nd in nodes]
    labels = [_primary_label(nd) for nd in nodes]
    aliases = [_node_aliases(nd) for nd in nodes]  # R2-KG-8: alias-aware matching
    amap = alias_map or {}
    # dossier_canon[i] = the canonical this node resolves to via actors.json aliases,
    # whether the node's OWN name is that canonical or a known alias of it.
    dossier_canon = [amap.get(norms[i], norms[i] if norms[i] in canonical_norms else None)
                     for i in range(n)]
    is_canon = [norms[i] in canonical_norms and bool(norms[i]) for i in range(n)]
    seed_kinds = [_seed_kind(node) for node in nodes]
    seed_priorities = [_seed_survivor_priority(node) for node in nodes]

    uf = _UnionFind(n)
    sim_cache: Dict[tuple, float] = {}
    # R2-KG-8: distinct typed (non-'Entity') labels per UF root. A union is refused
    # if it would put two DISTINCT typed labels in one component, so an untyped
    # 'Entity' duplicate can bridge to AT MOST one typed cluster (no over-merge).
    typed_by_root: Dict[int, set] = {
        i: ({labels[i]} if labels[i] != "Entity" else set()) for i in range(n)
    }

    def _try_union(a: int, b: int, cos: float) -> None:
        key = (min(a, b), max(a, b))
        ra, rb = uf.find(a), uf.find(b)
        if ra == rb:
            sim_cache[key] = round(cos, 4)
            return
        merged_typed = typed_by_root.get(ra, set()) | typed_by_root.get(rb, set())
        if len(merged_typed) > 1:
            return  # would bridge two DISTINCT typed labels → refuse (over-merge guard)
        uf.union(a, b)
        typed_by_root[uf.find(a)] = merged_typed
        sim_cache[key] = round(cos, 4)

    for i in range(n):
        if not norms[i]:
            continue
        for j in range(i + 1, n):
            if "entity_type" in (seed_kinds[i], seed_kinds[j]):
                continue  # schema/type nodes are not actor-resolution candidates
            if seed_kinds[i] == seed_kinds[j] == "actor":
                continue  # duplicate sealed actor nodes are validation failures
            if not norms[j] or not _labels_mergeable(labels[i], labels[j]):
                continue
            if is_canon[i] and is_canon[j] and norms[i] != norms[j]:
                continue  # never merge two DISTINCT canonicals (same-canonical dups are fine)
            name_ok = _name_match(norms[i], norms[j])
            alias_ok = _alias_match(norms[i], norms[j], aliases[i], aliases[j])
            # 2026-07-03: dossier_ok — both nodes resolve to the SAME actors.json
            # canonical via the authoritative alias_map, independent of whatever
            # (usually absent) alias metadata the graph node itself carries.
            dossier_ok = bool(dossier_canon[i]) and dossier_canon[i] == dossier_canon[j]
            if not (name_ok or alias_ok or dossier_ok):
                continue
            cos = _cosine(emb[i], emb[j])
            if cos is None:
                # no embeddings → safe fallback: require an EXACT signal
                # (exact normalized name OR explicit-alias match OR dossier-alias match).
                if norms[i] != norms[j] and not (alias_ok or dossier_ok):
                    continue
                cos = 1.0
            elif cos < threshold and not dossier_ok:
                # dossier-alias match is authoritative ground truth (the research
                # stage already confirmed these are the same real actor) — bypass
                # the cosine gate exactly like the explicit-alias exact signal.
                continue
            _try_union(i, j, cos)

    return _finalize_clusters(
        nodes,
        uf,
        n,
        is_canon,
        norms,
        labels,
        sim_cache,
        seed_priorities,
    )


def _finalize_clusters(nodes, uf, n: int, is_canon: List[bool], norms: List[str],
                       labels: List[str], sim_cache: Dict[tuple, float],
                       seed_priorities: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    """Shared tail for both plan_merges (full) and plan_merges_fast: group union-find
    components into clusters, split components that contain DISTINCT canonicals, pick a
    survivor per cluster. Pure; no graph access. Identical to the original plan_merges
    tail (extracted so the O(N) fast path can reuse it without duplicating the logic)."""
    comps: Dict[int, List[int]] = {}
    for i in range(n):
        comps.setdefault(uf.find(i), []).append(i)

    def _sim(a: int, b: int) -> float:
        return sim_cache.get((min(a, b), max(a, b)), 1.0)

    out: List[Dict[str, Any]] = []
    for members in comps.values():
        if len(members) < 2:
            continue
        # DISTINCT canonical names within one component → split so each canonical
        # anchors its own cluster (duplicates of the SAME canonical stay together).
        distinct_canon = {norms[m] for m in members if is_canon[m]}
        if len(distinct_canon) >= 2:
            canon_members = [m for m in members if is_canon[m]]
            groups: Dict[str, List[int]] = {}
            for m in members:
                if is_canon[m]:
                    groups.setdefault(norms[m], []).append(m)
            for m in members:
                if is_canon[m]:
                    continue
                best_c = max(canon_members, key=lambda c: _sim(c, m))
                groups[norms[best_c]].append(m)
            for grp in groups.values():
                if len(grp) >= 2:
                    survivor = _pick_survivor(
                        grp, is_canon, norms, labels, nodes, seed_priorities
                    )
                    out.append(_make_cluster(nodes, survivor,
                                             [m for m in grp if m != survivor], _sim))
        else:
            survivor = _pick_survivor(
                members, is_canon, norms, labels, nodes, seed_priorities
            )
            out.append(_make_cluster(nodes, survivor,
                                     [m for m in members if m != survivor], _sim))
    return out


def plan_merges_fast(nodes: List[Dict[str, Any]], embeddings: Optional[List[List[float]]],
                     canonical_norms: set, threshold: float,
                     alias_map: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """O(N) duplicate clustering for LARGE graphs — bucket by EXACT normalized name and
    by shared explicit alias, union within buckets (still embedding-gated + canonical-
    protected + label-mergeable), then finalize. Skips the O(N²) containment+cosine scan
    that wedges plan_merges on big node sets. Catches the highest-value duplicates (the
    same surface form appearing many times) without the all-pairs blow-up. Pure.
    2026-07-03: also buckets by ``dossier_canon`` (actors.json alias_map resolution,
    see ``actor_alias_map``) so alias surface forms with zero character overlap and
    zero graph-node alias metadata still land in the same bucket and get merged."""
    from collections import defaultdict
    n = len(nodes)
    if n < 2:
        return []
    emb = embeddings if (embeddings and len(embeddings) == n) else [None] * n
    norms = [normalize_name(nd.get("name", "")) for nd in nodes]
    labels = [_primary_label(nd) for nd in nodes]
    aliases = [_node_aliases(nd) for nd in nodes]
    amap = alias_map or {}
    dossier_canon = [amap.get(norms[i], norms[i] if norms[i] in canonical_norms else None)
                     for i in range(n)]
    is_canon = [norms[i] in canonical_norms and bool(norms[i]) for i in range(n)]
    seed_kinds = [_seed_kind(node) for node in nodes]
    seed_priorities = [_seed_survivor_priority(node) for node in nodes]

    uf = _UnionFind(n)
    sim_cache: Dict[tuple, float] = {}
    typed_by_root: Dict[int, set] = {
        i: ({labels[i]} if labels[i] != "Entity" else set()) for i in range(n)
    }

    def _try_union(a: int, b: int, cos: float) -> None:
        key = (min(a, b), max(a, b))
        ra, rb = uf.find(a), uf.find(b)
        if ra == rb:
            sim_cache[key] = round(cos, 4)
            return
        merged_typed = typed_by_root.get(ra, set()) | typed_by_root.get(rb, set())
        if len(merged_typed) > 1:
            return
        uf.union(a, b)
        typed_by_root[uf.find(a)] = merged_typed
        sim_cache[key] = round(cos, 4)

    # Build candidate buckets: exact normalized name, plus each explicit alias key,
    # plus the dossier-resolved canonical (actors.json alias_map — 2026-07-03).
    buckets: Dict[str, List[int]] = defaultdict(list)
    for i in range(n):
        if norms[i]:
            buckets[norms[i]].append(i)
        for al in aliases[i]:
            buckets[al].append(i)
        if dossier_canon[i]:
            buckets[f"__dossier__{dossier_canon[i]}"].append(i)

    for idxs in buckets.values():
        if len(idxs) < 2:
            continue
        base = idxs[0]
        for k in idxs[1:]:
            a, b = base, k
            if "entity_type" in (seed_kinds[a], seed_kinds[b]):
                continue
            if seed_kinds[a] == seed_kinds[b] == "actor":
                continue
            if not _labels_mergeable(labels[a], labels[b]):
                continue
            if is_canon[a] and is_canon[b] and norms[a] != norms[b]:
                continue  # never merge two DISTINCT canonicals
            cos = _cosine(emb[a], emb[b])
            if cos is None:
                cos = 1.0  # no embeddings → exact bucket match is itself the exact signal
            elif cos < threshold:
                continue
            _try_union(a, b, cos)

    return _finalize_clusters(
        nodes,
        uf,
        n,
        is_canon,
        norms,
        labels,
        sim_cache,
        seed_priorities,
    )


def _pick_survivor(members: List[int], is_canon: List[bool], norms: List[str],
                   labels: List[str], nodes: List[Dict[str, Any]],
                   seed_priorities: Optional[List[int]] = None) -> int:
    """Prefer a canonical member; among equals prefer a TYPED label over the generic
    'Entity' (R2-KG-8: a cross-label merge keeps the entity's type on the survivor);
    then the longest normalized name. Tie-break by name string for determinism."""
    priorities = seed_priorities or [_seed_survivor_priority(node) for node in nodes]
    return min(members, key=lambda m: (
        priorities[m],
        0 if is_canon[m] else 1,
        0 if labels[m] != "Entity" else 1,
        -len(norms[m]),
        norms[m],
        str(nodes[m].get("uuid") or ""),
    ))


def _make_cluster(nodes, survivor: int, victims: List[int], sim_fn) -> Dict[str, Any]:
    surv_label = _primary_label(nodes[survivor])
    victim_rows = []
    cross_label = False
    for v in victims:
        vlabel = _primary_label(nodes[v])
        if vlabel != surv_label:
            cross_label = True  # R2-KG-8: audit cross-label merges in entity_merges.json
        victim_rows.append({
            "uuid": nodes[v]["uuid"], "name": nodes[v]["name"],
            "similarity": sim_fn(survivor, v), "label": vlabel,
        })
    return {
        "survivor_uuid": nodes[survivor]["uuid"],
        "survivor_name": nodes[survivor]["name"],
        "primary_label": surv_label,
        "cross_label": cross_label,
        "victims": victim_rows,
    }


# --------------------------------------------------------------- orchestration
def resolve_entities(graph_id: str, actors: Any, threshold: Optional[float] = None,
                     runtime: Any = None) -> Dict[str, Any]:
    """List entity nodes, embed names, plan merges, execute them (best-effort).

    Returns an audit dict (also written to handoff/entity_merges.json by the
    caller) with the planned clusters and per-merge execution results. Any failure
    degrades to a no-op partial result rather than raising — the GRAPH stage must
    never be broken by resolution.
    """
    from ..config import Config
    if threshold is None:
        threshold = float(getattr(Config, "GRAPH_RESOLVE_SIM_THRESHOLD", 0.88))
    if runtime is None:
        from .graphiti_client.runtime import get_runtime
        runtime = get_runtime()

    nodes = runtime.all_entity_nodes(graph_id) or []
    if len(nodes) < 2:
        return {"nodes_scanned": len(nodes), "clusters": 0, "merged_nodes": 0,
                "merges": [], "threshold": threshold}

    try:
        embeddings = runtime.embed_texts([nd.get("name", "") for nd in nodes])
    except Exception as exc:  # noqa: BLE001 — embeddings optional; fall back to exact-norm
        logger.warning("resolve_entities: embedding failed, exact-norm only: %s", exc)
        embeddings = None

    # Bound the O(N²) all-pairs containment+cosine scan: it is a pure-Python CPU wall on
    # large node sets (observed: 100% CPU / multi-GB wedge in this step on a big graph).
    # Above GRAPH_RESOLVE_MAX_NODES, fall back to the O(N) exact-norm/alias fast path —
    # still merges the highest-value exact duplicates, never wedges. Small graphs keep the
    # full containment refinement (byte-identical to before).
    cap = int(getattr(Config, "GRAPH_RESOLVE_MAX_NODES", 1200) or 1200)
    canon = canonical_norm_set(actors)
    # 2026-07-03: actors.json 的 aliases 字段是研究阶段已确认的权威真相（不依赖图节点
    # 自身是否恰好带了 alias 元数据）——见 actor_alias_map 文档。
    amap = actor_alias_map(actors)
    if cap > 0 and len(nodes) > cap:
        logger.info("resolve_entities[%s]: %d nodes > cap %d → O(N) exact-name/alias fast path "
                    "(skipping O(N²) containment refinement)", graph_id, len(nodes), cap)
        plan = plan_merges_fast(nodes, embeddings, canon, threshold, alias_map=amap)
    else:
        plan = plan_merges(nodes, embeddings, canon, threshold, alias_map=amap)

    merged = 0
    for cluster in plan:
        results = []
        for victim in cluster["victims"]:
            try:
                res = runtime.merge_nodes(graph_id, cluster["survivor_uuid"], victim["uuid"])
                if res.get("deleted"):
                    merged += 1
                results.append({"victim_uuid": victim["uuid"], **res})
            except Exception as exc:  # noqa: BLE001 — per-merge isolation
                logger.warning("resolve_entities: merge failed %s←%s: %s",
                               cluster["survivor_uuid"], victim["uuid"], exc)
                results.append({"victim_uuid": victim["uuid"], "error": str(exc)})
        cluster["execution"] = results

    logger.info("resolve_entities[%s]: scanned=%d clusters=%d merged=%d (thr=%.2f)",
                graph_id, len(nodes), len(plan), merged, threshold)
    return {"nodes_scanned": len(nodes), "clusters": len(plan),
            "merged_nodes": merged, "merges": plan, "threshold": threshold}
