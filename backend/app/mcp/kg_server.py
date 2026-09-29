"""DRF 知识图谱引擎 MCP 服务器（stdio 传输，官方 ``mcp`` SDK / FastMCP）。

把 ``app.services.zep_tools.ZepToolsService`` 已「工具化」的图谱函数暴露给 deer-flow 2.0
harness。运行方式（须从 backend 目录启动，使 ``import app.*`` 可解析；``python -m`` 会自动把
CWD 加入 sys.path）::

    /path/to/backend/.venv/bin/python -m app.mcp.kg_server --graph-id <id>

在 extensions_config.json 里注册为 stdio MCP server（command=上面的 venv python，
args=["-m","app.mcp.kg_server"]，可选把 ``--graph-id`` 或 ``DRF_MCP_KG_GRAPH_ID`` 环境变量传入）。

暴露的工具（工具名 → 底层 zep_tools 函数）：
- ``kg_search``            → ``ZepToolsService.search_graph`` / ``as_of_search``（按时点）
- ``kg_trace_cascade``     → ``ZepToolsService.trace_cascade``（source+target 因果路径 / center 多跳邻域）
- ``kg_entity_summary``    → ``ZepToolsService.get_entity_summary``（实体查询）
- ``kg_get_entities``      → ``ZepToolsService.get_entities_by_type`` / ``get_all_nodes``
- ``kg_centrality_priors`` → 基于 ``get_all_nodes``/``get_all_edges`` 的度中心性先验（确定性，无 LLM）
- ``kg_graph_statistics``  → ``ZepToolsService.get_graph_statistics``

可用性纪律（degrade-safe）：
- 启动 / ``tools/list`` 不构造 ZepToolsService、不触碰 FalkorDB/Graphiti——服务器永远能
  干净启动并列出工具，故 bridge research 早于任何图谱存在时也不会拖垮 harness。
- 每个工具在首次调用时才懒构造服务；图谱/存储缺失 → 返回结构化错误
  ``{"ok": False, "error": ...}``（清晰点明「图谱不可用」），并用 ``asyncio.wait_for`` 套超时上限，
  绝不 hang，也绝不把异常抛给协议层。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any, Callable, Dict, List, Optional

# 直接 `python app/mcp/kg_server.py` 或 harness 以非 backend CWD 拉起时的兜底：
# 把 backend 目录（parents[2]）放进 sys.path，使 `import app.*` 与 `-m app.mcp.kg_server` 等价。
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

SERVER_NAME = "drf-kg"

INSTRUCTIONS = (
    "DRF knowledge-graph engine backed by the project's temporal knowledge graph "
    "(local Graphiti/FalkorDB, or Zep-compatible backend). Tools cover hybrid "
    "semantic + BM25 search (kg_search, with optional point-in-time as_of "
    "filtering), multi-hop causal reasoning (kg_trace_cascade: source->target "
    "causal paths or a center entity's N-hop neighborhood), entity lookup "
    "(kg_entity_summary, kg_get_entities) and deterministic structural priors "
    "(kg_centrality_priors, kg_graph_statistics). Every tool accepts an optional "
    "graph_id; when omitted the server-level default graph (--graph-id or "
    "DRF_MCP_KG_GRAPH_ID) is used. When the graph/FalkorDB store is absent each "
    "tool returns a structured error {ok:false,error:...} rather than hanging."
)

# 进程级默认图谱 ID（--graph-id 或 DRF_MCP_KG_GRAPH_ID 环境变量），工具未显式传 graph_id 时使用。
_DEFAULT_GRAPH_ID: str = ""

# 懒构造的 ZepToolsService 单例（首次 tools/call 时才建，启动/列工具阶段永不触碰后端）。
_SERVICE: Any = None
_SERVICE_ERROR: Optional[str] = None


def _default_graph_id() -> str:
    """读取进程默认图谱 ID：优先 build_server/main 设定的模块级值，回退环境变量。"""
    return _DEFAULT_GRAPH_ID or (os.environ.get("DRF_MCP_KG_GRAPH_ID") or "").strip()


def _timeout_seconds() -> float:
    """单次工具调用的超时上限（秒）。DRF_MCP_KG_TIMEOUT 覆盖，默认 60；非法值回退 60。"""
    try:
        val = float(os.environ.get("DRF_MCP_KG_TIMEOUT", "60") or "60")
    except (TypeError, ValueError):
        val = 60.0
    return val if val > 0 else 60.0


def _resolve_graph_id(graph_id: Optional[str]) -> str:
    """把逐调用 graph_id 与进程默认合并；两者皆空则抛 ValueError（由工具包装折成结构化错误）。

    INFRA-10：graph_id 来自 LLM 工具调用，可能流向图谱工件路径（布局/kuzu）——非法 id 抛
    UnsafeIdError（ValueError 子类，同样折成结构化错误）。
    """
    gid = (graph_id or "").strip() or _default_graph_id()
    if not gid:
        raise ValueError(
            "缺少 graph_id：请在调用参数里传 graph_id，或用 --graph-id / "
            "DRF_MCP_KG_GRAPH_ID 配置进程默认图谱。"
        )
    from app.utils.security import safe_id
    return safe_id(gid, "graph")


def _get_service() -> Any:
    """懒构造并缓存 ZepToolsService。构造失败（缺依赖/后端不可用）→ 抛 RuntimeError，
    由工具包装折成结构化错误。首次失败后缓存原因，避免每次调用都重试昂贵的构造。"""
    global _SERVICE, _SERVICE_ERROR
    if _SERVICE is not None:
        return _SERVICE
    if _SERVICE_ERROR is not None:
        raise RuntimeError(_SERVICE_ERROR)
    try:
        from app.services.zep_tools import ZepToolsService  # 懒导入：启动阶段不连后端
        _SERVICE = ZepToolsService()
        return _SERVICE
    except Exception as exc:  # noqa: BLE001 — 构造失败点明「图谱/存储不可用」
        _SERVICE_ERROR = f"知识图谱后端不可用（ZepToolsService 构造失败）: {type(exc).__name__}: {exc}"
        raise RuntimeError(_SERVICE_ERROR) from exc


def _error_payload(exc: BaseException, graph_id: str = "") -> Dict[str, Any]:
    """把异常压成 LLM 可消费的结构化失败载荷（类型 + 消息，无堆栈噪音）。"""
    payload: Dict[str, Any] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if graph_id:
        payload["graph_id"] = graph_id
    return payload


async def _guarded(impl: Callable[..., Any], graph_id: Optional[str], *args: Any) -> Dict[str, Any]:
    """把同步的 zep_tools 调用（``impl(svc, graph_id, *args)``）丢进线程池 + 超时上限，
    异常/超时折成结构化错误。所有 KG 工具的公共出口：解析 graph_id、懒取服务、
    ``asyncio.wait_for(asyncio.to_thread(...))`` 执行并统一异常处理，绝不抛给协议层、绝不 hang。

    NOTE: 之所以**不**用带 ``functools.wraps`` 的通用装饰器，是因为 FastMCP 靠反射工具函数
    的签名生成 JSON schema——``wraps`` 会把内层 ``_impl(svc, graph_id, ...)`` 的签名泄漏成
    工具入参（暴露 svc/graph_id 位置参数、丢失 query/limit 等真实参数）。故各工具是**显式签名**
    的模块级 async 函数，仅在函数体里调用本 helper。"""
    gid = ""
    try:
        gid = _resolve_graph_id(graph_id)
        svc = _get_service()
        result = await asyncio.wait_for(
            asyncio.to_thread(impl, svc, gid, *args),
            timeout=_timeout_seconds(),
        )
        return {"ok": True, "graph_id": gid, "result": result}
    except asyncio.TimeoutError:
        return {
            "ok": False,
            "graph_id": gid,
            "error": f"TimeoutError: 图谱调用超过 {_timeout_seconds():.0f}s 未返回（已放弃，未 hang 协议）",
        }
    except Exception as exc:  # noqa: BLE001 — 工具面绝不向协议层抛异常
        return _error_payload(exc, gid)


# ==================== 工具实现（同步，签名首两参固定为 svc, graph_id；直接单元可测）====================

def _impl_search(svc: Any, graph_id: str, query: str, limit: int = 10,
                 scope: str = "edges", as_of: Optional[str] = None) -> str:
    """混合语义 + BM25 检索，返回最相关事实文本。as_of 非空则按时点过滤（as_of_search）。"""
    if as_of:
        res = svc.as_of_search(graph_id=graph_id, query=query, as_of=as_of, limit=limit, scope=scope)
    else:
        res = svc.search_graph(graph_id=graph_id, query=query, limit=limit, scope=scope)
    return res.to_text()


def _impl_trace_cascade(svc: Any, graph_id: str, source: str = "", target: str = "",
                        center: str = "", causal_only: bool = True) -> str:
    """沿图谱多跳追踪传导/级联：source+target → 有向因果路径；center → 多跳因果邻域。"""
    return svc.trace_cascade(graph_id=graph_id, source=source, target=target,
                             center=center, causal_only=causal_only)


def _impl_entity_summary(svc: Any, graph_id: str, entity_name: str) -> Dict[str, Any]:
    """返回指定实体的关系摘要（实体信息 + 相关事实 + 相关边）。"""
    return svc.get_entity_summary(graph_id=graph_id, entity_name=entity_name)


def _impl_get_entities(svc: Any, graph_id: str, entity_type: Optional[str] = None,
                       limit: int = 50) -> List[Dict[str, Any]]:
    """列出实体节点。entity_type 非空则按本体类型过滤，否则返回全部节点（截断至 limit）。"""
    if entity_type:
        nodes = svc.get_entities_by_type(graph_id=graph_id, entity_type=entity_type)
    else:
        nodes = svc.get_all_nodes(graph_id)
    out: List[Dict[str, Any]] = []
    for n in nodes[: max(1, int(limit))]:
        etype = next((l for l in n.labels if l not in ("Entity", "Node")), "")
        out.append({"uuid": n.uuid, "name": n.name, "type": etype, "summary": n.summary})
    return out


def _impl_centrality(svc: Any, graph_id: str, top_k: int = 20) -> Dict[str, Any]:
    """确定性度中心性先验：以入/出度之和度量结构影响力，归一化后取 Top-K。

    纯结构统计（无 LLM、无嵌入）：遍历全图边累计每个节点 uuid 的关联度，按最大度归一化。
    用于在模拟/预测前按结构影响力给 actor 加权。附带图谱统计（节点/边计数、实体类型分布）。"""
    nodes = svc.get_all_nodes(graph_id)
    edges = svc.get_all_edges(graph_id)
    name_by_uuid = {n.uuid: n.name for n in nodes if n.uuid}
    degree: Dict[str, int] = {}
    for e in edges:
        for u in (e.source_node_uuid, e.target_node_uuid):
            if u:
                degree[u] = degree.get(u, 0) + 1
    max_deg = max(degree.values()) if degree else 0
    ranked = sorted(degree.items(), key=lambda kv: kv[1], reverse=True)[: max(1, int(top_k))]
    top = [
        {
            "uuid": u,
            "name": name_by_uuid.get(u, u[:8]),
            "degree": d,
            "degree_centrality": round(d / max_deg, 4) if max_deg else 0.0,
        }
        for u, d in ranked
    ]
    stats = svc.get_graph_statistics(graph_id)
    return {
        "total_nodes": stats.get("total_nodes", len(nodes)),
        "total_edges": stats.get("total_edges", len(edges)),
        "entity_types": stats.get("entity_types", {}),
        "top_by_degree_centrality": top,
    }


def _impl_statistics(svc: Any, graph_id: str) -> Dict[str, Any]:
    """图谱统计：节点/边计数、实体类型分布、关系类型分布。"""
    return svc.get_graph_statistics(graph_id)


# ==================== 工具面（显式签名的模块级 async 函数；FastMCP 反射生成 JSON schema）====================
# 每个函数只在函数体里调用 _guarded(_impl_x, graph_id, ...)：显式签名让 schema 正确暴露真实入参
# （query/limit/... + 可选 graph_id），并统一超时 + 结构化错误。graph_id 恒为可选（回退进程默认）。

async def kg_search(query: str, limit: int = 10, scope: str = "edges",
                    as_of: Optional[str] = None, graph_id: Optional[str] = None) -> Dict[str, Any]:
    """Hybrid semantic + BM25 search over the knowledge graph."""
    return await _guarded(_impl_search, graph_id, query, limit, scope, as_of)


async def kg_trace_cascade(source: str = "", target: str = "", center: str = "",
                           causal_only: bool = True, graph_id: Optional[str] = None) -> Dict[str, Any]:
    """Trace directed causal paths (source+target) or an entity's N-hop neighborhood (center)."""
    return await _guarded(_impl_trace_cascade, graph_id, source, target, center, causal_only)


async def kg_entity_summary(entity_name: str, graph_id: Optional[str] = None) -> Dict[str, Any]:
    """Look up one entity by name and return its relationship summary."""
    return await _guarded(_impl_entity_summary, graph_id, entity_name)


async def kg_get_entities(entity_type: Optional[str] = None, limit: int = 50,
                          graph_id: Optional[str] = None) -> Dict[str, Any]:
    """List entities (nodes), optionally filtered by ontology type."""
    return await _guarded(_impl_get_entities, graph_id, entity_type, limit)


async def kg_centrality_priors(top_k: int = 20, graph_id: Optional[str] = None) -> Dict[str, Any]:
    """Deterministic degree-centrality structural priors + graph statistics."""
    return await _guarded(_impl_centrality, graph_id, top_k)


async def kg_graph_statistics(graph_id: Optional[str] = None) -> Dict[str, Any]:
    """Knowledge-graph statistics: node/edge counts and type distributions."""
    return await _guarded(_impl_statistics, graph_id)


# 工具名 → (函数, LLM 面向英文描述)。描述覆盖关键词，服务 deferred tool_search 语义匹配。
_TOOL_SPECS = (
    (
        "kg_search",
        kg_search,
        "Hybrid semantic + BM25 search over the knowledge graph with cross-encoder "
        "reranking. Returns the most relevant facts (edge facts and node summaries) "
        "as text. scope='edges' searches relationship facts (default); scope='nodes' "
        "searches entity summaries. Optional as_of (ISO or loose date) restricts "
        "results to facts valid at that point in time (point-in-time / temporal query). "
        "Optional graph_id overrides the server default. Use as the default retrieval "
        "tool for what the graph knows. Returns {ok, graph_id, result} or {ok:false,error}.",
    ),
    (
        "kg_trace_cascade",
        kg_trace_cascade,
        "Trace transmission / cascade chains through the knowledge graph and return "
        "human-readable path text. Two modes: pass source AND target to list directed "
        "multi-hop paths between them (preferring causal edge families "
        "CAUSES/ENABLES/CONSTRAINS/TRIGGERS/ACCELERATES); or pass center alone to list "
        "that entity's multi-hop causal neighborhood (N-hop subgraph). Entity names are "
        "resolved to canonical graph nodes automatically. causal_only=true (default) "
        "restricts to causal edges with a general-relation fallback. Use for 'how does X "
        "propagate to Y' or 'which node flips the outcome' reasoning.",
    ),
    (
        "kg_entity_summary",
        kg_entity_summary,
        "Look up one entity by name and return its relationship summary: the matched "
        "entity node (if any), related facts surfaced by search, and the entity's edges "
        "with source/target. Use to profile a single actor/organization before deeper "
        "traversal. Returns {ok, graph_id, result:{entity_name, entity_info, "
        "related_facts, related_edges, total_relations}}.",
    ),
    (
        "kg_get_entities",
        kg_get_entities,
        "List entities (nodes) of the knowledge graph with uuid, name, ontology type and "
        "summary. Optional entity_type filters by ontology label (e.g. 'PublicFigure', "
        "'Organization'); omit it to list all nodes. limit caps the number returned "
        "(default 50). Use the returned uuids for follow-up edge/summary lookups.",
    ),
    (
        "kg_centrality_priors",
        kg_centrality_priors,
        "Compute deterministic structural priors over the whole graph (no LLM): degree "
        "centrality per node (incident-edge count normalized by the max degree), the "
        "Top-K hub nodes by degree centrality, plus node/edge counts and entity-type "
        "distribution. Use to weight actors by structural influence before simulation or "
        "forecasting. top_k controls how many hubs are returned (default 20).",
    ),
    (
        "kg_graph_statistics",
        kg_graph_statistics,
        "Return knowledge-graph statistics: total node and edge counts, entity-type "
        "distribution and relationship-type distribution. Use for a quick structural "
        "overview / sanity check that the graph was built before deeper queries.",
    ),
)


def build_server(default_graph_id: str = ""):
    """构建并返回注册了全部 KG 工具的 FastMCP 实例（不启动传输）。

    ``mcp`` SDK 在函数内导入：让 ``import app.mcp.kg_server`` 在未装 SDK 的环境里也能干净失败
    （错误指向 requirements.txt），而非模块级 ImportError 连坐（tests 需能 import 本模块）。"""
    global _DEFAULT_GRAPH_ID
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - 环境缺依赖时的可读报错
        raise ImportError(
            "官方 mcp SDK 未安装。请执行 "
            "`backend/.venv/bin/pip install -r backend/requirements.txt`（含 'mcp'）。"
        ) from exc

    if default_graph_id:
        _DEFAULT_GRAPH_ID = default_graph_id

    server = FastMCP(SERVER_NAME, instructions=INSTRUCTIONS)
    for name, fn, description in _TOOL_SPECS:
        server.tool(name=name, description=description)(fn)
    return server


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="drf-kg-server",
        description="DRF KG engine MCP server (stdio) wrapping app.services.zep_tools.ZepToolsService.",
    )
    parser.add_argument(
        "--graph-id",
        default="",
        help="进程默认图谱 ID（工具未显式传 graph_id 时使用；亦可用 DRF_MCP_KG_GRAPH_ID 环境变量）。",
    )
    args = parser.parse_args(argv)
    default_gid = args.graph_id or (os.environ.get("DRF_MCP_KG_GRAPH_ID") or "").strip()
    server = build_server(default_graph_id=default_gid)
    # stdio 传输：stdout 只走 JSON-RPC，日志走 stderr（python logging 默认行为）。
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
