"""
Zep检索工具服务
封装图谱搜索、节点读取、边查询等工具，供Report Agent使用

核心检索工具（优化后）：
1. InsightForge（深度洞察检索）- 最强大的混合检索，自动生成子问题并多维度检索
2. PanoramaSearch（广度搜索）- 获取全貌，包括过期内容
3. QuickSearch（简单搜索）- 快速检索
"""

import re
import time
import json
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field

from .graphiti_client import Zep
# F-4-6: 引入后端错误类型，使 search_graph 只对预期的后端/连接/服务端错误降级，
# 而把编程/解析类缺陷暴露出来（ERROR + 重抛），不再被宽泛的 except 掩盖。
from .graphiti_client import ApiError, InternalServerError

from ..config import Config
from ..utils.ctxpool import submit_with_context
from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient
from ..utils.zep_paging import fetch_all_nodes, fetch_all_edges
from ..utils.zep_rate_limit import is_zep_rate_limit_error, zep_retry_delay_seconds
# EXECPLAN2 I-1-1: 宽松日期解析（ISO/斜杠/中文「年月日」/仅年月/仅年份 → UTC tz-aware），
# 用于 as-of（按时点）检索把字符串/日期统一成可下推到图谱时态过滤的 datetime。
from ..utils.dates import parse_as_of

logger = get_logger('mirofish.zep_tools')


def _interview_feedback_allowed(simulation_id: Optional[str],
                                feedback_allowed: Optional[bool] = None) -> bool:
    """FU-8: whether interview answers of ``simulation_id`` may be written to the graph.

    ``feedback_allowed`` is the gate the orchestrator resolved from the run's pin (main
    and seed reports, through ReportAgent) and wins; only True allows. Without it (None:
    /api/report regenerate and chat) the pinned value of the pipeline that ran the
    simulation decides (pipeline_orchestrator.interview_graph_feedback_for_simulation,
    imported lazily: the orchestrator imports this module). An import failure fails
    closed."""
    if feedback_allowed is not None:
        return feedback_allowed is True
    try:
        from .pipeline_orchestrator import interview_graph_feedback_for_simulation
    except Exception as exc:  # noqa: BLE001 — fail closed: no graph write without the pin
        logger.warning(f"安全政策钉不可读，采访事实不写入图谱（失败关闭）: {exc}")
        return False
    return interview_graph_feedback_for_simulation(simulation_id)


def compact_graph_query(text: str, max_chars: int = 350) -> str:
    """RPT-8/XRUN-5: 把整段需求书压成可用于图谱检索的紧凑查询（确定性，无 LLM）。

    整段 3388 字的预测需求书被当作 query 时，clamp 只保留开头的修辞性引言，检索
    从此锚定在「Two seismic forces …」而非真正的核心问题。这里按句界取前缀（避免
    截在半句中间），供调用方在把长文档当查询前先行压缩。文本不超限时原样返回。
    """
    t = " ".join(str(text or "").split())
    if len(t) <= max_chars:
        return t
    head = t[:max_chars]
    for sep in ("。", ". ", "! ", "? ", "！", "？", "；", "; "):
        idx = head.rfind(sep)
        if idx >= 40:  # 句界太靠前则弃用（避免只剩一个短标题）
            return head[:idx + len(sep)].strip()
    return (head.rsplit(" ", 1)[0] or head).strip()


def _semantic_clamp_query(query: str, max_chars: int) -> str:
    """KG-2: 语义保全式钳制——保留前缀 + 从被截尾部提取专名/数字 token 补进预算内，
    使尾部实体名与阈值数字在嵌入与 BM25 两条腿上都存活，而非被盲切丢弃。纯函数。"""
    head_budget = max(80, int(max_chars * 0.7))
    head = query[:head_budget].rsplit(" ", 1)[0] or query[:head_budget]
    tail = query[len(head):]
    # 专名（大写开头的词）与数字/年份 token；CJK 文本无大小写，数字仍可提取
    toks = re.findall(r"[A-Z][A-Za-z0-9\-\.]{2,}|\d[\d.,/%]*", tail)
    seen: set = set()
    out = head
    for t in toks:
        tl = t.lower()
        if tl in seen:
            continue
        seen.add(tl)
        if len(out) + 1 + len(t) > max_chars:
            break
        out += " " + t
    return out


@dataclass
class SearchResult:
    """搜索结果"""
    facts: List[str]
    edges: List[Dict[str, Any]]
    nodes: List[Dict[str, Any]]
    query: str
    total_count: int
    # F-4-6: 标记本次结果是否来自本地降级搜索（语义检索失败后的关键词兜底），
    # 让调用方能识别持续性降级，而非把降级结果误当成高质量语义命中。
    degraded: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "facts": self.facts,
            "edges": self.edges,
            "nodes": self.nodes,
            "query": self.query,
            "total_count": self.total_count,
            "degraded": self.degraded
        }

    def to_text(self) -> str:
        """转换为文本格式，供LLM理解"""
        # F-4-6: 降级搜索结果带上显式标记，便于人工/调用方察觉质量下降。
        degraded_marker = "（降级搜索）" if self.degraded else ""
        text_parts = [f"搜索查询: {self.query}{degraded_marker}", f"找到 {self.total_count} 条相关信息"]

        if self.facts:
            text_parts.append("\n### 相关事实:")
            for i, fact in enumerate(self.facts, 1):
                text_parts.append(f"{i}. {fact}")

        return "\n".join(text_parts)


@dataclass
class NodeInfo:
    """节点信息"""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes
        }

    def to_text(self) -> str:
        """转换为文本格式"""
        entity_type = next((l for l in self.labels if l not in ["Entity", "Node"]), "未知类型")
        return f"实体: {self.name} (类型: {entity_type})\n摘要: {self.summary}"


@dataclass
class EdgeInfo:
    """边信息"""
    uuid: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    source_node_name: Optional[str] = None
    target_node_name: Optional[str] = None
    # 时间信息
    created_at: Optional[str] = None
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    expired_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "fact": self.fact,
            "source_node_uuid": self.source_node_uuid,
            "target_node_uuid": self.target_node_uuid,
            "source_node_name": self.source_node_name,
            "target_node_name": self.target_node_name,
            "created_at": self.created_at,
            "valid_at": self.valid_at,
            "invalid_at": self.invalid_at,
            "expired_at": self.expired_at
        }

    def to_text(self, include_temporal: bool = False) -> str:
        """转换为文本格式"""
        source = self.source_node_name or self.source_node_uuid[:8]
        target = self.target_node_name or self.target_node_uuid[:8]
        base_text = f"关系: {source} --[{self.name}]--> {target}\n事实: {self.fact}"

        if include_temporal:
            valid_at = self.valid_at or "未知"
            invalid_at = self.invalid_at or "至今"
            base_text += f"\n时效: {valid_at} - {invalid_at}"
            if self.expired_at:
                base_text += f" (已过期: {self.expired_at})"

        return base_text

    @property
    def is_expired(self) -> bool:
        """是否已过期"""
        return self.expired_at is not None

    @property
    def is_invalid(self) -> bool:
        """是否已失效"""
        return self.invalid_at is not None


@dataclass
class InsightForgeResult:
    """
    深度洞察检索结果 (InsightForge)
    包含多个子问题的检索结果，以及综合分析
    """
    query: str
    simulation_requirement: str
    sub_queries: List[str]

    # 各维度检索结果
    semantic_facts: List[str] = field(default_factory=list)  # 语义搜索结果
    entity_insights: List[Dict[str, Any]] = field(default_factory=list)  # 实体洞察
    relationship_chains: List[str] = field(default_factory=list)  # 关系链

    # 统计信息
    total_facts: int = 0
    total_entities: int = 0
    total_relationships: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "simulation_requirement": self.simulation_requirement,
            "sub_queries": self.sub_queries,
            "semantic_facts": self.semantic_facts,
            "entity_insights": self.entity_insights,
            "relationship_chains": self.relationship_chains,
            "total_facts": self.total_facts,
            "total_entities": self.total_entities,
            "total_relationships": self.total_relationships
        }

    def to_text(self) -> str:
        """转换为详细的文本格式，供LLM理解"""
        text_parts = [
            f"## 未来预测深度分析",
            f"分析问题: {self.query}",
            f"预测场景: {self.simulation_requirement}",
            f"\n### 预测数据统计",
            f"- 相关预测事实: {self.total_facts}条",
            f"- 涉及实体: {self.total_entities}个",
            f"- 关系链: {self.total_relationships}条"
        ]

        # 子问题
        if self.sub_queries:
            text_parts.append(f"\n### 分析的子问题")
            for i, sq in enumerate(self.sub_queries, 1):
                text_parts.append(f"{i}. {sq}")

        # 语义搜索结果
        if self.semantic_facts:
            text_parts.append(f"\n### 【关键事实】(请在报告中引用这些原文)")
            for i, fact in enumerate(self.semantic_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")

        # 实体洞察
        if self.entity_insights:
            text_parts.append(f"\n### 【核心实体】")
            for entity in self.entity_insights:
                text_parts.append(f"- **{entity.get('name', '未知')}** ({entity.get('type', '实体')})")
                if entity.get('summary'):
                    text_parts.append(f"  摘要: \"{entity.get('summary')}\"")
                if entity.get('related_facts'):
                    text_parts.append(f"  相关事实: {len(entity.get('related_facts', []))}条")

        # 关系链
        if self.relationship_chains:
            text_parts.append(f"\n### 【关系链】")
            for chain in self.relationship_chains:
                text_parts.append(f"- {chain}")

        return "\n".join(text_parts)


@dataclass
class PanoramaResult:
    """
    广度搜索结果 (Panorama)
    包含所有相关信息，包括过期内容
    """
    query: str

    # 全部节点
    all_nodes: List[NodeInfo] = field(default_factory=list)
    # 全部边（包括过期的）
    all_edges: List[EdgeInfo] = field(default_factory=list)
    # 当前有效的事实
    active_facts: List[str] = field(default_factory=list)
    # 已过期/失效的事实（历史记录）
    historical_facts: List[str] = field(default_factory=list)

    # 统计
    total_nodes: int = 0
    total_edges: int = 0
    active_count: int = 0
    historical_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "all_nodes": [n.to_dict() for n in self.all_nodes],
            "all_edges": [e.to_dict() for e in self.all_edges],
            "active_facts": self.active_facts,
            "historical_facts": self.historical_facts,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "active_count": self.active_count,
            "historical_count": self.historical_count
        }

    def to_text(self) -> str:
        """转换为文本格式（完整版本，不截断）"""
        text_parts = [
            f"## 广度搜索结果（未来全景视图）",
            f"查询: {self.query}",
            f"\n### 统计信息",
            f"- 总节点数: {self.total_nodes}",
            f"- 总边数: {self.total_edges}",
            f"- 当前有效事实: {self.active_count}条",
            f"- 历史/过期事实: {self.historical_count}条"
        ]

        # 当前有效的事实（完整输出，不截断）
        if self.active_facts:
            text_parts.append(f"\n### 【当前有效事实】(模拟结果原文)")
            for i, fact in enumerate(self.active_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")

        # 历史/过期事实（完整输出，不截断）
        if self.historical_facts:
            text_parts.append(f"\n### 【历史/过期事实】(演变过程记录)")
            for i, fact in enumerate(self.historical_facts, 1):
                text_parts.append(f"{i}. \"{fact}\"")

        # 关键实体（完整输出，不截断）
        if self.all_nodes:
            text_parts.append(f"\n### 【涉及实体】")
            for node in self.all_nodes:
                entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), "实体")
                text_parts.append(f"- **{node.name}** ({entity_type})")

        # 类型化关系链（KG cookbook：把有向带类型边显式序列化为三元组行，并带边引用 [E<uuid8>]，
        # 让报告可在论断旁标注支撑边）。past to_text 只渲染自由文本 fact，丢掉了 typed 边结构。
        if self.all_edges:
            text_parts.append(f"\n### 【关系链】(有向带类型边，可作支撑引用)")
            for edge in self.all_edges[:40]:
                src = edge.source_node_name or (edge.source_node_uuid or "")[:8]
                tgt = edge.target_node_name or (edge.target_node_uuid or "")[:8]
                eref = (edge.uuid or "")[:8]
                prefix = f"[E{eref}] " if eref else ""
                text_parts.append(f"- {prefix}{src} --[{edge.name}]--> {tgt}")

        return "\n".join(text_parts)


@dataclass
class AgentInterview:
    """单个Agent的采访结果"""
    agent_name: str
    agent_role: str  # 角色类型（如：学生、教师、媒体等）
    agent_bio: str  # 简介
    question: str  # 采访问题
    response: str  # 采访回答
    key_quotes: List[str] = field(default_factory=list)  # 关键引言

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "agent_bio": self.agent_bio,
            "question": self.question,
            "response": self.response,
            "key_quotes": self.key_quotes
        }

    def to_text(self) -> str:
        text = f"**{self.agent_name}** ({self.agent_role})\n"
        # 显示完整的agent_bio，不截断
        text += f"_简介: {self.agent_bio}_\n\n"
        text += f"**Q:** {self.question}\n\n"
        text += f"**A:** {self.response}\n"
        if self.key_quotes:
            text += "\n**关键引言:**\n"
            for quote in self.key_quotes:
                # 清理各种引号
                clean_quote = quote.replace('\u201c', '').replace('\u201d', '').replace('"', '')
                clean_quote = clean_quote.replace('\u300c', '').replace('\u300d', '')
                clean_quote = clean_quote.strip()
                # 去掉开头的标点
                while clean_quote and clean_quote[0] in '，,；;：:、。！？\n\r\t ':
                    clean_quote = clean_quote[1:]
                # 过滤包含问题编号的垃圾内容（问题1-9）
                skip = False
                for d in '123456789':
                    if f'\u95ee\u9898{d}' in clean_quote:
                        skip = True
                        break
                if skip:
                    continue
                # 截断过长内容（按句号截断，而非硬截断）
                if len(clean_quote) > 150:
                    dot_pos = clean_quote.find('\u3002', 80)
                    if dot_pos > 0:
                        clean_quote = clean_quote[:dot_pos + 1]
                    else:
                        clean_quote = clean_quote[:147] + "..."
                if clean_quote and len(clean_quote) >= 10:
                    text += f'> "{clean_quote}"\n'
        return text


@dataclass
class InterviewResult:
    """
    采访结果 (Interview)
    包含多个模拟Agent的采访回答
    """
    interview_topic: str  # 采访主题
    interview_questions: List[str]  # 采访问题列表

    # 采访选择的Agent
    selected_agents: List[Dict[str, Any]] = field(default_factory=list)
    # 各Agent的采访回答
    interviews: List[AgentInterview] = field(default_factory=list)

    # 选择Agent的理由
    selection_reasoning: str = ""
    # 整合后的采访摘要
    summary: str = ""

    # 统计
    total_agents: int = 0
    interviewed_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interview_topic": self.interview_topic,
            "interview_questions": self.interview_questions,
            "selected_agents": self.selected_agents,
            "interviews": [i.to_dict() for i in self.interviews],
            "selection_reasoning": self.selection_reasoning,
            "summary": self.summary,
            "total_agents": self.total_agents,
            "interviewed_count": self.interviewed_count
        }

    def to_text(self) -> str:
        """转换为详细的文本格式，供LLM理解和报告引用"""
        text_parts = [
            "## 深度采访报告",
            f"**采访主题:** {self.interview_topic}",
            f"**采访人数:** {self.interviewed_count} / {self.total_agents} 位模拟Agent",
            "\n### 采访对象选择理由",
            self.selection_reasoning or "（自动选择）",
            "\n---",
            "\n### 采访实录",
        ]

        if self.interviews:
            for i, interview in enumerate(self.interviews, 1):
                text_parts.append(f"\n#### 采访 #{i}: {interview.agent_name}")
                text_parts.append(interview.to_text())
                text_parts.append("\n---")
        else:
            text_parts.append("（无采访记录）\n\n---")

        text_parts.append("\n### 采访摘要与核心观点")
        text_parts.append(self.summary or "（无摘要）")

        return "\n".join(text_parts)


def _roster_actor_for(name: Any, roster: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """INFRA-11: the one research-roster actor a name exactly denotes, else None.

    Its canonical name first, then an alias no other actor claims: an alias two actors list
    (or one equal to another actor's canonical name, where the canonical wins) denotes no
    single actor, so neither of them receives it.
    """
    from ..utils.actors import actor_match_candidates
    rows = actor_match_candidates(name, roster, exact_only=True)
    return rows[0] if len(rows) == 1 else None


class ZepToolsService:
    """
    Zep检索工具服务

    【核心检索工具 - 优化后】
    1. insight_forge - 深度洞察检索（最强大，自动生成子问题，多维度检索）
    2. panorama_search - 广度搜索（获取全貌，包括过期内容）
    3. quick_search - 简单搜索（快速检索）
    4. interview_agents - 深度采访（采访模拟Agent，获取多视角观点）

    【基础工具】
    - search_graph - 图谱语义搜索
    - get_all_nodes - 获取图谱所有节点
    - get_all_edges - 获取图谱所有边（含时间信息）
    - get_node_detail - 获取节点详细信息
    - get_node_edges - 获取节点相关的边
    - get_entities_by_type - 按类型获取实体
    - get_entity_summary - 获取实体的关系摘要
    """

    # 重试配置
    MAX_RETRIES = Config.ZEP_MAX_RETRIES
    RETRY_DELAY = Config.ZEP_RETRY_DELAY_SECONDS

    def __init__(self, api_key: Optional[str] = None, llm_client: Optional[LLMClient] = None):
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY 未配置")

        self.client = Zep(api_key=self.api_key)
        # LLM客户端用于InsightForge生成子问题
        self._llm_client = llm_client
        self._nodes_cache: Dict[str, List[NodeInfo]] = {}
        self._edges_cache: Dict[tuple[str, bool], List[EdgeInfo]] = {}
        # I-6-1: 跨 section 复用的检索缓存（图谱在报告阶段不可变）。默认关闭以保持现有行为，
        # 通过 Config.REPORT_RETRIEVAL_CACHE 开启；采访写图后通过 invalidate_search_cache 失效。
        self._search_cache: Dict[tuple, SearchResult] = {}
        self._forge_cache: Dict[tuple, InsightForgeResult] = {}
        # EXECPLAN2 I-6-3: guard the retrieval caches so concurrent section threads
        # (REPORT_SECTION_CONCURRENCY>1) can't crash on invalidate-during-iterate or
        # produce torn reads. Re-entrant (a cached path may re-enter via copy helpers).
        self._cache_lock = threading.RLock()
        # EXECPLAN2 I-1-6: 检索覆盖度追踪器（纯观测，try/except 包裹，绝不影响报告输出）。
        # 按 graph_id 累计本次报告运行中所有工具调用「触达」过的实体 uuid / 社区 id / 边类型，
        # 报告收尾时可 flush 成 handoff/retrieval_coverage.json，并对高影响 actor 覆盖不足告警。
        self._coverage: Dict[str, Dict[str, set]] = {}
        # EXECPLAN2 I-1-6: MMR 嵌入冗余抑制用的句向量缓存（事实文本 → 单位向量）。仅在
        # GRAPH_SEARCH_RECIPE=='mmr' 时按需填充；嵌入器懒加载失败则整体回退到精确字符串去重。
        self._fact_embed_cache: Dict[str, List[float]] = {}
        self._embedder = None  # 懒构建的本地句向量嵌入器（与图谱检索同源）
        self._embedder_unavailable = False  # 嵌入器不可用时置位，避免反复尝试
        # INFRA-11: 研究 actors.json 顶层对象（ReportAgent 构造时注入）。ACTOR_NAME_MATCH_STRICT 下
        # opinion_shift / _resolve_entity_name 先按名册（含别名）解析名字；None = 只按图谱/动作日志名匹配。
        self.actor_roster: Optional[Dict[str, Any]] = None
        logger.info("ZepToolsService 初始化完成")

    # I-6-1: 集中读取性能开关，默认 False/串行，缺少 Config 字段时回退到当前行为。
    @staticmethod
    def _retrieval_cache_enabled() -> bool:
        return bool(getattr(Config, "REPORT_RETRIEVAL_CACHE", False))

    @staticmethod
    def _retrieval_parallel_enabled() -> bool:
        return bool(getattr(Config, "REPORT_RETRIEVAL_PARALLEL", False))

    @staticmethod
    def _retrieval_parallel_workers() -> int:
        try:
            workers = int(getattr(Config, "REPORT_RETRIEVAL_PARALLEL_WORKERS", 4))
        except (TypeError, ValueError):
            workers = 4
        return max(1, workers)

    # EXECPLAN2 I-1-6: 集中读取检索 recipe 选择器。默认 'rrf'（与历史 RRF 行为逐字节一致）；
    # 设为 'mmr' 时 insight_forge 改用多样性感知检索并以嵌入冗余抑制替代精确字符串去重。
    @staticmethod
    def _search_recipe() -> str:
        val = getattr(Config, "GRAPH_SEARCH_RECIPE", "rrf")
        return (str(val).strip().lower() if val else "rrf")

    @staticmethod
    def _mmr_enabled() -> bool:
        return ZepToolsService._search_recipe() == "mmr"

    # EXECPLAN2 I-1-6: 高影响 actor 覆盖率告警阈值（[0,1]）。低于该值时记 WARNING（仅咨询性，
    # 不改变报告输出）。未配置 Config 字段时回退 0.6。
    @staticmethod
    def _min_actor_coverage() -> float:
        try:
            val = float(getattr(Config, "REPORT_MIN_ACTOR_COVERAGE", 0.6))
        except (TypeError, ValueError):
            val = 0.6
        # 夹到 [0,1]，避免误配置（如 60）触发恒为真/恒为假的告警。
        return min(1.0, max(0.0, val))

    def invalidate_search_cache(self, graph_id: Optional[str] = None) -> None:
        """I-6-1: 失效检索/洞察缓存。采访等写图操作后调用，避免返回陈旧检索结果。

        传入 graph_id 时仅清理该图谱相关缓存键；否则清空全部。"""
        with self._cache_lock:  # I-6-3: consistent vs concurrent get/set in other section threads
            if graph_id is None:
                self._search_cache.clear()
                self._forge_cache.clear()
                return
            # 缓存键首元素均为 graph_id，按图谱定向清理。
            for key in [k for k in self._search_cache if k and k[0] == graph_id]:
                self._search_cache.pop(key, None)
            for key in [k for k in self._forge_cache if k and k[0] == graph_id]:
                self._forge_cache.pop(key, None)

    @property
    def llm(self) -> LLMClient:
        """延迟初始化LLM客户端"""
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client

    def _call_with_retry(self, func, operation_name: str, max_retries: int = None):
        """带重试机制的API调用，Zep 429 时按 Retry-After 等待。"""
        max_retries = max_retries or self.MAX_RETRIES
        last_exception = None
        delay = self.RETRY_DELAY

        for attempt in range(max_retries):
            try:
                return func()
            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    sleep_for = (
                        zep_retry_delay_seconds(
                            e,
                            fallback=delay,
                            buffer_seconds=Config.ZEP_RATE_LIMIT_BUFFER_SECONDS,
                            max_sleep_seconds=Config.ZEP_RATE_LIMIT_MAX_SLEEP_SECONDS,
                        )
                        if is_zep_rate_limit_error(e)
                        else delay
                    )
                    logger.warning(
                        f"Zep {operation_name} 第 {attempt + 1} 次尝试失败: {str(e)[:100]}, "
                        f"{sleep_for:.1f}秒后重试..."
                    )
                    time.sleep(sleep_for)
                    delay *= 2
                else:
                    logger.error(f"Zep {operation_name} 在 {max_retries} 次尝试后仍失败: {str(e)}")

        raise last_exception

    def search_graph(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
        recipe: Optional[str] = None,
        search_filter: Optional[Dict[str, Any]] = None,
    ) -> SearchResult:
        """
        图谱语义搜索

        使用混合搜索（语义+BM25）在图谱中搜索相关信息。
        如果Zep Cloud的search API不可用，则降级为本地关键词匹配。

        Args:
            graph_id: 图谱ID (Standalone Graph)
            query: 搜索查询
            limit: 返回结果数量
            scope: 搜索范围，"edges" 或 "nodes"
            recipe: EXECPLAN2 I-1-6 可选检索 recipe 选择器（'rrf'|'mmr'|...）。None 时由
                runtime 用 Config.GRAPH_SEARCH_RECIPE（默认 'rrf'）决定，保持现有行为。
            search_filter: EXECPLAN2 I-1-1 可选时态/类型过滤字典（含 as_of/valid_at_*/
                invalid_at_* 等键），下推到图谱查询实现「按时点检索」。None 时不加过滤。

        Returns:
            SearchResult: 搜索结果
        """
        # QUALITY-OPT (a90b) + KG-2: 查询长度钳制。380 的紧限是 Zep Cloud 的 ~400 字符 400
        # 残留——本地 Graphiti/FalkorDB 没有该限制，盲用 380 会把 3388 字的需求书砍到只剩
        # 开头修辞句（嵌入与 BM25 都只见第一句）。默认改为：远端 Zep 380 / 本地 1200，可经
        # GRAPH_QUERY_MAX_CHARS 覆盖（0=自动）。仍超限时做语义保全钳制（前缀+尾部专名/数字
        # token），GRAPH_QUERY_CLAMP_SEMANTIC=False 回退旧的纯前缀切法。
        _default_max = 380 if getattr(Config, "GRAPHITI_REMOTE", False) else 1200
        _max_q = int(getattr(Config, "GRAPH_QUERY_MAX_CHARS", 0) or 0) or _default_max
        if isinstance(query, str) and len(query) > _max_q:
            _orig_len = len(query)
            if getattr(Config, "GRAPH_QUERY_CLAMP_SEMANTIC", True):
                query = _semantic_clamp_query(query, _max_q)
                logger.info(f"图谱搜索 query 过长（{_orig_len}>{_max_q}），已压缩至 {len(query)} 字符（保留前缀+尾部实体词）")
            else:
                query = query[:_max_q].rsplit(" ", 1)[0] or query[:_max_q]
                logger.info(f"图谱搜索 query 过长（{_orig_len}>{_max_q}），截断至 {len(query)} 字符")
        logger.info(f"图谱搜索: graph_id={graph_id}, query={query[:50]}...")

        # I-6-1: 命中跨 section 检索缓存则直接返回拷贝（避免调用方修改污染缓存）。
        # EXECPLAN2 I-1-1/I-1-6: 缓存键纳入 recipe 与 search_filter，避免不同 recipe / as-of
        # 时点的结果互相串档（同 query 但不同时态切片必须各自缓存）。
        cache_enabled = self._retrieval_cache_enabled()
        filter_key = json.dumps(search_filter, sort_keys=True, default=str) if search_filter else ""
        cache_key = (graph_id, (query or "").strip().lower(), limit, scope,
                     (recipe or "").strip().lower(), filter_key)
        if cache_enabled:
            with self._cache_lock:  # I-6-3
                cached = self._search_cache.get(cache_key)
            if cached is not None:
                logger.info("复用检索缓存命中（search_graph）")
                return self._copy_search_result(cached)

        # 尝试使用Zep Cloud Search API
        try:
            # EXECPLAN2 I-1-1/I-1-6: 仅在显式给出 recipe/search_filter 时透传，未给出则保持
            # 历史 4 参调用形态（runtime 默认 recipe + 无过滤），行为逐字节不变。
            search_kwargs: Dict[str, Any] = {
                "graph_id": graph_id,
                "query": query,
                "limit": limit,
                "scope": scope,
                "reranker": "cross_encoder",
            }
            if recipe:
                search_kwargs["recipe"] = recipe
            if search_filter:
                search_kwargs["search_filter"] = search_filter
            search_results = self._call_with_retry(
                func=lambda: self.client.graph.search(**search_kwargs),
                operation_name=f"图谱搜索(graph={graph_id})"
            )

            facts = []
            edges = []
            nodes = []

            # 解析边搜索结果
            if hasattr(search_results, 'edges') and search_results.edges:
                for edge in search_results.edges:
                    if hasattr(edge, 'fact') and edge.fact:
                        facts.append(edge.fact)
                    edges.append({
                        "uuid": getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', ''),
                        "name": getattr(edge, 'name', ''),
                        "fact": getattr(edge, 'fact', ''),
                        "source_node_uuid": getattr(edge, 'source_node_uuid', ''),
                        "target_node_uuid": getattr(edge, 'target_node_uuid', ''),
                    })

            # 解析节点搜索结果
            if hasattr(search_results, 'nodes') and search_results.nodes:
                for node in search_results.nodes:
                    nodes.append({
                        "uuid": getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                        "name": getattr(node, 'name', ''),
                        "labels": getattr(node, 'labels', []),
                        "summary": getattr(node, 'summary', ''),
                    })
                    # 节点摘要也算作事实
                    if hasattr(node, 'summary') and node.summary:
                        facts.append(f"[{node.name}]: {node.summary}")

            logger.info(f"搜索完成: 找到 {len(facts)} 条相关事实")

            result = SearchResult(
                facts=facts,
                edges=edges,
                nodes=nodes,
                query=query,
                total_count=len(facts)
            )
            if cache_enabled:
                with self._cache_lock:  # I-6-3
                    self._search_cache[cache_key] = self._copy_search_result(result)
            return result

        except (ApiError, InternalServerError, ConnectionError, TimeoutError, OSError) as e:
            # F-4-6: 仅对预期的后端/连接/服务端错误降级，保留对真实 API 故障的优雅退化。
            logger.warning(f"Zep Search API失败（已知后端/连接错误），降级为本地搜索: {str(e)}")
            return self._fallback_local_search(graph_id, query, limit, scope, cache_enabled, cache_key)
        except Exception as e:
            # F-4-6: 限流错误依然降级（_call_with_retry 已耗尽重试）；其余未知异常很可能是
            # 编程/解析类缺陷——记 ERROR + 堆栈并重抛，使真实回归可被诊断而非被静默掩盖。
            if is_zep_rate_limit_error(e):
                logger.warning(f"Zep Search API 限流，降级为本地搜索: {str(e)}")
                return self._fallback_local_search(graph_id, query, limit, scope, cache_enabled, cache_key)
            logger.error(f"Zep Search API 未预期异常（疑似程序/解析缺陷）: {str(e)}", exc_info=True)
            raise

    @staticmethod
    def _copy_search_result(result: SearchResult) -> SearchResult:
        """I-6-1: 返回 SearchResult 的浅拷贝（拷贝可变容器），避免缓存被调用方就地修改。"""
        return SearchResult(
            facts=list(result.facts),
            edges=[dict(e) for e in result.edges],
            nodes=[dict(n) for n in result.nodes],
            query=result.query,
            total_count=result.total_count,
            degraded=result.degraded,
        )

    def _fallback_local_search(
        self,
        graph_id: str,
        query: str,
        limit: int,
        scope: str,
        cache_enabled: bool,
        cache_key: tuple,
    ) -> SearchResult:
        """F-4-6/I-6-1: 统一的本地降级搜索出口，打上 degraded 标记并写入缓存。"""
        result = self._local_search(graph_id, query, limit, scope)
        result.degraded = True
        if cache_enabled:
            with self._cache_lock:  # I-6-3
                self._search_cache[cache_key] = self._copy_search_result(result)
        return result

    def _local_search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges"
    ) -> SearchResult:
        """
        本地关键词匹配搜索（作为Zep Search API的降级方案）

        获取所有边/节点，然后在本地进行关键词匹配

        Args:
            graph_id: 图谱ID
            query: 搜索查询
            limit: 返回结果数量
            scope: 搜索范围

        Returns:
            SearchResult: 搜索结果
        """
        logger.info(f"使用本地搜索: query={query[:30]}...")

        facts = []
        edges_result = []
        nodes_result = []

        # 提取查询关键词（简单分词）
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').replace('，', ' ').split() if len(w.strip()) > 1]

        def match_score(text: str) -> int:
            """计算文本与查询的匹配分数"""
            if not text:
                return 0
            text_lower = text.lower()
            # 完全匹配查询
            if query_lower in text_lower:
                return 100
            # 关键词匹配
            score = 0
            for keyword in keywords:
                if keyword in text_lower:
                    score += 10
            return score

        try:
            if scope in ["edges", "both"]:
                # 获取所有边并匹配
                all_edges = self.get_all_edges(graph_id)
                scored_edges = []
                for edge in all_edges:
                    score = match_score(edge.fact) + match_score(edge.name)
                    if score > 0:
                        scored_edges.append((score, edge))

                # 按分数排序
                scored_edges.sort(key=lambda x: x[0], reverse=True)

                for score, edge in scored_edges[:limit]:
                    if edge.fact:
                        facts.append(edge.fact)
                    edges_result.append({
                        "uuid": edge.uuid,
                        "name": edge.name,
                        "fact": edge.fact,
                        "source_node_uuid": edge.source_node_uuid,
                        "target_node_uuid": edge.target_node_uuid,
                    })

            if scope in ["nodes", "both"]:
                # 获取所有节点并匹配
                all_nodes = self.get_all_nodes(graph_id)
                scored_nodes = []
                for node in all_nodes:
                    score = match_score(node.name) + match_score(node.summary)
                    if score > 0:
                        scored_nodes.append((score, node))

                scored_nodes.sort(key=lambda x: x[0], reverse=True)

                for score, node in scored_nodes[:limit]:
                    nodes_result.append({
                        "uuid": node.uuid,
                        "name": node.name,
                        "labels": node.labels,
                        "summary": node.summary,
                    })
                    if node.summary:
                        facts.append(f"[{node.name}]: {node.summary}")

            logger.info(f"本地搜索完成: 找到 {len(facts)} 条相关事实")

        except Exception as e:
            logger.error(f"本地搜索失败: {str(e)}")

        return SearchResult(
            facts=facts,
            edges=edges_result,
            nodes=nodes_result,
            query=query,
            total_count=len(facts)
        )

    def search_from_cache(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "both",
    ) -> SearchResult:
        """I-6-5: 纯本地、基于已缓存全图节点/边的关键词匹配检索。

        供画像富集等阶段在 PROFILE_ENRICH_FROM_CACHE 模式下复用：当同一不可变图谱被按实体
        反复检索时（如 80 个 agent 各跑 2 次嵌入检索），可改为一次性 bulk 拉取（已缓存）+ 内存
        匹配评分，把 O(agents) 次嵌入往返收敛为 O(1) 次拉取。返回结果标记 degraded=True 以示其
        来自本地匹配而非嵌入语义检索。默认不被任何路径调用，仅由调用方显式选用，保持现有行为。
        """
        result = self._local_search(graph_id, query, limit, scope)
        result.degraded = True
        return result

    # ==================================================================
    # EXECPLAN2 I-1-1: 双时态「按时点」检索（as-of retrieval）
    # 预测本质是状态随时间演变。pipeline 已经在种子边（valid_at=as_of）与逐轮反馈边
    # （round 推导的 valid_at）上构建了真实的双时态轴，但此前检索从不按时间过滤，报告只能
    # 看到时间压平后的快照。as_of_search 把「valid_at <= D 且（invalid_at 为空 或 > D）」
    # 下推到图谱查询，只返回在时点 D 成立的事实，让「立场 X 在 T0 与 T_end 之间如何漂移」
    # 之类的轨迹/拐点论断有图谱级证据支撑。
    # ==================================================================
    @staticmethod
    def _as_of_filter(as_of: datetime) -> Dict[str, Any]:
        """构造下推到图谱查询的 as-of 时态过滤字典（runtime._to_search_filters 解析）。

        语义：valid_at <= as_of 且（invalid_at IS NULL OR invalid_at > as_of）。
        runtime 端把 null invalid_at 视为「仍然有效」并纳入结果，配合「null valid_at = 始终
        有效」的兜底，避免 LLM 文本抽取出的无时间戳边被时点过滤误删（覆盖率风险见 bundle）。
        """
        return {"as_of": as_of.isoformat()}

    def as_of_search(
        self,
        graph_id: str,
        query: str,
        as_of: Union[str, datetime, None],
        limit: int = 20,
        scope: str = "edges",
    ) -> SearchResult:
        """【AsOfSearch - 按时点检索】只返回在给定时点 ``as_of`` 成立的事实。

        Args:
            graph_id: 图谱ID
            query: 搜索查询
            as_of: 时点（datetime / ISO / 斜杠 / 中文「年月日」/ 仅年月 / 仅年份，宽松解析）。
                解析失败或为 None 时退化为全时段检索（等价 search_graph），保持现有行为。
            limit: 返回结果数量
            scope: 搜索范围

        Returns:
            SearchResult: 该时点成立的搜索结果。
        """
        parsed = parse_as_of(as_of)
        if parsed is None:
            # 无法解析 → 不加时态过滤，等价于普通语义检索（OFF-by-default 退化语义）。
            if as_of:
                logger.warning(f"as_of_search 无法解析时点 {as_of!r}，退化为全时段检索")
            return self.search_graph(graph_id=graph_id, query=query, limit=limit, scope=scope)
        logger.info(f"AsOfSearch 按时点检索: as_of={parsed.isoformat()}, query={query[:40]}...")
        return self.search_graph(
            graph_id=graph_id,
            query=query,
            limit=limit,
            scope=scope,
            search_filter=self._as_of_filter(parsed),
        )

    # ==================================================================
    # EXECPLAN2 I-1-6: MMR 多样性感知去重（嵌入冗余抑制）
    # insight_forge 此前用精确字符串集合去重，语义近重复的事实仍会挤占不同证据。当
    # GRAPH_SEARCH_RECIPE=='mmr' 时，改用本地句向量的余弦冗余抑制：若某事实与已选事实的
    # 最大余弦相似度超过阈值则丢弃，使最终事实集既相关又多样。嵌入器不可用 → 自动回退精确去重。
    # ==================================================================
    def _get_embedder(self):
        """懒构建与图谱检索同源的本地句向量嵌入器；不可用时置位并返回 None。"""
        if self._embedder_unavailable:
            return None
        if self._embedder is None:
            try:
                from .graphiti_client.embedder import LocalSentenceTransformerEmbedder
                self._embedder = LocalSentenceTransformerEmbedder()
            except Exception as e:  # 缺依赖/加载失败 → 回退精确去重，不影响检索
                logger.warning(f"MMR 嵌入器不可用，回退精确字符串去重: {e}")
                self._embedder_unavailable = True
                return None
        return self._embedder

    def _embed_facts(self, facts: List[str]) -> Dict[str, List[float]]:
        """批量嵌入事实文本（带进程内缓存），返回 {fact: 单位向量}；失败返回空 dict。"""
        embedder = self._get_embedder()
        if embedder is None:
            return {}
        # B8: 所有对 _fact_embed_cache 的 dict 读写加锁（与 insight_forge 并发 fan-out 一致），
        # 但**不**在持锁期间做慢速嵌入调用，避免串行化并发检索。
        with self._cache_lock:
            todo = [f for f in facts if f and f not in self._fact_embed_cache]
        if todo:
            try:
                # 嵌入器在后台事件循环线程上运行；通过 runtime 桥接同步取回 create_batch。
                from .graphiti_client.runtime import get_runtime
                vecs = get_runtime().run(embedder.create_batch(todo))
                with self._cache_lock:
                    for f, v in zip(todo, vecs):
                        self._fact_embed_cache[f] = v
            except Exception as e:
                logger.warning(f"MMR 事实嵌入失败，回退精确去重: {e}")
                self._embedder_unavailable = True
                return {}
        with self._cache_lock:
            return {f: self._fact_embed_cache[f] for f in facts if f in self._fact_embed_cache}

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        """两个单位向量的余弦相似度（嵌入器已 normalize，故为点积）。"""
        if not a or not b:
            return 0.0
        n = min(len(a), len(b))
        return sum(a[i] * b[i] for i in range(n))

    def _dedupe_facts_mmr(self, facts: List[str], threshold: float = 0.92) -> List[str]:
        """嵌入冗余抑制：按入参顺序贪心保留，与已选集最大余弦相似度 > 阈值者丢弃。

        先做精确字符串去重（保留首次出现），再做语义去重；嵌入不可用时只做精确去重，
        与历史 seen_facts 行为一致（OFF-by-default 退化）。"""
        exact: List[str] = []
        seen = set()
        for f in facts:
            if f and f not in seen:
                exact.append(f)
                seen.add(f)
        if not self._mmr_enabled():
            return exact
        embeds = self._embed_facts(exact)
        if not embeds:
            return exact  # 嵌入不可用 → 仅精确去重
        kept: List[str] = []
        kept_vecs: List[List[float]] = []
        for f in exact:
            v = embeds.get(f)
            if v is None:
                kept.append(f)  # 无向量者无法判冗余，保守保留
                continue
            if any(self._cosine(v, kv) > threshold for kv in kept_vecs):
                continue  # 语义近重复，丢弃
            kept.append(f)
            kept_vecs.append(v)
        if len(kept) < len(exact):
            logger.info(f"MMR 冗余抑制: {len(exact)} → {len(kept)} 条事实（阈值 {threshold}）")
        return kept

    # ==================================================================
    # EXECPLAN2 I-1-6: 检索覆盖度追踪（纯观测，绝不影响报告输出）
    # 记录本次报告运行中所有工具调用「触达」过的实体 uuid / 社区 id / 边类型，报告收尾时
    # 可 flush 成 handoff/retrieval_coverage.json，并对高影响 actor 覆盖不足发出咨询性告警，
    # 捕捉「自信地写了忽略整个派系的预测」这一最危险的静默质量缺陷。
    # ==================================================================
    def record_coverage(
        self,
        graph_id: str,
        *,
        entity_uuids: Optional[List[str]] = None,
        entity_names: Optional[List[str]] = None,
        community_ids: Optional[List[str]] = None,
        edge_types: Optional[List[str]] = None,
    ) -> None:
        """累计某次工具调用触达过的图谱元素。全程 try/except，任何异常都不外溢。"""
        try:
            bucket = self._coverage.setdefault(
                graph_id,
                {"entity_uuids": set(), "entity_names": set(), "community_ids": set(), "edge_types": set()},
            )
            for u in entity_uuids or []:
                if u:
                    bucket["entity_uuids"].add(str(u))
            for n in entity_names or []:
                if n:
                    bucket["entity_names"].add(str(n).strip().lower())
            for c in community_ids or []:
                if c:
                    bucket["community_ids"].add(str(c))
            for et in edge_types or []:
                if et:
                    bucket["edge_types"].add(str(et))
        except Exception as e:  # 观测代码绝不影响主流程
            logger.debug(f"record_coverage 跳过（不影响报告）: {e}")

    def get_coverage_report(
        self,
        graph_id: str,
        high_influence_actors: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """汇总本次运行对 ``graph_id`` 的检索覆盖度。

        Args:
            high_influence_actors: 高影响 actor 名（来自 actors.json influence=='high'）。
                提供时计算其被触达比例，低于阈值时返回 below_threshold=True 并记 WARNING。

        Returns:
            覆盖度摘要字典（可直接 json.dumps 写入 handoff/retrieval_coverage.json）。
        """
        bucket = self._coverage.get(graph_id) or {
            "entity_uuids": set(), "entity_names": set(), "community_ids": set(), "edge_types": set()
        }
        report: Dict[str, Any] = {
            "graph_id": graph_id,
            "surfaced_entity_count": len(bucket["entity_uuids"]) or len(bucket["entity_names"]),
            "surfaced_entity_uuids": sorted(bucket["entity_uuids"]),
            "surfaced_community_count": len(bucket["community_ids"]),
            "surfaced_edge_types": sorted(bucket["edge_types"]),
        }
        actors = [str(a).strip().lower() for a in (high_influence_actors or []) if str(a).strip()]
        if actors:
            surfaced_names = bucket["entity_names"]
            # 名字匹配：精确或子串（图谱实体名可能含头衔/限定词）。
            covered = [
                a for a in actors
                if a in surfaced_names or any(a in s or s in a for s in surfaced_names)
            ]
            ratio = len(covered) / len(actors) if actors else 1.0
            threshold = self._min_actor_coverage()
            below = ratio < threshold
            report.update({
                "high_influence_actor_total": len(actors),
                "high_influence_actor_covered": len(covered),
                "high_influence_actor_coverage": round(ratio, 3),
                "coverage_threshold": threshold,
                "below_threshold": below,
                "uncovered_high_influence_actors": sorted(set(actors) - set(covered)),
            })
            if below:
                logger.warning(
                    f"检索覆盖度告警: 高影响 actor 覆盖率 {ratio:.0%} < 阈值 {threshold:.0%}"
                    f"（{len(covered)}/{len(actors)}），报告可能忽略了重要参与者/派系"
                )
        return report

    def flush_coverage(
        self,
        graph_id: str,
        output_path: str,
        high_influence_actors: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """把覆盖度摘要原子写入 ``output_path``（如 handoff/retrieval_coverage.json）。

        全程 try/except；写盘失败只记 WARNING 并返回摘要，绝不影响报告产出。"""
        try:
            report = self.get_coverage_report(graph_id, high_influence_actors)
            from ..utils.atomic import write_json_atomic
            write_json_atomic(output_path, report)
            logger.info(f"检索覆盖度已写入 {output_path}")
            return report
        except Exception as e:
            logger.warning(f"flush_coverage 跳过（不影响报告）: {e}")
            return None

    def get_all_nodes(self, graph_id: str) -> List[NodeInfo]:
        """
        获取图谱的所有节点（分页获取）

        Args:
            graph_id: 图谱ID

        Returns:
            节点列表
        """
        # B8: 读缓存加锁（与并发章节线程的写保持一致，RLock 可重入）。
        with self._cache_lock:
            if graph_id in self._nodes_cache:
                logger.info(f"复用图谱 {graph_id} 的节点缓存: {len(self._nodes_cache[graph_id])} 个节点")
                return list(self._nodes_cache[graph_id])

        logger.info(f"获取图谱 {graph_id} 的所有节点...")

        nodes = fetch_all_nodes(
            self.client,
            graph_id,
            max_retries=Config.ZEP_MAX_RETRIES,
            retry_delay=Config.ZEP_RETRY_DELAY_SECONDS,
            rate_limit_buffer=Config.ZEP_RATE_LIMIT_BUFFER_SECONDS,
            rate_limit_max_sleep=Config.ZEP_RATE_LIMIT_MAX_SLEEP_SECONDS,
        )

        result = []
        for node in nodes:
            node_uuid = getattr(node, 'uuid_', None) or getattr(node, 'uuid', None) or ""
            result.append(NodeInfo(
                uuid=str(node_uuid) if node_uuid else "",
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {}
            ))

        logger.info(f"获取到 {len(result)} 个节点")
        # B8: 写缓存双检加锁，避免并发章节线程交错写 dict 撕裂；先到者写入，都返回一致结果。
        with self._cache_lock:
            if graph_id not in self._nodes_cache:
                self._nodes_cache[graph_id] = result
            return list(self._nodes_cache[graph_id])

    def get_all_edges(self, graph_id: str, include_temporal: bool = True) -> List[EdgeInfo]:
        """
        获取图谱的所有边（分页获取，包含时间信息）

        Args:
            graph_id: 图谱ID
            include_temporal: 是否包含时间信息（默认True）

        Returns:
            边列表（包含created_at, valid_at, invalid_at, expired_at）
        """
        cache_key = (graph_id, include_temporal)
        # B8: 读缓存加锁（与并发章节线程的写一致）。
        with self._cache_lock:
            if cache_key in self._edges_cache:
                logger.info(f"复用图谱 {graph_id} 的边缓存: {len(self._edges_cache[cache_key])} 条边")
                return list(self._edges_cache[cache_key])

        logger.info(f"获取图谱 {graph_id} 的所有边...")

        edges = fetch_all_edges(
            self.client,
            graph_id,
            max_retries=Config.ZEP_MAX_RETRIES,
            retry_delay=Config.ZEP_RETRY_DELAY_SECONDS,
            rate_limit_buffer=Config.ZEP_RATE_LIMIT_BUFFER_SECONDS,
            rate_limit_max_sleep=Config.ZEP_RATE_LIMIT_MAX_SLEEP_SECONDS,
        )

        result = []
        for edge in edges:
            edge_uuid = getattr(edge, 'uuid_', None) or getattr(edge, 'uuid', None) or ""
            edge_info = EdgeInfo(
                uuid=str(edge_uuid) if edge_uuid else "",
                name=edge.name or "",
                fact=edge.fact or "",
                source_node_uuid=edge.source_node_uuid or "",
                target_node_uuid=edge.target_node_uuid or ""
            )

            # 添加时间信息
            if include_temporal:
                edge_info.created_at = getattr(edge, 'created_at', None)
                edge_info.valid_at = getattr(edge, 'valid_at', None)
                edge_info.invalid_at = getattr(edge, 'invalid_at', None)
                edge_info.expired_at = getattr(edge, 'expired_at', None)

            result.append(edge_info)

        logger.info(f"获取到 {len(result)} 条边")
        # B8: 写缓存双检加锁，避免并发章节线程交错写 dict 撕裂。
        with self._cache_lock:
            if cache_key not in self._edges_cache:
                self._edges_cache[cache_key] = result
            return list(self._edges_cache[cache_key])

    def get_node_detail(self, node_uuid: str) -> Optional[NodeInfo]:
        """
        获取单个节点的详细信息

        Args:
            node_uuid: 节点UUID

        Returns:
            节点信息或None
        """
        logger.info(f"获取节点详情: {node_uuid[:8]}...")

        try:
            node = self._call_with_retry(
                func=lambda: self.client.graph.node.get(uuid_=node_uuid),
                operation_name=f"获取节点详情(uuid={node_uuid[:8]}...)"
            )

            if not node:
                return None

            return NodeInfo(
                uuid=getattr(node, 'uuid_', None) or getattr(node, 'uuid', ''),
                name=node.name or "",
                labels=node.labels or [],
                summary=node.summary or "",
                attributes=node.attributes or {}
            )
        except Exception as e:
            logger.error(f"获取节点详情失败: {str(e)}")
            return None

    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[EdgeInfo]:
        """
        获取节点相关的所有边

        通过获取图谱所有边，然后过滤出与指定节点相关的边

        Args:
            graph_id: 图谱ID
            node_uuid: 节点UUID

        Returns:
            边列表
        """
        logger.info(f"获取节点 {node_uuid[:8]}... 的相关边")

        try:
            # 获取图谱所有边，然后过滤
            all_edges = self.get_all_edges(graph_id)

            result = []
            for edge in all_edges:
                # 检查边是否与指定节点相关（作为源或目标）
                if edge.source_node_uuid == node_uuid or edge.target_node_uuid == node_uuid:
                    result.append(edge)

            logger.info(f"找到 {len(result)} 条与节点相关的边")
            return result

        except Exception as e:
            logger.warning(f"获取节点边失败: {str(e)}")
            return []

    def get_entities_by_type(
        self,
        graph_id: str,
        entity_type: str
    ) -> List[NodeInfo]:
        """
        按类型获取实体

        Args:
            graph_id: 图谱ID
            entity_type: 实体类型（如 Student, PublicFigure 等）

        Returns:
            符合类型的实体列表
        """
        logger.info(f"获取类型为 {entity_type} 的实体...")

        all_nodes = self.get_all_nodes(graph_id)

        filtered = []
        for node in all_nodes:
            # 检查labels是否包含指定类型
            if entity_type in node.labels:
                filtered.append(node)

        logger.info(f"找到 {len(filtered)} 个 {entity_type} 类型的实体")
        return filtered

    def get_entity_summary(
        self,
        graph_id: str,
        entity_name: str
    ) -> Dict[str, Any]:
        """
        获取指定实体的关系摘要

        搜索与该实体相关的所有信息，并生成摘要

        Args:
            graph_id: 图谱ID
            entity_name: 实体名称

        Returns:
            实体摘要信息
        """
        logger.info(f"获取实体 {entity_name} 的关系摘要...")

        # 先搜索该实体相关的信息
        search_result = self.search_graph(
            graph_id=graph_id,
            query=entity_name,
            limit=20
        )

        # 尝试在所有节点中找到该实体
        all_nodes = self.get_all_nodes(graph_id)
        entity_node = None
        for node in all_nodes:
            if node.name.lower() == entity_name.lower():
                entity_node = node
                break

        related_edges = []
        if entity_node:
            # 传入graph_id参数
            related_edges = self.get_node_edges(graph_id, entity_node.uuid)

        return {
            "entity_name": entity_name,
            "entity_info": entity_node.to_dict() if entity_node else None,
            "related_facts": search_result.facts,
            "related_edges": [e.to_dict() for e in related_edges],
            "total_relations": len(related_edges)
        }

    def _build_graph_statistics(
        self,
        graph_id: str,
        nodes: List[NodeInfo],
        edges: List[EdgeInfo],
    ) -> Dict[str, Any]:
        """Build graph statistics from already-loaded collections."""
        entity_types = {}
        for node in nodes:
            for label in node.labels:
                if label not in ["Entity", "Node"]:
                    entity_types[label] = entity_types.get(label, 0) + 1

        relation_types = {}
        for edge in edges:
            relation_types[edge.name] = relation_types.get(edge.name, 0) + 1

        return {
            "graph_id": graph_id,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "entity_types": entity_types,
            "relation_types": relation_types
        }

    def get_graph_statistics(self, graph_id: str) -> Dict[str, Any]:
        """
        获取图谱的统计信息

        Args:
            graph_id: 图谱ID

        Returns:
            统计信息
        """
        logger.info(f"获取图谱 {graph_id} 的统计信息...")

        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)
        return self._build_graph_statistics(graph_id, nodes, edges)

    def get_simulation_context(
        self,
        graph_id: str,
        simulation_requirement: str,
        limit: int = 30,
        search_query: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        获取模拟相关的上下文信息

        综合搜索与模拟需求相关的所有信息

        Args:
            graph_id: 图谱ID
            simulation_requirement: 模拟需求描述
            limit: 每类信息的数量限制
            search_query: RPT-8/XRUN-5 可选的紧凑检索查询。整段需求书作 query 会被长度
                钳制砍到只剩开头修辞句；调用方可传入预蒸馏的紧凑查询用于图谱检索，
                simulation_requirement 仍原样回显在返回值中。缺省 None → 行为与历史一致。

        Returns:
            模拟上下文信息
        """
        _q = (search_query or "").strip() or simulation_requirement
        logger.info(f"获取模拟上下文: {_q[:50]}...")

        # 搜索与模拟需求相关的信息
        search_result = self.search_graph(
            graph_id=graph_id,
            query=_q,
            limit=limit
        )

        # 获取图谱快照一次，后续统计和实体列表都复用这份数据。
        all_nodes = self.get_all_nodes(graph_id)
        all_edges = self.get_all_edges(graph_id)
        stats = self._build_graph_statistics(graph_id, all_nodes, all_edges)

        # 筛选有实际类型的实体（非纯Entity节点）
        entities = []
        for node in all_nodes:
            custom_labels = [l for l in node.labels if l not in ["Entity", "Node"]]
            if custom_labels:
                entities.append({
                    "name": node.name,
                    "type": custom_labels[0],
                    "summary": node.summary
                })

        return {
            "simulation_requirement": simulation_requirement,
            "related_facts": search_result.facts,
            "graph_statistics": stats,
            "entities": entities[:limit],  # 限制数量
            "total_entities": len(entities)
        }

    # ========== 核心检索工具（优化后） ==========

    def insight_forge(
        self,
        graph_id: str,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_sub_queries: int = 5,
        as_of: Union[str, datetime, None] = None,
    ) -> InsightForgeResult:
        """
        【InsightForge - 深度洞察检索】

        最强大的混合检索函数，自动分解问题并多维度检索：
        1. 使用LLM将问题分解为多个子问题
        2. 对每个子问题进行语义搜索
        3. 提取相关实体并获取其详细信息
        4. 追踪关系链
        5. 整合所有结果，生成深度洞察

        Args:
            graph_id: 图谱ID
            query: 用户问题
            simulation_requirement: 模拟需求描述
            report_context: 报告上下文（可选，用于更精准的子问题生成）
            max_sub_queries: 最大子问题数量
            as_of: EXECPLAN2 I-1-1 可选时点。给出时只检索在该时点成立的事实（按时点视图，
                如「round 0 状态 vs 最终轮」）；None（默认）保持全时段行为不变。

        Returns:
            InsightForgeResult: 深度洞察检索结果
        """
        logger.info(f"InsightForge 深度洞察检索: {query[:50]}...")

        # EXECPLAN2 I-1-1: 解析 as-of 时点；可解析时构造下推过滤字典，否则不加时态过滤。
        as_of_dt = parse_as_of(as_of)
        as_of_filter = self._as_of_filter(as_of_dt) if as_of_dt is not None else None
        # EXECPLAN2 I-1-6: MMR 时改用多样性感知 recipe；'rrf' 时不传 recipe（保持默认）。
        recipe = "mmr" if self._mmr_enabled() else None

        # I-6-1: 命中跨 section 的 InsightForge 缓存则直接返回（图谱在报告阶段不可变）。
        # 默认关闭，由 Config.REPORT_RETRIEVAL_CACHE 控制；采访写图后通过 invalidate_search_cache 失效。
        # EXECPLAN2 I-1-1/I-1-6: 缓存键纳入 as_of 与 recipe，避免不同时点/不同 recipe 串档。
        forge_cache_enabled = self._retrieval_cache_enabled()
        forge_key = (graph_id, (query or "").strip().lower(), (simulation_requirement or "").strip().lower(),
                     hash((report_context or "").strip()), max_sub_queries,
                     as_of_dt.isoformat() if as_of_dt else "", recipe or "")
        if forge_cache_enabled:
            with self._cache_lock:  # I-6-3
                cached_forge = self._forge_cache.get(forge_key)
            if cached_forge is not None:
                logger.info("复用 InsightForge 缓存命中")
                return cached_forge

        result = InsightForgeResult(
            query=query,
            simulation_requirement=simulation_requirement,
            sub_queries=[]
        )

        # Step 1: 使用LLM生成子问题
        sub_queries = self._generate_sub_queries(
            query=query,
            simulation_requirement=simulation_requirement,
            report_context=report_context,
            max_queries=max_sub_queries
        )
        result.sub_queries = sub_queries
        logger.info(f"生成 {len(sub_queries)} 个子问题")

        # Step 2: 对每个子问题进行语义搜索（I-6-1: 可选并行扇出，默认串行保持原顺序）
        all_facts = []
        all_edges = []

        # (子问题, limit) 列表 + 原始问题，统一调度，便于并行。
        search_specs = [(sq, 15) for sq in sub_queries]
        search_specs.append((query, 20))  # 原始问题用更大的 limit

        if self._retrieval_parallel_enabled() and len(search_specs) > 1:
            # 检索路径是 I/O 密集且线程安全（与 oasis_profile_generator 的并行边/点检索同源），
            # 用有界线程池并发扇出，墙钟时间趋近最慢的单次检索而非求和。
            from concurrent.futures import ThreadPoolExecutor

            ordered_results: List[Optional[SearchResult]] = [None] * len(search_specs)
            workers = min(self._retrieval_parallel_workers(), len(search_specs))
            with ThreadPoolExecutor(max_workers=workers) as ex:
                # EXECPLAN2 I-1-1/I-1-6: 透传 recipe（MMR）与 as-of 时态过滤到每次检索。
                # INFRA-9：每个检索任务带一份提交线程的 contextvars 副本（run/stage/report 归属）。
                future_to_idx = {
                    submit_with_context(
                        ex, self.search_graph, graph_id, spec_q, spec_limit, "edges",
                        recipe, as_of_filter,
                    ): idx
                    for idx, (spec_q, spec_limit) in enumerate(search_specs)
                }
                for fut, idx in future_to_idx.items():
                    try:
                        ordered_results[idx] = fut.result()
                    except Exception as e:  # noqa: BLE001  保持单次检索失败不影响整体扇出
                        logger.warning(f"子问题并行检索失败（跳过该项）: {e}")
            search_results_list = [r for r in ordered_results if r is not None]
        else:
            search_results_list = [
                self.search_graph(
                    graph_id=graph_id, query=spec_q, limit=spec_limit, scope="edges",
                    recipe=recipe, search_filter=as_of_filter,
                )
                for spec_q, spec_limit in search_specs
            ]

        # 合并所有事实（保持确定性先后次序），再统一去重。
        merged_facts: List[str] = []
        for search_result in search_results_list:
            merged_facts.extend(search_result.facts)
            all_edges.extend(search_result.edges)

        # EXECPLAN2 I-1-6: MMR 开启时用嵌入冗余抑制（含精确去重）替代纯字符串去重，
        # 使事实集既相关又多样；关闭时 _dedupe_facts_mmr 仅做精确去重，等价历史行为。
        all_facts = self._dedupe_facts_mmr(merged_facts)

        result.semantic_facts = all_facts
        result.total_facts = len(all_facts)

        # Step 3: 从边中提取相关实体UUID，只获取这些实体的信息（不获取全部节点）
        entity_uuids = set()
        for edge_data in all_edges:
            if isinstance(edge_data, dict):
                source_uuid = edge_data.get('source_node_uuid', '')
                target_uuid = edge_data.get('target_node_uuid', '')
                if source_uuid:
                    entity_uuids.add(source_uuid)
                if target_uuid:
                    entity_uuids.add(target_uuid)

        # 获取所有相关实体的详情（不限制数量，完整输出）
        entity_insights = []
        node_map = {}  # 用于后续关系链构建

        # F-4-3: 用一次（已缓存的）全图节点快照取代每个 UUID 一次的 get_node_detail 阻塞往返。
        # get_all_nodes(graph_id) 会分页拉全图并缓存；本会话若已调用过则直接命中缓存。
        # 仅当 UUID 不在快照中（跨图/陈旧）时才回退 get_node_detail，行为保持等价。
        snapshot = {n.uuid: n for n in self.get_all_nodes(graph_id) if n.uuid}

        for uuid in list(entity_uuids):  # 处理所有实体，不截断
            if not uuid:
                continue
            try:
                # F-4-3: 优先用快照命中，缺失才回退单点查询（保留原跨图/陈旧 UUID 兜底语义）。
                node = snapshot.get(uuid) or self.get_node_detail(uuid)
                if node:
                    node_map[uuid] = node
                    entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), "实体")

                    # 获取该实体相关的所有事实（不截断）
                    related_facts = [
                        f for f in all_facts
                        if node.name.lower() in f.lower()
                    ]

                    entity_insights.append({
                        "uuid": node.uuid,
                        "name": node.name,
                        "type": entity_type,
                        "summary": node.summary,
                        "related_facts": related_facts  # 完整输出，不截断
                    })
            except Exception as e:
                logger.debug(f"获取节点 {uuid} 失败: {e}")
                continue

        result.entity_insights = entity_insights
        result.total_entities = len(entity_insights)

        # R2-KG-9: 追加一次 node-scope 混合检索，把节点摘要直接折叠进 entity_insights。
        # 边检索（scope="edges"）只能触达「有出/入边」的实体；摘要丰富但少边的关键节点
        # （如刚被提及的机构、概念性 actor）会被漏掉。node-scope 检索按原始 query 召回这些
        # 节点，去重后补进洞察集；节点摘要经 MMR 冗余抑制（_mmr_enabled 时语义去冗，否则精确
        # 去重）避免与已有实体重复。全程 try/except，失败跳过，保持现有行为不变。
        node_scope_names: List[str] = []
        try:
            node_search = self.search_graph(
                graph_id=graph_id, query=query, limit=10, scope="nodes",
                recipe=recipe, search_filter=as_of_filter,
            )
            existing_uuids = {ei.get("uuid") for ei in entity_insights if ei.get("uuid")}
            existing_names = {(ei.get("name") or "").strip().lower()
                              for ei in entity_insights if ei.get("name")}
            candidates: List[tuple] = []  # (node_dict, summary_blob)
            for nd in node_search.nodes:
                nm = str(nd.get("name", "") or "").strip()
                summ = str(nd.get("summary", "") or "").strip()
                uid = nd.get("uuid") or ""
                if not nm or not summ:
                    continue
                if (uid and uid in existing_uuids) or nm.lower() in existing_names:
                    continue
                candidates.append((nd, f"[{nm}]: {summ}"))
            # MMR/精确去重补充节点摘要，去掉与彼此语义近重复的条目。
            kept_blobs = set(self._dedupe_facts_mmr([blob for _, blob in candidates]))
            for nd, blob in candidates:
                if blob not in kept_blobs:
                    continue
                nm = str(nd.get("name", "")).strip()
                if nm.lower() in existing_names:  # 防止本批内重名重复
                    continue
                labels = nd.get("labels") or []
                entity_type = next((l for l in labels if l not in ["Entity", "Node"]), "实体")
                entity_insights.append({
                    "uuid": nd.get("uuid") or "",
                    "name": nm,
                    "type": entity_type,
                    "summary": str(nd.get("summary", "") or ""),
                    "related_facts": [f for f in all_facts if nm.lower() in f.lower()],
                })
                existing_names.add(nm.lower())
                node_scope_names.append(nm)
            if node_scope_names:
                result.total_entities = len(entity_insights)
                logger.info(f"InsightForge: node-scope 检索折叠 {len(node_scope_names)} 个补充实体")
        except Exception as exc:  # noqa: BLE001  node-scope 是增强项，失败不影响主流程
            logger.debug(f"InsightForge node-scope 检索跳过（不影响报告）: {exc}")

        # Step 4: 构建所有关系链（不限制数量）
        relationship_chains = []
        for edge_data in all_edges:  # 处理所有边，不截断
            if isinstance(edge_data, dict):
                source_uuid = edge_data.get('source_node_uuid', '')
                target_uuid = edge_data.get('target_node_uuid', '')
                relation_name = edge_data.get('name', '')

                source_name = node_map.get(source_uuid, NodeInfo('', '', [], '', {})).name or source_uuid[:8]
                target_name = node_map.get(target_uuid, NodeInfo('', '', [], '', {})).name or target_uuid[:8]

                # 边引用句柄（KG cookbook 可追溯检索）：给关系链加 [E<uuid8>] 前缀，
                # 让报告能在论断旁标注具体支撑边。保持 "src --[rel]--> tgt" 为子串不变。
                eref = str(edge_data.get('uuid') or edge_data.get('uuid_') or '')[:8]
                chain = f"{source_name} --[{relation_name}]--> {target_name}"
                if eref:
                    chain = f"[E{eref}] {chain}"
                if chain not in relationship_chains:
                    relationship_chains.append(chain)

        result.relationship_chains = relationship_chains
        result.total_relationships = len(relationship_chains)

        logger.info(f"InsightForge完成: {result.total_facts}条事实, {result.total_entities}个实体, {result.total_relationships}条关系")

        # EXECPLAN2 I-1-6: 记录本次检索触达的实体（uuid+name）与边类型，供报告收尾时
        # 评估覆盖度。纯观测，record_coverage 内部已 try/except 兜底。
        self.record_coverage(
            graph_id,
            entity_uuids=list(node_map.keys()),
            # R2-KG-9: node-scope 补充实体也计入覆盖度，避免低估触达面。
            entity_names=[n.name for n in node_map.values() if n.name] + node_scope_names,
            edge_types=[
                e.get("name", "") for e in all_edges if isinstance(e, dict) and e.get("name")
            ],
        )

        # I-6-1: 写入 InsightForge 缓存，供后续 section 复用（写图后会被 invalidate_search_cache 失效）。
        if forge_cache_enabled:
            with self._cache_lock:  # I-6-3
                self._forge_cache[forge_key] = result
        return result

    def _generate_sub_queries(
        self,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_queries: int = 5
    ) -> List[str]:
        """
        使用LLM生成子问题

        将复杂问题分解为多个可以独立检索的子问题
        """
        system_prompt = """你是一个专业的问题分析专家。你的任务是将一个复杂问题分解为多个可以在模拟世界中独立观察的子问题。

要求：
1. 每个子问题应该足够具体，可以在模拟世界中找到相关的Agent行为或事件
2. 子问题应该覆盖原问题的不同维度（如：谁、什么、为什么、怎么样、何时、何地）
3. 子问题应该与模拟场景相关
4. 返回JSON格式：{"sub_queries": ["子问题1", "子问题2", ...]}"""

        user_prompt = f"""模拟需求背景：
{simulation_requirement}

{f"报告上下文：{report_context[:500]}" if report_context else ""}

请将以下问题分解为{max_queries}个子问题：
{query}

返回JSON格式的子问题列表。"""

        try:
            # EXECPLAN2 I-6-2: 子问题分解是机械型结构化任务，路由到 fast 档省钱省时；
            # 关闭 tiered routing 或 CLI 订阅提供方时 tier 为 no-op，行为不变。
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                tier="fast"
            )

            sub_queries = response.get("sub_queries", [])
            # 确保是字符串列表
            return [str(sq) for sq in sub_queries[:max_queries]]

        except Exception as e:
            logger.warning(f"生成子问题失败: {str(e)}，使用默认子问题")
            # 降级：返回基于原问题的变体。RPT-8：超长原问题（如整段需求书）的四个变体
            # 会在检索钳制时被切成同一段前缀，先压缩再派生变体，变体才有区分度。
            base = compact_graph_query(query, 300)
            return [
                base,
                f"{base} 的主要参与者",
                f"{base} 的原因和影响",
                f"{base} 的发展过程"
            ][:max_queries]

    def panorama_search(
        self,
        graph_id: str,
        query: str,
        include_expired: bool = True,
        limit: int = 50,
        as_of: Union[str, datetime, None] = None,
    ) -> PanoramaResult:
        """
        【PanoramaSearch - 广度搜索】

        获取全貌视图，包括所有相关内容和历史/过期信息：
        1. 获取所有相关节点
        2. 获取所有边（包括已过期/失效的）
        3. 分类整理当前有效和历史信息

        这个工具适用于需要了解事件全貌、追踪演变过程的场景。

        Args:
            graph_id: 图谱ID
            query: 搜索查询（用于相关性排序）
            include_expired: 是否包含过期内容（默认True）
            limit: 返回结果数量限制
            as_of: EXECPLAN2 I-1-1 可选时点。给出时按「在该时点是否成立」划分有效/历史
                （valid_at<=as_of 且 invalid_at 为空或晚于 as_of → 有效；已在 as_of 前失效/
                过期 → 历史），用于「某时点的全景快照」。None（默认）保持原「当前是否过期/失效」
                的划分，行为不变。

        Returns:
            PanoramaResult: 广度搜索结果
        """
        logger.info(f"PanoramaSearch 广度搜索: {query[:50]}...")

        # EXECPLAN2 I-1-1: 解析 as-of 时点（无法解析则退化为全时段/当前划分）。
        as_of_dt = parse_as_of(as_of)

        result = PanoramaResult(query=query)

        # 获取所有节点
        all_nodes = self.get_all_nodes(graph_id)
        node_map = {n.uuid: n for n in all_nodes}
        result.all_nodes = all_nodes
        result.total_nodes = len(all_nodes)

        # 获取所有边（包含时间信息）
        all_edges = self.get_all_edges(graph_id, include_temporal=True)
        result.all_edges = all_edges
        result.total_edges = len(all_edges)

        # 分类事实
        active_facts = []
        historical_facts = []

        for edge in all_edges:
            if not edge.fact:
                continue

            if as_of_dt is not None:
                # EXECPLAN2 I-1-1: 按时点划分。无 valid_at 视为「始终有效」（避免文本抽取的
                # 无时间戳边被误删，见 bundle 风险缓解）；invalid_at/expired_at 早于 as_of → 历史。
                valid_dt = parse_as_of(edge.valid_at)
                end_dt = parse_as_of(edge.invalid_at) or parse_as_of(edge.expired_at)
                started = (valid_dt is None) or (valid_dt <= as_of_dt)
                ended = (end_dt is not None) and (end_dt <= as_of_dt)
                if started and not ended:
                    active_facts.append(edge.fact)
                elif ended:
                    valid_at = edge.valid_at or "未知"
                    invalid_at = edge.invalid_at or edge.expired_at or "未知"
                    historical_facts.append(f"[{valid_at} - {invalid_at}] {edge.fact}")
                # else: 在 as_of 时尚未生效 → 既非有效也非历史，跳过（未来事实）。
                continue

            # 默认（无 as_of）：按「当前是否过期/失效」划分，行为不变。
            is_historical = edge.is_expired or edge.is_invalid
            if is_historical:
                # 历史/过期事实，添加时间标记
                valid_at = edge.valid_at or "未知"
                invalid_at = edge.invalid_at or edge.expired_at or "未知"
                fact_with_time = f"[{valid_at} - {invalid_at}] {edge.fact}"
                historical_facts.append(fact_with_time)
            else:
                # 当前有效事实
                active_facts.append(edge.fact)

        # 基于查询进行相关性排序
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').replace('，', ' ').split() if len(w.strip()) > 1]

        def relevance_score(fact: str) -> int:
            fact_lower = fact.lower()
            score = 0
            if query_lower in fact_lower:
                score += 100
            for kw in keywords:
                if kw in fact_lower:
                    score += 10
            return score

        # 排序并限制数量
        active_facts.sort(key=relevance_score, reverse=True)
        historical_facts.sort(key=relevance_score, reverse=True)

        result.active_facts = active_facts[:limit]
        result.historical_facts = historical_facts[:limit] if include_expired else []
        result.active_count = len(active_facts)
        result.historical_count = len(historical_facts)

        # EXECPLAN2 I-1-6: panorama 触达全图，记录覆盖的实体与边类型供覆盖度评估（纯观测）。
        self.record_coverage(
            graph_id,
            entity_uuids=[n.uuid for n in all_nodes if n.uuid],
            entity_names=[n.name for n in all_nodes if n.name],
            edge_types=[e.name for e in all_edges if e.name],
        )

        logger.info(f"PanoramaSearch完成: {result.active_count}条有效, {result.historical_count}条历史")
        return result

    def quick_search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10
    ) -> SearchResult:
        """
        【QuickSearch - 简单搜索】

        快速、轻量级的检索工具：
        1. 直接调用Zep语义搜索
        2. 返回最相关的结果
        3. 适用于简单、直接的检索需求

        Args:
            graph_id: 图谱ID
            query: 搜索查询
            limit: 返回结果数量

        Returns:
            SearchResult: 搜索结果
        """
        logger.info(f"QuickSearch 简单搜索: {query[:50]}...")

        # 直接调用现有的search_graph方法
        result = self.search_graph(
            graph_id=graph_id,
            query=query,
            limit=limit,
            scope="edges"
        )

        logger.info(f"QuickSearch完成: {result.total_count}条结果")
        return result

    def interview_agents(
        self,
        simulation_id: str,
        interview_requirement: str,
        simulation_requirement: str = "",
        max_agents: int = 5,
        custom_questions: List[str] = None,
        graph_id: Optional[str] = None,
        feedback_allowed: Optional[bool] = None,
    ) -> InterviewResult:
        """
        【InterviewAgents - 深度采访】

        调用真实的OASIS采访API，采访模拟中正在运行的Agent：
        1. 自动读取人设文件，了解所有模拟Agent
        2. 使用LLM分析采访需求，智能选择最相关的Agent
        3. 使用LLM生成采访问题
        4. 调用 /api/simulation/interview/batch 接口进行真实采访（双平台同时采访）
        5. 整合所有采访结果，生成采访报告

        【重要】此功能需要模拟环境处于运行状态（OASIS环境未关闭）

        【使用场景】
        - 需要从不同角色视角了解事件看法
        - 需要收集多方意见和观点
        - 需要获取模拟Agent的真实回答（非LLM模拟）

        Args:
            simulation_id: 模拟ID（用于定位人设文件和调用采访API）
            interview_requirement: 采访需求描述（非结构化，如"了解学生对事件的看法"）
            simulation_requirement: 模拟需求背景（可选）
            max_agents: 最多采访的Agent数量
            custom_questions: 自定义采访问题（可选，若不提供则自动生成）
            graph_id: 采访回答写入的图谱（可选；门允许时才写，见下）
            feedback_allowed: FU-8 编排器按该运行准入钉解析出的写图门（ReportAgent 转交；只有 True 放行）；
                None（API 重生成 / 对话）→ 按模拟 id 查所属管线的钉（无钉 → 环境值；查找失败 → 不写）

        Returns:
            InterviewResult: 采访结果
        """
        from .simulation_runner import SimulationRunner

        logger.info(f"InterviewAgents 深度采访（真实API）: {interview_requirement[:50]}...")

        result = InterviewResult(
            interview_topic=interview_requirement,
            interview_questions=custom_questions or []
        )

        # Step 1: 读取人设文件
        profiles = self._load_agent_profiles(simulation_id)

        if not profiles:
            logger.warning(f"未找到模拟 {simulation_id} 的人设文件")
            result.summary = "未找到可采访的Agent人设文件"
            return result

        result.total_agents = len(profiles)
        logger.info(f"加载到 {len(profiles)} 个Agent人设")

        # Step 2: 使用LLM选择要采访的Agent（返回agent_id列表）
        selected_agents, selected_indices, selection_reasoning = self._select_agents_for_interview(
            profiles=profiles,
            interview_requirement=interview_requirement,
            simulation_requirement=simulation_requirement,
            max_agents=max_agents
        )

        result.selected_agents = selected_agents
        result.selection_reasoning = selection_reasoning
        logger.info(f"选择了 {len(selected_agents)} 个Agent进行采访: {selected_indices}")

        # Step 3: 生成采访问题（如果没有提供）
        if not result.interview_questions:
            result.interview_questions = self._generate_interview_questions(
                interview_requirement=interview_requirement,
                simulation_requirement=simulation_requirement,
                selected_agents=selected_agents
            )
            logger.info(f"生成了 {len(result.interview_questions)} 个采访问题")

        # 将问题合并为一个采访prompt
        combined_prompt = "\n".join([f"{i+1}. {q}" for i, q in enumerate(result.interview_questions)])

        # 添加优化前缀，约束Agent回复格式
        INTERVIEW_PROMPT_PREFIX = (
            "你正在接受一次采访。请结合你的人设、所有的过往记忆与行动，"
            "以纯文本方式直接回答以下问题。\n"
            "回复要求：\n"
            "1. 直接用自然语言回答，不要调用任何工具\n"
            "2. 不要返回JSON格式或工具调用格式\n"
            "3. 不要使用Markdown标题（如#、##、###）\n"
            "4. 按问题编号逐一回答，每个回答以「问题X：」开头（X为问题编号）\n"
            "5. 每个问题的回答之间用空行分隔\n"
            "6. 回答要有实质内容，每个问题至少回答2-3句话\n\n"
        )
        optimized_prompt = f"{INTERVIEW_PROMPT_PREFIX}{combined_prompt}"

        # Step 4: 调用真实的采访API（不指定platform，默认双平台同时采访）
        try:
            # 构建批量采访列表（不指定platform，双平台采访）
            interviews_request = []
            for agent_idx in selected_indices:
                interviews_request.append({
                    "agent_id": agent_idx,
                    "prompt": optimized_prompt  # 使用优化后的prompt
                    # 不指定platform，API会在twitter和reddit两个平台都采访
                })

            logger.info(f"调用批量采访API（双平台）: {len(interviews_request)} 个Agent")

            # 调用 SimulationRunner 的批量采访方法（不传platform，双平台采访）
            api_result = SimulationRunner.interview_agents_batch(
                simulation_id=simulation_id,
                interviews=interviews_request,
                platform=None,  # 不指定platform，双平台采访
                # 双平台采访：每个Agent是一次 ~14-40s 的 claude-cli 调用，并发上限较低。
                # 6 个Agent约需 ~2.5min（曾贴近旧的 180s 上限），8 个则会超时。
                # 提高到 600s 以容纳更多受访者与 claude-cli 的高延迟，避免落入污染兜底。
                timeout=600.0
            )

            logger.info(f"采访API返回: {api_result.get('interviews_count', 0)} 个结果, success={api_result.get('success')}")

            # 检查API调用是否成功
            if not api_result.get("success", False):
                error_msg = api_result.get("error", "未知错误")
                logger.warning(f"采访API返回失败: {error_msg}")
                result.summary = f"采访API调用失败：{error_msg}。请检查OASIS模拟环境状态。"
                return result

            # Step 5: 解析API返回结果，构建AgentInterview对象
            # 双平台模式返回格式: {"twitter_0": {...}, "reddit_0": {...}, "twitter_1": {...}, ...}
            api_data = api_result.get("result", {})
            results_dict = api_data.get("results", {}) if isinstance(api_data, dict) else {}

            for i, agent_idx in enumerate(selected_indices):
                agent = selected_agents[i]
                agent_name = agent.get("realname", agent.get("username", f"Agent_{agent_idx}"))
                agent_role = agent.get("profession", "未知")
                agent_bio = agent.get("bio", "")

                # 获取该Agent在两个平台的采访结果
                twitter_result = results_dict.get(f"twitter_{agent_idx}", {})
                reddit_result = results_dict.get(f"reddit_{agent_idx}", {})

                twitter_response = twitter_result.get("response", "")
                reddit_response = reddit_result.get("response", "")

                # 清理可能的工具调用 JSON 包裹
                twitter_response = self._clean_tool_call_response(twitter_response)
                reddit_response = self._clean_tool_call_response(reddit_response)

                # 始终输出双平台标记
                twitter_text = twitter_response if twitter_response else "（该平台未获得回复）"
                reddit_text = reddit_response if reddit_response else "（该平台未获得回复）"
                response_text = f"【Twitter平台回答】\n{twitter_text}\n\n【Reddit平台回答】\n{reddit_text}"

                # 提取关键引言（从两个平台的回答中）
                import re
                combined_responses = f"{twitter_response} {reddit_response}"

                # 清理响应文本：去掉标记、编号、Markdown 等干扰
                clean_text = re.sub(r'#{1,6}\s+', '', combined_responses)
                clean_text = re.sub(r'\{[^}]*tool_name[^}]*\}', '', clean_text)
                clean_text = re.sub(r'[*_`|>~\-]{2,}', '', clean_text)
                clean_text = re.sub(r'问题\d+[：:]\s*', '', clean_text)
                clean_text = re.sub(r'【[^】]+】', '', clean_text)

                # 策略1（主）: 提取完整的有实质内容的句子
                sentences = re.split(r'[。！？]', clean_text)
                meaningful = [
                    s.strip() for s in sentences
                    if 20 <= len(s.strip()) <= 150
                    and not re.match(r'^[\s\W，,；;：:、]+', s.strip())
                    and not s.strip().startswith(('{', '问题'))
                ]
                meaningful.sort(key=len, reverse=True)
                key_quotes = [s + "。" for s in meaningful[:3]]

                # 策略2（补充）: 正确配对的中文引号「」内长文本
                if not key_quotes:
                    paired = re.findall(r'\u201c([^\u201c\u201d]{15,100})\u201d', clean_text)
                    paired += re.findall(r'\u300c([^\u300c\u300d]{15,100})\u300d', clean_text)
                    key_quotes = [q for q in paired if not re.match(r'^[，,；;：:、]', q)][:3]

                interview = AgentInterview(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    agent_bio=agent_bio[:1000],  # 扩大bio长度限制
                    question=combined_prompt,
                    response=response_text,
                    key_quotes=key_quotes[:5]
                )
                result.interviews.append(interview)

            result.interviewed_count = len(result.interviews)

            # T3.14: 把采访回答持久化为 typed 图谱事实（<agent> STATED_AT_END_OF_SIM …），
            # 让最丰富的收尾反思可被后续检索；key-free 走本地 shim。best-effort，失败不影响采访结果。
            # Foglamp WP1 (1A, I-11)：采访是模拟产物，默认不得写入观察图（门默认 false）；
            # 采访全文仍完整保留在 result.interviews（run 产物）。
            # FU-8：门由该运行钉住的安全政策决定——编排器传入的 feedback_allowed 优先；未传入时按模拟 id
            # 查所属管线的钉（无钉 → 环境值；查找失败 → 不写）。
            if (graph_id and result.interviews
                    and _interview_feedback_allowed(simulation_id, feedback_allowed)):
                try:
                    from .zep_graph_memory_updater import ZepGraphMemoryUpdater
                    _updater = ZepGraphMemoryUpdater(graph_id)
                    _written = 0
                    for itv in result.interviews:
                        if _updater.write_interview_fact(itv.agent_name, itv.response,
                                                         feedback_allowed=True):
                            _written += 1
                    logger.info(f"采访事实已写入图谱 {graph_id}: {_written}/{len(result.interviews)} 条")
                    # I-6-1: 采访写入了新事实，使该图谱的检索/洞察缓存失效，避免后续返回陈旧检索结果。
                    if _written:
                        self.invalidate_search_cache(graph_id)
                except Exception as _persist_err:
                    logger.warning(f"采访事实持久化跳过（不影响采访）: {_persist_err}")

        except ValueError as e:
            # 模拟环境未运行
            logger.warning(f"采访API调用失败（环境未运行？）: {e}")
            result.summary = f"采访失败：{str(e)}。模拟环境可能已关闭，请确保OASIS环境正在运行。"
            return result
        except Exception as e:
            logger.error(f"采访API调用异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            result.summary = f"采访过程发生错误：{str(e)}"
            return result

        # Step 6: 生成采访摘要
        if result.interviews:
            result.summary = self._generate_interview_summary(
                interviews=result.interviews,
                interview_requirement=interview_requirement
            )

        logger.info(f"InterviewAgents完成: 采访了 {result.interviewed_count} 个Agent（双平台）")
        return result

    @staticmethod
    def _clean_tool_call_response(response: str) -> str:
        """清理 Agent 回复中的 JSON 工具调用包裹，提取实际内容"""
        if not response or not response.strip().startswith('{'):
            return response
        text = response.strip()
        if 'tool_name' not in text[:80]:
            return response
        import re as _re
        try:
            data = json.loads(text)
            if isinstance(data, dict) and 'arguments' in data:
                for key in ('content', 'text', 'body', 'message', 'reply'):
                    if key in data['arguments']:
                        return str(data['arguments'][key])
        except (json.JSONDecodeError, KeyError, TypeError):
            match = _re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
            if match:
                return match.group(1).replace('\\n', '\n').replace('\\"', '"')
        return response

    def _load_agent_profiles(self, simulation_id: str) -> List[Dict[str, Any]]:
        """加载模拟的Agent人设文件"""
        import os
        import csv

        # 构建人设文件路径
        sim_dir = os.path.join(
            os.path.dirname(__file__),
            f'../../uploads/simulations/{simulation_id}'
        )

        profiles = []

        # 优先尝试读取Reddit JSON格式
        reddit_profile_path = os.path.join(sim_dir, "reddit_profiles.json")
        if os.path.exists(reddit_profile_path):
            try:
                with open(reddit_profile_path, 'r', encoding='utf-8') as f:
                    profiles = json.load(f)
                logger.info(f"从 reddit_profiles.json 加载了 {len(profiles)} 个人设")
                return profiles
            except Exception as e:
                logger.warning(f"读取 reddit_profiles.json 失败: {e}")

        # 尝试读取Twitter CSV格式
        twitter_profile_path = os.path.join(sim_dir, "twitter_profiles.csv")
        if os.path.exists(twitter_profile_path):
            try:
                with open(twitter_profile_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # CSV格式转换为统一格式
                        profiles.append({
                            "realname": row.get("name", ""),
                            "username": row.get("username", ""),
                            "bio": row.get("description", ""),
                            "persona": row.get("user_char", ""),
                            "profession": "未知"
                        })
                logger.info(f"从 twitter_profiles.csv 加载了 {len(profiles)} 个人设")
                return profiles
            except Exception as e:
                logger.warning(f"读取 twitter_profiles.csv 失败: {e}")

        return profiles

    def _select_agents_for_interview(
        self,
        profiles: List[Dict[str, Any]],
        interview_requirement: str,
        simulation_requirement: str,
        max_agents: int
    ) -> tuple:
        """
        使用LLM选择要采访的Agent

        Returns:
            tuple: (selected_agents, selected_indices, reasoning)
                - selected_agents: 选中Agent的完整信息列表
                - selected_indices: 选中Agent的索引列表（用于API调用）
                - reasoning: 选择理由
        """

        # 构建Agent摘要列表
        agent_summaries = []
        for i, profile in enumerate(profiles):
            summary = {
                "index": i,
                "name": profile.get("realname", profile.get("username", f"Agent_{i}")),
                "profession": profile.get("profession", "未知"),
                "bio": profile.get("bio", "")[:200],
                "interested_topics": profile.get("interested_topics", [])
            }
            agent_summaries.append(summary)

        system_prompt = """你是一个专业的采访策划专家。你的任务是根据采访需求，从模拟Agent列表中选择最适合采访的对象。

选择标准：
1. Agent的身份/职业与采访主题相关
2. Agent可能持有独特或有价值的观点
3. 选择多样化的视角（如：支持方、反对方、中立方、专业人士等）
4. 优先选择与事件直接相关的角色

返回JSON格式：
{
    "selected_indices": [选中Agent的索引列表],
    "reasoning": "选择理由说明"
}"""

        user_prompt = f"""采访需求：
{interview_requirement}

模拟背景：
{simulation_requirement if simulation_requirement else "未提供"}

可选择的Agent列表（共{len(agent_summaries)}个）：
{json.dumps(agent_summaries, ensure_ascii=False, indent=2)}

请选择最多{max_agents}个最适合采访的Agent，并说明选择理由。"""

        try:
            # EXECPLAN2 I-6-2: 受访者选择是低风险结构化任务，路由到 fast 档；tier 在关闭路由/
            # CLI 订阅提供方时为 no-op，行为不变。
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                tier="fast"
            )

            selected_indices = response.get("selected_indices", [])[:max_agents]
            reasoning = response.get("reasoning", "基于相关性自动选择")

            # 获取选中的Agent完整信息
            selected_agents = []
            valid_indices = []
            for idx in selected_indices:
                if 0 <= idx < len(profiles):
                    selected_agents.append(profiles[idx])
                    valid_indices.append(idx)

            return selected_agents, valid_indices, reasoning

        except Exception as e:
            logger.warning(f"LLM选择Agent失败，使用默认选择: {e}")
            # 降级：选择前N个
            selected = profiles[:max_agents]
            indices = list(range(min(max_agents, len(profiles))))
            return selected, indices, "使用默认选择策略"

    def _generate_interview_questions(
        self,
        interview_requirement: str,
        simulation_requirement: str,
        selected_agents: List[Dict[str, Any]]
    ) -> List[str]:
        """使用LLM生成采访问题"""

        agent_roles = [a.get("profession", "未知") for a in selected_agents]

        system_prompt = """你是一个专业的记者/采访者。根据采访需求，生成3-5个深度采访问题。

问题要求：
1. 开放性问题，鼓励详细回答
2. 针对不同角色可能有不同答案
3. 涵盖事实、观点、感受等多个维度
4. 语言自然，像真实采访一样
5. 每个问题控制在50字以内，简洁明了
6. 直接提问，不要包含背景说明或前缀

返回JSON格式：{"questions": ["问题1", "问题2", ...]}"""

        user_prompt = f"""采访需求：{interview_requirement}

模拟背景：{simulation_requirement if simulation_requirement else "未提供"}

采访对象角色：{', '.join(agent_roles)}

请生成3-5个采访问题。"""

        try:
            # EXECPLAN2 I-6-2: 采访问题生成是机械型结构化任务，路由到 fast 档；tier 在关闭
            # 路由/CLI 订阅提供方时为 no-op，行为不变。
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5,
                tier="fast"
            )

            return response.get("questions", [f"关于{interview_requirement}，您有什么看法？"])

        except Exception as e:
            logger.warning(f"生成采访问题失败: {e}")
            return [
                f"关于{interview_requirement}，您的观点是什么？",
                "这件事对您或您所代表的群体有什么影响？",
                "您认为应该如何解决或改进这个问题？"
            ]

    def _generate_interview_summary(
        self,
        interviews: List[AgentInterview],
        interview_requirement: str
    ) -> str:
        """生成采访摘要"""

        if not interviews:
            return "未完成任何采访"

        # 收集所有采访内容
        interview_texts = []
        for interview in interviews:
            interview_texts.append(f"【{interview.agent_name}（{interview.agent_role}）】\n{interview.response[:500]}")

        system_prompt = """你是一个专业的新闻编辑。请根据多位受访者的回答，生成一份采访摘要。

摘要要求：
1. 提炼各方主要观点
2. 指出观点的共识和分歧
3. 突出有价值的引言
4. 客观中立，不偏袒任何一方
5. 控制在1000字内

格式约束（必须遵守）：
- 使用纯文本段落，用空行分隔不同部分
- 不要使用Markdown标题（如#、##、###）
- 不要使用分割线（如---、***）
- 引用受访者原话时使用中文引号「」
- 可以使用**加粗**标记关键词，但不要使用其他Markdown语法"""

        user_prompt = f"""采访主题：{interview_requirement}

采访内容：
{"".join(interview_texts)}

请生成采访摘要。"""

        try:
            summary = self.llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=800
            )
            return summary

        except Exception as e:
            logger.warning(f"生成采访摘要失败: {e}")
            # 降级：简单拼接
            return f"共采访了{len(interviews)}位受访者，包括：" + "、".join([i.agent_name for i in interviews])

    # ==================================================================
    # 结构化模拟结果工具（EXECPLAN T4.2）—— 让报告的量化结论有据可查，
    # 不再只靠图谱模糊检索猜「谁最活跃 / 谁与谁抱团 / 立场怎么变」。
    # 三者都是确定性聚合（无 LLM），直接读 SimulationRunner 的结构化数据。
    # ==================================================================
    def simulation_outcomes(self, simulation_id: str, top_n: int = 15) -> str:
        """量化模拟结果：最活跃 agent Top-N、逐轮动作量、动作类型分布。"""
        from .simulation_runner import SimulationRunner
        try:
            stats = SimulationRunner.get_agent_stats(simulation_id) or []
            timeline = SimulationRunner.get_timeline(simulation_id) or []
        except Exception as e:
            return f"（无法读取模拟结构化数据：{e}）"
        if not stats and not timeline:
            return "（该模拟暂无可用的结构化结果数据）"

        # SIM-5（SIM_EVENT_PROVENANCE，默认开）：按 agent 自发动作排名、只列自发动作 >0 者，
        # 计数与类型都取 organic_* 字段——时间线事件回放挂在名字匹配/最高影响力回退的行为者
        # 名下，不得抬高其议程设置分层（report_agent._OUTCOME_ACTOR_LINE_RE 行格式不变）。
        # 开关关 → 旧输出逐字节不变。
        provenance_on = bool(getattr(Config, "SIM_EVENT_PROVENANCE", True))
        if provenance_on:
            def _count(s):
                return int(s.get("organic_actions", s.get("total_actions", 0)) or 0)

            def _types(s):
                return s.get("organic_action_types", s.get("action_types")) or {}

            ranked = [s for s in stats if _count(s) > 0]
            if stats and not ranked:
                # 全部动作都是注入：以「（」开头的无数据句，报告信号包据此整块自抑制，
                # 不把逐轮动作量等机制数字回退进章节提示（WAVE9/LOOP-015）。
                total = sum(int(s.get("total_actions", 0) or 0) for s in stats)
                return ("（本次模拟没有行为者自发动作"
                        + (f"：{total} 次动作均为注入——种子/时间线事件回放/采样点赞" if total else "")
                        + "）")
            header = f"### 最活跃 Agent（Top {top_n}，按自发动作数）"
        else:
            def _count(s):
                return s.get("total_actions", 0)

            def _types(s):
                return s.get("action_types") or {}

            ranked = stats
            header = f"### 最活跃 Agent（Top {top_n}，按总动作数）"
        stats_sorted = sorted(ranked, key=_count, reverse=True)
        lines = ["## 模拟量化结果（结构化，可直接引用）", "", header]
        for s in stats_sorted[:top_n]:
            at = _types(s)
            at_str = "、".join(f"{k}×{v}" for k, v in sorted(at.items(), key=lambda x: -x[1])[:5])
            lines.append(f"- {s.get('agent_name','?')}(id={s.get('agent_id')}): 共 {_count(s)} 次动作 [{at_str}]")
        if provenance_on:
            injected = sum(int(s.get("injected_actions", 0) or 0) for s in stats)
            if injected > 0:
                lines.append(f"（已剔除注入动作 {injected} 次：种子/时间线事件回放/采样点赞——非行为者自发）")

        breakdown: Dict[str, int] = {}
        for s in stats:
            for atype, c in _types(s).items():
                breakdown[atype] = breakdown.get(atype, 0) + int(c)
        if breakdown:
            lines.append("")
            lines.append("### 全局动作类型分布")
            lines.append("、".join(f"{k}: {v}" for k, v in sorted(breakdown.items(), key=lambda x: -x[1])))

        if timeline:
            lines.append("")
            lines.append("### 逐轮动作量 (round: total/active_agents)")
            vol = "  ".join(f"{r['round_num']}:{r['total_actions']}/{r['active_agents_count']}" for r in timeline)
            lines.append(vol)
            peak = max(timeline, key=lambda r: r["total_actions"])
            lines.append(f"峰值轮次: round {peak['round_num']}（{peak['total_actions']} 次动作）")
        return "\n".join(lines)

    def coalition_map(self, graph_id: str, simulation_id: str) -> str:
        """派系图：把对相同对象互动（点赞/转发/评论/关注）的 agent 聚成连通分量（确定性，无 LLM）。"""
        from .simulation_runner import SimulationRunner
        try:
            actions = SimulationRunner.get_actions(simulation_id, limit=100000) or []
        except Exception as e:
            return f"（无法读取模拟动作数据：{e}）"
        # agent → 其互动过的目标名集合
        # 修复：FOLLOW/MUTE 等动作的目标名由模拟侧写在 "target_user_name"（_enrich_action_context
        # 的规范键），此前只读 followee_name/target_name → 关注/拉黑关系被静默漏掉，派系聚类失真。
        # 把 target_user_name 纳入候选键。
        target_keys = ("post_author_name", "original_author_name", "comment_author_name",
                       "quoted_author_name", "target_user_name", "followee_name", "target_name")
        # SIM-5（SIM_EVENT_PROVENANCE，默认开）：对定时事件帖的回应是对新闻的反应，不是与发帖
        # 账号（名字匹配/最高影响力回退的行为者）的结盟证据——不把其作者名计为互动对象；
        # 事件回放行与采样点赞（随机采样，非 agent 选择）整行跳过。开关关 → 旧聚类不变。
        # 事件帖按 (正文, 发帖账号) 识别而非只比正文：OASIS 引用帖把被引根帖正文复制进
        # post.content，对「另一行为者引用事件」的互动带着事件正文、作者却是引用者——那是
        # 真实的行为者间互动，必须保留。
        provenance_on = bool(getattr(Config, "SIM_EVENT_PROVENANCE", True))
        event_posts: set = set()
        if provenance_on:
            event_posts = {
                (str((a.action_args or {}).get("content", "") or "").strip(),
                 str(a.agent_name or "").strip())
                for a in actions if (a.action_args or {}).get("is_scheduled_event")
            }
            event_posts = {key for key in event_posts if key[0]}
        # 作者键 → 该作者所写帖子的正文键（用于识别「该目标就是事件帖本身」）
        author_content_keys = {"post_author_name": "post_content",
                               "original_author_name": "original_content",
                               "quoted_author_name": "original_content"}
        agent_targets: Dict[int, set] = {}
        agent_name: Dict[int, str] = {}
        for a in actions:
            agent_name[a.agent_id] = a.agent_name
            args = a.action_args or {}
            if provenance_on and (args.get("is_scheduled_event") or args.get("is_engagement_sample")):
                continue
            for k in target_keys:
                v = str(args.get(k, "") or "").strip()
                if not v:
                    continue
                content_key = author_content_keys.get(k)
                if (event_posts and content_key
                        and (str(args.get(content_key, "") or "").strip(), v) in event_posts):
                    continue
                agent_targets.setdefault(a.agent_id, set()).add(v)
        if not agent_targets:
            return "（本次模拟没有可用于聚类的定向互动，无法形成派系图）"

        # 并查集：共享任一目标的 agent 归为同一派系
        parent: Dict[int, int] = {aid: aid for aid in agent_targets}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            parent[find(x)] = find(y)

        target_to_agent: Dict[str, int] = {}
        for aid, tgts in agent_targets.items():
            for t in tgts:
                if t in target_to_agent:
                    union(aid, target_to_agent[t])
                else:
                    target_to_agent[t] = aid
        clusters: Dict[int, List[int]] = {}
        for aid in agent_targets:
            clusters.setdefault(find(aid), []).append(aid)
        clusters_sorted = sorted(clusters.values(), key=len, reverse=True)

        lines = ["## 派系/联盟图（按共享互动对象聚类，确定性）"]
        idx = 0
        for members in clusters_sorted:
            if len(members) < 2:
                continue
            idx += 1
            names = "、".join(agent_name.get(m, f"agent{m}") for m in members[:15])
            lines.append(f"- 派系 {idx}（{len(members)} 人）: {names}")
        if idx == 0:
            lines.append("- （未发现 ≥2 人的互动派系）")
        return "\n".join(lines)

    def faction_brief(self, graph_id: str, query: str = "", simulation_id: str = "") -> str:
        """派系简报（EXECPLAN2 I-1-2）：基于图谱已检测的社区(Community)节点 + LLM 摘要，
        列出各派系的成员实体与定位，给报告「图谱原生」的阵营证据（互补于 coalition_map 的
        行为日志聚类）。无社区节点（或未启用 GRAPH_COMMUNITY_RETRIEVAL）时降级到 coalition_map。"""
        if not getattr(Config, "GRAPH_COMMUNITY_RETRIEVAL", False):
            return (self.coalition_map(graph_id, simulation_id) if simulation_id
                    else "（GRAPH_COMMUNITY_RETRIEVAL 未启用；无 simulation_id 可回退到行为聚类）")
        try:
            from .graphiti_client.runtime import get_runtime
            communities = get_runtime().list_communities(graph_id) or []
        except Exception as e:
            logger.warning(f"faction_brief: 读取社区失败，降级到 coalition_map: {e}")
            communities = []
        if not communities:
            # 图谱无社区节点 → 降级到行为日志派系聚类
            return (self.coalition_map(graph_id, simulation_id) if simulation_id
                    else "（图谱无社区节点，且无 simulation_id 可回退到行为聚类）")
        q = (query or "").strip().lower()

        def _relevance(c):
            if not q:
                return 0
            hay = (str(c.get("name", "")) + " " + str(c.get("summary", "")) + " "
                   + " ".join(str(m) for m in (c.get("members") or []))).lower()
            return hay.count(q)

        # 有查询时优先相关社区，其次按成员数；无查询时纯按成员数（派系规模）排序。
        communities.sort(key=lambda c: (_relevance(c), len(c.get("members") or [])), reverse=True)
        lines = ["## 派系/社区简报（基于图谱社区检测 + LLM 摘要）"]
        for i, c in enumerate(communities[:8], 1):
            members = c.get("members") or []
            lines.append(f"### 派系 {i}: {c.get('name') or f'社区{i}'}（{len(members)} 个实体）")
            if c.get("summary"):
                lines.append(c["summary"].strip())
            if members:
                shown = "、".join(str(m) for m in members[:20])
                lines.append(f"成员: {shown}" + ("…" if len(members) > 20 else ""))
        # R2-KG-11: 追加确定性的社区间张力矩阵（跨界边按极性加权）。失败 → 不追加（degrade-safe）。
        tension_lines = self._inter_community_tension(graph_id, communities)
        if tension_lines:
            lines.extend(tension_lines)
        return "\n".join(lines)

    def _inter_community_tension(self, graph_id: str,
                                 communities: List[Dict[str, Any]]) -> List[str]:
        """R2-KG-11: 确定性的「社区间张力矩阵」——把跨社区边按关系极性
        （actors.relation_polarity，allied→正 / adversarial→负）加权汇总，给报告
        「派系 A 与派系 B 整体对抗还是结盟」的图谱级证据（互补于派系内部的成员清单）。
        纯聚合无 LLM；读图失败或无跨界边 → 返回 []（faction_brief 照常输出，degrade-safe）。"""
        try:
            from ..utils.actors import normalize_name, relation_polarity
            # 只取有成员的前若干社区，避免社区极多时 O(K^2) 渲染爆炸。
            comms = [c for c in (communities or []) if (c.get("members") or [])][:12]
            if len(comms) < 2:
                return []
            # 标准化成员名 → 社区下标（重名归最先出现的社区，保持确定性）。
            member_to_comm: Dict[str, int] = {}
            for idx, c in enumerate(comms):
                for m in (c.get("members") or []):
                    nm = normalize_name(str(m))
                    if nm and nm not in member_to_comm:
                        member_to_comm[nm] = idx
            if not member_to_comm:
                return []
            nodes = self.get_all_nodes(graph_id)
            uuid_to_norm = {n.uuid: normalize_name(n.name)
                            for n in nodes if n.uuid and n.name}
            edges = self.get_all_edges(graph_id)
            # (min社区,max社区) → [净极性累计, 跨界边数, 负向边数]
            pair_stats: Dict[tuple, List[float]] = {}
            for e in edges:
                sn = uuid_to_norm.get(e.source_node_uuid)
                tn = uuid_to_norm.get(e.target_node_uuid)
                if not sn or not tn:
                    continue
                ci = member_to_comm.get(sn)
                cj = member_to_comm.get(tn)
                if ci is None or cj is None or ci == cj:
                    continue
                pol = relation_polarity({"type": e.name})
                key = (min(ci, cj), max(ci, cj))
                st = pair_stats.setdefault(key, [0.0, 0, 0])
                st[0] += pol
                st[1] += 1
                if pol < 0:
                    st[2] += 1
            if not pair_stats:
                return []

            def _cname(i: int) -> str:
                return comms[i].get("name") or f"社区{i + 1}"

            # 净极性越负越靠前（最对抗的派系对置顶），再以边数稳定排序。
            ordered = sorted(pair_stats.items(), key=lambda kv: (kv[1][0], -kv[1][1]))
            lines = ["", "### 社区间张力矩阵（跨界边按关系极性加权，确定性）"]
            for (i, j), (net, cnt, neg) in ordered[:12]:
                if net < -0.05:
                    tag = "对抗"
                elif net > 0.05:
                    tag = "结盟"
                else:
                    tag = "中性/混合"
                lines.append(
                    f"- {_cname(i)} ↔ {_cname(j)}: {cnt} 条跨界边，净极性 {net:+.2f}"
                    f"（{neg} 条负向）→ {tag}"
                )
            return lines
        except Exception as exc:  # noqa: BLE001  张力矩阵是增强项，失败不影响 faction_brief
            logger.debug(f"inter-community tension 跳过（不影响 faction_brief）: {exc}")
            return []

    # NEXTSTEPS P3-6: 多跳传导/级联追踪（图谱原生结构推理，互补于 1-hop 检索）。
    _CAUSAL_EDGE_NAMES = ["CAUSES", "ENABLES", "CONSTRAINS", "TRIGGERS", "ACCELERATES"]

    def _resolve_entity_name(self, graph_id: str, name: str) -> str:
        """R2-KG-2: 把工具/LLM 传入的实体名解析为图谱里实际存在的规范节点名，供
        trace_cascade 的精确 `a.name = $src` Cypher 匹配使用（否则大小写/空格/公司后缀
        的细微差异会让多跳查询无谓地返回空）。解析顺序对齐 actors.match_actor 语义：
        标准化精确匹配 → 双向包含（取较长名，避免「AI」类短名误配）。无命中或读取失败 →
        原样返回（degrade-safe，绝不因解析失败而阻断遍历）。
        INFRA-11（ACTOR_NAME_MATCH_STRICT，默认开）：见 _resolve_entity_name_strict——先查名册
        别名，包含匹配下限 4 字符且要求唯一命中；关闭 = 上面的旧解析（2 字符包含、取较长名）。"""
        raw = (name or "").strip()
        if not raw:
            return raw
        try:
            from ..utils.actors import normalize_name
            nodes = self.get_all_nodes(graph_id)
        except Exception as exc:  # noqa: BLE001  解析是增强项，失败按原名走
            logger.debug(f"_resolve_entity_name 读取节点失败，按原名匹配: {exc}")
            return raw
        target = normalize_name(raw)
        if not target:
            return raw
        if getattr(Config, "ACTOR_NAME_MATCH_STRICT", True):
            resolved = self._resolve_entity_name_strict(raw, target, nodes)
        else:
            exact: Optional[str] = None
            best: Optional[str] = None
            best_len = 0
            for node in nodes:
                cand = normalize_name(node.name)
                if not cand:
                    continue
                if cand == target:
                    exact = node.name
                    break
                if len(cand) >= 2 and (cand in target or target in cand) and len(cand) > best_len:
                    best, best_len = node.name, len(cand)
            resolved = exact or best
        if resolved and resolved != raw:
            logger.info(f"trace_cascade 名称解析: {raw!r} → 规范节点 {resolved!r}")
            return resolved
        return raw

    def _resolve_entity_name_strict(self, raw: str, target: str, nodes: List[Any]) -> Optional[str]:
        """INFRA-11: fail-closed node-name resolution for trace_cascade.

        1. Exact normalized node name: the name itself, then (when it is exactly the name or
           an alias of one roster actor) that actor's canonical name and the aliases that
           denote only it, so an exact alias such as 'EU' reaches the 'European Union' node
           while a contested alias ('China' listed by the Chinese Communist Party beside a
           China actor) never steers the pick to another actor's node.
        2. Containment only when both sides have at least 4 normalized characters (a CJK name
           counts per character) and exactly one distinct node name qualifies.
        Anything else returns None and the caller keeps the raw name.
        """
        from ..utils.actors import normalize_name
        roster = getattr(self, "actor_roster", None)
        surfaces = [target]
        row = _roster_actor_for(raw, roster)
        if row is not None:
            canonical = normalize_name(row.get("name"))
            aliases = row.get("aliases") if isinstance(row.get("aliases"), list) else []
            for surface in (row.get("name"), *aliases):
                norm = normalize_name(surface) if isinstance(surface, str) else ""
                if not norm or norm in surfaces:
                    continue
                owner = _roster_actor_for(surface, roster)
                if owner is not None and normalize_name(owner.get("name")) == canonical:
                    surfaces.append(norm)
        by_norm: Dict[str, str] = {}
        for node in nodes:
            cand = normalize_name(node.name)
            if cand:
                by_norm.setdefault(cand, node.name)
        for surface in surfaces:
            if surface in by_norm:
                return by_norm[surface]
        contained = [
            cand for cand in by_norm
            if min(len(cand), len(target)) >= 4 and (cand in target or target in cand)
        ]
        if len(contained) == 1:
            return by_norm[contained[0]]
        if contained:
            logger.info(
                f"trace_cascade 名称解析: {raw!r} 包含匹配到 {len(contained)} 个节点，歧义不解析"
                f"（{', '.join(by_norm[c] for c in contained[:6])}）"
            )
        return None

    @staticmethod
    def _fmt_edge_label(edge: Any) -> str:
        """渲染一跳的边标签。runtime 当前返回边 name 字符串；若图谱侧升级为带
        {name/sign/strength/lag/polarity} 的富投影（见因果遍历投影契约），这里把它渲染成
        `REL, sign=-, strength=high, lag=...` 而不是把整个 dict 直接 str 出来。两种形态都
        安全处理（forward-compat，degrade-safe）。"""
        if isinstance(edge, dict):
            parts = [str(edge.get("name") or edge.get("edge") or edge.get("rel") or "REL")]
            for key in ("sign", "strength", "lag", "polarity", "family"):
                val = edge.get(key)
                if val not in (None, ""):
                    parts.append(f"{key}={val}")
            return ", ".join(parts)
        return str(edge)

    def trace_cascade(self, graph_id: str, source: str = "", target: str = "",
                      center: str = "", causal_only: bool = True) -> str:
        """沿图谱多跳追踪传导/级联。给 source+target → 列出二者间的有向路径（优先因果族边）；
        只给 center → 列出其多跳因果邻域。用于"追踪级联、哪个节点一动就翻盘"的结构推理。
        无路径/遍历失败 → 友好降级串（不抛出）。"""
        try:
            from .graphiti_client.runtime import get_runtime
            rt = get_runtime()
        except Exception:  # noqa: BLE001
            return "（图谱遍历不可用）"
        edge_types = self._CAUSAL_EDGE_NAMES if causal_only else None
        try:
            if source and target:
                # R2-KG-2: 先把 source/target 解析为规范节点名再下推 Cypher（并记录解析）。
                rsource = self._resolve_entity_name(graph_id, source)
                rtarget = self._resolve_entity_name(graph_id, target)
                paths = rt.causal_paths(graph_id, rsource, rtarget, edge_types=edge_types) or []
                note = ""
                if not paths and causal_only:
                    paths = rt.causal_paths(graph_id, rsource, rtarget, edge_types=None) or []
                    note = "（无纯因果路径，下列为一般关系路径）"
                if not paths:
                    return f"（{rsource} → {rtarget} 间未找到 ≤6 跳路径）"
                lines = [f"【传导路径：{rsource} → {rtarget}】{note}"]
                for p in paths[:12]:
                    nodes, edges = p.get("nodes", []), p.get("edges", [])
                    chain = ""
                    for i, n in enumerate(nodes):
                        chain += str(n)
                        if i < len(edges):
                            chain += f" --[{self._fmt_edge_label(edges[i])}]--> "
                    lines.append(f"· ({p.get('hops')}跳) {chain}")
                return "\n".join(lines)
            if center:
                rcenter = self._resolve_entity_name(graph_id, center)
                edges = rt.n_hop_subgraph(graph_id, rcenter, edge_types=edge_types) or []
                if not edges and causal_only:
                    edges = rt.n_hop_subgraph(graph_id, rcenter, edge_types=None) or []
                if not edges:
                    return f"（{rcenter} 的多跳邻域为空）"
                lines = [f"【{rcenter} 的多跳传导邻域（{len(edges)} 条边）】"]
                for e in edges[:40]:
                    lines.append(
                        f"· {e.get('source')} --[{self._fmt_edge_label(e.get('edge'))}]--> {e.get('target')}"
                    )
                return "\n".join(lines)
            return "（trace_cascade 需要 source+target 或 center）"
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"trace_cascade 失败（降级）: {exc}")
            return "（图谱遍历失败）"

    def opinion_shift(self, simulation_id: str, actor_name: str) -> str:
        """单个 actor 的逐轮行为轨迹（动作量/类型随轮次变化），用于观察立场/参与度演变。"""
        from .simulation_runner import SimulationRunner
        try:
            actions = SimulationRunner.get_actions(simulation_id, limit=100000) or []
        except Exception as e:
            return f"（无法读取模拟动作数据：{e}）"
        from ..utils.actors import normalize_name
        target = normalize_name(actor_name)
        # RPT-13：空 target 时 str.find('') 恒为 0，会把全体动作日志误标成单一 actor 的轨迹。
        if not target:
            return "（opinion_shift 需要 actor_name 参数：请提供要追踪的 Agent/角色名）"
        shown = f"「{actor_name}」"
        if getattr(Config, "ACTOR_NAME_MATCH_STRICT", True):
            agents, note, ambiguity = self._opinion_shift_agents(actor_name, actions)
            if ambiguity:
                return ambiguity
            # INFRA-11：解析到的行为者与并入的 agent 都在输出里点名，绝不把替换/合并后的轨迹挂在原始名下。
            shown += note
            mine = [a for a in actions if a.agent_name and str(a.agent_name) in agents]
        else:
            mine = [a for a in actions if normalize_name(a.agent_name) == target or normalize_name(a.agent_name).find(target) >= 0]
        if not mine:
            return f"（未找到名为{shown}的 agent 的动作记录）"
        # SIM-5（SIM_EVENT_PROVENANCE，默认开）：挂在该行为者名下的种子/时间线事件回放/采样
        # 点赞不是它的行为轨迹——剔除并注明条数。开关关 → 旧输出逐字节不变。
        injected = 0
        if getattr(Config, "SIM_EVENT_PROVENANCE", True):
            from .sim_event_provenance import is_injected_row
            organic = [a for a in mine
                       if not is_injected_row(getattr(a, "action_args", None), a.round_num)]
            injected = len(mine) - len(organic)
            if not organic:
                return (f"（{shown}名下没有自发动作：{injected} 次均为注入动作——"
                        "种子/时间线事件回放/采样点赞）")
            mine = organic
        by_round: Dict[int, Dict[str, int]] = {}
        for a in mine:
            r = by_round.setdefault(a.round_num, {})
            r[a.action_type] = r.get(a.action_type, 0) + 1
        lines = [f"## {shown}逐轮行为轨迹（参与度/立场演变线索）"]
        for rn in sorted(by_round):
            at = by_round[rn]
            lines.append(f"- round {rn}: " + "、".join(f"{k}×{v}" for k, v in sorted(at.items(), key=lambda x: -x[1])))
        lines.append(f"合计 {len(mine)} 次动作，跨 {len(by_round)} 轮。")
        if injected:
            lines.append(f"（已剔除注入动作 {injected} 次：种子/时间线事件回放/采样点赞——非行为者自发）")
        return "\n".join(lines)

    def _opinion_shift_agents(self, actor_name: str, actions: List[Any]) -> tuple[set, str, str]:
        """INFRA-11: (agent names opinion_shift tracks, header note, ambiguity message).

        The legacy filter kept every agent whose normalized name merely contained the
        target, so 'US' also swept in Russia, Australia and Business Roundtable.  Here an
        exact name decides first: the research roster's canonical name or an alias (the
        canonical wins over another actor's alias), then an agent name from the action log.
        An alias two roster actors share belongs to neither of them, so an agent carrying
        exactly that name is tracked on its own (the note says whose alias the name also is)
        instead of leaving its trajectory unreachable; without such an agent the shared alias
        stays ambiguous.  Otherwise containment of at least 4 characters is weighed across
        both pools at once: every roster actor sharing such a containment with the target,
        plus every agent name that does and that none of those roster actors already tracks
        ('Japan' against the roster actor Bank of Japan and the unrostered agent Government
        of Japan is two candidates).  A roster actor tracks the agents whose name denotes it
        exactly or that ``match_actor`` resolves to it.  One candidate resolves, and the note
        names the actor the target resolved to and every tracked agent under another name;
        several return an explanatory message naming them instead of merging their
        trajectories; none returns empty values.
        """
        from ..utils.actors import actor_match_candidates, match_actor, normalize_name
        target = normalize_name(actor_name)
        agent_names = sorted({str(a.agent_name) for a in actions if a.agent_name})
        roster = getattr(self, "actor_roster", None)
        agent_pool = {"actors": [{"name": name} for name in agent_names]}
        owners: Optional[Dict[str, str]] = None  # agent name -> normalized roster canonical

        def _roster_agents(row: Dict[str, Any]) -> set:
            nonlocal owners
            if owners is None:
                owners = {}
                for name in agent_names:
                    exact = actor_match_candidates(name, roster, exact_only=True)
                    if exact:  # an alias two actors share names neither of them
                        owner = exact[0] if len(exact) == 1 else None
                    else:
                        owner = match_actor(name, roster)
                    owners[name] = normalize_name(owner.get("name")) if owner else ""
            canonical = normalize_name(row.get("name"))
            return {name for name in agent_names if owners[name] == canonical}

        def _named_agents(row: Dict[str, Any]) -> set:
            norm = normalize_name(row.get("name"))
            return {name for name in agent_names if normalize_name(name) == norm}

        def _listing(labels: List[str]) -> str:
            more = f" 等 {len(labels)} 个" if len(labels) > 12 else ""
            return "、".join(labels[:12]) + more

        note = ""
        candidates = [(str(row.get("name")), _roster_agents(row))
                      for row in actor_match_candidates(actor_name, roster, exact_only=True)]
        same_name = [(str(row.get("name")), _named_agents(row))
                     for row in actor_match_candidates(actor_name, agent_pool, exact_only=True)]
        if len(candidates) > 1 and same_name:
            # The agent named exactly after the shared alias is owned by none of the actors
            # sharing it (see owners), so its own trajectory is the one to show.
            note = (f"（同名 agent；「{actor_name}」也是 {_listing([label for label, _ in candidates])}"
                    " 共用的别名，未并入它们的轨迹）")
            candidates = same_name
        if not candidates:
            candidates = same_name
        if not candidates:
            candidates = [(str(row.get("name")), _roster_agents(row))
                          for row in actor_match_candidates(actor_name, roster)]
            tracked = set().union(*(agents for _, agents in candidates))
            for row in actor_match_candidates(actor_name, agent_pool):
                untracked = _named_agents(row) - tracked
                if untracked:
                    candidates.append((str(row.get("name")), untracked))
        if len(candidates) == 1:
            label, agents = candidates[0]
            resolved = normalize_name(label)
            if resolved != target:
                note += f"（解析为「{label}」）"
            if any(normalize_name(name) not in (resolved, target) for name in agents):
                note += f"（合并 agent：{_listing(sorted(agents))}）"
            return agents, note, ""
        if not candidates:
            return set(), "", ""
        return set(), "", (
            f"（「{actor_name}」可对应多个行为者：{_listing([label for label, _ in candidates])}"
            "——为避免把不同行为者的轨迹混在一起，请用其中一个的完整名称重新调用 opinion_shift）"
        )

    def scenario_diff(self, base_sim_id: str, scenario_sim_id: str) -> str:
        """T4.7: 反事实对比 base vs 情景两次模拟的结构化差异（确定性，无 LLM）。

        计算：总动作量差、峰值轮次差、逐轮动作量 delta、Top-actor 活跃度 delta。所有数字都可
        回溯到各自的 get_timeline / get_agent_stats。任一模拟缺失 → 友好降级提示。
        """
        from .simulation_runner import SimulationRunner
        try:
            base_tl = SimulationRunner.get_timeline(base_sim_id) or []
            scen_tl = SimulationRunner.get_timeline(scenario_sim_id) or []
            base_stats = SimulationRunner.get_agent_stats(base_sim_id) or []
            scen_stats = SimulationRunner.get_agent_stats(scenario_sim_id) or []
        except Exception as e:
            return f"（无法读取对比所需的结构化数据：{e}）"
        if not (base_tl or scen_tl):
            return "（基线或情景模拟暂无可用结构化数据，无法对比）"

        def _total(tl):
            return sum(r.get("total_actions", 0) for r in tl)

        def _peak(tl):
            return max(tl, key=lambda r: r.get("total_actions", 0), default=None)

        bt, st = _total(base_tl), _total(scen_tl)
        lines = ["## 情景对比 / 反事实差异（基线 vs 情景，结构化）", ""]
        lines.append(f"- 总动作量: 基线 {bt} → 情景 {st}（Δ {st - bt:+d}, {((st-bt)/bt*100) if bt else 0:+.1f}%）")
        bp, sp = _peak(base_tl), _peak(scen_tl)
        if bp and sp:
            lines.append(
                f"- 峰值轮次: 基线 round {bp['round_num']}（{bp['total_actions']}）"
                f" → 情景 round {sp['round_num']}（{sp['total_actions']}）"
            )
        lines.append(f"- 执行轮数: 基线 {len(base_tl)} → 情景 {len(scen_tl)}")

        # 逐轮 delta（取两者并集的前若干轮）
        bvol = {r["round_num"]: r.get("total_actions", 0) for r in base_tl}
        svol = {r["round_num"]: r.get("total_actions", 0) for r in scen_tl}
        rounds = sorted(set(bvol) | set(svol))
        if rounds:
            lines.append("")
            lines.append("### 逐轮动作量 delta (round: base→scenario)")
            lines.append("  ".join(
                f"{rn}:{bvol.get(rn,0)}→{svol.get(rn,0)}" for rn in rounds[:48]
            ))

        # Top-actor 活跃度 delta。SIM-5（SIM_EVENT_PROVENANCE，默认开）：只比自发动作——情景注入
        # 事件挂在发帖行为者名下，按总动作数会把注入本身读成该行为者的活跃度变化。
        if getattr(Config, "SIM_EVENT_PROVENANCE", True):
            count_key, delta_header = "organic_actions", "### Top-actor 活跃度 delta（按变化幅度，仅自发动作）"
        else:
            count_key, delta_header = "total_actions", "### Top-actor 活跃度 delta（按变化幅度）"
        b_by = {s.get("agent_name"): s.get(count_key, s.get("total_actions", 0)) for s in base_stats}
        s_by = {s.get("agent_name"): s.get(count_key, s.get("total_actions", 0)) for s in scen_stats}
        names = set(b_by) | set(s_by)
        deltas = sorted(
            ((n, s_by.get(n, 0) - b_by.get(n, 0)) for n in names if n),
            key=lambda x: abs(x[1]), reverse=True,
        )[:10]
        if deltas:
            lines.append("")
            lines.append(delta_header)
            for n, d in deltas:
                lines.append(f"- {n}: {b_by.get(n,0)} → {s_by.get(n,0)}（Δ {d:+d}）")
        return "\n".join(lines)
