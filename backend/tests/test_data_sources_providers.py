"""Provider routes of the official-data layer (fix contract §3 "A2").

Real MCP payloads captured 2026-10-12 through the vendored servers
(fixtures/data_sources/real/providers/*.json) are replayed through a fake hub at
their capture clock: the adapter must issue exactly the recorded requests. Covers
the usgov EIA and BEA adapters, FRED server-side monthly aggregation for long daily
windows, the FRED/BLS rejected-key fallbacks, FRED 'series does not exist', BLS
per-series messages, fiscal-year settlement and the search flow (strong catalog
hits, English provider search, Data360 geographies). Runs under plain pytest;
bridge modules load by bare name from deerflow_bridge/.
"""
import copy
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

import pytest

_BRIDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import data_sources as ds  # noqa: E402
from data_mcp import CallResult  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "data_sources"
REAL = FIXTURES / "real" / "providers"
NOW = 1791763200.0  # 2026-10-12T00:00:00Z
KEYS = {"FRED_API_KEY": "synthetic-fred-key-0123", "BLS_API_KEY": "synthetic-bls-key-0123",
        "EIA_API_KEY": "synthetic-eia-key-0123", "BEA_API_KEY": "synthetic-bea-key-0123"}


class Hub:
    def __init__(self, handler):
        self.handler, self.calls, self.restarted = handler, [], []

    def call(self, provider, tool, args, **kw):
        self.calls.append((provider, tool, json.loads(json.dumps(args))))
        data = self.handler(provider, tool, args)
        return data if isinstance(data, CallResult) else CallResult(True, json.dumps(data), None, 0.0)

    def status(self):
        return {p: {"state": "ready", "error": None} for p in ds.PROVIDERS}

    def start(self, names, **kw):
        pass

    def restart_without(self, name, keys):
        self.restarted.append((name, tuple(keys)))
        return True

    def close(self):
        pass


def capture(name):
    return json.loads((REAL / f"{name}.json").read_text())


def source(tmp_path, handler, *, clock=NOW, env=None, **kw):
    settings = {"DATA_SOURCES_ENABLED": "true", **KEYS, **(env or {})}
    hub = Hub(handler)
    return ds.DataSources(hub, env=settings, cache_dir=tmp_path / "cache", clock=lambda: clock, **kw), hub


def exact_replay(recorded):
    """A handler answering only the exact recorded requests (any other request fails the test)."""
    def handler(provider, tool, args):
        for call in recorded["calls"]:
            if (call["provider"], call["tool"], call["args"]) == (provider, tool, json.loads(json.dumps(args))):
                return call["response"] if "response" in call else CallResult(False, "", call["error"], 0.0)
        raise AssertionError(f"unrecorded request {provider}.{tool} {args}")
    return handler


def csv_replay(recorded):
    def fetch(url, **kw):
        return next(c["response"] for c in recorded["calls"] if c["args"].get("url") == url).encode()
    return fetch


def replay(tmp_path, name, monkeypatch=None, **kw):
    recorded = capture(name)
    if monkeypatch is not None:
        for attr, value in recorded.get("patches", {}).items():
            monkeypatch.setattr(ds, attr, value)
    env = {k: "" for k, v in recorded.get("env", {}).items() if v == ""}
    data_source, hub = source(tmp_path, exact_replay(recorded), clock=recorded["clock"], env=env,
                              http_get=csv_replay(recorded), **kw)
    return data_source.get(recorded["series"], **recorded["request"]), hub, recorded


# EIA (usgov eia_query)

def test_eia_retail_sales_pages_through_the_exact_recorded_requests(tmp_path, monkeypatch):
    result, hub, recorded = replay(tmp_path, "usgov_eia_sales_us_com_paged", monkeypatch)
    assert isinstance(result, ds.Series), result
    assert [c[2]["offset"] for c in hub.calls] == [0, 5, 10] and len(hub.calls) == len(recorded["calls"])
    assert [o.date for o in result.observations] == [f"2025-{m:02d}-01" for m in range(1, 13)]
    assert result.observations[-1].value == 122521.59204 and result.units == "Million kilowatt-hours"
    assert result.frequency == "M" and result.title.startswith("EIA: Retail Sales of Electricity")
    assert result.provenance["facets"] == {"stateid": "US", "sectorid": "COM"}
    assert result.provenance["pages"] == 3 and result.provenance["native_total"] == 12
    assert "facets%5Bstateid%5D%5B%5D=US" in result.api_url and "api_key" not in result.api_url
    assert all(ds.observation_kind(o, result) == "observed" for o in result.observations)


def test_eia_annual_capacity_and_crude_columns(tmp_path):
    battery, _, _ = replay(tmp_path / "bat", "usgov_eia_capacity_bat")
    assert isinstance(battery, ds.Series) and battery.frequency == "A" and battery.units == "Megawatts"
    assert (battery.observations[0].date, battery.observations[-1].date) == ("2019-01-01", "2024-01-01")
    assert ds.latest_observed(battery).value == 27020
    crude, _, _ = replay(tmp_path / "crude", "usgov_eia_crude_production")
    assert isinstance(crude, ds.Series) and crude.units == "Thousand barrels per day"
    assert crude.observations[-1].date == "2026-07-01" and crude.observations[-1].value == 13948


@pytest.mark.parametrize("damage,code", [
    (lambda row, cols: row.__setitem__(cols.index("sectorid"), "RES"), "provider_error"),
    (lambda row, cols: row.__setitem__(cols.index("sales-units"), "thousand megawatthours"), "provider_error"),
])
def test_eia_rows_must_match_recipe_facets_and_verified_units(tmp_path, monkeypatch, damage, code):
    recorded = capture("usgov_eia_sales_us_com_paged")
    data = recorded["calls"][1]["response"]["data"]
    damage(data["rows"][2], data["columns"])
    monkeypatch.setattr(ds, "_EIA_PAGE_ROWS", 5)
    data_source, _ = source(tmp_path, exact_replay(recorded), clock=recorded["clock"])
    result = data_source.get(recorded["series"], **recorded["request"])
    assert isinstance(result, ds.DataError) and result.code == code


def test_eia_duplicate_period_and_empty_window(tmp_path, monkeypatch):
    recorded = capture("usgov_eia_capacity_bat")
    rows = recorded["calls"][0]["response"]["data"]["rows"]
    rows.append(list(rows[0]))
    recorded["calls"][0]["response"]["data"]["total"] += 1
    data_source, _ = source(tmp_path, exact_replay(recorded), clock=recorded["clock"])
    result = data_source.get(recorded["series"], **recorded["request"])
    assert isinstance(result, ds.DataError) and "not unique" in result.message
    empty = {"summary": "No EIA data for electricity/state-electricity-profiles/capability with these filters.",
             "dataType": "empty", "data": None}
    data_source, _ = source(tmp_path / "empty", lambda *a: empty, clock=recorded["clock"])
    result = data_source.get(recorded["series"], **recorded["request"])
    assert isinstance(result, ds.DataError) and result.code == "not_found"


def test_keyed_usgov_recipe_without_its_key_never_calls(tmp_path):
    data_source, hub = source(tmp_path, lambda *a: pytest.fail("no call expected"), env={"EIA_API_KEY": ""})
    result = data_source.get("usgov:eia/electricity_sales/US.ALL")
    assert isinstance(result, ds.DataError) and result.code == "unknown_recipe" and "EIA_API_KEY" in result.message
    assert hub.calls == []


# BEA (usgov bea_gdp_national / bea_gdp_by_industry)

def test_bea_nipa_line_read_in_two_year_chunks(tmp_path):
    result, hub, _ = replay(tmp_path, "usgov_bea_real_gdp_growth")
    assert isinstance(result, ds.Series), result
    assert [c[2]["year"] for c in hub.calls] == ["2025,2026", "2024"]
    assert [o.date for o in result.observations][:2] == ["2024-01-01", "2024-04-01"] and len(result.observations) == 10
    assert result.observations[-1].date == "2026-04-01" and result.observations[-1].value == 2.2
    assert result.units == "Percent change from preceding period (annual rate)" and result.frequency == "Q"
    assert result.provenance["line"] == "Gross domestic product"
    assert result.provenance["units_origin"].startswith("curated recipe")


def test_bea_industry_roman_quarters_one_year_per_call(tmp_path):
    result, hub, _ = replay(tmp_path, "usgov_bea_value_added_514")
    assert isinstance(result, ds.Series), result
    assert [(c[2]["year"], c[2]["industry"]) for c in hub.calls] == [("2026", "514"), ("2025", "514")]
    assert [o.date for o in result.observations] == ["2025-01-01", "2025-04-01", "2025-07-01", "2025-10-01",
                                                     "2026-01-01", "2026-04-01"]
    assert result.observations[-1].value == 694.7 and result.units.startswith("Billions of dollars")


def test_bea_unpublished_current_year_is_skipped_not_fatal(tmp_path):
    recorded = capture("usgov_bea_value_added_514")
    rejected = capture("usgov_bea_unpublished_year")["errors"]["invalid_year"]
    january = 1799020800.0  # 2027-01-04
    def handler(provider, tool, args):
        if args["year"] == "2027":
            return CallResult(False, "", rejected, 0.0)
        return next(c["response"] for c in recorded["calls"] if c["args"]["year"] == args["year"])
    data_source, hub = source(tmp_path, handler, clock=january)
    result = data_source.get(recorded["series"], start="2025-01-01")
    assert isinstance(result, ds.Series) and result.observations[-1].date == "2026-04-01"
    assert result.provenance["chunks"][0] == {"years": [2027, 2027], "lines": 0, "note": "not yet published"}
    # An older year failing the same way is a real error.
    data_source, _ = source(tmp_path / "old", lambda *a: CallResult(False, "", rejected, 0.0), clock=january)
    assert isinstance(data_source.get(recorded["series"], start="2025-01-01", end="2025-12-31"), ds.DataError)


def test_bea_industry_window_is_clamped_to_its_first_quarterly_year(tmp_path):
    # BEA publishes quarterly GDP by Industry from 2005: an earlier year fails the whole request
    # live ("Invalid year: 2004", final/L bea_probe.log), so the recipe's min_start clamps it.
    recorded = capture("usgov_bea_value_added_514")
    rejected = capture("usgov_bea_unpublished_year")["errors"]["invalid_year"].replace("2027", "2004")
    payload = copy.deepcopy(next(c["response"] for c in recorded["calls"] if c["args"]["year"] == "2025"))
    row = payload["data"]["rows"][0]
    row[1] = row[1].replace("2025Q", "2005Q")
    def handler(provider, tool, args):
        return CallResult(False, "", rejected, 0.0) if args["year"] == "2004" else payload
    data_source, hub = source(tmp_path, handler, clock=recorded["clock"])
    result = data_source.get(recorded["series"], start="2004-01-01", end="2005-12-31")
    assert isinstance(result, ds.Series), result
    assert [c[2]["year"] for c in hub.calls] == ["2005"]
    assert [o.date for o in result.observations] == ["2005-01-01", "2005-04-01", "2005-07-01", "2005-10-01"]
    assert result.provenance["requested_start"] == "2005-01-01"
    early = data_source.get(recorded["series"], start="2003-01-01", end="2004-12-31")
    assert isinstance(early, ds.DataError) and early.code == "invalid_window" and "2005-01-01" in early.message
    assert len(hub.calls) == 1


def test_bea_nipa_line_must_match_exactly_once(tmp_path):
    recorded = capture("usgov_bea_real_gdp_growth")
    for call in recorded["calls"]:
        call["response"]["data"]["rows"] = [r for r in call["response"]["data"]["rows"] if r[0] != "Gross domestic product"]
    data_source, _ = source(tmp_path, exact_replay(recorded), clock=recorded["clock"])
    result = data_source.get(recorded["series"], **recorded["request"])
    assert isinstance(result, ds.DataError) and result.code == "not_found" and "Gross domestic product" in result.message


# usgov publishers (RPT-R2-9): a row names the agency behind its recipe, not the gateway

@pytest.mark.parametrize("name, publisher", [
    ("usgov_eia_sales_us_com_paged", "U.S. Energy Information Administration (EIA)"),
    ("usgov_bea_real_gdp_growth", "U.S. Bureau of Economic Analysis (BEA)"),
    ("usgov_bea_value_added_514", "U.S. Bureau of Economic Analysis (BEA)"),
    ("usgov_mts_deficit_2024", "U.S. Treasury Fiscal Data (Bureau of the Fiscal Service)"),
    ("usgov_debt_to_penny_daily", "U.S. Treasury Fiscal Data (Bureau of the Fiscal Service)"),
    ("usgov_spending_total_fy", "USAspending.gov (U.S. Department of the Treasury)"),
])
def test_usgov_rows_name_the_agency_that_publishes_them(tmp_path, monkeypatch, name, publisher):
    result, _hub, _recorded = replay(tmp_path, name, monkeypatch)
    assert isinstance(result, ds.Series), result
    assert result.provider == "usgov" and result.provider_name == publisher
    assert f"Provider: {publisher} · Series: {result.series}" in ds.render_series_page(result)
    assert ds.Series.from_dict(result.to_dict()).provider_name == publisher
    assert result.provider_name != ds.catalog.PROVIDERS["usgov"]["name"]  # never the gateway's list of agencies


def test_publisher_names_of_other_providers_and_stored_usgov_rows_are_unchanged():
    for provider, meta in ds.catalog.PROVIDERS.items():
        if provider != "usgov":
            assert ds.catalog.provider_name(provider, "ANY") == meta["name"]
    assert ds.catalog.provider_name("usgov", "not/a_recipe") == ds.catalog.PROVIDERS["usgov"]["name"]
    # A row stored before the change keeps its stored name, and its page keeps its bytes.
    stored = json.loads((FIXTURES / "real" / "stored_v2" / "usgov_treasury_debt_to_penny.json").read_text())
    series = ds.Series.from_dict(stored["row"])
    assert series.provider_name == "U.S. Government Open Data (Treasury Fiscal Data, USAspending)"
    assert ds.render_series_page(series) == stored["head_page"]


# FRED long daily windows (P-FREDCAP)

@pytest.mark.parametrize("name,route", [("fred_dgs10_long_split_api", "mcp"), ("fred_dgs10_long_split_csv", "fred_csv")])
def test_fred_long_daily_window_uses_server_monthly_aggregation(tmp_path, name, route):
    result, hub, recorded = replay(tmp_path, name)
    assert isinstance(result, ds.Series), result
    assert result.route == route and result.frequency == "M" and result.provenance["native_frequency"] == "D"
    aggregation = result.provenance["server_aggregation"]
    assert aggregation["method"] == "avg" and aggregation["through"] == "2024-09-30"
    assert ("frequency=m&aggregation_method=avg" if route == "mcp" else "fq=Monthly&fam=avg") in aggregation["request"]
    dates = [o.date for o in result.observations]
    assert dates[0] == "2010-01-01" and dates[-1] == "2026-10-01" and len(dates) == len(set(dates)) == 202
    by_date = {o.date: o for o in result.observations}
    assert by_date["2010-01-01"].value == 3.73 and by_date["2024-09-01"].value == 3.72
    periods = result.provenance["periods"]
    assert periods["2024-09-01"]["complete"] is True and periods["2026-09-01"]["complete"] is True
    assert periods["2026-10-01"]["complete"] is False and ds.observation_kind(by_date["2026-10-01"], result) == "partial"
    assert ds.latest_observed(result).date == "2026-09-01"
    assert result.provenance["latest_daily"]["date"] == "2026-10-08"
    assert result.notes.startswith("Daily data aggregated to monthly means") and "FRED's own monthly means" in result.notes


def test_fred_uncatalogued_daily_overflow_is_refetched_as_months_plus_days(tmp_path):
    recorded = capture("fred_dgs10_long_split_api")
    daily = copy.deepcopy(recorded["calls"][0]["response"])
    monthly = copy.deepcopy(recorded["calls"][1]["response"])
    for payload in (daily, monthly):
        payload["series_id"] = "DGS20"
    overflow = {**copy.deepcopy(daily), "total_observations": 5200, "data": daily["data"]}
    def handler(provider, tool, args):
        if tool == "fred_search":  # geography tags of an uncatalogued id
            return {"total_results": 0, "results": []}
        if args.get("frequency") == "m":
            return monthly
        return overflow if args["observation_start"] == "2005-01-01" else daily
    data_source, hub = source(tmp_path, handler, clock=recorded["clock"])
    assert ds.catalog.lookup("fred:DGS20") is None
    result = data_source.get("fred:DGS20", start="2005-01-01")
    assert isinstance(result, ds.Series), result
    series_calls = [c[2] for c in hub.calls if c[1] == "fred_get_series"]
    assert [c["observation_start"] for c in series_calls] == ["2005-01-01", "2024-10-01", "2005-01-01"]
    assert series_calls[2]["aggregation_method"] == "avg" and result.frequency == "M"
    assert [c[1] for c in hub.calls].count("fred_search") == 1 and result.geography == ""
    short = data_source.get("fred:DGS20", start="2025-01-01")
    assert isinstance(short, ds.Series) and "server_aggregation" not in short.provenance


def _months_between(rows, start, end):
    return [row for row in rows if start <= row["date"] <= end]


@pytest.mark.parametrize("route", ["mcp", "fred_csv"])
def test_fred_daily_default_window_holds_ten_years_with_server_months(tmp_path, route):
    # Without start, a curated daily series keeps the same 24-month native page as before and adds
    # FRED's own monthly aggregates back to the ten-year default (an empirical base rate needs
    # >= 30 h-step samples); every page stays bounded.
    recorded = capture("fred_dgs10_long_split_api" if route == "mcp" else "fred_dgs10_long_split_csv")
    native, monthly = recorded["calls"][0], recorded["calls"][1]

    def handler(provider, tool, args):
        if args.get("frequency") == "m":
            payload = copy.deepcopy(monthly["response"])
            payload["data"] = _months_between(payload["data"], args["observation_start"], args["observation_end"])
            payload["total_observations"] = len(payload["data"])
            return payload
        assert args == native["args"], args
        return native["response"]

    def fetch(url, **kw):
        if "fq=Monthly" not in url:
            assert url == native["args"]["url"], url
            return native["response"].encode()
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        header, *rows = monthly["response"].splitlines()
        kept = [line for line in rows if params["cosd"] <= line.split(",")[0] <= params["coed"]]
        return "\n".join([header, *kept, ""]).encode()

    env = {"FRED_API_KEY": ""} if route == "fred_csv" else {}
    data_source, hub = source(tmp_path, handler, clock=recorded["clock"], env=env, http_get=fetch)
    result = data_source.get("fred:DGS10")
    assert isinstance(result, ds.Series), result
    assert result.route == route and result.frequency == "M" and result.provenance["native_frequency"] == "D"
    aggregation = result.provenance["server_aggregation"]
    assert aggregation["method"] == "avg" and aggregation["through"] == "2024-09-30"
    if route == "mcp":
        older = [c[2] for c in hub.calls if c[2].get("frequency") == "m"]
        assert len(hub.calls) == 2 and [(c["observation_start"], c["observation_end"]) for c in older] == [
            ("2016-10-01", "2024-09-30")]
    else:
        assert "cosd=2016-10-01&coed=2024-09-30&fq=Monthly&fam=avg" in aggregation["request"]
    dates = [o.date for o in result.observations]
    assert dates[0] == "2016-10-01" and dates[-1] == "2026-10-01" and len(dates) == len(set(dates)) == 121
    assert result.provenance["periods"]["2016-10-01"]["complete"] is True
    assert ds.observation_kind(result.observations[-1], result) == "partial"
    assert ds.latest_observed(result).date == "2026-09-01" and result.provenance["latest_daily"]["date"] == "2026-10-08"
    assert sum(ds.observation_kind(o, result) == "observed" for o in result.observations) == 120
    # Bounded pages: 96 server-aggregated months plus the 25 months of the 528-day native page.
    assert sum(o.date < "2024-10-01" for o in result.observations) == 96
    assert len(native["response"]["data"] if route == "mcp" else native["response"].splitlines()[1:]) == 528


def test_daily_default_windows_by_provider(tmp_path):
    data_source, hub = source(tmp_path, lambda *a: pytest.fail("no call expected"))
    today = "2026-10-12"
    windows = {sid: data_source._request(sid, None, None, transform, 240)
               for sid, transform in (("fred:DFEDTARU", None), ("fred:T10YIE#yoy", None),
                                      ("usgov:treasury/debt_to_penny", None))}
    # FRED daily: ten years, native days only for the latest 24 months (end-of-period targets too).
    assert (windows["fred:DFEDTARU"]["start"], windows["fred:DFEDTARU"]["end"]) == ("2016-10-01", today)
    assert ds.DataSources._fred_split(windows["fred:DFEDTARU"]) == "2024-10-01"
    assert ds._aggregation(windows["fred:DFEDTARU"]) == "eop"
    assert windows["fred:T10YIE#yoy"]["fetch_start"] == "2015-10-01"
    assert ds.DataSources._fred_split(windows["fred:T10YIE#yoy"]) == "2024-10-01"
    # Treasury has no server-side aggregation: its daily default stays two years of bounded pages.
    assert windows["usgov:treasury/debt_to_penny"]["start"] == "2024-10-01"
    # An explicit window shorter than one page is still one native request.
    explicit = data_source._request("fred:DGS10", "2020-01-01", None, None, 240)
    assert ds.DataSources._fred_split(explicit) == ""
    assert hub.calls == []


# FRED and BLS key rejection, FRED unknown series

@pytest.mark.parametrize("state,error", [
    ("unavailable", "not built: run npm run setup:datamcps (missing fred-mcp-server-main/build/index.js)"),
    ("failed", "circuit open: server exited unexpectedly (exit code 1)"),
])
def test_fred_server_down_with_a_key_uses_the_keyless_csv(tmp_path, state, error):
    fetched = []
    def fetch(url, **kw):
        fetched.append(url)
        native = url.split("id=")[1].split("&")[0]
        return f"observation_date,{native}\n2024-01-01,4.0\n".encode()
    data_source, hub = source(tmp_path, lambda *a: CallResult(False, "", error, 0.0), http_get=fetch)
    hub.status = lambda: {p: {"state": state if p == "fred" else "ready", "error": error} for p in ds.PROVIDERS}
    for sid in ("fred:UNRATE", "fred:IPN31152S"):  # curated and uncurated alike: the CSV needs no server
        result = data_source.get(sid, start="2024-01-01", end="2024-01-31")
        assert isinstance(result, ds.Series) and result.route == "fred_csv", result
        assert result.provenance["fallback_reason"] == "provider_unavailable"
    assert len(fetched) == 2


def test_fred_series_does_not_exist_is_unknown_series(tmp_path):
    text = capture("fred_errors_and_search")["errors"]["unknown_series"]
    data_source, _ = source(tmp_path, lambda *a: CallResult(False, "", text, 0.0))
    result = data_source.get("fred:NOSUCHSERIES123")
    assert isinstance(result, ds.DataError) and result.code == "unknown_series" and result.retryable is False
    assert "data_search" in result.message


def test_fred_rejected_key_switches_the_process_to_csv(tmp_path):
    text = capture("fred_errors_and_search")["errors"]["key_invalid"]
    fetched = []
    def fetch(url, **kw):
        fetched.append(url)
        return b"observation_date,UNRATE\n2024-01-01,4.0\n2024-02-01,4.1\n"
    data_source, hub = source(tmp_path, lambda *a: CallResult(False, "", text, 0.0), http_get=fetch)
    assert data_source.providers()["fred"] == "ready"
    first = data_source.get("fred:UNRATE", start="2024-01-01", end="2024-02-29")
    assert isinstance(first, ds.Series) and first.route == "fred_csv" and first.provenance["fallback_reason"] == "key_invalid"
    assert data_source.providers()["fred"] == "key_invalid" and data_source.enabled()
    # Uncurated ids use the CSV too once the key is known bad; no further API calls.
    other, _ = source(tmp_path / "other", lambda *a: pytest.fail("rejected key must not be retried"), http_get=fetch)
    second = other.get("fred:UNRATE", start="2024-01-01", end="2024-01-31")
    assert isinstance(second, ds.Series) and len(hub.calls) == 1 and len(fetched) == 2
    assert other.providers()["fred"] == "key_invalid"
    fresh, _ = source(tmp_path / "fresh", lambda *a: pytest.fail("no call"), env={"FRED_API_KEY": "another-fred-key-9876"})
    assert fresh.providers()["fred"] == "ready"


# FRED geography of series outside the catalog (captured 2026-10-13)

def test_search_discovered_fred_national_series_is_labelled_united_states(tmp_path):
    result, hub, recorded = replay(tmp_path, "fred_search_discovered_national_geography")
    assert isinstance(result, ds.Series), result
    assert ds.catalog.lookup(recorded["series"]) is None and result.title == recorded["captured_result"]["title"]
    assert [c[1] for c in hub.calls] == ["fred_get_series", "fred_search"]
    assert hub.calls[1][2] == {"search_text": "CORESTICKM159SFRBATL", "search_type": "series_id",
                               "tag_names": "nation;usa", "limit": 25}
    assert result.geography == "USA" and result.provenance["geography_basis"] == "FRED series tags: nation, usa"
    label = "Sticky Price Consumer Price Index less Food and Energy — United States"
    assert ds.series_label(result) == label == recorded["captured_result"]["label"]
    assert ds.series_label(result, "zh") == "Sticky Price Consumer Price Index less Food and Energy — 美国"
    stored = ds.Series.from_dict(json.loads(json.dumps(result.to_dict())))
    assert ds.series_label(stored) == label and ds.render_series_page(stored).startswith(f"# {label}\n")
    assert "Geography: USA" in ds.render_series_page(stored)


def test_fred_geography_stays_unknown_unless_fred_tags_confirm_it(tmp_path):
    result, hub, recorded = replay(tmp_path, "fred_search_discovered_untagged_geography")
    assert isinstance(result, ds.Series) and [c[1] for c in hub.calls] == ["fred_get_series", "fred_search"]
    assert result.geography == "" and "geography_basis" not in result.provenance
    assert ds.series_label(result) == "Nikkei Stock Average, Nikkei 225"
    # A failed tag lookup never fails the fetched series.
    payload = recorded["calls"][0]["response"]

    def failing(provider, tool, args):
        return CallResult(False, "", "Request timed out", 0.0) if tool == "fred_search" else payload

    data_source, _ = source(tmp_path / "failed", failing, clock=recorded["clock"])
    failed = data_source.get(recorded["series"], **recorded["request"])
    assert isinstance(failed, ds.Series) and failed.route == "mcp" and failed.geography == "", failed
    # Curated ids keep their catalog geography without a lookup; the keyless CSV route has no tags.
    curated, hub = replay(tmp_path / "curated", "fred_unrate_2024")[:2]
    assert curated.geography == "USA" and [c[1] for c in hub.calls] == ["fred_get_series"]
    keyless, hub = source(tmp_path / "csv", lambda *a: pytest.fail("no MCP call on the keyless route"),
                          env={"FRED_API_KEY": ""},
                          http_get=lambda url, **kw: b"observation_date,NIKKEI225\n2026-09-01,44000.1\n")
    csv_row = keyless.get(recorded["series"], start="2026-09-01", end="2026-09-01")
    assert isinstance(csv_row, ds.Series) and csv_row.route == "fred_csv" and csv_row.geography == "" and hub.calls == []


def test_fred_tag_lookup_never_costs_the_fetched_series_its_deadline(tmp_path):
    recorded = capture("fred_search_discovered_national_geography")
    payload = recorded["calls"][0]["response"]
    timeouts = []

    class StalledSearchHub(Hub):
        def call(self, provider, tool, args, **kw):
            if tool != "fred_search":
                return super().call(provider, tool, args, **kw)
            timeouts.append(kw.get("timeout"))
            time.sleep(min(kw.get("timeout") or 1.0, 1.0))  # a stalled search answers at its timeout
            return CallResult(False, "", "Request timed out", 0.0)

    data_source = ds.DataSources(StalledSearchHub(lambda *a: payload), env={"DATA_SOURCES_ENABLED": "true", **KEYS},
                                 cache_dir=tmp_path / "cache", clock=lambda: recorded["clock"])
    result = data_source.get(recorded["series"], **recorded["request"], deadline_s=0.8)
    assert isinstance(result, ds.Series) and result.geography == "", result
    assert len(timeouts) == 1 and 0 < timeouts[0] <= 0.41


def test_bls_rejected_key_respawns_keyless_and_continues(tmp_path):
    rejected = capture("bls_messages_and_rejected_key")["calls"][1]["response"]
    ok = capture("bls_ces_lns_2025_2026")
    responses = [rejected, ok["calls"][0]["response"]]
    data_source, hub = source(tmp_path, lambda *a: responses.pop(0), clock=ok["clock"])
    assert data_source.providers()["bls"] == "ready"
    result = data_source.get_many(["bls:CES0000000001", "bls:LNS14000000"], deadline_s=30, start="2025-01-01")
    assert all(isinstance(v, ds.Series) for v in result.values()), result
    assert hub.restarted == [("bls", ("BLS_API_KEY",))] and len(hub.calls) == 2
    assert data_source.providers()["bls"] == "key_invalid" and data_source.enabled()
    quota = json.loads((tmp_path / "cache" / "bls-quota.json").read_text())
    assert quota["count"] == 1  # the keyless retry is counted against the keyless daily quota


def test_bls_rejected_key_without_respawn_support_reports_key_invalid(tmp_path):
    rejected = capture("bls_messages_and_rejected_key")["calls"][1]["response"]
    data_source, hub = source(tmp_path, lambda *a: rejected)
    hub.restart_without = None
    result = data_source.get("bls:LNS14000000")
    assert isinstance(result, ds.DataError) and result.code == "key_invalid" and "key:[redacted]" in result.message.lower()


def test_bls_unpublished_year_and_invalid_id_do_not_fail_the_batch(tmp_path):
    recorded = capture("bls_messages_and_rejected_key")["calls"][0]
    data_source, hub = source(tmp_path, lambda *a: recorded["response"])
    result = data_source.get_many(["bls:LNS14000000", "bls:NOSUCHSERIES1"], deadline_s=30,
                                  start="2026-01-01", end="2027-12-31")
    assert hub.calls[0][2] == recorded["args"]
    good, bad = result["bls:LNS14000000"], result["bls:NOSUCHSERIES1"]
    assert isinstance(good, ds.Series) and good.observations[-1].date == "2026-09-01"
    assert good.provenance["chunks"][0]["notices"] == ["No Data Available for Series LNS14000000 Year: 2027"]
    assert isinstance(bad, ds.DataError) and bad.code == "unknown_series"


def test_bls_catalog_metadata_notice_does_not_fail_the_batch(tmp_path):
    # Live 2026-10-12 (datamcp_smoke): a batch with JOLTS ids answered REQUEST_SUCCEEDED plus
    # "Unable to get Catalog Data for series JTS000000000000000JOL" and was rejected whole.
    payload = copy.deepcopy(capture("bls_messages_and_rejected_key")["calls"][0]["response"])
    payload["message"] = ["Unable to get Catalog Data for series LNS14000000"]
    payload["Results"]["series"] = payload["Results"]["series"][:1]
    data_source, _ = source(tmp_path, lambda *a: payload)
    result = data_source.get("bls:LNS14000000", start="2026-01-01", end="2026-12-31")
    assert isinstance(result, ds.Series) and result.title == ds.catalog.lookup("bls:LNS14000000").title
    assert result.provenance["chunks"][0]["notices"] == ["Unable to get Catalog Data for series LNS14000000"]


def test_bls_unexpected_message_still_fails_closed(tmp_path):
    payload = copy.deepcopy(capture("bls_messages_and_rejected_key")["calls"][0]["response"])
    payload["message"] = ["Year range has been reduced to the system-allowed limit of 10 years."]
    data_source, _ = source(tmp_path, lambda *a: payload)
    result = data_source.get("bls:LNS14000000", start="2026-01-01", end="2027-12-31")
    assert isinstance(result, ds.DataError) and "warnings" in result.message


# BIS windows without observations (captured 2026-10-13)

def tool_error_replay(recorded, *, clipped_only=False):
    """The recorded BIS tool errors as the hub returns them: the isError text plus the hub's
    clipped reason (or the clipped reason alone, as a hub without the text would)."""
    def handler(provider, tool, args):
        for call in recorded["calls"] + recorded["other_calls"]:
            if (call["provider"], call["tool"], call["args"]) == (provider, tool, json.loads(json.dumps(args))):
                if clipped_only:
                    return CallResult(False, "", call["error"], 0.0)
                return CallResult(False, call["text"], call["error"], 0.0, is_tool_error=True)
        raise AssertionError(f"unrecorded request {provider}.{tool} {args}")
    return handler


@pytest.mark.parametrize("clipped_only", [False, True])
def test_bis_unpublished_period_is_not_found_and_the_monitor_waits(tmp_path, clipped_only):
    recorded = capture("bis_empty_window_and_unknown_key")
    data_source, hub = source(tmp_path, tool_error_replay(recorded, clipped_only=clipped_only), clock=recorded["clock"])
    result = data_source.get(recorded["series"], **recorded["request"])
    assert isinstance(result, ds.DataError) and result.code == "not_found" and result.retryable is False, result
    assert result.message.startswith("BIS publishes this series but has no observations from 2026-09-01 to 2026-09-30; "
                                     "its most recent observation is 2026-08.")
    assert result.message.endswith(ds._HINTS["not_found"]) and "user_error" not in result.message
    assert len(hub.calls) == 1
    import scripts.resolution_monitor as monitor
    status = monitor._unusable_fetch_status(result, "2026-09-30", "M", "2026-10-13")
    assert status["status"] == "pending" and "not yet published" in status["reason"]


def test_bis_future_window_keeps_the_bis_note_and_unknown_key_is_unknown_series(tmp_path):
    recorded = capture("bis_empty_window_and_unknown_key")
    data_source, _ = source(tmp_path, tool_error_replay(recorded), clock=recorded["clock"])
    future = data_source.get("bis:WS_CBPOL/M.US", start="2026-11-01", end="2026-11-30")
    assert isinstance(future, ds.DataError) and future.code == "not_found", future
    assert future.message == ("BIS publishes this series but has no observations from 2026-11-01 to 2026-11-30; its most "
                              "recent observation is 2026-09; BIS note: From 19 Dec 1985 onwards: mid-point of the Federal "
                              "Reserve target rate. " + ds._HINTS["not_found"])
    unknown = data_source.get("bis:WS_CBPOL/M.ZZ", start="2025-01-01", end="2025-12-31")
    assert isinstance(unknown, ds.DataError) and unknown.code == "unknown_series" and unknown.retryable is False, unknown
    assert unknown.message == ("BIS has never published a series under this key; the key's positions are FREQ.REF_AREA. "
                               + ds._HINTS["unknown_series"])


def test_other_bis_tool_errors_keep_their_classification(tmp_path):
    generic = ('user_error: BIS returned no data for flow_ref "BIS,WS_CBPOL,1.0" with key "M.US". Either the flow_ref '
               "is wrong — get a valid one from search_dataflows or list_curated_flows — or the dimension key filtered "
               "everything out.")
    for text, code, retryable in ((generic, "not_found", False), ("BIS data error: 503 — Service Unavailable", "provider_unavailable", True)):
        data_source, _ = source(tmp_path / code, lambda *a, t=text: CallResult(False, t, t[:300], 0.0, is_tool_error=True))
        result = data_source.get("bis:WS_CBPOL/M.US", start="2026-01-01", end="2026-03-31")
        assert isinstance(result, ds.DataError) and (result.code, result.retryable) == (code, retryable), result


# Fiscal years (P-USGOV)

def test_fiscal_year_is_complete_only_after_late_reporting_settles(tmp_path):
    payload = json.loads((FIXTURES / "provider_responses.json").read_text())["spending"]
    data_source, _ = source(tmp_path, lambda *a: payload)
    result = data_source.get("usgov:spending/total", start="2022-10-01")
    periods = result.provenance["periods"]
    assert periods["2024-10-01"]["complete"] is True      # FY2025 ended 2025-09-30
    assert periods["2025-10-01"]["complete"] is False     # FY2026 ended 12 days before the clock
    assert "FY2026 (partial)" in ds.render_series_page(result)
    later, _ = source(tmp_path / "later", lambda *a: payload, clock=NOW + 120 * 86400)
    assert later.get("usgov:spending/total", start="2022-10-01").provenance["periods"]["2025-10-01"]["complete"] is True


# Search flow (P-SEARCH, P-WBGEO, V3-M2)

def search_handler(fred_rows=None, wb=None, seen=None):
    def handler(provider, tool, args):
        if seen is not None:
            seen.append((provider, tool, dict(args)))
        if tool == "fred_search":
            return {"results": fred_rows or []}
        if tool == "data360_search_indicators":
            return wb or {"indicators": []}
        if tool == "search_dataflows":
            return {"dataflows": []}
        return {"data": {"items": []}}
    return handler


def test_weak_catalog_hits_no_longer_hide_live_provider_search(tmp_path):
    fred_rows = capture("fred_errors_and_search")["calls"][0]["response"]["results"]
    seen = []
    data_source, _ = source(tmp_path, search_handler(fred_rows, seen=seen))
    hits = data_source.search("半导体出口", limit=6)
    fred = [c for c in seen if c[1] == "fred_search"]
    assert fred and fred[0][2]["search_text"] == "semiconductor exports"
    assert hits[0].series == "fred:IY3344" and hits[0].provider == "fred"
    assert all(h.note.lower() not in ("undefined", "null") for h in hits)


def test_strong_catalog_hits_answer_without_provider_calls(tmp_path):
    data_source, hub = source(tmp_path, lambda *a: pytest.fail("no provider call expected"))
    hits = data_source.search("US unemployment rate", limit=1)
    assert hits and hits[0].series in ("fred:UNRATE", "bls:LNS14000000") and hub.calls == []


@pytest.mark.parametrize("query,countries", [
    ("urban population growth", "WLD"), ("silicon carbide wafer exports", "WLD"),
    ("electricity usage per capita", "WLD"), ("fedex shipping volumes", "WLD"),
    ("urban population growth in the United States and China", "CHN;USA"),
])
def test_data360_search_countries_come_from_whole_word_geographies(tmp_path, query, countries):
    seen = []
    data_source, _ = source(tmp_path, search_handler(seen=seen), env={"FRED_API_KEY": ""})
    data_source.search(query, provider="wb", limit=6)
    assert [c[2]["required_country"] for c in seen if c[1] == "data360_search_indicators"] == [countries]


def test_data360_hits_per_requested_geography_and_world_aggregate(tmp_path):
    calls = {c["args"]["required_country"] if "required_country" in c["args"] else "": c["response"]
             for c in capture("wb_search_geographies")["calls"]}
    data_source, _ = source(tmp_path, search_handler(wb=calls["USA;CHN"]))
    hits = [h.series for h in data_source.search("urban population growth United States China", provider="wb", limit=12)]
    assert "wb:WB_WDI_SP_URB_GROW/CHN" in hits and "wb:WB_WDI_SP_URB_GROW/USA" in hits
    data_source, _ = source(tmp_path / "wld", search_handler(wb=calls["WLD"]))
    world = data_source.search("battery storage capacity", provider="wb", limit=6)
    live = [h for h in world if ds.catalog.lookup(h.series) is None]
    # Electricity use per capita is the only fetchable world hit, and it measures no battery storage.
    assert [h.series for h in live] == ["wb:WB_WDI_EG_USE_ELEC_KH_PC/WLD"]
    assert live[0].note.startswith(ds.OFF_CONCEPT_NOTE)
    # Non-allowlisted Data360 databases (WB_CSC, OWID, ...) are not fetchable ids.
    assert all(h.series.endswith("/WLD") and h.series.split(":")[1].startswith(("WB_WDI_", "IMF_WEO_", "WB_GEP_"))
               for h in live)


# Search relevance (live discovery captured 2026-10-14 for the agent-usage audit questions)

SEARCH_CAPTURE = capture("search_relevance_2026-10-14")
SEARCH_CLOCK = 1791936000.0  # 2026-10-14T00:00:00Z


def search_replay(*, any_limit=False):
    """Answers the recorded discovery requests; ``any_limit`` also accepts another ``limit``."""
    def same(recorded, args):
        if any_limit:
            recorded, args = ({k: v for k, v in a.items() if k != "limit"} for a in (recorded, args))
        return recorded == args

    def handler(provider, tool, args):
        args = json.loads(json.dumps(args))
        for call in SEARCH_CAPTURE["calls"]:
            if (call["provider"], call["tool"]) == (provider, tool) and same(call["args"], args):
                return call["response"]
        raise AssertionError(f"unrecorded request {provider}.{tool} {args}")
    return handler


def test_search_lists_discovery_hits_sharing_no_concept_last(tmp_path):
    # Agents searched "global semiconductor sales" (audit Q5) and got arms exports and mobile
    # subscriptions first: Data360 matches words loosely.  They now follow every hint that
    # names semiconductors, marked as not matching.
    data_source, hub = source(tmp_path, search_replay(), clock=SEARCH_CLOCK)
    hits = data_source.search("global semiconductor sales", limit=6)
    assert [c[1] for c in hub.calls] == ["fred_search", "data360_search_indicators", "search_dataflows",
                                         "treasury_search_datasets"]
    assert [h.series for h in hits[:4]] == ["fred:IPG3344S", "fred:CAPUTLG3344S", "fred:PCU33443344",
                                            "fred:NASDAQSOX"]
    assert not any(h.note.startswith(ds.OFF_CONCEPT_NOTE) for h in hits[:4])
    every, _ = source(tmp_path / "all", search_replay(any_limit=True), clock=SEARCH_CLOCK)
    late = every.search("global semiconductor sales", limit=20)[4:]
    assert [h.series for h in late[:4]] == ["wb:WB_WDI_MS_MIL_XPRT_KD/WLD", "wb:WB_WDI_TX_VAL_TECH_CD/WLD",
                                            "wb:WB_WDI_IT_CEL_SETS/WLD", "wb:WB_WDI_MS_MIL_MPRT_KD/WLD"]
    assert all(h.note.startswith(ds.OFF_CONCEPT_NOTE) for h in late)
    assert late[0].note == ds.OFF_CONCEPT_NOTE + "; Discovery metadata; fetch before citing"


@pytest.mark.parametrize("query,first,off_concept", [
    ("new energy vehicle sales share", ["fred:TOTALSA"],
     {"wb:WB_WDI_EG_USE_COMM_CL_ZS/WLD", "wb:WB_WDI_EG_FEC_RNEW_ZS/WLD", "fred:RSAFS"}),
    ("US electricity retail price", ["usgov:eia/electricity_price/US.ALL", "usgov:eia/electricity_price/US.COM",
                                     "usgov:eia/electricity_price/US.IND", "usgov:eia/electricity_price/US.RES",
                                     "fred:APU000072610"],
     {"fred:APU0000703112", "fred:APU0000708111", "fred:APU000074714"}),
    ("euro area deposit facility rate", ["fred:ECBDFR", "bis:WS_CBPOL/M.XM"],
     {"wb:WB_WDI_FD_RES_LIQU_AS_ZS/EMU", "wb:WB_WDI_PA_NUS_FCRF/EMU", "bis:WS_EER/M.R.B.XM",
      "usgov:treasury/fx/Euro Zone-Euro"}),
    ("fed funds rate history", ["fred:FEDFUNDS", "bis:WS_CBPOL/M.US"], {"wb:WB_WDI_FR_INR_LEND/USA", "fred:SOFR"}),
])
def test_audit_searches_lead_with_series_of_the_asked_concept(tmp_path, query, first, off_concept):
    data_source, _ = source(tmp_path, search_replay(any_limit=True), clock=SEARCH_CLOCK)
    hits = data_source.search(query, limit=50)
    ids = [h.series for h in hits]
    assert ids[:len(first)] == first, ids
    marked = {h.series for h in hits if h.note.startswith(ds.OFF_CONCEPT_NOTE)}
    assert off_concept <= marked and not marked & set(first), marked
    # Marked results come after every unmarked one.
    flags = [h.note.startswith(ds.OFF_CONCEPT_NOTE) for h in hits]
    assert flags == sorted(flags)


def test_a_chinese_query_is_judged_through_the_glossary(tmp_path):
    china = next(c["response"] for c in SEARCH_CAPTURE["calls"]
                 if c["tool"] == "data360_search_indicators" and c["args"]["required_country"] == "CHN")
    seen = []
    data_source, _ = source(tmp_path, search_handler(wb=china, seen=seen), clock=SEARCH_CLOCK)
    hits = data_source.search("中国新能源汽车销量占比", limit=20)
    assert [c[2]["required_country"] for c in seen if c[1] == "data360_search_indicators"] == ["CHN"]
    assert next(c[2]["search_text"] for c in seen if c[1] == "fred_search") == "China electric vehicle sales share"
    live = [h for h in hits if h.series.startswith("wb:")]
    assert live and all(h.note.startswith(ds.OFF_CONCEPT_NOTE) for h in live)  # energy and CO2 shares
    assert hits[0].series == "fred:TOTALSA" and not hits[0].note.startswith(ds.OFF_CONCEPT_NOTE)


def test_keyed_recipes_are_not_discovered_without_their_key(tmp_path):
    data_source, _ = source(tmp_path, search_handler(), env={"EIA_API_KEY": ""})
    assert not any(h.series.startswith("usgov:eia/") for h in data_source.search("electricity demand", limit=20))
    keyed, _ = source(tmp_path / "keyed", search_handler())
    assert any(h.series.startswith("usgov:eia/") for h in keyed.search("electricity demand", limit=20))


def test_data360_empty_result_is_not_logged_as_unavailable(tmp_path, caplog):
    empty = {"indicators": [], "error": "No indicators found for: 'data center electricity demand'"}
    data_source, _ = source(tmp_path, search_handler(wb=empty), env={"FRED_API_KEY": ""})
    with caplog.at_level("WARNING"):
        assert data_source.search("data center electricity demand", provider="wb", limit=6) is not None
    assert "Data360 search unavailable" not in caplog.text
    broken = {"indicators": [], "error": "Data360 API error 503"}
    data_source, _ = source(tmp_path / "broken", search_handler(wb=broken), env={"FRED_API_KEY": ""})
    with caplog.at_level("WARNING"):
        data_source.search("data center electricity demand", provider="wb", limit=6)
    assert "Data360 search unavailable" in caplog.text


# Fixture index

def test_fixture_readme_indexes_every_real_capture():
    readme = (FIXTURES / "README.md").read_text()
    real = FIXTURES / "real"
    for path in sorted(real.iterdir()):
        assert (f"`{path.name}/" if path.is_dir() else f"`{path.name}`") in readme, path.name
    for folder in ("agent_usage", "downstream", "gateway", "legacy", "v3_engine"):
        for path in sorted((real / folder).glob("*.json")):
            assert f"`{folder}/{path.name}`" in readme, path
