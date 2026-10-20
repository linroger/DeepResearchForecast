"""Real durable ledger with synthetic external observations; no live accuracy claims."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib
import json
import os
import subprocess
import sys

import pytest

from app.services import forecast_feedback as feedback
from app.services import forecast_ledger as ledger
from app.services import official_data

pytestmark = pytest.mark.guarded_runner
CREATED = "2026-01-01T00:00:00Z"
RESOLVED = "2026-03-01T00:00:00Z"


def forecast():
    return {
        "horizon": "2026",
        "scenarios": [
            {"name": "Growth", "probability": 0.7, "resolution_criteria": "Aggregate expands"},
            {"name": "Decline", "probability": 0.3, "resolution_criteria": "Aggregate contracts"},
        ],
        "binary_forecasts": [
            {"id": "F1", "statement": "Event A", "probability": 0.7,
             "resolution_criteria": "settles by 2026-02-01",
             "market_anchor": {"market_id": "m1", "resolution_equivalence": "exact"}},
            {"id": "F2", "statement": "Unemployment above 4 percent", "probability": 0.6,
             "resolution_criteria": "January 2026 official unemployment > 4",
             "data_anchor": {"series": "fred:UNRATE", "comparator": ">", "threshold": 4,
                             "units": "Percent", "observation": "2026-01"}},
        ],
    }


def publish(tmp_path, fc=None, report_id="r1", created_at=CREATED):
    return ledger.record_published_forecast(fc if fc is not None else forecast(),
                                           report_id=report_id, created_at=created_at, d=tmp_path)


def market_row(**changes):
    return dict({"report_id": "r1", "forecast_id": "F1", "market_id": "m1",
                 "resolved_outcome": "Yes", "resolved_yes_price": 1.0, "model_p": 0.7,
                 "brier_contribution": 999, "resolved_at": RESOLVED}, **changes)


def data_row():
    dataset = {"series": "fred:UNRATE", "units": "Percent", "frequency": "M",
               "retrieved_at": RESOLVED, "source_url": "https://fred.stlouisfed.org/series/UNRATE",
               "observations": [{"date": "2026-01-01", "value": 4.2, "flag": ""}]}
    anchor = forecast()["binary_forecasts"][1]["data_anchor"]
    decision = official_data.resolve_data_anchor(anchor, dataset, as_of=RESOLVED)
    assert decision["status"] == "resolved"
    return {"report_id": "r1", "forecast_id": "F2", "series": "fred:UNRATE",
            "resolved_outcome": decision["outcome"], "model_p": 0.6, "resolved_at": RESOLVED,
            "observation": decision["observation"], "data_anchor": anchor,
            "dataset_snapshot": dataset, "dataset_sha256": feedback._digest(dataset),
            "units": "Percent", "transform": "", "source_url": dataset["source_url"],
            "retrieved_at": RESOLVED, "vintage": ""}


def reconcile(tmp_path, market=None, data=None):
    return ledger.reconcile_published_resolutions("r1", market_rows=market or [],
                                                  data_rows=data or [], d=tmp_path)


def test_publication_is_detached_immutable_and_metadata_idempotent(tmp_path):
    fc = forecast()
    original = publish(tmp_path, fc)
    raw = (tmp_path / feedback._FILE).read_bytes()
    fc.update(historical_calibration={"forecasts": 999}, binary_quality={"changed": True},
              audit={"passed": False}, track_record={"other": True})
    assert publish(tmp_path, fc, created_at=RESOLVED) == original
    assert (tmp_path / feedback._FILE).read_bytes() == raw
    original["forecast"]["binary_forecasts"][0]["probability"] = 0.99
    assert ledger.read_published_forecast("r1", d=tmp_path)["forecast"]["binary_forecasts"][0]["probability"] == 0.7
    fc["binary_forecasts"][0]["probability"] = 0.99
    with pytest.raises(ledger.ForecastFeedbackError, match="publication_conflict"):
        publish(tmp_path, fc)
    assert (tmp_path / feedback._FILE).read_bytes() == raw


def test_pure_digest_and_read_only_verify(tmp_path):
    fc = forecast()
    digest = ledger.forecast_publication_digest(fc)
    assert ledger.verify_published_forecast(fc, report_id="missing", d=tmp_path) is None
    assert list(tmp_path.iterdir()) == []
    assert publish(tmp_path)["publication_sha256"] == digest
    assert ledger.verify_published_forecast(fc, report_id="r1", d=tmp_path)["publication_sha256"] == digest
    fc["binary_forecasts"][0]["market_anchor"]["market_id"] = "changed"
    with pytest.raises(ledger.ForecastFeedbackError, match="publication_conflict"):
        ledger.verify_published_forecast(fc, report_id="r1", d=tmp_path)


@pytest.mark.parametrize("value", [True, False, "0.7", None, -0.1, 1.1, float("nan"), float("inf")])
def test_invalid_probabilities_rejected(tmp_path, value):
    fc = forecast()
    fc["binary_forecasts"][0]["probability"] = value
    with pytest.raises(ledger.ForecastFeedbackError):
        publish(tmp_path, fc)
    assert ledger.read_published_forecast("r1", d=tmp_path) is None


@pytest.mark.parametrize("change", ["scenario_duplicate", "binary_duplicate", "distribution", "golden", "evaluation"])
def test_invalid_publications_rejected(tmp_path, change):
    fc = forecast()
    if change == "scenario_duplicate":
        fc["scenarios"][1]["name"] = "Growth"
    elif change == "binary_duplicate":
        fc["binary_forecasts"][1]["id"] = "F1"
    elif change == "distribution":
        fc["scenarios"][1]["probability"] = 0.9
    else:
        fc["golden" if change == "golden" else "record_class"] = True if change == "golden" else "evaluation"
    with pytest.raises(ledger.ForecastFeedbackError):
        publish(tmp_path, fc)


def test_published_rounded_thirds_keep_exact_issued_probabilities_digest_and_score(tmp_path):
    fc = {"scenarios": [{"name": name, "probability": 0.3333} for name in ("A", "B", "C")]}
    original = deepcopy(fc)
    stored = publish(tmp_path, fc)
    assert sum(s["probability"] for s in stored["forecast"]["scenarios"]) == 0.9999
    assert stored["forecast"] == original
    assert stored["publication_sha256"] == feedback._digest(original)
    outcome = ledger.resolve_published_scenario("r1", "A", resolved_at=RESOLVED, d=tmp_path)
    assert outcome["score"]["realized_probability"] == 0.3333
    assert outcome["score"]["brier"] == round((0.3333 - 1) ** 2 + 2 * 0.3333 ** 2, 4)
    assert ledger.read_published_forecast("r1", d=tmp_path)["forecast"] == original
    assert ledger.read_published_resolutions("r1", tmp_path)[0]["score"] == outcome["score"]


@pytest.mark.parametrize("probability", [0.333, 0.3336])
def test_scenario_distribution_outside_rounding_tolerance_is_rejected(tmp_path, probability):
    fc = {"scenarios": [{"name": name, "probability": probability} for name in ("A", "B", "C")]}
    with pytest.raises(ValueError, match="invalid_scenario_distribution"):
        publish(tmp_path, fc)
    assert ledger.read_published_forecast("r1", d=tmp_path) is None


def test_native_exact_joins_recompute_scores_and_leave_scenarios_unresolved(tmp_path):
    publish(tmp_path)
    result = reconcile(tmp_path, [market_row()], [data_row()])
    assert result == {"accepted": 2, "duplicates": 0, "rejected": []}
    summary = ledger.production_track_record(d=tmp_path)
    assert summary["tracks"]["market_binary"]["mean_brier"] == 0.09
    assert summary["tracks"]["official_data_binary"]["mean_brier"] == 0.16
    assert summary["tracks"]["scenario"]["n_resolved"] == 0
    assert summary["tracks"]["scenario"]["n_outstanding"] == 1
    assert len(summary["scored_identities"]) == 2


@pytest.mark.parametrize("changes,reason", [
    ({"forecast_id": "wrong"}, "unknown_forecast"),
    ({"market_id": "wrong"}, "market_identity_mismatch"),
    ({"model_p": 0.9}, "probability_mismatch"),
    ({"model_p": True}, "invalid_probability"),
    ({"resolved_outcome": 1}, "invalid_outcome"),
    ({"resolved_outcome": "yes"}, "invalid_outcome"),
    ({"resolved_outcome": "No"}, "market_not_terminal"),
    ({"resolved_yes_price": 0.5}, "market_not_terminal"),
    ({"resolved_yes_price": float("nan")}, "invalid_probability"),
    ({"resolved_at": "2025-01-01"}, "outcome_before_publication"),
    ({"record_class": "evaluation"}, "evaluation_excluded"),
])
def test_market_invalid_evidence_cannot_score(tmp_path, changes, reason):
    publish(tmp_path)
    result = reconcile(tmp_path, [market_row(**changes)])
    assert result["rejected"][0]["reason"] == reason
    assert ledger.production_track_record(d=tmp_path)["tracks"]["market_binary"]["n_resolved"] == 0


@pytest.mark.parametrize("field", ["dataset_sha256", "series", "model_p", "resolved_outcome",
                                 "source_url", "observation", "data_anchor", "resolved_at"])
def test_official_evidence_must_replay_original_contract(tmp_path, field):
    publish(tmp_path)
    row = data_row()
    changes = {"dataset_sha256": "bad", "series": "fred:OTHER", "model_p": 0.99,
               "resolved_outcome": 1, "source_url": "https://example.invalid",
               "observation": {"date": "2026-01-01", "value": 100},
               "data_anchor": dict(row["data_anchor"], threshold=5),
               "resolved_at": "2026-02-01"}
    row[field] = changes[field]
    result = reconcile(tmp_path, data=[row])
    assert result["accepted"] == 0 and len(result["rejected"]) == 1
    assert ledger.production_track_record(d=tmp_path)["tracks"]["official_data_binary"]["n_resolved"] == 0


def test_official_equivalent_period_alias_accepted_but_changed_period_rejected(tmp_path):
    publish(tmp_path)
    row = data_row()
    row["data_anchor"]["period"] = row["data_anchor"].pop("observation")
    assert reconcile(tmp_path, data=[row])["accepted"] == 1
    row["data_anchor"]["period"] = "2026-02"
    assert reconcile(tmp_path, data=[row])["rejected"][0]["reason"] == "data_contract_mismatch"


def test_official_period_frequency_cannot_be_replaced_by_incoming_dataset(tmp_path):
    fc = forecast()
    fc["binary_forecasts"][1]["data_anchor"].update(
        observation="2026-01-01", period="2026-01-01", frequency="Q")
    publish(tmp_path, fc)
    row = data_row()
    row["data_anchor"] = fc["binary_forecasts"][1]["data_anchor"]
    row["resolved_at"] = "2026-02-02"
    row["retrieved_at"] = row["dataset_snapshot"]["retrieved_at"] = "2026-02-02"
    row["dataset_sha256"] = feedback._digest(row["dataset_snapshot"])
    result = reconcile(tmp_path, data=[row])
    assert result["rejected"][0]["reason"] == "data_contract_mismatch"
    assert ledger.production_track_record(d=tmp_path)["tracks"]["official_data_binary"]["n_resolved"] == 0


def test_duplicate_and_conflict_keep_original_evidence_and_score(tmp_path):
    publish(tmp_path)
    assert reconcile(tmp_path, [market_row()])["accepted"] == 1
    original = (tmp_path / feedback._FILE).read_bytes()
    assert reconcile(tmp_path, [market_row(resolved_at="2026-03-02")])["duplicates"] == 1
    result = reconcile(tmp_path, [market_row(resolved_outcome="No", resolved_yes_price=0.0)])
    assert result["rejected"][0]["reason"] == "outcome_conflict"
    assert (tmp_path / feedback._FILE).read_bytes() == original
    assert ledger.production_track_record(d=tmp_path)["tracks"]["market_binary"]["n_resolved"] == 1


def test_exact_scenario_resolution_original_probabilities_and_self_exclusion(tmp_path):
    publish(tmp_path)
    result = ledger.resolve_published_scenario("r1", "Growth", evidence={"source": "manual adjudication"},
                                                resolved_at=RESOLVED, d=tmp_path)
    assert result["score"]["brier"] == 0.18
    assert result["score"]["realized_probability"] == 0.7
    assert ledger.resolve_published_scenario("r1", "Growth", evidence={"source": "later"},
                                             resolved_at="2026-04-01", d=tmp_path) == result
    for outcome in ("growth", "Growth ", "0", 0, True, "Decline"):
        with pytest.raises(ledger.ForecastFeedbackError):
            ledger.resolve_published_scenario("r1", outcome, resolved_at=RESOLVED, d=tmp_path)
    summary = ledger.production_track_record(d=tmp_path, exclude_report_id="r1")
    assert summary["n_reports"] == 0
    assert summary["scored_identities"] == []
    assert all(t["n_forecasts"] == 0 for t in summary["tracks"].values())


def test_unregistered_native_rows_never_admitted(tmp_path):
    ledger.append_market_resolution(report_id="r1", forecast_id="F1", market_id="m1",
                                   resolved_outcome="Yes", model_p=0.7, market_p_at_research=0.5,
                                   brier_contribution=0.09, resolved_at=RESOLVED, d=tmp_path)
    with pytest.raises(ledger.ForecastFeedbackError, match="unpublished_report"):
        ledger.reconcile_published_resolutions("r1", d=tmp_path)
    with pytest.raises(ledger.ForecastFeedbackError, match="unpublished_report"):
        ledger.resolve_published_scenario("r1", "Growth", resolved_at=RESOLVED, d=tmp_path)
    assert ledger.production_track_record(d=tmp_path)["n_reports"] == 0


def test_read_published_resolutions_missing_is_read_only_and_ignores_native_candidates(tmp_path):
    missing = tmp_path / "missing"
    assert ledger.read_published_resolutions("r1", missing) == []
    assert not missing.exists()
    publish(tmp_path)
    (tmp_path / "resolutions.jsonl").write_text(json.dumps(market_row()) + "\n")
    original = (tmp_path / feedback._FILE).read_bytes()
    assert ledger.read_published_resolutions("r1", d=tmp_path) == []
    assert ledger.read_published_resolutions("unregistered", d=tmp_path) == []
    assert (tmp_path / feedback._FILE).read_bytes() == original


def test_read_published_resolutions_returns_detached_validated_typed_rows_after_reload(tmp_path):
    publish(tmp_path)
    publish(tmp_path, report_id="other")
    assert reconcile(tmp_path, [market_row()], [data_row()])["accepted"] == 2
    ledger.resolve_published_scenario("r1", "Growth", evidence={"source": "manual"},
                                     resolved_at=RESOLVED, d=tmp_path)
    ledger.resolve_published_scenario("other", "Decline", resolved_at=RESOLVED, d=tmp_path)
    original = (tmp_path / feedback._FILE).read_bytes()
    rows = ledger.read_published_resolutions("r1", tmp_path)
    assert [row["kind"] for row in rows] == ["market_binary", "official_data_binary", "scenario"]
    assert [row["forecast_id"] for row in rows] == ["F1", "F2", None]
    assert all(row["report_id"] == "r1" for row in rows)
    assert [row["score"]["brier"] for row in rows] == [0.09, 0.16, 0.18]
    assert rows[0]["outcome"] is True
    assert rows[0]["evidence"]["brier_contribution"] == 999  # Retained candidate; score is authoritative.
    frozen = deepcopy(rows)
    rows[0]["score"]["brier"] = 0.99
    rows[1]["evidence"]["dataset_snapshot"]["observations"][0]["value"] = 999
    rows.clear()
    importlib.reload(feedback)
    assert ledger.read_published_resolutions("r1", tmp_path) == frozen
    assert (tmp_path / feedback._FILE).read_bytes() == original


def test_read_published_resolutions_preserves_first_outcome_after_provider_conflict(tmp_path):
    publish(tmp_path)
    assert reconcile(tmp_path, [market_row()])["accepted"] == 1
    frozen = ledger.read_published_resolutions("r1", tmp_path)
    conflict = reconcile(tmp_path, [market_row(resolved_outcome="No", resolved_yes_price=0.0)])
    assert conflict["rejected"][0]["reason"] == "outcome_conflict"
    assert reconcile(tmp_path, [market_row(resolved_at="2026-04-01")])["duplicates"] == 1
    original = (tmp_path / feedback._FILE).read_bytes()
    assert ledger.read_published_resolutions("r1", tmp_path) == frozen
    assert frozen[0]["outcome"] is True and frozen[0]["score"]["brier"] == 0.09
    assert frozen[0]["resolved_at"] == RESOLVED
    assert (tmp_path / feedback._FILE).read_bytes() == original


@pytest.mark.parametrize("damage", ["torn_tail", "bound_score"])
def test_read_published_resolutions_fails_closed_on_invalid_journal(tmp_path, damage):
    publish(tmp_path)
    reconcile(tmp_path, [market_row()])
    path = tmp_path / feedback._FILE
    if damage == "torn_tail":
        with path.open("ab") as stream:
            stream.write(b"torn")
        code = "journal_torn_tail"
    else:
        records = [json.loads(line) for line in path.read_text().splitlines()]
        records[-1]["event"]["record"]["score"]["brier"] = 0.99
        records[-1]["sha256"] = feedback._digest(records[-1]["event"])
        path.write_text("".join(json.dumps(record) + "\n" for record in records))
        code = "journal_outcome_mismatch"
    original = path.read_bytes()
    with pytest.raises(ValueError, match=code):
        ledger.read_published_resolutions("r1", tmp_path)
    assert path.read_bytes() == original


def test_native_durable_outcome_can_be_joined_after_crash(tmp_path):
    publish(tmp_path)
    # Native append is real; the external settlement itself is synthetic.
    row = market_row()
    row.pop("brier_contribution")
    assert ledger.append_market_resolution(**row, brier_contribution=0.09,
                                            market_p_at_research=0.5, d=tmp_path)
    assert ledger.production_track_record(d=tmp_path)["tracks"]["market_binary"]["n_resolved"] == 0
    assert ledger.reconcile_published_resolutions("r1", d=tmp_path)["accepted"] == 1
    assert ledger.reconcile_published_resolutions("r1", d=tmp_path)["duplicates"] == 1
    assert ledger.production_track_record(d=tmp_path)["tracks"]["market_binary"]["mean_brier"] == 0.09


def test_crash_after_outcome_fsync_reconstructs_without_summary_cache(tmp_path, monkeypatch):
    publish(tmp_path)
    real_append = feedback._append
    def interrupted(stream, events, event):
        real_append(stream, events, event)
        raise OSError("synthetic crash after fsync")
    with monkeypatch.context() as patch:
        patch.setattr(feedback, "_append", interrupted)
        with pytest.raises(OSError, match="synthetic crash"):
            reconcile(tmp_path, [market_row()])
    before = ledger.production_track_record(d=tmp_path)
    importlib.reload(feedback)
    assert ledger.production_track_record(d=tmp_path) == before
    assert reconcile(tmp_path, [market_row()])["duplicates"] == 1
    assert before["tracks"]["market_binary"]["n_resolved"] == 1


def test_write_failure_observable_and_flock_never_silently_degrades(tmp_path, monkeypatch):
    import fcntl
    def denied(*args):
        raise OSError("synthetic lock failure")
    monkeypatch.setattr(fcntl, "flock", denied)
    with pytest.raises(OSError, match="lock failure"):
        publish(tmp_path)
    assert (tmp_path / feedback._FILE).read_bytes() == b""


def test_fsync_failure_retry_reestablishes_durability(tmp_path, monkeypatch):
    def interrupted(fd):
        raise OSError("synthetic fsync failure")
    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", interrupted)
        with pytest.raises(OSError, match="fsync failure"):
            publish(tmp_path)
        # A complete visible line is not proof that the failed barrier succeeded.
        with pytest.raises(OSError, match="fsync failure"):
            publish(tmp_path)
    calls = []
    original = os.fsync
    def counted(fd):
        calls.append(fd)
        original(fd)
    monkeypatch.setattr(os, "fsync", counted)
    publish(tmp_path)
    assert len(calls) == 2  # Journal bytes plus containing directory entry.
    assert len((tmp_path / feedback._FILE).read_text().splitlines()) == 1


def test_outcome_fsync_failure_never_acknowledged_on_retry(tmp_path, monkeypatch):
    publish(tmp_path)
    def interrupted(fd):
        raise OSError("synthetic outcome fsync failure")
    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", interrupted)
        for _ in range(2):
            with pytest.raises(OSError, match="outcome fsync failure"):
                ledger.resolve_published_scenario("r1", "Growth", resolved_at=RESOLVED, d=tmp_path)
    row = ledger.resolve_published_scenario("r1", "Growth", resolved_at=RESOLVED, d=tmp_path)
    assert row["score"]["brier"] == 0.18
    assert len((tmp_path / feedback._FILE).read_text().splitlines()) == 2


@pytest.mark.parametrize("damage,code", [(b'{"event":', "journal_torn_tail"),
                                        (b"not json\n", "journal_corrupt")])
def test_corrupt_tail_blocks_reads_and_appends_without_repair(tmp_path, damage, code):
    publish(tmp_path)
    target = tmp_path / feedback._FILE
    with target.open("ab") as stream:
        stream.write(damage)
    damaged = target.read_bytes()
    for action in (lambda: ledger.production_track_record(d=tmp_path),
                   lambda: publish(tmp_path, report_id="new"),
                   lambda: ledger.read_published_forecast("r1", d=tmp_path)):
        with pytest.raises(ValueError, match=code):
            action()
    assert target.read_bytes() == damaged


def test_journal_checksum_rejects_valid_json_mutation(tmp_path):
    publish(tmp_path)
    path = tmp_path / feedback._FILE
    record = json.loads(path.read_text())
    record["event"]["record"]["forecast"]["binary_forecasts"][0]["probability"] = 0.99
    path.write_text(json.dumps(record) + "\n")
    with pytest.raises(ValueError, match="journal_checksum"):
        ledger.production_track_record(d=tmp_path)


def test_native_torn_tail_blocks_reconciliation(tmp_path):
    publish(tmp_path)
    (tmp_path / "resolutions.jsonl").write_text(json.dumps(market_row()))
    with pytest.raises(ValueError, match="native_torn_tail"):
        ledger.reconcile_published_resolutions("r1", d=tmp_path)


def test_queue_rotates_old_due_reports_across_restart_and_bounds_questions(tmp_path):
    for rid in ("old", "middle", "new"):
        publish(tmp_path, report_id=rid)
    initial = ledger.outstanding_published_report_ids(as_of="2026-04-01", limit=2, d=tmp_path)
    assert len(initial) == 2
    ledger.mark_published_report_checked(initial[0], checked_at=RESOLVED, d=tmp_path)
    importlib.reload(feedback)
    following = ledger.outstanding_published_report_ids(as_of="2026-04-01", limit=3, d=tmp_path)
    assert following[-1] == initial[0]
    assert len(ledger.list_outstanding_published_questions(as_of="2026-04-01", limit=2, d=tmp_path)) == 2
    questions = ledger.list_outstanding_published_questions(limit=3, d=tmp_path)
    assert len({q["report_id"] for q in questions}) == 3
    assert ledger.outstanding_published_report_ids(limit=0, d=tmp_path) == []
    with pytest.raises(ValueError, match="invalid_limit"):
        ledger.outstanding_published_report_ids(limit=True, d=tmp_path)


def test_question_queue_rotates_manual_prefix_after_restart(tmp_path):
    fc = forecast()
    fc["binary_forecasts"].insert(0, {"id": "manual", "probability": 0.5})
    publish(tmp_path, fc)
    observed = []
    for _ in range(3):
        selected = ledger.list_outstanding_published_questions(limit=1, d=tmp_path)[0]
        observed.append(selected["forecast_id"])
        ledger.mark_published_report_checked("r1", checked_at=RESOLVED,
                                             selection_token=selected["selection_token"], d=tmp_path)
        importlib.reload(feedback)
    assert observed == ["manual", "F1", "F2"]
    assert ledger.list_published_report_ids(tmp_path) == ["r1"]


def test_concurrent_question_pollers_advance_a_selected_batch_once(tmp_path):
    publish(tmp_path)
    seen = []
    for _ in range(4):
        first = ledger.list_outstanding_published_questions(limit=1, d=tmp_path)[0]
        second = ledger.list_outstanding_published_questions(limit=1, d=tmp_path)[0]
        seen.append(first["forecast_id"])
        assert first["selection_token"] == second["selection_token"]
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda row: ledger.mark_published_report_checked(
                "r1", checked_at=RESOLVED, selection_token=row["selection_token"], d=tmp_path),
                [first, second]))
        assert results[0] == results[1]
        importlib.reload(feedback)
    assert seen == ["F1", "F2", "F1", "F2"]
    assert len((tmp_path / feedback._FILE).read_text().splitlines()) == 5


def test_dual_anchors_near_market_and_unanchored_remain_separate(tmp_path):
    fc = forecast()
    fc["binary_forecasts"][1]["market_anchor"] = fc["binary_forecasts"][0]["market_anchor"]
    fc["binary_forecasts"][0]["market_anchor"]["resolution_equivalence"] = "near"
    fc["binary_forecasts"].append({"id": "F3", "probability": 0.5})
    publish(tmp_path, fc)
    assert reconcile(tmp_path, [market_row()])["rejected"][0]["reason"] == "market_not_exact"
    assert reconcile(tmp_path, [market_row(forecast_id="F2", model_p=0.6)])["rejected"][0]["reason"] == "resolution_kind_mismatch"
    assert reconcile(tmp_path, data=[data_row()])["accepted"] == 1
    tracks = ledger.production_track_record(d=tmp_path)["tracks"]
    assert sum(t["n_forecasts"] for k, t in tracks.items() if k != "scenario") == 3
    assert tracks["official_data_binary"]["n_resolved"] == 1
    assert tracks["market_binary"]["n_resolved"] == 0


@pytest.mark.parametrize("period,frequency,due", [
    ("2026-01", "", "2026-01-31"), ("2026-Q1", "", "2026-03-31"),
    ("2026-01-01", "A", "2026-12-31"), ("2026-01-01", "M", "2026-01-31"),
    ("2026-01-01", "Q", "2026-03-31"), ("2026-01-01", "W", "2026-01-07"),
])
def test_queue_uses_exact_data_period_instead_of_report_horizon(tmp_path, period, frequency, due):
    fc = forecast()
    fc["binary_forecasts"] = [fc["binary_forecasts"][1]]
    fc["binary_forecasts"][0]["data_anchor"].update(observation=period, frequency=frequency)
    fc["horizon"] = "2099"
    publish(tmp_path, fc)
    questions = ledger.list_outstanding_published_questions(as_of=due, d=tmp_path)
    assert len(questions) == 1 and questions[0]["resolution_date"] == due
    assert ledger.list_outstanding_published_questions(as_of="2025-12-31", d=tmp_path) == []


def test_queue_uses_canonical_fiscal_period_and_keeps_unknown_period_eligible(tmp_path):
    fc = forecast()
    fc["binary_forecasts"] = [fc["binary_forecasts"][1]]
    fc["binary_forecasts"][0]["data_anchor"].update(
        observation="FY2026", period="2025-10-01", frequency="A")
    fc["horizon"] = "2030"
    publish(tmp_path, fc)
    questions = ledger.list_outstanding_published_questions(as_of="2026-10-01", d=tmp_path)
    assert len(questions) == 1 and questions[0]["resolution_date"] == "2026-09-30"
    fc["binary_forecasts"][0]["data_anchor"].pop("period")
    publish(tmp_path, fc, report_id="unknown")
    questions = ledger.list_outstanding_published_questions(as_of="2026-08-01", d=tmp_path)
    assert len(questions) == 1 and questions[0]["report_id"] == "unknown"
    assert questions[0]["resolution_date"] is None


def test_legacy_scenarios_labelled_deduplicated_exclude_evaluation_and_published(tmp_path):
    publish(tmp_path)
    rows = []
    for rid in ("r1", "legacy", "golden"):
        row = ledger.append_forecast(forecast(), report_id=rid, d=tmp_path)
        row.update(resolved=True, outcome="Growth")
        if rid == "golden":
            row["golden"] = True
        rows.append(row)
    rows.append(deepcopy(rows[1]))
    (tmp_path / "ledger.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    summary = ledger.production_track_record(d=tmp_path)
    assert summary["legacy_scenario"] == {"source": "ledger.jsonl", "n_resolved": 1, "mean_brier": 0.18}
    assert summary["tracks"]["scenario"]["n_resolved"] == 0
    assert ledger.production_track_record(d=tmp_path, exclude_report_id="legacy")["legacy_scenario"]["n_resolved"] == 0


def test_legacy_official_summary_excludes_evaluation_and_invalid_scores(tmp_path):
    rows = [{"brier_contribution": 0.09}, {"brier_contribution": 0.16, "dataset_snapshot": {}},
            {"brier_contribution": 0.7, "record_class": "evaluation"},
            {"brier_contribution": 0.7, "golden": True},
            {"brier_contribution": 0.7, "dataset_snapshot": {"golden": True}},
            {"brier_contribution": 0.7, "dataset_snapshot": {"record_class": "evaluation"}}]
    rows.extend({"brier_contribution": value} for value in (
        None, True, float("nan"), float("inf"), -1, 2, "0.5"))
    (tmp_path / "data_resolutions.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows))
    assert ledger.data_brier_summary(tmp_path) == {"n_resolved": 2, "mean_brier": 0.125}
    assert ledger.official_data_track_record(tmp_path) == {
        "n_resolved": 2, "mean_brier": 0.125, "source": "data_resolutions.jsonl",
        "scoring": "binary Brier vs official observation"}
    assert ledger.production_track_record(d=tmp_path)["tracks"]["official_data_binary"]["n_resolved"] == 0


def test_frozen_track_record_verifies_after_new_outcomes_publications_and_legacy_changes(tmp_path):
    empty = ledger.production_track_record(d=tmp_path, exclude_report_id="next")
    publish(tmp_path)
    frozen = ledger.production_track_record(d=tmp_path, exclude_report_id="next")
    original = deepcopy(frozen)
    assert reconcile(tmp_path, [market_row()])["accepted"] == 1
    publish(tmp_path, report_id="next")
    ledger.mark_published_report_checked("r1", checked_at=RESOLVED, d=tmp_path)
    (tmp_path / "ledger.jsonl").write_text(json.dumps({
        "report_id": "legacy", "resolved": True, "outcome": "Growth",
        "scenarios": forecast()["scenarios"]}) + "\n")
    assert ledger.verify_production_track_record(empty, exclude_report_id="next", d=tmp_path)
    assert ledger.verify_production_track_record(frozen, exclude_report_id="next", d=tmp_path)
    assert frozen == original
    assert ledger.production_track_record(d=tmp_path)["tracks"]["market_binary"]["n_resolved"] == 1
    assert frozen["tracks"]["market_binary"]["n_resolved"] == 0


@pytest.mark.parametrize("change", ["count", "score", "identities", "digest", "length", "prefix", "exclude", "bool"])
def test_frozen_summary_tampering_is_rejected(tmp_path, change):
    publish(tmp_path)
    reconcile(tmp_path, [market_row()])
    summary = ledger.production_track_record(d=tmp_path, exclude_report_id="next")
    if change == "count":
        summary["tracks"]["market_binary"]["n_resolved"] = 100
    elif change == "score":
        summary["tracks"]["market_binary"]["mean_brier"] = 0.01
    elif change == "identities":
        summary["scored_identities"] = []
    elif change == "digest":
        summary["source_digest"] = "0" * 64
    elif change == "length":
        summary["journal_length"] += 1
    elif change == "prefix":
        summary["journal_sha256"] = "0" * 64
    elif change == "exclude":
        summary["excluded_report_id"] = "another"
    else:
        summary["n_reports"] = True
    with pytest.raises(ValueError, match="track_record"):
        ledger.verify_production_track_record(summary, exclude_report_id="next", d=tmp_path)


def test_frozen_summary_still_fails_on_corrupt_tail_after_its_prefix(tmp_path):
    publish(tmp_path)
    summary = ledger.production_track_record(d=tmp_path)
    with (tmp_path / feedback._FILE).open("ab") as stream:
        stream.write(b"torn")
    with pytest.raises(ValueError, match="journal_torn_tail"):
        ledger.verify_production_track_record(summary, d=tmp_path)


def test_threads_publish_and_settle_once(tmp_path):
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: publish(tmp_path), range(16)))
        results = list(executor.map(lambda _: reconcile(tmp_path, [market_row()]), range(16)))
    assert sum(r["accepted"] for r in results) == 1
    assert sum(r["duplicates"] for r in results) == 15
    assert len((tmp_path / feedback._FILE).read_text().splitlines()) == 2


def test_separate_guarded_processes_publish_once(tmp_path):
    guard = sys.modules["main_offline_guard"]
    script = tmp_path / "publish_child.py"
    backend = str(__import__("pathlib").Path(ledger.__file__).resolve().parents[2])
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {backend!r})\n"
        "from app.services.forecast_ledger import record_published_forecast\n"
        f"record_published_forecast({forecast()!r}, report_id='r1', created_at={CREATED!r}, d={str(tmp_path)!r})\n"
    )
    guard.allow_python_script(script)
    children = [subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True) for _ in range(3)]
    for child in children:
        stdout, stderr = child.communicate(timeout=30)
        assert child.returncode == 0, (stdout, stderr)
    assert len((tmp_path / feedback._FILE).read_text().splitlines()) == 1
    assert ledger.production_track_record(d=tmp_path)["n_reports"] == 1
