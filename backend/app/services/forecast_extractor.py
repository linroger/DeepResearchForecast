"""Structured, machine-readable forecast extraction + citation-grounding audit.

Turns a prose forecast report into a machine-checkable object — explicit
scenarios with calibrated probabilities, key drivers, and resolution criteria —
plus a lightweight audit of how well quantitative claims are cited. This is what
makes the pipeline's output *calibratable and backtestable* rather than a wall of
text. EXECPLAN2: I-3-0 / I-9-1 (structured forecast object), I-3-1 (citation
grounding audit). Optional-degrade: only runs when REPORT_STRUCTURED_FORECAST is on.

Kept dependency-light and side-effect-free (takes an LLM client, returns a dict)
so it is unit-testable offline with a fake client.
"""

from __future__ import annotations

import calendar
import hashlib
import logging
import math
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _cfg(name: str, default: Any) -> Any:
    """Read a Config flag with a safe default (degrade-safe; never raises).

    All new calibration behavior is gated through this so the DEFAULT/unflagged
    path is byte-identical to the pre-optimization pipeline.
    """
    try:
        from ..config import Config
        return getattr(Config, name, default)
    except Exception:  # noqa: BLE001 — config import must never break extraction
        return default


def forecast_language_rule(language: str) -> str:
    """Output-language directive for the structured-forecast prompts.

    The forecast prompts are written in Chinese, so without this rule an English
    report got a Chinese headline, scenario names, criteria and rationales in
    forecast.json — which the dashboard, the scenario chart and the executive brief
    all display verbatim.  Empty ``language`` returns "" (prompt unchanged).
    """
    lang = str(language or "").strip()
    if not lang:
        return ""
    lowered = lang.lower()
    if lowered.startswith(("zh", "chinese")) or "中文" in lang:
        return (
            "\n\n【输出语言】所有可读文本字段（headline、情景名、summary、key_drivers、"
            "base_rate_anchor、adjustment_rationale、resolution_criteria、key_uncertainties、"
            "confidence_rationale、critique_note、missed_signals 等）一律使用简体中文；"
            "JSON 键名与枚举值（low/medium/high）保持原样。"
        )
    return (
        f"\n\n[OUTPUT LANGUAGE] Write every human-readable string value in {lang}: "
        "headline, scenario names, summaries, key drivers, base-rate anchors, adjustment "
        "rationales, resolution criteria, key uncertainties, confidence rationale, critique "
        "notes and missed signals. Keep JSON keys and enum values (low/medium/high) exactly "
        "as specified."
    )


# JSON schema the extractor asks the model to fill. Mirrored in the prompt.
_FORECAST_INSTRUCTIONS = """你是预测校准专家。基于下面的预测报告，抽取一个**机器可读**的结构化预测对象。
只输出 JSON，不要解释。字段：
{
  "headline": "一句话核心结论",
  "horizon": "预测时间范围（如 '2030'）",
  "scenarios": [
    {
      "name": "情景名",
      "probability": 0.0-1.0,         // 所有情景概率之和应≈1
      "summary": "该情景的简述",
      "key_drivers": ["关键驱动因素", ...],
      "resolution_criteria": "可证伪的判定标准：到期时如何客观判断此情景是否发生"
    }
  ],
  "key_uncertainties": ["最大的不确定性来源", ...],
  "confidence": "low|medium|high",     // 对整体预测的信心
  "confidence_rationale": "信心评级的理由（数据质量/分歧度/时间跨度）"
}
要求：2-5 个互斥且尽量穷尽的情景；概率为数值；resolution_criteria 必须客观可验证。"""


def _coerce_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _normalize_scenarios(scenarios: Any, *, keep_metric_range: bool = False) -> List[Dict[str, Any]]:
    """Validate + normalize scenarios so probabilities are floats summing to ~1.0."""
    if not isinstance(scenarios, list):
        return []
    cleaned: List[Dict[str, Any]] = []
    for s in scenarios:
        if not isinstance(s, dict):
            continue
        prob = _coerce_float(s.get("probability"))
        row = {
            "name": str(s.get("name") or "未命名情景"),
            "probability": prob if prob is not None else 0.0,
            "summary": str(s.get("summary") or ""),
            "key_drivers": [str(x) for x in (s.get("key_drivers") or []) if x],
            "resolution_criteria": str(s.get("resolution_criteria") or ""),
        }
        # NEXTSTEPS P2-1（anchor-and-adjust）：保留参考类基率锚点与调整理由（若模型给出），
        # 让最终概率对"外部视角基率 + 案例调整"可审计；缺省则不增字段（degrade-safe）。
        if s.get("base_rate_anchor"):
            row["base_rate_anchor"] = str(s.get("base_rate_anchor"))
        if s.get("adjustment_rationale"):
            row["adjustment_rationale"] = str(s.get("adjustment_rationale"))
        if keep_metric_range and isinstance(s.get("metric_range"), dict):
            row["metric_range"] = dict(s["metric_range"])
        cleaned.append(row)
    total = sum(s["probability"] for s in cleaned)
    if total > 0:
        for s in cleaned:
            s["probability"] = s["probability"] / total
    # R2-CAL-4：对每个保留情景设下限再重新归一，避免「已实现但被预测到≈0%」的灾难性
    # log-loss/Brier。默认 0.0（无下限）→ 与旧路径逐字节一致；config 置 0.03 后生效。
    floor = _coerce_float(_cfg("FORECAST_PROB_FLOOR", 0.0)) or 0.0
    if cleaned and floor > 0:
        for s in cleaned:
            if s["probability"] < floor:
                s["probability"] = floor
        t2 = sum(s["probability"] for s in cleaned)
        if t2 > 0:
            for s in cleaned:
                s["probability"] = s["probability"] / t2
    for s in cleaned:
        s["probability"] = round(s["probability"], 4)
    return cleaned


# ------------------------------------------------------ scenario contract audit
_SCENARIO_SUM_TOLERANCE = 0.015
_SCENARIO_VALUE_TOLERANCE = 0.015
_SCENARIO_RESIDUAL_TERMS = (
    "status quo", "status-quo", "baseline", "residual",
    "other", "catch-all", "remainder", "everything else", "all else",
    "none of the above", "otherwise",
    "维持现状", "基准", "基线", "其它", "其他", "兜底", "剩余",
)

_CRITIQUE_TARGET_PATTERNS = (
    re.compile(
        r"\b(?:probability|likelihood|weight)\s+(?:was\s+|is\s+)?"
        r"(?:revised|adjusted|updated|reduced|increased|lowered|raised|set)"
        r"(?:\s+from\s+(?:0?\.\d+|\d+(?:\.\d+)?\s*%))?\s+"
        r"(?:to|at|=|:)\s*(?P<value>0?\.\d+|\d+(?:\.\d+)?)\s*"
        r"(?P<percent>%)?",
        re.I,
    ),
    re.compile(
        r"\b(?:revised|adjusted|updated|reduced|increased|lowered|raised|final|"
        r"current|new)\s+(?:scenario\s+)?(?:probability|likelihood|weight)"
        r"(?:\s+from\s+(?:0?\.\d+|\d+(?:\.\d+)?\s*%))?\s*"
        r"(?:to|at|=|:|is)?\s*(?P<value>0?\.\d+|\d+(?:\.\d+)?)\s*"
        r"(?P<percent>%)?",
        re.I,
    ),
    re.compile(
        r"(?:调整|修正|更新|下调|上调|降低|提高|最终)(?:后的)?"
        r"(?:情景)?(?:概率|权重)(?:从\s*(?:0?\.\d+|\d+(?:\.\d+)?\s*%)\s*)?"
        r"(?:为|至|到|=|：)\s*(?P<value>0?\.\d+|\d+(?:\.\d+)?)\s*"
        r"(?P<percent>%)?",
        re.I,
    ),
    re.compile(
        r"\b(?:scenario\s+)?(?:probability|likelihood|weight)\s*"
        r"(?:is|=|:)\s*(?P<value>0?\.\d+|\d+(?:\.\d+)?)\s*"
        r"(?P<percent>%)?",
        re.I,
    ),
    re.compile(
        r"(?:当前|最终|调整后|修正后)?(?:情景)?(?:概率|权重)\s*"
        r"(?:为|是|=|：)\s*(?P<value>0?\.\d+|\d+(?:\.\d+)?)\s*"
        r"(?P<percent>%)?",
        re.I,
    ),
)

_SCENARIO_ALLOCATION_SUBJECT = (
    r"(?:scenario(?:s)?\s+(?:probabilit(?:y|ies)|weights?|allocations?|"
    r"split|distribution|partition)|(?:probabilit(?:y|ies)|weights?)\s+"
    r"(?:across|among)\s+scenarios|probability\s+allocation|"
    r"scenario\s+probability\s+allocation)"
)
_EXPLICIT_TOTAL_PERCENT_PATTERNS = (
    re.compile(
        rf"\b{_SCENARIO_ALLOCATION_SUBJECT}\b[^.!?\n]{{0,120}}?\b"
        r"(?:sum(?:s|med)?|total(?:s|ed|ing)?|add(?:s|ed)?\s+up)\s*"
        r"(?:to|at|of|=|:|is)?\s*(?P<total>\d+(?:\.\d+)?)\s*%",
        re.I,
    ),
    re.compile(
        rf"\b{_SCENARIO_ALLOCATION_SUBJECT}\b[^.!?\n]{{0,120}}?"
        r"(?P<total>\d+(?:\.\d+)?)\s*%\s*(?:in\s+)?total\b",
        re.I,
    ),
    re.compile(
        r"(?:情景(?:概率|权重|分配|分布|组合)|概率分配)"
        r"[^。！？\n]{0,120}?(?:之和|合计|总计|加总)"
        r"(?:为|是|至|到|=|：)?\s*(?P<total>\d+(?:\.\d+)?)\s*%",
        re.I,
    ),
)
_PERCENT_ADDITION_RE = re.compile(
    r"(?P<expression>\d+(?:\.\d+)?\s*%"
    r"(?:\s*\+\s*\d+(?:\.\d+)?\s*%){1,})"
    r"(?:\s*=\s*(?P<stated>\d+(?:\.\d+)?)\s*%)?"
)
_ALLOCATION_CONTEXT_RE = re.compile(
    rf"\b{_SCENARIO_ALLOCATION_SUBJECT}\b|"
    r"情景(?:概率|权重|分配|拆分|分布|组合)|概率分配",
    re.I,
)


def _range_value_pattern(prefix: str) -> str:
    return (
        rf"(?P<{prefix}_currency>[$€£¥])?\s*"
        rf"(?P<{prefix}_number>[-+−]?\d+(?:,\d{{3}})*(?:\.\d+)?)\s*"
        rf"(?P<{prefix}_unit>%|[KMBT]\b|thousand\b|million\b|billion\b|"
        rf"trillion\b|seats?\b|points?\b|units?\b|tons?\b|tonnes?\b|"
        rf"barrels?\b|votes?\b)"
    )


_RANGE_METRIC = (
    r"(?P<metric>[A-Za-z\u4e00-\u9fff]"
    r"[A-Za-z0-9\u4e00-\u9fff /&()_-]{1,80}?)"
)
_BETWEEN_RANGE_RE = re.compile(
    rf"^\s*{_RANGE_METRIC}\s+(?:(?:is|will\s+be|must\s+be|remains?)\s+)?"
    rf"(?:between|from)\s+{_range_value_pattern('lo')}\s+"
    rf"(?:and|to)\s+{_range_value_pattern('hi')}",
    re.I,
)
_COLON_RANGE_RE = re.compile(
    rf"^\s*{_RANGE_METRIC}\s*[:：]\s*{_range_value_pattern('lo')}\s*"
    rf"(?:-|to)\s*{_range_value_pattern('hi')}",
    re.I,
)
_CHINESE_RANGE_RE = re.compile(
    rf"^\s*{_RANGE_METRIC}\s*(?:为|介于|在)?\s*"
    rf"{_range_value_pattern('lo')}\s*(?:至|到|-)\s*"
    rf"{_range_value_pattern('hi')}(?:\s*之间)?",
    re.I,
)
_COMPARATOR_RANGE_RE = re.compile(
    rf"^\s*{_RANGE_METRIC}\s+(?:(?:is|will\s+be|must\s+be|remains?|reaches?)\s+)?"
    rf"(?P<operator>>=|<=|>|<|at\s+least|at\s+most|more\s+than|"
    rf"less\s+than|above|below|exceeds?|under)\s+"
    rf"{_range_value_pattern('bound')}",
    re.I,
)
_CHINESE_COMPARATOR_RANGE_RE = re.compile(
    rf"^\s*{_RANGE_METRIC}\s*(?P<operator>高于|超过|不低于|至少|"
    rf"低于|少于|不超过|至多)\s*{_range_value_pattern('bound')}",
    re.I,
)


def _normalise_metric_label(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    text = re.sub(
        r"^(?:if|when|where|by|in|at|through)\s+(?:fy\s*)?20\d{2}\s*[,;:-]?\s*",
        "",
        text,
    )
    text = re.sub(r"^(?:the|a|an)\s+", "", text)
    text = text.strip(" ,;:-")
    has_named_metric = bool(
        re.search(r"[a-z]{3}", text) or re.search(r"[\u4e00-\u9fff]{2}", text)
    )
    if len(text) < 2 or not has_named_metric:
        return ""
    ascii_tokens = re.findall(r"[a-z]+", text)
    if ascii_tokens and all(
        token in {"scenario", "outcome", "result", "metric", "value"}
        for token in ascii_tokens
    ):
        return ""
    return text


def _is_residual_scenario_name(value: Any) -> bool:
    """Match residual labels as terms, never as substrings of actor names."""
    name = str(value or "").replace("–", "-").replace("—", "-")
    name = re.sub(r"\s+", " ", name.strip().casefold())
    for term in _SCENARIO_RESIDUAL_TERMS:
        if re.search(r"[^\x00-\x7f]", term):
            if term in name:
                return True
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", name):
            return True
    return False


def _ensure_residual_critique_scenario(
    scenarios: Any,
    forecast: Dict[str, Any],
) -> tuple[Optional[List[Dict[str, Any]]], bool]:
    """Materialize the critic's unallocated mass as an explicit residual bin.

    The publication contract requires a status-quo/other scenario, but an LLM
    critic can lower every named probability without emitting the implied
    remainder.  Normalizing that partial allocation immediately erases the
    critic's uncertainty and makes its probability-bearing notes stale.  This
    helper runs *before* normalization:

    * preserve ``1 - sum(named probabilities)`` when the critic left real mass;
    * otherwise reserve a small bounded residual and scale named rows together;
    * never repair malformed/non-finite probabilities (the contract audit must
      still expose those failures).

    Returns a copied list plus whether a deterministic residual was inserted.
    """
    if not isinstance(scenarios, list) or not scenarios:
        return None, False
    if any(not isinstance(row, dict) for row in scenarios):
        return None, False
    rows = [dict(row) for row in scenarios]

    probabilities: List[float] = []
    for row in rows:
        raw_probability = row.get("probability")
        if type(raw_probability) not in (int, float):
            return None, False
        probability = float(raw_probability)
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            return None, False
        probabilities.append(probability)
    total = sum(probabilities)
    if total <= 0.0:
        return None, False
    if total > 1.0 + _SCENARIO_SUM_TOLERANCE:
        return None, False
    if any(_is_residual_scenario_name(row.get("name")) for row in rows):
        return rows, False

    configured_floor = _coerce_float(_cfg("FORECAST_PROB_FLOOR", 0.03)) or 0.03
    residual_floor = min(0.20, max(0.03, configured_floor))
    unallocated = max(0.0, 1.0 - total)
    residual_probability = (
        unallocated
        if unallocated >= max(_SCENARIO_SUM_TOLERANCE, residual_floor)
        else residual_floor
    )
    residual_probability = min(0.95, residual_probability)
    named_target = 1.0 - residual_probability
    scale = named_target / total
    for row, probability in zip(rows, probabilities, strict=True):
        row["probability"] = probability * scale

    text_probe = " ".join(
        [str(forecast.get("headline") or "")]
        + [str(row.get("name") or "") for row in rows]
    )
    is_cjk = bool(re.search(r"[\u4e00-\u9fff]", text_probe))
    horizon = str(forecast.get("horizon") or "").strip()
    if is_cjk:
        residual = {
            "name": "其它 / 维持现状",
            "probability": residual_probability,
            "summary": "已命名情景均未完整发生，结果呈现混合、延迟或接近既有轨迹的剩余路径。",
            "key_drivers": ["政策与技术结果混合或延迟", "未满足任何已命名情景的完整判定标准"],
            "resolution_criteria": (
                f"截至{horizon or '预测期末'}，若所有已命名情景的完整判定标准均未满足，"
                "或结果仍为混合/维持现状路径，则归入本剩余情景。"
            ),
            "base_rate_anchor": "红队重新分配后剩余的未分配概率质量。",
            "adjustment_rationale": "以 1 减去已命名情景概率之和，确定性保留剩余情景。",
            "critique_note": "为保证情景集合互斥且穷尽，显式补入剩余/维持现状情景。",
        }
    else:
        residual = {
            "name": "Other / Status Quo",
            "probability": residual_probability,
            "summary": (
                "None of the named scenarios resolves in full; outcomes remain mixed, "
                "delayed, or close to the prior trajectory."
            ),
            "key_drivers": [
                "Mixed or delayed policy and technology outcomes",
                "Failure to satisfy any named scenario's complete resolution contract",
            ],
            "resolution_criteria": (
                f"At {horizon or 'the forecast horizon'}, classify this residual bin if none "
                "of the named scenarios' complete resolution criteria are met, or if the "
                "outcome remains a mixed/status-quo path."
            ),
            "base_rate_anchor": "Unallocated probability mass after red-team reassignment.",
            "adjustment_rationale": (
                "Deterministically preserves one minus the sum of the named scenario "
                "probabilities as the residual path."
            ),
            "critique_note": (
                "Added explicitly so the scenario partition remains mutually exclusive and "
                "collectively exhaustive."
            ),
        }
    rows.append(residual)
    return rows, True


_LEADING_RANGE_TIME_RE = re.compile(
    r"^\s*(?:(?:by|in|at|through|as\s+of|before|until)\s+"
    r"(?:FY\s*|CY\s*)?20\d{2}(?:\s*Q[1-4])?"
    r"|(?:到|截至|在)\s*20\d{2}年(?:底|末)?)\s*[,，;；:-]\s*",
    re.I,
)
_ALLOWED_RANGE_TRAILING_RE = re.compile(
    r"^\s*(?:(?:by|in|at|through|as\s+of|before|until|during)\s+"
    r"(?:FY\s*|CY\s*)?20\d{2}(?:\s*Q[1-4])?"
    r"|(?:到|截至|在)\s*20\d{2}年(?:底|末)?)\s*[,，。]?\s*$",
    re.I,
)
_RANGE_TIME_TOKEN_RE = re.compile(
    r"(?:FY\s*|CY\s*)?20\d{2}(?:\s*Q[1-4])?|20\d{2}年(?:底|末)?",
    re.I,
)


def _range_time_scope(value: str) -> Optional[str]:
    tokens = {
        re.sub(r"\s+", "", match.group(0)).casefold()
        for match in _RANGE_TIME_TOKEN_RE.finditer(value)
    }
    return "|".join(sorted(tokens)) if tokens else None


def _supported_range_trailing(value: str) -> bool:
    return not value.strip() or bool(_ALLOWED_RANGE_TRAILING_RE.fullmatch(value))


def _range_value(match: "re.Match[str]", prefix: str) -> Optional[tuple[float, str]]:
    try:
        number = float(match.group(f"{prefix}_number").replace(",", "").replace("−", "-"))
    except (AttributeError, TypeError, ValueError):
        return None
    currency = str(match.group(f"{prefix}_currency") or "").lower()
    unit = str(match.group(f"{prefix}_unit") or "").lower()
    normalized_unit = currency + unit
    return (number, normalized_unit) if normalized_unit else None


def _extract_comparable_numeric_range(criteria: Any) -> Optional[Dict[str, Any]]:
    """Extract one explicit metric interval; ambiguous compound criteria are skipped."""
    text = str(criteria or "").replace("–", "-").replace("—", "-")
    clauses = [
        clause.strip()
        for clause in re.split(r"(?<!\d)[.;](?!\d)|\n+", text)
        if clause.strip()
    ]
    candidates: List[Dict[str, Any]] = []
    for clause in clauses:
        # OR criteria are not a single comparable interval.  Do not infer which
        # branch owns the scenario.
        if re.search(r"\b(?:or|either)\b|(?:或者|或)", clause, re.I):
            continue
        match_clause = _LEADING_RANGE_TIME_RE.sub("", clause)
        scope = _range_time_scope(clause)
        for pattern, kind in (
            (_BETWEEN_RANGE_RE, "interval"),
            (_COLON_RANGE_RE, "interval"),
            (_CHINESE_RANGE_RE, "interval"),
            (_COMPARATOR_RANGE_RE, "comparator"),
            (_CHINESE_COMPARATOR_RANGE_RE, "comparator"),
        ):
            match = pattern.search(match_clause)
            if not match:
                continue
            metric = _normalise_metric_label(match.group("metric"))
            if not metric:
                break
            trailing = match_clause[match.end():]
            if not _supported_range_trailing(trailing):
                break
            if re.search(r"\b(?:and|or)\b\s+\S+\s*(?:>=|<=|>|<)|(?:以及|并且|或)",
                         trailing, re.I):
                break
            if kind == "interval":
                low = _range_value(match, "lo")
                high = _range_value(match, "hi")
                if not low or not high or low[1] != high[1] or low[0] > high[0]:
                    break
                candidates.append({
                    "metric": metric,
                    "unit": low[1],
                    "low": low[0],
                    "high": high[0],
                    "scope": scope,
                })
            else:
                bound = _range_value(match, "bound")
                if not bound:
                    break
                operator = re.sub(r"\s+", " ", match.group("operator").lower())
                lower_ops = {
                    ">", ">=", "at least", "more than", "above", "exceed",
                    "exceeds", "高于", "超过", "不低于", "至少",
                }
                upper_ops = {
                    "<", "<=", "at most", "less than", "below", "under",
                    "低于", "少于", "不超过", "至多",
                }
                if operator in lower_ops:
                    low, high = bound[0], math.inf
                elif operator in upper_ops:
                    low, high = -math.inf, bound[0]
                else:
                    break
                candidates.append({
                    "metric": metric,
                    "unit": bound[1],
                    "low": low,
                    "high": high,
                    "scope": scope,
                })
            break
    return candidates[0] if len(candidates) == 1 else None


def _critique_probability_targets(note: Any) -> List[float]:
    text = str(note or "")
    targets: List[float] = []
    seen: set[tuple[int, int]] = set()
    for pattern in _CRITIQUE_TARGET_PATTERNS:
        for match in pattern.finditer(text):
            span = match.span("value")
            if span in seen:
                continue
            historical_prefix = text[max(0, match.start() - 32):match.start()]
            if re.search(
                r"(?:\b(?:base|prior|previous|old|initial|starting|reference)\s+"
                r"|(?:基准|先前|原始|初始|历史|之前)\s*)$",
                historical_prefix,
                re.I,
            ):
                continue
            seen.add(span)
            try:
                raw = float(match.group("value"))
            except (TypeError, ValueError):
                continue
            target = raw / 100.0 if match.group("percent") or raw > 1.0 else raw
            if 0.0 <= target <= 1.0:
                targets.append(target)
    return targets


def _synchronize_scenario_probability_narratives(
    scenarios: List[Dict[str, Any]],
) -> None:
    """Keep probability-bearing critique prose aligned after deterministic moves.

    Residual insertion, humility clamping, or the pre-mortem can legitimately
    rebalance probabilities after the critic writes its notes.  Preserve the
    original qualitative explanation in a detail field, but replace a stale
    numeric claim with an explicit final-calibration note.  This mutates only
    rows whose prose contains a parsed target that contradicts the final value.
    """
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            continue
        probability = _coerce_float(scenario.get("probability"))
        if probability is None:
            continue
        for field in ("critique_note", "adjustment_rationale"):
            narrative = str(scenario.get(field) or "").strip()
            if not narrative:
                continue
            targets = _critique_probability_targets(narrative)
            if not any(
                abs(target - probability) > _SCENARIO_VALUE_TOLERANCE
                for target in targets
            ):
                continue
            detail_field = f"{field}_detail"
            scenario.setdefault(detail_field, narrative)
            if field == "critique_note":
                scenario[field] = (
                    f"Final calibrated probability is {probability:.1%} after explicit "
                    "residual-bin normalization and bounded uncertainty rebalancing; the "
                    f"original qualitative review is preserved in {detail_field}."
                )
            else:
                scenario[field] = (
                    f"Final calibrated probability is {probability:.1%} after preserving an "
                    "explicit residual/status-quo bin; the original anchor-and-adjust "
                    f"reasoning is preserved in {detail_field}."
                )


def _bad_percentage_allocations(text: Any) -> List[Dict[str, Any]]:
    value = str(text or "")
    findings: List[Dict[str, Any]] = []
    invalid_total_spans: List[tuple[int, int]] = []
    for pattern in _EXPLICIT_TOTAL_PERCENT_PATTERNS:
        for match in pattern.finditer(value):
            total = float(match.group("total"))
            if abs(total - 100.0) > 0.5:
                findings.append({
                    "kind": "stated_total",
                    "total": total,
                    "excerpt": match.group(0)[:180],
                })
                invalid_total_spans.append(match.span())
    for match in _PERCENT_ADDITION_RE.finditer(value):
        if any(start <= match.start() and match.end() <= end
               for start, end in invalid_total_spans):
            continue
        left = 0
        right = len(value)
        for boundary in re.finditer(r"(?<!\d)[.!?](?!\d)|[。！？;；\n]", value):
            if boundary.end() <= match.start():
                left = boundary.end()
            elif boundary.start() >= match.end():
                right = boundary.start()
                break
        context = value[left:right]
        if not _ALLOCATION_CONTEXT_RE.search(context):
            continue
        parts = [
            float(number)
            for number in re.findall(r"(\d+(?:\.\d+)?)\s*%", match.group("expression"))
        ]
        computed = sum(parts)
        stated = float(match.group("stated")) if match.group("stated") else None
        if stated is not None and abs(stated - computed) > 0.5:
            findings.append({
                "kind": "arithmetic_mismatch",
                "computed": computed,
                "stated": stated,
                "excerpt": match.group(0)[:180],
            })
        elif abs((stated if stated is not None else computed) - 100.0) > 0.5:
            findings.append({
                "kind": "allocation_total",
                "total": stated if stated is not None else computed,
                "excerpt": match.group(0)[:180],
            })
    return findings


def _json_safe_audit_value(value: Any) -> Any:
    """Recursively normalize diagnostics so strict JSON can always persist them."""
    if type(value) is float and not math.isfinite(value):
        if math.isnan(value):
            return "nan"
        return "infinity" if value > 0 else "-infinity"
    if isinstance(value, dict):
        return {
            str(key): _json_safe_audit_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_audit_value(item) for item in value]
    return value


def _json_safe_range_endpoint(value: float) -> Optional[float]:
    return value if math.isfinite(value) else None


def audit_scenario_contract(forecast: Dict[str, Any]) -> Dict[str, Any]:
    """Fail-closed structural audit for a mutually-exclusive scenario contract.

    Range overlap is deliberately narrow: it is reported only when two criteria
    expose one parseable numeric interval for the exact same normalized metric and
    unit.  Free-text semantic similarity is never used.
    """
    issues: List[str] = []
    examples: List[Dict[str, Any]] = []

    def add(code: str, message: str, **context: Any) -> None:
        issues.append(message)
        if len(examples) < 24:
            examples.append(_json_safe_audit_value({
                "code": code, "message": message, **context,
            }))

    if not isinstance(forecast, dict):
        add("forecast_not_object", "forecast must be an object")
        return {
            "valid": False,
            "issue_count": len(issues),
            "issues": issues,
            "examples": examples,
        }
    if "scenarios" not in forecast:
        return {"valid": True, "issue_count": 0, "issues": [], "examples": []}
    scenarios = forecast.get("scenarios")
    if not isinstance(scenarios, list):
        add("scenarios_not_list", "scenarios must be a list when present")
    elif not scenarios:
        add("scenarios_empty", "scenarios must not be empty when present")
    elif not 2 <= len(scenarios) <= 5:
        add(
            "scenario_count",
            f"scenario partition must contain 2-5 rows, found {len(scenarios)}",
            count=len(scenarios),
        )
    if not isinstance(scenarios, list) or not scenarios:
        return {
            "valid": False,
            "issue_count": len(issues),
            "issues": issues,
            "examples": examples,
        }

    seen_names: Dict[str, int] = {}
    valid_probabilities: List[float] = []
    all_probabilities_valid = True
    parsed_ranges: List[Dict[str, Any]] = []
    text_fields: List[tuple[str, str]] = []
    residual_present = False

    for index, scenario in enumerate(scenarios):
        label = f"scenario[{index}]"
        if not isinstance(scenario, dict):
            add("scenario_not_object", f"{label} must be an object", index=index)
            all_probabilities_valid = False
            continue
        name = str(scenario.get("name") or "").strip()
        if not name:
            add("scenario_name_missing", f"{label} has no non-empty name", index=index)
        else:
            normalized_name = re.sub(r"\s+", " ", name).casefold()
            if normalized_name in seen_names:
                add(
                    "duplicate_scenario_name",
                    f"scenario name '{name}' is duplicated",
                    scenario=name,
                    first_index=seen_names[normalized_name],
                    index=index,
                )
            else:
                seen_names[normalized_name] = index
            residual_present = residual_present or _is_residual_scenario_name(
                normalized_name
            )

        probability = scenario.get("probability")
        numeric_probability: Optional[float] = None
        if (type(probability) not in (int, float)
                or (type(probability) is float and not math.isfinite(probability))):
            add(
                "probability_not_numeric",
                f"{label} probability must be a finite JSON number",
                scenario=name,
                value=_json_safe_audit_value(probability),
            )
            all_probabilities_valid = False
        elif not 0 <= probability <= 1:
            add(
                "probability_out_of_range",
                f"{label} probability is outside [0, 1]",
                scenario=name,
                value=_json_safe_audit_value(probability),
            )
            all_probabilities_valid = False
        else:
            numeric_probability = float(probability)
            valid_probabilities.append(numeric_probability)

        criteria = scenario.get("resolution_criteria")
        if not isinstance(criteria, str) or not criteria.strip():
            add(
                "resolution_criteria_missing",
                f"{label} has no non-empty resolution criteria",
                scenario=name,
            )
        else:
            parsed_range = _extract_comparable_numeric_range(criteria)
            if parsed_range:
                parsed_ranges.append({
                    **parsed_range,
                    "scenario": name or label,
                    "index": index,
                })

        critique_note = scenario.get("critique_note")
        if critique_note not in (None, "") and numeric_probability is not None:
            current = numeric_probability
            for target in _critique_probability_targets(critique_note):
                if abs(target - current) > _SCENARIO_VALUE_TOLERANCE:
                    add(
                        "stale_critique_probability",
                        f"{label} critique probability {target:.4f} contradicts current "
                        f"probability {current:.4f}",
                        scenario=name,
                        current_probability=current,
                        critique_probability=target,
                        excerpt=str(critique_note)[:180],
                    )

        for field in ("summary", "resolution_criteria", "critique_note"):
            field_value = scenario.get(field)
            if isinstance(field_value, str) and field_value.strip():
                text_fields.append((f"{label}.{field}", field_value))

    if all_probabilities_valid and len(valid_probabilities) == len(scenarios):
        probability_sum = sum(valid_probabilities)
        if not math.isclose(
            probability_sum,
            1.0,
            rel_tol=0.0,
            abs_tol=_SCENARIO_SUM_TOLERANCE + 1e-12,
        ):
            add(
                "probability_sum",
                f"scenario probabilities sum to {probability_sum:.4f}, outside "
                f"1±{_SCENARIO_SUM_TOLERANCE:.3f}",
                probability_sum=round(probability_sum, 6),
            )

    if not residual_present:
        add(
            "residual_scenario_missing",
            "scenario partition has no residual/status-quo/other bin",
        )

    for left_index, left in enumerate(parsed_ranges):
        for right in parsed_ranges[left_index + 1:]:
            if (left["metric"] != right["metric"]
                    or left["unit"] != right["unit"]
                    or left.get("scope") != right.get("scope")):
                continue
            overlap_low = max(left["low"], right["low"])
            overlap_high = min(left["high"], right["high"])
            # Touching endpoints are not enough: inclusive/exclusive language is
            # often omitted, so require a positive-width intersection.
            if overlap_low < overlap_high:
                add(
                    "overlapping_numeric_ranges",
                    f"scenarios '{left['scenario']}' and '{right['scenario']}' overlap "
                    f"on metric '{left['metric']}'",
                    metric=left["metric"],
                    unit=left["unit"],
                    scope=left.get("scope"),
                    scenarios=[left["scenario"], right["scenario"]],
                    overlap=[
                        _json_safe_range_endpoint(overlap_low),
                        _json_safe_range_endpoint(overlap_high),
                    ],
                )

    for field in ("headline", "confidence_rationale"):
        value = forecast.get(field)
        if isinstance(value, str) and value.strip():
            text_fields.append((field, value))
    seen_text: set[str] = set()
    for field, text in text_fields:
        if text in seen_text:
            continue
        seen_text.add(text)
        for finding in _bad_percentage_allocations(text):
            add(
                "percentage_allocation_arithmetic",
                f"{field} contains an explicit percentage allocation that does not "
                "resolve to 100%",
                field=field,
                **finding,
            )

    return {
        "valid": not issues,
        "issue_count": len(issues),
        "issues": issues,
        "examples": examples,
    }


# ---------------------------------------------------------- resolution sharpness
# A "sharp" resolution criterion must pin down WHAT (a metric/threshold), HOW MUCH
# (a number) and WHEN (a date/trigger) so the forecast is later trackable & scorable
# — the difference between "利率可能上升" and "若 X 于 Z 日前超过 Y% 则确认".
_RC_DATE_RE = re.compile(
    r"20\d{2}|FY\s*\d{2,4}|CY\s*\d{2,4}|Q[1-4]|H[12]|[年月日季]|"
    r"\b\d{1,2}/\d{1,2}\b|前|底|内|by\s|until|before|deadline|"
    r"election day|fiscal year|calendar year",
    re.I)
_RC_METRIC_RE = re.compile(
    r"[<>＜＞≥≤%+$]|份额|份額|占比|增速|增长|价格|股价|指数|数量|规模|阈值|"
    r"超过|低于|达到|不低于|不超过|至少|以上|以下|"
    r"\b(?:share|rate|revenue|capex|demand|consumption|shipments?|wafers?|"
    r"price|index|total|sum|count|tally|average|percentage points?|seats?|"
    r"majority|composition|wins?|elects?|call(?:ed)?|certif(?:y|ies|ied)|"
    r"filing|registration statement|ruling|opinion|upholds?|vacat(?:e|ing)|"
    r"invalidat(?:e|ion)|regulation|decree|guidance|screening|export controls?|"
    r"disclos(?:e|ure)|threshold|between|more than|less than|at least)\b",
    re.I)


def validate_resolution_criteria(text: Any) -> Dict[str, bool]:
    """Heuristic check that a resolution criterion is sharp (number + date + metric).

    Pure / offline. ``sharp`` is True only when all three signals are present so a
    later auditor can objectively decide whether the scenario occurred. Used to
    populate ``quality.vague_criteria`` (R2-CAL-7). Degrade-safe: never raises.
    """
    t = str(text or "")
    has_number = bool(re.search(r"\d", t))
    has_date = bool(_RC_DATE_RE.search(t))
    has_metric = bool(_RC_METRIC_RE.search(t))
    return {
        "sharp": bool(has_number and has_date and has_metric),
        "has_number": has_number,
        "has_date": has_date,
        "has_metric": has_metric,
    }


def _quality_from_scenarios(scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute degrade-safe quality flags from a scenario list (gated by flags).

    Returns only the keys whose gating flag is on; an empty dict otherwise so the
    default path adds no ``quality`` block at all (schema unchanged when unflagged).
    """
    q: Dict[str, Any] = {}
    if _cfg("REPORT_REQUIRE_SHARP_CRITERIA", False):
        # R2-CAL-7：标记判定标准过于模糊（缺数字/日期/指标之一）的情景。
        vague = [s.get("name") for s in scenarios
                 if not validate_resolution_criteria(s.get("resolution_criteria")).get("sharp")]
        q["vague_criteria"] = [str(n) for n in vague if n]
    if _cfg("REPORT_REQUIRE_ANCHOR", False):
        # R2-CAL-12：标记缺少 base_rate_anchor / adjustment_rationale 的情景（anchor-and-adjust 不可审计），
        # 以及锚点→最终概率出现"无理由大跳"（>0.35）的情景。
        missing = []
        unjustified = []
        for s in scenarios:
            anchor = str(s.get("base_rate_anchor") or "").strip()
            rationale = str(s.get("adjustment_rationale") or "").strip()
            if not (anchor and rationale):
                missing.append(s.get("name"))
            a = _anchor_to_prob(anchor)
            p = _coerce_float(s.get("probability"))
            if a is not None and p is not None and not rationale and abs(p - a) > 0.35:
                unjustified.append(s.get("name"))
        q["missing_anchor"] = [str(n) for n in missing if n]
        if unjustified:
            q["unjustified_anchor_jump"] = [str(n) for n in unjustified if n]
    return q


def _anchor_to_prob(anchor: str) -> Optional[float]:
    """Pull a leading base-rate percentage/fraction out of a free-text anchor, if any."""
    if not anchor:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", anchor)
    if m:
        return max(0.0, min(1.0, float(m.group(1)) / 100.0))
    m = re.search(r"0?\.\d+", anchor)
    if m:
        try:
            return max(0.0, min(1.0, float(m.group(0))))
        except ValueError:
            return None
    return None


def slice_head_tail(text: str, budget: int, head_ratio: float = 0.6) -> str:
    """RQ-2：在同一字符预算内取「前 head_ratio + 后 (1-head_ratio)」两段拼接。

    成稿后抽取此前只取正文开头 [:budget]，但预测报告的收敛判断（"综上/因此/展望/
    结论"）几乎总在文末——head-only 截断恰好把最关键的结论切掉。本函数取前段（导言/
    框架）与尾段（结论/情景概率）各一半预算并以省略标记拼接，让抽取同时看到问题设定与
    最终判断。Pure / offline：budget 覆盖全文或非正 → 原样返回（degrade-safe）。
    """
    t = text or ""
    try:
        budget = int(budget)
    except (TypeError, ValueError):
        return t
    if budget <= 0 or len(t) <= budget:
        return t
    try:
        hr = float(head_ratio)
    except (TypeError, ValueError):
        hr = 0.6
    hr = min(0.95, max(0.05, hr))
    head_n = int(budget * hr)
    tail_n = budget - head_n
    if head_n <= 0 or tail_n <= 0:
        return t[:budget]
    return t[:head_n] + "\n…(中段略)…\n" + t[-tail_n:]


def extract_structured_forecast(report_markdown: str, llm,
                                situation_brief: Optional[str] = None,
                                language: str = "",
                                data_pack: str = "") -> Dict[str, Any]:
    """Run one LLM pass to produce a validated structured forecast object.

    ``llm`` must expose ``chat_json(messages, temperature, max_tokens)``. Returns a
    dict with normalized scenarios; raises nothing on a malformed model reply
    beyond what chat_json raises (caller wraps in try/except and degrades).

    RQ-2：成稿后切片改为 head+tail（结论在文末，不能只取开头）；抽取 max_tokens 2048→4096
    （5 情景 × anchor/rationale/criteria 常被 2048 截断成断裂 JSON）。默认值即新行为。
    """
    content = report_markdown or ""
    budget = int(_cfg("FORECAST_EXTRACT_BUDGET", 40000))
    head_ratio = _coerce_float(_cfg("FORECAST_EXTRACT_HEAD_RATIO", 0.6))
    if head_ratio is None:
        head_ratio = 0.6
    content = slice_head_tail(content, budget, head_ratio)
    user = _FORECAST_INSTRUCTIONS
    if situation_brief:
        user += f"\n\n[态势简报]\n{situation_brief[:2000]}"
    user += f"\n\n[预测报告]\n{content}"
    user += _official_context_suffix(data_pack)
    user += forecast_language_rule(language)
    raw = llm.chat_json(
        messages=[{"role": "user", "content": user}],
        temperature=0.2,
        max_tokens=int(_cfg("FORECAST_EXTRACT_MAX_TOKENS", 4096)),
    )
    if not isinstance(raw, dict):
        raw = {}
    return _assemble_forecast(raw)


# Prompt room for the report's stored-data pack (report_agent builds it within this budget).
OFFICIAL_PACK_PROMPT_CAP = 5000
# The judging stages (critique, pre-mortem, fallback extraction) get the pack followed by
# the outside view (official_outside_view_block, at most 3600 characters by default).
OFFICIAL_JUDGING_PROMPT_CAP = OFFICIAL_PACK_PROMPT_CAP + 4000


def _official_context_suffix(data_pack: Any) -> str:
    """Fixed suffix with the stored official-data pack ("" when absent: prompt unchanged)."""
    text = str(data_pack or "").strip()
    if not text:
        return ""
    return ("\n\n[官方统计数据（已存储的观测值，数值以此为准；外部视角/基率须与之核对）]\n"
            + _cap_at_line(text, OFFICIAL_JUDGING_PROMPT_CAP))


def _assemble_forecast(raw: Dict[str, Any], *, keep_metric_range: bool = False) -> Dict[str, Any]:
    """Normalize a raw model JSON into the canonical structured-forecast dict.

    Shared by ``extract_structured_forecast`` (post-hoc, from prose) and
    ``derive_forecast_spine`` (NEXTSTEPS P0-1, from signals) so both emit an
    identical shape regardless of where the probabilities came from.
    ``keep_metric_range`` keeps a raw per-scenario ``metric_range`` for the
    caller to validate against the official-data carrier.
    """
    scenarios = _normalize_scenarios(raw.get("scenarios"), keep_metric_range=keep_metric_range)
    confidence = str(raw.get("confidence") or "medium").lower()
    if confidence not in ("low", "medium", "high"):
        confidence = "medium"
    out = {
        "headline": str(raw.get("headline") or ""),
        "horizon": str(raw.get("horizon") or ""),
        "scenarios": scenarios,
        "key_uncertainties": [str(x) for x in (raw.get("key_uncertainties") or []) if x],
        "confidence": confidence,
        "confidence_rationale": str(raw.get("confidence_rationale") or ""),
        "schema_version": 1,
    }
    # R2-CAL-7 / R2-CAL-12：仅当相应旗标开启时附加 quality 诊断块（默认不加 → schema 不变）。
    quality = _quality_from_scenarios(scenarios)
    if quality:
        out["quality"] = quality
    return out


# ----------------------------------------------------- binary forecasts (QUALITY-OPT A1)
# Many briefs (e.g. Bridgewater) demand the headline deliverable as a SET OF INDEPENDENT
# BINARY yes/no forecasts — one sentence, a probability, and an OBJECTIVE resolution test —
# NOT a set of mutually-exclusive scenarios that sum to 1. The research stage already tends
# to produce these (e.g. an F1..Fn table); the scenario-only finalizer discarded them. This
# pathway extracts/derives >=min_count independent binaries and keeps them ALONGSIDE the
# scenario spine, so both the calibratable scenario view and the brief's contract survive.
_BINARY_FORECAST_INSTRUCTIONS = (
    "You are a forecasting-calibration expert assembling the HEADLINE deliverable: a set of "
    "INDEPENDENT BINARY (yes/no) forecasts. From the research dossier below, FIRST extract "
    "every binary forecast the analyst already stated (preserve their probabilities and "
    "resolution criteria verbatim where given); THEN, if fewer than {min_count}, derive "
    "additional ones from the dossier's drivers, indicators, and quantitative facts. Never "
    "invent facts the dossier does not support.\n\n"
    "Output JSON ONLY: {{\"binary_forecasts\": [ {{...}}, ... ]}}. Each object:\n"
    "{{\n"
    '  "id": "F1",\n'
    '  "statement": "ONE declarative sentence that resolves strictly yes/no, with the number and date INSIDE it (model: \\"The US effective tariff rate on imports averages over 10% from 2026-2028\\").",\n'
    '  "probability": 0.02-0.98,        // INDEPENDENT per forecast — do NOT make these sum to 1\n'
    '  "resolution_criteria": "Objective settle test: a named METRIC + a NUMERIC threshold + a DATE/window + the SOURCE that resolves it.",\n'
    '  "resolution_source": "the dataset/agency/publication that will settle it",\n'
    '  "theme": "{theme_enum}",\n'
    '  "horizon_year": {horizon_year_hint},            // {horizon_year_rule}\n'
    '  "base_rate_anchor": "reference-class base rate / outside view",\n'
    '  "adjustment_rationale": "why this case differs from the base rate (anchor-and-adjust)",\n'
    '  "source": "provenance of the probability: name the simulation signal that moved it (e.g. \\"world-state outcome shares\\", \\"coalition map\\") or \\"research-prior\\" when only research evidence informs it"\n'
    "}}\n\n"
    "Each object MUST also include proposition_id (a stable kebab-case identifier for the exact "
    "resolvable event) and a scenario_membership object with a derivable boolean and a "
    "yes_scenarios list. Set derivable=true ONLY when the canonical mutually-exclusive "
    "scenario partition fully determines the binary, and then copy every YES scenario name exactly. "
    "Otherwise set derivable=false with an empty yes_scenarios list.\n\n"
    "RULES: produce AT LEAST {min_count} DISTINCT forecasts. Every statement is ONE sentence, "
    "falsifiable, and {tie_rule}. Probabilities "
    "express genuine CONVICTION — do not cluster in 0.40-0.60; commit where the evidence "
    "warrants. Each resolution_criteria MUST contain a metric, a number, and a date. Write all "
    "text in {language}."
)

# RPT-6：主题不再硬编码为 Bridgewater 三元组；未显式给 themes 时用主题无关措辞 + 自由主题串。
_BINARY_DEFAULT_THEME_ENUM = "one short lowercase tag naming the driving force this forecast belongs to"
_BINARY_DEFAULT_TIE_RULE = "tied to the report's central question and its key driving forces"

# RPT-4（FORECAST_BINARY_CONTRARIAN，默认开）：单向框架会让全部概率挤在 0.5 以上、
# stdev 永远过不了 0.12 门；要求近半数陈述以「证据支持概率 < 0.5」的反共识方向直接表述。
_BINARY_CONTRARIAN_RULE = (
    "\nCONTRARIAN FRAMING: frame roughly 40-50% of the statements so that the "
    "evidence-supported probability is BELOW 0.5 — assert the counter-consensus outcome "
    "directly (e.g. \"X exceeds Y by Z date\" priced at 0.25). Do NOT achieve this by "
    "negating another statement in the set."
)

# RPT-4：首轮全部 >0.5 / spread 过低时的一次有界重述补足（仅低概率陈述）。
_BINARY_LOW_P_RULE = (
    "\nIMPORTANT: EVERY new statement must carry an evidence-supported probability in the "
    "0.05-0.35 range — assert specific, falsifiable counter-consensus outcomes directly "
    "(not negations of earlier statements)."
)

# 预测市场校准锚点（Polymarket 公开 Gamma API）：与所列市场重叠的预测须引用市场
# 隐含概率，偏离 >10 个百分点须显式解释分歧；市场是校准锚点，不是真值。命中时模型给出
# market_anchor 字段，_normalize_binaries 用我们自己的市场数据回填/校验隐含概率并计算
# divergence（不盲信模型转录的数字）。
_BINARY_MARKET_RULE = (
    "\nMARKET CALIBRATION: real prediction-market implied probabilities "
    "(Polymarket) are listed below. Where a forecast overlaps a listed "
    "market, CITE that market's implied probability in adjustment_rationale, and when your "
    "probability diverges from it by MORE than 10 percentage points, EXPLAIN the divergence "
    "explicitly (what the market is missing or mispricing). Markets are calibration anchors, "
    "NOT ground truth — do not blindly copy them. For each such overlapping forecast add an "
    "extra field \"market_anchor\": {\"market_id\": \"<id from the table>\", "
    "\"implied_yes_prob\": 0.0-1.0}; OMIT market_anchor entirely when no listed market applies."
)

# ------------------------------------------------- source 溯源确定性校验（编造溯源修复）
# 取证（report_9147b3f6a0a9 6/12、report_c83f21765b96 9/20、report_1b70ace5c9e8 8/13）：模型把
# source 标成 "world-state outcome shares"，而 41 次模拟中 world_state_trajectory.json 从未存在
# ——该信号从未进过提示词，属**编造溯源**。修复：从实际注入提示词的 signal_pack 切片（与提示词
# 逐字节同源）确定性推导「允许的信号标签集」，抽取后把不能对账到该集合的 source 降级为
# 'research-prior'（原话保留在 source_claimed 供审计），降级条数落 binary_quality.provenance_downgrades。
# 每行 = (规范信号名, 信号包块标记——对注入切片匹配, source 标签识别——对模型自由文本匹配)；
# 块标记逐字节取自各渲染器的标题行（report_agent._world_state_block / zep_tools.coalition_map 等），
# 渲染器改头时此表须同步。
_SIM_SIGNAL_TAXONOMY: List[Tuple[str, re.Pattern, re.Pattern]] = [
    ("world-state outcome shares",
     re.compile(r"【预测结果分布\s*P\(outcome\)"),
     re.compile(r"world[\s_-]*state|outcome\s*shares?|P\(outcome\)|世界态|结果分布|结果份额", re.I)),
    ("salience tiers",
     re.compile(r"议程设置力分层"),
     re.compile(r"salience|agenda[\s_-]*setting|tier|议程设置|梯队|分层", re.I)),
    ("coalition map",
     re.compile(r"##\s*派系/联盟图"),
     re.compile(r"coalition|faction|联盟|派系", re.I)),
    ("causal spine",
     re.compile(r"【因果骨架"),
     re.compile(r"causal|chokepoint|cascade|因果|传导|支点", re.I)),
    ("scenario diff",
     re.compile(r"##\s*情景对比\s*/\s*反事实差异"),
     re.compile(r"scenario[\s_-]*diff|counterfactual|反事实|情景对比", re.I)),
    ("projected edges",
     re.compile(r"【关系演化投影"),
     re.compile(r"projected[\s_-]*edges?|relationship\s*(?:projection|trajectory)|关系演化|投影", re.I)),
    ("simulation outcomes",
     re.compile(r"##\s*模拟量化结果"),
     re.compile(r"simulation[\s_-]*outcomes?|action\s*(?:counts?|volume|types?)|top[\s_-]*actor"
                r"|模拟量化|动作(?:量|计数|类型)|最活跃", re.I)),
]

# 非模拟信号的合法 source：research-prior（缺省值）与 scenario-partition
# （reconcile_forecast_contract 的确定性改写）永远放行，不参与对账。
_SOURCE_ALWAYS_ALLOWED_RE = re.compile(
    r"research[\s_-]*prior|scenario[\s_-]*partition|研究先验|情景划分", re.I)
# 预测市场标签：market_pack 实际注入时放行（市场表是提示词里的真实信号，非编造）。
_SOURCE_MARKET_LABEL = "prediction markets"
_SOURCE_MARKET_RE = re.compile(
    r"polymarket|prediction[\s_-]*market|market[\s_-]*implied|预测市场|市场隐含", re.I)


def allowed_signal_labels(signal_pack: Optional[str]) -> set:
    """从**实际注入提示词**的 signal_pack 切片推导允许的规范信号名集合（确定性、离线）。

    只有块标记真实出现在切片里的信号才可被 source 引用；空/None → 空集（即所有模拟信号
    标签都不被允许）。调用方必须传入与提示词完全相同的截断切片，保证「允许集」与模型
    实际看到的内容逐字节对齐。
    """
    text = str(signal_pack or "")
    return {canon for canon, marker, _label in _SIM_SIGNAL_TAXONOMY if marker.search(text)}


def _enforce_source_provenance(binaries: List[Dict[str, Any]], allowed: set) -> int:
    """把不能对账到 ``allowed`` 集合的模拟信号 source 降级为 'research-prior'，返回降级条数。

    research-prior / scenario-partition 永远放行；能归类到已知信号但该信号块未注入 →
    降级；无法归类到任何已知信号（模型自造名）同样降级——溯源必须可对账到确实注入过的
    信号块。原话保留在 ``source_claimed``（审计可回放模型原始声称）。原地修改
    （与 reconcile_forecast_contract 同风格）；纯离线，绝不抛异常。
    """
    downgrades = 0
    for b in (binaries or []):
        if not isinstance(b, dict):
            continue
        src = str(b.get("source") or "").strip()
        if not src or _SOURCE_ALWAYS_ALLOWED_RE.search(src):
            continue
        if _SOURCE_MARKET_RE.search(src):
            canon: Optional[str] = _SOURCE_MARKET_LABEL
        else:
            canon = next((c for c, _marker, label in _SIM_SIGNAL_TAXONOMY
                          if label.search(src)), None)
        if canon is not None and canon in allowed:
            continue
        b["source_claimed"] = src
        b["source"] = "research-prior"
        downgrades += 1
    return downgrades


# ------------------------------------------------- SIM-ADD-3：世界态结果分布 → 显式 sim 先验
# 取证（sim_05ab2bdebbd2 等）：即便决策通道真的产出了 world_state_trajectory.json，其收敛的
# P(outcome) 份额此前只作为提示词里的一段文本影响 LLM，从不作为**可对账的显式先验**落进
# forecast.json——sim 的贡献既不可审计、也无法量化「相对研究先验移动了多少」。下列解析器从
# **实际注入提示词**的世界态块（report_agent._world_state_block 渲染，块标记逐字节同源）里
# 抽出收敛结果份额与趋稳判定，供 reconcile_forecast_contract 记成 forecast.sim_adjustment。
# 份额来自渲染文本（整数百分比），故做一次归一并标注为先验（非精确观测），degrade-safe。
_WS_OUTCOME_HEADER_RE = re.compile(r"【预测结果分布\s*P\(outcome\)")
_WS_OUTCOME_SHARE_RE = re.compile(
    r"^·\s*(?P<name>.+?)\s*[:：]\s*(?P<pct>\d{1,3}(?:\.\d+)?)\s*%\s*$")
# 世界态块内**份额行之后**的其它小节起始（碰到即停止份额收集，避免把日历航点/诊断行混入）。
_WS_OUTCOME_SECTION_BREAK = ("【", "演化航点", "稳定性诊断", "截至", "于 ", "注", "预测期限")


def world_state_outcome_from_signal_pack(
    signal_pack: Optional[str],
) -> Optional[Dict[str, Any]]:
    """从 signal_pack 的世界态结果分布块解析决策通道的收敛 P(outcome) 份额（纯离线、确定性）。

    识别 ``【预测结果分布 P(outcome)…】`` 块及其下的 ``· <情景名>: <NN>%`` 份额行，归一后
    返回 ``{"scenario_shares": {name: frac}, "converged": bool|None,
    "source": "world-state outcome shares"}``；块缺失/无份额行 → ``None``（调用方视同 sim
    无收敛结果，degrade-safe）。``converged`` 由块内「已趋稳/尚未趋稳」文案判定（无 → None）。
    """
    text = str(signal_pack or "")
    m = _WS_OUTCOME_HEADER_RE.search(text)
    if not m:
        return None
    tail = text[m.end():]
    shares: Dict[str, float] = {}
    for ln in tail.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith(_WS_OUTCOME_SECTION_BREAK):
            break  # 到达块内其它小节/下一个信号块 → 份额行收集结束
        mm = _WS_OUTCOME_SHARE_RE.match(s)
        if mm:
            try:
                shares[mm.group("name").strip()] = float(mm.group("pct")) / 100.0
            except ValueError:
                continue
    if not shares:
        return None
    total = sum(shares.values())
    if total > 0:
        shares = {k: v / total for k, v in shares.items()}  # 整数百分比未必精确求和 → 归一
    converged: Optional[bool] = None
    if "尚未趋稳" in tail:
        converged = False
    elif "趋稳" in tail:
        converged = True
    return {
        "scenario_shares": {k: round(v, 4) for k, v in shares.items()},
        "converged": converged,
        "source": "world-state outcome shares",
    }


def _norm_scenario_key(name: Any) -> str:
    """情景名归一（大小写/空白/标点无关）——用于把 sim 份额对齐到 forecast 情景先验。"""
    return re.sub(r"\s+", " ", re.sub(r"[^\w一-鿿]+", " ", str(name or "").lower())).strip()


def _record_sim_adjustment(
    forecast: Dict[str, Any], world_state_outcome: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """SIM-ADD-3：把决策通道的收敛结果份额记成 ``forecast['sim_adjustment']``（显式、可审计）。

    ``world_state_outcome`` = ``world_state_outcome_from_signal_pack`` 的输出（或等价 dict，
    含 ``scenario_shares``）。计算每个情景 sim 份额相对**研究先验**（forecast['scenarios'] 的
    probability）的位移 ``delta_vs_research_prior``，并把 ``{scenario_shares, converged,
    converged_at, delta_vs_research_prior, source}`` 写入 forecast。缺份额 → 不写、返回 None
    （trajectory 缺席时保持今日行为，绝不虚构 sim 贡献）。返回写入的 sim_adjustment 或 None。
    """
    if not isinstance(world_state_outcome, dict):
        return None
    shares = world_state_outcome.get("scenario_shares")
    if not (isinstance(shares, dict) and shares):
        return None
    # 研究先验：forecast 情景概率（sim 从不改情景表，故它即外部/研究视角先验）。
    prior: Dict[str, float] = {}
    for row in (forecast.get("scenarios") or []):
        if not isinstance(row, dict):
            continue
        p = _coerce_float(row.get("probability"))
        nm = _norm_scenario_key(row.get("name") or row.get("scenario"))
        if nm and p is not None:
            prior[nm] = p
    delta: Dict[str, float] = {}
    for name, sh in shares.items():
        sv = _coerce_float(sh)
        if sv is None:
            continue
        pv = prior.get(_norm_scenario_key(name))
        if pv is not None:
            delta[str(name)] = round(sv - pv, 4)
    adjustment: Dict[str, Any] = {
        "scenario_shares": {str(k): round(float(v), 4) for k, v in shares.items()
                            if _coerce_float(v) is not None},
        "converged": world_state_outcome.get("converged"),
        "converged_at": world_state_outcome.get("converged_at"),
        "delta_vs_research_prior": delta,
        "source": "world-state outcome shares",
    }
    forecast["sim_adjustment"] = adjustment
    return adjustment


def _binary_key(stmt: str) -> str:
    return re.sub(r"\W+", " ", str(stmt or "").lower()).strip()


_MARKET_ENTITY_EN_RE = re.compile(
    r"\b(?:polymarket|prediction[- ]market|event[- ]contract|market[- ]contract|"
    r"market[- ]implied)\b",
    re.I,
)
_MARKET_QUOTE_EN_RE = re.compile(
    r"\b(?:probabilit(?:y|ies)|prices?|odds|quotes?|(?:yes|no)\s+shares?|"
    r"cents?)\b",
    re.I,
)
_MARKET_QUOTE_MOVEMENT_EN_RE = re.compile(
    r"\b(?:"
    r"(?:will|would|shall)\s+(?:be|remain|rise|fall|increase|decrease|move|reach|"
    r"exceed|drop|trade|double|halve|settle|close|resolve)"
    r"|(?:is|are)\s+(?:expected|forecast|forecasted|projected)\s+to\s+"
    r"(?:be|remain|rise|fall|increase|decrease|move|reach|exceed|drop|trade|"
    r"double|halve|settle|close|resolve)"
    r"|(?:rise|fall|increase|decrease|move|reach|exceed|drop|trade|double|halve)s?"
    r")\b",
    re.I,
)
_MARKET_SETTLEMENT_EN_RE = re.compile(
    r"\b(?:resolve|resolves|resolved|resolving|settle|settles|settled|settling|"
    r"close|closes|closed|closing)\b",
    re.I,
)
_MARKET_CURRENT_EN_RE = re.compile(r"\b(?:currently|today|now|as\s+of)\b", re.I)
_MODEL_FORECAST_EN_RE = re.compile(
    r"\b(?:(?:our|the|this)\s+)?(?:model|forecast)(?:'s)?\b", re.I)
_MARKET_ENTITY_ZH_RE = re.compile(r"Polymarket|预测市场|市场合约|事件合约|市场隐含", re.I)
_MARKET_QUOTE_ZH_RE = re.compile(r"概率|价格|赔率|报价|(?:YES|NO|是|否)份额", re.I)
_MARKET_QUOTE_MOVEMENT_ZH_RE = re.compile(
    r"升至|涨至|降至|跌至|翻倍|减半|交易于|结算于|收于"
    r"|(?:将|预计|预期)[^。！？\n]{0,24}"
    r"(?:为|达到|超过|高于|低于|维持在|收于|交易于|结算|判定)",
    re.I,
)
_MARKET_SETTLEMENT_ZH_RE = re.compile(r"结算|判定|收盘|解决为", re.I)
_MARKET_CURRENT_ZH_RE = re.compile(r"目前|当前|现在|截至|现为", re.I)
_MODEL_FORECAST_ZH_RE = re.compile(
    r"(?:(?:我们(?:的)?|本报告(?:的)?|该)?(?:模型|预测))", re.I)
_MARKET_DEADLINE_ZH_RE = re.compile(
    r"(?:到|截至|在)?\s*(?:20\d{2}年(?:底)?|年底|年末)(?:前)?",
    re.I,
)
_MARKET_QUOTE_LEVEL_ZH_RE = re.compile(
    r"(?:概率|价格|赔率|报价)[^。！？\n]{0,24}(?:为|在)\s*"
    r"(?:\d{1,3}(?:\.\d+)?\s*%|0?\.\d+|是|否|YES|NO)",
    re.I,
)


def _has_market_scoped_movement(
        text: str, quote_pattern: re.Pattern, movement_pattern: re.Pattern,
        blocker_pattern: re.Pattern) -> bool:
    """True when movement follows a market quote, not a model comparison.

    Calibration prose commonly says "market currently 15%, while our model
    will be 30%". An order-independent token bag misclassified the model's
    movement as a forecast of the market quote. Keep the predicate local to a
    preceding quote noun and reject spans that switch subject to the model.
    """
    for quote in quote_pattern.finditer(text):
        for movement in movement_pattern.finditer(text, quote.end()):
            if movement.start() - quote.end() > 120:
                break
            if blocker_pattern.search(text[quote.end():movement.start()]):
                continue
            return True
    return False


def _market_forecast_clause_is_circular(clause: str) -> bool:
    """Classify a single market-bearing clause without substring ambiguity."""
    text = str(clause or "").strip()
    if not text:
        return False
    entity_en = _MARKET_ENTITY_EN_RE.search(text)
    if entity_en:
        current = bool(_MARKET_CURRENT_EN_RE.search(text))
        movement = _has_market_scoped_movement(
            text, _MARKET_QUOTE_EN_RE, _MARKET_QUOTE_MOVEMENT_EN_RE,
            _MODEL_FORECAST_EN_RE)
        # A contract-resolution sentence is circular unless it explicitly
        # reports an already-current quote/outcome without forecasting another
        # movement. Quote forecasts require an actual movement/level predicate;
        # an event horizon or the noun "forecast" elsewhere in the clause is
        # not enough (those are normal calibration prose).
        if _MARKET_SETTLEMENT_EN_RE.search(text):
            return not current or movement
        return bool(_MARKET_QUOTE_EN_RE.search(text)) and movement

    entity_zh = _MARKET_ENTITY_ZH_RE.search(text)
    if entity_zh:
        current = bool(_MARKET_CURRENT_ZH_RE.search(text))
        movement = _has_market_scoped_movement(
            text, _MARKET_QUOTE_ZH_RE, _MARKET_QUOTE_MOVEMENT_ZH_RE,
            _MODEL_FORECAST_ZH_RE)
        if _MARKET_SETTLEMENT_ZH_RE.search(text):
            return not current or movement
        if not _MARKET_QUOTE_ZH_RE.search(text):
            return False
        if movement:
            return True
        # Chinese often omits a future auxiliary: "到年底，...概率为60%".
        # Only treat that as a future quote when the deadline leads the market
        # phrase. A date inside the market's event question is current evidence.
        deadline = _MARKET_DEADLINE_ZH_RE.search(text)
        implicit_future_level = bool(
            deadline
            and deadline.start() < entity_zh.start()
            and _MARKET_QUOTE_LEVEL_ZH_RE.search(text)
        )
        return not current and implicit_future_level
    return False


def _is_circular_market_forecast(
        statement: Any, resolution_criteria: Any = None) -> bool:
    """True when a forecast predicts a market quote/contract, not its event."""
    for value in (statement, resolution_criteria):
        clauses = re.split(
            r"(?<!\d)[.!?](?!\d)|[。！？;；\n]+", str(value or ""))
        if any(_market_forecast_clause_is_circular(clause) for clause in clauses):
            return True
    return False


OFFICIAL_SERIES_MAX = 24
_OFFICIAL_KIND_LABELS = {
    "observed": "historical observation",
    "preliminary": "publisher preliminary",
    "estimate": "publisher estimate",
    "projection": "publisher projection",
    "unknown": "unclassified publisher value",
    "partial": "partial-period value",
}
# Rows stored before normalization policy 3 flagged every aggregated calendar month
# incomplete; their completeness is re-derived from the recorded coverage bounds.
_OFFICIAL_COMPLETENESS_POLICY = 3
_OFFICIAL_KINDS_MEMO = threading.local()


def official_series_rows(official_data: Any, max_rows: int = OFFICIAL_SERIES_MAX) -> List[Dict[str, Any]]:
    """Bound and check the persisted carrier, without fetching or filling gaps.

    This is a rendering boundary, not an alternative provider normalizer. Bad
    rows are omitted; valid normalized observations retain their exact values.
    The bound matches the carrier cap, so an anchor on any carried row validates.
    """
    from datetime import date
    from urllib.parse import urlsplit

    if (not isinstance(official_data, dict) or type(official_data.get("schema_version")) is not int
            or official_data["schema_version"] != 1):
        return []
    rows = official_data.get("series")
    if not isinstance(rows, list):
        return []
    from .official_data import data_api
    api = data_api()
    if api is None:
        return []
    result = []
    seen = set()
    for row in rows[:max(0, int(max_rows))]:
        if not isinstance(row, dict) or not isinstance(row.get("series"), str):
            continue
        identity = row["series"]
        if (identity in seen or not identity or not isinstance(row.get("units"), str)
                or not row["units"].strip() or row.get("frequency") not in ("D", "W", "M", "Q", "A")):
            continue
        try:
            parsed = api.parse_series_id(identity)
            if not parsed or ":".join(parsed) != identity:
                continue
            if row.get("transform", "") != parsed[1].partition("#")[2]:
                continue
            url = urlsplit(str(row.get("source_url") or ""))
            if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password:
                continue
            boundary = row.get("projection_from")
            if boundary and date.fromisoformat(boundary).isoformat() != boundary:
                continue
            observations = row.get("observations")
            if not isinstance(observations, list):
                continue
            points = []
            dates = set()
            for point in observations[-240:]:
                period, value = point["date"], point["value"]
                if date.fromisoformat(period).isoformat() != period or period in dates:
                    raise ValueError("noncanonical or duplicate observation period")
                if value is not None and (isinstance(value, bool) or
                        not isinstance(value, (int, float)) or not math.isfinite(value)):
                    raise ValueError("nonfinite observation")
                dates.add(period)
                points.append(dict(point))
            if not any(p["value"] is not None for p in points):
                continue
            points.sort(key=lambda p: p["date"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        seen.add(identity)
        result.append({**row, "observations": points})
    return result


def _official_legacy_periods(row: Dict[str, Any], dates: List[str]) -> Optional[Dict[str, Any]]:
    """Completeness for calendar months stored under policy < 3, which marked all incomplete.

    A month is complete when its recorded coverage spans the whole month and either
    a later month was stored or the retrieval came more than a week after month end
    (the same rule the current data layer applies at fetch time).
    """
    provenance = row.get("provenance")
    periods = provenance.get("periods") if isinstance(provenance, dict) else None
    version = provenance.get("normalization_policy_version") if isinstance(provenance, dict) else None
    if (not isinstance(periods, dict) or isinstance(version, bool)
            or isinstance(version, int) and version >= _OFFICIAL_COMPLETENESS_POLICY):
        return None
    from datetime import date, timedelta
    retrieved = str(row.get("retrieved_at") or "")[:10]
    try:
        retrieved_day = date.fromisoformat(retrieved)
    except ValueError:
        retrieved_day = None
    fixed = dict(periods)
    for period, record in periods.items():
        if (not isinstance(record, dict) or record.get("calendar") != "calendar_month"
                or record.get("complete") is not False):
            continue
        try:
            end = date.fromisoformat(str(record.get("end")))
        except ValueError:
            continue
        covered = (record.get("covered_start"), record.get("covered_end")) == (record.get("start"), record.get("end"))
        later = any(d > str(record.get("end")) for d in dates)
        settled = later or (retrieved_day is not None and retrieved_day > end + timedelta(days=7))
        if covered and settled:
            fixed[period] = {**record, "complete": True}
    return fixed


def _official_flag_kind(row: Dict[str, Any], point: Dict[str, Any]) -> str:
    """Conservative label for a row the data layer cannot revalidate: never history."""
    flag = str(point.get("flag") or "").strip().lower()
    provider = str(row.get("provider") or str(row.get("series") or "").split(":", 1)[0]).lower()
    if flag in {"projection", "projected", "forecast"}:
        return "publisher projection"
    if flag in {"e", "estimate", "estimated"}:
        return "publisher estimate"
    if flag in {"preliminary", "prelim", "provisional"} or flag == "p" and provider == "bls":
        return "publisher preliminary"
    return "unclassified publisher value"


def _official_kinds(row: Dict[str, Any], points: List[Any]) -> List[str]:
    from .official_data import data_api
    api = data_api()
    clean = [{"date": p.get("date"), "value": p.get("value"), "flag": p.get("flag") or ""}
             for p in points if isinstance(p, dict)]
    series = None
    if api is not None and len(clean) == len(points):
        try:
            candidate = {**row, "observations": clean}
            periods = _official_legacy_periods(row, [str(p["date"]) for p in clean])
            if periods is not None:
                candidate["provenance"] = {**row["provenance"], "periods": periods}
            series = api.Series.from_dict(candidate)
        except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
            series = None
    if series is None:
        return [_official_flag_kind(row, p if isinstance(p, dict) else {}) for p in points]
    by_date = {o.date: _OFFICIAL_KIND_LABELS.get(api.observation_kind(o, series), "unclassified publisher value")
               for o in series.observations}
    return [by_date.get(str(p["date"]), "unclassified publisher value") for p in clean]


def official_observation_kinds(row: Dict[str, Any]) -> List[str]:
    """Status label for each of ``row['observations']`` (same order), via the data layer.

    Labels: historical observation, publisher preliminary/estimate/projection,
    unclassified publisher value, partial-period value (an aggregated period that is
    not fully covered). Rows the data layer rejects are never labelled history.
    """
    points = row.get("observations") if isinstance(row, dict) else None
    if not isinstance(points, list):
        return []
    provenance = row.get("provenance")
    fingerprint = (row.get("series"), row.get("provider"), row.get("projection_from"), row.get("retrieved_at"),
                   row.get("frequency"), id(provenance),
                   tuple((p.get("date"), p.get("value"), p.get("flag")) if isinstance(p, dict) else None
                         for p in points))
    memo = getattr(_OFFICIAL_KINDS_MEMO, "entry", None)
    if memo is not None and memo[0] is row and memo[1] == fingerprint:
        return list(memo[2])
    kinds = _official_kinds(row, points)
    _OFFICIAL_KINDS_MEMO.entry = (row, fingerprint, tuple(kinds))
    return kinds


def official_observation_kind(row: Dict[str, Any], point: Dict[str, Any]) -> str:
    """Do not present publisher forecasts, estimates, unknown status or partial periods as actuals."""
    points = row.get("observations") if isinstance(row.get("observations"), list) else []
    for candidate, kind in zip(points, official_observation_kinds(row)):
        if candidate is point or (isinstance(candidate, dict) and candidate.get("date") == point.get("date")
                                  and candidate.get("value") == point.get("value")
                                  and (candidate.get("flag") or "") == (point.get("flag") or "")):
            return kind
    return official_observation_kinds({**row, "observations": [point]})[0]


def official_latest_observed(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Newest complete historical observation ``{date, value}`` (display-safe), else None.

    The report pack, charts, anchors and the resolution table share this helper so
    they never disagree; resolution itself still requires ``resolve_data_anchor``.
    """
    points = row.get("observations") if isinstance(row, dict) else None
    if not isinstance(points, list):
        return None
    pairs = [(p, k) for p, k in zip(points, official_observation_kinds(row))
             if k == "historical observation" and isinstance(p, dict) and p.get("value") is not None]
    if not pairs:
        return None
    point = max(pairs, key=lambda item: str(item[0].get("date")))[0]
    return {"date": point["date"], "value": point["value"]}


# IMF WEO rows stored before the vintage status policy carry no resolution flag, yet every
# fresh fetch of them is inferred-status data.
_OFFICIAL_INFERRED_STATUS_PREFIXES = ("imf:WEO/", "imf:WEO_")


def official_auto_resolvable(row: Dict[str, Any]) -> bool:
    """Whether ``resolve_data_anchor`` can ever settle an anchor on this series from a fetch.

    The data layer answers 'manual' for every period of a series it marks resolution-unsafe:
    daily data averaged or sampled to months, World Bank Data360 and USAspending fiscal
    totals (status or missingness stripped) and IMF WEO vintages (status inferred). Anchors
    on them still feed charts and watch tables; the resolution monitor need not refetch them.
    """
    from .official_data import data_api
    api = data_api()
    if not isinstance(row, dict) or api is None or str(row.get("series") or "").startswith(
            _OFFICIAL_INFERRED_STATUS_PREFIXES):
        return False
    points = row.get("observations") if isinstance(row.get("observations"), list) else []
    try:
        series = api.Series.from_dict({**row, "observations": [
            {"date": p.get("date"), "value": p.get("value"), "flag": p.get("flag") or ""}
            for p in points if isinstance(p, dict)]})
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
        return False
    return series.provenance.get("resolution_safe") is not False


def official_data_statements(official_data: Any) -> List[Tuple[Dict[str, Any], str]]:
    """Exact, narrow factual sentences for report grounding; no free-form claims."""
    rows = official_series_rows(official_data)
    if not rows:
        return []
    from .official_data import format_value
    out = []
    for row in rows:
        for point, kind in zip(row["observations"], official_observation_kinds(row)):
            if point["value"] is not None:
                out.append((row, f"{row['series']}: {format_value(point['value'], row['units'])} "
                                 f"on {point['date']} ({kind}, units: {row['units']})."))
    return out


def official_source_tag(row: Dict[str, Any], index: Dict[str, Any]) -> str:
    """Match the actual V3/legacy ledger dataset identity, including transforms."""
    from urllib.parse import parse_qsl, urlsplit

    def origin(value: Any, *, decorated: bool = False):
        try:
            parts = urlsplit(str(value or ""))
        except ValueError:
            return None
        query = parse_qsl(parts.query, keep_blank_values=True)
        decorations = [v for k, v in query if k == "drf_series"]
        if decorations:
            if not decorated or decorations != [row.get("series")]:
                return None
            query = [(k, v) for k, v in query if k != "drf_series"]
        return (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"),
                tuple(sorted(query)), parts.fragment)

    exact, generic = [], []
    for tag, source in index.items():
        if not isinstance(source, dict):
            continue
        dataset = source.get("dataset")
        dataset = dataset if isinstance(dataset, dict) else {}
        url = source.get("url") or source.get("source_url") or dataset.get("source_url")
        identity = dataset.get("series") or source.get("series") or source.get("series_id")
        if origin(url, decorated=identity == row.get("series")) != origin(row.get("source_url")):
            continue
        if dataset.get("source_url") and origin(dataset["source_url"]) != origin(row.get("source_url")):
            continue
        if identity == row.get("series"):
            exact.append(tag)
        elif not identity:
            generic.append(tag)
    matches = exact or generic
    return str(matches[0]) if len(matches) == 1 else ""


EMPIRICAL_MIN_SAMPLES = 30
_EMPIRICAL_DEFAULT_STEPS = {"M": 12, "Q": 4, "A": 1}
_EMPIRICAL_QUANTILES = (("p10", 0.10), ("p25", 0.25), ("p50", 0.50), ("p75", 0.75), ("p90", 0.90))


def _official_period_index(period: Any, frequency: str) -> Optional[int]:
    """Ordinal of a monthly/quarterly/annual period ('YYYY-MM[-DD]', 'YYYY-Qn' or 'YYYY')."""
    text = str(period or "")
    quarter = re.fullmatch(r"(\d{4})-?Q([1-4])", text, re.I)
    match = re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-\d{2})?)?", text)
    if quarter:
        year, month = int(quarter.group(1)), (int(quarter.group(2)) - 1) * 3 + 1
    elif match:
        year, month = int(match.group(1)), int(match.group(2) or 1)
    else:
        return None
    if not 1 <= month <= 12:
        return None
    return {"M": year * 12 + month - 1, "Q": year * 4 + (month - 1) // 3, "A": year}.get(frequency)


def _official_history(row: Dict[str, Any]) -> List[Tuple[int, str, float]]:
    """(period ordinal, date, value) of complete historical observations, ascending.

    Projections, estimates, preliminary and unclassified values and partial periods
    never enter an outside view.
    """
    history = {}
    for point, kind in zip(row.get("observations") or [], official_observation_kinds(row)):
        if kind != "historical observation" or point.get("value") is None:
            continue
        index = _official_period_index(point.get("date"), str(row.get("frequency") or ""))
        if index is not None:
            history[index] = (index, str(point["date"]), float(point["value"]))
    return [history[i] for i in sorted(history)]


def _empirical_quantile(ordered: List[float], q: float) -> float:
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _empirical_changes(history: List[Tuple[int, str, float]], steps: int,
                       month: Optional[int] = None) -> List[float]:
    """h-step changes of ``history``; with ``month`` (0-11) only from starts in that calendar month."""
    values = {index: value for index, _date, value in history}
    return [values[index + steps] - value for index, _date, value in history
            if index + steps in values and (month is None or index % 12 == month)]


# How an h-step sample of a monthly series published without seasonal adjustment treats its
# seasonal swing (see _empirical_season): (EN, ZH) wording for tables and briefs, and a short
# form for the length-capped outside view and chart labels.
EMPIRICAL_SEASONAL_BASIS_TEXT = {
    "same_calendar_month": ("same-month starts only, not seasonally adjusted", "仅同月起点，未经季节调整"),
    "seasonal_profile": ("same-month seasonal mean plus pooled deviations, not seasonally adjusted",
                         "同月季节均值加合并偏差，未经季节调整"),
    "all_start_months": ("start months pooled, not seasonally adjusted", "合并所有起始月份，未经季节调整"),
}
EMPIRICAL_SEASONAL_BASIS_SHORT = {
    "same_calendar_month": ("same-month starts", "仅同月起点"),
    "seasonal_profile": ("seasonal profile", "同月季节均值"),
    "all_start_months": ("seasons pooled", "合并各起始月份"),
}


# Share of the month-over-month variance that the calendar month explains (adjusted for the 11
# month means any history fits by chance) from which an NSA monthly series counts as seasonal.
# The share is taken on the ranks of the changes, so one shock (the 2020 pandemic months in
# every ten-year carrier) cannot hide a seasonal swing: on raw changes the live NSA FRED
# unemployment rate (UNRATENSA), payrolls (PAYNSA) and CPI (CPIAUCNS) of 2016-11 to 2026 read
# -0.00, 0.19 and 0.22, on ranks 0.47, 0.66 and 0.33. On the stored 2026-10-13 carriers the EIA
# sales, price and generation series and the euro-area HICP index read 0.44-0.93; FRED's policy
# rates (FEDFUNDS, ECBDFR) and the semiconductor PPI, which FRED also labels 'Not Seasonally
# Adjusted', read 0.07 or less. A non-seasonal history long enough for a seasonal profile
# (61+ months) reaches 0.25 in under 1% of simulated random walks.
EMPIRICAL_SEASONAL_SHARE = 0.25
# 'seasonal_profile' sample (_empirical_profile): a start month needs this many h-step changes
# for its seasonal mean, and the latest observation's calendar month this many.
EMPIRICAL_PROFILE_MONTH_MIN = 3
EMPIRICAL_PROFILE_LATEST_MIN = 5


def _empirical_seasonal_share(history: List[Tuple[int, str, float]]) -> Optional[float]:
    """Adjusted share (epsilon squared, on ranks: the Kruskal-Wallis effect size) of the variance
    of month-over-month changes of a monthly ``history`` explained by their calendar month; None
    while some calendar month has fewer than three changes (too short a history to tell)."""
    changes = [(start % 12, value - before) for (start, _d, before), (end, _e, value) in zip(history, history[1:])
               if end == start + 1]
    order = sorted(range(len(changes)), key=lambda i: changes[i][1])
    ranks = [0.0] * len(changes)
    first = 0
    while first < len(order):  # ties share their average rank
        last = first
        while last + 1 < len(order) and changes[order[last + 1]][1] == changes[order[first]][1]:
            last += 1
        for position in range(first, last + 1):
            ranks[order[position]] = (first + last) / 2 + 1
        first = last + 1
    groups: Dict[int, List[float]] = {}
    for (month, _change), rank in zip(changes, ranks):
        groups.setdefault(month, []).append(rank)
    if len(groups) < 12 or min(len(group) for group in groups.values()) < 3:
        return None
    mean = sum(ranks) / len(ranks)
    total = sum((rank - mean) ** 2 for rank in ranks)
    if total <= 0:
        return 0.0
    between = sum(len(group) * (sum(group) / len(group) - mean) ** 2 for group in groups.values())
    return (between - 11 * (total - between) / (len(changes) - 12)) / total


def _empirical_profile(history: List[Tuple[int, str, float]], steps: int, *,
                       relative: bool = False) -> List[float]:
    """'seasonal_profile' sample of the h-step changes of a monthly ``history`` (fix contract,
    RPT-R2-7): every change c_t grouped by its start calendar month; each month with at least
    EMPIRICAL_PROFILE_MONTH_MIN changes gets its mean s(m), and the sample is s(m*) + r_t with
    r_t = c_t - s(month(t)) over the starts in those months, where m* (the latest
    observation's calendar month) needs at least EMPIRICAL_PROFILE_LATEST_MIN changes ([]
    otherwise). ``relative`` uses changes as a fraction of the starting value (zero starts
    skipped, as in _empirical_relative_changes)."""
    values = {index: value for index, _date, value in history}
    pairs = [(index % 12, (values[index + steps] - value) / (abs(value) if relative else 1))
             for index, _date, value in history if index + steps in values and (value or not relative)]
    groups: Dict[int, List[float]] = {}
    for month, change in pairs:
        groups.setdefault(month, []).append(change)
    latest = history[-1][0] % 12 if history else None
    if len(groups.get(latest, ())) < EMPIRICAL_PROFILE_LATEST_MIN:
        return []
    means = {month: sum(group) / len(group) for month, group in groups.items()
             if len(group) >= EMPIRICAL_PROFILE_MONTH_MIN}
    return [means[latest] + change - means[month] for month, change in pairs if month in means]


def _empirical_season(row: Dict[str, Any], history: List[Tuple[int, str, float]],
                      steps: int) -> Tuple[Optional[int], str]:
    """(start calendar month or None, seasonal basis) of an h-step sample of ``row``.

    A monthly series that is not seasonally adjusted (NSA, and not a year-over-year
    transform) carries its seasonal swing into every change between two different
    calendar months (h not a multiple of 12), so pooling every start month mixes the
    seasons: on the stored EIA commercial electricity sales, July-to-December changes
    have a median of -21,842 million kWh over the July starts and +63 over all starts.
    Such a sample keeps only starts in the latest observation's calendar month when they
    give at least EMPIRICAL_MIN_SAMPLES changes ('same_calendar_month'; with at most 240
    stored observations that needs a longer monthly history than a carrier holds). Else a
    history measured as seasonal takes the seasonal profile ('seasonal_profile',
    _empirical_profile: the latest calendar month's mean change plus every pooled
    deviation from its own month's mean) when that gives EMPIRICAL_MIN_SAMPLES values;
    otherwise every start month stays pooled and the basis says so ('all_start_months')
    wherever the sample is shown. 'NSA' alone does not make a series seasonal (FRED labels
    policy rates and yields so): a history whose calendar months explain less than
    EMPIRICAL_SEASONAL_SHARE of its month-over-month variance has no swing to mix, and a
    history too short to measure that share is never given a seasonal profile. Every
    other series or horizon: (None, ''), the plain pooled sample.
    """
    if (row.get("frequency") != "M" or row.get("seasonal_adjustment") != "NSA" or row.get("transform") == "yoy"
            or steps % 12 == 0 or not history):
        return None, ""
    share = _empirical_seasonal_share(history)
    if share is not None and share < EMPIRICAL_SEASONAL_SHARE:
        return None, ""
    month = history[-1][0] % 12
    if len(_empirical_changes(history, steps, month)) >= EMPIRICAL_MIN_SAMPLES:
        return month, "same_calendar_month"
    if share is not None and len(_empirical_profile(history, steps)) >= EMPIRICAL_MIN_SAMPLES:
        return None, "seasonal_profile"
    return None, "all_start_months"


def _empirical_sample(row: Dict[str, Any], history: List[Tuple[int, str, float]], steps: int, *,
                      relative: bool = False) -> Tuple[List[float], str]:
    """(h-step sample, seasonal basis) of ``row`` under _empirical_season: the changes
    (``relative``: as a fraction of the starting value) from every start, from the
    same-calendar-month starts, or the seasonal-profile sample."""
    month, basis = _empirical_season(row, history, steps)
    if basis == "seasonal_profile":
        return _empirical_profile(history, steps, relative=relative), basis
    return (_empirical_relative_changes if relative else _empirical_changes)(history, steps, month), basis


def empirical_seasonal_note(base: Any, zh: bool, *, short: bool = False) -> str:
    """Disclosure of an empirical sample's seasonal basis ('' for the plain pooled sample)."""
    basis = base.get("seasonal_basis") if isinstance(base, dict) else None
    texts = EMPIRICAL_SEASONAL_BASIS_SHORT if short else EMPIRICAL_SEASONAL_BASIS_TEXT
    text = texts.get(basis) if isinstance(basis, str) else None
    return text[1 if zh else 0] if text else ""


def _empirical_outlook(row: Dict[str, Any], period: Any, holds) -> Optional[Dict[str, Any]]:
    """Empirical h-step distribution from the latest historical observation to ``period``."""
    frequency = str(row.get("frequency") or "")
    history = _official_history(row)
    target = _official_period_index(period, frequency)
    if not history or target is None:
        return None
    latest_index, latest_date, latest = history[-1]
    steps = target - latest_index
    if steps <= 0:
        return None
    changes, basis = _empirical_sample(row, history, steps)
    if len(changes) < EMPIRICAL_MIN_SAMPLES:
        return None
    levels = sorted(round(latest + change, 9) for change in changes)
    mean = sum(changes) / len(changes)
    sd = math.sqrt(sum((c - mean) ** 2 for c in changes) / (len(changes) - 1))
    outlook = {
        "p": round(sum(1 for level in levels if holds(level)) / len(levels), 4),
        "n": len(levels), "h": steps,
        "window": {"start": history[0][1], "end": latest_date},
        "method": "empirical_h_step",
        "latest": {"date": latest_date, "value": latest},
        "quantiles": {name: round(_empirical_quantile(levels, q), 6) for name, q in _EMPIRICAL_QUANTILES},
        "historical_share": round(sum(1 for _i, _d, value in history if holds(round(value, 9))) / len(history), 4),
        "sd": sd,
    }
    if basis:
        outlook["seasonal_basis"] = basis
    return outlook


def official_empirical_base_rate(row: Dict[str, Any], anchor: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Outside view for a validated data anchor (fix contract §1.8), or None.

    h = periods from the latest complete historical observation to the anchor
    period; p = share of the historical h-step changes that, added to the latest
    value, satisfy the anchor's comparison (n >= 30 samples). ``sigma_distance`` is
    (threshold - latest) in standard deviations of those changes. A seasonal monthly
    series without seasonal adjustment adds ``seasonal_basis`` (_empirical_season), which
    every display of the rate discloses. The model's probability is never adjusted from it.
    """
    try:
        threshold = round(float(anchor["threshold"]), 9)
        compare = {">": lambda v: v > threshold, ">=": lambda v: v >= threshold,
                   "<": lambda v: v < threshold, "<=": lambda v: v <= threshold}[anchor["comparator"]]
        outlook = _empirical_outlook(row, anchor["period"], compare)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if outlook is None:
        return None
    sd = outlook.pop("sd")
    outlook["sigma_distance"] = round((threshold - outlook["latest"]["value"]) / sd, 2) if sd > 0 else None
    return outlook


def _official_period_date(index: int, frequency: str) -> str:
    if frequency == "M":
        year, month = divmod(index, 12)
        return f"{year:04d}-{month + 1:02d}-01"
    if frequency == "Q":
        year, quarter = divmod(index, 4)
        return f"{year:04d}-{quarter * 3 + 1:02d}-01"
    return f"{index:04d}-01-01"


def official_empirical_fan(row: Dict[str, Any], period: Any, max_steps: int = 120) -> List[Dict[str, Any]]:
    """Empirical outcome fan from the latest historical observation to ``period``.

    One point per step k = 1..h (h <= ``max_steps``): quantiles p10..p90 of the
    latest value plus every historical k-step change. Steps with fewer than 30
    samples are skipped; [] when the history cannot support any step. A step of a
    seasonal monthly series without seasonal adjustment uses the base rate's seasonal rule
    (_empirical_season) and records its ``seasonal_basis``.
    """
    frequency = str(row.get("frequency") or "")
    history = _official_history(row)
    target = _official_period_index(period, frequency)
    if not history or target is None:
        return []
    latest_index, _latest_date, latest = history[-1]
    fan = []
    for steps in range(1, min(target - latest_index, max_steps) + 1):
        changes, basis = _empirical_sample(row, history, steps)
        if len(changes) < EMPIRICAL_MIN_SAMPLES:
            continue
        levels = sorted(latest + change for change in changes)
        fan.append({"date": _official_period_date(latest_index + steps, frequency), "n": len(levels),
                    **{name: round(_empirical_quantile(levels, q), 6) for name, q in _EMPIRICAL_QUANTILES},
                    **({"seasonal_basis": basis} if basis else {})})
    return fan


def validate_metric_range(value: Any, official_data: Any) -> Optional[Dict[str, Any]]:
    """Normalize a scenario's ``metric_range`` against the stored carrier, or None.

    ``{series, low, high, period, units}``: one listed series, at least one finite
    bound (``null`` = open), low <= high, and a single period at the series frequency
    (validated by the shared anchor helper). Listed units are required; '%' is
    accepted for percent-unit series. Adds the empirical share of h-step outcomes
    that land in the range when the history supports it.
    """
    if not isinstance(value, dict):
        return None

    def bound(raw: Any) -> Optional[float]:
        if raw is None or isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
            return None
        return float(raw)

    low, high = bound(value.get("low")), bound(value.get("high"))
    for key in ("low", "high"):
        if value.get(key) is not None and bound(value.get(key)) is None:
            return None
    if (low is None and high is None) or (low is not None and high is not None and low > high):
        return None
    row = next((r for r in official_series_rows(official_data) if r["series"] == value.get("series")), None)
    if row is None:
        return None
    from .official_data import data_api, validate_data_anchor
    api = data_api()
    probe = {"series": row["series"], "comparator": ">=", "threshold": low if low is not None else high,
             "observation": value.get("period", value.get("observation"))}
    if "transform" in value:
        probe["transform"] = value["transform"]
    units = str(value.get("units") or "")
    if units and not (units.strip().casefold() == row["units"].strip().casefold()
                      or api is not None and api.is_percent_units(units) and api.is_percent_units(row["units"])):
        return None
    anchor = validate_data_anchor(probe, official_data)
    if anchor is None:
        return None
    result = {"series": anchor["series"], "low": low, "high": high, "period": anchor["period"],
              "observation": anchor["observation"], "units": anchor["units"],
              "frequency": anchor["frequency"], "transform": anchor["transform"]}

    def inside(level: float) -> bool:
        return (low is None or level >= round(low, 9)) and (high is None or level <= round(high, 9))

    outlook = _empirical_outlook(row, anchor["period"], inside)
    if outlook is not None:
        outlook.pop("sd")
        result["empirical_base_rate"] = outlook
    return result


def _official_period_text(period: str, frequency: str) -> str:
    if frequency == "M":
        return period[:7]
    if frequency == "Q":
        return f"{period[:4]}-Q{(int(period[5:7]) - 1) // 3 + 1}"
    if frequency == "A":
        return period[:4]
    return period[:10]


def official_fiscal_label(row: Any, period: Any) -> str:
    """'FY2026' when ``period`` (a stored date, '2025-10-01') of an annual ``row`` is a US
    federal fiscal year, else ''. The label is the row's stored period record (data layer
    provenance ``periods``, as report_agent.official_period_label reads it); a fiscal-year
    period the row does not store yet takes the data layer's own rule, FY<start year + 1>."""
    if not isinstance(row, dict) or row.get("frequency") != "A":
        return ""
    provenance = row.get("provenance")
    periods = provenance.get("periods") if isinstance(provenance, dict) else None
    if not isinstance(periods, dict):
        return ""
    day = str(period or "")[:10]
    record = periods.get(day)
    if isinstance(record, dict) and record.get("calendar") == "us_federal_fiscal_year":
        label = str(record.get("label") or "").strip()
        return label if re.fullmatch(r"FY\d{4}", label) else ""
    if (provenance.get("fiscal_start_month") == 10 and re.fullmatch(r"\d{4}-10-01", day)
            and any(isinstance(r, dict) and r.get("calendar") == "us_federal_fiscal_year" for r in periods.values())):
        return f"FY{int(day[:4]) + 1}"
    return ""


def official_anchor_period_text(row: Any, period: Any, frequency: str) -> str:
    """Reader period of a stored or anchored period: the fiscal-year label of a US federal
    fiscal-year row ('FY2026' for 2025-10-01), else the calendar period text (2026-12, 2026-Q2, 2026)."""
    return (official_fiscal_label(row, period) if frequency == "A" else "") or _official_period_text(
        str(period), frequency)


def _official_index_text(index: int, frequency: str) -> str:
    """The reader period of a period ordinal (inverse of _official_period_index)."""
    if frequency == "M":
        return f"{index // 12:04d}-{index % 12 + 1:02d}"
    if frequency == "Q":
        return f"{index // 4:04d}-Q{index % 4 + 1}"
    return f"{index:04d}"


def _official_horizon_index(horizon_date: Any, frequency: str) -> Optional[int]:
    text = str(horizon_date or "").strip()
    match = re.match(r"(\d{4})(?:-(\d{2}))?", text)
    if not match:
        return None
    return _official_period_index(f"{match.group(1)}-{match.group(2) or '12'}", frequency)


def _empirical_relative_changes(history: List[Tuple[int, str, float]], steps: int,
                                month: Optional[int] = None) -> List[float]:
    """h-step changes as a fraction of the starting value (zero starts skipped); ``month`` as
    in _empirical_changes."""
    values = {index: value for index, _date, value in history}
    return [(values[index + steps] - value) / abs(value) for index, _date, value in history
            if index + steps in values and value and (month is None or index % 12 == month)]


def official_outside_view_block(official_data: Any, horizon_date: Any = None, language: str = "English",
                                max_chars: int = 3600) -> str:
    """Deterministic outside-view lines from stored history ("" when none).

    Per monthly/quarterly/annual series: latest complete historical value, its
    percentile within the stored history, and empirical quantiles of the change
    from the latest period to the horizon (or over a standard 12 months / 4 quarters /
    1 year, said so, when the horizon is unknown or lacks 30 samples); each line names
    the window it describes and, for a seasonal monthly series without seasonal adjustment, the
    start months its sample uses (_empirical_season). For levels and indexes (units not in percent or points) the same
    change is also given in percent, the scale a growth or inflation threshold is
    set on. Lines are dropped whole beyond ``max_chars`` with a count note.
    """
    rows = official_series_rows(official_data)
    if not rows:
        return ""
    from .official_data import data_api
    api = data_api()
    if api is None:
        return ""
    zh = str(language or "").lower().startswith(("zh", "chinese")) or "中文" in str(language or "")
    lines = []
    for row in rows:
        frequency = row["frequency"]
        history = _official_history(row)
        if frequency not in _EMPIRICAL_DEFAULT_STEPS or len(history) < 12:
            continue
        latest_index, latest_date, latest = history[-1]
        rank = sum(1 for _i, _d, value in history if value <= latest) / len(history)
        units = row["units"]
        label = api.series_label(row, "zh" if zh else "en")
        span = (_official_period_text(history[0][1], frequency), _official_period_text(latest_date, frequency))
        horizon = _official_horizon_index(horizon_date, frequency)
        steps = horizon - latest_index if horizon is not None and horizon > latest_index else None
        changes, basis = _empirical_sample(row, history, steps) if steps else ([], "")
        to_horizon = len(changes) >= EMPIRICAL_MIN_SAMPLES
        if not to_horizon:
            steps = _EMPIRICAL_DEFAULT_STEPS[frequency]
            changes, basis = _empirical_sample(row, history, steps)
        seasonal = empirical_seasonal_note({"seasonal_basis": basis}, zh, short=True)
        scaled = api.scaled_value(latest, units, "zh" if zh else "en")
        value = (api.format_value(latest, units) + ("" if api.is_percent_units(units) else f" {units}")
                 + (f"（{scaled}）" if zh and scaled else f" ({scaled})" if scaled else ""))
        noun = {"M": ("months", "个月"), "Q": ("quarters", "个季度"), "A": ("years", "年")}[frequency]
        target = _official_index_text(latest_index + steps, frequency)
        if zh:
            line = (f"- {label}（{row['series']}）：最新 {value}（{_official_period_text(latest_date, frequency)}）；"
                    f"{span[0]} 至 {span[1]} 共 {len(history)} {noun[1]}历史值，最新值处于第 {round(rank * 100)} 百分位")
        else:
            line = (f"- {label} ({row['series']}): latest {value} ({_official_period_text(latest_date, frequency)}); "
                    f"{len(history)} historical {noun[0]} {span[0]} to {span[1]}, latest at percentile "
                    f"{round(rank * 100)} of that history")
        if len(changes) >= EMPIRICAL_MIN_SAMPLES:
            ordered = sorted(changes)
            cells = [api.format_change(round(_empirical_quantile(ordered, q), 9), units) for q in (0.1, 0.5, 0.9)]
            if zh:
                sample = f"n={len(changes)}" + (f"；{seasonal}" if seasonal else "")
                window = (f"至预测期末 {target} 的 {steps} {noun[1]}变化经验分位（{sample}）" if to_horizon
                          else f"{steps} {noun[1]}变化经验分位（标准窗口，非预测期末；{sample}）")
                line += f"；{window}：p10 {cells[0]}，中位数 {cells[1]}，p90 {cells[2]}"
            else:
                sample = f"n={len(changes)}" + (f"; {seasonal}" if seasonal else "")
                window = (f"{steps}-{noun[0][:-1]} change to the horizon {target} ({sample})" if to_horizon
                          else f"{steps}-{noun[0][:-1]} change (a standard window, not the horizon; {sample})")
                line += f"; {window}: p10 {cells[0]}, median {cells[1]}, p90 {cells[2]}"
            relative = ([] if api.is_percent_units(units) or re.search(r"point", units, re.I)
                        else sorted(_empirical_sample(row, history, steps, relative=True)[0]))
            if len(relative) >= EMPIRICAL_MIN_SAMPLES:
                cells = [api.format_change(round(_empirical_quantile(relative, q) * 100, 9), "Percent")
                         .replace(" pp", "%") for q in (0.1, 0.5, 0.9)]
                if zh:
                    line += f"；按百分比变化：p10 {cells[0]}，中位数 {cells[1]}，p90 {cells[2]}"
                else:
                    line += f"; as % change: p10 {cells[0]}, median {cells[1]}, p90 {cells[2]}"
        lines.append(line + ("。" if zh else "."))
    if not lines:
        return ""
    if zh:
        head = "【官方历史·外部视角（仅由已存储的完整历史观测计算，不含不完整期、估计与预测值；不是预测）】"
        foot = "为所列序列设定阈值或区间时，先以上述经验分布为基率，再按本案特征调整并说明理由。"
    else:
        head = ("[Official history — outside view (computed only from stored complete historical observations; "
                "partial periods, estimates and projections excluded; not a forecast)]")
        foot = ("When setting a threshold or range on a listed series, start from these empirical "
                "distributions as the base rate, then adjust for case specifics and say why.")
    kept = []
    for line in lines:
        if len(head) + len(foot) + 80 + sum(len(item) + 1 for item in kept) + len(line) > max_chars:
            break
        kept.append(line)
    if len(kept) < len(lines):
        omitted = len(lines) - len(kept)
        kept.append(f"（另有 {omitted} 个序列因篇幅省略）" if zh else f"({omitted} further series omitted for length)")
    return "\n".join([head, *kept, foot])


_ANCHOR_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
                  "september", "october", "november", "december")
_ANCHOR_MONTH_ALIASES = {**{name: i for i, name in enumerate(_ANCHOR_MONTHS, 1)},
                         **{name[:3]: i for i, name in enumerate(_ANCHOR_MONTHS, 1)}, "sept": 9}
_ANCHOR_ORDINAL_QUARTERS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "1st": 1, "2nd": 2,
                            "3rd": 3, "4th": 4, "一": 1, "二": 2, "三": 3, "四": 4}
# Chinese dates may be typeset with spaces around the digits ('2027 年 12 月'); a neighbouring
# CJK character is not a word boundary for the Latin forms ('在Q4 2027', '2027年Q4').
_ANCHOR_PERIOD_RE = re.compile(
    r"(?P<ymd>(?<!\d)(?P<ymd_y>\d{4})-(?P<ymd_m>\d{2})-(?P<ymd_d>\d{2})(?!\d))"
    r"|(?P<zhd>(?P<zhd_y>\d{4})\s*年\s*(?P<zhd_m>\d{1,2})\s*月\s*(?P<zhd_d>\d{1,2})\s*[日号])"
    r"|(?P<zhm>(?P<zhm_y>\d{4})\s*年\s*(?P<zhm_m>\d{1,2})\s*月份?)"
    r"|(?P<zhq>(?P<zhq_y>\d{4})\s*年\s*第?\s*(?P<zhq_q>[一二三四1-4])\s*季度)"
    r"|(?P<yq>(?<!\d)(?P<yq_y>\d{4})\s*(?:年\s*)?[- ]?Q(?P<yq_q>[1-4])(?![A-Za-z0-9]))"
    r"|(?P<qy>(?<![A-Za-z0-9])Q(?P<qy_q>[1-4])[- ]?(?P<qy_y>\d{4})(?!\d))"
    r"|(?P<oq>\b(?P<oq_o>first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter\s+(?:of\s+)?(?P<oq_y>\d{4})(?!\d))"
    r"|(?P<ym>(?<!\d)(?P<ym_y>\d{4})-(?P<ym_m>\d{2})(?![\d-]))"
    r"|(?P<my>(?<![A-Za-z])(?P<my_m>" + "|".join(sorted(_ANCHOR_MONTH_ALIASES, key=len, reverse=True))
    + r")\.?(?:,?\s+|-)(?:of\s+)?(?P<my_y>\d{4})(?!\d))"
    r"|(?P<y>(?<![\d.])(?P<y_y>\d{4})(?:\s*年(?!\s*[\d第]))?(?!\d|\.\d|%))",
    re.I,
)
# Periods introduced by these words describe a deadline or a different interval.
_ANCHOR_PERIOD_LEAD_RE = re.compile(
    r"(?:\b(?:by|before|until|till|through|thru|prior\s+to|no\s+later\s+than|ahead\s+of|from|since|"
    r"after|end|end\s+of|close\s+of|within)|截至|截止|到|自|从)\s*(?:the\s+)?(?:end\s+of\s+)?$",
    re.I,
)
_ANCHOR_PERIOD_TAIL_RE = re.compile(r"^\s*(?:之前|以前|前|底|末|以来|之后|以后|后|起)")
_ANCHOR_NUMBER = (r"(?P<sign>[-+−])?\s*(?P<currency>US\$|\$|USD\s)?\s*"
                  r"(?P<number>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
                  r"(?P<scale>(?:trillion|billion|million|thousand)(?![A-Za-z])|万亿|亿|万)?")
_ANCHOR_SCALES = {"trillion": 1e12, "billion": 1e9, "million": 1e6, "thousand": 1e3,
                  "万亿": 1e12, "亿": 1e8, "万": 1e4}
_ANCHOR_UNIT_TOKENS = (r"percentage\s+points?|个百分点|百分点|per\s*cent|percent|pp\b|%|"
                       r"u\.?s\.?\s+dollars?|dollars?|美元")
_ANCHOR_COMPARATOR_WORDS = (
    (">=", ("greater than or equal to", "equal to or greater than", "more than or equal to",
            "equal to or above", "equal to or higher than", "at or above", "at or over", "at or higher than",
            "at least", "no less than", "not less than", "no lower than", "not lower than", "not below",
            "no fewer than",
            "大于或等于", "大于等于", "高于或等于", "达到或超过", "不低于", "不少于", "不小于", "至少")),
    ("<=", ("less than or equal to", "equal to or less than", "equal to or below", "equal to or lower than",
            "at or below", "at or under", "at or lower than", "at most", "no more than", "not more than",
            "no higher than", "not higher than", "not above", "no greater than", "not exceeding",
            "小于或等于", "小于等于", "低于或等于", "不超过", "不高于", "不大于", "至多", "最多")),
    (">", ("greater than", "more than", "higher than", "in excess of", "above", "exceeds", "exceeding",
           "exceeded", "exceed", "surpasses", "surpass", "tops", "over",
           "超过", "高于", "大于", "突破", "超出")),
    ("<", ("less than", "lower than", "below", "under", "beneath",
           "低于", "小于", "少于", "跌破", "不足", "不到")),
)
_ANCHOR_POSTFIX_WORDS = ((">=", ("or more", "or higher", "or above", "or greater", "及以上", "或以上", "或更高")),
                         ("<=", ("or less", "or lower", "or below", "or fewer", "及以下", "或以下", "或更低")))
# The sign of the value is a comparison with zero ('the spread is negative', '增速为负').
_ANCHOR_SIGN_WORDS = (("<", ("negative", "below zero", "under zero", "less than zero",
                             "为负", "转负", "负值", "低于零", "小于零")),
                      (">", ("positive", "above zero", "greater than zero",
                             "为正", "转正", "正值", "高于零", "大于零")))
_ANCHOR_SYMBOLS = {">=": ">=", "=>": ">=", "≥": ">=", "<=": "<=", "=<": "<=", "≤": "<=", ">": ">", "<": "<"}
_ANCHOR_SYMBOL_RE = r"(?P<symbol>>=|=>|≥|<=|=<|≤|>|<)"
# Full-width forms typed with Chinese input methods read as their ASCII equivalents.
_ANCHOR_FULLWIDTH = str.maketrans({"＞": ">", "＜": "<", "＝": "=", "≧": "≥", "≦": "≤", "⩾": "≥", "⩽": "≤",
                                   "％": "%", "．": ".", "－": "-",
                                   **{chr(0xFF10 + digit): str(digit) for digit in range(10)}})
# Negation, alternatives, conditions and conjunctions change the proposition.
_ANCHOR_BLOCKERS_RE = re.compile(
    r"\b(?:not|no|never|neither|nor|unless|if|or|either|except|excluding|without|fail|fails|failed|"
    r"instead|otherwise|whether|and|but|while|whereas|although|though|plus|then|also|"
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|"
    r"hundred|percent|per\s*cent|trillion|billion|million|thousand)\b|n't|%|"
    r"不|未|没|无|非|或|若|如果|除非|否则|并且|而且|且|同时|但|以及|和|与|及|并|百分之",
    re.I,
)
_ANCHOR_FRAMING_RE = re.compile(
    r"^(?:(?:this\s+(?:question|forecast|binary)\s+)?resolves?\s+(?:to\s+)?yes\s+(?:if|when)|"
    r"resolved?\s+yes\s+(?:if|when)|yes\s+(?:if|when)|resolution\s*[:：]|resolution\s+criteria\s*[:：]|"
    r"criteria\s*[:：]|判定(?:标准)?\s*[:：]?\s*(?:为是)?\s*(?:若|如果|当)?|若|如果|当|是\s*[:：]?)\s*",
    re.I,
)
_ANCHOR_SOURCE_SUFFIX_RE = re.compile(
    r"^[\s,;，；—–-]*(?:[(（]\s*)?(?:(?:source|sources|data\s+source|per|according\s+to|as\s+(?:published|"
    r"reported|released|measured)\s+(?:by|in|on)|published\s+by|reported\s+by|released\s+by|from|via)\b|"
    r"数据来源|来源|据|以|按)",
    re.I,
)
_ANCHOR_YES_SUFFIX_RE = re.compile(r"^[\s,，]*(?:则)?(?:判定|视为|记为)?为?\s*[“\"]?(?:是|YES)[”\"]?\s*[。.!]?\s*$", re.I)
# A provider whose name carries digits ('World Bank Data360') is a name, not a second number.
_ANCHOR_PROVIDER_DIGITS_RE = re.compile(r"(?<![A-Za-z0-9])data\s?360(?![A-Za-z0-9])", re.I)
# A resolution phrase directly after the clause, before a source ('，判定为是（数据来源：FRED）').
_ANCHOR_YES_LEAD_RE = re.compile(
    r"^[\s,，]*(?:(?:则\s*)?(?:判定|视为|记为)\s*为?\s*[“\"]?(?:是|YES)[”\"]?|"
    r"(?:then\s+)?(?:it\s+)?resolves?\s+(?:to\s+)?[“\"]?yes[”\"]?)(?![A-Za-z])", re.I)


def _anchor_period_key(match: "re.Match[str]") -> Optional[Tuple[str, str]]:
    """(granularity, canonical period) for one period mention."""
    try:
        if match.group("ymd"):
            return "D", f"{int(match.group('ymd_y')):04d}-{int(match.group('ymd_m')):02d}-{int(match.group('ymd_d')):02d}"
        if match.group("zhd"):
            return "D", f"{int(match.group('zhd_y')):04d}-{int(match.group('zhd_m')):02d}-{int(match.group('zhd_d')):02d}"
        if match.group("zhm"):
            month = int(match.group("zhm_m"))
            return ("M", f"{int(match.group('zhm_y')):04d}-{month:02d}") if 1 <= month <= 12 else None
        for name in ("zhq", "yq", "qy", "oq"):
            if match.group(name):
                raw = match.group(f"{name}_q" if name != "oq" else "oq_o").lower()
                quarter = _ANCHOR_ORDINAL_QUARTERS.get(raw) or int(raw)
                return "Q", f"{int(match.group(name + '_y')):04d}-Q{quarter}"
        if match.group("ym"):
            month = int(match.group("ym_m"))
            return ("M", f"{int(match.group('ym_y')):04d}-{month:02d}") if 1 <= month <= 12 else None
        if match.group("my"):
            return "M", f"{int(match.group('my_y')):04d}-{_ANCHOR_MONTH_ALIASES[match.group('my_m').lower()]:02d}"
        if match.group("y"):
            return "A", f"{int(match.group('y_y')):04d}"
    except (TypeError, ValueError, KeyError):
        return None
    return None


def _anchor_target(period: str, frequency: str, row: Any = None) -> Tuple[str, str]:
    """The anchor's normalized period as (granularity, canonical text) for prose matching.

    A US federal fiscal year of ``row`` is ('FY', 'FY2026'): only a fiscal-year mention
    (_anchor_periods with ``fiscal``) or its exact start date names it, never a calendar year."""
    label = official_fiscal_label(row, period) if row is not None and frequency == "A" else ""
    if label:
        return "FY", label
    if frequency == "M":
        return "M", period[:7]
    if frequency == "Q":
        return "Q", f"{period[:4]}-Q{(int(period[5:7]) - 1) // 3 + 1}"
    if frequency == "A":
        return "A", period[:4]
    return "D", period[:10]


def _anchor_mention_matches(key: Tuple[str, str], target: Tuple[str, str]) -> bool:
    """A period mention names exactly the target period at the series frequency.

    Exact period starts written as dates ("2027-04-01" for Q2 2027) are accepted.
    """
    granularity, value = key
    if (granularity, value) == target:
        return True
    if granularity != "D" or target[0] == "D":
        return False
    year, month, day = int(value[:4]), int(value[5:7]), int(value[8:10])
    if day != 1:
        return False
    if target[0] == "FY":
        return month == 10 and f"FY{year + 1}" == target[1]
    if target[0] == "M":
        return f"{year:04d}-{month:02d}" == target[1]
    if target[0] == "Q":
        return month in (1, 4, 7, 10) and f"{year:04d}-Q{(month - 1) // 3 + 1}" == target[1]
    return month == 1 and f"{year:04d}" == target[1]


def _anchor_end_of_month(row: Dict[str, Any]) -> bool:
    """A monthly series whose values are end-of-month readings: daily data the data
    layer aggregated end of month, or (when the data layer did not aggregate) a
    publisher's monthly end-of-period series such as BIS 'Monthly - End of period'."""
    if row.get("frequency") != "M":
        return False
    provenance = row.get("provenance")
    method = provenance.get("aggregation_method") if isinstance(provenance, dict) else None
    if method:
        return method == "eop"
    return bool(re.search(r"\bend[\s-]of[\s-]period\b", str(row.get("title") or ""), re.I))


def _anchor_month_end_text(text: str, target: Tuple[str, str]) -> str:
    """Month-end wordings of the target month rewritten to the canonical month.

    Only for an end-of-month series (whose month value IS its last daily reading):
    '31 December 2026', 'December 31, 2026', 'the end of December 2026',
    '2026-12-31' and '2026年12月31日/底' (and, for December, 'year-end 2026',
    'end of 2026', '2026年底') name the target month. A deadline before them
    ('by the end of 2026') stays a deadline; any other day stays a day.
    """
    if target[0] != "M":
        return text
    year, month = int(target[1][:4]), int(target[1][5:7])
    last = calendar.monthrange(year, month)[1]
    names = "|".join(sorted((re.escape(name) for name, number in _ANCHOR_MONTH_ALIASES.items()
                             if number == month), key=len, reverse=True))
    day = rf"{last}(?:st|nd|rd|th)?"
    patterns = [
        rf"(?<![\w-])(?:(?:at|on)\s+)?(?:the\s+)?(?:last\s+day|end)\s+of\s+(?:{names})\.?,?\s+(?:of\s+)?{year}(?!\d)",
        rf"(?<![\w-])(?:on\s+)?(?:the\s+)?{day}\s+(?:of\s+)?(?:{names})\.?,?\s+{year}(?!\d)",
        rf"(?<![\w-])(?:on\s+)?(?:{names})\.?\s+{day},?\s+{year}(?!\d)",
        rf"(?<![\d-]){year}-{month:02d}-{last:02d}(?![\d-])",
        rf"(?<!\d){year}\s*年\s*0?{month}\s*月\s*(?:{last}\s*[日号]|底|末)",
    ]
    if month == 12:
        patterns += [
            rf"(?<![\w-])(?:(?:at|on)\s+)?(?:the\s+)?(?:end\s+of\s+|year[-\s]end\s+(?:of\s+)?|end-){year}(?!\d)",
            rf"(?<!\d){year}\s*年\s*(?:底|末)",
        ]
    for pattern in patterns:
        text = re.sub(pattern, target[1], text, flags=re.I)
    return text


# A year named as a fiscal year ('FY2026', 'FY 2026', 'fiscal year 2026', 'fiscal 2026',
# '2026 fiscal year', '2026财年', '2026财政年度'), read only for a fiscal-year anchor.
_ANCHOR_FISCAL_PREFIX_RE = re.compile(r"(?:(?<![A-Za-z])FY|\bfiscal(?:\s+year)?)\s*$", re.I)
_ANCHOR_FISCAL_SUFFIX_RE = re.compile(r"^(?:\s*(?:财年|财政年度|会计年度)|\s+fiscal\s+year\b)", re.I)


def _anchor_periods(text: str, fiscal: bool = False) -> List[Tuple[int, int, Optional[Tuple[str, str]], bool]]:
    """Every period mention: (start, end, key, introduced by a deadline/interval word).

    With ``fiscal`` (a US federal fiscal-year anchor) a year named as a fiscal year is
    ('FY', 'FY2026') and its span includes the fiscal wording; a bare year stays a calendar year."""
    found = []
    for match in _ANCHOR_PERIOD_RE.finditer(text):
        start, end, key = match.start(), match.end(), _anchor_period_key(match)
        if fiscal and match.group("y") and not re.search(r"年\s*$", match.group(0)):
            prefix = _ANCHOR_FISCAL_PREFIX_RE.search(text[max(0, start - 20):start])
            suffix = _ANCHOR_FISCAL_SUFFIX_RE.match(text[end:])
            if prefix or suffix:
                key = ("FY", f"FY{int(match.group('y_y')):04d}")
                start -= len(prefix.group(0)) if prefix else 0
                end += suffix.end() if suffix else 0
        lead = bool(_ANCHOR_PERIOD_LEAD_RE.search(text[max(0, start - 40):start]))
        tail = bool(_ANCHOR_PERIOD_TAIL_RE.match(text[end:]))
        found.append((start, end, key, lead or tail))
    return found


_ANCHOR_UNIT_SCALE_RE = re.compile(r"^\s*(thousand|million|billion|trillion)s?(?:\s+of)?\s+", re.I)


def _anchor_unit_scale(units: str) -> Tuple[float, str]:
    """(multiplier, base units) of scaled units: 'Billions of Chained 2017 Dollars' -> (1e9, ...),
    'Million kilowatt-hours' -> (1e6, 'kilowatt-hours')."""
    match = _ANCHOR_UNIT_SCALE_RE.match(units)
    return (_ANCHOR_SCALES[match.group(1).lower()], units[match.end():]) if match else (1.0, units)


def _anchor_value(match: "re.Match[str]", units: str = "") -> Optional[float]:
    """The written number in the series' units: a scale word ('$24.5 trillion') is
    divided by the units' own scale ('Billions of ...' -> 24500)."""
    try:
        value = float(match.group("number").replace(",", ""))
    except (TypeError, ValueError):
        return None
    if match.group("sign") in ("-", "−"):
        value = -value
    scale = match.group("scale")
    return value * _ANCHOR_SCALES[scale.lower()] / _anchor_unit_scale(units)[0] if scale else value


def _anchor_unit_ok(match: "re.Match[str]", units: str) -> bool:
    """Units written next to the number must agree with the stored units."""
    from .official_data import data_api
    api = data_api()
    percent = bool(api and api.is_percent_units(units))
    points = bool(re.search(r"percentage\s+points?", units, re.I))
    dollars = bool(re.search(r"dollar|usd", units, re.I))
    token = re.sub(r"\s+", " ", str(match.group("unit") or "").strip().lower())
    full = re.sub(r"\s+", " ", units.strip().lower())
    base = re.sub(r"\s+", " ", _anchor_unit_scale(units)[1].strip().lower())
    if (match.group("currency") or token in {"dollar", "dollars", "美元"} or token.endswith("dollars")
            or token.endswith("dollar")) and not dollars:
        return False
    if match.group("scale") and (percent or points):
        return False
    if token == full or not (token or match.group("currency")):
        return True
    if base != full and not match.group("scale"):
        # Units with a scale word ('Thousands of U.S. Dollars', 'Million kilowatt-hours'): an amount
        # written with a currency or unit but no scale word ('$70,000,000', '160,000 kilowatt-hours')
        # is a thousandth or a millionth of the same number in the series' units.
        return False
    if not token or token == base:
        return True
    if token in {"%", "percent", "per cent"}:
        return percent
    if token in {"pp", "percentage point", "percentage points", "个百分点", "百分点"}:
        return points
    return dollars and ("dollar" in token or token == "美元")


def _anchor_comparisons(text: str, units: str) -> List[Tuple[int, int, str, Optional[float], bool]]:
    """Comparator+number expressions: (start, end, comparator, value, units agree)."""
    # A unit ends at a word boundary: 'Percent' must not swallow the start of 'percentage points'.
    # Scaled units also read without their scale word after a written one ('160,000 million kilowatt-hours').
    base = _anchor_unit_scale(units)[1].strip()
    names = "|".join(re.escape(name) for name in dict.fromkeys((units.strip(), base)) if name)
    unit = rf"(?:\s*(?P<unit>(?:{names}|{_ANCHOR_UNIT_TOKENS})(?![A-Za-z])))?" if names else \
        rf"(?:\s*(?P<unit>(?:{_ANCHOR_UNIT_TOKENS})(?![A-Za-z])))?"
    spans: List[Tuple[int, int, str, Optional[float], bool]] = []
    patterns = [(re.compile(_ANCHOR_SYMBOL_RE + r"\s*" + _ANCHOR_NUMBER + unit, re.I), None)]
    for comparator, words in _ANCHOR_COMPARATOR_WORDS:
        alternation = "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in sorted(words, key=len, reverse=True))
        patterns.append((re.compile(rf"(?:(?<![A-Za-z])(?:{alternation})(?![A-Za-z]))\s*(?:of\s+)?"
                                    + _ANCHOR_NUMBER + unit, re.I), comparator))
    for comparator, words in _ANCHOR_POSTFIX_WORDS:
        alternation = "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in words)
        # A CJK verb may sit right before the number ('达到5%及以上'); a Latin identifier may not.
        patterns.append((re.compile(r"(?<![A-Za-z0-9_.])" + _ANCHOR_NUMBER + unit
                                    + rf"\s*(?:{alternation})(?![A-Za-z])", re.I), comparator))
    for pattern, comparator in patterns:
        for match in pattern.finditer(text):
            if any(match.start() < end and start < match.end() for start, end, *_ in spans):
                continue
            symbol = _ANCHOR_SYMBOLS.get(match.groupdict().get("symbol") or "", comparator)
            spans.append((match.start(), match.end(), symbol, _anchor_value(match, units),
                          _anchor_unit_ok(match, units)))
    for comparator, words in _ANCHOR_SIGN_WORDS:
        alternation = "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in sorted(words, key=len, reverse=True))
        # 'non-negative' is the opposite proposition, so a hyphenated prefix never counts.
        for match in re.finditer(rf"(?<![A-Za-z-])(?:{alternation})(?![A-Za-z-])", text, re.I):
            if not any(match.start() < end and start < match.end() for start, end, *_ in spans):
                spans.append((match.start(), match.end(), comparator, 0.0, True))
    return sorted(spans)


def _anchor_blank(text: str, spans: List[Tuple[int, int]]) -> str:
    chars = list(text)
    for start, end in spans:
        for i in range(start, end):
            chars[i] = " "
    return "".join(chars)


def _anchor_units_spans(text: str, units: str) -> List[Tuple[int, int]]:
    """Mentions of the stored units in prose ('(chained 2017 dollars)'): descriptive, not a second number."""
    spans: List[Tuple[int, int]] = []
    for term in sorted({units.strip(), _anchor_unit_scale(units)[1].strip()}, key=len, reverse=True):
        if len(term) < 3:
            continue
        for match in re.finditer(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", text, re.I):
            if not any(match.start() < end and start < match.end() for start, end in spans):
                spans.append(match.span())
    return spans


def _anchor_row_geography(row: Dict[str, Any]) -> str:
    """The series' geography code: the stored one, else its catalog entry's, else the single
    geography its title names (a FRED search result such as 'ECB Deposit Facility Rate for
    Euro Area' is stored without one)."""
    geography = str(row.get("geography") or getattr(_anchor_catalog_entry(row), "geography", "") or "").upper()
    if geography:
        return geography
    from .official_data import data_api
    api = data_api()
    named = api.catalog.query_geographies(str(row.get("title") or "")) if api is not None else ()
    return next(iter(named)) if len(named) == 1 else ""


def _anchor_catalog_entry(row: Dict[str, Any]) -> Any:
    from .official_data import data_api
    api = data_api()
    return api.catalog.lookup(row["series"].partition("#")[0]) if api is not None else None


def _anchor_metric_labels(row: Dict[str, Any]) -> List[str]:
    """Reader-facing names of the series (EN and ZH titles, labels, catalog terms)."""
    from .official_data import data_api
    api = data_api()
    entry = _anchor_catalog_entry(row)
    titles = {str(row.get("title") or ""), str(row.get("title_zh") or ""),
              str(getattr(entry, "title", "") or ""), str(getattr(entry, "title_zh", "") or "")}
    if api is not None:
        titles.update({api.series_label(row), api.series_label(row, "zh")})
    geography = _anchor_row_geography(row)
    name, aliases = (api.catalog.GEOGRAPHIES.get(geography, (geography, ())) if api is not None else ("", ()))
    # A trailing qualifier ('（月均）', '(daily)') is part of the title, not of how prose names
    # it; the shortened name must stay specific (two words, or four CJK characters).
    for title in list(titles):
        short = re.sub(r"\s*[（(][^（）()]*[）)]\s*$", "", title)
        if short != title and (len(short.split()) >= 2 or len(re.findall(r"[㐀-鿿]", short)) >= 4):
            titles.add(short)
    for title in list(titles):
        for term in (name, *aliases):
            term = str(term or "")
            if term and re.search(r"[㐀-鿿]", term) and term in title:
                titles.add(title.replace(term, ""))
        titles.add(re.sub(r"\s*(?:—|:|-)\s*" + re.escape(name) + r"\s*$", "", title, flags=re.I) if name else title)
    for keyword in getattr(entry, "keywords", ()) or ():
        keyword = str(keyword)
        cjk = len(re.findall(r"[㐀-鿿]", keyword))
        # Specific keywords only: two words, three CJK characters, or an acronym with two ('gdp增速').
        if len(keyword.split()) >= 2 or cjk >= 3 or cjk >= 2 and len(re.findall(r"[A-Za-z]", keyword)) >= 2:
            titles.add(keyword)
    labels = {re.sub(r"\s+", " ", t).strip(" —:-") for t in titles}
    # Chinese prose names a growth rate 增速 as often as 增长率 ('实际GDP增速' is '实际GDP增长率').
    labels |= {label.replace(a, b) for label in labels for a, b in (("增长率", "增速"), ("增速", "增长率"))
               if a in label}
    return sorted((t for t in labels if len(t) >= 2), key=len, reverse=True)


# Title words prose leaves out when naming a series ('Market Yield on U.S. Treasury Securities at
# 10-Year Constant Maturity' is 'the 10-year Treasury yield'); the remaining title words must all
# appear together, joined only by the connective words below.
_ANCHOR_TITLE_FILLER = frozenset((
    "a", "an", "the", "of", "for", "in", "on", "at", "to", "by", "and", "or", "as", "all", "item", "items",
    "total", "plus", "minus", "less", "constant", "maturity", "market", "yield", "yields", "quoted",
    "investment", "basis", "securities", "seasonally", "adjusted", "index", "level", "average", "rate",
    "rates", "u", "s", "us", "daily", "weekly", "monthly", "quarterly", "annual", "end", "period", "percent",
    "change", "prices", "current", "month", "units",
))
_ANCHOR_TITLE_JOINERS = frozenset((
    "the", "of", "on", "and", "minus", "less", "between", "versus", "vs", "u", "s", "us", "constant",
    "maturity", "market", "yield", "yields", "rate", "rates", "securities", "note", "notes", "bond", "bonds",
    "bill", "bills",
))
_ANCHOR_TENOR_NUMBERS = {"one": 1, "two": 2, "three": 3, "five": 5, "six": 6, "seven": 7, "ten": 10,
                         "twenty": 20, "thirty": 30}
# Tenors read alike in every spelling: '10-year', '10 year', '10y', 'ten-year' -> '10y'; '3-month', '3m' -> '3m'.
_ANCHOR_TOKEN_RE = re.compile(
    r"(?<![0-9.])(?P<n>\d{1,2})(?:-?(?P<short>yrs?|y|mos?|m)|[\s-]?(?P<long>years?|months?))(?![a-z])"
    r"|(?<![a-z])(?P<word>" + "|".join(_ANCHOR_TENOR_NUMBERS) + r")[\s-](?P<wlong>years?|months?)(?![a-z])"
    r"|[a-z]+", re.I)
_ANCHOR_WINDOW_GAP_RE = re.compile(r"[\s\-–—/()'’.]*")


def _anchor_tokens(text: str) -> List[Tuple[str, int, int]]:
    """(token, start, end) of the ASCII words (lowercased) and normalized tenors of ``text``;
    offsets index ``text`` itself."""
    tokens = []
    for match in _ANCHOR_TOKEN_RE.finditer(text):
        number = match.group("n") or _ANCHOR_TENOR_NUMBERS.get((match.group("word") or "").lower())
        unit = (match.group("short") or match.group("long") or match.group("wlong") or "").lower()
        token = f"{int(number)}{'y' if unit[0] == 'y' else 'm'}" if number and unit else match.group(0).lower()
        tokens.append((token, match.start(), match.end()))
    return tokens


# Clause boundaries of a compound question, as the data catalog splits one ("Will US CPI fall below
# 2.5% ..., and how will the Fed policy rate evolve?"): sentence ends (not the 'S.' of 'U.S.'),
# ?!;: , ', and/but/or/while/whereas', 'and/but' before a question word, and CJK punctuation.
_QUESTION_CLAUSE_RE = re.compile(
    r"(?<!\b[A-Za-z])\.(?=\s|$)|[?!;。？！；：\n]+|:\s|,\s*(?:and|but|or|while|whereas)\s+"
    r"|\s+(?:and|but)\s+(?=(?:how|what|when|where|whether|which|who|why|will|would|could|can|should|does|do"
    r"|did|is|are)\b)|[，、]",
    re.I,
)


def official_question_mention(question: str, row: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """(clause, position) where ``question`` first names a stored series (title, catalog name
    or acronym, EN or ZH, with hyphenated compounds such as 'data-center' read as words); None
    when it does not name it or the series' geography is not one the question asks about."""
    text = re.sub(r"(?<=[A-Za-z])-(?=[A-Za-z])", " ", _anchor_markup(question))
    from .official_data import data_api
    api = data_api()
    asked = set(api.catalog.query_geographies(text)) if api is not None else set()
    geography = _anchor_row_geography(row)
    if asked and geography and geography not in asked:
        return None
    spans = _anchor_metric_spans(text, row)
    if not spans:
        return None
    start = min(begin for begin, _end in spans)
    return sum(1 for match in _QUESTION_CLAUSE_RE.finditer(text) if match.end() <= start), start


def _anchor_title_windows(statement: str, row: Dict[str, Any]) -> List[Tuple[int, int]]:
    """Spans naming the series by its distinctive English title words in any order
    ('the 10-year minus 3-month Treasury spread' for '10-Year Treasury Constant Maturity Minus
    3-Month Treasury Constant Maturity'). A single distinctive word must be a long one."""
    from .official_data import data_api
    api = data_api()
    entry = _anchor_catalog_entry(row)
    geography = _anchor_row_geography(row)
    name, aliases = (api.catalog.GEOGRAPHIES.get(geography, (geography, ())) if api is not None else ("", ()))
    places = {token for term in (name, *aliases) for token, _s, _e in _anchor_tokens(str(term or ""))}
    tokens = _anchor_tokens(statement)
    spans: List[Tuple[int, int]] = []
    for title in {str(row.get("title") or ""), str(getattr(entry, "title", "") or "")}:
        distinct = {token for token, _s, _e in _anchor_tokens(title)
                    if token not in _ANCHOR_TITLE_FILLER and token not in places and len(token) > 1}
        if not distinct or len(distinct) == 1 and not (next(iter(distinct)).isalpha()
                                                       and len(next(iter(distinct))) >= 6):
            continue
        for first, (token, start, _end) in enumerate(tokens):
            if token not in distinct:
                continue
            covered = set()
            for last in range(first, min(len(tokens), first + len(distinct) + 4)):
                word = tokens[last][0]
                if (word not in distinct and word not in _ANCHOR_TITLE_JOINERS
                        or last > first and not _ANCHOR_WINDOW_GAP_RE.fullmatch(
                            statement[tokens[last - 1][2]:tokens[last][1]])):
                    break
                covered.add(word)
                if covered >= distinct:
                    span = (start, tokens[last][2])
                    if not any(span[0] < e and s < span[1] for s, e in spans):
                        spans.append(span)
                    break
    return spans


def _anchor_identifier_spans(statement: str, row: Dict[str, Any]) -> List[Tuple[int, int]]:
    """The bare native id ('UNRATE', 'T10Y3M') and catalog acronyms written in capitals ('CPI')
    match their exact case; catalog terms with digits ('10y3m', 'u-6') match in any case."""
    native = row["series"].partition(":")[2].partition("#")[0]
    exact = {native} if len(native) >= 3 else set()
    loose = set()
    for keyword in getattr(_anchor_catalog_entry(row), "keywords", ()) or ():
        keyword = str(keyword)
        if not re.fullmatch(r"[A-Za-z0-9-]+", keyword):
            continue
        if re.search(r"\d", keyword):
            loose.add(keyword)
        elif len(keyword) <= 5:
            exact.add(keyword.upper())
    spans: List[Tuple[int, int]] = []
    for terms, flags in ((exact, 0), (loose, re.I)):
        for term in sorted(terms, key=len, reverse=True):
            for match in re.finditer(r"(?<![A-Za-z0-9_:/.])" + re.escape(term) + r"(?![A-Za-z0-9_])",
                                     statement, flags):
                if not any(match.start() < end and start < match.end() for start, end in spans):
                    spans.append(match.span())
    return spans


def _anchor_singular(token: str) -> str:
    """'prices' -> 'price', 'semiconductors' -> 'semiconductor'; 'gas', 'us', 'business' unchanged."""
    return token[:-1] if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")) else token


# A price-index acronym among a series' catalog keywords names the same thing as its spelled-out
# prices (the catalog already pairs 'cpi' with 'consumer prices' on most CPI entries).
_ANCHOR_ACRONYM_KEYWORDS = {"cpi": "consumer prices", "ppi": "producer prices"}


def _anchor_keyword_windows(statement: str, row: Dict[str, Any]) -> List[Tuple[int, int]]:
    """Spans naming the series by a multi-word catalog keyword in natural word order and number:
    'consumer price inflation' for 'consumer prices', 'industrial production of semiconductors'
    and 'semiconductor industrial production' for 'semiconductor production'.

    Every keyword word (singular or plural, any order) appears in one run joined only by
    'of'/'the' and the series' own title words; a negation, conjunction, number word or place
    never sits inside the run, so the remainder checks still see it.
    """
    entry = _anchor_catalog_entry(row)
    keywords = [str(keyword) for keyword in getattr(entry, "keywords", ()) or ()
                if re.fullmatch(r"[A-Za-z][A-Za-z -]*[A-Za-z]", str(keyword))]
    keywords += [_ANCHOR_ACRONYM_KEYWORDS[k] for k in keywords if k in _ANCHOR_ACRONYM_KEYWORDS]
    if not keywords:
        return []
    from .official_data import data_api
    api = data_api()
    geography = _anchor_row_geography(row)
    name, aliases = (api.catalog.GEOGRAPHIES.get(geography, (geography, ())) if api is not None else ("", ()))
    places = {_anchor_singular(token) for term in (name, *aliases)
              for token, _s, _e in _anchor_tokens(str(term or ""))}
    titles = {str(row.get("title") or ""), str(getattr(entry, "title", "") or "")}
    fillers = {_anchor_singular(token) for title in titles for token, _s, _e in _anchor_tokens(title)}
    fillers = {token for token in fillers if token not in places and not _ANCHOR_BLOCKERS_RE.fullmatch(token)}
    fillers |= {"of", "the"}
    tokens = [(_anchor_singular(token), start, end) for token, start, end in _anchor_tokens(statement)]
    spans: List[Tuple[int, int]] = []
    for keyword in keywords:
        words = {_anchor_singular(token) for token, _s, _e in _anchor_tokens(keyword)}
        if len(words) < 2:
            continue
        for first, (token, start, _end) in enumerate(tokens):
            if token not in words:
                continue
            covered = set()
            for last in range(first, min(len(tokens), first + len(words) + 3)):
                word = tokens[last][0]
                if (word not in words and word not in fillers
                        or last > first and not _ANCHOR_WINDOW_GAP_RE.fullmatch(
                            statement[tokens[last - 1][2]:tokens[last][1]])):
                    break
                covered.add(word)
                if covered >= words:
                    span = (start, tokens[last][2])
                    if not any(span[0] < e and s < span[1] for s, e in spans):
                        spans.append(span)
                    break
    return spans


def _anchor_metric_spans(statement: str, row: Dict[str, Any]) -> List[Tuple[int, int]]:
    """Where ``statement`` names the series; overlapping names merge into one span ('10-year
    breakeven inflation expectations' joins the title words and the keyword)."""
    folded = statement.casefold()
    found: List[Tuple[int, int]] = []
    for label in [row["series"], *_anchor_metric_labels(row)]:
        key = label.casefold()
        cjk = bool(re.search(r"[㐀-鿿]", key))
        # A name ending in 通胀 ('整体通胀') never takes the 通胀 of 通胀预期 (inflation
        # expectations, a sibling qualifier the remainder check must still see).
        pattern = (re.escape(key) + ("(?!预期)" if key.endswith("通胀") else "") if cjk
                   else r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])")
        found.extend(match.span() for match in re.finditer(pattern, folded))
    found += [*_anchor_identifier_spans(statement, row), *_anchor_title_windows(statement, row),
              *_anchor_keyword_windows(statement, row)]
    spans: List[Tuple[int, int]] = []
    for start, end in sorted(found):
        if spans and start < spans[-1][1]:
            spans[-1] = (spans[-1][0], max(end, spans[-1][1]))
        else:
            spans.append((start, end))
    if not spans:
        # Legacy rule: every ≥4-letter title word appears in the statement.
        words = set(re.findall(r"[a-z]{4,}", str(row.get("title") or "").lower()))
        if words and words.issubset(set(re.findall(r"[a-z]{4,}", folded))):
            spans = [m.span() for m in re.finditer(r"[a-z]{4,}", folded) if m.group(0) in words]
    return spans


# Words naming a sibling series of the same family (core vs headline prices, real vs nominal,
# the lower vs upper target limit, market-implied or forward rates, inflation expectations vs
# realized inflation, the ECB's main refinancing or marginal lending rate vs its deposit facility
# rate, the Fed's discount (primary credit) rate or interest on reserve balances vs its policy
# rate). A statement may use one only when the anchored series' own names carry it ('real' also
# fits a constant-price series).
_ANCHOR_QUALIFIER_RE = re.compile(
    r"(?<![A-Za-z])(?:core|supercore|real|nominal|underlying|trimmed|median|sticky|youth|teen|teenage|"
    r"inflation[\s-]indexed|tips|implied|futures|forward|expectations?|refinancing|marginal[\s-]+lending|"
    r"discount|primary[\s-]+credit|reserve[\s-]+balances?|iorb|"
    r"(?:upper|lower)\s+(?:bound|limit|end))(?![A-Za-z-])"
    r"|核心|名义|青年|广义|隐含|期货|远期|上限|下限|通胀预期|再融资|边际贷款|边际借贷|贴现|准备金余额|实际(?![值公发数读])",
    re.I,
)
# Words naming a component or a population subgroup of a headline series (services or food
# prices, the commercial sector, Black or female workers, wage earners): allowed, like the
# sibling qualifiers, only when the anchored series' own names carry them (singular or plural).
_ANCHOR_SUBSET_RE = re.compile(
    r"(?<![A-Za-z])(?:services?|goods|food|energy|shelter|rents?|housing|medical|gasoline|"
    r"residential|commercial|industrial|black|white|hispanic|latino|asian|women|men|female|male|"
    r"veterans?|graduates?|wage[\s-]+earners?|clerical|part[\s-]time|full[\s-]time)(?![A-Za-z-])"
    r"|服务|食品|能源|住房|房租|女性|男性|黑人|白人",
    re.I,
)
# Other price measures beside a generic inflation name ('PCE headline inflation', '美国PPI整体通胀'):
# allowed only when the anchored series' own names carry the measure, by its acronym or in full.
_ANCHOR_PRICE_MEASURES = tuple(
    (re.compile(pattern, re.I), re.compile(pattern)) for pattern in (
        r"(?<![A-Za-z])(?:pce|personal[\s-]+consumption[\s-]+expenditures?)(?![A-Za-z])|个人消费支出",
        r"(?<![A-Za-z])(?:ppi|producer[\s-]+prices?|wholesale)(?![A-Za-z])|生产者价格|出厂价格|批发",
    )
)


def _anchor_foreign_qualifier(remainder: str, row: Dict[str, Any]) -> bool:
    names = " | ".join(_anchor_metric_labels(row)).casefold()
    real_terms = bool(re.search(r"\breal\b|constant\s+prices|chained|实际",
                                " ".join(str(row.get(key) or "") for key in ("title", "title_zh", "units")), re.I)
                      or re.search(r"_KD(?:_|/|$)", row["series"]))
    for match in _ANCHOR_QUALIFIER_RE.finditer(remainder):
        term = re.sub(r"[\s-]+", " ", match.group(0).casefold())
        if term in ("real", "实际") and real_terms:
            continue
        side = re.fullmatch(r"(upper|lower) (?:bound|limit|end)", term)  # 'upper bound' is the 'Upper Limit'
        pattern = (side[1] + r"[\s-]+(?:bound|limit|end)" if side else "expectations?" if term.startswith("expectation")
                   else re.escape(term).replace(r"\ ", r"[\s-]+"))
        if not re.search(r"(?<![a-z])" + pattern + r"(?![a-z])", names):
            return True
    for match in _ANCHOR_SUBSET_RE.finditer(remainder):
        word = _anchor_singular(re.sub(r"[\s-]+", " ", match.group(0).casefold()))
        if not re.search(r"(?<![a-z])" + re.escape(word).replace(r"\ ", r"[\s-]+") + r"s?(?![a-z])", names):
            return True
    return any(mention.search(remainder) and not carried.search(names) for mention, carried in _ANCHOR_PRICE_MEASURES)


def _anchor_settlement_sentence(anchor: Dict[str, Any], zh: bool, row: Any = None) -> str:
    """Canonical settlement clause appended to an admitted binary's resolution criteria
    (the anchored ``row`` names a US federal fiscal year by its label, 'for FY2026')."""
    from .official_data import data_api
    api = data_api()
    units = str(anchor.get("units") or "")
    threshold = api.format_value(anchor["threshold"], units) if api is not None else str(anchor["threshold"])
    percent = bool(api and api.is_percent_units(units))
    period = _anchor_target(str(anchor["period"]), str(anchor.get("frequency") or ""), row)[1]
    scaled = api.scaled_value(anchor["threshold"], units, "zh" if zh else "en") if api is not None else ""
    if zh:
        return (f"官方判定：{anchor['series']} {anchor['comparator']} {threshold}"
                + (f"（{scaled}）" if scaled else "") + ("" if percent else f"（单位 `{units}`）")
                + f"，观察期 {period}。")
    return (f"Official resolution: {anchor['series']} {anchor['comparator']} {threshold}"
            + ("" if percent else f" {units}") + (f" ({scaled})" if scaled else "") + f" for {period}.")


def _strip_anchor_settlement(criteria: str, anchor: Dict[str, Any], row: Any = None) -> str:
    for zh in (False, True):
        criteria = criteria.replace(_anchor_settlement_sentence(anchor, zh, row), "")
    return criteria.strip()


def _anchor_markup(text: str) -> str:
    """Drop Markdown emphasis/code marks; underscores inside identifiers (debt_to_penny) stay.
    Full-width symbols and digits ('＜3％') read as ASCII."""
    text = re.sub(r"[`*]+", "", str(text or "").translate(_ANCHOR_FULLWIDTH))
    return re.sub(r"(?<![A-Za-z0-9])_+|_+(?![A-Za-z0-9])", "", text).replace("−", "-").strip()


def _anchor_threshold_equal(value: Optional[float], threshold: float) -> bool:
    return value is not None and math.isclose(value, threshold, rel_tol=1e-9, abs_tol=1e-12)


def _anchor_criteria_ok(criteria: str, anchor: Dict[str, Any], row: Dict[str, Any]) -> bool:
    """Exactly one canonical clause '<series> <cmp> <threshold> [units] [in|for|on] <period>'.

    The comparator is a symbol or a word ('fred:FEDFUNDS 于2027年12月低于3%'). Framing
    ('Resolves YES if', '当 … 时') and source attributions ('(source: FRED)', ', per the
    BLS release') are allowed; any other number, comparator, negation or condition is not.
    """
    text = re.sub(r"https?://\S+", " ", _anchor_markup(criteria))
    # Chinese prose sets the id between CJK characters without spaces ('若fred:FEDFUNDS于…');
    # only a Latin identifier character extends the id.
    identity = re.compile(r"(?<![A-Za-z0-9_:/])" + re.escape(row["series"])
                          + r"(?![A-Za-z0-9_#/-]|\.[A-Za-z0-9_])", re.I)
    if len(identity.findall(text)) != 1:
        return False
    id_match = identity.search(text)
    head = text[:id_match.start()].strip()
    framing = _ANCHOR_FRAMING_RE.match(head)
    rest_of_head = head[framing.end():] if framing else head
    if (re.search(r"\d|[<>=≥≤]", rest_of_head) or _ANCHOR_BLOCKERS_RE.search(rest_of_head)
            or len(rest_of_head.split()) > 6):
        return False
    tail = text[id_match.end():]
    target = _anchor_target(anchor["period"], row["frequency"], row)
    if _anchor_end_of_month(row):
        tail = _anchor_month_end_text(tail, target)
    comparisons = _anchor_comparisons(tail, row["units"])
    # A comparison's own digits (a 4-digit threshold, '2017' in its units) are not periods.
    periods = _anchor_periods(_anchor_blank(tail, [(s, e) for s, e, *_ in comparisons]), target[0] == "FY")
    if len(comparisons) != 1 or len(periods) != 1:
        return False
    start, end, comparator, value, unit_ok = comparisons[0]
    p_start, p_end, key, lead = periods[0]
    if (comparator != anchor["comparator"] or not unit_ok or not _anchor_threshold_equal(value, anchor["threshold"])
            or lead or key is None or not _anchor_mention_matches(key, target)):
        return False
    first, last = (start, p_end) if p_start > start else (p_start, end)
    if p_start > start:
        between = tail[end:p_start]
        joiners = (r"\s*(?:[,，]\s*)?(?:(?:in|for|on|during|at)\s+(?:the\s+)?(?:period\s+)?|"
                   r"(?:于|在|观察期\s*[:：]?)\s*)?(?:[(（]\s*)?")
    else:
        between = tail[p_end:start]
        joiners = (r"\s*(?:[)）]\s*)?(?:在|于)?\s*(?:的?(?:月度|月均|季度|年度)?(?:数值|值|读数))?\s*"
                   r"(?:(?:(?:monthly|quarterly|annual)\s+)?(?:value|reading)\s+)?(?:(?:is|will\s+be)\s+)?")
    lead_text = tail[:first]
    if not re.fullmatch(joiners, between, re.I) or not re.fullmatch(
            r"\s*(?:[)）:：]\s*)?(?:(?:在|于)\s*)?(?:(?:in|for|on|during|at)\s+)?(?:[(（]\s*)?"
            r"(?:(?:the\s+)?(?:value|reading)\s+)?(?:(?:is|will\s+be)\s+)?", lead_text, re.I):
        return False
    after = _ANCHOR_PROVIDER_DIGITS_RE.sub("Data", tail[last:]).strip()
    # '时' closes a '当/若 … 时' condition clause before the resolution phrase.
    after = re.sub(r"^[)）]?\s*时?\s*", "", after)
    yes = _ANCHOR_YES_LEAD_RE.match(after)
    if yes:
        after = after[yes.end():].strip()
    if not after or re.fullmatch(r"[.!。;；]?", after):
        return True
    if re.search(r"\d|[<>=≥≤]", after) or _ANCHOR_BLOCKERS_RE.search(_ANCHOR_SOURCE_SUFFIX_RE.sub("", after, 1)):
        return False
    return bool(_ANCHOR_SOURCE_SUFFIX_RE.match(after) or _ANCHOR_YES_SUFFIX_RE.match(after))


def _anchor_statement_ok(statement: str, anchor: Dict[str, Any], row: Dict[str, Any]) -> bool:
    """The prose proposition is the anchored one: same metric, one comparison with the
    anchor's comparator (symbol or word, EN/ZH) and threshold, the anchor period, the
    series geography, and no negation, alternative, condition, second number or a
    qualifier naming a sibling series ('core', 'real', 'lower limit')."""
    text = _anchor_markup(statement)
    metric = _anchor_metric_spans(text, row)
    if not metric:
        return False
    from .official_data import data_api
    api = data_api()
    geographies = set(api.catalog.query_geographies(_anchor_blank(text, metric))) if api is not None else set()
    geography = _anchor_row_geography(row)
    if geographies and geographies != {geography}:
        return False
    comparisons = _anchor_comparisons(text, row["units"])
    if len(comparisons) != 1:
        return False
    start, end, comparator, value, unit_ok = comparisons[0]
    if (comparator != anchor["comparator"] or not unit_ok
            or not _anchor_threshold_equal(value, anchor["threshold"])):
        return False
    remainder = _anchor_blank(text, [*metric, (start, end)])
    remainder = _anchor_blank(remainder, _anchor_units_spans(remainder, row["units"]))
    target = _anchor_target(anchor["period"], row["frequency"], row)
    if _anchor_end_of_month(row):
        remainder = _anchor_month_end_text(remainder, target)
    periods = _anchor_periods(remainder, target[0] == "FY")
    if not periods or any(lead or key is None or not _anchor_mention_matches(key, target)
                          for _s, _e, key, lead in periods):
        return False
    remainder = _anchor_blank(remainder, [(s, e) for s, e, _k, _l in periods])
    if api is not None and geography:
        name, aliases = api.catalog.GEOGRAPHIES.get(geography, (geography, ()))
        short = {"USA": ("U.S.A.", "U.S.", "US"), "GBR": ("U.K.", "UK")}.get(geography, ())
        for term in sorted({name, *aliases, *short, geography}, key=len, reverse=True):
            remainder = re.sub(r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])", " ", remainder,
                               flags=0 if term in short else re.I)
    remainder = _ANCHOR_PROVIDER_DIGITS_RE.sub("Data", remainder)
    return not (re.search(r"\d|[<>=≥≤]", remainder) or _ANCHOR_BLOCKERS_RE.search(remainder)
                or _anchor_foreign_qualifier(remainder, row))


def _data_anchor_matches_binary(anchor: Dict[str, Any], binary: Dict[str, Any], official_data: Any) -> bool:
    """Admit optional anchors only when the displayed proposition is unambiguous.

    The shared helper checks the dataset; this boundary also binds the model's
    threshold to its prose. The criterion must state the canonical clause for the
    anchored series; the statement must state the same proposition in natural
    language (EN or ZH). Anything ambiguous keeps its forecast but loses automatic
    anchoring rather than acquiring a different settlement rule.
    """
    rows = official_series_rows(official_data)
    row = next((r for r in rows if r["series"] == anchor["series"]), None)
    if row is None:
        return False
    try:
        criteria = str(binary.get("resolution_criteria") or "")
        return ((_anchor_criteria_ok(criteria, anchor, row)
                 or _anchor_criteria_ok(_strip_anchor_settlement(criteria, anchor, row), anchor, row))
                and _anchor_statement_ok(str(binary.get("statement") or ""), anchor, row))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _normalize_binaries(items: Any, *, start_index: int = 1,
                        allowed_themes: Optional[List[str]] = None,
                        market_lookup: Optional[Dict[str, float]] = None,
                        official_data: Optional[Dict[str, Any]] = None,
                        language: str = "English") -> List[Dict[str, Any]]:
    """Clamp/round each probability INDEPENDENTLY (no sum-normalization), dedup by
    statement, attach an objective-criteria quality flag. Drops rows missing a
    statement or a numeric probability.

    RPT-6: ``allowed_themes`` 给出时未知主题被钳到末位（历史三元组下逐字节等价于旧
    「非法→intersection」行为）；未给出时保留模型原话（小写），主题不再被硬编码扭曲。
    XRUN-1(a): 每条预测附带 ``source`` 溯源字段（缺省 'research-prior'），让每个概率
    可追责到具体模拟信号或研究先验。
    预测市场锚点：模型给出 market_anchor 时校验并保留 {market_id, implied_yes_prob,
    divergence}；``market_lookup``（market_id→隐含概率，来自我们抓取的快照）命中时
    以快照价回填 implied_yes_prob（不盲信模型转录），divergence 一律由本函数确定性
    计算（本预测概率 − 市场隐含概率）。锚点非法/缺失时不加字段（degrade-safe）。"""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        stmt = str(it.get("statement") or "").strip()
        p = _coerce_float(it.get("probability"))
        if not stmt or p is None or _is_circular_market_forecast(
                stmt, it.get("resolution_criteria")):
            continue
        key = _binary_key(stmt)
        if not key or key in seen:
            continue
        seen.add(key)
        p = max(0.02, min(0.98, p))
        rc = str(it.get("resolution_criteria") or "")
        hy_raw = it.get("horizon_year")
        try:
            hy = int(float(hy_raw)) if hy_raw not in (None, "") else None
        except (TypeError, ValueError):
            hy = None
        theme = str(it.get("theme") or "").strip().lower()
        if allowed_themes:
            if theme not in allowed_themes:
                theme = allowed_themes[-1]
        elif not theme:
            theme = "general"
        row = {
            "id": str(it.get("id") or f"F{start_index + len(out)}"),
            "statement": stmt,
            "probability": round(p, 2),
            "resolution_criteria": rc,
            "resolution_source": str(it.get("resolution_source") or ""),
            "theme": theme,
            "horizon_year": hy,
            "base_rate_anchor": str(it.get("base_rate_anchor") or ""),
            "adjustment_rationale": str(it.get("adjustment_rationale") or ""),
            "source": str(it.get("source") or "").strip() or "research-prior",
            "proposition_id": (
                re.sub(
                    r"[^a-z0-9]+", "-",
                    str(it.get("proposition_id") or "").lower(),
                ).strip("-")
                or "forecast-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
            ),
            # The statement and criterion are rendered side by side as one
            # resolvable row. Accept a date/metric stated once in either field,
            # while still preserving the criterion verbatim.
            "criteria_sharp": bool(validate_resolution_criteria(
                f"{stmt} {rc}").get("sharp")),
        }
        membership = it.get("scenario_membership")
        if isinstance(membership, dict):
            raw_derivable = membership.get("derivable")
            raw_yes_scenarios = membership.get("yes_scenarios")
            membership_errors: List[str] = []
            if type(raw_derivable) is not bool:
                membership_errors.append("derivable must be a JSON boolean")
            if not isinstance(raw_yes_scenarios, list):
                membership_errors.append("yes_scenarios must be a list")
                raw_yes_scenarios = []
            yes_scenarios = [
                name.strip()
                for name in raw_yes_scenarios
                if isinstance(name, str) and name.strip()
            ]
            if len(yes_scenarios) != len(raw_yes_scenarios):
                membership_errors.append(
                    "yes_scenarios entries must be non-empty strings"
                )
            if len(set(yes_scenarios)) != len(yes_scenarios):
                membership_errors.append("yes_scenarios contains duplicates")
            discarded_yes_scenarios: List[str] = []
            if (
                raw_derivable is False
                and not membership_errors
                and yes_scenarios
            ):
                # ``derivable=false`` is the conservative, non-binding choice:
                # no scenario bin is permitted to overwrite this independent
                # binary probability.  Some model responses still emit related
                # (but not fully determining) scenario names.  Preserve those
                # suggestions for diagnostics while canonicalizing the active
                # contract to the prompt-mandated empty list.  Structurally
                # malformed declarations continue to fail closed below.
                discarded_yes_scenarios = list(yes_scenarios)
                yes_scenarios = []
            row["scenario_membership"] = {
                # Do not coerce strings such as ``"false"`` with ``bool()``:
                # that silently turns an invalid model payload into permission
                # to overwrite the binary probability from scenario bins.
                "derivable": (
                    raw_derivable if type(raw_derivable) is bool else None
                ),
                "yes_scenarios": yes_scenarios,
            }
            if discarded_yes_scenarios:
                row["scenario_membership"]["discarded_yes_scenarios"] = (
                    discarded_yes_scenarios
                )
            if membership_errors:
                row["scenario_membership"]["validation_errors"] = membership_errors
        elif membership is not None:
            # Preserve an explicit invalid declaration as a rejected contract;
            # dropping it would re-enable the legacy heuristic reconciliation
            # path and hide the model's schema violation.
            row["scenario_membership"] = {
                "derivable": None,
                "yes_scenarios": [],
                "validation_errors": ["scenario_membership must be an object"],
            }
        anchor = it.get("market_anchor")
        if isinstance(anchor, dict):
            mid = str(anchor.get("market_id") or "").strip()
            ip = _coerce_float(anchor.get("implied_yes_prob"))
            if market_lookup and mid in market_lookup:
                ip = _coerce_float(market_lookup.get(mid))  # 以我们的快照价为准
            if mid and ip is not None and 0.0 <= ip <= 1.0:
                row["market_anchor"] = {
                    "market_id": mid,
                    "implied_yes_prob": round(ip, 4),
                    "divergence": round(row["probability"] - ip, 4),
                }
        if official_data and isinstance(it.get("data_anchor"), dict):
            from .official_data import validate_data_anchor
            data_anchor = validate_data_anchor(it["data_anchor"], official_data)
            if data_anchor is not None and _data_anchor_matches_binary(data_anchor, it, official_data):
                _admit_data_anchor(row, data_anchor, official_data, language)
        out.append(row)
    return out


def _admit_data_anchor(row: Dict[str, Any], anchor: Dict[str, Any], official_data: Any, language: str) -> None:
    """Attach an admitted anchor: display-safe latest, outside view, canonical settlement.

    ``latest_value``/``latest_date`` come from the same helper as the data pack and
    charts (complete historical observations only); the probability is never changed.
    ``auto_resolvable`` is False for series the data layer never settles automatically
    (official_auto_resolvable), so the resolution monitor can leave them to manual review.
    """
    series = next(r for r in official_series_rows(official_data) if r["series"] == anchor["series"])
    latest = official_latest_observed(series)
    anchor["latest_value"], anchor["latest_date"] = (latest["value"], latest["date"]) if latest else (None, "")
    anchor["auto_resolvable"] = official_auto_resolvable(series)
    base_rate = official_empirical_base_rate(series, anchor)
    if base_rate is not None:
        anchor["empirical_base_rate"] = base_rate
    row["data_anchor"] = anchor
    zh = str(language or "").lower().startswith(("zh", "chinese")) or "中文" in str(language or "")
    sentence = _anchor_settlement_sentence(anchor, zh, series)
    if sentence not in row["resolution_criteria"]:
        row["resolution_criteria"] = (row["resolution_criteria"].rstrip() + " " + sentence).strip()
        row["criteria_sharp"] = bool(validate_resolution_criteria(
            f"{row['statement']} {row['resolution_criteria']}").get("sharp"))


def _binary_quality(binaries: List[Dict[str, Any]], *, min_count: int,
                    themes_expected: Optional[List[str]] = None) -> Dict[str, Any]:
    """Conviction + objectivity scorecard for a binary set (QUALITY-OPT A3/A4).

    Flags the two failure modes the brief calls out: hedging (everything near 0.5)
    and vague criteria. ``passed`` is the publish gate.
    RPT-6: 主题统计改为「配置的期望主题（补零）+ 实际观察到的主题」，不再硬编码三元组。
    """
    n = len(binaries)
    probs = [b["probability"] for b in binaries]
    mean = sum(probs) / n if n else 0.0
    std = math.sqrt(sum((p - mean) ** 2 for p in probs) / n) if n else 0.0
    midband = sum(1 for p in probs if 0.40 <= p <= 0.60)
    conviction = sum(1 for p in probs if p >= 0.70 or p <= 0.30)
    # 信任 _normalize_binaries 落盘的 criteria_sharp 标记（那里已按「陈述+判定标准
    # 任一字段含日期/指标即可」规则计算）；此处不重算，门控/降级行为与存量跑保持一致。
    sharp = sum(1 for b in binaries if b.get("criteria_sharp"))
    themes: Dict[str, int] = {str(t): 0 for t in (themes_expected or [])}
    for b in binaries:
        t = str(b.get("theme") or "")
        if t:
            themes[t] = themes.get(t, 0) + 1
    # RQ-2：主题基数（实际出现的不同主题数）。二元集合全部塌成同一主题（如 _normalize_binaries
    # 把未知主题钳到残余主题、或模型对所有条目复读同一 theme）= 主题多样性丢失，交付物看似
    # 覆盖多个驱动力实则单一。基数<=1 时记诊断标记（不阻断发布门，避免回归既有合法单主题跑）。
    theme_cardinality = sum(1 for _t, _c in themes.items() if _c > 0)
    midband_share = (midband / n) if n else 1.0
    passed = (
        n >= min_count
        and std >= 0.12               # genuine spread, not all-hedged
        and midband_share <= 0.40     # not a wall of coin-flips
        and conviction >= 3           # at least a few committed calls
        and sharp >= int(0.8 * n)     # mostly objective criteria
    )
    issues = []
    if n < min_count:
        issues.append(f"only {n} binaries (< {min_count})")
    if std < 0.12:
        issues.append(f"probability spread too low (stdev {std:.2f}) — hedging")
    if midband_share > 0.40:
        issues.append(f"{midband}/{n} forecasts in 0.40-0.60 — under-committed")
    if conviction < 3:
        issues.append("fewer than 3 high-conviction calls (p>=0.70 or <=0.30)")
    if sharp < int(0.8 * n):
        issues.append(f"only {sharp}/{n} have objective metric+number+date criteria")
    if n > 1 and theme_cardinality <= 1:
        issues.append("all forecasts share a single theme — no thematic spread")
    out = {
        "count": n, "prob_stdev": round(std, 3), "midband_share": round(midband_share, 3),
        "conviction_count": conviction, "sharp_criteria_count": sharp, "themes": themes,
        "theme_cardinality": theme_cardinality,
        "passed": bool(passed), "issues": issues,
    }
    # Official-data outside view (fix contract §1.8): flag, never adjust, a model
    # probability more than 25 pp from the empirical base rate of its data anchor. A rate
    # that pools the seasons of a series without seasonal adjustment is shown with that
    # caveat but is no yardstick for a divergence flag.
    divergent = []
    for b in binaries:
        anchor = b.get("data_anchor") if isinstance(b.get("data_anchor"), dict) else {}
        base = anchor.get("empirical_base_rate")
        if (isinstance(base, dict) and isinstance(base.get("p"), (int, float))
                and base.get("seasonal_basis") != "all_start_months"):
            gap = round(b["probability"] - base["p"], 4)
            if abs(gap) > _BASE_RATE_DIVERGENCE:
                divergent.append({"id": str(b.get("id") or ""), "probability": b["probability"],
                                  "empirical_p": base["p"], "divergence": gap})
    if divergent:
        out["base_rate_divergence"] = divergent
        issues.append(f"{len(divergent)} data-anchored forecast(s) differ from the official-data empirical "
                      f"base rate by more than {_BASE_RATE_DIVERGENCE * 100:.0f} pp: "
                      + ", ".join(d["id"] for d in divergent))
    return out


_BASE_RATE_DIVERGENCE = 0.25


# --------------------------------------------- PM-2: deterministic market anchoring
# 此前市场锚点走「模型自愿在 market_anchor 里给 market_id」的 opt-in 路径，取证 0/13 与
# 0/11 条二元被锚定——模型几乎从不主动转录 id。PM-2 改为**确定性**：先跑一次批处理 LLM
# 匹配（预测陈述表 × 相关性门控后的市场表[含 endDate]），每条预测得 {market_id|null,
# resolution_equivalence: exact|near|loose, confidence}；再由本模块确定性回填 rich
# market_anchor（question/implied/price_at_research/url/endDate/divergence，隐含概率一律
# 以我们的快照价为准、divergence 本地计算）。匹配调用失败/无市场 → 不加锚点（今日行为）。
_MARKET_MATCH_INSTRUCTIONS = (
    "You are matching binary forecasts to real prediction markets for CALIBRATION. Below is a "
    "numbered list of binary (yes/no) FORECASTS and a list of live prediction MARKETS (each with "
    "an implied YES probability and a market end date). For EACH forecast decide whether ANY "
    "listed market resolves to the SAME real-world event on a compatible timeframe.\n"
    "Return JSON ONLY: {\"matches\": [ {\"forecast_id\": \"F1\", "
    "\"market_id\": \"<id copied verbatim from the MARKETS list, or null>\", "
    "\"resolution_equivalence\": \"exact|near|loose\", \"confidence\": 0.0-1.0} , ... ] }\n"
    "RULES: market_id MUST be copied verbatim from the MARKETS list or be null when nothing "
    "matches — never invent an id. resolution_equivalence = exact (same metric, threshold AND "
    "window), near (same event, slightly different threshold/date), loose (related theme only). "
    "A forecast matches at most ONE market; a market may be cited by several forecasts."
)

# 10pp 分歧有界重述：锚定后 |model_p − market_p| > 0.10 且理由未提及市场的预测，做一次
# 批处理重述——模型须**要么**把概率移向市场、**要么**保留分歧，但两种情形都必须在
# adjustment_rationale 里显式引用市场隐含概率并解释（绝不静默移动概率）。
_MARKET_DIVERGENCE_INSTRUCTIONS = (
    "You are reconciling forecasts against live prediction-market prices. Each item below is a "
    "binary forecast whose probability diverges from a matched market's implied probability by "
    "MORE than 10 percentage points, and whose rationale does NOT yet address that market. For "
    "EACH item decide deliberately: EITHER move your probability toward the market, OR keep your "
    "divergence — but in BOTH cases you MUST rewrite adjustment_rationale to explicitly cite the "
    "market's implied probability and explain the divergence (what the market is missing / "
    "mispricing, or why you now defer to it). Markets are calibration anchors, not ground truth.\n"
    "Return JSON ONLY: {\"revisions\": [ {\"id\": \"F1\", \"probability\": 0.02-0.98, "
    "\"adjustment_rationale\": \"...must mention the market and its implied probability...\"} , ... ] }"
)

_MARKET_EQUIVALENCE_RANK = {"exact": 3, "near": 2, "loose": 1}
# 理由「提及市场」的判据：命中关键词（market/Polymarket/市场/预测市场/implied）即算。
_MARKET_MENTION_RE = re.compile(r"market|polymarket|市场|預測|预测市场|implied", re.I)


def _market_end_date(market: Dict[str, Any]) -> str:
    """规整化市场快照用 end_date（见 prediction_markets），锚点对外用 endDate（camelCase）。"""
    return str((market or {}).get("end_date") or (market or {}).get("endDate") or "").strip()


def _rationale_cites_market(text: Any, anchor: Optional[Dict[str, Any]] = None) -> bool:
    """理由是否引用了市场——关键词命中，或文本里出现了市场隐含概率的百分数。Pure。"""
    t = str(text or "")
    if not t.strip():
        return False
    if _MARKET_MENTION_RE.search(t):
        return True
    if isinstance(anchor, dict):
        ip = _coerce_float(anchor.get("implied_yes_prob"))
        if ip is not None and re.search(rf"\b{int(round(ip * 100))}\s*%", t):
            return True
    return False


def _build_market_anchor(prob: Optional[float], market: Dict[str, Any], *,
                         equivalence: Optional[str] = None,
                         match_confidence: Optional[float] = None,
                         binary: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """确定性组装 rich market_anchor：隐含概率取我们的快照价，divergence 本地计算。

    price_at_research 记研究时点的快照价（与 implied_yes_prob 同源，供日后与实时价对比）。
    市场缺 id / 隐含概率非法 → None（不加锚点，degrade-safe）。"""
    mid = str((market or {}).get("market_id") or "").strip()
    ip = _coerce_float((market or {}).get("implied_yes_prob"))
    p = _coerce_float(prob)
    if not mid or ip is None or not (0.0 <= ip <= 1.0):
        return None
    anchor: Dict[str, Any] = {
        "market_id": mid,
        "question": str(market.get("question") or ""),
        "implied_yes_prob": round(ip, 4),
        "price_at_research": round(ip, 4),
        "divergence": round((p if p is not None else 0.0) - ip, 4),
    }
    url = str(market.get("url") or "").strip()
    if url:
        anchor["url"] = url
    ed = _market_end_date(market)
    if ed:
        anchor["endDate"] = ed
    eq = str(equivalence or "").strip().lower()
    if eq:
        anchor["resolution_equivalence"] = eq
    mc = _coerce_float(match_confidence)
    if mc is not None:
        anchor["match_confidence"] = round(max(0.0, min(1.0, mc)), 3)
    if isinstance(binary, dict):
        contract_text = (
            str(binary.get("statement") or "").strip()
            + "\n"
            + str(binary.get("resolution_criteria") or "").strip()
        )
        question = str(market.get("question") or "").strip()
        anchor.update({
            "forecast_proposition_id": str(binary.get("proposition_id") or "").strip(),
            "forecast_contract_sha256": hashlib.sha256(
                contract_text.encode("utf-8")
            ).hexdigest(),
            "market_question_sha256": hashlib.sha256(
                question.encode("utf-8")
            ).hexdigest(),
            "match_method": "bounded-semantic-equivalence-review",
        })
    return anchor


def anchor_binaries_to_markets(binaries: List[Dict[str, Any]], markets: Optional[List[Dict[str, Any]]],
                               llm, *, language: str = "English", max_markets: int = 24) -> int:
    """PM-2：一次批处理 LLM 匹配 + 确定性回填 market_anchor（就地改写 binaries）。返回锚定条数。

    只接受 resolution_equivalence 严格度 ≥ FORECAST_MARKET_ANCHOR_MIN_EQUIVALENCE（默认 near，
    即 exact/near 采纳、loose 丢弃）的匹配。旗标 FORECAST_MARKET_ANCHORING 关闭 / 无市场 /
    无二元 / 匹配调用异常或非法 JSON → 不加锚点（今日行为，degrade-safe）。"""
    if not _cfg("FORECAST_MARKET_ANCHORING", True):
        return 0
    bins = [b for b in (binaries or []) if isinstance(b, dict) and str(b.get("statement") or "").strip()]
    mkts = []
    for m in (markets or []):
        if not isinstance(m, dict):
            continue
        mid = str(m.get("market_id") or "").strip()
        ip = _coerce_float(m.get("implied_yes_prob"))
        if mid and ip is not None and 0.0 <= ip <= 1.0:
            mkts.append(m)
    if not bins or not mkts:
        return 0
    mkts = mkts[:max_markets]
    market_by_id = {str(m.get("market_id")).strip(): m for m in mkts}
    min_eq = str(_cfg("FORECAST_MARKET_ANCHOR_MIN_EQUIVALENCE", "near")).strip().lower()
    min_rank = _MARKET_EQUIVALENCE_RANK.get(min_eq, 2)
    flines = [f"[{b.get('id')}] {str(b.get('statement') or '')[:220]}" for b in bins]
    mlines = []
    for m in mkts:
        ip = _coerce_float(m.get("implied_yes_prob"))
        pct = f"{ip * 100:.0f}%" if ip is not None else "—"
        ed = _market_end_date(m)
        mlines.append(f"[{str(m.get('market_id')).strip()}] {str(m.get('question') or '')[:200]} "
                      f"(implied YES {pct}{', ends ' + ed if ed else ''})")
    user = (_MARKET_MATCH_INSTRUCTIONS + f"\n\nWrite any prose in {language}."
            + "\n\n[FORECASTS]\n" + "\n".join(flines)
            + "\n\n[MARKETS]\n" + "\n".join(mlines))
    try:
        raw = llm.chat_json(messages=[{"role": "user", "content": user}],
                            temperature=0.1, max_tokens=1500)
    except Exception as _me:  # noqa: BLE001 — 匹配失败 → 不加锚点（degrade-safe）
        logger.warning(f"预测市场匹配调用失败（忽略，不加锚点）: {_me}")
        return 0
    matches = raw.get("matches") if isinstance(raw, dict) else None
    if not isinstance(matches, list):
        return 0
    bin_by_id = {str(b.get("id")): b for b in bins}
    anchored = 0
    for mt in matches:
        if not isinstance(mt, dict):
            continue
        fid = str(mt.get("forecast_id") or "").strip()
        mid = str(mt.get("market_id") or "").strip()
        if not mid or mid.lower() == "null":
            continue
        b = bin_by_id.get(fid)
        m = market_by_id.get(mid)
        if b is None or m is None:
            continue
        eq = str(mt.get("resolution_equivalence") or "").strip().lower()
        if _MARKET_EQUIVALENCE_RANK.get(eq, 0) < min_rank:
            continue  # 严格度不足（如 loose）→ 不锚定
        anchor = _build_market_anchor(b.get("probability"), m, equivalence=eq,
                                      match_confidence=mt.get("confidence"), binary=b)
        if anchor:
            b["market_anchor"] = anchor  # 确定性回填（覆盖模型自愿转录的最小锚点）
            anchored += 1
    return anchored


def _stamp_market_influence(binary: Dict[str, Any], anchor: Dict[str, Any], *,
                            prior_p: float, revised_p: float) -> None:
    """LOOP-017 P0：把「市场把概率从 prior 移到 revised」盖成耐久的 market_influence 印章。

    与 market_anchor **分离**存放：对账（reconcile_forecast_contract）可依据命题/完整性
    弹出锚点，但影响印章必须存活——它是恢复被错误匹配移动的概率的唯一凭据，也是
    build_market_comparison ``influences`` 审计面的数据源。重复重述时保留最初的
    prior_probability（真实的未受影响值），只滚动 revised/修订时市场价。任何后续 pass
    都不得弹出此键（取证事故：锚点被弹出后，修订概率永久保留而市场溯源全部消失）。"""
    market_id = str(anchor.get("market_id") or "").strip()
    record: Dict[str, Any] = {
        "market_id": market_id,
        "market_question": str(anchor.get("question") or ""),
        "price_at_revision": _coerce_float(anchor.get("implied_yes_prob")),
        "prior_probability": round(prior_p, 4),
        "revised_probability": revised_p,
        "match_confidence": _coerce_float(anchor.get("match_confidence")),
        "resolution_equivalence": anchor.get("resolution_equivalence"),
    }
    existing = binary.get("market_influence")
    if (isinstance(existing, dict)
            and str(existing.get("market_id") or "").strip() == market_id
            and _coerce_float(existing.get("prior_probability")) is not None):
        record["prior_probability"] = round(
            float(_coerce_float(existing["prior_probability"])), 4)
    binary["market_influence"] = record


def enforce_market_divergence(binaries: List[Dict[str, Any]], llm, *,
                              language: str = "English") -> int:
    """PM-2 的 10pp 规则：锚定后 |divergence|>0.10 且理由未提及市场的预测做一次有界重述。

    重述须在理由中引用市场；否则不接受（绝不静默移动概率）。就地改写 binaries，重算
    market_anchor.divergence。旗标 FORECAST_MARKET_DIVERGENCE_REVISION 关闭 / 无候选 /
    调用异常 → 原样返回。返回被接受的重述条数。

    LOOP-017 P0（影响边界）：只有 ``match_confidence >=
    FORECAST_MARKET_DIVERGENCE_MIN_CONFIDENCE``（默认 0.6；缺失/None 一律不合格）的锚点
    才有**移动概率**的资格——低置信匹配仍可作为校准展示锚点，但绝不拉动发布概率。
    被采纳且确实移动了概率的重述会盖 ``market_influence`` 印章（见 _stamp_market_influence）。"""
    if not _cfg("FORECAST_MARKET_DIVERGENCE_REVISION", True):
        return 0
    min_conf = _coerce_float(_cfg("FORECAST_MARKET_DIVERGENCE_MIN_CONFIDENCE", 0.6))
    if min_conf is None:
        min_conf = 0.6
    candidates = []
    for b in (binaries or []):
        if not isinstance(b, dict):
            continue
        anchor = b.get("market_anchor")
        if not isinstance(anchor, dict):
            continue
        dv = _coerce_float(anchor.get("divergence"))
        if dv is None or abs(dv) <= 0.10:
            continue
        if _rationale_cites_market(b.get("adjustment_rationale"), anchor):
            continue  # 已解释分歧 → 无需重述
        mc = _coerce_float(anchor.get("match_confidence"))
        if mc is None or mc < float(min_conf):
            continue  # 低置信/无置信匹配 → 无移动概率资格（展示锚点照旧，见 docstring）
        candidates.append(b)
    if not candidates:
        return 0
    items = []
    for b in candidates:
        anchor = b["market_anchor"]
        ip = _coerce_float(anchor.get("implied_yes_prob"))
        items.append(
            f"[{b.get('id')}] statement: {str(b.get('statement') or '')[:220]}\n"
            f"    your probability: {b.get('probability')}; market implied YES: {ip}; "
            f"market question: {str(anchor.get('question') or '')[:160]}\n"
            f"    current rationale: {str(b.get('adjustment_rationale') or '')[:200]}")
    user = (_MARKET_DIVERGENCE_INSTRUCTIONS + f"\n\nWrite all text in {language}."
            + "\n\n[Divergent forecasts]\n" + "\n".join(items))
    try:
        raw = llm.chat_json(messages=[{"role": "user", "content": user}],
                            temperature=0.2, max_tokens=2048)
    except Exception as _re:  # noqa: BLE001 — 重述失败 → 保留原分歧（degrade-safe）
        logger.warning(f"预测市场分歧重述调用失败（忽略，保留原概率/理由）: {_re}")
        return 0
    revs = raw.get("revisions") if isinstance(raw, dict) else None
    if not isinstance(revs, list):
        return 0
    by_id = {str(b.get("id")): b for b in candidates}
    revised = 0
    for r in revs:
        if not isinstance(r, dict):
            continue
        b = by_id.get(str(r.get("id") or "").strip())
        if b is None:
            continue
        anchor = b.get("market_anchor")
        if not isinstance(anchor, dict):
            continue
        new_rat = str(r.get("adjustment_rationale") or "").strip()
        if not new_rat or not _rationale_cites_market(new_rat, anchor):
            continue  # 重述未引用市场 → 拒绝（绝不静默移动概率）
        b["adjustment_rationale"] = new_rat
        new_p = _coerce_float(r.get("probability"))
        if new_p is not None:
            new_p = round(max(0.02, min(0.98, new_p)), 2)
            prior_p = _coerce_float(b.get("probability"))
            b["probability"] = new_p
            ip = _coerce_float(anchor.get("implied_yes_prob"))
            if ip is not None:
                anchor["divergence"] = round(new_p - ip, 4)
            # LOOP-017 P0（影响耐久性）：重述确实移动了概率 → 盖 market_influence 印章。
            # 仅重写理由/概率未变的「保留分歧」情形不盖章（无需恢复凭据）。
            if prior_p is not None and abs(prior_p - new_p) > 1e-9:
                _stamp_market_influence(b, anchor, prior_p=prior_p, revised_p=new_p)
        revised += 1
    return revised


def build_market_comparison(binaries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """PM-2：从已锚定的二元预测汇出确定性的 market_comparison 负载（供落 market_comparison.json）。

    Pure / 无副作用：扫描 binaries 的 market_anchor，逐条给出 预测概率 vs 市场隐含概率、
    分歧、是否超 10pp、是否已在理由中引用市场。无锚定预测 → comparisons 为空列表。

    LOOP-017 P0（影响审计面）：额外汇出 ``influences``——每条被市场**实际移动过**概率的
    预测（market_influence 印章，含锚点其后被对账移除的情形），带 prior/revised/现值/
    修订时市场价/anchor_removed/probability_restored。无影响记录时两个键都不出现
    （缺失不造假，schema 向后兼容）。"""
    comps: List[Dict[str, Any]] = []
    for b in (binaries or []):
        if not isinstance(b, dict):
            continue
        anchor = b.get("market_anchor")
        if not isinstance(anchor, dict):
            continue
        p = _coerce_float(b.get("probability"))
        implied = _coerce_float(anchor.get("implied_yes_prob"))
        # Derived values MUST come from the two canonical probabilities. A
        # cached/model-supplied divergence can be stale after a probability
        # revision and must never drive the published cross-check.
        dv = round(p - implied, 4) if p is not None and implied is not None else None
        comps.append({
            "forecast_id": b.get("id"),
            "statement": b.get("statement"),
            "model_probability": p,
            "market_id": anchor.get("market_id"),
            "market_question": anchor.get("question"),
            "market_implied_yes_prob": implied,
            "price_at_research": _coerce_float(anchor.get("price_at_research")),
            "divergence": dv,
            "abs_divergence": round(abs(dv), 4) if dv is not None else None,
            "exceeds_10pp": (abs(dv) > 0.10) if dv is not None else False,
            "resolution_equivalence": anchor.get("resolution_equivalence"),
            "match_confidence": anchor.get("match_confidence"),
            "url": anchor.get("url"),
            "endDate": anchor.get("endDate"),
            "rationale_cites_market": _rationale_cites_market(b.get("adjustment_rationale"), anchor),
        })
    influences: List[Dict[str, Any]] = []
    for b in (binaries or []):
        if not isinstance(b, dict):
            continue
        inf = b.get("market_influence")
        if not isinstance(inf, dict) or not str(inf.get("market_id") or "").strip():
            continue
        influences.append({
            "forecast_id": b.get("id"),
            "statement": b.get("statement"),
            "market_id": inf.get("market_id"),
            "market_question": inf.get("market_question"),
            "price_at_revision": _coerce_float(inf.get("price_at_revision")),
            "prior_probability": _coerce_float(inf.get("prior_probability")),
            "revised_probability": _coerce_float(inf.get("revised_probability")),
            "current_probability": _coerce_float(b.get("probability")),
            "match_confidence": _coerce_float(inf.get("match_confidence")),
            "resolution_equivalence": inf.get("resolution_equivalence"),
            "anchor_removed": bool(inf.get("anchor_removed", False)),
            "probability_restored": bool(inf.get("probability_restored", False)),
        })
    out: Dict[str, Any] = {"anchored_count": len(comps), "comparisons": comps}
    if influences:
        out["influences"] = influences
        out["influence_count"] = len(influences)
    return out


# ------------------------------------------ cross-artifact proposition contract
def _proposition_key_text(value: Any) -> str:
    """Classify one statement or criterion without blending contradictory text."""
    text = str(value or "").lower().replace("–", "-").replace("—", "-")
    has_house = "house" in text
    has_senate = "senate" in text
    d_house = bool(re.search(
        r"(?:\b(?:democratic|democrats?)\b(?:(?!\b(?:republicans?|gop)\b)[^.!?]){0,100}\bhouse\b|"
        r"\bhouse\b(?:(?!\b(?:republicans?|gop)\b)[^.!?]){0,100}\b(?:democratic|democrats?)\b|\bd house\b)",
        text,
    ))
    d_senate = bool(re.search(
        r"(?:\b(?:democratic|democrats?)\b(?:(?!\b(?:republicans?|gop)\b)[^.!?]){0,100}\bsenate\b|"
        r"\bsenate\b(?:(?!\b(?:republicans?|gop)\b)[^.!?]){0,100}\b(?:democratic|democrats?)\b|\bd senate\b)",
        text,
    ))
    r_house = bool(re.search(
        r"(?:\b(?:republican|republicans?|gop)\b(?:(?!\b(?:democratic|democrats?)\b)[^.!?]){0,100}\bhouse\b|"
        r"\bhouse\b(?:(?!\b(?:democratic|democrats?)\b)[^.!?]){0,100}\b(?:republican|republicans?|gop)\b|\br house\b)",
        text,
    ))
    r_senate = bool(re.search(
        r"(?:\b(?:republican|republicans?|gop)\b(?:(?!\b(?:democratic|democrats?)\b)[^.!?]){0,100}\bsenate\b|"
        r"\bsenate\b(?:(?!\b(?:democratic|democrats?)\b)[^.!?]){0,100}\b(?:republican|republicans?|gop)\b|\br senate\b)",
        text,
    ))
    if has_house and has_senate and d_house:
        if d_senate or "sweep" in text:
            return "d_sweep"
        if r_senate:
            return "d_house_r_senate"
    if has_senate and r_senate and re.search(
        r"\b(?:effective control|vice[- ]presidential tiebreaker|gop vp|50/50)\b",
        text,
    ):
        return "r_effective_senate"
    # A net seat gain is not equivalent to winning/retaining chamber control.
    # Keep it in a distinct namespace so a statement about gaining >=0 seats
    # cannot be silently reconciled against a criterion about reaching 218.
    if has_house and (d_house or r_house) and re.search(
        r"\b(?:gain(?:s|ed|ing)?|net)\b[^.!?]{0,80}\b(?:house\s+)?seats?\b",
        text,
    ):
        return "d_house_net_seat_change" if d_house else "r_house_net_seat_change"
    if has_house and d_house and re.search(r"\b(?:majority|control|218\+?)\b", text):
        return "d_house"
    if has_house and r_house and re.search(
        r"\b(?:majority|control|218\+?)\b", text
    ):
        return "r_house"
    return ""


def _binary_proposition_key(binary: Dict[str, Any]) -> str:
    """Return a key only when statement and criterion do not contradict."""
    statement_key = _proposition_key_text(binary.get("statement"))
    criteria_key = _proposition_key_text(binary.get("resolution_criteria"))
    if statement_key and criteria_key and statement_key != criteria_key:
        return ""
    return statement_key or criteria_key


def _binary_proposition_conflict(binary: Dict[str, Any]) -> Optional[str]:
    """Describe a recognized statement/criterion event mismatch, if present."""
    statement_key = _proposition_key_text(binary.get("statement"))
    criteria_key = _proposition_key_text(binary.get("resolution_criteria"))
    if statement_key and criteria_key and statement_key != criteria_key:
        return (
            "statement and resolution criteria describe different events "
            f"({statement_key} vs {criteria_key})"
        )
    return None


def _market_proposition_key(question: Any) -> str:
    text = str(question or "").lower().replace("–", "-").replace("—", "-")
    if not text:
        return ""
    if "house" in text and "senate" in text:
        has_d_house = bool(re.search(r"\b(?:d|democratic|democrats?)\s+house\b", text))
        has_d_senate = bool(re.search(r"\b(?:d|democratic|democrats?)\s+senate\b", text))
        if has_d_house and has_d_senate:
            return "d_sweep"
        has_r_senate = bool(re.search(r"\b(?:r|republican|gop)\s+senate\b", text))
        if has_d_house and has_r_senate:
            return "d_house_r_senate"
    if "house" in text and re.search(r"\b(?:democratic party|democrats?)\b", text):
        return "d_house"
    if "house" in text and re.search(r"\b(?:republican party|republicans?|gop)\b", text):
        return "r_house"
    return ""


def _scenario_yes_membership(
    binary: Dict[str, Any], scenarios: List[Dict[str, Any]]
) -> Tuple[str, List[str], Optional[float], Optional[str]]:
    """Map a fully partition-determined proposition to its YES scenario bins."""
    proposition_conflict = _binary_proposition_conflict(binary)
    if proposition_conflict:
        return "conflicting-binary-contract", [], None, proposition_conflict
    membership = binary.get("scenario_membership")
    if membership is not None and not isinstance(membership, dict):
        return (
            "invalid-scenario-membership",
            [],
            None,
            "scenario_membership must be an object",
        )
    if isinstance(membership, dict):
        recorded_errors = [
            str(error) for error in (membership.get("validation_errors") or [])
            if str(error).strip()
        ]
        raw_derivable = membership.get("derivable")
        raw_yes_scenarios = membership.get("yes_scenarios")
        if type(raw_derivable) is not bool:
            return (
                "invalid-scenario-membership",
                [],
                None,
                "; ".join(recorded_errors)
                or "scenario_membership.derivable must be a JSON boolean",
            )
        if not isinstance(raw_yes_scenarios, list):
            return (
                "invalid-scenario-membership",
                [],
                None,
                "; ".join(recorded_errors)
                or "scenario_membership.yes_scenarios must be a list",
            )
        yes_names = [
            name.strip()
            for name in raw_yes_scenarios
            if isinstance(name, str) and name.strip()
        ]
        if len(yes_names) != len(raw_yes_scenarios):
            return (
                "invalid-scenario-membership",
                yes_names,
                None,
                "; ".join(recorded_errors)
                or "scenario_membership.yes_scenarios entries must be non-empty strings",
            )
        if len(set(yes_names)) != len(yes_names):
            return (
                "invalid-scenario-membership",
                yes_names,
                None,
                "; ".join(recorded_errors)
                or "scenario_membership.yes_scenarios contains duplicates",
            )
        if recorded_errors:
            return (
                "invalid-scenario-membership",
                yes_names,
                None,
                "; ".join(recorded_errors),
            )
        if not raw_derivable:
            if yes_names:
                return (
                    "invalid-scenario-membership",
                    yes_names,
                    None,
                    "non-derivable membership must have an empty yes_scenarios list",
                )
            return "", [], None, None
        if not yes_names:
            return (
                "invalid-scenario-membership",
                [],
                None,
                "derivable membership must declare at least one YES scenario",
            )
        scenario_by_name = {
            str(row.get("name") or ""): _coerce_float(row.get("probability"))
            for row in scenarios if isinstance(row, dict) and row.get("name")
        }
        scenario_names = [
            str(row.get("name") or "")
            for row in scenarios if isinstance(row, dict) and row.get("name")
        ]
        if len(set(scenario_names)) != len(scenario_names):
            return (
                "invalid-scenario-membership",
                yes_names,
                None,
                "canonical scenario partition contains duplicate names",
            )
        if (
            yes_names
            and all(name in scenario_by_name for name in yes_names)
            and all(scenario_by_name[name] is not None for name in yes_names)
        ):
            expected = round(sum(
                float(scenario_by_name[name]) for name in yes_names
            ), 4)
            proposition_id = str(binary.get("proposition_id") or "").strip()
            return (
                proposition_id or "explicit-scenario-membership",
                yes_names,
                expected,
                None,
            )
        return (
            "invalid-scenario-membership",
            yes_names,
            None,
            "declared scenario membership references missing/invalid bins",
        )
    key = _binary_proposition_key(binary)
    if not key or not scenarios:
        return "", [], None, None
    text = " ".join(
        str(binary.get(field) or "")
        for field in ("statement", "resolution_criteria")
    ).lower().replace("–", "-").replace("—", "-")
    include_tie = bool(re.search(r"50/50|50-50|tiebreak", text))
    yes_names: List[str] = []
    total = 0.0
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            continue
        name = str(scenario.get("name") or "")
        normalized = name.lower().replace("–", "-").replace("—", "-")
        probability = _coerce_float(scenario.get("probability"))
        if not name or probability is None:
            return "", [], None, None
        d_house = "d house" in normalized or "democratic house" in normalized
        r_house = "r house" in normalized or "republican house" in normalized
        d_senate = "d senate" in normalized or "dem senate" in normalized
        r_senate = "r senate" in normalized or "republican senate" in normalized
        tie = bool(re.search(r"50/50|50-50", normalized))
        r_trifecta = "r trifecta" in normalized or "republican trifecta" in normalized
        yes = False
        if key == "d_sweep":
            yes = d_house and d_senate
        elif key == "d_house_r_senate":
            yes = d_house and (r_senate or (include_tie and tie))
        elif key == "r_effective_senate":
            yes = r_senate or tie or r_trifecta
        elif key == "d_house":
            yes = d_house
        elif key == "r_house":
            yes = r_house or r_trifecta
        if yes:
            yes_names.append(name)
            total += probability
    if not yes_names:
        return "", [], None, None
    return key, yes_names, round(total, 4), None


def audit_proposition_consistency(forecast: Dict[str, Any]) -> Dict[str, Any]:
    """Read-only audit of binary probabilities against the scenario partition."""
    scenarios = [
        row for row in (forecast.get("scenarios") or []) if isinstance(row, dict)
    ]
    checked: List[Dict[str, Any]] = []
    mismatches: List[Dict[str, Any]] = []
    for binary in (forecast.get("binary_forecasts") or []):
        if not isinstance(binary, dict):
            continue
        key, names, expected, membership_error = _scenario_yes_membership(
            binary, scenarios
        )
        actual = _coerce_float(binary.get("probability"))
        if key in {
            "invalid-scenario-membership",
            "conflicting-binary-contract",
        }:
            mismatches.append({
                "forecast_id": str(binary.get("id") or ""),
                "proposition_key": key,
                "binary_probability": round(actual, 4) if actual is not None else None,
                "scenario_probability": None,
                "delta": None,
                "yes_scenarios": names,
                "reason": membership_error or (
                    "declared scenario membership references missing/invalid bins"
                ),
            })
            continue
        if not key or expected is None or actual is None:
            continue
        row = {
            "forecast_id": str(binary.get("id") or ""),
            "proposition_key": key,
            "binary_probability": round(actual, 4),
            "scenario_probability": expected,
            "delta": round(actual - expected, 4),
            "yes_scenarios": names,
        }
        checked.append(row)
        if abs(actual - expected) > 0.015:
            mismatches.append(row)
    return {
        "checked": len(checked),
        "rows": checked,
        "mismatches": mismatches,
        "mismatch_count": len(mismatches),
        "passed": not mismatches,
    }


def _market_anchor_complete(anchor: Dict[str, Any]) -> bool:
    required_text = ("market_id", "question", "url", "endDate", "resolution_equivalence")
    if not all(str(anchor.get(field) or "").strip() for field in required_text):
        return False
    implied = _coerce_float(anchor.get("implied_yes_prob"))
    confidence = _coerce_float(anchor.get("match_confidence"))
    return bool(
        implied is not None and 0.0 <= implied <= 1.0
        and confidence is not None and confidence >= 0.5
        and str(anchor.get("resolution_equivalence") or "").lower() in {"exact", "near"}
    )


def _market_anchor_binding_valid(
    binary: Dict[str, Any], anchor: Dict[str, Any]
) -> bool:
    """Verify that an unclassified semantic match is bound to the current bytes."""
    proposition_id = str(binary.get("proposition_id") or "").strip()
    if not proposition_id or str(anchor.get("forecast_proposition_id") or "") != proposition_id:
        return False
    contract_text = (
        str(binary.get("statement") or "").strip()
        + "\n"
        + str(binary.get("resolution_criteria") or "").strip()
    )
    question = str(anchor.get("question") or "").strip()
    return bool(
        anchor.get("match_method") == "bounded-semantic-equivalence-review"
        and anchor.get("forecast_contract_sha256")
        == hashlib.sha256(contract_text.encode("utf-8")).hexdigest()
        and anchor.get("market_question_sha256")
        == hashlib.sha256(question.encode("utf-8")).hexdigest()
    )


def audit_market_anchor_integrity(forecast: Dict[str, Any]) -> Dict[str, Any]:
    """Reject incomplete anchors and anchors resolving a different proposition."""
    issues: List[Dict[str, Any]] = []
    anchored = 0
    for binary in (forecast.get("binary_forecasts") or []):
        if not isinstance(binary, dict) or not isinstance(binary.get("market_anchor"), dict):
            continue
        anchored += 1
        anchor = binary["market_anchor"]
        binary_key = _binary_proposition_key(binary)
        market_key = _market_proposition_key(anchor.get("question"))
        reasons: List[str] = []
        if not _market_anchor_complete(anchor):
            reasons.append("incomplete provenance")
        if binary_key and market_key:
            if binary_key != market_key:
                reasons.append(f"resolution mismatch ({binary_key} vs {market_key})")
        elif not _market_anchor_binding_valid(binary, anchor):
            reasons.append("unclassified equivalence lacks a byte-bound match contract")
        if reasons:
            issues.append({
                "forecast_id": str(binary.get("id") or ""),
                "market_id": str(anchor.get("market_id") or ""),
                "reasons": reasons,
            })
    return {
        "anchored_count": anchored,
        "issues": issues,
        "issue_count": len(issues),
        "passed": not issues,
    }


def _restore_market_influence(binary: Dict[str, Any], removed_market_id: str,
                              restored: List[str]) -> None:
    """LOOP-017 P0：对账弹出了「曾把概率移向市场」的锚点 → 恢复 prior_probability。

    只在影响仍是现值的直接成因（binary.probability == 印章里的 revised_probability）时
    回滚——概率若已被后续步骤（如情景分区对账）取代，该影响已被更权威机制覆盖，绝不
    回滚 canonical 值。两种情形都把 anchor_removed=True 记进影响印章（印章永不弹出）；
    真正回滚才记 probability_restored=True、追加解释理由并把 forecast id 收进 pass 诊断。
    「保留分歧」型重述（概率未动）不产生印章，天然无需恢复。"""
    influence = binary.get("market_influence")
    if not isinstance(influence, dict):
        return
    if (str(influence.get("market_id") or "").strip()
            != str(removed_market_id or "").strip() or not str(removed_market_id or "").strip()):
        return
    influence["anchor_removed"] = True
    # 分区治理优先：本 pass 已用互斥情景分区验证/改写过该概率（membership.method 为
    # canonical 标记）→ 概率的权威来源是分区而非市场，哪怕数值恰与 revised 巧合相等，
    # 也绝不回滚 canonical 值（回滚会制造 after 审计里的分区失配）。
    membership = binary.get("scenario_membership")
    if (isinstance(membership, dict)
            and membership.get("method") == "mutually-exclusive-scenario-partition"):
        influence["probability_restored"] = False
        return
    prior = _coerce_float(influence.get("prior_probability"))
    revised = _coerce_float(influence.get("revised_probability"))
    current = _coerce_float(binary.get("probability"))
    live_cause = (prior is not None and revised is not None and current is not None
                  and abs(current - revised) <= 1e-9 and abs(current - prior) > 1e-9)
    if not live_cause:
        influence["probability_restored"] = False
        return
    binary["probability"] = round(prior, 4)
    influence["probability_restored"] = True
    note = (
        f"Market anchor {removed_market_id} was removed during contract reconciliation; "
        f"the market-influenced revision to {revised:.0%} is reverted and the "
        f"pre-influence probability {prior:.0%} is restored."
    )
    rationale = str(binary.get("adjustment_rationale") or "").strip()
    if note not in rationale:
        binary["adjustment_rationale"] = (rationale + " " + note).strip()
    restored.append(str(binary.get("id") or ""))


def reconcile_forecast_contract(
    forecast: Dict[str, Any],
    world_state_outcome: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Make scenario-equivalent binaries and market anchors one canonical contract.

    The function mutates ``forecast`` intentionally and returns a diagnostics
    payload.  Only propositions fully determined by mutually exclusive scenario
    bins are reconciled; unrelated binaries retain their independent estimates.

    SIM-ADD-3：额外把决策通道收敛的世界态结果份额记成显式、可审计的
    ``forecast['sim_adjustment']``（scenario_shares + 相对研究先验的位移）。
    ``world_state_outcome`` 显式传入优先；未传时自动从
    ``forecast['binary_quality']['world_state_outcome']`` 读取（extract_binary_forecasts 在
    世界态块确实注入提示词时钉在那里）。两者都缺 → 不写 sim_adjustment，保持今日行为
    （trajectory 缺席时绝不虚构 sim 贡献）；诊断负载记 ``sim_adjustment`` 是否落地。
    """
    binaries = [
        row for row in (forecast.get("binary_forecasts") or []) if isinstance(row, dict)
    ]
    scenarios = [
        row for row in (forecast.get("scenarios") or []) if isinstance(row, dict)
    ]
    before = audit_proposition_consistency(forecast)
    corrected: List[Dict[str, Any]] = []
    for binary in binaries:
        key, names, expected, _membership_error = _scenario_yes_membership(
            binary, scenarios
        )
        actual = _coerce_float(binary.get("probability"))
        if not key or expected is None or actual is None:
            continue
        binary["scenario_membership"] = {
            "derivable": True,
            "proposition_key": key,
            "yes_scenarios": names,
            "implied_probability": expected,
            "method": "mutually-exclusive-scenario-partition",
        }
        if abs(actual - expected) <= 0.015:
            continue
        binary["pre_reconciliation_probability"] = round(actual, 4)
        binary["probability"] = expected
        binary["source"] = "scenario-partition"
        note = (
            f"Scenario-partition reconciliation implies {expected:.0%}; this canonical "
            "value supersedes the earlier standalone estimate."
        )
        rationale = str(binary.get("adjustment_rationale") or "").strip()
        if note not in rationale:
            binary["adjustment_rationale"] = (rationale + " " + note).strip()
        corrected.append({
            "forecast_id": str(binary.get("id") or ""),
            "from": round(actual, 4),
            "to": expected,
            "proposition_key": key,
        })

    # Build the richest available record for each market before removing wrong
    # attachments; a correctly matching binary can inherit that provenance.
    richest_by_id: Dict[str, Dict[str, Any]] = {}
    for binary in binaries:
        anchor = binary.get("market_anchor")
        if not isinstance(anchor, dict):
            continue
        market_id = str(anchor.get("market_id") or "").strip()
        if not market_id:
            continue
        score = sum(1 for value in anchor.values() if value not in (None, ""))
        current = richest_by_id.get(market_id)
        current_score = sum(
            1 for value in (current or {}).values() if value not in (None, "")
        )
        if score > current_score:
            richest_by_id[market_id] = dict(anchor)

    removed_anchors: List[str] = []
    restored_influences: List[str] = []
    for binary in binaries:
        anchor = binary.get("market_anchor")
        if not isinstance(anchor, dict):
            continue
        market_id = str(anchor.get("market_id") or "").strip()
        merged = dict(richest_by_id.get(market_id) or {})
        merged.update({key: value for key, value in anchor.items() if value not in (None, "")})
        binary_key = _binary_proposition_key(binary)
        market_key = _market_proposition_key(merged.get("question"))
        proposition_matches = bool(
            (binary_key and market_key and binary_key == market_key)
            or _market_anchor_binding_valid(binary, merged)
        )
        if not proposition_matches or not _market_anchor_complete(merged):
            binary.pop("market_anchor", None)
            removed_anchors.append(str(binary.get("id") or ""))
            # LOOP-017 P0：这枚锚点若曾移动过概率（market_influence 印章），恢复
            # prior_probability——「匹配被判错 → 修订概率永久保留」的事故链在此闭合。
            _restore_market_influence(binary, market_id, restored_influences)
            continue
        binary["market_anchor"] = merged

    transferred: List[str] = []
    for market_id, rich in richest_by_id.items():
        market_key = _market_proposition_key(rich.get("question"))
        if not market_key or not _market_anchor_complete(rich):
            continue
        candidates = [row for row in binaries if _binary_proposition_key(row) == market_key]
        if len(candidates) != 1:
            continue
        binary = candidates[0]
        existing = binary.get("market_anchor")
        if not isinstance(existing, dict) or str(existing.get("market_id") or "") != market_id:
            binary["market_anchor"] = dict(rich)
            transferred.append(str(binary.get("id") or ""))
        anchor = binary["market_anchor"]
        anchor["price_at_research"] = (
            _coerce_float(anchor.get("price_at_research"))
            if _coerce_float(anchor.get("price_at_research")) is not None
            else _coerce_float(anchor.get("implied_yes_prob"))
        )

    for binary in binaries:
        anchor = binary.get("market_anchor")
        if not isinstance(anchor, dict):
            continue
        probability = _coerce_float(binary.get("probability"))
        implied = _coerce_float(anchor.get("implied_yes_prob"))
        if probability is not None and implied is not None:
            anchor["divergence"] = round(probability - implied, 4)

    forecast["binary_forecasts"] = binaries
    forecast["market_comparison"] = build_market_comparison(binaries)
    after = audit_proposition_consistency(forecast)
    market_audit = audit_market_anchor_integrity(forecast)
    diagnostics = {
        "corrected": corrected,
        "corrected_count": len(corrected),
        "removed_market_anchors": removed_anchors,
        # LOOP-017 P0：被移除锚点曾移动过概率、且本 pass 恢复了 prior 的 forecast id。
        "restored_market_influences": restored_influences,
        "transferred_market_anchors": transferred,
        "before": before,
        "after": after,
        "market_anchors": market_audit,
        "passed": after["passed"] and market_audit["passed"],
    }
    # SIM-ADD-3：记录 sim 的显式先验（如存在）。显式参数优先，其次 binary_quality 里的挂载。
    _ws_out = world_state_outcome
    if _ws_out is None:
        _bq = forecast.get("binary_quality")
        if isinstance(_bq, dict) and isinstance(_bq.get("world_state_outcome"), dict):
            _ws_out = _bq["world_state_outcome"]
    _sim_adj = _record_sim_adjustment(forecast, _ws_out)
    diagnostics["sim_adjustment"] = _sim_adj if _sim_adj is not None else None
    forecast["proposition_consistency"] = diagnostics
    return diagnostics


# --------------------------------------------------- ITEM 12: multi-model ensemble
def _build_ensemble_client(provider: str) -> Any:
    """ITEM 12：按（副模型）提供方名构造一个 LLMClient，复用 llm_client 的提供方选择机制。

    与 LLMClient/Config 的现有约定完全一致：
      - CLI 订阅提供方（claude-cli / codex-cli，PROVIDER_META 里 openai_compat=False）无需 Key，
        直接 ``LLMClient(provider=p)``；
      - OpenAI 兼容提供方从 PROVIDER_META 取 default_base/default_model，Key 依次尝试
        ``<PROVIDER>_API_KEY`` → 该提供方的 key_env（如 DEEPSEEK_API_KEY）→ 当且仅当与主提供方
        同名时的 Config.LLM_API_KEY；缺 Key 时 LLMClient 构造抛 ValueError。
    未知提供方（不在 PROVIDER_META）→ LLMClient 构造抛 ValueError。两类异常都由
    ``_run_ensemble_draws`` 捕获 → 跳过该模型并记 flag（绝不阻断主抽取）。"""
    import os as _os
    from ..config import Config
    from ..utils.llm_client import LLMClient
    p = str(provider or "").strip().lower()
    meta = Config.PROVIDER_META.get(p) or {}
    if not meta.get("openai_compat"):
        # CLI 订阅提供方 / 未知名：交给 LLMClient 构造决定（合法 CLI 通过，未知名抛 ValueError）。
        return LLMClient(provider=p)
    key = (_os.environ.get(f"{p.upper()}_API_KEY")
           or (_os.environ.get(str(meta.get("key_env"))) if meta.get("key_env") else None)
           or (Config.LLM_API_KEY if p == str(Config.LLM_PROVIDER or "").lower() else None))
    return LLMClient(provider=p, api_key=key,
                     base_url=meta.get("default_base"),
                     model=meta.get("default_model"))


def _run_ensemble_draws(models: List[str], draw_fn: Any, min_count: int, *,
                        primary_provider: str, client_factory: Any,
                        skipped: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """ITEM 12：对每个（非主）副模型各跑一次同提示词二元抽取，返回 {provider: [binaries]}。

    ``draw_fn`` 即 ``extract_binary_forecasts`` 内的 ``_draw`` 闭包（``client=`` 指定副模型
    客户端，共用主抽取的提示词与切片）。与主提供方同名或重复的名字被去重跳过（主模型已抽过）。
    某副模型构造/抽取失败或产出空列表 → 记入 ``skipped`` 并继续（绝不阻断，degrade-safe）。"""
    secondary: Dict[str, List[Dict[str, Any]]] = {}
    seen: set = set()
    prim = str(primary_provider or "").strip().lower()
    for name in (models or []):
        m = str(name or "").strip().lower()
        if not m or m == prim or m in seen:
            continue
        seen.add(m)
        try:
            client = client_factory(m)
            if client is None:
                skipped.append(m)
                continue
            drawn = draw_fn(min_count, [], client=client)
            if drawn:
                secondary[m] = drawn
            else:
                skipped.append(m)  # 空抽取（全被过滤）视同该模型无贡献
        except Exception as _de:  # noqa: BLE001 — 单个副模型失败绝不阻断集成/主抽取
            skipped.append(m)
            logger.warning(f"集成副模型 {m} 抽取失败（跳过）: {_de}")
    return secondary


_BINARY_DATA_ANCHOR_EXAMPLE = (
    "\nFormat illustration only (use a series and period that are actually listed): "
    '{"statement": "The US unemployment rate is at least 5% in June 2027", '
    '"resolution_criteria": "Resolves YES if fred:UNRATE >= 5% in 2027-06 (source: FRED).", '
    '"data_anchor": {"series": "fred:UNRATE", "comparator": ">=", "threshold": 5, '
    '"observation": "2027-06", "transform": "", "units": "Percent"}}. '
    "The statement may use words (at least, above, below, at most; 不低于, 超过, 低于, 不超过) "
    "but must name one metric, one threshold and the same single period, with no second "
    "number, negation, alternative or condition; the criterion must contain exactly one "
    "'<series> <comparator> <threshold> [units] in <period>' clause plus an optional source."
)


def _cap_at_line(text: str, cap: int) -> str:
    """Bound prompt text at a line boundary, noting omitted lines (unchanged when within cap)."""
    if len(text) <= cap:
        return text
    note = "\n[further rows omitted for length]"
    cut = text.rfind("\n", 0, max(0, cap - len(note)))
    return (text[:cut] if cut > 0 else text[:max(0, cap - len(note))]) + note


def _pinned_slug(value: Any) -> str:
    """A golden id as ``_normalize_binaries`` normalizes a ``proposition_id``."""
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def _pinned_questions_rule(pinned: List[Dict[str, Any]]) -> str:
    """Backtest mode: the prompt block that pins each golden question."""
    lines = ["\nPINNED QUESTIONS: the set MUST include exactly one forecast for each question "
             "below, with the given proposition_id, a statement that asserts the question's YES "
             "outcome as one declarative sentence, these resolution criteria, and your own "
             "probability from the dossier's evidence alone (they count toward the minimum):"]
    for question in pinned:
        lines.append(f'- proposition_id "{_pinned_slug(question.get("golden_id"))}": '
                     f'{str(question.get("question") or "")[:600]}'
                     + (f" | resolution criteria: {str(question.get('resolution_criteria'))[:600]}"
                        if question.get("resolution_criteria") else "")
                     + (f" | resolves on {question.get('resolution_date')}"
                        if question.get("resolution_date") else ""))
    return "\n".join(lines)


def _mark_pinned_answers(binaries: List[Dict[str, Any]], pinned: List[Dict[str, Any]]) -> None:
    """Mark the row answering each pinned question with ``golden_id`` (first match wins)."""
    wanted = {_pinned_slug(q.get("golden_id")): str(q.get("golden_id")) for q in pinned}
    for row in binaries:
        golden = wanted.pop(str(row.get("proposition_id") or ""), None)
        if golden is not None:
            row["golden_id"] = golden


def extract_binary_forecasts(report_markdown: str, llm, *, min_count: int = 10,
                             language: str = "English",
                             situation_brief: Optional[str] = None,
                             themes: Optional[List[str]] = None,
                             signal_pack: Optional[str] = None,
                             market_pack: Optional[str] = None,
                             markets: Optional[List[Dict[str, Any]]] = None,
                             scenarios: Optional[List[Dict[str, Any]]] = None,
                             ensemble_client_factory: Optional[Any] = None,
                             horizon_date: Optional[str] = None,
                             data_pack: Optional[str] = None,
                             official_data: Optional[Dict[str, Any]] = None,
                             simulation_effect: Optional[str] = None,
                             pinned_questions: Optional[List[Dict[str, Any]]] = None,
                             report_policy=None) -> Dict[str, Any]:
    """Extract/derive >=min_count INDEPENDENT binary forecasts from the dossier.

    Returns ``{"binary_forecasts": [...], "binary_quality": {...}}``. Degrade-safe:
    a malformed reply yields an empty list (caller keeps the scenario forecast). Runs a
    single bounded top-up pass if the first pass is short of ``min_count``.

    RPT-6: ``themes``（可选）取代硬编码的 mercantilism|ai|intersection 契约；未给出时
    提示词改用主题无关措辞、主题串自由。RPT-4（FORECAST_BINARY_CONTRARIAN，默认开）：
    要求近半数陈述以「证据支持概率 <0.5」的反共识方向表述，首轮 spread 过低/全部 >0.5
    时追加一次有界低概率重述补足。XRUN-1(b)（FORECAST_SIM_SENSITIVITY，默认开）：
    注入模拟量化信号包并要求每个概率说明其相对 base_rate_anchor 的位移与来源。
    预测市场（PREDICTION_MARKETS_ENABLED，默认开）：``market_pack``（渲染好的市场表）
    注入提示词要求对照市场隐含概率；``markets``（规整化快照）用于回填/校验 market_anchor。
    PM-2：抽取后跑一次确定性市场匹配（anchor_binaries_to_markets）+ 10pp 分歧有界重述
    （enforce_market_divergence），并把对照负载放进返回值 ``market_comparison``（供落
    market_comparison.json）。RQ-2：dossier 切片改为 head+tail（结论在文末）。

    Backtest mode (both default ``None`` = unchanged): ``simulation_effect``
    replaces ``SIMULATION_FORECAST_EFFECT`` for this call (the ablation arm's
    policy); ``pinned_questions`` (``[{golden_id, question, resolution_criteria,
    resolution_date}]``) asks every draw to include one forecast per question
    with that ``proposition_id``, and each row that answers one is marked
    ``golden_id`` (the backtest driver maps forecasts to golden questions by it).
    """
    from .ensemble import freeze_report_policy
    policy = freeze_report_policy(report_policy)
    content = (report_markdown or "")
    _bbudget = int(_cfg("FORECAST_BINARY_EXTRACT_BUDGET", 48000))
    _bhr = _coerce_float(_cfg("FORECAST_EXTRACT_HEAD_RATIO", 0.6))
    content = slice_head_tail(content, _bbudget, _bhr if _bhr is not None else 0.6)
    themes = [str(t).strip().lower() for t in (themes or []) if str(t).strip()] or None
    contrarian = bool(_cfg("FORECAST_BINARY_CONTRARIAN", True))
    # Foglamp WP1 (1D, I-16)：模拟信号只有在 SIMULATION_FORECAST_EFFECT=legacy_prompt
    # （特征化 fixture 专用）时才允许进入二元概率生成；默认 diagnostic_only 下模拟产出
    # 不得移动任何已发布概率（simulation adjustments 是未晋升的预测政策）。
    _sim_effect = str(simulation_effect or (
        policy["simulation_forecast_effect"] if policy is not None else
        _cfg("SIMULATION_FORECAST_EFFECT", "diagnostic_only"))
                      or "diagnostic_only").strip().lower()
    pinned = [q for q in (pinned_questions or []) if isinstance(q, dict) and q.get("golden_id")]
    sim_sensitive = (_sim_effect == "legacy_prompt"
                     and bool(_cfg("FORECAST_SIM_SENSITIVITY", True))
                     and bool((signal_pack or "").strip()))
    market_aware = (bool(_cfg("PREDICTION_MARKETS_ENABLED", True))
                    and bool((market_pack or "").strip()))
    # market_id → 隐含概率查找表（用我们抓取的快照回填模型转录的锚点，不盲信模型数字）。
    market_lookup: Dict[str, float] = {}
    for m in (markets or []):
        if not isinstance(m, dict):
            continue
        mid = str(m.get("market_id") or "").strip()
        ip = _coerce_float(m.get("implied_yes_prob"))
        if mid and ip is not None and 0.0 <= ip <= 1.0:
            market_lookup[mid] = ip
    # spec §4（日历模式）：确定性 horizon_date 可用时，horizon_year 提示直接用
    # horizon_date.year（判定年即预测期限年）；缺省 None → 旧措辞逐字节不变。
    _hz_year: Optional[int] = None
    if horizon_date:
        try:
            from ..utils.dates import parse_as_of as _pao
            _hd = _pao(str(horizon_date))
            _hz_year = _hd.year if _hd else None
        except Exception:  # noqa: BLE001 — 判定年提示为增强，失败退回旧措辞
            _hz_year = None
    _hz_hint = str(_hz_year) if _hz_year else "2027"
    _hz_rule = (f"resolution year, at or before the forecast horizon {_hz_year}"
                if _hz_year else "resolution year, within 1-5 years of now")

    def _draw(instr_min: int, exclude: List[str], *, low_p: bool = False,
              client: Any = None) -> List[Dict[str, Any]]:
        # ITEM 12：client 指定时用该（副模型）客户端抽取，否则用主 llm——集成各模型共用同一提示词。
        _llm = client if client is not None else llm
        user = _BINARY_FORECAST_INSTRUCTIONS.format(
            min_count=instr_min, language=language,
            theme_enum=("|".join(themes) if themes else _BINARY_DEFAULT_THEME_ENUM),
            tie_rule=(f"tied to {', '.join(themes)}" if themes else _BINARY_DEFAULT_TIE_RULE),
            horizon_year_hint=_hz_hint, horizon_year_rule=_hz_rule,
        )
        if contrarian:
            user += _BINARY_LOW_P_RULE if low_p else _BINARY_CONTRARIAN_RULE
        if sim_sensitive:
            user += (
                "\nSIMULATION SENSITIVITY: each adjustment_rationale MUST state how far and in "
                "which direction the probability moved from base_rate_anchor, citing the specific "
                "simulation signal below when one applies; set the source field to that signal "
                "name, or to \"research-prior\" when no simulation signal informs it."
            )
        if market_aware:
            user += _BINARY_MARKET_RULE
        if pinned:
            user += _pinned_questions_rule(pinned)
        if data_pack and official_data:
            pack = _cap_at_line(str(data_pack), OFFICIAL_PACK_PROMPT_CAP)
            user += (
                ("\n\n" if pack.startswith("[Official data snapshot") else "\n\n[Official data snapshot]\n")
                + pack
                + '\nWhenever a binary\'s metric is one of the listed series, add data_anchor '
                  '{"series": "exact canonical ID", "comparator": ">|>=|<|<=", '
                  '"threshold": number, "observation": "YYYY-MM|YYYY-Qn|YYYY|YYYY-MM-DD|FYyyyy", '
                  '"transform": "exact listed transform", "units": "exact listed units"}: an anchored '
                  "binary settles from the publisher's data, and its probability is compared with the "
                  "empirical base rate computed from the stored history (the outside view below). "
                  "Match the series frequency and a single exact period (monthly YYYY-MM, quarterly "
                  "YYYY-Qn, annual YYYY; a fiscal-year series listed with FY labels uses its label, such "
                  "as FY2026). For a series whose monthly values are end-of-month values (the "
                  "end-of-month value of daily data, or a monthly 'End of period' series), a question "
                  "about the last day of a month or the end of a year uses that month ('on 31 December "
                  "2026' or 'at the end of 2026' -> 2026-12; 'by the end of 2026' is a deadline, not a "
                  "period); a monthly mean of daily data cannot settle a single-day question, so do not "
                  "anchor one. In the statement, name the metric as the snapshot lists it (its title, or a "
                  "short form keeping the title's distinctive words, such as 'the US unemployment rate'); "
                  "when your wording differs from the title, put the canonical ID in parentheses right "
                  "after it (such as 'the US jobless rate (fred:UNRATE)'), or the anchor cannot be "
                  "verified and is dropped. State thresholds with at least / above / below / at most: an "
                  "exact-value statement ('is 4.25%') cannot be anchored. Thresholds and probabilities are model "
                  "forecasts; publisher projections are not observed outcomes. In resolution_criteria "
                  "include the canonical series ID, literal comparator, numeric threshold, units and "
                  "observation period exactly; keep the statement's metric and numeric comparison "
                  "consistent with this criterion (use the same literal comparator and units in the "
                  "statement). Do not transcribe latest values or invent series metadata."
                + _BINARY_DATA_ANCHOR_EXAMPLE
            )
            outside_view = official_outside_view_block(official_data, horizon_date, language)
            if outside_view:
                user += "\n\n" + outside_view
        if exclude:
            user += "\n\nDo NOT repeat these already-captured forecasts (produce NEW, distinct ones):\n" + \
                "\n".join(f"- {s}" for s in exclude[:30])
        if situation_brief:
            user += f"\n\n[Situation brief]\n{situation_brief[:2000]}"
        if sim_sensitive:
            user += f"\n\n[Simulation quantitative signals]\n{str(signal_pack)[:4000]}"
        if market_aware:
            # PM-2：市场表切片 4000→8000，让相关性门控后的更多市场进入锚定视野。
            user += f"\n\n[Prediction market signals]\n{str(market_pack)[:8000]}"
        if scenarios:
            scenario_rows = [
                {
                    "name": str(row.get("name") or ""),
                    "probability": row.get("probability"),
                    "resolution_criteria": str(row.get("resolution_criteria") or ""),
                }
                for row in scenarios
                if isinstance(row, dict) and row.get("name")
            ]
            if scenario_rows:
                user += (
                    "\n\n[Canonical mutually-exclusive scenario partition]\n"
                    + str(scenario_rows)[:6000]
                    + "\nFor a binary fully determined by this partition, set "
                    "scenario_membership.derivable=true and copy every YES scenario name "
                    "exactly. Otherwise set derivable=false and leave yes_scenarios empty."
                )
        user += f"\n\n[Research dossier]\n{content}"
        raw = _llm.chat_json(messages=[{"role": "user", "content": user}],
                             temperature=0.25, max_tokens=4096)
        items = raw.get("binary_forecasts") if isinstance(raw, dict) else None
        return _normalize_binaries(items or [], allowed_themes=themes,
                                   market_lookup=market_lookup or None,
                                   official_data=official_data, language=language)

    def _merge(base: List[Dict[str, Any]], extra: List[Dict[str, Any]]) -> None:
        seen = {_binary_key(b["statement"]) for b in base}
        for b in extra:
            k = _binary_key(b["statement"])
            if k not in seen:
                seen.add(k)
                base.append(b)

    binaries = _draw(min_count, [])
    if len(binaries) < min_count:
        need = min_count - len(binaries)
        _merge(binaries, _draw(need + 2, [b["statement"] for b in binaries]))
    # RPT-4：一次有界的低概率重述补足——首轮 stdev<0.12 或全部 >0.5 时，同方向 top-up
    # 永远无法过 conviction 门，必须显式索取 0.05-0.35 区间的反共识陈述。
    if contrarian and binaries:
        probs = [b["probability"] for b in binaries]
        mean = sum(probs) / len(probs)
        std = math.sqrt(sum((p - mean) ** 2 for p in probs) / len(probs))
        if std < 0.12 or min(probs) > 0.5:
            try:
                low_n = max(3, min_count // 3)
                _merge(binaries, _draw(low_n, [b["statement"] for b in binaries], low_p=True))
            except Exception as _le:  # noqa: BLE001 — 补足失败保留首轮结果（degrade-safe）
                logger.warning(f"二元预测低概率重述补足失败（忽略）: {_le}")
    # renumber ids stably F1..Fn（锚定用稳定 id 匹配，故在此之后再跑市场锚定）
    for i, b in enumerate(binaries, start=1):
        b["id"] = f"F{i}"
    if pinned:
        _mark_pinned_answers(binaries, pinned)
    # ITEM 12：多模型集成——主模型抽完后，对每个所列（非主）提供方各跑一次同提示词二元抽取，
    # 按 id/陈述匹配同一条预测，用与种子集成同一套 extremizing log-odds（ENSEMBLE_EXTREMIZE_A）
    # 把各模型概率池化为发布概率，记 binary['ensemble']={models,probs,pooled,spread}。置于市场锚定
    # **之前** ⇒ 锚定/分歧重述基于池化后的概率，market_anchor.divergence 一次算准。任一副提供方
    # 失败→跳过该模型并记 flag，绝不阻断；FORECAST_ENSEMBLE_MODELS 空=整段跳过（逐字节复现旧行为）。
    ensemble_low_agreement: List[str] = []
    ensemble_skipped: List[str] = []
    ensemble_pooled_models: List[str] = []
    _ens_models = [m.strip().lower() for m in str(_cfg("FORECAST_ENSEMBLE_MODELS", "") or "").split(",")
                   if m.strip()]
    if binaries and _ens_models:
        try:
            secondary = _run_ensemble_draws(
                _ens_models, _draw, min_count,
                primary_provider=str(getattr(llm, "provider", "") or "primary").lower(),
                client_factory=ensemble_client_factory or _build_ensemble_client,
                skipped=ensemble_skipped)
            if secondary:
                ensemble_pooled_models = sorted(secondary.keys())
                from .ensemble import pool_binary_forecasts as _pool
                a_raw = (policy["ensemble_extremize_a"] if policy is not None else
                         _cfg("ENSEMBLE_EXTREMIZE_A", None))
                try:
                    _a = float(a_raw) if a_raw is not None else None
                except (TypeError, ValueError):
                    _a = None
                _thr = _coerce_float(_cfg("FORECAST_ENSEMBLE_SPREAD_THRESHOLD", 0.15))
                ensemble_low_agreement = _pool(
                    binaries, secondary,
                    primary_model=str(getattr(llm, "provider", "") or "primary").lower(),
                    extremize_a=_a,
                    spread_threshold=_thr if _thr is not None else 0.15)
        except Exception as _ee:  # noqa: BLE001 — 集成为增强，绝不阻断二元抽取
            logger.warning(f"多模型预测集成失败（忽略，保留主模型结果）: {_ee}")
    # PM-2：确定性市场锚定 + 10pp 分歧有界重述 + 对照负载。任何失败 → 保留无锚点结果
    # （_normalize_binaries 已回填的模型自愿锚点仍在），即今日行为（degrade-safe）。
    market_comparison: Optional[Dict[str, Any]] = None
    if binaries and (markets or []):
        try:
            anchor_binaries_to_markets(binaries, markets, llm, language=language)
            enforce_market_divergence(binaries, llm, language=language)
            market_comparison = build_market_comparison(binaries)
        except Exception as _ae:  # noqa: BLE001 — 锚定为增强，绝不阻断二元抽取
            logger.warning(f"预测市场锚定失败（忽略，保留无锚点结果）: {_ae}")
            market_comparison = None
    # 编造溯源修复：source 只允许指向**确实注入过提示词**的信号块。允许集取自与 _draw 提示词
    # 相同的 [:4000] 切片（sim_sensitive 关/包空 → 空集）；market_pack 注入时额外放行市场标签。
    # 不在集合内（含模型自造名，如从未存在过的 world-state 信号）→ 降级 research-prior，原话
    # 存 source_claimed，计数落 binary_quality.provenance_downgrades（审计可对账）。
    _allowed_labels = allowed_signal_labels(str(signal_pack)[:4000] if sim_sensitive else "")
    if market_aware:
        _allowed_labels.add(_SOURCE_MARKET_LABEL)
    provenance_downgrades = _enforce_source_provenance(binaries, _allowed_labels)
    out: Dict[str, Any] = {
        "binary_forecasts": binaries,
        "binary_quality": _binary_quality(binaries, min_count=min_count,
                                          themes_expected=themes),
    }
    _bq_prov = out["binary_quality"]
    if isinstance(_bq_prov, dict):
        _bq_prov["provenance_downgrades"] = provenance_downgrades
        if provenance_downgrades:
            _bq_prov.setdefault("issues", []).append(
                f"{provenance_downgrades} forecast(s) claimed a simulation signal that was never "
                "injected into the prompt — source downgraded to research-prior (see source_claimed)")
    # SIM-ADD-3：世界态结果分布块**确实注入**（在允许集内）时，把决策通道收敛的 P(outcome)
    # 份额解析出来钉进 binary_quality.world_state_outcome。report_agent 在调用
    # reconcile_forecast_contract 前会把本 binary_quality 挂到 forecast 上，reconcile 据此
    # 记成显式、可审计的 forecast.sim_adjustment（sim 真实贡献才被记录；块未注入 → 不加）。
    if "world-state outcome shares" in _allowed_labels and isinstance(_bq_prov, dict):
        _ws_out = world_state_outcome_from_signal_pack(str(signal_pack)[:4000])
        if _ws_out:
            _bq_prov["world_state_outcome"] = _ws_out
    # ITEM 12：把多模型集成诊断落进 binary_quality（该块经 report_agent 落到 forecast['binary_quality']
    # 并被 render_binary_forecasts_block 消费）。仅当 FORECAST_ENSEMBLE_MODELS 非空时附加（默认整段不加
    # → schema 逐字节不变）。low_agreement 收 spread>阈值的预测 id，其陈述在报表以 ±spread 高亮分歧；
    # skipped 记构造/抽取失败被跳过的副提供方；pooled_models 记真正参与池化的副提供方。
    if _ens_models:
        _ens_block: Dict[str, Any] = {
            "enabled_models": _ens_models,
            "pooled_models": ensemble_pooled_models,
            "skipped": ensemble_skipped,
            "low_agreement": ensemble_low_agreement,
            "spread_threshold": (_coerce_float(_cfg("FORECAST_ENSEMBLE_SPREAD_THRESHOLD", 0.15)) or 0.15),
        }
        _bq = out["binary_quality"]
        if isinstance(_bq, dict):
            _bq["ensemble"] = _ens_block
            if ensemble_low_agreement:
                _bq.setdefault("issues", []).append(
                    f"{len(ensemble_low_agreement)} forecast(s) show cross-model disagreement "
                    f"(spread > {_ens_block['spread_threshold']}): {', '.join(ensemble_low_agreement)}")
    if market_comparison and market_comparison.get("comparisons"):
        out["market_comparison"] = market_comparison
    return out


# ------------------------------------------ requirement-horizon consistency (RQ-6)
# 一个 2026 年期中选举 brief 抽出的二元预测若全部落在 2028 年结算 = 交付物答非所问。
# requirement_spec 不解析目标日期（只有 themes/page_budget 等），这里直接用正则从需求
# 文本抽取「目标年份」，与二元预测的结算年份（horizon_year 字段 + 陈述/判定标准中出现
# 的年份）对比；两侧都解析出年份且**完全不相交**时，在 forecast['quality'] 合并写入
# ``horizon_mismatch`` 标记（镜像 _apply_publish_gate 的 merge 行为，绝不覆盖既有
# quality 键），供发布门（RQ-6 gate 半）降级 confidence。Degrade-safe：任一侧解析不出
# 年份 → 不加标记；任何异常 → 原 forecast 原样返回。
_REQ_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def _plausible_years(text: Any, lo: int, hi: int) -> set:
    """Years mentioned in ``text`` that fall inside the plausible window [lo, hi]."""
    out: set = set()
    for m in _REQ_YEAR_RE.finditer(str(text or "")):
        y = int(m.group(1))
        if lo <= y <= hi:
            out.add(y)
    return out


def parse_requirement_years(requirement_text: Optional[str], *,
                            now_year: Optional[int] = None) -> List[int]:
    """Extract the brief's candidate TARGET years from the requirement text (sorted).

    过滤到 [now-1, now+30] 窗口：历史背景年份（"since the 2008 crisis"）不是结算目标，
    保留会造成假阳性。Pure / offline；解析不出 → []（调用方随之不加标记，degrade-safe）。
    """
    if now_year is None:
        from datetime import datetime
        now_year = datetime.now().year
    return sorted(_plausible_years(requirement_text, now_year - 1, now_year + 30))


def apply_horizon_consistency(forecast: Dict[str, Any], requirement_text: Optional[str], *,
                              now_year: Optional[int] = None,
                              horizon_date: Optional[str] = None) -> Dict[str, Any]:
    """RQ-6（extractor 半）：抽取时校验二元预测结算年份与 brief 目标年份的一致性。

    需求文本目标年份集合与二元预测结算年份集合均非空且**无交集**时（例：2026 brief 抽出
    全 2028 结算且无一条 2026 的二元），把结构化标记 merge 进 ``forecast['quality']``
    （绝不覆盖既有键——镜像 _apply_publish_gate 的 merge 行为），供发布门降信心。
    Mutates + returns ``forecast``。FORECAST_HORIZON_CHECK 旗标关闭、年份解析不出、
    或任何异常 → 原样返回（degrade-safe，不阻断抽取）。

    日历模式（spec §4）：可用**确定性** ``horizon_date`` 时（显式入参优先，否则用
    ``sim_timeline.extract_horizon`` 对需求文本做确定性四层抽取——LLM 兜底不在此处），
    额外把 ``horizon_date.year`` 并入需求侧目标年份参与同一交集比对——覆盖相对期限
    （"within 18 months"）等 bare-year 正则取不到年份的 brief。门/降级行为不变。
    """
    try:
        if not isinstance(forecast, dict) or not _cfg("FORECAST_HORIZON_CHECK", True):
            return forecast
        if now_year is None:
            from datetime import datetime
            now_year = datetime.now().year
        req_years = set(parse_requirement_years(requirement_text, now_year=now_year))
        lo, hi = now_year - 1, now_year + 30
        hz_year: Optional[int] = None
        try:
            if horizon_date:
                from ..utils.dates import parse_as_of as _pao
                _hd = _pao(str(horizon_date))
                hz_year = _hd.year if _hd else None
            else:
                from datetime import date as _date
                from ..utils.sim_timeline import extract_horizon as _eh
                _res = _eh(str(requirement_text or ""), _date(int(now_year), 1, 1))
                hz_year = int(str(_res.horizon_date)[:4]) if _res else None
            if hz_year is not None and not (lo <= hz_year <= hi):
                hz_year = None
        except Exception:  # noqa: BLE001 — 判定年推导为增强，失败退回纯正则口径
            hz_year = None
        if hz_year is not None:
            req_years.add(hz_year)
        if not req_years:
            return forecast  # brief 未给出可解析的目标年份/判定日 → 无从比对（不加标记）
        bin_years: set = set()
        for b in (forecast.get("binary_forecasts") or []):
            if not isinstance(b, dict):
                continue
            hy = _coerce_float(b.get("horizon_year"))
            if hy is not None and lo <= int(hy) <= hi:
                bin_years.add(int(hy))
            bin_years |= _plausible_years(
                f"{b.get('statement') or ''} {b.get('resolution_criteria') or ''}", lo, hi)
        if not bin_years or (req_years & bin_years):
            return forecast  # 二元侧无年份可比 / 存在交集 → 视为一致，不加标记
        req_s, bin_s = sorted(req_years), sorted(bin_years)
        _q0 = forecast.get("quality")
        quality = dict(_q0) if isinstance(_q0, dict) else {}
        quality["horizon_mismatch"] = {
            "requirement_years": req_s,
            "binary_years": bin_s,
            "detail": (f"binary forecasts resolve in {'/'.join(map(str, bin_s))} but the "
                       f"brief targets {'/'.join(map(str, req_s))} (no overlap)"),
        }
        forecast["quality"] = quality
        return forecast
    except Exception as _he:  # noqa: BLE001 — 一致性检查绝不阻断抽取（degrade-safe）
        logger.warning(f"需求-预测时间范围一致性检查失败（忽略）: {_he}")
        return forecast


# ----------------------------------------------------------- forecast spine (P0-1)
_SPINE_INSTRUCTIONS = """你是预测校准专家。在撰写任何叙事之前，先基于下面的【研究输入】（参考类基率/
驱动因素/观察指标/候选情景）与【模拟量化信号】，给出一个**机器可读**的结构化预测骨架。
只输出 JSON，不要解释。字段：
{
  "headline": "一句话核心结论",
  "horizon": "预测时间范围（如 '2030'）",
  "scenarios": [
    {
      "name": "情景名",
      "probability": 0.0-1.0,         // 所有情景概率之和必须≈1
      "summary": "该情景的简述",
      "key_drivers": ["关键驱动因素", ...],
      "base_rate_anchor": "该情景的参考类基率/外部视角起点（先从基率出发）",
      "adjustment_rationale": "据本案具体特征对基率所做调整及理由（anchor-and-adjust）",
      "resolution_criteria": "可证伪的判定标准：到期时如何客观判断此情景是否发生（含可观测指标/阈值/日期）"
    }
  ],
  "key_uncertainties": ["最大的不确定性来源", ...],
  "confidence": "low|medium|high",
  "confidence_rationale": "信心评级的理由（数据质量/分歧度/时间跨度）"
}
要求：2-5 个**互斥且尽量穷尽（MECE）**的情景，并**必须**含一个「维持现状/其它」兜底情景；
概率为数值且之和≈1；resolution_criteria 必须客观可验证。**对每个情景采用 anchor-and-adjust**：
先给 base_rate_anchor（参考类基率/外部视角），再据案例特征调整得到最终 probability，并在
adjustment_rationale 说明，以抵御基率忽视/内视过度自信。先确定数字与判定标准，再让叙事去捍卫它们。"""


_SPINE_METRIC_RANGE_RULE = (
    "\n\n[情景量化区间（可选）]\n若某情景可由上方所列官方序列在单一观察期的数值区间刻画，为该情景增加 "
    'metric_range：{"series": "所列规范ID（原样）", "low": 数值或null, "high": 数值或null, '
    '"period": "YYYY-MM|YYYY-Qn|YYYY|YYYY-MM-DD|FYyyyy（与序列频率一致；财年序列用所列 FY 标签，如 FY2026）", '
    '"units": "所列单位原文"}。'
    "low/high 至少一个为数值（开区间用 null），同一序列的各情景区间应互斥；不要使用未列出的序列，"
    "无法量化的情景不要加此字段。"
)


def _spine_draw(llm, user: str, temperature: float, max_tokens: int, *,
                keep_metric_range: bool = False) -> Dict[str, Any]:
    """One spine LLM draw → assembled forecast dict (degrade-safe on bad replies)."""
    raw = llm.chat_json(
        messages=[{"role": "user", "content": user}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if not isinstance(raw, dict):
        raw = {}
    return _assemble_forecast(raw, keep_metric_range=keep_metric_range)


def _pool_spine_draws(draws: List[Dict[str, Any]], floor: float) -> Dict[str, Any]:
    """R2-CAL-1/R2-CAL-17: pool K self-consistency draws (shared scenario names).

    The first draw establishes the canonical scenario set (names + criteria + anchors);
    each scenario's published probability becomes the MEAN across the draws that
    surfaced it, with [p_low, p_high] carrying the across-draw spread. Means are
    floored + renormalized. Confidence is demoted when the mean spread is wide.
    """
    from .ensemble import _norm_name  # local: avoid import cycle at module load
    base = draws[0]
    base_scen = [s for s in (base.get("scenarios") or []) if isinstance(s, dict)]
    # collect probabilities per canonical name across all draws
    probs_by_key: Dict[str, List[float]] = {}
    for d in draws:
        for s in (d.get("scenarios") or []):
            if not isinstance(s, dict):
                continue
            k = _norm_name(s.get("name"))
            if not k:
                continue
            p = _coerce_float(s.get("probability"))
            if p is not None:
                probs_by_key.setdefault(k, []).append(p)
    pooled: List[Dict[str, Any]] = []
    spreads: List[float] = []
    for s in base_scen:
        k = _norm_name(s.get("name"))
        ps = probs_by_key.get(k) or [_coerce_float(s.get("probability")) or 0.0]
        mean = sum(ps) / len(ps)
        if len(ps) > 1:
            m = mean
            sd = math.sqrt(sum((x - m) ** 2 for x in ps) / (len(ps) - 1))
        else:
            sd = 0.0
        spreads.append(sd)
        row = dict(s)
        row["probability"] = mean
        row["p_low"] = max(0.0, mean - sd)
        row["p_high"] = min(1.0, mean + sd)
        row["self_consistency_n"] = len(ps)
        pooled.append(row)
    # floor + renormalize the pooled means (keep intervals proportional)
    total = sum(r["probability"] for r in pooled)
    if total > 0:
        for r in pooled:
            r["probability"] = r["probability"] / total
    if floor > 0 and pooled:
        for r in pooled:
            if r["probability"] < floor:
                r["probability"] = floor
        t2 = sum(r["probability"] for r in pooled)
        if t2 > 0:
            for r in pooled:
                r["probability"] = r["probability"] / t2
    for r in pooled:
        r["probability"] = round(r["probability"], 4)
        r["p_low"] = round(min(r["p_low"], r["probability"]), 4)
        r["p_high"] = round(max(r["p_high"], r["probability"]), 4)
    out = dict(base)
    out["scenarios"] = pooled
    out["self_consistency_k"] = len(draws)
    out["self_consistency_mean_spread"] = round(sum(spreads) / len(spreads), 4) if spreads else 0.0
    # demote confidence on wide disagreement across draws (overconfidence guard)
    mean_spread = out["self_consistency_mean_spread"]
    if mean_spread >= 0.15 and out.get("confidence") == "high":
        out["confidence"] = "medium"
    if mean_spread >= 0.25 and out.get("confidence") == "medium":
        out["confidence"] = "low"
    return out


SELF_CONSISTENCY_INTERVAL_SOURCE = "self_consistency_spread"


def apply_self_consistency_intervals(forecast: Any) -> Any:
    """VIZ-GAP1(a): derive honest per-scenario intervals from pooled self-consistency data.

    ``_pool_spine_draws`` computes per-scenario ``p_low``/``p_high`` from K draws, and
    forecast.json publishes ``self_consistency_k`` / ``self_consistency_mean_spread`` —
    but downstream passes (the red-team critique re-runs ``_normalize_scenarios``, the
    pre-mortem shifts probabilities) strip or invalidate those bounds, so real runs
    shipped bare point estimates and every uncertainty encoding downstream stayed dead.

    This helper re-establishes the interval contract additively and deterministically:

    * requires ``self_consistency_k >= 2`` AND a finite non-negative
      ``self_consistency_mean_spread`` — otherwise it EMITS NOTHING (never fabricates);
    * a scenario whose existing bounds are valid (``0 <= p_low <= p <= p_high <= 1``)
      keeps them; pooled bounds (marked by ``self_consistency_n >= 2``) additionally
      gain ``interval_source`` so their provenance survives serialization, while
      model-declared bounds are left untagged (they are not self-consistency evidence);
    * a scenario with missing/invalidated bounds gets
      ``p_low/p_high = clamp(p ± mean_spread)`` tagged
      ``interval_source='self_consistency_spread'``;
    * the forecast gains top-level ``interval_provenance = {source, k, spread}`` so
      renderers can annotate charts with where the interval came from.

    Mutates ``forecast`` in place and returns it; non-dict input is returned unchanged.
    """
    if not isinstance(forecast, dict):
        return forecast
    try:
        k = int(forecast.get("self_consistency_k"))
    except (TypeError, ValueError):
        return forecast
    spread = _coerce_float(forecast.get("self_consistency_mean_spread"))
    if k < 2 or spread is None or spread < 0:
        return forecast
    scenarios = [s for s in (forecast.get("scenarios") or []) if isinstance(s, dict)]
    tagged = False
    for scenario in scenarios:
        p = _coerce_float(scenario.get("probability"))
        if p is None or not 0.0 <= p <= 1.0:
            continue
        lo = _coerce_float(scenario.get("p_low"))
        hi = _coerce_float(scenario.get("p_high"))
        has_valid_bounds = (lo is not None and hi is not None
                            and 0.0 <= lo <= p <= hi <= 1.0)
        if has_valid_bounds:
            pooled_n = _coerce_float(scenario.get("self_consistency_n"))
            if scenario.get("interval_source") == SELF_CONSISTENCY_INTERVAL_SOURCE:
                tagged = True
            elif "interval_source" not in scenario and pooled_n is not None and pooled_n >= 2:
                scenario["interval_source"] = SELF_CONSISTENCY_INTERVAL_SOURCE
                tagged = True
            continue
        scenario["p_low"] = round(max(0.0, p - spread), 4)
        scenario["p_high"] = round(min(1.0, p + spread), 4)
        scenario["interval_source"] = SELF_CONSISTENCY_INTERVAL_SOURCE
        tagged = True
    if tagged:
        forecast["interval_provenance"] = {
            "source": SELF_CONSISTENCY_INTERVAL_SOURCE,
            "k": k,
            "spread": spread,
        }
    return forecast


def derive_forecast_spine(llm, *, central_question: str = "", horizon: str = "",
                          situation_brief: Optional[str] = None,
                          forecast_inputs: str = "", signal_pack: str = "",
                          base_distribution: Optional[Dict[str, float]] = None,
                          quantitative_facts: str = "",
                          market_block: str = "",
                          language: str = "",
                          official_data: Optional[Dict[str, Any]] = None,
                          report_policy=None) -> Dict[str, Any]:
    """NEXTSTEPS P0-1: derive the structured forecast *spine* from research +
    simulation SIGNALS — *before* any prose is written.

    This forces MECE probabilistic discipline up front and yields a spine whose
    scenarios+probabilities+resolution_criteria each later report section must
    defend, rather than reverse-engineering numbers out of finished narrative.
    Same output shape as ``extract_structured_forecast`` plus ``derived_from='spine'``.
    Degrade-safe: a malformed reply yields a well-formed empty forecast; the caller
    wraps in try/except and falls back to the post-hoc extractor.

    Optional enhancements (all inert unless their flag + input are supplied):
      * ``base_distribution`` — WorldState.shares anchor (R2-CAL-3) used to constrain
        the scenario set + probability band and to compute per-scenario divergence
        (R2-CAL-18); echoed into the output as ``base_distribution``.
      * ``quantitative_facts`` — S-tier metric digest (R2-CAL-16) requiring anchors to
        cite a metric + as-of date.
      * ``REPORT_SPINE_SELFCONSISTENCY_K`` — K self-consistency draws pooled to
        mean + spread (R2-CAL-1 / R2-CAL-17).
      * ``official_data`` — the stored carrier: adds the empirical outside view from
        official history and asks for an optional per-scenario ``metric_range``,
        validated against the carrier (invalid ranges are dropped).
    """
    # R2-DETAIL-3：每块输入上限可配置。RQ-4：signal/inputs 两块 4000→6000（骨架情景/概率
    # 由这两块驱动，4000 会把驱动因素与量化信号截断，让骨架欠地气）；brief/facts 维持旧值。
    from .ensemble import freeze_report_policy
    policy = freeze_report_policy(report_policy)
    cap_brief = int(_cfg("REPORT_SPINE_INPUT_CAP_BRIEF", 2000))
    cap_inputs = int(_cfg("REPORT_SPINE_INPUT_CAP_INPUTS", 6000))
    cap_signal = int(_cfg("REPORT_SPINE_INPUT_CAP_SIGNAL", 6000))
    cap_facts = int(_cfg("REPORT_SPINE_INPUT_CAP_FACTS", OFFICIAL_PACK_PROMPT_CAP))
    user = _SPINE_INSTRUCTIONS
    if central_question:
        user += f"\n\n[核心问题]\n{central_question[:600]}"
    if horizon:
        user += f"\n\n[预测时间范围]\n{horizon[:120]}"
    if situation_brief:
        user += f"\n\n[态势简报]\n{situation_brief[:cap_brief]}"
    if forecast_inputs:
        user += f"\n\n[研究输入：参考类基率 / 驱动因素 / 观察指标 / 候选情景]\n{forecast_inputs[:cap_inputs]}"
    if signal_pack:
        user += f"\n\n[模拟量化信号]\n{signal_pack[:cap_signal]}"
    # 预测市场校准锚点（Polymarket 公开 Gamma API）：市场隐含概率是外部视角的
    # 聚合信念——与所列市场重叠的情景概率应对照之，偏离 >10 个百分点须在
    # adjustment_rationale 说明依据（市场是校准锚点，不是真值）。空串时提示词不变。
    if market_block:
        # PM-2：市场块切片 2500→6000，让相关性门控后的更多市场进入骨架校准视野。
        user += ("\n\n[预测市场隐含概率（Polymarket 实盘·校准锚点，非真值）]\n"
                 + str(market_block)[:6000]
                 + "\n与上述市场重叠的情景，其概率须对照市场隐含概率；偏离超过 10 个百分点时"
                   "在 adjustment_rationale 中显式解释分歧（市场遗漏/错价了什么）。")
    # R2-CAL-16：S 级量化事实数字底座，要求锚点引用 指标 + as_of 日期。
    if quantitative_facts:
        user += ("\n\n[S级量化事实（数字底座，base_rate_anchor 须引用其中的 指标+as_of 日期）]\n"
                 + _cap_at_line(str(quantitative_facts), cap_facts))
    # 官方数据外部视角 + 情景量化区间（仅在传入已存储官方数据时追加；缺省提示词逐字节不变）。
    if official_data:
        outside_view = official_outside_view_block(official_data, horizon, language or "Chinese")
        if outside_view:
            user += "\n\n" + outside_view
        user += _SPINE_METRIC_RANGE_RULE
    # R2-CAL-3：把模拟得到的 WorldState.shares 作为基准分布锚点，约束情景集合与概率带。
    anchor_ws = bool(_cfg("REPORT_SPINE_ANCHOR_WORLDSTATE", False)) and isinstance(base_distribution, dict)
    if anchor_ws and base_distribution:
        shares_txt = "；".join(f"{k}={float(v):.2f}" for k, v in base_distribution.items()
                              if _coerce_float(v) is not None)
        if shares_txt:
            user += ("\n\n[基准分布锚点（模拟 WorldState 份额，先验）]\n" + shares_txt
                     + "\n请以此为外部视角先验：沿用相同情景集合，最终概率应落在各自份额的合理带内"
                       "（偏离须在 adjustment_rationale 中给出具体证据）。")

    user += forecast_language_rule(language)

    max_tokens = int(_cfg("REPORT_SPINE_MAX_TOKENS", 6144))  # R2-CAL-11: 2048→6144
    floor = _coerce_float(_cfg("FORECAST_PROB_FLOOR", 0.0)) or 0.0
    try:
        k = int(policy["report_spine_selfconsistency_k"] if policy is not None else
                (_cfg("REPORT_SPINE_SELFCONSISTENCY_K", 1) or 1))
    except (TypeError, ValueError):
        k = 1
    k = max(1, k)

    keep_ranges = bool(official_data)
    first = _spine_draw(llm, user, 0.2, max_tokens, keep_metric_range=keep_ranges)
    if not first.get("scenarios"):
        # R2-CAL-11：骨架为空 → 告警并重试一次后再让上层回退成稿后抽取。
        logger.warning("预测骨架首轮无情景，重试一次")
        first = _spine_draw(llm, user, 0.2, max_tokens, keep_metric_range=keep_ranges)

    draws = [first]
    if k > 1 and first.get("scenarios"):
        names = [str(s.get("name")) for s in first["scenarios"] if isinstance(s, dict)]
        follow = user + ("\n\n[已确定情景集合：请沿用完全相同的情景名，仅独立重新估计各自概率"
                         "（其和≈1），不要新增或重命名情景]\n" + "；".join(names))
        for i in range(1, k):
            temp = min(0.9, 0.2 + 0.15 * i)  # varied temperature for diversity
            d = _spine_draw(llm, follow, temp, max_tokens, keep_metric_range=keep_ranges)
            if d.get("scenarios"):
                draws.append(d)

    out = _pool_spine_draws(draws, floor) if len(draws) > 1 else first
    out["derived_from"] = "spine"
    for scenario in out.get("scenarios") or []:
        if isinstance(scenario, dict) and "metric_range" in scenario:
            metric_range = validate_metric_range(scenario.pop("metric_range"), official_data)
            if metric_range is not None:
                scenario["metric_range"] = metric_range

    # R2-CAL-3 echo + R2-CAL-18 per-scenario model-vs-sim divergence.
    if anchor_ws and base_distribution and out.get("scenarios"):
        from .ensemble import _norm_name
        bd_keyed = {_norm_name(k2): _coerce_float(v) for k2, v in base_distribution.items()}
        out["base_distribution"] = {str(k2): float(v) for k2, v in base_distribution.items()
                                    if _coerce_float(v) is not None}
        divergences = []
        for s in out["scenarios"]:
            ws = bd_keyed.get(_norm_name(s.get("name")))
            if ws is None:
                continue
            d = abs((_coerce_float(s.get("probability")) or 0.0) - ws)
            s["worldstate_divergence"] = round(d, 4)
            thin = (s.get("self_consistency_n", 1) or 1) <= 1
            if d >= 0.2:
                # widen the published interval & demote confidence on thin-evidence divergence.
                lo = _coerce_float(s.get("p_low"))
                hi = _coerce_float(s.get("p_high"))
                p = _coerce_float(s.get("probability")) or 0.0
                s["p_low"] = round(max(0.0, min(lo if lo is not None else p, p) - d / 2), 4)
                s["p_high"] = round(min(1.0, max(hi if hi is not None else p, p) + d / 2), 4)
                if thin:
                    divergences.append({"name": str(s.get("name")), "divergence": round(d, 4)})
        if divergences:
            out.setdefault("quality", {})["model_vs_sim_divergence"] = divergences
            if out.get("confidence") == "high":
                out["confidence"] = "medium"
    # VIZ-GAP1(a)：给池化区间补显式溯源标记（K=1 时无 self_consistency_k → no-op）。
    return apply_self_consistency_intervals(out)


def render_forecast_spine_block(forecast: Optional[Dict[str, Any]], max_scenarios: int = 6) -> str:
    """Render a compact, authoritative spine block to pin into each section prompt.

    Empty forecast / no scenarios → "" (so the prefix injection is a no-op and the
    section prompt is byte-identical to the pre-spine path). NEXTSTEPS P0-1.
    """
    if not isinstance(forecast, dict):
        return ""
    scenarios = forecast.get("scenarios") or []
    if not scenarios:
        return ""
    lines = [
        "【预测骨架（权威·先于叙事确定，本章撰写须对齐并捍卫所分配的概率）】",
    ]
    headline = str(forecast.get("headline") or "").strip()
    horizon = str(forecast.get("horizon") or "").strip()
    if headline:
        lines.append(f"核心结论：{headline}" + (f"（时间范围 {horizon}）" if horizon else ""))
    for s in scenarios[:max_scenarios]:
        if not isinstance(s, dict):
            continue
        try:
            pct = f"{float(s.get('probability') or 0.0) * 100:.0f}%"
        except (TypeError, ValueError):
            pct = "—"
        name = str(s.get("name") or "未命名情景")
        crit = str(s.get("resolution_criteria") or "").strip()
        line = f"· [{pct}] {name}"
        if crit:
            line += f" — 判定：{crit[:160]}"
        lines.append(line)
    conf = str(forecast.get("confidence") or "").strip()
    if conf:
        lines.append(f"整体信心：{conf}")
    lines.append(
        "撰写本章时：凡涉及上述情景的论断须与所分配概率一致；若本章证据要求调整某情景概率，"
        "请显式说明依据，不得无声偏离骨架。"
    )
    return "\n".join(lines)


def _esc_cell(x: Any) -> str:
    """markdown 表格单元转义（管道符/换行）。"""
    return str(x).replace("|", "／").replace("\n", " ").strip()


def render_binary_forecasts_block(forecast: Optional[Dict[str, Any]],
                                  language: str = "English") -> str:
    """QUALITY-OPT B1: render a DETERMINISTIC 'Part 1 — Binary Forecasts' table.

    Deterministic (no LLM) so the brief's headline deliverable always appears in the report
    AND always matches forecast.json exactly (kills prose↔json probability drift). Empty
    binary list → "" (degrade-safe: nothing injected). Bilingual headers track output language.
    """
    if not isinstance(forecast, dict):
        return ""
    binaries = forecast.get("binary_forecasts") or []
    if not binaries:
        return ""
    zh = not str(language or "").lower().startswith("en")
    # 预测市场锚点列：任一预测带 market_anchor 时追加「市场隐含 P(yes)」列（预测 vs 市场
    # 对照）；全无锚点时不加列，表格与历史逐字节一致（degrade-safe）。
    has_anchor = any(isinstance(b, dict) and isinstance(b.get("market_anchor"), dict)
                     for b in binaries)
    if zh:
        head = "## 第一部分 · 二元预测（Part 1 — Binary Forecasts）"
        intro = ("以下为可独立判定的二元（是/否）预测，每条含概率与客观判定标准"
                 "（指标·阈值·日期·来源）。概率反映真实研判，非对冲。")
        cols = "| # | 预测（一句话） | 概率 | 判定标准 | 主题 |"
        anchor_col = " 市场隐含 P(yes)（Polymarket） |"
    else:
        head = "## Part 1 — Binary Forecasts"
        intro = ("Independent binary (yes/no) forecasts, each with a probability and an "
                 "objective resolution test (metric · threshold · date · source). "
                 "Probabilities express genuine conviction, not hedging.")
        cols = "| # | Forecast (one sentence) | Prob. | Resolution criteria | Theme |"
        anchor_col = " Market P(yes) (Polymarket) |"
    sep = "|---|---|---|---|---|"
    if has_anchor:
        cols += anchor_col
        sep += "---|"
        intro += ("其中标注市场隐含概率的预测可与真实预测市场对照（市场为校准锚点，非真值）。"
                  if zh else
                  " Forecasts with a market-implied probability are benchmarked against live "
                  "prediction markets (markets are calibration anchors, not ground truth).")
    # 官方数据经验基率列：任一预测的 data_anchor 带 empirical_base_rate 时追加（外部视角，
    # 不改概率）；全无时不加列，表格逐字节不变。
    has_base_rate = any(isinstance(b, dict) and isinstance(b.get("data_anchor"), dict)
                        and isinstance(b["data_anchor"].get("empirical_base_rate"), dict) for b in binaries)
    if has_base_rate:
        cols += " 官方数据经验基率 |" if zh else " Official-data base rate |"
        sep += "---|"
        intro += ("经验基率＝历史上从最新完整观测出发、同样期数的变化中满足阈值的比例（外部视角，非预测）。"
                  if zh else
                  " The official-data base rate is the share of past moves over the same number of "
                  "periods, applied to the latest complete observation, that meet the threshold "
                  "(an outside view, not a forecast).")
    lines = [head, "", intro, "", cols, sep]
    # ITEM 12：多模型集成开启时，概率列以 ±spread（跨模型样本 stdev）显示分歧；spread 超阈值
    # （binary_quality.ensemble.spread_threshold，缺省 0.15）的预测加 ⚠ 低一致性标记。无 ensemble
    # 块（默认单模型）→ 概率列逐字节不变（degrade-safe）。
    _ens_meta = (forecast.get("binary_quality") or {}).get("ensemble") if isinstance(
        forecast.get("binary_quality"), dict) else None
    _ens_thr = _coerce_float((_ens_meta or {}).get("spread_threshold"))
    if _ens_thr is None:
        _ens_thr = 0.15
    for b in binaries:
        if not isinstance(b, dict):
            continue
        try:
            pct = f"{float(b.get('probability') or 0.0) * 100:.0f}%"
        except (TypeError, ValueError):
            pct = "—"
        _ens = b.get("ensemble")
        if isinstance(_ens, dict):
            _spread = _coerce_float(_ens.get("spread"))
            if _spread is not None and _spread > 0:
                pct += f" ±{_spread * 100:.0f}%"
                if _spread > _ens_thr:
                    pct += " ⚠"
        line = "| {id} | {st} | {p} | {rc} | {th} |".format(
            id=_esc_cell(b.get("id") or ""),
            st=_esc_cell(b.get("statement") or ""),
            p=pct,
            # WAVE9：去掉 [:200] 硬截断——判定标准被切成 'used in Q3 202' 型断句是交付缺陷；
            # _esc_cell 已转义管道符/换行，长单元格由渲染端自然换行。
            rc=_esc_cell(str(b.get("resolution_criteria") or "")),
            th=_esc_cell(b.get("theme") or ""),
        )
        if has_anchor:
            anchor = b.get("market_anchor")
            cell = "—"
            if isinstance(anchor, dict):
                ip = _coerce_float(anchor.get("implied_yes_prob"))
                dv = _coerce_float(anchor.get("divergence"))
                if ip is not None:
                    cell = f"{ip * 100:.0f}%"
                    if dv is not None:
                        cell += f" (Δ{dv * 100:+.0f}pt)"
            line += f" {_esc_cell(cell)} |"
        if has_base_rate:
            line += f" {_esc_cell(_base_rate_cell(b, zh))} |"
        lines.append(line)
    q = forecast.get("binary_quality") or {}
    if q:
        if zh:
            lines += ["", (f"_共 {q.get('count')} 条；高研判（≥70% 或 ≤30%）{q.get('conviction_count')} 条；"
                           f"客观判定 {q.get('sharp_criteria_count')} 条。_")]
        else:
            lines += ["", (f"_{q.get('count')} forecasts; {q.get('conviction_count')} high-conviction "
                           f"(≥70% or ≤30%); {q.get('sharp_criteria_count')} with objective criteria._")]
    # ITEM 12：集成低一致性脚注——列出跨模型 spread 超阈值的预测 id（±spread 已在概率列高亮）。
    _ens_meta2 = q.get("ensemble") if isinstance(q, dict) else None
    if isinstance(_ens_meta2, dict) and _ens_meta2.get("low_agreement"):
        _la = ", ".join(str(x) for x in _ens_meta2.get("low_agreement") or [])
        _pm = ", ".join(str(x) for x in _ens_meta2.get("pooled_models") or [])
        if zh:
            lines += ["", (f"_多模型集成（{_pm}）：{_la} 存在跨模型分歧（±spread 超 "
                           f"{_ens_meta2.get('spread_threshold')}，概率列以 ⚠ 标记，谨慎解读）。_")]
        else:
            lines += ["", (f"_Multi-model ensemble ({_pm}): {_la} show cross-model disagreement "
                           f"(spread > {_ens_meta2.get('spread_threshold')}, flagged ⚠ in the "
                           f"probability column — interpret with caution)._")]
    return "\n".join(lines)


def _base_rate_cell(binary: Dict[str, Any], zh: bool) -> str:
    anchor = binary.get("data_anchor") if isinstance(binary.get("data_anchor"), dict) else {}
    base = anchor.get("empirical_base_rate")
    if not isinstance(base, dict) or not isinstance(base.get("p"), (int, float)):
        return "—"
    note = empirical_seasonal_note(base, zh)
    if zh:
        return f"{base['p'] * 100:.0f}%（n={base.get('n')}，{base.get('h')} 期" + (f"；{note}" if note else "") + "）"
    return f"{base['p'] * 100:.0f}% (n={base.get('n')}, h={base.get('h')}" + (f"; {note}" if note else "") + ")"


def upsert_binary_forecasts_block(markdown: str, block: str) -> tuple[str, str]:
    """Insert or replace the deterministic Part-1 H2 section.

    Earlier runs hard-truncated resolution cells and the old report finalizer
    treated the mere presence of the heading as an idempotency success.  This
    helper makes the structured ``forecast.json`` block authoritative on every
    finalization while leaving all other H2 sections byte-for-byte intact.
    Returns ``(markdown, action)`` where action is replaced/inserted/noop.
    """
    md = str(markdown or "")
    rendered = str(block or "").strip()
    if not rendered:
        return md, "noop"
    start_marker = "<!-- binary-forecast-block:start -->"
    end_marker = "<!-- binary-forecast-block:end -->"
    owned = f"{start_marker}\n{rendered}\n{end_marker}"
    owned_start = md.find(start_marker)
    owned_end = md.find(end_marker, owned_start + len(start_marker))
    if owned_start >= 0 and owned_end >= 0:
        owned_end += len(end_marker)
        updated = md[:owned_start] + owned + md[owned_end:]
        return updated, "noop" if updated == md else "replaced"
    lines = md.splitlines()
    marker_re = re.compile(
        r"^##\s+(?:Part 1\s+[—-]\s+Binary Forecasts|"
        r"第一部分\s*[·・]\s*二元预测(?:（Part 1\s+[—-]\s+Binary Forecasts）)?)\s*$",
        re.I,
    )
    start = next((i for i, line in enumerate(lines) if marker_re.match(line.strip())), -1)
    if start >= 0:
        end = start + 1
        while end < len(lines) and not re.match(r"^##\s+\S", lines[end].strip()):
            end += 1
        before = "\n".join(lines[:start]).rstrip()
        after = "\n".join(lines[end:]).lstrip()
        pieces = [piece for piece in (before, owned, after) if piece]
        return "\n\n".join(pieces).rstrip() + "\n", "replaced"

    first, sep, rest = md.partition("\n")
    if first.lstrip().startswith("# "):
        suffix = rest.lstrip("\n") if sep else ""
        result = first.rstrip() + "\n\n" + owned
        if suffix:
            result += "\n\n" + suffix
        return result.rstrip() + "\n", "inserted"
    result = owned + ("\n\n" + md.lstrip() if md.strip() else "")
    return result.rstrip() + "\n", "inserted"


def render_resolution_block(forecast: Optional[Dict[str, Any]],
                            indicators: Optional[List[Dict[str, Any]]] = None,
                            language: str = "Chinese",
                            official_data: Optional[Dict[str, Any]] = None,
                            source_index: Optional[Dict[str, Any]] = None) -> str:
    """NEXTSTEPS P2-2: 渲染一个**确定性**的「如何验证本预测」章节。

    逐情景列出可证伪的判定标准 + 来自 forecast_inputs 的带日期/触发型观察指标（并把指标绑定到
    它所判别的情景）。一个没有明确、可观测、带日期指标的预测无法被追踪或打分——这正是"利率可能
    上升" vs "若指标 X 于日期 Z 前超过 Y，则情景 A 确认"的区别。forecast 无情景 → ""（不追加）。

    WAVE9：新增 language 参数（默认 "Chinese"，与历史输出逐字节一致）——此前标题/表头硬编码
    中文，英文报告末尾出现整段中文章节。调用方（report_agent）传入报告输出语言。

    官方观察序列表：最近完整历史观测与数据包/图表同源（official_latest_observed），数值经
    format_value 格式化（大额附量级），附经验基率；传入 ``source_index``（报告引文索引）时
    来源列带 [S#]。
    """
    if not isinstance(forecast, dict):
        return ""
    scenarios = forecast.get("scenarios") or []
    if not scenarios:
        return ""
    zh = not str(language or "").strip().lower().startswith("en")
    if zh:
        lines = [
            "## 如何验证本预测（判定标准与观察指标）",
            "本节给出每个情景**可证伪、可追踪**的判定标准与到期/触发型观察指标，供日后核对与校准。",
            "",
            "### 各情景判定标准",
        ]
    else:
        lines = [
            "## How to Verify This Forecast (Resolution Criteria & Indicators)",
            "This section lists **falsifiable, trackable** resolution criteria for each scenario, "
            "plus dated/triggered indicators for future scoring and calibration.",
            "",
            "### Per-Scenario Resolution Criteria",
        ]
    for s in scenarios:
        if not isinstance(s, dict):
            continue
        try:
            pct = f"{float(s.get('probability') or 0.0) * 100:.0f}%"
        except (TypeError, ValueError):
            pct = "—"
        name = str(s.get("name") or ("未命名情景" if zh else "Unnamed scenario"))
        crit = str(s.get("resolution_criteria") or "").strip() or (
            "（缺明确判定标准——需补全）" if zh
            else "(no explicit resolution criteria — needs completion)")
        sep = "：" if zh else ": "
        lines.append(f"- **[{pct}] {name}**{sep}{crit}")
    inds = [i for i in (indicators or []) if isinstance(i, dict)]
    if inds:
        lines.append("")
        if zh:
            lines.append("### 观察指标（到期/触发即核对）")
            lines.append("| 指标 | 到期/触发 | 关联情景 |")
        else:
            lines.append("### Indicators to Watch (check at expiry/trigger)")
            lines.append("| Indicator | Due / trigger | Discriminates scenario |")
        lines.append("|---|---|---|")
        for i in inds[:20]:
            name = _esc_cell(i.get("indicator") or i.get("name") or i.get("metric") or "—")
            trig = _esc_cell(i.get("date_or_trigger") or i.get("date") or i.get("trigger") or "—")
            disc = _esc_cell(i.get("discriminates") or i.get("scenario") or "—")
            lines.append(f"| {name or '—'} | {trig or '—'} | {disc or '—'} |")
    if official_data:
        from .official_data import validate_data_anchor
        binaries = forecast.get("binary_forecasts")
        binaries = binaries if isinstance(binaries, list) else []
        rows = {row["series"]: row for row in official_series_rows(official_data)}
        anchored = []
        for binary in binaries:
            if not isinstance(binary, dict):
                continue
            anchor = validate_data_anchor(binary.get("data_anchor"), official_data)
            if anchor and anchor["series"] in rows and _data_anchor_matches_binary(anchor, binary, official_data):
                anchored.append((anchor, binary))
        if anchored:
            lines += ["", "### 官方观察序列" if zh else "### Official series to watch",
                      ("| 序列 | 最近完整历史观测 | 模型阈值 / 观察期 | 经验基率 vs 模型概率 | 来源 |" if zh else
                       "| Series | Latest complete historical observation | Model threshold / period | "
                       "Empirical base rate vs model P | Source |"),
                      "|---|---|---|---|---|"]
            for anchor, binary in anchored[:12]:
                lines.append(_official_watch_row(anchor, binary, rows[anchor["series"]], zh, source_index))
    return "\n".join(lines)


def _official_watch_row(anchor: Dict[str, Any], binary: Dict[str, Any], row: Dict[str, Any], zh: bool,
                        source_index: Optional[Dict[str, Any]]) -> str:
    """One 'Official series to watch' row from the stored carrier (never model-transcribed values)."""
    from .official_data import data_api
    api = data_api()
    units = str(row["units"])
    percent = bool(api and api.is_percent_units(units))

    def shown(value: float) -> str:
        text = api.format_value(value, units) if api is not None else str(value)
        scaled = api.scaled_value(value, units, "zh" if zh else "en") if api is not None else ""
        return text + ("" if percent else f" {units}") + (f"（{scaled}）" if zh and scaled else f" ({scaled})" if scaled else "")

    label = api.series_label(row, "zh" if zh else "en") if api is not None else row["series"]
    series = f"{label}（{row['series']}）" if zh else f"{label} ({row['series']})"
    latest = official_latest_observed(row)
    if latest:
        latest_period = official_anchor_period_text(row, latest["date"], row["frequency"])
        latest_text = (f"{shown(latest['value'])}（{latest_period}）" if zh
                       else f"{shown(latest['value'])} ({latest_period})")
    else:
        latest_text = "暂无历史观测" if zh else "Historical observation unavailable"
    threshold = (f"{anchor['comparator']} {shown(anchor['threshold'])} / "
                 f"{official_anchor_period_text(row, anchor['period'], anchor['frequency'])}")
    base = official_empirical_base_rate(row, anchor)
    probability = _coerce_float(binary.get("probability"))
    model = f"{probability * 100:.0f}%" if probability is not None else "—"
    if base:
        note = empirical_seasonal_note(base, zh)
        base_text = (f"{base['p'] * 100:.0f}%（n={base['n']}，{base['h']} 期" + (f"；{note}" if note else "")
                     + f"）vs 模型 {model}" if zh
                     else f"{base['p'] * 100:.0f}% (n={base['n']}, h={base['h']}" + (f"; {note}" if note else "")
                     + f") vs model {model}")
    else:
        base_text = (f"历史样本不足 vs 模型 {model}" if zh else f"insufficient history vs model {model}")
    tag = official_source_tag(row, source_index) if isinstance(source_index, dict) and source_index else ""
    url = str(row.get("source_url") or "")
    source = f"[{'来源' if zh else 'Source'}](<{url}>)" + (f" [{tag}]" if tag else "")
    return (f"| {_esc_cell(series)} | {_esc_cell(latest_text)} | {_esc_cell(threshold)} | "
            f"{_esc_cell(base_text)} | {source} |")


_CRITIQUE_INSTRUCTIONS = """你是预测红队评审。下面是一个结构化预测对象（JSON）。请审查并修正它，重点检查：
1) 过度自信：是否有情景概率过高而证据不足？向不确定性回归（base-rate）。
2) 基率忽视：是否忽略了历史基率/惯性情景？
3) 无支撑的跳跃：resolution_criteria 是否客观可验证？
4) 互斥穷尽：情景是否互斥、是否需要补一个「其它/维持现状」兜底情景？
输出修正后的**同样结构**的 JSON（headline/horizon/scenarios[name,probability,summary,key_drivers,resolution_criteria]/
key_uncertainties/confidence/confidence_rationale），并在每个情景加一个 "critique_note" 字段说明你的调整。
只输出 JSON。概率之和应≈1。"""


def self_critique_forecast(forecast: Dict[str, Any], llm, language: str = "",
                           data_pack: str = "") -> Dict[str, Any]:
    """Red-team + recalibrate a structured forecast (EXECPLAN2 I-3-5).

    Runs one adversarial LLM pass that pushes back on overconfidence / base-rate
    neglect / unsupported leaps and may add a status-quo fallback scenario, then
    re-normalizes. Returns a new forecast dict tagged ``critiqued=True``; on any
    failure returns the input unchanged (degrade-safe). ``data_pack`` (stored
    official data and its outside view) is appended as a fixed suffix block so the
    base-rate check can use it; validated scenario ``metric_range`` values survive
    by scenario name and the critique cannot invent new ones.
    """
    import json as _json
    try:
        raw = llm.chat_json(
            messages=[{"role": "user",
                       "content": _CRITIQUE_INSTRUCTIONS + "\n\n[预测对象]\n"
                       + _json.dumps(forecast, ensure_ascii=False)
                       + _official_context_suffix(data_pack)
                       + forecast_language_rule(language)}],
            temperature=0.2,
            max_tokens=2048,
        )
        if not isinstance(raw, dict):
            return forecast
        critique_scenarios = raw.get("scenarios")
        if not isinstance(critique_scenarios, list) or not critique_scenarios:
            return forecast
        out = dict(forecast)
        raw_scenarios, residual_added = _ensure_residual_critique_scenario(
            critique_scenarios, forecast,
        )
        if raw_scenarios is None:
            return forecast
        out["scenarios"] = _normalize_scenarios(raw_scenarios)
        if not out["scenarios"]:
            return forecast
        # preserve critique_note per scenario if the model supplied it
        for new_s, raw_s in zip(out["scenarios"], raw_scenarios or [], strict=True):
            if isinstance(raw_s, dict) and raw_s.get("critique_note"):
                new_s["critique_note"] = str(raw_s["critique_note"])
        ranges = {s.get("name"): s["metric_range"] for s in forecast.get("scenarios") or []
                  if isinstance(s, dict) and isinstance(s.get("metric_range"), dict)}
        for new_s in out["scenarios"]:
            if new_s.get("name") in ranges:
                new_s["metric_range"] = ranges[new_s["name"]]
        if raw.get("confidence"):
            c = str(raw["confidence"]).lower()
            if c in ("low", "medium", "high"):
                out["confidence"] = c
        if raw.get("confidence_rationale"):
            out["confidence_rationale"] = str(raw["confidence_rationale"])
        # R2-CAL-8：让红队评审「谦逊单调」——修正只能降低、不得抬高峰值自信。若评审反而把
        # 最高概率推得比原来更高，则把峰值夹回原始上限并重新归一（cap residual growth）。
        out["scenarios"] = _enforce_humility_monotone(forecast, out["scenarios"])
        _synchronize_scenario_probability_narratives(out["scenarios"])
        if residual_added:
            out["residual_scenario_added"] = True
            original_rationale = str(out.get("confidence_rationale") or "").strip()
            if original_rationale:
                out["confidence_rationale_detail"] = original_rationale
            confidence = str(out.get("confidence") or "medium").strip().capitalize()
            out["confidence_rationale"] = (
                f"{confidence} confidence after red-team calibration. The named scenarios "
                "plus an explicit residual/status-quo bin form a complete 100% partition; "
                "remaining uncertainty reflects evidence quality, forecast-horizon length, "
                "and unresolved policy and technology branches."
            )
        if audit_scenario_contract(out).get("valid") is not True:
            return forecast
        out["critiqued"] = True
        # VIZ-GAP1(a)：_normalize_scenarios 剥掉了池化的 p_low/p_high——发布前从顶层
        # self_consistency 数据确定性重建区间（K<2/缺 spread 时 no-op，绝不编造）。
        return apply_self_consistency_intervals(out)
    except Exception:
        return forecast


def _close_probability_rounding(
    scenarios: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Close four-decimal probability rounding on one deterministic row."""
    if not scenarios:
        return scenarios
    probabilities = [_coerce_float(row.get("probability")) for row in scenarios]
    if any(probability is None for probability in probabilities):
        return scenarios
    rounded = [round(float(probability), 4) for probability in probabilities]
    correction = round(1.0 - sum(rounded), 4)
    target_index = next(
        (
            index
            for index, row in enumerate(scenarios)
            if _is_residual_scenario_name(row.get("name"))
        ),
        len(scenarios) - 1,
    )
    adjusted = rounded[target_index] + correction
    if not 0.0 <= adjusted <= 1.0:
        return scenarios
    for row, probability in zip(scenarios, rounded, strict=True):
        row["probability"] = probability
    scenarios[target_index]["probability"] = round(adjusted, 4)
    return scenarios


def _enforce_humility_monotone(orig: Dict[str, Any],
                               new_scenarios: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Clamp a critiqued scenario set so its peak probability never EXCEEDS the
    original peak (a red-team pass must not manufacture more confidence). Renormalizes
    after clamping. Pure; returns the (possibly) adjusted list. R2-CAL-8.
    """
    orig_probs = [_coerce_float(s.get("probability")) or 0.0
                  for s in (orig.get("scenarios") or []) if isinstance(s, dict)]
    if not orig_probs or len(new_scenarios) < 2:
        return _close_probability_rounding(new_scenarios)
    orig_max = max(orig_probs)
    peak = max(new_scenarios, key=lambda s: _coerce_float(s.get("probability")) or 0.0)
    cur_max = _coerce_float(peak.get("probability")) or 0.0
    if cur_max <= orig_max + 1e-9:
        return _close_probability_rounding(new_scenarios)
    # Cap the peak at the original peak and redistribute the FREED mass across the
    # other scenarios proportionally (a plain renormalize would re-inflate the peak).
    excess = cur_max - orig_max
    others = [s for s in new_scenarios if s is not peak]
    other_total = sum((_coerce_float(s.get("probability")) or 0.0) for s in others)
    peak["probability"] = round(orig_max, 4)
    if other_total > 0:
        for s in others:
            p = _coerce_float(s.get("probability")) or 0.0
            s["probability"] = round(p + excess * (p / other_total), 4)
    return _close_probability_rounding(new_scenarios)


_PREMORTEM_INSTRUCTIONS = """你是预测红队的「事前验尸（pre-mortem）」分析师。假设到期时这份预测被证明**严重错误**。
请回答：(1) 最可能是哪个被低估的情景实际发生了？(2) 我们忽略了哪些信号/基率/尾部风险？
(3) 哪个情景的概率显得过度自信、应当向不确定性回归？只输出 JSON：
{ "underweighted_scenario": "情景名（须取自给定情景集合）", "missed_signals": ["...", ...],
  "overconfident_scenario": "情景名（可空）" }"""


def premortem_forecast(forecast: Dict[str, Any], llm, language: str = "",
                       data_pack: str = "") -> Dict[str, Any]:
    """R2-CAL-8 pre-mortem: imagine the forecast failed badly, surface missed signals,
    and gently widen uncertainty (append key_uncertainties + shave the overconfident
    peak toward the underweighted scenario, bounded). Gated by REPORT_PREMORTEM; on any
    failure returns the input unchanged (degrade-safe). ``data_pack`` is appended as a
    fixed suffix block ("" leaves the prompt unchanged).
    """
    if not _cfg("REPORT_PREMORTEM", False):
        return forecast
    import json as _json
    try:
        scenarios = [s for s in (forecast.get("scenarios") or []) if isinstance(s, dict)]
        if not scenarios:
            return forecast
        raw = llm.chat_json(
            messages=[{"role": "user",
                       "content": _PREMORTEM_INSTRUCTIONS + "\n\n[预测对象]\n"
                       + _json.dumps(forecast, ensure_ascii=False)
                       + _official_context_suffix(data_pack)
                       + forecast_language_rule(language)}],
            temperature=0.3,
            max_tokens=1024,
        )
        if not isinstance(raw, dict):
            return forecast
        out = dict(forecast)
        out["scenarios"] = [dict(s) for s in scenarios]
        from .ensemble import _norm_name
        missed = [str(x) for x in (raw.get("missed_signals") or []) if x]
        if missed:
            ku = list(out.get("key_uncertainties") or [])
            for m in missed:
                if m not in ku:
                    ku.append(m)
            out["key_uncertainties"] = ku[:12]
        # bounded transfer: shave up to 0.05 off the overconfident peak toward the
        # underweighted scenario, then renormalize (humility, capped residual growth).
        over = _norm_name(raw.get("overconfident_scenario"))
        under = _norm_name(raw.get("underweighted_scenario"))
        if over and under and over != under:
            src = next((s for s in out["scenarios"] if _norm_name(s.get("name")) == over), None)
            dst = next((s for s in out["scenarios"] if _norm_name(s.get("name")) == under), None)
            if src and dst:
                p_src = _coerce_float(src.get("probability")) or 0.0
                shift = min(0.05, p_src * 0.25)
                src["probability"] = round(p_src - shift, 4)
                dst["probability"] = round((_coerce_float(dst.get("probability")) or 0.0) + shift, 4)
        _synchronize_scenario_probability_narratives(out["scenarios"])
        out["premortem"] = {"underweighted_scenario": str(raw.get("underweighted_scenario") or ""),
                            "missed_signals": missed[:8]}
        # VIZ-GAP1(a)：概率被谦逊转移后旧区间可能不再包住 p——先作废再按 ±spread 重建。
        for s in out["scenarios"]:
            p = _coerce_float(s.get("probability"))
            lo = _coerce_float(s.get("p_low"))
            hi = _coerce_float(s.get("p_high"))
            if p is not None and lo is not None and hi is not None \
                    and not lo <= p <= hi:
                s.pop("p_low", None)
                s.pop("p_high", None)
                s.pop("interval_source", None)
        return apply_self_consistency_intervals(out)
    except Exception:
        return forecast


# ---------------------------------------------------------------- citation audit
# Citation coverage is measured at the smallest deterministic Markdown claim
# surface we can preserve: prose sentences and individual table body cells.
# A marker in one sentence/cell must never launder a neighboring numeric claim.
_CITATION_RE = re.compile(r"[\[【]\s*S\d+\s*[\]】]", re.I)
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?\s*%|\b\d{2,}(?:\.\d+)?\b|\b\d{4}年")
# REPORT-6：模拟/图谱接地标记也算作有效接地——agent 言行引用（> "…"）、因果边渲染
# （--[REL, …]-->）、以及 [sim_id]/【模拟】/【图谱】/[E\d] 等模拟与边引用标记。
_SIM_GROUNDING_RE = re.compile(
    r">\s*[\"“]"
    r"|--\[[^\]]*\]-->"
    r"|[\[【]\s*(?:SIM|sim_id|E\d+|EDGE|模拟|图谱|图|边)\b",
    re.I)


BINARY_FORECAST_START_MARKER = "<!-- binary-forecast-block:start -->"
BINARY_FORECAST_END_MARKER = "<!-- binary-forecast-block:end -->"

_AUTHORED_FORECAST_H2_RE = re.compile(
    r"^(?:"
    r"##\s+Part\s*1\s*[—-]\s*Binary\s+Forecasts|"
    r"##\s+第一部分\s*[·・]\s*二元预测"
    r"(?:[（(]Part\s*1\s*[—-]\s*Binary\s+Forecasts[）)])?|"
    r"##\s+How\s+to\s+Verify\s+This\s+Forecast\s*"
    r"\(Resolution\s+Criteria\s*&\s*Indicators\)|"
    r"##\s+如何验证本预测（判定标准与观察指标）"
    r")\s*$",
    re.I,
)

_MARKDOWN_FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})(.*)$")
_MARKDOWN_TABLE_DELIMITER_CELL_RE = re.compile(r"^:?-{3,}:?$")
_QUANT_CLAIM_BOUNDARY_RE = re.compile(
    r"(?:"
    r"[!?;。！？；](?:\s*[\[【]\s*S\d+(?:-[A-Za-z])?\s*[\]】])*"
    r"[.!?;。！？；]?\s*(?=[A-Za-z0-9*_(`>\[\"'“‘（【\u3400-\u9fff])"
    r"|"
    r"\.(?!\d)(?:\s*[\[【]\s*S\d+(?:-[A-Za-z])?\s*[\]】])*"
    r"[.!?;]?\s+(?=[A-Za-z0-9*_(`>\[\"'“‘（【\u3400-\u9fff])"
    r")",
    re.I,
)
_LEADING_CITATION_FRAGMENT_RE = re.compile(
    r"^((?:[\[【]\s*S\d+(?:-[A-Za-z])?\s*[\]】]\s*)+)"
    r"([.,;:。！？]?\s*)(.*)$",
    re.I,
)
_DOTTED_INITIALISM_RE = re.compile(r"^(?:[A-Za-z]\.){2,}$")
_MARKDOWN_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*+] |\d+[.)] )")

# (opening character, minimum closing length); None means outside a fence.
MarkdownFenceState = Optional[Tuple[str, int]]


def markdown_fence_transition(
    line: Any,
    state: MarkdownFenceState,
) -> Tuple[MarkdownFenceState, bool]:
    """Advance a CommonMark-style fenced-block state machine.

    A fence closes only with the same character and at least the opening length.
    This prevents a literal ``~~~`` inside a backtick block (or vice versa) from
    flipping scanners back into report prose. ``bool`` identifies fence lines so
    callers can preserve/ignore them without treating their contents as claims.
    """
    match = _MARKDOWN_FENCE_RE.match(str(line or ""))
    if not match:
        return state, False
    token, remainder = match.group(1), match.group(2)
    marker = (token[0], len(token))
    if state is None:
        return marker, True
    if marker[0] == state[0] and marker[1] >= state[1] and not remainder.strip():
        return None, True
    return state, True


def markdown_table_cells(line: Any) -> List[str]:
    """Return cells for a Markdown row, with leading/trailing pipes optional."""
    stripped = str(line or "").strip()
    separators = list(re.finditer(r"(?<!\\)\|", stripped))
    if not separators:
        return []
    body = stripped[1:] if stripped.startswith("|") else stripped
    if body.endswith("|") and not body.endswith(r"\|"):
        body = body[:-1]
    cells = re.split(r"(?<!\\)\|", body)
    normalized = [cell.strip().replace(r"\|", "|") for cell in cells]
    return normalized if len(normalized) >= 2 else []


def is_markdown_table_delimiter(line: Any) -> bool:
    cells = markdown_table_cells(line)
    return bool(cells) and all(
        bool(_MARKDOWN_TABLE_DELIMITER_CELL_RE.fullmatch(cell.replace(" ", "")))
        for cell in cells
    )


def is_markdown_table_header(lines: List[str], index: int) -> bool:
    """Return whether ``lines[index]`` is immediately followed by a delimiter."""
    return bool(
        0 <= index < len(lines) - 1
        and markdown_table_cells(lines[index])
        and is_markdown_table_delimiter(lines[index + 1])
    )


def split_markdown_claim_units(
    text: Any,
    *,
    table_header: bool = False,
    table_delimiter: bool = False,
) -> List[str]:
    """Split prose or a table row into independently auditable claim units.

    Numeric table headers (for example ``2025 actual``) are labels and excluded,
    as are delimiter rows. Table body cells are independent; prose/list content is
    split on deterministic sentence boundaries while retaining citation markers
    with the sentence they annotate.
    """
    raw = str(text or "")
    if table_header or table_delimiter:
        return []
    cells = markdown_table_cells(raw)
    surfaces = cells if cells else [_MARKDOWN_LIST_PREFIX_RE.sub("", raw, count=1)]
    units: List[str] = []
    for surface in surfaces:
        fragments: List[str] = []
        cursor = 0
        for boundary in _QUANT_CLAIM_BOUNDARY_RE.finditer(surface):
            fragment = surface[cursor:boundary.end()].strip()
            if fragment:
                fragments.append(fragment)
            cursor = boundary.end()
        remainder = surface[cursor:].strip()
        if remainder:
            fragments.append(remainder)
        merged_fragments: List[str] = []
        for fragment in fragments:
            if (
                merged_fragments
                and _DOTTED_INITIALISM_RE.fullmatch(merged_fragments[-1])
            ):
                merged_fragments[-1] = f"{merged_fragments[-1]} {fragment}"
            else:
                merged_fragments.append(fragment)
        fragments = merged_fragments
        surface_units: List[str] = []
        for fragment in fragments:
            leading = _LEADING_CITATION_FRAGMENT_RE.match(fragment)
            if leading and surface_units:
                marker = (leading.group(1) + leading.group(2)).strip()
                surface_units[-1] = f"{surface_units[-1]} {marker}".strip()
                remainder = leading.group(3).strip()
                if remainder:
                    surface_units.append(remainder)
                continue
            surface_units.append(fragment)
        units.extend(surface_units)
    return units


def format_markdown_table_row(original: str, cells: List[str]) -> str:
    """Rebuild one table body row without changing its column count."""
    indent = original[:len(original) - len(original.lstrip())]
    stripped = original.strip()
    leading_pipe = stripped.startswith("|")
    trailing_pipe = stripped.endswith("|") and not stripped.endswith(r"\|")
    escaped = [str(cell).replace("|", r"\|").strip() for cell in cells]
    body = " | ".join(escaped)
    if leading_pipe:
        body = "| " + body
    if trailing_pipe:
        body += " |"
    return indent + body


def markdown_table_cell_index(line: Any, position: int) -> Optional[int]:
    """Map a character offset to its pipe-table cell, clamped at row edges."""
    raw = str(line or "")
    cells = markdown_table_cells(raw)
    if not cells:
        return None
    separators_before = sum(
        1 for match in re.finditer(r"(?<!\\)\|", raw)
        if match.start() < max(0, int(position))
    )
    index = separators_before - 1 if raw.lstrip().startswith("|") else separators_before
    index = max(0, index)
    return min(index, len(cells) - 1)


def markdown_table_claim_context(
    headers: List[str],
    cells: List[str],
    cell_index: int,
    claim: str,
) -> str:
    """Build the semantic label for one table claim without sharing citations.

    A numeric value cell often needs its row label and column header to mean
    anything (``Battery adoption`` + ``2025 actual`` + ``55.6%``). Those labels
    may help semantic source matching, but the citation marker must still live in
    the numeric cell itself for claim-unit coverage.
    """
    row_label = next(
        (
            cell for cell in cells
            if cell and not _NUMBER_RE.search(cell) and not _CITATION_RE.fullmatch(cell)
        ),
        "",
    )
    header = headers[cell_index] if 0 <= cell_index < len(headers) else ""
    # Header prose describes the column role but must not supply lexical anchors
    # that can override a contradictory row label (Earth evidence → Moon row).
    # Retain only numeric/time qualifiers such as the year in ``2025 actual``.
    header_numbers = " ".join(match.group(0) for match in _NUMBER_RE.finditer(header))
    parts: List[str] = []
    for part in (row_label, header_numbers, str(claim or "").strip()):
        if part and part not in parts:
            parts.append(part)
    return " ".join(parts)


def authored_forecast_markers_balanced(lines: List[str]) -> bool:
    """Return whether generated binary ownership markers are ordered and paired."""
    active = False
    fence_state: MarkdownFenceState = None
    for line in lines:
        was_in_fence = fence_state is not None
        fence_state, is_fence_line = markdown_fence_transition(line, fence_state)
        if is_fence_line or was_in_fence:
            continue
        stripped = str(line or "").strip()
        if stripped == BINARY_FORECAST_START_MARKER:
            if active:
                return False
            active = True
        elif stripped == BINARY_FORECAST_END_MARKER:
            if not active:
                return False
            active = False
    return not active


def is_authored_forecast_heading(line: Any) -> bool:
    """Return whether one H2 starts an authored forecast-contract section.

    Binary probabilities and resolution thresholds are the report's own
    predictions/definitions, not external factual claims.  Callers may exclude
    those explicitly labelled sections from *source* citation coverage while
    continuing to audit their structure through forecast.json.
    """
    return bool(_AUTHORED_FORECAST_H2_RE.fullmatch(str(line or "").strip()))


def audit_citation_grounding(
    report_markdown: str,
    index_map: Optional[Dict[str, Any]] = None,
    *,
    exclude_authored_forecasts: bool = False,
) -> Dict[str, Any]:
    """Heuristic, offline audit (I-3-1 + REPORT-6): of the prose-sentence and
    table-cell units making a quantitative claim, how many are *grounded* — i.e.
    carry a source citation ([S1]) OR a simulation/edge-grounding marker (agent
    quote, causal-edge render, sim/edge ref)?

    ``coverage`` now counts sim/edge grounding as valid; ``source_coverage`` keeps the
    strict source-only ratio as a separate metric so a regression in real-citation
    discipline is still visible. Fast guardrail, not a semantic verifier; deterministic.

    WAVE10（无缝引用）：可选 ``index_map``（记号→来源，如 {"S12": {...}}）——传入时额外
    报告 **resolved** 指标（记号必须能在注入索引里解析才算引用，悬空的 [S246] 不再充数）：
    ``resolved_cited`` / ``resolved_coverage``。最终发布门在该字段存在时优先使用它，避免
    悬空记号或内部模拟标记抬高引用覆盖；缺省 None 的遗留调用仍只输出历史 ``coverage``。
    """
    claim_units: List[str] = []
    excluded_authored = 0
    ignored_fenced = 0
    in_authored_block = False
    in_authored_section = False
    fence_state: MarkdownFenceState = None
    raw_lines = (report_markdown or "").splitlines()
    authored_markers_valid = authored_forecast_markers_balanced(raw_lines)
    for line_index, raw_line in enumerate(raw_lines):
        stripped = raw_line.strip()
        was_in_fence = fence_state is not None
        fence_state, is_fence_line = markdown_fence_transition(raw_line, fence_state)
        if is_fence_line:
            continue
        if was_in_fence:
            if _NUMBER_RE.search(stripped):
                ignored_fenced += 1
            continue
        if stripped == BINARY_FORECAST_START_MARKER:
            in_authored_block = bool(
                exclude_authored_forecasts and authored_markers_valid
            )
            in_authored_section = False
            continue
        if stripped == BINARY_FORECAST_END_MARKER:
            in_authored_block = False
            in_authored_section = False
            continue
        if stripped.startswith("## ") and not in_authored_block:
            in_authored_section = bool(
                exclude_authored_forecasts and is_authored_forecast_heading(stripped)
            )
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        units = split_markdown_claim_units(
            raw_line,
            table_header=is_markdown_table_header(raw_lines, line_index),
            table_delimiter=is_markdown_table_delimiter(raw_line),
        )
        quantitative = [unit for unit in units if _NUMBER_RE.search(unit)]
        if in_authored_block or in_authored_section:
            excluded_authored += len(quantitative)
            continue
        claim_units.extend(quantitative)
    if not claim_units:
        out = {"quantitative_claims": 0, "cited": 0, "coverage": 1.0,
               "source_cited": 0, "source_coverage": 1.0, "unsupported_samples": []}
        if index_map is not None:
            out["resolved_cited"] = 0
            out["resolved_coverage"] = 1.0
        if exclude_authored_forecasts:
            out["excluded_authored_forecast_claims"] = excluded_authored
            out["authored_forecast_markers_valid"] = authored_markers_valid
        if ignored_fenced:
            out["ignored_fenced_quantitative_lines"] = ignored_fenced
        return out

    def _grounded(unit: str) -> bool:
        return bool(_CITATION_RE.search(unit) or _SIM_GROUNDING_RE.search(unit))

    grounded = [unit for unit in claim_units if _grounded(unit)]
    source_cited = [unit for unit in claim_units if _CITATION_RE.search(unit)]
    unsupported = [unit for unit in claim_units if not _grounded(unit)]
    out = {
        "quantitative_claims": len(claim_units),
        "cited": len(grounded),                                   # grounded (source or sim/edge)
        "coverage": round(len(grounded) / len(claim_units), 3),
        "source_cited": len(source_cited),                        # source-only (separate metric)
        "source_coverage": round(len(source_cited) / len(claim_units), 3),
        "unsupported_samples": [unit[:200] for unit in unsupported[:8]],
    }
    if index_map is not None:
        resolvable = {_norm_citation_tag(k) for k in index_map}

        def _resolves(unit: str) -> bool:
            return any(_norm_citation_tag(m.group(1)) in resolvable
                       for m in _CITATION_TAG_RE.finditer(unit))

        resolved = [unit for unit in claim_units if _resolves(unit)]
        out["resolved_cited"] = len(resolved)
        out["resolved_coverage"] = round(len(resolved) / len(claim_units), 3)
    if exclude_authored_forecasts:
        out["excluded_authored_forecast_claims"] = excluded_authored
        out["authored_forecast_markers_valid"] = authored_markers_valid
    if ignored_fenced:
        out["ignored_fenced_quantitative_lines"] = ignored_fenced
    return out


# WAVE10（无缝引用）：带捕获组的引用记号（位置式 S12 与遗留分层 S1-a 均接受，方/全角括号）。
_CITATION_TAG_RE = re.compile(r"[\[【]\s*(S\d+(?:-[A-Za-z])?)\s*[\]】]", re.I)


def _norm_citation_tag(tag: str) -> str:
    """把记号归一为规范键：去括号/空白、S 大写、分层后缀小写（"[ s12 ]"→"S12"）。"""
    t = re.sub(r"[\[【\]】\s]", "", str(tag or ""))
    if not t:
        return ""
    t = "S" + t[1:].lower() if t[:1] in ("s", "S") else t
    return t


def validate_citation_markers(report_markdown: str,
                              index_map: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """WAVE10（无缝引用）：正文引用记号 vs 注入索引的确定性完整性校验。

    围栏感知（``` / ~~~ 内的记号不计——代码/mermaid 块里的 [S1] 是字面内容），按首现顺序
    采集全部 [S<n>]（含遗留 [S1-a]/【S1】变体，归一后计数）。返回：
      * ``total_markers`` / ``distinct_tags`` —— 出现总数与去重数；
      * ``order`` —— 记号首现顺序（引用最终化按此给参考来源编号）；
      * ``counts`` —— {记号: 出现次数}；
      * ``dangling`` —— 在 ``index_map`` 中无法解析的记号（[S246] 型幻觉编号）；
      * ``uncited`` —— 索引里从未被正文引用的记号（观测「索引膨胀」）。
    ``index_map`` 为 None 时 dangling/uncited 恒为空（仅做记号盘点）。纯函数、无副作用。
    """
    order: List[str] = []
    counts: Dict[str, int] = {}
    fence_state: MarkdownFenceState = None
    for ln in (report_markdown or "").split("\n"):
        was_in_fence = fence_state is not None
        fence_state, is_fence_line = markdown_fence_transition(ln, fence_state)
        if is_fence_line:
            continue
        if was_in_fence:
            continue
        for m in _CITATION_TAG_RE.finditer(ln):
            tag = _norm_citation_tag(m.group(1))
            if not tag:
                continue
            if tag not in counts:
                order.append(tag)
            counts[tag] = counts.get(tag, 0) + 1
    dangling: List[str] = []
    uncited: List[str] = []
    if index_map is not None:
        resolvable = {_norm_citation_tag(k) for k in index_map if _norm_citation_tag(k)}
        dangling = [t for t in order if t not in resolvable]
        uncited = sorted(resolvable - set(order),
                         key=lambda t: (len(t), t))  # S2 < S10 的自然序
    return {
        "total_markers": sum(counts.values()),
        "distinct_tags": len(order),
        "order": order,
        "counts": counts,
        "dangling": dangling,
        "uncited": uncited,
    }
