"""Backtesting & calibration scoring for structured forecasts (EXECPLAN2 I-9-2).

Once a forecast's horizon passes and the real outcome is known, score how good
the probabilities were — Brier score (lower=better) and log-loss — and, across
many resolved forecasts, a calibration report (do things predicted at ~70%
actually happen ~70% of the time?). This is what closes the loop from
"forecasting tool" to "calibratable forecasting tool". Pure / offline-testable.

A resolved forecast pairs a structured forecast (scenarios w/ probabilities) with
an ``outcome``: the name of the scenario that actually occurred (or its index).
"""

from __future__ import annotations

import math
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional

from .ensemble import _norm_name


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
    """
    items = [r for r in (resolved or []) if isinstance(r, dict) and r.get("forecast")]
    if not items:
        return {"n": 0, "mean_brier": None, "bins": [], "calibration_error": None}

    edges = [i / bins for i in range(bins + 1)]
    buckets = [{"lo": edges[i], "hi": edges[i + 1], "preds": [], "hits": []} for i in range(bins)]
    briers: List[float] = []

    for r in items:
        fc, outcome = r["forecast"], r.get("outcome")
        sc = score_forecast(fc, outcome or "")
        if sc.get("brier") is not None:
            briers.append(sc["brier"])
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


# Prospective design and trial references only. Published probabilities and
# outcomes remain authoritative in forecast_feedback, never in this journal.
EVALUATION_COST_COMPONENTS = ("acquisition", "simulation", "verification", "retries", "failures", "synthesis")
_EVALUATION_LOCK = threading.RLock()
_DISPOSITIONS = ("published", "failed", "abstained", "disputed", "void")
_CONTRASTS = ("same_evidence_diagnostic", "equal_cost_diagnostic", "equal_cost_investigation")


def _evaluation_now():
    return datetime.now(timezone.utc).isoformat()


def _eval_require(condition, message):
    if not condition:
        raise ValueError(message)


def _eval_number(value):
    return type(value) in (float, int) and math.isfinite(value) and value >= 0


def _evaluation_terminal_market(anchor):
    # A resolved No is just as terminal as Yes. Missing/null outcome is unknown;
    # explicit false closed/resolved flags are the ordinary unresolved case.
    return (any(anchor.get(k) is not None and anchor.get(k) is not False for k in ("closed", "resolved"))
            or anchor.get("resolved_outcome") is not None)


def _evaluation_official_identity(anchor, metadata=None):
    from . import official_data
    if metadata is None:
        metadata = {k: anchor[k] for k in ("series", "units", "frequency", "transform", "geography") if k in anchor}
    canonical = official_data.validate_data_anchor(anchor, {"series": [metadata]})
    _eval_require(canonical is not None, "official observation period cannot be canonicalized")
    family = ("official_data_binary", canonical["series"], canonical["frequency"], canonical["period"])
    return family, (*family, canonical["transform"], canonical["units"],
                    canonical["comparator"], canonical["threshold"])


@contextmanager
def _evaluation_unknown_settlements(questions, ledger_dir):
    """Check all registered publications, keeping an existing journal locked until append.

    Publication IDs and forecast IDs do not identify independent outcomes. Read
    the registry once under its own validated journal boundary; never trust a
    declared future outcome time over an outcome already present in that journal.
    Re-resolve official predicates from admitted same-vintage snapshots: changing
    a threshold cannot hide a known measurement. A genuinely future vintage is
    not treated as known solely from an older vintage.
    """
    from . import forecast_feedback as registry
    with registry._journal(ledger_dir) as (_, events):
        publications, outcomes, _ = registry._state(events)
        known, official_evidence = set(), []
        for rid, publication in publications.items():
            for binary in publication["forecast"].get("binary_forecasts", []):
                anchor = binary.get("market_anchor") or {}
                if anchor.get("market_id") and (_evaluation_terminal_market(anchor) or
                                                _evaluation_terminal_market(binary)):
                    known.add(("market_binary", anchor["market_id"]))
                outcome = outcomes.get((rid, binary["id"]))
                if not outcome:
                    continue
                if outcome["kind"] == "market_binary":
                    known.add(("market_binary", anchor["market_id"]))
                elif outcome["kind"] == "official_data_binary":
                    official_evidence.append(outcome["evidence"])
        for question in questions:
            source = question["resolution_source"]
            if source["kind"] == "market_binary":
                identity = ("market_binary", source["anchor"]["market_id"])
                _eval_require(identity not in known, "cannot admit a machine-known settlement")
            else:
                from . import official_data
                anchor = source["anchor"]
                for evidence in official_evidence:
                    dataset = evidence["dataset_snapshot"]
                    if (evidence.get("vintage") != source["outcome_vintage"]
                        or dataset.get("frequency") != anchor["frequency"]
                        or anchor.get("geography") and dataset.get("geography") != anchor["geography"]):
                        continue
                    decision = official_data.resolve_data_anchor(anchor, dataset, as_of=evidence["resolved_at"])
                    _eval_require(decision.get("status") != "resolved", "cannot admit a machine-known settlement")
        yield


def _evaluation_design(spec, enrolled_at):
    """Strict input contract; identifiers are operator-assigned, never fuzzy joins."""
    from . import forecast_feedback as registry
    spec = registry._clone(spec)
    _eval_require(isinstance(spec, dict), "evaluation design must be an object")
    for field in ("cohort_id", "policy_version"):
        registry._identity(spec.get(field))
    arms, questions, contrast = spec.get("arms"), spec.get("questions"), spec.get("contrast")
    _eval_require(isinstance(arms, list) and len(arms) == 2, "exactly two arms required")
    _eval_require(isinstance(questions, list) and bool(questions), "questions required")
    _eval_require(isinstance(contrast, dict) and contrast.get("kind") in _CONTRASTS, "invalid contrast")
    arm_ids = set()
    for arm in arms:
        _eval_require(isinstance(arm, dict), "invalid arm")
        aid = registry._identity(arm.get("id"))
        registry._identity(arm.get("method"))
        _eval_require(aid not in arm_ids and _eval_number(arm.get("budget_usd")), "invalid arm budget or duplicate id")
        arm_ids.add(aid)
    _eval_require({contrast.get("baseline"), contrast.get("candidate")} == arm_ids, "contrast arms mismatch")
    if contrast["kind"].startswith("equal_cost"):
        _eval_require(arms[0]["budget_usd"] == arms[1]["budget_usd"] > 0, "equal total budgets required")
        _eval_require(_eval_number(contrast.get("cost_tolerance_usd")), "cost tolerance required")
        _eval_require(contrast["cost_tolerance_usd"] <= arms[0]["budget_usd"] * 0.1,
                      "cost tolerance exceeds ten percent of budget")
    if contrast["kind"] == "equal_cost_investigation":
        _eval_require(_eval_number(contrast.get("practical_brier_margin"))
                      and 0 < contrast["practical_brier_margin"] <= 1, "practical Brier margin required")
    ids, contracts, settlements, settlement_families = set(), set(), set(), {}
    for question in questions:
        _eval_require(isinstance(question, dict), "invalid question")
        for field in ("question_id", "event_family_id", "statement", "resolution_criteria"):
            registry._identity(question.get(field))
        qid = question["question_id"]
        _eval_require(qid not in ids, "duplicate question id")
        ids.add(qid)
        _eval_require(not any(k in question for k in ("outcome", "resolved_outcome", "probability")),
                      "enrollment cannot contain predictions or outcomes")
        due = registry._instant(question.get("forecast_due_at"))
        earliest = registry._instant(question.get("outcome_not_before"))
        resolves = registry._instant(question.get("resolution_date"), date_end=True)
        _eval_require(registry._instant(enrolled_at) < due < earliest <= resolves,
                      "enrollment and forecast deadline must precede outcome availability")
        source = question.get("resolution_source")
        _eval_require(isinstance(source, dict) and source.get("kind") in
                      ("market_binary", "official_data_binary") and isinstance(source.get("anchor"), dict),
                      "typed resolution source required")
        anchor = source["anchor"]
        if source["kind"] == "market_binary":
            registry._identity(anchor.get("market_id"))
            _eval_require(anchor.get("resolution_equivalence") == "exact", "exact market contract required")
            _eval_require(not _evaluation_terminal_market(anchor), "terminal market anchor is not prospective")
            family_key = ("market_binary", anchor["market_id"])
            settlement_key = family_key
        else:
            for field in ("series", "units"):
                registry._identity(anchor.get(field))
            _eval_require(bool(anchor.get("period") or anchor.get("observation")) and
                          anchor.get("comparator") in (">", ">=", "<", "<=") and
                          type(anchor.get("threshold")) in (int, float) and math.isfinite(anchor["threshold"]),
                          "official observation contract required")
            vintage = source.get("outcome_vintage")
            _eval_require(isinstance(vintage, str) and len(vintage) == 10 and
                          registry._instant(vintage).date().isoformat() == vintage and
                          registry._instant(vintage, date_end=True) >= earliest,
                          "official outcome_vintage must pin a YYYY-MM-DD vintage at or after outcome availability")
            _eval_require(anchor.get("frequency") in ("D", "W", "M", "Q", "A"),
                          "official frequency required for stable period identity")
            # Reuse the resolver's exact period grammar with declared metadata,
            # no observations or acquisition. Due-date heuristics cannot identify
            # monthly/quarterly aliases safely when frequency is missing.
            # Conservative grouping: different thresholds/vintages for the same
            # observed series/period share one family. Prose never creates N.
            family_key, settlement_key = _evaluation_official_identity(anchor)
        _eval_require(settlement_key not in settlements, "duplicate settlement identity; revisions are not new cases")
        settlements.add(settlement_key)
        _eval_require(settlement_families.setdefault(family_key, question["event_family_id"]) == question["event_family_id"],
                      "same settlement must retain one event family")
        contract = {k: question[k] for k in ("statement", "resolution_criteria", "resolution_source",
                                            "resolution_date", "outcome_not_before")}
        digest = registry._digest(contract)
        _eval_require(digest not in contracts, "duplicate question contract; revisions are not new cases")
        contracts.add(digest)
        question["contract_sha256"] = digest
    return spec


@contextmanager
def _evaluation_journal(path, *, write=False):
    """Locked, checksummed enrollment log; a damaged tail fails closed."""
    import fcntl
    from . import forecast_feedback as registry
    path = Path(path)
    with _EVALUATION_LOCK:
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b" if write else "rb") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX if write else fcntl.LOCK_SH)
            stream.seek(0)
            events, previous = [], None
            for line in stream:
                _eval_require(line.endswith(b"\n"), "evaluation journal torn tail")
                try:
                    wrapped = json.loads(line)
                    event = wrapped["event"]
                    _eval_require(wrapped["sha256"] == registry._digest(event)
                                  and event["previous"] == previous, "evaluation journal checksum")
                    previous = wrapped["sha256"]
                    events.append(event)
                except (KeyError, TypeError, json.JSONDecodeError) as exc:
                    raise ValueError("evaluation journal corrupt") from exc
            yield stream, events


def _evaluation_append(stream, events, kind, payload):
    from . import forecast_feedback as registry
    event = {"type": kind, "payload": payload,
             "previous": registry._digest(events[-1]) if events else None}
    stream.seek(0, 2)
    stream.write((registry._json({"event": event, "sha256": registry._digest(event)}) + "\n").encode())
    registry._durable(stream)


def _evaluation_state(events):
    _eval_require(bool(events) and events[0]["type"] == "enrollment", "evaluation not enrolled")
    enrollment = events[0]["payload"]
    _eval_require(enrollment.get("schema") == "prospective-evaluation/v1", "unknown enrollment schema")
    spec = _evaluation_design(enrollment["design"], enrollment["enrolled_at"])
    _eval_require(spec == enrollment["design"], "enrollment contract mismatch")
    trials = {}
    keys = {(q["question_id"], a["id"]) for q in spec["questions"] for a in spec["arms"]}
    for event in events[1:]:
        row = event["payload"]
        key = (row.get("question_id"), row.get("arm"))
        _eval_require(key in keys, "unenrolled journal trial")
        if event["type"] == "disposition":
            _eval_require(key in trials and trials[key]["status"] == "published" and
                          "resolution_disposition" not in trials[key] and row["status"] in ("void", "disputed")
                          and row["costs_usd"] == trials[key]["costs_usd"], "invalid resolution disposition")
            trials[key] = {**trials[key], "resolution_disposition": row}
        else:
            _eval_require(event["type"] == "trial" and key not in trials, "invalid or duplicate evaluation trial")
            trials[key] = row
    return enrollment, trials


def enroll_evaluation(spec, *, path, ledger_dir=None):
    """Freeze a prospective design before dispatch. Repeating the same design is idempotent.

    The clock is captured here, not supplied by the operator. The declared earliest
    outcome time and family assignments require source review; this is no trusted
    timestamping service and cannot prove that an operator did not know an outcome.
    """
    from . import forecast_feedback as registry
    with _evaluation_journal(path, write=True) as (stream, events):
        if events:
            old, _ = _evaluation_state(events)
            _eval_require(_evaluation_design(spec, old["enrolled_at"]) == old["design"], "enrollment conflict")
            registry._durable(stream)
            return old
        now = _evaluation_now()
        row = {"schema": "prospective-evaluation/v1", "enrolled_at": now,
               "design": _evaluation_design(spec, now)}
        with _evaluation_unknown_settlements(row["design"]["questions"], ledger_dir):
            _evaluation_append(stream, events, "enrollment", row)
        return row


def _evaluation_publication(enrollment, question, row, ledger_dir):
    from . import forecast_feedback as registry
    publication = registry.read_published_forecast(row.get("report_id"), d=ledger_dir)
    _eval_require(publication is not None, "unpublished evaluation forecast")
    binary = next((b for b in publication["forecast"].get("binary_forecasts", [])
                   if b["id"] == row.get("forecast_id")), None)
    _eval_require(binary is not None, "unknown evaluation forecast")
    source = question["resolution_source"]
    anchor_key = "market_anchor" if source["kind"] == "market_binary" else "data_anchor"
    _eval_require(binary.get("statement") == question["statement"] and
                  binary.get("resolution_criteria") == question["resolution_criteria"] and
                  binary.get(anchor_key) == source["anchor"] and registry._lane(binary) == source["kind"],
                  "published question contract mismatch")
    deadline = binary.get("resolution_date")
    if source["kind"] == "market_binary":
        deadline = deadline or registry._due(binary, publication["forecast"])
        market_deadline = source["anchor"].get("endDate")
        if market_deadline:
            _eval_require(registry._instant(market_deadline).date() == registry._instant(question["resolution_date"]).date(),
                          "market resolution deadline mismatch")
    _eval_require(deadline is not None and registry._instant(deadline, date_end=True) ==
                  registry._instant(question["resolution_date"], date_end=True), "published resolution deadline mismatch")
    _eval_require(registry._instant(enrollment["enrolled_at"]) <= registry._instant(publication["created_at"])
                  <= registry._instant(row["recorded_at"]) < registry._instant(question["forecast_due_at"]),
                  "publication must be bound before forecast deadline")
    if row.get("publication_sha256"):
        _eval_require(row["publication_sha256"] == publication["publication_sha256"], "publication binding mismatch")
    return publication, binary


def record_evaluation_trial(trial, *, path, ledger_dir=None):
    """Finalize one enrolled question/arm, retaining costs even on failure.

    Costs are disjoint cumulative USD components including all attempts, supplied
    by the operator. None explicitly means unknown, never zero. A final disposition
    or publication reference cannot later be replaced by a more favorable revision.
    A publication may receive one append-only void/disputed disposition with the
    same costs and an explicit reason; this withholds scoring, never changes its probability.
    """
    from . import forecast_feedback as registry
    row = registry._clone(trial)
    _eval_require(isinstance(row, dict), "trial must be an object")
    allowed = {"question_id", "arm", "status", "reason", "costs_usd", "report_id", "forecast_id",
               "evidence_sha256", "forecast_request_sha256"}
    _eval_require(set(row) <= allowed, "unknown trial fields; outcomes and timestamps are registry-owned")
    _eval_require(row.get("status") in _DISPOSITIONS, "invalid trial disposition")
    costs = row.get("costs_usd")
    _eval_require(isinstance(costs, dict) and set(costs) == set(EVALUATION_COST_COMPONENTS)
                  and all(v is None or _eval_number(v) for v in costs.values()), "complete cost components required")
    _eval_require(math.isfinite(sum(v for v in costs.values() if v is not None)), "non-finite total cost")
    with _evaluation_journal(path, write=True) as (stream, events):
        enrollment, trials = _evaluation_state(events)
        spec = enrollment["design"]
        question = next((q for q in spec["questions"] if q["question_id"] == row.get("question_id")), None)
        _eval_require(question is not None and row.get("arm") in [a["id"] for a in spec["arms"]], "unenrolled trial")
        key = (row["question_id"], row["arm"])
        if key in trials:
            old = trials[key]
            disposition = old.get("resolution_disposition")
            if old["status"] == "published" and row["status"] in ("void", "disputed"):
                _eval_require(set(row) == {"question_id", "arm", "status", "reason", "costs_usd"}
                              and row["costs_usd"] == old["costs_usd"], "disposition must preserve publication costs")
                registry._identity(row["reason"])
                if disposition:
                    _eval_require({k: v for k, v in disposition.items() if k != "recorded_at"} == row,
                                  "resolution disposition conflict")
                    registry._durable(stream)
                    return disposition
                row["recorded_at"] = _evaluation_now()
                _eval_require(registry._instant(row["recorded_at"]) >= registry._instant(old["recorded_at"]),
                              "disposition predates publication binding")
                _evaluation_append(stream, events, "disposition", row)
                return row
            _eval_require({k: v for k, v in old.items() if k not in
                           ("recorded_at", "publication_sha256", "resolution_disposition")} == row,
                          "trial conflict; revisions cannot replace enrolled predictions")
            registry._durable(stream)
            return old
        row["recorded_at"] = _evaluation_now()
        _eval_require(registry._instant(row["recorded_at"]) >= registry._instant(enrollment["enrolled_at"]),
                      "trial predates enrollment")
        if row["status"] == "published":
            for field in ("evidence_sha256", "forecast_request_sha256"):
                value = row.get(field)
                _eval_require(isinstance(value, str) and len(value) == 64 and
                              all(c in "0123456789abcdef" for c in value), "SHA256 receipts required")
            publication, _ = _evaluation_publication(enrollment, question, row, ledger_dir)
            _eval_require(not any(o["forecast_id"] == row["forecast_id"] for o in
                                  registry.read_published_resolutions(row["report_id"], d=ledger_dir)),
                          "cannot bind an already resolved publication")
            _eval_require(not any((r.get("report_id"), r.get("forecast_id")) ==
                                  (row["report_id"], row["forecast_id"]) for r in trials.values()),
                          "publication already assigned to another trial")
            row["publication_sha256"] = publication["publication_sha256"]
            with _evaluation_unknown_settlements([question], ledger_dir):
                _evaluation_append(stream, events, "trial", row)
            return row
        else:
            registry._identity(row.get("reason"))
            _eval_require(not any(k in row for k in ("report_id", "forecast_id", "evidence_sha256",
                                                    "forecast_request_sha256")), "disposition cannot carry a prediction")
        _evaluation_append(stream, events, "trial", row)
        return row


def evaluation_report(*, path, ledger_dir=None):
    """Read-only full-denominator join to admitted registry outcomes.

    Families are the aggregation unit for paired deltas; no confidence interval,
    significance, or superiority claim is inferred from this bounded pilot.
    """
    from . import forecast_feedback as registry
    with _evaluation_journal(path) as (_, events):
        enrollment, trials = _evaluation_state(events)
    spec, now = enrollment["design"], _evaluation_now()
    arms, rows = {}, []
    for arm in spec["arms"]:
        arm_rows = []
        for question in spec["questions"]:
            trial = trials.get((question["question_id"], arm["id"]))
            row = {"id": question["question_id"], "event_family_id": question["event_family_id"],
                   "contract_sha256": question["contract_sha256"], "arm": arm["id"],
                   "status": "pending", "cost_usd": None, "costs_usd": None, "known_cost_usd": 0}
            if trial:
                row.update(status=trial["status"], reason=trial.get("reason"), costs_usd=trial["costs_usd"])
                row["known_cost_usd"] = sum(v for v in trial["costs_usd"].values() if v is not None)
                if all(v is not None for v in trial["costs_usd"].values()):
                    row["cost_usd"] = sum(trial["costs_usd"].values())
                if trial["status"] == "published":
                    _, binary = _evaluation_publication(enrollment, question, trial, ledger_dir)
                    row.update(probability=binary["probability"], report_id=trial["report_id"],
                               forecast_id=trial["forecast_id"], status="unresolved",
                               evidence_sha256=trial["evidence_sha256"],
                               forecast_request_sha256=trial["forecast_request_sha256"])
                    outcomes = registry.read_published_resolutions(trial["report_id"], d=ledger_dir)
                    outcome = next((o for o in outcomes if o["forecast_id"] == trial["forecast_id"]), None)
                    if outcome:
                        if registry._instant(outcome["resolved_at"]) < registry._instant(question["outcome_not_before"]):
                            row.update(status="disputed", reason="outcome_before_declared_availability")
                        elif question["resolution_source"]["kind"] == "official_data_binary" and (
                            outcome["evidence"].get("vintage") != question["resolution_source"]["outcome_vintage"]
                        ):
                            row.update(status="disputed", reason="outcome_vintage_mismatch")
                        elif registry._instant(outcome["resolved_at"], date_end=True) <= registry._instant(now):
                            # Reuse the registry's admitted boolean and score, never a legacy candidate or price.
                            row.update(status="resolved", outcome=outcome["outcome"], brier=outcome["score"]["brier"])
                    if trial.get("resolution_disposition"):
                        disposition = trial["resolution_disposition"]
                        row.update(status=disposition["status"], reason=disposition["reason"])
                        row.pop("outcome", None)
                        row.pop("brier", None)
            if row["status"] in ("pending", "unresolved"):
                deadline = question["forecast_due_at"] if row["status"] == "pending" else question["resolution_date"]
                if registry._instant(now) > registry._instant(deadline, date_end=True):
                    row["status"] = "overdue"
            arm_rows.append(row)
        rows.extend(arm_rows)
        known = [r["cost_usd"] for r in arm_rows if r["cost_usd"] is not None]
        arms[arm["id"]] = {"enrolled": len(arm_rows), "dispositions": dict(Counter(r["status"] for r in arm_rows)),
                            "resolved": sum(r["status"] == "resolved" for r in arm_rows),
                            "known_cost_usd": sum(r["known_cost_usd"] for r in arm_rows),
                            "unknown_cost_trials": len(arm_rows) - len(known),
                            "over_budget_trials": sum(r["known_cost_usd"] > arm["budget_usd"] for r in arm_rows)}
    contrast = spec["contrast"]
    pairs, exclusions, families, invariant_checks = [], [], {}, []
    index = {(r["id"], r["arm"]): r for r in rows}
    for question in spec["questions"]:
        base, candidate = (index[(question["question_id"], contrast[k])] for k in ("baseline", "candidate"))
        reason = None
        if contrast["kind"] == "same_evidence_diagnostic":
            checked = all("probability" in r for r in (base, candidate))
            invariant_checks.append({"question_id": question["question_id"], "checked": checked,
                                     "same_evidence": checked and base["evidence_sha256"] == candidate["evidence_sha256"],
                                     "same_request": checked and base["forecast_request_sha256"] == candidate["forecast_request_sha256"],
                                     "same_probability": checked and base["probability"] == candidate["probability"]})
            continue
        if base["status"] != "resolved" or candidate["status"] != "resolved":
            reason = "incomplete_outcomes"
        elif base["outcome"] != candidate["outcome"]:
            reason = "conflicting_outcomes"
        elif any(r["cost_usd"] is None for r in (base, candidate)):
            reason = "unknown_total_cost"
        elif any(r["cost_usd"] > next(a["budget_usd"] for a in spec["arms"] if a["id"] == r["arm"])
                 for r in (base, candidate)):
            reason = "over_budget"
        elif abs(base["cost_usd"] - candidate["cost_usd"]) > contrast["cost_tolerance_usd"]:
            reason = "unequal_total_cost"
        elif contrast["kind"] == "equal_cost_diagnostic" and base["probability"] != candidate["probability"]:
            reason = "diagnostic_probabilities_changed"
        if reason:
            exclusions.append({"question_id": question["question_id"], "reason": reason})
        else:
            delta = candidate["brier"] - base["brier"]
            pairs.append(question["question_id"])
            families.setdefault(question["event_family_id"], []).append(delta)
    family_deltas = {f: sum(ds) / len(ds) for f, ds in families.items()}
    diagnostic = contrast["kind"] != "equal_cost_investigation"
    comparison = {**contrast, "diagnostic_only": diagnostic, "probability_lift_established": False,
                  "enrolled_pairs": len(spec["questions"]), "eligible_pairs": len(pairs),
                  "eligible_event_families": len(family_deltas), "excluded_pairs": exclusions,
                  "invariance": invariant_checks,
                  "family_brier_deltas": {} if diagnostic else family_deltas,
                  "mean_family_brier_delta": None if diagnostic or not family_deltas else
                      sum(family_deltas.values()) / len(family_deltas),
                  "interpretation": "Diagnostic-only comparison; cannot imply probability lift." if diagnostic else
                      "Descriptive paired scores at matched recorded total cost; no statistical superiority claim. "
                      "Missing, failed and unpaired cases remain in the enrollment denominator."}
    return {"mode": "prospective-evaluation", "generated_at": now, "enrollment": enrollment,
            "enrolled_questions": len(spec["questions"]), "enrolled_trials": len(rows),
            "event_families": len({q["event_family_id"] for q in spec["questions"]}),
            "arms": arms, "questions": rows, "comparison": comparison,
            "limitations": ["Declared family membership and earliest outcome availability require source review.",
                            "Cost and evidence/request receipts are operator supplied, not independently metered.",
                            "Registry admission remains the outcome-quality authority; no new adjudication is performed.",
                            "Question-level scores are descriptive; correlated revisions are not independent samples.",
                            "Enrollment integrity is local, not an external trusted timestamp or live skill validation."]}
