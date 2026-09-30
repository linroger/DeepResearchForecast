"""actors.json（DeerFlow 深度研究的结构化产物）的共享工具。

handoff 契约中的 actors.json 形如（NEW 字段均为可选，缺失即降级到旧行为）：

    {
      "central_question": "...",
      "as_of_date": "2026-06-08",
      "situation_brief": {                       // NEW —模拟可直接消费的局势简报
        "current_situation": "...", "context": "...", "dynamics": "...",
        "fault_lines": ["..."], "catalysts": ["..."]
      },
      "actors": [
        {"name": "...", "type": "Person|Organization|Media|Government|Platform|Other",
         "role": "...", "stance": "...", "influence": "high|medium|low",
         // NEW 身份消歧 / 别名解析（KG cookbook：描述用于消歧，别名解析零字符重叠的同义名）：
         "description": "一句话锚定 who/what（消歧用）", "aliases": ["同义名/缩写/外文名"],
         // NEW 角色内在动机（actors-and-incentives 结构化，均可选；缺失即降级）：
         "goals": ["..."], "constraints": ["..."], "assets": ["..."],
         "vulnerabilities": ["..."], "stated_vs_revealed": "言行差异",
         "memory": "该角色对事件的已知信息/立场记忆",
         // NEW 本体分类（ONTOLOGY：区分「能动 agent」与「报道者/概念/资源」，均可选）：
         "archetype": "actor|collective|institution_rule|asset_object|event|signal|claim_narrative|constraint_resource|place_jurisdiction|source|scenario",
         "simulation_tier": 1,                    // 1=核心决策者 2=利益相关方 3=被动信息源 4=抽象概念/资源
         "role_class": "principal|arbiter|stakeholder|amplifier|intermediary",
         "salience": {"score": 0.85, "tier": "high|medium|low", "basis": "..."},
         // NEW 行为 DNA（持久人格底座；缺失即降级到旧的 stance/influence 标签）：
         "worldview": {"values": ["..."], "beliefs": ["..."], "identity": "...", "frame": "..."},
         "incentives": [{"driver": "...", "gains_if": "...", "loses_if": "...", "intensity": "high|medium|low"}],
         "resources": ["..."],                    // assets 的超集/别名
         "risk_tolerance": "low|medium|high",
         // NEW actor-intelligence/v1：对每个演员做证据绑定的深度研究，供模拟角色直接消费。
         "intelligence": {
           "schema_version": "actor-intelligence/v1",
           "dimensions": {
             "identity_history": [{"claim": "...", "evidence_type": "verified_fact",
                                    "as_of_date": "...", "confidence": "high", "source_refs": ["src_..."]}],
             // 同样的 claim[] 单元还用于 values_worldview / incentives / motivations /
             // capabilities / constraints / operational_preferences / alliances /
             // opponents_competitors / decision_rights_process_triggers / current_actions /
             // future_plans / investments_capital_allocation / track_record / likely_actions /
             // red_lines / knowledge_state。金额、条件等有限字段位于 qualifiers。
           },
           "evidence_gaps": {"future_plans": ["..."]},
           "coverage": {"covered_dimensions": ["..."]}
         }}
      ],
      "relationships": [                         // NEW — 命名 actor 之间的有向、带类型边
        {"source": "...", "target": "...",       // source/target 必须 = 某个 actors[].name
         // 8 个旧类型保留；NEW 经济/治理/媒体类型扩展（见 REL_EDGE_NAME）：
         "type": "ALLY_OF|OPPOSES|COMPETES_WITH|REGULATES|DEPENDS_ON|PARTNERS_WITH|INFLUENCES|OTHER"
                 "|SUPPLIES|CUSTOMER_OF|FUNDS|INVESTS_IN|BACKS|OWNS|SUPPORTS|SANCTIONS"
                 "|REPORTS_ON|CONSUMES|ENDORSES|CRITICIZES|LITIGATES_AGAINST",
         "relation_label": "type==OTHER 时的自由文本标签，如 SUPPLIES/FUNDS/OWNS",  // NEW 可选
         "valence": "allied|adversarial|neutral|transactional|directional",  // NEW 可选；缺失从 type 推
         "polarity": 0.4,                         // NEW 可选 -1..1；缺失从 valence/type 推
         "sign": "ally|rival|neutral", "strength": "high|medium|low",
         "since": "YYYY-MM-DD", "until": "YYYY-MM-DD",  // NEW 可选起止日
         "basis": "调研实证一行"}
      ],
      "key_events": [{"date": "...", "event": "..."}],
      "hot_topics": ["..."],

      // EXECPLAN2 I-0-0：来源分层 + Admiralty 式定级（均为可选）。
      "sources": [
        {"title": "...", "url": "...",
         "tier": "S1|S2|S3|S4",            // S1=一手/权威 … S4=低可信
         "date": "2026-05-01",            // 该来源的发布/更新日
         "supports": ["claim-ref", ...],  // 该来源支撑的短声明引用
         "independent": true}              // 是否独立信源（非循环引用）
      ],
      // actor/relationship 行可带可选 "grade": "A1".."F6"（Admiralty 可靠度+可信度）。

      // EXECPLAN2 I-0-5：结构化定量事实表（每条带单位 + as-of 日 + 定义）。
      "quantitative_facts": [
        {"metric": "...", "value": "...", "unit": "...",
         "as_of_date": "2026-05-01", "definition": "...",
         "source": "...", "tier": "S1|S2|S3|S4"}
      ],

      // EXECPLAN2 I-0-1：证据冲突 / 争议声明（triangulation / ACH-lite 的结构化产物）。
      "contested_claims": [
        {"claim": "...",
         "positions": [{"stance": "...", "sources": ["..."], "tier": "S1|S2|S3|S4"}],
         "status": "confirmed|contested|speculative|single-origin",
         "why_they_differ": "..."}
      ],

      // EXECPLAN2 I-0-2：预测输入（外部视角基率 / 驱动变量 / 可观测指标 / 情景）。
      "forecast_inputs": {
        "base_rates": [{"reference_class": "...", "outcome_frequency": "...", "basis": "..."}],
        "drivers": [{"variable": "...", "direction": "...", "why_it_matters": "..."}],
        "indicators": [{"indicator": "...", "signals_what": "...", "date_or_trigger": "..."}],
        "scenarios": [{"name": "base|upside|downside", "probability_band": "...",
                       "narrative": "...", "key_assumptions": ["..."]}]
      }
    }

本模块提供：
* ``match_actor``            — 把 Zep 实体名匹配回研究档案中的 actor（标准化精确匹配 → 双向包含）。
* ``actor_briefing``         — 单个 actor 的提示词注入块（persona / agent 配置生成用）。
* ``actors_digest``          — 全量 actors + key_events + hot_topics 的上下文摘要（配置生成用）。
* ``extract_relationship_rows`` — 过滤出 source/target 都能匹配到 actor 的关系行。
* ``situation_brief_block``  — 把 situation_brief 渲染为紧凑的中文提示块。
* ``relationship_briefing``  — 单个 actor 的社会关系网提示块（命名真实对手方）。
* ``build_initial_follow_graph`` — relationships[] → 模拟初始关注边 [[follower_id, followee_id]]。
* ``events_to_schedule``     — key_events → 映射到模拟轮次的事件计划。
* ``events_to_calendar_rounds`` — TEMPORAL：key_events → 日历回合精确落轮 + 判定日外事件留档。
* ``sources_index_tiered``   — I-0-0：按 S1-S4 分层渲染可引用来源索引（带日期/独立性/定级）。
* ``source_tier_histogram``  — I-0-0：统计 s1_count..s4_count（meta 观测用）。
* ``quantitative_facts_block`` / ``extract_quantitative_rows`` — I-0-5：定量事实表渲染 / 安全抽取。
* ``contested_claims_block`` / ``extract_contested_rows``      — I-0-1：争议证据块渲染 / 安全抽取。
* ``forecast_inputs_block`` / ``extract_forecast_inputs``      — I-0-2：预测输入块渲染 / 安全抽取。
* ``entity_archetype`` / ``entity_simulation_tier`` / ``is_agent_eligible`` — ONTOLOGY：实体分类与「能动 agent」准入门。
* ``is_media_entity``         — ACTOR-CAST：媒体/观察者判定（ACTOR_EXCLUDE_MEDIA 时推断为 tier 3，降级为 context）。
* ``salience_score``         — ONTOLOGY：actor 的显著度评分（salience.score → influence 回退）。
* ``relation_valence`` / ``relation_polarity`` — ONTOLOGY：关系边的价（allied/adversarial/…）与极性（-1..1）。
* ``relational_roster`` / ``roster_block`` — ONTOLOGY：把 relationships[] 投影为 10 个命名关系桶 / 渲染关系网角色块。
* ``behavioral_dna_block``   — ONTOLOGY：把 worldview/incentives/resources/risk_tolerance 渲染为人格底座块。

设计原则：actors.json 永远是「可选增强」。任何字段缺失 / 类型不符都静默降级为
None / 空串 / 空列表，绝不让结构化数据的缺陷阻断原有的纯 LLM 生成路径。
所有下游消费者都只经由本模块读取 actors.json，绝不自行解析原始字典。
"""

from __future__ import annotations

import copy
import json
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

# influence 的自由文本 → 数值权重（与 simulation_config 的 influence_weight 同标度）
INFLUENCE_WEIGHTS = {
    "high": 2.5,
    "高": 2.5,
    "medium": 1.5,
    "med": 1.5,
    "中": 1.5,
    "low": 1.0,
    "低": 1.0,
}


def normalize_name(name: str) -> str:
    """实体名标准化：全半角统一、去空白/标点、小写。

    Zep 抽取的实体名（如 "OpenAI 公司"）与 DeerFlow 写出的 actor 名（如 "OpenAI"）
    经常只差大小写 / 空格 / 公司后缀，标准化后做包含匹配能覆盖绝大多数情况。
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", str(name)).lower()
    # 去掉所有空白与常见标点（中英文），保留字母数字与 CJK
    s = re.sub(r"[\s\.\,\:\;\-\_\(\)\[\]【】（）'\"·]+", "", s)
    return s


def _actor_norm_aliases(row: Dict[str, Any]) -> List[str]:
    """actor 行的可选 ``aliases`` 列表 → 标准化别名列表（容错：非 list/非 str 返回 []）。

    KG 经验（Anthropic KG cookbook 核心洞见）：很多同一实体的别名零字符重叠
    （"Edwin Aldrin"=="Buzz Aldrin"、"MSFT"=="Microsoft"、"马斯克"=="Musk"），
    纯字符串相似度无法合并，需要显式别名表来解析。
    """
    if not isinstance(row, dict):
        return []
    raw = row.get("aliases")
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for a in raw:
        if isinstance(a, str):
            na = normalize_name(a)
            if na:
                out.append(na)
    return out


def extract_actor_rows(actors: Optional[Any]) -> List[Dict[str, Any]]:
    """从 actors.json 顶层对象安全取出 actor 行列表（容错任意脏数据）。"""
    if not isinstance(actors, dict):
        return []
    rows = actors.get("actors")
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("name")]


ACTOR_INTELLIGENCE_SCHEMA_VERSION = "actor-intelligence/v1"


def actor_intelligence_schema_version(actor: Optional[Dict[str, Any]]) -> str:
    """Return the actor's explicit intelligence schema marker, if any."""
    if not isinstance(actor, dict):
        return ""
    value = actor.get("intelligence")
    if not isinstance(value, dict):
        return ""
    return str(value.get("schema_version") or "").strip()


def has_unsupported_actor_intelligence_schema(
    actor: Optional[Dict[str, Any]],
) -> bool:
    """Whether an explicit future/unknown actor contract must fail closed.

    Unversioned rows remain the legacy compatibility path.  Once a producer
    declares a schema, however, consumers must not reinterpret an unsupported
    contract through older flat fields.
    """
    version = actor_intelligence_schema_version(actor)
    return bool(version and version != ACTOR_INTELLIGENCE_SCHEMA_VERSION)


def actor_intelligence_payload(actor: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a supported actor-intelligence payload without weakening old rows.

    The versioned shape is authoritative.  Unversioned dictionaries are also
    accepted as a migration compatibility path because early research outputs
    emitted the same additive fields before the schema marker existed.  A
    different explicit version fails closed so a future incompatible contract
    cannot silently be interpreted as v1.
    """
    if not isinstance(actor, dict):
        return {}
    value = actor.get("intelligence")
    if not isinstance(value, dict):
        return {}
    version = actor_intelligence_schema_version(actor)
    if version and version != ACTOR_INTELLIGENCE_SCHEMA_VERSION:
        return {}
    return value


def actor_intelligence_dimension(
    actor: Optional[Dict[str, Any]],
    canonical: str,
    *flat_aliases: str,
) -> Any:
    """Read one canonical ``intelligence.dimensions`` value with flat aliases."""
    intelligence = actor_intelligence_payload(actor)
    dimensions = intelligence.get("dimensions")
    value = dimensions.get(canonical) if isinstance(dimensions, dict) else None
    if isinstance(value, dict):
        for key in ("claims", "items", "entries"):
            if value.get(key) not in (None, "", []):
                return value.get(key)
    if value not in (None, "", []):
        return value
    for key in flat_aliases:
        if intelligence.get(key) not in (None, "", []):
            return intelligence.get(key)
    return None


def _intelligence_has_source_refs(value: Any, depth: int = 0) -> bool:
    if depth > 12:
        return False
    if isinstance(value, dict):
        if any(
            value.get(key)
            for key in ("source_refs", "source_ids", "evidence_refs", "citations")
        ):
            return True
        return any(_intelligence_has_source_refs(item, depth + 1) for item in value.values())
    if isinstance(value, list):
        return any(_intelligence_has_source_refs(item, depth + 1) for item in value)
    return False


def actor_intelligence_claims(
    actor: Optional[Dict[str, Any]],
    canonical: str,
    *flat_aliases: str,
    limit: int = 3,
    max_chars: int = 260,
) -> List[str]:
    """Render bounded claim/evidence rows for legacy prompt consumers."""
    value = actor_intelligence_dimension(actor, canonical, *flat_aliases)
    if isinstance(value, dict):
        rows = [value]
    elif isinstance(value, list):
        rows = value
    elif value not in (None, ""):
        rows = [value]
    else:
        rows = []
    out: List[str] = []
    for raw in rows:
        if isinstance(raw, dict):
            claim = str(
                raw.get("claim")
                or raw.get("finding")
                or raw.get("description")
                or raw.get("text")
                or ""
            ).strip()
            rendered_qualifiers: List[str] = []
            nested = raw.get("qualifiers")
            nested = nested if isinstance(nested, dict) else {}
            for label, keys in (
                ("as of", ("as_of_date", "as_of")),
                ("confidence", ("confidence",)),
                ("evidence type", ("evidence_type", "epistemic_status")),
                ("status", ("status",)),
                ("horizon", ("horizon", "timeframe")),
                ("conditions", ("conditions", "dependencies")),
                ("amount", ("amount",)),
                ("unit", ("unit",)),
                ("action type", ("action_type", "type")),
                ("purpose", ("strategic_purpose",)),
            ):
                selected = next((
                    raw.get(key) for key in keys if raw.get(key) not in (None, "", [])
                ), None)
                if selected in (None, "", []):
                    selected = next((
                        nested.get(key) for key in keys
                        if nested.get(key) not in (None, "", [])
                    ), None)
                if isinstance(selected, list):
                    item = "; ".join(str(value).strip() for value in selected[:4] if str(value).strip())
                else:
                    item = str(selected or "").strip()
                if item:
                    rendered_qualifiers.append(f"{label}={item}")
            refs = raw.get("source_refs") or raw.get("source_ids") or raw.get("evidence_refs")
            refs = refs or nested.get("source_refs") or nested.get("source_ids")
            if isinstance(refs, list):
                rendered_refs = ",".join(str(ref).strip() for ref in refs[:4] if str(ref).strip())
                if rendered_refs:
                    rendered_qualifiers.append(f"sources={rendered_refs}")
            text = claim + (
                f" [{'; '.join(rendered_qualifiers)}]"
                if claim and rendered_qualifiers else ""
            )
        else:
            text = str(raw or "").strip()
        text = re.sub(r"\s+", " ", text)
        if len(text) > max_chars:
            text = text[: max(0, max_chars - 1)].rstrip() + "…"
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def actor_intelligence_dimension_presence(
    actor: Optional[Dict[str, Any]],
) -> Dict[str, bool]:
    """Report evidence-bearing v1 dimensions for quality gates and telemetry.

    This helper only checks whether a dimension carries content; it does not
    claim that the content is true or sufficient.  That distinction keeps the
    coverage gate useful without turning a structural check into a confidence
    score.
    """
    intel = actor_intelligence_payload(actor)
    preferences = actor_intelligence_dimension(
        actor, "operational_preferences", "preferences"
    )
    if isinstance(preferences, dict):
        has_preferences = bool(preferences.get("likes") or preferences.get("dislikes"))
    else:
        has_preferences = bool(preferences or intel.get("aversions"))
    decision = actor_intelligence_dimension(
        actor, "decision_rights_process_triggers", "decision_model"
    )
    has_decision = bool(decision)
    context_pack = intel.get("context_pack")
    has_report_context = bool(intel.get("relevant_report_context")) or (
        isinstance(context_pack, dict)
        and bool(context_pack.get("actor_relevant_report_sections"))
    )
    return {
        "identity_history": bool(
            actor_intelligence_dimension(actor, "identity_history", "history")
        ),
        "track_record": bool(
            actor_intelligence_dimension(actor, "track_record", "track_record")
        ),
        "history": bool(
            actor_intelligence_dimension(actor, "identity_history", "history")
            or actor_intelligence_dimension(actor, "track_record", "track_record")
        ),
        "values_worldview": bool(
            actor_intelligence_dimension(actor, "values_worldview", "values_worldview")
        ),
        "incentives": bool(
            actor_intelligence_dimension(actor, "incentives", "intelligence_incentives")
        ),
        "motivations": bool(actor_intelligence_dimension(actor, "motivations", "motivations")),
        "capabilities": bool(actor_intelligence_dimension(actor, "capabilities", "capabilities")),
        "constraints": bool(
            actor_intelligence_dimension(actor, "constraints", "constraints")
        ),
        "preferences": has_preferences,
        "alliances": bool(
            actor_intelligence_dimension(actor, "alliances", "alliances")
        ),
        "opponents_competitors": bool(
            actor_intelligence_dimension(
                actor, "opponents_competitors", "opponents_competitors"
            )
        ),
        "current_actions": bool(
            actor_intelligence_dimension(
                actor, "current_actions", "current_actions", "actions_in_progress"
            )
        ),
        "future_plans": bool(
            actor_intelligence_dimension(actor, "future_plans", "future_plans", "plans")
        ),
        "investments": bool(
            actor_intelligence_dimension(
                actor,
                "investments_capital_allocation",
                "investments",
                "capital_allocation",
                "capex_divestments",
            )
        ),
        "decision_model": has_decision,
        "likely_actions": bool(
            actor_intelligence_dimension(
                actor, "likely_actions", "intelligence_likely_actions"
            )
        ),
        "red_lines": bool(
            actor_intelligence_dimension(actor, "red_lines", "red_lines")
        ),
        "knowledge_state": bool(
            actor_intelligence_dimension(actor, "knowledge_state", "knowledge_state")
        ),
        "report_context": has_report_context,
        "source_refs": _intelligence_has_source_refs(intel),
        "provenance": isinstance(intel.get("provenance"), dict) and bool(intel.get("provenance")),
        "evidence_gaps": bool(intel.get("evidence_gaps")),
        "producer_coverage": isinstance(intel.get("coverage"), dict) and bool(intel.get("coverage")),
    }


def match_actor(entity_name: str, actors: Optional[Any]) -> Optional[Dict[str, Any]]:
    """把一个 Zep 实体名匹配回研究档案的 actor 行。

    匹配顺序：标准化精确匹配 → 双向包含（取较长名者优先，避免 "AI" 这类
    短名误配）→ 别名匹配（覆盖零字符重叠的同义名/缩写/外文名）。无匹配返回 None。
    """
    rows = extract_actor_rows(actors)
    if not rows or not entity_name:
        return None
    target = normalize_name(entity_name)
    if not target:
        return None

    # Exact canonical/alias identity is authoritative.  Complete this pass for
    # the whole roster before considering fuzzy containment so an early short
    # name can never steal a later exact match.
    exact_rows: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        cand = normalize_name(str(row.get("name", "")))
        if cand == target or target in _actor_norm_aliases(row):
            exact_rows[cand] = row
    if len(exact_rows) == 1:
        return next(iter(exact_rows.values()))
    if len(exact_rows) > 1:
        return None

    # Fuzzy containment is a last-resort compatibility path for suffix/prefix
    # variants such as "OpenAI" versus "OpenAI Inc".  Two- and three-character
    # names (US/EU/AI/UK, many initials) are never safe substring signals.
    candidates: List[tuple[int, str, Dict[str, Any]]] = []
    for row in rows:
        surfaces = [normalize_name(str(row.get("name", ""))), *_actor_norm_aliases(row)]
        for surface in surfaces:
            if (min(len(surface), len(target)) >= 4
                    and (surface in target or target in surface)):
                canonical = normalize_name(str(row.get("name", "")))
                candidates.append((len(surface), canonical, row))
    if not candidates:
        return None
    best_len = max(item[0] for item in candidates)
    best_rows: Dict[str, Dict[str, Any]] = {
        canonical: row
        for length, canonical, row in candidates
        if length == best_len and canonical
    }
    # Ambiguous fuzzy identity is worse than a missing role: fail closed and let
    # the cast/roster audit expose the unresolved actor.
    return next(iter(best_rows.values())) if len(best_rows) == 1 else None


def influence_weight(actor: Optional[Dict[str, Any]]) -> Optional[float]:
    """actor.influence（high/medium/low 等自由文本）→ 数值权重；无法解析返回 None。"""
    if not isinstance(actor, dict):
        return None
    raw = str(actor.get("influence", "")).strip().lower()
    if not raw:
        return None
    for key, weight in INFLUENCE_WEIGHTS.items():
        if key in raw:
            return weight
    return None


def actor_briefing(
    actor: Optional[Dict[str, Any]],
    max_memory_chars: int = 600,
    max_intelligence_chars: int = 2200,
) -> str:
    """单个 actor 的提示词注入块（空 actor 返回空串）。

    persona / agent 配置生成的提示词里以「研究实证」的口吻注入，引导 LLM
    以真实调研数据为准，而不是凭报告行文再猜一遍。
    """
    if not isinstance(actor, dict):
        return ""
    parts: List[str] = []
    for label, key in (("角色定位", "role"), ("立场", "stance"), ("影响力", "influence")):
        val = str(actor.get(key, "") or "").strip()
        if val:
            parts.append(f"- {label}: {val}")
    # 角色「内在动机」结构化字段（来自深度研究的 actors-and-incentives 分析）。
    # 让 persona 从「立场标签」升级为「动机画像」；字段缺失时自动跳过，旧档案输出不变。
    for label, key in (("目标/动机", "goals"), ("约束", "constraints"),
                       ("资源/能力", "assets"), ("软肋/红线", "vulnerabilities")):
        val = actor.get(key)
        if isinstance(val, list) and val:
            parts.append(f"- {label}: " + "；".join(str(x) for x in val[:6] if str(x).strip()))
    svr = str(actor.get("stated_vs_revealed", "") or "").strip()
    if svr:
        parts.append(f"- 言行差异: {svr}")
    memory = str(actor.get("memory", "") or "").strip()
    if memory:
        if len(memory) > max_memory_chars:
            memory = memory[:max_memory_chars] + "…"
        parts.append(f"- 已知事实/记忆: {memory}")
    intelligence_lines: List[str] = []
    for label, dimension, aliases in (
        ("历史/轨迹", "identity_history", ("history",)),
        ("决策记录", "track_record", ("track_record",)),
        ("深层动机", "motivations", ("motivations",)),
        ("可调动能力及边界", "capabilities", ("capabilities",)),
        ("操作偏好/反感", "operational_preferences", ("preferences", "aversions")),
        ("当前行动", "current_actions", ("current_actions", "actions_in_progress")),
        ("未来计划/承诺", "future_plans", ("future_plans", "plans")),
        ("投资/资本配置", "investments_capital_allocation", ("investments", "capital_allocation")),
        ("决策权/流程/触发条件", "decision_rights_process_triggers", ("decision_model",)),
        ("已知信息边界", "knowledge_state", ("knowledge_state",)),
        ("红线", "red_lines", ("red_lines",)),
    ):
        values = actor_intelligence_claims(actor, dimension, *aliases, limit=2)
        if values:
            intelligence_lines.append(f"- {label}: " + "；".join(values))
    gaps = actor_intelligence_payload(actor).get("evidence_gaps")
    if gaps:
        # Evidence gaps are outside dimensions, so render them directly with
        # the same bounded claim convention.
        gap_values: List[str] = []
        if isinstance(gaps, dict):
            for dimension in sorted(gaps, key=str):
                raw_values = gaps.get(dimension)
                values = raw_values if isinstance(raw_values, list) else [raw_values]
                for raw in values:
                    claim = raw.get("claim") if isinstance(raw, dict) else raw
                    value = re.sub(r"\s+", " ", str(claim or "")).strip()
                    if value:
                        gap_values.append(f"{dimension}: {value[:220]}")
                    if len(gap_values) >= 3:
                        break
                if len(gap_values) >= 3:
                    break
        elif isinstance(gaps, list):
            for raw in gaps[:3]:
                claim = raw.get("claim") if isinstance(raw, dict) else raw
                value = re.sub(r"\s+", " ", str(claim or "")).strip()
                if value:
                    gap_values.append(value[:260])
        if gap_values:
            intelligence_lines.append("- 证据缺口: " + "；".join(gap_values))
    used = 0
    for line in intelligence_lines:
        addition = len(line) + (1 if used else 0)
        if used + addition > max(0, int(max_intelligence_chars)):
            break
        parts.append(line)
        used += addition
    if not parts:
        return ""
    return (
        "## 深度研究实证档案（来自真实网络调研，生成时必须以此为准）\n"
        + "\n".join(parts)
    )


def actors_digest(
    actors: Optional[Any],
    max_actors: int = 30,
    max_chars: int = 4000,
) -> str:
    """全量研究档案摘要：actors 表 + key_events + hot_topics。

    供 SimulationConfigGenerator 的上下文与事件配置提示词使用。超长时按行截断。
    """
    if not isinstance(actors, dict):
        return ""
    lines: List[str] = []

    rows = extract_actor_rows(actors)
    if rows:
        lines.append("### 深度研究确认的真实角色（立场/影响力为调研实证）")
        for row in rows[:max_actors]:
            name = str(row.get("name", "?"))
            typ = str(row.get("type", "") or "")
            role = str(row.get("role", "") or "")
            stance = str(row.get("stance", "") or "")
            influence = str(row.get("influence", "") or "")
            seg = f"- {name}（{typ}）"
            if role:
                seg += f" 角色: {role}"
            if stance:
                seg += f" | 立场: {stance}"
            if influence:
                seg += f" | 影响力: {influence}"
            goals = row.get("goals")
            if isinstance(goals, list) and goals and str(goals[0]).strip():
                seg += f" | 核心目标: {str(goals[0]).strip()}"
            for label, dimension, aliases in (
                ("当前行动", "current_actions", ("current_actions",)),
                ("未来计划", "future_plans", ("future_plans", "plans")),
                ("资本配置", "investments_capital_allocation", ("investments",)),
            ):
                claims = actor_intelligence_claims(
                    row, dimension, *aliases, limit=1, max_chars=140
                )
                if claims:
                    seg += f" | {label}: {claims[0]}"
            lines.append(seg)

    events = actors.get("key_events")
    if isinstance(events, list) and events:
        lines.append("### 关键时间线（调研实证）")
        for ev in events[:15]:
            if isinstance(ev, dict):
                date = str(ev.get("date", "") or "")
                desc = str(ev.get("event", "") or "")
                if desc:
                    lines.append(f"- {date} {desc}".strip())

    topics = actors.get("hot_topics")
    if isinstance(topics, list) and topics:
        lines.append("### 调研发现的热点议题")
        lines.append("、".join(str(t) for t in topics[:12]))

    digest = "\n".join(lines)
    if len(digest) > max_chars:
        digest = digest[:max_chars] + "\n…(研究档案已截断)"
    return digest


# ---------------------------------------------------------------------------
# 关系图 / 局势简报（EXECPLAN T1.3 — 黄金主线的基础工具）
# ---------------------------------------------------------------------------

# relationships[].type → 知识图谱边名（恒等映射，但集中在此以免散落各处漂移）
REL_EDGE_NAME = {
    "ALLY_OF": "ALLY_OF",
    "OPPOSES": "OPPOSES",
    "COMPETES_WITH": "COMPETES_WITH",
    "REGULATES": "REGULATES",
    "DEPENDS_ON": "DEPENDS_ON",
    "PARTNERS_WITH": "PARTNERS_WITH",
    "INFLUENCES": "INFLUENCES",
    # ONTOLOGY 扩展类型：经济/治理/媒体边。KG 边名 = 类型本身（恒等），让带价的供需/
    # 出资/持股/制裁/报道等关系不再被压平成无类型的 RELATES_TO，从而保留语义与方向。
    "SUPPLIES": "SUPPLIES",
    "CUSTOMER_OF": "CUSTOMER_OF",
    "FUNDS": "FUNDS",
    "INVESTS_IN": "INVESTS_IN",
    "BACKS": "BACKS",
    "OWNS": "OWNS",
    "SUPPORTS": "SUPPORTS",
    "SANCTIONS": "SANCTIONS",
    "REPORTS_ON": "REPORTS_ON",
    "CONSUMES": "CONSUMES",
    "ENDORSES": "ENDORSES",
    "CRITICIZES": "CRITICIZES",
    "LITIGATES_AGAINST": "LITIGATES_AGAINST",
    # NEXTSTEPS P3-5：因果/机制边族。预测 outcome 本质是沿**传导机制**推理而非"谁认识谁"——
    # 这些边把 KG 从一张扁平索引变成可追溯的传导模型（报告可沿因果链解释、未来可沿其播撒冲击/
    # 前投未来边）。带 {sign, lag, strength, basis} 时由 graph_builder 折进 fact 文本。
    "CAUSES": "CAUSES",
    "ENABLES": "ENABLES",
    "CONSTRAINS": "CONSTRAINS",
    "TRIGGERS": "TRIGGERS",
    "ACCELERATES": "ACCELERATES",
    # OTHER 是「逃生舱」类型：研究用 relation_label 给出自由文本边名（SUPPLIES/FUNDS/…）。
    # 这里给个兜底边名，graph_builder 会优先用 relation_label，否则落到 RELATES_TO。
    "OTHER": "RELATES_TO",
}

# 边类型 → 中文标签（persona 提示块用）
REL_LABEL = {
    "ALLY_OF": "盟友",
    "OPPOSES": "对立",
    "COMPETES_WITH": "竞争",
    "REGULATES": "监管",
    "DEPENDS_ON": "依赖",
    "PARTNERS_WITH": "伙伴",
    "INFLUENCES": "影响",
    # ONTOLOGY 扩展类型的双语标签（persona/报告提示块用；保持与旧 8 类同样的简洁口吻）。
    "SUPPLIES": "供应",
    "CUSTOMER_OF": "客户",
    "FUNDS": "出资",
    "INVESTS_IN": "投资",
    "BACKS": "扶持",
    "OWNS": "持有",
    "SUPPORTS": "支持",
    "SANCTIONS": "制裁",
    "REPORTS_ON": "报道",
    "CONSUMES": "消费",
    "ENDORSES": "背书",
    "CRITICIZES": "批评",
    "LITIGATES_AGAINST": "诉讼",
    # P3-5 因果/机制边族的中文标签
    "CAUSES": "导致",
    "ENABLES": "促成",
    "CONSTRAINS": "制约",
    "TRIGGERS": "触发",
    "ACCELERATES": "加速",
    "OTHER": "关联",
}


def extract_relationship_rows(actors: Optional[Any]) -> List[Dict[str, Any]]:
    """取出 source 与 target 都能标准化匹配到某个 actors[].name 的关系行。

    脏数据（非 dict、缺 source/target、端点不在 actor 表内）一律剔除；
    actors 不是 dict 或没有 relationships 时返回 []。
    """
    if not isinstance(actors, dict):
        return []
    rels = actors.get("relationships")
    if not isinstance(rels, list):
        return []
    rows = extract_actor_rows(actors)
    names = {normalize_name(r["name"]) for r in rows}
    # 端点名集合也并入别名（可选）：让用别名书写的关系端点也能匹配到 actor。
    for r in rows:
        names.update(_actor_norm_aliases(r))
    out: List[Dict[str, Any]] = []
    for r in rels:
        if not isinstance(r, dict):
            continue
        s, t = r.get("source"), r.get("target")
        if s and t and normalize_name(str(s)) in names and normalize_name(str(t)) in names:
            out.append(r)
    return out


def situation_brief_block(actors: Optional[Any], english: bool = False,
                          honest_label: bool = False) -> str:
    """把 situation_brief 渲染为紧凑的提示块（默认中文标题；english=True 用英文标题，
    供英文模拟的 agent 可见世界简报使用）；缺失返回空串。

    SIM-5 honest_label=True：标题如实标注为「研究综述，未逐条标注来源；背景参考，并非已核实
    事实」——v3 situation_brief 不带 [S#] 来源标记，不得自称「实证/权威」。只有 agent 可见的
    世界简报（SimulationConfigGenerator._build_world_brief，受 SIM_WORLD_BRIEF_HONEST_LABEL
    控制）传 True；其余调用点默认 False，逐字节不变。"""
    sb = actors.get("situation_brief") if isinstance(actors, dict) else None
    if not isinstance(sb, dict):
        return ""
    if english:
        prose = (("Current situation", "current_situation"), ("Background", "context"),
                 ("Tensions and dynamics", "dynamics"))
        lists = (("Fault lines", "fault_lines"), ("Potential triggers", "catalysts"))
        title = ("## Situation brief (research synthesis, not individually sourced; "
                 "background, not verified fact)" if honest_label
                 else "## Situation brief (deep-research evidence, authoritative background)")
    else:
        prose = (("当前态势", "current_situation"), ("来龙去脉", "context"), ("张力/动态", "dynamics"))
        lists = (("争议断层", "fault_lines"), ("潜在触发", "catalysts"))
        title = ("## 局势简报（深度研究综述，未逐条标注来源；作为背景参考，并非已核实事实）"
                 if honest_label else "## 局势简报（深度研究实证，作为权威背景）")
    parts: List[str] = []
    for label, key in prose:
        v = str(sb.get(key, "") or "").strip()
        if v:
            parts.append(f"### {label}\n{v}")
    for label, key in lists:
        lst = sb.get(key)
        if isinstance(lst, list) and lst:
            parts.append(f"### {label}\n" + "\n".join(f"- {x}" for x in lst[:6]))
    if not parts:
        return ""
    return title + "\n" + "\n".join(parts)


def relationship_briefing(actor_name: str, actors: Optional[Any], max_edges: int = 6) -> str:
    """单个 actor 的社会关系网提示块，命名真实对手方；无关系返回空串。"""
    if not actor_name:
        return ""
    rows = extract_relationship_rows(actors)
    me = normalize_name(actor_name)
    out: List[str] = []
    for r in rows:
        typ = str(r.get("type", "")).upper()
        # OTHER 边优先显示研究给出的自由文本标签（如 SUPPLIES / FUNDS），否则用通用「关联」。
        label = REL_LABEL.get(typ, "关联")
        if typ == "OTHER":
            rl = str(r.get("relation_label", "") or "").strip()
            if rl:
                label = rl
        s, t = normalize_name(str(r.get("source", ""))), normalize_name(str(r.get("target", "")))
        strength = str(r.get("strength", "") or "")
        if me == s:
            out.append(f"{label}（{strength}）: {r.get('target')}")
        elif me == t:
            out.append(f"被{label}: {r.get('source')}")
        if len(out) >= max_edges:
            break
    if not out:
        return ""
    return "## 你的社会关系网（调研实证，互动时据此 @ 相关方）\n" + "\n".join("- " + x for x in out)


# ---------------------------------------------------------------------------
# 本体分类 / 行为 DNA / 关系网角色（ONTOLOGY 层 — 让「报道者/概念/资源」不被当作能动 agent，
# 给真正的 actor 注入价值观/动机/资源的人格底座，并把关系投影成命名关系桶）
# ---------------------------------------------------------------------------

# 合法 archetype 枚举（其余值原样保留但按「非 actor」处理）。
ENTITY_ARCHETYPES = (
    "actor", "collective", "institution_rule", "asset_object", "event",
    "signal", "claim_narrative", "constraint_resource", "place_jurisdiction",
    "source", "scenario",
)
# 能动（可作为模拟 agent）的 archetype：只有真实决策主体 / 群体派系才进 agent 池。
_AGENT_ARCHETYPES = frozenset({"actor", "collective"})

# 关系价 → 极性基准值（relation_polarity 在无显式 polarity 时据此推算，并按 strength 缩放）。
_VALENCE_POLARITY = {
    "allied": 0.4,
    "adversarial": -0.4,
    "transactional": 0.15,
    "directional": 0.0,
    "neutral": 0.0,
}
# 关系类型 → 价（无显式 valence 时据此推）。四类语义簇：结盟/对抗/经济/治理-依赖-影响-报道。
_REL_TYPE_VALENCE = {
    # 结盟（正向）
    "ALLY_OF": "allied", "SUPPORTS": "allied", "PARTNERS_WITH": "allied", "ENDORSES": "allied",
    # 对抗（负向）
    "OPPOSES": "adversarial", "COMPETES_WITH": "adversarial", "SANCTIONS": "adversarial",
    "CRITICIZES": "adversarial", "LITIGATES_AGAINST": "adversarial",
    # 经济（交易性）
    "SUPPLIES": "transactional", "CUSTOMER_OF": "transactional", "FUNDS": "transactional",
    "INVESTS_IN": "transactional", "BACKS": "transactional", "OWNS": "transactional",
    "CONSUMES": "transactional",
    # 治理 / 依赖 / 影响 / 报道（有向、非褒贬）
    "REGULATES": "directional", "DEPENDS_ON": "directional", "INFLUENCES": "directional",
    "REPORTS_ON": "directional",
    # P3-5 因果/机制（有向传导，非褒贬）
    "CAUSES": "directional", "ENABLES": "directional", "CONSTRAINS": "directional",
    "TRIGGERS": "directional", "ACCELERATES": "directional",
}


def entity_archetype(actor: Optional[Dict[str, Any]]) -> str:
    """读取 actor 的 ``archetype``；缺失/非法返回默认 "actor"（保持旧行为：一切皆能动）。"""
    if not isinstance(actor, dict):
        return "actor"
    raw = str(actor.get("archetype", "") or "").strip().lower()
    return raw if raw in ENTITY_ARCHETYPES else "actor"


# ACTOR-CAST DISCIPLINE（ACTOR_EXCLUDE_MEDIA）：媒体/观察者的判定信号。
# type=Media / archetype=source / role·role_class·description 命中「报道/评论方」关键词。
# 媒体机构、记者、评论员、分析师、民调机构、智库是 context（被动信息源），不是对预测结果
# 有因果能动性的 main actor —— 除非研究方显式给了 simulation_tier ∈ {1,2}（它本身推动结局）。
_MEDIA_TYPE_VALUES = {"media", "mediaoutlet", "media_outlet", "媒体"}
_MEDIA_ROLE_KEYWORDS = (
    "journalist", "reporter", "correspondent", "columnist", "commentator", "pundit",
    "news outlet", "news agency", "newswire", "wire service", "newspaper", "broadcaster",
    "news channel", "media outlet", "media organization", "media organisation", "media company",
    "pollster", "think tank", "think-tank", "blogger", "podcaster", "media analyst",
    "记者", "评论员", "专栏作家", "媒体机构", "新闻机构", "通讯社", "报社", "电视台", "智库", "民调机构",
)


def _explicit_simulation_tier(actor: Dict[str, Any]) -> Optional[int]:
    """actor 行上**显式**携带的 simulation_tier ∈ {1,2,3,4}；缺失/非法 → None。"""
    raw = actor.get("simulation_tier")
    if isinstance(raw, bool):  # bool 是 int 子类，需先排除
        return None
    if isinstance(raw, int) and raw in (1, 2, 3, 4):
        return raw
    if isinstance(raw, str):
        m = re.search(r"[1-4]", raw)
        if m:
            return int(m.group(0))
    return None


def _media_exclusion_enabled() -> bool:
    """ACTOR_EXCLUDE_MEDIA 旗标（默认开）。延迟导入 Config，避免 utils→config 顶层环依赖。"""
    try:
        from ..config import Config as _Cfg
        return bool(getattr(_Cfg, "ACTOR_EXCLUDE_MEDIA", True))
    except Exception:  # noqa: BLE001 — Config 不可导入（独立脚本）时按默认开处理
        return True


def is_media_entity(actor: Optional[Dict[str, Any]]) -> bool:
    """媒体/观察者实体判定：type=Media、archetype=source，或角色文本命中媒体关键词。

    显式 simulation_tier ∈ {1,2} 时返回 False —— 研究方已判定该实体本身推动结局
    （例如预测问题就是关于媒体影响力的），不应被降级。
    """
    if not isinstance(actor, dict):
        return False
    if _explicit_simulation_tier(actor) in (1, 2):
        return False
    if str(actor.get("type", "") or "").strip().lower() in _MEDIA_TYPE_VALUES:
        return True
    raw_arch = str(actor.get("archetype", "") or "").strip().lower()
    if raw_arch == "source":
        return True
    haystack = " ".join(
        str(actor.get(k, "") or "") for k in ("role", "role_class", "description")
    ).lower()
    return any(kw in haystack for kw in _MEDIA_ROLE_KEYWORDS)


def entity_simulation_tier(actor: Optional[Dict[str, Any]]) -> int:
    """读取 actor 的 ``simulation_tier`` ∈ {1,2,3,4}；缺失时按 archetype/type/influence 推断。

    推断规则（与契约一致）：
    * source archetype 或「仅被引用的媒体」→ 3（被动信息源）。
    * 其余非 actor/collective 的 archetype（事件/概念/资源/地点等）→ 4（抽象）。
    * ACTOR_EXCLUDE_MEDIA（默认开）：无显式 tier 的媒体/观察者实体（type=Media /
      媒体类 role）→ 3 —— 报道方是 context，不是有因果能动性的 main actor。
      旗标关闭时跳过该分支（旧行为：media 默认 tier 1 放行）。
    * actor/collective：influence=high → 1（核心决策者），否则 → 2（利益相关方）。
    * 完全无信号 → 1（默认能动，保持旧行为）。
    """
    if not isinstance(actor, dict):
        return 1
    explicit = _explicit_simulation_tier(actor)
    if explicit is not None:
        return explicit
    arch = entity_archetype(actor)
    if arch == "source":
        return 3
    if arch not in _AGENT_ARCHETYPES:
        return 4
    # ACTOR-CAST DISCIPLINE：媒体/观察者（type=Media 等）此前因缺省 archetype 落到
    # 「能动 actor」分支被推断为 tier 1/2 —— 正是媒体挤占 agent 池席位的根因。
    if _media_exclusion_enabled() and is_media_entity(actor):
        return 3
    # actor / collective：按影响力分核心 / 利益相关方
    w = influence_weight(actor)
    if w is not None and w >= INFLUENCE_WEIGHTS["high"]:
        return 1
    return 1 if w is None else 2


def is_agent_eligible(actor: Optional[Dict[str, Any]]) -> bool:
    """能动 agent 准入门：tier ∈ {1,2}（即 archetype 实质为 actor/collective）。

    报道者/媒体出口/抽象概念/资源（tier 3/4）被挡在模拟 agent 池外，避免它们被
    错误地实例化为有行动力的角色。字段全缺时 tier 推断为 1，故旧档案全部放行。
    """
    return entity_simulation_tier(actor) in (1, 2)


def salience_score(actor: Optional[Dict[str, Any]]) -> float:
    """actor 的显著度评分 ∈ [0,1]：优先读 ``salience.score``，否则从 influence 回退。

    回退标度与契约一致：influence high/medium/low → 0.85/0.55/0.3；无信号 → 0.3。
    用于 agent 上限按「显著度」而非「原始度数」排序，让核心方优先入池。
    """
    if not isinstance(actor, dict):
        return 0.3
    sal = actor.get("salience")
    if isinstance(sal, dict):
        score = sal.get("score")
        if isinstance(score, bool):
            score = None
        if isinstance(score, (int, float)):
            return max(0.0, min(1.0, float(score)))
        # 无数值 score 时，退而读 salience.tier 文本
        tier = str(sal.get("tier", "") or "").strip().lower()
        if tier in ("high", "高"):
            return 0.85
        if tier in ("medium", "med", "中"):
            return 0.55
        if tier in ("low", "低"):
            return 0.3
    w = influence_weight(actor)
    if w is None:
        return 0.3
    if w >= INFLUENCE_WEIGHTS["high"]:
        return 0.85
    if w >= INFLUENCE_WEIGHTS["medium"]:
        return 0.55
    return 0.3


def relation_valence(rel: Optional[Dict[str, Any]]) -> str:
    """关系边的价 ∈ {allied, adversarial, transactional, directional, neutral}。

    优先读显式 ``valence``；否则按 type 推（_REL_TYPE_VALENCE）；OTHER/未知 → "neutral"。
    让「盟友 != 对手」「供应商 != 制裁方」在跟随图/情感计算里被正确区分。
    """
    if not isinstance(rel, dict):
        return "neutral"
    raw = str(rel.get("valence", "") or "").strip().lower()
    if raw in _VALENCE_POLARITY:
        return raw
    typ = str(rel.get("type", "") or "").strip().upper()
    return _REL_TYPE_VALENCE.get(typ, "neutral")


def relation_polarity(rel: Optional[Dict[str, Any]]) -> float:
    """关系边的极性 ∈ [-1,1]：优先读显式 ``polarity``，否则从价推（按 strength 缩放）。

    缺省映射：allied→+0.4 / adversarial→-0.4 / transactional→+0.15 / 其余→0.0。
    strength=high/medium/low → ×1.0/0.7/0.45（让强盟友比弱盟友极性更高）。
    """
    if not isinstance(rel, dict):
        return 0.0
    raw = rel.get("polarity")
    if isinstance(raw, bool):
        raw = None
    if isinstance(raw, (int, float)):
        return max(-1.0, min(1.0, float(raw)))
    base = _VALENCE_POLARITY.get(relation_valence(rel), 0.0)
    if base == 0.0:
        return 0.0
    strength = str(rel.get("strength", "") or "").strip().lower()
    scale = 1.0
    if strength in ("high", "高"):
        scale = 1.0
    elif strength in ("medium", "med", "中"):
        scale = 0.7
    elif strength in ("low", "低"):
        scale = 0.45
    return max(-1.0, min(1.0, base * scale))


# relational_roster 的 10 个命名桶 → (关系类型集合, 方向)。方向语义：
#   "out"  = 我是 source 时该 target 入桶；
#   "in"   = 我是 target 时该 source 入桶；
#   "both" = 任一端皆入桶（对称关系：竞争/对立等）。
# 同一类型可同时供应多个桶（如 SUPPLIES：我作为 supplier 的 target 是 customer；
# 我作为 customer 的 source 是 supplier）。
_ROSTER_RULES: Dict[str, List[tuple]] = {
    "allies": [("ALLY_OF", "both"), ("PARTNERS_WITH", "both"), ("SUPPORTS", "in"), ("ENDORSES", "in")],
    "opponents": [("OPPOSES", "both"), ("SANCTIONS", "in"), ("CRITICIZES", "in"),
                  ("LITIGATES_AGAINST", "both")],
    "competitors": [("COMPETES_WITH", "both")],
    # 我的客户：我是 SUPPLIES 的 source，或我是 CUSTOMER_OF 的 target，或 CONSUMES 的 target。
    "customers": [("SUPPLIES", "out"), ("CUSTOMER_OF", "in"), ("CONSUMES", "in")],
    # 我的供应商：我是 SUPPLIES 的 target，或我是 CUSTOMER_OF 的 source，或 CONSUMES 的 source。
    "suppliers": [("SUPPLIES", "in"), ("CUSTOMER_OF", "out"), ("CONSUMES", "out"), ("DEPENDS_ON", "out")],
    # 我的出资方/投资人：我是 FUNDS/INVESTS_IN/BACKS 的 target。
    "backers_investors": [("FUNDS", "in"), ("INVESTS_IN", "in"), ("BACKS", "in")],
    # 我的支持者：SUPPORTS/ENDORSES 的 source。
    "supporters": [("SUPPORTS", "out"), ("ENDORSES", "out")],
    # 监管我的方：REGULATES 的 source（我被监管）。
    "regulators": [("REGULATES", "in")],
    # 依赖我的方：DEPENDS_ON 的 source（依赖方），或我 SUPPLIES 的 target（下游对我有依赖）。
    "dependents": [("DEPENDS_ON", "in"), ("SUPPLIES", "out")],
    "partners": [("PARTNERS_WITH", "both")],
}


def _rel_strength_text(rel: Dict[str, Any]) -> str:
    """关系行的强度文本（兼容 strength；缺省空串）。"""
    return str(rel.get("strength", "") or "").strip()


def relational_roster(actor_name: str, actors: Optional[Any]) -> Dict[str, List[Dict[str, Any]]]:
    """把 relationships[] 投影为以 ``actor_name`` 为中心的 10 个命名关系桶。

    每桶为 [{name, basis, strength}]，按 relationships[] 的出现序去重（同名只取首条）。
    端点用 normalize_name 与 actor 表对齐（兼容别名）。无关系/无匹配返回 10 个空桶。

    桶含义（站在 actor_name 视角）：allies/opponents/competitors/customers/suppliers/
    backers_investors/supporters/regulators/dependents/partners。
    """
    buckets: Dict[str, List[Dict[str, Any]]] = {k: [] for k in _ROSTER_RULES}
    if not actor_name:
        return buckets
    rows = extract_relationship_rows(actors)
    if not rows:
        return buckets
    me = normalize_name(actor_name)
    if not me:
        return buckets
    # 每桶已收名集合（去重）。
    seen: Dict[str, set] = {k: set() for k in _ROSTER_RULES}

    def add(bucket: str, other_raw: Any, rel: Dict[str, Any]) -> None:
        name = str(other_raw or "").strip()
        if not name:
            return
        key = normalize_name(name)
        if not key or key == me or key in seen[bucket]:
            return
        seen[bucket].add(key)
        buckets[bucket].append({
            "name": name,
            "basis": str(rel.get("basis", "") or "").strip(),
            "strength": _rel_strength_text(rel),
        })

    for r in rows:
        typ = str(r.get("type", "") or "").strip().upper()
        s_raw, t_raw = r.get("source"), r.get("target")
        s, t = normalize_name(str(s_raw or "")), normalize_name(str(t_raw or ""))
        i_am_source = (s == me)
        i_am_target = (t == me)
        if not (i_am_source or i_am_target):
            continue
        for bucket, rules in _ROSTER_RULES.items():
            for rtype, direction in rules:
                if rtype != typ:
                    continue
                if direction == "out" and i_am_source:
                    add(bucket, t_raw, r)
                elif direction == "in" and i_am_target:
                    add(bucket, s_raw, r)
                elif direction == "both":
                    if i_am_source:
                        add(bucket, t_raw, r)
                    if i_am_target:
                        add(bucket, s_raw, r)
    return buckets


# roster_block 的桶 → 中文小标题（按谈判/竞争语义排序，最实用的在前）。
_ROSTER_BUCKET_LABEL = (
    ("allies", "盟友"),
    ("partners", "伙伴"),
    ("supporters", "支持者"),
    ("backers_investors", "出资方/投资人"),
    ("customers", "客户/下游"),
    ("suppliers", "供应商/上游"),
    ("dependents", "依赖你的方"),
    ("competitors", "竞争对手"),
    ("opponents", "对手/对立方"),
    ("regulators", "监管你的方"),
)


def roster_block(actor_name: str, actors: Optional[Any], max_per_bucket: int = 5) -> str:
    """把 relational_roster 渲染为「## 关系网角色」提示块；无任何关系返回空串。

    比 relationship_briefing 更结构化：按盟友/对手/客户/供应商等分组列出真实命名对手方，
    让 persona 在互动时能精确 @ 到正确阵营。每桶截断到 max_per_bucket。
    """
    roster = relational_roster(actor_name, actors)
    lines: List[str] = []
    for bucket, label in _ROSTER_BUCKET_LABEL:
        items = roster.get(bucket) or []
        if not items:
            continue
        names: List[str] = []
        for it in items[:max_per_bucket]:
            nm = str(it.get("name", "") or "").strip()
            if not nm:
                continue
            strength = str(it.get("strength", "") or "").strip()
            names.append(f"{nm}（{strength}）" if strength else nm)
        if names:
            lines.append(f"- {label}：" + "、".join(names))
    if not lines:
        return ""
    return "## 关系网角色（调研实证：互动时据此 @ 正确阵营）\n" + "\n".join(lines)


def _dna_str_list(value: Any, limit: int) -> List[str]:
    """取出非空字符串列表（容错：非 list 返回 []，逐项 strip 去空）。"""
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for x in value:
        s = str(x or "").strip()
        if s:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def behavioral_dna_block(actor: Optional[Dict[str, Any]]) -> str:
    """把 worldview/incentives/resources/risk_tolerance 渲染为「人格底座」提示块。

    缺全部字段时返回空串（旧档案输出不变）。让 persona 从「立场标签」升级为有价值观、
    信念、得失结构（incentives 的 driver/gains_if/loses_if）与风险偏好的稳定人格。
    """
    if not isinstance(actor, dict):
        return ""
    parts: List[str] = []

    wv = actor.get("worldview")
    if isinstance(wv, dict):
        identity = str(wv.get("identity", "") or "").strip()
        frame = str(wv.get("frame", "") or "").strip()
        values = _dna_str_list(wv.get("values"), 6)
        beliefs = _dna_str_list(wv.get("beliefs"), 6)
        if identity:
            parts.append(f"- 身份认同: {identity}")
        if frame:
            parts.append(f"- 看待问题的框架: {frame}")
        if values:
            parts.append("- 核心价值观: " + "；".join(values))
        if beliefs:
            parts.append("- 核心信念: " + "；".join(beliefs))

    incentives = actor.get("incentives")
    if isinstance(incentives, list) and incentives:
        inc_lines: List[str] = []
        for inc in incentives[:6]:
            if isinstance(inc, dict):
                driver = str(inc.get("driver", "") or "").strip()
                gains = str(inc.get("gains_if", "") or "").strip()
                loses = str(inc.get("loses_if", "") or "").strip()
                intensity = str(inc.get("intensity", "") or "").strip()
                if not (driver or gains or loses):
                    continue
                seg = f"  - {driver}" if driver else "  - 动机"
                tail: List[str] = []
                if gains:
                    tail.append(f"得益于「{gains}」")
                if loses:
                    tail.append(f"受损于「{loses}」")
                if tail:
                    seg += "：" + "，".join(tail)
                if intensity:
                    seg += f"（强度 {intensity}）"
                inc_lines.append(seg)
            else:
                s = str(inc or "").strip()  # 容忍纯字符串写法
                if s:
                    inc_lines.append(f"  - {s}")
        if inc_lines:
            parts.append("- 激励结构（得失驱动）:")
            parts.extend(inc_lines)

    # resources 是 assets 的超集/别名：优先 resources，回退 assets。
    resources = _dna_str_list(actor.get("resources"), 8) or _dna_str_list(actor.get("assets"), 8)
    if resources:
        parts.append("- 可调动资源: " + "；".join(resources))

    risk = str(actor.get("risk_tolerance", "") or "").strip()
    if risk:
        parts.append(f"- 风险偏好: {risk}")

    for label, dimension, aliases in (
        ("研究确认的价值观/世界观", "values_worldview", ("values_worldview",)),
        ("研究确认的激励", "incentives", ("intelligence_incentives",)),
        ("研究确认的深层动机", "motivations", ("motivations",)),
        ("研究确认的操作偏好", "operational_preferences", ("preferences",)),
    ):
        claims = actor_intelligence_claims(actor, dimension, *aliases, limit=3)
        if claims:
            parts.append(f"- {label}: " + "；".join(claims))

    if not parts:
        return ""
    return "## 行为 DNA（持久人格底座，决策时据此保持一致的价值观与得失计算）\n" + "\n".join(parts)


def build_initial_follow_graph(
    actors: Optional[Any],
    agent_id_by_name: Dict[str, int],
) -> List[List[int]]:
    """relationships[] → 去重后的初始关注边 [[follower_id, followee_id]]。

    ``agent_id_by_name`` 的键应已 ``normalize_name`` 标准化。关注方向遵循 EXECPLAN §2
    的方向表。端点无法解析 / 自环一律跳过；空数据返回 []。
    """
    rows = extract_relationship_rows(actors)
    pairs: set = set()

    def aid(n: Any) -> Optional[int]:
        return agent_id_by_name.get(normalize_name(str(n)))

    for r in rows:
        s, d = aid(r.get("source")), aid(r.get("target"))
        typ = str(r.get("type", "")).upper()
        if s is None or d is None or s == d:
            continue
        si = influence_weight(match_actor(str(r.get("source", "")), actors)) or 1.0
        ti = influence_weight(match_actor(str(r.get("target", "")), actors)) or 1.0
        if typ == "ALLY_OF":
            # 低影响力 → 关注高影响力
            pairs.add((s, d) if si <= ti else (d, s))
        elif typ in ("PARTNERS_WITH", "OPPOSES", "COMPETES_WITH"):
            pairs.add((s, d))
            pairs.add((d, s))
        elif typ == "DEPENDS_ON":
            pairs.add((s, d))           # 依赖方关注被依赖方
        elif typ == "INFLUENCES":
            pairs.add((d, s))           # 受众关注影响者
        elif typ == "REGULATES":
            pairs.add((s, d))           # 监管方关注被监管方（监控）
        # ---- ONTOLOGY 扩展类型（旧 8 类无新字段时上面已 continue / 命中，下面纯属增量）----
        elif typ in ("SUPPLIES", "CUSTOMER_OF"):
            # 依赖侧关注供给侧：SUPPLIES(source=供应商) → 客户(d) 关注供应商(s)；
            # CUSTOMER_OF(source=客户) → 客户(s) 关注供应商(d)。
            pairs.add((d, s) if typ == "SUPPLIES" else (s, d))
        elif typ in ("FUNDS", "INVESTS_IN", "BACKS"):
            pairs.add((d, s))           # 受资助/被投/被扶持方关注其出资方/投资人/后台
        elif typ == "OWNS":
            pairs.add((d, s))           # 被持有方关注其所有者
        elif typ in ("SUPPORTS", "ENDORSES"):
            pairs.add((d, s))           # 被支持/被背书方关注支持者/背书者
        elif typ in ("SANCTIONS", "LITIGATES_AGAINST", "CRITICIZES"):
            # 制裁/诉讼/批评：双向监视（被针对方紧盯发起方，发起方也持续盯目标）
            pairs.add((s, d))
            pairs.add((d, s))
        # REPORTS_ON / CONSUMES：报道者/消费者不应被建成能动 agent 的关注边（无 follow）。
    return [list(p) for p in pairs]


def situation_brief(actors: Optional[Any], max_actors: int = 25, max_chars: int = 6000) -> str:
    """报告用「背景档案」整体渲染（EXECPLAN T4.1）。

    把研究档案压成一段权威背景，钉进 ReportAgent 的提示词，省去报告阶段对全套
    cast/关系/时间线的盲搜：central_question + as_of_date + 局势简报 + 角色表 +
    角色关系 + 关键时间线 + 热点。空档案返回空串。
    """
    if not isinstance(actors, dict):
        return ""
    lines: List[str] = []
    cq = str(actors.get("central_question", "") or "").strip()
    aod = str(actors.get("as_of_date", "") or "").strip()
    if cq:
        lines.append(f"**核心问题**：{cq}")
    if aod:
        lines.append(f"**研究截止日 (as-of)**：{aod}")

    sb = situation_brief_block(actors)
    if sb:
        lines.append(sb)

    rows = extract_actor_rows(actors)
    if rows:
        lines.append("## 关键角色（调研实证）")
        for r in rows[:max_actors]:
            name = str(r.get("name", "?"))
            typ = str(r.get("type", "") or "")
            role = str(r.get("role", "") or "")
            stance = str(r.get("stance", "") or "")
            infl = str(r.get("influence", "") or "")
            seg = f"- {name}（{typ}）"
            if role:
                seg += f" 角色: {role}"
            if stance:
                seg += f" | 立场: {stance}"
            if infl:
                seg += f" | 影响力: {infl}"
            lines.append(seg)

    rels = extract_relationship_rows(actors)
    if rels:
        lines.append("## 角色关系（有向，调研实证）")
        for r in rels[:40]:
            typ = str(r.get("type", "")).upper()
            label = REL_LABEL.get(typ, typ or "关联")
            strength = str(r.get("strength", "") or "")
            basis = str(r.get("basis", "") or "")
            seg = f"- {r.get('source')} --[{label}]--> {r.get('target')}"
            if strength:
                seg += f"（{strength}）"
            if basis:
                seg += f": {basis}"
            lines.append(seg)

    events = actors.get("key_events")
    if isinstance(events, list) and events:
        lines.append("## 关键时间线（调研实证）")
        for ev in events[:20]:
            if isinstance(ev, dict):
                date = str(ev.get("date", "") or "")
                desc = str(ev.get("event", "") or "")
                if desc:
                    lines.append(f"- {date} {desc}".strip())

    topics = actors.get("hot_topics")
    if isinstance(topics, list) and topics:
        lines.append("## 热点议题（调研实证）")
        lines.append("、".join(str(t) for t in topics[:15]))

    brief = "\n".join(lines)
    if len(brief) > max_chars:
        brief = brief[:max_chars] + "\n…(背景档案已截断)"
    return brief


def events_to_schedule(
    actors: Optional[Any],
    total_rounds: int,
    as_of_date: Optional[str],
    horizon_days: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """key_events → [{round, event, date}]，映射到 [0, total_rounds)。早于 as_of 的事件跳过。

    ``horizon_days`` 缺省时取「最远未来事件距 as_of 的天数」为视界。as_of 不可解析 / 无事件
    时返回 []（永不抛异常）。
    """
    from .dates import parse_as_of  # T2.3 helper（同包相对导入，匹配代码库约定）

    if not isinstance(actors, dict) or total_rounds <= 0:
        return []
    base = parse_as_of(as_of_date)
    if base is None:
        return []
    evs = actors.get("key_events") or []
    if not isinstance(evs, list):
        return []

    spans: List[int] = []
    for e in evs:
        if not isinstance(e, dict):
            continue
        d = parse_as_of(e.get("date"))
        if d is None:
            continue
        span = (d - base).days
        if span >= 0:
            spans.append(span)
    hz = horizon_days or (max(spans) if spans else 1) or 1

    # PREP-5: 反应缓冲。hz 缺省取"最远未来事件的跨度"时，最远事件必然映到
    # round(span/hz*total_rounds)=total_rounds → 被夹到最后一轮——高潮事件永远落在收官轮，
    # agent 零轮可反应，事件形同虚设。把映射压进 [0, total_rounds-REACT_BUFFER] 窗口，
    # 给最远事件留出 max(2, total_rounds//5) 轮的反应期。旗标关闭时回到旧映射。
    effective_rounds = total_rounds
    try:
        from ..config import Config as _Cfg  # 延迟导入，避免 utils→config 顶层环依赖
        _buffered = bool(getattr(_Cfg, "SIM_EVENT_REACT_BUFFER", True))
    except Exception:
        _buffered = True
    if _buffered:
        effective_rounds = max(1, total_rounds - max(2, total_rounds // 5))

    out: List[Dict[str, Any]] = []
    for e in evs:
        if not isinstance(e, dict):
            continue
        d = parse_as_of(e.get("date"))
        if d is None:
            continue
        span = (d - base).days
        if span < 0:
            continue
        out.append({
            "round": min(total_rounds - 1, round(span / hz * effective_rounds)),
            "event": e.get("event"),
            "date": e.get("date"),
        })
    return out


def events_to_calendar_rounds(
    actors: Optional[Any],
    round_dates: List[Any],
    as_of_date: Optional[Any],
    horizon_date: Optional[Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """TEMPORAL spec §4: key_events → 日历回合精确落轮（与 ``events_to_schedule`` 并列）。

    小时制的 ``events_to_schedule`` 按比例把日期压进轮数窗口；日历模式下每轮对应真实
    日历区间，事件改用 ``sim_timeline.round_for_date`` 做区间包含定位——不做比例压缩、
    不做 PREP-5 反应缓冲（日历模式 fire_scheduled_events 在每轮 agent 激活前触发，
    同期反应有保障）。

    逐条 ``key_events[]`` 的处理：

    * 日期经 ``parse_as_of`` 解析；不可解析 → 排除（调用方按同一解析器统计并记
      ``event_date_unparsed:<n>`` warning 到 temporal_config.warnings）；
    * ``d ≤ as_of`` → 丢弃（沿用 events_to_schedule 的既有政策）；
    * ``d > horizon`` → 完整条目追加到第二个返回值（beyond_horizon_events 留档）；
    * 其余 → 精确落到包含该日期的回合。

    返回 ``(scheduled, beyond_horizon)``：scheduled 形如 ``[{"round","event","date"}]``
    （与 events_to_schedule 输出同形，poster 字段由调用方补齐）；beyond_horizon 是
    原始事件 dict 的浅拷贝列表。``round_dates`` 兼容 RoundPeriod 与 JSON dict 行。
    任何入参非法 → ``([], [])``，永不抛异常。
    """
    from .dates import parse_as_of  # 同包相对导入，匹配 events_to_schedule 的约定
    from .sim_timeline import round_for_date

    if not isinstance(actors, dict) or not round_dates:
        return [], []
    base = parse_as_of(as_of_date)
    horizon = parse_as_of(horizon_date)
    if base is None or horizon is None:
        return [], []
    base_d = base.date()
    horizon_d = horizon.date()
    evs = actors.get("key_events")
    if not isinstance(evs, list):
        return [], []

    scheduled: List[Dict[str, Any]] = []
    beyond: List[Dict[str, Any]] = []
    for e in evs:
        if not isinstance(e, dict):
            continue
        parsed = parse_as_of(e.get("date"))
        if parsed is None:
            continue  # 不可解析 → 排除（warning 由调用方统计）
        d = parsed.date()
        if d <= base_d:
            continue  # 早于/等于研究截止日 → 丢弃（既有政策）
        if d > horizon_d:
            beyond.append(dict(e))  # 晚于判定日 → 完整留档，不落轮
            continue
        r = round_for_date(d, round_dates)
        if r is None:
            continue  # 防御：区间数据异常时静默跳过（永不抛异常）
        scheduled.append({
            "round": int(r),
            "event": e.get("event"),
            "date": e.get("date"),
        })
    return scheduled, beyond


# ---------------------------------------------------------------------------
# 来源分层 + 证据定级（EXECPLAN2 I-0-0）
# ---------------------------------------------------------------------------

# 规范化的来源层级顺序（S1=最强证据 … S4=最弱）。其余值归入「未分层」。
SOURCE_TIERS = ("S1", "S2", "S3", "S4")
# 层级 → 中文释义（索引头部说明用）
_TIER_DESC = {
    "S1": "一手/权威",
    "S2": "可靠二手",
    "S3": "一般媒体",
    "S4": "低可信/未证实",
}


def _norm_tier(value: Any) -> str:
    """把自由文本的 tier 归一化为 S1..S4；无法识别返回空串（→「未分层」）。"""
    s = str(value or "").strip().upper()
    if not s:
        return ""
    # 容忍 "S1"/"s1"/"tier 1"/"1"/"S1（一手）" 等写法
    m = re.search(r"S?\s*([1-4])", s)
    if m:
        return "S" + m.group(1)
    return ""


def extract_source_rows(sources: Optional[Any]) -> List[Dict[str, Any]]:
    """从来源容器安全取出来源行列表（容错任意脏数据）。

    ``sources`` 可为：sources.json 的顶层 list、或 actors.json 里嵌套的
    ``{"sources": [...]}``。非法形状一律返回 []，绝不抛异常。
    """
    rows: Any = sources
    if isinstance(sources, dict):
        rows = sources.get("sources")
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict) and (r.get("title") or r.get("url"))]


def source_tier_histogram(sources: Optional[Any]) -> Dict[str, int]:
    """统计各层级来源数量 → {s1_count, s2_count, s3_count, s4_count, untiered_count}。

    供 meta.json 观测：让覆盖率门可据此拒绝「全是 S4」的报告。空数据返回全 0。
    """
    hist = {"s1_count": 0, "s2_count": 0, "s3_count": 0, "s4_count": 0, "untiered_count": 0}
    for r in extract_source_rows(sources):
        tier = _norm_tier(r.get("tier"))
        if tier:
            hist[tier.lower() + "_count"] += 1
        else:
            hist["untiered_count"] += 1
    return hist


def sources_index_tiered(sources: Optional[Any], max_sources: int = 40) -> str:
    """按 S1-S4 分层渲染可引用来源索引；缺省/空数据返回空串（→ 调用方回退旧逻辑）。

    引用记号形如 ``[S1-a]`` / ``[S2-b]``（层级 + 该层内字母序），并附日期与独立性，
    让报告代理优先引用 S1/S2 证据、并能在正文按真实层级标注，而不是按位置伪造 [S1]。
    """
    rows = extract_source_rows(sources)
    if not rows:
        return ""

    # 分桶：S1..S4 按序，未分层归入末尾的 "S?" 桶
    buckets: Dict[str, List[Dict[str, Any]]] = {t: [] for t in SOURCE_TIERS}
    buckets["S?"] = []
    used = 0
    for r in rows:
        if used >= max_sources:
            break
        tier = _norm_tier(r.get("tier")) or "S?"
        buckets[tier].append(r)
        used += 1

    lines = ["【可引用来源（按证据层级；正文用 [S1-a]/[S2-b] 形式标注，优先引用高层级）】"]
    letters = "abcdefghijklmnopqrstuvwxyz"
    for tier in (*SOURCE_TIERS, "S?"):
        items = buckets.get(tier) or []
        if not items:
            continue
        if tier == "S?":
            lines.append("— 未分层来源")
        else:
            lines.append(f"— {tier}（{_TIER_DESC.get(tier, '')}）")
        for i, s in enumerate(items):
            tag = letters[i] if i < len(letters) else str(i)
            ref = f"[{tier}-{tag}]"
            title = str(s.get("title", "") or "").strip()
            url = str(s.get("url", "") or "").strip()
            date = str(s.get("date", "") or "").strip()
            seg = f"{ref} {title}".rstrip()
            extras: List[str] = []
            if date:
                extras.append(date)
            if s.get("independent") is False:
                extras.append("非独立")
            if extras:
                seg += f"（{'，'.join(extras)}）"
            if url:
                seg += f" — {url}"
            lines.append(seg)
    return "\n".join(lines) if len(lines) > 1 else ""


def sources_index_tiered_map(sources: Optional[Any],
                             max_sources: int = 40) -> Dict[str, Dict[str, Any]]:
    """复现 sources_index_tiered 的分桶/字母序，返回 ``{"S1-a": 来源行, ...}`` 记号映射。

    供旧式（REPORT_CITATION_SINGLE_GRAMMAR=false）路径解析分层记号；与渲染函数
    逐字节同序（同样的 max_sources 截取 + 桶内字母序）。空数据返回 {}。
    """
    rows = extract_source_rows(sources)
    if not rows:
        return {}
    buckets: Dict[str, List[Dict[str, Any]]] = {t: [] for t in SOURCE_TIERS}
    buckets["S?"] = []
    used = 0
    for r in rows:
        if used >= max_sources:
            break
        tier = _norm_tier(r.get("tier")) or "S?"
        buckets[tier].append(r)
        used += 1
    letters = "abcdefghijklmnopqrstuvwxyz"
    out: Dict[str, Dict[str, Any]] = {}
    for tier in (*SOURCE_TIERS, "S?"):
        for i, s in enumerate(buckets.get(tier) or []):
            tag = letters[i] if i < len(letters) else str(i)
            out[f"{tier}-{tag}"] = s
    return out


def _raw_source_rows(sources: Optional[Any]) -> List[Any]:
    """取出**保位置**的原始来源列表（含非法行，编号按原始下标对齐 _source_haystacks）。

    与 extract_source_rows 不同：不过滤非 dict 行——统一引用语法 [S<n>] 的 n 是来源在
    原始列表中的 1 起位置，过滤会让编号漂移、与回填/悬空修复的位置锚定失配。
    """
    rows: Any = sources
    if isinstance(sources, dict):
        rows = sources.get("sources")
    return rows if isinstance(rows, list) else []


def _source_cited_in_research(row: Dict[str, Any], research_norm: str) -> bool:
    """相关性排序信号：该来源的 URL 片段或标题是否出现在研究报告正文里。

    仅用于排序（决定哪些来源进入注入索引），非精确匹配也无碍——宁可多选不漏选。
    """
    if not research_norm:
        return False
    url = str(row.get("url", "") or "").strip().lower()
    if url:
        frag = re.sub(r"^https?://", "", url).rstrip("/")
        if len(frag) >= 12 and frag in research_norm:
            return True
    title = str(row.get("title", "") or "").strip().lower()
    return bool(len(title) >= 8 and title in research_norm)


def _source_evidence_preview(row: Dict[str, Any], max_chars: int = 280) -> str:
    """Render a bounded, source-specific fact preview for citation selection."""
    parts: List[str] = []
    supports = row.get("supports")
    if isinstance(supports, list):
        parts.extend(str(value).strip() for value in supports[:3] if str(value).strip())
    elif isinstance(supports, str) and supports.strip():
        parts.append(supports.strip())
    for key in ("excerpt", "snippet"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    if not parts:
        return ""
    preview = "; ".join(dict.fromkeys(
        re.sub(r"\s+", " ", part).replace("|", "\\|") for part in parts
    ))
    limit = max(40, int(max_chars))
    return preview if len(preview) <= limit else preview[:limit - 1].rstrip() + "…"


def sources_index_unified(
    sources: Optional[Any],
    research_report: Optional[str] = None,
    max_sources: int = 60,
) -> "tuple[str, Dict[str, Dict[str, Any]]]":
    """单一引用语法渲染：→ ``(索引文本, {"S<n>": 来源行})``；空数据返回 ("", {})。

    设计（WAVE10 无缝引用）：
      * 正文引用记号只有一种形状——裸 [S<n>]，n = 来源在**原始列表**中的位置（1 起、
        固定不变）。分层记号 [S1-a] 降级为标题后的展示注记（层级仍可见，语法不再分叉）。
      * 相关性排序截取：研究报告中被实际引用（URL/标题命中）的来源优先，其次按证据
        层级（S1→S4→未分层），再按原始顺序；截取 max_sources 条后**按编号升序**渲染
        （编号不连续无妨——索引头已声明编号固定）。
    """
    raw = _raw_source_rows(sources)
    if not raw:
        return "", {}
    research_norm = re.sub(r"\s+", " ", str(research_report or "")).lower()
    tier_rank = {"S1": 1, "S2": 2, "S3": 3, "S4": 4}
    candidates: List["tuple[int, int, int, Dict[str, Any]]"] = []
    for pos, row in enumerate(raw, 1):
        if not isinstance(row, dict) or not (row.get("title") or row.get("url")):
            continue
        cited = 0 if _source_cited_in_research(row, research_norm) else 1
        rank = tier_rank.get(_norm_tier(row.get("tier")), 5)
        candidates.append((cited, rank, pos, row))
    if not candidates:
        return "", {}
    candidates.sort(key=lambda c: (c[0], c[1], c[2]))
    selected = sorted(candidates[:max(1, int(max_sources))], key=lambda c: c[2])

    lines = ["【可引用来源（正文引用一律用形如 [S12] 的数字编号标注；"
             "编号固定，不得自创或改写编号）】"]
    tag_map: Dict[str, Dict[str, Any]] = {}
    for _cited, _rank, pos, row in selected:
        tag = f"S{pos}"
        tag_map[tag] = row
        title = str(row.get("title", "") or "").strip()
        url = str(row.get("url", "") or "").strip()
        seg = f"[{tag}] {title}".rstrip()
        extras: List[str] = []
        tier = _norm_tier(row.get("tier"))
        if tier:
            extras.append(f"{tier}·{_TIER_DESC.get(tier, '')}")
        date = str(row.get("date", "") or "").strip()
        if date:
            extras.append(date)
        if row.get("independent") is False:
            extras.append("非独立")
        if extras:
            seg += f"（{'，'.join(extras)}）"
        if url:
            seg += f" — {url}"
        evidence = _source_evidence_preview(row)
        if evidence:
            seg += f" ｜supports: {evidence}"
        lines.append(seg)
    return ("\n".join(lines) if len(lines) > 1 else ""), tag_map


def actor_grade(actor: Optional[Dict[str, Any]]) -> str:
    """取出 actor/relationship 行上的可选 Admiralty 定级（如 "B2"）；缺失返回空串。"""
    if not isinstance(actor, dict):
        return ""
    g = str(actor.get("grade", "") or "").strip().upper()
    # 容错：仅接受形如「字母+数字」的 Admiralty 记号，其余忽略
    return g if re.fullmatch(r"[A-F][1-6]", g) else ""


# ---------------------------------------------------------------------------
# 结构化定量事实表（EXECPLAN2 I-0-5）
# ---------------------------------------------------------------------------


def extract_quantitative_rows(actors: Optional[Any]) -> List[Dict[str, Any]]:
    """从 actors.json 安全取出 quantitative_facts 行（需至少有 metric 与 value）。"""
    if not isinstance(actors, dict):
        return []
    rows = actors.get("quantitative_facts")
    if not isinstance(rows, list):
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        if isinstance(r, dict) and str(r.get("metric", "") or "").strip() and \
                str(r.get("value", "") or "").strip():
            out.append(r)
    return out


# typed 表「类型」列的中文标签（quant_typing.quant_class 的三类）。
_QUANT_CLASS_LABELS_ZH = {"reported": "已报告", "projected": "预期", "unknown": "未定"}


def quantitative_facts_block(actors: Optional[Any], max_facts: int = 20, *,
                             typed: bool = False) -> str:
    """把 quantitative_facts 渲染为紧凑的中文 markdown 表；缺省返回空串。

    每行携带单位 + as-of 日 + 定义 + 来源/层级，报告代理可直接引用精确、带日期、
    有定义的数字，无需再次联网检索，亦避免 SKILL §6 警示的「定义漂移」。

    typed=True（RESEARCH-5，供选择接入的报告侧调用方）：增加「类型」列（已报告 / 预期 /
    未定，quant_typing.quant_class 以 actors.as_of_date 为基准判定），日期列改为数据期
    （目标日 → 期末 → as-of，quant_typing.reference_period），使预测的目标年不再被读成
    实测值的时点。typed=False 与旧输出逐字节一致。
    """
    rows = extract_quantitative_rows(actors)
    if not rows:
        return ""
    rows = rows[:max_facts]
    if typed:
        from .dates import parse_as_of  # 同包相对导入，匹配代码库约定
        from .quant_typing import quant_class, reference_period
        as_of = parse_as_of(actors.get("as_of_date"))
        as_of_day = as_of.date() if as_of is not None else None
        lines = ["## 定量事实（深度研究数据；类型=已报告/预期/未定，预期值须注明预期方与目标期）",
                 "| 指标 | 数值 | 单位 | 数据期 | 类型 | 定义 | 来源 |",
                 "| --- | --- | --- | --- | --- | --- | --- |"]
    else:
        lines = ["## 定量事实（深度研究实证，引用时务必带单位与 as-of 日）",
                 "| 指标 | 数值 | 单位 | as-of | 定义 | 来源 |",
                 "| --- | --- | --- | --- | --- | --- |"]

    def cell(v: Any) -> str:
        # markdown 表格安全：转义竖线、压平换行
        return str(v or "").replace("|", "\\|").replace("\n", " ").strip()

    for r in rows:
        src = cell(r.get("source"))
        tier = _norm_tier(r.get("tier"))
        if tier and src:
            src = f"{src}（{tier}）"
        elif tier:
            src = tier
        if typed:
            lines.append("| " + " | ".join((
                cell(r.get("metric")) or "?", cell(r.get("value")), cell(r.get("unit")),
                cell(reference_period(r)), _QUANT_CLASS_LABELS_ZH[quant_class(r, as_of_day)],
                cell(r.get("definition")), src,
            )) + " |")
            continue
        lines.append(
            "| {metric} | {value} | {unit} | {as_of} | {definition} | {source} |".format(
                metric=cell(r.get("metric")) or "?",
                value=cell(r.get("value")),
                unit=cell(r.get("unit")),
                as_of=cell(r.get("as_of_date")),
                definition=cell(r.get("definition")),
                source=src,
            )
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 争议证据 / 证据冲突（EXECPLAN2 I-0-1）
# ---------------------------------------------------------------------------

# 合法的争议状态枚举；其余值在渲染时原样保留但不参与白名单。
CONTESTED_STATUS = ("confirmed", "contested", "speculative", "single-origin")
_STATUS_LABEL = {
    "confirmed": "已证实",
    "contested": "存在争议",
    "speculative": "推测性",
    "single-origin": "单一信源",
}


def extract_contested_rows(actors: Optional[Any]) -> List[Dict[str, Any]]:
    """安全取出 contested_claims 行（需有非空 claim）。

    每条要么 positions 含 >=2 个立场，要么 status 标为 single-origin，否则视为
    噪声（避免模型把琐碎分歧也列为争议）。形状不符一律剔除。
    """
    if not isinstance(actors, dict):
        return []
    rows = actors.get("contested_claims")
    if not isinstance(rows, list):
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        claim = str(r.get("claim", "") or "").strip()
        if not claim:
            continue
        positions = r.get("positions")
        positions = [p for p in positions if isinstance(p, dict)] if isinstance(positions, list) else []
        status = str(r.get("status", "") or "").strip().lower()
        if len(positions) >= 2 or status == "single-origin":
            out.append(r)
    return out


def contested_claims_block(actors: Optional[Any], max_claims: int = 8) -> str:
    """把 contested_claims 渲染为「争议证据」块；缺省返回空串。

    报告呈现「冲突而非平均」、模拟可据此给 agent 植入真实对立信念。
    """
    rows = extract_contested_rows(actors)
    if not rows:
        return ""
    rows = rows[:max_claims]
    out: List[str] = ["## 争议证据（深度研究：冲突而非平均，撰写时显式呈现分歧及缘由）"]
    for r in rows:
        claim = str(r.get("claim", "") or "").strip()
        status = str(r.get("status", "") or "").strip().lower()
        label = _STATUS_LABEL.get(status, status or "")
        head = f"- 声明：{claim}"
        if label:
            head += f"（{label}）"
        out.append(head)
        positions = r.get("positions")
        if isinstance(positions, list):
            for p in positions:
                if not isinstance(p, dict):
                    continue
                stance = str(p.get("stance", "") or "").strip()
                if not stance:
                    continue
                srcs = p.get("sources")
                srcs = [str(x) for x in srcs if str(x or "").strip()] if isinstance(srcs, list) else []
                tier = _norm_tier(p.get("tier"))
                seg = f"  - 立场：{stance}"
                tags: List[str] = []
                if tier:
                    tags.append(tier)
                if srcs:
                    tags.append("、".join(srcs[:3]))
                if tags:
                    seg += f"（{' / '.join(tags)}）"
                out.append(seg)
        why = str(r.get("why_they_differ", "") or "").strip()
        if why:
            out.append(f"  - 分歧缘由：{why}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 预测输入：基率 / 驱动变量 / 可观测指标 / 情景（EXECPLAN2 I-0-2）
# ---------------------------------------------------------------------------

# 合法情景名（其余原样保留）
SCENARIO_NAMES = ("base", "upside", "downside")
_SCENARIO_LABEL = {"base": "基线", "upside": "上行", "downside": "下行"}


def extract_forecast_inputs(actors: Optional[Any]) -> Dict[str, List[Dict[str, Any]]]:
    """安全取出 forecast_inputs 的四类列表 → {base_rates, drivers, indicators, scenarios}。

    任一子键缺失/非法均降级为空列表；整体缺失返回四个空列表。
    """
    empty = {"base_rates": [], "drivers": [], "indicators": [], "scenarios": []}
    if not isinstance(actors, dict):
        return empty
    fi = actors.get("forecast_inputs")
    if not isinstance(fi, dict):
        return empty
    out: Dict[str, List[Dict[str, Any]]] = {}
    for key in ("base_rates", "drivers", "indicators", "scenarios"):
        lst = fi.get(key)
        out[key] = [x for x in lst if isinstance(x, dict)] if isinstance(lst, list) else []
    return out


def dossier_coverage(actors: Optional[Any]) -> Dict[str, Any]:
    """NEXTSTEPS P3-4：计算 actors.json 契约中**载荷字段**的覆盖率，让"空壳种子"可被发现。

    actors.py 让每个契约字段都可选并静默降级——这对鲁棒性正确，但一份每个 actor 都缺激励、
    或关系网无边的"空壳" dossier 会与一份丰富的 dossier 无差别地流过，把预测建在空地基上而毫无
    信号。本函数把它量化为可读指标（写进 meta.json / 经研究质量面板暴露 / 可触发 refine 或加宽
    不确定度）。纯函数；actors 为空/畸形时返回零骨架。

    返回既有关系/激励指标，以及 actor-intelligence/v1 每个关键维度的覆盖率。
    新指标是纯添加的，不会改变任何旧调用方所依赖的键或数值。
    """
    zero = {
        "n_actors": 0, "n_relationships": 0, "n_tier12": 0,
        "pct_actors_with_incentives": 0.0, "pct_tier12_with_worldview": 0.0,
        "pct_edges_valenced": 0.0, "edges_per_actor": 0.0, "salience_basis_present": 0.0,
        "n_actor_intelligence_v1": 0,
        "pct_actors_with_actor_intelligence": 0.0,
        "pct_tier12_with_complete_actor_intelligence": 0.0,
        "pct_intelligence_with_history": 0.0,
        "pct_intelligence_with_identity_history": 0.0,
        "pct_intelligence_with_track_record": 0.0,
        "pct_intelligence_with_values_worldview": 0.0,
        "pct_intelligence_with_incentives": 0.0,
        "pct_intelligence_with_motivations": 0.0,
        "pct_intelligence_with_capabilities": 0.0,
        "pct_intelligence_with_constraints": 0.0,
        "pct_intelligence_with_preferences": 0.0,
        "pct_intelligence_with_alliances": 0.0,
        "pct_intelligence_with_opponents_competitors": 0.0,
        "pct_intelligence_with_current_actions": 0.0,
        "pct_intelligence_with_future_plans": 0.0,
        "pct_intelligence_with_investments": 0.0,
        "pct_intelligence_with_decision_model": 0.0,
        "pct_intelligence_with_likely_actions": 0.0,
        "pct_intelligence_with_red_lines": 0.0,
        "pct_intelligence_with_knowledge_state": 0.0,
        "pct_intelligence_with_report_context": 0.0,
        "pct_intelligence_with_source_refs": 0.0,
        "pct_intelligence_with_provenance": 0.0,
        "pct_intelligence_with_evidence_gaps": 0.0,
        "pct_intelligence_with_producer_coverage": 0.0,
    }
    rows = extract_actor_rows(actors)
    n = len(rows)
    if n == 0:
        return zero

    def _truthy_field(a: Dict[str, Any], key: str) -> bool:
        v = a.get(key)
        return bool(v) if isinstance(v, (list, dict)) else bool(v)

    n_incent = sum(
        1 for a in rows
        if _truthy_field(a, "incentives")
        or actor_intelligence_dimension(a, "incentives", "intelligence_incentives")
    )
    tier12 = [a for a in rows if entity_simulation_tier(a) in (1, 2)]
    n_wv = sum(
        1 for a in tier12
        if (isinstance(a.get("worldview"), dict) and a.get("worldview"))
        or actor_intelligence_dimension(a, "values_worldview", "values_worldview")
    )
    n_sal = sum(1 for a in rows if _truthy_field(a, "salience"))

    intelligence_rows = [
        a for a in rows
        if actor_intelligence_payload(a).get("schema_version")
        == ACTOR_INTELLIGENCE_SCHEMA_VERSION
    ]
    intelligence_presence = [
        actor_intelligence_dimension_presence(a) for a in intelligence_rows
    ]
    critical_dimensions = (
        "identity_history", "values_worldview", "incentives", "motivations",
        "capabilities", "constraints", "preferences", "alliances",
        "opponents_competitors", "decision_model", "current_actions",
        "future_plans", "investments", "track_record", "likely_actions",
        "red_lines", "knowledge_state", "source_refs",
    )
    complete_tier12 = sum(
        1 for actor in tier12
        if actor_intelligence_payload(actor).get("schema_version")
        == ACTOR_INTELLIGENCE_SCHEMA_VERSION
        and all(
            actor_intelligence_dimension_presence(actor).get(dimension, False)
            for dimension in critical_dimensions
        )
    )

    def _intel_rate(dimension: str) -> float:
        if not intelligence_presence:
            return 0.0
        present = sum(1 for row in intelligence_presence if row.get(dimension))
        return round(present / len(intelligence_presence), 3)

    rels = extract_relationship_rows(actors)
    n_rels = len(rels)
    # 显式 valence 覆盖：只数携带 explicit valence/polarity 字段的边（区别于按类型推断的默认值），
    # 这正是"扁平无 valence 网络"该被检测出的信号。
    n_valenced = sum(
        1 for r in rels
        if isinstance(r, dict) and (r.get("valence") or r.get("polarity") is not None)
    )
    return {
        "n_actors": n,
        "n_relationships": n_rels,
        "n_tier12": len(tier12),
        "pct_actors_with_incentives": round(n_incent / n, 3),
        "pct_tier12_with_worldview": round(n_wv / len(tier12), 3) if tier12 else 0.0,
        "pct_edges_valenced": round(n_valenced / n_rels, 3) if n_rels else 0.0,
        "edges_per_actor": round(n_rels / n, 2),
        "salience_basis_present": round(n_sal / n, 3),
        "n_actor_intelligence_v1": len(intelligence_rows),
        "pct_actors_with_actor_intelligence": round(len(intelligence_rows) / n, 3),
        "pct_tier12_with_complete_actor_intelligence": (
            round(complete_tier12 / len(tier12), 3) if tier12 else 0.0
        ),
        "pct_intelligence_with_history": _intel_rate("history"),
        "pct_intelligence_with_identity_history": _intel_rate("identity_history"),
        "pct_intelligence_with_track_record": _intel_rate("track_record"),
        "pct_intelligence_with_values_worldview": _intel_rate("values_worldview"),
        "pct_intelligence_with_incentives": _intel_rate("incentives"),
        "pct_intelligence_with_motivations": _intel_rate("motivations"),
        "pct_intelligence_with_capabilities": _intel_rate("capabilities"),
        "pct_intelligence_with_constraints": _intel_rate("constraints"),
        "pct_intelligence_with_preferences": _intel_rate("preferences"),
        "pct_intelligence_with_alliances": _intel_rate("alliances"),
        "pct_intelligence_with_opponents_competitors": _intel_rate("opponents_competitors"),
        "pct_intelligence_with_current_actions": _intel_rate("current_actions"),
        "pct_intelligence_with_future_plans": _intel_rate("future_plans"),
        "pct_intelligence_with_investments": _intel_rate("investments"),
        "pct_intelligence_with_decision_model": _intel_rate("decision_model"),
        "pct_intelligence_with_likely_actions": _intel_rate("likely_actions"),
        "pct_intelligence_with_red_lines": _intel_rate("red_lines"),
        "pct_intelligence_with_knowledge_state": _intel_rate("knowledge_state"),
        "pct_intelligence_with_report_context": _intel_rate("report_context"),
        "pct_intelligence_with_source_refs": _intel_rate("source_refs"),
        "pct_intelligence_with_provenance": _intel_rate("provenance"),
        "pct_intelligence_with_evidence_gaps": _intel_rate("evidence_gaps"),
        "pct_intelligence_with_producer_coverage": _intel_rate("producer_coverage"),
    }


def _row_norm_tokens(row: Dict[str, Any]) -> set:
    """一个 actor 行的标准化"名字 token 集"（主名 + 别名），用于跨轨去重。"""
    toks = set()
    nm = normalize_name(str(row.get("name", "")))
    if nm:
        toks.add(nm)
    for al in _actor_norm_aliases(row):
        if al:
            toks.add(al)
    return toks


def _rows_same_entity(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """两 actor 行是否指向同一实体（保守判定，合并是破坏性的）。

    命中任一：① 标准化名/别名 token 有交集；② 主名双向包含且较短名 ≥4 字符
    （避免 "AI"/"EU" 这类短名误并）。
    """
    ta, tb = _row_norm_tokens(a), _row_norm_tokens(b)
    if ta & tb:
        return True
    pa = normalize_name(str(a.get("name", "")))
    pb = normalize_name(str(b.get("name", "")))
    if pa and pb and min(len(pa), len(pb)) >= 4 and (pa in pb or pb in pa):
        return True
    return False


_INTELLIGENCE_DIMENSION_ALIASES = {
    "identity_history": ("history",),
    "values_worldview": ("values_worldview",),
    "incentives": ("intelligence_incentives",),
    "motivations": ("motivations",),
    "capabilities": ("capabilities",),
    "constraints": ("constraints",),
    "operational_preferences": ("preferences", "aversions"),
    "alliances": ("alliances",),
    "opponents_competitors": ("opponents_competitors",),
    "decision_rights_process_triggers": ("decision_model",),
    "current_actions": ("current_actions", "actions_in_progress"),
    "future_plans": ("future_plans", "plans"),
    "investments_capital_allocation": (
        "investments", "capital_allocation", "capex_divestments",
    ),
    "track_record": ("track_record",),
    "likely_actions": ("intelligence_likely_actions",),
    "red_lines": ("red_lines",),
    "knowledge_state": ("knowledge_state",),
}


def _claim_merge_key(value: Any) -> str:
    if isinstance(value, dict):
        claim = next((
            value.get(key) for key in (
                "claim", "finding", "description", "text", "event", "action",
                "plan", "investment", "capability", "subject",
            ) if value.get(key)
        ), None)
        if claim:
            return "claim:" + re.sub(r"\s+", " ", str(claim)).strip().casefold()
    if isinstance(value, str):
        return "claim:" + re.sub(r"\s+", " ", value).strip().casefold()
    try:
        return "json:" + json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return "repr:" + repr(value)


def _dimension_claim_rows(value: Any, dimension: str) -> List[Dict[str, Any]]:
    if isinstance(value, dict) and isinstance(value.get("claims"), list):
        rows: List[Any] = value["claims"]
    elif isinstance(value, dict) and dimension == "operational_preferences":
        rows = []
        for kind, key in (("like", "likes"), ("dislike", "dislikes")):
            raw = value.get(key)
            values = raw if isinstance(raw, list) else ([raw] if raw else [])
            for item in values:
                row = copy.deepcopy(item) if isinstance(item, dict) else {"claim": item}
                row.setdefault("preference_kind", kind)
                rows.append(row)
    elif isinstance(value, dict) and dimension == "decision_rights_process_triggers":
        rows = []
        for kind, keys in (
            ("decision_right", ("decision_rights",)),
            ("decision_process", ("decision_process", "process")),
            ("trigger", ("triggers",)),
            ("red_line", ("red_lines",)),
        ):
            raw = next((value.get(key) for key in keys if value.get(key)), None)
            values = raw if isinstance(raw, list) else ([raw] if raw else [])
            for item in values:
                row = copy.deepcopy(item) if isinstance(item, dict) else {"claim": item}
                row.setdefault("decision_kind", kind)
                rows.append(row)
    elif isinstance(value, list):
        rows = value
    elif value not in (None, "", {}):
        rows = [value]
    else:
        rows = []
    return [
        copy.deepcopy(row) if isinstance(row, dict) else {"claim": row}
        for row in rows if row not in (None, "")
    ]


def _merge_actor_intelligence(
    members: List[Dict[str, Any]],
) -> tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Union duplicate actor intelligence without discarding claim variants."""
    payloads = [
        (str(row.get("name") or ""), actor_intelligence_payload(row))
        for row in members
        if actor_intelligence_payload(row)
    ]
    # Preserve original row order so union output is stable regardless of which
    # duplicate wins the unrelated scalar-richness tie-break.
    unique_payloads: List[tuple[str, Dict[str, Any]]] = []
    seen_payloads: set[str] = set()
    for source_name, payload in payloads:
        fingerprint = _claim_merge_key(payload)
        if fingerprint not in seen_payloads:
            seen_payloads.add(fingerprint)
            unique_payloads.append((source_name, payload))
    if not unique_payloads:
        return None, []

    merged: Dict[str, Any] = {
        "schema_version": ACTOR_INTELLIGENCE_SCHEMA_VERSION,
        "dimensions": {},
    }
    conflicts: List[Dict[str, Any]] = []
    variant_audit: List[Dict[str, Any]] = []
    for dimension, aliases in _INTELLIGENCE_DIMENSION_ALIASES.items():
        claim_by_key: Dict[str, Dict[str, Any]] = {}
        claim_sources: Dict[str, List[str]] = {}
        for source_name, payload in unique_payloads:
            pseudo_actor = {"intelligence": payload}
            value = actor_intelligence_dimension(pseudo_actor, dimension, *aliases)
            for claim in _dimension_claim_rows(value, dimension):
                key = _claim_merge_key(claim)
                if key not in claim_by_key:
                    claim_by_key[key] = claim
                    claim_sources[key] = [source_name]
                    continue
                current = claim_by_key[key]
                claim_sources[key].append(source_name)
                for field, incoming in claim.items():
                    if field in ("source_refs", "source_ids", "evidence_refs"):
                        current_refs = current.get("source_refs")
                        if not isinstance(current_refs, list):
                            current_refs = []
                        incoming_refs = incoming if isinstance(incoming, list) else [incoming]
                        current["source_refs"] = list(dict.fromkeys([
                            *current_refs,
                            *(ref for ref in incoming_refs if ref not in (None, "")),
                        ]))
                    elif current.get(field) in (None, "", []):
                        current[field] = copy.deepcopy(incoming)
                    elif incoming not in (None, "", []) and current.get(field) != incoming:
                        conflicts.append({
                            "scope": "actor_intelligence_claim",
                            "dimension": dimension,
                            "claim_key": key,
                            "field": field,
                            "kept": copy.deepcopy(current.get(field)),
                            "alternate": copy.deepcopy(incoming),
                            "from": source_name,
                        })
        if claim_by_key:
            claims = list(claim_by_key.values())
            merged["dimensions"][dimension] = {"claims": claims}
            if len(claims) > 1 and dimension in {
                "current_actions", "future_plans", "investments_capital_allocation",
                "decision_rights_process_triggers", "red_lines",
            }:
                variant_audit.append({
                    "dimension": dimension,
                    "claim_keys": list(claim_by_key),
                    "sources_by_claim": claim_sources,
                    "interpretation": "retained variants; may be complementary or contradictory",
                })

    evidence_gaps: Dict[str, Dict[str, Any]] = {}
    for _source_name, payload in unique_payloads:
        raw_gaps = payload.get("evidence_gaps")
        if isinstance(raw_gaps, dict):
            gap_groups = raw_gaps.items()
        else:
            gap_groups = (("general", raw_gaps),)
        for dimension, raw_values in gap_groups:
            values = raw_values if isinstance(raw_values, list) else ([raw_values] if raw_values else [])
            dimension_gaps = evidence_gaps.setdefault(str(dimension), {})
            for gap in values:
                dimension_gaps.setdefault(_claim_merge_key(gap), copy.deepcopy(gap))
    if evidence_gaps:
        merged["evidence_gaps"] = {
            dimension: list(values.values())
            for dimension, values in evidence_gaps.items()
            if values
        }
    source_refs: List[Any] = []
    for _, payload in unique_payloads:
        for key in ("source_refs", "source_ids", "evidence_refs"):
            raw_refs = payload.get(key)
            values = raw_refs if isinstance(raw_refs, list) else ([raw_refs] if raw_refs else [])
            for ref in values:
                if ref not in source_refs:
                    source_refs.append(copy.deepcopy(ref))
    if source_refs:
        merged["source_refs"] = source_refs

    # Preserve producer coverage snapshots and source provenance verbatim for
    # audit instead of selecting whichever duplicate happened to be richest.
    coverage_snapshots = [
        {"actor_name": name, "coverage": copy.deepcopy(payload.get("coverage"))}
        for name, payload in unique_payloads if payload.get("coverage")
    ]
    provenance_snapshots = [
        {"actor_name": name, "provenance": copy.deepcopy(payload.get("provenance"))}
        for name, payload in unique_payloads if payload.get("provenance")
    ]
    merged["merge_provenance"] = {
        "source_actor_rows": [name for name, _ in unique_payloads],
        "coverage_snapshots": coverage_snapshots,
        "provenance_snapshots": provenance_snapshots,
        "claim_variants": variant_audit,
        "conflicts": copy.deepcopy(conflicts),
    }
    # Promote a single unchanged producer coverage/provenance object for legacy
    # readers while retaining every snapshot above.
    if len(coverage_snapshots) == 1:
        merged["coverage"] = coverage_snapshots[0]["coverage"]
    if len(provenance_snapshots) == 1:
        merged["provenance"] = provenance_snapshots[0]["provenance"]
    return merged, conflicts


def reconcile_cast(actors: Optional[Any]) -> tuple:
    """NEXTSTEPS P3-2：抽取后对 actors[] 做跨轨去重，合并指向同一实体的重复行。

    双轨研究刻意产出两份 cast，今天只是被拼接交给一个抽取 LLM 静默仲裁；同一实体的
    重复行（如 "Nvidia" vs "NVIDIA Corp"，可能 role-class 还不同）会**分裂中心度、衍生
    重复 persona、污染 agent-cap 依赖的 salience 排序**。本 pass 用 normalize_name +
    双向包含/别名把重复行聚类，合并为一条规范行（更丰富者胜、并别名、缺字段回填、记冲突），
    并把 relationships 端点改写到规范名。纯函数；返回 (reconciled_actors, audit)。
    actors 非 dict / actor 行<2 → 原样返回 + 空 audit。
    """
    empty_audit = {"merged": [], "n_before": 0, "n_after": 0}
    if not isinstance(actors, dict):
        return actors, empty_audit
    rows = extract_actor_rows(actors)
    n_before = len(rows)
    if n_before < 2:
        return actors, {"merged": [], "n_before": n_before, "n_after": n_before}

    # union-find 聚类
    parent = list(range(n_before))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n_before):
        for j in range(i + 1, n_before):
            if _rows_same_entity(rows[i], rows[j]):
                ri, rj = _find(i), _find(j)
                if ri != rj:
                    parent[rj] = ri

    clusters: Dict[int, List[int]] = {}
    for i in range(n_before):
        clusters.setdefault(_find(i), []).append(i)

    # 无任何重复 → 真正的 no-op：原样返回输入对象（与现状逐字节一致）。
    if all(len(idxs) == 1 for idxs in clusters.values()):
        return actors, {"merged": [], "n_before": n_before, "n_after": n_before}

    _RICH_KEYS = ("role", "stance", "influence", "memory", "incentives", "worldview",
                  "resources", "aliases", "goals", "constraints", "type", "salience",
                  "intelligence")
    _SCALAR_CONFLICT_KEYS = ("role", "stance", "type", "influence")

    def _richness(row: Dict[str, Any]) -> int:
        return sum(1 for k in _RICH_KEYS if row.get(k))

    merged_audit: List[Dict[str, Any]] = []
    new_rows: List[Dict[str, Any]] = []
    rename: Dict[str, str] = {}   # 标准化的 victim 名 → survivor 规范名
    for idxs in clusters.values():
        members = [rows[i] for i in idxs]
        if len(members) == 1:
            new_rows.append(members[0])
            continue
        survivor = max(
            members,
            key=lambda r: (_richness(r), len(r.get("aliases") or []), len(str(r.get("name", "")))),
        )
        merged = dict(survivor)
        aliases = {str(a) for a in (merged.get("aliases") or [])}
        conflicts: List[Dict[str, Any]] = []
        victim_names: List[str] = []
        for m in members:
            if m is survivor:
                continue
            vn = str(m.get("name") or "")
            if vn:
                victim_names.append(vn)
                aliases.add(vn)
            for a in (m.get("aliases") or []):
                aliases.add(str(a))
            for k, v in m.items():
                if k in ("name", "aliases", "intelligence"):
                    continue
                if not merged.get(k) and v:
                    merged[k] = v
                elif (k in _SCALAR_CONFLICT_KEYS and isinstance(v, str)
                      and isinstance(merged.get(k), str) and merged[k] and v and merged[k] != v):
                    conflicts.append({"field": k, "kept": merged[k], "dropped": v, "from": vn})
        merged_intelligence, intelligence_conflicts = _merge_actor_intelligence(members)
        if merged_intelligence:
            merged["intelligence"] = merged_intelligence
        conflicts.extend(intelligence_conflicts)
        aliases.discard(str(merged.get("name") or ""))
        if aliases:
            merged["aliases"] = sorted(aliases)
        new_rows.append(merged)
        canon = str(merged.get("name") or "")
        for vn in victim_names:
            nv = normalize_name(vn)
            if nv:
                rename[nv] = canon
        merged_audit.append({"canonical": canon, "merged": victim_names, "conflicts": conflicts})

    out = dict(actors)
    out["actors"] = new_rows
    rels = actors.get("relationships")
    if isinstance(rels, list) and rename:
        new_rels = []
        for r in rels:
            if not isinstance(r, dict):
                new_rels.append(r)
                continue
            r2 = dict(r)
            for ep in ("source", "target"):
                nv = normalize_name(str(r2.get(ep, "")))
                if nv in rename:
                    r2[ep] = rename[nv]
            new_rels.append(r2)
        out["relationships"] = new_rels

    return out, {"merged": merged_audit, "n_before": n_before, "n_after": len(new_rows)}


def ontology_from_actors(actors: Optional[Any]) -> Dict[str, Any]:
    """NEXTSTEPS P3-3: 把**已实现的 actor 阵容**投影成本体种子。

    dossier+抽取已给每个 actor 标了 type/archetype、给每条 relationship 标了 typed/valenced
    类型；而 OntologyGenerator 又从散文**重新派生** entity/edge 类型——一次冗余分类，可能与
    actor 上标注的不一致，悄悄劣化 typed 图谱检索与 typed follow 图。本函数把"已实现的现实"
    投影成种子（actor.type→entity_types，relationships[].type→edge_types，复用 REL_EDGE_NAME +
    _REL_TYPE_VALENCE），作为单一真源喂给本体生成。actors 空/无类型 → {}（调用方退化为纯散文派生）。
    """
    rows = extract_actor_rows(actors)
    rels = extract_relationship_rows(actors)
    ent_seen: List[str] = []
    for a in rows:
        t = str(a.get("type") or "").strip()
        if t and t not in ent_seen:
            ent_seen.append(t)
    edge_seen: Dict[str, Dict[str, Any]] = {}
    for r in rels:
        typ = str(r.get("type") or "OTHER").strip().upper()
        name = REL_EDGE_NAME.get(typ, "RELATES_TO")
        if typ == "OTHER":
            lbl = str(r.get("relation_label") or "").strip()
            if lbl:
                name = re.sub(r"[^A-Za-z0-9]+", "_", lbl).strip("_").upper() or "RELATES_TO"
        if name and name not in edge_seen:
            edge_seen[name] = {"name": name, "valence": _REL_TYPE_VALENCE.get(typ, "neutral")}
    if not ent_seen and not edge_seen:
        return {}
    return {
        "entity_types": [{"name": n} for n in ent_seen],
        "edge_types": list(edge_seen.values()),
    }


def ontology_seed_block(actors: Optional[Any]) -> str:
    """把 ontology_from_actors 渲染成喂给本体生成 LLM 的约束块；空种子 → ""（degrade-safe）。"""
    seed = ontology_from_actors(actors)
    if not seed:
        return ""
    ent_list = seed.get("entity_types", [])
    ents = "、".join(e["name"] for e in ent_list)
    edges = "、".join(e["name"] for e in seed.get("edge_types", []))
    # ONT-1: 新增预算自适应。dossier 的 actor.type 过粗（如仅 Government/Organization）时，
    # 硬编码"至多再新增 2 个"会把实体类型预算压到 seed+2≈4，与 general_forecast 模板
    # "6-10 个实体类型"的规则冲突，且 LLM 会偏向更紧的种子上限——这是 4 类型回归的根因。
    # 自适应：允许补足到 8 类（下限保持 2），硬上限 10 由 _validate_and_process 的
    # MAX_ENTITY_TYPES 兜底。旗标关闭时回到旧的固定 2。
    allow_new = 2
    try:
        from ..config import Config as _Cfg  # 延迟导入，避免 utils→config 顶层环依赖
        if bool(getattr(_Cfg, "ONTOLOGY_SEED_ADAPTIVE_BUDGET", True)):
            allow_new = max(2, 8 - len(ent_list))
    except Exception:
        allow_new = max(2, 8 - len(ent_list))
    parts = ["【本体种子（来自已实现的 actor 阵容，单一真源；请**保留**这些实体/关系类型，"
             f"至多再新增 {allow_new} 个领域专属类型（实体类型总数不超过 10）；"
             "不要把已标注的类型重新命名）】"]
    if ents:
        parts.append(f"实体类型（来自 actor.type）：{ents}")
    if edges:
        parts.append(f"关系类型（来自 relationships[].type，含因果/经济/治理族）：{edges}")
    return "\n".join(parts)


def _parse_probability_value(value: Any) -> Optional[float]:
    """R2-CAL-13: 把自由文本概率（probability_band / outcome_frequency）解析为 [0,1] 中点。

    这是 R2-SIM-9 的 schema-mismatch 根因修复：forecast_inputs.scenarios 几乎从不带裸
    ``probability`` 数值键，真实信号藏在 ``probability_band``（如 "30-40%"、"around 60%"、
    "0.3-0.5"）里；base_rates 的外部视角则藏在 ``outcome_frequency``（如 "25%"、"0.2"）里。
    旧逻辑只读裸数值键，于是几乎总是落空 → WorldState 被迫退化成静默 50/50 均匀先验。

    解析策略（纯字符串、确定性、容错）：
    * 抽取所有十进制数字；无数字 → None。
    * 若文本含 ``%`` 或任一数字 > 1 → 视为百分数，逐个除以 100。
    * 取所有数字的均值作为中点（区间 "30-40%" → 0.35；点估计 "60%" → 0.60）。
    * 夹到 (0,1]；解析为 0 或越界 → None（视作无可用信号，交由 uniform_prior 标注）。
    """
    if value is None:
        return None
    if isinstance(value, bool):  # bool 是 int 子类，须先排除
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return f if 0.0 < f <= 1.0 else None
    text = str(value).strip()
    if not text:
        return None
    nums = re.findall(r"\d+(?:\.\d+)?", text)
    if not nums:
        return None
    try:
        vals = [float(x) for x in nums]
    except ValueError:
        return None
    is_percent = ("%" in text) or any(v > 1.0 for v in vals)
    if is_percent:
        vals = [v / 100.0 for v in vals]
    mid = sum(vals) / len(vals)
    if mid <= 0.0 or mid > 1.0:
        return None
    return round(mid, 6)


def valid_scenario_distribution(forecast_inputs: Any) -> bool:
    """Return whether scenario rows form a named, weighted probability partition.

    A name-only shell is not a usable decision-channel seed: treating it as one
    suppresses deterministic report parsing and silently forces uniform priors.
    The accepted contract is one to six unique named rows, each with a parseable
    point probability or probability band, whose midpoint total is approximately
    one. A single scenario is retained for legacy compatibility only at P=1.
    """
    if not isinstance(forecast_inputs, dict):
        return False
    scenarios = forecast_inputs.get("scenarios")
    if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 6:
        return False
    names: set[str] = set()
    probabilities: list[float] = []
    for row in scenarios:
        if not isinstance(row, dict):
            return False
        name = str(row.get("name") or row.get("scenario") or "").strip()
        normalized = normalize_name(name)
        if not normalized or normalized in names:
            return False
        names.add(normalized)
        value = None
        for key in (
            "probability", "likelihood", "base_rate", "prob",
            "probability_band",
        ):
            if row.get(key) is not None:
                value = _parse_probability_value(row.get(key))
                if value is not None:
                    break
        if value is None:
            return False
        probabilities.append(value)
    return abs(sum(probabilities) - 1.0) <= 0.02


def _match_reference_class_to_scenario(reference_class: str, names: List[str]) -> Optional[str]:
    """R2-CAL-13: 把一条 base_rate 的 reference_class 映射回某个情景名（标准化子串匹配）。

    base_rates[].reference_class（如 "historical base rate of incumbent holding share"）
    与情景名（如 "base" / "NVIDIA holds"）经常只在标准化后有子串包含关系。命中较长的情景名
    优先，避免短名误配；无匹配返回 None（该 base_rate 不并入任何情景）。
    """
    rc = normalize_name(reference_class)
    if not rc:
        return None
    best: Optional[str] = None
    best_len = 0
    for nm in names:
        key = normalize_name(nm)
        if len(key) >= 3 and (key in rc or rc in key) and len(key) > best_len:
            best, best_len = nm, len(key)
    return best


def world_state_seed_from_actors(actors: Optional[Any]) -> Dict[str, Any]:
    """NEXTSTEPS P1-1 / R2-CAL-13: 从 forecast_inputs 抽出 WorldState 种子。

    返回 {scenarios:[name], base_rates:{name: prob}, uniform_prior: bool}——给"结果世界态"
    一个由外部视角基率初始化的起点（services.worldstate.WorldState 据此 seed）。无候选情景 →
    {}（调用方退化为不建世界态）。

    R2-CAL-13（critical）：基率来源按优先级为
      1. 情景上的裸数值键 probability/likelihood/base_rate/prob（旧行为，逐字节保留）；
      2. 情景上的 ``probability_band`` 文本中点（"30-40%"→0.35）——这才是 forecast_inputs
         的真实 schema，旧逻辑遗漏它正是 WorldState 总落到 50/50 的根因（R2-SIM-9）；
      3. forecast_inputs.base_rates[].outcome_frequency，按 reference_class→情景名映射补全。
    当三条来源都未给出任何可用基率时，``uniform_prior`` 置 True（显式标注"基率确实缺失、
    将用均匀先验"），而不是让下游静默 50/50 而无人知晓。
    """
    fi = extract_forecast_inputs(actors)
    scs = fi.get("scenarios") or []
    names: List[str] = []
    rates: Dict[str, float] = {}
    for s in scs:
        if not isinstance(s, dict):
            continue
        nm = str(s.get("name") or s.get("scenario") or "").strip()
        if not nm or nm in names:
            continue
        names.append(nm)
        # 1) 裸数值键（旧行为，byte-stable）。
        got = False
        for key in ("probability", "likelihood", "base_rate", "prob"):
            v = s.get(key)
            if v is None:
                continue
            try:
                rates[nm] = float(v)
                got = True
                break
            except (TypeError, ValueError):
                pass
        # 2) R2-CAL-13: probability_band 中点回退（真实 schema 所在）。
        if not got:
            band = _parse_probability_value(s.get("probability_band"))
            if band is not None:
                rates[nm] = band
    if not names:
        return {}

    # 3) R2-CAL-13: forecast_inputs.base_rates[].outcome_frequency 按 reference_class 映射补全，
    #    只填尚无基率的情景（情景自带的概率优先级更高）。
    for br in fi.get("base_rates") or []:
        if not isinstance(br, dict):
            continue
        rc = str(br.get("reference_class") or "").strip()
        if not rc:
            continue
        freq = _parse_probability_value(br.get("outcome_frequency"))
        if freq is None:
            continue
        target = _match_reference_class_to_scenario(rc, names)
        if target and target not in rates:
            rates[target] = freq

    # uniform_prior：三条来源都没给出任何正基率 → 显式标注将退化为均匀先验（替代静默 50/50）。
    uniform_prior = not any(
        isinstance(v, (int, float)) and v > 0 for v in rates.values()
    )
    return {"scenarios": names, "base_rates": rates, "uniform_prior": uniform_prior}


# ------------------- 研究报告 → forecast_inputs 情景种子（决策通道兜底解析）-------------------
# 取证：41 次模拟无一存在 world_state_trajectory.json——actors.json 缺 forecast_inputs.scenarios
# 时 world_state_seed_from_actors 返回 {}，决策通道从未点火。而研究报告本身几乎总带有
# 「## Four Mutually Exclusive Scenarios」/「### Scenario Probability Distribution」这类带概率的
# 情景节。下列正则把该节确定性解析回 forecast_inputs schema（纯离线、无 LLM）。
_SCENARIO_SECTION_CUE_RE = re.compile(r"scenario|情景|情境|场景", re.I)
_SCENARIO_AGGREGATE_TOTAL_RE = re.compile(
    r"mutually\s+exclusive|collectively\s+exhaustive|sum(?:ming|s|med)?\s+(?:up\s+)?to|"
    r"total(?:ing|s|led)?\s+(?:up\s+)?to|互斥|穷尽|合计|总计|总和|概率(?:之)?和",
    re.I,
)
_MD_HEADING_RE = re.compile(r"^(#{2,6})\s*(.+?)\s*$")
_MD_BOLD_LIST_ITEM_RE = re.compile(r"^\s*[-*+]\s*\*\*(?P<bold>.+?)\*\*(?P<rest>.*)$")
# 概率表达（按优先级）：① 百分数区间 "35–45%"（首数字后允许可选 %，兼容 "35%–45%"）；
# ② 中英「概率/probability + 小数」如 "概率 0.35"；③ 单点百分数 "(45%)"。
_PROB_RANGE_RE = re.compile(
    r"\d{1,3}(?:\.\d+)?\s*%?\s*[-–—~～至到]\s*\d{1,3}(?:\.\d+)?\s*%")
# 小数必须是完整数字：其后不得再跟数字/小数点/百分号。旧式只否定紧随的 "%"，
# 「概率 15%」会先匹配到 "1"（后跟 "5"）而被读成概率 1.0，使 10–19% 的中文情景
# 分布整体被判为合计越界而丢弃（world-state 种子因此为空）。
_PROB_DECIMAL_RE = re.compile(
    r"(?:概率|probability)\s*[:：=为约]?\s*(?:of\s+)?(0?\.\d+|1(?:\.0+)?)(?![\d.]|\s*%)", re.I)
_PROB_PERCENT_RE = re.compile(r"\d{1,3}(?:\.\d+)?\s*%")


def _extract_probability_text(text: str) -> Optional[str]:
    """从一行标题/粗体名里抽出概率原文（"35–45%" / "0.35" / "45%"）；无 → None。"""
    for pat in (_PROB_RANGE_RE, _PROB_DECIMAL_RE, _PROB_PERCENT_RE):
        m = pat.search(text or "")
        if m:
            return m.group(1) if m.lastindex else m.group(0)
    return None


def _is_scenario_section_heading(title: str) -> bool:
    """Return whether ``title`` introduces a scenario distribution section.

    Distribution headings commonly state the aggregate invariant themselves,
    for example ``Scenarios (4 mutually exclusive, summing to 100%)``.  The
    previous parser rejected every heading containing a percentage so that an
    item such as ``Scenario A (45%)`` could not become its own section.  That
    also rejected the aggregate 100% invariant and silently disabled the
    simulation decision channel.  Permit exactly that aggregate-total form;
    all other probability-bearing headings remain item headings.
    """
    if not _SCENARIO_SECTION_CUE_RE.search(title or ""):
        return False
    prob_text = _extract_probability_text(title)
    if prob_text is None:
        return True
    probability = _parse_probability_value(prob_text)
    return bool(
        probability is not None
        and abs(probability - 1.0) <= 1e-9
        and _SCENARIO_AGGREGATE_TOTAL_RE.search(title or "")
    )


def _strip_probability_annotation(name: str, prob_text: str) -> str:
    """从情景名里剥掉概率括注（中英括号皆可）与裸概率残留，再去首尾标点。"""
    out = re.sub(r"[（(][^()（）]*" + re.escape(prob_text) + r"[^()（）]*[)）]", "", str(name or ""))
    out = out.replace(prob_text, "")
    return out.strip(" \t*:：—–-·，,。").strip()


def _append_scenario_row(rows: List[Dict[str, Any]], seen: set,
                         raw_name: str, prob_text: str) -> None:
    """把一个候选情景条目规整为 forecast_inputs 情景行（名去括注、概率区间保留原文）。"""
    name = _strip_probability_annotation(raw_name, prob_text)
    key = normalize_name(name)
    if not name or not key or key in seen:
        return
    mid = _parse_probability_value(prob_text)
    if mid is None:
        return
    seen.add(key)
    row: Dict[str, Any] = {"name": name}
    if _PROB_RANGE_RE.search(prob_text):
        row["probability_band"] = prob_text  # 区间保留原文，中点由消费方按需计算
    else:
        row["probability"] = mid
    rows.append(row)


def forecast_inputs_from_report_markdown(report_md: str) -> Dict[str, Any]:
    """把研究报告的情景节确定性解析回 forecast_inputs schema（纯函数、离线、无 LLM）。

    预期调用点：pipeline_orchestrator 的 **prepare 阶段**，在 world_state_seed_from_actors
    之前——当 actors.json 缺 forecast_inputs（或其 scenarios 为空）时，用本函数从
    handoff/research_report.md 兜底解析出情景种子，使决策通道（世界态种子）不再因抽取
    遗漏而熄火。调用方形如：``seed = world_state_seed_from_actors(
    {"forecast_inputs": forecast_inputs_from_report_markdown(report_md)})``。

    识别两种真实版式（EN/zh 皆可，节标题含 scenario/情景/情境/场景 线索）：
      * 标题式：「## Four Mutually Exclusive Scenarios」下的
        「### Scenario A: …… (45% probability)」；
      * 粗体列表式：「### Scenario Probability Distribution」下的
        「- **Base Scenario (55% probability):** ……」（中文如「- **基准情景（概率 0.35）**：……」）。
    概率支持 '(35%)'、'35–45%'、'概率 0.35' 三型；区间在输出里保留为 ``probability_band``
    原文（消费方 _parse_probability_value 取中点），点估计折成 ``probability`` 小数。

    校验：2-6 个情景、每个都解析出概率、且中点之和落在 [0.9, 1.1]；任一不满足 → ``{}``
    （调用方视同无种子，degrade-safe）。命中时返回
    ``{"scenarios": [{"name", "probability"|"probability_band"}], "base_rates": []}``——
    与 extract_forecast_inputs / world_state_seed_from_actors 消费的 schema 一致。
    """
    lines = str(report_md or "").splitlines()
    # 候选情景节 = 含情景线索且不是带概率的单个情景条目。允许节标题陈述
    # 「summing to 100%」/「概率合计 100%」这类分布约束；其他带概率标题（如
    # 「### Scenario A: …… (45%)」）仍不能被当成节起点。逐个候选节尝试，取第一个
    # 收齐 2-6 个带概率条目的节作为**唯一**情景节（避免把全文多处情景复述混成一锅）。
    for i, ln in enumerate(lines):
        m = _MD_HEADING_RE.match(ln)
        if not m or not _is_scenario_section_heading(m.group(2)):
            continue
        level = len(m.group(1))
        rows: List[Dict[str, Any]] = []
        seen: set = set()
        for body_ln in lines[i + 1:]:
            hm = _MD_HEADING_RE.match(body_ln)
            if hm:
                if len(hm.group(1)) <= level:
                    break  # 同级/更浅标题 = 节结束
                prob_text = _extract_probability_text(hm.group(2))
                if prob_text:
                    _append_scenario_row(rows, seen, hm.group(2), prob_text)
                continue
            bm = _MD_BOLD_LIST_ITEM_RE.match(body_ln)
            if not bm:
                continue
            bold = bm.group("bold")
            prob_text = _extract_probability_text(bold)
            if not prob_text:
                # 概率可能紧跟在粗体名后（"- **X**（概率 35%）：……"）；只看首个冒号前的
                # 短前缀，避免把描述正文里的无关百分数（"份额达 55-60%"）误当概率。
                rest_head = re.split(r"[:：]", bm.group("rest"), maxsplit=1)[0]
                prob_text = _extract_probability_text(rest_head[:60])
            if prob_text:
                _append_scenario_row(rows, seen, bold, prob_text)
        if not (2 <= len(rows) <= 6):
            continue  # 该候选节不是概率分布节，尝试下一个
        mids = [_parse_probability_value(r.get("probability_band") or r.get("probability"))
                for r in rows]
        if any(v is None for v in mids) or not (0.9 <= sum(mids) <= 1.1):
            # 该候选节的概率不构成分布（缺失/合计不到 ~100%）→ **跳过并尝试下一个候选节**，
            # 而非直接放弃。真实报告常有多处情景复述（执行摘要「Scenario A (48%)」、地区节
            # 「…for China, US, EU (sum=100%)」、以及权威的「## Scenarios (…summing to 100%)」），
            # 早前一个杂乱节不该埋葬后面那个干净的分布节。绝不播下失真种子：只采纳合计≈100% 的节。
            continue
        return {"scenarios": rows, "base_rates": []}
    return {}


# 关系价 → 到预测时点的保守轨迹先验。结构性纽带（联盟/对抗）有惯性、更"黏"；交易性纽带随利益
# 变化、最易翻转。这是**模型推断而非证据**，渲染时必须显式标注。
_VALENCE_TRAJECTORY = {
    "allied": ("likely_persists", "联盟有惯性，倾向延续"),
    "adversarial": ("persists_or_escalates", "对抗关系倾向延续或升级"),
    "transactional": ("contingent", "交易关系随利益变化，最易翻转"),
    "neutral": ("uncertain", "价中性，轨迹不定"),
}


def project_relationships(actors: Optional[Any]) -> List[Dict[str, Any]]:
    """NEXTSTEPS P3-8: 给每条已实现关系投一个「到预测时点的轨迹」标签。

    预测要问的是"到 horizon 时，**哪些**纽带还在/会翻转"，而 KG 只编码当下。本函数基于关系价
    （relation_valence）给一个保守先验轨迹（allied→likely_persists / adversarial→
    persists_or_escalates / transactional→contingent）。**模型推断而非证据**，调用方须标注。
    无关系 → []（degrade-safe）。
    """
    rows = extract_relationship_rows(actors)
    out: List[Dict[str, Any]] = []
    for r in rows:
        val = relation_valence(r)
        traj, why = _VALENCE_TRAJECTORY.get(val, ("uncertain", "轨迹不定"))
        out.append({
            "source": r.get("source"), "target": r.get("target"),
            "type": r.get("type"), "valence": val,
            "projected": traj, "rationale": why,
        })
    return out


def projected_edges_block(actors: Optional[Any], max_rows: int = 14) -> str:
    """把 project_relationships 渲染为报告用的「关系演化投影」块（显式标注=模型推断非证据）。
    空 → ""（degrade-safe）。优先展示最易翻转的（contingent）纽带——它们是情景分叉的支点。"""
    proj = project_relationships(actors)
    if not proj:
        return ""
    order = {"contingent": 0, "persists_or_escalates": 1, "likely_persists": 2, "uncertain": 3}
    proj.sort(key=lambda p: order.get(p.get("projected", "uncertain"), 9))
    lines = ["【关系演化投影到预测时点（⚠模型推断·非证据；标注 contingent 者最易翻转、是情景支点）】"]
    for p in proj[:max_rows]:
        src, tgt = p.get("source") or "?", p.get("target") or "?"
        lines.append(f"· {src} —[{p.get('type') or 'REL'}]→ {tgt}：{p.get('projected')}（{p.get('rationale')}）")
    return "\n".join(lines)


def forecast_inputs_block(actors: Optional[Any], max_per_section: int = 6) -> str:
    """把 forecast_inputs 渲染为预测脚手架块；全空返回空串。

    给报告代理一个外部视角基率 + 驱动 + 带日期指标 + 概率区间情景的校准底座，
    让预测可证伪（指标）、可校准（情景概率），而非纯叙事。
    """
    fi = extract_forecast_inputs(actors)
    base_rates = fi["base_rates"][:max_per_section]
    drivers = fi["drivers"][:max_per_section]
    indicators = fi["indicators"][:max_per_section]
    scenarios = fi["scenarios"][:max_per_section]
    if not (base_rates or drivers or indicators or scenarios):
        return ""

    out: List[str] = ["## 预测输入（深度研究实证；作为校准脚手架，撰写时据此给出概率与可观测信号）"]

    if base_rates:
        out.append("### 外部视角基率（参照类）")
        for b in base_rates:
            rc = str(b.get("reference_class", "") or "").strip()
            freq = str(b.get("outcome_frequency", "") or "").strip()
            basis = str(b.get("basis", "") or "").strip()
            if not rc:
                continue
            seg = f"- {rc}"
            if freq:
                seg += f"：基率 {freq}"
            if basis:
                seg += f"（依据：{basis}）"
            out.append(seg)

    if drivers:
        out.append("### 关键驱动变量")
        for d in drivers:
            var = str(d.get("variable", "") or "").strip()
            direction = str(d.get("direction", "") or "").strip()
            why = str(d.get("why_it_matters", "") or "").strip()
            if not var:
                continue
            seg = f"- {var}"
            if direction:
                seg += f"（方向：{direction}）"
            if why:
                seg += f"：{why}"
            out.append(seg)

    if indicators:
        out.append("### 可观测指标（带日期/触发条件，用于事后验证）")
        for ind in indicators:
            name = str(ind.get("indicator", "") or "").strip()
            signals = str(ind.get("signals_what", "") or "").strip()
            when = str(ind.get("date_or_trigger", "") or "").strip()
            if not name:
                continue
            seg = f"- {name}"
            if when:
                seg += f"（{when}）"
            if signals:
                seg += f"：预示 {signals}"
            out.append(seg)

    if scenarios:
        out.append("### 情景（基线/上行/下行 + 概率区间）")
        for sc in scenarios:
            raw = str(sc.get("name", "") or "").strip().lower()
            label = _SCENARIO_LABEL.get(raw, raw or "情景")
            # REPORT-10（信息墙）：只渲染旧式 probability_band；v3 情景的数值 ``probability``
            # 是研究规划期的权重，刻意不渲染——它经本块会进入骨架/报告的概率权威，把研究
            # 先验当成已定的概率（test_information_walls_static 钉住此选择）。
            band = str(sc.get("probability_band", "") or "").strip()
            narrative = str(sc.get("narrative", "") or "").strip()
            seg = f"- {label}"
            if band:
                seg += f"（概率 {band}）"
            if narrative:
                seg += f"：{narrative}"
            out.append(seg)
            assumptions = sc.get("key_assumptions")
            if isinstance(assumptions, list):
                for a in [str(x) for x in assumptions if str(x or "").strip()][:4]:
                    out.append(f"  - 关键假设：{a}")
    return "\n".join(out)


def indicators_to_schedule(
    actors: Optional[Any],
    total_rounds: int,
    as_of_date: Optional[str],
    horizon_days: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """forecast_inputs.indicators 中带日期者 → [{round, indicator, date}]，复用 key_events 的映射逻辑。

    只挑选 ``date_or_trigger`` 能被 ``parse_as_of`` 解析为未来日期的指标，把它们落到对应
    模拟轮次，让模拟可在「该信号本应出现」的时点关注对应驱动变量。无可解析项返回 []。
    """
    from .dates import parse_as_of  # 同包相对导入，匹配代码库约定

    if not isinstance(actors, dict) or total_rounds <= 0:
        return []
    base = parse_as_of(as_of_date)
    if base is None:
        return []
    inds = extract_forecast_inputs(actors)["indicators"]
    if not inds:
        return []

    spans: List[int] = []
    for ind in inds:
        d = parse_as_of(ind.get("date_or_trigger"))
        if d is None:
            continue
        span = (d - base).days
        if span >= 0:
            spans.append(span)
    hz = horizon_days or (max(spans) if spans else 1) or 1

    out: List[Dict[str, Any]] = []
    for ind in inds:
        d = parse_as_of(ind.get("date_or_trigger"))
        if d is None:
            continue
        span = (d - base).days
        if span < 0:
            continue
        out.append({
            "round": min(total_rounds - 1, round(span / hz * total_rounds)),
            "indicator": ind.get("indicator"),
            "date": ind.get("date_or_trigger"),
        })
    return out
