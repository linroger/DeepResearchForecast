"""Part2 feedback acceptance through the actual immutable journal, offline only."""
from copy import deepcopy
import hashlib
import json

import pytest

from app.config import Config
from app.services import forecast_feedback as feedback
from app.services import forecast_ledger as ledger
import scripts.resolution_monitor as monitor

pytestmark = pytest.mark.guarded_runner
CREATED = "2026-01-01T00:00:00Z"
RESOLVED = "2026-02-03T00:00:00Z"


def manual_binary(named=True):
    row = {"id": "F1", "statement": "The authority issues the final rule",
           "resolution_criteria": "The named publisher confirms the final rule by the deadline",
           "probability": 0.7, "resolution_date": "2026-02-01"}
    if named:
        row["resolution_contract"] = {"kind": "named_source_event", "publisher": "Agency",
                                       "event": "final rule issued", "deadline": "2026-02-01"}
    return row


def evidence():
    return {"text": "The Agency's dated statement confirms that the final rule was issued.",
            "url": "https://agency.example/releases/final-rule", "publisher": "Agency",
            "published_at": "2026-02-02T10:00:00Z", "retrieved_at": "2026-02-02T11:00:00Z",
            "adjudicator": "fixture reviewer"}


def publish(tmp_path, binary):
    return ledger.record_published_forecast({"binary_forecasts": [binary]}, report_id="r1",
                                           created_at=CREATED, d=tmp_path)


def resolve(tmp_path, binary, **changes):
    args = dict(outcome=True, evidence=evidence(),
                contract_sha256=feedback.binary_resolution_contract_sha256(binary), resolved_at=RESOLVED)
    args.update(changes)
    return feedback.resolve_published_binary("r1", "F1", **args, d=tmp_path)


@pytest.mark.parametrize("named,lane", [(True, "named_source_event"), (False, "unanchored_binary")])
def test_manual_resolution_reaches_durable_score_and_read_consumer(tmp_path, named, lane):
    binary = manual_binary(named)
    publication = publish(tmp_path, binary)
    outcome = resolve(tmp_path, binary)
    assert outcome["kind"] == lane and outcome["score"] == {"brier": 0.09, "probability": 0.7}
    assert outcome["evidence"]["adjudication"] == "manual"
    assert outcome["publication_sha256"] == publication["publication_sha256"]
    assert ledger.read_published_resolutions("r1", tmp_path) == [outcome]
    track = ledger.production_track_record(d=tmp_path)
    assert track["tracks"][lane]["n_resolved"] == 1
    assert ledger.verify_production_track_record(track, d=tmp_path)
    assert ledger.list_outstanding_published_questions(as_of=RESOLVED, d=tmp_path) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == [feedback._FILE]


@pytest.mark.parametrize("field,value,code", [
    ("text", "", "invalid_identity"), ("url", "file:///tmp/source", "invalid_evidence_url"),
    ("publisher", "Another Agency", "publisher_mismatch"),
    ("published_at", None, "invalid_timestamp"),
    ("published_at", "2025-12-30", "invalid_resolution_chronology"),
    ("published_at", "2026-02-01", "invalid_resolution_chronology"),
    ("retrieved_at", "2026-02-02T09:00:00Z", "invalid_resolution_chronology"),
    ("retrieved_at", "2027-01-01", "invalid_resolution_chronology"),
    ("adjudicator", "", "invalid_identity"),
])
def test_rejected_manual_evidence_leaves_journal_and_scores_unchanged(tmp_path, field, value, code):
    binary = manual_binary()
    publish(tmp_path, binary)
    before = (tmp_path / feedback._FILE).read_bytes()
    source = evidence()
    source[field] = value
    with pytest.raises(feedback.ForecastFeedbackError, match=code):
        resolve(tmp_path, binary, evidence=source)
    assert (tmp_path / feedback._FILE).read_bytes() == before
    assert ledger.production_track_record(d=tmp_path)["tracks"]["named_source_event"]["n_resolved"] == 0


def test_manual_wrong_hash_and_changed_contract_cannot_resolve(tmp_path):
    binary = manual_binary()
    publish(tmp_path, binary)
    for key in ("statement", "resolution_criteria", "resolution_date"):
        mutated = deepcopy(binary)
        mutated[key] += " changed" if key != "resolution_date" else "T12:00:00Z"
        with pytest.raises(feedback.ForecastFeedbackError, match="resolution_contract_mismatch"):
            resolve(tmp_path, binary, contract_sha256=feedback.binary_resolution_contract_sha256(mutated))
    with pytest.raises(feedback.ForecastFeedbackError, match="resolution_contract_mismatch"):
        resolve(tmp_path, binary, contract_sha256="0" * 64)
    assert ledger.read_published_resolutions("r1", tmp_path) == []


def test_manual_retries_keep_original_and_conflicts_reject(tmp_path):
    binary = manual_binary()
    publish(tmp_path, binary)
    original = resolve(tmp_path, binary)
    before = (tmp_path / feedback._FILE).read_bytes()
    changed = dict(evidence(), text="Another source quotation for the same adjudication.")
    assert resolve(tmp_path, binary, evidence=changed) == original
    with pytest.raises(feedback.ForecastFeedbackError, match="outcome_conflict"):
        resolve(tmp_path, binary, outcome=False)
    assert (tmp_path / feedback._FILE).read_bytes() == before


@pytest.mark.parametrize("outcome", [1, "Yes", None])
def test_manual_bool_outcome_is_strict(tmp_path, outcome):
    binary = manual_binary()
    publish(tmp_path, binary)
    with pytest.raises(feedback.ForecastFeedbackError, match="invalid_outcome"):
        resolve(tmp_path, binary, outcome=outcome)


def test_manual_deadline_is_declared_and_forecast_precedes_deadline(tmp_path):
    binary = manual_binary(False)
    binary.pop("resolution_date")
    publish(tmp_path, binary)
    with pytest.raises(feedback.ForecastFeedbackError, match="invalid_timestamp"):
        resolve(tmp_path, binary)
    binary = manual_binary()
    binary["resolution_contract"]["deadline"] = "2025-12-01"
    publish(tmp_path / "retro", binary)
    with pytest.raises(feedback.ForecastFeedbackError, match="invalid_resolution_chronology"):
        resolve(tmp_path / "retro", binary)


def test_future_adjudication_cannot_be_admitted_by_client_clock(tmp_path):
    binary = manual_binary()
    publish(tmp_path, binary)
    with pytest.raises(feedback.ForecastFeedbackError, match="resolution_in_future"):
        resolve(tmp_path, binary, resolved_at="2999-01-01T00:00:00Z")
    assert ledger.read_published_resolutions("r1", tmp_path) == []


def near_binary():
    binary = {"id": "F1", "statement": "Event A occurs", "resolution_criteria": "settles by 2026-02-01",
              "probability": 0.7, "resolution_date": "2026-02-01"}
    binary["market_anchor"] = {"market_id": "m1", "resolution_equivalence": "near",
                               "question": binary["statement"], "description": binary["resolution_criteria"],
                               "endDate": binary["resolution_date"],
                               "forecast_contract_sha256": hashlib.sha256(
                                   (binary["statement"] + "\n" + binary["resolution_criteria"]).encode()).hexdigest()}
    binary["market_anchor"]["market_contract_sha256"] = feedback.market_resolution_contract_sha256(binary["market_anchor"])
    return binary


def near_evidence(binary):
    anchor = binary["market_anchor"]
    return {"report_id": "r1", "forecast_id": "F1", "market_id": "m1", "model_p": 0.7,
            "resolved_outcome": "Yes", "resolved_yes_price": 1.0, "resolved_at": RESOLVED,
            "market_anchor": deepcopy(anchor), "forecast_contract_sha256": anchor["forecast_contract_sha256"],
            "market_contract": {key: anchor[key] for key in ("market_id", "question", "description", "endDate")},
            "market_resolved": True, "market_closed": True}


def reconcile(tmp_path, row):
    return ledger.reconcile_published_resolutions("r1", market_rows=[row], data_rows=[], d=tmp_path)


def test_near_has_separate_score_and_rolls_back_admission_without_erasing_history(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_MARKET_NEAR_RESOLUTION", True, raising=False)
    binary = near_binary()
    publish(tmp_path, binary)
    assert reconcile(tmp_path, near_evidence(binary))["accepted"] == 1
    track = ledger.production_track_record(d=tmp_path)
    assert track["tracks"]["market_binary_near"]["mean_brier"] == 0.09
    assert track["tracks"]["market_binary"]["n_resolved"] == 0
    monkeypatch.setattr(Config, "FORECAST_MARKET_NEAR_RESOLUTION", False)
    assert ledger.verify_production_track_record(track, d=tmp_path)
    assert ledger.read_published_resolutions("r1", tmp_path)[0]["kind"] == "market_binary_near"
    assert reconcile(tmp_path, near_evidence(binary))["rejected"][0]["reason"] == "market_near_resolution_disabled"


@pytest.mark.parametrize("field,value", [("forecast_contract_sha256", "wrong"), ("market_anchor", {}),
                                        ("market_closed", False), ("market_resolved", False),
                                        ("resolved_yes_price", 0.8), ("market_id", "another")])
def test_near_without_complete_exact_contract_and_settlement_proof_cannot_score(tmp_path, monkeypatch, field, value):
    monkeypatch.setattr(Config, "FORECAST_MARKET_NEAR_RESOLUTION", True, raising=False)
    binary = near_binary()
    publish(tmp_path, binary)
    row = near_evidence(binary)
    row[field] = value
    assert reconcile(tmp_path, row)["accepted"] == 0
    assert ledger.read_published_resolutions("r1", tmp_path) == []


def test_near_recomputes_hash_from_frozen_question(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_MARKET_NEAR_RESOLUTION", True, raising=False)
    binary = near_binary()
    binary["statement"] += " with a different settlement term"
    publish(tmp_path, binary)
    assert reconcile(tmp_path, near_evidence(binary))["rejected"][0]["reason"] == "market_contract_mismatch"


def test_near_rejects_retrospective_publication(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_MARKET_NEAR_RESOLUTION", True, raising=False)
    binary = near_binary()
    ledger.record_published_forecast({"binary_forecasts": [binary]}, report_id="r1",
                                     created_at="2026-02-02T00:00:00Z", d=tmp_path)
    assert reconcile(tmp_path, near_evidence(binary))["rejected"][0]["reason"] == "invalid_resolution_chronology"


def test_monitor_producer_to_journal_to_separate_score(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_MARKET_NEAR_RESOLUTION", True, raising=False)
    monkeypatch.setattr(Config, "DATA_SOURCES_ENABLED", False)
    binary = near_binary()
    publish(tmp_path, binary)

    class Client:
        def requote_markets(self, rows):
            return []

        def fetch_resolutions(self, ids):
            return {"m1": {"market_id": "m1", "resolved": True, "closed": True,
                           "resolved_outcome": "Yes", "resolved_yes_price": 1.0}}

        def _fetch_fresh_markets(self, ids):
            return {"m1": {"id": "m1", "closed": True, "outcomes": ["Yes", "No"],
                           "outcomePrices": [1, 0], "question": binary["statement"],
                           "description": binary["resolution_criteria"], "endDate": binary["resolution_date"]}}

    out = monitor.run_monitor("r1", forecast={"binary_forecasts": [binary]},
                              report_folder=str(tmp_path), ledger_dir=tmp_path,
                              client=Client(), as_of=RESOLVED, write_report=False)
    assert out["resolved_count"] == 1 and out["forecast_feedback"]["accepted"] == 1
    assert out["market_brier"]["n_resolved"] == 0
    assert out["market_near_brier"]["mean_brier"] == 0.09
    assert out["resolution_records"][0]["resolution_kind"] == "market_binary_near"
    assert "separate market_binary_near lane" in out["monitor_report_md"]
    assert not (tmp_path / "resolutions.jsonl").exists()


def test_manual_monitor_consumer_removes_adjudicated_question_from_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_SOURCES_ENABLED", False)
    binary = manual_binary()
    publish(tmp_path, binary)
    resolve(tmp_path, binary)
    out = monitor.run_monitor("r1", forecast={"binary_forecasts": [binary]},
                              report_folder=str(tmp_path), ledger_dir=tmp_path,
                              client=object(), as_of=RESOLVED, write_report=False)
    assert out["resolved_count"] == 1 and out["needs_manual_count"] == 0
    assert len(out["manual_resolution_records"]) == 1
    assert "## Manual adjudications" in out["monitor_report_md"]


def test_old_frozen_track_record_near_classification_still_verifies(tmp_path):
    publish(tmp_path, near_binary())
    frozen = ledger.production_track_record(d=tmp_path)
    old = frozen["tracks"].pop("market_binary_near")
    frozen["tracks"]["market_binary"].update(old)
    assert ledger.verify_production_track_record(frozen, d=tmp_path)


@pytest.mark.parametrize("difference", ["question", "description", "endDate", "missing_source_terms", "changed_at_settlement"])
def test_near_proxy_with_matching_forecast_self_hash_cannot_resolve_different_contract(tmp_path, monkeypatch, difference):
    monkeypatch.setattr(Config, "FORECAST_MARKET_NEAR_RESOLUTION", True, raising=False)
    binary = near_binary()
    anchor = binary["market_anchor"]
    if difference in ("question", "description"):
        anchor[difference] = "A different event or threshold"
    elif difference == "endDate":
        anchor["endDate"] = "2026-01-31"
    anchor["market_contract_sha256"] = feedback.market_resolution_contract_sha256(anchor)
    row = near_evidence(binary)
    if difference == "missing_source_terms":
        row.pop("market_contract")
    elif difference == "changed_at_settlement":
        row["market_contract"]["description"] = "Changed provider terms"
    publish(tmp_path, binary)
    assert reconcile(tmp_path, row)["accepted"] == 0
    assert ledger.read_published_resolutions("r1", tmp_path) == []
    assert ledger.list_outstanding_published_questions(as_of=RESOLVED, d=tmp_path)[0]["forecast_id"] == "F1"


@pytest.mark.parametrize("legacy_contract", [{"kind": "manual"}, "unvalidated old annotation"])
def test_pre_extension_v1_journal_replays_without_new_admission_rules(tmp_path, legacy_contract):
    """Frozen v1 wire fixture: old admission preserved auxiliary contracts verbatim."""
    binary = manual_binary(False)
    binary["resolution_contract"] = legacy_contract
    fc = {"binary_forecasts": [binary]}

    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                         separators=(",", ":"), allow_nan=False).encode()).hexdigest()

    publication = {"report_id": "r1", "created_at": CREATED, "forecast": fc,
                   "publication_sha256": digest(fc), "record_class": "production"}
    event = {"schema_version": 1, "type": "publication", "record": publication}
    wire = {"sequence": 1, "previous_sha256": None, "sha256": digest(event), "event": event}
    (tmp_path / feedback._FILE).write_text(json.dumps(wire) + "\n")
    assert ledger.read_published_forecast("r1", d=tmp_path) == publication
    assert publish(tmp_path, binary) == publication  # exact retry remains compatible
    assert ledger.production_track_record(d=tmp_path)["n_reports"] == 1
    assert ledger.list_outstanding_published_questions(as_of=RESOLVED, d=tmp_path)
    ledger.record_published_forecast({"binary_forecasts": [manual_binary()]},
                                     report_id="new", created_at=CREATED, d=tmp_path)
    assert ledger.production_track_record(d=tmp_path)["n_reports"] == 2
    with pytest.raises(feedback.ForecastFeedbackError):
        ledger.record_published_forecast(fc, report_id="new-invalid", created_at=CREATED, d=tmp_path)


def test_unregistered_near_candidate_never_appears_as_committed_resolution(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_MARKET_NEAR_RESOLUTION", True, raising=False)
    monkeypatch.setattr(Config, "DATA_SOURCES_ENABLED", False)
    binary = near_binary()

    class Client:
        def requote_markets(self, rows):
            return []

        def fetch_resolutions(self, ids):
            return {"m1": {"market_id": "m1", "resolved": True, "closed": True,
                           "resolved_outcome": "Yes", "resolved_yes_price": 1.0}}

        def _fetch_fresh_markets(self, ids):
            return {"m1": {"id": "m1", "closed": True, "outcomes": ["Yes", "No"],
                           "outcomePrices": [1, 0], "question": binary["statement"],
                           "description": binary["resolution_criteria"], "endDate": binary["resolution_date"]}}

    out = monitor.run_monitor("r1", forecast={"binary_forecasts": [binary]},
                              report_folder=str(tmp_path), ledger_dir=tmp_path,
                              client=Client(), as_of=RESOLVED, write_report=False)
    assert out["resolved_count"] == 0 and out["resolution_records"] == []
    assert out["needs_manual_count"] == 1
    assert len(out["candidate_resolution_records"]) == 1
    assert ledger.read_published_resolutions("r1", tmp_path) == []
    assert not (tmp_path / "resolutions.jsonl").exists()


def test_sdk_route_reaches_journal_and_maps_validation_errors(tmp_path, monkeypatch):
    from flask import Flask
    from app.api.sdk import sdk_bp

    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(tmp_path))
    binary = manual_binary()
    publish(tmp_path, binary)
    app = Flask(__name__)
    app.register_blueprint(sdk_bp, url_prefix="/api/v1")
    client = app.test_client()
    payload = {"forecast_id": "F1", "outcome": True, "evidence": evidence(),
               "contract_sha256": "wrong", "resolved_at": RESOLVED}
    assert client.post("/api/v1/resolve-binary/r1", json=payload).status_code == 422
    assert ledger.read_published_resolutions("r1", tmp_path) == []
    payload["contract_sha256"] = feedback.binary_resolution_contract_sha256(binary)
    response = client.post("/api/v1/resolve-binary/r1", json=payload)
    assert response.status_code == 200
    assert response.get_json()["data"]["score"]["brier"] == 0.09
    assert ledger.read_published_resolutions("r1", tmp_path)[0]["kind"] == "named_source_event"
    payload["outcome"] = False
    assert client.post("/api/v1/resolve-binary/r1", json=payload).status_code == 409
    assert client.post("/api/v1/resolve-binary/missing", json=payload).status_code == 404


@pytest.mark.parametrize("contract,lane", [
    ({"kind": "official_data", "series": "fred:UNRATE", "comparator": ">", "threshold": 4,
      "period": "2026-01", "units": "Percent"}, "official_data_binary"),
    ({"kind": "polymarket", "market_id": "m1", "equivalence": "exact"}, "market_binary"),
])
def test_typed_contract_without_validated_anchor_is_visible_and_cannot_resolve(tmp_path, contract, lane):
    binary = manual_binary(False)
    binary["resolution_contract"] = contract
    publish(tmp_path, binary)
    pending = ledger.list_outstanding_published_questions(as_of=RESOLVED, d=tmp_path)
    assert pending[0]["kind"] == lane
    assert pending[0]["resolution_status"] == "missing_validated_anchor"
    row = {"report_id": "r1", "forecast_id": "F1", "model_p": 0.7,
           "resolved_at": RESOLVED, "resolved_outcome": True}
    kwargs = {"market_rows": [row] if lane == "market_binary" else [],
              "data_rows": [row] if lane == "official_data_binary" else []}
    result = ledger.reconcile_published_resolutions("r1", **kwargs, d=tmp_path)
    assert result["rejected"][0]["reason"] == "missing_validated_anchor"
    tracks = ledger.production_track_record(d=tmp_path)["tracks"]
    assert tracks[lane]["n_forecasts"] == 1 and tracks[lane]["n_resolved"] == 0
    assert tracks["unanchored_binary"]["n_forecasts"] == 0
    old = ledger.production_track_record(d=tmp_path)
    old["tracks"]["unanchored_binary"].update(old["tracks"][lane])
    old["tracks"][lane].update(n_forecasts=0, n_outstanding=0)
    assert ledger.verify_production_track_record(old, d=tmp_path)


def test_typed_market_producer_anchor_reaches_real_journal_and_score(tmp_path):
    from pathlib import Path
    from app.services.forecast_extractor import derive_binaries_from_tree

    case = json.loads((Path(__file__).parent / "fixtures/target_case.json").read_text())
    candidate = case["binaries"][0]
    candidate["resolution_contract"] = {"kind": "polymarket", "market_id": "M1", "equivalence": "exact"}
    snapshot = {"market_id": "M1", "implied_yes_prob": 0.73, "question": candidate["question"],
                "url": "https://example.test/market", "endDate": "2027-12-31"}
    produced = derive_binaries_from_tree(case, markets=[snapshot])["binary_forecasts"][0]
    publish(tmp_path, produced)
    proof = {"report_id": "r1", "forecast_id": produced["id"], "model_p": produced["probability"],
             "market_id": "M1", "market_anchor": produced["market_anchor"],
             "resolved_at": "2028-01-02T00:00:00Z", "resolved_outcome": "Yes", "resolved_yes_price": 1.0}
    assert reconcile(tmp_path, proof)["accepted"] == 1
    assert ledger.production_track_record(d=tmp_path)["tracks"]["market_binary"]["mean_brier"] == 0.16
    assert ledger.read_published_resolutions("r1", tmp_path)[0]["forecast_id"] == candidate["binaryId"]
