"""SIM-4 (C30): zero-LLM prior-echo diagnostic for the decision channel.

The decision channel starts from a seed WorldState (the research's scenario
probabilities, the trajectory row with ``round == 0``) and moves it with
per-round agent commitments. A run whose final shares are the seed again, or
whose commitments all pile onto the seed's leading scenario, has added nothing
beyond the research prior: it is an echo, not independent corroboration.

:func:`prior_echo_diagnostics` measures that from ``world_state_trajectory.json``
alone (both producers, ``decision_channel.run_decision_channel`` and the in-band
calendar evolver in ``run_parallel_simulation.py``, write the seed as row 0).
The verdict is diagnostic only: the channel is ``diagnostic_only``, so nothing
here moves a probability, and ``divergent`` means only "not trivially hollow",
never "informative".

Pure and stdlib only (no Config, camel or oasis import), deterministic and
never raising.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional

# Frozen: changing a threshold means bumping the version (CONVERGENCE_POLICY_V1 pattern).
SIM_CONTROL_POLICY_V1: Mapping[str, Any] = {
    "version": "drf-sim-control/v1",
    "echo_tv": 0.05,              # total-variation distance below which final == prior
    "leader_commit_rate": 0.9,    # share of commitment mass on the prior leader = herd
    "min_valid_rounds": 3,        # fewer committed/abstained rounds → inconclusive
}

VERDICT_UNAVAILABLE = "unavailable"
VERDICT_INCONCLUSIVE = "inconclusive"
VERDICT_PRIOR_ECHO = "prior_echo"
VERDICT_PRIOR_LEADER_HERD = "prior_leader_herd"
VERDICT_DIVERGENT = "divergent"

_VALID_ROUND_STATUSES = frozenset({"committed", "abstained"})
_TIE_EPS = 1e-9


def _number(value: Any) -> Optional[float]:
    """``value`` as a finite float (never a bool), else None."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))


def _shares(raw: Any) -> Optional[Dict[str, float]]:
    """A shares mapping as {scenario: finite share >= 0}; None when it is not a mapping."""
    if not isinstance(raw, Mapping):
        return None
    out: Dict[str, float] = {}
    for name, value in raw.items():
        number = _number(value)
        if number is not None and number >= 0:
            out[str(name)] = number
    return out


def _result(policy: Mapping[str, Any], verdict: str, reasons: List[str], **fields: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "policy_version": policy.get("version"),
        "verdict": verdict,
        "reasons": reasons,
        "tv_to_prior": None,
        "prior_leader": None,
        "prior_leader_commit_rate": None,
        "valid_rounds": None,
        "uniform_prior": None,
    }
    out.update(fields)
    return out


def _valid_rounds(traj: Mapping[str, Any], rows: List[Mapping[str, Any]]) -> int:
    """Rounds >= 1 whose round_status is committed/abstained; legacy rows without any
    round_status fall back to the number of distinct decision rounds."""
    later = [row for row in rows if (_number(row.get("round")) or 0) >= 1]
    if any("round_status" in row for row in later):
        return sum(1 for row in later
                   if str(row.get("round_status") or "").strip().lower() in _VALID_ROUND_STATUSES)
    rounds = set()
    for decision in traj.get("decisions") or []:
        if isinstance(decision, Mapping):
            rnd = _number(decision.get("round"))
            if rnd is not None:
                rounds.add(rnd)
    return len(rounds)


def _leader_commit_rate(decisions: Any, leader: Optional[str]) -> Optional[float]:
    """Commitment mass on ``leader`` / total mass; mass = clamp01(magnitude) *
    max(0, outcome_power or 1.0) * clamp01(confidence). Non-numeric or non-finite
    values skip the decision. None without a leader or without mass."""
    if leader is None:
        return None
    total = on_leader = 0.0
    for decision in decisions or []:
        if not isinstance(decision, Mapping):
            continue
        magnitude = _number(decision.get("magnitude"))
        confidence = _number(decision.get("confidence"))
        power = _number(decision.get("outcome_power")) if "outcome_power" in decision else 1.0
        if magnitude is None or confidence is None or power is None:
            continue
        mass = _clamp01(magnitude) * max(0.0, power) * _clamp01(confidence)
        total += mass
        if str(decision.get("scenario") or "") == leader:
            on_leader += mass
    if total <= 0:
        return None
    return round(on_leader / total, 6)


def prior_echo_diagnostics(traj: Dict[str, Any],
                           policy: Mapping[str, Any] = SIM_CONTROL_POLICY_V1) -> Dict[str, Any]:
    """The prior-echo verdict of one decision-channel trajectory (see the module docstring).

    Returns ``{policy_version, verdict, reasons, tv_to_prior, prior_leader,
    prior_leader_commit_rate, valid_rounds, uniform_prior}``. Verdicts, first match:
    ``unavailable`` (no row-0 prior, no final shares or fewer than 2 scenarios);
    ``inconclusive`` (a non-valid top-level ``validity``: reason ``trajectory_not_valid``;
    fewer than ``min_valid_rounds`` valid rounds: ``too_few_valid_rounds``);
    ``prior_echo`` (total-variation distance final vs prior < ``echo_tv``);
    ``prior_leader_herd`` (commitment mass on the prior's unique leader >=
    ``leader_commit_rate``); else ``divergent`` — not trivially hollow, which is NOT
    evidence that the run is informative. A uniform or tied prior has no leader, so
    it is never a herd. Never raises: an internal error gives ``unavailable`` with
    reason ``diagnostics_error:<ExceptionClass>``.
    """
    try:
        return _diagnose(traj, policy)
    except Exception as exc:  # noqa: BLE001 — a diagnostic never breaks the run
        return _result(policy, VERDICT_UNAVAILABLE, [f"diagnostics_error:{type(exc).__name__}"])


def _diagnose(traj: Any, policy: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(traj, Mapping):
        return _result(policy, VERDICT_UNAVAILABLE, ["no_trajectory"])
    rows = [row for row in (traj.get("trajectory") or []) if isinstance(row, Mapping)]
    row0 = next((row for row in rows if _number(row.get("round")) == 0), None)
    outcome = traj.get("outcome") if isinstance(traj.get("outcome"), Mapping) else {}
    prior = _shares(row0.get("shares")) if row0 is not None else None
    final = _shares(outcome.get("shares"))
    if row0 is None or prior is None:
        return _result(policy, VERDICT_UNAVAILABLE, ["no_prior"])
    if final is None:
        return _result(policy, VERDICT_UNAVAILABLE, ["no_final_shares"])
    scenarios = sorted(set(prior) | set(final))
    if len(scenarios) < 2:
        return _result(policy, VERDICT_UNAVAILABLE, ["fewer_than_two_scenarios"])

    uniform_prior = bool(row0.get("uniform_prior") or outcome.get("uniform_prior"))
    leader: Optional[str] = None
    if not uniform_prior:
        ranked = sorted(scenarios, key=lambda s: -prior.get(s, 0.0))
        if prior.get(ranked[0], 0.0) - prior.get(ranked[1], 0.0) > _TIE_EPS:
            leader = ranked[0]
    tv = round(0.5 * sum(abs(final.get(s, 0.0) - prior.get(s, 0.0)) for s in scenarios), 6)
    valid_rounds = _valid_rounds(traj, rows)
    rate = _leader_commit_rate(traj.get("decisions"), leader)
    fields = {"tv_to_prior": tv, "prior_leader": leader, "prior_leader_commit_rate": rate,
              "valid_rounds": valid_rounds, "uniform_prior": uniform_prior}

    validity = traj.get("validity")
    if validity is not None and str(validity).strip().lower() != "valid":
        return _result(policy, VERDICT_INCONCLUSIVE, ["trajectory_not_valid"], **fields)
    if valid_rounds < int(policy["min_valid_rounds"]):
        return _result(policy, VERDICT_INCONCLUSIVE, ["too_few_valid_rounds"], **fields)
    if tv < float(policy["echo_tv"]):
        return _result(policy, VERDICT_PRIOR_ECHO, ["final_equals_prior"], **fields)
    if rate is not None and rate >= float(policy["leader_commit_rate"]):
        return _result(policy, VERDICT_PRIOR_LEADER_HERD, ["commitments_on_prior_leader"], **fields)
    return _result(policy, VERDICT_DIVERGENT, [], **fields)
