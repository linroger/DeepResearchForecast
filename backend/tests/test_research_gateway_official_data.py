"""Official-data tools of the v3 research gateway (data_search / data_get / prefetch).

Covers the fix contract for slice C (docs/handoff/data-sources-mcp/fix-plan.md):
run dataset caps per preset with a bounded seeder (F13, V3-M1), agent-facing
failure reasons and retry semantics (F14, P-TEXT, F19), window handling
(F19, V3-M4), KIQ links on stored series (RPT-8), persistence failures and
resume (F9, M4), shared publisher pages (F11), geography-qualified ledger
titles (F10) and the static tool schema (F20).

Only the DataSources boundary is replaced.  Its answers are real normalized
series captured live on 2026-10-11 (fixtures/data_sources/real/gateway); the
gateway, ledger, pages and dataset manifest are the real ones.  Bridge modules
are imported by bare name (see test_research_gateway.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import pytest

_BRIDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import research_gateway as rg  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "data_sources" / "real" / "gateway" / "series-2026-10-11.json"
# sha256 of the web-only tool list at eac717b: runs without official data send it unchanged.
WEB_SCHEMA_SHA256 = "ade874b5c6dbd8ad2803e8e11a6888eade789a8b3b20e162fe12ad60815af25f"
# Verbatim FRED tool error for HTTP 429 (datamcps/fred-mcp-server-main/src/common/fred-client.ts).
FRED_429 = ('Failed to retrieve series data: FRED API error (429): '
            '{"error_code":429,"error_message":"Too Many Requests.  Exceeded Rate Limit"}')
WEO_PAGE = "https://data360.worldbank.org/en/indicator/IMF_WEO_NGDP_RPCH"
FRED_IDS = ["UNRATE", "GDP", "PAYEMS", "CPIAUCSL", "FEDFUNDS", "DGS10", "DGS2", "T10Y2Y", "INDPRO",
            "HOUST", "RSAFS", "PCEPI"]


@pytest.fixture
def api():
    import data_sources
    return data_sources


@pytest.fixture(scope="module")
def captured():
    return {row["series"]: row for row in json.loads(FIXTURE.read_text("utf-8"))["series"]}


class Sources:
    """The DataSources boundary: real captured series, scripted failures first.

    As in DataSources, an unknown (or empty) provider selects nothing and an
    empty date is an invalid request; every answer is a fresh Series object.
    """

    def __init__(self, api, captured, *, hits=(), script=None):
        self.api, self.captured, self.hits = api, captured, list(hits)
        self.script = {key: list(values) for key, values in (script or {}).items()}
        self.calls: list[tuple] = []

    def series(self, identity):
        base, _, transform = identity.partition("#")
        native = base.split(":", 1)[1]
        row = self.captured.get(base) or {**self.captured["fred:UNRATE"], "series": base, "title": native,
                                          "source_url": "https://fred.stlouisfed.org/series/" + native}
        if transform:
            row = {**row, "series": identity, "transform": transform, "units": "Percent change from year ago"}
        return self.api.Series.from_dict(row)

    def search(self, query, *, provider=None, limit=6, deadline_s=None):
        self.calls.append(("search", query, provider))
        if provider is not None and provider not in self.api.PROVIDERS:
            return []
        return list(self.hits)[:limit]

    def get(self, series, *, start=None, end=None, transform=None, max_obs=240, deadline_s=None):
        identity = series + ("#" + transform if transform else "")
        self.calls.append(("get", identity, start, end))
        scripted = self.script.get(identity)
        if scripted:
            answer = scripted.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return answer
        if start == "" or end == "":
            return self.api.DataError(series, "start/end must be dates such as YYYY-MM-DD. Check the series ID, "
                                      "dates (YYYY-MM-DD) and max_obs.", False, "invalid_input")
        return self.series(identity)

    def get_many(self, identities, *, deadline_s, **kwargs):
        return {identity: self.get(identity, **kwargs) for identity in identities}

    def gets(self):
        return [call for call in self.calls if call[0] == "get"]


def make_tools(root: Path, source, limits=None, **kwargs):
    ledger = rg.SourceLedger(root / "v3" / "sources_ledger.json")
    return rg.ResearchTools(ledger, root / "v3" / "pages", data_sources=source, limits=limits,
                            fetch_fn=lambda url: pytest.fail(f"unexpected web fetch of {url}"), **kwargs)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ F20 schema
def test_data_tool_schema_documents_ids_providers_and_windows_and_web_schema_is_unchanged(api):
    web = json.dumps(rg.AGENT_TOOLS_SCHEMA, sort_keys=True, ensure_ascii=False)
    assert sha(web) == WEB_SCHEMA_SHA256
    assert rg.AGENT_TOOLS_WITH_DATA_SCHEMA[:2] == rg.AGENT_TOOLS_SCHEMA
    tools = {entry["function"]["name"]: entry["function"] for entry in rg.AGENT_TOOLS_WITH_DATA_SCHEMA[2:]}
    assert sorted(tools) == ["data_get", "data_search"]
    search, get = tools["data_search"]["parameters"], tools["data_get"]["parameters"]
    assert search["properties"]["provider"]["enum"] == list(api.PROVIDERS) == list(rg.DATA_PROVIDERS)
    assert get["properties"]["transform"]["enum"] == ["yoy", "pct"]
    assert (search["required"], get["required"]) == (["query"], ["series"])
    for params in (search, get):
        assert all(spec.get("description") for spec in params["properties"].values())
    # Rendered KIQs (glue U1-v3): searches for China NEV share or world chip sales
    # return other concepts (energy use, military exports); none is a proxy.
    assert ("only for a result whose title, units and geography measure the statistic you need (another "
            "concept or place is no proxy)") in tools["data_search"]["description"]
    examples = [match.rstrip(".") for match in
                re.findall(r"\b(?:fred|bls|bis|imf|wb|usgov):[^\s,]+", get["properties"]["series"]["description"])]
    assert len(examples) >= 6 and all(api.parse_series_id(example) for example in examples)
    # Static text only: one cached tool prefix for every data-enabled run.
    assert not re.search(r"\d{4}-\d{2}-\d{2}|\$|\{[a-z_]+\}", json.dumps(rg.AGENT_TOOLS_WITH_DATA_SCHEMA))


# ------------------------------------------------- F13 / V3-M1 caps and seeder
def test_dataset_cap_scales_by_preset_and_prefetch_leaves_agents_room(tmp_path, api, captured):
    assert [rg.dataset_cap(depth, {}) for depth in ("quick", "standard", "deep", "other")] == [10, 16, 24, 16]
    assert rg.dataset_cap("quick", {"DATA_SOURCES_MAX_SERIES": "30"}) == 30
    assert rg.dataset_cap("deep", {"DATA_SOURCES_MAX_SERIES": "many"}) == 24
    assert rg.dataset_cap("deep", {"DATA_SOURCES_MAX_SERIES": "900"}) == rg.MAX_RUN_DATASETS
    with pytest.raises(ValueError):
        rg.ToolLimits(max_datasets=rg.MAX_RUN_DATASETS + 1)
    # The quick preset's data budget (linear_research: 24 calls, 3 per KIQ agent).
    limits = rg.ToolLimits(max_data_calls_total=24, max_data_calls_per_agent=3, max_datasets=rg.dataset_cap("quick", {}))
    assert (limits.max_prefetch_datasets, limits.max_seeder_data_calls) == (6, 18)
    hit = api.SearchHit("fred:UNRATE", "Unemployment Rate", "Percent", "M", "", "fred", "")
    source = Sources(api, captured, hits=[hit])
    tools = make_tools(tmp_path, source, limits)
    for n in range(12):
        assert tools.data_search(f"labour market need {n}", agent_id=rg.DATA_SEEDER).startswith("fred:UNRATE")
    ids = ["fred:" + name for name in FRED_IDS]
    result = tools.prefetch_data(ids, deadline=rg.Deadline(30))
    assert [identity for identity in ids if result[identity].startswith("[S")] == ids[:6]
    assert all(result[identity].startswith("DATA_BUDGET_EXHAUSTED: prefetch limit") for identity in ids[6:])
    # Seeder calls never spend the agents' budget: every KIQ agent keeps all
    # of its calls, and the cap leaves room for one new series each.
    for n, identity in enumerate(ids[6:10], start=1):
        assert tools.data_get(identity, agent_id=f"K{n}").startswith("[S")
        for query in ("policy rate", "payrolls"):
            assert tools.data_search(f"{query} K{n}", agent_id=f"K{n}").startswith("fred:UNRATE")
    assert tools.data_search("one more", agent_id="K1").startswith("DATA_BUDGET_EXHAUSTED")
    assert len(tools.data_rows()) == 10
    refused = tools.data_get(ids[10], agent_id="K5")
    assert refused.startswith("DATA_BUDGET_EXHAUSTED") and "10 official series" in refused
    stats = tools.data_stats()
    assert (stats["dataset_cap"], stats["prefetch_cap"], stats["seeder_calls"], stats["calls"]) == (10, 6, 18, 30)
    assert stats["per_agent"][rg.DATA_SEEDER] == 18


def test_seeder_windowed_get_counts_toward_the_prefetch_cap_and_links_its_kiqs(tmp_path, api, captured):
    source = Sources(api, captured)
    tools = make_tools(tmp_path, source, rg.ToolLimits(max_datasets=5))  # prefetch cap 3
    assert tools.data_get("fred:UNRATE", start="1990", agent_id=rg.DATA_SEEDER, kiqs=["K2"]).startswith("[S1]")
    assert source.gets()[-1] == ("get", "fred:UNRATE", "1990-01-01", None)
    result = tools.prefetch_data(["fred:GDP", "fred:PAYEMS", "fred:CPIAUCSL"], deadline=rg.Deadline(10),
                                 kiqs={"fred:GDP": ["K1"]})
    assert [result[key][:4] for key in ("fred:GDP", "fred:PAYEMS")] == ["[S2]", "[S3]"]
    assert result["fred:CPIAUCSL"].startswith("DATA_BUDGET_EXHAUSTED: prefetch limit")
    assert tools.data_get("fred:INDPRO", agent_id=rg.DATA_SEEDER).startswith("DATA_BUDGET_EXHAUSTED: prefetch limit")
    assert tools.data_get("fred:INDPRO", agent_id="K1").startswith("[S4]")  # agents keep the rest of the cap
    kiqs = {row["series"]: row["kiqs"] for row in api.load_datasets(tmp_path / "v3")}
    assert kiqs == {"fred:UNRATE": ["K2"], "fred:GDP": ["K1"], "fred:PAYEMS": [], "fred:INDPRO": ["K1"]}
    # A resumed run counts the seeder's stored series against the same cap.
    resumed = make_tools(tmp_path, source, rg.ToolLimits(max_datasets=5))
    resumed.restore_data()
    assert resumed.prefetch_data(["fred:CPIAUCSL"], deadline=rg.Deadline(10))["fred:CPIAUCSL"].startswith(
        "DATA_BUDGET_EXHAUSTED: prefetch limit")


# ----------------------------------------------------------- RPT-8 KIQ links
def test_requesting_kiqs_accumulate_on_the_stored_series_without_changing_evidence(tmp_path, api, captured):
    source = Sources(api, captured)
    tools = make_tools(tmp_path, source)
    page = tools.prefetch_data(["fred:UNRATE"], deadline=rg.Deadline(10),
                               kiqs={"fred:UNRATE": ["K1", "K3", "K1"]})["fred:UNRATE"]
    assert page.startswith("[S1]")
    content = tools.ledger.get(1)["content_sha256"]
    assert tools.data_get("fred:UNRATE", agent_id="K2") == page
    assert tools.data_get("fred:UNRATE", agent_id="K3") == page
    [row] = api.load_datasets(tmp_path / "v3")
    assert row["kiqs"] == ["K1", "K3", "K2"] and row["source_id"] == "S1"
    assert tools.ledger.get(1)["content_sha256"] == content == sha(tools.page_text(1))
    assert len(source.gets()) == 1
    resumed = make_tools(tmp_path, source)
    resumed.restore_data()
    assert [series.kiqs for series, _ in resumed.data_rows()] == [["K1", "K3", "K2"]]
    assert tools.data_stats()["per_kiq"]["K2"] == {"requested": ["fred:UNRATE"], "stored": ["fred:UNRATE"],
                                                  "failed": []}


# ------------------------------------------------- F14 / P-TEXT / F19 failures
def test_failure_reason_reaches_the_agent_and_retryable_failures_are_asked_again(tmp_path, api, captured):
    limited = api.DataError("fred:UNRATE", FRED_429 + ". Retry in a minute and avoid request bursts.", True,
                            "rate_limited")
    missing = api.DataError("fred:NOSUCH", "Provider returned no observations for the requested series. Check the "
                            "ID, geography and window, or search for another series.", False, "not_found")
    source = Sources(api, captured, script={"fred:UNRATE": [limited], "fred:NOSUCH": [missing]})
    tools = make_tools(tmp_path, source)
    first = tools.data_get("fred:UNRATE", agent_id="K1")
    assert first == limited.unavailable_text()
    assert first.startswith("DATA_UNAVAILABLE[rate_limited]: Failed to retrieve series data: FRED API error (429)")
    assert tools.data_get("fred:UNRATE", agent_id="K2").startswith("[S1]")
    gone = tools.data_get("fred:NOSUCH", agent_id="K1")
    assert gone == missing.unavailable_text()
    assert tools.data_get("fred:NOSUCH", agent_id="K2") == gone  # a deterministic answer is reused for free
    assert len(source.gets()) == 3
    stats = tools.data_stats()
    assert stats["failures"] == 2 and stats["cached"] == 1
    assert [(row["request"], row["code"], row["retryable"], row["by"]) for row in stats["failed_requests"]] == [
        ("fred:UNRATE", "rate_limited", True, "K1"), ("fred:NOSUCH", "not_found", False, "K1")]
    assert stats["per_kiq"]["K1"] == {"requested": ["fred:UNRATE", "fred:NOSUCH"], "stored": [],
                                      "failed": ["fred:UNRATE", "fred:NOSUCH"]}


def test_exceptions_are_classified_without_echoing_provider_text(tmp_path, api, captured):
    timeout = TimeoutError("read timed out for https://api.stlouisfed.org/?api_key=do-not-expose-123456")
    source = Sources(api, captured, script={"fred:UNRATE": [timeout]})
    tools = make_tools(tmp_path, source)
    output = tools.data_get("fred:UNRATE", agent_id="K1")
    assert output.startswith("DATA_UNAVAILABLE[timeout]: ") and "do-not-expose" not in output
    assert tools.data_get("fred:UNRATE", agent_id="K2").startswith("[S1]")


def test_prefetch_failures_carry_their_reason_class(tmp_path, api, captured):
    # Data360 unit validation failure as raised before the P-UNITS pins (review K2).
    units = api.DataError("wb:IMF_WEO_NGDP_RPCH/USA", "Data360 response has ambiguous disaggregations. Use another "
                          "series or source.", False, "provider_error")
    source = Sources(api, captured, script={"wb:IMF_WEO_NGDP_RPCH/USA": [units]})
    tools = make_tools(tmp_path, source)
    result = tools.prefetch_data(["wb:IMF_WEO_NGDP_RPCH/USA", "fred:UNRATE"], deadline=rg.Deadline(10))
    assert result["wb:IMF_WEO_NGDP_RPCH/USA"] == units.unavailable_text()
    assert result["fred:UNRATE"].startswith("[S1]")
    assert tools.data_stats()["failed_requests"][0]["by"] == rg.DATA_SEEDER


@pytest.mark.parametrize("series, transform, code", [
    ("usgov:treasury/not_a_recipe", None, "unknown_recipe"),
    ("UNRATE", None, "unknown_series"),
    ("fred:UNRATE", "log", "unsupported_transform"),
    ("fred:UNRATE#yoy", "pct", "unsupported_transform"),
])
def test_invalid_requests_name_their_reason_without_a_provider_call(tmp_path, api, captured, series, transform, code):
    source = Sources(api, captured)
    tools = make_tools(tmp_path, source)
    assert tools.data_get(series, transform=transform, agent_id="K1").startswith(f"DATA_UNAVAILABLE[{code}]: ")
    assert source.calls == [] and tools.data_stats()["calls"] == 0


def test_empty_optional_arguments_mean_not_given_and_never_poison_later_calls(tmp_path, api, captured):
    hit = api.SearchHit("fred:UNRATE", "Unemployment Rate", "Percent", "M", "", "fred", "")
    source = Sources(api, captured, hits=[hit])
    tools = make_tools(tmp_path, source)
    assert tools.data_search("US unemployment rate", provider="", agent_id="K1").startswith("fred:UNRATE — ")
    assert tools.data_search("US unemployment rate", agent_id="K2").startswith("fred:UNRATE — ")
    assert source.calls == [("search", "US unemployment rate", None)]
    unknown = tools.data_search("US unemployment rate", provider="worldbank", agent_id="K3")
    assert unknown.startswith("DATA_UNAVAILABLE[invalid_input]: ") and "fred, bls, bis, imf, wb, usgov" in unknown
    assert tools.data_get("fred:UNRATE", start="", end=" ", transform="", agent_id="K1").startswith("[S1]")
    assert source.gets() == [("get", "fred:UNRATE", None, None)]


def test_an_empty_search_is_not_remembered(tmp_path, api, captured):
    source = Sources(api, captured)
    tools = make_tools(tmp_path, source)
    assert tools.data_search("semiconductor capacity utilization", agent_id="K1").startswith("NO_DATA_MATCH")
    source.hits = [api.SearchHit("fred:CAPUTLG3344S", "Capacity Utilization: Semiconductor", "Percent of Capacity",
                                 "M", "", "fred", "")]
    assert tools.data_search("semiconductor capacity utilization", agent_id="K2").startswith("fred:CAPUTLG3344S — ")
    assert tools.data_stats()["failures"] == 0


def test_search_results_end_with_the_relevance_rule_an_empty_search_has_none(tmp_path, api, captured):
    # Rendered China-NEV KIQ (glue U1-v3): "new energy vehicle sales share" in CHN
    # returned world energy shares and US vehicle sales; the decision whether a
    # result measures the statistic is made here, on the result list.
    hits = [api.SearchHit("wb:WB_WDI_EG_USE_COMM_CL_ZS/WLD", "Alternative and nuclear energy (% of total energy "
                          "use)", "", "A", "", "wb", "Discovery metadata; fetch before citing"),
            api.SearchHit("fred:TOTALSA", "Total Vehicle Sales", "Millions of Units", "M", "", "fred", "")]
    source = Sources(api, captured, hits=hits)
    tools = make_tools(tmp_path, source)
    lines = tools.data_search("new energy vehicle sales share China", agent_id="K1").splitlines()
    assert [line.split(" — ", 1)[0] for line in lines[:2]] == ["wb:WB_WDI_EG_USE_COMM_CL_ZS/WLD", "fred:TOTALSA"]
    assert lines[2:] == [rg.DATA_SEARCH_RULE]
    assert rg.DATA_SEARCH_RULE == ("Use a result only when its title, units and geography measure the statistic you "
                                   "need; when none does, no official series covers it: say so and use web sources.")
    source.hits = []
    assert tools.data_search("lithium share of EV battery cost", agent_id="K1") == (
        "NO_DATA_MATCH: try another concept, an English term or another provider.")


def test_search_lines_lead_with_the_id_and_carry_geography_units_and_pitfalls(tmp_path, api, captured):
    # Data360 discovery shape (DataSources._search): indicator name without country, no units.
    discovered = api.SearchHit("wb:IMF_WEO_NGDP_RPCH/CHN", "Gross domestic product (GDP), Constant prices, "
                               "Percent change", "", "A", "", "wb", "Discovery metadata; fetch before citing")
    long_note = api.SearchHit("fred:UNRATE", "Unemployment Rate", "Percent", "M", "1948-01 to 2026-09", "fred",
                              "The unemployment rate represents the number of unemployed as a percentage of the "
                              "labor force. " * 6)
    tools = make_tools(tmp_path, Sources(api, captured, hits=[discovered, long_note]))
    first, second, rule = tools.data_search("GDP growth China", agent_id="K1").splitlines()
    assert rule == rg.DATA_SEARCH_RULE
    assert first.split(" — ", 1)[0] == "wb:IMF_WEO_NGDP_RPCH/CHN" and "China" in first
    assert first.endswith("A · Discovery metadata; fetch before citing")
    label = api.series_label({"series": "fred:UNRATE", "title": "Unemployment Rate"})
    assert "United States" in label
    assert second.startswith(f"fred:UNRATE — {label} · Percent · M · 1948-01 to 2026-09 · The unemployment rate")
    assert second.endswith("…") and len(second.rsplit(" · ", 1)[1]) <= 120


# ------------------------------------------------------------ F19 / V3-M4 windows
@pytest.mark.parametrize("start, end, expected", [
    ("2020", "2026", ("2020-01-01", "2026-12-31")),
    ("2026-Q2", "2026q2", ("2026-04-01", "2026-06-30")),
    ("2024-02", "2024-02", ("2024-02-01", "2024-02-29")),
    (" 2019-03-15 ", None, ("2019-03-15", None)),
])
def test_window_bounds_are_normalized_before_the_provider(tmp_path, api, captured, start, end, expected):
    source = Sources(api, captured)
    tools = make_tools(tmp_path, source)
    assert tools.data_get("fred:UNRATE", start=start, end=end, agent_id="K1").startswith("[S1]")
    assert source.gets() == [("get", "fred:UNRATE", *expected)]


@pytest.mark.parametrize("start, end", [("2026-13", None), ("26", None), ("2026", "2020"), ("last year", None)])
def test_a_malformed_window_is_rejected_without_a_provider_call(tmp_path, api, captured, start, end):
    source = Sources(api, captured)
    tools = make_tools(tmp_path, source)
    assert tools.data_get("fred:UNRATE", start=start, end=end, agent_id="K1").startswith(
        "DATA_UNAVAILABLE[invalid_input]: ")
    assert source.calls == [] and tools.data_stats()["calls"] == 0


def test_prefetch_windows_reach_the_provider_per_series(tmp_path, api, captured):
    # Stored windows are immutable for the run, so projection horizons and
    # long histories are requested at prefetch time.
    source = Sources(api, captured)
    tools = make_tools(tmp_path, source)
    result = tools.prefetch_data(["wb:IMF_WEO_NGDP_RPCH/CHN", "fred:UNRATE", "fred:GDP", "fred:PAYEMS"],
                                 deadline=rg.Deadline(10),
                                 windows={"wb:IMF_WEO_NGDP_RPCH/CHN": ("", "2031"), "fred:UNRATE": ("1990", None),
                                          "fred:GDP": ("2030", "2020"), "fred:PAYEMS": (2020, None)})
    assert result["wb:IMF_WEO_NGDP_RPCH/CHN"].startswith("[S") and result["fred:UNRATE"].startswith("[S")
    assert result["fred:GDP"].startswith("DATA_UNAVAILABLE[invalid_input]: ")
    assert result["fred:PAYEMS"].startswith("DATA_UNAVAILABLE[invalid_input]: ")
    assert sorted(call[1:] for call in source.gets()) == [("fred:UNRATE", "1990-01-01", None),
                                                          ("wb:IMF_WEO_NGDP_RPCH/CHN", None, "2031-12-31")]


def test_a_request_outside_the_stored_window_is_answered_with_a_note(tmp_path, api, captured):
    source = Sources(api, captured)
    tools = make_tools(tmp_path, source)
    first = tools.data_get("fred:UNRATE", agent_id="K1")
    longer = tools.data_get("fred:UNRATE", start="1990-01", agent_id="K2")
    header, note, *body = longer.splitlines()
    assert header == first.splitlines()[0] and body == first.splitlines()[1:]
    # The agent learns what still gets it the history (a base-rate KIQ asking
    # after another KIQ stored the series with its default window).
    assert note == ("NOTE: this run already stores fred:UNRATE for 2023-10-01 to 2026-09-01; the requested window "
                    "1990-01-01 to default was not refetched (one stored window per series per run). Longer "
                    "history needs another series that measures the statistic (a yoy or pct transform is a "
                    "separate series).")
    assert tools.data_get("fred:UNRATE", start="2024", end="2026-06", agent_id="K3") == first
    assert len(source.gets()) == 1


def test_a_forecast_horizon_end_is_no_window_gap_unless_the_stored_window_was_cut_short(tmp_path, api, captured):
    # The default window ran to its retrieval date (2026-10-11): it holds every
    # period published by then, so asking to the forecast year is no gap.
    source = Sources(api, captured)
    tools = make_tools(tmp_path, source)
    first = tools.data_get("fred:UNRATE", agent_id="K1")
    assert tools.data_get("fred:UNRATE", end="2027", agent_id="K2") == first
    assert tools.data_get("fred:UNRATE", start="2024", end="2030-06", agent_id="K3") == first
    assert tools.data_get("fred:UNRATE", start="1990", end="2027", agent_id="K4").splitlines()[1].startswith(
        "NOTE: this run already stores fred:UNRATE for 2023-10-01 to 2026-09-01; the requested window "
        "1990-01-01 to 2027-12-31 was not refetched")
    # A stored window cut short before retrieval does miss later periods.
    row = captured["fred:UNRATE"]
    short = {**row, "observations": [obs for obs in row["observations"] if obs["date"] <= "2025-12-31"],
             "provenance": {**row["provenance"], "requested_end": "2025-12-31"}}
    # An unreadable retrieval date keeps the conservative rule (noted).
    for n, retrieved_at in enumerate((row["retrieved_at"], "", "unknown")):
        source = Sources(api, captured, script={"fred:UNRATE": [api.Series.from_dict(
            {**short, "retrieved_at": retrieved_at})]})
        tools = make_tools(tmp_path / f"short{n}", source)
        stored = tools.data_get("fred:UNRATE", end="2025", agent_id="K1")
        assert stored.startswith("[S1]")
        later = tools.data_get("fred:UNRATE", end="2027", agent_id="K2").splitlines()
        assert later[1].startswith("NOTE: this run already stores fred:UNRATE for 2023-10-01 to 2025-12-01; the "
                                   "requested window default to 2027-12-31 was not refetched")
        assert later[2:] == stored.splitlines()[1:]
        assert tools.data_get("fred:UNRATE", end="2025-06", agent_id="K3") == stored
        assert len(source.gets()) == 1


def test_a_projection_path_stored_to_the_horizon_notes_a_later_end(tmp_path, api):
    # Real v3 row (2026-10-12): the WEO CPI path prefetched to the 2027 horizon,
    # after its retrieval date; the publisher's path runs further (to 2031), so a
    # later end is a window the stored generation does not hold.
    rows = json.loads((FIXTURE.parent.parent / "v3_engine" / "series-2026-10-12.json").read_text("utf-8"))["series"]
    weo = next(row for row in rows if row["series"] == "wb:IMF_WEO_PCPIPCH/USA")
    assert (weo["provenance"]["requested_end"], weo["observations"][-1]["date"], weo["retrieved_at"][:10]) == (
        "2027-12-31", "2027-01-01", "2026-10-12")
    source = Sources(api, {}, script={"wb:IMF_WEO_PCPIPCH/USA": [api.Series.from_dict(weo)]})
    tools = make_tools(tmp_path, source)
    stored = tools.prefetch_data(["wb:IMF_WEO_PCPIPCH/USA"], deadline=rg.Deadline(10),
                                 windows={"wb:IMF_WEO_PCPIPCH/USA": (None, "2027")})["wb:IMF_WEO_PCPIPCH/USA"]
    assert stored.startswith("[S1]")
    later = tools.data_get("wb:IMF_WEO_PCPIPCH/USA", end="2031", agent_id="K1").splitlines()
    assert later[1].startswith("NOTE: this run already stores wb:IMF_WEO_PCPIPCH/USA for ")
    assert "the requested window default to 2031-12-31 was not refetched" in later[1]
    assert tools.data_get("wb:IMF_WEO_PCPIPCH/USA", end="2027", agent_id="K1") == stored
    assert len(source.gets()) == 1


def test_a_projection_path_stored_to_the_retrieval_year_notes_a_later_end(tmp_path, api):
    # The same real row as the data layer returns it for end="2026": a v3 plan
    # whose horizon is the current year ("2026", "2026-12-31" in real plans), or
    # an agent asking for this year's value first.  No stored point lies after
    # the retrieval date, yet the publisher's path runs on (2027 here), so a
    # later end is a window the stored generation does not hold.
    rows = json.loads((FIXTURE.parent.parent / "v3_engine" / "series-2026-10-12.json").read_text("utf-8"))["series"]
    weo = next(row for row in rows if row["series"] == "wb:IMF_WEO_PCPIPCH/USA")
    current = {**weo, "observations": [obs for obs in weo["observations"] if obs["date"] <= "2026-12-31"],
               "provenance": {**weo["provenance"], "requested_end": "2026-12-31"}}
    assert (current["projection_from"], current["observations"][-1]["date"], current["retrieved_at"][:10]) == (
        "2026-01-01", "2026-01-01", "2026-10-12")
    source = Sources(api, {}, script={"wb:IMF_WEO_PCPIPCH/USA": [api.Series.from_dict(current)]})
    tools = make_tools(tmp_path, source)
    stored = tools.prefetch_data(["wb:IMF_WEO_PCPIPCH/USA"], deadline=rg.Deadline(10),
                                 windows={"wb:IMF_WEO_PCPIPCH/USA": (None, "2026")})["wb:IMF_WEO_PCPIPCH/USA"]
    assert stored.startswith("[S1]")
    later = tools.data_get("wb:IMF_WEO_PCPIPCH/USA", end="2028", agent_id="K1").splitlines()
    assert later[1].startswith("NOTE: this run already stores wb:IMF_WEO_PCPIPCH/USA for ")
    assert "the requested window default to 2028-12-31 was not refetched" in later[1]
    assert later[2:] == stored.splitlines()[1:]
    assert tools.data_get("wb:IMF_WEO_PCPIPCH/USA", end="2026", agent_id="K2") == stored
    assert len(source.gets()) == 1


# ------------------------------------------------------- F9 / M4 persistence
def test_persistence_failure_is_reported_never_orphans_the_ledger_and_is_retried(tmp_path, api, captured,
                                                                                  monkeypatch):
    source = Sources(api, captured)
    tools = make_tools(tmp_path, source)
    failed = {"schema_version": 1, "series": [], "error": "Official data persistence failed",
              "code": "persistence_failed"}
    with monkeypatch.context() as patch:
        patch.setattr(api, "write_dataset_files", lambda *args, **kwargs: dict(failed))
        output = tools.data_get("fred:UNRATE", agent_id="K1")
    assert output.startswith("DATA_UNAVAILABLE[persistence_failed]: ") and "StopIteration" not in output
    assert len(tools.ledger) == 0 and not tools.data_rows()
    tools.ledger.flush()
    resumed = make_tools(tmp_path, source)
    resumed.restore_data()
    assert resumed.invalid_data_sids() == set()
    # The failure is local and transient: the next request stores the series
    # under a new source ID (an ID is never handed out twice).
    assert tools.data_get("fred:UNRATE", agent_id="K2").startswith("[S2]")
    assert len(source.gets()) == 2


def test_restore_ignores_a_dataset_row_a_crash_left_unfetched(tmp_path, api, captured):
    path = tmp_path / "v3" / "sources_ledger.json"
    crashed = rg.SourceLedger(path)
    series = api.Series.from_dict(captured["fred:UNRATE"])
    crashed.register_dataset(series.source_url, series.title, series.to_dict(), "data-seeder")
    crashed.flush()
    tools = make_tools(tmp_path, Sources(api, captured))
    tools.restore_data()
    assert tools.invalid_data_sids() == set()
    assert tools.data_get("fred:UNRATE", agent_id="K1").startswith("[S1]")


def test_a_rejected_stored_generation_is_never_refetched(tmp_path, api, captured):
    source = Sources(api, captured)
    tools = make_tools(tmp_path, source)
    tools.data_get("fred:UNRATE", agent_id="K1")
    row = tools.ledger.get(1)
    (tmp_path / "v3" / row["page_path"]).write_text("tampered: 999.9%", "utf-8")
    resumed = make_tools(tmp_path, source)
    resumed.restore_data()
    assert resumed.invalid_data_sids() == {1}
    answers = [resumed.data_get("fred:UNRATE", agent_id="K2"),
               resumed.prefetch_data(["fred:UNRATE"], deadline=rg.Deadline(10))["fred:UNRATE"],
               resumed.fetch(row["dataset"]["source_url"], agent_id="K2")]
    assert all(answer.startswith("DATA_UNAVAILABLE[persistence_failed]: ") for answer in answers)
    assert len(source.gets()) == 1


def test_run_directory_below_a_symlinked_parent_stores_datasets(tmp_path, api, captured):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real, target_is_directory=True)
    root = tmp_path / "link" / "run"
    tools = make_tools(root, Sources(api, captured))
    assert tools.data_get("fred:UNRATE", agent_id="K1").startswith("[S1]")
    assert [row["series"] for row in api.load_datasets(root / "v3")] == ["fred:UNRATE"]
    resumed = make_tools(root, Sources(api, captured))
    resumed.restore_data()
    assert [sid for _, sid in resumed.data_rows()] == [1]


# ------------------------------------------------- F11 shared pages, F10 titles
def test_a_shared_publisher_page_offers_a_choice_instead_of_another_countrys_series(tmp_path, api, captured):
    tools = make_tools(tmp_path, Sources(api, captured))
    for country in ("USA", "DEU", "CHN"):
        assert tools.data_get(f"wb:IMF_WEO_NGDP_RPCH/{country}", agent_id="K1").startswith("[S")
    assert tools.data_get("fred:UNRATE", agent_id="K2").startswith("[S4]")
    choice = tools.fetch(WEO_PAGE, focus="China GDP growth", agent_id="K3")
    first, *listed = choice.splitlines()
    assert first.startswith("DATASET_CHOICE: ") and "[S" not in first
    assert [line.split(" — ", 1)[0] for line in listed] == [
        "- [S1] wb:IMF_WEO_NGDP_RPCH/USA", "- [S2] wb:IMF_WEO_NGDP_RPCH/DEU", "- [S3] wb:IMF_WEO_NGDP_RPCH/CHN"]
    assert ["United States" in listed[0], "Germany" in listed[1], "China" in listed[2]] == [True] * 3
    # A marker resolves to the exact identity URL, and a single-series page
    # still reads its stored dataset; neither reaches the web.
    assert tools.fetch(tools.ledger.get(3)["url"], agent_id="K3").startswith("[S3]")
    assert tools.fetch("https://fred.stlouisfed.org/series/UNRATE", agent_id="K3").startswith("[S4]")


def test_dataset_references_name_their_geography(tmp_path, api, captured):
    tools = make_tools(tmp_path, Sources(api, captured))
    outputs = [tools.data_get(f"wb:IMF_WEO_NGDP_RPCH/{country}", agent_id="K1") for country in ("USA", "DEU", "CHN")]
    titles = [tools.ledger.get(sid)["title"] for sid in (1, 2, 3)]
    # The Data360 indicator name is the same for every country.
    assert len({captured[f"wb:IMF_WEO_NGDP_RPCH/{c}"]["title"] for c in ("USA", "DEU", "CHN")}) == 1
    assert len(set(titles)) == 3
    for output, title, name in zip(outputs, titles, ("United States", "Germany", "China")):
        assert name in title and output.splitlines()[0].startswith(f"[S{titles.index(title) + 1}] {title} — ")
