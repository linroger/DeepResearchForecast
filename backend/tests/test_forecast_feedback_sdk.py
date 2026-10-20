"""SDK adjudication against real audited reports and the durable typed ledger.

The forecast and prose are synthetic inputs. Publication audits, report saving,
SDK requests, ledger persistence and scoring are real; no provider is called.
The child entrypoint exercises retry after an actual interpreter restart under
the unchanged main_offline_pytest.py guard.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from app.config import Config
from app.services import forecast_ledger
from app.services.report_agent import Report, ReportAgent, ReportManager, ReportStatus


class NoExternalCalls:
    def __getattr__(self, name):
        raise AssertionError(f"Unexpected external call: {name}")


def _client():
    from app import create_app

    application = create_app()
    application.config["TESTING"] = True
    return application.test_client()


@pytest.fixture
def non_utc_clock(monkeypatch):
    try:
        with monkeypatch.context() as clock:
            clock.setenv("TZ", "Asia/Shanghai")
            time.tzset()
            yield
    finally:
        time.tzset()


@pytest.fixture
def published(tmp_path, monkeypatch, request):
    naive_local_time = getattr(request, "param", None) == "naive-local-time"
    if naive_local_time:
        request.getfixturevalue("non_utc_clock")
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path / "simulations"))
    monkeypatch.setattr(Config, "API_V1_ENABLED", True)
    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", True)
    monkeypatch.setattr(Config, "REPORT_STRUCTURED_FORECAST", True)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True)
    monkeypatch.setattr(Config, "REPORT_CITATION_FINALIZER", True)
    monkeypatch.setenv("REPORT_OUTPUT_LANGUAGE", "English")
    report = Report(
        report_id="report_feedback_sdk",
        simulation_id="sim_feedback_sdk",
        graph_id="graph_feedback_sdk",
        simulation_requirement="Forecast the committee decision.",
        status=ReportStatus.COMPLETED,
        markdown_content=(
            "# Committee outlook\n\n## Decision\n\n"
            "The committee could approve the proposal. Other outcomes remain possible.\n"
        ),
        created_at="2026-01-01T00:00:00Z",
        completed_at=(
            "2026-01-01T08:01:00" if naive_local_time else "2026-01-01T00:01:00Z"
        ),
    )
    forecast = {
        "headline": "Committee decision",
        "horizon": "2026-12-31",
        "scenarios": [
            {
                "name": "Base case",
                "probability": 0.7,
                "resolution_criteria": "The committee approves the proposal by the deadline.",
            },
            {
                "name": "Other",
                "probability": 0.3,
                "resolution_criteria": "All other committee outcomes at the deadline.",
            },
        ],
        "binary_forecasts": [{
            "id": "F1",
            "statement": "The committee approves the proposal by the deadline.",
            "probability": 0.7,
            "resolution_criteria": "The committee records approval by the deadline.",
        }],
    }
    # These are actual publication operations, not a fabricated passing audit.
    # save_report must admit the original only after the real audit seals it.
    ReportManager.save_report(report)
    folder = Path(ReportManager._get_report_folder(report.report_id))
    (folder / "forecast.json").write_text(json.dumps(forecast), encoding="utf-8")
    agent = ReportAgent(
        report.graph_id, report.simulation_id, report.simulation_requirement,
        llm_client=NoExternalCalls(), zep_tools=NoExternalCalls(),
    )
    agent._stabilize_publish_markdown(report.report_id, report)
    audit = agent._enforce_final_publish_audit(report.report_id, report)
    assert audit["hard_passed"], audit
    ReportManager.save_report(report)
    assert ReportManager.publication_status(report.report_id)["publishable"]
    snapshot = forecast_ledger.read_published_forecast(report.report_id)
    assert snapshot is not None, "Real report publication must retain the original forecast"
    return {
        "client": _client(), "report": report, "folder": folder,
        "snapshot": snapshot, "ledger": Path(Config.FORECAST_LEDGER_DIR),
    }


def _resolve(published, payload):
    return published["client"].post(
        f"/api/v1/resolve/{published['report'].report_id}", json=payload,
    )


def _journal(published):
    return (published["ledger"] / "published_forecasts.jsonl").read_bytes()


def _mirror(published):
    return json.loads((published["folder"] / "resolved.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("payload", [
    {"outcome": "Base case"},
    {"outcomes": "Base case"},
    {"outcomes": ["Base case"]},
    {"outcome": None, "outcomes": ["Base case"]},
    {"outcome": "Base case", "outcomes": ["Base case"]},
])
def test_legacy_request_shapes_score_original_and_enter_scenario_track(published, payload):
    response = _resolve(published, payload)
    assert response.status_code == 200, response.get_json()
    body = response.get_json()["data"]
    assert body["outcome"] == "Base case"
    assert body["scoring"]["brier"] == pytest.approx(0.18)
    assert body["scoring"]["realized_probability"] == 0.7
    assert body["scoring"]["outcome_matched_a_scenario"] is True
    tracks = forecast_ledger.production_track_record()["tracks"]
    assert tracks["scenario"]["n_resolved"] == 1
    assert tracks["scenario"]["mean_brier"] == pytest.approx(0.18)
    assert tracks["unanchored_binary"]["n_resolved"] == 0
    assert tracks["market_binary"]["n_resolved"] == 0
    assert tracks["official_data_binary"]["n_resolved"] == 0
    mirror = _mirror(published)
    assert mirror["forecast"] == published["snapshot"]["forecast"]
    assert mirror["publication_sha256"] == published["snapshot"]["publication_sha256"]
    assert mirror["evidence"] == {
        "adjudication": "manual_user", "externally_verified": False,
    }
    excluded = forecast_ledger.production_track_record(
        exclude_report_id=published["report"].report_id,
    )
    assert excluded["n_reports"] == 0
    assert excluded["tracks"]["scenario"]["n_resolved"] == 0


@pytest.mark.parametrize("payload", [
    {},
    {"outcome": ""},
    {"outcome": True},
    {"outcome": 0},
    {"outcome": ["Base case"]},
    {"outcome": {"name": "Base case"}},
    {"outcome": "base case"},
    {"outcome": "Base-case"},
    {"outcome": " Base case "},
    {"outcome": "0"},
    {"outcome": "Never forecast"},
    {"outcomes": []},
    {"outcomes": ["Base case", "Other"]},
    {"outcomes": ["Base case", "Base case"]},
    {"outcomes": [True]},
    {"outcomes": [["Base case"]]},
    {"outcomes": None},
    {"outcome": "Base case", "outcomes": "Other"},
    {"outcome": "Base case", "outcomes": []},
    ["Base case"],
])
def test_invalid_or_ambiguous_requests_do_not_write_outcomes(published, payload):
    before = _journal(published)
    response = _resolve(published, payload)
    assert response.status_code == 400, response.get_json()
    assert _journal(published) == before
    assert not (published["folder"] / "resolved.json").exists()
    assert forecast_ledger.production_track_record()["tracks"]["scenario"]["n_resolved"] == 0


def test_same_outcome_preserves_original_evidence_and_conflict_is_409(published):
    first = _resolve(published, {
        "outcome": "Base case",
        "evidence": {"note": "Human reading of the committee minutes.", "verified": True},
        "source": "https://example.invalid/committee/minutes",
    })
    assert first.status_code == 200, first.get_json()
    before = _journal(published)
    original = _mirror(published)
    assert original["evidence"]["source"] == "https://example.invalid/committee/minutes"
    assert original["evidence"]["evidence"]["verified"] is True
    assert original["evidence"]["externally_verified"] is False

    repeated = _resolve(published, {
        "outcome": "Base case", "evidence": "A later claim", "source": "Another source",
    })
    assert repeated.status_code == 200, repeated.get_json()
    assert repeated.get_json() == first.get_json()
    assert _journal(published) == before
    assert _mirror(published) == original
    conflict = _resolve(published, {"outcome": "Other"})
    assert conflict.status_code == 409, conflict.get_json()
    assert _journal(published) == before
    assert _mirror(published) == original


def test_module_reload_preserves_conflict_409_and_idempotent_retry(published):
    from app.services import forecast_feedback

    first = _resolve(published, {"outcome": "Base case", "source": "Original manual record"})
    assert first.status_code == 200, first.get_json()
    journal = _journal(published)
    mirror = _mirror(published)

    # A reload creates a new exception class while forecast_ledger's re-export
    # still refers to the old one. Exercise the real Flask handler in that state.
    original_error_class = forecast_feedback.ForecastFeedbackError
    try:
        importlib.reload(forecast_feedback)
        conflict = _resolve(published, {"outcome": "Other"})
        assert conflict.status_code == 409, conflict.get_json()
        assert "outcome_conflict" in conflict.get_json()["error"]
        assert _journal(published) == journal
        assert _mirror(published) == mirror
        retry = _resolve(published, {"outcome": "Base case", "source": "Later claim"})
        assert retry.status_code == 200, retry.get_json()
        assert retry.get_json() == first.get_json()
        assert _journal(published) == journal
        assert _mirror(published) == mirror
        assert forecast_ledger.production_track_record()["tracks"]["scenario"]["n_resolved"] == 1
    finally:
        # Preserve the pretest class identity for other modules holding imports,
        # including when an assertion fails; do not repair aliases in production.
        forecast_feedback.ForecastFeedbackError = original_error_class
    assert forecast_feedback.ForecastFeedbackError is original_error_class


@pytest.mark.parametrize("published", ["naive-local-time"], indirect=True)
def test_real_registration_converts_legacy_local_timestamp_once(published):
    assert time.strftime("%z") == "+0800"
    registered = datetime.fromisoformat(published["snapshot"]["created_at"])
    assert registered.tzinfo is not None
    assert registered == datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
    before = _journal(published)
    ReportManager.save_report(published["report"])
    assert _journal(published) == before
    assert forecast_ledger.read_published_forecast(
        published["report"].report_id,
    )["created_at"] == published["snapshot"]["created_at"]
    response = _resolve(published, {"outcome": "Base case"})
    assert response.status_code == 200, response.get_json()
    resolved = datetime.fromisoformat(response.get_json()["data"]["resolved_at"])
    assert resolved.utcoffset().total_seconds() == 0
    assert resolved > registered


def test_unregistered_legacy_report_is_not_backfilled(published, tmp_path, monkeypatch):
    # Simulate an audited report from an installation with only the old ledger.
    legacy = tmp_path / "legacy-only-ledger"
    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(legacy))
    metadata_path = Path(ReportManager._get_report_path(published["report"].report_id))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.pop("forecast_feedback_required", None)
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    forecast_ledger.append_forecast(
        published["snapshot"]["forecast"], report_id=published["report"].report_id,
    )
    before = (legacy / "ledger.jsonl").read_bytes()
    response = _resolve(published, {"outcome": "Base case"})
    assert response.status_code == 409, response.get_json()
    assert "regenerate/publish" in response.get_json()["error"]
    assert (legacy / "ledger.jsonl").read_bytes() == before
    assert forecast_ledger.read_published_forecast(published["report"].report_id) is None
    assert not (published["folder"] / "resolved.json").exists()


@pytest.mark.parametrize("artifact", ["forecast.json", "full_report.md", "final_audit.json"])
def test_publication_gate_still_precedes_ledger_resolution(published, artifact):
    path = published["folder"] / artifact
    if artifact == "forecast.json":
        forecast = json.loads(path.read_text(encoding="utf-8"))
        forecast["scenarios"][0]["probability"] = 0.1
        forecast["scenarios"][1]["probability"] = 0.9
        path.write_text(json.dumps(forecast), encoding="utf-8")
    elif artifact == "full_report.md":
        path.write_text("# Changed after publication\n", encoding="utf-8")
    else:
        path.unlink()
    before = _journal(published)
    response = _resolve(published, {"outcome": "Base case"})
    assert response.status_code == 409, response.get_json()
    assert "发布完整性门" in response.get_json()["error"]
    assert _journal(published) == before
    assert not (published["folder"] / "resolved.json").exists()


def test_resolution_never_uses_mutable_forecast_loader(published, monkeypatch):
    from app.api import sdk

    def forbidden_reload(*args, **kwargs):
        raise AssertionError("Resolution must score the retained publication snapshot")

    monkeypatch.setattr(sdk, "_load_forecast", forbidden_reload)
    # Mutating a detached read cannot change the original stored probabilities.
    detached = deepcopy(published["snapshot"])
    detached["forecast"]["scenarios"][0]["probability"] = 0.1
    detached["forecast"]["scenarios"][1]["probability"] = 0.9
    response = _resolve(published, {"outcome": "Base case"})
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["data"]["scoring"]["realized_probability"] == 0.7


@pytest.mark.parametrize("mirror_state", ["missing", "corrupt", "stale"])
def test_same_outcome_repairs_missing_corrupt_or_stale_mirror(published, mirror_state):
    first = _resolve(published, {"outcome": "Base case", "source": "Manual record"})
    assert first.status_code == 200, first.get_json()
    original = _mirror(published)
    before = _journal(published)
    path = published["folder"] / "resolved.json"
    if mirror_state == "missing":
        path.unlink()
    else:
        path.write_text("{" if mirror_state == "corrupt" else '{"outcome":"Other"}')
    retry = _resolve(published, {"outcome": "Base case"})
    assert retry.status_code == 200, retry.get_json()
    assert retry.get_json() == first.get_json()
    assert _mirror(published) == original
    assert _journal(published) == before


def test_failed_ledger_write_does_not_create_report_mirror(published, monkeypatch):
    def failed_persist(*args, **kwargs):
        raise OSError("Synthetic ledger write failure")

    before = _journal(published)
    monkeypatch.setattr(forecast_ledger, "resolve_published_scenario", failed_persist)
    response = _resolve(published, {"outcome": "Base case"})
    assert response.status_code == 500
    assert _journal(published) == before
    assert not (published["folder"] / "resolved.json").exists()


@pytest.mark.guarded_runner
def test_restart_repairs_mirror_after_ledger_committed(published, monkeypatch, tmp_path):
    from app.api import sdk

    def failed_mirror(*args, **kwargs):
        raise OSError("Synthetic report mirror write failure")

    with monkeypatch.context() as failure:
        failure.setattr(sdk, "write_json_atomic", failed_mirror)
        response = _resolve(published, {
            "outcome": "Base case", "source": "Original manual record",
        })
    assert response.status_code == 500
    assert not (published["folder"] / "resolved.json").exists()
    assert forecast_ledger.production_track_record()["tracks"]["scenario"]["n_resolved"] == 1
    journal_after_commit = _journal(published)

    result_path = tmp_path / "restarted-response.json"
    completed = subprocess.run(
        [
            # The registered child adapter supplies -I -S -B itself.
            sys.executable, "-B", str(Path(__file__).resolve()),
            "--repair", str(published["folder"].parent), str(published["ledger"]),
            published["report"].report_id, str(result_path),
        ],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert completed.returncode == 0, completed.stderr[-6000:]
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status_code"] == 200, result
    assert _journal(published) == journal_after_commit
    mirror = _mirror(published)
    assert mirror["evidence"]["source"] == "Original manual record"
    assert mirror["scoring"]["realized_probability"] == 0.7
    assert mirror["forecast"] == published["snapshot"]["forecast"]
    assert result["body"]["data"]["resolved_at"] == mirror["resolved_at"]
    assert forecast_ledger.production_track_record()["tracks"]["scenario"]["n_resolved"] == 1


if __name__ == "__main__":
    assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
    assert sys.argv[1] == "--repair"
    ReportManager.REPORTS_DIR = sys.argv[2]
    Config.FORECAST_LEDGER_DIR = sys.argv[3]
    Config.API_V1_ENABLED = True
    response = _client().post(
        f"/api/v1/resolve/{sys.argv[4]}",
        json={"outcome": "Base case", "source": "Later retry must not replace evidence"},
    )
    Path(sys.argv[5]).write_text(json.dumps({
        "status_code": response.status_code, "body": response.get_json(),
    }), encoding="utf-8")
