"""Offline tests for app.services.eval_stats (EVAL-7, candidate P06).

Known-value fixtures pin the small-n statistics that make golden-eval numbers
readable: climatology Brier and BSS on the committed (24/30 YES) golden set,
MCC on a known confusion matrix, the inclusive hedge band shared with
forecast_extractor._binary_quality, horizon buckets, the question-clustered
bootstrap, the dispersion collapse check and the Wilson interval. No LLM, no
network, no disk writes.
"""

import ast
import json
import math
import os
import sys
from collections import Counter

import pytest

from app.services import eval_stats as es

GOLDEN_FIXTURE = os.path.join(os.path.dirname(__file__), "eval", "golden_questions.json")


def _golden_questions():
    with open(GOLDEN_FIXTURE, encoding="utf-8") as f:
        return json.load(f)["questions"]


def _constant_rows(p):
    return [{"id": q["id"], "probability": p, "outcome": q["resolved_outcome"]}
            for q in _golden_questions()]


# ------------------------------------------------------- skill vs climatology
def test_constant_forecasts_on_committed_golden():
    rows_08 = _constant_rows(0.8)
    assert sum(1 for r in rows_08 if r["outcome"]) == 24 and len(rows_08) == 30
    assert es.mean_brier(rows_08) == pytest.approx(0.16)
    assert es.climatology_brier(r["outcome"] for r in rows_08) == pytest.approx(0.16)
    ref_08 = es.reference_scores(rows_08)
    assert ref_08["base_rate"] == 0.8
    assert ref_08["climatology_brier"] == 0.16
    assert ref_08["bss"] == 0.0                         # constant base rate = no skill
    assert math.copysign(1.0, ref_08["bss"]) == 1.0      # never rendered as -0.0

    rows_09 = _constant_rows(0.9)
    assert es.mean_brier(rows_09) == pytest.approx(0.17)
    ref_09 = es.reference_scores(rows_09)
    assert ref_09["bss"] == -0.0625
    assert ref_09["bss_vs_half"] == pytest.approx(1 - 0.17 / 0.25, abs=1e-4)
    d_09 = es.direction_stats(rows_09)
    assert d_09["mcc"] == 0.0                           # always-YES: zero MCC denominator
    assert d_09["predicted_yes_rate"] == 1.0 and d_09["realized_yes_rate"] == 0.8
    assert d_09["confusion"] == {"tp": 24, "fp": 6, "tn": 0, "fn": 0}
    assert d_09["mean_bias"] == pytest.approx(0.1)
    # six NO outcomes at p = 0.9 are confident misses, each Brier 0.81
    assert len(d_09["confident_misses"]) == 6
    assert {m["brier"] for m in d_09["confident_misses"]} == {0.81}

    assert es.reference_scores(_constant_rows(0.5))["bss"] == -0.5625


def test_brier_skill_and_climatology_degenerate_cases():
    assert es.brier_skill(0.1, 0.0) is None         # single-outcome reference: undefined, never inf
    assert es.brier_skill(None, 0.2) is None and es.brier_skill(0.1, None) is None
    assert es.brier_skill(0.1, 0.2) == pytest.approx(0.5)
    assert es.climatology_brier([]) is None
    assert es.climatology_brier([True, True]) == 0.0
    ref = es.reference_scores([{"id": "a", "probability": 0.9, "outcome": True}])
    assert ref["bss"] is None and ref["reason"] == "degenerate_reference"
    empty = es.reference_scores([])
    assert empty["base_rate"] is None and empty["bss"] is None


# ----------------------------------------------------------------- direction
def test_mcc_known_confusion():
    rows = (
        [{"id": f"tp{i}", "probability": 0.8, "outcome": True} for i in range(3)]
        + [{"id": f"tn{i}", "probability": 0.2, "outcome": False} for i in range(2)]
        + [{"id": "fp", "probability": 0.7, "outcome": False},
           {"id": "fn", "probability": 0.25, "outcome": True}]
        + [{"id": "tie-yes", "probability": 0.5, "outcome": True},
           {"id": "tie-no", "probability": 0.5, "outcome": False}]
    )
    d = es.direction_stats(rows)
    assert d["confusion"] == {"tp": 3, "fp": 1, "tn": 2, "fn": 1}
    assert d["ties"] == 2                               # p == 0.5 excluded from the confusion
    assert d["yes_calls"] == 4 and d["no_calls"] == 3 and d["n"] == 9
    assert d["mcc"] == 0.4167
    assert es.mcc(3, 1, 2, 1) == pytest.approx(5 / 12)
    assert es.mcc(5, 0, 0, 0) == 0.0                    # zero denominator
    # confident misses: fn (p 0.25 on YES, Brier 0.5625) before fp (p 0.7 on NO, Brier 0.49)
    assert [m["id"] for m in d["confident_misses"]] == ["fn", "fp"]
    assert d["confident_misses"][1] == {"id": "fp", "p": 0.7, "outcome": False, "brier": 0.49}
    # the boundaries are inclusive, like the publish gate's conviction rule
    edge = es.direction_stats([{"id": "hi", "probability": 0.7, "outcome": False},
                               {"id": "lo", "probability": 0.3, "outcome": True},
                               {"id": "in", "probability": 0.69, "outcome": False}])
    assert sorted(m["id"] for m in edge["confident_misses"]) == ["hi", "lo"]


def test_direction_stats_empty_is_null():
    d = es.direction_stats([])
    assert d["n"] == 0 and d["yes_calls"] == 0 and d["ties"] == 0
    for key in ("predicted_yes_rate", "realized_yes_rate", "mean_p", "mean_bias",
                "mcc", "hedge_share", "hedge_collapse"):
        assert d[key] is None, key
    assert d["confident_misses"] == []


def test_hedge_share_inclusive_band():
    from app.services.forecast_extractor import _binary_quality

    ps = [0.39, 0.4, 0.5, 0.6, 0.61]
    rows = [{"id": f"r{i}", "probability": p, "outcome": i % 2 == 0} for i, p in enumerate(ps)]
    d = es.direction_stats(rows)
    assert d["hedge_share"] == 0.6                      # 0.40, 0.50 and 0.60 are inside
    assert d["hedge_collapse"] is True                  # share >= 0.5
    assert es.HEDGE_BAND == (0.40, 0.60) and es.CONFIDENT_P == 0.70
    gate = _binary_quality([{"probability": p} for p in ps], min_count=1)
    assert gate["midband_share"] == d["hedge_share"]    # same band as the publish gate
    assert es.dispersion(ps, [r["outcome"] for r in rows])["hedge_share"] == 0.6


# ------------------------------------------------------------------ horizons
def test_horizon_buckets_on_golden():
    questions = _golden_questions()
    buckets = Counter(es.horizon_bucket(es.horizon_days(q["as_of_date"], q["resolution_date"]))
                      for q in questions)
    assert buckets == Counter({"le30": 16, "d31_180": 13, "gt180": 1})
    rows = [{"id": q["id"], "probability": 0.8, "outcome": q["resolved_outcome"],
             "horizon_bucket": es.horizon_bucket(es.horizon_days(q["as_of_date"], q["resolution_date"]))}
            for q in questions]
    strata = es.strata_stats(rows, "horizon_bucket", min_n=3)
    assert {k: v["n"] for k, v in strata.items()} == {"d31_180": 13, "gt180": 1, "le30": 16}
    assert strata["gt180"]["small"] is True
    assert strata["gt180"]["single_outcome"] is True and strata["gt180"]["bss"] is None
    assert strata["gt180"]["reason"] == "degenerate_reference"
    assert strata["le30"]["small"] is False and strata["le30"]["bss"] is not None

    assert es.horizon_bucket(0) == "le30" and es.horizon_bucket(30) == "le30"
    assert es.horizon_bucket(31) == "d31_180" and es.horizon_bucket(180) == "d31_180"
    assert es.horizon_bucket(181) == "gt180"
    for bad in (None, -1, True, "30", float("nan")):
        assert es.horizon_bucket(bad) == "unknown", bad
    assert es.horizon_bucket_labels() == ("le30", "d31_180", "gt180", "unknown")
    # malformed (non-canonical) dates never produce a horizon
    assert es.horizon_days("2024-1-05", "2024-02-01") is None
    assert es.horizon_days("2024/01/05", "2024-02-01") is None
    assert es.horizon_days("20240105", "2024-02-01") is None
    assert es.horizon_days(None, "2024-02-01") is None
    assert es.horizon_days("2024-02-01", "2024-01-05") == -27   # evidence kept; bucket unknown
    with pytest.raises(ValueError):
        es.horizon_bucket(10, edges=(180, 30))


def test_category_strata_small_and_single_outcome_on_golden():
    rows = [{"id": q["id"], "probability": 0.8, "outcome": q["resolved_outcome"],
             "category": q["category"]} for q in _golden_questions()]
    strata = es.strata_stats(rows, "category", min_n=3)
    small = sorted(k for k, v in strata.items() if v["small"])
    single = sorted(k for k, v in strata.items() if v["single_outcome"])
    assert small == ["awards", "legal-politics", "science-tech"]
    assert single == ["awards", "legal-politics", "markets", "product-launch", "science-tech", "sports"]
    assert all(strata[k]["bss"] is None and strata[k]["reason"] == "degenerate_reference" for k in single)
    assert strata["elections"]["bss"] is not None and strata["monetary-policy"]["bss"] is not None


# ----------------------------------------------------------------- bootstrap
def _paired_rows():
    """Golden rows at varied p, with the four linked election pairs as clusters."""
    linked = {"us-pres-2024-trump": "us-pres-2024", "us-pres-2024-harris": "us-pres-2024",
              "us-senate-2024-gop": "us-senate-2024", "us-senate-2024-dem-hold": "us-senate-2024",
              "uk-ge-2024-labour": "uk-ge-2024", "uk-ge-2024-tory": "uk-ge-2024",
              "in-ge-2024-bjp-alone": "in-ge-2024", "in-ge-2024-nda-majority": "in-ge-2024"}
    rows = []
    for i, q in enumerate(_golden_questions()):
        rows.append({"id": q["id"], "probability": [0.2, 0.55, 0.7, 0.9][i % 4],
                     "outcome": q["resolved_outcome"], "cluster": linked.get(q["id"], q["id"])})
    return rows


def test_bootstrap_deterministic_and_single_cluster_none():
    rows = _paired_rows()
    assert len(es.group_clusters(rows, "cluster")) == 26
    ci_a = es.cluster_bootstrap_ci(rows, es.mean_brier, "cluster", B=500, seed=1729)
    ci_b = es.cluster_bootstrap_ci(rows, es.mean_brier, "cluster", B=500, seed=1729)
    assert ci_a == ci_b                                  # same seed, same interval
    assert ci_a[0] <= es.mean_brier(rows) <= ci_a[1]
    reps_a = es.cluster_bootstrap_replicates(rows, es.mean_brier, "cluster", B=500, seed=1729)
    reps_c = es.cluster_bootstrap_replicates(rows, es.mean_brier, "cluster", B=500, seed=7)
    assert len(reps_a) == 500 and reps_a != reps_c       # the seed drives the resamples
    assert reps_a == es.cluster_bootstrap_replicates(list(reversed(rows)), es.mean_brier,
                                                     "cluster", B=500, seed=1729)  # row order is irrelevant

    # linked questions are resampled together: both members of a pair, or neither
    def _pair_stat(sample):
        ids = Counter(r["id"] for r in sample)
        assert ids["us-pres-2024-trump"] == ids["us-pres-2024-harris"]
        assert ids["uk-ge-2024-labour"] == ids["uk-ge-2024-tory"]
        return es.mean_brier(sample)

    assert es.cluster_bootstrap_replicates(rows, _pair_stat, "cluster", B=200, seed=3)

    one_cluster = [dict(r, cluster="all") for r in rows]
    assert es.cluster_bootstrap_ci(one_cluster, es.mean_brier, "cluster", B=100, seed=1) is None
    assert es.cluster_bootstrap_ci(rows[:1], es.mean_brier, "cluster", B=100, seed=1) is None
    assert es.cluster_bootstrap_ci([], es.mean_brier, "cluster", B=100, seed=1) is None
    with pytest.raises(ValueError):
        es.cluster_bootstrap_ci(rows, es.mean_brier, "cluster", B=0, seed=1)

    # a stat that is undefined on some resamples yields None replicates, not a crash
    def _bss(sample):
        return es.brier_skill(es.mean_brier(sample), es.climatology_brier(r["outcome"] for r in sample))

    two = [{"id": "y", "probability": 0.9, "outcome": True}, {"id": "n", "probability": 0.1, "outcome": False}]
    reps = es.cluster_bootstrap_replicates(two, _bss, "cluster", B=200, seed=11)
    assert None in reps and any(v is not None for v in reps)


def test_cluster_fallbacks_and_percentile_indices():
    rows = [{"id": "a", "probability": 0.5, "outcome": True},             # no cluster -> id
            {"id": "b", "probability": 0.5, "outcome": True, "cluster": " "},
            {"probability": 0.5, "outcome": False},                         # no id -> singleton
            {"probability": 0.5, "outcome": False}]
    clusters = es.group_clusters(rows, "cluster")
    assert len(clusters) == 4
    by_callable = es.group_clusters(rows, lambda r: "same")
    assert len(by_callable) == 1
    assert es.percentile_interval(float(v) for v in range(1000)) == [25.0, 974.0]
    assert es.percentile_interval([None, 2.0]) == [2.0, 2.0]
    assert es.percentile_interval([None]) is None
    with pytest.raises(ValueError):
        es.percentile_interval([1.0], alpha=0)


# ---------------------------------------------------------------- dispersion
def test_dispersion_collapse_constant_and_hedger():
    ys = [q["resolved_outcome"] for q in _golden_questions()]
    constant = es.dispersion([0.8] * len(ys), ys)
    assert constant["collapsed"] is True
    assert "low_std" in constant["reasons"] and "one_sided" in constant["reasons"]
    assert constant["std"] == 0.0 and constant["n_distinct"] == 1
    assert constant["pos_rate"] == 1.0 and constant["auc"] == 0.5   # all tied

    hedger_ps = [0.45 if i % 2 else 0.58 for i in range(len(ys))]
    hedger = es.dispersion(hedger_ps, ys)
    assert hedger["collapsed"] is True and "hedged" in hedger["reasons"]
    assert hedger["hedge_share"] == 1.0

    ps = [0.9 if y else 0.1 for y in ys]
    sharp = es.dispersion(ps, ys)
    assert sharp["collapsed"] is False and sharp["reasons"] == []
    assert sharp["auc"] == 1.0 and sharp["n_distinct"] == 2

    inverted = es.dispersion([0.1 if y else 0.9 for y in ys], ys)
    assert inverted["auc"] == 0.0 and inverted["collapsed"] is False

    one_class = es.dispersion([0.1, 0.9, 0.5], [True, True, True])
    assert one_class["auc"] == 0.5
    assert "one_sided" not in one_class["reasons"]      # pos_rate rule needs both outcomes

    empty = es.dispersion([], [])
    assert empty["collapsed"] is True and empty["n"] == 0   # no spread to show: fail closed
    assert sharp["invalid_indices"] == [] and empty["invalid_indices"] == []
    with pytest.raises(ValueError):
        es.dispersion([0.1, 0.2], [True])


BAD_PROBABILITIES = (float("nan"), float("inf"), float("-inf"), -40.0, 1.5, None, "high")


def test_invalid_probabilities_fail_closed():
    """NaN, inf, out-of-range or non-numeric p never passes a collapse check or skews a statistic."""
    ys = [q["resolved_outcome"] for q in _golden_questions()]
    for bad in BAD_PROBABILITIES:
        for ps in ([0.8] * (len(ys) - 1) + [bad],                        # would collapse if valid
                   [0.9 if y else 0.1 for y in ys[:-1]] + [bad]):        # would pass if valid
            d = es.dispersion(ps, ys)
            assert d["collapsed"] is True, bad
            assert d["reasons"] == ["invalid_probability"] and d["invalid_indices"] == [len(ys) - 1]
            assert d["n"] == len(ys) and d["std"] is None and d["pos_rate"] is None and d["auc"] is None
            json.dumps(d, allow_nan=False)                               # standard JSON, never NaN
    assert es.dispersion([None, 0.5, float("nan")], [True, False, True])["invalid_indices"] == [0, 2]

    # the row helpers refuse bad input instead of scoring it (a NaN was a direction "tie")
    for bad in BAD_PROBABILITIES:
        rows = [{"id": "ok", "probability": 0.7, "outcome": True},
                {"id": "bad-row", "probability": bad, "outcome": False}]
        for fn in (es.mean_brier, es.direction_stats, es.reference_scores,
                   lambda r: es.strata_stats(r, "category")):
            with pytest.raises(ValueError, match="bad-row"):
                fn(rows)
    with pytest.raises(ValueError, match="missing"):
        es.mean_brier([{"id": "missing", "outcome": True}])

    for good, expected in ((0, 0.0), (1, 1.0), (0.5, 0.5), ("0.25", 0.25)):
        assert es.as_probability(good) == expected
    for bad in BAD_PROBABILITIES:
        assert es.as_probability(bad) is None, bad


# -------------------------------------------------------------------- wilson
def test_wilson_interval_known_values():
    lo, hi = es.wilson_interval(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-4) and hi == pytest.approx(0.9433, abs=1e-4)
    lo0, hi0 = es.wilson_interval(0, 10)
    assert lo0 == 0.0 and 0 < hi0 < 0.35
    assert es.wilson_interval(10, 10)[1] == 1.0
    assert es.wilson_interval(0, 0) is None
    for bad in ((11, 10), (-1, 10), (1.5, 10), (True, 10)):
        with pytest.raises(ValueError):
            es.wilson_interval(*bad)
    with pytest.raises(ValueError):
        es.wilson_interval(1, 10, z=0)


# ----------------------------------------------------------------- placement
def test_module_is_pure_stdlib_outside_evaluation_namespace():
    path = es.__file__
    assert os.path.normpath(path).endswith(os.path.join("app", "services", "eval_stats.py"))
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "eval_stats must not import app modules (Config, disk, LLM)"
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names), imported
    assert es.DEFAULT_BOOTSTRAP_SEED == 1729
