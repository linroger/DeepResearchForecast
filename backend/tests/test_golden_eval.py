"""Offline unit tests for the golden-question forecast-quality harness (EVAL-1).

All tests are offline and deterministic — no LLM, no network. They exercise the
pure scoring core (binary Brier / log-score / ECE bins / matching / breakdowns),
the golden-set fixture integrity, and the ledger bridge (append_golden_result →
calibration_summary). Known-value fixtures pin the math.
"""

import argparse
import json
import math
import os
import sys
from types import SimpleNamespace

import pytest

# golden_eval harness lives in backend/scripts/
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import golden_eval as ge  # noqa: E402

from app.services.forecast_ledger import (  # noqa: E402
    append_golden_result,
    calibration_summary,
    read_ledger,
)


# ----------------------------------------------------------------- binary_brier
def test_binary_brier_known_values():
    assert ge.binary_brier(0.8, True) == pytest.approx(0.04)     # (0.8-1)^2
    assert ge.binary_brier(0.8, False) == pytest.approx(0.64)    # (0.8-0)^2
    assert ge.binary_brier(0.0, False) == 0.0                    # perfect NO
    assert ge.binary_brier(1.0, True) == 0.0                     # perfect YES
    assert ge.binary_brier(0.5, True) == pytest.approx(0.25)


# -------------------------------------------------------------- binary_log_score
def test_binary_log_score_known_values_and_clamp():
    assert ge.binary_log_score(0.8, True) == pytest.approx(math.log(0.8))
    assert ge.binary_log_score(0.25, False) == pytest.approx(math.log(0.75))
    # confidently-wrong 0/1 does not blow up (clamped, large finite penalty)
    v = ge.binary_log_score(1.0, False)
    assert v < 0 and math.isfinite(v)
    assert v == pytest.approx(math.log(ge._EPS))


# ------------------------------------------------------------------ _coerce_prob
def test_coerce_prob_rejects_garbage_and_out_of_range():
    assert ge._coerce_prob(0.5) == 0.5
    assert ge._coerce_prob("0.3") == 0.3
    assert ge._coerce_prob(None) is None
    assert ge._coerce_prob("nope") is None
    assert ge._coerce_prob(1.5) is None
    assert ge._coerce_prob(-0.1) is None
    assert ge._coerce_prob(float("nan")) is None
    assert ge._coerce_prob(float("inf")) is None


# --------------------------------------------------------------- calibration_bins
def test_calibration_bins_ece_known_value():
    # two 0.1-preds that are NO, two 0.9-preds that are YES → each bin gap 0.1
    pairs = [(0.1, False), (0.1, False), (0.9, True), (0.9, True)]
    cal = ge.calibration_bins(pairs, bins=10)
    assert cal["n"] == 4
    assert cal["ece"] == pytest.approx(0.1)
    # bin[1] holds the 0.1s (observed 0), bin[9] holds the 0.9s (observed 1)
    assert cal["bins"][1]["count"] == 2 and cal["bins"][1]["observed_frequency"] == 0.0
    assert cal["bins"][9]["count"] == 2 and cal["bins"][9]["observed_frequency"] == 1.0


def test_calibration_bins_perfect_and_empty():
    # perfectly calibrated: 0.5 pred, half YES → gap 0
    perfect = ge.calibration_bins([(0.5, True), (0.5, False)], bins=10)
    assert perfect["ece"] == pytest.approx(0.0)
    empty = ge.calibration_bins([], bins=10)
    assert empty["ece"] is None and empty["n"] == 0


def test_calibration_bins_edge_p_one_goes_in_last_bin():
    cal = ge.calibration_bins([(1.0, True)], bins=10)
    assert cal["bins"][9]["count"] == 1  # p=1.0 clamps into the top bin, not out of range


# ------------------------------------------------------------------- score_pairs
def test_score_pairs_overall_and_breakdowns():
    scored = [
        {"id": "a", "probability": 0.9, "outcome": True, "category": "x", "difficulty": "easy"},
        {"id": "b", "probability": 0.2, "outcome": False, "category": "x", "difficulty": "hard"},
        {"id": "c", "probability": 0.6, "outcome": True, "category": "y", "difficulty": "easy"},
    ]
    m = ge.score_pairs(scored, bins=10)
    assert m["n"] == 3
    # mean brier = (0.01 + 0.04 + 0.16)/3
    assert m["mean_brier"] == pytest.approx((0.01 + 0.04 + 0.16) / 3, abs=1e-4)
    # all three predicted correctly at 0.5 threshold (YES,NO,YES)
    assert m["resolution_accuracy"] == 1.0
    assert m["base_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert m["by_category"]["x"]["n"] == 2 and m["by_category"]["y"]["n"] == 1
    assert m["by_difficulty"]["easy"]["n"] == 2


def test_score_pairs_resolution_threshold_and_empty():
    # p exactly 0.5 predicts YES; here outcome False → wrong
    m = ge.score_pairs([{"id": "a", "probability": 0.5, "outcome": False,
                         "category": None, "difficulty": None}])
    assert m["resolution_accuracy"] == 0.0
    empty = ge.score_pairs([])
    assert empty["n"] == 0 and empty["mean_brier"] is None


# ------------------------------------------------------------ extract + matching
def test_extract_binary_forecasts_shapes():
    assert ge.extract_binary_forecasts({"binary_forecasts": [{"id": "F1"}]}) == [{"id": "F1"}]
    assert ge.extract_binary_forecasts([{"id": "F1"}]) == [{"id": "F1"}]
    assert ge.extract_binary_forecasts({"forecast": {"binary_forecasts": [{"id": "F2"}]}}) == [{"id": "F2"}]
    assert ge.extract_binary_forecasts("garbage") == []


def test_match_forecasts_matched_unmatched_and_invalid():
    golden = ge.index_golden([
        {"id": "q1", "resolved_outcome": True, "category": "c", "difficulty": "easy"},
        {"id": "q2", "resolved_outcome": False, "category": "c", "difficulty": "hard"},
        {"id": "q3", "resolved_outcome": True, "category": "d", "difficulty": "easy"},
    ])
    binaries = [
        {"id": "q1", "probability": 0.7},
        {"id": "q2", "probability": 1.5},     # out of range → invalid
        {"id": "zzz", "probability": 0.5},    # not in golden → unmatched forecast
    ]
    res = ge.match_forecasts(binaries, golden)
    assert [m["id"] for m in res["matched"]] == ["q1"]
    assert res["matched"][0]["outcome"] is True
    assert res["invalid_probability_ids"] == ["q2"]
    assert res["unmatched_forecast_ids"] == ["zzz"]
    assert res["unmatched_golden_ids"] == ["q2", "q3"]  # q2 invalid counts as unmatched


def test_match_by_target_question_id():
    """EVAL-13: an evaluation cell's bound binary is matched on target_question_id, not its F id."""
    golden = ge.index_golden([
        {"id": "q-eu", "resolved_outcome": True, "category": "c", "difficulty": "easy"},
        {"id": "q-fed", "resolved_outcome": False, "category": "c", "difficulty": "hard"},
    ])
    binaries = [
        {"id": "F1", "probability": 0.4},                                   # unbound → unmatched
        {"id": "F2", "probability": 0.7, "target_question_id": "q-eu",
         "target_bind": "normalized"},
        {"id": "F3", "probability": 0.2, "target_question_id": "not-golden"},  # falls back to F3
        {"id": "q-fed", "probability": 0.1},                                # plain id match unchanged
    ]
    res = ge.match_forecasts(binaries, golden)
    by_id = {m["id"]: m for m in res["matched"]}
    assert set(by_id) == {"q-eu", "q-fed"}
    assert by_id["q-eu"]["probability"] == 0.7 and by_id["q-eu"]["outcome"] is True
    assert by_id["q-eu"]["forecast_id"] == "F2"          # the row's own id is kept for audit
    assert "forecast_id" not in by_id["q-fed"]           # id-matched rows keep today's shape
    assert res["unmatched_forecast_ids"] == ["F1", "F3"]
    assert res["unmatched_golden_ids"] == []
    # target_question_id is preferred over the F id: a row whose own id is also golden
    # still answers its bound target, and a second row for that target is a duplicate.
    res2 = ge.match_forecasts([
        {"id": "q-fed", "probability": 0.6, "target_question_id": "q-eu"},
        {"id": "F9", "probability": 0.3, "target_question_id": "q-eu"},
    ], golden)
    assert [m["id"] for m in res2["matched"]] == ["q-eu"]
    assert res2["matched"][0]["probability"] == 0.6
    assert res2["duplicate_forecast_ids"] == ["q-eu"]
    assert res2["unmatched_golden_ids"] == ["q-fed"]


# --------------------------------------------------------------- golden fixture
def test_golden_set_fixture_is_wellformed():
    questions = ge.load_golden_set()  # committed fixture
    assert len(questions) >= 25, "golden set should have ~25-30 questions"
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids)), "golden ids must be unique"
    for q in questions:
        assert isinstance(q["resolved_outcome"], bool)
        assert q.get("resolution_criteria"), f"{q['id']} needs resolution_criteria"
        assert q.get("as_of_date"), f"{q['id']} needs as_of_date"
        assert q.get("category") and q.get("difficulty")
        # as_of_date must precede resolution_date (no peeking past the outcome)
        assert q["as_of_date"] <= q["resolution_date"], f"{q['id']} as_of after resolution"
    # a healthy golden set has BOTH outcomes so Brier/calibration are meaningful
    outs = {q["resolved_outcome"] for q in questions}
    assert outs == {True, False}


def test_load_golden_set_rejects_malformed(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"questions": [{"id": "x"}]}), encoding="utf-8")  # no resolved_outcome
    with pytest.raises(ValueError):
        ge.load_golden_set(str(bad))
    bad.write_text(json.dumps({"questions": [{"resolved_outcome": True}]}), encoding="utf-8")  # no id
    with pytest.raises(ValueError):
        ge.load_golden_set(str(bad))


# --------------------------------------------------------------- ledger bridge
def test_append_golden_result_and_calibration(tmp_path):
    d = str(tmp_path)
    e = append_golden_result(question_id="q1", probability=0.7, resolved_outcome=True,
                             category="elections", resolution_date="2024-11-06",
                             as_of_date="2024-11-01", d=d)
    assert e["resolved"] is True and e["outcome"] == "YES" and e["golden"] is True
    assert e["scenarios"][0]["name"] == "YES" and e["scenarios"][0]["probability"] == 0.7
    assert e["scenarios"][1]["probability"] == pytest.approx(0.3)
    append_golden_result(question_id="q2", probability=0.2, resolved_outcome=False, d=d)
    led = read_ledger(d)
    assert len(led) == 2
    # Foglamp WP1 (1E, I-21)：生产口径的 calibration_summary 按记录类型排除黄金行；
    # 评估通道显式 include_evaluation=True 才能给隔离账本打分。
    cs = calibration_summary(d)
    assert cs["n_resolved"] == 0
    cs_eval = calibration_summary(d, include_evaluation=True)
    assert cs_eval["n_resolved"] == 2 and cs_eval["mean_brier"] is not None


def test_append_golden_result_rejects_bad_probability(tmp_path):
    d = str(tmp_path)
    assert append_golden_result(question_id="q", probability="nope", resolved_outcome=True, d=d) is None
    assert append_golden_result(question_id="q", probability=float("nan"), resolved_outcome=True, d=d) is None
    assert append_golden_result(question_id="", probability=0.5, resolved_outcome=True, d=d) is None
    assert read_ledger(d) == []  # nothing written


# ----------------------------------------------------------- end-to-end scoring
def test_score_forecast_file_end_to_end(tmp_path):
    """A synthetic forecast.json scored against a synthetic golden set → report."""
    golden = {"questions": [
        {"id": "q1", "question": "?", "resolution_criteria": "x", "resolved_outcome": True,
         "resolution_date": "2024-11-06", "category": "elections", "difficulty": "easy",
         "as_of_date": "2024-11-01"},
        {"id": "q2", "question": "?", "resolution_criteria": "x", "resolved_outcome": False,
         "resolution_date": "2024-11-06", "category": "elections", "difficulty": "easy",
         "as_of_date": "2024-11-01"},
    ]}
    gpath = tmp_path / "golden.json"
    gpath.write_text(json.dumps(golden), encoding="utf-8")
    fc = {"binary_forecasts": [
        {"id": "q1", "statement": "s1", "probability": 0.9},
        {"id": "q2", "statement": "s2", "probability": 0.3},
    ]}
    fpath = tmp_path / "forecast.json"
    fpath.write_text(json.dumps(fc), encoding="utf-8")
    out = tmp_path / "eval_report.json"
    md = tmp_path / "eval_report.md"
    args = SimpleNamespace(forecast=str(fpath), golden=str(gpath), bins=10,
                           out=str(out), markdown=str(md), to_ledger=False,
                           ledger_dir=str(tmp_path / "ledger"))
    rc = ge.cmd_score_forecast_file(args)
    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["metrics"]["n"] == 2
    assert report["metrics"]["resolution_accuracy"] == 1.0
    assert report["ledger_appended"] == 0            # opt-in OFF → no ledger writes
    assert not os.path.exists(str(tmp_path / "ledger" / "ledger.jsonl"))
    assert "Golden-question forecast evaluation" in md.read_text(encoding="utf-8")


def test_score_forecast_file_to_ledger_opt_in(tmp_path):
    golden = {"questions": [
        {"id": "q1", "resolution_criteria": "x", "resolved_outcome": True,
         "resolution_date": "2024-11-06", "category": "elections", "difficulty": "easy",
         "as_of_date": "2024-11-01"},
    ]}
    gpath = tmp_path / "golden.json"
    gpath.write_text(json.dumps(golden), encoding="utf-8")
    fpath = tmp_path / "forecast.json"
    fpath.write_text(json.dumps({"binary_forecasts": [{"id": "q1", "probability": 0.8}]}), encoding="utf-8")
    ldir = str(tmp_path / "ledger")
    args = SimpleNamespace(forecast=str(fpath), golden=str(gpath), bins=10,
                           out=None, markdown=None, to_ledger=True,  # explicit opt-in
                           ledger_dir=ldir)
    rc = ge.cmd_score_forecast_file(args)
    assert rc == 0
    led = read_ledger(ldir)
    assert len(led) == 1 and led[0]["outcome"] == "YES" and led[0]["golden"] is True


def test_score_forecast_file_no_match_exit_code(tmp_path):
    golden = {"questions": [{"id": "q1", "resolved_outcome": True, "resolution_criteria": "x",
                             "resolution_date": "2024-11-06", "category": "c", "difficulty": "easy",
                             "as_of_date": "2024-11-01"}]}
    gpath = tmp_path / "golden.json"
    gpath.write_text(json.dumps(golden), encoding="utf-8")
    fpath = tmp_path / "forecast.json"
    fpath.write_text(json.dumps({"binary_forecasts": [{"id": "F1", "probability": 0.5}]}), encoding="utf-8")
    args = SimpleNamespace(forecast=str(fpath), golden=str(gpath), bins=10,
                           out=None, markdown=None, to_ledger=False,
                           ledger_dir=str(tmp_path / "ledger"))
    assert ge.cmd_score_forecast_file(args) == 3   # nothing matched → id-misalignment signal


def test_score_ledger_over_golden_entries(tmp_path):
    d = str(tmp_path / "ledger")
    append_golden_result(question_id="q1", probability=0.7, resolved_outcome=True,
                         category="elections", d=d)
    append_golden_result(question_id="q2", probability=0.2, resolved_outcome=False,
                         category="sports", d=d)
    out = tmp_path / "ledger_eval.json"
    args = SimpleNamespace(ledger_dir=d, bins=10, out=str(out), markdown=None)
    rc = ge.cmd_score_ledger(args)
    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["n_resolved"] == 2 and report["mean_brier"] is not None
    assert report["golden"]["n"] == 2
    assert report["golden"]["by_category"]["elections"]["n"] == 1


# ================================================== EVAL-7: honesty layer (P06)
LEGACY_REPORT_SHA256 = "a52690dbee3ebbc2a2b2188d0bd3739ed061b1d99c723c486d4927c60c807177"
EVAL7_REPORT_KEYS = {"duplicate_forecast_ids", "promotion_eligible"}
EVAL7_ROW_KEYS = {"cluster", "horizon_days", "horizon_bucket"}
# EVAL-8 (GOLDEN_HEADLINE_GATE, default on) adds these, additively as well.
EVAL8_REPORT_KEYS = {"headline", "metrics_scope", "characterization"}
EVAL8_ROW_KEYS = {"tier", "tier_reasons"}
# EVAL-12 adds the contamination block (unprobed without --probe-report) and, with a
# matching probe report, the flagged/unflagged metric split.
EVAL12_REPORT_KEYS = {"contamination", "metrics_flagged", "metrics_unflagged"}


@pytest.fixture
def isolated_ledgers(tmp_path, monkeypatch):
    """Production + evaluation ledgers under tmp_path; the GOLDEN_EVAL_LEDGER env opt-in forced off."""
    from app.config import Config
    from app.services import forecast_ledger as fl

    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(tmp_path / "_forecast_ledger"), raising=False)
    monkeypatch.setattr(Config, "GOLDEN_EVAL_LEDGER", False, raising=False)
    return fl


def _write_json(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


def _legacy_fixture(tmp_path):
    """Five golden questions (one tie at 0.5, one confident miss) + one unmatched id."""
    golden = {"questions": [
        {"id": "q1", "question": "Q1?", "resolution_criteria": "x", "resolved_outcome": True,
         "resolution_date": "2024-11-06", "category": "elections", "difficulty": "easy", "as_of_date": "2024-11-01"},
        {"id": "q2", "question": "Q2?", "resolution_criteria": "x", "resolved_outcome": False,
         "resolution_date": "2024-11-06", "category": "elections", "difficulty": "easy", "as_of_date": "2024-11-01"},
        {"id": "q3", "question": "Q3?", "resolution_criteria": "x", "resolved_outcome": True,
         "resolution_date": "2024-12-05", "category": "markets", "difficulty": "hard", "as_of_date": "2024-01-01"},
        {"id": "q4", "question": "Q4?", "resolution_criteria": "x", "resolved_outcome": False,
         "resolution_date": "2024-08-01", "category": "markets", "difficulty": "medium", "as_of_date": "2024-06-01"},
        {"id": "q5", "question": "Q5?", "resolution_criteria": "x", "resolved_outcome": True,
         "resolution_date": "2024-06-01", "category": "sports", "difficulty": "medium", "as_of_date": "2024-05-01"},
    ]}
    fc = {"binary_forecasts": [
        {"id": "q1", "probability": 0.9}, {"id": "q2", "probability": 0.5},
        {"id": "q3", "probability": 0.4}, {"id": "q4", "probability": 0.75},
        {"id": "q5", "probability": 0.62}, {"id": "zzz", "probability": 0.3},
    ]}
    return _write_json(tmp_path / "golden.json", golden), _write_json(tmp_path / "forecast.json", fc)


def _args(**kw):
    base = {"bins": 10, "out": None, "markdown": None, "to_ledger": False, "ledger_dir": None}
    base.update(kw)
    return SimpleNamespace(**base)


def _constant_forecast(tmp_path, p):
    ids = [q["id"] for q in ge.load_golden_set()]
    return _write_json(tmp_path / f"const_{p}.json",
                       {"binary_forecasts": [{"id": i, "probability": p} for i in ids]})


def _committed_cluster_count():
    """Resampling clusters in the committed set: its ``event_cluster`` when present, else the id."""
    return len({str(q.get("event_cluster") or "").strip() or q["id"] for q in ge.load_golden_set()})


@pytest.mark.usefixtures("isolated_ledgers")
def test_rigor_block_additive_legacy_unchanged(tmp_path):
    """Every pre-EVAL-7 key and value is unchanged; rigor and the new keys are additive.

    LEGACY_REPORT_SHA256 is the sha256 of the canonical JSON (sort_keys, compact) of
    the report the pre-EVAL-7 code (main@1e40844) wrote for this exact fixture, with
    the two tmp paths removed.
    """
    import hashlib

    gpath, fpath = _legacy_fixture(tmp_path)
    out = tmp_path / "eval_report.json"
    assert ge.cmd_score_forecast_file(_args(forecast=fpath, golden=gpath, out=str(out))) == 0
    report = json.loads(out.read_text(encoding="utf-8"))

    legacy = {k: v for k, v in report.items()
              if k not in EVAL7_REPORT_KEYS | EVAL8_REPORT_KEYS | EVAL12_REPORT_KEYS
              | {"forecast_path", "golden_path"}}
    legacy["metrics"] = {k: v for k, v in report["metrics"].items() if k != "rigor"}
    legacy["matched"] = [{k: v for k, v in r.items() if k not in EVAL7_ROW_KEYS | EVAL8_ROW_KEYS}
                         for r in report["matched"]]
    canon = json.dumps(legacy, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(canon.encode("utf-8")).hexdigest() == LEGACY_REPORT_SHA256
    m = report["metrics"]
    assert (m["n"], m["mean_brier"], m["resolution_accuracy"], m["base_rate"]) == (5, 0.2654, 0.4, 0.6)

    rigor = m["rigor"]
    assert set(rigor) == {"n", "reference", "direction", "by_horizon", "category_flags",
                          "n_clusters", "caveats", "promotion_eligible"}
    assert rigor["promotion_eligible"] is False and report["promotion_eligible"] is False
    assert rigor["reference"] == {"base_rate": 0.6, "climatology_brier": 0.24, "bss": -0.1058,
                                  "bss_vs_half": -0.0615, "reason": None}
    d = rigor["direction"]
    assert d["ties"] == 1 and d["confusion"] == {"tp": 2, "fp": 1, "tn": 0, "fn": 1}
    assert d["mcc"] == -0.3333 and d["hedge_share"] == 0.4
    assert [x["id"] for x in d["confident_misses"]] == ["q4"]
    assert list(rigor["by_horizon"]) == ["le30", "d31_180", "gt180"]      # horizon order
    assert rigor["category_flags"] == {"min_n": 3, "small": ["elections", "markets", "sports"],
                                       "single_outcome": ["sports"]}
    assert rigor["n_clusters"] == 5
    assert any("exactly p = 0.5" in c for c in rigor["caveats"])
    assert "ci" not in rigor                               # --bootstrap defaults to off
    row = report["matched"][0]
    assert (row["cluster"], row["horizon_days"], row["horizon_bucket"]) == ("q1", 5, "le30")
    assert report["duplicate_forecast_ids"] == []

    # empty input: rigor with n 0 and nulls; legacy empty shape unchanged
    empty = ge.score_pairs([])
    assert {k: v for k, v in empty.items() if k not in ("calibration", "rigor")} == {
        "n": 0, "mean_brier": None, "mean_log_score": None, "resolution_accuracy": None,
        "base_rate": None, "by_category": {}, "by_difficulty": {}}
    er = empty["rigor"]
    assert er["n"] == 0 and er["n_clusters"] == 0 and er["promotion_eligible"] is False
    assert all(v is None for v in er["reference"].values())
    assert er["direction"]["mcc"] is None and er["direction"]["predicted_yes_rate"] is None
    assert er["by_horizon"] == {} and er["caveats"][-1] == "n = 0 questions in 0 clusters"


@pytest.mark.usefixtures("isolated_ledgers")
def test_score_forecast_file_constant_09_on_committed_set(tmp_path):
    """Acceptance: always-YES at 0.9 is '80% accurate' with MCC 0 and negative skill."""
    fpath = _constant_forecast(tmp_path, 0.9)
    out, md = tmp_path / "eval_report.json", tmp_path / "eval_report.md"
    rc = ge.cmd_score_forecast_file(_args(forecast=fpath, golden=ge.GOLDEN_PATH,
                                          out=str(out), markdown=str(md)))
    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    m = report["metrics"]
    assert m["n"] == 30 and m["resolution_accuracy"] == 0.8 and m["mean_brier"] == 0.17
    rigor = m["rigor"]
    assert rigor["direction"]["mcc"] == 0.0
    assert rigor["direction"]["predicted_yes_rate"] == 1.0 and rigor["direction"]["realized_yes_rate"] == 0.8
    assert rigor["reference"]["climatology_brier"] == 0.16 and rigor["reference"]["bss"] == -0.0625
    assert rigor["caveats"][0] == "base rate 0.80 (24/30): a constant 0.80 forecast scores Brier 0.160 - read BSS"
    assert ge.ANSWER_BEARING_CAVEAT in rigor["caveats"]
    n_clusters = _committed_cluster_count()             # 30 until the fixture gains event_cluster
    assert rigor["n_clusters"] == n_clusters
    assert f"n = 30 questions in {n_clusters} clusters" in rigor["caveats"]
    assert {k: v["n"] for k, v in rigor["by_horizon"].items()} == {"le30": 16, "d31_180": 13, "gt180": 1}
    assert rigor["by_horizon"]["gt180"]["small"] is True
    assert rigor["category_flags"]["small"] == ["awards", "legal-politics", "science-tech"]
    assert len(rigor["category_flags"]["single_outcome"]) == 6
    assert rigor["promotion_eligible"] is False and report["promotion_eligible"] is False

    text = md.read_text(encoding="utf-8")
    # EVAL-8: the withheld-headline line (no run provenance given) sits above the banner
    assert text.splitlines()[0].startswith("HEADLINE WITHHELD: ")
    assert text.splitlines()[2] == ge.CHARACTERIZATION_BANNER
    assert ge.CHARACTERIZATION_BANNER == ("Characterization only - answer-bearing golden set; "
                                          "not a skill estimate (ADR 0002 I-21)")
    for section in ("## Caveats", "## Reference & skill", "## Direction & hedging", "## By horizon"):
        assert section in text.splitlines(), section
    assert "resolution accuracy (p >= 0.5 counts as YES)" in text
    assert "base rate 0.80 (24/30)" in text


@pytest.mark.usefixtures("isolated_ledgers")
def test_score_forecast_file_bootstrap_ci(tmp_path):
    fpath = _constant_forecast(tmp_path, 0.9)
    reports = []
    for name in ("a.json", "b.json"):
        out = tmp_path / name
        assert ge.cmd_score_forecast_file(_args(forecast=fpath, golden=ge.GOLDEN_PATH,
                                                out=str(out), bootstrap=300)) == 0
        reports.append(out.read_bytes())
    assert reports[0] == reports[1]                        # seeded: byte-identical reruns
    ci = json.loads(reports[0])["metrics"]["rigor"]["ci"]
    assert ci["method"] == "question-clustered percentile bootstrap"
    assert (ci["B"], ci["seed"], ci["n_clusters"]) == (300, 1729, _committed_cluster_count())
    assert ci["brier"][0] <= 0.17 <= ci["brier"][1]
    assert ci["bss"][0] <= ci["bss"][1] and ci["reason"] is None
    assert isinstance(ci["bss_degenerate_replicates"], int)

    # clusters come from the golden event_cluster key: a linked pair resamples as one
    golden = {"questions": [
        {"id": "a", "resolved_outcome": True, "event_cluster": "pair", "as_of_date": "2024-01-01",
         "resolution_date": "2024-01-10", "category": "c", "difficulty": "easy"},
        {"id": "b", "resolved_outcome": False, "event_cluster": "pair", "as_of_date": "2024-01-01",
         "resolution_date": "2024-01-10", "category": "c", "difficulty": "easy"},
    ]}
    gpath = _write_json(tmp_path / "pair_golden.json", golden)
    fpair = _write_json(tmp_path / "pair_fc.json", {"binary_forecasts": [
        {"id": "a", "probability": 0.7}, {"id": "b", "probability": 0.4}]})
    out = tmp_path / "pair.json"
    assert ge.cmd_score_forecast_file(_args(forecast=fpair, golden=gpath, out=str(out), bootstrap=50)) == 0
    pair = json.loads(out.read_text(encoding="utf-8"))
    assert [r["cluster"] for r in pair["matched"]] == ["pair", "pair"]
    assert pair["metrics"]["rigor"]["n_clusters"] == 1
    pci = pair["metrics"]["rigor"]["ci"]
    assert pci["brier"] is None and pci["bss"] is None and pci["reason"] == "fewer_than_2_clusters"

    assert ci["bss_degenerate_replicates"] / 300 <= ge.BOOTSTRAP_ALPHA   # committed set: interval kept
    with pytest.raises(ValueError):
        ge.cmd_score_forecast_file(_args(forecast=fpath, golden=ge.GOLDEN_PATH, bootstrap=-1))
    with pytest.raises(argparse.ArgumentTypeError):
        ge._non_negative_int("-5")
    with pytest.raises(argparse.ArgumentTypeError):
        ge._non_negative_int("many")
    assert ge._non_negative_int("0") == 0


@pytest.mark.usefixtures("isolated_ledgers")
def test_bss_ci_withheld_when_degenerate_replicates_exceed_alpha(tmp_path, monkeypatch):
    """With 2 clusters about half the resamples have one outcome: no 95% BSS interval, fail closed."""
    golden = {"questions": [
        {"id": "a", "resolved_outcome": True, "event_cluster": "c1", "category": "c", "difficulty": "easy"},
        {"id": "c", "resolved_outcome": True, "event_cluster": "c1", "category": "c", "difficulty": "easy"},
        {"id": "b", "resolved_outcome": False, "event_cluster": "c2", "category": "c", "difficulty": "easy"},
    ]}
    gpath = _write_json(tmp_path / "two_clusters.json", golden)
    fpath = _write_json(tmp_path / "fc.json", {"binary_forecasts": [
        {"id": "a", "probability": 0.9}, {"id": "c", "probability": 0.7}, {"id": "b", "probability": 0.2}]})
    out, md = tmp_path / "r.json", tmp_path / "r.md"
    assert ge.cmd_score_forecast_file(_args(forecast=fpath, golden=gpath, out=str(out), markdown=str(md),
                                            bootstrap=200)) == 0
    ci = json.loads(out.read_text(encoding="utf-8"))["metrics"]["rigor"]["ci"]
    assert ci["n_clusters"] == 2 and ci["bss_degenerate_replicates"] / 200 > ge.BOOTSTRAP_ALPHA
    assert ci["bss"] is None and ci["reason"] == "degenerate_reference"   # was a zero-width [0.79, 0.79]
    assert ci["brier"] is not None                                        # the Brier interval stands
    text = md.read_text(encoding="utf-8")
    assert "| — (degenerate_reference) |" in text
    assert f"| {ci['bss_degenerate_replicates']} / 200 |" in text

    # the threshold is the CI's alpha: 1/20 degenerate keeps the interval, 2/20 withholds it
    rows = [{"id": "x", "probability": 0.6, "outcome": True, "cluster": "k1"},
            {"id": "y", "probability": 0.3, "outcome": False, "cluster": "k2"}]

    def _replicates_with(n_none):
        def fake(_rows, _stat_fn, _cluster_key, B, _seed):
            return [None] * n_none + [i / B for i in range(B - n_none)]
        return fake

    monkeypatch.setattr(ge.eval_stats, "cluster_bootstrap_replicates", _replicates_with(1))
    at_alpha = ge.rigor_ci(rows, 20)
    assert at_alpha["bss"] is not None and at_alpha["reason"] is None
    assert at_alpha["bss_degenerate_replicates"] == 1
    monkeypatch.setattr(ge.eval_stats, "cluster_bootstrap_replicates", _replicates_with(2))
    over_alpha = ge.rigor_ci(rows, 20)
    assert over_alpha["bss"] is None and over_alpha["reason"] == "degenerate_reference"
    assert over_alpha["bss_degenerate_replicates"] == 2 and over_alpha["brier"] is not None


def test_score_ledger_repeated_question_ids_caveat(tmp_path, isolated_ledgers):
    """Append-only ledger repeats are scored per row; the size caveat says rows, not questions."""
    for _ in range(4):
        append_golden_result(question_id="q1", probability=0.7, resolved_outcome=True, category="c")
    append_golden_result(question_id="q2", probability=0.2, resolved_outcome=False, category="c")
    out, md = tmp_path / "ledger.json", tmp_path / "ledger.md"
    assert ge.cmd_score_ledger(SimpleNamespace(ledger_dir=None, bins=10, out=str(out), markdown=str(md))) == 0
    rigor = json.loads(out.read_text(encoding="utf-8"))["golden"]["rigor"]
    expected = ("n = 5 rows (2 distinct questions) in 2 clusters: a repeated question id is scored "
                "once per row, so repeats weigh on n, the base rate and every mean")
    assert expected in rigor["caveats"]
    assert not any(c.startswith("n = 5 questions") for c in rigor["caveats"])
    assert f"- {expected}" in md.read_text(encoding="utf-8").splitlines()
    # distinct ids keep the plain wording
    unique = ge.score_pairs([{"id": "q1", "probability": 0.7, "outcome": True},
                             {"id": "q2", "probability": 0.2, "outcome": False}])
    assert "n = 2 questions in 2 clusters" in unique["rigor"]["caveats"]


@pytest.mark.usefixtures("isolated_ledgers")
def test_duplicate_forecast_ids_not_double_counted(tmp_path):
    golden = ge.index_golden([
        {"id": "q1", "resolved_outcome": True, "category": "c", "difficulty": "easy"},
        {"id": "q2", "resolved_outcome": False, "category": "c", "difficulty": "easy"},
    ])
    res = ge.match_forecasts([
        {"id": "q1", "probability": 0.9},
        {"id": "q1", "probability": 0.1},       # repeated id: never scored
        {"id": "q2", "probability": 0.2},
        {"id": " q1 ", "probability": 0.5},     # same id after strip
    ], golden)
    assert [r["id"] for r in res["matched"]] == ["q1", "q2"]
    assert res["matched"][0]["probability"] == 0.9         # first row wins
    assert res["duplicate_forecast_ids"] == ["q1"]
    assert ge.score_pairs(res["matched"])["n"] == 2
    # a later row can never replace an invalid first row
    res2 = ge.match_forecasts([{"id": "q1", "probability": 7}, {"id": "q1", "probability": 0.8}], golden)
    assert res2["matched"] == [] and res2["invalid_probability_ids"] == ["q1"]
    assert res2["duplicate_forecast_ids"] == ["q1"]

    # end to end: the report lists the id once under duplicate_forecast_ids
    gpath = _write_json(tmp_path / "golden.json", {"questions": [
        {"id": "q1", "resolved_outcome": True, "category": "c", "difficulty": "easy"},
        {"id": "q2", "resolved_outcome": False, "category": "c", "difficulty": "easy"}]})
    fpath = _write_json(tmp_path / "forecast.json", {"binary_forecasts": [
        {"id": "q1", "probability": 0.9}, {"id": "q1", "probability": 0.9}, {"id": "q2", "probability": 0.2}]})
    out, md = tmp_path / "r.json", tmp_path / "r.md"
    assert ge.cmd_score_forecast_file(_args(forecast=fpath, golden=gpath, out=str(out), markdown=str(md))) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["metrics"]["n"] == 2 and [r["id"] for r in report["matched"]] == ["q1", "q2"]
    assert report["duplicate_forecast_ids"] == ["q1"]
    assert "repeated forecast ids (first row scored, later rows ignored): q1" in md.read_text(encoding="utf-8")
    # rows without dates: horizon unknown, cluster falls back to the id
    assert report["matched"][0]["horizon_days"] is None and report["matched"][0]["horizon_bucket"] == "unknown"
    assert report["matched"][0]["cluster"] == "q1"
    assert list(report["metrics"]["rigor"]["by_horizon"]) == ["unknown"]


@pytest.mark.usefixtures("isolated_ledgers")
def test_duplicate_golden_ids_raise(tmp_path):
    with pytest.raises(ValueError, match="duplicate ids: q1"):
        ge.index_golden([{"id": "q1", "resolved_outcome": True},
                         {"id": " q1", "resolved_outcome": False}])
    assert len(ge.index_golden(ge.load_golden_set())) == 30   # committed ids are unique
    gpath = _write_json(tmp_path / "dup_golden.json", {"questions": [
        {"id": "q1", "resolved_outcome": True}, {"id": "q1", "resolved_outcome": False}]})
    fpath = _write_json(tmp_path / "forecast.json", {"binary_forecasts": [{"id": "q1", "probability": 0.8}]})
    out = tmp_path / "never.json"
    with pytest.raises(ValueError):
        ge.cmd_score_forecast_file(_args(forecast=fpath, golden=gpath, out=str(out)))
    assert not out.exists()


def test_score_ledger_default_reads_evaluation_dir(tmp_path, isolated_ledgers):
    fl = isolated_ledgers                                 # ledgers monkeypatched under tmp_path
    eval_dir = fl.evaluation_ledger_dir()
    assert os.path.abspath(eval_dir) == os.path.abspath(str(tmp_path / "_evaluation_ledger"))
    # default-dir golden appends are redirected to the isolated evaluation ledger
    e1 = append_golden_result(question_id="q1", probability=0.7, resolved_outcome=True,
                              category="elections", as_of_date="2024-11-01", resolution_date="2024-11-06")
    append_golden_result(question_id="q2", probability=0.2, resolved_outcome=False,
                         category="sports", as_of_date="2024-01-01", resolution_date="2024-12-05")
    assert e1["ledger_redirected"] == "evaluation"
    assert read_ledger(fl.ledger_dir()) == [] and len(read_ledger(eval_dir)) == 2

    out, md = tmp_path / "ledger_eval.json", tmp_path / "ledger_eval.md"
    assert ge.cmd_score_ledger(SimpleNamespace(ledger_dir=None, bins=10, out=str(out), markdown=str(md))) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["n_entries"] == 0 and report["n_resolved"] == 0   # production ledger is empty
    assert report["golden"]["n"] == 2                                 # was always 0 before EVAL-7
    assert os.path.abspath(report["eval_ledger_dir"]) == os.path.abspath(eval_dir)
    assert report["brier_scale"] == "multiclass_sum" and report["golden"]["brier_scale"] == "binary"
    assert report["promotion_eligible"] is False
    assert report["golden"]["rigor"]["promotion_eligible"] is False
    assert {k: v["n"] for k, v in report["golden"]["rigor"]["by_horizon"].items()} == {"le30": 1, "gt180": 1}
    # the markdown uses the ledger layout: both scales labelled, golden rigor rendered
    text = md.read_text(encoding="utf-8")
    assert text == ge.render_markdown(report)
    assert text.splitlines()[0] == ge.CHARACTERIZATION_BANNER
    assert "# Forecast-ledger evaluation" in text.splitlines() and "matched / scored" not in text
    assert "| mean Brier (multiclass_sum: summed over scenarios" in text
    assert "\n## Golden section (binary Brier)\n" in text and "(2 scored golden rows)" in text
    headings = [line for line in text.splitlines() if line.startswith("#")]
    golden_at = headings.index("## Golden section (binary Brier)")
    for section in ("Caveats", "Overall", "Reference & skill", "Direction & hedging", "By horizon"):
        assert headings.index(f"### {section}") > golden_at, section   # nested under the golden heading

    # an explicit --ledger-dir naming the production ledger reads golden rows like the
    # default does (the writer redirects explicit production targets too)
    for prod_dir in (fl.ledger_dir(), fl.ledger_dir() + os.sep):
        out_p = tmp_path / "explicit_production.json"
        assert ge.cmd_score_ledger(SimpleNamespace(ledger_dir=prod_dir, bins=10, out=str(out_p),
                                                   markdown=None)) == 0
        prod = json.loads(out_p.read_text(encoding="utf-8"))
        assert prod["golden"]["n"] == 2 and prod["n_entries"] == 0
        assert os.path.abspath(prod["eval_ledger_dir"]) == os.path.abspath(eval_dir)

    # both scales over the same golden rows: the multi-class sum is twice the binary Brier
    out2 = tmp_path / "same_dir.json"
    assert ge.cmd_score_ledger(SimpleNamespace(ledger_dir=eval_dir, bins=10, out=str(out2), markdown=None)) == 0
    same = json.loads(out2.read_text(encoding="utf-8"))
    assert same["golden"]["n"] == 2 and same["eval_ledger_dir"] == eval_dir
    assert same["mean_brier"] == pytest.approx(2 * same["golden"]["mean_brier"], abs=1e-3)

    # --eval-ledger-dir overrides both defaults for the golden section only
    other = str(tmp_path / "other_eval")
    append_golden_result(question_id="q9", probability=0.6, resolved_outcome=True, d=other)
    out3 = tmp_path / "override.json"
    assert ge.cmd_score_ledger(SimpleNamespace(ledger_dir=None, eval_ledger_dir=other, bins=10,
                                               out=str(out3), markdown=None)) == 0
    over = json.loads(out3.read_text(encoding="utf-8"))
    assert over["golden"]["n"] == 1 and over["eval_ledger_dir"] == other and over["n_entries"] == 0

    # an empty golden section still carries its scale label
    empty_dir = str(tmp_path / "empty")
    out4 = tmp_path / "empty.json"
    assert ge.cmd_score_ledger(SimpleNamespace(ledger_dir=empty_dir, bins=10, out=str(out4), markdown=None)) == 0
    assert json.loads(out4.read_text(encoding="utf-8"))["golden"] == {"n": 0, "brier_scale": "binary"}
    empty_md = ge.render_markdown(json.loads(out4.read_text(encoding="utf-8")))
    assert "## Golden section (binary Brier)" in empty_md and "No resolved golden rows in this ledger." in empty_md


@pytest.mark.usefixtures("isolated_ledgers")
def test_cli_wires_bootstrap_and_eval_ledger_dir(tmp_path, monkeypatch):
    fpath = _constant_forecast(tmp_path, 0.8)
    out = tmp_path / "cli.json"
    monkeypatch.setattr(sys, "argv", ["golden_eval.py", "score-forecast-file", "--forecast", fpath,
                                      "-o", str(out), "--bootstrap", "40"])
    assert ge.main() == 0
    rigor = json.loads(out.read_text(encoding="utf-8"))["metrics"]["rigor"]
    assert rigor["ci"]["B"] == 40 and rigor["reference"]["bss"] == 0.0

    other = str(tmp_path / "cli_eval")
    append_golden_result(question_id="q1", probability=0.7, resolved_outcome=True, d=other)
    out2 = tmp_path / "cli_ledger.json"
    monkeypatch.setattr(sys, "argv", ["golden_eval.py", "score-ledger", "--ledger-dir", str(tmp_path / "prod"),
                                      "--eval-ledger-dir", other, "-o", str(out2)])
    assert ge.main() == 0
    assert json.loads(out2.read_text(encoding="utf-8"))["golden"]["n"] == 1
    monkeypatch.setattr(sys, "argv", ["golden_eval.py", "score-forecast-file", "--forecast", fpath,
                                      "--bootstrap", "-3"])
    with pytest.raises(SystemExit):
        ge.main()


@pytest.mark.usefixtures("isolated_ledgers")
def test_outputs_written_atomically(tmp_path, monkeypatch):
    import app.utils.atomic as atomic

    gpath, fpath = _legacy_fixture(tmp_path)
    out, md = tmp_path / "eval_report.json", tmp_path / "eval_report.md"
    calls = []
    real_json, real_text = ge.write_json_atomic, ge.write_text_atomic
    monkeypatch.setattr(ge, "write_json_atomic",
                        lambda path, obj, **kw: (calls.append(("json", path)), real_json(path, obj, **kw))[1])
    monkeypatch.setattr(ge, "write_text_atomic",
                        lambda path, text, **kw: (calls.append(("text", path)), real_text(path, text, **kw))[1])
    assert ge.cmd_score_forecast_file(_args(forecast=fpath, golden=gpath, out=str(out), markdown=str(md))) == 0
    assert calls == [("json", str(out)), ("text", str(md))]
    report = json.loads(out.read_text(encoding="utf-8"))
    # same bytes the legacy json.dumps(..., ensure_ascii=False, indent=2) writer produced
    assert out.read_text(encoding="utf-8") == json.dumps(report, ensure_ascii=False, indent=2)
    assert md.read_text(encoding="utf-8") == ge.render_markdown(report)
    assert not [p for p in os.listdir(tmp_path) if p.startswith(".tmp-")]

    # a failed rename leaves the previous report intact and no temp file behind
    out.write_text("PREVIOUS", encoding="utf-8")

    def _boom(src, dst):
        raise OSError("simulated crash before rename")

    # only app.utils.atomic sees the failing rename; the process-wide os module is untouched
    monkeypatch.setattr(atomic, "os", SimpleNamespace(**{**vars(os), "replace": _boom}))
    with pytest.raises(OSError, match="simulated crash"):
        ge.cmd_score_forecast_file(_args(forecast=fpath, golden=gpath, out=str(out)))
    assert os.replace is not _boom
    assert out.read_text(encoding="utf-8") == "PREVIOUS"
    assert not [p for p in os.listdir(tmp_path) if p.startswith(".tmp-")]


# ------------------------------------------------------------------ EVAL-12 probe report
PROBE_BACKBONE = {"provider": "deepseek", "model": "deepseek-chat"}


def _probe_report(tmp_path, golden_path, flagged, status="flagged", **over):
    report = {"schema": "drf.golden_probe.v1", "golden_sha256": ge._file_sha256(str(golden_path)),
              "backbone": PROBE_BACKBONE, "closed_book_attested": True,
              "summary": {"status": status, "flagged_ids": flagged, "inconclusive_reasons": []}}
    report.update(over)
    return _write_json(tmp_path / "probe_report.json", report)


@pytest.mark.usefixtures("isolated_ledgers")
def test_probe_report_split_sums_and_mismatch(tmp_path):
    gpath, fpath = _legacy_fixture(tmp_path)
    out, md = tmp_path / "r.json", tmp_path / "r.md"
    probe = _probe_report(tmp_path, gpath, ["q1", "q3"])
    assert ge.cmd_score_forecast_file(_args(forecast=fpath, golden=gpath, out=str(out), markdown=str(md),
                                            probe_report=probe)) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["contamination"] == {"status": "flagged", "flagged_ids": ["q1", "q3"], "probe_run": probe,
                                       "backbone": PROBE_BACKBONE, "closed_book_attested": True}
    assert report["metrics_flagged"]["n"] + report["metrics_unflagged"]["n"] == report["metrics"]["n"]
    assert report["metrics_flagged"]["n"] == 2
    # The markdown names the status, the probe backbone and the split.
    line = (f"- contamination: **flagged** (probe `{probe}`, backbone deepseek/deepseek-chat); "
            f"flagged n=2, unflagged n={report['metrics']['n'] - 2}")
    assert line in md.read_text(encoding="utf-8").splitlines()
    # A probe report for another golden file: recorded, no split.
    other = _write_json(tmp_path / "other_golden.json", {"questions": []})
    mismatch = _probe_report(tmp_path, other, ["q1"])
    assert ge.cmd_score_forecast_file(_args(forecast=fpath, golden=gpath, out=str(out), markdown=str(md),
                                            probe_report=mismatch)) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["contamination"] == {"status": "probe_mismatch", "probe_run": mismatch}
    assert "metrics_flagged" not in report and "metrics_unflagged" not in report
    assert any(ln.startswith("- contamination: **probe_mismatch**") for ln in md.read_text(encoding="utf-8").splitlines())


@pytest.mark.usefixtures("isolated_ledgers")
@pytest.mark.parametrize("over", [{"schema": "drf.golden_probe.v0"}, {"schema": None}])
def test_probe_report_wrong_schema_fails_loud(tmp_path, over):
    gpath, fpath = _legacy_fixture(tmp_path)
    probe = _probe_report(tmp_path, gpath, ["q1"], **over)
    with pytest.raises(ValueError, match="drf.golden_probe.v1"):
        ge.cmd_score_forecast_file(_args(forecast=fpath, golden=gpath, out=str(tmp_path / "r.json"),
                                         probe_report=probe))
    assert not (tmp_path / "r.json").exists()
    # not a JSON object at all
    bare = _write_json(tmp_path / "list.json", [1, 2])
    with pytest.raises(ValueError, match="schema None"):
        ge.load_probe_contamination(bare, gpath)


@pytest.mark.usefixtures("isolated_ledgers")
def test_unprobed_status_additive(tmp_path):
    gpath, fpath = _legacy_fixture(tmp_path)
    out, md = tmp_path / "r.json", tmp_path / "r.md"
    assert ge.cmd_score_forecast_file(_args(forecast=fpath, golden=gpath, out=str(out), markdown=str(md))) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["contamination"] == {"status": "unprobed"}
    assert "metrics_flagged" not in report
    # no contamination line: an unprobed markdown renders exactly as before EVAL-12
    assert "contamination" not in md.read_text(encoding="utf-8")


def test_ledger_rows_record_the_probe_verdict_only_when_probed(tmp_path):
    gpath, fpath = _legacy_fixture(tmp_path)
    ldir = str(tmp_path / "eval_ledger")
    probe = _probe_report(tmp_path, gpath, ["q1"])
    assert ge.cmd_score_forecast_file(_args(forecast=fpath, golden=gpath, to_ledger=True, ledger_dir=ldir,
                                            probe_report=probe)) == 0
    rows = {r["question_id"]: r for r in read_ledger(ldir)}
    assert rows["q1"]["contamination"] == {"status": "flagged", "flagged": True, "probe_run": probe,
                                           "backbone": PROBE_BACKBONE}
    assert rows["q2"]["contamination"]["flagged"] is False
    plain = str(tmp_path / "plain_ledger")
    assert ge.cmd_score_forecast_file(_args(forecast=fpath, golden=gpath, to_ledger=True, ledger_dir=plain)) == 0
    assert all("contamination" not in r for r in read_ledger(plain))
