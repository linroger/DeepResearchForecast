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
import re
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

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


def _display(row: Mapping[str, Any], group: str, tag_for: TagFor, zh: bool,
             texts: Mapping[str, Any]) -> Dict[str, Any]:
    """The rendered cells of an admitted row (plus its sort keys)."""
    tag = _admissible_tag(tag_for(row))
    projected = group == PROJECTED
    if projected:
        when = reference_period({key: row.get(key) for key in ("target_date", "period_end")})
    else:
        when = str(row.get("as_of_date") or "").strip() or reference_period(row)
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


def _preference(shown: Mapping[str, Any]) -> Tuple[str, int, bool]:
    """Which of two admitted rows with the same cells the block keeps (the
    larger): the newest as-of date (a projection quoted on two pages, or a
    reported row whose date is only in period_end), then the better tier, then
    the current one.  With the cells, this covers every field a kept row
    carries, so the choice never depends on input order."""
    return shown["as_of_key"], -shown["tier_rank"], not shown["stale"]


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
    keys = ("metric", "value", "unit", "when", "tier", "source", "tag", "stale", "label")
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
    "omitted"}``: ``rows`` / ``projections`` are the rendered rows' cells,
    ``excluded`` counts every EXCLUDED_BUCKETS reason and ``omitted`` the
    admitted rows the caps left out.  ``sha256`` is the digest of ``rendered``
    ("" when nothing is rendered)."""
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

CHECK_KINDS = ("matched", "conflict", "ambiguous", "states_unverified", "market_conflict", "unmatched")
DEFAULT_REL_TOL = 0.02
CHECK_EXAMPLES_MAX = 24
EXCERPT_CHARS = 180
MATCHED_LINES_PER_ROW = 10
CONFLICT_RATIO = (0.1, 10.0)
# The verification labels whose rows a report may restate only as unverified (critic
# amendment: the excluded rows come from the research quantitative rows themselves).
UNVERIFIED_LABELS = ("unverified", "snippet_only", "none")
# numeric_guards unit classes -> the check's classes.  pp and bp are changes, never
# compared with a level, so each is its own class.
_CHECK_CLASS = {"percent": "percent", "currency": "currency", "count": "plain", "unknown": "plain",
                "pp": "pp", "bp": "bp"}
_REFERENCES_HEADINGS = ("## references", "## 参考来源", "## 参考文献")
_MARKET_CONTEXT_RE = re.compile(r"polymarket|kalshi|manifold|prediction[ -]?markets?|预测市场|隐含概率|implied",
                                re.I)
_ANCHOR_LATIN_RE = re.compile(r"[a-z]{4,}")
_ANCHOR_CJK_RE = re.compile(r"[㐀-䶿一-鿿]+")
_ANCHOR_STOPWORDS = frozenset({
    "about", "above", "after", "also", "around", "below", "been", "being", "from", "have", "into",
    "more", "most", "over", "percent", "than", "that", "their", "there", "these", "this",
    "those", "under", "were", "what", "when", "which", "while", "will", "with", "within", "would",
    "year", "years", "total", "level", "levels", "value", "values", "figure", "figures"})
_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2}|2100)(?!\d)")
_FIRST_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.(\d+))?")
_UNIT_TAG_RE = re.compile(r"[\[【]\s*(S\d+)\s*[\]】]", re.I)


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


def _figure_row(index: int, row: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """A block row (or an excluded research row) as the check reads it, or None when its
    value states no figure."""
    metric = str(row.get("metric") or row.get("definition") or "").strip()
    if metric.startswith("⚠"):
        metric = metric[1:].strip()
    value = _parsed_value(row.get("value"), row.get("unit"))
    if not metric or value is None:
        return None
    anchor_text = " ".join(str(row.get(key) or "") for key in ("series", "definition")) + " " + metric
    return dict(value, index=index, metric=metric, anchor=_anchor_tokens(anchor_text),
                years=_years(metric, *(row.get(key) for key in
                                       ("when", "as_of_date", "period_end", "target_date"))),
                value_text=str(row.get("value") or ""))


def _claim_units(md: str) -> Iterable[Tuple[int, str, str]]:
    """``(line number, unit, context)`` for every claim unit of ``md`` with the scan
    discipline of forecast_extractor.audit_citation_grounding (fences, headings, the
    Part-1 marker block and authored forecast sections skipped) plus the References
    section.  ``context`` is the whole table row for a table cell (the metric of a
    figure in a table is in another cell), else the unit itself."""
    from .forecast_extractor import (
        BINARY_FORECAST_END_MARKER, BINARY_FORECAST_START_MARKER, authored_forecast_markers_balanced,
        is_authored_forecast_heading, is_markdown_table_delimiter, is_markdown_table_header,
        markdown_fence_transition, markdown_table_cells, split_markdown_claim_units,
    )
    lines = str(md or "").splitlines()
    markers_valid = authored_forecast_markers_balanced(lines)
    fence = None
    in_block = in_authored = in_references = False
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        was_in_fence = fence is not None
        fence, is_fence_line = markdown_fence_transition(raw, fence)
        if is_fence_line or was_in_fence:
            continue
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
        units = split_markdown_claim_units(raw, table_header=is_markdown_table_header(lines, index),
                                           table_delimiter=is_markdown_table_delimiter(raw))
        context_row = raw if markdown_table_cells(raw) else None
        for unit in units:
            yield index + 1, unit, context_row or unit


def _claim_figures(unit: str) -> List[Dict[str, Any]]:
    """The figures of a unit worth checking: no dates or bare years, and a unit mark or at
    least two digits (a bare "3 scenarios" is no figure)."""
    from ..utils.numeric_guards import scan_quantities
    out = []
    for hit in scan_quantities(unit):
        if hit.get("date") or hit.get("year_like"):
            continue
        token = _FIRST_NUMBER_RE.search(str(hit.get("raw") or ""))
        if token is None:
            continue
        digits = token.group(0).replace(",", "")
        if not hit.get("has_marks") and len(digits.replace(".", "")) < 2:
            continue
        try:
            stated = float(digits)
        except ValueError:
            continue
        lo = float(hit["lo"])
        scale = abs(lo / stated) if stated else 1.0
        decimals = len(token.group(1) or "")
        out.append({"lo": lo, "hi": float(hit["hi"]), "raw": str(hit.get("raw") or ""),
                    "cls": _CHECK_CLASS.get(hit.get("unit_class"), "plain"),
                    "currency": hit.get("currency"),
                    "tol": 0.5 * (10 ** -decimals) * (scale or 1.0)})
    return out


def _agrees(figure: Mapping[str, Any], lo: float, hi: float) -> bool:
    """The figure states the value [lo, hi] at its own precision (a range on either side
    agrees when the intervals meet)."""
    tol = figure["tol"] + 1e-9 * max(abs(lo), abs(hi), 1.0)
    return figure["lo"] - tol <= hi and lo <= figure["hi"] + tol


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


def _conflicts(figure: Mapping[str, Any], row: Mapping[str, Any], rel_tol: float) -> bool:
    """A point figure against a point row: same sign, value ratio within CONFLICT_RATIO
    (beyond it the two are more likely different measures than a disagreement), and a
    relative difference above ``rel_tol``."""
    claim, value = figure["lo"], row["lo"]
    if figure["lo"] != figure["hi"] or row["lo"] != row["hi"] or not claim or not value:
        return False
    ratio = claim / value
    if not CONFLICT_RATIO[0] <= ratio <= CONFLICT_RATIO[1]:
        return False
    return abs(claim - value) / abs(value) > rel_tol


def _market_row(row: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    prices = []
    for key in ("implied_yes_prob", "price_at_research"):
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1:
            prices.append(float(value) * 100)
    if not prices:
        return None
    return {"anchor": _anchor_tokens(row.get("question")), "prices": prices}


def _cited_tag(unit: str) -> Optional[str]:
    match = _UNIT_TAG_RE.search(unit)
    return match.group(1).upper() if match else None


def check_verified_figures(md: Any, block_rows: Any, *, excluded_rows: Any = (), market_rows: Any = (),
                           rel_tol: float = DEFAULT_REL_TOL,
                           support_fn: Optional[Callable[[str, str], Optional[bool]]] = None) -> Dict[str, Any]:
    """Shadow check of the report's figures against the verified-figures block (REPORT-9).

    Every figure of every claim unit (:func:`_claim_units`) is classified once:

    * ``matched``: a candidate block row states the same value (across scales, or the
      row's value rounded to the claim's precision);
    * ``conflict``: exactly one candidate value, a point on both sides, within a 10x
      ratio and more than ``rel_tol`` apart;
    * ``ambiguous``: candidates with different values (never a conflict);
    * ``states_unverified``: an uncited figure equal to an anchored ``excluded_rows``
      row (research rows whose verification is unverified / snippet_only / none);
    * ``market_conflict``: a percentage in a market context (Polymarket, prediction
      market, 预测市场, 隐含概率, implied) that agrees with neither the current nor the
      research-time price of an anchored market;
    * ``unmatched``: anything else (no candidate, a range outside a row, a market
      percentage that agrees, a ratio beyond 10x).

    A candidate row shares the figure's class (percent, currency, plain; pp and bp only
    with themselves), its anchor (two Latin words of four or more letters or four CJK
    bigrams from the row's metric with the unit, or the whole table row for a cell) and
    at least one year when both name years.  Read-only and deterministic.

    Returns ``{'counts', 'examples' (<= 24: conflict, ambiguous, states_unverified,
    market_conflict), 'matched_rows' ({block row index: [{'line', 'excerpt'}]}),
    'source_discrepancies'}``: the cited conflicts whose own [S#] supports the claim
    (``support_fn(unit, tag)`` is True), i.e. two sources that disagree."""
    rows = [r for r in (_figure_row(i, row) for i, row in enumerate(block_rows or [])
                        if isinstance(row, Mapping)) if r is not None]
    excluded = [r for r in (_figure_row(i, row) for i, row in enumerate(excluded_rows or [])
                            if isinstance(row, Mapping)) if r is not None]
    markets = [m for m in (_market_row(row) for row in market_rows or [] if isinstance(row, Mapping))
               if m is not None]
    counts = dict.fromkeys(CHECK_KINDS, 0)
    examples: List[Dict[str, Any]] = []
    matched_rows: Dict[int, List[Dict[str, Any]]] = {}
    discrepancies: List[Dict[str, Any]] = []

    def example(kind: str, line: int, unit: str, figure: Mapping[str, Any], row_index: Optional[int]) -> None:
        if len(examples) < CHECK_EXAMPLES_MAX:
            examples.append({"kind": kind, "line": line, "excerpt": unit.strip()[:EXCERPT_CHARS],
                             "figure": figure["raw"][:60], "cited": _cited_tag(unit), "row_index": row_index})

    for line, unit, context in _claim_units(str(md or "")):
        figures = _claim_figures(unit)
        if not figures:
            continue
        anchor = _anchor_tokens(context)
        years = _years(unit)
        cited = _cited_tag(unit)
        in_market_context = bool(_MARKET_CONTEXT_RE.search(unit))
        for figure in figures:
            candidates = _candidates(figure, anchor, years, rows)
            agreeing = [row for row in candidates if _agrees(figure, row["lo"], row["hi"])]
            if agreeing:
                counts["matched"] += 1
                for row in agreeing:
                    used = matched_rows.setdefault(row["index"], [])
                    if len(used) < MATCHED_LINES_PER_ROW:
                        used.append({"line": line, "excerpt": unit.strip()[:EXCERPT_CHARS]})
                continue
            values = {(row["lo"], row["hi"]) for row in candidates}
            if len(values) > 1:
                counts["ambiguous"] += 1
                example("ambiguous", line, unit, figure, None)
                continue
            if candidates:
                row = candidates[0]
                if _conflicts(figure, row, rel_tol):
                    counts["conflict"] += 1
                    example("conflict", line, unit, figure, row["index"])
                    if cited and support_fn is not None:
                        try:
                            supported = support_fn(unit, cited)
                        except Exception:  # noqa: BLE001 — undecidable is not a discrepancy
                            supported = None
                        if supported is True:
                            discrepancies.append({"line": line, "excerpt": unit.strip()[:EXCERPT_CHARS],
                                                  "tag": cited, "row_index": row["index"],
                                                  "claim": figure["raw"][:60], "row_value": row["value_text"]})
                    continue
                counts["unmatched"] += 1
                continue
            if not cited and any(_agrees(figure, row["lo"], row["hi"])
                                 for row in _candidates(figure, anchor, years, excluded)):
                counts["states_unverified"] += 1
                example("states_unverified", line, unit, figure, None)
                continue
            if in_market_context and figure["cls"] == "percent":
                anchored = [m for m in markets if _anchored(anchor, m["anchor"])]
                if anchored and not any(_agrees(figure, price, price)
                                        for m in anchored for price in m["prices"]):
                    counts["market_conflict"] += 1
                    example("market_conflict", line, unit, figure, None)
                    continue
            counts["unmatched"] += 1
    return {"counts": counts, "examples": examples,
            "matched_rows": {index: matched_rows[index] for index in sorted(matched_rows)},
            "source_discrepancies": discrepancies}
