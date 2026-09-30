"""SIM-5 (C42): provenance of scheduled simulation events (ADR-0002 I-11).

Research key_events and scenario injections are replayed on the simulated feed
as CREATE_POSTs by a real actor agent, chosen by name match or, failing that,
as the top-influence fallback (``SimulationConfigGenerator._build_scheduled_events``;
scenario overlays always carry a ``poster_name``).  The post therefore sits under
an actor's account although no actor said it.  This module is the single source
of truth that lets every DRF consumer tell those injected rows apart from actor
behaviour:

* ``label_event_post`` is what ``fire_scheduled_events`` posts and logs, and
  ``event_post_contents`` rebuilds exactly those strings, so the feed text and the
  consumers' matcher can never drift apart;
* ``is_injected_row`` is the one predicate for rows that are not an actor's own
  choice (round-0 seeding, timeline replays, seed actions, sampled likes).

Pure and stdlib-only: the simulation child, the Flask process and the offline
tests all import it without side effects.  Callers own the SIM_EVENT_PROVENANCE
gate; nothing here reads configuration.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Set

EVENT_PROVENANCE_RESEARCH = "research_timeline"
EVENT_PROVENANCE_SCENARIO = "scenario_assumption"

_POST_LABELS = {
    EVENT_PROVENANCE_RESEARCH: (
        "[WORLD EVENT · scheduled on the research timeline · not a statement by any actor] "
    ),
    EVENT_PROVENANCE_SCENARIO: "[SCENARIO ASSUMPTION · what-if, not observed] ",
}
# A post already carrying any provenance label is never labelled again.
_LABEL_HEADS = tuple(label.strip() for label in _POST_LABELS.values())

# Author slot shown in reaction prompts instead of the poster actor's name.
EVENT_AUTHOR_RESEARCH = (
    "SCHEDULED WORLD EVENT (research timeline; posted on the feed, not said by any actor)"
)
EVENT_AUTHOR_SCENARIO = (
    "SCHEDULED SCENARIO ASSUMPTION (what-if; posted on the feed, not said by any actor)"
)

# action_args markers of rows the simulation injected rather than an actor chose.
_INJECTED_MARKERS = ("is_scheduled_event", "is_seed_action", "is_engagement_sample")


def classify_event(ev: Any) -> str:
    """Scenario assumption when the row carries ``is_scenario_injection``; research
    timeline otherwise.  Authorship is not a signal: overlay rows always name a
    poster, so an explicit poster cannot be told from the fallback one."""
    if isinstance(ev, Mapping) and ev.get("is_scenario_injection"):
        return EVENT_PROVENANCE_SCENARIO
    return EVENT_PROVENANCE_RESEARCH


def label_event_post(content: Any, provenance: str) -> str:
    """Prefix the feed text with its provenance label; idempotent.

    An unknown provenance gets the research label: an injected post is never
    left looking like an actor's own statement."""
    text = str(content or "")
    if text.lstrip().startswith(_LABEL_HEADS):
        return text
    return _POST_LABELS.get(provenance, _POST_LABELS[EVENT_PROVENANCE_RESEARCH]) + text


def event_author_label(content: Any) -> str:
    """Author slot for an event post, chosen from the label its feed text carries."""
    head = _POST_LABELS[EVENT_PROVENANCE_SCENARIO].strip()
    if str(content or "").lstrip().startswith(head):
        return EVENT_AUTHOR_SCENARIO
    return EVENT_AUTHOR_RESEARCH


def strip_event_label(content: Any) -> str:
    """The event text without its leading provenance label, for a slot that already names
    the provenance (``event_author_label``); text without a label is returned unchanged."""
    text = str(content or "")
    body = text.lstrip()
    for head in _LABEL_HEADS:
        if body.startswith(head):
            return body[len(head):].lstrip()
    return text


def event_post_contents(events: Optional[Iterable[Any]], labelled: bool) -> Set[str]:
    """The exact strings ``fire_scheduled_events`` posts for ``events``, stripped.

    Mirrors its skip rule (no poster or empty content is never posted); with
    ``labelled`` each string carries the provenance label the feed shows."""
    out: Set[str] = set()
    for ev in events or []:
        if not isinstance(ev, Mapping) or ev.get("poster_agent_id") is None:
            continue
        content = str(ev.get("content", "") or "")
        if not content:
            continue
        posted = label_event_post(content, classify_event(ev)) if labelled else content
        posted = posted.strip()
        if posted:
            out.add(posted)
    return out


def is_injected_row(action_args: Any, round_num: Any) -> bool:
    """True for rows that are not an actor's own choice: round <= 0 (seeding), or
    a scheduled-event replay, seed action or sampled like.  An unreadable round
    cannot be shown to be organic, so it counts as injected."""
    try:
        if int(round_num or 0) <= 0:
            return True
    except (TypeError, ValueError):
        return True
    args = action_args if isinstance(action_args, Mapping) else {}
    return any(args.get(marker) for marker in _INJECTED_MARKERS)
