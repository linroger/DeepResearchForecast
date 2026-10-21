"""Offline unit tests for the golden-question forecast-quality harness (EVAL-1).

All tests are offline and deterministic — no LLM, no network. They exercise the
pure scoring core (binary Brier / log-score / ECE bins / matching / breakdowns),
the golden-set fixture integrity, and the ledger bridge (append_golden_result →
calibration_summary). Known-value fixtures pin the math.
"""

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


# ------------------------------------------------- model-knowledge leakage (backtest §6)
def test_golden_set_carries_knowledge_cutoffs():
    for q in ge.load_golden_set():
        assert q["knowledge_cutoff"] > q["as_of_date"], q["id"]
        assert q["knowledge_cutoff"] == q["resolution_date"], q["id"]


def test_knowledge_cutoff_is_validated(tmp_path):
    bad = tmp_path / "bad.json"
    row = {"id": "x", "resolved_outcome": True, "as_of_date": "2024-11-01"}
    for value in ("Nov 6", "2024-02-30", "2024-11-01", "2024-10-01"):
        bad.write_text(json.dumps({"questions": [dict(row, knowledge_cutoff=value)]}), encoding="utf-8")
        with pytest.raises(ValueError):
            ge.load_golden_set(str(bad))


def test_knowledge_groups_and_split():
    assert ge.knowledge_group("2025-03-01", "2025-01-31") == "post_model_cutoff"
    assert ge.knowledge_group("2025-01-31", "2025-01-31") == "pre_model_cutoff"  # the data includes that day
    assert ge.knowledge_group("2024-11-06", None) == "unknown"
    assert ge.knowledge_group(None, "2025-01-31") == "unknown"
    rows = [{"id": "a", "probability": 0.9, "outcome": True, "knowledge_cutoff": "2024-11-06"},
            {"id": "b", "probability": 0.2, "outcome": True, "knowledge_cutoff": "2025-06-01"},
            {"id": "c", "probability": 0.5, "outcome": False}]
    split = ge.knowledge_split(rows, "2025-01-31")
    assert split["ids"] == {"post_model_cutoff": ["b"], "pre_model_cutoff": ["a"], "unknown": ["c"]}
    assert split["groups"]["post_model_cutoff"]["mean_brier"] == pytest.approx(0.64)
    assert split["groups"]["pre_model_cutoff"]["mean_brier"] == pytest.approx(0.01)
    unknown = ge.knowledge_split(rows, None)
    assert unknown["ids"]["unknown"] == ["a", "b", "c"] and "not given" in unknown["note"]


def test_model_knowledge_cutoff_input(monkeypatch):
    monkeypatch.delenv("GOLDEN_MODEL_KNOWLEDGE_CUTOFF", raising=False)
    assert ge.model_knowledge_cutoff(None) is None
    monkeypatch.setenv("GOLDEN_MODEL_KNOWLEDGE_CUTOFF", "2025-01-31")
    assert ge.model_knowledge_cutoff(None) == "2025-01-31"
    assert ge.model_knowledge_cutoff("2024-06-30") == "2024-06-30"
    with pytest.raises(ValueError):
        ge.model_knowledge_cutoff("June 2024")


def test_score_forecast_file_reports_the_knowledge_split(tmp_path, monkeypatch):
    monkeypatch.delenv("GOLDEN_MODEL_KNOWLEDGE_CUTOFF", raising=False)
    golden = {"questions": [
        {"id": "old", "question": "?", "resolution_criteria": "x", "resolved_outcome": True,
         "resolution_date": "2024-11-06", "as_of_date": "2024-11-01", "knowledge_cutoff": "2024-11-06"},
        {"id": "new", "question": "?", "resolution_criteria": "x", "resolved_outcome": False,
         "resolution_date": "2026-03-01", "as_of_date": "2026-02-01", "knowledge_cutoff": "2026-03-01"},
    ]}
    gpath = tmp_path / "golden.json"
    gpath.write_text(json.dumps(golden), encoding="utf-8")
    fpath = tmp_path / "forecast.json"
    fpath.write_text(json.dumps({"binary_forecasts": [{"id": "old", "probability": 0.8},
                                                      {"id": "new", "probability": 0.3}]}), encoding="utf-8")
    out, md = tmp_path / "eval_report.json", tmp_path / "eval_report.md"
    args = SimpleNamespace(forecast=str(fpath), golden=str(gpath), bins=10, out=str(out), markdown=str(md),
                           to_ledger=False, ledger_dir=str(tmp_path / "ledger"),
                           model_knowledge_cutoff="2025-06-30")
    assert ge.cmd_score_forecast_file(args) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["knowledge_split"]["ids"]["post_model_cutoff"] == ["new"]
    assert report["knowledge_split"]["ids"]["pre_model_cutoff"] == ["old"]
    assert [row["knowledge_cutoff"] for row in report["matched"]] == ["2024-11-06", "2026-03-01"]
    assert "## Model-knowledge split" in md.read_text(encoding="utf-8")
