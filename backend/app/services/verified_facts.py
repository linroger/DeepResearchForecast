"""Labelled verified-figures block for the report prompts (REPORT-8).

The v3 research engine checks every quantitative figure against the page its
citation points to (RESEARCH-4, carried into the handoff by REPORT-7):
``verification`` is ``verified`` when every number of the value is on the
fetched page, ``unverified`` when the fetched page lacks one, ``snippet_only``
when the cited source was never fetched and ``none`` when no source resolves;
a value without a checkable number carries no label.  The report's key-metrics
table dropped the label, mixed outcomes with other parties' forecasts and gave
the writer no citable [S#].  :func:`build_verified_figures_block` renders the
labelled rows as one bounded, deterministic markdown block instead:

* the verified-on-page table: ``verified`` rows that
  :func:`app.utils.quant_typing.quant_class` reads as ``reported`` and that are
  not future-dated;
* the projections table: ``verified`` rows read as ``projected``, each labelled
  with :func:`app.utils.quant_typing.expectation_qualifier` and "not an
  outcome";
* ``excluded`` counts of every other row: ``unverified``, ``snippet_only``,
  ``none`` (no source), ``unchecked`` (no label), ``future_dated`` and
  ``unclassified`` (verified, but typing cannot tell an outcome from a
  projection, so it is in neither table).

"Verified" means only that the number was found on the cited page, never that
the page is the source of truth: the rule paragraph tells the writer to set
conflicting sources side by side and never to reconcile them into a new
number.  A source cell holds an [S#] only when ``tag_for`` finds the row's
source in the report's citation index (:func:`citation_tag_resolver`);
otherwise it holds the source's title, so the block never invents a tag.

Idea credit: the TradingAgents verified-snapshot contract (#830, Apache-2.0):
figures reach the writer together with their verification state, date and
source, and a discrepancy between sources is flagged, never reconciled.
Reimplemented from the idea; no code was copied.

Pure: no IO, no LLM.  Rows that are not mappings or name no metric are skipped.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import math
import re
from typing import Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from ..utils.quant_typing import (
    PROJECTED,
    REPORTED,
    expectation_qualifier,
    quant_class,
    reference_period,
)

VERIFIED = "verified"
# Rows left out of the block, by reason, in the order the result lists them.
EXCLUDED_BUCKETS = ("unverified", "snippet_only", "none", "unchecked", "future_dated", "unclassified")
_NOT_VERIFIED_LABELS = frozenset({"unverified", "snippet_only", "none"})
# Evidence-tier order of the key-metrics table (ReportAgent._TIER_RANK):
# S1 > S2 > S3 > untiered or unknown > S4.
_TIER_RANK = {"S1": 0, "S2": 1, "S3": 2, "": 3, "S4": 4}
_UNKNOWN_TIER_RANK = 3
_CELL_CAP = 90
# The key-metrics table's stale rule: is_stale, or staleness_days above this.
_STALE_DAYS = 180
# A citation-shaped token inside a data cell ([S12], [S1-a], 【S3】, [S?], [S#]).
# Cells drop them, so the only tags in the block are those tag_for resolved.
_CITATION_TOKEN_RE = re.compile(r"[\[【]\s*S[\d?#][^\]】]*[\]】]", re.I)
# The shape of an admissible report tag: positional S<n> or the tiered S<n>-<letter>.
_TAG_RE = re.compile(r"S\d+(?:-[A-Za-z])?")

_TEXT: Dict[str, Dict[str, Any]] = {
    "zh": {
        "header": "## 已核验指标（研究期在所引网页上核验到数字——引用时保持数值、时点与 [S#]）",
        "rule": ("核验仅表示该数字出现在所引来源页面，不代表指标口径已人工确认。若其他来源给出不同数字，"
                 "请并列呈现两者及其来源，不要自行调和出新数字；预测/目标值是具名来源的预期，不是已发生的"
                 "结果；未列出或未核验的数字不得作为确切事实陈述（本表未收录：未核验 {unverified} 条、"
                 "仅转述 {relayed} 条{other}）。"),
        "other": "、时点晚于研究时点或无法区分实际与预期 {count} 条",
        "columns": ("指标", "数值", "单位", "时点", "层级", "来源"),
        "projections": "### 预测/目标值（具名来源的预期，不是已发生的结果）",
        "projection_columns": ("指标", "数值", "单位", "目标期", "层级", "来源", "性质"),
        "not_outcome": "——不是已发生的结果",
        "stale": "⚠ = 陈旧数据（研究标记为陈旧，或距研究时点逾 180 天）",
        "empty": "（本次研究没有在所引页面核验通过的数字。）",
        "overflow": "…（另有 {count} 条已核验数字因篇幅上限未列出）",
    },
    "en": {
        "header": ("## Verified-on-page figures (numbers found on the cited page during research — "
                   "keep the value, date and [S#] when citing)"),
        "rule": ("Verified only means the number appears on the cited source page; it does not mean "
                 "anyone confirmed the metric's definition. If another source gives a different number, "
                 "present both with their sources and never reconcile them into a new number; a "
                 "projection or target is a named source's expectation, not an outcome; a number that "
                 "is not listed here or not verified must not be stated as an exact fact (left out of "
                 "this table: {unverified} unverified, {relayed} reported only{other})."),
        "other": ", {count} dated after the research or not typed as outcome or projection",
        "columns": ("metric", "value", "unit", "as of", "tier", "source"),
        "projections": "### Projections (a named source's expectation, not an outcome)",
        "projection_columns": ("metric", "value", "unit", "target", "tier", "source", "status"),
        "not_outcome": " — not an outcome",
        "stale": "⚠ = stale figure (flagged stale by the research, or dated more than 180 days before it)",
        "empty": "(No figure passed the on-page check in this research.)",
        "overflow": "…({count} more verified figures not listed: the block's size cap)",
    },
}

TagFor = Callable[[Mapping[str, Any]], Optional[str]]


def _is_zh(lang: Any) -> bool:
    """zh* / Chinese / 中文 → Chinese, anything else → English (quant_typing's rule,
    so the block and its expectation qualifiers never disagree)."""
    return str(lang or "").strip().lower().startswith(("zh", "chinese", "中"))


def _cell(value: Any, cap: int = _CELL_CAP) -> str:
    """One markdown-safe table cell: citation tokens dropped, whitespace
    collapsed, pipes escaped, capped at ``cap`` characters."""
    text = _CITATION_TOKEN_RE.sub(" ", str(value if value is not None else ""))
    text = re.sub(r"\s+", " ", text).strip().replace("|", "\\|")
    return text if len(text) <= cap else text[:cap - 1] + "…"


def _tier(row: Mapping[str, Any]) -> str:
    return str(row.get("tier") or "").strip().upper()


def _tier_rank(row: Mapping[str, Any]) -> int:
    return _TIER_RANK.get(_tier(row), _UNKNOWN_TIER_RANK)


def _is_stale(row: Mapping[str, Any]) -> bool:
    days = row.get("staleness_days")
    return bool(row.get("is_stale")) or (
        isinstance(days, (int, float)) and not isinstance(days, bool) and days > _STALE_DAYS)


def _future_dated(row: Mapping[str, Any]) -> bool:
    """REPORT-7's ``future_dated`` stamp, or RESEARCH-4's ``future_dated_reported`` flag."""
    flags = row.get("epistemic_flags")
    return bool(row.get("future_dated")) or (
        isinstance(flags, (list, tuple)) and "future_dated_reported" in flags)


def _bucket(row: Mapping[str, Any], as_of: Optional[_dt.date]) -> str:
    """REPORTED / PROJECTED for an admitted row, else its EXCLUDED_BUCKETS reason.
    An unknown non-empty label counts as unverified (never admitted)."""
    label = str(row.get("verification") or "").strip().lower()
    if not label:
        return "unchecked"
    if label != VERIFIED:
        return label if label in _NOT_VERIFIED_LABELS else "unverified"
    if _future_dated(row):
        return "future_dated"
    klass = quant_class(row, as_of)
    return klass if klass in (REPORTED, PROJECTED) else "unclassified"


def _source_url(source: Any) -> str:
    return str(source.get("url") or "").strip() if isinstance(source, Mapping) else ""


def citation_tag_resolver(tag_map: Optional[Mapping[str, Any]]) -> TagFor:
    """``tag_for`` over the report's citation index (``{tag: source row}``).

    A row resolves to its ``source_ref`` when that is a key of the index (the
    unified grammar's S<n> is the sources.json position, the numbering research
    used) and the indexed source's ``url`` does not contradict the row's
    ``source_url`` (a renumbered ledger would otherwise pin a real but wrong
    tag); else to the first tag, in index order, whose source ``url`` equals the
    row's ``source_url``; else to None.  Only index keys are ever returned."""
    index = dict(tag_map) if isinstance(tag_map, Mapping) else {}
    by_url: Dict[str, str] = {}
    for tag, source in index.items():
        url = _source_url(source)
        if url:
            by_url.setdefault(url, str(tag))

    def tag_for(row: Mapping[str, Any]) -> Optional[str]:
        ref = str(row.get("source_ref") or "").strip().strip("[]【】").strip()
        if ref[:1] in ("s", "S"):
            ref = "S" + ref[1:]
        url = str(row.get("source_url") or "").strip()
        if ref and ref in index:
            indexed_url = _source_url(index[ref])
            if not (url and indexed_url and url != indexed_url):
                return ref
        return by_url.get(url) if url else None

    return tag_for


def _admissible_tag(tag: Any) -> Optional[str]:
    text = tag.strip() if isinstance(tag, str) else ""
    return text if _TAG_RE.fullmatch(text) else None


def _text_or_none(value: Any) -> Optional[str]:
    """A string field with its whitespace collapsed, or None (blank, or not a string)."""
    text = re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else ""
    return text or None


def _display(row: Mapping[str, Any], group: str, tag_for: TagFor, zh: bool,
             texts: Mapping[str, Any]) -> Dict[str, Any]:
    """The rendered cells of an admitted row (plus its sort keys)."""
    tag = _admissible_tag(tag_for(row))
    projected = group == PROJECTED
    if projected:
        when = reference_period({key: row.get(key) for key in ("target_date", "period_end")})
        # A projection's as_of_date is when its source published it, never its target.
        period = when
    else:
        when = str(row.get("as_of_date") or "").strip() or reference_period(row)
        period = reference_period(row)
    metric = _cell(row.get("metric") or row.get("definition"))
    stale = not projected and _is_stale(row)
    shown = {
        "metric": f"⚠ {metric}" if stale else metric,
        "value": _cell(row.get("value")),
        "unit": _cell(row.get("unit")),
        "when": _cell(when),
        "tier": _cell(_tier(row)),
        "source": f"[{tag}]" if tag else _cell(row.get("source")),
        "tag": tag,
        # Not rendered: the provenance REPORT-9's figure_provenance.json records, and what
        # its check reads (the period the value is about, which ``when`` is not for a
        # reported row dated by publication; the metric's definition and series).
        "source_title": _text_or_none(row.get("source")),
        "source_url": _text_or_none(row.get("source_url")),
        "period": _text_or_none(period),
        "definition": _text_or_none(row.get("definition")),
        "series": _text_or_none(row.get("series")),
        "stale": stale,
        "group": group,
        "tier_rank": _tier_rank(row),
        "as_of_key": str(row.get("as_of_date") or "").strip(),
    }
    if projected:
        suffix = texts["not_outcome"]
        qualifier = _cell(expectation_qualifier(row, "zh" if zh else "en"), _CELL_CAP - len(suffix))
        shown["label"] = qualifier + suffix
    return shown


def _cells(shown: Mapping[str, Any]) -> Tuple[str, ...]:
    cells = (shown["metric"], shown["value"], shown["unit"], shown["when"], shown["tier"], shown["source"])
    return cells + (shown["label"],) if "label" in shown else cells


def _preference(shown: Mapping[str, Any]) -> Tuple[Any, ...]:
    """Which of two admitted rows with the same cells the block keeps (the
    larger): the newest as-of date (a projection quoted on two pages, or a
    reported row whose date is only in period_end), then the better tier, then
    the current one, then the unrendered fields only the public rows carry
    (source title and URL, period, definition, series).  With the cells, this
    covers every field a kept row carries, so the choice never depends on input
    order."""
    return (shown["as_of_key"], -shown["tier_rank"], not shown["stale"],
            *(shown[key] or "" for key in ("source_title", "source_url", "period", "definition", "series")))


def _render_order(rows: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    """Tier (S1 first), then as-of date (newest first), then the cells."""
    ordered = sorted(rows, key=_cells)
    ordered.sort(key=lambda shown: shown["as_of_key"], reverse=True)
    ordered.sort(key=lambda shown: shown["tier_rank"])
    return ordered


def _keep_order(rows: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    """Rows in the order the caps keep them: current verified figures, then
    stale ones, then projections; newest first within each, then tier, then
    cells.  The caps drop from the end: projections first, then stale rows,
    then the oldest."""
    def group_rank(shown: Mapping[str, Any]) -> int:
        if shown["group"] == PROJECTED:
            return 2
        return 1 if shown["stale"] else 0

    ordered = sorted(rows, key=_cells)
    ordered.sort(key=lambda shown: shown["tier_rank"])
    ordered.sort(key=lambda shown: shown["as_of_key"], reverse=True)
    ordered.sort(key=group_rank)
    return ordered


def _table(columns: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> List[str]:
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines.extend("| " + " | ".join(_cells(shown)) + " |" for shown in rows)
    return lines


def _render(texts: Mapping[str, Any], kept: Sequence[Mapping[str, Any]], omitted: int,
            unverified: int, relayed: int, other: int) -> str:
    verified = _render_order([shown for shown in kept if shown["group"] == REPORTED])
    projections = _render_order([shown for shown in kept if shown["group"] == PROJECTED])
    rule = texts["rule"].format(unverified=unverified, relayed=relayed,
                                other=texts["other"].format(count=other) if other else "")
    lines = [texts["header"], rule]
    if verified:
        lines += [""] + _table(texts["columns"], verified)
        if any(shown["stale"] for shown in verified):
            lines.append(texts["stale"])
    if projections:
        lines += ["", texts["projections"]] + _table(texts["projection_columns"], projections)
    if omitted:
        lines += ["", texts["overflow"].format(count=omitted)]
    elif not verified and not projections:
        lines += ["", texts["empty"]]
    return "\n".join(lines)


def _public(shown: Mapping[str, Any]) -> Dict[str, Any]:
    keys = ("metric", "value", "unit", "when", "tier", "source", "tag", "source_title", "source_url", "period",
            "definition", "series", "stale", "label")
    return {key: shown[key] for key in keys if key in shown}


def build_verified_figures_block(quantitative: Any, *, tag_for: TagFor, lang: Any = "zh",
                                 max_rows: int = 40, max_chars: int = 6000,
                                 as_of: Optional[_dt.date] = None) -> Dict[str, Any]:
    """The verified-figures block over research quantitative rows.

    Only rows carrying a ``verification`` key count as labelled; when no row
    does (legacy engine, reused research, verification off) ``rendered`` is ""
    and the caller keeps its legacy table.  ``as_of`` (the research as-of
    date) is what :func:`quant_class` types the rows against.  ``tag_for(row)``
    returns the row's report tag or None (see :func:`citation_tag_resolver`);
    anything not shaped like a tag is treated as None.

    Deterministic: the same rows in any order render the same text; admitted
    rows whose cells coincide render once (:func:`_preference` picks which).
    The block keeps at most ``max_rows`` rows and ``max_chars`` characters (the
    header and rule are never cut), dropping projections first, then stale
    rows, then the oldest, and says how many it left out.  The rule paragraph
    counts as "unverified" the unverified, none and unchecked rows, as
    "reported only" the snippet_only rows and, when there are any, the
    future_dated and unclassified rows as a third count.

    Returns ``{"rendered", "sha256", "rows", "projections", "excluded",
    "omitted"}``: ``rows`` / ``projections`` are the rendered rows' cells (plus
    each row's unrendered ``source_title``, ``source_url``, ``period`` — the
    date or period the value is about, :func:`reference_period`; a projection's
    target only — ``definition`` and ``series``), ``excluded``
    counts every EXCLUDED_BUCKETS reason and ``omitted`` the admitted rows the
    caps left out.  ``sha256`` is the digest of ``rendered`` ("" when nothing
    is rendered)."""
    rows = [row for row in (quantitative if isinstance(quantitative, list) else [])
            if isinstance(row, Mapping) and (row.get("metric") or row.get("definition"))]
    result: Dict[str, Any] = {"rendered": "", "sha256": "", "rows": [], "projections": [],
                              "excluded": dict.fromkeys(EXCLUDED_BUCKETS, 0), "omitted": 0}
    if not any("verification" in row for row in rows):
        return result
    zh = _is_zh(lang)
    texts = _TEXT["zh" if zh else "en"]
    admitted: Dict[Tuple[str, ...], Dict[str, Any]] = {}
    for row in rows:
        bucket = _bucket(row, as_of)
        if bucket in (REPORTED, PROJECTED):
            shown = _display(row, bucket, tag_for, zh, texts)
            key = (bucket,) + _cells(shown)
            previous = admitted.get(key)
            if previous is None or _preference(shown) > _preference(previous):
                admitted[key] = shown
        else:
            result["excluded"][bucket] += 1
    excluded = result["excluded"]
    counts = (excluded["unverified"] + excluded["none"] + excluded["unchecked"],
              excluded["snippet_only"], excluded["future_dated"] + excluded["unclassified"])
    candidates = _keep_order(list(admitted.values()))
    kept = candidates[:max(0, int(max_rows))]
    rendered = _render(texts, kept, len(candidates) - len(kept), *counts)
    while kept and len(rendered) > max_chars:
        kept = kept[:-1]
        rendered = _render(texts, kept, len(candidates) - len(kept), *counts)
    result.update(
        rendered=rendered,
        sha256=hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        rows=[_public(shown) for shown in _render_order([s for s in kept if s["group"] == REPORTED])],
        projections=[_public(shown) for shown in _render_order([s for s in kept if s["group"] == PROJECTED])],
        omitted=len(candidates) - len(kept),
    )
    return result


# ---------------------------------------------------------------------------
# REPORT-9: shadow check of the report's figures against the block (detection only)
# ---------------------------------------------------------------------------

CHECK_KINDS = ("matched", "conflict", "ambiguous", "states_unverified", "market_conflict",
               "threshold_or_probability", "unmatched")
DEFAULT_REL_TOL = 0.02
CHECK_EXAMPLES_MAX = 24
EXCERPT_CHARS = 180
MATCHED_LINES_PER_ROW = 10
CONFLICT_RATIO = (0.1, 10.0)
# numeric_guards unit classes -> the check's classes.  pp and bp are changes, never
# compared with a level, so each is its own class.
_CHECK_CLASS = {"percent": "percent", "currency": "currency", "count": "plain", "unknown": "plain",
                "pp": "pp", "bp": "bp"}
_REFERENCES_HEADINGS = ("## references", "## 参考来源", "## 参考文献")
# The spec's market words.  A bare "implied" ("the implied growth rate") is no market, so
# it counts only before a probability, odds, chance or price.
_MARKET_CONTEXT_RE = re.compile(
    r"polymarket|prediction[ -]?markets?|预测市场|隐含概率"
    r"|implied[ -](?:yes[ -])?(?:probabilit(?:y|ies)|odds|chances?|prices?)", re.I)
# A figure stated as a probability ("a 40% chance", "40% implied probability", "70% likely",
# "with 70% confidence", "a 55% weight", "odds of 45%", "40%的概率", "概率为40%", "置信度70%"):
# like a threshold, it states no level of a metric.
_PROBABILITY_WORDS = r"(?:chances?|probabilit(?:y|ies)|likelihood|odds|confidence|weight(?:ing)?)"
_CJK_PROBABILITY_WORDS = r"(?:概率|可能性|几率|机率|置信度|置信水平|权重)"
_PROBABILITY_AFTER_RE = re.compile(
    r"^[\s-]*(?:(?:implied|estimated|subjective|assessed|market|model|forecast|yes)[- ]+)?"
    r"(?:" + _PROBABILITY_WORDS + r"|confident)(?![A-Za-z])"
    # "70% likely that / to", "is 70% likely.", never "31% likely because".
    r"|^[\s-]*(?:un)?likely(?=\s+(?:that|to)\b|\s*[,.;:)]|\s*$)"
    r"|^\s*的?" + _CJK_PROBABILITY_WORDS, re.I)
_PROBABILITY_BEFORE_RE = re.compile(
    r"(?<![A-Za-z])(?:" + _PROBABILITY_WORDS + r"(?:\s+level)?\s*(?:(?:of|at|is|are|was|were|stands\s+at|=|:)\s*)?"
    # "we put the surge scenario at 40%", "the base case at about 55%".
    r"|(?:scenario|case)\s+at\s+)(?:(?:about|around|roughly|approximately|~|≈)\s*)?$"
    r"|" + _CJK_PROBABILITY_WORDS + r"(?:为|是|约为|约|达|在|仅|高达)?\s*[:：]?\s*$", re.I)
_PROBABILITY_WINDOW = 40
# A figure in a scenario's label slot, the text before it in its unit ("Scenario A (surge):
# 55%", "**Scenario B** (25%", "1. 情景A（上升）：55%"): the scenario's probability, never
# a level ("Scenario A: the share reaches 31%" has words between the label and the figure).
# The leading run is possessive: it overlaps the emphasis class on "*" and "_", and a
# backtracking run would make a long run of either quadratic.
_SCENARIO_SLOT_RE = re.compile(
    r"^[\s>*_•·-]*+(?:\d+[.)]\s*)?[*_]*(?:scenarios?(?![A-Za-z])|情景|场景)[^:：\n]{0,80}?(?:[:：]|[(（])[\s*_]*$",
    re.I)
# A table column header or row label that makes every figure under it a probability
# ("| Scenario | Probability |", "| Market P(yes) |", "| 情景 | 概率 |"), and a column
# headed by a bare "P" alone (_BARE_P_HEADER_RE: "S&P" or "p.a." in a label is none).  A
# bare "price" or "implied" is no probability ("Electricity price growth", "Implied CAGR"):
# a market price column is read through the market words instead.
_PROBABILITY_LABEL_RE = re.compile(
    r"(?<![A-Za-z])(?:" + _PROBABILITY_WORDS + r"|yes[- ]price)(?![A-Za-z])"
    r"|(?<![A-Za-z])P\s*\(\s*yes\s*\)|" + _CJK_PROBABILITY_WORDS, re.I)
_BARE_P_HEADER_RE = re.compile(r"[\s*_]*P[\s*_]*")
# Probability words that also name metrics ("Technology sector index weight", "Consumer
# confidence", "行业权重"): when an anchored candidate row's own metric names every such
# word that made a figure a probability, the figure is that metric's level.
_METRIC_PROBABILITY_WORDS = frozenset({"weight", "weighting", "confidence", "权重", "置信度", "置信水平"})
_PROBABILITY_WORD_RE = re.compile(_PROBABILITY_WORDS + "|" + _CJK_PROBABILITY_WORDS, re.I)
# A qualitative confidence grade in a table label ("Data-centre share (high confidence)",
# "高置信度") grades the row's figures: it states no probability.
_CONFIDENCE_GRADE_RE = re.compile(
    r"(?<![A-Za-z])(?:(?:very|fairly)\s+)?(?:high|medium|moderate|low|limited)[- ]confidence(?![A-Za-z])"
    r"|(?:高|中等?|低)置信度?|置信度(?:高|中等?|低)", re.I)
# A threshold named by a noun rather than a comparator: right before the figure ("the key
# threshold for the share is 30%", "trigger level of 30%", "阈值为30%"), right after it
# ("the 30% threshold", "30%的阈值"), as the label that
# leads its unit ("Trigger: … at 30%", "**Signpost**: …", "阈值：…") or as a table column
# header or row label ("| Threshold |", "| Trigger level |", "| 阈值 |").  Like a
# comparator's, such a figure states no level.
_THRESHOLD_NOUNS = r"(?:thresholds?|trigger(?:s|\s+(?:levels?|points?))?|tripwires?|signposts?|cut-?offs?)"
_THRESHOLD_NOUN_BEFORE_RE = re.compile(
    r"(?<![A-Za-z])" + _THRESHOLD_NOUNS + r"(?:\s+(?:for|of|on)\s[^.;:,!?\n]{0,60}?)?\s*"
    r"(?:(?<![A-Za-z])(?:is|are|was|were|of|at|sits\s+at|stands\s+at|set\s+at)|[:=：])\s*"
    r"(?:(?:about|around|roughly|approximately|~|≈)\s*)?$"
    r"|(?:阈值|触发值|触发点|触发水平|临界值|临界点)(?:为|是|设为|设在|在|约为|约)?\s*[:：]?\s*$", re.I)
_THRESHOLD_NOUN_AFTER_RE = re.compile(
    r"^\s*" + _THRESHOLD_NOUNS + r"(?![A-Za-z])|^\s*的?(?:阈值|触发值|触发点|临界值|临界点)", re.I)
_THRESHOLD_WINDOW = 100
_THRESHOLD_LEAD_RE = re.compile(
    r"[\s>*_•·-]*+(?:\d+[.)]\s*)?[*_]*(?:(?:[A-Za-z][A-Za-z-]*\s+){0,2}" + _THRESHOLD_NOUNS
    + r"|阈值|触发条件|触发值|触发点|临界值|临界点)[*_]*\s*[:：]", re.I)
_THRESHOLD_LABEL_RE = re.compile(r"(?<![A-Za-z])" + _THRESHOLD_NOUNS + r"(?![A-Za-z])|阈值|触发|临界", re.I)
# Scientific notation ("10⁻⁶", "10^-6", "10<sup>-6</sup>", "3.5×10⁸"): its base, its
# mantissa and its exponent are no figures (the scanner reads e-notation, "1e-6", whole).
_EXPONENT = r"(?:\^|<sup>|[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺])"
_SCIENTIFIC_AFTER_RE = re.compile(r"\s*(?:" + _EXPONENT + r"|[×xX*·]\s*10\s*" + _EXPONENT + r")", re.I)
_EXPONENT_BEFORE_RE = re.compile(r"(?:\^|<sup>)\s*$", re.I)
# A block row whose value is "up to" a figure bounds it from above (numeric_guards reads the
# other comparators; a trailing "+" bounds it from below: "20+", "$153M+").
_UP_TO_BEFORE_RE = re.compile(r"(?<![A-Za-z])up\s+to\s*$", re.I)
# No figures: a year span ("2025—26", "2025~26"), and a bare number (no unit mark) that is a
# fiscal-year suffix ("in 2025/26," leaves "26"; "2025 – 26% of" is a figure) or a label
# number ("Figure 12", "Section 301", "图12", "第12"; "代表30%" is a figure).
_YEAR_SPAN_RE = re.compile(r"(?:19|20)\d{2}\s*[/\-–—~]\s*\d{2}(?!\d)")
_YEAR_SUFFIX_BEFORE_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}[/\-–—~]$")
_LABEL_BEFORE_RE = re.compile(
    r"(?<![A-Za-z])(?:figure|fig\.|table|chart|exhibit|appendix|section|part)\s*$|(?:图|表|附录|第)\s*$", re.I)
_LABEL_WINDOW = 12
_ANCHOR_LATIN_RE = re.compile(r"[a-z]{4,}")
_ANCHOR_CJK_RE = re.compile(r"[㐀-䶿一-鿿]+")
_ANCHOR_STOPWORDS = frozenset({
    "about", "above", "after", "also", "around", "below", "been", "being", "from", "have", "into",
    "more", "most", "over", "percent", "than", "that", "their", "there", "these", "this",
    "those", "under", "were", "what", "when", "which", "while", "will", "with", "within", "would",
    "year", "years", "total", "level", "levels", "value", "values", "figure", "figures"})
_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2}|2100)(?!\d)")
_FIRST_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.(\d+))?")
# The report's citation grammar (forecast_extractor._CITATION_TAG_RE): positional S<n> and
# the legacy tiered S<n>-a, in square or CJK brackets.
_UNIT_TAG_RE = re.compile(r"[\[【]\s*(S\d+(?:-[A-Za-z])?)\s*[\]】]", re.I)


def _anchor_tokens(text: Any) -> Tuple[frozenset, frozenset]:
    """(casefolded Latin words of four or more letters, CJK character bigrams)."""
    folded = str(text or "").casefold()
    latin = frozenset(w for w in _ANCHOR_LATIN_RE.findall(folded) if w not in _ANCHOR_STOPWORDS)
    cjk = frozenset(run[i:i + 2] for run in _ANCHOR_CJK_RE.findall(folded) for i in range(len(run) - 1))
    return latin, cjk


def _anchored(a: Tuple[frozenset, frozenset], b: Tuple[frozenset, frozenset]) -> bool:
    """At least two shared Latin words or four shared CJK bigrams."""
    return len(a[0] & b[0]) >= 2 or len(a[1] & b[1]) >= 4


def _years(*texts: Any) -> frozenset:
    return frozenset(int(y) for text in texts for y in _YEAR_RE.findall(str(text or "")))


def _parsed_value(value: Any, unit: Any) -> Optional[Dict[str, Any]]:
    from ..utils.numeric_guards import parse_quantity
    quantity = parse_quantity(value, unit or "")
    if quantity is None:
        return None
    return {"lo": quantity["lo"], "hi": quantity["hi"],
            "cls": _CHECK_CLASS.get(quantity["unit_class"], "plain"), "currency": quantity.get("currency")}


def _value_bound(value: Any) -> Optional[str]:
    """How a row's value text bounds the figure :func:`_parsed_value` reads (its first
    non-date figure): ``"lower"`` (">3", "≥25", "at least 5", "超过30", "5 or more",
    "20+", "$153M+"), ``"upper"`` ("<12", "≤4", "up to 40", "至多5"), ``"between"``
    ("between 28% and 38%") or None for a stated value."""
    from ..utils.numeric_guards import scan_quantities, threshold_comparators
    text = value if isinstance(value, str) else ""
    first = next((hit for hit in scan_quantities(text) if not hit.get("date")), None)
    if first is None:
        return None
    start, end = int(first["start"]), int(first["end"])
    for lo, hi, comparator in threshold_comparators(text):
        if lo <= start < hi:
            return {">": "lower", ">=": "lower", "<": "upper", "<=": "upper"}.get(comparator, "between")
    if text[end:].lstrip().startswith("+"):
        return "lower"
    return "upper" if _UP_TO_BEFORE_RE.search(text[:start]) else None


def _figure_row(index: int, row: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """A block row (or an excluded research row) as the check reads it, or None when its
    value states no figure.  Its years are the metric's plus the period the value is about:
    a block row's unrendered ``period`` (its ``when`` is a reported row's publication
    date), a research row's :func:`reference_period`, else ``when``.

    A bounded value (:func:`_value_bound`) is a one-sided interval whose open end is
    infinite (``bound`` True): ">3" trillion is [3e12, inf], so "$3.5 trillion" states it
    and "$1.2 trillion" is no conflict with it.  A "between" value the reader kept one end
    of (no range) states no figure."""
    metric = str(row.get("metric") or row.get("definition") or "").strip()
    if metric.startswith("⚠"):
        metric = metric[1:].strip()
    value = _parsed_value(row.get("value"), row.get("unit"))
    if not metric or value is None:
        return None
    bound = _value_bound(row.get("value"))
    if bound == "between" and value["lo"] == value["hi"]:
        return None
    if bound == "lower":
        value["hi"] = math.inf
    elif bound == "upper":
        value["lo"] = -math.inf
    anchor_text = " ".join(str(row.get(key) or "") for key in ("series", "definition")) + " " + metric
    period = row.get("period") if "period" in row else reference_period(row)
    return dict(value, index=index, metric=metric, anchor=_anchor_tokens(anchor_text),
                years=_years(metric, period or row.get("when")),
                value_text=str(row.get("value") or ""), bound=bound in ("lower", "upper"))


def _unit_columns(cells: Sequence[str], units: Sequence[str]) -> List[Optional[int]]:
    """The column of each claim unit of a table body row.  split_markdown_claim_units
    splits a row cell by cell, in order, so splitting each cell alone gives the same units
    column by column; when the counts disagree (a cell with an escaped pipe or a leading
    list marker) no unit gets a column."""
    from .forecast_extractor import split_markdown_claim_units
    columns: List[Optional[int]] = [column for column, cell in enumerate(cells)
                                    for _unit in split_markdown_claim_units(cell)]
    return columns if len(columns) == len(units) else [None] * len(units)


class _Unit(NamedTuple):
    """One claim unit as the check reads it (:func:`_claim_units`)."""
    line: int
    text: str
    # The whole table row for a table cell (the metric of a figure in a table, its
    # citation and anything a reviewer needs to judge it are in other cells), else the
    # unit: the anchor, the excerpt and the citation fallback.
    context: str
    years: frozenset
    # Where market words count: the context plus, for a table cell, its column header and
    # the header of the row-label column ("| Polymarket market | … |" makes every row a market).
    market_text: str
    # A table cell's column header and row label, where probability words count ("" outside
    # a table: prose is read around the figure instead).
    label_text: str
    column: Optional[str]


def _claim_units(md: str) -> Iterable[_Unit]:
    """Every claim unit of ``md`` with the scan discipline of
    forecast_extractor.audit_citation_grounding (fences, headings, the Part-1 marker block
    and authored forecast sections skipped) plus the References section.  ``years`` are
    the unit's own; a table cell without one takes its column header's ("| Metric | 2025 |
    2030E |"), else its row's ("| Metric | Year | Value |")."""
    from .forecast_extractor import (
        BINARY_FORECAST_END_MARKER, BINARY_FORECAST_START_MARKER, authored_forecast_markers_balanced,
        is_authored_forecast_heading, is_markdown_table_delimiter, is_markdown_table_header,
        markdown_fence_transition, markdown_table_cells, split_markdown_claim_units,
    )
    lines = str(md or "").splitlines()
    markers_valid = authored_forecast_markers_balanced(lines)
    fence = None
    header: Optional[List[str]] = None
    in_block = in_authored = in_references = False
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        was_in_fence = fence is not None
        fence, is_fence_line = markdown_fence_transition(raw, fence)
        if is_fence_line or was_in_fence:
            header = None
            continue
        cells = markdown_table_cells(raw)
        is_header = is_markdown_table_header(lines, index)
        if not cells:
            header = None
        elif is_header:
            header = cells
        if stripped == BINARY_FORECAST_START_MARKER:
            in_block, in_authored = markers_valid, False
            continue
        if stripped == BINARY_FORECAST_END_MARKER:
            in_block = in_authored = False
            continue
        if stripped.startswith("## ") and not in_block:
            in_authored = is_authored_forecast_heading(stripped)
            in_references = stripped.casefold().rstrip("：: ") in _REFERENCES_HEADINGS
        if not stripped or stripped.startswith("#") or in_block or in_authored or in_references:
            continue
        units = split_markdown_claim_units(raw, table_header=is_header,
                                           table_delimiter=is_markdown_table_delimiter(raw))
        if not cells:
            for unit in units:
                yield _Unit(index + 1, unit, unit, _years(unit), unit, "", None)
            continue
        row_years = _years(raw)
        label_header = header[0] if header else ""
        for unit, column in zip(units, _unit_columns(cells, units), strict=True):
            column_header = header[column] if header and column is not None and column < len(header) else ""
            yield _Unit(index + 1, unit, raw, _years(unit) or _years(column_header) or row_years,
                        " ".join((raw, column_header, label_header)), f"{column_header} {cells[0]}",
                        column_header or None)


def _metric_words(readings: Sequence[str]) -> Optional[frozenset]:
    """The probability words of ``readings`` (the texts that made a figure a probability)
    when every reading has one and each can name a metric (_METRIC_PROBABILITY_WORDS),
    else None: such a figure is a probability whatever the rows name."""
    words: set = set()
    for reading in readings:
        found = {word.casefold() for word in _PROBABILITY_WORD_RE.findall(reading)}
        if not found or not found <= _METRIC_PROBABILITY_WORDS:
            return None
        words |= found
    return frozenset(words) or None


def _claim_figures(unit: str) -> List[Dict[str, Any]]:
    """The figures of a unit worth checking: no dates, bare years, year spans, fiscal-year
    suffixes, label numbers ("Figure 12") or parts of scientific notation ("10⁻⁶",
    "3.5×10⁸"), and a unit mark or at least two digits (a bare "3 scenarios" is no
    figure).  ``threshold`` marks a figure a comparator governs ("exceeds 30%") or a
    threshold noun names ("the threshold is 30%", "the 30% threshold", "Trigger: … 30%"),
    ``probability`` one
    the unit states as a probability ("a 40% chance", "概率为40%", "Scenario A: 55%"), and
    ``metric_words`` the words that alone made it one when each can also name a metric
    ("index weight was 31%": {"weight"}; else None)."""
    from ..utils.numeric_guards import scan_quantities, threshold_spans
    thresholds = threshold_spans(unit)
    lead = _THRESHOLD_LEAD_RE.match(unit)
    out = []
    for hit in scan_quantities(unit):
        if hit.get("date") or hit.get("year_like"):
            continue
        raw = str(hit.get("raw") or "")
        token = _FIRST_NUMBER_RE.search(raw)
        if token is None or _YEAR_SPAN_RE.match(raw.strip()):
            continue
        start, end = int(hit["start"]), int(hit["end"])
        if _SCIENTIFIC_AFTER_RE.match(unit, start + token.end()) \
                or _EXPONENT_BEFORE_RE.search(unit[max(0, start - _LABEL_WINDOW):start]):
            continue
        digits = token.group(0).replace(",", "")
        if not hit.get("has_marks") and len(digits.replace(".", "")) < 2:
            continue
        before = unit[max(0, start - _LABEL_WINDOW):start]
        if not hit.get("has_marks") and (_LABEL_BEFORE_RE.search(before) or (
                len(digits) == 2 and _YEAR_SUFFIX_BEFORE_RE.search(before))):
            continue
        try:
            stated = float(digits)
        except ValueError:
            continue
        lo = float(hit["lo"])
        scale = abs(lo / stated) if stated else 1.0
        decimals = len(token.group(1) or "")
        readings = [match.group(0) for match in (
            _PROBABILITY_AFTER_RE.search(unit[end:end + _PROBABILITY_WINDOW]),
            _PROBABILITY_BEFORE_RE.search(unit[max(0, start - _PROBABILITY_WINDOW):start])) if match]
        slot = _SCENARIO_SLOT_RE.search(unit[:start])
        threshold = (any(lo_span <= start < hi_span for lo_span, hi_span in thresholds)
                     or (lead is not None and start >= lead.end())
                     or bool(_THRESHOLD_NOUN_BEFORE_RE.search(unit[max(0, start - _THRESHOLD_WINDOW):start]))
                     or bool(_THRESHOLD_NOUN_AFTER_RE.search(unit[end:end + _THRESHOLD_WINDOW])))
        out.append({"lo": lo, "hi": float(hit["hi"]), "raw": raw,
                    "cls": _CHECK_CLASS.get(hit.get("unit_class"), "plain"),
                    "currency": hit.get("currency"),
                    "tol": 0.5 * (10 ** -decimals) * (scale or 1.0),
                    "threshold": threshold,
                    "probability": bool(readings or slot),
                    "metric_words": None if slot else _metric_words(readings)})
    return out


def _agrees(figure: Mapping[str, Any], lo: float, hi: float) -> bool:
    """The figure states the value [lo, hi] at its own precision (a range on either side
    agrees when the intervals meet; a bound's infinite end meets anything on its side)."""
    tol = figure["tol"] + 1e-9 * max([abs(end) for end in (lo, hi) if math.isfinite(end)] + [1.0])
    return figure["lo"] - tol <= hi and lo <= figure["hi"] + tol


def _states(figure: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    """The figure states the row's value (:func:`_agrees`); a bound only when the figure is
    also :func:`_comparable` with it (ten times past ">3" is more likely another measure)."""
    return _agrees(figure, row["lo"], row["hi"]) and (not row["bound"] or _comparable(figure, row))


def _names_words(words: Optional[frozenset], rows: Sequence[Mapping[str, Any]]) -> bool:
    """One of ``rows`` names every one of ``words`` in its metric, definition or series
    (its anchor tokens): "Technology sector index weight" names "weight"."""
    if not words:
        return False
    tokens = [_anchor_tokens(word) for word in words]
    return any(all((latin or cjk) and latin <= row["anchor"][0] and cjk <= row["anchor"][1]
                   for latin, cjk in tokens) for row in rows)


def _candidates(figure: Mapping[str, Any], anchor: Tuple[frozenset, frozenset], years: frozenset,
                rows: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    out = []
    for row in rows:
        if row["cls"] != figure["cls"] or not _anchored(anchor, row["anchor"]):
            continue
        if figure["cls"] == "currency" and figure["currency"] and row["currency"] \
                and figure["currency"] != row["currency"]:
            continue
        if years and row["years"] and not (years & row["years"]):
            continue
        out.append(row)
    return out


def _comparable(figure: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    """The figure and the row (midpoints of a range, a bound's finite end) share a sign and
    their ratio is within CONFLICT_RATIO: beyond it the two are more likely different
    measures than a disagreement, so such a row neither conflicts nor makes the figure
    ambiguous."""
    finite = [end for end in (row["lo"], row["hi"]) if math.isfinite(end)]
    claim, value = (figure["lo"] + figure["hi"]) / 2, sum(finite) / len(finite) if finite else 0.0
    return bool(claim and value) and CONFLICT_RATIO[0] <= claim / value <= CONFLICT_RATIO[1]


def _conflicts(figure: Mapping[str, Any], row: Mapping[str, Any], rel_tol: float) -> bool:
    """A point figure against a comparable point row more than ``rel_tol`` apart."""
    if figure["lo"] != figure["hi"] or row["lo"] != row["hi"] or not _comparable(figure, row):
        return False
    return abs(figure["lo"] - row["lo"]) / abs(row["lo"]) > rel_tol


def _market_row(row: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    prices = []
    for key in ("implied_yes_prob", "price_at_research"):
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1:
            prices.append(float(value) * 100)
    if not prices:
        return None
    return {"anchor": _anchor_tokens(row.get("question")), "prices": prices}


def _cited_tags(unit: str) -> List[str]:
    """The unit's [S#] tags in reading order, normalised as
    forecast_extractor._norm_citation_tag does ("[s12]" -> "S12", "[S1-A]" -> "S1-a")."""
    tags: List[str] = []
    for match in _UNIT_TAG_RE.finditer(unit):
        tag = "S" + match.group(1)[1:].lower()
        if tag not in tags:
            tags.append(tag)
    return tags


def _supporting_tag(unit: str, tags: Sequence[str],
                    support_fn: Callable[[str, str], Optional[bool]]) -> Optional[str]:
    """The first of ``tags`` whose source supports the unit; an undecidable check (None,
    an exception) supports nothing."""
    for tag in tags:
        try:
            if support_fn(unit, tag) is True:
                return tag
        except Exception:  # noqa: BLE001 — undecidable is not a discrepancy
            continue
    return None


def check_verified_figures(md: Any, block_rows: Any, *, excluded_rows: Any = (), market_rows: Any = (),
                           rel_tol: float = DEFAULT_REL_TOL,
                           support_fn: Optional[Callable[[str, str], Optional[bool]]] = None) -> Dict[str, Any]:
    """Shadow check of the report's figures against the verified-figures block (REPORT-9).

    Every figure of every claim unit (:func:`_claim_units`) is classified once, in this
    order:

    * ``threshold_or_probability``: a figure a comparator governs ("exceeds 30%", "below
      $100", numeric_guards.threshold_spans) or a threshold noun names ("the threshold is
      30%", "Trigger: …", any figure of a table column or row labelled Threshold / Trigger /
      阈值) or, outside a market reading, one stated as a probability ("a 40% chance", "70%
      likely", "Scenario A: 55%", "the base case at 55%", "概率为40%", or any figure of a
      table column or row labelled Probability / Weight / P(yes) / 概率 — a confidence
      grade such as "(high confidence)" is no such label —, or of a column headed "P"):
      neither states a level of the metric.  A weight or confidence word that an anchored
      candidate row's own metric names ("the index weight was 31%" against "Technology
      sector index weight"), in the unit or a table row's label, makes no probability (a
      column headed by such a word always does);
    * a percentage in a market context (Polymarket, prediction market, 预测市场, 隐含概率,
      implied probability / odds / chance / price, in the unit or, for a table cell, its
      row, column header or row-label column header) is read against the markets, never
      against the block's conflict branches: ``unmatched`` when it agrees with the current
      or the research-time price of an anchored market, else ``matched`` when it is no
      probability and states a candidate block row's value (a level quoted beside the
      market), else ``market_conflict`` when a market is anchored, else
      ``threshold_or_probability`` (a probability) or ``unmatched``;
    * ``matched``: a candidate block row states the same value (across scales, or the
      row's value rounded to the claim's precision);
    * ``ambiguous``: comparable candidates (:func:`_comparable`) with different values
      (never a conflict);
    * ``conflict``: exactly one comparable candidate value, a point on both sides, more
      than ``rel_tol`` apart (a bounded row, ">3" trillion, is matched by a figure on its
      side within 10x and conflicts with none);
    * ``states_unverified``: an uncited figure with no comparable candidate that equals an
      anchored ``excluded_rows`` row (research rows whose verification is unverified /
      snippet_only / none);
    * ``unmatched``: anything else (no candidate, a point within ``rel_tol`` of its one
      comparable row that its own precision does not state — neither matched nor a
      conflict, and never in the row's used_in —, a range outside a row, a ratio beyond
      10x).

    A candidate row shares the figure's class (percent, currency, plain; pp and bp only
    with themselves), its anchor (two Latin words of four or more letters or four CJK
    bigrams from the row's metric, definition and series with the unit, or the whole table
    row for a cell) and at least one year when both name years (the row's: its metric's
    and the period its value is about, :func:`_figure_row`; a table cell's: its own, its
    column's or its row's, :func:`_claim_units`).  A table cell is cited by its own [S#],
    else by its row's.  Read-only and deterministic.

    Returns ``{'counts' (every CHECK_KINDS key), 'examples' (<= 24: conflict, ambiguous,
    states_unverified, market_conflict; each with the table column header, if any),
    'matched_rows' ({block row index: [{'line', 'excerpt'}]}, at most
    MATCHED_LINES_PER_ROW per row), 'matched_counts' ({block row index: every matched
    figure, uncapped}), 'source_discrepancies'}``: the conflicts whose own [S#] supports the
    claim (``support_fn(context, tag)`` is True for one of the unit's tags, the first such
    tag recorded), i.e. two sources that disagree.  A context is the unit, or a table cell's
    whole row; an excerpt is the context cut at EXCERPT_CHARS."""
    rows = [r for r in (_figure_row(i, row) for i, row in enumerate(block_rows or [])
                        if isinstance(row, Mapping)) if r is not None]
    excluded = [r for r in (_figure_row(i, row) for i, row in enumerate(excluded_rows or [])
                            if isinstance(row, Mapping)) if r is not None]
    markets = [m for m in (_market_row(row) for row in market_rows or [] if isinstance(row, Mapping))
               if m is not None]
    counts = dict.fromkeys(CHECK_KINDS, 0)
    examples: List[Dict[str, Any]] = []
    matched_rows: Dict[int, List[Dict[str, Any]]] = {}
    matched_counts: Dict[int, int] = {}
    discrepancies: List[Dict[str, Any]] = []

    def example(kind: str, unit: _Unit, excerpt: str, figure: Mapping[str, Any], row_index: Optional[int],
                tags: Sequence[str]) -> None:
        if len(examples) < CHECK_EXAMPLES_MAX:
            examples.append({"kind": kind, "line": unit.line, "excerpt": excerpt, "column": unit.column,
                             "figure": figure["raw"][:60], "cited": tags[0] if tags else None,
                             "row_index": row_index})

    def matched(line: int, excerpt: str, agreeing: Sequence[Mapping[str, Any]]) -> None:
        counts["matched"] += 1
        for row in agreeing:
            matched_counts[row["index"]] = matched_counts.get(row["index"], 0) + 1
            used = matched_rows.setdefault(row["index"], [])
            if len(used) < MATCHED_LINES_PER_ROW:
                used.append({"line": line, "excerpt": excerpt})

    for unit in _claim_units(str(md or "")):
        figures = _claim_figures(unit.text)
        if not figures:
            continue
        anchor = _anchor_tokens(unit.context)
        tags = _cited_tags(unit.text) or _cited_tags(unit.context)
        excerpt = unit.context.strip()[:EXCERPT_CHARS]
        in_market_context = bool(_MARKET_CONTEXT_RE.search(unit.market_text))
        labelled_threshold = bool(unit.label_text and _THRESHOLD_LABEL_RE.search(unit.label_text))
        label_readings = [match.group(0) for match in
                          _PROBABILITY_LABEL_RE.finditer(_CONFIDENCE_GRADE_RE.sub(" ", unit.label_text))]
        bare_p = bool(unit.column and _BARE_P_HEADER_RE.fullmatch(unit.column))
        # A column headed by a probability word ("| Scenario | Weight |") is a probability
        # column whatever its rows name: only a row label's word can name the metric.
        header_probability = bool(unit.column and _PROBABILITY_LABEL_RE.search(
            _CONFIDENCE_GRADE_RE.sub(" ", unit.column)))
        label_words = None if bare_p or header_probability else _metric_words(label_readings)
        for figure in figures:
            if figure["threshold"] or labelled_threshold:
                counts["threshold_or_probability"] += 1
                continue
            candidates = _candidates(figure, anchor, unit.years, rows)
            # A probability word an anchored candidate's metric names ("index weight") marks
            # that metric's level, not a probability.
            probability = (figure["probability"] and not _names_words(figure["metric_words"], candidates)) \
                or ((bool(label_readings) or bare_p) and not _names_words(label_words, candidates))
            agreeing = [row for row in candidates if _states(figure, row)]
            if in_market_context and figure["cls"] == "percent":
                anchored = [m for m in markets if _anchored(anchor, m["anchor"])]
                if any(_agrees(figure, price, price) for m in anchored for price in m["prices"]):
                    counts["unmatched"] += 1
                elif agreeing and not probability:
                    matched(unit.line, excerpt, agreeing)
                elif anchored:
                    counts["market_conflict"] += 1
                    example("market_conflict", unit, excerpt, figure, None, tags)
                elif probability:
                    counts["threshold_or_probability"] += 1
                else:
                    counts["unmatched"] += 1
                continue
            if probability:
                counts["threshold_or_probability"] += 1
                continue
            if agreeing:
                matched(unit.line, excerpt, agreeing)
                continue
            comparable = [row for row in candidates if _comparable(figure, row)]
            if len({(row["lo"], row["hi"]) for row in comparable}) > 1:
                counts["ambiguous"] += 1
                example("ambiguous", unit, excerpt, figure, None, tags)
                continue
            if comparable:
                row = comparable[0]
                if _conflicts(figure, row, rel_tol):
                    counts["conflict"] += 1
                    example("conflict", unit, excerpt, figure, row["index"], tags)
                    supporting = (_supporting_tag(unit.context, tags, support_fn)
                                  if support_fn is not None else None)
                    if supporting:
                        discrepancies.append({"line": unit.line, "excerpt": excerpt, "tag": supporting,
                                              "row_index": row["index"], "claim": figure["raw"][:60],
                                              "row_value": row["value_text"]})
                    continue
                counts["unmatched"] += 1
                continue
            if not tags and any(_states(figure, row)
                                for row in _candidates(figure, anchor, unit.years, excluded)):
                counts["states_unverified"] += 1
                example("states_unverified", unit, excerpt, figure, None, tags)
                continue
            counts["unmatched"] += 1
    return {"counts": counts, "examples": examples,
            "matched_rows": {index: matched_rows[index] for index in sorted(matched_rows)},
            "matched_counts": {index: matched_counts[index] for index in sorted(matched_counts)},
            "source_discrepancies": discrepancies}
