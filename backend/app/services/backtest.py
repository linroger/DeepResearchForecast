"""Backtesting & calibration scoring for structured forecasts (EXECPLAN2 I-9-2).

Once a forecast's horizon passes and the real outcome is known, score how good
the probabilities were — Brier score (lower=better) and log-loss — and, across
many resolved forecasts, a calibration report (do things predicted at ~70%
actually happen ~70% of the time?). This is what closes the loop from
"forecasting tool" to "calibratable forecasting tool". Pure / offline-testable.

A resolved forecast pairs a structured forecast (scenarios w/ probabilities) with
an ``outcome``: the name of the scenario that actually occurred (or its index).

EVAL-5 adds ``market_skill_report``: Brier skill of resolved market-anchored binaries
against the market price each forecast saw, and the hit rate of the forecasts that
claimed an edge over that price (``divergence_eligible``, the 10pp revision rule)
against the hit rate the market itself implies. Pure: normalized rows in, one dict out.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .ensemble import _norm_name
from .eval_stats import wilson_interval


def _cfg(name: str, default: Any) -> Any:
    """Read a Config flag with a safe default (degrade-safe; never raises)."""
    try:
        from ..config import Config
        return getattr(Config, name, default)
    except Exception:  # noqa: BLE001
        return default


def _scenario_prob(scenario: Dict[str, Any]) -> float:
    for k in ("probability", "mean_probability"):
        v = scenario.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return 0.0


def score_forecast(forecast: Dict[str, Any], outcome: str) -> Dict[str, Any]:
    """Score one resolved forecast against the scenario that actually happened.

    Multi-class Brier score = sum over scenarios of (p_i - y_i)^2 where y_i is 1
    for the realized scenario else 0. Also returns the probability the forecast
    assigned to the realized scenario and a log-loss (clamped).
    """
    scenarios = [s for s in (forecast.get("scenarios") or []) if isinstance(s, dict)]
    if not scenarios:
        return {"error": "no scenarios", "brier": None, "realized_probability": None}
    target = _norm_name(outcome)
    names = [_norm_name(s.get("name")) for s in scenarios]
    matched = target in names
    brier = 0.0
    realized_p = 0.0
    for s, nm in zip(scenarios, names):
        p = _scenario_prob(s)
        y = 1.0 if nm == target else 0.0
        brier += (p - y) ** 2
        if y:
            realized_p = p
    eps = 1e-9
    log_loss = -math.log(min(1.0, max(eps, realized_p))) if matched else None
    return {
        "brier": round(brier, 4),
        "realized_probability": round(realized_p, 4),
        "log_loss": round(log_loss, 4) if log_loss is not None else None,
        "outcome_matched_a_scenario": matched,
        "n_scenarios": len(scenarios),
    }


def calibration_report(resolved: List[Dict[str, Any]],
                       bins: int = 5) -> Dict[str, Any]:
    """Aggregate calibration across many resolved forecasts.

    Each item: {"forecast": <forecast dict>, "outcome": <scenario name>}. Buckets
    every scenario's predicted probability and compares the bucket's mean
    predicted probability to the observed hit-rate (how often those scenarios
    actually occurred). Returns per-bin stats + mean Brier + a calibration error.

    EVAL-5: ``n_unmatched_outcome`` (additive) counts the items whose outcome names
    none of their scenarios; they still enter every legacy number exactly as before
    (scored as an all-miss), so the count makes that silent penalty visible.
    """
    items = [r for r in (resolved or []) if isinstance(r, dict) and r.get("forecast")]
    if not items:
        return {"n": 0, "mean_brier": None, "bins": [], "calibration_error": None,
                "n_unmatched_outcome": 0}

    edges = [i / bins for i in range(bins + 1)]
    buckets = [{"lo": edges[i], "hi": edges[i + 1], "preds": [], "hits": []} for i in range(bins)]
    briers: List[float] = []
    n_unmatched = 0

    for r in items:
        fc, outcome = r["forecast"], r.get("outcome")
        sc = score_forecast(fc, outcome or "")
        if sc.get("brier") is not None:
            briers.append(sc["brier"])
        if sc.get("outcome_matched_a_scenario") is False:
            n_unmatched += 1
        tgt = _norm_name(outcome)
        for s in (fc.get("scenarios") or []):
            if not isinstance(s, dict):
                continue
            p = _scenario_prob(s)
            hit = 1.0 if _norm_name(s.get("name")) == tgt else 0.0
            idx = min(bins - 1, max(0, int(p * bins)))
            buckets[idx]["preds"].append(p)
            buckets[idx]["hits"].append(hit)

    # R2-CAL-14: Jeffreys (Beta(0.5,0.5)) smoothing for per-bin hit-rates + a credible
    # interval, so a 1/1 bin doesn't masquerade as perfectly calibrated.
    alpha = beta = 0.5
    bin_out = []
    cal_err_terms = []
    total = 0
    # accumulators for the Murphy Brier decomposition (R2-CAL-10)
    all_hits = 0.0
    all_n = 0
    rel_terms = 0.0   # sum n_k (p_k - o_k)^2  (reliability, lower=better)
    pooled_sq = 0.0   # sum (p_i - y_i)^2 over every per-scenario prediction
    for b in buckets:
        n = len(b["preds"])
        total += n
        if n:
            mean_pred = sum(b["preds"]) / n
            hits = sum(b["hits"])
            hit_rate = hits / n
            cal_err_terms.append((n, abs(mean_pred - hit_rate)))
            pooled_sq += sum((p - y) ** 2 for p, y in zip(b["preds"], b["hits"]))
            smoothed = (hits + alpha) / (n + alpha + beta)
            # normal-approx credible interval on the smoothed Beta posterior
            a_post, b_post = hits + alpha, (n - hits) + beta
            var = (a_post * b_post) / ((a_post + b_post) ** 2 * (a_post + b_post + 1))
            half = 1.96 * math.sqrt(var)
            ci_low = round(max(0.0, smoothed - half), 4)
            ci_high = round(min(1.0, smoothed + half), 4)
            all_hits += hits
            all_n += n
            rel_terms += n * (mean_pred - hit_rate) ** 2
        else:
            mean_pred = hit_rate = smoothed = ci_low = ci_high = None
        bin_out.append({
            "range": [round(b["lo"], 2), round(b["hi"], 2)],
            "count": n,
            "mean_predicted": round(mean_pred, 4) if mean_pred is not None else None,
            "observed_hit_rate": round(hit_rate, 4) if hit_rate is not None else None,
            "hit_rate_smoothed": round(smoothed, 4) if smoothed is not None else None,
            "ci_low": ci_low,
            "ci_high": ci_high,
        })
    # expected calibration error (count-weighted)
    cal_err: Optional[float] = None
    if total:
        cal_err = round(sum(w * e for w, e in cal_err_terms) / total, 4)

    # R2-CAL-10 — Murphy decomposition: Brier = Reliability − Resolution + Uncertainty.
    decomposition: Optional[Dict[str, float]] = None
    if all_n:
        obar = all_hits / all_n                                   # overall base rate
        reliability = rel_terms / all_n
        resolution = 0.0
        for b in buckets:
            nk = len(b["preds"])
            if nk:
                ok = sum(b["hits"]) / nk
                resolution += nk * (ok - obar) ** 2
        resolution /= all_n
        uncertainty = obar * (1.0 - obar)
        decomposition = {
            "reliability": round(reliability, 4),
            "resolution": round(resolution, 4),
            "uncertainty": round(uncertainty, 4),
            # per-prediction (reliability-diagram) Brier the 3 terms decompose:
            # brier_pooled ≈ reliability − resolution + uncertainty (binning residual aside).
            "brier_pooled": round(pooled_sq / all_n, 4),
        }

    # R2-CAL-14 — CAL_MIN_RESOLVED gate: flag (don't suppress) thin-evidence reports.
    min_resolved = int(_cfg("CAL_MIN_RESOLVED", 0) or 0)
    insufficient = bool(min_resolved and len(items) < min_resolved)

    return {
        "n": len(items),
        "mean_brier": round(sum(briers) / len(briers), 4) if briers else None,
        "calibration_error": cal_err,
        "brier_decomposition": decomposition,    # R2-CAL-10
        "resolution": decomposition.get("resolution") if decomposition else None,
        "insufficient_data": insufficient,       # R2-CAL-14 gate
        "bins": bin_out,
        "n_unmatched_outcome": n_unmatched,      # EVAL-5
    }


def fit_recalibrator(resolved: List[Dict[str, Any]]) -> Dict[str, Any]:
    """R2-CAL-5: fit a 1-parameter logit-scale recalibrator from resolved forecasts.

    Models observed hit ~ sigmoid(slope · logit(p_pred)); a slope < 1 means the
    forecaster is over-confident (probabilities should be pulled toward 0.5), > 1
    under-confident. Fitted by a tiny gradient descent on log-loss. Returns
    ``{slope, n, fitted}``; ``slope=1.0`` (identity) when there is too little data —
    so applying it is always a no-op until enough labels exist (degrade-safe).

    Application is deliberately left OFF by default (REPORT_RECALIBRATE_FROM_LEDGER);
    callers should only apply ``slope`` once ``n`` is meaningful.
    """
    pts: List = []  # (logit_p, y)
    eps = 1e-6
    for r in (resolved or []):
        if not isinstance(r, dict):
            continue
        fc, outcome = r.get("forecast"), r.get("outcome")
        if not fc or outcome is None:
            continue
        tgt = _norm_name(outcome)
        for s in (fc.get("scenarios") or []):
            if not isinstance(s, dict):
                continue
            p = min(1.0 - eps, max(eps, _scenario_prob(s)))
            y = 1.0 if _norm_name(s.get("name")) == tgt else 0.0
            pts.append((math.log(p / (1.0 - p)), y))
    if len(pts) < 10:
        return {"slope": 1.0, "n": len(pts), "fitted": False}
    slope = 1.0
    lr = 0.05
    for _ in range(500):
        grad = 0.0
        for x, y in pts:
            z = max(-50.0, min(50.0, slope * x))
            pred = 1.0 / (1.0 + math.exp(-z))
            grad += (pred - y) * x
        slope -= lr * grad / len(pts)
        slope = max(0.1, min(5.0, slope))
    return {"slope": round(slope, 4), "n": len(pts), "fitted": True}


def apply_recalibration(prob: float, slope: float, eps: float = 1e-6) -> float:
    """Apply a fitted logit-scale ``slope`` to a single probability (R2-CAL-5)."""
    try:
        p = min(1.0 - eps, max(eps, float(prob)))
        z = max(-50.0, min(50.0, float(slope) * math.log(p / (1.0 - p))))
        return 1.0 / (1.0 + math.exp(-z))
    except (TypeError, ValueError, ZeroDivisionError):
        return prob


# ---------------------------------------------------------------------------
# EVAL-5: market-relative skill (read-only, interim; a WP13 score row can feed it)
# ---------------------------------------------------------------------------

MARKET_SKILL_SCHEMA = "market-skill/v1"
# The dead-band of forecast_extractor.enforce_market_divergence (the 10pp revision rule): a
# forecast within it of the market price claims no edge. Strict, as there: |d| must EXCEED it.
MARKET_DIVERGENCE_DEADBAND = 0.10
# Only an exact-equivalence anchor resolves the same proposition as the forecast it prices.
HEADLINE_EQUIVALENCE = "exact"
# Anchor price_time_basis values (EVAL-6, FU-11), in prediction_markets.market_price_time's
# precedence: its PRICE_TIME_BASIS_REQUOTE / _OBSERVED / _SNAPSHOT, mirrored so the scorer
# stays free of that module's network client (a parity test pins the two). A market price
# without one of them is undated.
PRICE_TIME_BASES = ("requote", "observed", "snapshot")
# Gate reasons that only demote a row to the proxy stratum (its anchor prices a related, not the
# same, proposition); every other gate reason keeps a row out of all strata.
PROXY_GATE_REASONS = ("equivalence_near", "equivalence_loose", "equivalence_missing")
NO_PRICE_TIME_BASIS = "no_price_time_basis"
WITHHELD_REPORT = "withheld_report"
SKILL_STRATA = ("headline", "proxy", "all_produced")
MARKET_SKILL_CAVEATS = (
    "Anchored subset only: a binary without a market anchor has no price to score against, so "
    "anchor coverage bounds what these figures can say.",
    "proxy rows are scored against a near/loose-equivalence market (a related, not the same, "
    "proposition) or an exact market whose price has no time basis; they are proxy labels and "
    "never pooled with the headline.",
    "market_p is the anchor price the extractor saw (price_at_research), dated by the anchor's "
    "price_time_basis: a report-time requote, not a research-time price, when 'requote'; the "
    "research bridge's fetch of that market row when 'observed'; a snapshot (research or "
    "report-time) whose as_of only bounds the price's time from above when 'snapshot'.",
    "This measures the published, market-aware forecast (the market price is in the extraction "
    "prompt), not information the pipeline holds independently of the market.",
    "all_produced adds rows of reports not publishable at issue to the headline criteria for "
    "transparency only; it is never a headline figure.",
)


def _finite_float(value: Any) -> Optional[float]:
    """A finite float, else None (bools are not numbers here)."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _unit_float(value: Any) -> Optional[float]:
    """A finite probability in [0, 1], else None."""
    number = _finite_float(value)
    return number if number is not None and 0.0 <= number <= 1.0 else None


def _binary_label(y: Any) -> Optional[int]:
    """1 or 0 for a YES/NO label, else None (bools and other values are unlabelled)."""
    if isinstance(y, bool) or not isinstance(y, (int, float)) or y not in (0, 1):
        return None
    return int(y)


def divergence_eligible(d: Any, mc: Any, min_conf: Any) -> bool:
    """Does a forecast ``d`` = model_p - market_p away from its anchor claim an edge the 10pp
    revision rule would act on? ``abs(d) > MARKET_DIVERGENCE_DEADBAND`` (strict: exactly 0.10
    claims none) and match confidence ``mc >= min_conf``, the same boundaries as
    ``forecast_extractor.enforce_market_divergence`` (which also skips a rationale that
    already cites the market). A missing or non-finite value is never eligible."""
    d_value, confidence, floor = _finite_float(d), _finite_float(mc), _finite_float(min_conf)
    if d_value is None or confidence is None or floor is None:
        return False
    return abs(d_value) > MARKET_DIVERGENCE_DEADBAND and confidence >= floor


def _price_time_basis(row: Dict[str, Any]) -> Optional[str]:
    basis = row.get("price_time_basis")
    return basis if basis in PRICE_TIME_BASES else None


def _skill_bucket(row: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """``('headline', None)``, ``('proxy', reason)`` or ``('unscored', reason)`` for one row,
    publishability aside. Checked in order: a gate reason other than an equivalence demotion,
    ``unlabelled``, ``missing_probability``, ``missing_market_price``; then the headline needs
    no gate reason, an exact equivalence and a price time basis, and anything short of that is
    proxy (the reason names the first shortfall)."""
    gate = row.get("gate_reason")
    gate = str(gate).strip() if gate not in (None, "") else None
    if gate is not None and gate not in PROXY_GATE_REASONS:
        return "unscored", gate
    if _binary_label(row.get("y")) is None:
        return "unscored", "unlabelled"
    if _unit_float(row.get("model_p")) is None:
        return "unscored", "missing_probability"
    if _unit_float(row.get("market_p")) is None:
        return "unscored", "missing_market_price"
    if gate is not None:
        return "proxy", gate
    equivalence = str(row.get("equivalence") or "").strip().lower()
    if equivalence != HEADLINE_EQUIVALENCE:
        level = equivalence if equivalence in ("near", "loose") else "missing"
        return "proxy", f"equivalence_{level}"
    if _price_time_basis(row) is None:
        return "proxy", NO_PRICE_TIME_BASIS
    return "headline", None


def _round4(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 4)


def _mean(values: List[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _hit_stats(edges: List[Tuple[float, float, int, Any]]) -> Dict[str, Any]:
    """Hit rate of edge-claiming rows ``(d, market_p, y, rationale_cites_market)`` against the
    market-implied null: a hit is ``(y - market_p) * d > 0`` (the outcome landed on the
    forecast's side of the market), and under the market's own probabilities that happens with
    ``market_p`` when d > 0, else ``1 - market_p``."""
    n = len(edges)
    hits = sum(1 for d, market_p, y, _ in edges if (y - market_p) * d > 0)
    hit_rate = hits / n if n else None
    null_rate = _mean([market_p if d > 0 else 1.0 - market_p for d, market_p, _, _ in edges])
    interval = wilson_interval(hits, n)
    return {
        "n": n,
        "hits": hits,
        "hit_rate": _round4(hit_rate),
        "hit_rate_ci95": [round(bound, 4) for bound in interval] if interval else None,
        "null_hit_rate": _round4(null_rate),
        "hit_rate_excess": _round4(hit_rate - null_rate) if n else None,
        "n_rationale_cites_market": sum(1 for *_, cites in edges if cites is True),
        "n_rationale_unknown": sum(1 for *_, cites in edges if cites not in (True, False)),
    }


def _divergence_block(rows: List[Dict[str, Any]], min_conf: float) -> Dict[str, Any]:
    """Divergence accounting over one stratum's scored rows. d = model_p - market_p, rounded
    to 4 places as ``_build_market_anchor`` stores ``divergence``, so float noise never moves a
    row across the strict 0.10 boundary that ``enforce_market_divergence`` applies to it.
    Rows inside the dead-band claim no edge (they still count in the Brier skill); a row
    without a match confidence has unknown eligibility; an edge row is
    ``revised_toward_market`` when its binary carries a standing market_influence prior
    (the divergence revision moved it), else ``retained_divergence``."""
    no_edge = low_confidence = unknown = 0
    groups: Dict[str, List[Tuple[float, float, int, Any]]] = {
        "edge": [], "revised_toward_market": [], "retained_divergence": []}
    for row in rows:
        market_p = float(row["market_p"])
        d = round(float(row["model_p"]) - market_p, 4)
        if abs(d) <= MARKET_DIVERGENCE_DEADBAND:
            no_edge += 1
            continue
        confidence = _finite_float(row.get("match_confidence"))
        if confidence is None:
            unknown += 1
            continue
        if not divergence_eligible(d, confidence, min_conf):
            low_confidence += 1
            continue
        edge = (d, market_p, int(row["y"]), row.get("rationale_cites_market"))
        groups["edge"].append(edge)
        revised = _unit_float(row.get("prior_probability")) is not None
        groups["revised_toward_market" if revised else "retained_divergence"].append(edge)
    return {
        "deadband": MARKET_DIVERGENCE_DEADBAND,
        "min_match_confidence": min_conf,
        "n_no_edge_claimed": no_edge,
        "n_ineligible_low_confidence": low_confidence,
        "n_eligibility_unknown": unknown,
        **{name: _hit_stats(edges) for name, edges in groups.items()},
    }


def _report_delta_ci95(deltas: Dict[str, List[float]]) -> Optional[List[float]]:
    """Normal-approximation 95% interval for the mean of per-report mean Brier deltas (rows of
    one report share a question and a run, so the report is the unit); None under 2 reports."""
    means = [sum(values) / len(values) for values in deltas.values()]
    if len(means) < 2:
        return None
    center = sum(means) / len(means)
    sd = math.sqrt(sum((m - center) ** 2 for m in means) / (len(means) - 1))
    half = 1.96 * sd / math.sqrt(len(means))
    return [round(center - half, 4), round(center + half, 4)]


def _stratum_stats(rows: List[Dict[str, Any]], *, min_n: int, min_conf: float,
                   headline: bool) -> Dict[str, Any]:
    """Brier, skill and divergence figures of one stratum's scored rows."""
    model_briers: List[float] = []
    market_briers: List[float] = []
    deltas: Dict[str, List[float]] = defaultdict(list)
    for row in rows:
        y = int(row["y"])
        model_brier = (float(row["model_p"]) - y) ** 2
        market_brier = (float(row["market_p"]) - y) ** 2
        model_briers.append(model_brier)
        market_briers.append(market_brier)
        deltas[str(row.get("report_id") or "")].append(market_brier - model_brier)
    bs_model, bs_market = _mean(model_briers), _mean(market_briers)
    skill = (1.0 - bs_model / bs_market) if bs_market else None
    bases = Counter(_price_time_basis(row) or "none" for row in rows)
    return {
        "headline": headline,
        "n_scored": len(rows),
        "n_reports": len(deltas),
        "mean_brier_model": _round4(bs_model),
        "mean_brier_market": _round4(bs_market),
        "brier_skill_vs_market": _round4(skill),
        "mean_brier_delta": _round4(bs_market - bs_model) if rows else None,
        "brier_delta_ci95": _report_delta_ci95(deltas),
        "insufficient_data": len(rows) < min_n,
        "price_time_basis": {basis: bases.get(basis, 0) for basis in PRICE_TIME_BASES + ("none",)},
        "divergence": _divergence_block(rows, min_conf),
    }


def market_skill_report(rows: Optional[Iterable[Any]], *, min_n: int = 10,
                        min_match_confidence: float = 0.6) -> Dict[str, Any]:
    """Skill of resolved market-anchored binaries against the market price each one saw.

    ``rows`` are normalized dicts: ``report_id``, ``forecast_id``, ``y`` (1/0), ``model_p``,
    ``market_p``, ``equivalence``, ``match_confidence``, ``publishable_at_issue``,
    ``rationale_cites_market``, ``prior_probability``, ``price_time_basis`` and
    ``gate_reason`` (None when the settlement passed the point-in-time gate, an equivalence
    reason when only the anchor's equivalence kept it out, else why it is never scored).

    Every row lands in exactly one place (``n_rows`` = headline + proxy + unscored): a row
    whose report was not publishable at issue is always ``unscored.withheld_report`` (fail
    closed); otherwise ``_skill_bucket`` makes it ``unscored.<reason>``, ``proxy`` or
    ``headline``. ``all_produced`` re-scores the headline criteria with the withheld rows
    added (``n_withheld``), for transparency, never as a headline. Each stratum reports
    ``n_scored``, ``n_reports``, model and market mean Brier, ``brier_skill_vs_market`` =
    1 - BS_model / BS_market (None when BS_market is 0), ``mean_brier_delta`` = BS_market -
    BS_model, ``brier_delta_ci95`` over per-report mean deltas (None under 2 reports),
    ``insufficient_data`` (n_scored < ``min_n``), the price-time-basis mix and the
    divergence block (``_divergence_block``; edges need ``divergence_eligible`` at
    ``min_match_confidence``). With nothing scored every metric is None and every count 0.
    Raises ValueError on a non-integer ``min_n`` or a non-finite ``min_match_confidence``.
    """
    if isinstance(min_n, bool) or not isinstance(min_n, int):
        raise ValueError(f"min_n must be an integer, got {min_n!r}")
    min_conf = _finite_float(min_match_confidence)
    if min_conf is None:
        raise ValueError(f"min_match_confidence must be finite, got {min_match_confidence!r}")
    members: Dict[str, List[Dict[str, Any]]] = {name: [] for name in SKILL_STRATA}
    proxy_reasons: Counter = Counter()
    unscored: Counter = Counter()
    n_rows = n_withheld = 0
    for row in rows or []:
        n_rows += 1
        if not isinstance(row, dict):
            unscored["invalid_row"] += 1
            continue
        bucket, reason = _skill_bucket(row)
        if row.get("publishable_at_issue") is not True:
            unscored[WITHHELD_REPORT] += 1
            if bucket == "headline":
                members["all_produced"].append(row)
                n_withheld += 1
            continue
        if bucket == "unscored":
            unscored[reason] += 1
        elif bucket == "proxy":
            members["proxy"].append(row)
            proxy_reasons[reason] += 1
        else:
            members["headline"].append(row)
            members["all_produced"].append(row)
    strata = {name: _stratum_stats(members[name], min_n=min_n, min_conf=min_conf,
                                   headline=name == "headline")
              for name in SKILL_STRATA}
    strata["proxy"]["proxy_reasons"] = dict(sorted(proxy_reasons.items()))
    strata["all_produced"]["n_withheld"] = n_withheld
    return {
        "schema": MARKET_SKILL_SCHEMA,
        "min_n": min_n,
        "min_match_confidence": min_conf,
        "divergence_deadband": MARKET_DIVERGENCE_DEADBAND,
        "n_rows": n_rows,
        "strata": strata,
        "unscored": dict(sorted(unscored.items())),
        "n_unscored": sum(unscored.values()),
        "caveats": list(MARKET_SKILL_CAVEATS),
    }
