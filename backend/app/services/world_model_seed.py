"""PREPARE-time ``world_model`` block for the reflexive simulation (design §2.7).

Built deterministically (no LLM) inside ``SimulationConfigGenerator.generate_config``
before the config is sealed, from research artifacts the preparation stage already
holds:

* ``state_variables`` — numeric/categorical facts parsed from the dossier's
  ``quantitative_facts`` and the bound official-data snapshot (latest observation at
  or before the research as-of date), each with unit, as-of and provenance.
* ``actors`` — one row per cast member (audience fill excluded): agency class
  (dossier value → ontology/type/role inference), archetype, class capacity,
  declared outcome power only, documented plans / red lines / goals (bounded,
  sanitised, actor-own evidence), allies and rivals from the valenced relationships.
* ``relationships`` — valenced edges restricted to the cast.
* ``shocks`` — researched risks / wildcards (``forecast_inputs.risks``) that may materialise in
  any period: event, documented base rate converted to a per-day hazard, source, effects on
  tracked variables and the actors they hit.  Only documented rows qualify; everything else is
  a typed modelling gap (design §2.12).
* ``settings`` — arbiter switch, change-ratio clamp, barrier timeout.

Canonical actor-intelligence/v1 dossiers: plans, red lines and goals come only from
the validated context pack's producer-admitted claim rows (never from the flat
compatibility fields); analyst inference is skipped.  Legacy dossiers use their flat
fields.  Research engine v3 dossiers (``deerflow_bridge/linear_research.py`` ACTOR
EXTRACTION TASK) carry no plan or red-line keys at all, only ``goals`` /
``constraints`` / ``stated_vs_revealed`` / ``memory``; for them the seed derives
documented plans from the actor's own stated commitments and action-phrased goals,
and red lines from constraints or statements phrased as non-negotiables — never from
hedged wording, the "revealed" half of ``stated_vs_revealed``, incentives,
vulnerabilities or worldview (analyst reading, not world fact).  Pure and never
raises (a failure degrades to a smaller block).
"""

from __future__ import annotations

import calendar
import math
import re
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..utils.actors import (
    entity_archetype,
    extract_forecast_inputs,
    extract_quantitative_rows,
    extract_relationship_rows,
    extract_risk_rows,
    match_actor,
    normalize_name,
    relation_polarity,
    relation_valence,
)
from .actor_role_prompt import sanitize_untrusted_dossier_text
from .agent_decision import default_capacity, infer_agency_class
from .official_data import data_api, resolution_instant
from .world_model import parse_quantity, slugify

WORLD_MODEL_SEED_VERSION = "world-model-seed/v1"
DEFAULT_MAX_VARIABLES = 24
MAX_OFFICIAL_SERIES = 10
MAX_PLANS = 4
MAX_RED_LINES = 3
MAX_GOALS = 3
_PLAN_DIMENSIONS = ("future_plans", "likely_actions", "current_actions", "investments_capital_allocation")
_CURRENT_QUANTITATIVE_TYPES = {"", "actual", "estimate"}
_STATUS_INFERRED_PREFIXES = ("wb:", "imf:WEO/", "imf:WEO_")
_LEGACY_PLAN_KEYS = ("future_plans", "plans", "likely_actions", "current_actions", "actions_in_progress")
_LEGACY_RED_LINE_KEYS = ("red_lines", "non_negotiables")

# --- research engine v3 rows (no plan / red-line keys; items carry no evidence_type) ---------------
# Only wording can separate the actor's documented intent from the analyst's reading there, so an
# item is promoted only when it is phrased as the actor's own commitment, as an action the actor
# pursues, or as a prohibition the actor declares.  Hedged wording never qualifies.
_V3_CLAUSE_SPLIT_RE = re.compile(
    r"\s*(?:;|；|。|(?<![A-Z])\.\s+|\s+[—–]\s+|\s+but\s+|\s+while\s+|\s+whereas\s+)\s*", re.IGNORECASE)
_V3_REVEALED_RE = re.compile(
    r"\b(?:reveal\w*|in practice|in fact|actually|privately|de facto|track record|record (?:shows|is)|"
    r"behaviou?r (?:shows|is)|however)\b|实际|暗中|私下|但实际", re.IGNORECASE)
_V3_STATED_RE = re.compile(
    r"\b(?:states|stated|says?|said|publicly|public(?:ly)? (?:commit|pledg)\w*|commits?|committed|pledg\w*|"
    r"promis\w*|announc\w*|claims?|declar\w*|insists?|vow\w*|official(?:ly)?|rhetoric)\b|"
    r"声称|公开|宣称|承诺|表示|宣布", re.IGNORECASE)
_V3_COMMIT_RE = re.compile(
    r"\b(?:commit(?:s|ted)? to|pledg(?:e|es|ed)|promis(?:e|es|ed)|vow(?:s|ed)?|plan(?:s|ned)? to|"
    r"intend(?:s|ed)? to|announc(?:e|es|ed)|agree(?:s|d)? to|will|shall|scheduled|set to|aims? to|"
    r"seeks? to|propos(?:e|es|ed))\b|承诺|计划|宣布将|将于|推进|推动", re.IGNORECASE)
_V3_LEADING_COMMIT_RE = re.compile(
    r"^\s*?(?:agree[sd]?|pledge[sd]?|committed|promis(?:es|ed)|vow(?:s|ed)?|plan(?:s|ned)?|"
    r"seek(?:s|ing)?|aim(?:s|ing)?|propos(?:es|ed)?|announce[sd]?|confirm[sd]?|accept[sd]?)\b",
    re.IGNORECASE)
_V3_HEDGE_RE = re.compile(
    r"\b(?:possibl[ey]|perhaps|maybe|might|could|potentially|likely|probably|unclear|uncertain|"
    r"speculat\w*|expected to|reportedly)\b|\bmay\s+(?!\d)|可能|或将|或许|也许|大概|预计|据称", re.IGNORECASE)
_V3_RED_LINE_RE = re.compile(
    r"\b(?:will not|won't|would not|will never|would never|never (?:accept|allow|agree|sign|permit|concede|"
    r"tolerate|negotiate|recogni[sz]e)|refus\w* to|non-?negotiable|not negotiable|not up for negotiation|"
    r"red ?lines?|cannot accept|can't accept|unacceptable|must not|must never|rules? out|ruled out|"
    r"off the table|under no circumstances|not an option|insists? on|only if|no (?:deal|agreement|"
    r"concession|compromise)s? (?:without|unless))\b|绝不|决不|不会接受|(?<!不得)不接受|不可接受|底线|红线|不得(?!不)",
    re.IGNORECASE)
# Leading base-form verbs that make a goal read as an intended move rather than a posture.  Maintain-
# type verbs (keep, preserve, maintain, protect, comply, ...) are deliberately absent: holding a
# position is already an option of every agency class.
_V3_ACTION_VERBS = frozenset("""
acquire adopt advance announce appeal apply approve arrange audit ban block blockade boost broker build buy
cancel capture cap certify challenge close codify commit complete conclude constrain convert create curb cut
degrade defeat deliver deploy detain develop disrupt diversify divest ease enact end enforce enter escalate
establish exit expand extend
file finalise finalize form freeze fund halt implement impose increase introduce invest issue join launch
legislate license lift limit list lobby lower negotiate obtain open overturn pass phase prolong publish
purchase pursue raise ratify rebuild reduce reform reimpose reinstate relocate remove renew reopen repeal
replace resolve restore restrict resume retaliate revoke roll scale secure sell set settle sign stop strip
strike submit suspend target tighten unlock unwind upgrade verify win withdraw
推进 推动 实施 签署 落实 延长 扩大 建立 启动 完成 达成 争取 收紧 放宽 取消 恢复 加强 实现 出台 制定 发布 加征 削减
""".split())


def _clean(value: Any, max_chars: int) -> str:
    return sanitize_untrusted_dossier_text(value, max_chars) if value not in (None, "") else ""


def _dedupe(values: Iterable[str], limit: int) -> List[str]:
    out: List[str] = []
    for v in values:
        t = str(v or "").strip()
        if t and t.casefold() not in {o.casefold() for o in out}:
            out.append(t)
        if len(out) >= limit:
            break
    return out


def _is_canonical(actor: Dict[str, Any]) -> bool:
    intel = actor.get("intelligence")
    return isinstance(intel, dict) and str(intel.get("schema_version") or "") == "actor-intelligence/v1"


def _pack_claims(pack: Optional[Dict[str, Any]], dimensions: Sequence[str], limit: int) -> List[str]:
    """Documented (non-inference) claim texts of the actor's own validated context pack."""
    if not isinstance(pack, dict):
        return []
    intel = pack.get("actor_intelligence")
    dims = intel.get("dimensions") if isinstance(intel, dict) else None
    if not isinstance(dims, dict):
        return []
    out: List[str] = []
    for dim in dimensions:
        rows = dims.get(dim)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("evidence_type") or "").casefold().replace("-", "_") == "analyst_inference":
                continue
            qualifiers = row.get("qualifiers")
            qualifiers = qualifiers if isinstance(qualifiers, dict) else {}
            if row.get("actor_knows") is False or qualifiers.get("actor_knows") is False:
                continue
            claim = _clean(row.get("claim"), 200)
            if claim:
                out.append(claim)
    return _dedupe(out, limit)


def _legacy_list(actor: Dict[str, Any], keys: Sequence[str], limit: int) -> List[str]:
    out: List[str] = []
    for key in keys:
        value = actor.get(key)
        if isinstance(value, str):
            value = [value]
        if isinstance(value, dict):
            value = list(value.values())
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                item = item.get("claim") or item.get("text") or item.get("action") or item.get("description")
            text = _clean(item, 200)
            if text:
                out.append(text)
    intel = actor.get("intelligence")
    if isinstance(intel, dict) and not _is_canonical(actor):
        for key in keys:
            value = intel.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        item = item.get("claim") or item.get("text")
                    text = _clean(item, 200)
                    if text:
                        out.append(text)
    return _dedupe(out, limit)


def _v3_items(value: Any, max_chars: int = 200) -> List[str]:
    """Sanitised strings of a v3 list field (strings or {claim|text} rows); never dict values."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if isinstance(item, dict):
            item = item.get("claim") or item.get("text")
        text = _clean(item, max_chars)
        if text:
            out.append(text)
    return out


def _v3_clauses(value: Any, max_chars: int = 200) -> List[str]:
    """Clauses of a v3 free-text field (``stated_vs_revealed``, ``memory``)."""
    text = _clean(value, 1200)
    if not text:
        return []
    out: List[str] = []
    for clause in _V3_CLAUSE_SPLIT_RE.split(text):
        clause = clause.strip(" ,，:：.").strip()
        if clause:
            out.append(clause[:max_chars].rstrip())
    return out


def _v3_stated_clauses(actor: Dict[str, Any]) -> List[str]:
    """The actor's own public statements in ``stated_vs_revealed``: clauses with stated-wording and
    without revealed-wording (the revealed half is the analyst's reading of behaviour)."""
    return [c for c in _v3_clauses(actor.get("stated_vs_revealed"))
            if _V3_STATED_RE.search(c) and not _V3_REVEALED_RE.search(c)]


def _v3_is_hedged(text: str) -> bool:
    return bool(_V3_HEDGE_RE.search(text))


def _v3_red_line_worded(text: str) -> bool:
    return bool(_V3_RED_LINE_RE.search(text))


def _v3_leading_action_verb(text: str) -> bool:
    head = text.lstrip("\"'“‘(（[").split(" ", 1)[0].strip(",.;:").casefold()
    if head in _V3_ACTION_VERBS:
        return True
    return any(text.startswith(v) for v in _V3_ACTION_VERBS if not v.isascii())


def _v3_plan_like(text: str, *, require_commitment: bool) -> bool:
    """Worded as a move the actor intends: a commitment marker (``commits to``, ``will``,
    ``scheduled`` …) or — for goals — a leading action verb.  Hedged wording is never a plan, and
    a declared refusal ("will not accept …") is a red line, not a plan."""
    if _v3_is_hedged(text) or _v3_red_line_worded(text):
        return False
    if _V3_COMMIT_RE.search(text):
        return True
    return not require_commitment and _v3_leading_action_verb(text)


def derive_v3_plans(actor: Optional[Dict[str, Any]], limit: int = MAX_PLANS) -> List[str]:
    """Documented plans of a research engine v3 row (no legacy plan keys): the actor's stated
    commitments first, then action-phrased goals, then forward commitments in ``memory``.  Hedged
    wording, refusals and revealed/analyst clauses are never promoted."""
    if not isinstance(actor, dict):
        return []
    out: List[str] = []
    for clause in _v3_stated_clauses(actor):
        if _v3_plan_like(clause, require_commitment=True):
            out.append(clause)
    for goal in _v3_items(actor.get("goals")):
        if _v3_plan_like(goal, require_commitment=False):
            out.append(goal)
    for clause in _v3_clauses(actor.get("memory")):
        if _v3_plan_like(clause, require_commitment=True) and not _V3_REVEALED_RE.search(clause):
            out.append(clause)
    # 2026-10-21（pipe_0827b81a9998）：研究档常把唯一的前瞻承诺藏在 stance /
    # stated_vs_revealed 里且措辞带对冲（"agreed 'in principle' to talks"）。此前对冲
    # 一律不升级 → 20 个 actor 里 10 个 actor_without_plans、选项菜单退化成类属模板。
    # 折中：显式承诺动词（agree/commit/plan to/scheduled…）命中的对冲条款**原样**升级
    # （对冲词保留在文本里，读者可见「有保留的承诺」），绝不改写、绝不发明。
    if not out:
        # 句首承诺动词也算显式承诺（"Agreed 'in principle' to talks"——动词与 to 之间
        # 隔着限定语，_V3_COMMIT_RE 的连续短语匹配不到，但句首形式同样是承诺措辞）。
        for clause in _v3_clauses(actor.get("stance")) + _v3_stated_clauses(actor):
            if ((_V3_COMMIT_RE.search(clause) or _V3_LEADING_COMMIT_RE.match(clause))
                    and not _v3_red_line_worded(clause)
                    and not _V3_REVEALED_RE.search(clause) and len(clause) > 12):
                out.append(clause)
                if len(out) >= limit:
                    break
    return _dedupe(out, limit)


def derive_v3_red_lines(actor: Optional[Dict[str, Any]], limit: int = MAX_RED_LINES) -> List[str]:
    """Red lines of a research engine v3 row (no legacy red-line keys): constraints and the actor's
    own statements that are phrased as non-negotiables ("will not accept", "rules out", 绝不 …).
    Historical observations ("never recovered"), absences ("No clear majority") and procedural
    requirements do not qualify."""
    if not isinstance(actor, dict):
        return []
    out: List[str] = []
    for text in _v3_items(actor.get("constraints"), 160) + [c[:160] for c in _v3_stated_clauses(actor)]:
        if _v3_red_line_worded(text) and not _v3_is_hedged(text):
            out.append(text)
    return _dedupe(out, limit)


def _declared_outcome_power(actor: Optional[Dict[str, Any]], cfg: Dict[str, Any]) -> Optional[float]:
    """Only an explicitly declared power counts (I-3); visibility is never reused."""
    for source in (cfg, actor or {}):
        if not isinstance(source, dict):
            continue
        for key in ("outcome_power", "power"):
            raw = source.get(key)
            if isinstance(raw, bool) or raw is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value) and value >= 0:
                return value
    return None


def _cfg_get(cfg: Any, key: str, default: Any = None) -> Any:
    if isinstance(cfg, dict):
        return cfg.get(key, default)
    return getattr(cfg, key, default)


def resolve_agency_class(actor: Optional[Dict[str, Any]], entity_type: str = "",
                         ontology_class: str = "") -> str:
    """Dossier value → ontology value → inference from type/role/description text."""
    for candidate in ((actor or {}).get("agency_class"), ontology_class):
        if isinstance(candidate, str) and candidate.strip():
            klass = infer_agency_class(candidate)
            if klass != "other_actor" or candidate.strip().casefold() == "other_actor":
                return klass
    actor = actor if isinstance(actor, dict) else {}
    generic = {"", "actor", "actors", "entity", "agent", "unknown"}
    type_name = entity_type if str(entity_type or "").strip().casefold() not in generic else ""
    return infer_agency_class(
        type_name or actor.get("type") or "",
        actor.get("role"), actor.get("role_class"), actor.get("description"), actor.get("name"),
        archetype=entity_archetype(actor) if actor else "",
    )


def state_variables_from_research(actors: Optional[Dict[str, Any]],
                                  official_data: Optional[Dict[str, Any]] = None, *,
                                  max_variables: int = DEFAULT_MAX_VARIABLES) -> List[Dict[str, Any]]:
    """Seed variables: dossier quantitative facts first, then the official snapshot."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    as_of = str((actors or {}).get("as_of_date") or "")[:10] if isinstance(actors, dict) else ""
    cutoff = None
    if as_of:
        try:
            cutoff = resolution_instant(as_of)
        except (TypeError, ValueError, OverflowError):
            cutoff = None

    def push(row: Dict[str, Any]) -> bool:
        vid = slugify(row.get("name"))
        if vid in seen or len(out) >= max_variables:
            return False
        seen.add(vid)
        out.append({"id": vid, **row})
        return True

    for fact in extract_quantitative_rows(actors):
        value_type = _clean(fact.get("value_type"), 40).casefold()
        if value_type not in _CURRENT_QUANTITATIVE_TYPES:
            continue
        period_end = str(fact.get("period_end") or "")[:10]
        if as_of and period_end and period_end > as_of:
            continue
        fact_as_of = str(fact.get("as_of_date") or fact.get("as_of") or "")[:10]
        if as_of and fact_as_of and fact_as_of > as_of:
            continue
        name = _clean(fact.get("metric"), 140)
        if not name:
            continue
        number, parsed_unit = parse_quantity(fact.get("value"))
        unit = _clean(fact.get("unit"), 24) or parsed_unit
        row: Dict[str, Any] = {
            "name": name,
            "value": number if number is not None else _clean(fact.get("value"), 160),
            "unit": unit if number is not None else "",
            "kind": "numeric" if number is not None else "text",
            "as_of": _clean(fact.get("as_of_date") or fact.get("as_of"), 40) or (as_of or None),
            "provenance": "research",
        }
        source = _clean(fact.get("source"), 120)
        definition = _clean(fact.get("definition"), 160)
        rationale = "; ".join(x for x in (definition, source) if x)
        if rationale:
            row["rationale"] = rationale
        push(row)

    series = official_data.get("series") if isinstance(official_data, dict) else None
    api = data_api()
    taken = 0
    for row in series if isinstance(series, list) else []:
        if taken >= MAX_OFFICIAL_SERIES or len(out) >= max_variables:
            break
        if not isinstance(row, dict):
            continue
        name = _clean(row.get("title") or row.get("name") or row.get("series"), 140)
        units = _clean(row.get("units"), 24)
        obs = row.get("observations")
        if not name or not units or not isinstance(obs, list):
            continue  # the official snapshot applies the same no-units exclusion
        latest: Optional[Dict[str, Any]] = None
        if api is not None:
            try:
                carrier = api.Series.from_dict(dict(row))
            except (TypeError, ValueError, KeyError, OverflowError):
                carrier = None
            if carrier is not None:
                try:
                    retrieved = resolution_instant(carrier.retrieved_at)
                except (TypeError, ValueError, OverflowError):
                    continue
                if cutoff is not None and retrieved > cutoff:
                    continue
                provenance = carrier.provenance
                aggregated = bool(provenance.get("aggregation") or provenance.get("aggregation_method"))
                inferred = carrier.series.startswith(_STATUS_INFERRED_PREFIXES) or "fidelity_policy_version" in provenance
                if provenance.get("resolution_safe") is False and not (aggregated or inferred):
                    continue
                for o in carrier.observations:
                    value = o.value
                    date = str(o.date or "")[:10]
                    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                        continue
                    if as_of and date and date > as_of:
                        continue
                    kind = api.observation_kind(o, carrier)
                    if kind not in ("observed", "preliminary"):
                        continue
                    if latest is None or date > str(latest.get("date") or ""):
                        latest = {"date": date, "value": float(value)}
            else:
                for o in obs:
                    if not isinstance(o, dict):
                        continue
                    value = o.get("value")
                    date = str(o.get("date") or "")[:10]
                    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                        continue
                    if as_of and date and date > as_of:
                        continue
                    if latest is None or date > str(latest.get("date") or ""):
                        latest = {"date": date, "value": float(value)}
        else:
            for o in obs:
                if not isinstance(o, dict):
                    continue
                value = o.get("value")
                date = str(o.get("date") or "")[:10]
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                    continue
                if as_of and date and date > as_of:
                    continue
                if latest is None or date > str(latest.get("date") or ""):
                    latest = {"date": date, "value": float(value)}
        if latest is None:
            continue
        provider = _clean(row.get("provider_name") or row.get("provider"), 80)
        if push({"name": name, "value": latest["value"], "unit": units, "kind": "numeric",
                 "as_of": latest["date"] or None, "provenance": "official",
                 "rationale": provider or "official statistics"}):
            taken += 1
    return out


# --- EXOGENOUS SHOCKS (design §2.12) ------------------------------------------------------------------
# A researched risk becomes a shock only when the dossier documents it: an event, a probability (a
# number in (0, 1), a percentage or a count such as "1 in 20" / "2 of 10 years"), the window that
# probability refers to (a calendar unit, a number of them, or the forecast horizon) and a source.
# Anything missing is a typed modelling gap — never an invented number.  The documented window is
# turned into a per-day hazard under a constant-hazard assumption (p_window = 1 − exp(−hazard × days));
# the kernel turns the hazard back into a probability for each period's own length.  A window that is a
# stretch of the calendar ("October–December 2026", see DATED WINDOWS) is also where the shock can fire:
# the kernel rolls it only on the days a period shares with that stretch, a stretch already over at the
# as-of date is ``shock_window_elapsed``, one starting after the horizon ``shock_window_after_horizon``;
# one partly over keeps the hazard of its full length, so its remaining days are never given the whole
# probability.  Effects bind only
# to variables the world tracks; a documented direction without a size moves nothing mechanically
# (the arbiter sizes it).
MAX_SHOCKS = 8
MAX_SHOCK_EFFECTS = 4
MAX_SHOCK_GAPS = 8
_WINDOW_DAYS = {"day": 1.0, "week": 7.0, "month": 30.4375, "quarter": 91.3125, "half_year": 182.625,
                "year": 365.25}
# unit words; CJK forms are the explicit periodic ones only ("2027年" is a date, never a window)
_WINDOW_UNIT_WORDS = (
    ("half_year", r"half[- ]?years?|semi[- ]?annual(?:ly)?|six[- ]months?|每半年|半年"),
    ("quarter", r"quarters?|quarterly|每季度|每季|季度"),
    ("month", r"months?|monthly|每月|月度"),
    ("week", r"weeks?|weekly|每周"),
    ("day", r"days?|daily|每日|每天"),
    ("year", r"years?|yearly|annual(?:ly)?|annum|每年|年度|年内"),
)
_WINDOW_COUNTED_UNITS = (
    ("half_year", r"half[- ]?years?"), ("quarter", r"quarters?|个季度"), ("month", r"months?|个月"),
    ("week", r"weeks?|周"), ("day", r"days?|天"), ("year", r"years?|年"),
)
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                 "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "eighteen": 18, "twenty": 20, "thirty": 30}
_HORIZON_RE = re.compile(r"\bhorizon\b|forecast (?:window|period)|预测期|预测窗口", re.IGNORECASE)
_COUNT_DENOMINATOR_RE = re.compile(r"(?:\bof|\bin|out of|/)\s*$", re.IGNORECASE)
_PROBABILITY_KEYS = ("probability", "base_rate", "likelihood", "prob", "frequency", "outcome_frequency")
_WINDOW_KEYS = ("per", "window", "period", "time_window", "horizon")
_SOURCE_KEYS = ("source", "basis", "source_ref", "evidence", "citation")
_EFFECT_REF_KEYS = ("variable_id", "variable", "metric", "indicator", "name")
_UP_WORDS = frozenset("up rise rises rising increase increases higher raise raises surge surges jump jumps spike "
                      "spikes".split())
_DOWN_WORDS = frozenset("down fall falls falling decrease decreases lower drop drops decline declines cut cuts "
                        "plunge plunges".split())
_UP_CJK = ("上升", "上涨", "提高", "增加", "走高")
_DOWN_CJK = ("下降", "下跌", "降低", "减少", "走低")
_SIGNED_NUMBER = r"[+-]?\d[\d,]*(?:\.\d+)?"
_RANGE_RE = re.compile(r"\d\s*(?:to|–|—|~|-|至|到)\s*[+-]?\d")


def parse_risk_probability(raw: Any) -> Optional[float]:
    """A documented probability in [0, 1]: a number in [0, 1], "5%", "1 in 20", "2 of 10", "3/20" or
    "0.05"; None when no probability is stated or it falls outside [0, 1]."""
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        return value if math.isfinite(value) and 0.0 <= value <= 1.0 else None
    text = _clean(raw, 160).casefold()
    if not text:
        return None
    m = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*%", text)
    if m:
        value = float(m.group(1)) / 100.0
    else:
        m = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:in|out of|of|/)\s*(\d+(?:\.\d+)?)(?![\d.])", text)
        if m:
            denominator = float(m.group(2))
            if denominator <= 0:
                return None
            value = float(m.group(1)) / denominator
        else:
            m = re.fullmatch(r"(\d*\.\d+|\d+)", text.strip())
            if not m:
                return None
            value = float(m.group(1))
    return value if 0.0 <= value <= 1.0 else None


def parse_risk_window(raw: Any, *, horizon_days: Optional[float] = None) -> Optional[Tuple[str, float]]:
    """``(label, days)`` of the window a documented probability refers to: the forecast horizon, a
    number of calendar units ("within 9 months"), or one unit ("per month", "annual", "2 of 10 years"
    counts years); None when the text states none (or the horizon length is unknown)."""
    text = _clean(raw, 160)
    if not text:
        return None
    if _HORIZON_RE.search(text):
        return ("horizon", float(horizon_days)) if horizon_days and horizon_days > 0 else None
    low = text.casefold()
    for label, words in _WINDOW_COUNTED_UNITS:
        for m in re.finditer(rf"(?<![\d.])(\d{{1,3}}(?:\.\d+)?)\s*-?\s*(?:{words})(?![a-z])", low):
            if _COUNT_DENOMINATOR_RE.search(low[:m.start()]):
                continue                                  # "2 of 10 years": a count of years, i.e. per year
            n = float(m.group(1))
            if n > 0:
                return (f"{m.group(1)} {label}", n * _WINDOW_DAYS[label])
    # spelled-out counts ("a three-month window") are counts too, never the bare unit ("per month")
    for label, words in _WINDOW_COUNTED_UNITS:
        for m in re.finditer(rf"(?<![a-z])({'|'.join(_NUMBER_WORDS)})\s*-?\s*(?:{words})(?![a-z])", low):
            if not _COUNT_DENOMINATOR_RE.search(low[:m.start()]):
                n = _NUMBER_WORDS[m.group(1)]
                return (f"{n} {label}", n * _WINDOW_DAYS[label])
    for label, words in _WINDOW_UNIT_WORDS:
        if re.search(rf"(?<![a-z])(?:{words})(?![a-z])", low):
            return (label, _WINDOW_DAYS[label])
    return None


# DATED WINDOWS (handoff research-risks §12 P2, 2026-10-21): published outlooks state a probability for
# a stretch of the calendar ("83% October–December", "DJF 2026-27", "by 31 March 2027"), not per unit of
# time.  ``calendar_window_spec`` reads the forms of the research extraction (linear_research's
# ``_CAL_PATTERNS``, the same grammar; parity pinned by test_research_frame_risks) plus a bare year ("in
# 2027"); ``parse_dated_window`` places the span on the calendar.  A span written without a year is its
# first occurrence that has not ended at the as-of date; "until <date>" runs from the as-of date.  Ambiguous
# text is no window: a span across the new year with one plain year ("Nov-Jan 2027"), "by 2030", a named
# season ("winter 2026-27" depends on the hemisphere), a CPC season code not written in capitals.
_CAL_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
               "october", "november", "december")
_CAL_MONTH_NUMBERS = {**{name: i for i, name in enumerate(_CAL_MONTHS, 1)},
                      **{name[:3]: i for i, name in enumerate(_CAL_MONTHS, 1)}, "sept": 9}
_CAL_MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
              r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)(?![a-z])\.?")
_CAL_YEAR = r"(?:19|20)\d{2}"
_CAL_SEASONS = {"jfm": (1, 3), "fma": (2, 4), "mam": (3, 5), "amj": (4, 6), "mjj": (5, 7), "jja": (6, 8),
                "jas": (7, 9), "aso": (8, 10), "son": (9, 11), "ond": (10, 12), "ndj": (11, 1), "djf": (12, 2)}
_CAL_ORDINALS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4,
                 "一": 1, "二": 2, "三": 3, "四": 4}
_CAL_DATE = (rf"(?:\d{{1,2}}(?:st|nd|rd|th)?\s+{_CAL_MONTH},?(?:\s+{_CAL_YEAR})?"
             rf"|{_CAL_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?(?![\d:])(?:,?\s+{_CAL_YEAR})?"
             rf"|{_CAL_YEAR}-\d{{1,2}}-\d{{1,2}}|{_CAL_YEAR}年\d{{1,2}}月\d{{1,2}}日)")
_CAL_SEP = r"\s*(?:-|–|—|‐|‑|~|to|through|thru|until|till|至|到)\s*"
_CAL_PATTERNS = (     # tried in this order; a later match may not overlap an earlier one
    ("dates", re.compile(rf"(?<![\w]){_CAL_DATE}{_CAL_SEP}{_CAL_DATE}")),
    ("months", re.compile(rf"(?<![a-z])(?P<m1>{_CAL_MONTH})(?:\s+(?P<y1>{_CAL_YEAR}))?{_CAL_SEP}"
                          rf"(?P<m2>{_CAL_MONTH})(?:,?\s*(?P<y2>{_CAL_YEAR})(?:\s*[-–—/]\s*(?P<y2b>\d{{2}}"
                          rf"(?!\d)|{_CAL_YEAR}))?)?")),
    ("months", re.compile(rf"(?:(?P<y1>{_CAL_YEAR})年)?(?<!\d)(?P<m1>\d{{1,2}})月?\s*(?:至|到|-|–|—|~)\s*"
                          rf"(?:(?P<y2>{_CAL_YEAR})年)?(?P<m2>\d{{1,2}})月(?!\d{{1,2}}日)")),
    ("until", re.compile(rf"(?<![\w])(?:through|thru|to|until|till|by|before|up to|ending)\s+(?:the\s+)?"
                         rf"(?P<end>end[\s-]+(?:of\s+)?)?(?:{_CAL_DATE}|{_CAL_MONTH}(?:\s+{_CAL_YEAR})?"
                         rf"|{_CAL_YEAR})(?![\w])")),
    ("until", re.compile(rf"(?:到|至|截至|截止)\s*{_CAL_YEAR}年\d{{1,2}}月\d{{1,2}}日"
                         rf"|{_CAL_YEAR}年\d{{1,2}}月\d{{1,2}}日\s*(?:之前|以前|前)"
                         rf"|(?:到|至|截至|截止)?\s*{_CAL_YEAR}年(?:\d{{1,2}}月)?底(?:之前|以前|前)?")),
    ("quarter", re.compile(rf"(?<![a-z0-9])q(?P<q>[1-4])(?:\s*[-/]?\s*(?P<y>{_CAL_YEAR}))?(?![a-z0-9])"
                           rf"|(?<![\d])(?P<y2>{_CAL_YEAR})\s*[-/]?\s*q(?P<q2>[1-4])(?![a-z0-9])"
                           rf"|(?<![a-z])(?P<o>first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter"
                           rf"(?:\s+(?:of\s+)?(?P<y3>{_CAL_YEAR}))?"
                           rf"|(?P<y4>{_CAL_YEAR})年(?:第)?(?P<o2>[一二三四1-4])季度")),
    ("season", re.compile(rf"(?<![a-z])(?P<code>{'|'.join(_CAL_SEASONS)})(?![a-z])"
                          rf"(?:\s*(?P<y>{_CAL_YEAR})(?:\s*[-–—/]\s*(?P<yb>\d{{2}}(?!\d)|{_CAL_YEAR}))?)?")),
    ("month", re.compile(rf"(?<![a-z\d])(?<!\d )(?<!\dst )(?<!\dnd )(?<!\drd )(?<!\dth )"
                         rf"(?P<m>{_CAL_MONTH})\s+(?P<y>{_CAL_YEAR})(?![\d])"
                         rf"|(?P<y2>{_CAL_YEAR})年(?P<m2>\d{{1,2}})月(?![\d底])")),
)
_CAL_YEAR_ONLY_RE = re.compile(rf"(?:in|during|for|over|throughout|through|across)?\s*(?:the\s+)?"
                               rf"(?:calendar\s+(?:year\s+)?|cy\s*)?(?P<y>{_CAL_YEAR})|(?P<y2>{_CAL_YEAR})年(?:全年|度)")


def _cal_month(token: Any) -> int:
    return _CAL_MONTH_NUMBERS.get(str(token or "").rstrip(".").casefold(), 0)


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _cal_valid_day(year: Optional[int], month: int, day: int) -> bool:
    if not 1 <= month <= 12:
        return False
    return 1 <= day <= (calendar.monthrange(year, month)[1] if year else 31)


def _cal_date(text: str) -> Optional[Tuple[Optional[int], int, int]]:
    """``(year or None, month, day)`` of one ``_CAL_DATE`` phrase."""
    m = re.fullmatch(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+({_CAL_MONTH}),?(?:\s+({_CAL_YEAR}))?", text)
    if m:
        year, month, day = (int(m.group(3)) if m.group(3) else None), _cal_month(m.group(2)), int(m.group(1))
    else:
        m = re.fullmatch(rf"({_CAL_MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+({_CAL_YEAR}))?", text)
        if m:
            year, month, day = (int(m.group(3)) if m.group(3) else None), _cal_month(m.group(1)), int(m.group(2))
        else:
            m = re.fullmatch(rf"({_CAL_YEAR})-(\d{{1,2}})-(\d{{1,2}})|({_CAL_YEAR})年(\d{{1,2}})月(\d{{1,2}})日", text)
            if not m:
                return None
            groups = m.groups()[:3] if m.group(1) else m.groups()[3:]
            year, month, day = (int(g) for g in groups)
    return (year, month, day) if _cal_valid_day(year, month, day) else None


def _cal_years(m1: int, m2: int, y1: Any, y2: Any, y2b: Any = None) -> Optional[Tuple[Optional[int], Optional[int]]]:
    """Start and end year of a month span as written: both, neither, or None when the text is
    ambiguous (a span across the new year with one plain year: "Nov-Jan 2027")."""
    wrap = m2 < m1
    y1, y2 = (int(y1) if y1 else None), (int(y2) if y2 else None)
    if y2b:
        if y1 is not None or y2 is None or not wrap:
            return None
        end = (y2 // 100) * 100 + int(y2b) if len(str(y2b)) == 2 else int(y2b)
        return (y2, end) if end == y2 + 1 else None
    if y1 is not None and y2 is not None:
        return (y1, y2) if 0 <= (y2 * 12 + m2) - (y1 * 12 + m1) <= 11 else None
    if y1 is not None:
        return (y1, y1 + wrap)
    if y2 is not None:
        return None if wrap else (y2, y2)
    return (None, None)


def _cal_spec(kind: str, m: Any, raw: str) -> Optional[tuple]:
    """The calendar span one ``_CAL_PATTERNS`` match names: ("months", y1, m1, y2, m2), ("until", y,
    m, d) or ("dates", y1, m1, d1, y2, m2, d2), a year or a day None when the text leaves it open
    (m None: the end of that year, d None: the end of that month)."""
    text = m.group(0)
    names = m.groupdict()
    if kind == "dates":
        found = [_cal_date(d.group(0).strip()) for d in re.finditer(_CAL_DATE, text)]
        if len(found) != 2 or None in found:
            return None
        (y1, m1, d1), (y2, m2, d2) = found
        if y1 is None and y2 is not None:
            y1 = y2 if (m1, d1) <= (m2, d2) else y2 - 1
        elif y2 is None and y1 is not None:
            y2 = y1 if (m1, d1) <= (m2, d2) else y1 + 1
        if y1 is not None and (y1, m1, d1) > (y2, m2, d2):
            return None
        return ("dates", y1, m1, d1, y2, m2, d2)
    if kind == "months":
        cjk = names["m1"].isdigit()
        m1, m2 = (int(names["m1"]), int(names["m2"])) if cjk else (_cal_month(names["m1"]), _cal_month(names["m2"]))
        if not (1 <= m1 <= 12 and 1 <= m2 <= 12) or m1 == m2:
            return None
        if cjk:                                        # CJK: each year is written beside its month
            wrap = m2 < m1
            y1 = int(names["y1"]) if names.get("y1") else (int(names["y2"]) - wrap if names.get("y2") else None)
            y2 = int(names["y2"]) if names.get("y2") else (y1 + wrap if y1 is not None else None)
            years = (y1, y2) if y1 is None or 0 <= (y2 * 12 + m2) - (y1 * 12 + m1) <= 11 else None
        else:
            years = _cal_years(m1, m2, names["y1"], names["y2"], names.get("y2b"))
        return ("months", years[0], m1, years[1], m2) if years else None
    if kind == "until":
        cjk = re.search(rf"({_CAL_YEAR})年(?:(\d{{1,2}})月)?(?:(\d{{1,2}})日|底)", text)
        date_hit = re.search(_CAL_DATE, text[text.find(" "):]) if " " in text else None
        month_hit = re.search(rf"(?<![a-z])({_CAL_MONTH})(?:\s+({_CAL_YEAR}))?", text[text.find(" "):]) \
            if " " in text else None
        if cjk:
            year, month = int(cjk.group(1)), int(cjk.group(2)) if cjk.group(2) else None
            day = int(cjk.group(3)) if cjk.group(3) else None
            if month is None and day is not None:
                return None
        elif date_hit:
            parsed = _cal_date(date_hit.group(0).strip())
            if parsed is None:
                return None
            year, month, day = parsed
        elif month_hit:
            year = int(month_hit.group(2)) if month_hit.group(2) else None
            month, day = _cal_month(month_hit.group(1)), None
        elif names.get("end") and re.search(_CAL_YEAR, text):
            year, month, day = int(re.search(_CAL_YEAR, text).group(0)), None, None
        else:
            return None                                # "by 2030": the year's start or its end?
        if month is not None and day is not None and not _cal_valid_day(year, month, day):
            return None
        return ("until", year, month, day)
    if kind == "quarter":
        ordinal = names.get("o") or names.get("o2") or ""
        q = int(names.get("q") or names.get("q2") or _CAL_ORDINALS.get(ordinal)
                or (ordinal if ordinal.isdigit() else 0))
        year = names.get("y") or names.get("y2") or names.get("y3") or names.get("y4")
        y = int(year) if year else None
        return ("months", y, 3 * q - 2, y, 3 * q) if 1 <= q <= 4 else None
    if kind == "season":
        code = names["code"]
        if not re.search(rf"(?<![A-Za-z]){code.upper()}(?![A-Za-z])", raw):
            return None                                # "son", "mam": words, not CPC season codes
        m1, m2 = _CAL_SEASONS[code]
        years = _cal_years(m1, m2, None, names.get("y"), names.get("yb"))
        return ("months", years[0], m1, years[1], m2) if years else None
    month = _cal_month(names.get("m")) if names.get("m") else int(names.get("m2") or 0)
    year = int(names.get("y") or names.get("y2") or 0)
    return ("months", year, month, year, month) if 1 <= month <= 12 and year else None


def calendar_window_spec(raw: Any) -> Optional[tuple]:
    """The one calendar span a window text names (see ``_cal_spec``), or None when it names none or
    several.  A whole text that is just a year ("in 2027", "calendar 2027", "2027年全年") is that year."""
    text = _clean(raw, 160)
    if not text:
        return None
    key = " ".join(text.casefold().split())
    year_only = _CAL_YEAR_ONLY_RE.fullmatch(key)
    if year_only:
        y = int(year_only.group("y") or year_only.group("y2"))
        return ("months", y, 1, y, 12)
    taken: List[Tuple[int, int, Optional[tuple]]] = []
    for kind, pattern in _CAL_PATTERNS:
        for m in pattern.finditer(key):
            if not any(m.start() < end and start < m.end() for start, end, _ in taken):
                taken.append((m.start(), m.end(), _cal_spec(kind, m, text)))
    spans = {spec for _, _, spec in taken if spec is not None}
    return spans.pop() if len(spans) == 1 else None


def _iso_day(raw: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def _resolve_span(spec: tuple, as_of: Optional[date]) -> Optional[Tuple[date, date]]:
    """``(start, end)`` of a calendar span; a span without a year is its first occurrence that has
    not ended at ``as_of`` and an "until" span starts at ``as_of`` (None without it)."""
    kind = spec[0]
    try:
        if kind == "until":
            _, year, month, day = spec
            if as_of is None:
                return None

            def end_of(y: int) -> date:
                return date(y, 12, 31) if month is None else _month_end(y, month) if day is None \
                    else date(y, month, day)
            if year is None:
                year = as_of.year if end_of(as_of.year) >= as_of else as_of.year + 1
            return as_of, end_of(year)
        if kind == "months":
            _, y1, m1, y2, m2 = spec
            if y1 is not None:
                return date(y1, m1, 1), _month_end(y2, m2)
            if as_of is None:
                return None
            wrap = int(m2 < m1)
            for y in (as_of.year - 1, as_of.year, as_of.year + 1):
                if _month_end(y + wrap, m2) >= as_of:
                    return date(y, m1, 1), _month_end(y + wrap, m2)
            return None
        _, y1, m1, d1, y2, m2, d2 = spec
        if y1 is not None:
            return date(y1, m1, d1), date(y2, m2, d2)
        if as_of is None:
            return None
        wrap = int((m2, d2) < (m1, d1))
        for y in (as_of.year - 1, as_of.year, as_of.year + 1):
            try:
                start, end = date(y, m1, d1), date(y + wrap, m2, d2)
            except ValueError:                         # 29 February of a common year
                continue
            if end >= as_of:
                return start, end
        return None
    except ValueError:
        return None


def parse_dated_window(raw: Any, *, as_of: Any = None) -> Optional[Tuple[date, date]]:
    """``(start, end)`` (both days included) of the calendar stretch a documented probability refers
    to ("October–December 2026", "DJF 2026-27", "Q1 2027", "by 31 March 2027", "in 2027"); None when
    the text names no such stretch, names it ambiguously, or needs an as-of date it is not given."""
    spec = calendar_window_spec(raw)
    if spec is None:
        return None
    span = _resolve_span(spec, _iso_day(as_of) if as_of else None)
    return span if span is not None and (span[0] <= span[1] or spec[0] == "until") else None


def _horizon_days(as_of: Any, horizon: Any) -> Optional[float]:
    try:
        days = (date.fromisoformat(str(horizon)[:10]) - date.fromisoformat(str(as_of)[:10])).days
    except (TypeError, ValueError):
        return None
    return float(days) if days > 0 else None


def _direction_word(raw: Any) -> str:
    low = _clean(raw, 40).casefold()
    words = set(re.findall(r"[a-z]+", low))
    up = bool(words & _UP_WORDS) or any(w in low for w in _UP_CJK)
    down = bool(words & _DOWN_WORDS) or any(w in low for w in _DOWN_CJK)
    return "up" if up and not down else "down" if down and not up else ""


def _match_tracked_variable(ref: Any, variables: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The seeded state variable an effect names: id, then name, then the longest contained name."""
    text = _clean(ref, 140)
    if not text:
        return None
    key, want = slugify(text), normalize_name(text)
    for var in variables:
        if str(var.get("id") or "") == key or normalize_name(str(var.get("name") or "")) == want:
            return var
    best: Optional[Tuple[int, Dict[str, Any]]] = None
    for var in variables:
        name = normalize_name(str(var.get("name") or ""))
        if len(name) >= 4 and (name in want or (len(want) >= 4 and want in name)):
            if best is None or len(name) > best[0]:
                best = (len(name), var)
    return best[1] if best else None


def _parse_change(text: str, unit: str, direction: str) -> Tuple[Optional[str], Optional[float]]:
    """``(op, value)`` of a documented change: "to 150" → set, "+30%" → mul (unless the fact is itself a
    percentage: then +30% is ambiguous), "+50 bp" / "+2 pp" → add on a percentage, "+25" / "-5 bn" →
    add.  An unsigned size takes its sign from a documented direction.  ``(None, None)`` = no size."""
    low = _clean(text, 80).casefold().replace("−", "-").strip()
    if not low:
        return None, None
    if _RANGE_RE.search(low):
        return None, None                             # "+30% to +50%": a range has no single documented size
    m = re.match(r"^(?:to|=|→|->|至|到)\s*(.+)$", low)
    if m:
        number, _ = parse_quantity(m.group(1))
        return ("set", number) if number is not None else (None, None)
    if low[0] not in "+-" and direction:
        low = ("+" if direction == "up" else "-") + low
    is_pct_fact = unit.strip() == "%"
    m = re.fullmatch(rf"({_SIGNED_NUMBER})\s*%", low)
    if m:
        if is_pct_fact:
            return None, None                         # +30% of a percentage: points or relative? unstated
        return "mul", 1.0 + float(m.group(1).replace(",", "")) / 100.0
    m = re.fullmatch(rf"({_SIGNED_NUMBER})\s*(pp|percentage points?|个百分点|bps?|basis points?|个基点)", low)
    if m:
        if not is_pct_fact:
            return None, None
        value = float(m.group(1).replace(",", ""))
        return "add", value / 100.0 if m.group(2).startswith(("bp", "basis", "个基")) else value
    m = re.fullmatch(r"([+-])\s*(.+)", low)
    if m:
        number, parsed_unit = parse_quantity(m.group(2))
        if number is not None and parsed_unit != "%":
            return "add", number if m.group(1) == "+" else -number
    return None, None


def _shock_effect(raw: Any, variables: Sequence[Dict[str, Any]],
                  gap: Any) -> Optional[Dict[str, Any]]:
    """One documented effect bound to a tracked variable, or None (recorded through ``gap``)."""
    if isinstance(raw, str):
        raw = {"variable": raw}
    if not isinstance(raw, dict):
        return None
    ref = next((raw.get(k) for k in _EFFECT_REF_KEYS if _clean(raw.get(k), 140)), None)
    var = _match_tracked_variable(ref, variables)
    if var is None:
        gap("shock_effect_untracked", f"effect on '{_clean(ref, 60) or '?'}', which the world does not track; dropped")
        return None
    direction = _direction_word(raw.get("direction"))
    text = _clean(next((raw.get(k) for k in ("change", "size", "magnitude", "effect") if raw.get(k) not in (None, "")),
                       ""), 80)
    op: Optional[str] = None
    value: Any = None
    if str(var.get("kind") or "numeric") == "numeric":
        current = var.get("value") if isinstance(var.get("value"), (int, float)) else None
        for keys, kind in ((("new_value", "to"), "set"), (("delta",), "add"),
                           (("change_pct", "pct_change", "percent_change"), "mul")):
            got = next((raw.get(k) for k in keys if raw.get(k) not in (None, "")), None)
            number, parsed_unit = parse_quantity(got) if got is not None else (None, "")
            if kind != "mul" and parsed_unit == "%" and str(var.get("unit") or "").strip() != "%":
                number = None                         # "delta: -5%" of a non-percentage fact is not -5 units
            if number is not None:
                op, value = kind, (1.0 + number / 100.0 if kind == "mul" else number)
                break
        if op is None and text:
            op, value = _parse_change(text, str(var.get("unit") or ""), direction)
            if op is None and not direction and text.lstrip()[:1] in ("+", "-", "−"):
                direction = "up" if text.lstrip()[0] == "+" else "down"   # the sign survives an unreadable size
        if op == "mul" and (value is None or value <= 0):
            gap("shock_effect_unreadable", f"effect on '{var.get('name')}' would wipe out or flip the fact; dropped")
            return None
        implied = ""
        if op == "add" and value:
            implied = "up" if value > 0 else "down"
        elif op == "mul" and value != 1.0:
            implied = "up" if value > 1.0 else "down"
        elif op == "set" and current is not None and value != current:
            implied = "up" if value > current else "down"
        if direction and implied and implied != direction:
            gap("shock_effect_unreadable", f"effect on '{var.get('name')}' contradicts its own direction; dropped")
            return None
        direction = direction or implied
    else:
        got = next((raw.get(k) for k in ("new_value", "to") if raw.get(k) not in (None, "")), None)
        m = re.match(r"^(?:to|=|→|->|至|到)\s*(.+)$", text, re.IGNORECASE) if got is None and text else None
        target = _clean(got if got is not None else (m.group(1) if m else ""), 80)
        if target:
            op, value = "set", target
    if op is None and not direction:
        gap("shock_effect_unreadable", f"effect on '{var.get('name')}' states neither a size nor a direction; dropped")
        return None
    if op is None:
        gap("shock_effect_direction_only", f"effect on '{var.get('name')}' documents a direction only; the arbiter sizes it")
    return {"variable_id": str(var.get("id")), "variable": _clean(var.get("name"), 140), "op": op,
            "value": value, "direction": direction, "text": text}


def shocks_from_research(actors: Optional[Dict[str, Any]], variables: Sequence[Dict[str, Any]],
                         cast: Optional[Dict[str, str]] = None, *, as_of: Any = None,
                         horizon: Any = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """Seed ``shocks`` from the dossier's documented risks, plus the typed gaps of the rows that do not
    qualify (see the comment above ``MAX_SHOCKS``).  ``cast`` maps normalised names to cast names for
    ``affects``.  Pure and never raises."""
    shocks: List[Dict[str, Any]] = []
    gaps: List[Dict[str, str]] = []
    horizon_days = _horizon_days(as_of, horizon)
    as_of_day, horizon_day = (_iso_day(as_of) if as_of else None), (_iso_day(horizon) if horizon else None)
    for row in extract_risk_rows(actors):
        if len(shocks) >= MAX_SHOCKS:
            break
        event = _clean(row.get("event") or row.get("risk") or row.get("name") or row.get("description"), 200)

        def gap(kind: str, note: str, _subject: str = event) -> None:
            if len(gaps) < MAX_SHOCK_GAPS:
                gaps.append({"kind": kind, "subject": _clean(_subject, 120), "note": _clean(note, 160)})

        raw_p = next((row.get(k) for k in _PROBABILITY_KEYS if row.get(k) not in (None, "")), None)
        p = parse_risk_probability(raw_p)
        if p is None or not 0.0 < p < 1.0:
            gap("shock_without_base_rate", "no probability strictly between 0 and 1 is stated (a certain event "
                                           "is a scheduled event); not modelled as a shock")
            continue
        raw_window = next((row.get(k) for k in _WINDOW_KEYS if _clean(row.get(k), 80)), None)
        window_text = raw_window if raw_window is not None else raw_p
        window = parse_risk_window(window_text, horizon_days=horizon_days)
        dated = parse_dated_window(window_text, as_of=as_of)
        if window is None and dated is None:
            gap("shock_without_window", "the window of its probability (per day … year, a stretch of the "
                                        "calendar, or the forecast horizon) is not stated; not modelled as a shock")
            continue
        if dated is not None:
            start, end = dated
            if as_of_day is not None and end < as_of_day:
                gap("shock_window_elapsed", f"its window ({start.isoformat()} to {end.isoformat()}) ended before "
                                            "the as-of date; not modelled as a shock")
                continue
            if horizon_day is not None and start > horizon_day:
                gap("shock_window_after_horizon", f"its window ({start.isoformat()} to {end.isoformat()}) starts "
                                                  "after the forecast horizon; not modelled as a shock")
                continue
            if window is None:                         # the probability covers the whole stretch
                window = ("dated", float((end - start).days + 1))
        source = _clean(next((row.get(k) for k in _SOURCE_KEYS if _clean(row.get(k), 160)), ""), 160)
        if not source:
            gap("shock_without_source", "no source for its probability; not modelled as a shock")
            continue
        sid = "shock_" + slugify(event, 40)
        if dated is not None:                          # one event documented for several stretches
            sid += f"_{dated[0]:%Y%m}_{dated[1]:%Y%m}"
        if any(s["id"] == sid for s in shocks):
            continue
        effects = []
        raw_effects = row.get("effects")
        for raw in (raw_effects if isinstance(raw_effects, list) else [raw_effects] if raw_effects else []):
            effect = _shock_effect(raw, variables, gap)
            if effect is not None and len(effects) < MAX_SHOCK_EFFECTS:
                effects.append(effect)
        affects: List[str] = []
        raw_affects = row.get("affects") or row.get("actors") or row.get("targets")
        for name in (raw_affects if isinstance(raw_affects, list) else [raw_affects] if raw_affects else []):
            hit = (cast or {}).get(normalize_name(str(name or "")))
            if hit and hit not in affects:
                affects.append(hit)
        label, days = window
        base_rate = {"probability": round(p, 6), "window": label, "window_days": round(days, 4),
                     "text": _clean(raw_p, 80)}
        if dated is not None:                          # the kernel rolls it only inside this stretch
            base_rate.update(window_start=dated[0].isoformat(), window_end=dated[1].isoformat(),
                             window_text=_clean(window_text, 80))
        shocks.append({
            "id": sid, "event": event,
            "base_rate": base_rate,
            "hazard_per_day": -math.log1p(-p) / days,
            "source": source, "effects": effects, "affects": affects[:6],
            "recurring": row.get("recurring") is True,
        })
    return shocks, gaps


def build_world_model_seed(
    actors: Optional[Dict[str, Any]],
    agent_configs: Sequence[Any],
    *,
    question: str = "",
    actor_context_packs: Optional[Dict[str, Dict[str, Any]]] = None,
    official_data: Optional[Dict[str, Any]] = None,
    temporal_timeline: Any = None,
    audience_entity_type: str = "Audience",
    ontology_classes: Optional[Dict[str, str]] = None,
    max_variables: int = DEFAULT_MAX_VARIABLES,
    arbiter_enabled: bool = True,
    max_change_ratio: float = 0.5,
    barrier_timeout_s: float = 1800.0,
    pressure_weight: Optional[float] = None,
) -> Dict[str, Any]:
    """The sealed ``world_model`` block.  Degrades to a smaller block, never raises.

    ``pressure_weight`` (backtest ablation) pins ``settings.pressure_weight``, the
    world channel's weight the runner reads before SIM_WORLD_PRESSURE_WEIGHT;
    ``None`` leaves the block as before."""
    block: Dict[str, Any] = {
        "schema_version": WORLD_MODEL_SEED_VERSION,
        "question": _clean(question, 400),
        "as_of_date": None,
        "horizon_date": None,
        "scenarios": [],
        "state_variables": [],
        "actors": [],
        "relationships": [],
        "scenario_indicators": [],
        "settings": {
            "arbiter_enabled": bool(arbiter_enabled),
            "max_change_ratio": float(max_change_ratio),
            "barrier_timeout_s": float(barrier_timeout_s),
        },
    }
    if pressure_weight is not None:
        block["settings"]["pressure_weight"] = max(0.0, float(pressure_weight))
    actors_dict = actors if isinstance(actors, dict) else {}
    try:
        block["as_of_date"] = _clean(actors_dict.get("as_of_date"), 40) or None
        if temporal_timeline is not None:
            block["as_of_date"] = _clean(getattr(temporal_timeline, "as_of_date", None)
                                         or (temporal_timeline.get("as_of_date") if isinstance(temporal_timeline, dict) else None), 40) or block["as_of_date"]
            block["horizon_date"] = _clean(getattr(temporal_timeline, "horizon_date", None)
                                           or (temporal_timeline.get("horizon_date") if isinstance(temporal_timeline, dict) else None), 40) or None
        fi = extract_forecast_inputs(actors_dict)
        block["scenarios"] = _dedupe(
            (str(s.get("name") or s.get("scenario") or "") for s in fi.get("scenarios") or []), 8)
        block["scenario_indicators"] = [
            {"indicator": _clean(i.get("indicator") or i.get("name") or i.get("metric"), 160),
             "direction": _clean(i.get("direction") or i.get("signal"), 60)}
            for i in (fi.get("indicators") or [])[:8]
            if isinstance(i, dict) and _clean(i.get("indicator") or i.get("name") or i.get("metric"), 160)
        ]
    except Exception:  # noqa: BLE001
        pass
    try:
        block["state_variables"] = state_variables_from_research(actors_dict, official_data,
                                                                 max_variables=max_variables)
    except Exception:  # noqa: BLE001
        block["state_variables"] = []

    # actors ------------------------------------------------------------------------------
    packs = actor_context_packs if isinstance(actor_context_packs, dict) else {}
    pack_by_name: Dict[str, Dict[str, Any]] = {}
    for pack in packs.values():
        if isinstance(pack, dict) and pack.get("actor_name"):
            pack_by_name[normalize_name(str(pack["actor_name"]))] = pack
    name_to_agent: Dict[str, int] = {}
    rows: List[Dict[str, Any]] = []
    for cfg in agent_configs or []:
        try:
            aid = _cfg_get(cfg, "agent_id")
            if aid is None:
                continue
            aid = int(aid)
            entity_type = str(_cfg_get(cfg, "entity_type", "") or "")
            if entity_type == audience_entity_type:
                continue
            name = _clean(_cfg_get(cfg, "entity_name", "") or f"Agent_{aid}", 160)
            actor = match_actor(name, actors_dict) if actors_dict else None
            actor = actor if isinstance(actor, dict) else None
            ontology_class = (ontology_classes or {}).get(entity_type, "") if ontology_classes else ""
            agency = resolve_agency_class(actor, entity_type, ontology_class)
            canonical = bool(actor and _is_canonical(actor))
            pack = pack_by_name.get(normalize_name(name)) if canonical else None
            if canonical:
                plans = _pack_claims(pack, _PLAN_DIMENSIONS, MAX_PLANS)
                red_lines = _pack_claims(pack, ("red_lines",), MAX_RED_LINES)
                goals = _pack_claims(pack, ("motivations", "values_worldview"), MAX_GOALS)
            else:
                plans = _legacy_list(actor or {}, _LEGACY_PLAN_KEYS, MAX_PLANS)
                red_lines = _legacy_list(actor or {}, _LEGACY_RED_LINE_KEYS, MAX_RED_LINES)
                goals = _legacy_list(actor or {}, ("goals", "objectives", "motivations"), MAX_GOALS)
                # research engine v3 rows: no plan / red-line keys → derive from the documented wording
                if actor and not plans:
                    plans = derive_v3_plans(actor, MAX_PLANS)
                if actor and not red_lines:
                    red_lines = derive_v3_red_lines(actor, MAX_RED_LINES)
            aliases = []
            if actor:
                raw_aliases = actor.get("aliases")
                if isinstance(raw_aliases, list):
                    aliases = _dedupe((_clean(a, 80) for a in raw_aliases), 6)
            incentives = {}
            for key in ("gains_if", "loses_if"):
                value = _clean(_cfg_get(cfg, key, ""), 220)
                if value:
                    incentives[key] = value
            row = {
                "agent_id": aid,
                "name": name,
                "agency_class": agency,
                "archetype": entity_archetype(actor) if actor else (
                    "collective" if agency == "public_collective" else "actor"),
                "capacity_per_round": default_capacity(agency),
                "outcome_power": _declared_outcome_power(actor, cfg if isinstance(cfg, dict) else {
                    "outcome_power": _cfg_get(cfg, "outcome_power")}),
                "posture": _clean(_cfg_get(cfg, "stance", ""), 60),
                "documented_plans": plans,
                "red_lines": red_lines,
                "goals": goals,
                "incentives": incentives,
                "aliases": aliases,
                "allies": [],
                "rivals": [],
            }
            rows.append(row)
            name_to_agent[normalize_name(name)] = aid
            for alias in aliases:
                name_to_agent.setdefault(normalize_name(alias), aid)
        except Exception:  # noqa: BLE001 — one malformed agent never drops the block
            continue
    block["actors"] = rows

    # relationships -------------------------------------------------------------------------
    rels: List[Dict[str, Any]] = []
    by_id = {r["agent_id"]: r for r in rows}
    try:
        for rel in extract_relationship_rows(actors_dict):
            s = name_to_agent.get(normalize_name(str(rel.get("source") or "")))
            t = name_to_agent.get(normalize_name(str(rel.get("target") or "")))
            if s is None or t is None or s == t:
                continue
            valence = relation_valence(rel)
            polarity = relation_polarity(rel)
            rels.append({
                "source_agent_id": s, "target_agent_id": t,
                "source": by_id[s]["name"], "target": by_id[t]["name"],
                "kind": str(rel.get("type") or "RELATES_TO").upper(),
                "valence": valence, "polarity": round(polarity, 4),
                "basis": _clean(rel.get("basis") or rel.get("evidence"), 160),
            })
            if valence == "allied":
                by_id[s]["allies"].append(by_id[t]["name"])
                by_id[t]["allies"].append(by_id[s]["name"])
            elif valence == "adversarial":
                by_id[s]["rivals"].append(by_id[t]["name"])
                by_id[t]["rivals"].append(by_id[s]["name"])
    except Exception:  # noqa: BLE001
        rels = []
    for row in rows:
        row["allies"] = _dedupe(row["allies"], 8)
        row["rivals"] = _dedupe(row["rivals"], 8)
    block["relationships"] = rels[:80]
    # EXOGENOUS SHOCKS: documented risks only; the rows that fall short become gaps below
    shock_gaps: List[Dict[str, str]] = []
    try:
        block["shocks"], shock_gaps = shocks_from_research(
            actors_dict, block["state_variables"], {normalize_name(r["name"]): r["name"] for r in rows},
            as_of=block["as_of_date"], horizon=block["horizon_date"])
    except Exception:  # noqa: BLE001
        block["shocks"] = []
    # MODELLING GAPS (ported from the world-v1 compiler's stance): what the research could not
    # ground is reported, never invented — the run, the panel and the report show the list
    block["gaps"] = (shock_gaps + seed_gaps(block))[:MAX_SEED_GAPS]
    return block


MAX_SEED_GAPS = 32


def seed_gaps(block: Dict[str, Any]) -> List[Dict[str, str]]:
    """Typed modelling gaps of a seed block: facts without units or dates, actors without
    documented goals / plans / levers, a cast with no grounded relationships."""
    gaps: List[Dict[str, str]] = []

    def add(kind: str, subject: str, note: str) -> None:
        if len(gaps) < MAX_SEED_GAPS:
            gaps.append({"kind": kind, "subject": _clean(subject, 120), "note": _clean(note, 160)})

    # EXOGENOUS SHOCKS (blocks built before 2026-10-20 carry no ``shocks`` key and report nothing);
    # listed first so a large cast's per-actor gaps never crowd it out
    if "shocks" in block and not block.get("shocks"):
        add("no_documented_shocks", "world", "no risk is documented with a probability, its window and a "
                                             "source; the world has no exogenous shocks")
    for var in block.get("state_variables") or []:
        if not isinstance(var, dict):
            continue
        name = str(var.get("name") or var.get("id") or "")
        if str(var.get("kind") or "numeric") == "numeric" and not str(var.get("unit") or "").strip():
            add("variable_without_unit", name, "numeric fact without a unit; the arbiter can only move it as a bare number")
        if str(var.get("provenance") or "research") in ("research", "official") and not str(var.get("as_of") or "").strip():
            add("variable_without_as_of", name, "no as-of date; staleness cannot be judged")
    actors = [a for a in (block.get("actors") or []) if isinstance(a, dict)]
    for a in actors:
        name = str(a.get("name") or f"Agent {a.get('agent_id')}")
        if a.get("agency_class") in (None, "", "other_actor"):
            add("actor_unclassified", name, "no agency class inferred; falls back to the generic option catalogue")
        if not a.get("goals"):
            add("actor_without_goals", name, "no documented goals; decisions lean on the role brief alone")
        if not a.get("documented_plans") and not a.get("red_lines"):
            add("actor_without_plans", name, "no documented plans or red lines; option menu is class-generic")
    if len(actors) >= 2 and not (block.get("relationships") or []):
        add("no_relationships", "cast", "no grounded relationships between the actors; alliances start from scratch")
    if not (block.get("state_variables") or []):
        add("no_state_variables", "world", "no quantitative facts to track; the world starts without numbers")
    return gaps


def world_model_seed_summary(block: Optional[Dict[str, Any]]) -> str:
    if not isinstance(block, dict):
        return ""
    gaps = block.get("gaps") if isinstance(block.get("gaps"), list) else []
    return (f"world model: {len(block.get('state_variables') or [])} variables, "
            f"{len(block.get('actors') or [])} actors, {len(block.get('relationships') or [])} relationships"
            + (f", {len(gaps)} modelling gaps" if gaps else ""))
