"""EVAL-14 (P14): proper scoring rules for quantity (value) forecasts.

The pure scoring core for a future quantity-forecast producer (P12, not built yet)
and for threshold ladders read off binary targets (:mod:`binary_targets`):

- :func:`pinball` / :func:`quantile_score` (the 0.1 / 0.5 / 0.9 quantiles; lower is
  better);
- :func:`interval_score80` (Gneiting-Raftery interval score of the 80% interval
  [q10, q90]: width plus 10x any miss) and :func:`covered80` (inclusive bounds);
- :func:`ape50` (absolute percentage error of the median), only for level-scale
  units: a rate (%, pp, bp in any spelling :func:`binary_targets.canonical_unit`
  reads, e.g. "percent", "bps", "% of GDP") already is a ratio, an unreadable unit is
  not known to be a level, and a realized 0 has no percentage;
- :func:`rel_to_persistence` (score relative to the no-change forecast y0);
- :func:`threshold_ladder_brier` (mean Brier over the rungs of one ladder).

Stdlib plus the pure sibling :mod:`binary_targets` (unit reading and comparators; it
imports only the stdlib at module level), no I/O; non-finite input raises ValueError
rather than scoring.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Sequence, Tuple

from .binary_targets import RATE_UNITS, canonical_unit, comparator_holds

QUANTILES = (0.1, 0.5, 0.9)
INTERVAL_ALPHA = 0.2              # the 80% central interval


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    try:
        number = float(value)
    except OverflowError:
        number = math.inf   # an int too large for a float is not finite
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return number


def pinball(q: float, y: float, tau: float) -> float:
    """Pinball (quantile) loss of the tau-quantile forecast ``q`` for outcome ``y``."""
    q, y, tau = _finite(q, "q"), _finite(y, "y"), _finite(tau, "tau")
    if not 0.0 < tau < 1.0:
        raise ValueError(f"tau must be in (0, 1), got {tau}")
    return tau * (y - q) if y >= q else (1.0 - tau) * (q - y)


def quantile_score(quantiles: Dict[float, float], y: float) -> float:
    """(2 / |T|) * sum of pinball losses over the forecast's quantiles T (here 0.1/0.5/0.9);
    for a single median it equals the absolute error."""
    if not quantiles:
        raise ValueError("quantile_score needs at least one quantile")
    return 2.0 / len(quantiles) * sum(pinball(q, y, tau) for tau, q in quantiles.items())


def interval_score80(q10: float, q90: float, y: float) -> float:
    """(q90 - q10) + (2 / alpha) * max(0, q10 - y) + (2 / alpha) * max(0, y - q90), alpha 0.2."""
    q10, q90, y = _finite(q10, "q10"), _finite(q90, "q90"), _finite(y, "y")
    if q10 > q90:
        raise ValueError(f"interval bounds out of order: q10={q10} > q90={q90}")
    penalty = 2.0 / INTERVAL_ALPHA
    return (q90 - q10) + penalty * max(0.0, q10 - y) + penalty * max(0.0, y - q90)


def covered80(q10: float, q90: float, y: float) -> bool:
    """Whether y lies in [q10, q90] (bounds inclusive)."""
    return _finite(q10, "q10") <= _finite(y, "y") <= _finite(q90, "q90")


def ape50(q50: float, y: float, unit: str) -> Optional[float]:
    """|q50 - y| / |y| for a level-scale unit; None for a rate unit (%, pp, bp in any
    spelling), an unreadable unit, or y == 0."""
    q50, y = _finite(q50, "q50"), _finite(y, "y")
    canonical = canonical_unit(unit)
    if canonical is None or canonical[0] in RATE_UNITS or y == 0:
        return None
    return abs(q50 - y) / abs(y)


def rel_to_persistence(score: float, y: float, y0: Optional[float]) -> Tuple[Optional[float], Optional[str]]:
    """``(score / |y - y0|, None)``: the score relative to the persistence (no-change)
    forecast's absolute error. ``(None, 'no_persistence_anchor')`` without y0;
    ``(None, 'baseline_exact')`` when persistence was exactly right (no denominator)."""
    score, y = _finite(score, "score"), _finite(y, "y")
    if y0 is None:
        return None, "no_persistence_anchor"
    baseline = abs(y - _finite(y0, "y0"))
    if baseline == 0:
        return None, "baseline_exact"
    return score / baseline, None


def threshold_ladder_brier(rungs: Sequence[Tuple[float, str, float]], y: float) -> float:
    """Mean Brier over a ladder's rungs ``(threshold, comparator, p)`` for realized y."""
    if not rungs:
        raise ValueError("threshold_ladder_brier needs at least one rung")
    y = _finite(y, "y")
    total = 0.0
    for threshold, comparator, p in rungs:
        p = _finite(p, "p")
        if not 0.0 <= p <= 1.0:
            raise ValueError(f"rung probability must be in [0, 1], got {p}")
        outcome = 1.0 if comparator_holds(y, comparator, _finite(threshold, "threshold")) else 0.0
        total += (p - outcome) ** 2
    return total / len(rungs)
