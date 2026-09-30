"""SIM-6 (P23): truthful per-period context for the calendar simulation.

One renderer for what an actor is told about the current period.  Three consumers
share it, so they cannot drift apart:

* the WORLD CLOCK memory note (``run_parallel_simulation._inject_period_context``);
* the stateless reaction-step helper prompt (``build_reaction_prompt``), which
  otherwise sees neither the period's scheduled events nor what changed;
* the per-agent catch-up of scheduled events a sampled actor sat out
  (``EventCatchUp``).

Honesty rules encoded here:

* scheduled research events are dated after the as-of date, so their outcome is
  not known in advance: they are *expected* events, never "confirmed" ones, and
  overlay injections are labelled as scenario assumptions (what-if, not observed);
* an empty "what changed" section never claims "first period" after round 0: a
  quiet period, a failed or not-yet-delivered summary and a run that produces no
  summaries each get their own marker (REPORT-6), and a summary that covers an
  older period says which period it covers;
* every cap keeps whole lines and ends with an explicit omission marker instead
  of cutting text silently (a single line too long for its section is cut with an
  explicit ``…(truncated)`` ending rather than dropped).

The REPORT-6 absence markers live here (moved verbatim from the runner) so only
one copy exists.  Herding guard: the markers carry no digits and no ``%``.

Pure and deterministic (stdlib plus ``sim_event_provenance`` and the whole-line
cap of ``world_delta``).  Callers own every knob: SIM_PERIOD_CONTEXT_V2,
SIM_ABSENCE_MARKERS, SIM_WORLD_DELTA and SIM_EVENT_CATCHUP_MAX_CHARS.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .sim_event_provenance import EVENT_PROVENANCE_SCENARIO, classify_event
from .world_delta import fit_whole_lines

# REPORT-6 absence markers (SIM_ABSENCE_MARKERS). Byte-identical to the strings the
# runner defined before SIM-6; no digits and no "%" (herding guard).
WORLD_CLOCK_NO_EVENTS = ("(no dated research event is scheduled for this period — "
                         "this does not mean nothing happened in the world)")
WORLD_CLOCK_FIRST_PERIOD = "(first period — nothing has happened in this simulation yet)"
WORLD_CLOCK_QUIET_PERIOD = ("(no scheduled event and no notable public move was recorded "
                            "last period)")
WORLD_CLOCK_SUMMARY_UNAVAILABLE = ("(last period's summary is unavailable in this run — "
                                   "this is not evidence that nothing happened)")
WORLD_CLOCK_SUMMARY_NOT_PRODUCED = ("(period summaries are not produced in this run — "
                                    "this is not evidence that nothing happened)")
# Legacy placeholders (SIM_ABSENCE_MARKERS=false, or a caller that passes no delta state).
LEGACY_NO_EVENTS = "(none)"
LEGACY_FIRST_PERIOD = "(first period)"

LEGACY_EVENTS_HEADING = "## CONFIRMED EVENTS THIS PERIOD"
SCHEDULED_EVENTS_HEADING_V2 = ("## SCHEDULED EVENTS THIS PERIOD (research timeline — expected; "
                               "outcomes not known in advance)")
WHAT_CHANGED_HEADING = "## WHAT CHANGED LAST PERIOD"
THIS_PERIOD_HEADING = "## THIS PERIOD — scheduled events (research timeline)"
CATCHUP_HEADING = "## EARLIER SCHEDULED EVENTS YOU HAVE NOT BEEN BRIEFED ON"
SCENARIO_ASSUMPTION_PREFIX = "SCENARIO ASSUMPTION (what-if, not observed): "
# Shown above a summary that covers an older period than the one just finished: a dead
# round or the dual-platform watermark can leave the latest summary one or more periods
# behind the clock.
STALE_DIGEST_LINE = ("(latest available digest covers {label}; no digest of the most recent "
                     "period is available)")

REACTION_CONTEXT_MAX_CHARS = 1200
# compact_period_context: this period's events come first, but the "what changed"
# section keeps at least this much of an overflowing budget (a couple of digest lines).
_DELTA_RESERVE_CHARS = 300


def _catchup_marker(n: int) -> str:
    return f"(+{n} earlier scheduled events omitted)"


def _more_marker(n: int) -> str:
    return f"(+{n} more omitted)"


def _event_line(ev: Any, scenario_labels: bool) -> str:
    """One event as shown to an actor ('' when it has no content).

    Date rule of the legacy header: add ``[date] `` unless the content already starts
    with ``[`` (the config generator prefixes calendar events itself)."""
    if not isinstance(ev, dict):
        return ""
    content = str(ev.get("content", "") or "").strip()
    if not content:
        return ""
    scenario = scenario_labels and classify_event(ev) == EVENT_PROVENANCE_SCENARIO
    if scenario and content.startswith(SCENARIO_ASSUMPTION_PREFIX):
        return content
    date = str(ev.get("date", "") or "").strip()
    if date and not content.startswith("["):
        content = f"[{date}] {content}"
    return SCENARIO_ASSUMPTION_PREFIX + content if scenario else content


def _event_lines(events: Optional[Iterable[Any]], scenario_labels: bool = True) -> List[str]:
    try:
        return [line for line in (_event_line(ev, scenario_labels) for ev in events or []) if line]
    except TypeError:  # a non-iterable events value renders like no events
        return []


def render_event_lines(events: Optional[Iterable[Any]], *, markers: bool,
                       scenario_labels: bool = True) -> List[str]:
    """The period's scheduled events, one line each, in config order.

    Scenario injections are prefixed ``SCENARIO ASSUMPTION (what-if, not observed): ``
    (``scenario_labels=False`` reproduces the legacy header lines).  No events →
    REPORT-6's no-scheduled-event marker when ``markers`` is on, ``(none)`` when off."""
    lines = _event_lines(events, scenario_labels)
    if lines:
        return lines
    return [WORLD_CLOCK_NO_EVENTS if markers else LEGACY_NO_EVENTS]


def render_delta_lines(delta_text: Any, delta_state: Optional[str], *, round_num: int,
                       stale_label: str = "", markers: bool) -> List[str]:
    """Body of the WHAT CHANGED LAST PERIOD section.

    ``delta_state`` is REPORT-6's provenance of the summary (``not_stepped`` /
    ``stepped`` / ``quiet`` / ``failed``, or the caller's ``no_inband``).

    markers on: round 0 → first-period marker; a non-empty summary → its lines;
    ``quiet`` → quiet marker; ``no_inband`` → not-produced marker; anything else →
    "unavailable in this run" (fail closed).  Never "first period" after round 0.

    markers off: the summary or ``(first period)``, exactly as the legacy header.

    Either way a non-empty summary is preceded by the stale line when ``stale_label``
    names the older period it covers.  The stale line is not a placeholder: the caller
    passes ``stale_label`` only under SIM_PERIOD_CONTEXT_V2, which governs it."""
    text = str(delta_text or "").strip()
    if markers and round_num == 0:
        return [WORLD_CLOCK_FIRST_PERIOD]
    if text:
        stale = [STALE_DIGEST_LINE.format(label=stale_label)] if stale_label else []
        return stale + text.split("\n")
    if not markers:
        return [LEGACY_FIRST_PERIOD]
    if delta_state == "quiet":
        return [WORLD_CLOCK_QUIET_PERIOD]
    if delta_state == "no_inband":
        return [WORLD_CLOCK_SUMMARY_NOT_PRODUCED]
    return [WORLD_CLOCK_SUMMARY_UNAVAILABLE]


def compact_period_context(event_lines: Optional[Iterable[Any]],
                           delta_lines: Optional[Iterable[Any]],
                           max_chars: int = REACTION_CONTEXT_MAX_CHARS) -> str:
    """The period context for a stateless helper prompt, at most ``max_chars``.

    ``## THIS PERIOD — scheduled events (research timeline)`` with the event lines,
    then ``## WHAT CHANGED LAST PERIOD`` with the delta lines (the section is left out
    when ``delta_lines`` is empty, i.e. SIM_WORLD_DELTA is off).  When the whole text
    does not fit, each section keeps whole lines in order and ends with
    ``(+N more omitted)`` (a first line too long on its own is cut with an explicit
    ``…(truncated)`` ending, see ``world_delta.fit_whole_lines``).  The period's
    events have priority: they get what they need up to all but
    ``_DELTA_RESERVE_CHARS`` of the budget (never less than half), the delta the rest,
    and a section that needs less lends its slack to the other.  Headings and omission
    markers are never dropped, so a cap smaller than them yields just those lines."""
    events = [str(line) for line in event_lines or []]
    delta = [str(line) for line in delta_lines or []]
    sections = [(THIS_PERIOD_HEADING, events)]
    if delta:
        sections.append((WHAT_CHANGED_HEADING, delta))
    full = "\n".join("\n".join([heading, *lines]) for heading, lines in sections)
    if len(full) <= max_chars:
        return full
    # Each heading is followed by a newline, and sections are joined by one.
    overhead = sum(len(heading) + 1 for heading, _ in sections) + len(sections) - 1
    budget = max(0, int(max_chars) - overhead)
    if len(sections) == 1:
        budgets = [budget]
    else:
        ev_len, de_len = len("\n".join(events)), len("\n".join(delta))
        ev_cap = min(ev_len, max(budget // 2, budget - _DELTA_RESERVE_CHARS))
        if de_len < budget - ev_cap:
            ev_cap = budget - de_len
        budgets = [ev_cap, budget - ev_cap]
    parts = []
    for (heading, lines), cap in zip(sections, budgets, strict=True):
        kept, omitted = fit_whole_lines(lines, cap, _more_marker)
        parts.append("\n".join([heading, *kept] + ([_more_marker(omitted)] if omitted else [])))
    return "\n".join(parts)


class EventCatchUp:
    """Scheduled events a sampled actor sat out, delivered on its next activation.

    A sampled actor inactive in the round an event fires never receives that round's
    WORLD CLOCK note.  ``missed(aid, round_num)`` returns the events of every round r
    with ``last_briefed < r < round_num`` (chronological); ``mark_briefed`` records a
    successful injection.  Events are indexed with ``_scheduled_events_due``'s
    matching rule (``int(round)``; invalid rounds are skipped).

    Resume-safe: the index is rebuilt from the config, and after a lossy resume the
    first activation re-delivers earlier events, which is correct because the
    resumed process rebuilt every agent's memory."""

    def __init__(self, event_config: Any, max_chars: int = 1200) -> None:
        self._max_chars = int(max_chars)
        self._by_round: Dict[int, List[Dict[str, Any]]] = {}
        self._last_briefed: Dict[Any, int] = {}
        events = event_config.get("scheduled_events") if isinstance(event_config, dict) else None
        for ev in events or []:
            if not isinstance(ev, dict):
                continue
            try:
                rnd = int(ev.get("round", -1))
            except (TypeError, ValueError):
                continue
            self._by_round.setdefault(rnd, []).append(ev)

    def missed(self, aid: Any, round_num: int) -> List[Dict[str, Any]]:
        last = self._last_briefed.get(aid, -1)
        out: List[Dict[str, Any]] = []
        for rnd in sorted(self._by_round):
            if last < rnd < round_num:
                out.extend(self._by_round[rnd])
        return out

    def mark_briefed(self, aid: Any, round_num: int) -> None:
        self._last_briefed[aid] = max(self._last_briefed.get(aid, -1), int(round_num))

    def render(self, events: Optional[Iterable[Any]]) -> str:
        """'' without events; otherwise the catch-up block, newest event first (``events``
        in chronological order, as ``missed`` returns them).  Whole lines, at most
        ``max_chars`` in total, ending with ``(+N earlier scheduled events omitted)``
        when older events are dropped (a newest event too long on its own is cut with an
        explicit ``…(truncated)`` ending); the heading and the marker are never dropped."""
        lines = _event_lines(events)
        if not lines:
            return ""
        lines.reverse()
        kept, omitted = fit_whole_lines(lines, self._max_chars - len(CATCHUP_HEADING) - 1,
                                        _catchup_marker)
        return "\n".join([CATCHUP_HEADING, *kept] + ([_catchup_marker(omitted)] if omitted else []))
