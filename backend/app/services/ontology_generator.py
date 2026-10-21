"""
本体生成服务
接口1：分析文本内容，生成适合社会模拟的实体和关系类型定义
"""

import json
import unicodedata
from collections import Counter
from typing import Dict, Any, List, Optional
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from .actor_role_prompt import (
    delimit_untrusted_research_text,
    sanitize_untrusted_research_text,
)

try:
    # 读取可选配置旗标（本文件不拥有 config.py，仅通过 getattr 读取，缺失即降级）。
    from ..config import Config as _Config
except Exception:  # pragma: no cover - 配置导入失败时退回纯默认行为
    _Config = None


# F-3-4: 模块日志器，使本体截断/丢弃可审计（此前文件无任何日志）
logger = get_logger('mirofish.ontology_generator')

# Zep/Falkor 属性保留字（与 graph_builder.safe_attr_name 的 RESERVED_NAMES 对齐）。
# 本体属性名若撞上保留字，下游 set_ontology 会改写为 entity_<name>，因此在生成阶段
# 也据此校验/清洗，保证 general_forecast 模板新引入的 edge/entity 属性可被检索安全消费。
RESERVED_ATTR_NAMES = {
    'uuid', 'name', 'group_id', 'name_embedding', 'summary', 'created_at',
}


# 本体生成的系统提示词
ONTOLOGY_SYSTEM_PROMPT = """你是一个专业的知识图谱本体设计专家。你的任务是分析给定的文本内容和模拟需求，设计适合**社交媒体舆论模拟**的实体类型和关系类型。

**重要：你必须输出有效的JSON格式数据，不要输出任何其他内容。**

## 核心任务背景

我们正在构建一个**社交媒体舆论模拟系统**。在这个系统中：
- 每个实体都是一个可以在社交媒体上发声、互动、传播信息的"账号"或"主体"
- 实体之间会相互影响、转发、评论、回应
- 我们需要模拟舆论事件中各方的反应和信息传播路径

因此，**实体必须是现实中真实存在的、可以在社媒上发声和互动的主体**：

**可以是**：
- 具体的个人（公众人物、当事人、意见领袖、专家学者、普通人）
- 公司、企业（包括其官方账号）
- 组织机构（大学、协会、NGO、工会等）
- 政府部门、监管机构
- 媒体机构（报纸、电视台、自媒体、网站）
- 社交媒体平台本身
- 特定群体代表（如校友会、粉丝团、维权群体等）

**不可以是**：
- 抽象概念（如"舆论"、"情绪"、"趋势"）
- 主题/话题（如"学术诚信"、"教育改革"）
- 观点/态度（如"支持方"、"反对方"）

## 输出格式

请输出JSON格式，包含以下结构：

```json
{
    "entity_types": [
        {
            "name": "实体类型名称（英文，PascalCase）",
            "description": "简短描述（英文，不超过100字符）",
            "attributes": [
                {
                    "name": "属性名（英文，snake_case）",
                    "type": "text",
                    "description": "属性描述"
                }
            ],
            "examples": ["示例实体1", "示例实体2"]
        }
    ],
    "edge_types": [
        {
            "name": "关系类型名称（英文，UPPER_SNAKE_CASE）",
            "description": "简短描述（英文，不超过100字符）",
            "source_targets": [
                {"source": "源实体类型", "target": "目标实体类型"}
            ],
            "attributes": []
        }
    ],
    "analysis_summary": "对文本内容的简要分析说明（中文）"
}
```

## 设计指南（极其重要！）

### 1. 实体类型设计 - 必须严格遵守

**数量要求：必须正好10个实体类型**

**层次结构要求（必须同时包含具体类型和兜底类型）**：

你的10个实体类型必须包含以下层次：

A. **兜底类型（必须包含，放在列表最后2个）**：
   - `Person`: 任何自然人个体的兜底类型。当一个人不属于其他更具体的人物类型时，归入此类。
   - `Organization`: 任何组织机构的兜底类型。当一个组织不属于其他更具体的组织类型时，归入此类。

B. **具体类型（8个，根据文本内容设计）**：
   - 针对文本中出现的主要角色，设计更具体的类型
   - 例如：如果文本涉及学术事件，可以有 `Student`, `Professor`, `University`
   - 例如：如果文本涉及商业事件，可以有 `Company`, `CEO`, `Employee`

**为什么需要兜底类型**：
- 文本中会出现各种人物，如"中小学教师"、"路人甲"、"某位网友"
- 如果没有专门的类型匹配，他们应该被归入 `Person`
- 同理，小型组织、临时团体等应该归入 `Organization`

**具体类型的设计原则**：
- 从文本中识别出高频出现或关键的角色类型
- 每个具体类型应该有明确的边界，避免重叠
- description 必须清晰说明这个类型和兜底类型的区别

### 2. 关系类型设计

- 数量：6-10个
- 关系应该反映社媒互动中的真实联系
- 确保关系的 source_targets 涵盖你定义的实体类型
- **优先采用调研关系taxonomy**：当语义吻合时，优先用 `ALLY_OF`、`OPPOSES`、`COMPETES_WITH`、`REGULATES`、`DEPENDS_ON`、`PARTNERS_WITH`、`INFLUENCES` 这套类型名，使本体边类型与已注入图谱的角色关系图对齐（便于 typed 检索）。
- 关系可带属性：推荐 `sentiment`（极性）、`strength`（强度）、`since_date`（起始日）、`basis`（依据），让边可被 typed 过滤检索。

### 3. 属性设计

- 每个实体类型1-3个关键属性
- **注意**：属性名不能使用 `name`、`uuid`、`group_id`、`created_at`、`summary`（这些是系统保留字）
- 推荐使用：`full_name`, `title`, `role`, `position`, `location`, `description` 等
- 对「会决策/发声」的主体，推荐补充能驱动智能体行为的属性：`role`、`stance`（立场）、`influence_tier`（影响力档位）、`motivation`/`goals`（动机/目标）、`interests`（关注议题）。
- **对能动主体（actor/collective），强烈建议加一个 `aliases` 属性**（该主体的别名/简称/外文名列表，如「CCP」「Beijing」之于「Government of the People's Republic of China」）。抽取时若模型据研究档案填出该属性，会话检索的实体解析（entity resolution）能据此把同一真实主体的多个别名表面形合并为一个图节点——避免「China」「CCP」「Beijing」「MOFCOM」被误判为 4 个不同实体，挤占主阵容（main-cast）席位。即使模型此次没填，图谱构建阶段仍会用 actors.json 的 aliases 字段做兜底合并（不依赖此属性），故此建议是锦上添花，不是强制项。

## 实体类型参考

**个人类（具体）**：
- Student: 学生
- Professor: 教授/学者
- Journalist: 记者
- Celebrity: 明星/网红
- Executive: 高管
- Official: 政府官员
- Lawyer: 律师
- Doctor: 医生

**个人类（兜底）**：
- Person: 任何自然人（不属于上述具体类型时使用）

**组织类（具体）**：
- University: 高校
- Company: 公司企业
- GovernmentAgency: 政府机构
- MediaOutlet: 媒体机构
- Hospital: 医院
- School: 中小学
- NGO: 非政府组织

**组织类（兜底）**：
- Organization: 任何组织机构（不属于上述具体类型时使用）

## 关系类型参考

- WORKS_FOR: 工作于
- STUDIES_AT: 就读于
- AFFILIATED_WITH: 隶属于
- REPRESENTS: 代表
- REGULATES: 监管
- REPORTS_ON: 报道
- COMMENTS_ON: 评论
- RESPONDS_TO: 回应
- SUPPORTS: 支持
- OPPOSES: 反对
- COLLABORATES_WITH: 合作
- COMPETES_WITH: 竞争
"""


# EXECPLAN2 I-1-3: 领域自适应本体模板。社交舆论事件之外（市场冲击、地缘、监管、产品发布等）
# 用学生/教授/媒体那套固定模板会丢失信号；general_forecast 让类型预算与兜底策略随真实
# central_question / actor 类型分布而定，并鼓励产出可供 typed 检索过滤的边/实体属性
# （sentiment / strength / since_date / influence_tier / sector）。该模板需 opt-in，默认仍用
# social_opinion，保证现有行为逐字节不变。
ONTOLOGY_GENERAL_FORECAST_PROMPT = """你是一个专业的知识图谱本体设计专家。你的任务是分析给定的预测问题、研究材料与角色阵容，设计**贴合该预测领域**的实体类型和关系类型，用于多智能体推演与结构化预测。

**重要：你必须输出有效的JSON格式数据，不要输出任何其他内容。**

## 核心任务背景

我们正在围绕一个具体的**预测问题（central question）**构建知识图谱与推演系统。推演是一个**随时间演化的多主体世界**：每个能动主体在每个日历时段做出有代价、有约束、有时滞的真实行动（政策/投资/结盟/诉讼/施压/观望），世界状态随之改变并反馈给所有主体。因此能动实体类型要体现其**行动杠杆、决策权与约束**，而非只体现「会发声」。该问题可能属于任意领域：
- 市场/资产价格走势（如某资产、汇率、商品价格在某时点的区间）
- 地缘政治/政策（如某项谈判、选举、制裁、监管裁决的结果）
- 产品/技术发布与采用（如某产品能否如期发布、市场反应、份额变化）
- 社会舆论事件（如某争议事件的舆论走向与各方反应）
- 企业/行业事件（如并购、财报、诉讼、供应链中断的后果）

实体必须是与该预测问题相关的、现实中真实存在的**主体**（可以决策、发声、施加影响）：

**可以是**：
- 具体的个人（决策者、当事人、专家、意见领袖、分析师等）
- 公司、企业、金融机构、行业参与者
- 组织机构（监管机构、政府部门、行业协会、NGO、智库等）
- 媒体机构、平台
- 国家/经济体（当问题涉及地缘或宏观时）
- 市场/资产/产品（当它们是该预测问题的核心客体且需要被追踪时）

**不可以是**：
- 抽象概念（如"风险"、"情绪"、"趋势"）
- 纯主题/话题（如"通胀"、"AI 监管"）——除非作为可追踪的具体客体出现
- 观点/态度（如"看多方"、"反对者"）

## 输出格式

请输出JSON格式，包含以下结构：

```json
{
    "entity_types": [
        {
            "name": "实体类型名称（英文，PascalCase）",
            "description": "简短描述（英文，不超过100字符）",
            "attributes": [
                {
                    "name": "属性名（英文，snake_case）",
                    "type": "text",
                    "description": "属性描述"
                }
            ],
            "examples": ["示例实体1", "示例实体2"]
        }
    ],
    "edge_types": [
        {
            "name": "关系类型名称（英文，UPPER_SNAKE_CASE）",
            "description": "简短描述（英文，不超过100字符）",
            "source_targets": [
                {"source": "源实体类型", "target": "目标实体类型"}
            ],
            "attributes": [
                {"name": "属性名（英文，snake_case）", "type": "text", "description": "属性描述"}
            ]
        }
    ],
    "analysis_summary": "对预测问题与领域的简要分析说明（中文）"
}
```

## 设计指南（极其重要！）

### 1. 实体类型设计 - 领域自适应

- **数量要求：根据领域复杂度设计 6-10 个实体类型，不要超过 10 个。** 类型数量应贴合下方"角色阵容统计"反映的真实主体构成，而非凑满固定数目。
- **优先具体、可区分的领域类型**：从预测问题与研究材料中识别高频/关键的主体类别，为它们设计边界清晰、互不重叠的类型（如金融领域的 `CentralBank`/`Investor`/`Regulator`，地缘领域的 `NationState`/`Coalition`，产品领域的 `Vendor`/`Competitor`/`Product`）。
- **兜底类型按需引入（不再强制）**：仅当角色阵容中确实出现"无法归入任何具体类型的自然人 / 组织"时，才加入 `Person` / `Organization` 兜底类型；若领域无此需要（如纯市场/资产问题），可不设兜底类型，把预算留给更具区分度的领域类型。
- **属性应服务于检索与画像**：为关键实体类型设计 1-3 个可被下游过滤/排序的属性，例如 `influence_tier`（高/中/低影响力档位）、`sector`（所属行业/板块）、`jurisdiction`（管辖区）、`role`、`stance`。

### 2. 关系类型设计 - 覆盖领域动态并带预测可用属性

- 数量：6-10 个，覆盖该领域真实的相互作用（如 `REGULATES`/`COMPETES_WITH`/`DEPENDS_ON`/`SUPPLIES`/`INFLUENCES`/`HOLDS_STAKE_IN`）。
- **优先复用调研关系taxonomy**：语义吻合时优先采用 `ALLY_OF`、`OPPOSES`、`COMPETES_WITH`、`REGULATES`、`DEPENDS_ON`、`PARTNERS_WITH`、`INFLUENCES`，使本体边类型与已注入图谱的角色关系图对齐（typed 检索更准）；无合适类型时再自定义领域专属边名。
- **因果/机制边（对预测高价值，强烈推荐）**：当领域存在传导机制时，加入 `CAUSES`/`ENABLES`/`CONSTRAINS`/`TRIGGERS`/`ACCELERATES` 这类因果边类型（family=causal），并尽量带 `sign`/`lag`/`strength` 属性——它们刻画"冲击如何传导到结果"，是把图谱从索引升级为传导模型的关键，比"谁认识谁"更能驱动预测。
- 确保 source_targets 连接你定义的实体类型。
- **为关系附带对预测有判别力的属性**（强烈推荐），例如：
  - `sentiment`: 关系的方向性态度（positive/negative/neutral）
  - `strength`: 关系强度（high/medium/low）
  - `since_date`: 关系起始时间（如可考）
  这些属性会被下游 typed 检索用于过滤与排序，请尽量为关键关系类型给出。

### 3. 属性命名约束

- **属性名不能使用 `name`、`uuid`、`group_id`、`created_at`、`summary`、`name_embedding`（系统保留字）。**
- 一律使用英文 snake_case；推荐：`full_name`、`influence_tier`、`sector`、`jurisdiction`、`sentiment`、`strength`、`since_date` 等。

请严格依据下方提供的「预测问题」「角色阵容统计」「研究材料」来取舍类型，使本体真正贴合该预测领域。
"""


# EXECPLAN2 I-1-3: 模板注册表。键即 Config.ONTOLOGY_TEMPLATE 的取值；默认 social_opinion =
# 今日完全一致的提示词，新领域显式 opt-in 到 general_forecast。
ONTOLOGY_TEMPLATES: Dict[str, str] = {
    "social_opinion": ONTOLOGY_SYSTEM_PROMPT,
    "general_forecast": ONTOLOGY_GENERAL_FORECAST_PROMPT,
}

DEFAULT_ONTOLOGY_TEMPLATE = "social_opinion"


# ============================================================================
# ONTOLOGY（CLAUDE §12.2 / CODEX Step 2-3 / GEMINI §5）：富本体 schema 附录。
# ----------------------------------------------------------------------------
# 设计要点：让 LLM 在生成实体/边类型时**额外**标注分类元数据，使下游能区分
# 「能动 agent」与「报道者/概念/资源」、并让边带家族/价/方向语义——而不破坏
# set_ontology 依赖的核心键（entity: name/description/attributes/examples；
# edge: name/description/source_targets/attributes）。
#
# 关键：这两段附录只在 getattr(Config,'ONTOLOGY_RICH_SCHEMA',True) 为真时被
# 拼接到对应基础提示词之后；旗标关闭时，发往 LLM 的 system_prompt 与产出 schema
# 逐字节等于今日，新增字段纯属附加（additive）元数据。
#
# archetype 取值集与 actors.py 的 ENTITY_ARCHETYPES 契约一致：
#   actor / collective / institution_rule / asset_object / event / signal /
#   claim_narrative / constraint_resource / place_jurisdiction / source / scenario
# ============================================================================
ONTOLOGY_RICH_SCHEMA_ADDENDUM = """

## 富本体分类元数据（附加要求，务必输出）

除上述核心字段外，请为**每个 entity_type** 额外标注以下分类元数据（作为附加键写入同一对象，不要改动核心键 name/description/attributes/examples 的结构）：

- `archetype`: 该类型的本体原型，必须取自——`actor`（能决策/发声的真实主体）、`collective`（派系/群体/联盟）、`institution_rule`（制度/规则/法律）、`asset_object`（资产/产品/标的客体）、`event`（事件）、`signal`（指标/信号）、`claim_narrative`（叙事/主张）、`constraint_resource`（约束/资源）、`place_jurisdiction`（地点/管辖区）、`source`（信息来源/被引用的媒体或报告）、`scenario`（情景）。
- `simulation_tier`: 默认模拟层级（整数）：1=核心决策者，2=利益相关方/派系，3=被动信息源（如被引用的媒体/报告/分析），4=抽象概念/资源/标的。
- `role_class`: 默认角色类（可选）：`principal`（主事方）、`arbiter`（裁决方）、`stakeholder`（利益相关方）、`amplifier`（放大/传播方）、`intermediary`（中介方）。
- `selection_rule`: 一句话判定规则，说明何种实体应归入此类型（用于抽取阶段消歧）。
- `anti_examples`: 反例数组，列出**不应**被实例化为此类型的对象。**特别强调**：被引用的媒体/报刊/榜单/数据库是 `source`（archetype=source, tier=3），不是能动 actor——除非它本身就是推动结局的当事方，否则不要把它设成一个独立的能动实体类型。
- `agency_class`（仅 archetype=actor/collective 需填）：该类主体在演化世界中真实握有的**行动杠杆类别**，必须取自——`sovereign_government`（主权政府/部委）、`regulator_agency`（监管/执法机构）、`legislature`（立法机关/议员）、`central_bank`、`judiciary`、`political_party`、`firm`（企业）、`state_owned_enterprise`、`financial_institution`、`industry_coalition`（行业协会/联盟）、`labor_union`、`ngo_advocacy`、`international_org`、`research_institution`、`individual_leader`（以个人身份行动的领导者/意见人物）、`public_collective`（公众/消费者/选民群体）、`media_outlet`。
- `levers`（可选，≤5 项）：该类主体可以采取的典型可执行动作（如「加征关税」「开启调查」「追加资本开支」「罢工」），供多智能体推演生成**有约束、有代价、有时滞**的行动选项。

为**每个 edge_type** 额外标注：
- `family`: 边的语义家族，取自——`alignment`（结盟/支持，正向）、`antagonism`（对抗/制裁/批评，负向）、`economic`（供应/出资/持股/消费，交易性）、`governance`（监管/裁决）、`dependency`（依赖）、`influence`（影响）、`information`（报道/披露）、`causal`（因果/机制传导，如 CAUSES/ENABLES/CONSTRAINS/TRIGGERS/ACCELERATES，有向）。
- `valence`: 边的价，取自——`allied`、`adversarial`、`transactional`、`directional`、`neutral`。
- `direction_semantics`: 一句话说明该边方向的含义（source 与 target 谁对谁，如「source 供应 target」「source 监管 target」），避免方向被读反。

这些元数据是**附加**的：核心键结构保持不变，下游消费照旧；新增键让被引用来源不被误当能动 actor、并让边携带价/家族/方向以供检索与推演。
"""


# ============================================================================
# ACTOR-CAST DISCIPLINE：主角色纪律提示块（动态拼接，随 Config 旗标取值）。
# 任何真实预测模拟都应蒸馏到 ≤ACTOR_CAST_MAX（默认 20）个 main actors——只有其
# 决策/行动会**因果性影响预测结果**的主体才该成为模拟 agent；媒体机构/记者/评论员/
# 分析师/智库是 context（信息来源，archetype=source / tier 3），绝不是能动 actor。
# 该块指导本体 LLM 把实体类型预算聚焦在 main actors 上、并把媒体/观察者类型正确
# 归为 source，从而让下游 agent 准入门（is_agent_eligible）一致地把它们挡在池外。
# ACTOR_CAST_MAX<=0 且 ACTOR_EXCLUDE_MEDIA=false 时返回 ""（提示词与旧行为一致）。
# ============================================================================
def _actor_cast_discipline_block() -> str:
    cap = 20
    exclude_media = True
    try:
        if _Config is not None:
            cap = int(getattr(_Config, "ACTOR_CAST_MAX", 20) or 0)
            exclude_media = bool(getattr(_Config, "ACTOR_EXCLUDE_MEDIA", True))
    except (TypeError, ValueError):
        cap = 20
    parts: List[str] = []
    if cap > 0:
        parts.append(
            f"- 本体服务于一个多智能体预测模拟，模拟的 agent 阵容会被硬性收敛到 **≤{cap} 个主角色"
            "（main actors）**：只有「其决策与行动会**因果性影响预测结果**」的真实主体才会被实例化为"
            "模拟 agent。设计实体类型与 examples 时请聚焦这些 main actors（核心决策者与关键利益相关方），"
            "不要为仅被顺带提及、与结果无因果关联的边缘实体设计专属类型或示例。"
        )
    if exclude_media:
        parts.append(
            "- **媒体机构、记者、评论员、分析师、民调机构、智库等「报道/评论方」是 context（信息来源），"
            "不是能动 actor**：它们不决策、不推动结局，只报道结局。若确需为它们设实体类型，必须把该类型"
            "标注为 archetype=source、simulation_tier=3（被动信息源），且不要把媒体实体列为能动主体类型的"
            "examples——除非该媒体本身就是推动结局的当事方（此时按当事方建模并说明理由）。"
        )
    if not parts:
        return ""
    return "\n\n## 主角色纪律（actor-cast discipline，务必遵守）\n\n" + "\n".join(parts) + "\n"


# F1: 自动选模板用的双语关键词集。命中"公众反应/舆情/民意/社交媒体"语义即判定为
# social_opinion，否则归入领域自适应的 general_forecast。仅在 Config.ONTOLOGY_AUTO_SELECT 打开
# 且调用方未显式指定模板时才生效；默认（旗标关闭）路径逐字节不变。
# ONT-11: 单词级触发词（bare 'sentiment'/'opinion'/'情绪'/'观点'）在市场/地缘问题里极常见
# （"investor sentiment"、"expert opinion"），任一命中就会把 10 类社媒模板强套到非社媒预测
# ——恰是 ONTO-4 要防的反向误路由。故只保留"公众/舆论"限定的双词组合，弃用裸单词。
SOCIAL_OPINION_KEYWORDS = (
    # 英文
    "public reaction", "public opinion", "public sentiment", "social media",
    "backlash", "outrage", "controversy", "viral", "netizen",
    "reputation", "public perception", "trending", "hashtag",
    # 中文
    "舆情", "民意", "社交媒体", "公众反应", "公众舆论", "舆论", "公众情绪",
    "争议", "热搜", "网友", "口碑", "声誉", "民众", "网络舆论",
)


# ============================================================================
# ONTOLOGY 归一化（CODEX Step 3）：当 LLM 漏标 archetype / edge family / valence 时，
# 据类型名 / 边名确定性补全。映射保守、纯字符串子串匹配，无副作用；仅在
# ONTOLOGY_RICH_SCHEMA 为真时被 _normalize_rich_schema 调用，旗标关闭时整段不触达。
# ----------------------------------------------------------------------------

# entity_type.name（小写）子串 → 推断的 archetype。命中第一个即止；都不中 → "actor"
# （与 actors.entity_archetype 的缺省一致：信号不足时按能动主体处理，不误降级）。
# 顺序重要：先判更专的（source/media/event/...），再落到 person/org 这类宽泛能动主体。
_ARCHETYPE_NAME_HINTS = (
    # 信息源 / 被引用媒体 / 报告 → source（tier 3，被动信息源，绝不当能动 actor）
    (("source", "outlet", "press", "newspaper", "newswire", "publication",
      "report", "dataset", "database", "index", "ranking", "wire",
      "媒体", "报刊", "通讯社", "来源", "信源", "榜单", "数据库"), "source"),
    # 制度 / 规则 / 法律 / 政策 → institution_rule
    (("rule", "law", "regulation", "policy", "statute", "treaty", "framework",
      "mandate", "制度", "规则", "法律", "法规", "政策", "条约"), "institution_rule"),
    # 事件 → event
    (("event", "incident", "summit", "election", "meeting", "hearing",
      "事件", "峰会", "选举", "听证", "会议"), "event"),
    # 指标 / 信号 → signal
    (("signal", "indicator", "metric", "price", "rate", "index_value",
      "指标", "信号", "价格", "利率"), "signal"),
    # 叙事 / 主张 → claim_narrative
    (("narrative", "claim", "rumor", "rumour", "story", "thesis",
      "叙事", "主张", "传闻", "说法"), "claim_narrative"),
    # 约束 / 资源 → constraint_resource
    (("resource", "constraint", "supply", "capacity", "reserve", "budget",
      "资源", "约束", "产能", "储备", "预算"), "constraint_resource"),
    # 地点 / 管辖区 / 国家经济体 → place_jurisdiction
    # 注意：不含裸词 "state" —— 子串匹配下它会命中 HeadOfState / SecretaryOfState 等
    # 常见的能动 actor 类型名（2026-07-03 live-surfaced：一次真实预测跑里 HeadOfState
    # 被误判为 place_jurisdiction，导致该类型的图节点在 tier 推断中被排出 agent 池）。
    # "nation"/"country"/"jurisdiction" 已覆盖同样的国家/地区语义，无需再靠泛化的 "state"。
    (("place", "jurisdiction", "region", "country", "nation", "nation_state",
      "nationstate", "city", "market_place", "地点", "管辖", "地区", "国家", "城市"),
     "place_jurisdiction"),
    # 情景 → scenario
    (("scenario", "case", "情景", "情境"), "scenario"),
    # 资产 / 产品 / 标的客体 → asset_object
    (("asset", "product", "commodity", "currency", "security", "token",
      "instrument", "device", "资产", "产品", "商品", "货币", "标的"),
     "asset_object"),
    # 群体 / 派系 / 联盟 / 阵营 → collective（仍是能动，tier 2）
    (("collective", "coalition", "alliance", "faction", "bloc", "group",
      "union", "community", "fans", "联盟", "派系", "阵营", "群体", "工会",
      "团体", "粉丝"), "collective"),
)

# edge_type.name（大写）= REL_TYPE → (family, valence)。复用 actors._REL_TYPE_VALENCE
# 的四簇划分，并细分出 governance/dependency/influence/information 家族，使 family 比
# valence 更细。LLM 漏标 family/valence 时据此补全；未知边名 → ("other", "neutral")。
_EDGE_FAMILY_VALENCE = {
    # 结盟（正向）
    "ALLY_OF": ("alignment", "allied"),
    "SUPPORTS": ("alignment", "allied"),
    "PARTNERS_WITH": ("alignment", "allied"),
    "ENDORSES": ("alignment", "allied"),
    # 对抗（负向）
    "OPPOSES": ("antagonism", "adversarial"),
    "COMPETES_WITH": ("antagonism", "adversarial"),
    "SANCTIONS": ("antagonism", "adversarial"),
    "CRITICIZES": ("antagonism", "adversarial"),
    "LITIGATES_AGAINST": ("antagonism", "adversarial"),
    # 经济（交易性）
    "SUPPLIES": ("economic", "transactional"),
    "CUSTOMER_OF": ("economic", "transactional"),
    "FUNDS": ("economic", "transactional"),
    "INVESTS_IN": ("economic", "transactional"),
    "BACKS": ("economic", "transactional"),
    "OWNS": ("economic", "transactional"),
    "CONSUMES": ("economic", "transactional"),
    # 治理 / 依赖 / 影响 / 报道（有向、非褒贬）
    "REGULATES": ("governance", "directional"),
    "DEPENDS_ON": ("dependency", "directional"),
    "INFLUENCES": ("influence", "directional"),
    "REPORTS_ON": ("information", "directional"),
    # NEXTSTEPS P3-5：因果/机制家族（有向传导，非褒贬）。把 KG 从索引升级为传导模型。
    "CAUSES": ("causal", "directional"),
    "ENABLES": ("causal", "directional"),
    "CONSTRAINS": ("causal", "directional"),
    "TRIGGERS": ("causal", "directional"),
    "ACCELERATES": ("causal", "directional"),
    "OTHER": ("other", "neutral"),
}


class OntologyGenerator:
    """
    本体生成器
    分析文本内容，生成实体和关系类型定义
    """
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()
    
    @staticmethod
    def _resolve_template(template: Optional[str]) -> str:
        """解析模板名：显式传入 > Config.ONTOLOGY_TEMPLATE > 默认 social_opinion。

        EXECPLAN2 I-1-3：未知模板名一律降级回 social_opinion（保持现有行为），并记录告警。
        """
        name = template
        if not name:
            name = getattr(_Config, "ONTOLOGY_TEMPLATE", DEFAULT_ONTOLOGY_TEMPLATE) if _Config else DEFAULT_ONTOLOGY_TEMPLATE
        name = str(name or DEFAULT_ONTOLOGY_TEMPLATE).strip().lower()
        if name not in ONTOLOGY_TEMPLATES:
            logger.warning(
                "Ontology: unknown template %r, falling back to %r",
                name, DEFAULT_ONTOLOGY_TEMPLATE,
            )
            name = DEFAULT_ONTOLOGY_TEMPLATE
        return name

    @staticmethod
    def _rich_schema_enabled() -> bool:
        """读取 ONTOLOGY_RICH_SCHEMA 旗标（缺失默认 True）。

        本文件不拥有 config.py，仅经 getattr 读取，配置缺失即退回契约默认值，
        保证富本体逻辑可被一处开关，且关闭时整条新增路径不触达。
        """
        return bool(getattr(_Config, "ONTOLOGY_RICH_SCHEMA", True))

    @classmethod
    def _effective_system_prompt(cls, template_name: str) -> str:
        """组装发往 LLM 的 system 提示词。

        ONTOLOGY_RICH_SCHEMA 为真时，把 ONTOLOGY_RICH_SCHEMA_ADDENDUM 追加到所选
        基础模板之后，要求 LLM 额外标注 archetype/simulation_tier/role_class/
        selection_rule/anti_examples（实体）与 family/valence/direction_semantics（边）；
        旗标关闭时返回基础模板**原文**，发往 LLM 的提示词逐字节等于今日。
        """
        base = ONTOLOGY_TEMPLATES[template_name]
        if cls._rich_schema_enabled():
            base = base + ONTOLOGY_RICH_SCHEMA_ADDENDUM
        return base + _actor_cast_discipline_block()

    @staticmethod
    def _auto_select_template(prompt: str, default_template: str) -> str:
        """F1：根据预测问题文本确定性地挑选本体模板。

        命中双语「公众反应 / 舆情 / 民意 / 社交媒体 / 情绪 / 观点」关键词集 → 'social_opinion'；
        否则归入领域自适应的 'general_forecast'。空/非字符串提示返回 default_template，保证无信号
        时不改变行为。该方法纯函数、无副作用，仅在 Config.ONTOLOGY_AUTO_SELECT 打开且调用方未显式
        指定模板时被 generate() 调用。
        """
        text = str(prompt or "").strip().lower()
        if not text:
            return default_template
        if any(kw in text for kw in SOCIAL_OPINION_KEYWORDS):
            return "social_opinion"
        return "general_forecast"

    def generate(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str] = None,
        template: Optional[str] = None,          # EXECPLAN2 I-1-3
        central_question: Optional[str] = None,  # EXECPLAN2 I-1-3
        actors: Optional[Dict[str, Any]] = None  # EXECPLAN2 I-1-3
    ) -> Dict[str, Any]:
        """
        生成本体定义

        Args:
            document_texts: 文档文本列表
            simulation_requirement: 模拟需求描述
            additional_context: 额外上下文
            template: 本体模板名（EXECPLAN2 I-1-3，可选）。缺省读 Config.ONTOLOGY_TEMPLATE，
                再缺省为 'social_opinion'（与现有行为逐字节一致）。'general_forecast' 为领域自适应模板。
            central_question: 预测核心问题（可选）。所有模板及回退请求均保留此上下文。
            actors: actors.json 顶层对象（可选）。所有模板保留类型分布直方图；
                general_forecast 据此决定是否引入 Person/Organization 兜底类型。

        Returns:
            本体定义（entity_types, edge_types等）
        """
        # F1: 模板自动选择（默认关闭）。仅当 Config.ONTOLOGY_AUTO_SELECT 打开且调用方未显式传入
        # template 时，才根据预测问题文本挑选模板；否则尊重显式覆盖 / 已配置的 ONTOLOGY_TEMPLATE。
        # 旗标关闭（默认）时此分支不进入，template 原样进 _resolve_template，行为逐字节不变。
        effective_template = template
        if effective_template is None and getattr(_Config, "ONTOLOGY_AUTO_SELECT", False):
            classifier_prompt = central_question or simulation_requirement or ""
            effective_template = self._auto_select_template(classifier_prompt, DEFAULT_ONTOLOGY_TEMPLATE)
            logger.info(
                "Ontology: ONTOLOGY_AUTO_SELECT on, auto-selected template %r from central question.",
                effective_template,
            )

        # EXECPLAN2 I-1-3: 解析模板（默认 social_opinion=现有行为）。
        # ONTOLOGY: 富本体旗标开启时在所选模板后追加分类元数据要求；关闭时逐字节等于今日。
        template_name = self._resolve_template(effective_template)
        system_prompt = self._effective_system_prompt(template_name)

        # 构建用户消息
        user_message = self._build_user_message(
            document_texts,
            simulation_requirement,
            additional_context,
            template=template_name,            # EXECPLAN2 I-1-3
            central_question=central_question,  # EXECPLAN2 I-1-3
            actors=actors,                      # EXECPLAN2 I-1-3
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        # 调用LLM
        # ONTO-5: max_tokens 4096→8192。富本体 schema 要求每个 entity/edge 额外标注
        # archetype/simulation_tier/family/valence 等元数据，10 类实体 + 10 类边的 JSON 体积
        # 已逼近 4096 token 上限，截断会产出非法 JSON 触发空本体回退。提到 8192 给足裕量。
        result = self.llm_client.chat_json(
            messages=messages,
            temperature=0.3,
            max_tokens=8192
        )

        # 验证和后处理
        # EXECPLAN2 I-1-3: 把模板与 actors 透传给校验器，让 general_forecast 走"按需兜底"策略，
        # social_opinion 仍走"强制 Person/Organization 兜底"的现有路径。
        result = self._validate_and_process(result, template=template_name, actors=actors)

        # EXECPLAN2 I-1-3: schema 违例（领域模板未产出任何可用实体类型）时，回退到默认
        # social_opinion 模板重跑一次，保证不会因新模板失灵而把空本体喂给建图阶段。
        if template_name != DEFAULT_ONTOLOGY_TEMPLATE and not result.get("entity_types"):
            logger.warning(
                "Ontology: template %r produced no valid entity types; "
                "falling back to %r template.",
                template_name, DEFAULT_ONTOLOGY_TEMPLATE,
            )
            fallback_message = self._build_user_message(
                document_texts,
                simulation_requirement,
                additional_context,
                template=DEFAULT_ONTOLOGY_TEMPLATE,
                central_question=central_question,
                actors=actors,
            )
            fallback_result = self.llm_client.chat_json(
                messages=[
                    {"role": "system", "content": self._effective_system_prompt(DEFAULT_ONTOLOGY_TEMPLATE)},
                    {"role": "user", "content": fallback_message},
                ],
                temperature=0.3,
                max_tokens=8192,  # ONTO-5: 与主调用一致，避免回退路径再次因截断产出空本体
            )
            result = self._validate_and_process(
                fallback_result, template=DEFAULT_ONTOLOGY_TEMPLATE, actors=actors
            )

        return result
    
    # ONTO-3: 传给 LLM 的文本最大长度 5万→12万字。本体分析需要"看全角色阵容"——50000 字常把
    # 后半部分出现的关键 actor/关系整段截掉，导致类型覆盖不全。12万字配合下方 head+middle+tail
    # 采样，让超长文档的首/中/尾都进入分析视野，而非只读前 N 字。仅影响传给 LLM 的内容，不影响图谱构建。
    MAX_TEXT_LENGTH_FOR_LLM = 120000

    @staticmethod
    def _sample_head_middle_tail(text: str, cap: int) -> str:
        """ONTO-3: 超长文本按 head(50%)+middle(25%)+tail(25%) 采样，替代纯首部截断。

        纯 ``text[:cap]`` 会丢弃文档后半全部信号；本体分析尤其需要尾部出现的角色/关系。
        这里在 head 与 tail 之间各保留一段，使首/中/尾都被采样到。``cap`` 极小（<=3）时
        退化为简单首部切片，保证永不抛异常。纯函数、确定性。
        """
        if cap <= 0:
            return ""
        if len(text) <= cap:
            return text
        # 预留分隔标记的开销后再分配三段预算。
        head_n = cap // 2
        mid_n = cap // 4
        tail_n = cap - head_n - mid_n
        if mid_n <= 0 or tail_n <= 0:
            return text[:cap]
        head = text[:head_n]
        mid_start = (len(text) - mid_n) // 2
        middle = text[mid_start:mid_start + mid_n]
        tail = text[-tail_n:]
        return (
            f"{head}\n\n…(中段节选)…\n\n{middle}\n\n…(尾段节选)…\n\n{tail}"
        )
    
    @staticmethod
    def _actor_type_histogram(actors: Optional[Dict[str, Any]]) -> "Counter":
        """统计 actors.json 中 actor 的 type 分布（EXECPLAN2 I-1-3）。

        用于让 general_forecast 模板的类型预算贴合真实角色构成，并据以判断是否需要
        Person/Organization 兜底。容错任意脏数据：actors 非 dict / 无 actors 列表时返回空。
        """
        hist: "Counter" = Counter()
        if not isinstance(actors, dict):
            return hist
        rows = actors.get("actors")
        if not isinstance(rows, list):
            return hist
        for r in rows:
            if not isinstance(r, dict):
                continue
            typ = str(r.get("type", "") or "").strip()
            if typ:
                hist[typ] += 1
        return hist

    def _build_user_message(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str],
        template: str = DEFAULT_ONTOLOGY_TEMPLATE,  # EXECPLAN2 I-1-3
        central_question: Optional[str] = None,     # EXECPLAN2 I-1-3
        actors: Optional[Dict[str, Any]] = None     # EXECPLAN2 I-1-3
    ) -> str:
        """构建用户消息"""

        # Every report/document string is research evidence, never prompt
        # control. Sanitize each document independently so one malicious line
        # does not erase safe neighbouring reports, then delimit the combined
        # evidence block before it reaches the model.
        safe_documents = []
        for text in document_texts:
            normalized = unicodedata.normalize("NFKC", str(text or ""))
            safe_documents.append(sanitize_untrusted_research_text(
                normalized,
                # Sanitize the complete document before sampling. Replacement
                # markers can expand short unsafe lines, so reserve per-line
                # space rather than truncating the evidence before the sampler.
                max_chars=max(1, len(normalized) + (normalized.count("\n") + 1) * 64),
            ))
        combined_text = "\n\n---\n\n".join(safe_documents)
        original_length = len(combined_text)

        # ONTO-3: 文本超长时按 head+middle+tail 采样（仅影响传给LLM的内容，不影响图谱构建）
        if len(combined_text) > self.MAX_TEXT_LENGTH_FOR_LLM:
            combined_text = self._sample_head_middle_tail(combined_text, self.MAX_TEXT_LENGTH_FOR_LLM)
            combined_text += (
                f"\n\n...(原文共{original_length}字，已采样首/中/尾约"
                f"{self.MAX_TEXT_LENGTH_FOR_LLM}字用于本体分析)..."
            )

        requirement_block = delimit_untrusted_research_text(
            "simulation requirement",
            simulation_requirement,
            max_chars=12_000,
        )
        documents_block = delimit_untrusted_research_text(
            "research documents",
            combined_text,
            max_chars=self.MAX_TEXT_LENGTH_FOR_LLM + 400,
        )
        message = f"""## 模拟需求

{requirement_block}

## 文档内容

{documents_block}
"""

        if additional_context:
            additional_block = delimit_untrusted_research_text(
                "additional actor context",
                additional_context,
                max_chars=16_000,
            )
            message += f"""
## 额外说明

{additional_block}
"""

        # EXECPLAN2 I-1-3: general_forecast 模板下注入领域自适应规则（central_question + 角色
        # 类型直方图驱动类型预算与兜底策略）；social_opinion 也保留问题/类型上下文，
        # 但继续使用自身的类型预算规则。
        if template == "general_forecast":
            message += self._general_forecast_rules(central_question, actors)
        else:
            message += self._forecast_context(central_question, actors)
            message += """
请根据以上内容，设计适合社会舆论模拟的实体类型和关系类型。

**必须遵守的规则**：
1. 必须正好输出10个实体类型
2. 最后2个必须是兜底类型：Person（个人兜底）和 Organization（组织兜底）
3. 前8个是根据文本内容设计的具体类型
4. 所有实体类型必须是现实中可以发声的主体，不能是抽象概念
5. 属性名不能使用 name、uuid、group_id 等保留字，用 full_name、org_name 等替代
"""

        return message

    def _forecast_context(
        self,
        central_question: Optional[str],
        actors: Optional[Dict[str, Any]],
    ) -> str:
        """Preserve question and observed actor types across templates/fallback."""
        parts: List[str] = ["\n"]
        cq = delimit_untrusted_research_text(
            "central forecast question",
            central_question,
            max_chars=4_000,
        )
        if cq:
            parts.append(f"## 预测核心问题\n\n{cq}\n")

        hist = self._actor_type_histogram(actors)
        if hist:
            ranked = ", ".join(
                f"{sanitize_untrusted_research_text(typ, max_chars=160)}×{n}"
                for typ, n in hist.most_common()
            )
            ranked = delimit_untrusted_research_text(
                "actor type histogram",
                ranked,
                max_chars=4_000,
            )
            parts.append(
                "## 角色阵容统计（深度研究实证的 actor 类型分布）\n\n"
                f"{ranked}\n\n"
                "请在所选模板的类型预算内覆盖上述真实角色类型。\n"
            )

        return "".join(parts)

    def _general_forecast_rules(
        self,
        central_question: Optional[str],
        actors: Optional[Dict[str, Any]],
    ) -> str:
        """Render the shared forecast context and domain-adaptive schema rules."""
        parts = [self._forecast_context(central_question, actors)]

        parts.append(
            "请根据以上内容，设计**贴合该预测领域**的实体类型和关系类型。\n\n"
            "**必须遵守的规则**：\n"
            "1. 实体类型 6-10 个，数量贴合角色阵容，绝不超过 10 个\n"
            "2. 仅当角色阵容确有无法归入具体类型的自然人/组织时，才加入 Person/Organization 兜底类型；纯客体型问题可不设兜底\n"
            "3. 实体类型必须是与预测问题相关的现实主体（个人/组织/机构/国家/可追踪客体），不能是抽象概念\n"
            "4. 为关键实体类型设计可供检索过滤的属性（如 influence_tier、sector、jurisdiction）\n"
            "5. 为关键关系类型附带预测可用属性（如 sentiment、strength、since_date）\n"
            "6. 属性名不能使用 name、uuid、group_id、created_at、summary、name_embedding 等保留字\n"
        )
        return "".join(parts)
    
    # 兜底类型识别用：actor.type 文本是否表示「自然人」/「组织机构」（EXECPLAN2 I-1-3）。
    _PERSON_TYPE_HINTS = ("person", "individual", "people", "人", "个人")
    _ORG_TYPE_HINTS = (
        "organization", "organisation", "org", "company", "corp", "agency",
        "government", "media", "platform", "institution", "ngo", "association",
        "机构", "组织", "公司", "企业", "政府", "媒体", "平台",
    )

    def _fallback_needs_from_actors(self, actors: Optional[Dict[str, Any]]) -> "tuple":
        """根据 actor 类型直方图判断是否需要 Person / Organization 兜底（EXECPLAN2 I-1-3）。

        actor 的 type 文本命中"自然人"语义 → 需要 Person 兜底；命中"组织机构"语义 → 需要
        Organization 兜底。ONT-5：必须区分「数据缺失」与「实证无人/无组织」——actors.json
        丢失/畸形/空阵容（恰是研究交接降级的失败模式）不是"阵容里没有自然人"的证据，此时
        退回旧的安全行为（两个兜底都注入），否则图谱抽取会把报告里的人/组织降级为无类型
        泛实体，雪上加霜。仅当**非空阵容确实存在**却全是具体客体类型时，才允许 (False, False)。
        """
        rows = actors.get("actors") if isinstance(actors, dict) else None
        if not isinstance(rows, list) or not rows:
            return (True, True)  # 数据缺失 → legacy-safe 兜底
        hist = self._actor_type_histogram(actors)
        if not hist:
            return (True, True)  # 阵容存在但 type 字段全不可用 → 同样按降级处理
        need_person = False
        need_org = False
        for typ in hist:
            low = str(typ).strip().lower()
            if any(h in low for h in self._PERSON_TYPE_HINTS):
                need_person = True
            if any(h in low for h in self._ORG_TYPE_HINTS):
                need_org = True
        return (need_person, need_org)

    @staticmethod
    def _sanitize_reserved_attrs(type_defs: List[Dict[str, Any]]) -> None:
        """就地把实体/边类型属性里的保留字属性名改写为 entity_<name>（EXECPLAN2 I-1-3）。

        与 graph_builder.safe_attr_name 的 RESERVED_NAMES 对齐，使本体中描述的属性名与图谱中
        实际可过滤的字段名一致，避免 typed 检索引用到不存在的字段。
        """
        for td in type_defs:
            if not isinstance(td, dict):
                continue
            attrs = td.get("attributes")
            if not isinstance(attrs, list):
                continue
            for attr in attrs:
                if not isinstance(attr, dict):
                    continue
                a_name = attr.get("name")
                if isinstance(a_name, str) and a_name.lower() in RESERVED_ATTR_NAMES:
                    attr["name"] = f"entity_{a_name}"

    @staticmethod
    def _infer_archetype_from_name(type_name: str) -> str:
        """据 entity_type 名（子串匹配 _ARCHETYPE_NAME_HINTS）推断 archetype。

        命中第一个提示组即返回对应 archetype；都不中 → "actor"（与 actors.entity_archetype
        的缺省一致：信号不足时按能动主体处理）。纯字符串、确定性、无副作用。
        """
        low = str(type_name or "").strip().lower()
        if not low:
            return "actor"
        for hints, archetype in _ARCHETYPE_NAME_HINTS:
            if any(h in low for h in hints):
                return archetype
        return "actor"

    @classmethod
    def _normalize_rich_schema(cls, result: Dict[str, Any]) -> None:
        """ONTOLOGY 归一化（CODEX Step 3）：就地补全缺失的富本体分类元数据。

        仅在 ONTOLOGY_RICH_SCHEMA 为真时由 _validate_and_process 调用。职责：
        * 实体类型缺 ``archetype`` → 据类型名推断（_infer_archetype_from_name）。
        * 边类型缺 ``family`` / ``valence`` → 据边名（大写）查 _EDGE_FAMILY_VALENCE 推断。

        所有补全均为**附加**键：core 键（name/description/attributes/examples 及
        edge 的 source_targets）一律不动，故 set_ontology 兼容性不受影响。LLM 已显式
        给出（非空）的值一律保留，绝不覆盖——唯一例外是 ONT-6：五个 P3-5 因果边名的
        family/valence 按边名确定性锁定为 ('causal','directional')。``relation_types``
        别名折叠在调用本方法前已完成（见 _validate_and_process 开头），故此处只处理
        规范化后的 edge_types。
        """
        for entity in result.get("entity_types", []):
            if not isinstance(entity, dict):
                continue
            arch = entity.get("archetype")
            if not (isinstance(arch, str) and arch.strip()):
                entity["archetype"] = cls._infer_archetype_from_name(entity.get("name", ""))
            # REFLEXIVE WORLD: agency class for agent archetypes (LLM value kept when valid).
            if str(entity.get("archetype") or "").strip().lower() in ("actor", "collective"):
                klass = entity.get("agency_class")
                try:
                    from .agent_decision import AGENCY_CLASSES, infer_agency_class
                    if not (isinstance(klass, str) and klass.strip().lower() in AGENCY_CLASSES):
                        entity["agency_class"] = infer_agency_class(
                            entity.get("name", ""), entity.get("description", ""),
                            archetype=str(entity.get("archetype") or ""),
                        )
                    else:
                        entity["agency_class"] = klass.strip().lower()
                except Exception:  # noqa: BLE001 — additive metadata only
                    pass

        for edge in result.get("edge_types", []):
            if not isinstance(edge, dict):
                continue
            edge_key = str(edge.get("name", "") or "").strip().upper()
            mapped = _EDGE_FAMILY_VALENCE.get(edge_key)
            # ONT-6: P3-5 因果边名（CAUSES/ENABLES/CONSTRAINS/TRIGGERS/ACCELERATES）的
            # family/valence 由边名确定性锁定。附录枚举曾缺 'causal'，遵循枚举的 LLM 会填成
            # dependency/adversarial 等，而"显式值不覆盖"规则会让因果族在出生时即永久丢失
            # （KG 作为传导模型的信号被毁）。名字键控校正只针对这五个因果边名，其余边的
            # LLM 显式值一律保留不覆盖。
            if mapped is not None and mapped[0] == "causal":
                fam = edge.get("family")
                val = edge.get("valence")
                if (isinstance(fam, str) and fam.strip() and fam.strip().lower() != "causal") or \
                   (isinstance(val, str) and val.strip() and val.strip().lower() != "directional"):
                    logger.info(
                        "Ontology ONT-6: causal edge %r family/valence %r/%r overridden to "
                        "'causal'/'directional' (name-keyed).",
                        edge.get("name"), fam, val,
                    )
                edge["family"], edge["valence"] = mapped
                continue
            fam = edge.get("family")
            val = edge.get("valence")
            need_family = not (isinstance(fam, str) and fam.strip())
            need_valence = not (isinstance(val, str) and val.strip())
            if not (need_family or need_valence):
                continue
            inferred_family, inferred_valence = _EDGE_FAMILY_VALENCE.get(
                edge_key, ("other", "neutral")
            )
            if need_family:
                edge["family"] = inferred_family
            if need_valence:
                edge["valence"] = inferred_valence

    def _validate_and_process(
        self,
        result: Dict[str, Any],
        template: str = DEFAULT_ONTOLOGY_TEMPLATE,  # EXECPLAN2 I-1-3
        actors: Optional[Dict[str, Any]] = None      # EXECPLAN2 I-1-3
    ) -> Dict[str, Any]:
        """验证和后处理结果"""

        # F-3-0: 顶层类型强制。chat_json 直接返回 json.loads 的结果，
        # 合法 JSON 也可能是 list/str/None（顶层数组、字符串、null），此时
        # 下面的 result["entity_types"] = ... 赋值会抛 TypeError，整个本体阶段崩溃。
        if not isinstance(result, dict):
            result = {}

        # ONTOLOGY 归一化（CODEX Step 3）：容忍 ``relation_types`` 作为 ``edge_types`` 的别名。
        # 富 schema 提示词偶尔会让 LLM 用 relation_types 命名关系数组；这里在任何 edge_types
        # 处理之前把它折叠进 edge_types（仅当 edge_types 缺失/为空且 relation_types 是非空 list）。
        # 仅在 ONTOLOGY_RICH_SCHEMA 为真时生效，旗标关闭时此分支不触达、行为逐字节不变。
        if self._rich_schema_enabled():
            alias = result.get("relation_types")
            if isinstance(alias, list) and alias and not result.get("edge_types"):
                result["edge_types"] = alias
                logger.info(
                    "Ontology: folded %d 'relation_types' entr(ies) into 'edge_types' (alias).",
                    len(alias),
                )

        # F-3-0: 集合字段强制为 list。仅做成员检查（"x" not in result）无法
        # 处理 entity_types 被 LLM 返回为 dict/str/null 的情况，后续 for / 切片 /
        # extend / len 全部假设是 list，必须在此统一强制类型。
        if not isinstance(result.get("entity_types"), list):
            result["entity_types"] = []
        if not isinstance(result.get("edge_types"), list):
            result["edge_types"] = []
        if not isinstance(result.get("analysis_summary"), str):
            result["analysis_summary"] = ""

        # F-3-0: 丢弃非 dict 的条目，保证后续 entity["..."] / e["name"] 等访问安全
        result["entity_types"] = [e for e in result["entity_types"] if isinstance(e, dict)]
        result["edge_types"] = [e for e in result["edge_types"] if isinstance(e, dict)]

        # F-3-4: 实体类型按 name 去重（保留首次出现），并丢弃 name 缺失/为空的条目，
        # 避免重复或无名条目占用 10 个类型的预算、把唯一的尾部具体类型挤出去。
        deduped_entities: List[Dict[str, Any]] = []
        seen_entity_names: set = set()
        dropped_for_name: List[str] = []
        for entity in result["entity_types"]:
            name = entity.get("name")
            if not isinstance(name, str) or not name.strip():
                dropped_for_name.append(repr(name))
                continue
            if name in seen_entity_names:
                dropped_for_name.append(name)
                continue
            seen_entity_names.add(name)
            deduped_entities.append(entity)
        if dropped_for_name:
            logger.warning(
                "Ontology: dropped %d entity type(s) with empty/duplicate names: %s",
                len(dropped_for_name), dropped_for_name
            )
        result["entity_types"] = deduped_entities

        # 验证实体类型
        for entity in result["entity_types"]:
            if "attributes" not in entity:
                entity["attributes"] = []
            if "examples" not in entity:
                entity["examples"] = []
            # ONT-3: description 可能被 LLM 显式给成 null/非字符串（MiniMax/JSON 修复路径），
            # .get(...,"") 只兜键缺失，len(None) 会 TypeError 崩掉整个本体阶段——先强制为 str。
            if not isinstance(entity.get("description"), str):
                entity["description"] = ""
            # 确保description不超过100字符
            if len(entity["description"]) > 100:
                entity["description"] = entity["description"][:97] + "..."

        # 验证关系类型
        for edge in result["edge_types"]:
            if "source_targets" not in edge:
                edge["source_targets"] = []
            if "attributes" not in edge:
                edge["attributes"] = []
            # ONT-3: 同实体类型——null/非字符串 description 先强制为 str，再做长度裁剪。
            if not isinstance(edge.get("description"), str):
                edge["description"] = ""
            if len(edge["description"]) > 100:
                edge["description"] = edge["description"][:97] + "..."

        # EXECPLAN2 I-1-3: 属性名保留字清洗。general_forecast 模板鼓励产出 sentiment/strength/
        # since_date 等供检索消费的属性；若 LLM 误用保留字（name/uuid/...），下游 set_ontology
        # 会改写为 entity_<name>，导致提示里描述的属性名与图谱里实际可过滤的字段名不一致。
        # 这里提前按 graph_builder 的同一保留字集改写，使本体自洽（社媒模板亦受益，行为兼容）。
        self._sanitize_reserved_attrs(result["entity_types"])
        self._sanitize_reserved_attrs(result["edge_types"])

        # ONTOLOGY 归一化（CODEX Step 3）：富 schema 开启时补全 LLM 漏标的 archetype（实体）
        # 与 family/valence（边）。纯附加键，不动核心键，故 set_ontology 兼容性不变；旗标关闭
        # 时此分支不触达。注意：放在保留字清洗之后、兜底类型注入之前——兜底 Person/Organization
        # 不显式带 archetype（缺失即被 actors.entity_archetype 缺省为 "actor"，对二者均正确）。
        if self._rich_schema_enabled():
            self._normalize_rich_schema(result)

        # Zep API 限制：最多 10 个自定义实体类型，最多 10 个自定义边类型
        MAX_ENTITY_TYPES = 10
        MAX_EDGE_TYPES = 10
        
        # 兜底类型定义
        person_fallback = {
            "name": "Person",
            "description": "Any individual person not fitting other specific person types.",
            "attributes": [
                {"name": "full_name", "type": "text", "description": "Full name of the person"},
                {"name": "role", "type": "text", "description": "Role or occupation"}
            ],
            "examples": ["ordinary citizen", "anonymous netizen"]
        }
        
        organization_fallback = {
            "name": "Organization",
            "description": "Any organization not fitting other specific organization types.",
            "attributes": [
                {"name": "org_name", "type": "text", "description": "Name of the organization"},
                {"name": "org_type", "type": "text", "description": "Type of organization"}
            ],
            "examples": ["small business", "community group"]
        }
        
        # 检查是否已有兜底类型
        # F-3-0: 此处条目已保证为含非空 name 的 dict，e["name"] 访问安全
        entity_names = {e["name"] for e in result["entity_types"]}
        has_person = "Person" in entity_names
        has_organization = "Organization" in entity_names

        # EXECPLAN2 I-1-3: 兜底策略随模板而定。
        # - social_opinion（默认）：维持原行为——总是补齐缺失的 Person/Organization 兜底。
        # - general_forecast：仅当角色阵容中确有自然人 / 组织（含未细分类型）时才补对应兜底；
        #   纯客体型预测问题（如资产价格）不强行塞入 Person/Organization，把预算留给领域类型。
        want_person, want_organization = True, True
        if template == "general_forecast":
            want_person, want_organization = self._fallback_needs_from_actors(actors)

        # 需要添加的兜底类型
        fallbacks_to_add = []
        if want_person and not has_person:
            fallbacks_to_add.append(person_fallback)
        if want_organization and not has_organization:
            fallbacks_to_add.append(organization_fallback)

        if fallbacks_to_add:
            current_count = len(result["entity_types"])
            needed_slots = len(fallbacks_to_add)

            # 如果添加后会超过 10 个，需要移除一些现有类型
            if current_count + needed_slots > MAX_ENTITY_TYPES:
                # F-3-4: 用 max(0, ...) 防御异常巨大的 current_count 产生坏切片
                to_remove = max(0, current_count + needed_slots - MAX_ENTITY_TYPES)
                if to_remove:
                    # 从末尾移除（保留前面更重要的具体类型）。
                    # F-3-4: 兜底插入恰恰发生在模型未遵守"兜底类型放最后"指令时，
                    # 此时尾部条目未必是最不重要的，可能是研究中关键的具体类型，
                    # 因此显式记录被丢弃的类型名，使丢弃可审计而非静默。
                    removed = result["entity_types"][-to_remove:]
                    result["entity_types"] = result["entity_types"][:-to_remove]
                    logger.warning(
                        "Ontology truncated: dropping entity types %s to fit "
                        "MAX_ENTITY_TYPES=%d for fallbacks %s",
                        [t.get("name") for t in removed],
                        MAX_ENTITY_TYPES,
                        [f.get("name") for f in fallbacks_to_add],
                    )

            # 添加兜底类型
            result["entity_types"].extend(fallbacks_to_add)

        # 最终确保不超过限制（防御性编程）
        # F-3-4: 硬上限丢弃同样记录，避免静默丢失实体类型
        if len(result["entity_types"]) > MAX_ENTITY_TYPES:
            removed = result["entity_types"][MAX_ENTITY_TYPES:]
            result["entity_types"] = result["entity_types"][:MAX_ENTITY_TYPES]
            logger.warning(
                "Ontology hard cap: dropping %d entity type(s) over MAX_ENTITY_TYPES=%d: %s",
                len(removed), MAX_ENTITY_TYPES, [t.get("name") for t in removed],
            )

        if len(result["edge_types"]) > MAX_EDGE_TYPES:
            removed_edges = result["edge_types"][MAX_EDGE_TYPES:]
            result["edge_types"] = result["edge_types"][:MAX_EDGE_TYPES]
            logger.warning(
                "Ontology hard cap: dropping %d edge type(s) over MAX_EDGE_TYPES=%d: %s",
                len(removed_edges), MAX_EDGE_TYPES, [t.get("name") for t in removed_edges],
            )

        # ONTO-6: 实体类型已最终确定（去重/兜底/硬上限都跑完）后，校正每条边的 source_targets：
        # 端点引用了不存在的实体类型时——大小写漂移可规范化的就 remap 回标准名，确实未定义的就丢弃。
        # 必须放在所有 entity_types 变更之后，否则会拿"被截断前"的旧集合误判。
        self._reconcile_edge_endpoints(result)

        return result

    @staticmethod
    def _reconcile_edge_endpoints(result: Dict[str, Any]) -> None:
        """ONTO-6：就地把每条 edge 的 source_targets 端点校正到已定义的实体类型集合。

        graphiti 的 set_ontology 用 edge 的 source/target 把边绑定到实体类型；若某端点引用了
        本体里**不存在**的实体类型（LLM 漏定义、或该类型在去重/兜底/硬上限阶段被丢弃），下游会
        悄悄忽略整条边、甚至报错。处理规则（确定性、可审计）：
        * 端点精确命中已定义类型 → 保留。
        * 端点仅大小写/空白不同（如 "person" vs "Person"）→ remap 回规范名并记日志（remap）。
        * 端点确实未定义 → 丢弃该 {source,target} 对并记日志（drop）。
        丢弃后边可能只剩空 source_targets（下游已容忍空列表），整条边本身不删除。
        """
        entity_names = {
            e["name"] for e in result.get("entity_types", [])
            if isinstance(e, dict) and isinstance(e.get("name"), str)
        }
        if not entity_names:
            return
        lower_map = {n.lower(): n for n in entity_names}

        def _resolve(endpoint: Any):
            """→ (canonical_name | None, action) ；action ∈ {'ok','remap','drop'}。"""
            name = str(endpoint or "").strip()
            if not name:
                return None, "drop"
            if name in entity_names:
                return name, "ok"
            canon = lower_map.get(name.lower())
            if canon is not None:
                return canon, "remap"
            return None, "drop"

        for edge in result.get("edge_types", []):
            if not isinstance(edge, dict):
                continue
            sts = edge.get("source_targets")
            if not isinstance(sts, list):
                continue
            kept: List[Dict[str, Any]] = []
            for st in sts:
                if not isinstance(st, dict):
                    logger.warning(
                        "Ontology ONTO-6: dropping malformed source_target %r on edge %r",
                        st, edge.get("name"),
                    )
                    continue
                src, src_act = _resolve(st.get("source"))
                tgt, tgt_act = _resolve(st.get("target"))
                if src_act == "drop" or tgt_act == "drop":
                    logger.warning(
                        "Ontology ONTO-6: dropping edge %r source_target %s→%s "
                        "(undefined endpoint not in entity types)",
                        edge.get("name"), st.get("source"), st.get("target"),
                    )
                    continue
                if src_act == "remap" or tgt_act == "remap":
                    logger.info(
                        "Ontology ONTO-6: remapped edge %r endpoints %s→%s to canonical %s→%s",
                        edge.get("name"), st.get("source"), st.get("target"), src, tgt,
                    )
                new_st = dict(st)
                new_st["source"] = src
                new_st["target"] = tgt
                kept.append(new_st)
            edge["source_targets"] = kept
