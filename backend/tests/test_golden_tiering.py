"""EVAL-8: golden headline tiering in backend/scripts/golden_eval.py.

A golden Brier is a skill estimate only over rows the run could not look up. Every
matched row is tiered from the run's provenance (run.json / pipeline_state.json
created_at, dated through the run's last recorded activity, from a pipeline that
wrote the scored report; the TIME-7 hindcast pin; or --run-created-at): only
``prospective`` rows (run before the resolution date and no later than as_of +
the lead tolerance, never a pinned hindcast) reach the ``headline``; every other row is
under ``characterization.by_tier``; ``metrics`` keeps every matched row. A
headline without eligible rows is withheld and ``--require-headline`` exits 5.
When only the run's last activity cannot be dated, created_at is a lower bound (a row
resolved on or before it is exposed, any other row unknown). ``--to-ledger`` records
each tier's ``golden_tier_source``; an unreadable lead tolerance fails loud.
With GOLDEN_HEADLINE_GATE=false every output is byte-identical to the pre-EVAL-8
code.

Offline and deterministic: tmp ledgers, synthetic golden sets and pipeline dirs.
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import date
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import golden_eval as ge  # noqa: E402

from app.config import Config  # noqa: E402
from app.services import hindcast_policy as hp  # noqa: E402
from app.services.forecast_ledger import append_golden_result, evaluation_ledger_dir, read_ledger  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HINDCAST = "hindcast_retrieval_exposed"
# sha256 of what the pre-EVAL-8 golden_eval (feat/finharness-transplants@e57b26d) wrote
# for _legacy_files() scored with --to-ledger into a tmp evaluation ledger:
# the score-forecast-file report (canonical JSON, sorted keys, compact; forecast/golden
# paths replaced by "<forecast>"/"<golden>") and its markdown (same replacement), the
# ledger.jsonl bytes, and the score-ledger report (ledger dirs replaced by "<ledger>")
# and markdown over that ledger.
PRE_EVAL8_REPORT_SHA256 = "1a73902c047c1775309e6d933ae0d1a73e6d823c715cc8fdb02c977e4859ff7f"
PRE_EVAL8_MARKDOWN_SHA256 = "05893386c1bc6167dedd004d1080debd83852f1a06bcfee9760ef1a5bd481b21"
PRE_EVAL8_LEDGER_SHA256 = "a312724ad670735bcf223039ac3aa37ca9c472628d6005279769a3ae6c3878a3"
PRE_EVAL8_LEDGER_REPORT_SHA256 = "778291cba47ea9b07e477d68925a7017b90ae75164801722d7c3e14a03fdb5a3"
PRE_EVAL8_LEDGER_MARKDOWN_SHA256 = "5bc6e7c6e1a1b6a955556794374d811ab1cf128785a09b1c363601add18b6f34"
RUN_AT = "2026-09-28T10:00:00+00:00"
# The report directory the scored forecasts sit in, named as report_id by _state().
REPORT_ID = "report_eval8"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Ledgers under tmp_path, the GOLDEN_EVAL_LEDGER opt-in off, EVAL-8 knobs at their defaults."""
    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(tmp_path / "_forecast_ledger"), raising=False)
    monkeypatch.setattr(Config, "GOLDEN_EVAL_LEDGER", False, raising=False)
    monkeypatch.setattr(Config, "GOLDEN_HEADLINE_GATE", True, raising=False)
    monkeypatch.setattr(Config, "GOLDEN_PROSPECTIVE_LEAD_TOLERANCE_DAYS", 7, raising=False)


def _write_json(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


def _args(**kw):
    base = {"bins": 10, "out": None, "markdown": None, "to_ledger": False, "ledger_dir": None}
    base.update(kw)
    return SimpleNamespace(**base)


def _q(qid, as_of, resolution, outcome, category="c", difficulty="easy"):
    return {"id": qid, "question": f"{qid.upper()}?", "resolution_criteria": "x", "resolved_outcome": outcome,
            "as_of_date": as_of, "resolution_date": resolution, "category": category, "difficulty": difficulty}


def _report_forecast(tmp_path, fc, report_id=REPORT_ID):
    """``fc`` written where a pipeline writes it: reports/<report_id>/forecast.json."""
    d = tmp_path / "reports" / report_id
    d.mkdir(parents=True, exist_ok=True)
    return _write_json(d / "forecast.json", fc)


def _mixed_files(tmp_path):
    """Two prospective rows (as_of + 3 and the inclusive + 7), one late origin, one hindcast
    for a run on 2026-09-28."""
    golden = {"questions": [
        _q("p1", "2026-09-25", "2026-12-31", True),
        _q("p2", "2026-09-21", "2027-01-15", False),
        _q("l1", "2026-09-20", "2026-12-31", True),
        _q("h1", "2024-10-01", "2024-11-06", True),
    ]}
    fc = {"binary_forecasts": [{"id": "p1", "probability": 0.8}, {"id": "p2", "probability": 0.3},
                               {"id": "l1", "probability": 0.6}, {"id": "h1", "probability": 0.9}]}
    return _write_json(tmp_path / "mixed_golden.json", golden), _report_forecast(tmp_path, fc)


def _legacy_files(tmp_path):
    """The five-question v1 fixture of test_golden_eval._legacy_fixture."""
    golden = {"questions": [
        _q("q1", "2024-11-01", "2024-11-06", True, "elections"),
        _q("q2", "2024-11-01", "2024-11-06", False, "elections"),
        _q("q3", "2024-01-01", "2024-12-05", True, "markets", "hard"),
        _q("q4", "2024-06-01", "2024-08-01", False, "markets", "medium"),
        _q("q5", "2024-05-01", "2024-06-01", True, "sports", "medium"),
    ]}
    fc = {"binary_forecasts": [
        {"id": "q1", "probability": 0.9}, {"id": "q2", "probability": 0.5}, {"id": "q3", "probability": 0.4},
        {"id": "q4", "probability": 0.75}, {"id": "q5", "probability": 0.62}, {"id": "zzz", "probability": 0.3}]}
    return _write_json(tmp_path / "golden.json", golden), _write_json(tmp_path / "forecast.json", fc)


def _state(**kw):
    """A pipeline_state.json created at RUN_AT that wrote REPORT_ID (``kw`` overrides keys)."""
    state = {"pipeline_id": "pipe_eval8", "created_at": RUN_AT, "report_id": REPORT_ID, "options": {}}
    state.update(kw)
    return state


def _pipeline_dir(tmp_path, name="pipe_eval8", run=None, state=None):
    """A pipeline directory holding run.json / pipeline_state.json (None = file absent)."""
    d = tmp_path / name
    d.mkdir()
    if run is not None:
        _write_json(d / "run.json", run)
    if state is not None:
        _write_json(d / "pipeline_state.json", state)
    return str(d)


def _score(tmp_path, gpath, fpath, name="r", **kw):
    out, md = tmp_path / f"{name}.json", tmp_path / f"{name}.md"
    rc = ge.cmd_score_forecast_file(_args(forecast=fpath, golden=gpath, out=str(out), markdown=str(md), **kw))
    return rc, json.loads(out.read_text(encoding="utf-8")), md.read_text(encoding="utf-8")


def _gated_pin(as_of, audit_status=None):
    """A real TIME-7 admission pin whose TIME-8 gates ran, with a TIME-9 research audit."""
    pin = hp.capture_hindcast_policy_v1(as_of, research_engine="v3", today_utc=date(2026, 9, 28))
    pin["pit"]["gates"] = True
    if audit_status:
        pin["research_audit"] = {"status": audit_status, "sha256": "0" * 64}
    return pin


# ------------------------------------------------------------------ classify_tier
def test_classify_tier_boundaries():
    q = {"id": "q", "as_of_date": "2026-10-01", "resolution_date": "2026-12-01"}

    def tier(stamp, tolerance=7, question=q):
        return ge.classify_tier(question, run_created_at=stamp, lead_tolerance_days=tolerance)["tier"]

    assert tier("2026-10-08T23:59:59+00:00") == "prospective"            # as_of + 7 is inclusive
    assert tier("2026-10-09T00:00:00+00:00") == "late_origin"            # as_of + 8
    assert tier("2026-09-01T00:00:00Z") == "prospective"                 # before as_of ('Z' accepted)
    assert tier("2026-11-30T23:59:59+00:00") == "late_origin"            # the day before resolution
    assert tier("2026-12-01T00:00:00+00:00") == HINDCAST                 # run on the resolution day
    assert tier("2027-03-01T00:00:00+00:00") == HINDCAST
    # the UTC date decides: 01:00 at +05:00 is the previous UTC day, 22:00 at -03:00 the next
    assert tier("2026-10-09T01:00:00+05:00") == "prospective"
    assert tier("2026-11-30T22:00:00-03:00") == HINDCAST
    # tolerance 0: only runs on or before the as_of day
    assert tier("2026-10-01T23:00:00+00:00", tolerance=0) == "prospective"
    assert tier("2026-10-02T00:00:00+00:00", tolerance=0) == "late_origin"

    naive = ge.classify_tier(q, run_created_at="2026-10-02T10:00:00", lead_tolerance_days=7)
    assert naive["tier"] == "unknown" and "no UTC offset" in naive["reasons"][0]
    for bad in ("2026-10-02", "yesterday", "", None, 1790000000, "0001-01-01T00:00:00+01:00"):
        res = ge.classify_tier(q, run_created_at=bad, lead_tolerance_days=7)
        assert res["tier"] == "unknown" and res["reasons"], bad
    assert ge.parse_run_created_at(None) == (None, "no run created_at")
    assert ge.parse_run_created_at(1790000000)[1] == "run created_at 1790000000 is not an ISO-8601 string"
    assert "out of range" in ge.parse_run_created_at("0001-01-01T00:00:00+01:00")[1]

    # question dates: a run on or after a known resolution is exposed even without as_of
    assert tier(RUN_AT, question={"resolution_date": "2024-11-06"}) == HINDCAST
    assert tier(RUN_AT, question={"resolution_date": "2026-12-01"}) == "unknown"
    assert tier(RUN_AT, question={"as_of_date": "2026-09-27"}) == "unknown"
    assert tier(RUN_AT, question={"as_of_date": "2026-09-27", "resolution_date": "2026-12-1"}) == "unknown"

    prospective = ge.classify_tier(q, run_created_at="2026-10-03T00:00:00+00:00", lead_tolerance_days=7)
    assert prospective == {"tier": "prospective", "reasons": [
        "run 2026-10-03 precedes resolution 2026-12-01 and is no later than as_of 2026-10-01 + 7 days"]}
    assert ge.classify_tier(q, run_created_at="2026-10-09T00:00:00+00:00", lead_tolerance_days=7)["reasons"] == [
        "run 2026-10-09 is after as_of 2026-10-01 + 7 days (2026-10-08)"]

    # a pinned hindcast is never headline-eligible, whatever the dates, and carries TIME-9's verdict
    pit = ge.classify_tier(q, run_created_at="2026-10-03T00:00:00+00:00", lead_tolerance_days=7,
                           hindcast={"as_of": "2026-10-01", "source": "pipeline_state.json",
                                     "integrity": "date_verified"})
    assert pit["tier"] == "hindcast_pit" and pit["integrity"] == "date_verified"
    assert "point-in-time hindcast at as_of 2026-10-01 (pipeline_state.json)" in pit["reasons"][0]
    no_verdict = ge.classify_tier(q, run_created_at=None, lead_tolerance_days=7,
                                  hindcast={"as_of": None, "source": "forecast.json", "integrity": None})
    assert no_verdict["tier"] == "hindcast_pit" and "integrity" not in no_verdict

    for bad_tolerance in (-1, 1.5, True, "7", None, ge.MAX_LEAD_TOLERANCE_DAYS + 1, 10 ** 9):
        with pytest.raises(ValueError, match="lead tolerance"):
            ge.classify_tier(q, run_created_at=RUN_AT, lead_tolerance_days=bad_tolerance)
    # the largest tolerance is accepted, and as_of + tolerance past date.max clamps instead of raising
    assert ge.MAX_LEAD_TOLERANCE_DAYS == 3650
    assert tier("2026-11-30T00:00:00+00:00", tolerance=3650) == "prospective"
    far = {"as_of_date": "9999-12-01", "resolution_date": "9999-12-31"}
    assert tier("9999-12-30T00:00:00+00:00", tolerance=3650, question=far) == "prospective"
    assert ge.classify_tier(far, run_created_at="9999-12-30T00:00:00+00:00",
                            lead_tolerance_days=3650)["reasons"][0].endswith("as_of 9999-12-01 + 3650 days")

    # the run is dated by the later of created_at and its last activity (a resume keeps created_at)
    def active(created, last):
        return ge.classify_tier(q, run_created_at=created, lead_tolerance_days=7, run_last_activity_at=last)

    assert active("2026-10-03T00:00:00+00:00", "2026-10-09T00:00:00+00:00") == {"tier": "late_origin", "reasons": [
        "run last active 2026-10-09 (created 2026-10-03) is after as_of 2026-10-01 + 7 days (2026-10-08)"]}
    assert active("2026-10-03T00:00:00+00:00", "2026-12-01T00:00:00Z")["tier"] == HINDCAST
    assert active("2026-10-03T00:00:00+00:00", "2026-10-03T23:00:00+00:00")["reasons"][0].startswith(
        "run 2026-10-03 precedes")                                   # same day: worded as before
    assert active("2026-10-03T00:00:00+00:00", "2026-09-01T00:00:00+00:00")["tier"] == "prospective"
    stale = active("2026-10-03T00:00:00+00:00", "2026-10-04T00:00:00")
    assert stale == {"tier": "unknown", "reasons": [
        "run last activity '2026-10-04T00:00:00' has no UTC offset (naive stamps are rejected)",
        "run created 2026-10-03 precedes resolution 2026-12-01, but a later resume or report regeneration "
        "could have seen the outcome"]}
    assert active(None, "2026-10-04T00:00:00+00:00")["reasons"] == ["no run created_at"]

    # an unknown last activity leaves created_at a lower bound (review round 2): a run created on or
    # after resolution is still exposed, any other row is unknown, never prospective or late origin
    def bounded(created, question=q):
        return ge.classify_tier(question, run_created_at=created, lead_tolerance_days=7, last_activity_unknown=True)

    assert bounded("2026-12-01T00:00:00+00:00") == {"tier": HINDCAST, "reasons": [
        "run 2026-12-01 is on or after resolution 2026-12-01: live retrieval and model memory can see the outcome"]}
    assert bounded("2026-10-03T00:00:00+00:00") == {"tier": "unknown", "reasons": [
        "the run's last activity is unknown",
        "run created 2026-10-03 precedes resolution 2026-12-01, but a later resume or report regeneration "
        "could have seen the outcome"]}
    assert bounded("2026-10-20T00:00:00+00:00")["tier"] == "unknown"                  # would be late_origin
    assert active("2026-12-02T00:00:00+00:00", "2026-12-02T00:00:00")["tier"] == HINDCAST   # malformed, but late
    assert bounded(None)["reasons"] == ["no run created_at"]
    assert bounded("2026-10-03T00:00:00+00:00", question={"as_of_date": "2026-10-01"})["reasons"][-1] == (
        "question has no canonical resolution_date")
    assert ge.classify_tier(q, run_created_at=RUN_AT, lead_tolerance_days=7, last_activity_unknown=True,
                            hindcast={"as_of": "2026-10-01", "source": "run.json"})["tier"] == "hindcast_pit"
    with pytest.raises(ValueError, match="mutually exclusive"):
        ge.classify_tier(q, run_created_at=RUN_AT, lead_tolerance_days=7, last_activity_unknown=True,
                         run_last_activity_at=RUN_AT)


# ------------------------------------------------------- committed set, 2026 run
def test_committed_set_all_hindcast_withheld(tmp_path, monkeypatch):
    """Acceptance: a 2026 run over the committed 2024-25 set has no headline; every row is characterization."""
    ids = [q["id"] for q in ge.load_golden_set()]
    fpath = _report_forecast(tmp_path, {"binary_forecasts": [{"id": i, "probability": 0.9} for i in ids]})
    stamp = "2026-09-28T09:15:00.123456+00:00"                      # pipeline_orchestrator._utcnow format
    pdir = _pipeline_dir(tmp_path, run={"pipeline_id": "pipe_eval8", "created_at": stamp, "resolved": {}},
                         state=_state(created_at=stamp))

    rc, report, text = _score(tmp_path, ge.GOLDEN_PATH, fpath, pipeline_dir=pdir)
    assert rc == 0
    h = report["headline"]
    assert h["status"] == "withheld_no_eligible_rows"
    assert h["tier_counts"] == {"prospective": 0, "late_origin": 0, HINDCAST: 30, "hindcast_pit": 0, "unknown": 0}
    assert (h["run_created_at"], h["run_created_at_source"], h["lead_tolerance_days"]) == (stamp, "run.json", 7)
    assert (h["run_last_activity_at"], h["run_last_activity_source"]) == (stamp, "run.json")
    assert (h["pipeline_id"], h["pipeline_dir"]) == ("pipe_eval8", pdir)
    assert h["metrics"]["n"] == 0 and h["metrics"]["mean_brier"] is None
    assert "hindcast" not in h and "provenance_notes" not in h
    by_tier = report["characterization"]["by_tier"]
    assert list(by_tier) == [HINDCAST]
    assert by_tier[HINDCAST]["n"] == 30 and by_tier[HINDCAST]["mean_brier"] == 0.17
    # the legacy block is unchanged and labelled as characterization
    assert report["metrics_scope"] == "all_matched_characterization"
    assert report["metrics"]["n"] == 30 and report["metrics"]["mean_brier"] == 0.17
    assert {r["tier"] for r in report["matched"]} == {HINDCAST}
    assert report["matched"][0]["tier_reasons"][0].startswith("run 2026-09-28 is on or after resolution")

    lines = text.splitlines()
    assert lines[0] == "HEADLINE WITHHELD: 30/30 hindcast (live retrieval + model memory exposed)"
    assert lines[1] == "" and lines[2] == ge.CHARACTERIZATION_BANNER
    assert "## Headline" in lines and "- status: `withheld_no_eligible_rows`" in lines
    assert f"- pipeline: `pipe_eval8` (`{pdir}`)" in lines and ge.HEADLINE_SCOPE_NOTE not in lines
    assert f"| {HINDCAST} | 30 | 0.1700 | 0.8000 | characterization |" in lines
    assert lines.index("## Headline") < lines.index("## Overall")
    assert "### Overall" not in lines                                # no headline metrics when withheld
    assert "| id | category | p(YES) | outcome | Brier | tier |" in lines

    # --require-headline: the same report is written, the exit is 5
    rc5, report5, _ = _score(tmp_path, ge.GOLDEN_PATH, fpath, name="req", pipeline_dir=pdir, require_headline=True)
    assert rc5 == ge.EXIT_HEADLINE_WITHHELD == 5
    assert report5["headline"] == h
    out = tmp_path / "cli.json"
    monkeypatch.setattr(sys, "argv", ["golden_eval.py", "score-forecast-file", "--forecast", fpath,
                                      "--pipeline-dir", pdir, "--require-headline", "-o", str(out)])
    assert ge.main() == 5 and json.loads(out.read_text(encoding="utf-8"))["headline"]["status"] == h["status"]
    monkeypatch.setattr(sys, "argv", ["golden_eval.py", "score-forecast-file", "--forecast", fpath,
                                      "--pipeline-dir", pdir, "-o", str(out)])
    assert ge.main() == 0
    monkeypatch.setattr(sys, "argv", ["golden_eval.py", "score-forecast-file", "--forecast", fpath,
                                      "--pipeline-dir", pdir, "--run-created-at", RUN_AT])
    with pytest.raises(SystemExit):                                  # mutually exclusive provenance
        ge.main()

    # the spec's literal fixture, a pipeline dir holding only run.json: without pipeline_state.json a
    # later resume cannot be ruled out, but created_at is a lower bound and every row resolved before it
    literal = _pipeline_dir(tmp_path, "pipe_literal", run={"pipeline_id": "pipe_literal", "created_at": stamp})
    rc_l, lit, lit_text = _score(tmp_path, ge.GOLDEN_PATH, fpath, name="literal", pipeline_dir=literal)
    lh = lit["headline"]
    assert rc_l == 0 and lh["status"] == "withheld_no_eligible_rows"
    assert lh["tier_counts"] == {"prospective": 0, "late_origin": 0, HINDCAST: 30, "hindcast_pit": 0, "unknown": 0}
    assert (lh["run_created_at"], lh["run_created_at_source"]) == (stamp, "run.json")
    assert lh["run_last_activity_at"] is None and lh["run_last_activity_unknown"] is True
    assert lh["provenance_notes"] == [
        "pipeline_state.json: missing",
        "pipeline_state.json cannot be read, so a resume or report regeneration after created_at cannot be "
        "ruled out: created_at kept as a lower bound only"]
    assert list(lit["characterization"]["by_tier"]) == [HINDCAST]
    lit_lines = lit_text.splitlines()
    assert lit_lines[0] == "HEADLINE WITHHELD: 30/30 hindcast (live retrieval + model memory exposed)"
    assert ("- run last activity: unknown (created_at is a lower bound only: rows resolved on or before it are "
            "hindcast, the rest unknown)") in lit_lines
    assert _score(tmp_path, ge.GOLDEN_PATH, fpath, name="literal_req", pipeline_dir=literal,
                  require_headline=True)[0] == 5


# ------------------------------------------------------------ prospective rows
def test_prospective_synthetic_row_headline_ok(tmp_path, monkeypatch):
    gpath, fpath = _mixed_files(tmp_path)
    rc, report, text = _score(tmp_path, gpath, fpath, run_created_at=RUN_AT, require_headline=True, bootstrap=40)
    assert rc == 0                                                   # ok headline: --require-headline passes
    h = report["headline"]
    assert h["status"] == "ok"
    assert h["tier_counts"] == {"prospective": 2, "late_origin": 1, HINDCAST: 1, "hindcast_pit": 0, "unknown": 0}
    assert (h["run_created_at"], h["run_created_at_source"]) == (RUN_AT, "--run-created-at")
    assert h["run_last_activity_at"] is None and "pipeline_dir" not in h
    assert h["provenance_notes"] == ["--run-created-at: taken as given; a later resume or report "
                                     "regeneration of the run is not checked"]
    hm = h["metrics"]
    assert hm["n"] == 2 and hm["mean_brier"] == 0.065                # (0.2^2 + 0.3^2) / 2 over p1, p2 only
    assert hm["rigor"]["reference"]["bss"] == 0.74
    assert hm["rigor"]["ci"]["B"] == 40 and hm["rigor"]["ci"]["n_clusters"] == 2
    assert ge.HEADLINE_CAVEAT in hm["rigor"]["caveats"] and ge.ANSWER_BEARING_CAVEAT not in hm["rigor"]["caveats"]
    assert ge.ANSWER_BEARING_CAVEAT in report["metrics"]["rigor"]["caveats"]     # the all-matched block keeps it
    assert {r["id"]: r["tier"] for r in report["matched"]} == {
        "p1": "prospective", "p2": "prospective", "l1": "late_origin", "h1": HINDCAST}
    by_tier = report["characterization"]["by_tier"]
    assert list(by_tier) == ["late_origin", HINDCAST]
    assert by_tier["late_origin"]["n"] == 1 and by_tier[HINDCAST]["n"] == 1
    assert report["metrics"]["n"] == 4 and report["metrics"]["rigor"]["ci"]["B"] == 40

    lines = text.splitlines()
    assert lines[0] == "HEADLINE: mean Brier 0.0650 over 2/4 prospective rows (BSS vs climatology 0.7400)"
    assert lines[2] == ge.CHARACTERIZATION_BANNER
    # an ok headline says, right under the banner, which lines the banner covers
    assert lines[3:7] == ["", ge.HEADLINE_SCOPE_NOTE, "", "# Golden-question forecast evaluation"]
    assert "| prospective | 2 | 0.0650 | 1.0000 | headline |" in lines
    assert "| late_origin | 1 | 0.1600 | 1.0000 | characterization |" in lines
    # the headline metrics nest under ## Headline; the all-matched sections follow at ##
    assert lines.index("## Headline") < lines.index("### Overall") < lines.index("## Overall")
    assert any(line.startswith("- metrics scope: `all_matched_characterization`") for line in lines)

    # the tolerance knob is read at scoring time; 0 days leaves no prospective row here
    monkeypatch.setattr(Config, "GOLDEN_PROSPECTIVE_LEAD_TOLERANCE_DAYS", 0, raising=False)
    rc0, zero, text0 = _score(tmp_path, gpath, fpath, name="zero", run_created_at=RUN_AT)
    assert rc0 == 0 and zero["headline"]["status"] == "withheld_no_eligible_rows"
    assert zero["headline"]["tier_counts"]["late_origin"] == 3 and zero["headline"]["lead_tolerance_days"] == 0
    assert text0.splitlines()[0] == ("HEADLINE WITHHELD: 3/4 late origin (run active after as_of + the lead "
                                     "tolerance); 1/4 hindcast (live retrieval + model memory exposed)")
    assert text0.splitlines()[2:5] == [ge.CHARACTERIZATION_BANNER, "", "# Golden-question forecast evaluation"]
    monkeypatch.setattr(Config, "GOLDEN_PROSPECTIVE_LEAD_TOLERANCE_DAYS", 10 ** 9, raising=False)
    with pytest.raises(ValueError, match="lead tolerance"):
        _score(tmp_path, gpath, fpath, name="huge", run_created_at=RUN_AT)
    monkeypatch.setattr(Config, "GOLDEN_PROSPECTIVE_LEAD_TOLERANCE_DAYS", -1, raising=False)
    with pytest.raises(ValueError, match="lead tolerance"):
        _score(tmp_path, gpath, fpath, name="negative", run_created_at=RUN_AT)
    assert not (tmp_path / "negative.json").exists()


def test_hindcast_pin_never_headline_eligible(tmp_path):
    """Integration adjustment: a TIME-7 hindcast run is hindcast_pit whatever its dates."""
    gpath, fpath = _mixed_files(tmp_path)
    run = {"created_at": RUN_AT, "resolved": {}}

    pdir = _pipeline_dir(tmp_path, "pipe_pin", run=run,
                         state=_state(options={"hindcast_policy_v1": _gated_pin("2026-09-25", "date_verified")}))
    rc, report, text = _score(tmp_path, gpath, fpath, name="pin", pipeline_dir=pdir, require_headline=True)
    assert rc == 5
    h = report["headline"]
    assert h["status"] == "withheld_no_eligible_rows"
    assert h["tier_counts"]["hindcast_pit"] == 4 and h["tier_counts"]["prospective"] == 0
    assert h["hindcast"] == {"as_of": "2026-09-25", "source": "pipeline_state.json", "integrity": "date_verified"}
    assert list(report["characterization"]["by_tier"]) == ["hindcast_pit"]
    lines = text.splitlines()
    assert lines[0] == "HEADLINE WITHHELD: 4/4 point-in-time hindcast (model memory exposed)"
    assert ("- pinned hindcast (as_of 2026-09-25, from pipeline_state.json; integrity date_verified): "
            "characterization only") in lines

    # without a research audit the verdict is TIME-6's 'labelled'; a violated audit is leak_suspected
    unaudited = _pipeline_dir(tmp_path, "pipe_unaudited", run=run,
                              state=_state(options={"hindcast_policy_v1": _gated_pin("2026-09-25")}))
    assert _score(tmp_path, gpath, fpath, name="unaudited",
                  pipeline_dir=unaudited)[1]["headline"]["hindcast"]["integrity"] == "labelled"
    # pipeline_state.json unreadable: run.json's as_of_enforcement still marks the hindcast
    enforcement = hp.as_of_enforcement_record(_gated_pin("2026-09-25", "violated"))
    enforced_run = {"created_at": RUN_AT, "resolved": {"as_of_enforcement": enforcement}}
    manifest_only = _pipeline_dir(tmp_path, "pipe_manifest", run=enforced_run)
    mh = _score(tmp_path, gpath, fpath, name="manifest", pipeline_dir=manifest_only)[1]["headline"]
    assert mh["hindcast"] == {"as_of": "2026-09-25", "source": "run.json", "integrity": "leak_suspected"}
    assert mh["tier_counts"]["hindcast_pit"] == 4 and "pipeline_state.json: missing" in mh["provenance_notes"]
    assert mh["run_created_at"] == RUN_AT and mh["run_last_activity_unknown"] is True   # a lower bound only
    # ... and it is read even when the state is readable and carries no pin
    unpinned = _pipeline_dir(tmp_path, "pipe_unpinned", run=enforced_run, state=_state())
    uh = _score(tmp_path, gpath, fpath, name="unpinned", pipeline_dir=unpinned, require_headline=True)
    assert uh[0] == 5 and uh[1]["headline"]["status"] == "withheld_no_eligible_rows"
    assert uh[1]["headline"]["hindcast"] == mh["hindcast"] and uh[1]["headline"]["tier_counts"]["hindcast_pit"] == 4
    # both records: the state pin's verdict wins
    both = _pipeline_dir(tmp_path, "pipe_both", run=enforced_run,
                         state=_state(options={"hindcast_policy_v1": _gated_pin("2026-09-25", "date_verified")}))
    assert _score(tmp_path, gpath, fpath, name="both", pipeline_dir=both)[1]["headline"]["hindcast"] == {
        "as_of": "2026-09-25", "source": "pipeline_state.json", "integrity": "date_verified"}
    # no pipeline dir: the forecast's own hindcast stamp marks it
    with open(fpath, encoding="utf-8") as fh:
        stamped = json.load(fh)
    stamped["hindcast"] = hp.hindcast_forecast_block(_gated_pin("2026-09-25", "date_verified_with_unverifiable"),
                                                     research_audit={"status": "date_verified_with_unverifiable"})
    spath = _write_json(tmp_path / "stamped.json", stamped)
    sh = _score(tmp_path, gpath, spath, name="stamped", run_created_at=RUN_AT)[1]["headline"]
    assert sh["hindcast"] == {"as_of": "2026-09-25", "source": "forecast.json",
                              "integrity": "date_verified_with_unverifiable"}
    assert sh["status"] == "withheld_no_eligible_rows" and sh["tier_counts"]["hindcast_pit"] == 4

    # an as-of equal to today is pinned but live: tiered by its dates
    live_pin = hp.capture_hindcast_policy_v1("2026-09-28", research_engine="v3", today_utc=date(2026, 9, 28))
    assert live_pin["hindcast"] is False
    live = _pipeline_dir(tmp_path, "pipe_live", run=run, state=_state(options={"hindcast_policy_v1": live_pin}))
    lh = _score(tmp_path, gpath, fpath, name="live", pipeline_dir=live)[1]["headline"]
    assert lh["status"] == "ok" and lh["tier_counts"]["prospective"] == 2 and "hindcast" not in lh
    assert "provenance_notes" not in lh
    # a record that is neither a pin nor ruled out as one withholds the run stamp: an odd pin value,
    # options that is not an object, an as_of_enforcement that is not an object
    for name, pipe_run, state, note in (
            ("odd", run, _state(options={"hindcast_policy_v1": {"hindcast": True}}),
             "pipeline_state.json: options.hindcast_policy_v1 is not a recognised pin"),
            ("list_options", run, _state(options=[["hindcast_policy_v1", {"hindcast": True}]]),
             "pipeline_state.json: options is not an object"),
            ("odd_enforcement", {"created_at": RUN_AT, "resolved": {"as_of_enforcement": "2026-09-25"}}, _state(),
             "run.json: resolved.as_of_enforcement is not an object"),
            ("list_resolved", {"created_at": RUN_AT, "resolved": [{"as_of_enforcement": enforcement}]}, _state(),
             "run.json: resolved is not an object")):
        odd = _pipeline_dir(tmp_path, f"pipe_{name}", run=pipe_run, state=state)
        rc_odd, odd_report, _ = _score(tmp_path, gpath, fpath, name=name, pipeline_dir=odd, require_headline=True)
        oh = odd_report["headline"]
        assert rc_odd == 5 and oh["status"] == "withheld_no_provenance" and oh["tier_counts"]["unknown"] == 4, name
        assert oh["run_created_at"] is None and "hindcast" not in oh, name
        assert oh["provenance_notes"] == [f"{note}, so a hindcast cannot be ruled out: run stamp withheld"], name


# ------------------------------------------------- resumed / regenerated runs
def test_resumed_run_dated_by_last_activity(tmp_path):
    """A run created before resolution but resumed or regenerated in place after it is a hindcast:
    the run is dated by its last recorded activity, not by created_at (review round 1)."""
    gpath = _write_json(tmp_path / "resume_golden.json", {"questions": [_q("r1", "2026-09-25", "2026-10-10", True)]})
    fpath = _report_forecast(tmp_path, {"binary_forecasts": [{"id": "r1", "probability": 0.8}]})
    created = "2026-09-28T09:00:00+00:00"
    run = {"pipeline_id": "pipe_eval8", "created_at": created}
    stages = {"research": {"status": "completed", "started_at": "2026-09-28T09:01:00+00:00",
                           "finished_at": "2026-09-28T10:30:00+00:00"},
              "report": {"status": "completed", "started_at": "2026-09-28T11:00:00+00:00",
                         "finished_at": "2026-09-28T12:00:00+00:00"},
              "simulation": {"status": "pending", "started_at": None, "finished_at": None}}

    # untouched after creation: prospective, dated by the report stage's finish
    clean = _pipeline_dir(tmp_path, "pipe_clean", run=run, state=_state(created_at=created, stages=stages))
    rc, report, text = _score(tmp_path, gpath, fpath, name="clean", pipeline_dir=clean, require_headline=True)
    h = report["headline"]
    assert rc == 0 and h["status"] == "ok" and h["tier_counts"]["prospective"] == 1
    assert (h["run_created_at"], h["run_last_activity_at"], h["run_last_activity_source"]) == (
        created, "2026-09-28T12:00:00+00:00", "pipeline_state.json stages.report.finished_at")
    assert "provenance_notes" not in h
    assert ("- run last activity: 2026-09-28T12:00:00+00:00 (pipeline_state.json stages.report.finished_at)"
            in text.splitlines())

    # the review probe: resumed 2026-11-01, research and report re-ran after the 2026-10-10 resolution
    resumed_stages = {"research": {"status": "completed", "started_at": "2026-11-01T07:05:00+00:00",
                                   "finished_at": "2026-11-01T09:00:00+00:00"},
                      "report": {"status": "completed", "started_at": "2026-11-01T09:10:00+00:00",
                                 "finished_at": "2026-11-02T08:00:00+00:00"}}
    resumed = _pipeline_dir(tmp_path, "pipe_resumed", run=run, state=_state(
        created_at=created, stages=resumed_stages,
        options={"resumed_at": "2026-11-01T07:00:00+00:00", "resume_count": 1}))
    rc5, report5, text5 = _score(tmp_path, gpath, fpath, name="resumed", pipeline_dir=resumed,
                                 require_headline=True)
    h5 = report5["headline"]
    assert rc5 == 5 and h5["status"] == "withheld_no_eligible_rows"
    assert h5["tier_counts"] == {"prospective": 0, "late_origin": 0, HINDCAST: 1, "hindcast_pit": 0, "unknown": 0}
    assert (h5["run_created_at"], h5["run_last_activity_at"], h5["run_last_activity_source"]) == (
        created, "2026-11-02T08:00:00+00:00", "pipeline_state.json stages.report.finished_at")
    assert report5["matched"][0]["tier_reasons"] == [
        "run last active 2026-11-02 (created 2026-09-28) is on or after resolution 2026-10-10: "
        "live retrieval and model memory can see the outcome"]
    assert text5.splitlines()[0] == "HEADLINE WITHHELD: 1/1 hindcast (live retrieval + model memory exposed)"

    # each activity stamp alone dates the run: the state's own created_at (later than run.json's), a
    # resume that reached no stage yet, a forced report regeneration, a heartbeat, progress, the
    # ensemble window, a stage still running
    after = "2026-10-10T00:00:00+00:00"
    for i, (extra, field) in enumerate((
            ({"created_at": after}, "created_at"),
            ({"options": {"resumed_at": after}}, "options.resumed_at"),
            ({"options": {"force_report_regen": after}}, "options.force_report_regen"),
            ({"heartbeat_at": after}, "heartbeat_at"),
            ({"last_progress_at": after}, "last_progress_at"),
            ({"options": {"ensemble_wall": {"started_at": created, "finished_at": after}}},
             "options.ensemble_wall.finished_at"),
            ({"stages": {**stages, "graph": {"status": "running", "started_at": after, "finished_at": None}}},
             "stages.graph.started_at"))):
        pdir = _pipeline_dir(tmp_path, f"pipe_after_{i}", run=run, state=_state(**{"created_at": created, **extra}))
        ha = _score(tmp_path, gpath, fpath, name=f"after_{i}", pipeline_dir=pdir)[1]["headline"]
        assert ha["tier_counts"][HINDCAST] == 1 and ha["status"] == "withheld_no_eligible_rows", field
        assert (ha["run_last_activity_at"], ha["run_last_activity_source"]) == (
            after, f"pipeline_state.json {field}"), field

    # a resume before resolution but after as_of + 7 moved the information set: late origin
    late = _pipeline_dir(tmp_path, "pipe_late", run=run, state=_state(
        created_at=created, options={"resumed_at": "2026-10-03T00:00:00+00:00"}))
    lh = _score(tmp_path, gpath, fpath, name="late", pipeline_dir=late)[1]["headline"]
    assert lh["status"] == "withheld_no_eligible_rows" and lh["tier_counts"]["late_origin"] == 1

    # fail closed: a malformed activity record, or no readable pipeline_state.json (run.json alone
    # cannot rule a resume out), leaves created_at a lower bound only (review round 2): r1, resolved
    # after it, is unknown and r0, resolved before it, is exposed; neither is ever prospective
    gpath = _write_json(tmp_path / "bound_golden.json", {"questions": [
        _q("r1", "2026-09-25", "2026-10-10", True), _q("r0", "2026-08-01", "2026-09-01", False)]})
    fpath = _report_forecast(tmp_path, {"binary_forecasts": [{"id": "r1", "probability": 0.8},
                                                             {"id": "r0", "probability": 0.3}]})
    for i, (state, note) in enumerate((
            (_state(created_at="2026-09-28 09:00:00"),
             "pipeline_state.json: created_at '2026-09-28 09:00:00' has no UTC offset (naive stamps are "
             "rejected), so the run's last activity cannot be dated"),
            (_state(created_at=created, options={"resumed_at": "2026-11-01T07:00:00"}),
             "pipeline_state.json: options.resumed_at '2026-11-01T07:00:00' has no UTC offset (naive stamps "
             "are rejected), so the run's last activity cannot be dated"),
            (_state(created_at=created, heartbeat_at=1790000000),
             "pipeline_state.json: heartbeat_at 1790000000 is not an ISO-8601 string, so the run's last "
             "activity cannot be dated"),
            (_state(created_at=created, stages=[stages]),
             "pipeline_state.json: stages is not an object, so the run's last activity cannot be dated"),
            (_state(created_at=created, stages={"report": "completed"}),
             "pipeline_state.json: stages.report is not an object, so the run's last activity cannot be dated"),
            (_state(created_at=created, options={"ensemble_wall": [after]}),
             "pipeline_state.json: options.ensemble_wall is not an object, so the run's last activity cannot "
             "be dated"),
            (None, "pipeline_state.json cannot be read, so a resume or report regeneration after created_at "
                   "cannot be ruled out"))):
        pdir = _pipeline_dir(tmp_path, f"pipe_malformed_{i}", run=run, state=state)
        rc_m, rep_m, _ = _score(tmp_path, gpath, fpath, name=f"malformed_{i}", pipeline_dir=pdir,
                                require_headline=True)
        hm = rep_m["headline"]
        assert rc_m == 5 and hm["status"] == "withheld_no_eligible_rows", note
        assert hm["tier_counts"] == {"prospective": 0, "late_origin": 0, HINDCAST: 1, "hindcast_pit": 0,
                                     "unknown": 1}, note
        assert (hm["run_created_at"], hm["run_created_at_source"]) == (created, "run.json"), note
        assert hm["run_last_activity_at"] is None and hm["run_last_activity_unknown"] is True, note
        assert hm["provenance_notes"][-1] == f"{note}: created_at kept as a lower bound only"
        assert {r["id"]: r["tier"] for r in rep_m["matched"]} == {"r1": "unknown", "r0": HINDCAST}, note
        assert next(r for r in rep_m["matched"] if r["id"] == "r1")["tier_reasons"] == [
            "the run's last activity is unknown",
            "run created 2026-09-28 precedes resolution 2026-10-10, but a later resume or report regeneration "
            "could have seen the outcome"], note
    # ... but a state that also names another report withholds the stamp outright
    mixed = _pipeline_dir(tmp_path, "pipe_malformed_other", run=run,
                          state=_state(created_at=created, heartbeat_at=1790000000, report_id="report_other"))
    hx = _score(tmp_path, gpath, fpath, name="malformed_other", pipeline_dir=mixed)[1]["headline"]
    assert hx["status"] == "withheld_no_provenance" and hx["tier_counts"]["unknown"] == 2
    assert hx["run_created_at"] is None and "run_last_activity_unknown" not in hx
    assert hx["provenance_notes"] == [
        "pipeline_state.json: heartbeat_at 1790000000 is not an ISO-8601 string, so the run's last activity "
        "cannot be dated: run stamp withheld",
        "pipeline_state.json report_id 'report_other' is not the scored forecast's report directory "
        "'report_eval8': run stamp withheld"]


def test_pipeline_must_name_the_scored_report(tmp_path):
    """The pipeline dir must be the run that wrote the scored forecast (its report_id is the forecast's
    report directory), and the headline names it (review round 1)."""
    gpath, fpath = _mixed_files(tmp_path)
    run = {"pipeline_id": "pipe_named", "created_at": RUN_AT}
    named = _pipeline_dir(tmp_path, "pipe_named", run=run, state=_state(pipeline_id="pipe_named"))
    rc, report, text = _score(tmp_path, gpath, fpath, name="named", pipeline_dir=named, require_headline=True)
    h = report["headline"]
    assert rc == 0 and h["status"] == "ok" and (h["pipeline_id"], h["pipeline_dir"]) == ("pipe_named", named)
    assert f"- pipeline: `pipe_named` (`{named}`)" in text.splitlines()
    # a state without a pipeline_id falls back to run.json's
    unlabelled = _pipeline_dir(tmp_path, "pipe_unlabelled", run=run, state=_state(pipeline_id=None))
    assert _score(tmp_path, gpath, fpath, name="unlabelled",
                  pipeline_dir=unlabelled)[1]["headline"]["pipeline_id"] == "pipe_named"

    # another report's forecast (say an older run's, regenerated after resolution) scored with this
    # pipeline dir: the dates vouch for nothing, so the run stamp is withheld
    with open(fpath, encoding="utf-8") as fh:
        other = _report_forecast(tmp_path, json.load(fh), report_id="report_older")
    rc5, other_report, _ = _score(tmp_path, gpath, other, name="other", pipeline_dir=named, require_headline=True)
    oh = other_report["headline"]
    assert rc5 == 5 and oh["status"] == "withheld_no_provenance" and oh["tier_counts"]["unknown"] == 4
    assert oh["run_created_at"] is None and oh["pipeline_id"] == "pipe_named"
    assert oh["provenance_notes"] == ["pipeline_state.json report_id 'report_eval8' is not the scored forecast's "
                                      "report directory 'report_older': run stamp withheld"]
    # a state that names no report cannot vouch for any forecast
    for i, report_id in enumerate((None, "", 7)):
        unnamed = _pipeline_dir(tmp_path, f"pipe_unnamed_{i}", run=run, state=_state(report_id=report_id))
        uh = _score(tmp_path, gpath, fpath, name=f"unnamed_{i}", pipeline_dir=unnamed)[1]["headline"]
        assert uh["status"] == "withheld_no_provenance" and uh["provenance_notes"] == [
            "pipeline_state.json names no report_id, so the scored forecast cannot be tied to this run: "
            "run stamp withheld"], report_id
    # the provenance helper without a forecast path cannot tie the run either
    bare = ge.resolve_run_provenance(pipeline_dir=named)
    assert bare["run_created_at"] is None and bare["notes"] == [
        "no forecast path to tie to this run's report: run stamp withheld"]
    tied = ge.resolve_run_provenance(pipeline_dir=named, forecast_path=fpath)
    assert (tied["run_created_at"], tied["source"], tied["pipeline_id"], tied["notes"]) == (
        RUN_AT, "run.json", "pipe_named", [])


# --------------------------------------------------------------- no provenance
def test_no_provenance_withheld(tmp_path):
    gpath, fpath = _mixed_files(tmp_path)
    rc, report, text = _score(tmp_path, gpath, fpath)                  # neither --pipeline-dir nor a stamp
    assert rc == 0
    h = report["headline"]
    assert h["status"] == "withheld_no_provenance"
    assert h["tier_counts"] == {"prospective": 0, "late_origin": 0, HINDCAST: 0, "hindcast_pit": 0, "unknown": 4}
    assert h["run_created_at"] is None and h["run_created_at_source"] is None
    assert list(report["characterization"]["by_tier"]) == ["unknown"]
    assert text.splitlines()[0] == "HEADLINE WITHHELD: 4/4 unknown provenance"
    assert report["matched"][0]["tier_reasons"] == ["no run created_at"]
    assert _score(tmp_path, gpath, fpath, name="req", require_headline=True)[0] == 5

    # a naive --run-created-at is rejected, never guessed
    naive = _score(tmp_path, gpath, fpath, name="naive", run_created_at="2026-09-28T10:00:00")[1]["headline"]
    assert naive["status"] == "withheld_no_provenance"
    assert naive["provenance_notes"] == [
        "--run-created-at: run created_at '2026-09-28T10:00:00' has no UTC offset (naive stamps are rejected)"]

    # naive stamps in both pipeline files: no provenance
    both_naive = _pipeline_dir(tmp_path, "pipe_naive", run={"created_at": "2026-09-28T10:00:00"},
                               state={"created_at": "2026-09-28 10:00:00", "options": {}})
    bn = _score(tmp_path, gpath, fpath, name="both_naive", pipeline_dir=both_naive)[1]["headline"]
    assert bn["status"] == "withheld_no_provenance" and bn["run_created_at"] is None
    assert [n.split(":")[0] for n in bn["provenance_notes"]] == ["run.json", "pipeline_state.json"]
    # a naive run.json falls back to an aware pipeline_state.json stamp
    fallback = _pipeline_dir(tmp_path, "pipe_fallback", run={"created_at": "2026-09-28T10:00:00"},
                             state=_state(created_at="2026-09-28T02:00:00-05:00"))
    fb = _score(tmp_path, gpath, fpath, name="fallback", pipeline_dir=fallback)[1]["headline"]
    assert (fb["status"], fb["run_created_at"], fb["run_created_at_source"]) == (
        "ok", "2026-09-28T07:00:00+00:00", "pipeline_state.json")
    # a missing run.json falls back too, and says so
    no_manifest = _pipeline_dir(tmp_path, "pipe_no_manifest", state=_state())
    nm = _score(tmp_path, gpath, fpath, name="no_manifest", pipeline_dir=no_manifest)[1]["headline"]
    assert nm["run_created_at_source"] == "pipeline_state.json" and nm["provenance_notes"] == ["run.json: missing"]
    # an empty pipeline dir has no provenance
    empty = _pipeline_dir(tmp_path, "pipe_empty")
    assert _score(tmp_path, gpath, fpath, name="empty",
                  pipeline_dir=empty)[1]["headline"]["status"] == "withheld_no_provenance"

    # a mistyped --pipeline-dir, or both provenance options, fail loud before any write
    out = tmp_path / "never.json"
    with pytest.raises(ValueError, match="is not a directory"):
        ge.cmd_score_forecast_file(_args(forecast=fpath, golden=gpath, out=str(out),
                                         pipeline_dir=str(tmp_path / "missing")))
    with pytest.raises(ValueError, match="mutually exclusive"):
        ge.cmd_score_forecast_file(_args(forecast=fpath, golden=gpath, out=str(out),
                                         pipeline_dir=fallback, run_created_at=RUN_AT))
    assert not out.exists()

    # nothing matched: still exit 3, or 5 under --require-headline
    nothing = _write_json(tmp_path / "nothing.json", {"binary_forecasts": [{"id": "F1", "probability": 0.5}]})
    rc3, r3, t3 = _score(tmp_path, gpath, nothing, name="nothing", run_created_at=RUN_AT)
    assert rc3 == 3 and r3["headline"]["status"] == "withheld_no_eligible_rows"
    assert t3.splitlines()[0] == "HEADLINE WITHHELD: no scored rows"
    assert _score(tmp_path, gpath, nothing, name="nothing_req", run_created_at=RUN_AT,
                  require_headline=True)[0] == 5


# ------------------------------------------------------------- gate disabled
def test_gate_disabled_legacy_keys(tmp_path, monkeypatch):
    """GOLDEN_HEADLINE_GATE=false: report, markdown, ledger rows and score-ledger match the pre-EVAL-8 bytes."""
    monkeypatch.setattr(Config, "GOLDEN_HEADLINE_GATE", False, raising=False)
    gpath, fpath = _legacy_files(tmp_path)
    ldir = str(tmp_path / "eval_ledger")
    pdir = _pipeline_dir(tmp_path, run={"created_at": RUN_AT}, state={"created_at": RUN_AT, "options": {}})
    out, md = tmp_path / "r.json", tmp_path / "r.md"
    assert ge.cmd_score_forecast_file(_args(forecast=fpath, golden=gpath, out=str(out), markdown=str(md),
                                            to_ledger=True, ledger_dir=ldir, bootstrap=0, pipeline_dir=pdir)) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert not {"headline", "characterization", "metrics_scope"} & set(report)
    assert not any("tier" in r for r in report["matched"])
    # EVAL-12's additive contamination block (no --probe-report) is not part of the pre-EVAL-8 bytes.
    assert report.pop("contamination") == {"status": "unprobed"}
    report["forecast_path"], report["golden_path"] = "<forecast>", "<golden>"
    canon = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(canon.encode("utf-8")).hexdigest() == PRE_EVAL8_REPORT_SHA256
    text = md.read_text(encoding="utf-8").replace(fpath, "<forecast>").replace(gpath, "<golden>")
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == PRE_EVAL8_MARKDOWN_SHA256
    assert text.splitlines()[0] == ge.CHARACTERIZATION_BANNER and "HEADLINE" not in text

    ledger_bytes = (tmp_path / "eval_ledger" / "ledger.jsonl").read_bytes()
    assert hashlib.sha256(ledger_bytes).hexdigest() == PRE_EVAL8_LEDGER_SHA256
    assert all("golden_tier" not in row for row in read_ledger(ldir))

    lout, lmd = tmp_path / "l.json", tmp_path / "l.md"
    assert ge.cmd_score_ledger(SimpleNamespace(ledger_dir=ldir, bins=10, out=str(lout), markdown=str(lmd))) == 0
    lrep = json.loads(lout.read_text(encoding="utf-8"))
    assert "headline" not in lrep and "characterization" not in lrep
    lrep["ledger_dir"] = lrep["eval_ledger_dir"] = "<ledger>"
    canon = json.dumps(lrep, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(canon.encode("utf-8")).hexdigest() == PRE_EVAL8_LEDGER_REPORT_SHA256
    ltext = lmd.read_text(encoding="utf-8").replace(ldir, "<ledger>")
    assert hashlib.sha256(ltext.encode("utf-8")).hexdigest() == PRE_EVAL8_LEDGER_MARKDOWN_SHA256

    # asking for a headline the disabled gate cannot give fails closed (status gate_disabled)
    assert ge.cmd_score_forecast_file(_args(forecast=fpath, golden=gpath, require_headline=True,
                                            run_created_at=RUN_AT)) == ge.EXIT_HEADLINE_WITHHELD
    assert ge.HEADLINE_GATE_DISABLED == "gate_disabled"


def test_knob_defaults_and_documentation():
    """The gate defaults on and the tolerance to 7 days (config.py source defaults, read the
    way check_env_drift reads them); both are documented in .env.example."""
    import check_env_drift as ed

    defaults = ed.config_defaults()
    assert defaults["GOLDEN_HEADLINE_GATE"] == "true"
    assert defaults["GOLDEN_PROSPECTIVE_LEAD_TOLERANCE_DAYS"] == "7"
    with open(os.path.join(REPO_ROOT, ".env.example"), encoding="utf-8") as fh:
        documented = fh.read()
    assert "# GOLDEN_HEADLINE_GATE=true " in documented
    assert "# GOLDEN_PROSPECTIVE_LEAD_TOLERANCE_DAYS=7 " in documented


def test_lead_tolerance_fails_loud_when_unreadable(tmp_path, monkeypatch):
    """A tolerance the operator set but Config could not read fails loud; it never falls back to a more
    lenient 7 days (review round 2). INFRA-14's import audit pops an unparseable value (Config then
    holds the default) and records it; without app.config the variable is parsed here."""
    import app.config as app_config
    from app.config_audit import sanitize_numeric_env

    knob = "GOLDEN_PROSPECTIVE_LEAD_TOLERANCE_DAYS"
    for bad in ("abc", "0d"):
        environ = {knob: bad}
        issues = sanitize_numeric_env(environ, app_config.CONFIG_KNOBS)
        assert environ == {} and [issue.knob for issue in issues] == [knob]          # popped: Config reads 7
        monkeypatch.setattr(app_config, "CONFIG_IMPORT_ISSUES", issues)
        with pytest.raises(ValueError, match=f"^{knob} could not be read, and the golden headline never falls "
                                             "back to the default: lead tolerance must be an integer"):
            ge._lead_tolerance_days()
    other = sanitize_numeric_env({"OASIS_MAX_AGENTS": "abc"}, app_config.CONFIG_KNOBS)
    monkeypatch.setattr(app_config, "CONFIG_IMPORT_ISSUES", other)
    assert ge._lead_tolerance_days() == 7                            # another knob's issue is not this one's

    monkeypatch.setitem(sys.modules, "app.config", None)            # `import app.config` now raises
    for bad in ("abc", "0d", " "):
        monkeypatch.setenv(knob, bad)
        with pytest.raises(ValueError, match=f"^{knob}='{bad}': lead tolerance must be an integer from 0 to 3650"):
            ge._lead_tolerance_days()
    for bad in ("-1", "3651"):
        monkeypatch.setenv(knob, bad)
        with pytest.raises(ValueError, match="lead tolerance must be an integer from 0 to 3650 days"):
            ge._lead_tolerance_days()
    monkeypatch.setenv(knob, "0")
    assert ge._lead_tolerance_days() == 0                            # a strict tolerance stays strict
    monkeypatch.setenv(knob, "")
    assert ge._lead_tolerance_days() == 7                            # empty means the default, as in Config
    monkeypatch.delenv(knob)
    assert ge._lead_tolerance_days() == 7

    # the review probe, end to end in a fresh process: the command fails before writing any report
    gpath, fpath = _mixed_files(tmp_path)
    out = tmp_path / "probe.json"
    proc = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "backend", "scripts", "golden_eval.py"), "score-forecast-file",
         "--forecast", fpath, "--golden", gpath, "--run-created-at", RUN_AT, "-o", str(out)],
        env={**os.environ, knob: "abc"}, capture_output=True, text=True, timeout=120)
    assert proc.returncode != 0 and not out.exists()
    assert f"ValueError: {knob} could not be read" in proc.stderr
    assert f"(config audit: {knob}=abc is not an integer" in proc.stderr


# ------------------------------------------------------- ledger forwarding
def test_golden_tier_forwarded_and_score_ledger_split(tmp_path):
    ldir = str(tmp_path / "eval_ledger")
    # append_golden_result writes golden_tier only when given; the record class is unchanged
    tiered = append_golden_result(question_id="x1", probability=0.4, resolved_outcome=False, d=ldir,
                                  golden_tier="prospective")
    plain = append_golden_result(question_id="x2", probability=0.4, resolved_outcome=False, d=ldir)
    assert tiered["golden_tier"] == "prospective" and "golden_tier" not in plain
    assert {k: v for k, v in tiered.items() if k not in ("golden_tier", "question_id", "report_id")} == \
        {k: v for k, v in plain.items() if k not in ("question_id", "report_id")}
    assert tiered["record_class"] == "evaluation" and tiered["characterization_only"] is True
    # golden_tier_source is written only alongside golden_tier (review round 2)
    src_dir = str(tmp_path / "source_ledger")
    sourced = append_golden_result(question_id="s1", probability=0.4, resolved_outcome=False, d=src_dir,
                                   golden_tier="prospective", golden_tier_source="pipeline_dir")
    assert (sourced["golden_tier"], sourced["golden_tier_source"]) == ("prospective", "pipeline_dir")
    untiered = append_golden_result(question_id="s2", probability=0.4, resolved_outcome=False, d=src_dir,
                                    golden_tier_source="pipeline_dir")
    assert not {"golden_tier", "golden_tier_source"} & set(untiered)
    assert "golden_tier_source" not in tiered

    # score-forecast-file --to-ledger stamps each row's tier and what it rests on (default dir:
    # redirected, tier kept)
    gpath, fpath = _mixed_files(tmp_path)
    rc, report, _ = _score(tmp_path, gpath, fpath, run_created_at=RUN_AT, to_ledger=True, ledger_dir=ldir)
    assert rc == 0 and report["ledger_appended"] == 4
    assert not any("tier_source" in r for r in report["matched"])     # the report rows are unchanged
    rows = {r["question_id"]: r for r in read_ledger(ldir)}
    assert {qid: rows[qid]["golden_tier"] for qid in ("p1", "p2", "l1", "h1")} == {
        "p1": "prospective", "p2": "prospective", "l1": "late_origin", "h1": HINDCAST}
    assert {rows[qid]["golden_tier_source"] for qid in ("p1", "p2", "l1", "h1")} == {"--run-created-at"}
    assert all(r["record_class"] == "evaluation" and r["characterization_only"] is True for r in rows.values())
    redirected = append_golden_result(question_id="r1", probability=0.5, resolved_outcome=True,
                                      golden_tier="late_origin")
    assert redirected["ledger_redirected"] == "evaluation"
    assert read_ledger(evaluation_ledger_dir())[-1]["golden_tier"] == "late_origin"
    # a value that is no tier counts as unknown, like a row without the key
    append_golden_result(question_id="x3", probability=0.9, resolved_outcome=True, d=ldir, golden_tier="PROSPECTIVE")

    out, md = tmp_path / "ledger.json", tmp_path / "ledger.md"
    assert ge.cmd_score_ledger(SimpleNamespace(ledger_dir=ldir, bins=10, out=str(out), markdown=str(md))) == 0
    lrep = json.loads(out.read_text(encoding="utf-8"))
    h = lrep["headline"]
    assert h["status"] == "ok" and h["tier_source"] == "golden_tier"
    # x1 (prospective, p 0.4 on NO) joins p1 and p2; x2 (no key) and x3 (bogus) are unknown
    assert h["tier_counts"] == {"prospective": 3, "late_origin": 1, HINDCAST: 1, "hindcast_pit": 0, "unknown": 2}
    assert h["metrics"]["n"] == 3 and h["metrics"]["mean_brier"] == round((0.16 + 0.04 + 0.09) / 3, 4)
    assert list(lrep["characterization"]["by_tier"]) == ["late_origin", HINDCAST, "unknown"]
    assert lrep["golden"]["n"] == 7                                  # the golden section keeps every row
    # what the prospective rows rest on: p1/p2 on an operator-given stamp, x1 on nothing recorded
    assert h["prospective_tier_sources"] == {"--run-created-at": 2, "unrecorded": 1}
    run_created_at_note = ("2 prospective row(s) rest on an operator-given --run-created-at, taken as given "
                           "(a later resume or report regeneration of the run was not checked)")
    assert h["provenance_notes"] == [run_created_at_note, "1 prospective row(s) record no golden_tier_source, so "
                                                          "what their tier rests on is unknown"]
    text = md.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert "- prospective rows by tier source: `--run-created-at` 2, `unrecorded` 1" in lines
    assert f"- provenance note: {run_created_at_note}" in lines
    assert lines[0] == ge.CHARACTERIZATION_BANNER and lines[2] == ge.HEADLINE_SCOPE_NOTE
    golden_at = lines.index("## Golden section (binary Brier)")
    assert lines[golden_at + 2] == (f"HEADLINE: mean Brier {h['metrics']['mean_brier']:.4f} over 3/7 prospective "
                                    f"rows (BSS vs climatology {h['metrics']['rigor']['reference']['bss']:.4f})")
    assert golden_at < lines.index("### Headline") < lines.index("#### Overall") < lines.index("### Overall")

    # only legacy rows: no provenance; an empty ledger: nothing eligible
    legacy_dir = str(tmp_path / "legacy_ledger")
    append_golden_result(question_id="old", probability=0.7, resolved_outcome=True, d=legacy_dir)
    assert ge.cmd_score_ledger(SimpleNamespace(ledger_dir=legacy_dir, bins=10, out=str(out), markdown=None)) == 0
    legacy = json.loads(out.read_text(encoding="utf-8"))["headline"]
    assert legacy["status"] == "withheld_no_provenance" and legacy["tier_counts"]["unknown"] == 1
    assert legacy["prospective_tier_sources"] == {} and "provenance_notes" not in legacy
    empty_dir = str(tmp_path / "empty_ledger")
    assert ge.cmd_score_ledger(SimpleNamespace(ledger_dir=empty_dir, bins=10, out=str(out), markdown=str(md))) == 0
    empty = json.loads(out.read_text(encoding="utf-8"))
    assert empty["headline"]["status"] == "withheld_no_eligible_rows" and empty["golden"] == {
        "n": 0, "brier_scale": "binary"}
    empty_lines = md.read_text(encoding="utf-8").splitlines()
    assert "HEADLINE WITHHELD: no scored rows" in empty_lines and ge.HEADLINE_SCOPE_NOTE not in empty_lines


def test_golden_tier_source_per_provenance(tmp_path):
    """--to-ledger records what each tier rests on, so the ledger headline can tell a pipeline-checked
    prospective row from one resting on an operator-given --run-created-at (review round 2)."""
    gpath, fpath = _mixed_files(tmp_path)
    pdir = _pipeline_dir(tmp_path, run={"pipeline_id": "pipe_eval8", "created_at": RUN_AT}, state=_state())
    with open(fpath, encoding="utf-8") as fh:
        stamped = json.load(fh)
    stamped["hindcast"] = hp.hindcast_forecast_block(_gated_pin("2026-09-25", "date_verified"),
                                                     research_audit={"status": "date_verified"})
    spath = _write_json(tmp_path / "stamped.json", stamped)
    for name, forecast, kw, source, tiers in (
            ("pipe", fpath, {"pipeline_dir": pdir}, "pipeline_dir",
             {"p1": "prospective", "p2": "prospective", "l1": "late_origin", "h1": HINDCAST}),
            ("stamped", spath, {}, "forecast_hindcast", dict.fromkeys(("p1", "p2", "l1", "h1"), "hindcast_pit")),
            ("bare", fpath, {}, "none", dict.fromkeys(("p1", "p2", "l1", "h1"), "unknown"))):
        ldir = str(tmp_path / f"ledger_{name}")
        assert _score(tmp_path, gpath, forecast, name=name, to_ledger=True, ledger_dir=ldir, **kw)[0] == 0, name
        rows = read_ledger(ldir)
        assert {r["question_id"]: r["golden_tier"] for r in rows} == tiers, name
        assert {r["golden_tier_source"] for r in rows} == {source}, name
    # the pipeline-checked prospective rows carry no caveat in the ledger headline
    out = tmp_path / "pipe_ledger.json"
    assert ge.cmd_score_ledger(SimpleNamespace(ledger_dir=str(tmp_path / "ledger_pipe"), bins=10, out=str(out),
                                               markdown=None)) == 0
    h = json.loads(out.read_text(encoding="utf-8"))["headline"]
    assert h["status"] == "ok" and h["prospective_tier_sources"] == {"pipeline_dir": 2}
    assert "provenance_notes" not in h


def test_preflight_range_for_the_lead_tolerance_matches_the_runtime_check():
    """config_audit names an out-of-range GOLDEN_PROSPECTIVE_LEAD_TOLERANCE_DAYS before
    golden_eval runs; its bound must be the one _check_tolerance enforces."""
    from app.config_audit import RANGE_RULES
    rule = RANGE_RULES["GOLDEN_PROSPECTIVE_LEAD_TOLERANCE_DAYS"]
    assert (rule.low, rule.low_inclusive, rule.high, rule.high_inclusive) == (
        0, True, ge.MAX_LEAD_TOLERANCE_DAYS, True)
