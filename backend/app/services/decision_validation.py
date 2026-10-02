"""SIM-2 (C26): roster-bound validation of one decision-channel elicitation reply.

The decision channel asks the LLM, in one batched call per round, where each
roster actor commits (``{agent_id, scenario, magnitude, confidence}``). Before
this module the parsed reply was trusted almost verbatim: a hallucinated id
(``999``) or a duplicate row voted, ``magnitude: 7`` dominated a round, a string
id (``"3"``) lost its actor's outcome power, ``magnitude: "inf"`` inverted the
distribution, and a missing magnitude silently became the maximum 1.0.

``validate_round_decisions`` binds a reply to the round roster and returns only
canonical, bounded commitments plus a reason-coded record of every rejection and
normalisation. ``summarize_validation`` folds the per-round records into the
run-level ``fallback_share`` (roster slots without an accepted or abstained
answer) that ``decision_channel_verdict`` uses to demote an otherwise valid run.

Pure and deterministic (stdlib plus the WorldState round-status constants), so
the RUN child imports it exactly like ``worldstate.py``. It never emits
``infeasible``: that status stays reserved for WP11 feasibility rejection.
"""

from __future__ import annotations

import math
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from .worldstate import (
    ROUND_STATUS_ABSTAINED,
    ROUND_STATUS_COMMITTED,
    ROUND_STATUS_SILENT,
)

DECISION_VALIDATION_POLICY_V1: Dict[str, Any] = {
    "version": "drf-decision-validation/v1",
    # legacy default for an absent confidence (kept, but counted as confidence_defaulted)
    "default_confidence": 0.7,
    # cap on per-round rejected_samples kept for diagnosis
    "max_rejected_samples": 10,
}

# Rejection reason codes: every reply element that is neither accepted nor
# abstained is counted under exactly one of these.
REASON_MALFORMED_ENTRY = "malformed_entry"
REASON_UNKNOWN_AGENT = "unknown_agent"
REASON_DUPLICATE = "duplicate"
REASON_INVALID_SCENARIO = "invalid_scenario"
REASON_MISSING_MAGNITUDE = "missing_magnitude"
REASON_NON_NUMERIC = "non_numeric"
REASON_CODES: Tuple[str, ...] = (
    REASON_MALFORMED_ENTRY, REASON_UNKNOWN_AGENT, REASON_DUPLICATE,
    REASON_INVALID_SCENARIO, REASON_MISSING_MAGNITUDE, REASON_NON_NUMERIC,
)

# Normalisation codes: repairs applied to an entry that was then accepted or abstained.
NORM_ID_COERCED = "id_coerced"
NORM_SCENARIO_NORMALIZED = "scenario_normalized"
NORM_CLAMPED = "clamped"
NORM_CONFIDENCE_DEFAULTED = "confidence_defaulted"
NORMALIZATION_CODES: Tuple[str, ...] = (
    NORM_ID_COERCED, NORM_SCENARIO_NORMALIZED, NORM_CLAMPED, NORM_CONFIDENCE_DEFAULTED,
)

# Whitespace plus the quote/bracket characters an LLM wraps scenario names in
# (the spec's list, plus single curly quotes and 《》 title marks).
_SCENARIO_STRIP_CHARS = " \t\r\n\x0b\x0c" + "「」『』“”‘’《》\"'()（）[]【】"

_COUNT_KEYS = ("accepted", "abstained", "rejected", "missing_from_reply", "fallback_slots")


def _norm(text: str) -> str:
    """Scenario comparison key: NFKC, casefold, then strip surrounding
    whitespace and quote/bracket characters."""
    return unicodedata.normalize("NFKC", str(text)).casefold().strip(_SCENARIO_STRIP_CHARS)


def _id_text(raw: Any) -> str:
    """``str(raw)``, except that an integral float is rendered as its int (``1.0``
    → ``"1"``): a JSON reply may carry a whole-number id as a float."""
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    return str(raw)


def _canonical_id_key(raw: Any) -> str:
    """``_id_text(raw)`` stripped, with a leading ``id=`` (any case) removed — the
    roster lines render as ``- id=<agent_id>``, and models echo that prefix."""
    key = _id_text(raw).strip()
    if key[:3].casefold() == "id=":
        key = key[3:].strip()
    return key


def _unit_value(raw: Any) -> Tuple[Optional[float], bool]:
    """Parse a magnitude/confidence value into ``[0, 1]``.

    Returns ``(value, clamped)``; ``value`` is ``None`` when ``raw`` is a bool,
    a non-numeric string or type, NaN or ±inf. A finite value outside ``[0, 1]``
    is clamped and flagged.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        return None, False
    try:
        value = float(raw.strip() if isinstance(raw, str) else raw)
    except (ValueError, OverflowError):  # OverflowError: an int too large for a float
        return None, False
    if not math.isfinite(value):
        return None, False
    bounded = min(1.0, max(0.0, value))
    return bounded, bounded != value


def _zero_counts(codes: Tuple[str, ...]) -> Dict[str, int]:
    return dict.fromkeys(sorted(codes), 0)


def validate_round_decisions(raw_decisions: Any, roster: List[Dict[str, Any]],
                             scenarios: List[str], *, abstain_token: str) -> Dict[str, Any]:
    """Bind one parsed ``decisions`` list to the round roster.

    Elements are processed in answer order; each one ends up accepted, abstained
    or rejected under exactly one reason code:

    - not a dict → ``malformed_entry``;
    - its id, canonicalised through the roster (``"3"`` → ``3``, ``"id=2"`` →
      ``2``, ``1.0`` → ``1``, ``"__public__"`` stays a string), is not a roster id →
      ``unknown_agent`` (it never votes and is not a roster slot);
    - its canonical id was already named by an earlier element → ``duplicate``
      (the first element naming an actor is that actor's answer);
    - its scenario is the abstain token (after normalisation) → abstained, with
      magnitude and confidence ignored; an exact candidate or a unique match
      under ``_norm`` → ok; otherwise → ``invalid_scenario``;
    - magnitude absent or ``None`` → ``missing_magnitude``; bool, non-numeric or
      non-finite → ``non_numeric``; outside ``[0, 1]`` → clamped;
    - confidence absent or ``None`` → the policy default 0.7; bool, non-numeric
      or non-finite → ``non_numeric``; outside ``[0, 1]`` → clamped.

    Normalisation counters (``id_coerced``, ``scenario_normalized``,
    ``clamped``, ``confidence_defaulted``) describe the entries that were kept
    (accepted or abstained); a rejected entry is counted only under its reason.

    ``round_status`` is ``committed`` when anything was accepted, else
    ``abstained`` when anything abstained, else ``silent`` (answered, but no
    usable decision). ``missing_from_reply`` counts roster actors no element
    named; ``fallback_slots`` counts roster actors with neither an accepted nor
    an abstained answer. Deterministic: identical inputs give identical outputs.

    Returns ``{accepted, abstained_ids, round_status, record}``; ``accepted``
    rows are ``{agent_id, scenario, magnitude, confidence}`` in answer order.
    """
    policy = DECISION_VALIDATION_POLICY_V1
    roster_by_key: Dict[str, Any] = {}
    for entry in roster or []:
        if isinstance(entry, dict) and entry.get("agent_id") is not None:
            roster_by_key.setdefault(_id_text(entry["agent_id"]), entry["agent_id"])
    candidates = [str(s) for s in (scenarios or [])]
    by_norm: Dict[str, List[str]] = {}
    for name in candidates:
        by_norm.setdefault(_norm(name), []).append(name)
    abstain_norm = _norm(abstain_token)
    elements = list(raw_decisions) if isinstance(raw_decisions, list) else []

    reasons = _zero_counts(REASON_CODES)
    normalized = _zero_counts(NORMALIZATION_CODES)
    accepted: List[Dict[str, Any]] = []
    abstained_ids: List[Any] = []
    seen: set = set()       # roster id keys already named by an element
    answered: set = set()   # roster id keys with an accepted or abstained answer
    rejected_samples: List[Dict[str, str]] = []

    def _reject(raw_id: Any, code: str) -> None:
        reasons[code] += 1
        if len(rejected_samples) < int(policy["max_rejected_samples"]):
            rejected_samples.append({"agent_id": repr(raw_id)[:40], "reason": code})

    for element in elements:
        if not isinstance(element, dict):
            _reject(element, REASON_MALFORMED_ENTRY)
            continue
        raw_id = element.get("agent_id")
        key = _canonical_id_key(raw_id)
        if key not in roster_by_key:
            _reject(raw_id, REASON_UNKNOWN_AGENT)
            continue
        if key in seen:
            _reject(raw_id, REASON_DUPLICATE)
            continue
        seen.add(key)
        canonical = roster_by_key[key]
        repairs: List[str] = []
        if type(raw_id) is not type(canonical) or raw_id != canonical:
            repairs.append(NORM_ID_COERCED)

        scenario_text = str(element.get("scenario") or "").strip()
        scenario_key = _norm(scenario_text)
        if scenario_key and scenario_key == abstain_norm:
            if scenario_text != abstain_token:
                repairs.append(NORM_SCENARIO_NORMALIZED)
            for code in repairs:
                normalized[code] += 1
            abstained_ids.append(canonical)
            answered.add(key)
            continue
        if scenario_text in candidates:
            scenario = scenario_text
        else:
            matches = by_norm.get(scenario_key, []) if scenario_key else []
            if len(matches) != 1:
                _reject(raw_id, REASON_INVALID_SCENARIO)
                continue
            scenario = matches[0]
            repairs.append(NORM_SCENARIO_NORMALIZED)

        if element.get("magnitude") is None:
            _reject(raw_id, REASON_MISSING_MAGNITUDE)
            continue
        magnitude, mag_clamped = _unit_value(element["magnitude"])
        if magnitude is None:
            _reject(raw_id, REASON_NON_NUMERIC)
            continue
        if mag_clamped:
            repairs.append(NORM_CLAMPED)

        if element.get("confidence") is None:
            confidence = float(policy["default_confidence"])
            repairs.append(NORM_CONFIDENCE_DEFAULTED)
        else:
            confidence, conf_clamped = _unit_value(element["confidence"])
            if confidence is None:
                _reject(raw_id, REASON_NON_NUMERIC)
                continue
            if conf_clamped:
                repairs.append(NORM_CLAMPED)

        for code in repairs:
            normalized[code] += 1
        accepted.append({"agent_id": canonical, "scenario": scenario,
                         "magnitude": magnitude, "confidence": confidence})
        answered.add(key)

    missing_keys = [k for k in roster_by_key if k not in seen]
    if accepted:
        round_status = ROUND_STATUS_COMMITTED
    elif abstained_ids:
        round_status = ROUND_STATUS_ABSTAINED
    else:
        round_status = ROUND_STATUS_SILENT
    record = {
        "measured": True,
        "roster_size": len(roster_by_key),
        "answered": len(elements),
        "accepted": len(accepted),
        "abstained": len(abstained_ids),
        "rejected": sum(reasons.values()),
        "missing_from_reply": len(missing_keys),
        "fallback_slots": sum(1 for k in roster_by_key if k not in answered),
        "reasons": reasons,
        "normalized": normalized,
        "roster_agent_ids": list(roster_by_key),
        "abstained_agent_ids": [str(aid) for aid in abstained_ids],
        "missing_agent_ids": missing_keys,
        "rejected_samples": rejected_samples,
    }
    return {
        "accepted": accepted,
        "abstained_ids": abstained_ids,
        "round_status": round_status,
        "record": record,
    }


def summarize_validation(records: List[Dict[str, Any]], *,
                         unmeasured_rounds: int = 0) -> Dict[str, Any]:
    """Fold per-round validation records into the run-level summary.

    Only records with ``measured is True`` contribute; any other record (a
    round whose elicitation failed before a reply could be validated, marked
    ``{"measured": False}``) is added to ``unmeasured_rounds``, as are the
    caller's ``unmeasured_rounds`` (rounds that carried no record at all).

    ``slots`` is the sum of ``roster_size``; ``fallback_share`` is
    ``fallback_slots / slots`` rounded to 6 places, or ``None`` when no slot was
    measured. Output keys (and the nested reason/normalisation keys) are sorted.
    """
    measured = [r for r in (records or []) if isinstance(r, dict) and r.get("measured") is True]
    unmeasured = max(0, int(unmeasured_rounds or 0)) + (len(records or []) - len(measured))
    totals = dict.fromkeys(_COUNT_KEYS, 0)
    slots = 0
    reasons = _zero_counts(REASON_CODES)
    normalized = _zero_counts(NORMALIZATION_CODES)
    for rec in measured:
        slots += int(rec.get("roster_size", 0) or 0)
        for key in _COUNT_KEYS:
            totals[key] += int(rec.get(key, 0) or 0)
        for target, source in ((reasons, rec.get("reasons")),
                               (normalized, rec.get("normalized"))):
            for code, n in (source or {}).items():
                target[str(code)] = target.get(str(code), 0) + int(n or 0)
    summary = {
        "policy_version": DECISION_VALIDATION_POLICY_V1["version"],
        "measured_rounds": len(measured),
        "unmeasured_rounds": unmeasured,
        "slots": slots,
        "fallback_share": round(totals["fallback_slots"] / slots, 6) if slots else None,
        "reasons": dict(sorted(reasons.items())),
        "normalized": dict(sorted(normalized.items())),
        **totals,
    }
    return dict(sorted(summary.items()))
