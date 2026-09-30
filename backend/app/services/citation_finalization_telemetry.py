"""RESEARCH-9: citation-surgery telemetry of the report publish stabilizer.

``ReportAgent._stabilize_publish_markdown`` finalizes citations, strips dangling,
semantically unsupported and over-used markers, removes ungrounded quotes and runs
a quantitative-grounding repair that can add machine citations and delete whole
sentences, table rows and cells, all before the read-only final audit measures the
document.  The audit sees only the surviving markers, so a report whose markers
were mostly stripped used to look clean in final_audit.json.

This module keeps one report's log of those repairs and turns it into the
``report-citation-finalization/1`` record the audit persists as final_audit.json
``pre_audit_repairs`` and forecast.json ``quality.citation_finalization``.

Pure and offline: plain dicts in and out, no config, no disk, no Markdown edits,
and never a gate input (the publish gate and the integrity issues do not read it).
Malformed counts read as 0, so a log update cannot raise on odd repair output.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

SCHEMA = "report-citation-finalization/1"
# The audit logs a WARNING at or above this share of stripped markers.
STRIP_RATIO_WARNING = 0.5

# Per-marker outcome counts of each repair.
_BUCKET_KEYS = {
    "dangling": ("kept_verified", "remapped", "stripped"),
    "semantic": ("kept", "unverifiable", "remapped", "stripped"),
}
# Every semantic pass re-checks every surviving marker, so its 'checked', 'kept'
# and 'unverifiable' re-count the same markers pass after pass.  Only remaps and
# strips are distinct events that sum; kept / unverifiable are the state of the
# latest finalization's last pass (the markers that survived it), and 'checked'
# is no log key at all.
_SEMANTIC_EVENT_KEYS = ("remapped", "stripped")
_SEMANTIC_STATE_KEYS = ("kept", "unverifiable")
_QUANTITATIVE_KEYS = (
    "citations_added", "sentences_removed", "table_rows_removed", "table_cells_cleared",
)
# Stabilizer totals the log mirrors once per pass.
_TOTALS_KEYS = ("overuse_stripped", "quotes_removed", "passes")


def _count(value: Any) -> int:
    """A non-negative integer count; anything unreadable is 0."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _ratio(value: Any) -> Optional[float]:
    """A coverage value as a float; None when absent or unreadable."""
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _coverage(audit: Any) -> Optional[float]:
    """``resolved_coverage`` of one grounding audit, else None."""
    return _ratio(audit.get("resolved_coverage")) if isinstance(audit, Mapping) else None


def new_log(report_id: str, markers_before: int) -> Dict[str, Any]:
    """A fresh log: ``markers_before`` is the body-marker total (References
    excluded) measured before the stabilizer's first citation finalization."""
    return {
        "report_id": str(report_id),
        "markers_before": _count(markers_before),
        "dangling": dict.fromkeys(_BUCKET_KEYS["dangling"], 0),
        "semantic": dict.fromkeys(_BUCKET_KEYS["semantic"], 0),
        "quantitative": {
            **dict.fromkeys(_QUANTITATIVE_KEYS, 0),
            "coverage_before": None,
            "coverage_after": None,
        },
        "overuse_stripped": 0,
        "quotes_removed": 0,
        "passes": 0,
    }


def record(
    log: Dict[str, Any],
    event: str,
    info: Any,
    *,
    first_pass: bool = False,
    state: Any = None,
) -> None:
    """Add one stabilizer event to ``log``.

    * ``dangling``: one citation finalization's dangling-repair counts (summed);
    * ``semantic``: one citation finalization's summed semantic-pass counts
      (``info``: remapped / stripped are added) and its LAST pass's counts
      (``state``: kept / unverifiable replace the previous values);
    * ``quantitative``: the diagnostics of a pass's FIRST (repairing)
      ``_repair_final_quantitative_grounding`` call.  Its counts are summed over
      passes; coverage_before is pass 1's ``before`` and coverage_after the latest
      ``after``.  The post-repair probe is never recorded: it runs on repaired text
      and would report zeros;
    * ``totals``: the stabilizer's running overuse_stripped / quotes_removed /
      passes, mirrored as they stand.
    """
    info = info if isinstance(info, Mapping) else {}
    if event == "dangling":
        bucket = log["dangling"]
        for key in _BUCKET_KEYS["dangling"]:
            bucket[key] = _count(bucket.get(key)) + _count(info.get(key))
    elif event == "semantic":
        bucket = log["semantic"]
        for key in _SEMANTIC_EVENT_KEYS:
            bucket[key] = _count(bucket.get(key)) + _count(info.get(key))
        latest = state if isinstance(state, Mapping) else {}
        for key in _SEMANTIC_STATE_KEYS:
            bucket[key] = _count(latest.get(key))
    elif event == "quantitative":
        bucket = log["quantitative"]
        for key in _QUANTITATIVE_KEYS:
            bucket[key] = _count(bucket.get(key)) + _count(info.get(key))
        if first_pass:
            bucket["coverage_before"] = _coverage(info.get("before"))
        bucket["coverage_after"] = _coverage(info.get("after"))
    elif event == "totals":
        for key in _TOTALS_KEYS:
            log[key] = _count(info.get(key))
    else:
        raise ValueError(f"unknown citation-finalization event {event!r}")


def pre_audit_repairs(log: Mapping[str, Any], markers_final: Any) -> Dict[str, Any]:
    """The ``report-citation-finalization/1`` record of ``log``.

    ``markers_final`` is the audit's body-marker total.  ``marker_strip_ratio`` is
    the markers the repairs stripped (dangling + semantic + overuse) over
    ``markers_before``; ``markers_lost_with_removed_text`` is the remaining
    imbalance, markers that disappeared with deleted text (quotes, sentences,
    rows): before + machine-added - final - stripped, never negative.
    """
    dangling_log = log.get("dangling") if isinstance(log.get("dangling"), Mapping) else {}
    semantic_log = log.get("semantic") if isinstance(log.get("semantic"), Mapping) else {}
    quant_log = log.get("quantitative") if isinstance(log.get("quantitative"), Mapping) else {}
    dangling = {key: _count(dangling_log.get(key)) for key in _BUCKET_KEYS["dangling"]}
    semantic = {key: _count(semantic_log.get(key)) for key in _BUCKET_KEYS["semantic"]}
    quantitative: Dict[str, Any] = {key: _count(quant_log.get(key)) for key in _QUANTITATIVE_KEYS}
    quantitative["coverage_before"] = _ratio(quant_log.get("coverage_before"))
    quantitative["coverage_after"] = _ratio(quant_log.get("coverage_after"))
    markers_before = _count(log.get("markers_before"))
    final = _count(markers_final)
    overuse = _count(log.get("overuse_stripped"))
    stripped = dangling["stripped"] + semantic["stripped"] + overuse
    added = quantitative["citations_added"]
    return {
        "schema": SCHEMA,
        "markers_before": markers_before,
        "markers_final": final,
        "dangling": dangling,
        "semantic": semantic,
        "overuse_stripped": overuse,
        "quotes_removed": _count(log.get("quotes_removed")),
        "passes": _count(log.get("passes")),
        "quantitative": quantitative,
        "machine_added_citations": added,
        "marker_strip_ratio": round(stripped / max(1, markers_before), 4),
        "markers_lost_with_removed_text": max(0, markers_before + added - final - stripped),
    }
