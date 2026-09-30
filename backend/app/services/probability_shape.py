"""REPORT-11: deterministic probability-shape telemetry of one forecast.

DRF pushes binary sets hard away from 0.5 (the binary scorecard, the contrarian
framing rule, the low-probability top-up), while the always-on red-team critique
may flatten the scenario spine, and the uncritiqued spine was never persisted.
Neither effect was measured. :func:`probability_shape` measures both, from the
published numbers alone:

- scenarios: ``n``, ``max_probability`` (the same peak the publish gate records as
  ``quality.max_probability``), ``normalized_entropy`` (H / ln n, None when n < 2)
  and ``tv_from_uniform`` (0.5 * sum |p - 1/n|); with the pre-critique snapshot
  (``quality.pre_critique_scenarios``, see :func:`stamp_pre_critique`) also the same
  stats before the critique and the post - pre ``critique_delta``;
- binaries: the 0.40-0.60 ``midband_share`` (the band ``_binary_quality`` gates on),
  ``near_half_share`` (0.45-0.55), ``extreme_share`` (<= 0.05 or >= 0.95),
  ``mean_abs_from_half``, ``stdev``, a ten-bin ``decile_hist`` and the number of
  recorded probability ``moves`` toward or away from 0.5 (market restatements and
  scenario-partition reconciliation).

Observability only: no gate reads the result, it never raises, and it ignores any
probability that is not a finite number in [0, 1] (bool, None, NaN, strings).
Pure: stdlib only, no I/O.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

SHAPE_VERSION = "prob-shape/v1"
# The binary scorecard's hedging band (forecast_extractor._binary_quality), inclusive.
MIDBAND = (0.40, 0.60)
NEAR_HALF = (0.45, 0.55)
EXTREME_LOW = 0.05
EXTREME_HIGH = 0.95
DECILE_BINS = 10
_DIGITS = 4
# Absorbs float noise: 0.3 * 10 is 3.0000000000000004, and a move of 1e-12 is no move.
_EPS = 1e-9
_SCENARIO_STATS = ("max_probability", "normalized_entropy", "tv_from_uniform")
_DELTA_STATS = ("max_probability", "normalized_entropy")


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, _DIGITS)


def _unit_probability(value: Any) -> Optional[float]:
    """A finite probability in [0, 1], else None (bool, None, NaN, str and out-of-range)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    p = float(value)
    if not math.isfinite(p) or p < 0.0 or p > 1.0:
        return None
    return p


def _probabilities(rows: Any) -> List[float]:
    """Readable probabilities of a list of rows (dicts with ``probability``, or bare numbers)."""
    if not isinstance(rows, (list, tuple)):
        return []
    out: List[float] = []
    for row in rows:
        p = _unit_probability(row.get("probability") if isinstance(row, dict) else row)
        if p is not None:
            out.append(p)
    return out


def _scenario_stats(probs: List[float]) -> Dict[str, Any]:
    """n plus the three scenario stats. Entropy and TV use the probabilities renormalised to
    sum 1 (a valid partition already does, up to rounding); the peak is the raw value."""
    n = len(probs)
    stats: Dict[str, Any] = {"n": n, **dict.fromkeys(_SCENARIO_STATS)}
    if not n:
        return stats
    stats["max_probability"] = _round(max(probs))
    total = sum(probs)
    if total <= 0.0:
        return stats
    shares = [p / total for p in probs]
    if n >= 2:
        entropy = -sum(s * math.log(s) for s in shares if s > 0.0)
        stats["normalized_entropy"] = _round(entropy / math.log(n))
    stats["tv_from_uniform"] = _round(0.5 * sum(abs(s - 1.0 / n) for s in shares))
    return stats


def _delta(post: Optional[float], pre: Optional[float]) -> Optional[float]:
    return None if post is None or pre is None else _round(post - pre)


def _scenario_block(scenarios: Any, pre_critique_scenarios: Any) -> Dict[str, Any]:
    block = _scenario_stats(_probabilities(scenarios))
    if pre_critique_scenarios is not None:
        pre = _scenario_stats(_probabilities(pre_critique_scenarios))
        block["pre_critique"] = pre
        block["critique_delta"] = {key: _delta(block[key], pre[key]) for key in _DELTA_STATS}
    return block


def _count_move(before: Any, after: Any, moves: Dict[str, int]) -> None:
    prior, revised = _unit_probability(before), _unit_probability(after)
    if prior is None or revised is None:
        return
    distance_before, distance_after = abs(prior - 0.5), abs(revised - 0.5)
    if distance_after < distance_before - _EPS:
        moves["toward_half"] += 1
    elif distance_after > distance_before + _EPS:
        moves["away_from_half"] += 1


def _binary_moves(rows: Any) -> Dict[str, int]:
    """Recorded probability moves: a market restatement (``market_influence`` prior ->
    revised, unless reconciliation reverted it: ``probability_restored``) and a
    scenario-partition reconciliation (``pre_reconciliation_probability`` -> probability).
    A move that keeps the distance to 0.5 (e.g. 0.3 -> 0.7) counts as neither."""
    moves = {"toward_half": 0, "away_from_half": 0}
    for row in rows if isinstance(rows, (list, tuple)) else []:
        if not isinstance(row, dict):
            continue
        influence = row.get("market_influence")
        if isinstance(influence, dict) and influence.get("probability_restored") is not True:
            _count_move(influence.get("prior_probability"),
                        influence.get("revised_probability"), moves)
        if "pre_reconciliation_probability" in row:
            _count_move(row.get("pre_reconciliation_probability"), row.get("probability"), moves)
    return moves


def _binary_block(binaries: Any) -> Dict[str, Any]:
    probs = _probabilities(binaries)
    n = len(probs)
    block: Dict[str, Any] = {
        "n": n, "midband_share": None, "near_half_share": None, "extreme_share": None,
        "mean_abs_from_half": None, "stdev": None, "decile_hist": None,
        "moves": _binary_moves(binaries),
    }
    if not n:
        return block
    mean = sum(probs) / n
    hist = [0] * DECILE_BINS
    for p in probs:
        hist[min(int(math.floor(p * DECILE_BINS + _EPS)), DECILE_BINS - 1)] += 1
    block.update({
        "midband_share": _round(sum(1 for p in probs if MIDBAND[0] <= p <= MIDBAND[1]) / n),
        "near_half_share": _round(sum(1 for p in probs if NEAR_HALF[0] <= p <= NEAR_HALF[1]) / n),
        "extreme_share": _round(
            sum(1 for p in probs if p <= EXTREME_LOW or p >= EXTREME_HIGH) / n),
        "mean_abs_from_half": _round(sum(abs(p - 0.5) for p in probs) / n),
        "stdev": _round(math.sqrt(sum((p - mean) ** 2 for p in probs) / n)),
        "decile_hist": hist,
    })
    return block


def probability_shape(scenarios: Any = None, binaries: Any = None, *,
                      pre_critique_scenarios: Any = None,
                      policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The ``prob-shape/v1`` record of one forecast; never raises.

    ``pre_critique_scenarios`` (the uncritiqued spine, when a critique ran) adds
    ``scenarios.pre_critique`` and ``scenarios.critique_delta`` (post - pre of
    ``max_probability`` and ``normalized_entropy``). ``policy`` is the prompt policy
    the forecast was produced under (``quality.forecast_policy``), copied as given.
    A block with n=0 carries None stats.
    """
    try:
        return {
            "version": SHAPE_VERSION,
            "policy": dict(policy) if isinstance(policy, dict) else {},
            "scenarios": _scenario_block(scenarios, pre_critique_scenarios),
            "binaries": _binary_block(binaries),
        }
    except Exception:  # noqa: BLE001 — telemetry must never break report finalization
        return {"version": SHAPE_VERSION, "policy": {},
                "scenarios": _scenario_stats([]), "binaries": _binary_block(None)}


def _json_safe(value: Any) -> Any:
    """``value`` unless it is a non-finite float (None then): the final audit re-serialises
    forecast.json with ``allow_nan=False``, so telemetry must never carry NaN or inf."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def scenario_snapshot(scenarios: Any) -> List[Dict[str, Any]]:
    """``[{'name', 'probability'}]`` of each scenario row, values as given except that a
    non-finite float becomes None (the pre-critique record kept in
    ``quality.pre_critique_scenarios``)."""
    if not isinstance(scenarios, (list, tuple)):
        return []
    return [{"name": _json_safe(row.get("name")),
             "probability": _json_safe(row.get("probability"))}
            for row in scenarios if isinstance(row, dict)]


def stamp_pre_critique(forecast: Any, snapshot: List[Dict[str, Any]]) -> bool:
    """Record ``snapshot`` as ``forecast['quality']['pre_critique_scenarios']`` when the
    critique succeeded (``critiqued`` is True); returns whether it did.

    The quality dict is copied, never mutated in place: a critiqued forecast is a
    shallow copy of its input, so the uncritiqued spine shares the same dict.
    """
    if not isinstance(forecast, dict) or forecast.get("critiqued") is not True:
        return False
    quality0 = forecast.get("quality")
    quality = dict(quality0) if isinstance(quality0, dict) else {}
    quality["pre_critique_scenarios"] = list(snapshot or [])
    forecast["quality"] = quality
    return True
