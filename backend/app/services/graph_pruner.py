"""建后图谱剪枝服务（Wave9-KG）。

无界的逐 chunk 实体抽取会把 25 个策展 actor 膨胀成 ~740 个实体节点（~30x），其中
66% 度数 ≤2、145 个完全孤立——UI 渲染、中心度先验与 agent 选池全被长尾垃圾稀释。
本服务在实体消解（zep_entity_resolver）之后运行一遍收敛剪枝：

1. 核心集 = actors.json 的 names ∪ aliases（复用 zep_entity_resolver 的归一化口径）；
2. keep-set = 核心 ∪ 核心 N-hop 邻域内按重要度排序的节点，硬容量为
   max(GRAPH_MAX_ENTITIES, 核心节点数)，单类型上限 GRAPH_MAX_ENTITIES_PER_TYPE
   只约束非核心节点；
3. keep-set 之外的节点全部 DETACH DELETE。禁止用「度数较高」或「与核心存在任意长路径」
   逃逸硬上限，否则一个弱桥就会让整个巨型连通分量存活；
4. 返回审计 dict（kept/deleted 计数、逐原因分布）——编排器把它写进
   handoff/graph_prune.json（与 entity_merges.json 同款审计范式）。

规划逻辑（plan_prune）是纯函数、零副作用，可离线单测；只有 prune_graph 触图
（删除经 runtime.delete_entity_nodes，在 per-graph 写锁上串行化）。

OPTIONAL-DEGRADE：GRAPH_PRUNE_ENABLED=false 时 prune_graph 直接返回空审计，图谱
逐字节不变；核心 actor 在图中一个都匹配不上时同样整体跳过（绝不基于空核心集删图）。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Set

from ..config import Config
from ..utils.actors import normalize_name
from .zep_entity_resolver import actor_alias_norms, canonical_norm_set
from .graph_builder import (
    compute_layout_positions,
    compute_node_degrees,
    invalidate_graph_cache,
    store_layout_positions,
)

logger = logging.getLogger("mirofish.graph_pruner")


# ----------------------------------------------------------------- pure helpers
def _as_actors_dict(actors: Any) -> Dict[str, Any]:
    """编排器可能传 actors.json 顶层 dict，也可能直接传 actor 行列表——两者都接。"""
    if isinstance(actors, dict):
        return actors
    if isinstance(actors, list):
        return {"actors": actors}
    return {"actors": []}


def _primary_label(node: Dict[str, Any]) -> str:
    labels = [str(x) for x in (node.get("labels") or []) if x and str(x) != "Entity"]
    return labels[0] if labels else "Entity"


def core_norm_names(actors: Any) -> Set[str]:
    """核心集的归一名：canonicals ∪ aliases（口径与 zep_entity_resolver 完全一致）。"""
    actors_dict = _as_actors_dict(actors)
    return canonical_norm_set(actors_dict) | actor_alias_norms(actors_dict)


def core_actor_match_stats(nodes: List[Dict[str, Any]], actors: Any) -> Dict[str, Any]:
    """Count curated actor rows represented by at least one canonical/alias graph node."""
    actor_rows = (_as_actors_dict(actors).get("actors") or [])
    node_norms = {
        normalize_name(str(n.get("name") or ""))
        for n in (nodes or [])
        if n.get("name")
    }
    expected = 0
    matched = 0
    for actor in actor_rows:
        if not isinstance(actor, dict):
            continue
        names = [actor.get("name")]
        aliases = actor.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        names.extend(aliases if isinstance(aliases, list) else [])
        norms = {normalize_name(str(x)) for x in names if x}
        if not norms:
            continue
        expected += 1
        if norms & node_norms:
            matched += 1
    return {
        "core_actor_expected": expected,
        "core_actor_matched": matched,
        "core_actor_coverage": round(matched / expected, 4) if expected else 0.0,
    }


def plan_prune(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    mentions: Dict[str, int],
    actors: Any,
    *,
    max_entities: Optional[int] = None,
    hops: Optional[int] = None,
    min_degree: Optional[int] = None,
    per_type_cap: Optional[int] = None,
) -> Dict[str, Any]:
    """纯规划：给定图内容与 actors，产出 keep/delete 决策与审计统计（零副作用）。

    Returns:
        {"keep": set(uuid), "delete": [uuid...], "stats": {...}}
    """
    if max_entities is None:
        max_entities = int(getattr(Config, "GRAPH_MAX_ENTITIES", 400))
    if hops is None:
        hops = int(getattr(Config, "GRAPH_CORE_ACTOR_HOPS", 2))
    if min_degree is None:
        min_degree = int(getattr(Config, "GRAPH_PRUNE_MIN_DEGREE", 2))
    if per_type_cap is None:
        per_type_cap = int(getattr(Config, "GRAPH_MAX_ENTITIES_PER_TYPE", 150))
    max_entities = max(1, max_entities)
    hops = max(0, hops)
    per_type_cap = max(1, per_type_cap)

    node_by_uuid = {n.get("uuid"): n for n in (nodes or []) if n.get("uuid")}
    all_uuids = list(node_by_uuid.keys())

    # 1) 核心集：节点归一名命中 actors.json 的 canonical/alias。
    core_norms = core_norm_names(actors)
    core: Set[str] = {
        u for u, n in node_by_uuid.items()
        if normalize_name(str(n.get("name") or "")) in core_norms
    }

    # 2) 邻接（无向、去自环、按边 uuid 去重）与度数。
    seen_edge_uuids: Set[str] = set()
    adj: Dict[str, Set[str]] = {u: set() for u in all_uuids}
    dedup_edges: List[Dict[str, Any]] = []
    for e in edges or []:
        eu = e.get("uuid")
        if eu and eu in seen_edge_uuids:
            continue
        if eu:
            seen_edge_uuids.add(eu)
        dedup_edges.append(e)
        s, t = e.get("source_node_uuid"), e.get("target_node_uuid")
        if s in adj and t in adj and s != t:
            adj[s].add(t)
            adj[t].add(s)
    degree = compute_node_degrees(dedup_edges)

    # 3) 多源 BFS 得到核心 N-hop 距离。候选必须在配置半径内；任意长路径可达不再
    #    构成保留理由，否则一个弱桥会让整个巨型连通分量绕过硬上限。
    distance: Dict[str, int] = {u: 0 for u in core}
    nhop: Set[str] = set(core)
    frontier = set(core)
    for depth in range(1, hops + 1):
        nxt: Set[str] = set()
        for u in frontier:
            for v in adj.get(u, ()):
                if v not in nhop:
                    nxt.add(v)
                    distance[v] = depth
        nhop |= nxt
        frontier = nxt
        if not frontier:
            break

    # 4) keep-set：核心恒保留（不受容量/类型上限约束——策展 actor 是图存在的理由）；
    #    其余候选只从 N-hop 内按距离、重要度补位。核心数超过配置时提升有效上限，
    #    绝不为了满足数值上限删除策展 actor。
    effective_cap = max(max_entities, len(core))

    def importance(u: str) -> float:
        return float(mentions.get(u, 0) or 0) + float(degree.get(u, 0) or 0) \
            + (1000.0 if u in core else 0.0)

    keep: Set[str] = set(core)
    keep_reason: Dict[str, str] = {u: "core" for u in core}
    type_counts: Dict[str, int] = {}
    for u in core:
        lbl = _primary_label(node_by_uuid[u])
        type_counts[lbl] = type_counts.get(lbl, 0) + 1

    candidates = [u for u in all_uuids if u not in keep and u in nhop]
    candidates.sort(key=lambda u: (
        distance.get(u, hops + 1),          # 离任一核心越近越优先
        -importance(u),
        str(node_by_uuid[u].get("name") or ""),
        u,
    ))
    type_capped = 0
    type_capped_nodes: Set[str] = set()
    for u in candidates:
        if len(keep) >= effective_cap:
            break
        lbl = _primary_label(node_by_uuid[u])
        if type_counts.get(lbl, 0) >= per_type_cap:
            type_capped += 1
            type_capped_nodes.add(u)
            continue
        keep.add(u)
        keep_reason[u] = "nhop" if u in nhop else "importance"
        type_counts[lbl] = type_counts.get(lbl, 0) + 1

    # 5) 硬剪枝：删除精确补集。min_degree 保留在函数签名/审计参数中以兼容旧调用方，
    #    但不再允许高 度数 或任意长连通路径绕过 actor-centered keep-set。
    delete: List[str] = [u for u in all_uuids if u not in keep]
    delete_by_reason: Dict[str, int] = {}
    for u in delete:
        if u not in nhop:
            reason = "outside_core_hops"
        elif u in type_capped_nodes:
            reason = "per_type_cap"
        else:
            reason = "capacity"
        delete_by_reason[reason] = delete_by_reason.get(reason, 0) + 1

    keep_by_reason: Dict[str, int] = {}
    for r in keep_reason.values():
        keep_by_reason[r] = keep_by_reason.get(r, 0) + 1

    stats = {
        "total_before": len(all_uuids),
        "core_count": len(core),
        "nhop_count": len(nhop),
        "keep_count": len(keep),
        "delete_count": len(delete),
        "effective_cap": effective_cap,
        "cap_overridden_by_core": len(core) > max_entities,
        "max_hop_retained": max((distance.get(u, 0) for u in keep), default=0),
        "keep_by_reason": keep_by_reason,
        "delete_by_reason": delete_by_reason,
        "type_capped": type_capped,
        "params": {
            "max_entities": max_entities,
            "hops": hops,
            "min_degree": min_degree,
            "per_type_cap": per_type_cap,
        },
    }
    stats.update(core_actor_match_stats(nodes, actors))
    return {"keep": keep, "delete": delete, "stats": stats}


# ----------------------------------------------------------------- side-effecting
def prune_graph(graph_id: str, actors: list) -> dict:
    """对已建成的图执行「核心 actor + 邻域 + 重要度」收敛剪枝，返回审计 dict。

    编排器在 resolve_entities 之后调用（别名已折叠），并把返回值写进
    handoff/graph_prune.json。任何失败都只降级（返回带 error 的审计），绝不让
    剪枝失败拖垮建图阶段。
    """
    started = time.monotonic()
    audit: Dict[str, Any] = {
        "graph_id": graph_id,
        "enabled": bool(getattr(Config, "GRAPH_PRUNE_ENABLED", True)),
        "kept": 0,
        "deleted": 0,
        "total_before": 0,
        "skipped_reason": None,
    }
    mutation_attempted = False
    if not audit["enabled"]:
        audit["skipped_reason"] = "GRAPH_PRUNE_ENABLED=false"
        audit["duration_s"] = 0.0
        return audit

    try:
        from .graphiti_client.runtime import get_runtime

        rt = get_runtime()
        nodes = rt.all_entity_nodes(graph_id)
        edges = rt.all_entity_edges(graph_id)
        mentions = rt.mention_counts(graph_id)
        audit["total_before"] = len(nodes)

        plan = plan_prune(nodes, edges, mentions, actors)
        stats = plan["stats"]
        audit.update(stats)
        audit["planned_keep"] = stats["keep_count"]

        try:
            min_core_coverage = max(
                0.0,
                min(1.0, float(getattr(Config, "GRAPH_PRUNE_MIN_CORE_COVERAGE", 0.8))),
            )
        except (TypeError, ValueError):
            min_core_coverage = 0.8
        audit["min_core_coverage"] = min_core_coverage
        coverage_too_low = (
            stats.get("core_actor_expected", 0) > 0
            and stats.get("core_actor_coverage", 0.0) < min_core_coverage
        )
        if stats["core_count"] == 0 or coverage_too_low:
            # 空/低覆盖核心集时 destructive prune 必须 fail closed；否则会围绕少数误命中
            # actor 删除其余主题。把计划值与实际未变图明确分开，避免审计谎报已删。
            audit["planned_delete"] = stats["delete_count"]
            audit["planned_keep_count"] = stats["keep_count"]
            audit["planned_delete_by_reason"] = dict(stats.get("delete_by_reason") or {})
            audit["delete_count"] = 0
            audit["planned_keep"] = stats["keep_count"]
            audit["kept"] = len(nodes)
            audit["keep_count"] = len(nodes)
            audit["delete_by_reason"] = {}
            audit["actual_after"] = len(nodes)
            audit["postcondition_ok"] = None
            audit["degraded"] = True
            audit["skipped_reason"] = (
                "no core actors matched in graph — prune skipped"
                if stats["core_count"] == 0
                else "core actor coverage below destructive-prune threshold — prune skipped"
            )
            logger.warning("[%s] %s", graph_id, audit["skipped_reason"])
            return audit

        delete_uuids: List[str] = plan["delete"]
        name_by_uuid = {n.get("uuid"): n.get("name") for n in nodes}
        audit["deleted_names_sample"] = [
            str(name_by_uuid.get(u) or u) for u in delete_uuids[:50]
        ]
        if delete_uuids:
            mutation_attempted = True
            result = rt.delete_entity_nodes(graph_id, delete_uuids)
            audit["deleted"] = int(result.get("deleted", 0))
            audit["delete_failed"] = int(result.get("failed", 0))
        else:
            audit["deleted"] = 0

        # 剪枝改变了图内容：清 UI 缓存，然后重新读取真实幸存图。删除可能部分失败，
        # 不能用「请求删除集合」虚构布局/上限已满足。
        invalidate_graph_cache(graph_id)
        actual_nodes: List[Dict[str, Any]] = []
        actual_edges: List[Dict[str, Any]] = []
        verification_ok = False
        try:
            actual_nodes = rt.all_entity_nodes(graph_id)
            actual_edges = rt.all_entity_edges(graph_id)
            actual_ids = {n.get("uuid") for n in actual_nodes if n.get("uuid")}
            planned_keep = set(plan["keep"])
            # Retry only victims present in the original immutable plan. A concurrently created
            # node is evidence that the survivor set changed and must degrade verification; it is
            # never silently added to destructive scope after the plan was reviewed.
            remaining_excess = sorted(
                (actual_ids - planned_keep) & set(delete_uuids)
            )
            if remaining_excess:
                # 一次有界重试：runtime 按批删除时可能有瞬时单点失败。仅重试真实读回后
                # 仍超出计划的节点，绝不扩大删除集合或循环重试。
                retry = rt.delete_entity_nodes(graph_id, remaining_excess)
                audit["delete_retry_requested"] = len(remaining_excess)
                audit["delete_retry_deleted"] = int(retry.get("deleted", 0))
                audit["delete_retry_failed"] = int(retry.get("failed", 0))
                audit["deleted"] = int(audit.get("deleted", 0)) + audit["delete_retry_deleted"]
                audit["delete_failed_initial"] = int(audit.get("delete_failed", 0))
                audit["delete_failed"] = audit["delete_retry_failed"]
                invalidate_graph_cache(graph_id)
                actual_nodes = rt.all_entity_nodes(graph_id)
                actual_edges = rt.all_entity_edges(graph_id)
                actual_ids = {n.get("uuid") for n in actual_nodes if n.get("uuid")}
            core_ids = {
                u for u, n in {n.get("uuid"): n for n in nodes if n.get("uuid")}.items()
                if normalize_name(str(n.get("name") or "")) in core_norm_names(actors)
            }
            audit["actual_after"] = len(actual_ids)
            audit["kept"] = len(actual_ids)
            audit["survivor_set_matches_plan"] = actual_ids == planned_keep
            audit["core_survived"] = core_ids <= actual_ids
            audit["cap_satisfied"] = len(actual_ids) <= stats["effective_cap"]
            postcondition_issues: List[str] = []
            if not audit["survivor_set_matches_plan"]:
                postcondition_issues.append("actual survivor set differs from planned keep-set")
            if not audit["core_survived"]:
                postcondition_issues.append("one or more core actors were deleted")
            if not audit["cap_satisfied"]:
                postcondition_issues.append("actual graph exceeds effective hard cap")
            if int(audit.get("delete_failed", 0) or 0) > 0:
                postcondition_issues.append("one or more requested deletions failed")
            audit["postcondition_issues"] = postcondition_issues
            audit["postcondition_ok"] = not postcondition_issues
            audit["degraded"] = bool(postcondition_issues)
            if postcondition_issues:
                audit["error"] = "graph pruning postcondition failed: " + "; ".join(postcondition_issues)
            verification_ok = True
        except Exception as exc:  # noqa: BLE001 — 删除已发生，核验未知必须显式失败
            audit["actual_after"] = None
            audit["kept"] = None
            audit["survivor_set_matches_plan"] = None
            audit["core_survived"] = None
            audit["cap_satisfied"] = None
            audit["postcondition_ok"] = False
            audit["postcondition_issues"] = ["unable to read graph after deletion"]
            audit["verification_error"] = str(exc)[:300]
            audit["degraded"] = True
            audit["error"] = "graph pruning postcondition could not be verified"
            logger.warning("[%s] post-prune verification failed: %s", graph_id, exc)

        # 布局是可选增强，与不可省略的删除后核验分开。只有读取到真实幸存图后才计算。
        if verification_ok and getattr(Config, "GRAPH_LAYOUT_PRECOMPUTE", True):
            try:
                positions = compute_layout_positions(actual_nodes, actual_edges)
                if positions:
                    store_layout_positions(graph_id, positions)
                    audit["layout_recomputed"] = True
            except Exception as exc:  # noqa: BLE001 — 布局失败不改变已核验的剪枝结果
                logger.warning("[%s] post-prune layout recompute failed: %s", graph_id, exc)
                audit["layout_recomputed"] = False

        log_result = logger.info if audit.get("postcondition_ok") is True else logger.warning
        log_result(
            "[%s] prune complete: before=%d planned_keep=%d actual_after=%s deleted=%d "
            "postcondition_ok=%s (by_reason=%s) in %.1fs",
            graph_id, audit["total_before"], audit["planned_keep"],
            audit.get("actual_after"), audit["deleted"], audit.get("postcondition_ok"),
            audit.get("delete_by_reason"), time.monotonic() - started,
        )
    except Exception as exc:  # noqa: BLE001 — 剪枝失败必须降级，绝不让建图阶段失败
        state_text = "graph may be partially mutated" if mutation_attempted else "mutation not started"
        logger.warning("[%s] prune_graph failed (%s): %s", graph_id, state_text, exc)
        audit["error"] = str(exc)[:300]
        audit["degraded"] = True
        audit["postcondition_ok"] = False
        audit["postcondition_issues"] = [
            "pruning failed after mutation began; graph state requires verification"
            if mutation_attempted
            else "pruning failed before a verified hard-cap result was produced"
        ]
        audit["mutation_state"] = "possibly_mutated" if mutation_attempted else "not_started"
    finally:
        audit["duration_s"] = round(time.monotonic() - started, 2)
    return audit
