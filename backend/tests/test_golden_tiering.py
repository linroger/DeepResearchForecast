"""EVAL-8: golden headline tiering in backend/scripts/golden_eval.py.

A golden Brier is a skill estimate only over rows the run could not look up. Every
matched row is tiered from the run's provenance (run.json / pipeline_state.json
created_at, the TIME-7 hindcast pin, or --run-created-at): only ``prospective``
rows (run before the resolution date and no later than as_of + the lead
tolerance, never a pinned hindcast) reach the ``headline``; every other row is
under ``characterization.by_tier``; ``metrics`` keeps every matched row. A
headline without eligible rows is withheld and ``--require-headline`` exits 5.
With GOLDEN_HEADLINE_GATE=false every output is byte-identical to the pre-EVAL-8
code.

Offline and deterministic: tmp ledgers, synthetic golden sets and pipeline dirs.
"""

import hashlib
import json
import os
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
    return _write_json(tmp_path / "mixed_golden.json", golden), _write_json(tmp_path / "mixed_fc.json", fc)


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

    for bad_tolerance in (-1, 1.5, True, "7", None):
        with pytest.raises(ValueError, match="lead tolerance"):
            ge.classify_tier(q, run_created_at=RUN_AT, lead_tolerance_days=bad_tolerance)


# ------------------------------------------------------- committed set, 2026 run
def test_committed_set_all_hindcast_withheld(tmp_path, monkeypatch):
    """Acceptance: a 2026 run over the committed 2024-25 set has no headline; every row is characterization."""
    ids = [q["id"] for q in ge.load_golden_set()]
    fpath = _write_json(tmp_path / "const.json", {"binary_forecasts": [{"id": i, "probability": 0.9} for i in ids]})
    stamp = "2026-09-28T09:15:00.123456+00:00"                      # pipeline_orchestrator._utcnow format
    pdir = _pipeline_dir(tmp_path, run={"pipeline_id": "pipe_eval8", "created_at": stamp, "resolved": {}},
                         state={"pipeline_id": "pipe_eval8", "created_at": stamp, "options": {}})

    rc, report, text = _score(tmp_path, ge.GOLDEN_PATH, fpath, pipeline_dir=pdir)
    assert rc == 0
    h = report["headline"]
    assert h["status"] == "withheld_no_eligible_rows"
    assert h["tier_counts"] == {"prospective": 0, "late_origin": 0, HINDCAST: 30, "hindcast_pit": 0, "unknown": 0}
    assert (h["run_created_at"], h["run_created_at_source"], h["lead_tolerance_days"]) == (stamp, "run.json", 7)
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


# ------------------------------------------------------------ prospective rows
def test_prospective_synthetic_row_headline_ok(tmp_path, monkeypatch):
    gpath, fpath = _mixed_files(tmp_path)
    rc, report, text = _score(tmp_path, gpath, fpath, run_created_at=RUN_AT, require_headline=True, bootstrap=40)
    assert rc == 0                                                   # ok headline: --require-headline passes
    h = report["headline"]
    assert h["status"] == "ok"
    assert h["tier_counts"] == {"prospective": 2, "late_origin": 1, HINDCAST: 1, "hindcast_pit": 0, "unknown": 0}
    assert (h["run_created_at"], h["run_created_at_source"]) == (RUN_AT, "--run-created-at")
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
    assert text0.splitlines()[0] == ("HEADLINE WITHHELD: 3/4 late origin (run started after as_of + the lead "
                                     "tolerance); 1/4 hindcast (live retrieval + model memory exposed)")
    monkeypatch.setattr(Config, "GOLDEN_PROSPECTIVE_LEAD_TOLERANCE_DAYS", -1, raising=False)
    with pytest.raises(ValueError, match="lead tolerance"):
        _score(tmp_path, gpath, fpath, name="negative", run_created_at=RUN_AT)
    assert not (tmp_path / "negative.json").exists()


def test_hindcast_pin_never_headline_eligible(tmp_path):
    """Integration adjustment: a TIME-7 hindcast run is hindcast_pit whatever its dates."""
    gpath, fpath = _mixed_files(tmp_path)
    run = {"created_at": RUN_AT, "resolved": {}}

    pdir = _pipeline_dir(tmp_path, "pipe_pin", run=run,
                         state={"created_at": RUN_AT, "options": {"hindcast_policy_v1": _gated_pin("2026-09-25",
                                                                                                   "date_verified")}})
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
                              state={"created_at": RUN_AT, "options": {"hindcast_policy_v1": _gated_pin("2026-09-25")}})
    assert _score(tmp_path, gpath, fpath, name="unaudited",
                  pipeline_dir=unaudited)[1]["headline"]["hindcast"]["integrity"] == "labelled"
    # pipeline_state.json unreadable: run.json's as_of_enforcement still marks the hindcast
    enforcement = hp.as_of_enforcement_record(_gated_pin("2026-09-25", "violated"))
    manifest_only = _pipeline_dir(tmp_path, "pipe_manifest", run={"created_at": RUN_AT, "resolved": {
        "as_of_enforcement": enforcement}})
    mh = _score(tmp_path, gpath, fpath, name="manifest", pipeline_dir=manifest_only)[1]["headline"]
    assert mh["hindcast"] == {"as_of": "2026-09-25", "source": "run.json", "integrity": "leak_suspected"}
    assert mh["tier_counts"]["hindcast_pit"] == 4 and "pipeline_state.json: missing" in mh["provenance_notes"]
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
    live = _pipeline_dir(tmp_path, "pipe_live", run=run,
                         state={"created_at": RUN_AT, "options": {"hindcast_policy_v1": live_pin}})
    lh = _score(tmp_path, gpath, fpath, name="live", pipeline_dir=live)[1]["headline"]
    assert lh["status"] == "ok" and lh["tier_counts"]["prospective"] == 2 and "hindcast" not in lh
    # a pin value that is neither cannot rule a hindcast out: the run stamp is withheld
    odd = _pipeline_dir(tmp_path, "pipe_odd", run=run,
                        state={"created_at": RUN_AT, "options": {"hindcast_policy_v1": {"hindcast": True}}})
    oh = _score(tmp_path, gpath, fpath, name="odd", pipeline_dir=odd)[1]["headline"]
    assert oh["status"] == "withheld_no_provenance" and oh["tier_counts"]["unknown"] == 4
    assert oh["run_created_at"] is None and "not a recognised pin" in oh["provenance_notes"][0]


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
                             state={"created_at": "2026-09-28T02:00:00-05:00", "options": {}})
    fb = _score(tmp_path, gpath, fpath, name="fallback", pipeline_dir=fallback)[1]["headline"]
    assert (fb["status"], fb["run_created_at"], fb["run_created_at_source"]) == (
        "ok", "2026-09-28T07:00:00+00:00", "pipeline_state.json")
    # a missing run.json falls back too, and says so
    no_manifest = _pipeline_dir(tmp_path, "pipe_no_manifest", state={"created_at": RUN_AT, "options": {}})
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

    # score-forecast-file --to-ledger stamps each row's tier (default dir: redirected, tier kept)
    gpath, fpath = _mixed_files(tmp_path)
    rc, report, _ = _score(tmp_path, gpath, fpath, run_created_at=RUN_AT, to_ledger=True, ledger_dir=ldir)
    assert rc == 0 and report["ledger_appended"] == 4
    rows = {r["question_id"]: r for r in read_ledger(ldir)}
    assert {qid: rows[qid]["golden_tier"] for qid in ("p1", "p2", "l1", "h1")} == {
        "p1": "prospective", "p2": "prospective", "l1": "late_origin", "h1": HINDCAST}
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
    text = md.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == ge.CHARACTERIZATION_BANNER
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
    empty_dir = str(tmp_path / "empty_ledger")
    assert ge.cmd_score_ledger(SimpleNamespace(ledger_dir=empty_dir, bins=10, out=str(out), markdown=str(md))) == 0
    empty = json.loads(out.read_text(encoding="utf-8"))
    assert empty["headline"]["status"] == "withheld_no_eligible_rows" and empty["golden"] == {
        "n": 0, "brier_scale": "binary"}
    assert "HEADLINE WITHHELD: no scored rows" in md.read_text(encoding="utf-8").splitlines()
