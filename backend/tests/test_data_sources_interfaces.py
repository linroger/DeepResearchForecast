"""Shared official-data interfaces (fix contract §1.1, §1.3, §1.5 data-layer side).

DataError reason codes and hints, display helpers, the stored-row display
policy gate (pages of rows fetched under policy <= 2 re-render byte for byte),
optional catalog fields, KIQ links and caller deadlines. Runs under plain
pytest; bridge modules load by bare name from deerflow_bridge/.
"""
import json
import os
import sys
import threading
import time
import urllib.error
from pathlib import Path

import pytest

_BRIDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import data_sources as ds  # noqa: E402
from data_mcp import CallResult  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "data_sources"
STORED_V2 = sorted((FIXTURES / "real" / "stored_v2").glob("*.json"))
NOW = 1791763200.0  # 2026-10-12T00:00:00Z
# Real FRED tool failure text: datamcps/fred-mcp-server-main src/common/fred-client.ts:197
# wrapped by src/fred/series.ts:100, with the body FRED returns for a burst.
FRED_429 = ('Failed to retrieve series data: FRED API error (429): '
            '{"error_code":429,"error_message":"Too Many Requests.  Exceeded Rate Limit"}')


class Hub:
    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def call(self, provider, tool, args, **kw):
        self.calls.append((provider, tool, dict(args), dict(kw)))
        data = self.handler(provider, tool, args, kw)
        return data if isinstance(data, CallResult) else CallResult(True, json.dumps(data), None, 0.0)

    def status(self):
        return {p: {"state": "ready", "error": None} for p in ds.PROVIDERS}

    def start(self, names, **kw):
        pass

    def close(self):
        pass


def source(tmp_path, handler, **kw):
    env = {"DATA_SOURCES_ENABLED": "true", "FRED_API_KEY": "synthetic-key-123456"}
    env.update(kw.pop("env", {}))
    hub = Hub(handler)
    return ds.DataSources(hub, env=env, cache_dir=tmp_path / "cache", clock=lambda: NOW, **kw), hub


def fred_payload(native="UNRATE", rows=(("2024-01-01", 4.0), ("2024-02-01", 4.1))):
    return {"series_id": native, "title": "Unemployment Rate", "units": "Percent", "frequency": "Monthly",
            "seasonal_adjustment": "Seasonally Adjusted", "total_observations": len(rows), "data_offset": 0,
            "data_limit": 5000, "data": [{"date": d, "value": v} for d, v in rows]}


def stored(name):
    return json.loads((FIXTURES / "real" / "stored_v2" / name).read_text())


class Entry:
    """A curated catalog entry with the optional equivalence fields set explicitly."""

    def __init__(self, entry, fred_equivalent="", preferred=""):
        self._entry, self.fred_equivalent, self.preferred = entry, fred_equivalent, preferred

    def __getattr__(self, name):
        return getattr(self._entry, name)


@pytest.fixture
def no_equivalents(monkeypatch):
    """Generic hints regardless of which equivalents the live catalog curates."""
    real = ds.catalog.lookup
    monkeypatch.setattr(ds.catalog, "lookup", lambda sid: Entry(real(sid)) if real(sid) else None)


# §1.1 DataError taxonomy ---------------------------------------------------------------------

def test_data_error_carries_a_code_and_formats_the_agent_text():
    error = ds.DataError("fred:UNRATE", "x" * 400, True, "rate_limited")
    assert error.code == "rate_limited" and len(error.message) == 300
    assert error.unavailable_text().startswith("DATA_UNAVAILABLE[rate_limited]: ")
    assert ds.DataError("fred:UNRATE", "legacy positional form").code == "provider_error"
    assert ds.DataError("fred:UNRATE", "unknown class", False, "made_up").code == "provider_error"
    assert set(ds.DATA_ERROR_CODES) == set(ds._HINTS)


@pytest.mark.parametrize("kwargs, code", [
    ({"series": "fred:"}, "unknown_series"),
    ({"series": "nonsense"}, "unknown_series"),
    ({"series": "usgov:treasury/not_a_recipe"}, "unknown_recipe"),
    ({"series": "fred:UNRATE", "start": "2024-13-45"}, "invalid_input"),
    ({"series": "fred:UNRATE", "start": "2025-01-01", "end": "2024-01-01"}, "invalid_window"),
    ({"series": "fred:UNRATE", "transform": "log"}, "unsupported_transform"),
    ({"series": "fred:UNRATE#yoy", "transform": "pct"}, "invalid_input"),
    ({"series": "fred:UNRATE", "max_obs": 0}, "invalid_input"),
])
def test_request_validation_failures_have_codes_and_end_with_a_hint(tmp_path, kwargs, code):
    api, hub = source(tmp_path, lambda *a: pytest.fail("validation must not reach a provider"))
    error = api.get(**kwargs)
    assert isinstance(error, ds.DataError) and error.code == code and error.retryable is False
    assert error.message.endswith(ds._HINTS[code]) and len(error.message) <= 300
    assert not hub.calls


def test_real_fred_429_text_is_retryable_rate_limit_without_secret(tmp_path, no_equivalents):
    def csv_429(url, timeout):
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
    api, _ = source(tmp_path, lambda *a: CallResult(False, "", FRED_429 + " api_key=synthetic-key-123456", 0.0, is_tool_error=True),
                    http_get=csv_429)
    error = api.get("fred:UNRATE", start="2024-01-01", end="2024-12-31")
    assert isinstance(error, ds.DataError) and error.code == "rate_limited" and error.retryable is True
    assert "synthetic-key-123456" not in error.message and error.message.endswith(ds._HINTS["rate_limited"])


@pytest.mark.parametrize("text, code, retryable", [
    ("tool call timed out after 60s", "timeout", True),
    ("data request deadline exceeded", "timeout", True),
    ("server still starting after 50s", "provider_unavailable", True),
    ("circuit open: process exited with code 1", "provider_unavailable", True),
    ("data hub is closed", "provider_unavailable", False),
    # FRED 400 body for an unregistered key (FRED API documentation).
    ("FRED API error (400): Bad Request.  The value for variable api_key is not registered.", "key_invalid", False),
    # BLS v2 status messages (REQUEST_NOT_PROCESSED); the key itself is redacted by _clean.
    ("BLS request failed: ['The key:0123abcd provided by the User is invalid.']", "key_invalid", False),
    ("BLS request failed: ['The key:[redacted] provided by the User is invalid.']", "key_invalid", False),
    ("BLS request failed: ['Request could not be serviced, as the daily threshold for total number of requests "
     "allocated to the user has been reached.']", "quota_exhausted", False),
    ("FRED API error (503): Service Unavailable", "provider_unavailable", True),
    ("FRED API error (404): Not Found", "not_found", False),
    ("Provider response truncated; narrow the requested window", "invalid_window", False),
    ("FRED response series identity mismatch", "provider_error", False),
])
def test_provider_and_hub_failure_text_classification(text, code, retryable):
    assert ds._failure_class(ValueError(text)) == (code, retryable)


def test_exception_types_classify_without_text():
    assert ds._failure_class(TimeoutError()) == ("timeout", True)
    assert ds._failure_class(ConnectionResetError("reset")) == ("provider_unavailable", True)
    assert ds._failure_class(urllib.error.HTTPError("u", 404, "Not Found", {}, None)) == ("not_found", False)
    assert ds._failure_class(urllib.error.HTTPError("u", 502, "Bad Gateway", {}, None)) == ("provider_unavailable", True)
    assert ds._failure_class(ds.DataFailure("x", "quota_exhausted")) == ("quota_exhausted", False)


def test_bls_keyless_quota_is_quota_exhausted_and_names_the_curated_fred_equivalent(tmp_path, monkeypatch):
    real = ds.catalog.lookup
    # Slice B ships bare FRED ids in fred_equivalent; other BLS ids carry none here.
    monkeypatch.setattr(ds.catalog, "lookup", lambda sid: Entry(real(sid), "UNRATE" if sid == "bls:LNS14000000" else "") if real(sid) else None)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "bls-quota.json").write_text(json.dumps({"day": "2026-10-12", "count": 20}))
    api, hub = source(tmp_path, lambda *a: pytest.fail("quota must block dispatch"), env={"BLS_API_KEY": ""})
    error = api.get("bls:LNS14000000", start="2024-01-01", end="2024-12-31")
    assert isinstance(error, ds.DataError) and error.code == "quota_exhausted" and error.retryable is False
    assert error.message.endswith("Use fred:UNRATE (same data on FRED) instead.")
    other = api.get("bls:CES0000000001", start="2024-01-01", end="2024-12-31")
    assert other.code == "quota_exhausted" and other.message.endswith(ds._HINTS["quota_exhausted"])


def test_omitted_bls_series_and_sec_recipe_have_codes(tmp_path):
    def bls(provider, tool, args, kw):
        return {"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": []}}
    api, _ = source(tmp_path, bls, env={"BLS_API_KEY": "synthetic"})
    omitted = api.get("bls:LNS14000000", start="2024-01-01", end="2024-12-31")
    assert omitted.code == "not_found" and omitted.message.endswith(ds._HINTS["not_found"])
    sec = api.get("usgov:sec/AAPL/Assets")
    assert sec.code == "unknown_recipe" and sec.retryable is False and sec.message.endswith(ds._HINTS["unknown_recipe"])


def test_rejected_bls_key_is_key_invalid_and_redacted(tmp_path, no_equivalents):
    # BLS v2 answers a rejected registration key with REQUEST_NOT_PROCESSED and echoes the key.
    def rejected(provider, tool, args, kw):
        return {"status": "REQUEST_NOT_PROCESSED", "responseTime": 21, "Results": {},
                "message": ["The key:0123abcd4567 provided by the User is invalid."]}
    api, _ = source(tmp_path, rejected, env={"BLS_API_KEY": "0123abcd4567"})
    error = api.get("bls:LNS14000000", start="2024-01-01", end="2024-12-31")
    assert error.code == "key_invalid" and error.retryable is False and "0123abcd4567" not in error.message
    assert error.message.endswith(ds._HINTS["key_invalid"])


def test_operational_failures_route_to_a_curated_faster_equivalent(tmp_path, monkeypatch):
    real = ds.catalog.lookup
    copper = "imf:PCPS/G001.PCOPP.USD.M"
    monkeypatch.setattr(ds.catalog, "lookup", lambda sid: Entry(real(sid), preferred="fred:PCOPPUSDM" if sid == copper else "") if real(sid) else None)
    api, _ = source(tmp_path, lambda *a: CallResult(False, "", "tool call timed out after 90s", 90.0))
    error = api.get(copper, start="2024-01-01", end="2024-12-31")
    assert error.code == "timeout" and error.message.endswith("Use fred:PCOPPUSDM (faster equivalent) or retry later.")
    assert api._hint(copper + "#yoy", "timeout") == "Use fred:PCOPPUSDM#yoy (faster equivalent) or retry later."
    assert api._hint(copper, "not_found") == ds._HINTS["not_found"]


def test_persistence_failure_manifest_carries_its_code(tmp_path):
    target = tmp_path / "not_a_dir"
    target.write_text("file")
    manifest = ds.write_dataset_files([], target)
    assert manifest["error"] and manifest["code"] == "persistence_failed"


# Caller deadlines ----------------------------------------------------------------------------

def test_get_deadline_bounds_the_provider_wait(tmp_path):
    def slow(provider, tool, args, kw):
        assert kw["timeout"] <= 0.3 and kw["deadline"] <= time.monotonic() + 0.3
        time.sleep(kw["timeout"])  # the hub honours the passed timeout
        return CallResult(False, "", "data request deadline exceeded", kw["timeout"])
    api, hub = source(tmp_path, slow)
    began = time.monotonic()
    error = api.get("fred:UNRATE", start="2024-01-01", end="2024-12-31", deadline_s=0.3)
    assert isinstance(error, ds.DataError) and error.code == "timeout" and error.retryable is True
    assert time.monotonic() - began < 2 and len(hub.calls) == 1
    assert getattr(api._local, "deadline", None) is None


def test_get_without_deadline_keeps_unbounded_hub_calls(tmp_path):
    api, hub = source(tmp_path, lambda *a: fred_payload())
    result = api.get("fred:UNRATE", start="2024-01-01", end="2024-12-31")
    assert isinstance(result, ds.Series) and hub.calls[0][3] == {}


@pytest.mark.parametrize("deadline, code", [(0, "timeout"), (-1, "timeout"), (float("nan"), "invalid_input"), ("5", "invalid_input")])
def test_invalid_or_spent_deadline_is_refused_before_provider_work(tmp_path, deadline, code):
    api, hub = source(tmp_path, lambda *a: pytest.fail("no provider work"))
    error = api.get("fred:UNRATE", deadline_s=deadline)
    assert isinstance(error, ds.DataError) and error.code == code and not hub.calls


def test_nested_get_deadline_never_extends_the_outer_one(tmp_path):
    seen = []
    def record(provider, tool, args, kw):
        seen.append(kw["deadline"])
        return fred_payload()
    api, _ = source(tmp_path, record)
    outer = time.monotonic() + 0.5
    api._local.deadline = outer
    try:
        assert isinstance(api.get("fred:UNRATE", start="2024-01-01", end="2024-12-31", deadline_s=30), ds.Series)
    finally:
        restored = api._local.deadline
        api._local.deadline = None
    assert seen == [outer] and restored == outer


def test_search_deadline_bounds_live_discovery_calls(tmp_path):
    api, hub = source(tmp_path, lambda provider, tool, args, kw: {"results": []} if provider == "fred" else {"indicators": []})
    api.search("zzz unmatched concept", deadline_s=0.3)
    assert hub.calls and all(0 < call[3]["timeout"] <= 0.3 and call[3]["deadline"] for call in hub.calls)
    api.search("zzz unmatched concept")
    assert hub.calls[-1][3] == {}
    assert api.search("unemployment", deadline_s=-1) == []
    assert getattr(api._local, "deadline", None) is None


# §1.3 display helpers ------------------------------------------------------------------------

@pytest.mark.parametrize("value, units, text", [
    (3.875, "Per cent per year", "3.875%"),   # BIS policy-rate midpoint (stored row)
    (4.2, "Percent", "4.2%"),
    (4.125, "Percent", "4.125%"),
    (5.266666666666667, "Percent", "5.267%"),
    (-0.0001, "Percent", "0%"),
    (3.2, "Percentage points of GDP", "3.2"),
    (40269094993348.984, "U.S. dollars", "40269094993348.98"),  # 16 significant digits, no binary noise; see scaled_value
    (1.12455, "U.S. Dollars to One Euro", "1.1245"),  # binary float 1.124549...
    (0.04567, "Ratio", "0.04567"),
    (0, "Index", "0"),
    (None, "Percent", "missing"),
])
def test_format_value_percent_precision_and_levels(value, units, text):
    assert ds.format_value(value, units) == text


@pytest.mark.parametrize("delta, units, text", [
    (-0.25, "Per cent per year", "-0.25 pp"),
    (4.2 - 4.1, "Percent", "+0.1 pp"),
    (0.0, "Percentage change", "0 pp"),
    (2307966401253.7656, "U.S. dollars", "+2307966401253.766"),
    (-3, "Index", "-3"),
    (None, "Percent", "missing"),
])
def test_format_change_uses_percentage_points_for_percent_units(delta, units, text):
    assert ds.format_change(delta, units) == text


def test_scaled_value_from_real_debt_row_and_magnitude_only():
    row = stored("usgov_treasury_debt_to_penny.json")["row"]
    latest = row["observations"][-1]["value"]
    assert ds.scaled_value(latest, row["units"]) == "≈ 40.27 trillion U.S. dollars"
    assert ds.scaled_value(latest, row["units"], lang="zh") == "≈40.27万亿美元"
    assert ds.scaled_value(-2.5e9, "Number") == "≈ -2.5 billion"
    assert ds.scaled_value(2.5e9, "Number", lang="zh") == "≈25亿"
    for value, units in ((9.9e8, "U.S. dollars"), (3e12, "Billions of Dollars"), (2e9, "Percent"), (None, "U.S. dollars"), ("x", "")):
        assert ds.scaled_value(value, units) == ""


def test_series_label_disambiguates_countries_for_provider_titles(monkeypatch):
    # Real Data360 rows carry the indicator name without the country (finding F10/L8).
    row = stored("wb_imf_weo_ngdp_rpch_chn.json")["row"]
    assert "China" not in row["title"]
    labels = {code: ds.series_label({**row, "series": f"wb:IMF_WEO_NGDP_RPCH/{code}", "geography": code}) for code in ("CHN", "USA", "DEU")}
    assert len(set(labels.values())) == 3
    assert "China" in labels["CHN"] and "United States" in labels["USA"] and "Germany" in labels["DEU"]
    assert "中国" in ds.series_label(row, "zh")
    monkeypatch.setattr(ds.catalog, "lookup", lambda sid: None)  # a discovered, non-catalog id
    assert ds.series_label(row) == row["title"] + " — China"
    assert "中国" in row["title_zh"] and ds.series_label(row, lang="zh") == row["title_zh"]
    assert ds.series_label({**row, "title_zh": ""}, lang="zh") == row["title"] + " — 中国"
    # Data360 economies beyond the curated series carry their catalog names; unknown codes stay codes.
    assert ds.series_label({**row, "geography": "FRA"}) == row["title"] + " — France"
    assert ds.series_label({**row, "title_zh": "", "geography": "VNM"}, lang="zh") == row["title"] + " — 越南"
    assert ds.series_label({**row, "geography": "KEN"}) == row["title"] + " — KEN"


def test_series_label_keeps_named_geography_transform_and_never_raises():
    row = stored("bis_ws_cbpol_m_us.json")["row"]
    assert ds.series_label(row) == row["title"]  # "... - United States - ..." already names it
    assert ds.series_label({"series": "fred:UNRATE#yoy", "title": "Unemployment Rate", "geography": "USA"}).endswith(
        "(year-over-year % change) — United States")
    assert ds.series_label(ds.Series.from_dict(row)) == ds.series_label(row)
    assert ds.series_label({}) == "" and ds.series_label(None) == "" and ds.series_label({"series": 7}) == ""


def test_observation_kind_marks_partial_aggregated_periods_and_latest_observed_skips_them():
    daily = stored("fred_dgs10.json")["row"]  # daily->monthly row: every period stored complete=False
    current = json.loads(json.dumps(daily))
    current["provenance"]["normalization_policy_version"] = 3  # policy 3 stores completeness itself
    s = ds.Series.from_dict(current)
    assert {ds.observation_kind(o, s) for o in s.observations} == {"partial"}
    assert ds.latest_observed(s) is None and ds.latest_observed(current) is None
    complete = json.loads(json.dumps(current))
    for period in complete["provenance"]["periods"].values():
        period["complete"] = True
    complete["provenance"]["periods"][complete["observations"][-1]["date"]]["complete"] = False
    latest = ds.latest_observed(complete)
    assert latest.date == complete["observations"][-2]["date"]
    assert ds.observation_kind(complete["observations"][-1], complete) == "partial"
    assert ds.observation_kind(complete["observations"][-2], complete) == "observed"


@pytest.mark.parametrize("name", ["fred_dgs10.json", "usgov_treasury_debt_to_penny.json"])
def test_policy2_daily_months_settle_by_the_rule_every_consumer_shares(name):
    # Policy 2 stored every aggregated month complete=False; a whole month followed by a later
    # stored month is history, the open month (covered to the retrieval day) stays partial.
    row = stored(name)["row"]
    s = ds.Series.from_dict(row)
    kinds = [ds.observation_kind(o, s) for o in s.observations]
    assert kinds == ["observed"] * (len(kinds) - 1) + ["partial"] and s.observations[-1].date == "2026-10-01"
    assert ds.latest_observed(s).date == ds.latest_observed(row).date == "2026-09-01"
    assert ds.render_series_page(s) == stored(name)["head_page"]  # stored pages keep their bytes
    # The report pack, charts and anchors (forecast_extractor) and the simulation snapshot agree.
    from app.services import forecast_extractor, official_data
    labels = forecast_extractor.official_observation_kinds(row)
    assert [k == "observed" for k in kinds] == [label == "historical observation" for label in labels]
    assert forecast_extractor.official_latest_observed(row)["date"] == "2026-09-01"
    snapshot = official_data.historical_snapshot({"series": [row]}, as_of="2026-10-12T00:00:00Z")
    assert " | 2026-09 | " in snapshot and "2026-10" not in snapshot.split("\n", 2)[2]


def test_policy2_month_without_a_later_month_settles_a_week_after_month_end():
    row = stored("fred_dgs10.json")["row"]
    row["observations"] = [o for o in row["observations"] if o["date"] <= "2026-09-01"]
    row["provenance"]["periods"] = {k: v for k, v in row["provenance"]["periods"].items() if k <= "2026-09-01"}
    last = row["observations"][-1]
    for retrieved, kind in (("2026-10-07T23:00:00+00:00", "partial"), ("2026-10-08T01:00:00+00:00", "observed")):
        assert ds.observation_kind(last, {**row, "retrieved_at": retrieved}) == kind
    gap = json.loads(json.dumps(row))
    gap["provenance"]["periods"]["2026-08-01"]["covered_start"] = "2026-08-03"  # not the whole month
    assert ds.observation_kind(gap["observations"][-2], gap) == "partial"
    for version in (3, True):  # current rows (and malformed versions) keep the stored flag
        pinned = json.loads(json.dumps(row))
        pinned["provenance"]["normalization_policy_version"] = version
        assert ds.observation_kind(pinned["observations"][-2], pinned) == "partial"


def test_observation_kind_keeps_publisher_status_and_rejects_garbage():
    weo = stored("wb_imf_weo_ngdp_rpch_chn.json")["row"]
    assert {ds.observation_kind(o, weo) for o in weo["observations"]} == {"unknown"}
    assert ds.latest_observed(weo) is None
    policy = ds.Series.from_dict(stored("bis_ws_cbpol_m_us.json")["row"])
    assert ds.latest_observed(policy).value == 3.875
    projected = ds.Series("fred:UNRATE", observations=[{"date": "2024-01-01", "value": 4}, {"date": "2025-01-01", "value": 5}],
                          projection_from="2025-01-01", provenance={"periods": {"2025-01-01": {"complete": False}}})
    assert ds.observation_kind(projected.observations[1], projected) == "projection"
    assert ds.latest_observed(projected).value == 4
    assert ds.observation_kind({"date": "garbage"}, projected) == "unknown"
    assert ds.latest_observed({"series": "nonsense"}) is None


# §1.2 optional catalog fields ----------------------------------------------------------------

def test_catalog_field_reads_optional_fields_with_defaults_and_validation():
    class Old:  # a catalog entry before slice B adds the fields
        series = "bis:WS_CBPOL/M.US"

    class New(Old):
        native_unit, native_dims, aggregation, status_policy = ("PERCENT", 0), {"FREQ": "M"}, "eop", "history_only"
        fred_equivalent, preferred, min_start, requires_key = "UNRATE", "fred:PCOPPUSDM", "2007-10-01", "EIA_API_KEY"

    class Bad(Old):
        native_unit, native_dims, aggregation, status_policy = ("USD", True), {"FREQ": 1}, "sum", "guess"
        fred_equivalent, preferred, min_start, requires_key = 5, None, ["2007"], b"EIA_API_KEY"

    names = ("native_unit", "native_dims", "aggregation", "status_policy", "fred_equivalent", "preferred", "min_start", "requires_key")
    assert [ds.catalog_field(Old(), n) for n in names] == [None, {}, "", "", "", "", "", ""]
    assert [ds.catalog_field(New(), n) for n in names] == [("PERCENT", 0), {"FREQ": "M"}, "eop", "history_only", "UNRATE",
                                                           "fred:PCOPPUSDM", "2007-10-01", "EIA_API_KEY"]
    assert [ds.catalog_field(Bad(), n) for n in names] == [None, {}, "", "", "", "", "", ""]
    from types import MappingProxyType
    proxy = type("Proxy", (Old,), {"native_dims": MappingProxyType({"UNIT_TYPE": "770"})})()
    assert ds.catalog_field(proxy, "native_dims") == {"UNIT_TYPE": "770"}
    assert ds.catalog_field(None, "aggregation") == "" and ds.catalog_field("not-an-id", "native_dims") == {}
    assert ds.catalog_field("fred:UNRATE#yoy", "min_start") == ds.catalog_field("fred:UNRATE", "min_start")
    with pytest.raises(KeyError):
        ds.catalog_field(Old(), "units")


# §1.5 KIQ links -------------------------------------------------------------------------------

def test_kiqs_round_trip_and_accumulate_through_stored_datasets(tmp_path):
    row = stored("bis_ws_cbpol_m_us.json")["row"]
    first = ds.Series.from_dict({**row, "kiqs": ["KIQ-1", " ", "KIQ-1", 3]})
    assert first.kiqs == ["KIQ-1"] and ds.Series.from_dict(first.to_dict()).kiqs == ["KIQ-1"]
    ds.write_dataset_files([first], tmp_path)
    assert ds.load_datasets(tmp_path)[0]["kiqs"] == ["KIQ-1"]
    ds.write_dataset_files([ds.Series.from_dict({**row, "kiqs": ["KIQ-2"]})], tmp_path)
    ds.write_dataset_files([ds.Series.from_dict({**row, "kiqs": []})], tmp_path)
    loaded = ds.load_datasets(tmp_path)
    assert [r["kiqs"] for r in loaded] == [["KIQ-1", "KIQ-2"]]
    assert ds.load_official_data(tmp_path)["series"][0]["kiqs"] == ["KIQ-1", "KIQ-2"]
    with pytest.raises(ValueError):
        ds.Series.from_dict({**row, "kiqs": "KIQ-1"})


# M3: stored rows re-render byte for byte; new rows use the current display rules ------------

@pytest.mark.parametrize("path", STORED_V2, ids=lambda p: p.stem)
def test_stored_policy_v2_rows_re_render_byte_identically(path):
    fixture = json.loads(path.read_text())
    series = ds.Series.from_dict(fixture["row"])
    assert series.provenance["normalization_policy_version"] == 2
    assert ds.render_series_page(series) == fixture["head_page"]
    assert ds.render_series_brief(series, 3) == fixture["head_brief"]
    unversioned = ds.Series.from_dict({**fixture["row"], "provenance": {k: v for k, v in fixture["row"]["provenance"].items()
                                                                         if k != "normalization_policy_version"}})
    assert ds.render_series_page(unversioned) == fixture["head_page"]
    latest = series.observations[-1].value
    assert ds.format_series_value(latest, series) == ds._legacy_format_value(latest, series.units)
    assert ds.format_series_value(latest, series) in fixture["head_page"]


def test_current_policy_rows_use_precise_percent_pp_changes_labels_and_partial_status():
    policy = stored("bis_ws_cbpol_m_us.json")
    row = json.loads(json.dumps(policy["row"]))
    row["provenance"]["normalization_policy_version"] = ds.NORMALIZATION_POLICY_VERSION
    page = ds.render_series_page(ds.Series.from_dict(row))
    assert "3.88%" in policy["head_page"] and "change -0.25% (-6.06%)" in policy["head_page"]
    assert "- Latest: 3.875% (2026-09-01)" in page and "change -0.25 pp." in page and "(-6.06%)" not in page
    assert "| 2026-09 | 3.875% | observed |" in page
    assert ds.format_series_value(3.875, ds.Series.from_dict(row)) == "3.875%"
    weo = json.loads(json.dumps(stored("wb_imf_weo_ngdp_rpch_chn.json")["row"]))
    weo["provenance"]["normalization_policy_version"] = ds.NORMALIZATION_POLICY_VERSION
    weo_series = ds.Series.from_dict(weo)
    assert ds.render_series_page(weo_series).splitlines()[0] == "# " + ds.series_label(weo_series)
    assert ds.render_series_brief(weo_series, 2).startswith(f"[S2] {weo_series.series} — {ds.series_label(weo_series)} (")
    daily = json.loads(json.dumps(stored("fred_dgs10.json")["row"]))
    daily["provenance"]["normalization_policy_version"] = ds.NORMALIZATION_POLICY_VERSION
    daily_page = ds.render_series_page(ds.Series.from_dict(daily))
    assert "| 2026-10 (partial) | 5.267% | partial |" in daily_page
    level = ds.Series("fred:PAYEMS", units="Thousands of Persons", frequency="M", provenance={"normalization_policy_version": 3},
                      observations=[{"date": "2023-01-01", "value": 1000}, {"date": "2024-01-01", "value": 1100}])
    assert "change +100 (+10%)." in ds.render_series_page(level)


def test_fetched_rows_carry_the_current_policy_version(tmp_path):
    api, _ = source(tmp_path, lambda *a: fred_payload())
    result = api.get("fred:UNRATE", start="2024-01-01", end="2024-12-31")
    assert result.provenance["normalization_policy_version"] == ds.NORMALIZATION_POLICY_VERSION >= 3
    assert ds._display_current(result)


def test_concurrent_deadline_scopes_are_thread_local(tmp_path):
    barrier = threading.Barrier(2)
    seen = {}
    def record(provider, tool, args, kw):
        seen[threading.current_thread().name] = kw.get("timeout")
        return fred_payload(args["series_id"])
    api, _ = source(tmp_path, record)
    def bounded():
        barrier.wait()
        api.get("fred:UNRATE", start="2024-01-01", end="2024-12-31", deadline_s=5)
    def unbounded():
        barrier.wait()
        api.get("fred:PAYEMS", start="2024-01-01", end="2024-12-31")
    threads = [threading.Thread(target=bounded, name="bounded"), threading.Thread(target=unbounded, name="unbounded")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert seen["bounded"] and seen["bounded"] <= 5 and seen["unbounded"] is None
