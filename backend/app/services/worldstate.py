"""NEXTSTEPS P1-1: a modeled outcome WorldState the simulation converges ON.

The forecast outcome is the aggregate of consequential **decisions** (allocate,
commit, vote, switch supplier), not of posts. Today OASIS produces post-counts and
``final_stance_share`` is voice-share — the forecaster then has to make the unmodeled
leap from "who talked most" to a number. This module is the pure, testable core of
the fix: a base-rate-seeded distribution over the forecast scenarios, evolved each
round by **resource-weighted** agent commitments, with EWMA convergence tracking.

Kept pure / side-effect-free (no camel/oasis/LLM imports) so it is unit-testable
offline, exactly like ``agent_dynamics.py``. The OASIS round-loop wiring (eliciting
a per-agent ``{scenario, magnitude, confidence}`` decision and persisting
``decisions.jsonl`` / ``world_state_trajectory.json``) is gated behind
``SIM_DECISION_CHANNEL`` (default OFF) and lives in ``run_parallel_simulation.py``.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Foglamp WP1 (slice 1C, invariant I-16): typed round validity accounting.
#
# Failure, silence, abstention, infeasibility, no change, and convergence are
# DIFFERENT states. Before this containment, an elicitation failure produced an
# empty commitment list, the shares stayed put, the EWMA delta decayed toward
# zero, and the trajectory eventually reported ``converged=True`` — a dead
# decision channel was indistinguishable from a genuine equilibrium.
#
# Round statuses (recorded per ``step``):
#   committed  — at least one validated commitment was applied (valid evidence)
#   abstained  — elicitation succeeded and actors explicitly abstained (valid
#                evidence of "no move", per R2-CAL-13/SIM-9)
#   silent     — elicitation succeeded but returned no usable decisions
#                (ambiguous; NOT evidence of stability)
#   failed     — provider/infrastructure error during elicitation
#   missing    — no elicitation was attempted (e.g. empty roster/inputs)
#   infeasible — reserved for WP11 feasibility rejection (not yet emitted)
#
# Only VALID_ROUND_STATUSES update the convergence EWMA. Invalid rounds freeze
# the state (including the calendar entropy floor — an uninformative round
# contributes nothing, not a synthetic drift).
ROUND_STATUS_COMMITTED = "committed"
ROUND_STATUS_ABSTAINED = "abstained"
ROUND_STATUS_SILENT = "silent"
ROUND_STATUS_FAILED = "failed"
ROUND_STATUS_MISSING = "missing"
ROUND_STATUS_INFEASIBLE = "infeasible"

VALID_ROUND_STATUSES = frozenset({ROUND_STATUS_COMMITTED, ROUND_STATUS_ABSTAINED})
KNOWN_ROUND_STATUSES = frozenset({
    ROUND_STATUS_COMMITTED, ROUND_STATUS_ABSTAINED, ROUND_STATUS_SILENT,
    ROUND_STATUS_FAILED, ROUND_STATUS_MISSING, ROUND_STATUS_INFEASIBLE,
})

# Frozen containment thresholds (EXECPLAN_FOGLAMP §9: "the exact thresholds are
# frozen in a fixture policy before implementation; missing data yields
# ``inconclusive``, not convergence").
CONVERGENCE_POLICY_V1: Dict[str, Any] = {
    "version": "foglamp-convergence-policy/v1",
    # settled requires at least this many valid (committed/abstained) transitions
    "min_valid_transitions": 3,
    # and at least this fraction of accounted rounds must be valid
    "min_valid_coverage": 0.5,
    # any provider/infrastructure failure makes convergence at best inconclusive
    "max_failed_rounds": 0,
}


def _norm_shares(shares: Dict[str, float]) -> Dict[str, float]:
    """Clamp negatives to 0 and renormalize to sum 1; empty/degenerate → uniform."""
    if not shares:
        return {}
    total = sum(max(0.0, float(v)) for v in shares.values())
    if total <= 0:
        n = len(shares)
        return {k: round(1.0 / n, 6) for k in shares}
    return {k: round(max(0.0, float(v)) / total, 6) for k, v in shares.items()}


def commitments_from_decisions(
    decisions: List[Dict[str, Any]],
    weight_by_agent: Optional[Dict[Any, float]] = None,
) -> List[Dict[str, Any]]:
    """Turn raw per-agent decisions into resource-weighted commitments for ``step``.

    Each decision: ``{agent_id, scenario, magnitude, confidence}``. The commitment
    weight = (outcome power on the result, default 1.0) × confidence. Pure.

    R2-SIM-2: the weight that moves the modeled OUTCOME is the agent's *outcome power*
    (structural/resource leverage over the result), NOT its voice/activation influence.
    Resolution order per decision: explicit ``outcome_power`` on the decision →
    ``weight_by_agent[agent_id]`` (a power map the caller may still pass) → 1.0. An empty
    / abstaining ``scenario`` contributes nothing (R2-CAL-13/SIM-9 abstention).

    SIM-2: a decision whose magnitude, confidence or power is not finite (NaN/±inf)
    is skipped — clamping would turn NaN into a full-weight vote and inf into a NaN
    target that zeroes its scenario.
    """
    out: List[Dict[str, Any]] = []
    wmap = weight_by_agent or {}
    for d in decisions or []:
        if not isinstance(d, dict):
            continue
        sc = str(d.get("scenario") or "").strip()
        if not sc:
            continue
        try:
            mag_raw = float(d.get("magnitude", 1.0) or 0.0)
            conf_raw = float(d.get("confidence", 1.0) or 0.0)
        except (TypeError, ValueError):
            continue
        # R2-SIM-2: prefer per-decision outcome_power; fall back to the supplied map.
        power = d.get("outcome_power")
        if power is None:
            power = wmap.get(d.get("agent_id"), 1.0)
        try:
            power_raw = float(power)
        except (TypeError, ValueError):
            power_raw = 1.0
        if not (math.isfinite(mag_raw) and math.isfinite(conf_raw)
                and math.isfinite(power_raw)):
            continue  # SIM-2: non-finite values never reach WorldState
        mag = max(0.0, mag_raw)
        conf = max(0.0, min(1.0, conf_raw))
        base_w = max(0.0, power_raw)
        out.append({"scenario": sc, "magnitude": mag, "weight": base_w * conf})
    return out


class WorldState:
    """A distribution over scenario names ∈ [0,1] summing to 1, evolved by commitments.

    ``inertia`` ∈ [0,1] is how much of the prior persists each round (high = slow,
    stable; low = fast, jumpy). Seeded from ``base_rates`` (the outside view); absent
    base rates → uniform.
    """

    def __init__(self, scenarios: List[str], base_rates: Optional[Dict[str, float]] = None,
                 inertia: float = 0.7):
        self.scenarios = [str(s) for s in (scenarios or []) if str(s).strip()]
        self.inertia = max(0.0, min(1.0, float(inertia)))
        seed: Dict[str, float] = {}
        for s in self.scenarios:
            try:
                seed[s] = float((base_rates or {}).get(s, 0.0) or 0.0)
            except (TypeError, ValueError):
                seed[s] = 0.0
        # R2-CAL-13/SIM-9: distinguish a genuinely seeded prior from a fabricated
        # uniform one so a forecaster can flag "uniform_prior" instead of silently
        # treating 50/50 as evidence.
        self.uniform_prior = sum(seed.values()) <= 0
        if self.uniform_prior:  # no usable base rates → uniform prior
            seed = dict.fromkeys(self.scenarios, 1.0)
        self.shares = _norm_shares(seed)
        # 日历熵地板（WORLDSTATE_ENTROPY_MIX）：记住种子先验（外部视角基率），
        # step(entropy_mix_days=...) 时向它回混——回混目标是先验而非均匀分布，
        # 偏斜先验（如 90/10）不会被拉向 50/50。
        self._seed_shares = dict(self.shares)
        self.history: List[Dict[str, float]] = [dict(self.shares)]
        self._last_delta = 1.0
        self._ewma_delta = 1.0
        # P1-4: round at which the trajectory settled (set by the orchestration loop).
        self.converged_at: Optional[int] = None
        # Foglamp WP1 (1C/I-16): per-round validity statuses, in step order.
        self.round_statuses: List[str] = []

    def step(self, commitments: List[Dict[str, Any]],
             inertia: Optional[float] = None,
             entropy_mix_days: Optional[int] = None,
             round_status: Optional[str] = None) -> Dict[str, float]:
        """Evolve one round: aggregate resource-weighted commitments into a target
        distribution, blend with the prior by ``inertia``. No commitments → unchanged.

        R2-SIM-12: ``inertia`` may be overridden per round (e.g. scaled by the calendar
        gap between rounds) — ``None`` keeps the instance default so existing callers
        and the no-date path are byte-identical.

        日历熵地板（WORLDSTATE_ENTROPY_MIX，calendar-only）：``entropy_mix_days`` 为本轮
        覆盖的日历天数时，在常规 blend/renormalize 之后再向**种子先验**回混
        ``lam = min(0.05, 0.0005×天数)``（day→0.0005，month→≈0.0152，half_year→0.05 封顶），
        防止长推演把分布锁死在极端值。``None``（所有旧调用方）→ 逐字节不变。

        Foglamp WP1 (1C/I-16): ``round_status`` records why this round looks the
        way it does. ``None`` infers ``committed`` when a positive-weight
        commitment exists, else ``silent`` (conservative: an unexplained empty
        round is NOT evidence of stability). Rounds whose status is not in
        ``VALID_ROUND_STATUSES`` freeze the state and do NOT update the
        convergence EWMA, so a failed/absent decision channel can no longer
        decay into apparent convergence.
        """
        if not self.scenarios:
            return {}
        status = round_status
        if status is None:
            has_signal = any(
                isinstance(c, dict)
                and str(c.get("scenario") or "") in set(self.scenarios)
                for c in (commitments or [])
            )
            status = ROUND_STATUS_COMMITTED if has_signal else ROUND_STATUS_SILENT
        elif status not in KNOWN_ROUND_STATUSES:
            status = ROUND_STATUS_SILENT
        if status not in VALID_ROUND_STATUSES:
            # Invalid/uninformative round: freeze state, record the status, and
            # leave the convergence EWMA untouched (I-16: no update, no decay).
            self.round_statuses.append(status)
            self.history.append(dict(self.shares))
            return self.shares
        self.round_statuses.append(status)
        eff_inertia = self.inertia if inertia is None else max(0.0, min(1.0, float(inertia)))
        votes: Dict[str, float] = dict.fromkeys(self.scenarios, 0.0)
        for c in commitments or []:
            if not isinstance(c, dict):
                continue
            sc = str(c.get("scenario") or "")
            if sc not in votes:
                continue
            try:
                vote = max(0.0, float(c.get("magnitude", 1.0) or 0.0)) * \
                    max(0.0, float(c.get("weight", 1.0) or 0.0))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(vote):
                continue  # SIM-2: an inf/NaN vote would poison the target distribution
            votes[sc] += vote
        if sum(votes.values()) > 0:
            target = _norm_shares(votes)
            blended = {s: eff_inertia * self.shares[s] + (1.0 - eff_inertia) * target[s]
                       for s in self.scenarios}
            new = _norm_shares(blended)
        else:
            new = dict(self.shares)
        if entropy_mix_days is not None:
            # 熵地板：向种子先验（非均匀）回混后再归一化；lam 钳在 [0, 0.05]。
            lam = max(0.0, min(0.05, 0.0005 * float(entropy_mix_days)))
            new = _norm_shares({k: (1.0 - lam) * v + lam * self._seed_shares.get(k, 0.0)
                                for k, v in new.items()})
        delta = sum(abs(new[s] - self.shares[s]) for s in self.scenarios)
        self._last_delta = round(delta, 6)
        self._ewma_delta = round(0.5 * self._ewma_delta + 0.5 * delta, 6)
        self.shares = new
        self.history.append(dict(self.shares))
        return self.shares

    def round_accounting(self) -> Dict[str, Any]:
        """Foglamp WP1 (1C/I-16): typed per-round accounting for the trajectory.

        Returns counts by status plus the derived validity measures the
        convergence policy consumes. Pure; safe on a fresh instance.
        """
        counts: Dict[str, int] = {}
        for s in self.round_statuses:
            counts[s] = counts.get(s, 0) + 1
        total = len(self.round_statuses)
        valid = sum(counts.get(s, 0) for s in VALID_ROUND_STATUSES)
        return {
            "policy_version": CONVERGENCE_POLICY_V1["version"],
            "counts": counts,
            "rounds_accounted": total,
            "valid_transitions": valid,
            "valid_coverage": round(valid / total, 6) if total else 0.0,
            "failed_rounds": counts.get(ROUND_STATUS_FAILED, 0),
            "missing_rounds": counts.get(ROUND_STATUS_MISSING, 0),
        }

    def convergence_state(self, eps: float = 0.02) -> str:
        """Foglamp WP1 (1C/I-16): ``converged`` | ``inconclusive`` | ``active``.

        ``converged`` requires the settled EWMA **and** the frozen
        ``CONVERGENCE_POLICY_V1`` guards: enough valid transitions, enough valid
        coverage, and zero provider/infrastructure failures. A settled EWMA that
        fails a guard is ``inconclusive`` — stability of a starved channel is
        not evidence of equilibrium. Missing data never yields convergence.
        """
        settled = self._ewma_delta < float(eps)
        if not settled:
            return "active"
        acct = self.round_accounting()
        policy = CONVERGENCE_POLICY_V1
        if (acct["valid_transitions"] < int(policy["min_valid_transitions"])
                or acct["valid_coverage"] < float(policy["min_valid_coverage"])
                or acct["failed_rounds"] > int(policy["max_failed_rounds"])):
            return "inconclusive"
        return "converged"

    def converged(self, eps: float = 0.02) -> bool:
        """True once the EWMA of per-round L1 change drops below ``eps`` (settled)
        AND the ``CONVERGENCE_POLICY_V1`` validity guards pass (Foglamp 1C/I-16).
        A failed or silent decision channel therefore can no longer report
        convergence; use :meth:`convergence_state` to distinguish
        ``inconclusive`` from ``active``."""
        return self.convergence_state(eps) == "converged"

    def outcome(self) -> Dict[str, Any]:
        """The modeled outcome: scenario shares + leader + convergence diagnostics.
        This is what a forecaster reads INSTEAD of voice-share ``final_stance_share``.

        Foglamp WP1 (1D/I-11): the block is labeled ``elicited_model_projection``
        — it is an elicited model projection over scenario names, never observed
        real-world evidence, and must be presented as such downstream.
        """
        ranked = sorted(self.shares.items(), key=lambda kv: -kv[1])
        return {
            "shares": dict(self.shares),
            "leader": ranked[0][0] if ranked else None,
            "leader_share": round(ranked[0][1], 4) if ranked else 0.0,
            "rounds": max(0, len(self.history) - 1),
            "ewma_delta": self._ewma_delta,
            "converged": self.converged(),
            "convergence_state": self.convergence_state(),  # Foglamp 1C/I-16
            "converged_at": self.converged_at,   # P1-4 (set by the loop; None until settled)
            "uniform_prior": self.uniform_prior,  # R2-CAL-13/SIM-9
            "round_accounting": self.round_accounting(),     # Foglamp 1C/I-16
            "epistemic_status": "elicited_model_projection",  # Foglamp 1D/I-11
        }
