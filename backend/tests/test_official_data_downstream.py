"""Controlled consumers of official snapshots and verified data outcomes."""
import json
from types import SimpleNamespace
from copy import deepcopy

import pytest

from app.config import Config
from app.services import official_data
from app.services import forecast_ledger
import scripts.resolution_monitor as monitor
from official_data_replay import REAL, ds, publish, replay, stored_row

UNCLASSIFIED = "Publisher status unclassified"
REAL_ROWS = ("fred_unrate_2024", "fred_dgs10_daily", "fred_dfedtaru_daily_step", "wb_wdi_gdp_growth_usa",
             "wb_imf_weo_ngdp_rpch_chn_default_window", "wb_gep_gdp_growth_chn_default_window",
             "usgov_spending_total_fy", "usgov_debt_to_penny_daily", "bis_ws_cbpol_us_2024")


def _real_carrier(tmp_path, names=REAL_ROWS, extra=()):
    rows = [replay(name, tmp_path) for name in names] + list(extra)
    return official_data.load_official_data(publish(rows, tmp_path / "handoff"))


def _line(text, needle):
    return next(line for line in text.splitlines() if needle in line)


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


def test_canonical_brief_receives_official_data_only_through_its_public_builder(monkeypatch):
    """Canonical v1 routes official data into its own public builder, never the legacy assembly."""
    gen = _world_brief(monkeypatch, canonical=True)
    calls = []
    monkeypatch.setattr(gen, "_build_canonical_public_world_brief",
                        lambda *a, **kw: calls.append(kw) or "Admitted pack only")
    window = {"started_at": "2026-10-11T00:00:00Z"}
    assert gen._build_world_brief("Question", {}, ["raw topic"], official_data={"series": []},
                                  official_window=window) == "Admitted pack only"
    assert calls == [{"english": True, "official_data": {"series": []}, "official_window": window}]


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
    ("fred:UNRATE", {"resolution_safe": False}),
    ("fred:UNRATE", []),
])
def test_historical_snapshot_honors_current_fidelity_and_malformed_provenance(identity, provenance):
    # resolution_safe=False without a stated reason (aggregation, status-stripping feed) stays out.
    row = {"series": identity, "units": "Percent", "frequency": "A",
           "retrieved_at": "2026-03-01", "provenance": provenance,
           "observations": [{"date": "2025-01-01", "value": 4.2, "flag": ""}]}
    assert official_data.historical_snapshot({"series": [row]}, as_of="2026-03-02") == ""


def test_status_stripped_rows_appear_only_as_labelled_unclassified_history():
    """G2: an older-policy Data360 row has no status; it is shown in its own labelled
    block, only for years before the retrieval year, and never as observed history."""
    row = json.loads((REAL / "stored_v2" / "wb_imf_weo_ngdp_rpch_chn.json").read_text())["row"]
    assert {o["flag"] for o in row["observations"]} == {"unknown"}
    stats = {}
    text = official_data.historical_snapshot({"series": [row]}, as_of="2026-10-12", stats=stats)
    head, _, block = text.partition(UNCLASSIFIED)
    assert head == "## Official historical data\n" and block
    line = _line(block, "China")
    assert "| 2025 |" in line and line.endswith("(status not supplied)")
    assert "| 2026 |" not in text  # the retrieval year may hold estimates or projections
    assert stats == {"shown": 1, "excluded": {}}
    # Display visibility never changes resolution eligibility.
    anchor = {"series": row["series"], "comparator": ">", "threshold": 1, "units": row["units"], "observation": "2025"}
    assert official_data.resolve_data_anchor(anchor, row, as_of="2026-10-12")["status"] == "manual"


def test_snapshot_separates_display_safety_from_resolution_safety(tmp_path):
    """P-SNAP/G2/I5 on real provider payloads: aggregated daily months, Data360 WDI and
    WEO history are shown with their qualifiers and trend; partial periods and
    projections never are."""
    carrier = _real_carrier(tmp_path, ("fred_dgs10_daily", "wb_wdi_gdp_growth_usa",
                                       "wb_imf_weo_ngdp_rpch_chn_default_window", "usgov_spending_total_fy",
                                       "fred_unrate_2024", "fred_dfedtaru_daily_step"))
    text = official_data.historical_snapshot(carrier, as_of="2026-10-12", max_chars=6000)
    main, _, unclassified = text.partition(UNCLASSIFIED)
    assert main.splitlines()[1] == "Indicator | Value | Period | YoY change | 5y range | Units | Source"
    dgs10 = _line(main, "10-Year")
    # September is a closed month (mean of daily closes); open October is partial.
    assert "| 4.989% | 2026-09 |" in dgs10
    assert "(monthly mean of daily data; latest daily 2026-10-08: 5.22%)" in dgs10
    assert "5.267" not in text and "2026-10 |" not in text
    target = _line(main, "Federal Funds Target Range")
    assert "| 3.75% | 2025-12 |" in target and "end-of-month value of daily data" in target
    wdi = _line(main, "GDP (annual % growth)")
    assert "| 2.161% | 2025 | -0.632 pp |" in wdi and "status inferred" in wdi
    weo = _line(main, "China")
    # WEO vintage 2026: 2025 is a publisher estimate, 2026+ projections; history ends 2024.
    assert "| 2024 |" in weo and "status inferred" in weo
    assert "| 2025 |" not in weo and "| 2026 |" not in text and "2028" not in text
    unrate = _line(main, "Unemployment Rate")
    assert "| 4.1% | 2024-12 | n/a | 3.7% to 4.2% | Percent | FRED [S5]" in unrate
    spending = _line(unclassified, "USAspending")
    # Completeness follows the recorded capture clock (2026-10-11), never the wall clock:
    # FY2026 ended 11 days before retrieval, so it is still partial (fiscal years settle
    # 120 days after their end) on any day this test runs.
    stored = next(r for r in carrier["series"] if r["series"] == "usgov:spending/total")
    assert stored["retrieved_at"].startswith("2026-10-11T")
    fiscal = stored["provenance"]["periods"]
    assert (fiscal["2024-10-01"]["label"], fiscal["2024-10-01"]["complete"]) == ("FY2025", True)
    assert (fiscal["2025-10-01"]["label"], fiscal["2025-10-01"]["complete"]) == ("FY2026", False)
    assert "| FY2025 |" in spending and spending.endswith("(status not supplied)")
    assert "FY2026" not in text and "FY2027" not in text
    for row in carrier["series"]:
        if row["series"] in ("fred:DGS10", "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA"):
            assert row["provenance"]["resolution_safe"] is False  # still never auto-resolves


def test_snapshot_uses_exact_projection_family_prefixes(tmp_path):
    """Downstream M1: a FRED series whose id merely contains 'GEP' is ordinary history."""
    row = stored_row("fred_gepucurrent_stored")
    carrier = official_data.load_official_data(publish([row], tmp_path / "handoff"))
    text = official_data.historical_snapshot(carrier, as_of="2026-10-12")
    line = _line(text, "Global Economic Policy Uncertainty Index")
    assert "| 241.6905 | 2026-07 |" in line and UNCLASSIFIED not in text


def _stored_rows(relative):
    payload = json.loads((REAL / relative).read_text())
    return payload["row"] if "row" in payload else payload["series"]


# Real rows stored under normalization policy 2 (every aggregated month marked
# incomplete, completeness re-derived on read) and rows replayed under the current one.
_POLICY2_ROWS = [(f"stored_v2/{p.name}", None) for p in sorted((REAL / "stored_v2").glob("*.json"))] + [
    ("v3_engine/series-2026-10-11.json", row["series"])
    for row in _stored_rows("v3_engine/series-2026-10-11.json")]
_POLICY3_ROWS = [("replay", name) for name in REAL_ROWS] + [
    ("v3_engine/series-2026-10-12.json", row["series"])
    for row in _stored_rows("v3_engine/series-2026-10-12.json")]


def _agreement_row(tmp_path, source, key):
    if source == "replay":
        return replay(key, tmp_path).to_dict()
    rows = _stored_rows(source)
    return rows if key is None else next(row for row in rows if row["series"] == key)


def _period_cell(row, day):
    label = ((row.get("provenance") or {}).get("periods") or {}).get(day, {}).get("label")
    if label:
        return label
    if row["frequency"] == "A":
        return day[:4]
    if row["frequency"] == "Q":
        return f"{day[:4]}-Q{(int(day[5:7]) - 1) // 3 + 1}"
    return day[:7] if row["frequency"] == "M" else day


@pytest.mark.parametrize("source, key", _POLICY2_ROWS + _POLICY3_ROWS)
def test_snapshot_pack_charts_and_anchors_share_one_latest_observation(tmp_path, source, key):
    """The world-brief snapshot, the report pack and charts (official_latest_observed) and the
    anchors (data layer latest_observed) name the same newest complete observation for every
    real stored row: policy-2 aggregated months are settled by the shared data-layer rule,
    never by a consumer-local one."""
    from app.services.forecast_extractor import official_latest_observed, official_series_rows

    carrier = official_data.load_official_data(publish([_agreement_row(tmp_path, source, key)],
                                                       tmp_path / "handoff"))
    row = carrier["series"][0]
    as_of = row["retrieved_at"][:10]
    text = official_data.historical_snapshot(carrier, as_of=as_of, max_chars=6000)
    main = text.partition(UNCLASSIFIED)[0].splitlines()[2:]
    pack = official_latest_observed(official_series_rows(carrier)[0])
    anchor = ds.latest_observed(row)

    assert pack == (anchor and {"date": anchor.date, "value": anchor.value})
    series = ds.Series.from_dict(row)
    shown = [o for o in series.observations if o.value is not None and o.date <= as_of
             and ds.observation_kind(o, series) in ("observed", "preliminary")]
    if not shown:
        assert pack is None and main == []
        return
    cells = main[0].split(" | ")
    if ds.observation_kind(shown[-1], series) == "observed":
        assert (shown[-1].date, shown[-1].value) == (pack["date"], pack["value"])
    assert cells[1].split(" (")[0] == official_data.format_value(shown[-1].value, row["units"])
    assert cells[2] == _period_cell(row, shown[-1].date)


def test_snapshot_periods_and_trends_read_at_their_frequency_and_magnitude(tmp_path):
    """Periods read at the series frequency (a month or year is never shown as a single
    day) and derived trend cells read at magnitude; the Value cell keeps the exact
    stored number. Real BIS quarterly, Treasury monthly and daily-stock payloads."""
    carrier = _real_carrier(tmp_path, ("bis_ws_tc_us_770", "usgov_mts_deficit_2024",
                                       "usgov_debt_to_penny_daily", "wb_wdi_gdp_growth_usa"))
    text = official_data.historical_snapshot(carrier, as_of="2026-10-12", max_chars=6000)
    assert "| 142.5% | 2024-Q4 | -4.6 pp | 142.5% to 151.7% |" in _line(text, "Credit to Private")
    deficit = _line(text, "Monthly Treasury Statement")
    assert "| -86731619013.29 (≈ -86.73 billion U.S. dollars) | 2024-12 | n/a |" in deficit
    assert "| ≈ -380.08 billion to ≈ 209.53 billion | U.S. dollars |" in deficit
    debt = _line(text, "Debt to the Penny")
    assert "| 2026-09 |" in debt and "| ≈ 40.17 trillion to ≈ 40.18 trillion |" in debt
    assert "latest daily 2026-10-08: 40305316210829.72 (≈ 40.31 trillion U.S. dollars)" in debt
    assert "| 2.161% | 2025 |" in _line(text, "GDP (annual % growth)")
    assert "-01 |" not in text.replace("FY", "")  # no period cell reads as a single day


def test_snapshot_level_changes_read_relative_to_the_prior_magnitude(monkeypatch):
    """Year-on-year level changes: billions read at magnitude, and the relative change is
    taken against |prior| (as series_stats does), so a widening deficit reads as a fall."""
    row = {"series": "usgov:treasury/mts_deficit", "units": "U.S. dollars", "frequency": "M", "source_id": "S2",
           "source_url": "https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/",
           "retrieved_at": "2026-10-11T22:08:15+00:00",
           "observations": [{"date": "2024-12-01", "value": -50e9}, {"date": "2025-12-01", "value": -86.5e9}]}
    line = official_data.historical_snapshot({"series": [row]}, as_of="2026-10-12").splitlines()[-1]
    assert "| 2025-12 | ≈ -36.5 billion (-73.0%) | ≈ -86.5 billion to ≈ -50 billion |" in line
    row["observations"][0]["value"] = -120e9
    line = official_data.historical_snapshot({"series": [row]}, as_of="2026-10-12").splitlines()[-1]
    assert "| ≈ +33.5 billion (+27.9%) |" in line


_ENGLISH_SNAPSHOT_WORDS = ("Official historical data", "Indicator", "YoY change", "n/a", " to ", " pp",
                           "preliminary", "monthly mean", "end-of-month", "latest daily", "status inferred",
                           "status not supplied", "publisher estimate", "Publisher status", "billion", "trillion")


def test_chinese_snapshot_localizes_its_words_and_keeps_every_figure(tmp_path):
    """Chinese simulation worlds get a Chinese snapshot body (real payloads): headings,
    series names, notes, 'pp' and magnitudes in Chinese; the Value number, Period, published
    Units and the source with its [S#] marker are the English snapshot's, row for row. Any
    language other than Chinese keeps the English text byte for byte."""
    import unicodedata
    carrier = _real_carrier(tmp_path)
    english = official_data.historical_snapshot(carrier, as_of="2026-10-12", max_chars=6000)
    for language in ("en", "English", None, "fr"):
        assert official_data.historical_snapshot(carrier, as_of="2026-10-12", max_chars=6000,
                                                 language=language) == english
    stats_en, stats_zh = {}, {}
    official_data.historical_snapshot(carrier, as_of="2026-10-12", max_chars=6000, stats=stats_en)
    chinese = official_data.historical_snapshot(carrier, as_of="2026-10-12", max_chars=6000, language="zh",
                                                stats=stats_zh)
    assert stats_zh == stats_en and stats_zh["shown"] == 8
    for language in ("Chinese", "中文", "zh-CN"):
        assert official_data.historical_snapshot(carrier, as_of="2026-10-12", max_chars=6000,
                                                 language=language) == chinese
    zh_lines, en_lines = chinese.splitlines(), english.splitlines()
    assert zh_lines[:2] == ["## 官方历史数据", "指标 | 数值 | 期间 | 同比变化 | 五年区间 | 单位 | 来源"]
    assert "发布方未标注状态 (可能含估计值; 并非已确认的历史):" in zh_lines
    assert "指标 | 数值 | 期间 | 单位 | 来源" in zh_lines
    assert not [word for word in _ENGLISH_SNAPSHOT_WORDS if word in chinese]
    assert len(zh_lines) == len(en_lines)
    api = official_data.data_api()
    for zh_line, en_line in zip(zh_lines, en_lines):
        if " [S" not in en_line:
            continue
        zh_cells, en_cells = zh_line.split(" | "), en_line.split(" | ")
        assert len(zh_cells) == len(en_cells)
        assert zh_cells[1].split(" (")[0] == en_cells[1].split(" (")[0]  # the exact stored value
        assert zh_cells[2] == en_cells[2] and zh_cells[-2] == en_cells[-2]  # period and published units
        assert zh_cells[-1].split(" (")[0] == en_cells[-1].split(" (")[0]  # source and [S#]
        row = next(row for row in carrier["series"]
                   if official_data._cell(api.series_label(row), 140) == en_cells[0])
        assert zh_cells[0] == official_data._cell(api.series_label(row, "zh"), 140) != en_cells[0]
    debt = _line(chinese, "美国联邦公共债务总额")
    assert debt.endswith("| 40171825101340.31 (≈40.17万亿美元) | 2026-09 | 无 | ≈40.17万亿 至 ≈40.18万亿 | "
                         "U.S. dollars | U.S. Treasury Fiscal Data [S8] (日度数据的月末值; "
                         "最新日度值 2026-10-08: 40305316210829.72 (≈40.31万亿美元))")
    assert "| 4.989% | 2026-09 | 无 | 4.684% 至 4.989% | Percent | FRED [S2] (日度数据的月均值; " \
           "最新日度值 2026-10-08: 5.22%)" in _line(chinese, "国债收益率")
    assert "| 2.161% | 2025 | -0.632 个百分点 | 2.161% 至 6.152% |" in _line(chinese, "美国GDP")
    assert _line(chinese, "美国GDP").endswith("[S4] (状态为推断: 发布方数据未提供观测状态)")
    assert _line(chinese, "FY2025").endswith("| U.S. dollars | USAspending.gov [S7] (未提供状态)")
    # The fixed vocabulary is NFKC-stable: the world brief's untrusted-data boundary keeps it verbatim.
    assert all(unicodedata.normalize("NFKC", text) == text for text in official_data._SNAPSHOT_TEXT["zh"].values())


def test_chinese_snapshot_signs_level_changes_at_chinese_magnitude():
    row = {"series": "usgov:treasury/mts_deficit", "units": "U.S. dollars", "frequency": "M", "source_id": "S2",
           "source_url": "https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/",
           "retrieved_at": "2026-10-11T22:08:15+00:00",
           "observations": [{"date": "2024-12-01", "value": -50e9}, {"date": "2025-12-01", "value": -86.5e9}]}
    line = official_data.historical_snapshot({"series": [row]}, as_of="2026-10-12", language="zh").splitlines()[-1]
    assert "| -86500000000 (≈-865亿美元) | 2025-12 | ≈-365亿 (-73.0%) | ≈-865亿 至 ≈-500亿 |" in line
    row["observations"][0]["value"] = -120e9
    line = official_data.historical_snapshot({"series": [row]}, as_of="2026-10-12", language="zh").splitlines()[-1]
    assert "| ≈+335亿 (+27.9%) |" in line


@pytest.mark.parametrize("as_of, window, admitted", [
    ("2026-10-11", {"started_at": "2026-10-11T21:00:00Z", "finished_at": "2026-10-12T01:00:00Z"}, True),
    ("2026-10-11", None, True),
    ("2026-10-10", {"started_at": "2026-10-10T23:30:00Z", "finished_at": "2026-10-11T23:00:00Z"}, True),
    ("2026-10-10", None, False),
    ("2026-10-10", {"started_at": "2026-10-10T23:30:00Z"}, False),
    ("2026-10-10", {"started_at": "2026-10-10T23:30:00Z", "finished_at": "2026-10-11T22:00:00Z"}, False),
    ("2026-09-30", {"started_at": "2026-10-10T23:30:00Z", "finished_at": "2026-10-11T23:00:00Z"}, False),
])
def test_live_forecast_cutoff_admits_its_own_research_run(tmp_path, as_of, window, admitted):
    """D5: a run crossing UTC midnight keeps its own captures (retrieved 2026-10-11T22:07Z);
    a historical as_of before the run started stays strict."""
    carrier = _real_carrier(tmp_path, ("fred_unrate_2024",))
    stats = {}
    text = official_data.historical_snapshot(carrier, as_of=as_of, research_window=window, stats=stats)
    assert ("Unemployment Rate" in text) is admitted
    assert stats["excluded"] == ({} if admitted else {"after_cutoff": 1})


def test_research_window_reads_the_run_metadata(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({
        "started_at": "2026-10-10T23:30:00+00:00", "finished_at": "2026-10-11T23:00:00+00:00", "status": "completed"}))
    assert official_data.research_run_window(tmp_path) == {
        "started_at": "2026-10-10T23:30:00+00:00", "finished_at": "2026-10-11T23:00:00+00:00"}
    (tmp_path / "meta.json").write_text(json.dumps({"started_at": "yesterday", "finished_at": "2026-10-11"}))
    assert official_data.research_run_window(tmp_path) is None
    assert official_data.research_run_window(tmp_path / "missing") is None


def _world_brief(monkeypatch, *, canonical=False, max_chars=3500, english=True):
    from app.services.simulation_config_generator import SimulationConfigGenerator
    gen = object.__new__(SimulationConfigGenerator)
    monkeypatch.setattr(Config, "SIM_WORLD_BRIEF", True)
    monkeypatch.setattr(gen, "_world_brief_max_chars", lambda: max_chars)
    monkeypatch.setattr(gen, "_english_output", lambda: english)
    monkeypatch.setattr(gen, "_market_priors_enabled", lambda: False)
    monkeypatch.setattr(gen, "_dossier_uses_canonical_intelligence", lambda actors: canonical)
    return gen


def test_world_brief_never_cuts_the_official_block_delimiter(tmp_path, monkeypatch):
    """D4: the wrapped snapshot is budgeted whole, so BEGIN and END always appear together."""
    carrier = _real_carrier(tmp_path)
    begin = "BEGIN UNTRUSTED RESEARCH DATA — official public historical statistics"
    end = "END UNTRUSTED RESEARCH DATA — official public historical statistics"
    with_snapshot = 0
    for budget in range(500, 3001, 50):
        gen = _world_brief(monkeypatch, max_chars=budget)
        for length in range(40, 401, 60):
            brief = gen._build_world_brief("Will policy rates fall? " + "x" * length,
                                           {"as_of_date": "2026-10-12"}, [], official_data=carrier)
            assert len(brief) <= budget
            assert brief.count(begin) == brief.count(end)
            if begin in brief:
                with_snapshot += 1
                assert brief.endswith(end)
    assert with_snapshot > 100


def test_unversioned_world_brief_is_unchanged_without_official_data(monkeypatch):
    gen = _world_brief(monkeypatch)
    brief = gen._build_world_brief("Question", {"as_of_date": "2026-10-12"}, ["rates"])
    assert brief == "## Forecast question (what this world is debating)\nQuestion\n\n## Hot topics\nrates"
    assert gen._build_world_brief("Question", {}, ["rates"], official_data=None, official_window=None) == brief


def test_canonical_world_brief_carries_the_bound_official_block(tmp_path, monkeypatch):
    """G1: canonical v1 shares the binding-verified statistics as their own delimited
    block, even without public actor rows; actor packs are not consulted for it."""
    carrier = _real_carrier(tmp_path, ("fred_unrate_2024",))
    gen = _world_brief(monkeypatch, canonical=True)
    brief = gen._build_world_brief("Question", {"as_of_date": "2026-10-12"}, ["private hot topic"],
                                   actor_context_packs={}, official_data=carrier)
    assert brief.startswith("## Forecast question (what this world is debating)\nQuestion\n\n## Official statistics "
                            "(published before this world's start date: quote the exact values and periods; "
                            "observed history, not forecasts)\nBEGIN UNTRUSTED")
    assert "Unemployment Rate — United States | 4.1% | 2024-12 |" in brief and "[S1]" in brief
    assert "private hot topic" not in brief
    assert brief.endswith("END UNTRUSTED RESEARCH DATA — official public historical statistics")
    # Without official data the canonical brief keeps its exact fail-closed result.
    assert gen._build_world_brief("Question", {"as_of_date": "2026-10-12"}, [], actor_context_packs={}) == ""


@pytest.mark.parametrize("canonical", [False, True])
def test_chinese_world_brief_carries_a_chinese_snapshot_body(tmp_path, monkeypatch, canonical):
    """A Chinese world's official block reads in Chinese under its Chinese header; the
    English world's block is the English snapshot (unchanged)."""
    from app.services.simulation_config_generator import SimulationConfigGenerator
    carrier = _real_carrier(tmp_path, ("fred_unrate_2024", "wb_wdi_gdp_growth_usa"))
    question = "美国失业率会在2027年前升破5%吗？"
    briefs = {}
    for english in (True, False):
        gen = _world_brief(monkeypatch, canonical=canonical, english=english)
        briefs[english] = gen._build_world_brief(question, {"as_of_date": "2026-10-12"}, ["失业"],
                                                 actor_context_packs={}, official_data=carrier)
        header = SimulationConfigGenerator.OFFICIAL_SNAPSHOT_HEADER[english]
        assert header + "\nBEGIN UNTRUSTED RESEARCH DATA — official public historical statistics" in briefs[english]
        assert briefs[english].endswith("END UNTRUSTED RESEARCH DATA — official public historical statistics")
    english_body = official_data.historical_snapshot(carrier, as_of="2026-10-12", max_chars=3000)
    assert english_body in briefs[True]
    chinese = briefs[False].split("BEGIN UNTRUSTED")[1]
    assert "## 官方历史数据\n指标 | 数值 | 期间 | 同比变化 | 五年区间 | 单位 | 来源\n" in chinese
    assert "\n美国失业率 | 4.1% | 2024-12 | 无 | 3.7% 至 4.2% | Percent | FRED [S1]\n" in chinese
    assert "| 2.161% | 2025 | -0.632 个百分点 |" in chinese and "[S2] (状态为推断: 发布方数据未提供观测状态)" in chinese
    assert not [word for word in _ENGLISH_SNAPSHOT_WORDS if word in chinese]


def test_chinese_situation_brief_is_cut_at_a_character_not_back_to_its_first_space(tmp_path, monkeypatch):
    """Chinese prose has spaces only around numbers and Latin words: a cut back to the last
    space turned a paragraph into '截至 2026 年 9…' (12 characters of 60+ of room). Chinese is
    cut at the character; a Latin word is still never cut in the middle."""
    from app.services.simulation_config_generator import SimulationConfigGenerator
    carrier = _real_carrier(tmp_path)
    sentence = "美联储在九月议息会议上降息并暗示年内仍有进一步宽松空间，市场对此反应分化，债券收益率曲线趋于陡峭。"
    paragraph = "截至 2026 年 9 月，美国通胀持续回落，" + sentence * 8
    actors = {"as_of_date": "2026-10-12", "situation_brief": {"current_situation": paragraph, "context": paragraph}}
    gen = _world_brief(monkeypatch, max_chars=1400, english=False)
    brief = gen._build_world_brief("美国失业率会在2027年前升破5%吗？", actors, ["失业", "降息"], official_data=carrier)
    assert len(brief) <= 1400 and brief.endswith("END UNTRUSTED RESEARCH DATA — official public historical statistics")
    cut = [line for line in brief.split("BEGIN UNTRUSTED")[0].splitlines() if line.endswith("…")]
    assert cut and all(len(line) >= 60 and paragraph.startswith(line[:-1]) for line in cut)
    part = "## 局势简报\n### 当前态势\n" + paragraph
    trimmed = SimulationConfigGenerator._trim_brief_part(part, 200)
    assert len(trimmed) == 200 and part.startswith(trimmed[:-1]) and trimmed.endswith("…")
    # A Latin word inside Chinese prose is dropped whole, never cut in the middle.
    lead, prose = "## 局势简报\n### 当前态势\n", "美联储官员在九月会议后表示" * 6 + "，Federal Reserve officials signalled cuts."
    trimmed = SimulationConfigGenerator._trim_brief_part(lead + prose, len(lead) + len(prose.split("eral")[0]) + 1)
    assert trimmed == lead + "美联储官员在九月会议后表示" * 6 + "…"
    english = "## Situation brief\n### Current situation\n" + "Inflation stayed above target for a year. " * 10
    trimmed = SimulationConfigGenerator._trim_brief_part(english, 200)
    assert english.startswith(trimmed[:-1] + " ") and len(trimmed) >= 190


def test_snapshot_stats_record_every_exclusion(tmp_path):
    carrier = _real_carrier(tmp_path)
    stats = {}
    text = official_data.historical_snapshot(carrier, as_of="2026-10-12", max_series=3, stats=stats)
    assert stats["shown"] == 3 == text.count(" [S")
    assert stats["excluded"] == {"max_series": len(REAL_ROWS) - 3}
    stats = {}
    assert official_data.historical_snapshot(carrier, as_of="2026-10-12", max_chars=10, stats=stats) == ""
    assert stats == {"shown": 0, "excluded": {"budget": len(REAL_ROWS)}}


@pytest.mark.parametrize("frequency, period, before, after, bounds", [
    ("A", "2026-01-01", "2026-03-01", "2027-01-15", ("2026-01-01", "2026-12-31")),
    ("Q", "2026-04-01", "2026-05-15", "2026-07-02", ("2026-04-01", "2026-06-30")),
    ("W", "2026-02-28", "2026-03-02", "2026-03-07", ("2026-02-28", "2026-03-06")),
    ("A", "2025-10-01", "2026-09-29", "2026-10-01", ("2025-10-01", "2026-09-30")),
])
def test_monitor_waits_for_the_whole_anchor_period(tmp_path, monkeypatch, frequency, period, before, after, bounds):
    """Downstream M2: a validated anchor's period start + frequency bound the query, so an
    annual '2026-01-01' anchor is not fetched before the year ends."""
    monkeypatch.setattr(Config, "DATA_SOURCES_ENABLED", True)
    calls = []
    client = SimpleNamespace(get=lambda sid, **kw: calls.append(kw) or {"observations": []})
    binary = {"id": "F1", "probability": 0.6, "resolution_criteria": "official value",
              "data_anchor": {"series": "fred:SERIES", "comparator": ">", "threshold": 1, "units": "Percent",
                              "observation": period, "period": period, "frequency": frequency}}
    kwargs = {"forecast": {"binary_forecasts": [binary]}, "client": SimpleNamespace(), "data_client": client,
              "report_folder": str(tmp_path / "report"), "ledger_dir": str(tmp_path / "ledger"), "write_report": False}
    early = monitor.run_monitor("report_local", as_of=before, **kwargs)
    assert calls == []
    assert early["data_resolution_status"][0] == {
        "forecast_id": "F1", "series": "fred:SERIES", "status": "pending", "reason": "Observation period has not ended"}
    monitor.run_monitor("report_local", as_of=after, **kwargs)
    assert [(c["start"], c["end"]) for c in calls] == [bounds]


def _cpi_binary():
    return {"id": "F2", "probability": 0.55, "resolution_criteria": "September CPI, reviewed by 2026-10-12",
            "data_anchor": {"series": "fred:CPIAUCSL#yoy", "comparator": ">=", "threshold": 3.0,
                            "units": "Percent change from year ago", "transform": "yoy",
                            "observation": "2026-09", "period": "2026-09-01", "frequency": "M"}}


def _monitor_with_fetch(tmp_path, monkeypatch, fetched, as_of):
    monkeypatch.setattr(Config, "DATA_SOURCES_ENABLED", True)
    calls = []
    client = SimpleNamespace(get=lambda sid, **kw: calls.append(sid) or fetched)
    result = monitor.run_monitor("report_local", forecast={"binary_forecasts": [_cpi_binary()]},
                                 client=SimpleNamespace(), data_client=client, as_of=as_of, write_report=False,
                                 report_folder=str(tmp_path / "report"), ledger_dir=str(tmp_path / "ledger"))
    assert calls == ["fred:CPIAUCSL#yoy"]
    return result


@pytest.mark.parametrize("as_of, expected, reason", [
    ("2026-10-12", "pending", "Official value for the period is not yet published"),
    ("2027-01-28", "pending", "Official value for the period is not yet published"),
    ("2027-01-29", "manual", "Official value still unpublished 120 days after the period ended"),
])
def test_monitor_keeps_an_ended_but_unpublished_period_pending(tmp_path, monkeypatch, as_of, expected, reason):
    """The real FRED DataError for CPI yoy 2026-09, captured live on 2026-10-12 before the
    September release: publication lag is pending (no manual review, not degraded) until
    the grace window after the period end closes."""
    capture = json.loads((REAL / "downstream" / "fred_cpi_yoy_unpublished_period_error.json").read_text())
    result = _monitor_with_fetch(tmp_path, monkeypatch, ds.DataError(**capture["error"]), as_of)
    assert result["data_resolution_status"] == [
        {"forecast_id": "F2", "series": "fred:CPIAUCSL#yoy", "status": expected, "reason": reason}]
    assert result["degraded"] is (expected == "manual")
    assert [row["reason"] for row in result["needs_manual"]] == ([reason] if expected == "manual" else [])
    assert forecast_ledger.read_data_resolutions(str(tmp_path / "ledger")) == []


@pytest.mark.parametrize("error, expected, reason", [
    (("FRED rate limit reached; retry shortly.", True, "rate_limited"), "pending",
     "Official source temporarily unavailable (rate_limited); retried on the next run"),
    (("The series does not exist.", False, "unknown_series"), "manual",
     "Provider did not return a usable official series (unknown_series)"),
    (None, "manual", "Provider did not return a usable official series"),
])
def test_monitor_retries_transient_failures_and_flags_broken_series(tmp_path, monkeypatch, error, expected, reason):
    fetched = ds.DataError("fred:CPIAUCSL", *error) if error else "not a series"
    result = _monitor_with_fetch(tmp_path, monkeypatch, fetched, "2026-10-12")
    assert result["data_resolution_status"][0]["status"] == expected
    assert result["data_resolution_status"][0]["reason"] == reason
    assert result["degraded"] is (expected == "manual")


def test_monitor_summary_reports_the_official_data_track_record(tmp_path, monkeypatch, capsys):
    """G5: data_resolutions.jsonl feeds the summary CLI, per-report rows and a separate
    forecast track record (None until something resolved, so consumers stay unchanged)."""
    monkeypatch.setattr(forecast_ledger, "ledger_dir", lambda: str(tmp_path))
    assert forecast_ledger.official_data_track_record() is None
    assert monitor.main(["summary"]) == 0
    assert json.loads(capsys.readouterr().out)["official_data_brier"] == {"n_resolved": 0, "mean_brier": None}
    forecast_ledger.append_data_resolution({
        "report_id": "report_local", "forecast_id": "F1", "series": "fred:UNRATE", "resolved_outcome": True,
        "model_p": 0.7, "observation": {"date": "2026-01-01", "value": 4.2}, "resolved_at": "2026-03-01"},
        d=str(tmp_path))
    assert monitor.main(["summary"]) == 0
    assert json.loads(capsys.readouterr().out)["official_data_brier"] == {"n_resolved": 1, "mean_brier": 0.09}
    assert forecast_ledger.official_data_track_record() == {
        "n_resolved": 1, "mean_brier": 0.09, "source": "data_resolutions.jsonl",
        "scoring": "binary Brier vs official observation"}
    row = monitor._summary_row({"report_id": "r", "data_resolution_status": [
        {"status": "resolved"}, {"status": "pending"}, {"status": "pending"}, {"status": "manual"}]})
    assert (row["data_resolved"], row["data_pending"], row["data_manual"]) == (1, 2, 1)
    assert not any(key.startswith("data_") for key in monitor._summary_row({"report_id": "r"}))
