"""SIM-3 (C16): reachability audit of scheduled simulation events.

``event_config.scheduled_events`` rows (research key_events and scenario-overlay
injections) are replayed by ``fire_scheduled_events`` in
``backend/scripts/run_parallel_simulation.py``: the platform loop runs
``range(start_round, total_rounds)`` over 0-based event rounds and fires the rows
whose ``round`` equals the loop round, skipping rows without a poster or content.
A row that can never reach that path is a world event the simulated actors never
saw, yet the run used to look complete.  The real exposure is legacy hours mode:
overlay ``injected_events`` keep their raw round, and an overlay ``max_rounds``
shrinks the run after the schedule was built (calendar mode clamps both at config
time).

``audit_scheduled_events`` counts those rows for ``run_summary.json``;
``unreachable_issue`` turns the stored block into the pipeline run-health issue.
Rows inside the horizon but after a truncation point are not counted: the run
summary already reports those as ``simulation_health='truncated'``.

Pure and stdlib-only; callers own the SIM_SCHEDULE_AUDIT gate and nothing here
reads configuration.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

# Reasons in the order they are checked; the first match wins.
REASON_INVALID_ROUND = "invalid_round"
REASON_BEYOND_TOTAL_ROUNDS = "beyond_total_rounds"
REASON_MISSING_POSTER = "missing_poster"
REASON_MISSING_CONTENT = "missing_content"
REASONS = (
    REASON_INVALID_ROUND,
    REASON_BEYOND_TOTAL_ROUNDS,
    REASON_MISSING_POSTER,
    REASON_MISSING_CONTENT,
)

MAX_SAMPLES = 10

_JSON_SCALARS = (str, int, float, bool)


def _event_round(value: Any) -> Optional[int]:
    """The 0-based round ``fire_scheduled_events`` would compare against, or None
    when the value is missing, not int-coercible or negative (never fires)."""
    if value is None:
        return None
    try:
        rnd = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return rnd if rnd >= 0 else None


def _horizon(total_rounds: Any) -> Optional[int]:
    """The executed round count when it is a positive int; otherwise the horizon
    check is skipped (bool is not a round count)."""
    if isinstance(total_rounds, int) and not isinstance(total_rounds, bool) and total_rounds > 0:
        return total_rounds
    return None


def _json_safe(value: Any) -> Any:
    """Keep JSON scalars as they are; stringify anything else so the sample can
    never break the run_summary.json dump."""
    if value is None or isinstance(value, _JSON_SCALARS):
        return value
    return str(value)


def _unreachable_reason(event: Any, horizon: Optional[int]) -> Optional[str]:
    ev = event if isinstance(event, Mapping) else {}
    rnd = _event_round(ev.get("round"))
    if rnd is None:
        return REASON_INVALID_ROUND
    if horizon is not None and rnd >= horizon:
        return REASON_BEYOND_TOTAL_ROUNDS
    if ev.get("poster_agent_id") is None:
        return REASON_MISSING_POSTER
    if not str(ev.get("content") or "").strip():
        return REASON_MISSING_CONTENT
    return None


def audit_scheduled_events(
    scheduled_events: List[Dict[str, Any]],
    total_rounds: Optional[int],
) -> Dict[str, Any]:
    """Count the scheduled events that can never fire.

    Returns ``{'scheduled': n, 'unreachable': k, 'by_reason': {reason: count},
    'samples': [{'round', 'date', 'reason', 'is_scenario_injection'}]}``.
    ``by_reason`` lists only reasons that occurred, in check order; ``samples``
    holds at most ``MAX_SAMPLES`` unreachable rows in schedule order, so the
    output is deterministic for a given input.  ``total_rounds`` that is not a
    positive int skips the horizon check.
    """
    events = list(scheduled_events or [])
    horizon = _horizon(total_rounds)
    counts = dict.fromkeys(REASONS, 0)
    samples: List[Dict[str, Any]] = []
    for event in events:
        reason = _unreachable_reason(event, horizon)
        if reason is None:
            continue
        counts[reason] += 1
        if len(samples) < MAX_SAMPLES:
            ev = event if isinstance(event, Mapping) else {}
            samples.append({
                "round": _json_safe(ev.get("round")),
                "date": _json_safe(ev.get("date")),
                "reason": reason,
                "is_scenario_injection": bool(ev.get("is_scenario_injection")),
            })
    by_reason = {reason: n for reason, n in counts.items() if n}
    return {
        "scheduled": len(events),
        "unreachable": sum(by_reason.values()),
        "by_reason": by_reason,
        "samples": samples,
    }


def unreachable_issue(audit: Any) -> Optional[Tuple[int, str]]:
    """``(k, issue)`` for a run_summary ``schedule_audit`` block whose ``unreachable``
    is a positive int, else None (absent, malformed or zero never raises an issue)."""
    if not isinstance(audit, Mapping):
        return None
    k = audit.get("unreachable")
    if not isinstance(k, int) or isinstance(k, bool) or k <= 0:
        return None
    by_reason = audit.get("by_reason")
    parts = [f"{reason}={n}" for reason, n in by_reason.items()] \
        if isinstance(by_reason, Mapping) else []
    detail = ", ".join(parts) or "reason unknown"
    return k, (f"{k} scheduled event(s) could never fire ({detail}) — "
               "the simulated actors never saw them")
