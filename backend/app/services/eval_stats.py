"""Small-n evaluation statistics for binary forecasts (EVAL-7, candidate P06).

A mean Brier score cannot be read on its own when the answer key is imbalanced:
the committed golden set is 24/30 YES, so a constant 0.8 forecast already scores
Brier 0.16 and an always-YES 0.9 forecast is "80% accurate" with zero direction
skill. This module supplies the reference points and diagnostics that make such
numbers honest:

- skill: climatology Brier ``ybar(1-ybar)`` and the Brier skill score against it;
- direction: YES/NO calls at 0.5 (exact ties excluded), predicted vs realized
  YES rate, confusion matrix, MCC (0.0 when undefined), hedge share, confident
  misses;
- strata: horizon buckets and per-stratum flags for small or single-outcome
  groups (a single-outcome stratum has no Brier skill: ``degenerate_reference``);
- uncertainty: an unstratified, cluster-level percentile bootstrap (linked
  questions resample together) and the Wilson interval for a proportion;
- dispersion: a collapse check over a probability vector (constant or hedged).

Pure and stdlib-only: no Config, disk, LLM or network access, so every function
is deterministic and offline-testable. It deliberately lives outside
``app.evaluation`` (that namespace is reserved for WP14's sealed case registry).

Row contract used throughout: a dict with ``probability`` (YES probability, a
float in [0, 1]) and ``outcome`` (truthy when the event happened), plus an
optional ``id`` and any stratum/cluster fields the caller names.
"""

from __future__ import annotations

import math
import numbers
import random
from datetime import date
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

# Hedge band and conviction threshold mirror forecast_extractor._binary_quality
# (midband 0.40 <= p <= 0.60 inclusive; conviction p >= 0.70 or p <= 0.30), so the
# evaluation lane and the publish gate agree on what "hedged" and "confident" mean.
HEDGE_BAND: Tuple[float, float] = (0.40, 0.60)
CONFIDENT_P = 0.70
# A set with at least half of its forecasts inside the hedge band has collapsed
# toward coin-flips.
HEDGE_COLLAPSE_SHARE = 0.5
HORIZON_EDGES: Tuple[int, int] = (30, 180)
MIN_STRATUM_N = 3
DEFAULT_BOOTSTRAP_B = 1000
DEFAULT_BOOTSTRAP_SEED = 1729
# dispersion(): a probability vector is "collapsed" when its spread is below this
# stdev, or when more than this share of it sits inside the hedge band.
COLLAPSE_MIN_STD = 0.08
COLLAPSE_MAX_HEDGE_SHARE = 0.6

DEGENERATE_REFERENCE = "degenerate_reference"
UNKNOWN_BUCKET = "unknown"

Row = Dict[str, Any]
ClusterKey = Union[str, Callable[[Row], Any]]


def round4(v: Optional[float]) -> Optional[float]:
    """Round to 4 decimals for reports; None passes through and -0.0 folds into 0.0."""
    return None if v is None else round(v, 4) + 0.0


def _prob(row: Row) -> float:
    return float(row["probability"])


def _hit(row: Row) -> bool:
    return bool(row["outcome"])


def mean_brier(rows: Sequence[Row]) -> Optional[float]:
    """Mean binary Brier ``(p - y)^2`` over rows (unrounded); None when empty."""
    if not rows:
        return None
    return sum((_prob(r) - (1.0 if _hit(r) else 0.0)) ** 2 for r in rows) / len(rows)


def climatology_brier(outcomes: Iterable[Any]) -> Optional[float]:
    """Brier of the constant forecast p = ybar: ``ybar * (1 - ybar)``; None when empty.

    This is the in-sample base-rate reference: a forecaster with no information
    beyond the answer key's YES share scores exactly this.
    """
    ys = [1.0 if bool(o) else 0.0 for o in outcomes]
    if not ys:
        return None
    ybar = sum(ys) / len(ys)
    return ybar * (1.0 - ybar)


def brier_skill(bs: Optional[float], ref: Optional[float]) -> Optional[float]:
    """Brier skill score ``1 - bs / ref``; None when either is missing or ref <= 0.

    A zero reference (single-outcome set) makes the ratio undefined, never +/-inf.
    """
    if bs is None or ref is None or ref <= 0:
        return None
    return 1.0 - bs / ref


def reference_scores(rows: Sequence[Row]) -> Dict[str, Any]:
    """Skill reference block: base rate, climatology Brier, BSS vs climatology and vs 0.5."""
    if not rows:
        return {"base_rate": None, "climatology_brier": None, "bss": None,
                "bss_vs_half": None, "reason": None}
    bs = mean_brier(rows)
    hits = sum(1 for r in rows if _hit(r))
    clim = climatology_brier(_hit(r) for r in rows)
    bss = brier_skill(bs, clim)
    return {
        "base_rate": round4(hits / len(rows)),
        "climatology_brier": round4(clim),
        "bss": round4(bss),
        "bss_vs_half": round4(brier_skill(bs, 0.25)),
        "reason": DEGENERATE_REFERENCE if bss is None else None,
    }


def mcc(tp: int, fp: int, tn: int, fn: int) -> float:
    """Matthews correlation coefficient; 0.0 when the denominator is zero."""
    denom = math.sqrt(float((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)))
    if denom == 0:
        return 0.0
    return (tp * tn - fp * fn) / denom


def direction_stats(rows: Sequence[Row], *, hedge_band: Tuple[float, float] = HEDGE_BAND,
                    confident_p: float = CONFIDENT_P) -> Dict[str, Any]:
    """Direction, class-collapse and hedging diagnostics at the 0.5 decision point.

    A YES call is p > 0.5 and a NO call is p < 0.5; an exact p == 0.5 is a tie and
    is excluded from the confusion matrix (the legacy ``resolution_accuracy`` in
    golden_eval counts it as YES instead). ``predicted_yes_rate`` is YES calls over
    all rows. ``confident_misses`` lists p >= confident_p on a NO outcome and
    p <= 1 - confident_p on a YES outcome, worst Brier first.
    """
    lo_band, hi_band = hedge_band
    lo_conf = round(1.0 - confident_p, 10)
    n = len(rows)
    tp = fp = tn = fn = ties = hedged = hits = 0
    p_sum = 0.0
    misses: List[Dict[str, Any]] = []
    for r in rows:
        p, y = _prob(r), _hit(r)
        p_sum += p
        hits += 1 if y else 0
        if p > 0.5:
            tp, fp = tp + (1 if y else 0), fp + (0 if y else 1)
        elif p < 0.5:
            fn, tn = fn + (1 if y else 0), tn + (0 if y else 1)
        else:
            ties += 1
        if lo_band <= p <= hi_band:
            hedged += 1
        if (p >= confident_p and not y) or (p <= lo_conf and y):
            misses.append({"id": r.get("id"), "p": p, "outcome": y,
                           "brier": round4((p - (1.0 if y else 0.0)) ** 2)})
    misses.sort(key=lambda m: (-m["brier"], str(m["id"])))
    hedge_share = hedged / n if n else None
    mean_p = p_sum / n if n else None
    ybar = hits / n if n else None
    return {
        "n": n,
        "yes_calls": tp + fp,
        "no_calls": tn + fn,
        "ties": ties,
        "predicted_yes_rate": round4((tp + fp) / n) if n else None,
        "realized_yes_rate": round4(ybar),
        "mean_p": round4(mean_p),
        "mean_bias": round4(mean_p - ybar) if n else None,
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "mcc": round4(mcc(tp, fp, tn, fn)) if n else None,
        "hedge_band": [lo_band, hi_band],
        "hedge_share": round4(hedge_share),
        "hedge_collapse": (hedge_share >= HEDGE_COLLAPSE_SHARE) if n else None,
        "confident_p": confident_p,
        "confident_misses": misses,
    }


def parse_iso_date(value: Any) -> Optional[date]:
    """Parse a canonical ``YYYY-MM-DD`` string (checked by round-trip); None otherwise."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == text else None


def horizon_days(as_of_date: Any, resolution_date: Any) -> Optional[int]:
    """Days from ``as_of_date`` to ``resolution_date``; None when either date is not canonical."""
    start, end = parse_iso_date(as_of_date), parse_iso_date(resolution_date)
    if start is None or end is None:
        return None
    return (end - start).days


def horizon_bucket_labels(edges: Tuple[int, int] = HORIZON_EDGES) -> Tuple[str, str, str, str]:
    """Bucket labels in horizon order: ``(le30, d31_180, gt180, unknown)`` for the default edges."""
    lo, hi = int(edges[0]), int(edges[1])
    if not 0 <= lo < hi:
        raise ValueError(f"horizon edges must satisfy 0 <= lo < hi, got {edges!r}")
    return f"le{lo}", f"d{lo + 1}_{hi}", f"gt{hi}", UNKNOWN_BUCKET


def horizon_bucket(days: Any, edges: Tuple[int, int] = HORIZON_EDGES) -> str:
    """Bucket a horizon in days: ``le30`` | ``d31_180`` | ``gt180`` (default edges) | ``unknown``.

    Missing, non-numeric or negative horizons (resolution before as_of) are ``unknown``.
    """
    near, mid, far, unknown = horizon_bucket_labels(edges)
    if isinstance(days, bool) or not isinstance(days, (int, float)):
        return unknown
    if days != days or days < 0:
        return unknown
    if days <= int(edges[0]):
        return near
    if days <= int(edges[1]):
        return mid
    return far


def strata_stats(rows: Sequence[Row], field: str, min_n: int = MIN_STRATUM_N) -> Dict[str, Any]:
    """Per-stratum ``{n, brier, base_rate, climatology_brier, bss, small, single_outcome, reason}``.

    Strata are keyed by ``str(row[field])`` (``unknown`` when missing), sorted.
    ``small`` marks n < min_n (too few to rank). A single-outcome stratum has a
    zero climatology reference, so its ``bss`` is None with reason
    ``degenerate_reference``.
    """
    groups: Dict[str, List[Row]] = {}
    for r in rows:
        groups.setdefault(str(r.get(field) or UNKNOWN_BUCKET), []).append(r)
    out: Dict[str, Any] = {}
    for key in sorted(groups):
        group = groups[key]
        n = len(group)
        hits = sum(1 for r in group if _hit(r))
        single = hits in (0, n)
        bs = mean_brier(group)
        clim = climatology_brier(_hit(r) for r in group)
        out[key] = {
            "n": n,
            "brier": round4(bs),
            "base_rate": round4(hits / n),
            "climatology_brier": round4(clim),
            "bss": None if single else round4(brier_skill(bs, clim)),
            "small": n < min_n,
            "single_outcome": single,
            "reason": DEGENERATE_REFERENCE if single else None,
        }
    return out


def group_clusters(rows: Sequence[Row], cluster_key: ClusterKey = "cluster") -> Dict[Tuple[str, Any], List[Row]]:
    """Group rows into resampling clusters.

    The cluster is ``cluster_key(row)`` when callable, else ``row[cluster_key]``;
    a missing or blank value falls back to the row's ``id``, and a row with
    neither is its own singleton cluster. Keys are tagged tuples so a real
    cluster name can never collide with a singleton.
    """
    clusters: Dict[Tuple[str, Any], List[Row]] = {}
    for idx, row in enumerate(rows):
        raw = cluster_key(row) if callable(cluster_key) else row.get(cluster_key)
        if raw is None or not str(raw).strip():
            raw = row.get("id")
        key: Tuple[str, Any]
        if raw is None or not str(raw).strip():
            key = ("row", idx)
        else:
            key = ("key", str(raw).strip())
        clusters.setdefault(key, []).append(row)
    return clusters


def cluster_bootstrap_replicates(rows: Sequence[Row], stat_fn: Callable[[List[Row]], Optional[float]],
                                 cluster_key: ClusterKey = "cluster", B: int = DEFAULT_BOOTSTRAP_B,
                                 seed: int = DEFAULT_BOOTSTRAP_SEED) -> Optional[List[Optional[float]]]:
    """Unstratified cluster bootstrap: ``B`` replicate values of ``stat_fn``.

    Each replicate draws as many clusters as exist, with replacement, from a
    ``random.Random(seed)`` stream, so linked questions always move together and
    reruns are identical. Stratifying at DRF's size (3-7 clusters per stratum)
    would understate the variance, so no stratification is done. A replicate on
    which ``stat_fn`` returns None or a non-finite value is kept as None (for
    example a BSS draw with a single outcome). Returns None with fewer than two
    clusters: a one-cluster bootstrap has no variance to report.
    """
    B = int(B)
    if B < 1:
        raise ValueError(f"bootstrap B must be >= 1, got {B}")
    clusters = group_clusters(rows, cluster_key)
    if len(clusters) < 2:
        return None
    members = [clusters[k] for k in sorted(clusters)]
    k = len(members)
    rng = random.Random(seed)
    replicates: List[Optional[float]] = []
    for _ in range(B):
        sample: List[Row] = []
        for _draw in range(k):
            sample.extend(members[rng.randrange(k)])
        value = stat_fn(sample)
        replicates.append(float(value) if value is not None and math.isfinite(value) else None)
    return replicates


def percentile_interval(values: Iterable[Optional[float]], alpha: float = 0.05) -> Optional[List[float]]:
    """Percentile interval ``[s[floor(a/2*m)], s[ceil((1-a/2)*m)-1]]`` over non-None values."""
    if not 0 < alpha < 1:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    ordered = sorted(v for v in values if v is not None)
    m = len(ordered)
    if not m:
        return None
    lo_idx = int(math.floor(round(alpha / 2 * m, 9)))
    hi_idx = int(math.ceil(round((1 - alpha / 2) * m, 9))) - 1
    return [ordered[min(lo_idx, m - 1)], ordered[max(0, min(hi_idx, m - 1))]]


def cluster_bootstrap_ci(rows: Sequence[Row], stat_fn: Callable[[List[Row]], Optional[float]],
                         cluster_key: ClusterKey = "cluster", B: int = DEFAULT_BOOTSTRAP_B,
                         seed: int = DEFAULT_BOOTSTRAP_SEED, alpha: float = 0.05) -> Optional[List[float]]:
    """Cluster percentile bootstrap CI ``[lo, hi]`` of ``stat_fn``; None with fewer than 2 clusters."""
    replicates = cluster_bootstrap_replicates(rows, stat_fn, cluster_key, B, seed)
    if replicates is None:
        return None
    return percentile_interval(replicates, alpha)


def _mann_whitney_auc(pos: Sequence[float], neg: Sequence[float]) -> float:
    """AUC = P(p_pos > p_neg) + 0.5 * P(tie), via midranks (O(n log n))."""
    pooled = sorted([(p, 1) for p in pos] + [(p, 0) for p in neg])
    rank_sum_pos = 0.0
    i = 0
    while i < len(pooled):
        j = i
        while j + 1 < len(pooled) and pooled[j + 1][0] == pooled[i][0]:
            j += 1
        midrank = (i + j) / 2.0 + 1.0
        rank_sum_pos += midrank * sum(label for _p, label in pooled[i:j + 1])
        i = j + 1
    n_pos, n_neg = len(pos), len(neg)
    return (rank_sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def dispersion(ps: Sequence[Any], ys: Sequence[Any]) -> Dict[str, Any]:
    """Spread and collapse check over a probability vector with its outcomes.

    ``collapsed`` is True when the stdev is below 0.08, when more than 60% of the
    forecasts sit in the hedge band, or when every forecast calls the same side
    (``pos_rate`` 0 or 1, with p > 0.5 as a positive call) while both outcomes are
    present. ``auc`` is the Mann-Whitney AUC (0.5 when a class is absent). An
    empty vector cannot show spread, so it reports collapsed (fail closed).
    """
    if len(ps) != len(ys):
        raise ValueError(f"dispersion needs one outcome per probability ({len(ps)} != {len(ys)})")
    probs = [float(p) for p in ps]
    labels = [bool(y) for y in ys]
    n = len(probs)
    if not n:
        return {"n": 0, "std": None, "hedge_share": None, "pos_rate": None, "n_distinct": 0,
                "auc": 0.5, "collapsed": True, "reasons": ["empty"]}
    mean = sum(probs) / n
    std = math.sqrt(sum((p - mean) ** 2 for p in probs) / n)
    lo_band, hi_band = HEDGE_BAND
    hedge_share = sum(1 for p in probs if lo_band <= p <= hi_band) / n
    pos_rate = sum(1 for p in probs if p > 0.5) / n
    pos = [p for p, y in zip(probs, labels, strict=True) if y]
    neg = [p for p, y in zip(probs, labels, strict=True) if not y]
    both_outcomes = bool(pos) and bool(neg)
    reasons: List[str] = []
    if std < COLLAPSE_MIN_STD:
        reasons.append("low_std")
    if hedge_share > COLLAPSE_MAX_HEDGE_SHARE:
        reasons.append("hedged")
    if both_outcomes and pos_rate in (0.0, 1.0):
        reasons.append("one_sided")
    return {
        "n": n,
        "std": round4(std),
        "hedge_share": round4(hedge_share),
        "pos_rate": round4(pos_rate),
        "n_distinct": len({round(p, 6) for p in probs}),
        "auc": round4(_mann_whitney_auc(pos, neg)) if both_outcomes else 0.5,
        "collapsed": bool(reasons),
        "reasons": reasons,
    }


def wilson_interval(k: int, n: int, z: float = 1.96) -> Optional[List[float]]:
    """Wilson score interval ``[lo, hi]`` for k successes in n trials; None when n == 0."""
    if any(isinstance(v, bool) or not isinstance(v, numbers.Integral) for v in (k, n)):
        raise ValueError(f"wilson_interval needs integer counts, got k={k!r} n={n!r}")
    k, n = int(k), int(n)
    if n < 0 or not 0 <= k <= n:
        raise ValueError(f"wilson_interval needs 0 <= k <= n, got k={k} n={n}")
    if z <= 0:
        raise ValueError(f"wilson_interval needs z > 0, got {z}")
    if n == 0:
        return None
    phat = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (phat + z2 / (2 * n)) / denom
    half = z * math.sqrt(phat * (1.0 - phat) / n + z2 / (4.0 * n * n)) / denom
    return [max(0.0, center - half), min(1.0, center + half)]
