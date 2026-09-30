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
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

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
