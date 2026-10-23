"""World paths: a distribution of futures from one reflexive simulation (design §2.12).

A run used to produce one world path: one deterministic update, one arbiter call and one roll
of the pending effects per committed round.  With ``SIM_WORLD_PATHS=K`` the coordinator runs K
seeded variants of every round's world update, all sharing the round's actor decisions (no extra
decision calls):

* **path 0** is the path the agents live in.  It is computed exactly as before (same RNG stream,
  same arbiter temperature) and is the only path ever rendered into a brief, so K>1 changes no
  agent-facing text (herding guard: agents never see scenario shares, let alone their spread).
* **paths 1..K−1** are counterfactual siblings: their own world copy, their own seeded RNG (pending
  effects and exogenous shocks roll differently) and their own arbiter call, sampled at a bounded
  temperature.  They capture world-side uncertainty conditional on the actors' realised decisions;
  the actors never react to a sibling's divergent world.

Cost: at most K arbiter calls per round (one per path; none when the arbiter is off) and no extra
decision calls; K is capped at ``MAX_WORLD_PATHS``.

The explicit ``world_model.settings.branch_policy='adaptive-v1'`` experiment instead
elicits sibling decisions from their own observations, fixed personas, prior moves
and public discourse. It requires a pinned attempt budget, actor/round bounds,
path count and seed. Stopped branches retain their last state. These are diagnostic
model branches, not calibrated outcome probabilities; default shared-v1 is unchanged.

This module is pure: per-path RNGs, the settings clamps and the aggregation of shares, shocks and
numeric facts across paths.  The coordinator (``run_parallel_simulation._ReflexiveWorldCoordinator``)
owns the worlds, the arbiter calls and the artifacts.
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

WORLD_PATHS_VERSION = "world-paths/v1"
WORLD_PATHS_FILE = "world_paths.json"
MAX_WORLD_PATHS = 8
BASE_ARBITER_TEMPERATURE = 0.3        # path 0 (world_update.run_arbiter's default)
DEFAULT_PATH_TEMPERATURE = 0.7        # paths 1..K-1 unless SIM_WORLD_PATH_TEMPERATURE says otherwise
MAX_PATH_TEMPERATURE = 1.0
MAX_SPREAD_VARIABLES = 12
_QUANTILES = (("p10", 0.1), ("p50", 0.5), ("p90", 0.9))


def resolve_branch_policy(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the explicit experiment envelope; never consult the environment.

    The budget counts structured decision attempts, including failed calls. Provider
    retries are not priced here, so this is not a monetary spending guarantee.
    """
    policy = settings.get("branch_policy", "shared-v1")
    if policy == "shared-v1":
        return {"branch_policy": policy}
    if policy != "adaptive-v1":
        raise ValueError("unsupported branch_policy")
    out = {"branch_policy": policy}
    for key, low, high in (("path_count", 2, MAX_WORLD_PATHS),
                           ("branch_decision_budget", 1, 4096),
                           ("branch_max_actors", 1, 64),
                           ("branch_max_rounds", 1, 256)):
        value = settings.get(key)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"adaptive-v1 requires {key} integer in [{low}, {high}]")
        out[key] = value
    seed = settings.get("path_seed")
    if type(seed) is not int:
        raise ValueError("adaptive-v1 requires an integer path_seed")
    out["path_seed"] = seed
    temperature = settings.get("path_temperature", DEFAULT_PATH_TEMPERATURE)
    if type(temperature) not in (int, float) or not math.isfinite(temperature) or not 0 <= temperature <= 1:
        raise ValueError("adaptive-v1 path_temperature must be finite and in [0, 1]")
    out["path_temperature"] = float(temperature)
    return out


def resolve_path_count(raw: Any) -> Tuple[int, str]:
    """``(K, note)``: the number of world paths in [1, MAX_WORLD_PATHS]; ``note`` says why a value was
    not taken as given ("" when it was)."""
    text = str(raw if raw is not None else "").strip()
    if not text:
        return 1, ""
    try:
        k = int(float(text))
    except (TypeError, ValueError):
        return 1, f"SIM_WORLD_PATHS={text!r} is not a number; running one path"
    if k < 1:
        return 1, f"SIM_WORLD_PATHS={text} is below 1; running one path"
    if k > MAX_WORLD_PATHS:
        return MAX_WORLD_PATHS, f"SIM_WORLD_PATHS={text} exceeds the cap; running {MAX_WORLD_PATHS} paths"
    return k, ""


def resolve_path_temperature(raw: Any) -> float:
    """Arbiter temperature of paths 1..K-1, clamped to [0, MAX_PATH_TEMPERATURE]."""
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_PATH_TEMPERATURE
    if not math.isfinite(value):
        return DEFAULT_PATH_TEMPERATURE
    return max(0.0, min(MAX_PATH_TEMPERATURE, value))


def path_rng(seed_value: int, path: int, round_num: int) -> random.Random:
    """The RNG of one path's update in round ``round_num`` (1-based).  Path 0 keeps the single-path
    stream (``SIM_SEED * 1000003 + round``), so a one-path run draws exactly as before; the siblings
    get independent streams derived from (seed, path, round) — reproducible across processes
    (a ``str`` seed is hashed with SHA-512, not with the per-process ``hash``)."""
    if int(path) == 0:
        return random.Random(int(seed_value) * 1000003 + int(round_num))
    return random.Random(f"world-path/{int(seed_value)}/{int(path)}/{int(round_num)}")


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile of an ascending, non-empty sequence."""
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = (len(sorted_values) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_values) - 1)
    return float(sorted_values[lo]) + (float(sorted_values[hi]) - float(sorted_values[lo])) * (pos - lo)


def _stats(values: Sequence[float]) -> Dict[str, float]:
    ordered = sorted(float(v) for v in values)
    mean = sum(ordered) / len(ordered)
    sd = math.sqrt(sum((v - mean) ** 2 for v in ordered) / len(ordered))
    out = {"mean": round(mean, 6), "sd": round(sd, 6), "min": round(ordered[0], 6)}
    for key, q in _QUANTILES:
        out[key] = round(_quantile(ordered, q), 6)
    out["max"] = round(ordered[-1], 6)
    return out


def share_distribution(per_path_shares: Sequence[Dict[str, Any]], scenarios: Sequence[str]) -> Dict[str, Any]:
    """Each scenario's share across paths (mean, population sd, min, p10, p50, p90, max) and how many
    paths each scenario leads (ties go to the first scenario in ``scenarios`` order, as in
    ``WorldState.outcome``'s stable sort)."""
    rows = [r for r in per_path_shares if isinstance(r, dict)]
    names = [str(s) for s in scenarios if str(s).strip()]
    out: Dict[str, Any] = {"k": len(rows), "shares": {}, "leaders": {}}
    if not rows or not names:
        return out
    for s in names:
        out["shares"][s] = _stats([_share(r, s) for r in rows])
    leaders: Dict[str, int] = {}
    for r in rows:
        leader = max(names, key=lambda s: (_share(r, s), -names.index(s)))
        leaders[leader] = leaders.get(leader, 0) + 1
    out["leaders"] = {s: leaders[s] for s in names if s in leaders}
    return out


def _share(row: Dict[str, Any], scenario: str) -> float:
    try:
        value = float(row.get(scenario, 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) else 0.0


def shock_frequency(worlds: Sequence[Any]) -> Dict[str, Dict[str, Any]]:
    """For each seeded shock: in how many paths it fired, and the round it first fired in each."""
    out: Dict[str, Dict[str, Any]] = {}
    for path, world in enumerate(worlds):
        for shock in getattr(world, "shocks", None) or []:
            row = out.setdefault(shock.id, {"event": shock.event, "base_rate": shock.base_rate_text(),
                                            "paths_fired": 0, "first_rounds": {}})
            if shock.fired_rounds:
                row["paths_fired"] += 1
                row["first_rounds"][str(path)] = int(min(shock.fired_rounds))
    return out


def variable_spread(worlds: Sequence[Any], limit: int = MAX_SPREAD_VARIABLES) -> Dict[str, Dict[str, Any]]:
    """Numeric facts tracked in every path: min / p50 / max across paths, widest relative spread first
    (facts that ended identical in every path are left out)."""
    if not worlds:
        return {}
    common = None
    for world in worlds:
        ids = {vid for vid, v in (getattr(world, "variables", None) or {}).items()
               if v.kind == "numeric" and isinstance(v.value, (int, float)) and not isinstance(v.value, bool)}
        common = ids if common is None else common & ids
    rows: List[Tuple[float, str, Dict[str, Any]]] = []
    for vid in sorted(common or ()):
        values = sorted(float(w.variables[vid].value) for w in worlds)
        if values[-1] - values[0] <= 1e-12:
            continue
        ref = worlds[0].variables[vid]
        scale = max(abs(values[0]), abs(values[-1])) or 1.0
        rows.append(((values[-1] - values[0]) / scale, vid, {
            "name": ref.name, "unit": ref.unit, "min": round(values[0], 6),
            "p50": round(_quantile(values, 0.5), 6), "max": round(values[-1], 6)}))
    rows.sort(key=lambda r: (-r[0], r[1]))
    return {vid: row for _, vid, row in rows[:limit]}


def paths_summary(*, k: int, temperature: float, arbiter_enabled: bool, rounds: int,
                  per_path_shares: Sequence[Dict[str, Any]], scenarios: Sequence[str], worlds: Sequence[Any],
                  arbiter_failed: Sequence[int], restarted_at_round: Optional[int] = None,
                  branch_policy: str = "shared-v1", decision_budget: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The ``paths`` block of the world summary (``world_state.json`` summary, trajectory
    ``world_model``, run summary)."""
    dist = share_distribution(per_path_shares, scenarios)
    per_path = []
    for i, shares in enumerate(per_path_shares):
        names = [str(s) for s in scenarios]
        leader = max(names, key=lambda s: (_share(shares, s), -names.index(s))) if names and shares else None
        world = worlds[i] if i < len(worlds) else None
        per_path.append({"path": i, "shares": {s: round(_share(shares, s), 6) for s in names},
                         "leader": leader,
                         "arbiter_failed_rounds": int(arbiter_failed[i]) if i < len(arbiter_failed) else 0,
                         "shocks_fired": sorted(s.id for s in (getattr(world, "shocks", None) or [])
                                                if s.fired_rounds)})
    out = {
        "schema_version": WORLD_PATHS_VERSION,
        "k": int(k),
        "rounds": int(rounds),
        "arbiter_temperature": {"path_0": BASE_ARBITER_TEMPERATURE, "siblings": round(float(temperature), 4)},
        "arbiter_calls_per_round_max": int(k) if arbiter_enabled else 0,
        "shares": dist["shares"],
        "leaders": dist["leaders"],
        "per_path": per_path,
        "shocks": shock_frequency(worlds),
        "variables": variable_spread(worlds),
        "basis": ("path 0 is the path the actors lived; paths 1..K-1 share its decisions and differ in "
                  "pending-effect and shock rolls and in a sampled arbiter (world-side uncertainty only)"),
    }
    if restarted_at_round:
        out["restarted_at_round"] = int(restarted_at_round)
    out["branch_policy"] = branch_policy
    if branch_policy == "adaptive-v1":
        out["basis"] = ("Bounded experimental branches with branch-local actor decisions, observations, "
                        "private memory and public statements; world rolls and sampled model responses "
                        "are diagnostic uncertainty, not calibrated event probabilities. Stopped branches "
                        "retain their last state; inspect per-branch completed rounds and stop reasons.")
        out["decision_budget"] = dict(decision_budget or {})
    return out
