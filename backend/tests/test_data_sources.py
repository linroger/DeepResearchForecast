"""Common producer acceptance with source-derived synthetic MCP payloads.

Run under backend/scripts/main_offline_pytest.py, before application imports.
No vendor imports, built servers, provider calls, or populated runs are used.
"""
import copy
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from deerflow_bridge import data_sources as ds
from deerflow_bridge.data_mcp import CallResult


FIXTURES = Path(__file__).parent / "fixtures" / "data_sources" / "provider_responses.json"
NOW = 1791763200.0  # fixed UTC clock; no vintage inference from this value


class Hub:
    def __init__(self, handler):
        self.handler, self.calls, self.started, self.closed = handler, [], [], False

    def call(self, provider, tool, args, **kw):
        self.calls.append((provider, tool, copy.deepcopy(args)))
        data = self.handler(provider, tool, args)
        if isinstance(data, CallResult):
            return data
        return CallResult(True, json.dumps(data), None, 0.0)

    def status(self):
        return {p: {"state": "ready", "error": None} for p in ds.PROVIDERS}

    def start(self, names, **kw):
        self.started.extend(names)

    def close(self):
        self.closed = True


@pytest.fixture
def payloads():
    return json.loads(FIXTURES.read_text())


def api(tmp_path, payloads, handler=None, **kw):
    def default(provider, tool, args):
        if tool == "imf_get_parameter_defs":
            return payloads["imf_defs"]
        if tool == "data360_get_metadata":
            return {"indicator_metadata": payloads["wb"]["metadata"], "error": None}
        return payloads["treasury" if provider == "usgov" else provider]
    hub = Hub(handler or default)
    env = {"DATA_SOURCES_ENABLED": "true", "FRED_API_KEY": "synthetic-key"}
    env.update(kw.pop("env", {}))
    return ds.DataSources(hub, env=env, cache_dir=tmp_path / "cache", clock=lambda: NOW, **kw), hub


def sample(**kw):
    args = {"series": "fred:UNRATE", "provider": "fred", "provider_name": "FRED", "title": "Unemployment Rate",
            "title_zh": "失业率", "units": "Percent", "frequency": "M", "seasonal_adjustment": "SA",
            "geography": "USA", "source_url": "https://fred.stlouisfed.org/series/UNRATE",
            "observations": [ds.Observation("2024-01-01", 4.0), ds.Observation("2024-02-01", None),
                             ds.Observation("2024-03-01", 4.2)]}
    args.update(kw)
    return ds.Series(**args)


@pytest.mark.parametrize("text,expected", [
    (" `FrEd:unrate` ", ("fred", "UNRATE")), ("bis:WS_TC/Q.US.P.A.M.770.A", ("bis", "WS_TC/Q.US.P.A.M.770.A")),
    ("fred:UNRATE#yoy", ("fred", "UNRATE#yoy")), ("https://evil.test/a", None),
    ("fred:UNRATE?api_key=secret", None), ("bis:WS_CBPOL/M.*", None),
    ("usgov:treasury/fx/Euro Zone-Euro", ("usgov", "treasury/fx/Euro Zone-Euro")),
])
def test_ids(text, expected):
    assert ds.parse_series_id(text) == expected


@pytest.mark.parametrize("sid,provider,tool", [
    ("fred:UNRATE", "fred", "fred_get_series"), ("bls:LNS14000000", "bls", "get_multiple_series"),
    ("bis:WS_CBPOL/M.US", "bis", "fetch_dataset"), ("imf:PCPS/G001.POILBRE.USD.M", "imf", "imf_fetch_data"),
    ("wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA", "wb", "data360_get_data"),
    ("usgov:treasury/mts_deficit", "usgov", "treasury_query_fiscal_data"),
])
def test_six_native_handlers_to_persisted_pack(tmp_path, payloads, sid, provider, tool):
    source, hub = api(tmp_path, payloads)
    result = source.get(sid, start="2022-01-01", end="2024-12-31")
    assert isinstance(result, ds.Series), result
    assert result.series == sid and result.provider == provider
    assert result.observations == sorted(result.observations, key=lambda o: o.date)
    assert result.observations[1].value is None
    assert result.route == "mcp" and result.retrieved_at and result.source_url.startswith("https://")
    assert result.vintage == "" and result.provenance["response_sha256"]
    args = next(a for p, t, a in hub.calls if t == tool)
    if provider == "fred":
        assert args["units"] == "lin" and "frequency" not in args
    if provider == "bls":
        assert args["series_ids"] == ["LNS14000000"] and args["start_year"] == "2022"
        assert result.observations[-1].flag == "preliminary"
    if provider == "bis":
        assert args["flow_ref"] == "BIS,WS_CBPOL,1.0" and args["key"] == "M.US"
    if provider == "imf":
        assert args["params"]["filters"] == {"country": ["G001"], "indicator": ["POILBRE"],
                                                "data_transformation": ["USD"], "frequency": ["M"]}
    if provider == "usgov":
        assert "line_code_nbr:eq:520" in args["filter"] and "filters" not in args
    manifest = ds.write_dataset_files([result], tmp_path / "run", citations={sid: 12})
    row = manifest["series"][0]
    assert row["source_id"] == "S12"
    assert row["sha256"] == hashlib.sha256((tmp_path / "run" / row["file"]).read_bytes()).hexdigest()
    loaded = ds.load_official_data(tmp_path / "run")
    assert loaded["schema_version"] == 1 and loaded["series"][0]["observations"] == result.to_dict()["observations"]


def test_disabled_and_invalid_inputs_never_call(tmp_path, payloads):
    source, hub = api(tmp_path, payloads, env={"DATA_SOURCES_ENABLED": "false"})
    assert not source.enabled()
    assert isinstance(source.get("fred:UNRATE"), ds.DataError)
    assert source.search("unemployment") == []
    source.prewarm()
    assert hub.calls == hub.started == []
    source, hub = api(tmp_path, payloads)
    for args in ({"series": "fred:UNRATE", "start": "2024-02-30"},
                 {"series": "fred:UNRATE", "start": "2025-01-01", "end": "2024-01-01"},
                 {"series": "fred:UNRATE", "transform": "log"}, {"series": "fred:UNRATE", "max_obs": 0}):
        assert isinstance(source.get(**args), ds.DataError)
    assert not hub.calls


def test_provider_payload_errors_and_secrets(tmp_path, payloads):
    for payload in ({"error": "The key:synthetic-key is invalid"},
                    {"status": "REQUEST_FAILED", "message": ["The key:synthetic-key"]},
                    CallResult(True, "Error: The key:synthetic-key rejected", None, 0)):
        source, _ = api(tmp_path, payloads, lambda *a, response=payload: response)
        result = source.get("bls:LNS14000000")
        assert isinstance(result, ds.DataError) and "synthetic-key" not in result.message
        assert len(result.message) <= 300


@pytest.mark.parametrize("provider,sid", [("bis", "bis:WS_CBPOL/M.US"), ("imf", "imf:PCPS/G001.POILBRE.USD.M")])
def test_sdmx_rejects_wrong_identity_and_truncation(tmp_path, payloads, provider, sid):
    payloads[provider]["rows"][0]["REF_AREA" if provider == "bis" else "country"] = "CN"
    source, _ = api(tmp_path, payloads)
    assert isinstance(source.get(sid, start="2024-01-01", end="2024-12-31"), ds.DataError)
    payloads[provider]["rows"][0]["REF_AREA" if provider == "bis" else "country"] = "US" if provider == "bis" else "G001"
    payloads[provider]["truncated"] = True
    source, _ = api(tmp_path, payloads)
    assert isinstance(source.get(sid, start="2024-01-01", end="2024-12-31"), ds.DataError)


def test_keyless_fred_bounded_injected_csv(tmp_path, payloads):
    calls = []
    def fetch(url, **kw):
        calls.append((url, kw))
        return b"observation_date,UNRATE\n2024-01-01,4.0\n2024-02-01,.\n2024-03-01,4.2\n"
    source, hub = api(tmp_path, payloads, env={"FRED_API_KEY": ""}, http_get=fetch)
    result = source.get("fred:UNRATE", start="2024-01-01", end="2024-03-31")
    assert isinstance(result, ds.Series) and result.route == "fred_csv"
    assert not hub.calls and len(calls) == 1
    assert calls[0][0].startswith("https://fred.stlouisfed.org/graph/fredgraph.csv?")
    assert "api_key" not in result.api_url and result.vintage == ""
    assert result.observations[1].value is None
    assert calls[0][1]["timeout"] <= 20


def test_fred_fallback_rejects_wrong_header_and_oversize(tmp_path, payloads):
    for content in (b"observation_date,GDP\n2024-01-01,4\n", b"x" * (2 * 1024 * 1024 + 1)):
        source, _ = api(tmp_path, payloads, env={"FRED_API_KEY": ""}, http_get=lambda *a, response=content, **k: response)
        assert isinstance(source.get("fred:UNRATE"), ds.DataError)


def test_exact_calendar_transform_gaps_and_warmup(tmp_path, payloads):
    payloads["fred"]["data"] = [{"date": "2023-03-01", "value": 100}, {"date": "2024-01-01", "value": 110},
                                {"date": "2024-03-01", "value": 120}]
    source, hub = api(tmp_path, payloads)
    result = source.get("fred:UNRATE", start="2024-01-01", end="2024-03-31", transform="yoy")
    assert isinstance(result, ds.Series) and result.series == "fred:UNRATE#yoy"
    assert result.units == "Percent change from year ago"
    assert result.observations[-1].value == pytest.approx(20)
    assert result.observations[0].value is None
    assert hub.calls[0][2]["observation_start"] <= "2023-01-01"
    other = source.get("fred:UNRATE", start="2024-01-01", end="2024-03-31", transform="pct")
    assert other.observations[-1].value is None  # February is absent, never compare January to March


def test_bls_batch_chunking_and_quota(tmp_path, payloads):
    def batch(provider, tool, args):
        return {"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": [
            {"seriesID": sid, "data": [{"year": args["end_year"], "period": "M01", "value": "1"}]}
            for sid in args["series_ids"]]}}
    source, hub = api(tmp_path, payloads, batch)
    ids = [f"bls:TEST{i}" for i in range(26)]
    result = source.get_many(ids, deadline_s=3, start="2000-01-01", end="2024-12-31")
    assert all(isinstance(v, ds.Series) for v in result.values())
    assert len(hub.calls) == 6  # two ID batches, three non-overlapping <=10-year windows
    assert all(len(a["series_ids"]) <= 25 and int(a["end_year"]) - int(a["start_year"]) <= 9 for _, _, a in hub.calls)
    assert hub.calls[0][2]["end_year"] == "2024"
    for i in range(14):
        assert isinstance(source.get(f"bls:QUOTA{i}", start="2024-01-01", end="2024-12-31"), ds.Series)
    fresh, second_hub = api(tmp_path, payloads, batch)
    exhausted = fresh.get("bls:LIMIT", start="2024-01-01", end="2024-12-31")
    assert isinstance(exhausted, ds.DataError) and "quota" in exhausted.message.lower()
    assert not second_hub.calls


def test_wb_paging_and_no_invented_projection_boundary(tmp_path, payloads):
    def pages(provider, tool, args):
        if tool == "data360_get_metadata":
            return {"indicator_metadata": {"idno": "IMF_WEO_NGDP_RPCH", "database_id": "IMF_WEO", "indicator_name": "WEO GDP", "periodicity": "Annual", "measurement_unit": "Percent change"}, "error": None}
        return {"data": [{"REF_AREA": "CHN", "TIME_PERIOD": str(2024 + args["offset"]), "OBS_VALUE": 4.0, "UNIT_MEASURE": "PT", "UNIT_MEASURE_NAME": "Percent"}],
                "metadata": {}, "count": 1, "offset": args["offset"], "total_count": 2,
                "has_more": args["offset"] == 0, "next_offset": 1 if args["offset"] == 0 else None}
    source, hub = api(tmp_path, payloads, pages)
    result = source.get("wb:IMF_WEO_NGDP_RPCH/CHN", start="2024-01-01", end="2026-12-31")
    assert isinstance(result, ds.Series) and len(result.observations) == 2
    assert result.projection_from == "" and all(o.flag == "unknown" for o in result.observations)
    assert len([c for c in hub.calls if c[1] == "data360_get_data"]) == 2


def test_cache_singleflight_and_ttl(tmp_path, payloads):
    source, hub = api(tmp_path, payloads)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: source.get("fred:UNRATE", start="2024-01-01", end="2024-12-31"), range(4)))
    assert len(hub.calls) == 1 and all(isinstance(v, ds.Series) for v in results)
    fresh, new_hub = api(tmp_path, payloads)
    assert fresh.get("fred:UNRATE", start="2024-01-01", end="2024-12-31").route == "cache"
    assert not new_hub.calls


def test_get_many_returns_at_deadline(tmp_path, payloads):
    release = threading.Event()
    def slow(*args):
        release.wait(1)
        return payloads["fred"]
    source, _ = api(tmp_path, payloads, slow)
    started = time.monotonic()
    try:
        result = source.get_many(["fred:UNRATE"], deadline_s=0.03)
        assert time.monotonic() - started < 0.4
        assert isinstance(result["fred:UNRATE"], ds.DataError)
    finally:
        release.set()


def test_roundtrip_metadata_and_safe_distinct_slugs(tmp_path):
    base = sample(vintage="2024-04", kiqs=["K1"])
    changed = sample(series="fred:UNRATE#yoy", transform="yoy", units="Percent change from year ago")
    assert ds.Series.from_dict(base.to_dict()).to_dict() == base.to_dict()
    manifest = ds.write_dataset_files([base, changed], tmp_path, citations={base.series: "S3"})
    assert len({r["slug"] for r in manifest["series"]}) == 2
    assert all(len(r["slug"]) <= 60 for r in manifest["series"])
    rows = ds.load_datasets(tmp_path)
    assert rows[0]["vintage"] == "2024-04" and rows[0]["kiqs"] == ["K1"]


@pytest.mark.parametrize("damage", ["hash", "csv_hash", "identity", "traversal", "symlink", "metadata"])
def test_persistence_refuses_corrupt_artifacts(tmp_path, damage):
    manifest = ds.write_dataset_files([sample()], tmp_path)
    row = manifest["series"][0]
    path = tmp_path / row["file"]
    if damage == "hash":
        path.write_text("{}")
    elif damage == "csv_hash":
        (tmp_path / row["csv"]).write_text("date,value\n2024-01-01,999\n")
    elif damage == "identity":
        row["series"] = "fred:GDP"
    elif damage == "metadata":
        row["units"] = "Billions of dollars"
    elif damage == "traversal":
        row["file"] = "../outside.json"
    elif damage == "symlink":
        copy_path = tmp_path / "outside.json"
        path.rename(copy_path)
        path.symlink_to(copy_path)
    (tmp_path / "data/datasets.json").write_text(json.dumps(manifest))
    assert ds.load_datasets(tmp_path) == [] and ds.load_official_data(tmp_path) is None


def test_incremental_persistence_preserves_other_series_and_citations(tmp_path):
    ds.write_dataset_files([sample()], tmp_path, citations={"fred:UNRATE": 4})
    second = sample(series="fred:GDP", title="GDP")
    ds.write_dataset_files([second], tmp_path, citations={"fred:GDP": "S5"})
    rows = ds.load_datasets(tmp_path)
    assert {r["series"]: r["source_id"] for r in rows} == {"fred:UNRATE": "S4", "fred:GDP": "S5"}


def test_anchor_exact_period_metadata_and_projection_refusal():
    s = sample(retrieved_at="2024-04-01T00:00:00Z")
    anchor = {"series": s.series, "period": "2024-03", "threshold": 4.1, "comparator": ">", "units": s.units, "transform": ""}
    valid = ds.validate_data_anchor(anchor, {"schema_version": 1, "series": [s.to_dict()]})
    assert valid is not None and valid["period"] == "2024-03-01"
    resolved = ds.resolve_data_anchor(valid, s, as_of="2024-04-01")
    assert resolved == {"status": "resolved", "reason": "Exact historical observation satisfies comparison", "series": s.series,
                        "observation": {"date": "2024-03-01", "value": 4.2, "flag": ""}, "outcome": True}
    for patch in ({"threshold": float("nan")}, {"units": "Dollars"}, {"transform": "pct"}, {"period": "2024-03-02"}, {"comparator": "="}):
        assert ds.validate_data_anchor({**anchor, **patch}, {"series": [s.to_dict()]}) is None
    for flag in ("projection", "P", "unknown", "estimate"):
        s.observations[-1].flag = flag
        result = ds.resolve_data_anchor(anchor, s, as_of="2024-04-01")
        assert result["status"] == "manual" and "outcome" not in result
    s.observations[-1].flag = ""
    s.units = ""
    assert ds.resolve_data_anchor(anchor, s)["status"] == "manual"


def test_anchor_missing_period_and_future_never_resolve():
    s = sample()
    anchor = {"series": s.series, "period": "2025-01", "threshold": 4.1, "comparator": ">"}
    assert ds.validate_data_anchor(anchor, {"series": [s.to_dict()]}) is not None
    result = ds.resolve_data_anchor(anchor, s, as_of="2024-04-01")
    assert result["status"] == "pending" and "outcome" not in result
    anchor["period"] = "2024-02"
    assert ds.resolve_data_anchor(anchor, s, as_of="2025-01-01")["status"] == "pending"


def test_rendered_numbers_and_stats_use_stored_values():
    s = sample()
    page = ds.render_series_page(s)
    assert "4.2%" in page and "4%" in page and len(page) <= 12000
    assert "2024-02" in page and "missing" in page.lower()
    assert len(ds.render_series_brief(s, 12)) <= 900 and "[S12]" in ds.render_series_brief(s, 12)
    stats = ds.series_stats(s)
    assert stats["latest"] == {"date": "2024-03-01", "value": 4.2}
    assert stats["count"] == 3 and stats["projection_count"] == 0


def test_observation_anchor_contract_and_historical_latest():
    s = sample()
    s.observations.append(ds.Observation("2025-01-01", 99, "projection"))
    anchor = {"series": s.series, "observation": "2026-03", "threshold": 4.1, "comparator": ">"}
    valid = ds.validate_data_anchor(anchor, {"series": [s.to_dict()]})
    assert valid is not None
    assert valid["observation"] == "2026-03"
    assert valid["latest_value"] == 4.2 and valid["latest_date"] == "2024-03-01"


def test_anchor_rejects_period_syntax_with_wrong_frequency():
    s = sample()
    for period in ("2024", "2024-Q1"):
        anchor = {"series": s.series, "period": period, "threshold": 3, "comparator": ">"}
        assert ds.validate_data_anchor(anchor, {"series": [s.to_dict()]}) is None


def test_wb_search_actual_enriched_handler_response(tmp_path, payloads):
    def handler(provider, tool, args):
        assert tool == "data360_search_indicators"
        return {"indicators": [{"idno": "WB_WDI_TEST_INDICATOR", "database_id": "WB_WDI", "name": "Synthetic rare metric",
                                 "periodicity": "Annual", "covers_country": {"CHN": True}, "requested_country": "CHN"}], "error": None}
    source, _ = api(tmp_path, payloads, handler)
    hits = source.search("synthetic rare metric China", provider="wb", limit=50)
    assert any(h.series == "wb:WB_WDI_TEST_INDICATOR/CHN" for h in hits)


def test_metadata_source_urls_and_provenance_receipts(tmp_path, payloads):
    source, hub = api(tmp_path, payloads)
    result = source.get("imf:PCPS/G001.POILBRE.USD.M", start="2024-01-01", end="2024-12-31")
    assert result.source_url == "https://data.imf.org/en/datasets/IMF.RES:PCPS"
    receipt = next(r for r in result.provenance["tool_responses"] if r["tool"] == "imf_fetch_data")
    assert receipt["arguments"] == hub.calls[-1][2]


def test_bls_all_null_column_and_quarterly_period(tmp_path, payloads):
    payloads["bls"]["Results"]["series"] = [{"seriesID": "CIU1010000000000A", "data": [
        {"year": "2024", "period": "Q02", "value": "4.1"}, {"year": "2024", "period": "Q01", "value": "3.9"}]}]
    source, _ = api(tmp_path, payloads)
    result = source.get("bls:CIU1010000000000A", start="2024-01-01", end="2024-12-31")
    assert result.frequency == "Q" and [o.date for o in result.observations] == ["2024-01-01", "2024-04-01"]


def test_treasury_pagination_reordered_columns_and_native_source_receipts(tmp_path, payloads):
    def handler(provider, tool, args):
        payload = copy.deepcopy(payloads["treasury"])
        payload["meta"]["totalPages"] = 2
        payload["meta"]["sources"] = [{"url": "https://api.fiscaldata.treasury.gov/example?api_key=synthetic-key", "fetchedAt": "2025-01-01T00:00:00Z", "cached": True}]
        payload["data"]["rows"] = payload["data"]["rows"][:1] if args["page_number"] == 1 else payload["data"]["rows"][1:]
        payload["meta"]["recordsReturned"] = len(payload["data"]["rows"])
        if args["page_number"] == 2:
            payload["data"]["columns"].reverse()
            for row in payload["data"]["rows"]:
                row.reverse()
        return payload
    source, hub = api(tmp_path, payloads, handler)
    result = source.get("usgov:treasury/mts_deficit", start="2024-01-01", end="2024-12-31")
    assert isinstance(result, ds.Series) and len(result.observations) == 3
    assert len(hub.calls) == 2
    receipt = result.provenance["tool_responses"][0]
    assert receipt["sources"][0]["fetchedAt"] == "2025-01-01T00:00:00Z"
    assert "api_key" not in receipt["sources"][0]["url"] and "synthetic-key" not in json.dumps(result.to_dict())


def test_wb_periodicity_conflict_is_unavailable(tmp_path, payloads):
    payloads["wb"]["metadata"]["periodicity"] = "Monthly"
    source, _ = api(tmp_path, payloads)
    result = source.get("wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA", start="2022-01-01", end="2024-12-31")
    assert isinstance(result, ds.DataError)


def test_spending_and_sec_expose_source_limitations(tmp_path, payloads):
    source, hub = api(tmp_path, payloads, lambda *a: payloads["spending"])
    result = source.get("usgov:spending/total", start="2023-01-01", end="2025-12-31")
    assert isinstance(result, ds.Series) and result.observations[0].date == "2023-10-01"
    anchor = {"series": result.series, "observation": "2023-10-01", "comparator": ">", "threshold": 1}
    assert ds.resolve_data_anchor(anchor, result)["status"] == "manual"
    calls = len(hub.calls)
    result = source.get("usgov:sec/AAPL/Assets")
    assert isinstance(result, ds.DataError) and "period starts" in result.message
    assert len(hub.calls) == calls


@pytest.mark.parametrize("raw", [[], {"schema_version": 1, "series": [{}]}, {"schema_version": 1, "series": [None]}])
def test_malformed_manifest_is_unavailable_not_exception(tmp_path, raw):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/datasets.json").write_text(json.dumps(raw))
    assert ds.load_datasets(tmp_path) == []


def test_manifest_slug_and_chart_cannot_escape(tmp_path):
    manifest = ds.write_dataset_files([sample()], tmp_path)
    manifest["series"][0]["slug"] = "../../escape"
    manifest["series"][0]["chart"] = "../outside.png"
    (tmp_path / "data/datasets.json").write_text(json.dumps(manifest))
    assert ds.load_datasets(tmp_path) == []


def test_keyless_fred_raw_identity_and_cache_ttl(tmp_path, payloads):
    csv_bytes = b"observation_date,UNRATE\n2024-01-01,4.0\n2024-03-01,4.2\n"
    source, _ = api(tmp_path, payloads, env={"FRED_API_KEY": ""}, http_get=lambda *a, **k: csv_bytes)
    result = source.get("fred:UNRATE", start="2024-01-01", end="2024-12-31")
    assert result.provenance["tool_responses"][0]["sha256"] == hashlib.sha256(csv_bytes).hexdigest()
    assert result.provenance["metadata_origin"] == "curated_catalog"
    source._clock = lambda: NOW + 43201
    result2 = source.get("fred:UNRATE", start="2024-01-01", end="2024-12-31")
    assert result2.route == "fred_csv" and result2.retrieved_at != result.retrieved_at


def test_fred_rejected_key_fallback_and_daily_aggregation(tmp_path, payloads):
    def auth_error(*args):
        return CallResult(False, "", "FRED API key rejected", 0)
    csv_bytes = b"observation_date,DGS10\n2024-01-01,4\n2024-01-02,.\n2024-01-03,6\n2024-02-01,.\n"
    source, hub = api(tmp_path, payloads, auth_error, http_get=lambda *a, **k: csv_bytes)
    result = source.get("fred:DGS10", start="2024-01-01", end="2024-12-31")
    assert result.route == "fred_csv" and result.frequency == "M"
    assert [(o.date, o.value) for o in result.observations] == [("2024-01-01", 5.0), ("2024-02-01", None)]
    assert result.provenance["native_frequency"] == "D" and result.provenance["resolution_safe"] is False


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), "Infinity", "1oops", True])
def test_nonfinite_and_malformed_provider_values_never_become_zero(tmp_path, payloads, bad):
    payloads["fred"]["data"][0]["value"] = bad
    source, _ = api(tmp_path, payloads)
    assert isinstance(source.get("fred:UNRATE", start="2024-01-01", end="2024-12-31"), ds.DataError)


def test_imf_weo_vintage_and_status_are_not_inferred(tmp_path, payloads):
    def handler(provider, tool, args):
        if tool == "imf_get_parameter_defs":
            return [{"parameter": "country"}, {"parameter": "indicator"}, {"parameter": "frequency"}]
        return {"database_id": "WEO_2026_APR_VINTAGE", "rows": [
            {"country": "USA", "indicator": "NGDP_RPCH", "frequency": "A", "time_period": "2024", "obs_value": 2.0},
            {"country": "USA", "indicator": "NGDP_RPCH", "frequency": "A", "time_period": "2027", "obs_value": 3.0}], "truncated": False}
    source, hub = api(tmp_path, payloads, handler)
    result = source.get("imf:WEO_2026_APR_VINTAGE/USA.NGDP_RPCH.A", start="2024-01-01", end="2027-12-31")
    assert isinstance(result, ds.Series) and result.vintage == "WEO_2026_APR_VINTAGE"
    assert result.projection_from == "" and all(o.flag == "unknown" for o in result.observations)
    assert hub.calls[-1][2]["params"]["database_id"] == result.vintage


def test_bis_exact_version_and_byte_truncation_errors(tmp_path, payloads):
    def handler(provider, tool, args):
        assert tool == "fetch_dataset" and args["flow_ref"] == "BIS,WS_TC,2.0"
        return {"flow_ref": args["flow_ref"], "rows": [], "truncated": True}
    source, _ = api(tmp_path, payloads, handler)
    result = source.get("bis:WS_TC/Q.US.P.A.M.770.A", start="2024-01-01", end="2024-12-31")
    assert isinstance(result, ds.DataError) and "truncated" in result.message
    payloads["treasury"]["truncatedToFit"] = True
    source, _ = api(tmp_path, payloads)
    assert isinstance(source.get("usgov:treasury/mts_deficit", start="2024-01-01", end="2024-12-31"), ds.DataError)


def test_wb_repeated_page_and_wrong_geography_are_errors(tmp_path, payloads):
    payloads["wb"]["has_more"] = True
    def repeated(provider, tool, args):
        if tool == "data360_get_metadata":
            return {"indicator_metadata": payloads["wb"]["metadata"], "error": None}
        return {**payloads["wb"], "offset": args["offset"], "total_count": None, "next_offset": args["offset"] + 3}
    source, _ = api(tmp_path, payloads, repeated)
    assert "repeated" in source.get("wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA").message
    payloads["wb"]["has_more"] = False
    payloads["wb"]["data"][0]["REF_AREA"] = "CHN"
    source, _ = api(tmp_path, payloads)
    assert isinstance(source.get("wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA"), ds.DataError)


def test_load_official_pack_bounded_and_no_network(tmp_path):
    s = sample(observations=[ds.Observation(f"{year}-01-01", year) for year in range(1700, 2000)])
    ds.write_dataset_files([s], tmp_path)
    result = ds.load_official_data(tmp_path)
    assert len(result["series"][0]["observations"]) == 240
    assert result["series"][0]["observations"][0]["date"] == "1760-01-01"
    assert ds.load_official_data(tmp_path, max_series=0) is None


def test_cache_returned_metadata_cannot_mutate_next_reader(tmp_path, payloads):
    source, hub = api(tmp_path, payloads)
    args = {"start": "2024-01-01", "end": "2024-12-31"}
    source.get("fred:UNRATE", **args)
    second = source.get("fred:UNRATE", **args)
    second.provenance["metadata_origin"] = "forged"
    second.observations[0].value = 999
    third = source.get("fred:UNRATE", **args)
    assert third.provenance["metadata_origin"] != "forged" and third.observations[0].value == 4
    assert len(hub.calls) == 1


def test_lazy_import_modes_and_reset_never_start_hub(monkeypatch):
    import importlib
    import sys
    monkeypatch.syspath_prepend(str(Path(ds.__file__).parent))
    bare = importlib.import_module("data_sources")
    for module in (ds, bare):
        module.reset_data_sources_for_tests()
        monkeypatch.setattr(module, "get_hub", lambda **k: pytest.fail("Lazy singleton must not initialize hub"))
        source = module.get_data_sources(env={"DATA_SOURCES_ENABLED": "false"})
        assert not source.enabled() and source.search("unemployment") == []
        module.reset_data_sources_for_tests()
    assert "data_sources" in sys.modules


@pytest.mark.parametrize("failure", ["invalid_later_series", "csv_write", "manifest_write"])
def test_failed_update_preserves_previously_committed_generation(tmp_path, monkeypatch, failure):
    previous = sample()
    ds.write_dataset_files([previous], tmp_path, citations={previous.series: "S4"})
    manifest_before = (tmp_path / "data/datasets.json").read_bytes()
    changed = sample(observations=[ds.Observation("2024-03-01", 9)])
    incoming = [changed]
    if failure == "invalid_later_series":
        incoming.append({"series": "fred:GDP", "observations": []})
    else:
        atomic = ds._atomic
        def fail(path, data):
            if (failure == "csv_write" and str(path).endswith(".csv")) or (failure == "manifest_write" and path.name == "datasets.json"):
                raise OSError("Synthetic write failure")
            atomic(path, data)
        monkeypatch.setattr(ds, "_atomic", fail)
    assert ds.write_dataset_files(incoming, tmp_path).get("error")
    assert (tmp_path / "data/datasets.json").read_bytes() == manifest_before
    rows = ds.load_datasets(tmp_path)
    assert rows[0]["observations"] == previous.to_dict()["observations"] and rows[0]["source_id"] == "S4"


@pytest.mark.parametrize("damage", ["unit", "multiplier", "period"])
def test_sdmx_metadata_conflicts_cannot_resolve_under_catalog_label(tmp_path, payloads, damage):
    for row in payloads["bis"]["rows"]:
        if damage == "unit":
            row["UNIT_MEASURE"], row["UNIT_MULT"] = "USD", "6"
        elif damage == "multiplier":
            row["UNIT_MULT"] = "6"
        else:
            row["TIME_PERIOD"] = row["TIME_PERIOD"][:4] + "-Q1"
    source, _ = api(tmp_path, payloads)
    result = source.get("bis:WS_CBPOL/M.US", start="2024-01-01", end="2024-12-31")
    assert isinstance(result, ds.DataError)


def test_sdmx_single_wrong_precision_period_rejected(tmp_path, payloads):
    payloads["bis"]["rows"][0]["TIME_PERIOD"] = "2024-Q2"
    source, _ = api(tmp_path, payloads)
    assert isinstance(source.get("bis:WS_CBPOL/M.US", start="2024-01-01", end="2024-12-31"), ds.DataError)


def test_treasury_incomplete_final_page_is_unavailable(tmp_path, payloads):
    def handler(provider, tool, args):
        data = copy.deepcopy(payloads["treasury"])
        data["meta"]["totalPages"] = 2
        data["data"]["rows"] = data["data"]["rows"][:2] if args["page_number"] == 1 else []
        data["meta"]["recordsReturned"] = len(data["data"]["rows"])
        return data
    source, _ = api(tmp_path, payloads, handler)
    assert isinstance(source.get("usgov:treasury/mts_deficit", start="2024-01-01", end="2024-12-31"), ds.DataError)


def test_overlapping_bls_batches_share_one_provider_request(tmp_path, payloads):
    entered, release = threading.Event(), threading.Event()
    def handler(*a):
        entered.set()
        release.wait(1)
        return payloads["bls"]
    source, hub = api(tmp_path, payloads, handler)
    args = {"deadline_s": 2, "start": "2024-01-01", "end": "2024-12-31"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(source.get_many, ["bls:LNS14000000"], **args)
        assert entered.wait(0.5)
        second = pool.submit(source.get_many, ["bls:LNS14000000"], **args)
        release.set()
        assert isinstance(first.result()["bls:LNS14000000"], ds.Series)
        assert isinstance(second.result()["bls:LNS14000000"], ds.Series)
    assert len(hub.calls) == 1


def test_parent_swap_during_open_cannot_read_symlinked_dataset(tmp_path, monkeypatch):
    import os
    ds.write_dataset_files([sample()], tmp_path / "run")
    directory = tmp_path / "run/data"
    displaced = tmp_path / "run/original-data"
    external = tmp_path / "external"
    external.mkdir()
    original_open = os.open
    swapped = False
    def replace_parent(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if not swapped and Path(path) == directory:
            swapped = True
            directory.rename(displaced)
            directory.symlink_to(external, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)
    monkeypatch.setattr(os, "open", replace_parent)
    assert ds.load_datasets(tmp_path / "run") == []
    assert swapped and list(external.iterdir()) == []


def test_parent_swap_during_replace_cannot_redirect_write(tmp_path, monkeypatch):
    import os
    directory, external, displaced = tmp_path / "data", tmp_path / "external", tmp_path / "original-data"
    directory.mkdir()
    external.mkdir()
    (external / "evidence.json").write_bytes(b"external unchanged")
    original_replace = os.replace
    def replace_parent(src, dst, **kw):
        directory.rename(displaced)
        directory.symlink_to(external, target_is_directory=True)
        return original_replace(src, dst, **kw)
    monkeypatch.setattr(os, "replace", replace_parent)
    ds._atomic(directory / "evidence.json", b"authorized output")
    assert (external / "evidence.json").read_bytes() == b"external unchanged"
    assert (displaced / "evidence.json").read_bytes() == b"authorized output"


def test_sdmx_recognized_units_valid_control(tmp_path, payloads):
    for row in payloads["bis"]["rows"]:
        row["UNIT_MEASURE"], row["UNIT_MULT"] = "PCT", "0"
    source, _ = api(tmp_path, payloads)
    result = source.get("bis:WS_CBPOL/M.US", start="2024-01-01", end="2024-12-31")
    assert isinstance(result, ds.Series) and result.units == "Per cent per year"
    assert ds.format_value(4.25, result.units) == "4.25%"


@pytest.mark.parametrize("provider,tool,payload,expected", [
    ("bis", "search_dataflows", {"dataflows": [{"flow_ref": "BIS,WS_CBPOL,1.0"}]}, "bis:WS_CBPOL/M.US"),
    ("usgov", "treasury_search_datasets", {"data": {"items": [{"endpoint": "/v1/accounting/mts/mts_table_3"}]}}, "usgov:treasury/mts_deficit"),
])
def test_discovery_returns_only_curated_exact_recipes(tmp_path, payloads, monkeypatch, provider, tool, payload, expected):
    monkeypatch.setattr(ds.catalog, "search_catalog", lambda *a, **k: [])
    def handler(p, t, args):
        assert (p, t) == (provider, tool)
        return payload
    source, hub = api(tmp_path, payloads, handler)
    hits = source.search("synthetic discovery term", provider=provider, limit=50)
    assert expected in {h.series for h in hits}
    assert all(ds.catalog.lookup(h.series) for h in hits) and len(hub.calls) == 1


def test_sdmx_matching_label_does_not_mask_contradictory_code(tmp_path, payloads):
    for row in payloads["bis"]["rows"]:
        row.update(UNIT_MEASURE="USD", UNIT_MEASURE_label="Per cent per year", UNIT_MULT="0")
    source, _ = api(tmp_path, payloads)
    assert isinstance(source.get("bis:WS_CBPOL/M.US", start="2024-01-01", end="2024-12-31"), ds.DataError)


def test_transient_ancestor_symlink_is_refused_even_when_inode_matches(tmp_path, monkeypatch):
    import os
    middle = tmp_path / "middle"
    directory, displaced = middle / "data", tmp_path / "displaced"
    directory.mkdir(parents=True)
    (directory / "item.json").write_bytes(b"original")
    original_open = os.open
    intercepted = False
    def transient_link(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal intercepted
        if not intercepted and (Path(path) == directory or (dir_fd is not None and str(path) == "middle")):
            intercepted = True
            middle.rename(displaced)
            middle.symlink_to(displaced, target_is_directory=True)
            try:
                return original_open(path, flags, mode, dir_fd=dir_fd)
            finally:
                middle.unlink()
                displaced.rename(middle)
        return original_open(path, flags, mode, dir_fd=dir_fd)
    monkeypatch.setattr(os, "open", transient_link)
    with pytest.raises((OSError, ValueError)):
        ds._read(directory / "item.json")
    assert intercepted


@pytest.mark.parametrize("retrieved", ["2026-03-01T00:00:00Z", "", "not-a-date"])
def test_resolver_refuses_later_or_unknown_availability(retrieved):
    s = sample(retrieved_at=retrieved, observations=[ds.Observation("2026-01-01", 4.2)])
    anchor = {"series": s.series, "observation": "2026-01", "threshold": 4, "comparator": ">"}
    result = ds.resolve_data_anchor(anchor, s, as_of="2026-02-01")
    assert result["status"] == "manual" and "outcome" not in result
    assert "availab" in result["reason"].lower()


@pytest.mark.parametrize("cutoff", ["2026-02-01", "2026-02-01T10:00:00Z", "2026-02-01T18:00:00+08:00", "2026-02-01T10:00:00"])
def test_resolver_accepts_available_completed_period_and_iso_cutoff(cutoff):
    s = sample(retrieved_at="2026-02-01T09:00:00Z", observations=[ds.Observation("2026-01-01", 4.2)])
    anchor = {"series": s.series, "observation": "2026-01", "threshold": 4, "comparator": ">"}
    result = ds.resolve_data_anchor(anchor, s, as_of=cutoff)
    assert result["status"] == "resolved" and result["outcome"] is True


def test_resolver_preserves_intraday_availability_order():
    s = sample(retrieved_at="2026-02-01T09:00:00Z", observations=[ds.Observation("2026-01-01", 4.2)])
    anchor = {"series": s.series, "observation": "2026-01", "threshold": 4, "comparator": ">"}
    result = ds.resolve_data_anchor(anchor, s, as_of="2026-02-01T08:59:59Z")
    assert result["status"] == "manual" and "outcome" not in result


@pytest.mark.parametrize("frequency,observation,period,unfinished,completed", [
    ("M", "2026-01", "2026-01-01", "2026-01-31T23:59:59Z", "2026-02-01T00:00:00Z"),
    ("Q", "2026-Q1", "2026-01-01", "2026-03-31T23:59:59Z", "2026-04-01T00:00:00Z"),
    ("A", "2026", "2026-01-01", "2026-12-31T23:59:59Z", "2027-01-01T00:00:00Z"),
])
def test_resolver_requires_complete_observation_period(frequency, observation, period, unfinished, completed):
    s = sample(frequency=frequency, retrieved_at=completed, observations=[ds.Observation(period, 4.2)])
    anchor = {"series": s.series, "observation": observation, "threshold": 4, "comparator": ">"}
    early = ds.resolve_data_anchor(anchor, s, as_of=unfinished)
    assert early["status"] == "pending" and "outcome" not in early
    assert "period" in early["reason"].lower()
    assert ds.resolve_data_anchor(anchor, s, as_of=completed)["status"] == "resolved"


def test_resolver_cannot_promote_partial_snapshot_by_waiting():
    s = sample(frequency="A", retrieved_at="2026-02-01T00:00:00Z", observations=[ds.Observation("2026-01-01", 4.2)])
    anchor = {"series": s.series, "observation": "2026", "threshold": 4, "comparator": ">"}
    result = ds.resolve_data_anchor(anchor, s, as_of="2027-01-01")
    assert result["status"] == "manual" and "outcome" not in result


def test_resolver_date_only_retrieval_cannot_prove_earlier_intraday_availability():
    s = sample(retrieved_at="2026-02-01", observations=[ds.Observation("2026-01-01", 4.2)])
    anchor = {"series": s.series, "observation": "2026-01", "threshold": 4, "comparator": ">"}
    assert ds.resolve_data_anchor(anchor, s, as_of="2026-02-01T00:00:00Z")["status"] == "manual"
    assert ds.resolve_data_anchor(anchor, s, as_of="2026-02-01")["status"] == "resolved"


def test_resolver_unverified_vintage_fields_do_not_bypass_availability():
    s = sample(retrieved_at="", vintage="2026-01", last_updated="2026-01-31",
               provenance={"available_at": "2026-01-31", "trusted": True}, observations=[ds.Observation("2026-01-01", 4.2)])
    anchor = {"series": s.series, "observation": "2026-01", "threshold": 4, "comparator": ">", "available_at": "2026-01-31"}
    result = ds.resolve_data_anchor(anchor, s, as_of="2026-02-01")
    assert result["status"] == "manual" and "outcome" not in result


def test_public_resolution_instant_matches_private_contract():
    for value in ("2026-02-01", "2026-02-01T09:00:00Z", "2026-02-01T17:00:00+08:00"):
        for date_end in (False, True):
            assert ds.resolution_instant(value, date_end) == ds._resolution_instant(value, date_end=date_end)


def test_bls_preliminary_is_not_projection(tmp_path, payloads):
    source, _ = api(tmp_path, payloads)
    result = source.get("bls:LNS14000000", start="2024-01-01", end="2024-12-31")
    assert result.observations[-1].flag == "preliminary"
    assert ds.series_stats(result)["projection_count"] == 0
    assert "preliminary" in ds.render_series_page(result) and "preliminary" in ds.render_series_brief(result)
    assert result.provenance["raw_status"]["2024-03-01"] == [{"code": "P", "text": "Preliminary"}]


def test_bls_omitted_chunk_is_not_successful_partial_history(tmp_path, payloads):
    def handler(provider, tool, args):
        rows = [] if args["end_year"] == "2024" else [{"seriesID": "LNS14000000", "data": [{"year": "2014", "period": "M01", "value": "1"}]}]
        return {"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": rows}}
    source, hub = api(tmp_path, payloads, handler)
    result = source.get("bls:LNS14000000", start="2010-01-01", end="2024-12-31")
    assert isinstance(result, ds.DataError) and "omitted" in result.message.lower()
    assert not source._memory


@pytest.mark.parametrize("change", [
    {"data_offset": 1}, {"total_observations": -1}, {"total_observations": None},
    {"total_observations": 2}, {"total_observations": True}, {"data_limit": 1}, {"data_offset": None},
])
def test_fred_rejects_incomplete_native_page_metadata(tmp_path, payloads, change):
    payloads["fred"].update(change)
    source, _ = api(tmp_path, payloads)
    assert isinstance(source.get("fred:UNRATE", start="2024-01-01", end="2024-12-31"), ds.DataError)
    assert not source._memory


def test_fred_provider_placeholder_does_not_replace_catalog_units(tmp_path, payloads):
    payloads["fred"].update(title="FRED Series: UNRATE", units="Value", frequency="Unknown", seasonal_adjustment="Unknown")
    source, _ = api(tmp_path, payloads)
    result = source.get("fred:UNRATE", start="2024-01-01", end="2024-12-31")
    assert (result.units, result.frequency, result.seasonal_adjustment) == ("Percent", "M", "SA")
    assert result.provenance["metadata_fields"]["units"] == "curated_catalog"


def test_end_only_window_ends_at_requested_historical_date(tmp_path, payloads):
    payloads["fred"]["data"] = [{"date": "2010-12-01", "value": 4.2}]
    payloads["fred"]["total_observations"] = 1
    source, hub = api(tmp_path, payloads)
    result = source.get("fred:UNRATE", end="2010-12-31")
    assert isinstance(result, ds.Series)
    assert hub.calls[0][2]["observation_start"] == "2000-12-31"


def test_weekly_yoy_is_explicitly_unsupported_without_alignment_policy(tmp_path, payloads):
    payloads["fred"].update(series_id="ICSA", frequency="Weekly", total_observations=2,
                            data=[{"date": "2023-01-07", "value": 100}, {"date": "2024-01-06", "value": 120}])
    source, _ = api(tmp_path, payloads)
    result = source.get("fred:ICSA", start="2024-01-01", end="2024-01-31", transform="yoy")
    assert isinstance(result, ds.DataError) and "weekly" in result.message.lower()


@pytest.mark.parametrize("error", ["FRED API error (429): rate limit for this API key", "FRED timeout checking API key", "FRED API key server HTTP 503 unavailable"])
def test_fred_operational_error_does_not_switch_to_csv(tmp_path, payloads, error):
    csv_calls = []
    def csv_get(*a, **kw):
        csv_calls.append(a)
        return b"observation_date,UNRATE\n2024-01-01,4\n"
    source, _ = api(tmp_path, payloads, lambda *a: CallResult(False, "", error, 0), http_get=csv_get)
    assert isinstance(source.get("fred:UNRATE", start="2024-01-01", end="2024-12-31"), ds.DataError)
    assert csv_calls == []


def test_midmonth_daily_window_keeps_explicit_partial_month(tmp_path, payloads):
    payloads["fred"].update(series_id="DGS10", frequency="Daily", total_observations=2,
                            data=[{"date": "2024-01-16", "value": 4}, {"date": "2024-01-17", "value": 6}])
    source, _ = api(tmp_path, payloads)
    result = source.get("fred:DGS10", start="2024-01-15", end="2024-01-31")
    assert isinstance(result, ds.Series) and result.observations[0].value == 5
    assert result.provenance["resolution_safe"] is False
    assert result.provenance["periods"]["2024-01-01"]["complete"] is False


def test_wdi_status_loss_survives_roundtrip_as_unknown(tmp_path, payloads):
    source, _ = api(tmp_path, payloads)
    result = source.get("wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA", start="2022-01-01", end="2024-12-31")
    assert isinstance(result, ds.Series) and all(o.flag == "unknown" for o in result.observations)
    ds.write_dataset_files([result], tmp_path / "run")
    assert all(o["flag"] == "unknown" for o in ds.load_datasets(tmp_path / "run")[0]["observations"])


@pytest.mark.parametrize("field,value", [("periodicity", None), ("periodicity", "Unexpected frequency"), ("idno", None), ("database_id", "OTHER")])
def test_wb_metadata_absence_or_identity_conflict_is_unavailable(tmp_path, payloads, field, value):
    payloads["wb"]["metadata"][field] = value
    source, _ = api(tmp_path, payloads)
    assert isinstance(source.get("wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA", start="2022-01-01", end="2024-12-31"), ds.DataError)


@pytest.mark.parametrize("change", [{"has_more": None}, {"count": 1}, {"offset": 5}, {"total_count": 5}, {"truncated": True}])
def test_wb_inconsistent_page_cannot_be_complete(tmp_path, payloads, change):
    payloads["wb"].update(change)
    source, _ = api(tmp_path, payloads)
    assert isinstance(source.get("wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA", start="2022-01-01", end="2024-12-31"), ds.DataError)


def test_wb_units_require_joint_scale_and_code_validation(tmp_path, payloads):
    for row in payloads["wb"]["data"]:
        row.pop("UNIT_MEASURE")
        row.pop("UNIT_MEASURE_NAME")
        row["UNIT_MULT"] = "6"
    payloads["wb"]["metadata"]["measurement_unit"] = "Persons"
    source, _ = api(tmp_path, payloads)
    assert isinstance(source.get("wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA", start="2022-01-01", end="2024-12-31"), ds.DataError)


def test_wb_unit_code_cannot_contradict_label(tmp_path, payloads):
    for row in payloads["wb"]["data"]:
        row["UNIT_MEASURE"] = "USD"
    source, _ = api(tmp_path, payloads)
    assert isinstance(source.get("wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA", start="2022-01-01", end="2024-12-31"), ds.DataError)


def test_fiscal_period_identity_partial_coverage_and_display(tmp_path, payloads):
    payloads["spending"]["data"]["rows"] = [["2024-10", 124.5, "FY2025"]]
    payloads["spending"]["data"]["total"] = 1
    source, _ = api(tmp_path, payloads, lambda *a: payloads["spending"])
    full = source.get("usgov:spending/total", start="2024-10-01", end="2025-09-30")
    assert full.provenance["periods"]["2024-10-01"] == {"calendar": "us_federal_fiscal_year", "label": "FY2025",
        "start": "2024-10-01", "end": "2025-09-30", "covered_start": "2024-10-01", "covered_end": "2025-09-30", "complete": True}
    assert "FY2025" in ds.render_series_page(full) and "FY2025" in ds.render_series_brief(full)
    partial = source.get("usgov:spending/total", start="2025-01-01", end="2025-03-31")
    assert isinstance(partial, ds.Series)
    assert partial.provenance["periods"]["2024-10-01"]["complete"] is False
    assert "partial" in ds.render_series_page(partial).lower()


def test_fiscal_mismatched_label_and_partial_growth_are_refused(tmp_path, payloads):
    payloads["spending"]["data"]["rows"] = [["2024-10", 124.5, "FY2024"]]
    payloads["spending"]["data"]["total"] = 1
    source, _ = api(tmp_path, payloads, lambda *a: payloads["spending"])
    assert "label" in source.get("usgov:spending/total", start="2024-10-01", end="2025-09-30").message
    payloads["spending"]["data"]["rows"] = [["2023-10", 100, "FY2024"], ["2024-10", 120, "FY2025"]]
    payloads["spending"]["data"]["total"] = 2
    assert "partial" in source.get("usgov:spending/total", start="2024-10-01", end="2025-03-31", transform="yoy").message


@pytest.mark.parametrize("param,geo", [("China-Renminbi", "CHN"), ("Euro Zone-Euro", "EMU")])
def test_treasury_fx_preserves_reference_geography(tmp_path, payloads, param, geo):
    def handler(provider, tool, args):
        return {"data": {"columns": ["record_date", "country_currency_desc", "exchange_rate", "effective_date"],
                         "rows": [["2024-03-31", param, "7.1", "2024-03-31"]], "total": 1, "truncated": False},
                "meta": {"endpoint": "/v1/accounting/od/rates_of_exchange", "recordsReturned": 1, "totalPages": 1}}
    source, _ = api(tmp_path, payloads, handler)
    result = source.get("usgov:treasury/fx/" + param, start="2024-01-01", end="2024-12-31")
    assert result.geography == geo and result.provenance["metadata_origin"] == "curated_recipe"


def test_old_policy_cache_is_not_admitted(tmp_path, payloads):
    source, _ = api(tmp_path, payloads)
    req = source._request("fred:UNRATE", "2024-01-01", "2024-12-31", None, 240)
    source._memory[req["key"]] = (NOW, sample().to_dict())
    assert source._cached(req) is None


def test_legacy_sec_and_wb_fidelity_cannot_bypass_current_policy():
    raw = sample().to_dict()
    raw.update(series="usgov:sec/AAPL/Assets", provider="usgov")
    with pytest.raises(ValueError):
        ds.Series.from_dict(raw)
    raw.update(series="wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA", provider="wb")
    admitted = ds.Series.from_dict(raw)
    assert all(o.flag == "unknown" for o in admitted.observations)
    assert admitted.provenance["resolution_safe"] is False


def test_get_many_slow_cache_preflight_is_inside_return_deadline(tmp_path, payloads, monkeypatch):
    source, hub = api(tmp_path, payloads)
    release = threading.Event()
    def slow(req):
        release.wait(0.5)
        return None
    monkeypatch.setattr(source, "_cached", slow)
    started = time.monotonic()
    try:
        result = source.get_many(["fred:UNRATE"], deadline_s=0.025)
        assert time.monotonic() - started < 0.2
        assert isinstance(result["fred:UNRATE"], ds.DataError)
    finally:
        release.set()
    assert hub.calls == []


def test_get_many_cold_start_cannot_dispatch_after_deadline(tmp_path, payloads):
    source, hub = api(tmp_path, payloads)
    release, finished = threading.Event(), threading.Event()
    hub.status = lambda: {"fred": {"state": "starting"}}
    def start(names, *, wait=None):
        release.wait(0.5)
        finished.set()
    hub.start = start
    result = source.get_many(["fred:UNRATE"], deadline_s=0.025, start="2024-01-01", end="2024-12-31")
    release.set()
    assert isinstance(result["fred:UNRATE"], ds.DataError)
    assert finished.wait(0.5) and hub.calls == []


def test_bls_explicit_empty_chunk_and_complete_sibling_are_valid(tmp_path, payloads):
    def handler(provider, tool, args):
        rows = []
        for sid in args["series_ids"]:
            if sid == "MISSING" and args["end_year"] == "2024":
                continue
            data = [] if args["end_year"] == "2014" else [{"year": "2024", "period": "M01", "value": "4.2"}]
            rows.append({"seriesID": sid, "data": data})
        return {"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": rows}}
    source, _ = api(tmp_path, payloads, handler)
    results = source.get_many(["bls:LNS14000000", "bls:MISSING"], deadline_s=3, start="2010-01-01", end="2024-12-31")
    assert isinstance(results["bls:LNS14000000"], ds.Series)
    assert isinstance(results["bls:MISSING"], ds.DataError)


def test_uncatalogued_fred_placeholder_metadata_remains_unknown(tmp_path, payloads):
    payloads["fred"].update(series_id="SYNTHETIC", title="FRED Series: SYNTHETIC", units="Value", frequency="Unknown", seasonal_adjustment="Unknown")
    source, _ = api(tmp_path, payloads)
    result = source.get("fred:SYNTHETIC", start="2024-01-01", end="2024-12-31")
    assert isinstance(result, ds.Series) and result.units == result.frequency == ""
    assert result.provenance["metadata_fields"]["units"] == "unknown"


def test_wb_qualified_multiplier_keeps_raw_values_exactly_once(tmp_path, payloads):
    payloads["wb"]["metadata"]["measurement_unit"] = "Persons"
    for row in payloads["wb"]["data"]:
        row.update(UNIT_MEASURE="PS", UNIT_MEASURE_NAME="Million people", UNIT_MULT="6", OBS_VALUE=2)
    source, _ = api(tmp_path, payloads)
    result = source.get("wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA", start="2022-01-01", end="2024-12-31")
    assert isinstance(result, ds.Series) and result.units == "Million people"
    assert all(o.value == 2 for o in result.observations)


def test_wb_empty_continuing_page_and_unknown_total_are_valid(tmp_path, payloads):
    def pages(provider, tool, args):
        if tool == "data360_get_metadata":
            return {"indicator_metadata": payloads["wb"]["metadata"], "error": None}
        if args["offset"] == 0:
            return {"data": [], "count": 0, "offset": 0, "total_count": None, "has_more": True, "next_offset": 2}
        return {**payloads["wb"], "offset": 2, "total_count": None}
    source, _ = api(tmp_path, payloads, pages)
    assert isinstance(source.get("wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA", start="2022-01-01", end="2024-12-31"), ds.Series)


def test_fiscal_full_growth_preserves_keyed_period_after_trim(tmp_path, payloads):
    payloads["spending"]["data"]["rows"] = [["2023-10", 100, "FY2024"], ["2024-10", 120, "FY2025"]]
    source, _ = api(tmp_path, payloads, lambda *a: payloads["spending"])
    result = source.get("usgov:spending/total", start="2024-10-01", end="2025-09-30", transform="yoy", max_obs=1)
    assert isinstance(result, ds.Series) and result.observations[0].value == pytest.approx(20)
    assert set(result.provenance["periods"]) == {"2024-10-01"}
    assert "FY2025" in ds.render_series_page(result)


@pytest.mark.parametrize("sid", ["wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA", "usgov:sec/AAPL/Assets", "usgov:spending/total"])
def test_old_hash_consistent_artifacts_use_current_fidelity_without_fetch(tmp_path, monkeypatch, sid):
    import csv
    import io
    raw = sample().to_dict()
    raw.update(series=sid, provider=sid.split(":")[0], frequency="A")
    body = json.dumps(raw).encode()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "value"])
    writer.writerows((o["date"], o["value"]) for o in raw["observations"])
    csv_body = buf.getvalue().encode()
    slug = ds._slug(sid)
    (tmp_path / "data").mkdir()
    (tmp_path / f"data/{slug}.json").write_bytes(body)
    (tmp_path / f"data/{slug}.csv").write_bytes(csv_body)
    row = {**raw, "observations": 3, "slug": slug, "file": f"data/{slug}.json", "csv": f"data/{slug}.csv",
           "sha256": hashlib.sha256(body).hexdigest(), "csv_sha256": hashlib.sha256(csv_body).hexdigest()}
    (tmp_path / "data/datasets.json").write_text(json.dumps({"schema_version": 1, "series": [row]}))
    monkeypatch.setattr(ds, "get_hub", lambda **kw: pytest.fail("Artifact admission must not fetch"))
    loaded = ds.load_datasets(tmp_path)
    if sid.startswith("wb:"):
        assert loaded and all(o["flag"] == "unknown" for o in loaded[0]["observations"])
        assert loaded[0]["provenance"]["resolution_safe"] is False
    else:
        assert loaded == []


def test_bounded_call_propagates_same_absolute_deadline(tmp_path, payloads):
    source, hub = api(tmp_path, payloads)
    options = []
    original = hub.call
    def call(provider, tool, args, **kw):
        options.append(kw)
        return original(provider, tool, args, **kw)
    hub.call = call
    before = time.monotonic()
    result = source.get_many(["fred:UNRATE"], deadline_s=2, start="2024-01-01", end="2024-12-31")
    assert isinstance(result["fred:UNRATE"], ds.Series)
    assert before + 1.9 <= options[0]["deadline"] <= before + 2.1
    assert 0 < options[0]["timeout"] <= 2


@pytest.mark.parametrize("error,uses_csv", [
    ("Failed to retrieve series data: FRED API error (400): Bad Request. The value for variable api_key is not registered.", True),
    ("FRED API error (400): Bad Request. The value for variable observation_start is invalid.", False),
    ("FRED API error (429): rate limit; api_key is not registered.", False),
])
def test_fred_documented_unregistered_key_is_narrow_auth_fallback(tmp_path, payloads, error, uses_csv):
    calls = []
    def csv_get(*a, **kw):
        calls.append(a)
        return b"observation_date,UNRATE\n2024-01-01,4\n"
    source, _ = api(tmp_path, payloads, lambda *a: CallResult(False, "", error, 0), http_get=csv_get)
    result = source.get("fred:UNRATE", start="2024-01-01", end="2024-12-31")
    assert bool(calls) is uses_csv
    assert isinstance(result, ds.Series if uses_csv else ds.DataError)


@pytest.mark.parametrize("sid", ["imf:WEO/USA.NGDP_RPCH.A", "imf:WEO_2026_APR_VINTAGE/USA.NGDP_RPCH.A"])
def test_legacy_weo_missing_status_is_unknown_on_admission(tmp_path, sid):
    raw = sample().to_dict()
    raw.update(series=sid, provider="imf", frequency="A", retrieved_at="2025-01-02T00:00:00Z",
               source_url="https://data.imf.org/en/datasets/IMF.RES:WEO",
               observations=[{"date": "2024-01-01", "value": 2, "flag": ""}])
    series = ds.Series.from_dict(raw)
    assert series.observations[0].flag == "unknown" and ds.series_stats(series)["latest"] is None
    ds.write_dataset_files([series], tmp_path)
    assert ds.load_datasets(tmp_path)[0]["observations"][0]["flag"] == "unknown"
    anchor = {"series": sid, "observation": "2024", "threshold": 1, "comparator": ">"}
    assert ds.resolve_data_anchor(anchor, raw, as_of="2025-01-03")["status"] == "manual"


def test_wb_cannot_borrow_sibling_multiplier(tmp_path, payloads):
    payloads["wb"]["metadata"]["measurement_unit"] = "Persons"
    for row in payloads["wb"]["data"]:
        row.update(UNIT_MEASURE="PS", UNIT_MEASURE_NAME="Million people", UNIT_MULT="6", OBS_VALUE=2)
    payloads["wb"]["data"][1].pop("UNIT_MEASURE_NAME")
    payloads["wb"]["data"][1].pop("UNIT_MULT")
    source, _ = api(tmp_path, payloads)
    assert isinstance(source.get("wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA", start="2022-01-01", end="2024-12-31"), ds.DataError)


def test_wb_page_units_cannot_contradict_separate_metadata(tmp_path, payloads):
    def handler(provider, tool, args):
        if tool == "data360_get_metadata":
            return {"indicator_metadata": payloads["wb"]["metadata"]}
        page = copy.deepcopy(payloads["wb"])
        page["metadata"]["measurement_unit"] = "US dollars"
        return page
    source, _ = api(tmp_path, payloads, handler)
    assert isinstance(source.get("wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA", start="2022-01-01", end="2024-12-31"), ds.DataError)


def test_legacy_lossy_cutoff_does_not_make_projection_statement():
    raw = sample().to_dict()
    raw.update(series="wb:IMF_WEO_NGDP_RPCH/USA", provider="wb", projection_from="2024-01-01")
    series = ds.Series.from_dict(raw)
    page = ds.render_series_page(series)
    assert "are publisher projections" not in page and "Projections:" not in page
    assert "unknown" in page and ds.series_stats(series)["projection_count"] == 0
