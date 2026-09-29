"""
模拟配置智能生成器
使用LLM根据模拟需求、文档内容、图谱信息自动生成细致的模拟参数
实现全程自动化，无需人工设置参数

采用分步生成策略，避免一次性生成过长内容导致失败：
1. 生成时间配置
2. 生成事件配置
3. 分批生成Agent配置
4. 生成平台配置
"""

import json
import math
import os
import random
import re
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime

from ..config import Config
from ..utils import sim_timeline
from ..utils.actors import (
    actors_digest,
    build_initial_follow_graph,
    events_to_calendar_rounds,
    events_to_schedule,
    extract_actor_rows,
    extract_relationship_rows,
    forecast_inputs_block,
    influence_weight,
    match_actor,
    normalize_name,
    relation_polarity,
    relation_valence,
    situation_brief_block,
)
from ..utils.dates import parse_as_of
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from .zep_entity_reader import EntityNode, ZepEntityReader
from .actor_context import (
    ACTOR_CONTEXT_VERSION,
    ACTOR_INTELLIGENCE_VERSION,
    INTELLIGENCE_DIMENSIONS,
    actor_id_for,
    canonical_json_sha256,
    is_hard_public_relationship,
    normalize_evidence_gap_map,
)
from .actor_role_prompt import (
    delimit_untrusted_research_text,
    sanitize_untrusted_dossier_text,
    sanitize_untrusted_research_text,
)

logger = get_logger('mirofish.simulation_config')

ACTOR_CONFIG_EVIDENCE_GAP_AUDIT_VERSION = (
    "actor-config-evidence-gap-audit/v1"
)
ACTOR_CONFIG_EVIDENCE_GAP_AUDIT_KEY = (
    "evidence_gap_audit_not_actor_or_llm_knowledge"
)
ACTOR_CONFIG_EVIDENCE_GAP_AUDIT_MAX_BYTES = 65_536

# C5: 旧 8 类关系（valence 价感知前就存在的类型）。仅当 relationships[] 出现「新信号」
# ——任一关系带显式 valence/polarity 字段，或带一个超出这 8 类的新关系类型——才认为
# 研究档案携带了价感知数据，从而启用价感知的同温层关注与情感种子。否则（今日数据：
# 只有这 8 类、且无 valence/polarity 字段）价感知逻辑整体跳过，跟随图与情感逐字节不变。
_LEGACY_REL_TYPES = frozenset({
    "ALLY_OF", "OPPOSES", "COMPETES_WITH", "REGULATES",
    "DEPENDS_ON", "PARTNERS_WITH", "INFLUENCES", "OTHER",
})

# 中国作息时间配置（北京时间）
CHINA_TIMEZONE_CONFIG = {
    # 深夜时段（几乎无人活动）
    "dead_hours": [0, 1, 2, 3, 4, 5],
    # 早间时段（逐渐醒来）
    "morning_hours": [6, 7, 8],
    # 工作时段
    "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    # 晚间高峰（最活跃）
    "peak_hours": [19, 20, 21, 22],
    # 夜间时段（活跃度下降）
    "night_hours": [23],
    # 活跃度系数
    "activity_multipliers": {
        "dead": 0.05,      # 凌晨几乎无人
        "morning": 0.4,    # 早间逐渐活跃
        "work": 0.7,       # 工作时段中等
        "peak": 1.5,       # 晚间高峰
        "night": 0.5       # 深夜下降
    }
}


# ====================================================================
# 活动作息画像（activity profile）抽象
# ----------------------------------------------------------------
# 历史上时间/Agent 配置的作息节奏（北京时间）、提示词措辞、默认回退值都硬编码为
# 中国社交媒体语境。这里把这一整套口径抽象成可切换的「画像」，由
# getattr(Config, 'SIM_ACTIVITY_PROFILE', 'china_social') 选择：
#   - 'china_social'：完全等价于历史行为，常量/提示词/默认值逐字节不变（默认）
#   - 'us_business' ：美国商务作息口径（英文倾向的引导语）
#   - 'global_market'：跨时区市场口径（24 小时更平坦，无明显深夜真空）
# 缺省（未配置 SIM_ACTIVITY_PROFILE）= 'china_social'，产出与今日完全一致。
# 注意：china_social 各字段的字符串/数值即今日代码内联使用的原文，切勿改动，
# 否则默认输出会发生字节级漂移。
# ====================================================================
ACTIVITY_PROFILES = {
    "china_social": {
        # _generate_time_config 提示词内「基本原则」段（与原内联逐字一致）
        "time_prompt_principles": (
            "- 用户群体为中国人，需符合北京时间作息习惯\n"
            "- 凌晨0-5点几乎无人活动（活跃度系数0.05）\n"
            "- 早上6-8点逐渐活跃（活跃度系数0.4）\n"
            "- 工作时间9-18点中等活跃（活跃度系数0.7）\n"
            "- 晚间19-22点是高峰期（活跃度系数1.5）\n"
            "- 23点后活跃度下降（活跃度系数0.5）\n"
            "- 一般规律：凌晨低活跃、早间渐增、工作时段中等、晚间高峰"
        ),
        # _generate_time_config 的 system_prompt（与原内联逐字一致）
        "time_system_prompt": "你是社交媒体模拟专家。返回纯JSON格式，时间配置需符合中国人作息习惯。",
        # _get_default_time_config 的 reasoning 文案（与原内联逐字一致）
        "default_time_reasoning": "使用默认中国人作息配置（每轮1小时）",
        # _generate_agent_config 提示词首条作息要点（与原内联逐字一致）
        "agent_prompt_rhythm": "- **时间符合中国人作息**：凌晨0-5点几乎不活动，晚间19-22点最活跃",
        # active_hours 占位说明（与原内联逐字一致）
        "agent_active_hours_hint": "活跃小时列表，考虑中国人作息",
        # _generate_agent_config 的 system_prompt（与原内联逐字一致）
        "agent_system_prompt": "你是社交媒体行为分析专家。返回纯JSON，配置需符合中国人作息习惯。",
        # 时间配置数值口径（与原内联默认逐字一致）
        "peak_hours": [19, 20, 21, 22],
        "off_peak_hours": [0, 1, 2, 3, 4, 5],
        "morning_hours": [6, 7, 8],
        "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    },
    "us_business": {
        "time_prompt_principles": (
            "- 用户群体为美国受众，需符合美东/美西商务作息习惯\n"
            "- 凌晨0-5点几乎无人活动（活跃度系数0.05）\n"
            "- 早上6-8点逐渐活跃（活跃度系数0.4）\n"
            "- 工作时间9-17点最活跃（活跃度系数1.5）\n"
            "- 午休及午后12-14点保持中等活跃（活跃度系数0.7）\n"
            "- 18点后逐渐回落，晚间19-22点中等活跃（活跃度系数0.7）\n"
            "- 一般规律：凌晨低活跃、早间渐增、工作时段高峰、晚间中等"
        ),
        "time_system_prompt": "你是社交媒体模拟专家。返回纯JSON格式，时间配置需符合美国商务作息习惯。",
        "default_time_reasoning": "使用默认美国商务作息配置（每轮1小时）",
        "agent_prompt_rhythm": "- **时间符合美国商务作息**：凌晨0-5点几乎不活动，工作时间9-17点最活跃",
        "agent_active_hours_hint": "活跃小时列表，考虑美国商务作息",
        "agent_system_prompt": "你是社交媒体行为分析专家。返回纯JSON，配置需符合美国商务作息习惯。",
        "peak_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17],
        "off_peak_hours": [0, 1, 2, 3, 4, 5],
        "morning_hours": [6, 7, 8],
        "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17],
    },
    "global_market": {
        "time_prompt_principles": (
            "- 用户群体为跨时区全球市场受众，作息相对平坦、无明显深夜真空\n"
            "- 凌晨0-5点活跃度偏低但非归零（活跃度系数0.3）\n"
            "- 各主要交易时段轮替接力，全天保持中高活跃（活跃度系数0.7-1.0）\n"
            "- 欧美时段重叠的13-21点为相对高峰（活跃度系数1.2）\n"
            "- 一般规律：24小时连续活跃、随交易时段切换而起伏，而非单一作息曲线"
        ),
        "time_system_prompt": "你是社交媒体模拟专家。返回纯JSON格式，时间配置需符合跨时区全球市场作息习惯。",
        "default_time_reasoning": "使用默认跨时区全球市场作息配置（每轮1小时）",
        "agent_prompt_rhythm": "- **时间符合全球市场作息**：全天24小时连续活跃，欧美重叠的13-21点相对最活跃",
        "agent_active_hours_hint": "活跃小时列表，考虑跨时区全球市场作息",
        "agent_system_prompt": "你是社交媒体行为分析专家。返回纯JSON，配置需符合跨时区全球市场作息习惯。",
        "peak_hours": [13, 14, 15, 16, 17, 18, 19, 20, 21],
        "off_peak_hours": [0, 1, 2, 3, 4, 5],
        "morning_hours": [6, 7, 8],
        "work_hours": [9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
    },
}


def get_activity_profile() -> Dict[str, Any]:
    """读取当前活动作息画像。

    通过 getattr(Config, 'SIM_ACTIVITY_PROFILE', 'china_social') 选择画像；
    非法/未识别取值一律回退到 'china_social'，确保默认与未配置时行为完全一致。
    """
    raw = getattr(Config, "SIM_ACTIVITY_PROFILE", "china_social")
    name = str(raw or "china_social").strip().lower()
    return ACTIVITY_PROFILES.get(name, ACTIVITY_PROFILES["china_social"])


@dataclass
class AgentActivityConfig:
    """单个Agent的活动配置"""
    agent_id: int
    entity_uuid: str
    entity_name: str
    entity_type: str
    
    # 活跃度配置 (0.0-1.0)
    activity_level: float = 0.5  # 整体活跃度
    
    # 发言频率（每小时预期发言次数）
    posts_per_hour: float = 1.0
    comments_per_hour: float = 2.0
    
    # 活跃时间段（24小时制，0-23）
    active_hours: List[int] = field(default_factory=lambda: list(range(8, 23)))
    
    # 响应速度（对热点事件的反应延迟，单位：模拟分钟）
    response_delay_min: int = 5
    response_delay_max: int = 60
    
    # 情感倾向 (-1.0到1.0，负面到正面)
    sentiment_bias: float = 0.0
    
    # 立场（对特定话题的态度）
    stance: str = "neutral"  # supportive, opposing, neutral, observer
    
    # 影响力权重（决定其发言被其他Agent看到的概率）
    influence_weight: float = 1.0

    # 关注议题（用于 T3.4 同温层聚类；LLM 未给出时为空，聚类退化为仅按 stance）
    interested_topics: List[str] = field(default_factory=list)

    # R2-SIM-3: 角色的「得失结构」（来自深度研究 actors-and-incentives 的 incentives[]）。
    # 决策通道（decision_channel）按这些利害判断角色本轮承诺朝哪个情景，让承诺跟随激励而非
    # 只跟随 stance 标签。缺失即空串 → asdict 仍输出空值、子进程忽略、决策通道退化为仅按立场。
    gains_if: str = ""
    loses_if: str = ""

    # Deterministic actor-specific projection of actor-context/v1 used when
    # selecting activity, topics, stance and influence.  It remains in the
    # saved config for audit and downstream behavior hooks; audience agents
    # and legacy dossiers leave both fields empty.
    actor_context_digest: str = ""
    actor_context_evidence_gap_audit: Dict[str, Any] = field(
        default_factory=dict
    )
    actor_context_urgency: str = ""

    # TEMPORAL: 激活节奏分层。"sampled"（默认）= 按活跃度概率采样激活；"principal" =
    # 日历模式运行脚本每轮无条件激活的主角（非受众且 influence_weight ≥ 0.6 的前 20 名，
    # 一个季度什么都不做的主角是建模错误）。小时制运行路径不读取该字段（additive 新键，
    # 不改变旧行为）。
    cadence: str = "sampled"


@dataclass
class TimeSimulationConfig:
    """时间模拟配置（基于中国人作息习惯）"""
    # 模拟总时长（模拟小时数）
    total_simulation_hours: int = 72  # 默认模拟72小时（3天）
    
    # 每轮代表的时间（模拟分钟）- 默认60分钟（1小时），加快时间流速
    minutes_per_round: int = 60
    
    # 每小时激活的Agent数量范围
    agents_per_hour_min: int = 5
    agents_per_hour_max: int = 20
    
    # 高峰时段（晚间19-22点，中国人最活跃的时间）
    peak_hours: List[int] = field(default_factory=lambda: [19, 20, 21, 22])
    peak_activity_multiplier: float = 1.5
    
    # 低谷时段（凌晨0-5点，几乎无人活动）
    off_peak_hours: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5])
    off_peak_activity_multiplier: float = 0.05  # 凌晨活跃度极低
    
    # 早间时段
    morning_hours: List[int] = field(default_factory=lambda: [6, 7, 8])
    morning_activity_multiplier: float = 0.4
    
    # 工作时段
    work_hours: List[int] = field(default_factory=lambda: [9, 10, 11, 12, 13, 14, 15, 16, 17, 18])
    work_activity_multiplier: float = 0.7


@dataclass
class EventConfig:
    """事件配置"""
    # 初始事件（模拟开始时的触发事件）
    initial_posts: List[Dict[str, Any]] = field(default_factory=list)

    # 定时事件（在特定时间触发的事件）
    scheduled_events: List[Dict[str, Any]] = field(default_factory=list)

    # 热点话题关键词
    hot_topics: List[str] = field(default_factory=list)

    # 舆论引导方向
    narrative_direction: str = ""

    # 初始关注边 [[follower_agent_id, followee_agent_id], ...]（T3.2）
    # 来自研究 relationships[] + 图谱邻边，模拟开始前注入，让 OASIS 不再从空社交图起步。
    initial_follows: List[List[int]] = field(default_factory=list)


@dataclass
class PlatformConfig:
    """平台特定配置"""
    platform: str  # twitter or reddit
    
    # 推荐算法权重
    recency_weight: float = 0.4  # 时间新鲜度
    popularity_weight: float = 0.3  # 热度
    relevance_weight: float = 0.3  # 相关性
    
    # 病毒传播阈值（达到多少互动后触发扩散）
    viral_threshold: int = 10

    # 回声室效应强度（相似观点聚集程度）
    echo_chamber_strength: float = 0.5

    # —— OASIS 推荐器真正消费的旋钮（T3.12；仅当 SIM_WIRE_RECSYS=true 时生效）——
    # 上面的 recency/popularity/relevance/viral_threshold 是展示性权重，OASIS 推荐器并不读取；
    # 下列字段会被映射到 oasis Platform(recsys_type, refresh_rec_post_count, max_rec_post_len,
    # following_post_count)，是真正改变曝光的旋钮。twitter 默认 twhin-bert，reddit 默认 reddit。
    recsys_type: str = ""               # 留空 → 平台默认（twitter:twhin-bert / reddit:reddit）
    refresh_rec_post_count: int = 0     # 0 → 平台默认（twitter:2 / reddit:5）
    max_rec_post_len: int = 0           # 0 → 平台默认（twitter:2 / reddit:100）


@dataclass
class SimulationParameters:
    """完整的模拟参数配置"""
    # 基础信息
    simulation_id: str
    project_id: str
    graph_id: str
    simulation_requirement: str
    
    # 时间配置
    time_config: TimeSimulationConfig = field(default_factory=TimeSimulationConfig)
    
    # Agent配置列表
    agent_configs: List[AgentActivityConfig] = field(default_factory=list)
    
    # 事件配置
    event_config: EventConfig = field(default_factory=EventConfig)
    
    # 平台配置
    twitter_config: Optional[PlatformConfig] = None
    reddit_config: Optional[PlatformConfig] = None
    
    # LLM配置
    llm_provider: str = ""
    llm_model: str = ""
    llm_base_url: str = ""
    
    # 研究截止日（T3.9：锚定模拟时钟 round→date 映射；来自 actors.as_of_date，可空）
    as_of_date: Optional[str] = None

    # NEXTSTEPS SIM_WORLD_BRIEF: 全体 Agent 共享的紧凑世界底稿（预测问题 + 局势简报 + 热点话题，
    # 确定性拼装、无 LLM 调用）。运行脚本据此把同一份世界背景注入每个 Agent 的 system prompt。
    # 空串 → to_dict() 省略该字段（可降级不变式：未启用时配置 JSON 与今日逐字节一致）。
    world_brief: str = ""

    # TEMPORAL spec §3: 顶层 temporal_config 块（日历模式时间线的序列化形态，
    # schema_version=1）。运行侧只按该块是否存在分派新旧路径；None → to_dict() 省略字段
    # （小时制 / SIM_TEMPORAL_MODE=hours 时配置 JSON 与今日逐字节一致）。
    temporal_config: Optional[Dict[str, Any]] = None

    # 模拟内容的输出语言（English / Chinese）。运行脚本据此要求 agent 用该语言发帖与回应，
    # 世界简报用对应语言的标题。空串 → to_dict() 省略字段（旧配置逐字节不变）。
    output_language: str = ""

    # 生成元数据
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    generation_reasoning: str = ""  # LLM的推理说明

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        time_dict = asdict(self.time_config)
        data = {
            "simulation_id": self.simulation_id,
            "project_id": self.project_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "as_of_date": self.as_of_date,
            "time_config": time_dict,
            "agent_configs": [asdict(a) for a in self.agent_configs],
            "event_config": asdict(self.event_config),
            "twitter_config": asdict(self.twitter_config) if self.twitter_config else None,
            "reddit_config": asdict(self.reddit_config) if self.reddit_config else None,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "llm_base_url": self.llm_base_url,
            "generated_at": self.generated_at,
            "generation_reasoning": self.generation_reasoning,
        }
        # NEXTSTEPS SIM_WORLD_BRIEF: 空简报省略字段——运行脚本以 config.get("world_brief")
        # 消费，缺失即整体跳过注入（degrade-safe）。
        if self.world_brief:
            data["world_brief"] = self.world_brief
        # TEMPORAL spec §3: 日历模式附加顶层 temporal_config（additive；旧 time_config
        # 永不改义）。None → 省略字段，运行侧据此走小时制旧路径（字节不变）。
        if self.temporal_config:
            data["temporal_config"] = self.temporal_config
        if self.output_language:
            data["output_language"] = self.output_language
        return data
    
    def to_json(self, indent: int = 2) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class SimulationConfigGenerator:
    """
    模拟配置智能生成器
    
    使用LLM分析模拟需求、文档内容、图谱实体信息，
    自动生成最佳的模拟参数配置
    
    采用分步生成策略：
    1. 生成时间配置和事件配置（轻量级）
    2. 分批生成Agent配置（每批10-20个）
    3. 生成平台配置
    """
    
    # 上下文最大字符数
    MAX_CONTEXT_LENGTH = 50000
    # 每批生成的Agent数量
    AGENTS_PER_BATCH = 15
    
    # 各步骤的上下文截断长度（字符数）
    TIME_CONFIG_CONTEXT_LENGTH = 10000   # 时间配置
    EVENT_CONFIG_CONTEXT_LENGTH = 8000   # 事件配置
    ENTITY_SUMMARY_LENGTH = 300          # 实体摘要
    AGENT_SUMMARY_LENGTH = 300           # Agent配置中的实体摘要
    ENTITIES_PER_TYPE_DISPLAY = 20       # 每类实体显示数量
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        provider: Optional[str] = None
    ):
        self.provider = (provider or Config.LLM_PROVIDER or "claude-cli").lower()
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model_name = model_name or Config.LLM_MODEL_NAME

        # 统一通过 LLMClient 调用（claude-cli / codex-cli / openai）
        self.llm = LLMClient(
            provider=self.provider,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model_name,
        )
    
    def generate_config(
        self,
        simulation_id: str,
        project_id: str,
        graph_id: str,
        simulation_requirement: str,
        document_text: str,
        entities: List[EntityNode],
        enable_twitter: bool = True,
        enable_reddit: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        actors: Optional[Dict[str, Any]] = None,
        actor_context_packs: Optional[Dict[str, Dict[str, Any]]] = None,
        max_rounds: Optional[int] = None,
        research_language: Optional[str] = None,
    ) -> SimulationParameters:
        """
        智能生成完整的模拟配置（分步生成）

        Args:
            simulation_id: 模拟ID
            project_id: 项目ID
            graph_id: 图谱ID
            simulation_requirement: 模拟需求描述
            document_text: 原始文档内容
            entities: 过滤后的实体列表
            enable_twitter: 是否启用Twitter
            enable_reddit: 是否启用Reddit
            progress_callback: 进度回调函数(current_step, total_steps, message)
            actors: 深度研究 actors.json 顶层对象（可选）。提供时：上下文与事件
                    配置注入调研实证（立场/影响力/时间线/热点），初始帖子可按
                    actor 名字定向到对应 Agent，Agent 配置以实证立场为准
            actor_context_packs: selected cast's sealed actor-context/v1 packs;
                    each matching actor receives only its bounded projection
            max_rounds: 运行阶段实际执行的轮数预算（可选）。PREP-1：定时事件按
                        min(配置轮数, max_rounds) 排期，避免关键 flashpoint 落在
                        截断窗口之外被静默丢弃。None → 按 SIM_SCHEDULE_CLAMP_ROUNDS
                        回退到 OASIS_DEFAULT_MAX_ROUNDS（0/关 → 行为不变）
            research_language: 调研语言（可选）。PREP-4：为 English 且未显式设置
                        SIM_ACTIVITY_PROFILE 环境变量时，本次配置切换到
                        global_market 活动画像；未传 → 画像选择不变

        Returns:
            SimulationParameters: 完整的模拟参数
        """
        logger.info(f"开始智能生成模拟配置: simulation_id={simulation_id}, 实体数={len(entities)}")

        # PREP-4(2): 英文调研 + 未显式设置 SIM_ACTIVITY_PROFILE 环境变量 → 本实例切换
        # global_market 画像（作息/提示词口径与英文语料一致）。显式 env 永远优先；
        # research_language 未传（旧调用方）→ 覆盖为 None，画像选择与今日完全一致。
        self._profile_override = None
        # TEMPORAL: 先复位，避免上一次 generate_config 的时间线泄漏到本次（下方按
        # SIM_TEMPORAL_MODE 重建；hours / 构建失败 → 保持 None，全程走旧小时制分支）。
        self._temporal_timeline = None
        if (research_language
                and str(research_language).strip().lower().startswith("en")
                and not str(os.environ.get("SIM_ACTIVITY_PROFILE", "") or "").strip()):
            self._profile_override = "global_market"
            logger.info("活动画像: research_language=English 且未显式配置 SIM_ACTIVITY_PROFILE → global_market")
        # 模拟内容语言：事件配置（热点/种子帖）、世界简报标题与运行期发帖语言都跟随它。
        # 此前事件配置提示是中文且不指定输出语言，英文运行也会产出中文种子帖与热点话题。
        self._output_language = self._resolve_output_language(
            research_language, simulation_requirement
        )
        logger.info(f"模拟输出语言: {self._output_language or '未判定（沿用旧行为）'}")
        
        # 计算总步骤数
        num_batches = math.ceil(len(entities) / self.AGENTS_PER_BATCH)
        total_steps = 3 + num_batches  # 时间配置 + 事件配置 + N批Agent + 平台配置
        current_step = 0
        
        def report_progress(step: int, message: str):
            nonlocal current_step
            current_step = step
            if progress_callback:
                progress_callback(step, total_steps, message)
            logger.info(f"[{step}/{total_steps}] {message}")
        
        # 1. 构建基础上下文信息（含深度研究档案摘要，如有）
        context = self._build_context(
            simulation_requirement=simulation_requirement,
            document_text=document_text,
            entities=entities,
            actors=actors,
            actor_context_packs=actor_context_packs,
        )

        reasoning_parts = []
        if self._profile_override:
            reasoning_parts.append(f"活动画像: {self._profile_override}（英文调研自动选择）")

        # ========== 日历时间线（TEMPORAL spec §4）==========
        # SIM_TEMPORAL_MODE=calendar（默认）→ 解析 as_of / 判定日，把 (as_of, horizon]
        # 按自然日历网格切成回合，随后作为顶层 temporal_config 序列化（运行侧只按该块
        # 是否存在分派新旧路径）。hours / 构建失败 → temporal_timeline=None，下方所有
        # 分支走旧小时制路径（字节不变，degrade-safe）。
        temporal_timeline = None
        if str(getattr(Config, "SIM_TEMPORAL_MODE", "hours") or "").strip().lower() == "calendar":
            try:
                temporal_timeline = self._build_temporal_timeline(
                    simulation_requirement, actors, context, max_rounds
                )
                logger.info(
                    f"日历时间线: {temporal_timeline.unit}×{temporal_timeline.n_rounds} 轮 "
                    f"({temporal_timeline.as_of_date} → {temporal_timeline.horizon_date}, "
                    f"horizon_source={temporal_timeline.horizon_source})"
                )
                reasoning_parts.append(
                    f"日历时间线: {temporal_timeline.unit}×{temporal_timeline.n_rounds} 轮, "
                    f"判定日 {temporal_timeline.horizon_date}（{temporal_timeline.horizon_source}）"
                )
            except Exception as e:
                logger.warning(f"日历时间线构建失败（降级回小时制路径）: {e}")
                temporal_timeline = None
        self._temporal_timeline = temporal_timeline

        # ========== 步骤1: 生成时间配置 ==========
        report_progress(1, "生成时间配置...")
        num_entities = len(entities)
        if temporal_timeline is not None:
            # TEMPORAL: 日历模式跳过 _generate_time_config 的 LLM 调用（昼夜作息输出对
            # 「一轮=一个日历时段」无意义，还省一次调用），改用确定性默认配置并覆盖
            # 兼容垫片字段 total_simulation_hours=n_rounds、minutes_per_round=60——所有
            # 旧的 rounds = hours*60/minutes_per_round 重算点无需修改即得到正确轮数。
            time_config_result = self._get_default_time_config(num_entities)
            time_config = self._parse_time_config(time_config_result, num_entities)
            time_config.total_simulation_hours = temporal_timeline.n_rounds
            time_config.minutes_per_round = 60
            reasoning_parts.append(
                f"时间配置: 日历模式垫片（{temporal_timeline.n_rounds} 轮，跳过LLM作息生成）"
            )
        else:
            time_config_result = self._generate_time_config(context, num_entities)
            time_config = self._parse_time_config(time_config_result, num_entities)
            reasoning_parts.append(f"时间配置: {time_config_result.get('reasoning', '成功')}")

        # ========== 步骤2: 生成事件配置 ==========
        report_progress(2, "生成事件配置和热点话题...")
        event_config_result = self._generate_event_config(
            context,
            simulation_requirement,
            entities,
            actors=actors,
            actor_context_packs=actor_context_packs,
        )
        event_config = self._parse_event_config(
            event_config_result,
            actors=actors,
            actor_context_packs=actor_context_packs,
        )
        reasoning_parts.append(f"事件配置: {event_config_result.get('reasoning', '成功')}")
        
        # ========== 世界底稿（NEXTSTEPS SIM_WORLD_BRIEF）==========
        # 预测问题 + 局势简报 + 热点话题的确定性拼装（无 LLM 调用），写入配置顶层
        # world_brief 字段；运行脚本据此把同一份世界背景注入全体 Agent 的 system prompt。
        # 任何一段缺失 → 简报变短；全部缺失 / 开关关闭 → 空串（to_dict 省略字段）。
        # ITEM 11 SIM_MARKET_PRIORS: 载入本次运行 handoff 的 relevance-gated 市场快照
        # （prediction_markets.json），供世界底稿注入「市场定价」块。开关关/无对应 handoff/
        # 文件缺失/解析失败 → []（world_brief 与今日逐字节一致）。
        market_priors = self._load_prediction_markets(simulation_id)
        if market_priors:
            logger.info(f"市场先验: 载入 {len(market_priors)} 个 relevance-gated 市场")
        world_brief = ""
        try:
            world_brief = self._build_world_brief(
                simulation_requirement, actors, event_config.hot_topics,
                prediction_markets=market_priors,
                actor_context_packs=actor_context_packs,
            )
            if world_brief:
                reasoning_parts.append(f"世界简报: {len(world_brief)} 字")
        except Exception as e:
            logger.warning(f"世界简报构建失败（降级省略，不影响模拟）: {e}")
            world_brief = ""

        # ========== 步骤3-N: 分批生成Agent配置 ==========
        # PREP-4(1): 按批记录 LLM 成功/规则回退，让 generation_reasoning 能区分
        # 「LLM 塑形的角色阵容」与「全默认值阵容」（此前无条件报「成功生成 N 个」）。
        self._agent_batch_stats = {"llm_batches": 0, "rule_batches": 0, "rule_agents": 0}
        all_agent_configs = []
        for batch_idx in range(num_batches):
            start_idx = batch_idx * self.AGENTS_PER_BATCH
            end_idx = min(start_idx + self.AGENTS_PER_BATCH, len(entities))
            batch_entities = entities[start_idx:end_idx]
            
            report_progress(
                3 + batch_idx,
                f"生成Agent配置 ({start_idx + 1}-{end_idx}/{len(entities)})..."
            )
            
            batch_configs = self._generate_agent_configs_batch(
                context=context,
                entities=batch_entities,
                start_idx=start_idx,
                simulation_requirement=simulation_requirement,
                actors=actors,
                actor_context_packs=actor_context_packs,
            )
            all_agent_configs.extend(batch_configs)
        
        _bs = self._agent_batch_stats
        reasoning_parts.append(
            f"Agent配置: LLM {_bs['llm_batches']}/{num_batches} 批, 规则回退 {_bs['rule_batches']} 批"
            f"（规则兜底 {_bs['rule_agents']} 个Agent）, 共 {len(all_agent_configs)} 个"
        )
        if _bs["rule_batches"]:
            logger.warning(
                f"Agent配置: {_bs['rule_batches']}/{num_batches} 批 LLM 失败退化为规则生成"
                f"（{_bs['rule_agents']} 个Agent为默认口径）"
            )
        
        # ========== 为初始帖子分配发布者 Agent ==========
        logger.info("为初始帖子分配合适的发布者 Agent...")
        event_config = self._assign_initial_post_agents(event_config, all_agent_configs)
        assigned_count = len([p for p in event_config.initial_posts if p.get("poster_agent_id") is not None])
        reasoning_parts.append(f"初始帖子分配: {assigned_count} 个帖子已分配发布者")

        # ========== 追加「沉默的大多数」受众群体（I-2-2）==========
        # 在具名调研角色（all_agent_configs）之后，按 SIM_AUDIENCE_AGENTS（兼容旧名
        # SIM_AUDIENCE_SIZE）追加 M 个程序化生成的
        # 低影响力受众 Agent（不做逐个 LLM 调研）：立场按调研立场分布抽样、议题复用热点话题、
        # 高潜水偏好（低活跃度 + 低影响力）。它们的 agent_id 与具名角色连续，使 OASIS 的
        # agent_graph 下标保持一致；并在 _build_echo_chamber_follows 之前追加，从而自然加入同温层
        # 聚类。SIM_AUDIENCE_AGENTS 默认 0 → 完全保持当前行为（不生成受众，池子只含主阵容）。
        try:
            audience_configs = self._generate_audience_agent_configs(
                start_idx=len(all_agent_configs),
                event_config=event_config,
                actors=actors,
                main_agent_configs=all_agent_configs,
                actor_context_packs=actor_context_packs,
            )
            if audience_configs:
                all_agent_configs.extend(audience_configs)
                reasoning_parts.append(f"受众群体: 追加 {len(audience_configs)} 个沉默大多数 Agent")
                logger.info(f"受众群体（沉默大多数）: 追加 {len(audience_configs)} 个 Agent")
        except Exception as e:
            logger.warning(f"受众群体生成失败（降级跳过，不影响模拟）: {e}")

        # ========== 主角节奏分层（TEMPORAL cadence tiering）==========
        # 非受众且 influence_weight ≥ 0.6 的阵容按影响力降序（并列按 agent_id 升序）取前
        # 20 名标记 cadence="principal"；受众与其余保持默认 "sampled"。日历模式运行脚本
        # 每轮无条件激活 principal；小时制运行路径不读该字段（additive，不改变旧行为）。
        try:
            n_principal = self._assign_cadence_tiers(all_agent_configs)
            if n_principal:
                reasoning_parts.append(f"主角节奏: {n_principal} 个 principal")
        except Exception as e:
            logger.warning(f"主角节奏分层失败（全部保持 sampled）: {e}")

        # ========== 构建初始关注图（T3.2）==========
        # 研究 relationships[] → 有向关注边（方向遵循 actors.build_initial_follow_graph 的语义），
        # 再用图谱邻边补充（relationships[] 稀疏时也能成形）。模拟开始前注入，杜绝空社交图。
        try:
            event_config.initial_follows = self._build_initial_follows(
                all_agent_configs,
                entities,
                actors,
                actor_context_packs=actor_context_packs,
            )
            reasoning_parts.append(f"初始关注图: {len(event_config.initial_follows)} 条关注边")
            logger.info(f"初始关注图: {len(event_config.initial_follows)} 条关注边")
        except Exception as e:
            logger.warning(f"初始关注图构建失败（降级为空，不影响模拟）: {e}")
            event_config.initial_follows = []

        # ========== 回放研究时间线为定时事件（T3.8）==========
        # key_events → 映射到 [0, total_rounds) 的 scheduled_events，附上最相关的高影响力发布者；
        # 运行脚本在对应轮次以 CREATE_POST 触发。无 key_events / 无法解析 → 空，不影响模拟。
        try:
            event_config.scheduled_events = self._build_scheduled_events(
                actors, time_config, all_agent_configs, max_rounds=max_rounds,
                timeline=temporal_timeline,
                actor_context_packs=actor_context_packs,
            )
            if event_config.scheduled_events:
                reasoning_parts.append(f"定时事件: {len(event_config.scheduled_events)} 个")
                logger.info(f"定时事件（时间线回放）: {len(event_config.scheduled_events)} 个")
        except Exception as e:
            logger.warning(f"定时事件构建失败（降级为空，不影响模拟）: {e}")
            event_config.scheduled_events = []

        # ========== 把 echo-chamber 同温层关注补进初始关注图（T3.4）==========
        try:
            extra = self._build_echo_chamber_follows(
                all_agent_configs,
                twitter_config_strength=None,
                actors=actors,
                actor_context_packs=actor_context_packs,
            )
            if extra:
                merged = {(a, b) for (a, b) in (tuple(p) for p in event_config.initial_follows)}
                before = len(merged)
                merged |= {(a, b) for (a, b) in extra}
                event_config.initial_follows = [[a, b] for (a, b) in sorted(merged)]
                logger.info(f"同温层关注边: 新增 {len(merged) - before} 条（echo-chamber）")
                reasoning_parts.append(f"同温层关注: +{len(merged) - before} 条")
        except Exception as e:
            logger.warning(f"同温层关注构建失败（降级跳过，不影响模拟）: {e}")

        # ========== 最后一步: 生成平台配置 ==========
        report_progress(total_steps, "生成平台配置...")
        twitter_config = None
        reddit_config = None
        
        if enable_twitter:
            twitter_config = PlatformConfig(
                platform="twitter",
                recency_weight=0.4,
                popularity_weight=0.3,
                relevance_weight=0.3,
                viral_threshold=10,
                echo_chamber_strength=0.5
            )
        
        if enable_reddit:
            reddit_config = PlatformConfig(
                platform="reddit",
                recency_weight=0.3,
                popularity_weight=0.4,
                relevance_weight=0.3,
                viral_threshold=15,
                echo_chamber_strength=0.6
            )
        
        # 构建最终参数
        params = SimulationParameters(
            simulation_id=simulation_id,
            project_id=project_id,
            graph_id=graph_id,
            simulation_requirement=simulation_requirement,
            time_config=time_config,
            agent_configs=all_agent_configs,
            event_config=event_config,
            twitter_config=twitter_config,
            reddit_config=reddit_config,
            as_of_date=(str((actors or {}).get("as_of_date")) if isinstance(actors, dict) and actors.get("as_of_date") else None),
            world_brief=world_brief,
            output_language=getattr(self, "_output_language", "") or "",
            # TEMPORAL spec §3: beyond_horizon_events/warnings 已在 _build_scheduled_events
            # 中回填到 timeline，此处一次性序列化（None → to_dict 省略字段）。
            temporal_config=(asdict(temporal_timeline) if temporal_timeline is not None else None),
            llm_provider=self.provider,
            llm_model=self.model_name,
            llm_base_url=self.base_url,
            generation_reasoning=" | ".join(reasoning_parts)
        )
        
        logger.info(f"模拟配置生成完成: {len(params.agent_configs)} 个Agent配置")

        return params

    # 每个 agent 从图谱邻边最多派生的关注数（防止稠密图把关注表撑爆）
    MAX_GRAPH_FOLLOWS_PER_AGENT = 8

    def _activity_profile(self) -> Dict[str, Any]:
        """本实例生效的活动画像：generate_config 计算的覆盖（PREP-4(2)）优先，否则读全局配置。"""
        name = getattr(self, "_profile_override", None)
        if name:
            return ACTIVITY_PROFILES.get(name, ACTIVITY_PROFILES["china_social"])
        return get_activity_profile()

    def _build_initial_follows(
        self,
        agent_configs: List[AgentActivityConfig],
        entities: List[EntityNode],
        actors: Optional[Dict[str, Any]],
        actor_context_packs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[List[int]]:
        """T3.2: relationships[] + 图谱邻边 → 去重的初始关注边 [[follower, followee]]。

        研究 relationships[] 走 ``build_initial_follow_graph`` 的方向语义（盟友低→高、
        依赖方→被依赖方、受众→影响者……）；图谱邻边作为补充，让 relationships[] 稀疏时
        也能形成初始社交结构。自环/越界 id 一律剔除。
        """
        # PREP-10: 同名归一实体的平局裁决与 _build_echo_chamber_follows 保持一致——首个胜出。
        # （此前 dict 推导为末个胜出，两处跟随图会把关系边挂到不同的物理 agent。）
        agent_id_by_name: Dict[str, int] = {}
        dup_names: List[str] = []
        for c in agent_configs:
            if not c.entity_name:
                continue
            key = normalize_name(c.entity_name)
            if key in agent_id_by_name:
                dup_names.append(c.entity_name)
            else:
                agent_id_by_name[key] = c.agent_id
        if dup_names:
            logger.warning(
                f"初始关注图: {len(dup_names)} 个重名实体（首个胜出，上游实体解析可能有泄漏）: {dup_names[:5]}"
            )
        pairs: set = set()
        canonical_v1 = self._dossier_uses_canonical_intelligence(actors)
        # 1. 研究关系（带方向语义）。Canonical v1 never reopens raw
        # top-level relationships; only sealed, source-bound public/actor-local
        # rows may shape behavior.
        if canonical_v1:
            relationship_rows = self._canonical_context_relationship_rows(
                actors, actor_context_packs
            )
            pairs.update(self._canonical_relationship_follow_pairs(
                relationship_rows, agent_id_by_name
            ))
        else:
            for f in build_initial_follow_graph(actors, agent_id_by_name):
                if len(f) == 2:
                    pairs.add((f[0], f[1]))
        # 2. 图谱邻边补充
        # Graph-neighbor edges are an unsealed compatibility source. They are
        # retained byte-for-byte for unversioned dossiers and excluded for v1.
        if not canonical_v1:
            name_by_uuid = {e.uuid: e.name for e in entities}
            for e in entities:
                src = agent_id_by_name.get(normalize_name(e.name))
                if src is None:
                    continue
                added = 0
                for edge in (e.related_edges or []):
                    if added >= self.MAX_GRAPH_FOLLOWS_PER_AGENT:
                        break
                    other_uuid = edge.get("target_node_uuid") or edge.get("source_node_uuid")
                    if not other_uuid:
                        continue
                    other_name = name_by_uuid.get(other_uuid)
                    if not other_name:
                        continue
                    dst = agent_id_by_name.get(normalize_name(other_name))
                    if dst is None or dst == src:
                        continue
                    # 出边：src 关注邻居；入边：邻居关注 src（监控/受影响方向）
                    if edge.get("direction") == "outgoing":
                        pairs.add((src, dst))
                    else:
                        pairs.add((dst, src))
                    added += 1
        valid = {c.agent_id for c in agent_configs}
        return [[a, b] for (a, b) in sorted(pairs) if a in valid and b in valid]

    # TEMPORAL: principal 节奏名额上限与影响力门槛（全体主角每轮必激活，规模失控会挤掉采样阵容）
    PRINCIPAL_CADENCE_MAX = 20
    PRINCIPAL_CADENCE_MIN_INFLUENCE = 0.6
    # SIM-ADD-4：退化守卫参数。取证（sim_05ab2bdebbd2）：12 名 actor 全落 principal（每轮必激活）
    # → 每轮名册恒等 → 决策通道 elicitation 缓存塌成 1 条 unique roster → 18 轮模拟只贡献一个
    # 重复信号（节奏毫无区分度）。仅在「按满额会让**整个非受众阵容**都成 principal、且阵容
    # 够大」时，把名额压到 ceil(阵容 × FRACTION)，强制保留一个 sampled 层，让逐轮名册产生可分辨
    # 差异（头部真主角仍每轮必激活）。已有 sampled 层的阵容（如 23 合格取 20、余 3 采样）不受影响。
    PRINCIPAL_CADENCE_FRACTION = 0.5
    PRINCIPAL_CADENCE_GRADE_MIN = 4

    def _assign_cadence_tiers(self, agent_configs: List[AgentActivityConfig]) -> int:
        """TEMPORAL: 非受众且 influence_weight ≥ 0.6 的阵容按影响力降序（并列按 agent_id
        升序）取头部标记 cadence="principal"；其余（含全部受众）保持 "sampled"。返回标记数。
        确定性实现，不依赖随机数。

        SIM-ADD-4：仅当满额 principal 会覆盖**整个**非受众阵容（=零 sampled 非受众 → 每轮
        名册恒等、决策通道信号塌成单条重复）且阵容 > PRINCIPAL_CADENCE_GRADE_MIN 时，把名额
        压到 ``max(GRADE_MIN, ceil(非受众数 × FRACTION))``，强制保留 sampled 层。其余情形（已存在
        sampled 非受众、或小阵容）行为与旧「前 20」实现逐字节一致。
        """
        non_audience = [
            c for c in agent_configs
            if c.entity_type != self.AUDIENCE_ENTITY_TYPE
        ]
        eligible = [
            c for c in non_audience
            if c.influence_weight >= self.PRINCIPAL_CADENCE_MIN_INFLUENCE
        ]
        eligible.sort(key=lambda c: (-c.influence_weight, c.agent_id))
        principal_budget = self.PRINCIPAL_CADENCE_MAX
        # 退化守卫：满额会让整个非受众阵容都成 principal（零 sampled 非受众）→ 收紧名额。
        if (len(non_audience) > self.PRINCIPAL_CADENCE_GRADE_MIN
                and min(len(eligible), principal_budget) >= len(non_audience)):
            principal_budget = max(
                self.PRINCIPAL_CADENCE_GRADE_MIN,
                math.ceil(len(non_audience) * self.PRINCIPAL_CADENCE_FRACTION),
            )
        chosen = eligible[:principal_budget]
        for c in chosen:
            c.cadence = "principal"
        return len(chosen)

    def _build_temporal_timeline(
        self,
        simulation_requirement: str,
        actors: Optional[Dict[str, Any]],
        context: str,
        max_rounds: Optional[int] = None,
    ) -> sim_timeline.SimulationTimeline:
        """TEMPORAL spec §4: 解析 as_of 与判定日（horizon），构建日历回合时间线。

        * as_of：actors["as_of_date"] 经 parse_as_of 解析；不可解析/缺失 → 运行日 +
          warning ``as_of_defaulted``。
        * 判定日阶梯：sim_timeline.extract_horizon（确定性四层，输入 =
          模拟需求 + "\\n" + central_question）→ _llm_extract_horizon（单次 JSON 兜底）
          → default_horizon(as_of, SIM_HORIZON_DEFAULT_MONTHS)。
        * target_max = min(SIM_CALENDAR_TARGET_MAX_ROUNDS, max_rounds, OASIS_DEFAULT_MAX_ROUNDS)
          （后两者未设/非正视为 ∞）——显式回合上限只粗化时间粒度、绝不截断预测期
          （build_timeline 记 round_cap_coarsened）。
        """
        as_of_raw = actors.get("as_of_date") if isinstance(actors, dict) else None
        parsed = parse_as_of(as_of_raw)
        as_of_defaulted = parsed is None
        as_of = parsed.date() if parsed is not None else datetime.now().date()
        if as_of_defaulted:
            logger.warning(f"as_of_date 不可解析（{as_of_raw!r}），默认取运行日 {as_of.isoformat()}")

        # 判定日阶梯：确定性抽取 → LLM 兜底 → 默认 12 个月
        cq = str(actors.get("central_question", "") or "") if isinstance(actors, dict) else ""
        horizon = sim_timeline.extract_horizon(f"{simulation_requirement}\n{cq}", as_of)
        if horizon is None:
            horizon = self._llm_extract_horizon(context, as_of)
        if horizon is None:
            horizon = sim_timeline.default_horizon(
                as_of, int(getattr(Config, "SIM_HORIZON_DEFAULT_MONTHS", 12) or 12)
            )

        target_max = int(getattr(Config, "SIM_CALENDAR_TARGET_MAX_ROUNDS", 36) or 36)
        try:
            if max_rounds is not None and int(max_rounds) > 0:
                target_max = min(target_max, int(max_rounds))
        except (TypeError, ValueError):
            pass
        oasis_cap = int(getattr(Config, "OASIS_DEFAULT_MAX_ROUNDS", 0) or 0)
        if oasis_cap > 0:
            target_max = min(target_max, oasis_cap)

        timeline = sim_timeline.build_timeline(
            as_of,
            horizon,
            target_max=target_max,
            reference_max=int(getattr(Config, "SIM_CALENDAR_TARGET_MAX_ROUNDS", 36) or 36),
            hard_max=int(getattr(Config, "SIM_CALENDAR_HARD_MAX_ROUNDS", 48) or 48),
        )
        if as_of_defaulted:
            timeline.warnings.append("as_of_defaulted")
        return timeline

    def _llm_extract_horizon(self, context: str, as_of) -> Optional[sim_timeline.HorizonResult]:
        """TEMPORAL: 确定性四层抽取落空时的 LLM 兜底——单次 JSON 调用抽取判定日。

        约定返回 ``{"horizon_date": "YYYY-MM-DD" | null}``；结果经 parse_as_of 复验，
        且必须落在 (as_of, as_of+30年] 内，否则丢弃返回 None（继续降级到默认时域）。
        任何调用/解析异常 → None，绝不阻断配置生成。
        """
        context_truncated = context[:self.TIME_CONFIG_CONTEXT_LENGTH]
        prompt = f"""从以下预测问题与背景材料中找出「预测判定日」（问题所问的结果应在哪一天之前见分晓）。

{context_truncated}

## 任务
只返回JSON（不要markdown）：
{{"horizon_date": "YYYY-MM-DD"}}

规则：
- 优先取问题文本中明示的期限/日期；只给年份时取该年12月31日
- 材料中找不到任何期限线索时返回 {{"horizon_date": null}}
- 不要编造：宁可返回 null 也不要猜一个没有依据的日期"""
        system_prompt = "你是预测问题分析专家。返回纯JSON格式。"
        try:
            result = self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"判定日LLM兜底失败: {e}")
            return None
        parsed = parse_as_of((result or {}).get("horizon_date"))
        if parsed is None:
            return None
        d = parsed.date()
        limit = sim_timeline._add_months(as_of, 360)  # as_of + 30 年（真日历加法）
        if not (as_of < d <= limit):
            logger.warning(f"判定日LLM兜底越界丢弃: {d.isoformat()} (as_of={as_of.isoformat()})")
            return None
        return sim_timeline.HorizonResult(d.isoformat(), "llm", "", False, 0.7)

    def _build_scheduled_events(
        self,
        actors: Optional[Dict[str, Any]],
        time_config: "TimeSimulationConfig",
        agent_configs: List[AgentActivityConfig],
        max_rounds: Optional[int] = None,
        timeline: Optional[sim_timeline.SimulationTimeline] = None,
        actor_context_packs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """T3.8: 研究 key_events → 映射到 [0,total_rounds) 的定时事件，附最相关高影响力发布者。

        每个事件优先定向到事件文本里提到的真实角色 Agent；否则回退到全局影响力最高的 Agent。
        无 key_events / 无法解析日期 → []（模拟不变）。返回项形如
        ``{"round","content","date","poster_agent_id","poster_name"}``。

        PREP-1: 运行阶段按 options.max_rounds / OASIS_DEFAULT_MAX_ROUNDS 截断实际轮数，
        而事件此前按配置全轮数（如 72）排期——关键 flashpoint 落在截断窗口外被静默丢弃。
        排期域改为 min(配置轮数, 执行轮数预算)：显式 max_rounds 优先；未接线时按
        SIM_SCHEDULE_CLAMP_ROUNDS 回退到 OASIS_DEFAULT_MAX_ROUNDS。预算<=0 → 不变。

        TEMPORAL spec §4: 传入 ``timeline``（日历模式）→ 改走 events_to_calendar_rounds
        的区间包含落轮：不做比例压缩、不做 PREP-5 反应缓冲（fire_scheduled_events 在每轮
        agent 激活前触发，同期反应有保障），事件内容加 ``[日期] `` 前缀；晚于判定日的
        事件完整留档到 timeline.beyond_horizon_events，日期不可解析的条目排除并记
        ``event_date_unparsed:<n>`` warning。timeline=None（小时制）→ 旧路径字节不变。
        """
        if not isinstance(actors, dict) or not agent_configs:
            return []
        event_source = actors
        if self._dossier_uses_canonical_intelligence(actors):
            safe_events = self._canonical_context_event_rows(
                actors, actor_context_packs
            )
            if not safe_events:
                return []
            # Utilities below consume only key_events/as_of_date.  Canonical
            # event content comes exclusively from sealed public rows.
            event_source = {
                "as_of_date": actors.get("as_of_date"),
                "key_events": safe_events,
            }
        calendar = timeline is not None
        if calendar:
            schedule, beyond = events_to_calendar_rounds(
                event_source,
                timeline.round_dates,
                timeline.as_of_date,
                timeline.horizon_date,
            )
            timeline.beyond_horizon_events = beyond
            evs = event_source.get("key_events")
            unparsed = sum(
                1 for e in (evs if isinstance(evs, list) else [])
                if isinstance(e, dict) and parse_as_of(e.get("date")) is None
            )
            if unparsed:
                timeline.warnings.append(f"event_date_unparsed:{unparsed}")
                logger.warning(f"定时事件: {unparsed} 个事件日期不可解析，已排除")
            if beyond:
                logger.info(
                    f"定时事件: {len(beyond)} 个事件晚于判定日 {timeline.horizon_date}，"
                    f"留档 beyond_horizon_events 不落轮"
                )
        else:
            config_rounds = max(
                1,
                int(time_config.total_simulation_hours * 60 / max(1, time_config.minutes_per_round)),
            )
            budget = 0
            try:
                if max_rounds is not None and int(max_rounds) > 0:
                    budget = int(max_rounds)
                elif getattr(Config, "SIM_SCHEDULE_CLAMP_ROUNDS", True):
                    budget = int(getattr(Config, "OASIS_DEFAULT_MAX_ROUNDS", 0) or 0)
            except (TypeError, ValueError):
                budget = 0
            total_rounds = min(config_rounds, budget) if budget > 0 else config_rounds
            if total_rounds < config_rounds:
                logger.info(f"定时事件: 排期轮数按执行预算钳制 {config_rounds} -> {total_rounds}")
            as_of = event_source.get("as_of_date")
            schedule = events_to_schedule(event_source, total_rounds, as_of)
        if not schedule:
            return []
        # 名字 → agent 索引（用于把事件定向到被提及的真实角色）
        agents_by_name = {
            normalize_name(c.entity_name): c for c in agent_configs if c.entity_name
        }
        fallback = max(agent_configs, key=lambda a: a.influence_weight)
        out: List[Dict[str, Any]] = []
        for ev in schedule:
            text = str(ev.get("event") or "").strip()
            if not text:
                continue
            poster = None
            for nm, cand in agents_by_name.items():
                if len(nm) >= 2 and nm in normalize_name(text):
                    poster = cand
                    break
            poster = poster or fallback
            out.append({
                "round": int(ev.get("round", 0)),
                # TEMPORAL: 日历模式给事件内容加 "[日期] " 前缀，让 agent 看到确切日期；
                # 小时制内容不变（字节不变）。
                "content": (f"[{ev.get('date')}] {text}" if calendar else text),
                "date": ev.get("date"),
                "poster_agent_id": poster.agent_id,
                "poster_name": poster.entity_name,
            })
        return out

    def _valence_signal_active(
        self,
        actors: Optional[Dict[str, Any]],
        actor_context_packs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> bool:
        """C5 准入门：研究档案是否携带「价感知」信号。

        仅当 SIM_VALENCED_RELATIONS 为真，且 relationships[] 中至少有一条边携带显式
        valence/polarity 字段、或一个超出旧 8 类的新关系类型时返回 True。否则（今日数据）
        返回 False，从而让价感知的同温层关注与情感种子整体跳过，行为逐字节不变。

        端点能否匹配到 actor 不在判定范围内——只要研究方写出了新字段/新类型，就视为意图
        启用价感知；不携带新信号的旧 8 类档案永远走 False 分支。
        """
        if not getattr(Config, "SIM_VALENCED_RELATIONS", True):
            return False
        if not isinstance(actors, dict):
            return False
        if self._dossier_uses_canonical_intelligence(actors):
            rels = self._canonical_context_relationship_rows(
                actors, actor_context_packs
            )
        else:
            rels = actors.get("relationships")
            if not isinstance(rels, list):
                return False
        for r in rels:
            if not isinstance(r, dict):
                continue
            # 显式 valence/polarity 字段 → 新信号
            if str(r.get("valence", "") or "").strip():
                return True
            pol = r.get("polarity")
            if isinstance(pol, (int, float)) and not isinstance(pol, bool):
                return True
            # 超出旧 8 类的关系类型 → 新信号
            typ = str(r.get("type", "") or "").strip().upper()
            if typ and typ not in _LEGACY_REL_TYPES:
                return True
        return False

    def _relation_sentiment_nudge(
        self,
        actor_name: str,
        actors: Optional[Dict[str, Any]],
        actor_context_packs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> float:
        """C5: 由一个具名角色的关系边聚合出对其整体情感偏置的「加性微调」∈ [-0.5, 0.5]。

        对该角色参与的每条关系取 relation_polarity（盟友为正、对手为负、交易性微正），
        以涉及自身的边的平均极性作为方向，再缩到一个温和幅度（×0.5），叠加到既有
        sentiment_bias 上。匿名受众（名字不在 relationships[] 中）→ 0.0，故受众情感不变。

        仅在 _valence_signal_active 为真时被调用；今日数据下整体跳过，返回值不会被使用。
        """
        if not actor_name:
            return 0.0
        canonical_v1 = self._dossier_uses_canonical_intelligence(actors)
        rows = (
            self._canonical_context_relationship_rows(
                actors, actor_context_packs
            )
            if canonical_v1 else extract_relationship_rows(actors)
        )
        if not rows:
            return 0.0
        me = normalize_name(actor_name)
        if not me:
            return 0.0
        polarities: List[float] = []
        for r in rows:
            s = normalize_name(str(r.get("source", "") or ""))
            t = normalize_name(str(r.get("target", "") or ""))
            if me != s and me != t:
                continue
            if (
                canonical_v1
                and r.get("_runtime_scope") == "actor_local"
                and me != normalize_name(str(r.get("_context_actor_name") or ""))
            ):
                continue
            polarities.append(relation_polarity(r))
        if not polarities:
            return 0.0
        avg = sum(polarities) / len(polarities)
        # 温和幅度：均值极性 ×0.5，再夹到 [-0.5, 0.5]，避免覆盖 LLM/规则给出的主立场。
        return max(-0.5, min(0.5, avg * 0.5))

    def _build_echo_chamber_follows(
        self,
        agent_configs: List[AgentActivityConfig],
        twitter_config_strength: Optional[float] = None,
        actors: Optional[Dict[str, Any]] = None,
        actor_context_packs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> "set":
        """T3.4: 按 (stance 桶, 主导议题) 聚类，在簇内加同温层关注边，高影响力 Agent 留跨簇桥。

        强度由 echo_chamber_strength 控制（默认 0.5）：簇内每个 Agent 关注最多 ``round(3×强度)``
        个同簇高影响力 Agent；少数高影响力 Agent 额外关注几个其他簇的高影响力 Agent（让叙事仍能
        外溢）。确定性实现（不依赖随机数），避免运行间漂移。返回 ``{(follower, followee), ...}``。

        C5（价感知，gated by SIM_VALENCED_RELATIONS）：在上述 (stance, topic, influence) 聚类
        基线之上，额外按关系价补边——盟友/伙伴/支持等「allied」边互相关注（把同盟拉得更紧），
        对抗/制裁/批评等「adversarial」边让双方互相关注（跨阵营的「桥接式对立」，使对立叙事彼此
        可见而非各自回声）。仅当 _valence_signal_active 为真（研究档案带显式 valence/polarity 或
        新关系类型）才追加；今日数据（只有旧 8 类、无新字段）下该段整体跳过，返回逐字节不变。
        """
        from collections import defaultdict

        strength = 0.5 if twitter_config_strength is None else float(twitter_config_strength)
        if strength <= 0 or len(agent_configs) < 3:
            return set()
        clusters: Dict[Any, List[AgentActivityConfig]] = defaultdict(list)
        for c in agent_configs:
            topic = ""
            if c.interested_topics:
                topic = normalize_name(str(c.interested_topics[0]))
            clusters[(str(c.stance or "neutral").lower(), topic)].append(c)
        pairs: set = set()
        k = max(1, round(3 * strength))  # strength 0.5 -> ~2
        for members in clusters.values():
            if len(members) < 2:
                continue
            ranked = sorted(members, key=lambda a: a.influence_weight, reverse=True)
            for c in members:
                followed = 0
                for peer in ranked:
                    if peer.agent_id == c.agent_id:
                        continue
                    pairs.add((c.agent_id, peer.agent_id))
                    followed += 1
                    if followed >= k:
                        break
        # 跨簇桥：让 top 影响力 Agent 互相关注，narratives 可外溢
        n_bridge = max(2, len(agent_configs) // 10)
        high = sorted(agent_configs, key=lambda a: a.influence_weight, reverse=True)[:n_bridge]
        for c in high:
            bridges = 0
            for peer in high:
                if peer.agent_id == c.agent_id:
                    continue
                pairs.add((c.agent_id, peer.agent_id))
                bridges += 1
                if bridges >= 2:
                    break

        # ---- C5 价感知补边（仅当研究档案携带 valence/polarity/新关系类型时）----
        # 旧 8 类、无新字段的今日数据走 _valence_signal_active==False，整段跳过 → pairs 不变。
        if self._valence_signal_active(actors, actor_context_packs):
            agent_by_name: Dict[str, AgentActivityConfig] = {}
            for c in agent_configs:
                if c.entity_name:
                    # 同名只保留首个（与初始关注图按出现序的口径一致）
                    agent_by_name.setdefault(normalize_name(c.entity_name), c)
            canonical_v1 = self._dossier_uses_canonical_intelligence(actors)
            relationship_rows = (
                self._canonical_context_relationship_rows(
                    actors, actor_context_packs
                )
                if canonical_v1 else extract_relationship_rows(actors)
            )
            for r in relationship_rows:
                src = agent_by_name.get(normalize_name(str(r.get("source", "") or "")))
                dst = agent_by_name.get(normalize_name(str(r.get("target", "") or "")))
                if src is None or dst is None or src.agent_id == dst.agent_id:
                    continue
                valence = relation_valence(r)
                local_owner = agent_by_name.get(normalize_name(
                    str(r.get("_context_actor_name") or "")
                ))
                if valence == "allied":
                    # 盟友互相关注，把同盟拉得更紧
                    candidates = [
                        (src.agent_id, dst.agent_id),
                        (dst.agent_id, src.agent_id),
                    ]
                elif valence == "adversarial":
                    # 桥接式对立：对立双方互相关注（盯住对方阵营），narratives 跨阵营可见
                    candidates = [
                        (src.agent_id, dst.agent_id),
                        (dst.agent_id, src.agent_id),
                    ]
                else:
                    candidates = []
                for follower, followee in candidates:
                    if (
                        canonical_v1
                        and r.get("_runtime_scope") == "actor_local"
                        and (
                            local_owner is None
                            or follower != local_owner.agent_id
                        )
                    ):
                        continue
                    pairs.add((follower, followee))
        return pairs

    # NEXTSTEPS SIM_WORLD_BRIEF: 世界底稿的确定性长度上限（无 LLM 调用，纯拼装）。
    WORLD_BRIEF_MAX_CHARS = 1400
    WORLD_BRIEF_QUESTION_CHARS = 400
    # ITEM 11 SIM_MARKET_PRIORS: 世界底稿注入的头部相关市场数（top N：question + 隐含 P）。
    MARKET_PRIORS_TOP_N = 5

    def _market_priors_enabled(self) -> bool:
        """ITEM 11: 市场先验注入开关（SIM_MARKET_PRIORS，默认开）。

        关闭 → 不加载 prediction_markets.json，世界底稿/人设与今日逐字节一致。
        __new__ 构造的实例（测试）走 getattr 缺省 True。
        """
        raw = getattr(Config, "SIM_MARKET_PRIORS", True)
        return str(raw).strip().lower() not in ("false", "0", "no", "off")

    def _load_prediction_markets(self, simulation_id: Optional[str]) -> List[Dict[str, Any]]:
        """ITEM 11: 加载本次运行 handoff 的 prediction_markets.json（relevance-gated 市场）。

        与 report_agent._load_prediction_markets / load_research_dossier_for_simulation 同模式：
        按 simulation_id 定位管线 handoff 目录，读 prediction_markets.json 的 markets[]（研究阶段
        已做相关性门控，带 question/implied_yes_prob/relevance_score/volume）。延迟导入
        PipelineManager 规避与 pipeline_orchestrator 的模块级循环依赖。

        开关关 / 无 simulation_id / 无对应管线 / 文件缺失 / 解析失败 → []（degrade-safe，
        world_brief 与今日逐字节一致）。
        TIME-3（PREDICTION_MARKETS_END_DATE_GATE，默认开）：截止日已过（market_clock_now()）或
        已盖 window_ended 章的市场不作为模拟先验（其近定盘价会被当成开放信念），剔除数记日志。
        """
        if not self._market_priors_enabled() or not simulation_id:
            return []
        try:
            from .pipeline_orchestrator import PipelineManager
            for entry in PipelineManager.list_pipelines():
                pid = entry.get("pipeline_id")
                if not pid:
                    continue
                data = PipelineManager.load(pid)
                if not data or data.get("simulation_id") != simulation_id:
                    continue
                hd = data.get("handoff_dir") or PipelineManager.handoff_dir(pid)
                path = os.path.join(hd, "prediction_markets.json")
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        payload = json.load(f)
                    markets = payload.get("markets") if isinstance(payload, dict) else payload
                    from ..utils.prediction_markets import drop_window_ended_rows
                    rows, ended = drop_window_ended_rows(
                        [m for m in (markets or []) if isinstance(m, dict)])
                    if ended:
                        logger.info(f"市场先验：剔除 {ended} 个已过截止日的市场"
                                    "（PREDICTION_MARKETS_END_DATE_GATE）")
                    return rows
                break  # 找到对应管线即停（无论有无市场文件）
        except Exception as e:  # noqa: BLE001 — 加载失败 → 空，绝不阻断配置生成
            logger.debug(f"读取 handoff prediction_markets.json 失败（降级跳过）: {e}")
        return []

    @staticmethod
    def _actor_intelligence_version(actor: Optional[Dict[str, Any]]) -> str:
        intelligence = actor.get("intelligence") if isinstance(actor, dict) else None
        if not isinstance(intelligence, dict):
            return ""
        return str(intelligence.get("schema_version") or "").strip()

    @classmethod
    def _is_canonical_actor(cls, actor: Optional[Dict[str, Any]]) -> bool:
        return cls._actor_intelligence_version(actor) == ACTOR_INTELLIGENCE_VERSION

    @classmethod
    def _dossier_uses_canonical_intelligence(
        cls, actors: Optional[Dict[str, Any]]
    ) -> bool:
        if not isinstance(actors, dict):
            return False
        contract = actors.get("actor_intelligence_contract")
        if (
            isinstance(contract, dict)
            and str(contract.get("schema_version") or "").strip()
            == ACTOR_INTELLIGENCE_VERSION
        ):
            return True
        return any(cls._is_canonical_actor(row) for row in extract_actor_rows(actors))

    @classmethod
    def _validated_canonical_context_pack(
        cls,
        actor: Dict[str, Any],
        actor_context_packs: Optional[Dict[str, Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """Return the exact source-bound actor-context/v1 pack or fail closed.

        A canonical actor may not fall back to the legacy flat role/stance/
        influence/memory/incentive fields.  The pack is therefore a required
        authority boundary for every selected v1 actor, not an optional prompt
        enhancement.  These local checks protect direct callers as well as the
        normal PREPARE path, which has already validated the root manifest.
        """
        if not cls._is_canonical_actor(actor):
            raise ValueError("canonical actor-context requested for a legacy actor")
        actor_id = actor_id_for(actor)
        pack = (
            actor_context_packs.get(actor_id)
            if isinstance(actor_context_packs, dict) else None
        )
        if not isinstance(pack, dict):
            raise ValueError(
                f"canonical actor {actor_id} requires a sealed actor-context/v1 pack"
            )
        if str(pack.get("schema_version") or "") != ACTOR_CONTEXT_VERSION:
            raise ValueError(
                f"canonical actor {actor_id} has an unsupported actor-context schema"
            )
        if str(pack.get("actor_id") or "") != actor_id:
            raise ValueError(f"canonical actor-context identity mismatch for {actor_id}")
        if normalize_name(str(pack.get("actor_name") or "")) != normalize_name(
            str(actor.get("name") or "")
        ):
            raise ValueError(f"canonical actor-context name mismatch for {actor_id}")

        actor_intelligence = actor.get("intelligence")
        pack_intelligence = pack.get("actor_intelligence")
        if not isinstance(actor_intelligence, dict) or not isinstance(pack_intelligence, dict):
            raise ValueError(f"canonical actor-context intelligence missing for {actor_id}")
        actor_intelligence_sha = canonical_json_sha256(actor_intelligence)
        if canonical_json_sha256(pack_intelligence) != actor_intelligence_sha:
            raise ValueError(f"canonical actor-context intelligence mismatch for {actor_id}")

        source = pack.get("source")
        if not isinstance(source, dict):
            raise ValueError(f"canonical actor-context provenance missing for {actor_id}")
        if (
            str(source.get("actor_intelligence_contract_version") or "")
            != ACTOR_INTELLIGENCE_VERSION
            or str(source.get("actor_intelligence_sha256") or "")
            != actor_intelligence_sha
        ):
            raise ValueError(f"canonical actor-context provenance mismatch for {actor_id}")
        return pack

    _PUBLIC_ACTOR_CONTEXT_VISIBILITIES = {
        "public", "public_record", "publicly_known", "open_source",
    }
    _ACTOR_LOCAL_CONTEXT_VISIBILITIES = {
        "actor_known", "known_to_actor", "actor_internal",
        "internal_to_actor", "private_actor_knowledge",
    }
    _NON_BEHAVIORAL_EVIDENCE_TYPES = {
        "analyst_inference", "contested", "unknown",
    }

    @classmethod
    def _validate_actor_context_dossier_binding(
        cls,
        pack: Dict[str, Any],
        actors: Optional[Dict[str, Any]],
    ) -> None:
        """Require cross-actor runtime rows to be sealed to this dossier."""
        if not isinstance(actors, dict):
            raise ValueError("canonical actor-context dossier binding is missing")
        source = pack.get("source")
        expected = canonical_json_sha256(actors)
        if (
            not isinstance(source, dict)
            or str(source.get("actors_sha256") or "") != expected
        ):
            raise ValueError("canonical actor-context dossier fingerprint mismatch")

    @classmethod
    def _canonical_context_relationship_rows(
        cls,
        actors: Optional[Dict[str, Any]],
        actor_context_packs: Optional[Dict[str, Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """Return sealed relationship evidence safe for runtime behavior.

        Only source-bound, explicitly public verified facts and public
        actor-stated claims may shape runtime behavior. Modeler-only,
        uncertain, and private/actor-local rows remain audit data and are not
        executable simulation authority.
        """
        if not isinstance(actors, dict) or not isinstance(actor_context_packs, dict):
            return []
        raw_rows = actors.get("relationships")
        raw_rows = raw_rows if isinstance(raw_rows, list) else []
        raw_fingerprints = {
            canonical_json_sha256(row)
            for row in raw_rows if isinstance(row, dict)
        }
        rows: List[Dict[str, Any]] = []
        seen = set()
        for actor in extract_actor_rows(actors):
            if not cls._is_canonical_actor(actor):
                continue
            actor_id = actor_id_for(actor)
            if actor_id not in actor_context_packs:
                continue
            pack = cls._validated_canonical_context_pack(
                actor, actor_context_packs
            )
            pack_rows = pack.get("relationships")
            if not isinstance(pack_rows, list) or not pack_rows:
                continue
            cls._validate_actor_context_dossier_binding(pack, actors)
            for raw in pack_rows:
                if not isinstance(raw, dict):
                    continue
                if canonical_json_sha256(raw) not in raw_fingerprints:
                    raise ValueError(
                        f"canonical actor-context relationship is not dossier-bound for {actor_id}"
                    )
                safe = cls._safe_actor_context_relationship(raw)
                if not safe.get("source") or not safe.get("target"):
                    continue
                if not is_hard_public_relationship(safe):
                    continue
                safe["_runtime_scope"] = "public"
                key = (
                    normalize_name(str(safe.get("source") or "")),
                    normalize_name(str(safe.get("target") or "")),
                    str(safe.get("type") or "").upper(),
                    str(safe.get("evidence_type") or ""),
                    str(safe.get("visibility") or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                rows.append(safe)
        return rows

    @staticmethod
    def _canonical_relationship_follow_pairs(
        rows: List[Dict[str, Any]],
        agent_id_by_name: Dict[str, int],
    ) -> "set":
        """Compile sealed relationship rows without legacy flat influence."""
        pairs: set = set()
        for row in rows:
            source_name = normalize_name(str(row.get("source") or ""))
            target_name = normalize_name(str(row.get("target") or ""))
            source_id = agent_id_by_name.get(source_name)
            target_id = agent_id_by_name.get(target_name)
            if source_id is None or target_id is None or source_id == target_id:
                continue
            relation_type = str(row.get("type") or "").strip().upper()
            candidates = []
            if relation_type in {
                "ALLY_OF", "PARTNERS_WITH", "OPPOSES", "COMPETES_WITH",
                "SANCTIONS", "LITIGATES_AGAINST", "CRITICIZES",
            }:
                candidates = [(source_id, target_id), (target_id, source_id)]
            elif relation_type in {"DEPENDS_ON", "REGULATES", "CUSTOMER_OF"}:
                candidates = [(source_id, target_id)]
            elif relation_type in {
                "INFLUENCES", "SUPPLIES", "FUNDS", "INVESTS_IN", "BACKS",
                "OWNS", "SUPPORTS", "ENDORSES",
            }:
                candidates = [(target_id, source_id)]
            context_actor_id = agent_id_by_name.get(normalize_name(
                str(row.get("_context_actor_name") or "")
            ))
            for follower, followee in candidates:
                if (
                    row.get("_runtime_scope") == "actor_local"
                    and follower != context_actor_id
                ):
                    continue
                pairs.add((follower, followee))
        return pairs

    @classmethod
    def _canonical_context_event_rows(
        cls,
        actors: Optional[Dict[str, Any]],
        actor_context_packs: Optional[Dict[str, Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """Return globally schedulable public events from sealed v1 packs."""
        if not isinstance(actors, dict) or not isinstance(actor_context_packs, dict):
            return []
        raw_events = actors.get("key_events")
        raw_events = raw_events if isinstance(raw_events, list) else []
        raw_fingerprints = {
            canonical_json_sha256(row)
            for row in raw_events if isinstance(row, dict)
        }
        events: List[Dict[str, Any]] = []
        seen = set()
        for actor in extract_actor_rows(actors):
            if not cls._is_canonical_actor(actor):
                continue
            actor_id = actor_id_for(actor)
            if actor_id not in actor_context_packs:
                continue
            pack = cls._validated_canonical_context_pack(
                actor, actor_context_packs
            )
            pack_events = pack.get("events")
            if not isinstance(pack_events, list) or not pack_events:
                continue
            cls._validate_actor_context_dossier_binding(pack, actors)
            for raw in pack_events:
                if not isinstance(raw, dict):
                    continue
                if canonical_json_sha256(raw) not in raw_fingerprints:
                    raise ValueError(
                        f"canonical actor-context event is not dossier-bound for {actor_id}"
                    )
                refs = cls._safe_actor_context_list(
                    raw.get("source_refs"), limit=8, max_chars=180
                )
                event = cls._safe_actor_context_scalar(raw.get("event"), 600)
                date = cls._safe_actor_context_scalar(raw.get("date"), 40)
                visibility = str(
                    raw.get("visibility") or ""
                ).strip().casefold().replace("-", "_").replace(" ", "_")
                evidence_type = str(
                    raw.get("evidence_type") or ""
                ).strip().casefold().replace("-", "_").replace(" ", "_")
                if (
                    not event or not date or not refs
                    or visibility not in cls._PUBLIC_ACTOR_CONTEXT_VISIBILITIES
                    or evidence_type in cls._NON_BEHAVIORAL_EVIDENCE_TYPES
                ):
                    continue
                key = (str(date), str(event).casefold())
                if key in seen:
                    continue
                seen.add(key)
                events.append({
                    "date": date,
                    "event": event,
                    "source_refs": refs,
                    "visibility": visibility,
                })
        return events

    @classmethod
    def _canonical_public_world_rows(
        cls,
        actors: Optional[Dict[str, Any]],
        actor_context_packs: Optional[Dict[str, Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """Select only explicitly public, source-bound canonical evidence.

        Analyst inference is modeler-only even when malformed input labels it
        public.  Contested/unknown rows may be shared only when their visibility
        is explicitly public, and retain their uncertainty label in the brief.
        A missing pack is not interpreted through raw dossier fields.
        """
        if not isinstance(actor_context_packs, dict):
            return []
        rows: List[Dict[str, Any]] = []
        seen_claims = set()
        for actor in extract_actor_rows(actors):
            if not cls._is_canonical_actor(actor):
                continue
            actor_id = actor_id_for(actor)
            if actor_id not in actor_context_packs:
                continue
            pack = cls._validated_canonical_context_pack(actor, actor_context_packs)
            cls._validate_actor_context_dossier_binding(pack, actors)
            intelligence = pack.get("actor_intelligence") or {}
            dimensions = intelligence.get("dimensions") or {}
            if not isinstance(dimensions, dict):
                continue
            for dimension in INTELLIGENCE_DIMENSIONS:
                claims = dimensions.get(dimension)
                if not isinstance(claims, list):
                    continue
                for raw in claims:
                    if not isinstance(raw, dict):
                        continue
                    claim = sanitize_untrusted_dossier_text(raw.get("claim"), 520)
                    refs = cls._safe_actor_context_list(
                        raw.get("source_refs"), limit=6, max_chars=120
                    )
                    if not claim or not refs:
                        continue
                    evidence_type = str(
                        raw.get("evidence_type") or "unknown"
                    ).strip().casefold().replace("-", "_").replace(" ", "_")
                    if evidence_type == "analyst_inference":
                        continue
                    qualifiers = raw.get("qualifiers")
                    qualifiers = qualifiers if isinstance(qualifiers, dict) else {}
                    visibility = str(
                        raw.get("visibility") or qualifiers.get("visibility") or ""
                    ).strip().casefold().replace("-", "_").replace(" ", "_")
                    if visibility not in cls._PUBLIC_ACTOR_CONTEXT_VISIBILITIES:
                        continue
                    dedupe_key = claim.casefold()
                    if dedupe_key in seen_claims:
                        continue
                    seen_claims.add(dedupe_key)
                    rows.append({
                        "actor_name": sanitize_untrusted_dossier_text(
                            pack.get("actor_name"), 180
                        ),
                        "dimension": dimension,
                        "claim": claim,
                        "evidence_type": evidence_type,
                        "as_of_date": sanitize_untrusted_dossier_text(
                            raw.get("as_of_date"), 40
                        ),
                        "source_refs": refs,
                    })
        return rows

    @classmethod
    def _build_canonical_public_world_brief(
        cls,
        simulation_requirement: str,
        actors: Optional[Dict[str, Any]],
        actor_context_packs: Optional[Dict[str, Dict[str, Any]]],
        max_chars: int,
        english: bool = False,
    ) -> str:
        public_rows = cls._canonical_public_world_rows(actors, actor_context_packs)
        if not public_rows:
            return ""
        parts: List[str] = []
        question = " ".join(str(simulation_requirement or "").split()).strip()
        if question:
            question = sanitize_untrusted_dossier_text(
                question, cls.WORLD_BRIEF_QUESTION_CHARS
            )
            parts.append(
                ("## Forecast question (what this world is debating)\n" if english
                 else "## 核心预测问题（这个世界正在争论什么）\n") + question
            )
        header = "## Public, source-bound shared facts" if english else "## 公开且来源绑定的共同事实"
        evidence_lines: List[str] = []
        for row in public_rows:
            uncertainty = ""
            evidence_type = str(row.get("evidence_type") or "unknown")
            if evidence_type in {"contested", "unknown"}:
                uncertainty = f" [{evidence_type}; not established fact]"
            refs = ",".join(str(ref) for ref in row.get("source_refs") or [])
            as_of = f"; as-of={row['as_of_date']}" if row.get("as_of_date") else ""
            line = (
                f"- {row.get('actor_name') or 'Actor'} / {row.get('dimension')}: "
                f"{row.get('claim')}{uncertainty} [sources={refs}{as_of}]"
            )
            candidate_lines = [*evidence_lines, line]
            candidate_parts = [*parts, header + "\n" + "\n".join(candidate_lines)]
            if len("\n\n".join(candidate_parts)) > max_chars:
                continue
            evidence_lines.append(line)
        if not evidence_lines:
            return ""
        parts.append(header + "\n" + "\n".join(evidence_lines))
        return "\n\n".join(parts).strip()

    @staticmethod
    def _resolve_output_language(research_language: Optional[str], simulation_requirement: str) -> str:
        """模拟内容语言：显式 English/Chinese 优先；auto/未传 → 预测问题本身的语言（与研究
        阶段 CONF-1 一致：英文问题 → 英文报告）。一个汉字约抵三个拉丁字母。判不出 → ""。"""
        raw = str(research_language or "").strip()
        low = raw.lower()
        if low.startswith("en"):
            return "English"
        if low.startswith(("zh", "chinese")) or "中文" in raw:
            return "Chinese"
        text = str(simulation_requirement or "")
        cjk = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))
        latin = len(re.findall(r"[A-Za-z]", text))
        if not cjk and not latin:
            return ""
        return "Chinese" if cjk * 3 >= latin else "English"

    def _english_output(self) -> bool:
        """本次配置的 agent 可见内容是否用英文（未判定语言 → False，沿用历史中文标题）。"""
        return getattr(self, "_output_language", "") == "English"

    def _build_market_pricing_block(
        self, prediction_markets: Optional[List[Dict[str, Any]]]
    ) -> str:
        """ITEM 11: top-N 相关市场的紧凑「市场定价」块（question + 隐含 P），进世界底稿。

        市场已在研究阶段做过相关性门控（relevance_score/volume 排序）；此处防御性再按
        (relevance_score, volume) 降序排一次，取头部 N 条渲染为一行一市场。无有效
        question/implied_yes_prob → 跳过该行；全部无效或空列表 → ""（不注入）。
        """
        rows = [m for m in (prediction_markets or []) if isinstance(m, dict)]
        if not rows:
            return ""

        def _num(v: Any) -> float:
            return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else -1.0

        rows = sorted(
            rows,
            key=lambda m: (_num(m.get("relevance_score")), _num(m.get("volume"))),
            reverse=True,
        )
        lines: List[str] = []
        for m in rows:
            q = str(m.get("question") or "").strip()
            prob = m.get("implied_yes_prob")
            if not q or not isinstance(prob, (int, float)) or isinstance(prob, bool):
                continue
            if self._english_output():
                lines.append(f'- "{q[:160]}": {float(prob) * 100:.0f}%')
            else:
                lines.append(f"- 「{q[:160]}」：{float(prob) * 100:.0f}%")
            if len(lines) >= self.MARKET_PRIORS_TOP_N:
                break
        if not lines:
            return ""
        header = (
            "## Market pricing (prediction-market implied probabilities: citable, debatable "
            "calibration priors, not ground truth)"
            if self._english_output()
            else "## 市场定价（预测市场隐含概率——可引用/可争论的校准先验，非真值）"
        )
        return header + "\n" + "\n".join(lines)

    def _build_world_brief(
        self,
        simulation_requirement: str,
        actors: Optional[Dict[str, Any]],
        hot_topics: Optional[List[str]],
        prediction_markets: Optional[List[Dict[str, Any]]] = None,
        actor_context_packs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> str:
        """NEXTSTEPS SIM_WORLD_BRIEF: 拼装全体 Agent 共享的紧凑世界底稿（≤1400 字）。

        组成（全部确定性拼接，不调 LLM）：
        (a) 预测问题（simulation_requirement 前 400 字——让每个 Agent 知道这个世界
            正在争论什么问题）；
        (b) 局势简报（复用 utils.actors.situation_brief_block：当前态势/来龙去脉/
            张力动态/争议断层/潜在触发）；
        (c) 热点话题清单；
        (d) ITEM 11 SIM_MARKET_PRIORS: 市场定价块（top 5 相关市场 question + 隐含 P，
            让全体 Agent 知道 priced beliefs 并据此争论）——仅当传入非空市场且开关开。

        actor-intelligence/v1 is fail-closed: raw situation_brief/hot_topics and
        unbound market rows are not shared with every actor.  Its brief is built
        only from explicitly-public, source-bound rows in validated
        actor-context/v1 packs; actor-private and modeler-only evidence cannot
        become common knowledge.  Legacy/unversioned dossiers retain the exact
        historical assembly below.

        可降级：任一段缺失 → 简报变短；全部缺失或 SIM_WORLD_BRIEF=false → 空串
        （调用方省略配置字段，运行脚本整体跳过注入）。
        """
        raw_flag = getattr(Config, "SIM_WORLD_BRIEF", True)
        if str(raw_flag).strip().lower() in ("false", "0", "no", "off"):
            return ""

        max_chars = self._world_brief_max_chars()
        if self._dossier_uses_canonical_intelligence(actors):
            return self._build_canonical_public_world_brief(
                simulation_requirement,
                actors,
                actor_context_packs,
                max_chars,
                english=self._english_output(),
            )

        english = self._english_output()
        parts: List[str] = []
        question = " ".join(str(simulation_requirement or "").split()).strip()
        if question:
            parts.append(("## Forecast question (what this world is debating)\n" if english
                          else "## 核心预测问题（这个世界正在争论什么）\n")
                         + question[:self.WORLD_BRIEF_QUESTION_CHARS])
        try:
            brief_block = situation_brief_block(actors, english=english)
        except Exception:  # noqa: BLE001 — 局势简报渲染失败绝不阻断配置生成
            brief_block = ""
        if brief_block:
            parts.append(brief_block)
        topics = [str(t).strip() for t in (hot_topics or []) if str(t).strip()]
        if topics:
            parts.append(("## Hot topics\n" + "; ".join(topics[:8])) if english
                         else ("## 热点话题\n" + "、".join(topics[:8])))

        # ITEM 11: 市场定价块（top 5 相关市场）——仅当开关开且传入非空市场；否则整体跳过，
        # 与今日逐字节一致（degrade-safe）。
        if self._market_priors_enabled():
            market_block = self._build_market_pricing_block(prediction_markets)
            if market_block:
                parts.append(market_block)

        # RQ-7 / I-6-4：世界简报上限从固定 1400 升级为按提供方窗口预算化——大窗口模型
        # （MiniMax 512K / DeepSeek 1M）抬到 SIM_WORLD_BRIEF_MAX_CHARS（默认 3000）以承载更完整的
        # 世界背景，小窗口/未知提供方守住 WORLD_BRIEF_MAX_CHARS（1400 floor）。ADAPTIVE_CONTEXT=false
        # 或任何异常 → 1400（degrade-safe，逐字节与历史一致）。
        return "\n\n".join(parts).strip()[:max_chars]

    def _world_brief_max_chars(self) -> int:
        """RQ-7：世界简报的预算化字符上限，钳在 [WORLD_BRIEF_MAX_CHARS(=1400 floor),
        SIM_WORLD_BRIEF_MAX_CHARS(=3000 ceiling)]。关闭 ADAPTIVE_CONTEXT/异常 → floor。"""
        floor = int(self.WORLD_BRIEF_MAX_CHARS)
        if not getattr(Config, "ADAPTIVE_CONTEXT", False):
            return floor
        ceiling = int(getattr(Config, "SIM_WORLD_BRIEF_MAX_CHARS", 3000))
        try:
            from ..utils import token_budget as _tb
            provider = getattr(self, "provider", None) or Config.LLM_PROVIDER
            window = Config.context_window_for(provider)
            budget = _tb.slice_budget_chars(
                window_tokens=window,
                reserved_tokens=getattr(Config, "RESERVED_COMPLETION_TOKENS", 8192),
                floor_chars=floor,
                share=0.05,          # 世界简报是全体 Agent 共享的紧凑底稿，仅占窗口极小份额
                num_items=1,
            )
            return _tb.clamp_chars(budget, floor, ceiling)
        except Exception:  # noqa: BLE001 — 预算化仅为增强，任何失败退回固定 floor
            return floor

    def _build_context(
        self,
        simulation_requirement: str,
        document_text: str,
        entities: List[EntityNode],
        actors: Optional[Dict[str, Any]] = None,
        actor_context_packs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> str:
        """构建LLM上下文，截断到最大长度"""

        # Every interpolated value below is research-derived. Sanitize values
        # before composition and wrap each logical block so the LLM receives
        # evidence data, never executable instructions.
        requirement_block = delimit_untrusted_research_text(
            "simulation requirement",
            simulation_requirement,
            max_chars=4_000,
        )

        canonical_v1 = self._dossier_uses_canonical_intelligence(actors)
        if canonical_v1:
            # Canonical v1 is an authority switch. Graph summaries and the
            # whole report are retrieval/indexing artifacts, not executable
            # behavior evidence. The shared config context therefore contains
            # only the caller's forecast question plus explicitly-public,
            # source-bound rows from validated actor-context/v1 packs. Missing
            # public evidence stays missing; it never reopens the raw report.
            context_parts = [f"## 模拟需求\n{requirement_block}"]
            public_context = self._build_canonical_public_world_brief(
                "", actors, actor_context_packs, 10_000
            )
            if public_context:
                context_parts.append("\n" + public_context)
            return "\n".join(context_parts)

        # Exact unversioned compatibility path. Keep the historical graph and
        # whole-document inputs byte-compatible for dossiers that have not
        # opted into actor-intelligence/v1.
        entity_summary = self._summarize_entities(entities)
        entity_block = delimit_untrusted_research_text(
            "graph entity summary",
            entity_summary,
            max_chars=10_000,
        )
        context_parts = [
            f"## 模拟需求\n{requirement_block}",
            f"\n## 实体信息 ({len(entities)}个)\n{entity_block}",
        ]
        brief_block = situation_brief_block(actors)
        if brief_block:
            safe_brief = delimit_untrusted_research_text(
                "situation brief",
                brief_block,
                max_chars=6_000,
            )
            context_parts.insert(1, f"\n## 局势简报\n{safe_brief}")

        digest = actors_digest(actors)
        if digest:
            safe_digest = delimit_untrusted_research_text(
                "actor dossier digest",
                digest,
                max_chars=10_000,
            )
            context_parts.append(
                "\n## 深度研究档案（调研实证，生成配置时优先采信）\n"
                + safe_digest
            )

        fi_block = forecast_inputs_block(actors)
        if fi_block:
            safe_forecast_inputs = delimit_untrusted_research_text(
                "forecast inputs",
                fi_block,
                max_chars=8_000,
            )
            context_parts.append(
                "\n## 预测输入（分析锚点：基率/驱动/指标/情景，模拟应据此推理）\n"
                + safe_forecast_inputs
            )

        current_length = sum(len(p) for p in context_parts)
        remaining_length = self.MAX_CONTEXT_LENGTH - current_length - 500  # 留500字符余量

        if remaining_length > 0 and document_text:
            raw_document = str(document_text)
            doc_text = sanitize_untrusted_research_text(
                raw_document,
                max_chars=remaining_length,
            )
            if len(raw_document) > remaining_length:
                doc_text += "\n...(文档已截断)"
            document_block = delimit_untrusted_research_text(
                "research report or source document",
                doc_text,
                max_chars=remaining_length + 40,
            )
            context_parts.append(f"\n## 原始文档内容\n{document_block}")

        return "\n".join(context_parts)
    
    def _summarize_entities(self, entities: List[EntityNode]) -> str:
        """生成实体摘要"""
        lines = []
        
        # 按类型分组
        by_type: Dict[str, List[EntityNode]] = {}
        for e in entities:
            t = e.get_entity_type() or "Unknown"
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(e)
        
        for entity_type, type_entities in by_type.items():
            safe_type = sanitize_untrusted_research_text(
                entity_type,
                max_chars=160,
            )
            lines.append(f"\n### {safe_type} ({len(type_entities)}个)")
            # 使用配置的显示数量和摘要长度
            display_count = self.ENTITIES_PER_TYPE_DISPLAY
            summary_len = self.ENTITY_SUMMARY_LENGTH
            for e in type_entities[:display_count]:
                raw_summary = str(e.summary or "")
                summary_preview = sanitize_untrusted_research_text(
                    raw_summary,
                    max_chars=summary_len,
                )
                if len(raw_summary) > summary_len:
                    summary_preview += "..."
                safe_name = sanitize_untrusted_research_text(
                    e.name,
                    max_chars=180,
                )
                lines.append(f"- {safe_name}: {summary_preview}")
            if len(type_entities) > display_count:
                lines.append(f"  ... 还有 {len(type_entities) - display_count} 个")
        
        return "\n".join(lines)
    
    def _call_llm_with_retry(self, prompt: str, system_prompt: str) -> Dict[str, Any]:
        """带重试的LLM调用，包含JSON修复逻辑。

        统一经由 LLMClient（claude-cli / codex-cli / openai）。瞬时失败的
        重试由 LLMClient 内部处理；此处的循环负责 JSON 解析/修复重试。
        """
        max_attempts = 3
        last_error = None

        for attempt in range(max_attempts):
            try:
                content = self.llm.chat(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.7 - (attempt * 0.1),  # 每次重试降低温度
                )

                # 尝试解析JSON
                try:
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON解析失败 (attempt {attempt+1}): {str(e)[:80]}")

                    # 尝试修复JSON（含截断闭合）
                    fixed = self._try_fix_config_json(content)
                    if fixed:
                        return fixed

                    last_error = e

            except Exception as e:
                logger.warning(f"LLM调用失败 (attempt {attempt+1}): {str(e)[:80]}")
                last_error = e
                import time
                time.sleep(2 * (attempt + 1))

        raise last_error or Exception("LLM调用失败")
    
    def _fix_truncated_json(self, content: str) -> str:
        """修复被截断的JSON"""
        content = content.strip()
        
        # 计算未闭合的括号
        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')
        
        # 检查是否有未闭合的字符串
        if content and content[-1] not in '",}]':
            content += '"'
        
        # 闭合括号
        content += ']' * open_brackets
        content += '}' * open_braces
        
        return content
    
    def _try_fix_config_json(self, content: str) -> Optional[Dict[str, Any]]:
        """尝试修复配置JSON"""
        import re
        
        # 修复被截断的情况
        content = self._fix_truncated_json(content)
        
        # 提取JSON部分
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()
            
            # 移除字符串中的换行符
            def fix_string(match):
                s = match.group(0)
                s = s.replace('\n', ' ').replace('\r', ' ')
                s = re.sub(r'\s+', ' ', s)
                return s
            
            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', fix_string, json_str)
            
            try:
                return json.loads(json_str)
            except:
                # 尝试移除所有控制字符
                json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', json_str)
                json_str = re.sub(r'\s+', ' ', json_str)
                try:
                    return json.loads(json_str)
                except:
                    pass
        
        return None
    
    def _generate_time_config(self, context: str, num_entities: int) -> Dict[str, Any]:
        """生成时间配置"""
        # 使用配置的上下文截断长度
        context_truncated = context[:self.TIME_CONFIG_CONTEXT_LENGTH]

        # 计算最大允许值（90%的agent数）
        max_agents_allowed = max(1, int(num_entities * 0.9))

        # 作息口径由活动画像决定；china_social 分支与历史措辞逐字节一致
        profile = self._activity_profile()
        time_prompt_principles = profile["time_prompt_principles"]

        prompt = f"""基于以下模拟需求，生成时间模拟配置。

{context_truncated}

## 任务
请生成时间配置JSON。

### 基本原则（仅供参考，需根据具体事件和参与群体灵活调整）：
{time_prompt_principles}
- **重要**：以下示例值仅供参考，你需要根据事件性质、参与群体特点来调整具体时段
  - 例如：学生群体高峰可能是21-23点；媒体全天活跃；官方机构只在工作时间
  - 例如：突发热点可能导致深夜也有讨论，off_peak_hours 可适当缩短

### 返回JSON格式（不要markdown）

示例：
{{
    "total_simulation_hours": 72,
    "minutes_per_round": 60,
    "agents_per_hour_min": 5,
    "agents_per_hour_max": 50,
    "peak_hours": {json.dumps(profile["peak_hours"])},
    "off_peak_hours": {json.dumps(profile["off_peak_hours"])},
    "morning_hours": {json.dumps(profile["morning_hours"])},
    "work_hours": {json.dumps(profile["work_hours"])},
    "reasoning": "针对该事件的时间配置说明"
}}

字段说明：
- total_simulation_hours (int): 模拟总时长，24-168小时，突发事件短、持续话题长
- minutes_per_round (int): 每轮时长，30-120分钟，建议60分钟
- agents_per_hour_min (int): 每小时最少激活Agent数（取值范围: 1-{max_agents_allowed}）
- agents_per_hour_max (int): 每小时最多激活Agent数（取值范围: 1-{max_agents_allowed}）
- peak_hours (int数组): 高峰时段，根据事件参与群体调整
- off_peak_hours (int数组): 低谷时段，通常深夜凌晨
- morning_hours (int数组): 早间时段
- work_hours (int数组): 工作时段
- reasoning (string): 简要说明为什么这样配置"""

        system_prompt = profile["time_system_prompt"]

        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"时间配置LLM生成失败: {e}, 使用默认配置")
            return self._get_default_time_config(num_entities)
    
    def _get_default_time_config(self, num_entities: int) -> Dict[str, Any]:
        """获取默认时间配置（中国人作息）"""
        # 默认时段口径随活动画像切换；china_social 各数值/文案与历史逐字节一致
        profile = self._activity_profile()
        return {
            "total_simulation_hours": 72,
            "minutes_per_round": 60,  # 每轮1小时，加快时间流速
            "agents_per_hour_min": max(1, num_entities // 15),
            "agents_per_hour_max": max(5, num_entities // 5),
            "peak_hours": list(profile["peak_hours"]),
            "off_peak_hours": list(profile["off_peak_hours"]),
            "morning_hours": list(profile["morning_hours"]),
            "work_hours": list(profile["work_hours"]),
            "reasoning": profile["default_time_reasoning"]
        }
    
    @staticmethod
    def _coerce_int(value: Any, default: int) -> int:
        """PREP-9: LLM 数值字段防御性转换——int(float(x))；0/负数/字符串等失败回默认值。"""
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    def _parse_time_config(self, result: Dict[str, Any], num_entities: int) -> TimeSimulationConfig:
        """解析时间配置结果，并验证agents_per_hour值不超过总agent数"""
        # 时段缺省值随活动画像切换；china_social 与历史默认逐字节一致
        profile = self._activity_profile()
        # PREP-9: 时长/轮长不做类型与区间校验会在运行脚本的整数除法里迟发爆炸
        # （0 → ZeroDivisionError，"60分钟" → TypeError），或产出病态的 336 轮计划。
        # 统一 coerce + 夹取到提示词承诺的区间（24-168h / 30-120min）；合规输出不变。
        total_hours = self._coerce_int(result.get("total_simulation_hours", 72), 72)
        clamped_hours = min(168, max(24, total_hours))
        if clamped_hours != total_hours:
            logger.warning(f"total_simulation_hours={total_hours!r} 越界，已夹取到 {clamped_hours}")
        minutes_per_round = self._coerce_int(result.get("minutes_per_round", 60), 60)
        clamped_mpr = min(120, max(30, minutes_per_round))
        if clamped_mpr != minutes_per_round:
            logger.warning(f"minutes_per_round={minutes_per_round!r} 越界，已夹取到 {clamped_mpr}")
        # 获取原始值（同样先 coerce，避免非数值直接进入下方的大小比较抛 TypeError）
        agents_per_hour_min = self._coerce_int(
            result.get("agents_per_hour_min", max(1, num_entities // 15)),
            max(1, num_entities // 15),
        )
        agents_per_hour_max = self._coerce_int(
            result.get("agents_per_hour_max", max(5, num_entities // 5)),
            max(5, num_entities // 5),
        )

        # 验证并修正：确保不超过总agent数
        if agents_per_hour_min > num_entities:
            logger.warning(f"agents_per_hour_min ({agents_per_hour_min}) 超过总Agent数 ({num_entities})，已修正")
            agents_per_hour_min = max(1, num_entities // 10)
        
        if agents_per_hour_max > num_entities:
            logger.warning(f"agents_per_hour_max ({agents_per_hour_max}) 超过总Agent数 ({num_entities})，已修正")
            agents_per_hour_max = max(agents_per_hour_min + 1, num_entities // 2)
        
        # 确保 min < max
        if agents_per_hour_min >= agents_per_hour_max:
            agents_per_hour_min = max(1, agents_per_hour_max // 2)
            logger.warning(f"agents_per_hour_min >= max，已修正为 {agents_per_hour_min}")
        
        return TimeSimulationConfig(
            total_simulation_hours=clamped_hours,
            minutes_per_round=clamped_mpr,  # 默认每轮1小时
            agents_per_hour_min=agents_per_hour_min,
            agents_per_hour_max=agents_per_hour_max,
            peak_hours=result.get("peak_hours", list(profile["peak_hours"])),
            off_peak_hours=result.get("off_peak_hours", list(profile["off_peak_hours"])),
            off_peak_activity_multiplier=0.05,  # 凌晨几乎无人
            morning_hours=result.get("morning_hours", list(profile["morning_hours"])),
            morning_activity_multiplier=0.4,
            work_hours=result.get("work_hours", list(profile["work_hours"])),
            work_activity_multiplier=0.7,
            peak_activity_multiplier=1.5
        )
    
    def _generate_event_config(
        self,
        context: str,
        simulation_requirement: str,
        entities: List[EntityNode],
        actors: Optional[Dict[str, Any]] = None,
        actor_context_packs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """生成事件配置"""

        canonical_v1 = self._dossier_uses_canonical_intelligence(actors)
        # Canonical v1 never exposes graph labels or graph names to the event
        # model. Its available poster roster is reconstructed from the exact
        # validated actor-context packs selected for this run. The legacy path
        # retains the historical graph-derived type examples.
        type_examples: Dict[str, List[str]] = {}
        if canonical_v1:
            canonical_names: List[str] = []
            for actor in extract_actor_rows(actors):
                if not self._is_canonical_actor(actor):
                    continue
                actor_id = actor_id_for(actor)
                if not isinstance(actor_context_packs, dict) or actor_id not in actor_context_packs:
                    continue
                pack = self._validated_canonical_context_pack(
                    actor, actor_context_packs
                )
                self._validate_actor_context_dossier_binding(pack, actors)
                name = sanitize_untrusted_dossier_text(pack.get("actor_name"), 180)
                if name and name not in canonical_names:
                    canonical_names.append(name)
            if canonical_names:
                type_examples["Actor"] = canonical_names
        else:
            for e in entities:
                etype = e.get_entity_type() or "Unknown"
                if etype not in type_examples:
                    type_examples[etype] = []
                if len(type_examples[etype]) < 3:
                    type_examples[etype].append(e.name)

        type_info = "\n".join([
            "- "
            + sanitize_untrusted_research_text(t, max_chars=160)
            + ": "
            + ", ".join(
                sanitize_untrusted_research_text(name, max_chars=180)
                for name in examples
            )
            for t, examples in type_examples.items()
        ])
        type_info_block = delimit_untrusted_research_text(
            "available entity types and examples",
            type_info,
            max_chars=6_000,
        )

        # 使用配置的上下文截断长度
        context_truncated = context[:self.EVENT_CONFIG_CONTEXT_LENGTH]

        # Canonical v1 accepts only explicitly-public, source-bound rows here;
        # unversioned dossiers retain the historical raw digest.
        digest = (
            self._build_canonical_public_world_brief(
                "", actors, actor_context_packs, 2_500
            )
            if canonical_v1
            else actors_digest(actors, max_chars=2500)
        )
        research_block = ""
        poster_name_hint = ""
        if digest:
            safe_digest = delimit_untrusted_research_text(
                "event actor dossier digest",
                digest,
                max_chars=2_500,
            )
            research_block = f"\n## 深度研究档案（调研实证）\n{safe_digest}\n"
            if canonical_v1:
                poster_name_hint = (
                    "\n**要求**: 初始帖子只能陈述上述公开且来源绑定的证据；可给出 "
                    "poster_name（角色名），但不得把角色私有知识、分析师推断或旧版平面立场"
                    "改写成公开事实。"
                )
            else:
                poster_name_hint = (
                    "\n**强烈建议**: 初始帖子尽量出自研究档案中的真实角色——为这类帖子额外给出 "
                    "poster_name（角色名，从档案中选），内容必须与该角色的实证立场一致；"
                    "热点话题优先复用档案中的热点议题。"
                )

        # T3.9(2): 让初始帖子覆盖局势简报里的每条「争议断层」(fault_lines)，由最相关的真实角色发声
        fault_lines = []
        if not canonical_v1 and isinstance(actors, dict):
            sb = actors.get("situation_brief")
            if isinstance(sb, dict) and isinstance(sb.get("fault_lines"), list):
                fault_lines = [
                    sanitize_untrusted_research_text(x, max_chars=500)
                    for x in sb["fault_lines"]
                    if str(x).strip()
                ][:6]
        if fault_lines:
            fl_lines = "\n".join(f"  - {x}" for x in fault_lines)
            fault_lines_block = delimit_untrusted_research_text(
                "event fault lines",
                fl_lines,
                max_chars=4_000,
            )
            research_block += (
                "\n## 争议断层（来自局势简报，必须覆盖）\n"
                + fault_lines_block
                + "\n"
            )
            poster_name_hint += (
                "\n**要求**: 为上述每一条「争议断层」至少生成一条初始帖子，由对该议题最相关的研究角色"
                "（poster_name）发声，立场与其实证立场一致，让模拟开局即围绕真实争议点展开。"
            )

        requirement_block = delimit_untrusted_research_text(
            "event simulation requirement",
            simulation_requirement,
            max_chars=8_000,
        )
        prompt = f"""基于以下模拟需求，生成事件配置。

模拟需求:
{requirement_block}

{context_truncated}
{research_block}
## 可用实体类型及示例
{type_info_block}

## 任务
请生成事件配置JSON：
- 提取热点话题关键词
- 描述舆论发展方向
- 设计初始帖子内容，**每个帖子必须指定 poster_type（发布者类型）**

**重要**: poster_type 必须从上面的"可用实体类型"中选择，这样初始帖子才能分配给合适的 Agent 发布。
例如：官方声明应由 Official/University 类型发布，新闻由 MediaOutlet 发布，学生观点由 Student 发布。{poster_name_hint}

返回JSON格式（不要markdown）：
{{
    "hot_topics": ["关键词1", "关键词2", ...],
    "narrative_direction": "<舆论发展方向描述>",
    "initial_posts": [
        {{"content": "帖子内容", "poster_type": "实体类型（必须从可用类型中选择）", "poster_name": "发布者角色名（可选，来自研究档案）"}},
        ...
    ],
    "reasoning": "<简要说明>"
}}"""
        # 输出语言：热点话题、舆论方向与种子帖会原样进入 agent 的世界简报与第 0 轮帖子流，
        # 必须与本次模拟语言一致（此前英文运行也产出中文种子帖，带偏整场模拟的发帖语言）。
        output_language = getattr(self, "_output_language", "")
        if output_language == "English":
            prompt += (
                "\n\n**Output language: English.** Write every text value — hot_topics, "
                "narrative_direction, each initial_posts[].content and reasoning — in English, "
                "even though these instructions are in Chinese. poster_type and poster_name must "
                "still exactly match the available types and names listed above."
            )
        elif output_language == "Chinese":
            prompt += "\n\n**输出语言：中文。** hot_topics、narrative_direction、initial_posts[].content 与 reasoning 一律用中文。"

        system_prompt = "你是舆论分析专家。返回纯JSON格式。注意 poster_type 必须精确匹配可用实体类型。"

        try:
            return self._call_llm_with_retry(prompt, system_prompt)
        except Exception as e:
            logger.warning(f"事件配置LLM生成失败: {e}, 使用默认配置")
            return {
                "hot_topics": [],
                "narrative_direction": "",
                "initial_posts": [],
                "reasoning": "使用默认配置"
            }

    def _parse_event_config(
        self,
        result: Dict[str, Any],
        actors: Optional[Dict[str, Any]] = None,
        actor_context_packs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> EventConfig:
        """解析事件配置结果。LLM 漏掉热点时回填研究档案中的热点议题。"""
        hot_topics = result.get("hot_topics", [])
        canonical_v1 = self._dossier_uses_canonical_intelligence(actors)
        if not hot_topics and not canonical_v1 and isinstance(actors, dict):
            researched = actors.get("hot_topics")
            if isinstance(researched, list):
                hot_topics = [str(t) for t in researched[:12]]
        # QUALITY-OPT C5: remember the run's real forecast topics so agents whose
        # interested_topics the LLM left blank get anchored to the ACTUAL subject (export
        # controls, tariffs, AI compute…) instead of the generic "Public Opinion" — agents
        # then engage with the forecast's themes, not nothing.
        self._run_hot_topics = [str(t).strip() for t in (hot_topics or []) if str(t).strip()][:8]
        initial_posts = result.get("initial_posts", []) or []
        # Seed-content fallback (SIM_SYNTH_SEED_POSTS): the event-config LLM sometimes returns
        # zero initial_posts, which leaves the opening feed empty — agents then have nothing to
        # react to and can only FOLLOW, producing 0 organic posts (the "hollow sim" root cause).
        # Synthesize seed posts from the research dossier so the sim opens on real, contested
        # positions. Narrow (only the empty case) + degrade-safe (any error → empty, unchanged).
        if not initial_posts and getattr(Config, "SIM_SYNTH_SEED_POSTS", True):
            try:
                initial_posts = self._synthesize_initial_posts(
                    actors,
                    hot_topics,
                    actor_context_packs=actor_context_packs,
                )
                if initial_posts:
                    logger.info(
                        "事件配置: LLM 返回 0 初始帖 → 已从研究档案合成 %d 条种子帖"
                        "（避免空 feed 导致模拟空转）", len(initial_posts))
            except Exception as _syn_err:  # noqa: BLE001
                logger.warning("初始帖合成失败（降级为空）: %s", _syn_err)
                initial_posts = []
        return EventConfig(
            initial_posts=initial_posts,
            scheduled_events=[],
            hot_topics=hot_topics,
            narrative_direction=result.get("narrative_direction", "")
        )

    def _synthesize_initial_posts(
        self,
        actors: Optional[Dict[str, Any]],
        hot_topics: Optional[List[str]],
        actor_context_packs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """从研究档案合成种子帖（SIM_SYNTH_SEED_POSTS 兜底）。

        取头部影响力/tier 的角色，各自就一个热点议题陈述其实证立场（stance），作为开局帖子，
        让智能体开局即有真实、对立的内容可评论/转发/引用，避免"空 feed → 只能 FOLLOW → 空转"。
        字段与 LLM 产出一致（content/poster_type/poster_name），交由 _assign_initial_post_agents
        定向到具体 agent。best-effort：数据缺失/异常 → 返回 []（与关闭时逐字节一致）。
        """
        if not isinstance(actors, dict):
            return []
        if self._dossier_uses_canonical_intelligence(actors):
            public_rows = self._canonical_public_world_rows(
                actors, actor_context_packs
            )
            topics = [
                str(topic).strip() for topic in (hot_topics or [])
                if str(topic).strip()
            ]
            max_posts = max(
                1, int(getattr(Config, "SIM_SYNTH_SEED_POSTS_MAX", 10) or 10)
            )
            posts: List[Dict[str, Any]] = []
            used_actors = set()
            for row in public_rows:
                name = str(row.get("actor_name") or "").strip()
                actor_key = normalize_name(name)
                if not name or actor_key in used_actors:
                    continue
                claim = str(row.get("claim") or "").strip()
                if not claim:
                    continue
                evidence_type = str(row.get("evidence_type") or "unknown")
                if evidence_type in {"contested", "unknown"}:
                    claim = f"[{evidence_type}; not established fact] {claim}"
                topic = topics[len(posts) % len(topics)] if topics else ""
                content = f"{topic}: {claim}" if topic else claim
                posts.append({
                    "content": content[:600],
                    "poster_type": "Actor",
                    "poster_name": name,
                })
                used_actors.add(actor_key)
                if len(posts) >= max_posts:
                    break
            return posts

        # Exact unversioned compatibility path.
        rows = actors.get("actors")
        if not isinstance(rows, list):
            return []
        _inf = {"high": 0, "medium": 1, "low": 2}

        def _tier(v: Any) -> int:
            try:
                return int(str(v).strip())
            except (TypeError, ValueError):
                return 9

        cand = [
            r for r in rows
            if isinstance(r, dict)
            and str(r.get("name") or "").strip()
            and str(r.get("stance") or "").strip()
        ]
        # 头部优先：影响力高→低，再按 simulation_tier 升序（tier 1 = 主角）。
        cand.sort(key=lambda r: (
            _inf.get(str(r.get("influence", "")).strip().lower(), 3),
            _tier(r.get("simulation_tier")),
        ))
        topics = [str(t).strip() for t in (hot_topics or []) if str(t).strip()]
        max_posts = max(1, int(getattr(Config, "SIM_SYNTH_SEED_POSTS_MAX", 10) or 10))
        # PREP-11: 种子帖语言随活动画像走（中文画像 → 中文连接词，避免与中文 persona 语言
        # 冲突），并交替使用「立场陈述 / 争议提问」两种模板，让开局 feed 里有可反驳的问题
        # 而非清一色第一人称机构声明。SIM_SEED_POST_VARIANTS=false → 回到单一英文旧模板。
        use_variants = bool(getattr(Config, "SIM_SEED_POST_VARIANTS", True))
        zh = self._activity_profile() is ACTIVITY_PROFILES["china_social"]
        posts: List[Dict[str, Any]] = []
        for i, r in enumerate(cand[:max_posts]):
            name = str(r.get("name")).strip()
            stance = str(r.get("stance")).strip()
            etype = str(r.get("type") or "").strip() or "Organization"
            topic = topics[i % len(topics)] if topics else ""
            if not topic:
                content = stance
            elif not use_variants:
                content = f"On {topic} — our position: {stance}"
            elif i % 2 == 1:
                content = (
                    f"{topic}：我们的立场——{stance} 这一走向下，谁受益、谁受损？" if zh
                    else f"{topic}: our position — {stance} Who gains and who loses if this holds?"
                )
            else:
                content = (
                    f"关于{topic}——我们的立场：{stance}" if zh
                    else f"On {topic} — our position: {stance}"
                )
            posts.append({
                "content": content[:600],
                "poster_type": etype,
                "poster_name": name,
            })
        return posts
    
    def _assign_initial_post_agents(
        self,
        event_config: EventConfig,
        agent_configs: List[AgentActivityConfig]
    ) -> EventConfig:
        """
        为初始帖子分配合适的发布者 Agent
        
        根据每个帖子的 poster_type 匹配最合适的 agent_id
        """
        if not event_config.initial_posts:
            return event_config
        
        # 按实体类型建立 agent 索引
        agents_by_type: Dict[str, List[AgentActivityConfig]] = {}
        for agent in agent_configs:
            etype = agent.entity_type.lower()
            if etype not in agents_by_type:
                agents_by_type[etype] = []
            agents_by_type[etype].append(agent)
        
        # 类型映射表（处理 LLM 可能输出的不同格式）
        type_aliases = {
            "official": ["official", "university", "governmentagency", "government"],
            "university": ["university", "official"],
            "mediaoutlet": ["mediaoutlet", "media"],
            "student": ["student", "person"],
            "professor": ["professor", "expert", "teacher"],
            "alumni": ["alumni", "person"],
            "organization": ["organization", "ngo", "company", "group"],
            "person": ["person", "student", "alumni"],
        }
        
        # 记录每种类型已使用的 agent 索引，避免重复使用同一个 agent
        used_indices: Dict[str, int] = {}

        # 名字索引：研究档案驱动的 poster_name 可以把帖子精确定向到真实角色
        from ..utils.actors import normalize_name
        agents_by_name = {
            normalize_name(agent.entity_name): agent
            for agent in agent_configs
            if agent.entity_name
        }

        updated_posts = []
        for post in event_config.initial_posts:
            poster_type = post.get("poster_type", "").lower()
            content = post.get("content", "")

            # 尝试找到匹配的 agent
            matched_agent_id = None

            # 0. 按名字精确定向（poster_name 来自研究档案的真实角色名）
            poster_name = str(post.get("poster_name", "") or "").strip()
            if poster_name:
                target = normalize_name(poster_name)
                agent = agents_by_name.get(target)
                if agent is None and target:
                    # 双向包含（处理 "OpenAI" vs "OpenAI 公司" 这类差异）
                    for cand_name, cand_agent in agents_by_name.items():
                        if len(cand_name) >= 2 and (cand_name in target or target in cand_name):
                            agent = cand_agent
                            break
                if agent is not None:
                    matched_agent_id = agent.agent_id
                    logger.info(f"初始帖子按角色名定向: '{poster_name}' -> agent_id={matched_agent_id}")

            # 1. 直接匹配
            if matched_agent_id is None and poster_type in agents_by_type:
                agents = agents_by_type[poster_type]
                idx = used_indices.get(poster_type, 0) % len(agents)
                matched_agent_id = agents[idx].agent_id
                used_indices[poster_type] = idx + 1

            # 2. 使用别名匹配
            if matched_agent_id is None:
                for alias_key, aliases in type_aliases.items():
                    if poster_type in aliases or alias_key == poster_type:
                        for alias in aliases:
                            if alias in agents_by_type:
                                agents = agents_by_type[alias]
                                idx = used_indices.get(alias, 0) % len(agents)
                                matched_agent_id = agents[idx].agent_id
                                used_indices[alias] = idx + 1
                                break
                    if matched_agent_id is not None:
                        break

            # 3. 如果仍未找到，使用影响力最高的 agent
            if matched_agent_id is None:
                logger.warning(f"未找到类型 '{poster_type}' 的匹配 Agent，使用影响力最高的 Agent")
                if agent_configs:
                    # 按影响力排序，选择影响力最高的
                    sorted_agents = sorted(agent_configs, key=lambda a: a.influence_weight, reverse=True)
                    matched_agent_id = sorted_agents[0].agent_id
                else:
                    matched_agent_id = 0

            updated_post = {
                "content": content,
                "poster_type": post.get("poster_type", "Unknown"),
                "poster_agent_id": matched_agent_id
            }
            if poster_name:
                updated_post["poster_name"] = poster_name
            updated_posts.append(updated_post)
            
            logger.info(f"初始帖子分配: poster_type='{poster_type}' -> agent_id={matched_agent_id}")
        
        event_config.initial_posts = updated_posts
        return event_config
    
    def _generate_agent_configs_batch(
        self,
        context: str,
        entities: List[EntityNode],
        start_idx: int,
        simulation_requirement: str,
        actors: Optional[Dict[str, Any]] = None,
        actor_context_packs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[AgentActivityConfig]:
        """分批生成Agent配置"""

        # Build the model-facing roster.  actor-intelligence/v1 is an
        # authority switch: graph labels, summaries, and unmatched graph names
        # are indexing artifacts, never behavior evidence.  Every canonical
        # row is therefore either a validated actor-context projection or a
        # deterministic anonymous neutral slot.  The unversioned path remains
        # byte-compatible with the historical graph-derived prompt.
        entity_list = []
        summary_len = self.AGENT_SUMMARY_LENGTH
        matched_actors: Dict[int, Dict[str, Any]] = {}
        context_projections: Dict[int, Dict[str, Any]] = {}
        canonical_agent_ids = set()
        canonical_run = self._dossier_uses_canonical_intelligence(actors)
        canonical_runtime_names: Dict[int, str] = {}
        for i, e in enumerate(entities):
            agent_id = start_idx + i
            actor = match_actor(e.name, actors)
            if canonical_run:
                # A current-v1 batch never leaks unmatched graph metadata into
                # either the LLM or the deterministic rule path.  In a healthy
                # selected cast every row matches a pack; the anonymous label
                # is a fail-neutral compatibility guard for extra graph nodes.
                row = {
                    "agent_id": agent_id,
                    "entity_name": f"Unbound Actor {agent_id}",
                    "entity_type": "Actor",
                }
                canonical_agent_ids.add(agent_id)
                canonical_runtime_names[agent_id] = row["entity_name"]
            else:
                row = {
                    "agent_id": agent_id,
                    "entity_name": sanitize_untrusted_research_text(
                        e.name,
                        max_chars=180,
                    ),
                    "entity_type": sanitize_untrusted_research_text(
                        e.get_entity_type() or "Unknown",
                        max_chars=160,
                    ),
                    "summary": sanitize_untrusted_research_text(
                        e.summary,
                        max_chars=summary_len,
                    ) if e.summary else "",
                }
            if actor is not None and (not canonical_run or self._is_canonical_actor(actor)):
                matched_actors[agent_id] = actor
                canonical_v1 = self._is_canonical_actor(actor)
                if canonical_v1:
                    pack = self._validated_canonical_context_pack(
                        actor, actor_context_packs
                    )
                    canonical_agent_ids.add(agent_id)
                else:
                    pack = None
                    if isinstance(actor_context_packs, dict):
                        pack = actor_context_packs.get(actor_id_for(actor))
                if isinstance(pack, dict):
                    projection = self._actor_context_config_projection(pack)
                    context_projections[agent_id] = projection
                    behavior_projection = self._actor_context_behavior_projection(
                        projection
                    )
                    if canonical_v1:
                        self._validate_actor_context_dossier_binding(pack, actors)
                        runtime_name = str(
                            behavior_projection.get("actor_name")
                            or pack.get("actor_name")
                            or ""
                        ).strip()
                        if not runtime_name:
                            raise ValueError(
                                f"canonical actor {actor_id_for(actor)} has no safe runtime name"
                            )
                        canonical_runtime_names[agent_id] = runtime_name
                        row["entity_name"] = runtime_name
                        row["entity_type"] = "Actor"
                if canonical_v1 and not context_projections.get(agent_id):
                    raise ValueError(
                        f"canonical actor {actor_id_for(actor)} has no safe config projection"
                    )
                if not canonical_v1:
                    # Exact legacy compatibility path.  Canonical v1 actors may
                    # never reopen these unversioned behavior fields.
                    researched = {
                        "role": sanitize_untrusted_research_text(
                            actor.get("role"), max_chars=500
                        ),
                        "stance": sanitize_untrusted_research_text(
                            actor.get("stance"), max_chars=500
                        ),
                        "influence": sanitize_untrusted_research_text(
                            actor.get("influence"), max_chars=160
                        ),
                    }
                    memory = sanitize_untrusted_research_text(
                        actor.get("memory"),
                        max_chars=300,
                    )
                    if memory:
                        researched["memory"] = memory
                    row["researched_profile"] = {
                        k: v for k, v in researched.items() if v
                    }
                if agent_id in context_projections:
                    row["actor_context"] = self._actor_context_behavior_projection(
                        context_projections[agent_id]
                    )
            entity_list.append(row)

        research_rule = ""
        if matched_actors and not canonical_agent_ids:
            research_rule = (
                "\n- **带 researched_profile 的实体是深度调研实证数据**：其 stance/sentiment_bias/"
                "influence_weight 必须与 researched_profile 的立场和影响力一致（high≈2.5-3.0, "
                "medium≈1.5-2.0, low≈0.8-1.2），不要凭空另行猜测"
                "；若带 actor_context，活动频率、响应速度、关注议题必须反映其中有来源的"
                "当前行动、未来计划、投资、能力边界、决策触发条件与时间紧迫性。"
                "analyst_inference/contested 只能作为建模不确定性，不能伪装成角色已知事实"
            )
        elif canonical_agent_ids:
            legacy_prefix = ""
            if len(canonical_agent_ids) != len(matched_actors):
                legacy_prefix = (
                    "\n- **带 researched_profile 的旧版实体继续按其调研字段配置**；"
                )
            research_rule = legacy_prefix + (
                "\n- **带 actor_context 的 actor-intelligence/v1 实体只以该来源绑定投影为准**："
                "活动频率、响应速度、关注议题、stance、sentiment_bias 与 influence_weight "
                "必须从 documented rows 推导；缺乏证据时保持 neutral/unknown，不得回读旧版 "
                "role/stance/influence/memory/incentives。analyst_inference/contested 只能表达"
                "建模不确定性，不能伪装成角色已知事实"
            )

        # 作息口径由活动画像决定；china_social 分支与历史措辞逐字节一致
        profile = self._activity_profile()
        agent_prompt_rhythm = profile["agent_prompt_rhythm"]
        agent_active_hours_hint = profile["agent_active_hours_hint"]
        # TEMPORAL spec §4: 日历模式（generate_config 已建时间线）删去昼夜作息提示行——
        # 「一轮=一个日历时段」下按小时的作息节律无意义；active_hours/响应延迟字段照常
        # 要求（运行时不消费，不破坏 schema）。小时制 rhythm_line 与历史逐字节一致。
        if getattr(self, "_temporal_timeline", None) is not None:
            rhythm_line = ""
        else:
            rhythm_line = f"{agent_prompt_rhythm}\n"

        requirement_block = delimit_untrusted_research_text(
            "agent configuration simulation requirement",
            simulation_requirement,
            max_chars=8_000,
        )
        entity_list_block = delimit_untrusted_research_text(
            "agent roster and actor-context projection JSON",
            json.dumps(entity_list, ensure_ascii=False, indent=2),
            max_chars=24_000,
        )
        prompt = f"""基于以下信息，为每个实体生成社交媒体活动配置。

模拟需求:
{requirement_block}

## 实体列表
```json
{entity_list_block}
```

## 任务
为每个实体生成活动配置，注意：
{rhythm_line}- **官方机构**（University/GovernmentAgency）：活跃度低(0.1-0.3)，工作时间(9-17)活动，响应慢(60-240分钟)，影响力高(2.5-3.0)
- **媒体**（MediaOutlet）：活跃度中(0.4-0.6)，全天活动(8-23)，响应快(5-30分钟)，影响力高(2.0-2.5)
- **个人**（Student/Person/Alumni）：活跃度高(0.6-0.9)，主要晚间活动(18-23)，响应快(1-15分钟)，影响力低(0.8-1.2)
- **公众人物/专家**：活跃度中(0.4-0.6)，影响力中高(1.5-2.0){research_rule}

返回JSON格式（不要markdown）：
{{
    "agent_configs": [
        {{
            "agent_id": <必须与输入一致>,
            "activity_level": <0.0-1.0>,
            "posts_per_hour": <发帖频率>,
            "comments_per_hour": <评论频率>,
            "active_hours": [<{agent_active_hours_hint}>],
            "response_delay_min": <最小响应延迟分钟>,
            "response_delay_max": <最大响应延迟分钟>,
            "sentiment_bias": <-1.0到1.0>,
            "stance": "<supportive/opposing/neutral/observer>",
            "influence_weight": <影响力权重>,
            "interested_topics": [<关注议题，1-3个；用于同温层聚类>]
        }},
        ...
    ]
}}"""

        system_prompt = profile["agent_system_prompt"]
        
        # EXECPLAN F-5-2: 防御式构建 agent_id -> 配置 映射，避免单条畸形配置（缺 agent_id / 类型不符）
        # 让 dict 推导原子失败，从而把整批 15 个 Agent 静默退化为规则生成；同时把 key 统一 int 化，
        # 修正 LLM 把 agent_id 输出成字符串（"5"）导致 int 查找全部 miss 的隐性退化。
        raw_cfgs: List[Any] = []
        llm_configs: Dict[int, Dict[str, Any]] = {}
        if not canonical_run:
            try:
                result = self._call_llm_with_retry(prompt, system_prompt)
                raw_cfgs = result.get("agent_configs", []) or []
                for cfg in raw_cfgs:
                    if not isinstance(cfg, dict):
                        continue
                    aid = cfg.get("agent_id")
                    if aid is None:
                        continue
                    try:
                        llm_configs[int(aid)] = cfg  # 强制 int 化："5" / 5.0 -> 5
                    except (TypeError, ValueError):
                        logger.warning(f"跳过无法解析 agent_id 的配置: {aid!r}")
            except Exception as e:
                logger.warning(f"Agent配置批次LLM生成失败: {e}, 使用规则生成")
                raw_cfgs = []
                llm_configs = {}

        # PREP-4(1): 按批记录 LLM 成功/规则回退（generate_config 初始化；直接调用本方法时缺省跳过）
        _stats = getattr(self, "_agent_batch_stats", None)
        if isinstance(_stats, dict):
            _stats["llm_batches" if (llm_configs or raw_cfgs) else "rule_batches"] += 1

        # 构建AgentActivityConfig对象
        configs = []
        # C5：是否启用价感知情感种子（旧 8 类/无新字段的今日数据 → False，逐批跳过 → 情感不变）
        valence_on = self._valence_signal_active(actors, actor_context_packs)
        for i, entity in enumerate(entities):
            agent_id = start_idx + i
            canonical_v1 = agent_id in canonical_agent_ids
            # EXECPLAN F-5-2: 优先按 id 命中；miss 时按位置回退（覆盖 LLM 漏写/写错 agent_id
            # 但仍按输入顺序返回配置的情况），最后再退化到规则生成。
            from_rule = False
            cfg = None if canonical_v1 else llm_configs.get(agent_id)
            if (
                not canonical_v1
                and not cfg
                and i < len(raw_cfgs)
                and isinstance(raw_cfgs[i], dict)
            ):
                cfg = raw_cfgs[i]

            # 如果LLM没有生成，使用规则生成
            if canonical_v1:
                cfg = self._generate_canonical_agent_config_by_rule(
                    self._actor_context_behavior_projection(
                        context_projections.get(agent_id) or {}
                    )
                )
                from_rule = True
                if isinstance(_stats, dict):
                    _stats["rule_agents"] += 1
            elif not cfg:
                cfg = self._generate_agent_config_by_rule(entity)
                from_rule = True
                if isinstance(_stats, dict):
                    _stats["rule_agents"] += 1
                if not canonical_v1:
                    # Legacy-only compatibility: canonical actors never read
                    # the unversioned flat influence field.
                    researched_weight = influence_weight(matched_actors.get(agent_id))
                    if researched_weight is not None:
                        cfg["influence_weight"] = researched_weight

            config = AgentActivityConfig(
                agent_id=agent_id,
                entity_uuid=entity.uuid,
                entity_name=(
                    canonical_runtime_names.get(agent_id, f"Unbound Actor {agent_id}")
                    if canonical_v1 else entity.name
                ),
                entity_type=(
                    "Actor" if canonical_v1 else entity.get_entity_type() or "Unknown"
                ),
                activity_level=cfg.get("activity_level", 0.5),
                posts_per_hour=cfg.get("posts_per_hour", 0.5),
                comments_per_hour=cfg.get("comments_per_hour", 1.0),
                active_hours=cfg.get("active_hours", list(range(9, 23))),
                response_delay_min=cfg.get("response_delay_min", 5),
                response_delay_max=cfg.get("response_delay_max", 60),
                sentiment_bias=cfg.get("sentiment_bias", 0.0),
                stance=cfg.get("stance", "neutral"),
                influence_weight=cfg.get("influence_weight", 1.0),
                # EXECPLAN F-5-3: cfg 未给 interested_topics 时按实体类型回退到确定性话题，
                # 保证 T3.4 同温层聚类键 (stance, topic) 不退化为仅按 stance。
                interested_topics=(
                    [str(t) for t in (cfg.get("interested_topics") or [])][:5]
                    or ([] if canonical_v1 else self._default_interested_topics(entity))
                ),
            )
            # T3.6: 在两条路径（LLM 成功 / 规则兜底）上都强制落研究档案的实证影响力，
            # 避免 LLM-success 路径只被「提示」而给出任意权重，破坏 T3.5 的影响力加权激活。
            if not canonical_v1:
                researched_weight = influence_weight(matched_actors.get(agent_id))
                if researched_weight is not None:
                    config.influence_weight = researched_weight
            # R2-SIM-3: 把研究档案的得失结构（incentives 的 gains_if/loses_if）落到配置，
            # 供决策通道按利害驱动承诺。缺失即空串，行为不变（degrade-safe）。
            gains_if, loses_if = self._extract_actor_incentive_summary(
                matched_actors.get(agent_id),
                self._actor_context_behavior_projection(
                    context_projections.get(agent_id) or {}
                ) if canonical_v1 else None,
            )
            config.gains_if = gains_if
            config.loses_if = loses_if
            projection = context_projections.get(agent_id) or {}
            if projection:
                behavior_projection = self._actor_context_behavior_projection(
                    projection
                )
                config.actor_context_digest = json.dumps(
                    behavior_projection,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                gap_audit = projection.get(
                    ACTOR_CONFIG_EVIDENCE_GAP_AUDIT_KEY
                )
                if isinstance(gap_audit, dict):
                    config.actor_context_evidence_gap_audit = gap_audit
                urgency = str(behavior_projection.get("urgency") or "")
                config.actor_context_urgency = urgency
                context_topics = self._actor_context_topics(behavior_projection)
                merged_topics: List[str] = []
                for topic in [*context_topics, *config.interested_topics]:
                    clean = str(topic or "").strip()
                    if clean and clean.casefold() not in {
                        item.casefold() for item in merged_topics
                    }:
                        merged_topics.append(clean)
                if merged_topics:
                    config.interested_topics = merged_topics[:5]
                # A documented active/near-term trigger should not yield a
                # dormant main actor on the rule or LLM path. The conservative
                # floors leave naturally more-active outputs unchanged.
                if urgency in {"active", "near_term"}:
                    try:
                        config.activity_level = max(float(config.activity_level), 0.4)
                    except (TypeError, ValueError):
                        config.activity_level = 0.4
                    try:
                        config.response_delay_max = min(
                            int(config.response_delay_max), 120
                        )
                    except (TypeError, ValueError):
                        config.response_delay_max = 120
            # C5: 价感知情感种子——把该角色关系网的聚合极性（盟友为正、对手为负）加性叠到
            # sentiment_bias 上，让对立双方开局即带方向性情绪，而非清一色由 stance 推。
            # 仅 valence_on（研究档案带新信号）时生效；今日数据走 valence_on==False，情感不变。
            if valence_on:
                nudge = self._relation_sentiment_nudge(
                    config.entity_name, actors, actor_context_packs
                )
                if nudge:
                    config.sentiment_bias = max(-1.0, min(1.0, config.sentiment_bias + nudge))
            # PREP-2: 规则兜底路径此前丢弃调研立场——LLM 整批失败时全体 neutral，产出零对比度
            # 话语场（0.58-0.82 聚簇预测的直接成因之一）。命中研究档案且配置来自规则兜底
            # （或 LLM 也只给了 neutral）时，按档案 stance 分桶覆盖，并为 supportive/opposing
            # 播下方向性情感种子。LLM 明确给出非 neutral 立场的路径不受影响。
            if getattr(Config, "SIM_RULE_FALLBACK_STANCE", True):
                actor_row = matched_actors.get(agent_id)
                if (
                    not canonical_v1
                    and isinstance(actor_row, dict)
                    and (from_rule or config.stance == "neutral")
                ):
                    bucket = self._classify_stance(str(actor_row.get("stance", "") or ""))
                    if bucket != "neutral" and bucket != config.stance:
                        config.stance = bucket
                        if config.sentiment_bias == 0.0 and bucket in ("supportive", "opposing"):
                            config.sentiment_bias = 0.3 if bucket == "supportive" else -0.3
            configs.append(config)

        return configs
    
    # EXECPLAN F-5-3: 按实体类型确定性映射关注议题，让 T3.4 同温层聚类键 (stance, topic)
    # 稳定且有意义；LLM 未给 interested_topics 时作为兜底，杜绝聚类静默退化为仅按 stance。
    _RULE_INTERESTED_TOPICS = {
        "university": ["Public Affairs"],
        "governmentagency": ["Public Affairs"],
        "ngo": ["Public Affairs"],
        "mediaoutlet": ["General News"],
        "professor": ["Academic"],
        "expert": ["Academic"],
        "official": ["Public Affairs"],
        "student": ["Education"],
        "alumni": ["Education"],
    }

    def _default_interested_topics(self, entity: EntityNode) -> List[str]:
        """EXECPLAN F-5-3 + QUALITY-OPT C5: deterministic interested-topics fallback.

        Keeps the entity-type topic FIRST (preserves echo-chamber cluster diversity — the
        cluster key is interested_topics[0]) and APPENDS the run's real forecast hot topics so
        agents engage with the actual subject. For entity types with no type-topic, spread agents
        deterministically across the hot topics (so clusters don't all collapse into one), and
        only fall back to the generic "Public Opinion" when no forecast topics exist at all.
        """
        entity_type = (entity.get_entity_type() or "Unknown").lower()
        base = list(self._RULE_INTERESTED_TOPICS.get(entity_type, []))
        hot = [str(t).strip() for t in (getattr(self, "_run_hot_topics", []) or []) if str(t).strip()]
        if base:
            primary = base[0]
        elif hot:
            # deterministic spread across the forecast's hot topics → diverse clusters
            primary = hot[sum(map(ord, (entity.name or "x"))) % len(hot)]
        else:
            primary = "Public Opinion"
        out: List[str] = [primary]
        for h in hot[:2]:
            if h.lower() != primary.lower() and h not in out:
                out.append(h)
        return out

    @classmethod
    def _extract_actor_incentive_summary(
        cls,
        actor: Optional[Dict[str, Any]],
        canonical_projection: Optional[Dict[str, Any]] = None,
    ) -> tuple:
        """R2-SIM-3: aggregate an actor's incentives[] into compact (gains_if, loses_if)
        strings for the decision channel. Each incentive is ``{driver, gains_if, loses_if,
        intensity}`` (deep-research actors-and-incentives schema). Missing/empty → ("", ""),
        so old dossiers without the field leave the config unchanged (degrade-safe)."""
        if not isinstance(actor, dict):
            return "", ""
        if cls._is_canonical_actor(actor):
            if (
                not isinstance(canonical_projection, dict)
                or canonical_projection.get("schema_version")
                != "actor-config-context/v1"
            ):
                raise ValueError(
                    "canonical actor incentive summary requires actor-context/v1 projection"
                )
            gains: List[str] = []
            loses: List[str] = []
            for inc in canonical_projection.get("decision_incentives") or []:
                if not isinstance(inc, dict):
                    continue
                g = str(inc.get("gains_if") or "").strip()
                l = str(inc.get("loses_if") or "").strip()
                if g and g not in gains:
                    gains.append(g)
                if l and l not in loses:
                    loses.append(l)
            return "；".join(gains), "；".join(loses)

        # Exact unversioned compatibility path.
        incentives = actor.get("incentives")
        if not isinstance(incentives, list):
            return "", ""
        gains: List[str] = []
        loses: List[str] = []
        for inc in incentives[:4]:  # cap so the prompt stays compact
            if not isinstance(inc, dict):
                continue
            g = str(inc.get("gains_if", "") or "").strip()
            l = str(inc.get("loses_if", "") or "").strip()
            if g and g not in gains:
                gains.append(g)
            if l and l not in loses:
                loses.append(l)
        return "；".join(gains), "；".join(loses)

    _ACTOR_CONTEXT_EVIDENCE_TYPES = {
        "verified_fact", "actor_stated_claim", "analyst_inference",
        "contested", "unknown",
    }
    _ACTOR_CONTEXT_QUALIFIERS = {
        "conditions", "amount", "unit", "scale", "type", "action_type",
        "strategic_purpose", "basis", "leverage", "project", "program",
        "product", "asset", "counterparty", "geography", "actor_knows",
        "visibility", "deployability", "driver", "gains_if", "loses_if",
        "intensity",
    }

    @staticmethod
    def _safe_actor_context_scalar(value: Any, max_chars: int = 320) -> Any:
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, (dict, list, tuple)):
            try:
                value = json.dumps(
                    value, ensure_ascii=False, sort_keys=True, allow_nan=False
                )
            except (TypeError, ValueError):
                return "[invalid nested actor-context value omitted]"
        return sanitize_untrusted_dossier_text(value, max_chars)

    @classmethod
    def _safe_actor_context_list(
        cls, value: Any, *, limit: int, max_chars: int
    ) -> List[Any]:
        if not isinstance(value, list):
            return []
        out: List[Any] = []
        for item in value[:limit]:
            clean = cls._safe_actor_context_scalar(item, max_chars)
            if clean not in (None, "", [], {}):
                out.append(clean)
        return out

    @classmethod
    def _actor_context_claim_rows(
        cls, pack: Dict[str, Any], dimensions: List[str]
    ) -> List[Dict[str, Any]]:
        intelligence = pack.get("actor_intelligence")
        dimension_map = (
            intelligence.get("dimensions")
            if isinstance(intelligence, dict) else None
        )
        if not isinstance(dimension_map, dict):
            return []
        intelligence_version = str(intelligence.get("schema_version") or "").strip()
        if intelligence_version and intelligence_version != "actor-intelligence/v1":
            raise ValueError(
                "unsupported actor intelligence schema in actor context: "
                + intelligence_version
            )
        canonical_v1 = intelligence_version == "actor-intelligence/v1"
        rows: List[Dict[str, Any]] = []
        for dimension in dimensions:
            claims = dimension_map.get(dimension)
            if not isinstance(claims, list):
                continue
            for claim in claims:
                if not isinstance(claim, dict) or not str(claim.get("claim") or "").strip():
                    continue
                if canonical_v1 and not (
                    isinstance(claim.get("source_refs"), list)
                    and any(str(ref or "").strip() for ref in claim["source_refs"])
                ):
                    continue
                evidence_type = str(
                    claim.get("evidence_type") or "unknown"
                ).strip().casefold()
                if evidence_type not in cls._ACTOR_CONTEXT_EVIDENCE_TYPES:
                    evidence_type = "unknown"
                row: Dict[str, Any] = {
                    "dimension": dimension,
                    "claim": cls._safe_actor_context_scalar(
                        claim.get("claim"), 600
                    ),
                    "evidence_type": evidence_type,
                }
                for key, limit in (
                    ("as_of_date", 40), ("horizon", 120),
                    ("status", 80), ("confidence", 40), ("visibility", 40),
                ):
                    clean = cls._safe_actor_context_scalar(claim.get(key), limit)
                    if clean not in (None, ""):
                        row[key] = clean
                if isinstance(claim.get("actor_knows"), bool):
                    row["actor_knows"] = claim["actor_knows"]
                for key, limit, max_chars in (
                    ("source_refs", 8, 180),
                    ("dependencies", 6, 240),
                    ("contradictions", 6, 240),
                ):
                    clean_list = cls._safe_actor_context_list(
                        claim.get(key), limit=limit, max_chars=max_chars
                    )
                    if clean_list:
                        row[key] = clean_list
                qualifiers = claim.get("qualifiers")
                if isinstance(qualifiers, dict):
                    safe_qualifiers = {
                        key: cls._safe_actor_context_scalar(value, 320)
                        for key, value in qualifiers.items()
                        if key in cls._ACTOR_CONTEXT_QUALIFIERS
                    }
                    safe_qualifiers = {
                        key: value for key, value in safe_qualifiers.items()
                        if value not in (None, "", [], {})
                    }
                    if safe_qualifiers:
                        row["qualifiers"] = safe_qualifiers
                rows.append(row)
        return rows

    @classmethod
    def _safe_actor_context_relationship(
        cls, row: Dict[str, Any]
    ) -> Dict[str, Any]:
        safe: Dict[str, Any] = {}
        for key, limit in (
            ("source", 180), ("target", 180), ("type", 80),
            ("relation_label", 80), ("direction", 40), ("strength", 40),
            ("valence", 40), ("sign", 40), ("basis", 400),
            ("confidence", 40), ("status", 80), ("as_of_date", 40),
            ("evidence_type", 40), ("visibility", 40), ("polarity", 40),
        ):
            clean = cls._safe_actor_context_scalar(row.get(key), limit)
            if clean not in (None, ""):
                safe[key] = clean
        if isinstance(row.get("actor_knows"), bool):
            safe["actor_knows"] = row["actor_knows"]
        refs = cls._safe_actor_context_list(
            row.get("source_refs"), limit=8, max_chars=180
        )
        if refs:
            safe["source_refs"] = refs
        return safe

    @classmethod
    def _actor_context_behavior_projection(
        cls,
        projection: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Return only the 1,800-character behavior view.

        The sealed gap ledger is config audit state. It must survive typed in
        the persisted config, but it must never enter actor/LLM knowledge or
        influence activity, topics, stance, incentives, or urgency.
        """
        if not isinstance(projection, dict):
            return {}
        return {
            key: value
            for key, value in projection.items()
            if key != ACTOR_CONFIG_EVIDENCE_GAP_AUDIT_KEY
        }

    @classmethod
    def _actor_context_config_projection(
        cls, pack: Dict[str, Any], max_chars: int = 1_800
    ) -> Dict[str, Any]:
        """Build behavior context plus a separately bounded typed gap audit.

        ``max_chars`` applies only to the behavior view returned by
        :meth:`_actor_context_behavior_projection`. The gap audit has its own
        deterministic bound and seal so all current v1 dimension gaps survive
        without consuming prompt/model tokens or influencing actor behavior.
        """
        if not isinstance(pack, dict):
            return {}
        priority_dimensions = [
            "current_actions",
            "future_plans",
            "investments_capital_allocation",
            "capabilities",
            "decision_rights_process_triggers",
            "incentives",
            "motivations",
            "constraints",
        ]
        claims = cls._actor_context_claim_rows(pack, priority_dimensions)
        documented: List[Dict[str, Any]] = []
        inference: List[Dict[str, Any]] = []
        contested: List[Dict[str, Any]] = []
        for claim in claims:
            evidence_type = str(claim.get("evidence_type") or "unknown")
            if evidence_type == "analyst_inference":
                inference.append(claim)
            elif evidence_type in {"contested", "unknown"}:
                contested.append(claim)
            else:
                documented.append(claim)

        projection: Dict[str, Any] = {
            "schema_version": "actor-config-context/v1",
            "actor_id": cls._safe_actor_context_scalar(pack.get("actor_id"), 180),
            "actor_name": cls._safe_actor_context_scalar(pack.get("actor_name"), 240),
            "source": {},
            "decision_incentives": [],
            "documented": [],
            "analyst_inference_not_actor_knowledge": [],
            "contested_not_actor_knowledge": [],
            "relationships_and_leverage": [],
            "report_section_headings": [],
        }

        raw_source = pack.get("source")
        if isinstance(raw_source, dict):
            for key in (
                "actor_intelligence_contract_version",
                "actor_intelligence_sha256", "actors_sha256", "report_sha256",
                "dossier_sha256", "sources_sha256", "actor_ids_sha256",
            ):
                clean = cls._safe_actor_context_scalar(raw_source.get(key), 180)
                if clean not in (None, ""):
                    projection["source"][key] = clean

        # The post-simulation decision channel consumes gains_if/loses_if
        # directly.  Preserve those structured, source-bound payoffs ahead of
        # the general 1,800-character activity projection so earlier action or
        # plan rows cannot starve them from the decision-facing contract.
        for row in documented:
            if row.get("dimension") != "incentives":
                continue
            qualifiers = row.get("qualifiers")
            if not isinstance(qualifiers, dict):
                continue
            incentive = {
                key: cls._safe_actor_context_scalar(qualifiers.get(key), 220)
                for key in ("driver", "gains_if", "loses_if", "intensity")
                if qualifiers.get(key) not in (None, "")
            }
            if not incentive.get("gains_if") and not incentive.get("loses_if"):
                continue
            candidate = dict(projection)
            candidate["decision_incentives"] = [
                *projection["decision_incentives"], incentive
            ]
            if len(json.dumps(
                candidate, ensure_ascii=False, sort_keys=True, allow_nan=False
            )) > max_chars:
                break
            projection["decision_incentives"].append(incentive)
            if len(projection["decision_incentives"]) >= 4:
                break

        def add_rows(key: str, rows: List[Dict[str, Any]], limit: int) -> None:
            for row in rows[:limit]:
                candidate = dict(projection)
                candidate[key] = [*projection[key], row]
                if len(json.dumps(
                    candidate, ensure_ascii=False, sort_keys=True, allow_nan=False
                )) > max_chars:
                    break
                projection[key].append(row)

        add_rows("documented", documented, 14)
        add_rows("analyst_inference_not_actor_knowledge", inference, 5)
        add_rows("contested_not_actor_knowledge", contested, 5)
        relationships = pack.get("relationships")
        if isinstance(relationships, list):
            add_rows(
                "relationships_and_leverage",
                [
                    cls._safe_actor_context_relationship(row)
                    for row in relationships
                    if isinstance(row, dict)
                    and is_hard_public_relationship(row)
                ],
                8,
            )
        sections = pack.get("relevant_sections")
        if isinstance(sections, list):
            for row in sections:
                if not isinstance(row, dict):
                    continue
                heading = cls._safe_actor_context_scalar(
                    row.get("heading"), 240
                )
                if not heading:
                    continue
                candidate = dict(projection)
                candidate["report_section_headings"] = [
                    *projection["report_section_headings"], heading
                ]
                if len(json.dumps(
                    candidate, ensure_ascii=False, sort_keys=True, allow_nan=False
                )) > max_chars:
                    break
                projection["report_section_headings"].append(heading)

        documented_dimensions = {
            str(row.get("dimension")) for row in projection["documented"]
        }
        if "current_actions" in documented_dimensions:
            urgency = "active"
        elif documented_dimensions.intersection({
            "future_plans", "decision_rights_process_triggers"
        }):
            near_tokens = ("now", "immediate", "near-term", "next 90", "本月", "近期", "立即")
            blob = json.dumps(projection["documented"], ensure_ascii=False).casefold()
            urgency = "near_term" if any(token in blob for token in near_tokens) else "strategic"
        else:
            urgency = "baseline"
        projection["urgency"] = urgency
        projection["epistemic_policy"] = (
            "Use documented rows as actor-grounded behavior evidence. Analyst inference "
            "and contested rows express modeler uncertainty, not actor knowledge. "
            "Evidence-gap queries and receipt/result identifiers are modeler-only "
            "research audit metadata and never establish actor knowledge."
        )
        # Final hard bound after adding policy/urgency. Remove complete lowest-
        # priority items rather than slicing serialized JSON mid-claim.
        trim_order = [
            "report_section_headings",
            "relationships_and_leverage",
            "contested_not_actor_knowledge",
            "analyst_inference_not_actor_knowledge",
            "documented",
        ]
        while len(json.dumps(
            projection, ensure_ascii=False, sort_keys=True, allow_nan=False
        )) > max_chars:
            trimmed = False
            for key in trim_order:
                values = projection.get(key)
                if isinstance(values, list) and values:
                    values.pop()
                    trimmed = True
                    break
            if not trimmed:
                break

        behavior_chars = len(json.dumps(
            projection, ensure_ascii=False, sort_keys=True, allow_nan=False
        ))
        if behavior_chars > max_chars:
            raise ValueError(
                "actor config behavior projection exceeds its character budget: "
                f"{behavior_chars} > {max_chars}"
            )

        intelligence = pack.get("actor_intelligence")
        raw_gaps = (
            intelligence.get("evidence_gaps")
            if isinstance(intelligence, dict) else None
        )
        typed_gaps = normalize_evidence_gap_map(
            raw_gaps,
            require_lossless=(
                isinstance(intelligence, dict)
                and intelligence.get("schema_version")
                == ACTOR_INTELLIGENCE_VERSION
            ),
        )
        if typed_gaps:
            audit_payload = {
                "schema_version": ACTOR_CONFIG_EVIDENCE_GAP_AUDIT_VERSION,
                "actor_id": projection["actor_id"],
                "actor_intelligence_sha256": projection["source"].get(
                    "actor_intelligence_sha256"
                ),
                "evidence_gaps": typed_gaps,
            }
            audit_bytes = len(json.dumps(
                audit_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8"))
            if audit_bytes > ACTOR_CONFIG_EVIDENCE_GAP_AUDIT_MAX_BYTES:
                raise ValueError(
                    "actor config evidence-gap audit exceeds its byte budget: "
                    f"{audit_bytes} > "
                    f"{ACTOR_CONFIG_EVIDENCE_GAP_AUDIT_MAX_BYTES}"
                )
            projection[ACTOR_CONFIG_EVIDENCE_GAP_AUDIT_KEY] = {
                **audit_payload,
                "canonical_bytes": audit_bytes,
                "max_bytes": ACTOR_CONFIG_EVIDENCE_GAP_AUDIT_MAX_BYTES,
                "sha256": canonical_json_sha256(audit_payload),
            }
        return projection

    @staticmethod
    def _actor_context_topics(projection: Dict[str, Any]) -> List[str]:
        topics: List[str] = []
        for row in projection.get("documented") or []:
            if not isinstance(row, dict):
                continue
            qualifiers = row.get("qualifiers")
            if isinstance(qualifiers, dict):
                for key in ("project", "program", "product", "asset", "strategic_purpose"):
                    value = str(qualifiers.get(key) or "").strip()
                    if value:
                        topics.append(value[:100])
            claim = str(row.get("claim") or "").strip()
            if claim and row.get("dimension") in {
                "current_actions", "future_plans", "investments_capital_allocation"
            }:
                topics.append(claim[:100])
        topics.extend(
            str(item).strip()
            for item in (projection.get("report_section_headings") or [])
            if str(item).strip()
        )
        unique: List[str] = []
        for topic in topics:
            if topic and topic.casefold() not in {item.casefold() for item in unique}:
                unique.append(topic)
        return unique[:3]

    @classmethod
    def _generate_canonical_agent_config_by_rule(
        cls, projection: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Return the deterministic fail-neutral v1 activity baseline.

        Graph type, graph summary, and unversioned actor shortcuts are not
        authoritative after the actor-intelligence/v1 cutover.  Known,
        source-bound context may add topics and the caller may later apply the
        documented urgency floor; everything else remains neutral rather than
        being guessed from an institution/person stereotype.
        """
        return {
            "activity_level": 0.5,
            "posts_per_hour": 0.5,
            "comments_per_hour": 1.0,
            "active_hours": list(range(9, 23)),
            "response_delay_min": 5,
            "response_delay_max": 60,
            "sentiment_bias": 0.0,
            "stance": "neutral",
            "influence_weight": 1.0,
            "interested_topics": cls._actor_context_topics(projection),
        }

    def _generate_agent_config_by_rule(self, entity: EntityNode) -> Dict[str, Any]:
        """基于规则生成单个Agent配置（中国人作息）"""
        entity_type = (entity.get_entity_type() or "Unknown").lower()
        # EXECPLAN F-5-3: 规则路径同样产出 interested_topics，保证聚类键在确定性兜底路径下可用
        interested_topics = self._default_interested_topics(entity)

        # PREP-2: 规则表补齐现行动态本体的实体类型（Government/Organization/StrategicAsset/
        # PolicyInstrument/MarketSignal…）——此前只认旧校园本体，动态本体的全部实体跌入
        # 「普通人」else 分支（全体 activity 0.7 / 0.5帖/时 / neutral，零对比度）。
        if entity_type in ["university", "governmentagency", "ngo", "government", "country"]:
            # 官方机构：工作时间活动，低频率，高影响力
            return {
                "activity_level": 0.2,
                "posts_per_hour": 0.1,
                "comments_per_hour": 0.05,
                "active_hours": list(range(9, 18)),  # 9:00-17:59
                "response_delay_min": 60,
                "response_delay_max": 240,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 3.0,
                "interested_topics": interested_topics
            }
        elif entity_type in ["mediaoutlet"]:
            # 媒体：全天活动，中等频率，高影响力
            return {
                "activity_level": 0.5,
                "posts_per_hour": 0.8,
                "comments_per_hour": 0.3,
                "active_hours": list(range(7, 24)),  # 7:00-23:59
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "observer",
                "influence_weight": 2.5,
                "interested_topics": interested_topics
            }
        elif entity_type in ["professor", "expert", "official"]:
            # 专家/教授：工作+晚间活动，中等频率
            return {
                "activity_level": 0.4,
                "posts_per_hour": 0.3,
                "comments_per_hour": 0.5,
                "active_hours": list(range(8, 22)),  # 8:00-21:59
                "response_delay_min": 15,
                "response_delay_max": 90,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 2.0,
                "interested_topics": interested_topics
            }
        elif entity_type in ["student"]:
            # 学生：晚间为主，高频率
            return {
                "activity_level": 0.8,
                "posts_per_hour": 0.6,
                "comments_per_hour": 1.5,
                "active_hours": [8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],  # 上午+晚间
                "response_delay_min": 1,
                "response_delay_max": 15,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 0.8,
                "interested_topics": interested_topics
            }
        elif entity_type in ["alumni"]:
            # 校友：晚间为主
            return {
                "activity_level": 0.6,
                "posts_per_hour": 0.4,
                "comments_per_hour": 0.8,
                "active_hours": [12, 13, 19, 20, 21, 22, 23],  # 午休+晚间
                "response_delay_min": 5,
                "response_delay_max": 30,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0,
                "interested_topics": interested_topics
            }
        elif entity_type in ["organization", "company"]:
            # PREP-2: 机构/企业：中等活跃、工作时段为主、响应偏慢、影响力中高
            return {
                "activity_level": 0.35,
                "posts_per_hour": 0.3,
                "comments_per_hour": 0.3,
                "active_hours": list(range(8, 20)),  # 8:00-19:59
                "response_delay_min": 30,
                "response_delay_max": 120,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 2.0,
                "interested_topics": interested_topics
            }
        elif entity_type in ["strategicasset", "policyinstrument", "marketsignal", "concept"]:
            # PREP-2: 资产/政策工具/市场信号等非能动实体：低活跃观察者，
            # 避免以「普通人」的高活跃度刷屏
            return {
                "activity_level": 0.15,
                "posts_per_hour": 0.1,
                "comments_per_hour": 0.2,
                "active_hours": list(range(9, 18)),  # 9:00-17:59
                "response_delay_min": 60,
                "response_delay_max": 240,
                "sentiment_bias": 0.0,
                "stance": "observer",
                "influence_weight": 1.2,
                "interested_topics": interested_topics
            }
        else:
            # 普通人：晚间高峰
            return {
                "activity_level": 0.7,
                "posts_per_hour": 0.5,
                "comments_per_hour": 1.2,
                "active_hours": [9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23],  # 白天+晚间
                "response_delay_min": 2,
                "response_delay_max": 20,
                "sentiment_bias": 0.0,
                "stance": "neutral",
                "influence_weight": 1.0,
                "interested_topics": interested_topics
            }

    # ====================================================================
    # I-2-2: 「沉默的大多数」受众群体生成（程序化、零 LLM/Zep 调用）
    # ====================================================================

    # 受众 Agent 在配置里的实体类型标记，便于运行脚本/指标按群体区分。
    AUDIENCE_ENTITY_TYPE = "Audience"

    # 受众立场 → AgentActivityConfig.stance 的取值（与具名 Agent 同一桶集合，
    # 以便 T3.4 同温层聚类键 (stance, topic) 自然把受众并入对应阵营）。
    _AUDIENCE_STANCE_BUCKETS = ["supportive", "opposing", "neutral", "observer"]

    # 研究档案里 actor.stance 自由文本 → 标准化立场桶的关键词映射（中英文）。
    _STANCE_KEYWORDS = {
        "supportive": ["support", "favor", "pro-", "拥护", "支持", "赞成", "看多", "利好"],
        "opposing": ["oppos", "against", "critic", "反对", "批评", "抵制", "看空", "质疑"],
        "observer": ["observ", "report", "neutral coverage", "中立报道", "观察", "旁观", "报道"],
    }

    def _build_audience_rng(self) -> "random.Random":
        """I-2-2: 受众抽样 RNG。SIM_SEED>0 时确定性可复现，否则系统熵播种。

        复用 run_parallel_simulation 的 SIM_SEED 语义；优先读环境变量（与运行脚本一致），
        缺省回退到 Config.SIM_SEED。0/空/非整数一律退化为非确定性，与历史行为一致。
        """
        raw = os.environ.get("SIM_SEED")
        if raw is None or str(raw).strip() == "":
            raw = getattr(Config, "SIM_SEED", 0)
        try:
            seed = int(str(raw).strip())
        except (TypeError, ValueError):
            return random.Random()
        if seed == 0:
            return random.Random()
        # 受众用独立子种子（与调度采样错开），避免两处采样耦合。
        return random.Random(seed ^ 0x4155_4449)  # "AUDI"

    def _audience_stance_distribution(
        self,
        actors: Optional[Dict[str, Any]],
        main_agent_configs: Optional[List[AgentActivityConfig]] = None,
    ) -> Dict[str, float]:
        """I-2-2: 由调研 actor 立场推导受众立场抽样分布。

        统计每个 actor 的 stance 落入哪个标准化立场桶（supportive/opposing/observer/neutral），
        归一化为概率分布。无 actor 或全部无法解析 → 返回均匀分布（不偏向任何阵营）。
        受众默认偏向「沉默」，因此把无法明确归类者计入 neutral，使大多数保持中立潜水。
        """
        counts: Dict[str, float] = dict.fromkeys(
            self._AUDIENCE_STANCE_BUCKETS, 0.0
        )
        safe_v1_stance_by_name = {
            normalize_name(config.entity_name): str(config.stance or "neutral")
            for config in (main_agent_configs or [])
            if isinstance(config, AgentActivityConfig) and config.entity_name
        }
        for row in extract_actor_rows(actors):
            if self._is_canonical_actor(row):
                # The named config was generated from actor-context/v1.  Use
                # that safe result; direct callers without it get neutral,
                # never the invalidated flat actor.stance compatibility field.
                raw_stance = safe_v1_stance_by_name.get(
                    normalize_name(str(row.get("name") or "")), "neutral"
                )
            else:
                raw_stance = str(row.get("stance", "") or "")
            bucket = self._classify_stance(raw_stance)
            counts[bucket] += 1.0
        total = sum(counts.values())
        if total <= 0:
            # 无实证立场：均匀分布
            n = len(self._AUDIENCE_STANCE_BUCKETS)
            return dict.fromkeys(self._AUDIENCE_STANCE_BUCKETS, 1.0 / n)
        return {b: c / total for b, c in counts.items()}

    def _classify_stance(self, raw_stance: str) -> str:
        """I-2-2: actor.stance 自由文本 → 标准化立场桶；无法识别归为 neutral。"""
        s = raw_stance.strip().lower()
        if not s:
            return "neutral"
        for bucket, keywords in self._STANCE_KEYWORDS.items():
            for kw in keywords:
                if kw in s:
                    return bucket
        return "neutral"

    def _sample_audience_stance(
        self, rng: "random.Random", distribution: Dict[str, float]
    ) -> str:
        """I-2-2: 按立场分布抽一个受众立场。分布退化（全 0）时回退均匀抽样。"""
        buckets = list(distribution.keys()) or list(self._AUDIENCE_STANCE_BUCKETS)
        weights = [max(0.0, distribution.get(b, 0.0)) for b in buckets]
        if sum(weights) <= 0:
            return rng.choice(self._AUDIENCE_STANCE_BUCKETS)
        return rng.choices(buckets, weights=weights, k=1)[0]

    def _generate_audience_agent_configs(
        self,
        start_idx: int,
        event_config: EventConfig,
        actors: Optional[Dict[str, Any]],
        main_agent_configs: Optional[List[AgentActivityConfig]] = None,
        actor_context_packs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[AgentActivityConfig]:
        """I-2-2: 程序化生成 M 个低影响力「沉默大多数」受众 Agent 配置。

        - 数量由 SIM_AUDIENCE_AGENTS 控制（默认 0 → 返回 []，agent 池只含主阵容；
          兼容旧名 SIM_AUDIENCE_SIZE）。ACTOR-CAST discipline：主阵容 ≤ ACTOR_CAST_MAX
          个具名 main actors + 本函数的 M 个零 LLM 成本受众填充，取代旧的
          「向 OASIS_MAX_AGENTS≈80 填充图谱通用节点（每个都烧 persona LLM 调用）」。
        - 立场按调研立场分布抽样（无调研 → 均匀），议题复用热点话题（无则留空，
          聚类退化为仅按 stance）。
        - 高潜水偏好：低 activity_level、低 posts_per_hour、低 influence_weight，
          response_delay 较长——绝大多数只 LIKE/REPOST/潜水，偶尔冒泡。
        - agent_id 从 start_idx 连续编号，与具名角色衔接，保证 OASIS agent_graph 下标一致。
        - 不做逐 Agent 的 LLM/Zep 调用，生成成本可忽略，可廉价压到 300-1000 规模。
        """
        try:
            size = int(getattr(Config, "SIM_AUDIENCE_AGENTS", 0) or 0)
        except (TypeError, ValueError):
            size = 0
        if size <= 0:
            # 兼容旧名 SIM_AUDIENCE_SIZE（I-2-2 时代的属性注入口径）。
            try:
                size = int(getattr(Config, "SIM_AUDIENCE_SIZE", 0) or 0)
            except (TypeError, ValueError):
                size = 0
        if size <= 0:
            return []
        # 防御性上限：避免极端配置一次性撑出超大配置文件（仍远超具名上限）。
        size = min(size, 5000)

        rng = self._build_audience_rng()
        distribution = self._audience_stance_distribution(
            actors, main_agent_configs=main_agent_configs
        )

        # 受众默认每轮激活上限（仅记录到 reasoning / 供运行脚本采样限流参考）——
        # 真正的「每轮只激活一小撮受众」由运行脚本的加权激活采样配合低 activity_level 实现。
        try:
            active_cap = int(getattr(Config, "SIM_AUDIENCE_ACTIVE_CAP", 0) or 0)
        except (TypeError, ValueError):
            active_cap = 0
        if active_cap > 0:
            logger.info(f"受众每轮激活上限（SIM_AUDIENCE_ACTIVE_CAP）: {active_cap}")

        # 受众关注议题：复用研究/事件得到的热点话题（最多 3 个），让受众落入真实议题的同温层。
        hot_topics = [str(t) for t in (event_config.hot_topics or []) if str(t).strip()]

        # C5：是否启用价感知情感种子。受众为匿名「公众_k」，名字不在 relationships[] 中，
        # _relation_sentiment_nudge 恒返回 0.0 → 受众情感逐字节不变；此处保持与具名路径一致的写法。
        valence_on = self._valence_signal_active(actors, actor_context_packs)

        configs: List[AgentActivityConfig] = []
        for k in range(size):
            agent_id = start_idx + k
            stance = self._sample_audience_stance(rng, distribution)

            # 高潜水：低活跃度、低发帖、几乎只评论/点赞，影响力低。
            activity_level = round(rng.uniform(0.2, 0.6), 3)
            influence = round(rng.uniform(0.3, 0.8), 3)
            posts_per_hour = round(rng.uniform(0.02, 0.15), 3)
            comments_per_hour = round(rng.uniform(0.1, 0.5), 3)

            # 立场决定轻微的情感偏置（与具名角色同向，但幅度更小、噪声更多）。
            if stance == "supportive":
                sentiment_bias = round(rng.uniform(0.1, 0.6), 3)
            elif stance == "opposing":
                sentiment_bias = round(rng.uniform(-0.6, -0.1), 3)
            else:
                sentiment_bias = round(rng.uniform(-0.2, 0.2), 3)

            # C5: 价感知情感种子，加性叠加（不消耗 RNG，故不扰乱受众抽样的确定性）。匿名受众名
            # 不在 relationships[] 中 → nudge 恒为 0.0 → 受众情感保持原值，今日数据逐字节不变。
            if valence_on:
                nudge = self._relation_sentiment_nudge(
                    f"公众_{k}", actors, actor_context_packs
                )
                if nudge:
                    sentiment_bias = round(max(-1.0, min(1.0, sentiment_bias + nudge)), 3)

            # 活跃时段：普通公众的白天 + 晚间高峰作息（与规则「普通人」一致，略加抖动）。
            base_hours = [9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 23]
            active_hours = sorted(rng.sample(base_hours, k=rng.randint(5, len(base_hours))))

            # 关注议题：从热点话题里随机取 1-2 个（无热点 → 空，聚类退化为仅按 stance）。
            if hot_topics:
                pick = min(len(hot_topics), rng.randint(1, 2))
                interested_topics = rng.sample(hot_topics, k=pick)
            else:
                interested_topics = []

            configs.append(AgentActivityConfig(
                agent_id=agent_id,
                entity_uuid=f"audience:{agent_id}",  # 合成 uuid，不指向任何图谱节点
                entity_name=f"公众_{k}",
                entity_type=self.AUDIENCE_ENTITY_TYPE,
                activity_level=activity_level,
                posts_per_hour=posts_per_hour,
                comments_per_hour=comments_per_hour,
                active_hours=active_hours,
                response_delay_min=rng.randint(5, 30),
                response_delay_max=rng.randint(60, 240),
                sentiment_bias=sentiment_bias,
                stance=stance,
                influence_weight=influence,
                interested_topics=interested_topics,
            ))

        return configs
