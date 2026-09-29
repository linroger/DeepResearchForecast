#!/usr/bin/env python3
"""Golden-question forecast-quality evaluation harness (EVAL-1).

WHY THIS EXISTS — full pytest can go green while the pipeline quietly produces
WORSE forecasts (vaguer, over-hedged, mis-calibrated). Unit tests check code
shape; they cannot tell you whether a 70% actually happens ~70% of the time.
This harness turns forecast quality into a NUMBER against ground truth: it scores
the pipeline's binary_forecasts against a curated set of REAL, already-resolved
2024-2026 yes/no questions (``backend/tests/eval/golden_questions.json``) and
emits Brier score, logarithmic score, calibration bins + ECE, resolution
accuracy, and per-category / per-difficulty breakdowns — so you can compare
``eval_report.json`` across code versions and SEE whether a change helped.

Relation to ``eval_forecast_quality.py`` (I-7-7): that harness is an LLM-JUDGE
rubric scorer for report *prose* (groundedness/coverage/…). THIS harness is a
purely-deterministic, offline OUTCOME scorer — no LLM, no network — that grades
probabilities against known truth. They are complementary, not duplicative.

INTENDED WORKFLOW (the whole point — read this before using):
  1. For each golden question, build a research brief and run the pipeline with an
     AS-OF constraint at/near the question's ``as_of_date`` (the knowledge cutoff a
     fair forecaster should be scored at — do NOT let it peek past the outcome).
  2. Set each produced binary forecast's ``id`` to the golden question's ``id``
     (matching is by id), or curate the golden ``id``s to match your forecast ids.
  3. Score the pipeline's ``forecast.json`` against the golden set:
         python backend/scripts/golden_eval.py score-forecast-file \
             --forecast backend/uploads/reports/<report_id>/forecast.json \
             -o eval_report.json --markdown eval_report.md [--bootstrap 1000]
  4. Commit ``eval_report.json`` and DIFF it across code versions. Read the
     ``metrics.rigor`` block (EVAL-7) before the raw numbers: the golden set is
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
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import eval_stats  # noqa: E402
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
BOOTSTRAP_METHOD = "question-clustered percentile bootstrap"
BOOTSTRAP_SEED = eval_stats.DEFAULT_BOOTSTRAP_SEED


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
    - ``caveats``: deterministic strings, rendered in JSON and markdown.
    - ``promotion_eligible`` is always False (ADR 0002 I-21).
    """
    rows = [dict(r, horizon_bucket=eval_stats.horizon_bucket(_row_horizon_days(r))) for r in scored]
    n = len(rows)
    n_clusters = len(eval_stats.group_clusters(rows, "cluster"))
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
    caveats.append(f"n = {n} questions in {n_clusters} clusters")
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
    ``bss_degenerate_replicates`` instead of being dropped silently. ``reason``
    explains a null interval (``fewer_than_2_clusters`` or ``degenerate_reference``).
    """
    B = int(B)
    n_clusters = len(eval_stats.group_clusters(scored, "cluster"))
    brier = eval_stats.cluster_bootstrap_ci(scored, eval_stats.mean_brier, "cluster", B, seed)
    bss_reps = eval_stats.cluster_bootstrap_replicates(scored, _bss_stat, "cluster", B, seed)
    bss = eval_stats.percentile_interval(bss_reps) if bss_reps is not None else None
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
        "bss_degenerate_replicates": (sum(1 for v in bss_reps if v is None)
                                      if bss_reps is not None else None),
        "reason": reason,
    }


def load_golden_set(path: str = GOLDEN_PATH) -> List[Dict[str, Any]]:
    """Load + validate the golden question set. Accepts either a top-level list or
    an object with a ``questions`` list. Each entry needs a non-empty ``id`` and a
    boolean ``resolved_outcome``; malformed entries raise ValueError (fail loud —
    a silently-dropped golden question would understate coverage)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    questions = data.get("questions") if isinstance(data, dict) else data
    if not isinstance(questions, list) or not questions:
        raise ValueError(f"golden set {path} has no 'questions' list")
    for q in questions:
        if not isinstance(q, dict) or not str(q.get("id") or "").strip():
            raise ValueError(f"golden entry missing 'id': {q!r}")
        if not isinstance(q.get("resolved_outcome"), bool):
            raise ValueError(f"golden entry {q.get('id')!r} needs boolean 'resolved_outcome'")
    return questions


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


def match_forecasts(binary_forecasts: List[Dict[str, Any]],
                    golden_index: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Match forecast rows to golden questions by ``id``; score the intersection.

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
    """
    matched: List[Dict[str, Any]] = []
    matched_ids: set = set()
    invalid: List[str] = []
    seen: set = set()
    duplicates: set = set()
    for row in binary_forecasts:
        fid = str(row.get("id") or "").strip()
        if not fid or fid not in golden_index:
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
        matched.append({
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
        })
    forecast_ids = {str(r.get("id") or "").strip() for r in binary_forecasts if str(r.get("id") or "").strip()}
    return {
        "matched": matched,
        "unmatched_forecast_ids": sorted(forecast_ids - matched_ids - set(invalid)),
        "unmatched_golden_ids": sorted(set(golden_index) - matched_ids),
        "invalid_probability_ids": sorted(invalid),
        "duplicate_forecast_ids": sorted(duplicates),
    }


# =============================================================== markdown render

def _fmt(v: Any) -> str:
    return "—" if v is None else (f"{v:.4f}" if isinstance(v, float) else str(v))


def _fmt_interval(v: Any) -> str:
    return "—" if not v else f"[{_fmt(v[0])}, {_fmt(v[1])}]"


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
        label = (f"95% CI, {ci.get('method')} (B={ci.get('B')}, seed {ci.get('seed')}, "
                 f"{ci.get('n_clusters')} clusters)")
        lines += [f"| mean Brier {label} | {_fmt_interval(ci.get('brier'))} |",
                  f"| BSS {label} | {_fmt_interval(ci.get('bss'))} |"]
        if ci.get("bss_degenerate_replicates"):
            lines.append(f"| BSS replicates without a reference (single-outcome resample) | "
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


def _render_ledger_markdown(report: Dict[str, Any]) -> str:
    """Markdown for a score-ledger report (EVAL-7).

    score-ledger used to reuse the forecast-file layout, which has no place for
    its numbers and always printed "matched / scored: 0". This layout shows the
    production summary on its multi-class-sum Brier scale and the golden section
    on the binary scale, each labelled, with the golden metric and rigor sections
    nested one level under the golden heading.
    """
    g = report.get("golden") or {}
    lines: List[str] = [
        f"> {CHARACTERIZATION_BANNER}", "", "# Forecast-ledger evaluation", "",
        f"- production ledger: `{report.get('ledger_dir', '')}` ({report.get('n_entries', 0)} entries, "
        f"{report.get('n_resolved', 0)} resolved)",
        f"- golden section ledger: `{report.get('eval_ledger_dir', '')}` ({g.get('n', 0)} scored golden rows)",
        "", "## Production ledger", "", "| metric | value |", "|---|---|",
        f"| mean Brier ({report.get('brier_scale')}: summed over scenarios, 2x the binary Brier "
        f"on a YES/NO row) | {_fmt(report.get('mean_brier'))} |",
        f"| calibration error | {_fmt(report.get('calibration_error'))} |", "",
        f"## Golden section ({g.get('brier_scale', 'binary')} Brier)"]
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
    """
    if report.get("mode") == "score-ledger":
        return _render_ledger_markdown(report)
    m = report.get("metrics", {})
    lines: List[str] = [f"> {CHARACTERIZATION_BANNER}", "", "# Golden-question forecast evaluation", ""]
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
    _render_metrics(m, lines)

    rows = report.get("matched") or []
    if rows:
        lines += ["## Per-question", "",
                  "| id | category | p(YES) | outcome | Brier |", "|---|---|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['id']} | {r.get('category') or '—'} | {r['probability']:.2f} | "
                         f"{'YES' if r['outcome'] else 'NO'} | {_fmt(r.get('brier'))} |")
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


def _append_matched_to_ledger(matched: List[Dict[str, Any]], ledger_dir: Optional[str]) -> int:
    """Append each matched (probability, known outcome) as a resolved golden binary
    forecast so an EVALUATION calibration curve accumulates. Returns count appended.

    Foglamp WP1 (1E, I-20/I-21): golden rows are answer-bearing characterization
    data. ``append_golden_result`` refuses to land them in the production ledger —
    a production-dir target (default or explicit) is transparently redirected to
    the isolated evaluation ledger, and production ``calibration_summary`` /
    ``recalibration_param`` exclude golden/characterization rows by record type.
    """
    from app.services.forecast_ledger import append_golden_result
    appended = 0
    redirected = 0
    for r in matched:
        e = append_golden_result(
            question_id=r["id"], probability=r["probability"], resolved_outcome=r["outcome"],
            question=r.get("question"), category=r.get("category"),
            resolution_date=r.get("resolution_date"), as_of_date=r.get("as_of_date"),
            d=ledger_dir,
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
    questions = load_golden_set(args.golden)
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

    ledger_appended = 0
    if _ledger_enabled(args) and match["matched"]:
        ledger_appended = _append_matched_to_ledger(match["matched"], args.ledger_dir)

    report: Dict[str, Any] = {
        "mode": "score-forecast-file",
        "forecast_path": args.forecast,
        "golden_path": args.golden,
        "golden_count": len(questions),
        "metrics": metrics,
        "matched": match["matched"],
        "unmatched_forecast_ids": match["unmatched_forecast_ids"],
        "unmatched_golden_ids": match["unmatched_golden_ids"],
        "invalid_probability_ids": match["invalid_probability_ids"],
        "duplicate_forecast_ids": match["duplicate_forecast_ids"],
        "ledger_appended": ledger_appended,
        "promotion_eligible": False,
    }
    _write_outputs(report, args.out, args.markdown)
    # Non-zero exit only when NOTHING matched — a signal the ids are misaligned, not
    # a quality gate (there is no committed golden baseline to gate against here).
    return 0 if match["matched"] else 3


def cmd_score_ledger(args) -> int:
    from app.services.forecast_ledger import calibration_summary, evaluation_ledger_dir, read_ledger
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

    # EVAL-7: golden rows are redirected to the isolated evaluation ledger on write
    # (forecast_ledger.append_golden_result), so by default the golden section reads
    # that ledger — reading the production ledger here always showed n=0. The
    # section reads --eval-ledger-dir when given, else --ledger-dir when given
    # (the explicit single-ledger behaviour), else evaluation_ledger_dir().
    eval_dir = getattr(args, "eval_ledger_dir", None)
    if eval_dir:
        golden_dir, golden_entries = eval_dir, read_ledger(eval_dir)
    elif args.ledger_dir:
        golden_dir, golden_entries = args.ledger_dir, entries
    else:
        golden_dir = evaluation_ledger_dir()
        golden_entries = read_ledger(golden_dir)

    # Golden-tagged entries carry a category → a per-category binary breakdown, using
    # the YES-scenario probability as the model's p and outcome=='YES' as the label.
    golden_scored: List[Dict[str, Any]] = []
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
    a.set_defaults(func=cmd_score_forecast_file)

    b = sub.add_parser("score-ledger",
                       help="score every recorded resolution in the forecast ledger")
    b.add_argument("--ledger-dir", default=None, help="override ledger dir (default: FORECAST_LEDGER_DIR)")
    b.add_argument("--eval-ledger-dir", default=None,
                   help="ledger dir for the golden section (default: --ledger-dir when given, "
                        "else the isolated evaluation ledger)")
    b.add_argument("--bins", type=int, default=DEFAULT_BINS)
    b.add_argument("-o", "--out", default=None, help="write report JSON (default: stdout)")
    b.add_argument("--markdown", default=None, help="also write a readable markdown table")
    b.set_defaults(func=cmd_score_ledger)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
