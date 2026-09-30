#!/usr/bin/env python3
"""Golden-question forecast-quality evaluation harness (EVAL-1).

WHY THIS EXISTS — full pytest can go green while the pipeline quietly produces
WORSE forecasts (vaguer, over-hedged, mis-calibrated). Unit tests check code
shape; they cannot tell you whether a 70% actually happens ~70% of the time.
This harness turns forecast quality into a NUMBER against ground truth: it scores
the pipeline's binary_forecasts against a curated set of REAL, already-resolved
2024-2025 yes/no questions (``backend/tests/eval/golden_questions.json``) and
emits Brier score, logarithmic score, calibration bins + ECE, resolution
accuracy, and per-category / per-difficulty breakdowns — so you can compare
``eval_report.json`` across code versions and SEE whether a change helped.

Relation to ``eval_forecast_quality.py`` (I-7-7): that harness is an LLM-JUDGE
rubric scorer for report *prose* (groundedness/coverage/…). THIS harness is a
purely-deterministic, offline OUTCOME scorer — no LLM, no network — that grades
probabilities against known truth. They are complementary, not duplicative.

INTENDED WORKFLOW (the whole point — read this before using):
  1. For each golden question, build a research brief from
     ``app.services.golden_set.forecaster_view(q)`` only (id, question,
     resolution_criteria, as_of_date; every other field is grader-only and
     answer-bearing) and run the pipeline framed at the question's ``as_of_date``.
     ``as_of_date`` is the forecast origin, not a model knowledge cutoff.
     Pass it as the run's ``as_of`` (TIME-7): ``PipelineOrchestrator.start(brief,
     as_of=q["as_of_date"], ...)`` or the ``as_of`` field of POST
     /api/research/run and /api/v1/run. It needs HINDCAST_ENABLED=true and
     RESEARCH_ENGINE=v3; otherwise the run is refused, never run live. A
     hindcast pins ``hindcast_policy_v1``: v3 research dated to as_of (the brief
     carries a point-in-time rule and fetched pages are labelled LIVE PAGE),
     prediction markets withheld in research and report (live odds leak the
     outcome), and the graph anchored at the pin. Without an ``evaluation``
     context it is an evaluation run with eval_run_id ``hindcast_<YYYYMMDD>``.
     Retrieval is labelled, not clamped (search is unbounded, pages are served
     as they are now), and the models may already know the outcome, so every
     hindcast is characterization-only (ADR 0002 I-21), never a fair as-of
     forecast. A replay started without ``as_of`` (for example with only the
     ``evaluation`` context of step 2) is a live run: it must set
     PREDICTION_MARKETS_ENABLED=false, because live Polymarket odds leak the
     outcome.
  2. Start the run as an evaluation run (EVAL-13):
     ``PipelineOrchestrator.start(brief, evaluation={"eval_run_id": ..., "target":
     evaluation_target_from_golden(q)})``. Its reports never read production
     calibration or write the production ledger (their rows go to the isolated
     evaluation ledger), the resolution monitor skips them, and the binary whose
     statement equals the question carries ``target_question_id`` (or the
     question is listed under ``forecast.evaluation.target_binding.missing``);
     matching prefers ``target_question_id`` over the row's F id. Without a
     target, set each produced binary forecast's ``id`` to the golden question's
     ``id``.
  3. Score the pipeline's primary report ``forecast.json`` (with
     N_FORECAST_SEEDS>1 the seed members are diagnostics, not the scored
     artifact) against the golden set, naming the run that produced it:
         python backend/scripts/golden_eval.py score-forecast-file \
             --forecast backend/uploads/reports/<report_id>/forecast.json \
             --pipeline-dir backend/uploads/pipelines/<pipeline_id> \
             -o eval_report.json --markdown eval_report.md [--bootstrap 1000] \
             [--require-headline]
  4. Commit ``eval_report.json`` and DIFF it across code versions. Read the
     ``headline`` (EVAL-8, below) first, then the ``metrics.rigor`` block (EVAL-7)
     before the raw numbers: the golden set is
     imbalanced (24/30 YES), so a constant base-rate forecast already scores the
     climatology Brier and always-YES earns 80% resolution accuracy with MCC 0.
     BSS vs climatology, MCC, hedge share and the optional question-clustered
     bootstrap CI (``--bootstrap B``) say whether a difference is skill or noise.
     The set is answer-bearing and resolved before current model cutoffs, so
     every report is characterization only (``promotion_eligible: false``,
     ADR 0002 I-21) — never a gate for promoting a version.

  Optional — accumulate golden outcomes into the calibration ledger so
  ``report_visualizer`` calibration curves grow over time (opt-in; default OFF so
  the read-only scorer never pollutes the production ledger):
         GOLDEN_EVAL_LEDGER=true python backend/scripts/golden_eval.py \
             score-forecast-file --forecast <...>/forecast.json --to-ledger

  Score everything already recorded in the forecast ledger (real pipeline
  resolutions from the production ledger; the golden section reads the isolated
  evaluation ledger that ``--to-ledger`` writes to, or ``--eval-ledger-dir``):
         python backend/scripts/golden_eval.py score-ledger -o ledger_eval.json
  Its top-level ``mean_brier`` is the multi-class sum over scenarios
  (``brier_scale: multiclass_sum``, 2x the binary Brier for YES/NO rows); the
  golden section is binary (``golden.brier_scale: binary``).

HEADLINE TIERS (EVAL-8, GOLDEN_HEADLINE_GATE, default on): a Brier over rows the
run could look up is recall, not skill. Each matched row gets a ``tier`` from the
run's provenance (``--pipeline-dir``: run.json ``created_at``, else
pipeline_state.json ``created_at``, plus the TIME-7 hindcast pin; or
``--run-created-at`` with a UTC offset), compared on UTC dates (``classify_tier``):
``prospective`` (run before the resolution date and no later than as_of_date +
GOLDEN_PROSPECTIVE_LEAD_TOLERANCE_DAYS), ``late_origin`` (before resolution, after
that window), ``hindcast_retrieval_exposed`` (run on or after the resolution date:
live-web research at as_of = today and model memory both see the outcome),
``hindcast_pit`` (a pinned hindcast run, whatever the dates; TIME-9's integrity
verdict is recorded) or ``unknown`` (no usable provenance). ``headline`` scores the
prospective rows only (status ``ok``, else ``withheld_no_eligible_rows`` /
``withheld_no_provenance``); every other tier is under ``characterization.by_tier``;
``metrics`` still covers every matched row (``metrics_scope:
all_matched_characterization``). The markdown opens with a ``HEADLINE:`` or
``HEADLINE WITHHELD:`` line, and ``--require-headline`` exits 5 unless the status is
``ok``. Every question of the committed 2024-2025 set resolved before any run of
this code, so its headline is always withheld. ``--to-ledger`` stamps each row's
``golden_tier``; score-ledger builds its headline from ``golden_tier ==
'prospective'`` rows (rows without the key are ``unknown``).
Deferred (no evidence yet; inert until point-in-time research exists): a
``model_knowledge_cutoffs`` registry with post_cutoff / straddles tiers,
``--reclassify``, a ``harvest-holdout`` refill, ``list_closed_markets`` and an AS_OF
prompt block.

Golden files declaring ``_meta.schema_version: 2`` (EVAL-9) are also checked
against the v2 contract on load (``golden_set.validate_question``: outcome-free
visible text, UTC resolve_time after the as_of day, ...), and their rows with
``scoring_status: ambiguous`` are never scored (``exclusions.ambiguous``). In any
file, an evidence-backed row whose recomputed label disagrees with its record
fails loudly (exit 4).
``backend/scripts/golden_curate.py audit`` reports the same checks plus a
balance audit without scoring anything.

This script NEVER runs the pipeline itself — it only scores its outputs.

The pure scoring core (brier / log-score / ECE bins / matching / breakdowns) is
side-effect-free and offline-unit-tested (backend/tests/test_golden_eval.py); the
rigor statistics live in ``app/services/eval_stats.py`` (test_eval_stats.py).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import eval_stats, golden_set, hindcast_policy  # noqa: E402
from app.utils.atomic import write_json_atomic, write_text_atomic  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVAL_DIR = os.path.join(REPO_ROOT, "backend", "tests", "eval")
GOLDEN_PATH = os.path.join(EVAL_DIR, "golden_questions.json")

DEFAULT_BINS = 10          # calibration bins over [0,1]
_EPS = 1e-9                # log-score clamp so ln() never blows up on p∈{0,1}

# EVAL-7: every golden report is characterization only. The set carries its
# answers inline, every question resolved before current model cutoffs, and the
# replay pipeline researches the live web with as_of = today, so a score here can
# never be a skill estimate or promote a version (ADR 0002 I-21).
CHARACTERIZATION_BANNER = ("Characterization only - answer-bearing golden set; "
                           "not a skill estimate (ADR 0002 I-21)")
ANSWER_BEARING_CAVEAT = ("answer-bearing golden set resolved before current model cutoffs; "
                         "replay research is live-web with as_of = today: "
                         "characterization only (ADR 0002 I-21)")
# EVAL-8: replaces ANSWER_BEARING_CAVEAT in the headline metrics, which cover only
# prospective rows (see classify_tier).
HEADLINE_CAVEAT = ("prospective rows only: each run started before its question's resolution date "
                   "and within the lead tolerance of its as_of (an event decided inside that window "
                   "could still be visible); promotion stays off (ADR 0002 I-21)")
BOOTSTRAP_METHOD = "question-clustered percentile bootstrap"
BOOTSTRAP_SEED = eval_stats.DEFAULT_BOOTSTRAP_SEED
# Two-sided alpha of the bootstrap percentile CI (95%). It is also the largest
# share of BSS replicates that may lack a reference before the BSS interval is
# withheld (see rigor_ci).
BOOTSTRAP_ALPHA = 0.05
# EVAL-9: exit status when an evidence-backed golden row's recomputed label
# disagrees with its recorded outcome (3 stays "nothing matched").
EXIT_RECOMPUTE_MISMATCH = 4
# EVAL-8: exit status of --require-headline when the headline status is not "ok".
EXIT_HEADLINE_WITHHELD = 5

# EVAL-8 headline tiers (see classify_tier), in the canonical order of tier_counts,
# characterization.by_tier and the markdown tier table. Only prospective rows are
# headline-eligible.
TIER_PROSPECTIVE = "prospective"
TIER_LATE_ORIGIN = "late_origin"
TIER_HINDCAST_EXPOSED = "hindcast_retrieval_exposed"
TIER_HINDCAST_PIT = "hindcast_pit"
TIER_UNKNOWN = "unknown"
TIERS = (TIER_PROSPECTIVE, TIER_LATE_ORIGIN, TIER_HINDCAST_EXPOSED, TIER_HINDCAST_PIT, TIER_UNKNOWN)
HEADLINE_OK = "ok"
HEADLINE_NO_ELIGIBLE_ROWS = "withheld_no_eligible_rows"
HEADLINE_NO_PROVENANCE = "withheld_no_provenance"
HEADLINE_GATE_DISABLED = "gate_disabled"
# What the legacy top-level ``metrics`` block covers once the headline exists.
METRICS_SCOPE = "all_matched_characterization"
DEFAULT_LEAD_TOLERANCE_DAYS = 7
# The run provenance files of a pipeline directory (PipelineManager.manifest_path /
# state_path); run.json is preferred for created_at.
RUN_MANIFEST_FILE = "run.json"
PIPELINE_STATE_FILE = "pipeline_state.json"
FORECAST_FILE_SOURCE = "forecast.json"
RUN_CREATED_AT_ARG = "--run-created-at"
# Markdown banner wording of each withheld tier.
_TIER_BANNER = {
    TIER_LATE_ORIGIN: "late origin (run started after as_of + the lead tolerance)",
    TIER_HINDCAST_EXPOSED: "hindcast (live retrieval + model memory exposed)",
    TIER_HINDCAST_PIT: "point-in-time hindcast (model memory exposed)",
    TIER_UNKNOWN: "unknown provenance",
}


# ============================================================ pure scoring core
# Everything in this block is deterministic and side-effect-free (no LLM, no
# network, no disk) so it can be unit-tested offline.

def _coerce_prob(v: Any) -> Optional[float]:
    """Coerce a value to a probability in [0,1]; None on garbage/NaN/inf/out-of-range."""
    try:
        p = float(v)
    except (TypeError, ValueError):
        return None
    if p != p or p in (float("inf"), float("-inf")):
        return None
    if p < 0.0 or p > 1.0:
        return None
    return p


def binary_brier(p: float, outcome: bool) -> float:
    """Binary Brier score for a single YES-probability vs a boolean outcome.

    (p − y)² where y=1 if the event happened (YES) else 0. Range [0,1], LOWER=better.
    """
    y = 1.0 if outcome else 0.0
    return (float(p) - y) ** 2


def binary_log_score(p: float, outcome: bool, eps: float = _EPS) -> float:
    """Logarithmic score = ln(probability assigned to the REALIZED outcome).

    ln(p) if YES happened else ln(1−p). Range (−∞, 0], HIGHER (closer to 0)=better.
    p is clamped to [eps, 1−eps] so a confidently-wrong 0/1 forecast gets a large
    finite penalty instead of −∞.
    """
    p = min(1.0 - eps, max(eps, float(p)))
    po = p if outcome else (1.0 - p)
    return math.log(po)


def calibration_bins(pairs: List[Tuple[float, bool]], bins: int = DEFAULT_BINS) -> Dict[str, Any]:
    """Reliability-diagram bins + Expected Calibration Error over (p_yes, outcome) pairs.

    Each YES-probability is dropped into one of ``bins`` equal-width buckets on
    [0,1]; per bucket we compare the mean predicted probability to the observed
    YES frequency. ECE = Σ (n_k/N)·|mean_pred_k − observed_k| (count-weighted).
    Returns ``{ece, n, bins:[{range,count,mean_predicted,observed_frequency,gap}]}``.
    """
    bins = max(1, int(bins))
    buckets = [{"preds": [], "hits": []} for _ in range(bins)]
    for p, y in pairs:
        pp = _coerce_prob(p)
        if pp is None:
            continue
        idx = min(bins - 1, max(0, int(pp * bins)))
        buckets[idx]["preds"].append(pp)
        buckets[idx]["hits"].append(1.0 if y else 0.0)

    total = sum(len(b["preds"]) for b in buckets)
    bin_out: List[Dict[str, Any]] = []
    ece_terms: List[Tuple[int, float]] = []
    for i, b in enumerate(buckets):
        n = len(b["preds"])
        lo, hi = i / bins, (i + 1) / bins
        if n:
            mean_pred = sum(b["preds"]) / n
            observed = sum(b["hits"]) / n
            gap = abs(mean_pred - observed)
            ece_terms.append((n, gap))
        else:
            mean_pred = observed = gap = None
        bin_out.append({
            "range": [round(lo, 3), round(hi, 3)],
            "count": n,
            "mean_predicted": round(mean_pred, 4) if mean_pred is not None else None,
            "observed_frequency": round(observed, 4) if observed is not None else None,
            "gap": round(gap, 4) if gap is not None else None,
        })
    ece = round(sum(w * g for w, g in ece_terms) / total, 4) if total else None
    return {"ece": ece, "n": total, "bins": bin_out}


def score_pairs(scored: List[Dict[str, Any]], bins: int = DEFAULT_BINS,
                threshold: float = 0.5) -> Dict[str, Any]:
    """Aggregate metrics over matched, scored questions.

    ``scored`` items: ``{id, probability, outcome(bool), category, difficulty}``.
    Returns overall Brier / log-score / resolution-accuracy / ECE + calibration
    bins + per-category and per-difficulty breakdowns. A forecast is "resolution
    correct" when (probability >= threshold) equals the actual outcome.

    EVAL-7 adds ``rigor`` (see ``rigor_block``); every legacy key and value is
    unchanged.
    """
    if not scored:
        return {"n": 0, "mean_brier": None, "mean_log_score": None,
                "resolution_accuracy": None, "base_rate": None,
                "calibration": calibration_bins([], bins),
                "by_category": {}, "by_difficulty": {},
                "rigor": rigor_block([])}
    briers, logs, correct, hits = [], [], 0, 0
    pairs: List[Tuple[float, bool]] = []
    for s in scored:
        p, y = float(s["probability"]), bool(s["outcome"])
        briers.append(binary_brier(p, y))
        logs.append(binary_log_score(p, y))
        pred_yes = p >= threshold
        correct += 1 if pred_yes == y else 0
        hits += 1 if y else 0
        pairs.append((p, y))
    n = len(scored)
    out: Dict[str, Any] = {
        "n": n,
        "mean_brier": round(sum(briers) / n, 4),
        "mean_log_score": round(sum(logs) / n, 4),
        "resolution_accuracy": round(correct / n, 4),
        "base_rate": round(hits / n, 4),
        "calibration": calibration_bins(pairs, bins),
        "by_category": _breakdown(scored, "category", threshold),
        "by_difficulty": _breakdown(scored, "difficulty", threshold),
        "rigor": rigor_block(scored),
    }
    return out


def _breakdown(scored: List[Dict[str, Any]], field: str, threshold: float) -> Dict[str, Any]:
    """Per-group {n, mean_brier, resolution_accuracy, base_rate} keyed by ``field``."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for s in scored:
        key = str(s.get(field) or "unknown")
        groups.setdefault(key, []).append(s)
    out: Dict[str, Any] = {}
    for key in sorted(groups):
        rows = groups[key]
        n = len(rows)
        briers = [binary_brier(float(r["probability"]), bool(r["outcome"])) for r in rows]
        correct = sum(1 for r in rows if (float(r["probability"]) >= threshold) == bool(r["outcome"]))
        hits = sum(1 for r in rows if bool(r["outcome"]))
        out[key] = {
            "n": n,
            "mean_brier": round(sum(briers) / n, 4),
            "resolution_accuracy": round(correct / n, 4),
            "base_rate": round(hits / n, 4),
        }
    return out


def _row_horizon_days(row: Dict[str, Any]) -> Optional[int]:
    """Matched rows carry ``horizon_days``; ledger/synthetic rows derive it from their dates."""
    if "horizon_days" in row:
        return row.get("horizon_days")
    return eval_stats.horizon_days(row.get("as_of_date"), row.get("resolution_date"))


def rigor_block(scored: List[Dict[str, Any]]) -> Dict[str, Any]:
    """EVAL-7 honesty layer over matched, scored questions (additive to the legacy metrics).

    - ``reference``: base rate, climatology Brier ybar(1-ybar), BSS vs climatology
      and vs a constant 0.5. With 24/30 YES a constant 0.8 already matches
      climatology, so a raw Brier is unreadable without this reference.
    - ``direction``: YES/NO calls at 0.5 with exact ties excluded (the legacy
      ``resolution_accuracy`` keeps p >= 0.5 as YES), MCC, hedge share, confident
      misses.
    - ``by_horizon``: le30 / d31_180 / gt180 strata (``unknown`` without dates).
    - ``category_flags``: categories too small to rank, and single-outcome
      categories (no BSS: degenerate reference).
    - ``caveats``: deterministic strings, rendered in JSON and markdown. The
      size caveat reads ``n = N questions in C clusters``, or ``n = N rows
      (Q distinct questions) ...`` when question ids repeat (ledger input).
    - ``promotion_eligible`` is always False (ADR 0002 I-21).
    """
    rows = [dict(r, horizon_bucket=eval_stats.horizon_bucket(_row_horizon_days(r))) for r in scored]
    n = len(rows)
    n_clusters = len(eval_stats.group_clusters(rows, "cluster"))
    # A forecast file is de-duplicated by match_forecasts, but the append-only
    # ledger can hold one golden question several times (score-ledger scores every
    # row); count distinct ids so the caveat never calls repeats "questions".
    n_questions = len(eval_stats.group_clusters(rows, lambda r: r.get("id")))
    direction = eval_stats.direction_stats(rows)
    categories = eval_stats.strata_stats(rows, "category", min_n=eval_stats.MIN_STRATUM_N)
    small = [key for key, v in categories.items() if v["small"]]
    single = [key for key, v in categories.items() if v["single_outcome"]]
    caveats: List[str] = []
    if n:
        hits = sum(1 for r in rows if r["outcome"])
        ybar = hits / n
        caveats.append(f"base rate {ybar:.2f} ({hits}/{n}): a constant {ybar:.2f} forecast "
                       f"scores Brier {ybar * (1.0 - ybar):.3f} - read BSS")
    caveats.append(ANSWER_BEARING_CAVEAT)
    if n_questions == n:
        caveats.append(f"n = {n} questions in {n_clusters} clusters")
    else:
        caveats.append(f"n = {n} rows ({n_questions} distinct questions) in {n_clusters} clusters: "
                       "a repeated question id is scored once per row, so repeats weigh on "
                       "n, the base rate and every mean")
    if direction["ties"]:
        caveats.append(f"{direction['ties']} forecast(s) at exactly p = 0.5: excluded from direction "
                       "and MCC; the legacy resolution_accuracy counts p >= 0.5 as YES")
    if small:
        caveats.append(f"categories with n < {eval_stats.MIN_STRATUM_N} are too small to rank: "
                       + ", ".join(small))
    if single:
        caveats.append("single-outcome categories have no Brier skill (degenerate_reference): "
                       + ", ".join(single))
    horizons = eval_stats.strata_stats(rows, "horizon_bucket", min_n=eval_stats.MIN_STRATUM_N)
    return {
        "n": n,
        "reference": eval_stats.reference_scores(rows),
        "direction": direction,
        "by_horizon": {key: horizons[key] for key in eval_stats.horizon_bucket_labels() if key in horizons},
        "category_flags": {"min_n": eval_stats.MIN_STRATUM_N, "small": small, "single_outcome": single},
        "n_clusters": n_clusters,
        "caveats": caveats,
        "promotion_eligible": False,
    }


def _bss_stat(rows: List[Dict[str, Any]]) -> Optional[float]:
    return eval_stats.brier_skill(eval_stats.mean_brier(rows),
                                  eval_stats.climatology_brier(r["outcome"] for r in rows))


def rigor_ci(scored: List[Dict[str, Any]], B: int, seed: int = BOOTSTRAP_SEED) -> Dict[str, Any]:
    """``metrics.rigor.ci`` for ``--bootstrap B``: question-clustered percentile 95% CIs.

    Unstratified: whole clusters (golden ``event_cluster``, else the question id)
    are resampled with replacement, so linked questions move together; stratifying
    by category at 3-7 clusters per stratum would understate the variance. Brier
    and BSS use the same seed, hence the same resamples. A BSS replicate whose
    resample has a single outcome has no reference; it is counted in
    ``bss_degenerate_replicates`` instead of being dropped silently. The BSS
    percentile interval is taken over the other replicates, so it is conditional
    on the resample having both outcomes; when more than ``BOOTSTRAP_ALPHA`` of
    the replicates are degenerate that conditional interval is no longer a 95%
    CI (with 2 clusters it can collapse to a single point), so it is withheld
    (fail closed). ``reason`` explains a null interval (``fewer_than_2_clusters``
    for both, or ``degenerate_reference`` for BSS).
    """
    B = int(B)
    n_clusters = len(eval_stats.group_clusters(scored, "cluster"))
    brier = eval_stats.cluster_bootstrap_ci(scored, eval_stats.mean_brier, "cluster", B, seed,
                                            alpha=BOOTSTRAP_ALPHA)
    bss_reps = eval_stats.cluster_bootstrap_replicates(scored, _bss_stat, "cluster", B, seed)
    degenerate: Optional[int] = None
    bss: Optional[List[float]] = None
    if bss_reps is not None:
        degenerate = sum(1 for v in bss_reps if v is None)
        if degenerate / B <= BOOTSTRAP_ALPHA:
            bss = eval_stats.percentile_interval(bss_reps, BOOTSTRAP_ALPHA)
    if n_clusters < 2:
        reason: Optional[str] = "fewer_than_2_clusters"
    elif bss is None:
        reason = eval_stats.DEGENERATE_REFERENCE
    else:
        reason = None
    return {
        "method": BOOTSTRAP_METHOD,
        "B": B,
        "seed": seed,
        "n_clusters": n_clusters,
        "brier": [eval_stats.round4(v) for v in brier] if brier else None,
        "bss": [eval_stats.round4(v) for v in bss] if bss else None,
        "bss_degenerate_replicates": degenerate,
        "reason": reason,
    }


def _check_tolerance(days: Any) -> int:
    """``days`` as a lead tolerance: an integer >= 0 (ValueError otherwise, fail loud)."""
    if isinstance(days, bool) or not isinstance(days, int) or days < 0:
        raise ValueError(f"lead tolerance must be an integer >= 0 days, got {days!r}")
    return days


def parse_run_created_at(value: Any) -> Tuple[Optional[datetime], Optional[str]]:
    """EVAL-8: a run creation stamp as an aware UTC datetime, else ``(None, reason)``.

    Strict: an ISO-8601 string with a UTC offset (``Z`` or ``+HH:MM``, as
    ``pipeline_orchestrator._utcnow`` writes it). A naive stamp is rejected: its
    zone is unknowable, and a shifted day can move a row across the as_of +
    tolerance or the resolution boundary.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "no run created_at"
    if not isinstance(value, str):
        return None, f"run created_at {value!r} is not an ISO-8601 string"
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None, f"run created_at {value!r} is not ISO-8601"
    if parsed.utcoffset() is None:
        return None, f"run created_at {value!r} has no UTC offset (naive stamps are rejected)"
    try:
        return parsed.astimezone(timezone.utc), None
    except OverflowError:
        return None, f"run created_at {value!r} is out of range in UTC"


def classify_tier(q: Dict[str, Any], *, run_created_at: Any, lead_tolerance_days: int,
                  hindcast: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """EVAL-8: the headline tier of one golden row, ``{'tier', 'reasons'}``.

    ``q`` needs canonical ``as_of_date`` / ``resolution_date``; the run date is the
    UTC date of ``run_created_at`` (see ``parse_run_created_at``). In order:

    - ``hindcast_pit``: ``hindcast`` is set (the run was pinned as a TIME-7
      hindcast), whatever the dates; the result also carries TIME-9's
      ``integrity`` verdict when the pin records one.
    - ``unknown``: no usable run stamp, or no canonical resolution date.
    - ``hindcast_retrieval_exposed``: run date >= resolution date; the run's
      live-web research (as_of = today) and the models' memory can see the outcome.
    - ``unknown``: no canonical as_of date.
    - ``late_origin``: before resolution, but after as_of + ``lead_tolerance_days``.
    - ``prospective``: before resolution and on or before as_of +
      ``lead_tolerance_days`` (keeps information sets comparable across code
      versions). Only this tier is headline-eligible.
    """
    tolerance = _check_tolerance(lead_tolerance_days)
    if hindcast is not None:
        out: Dict[str, Any] = {"tier": TIER_HINDCAST_PIT, "reasons": [
            f"run pinned as a point-in-time hindcast at as_of {hindcast.get('as_of') or 'unknown'} "
            f"({hindcast.get('source')}): characterization only"]}
        if hindcast.get("integrity"):
            out["integrity"] = hindcast["integrity"]
        return out
    run_at, why = parse_run_created_at(run_created_at)
    if run_at is None:
        return {"tier": TIER_UNKNOWN, "reasons": [why]}
    run_day = run_at.date()
    resolution = eval_stats.parse_iso_date(q.get("resolution_date"))
    if resolution is None:
        return {"tier": TIER_UNKNOWN, "reasons": ["question has no canonical resolution_date"]}
    if run_day >= resolution:
        return {"tier": TIER_HINDCAST_EXPOSED, "reasons": [
            f"run {run_day.isoformat()} is on or after resolution {resolution.isoformat()}: "
            "live retrieval and model memory can see the outcome"]}
    as_of = eval_stats.parse_iso_date(q.get("as_of_date"))
    if as_of is None:
        return {"tier": TIER_UNKNOWN, "reasons": ["question has no canonical as_of_date"]}
    latest = as_of + timedelta(days=tolerance)
    if run_day > latest:
        return {"tier": TIER_LATE_ORIGIN, "reasons": [
            f"run {run_day.isoformat()} is after as_of {as_of.isoformat()} + {tolerance} days "
            f"({latest.isoformat()})"]}
    return {"tier": TIER_PROSPECTIVE, "reasons": [
        f"run {run_day.isoformat()} precedes resolution {resolution.isoformat()} and is no later "
        f"than as_of {as_of.isoformat()} + {tolerance} days"]}


def summarize_tiers(rows: List[Dict[str, Any]], *, has_provenance: bool, bins: int = DEFAULT_BINS,
                    context: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """EVAL-8: ``(headline, characterization)`` over scored rows that carry ``tier``.

    ``headline``: ``status`` (``ok`` when any row is prospective, else
    ``withheld_no_provenance`` without provenance and ``withheld_no_eligible_rows``
    otherwise), ``tier_counts`` (every tier, canonical order), the ``context`` keys,
    and ``metrics`` = ``score_pairs`` over the prospective rows only (the n = 0
    block when withheld). ``characterization.by_tier``: ``score_pairs`` for each
    other tier that has rows. The headline caveats carry HEADLINE_CAVEAT in place of
    the all-matched ANSWER_BEARING_CAVEAT.
    """
    groups = {tier: [r for r in rows if r.get("tier") == tier] for tier in TIERS}
    prospective = groups[TIER_PROSPECTIVE]
    if prospective:
        status = HEADLINE_OK
    elif not has_provenance:
        status = HEADLINE_NO_PROVENANCE
    else:
        status = HEADLINE_NO_ELIGIBLE_ROWS
    headline: Dict[str, Any] = {"status": status, "tier_counts": {t: len(groups[t]) for t in TIERS}}
    headline.update(context or {})
    metrics = score_pairs(prospective, bins=bins)
    rigor = metrics["rigor"]
    rigor["caveats"] = [HEADLINE_CAVEAT if c == ANSWER_BEARING_CAVEAT else c for c in rigor["caveats"]]
    headline["metrics"] = metrics
    characterization = {"by_tier": {t: score_pairs(groups[t], bins=bins)
                                    for t in TIERS if t != TIER_PROSPECTIVE and groups[t]}}
    return headline, characterization


def headline_banner(headline: Dict[str, Any]) -> str:
    """The markdown's first line: ``HEADLINE: ...`` or ``HEADLINE WITHHELD: k/n <tier> ...``."""
    counts = headline.get("tier_counts") or {}
    n = sum(counts.values())
    if headline.get("status") == HEADLINE_OK:
        m = headline.get("metrics") or {}
        reference = (m.get("rigor") or {}).get("reference") or {}
        return (f"HEADLINE: mean Brier {_fmt(m.get('mean_brier'))} over "
                f"{counts.get(TIER_PROSPECTIVE, 0)}/{n} prospective rows "
                f"(BSS vs climatology {_fmt(reference.get('bss'))})")
    parts = [f"{counts[t]}/{n} {_TIER_BANNER[t]}" for t in TIERS if t != TIER_PROSPECTIVE and counts.get(t)]
    return "HEADLINE WITHHELD: " + ("; ".join(parts) if parts else "no scored rows")


def load_golden_file(path: str = GOLDEN_PATH) -> Tuple[int, List[Dict[str, Any]]]:
    """Load + validate a golden file; returns ``(schema_version, questions)``.

    Accepts either a top-level list or an object with a ``questions`` list. Each
    entry needs a non-empty ``id`` and a boolean ``resolved_outcome``; malformed
    entries raise ValueError (fail loud — a silently-dropped golden question
    would understate coverage).

    EVAL-9: a file declaring ``_meta.schema_version: 2`` also runs
    ``golden_set.validate_question`` (non-strict) on every row and raises
    ValueError naming the id on any error; there, a row with ``scoring_status:
    ambiguous`` needs no boolean outcome (validate_question governs it). In any
    file, an evidence-backed row whose recomputed label disagrees with its
    record raises ``golden_set.RecomputeMismatchError`` (a ValueError; ``main``
    exits 4). v1 rows carry no evidence, so v1 files keep exactly the checks above.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    questions = data.get("questions") if isinstance(data, dict) else data
    if not isinstance(questions, list) or not questions:
        raise ValueError(f"golden set {path} has no 'questions' list")
    version = golden_set.schema_version(data)
    v2 = version == golden_set.SCHEMA_VERSION
    for q in questions:
        if not isinstance(q, dict) or not str(q.get("id") or "").strip():
            raise ValueError(f"golden entry missing 'id': {q!r}")
        if v2 and golden_set.is_ambiguous(q):
            continue
        if not isinstance(q.get("resolved_outcome"), bool):
            raise ValueError(f"golden entry {q.get('id')!r} needs boolean 'resolved_outcome'")
    for q in questions:
        errors = golden_set.validate_question(q) if v2 else []
        if errors:
            raise ValueError(f"golden entry {q['id']!r} breaks the schema v2 contract: "
                             + "; ".join(errors))
        mismatch = golden_set.recompute_mismatch(q)
        if mismatch:
            raise golden_set.RecomputeMismatchError(f"golden entry {q['id']!r}: {mismatch}")
    return version, questions


def load_golden_set(path: str = GOLDEN_PATH) -> List[Dict[str, Any]]:
    """The validated golden questions of ``path`` (see ``load_golden_file``)."""
    return load_golden_file(path)[1]


def index_golden(questions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Index golden questions by (stripped) id.

    Duplicate ids raise ValueError (EVAL-7): two answer-key rows under one id
    would let the later one silently replace the earlier, scoring forecasts
    against an ambiguous outcome.
    """
    index: Dict[str, Dict[str, Any]] = {}
    duplicates: set = set()
    for q in questions:
        qid = str(q["id"]).strip()
        if qid in index:
            duplicates.add(qid)
        index[qid] = q
    if duplicates:
        raise ValueError(f"golden set has duplicate ids: {', '.join(sorted(duplicates))}")
    return index


def extract_binary_forecasts(forecast_obj: Any) -> List[Dict[str, Any]]:
    """Pull the binary_forecasts list out of a loaded forecast.json.

    Tolerates: the full forecast dict ({"binary_forecasts":[...]}), a bare list, or
    a wrapper with a nested "forecast". Non-dict rows are dropped.
    """
    if isinstance(forecast_obj, dict):
        items = forecast_obj.get("binary_forecasts")
        if items is None and isinstance(forecast_obj.get("forecast"), dict):
            items = forecast_obj["forecast"].get("binary_forecasts")
    elif isinstance(forecast_obj, list):
        items = forecast_obj
    else:
        items = None
    return [it for it in (items or []) if isinstance(it, dict)]


def _match_key(row: Dict[str, Any], golden_index: Dict[str, Dict[str, Any]]) -> str:
    """The golden id a forecast row answers: its ``target_question_id`` when that names a
    golden question (EVAL-13 target binding), else its own ``id``."""
    target = str(row.get("target_question_id") or "").strip()
    if target and target in golden_index:
        return target
    return str(row.get("id") or "").strip()


def match_forecasts(binary_forecasts: List[Dict[str, Any]],
                    golden_index: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Match forecast rows to golden questions by ``id``; score the intersection.

    EVAL-13: a row whose ``target_question_id`` names a golden question is matched
    on it in preference to its own (F-numbered) ``id``; such a matched row also
    carries ``forecast_id``, the row's own id.

    Returns ``{matched:[…scored…], unmatched_forecast_ids, unmatched_golden_ids,
    invalid_probability_ids, duplicate_forecast_ids}``. A matched row with an
    unparseable/out-of-range probability is reported under
    ``invalid_probability_ids`` (never silently kept).

    EVAL-7: only the FIRST row per golden id is considered; later rows with the
    same id are listed once under ``duplicate_forecast_ids`` and never scored, so
    a repeated id cannot be double-counted (and a later row cannot replace an
    invalid first one). Matched rows also carry ``cluster`` (golden
    ``event_cluster``, else the id), ``horizon_days`` (resolution_date minus
    as_of_date; None without canonical dates) and ``horizon_bucket``.

    EVAL-9: a golden row with ``scoring_status: ambiguous`` is never scored. Its id
    is listed under ``exclusions.ambiguous`` (whether or not a forecast names it)
    and in neither unmatched list, so an excluded row never reads as an id
    misalignment.
    """
    matched: List[Dict[str, Any]] = []
    matched_ids: set = set()
    invalid: List[str] = []
    seen: set = set()
    duplicates: set = set()
    ambiguous = {gid for gid, g in golden_index.items() if golden_set.is_ambiguous(g)}
    for row in binary_forecasts:
        fid = _match_key(row, golden_index)
        if not fid or fid not in golden_index or fid in ambiguous:
            continue
        if fid in seen:
            duplicates.add(fid)
            continue
        seen.add(fid)
        g = golden_index[fid]
        p = _coerce_prob(row.get("probability"))
        if p is None:
            invalid.append(fid)
            continue
        matched_ids.add(fid)
        h_days = eval_stats.horizon_days(g.get("as_of_date"), g.get("resolution_date"))
        entry = {
            "id": fid,
            "probability": p,
            "outcome": bool(g["resolved_outcome"]),
            "category": g.get("category"),
            "difficulty": g.get("difficulty"),
            "question": g.get("question"),
            "as_of_date": g.get("as_of_date"),
            "resolution_date": g.get("resolution_date"),
            "brier": round(binary_brier(p, bool(g["resolved_outcome"])), 4),
            "log_score": round(binary_log_score(p, bool(g["resolved_outcome"])), 4),
            "cluster": str(g.get("event_cluster") or "").strip() or fid,
            "horizon_days": h_days,
            "horizon_bucket": eval_stats.horizon_bucket(h_days),
        }
        own_id = str(row.get("id") or "").strip()
        if own_id != fid:
            entry["forecast_id"] = own_id
        matched.append(entry)
    forecast_ids = {key for key in (_match_key(r, golden_index) for r in binary_forecasts) if key}
    return {
        "matched": matched,
        "unmatched_forecast_ids": sorted(forecast_ids - matched_ids - set(invalid) - ambiguous),
        "unmatched_golden_ids": sorted(set(golden_index) - matched_ids - ambiguous),
        "invalid_probability_ids": sorted(invalid),
        "duplicate_forecast_ids": sorted(duplicates),
        "exclusions": {"ambiguous": sorted(ambiguous)},
    }


# ============================================================ run provenance (EVAL-8)
# Reads the run's own records; never the network. A hindcast is recognised from any
# of them (fail closed): the pipeline_state.json pin, run.json as_of_enforcement or
# the forecast's hindcast stamp.

def _read_json_object(path: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """``(object, None)`` for a JSON object file, else ``(None, why)``."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError) as exc:
        return None, f"unreadable ({exc.__class__.__name__})"
    if not isinstance(data, dict):
        return None, "not a JSON object"
    return data, None


def _integrity_of_audit_status(status: Any) -> str:
    """TIME-9 integrity for a run.json ``as_of_enforcement.audit_status``.

    That record carries ``audit_status`` only for a gated pin with a recognised
    research audit, so the verdict is mapped through the same
    ``hindcast_forecast_block`` that stamps a hindcast forecast (``labelled`` when
    there is none).
    """
    return hindcast_policy.hindcast_forecast_block(
        {"pit": {"gates": True}}, research_audit={"status": status})["integrity"]


def forecast_hindcast_stamp(forecast_obj: Any) -> Optional[Dict[str, Any]]:
    """The hindcast record of a forecast stamped ``hindcast`` by a pinned run (TIME-6), else None."""
    for obj in (forecast_obj, forecast_obj.get("forecast") if isinstance(forecast_obj, dict) else None):
        if isinstance(obj, dict) and obj.get("hindcast") is not None:
            block = obj["hindcast"] if isinstance(obj["hindcast"], dict) else {}
            return {"as_of": block.get("as_of"), "source": FORECAST_FILE_SOURCE,
                    "integrity": block.get("integrity")}
    return None


def load_pipeline_provenance(pipeline_dir: str) -> Dict[str, Any]:
    """EVAL-8: ``{run_created_at, source, hindcast, notes}`` from a pipeline directory.

    ``run_created_at`` is run.json's ``created_at`` (``_build_run_manifest``), else
    pipeline_state.json's, whichever first parses as a UTC-aware stamp (normalized
    to UTC ISO-8601); ``source`` names that file. ``hindcast`` is the TIME-7 pin in
    pipeline_state.json ``options.hindcast_policy_v1`` with TIME-9's integrity
    verdict (``hindcast_forecast_block`` over its ``research_audit``), or, when the
    state file cannot be read, run.json ``resolved.as_of_enforcement`` (written only
    for a pinned run). A pin value that is neither a hindcast pin nor a live
    (as-of = today) one cannot be ruled out, so the run stamp is withheld (every row
    ``unknown``). ``notes`` says why a file or stamp was not used. A path that is
    not a directory raises ValueError (a mistyped ``--pipeline-dir`` fails loud).
    """
    if not os.path.isdir(pipeline_dir):
        raise ValueError(f"--pipeline-dir {pipeline_dir!r} is not a directory")
    notes: List[str] = []
    docs: Dict[str, Optional[Dict[str, Any]]] = {}
    for name in (RUN_MANIFEST_FILE, PIPELINE_STATE_FILE):
        docs[name], why = _read_json_object(os.path.join(pipeline_dir, name))
        if why:
            notes.append(f"{name}: {why}")
    stamp: Optional[str] = None
    source: Optional[str] = None
    for name in (RUN_MANIFEST_FILE, PIPELINE_STATE_FILE):
        doc = docs[name]
        if doc is None:
            continue
        parsed, why = parse_run_created_at(doc.get("created_at"))
        if parsed is not None:
            stamp, source = parsed.isoformat(), name
            break
        notes.append(f"{name}: {why}")
    hindcast: Optional[Dict[str, Any]] = None
    state = docs[PIPELINE_STATE_FILE]
    if state is not None:
        options = state.get("options")
        raw = options.get(hindcast_policy.HINDCAST_POLICY_OPTION) if isinstance(options, dict) else None
        pin = hindcast_policy.hindcast_policy(options)
        live_pin = (isinstance(raw, dict) and raw.get("version") == hindcast_policy.HINDCAST_POLICY_VERSION
                    and raw.get("hindcast") is False)
        if pin is not None:
            block = hindcast_policy.hindcast_forecast_block(pin, research_audit=pin.get("research_audit"))
            hindcast = {"as_of": pin.get("as_of"), "source": PIPELINE_STATE_FILE,
                        "integrity": block["integrity"]}
        elif raw is not None and not live_pin:
            notes.append(f"{PIPELINE_STATE_FILE}: options.{hindcast_policy.HINDCAST_POLICY_OPTION} is not a "
                         "recognised pin, so a hindcast cannot be ruled out: run stamp withheld")
            stamp = source = None
    else:
        resolved = (docs[RUN_MANIFEST_FILE] or {}).get("resolved")
        enforcement = resolved.get("as_of_enforcement") if isinstance(resolved, dict) else None
        if isinstance(enforcement, dict):
            hindcast = {"as_of": enforcement.get("as_of"), "source": RUN_MANIFEST_FILE,
                        "integrity": _integrity_of_audit_status(enforcement.get("audit_status"))}
    return {"run_created_at": stamp, "source": source, "hindcast": hindcast, "notes": notes}


def resolve_run_provenance(*, pipeline_dir: Optional[str] = None, run_created_at: Optional[str] = None,
                           forecast_obj: Any = None) -> Dict[str, Any]:
    """EVAL-8: the scored run's provenance, ``{run_created_at, source, hindcast, notes}``.

    From ``--pipeline-dir`` (``load_pipeline_provenance``) or ``--run-created-at``
    (mutually exclusive: ValueError when both are given). A forecast stamped
    ``hindcast`` marks the run a hindcast even without either. Nothing given and no
    stamp: every field empty (the headline is then ``withheld_no_provenance``).
    """
    if pipeline_dir and run_created_at:
        raise ValueError("--pipeline-dir and --run-created-at are mutually exclusive")
    if pipeline_dir:
        provenance = load_pipeline_provenance(pipeline_dir)
    else:
        provenance = {"run_created_at": None, "source": None, "hindcast": None, "notes": []}
        if run_created_at is not None:
            parsed, why = parse_run_created_at(run_created_at)
            if parsed is not None:
                provenance["run_created_at"], provenance["source"] = parsed.isoformat(), RUN_CREATED_AT_ARG
            else:
                provenance["notes"].append(f"{RUN_CREATED_AT_ARG}: {why}")
    if provenance["hindcast"] is None:
        provenance["hindcast"] = forecast_hindcast_stamp(forecast_obj)
    return provenance


# =============================================================== markdown render

def _fmt(v: Any) -> str:
    return "—" if v is None else (f"{v:.4f}" if isinstance(v, float) else str(v))


def _fmt_interval(v: Any, reason: Optional[str] = None) -> str:
    """``[lo, hi]``; a missing interval renders as ``—``, followed by why when known."""
    if v:
        return f"[{_fmt(v[0])}, {_fmt(v[1])}]"
    return f"— ({reason})" if reason else "—"


def _render_rigor(rigor: Dict[str, Any], lines: List[str], heading: str = "##") -> None:
    """EVAL-7 sections: Reference & skill, Direction & hedging, By horizon (at ``heading`` level)."""
    ref = rigor.get("reference") or {}
    lines += [f"{heading} Reference & skill", "", "| metric | value |", "|---|---|",
              f"| base rate (YES share) | {_fmt(ref.get('base_rate'))} |",
              f"| climatology Brier (constant base-rate forecast) | {_fmt(ref.get('climatology_brier'))} |",
              f"| Brier skill vs climatology (BSS; > 0 beats the base rate) | {_fmt(ref.get('bss'))} |",
              f"| Brier skill vs constant 0.5 | {_fmt(ref.get('bss_vs_half'))} |"]
    ci = rigor.get("ci")
    if ci:
        label = (f"{1 - BOOTSTRAP_ALPHA:.0%} CI, {ci.get('method')} (B={ci.get('B')}, seed {ci.get('seed')}, "
                 f"{ci.get('n_clusters')} clusters)")
        lines += [f"| mean Brier {label} | {_fmt_interval(ci.get('brier'), ci.get('reason'))} |",
                  f"| BSS {label} | {_fmt_interval(ci.get('bss'), ci.get('reason'))} |"]
        if ci.get("bss_degenerate_replicates"):
            lines.append(f"| BSS replicates without a reference (single-outcome resample; the BSS "
                         f"interval is withheld above {BOOTSTRAP_ALPHA:.0%}) | "
                         f"{ci['bss_degenerate_replicates']} / {ci.get('B')} |")
    lines.append("")

    d = rigor.get("direction") or {}
    conf = d.get("confusion") or {}
    band = d.get("hedge_band") or list(eval_stats.HEDGE_BAND)
    collapse = d.get("hedge_collapse")
    lines += [f"{heading} Direction & hedging", "", "| metric | value |", "|---|---|",
              f"| YES calls (p > 0.5) | {_fmt(d.get('yes_calls'))} |",
              f"| NO calls (p < 0.5) | {_fmt(d.get('no_calls'))} |",
              f"| ties (p = 0.5; excluded from direction and MCC) | {_fmt(d.get('ties'))} |",
              f"| predicted YES rate vs realized YES rate | {_fmt(d.get('predicted_yes_rate'))} vs "
              f"{_fmt(d.get('realized_yes_rate'))} |",
              f"| mean p / mean bias (mean p - base rate) | {_fmt(d.get('mean_p'))} / "
              f"{_fmt(d.get('mean_bias'))} |",
              f"| confusion tp / fp / tn / fn | {conf.get('tp', 0)} / {conf.get('fp', 0)} / "
              f"{conf.get('tn', 0)} / {conf.get('fn', 0)} |",
              f"| MCC (0 when undefined) | {_fmt(d.get('mcc'))} |",
              f"| hedge share ({band[0]:.2f} <= p <= {band[1]:.2f}) | {_fmt(d.get('hedge_share'))}"
              f"{' (hedge collapse)' if collapse else ''} |", ""]
    misses = d.get("confident_misses") or []
    if misses:
        cp = d.get("confident_p", eval_stats.CONFIDENT_P)
        lines += [f"Confident misses (p >= {cp:.2f} on NO, or p <= {1 - cp:.2f} on YES), worst first:", "",
                  "| id | p(YES) | outcome | Brier |", "|---|---|---|---|"]
        for miss in misses:
            lines.append(f"| {miss.get('id')} | {miss['p']:.2f} | {'YES' if miss['outcome'] else 'NO'} | "
                         f"{_fmt(miss.get('brier'))} |")
        lines.append("")

    by_h = rigor.get("by_horizon") or {}
    if by_h:
        lines += [f"{heading} By horizon", "", "| horizon | n | mean Brier | base rate | BSS | flags |",
                  "|---|---|---|---|---|---|"]
        for key, v in by_h.items():
            flags = [name for name, on in (("small", v.get("small")),
                                           ("single outcome", v.get("single_outcome"))) if on]
            lines.append(f"| {key} | {v['n']} | {_fmt(v.get('brier'))} | {_fmt(v.get('base_rate'))} | "
                         f"{_fmt(v.get('bss'))} | {', '.join(flags) or '—'} |")
        lines.append("")


def _render_metrics(m: Dict[str, Any], lines: List[str], heading: str = "##") -> None:
    """Shared metric sections of a ``score_pairs`` result: Caveats, Overall, the
    EVAL-7 rigor sections, the category / difficulty tables and calibration bins,
    each titled at ``heading`` level."""
    rigor = m.get("rigor")
    if isinstance(rigor, dict) and rigor.get("caveats"):
        lines += ["", f"{heading} Caveats", ""]
        lines += [f"- {c}" for c in rigor["caveats"]]
    lines += ["", f"{heading} Overall", "", "| metric | value |", "|---|---|",
              f"| mean Brier (lower=better) | {_fmt(m.get('mean_brier'))} |",
              f"| mean log-score (higher=better) | {_fmt(m.get('mean_log_score'))} |",
              f"| resolution accuracy (p >= 0.5 counts as YES) | {_fmt(m.get('resolution_accuracy'))} |",
              f"| ECE (lower=better) | {_fmt(m.get('calibration', {}).get('ece'))} |",
              f"| base rate (YES share) | {_fmt(m.get('base_rate'))} |", ""]
    if isinstance(rigor, dict):
        _render_rigor(rigor, lines, heading)

    def _table(title: str, bd: Dict[str, Any]) -> None:
        if not bd:
            return
        lines.append(f"{heading} By {title}")
        lines.append("")
        lines.append("| " + title + " | n | mean Brier | accuracy (p >= 0.5) | base rate |")
        lines.append("|---|---|---|---|---|")
        for key, v in bd.items():
            lines.append(f"| {key} | {v['n']} | {_fmt(v['mean_brier'])} | "
                         f"{_fmt(v['resolution_accuracy'])} | {_fmt(v['base_rate'])} |")
        lines.append("")

    _table("category", m.get("by_category", {}))
    _table("difficulty", m.get("by_difficulty", {}))

    cal = m.get("calibration", {})
    if cal.get("bins"):
        lines += [f"{heading} Calibration bins", "",
                  "| range | n | mean pred | observed | gap |", "|---|---|---|---|---|"]
        for b in cal["bins"]:
            if not b["count"]:
                continue
            rng = f"{b['range'][0]:.1f}–{b['range'][1]:.1f}"
            lines.append(f"| {rng} | {b['count']} | {_fmt(b['mean_predicted'])} | "
                         f"{_fmt(b['observed_frequency'])} | {_fmt(b['gap'])} |")
        lines.append("")


def _render_headline(report: Dict[str, Any], lines: List[str], heading: str = "##") -> None:
    """EVAL-8 Headline section: status, provenance, the tier table and, when the
    status is ok, the headline metric sections one level below ``heading``."""
    h = report.get("headline") or {}
    by_tier = (report.get("characterization") or {}).get("by_tier") or {}
    counts = h.get("tier_counts") or {}
    lines += ["", f"{heading} Headline", "", f"- status: `{h.get('status')}`"]
    if "run_created_at" in h:
        source = h.get("run_created_at_source")
        lines.append(f"- run created_at: {h.get('run_created_at') or '—'}" + (f" ({source})" if source else ""))
    if "lead_tolerance_days" in h:
        lines.append("- prospective: the run started before the resolution date and no later than "
                     f"as_of + {h['lead_tolerance_days']} days")
    if "tier_source" in h:
        lines.append(f"- tiers from each golden row's `{h['tier_source']}` (rows without it count as unknown)")
    hindcast = h.get("hindcast")
    if isinstance(hindcast, dict):
        lines.append(f"- pinned hindcast (as_of {hindcast.get('as_of') or '—'}, from {hindcast.get('source')}; "
                     f"integrity {hindcast.get('integrity') or '—'}): characterization only")
    for note in h.get("provenance_notes") or []:
        lines.append(f"- provenance note: {note}")
    if any(counts.values()):
        lines += ["", "| tier | n | mean Brier | resolution accuracy (p >= 0.5) | counts toward |",
                  "|---|---|---|---|---|"]
        for tier in TIERS:
            if not counts.get(tier):
                continue
            tm = (h.get("metrics") if tier == TIER_PROSPECTIVE else by_tier.get(tier)) or {}
            lines.append(f"| {tier} | {counts[tier]} | {_fmt(tm.get('mean_brier'))} | "
                         f"{_fmt(tm.get('resolution_accuracy'))} | "
                         f"{'headline' if tier == TIER_PROSPECTIVE else 'characterization'} |")
    if h.get("status") == HEADLINE_OK:
        _render_metrics(h.get("metrics") or {}, lines, heading=heading + "#")
        if lines[-1] == "":
            lines.pop()  # the section after this one opens with its own blank line


def _render_ledger_markdown(report: Dict[str, Any]) -> str:
    """Markdown for a score-ledger report (EVAL-7).

    score-ledger used to reuse the forecast-file layout, which has no place for
    its numbers and always printed "matched / scored: 0". This layout shows the
    production summary on its multi-class-sum Brier scale and the golden section
    on the binary scale, each labelled, with the golden metric and rigor sections
    nested one level under the golden heading.

    EVAL-8: with a ``headline`` the golden section opens with its HEADLINE line and
    a Headline subsection; the golden metric sections after it cover every scored
    golden row (characterization).
    """
    g = report.get("golden") or {}
    lines: List[str] = [
        CHARACTERIZATION_BANNER, "", "# Forecast-ledger evaluation", "",
        f"- production ledger: `{report.get('ledger_dir', '')}` ({report.get('n_entries', 0)} entries, "
        f"{report.get('n_resolved', 0)} resolved)",
        f"- golden section ledger: `{report.get('eval_ledger_dir', '')}` ({g.get('n', 0)} scored golden rows)",
        "", "## Production ledger", "", "| metric | value |", "|---|---|",
        f"| mean Brier ({report.get('brier_scale')}: summed over scenarios, 2x the binary Brier "
        f"on a YES/NO row) | {_fmt(report.get('mean_brier'))} |",
        f"| calibration error | {_fmt(report.get('calibration_error'))} |", "",
        f"## Golden section ({g.get('brier_scale', 'binary')} Brier)"]
    headline = report.get("headline")
    if isinstance(headline, dict):
        lines += ["", headline_banner(headline)]
        _render_headline(report, lines, heading="###")
        if g.get("n"):
            lines += ["", "The sections below cover every scored golden row (characterization; "
                          "the headline counts prospective rows only)."]
    if g.get("n"):
        _render_metrics(g, lines, heading="###")
    else:
        lines += ["", "No resolved golden rows in this ledger.", ""]
    return "\n".join(lines)


def render_markdown(report: Dict[str, Any]) -> str:
    """Human-readable markdown summary of a score-forecast-file or score-ledger report.

    EVAL-7: the first line is the characterization-only banner; the Caveats,
    Reference & skill, Direction & hedging and By horizon sections render the
    ``metrics.rigor`` block when present. A score-ledger report gets its own
    layout (``_render_ledger_markdown``).

    EVAL-8: a report with a ``headline`` opens with its ``HEADLINE:`` /
    ``HEADLINE WITHHELD:`` line above that banner, adds a Headline section before
    the all-matched sections and a tier column to the per-question table.
    """
    if report.get("mode") == "score-ledger":
        return _render_ledger_markdown(report)
    m = report.get("metrics", {})
    headline = report.get("headline")
    lines: List[str] = [headline_banner(headline), ""] if isinstance(headline, dict) else []
    lines += [CHARACTERIZATION_BANNER, "", "# Golden-question forecast evaluation", ""]
    lines.append(f"- source: `{report.get('forecast_path', '')}`")
    lines.append(f"- golden: `{report.get('golden_path', '')}` "
                 f"({report.get('golden_count', 0)} questions)")
    lines.append(f"- matched / scored: **{m.get('n', 0)}**")
    um = report.get("unmatched_golden_ids") or []
    if um:
        lines.append(f"- unmatched golden ids ({len(um)}): {', '.join(um)}")
    inv = report.get("invalid_probability_ids") or []
    if inv:
        lines.append(f"- dropped (bad probability): {', '.join(inv)}")
    dup = report.get("duplicate_forecast_ids") or []
    if dup:
        lines.append(f"- repeated forecast ids (first row scored, later rows ignored): {', '.join(dup)}")
    excluded = (report.get("exclusions") or {}).get("ambiguous") or []
    if excluded:
        lines.append(f"- excluded, ambiguous resolution (never scored): {', '.join(excluded)}")
    if report.get("metrics_scope"):
        lines.append(f"- metrics scope: `{report['metrics_scope']}` (the Overall and later sections cover "
                     "every matched row; the headline counts prospective rows only)")
    if isinstance(headline, dict):
        _render_headline(report, lines)
    _render_metrics(m, lines)

    rows = report.get("matched") or []
    if rows:
        tiered = any("tier" in r for r in rows)
        lines += ["## Per-question", "",
                  "| id | category | p(YES) | outcome | Brier |" + (" tier |" if tiered else ""),
                  "|---|---|---|---|---|" + ("---|" if tiered else "")]
        for r in rows:
            lines.append(f"| {r['id']} | {r.get('category') or '—'} | {r['probability']:.2f} | "
                         f"{'YES' if r['outcome'] else 'NO'} | {_fmt(r.get('brier'))} |"
                         + (f" {r.get('tier') or '—'} |" if tiered else ""))
        lines.append("")
    return "\n".join(lines)


# =============================================================== ledger bridge

def _ledger_enabled(args) -> bool:
    """Appending golden outcomes to the calibration ledger is opt-in: requires
    Config.GOLDEN_EVAL_LEDGER or an explicit --to-ledger (mirrors the eval --live guard)."""
    try:
        from app.config import Config
        env_on = bool(getattr(Config, "GOLDEN_EVAL_LEDGER", False))
    except Exception:  # noqa: BLE001
        env_on = False
    return bool(env_on or getattr(args, "to_ledger", False))


def _headline_gate_enabled() -> bool:
    """EVAL-8 GOLDEN_HEADLINE_GATE; an unreadable Config keeps the gate on (fail closed)."""
    try:
        from app.config import Config
    except Exception:  # noqa: BLE001
        return True
    return bool(getattr(Config, "GOLDEN_HEADLINE_GATE", True))


def _lead_tolerance_days() -> int:
    """EVAL-8 GOLDEN_PROSPECTIVE_LEAD_TOLERANCE_DAYS (ValueError unless an integer >= 0)."""
    try:
        from app.config import Config
    except Exception:  # noqa: BLE001
        return DEFAULT_LEAD_TOLERANCE_DAYS
    return _check_tolerance(getattr(Config, "GOLDEN_PROSPECTIVE_LEAD_TOLERANCE_DAYS",
                                    DEFAULT_LEAD_TOLERANCE_DAYS))


def _tier_matched(matched: List[Dict[str, Any]], forecast_obj: Any, args,
                  bootstrap_b: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """EVAL-8: stamp ``tier`` / ``tier_reasons`` on every matched row (in place) from the
    run provenance of ``args`` and return ``(headline, characterization)``.

    ``--pipeline-dir`` / ``--run-created-at`` are read with getattr (as is
    ``--require-headline`` by the caller), so programmatic callers without them keep
    working (no provenance: the headline is withheld). With ``--bootstrap`` an ok
    headline gets its own CI.
    """
    tolerance = _lead_tolerance_days()
    provenance = resolve_run_provenance(pipeline_dir=getattr(args, "pipeline_dir", None),
                                        run_created_at=getattr(args, "run_created_at", None),
                                        forecast_obj=forecast_obj)
    for row in matched:
        tiering = classify_tier(row, run_created_at=provenance["run_created_at"],
                                lead_tolerance_days=tolerance, hindcast=provenance["hindcast"])
        row["tier"], row["tier_reasons"] = tiering["tier"], tiering["reasons"]
    context: Dict[str, Any] = {"run_created_at": provenance["run_created_at"],
                               "run_created_at_source": provenance["source"],
                               "lead_tolerance_days": tolerance}
    if provenance["hindcast"] is not None:
        context["hindcast"] = provenance["hindcast"]
    if provenance["notes"]:
        context["provenance_notes"] = provenance["notes"]
    has_provenance = provenance["run_created_at"] is not None or provenance["hindcast"] is not None
    headline, characterization = summarize_tiers(matched, has_provenance=has_provenance,
                                                 bins=args.bins, context=context)
    if bootstrap_b and headline["status"] == HEADLINE_OK:
        prospective = [r for r in matched if r["tier"] == TIER_PROSPECTIVE]
        headline["metrics"]["rigor"]["ci"] = rigor_ci(prospective, bootstrap_b)
    return headline, characterization


def _append_matched_to_ledger(matched: List[Dict[str, Any]], ledger_dir: Optional[str]) -> int:
    """Append each matched (probability, known outcome) as a resolved golden binary
    forecast so an EVALUATION calibration curve accumulates. Returns count appended.

    Foglamp WP1 (1E, I-20/I-21): golden rows are answer-bearing characterization
    data. ``append_golden_result`` refuses to land them in the production ledger —
    a production-dir target (default or explicit) is transparently redirected to
    the isolated evaluation ledger, and production ``calibration_summary`` /
    ``recalibration_param`` exclude golden/characterization rows by record type.

    EVAL-8: each row's ``tier`` (set only under GOLDEN_HEADLINE_GATE) becomes the
    ledger row's ``golden_tier``; untiered rows are appended exactly as before.
    """
    from app.services.forecast_ledger import append_golden_result
    appended = 0
    redirected = 0
    for r in matched:
        e = append_golden_result(
            question_id=r["id"], probability=r["probability"], resolved_outcome=r["outcome"],
            question=r.get("question"), category=r.get("category"),
            resolution_date=r.get("resolution_date"), as_of_date=r.get("as_of_date"),
            d=ledger_dir, golden_tier=r.get("tier"),
        )
        if e:
            appended += 1
            if e.get("ledger_redirected"):
                redirected += 1
    if redirected:
        print(f"note: {redirected} golden row(s) redirected to the isolated evaluation "
              "ledger (production ledger.jsonl never accepts golden/characterization rows)")
    return appended


def _write_outputs(report: Dict[str, Any], out_path: Optional[str], md_path: Optional[str]) -> None:
    """Write eval_report.json (--out) and/or the readable markdown (--markdown).

    EVAL-7: both files go through the atomic temp-file + rename helpers, so a
    reader (or a diff across code versions) never sees a half-written report.
    The JSON bytes are unchanged (same ensure_ascii=False, indent=2 encoding).
    """
    if out_path:
        write_json_atomic(out_path, report)
        print(f"wrote {out_path}")
    if md_path:
        write_text_atomic(md_path, render_markdown(report))
        print(f"wrote {md_path}")
    if not out_path and not md_path:
        print(json.dumps(report, ensure_ascii=False, indent=2))


# =============================================================== CLI commands

def cmd_score_forecast_file(args) -> int:
    version, questions = load_golden_file(args.golden)
    gindex = index_golden(questions)
    with open(args.forecast, encoding="utf-8") as f:
        forecast_obj = json.load(f)
    binaries = extract_binary_forecasts(forecast_obj)
    match = match_forecasts(binaries, gindex)
    metrics = score_pairs(match["matched"], bins=args.bins)
    # EVAL-7: --bootstrap B (0 = off) adds a question-clustered percentile CI.
    # Read with getattr so programmatic callers without the attribute keep working.
    bootstrap_b = int(getattr(args, "bootstrap", 0) or 0)
    if bootstrap_b < 0:
        raise ValueError(f"--bootstrap must be >= 0, got {bootstrap_b}")
    if bootstrap_b:
        metrics["rigor"]["ci"] = rigor_ci(match["matched"], bootstrap_b)

    # EVAL-8: tier the rows before the ledger append, which records each row's tier.
    tiering = (_tier_matched(match["matched"], forecast_obj, args, bootstrap_b)
               if _headline_gate_enabled() else None)

    ledger_appended = 0
    if _ledger_enabled(args) and match["matched"]:
        ledger_appended = _append_matched_to_ledger(match["matched"], args.ledger_dir)

    report: Dict[str, Any] = {
        "mode": "score-forecast-file",
        "forecast_path": args.forecast,
        "golden_path": args.golden,
        "golden_count": len(questions),
    }
    if tiering is not None:
        report["headline"] = tiering[0]
    report["metrics"] = metrics
    if tiering is not None:
        # The legacy block keeps every matched row: characterization, not the headline.
        report["metrics_scope"] = METRICS_SCOPE
        report["characterization"] = tiering[1]
    report.update({
        "matched": match["matched"],
        "unmatched_forecast_ids": match["unmatched_forecast_ids"],
        "unmatched_golden_ids": match["unmatched_golden_ids"],
        "invalid_probability_ids": match["invalid_probability_ids"],
        "duplicate_forecast_ids": match["duplicate_forecast_ids"],
        "ledger_appended": ledger_appended,
        "promotion_eligible": False,
    })
    # EVAL-9: a v2 golden set always reports its exclusions; a v1 report keeps its
    # exact pre-EVAL-9 keys unless a row really was excluded.
    if version == golden_set.SCHEMA_VERSION or any(match["exclusions"].values()):
        report["exclusions"] = match["exclusions"]
    _write_outputs(report, args.out, args.markdown)
    # EVAL-8: --require-headline fails closed on any status but ok (gate_disabled included).
    status = tiering[0]["status"] if tiering is not None else HEADLINE_GATE_DISABLED
    if getattr(args, "require_headline", False) and status != HEADLINE_OK:
        print(f"error: --require-headline: headline status is {status}", file=sys.stderr)
        return EXIT_HEADLINE_WITHHELD
    # Non-zero exit only when NOTHING matched — a signal the ids are misaligned, not
    # a quality gate (there is no committed golden baseline to gate against here).
    return 0 if match["matched"] else 3


def cmd_score_ledger(args) -> int:
    from app.services.forecast_ledger import calibration_summary, evaluation_ledger_dir, read_ledger
    from app.services.forecast_ledger import ledger_dir as production_ledger_dir
    from app.services.backtest import calibration_report
    entries = read_ledger(args.ledger_dir)
    resolved = [
        {"forecast": {"scenarios": e.get("scenarios")}, "outcome": e.get("outcome")}
        for e in entries
        if e.get("resolved") and e.get("outcome") and e.get("scenarios")
    ]
    cal = calibration_report(resolved, bins=args.bins) if resolved else {"n": 0}
    # Foglamp WP1 (1E)：这是评估通道对（隔离）账本的显式打分——include_evaluation=True。
    # 生产侧的 calibration_summary 默认排除 golden/characterization 行。
    summary = calibration_summary(args.ledger_dir, entries=entries,
                                  include_evaluation=True)

    # EVAL-7: forecast_ledger.append_golden_result redirects every golden row aimed
    # at the production ledger dir (default or explicit) to the isolated evaluation
    # ledger, so reading the production ledger here always showed n=0. The golden
    # section reads --eval-ledger-dir when given, else --ledger-dir when it names a
    # non-production dir (the explicit single-ledger behaviour), else
    # evaluation_ledger_dir() — the same production-dir test the writer applies.
    eval_dir = getattr(args, "eval_ledger_dir", None)
    explicit_non_production = bool(args.ledger_dir) and (
        os.path.abspath(args.ledger_dir) != os.path.abspath(production_ledger_dir()))
    if eval_dir:
        golden_dir, golden_entries = eval_dir, read_ledger(eval_dir)
    elif explicit_non_production:
        golden_dir, golden_entries = args.ledger_dir, entries
    else:
        golden_dir = evaluation_ledger_dir()
        golden_entries = read_ledger(golden_dir)

    # Golden-tagged entries carry a category → a per-category binary breakdown, using
    # the YES-scenario probability as the model's p and outcome=='YES' as the label.
    gate = _headline_gate_enabled()
    golden_scored: List[Dict[str, Any]] = []
    tier_stamped = 0
    for e in golden_entries:
        if not (e.get("golden") and e.get("resolved") and e.get("scenarios")):
            continue
        yes = next((s for s in e["scenarios"] if str(s.get("name")).upper() == "YES"), None)
        p = _coerce_prob(yes.get("probability")) if isinstance(yes, dict) else None
        if p is None:
            continue
        golden_scored.append({
            "id": e.get("question_id") or e.get("report_id"),
            "probability": p,
            "outcome": str(e.get("outcome")).upper() == "YES",
            "category": e.get("category"),
            "difficulty": None,
            "as_of_date": e.get("as_of_date"),
            "resolution_date": e.get("resolution_date"),
        })
        if gate:
            # EVAL-8: the tier the row was scored under; a row without one (or with a
            # value that is no tier) is unknown and never counts toward the headline.
            tier = e.get("golden_tier")
            golden_scored[-1]["tier"] = tier if tier in TIERS else TIER_UNKNOWN
            if "golden_tier" in e:
                tier_stamped += 1

    golden: Dict[str, Any] = score_pairs(golden_scored, bins=args.bins) if golden_scored else {"n": 0}
    # EVAL-7: the two Brier numbers are on different scales. The top-level one sums
    # (p_i - y_i)^2 over every scenario (backtest.score_forecast), which is twice the
    # binary Brier for a YES/NO row; the golden section is the binary (p - y)^2.
    golden["brier_scale"] = "binary"
    report: Dict[str, Any] = {
        "mode": "score-ledger",
        "ledger_dir": args.ledger_dir or "(default)",
        "eval_ledger_dir": golden_dir,
        "n_entries": len(entries),
        "n_resolved": summary.get("n_resolved", 0),
        "mean_brier": summary.get("mean_brier"),
        "brier_scale": "multiclass_sum",
        "calibration_error": summary.get("calibration_error"),
        "calibration_report": cal,
        "golden": golden,
        "promotion_eligible": False,
    }
    if gate:
        # EVAL-8: the golden headline counts golden_tier 'prospective' rows only; a
        # ledger whose golden rows carry no golden_tier at all has no provenance.
        report["headline"], report["characterization"] = summarize_tiers(
            golden_scored, has_provenance=bool(tier_stamped) or not golden_scored, bins=args.bins,
            context={"tier_source": "golden_tier"})
    _write_outputs(report, args.out, args.markdown)
    return 0


def _non_negative_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a non-negative integer, got {value!r}") from None
    if n < 0:
        raise argparse.ArgumentTypeError(f"expected a non-negative integer, got {value!r}")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(
        description="golden-question forecast-quality evaluation (deterministic, offline)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("score-forecast-file",
                       help="score a pipeline forecast.json's binary_forecasts vs the golden set")
    a.add_argument("--forecast", required=True, help="path to forecast.json (pipeline binary_forecasts schema)")
    a.add_argument("--golden", default=GOLDEN_PATH, help="golden question set JSON")
    a.add_argument("--bins", type=int, default=DEFAULT_BINS, help="calibration bins over [0,1]")
    a.add_argument("-o", "--out", default=None, help="write eval_report.json (default: stdout)")
    a.add_argument("--markdown", default=None, help="also write a readable markdown table")
    a.add_argument("--to-ledger", action="store_true",
                   help="append matched outcomes to the calibration ledger (opt-in; else needs GOLDEN_EVAL_LEDGER)")
    a.add_argument("--ledger-dir", default=None, help="override ledger dir (default: FORECAST_LEDGER_DIR)")
    a.add_argument("--bootstrap", type=_non_negative_int, default=0, metavar="B",
                   help="add a question-clustered percentile bootstrap 95%% CI on Brier and BSS "
                        f"with B resamples (seed {BOOTSTRAP_SEED}; default 0 = off)")
    provenance = a.add_mutually_exclusive_group()
    provenance.add_argument("--pipeline-dir", default=None, metavar="DIR",
                            help="the pipeline directory of the run that wrote --forecast (its run.json, else "
                                 "pipeline_state.json, created_at and hindcast pin decide each row's "
                                 "headline tier; EVAL-8)")
    provenance.add_argument("--run-created-at", default=None, metavar="ISO",
                            help="the run's creation time as ISO-8601 with a UTC offset "
                                 "(e.g. 2026-09-28T10:00:00+00:00) when no pipeline directory is at hand")
    a.add_argument("--require-headline", action="store_true",
                   help=f"exit {EXIT_HEADLINE_WITHHELD} unless the headline status is ok "
                        "(withheld or GOLDEN_HEADLINE_GATE=false)")
    a.set_defaults(func=cmd_score_forecast_file)

    b = sub.add_parser("score-ledger",
                       help="score every recorded resolution in the forecast ledger")
    b.add_argument("--ledger-dir", default=None, help="override ledger dir (default: FORECAST_LEDGER_DIR)")
    b.add_argument("--eval-ledger-dir", default=None,
                   help="ledger dir for the golden section (default: --ledger-dir when it is not "
                        "the production ledger, else the isolated evaluation ledger)")
    b.add_argument("--bins", type=int, default=DEFAULT_BINS)
    b.add_argument("-o", "--out", default=None, help="write report JSON (default: stdout)")
    b.add_argument("--markdown", default=None, help="also write a readable markdown table")
    b.set_defaults(func=cmd_score_ledger)

    args = ap.parse_args()
    try:
        return args.func(args)
    except golden_set.RecomputeMismatchError as exc:
        # EVAL-9: an answer key that its own evidence contradicts is never scored.
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_RECOMPUTE_MISMATCH


if __name__ == "__main__":
    sys.exit(main())
