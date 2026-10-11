"""Controlled consumers of official snapshots and verified data outcomes."""
from types import SimpleNamespace
from copy import deepcopy

import pytest

from app.config import Config
from app.services import official_data
from app.services import forecast_ledger
import scripts.resolution_monitor as monitor


@pytest.mark.parametrize("as_of", ["2026-03-01", "2026-03-01T00:00:00+00:00"])
def test_monitor_adopts_official_outcome_and_records_it_once(tmp_path, monkeypatch, as_of):
    monkeypatch.setattr(Config, "DATA_SOURCES_ENABLED", True)
    series = {"series": "fred:UNRATE", "units": "Percent", "frequency": "M",
              "source_url": "https://fred.stlouisfed.org/series/UNRATE",
              "retrieved_at": "2026-03-01T00:00:00Z",
              "observations": [{"date": "2026-01-01", "value": 4.2, "flag": ""}]}
    calls = []
    client = SimpleNamespace(get=lambda sid, **kw: calls.append((sid, kw)) or series)
    monkeypatch.setattr(official_data, "get_data_sources", lambda: client)
    forecast = {"binary_forecasts": [{
        "id": "F1", "statement": "Unemployment exceeds four percent in January",
        "probability": 0.7, "resolution_criteria": "January observation, reviewed by 2026-03-01",
        "data_anchor": {"series": "fred:UNRATE", "comparator": ">", "threshold": 4,
                        "observation": "2026-01", "transform": "", "units": "Percent"},
    }]}
    kwargs = {"forecast": forecast, "report_folder": str(tmp_path / "report"),
              "client": SimpleNamespace(), "ledger_dir": str(tmp_path / "ledger"),
              "as_of": as_of, "write_report": False}

    first = monitor.run_monitor("report_local", **kwargs)
    # A later provider revision cannot rewrite the already recorded outcome.
    series["observations"][0]["value"] = 3.8
    second = monitor.run_monitor("report_local", **kwargs)

    assert first["resolved_count"] == 1
    assert first["newly_recorded_count"] == 1
    assert second["newly_recorded_count"] == 0
    assert second["data_resolution_records"][0]["resolved_outcome"] is True
    assert second["data_resolution_records"][0]["brier_contribution"] == 0.09
    assert first["needs_manual"] == []
    assert calls[0] == ("fred:UNRATE", {"start": "2026-01-01", "end": "2026-01-31",
                                       "transform": "", "max_obs": 240})
    records = forecast_ledger.read_data_resolutions(str(tmp_path / "ledger"))
    assert len(records) == 1
    assert records[0]["brier_contribution"] == 0.09
    assert records[0]["observation"]["value"] == 4.2
    assert forecast_ledger.read_market_resolutions(str(tmp_path / "ledger")) == []


def test_historical_snapshot_keeps_gaps_and_excludes_projections(monkeypatch):
    monkeypatch.setattr(official_data, "format_value", lambda value, units: f"{value:g}%")
    rows = [{"series": "fred:UNRATE", "title": "Unemployment", "units": "Percent",
             "source_id": "S3", "source_url": "https://fred.stlouisfed.org/series/UNRATE",
             "retrieved_at": "2026-09-01", "projection_from": "2027-01-01",
             "observations": [{"date": "2026-06-01", "value": 4.2},
                              {"date": "2026-07-01", "value": None},
                              {"date": "2027-01-01", "value": 9.9, "flag": "projection"}]}]
    text = official_data.historical_snapshot({"series": rows}, as_of="2026-09-30")
    assert "4.2%" in text and "2026-06-01" in text and "[S3]" in text
    assert "9.9" not in text and "2026-07-01" not in text
    assert official_data.historical_snapshot({"series": rows}, as_of="2025-12-31") == ""


def test_historical_snapshot_does_not_infer_weo_history(monkeypatch):
    monkeypatch.setattr(official_data, "format_value", lambda value, units: str(value))
    row = {"series": "wb:IMF_WEO_NGDP_RPCH/USA", "units": "Percent",
           "observations": [{"date": "2025-01-01", "value": 2.1}]}
    assert official_data.historical_snapshot({"series": [row]}, as_of="2026-09-30") == ""


@pytest.mark.parametrize("flag", ["P", "estimate", "estimated", "forecast; provisional", "unknown"])
def test_historical_snapshot_refuses_ambiguous_flags(flag, monkeypatch):
    monkeypatch.setattr(official_data, "format_value", lambda value, units: str(value))
    row = {"series": "fred:UNRATE", "units": "Percent", "retrieved_at": "2026-01-31",
           "observations": [{"date": "2026-01-01", "value": 4.2, "flag": flag}]}
    assert official_data.historical_snapshot({"series": [row]}, as_of="2026-02-01") == ""


@pytest.mark.parametrize("retrieved", ["", "not a date", "2026-03-01"])
def test_historical_snapshot_requires_availability_evidence(retrieved, monkeypatch):
    monkeypatch.setattr(official_data, "format_value", lambda value, units: str(value))
    row = {"series": "fred:UNRATE", "units": "Percent", "retrieved_at": retrieved,
           "observations": [{"date": "2026-01-01", "value": 4.2}]}
    assert official_data.historical_snapshot({"series": [row]}, as_of="2026-02-01") == ""


@pytest.mark.parametrize("flag, expected", [("projection", "manual"), ("unknown", "manual"), ("", "pending")])
def test_unpublished_or_ambiguous_observation_does_not_resolve(tmp_path, monkeypatch, flag, expected):
    monkeypatch.setattr(Config, "DATA_SOURCES_ENABLED", True)
    row = {"series": "fred:UNRATE", "units": "Percent", "frequency": "M",
           "source_url": "https://fred.stlouisfed.org/series/UNRATE",
           "observations": [{"date": "2026-01-01", "value": 9 if flag else None, "flag": flag}]}
    binary = {"id": "F1", "probability": 0.7, "resolution_criteria": "by 2026-03-01",
              "data_anchor": {"series": "fred:UNRATE", "units": "Percent", "threshold": 4,
                              "comparator": ">", "observation": "2026-01", "transform": ""}}
    result = monitor.run_monitor("report_local", forecast={"binary_forecasts": [binary]},
                                 report_folder=str(tmp_path / "report"), ledger_dir=str(tmp_path / "ledger"),
                                 client=SimpleNamespace(), data_client=SimpleNamespace(get=lambda *a, **kw: row),
                                 as_of="2026-03-01", write_report=False)
    assert result["resolved_count"] == 0
    assert result["data_resolution_status"][0]["status"] == expected
    assert forecast_ledger.read_data_resolutions(str(tmp_path / "ledger")) == []


def test_data_dry_run_never_constructs_a_client_or_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_SOURCES_ENABLED", True)
    monkeypatch.setattr(official_data, "get_data_sources", lambda: pytest.fail("dry-run started a data client"))
    binary = {"id": "F1", "probability": 0.7,
              "data_anchor": {"series": "fred:UNRATE", "observation": "2026-01"}}
    result = monitor.run_monitor("report_local", forecast={"binary_forecasts": [binary]},
                                 report_folder=str(tmp_path / "report"), ledger_dir=str(tmp_path / "ledger"),
                                 client=SimpleNamespace(), as_of="2026-03-01", dry_run=True)
    assert result["data_resolution_status"][0]["attempted"] is False
    assert list(tmp_path.iterdir()) == []


def test_public_snapshot_does_not_bypass_canonical_actor_authority(monkeypatch):
    from app.services.simulation_config_generator import SimulationConfigGenerator
    gen = object.__new__(SimulationConfigGenerator)
    monkeypatch.setattr(Config, "SIM_WORLD_BRIEF", True)
    monkeypatch.setattr(gen, "_world_brief_max_chars", lambda: 3500)
    monkeypatch.setattr(gen, "_english_output", lambda: True)
    monkeypatch.setattr(gen, "_dossier_uses_canonical_intelligence", lambda actors: True)
    monkeypatch.setattr(gen, "_build_canonical_public_world_brief", lambda *a, **kw: "Admitted pack only")
    monkeypatch.setattr(official_data, "historical_snapshot", lambda *a, **kw: pytest.fail("v1 authority bypass"))
    assert gen._build_world_brief("Question", {}, [], official_data={"series": ["unbound"]}) == "Admitted pack only"


def test_unversioned_world_brief_consumes_stored_historical_snapshot(monkeypatch):
    from app.services.simulation_config_generator import SimulationConfigGenerator
    gen = object.__new__(SimulationConfigGenerator)
    monkeypatch.setattr(Config, "SIM_WORLD_BRIEF", True)
    monkeypatch.setattr(gen, "_world_brief_max_chars", lambda: 3500)
    monkeypatch.setattr(gen, "_english_output", lambda: True)
    monkeypatch.setattr(gen, "_market_priors_enabled", lambda: False)
    data = {"series": [{"series": "fred:UNRATE", "units": "Percent", "title": "Unemployment",
                        "source_id": "S3", "source_url": "https://fred.stlouisfed.org/series/UNRATE",
                        "retrieved_at": "2026-01-31",
                        "observations": [{"date": "2026-01-01", "value": 4.2}]}]}
    brief = gen._build_world_brief("Question", {"as_of_date": "2026-02-01"}, [], official_data=data)
    assert "4.2%" in brief and "[S3]" in brief
    assert "BEGIN UNTRUSTED" in brief


def test_ledger_normalizes_persisted_identity_before_deduplication(tmp_path):
    record = {"report_id": " report_spaced ", "forecast_id": " F1 ", "series": " fred:UNRATE ",
              "resolved_outcome": True, "model_p": 0.7,
              "observation": {"date": "2026-01-01", "value": 4.2}, "resolved_at": "2026-03-01"}
    first = forecast_ledger.append_data_resolution(record, d=str(tmp_path))
    second = forecast_ledger.append_data_resolution(record, d=str(tmp_path))
    assert first["report_id"] == "report_spaced"
    assert second is None
    assert len(forecast_ledger.read_data_resolutions(str(tmp_path))) == 1


@pytest.fixture
def resolution_case(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "DATA_SOURCES_ENABLED", True)
    series = {"series": "fred:UNRATE", "units": "Percent", "frequency": "M",
              "retrieved_at": "2026-03-01T00:00:00Z",
              "source_url": "https://fred.stlouisfed.org/series/UNRATE",
              "observations": [{"date": "2026-01-01", "value": 4.2, "flag": ""}]}
    binary = {"id": "F1", "probability": 0.7, "resolution_criteria": "review by 2026-02-28",
              "data_anchor": {"series": "fred:UNRATE", "comparator": ">", "threshold": 4,
                              "units": "Percent", "observation": "2026-01"}}
    calls = []
    kwargs = {"forecast": {"binary_forecasts": [binary]}, "client": SimpleNamespace(),
              "data_client": SimpleNamespace(get=lambda *a, **kw: calls.append((a, kw)) or deepcopy(series)),
              "report_folder": str(tmp_path / "report"), "ledger_dir": str(tmp_path / "ledger"),
              "as_of": "2026-03-01T19:00:00Z", "write_report": False}
    return series, binary, kwargs, calls


def test_monitor_preserves_exact_availability_cutoff(resolution_case):
    series, _, kwargs, _ = resolution_case
    series["retrieved_at"] = "2026-03-01T18:00:00Z"
    kwargs["as_of"] = "2026-03-01T01:00:00Z"
    result = monitor.run_monitor("report_local", **kwargs)
    assert result["resolved_count"] == 0
    assert result["data_resolution_status"][0]["status"] == "manual"
    assert forecast_ledger.read_data_resolutions(kwargs["ledger_dir"]) == []
    # An offset-equivalent cutoff and date-only end of day are valid controls.
    kwargs["as_of"] = "2026-03-02T02:00:00+08:00"
    assert monitor.run_monitor("report_local", **kwargs)["resolved_count"] == 1


def test_recorded_outcome_does_not_replay_before_exact_recording_time(resolution_case):
    _, _, kwargs, calls = resolution_case
    assert monitor.run_monitor("report_local", **kwargs)["resolved_count"] == 1
    kwargs["as_of"] = "2026-03-01T01:00:00Z"
    result = monitor.run_monitor("report_local", **kwargs)
    assert result["resolved_count"] == 0
    assert result["data_resolution_status"][0]["status"] == "pending"
    assert len(calls) == 1


def test_monitor_normalizes_forecast_ids_before_fetch_and_replay(resolution_case):
    _, binary, kwargs, calls = resolution_case
    binary["id"] = " F1 "
    for _ in range(2):
        result = monitor.run_monitor("report_local", **kwargs)
        assert result["resolved_count"] == 1
        assert [r["forecast_id"] for r in result["data_resolution_records"]] == ["F1"]
        assert len(result["data_resolution_status"]) == 1
        assert result["needs_manual"] == []
    assert len(calls) == 1
    assert len(forecast_ledger.read_data_resolutions(kwargs["ledger_dir"])) == 1


@pytest.mark.parametrize("change", ["period_changed", "conflicting_alias", "equivalent_alias"])
def test_recorded_contract_binds_canonical_period(resolution_case, change):
    _, binary, kwargs, calls = resolution_case
    anchor = binary["data_anchor"]
    if change != "conflicting_alias":
        anchor["period"] = anchor.pop("observation")
    assert monitor.run_monitor("report_local", **kwargs)["resolved_count"] == 1
    if change == "conflicting_alias":
        anchor["observation"] = "2026-01"
        anchor["period"] = "2026-02"
    elif change == "period_changed":
        anchor["period"] = "2026-02"
    else:
        anchor["observation"] = anchor.pop("period")
    result = monitor.run_monitor("report_local", **kwargs)
    assert result["resolved_count"] == (1 if change == "equivalent_alias" else 0)
    assert result["data_resolution_status"][0]["status"] == ("resolved" if change == "equivalent_alias" else "manual")
    assert len(calls) == 1


@pytest.mark.parametrize("winner_kind", ["same", "different_threshold", "later_cutoff"])
def test_monitor_revalidates_competing_ledger_winner(resolution_case, monkeypatch, winner_kind):
    _, _, kwargs, _ = resolution_case
    append = forecast_ledger.append_data_resolution

    def competing_append(record, *, d):
        winner = deepcopy(record)
        if winner_kind == "different_threshold":
            winner["data_anchor"]["threshold"] = 5
            winner["resolved_outcome"] = False
        elif winner_kind == "later_cutoff":
            winner["resolved_at"] = "2026-03-01T23:00:00Z"
        assert append(winner, d=d) is not None
        return None

    monkeypatch.setattr(forecast_ledger, "append_data_resolution", competing_append)
    result = monitor.run_monitor("report_local", **kwargs)
    assert result["newly_recorded_count"] == 0
    assert result["resolved_count"] == (1 if winner_kind == "same" else 0)
    expected = {"same": "resolved", "different_threshold": "manual", "later_cutoff": "pending"}[winner_kind]
    assert result["data_resolution_status"][0]["status"] == expected
    if winner_kind == "different_threshold":
        assert result["needs_manual_count"] == 1
        assert result["degraded"] is True
    assert len(forecast_ledger.read_data_resolutions(kwargs["ledger_dir"])) == 1


def test_historical_snapshot_preserves_intraday_cutoff(resolution_case):
    series, _, _, _ = resolution_case
    series["retrieved_at"] = "2026-03-01T18:00:00Z"
    assert official_data.historical_snapshot({"series": [series]}, as_of="2026-03-01T01:00:00Z") == ""
    assert "4.2" in official_data.historical_snapshot({"series": [series]}, as_of="2026-03-01")


@pytest.mark.parametrize("explicit_cutoff", [False, True])
def test_current_monitor_evaluates_after_fresh_fetch_but_historical_cutoff_stays_fixed(
    resolution_case, monkeypatch, explicit_cutoff,
):
    series, _, kwargs, calls = resolution_case
    now = ["2026-03-01T00:00:00Z"]
    monkeypatch.setattr(monitor, "_utcnow_iso", lambda: now[0])

    def fetch(*args, **kw):
        calls.append((args, kw))
        now[0] = "2026-03-01T00:00:01Z"
        series["retrieved_at"] = now[0]
        return deepcopy(series)

    kwargs["data_client"] = SimpleNamespace(get=fetch)
    kwargs["as_of"] = now[0] if explicit_cutoff else None
    result = monitor.run_monitor("report_local", **kwargs)
    assert len(calls) == 1
    assert result["resolved_count"] == (0 if explicit_cutoff else 1)
    records = forecast_ledger.read_data_resolutions(kwargs["ledger_dir"])
    if explicit_cutoff:
        assert records == []
        assert result["data_resolution_status"][0]["status"] == "manual"
    else:
        assert records[0]["resolved_at"] == "2026-03-01T00:00:01Z"
        assert records[0]["resolved_outcome"] is True


@pytest.mark.parametrize("identity,provenance", [
    ("wb:WB_WDI_NY_GDP_MKTP_CD/USA", {}),
    ("fred:UNRATE", {"resolution_safe": False}),
    ("fred:UNRATE", []),
])
def test_historical_snapshot_honors_current_fidelity_and_malformed_provenance(identity, provenance):
    row = {"series": identity, "units": "Percent", "frequency": "A",
           "retrieved_at": "2026-03-01", "provenance": provenance,
           "observations": [{"date": "2025-01-01", "value": 4.2, "flag": ""}]}
    assert official_data.historical_snapshot({"series": [row]}, as_of="2026-03-02") == ""
