"""Typed absence markers for optional prompt slots (REPORT-4).

Several report-stage prompts carry optional upstream material: the simulation
signal pack, the prediction-market table, the forecast spine, earlier sections.
When such a slot was blank (or held the literal ``（无）``), the model could read
the blank as a finding ("no market prices this", "the simulation shows
nothing"), or name a signal that was never injected.  This module renders an
absent slot as an explicit, typed marker instead, so a prompt tells the model
*why* the slot is empty and that nothing may be concluded from it.

Three absence states are told apart:

* ``not_run``     -- the step is not part of this run (disabled or not injected);
* ``empty``       -- the step ran and found nothing usable (a search result,
  not evidence that the thing does not exist);
* ``unavailable`` -- the step failed or its output could not be read.

Idea credit: TradingAgents (Apache-2.0), ``report_or_absent`` and
``opponent_argument_or_opening``: an absent upstream report renders as an
explicit marker rather than a blank, and an instruction that depends on absent
material is omitted.  Reimplemented from the idea; no code was copied.  The
three-way not_run / empty / unavailable taxonomy is a DRF-original extension
(the source distinguishes only present from absent).

Pure and stdlib-only so it is unit-testable offline; nothing here raises.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict

SLOT_PRESENT = "present"
SLOT_NOT_RUN = "not_run"
SLOT_EMPTY = "empty"
SLOT_UNAVAILABLE = "unavailable"
SLOT_STATES = (SLOT_PRESENT, SLOT_NOT_RUN, SLOT_EMPTY, SLOT_UNAVAILABLE)


@dataclass(frozen=True)
class SlotStatus:
    """State of one optional prompt slot plus a machine-readable reason code."""

    state: str
    reason: str = ""
    detail: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"state": self.state, "reason": self.reason, "detail": self.detail}


def present(reason: str = "", detail: str = "") -> SlotStatus:
    return SlotStatus(SLOT_PRESENT, reason, detail)


def not_run(reason: str = "", detail: str = "") -> SlotStatus:
    return SlotStatus(SLOT_NOT_RUN, reason, detail)


def empty(reason: str = "", detail: str = "") -> SlotStatus:
    return SlotStatus(SLOT_EMPTY, reason, detail)


def unavailable(reason: str = "", detail: str = "") -> SlotStatus:
    return SlotStatus(SLOT_UNAVAILABLE, reason, detail)


# Marker templates.  A marker never carries a digit (the reason code is sanitised
# to [a-z_]), so the numeric-grounding checks can never mistake it for a figure.
_MARKERS: Dict[str, Dict[str, str]] = {
    "zh": {
        SLOT_NOT_RUN: "（{slot}：本次运行未启用该步骤——不是空结果，不可据此推断任何结论）",
        SLOT_EMPTY: "（{slot}：已执行检索但未找到可用结果（{reason}）——这是检索结果，不代表现实中不存在）",
        SLOT_UNAVAILABLE: "（{slot}：本次运行中不可用（{reason}）——不是空结果，不可据此推断任何结论）",
    },
    "en": {
        SLOT_NOT_RUN: "({slot}: not part of this run — not an empty finding; "
                      "draw no conclusion from its absence.)",
        SLOT_EMPTY: "({slot}: searched, nothing usable found ({reason}) — a search result, "
                    "not evidence of absence in the world.)",
        SLOT_UNAVAILABLE: "({slot}: unavailable in this run ({reason}) — not an empty finding; "
                          "draw no conclusion from its absence.)",
    },
}

# Phrases unique to the marker texts above.  report_lint treats any of them in
# published prose as a leak (a marker copied from the prompt into the report).
MARKER_SENTINELS = (
    "not an empty finding",
    "not part of this run",
    "unavailable in this run",
    "not evidence of absence in the world",
    "不是空结果",
    "本次运行未启用",
    "本次运行中不可用",
    "不代表现实中不存在",
)

_REASON_SEPARATOR_RE = re.compile(r"[\s\-./:]+")
_REASON_DROP_RE = re.compile(r"[^a-z_]")
_REASON_UNDERSCORES_RE = re.compile(r"_+")


def _sanitize_reason(reason: Any) -> str:
    """Reduce a reason code to ``[a-z_]`` (digits and all other characters dropped)."""
    text = _REASON_SEPARATOR_RE.sub("_", str(reason or "").strip().lower())
    text = _REASON_UNDERSCORES_RE.sub("_", _REASON_DROP_RE.sub("", text)).strip("_")
    return text or "unspecified"


def _marker_lang(lang: Any) -> str:
    return "en" if str(lang or "").strip().lower().startswith("en") else "zh"


def absence_marker(slot_label: str, status: SlotStatus, lang: str = "zh") -> str:
    """Render the typed absence marker for ``slot_label`` in the host prompt's language.

    ``lang`` starting with 'en' selects English; anything else selects Chinese.  A
    ``present`` status needs no marker and returns ''.  An unknown state renders as
    ``unavailable``.  Digits are removed from the slot label and the reason, so the
    marker never contains a digit.
    """
    state = str(getattr(status, "state", "") or "")
    if state == SLOT_PRESENT:
        return ""
    if state not in _MARKERS["zh"]:
        state = SLOT_UNAVAILABLE
    slot = "".join(ch for ch in str(slot_label or "") if not ch.isdigit()).strip()
    template = _MARKERS[_marker_lang(lang)][state]
    return template.format(slot=slot, reason=_sanitize_reason(getattr(status, "reason", "")))


def _count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


# Labels written by the multi-track merge (pipeline_orchestrator.merge_market_snapshots
# ``status.state``) and by the research bridge (``status.empty_reason``).
_STATE_EMPTY = frozenset({"verified_empty", "all_candidates_irrelevant"})
_STATE_UNAVAILABLE = frozenset({"transport_failure", "partial_transport_failure",
                                "inflight_timeout"})
_EMPTY_REASONS = frozenset({"no_equivalent_market", "all_candidates_irrelevant",
                            "no_derivable_queries"})


def market_status(payload: Any, *, enabled: bool) -> SlotStatus:
    """Classify a ``prediction_markets.json`` payload into a prompt-slot status.

    ``status.state`` (the merge's rich label) is read first.  Without it, a
    transport failure on any query makes the result ``unavailable``: the bridge
    folds a partial outage with no candidates into ``no_equivalent_market``, so
    that label is trusted as ``empty`` only when every query succeeded.
    """
    if not enabled:
        return not_run("prediction_markets_disabled")
    if not isinstance(payload, dict):
        return unavailable("no_market_snapshot")
    markets = payload.get("markets")
    if isinstance(markets, list) and any(isinstance(row, dict) for row in markets):
        return present("research_snapshot")
    status = payload.get("status")
    status = status if isinstance(status, dict) else {}
    state = str(status.get("state") or "").strip().lower()
    if state == "markets_selected":
        return present(state)
    if state in _STATE_EMPTY:
        return empty(state)
    if state in _STATE_UNAVAILABLE:
        return unavailable(state)
    empty_reason = str(status.get("empty_reason") or "").strip().lower()
    if empty_reason == "transport_failure":
        return unavailable(empty_reason)
    failures = _count(status.get("transport_failure_count"))
    successes = _count(status.get("successful_query_count"))
    queries = _count(status.get("query_count", status.get("attempted_query_count")))
    if failures > 0 and (successes == 0 or successes < queries):
        return unavailable("partial_transport_failure")
    if empty_reason in _EMPTY_REASONS:
        return empty(empty_reason)
    if payload.get("no_relevant_markets"):
        return empty("no_relevant_markets")
    return unavailable("unknown_status")
