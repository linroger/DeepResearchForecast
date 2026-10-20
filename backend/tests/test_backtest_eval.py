"""Offline tests for backend/scripts/backtest_eval.py (design §7, §8).

The backend is a fake transport, report folders are written under tmp_path, the
resolution ledger is a temporary directory.  No pipeline runs.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import date
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import backtest_eval as be  # noqa: E402
import golden_eval as ge  # noqa: E402
from app.config import Config  # noqa: E402
from app.services import backtest_mode as bm  # noqa: E402

GOLDEN = [
    {"id": "us-pres-2024-trump", "question": "Will Donald Trump win the 2024 US presidential election?",
     "resolution_criteria": "YES if certified with >=270 electoral votes", "resolved_outcome": True,
     "resolution_date": "2024-11-06", "category": "elections", "difficulty": "medium",
     "as_of_date": "2024-11-01", "knowledge_cutoff": "2024-11-06"},
    {"id": "fed-2025-01-cut", "question": "Will the Federal Reserve cut rates at the January 2025 FOMC meeting?",
     "resolution_criteria": "YES if the target range is lowered on 2025-01-29", "resolved_outcome": False,
     "resolution_date": "2025-01-29", "category": "monetary-policy", "difficulty": "easy",
     "as_of_date": "2025-01-15", "knowledge_cutoff": "2025-01-29"},
]


# ------------------------------------------------------------------ requests

def test_request_is_admissible_and_pins_the_question():
    body = be.build_request(GOLDEN[0], "markets", be.Profile(), label="smoke")
    assert body["mode"] == "full" and body["depth"] == "quick" and body["max_rounds"] == 4
    assert "Treat 2024-11-01 as today" in body["prompt"] and GOLDEN[0]["question"] in body["prompt"]
    option = bm.normalize_backtest_request(body["backtest"], today=date(2026, 10, 21))
    assert option["arm"]["name"] == "markets" and option["target"]["golden_id"] == "us-pres-2024-trump"
    assert option["as_of"] == "2024-11-01" and option["run_label"] == "smoke"
    with pytest.raises(ValueError):
        be.build_request(GOLDEN[0], "everything", be.Profile())


def test_selection_and_arms():
    assert [q["id"] for q in be.select_questions(GOLDEN, ["fed-2025-01-cut", "us-pres-2024-trump"])] == [
        "fed-2025-01-cut", "us-pres-2024-trump"]
    assert len(be.select_questions(GOLDEN, None, 1)) == 1
    with pytest.raises(ValueError, match="unknown golden id"):
        be.select_questions(GOLDEN, ["nope"])
    assert be.parse_arms(None) == list(bm.ABLATION_ARMS)
    assert be.parse_arms("markets,markets,production") == ["markets", "production"]
    with pytest.raises(ValueError, match="unknown arm"):
        be.parse_arms("markets,all")


# ------------------------------------------------------------------ mapping

QUESTION = GOLDEN[0]


@pytest.mark.parametrize("rows, method", [
    ([{"id": "F3", "golden_id": "us-pres-2024-trump", "statement": "x", "probability": 0.6}], "golden_id"),
    ([{"id": "F2", "proposition_id": "us-pres-2024-trump", "statement": "x", "probability": 0.6}], "proposition_id"),
    ([{"id": "us-pres-2024-trump", "statement": "x", "probability": 0.6}], "id"),
    ([{"id": "F1", "statement": "Donald Trump wins the 2024 US presidential election.", "probability": 0.6},
      {"id": "F2", "statement": "Turnout exceeds 160 million in 2024.", "probability": 0.3}], "lexical"),
])
def test_mapping_methods(rows, method):
    result = be.map_forecast(rows, QUESTION)
    assert result["method"] == method and result["row"]["probability"] == 0.6


@pytest.mark.parametrize("rows, reason", [
    ([{"id": "F1", "statement": "Kamala Harris wins the 2024 US presidential election.", "probability": 0.5}],
     "no_match"),  # shares the race, not the candidate
    ([{"id": "F1", "statement": "Donald Trump does not win the 2024 presidential election.", "probability": 0.4}],
     "negation_mismatch"),
    ([{"id": "F1", "statement": "Donald Trump wins the 2024 presidential election in Ohio.", "probability": 0.5},
      {"id": "F2", "statement": "Donald Trump wins the 2024 presidential election overall.", "probability": 0.6}],
     "ambiguous"),
    ([], "no_match"),
])
def test_mapping_refusals(rows, reason):
    result = be.map_forecast(rows, QUESTION)
    assert result["row"] is None and result["reason"] == reason


def test_exact_only_mapping_never_guesses():
    rows = [{"id": "F1", "statement": "Donald Trump wins the 2024 US presidential election.", "probability": 0.6}]
    assert be.map_forecast(rows, QUESTION, lexical=False) == {"row": None, "reason": "no_exact_match",
                                                             "best_score": None}


# ------------------------------------------------------------------ runs

class FakeBackend:
    def __init__(self, *, polls_before_done=1, reject=()):
        self.posts: list[dict] = []
        self.gets: list[str] = []
        self.polls_before_done = polls_before_done
        self.reject = set(reject)
        self.seen: dict[str, int] = {}

    def post(self, path, body):
        assert path == "/api/v1/run"
        self.posts.append(body)
        key = (body["backtest"]["target"]["golden_id"], body["backtest"]["arm"])
        if key in self.reject:
            return 400, {"success": False, "error": "backtest 请求无效（invalid backtest request）: nope"}
        return 200, {"success": True, "data": {"pipeline_id": f"pipe_{len(self.posts)}"}}

    def get(self, path):
        self.gets.append(path)
        pid = path.rsplit("/", 1)[1]
        self.seen[pid] = self.seen.get(pid, 0) + 1
        if self.seen[pid] <= self.polls_before_done:
            return 200, {"success": True, "data": {"status": "running"}}
        return 200, {"success": True, "data": {"status": "completed", "report_id": f"report_{pid}"}}


def test_run_batch_submits_waits_and_resumes(tmp_path):
    backend = FakeBackend(reject={("fed-2025-01-cut", "markets")})
    sleeps = []
    records = be.run_batch(GOLDEN, ["research_only", "markets"], be.Profile(), transport=backend,
                           run_dir=str(tmp_path), poll_seconds=5, sleep=sleeps.append, log=lambda m: None)
    assert [(r["golden_id"], r["arm"], r["status"]) for r in records] == [
        ("us-pres-2024-trump", "research_only", "completed"), ("us-pres-2024-trump", "markets", "completed"),
        ("fed-2025-01-cut", "research_only", "completed"), ("fed-2025-01-cut", "markets", "rejected")]
    assert len(backend.posts) == 4 and sleeps == [5, 5, 5]
    manifest = be.read_manifest(str(tmp_path))
    assert {(r["golden_id"], r["arm"]): r["status"] for r in manifest}[("us-pres-2024-trump", "markets")] == "completed"
    # Resume: completed pairs are skipped, the rejected one is submitted again.
    again = FakeBackend(polls_before_done=0)
    be.run_batch(GOLDEN, ["research_only", "markets"], be.Profile(), transport=again,
                 run_dir=str(tmp_path), sleep=lambda s: None, log=lambda m: None)
    assert [(b["backtest"]["target"]["golden_id"], b["backtest"]["arm"]) for b in again.posts] == [
        ("fed-2025-01-cut", "markets")]


def test_a_submitted_pipeline_is_polled_not_resubmitted(tmp_path):
    be._append_manifest(str(tmp_path), {"golden_id": "us-pres-2024-trump", "arm": "markets",
                                        "status": "submitted", "pipeline_id": "pipe_old"})
    backend = FakeBackend(polls_before_done=0)
    records = be.run_batch(GOLDEN[:1], ["markets"], be.Profile(), transport=backend, run_dir=str(tmp_path),
                           sleep=lambda s: None, log=lambda m: None)
    assert backend.posts == [] and backend.gets == ["/api/v1/status/pipe_old"]
    assert records[0]["report_id"] == "report_pipe_old"


def test_a_stuck_pipeline_times_out(tmp_path):
    backend = FakeBackend(polls_before_done=10**6)
    ticks = iter(range(0, 10**6, 100))
    records = be.run_batch(GOLDEN[:1], ["markets"], be.Profile(), transport=backend, run_dir=str(tmp_path),
                           timeout_seconds=250, sleep=lambda s: None, clock=lambda: next(ticks),
                           log=lambda m: None)
    assert records[0]["status"] == "timed_out"


def _run_args(tmp_path, **extra):
    base = dict(golden=ge.GOLDEN_PATH, ids="us-pres-2024-trump", limit=None, arms="research_only,markets",
                depth="quick", max_rounds=4, language="English", lenient=False, archive="wayback", label="",
                base_url="http://127.0.0.1:9", run_dir=str(tmp_path), confirm_paid=False,
                max_pipelines=8, poll_seconds=1.0, timeout_hours=0.01)
    base.update(extra)
    return SimpleNamespace(**base)


def test_run_refuses_without_confirmation_or_over_the_cap(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(be, "ApiTransport", lambda *a, **k: pytest.fail("contacted a backend"))
    assert be.cmd_run(_run_args(tmp_path)) == 2
    assert "--confirm-paid" in capsys.readouterr().err
    assert be.cmd_run(_run_args(tmp_path, confirm_paid=True, ids=None, limit=5)) == 2
    assert "exceed --max-pipelines 8" in capsys.readouterr().err
    assert not (tmp_path / be.MANIFEST).exists()


# ------------------------------------------------------------------ scoring

def _forecast(as_of, rows):
    return {"binary_forecasts": rows, "backtest": {"version": bm.BACKTEST_VERSION, "as_of": as_of}}


FORECASTS = {
    "r_trump_base": _forecast("2024-11-01", [{"id": "F1", "golden_id": "us-pres-2024-trump",
                                              "statement": "Trump wins", "probability": 0.5}]),
    "r_trump_mkt": _forecast("2024-11-01", [{"id": "F1", "golden_id": "us-pres-2024-trump",
                                             "statement": "Trump wins", "probability": 0.6}]),
    "r_fed_base": _forecast("2025-01-15", [{"id": "F4", "proposition_id": "fed-2025-01-cut",
                                            "statement": "Fed cuts", "probability": 0.3}]),
    "r_fed_mkt": _forecast("2025-01-15", [{"id": "F1", "statement": "The Federal Reserve cuts rates at the "
                                           "January 2025 FOMC meeting.", "probability": 0.1},
                                          {"id": "F2", "statement": "Fed cuts in January 2025", "probability": 0.9}]),
    "r_live": {"binary_forecasts": [{"id": "F1", "golden_id": "us-pres-2024-trump", "probability": 0.99}]},
}


def _records():
    rows = [("us-pres-2024-trump", "research_only", "r_trump_base"), ("us-pres-2024-trump", "markets", "r_trump_mkt"),
            ("fed-2025-01-cut", "research_only", "r_fed_base"), ("fed-2025-01-cut", "markets", "r_fed_mkt"),
            ("us-pres-2024-trump", "simulation", "r_live")]
    out = [{"golden_id": g, "arm": a, "status": "completed", "report_id": r, "pipeline_id": "p"} for g, a, r in rows]
    out.append({"golden_id": "fed-2025-01-cut", "arm": "simulation", "status": "failed", "error": "provider outage"})
    return out


def test_score_runs_per_arm_with_deltas_and_knowledge_split():
    report = be.score_runs(_records(), GOLDEN, forecast_loader=FORECASTS.get, model_cutoff="2024-12-31")
    base, markets, simulation = (report["arms"][arm] for arm in ("research_only", "markets", "simulation"))
    assert base["scored"] == 2 and base["match_methods"] == {"golden_id": 1, "proposition_id": 1}
    assert base["metrics"]["mean_brier"] == pytest.approx((0.25 + 0.09) / 2, abs=1e-4)
    assert markets["metrics"]["mean_brier"] == pytest.approx((0.16 + 0.01) / 2, abs=1e-4)
    assert markets["unmatched"] == [] and markets["match_methods"] == {"golden_id": 1, "lexical": 1}
    delta = report["ablation"]["deltas"]["markets"]
    assert delta["n_pairs"] == 2 and delta["better"] == 2 and delta["mean_brier_delta"] == pytest.approx(-0.085)
    assert delta["mean_log_score_delta"] > 0
    # The live forecast (no backtest block) and the failed run are reported, never scored.
    assert simulation["scored"] == 0 and {item["reason"] for item in simulation["not_scored"]} == {
        "not_a_backtest_forecast_for_this_question", "run_failed"}
    assert report["ablation"]["deltas"]["simulation"] == {"n_pairs": 0}
    split = base["knowledge_split"]["ids"]
    assert split == {"post_model_cutoff": ["fed-2025-01-cut"], "pre_model_cutoff": ["us-pres-2024-trump"],
                     "unknown": []}
    assert report["ablation"]["order"] == ["research_only", "markets", "simulation"]
    assert {row["arm"] for row in report["questions"]} == {"research_only", "markets"}


def test_a_report_at_another_cutoff_is_not_evidence():
    wrong = {"r": _forecast("2024-10-01", [{"golden_id": "us-pres-2024-trump", "probability": 0.7}])}
    report = be.score_runs([{"golden_id": "us-pres-2024-trump", "arm": "markets", "status": "completed",
                             "report_id": "r"}], GOLDEN, forecast_loader=wrong.get)
    assert report["arms"]["markets"]["scored"] == 0
    assert report["arms"]["markets"]["not_scored"][0]["reason"] == "not_a_backtest_forecast_for_this_question"


def test_cmd_score_writes_report_and_markdown(tmp_path):
    reports = tmp_path / "reports"
    for rid, forecast in FORECASTS.items():
        (reports / rid).mkdir(parents=True)
        (reports / rid / "forecast.json").write_text(json.dumps(forecast), encoding="utf-8")
    golden = tmp_path / "golden.json"
    golden.write_text(json.dumps({"questions": GOLDEN}), encoding="utf-8")
    for record in _records():
        be._append_manifest(str(tmp_path / "runs"), record)
    args = SimpleNamespace(run_dir=str(tmp_path / "runs"), golden=str(golden), reports_dir=str(reports),
                           model_knowledge_cutoff="2024-12-31", bins=10, exact_only=False,
                           out=str(tmp_path / "eval_report.json"), markdown=str(tmp_path / "eval_report.md"))
    assert be.cmd_score(args) == 0
    report = json.loads((tmp_path / "eval_report.json").read_text(encoding="utf-8"))
    assert set(report["arms"]) == {"research_only", "markets", "simulation"}
    assert report["arms"]["markets"]["metrics"]["calibration"]["ece"] is not None
    md = (tmp_path / "eval_report.md").read_text(encoding="utf-8")
    assert "## Paired against research_only" in md and "## Model-knowledge split" in md and "## Not scored" in md
    args.exact_only = True
    assert be.cmd_score(args) == 0
    exact = json.loads((tmp_path / "eval_report.json").read_text(encoding="utf-8"))
    assert exact["arms"]["markets"]["scored"] == 1  # the lexical match is no longer taken


def test_load_forecast_rejects_odd_ids(tmp_path):
    assert be.load_forecast(str(tmp_path), "../etc") is None and be.load_forecast(str(tmp_path), "missing") is None


# ------------------------------------------------------------------ forward testing

def _forward(**extra):
    question = {"id": "unrate-2026-11", "question": "Will the US unemployment rate for November 2026 be at least 4.5%?",
                "resolution_criteria": "fred:UNRATE 2026-11 >= 4.5", "asked_on": "2026-10-21",
                "resolution_date": "2026-12-04",
                "resolution_source": {"kind": "official_data", "series": "fred:UNRATE", "observation": "2026-11",
                                      "comparator": ">=", "threshold": 4.5}}
    question.update(extra)
    return question


def test_forward_question_checks():
    assert be.check_forward_question(_forward()) == []
    assert "horizon 7 days" in be.check_forward_question(_forward(resolution_date="2026-10-28"))[0]
    assert "horizon 141 days" in be.check_forward_question(_forward(resolution_date="2027-03-11"))[0]
    assert be.check_forward_question(_forward(resolution_source={"kind": "polymarket", "market_id": "253591"})) == []
    assert "numeric market_id" in be.check_forward_question(
        _forward(resolution_source={"kind": "polymarket", "market_id": "REPLACE"}))[0]
    assert "kind must be" in be.check_forward_question(_forward(resolution_source={}))[0]
    prompt = be.forward_prompt(_forward())
    assert "fred:UNRATE for 2026-11 (>= 4.5)" in prompt and "2026-12-04" in prompt


def test_forward_template_checks(capsys, tmp_path):
    args = SimpleNamespace(questions=be.FORWARD_TEMPLATE, include_examples=False)
    assert be.cmd_forward_check(args) == 0  # examples are skipped by default
    args.include_examples = True
    assert be.cmd_forward_check(args) == 1  # the market example still needs its id
    out = capsys.readouterr().out
    assert "✓ example-us-unemployment-2026-11" in out and "✗ example-polymarket-market" in out
    custom = tmp_path / "forward.json"
    custom.write_text(json.dumps({"questions": [_forward()]}), encoding="utf-8")
    assert be.cmd_forward_check(SimpleNamespace(questions=str(custom), include_examples=False)) == 0


def test_forward_score_reads_market_and_data_resolutions(tmp_path):
    from app.services import forecast_ledger
    ledger = str(tmp_path)
    forecast_ledger.append_market_resolution(report_id="r1", forecast_id="F1", market_id="m1", resolved_outcome="Yes",
                                             model_p=0.7, market_p_at_research=0.6, brier_contribution=0.09,
                                             resolved_at="2026-12-01", d=ledger)
    forecast_ledger.append_market_resolution(report_id="r1", forecast_id="F2", market_id="m2", resolved_outcome=None,
                                             model_p=0.4, market_p_at_research=0.5, brier_contribution=None,
                                             resolved_at="2026-12-01", d=ledger)
    forecast_ledger.append_data_resolution({"report_id": "r2", "forecast_id": "F1", "series": "fred:UNRATE",
                                            "observation": {"date": "2026-11-01", "value": 4.6},
                                            "model_p": 0.2, "resolved_outcome": True}, d=ledger)
    report = be.forward_score(ledger)
    assert report["metrics"]["n"] == 2 and report["skipped_unusable"] == 1
    assert report["metrics"]["mean_brier"] == pytest.approx((0.09 + 0.64) / 2, abs=1e-4)
    assert report["metrics"]["by_category"].keys() == {"market", "official_data"}


def test_autorun_setting_drives_the_monitor_schedule(monkeypatch):
    """RESOLUTION_MONITOR_AUTORUN_HOURS=24 (the forward-testing setting) runs the
    monitor once after the start delay, then waits a day."""
    import app.services.resolution_autorun as ra
    monkeypatch.setattr(Config, "RESOLUTION_MONITOR_AUTORUN_HOURS", 24.0, raising=False)
    fired = threading.Event()
    count = {"n": 0}
    monkeypatch.setattr(ra, "trigger_once", lambda: count.__setitem__("n", count["n"] + 1) or fired.set() or True)
    thread = ra.start(initial_delay_s=0.01)
    assert thread is not None
    try:
        assert fired.wait(2.0)
        assert not thread._drf_stop_event.wait(0.3) and count["n"] == 1  # noqa: SLF001 — next run is a day away
    finally:
        thread._drf_stop_event.set()  # noqa: SLF001
        thread.join(timeout=2.0)
    assert not thread.is_alive()
