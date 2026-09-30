"""EVAL-4: the manual settlement path.

Covers ``forecast_tools resolve`` (scenario and binary attestations, validation exit
codes, no-op repeats, the supersede / retract protocol), the fold honouring the latest
standing revision (``forecast_resolution.standing_events``), the shared target helper
``load_manual_target`` and the hardened ``POST /api/v1/resolve`` (unmatched outcomes
refused without a file, attested events recorded through the same builder, the legacy
resolved.json-only path). Offline: per-test ledger directories and reports directories,
hand-built commit rows through the real EVAL-1 writer, no LLM, no network.
"""

import copy
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

import scripts.forecast_tools as tools
import scripts.resolution_monitor as mon
from app.config import Config
from app.services import forecast_ledger as fl
from app.services import forecast_resolution as fr
from app.services.backtest import calibration_report
from app.services.report_agent import ReportManager
from app.utils.prediction_markets import _parse_resolution
from tests.test_forecast_resolution import _forecast, _write_sealed_report
from tests.test_resolution_monitor import _exact_anchored
from tests.test_sdk_publication_barrier import _save_report

SCENARIOS = [{"name": "Status quo", "probability": 0.6, "resolution_criteria": "No change."},
             {"name": "Escalation", "probability": 0.3, "resolution_criteria": "Escalates."},
             {"name": "De-escalation", "probability": 0.1, "resolution_criteria": "Calms."}]
BINARIES = [{"id": "F1", "statement": "The treaty is ratified by 2025-12-31.", "probability": 0.7,
             "resolution_criteria": "Ratification is recorded by 2025-12-31.",
             "horizon_year": 2025},
            {"id": "F3", "statement": "Tariffs rise by 2025-12-31.", "probability": 0.2,
             "resolution_criteria": "A tariff increase takes effect by 2025-12-31.",
             "horizon_year": 2025}]
KNOWN_AT = "2025-09-01T10:00:00Z"
URL = "https://example.org/official-result"
NOTE = "Official gazette notice 42 of 2025-09-01 records the result."


@pytest.fixture
def reports(monkeypatch, tmp_path):
    """A per-test reports directory, so no test reads or writes the real one."""
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    return tmp_path / "reports"


@pytest.fixture
def ledger(tmp_path):
    d = tmp_path / "ledger"
    d.mkdir()
    return str(d)


def _commit(d, report_id="r1", *, as_of="2025-06-01", committed_at="2025-06-02T08:00:00+00:00",
            forecast=None, record_class="production", horizon="2025"):
    """A publication-sealed EVAL-1 commit row, written by the real writer."""
    forecast = forecast or {"horizon": horizon, "scenarios": copy.deepcopy(SCENARIOS),
                            "binary_forecasts": copy.deepcopy(BINARIES)}
    status, row = fl.commit_published_forecast(
        forecast, report_id=report_id, question=f"What happens to {report_id}?", language="en",
        as_of_date=as_of, as_of_source="validated", record_class=record_class,
        publication={"forecast_sha256": hashlib.sha256(
            json.dumps(forecast, sort_keys=True).encode("utf-8")).hexdigest()},
        d=d, committed_at=committed_at)
    assert status in ("committed", "revision")
    return row


def _resolutions_bytes(d):
    path = os.path.join(d, "resolutions.jsonl")
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        return fh.read()


def _cli(capsys, *argv):
    """Run ``forecast_tools`` in-process → (exit code, stdout JSON or None, stderr)."""
    code = tools.main(list(argv))
    out, err = capsys.readouterr()
    return code, (json.loads(out) if out.strip() else None), err


def _resolve(capsys, d, *args, report_id="r1"):
    return _cli(capsys, "resolve", "--report-id", report_id, "--ledger-dir", d, *args)


def _attest(capsys, d, name="Status quo", *extra, known_at=KNOWN_AT, evidence=URL):
    return _resolve(capsys, d, "--scenario", name, "--known-at", known_at,
                    "--evidence", evidence, *extra)


def _market_event(fid="F1", outcome="NO", *, report_id="r1", market_id="m-1"):
    """An eligible schema_version 2 market settlement (EVAL-2's row shape)."""
    return {"report_id": report_id, "forecast_id": fid, "market_id": market_id,
            "resolved_outcome": outcome, "resolved_yes_price": 0.0, "model_p": 0.7,
            "market_p_at_research": 0.4, "brier_contribution": 0.49,
            "resolved_at": "2025-09-03T00:00:00+00:00", "schema_version": 2,
            "item_kind": "binary", "source_kind": "polymarket", "outcome": outcome,
            "y": int(outcome == "YES"), "outcome_known_at": "2025-09-02T00:00:00+00:00",
            "known_at_basis": "source", "processed_at": "2025-09-03T00:00:00+00:00",
            "prospective": True, "scoring_eligible": True, "ineligible_reason": None,
            "resolution_status": "settled", "target_commit_id": None}


# ─────────────────────────────── CLI: scenario set ───────────────────────────
def test_cli_scenario_normalised_match(capsys, ledger):
    row = _commit(ledger)
    code, event, _ = _attest(capsys, ledger, " Status-Quo ")
    assert code == 0
    assert (event["forecast_id"], event["market_id"], event["item_kind"], event["source_kind"]) == \
        ("__scenarios__", "manual", "scenario_set", "manual")
    # The scorer's normaliser matched it; the canonical scenario name is what is stored.
    assert (event["outcome"], event["resolved_outcome"]) == ("Status quo", "Status quo")
    assert (event["known_at_basis"], event["outcome_known_at"], event["prospective"],
            event["scoring_eligible"], event["ineligible_reason"]) == \
        ("attested", KNOWN_AT, True, True, None)
    assert (event["resolution_status"], event["supersedes"], event["retracted"]) == \
        ("settled", None, False)
    assert (event["schema_version"], event["target_commit_id"], event["model_p"], event["y"]) == \
        (2, row["commit_id"], None, None)
    assert event["evidence"] == {"url": URL, "note": None}
    # Exactly one attested event was appended, and it is the one printed.
    assert fl.read_market_resolutions(ledger) == [event]
    before = _resolutions_bytes(ledger)

    # A second identical call without --supersedes is a no-op.
    code, again, err = _attest(capsys, ledger, "status quo")
    assert (code, again) == (0, event) and "no-op" in err
    assert _resolutions_bytes(ledger) == before
    # A different attestation without --supersedes is refused, never silently dropped.
    code, out, err = _attest(capsys, ledger, "Escalation")
    assert (code, out) == (2, None) and "supersedes" in err
    assert _resolutions_bytes(ledger) == before
    # --dry-run prints the correction it would append and writes nothing.
    code, dry, err = _attest(capsys, ledger, "Escalation", "--supersedes", "manual", "--dry-run")
    assert code == 0 and "dry run" in err
    assert (dry["market_id"], dry["supersedes"], dry["outcome"]) == \
        ("manual:r1", "manual", "Escalation")
    assert _resolutions_bytes(ledger) == before
    # A note of at least 20 characters is evidence too.
    other = _commit(ledger, "r2")
    assert _attest(capsys, ledger, "De-escalation")[0] == 2  # r1 holds another outcome
    code, noted, _ = _resolve(capsys, ledger, "--scenario", "de escalation", "--known-at",
                              "2025-09-01", "--evidence", f"  {NOTE}  ", report_id="r2")
    assert code == 0
    assert (noted["outcome"], noted["evidence"], noted["target_commit_id"]) == \
        ("De-escalation", {"url": None, "note": NOTE}, other["commit_id"])
    # A bare date is kept verbatim: prospective reads its start, admissible its end.
    assert noted["outcome_known_at"] == "2025-09-01"
    assert fr.admissible(noted, "2025-09-01") == (False, "known_on_or_after_as_of")
    assert fr.admissible(noted, "2025-09-02") == (True, None)


def test_cli_rejects_unmatched_missing_or_future(capsys, ledger, reports):
    _commit(ledger)
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    bad = {
        "unmatched": ["--scenario", "Collapse", "--known-at", KNOWN_AT, "--evidence", URL],
        "no scenario name": ["--scenario", "--known-at", KNOWN_AT, "--evidence", URL],
        "missing known-at": ["--scenario", "Status quo", "--evidence", URL],
        "future known-at": ["--scenario", "Status quo", "--known-at", future, "--evidence", URL],
        "naive known-at": ["--scenario", "Status quo", "--known-at", "2025-09-01T10:00:00",
                           "--evidence", URL],
        "free-text known-at": ["--scenario", "Status quo", "--known-at", "early September",
                               "--evidence", URL],
        "missing evidence": ["--scenario", "Status quo", "--known-at", KNOWN_AT],
        "short note": ["--scenario", "Status quo", "--known-at", KNOWN_AT, "--evidence", "see news"],
        "not an http url": ["--scenario", "Status quo", "--known-at", KNOWN_AT,
                            "--evidence", "ftp://x"],
        "overlong note": ["--scenario", "Status quo", "--known-at", KNOWN_AT,
                          "--evidence", "x" * (fr.MANUAL_EVIDENCE_MAX_CHARS + 1)],
        "outcome with scenario": ["--scenario", "Status quo", "--outcome", "YES",
                                  "--known-at", KNOWN_AT, "--evidence", URL],
        "nothing to supersede": ["--scenario", "Status quo", "--known-at", KNOWN_AT,
                                 "--evidence", URL, "--supersedes", "manual"],
        "retract without supersedes": ["--scenario", "--retract", "--evidence", NOTE],
    }
    for label, args in bad.items():
        code, out, err = _resolve(capsys, ledger, *args)
        assert (code, out) == (2, None), label
        assert err.startswith("error:"), label
        assert _resolutions_bytes(ledger) is None, label
    # --binary never names the scenario set (nor its reserved forecast id).
    for name in ("scenario", "__scenarios__"):
        code, out, err = _resolve(capsys, ledger, "--binary", name, "--outcome", "YES",
                                  "--known-at", KNOWN_AT, "--evidence", URL)
        assert (code, out) == (2, None) and "--scenario" in err, name
    # Invalid input is exit 2 even for a report without a settleable target.
    code, out, err = _resolve(capsys, ledger, "--scenario", "Status quo", "--known-at", future,
                              "--evidence", URL, report_id="unknown-report")
    assert (code, out) == (2, None) and "future" in err
    assert _resolutions_bytes(ledger) is None
    # No settleable target: exit 4 and nothing written either.
    for report_id in ("unknown-report", "r-ensemble"):
        if report_id == "r-ensemble":
            _commit(ledger, report_id, record_class="ensemble_member")
        code, out, err = _resolve(capsys, ledger, "--scenario", "Status quo", "--known-at",
                                  KNOWN_AT, "--evidence", URL, report_id=report_id)
        assert (code, out) == (4, None)
        assert ("not_publishable" if report_id == "unknown-report" else "not_production_primary") \
            in err
    assert _resolutions_bytes(ledger) is None


def test_cli_binary_yes_no_and_unknown_binary(capsys, ledger):
    _commit(ledger)
    code, yes, _ = _resolve(capsys, ledger, "--binary", "F1", "--outcome", "yes",
                            "--known-at", KNOWN_AT, "--evidence", URL)
    assert code == 0
    assert (yes["forecast_id"], yes["item_kind"], yes["market_id"], yes["outcome"], yes["y"]) == \
        ("F1", "binary", "manual", "YES", 1)
    assert (yes["model_p"], yes["brier_contribution"], yes["scoring_eligible"]) == (0.7, 0.09, True)
    code, no, _ = _resolve(capsys, ledger, "--binary", "F3", "--outcome", "NO",
                           "--known-at", KNOWN_AT, "--evidence", NOTE)
    assert code == 0
    assert (no["outcome"], no["y"], no["model_p"], no["brier_contribution"]) == ("NO", 0, 0.2, 0.04)
    before = _resolutions_bytes(ledger)
    for args in (["--binary", "F9", "--outcome", "YES"],      # not in the target
                 ["--binary", "F1", "--outcome", "MAYBE"],    # not YES/NO
                 ["--binary", "F1"]):                          # no outcome
        code, out, err = _resolve(capsys, ledger, *args, "--known-at", KNOWN_AT, "--evidence", URL)
        assert (code, out) == (2, None) and err.startswith("error:")
    assert _resolutions_bytes(ledger) == before
    # Both attested binaries enter the binary calibration (manual rows never the market Brier).
    summary = fl.binary_calibration_summary(ledger)
    assert (summary["n_resolved"], summary["excluded"]) == (2, {})
    assert summary["mean_brier"] == round((0.09 + 0.04) / 2, 4)
    assert fl.market_brier_summary(ledger)["n_resolved"] == 0


# ─────────────────────────── revisions and the fold ──────────────────────────
def test_supersede_chain_and_retract(capsys, ledger):
    row = _commit(ledger)

    def view():
        (folded,) = fr.resolved_view([row], fl.read_market_resolutions(ledger))
        return folded

    assert _attest(capsys, ledger, "Status quo")[0] == 0
    code, fix, _ = _attest(capsys, ledger, "Escalation", "--supersedes", "manual",
                           evidence=f"{URL}/corrected")
    assert code == 0
    assert (fix["market_id"], fix["supersedes"], fix["outcome"]) == ("manual:r1", "manual", "Escalation")
    # The fold uses the latest revision only: no conflict with the superseded original.
    assert (view()["resolved"], view()["outcome"], view()["resolution_status"]) == \
        (True, "Escalation", "settled")
    # --supersedes must name the latest manual event; re-running a correction is refused.
    before = _resolutions_bytes(ledger)
    assert _attest(capsys, ledger, "Escalation", "--supersedes", "manual")[0] == 2
    assert _attest(capsys, ledger, "Status quo", "--supersedes", "manual:r7")[0] == 2
    assert _resolutions_bytes(ledger) == before
    # A retraction removes the attestation: the row is unresolved again, nothing scores.
    code, retraction, _ = _resolve(capsys, ledger, "--scenario", "--retract",
                                   "--supersedes", "manual:r1", "--evidence", NOTE)
    assert code == 0
    assert (retraction["market_id"], retraction["supersedes"], retraction["retracted"],
            retraction["outcome"], retraction["outcome_known_at"],
            retraction["resolution_status"], retraction["scoring_eligible"],
            retraction["ineligible_reason"]) == \
        ("manual:r2", "manual:r1", True, None, None, "retracted", False, "retracted")
    assert (view()["resolved"], view()["outcome"], view()["scoring_eligible"]) == (False, None, False)
    assert fl.calibration_summary(ledger, fold_settlements=True)["n_resolved"] == 0
    # A retraction takes no outcome or known-at, and a retraction is never retracted twice.
    assert _resolve(capsys, ledger, "--scenario", "Escalation", "--retract", "--supersedes",
                    "manual:r2", "--evidence", NOTE)[0] == 2
    assert _resolve(capsys, ledger, "--scenario", "--retract", "--supersedes", "manual:r2",
                    "--known-at", KNOWN_AT, "--evidence", NOTE)[0] == 2
    assert _resolve(capsys, ledger, "--scenario", "--retract", "--supersedes", "manual:r2",
                    "--evidence", NOTE)[0] == 2
    # After a retraction, only a revision that names it attests again.
    assert _attest(capsys, ledger, "Status quo")[0] == 2
    code, again, _ = _attest(capsys, ledger, "Status quo", "--supersedes", "manual:r2")
    assert (code, again["market_id"]) == (0, "manual:r3")
    assert (view()["outcome"], view()["scoring_eligible"]) == ("Status quo", True)
    assert fl.calibration_summary(ledger, fold_settlements=True)["n_resolved"] == 1
    events = fl.read_market_resolutions(ledger)
    assert [e["market_id"] for e in events] == ["manual", "manual:r1", "manual:r2", "manual:r3"]
    # The fold never depends on the order the revisions were appended.
    assert fr.resolved_view([row], events[::-1]) == [view()]

    # Binaries: an eligible manual outcome that disagrees with an eligible market
    # settlement is a conflict; its correction resolves it.
    assert _resolve(capsys, ledger, "--binary", "F1", "--outcome", "YES", "--known-at",
                    KNOWN_AT, "--evidence", URL)[0] == 0
    market = _market_event("F1", "NO")
    events = fl.read_market_resolutions(ledger) + [market]
    item = fr.fold_binary_items(events)[("r1", "F1")]
    assert (item["resolution_status"], item["conflicting_outcomes"]) == ("conflict", ["NO", "YES"])
    assert fr.admissible(item) == (False, "conflict")
    assert _resolve(capsys, ledger, "--binary", "F1", "--outcome", "NO", "--known-at", KNOWN_AT,
                    "--evidence", NOTE, "--supersedes", "manual")[0] == 0
    events = fl.read_market_resolutions(ledger) + [market]
    item = fr.fold_binary_items(events)[("r1", "F1")]
    assert (item["resolution_status"], item["outcome"], item["n_events"]) == ("settled", "NO", 2)
    assert fr.fold_binary_items(events[::-1]) == fr.fold_binary_items(events)
    # A retracted manual binary leaves only the market's fact; alone, the item disappears.
    assert _resolve(capsys, ledger, "--binary", "F1", "--retract", "--supersedes", "manual:r1",
                    "--evidence", NOTE)[0] == 0
    events = fl.read_market_resolutions(ledger)
    assert ("r1", "F1") not in fr.fold_binary_items(events)
    only_market = fr.fold_binary_items(events + [market])[("r1", "F1")]
    assert (only_market["source_kind"], only_market["n_events"]) == ("polymarket", 1)


def test_standing_events_leaves_other_rows_untouched():
    market = _market_event()
    terminal = dict(_market_event("F2"), market_id="terminal", source_kind="terminal",
                    resolution_status="terminal", scoring_eligible=False)
    legacy = {"report_id": "r1", "forecast_id": "F4", "market_id": "m-9", "schema_version": 1,
              "resolved_yes_price": 1.0, "resolved_at": "2025-09-03T00:00:00+00:00"}
    # A manual row whose 'supersedes' names a market id never hides the market settlement,
    # and only manual rows of the same item supersede.
    manual = dict(_market_event("F1", "YES"), market_id="manual", source_kind="manual",
                  supersedes="m-1")
    elsewhere = dict(manual, forecast_id="F2", market_id="manual:r1", supersedes="manual")
    events = [market, terminal, legacy, manual, elsewhere, "not a row"]
    snapshot = copy.deepcopy(events)
    assert fr.standing_events(events) == [market, terminal, legacy, manual, elsewhere]
    assert events == snapshot
    assert fr.standing_events(None) == []
    # Two unsuperseded attestations (hand edits) both stand: disagreeing, they conflict.
    fork = dict(manual, market_id="manual:r1", supersedes=None, outcome="NO")
    item = fr.fold_binary_items([dict(manual, supersedes=None), fork])[("r1", "F1")]
    assert item["resolution_status"] == "conflict"


def _market_resolution(market_id, outcome, *, closed_time="2025-07-01T15:30:00Z"):
    """A settled Gamma market (the real parser), resolved YES or NO."""
    prices = '["1","0"]' if outcome == "YES" else '["0","1"]'
    return _parse_resolution({"id": market_id, "outcomes": '["Yes","No"]',
                              "outcomePrices": prices, "closed": True,
                              "umaResolutionStatus": "resolved", "closedTime": closed_time,
                              "endDate": "2025-06-30T12:00:00Z"})


def _due(d, processed_at):
    targets, _ = mon.settle_targets(fl.read_ledger(d), 10, fl.read_market_resolutions(d),
                                    processed_at=processed_at, grace_days=180)
    return {row["report_id"]: [binary["id"] for binary in due] for row, due in targets}


def test_settle_sweep_checks_attested_anchored_binary_against_its_market(capsys, ledger):
    """An attestation never makes an anchored item final for the settle sweep: the market
    is still fetched, and an eligible settlement that disagrees folds into a conflict."""
    anchored = _exact_anchored("F1", "X happens by 2025-06-30.", "Resolves YES if X by 2025-06-30.",
                               market_id="m-1", end_date="2025-06-30T12:00:00Z", horizon_year=2025)
    forecast = {"horizon": "2025", "scenarios": copy.deepcopy(SCENARIOS),
                "binary_forecasts": [anchored]}
    for report_id in ("r1", "r2"):
        _commit(ledger, report_id, as_of="2025-01-01", committed_at="2025-01-02T08:00:00+00:00",
                forecast=forecast)
        assert _resolve(capsys, ledger, "--binary", "F1", "--outcome", "YES", "--known-at",
                        "2025-07-01T00:00:00Z", "--evidence", URL, report_id=report_id)[0] == 0
    now = datetime.now(timezone.utc).isoformat()
    assert _due(ledger, now) == {"r1": ["F1"], "r2": ["F1"]}
    assert fr.recorded_items(fl.read_market_resolutions(ledger)) == set()
    assert fr.attested_items(fl.read_market_resolutions(ledger)) == {("r1", "F1"), ("r2", "F1")}

    # r1: the market settled NO. Its eligible event is appended beside the attestation.
    existing = fl.read_market_resolutions(ledger)
    targets = {row["report_id"]: (row, due) for row, due in mon.settle_targets(
        fl.read_ledger(ledger), 10, existing, processed_at=now, grace_days=180)[0]}
    row, due = targets["r1"]
    out = fr.settle_binaries("r1", due, {"m-1": _market_resolution("m-1", "NO")},
                             target_meta=mon._commit_target_meta(row), processed_at=now,
                             grace_days=180, existing_events=existing, answered_market_ids={"m-1"})
    (event,) = out["events"]
    assert (event["outcome"], event["scoring_eligible"], out["terminal"]) == ("NO", True, [])
    assert fl.append_settlement_event(event, d=ledger) is not None
    item = fr.fold_binary_items(fl.read_market_resolutions(ledger))[("r1", "F1")]
    assert (item["resolution_status"], item["conflicting_outcomes"]) == ("conflict", ["NO", "YES"])
    assert fr.admissible(item) == (False, "conflict")

    # r2: the source answered but the market never settled; past its grace the terminal
    # closes the market channel, while the attestation still decides the item.
    row, due = targets["r2"]
    out = fr.settle_binaries("r2", due, {}, target_meta=mon._commit_target_meta(row),
                             processed_at=now, grace_days=180, existing_events=existing,
                             answered_market_ids={"m-1"})
    (terminal,) = out["terminal"]
    assert fl.append_settlement_event(terminal, d=ledger) is not None
    item = fr.fold_binary_items(fl.read_market_resolutions(ledger))[("r2", "F1")]
    assert (item["source_kind"], item["outcome"], item["n_events"]) == ("manual", "YES", 2)
    assert fr.admissible(item) == (True, None)
    # Both market channels are closed now: nothing is due any more.
    assert _due(ledger, now) == {}


def test_standing_attestation_spares_only_an_unanchored_item_its_terminal(capsys, ledger):
    """An attested unanchored binary has nothing left for the sweep; once the attestation is
    retracted it is unsettled again and gets its grace terminal."""
    row = _commit(ledger)
    now = datetime.now(timezone.utc).isoformat()
    assert _due(ledger, now) == {"r1": ["F1", "F3"]}  # both past their 2025 grace
    assert _resolve(capsys, ledger, "--binary", "F1", "--outcome", "YES", "--known-at",
                    KNOWN_AT, "--evidence", URL)[0] == 0
    assert _due(ledger, now) == {"r1": ["F3"]}
    # A per-report run (all binaries, not only the due ones) writes no terminal for F1 either.
    out = fr.settle_binaries("r1", row["binary_forecasts"], {},
                             target_meta=mon._commit_target_meta(row), processed_at=now,
                             existing_events=fl.read_market_resolutions(ledger))
    assert [event["forecast_id"] for event in out["terminal"]] == ["F3"]

    assert _resolve(capsys, ledger, "--binary", "F1", "--retract", "--supersedes", "manual",
                    "--evidence", NOTE)[0] == 0
    assert fr.attested_items(fl.read_market_resolutions(ledger)) == set()
    assert _due(ledger, now) == {"r1": ["F1", "F3"]}
    out = fr.settle_binaries("r1", row["binary_forecasts"], {},
                             target_meta=mon._commit_target_meta(row), processed_at=now,
                             existing_events=fl.read_market_resolutions(ledger))
    assert [event["forecast_id"] for event in out["terminal"]] == ["F1", "F3"]
    for event in out["terminal"]:
        assert fl.append_settlement_event(event, d=ledger) is not None
    item = fr.fold_binary_items(fl.read_market_resolutions(ledger))[("r1", "F1")]
    assert (item["resolution_status"], item["scoring_eligible"]) == ("terminal", False)
    assert _due(ledger, now) == {}


def test_monitor_shares_the_settlement_helpers(monkeypatch):
    """One implementation each: the monitor's event append, report-row reader and meta.json
    stamp reader are the ones the manual path uses, so their field lists never drift."""
    assert mon._report_ledger_rows is fr.report_ledger_rows
    assert mon._local_stamp_to_utc is fr.local_stamp_to_utc
    calls = []

    def append(event, *, d=None):
        calls.append((event, d))
        return dict(event)

    monkeypatch.setattr(fl, "append_settlement_event", append)
    assert mon._append_event({"report_id": "r1"}, "/ledger") == {"report_id": "r1"}
    assert calls == [({"report_id": "r1"}, "/ledger")]


def test_manual_builders_fail_closed():
    target = {"report_id": "r1", "commit_id": "c-1", "as_of": "2025-06-01",
              "created_at": "2025-06-02T08:00:00+00:00", "scenarios": copy.deepcopy(SCENARIOS),
              "binary_forecasts": copy.deepcopy(BINARIES), "source": "ledger"}
    now = datetime(2025, 9, 30, tzinfo=timezone.utc)
    assert fr.validate_manual_settlement(target, "scenario", "status quo", KNOWN_AT, URL,
                                         now=now) == (True, [])
    ok, errors = fr.validate_manual_settlement(target, "scenario", "Collapse",
                                               "2025-10-01T00:00:00Z", "short", now=now)
    assert not ok and len(errors) == 3
    assert "matches no scenario" in errors[0] and "'Status quo'" in errors[0]
    assert "future" in errors[1] and "evidence" in errors[2]
    assert fr.validate_manual_settlement(None, "scenario", "Status quo", KNOWN_AT, URL)[0] is False
    assert fr.validate_manual_settlement(target, "", "YES", KNOWN_AT, URL)[0] is False
    with pytest.raises(ValueError):
        fr.validate_manual_settlement(target, "F1", "YES", KNOWN_AT, URL, now=datetime(2025, 9, 30))
    # Duplicate scenario names or binary ids make the target ambiguous, never guessed.
    twin = dict(target, scenarios=SCENARIOS + [{"name": "status-quo", "probability": 0.0}],
                binary_forecasts=BINARIES + [dict(BINARIES[0])])
    assert fr.match_scenario_name(twin["scenarios"], "Status quo") == (None, "ambiguous_outcome")
    assert fr.match_scenario_name(SCENARIOS, "  ") == (None, "no_outcome")
    assert "more than one" in fr.validate_manual_settlement(twin, "scenario", "Status quo",
                                                            KNOWN_AT, URL, now=now)[1][0]
    assert "not unique" in fr.validate_manual_settlement(twin, "F1", "YES", KNOWN_AT, URL,
                                                         now=now)[1][0]
    kwargs = {"target": target, "item": "scenario", "outcome": "Status quo",
              "outcome_known_at": KNOWN_AT, "evidence": URL}
    with pytest.raises(ValueError):
        fr.build_manual_event(**dict(kwargs, outcome="Collapse"), processed_at=now.isoformat())
    with pytest.raises(ValueError):
        fr.build_manual_event(**kwargs, processed_at="2025-09-30")  # not a date-time
    with pytest.raises(ValueError):
        fr.build_manual_event(**kwargs, supersedes="manual", processed_at=now.isoformat())
    with pytest.raises(ValueError):
        fr.plan_manual_settlement(target, "scenario", "Status quo", KNOWN_AT, URL,
                                  existing_events=[], processed_at="yesterday")
    # Known before the forecast origin (end of the as-of day / created_at): recorded, never scored.
    early = fr.build_manual_event(**dict(kwargs, outcome_known_at="2025-06-01T12:00:00Z"),
                                  processed_at=now.isoformat())
    assert (early["prospective"], early["scoring_eligible"], early["ineligible_reason"]) == \
        (False, False, "not_prospective")
    unknown = fr.build_manual_event(**dict(kwargs, target=dict(target, as_of=None, created_at=None)),
                                    processed_at=now.isoformat())
    assert (unknown["prospective"], unknown["ineligible_reason"]) == ("unknown", "prospective_unknown")
    assert fr.manual_revision("manual") == 0 and fr.manual_revision("manual:r12") == 12
    assert fr.manual_revision("manual:r0") is None and fr.manual_revision("m-1") is None
    # A binary probability outside [0, 1] (or none) gets no fabricated Brier and never scores.
    for probability in (70, -0.1, None, True):
        odd = dict(target, binary_forecasts=[dict(BINARIES[0], probability=probability)])
        event = fr.build_manual_event(target=odd, item="F1", outcome="NO",
                                      outcome_known_at=KNOWN_AT, evidence=URL,
                                      processed_at=now.isoformat())
        assert (event["brier_contribution"], event["scoring_eligible"],
                event["ineligible_reason"], event["prospective"], event["outcome"]) == \
            (None, False, "invalid_model_probability", True, "NO"), probability
    # The scenario set's forecast id is reserved, never a binary id.
    reserved = dict(target, binary_forecasts=[dict(BINARIES[0], id="__scenarios__")])
    for retract in (False, True):
        ok, errors = fr.validate_manual_settlement(
            reserved, "__scenarios__", None if retract else "YES", None if retract else KNOWN_AT,
            URL, retract=retract, now=now)
        assert not ok and "reserved" in errors[0], retract
    # The target-independent checks run on their own (callers use them before any lookup).
    assert fr.validate_manual_attestation(KNOWN_AT, URL, now=now) == (True, [])
    assert fr.validate_manual_attestation(None, NOTE, retract=True, now=now) == (True, [])
    ok, errors = fr.validate_manual_attestation("2025-10-01T00:00:00Z", "short", now=now)
    assert not ok and "future" in errors[0] and "evidence" in errors[1]


# ─────────────────────────────── target helper ───────────────────────────────
def test_load_manual_target_ledger_then_report(capsys, ledger, reports, monkeypatch):
    row = _commit(ledger)
    target, reason = fr.load_manual_target("r1", ledger_dir=ledger)
    assert reason is None
    assert (target["source"], target["commit_id"], target["as_of"], target["created_at"]) == \
        ("ledger", row["commit_id"], "2025-06-01", "2025-06-02T08:00:00+00:00")
    assert [s["name"] for s in target["scenarios"]] == ["Status quo", "Escalation", "De-escalation"]
    # Two primary rows for one report identify no target.
    _commit(ledger, "r-twin", as_of="2025-06-01")
    _commit(ledger, "r-twin", as_of="2025-06-03", horizon="2026")
    assert fr.load_manual_target("r-twin", ledger_dir=ledger) == (None, "ambiguous_target")
    assert fr.load_manual_target("  ", ledger_dir=ledger) == (None, "missing_report_id")

    # No ledger row: the report itself, publishable at issue even after a policy bump.
    _write_sealed_report("r-old", _forecast([]))
    monkeypatch.setattr(Config, "REPORT_FINAL_AUDIT_POLICY_VERSION",
                        int(Config.REPORT_FINAL_AUDIT_POLICY_VERSION) + 1)
    target, reason = fr.load_manual_target("r-old", ledger_dir=ledger)
    assert reason is None
    assert (target["source"], target["commit_id"], target["as_of"], target["created_at"]) == \
        ("report", None, None, "2026-05-02T08:00:00+00:00")
    # The CLI attests against it; the origin is the report's creation stamp. No production
    # primary row exists for resolved_view to label, so the scenario event is recorded with a
    # warning that it enters no calibration.
    code, event, err = _resolve(capsys, ledger, "--scenario", "adopted", "--known-at",
                                "2026-07-01T00:00:00Z", "--evidence", URL, report_id="r-old")
    assert code == 0
    assert (event["outcome"], event["target_commit_id"], event["prospective"]) == \
        ("Adopted", None, True)
    assert f"warning: {fr.MANUAL_NOT_BINDABLE}" in err
    view = fr.resolved_view(fl.read_ledger(ledger), fl.read_market_resolutions(ledger))
    assert view and all(row["report_id"] != "r-old" for row in view)
    assert fr.manual_not_bindable_reason(target, "F1") is None  # binaries fold without a row
    assert fr.manual_not_bindable_reason(dict(target, source="ledger"), "scenario") is None

    def target_reason(**kwargs):
        return fr.load_manual_target("r-x", ledger_dir=ledger, **kwargs)

    sealed = {"scenarios": copy.deepcopy(SCENARIOS)}
    assert target_reason(publishable_fn=lambda rid: False)[1] == "not_publishable"
    assert target_reason(publishable_fn=lambda rid: 1 / 0)[1] == "not_publishable"
    assert target_reason(publishable_fn=lambda rid: True,
                         load_forecast_fn=lambda rid: None)[1] == "not_sealed"
    assert target_reason(publishable_fn=lambda rid: True,
                         load_forecast_fn=lambda rid: 1 / 0)[1] == "not_sealed"
    assert target_reason(publishable_fn=lambda rid: True, load_forecast_fn=lambda rid: dict(
        sealed, evaluation={"record_class": "evaluation"}))[1] == "evaluation_run"
    target, reason = target_reason(publishable_fn=lambda rid: True,
                                   load_forecast_fn=lambda rid: sealed)
    assert (reason, target["source"], target["created_at"]) == (None, "report", None)
    # Only an explicit proof of publication passes: True, or the publishable_at_issue dict
    # with publishable True. The documented default itself, passed explicitly, fails closed
    # for a report that does not exist.
    for result in ({"publishable": False}, {"publishable": "yes"}, {}, "false", 1, None):
        assert target_reason(publishable_fn=lambda rid, result=result: result,
                             load_forecast_fn=lambda rid: sealed)[1] == "not_publishable", result
    assert target_reason(publishable_fn=lambda rid: {"publishable": True},
                         load_forecast_fn=lambda rid: sealed)[1] is None
    assert target_reason(publishable_fn=ReportManager.publishable_at_issue,
                         load_forecast_fn=lambda rid: sealed)[1] == "not_publishable"
    # Rows that are not a production primary (a revision, an evaluation run) never fall back.
    forecast = {"horizon": "2025", "scenarios": copy.deepcopy(SCENARIOS),
                "binary_forecasts": []}
    _commit(ledger, "r-eval", record_class="evaluation", forecast=forecast)
    assert fr.load_manual_target("r-eval", ledger_dir=ledger,
                                 publishable_fn=lambda rid: True,
                                 load_forecast_fn=lambda rid: sealed) == \
        (None, "not_production_primary")
    # Legacy schema_version 1 production rows prove nothing either way: the report decides.
    with open(os.path.join(ledger, "ledger.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"report_id": "r-legacy", "scenarios": SCENARIOS}) + "\n")
    assert fr.load_manual_target("r-legacy", ledger_dir=ledger, publishable_fn=lambda rid: True,
                                 load_forecast_fn=lambda rid: sealed)[1] is None


# ─────────────────────────────── calibration ─────────────────────────────────
def test_calibration_after_manual_scenario_event(capsys, ledger):
    _commit(ledger)
    assert fl.calibration_summary(ledger, fold_settlements=True)["n_resolved"] == 0
    assert _attest(capsys, ledger, "escalation")[0] == 0
    folded = fl.calibration_summary(ledger, fold_settlements=True)
    expected = calibration_report([{"forecast": {"scenarios": SCENARIOS}, "outcome": "Escalation"}])
    assert (folded["n_resolved"], folded["excluded"], folded["mean_brier"]) == \
        (1, {}, expected["mean_brier"])
    # The recalibrator fits one point per scenario of the one resolved forecast.
    assert fl.recalibration_param(ledger, fold_settlements=True)["n"] == len(SCENARIOS)
    # The report path's historical read (fold off, the default) never sees the event.
    assert Config.FORECAST_LEDGER_SETTLEMENT_FOLD is False
    assert fl.calibration_summary(ledger)["n_resolved"] == 0
    # Point in time: an as-of date on or before the attested known-at excludes it.
    assert fl.calibration_summary(ledger, fold_settlements=True, as_of="2025-09-01")["excluded"] \
        == {"known_on_or_after_as_of": 1}
    assert fl.calibration_summary(ledger, fold_settlements=True,
                                  as_of="2025-09-02")["n_resolved"] == 1


# ─────────────────────────────── POST /api/v1/resolve ────────────────────────
@pytest.fixture
def client(reports, monkeypatch):
    monkeypatch.setattr(Config, "API_V1_ENABLED", True, raising=False)
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _resolved_path(report_id):
    return os.path.join(ReportManager._get_report_folder(report_id), "resolved.json")


def _commit_report(report_id):
    """A publishable report plus its production primary commit row in the default ledger."""
    _save_report(report_id, publish=True)
    forecast = ReportManager.load_structured_forecast(report_id)
    assert forecast is not None
    return _commit(fl.ledger_dir(), report_id, forecast=forecast)


def _post(client, report_id, **body):
    response = client.post(f"/api/v1/resolve/{report_id}", json=body)
    return response.status_code, response.get_json()


def test_v1_resolve_unmatched_outcome_400_no_file(client):
    _commit_report("r-api")
    for body in ({"outcome": "Collapse"},
                 {"outcomes": ["Collapse"]},
                 {"outcome": "Collapse", "outcome_known_at": KNOWN_AT, "evidence": URL}):
        status, payload = _post(client, "r-api", **body)
        assert status == 400 and payload["success"] is False
        assert "unmatched_outcome" in payload["error"]
    assert not os.path.exists(_resolved_path("r-api"))
    assert fl.read_market_resolutions() == []


def test_v1_resolve_with_known_at_records_attested_event(client):
    row = _commit_report("r-api")
    status, payload = _post(client, "r-api", outcome=" base-case ", outcome_known_at=KNOWN_AT,
                            evidence=URL)
    assert status == 200
    data = payload["data"]
    assert data["settlement"] == {"recorded": True, "event_key": "manual", "reason": None}
    assert data["scoring"]["outcome_matched_a_scenario"] is True
    (event,) = fl.read_market_resolutions()
    assert (event["forecast_id"], event["item_kind"], event["outcome"], event["known_at_basis"],
            event["scoring_eligible"], event["target_commit_id"], event["source_kind"]) == \
        ("__scenarios__", "scenario_set", "Base case", "attested", True, row["commit_id"], "manual")
    assert os.path.exists(_resolved_path("r-api"))
    assert fl.calibration_summary(fold_settlements=True)["n_resolved"] == 1
    # The same attestation again: resolved.json is rewritten, the ledger keeps one event.
    status, payload = _post(client, "r-api", outcome="Base case", outcome_known_at=KNOWN_AT,
                            evidence=URL)
    assert status == 200
    assert payload["data"]["settlement"] == {"recorded": False, "event_key": "manual",
                                             "reason": "already_recorded"}
    assert len(fl.read_market_resolutions()) == 1
    # A different attestation needs an explicit correction (CLI --supersedes): 409, no write.
    with open(_resolved_path("r-api"), "rb") as fh:
        resolved_before = fh.read()
    status, payload = _post(client, "r-api", outcome="Other", outcome_known_at=KNOWN_AT,
                            evidence=URL)
    assert status == 409 and "--supersedes" in payload["error"]
    # Invalid attestations are 400 and write nothing.
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    for body in ({"outcome_known_at": future, "evidence": URL},
                 {"outcome_known_at": "2025-09-01T10:00:00", "evidence": URL},
                 {"outcome_known_at": KNOWN_AT, "evidence": "short"},
                 {"outcome_known_at": KNOWN_AT},
                 {"evidence": URL}):
        status, payload = _post(client, "r-api", outcome="Other", **body)
        assert status == 400 and payload["success"] is False, body
    with open(_resolved_path("r-api"), "rb") as fh:
        assert fh.read() == resolved_before
    assert len(fl.read_market_resolutions()) == 1

    # A report without a ledger row attests against itself (publishable at issue, sealed);
    # with no creation stamp its origin is unknown: recorded, never scored.
    _save_report("r-legacy-api", publish=True)
    status, payload = _post(client, "r-legacy-api", outcome="Other",
                            outcome_known_at="2025-09-01", evidence=NOTE)
    # Recorded, but no production primary row exists for it to label: the response says so.
    assert status == 200
    assert payload["data"]["settlement"] == {"recorded": True, "event_key": "manual",
                                             "reason": fr.MANUAL_NOT_BINDABLE}
    legacy_event = fl.read_market_resolutions()[-1]
    assert (legacy_event["report_id"], legacy_event["target_commit_id"],
            legacy_event["scoring_eligible"], legacy_event["ineligible_reason"]) == \
        ("r-legacy-api", None, False, "prospective_unknown")
    # A report whose ledger rows name no production primary cannot enter calibration.
    _save_report("r-ens", publish=True)
    _commit(fl.ledger_dir(), "r-ens", record_class="ensemble_member",
            forecast=ReportManager.load_structured_forecast("r-ens"))
    status, payload = _post(client, "r-ens", outcome="Other", outcome_known_at=KNOWN_AT,
                            evidence=URL)
    assert status == 409 and "not_production_primary" in payload["error"]
    # Invalid input is 400 before any target lookup, so it is 400 for r-ens too.
    for body in ({"outcome_known_at": future, "evidence": URL},
                 {"outcome_known_at": KNOWN_AT, "evidence": "short"}):
        status, payload = _post(client, "r-ens", outcome="Other", **body)
        assert status == 400, body
    assert not os.path.exists(_resolved_path("r-ens"))


def test_v1_resolve_appends_before_writing_resolved_json(client, monkeypatch):
    """resolved.json is written only once the ledger holds the attestation (appended, or an
    identical one already recorded), so it never disagrees with the ledger."""
    _commit_report("r-api")
    real_append = fl.append_settlement_event
    body = {"outcome": "Base case", "outcome_known_at": KNOWN_AT, "evidence": URL}

    # The ledger does not take the event (not writable): 500, nothing written anywhere.
    monkeypatch.setattr(fl, "append_settlement_event", lambda event, *, d=None: None)
    status, payload = _post(client, "r-api", **body)
    assert status == 500 and payload["success"] is False
    assert not os.path.exists(_resolved_path("r-api"))
    assert fl.read_market_resolutions() == []

    # A concurrent request wins the key with a different attestation: 409, no resolved.json.
    def lose_to(outcome):
        def append(event, *, d=None):
            real_append(dict(event, outcome=outcome, resolved_outcome=outcome), d=d)
            return None
        return append

    monkeypatch.setattr(fl, "append_settlement_event", lose_to("Other"))
    status, payload = _post(client, "r-api", **body)
    assert status == 409 and "--supersedes" in payload["error"]
    assert not os.path.exists(_resolved_path("r-api"))
    assert [e["outcome"] for e in fl.read_market_resolutions()] == ["Other"]

    # A concurrent request wins with the same attestation: a no-op, resolved.json written.
    _commit_report("r-api-2")
    monkeypatch.setattr(fl, "append_settlement_event", lose_to("Base case"))
    status, payload = _post(client, "r-api-2", **body)
    assert status == 200
    assert payload["data"]["settlement"] == {"recorded": False, "event_key": "manual",
                                             "reason": "already_recorded"}
    with open(_resolved_path("r-api-2"), encoding="utf-8") as fh:
        assert json.load(fh)["outcome"] == "Base case"


def test_v1_resolve_without_known_at_legacy_file_only(client):
    _commit_report("r-api")
    status, payload = _post(client, "r-api", outcome="other")
    assert status == 200
    data = payload["data"]
    assert data["settlement"] == {"recorded": False, "event_key": None,
                                  "reason": "outcome_known_at and evidence required to enter "
                                            "calibration"}
    assert (data["report_id"], data["outcome"]) == ("r-api", "other")
    with open(_resolved_path("r-api"), encoding="utf-8") as fh:
        record = json.load(fh)
    assert set(record) == {"report_id", "simulation_id", "outcome", "scoring", "resolved_at",
                           "forecast"}
    assert (record["outcome"], record["scoring"]) == ("other", data["scoring"])
    assert not os.path.exists(os.path.join(fl.ledger_dir(), "resolutions.jsonl"))
    assert fl.calibration_summary(fold_settlements=True)["n_resolved"] == 0


def test_v1_resolve_unpublished_still_409(client):
    _save_report("r-blocked", publish=False)
    status, _ = _post(client, "r-blocked", outcome="Base case", outcome_known_at=KNOWN_AT,
                      evidence=URL)
    assert status == 409
    assert not os.path.exists(_resolved_path("r-blocked"))
    assert fl.read_market_resolutions() == []
