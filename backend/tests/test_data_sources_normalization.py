"""Provider normalization of official data (fix contract §0, §1.2-§1.5; slice A1).

Real MCP payloads captured 2026-10-11 through the vendored servers
(fixtures/data_sources/real/providers/*.json) are replayed through a fake hub at
their capture clock, so the adapter issues the same requests it made live. The
catalog-wide unit test replays the native unit attributes captured for every
curated World Bank and BIS entry (real/catalog-native-units-2026-10-12.json).
Runs under plain pytest; bridge modules load by bare name from deerflow_bridge/.
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

_BRIDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import data_sources as ds  # noqa: E402
from data_mcp import CallResult  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "data_sources"
REAL = FIXTURES / "real" / "providers"
NATIVE_UNITS = json.loads((FIXTURES / "real" / "catalog-native-units-2026-10-12.json").read_text())
NOW = 1791763200.0  # 2026-10-12T00:00:00Z
REPO_ROOT = Path(_BRIDGE_DIR).parent


class Hub:
    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def call(self, provider, tool, args, **kw):
        self.calls.append((provider, tool, json.loads(json.dumps(args))))
        data = self.handler(provider, tool, args)
        return data if isinstance(data, CallResult) else CallResult(True, json.dumps(data), None, 0.0)

    def status(self):
        return {p: {"state": "ready", "error": None} for p in ds.PROVIDERS}

    def start(self, names, **kw):
        pass

    def close(self):
        pass


def capture(name):
    return json.loads((REAL / f"{name}.json").read_text())


def response(name, tool):
    return next(c["response"] for c in capture(name)["calls"] if c["tool"] == tool)


def source(tmp_path, handler, *, clock=NOW, env=None, **kw):
    settings = {"DATA_SOURCES_ENABLED": "true", "FRED_API_KEY": "synthetic-key-123456"}
    settings.update(env or {})
    hub = Hub(handler)
    return ds.DataSources(hub, env=settings, cache_dir=tmp_path / "cache", clock=lambda: clock, **kw), hub


def replay(tmp_path, name, *, env=None, **kw):
    """Replay one real capture at its own clock; returns (result, hub, capture)."""
    recorded = capture(name)
    def handler(provider, tool, args):
        return next(c["response"] for c in recorded["calls"] if (c["provider"], c["tool"]) == (provider, tool))
    data_source, hub = source(tmp_path, handler, clock=recorded["clock"], env=env)
    sid = recorded["series"]
    return data_source.get(sid, **{**recorded["request"], **kw}), hub, recorded


# P-UNITS / verifier M2: every curated wb and BIS entry, replayed from its captured native attributes

def _wb_handler(sid, native):
    indicator, country = sid.split(":", 1)[1].split("/")
    dims = {k: v[0] for k, v in native["dims"].items() if v and v[0] != "None"}
    rows = [{"REF_AREA": country, "TIME_PERIOD": period, "OBS_VALUE": "1.5", "UNIT_MEASURE": native["UNIT_MEASURE"][0],
             "UNIT_MEASURE_NAME": native["UNIT_MEASURE_NAME"][0], "UNIT_MULT": int(native["UNIT_MULT"][0]), **dims}
            for period in native["periods"]]
    metadata = {"idno": indicator, "database_id": "_".join(indicator.split("_")[:2]), "periodicity": "Annual",
                "measurement_unit": native["measurement_unit"], "name": "captured indicator"}
    def handler(provider, tool, args):
        if tool == "data360_get_metadata":
            return {"indicator_metadata": metadata, "error": None, "stale": False}
        return {"data": rows, "count": len(rows), "offset": 0, "total_count": None, "has_more": False,
                "next_offset": None, "metadata": {k: metadata[k] for k in ("idno", "database_id", "periodicity", "measurement_unit")},
                "error": None, "failed_validation": None}
    return handler, (f"{native['periods'][0]}-01-01", f"{native['periods'][-1]}-12-31")


def _bis_handler(sid, native):
    flow, key = sid.split(":", 1)[1].split("/")
    meta = ds.catalog.BIS_FLOWS[flow]
    row = dict(zip(meta["dims"], key.split(".")))
    assert all(row.get(d) == v[0] for d, v in native["dims"].items()), "captured dims disagree with the key"
    for name, label in (("UNIT_MEASURE", "UNIT_MEASURE_label"), ("UNIT_MULT", None)):
        if native[name]:
            row[name] = native[name][0]
        if label and native[label]:
            row[label] = native[label][0]
    row.update(TIME_PERIOD=native["last"][0], OBS_VALUE=native["last"][1])
    def handler(provider, tool, args):
        return {"flow_ref": args["flow_ref"], "rows": [row], "truncated": False, "count": 1}
    return handler, ("2024-01-01", "2026-10-12")


_PINNED = sorted((p, sid) for p in ("wb", "bis") for sid in NATIVE_UNITS[p])


def test_native_unit_capture_covers_every_curated_wb_and_bis_entry():
    curated = {e.series for e in ds.catalog.CATALOG if e.provider in ("wb", "bis")}
    assert curated == {sid for _, sid in _PINNED}
    assert all(ds.catalog_field(sid, "native_unit") is not None for sid in curated)


@pytest.mark.parametrize("provider,sid", _PINNED, ids=[sid for _, sid in _PINNED])
def test_captured_native_attributes_yield_the_curated_units(tmp_path, provider, sid):
    native = NATIVE_UNITS[provider][sid]
    handler, (start, end) = (_wb_handler if provider == "wb" else _bis_handler)(sid, native)
    data_source, _ = source(tmp_path, handler)
    result = data_source.get(sid, start=start, end=end)
    entry = ds.catalog.lookup(sid)
    assert isinstance(result, ds.Series), result
    assert result.units == entry.units
    assert result.provenance["native_unit"]["basis"] == "verified catalog pin"
    assert result.observations[-1].value == float(native["last"][1] if provider == "bis" else "1.5")


@pytest.mark.parametrize("damage", ["code", "multiplier"])
def test_pinned_identity_drift_fails_closed(tmp_path, damage):
    native = json.loads(json.dumps(NATIVE_UNITS["wb"]["wb:IMF_WEO_NGDPD/USA"]))
    native["UNIT_MEASURE" if damage == "code" else "UNIT_MULT"] = ["EUR" if damage == "code" else "6"]
    handler, (start, end) = _wb_handler("wb:IMF_WEO_NGDPD/USA", native)
    data_source, _ = source(tmp_path, handler)
    result = data_source.get("wb:IMF_WEO_NGDPD/USA", start=start, end=end)
    assert isinstance(result, ds.DataError) and "differs from the verified catalog pin" in result.message


def test_ngdpd_false_multiplier_keeps_whole_dollars_under_curated_units(tmp_path):
    result, _, _ = replay(tmp_path, "wb_imf_weo_ngdpd_usa")
    point = next(o for o in result.observations if o.date == "2024-01-01")
    # Data360 labels these rows "billion US Dollars" x10^9, but they are whole dollars (WDI 2024 = 2.93e13).
    assert result.units == "U.S. dollars" and point.value == pytest.approx(2.9298e13, rel=1e-3)
    assert result.provenance["native_unit"] == {"code": "USD", "label": "billion US Dollars", "multiplier": 9,
                                                "metadata_unit": "US dollars (Billions)", "basis": "verified catalog pin"}
    assert "≈ 29.3 trillion U.S. dollars" in ds.render_series_brief(result)


def _rows_for(name, country):
    rows = json.loads(json.dumps(response(name, "data360_get_data")))
    for row in rows["data"]:
        row["REF_AREA"] = country
    return rows


def test_uncurated_economy_takes_a_curated_siblings_pin_and_units(tmp_path):
    metadata = response("wb_imf_weo_ngdpd_usa", "data360_get_metadata")
    page = _rows_for("wb_imf_weo_ngdpd_usa", "DEU")
    data_source, _ = source(tmp_path, lambda p, t, a: metadata if t == "data360_get_metadata" else page)
    result = data_source.get("wb:IMF_WEO_NGDPD/DEU", start="2020-01-01", end="2031-12-31")
    assert isinstance(result, ds.Series) and result.units == "U.S. dollars"
    assert result.provenance["native_unit"]["basis"] == "verified pin of curated sibling wb:IMF_WEO_NGDPD/USA"
    assert ds.series_label(result) == "Gross domestic product (GDP), Current prices, US dollar — Germany"


def test_uncurated_indicator_with_an_unverified_multiplier_fails_closed(tmp_path):
    metadata = json.loads(json.dumps(response("wb_imf_weo_ngdpd_usa", "data360_get_metadata")))
    metadata["indicator_metadata"]["idno"] = "IMF_WEO_NGDPDPC"
    page = _rows_for("wb_imf_weo_ngdpd_usa", "USA")
    page["metadata"]["idno"] = "IMF_WEO_NGDPDPC"
    data_source, _ = source(tmp_path, lambda p, t, a: metadata if t == "data360_get_metadata" else page)
    result = data_source.get("wb:IMF_WEO_NGDPDPC/USA", start="2020-01-01", end="2031-12-31")
    assert isinstance(result, ds.DataError) and "multiplier cannot be verified" in result.message


def test_uncurated_codelist_fallback_ignores_uninformative_metadata(tmp_path):
    metadata = json.loads(json.dumps(response("wb_wdi_gdp_growth_usa", "data360_get_metadata")))
    metadata["indicator_metadata"].update(idno="WB_WDI_SP_POP_TOTL_FE_IN", measurement_unit="Unit")
    page = _rows_for("wb_wdi_gdp_growth_usa", "USA")
    page["metadata"].update(idno="WB_WDI_SP_POP_TOTL_FE_IN", measurement_unit="Unit")
    for row in page["data"]:
        row.update(UNIT_MEASURE="PS", UNIT_MEASURE_NAME="Persons")
    data_source, _ = source(tmp_path, lambda p, t, a: metadata if t == "data360_get_metadata" else page)
    result = data_source.get("wb:WB_WDI_SP_POP_TOTL_FE_IN/USA", start="2015-01-01", end="2025-12-31")
    assert isinstance(result, ds.Series) and result.units == "Persons"
    assert result.provenance["native_unit"]["basis"] == "native label"


def test_uncurated_sdmx_keys_use_sibling_codelist_or_unknown_units(tmp_path):
    bis = json.loads(json.dumps(response("bis_ws_cbpol_us_2024", "fetch_dataset")))
    rows = bis["rows"]
    for row in rows:
        row["REF_AREA"] = "FR"
    data_source, _ = source(tmp_path, lambda p, t, a: bis)
    result = data_source.get("bis:WS_CBPOL/M.FR", start="2024-01-01", end="2024-12-31")
    assert result.units == "Per cent per year" and result.provenance["native_unit"]["basis"].startswith("curated sibling bis:WS_CBPOL/")
    defs = response("imf_weo_usa_ngdp_rpch_default_window", "imf_get_parameter_defs")
    weo = json.loads(json.dumps(response("imf_weo_usa_ngdp_rpch_default_window", "imf_fetch_data")))
    for row in weo["rows"]:
        row["country"] = "FRA"
    data_source, _ = source(tmp_path / "imf", lambda p, t, a: defs if t == "imf_get_parameter_defs" else weo)
    result = data_source.get("imf:WEO/FRA.NGDP_RPCH.A", start="2015-01-01", end="2031-12-31")
    assert result.units == "Percent change" and result.provenance["native_unit"]["basis"].startswith("curated sibling imf:WEO/")
    for row in weo["rows"]:
        row["indicator"] = "NGSD_NGDP"
    data_source, _ = source(tmp_path / "imf2", lambda p, t, a: defs if t == "imf_get_parameter_defs" else weo)
    result = data_source.get("imf:WEO/FRA.NGSD_NGDP.A", start="2015-01-01", end="2031-12-31")
    assert isinstance(result, ds.Series) and result.units == "" and result.provenance["native_unit"]["basis"] == "not supplied by provider"


# V_LST: IMF WEO rows on Data360 carry COMP_BREAKDOWN_1="V_LST" on every row

@pytest.mark.parametrize("change", ["missing", "other"])
def test_v_lst_is_accepted_only_when_uniform(tmp_path, change):
    metadata = response("wb_imf_weo_ngdp_rpch_chn_default_window", "data360_get_metadata")
    page = json.loads(json.dumps(response("wb_imf_weo_ngdp_rpch_chn_default_window", "data360_get_data")))
    if change == "missing":
        page["data"][3].pop("COMP_BREAKDOWN_1")
    else:
        page["data"][3]["COMP_BREAKDOWN_1"] = "V_2025_OCT"
    data_source, _ = source(tmp_path, lambda p, t, a: metadata if t == "data360_get_metadata" else page)
    result = data_source.get("wb:IMF_WEO_NGDP_RPCH/CHN", start="2002-01-01", end="2031-12-31")
    assert isinstance(result, ds.DataError) and "ambiguous disaggregations" in result.message


# §1.4 status policies (P-WEOSTATUS, MISSED-2) and projection default end (M1, F2, RPT-7, L3)

def test_default_window_reaches_the_weo_projection_path_and_infers_status(tmp_path):
    result, hub, recorded = replay(tmp_path, "wb_imf_weo_ngdp_rpch_chn_default_window")
    args = next(a for p, t, a in hub.calls if t == "data360_get_data")
    assert recorded["request"] == {} and (args["start_year"], args["end_year"]) == (2001, 2032)
    assert args == next(c["args"] for c in recorded["calls"] if c["tool"] == "data360_get_data")
    assert result.observations[-1].date == "2031-01-01" and result.projection_from == "2026-01-01"
    assert result.provenance["vintage_basis"] == "Data360 version_statement.version_date 2026-10-06"
    kinds = {o.date[:4]: ds.observation_kind(o, result) for o in result.observations}
    assert kinds["2024"] == "observed" and kinds["2025"] == "estimate" and kinds["2026"] == kinds["2031"] == "projection"
    assert ds.latest_observed(result).date == "2024-01-01"
    assert result.title == "Gross domestic product (GDP), Constant prices, Percent change: China"
    page = ds.render_series_page(result)
    assert "publisher projections are marked 'projection'" in page and "| 2031 | 3.291% | projection |" in page


def test_imf_live_weo_flow_uses_the_retrieval_year_and_the_projection_end(tmp_path):
    result, hub, _ = replay(tmp_path, "imf_weo_usa_ngdp_rpch_default_window")
    params = next(a for p, t, a in hub.calls if t == "imf_fetch_data")["params"]
    assert (params["start_year"], params["end_year"]) == (2001, 2032)
    assert result.provenance["vintage_year"] == 2026 and result.provenance["status_basis"] == "inferred_from_vintage"
    assert [o.date[:4] for o in result.observations][-1] == "2031"
    assert ds.series_stats(result)["latest"] == {"date": "2024-01-01", "value": 2.793116}


def test_gep_vintage_comes_from_the_release_metadata_not_the_retrieval_year(tmp_path):
    result, _, _ = replay(tmp_path, "wb_gep_gdp_growth_chn_default_window")
    assert result.provenance["vintage_year"] == 2025  # Data360 GEP version date 2025-02-25
    assert [(o.date[:4], o.flag) for o in result.observations] == [
        ("2022", "observed"), ("2023", "observed"), ("2024", "estimate"), ("2025", "projection"), ("2026", "projection")]
    assert result.provenance["resolution_safe"] is False


def test_wdi_policy_leaves_the_retrieval_year_unclassified(tmp_path):
    recorded = capture("wb_wdi_gdp_growth_usa")
    metadata = response("wb_wdi_gdp_growth_usa", "data360_get_metadata")
    page = json.loads(json.dumps(response("wb_wdi_gdp_growth_usa", "data360_get_data")))
    page["data"][0]["TIME_PERIOD"] = "2026"
    data_source, _ = source(tmp_path, lambda p, t, a: metadata if t == "data360_get_metadata" else page, clock=recorded["clock"])
    result = data_source.get("wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA", start="2016-01-01", end="2026-12-31")
    flags = {o.date[:4]: o.flag for o in result.observations}
    assert flags["2026"] == "unknown" and flags["2024"] == "observed"


def test_older_policy_rows_keep_unknown_status_and_their_bytes():
    row = json.loads((FIXTURES / "real" / "stored_v2" / "wb_imf_weo_ngdp_rpch_chn.json").read_text())["row"]
    series = ds.Series.from_dict(row)
    assert {o.flag for o in series.observations} == {"unknown"} and "status_basis" not in series.provenance


@pytest.mark.parametrize("end,finish", [("2024", "2024-12-31"), ("2024-03", "2024-03-31"), ("2024-Q2", "2024-06-30"),
                                        ("2024-02-15", "2024-02-15")])
def test_partial_end_dates_mean_the_whole_period(tmp_path, end, finish):
    data_source, hub = source(tmp_path, lambda *a: response("fred_unrate_2024", "fred_get_series"))
    data_source.get("fred:UNRATE", start="2024-01-01", end=end)
    assert hub.calls[-1][2]["observation_end"] == finish


def test_history_series_default_window_still_ends_today(tmp_path):
    data_source, hub = source(tmp_path, lambda *a: response("fred_unrate_2024", "fred_get_series"))
    data_source.get("fred:UNRATE")
    assert (hub.calls[-1][2]["observation_start"], hub.calls[-1][2]["observation_end"]) == ("2016-10-12", "2026-10-12")


def test_default_daily_window_opens_on_a_whole_month(tmp_path):
    result, hub, _ = replay(tmp_path, "usgov_debt_to_penny_daily", start=None)
    assert "record_date:gte:2024-10-01" in hub.calls[-1][2]["filter"]
    assert ds.observation_kind(result.observations[0], result) == "observed"


def test_windows_never_start_before_the_providers_earliest_data(tmp_path):
    payload = response("usgov_spending_total_fy", "usa_spending_over_time")
    data_source, hub = source(tmp_path, lambda *a: payload)
    result = data_source.get("usgov:spending/total")
    assert isinstance(result, ds.Series) and hub.calls[-1][2]["start_date"] == "2007-10-01"
    early = data_source.get("usgov:spending/total", start="1999-01-01", end="2005-12-31")
    assert early.code == "invalid_window" and "no data before 2007-10-01" in early.message and len(hub.calls) == 1


# P-DAILY / RPT-6: complete vs partial months, end-of-period stocks, latest daily point

def test_daily_yields_complete_closed_months_and_a_partial_open_month(tmp_path):
    result, _, _ = replay(tmp_path, "fred_dgs10_daily")
    assert [(o.date, o.flag) for o in result.observations] == [("2026-08-01", ""), ("2026-09-01", ""), ("2026-10-01", "preliminary")]
    assert [result.provenance["periods"][o.date]["complete"] for o in result.observations] == [True, True, False]
    assert ds.observation_kind(result.observations[-1], result) == "partial"
    latest = ds.latest_observed(result)
    assert latest.date == "2026-09-01" and ds.series_stats(result)["latest"]["date"] == "2026-09-01"
    assert result.provenance["latest_daily"] == {"date": "2026-10-08", "value": 5.22}
    assert result.provenance["aggregation_method"] == "avg" and result.provenance["resolution_safe"] is False
    assert "- Latest daily value: 5.22% (2026-10-08); monthly values are means of daily data." in ds.render_series_page(result)
    assert "Latest daily: 5.22% (2026-10-08)" in ds.render_series_brief(result)


def test_policy_target_months_take_the_end_of_period_value(tmp_path):
    result, _, _ = replay(tmp_path, "fred_dfedtaru_daily_step")
    # FOMC cuts of 2025-09-17, 2025-10-29 and 2025-12-10: a mean would print 4.375 for September.
    assert [(o.date[:7], o.value) for o in result.observations] == [("2025-09", 4.25), ("2025-10", 4.0), ("2025-11", 4.0), ("2025-12", 3.75)]
    assert all(result.provenance["periods"][o.date]["complete"] for o in result.observations)
    assert result.provenance["aggregation_method"] == "eop"


def test_debt_stock_is_end_of_month_with_a_scaled_companion(tmp_path):
    result, _, recorded = replay(tmp_path, "usgov_debt_to_penny_daily")
    rows = recorded["calls"][0]["response"]["data"]["rows"]
    last_august = max((r for r in rows if r[0].startswith("2026-08")), key=lambda r: r[0])
    assert result.observations[0].value == float(last_august[1])
    assert result.observations[-1].flag == "preliminary" and result.provenance["latest_daily"]["date"] == "2026-10-08"
    page = ds.render_series_page(result)
    assert "- Latest: 40171825101340.31 (2026-09-01); ≈ 40.17 trillion U.S. dollars;" in page
    assert "≈ 40.17 trillion U.S. dollars" in ds.render_series_brief(result)


def test_a_closed_month_without_later_data_stays_partial_for_two_weeks(tmp_path):
    payload = json.loads(json.dumps(response("fred_dgs10_daily", "fred_get_series")))
    payload["data"] = [r for r in payload["data"] if r["date"] < "2026-10-01"]
    payload["total_observations"] = len(payload["data"])
    data_source, _ = source(tmp_path, lambda *a: payload, clock=1791763200.0 - 10 * 86400)  # 2026-10-02
    result = data_source.get("fred:DGS10", start="2026-08-01", end="2026-10-02")
    assert [(o.date, o.flag) for o in result.observations] == [("2026-08-01", ""), ("2026-09-01", "preliminary")]


def test_a_history_opening_mid_month_leaves_that_month_partial(tmp_path):
    # FRED keeps ten years of SP500 and three of the ICE spreads: live, the daily history opened on
    # 2016-10-13 / 2023-10-16 and FRED's own monthly mean of that month was null. An explicit window
    # opening earlier must not present the mean of those last days as the month (contract §1.3).
    payload = json.loads(json.dumps(response("fred_dgs10_daily", "fred_get_series")))
    payload["data"] = [r for r in payload["data"] if r["date"] >= "2026-08-17"]
    payload["total_observations"] = len(payload["data"])
    data_source, _ = source(tmp_path, lambda *a: payload, clock=capture("fred_dgs10_daily")["clock"])
    result = data_source.get("fred:DGS10", start="2026-07-01")
    august = result.provenance["periods"]["2026-08-01"]
    assert (august["covered_start"], august["complete"]) == ("2026-08-17", False)
    assert ds.observation_kind(result.observations[0], result) == "partial"
    assert ds.latest_observed(result).date == "2026-09-01" and result.provenance["periods"]["2026-09-01"]["complete"]
    # A month opened late only by a weekend or holidays stays complete (the real history opens 2026-08-03).
    full, _ = source(tmp_path / "full", lambda *a: response("fred_dgs10_daily", "fred_get_series"),
                     clock=capture("fred_dgs10_daily")["clock"])
    whole = full.get("fred:DGS10", start="2026-07-01")
    assert whole.observations[0].date == "2026-08-01" and whole.provenance["periods"]["2026-08-01"]["complete"]


# P-REDACT, P-SYMLINK, B1, P-CACHE / P-NEVERRAISE

def test_short_or_numeric_env_values_never_corrupt_dates_but_keys_are_redacted(tmp_path):
    env = {"X_MAX_TOKENS": "20", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "LLM_MAX_TOKENS": "16384",
           "TOKENIZERS_PARALLELISM": "false", "FRED_API_KEY": "abcd1234efgh"}
    payload = json.loads(json.dumps(response("fred_unrate_2024", "fred_get_series")))
    payload["notes"] = "Served for key abcd1234efgh. " + payload["notes"]
    data_source, _ = source(tmp_path, lambda *a: payload, env=env)
    result = data_source.get("fred:UNRATE", start="2024-01-01", end="2024-12-31")
    assert isinstance(result, ds.Series) and result.observations[0].date == "2024-01-01"
    assert "abcd1234efgh" not in json.dumps(result.to_dict())
    # A curated series shows its curated notes; FRED's own note text stays (redacted) in provenance.
    assert result.notes == ds.catalog.lookup("fred:UNRATE").notes
    assert "[redacted]" in result.provenance["provider_notes"]


def test_symlinked_ancestors_of_output_and_cache_dirs_work_but_inner_links_do_not(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    env = {"FRED_API_KEY": ""}
    def keyless(provider, tool, args):
        return {"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": [{"seriesID": "LNS14000000", "data": [
            {"year": "2026", "period": "M09", "value": "4.2", "footnotes": [{}]}]}]}}
    data_source = ds.DataSources(Hub(keyless), env={"DATA_SOURCES_ENABLED": "true", **env}, cache_dir=link / "cache", clock=lambda: NOW)
    result = data_source.get("bls:LNS14000000", start="2026-01-01", end="2026-09-30")
    assert isinstance(result, ds.Series) and (real / "cache" / "bls-quota.json").exists()
    manifest = ds.write_dataset_files([result], link / "run")
    assert "error" not in manifest and ds.load_datasets(link / "run")[0]["series"] == "bls:LNS14000000"
    (real / "run" / "data").rename(real / "run" / "elsewhere")
    (real / "run" / "data").symlink_to(real / "run" / "elsewhere", target_is_directory=True)
    assert ds.load_datasets(link / "run") == []


def test_relative_cache_dir_resolves_against_the_repository_from_any_cwd(tmp_path, monkeypatch):
    seen = []
    for cwd in (tmp_path, Path(_BRIDGE_DIR)):
        monkeypatch.chdir(cwd)
        seen.append(ds.DataSources(Hub(lambda *a: {}), env={"DATA_SOURCES_CACHE_DIR": "backend/uploads/.a1-relative-cache"})._cache_dir)
    assert seen[0] == seen[1] == Path(os.path.realpath(REPO_ROOT / "backend/uploads/.a1-relative-cache"))
    home = ds.DataSources(Hub(lambda *a: {}), env={"DATA_SOURCES_CACHE_DIR": "~/.a1-cache-probe"})._cache_dir
    assert home == Path(os.path.realpath(Path.home() / ".a1-cache-probe"))


def test_get_many_never_raises_on_malformed_ids_or_arguments(tmp_path):
    data_source, hub = source(tmp_path, lambda *a: response("fred_unrate_2024", "fred_get_series"))
    assert data_source.get_many(None, deadline_s=5) == {}
    odd = data_source.get_many([["fred:UNRATE"]], deadline_s=5)
    assert [e.code for e in odd.values()] == ["invalid_input"]
    unexpected = data_source.get_many(["fred:UNRATE"], deadline_s=5, frequency="m")
    assert unexpected["fred:UNRATE"].code == "invalid_input" and "frequency" in unexpected["fred:UNRATE"].message
    assert not hub.calls


def test_stale_cache_files_are_pruned_and_memory_is_bounded(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    old, fresh, other = cache / ("a" * 64 + ".json"), cache / ("b" * 64 + ".json"), cache / "bls-quota.json"
    for path in (old, fresh, other):
        path.write_text("{}")
    os.utime(old, (NOW - 8 * 86400, NOW - 8 * 86400))
    os.utime(other, (NOW - 30 * 86400, NOW - 30 * 86400))
    os.utime(fresh, (NOW - 86400, NOW - 86400))
    monkeypatch.setattr(ds, "_MEMORY_MAX", 2)
    data_source, _ = source(tmp_path, lambda *a: response("fred_unrate_2024", "fred_get_series"))
    assert not old.exists() and fresh.exists() and other.exists()
    for month in ("01", "02", "03", "04"):
        data_source.get("fred:UNRATE", start=f"2024-{month}-01", end="2024-12-31")
    assert len(data_source._memory) == 2


# F10 / L8: curated titles survive provider wording

@pytest.mark.parametrize("name", ["wb_imf_weo_ngdpd_usa", "wb_wdi_gdp_growth_usa", "wb_gep_gdp_growth_chn_default_window"])
def test_curated_title_wins_and_the_provider_title_is_kept(tmp_path, name):
    result, _, recorded = replay(tmp_path, name)
    entry = ds.catalog.lookup(recorded["series"])
    assert result.title == entry.title and result.provenance["provider_title"] and result.provenance["provider_title"] != entry.title


# BLS footnotes: only code P is a status

def test_bls_informational_footnotes_keep_the_published_status(tmp_path):
    payload = response("bls_ces_lns_2025_2026", "get_multiple_series")
    payload["Results"]["series"] = [s for s in payload["Results"]["series"] if s["seriesID"] == "LNS14000000"]
    data_source, _ = source(tmp_path, lambda *a: payload)
    result = data_source.get("bls:LNS14000000", start="2025-01-01", end="2026-12-31")
    january = next(o for o in result.observations if o.date == "2026-01-01")
    assert (january.value, january.flag) == (4.3, "observed")
    assert "population controls" in result.provenance["raw_status"]["2026-01-01"][0]["text"]
    assert next(o for o in result.observations if o.date == "2025-10-01").value is None


# G4: bounded downstream carrier ranked by relevance

def _write_run(root, count, kiq_rows=(), citations=None):
    series = []
    for n in range(1, count + 1):
        series.append(ds.Series(series=f"fred:A1TEST{n:02d}", provider="fred", provider_name="FRED", title=f"Test {n}",
                                units="Percent", frequency="M", source_url=f"https://fred.stlouisfed.org/series/A1TEST{n:02d}",
                                observations=[ds.Observation("2024-01-01", n)], kiqs=["K1"] if n in kiq_rows else []))
    ds.write_dataset_files(series, root, citations=citations or {s.series: n for n, s in enumerate(series, 1)})


def test_carrier_cap_ranks_anchored_cited_and_kiq_series_and_lists_omissions(tmp_path, monkeypatch):
    monkeypatch.delenv("DATA_SOURCES_MAX_SERIES", raising=False)
    _write_run(tmp_path, 28, kiq_rows=(27,))
    (tmp_path / "research_report.md").write_text("Rates rose [S26]; see also 【S3, S25】 and S27 unbracketed.\n")
    carrier = ds.load_official_data(tmp_path, anchored=["fred:A1TEST28"])
    kept = [r["series"] for r in carrier["series"]]
    assert len(kept) == 24 and kept[:5] == ["fred:A1TEST28", "fred:A1TEST03", "fred:A1TEST25", "fred:A1TEST26", "fred:A1TEST27"]
    assert carrier["omitted"] == ["fred:A1TEST21", "fred:A1TEST22", "fred:A1TEST23", "fred:A1TEST24"]
    monkeypatch.setenv("DATA_SOURCES_MAX_SERIES", "2")
    assert [r["series"] for r in ds.load_official_data(tmp_path)["series"]] == ["fred:A1TEST03", "fred:A1TEST25"]
    assert len(ds.load_official_data(tmp_path, max_series=30)["series"]) == 28
    assert "omitted" not in ds.load_official_data(tmp_path, max_series=30)


def test_carrier_under_the_cap_keeps_manifest_order_without_omissions(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_SOURCES_MAX_SERIES", "not-a-number")
    _write_run(tmp_path, 3)
    carrier = ds.load_official_data(tmp_path)
    assert [r["series"] for r in carrier["series"]] == ["fred:A1TEST01", "fred:A1TEST02", "fred:A1TEST03"]
    assert set(carrier) == {"schema_version", "series"}
