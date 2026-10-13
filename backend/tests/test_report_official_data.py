"""Stored official observations -> report context, anchored forecasts and exhibits.

Run with main_offline_pytest.py. All values and sources below are synthetic;
no provider, model, saved report or pipeline is consulted.
"""
from copy import deepcopy
import html
import json
import re

import pytest

from app.services import forecast_extractor as fe
from app.services import report_visualizer as rv
from app.services.report_agent import ReportAgent
from tests.conftest import FakeLLMClient


@pytest.fixture(autouse=True)
def forbid_report_fetch(monkeypatch):
    from app.services import official_data as adapter
    def forbidden(*args, **kwargs):
        pytest.fail("Report generation attempted to acquire an upstream data client")
    monkeypatch.setattr(adapter, "get_data_sources", forbidden)
    api = adapter.data_api()
    if api is not None and hasattr(api, "get_data_sources"):
        monkeypatch.setattr(api, "get_data_sources", forbidden)


@pytest.fixture
def official_data():
    return {"schema_version": 1, "series": [{
        "series": "fred:UNRATE", "provider": "fred", "provider_name": "FRED",
        "title": "Unemployment Rate", "title_zh": "失业率", "units": "Percent",
        "frequency": "M", "seasonal_adjustment": "SA", "geography": "USA",
        "transform": "", "vintage": "", "projection_from": "2025-05-01",
        "source_url": "https://fred.stlouisfed.org/series/UNRATE",
        "source_id": "S99", "retrieved_at": "2025-06-01T00:00:00Z",
        "sha256": "a" * 64, "csv_sha256": "b" * 64,
        "observations": [
            {"date": "2024-04-01", "value": 4.0, "flag": ""},
            {"date": "2025-02-01", "value": 4.1, "flag": ""},
            {"date": "2025-03-01", "value": None, "flag": ""},
            {"date": "2025-04-01", "value": 4.25, "flag": ""},
            {"date": "2025-05-01", "value": 4.5, "flag": "projection"},
        ],
    }]}


def _binary(**anchor_changes):
    anchor = {"series": "fred:UNRATE", "comparator": ">=", "threshold": 5.0,
              "observation": "2026-04", "transform": "", "units": "Percent",
              "latest_value": 999, "source_url": "https://invented.example"}
    anchor.update(anchor_changes)
    return {"statement": "US unemployment rate >= 5% in April 2026",
            "probability": 0.65, "resolution_criteria": "fred:UNRATE >= 5% for 2026-04",
            "data_anchor": anchor}


def _agent(monkeypatch, official_data=None):
    monkeypatch.setattr(ReportAgent, "_define_tools", lambda self: {})
    monkeypatch.setattr(ReportAgent, "_locate_timeline", lambda self: None)
    monkeypatch.setattr(ReportAgent, "_locate_handoff_dir", lambda self: None)
    return ReportAgent(
        "fixture_graph", "fixture_simulation", "Forecast unemployment in 2026",
        llm_client=FakeLLMClient(), zep_tools=object(), official_data=official_data,
        sources=[{"title": "Unemployment Rate", "url":
                  "https://fred.stlouisfed.org/series/UNRATE"}],
    )


def test_constructor_context_and_viz_use_same_stored_carrier(monkeypatch, tmp_path, official_data):
    before = deepcopy(official_data)
    agent = _agent(monkeypatch, official_data)
    assert agent.official_data is official_data
    assert official_data == before
    assert 0 < len(agent._data_pack) <= 5000
    assert "Official data snapshot" in agent._data_pack
    # Periods read at the series frequency (monthly 2025-04), as in the indicator table.
    assert "| 4.25% / 2025-04 |" in agent._data_pack and "2025-04-01" not in agent._data_pack
    assert "[S1]" in agent._data_pack and "[S99]" not in agent._data_pack
    assert "projection" in agent._data_pack.lower()
    assert "0.25 percentage points" in agent._data_pack
    assert "4% (2024-04) to 4.25% (2025-04)" in agent._data_pack
    assert agent._data_pack in agent._prepend_research_background("Write the report")
    assert agent._collect_viz_artifacts("fixture_report", str(tmp_path))["official_data"] is official_data


def test_absent_official_data_retains_existing_context(monkeypatch):
    agent = _agent(monkeypatch)
    assert agent._data_pack == ""
    assert "Official data snapshot" not in agent._prepend_research_background("Prompt")
    assert fe._normalize_binaries([_binary()])[0].get("data_anchor") is None


def test_only_exact_stored_claim_is_corroborated(monkeypatch, official_data):
    agent = _agent(monkeypatch, official_data)
    claim = "fred:UNRATE: 4.25% on 2025-04-01 (historical observation, units: Percent)."
    assert agent._official_data_corroborated_claim(claim)
    assert not agent._official_data_corroborated_claim(claim.replace("4.25", "9.25"))
    assert not agent._official_data_corroborated_claim(claim + " GDP rose 99%.")
    assert not agent._official_data_corroborated_claim(claim.replace("2025-04", "2025-03"))
    assert not agent._official_data_corroborated_claim(claim.replace("Percent", "USD"))
    projected = "fred:UNRATE: 4.5% on 2025-05-01 (publisher projection, units: Percent)."
    assert agent._official_data_corroborated_claim(projected)
    assert not agent._official_data_corroborated_claim(projected.replace("publisher projection", "historical observation"))
    tag, status = agent._quantitative_semantic_decision(claim)
    assert tag == "S1" and status == "supported"
    repaired, _ = agent._repair_final_quantitative_grounding("## Analysis\n\n" + claim)
    assert claim in repaired and "[S1]" in repaired
    repaired, audit = agent._repair_semantic_citations(repaired)
    assert "[S1]" in repaired and audit["stripped"] == 0
    final = agent._audit_semantic_citations(repaired)
    assert final["unsupported"] == 0


def test_anchor_enriched_from_real_shared_helper(official_data):
    result = fe._normalize_binaries([_binary()], official_data=official_data)[0]
    anchor = result["data_anchor"]
    assert anchor["latest_value"] == 4.25
    assert anchor["latest_date"] == "2025-04-01"
    assert anchor["source_url"] == official_data["series"][0]["source_url"]
    assert result["probability"] == 0.65


@pytest.mark.parametrize("changes", [
    {"series": "fred:UNKNOWN"}, {"threshold": float("nan")}, {"threshold": True},
    {"comparator": "="}, {"observation": "2026"}, {"units": "USD"}, {"transform": "yoy"},
])
def test_invalid_anchor_is_dropped_without_dropping_forecast(official_data, changes):
    result = fe._normalize_binaries([_binary(**changes)], official_data=official_data)
    assert len(result) == 1 and "data_anchor" not in result[0]


def test_extraction_prompt_and_resolution_use_canonical_data(monkeypatch, official_data):
    monkeypatch.setattr(fe, "_cfg", lambda key, default: {
        "FORECAST_BINARY_CONTRARIAN": False, "PREDICTION_MARKETS_ENABLED": False,
        "FORECAST_ENSEMBLE_MODELS": "",
    }.get(key, default))
    llm = FakeLLMClient(json_responses=[{"binary_forecasts": [_binary()]}])
    result = fe.extract_binary_forecasts("Fixture dossier", llm, min_count=1,
                                        data_pack="Exact stored snapshot", official_data=official_data)
    assert "data_anchor" in llm.calls[0]["messages"][0]["content"]
    assert "Exact stored snapshot" in llm.calls[0]["messages"][0]["content"]
    result["scenarios"] = [{"name": "Baseline", "probability": 1,
                            "resolution_criteria": "Resolve in April 2026"}]
    block = fe.render_resolution_block(result, language="English", official_data=official_data)
    assert "Official series to watch" in block
    assert "4.25" in block and "999" not in block
    assert "2026-04" in block and ">=" in block
    assert official_data["series"][0]["source_url"] in block


@pytest.fixture
def viz(monkeypatch):
    monkeypatch.setattr(rv.ReportVisualizer, "_png_export_ok", lambda self: False)
    monkeypatch.setattr(rv.ReportVisualizer, "_load_price_history", staticmethod(lambda *args: {}))
    return rv.ReportVisualizer()


def test_build_all_renders_stored_values_gaps_projection_and_threshold(viz, monkeypatch, tmp_path, official_data):
    if not rv.PLOTLY_AVAILABLE:
        pytest.skip("Plotly unavailable")
    captured = {}
    original = rv.ReportVisualizer._save_pair
    def capture(self, fig, charts_dir, stem, item_id=None):
        captured[stem] = fig
        return original(self, fig, charts_dir, stem, item_id)
    monkeypatch.setattr(rv.ReportVisualizer, "_save_pair", capture)
    forecast = {"horizon": "2026-12-31", "binary_forecasts": [_binary()]}
    items = viz.build_all("fixture", str(tmp_path), {"official_data": official_data,
                                                   "forecast": forecast})
    official = [i for i in items if i["source"] == "official_data"]
    assert {i["id"] for i in official} >= {"official_indicators"}
    detail = next(i for i in official if i["id"].startswith("official_series_"))
    fig = captured[detail["id"]]
    observed = next(t for t in fig.data if t.name == "Historical observations")
    projected = next(t for t in fig.data if t.name == "Publisher projections")
    assert list(observed.y) == [4.0, 4.1, None, 4.25, None]
    assert list(projected.y) == [None, None, None, None, 4.5]
    assert observed.connectgaps is False and projected.connectgaps is False
    assert fig.layout.xaxis.type == "date"
    assert fig.layout.yaxis.title.text == "Percent"
    assert any(s.type == "line" and s.y0 == 5.0 and s.y1 == 5.0 for s in fig.layout.shapes)
    # The full threshold label (comparator, period, P(yes)) lives in the legend; the plot
    # area only carries a short value tag so it never covers observations.
    assert any("Model threshold" in (t.name or "") and "65%" in (t.name or "") for t in fig.data)
    assert any(html.unescape(a.text).startswith(">=") and "5" in a.text for a in fig.layout.annotations)
    assert any("Forecast horizon" in a.text for a in fig.layout.annotations)
    projection_rect = next(s for s in fig.layout.shapes if s.type == "rect" and s.fillcolor == "#f59e0b")
    assert projection_rect.x0 == "2025-05-01" and projection_rect.x1 == "2025-06-01"
    for item in official:
        assert (tmp_path / item["path"]).is_file()
        assert (tmp_path / item["png_path"]).is_file()
        assert not re.search(r"\d", item["title"] + item["caption"] + item["path"])
        assert item["provenance"][0]["sha256"] == "a" * 64
        assert "fred.stlouisfed.org" in item["source_caption"]
    manifest = json.loads((tmp_path / "viz_manifest.json").read_text())
    assert manifest["items"] == items
    assert "official_data" in manifest["provenance"]["inputs_sha256"]


def test_matplotlib_fallback_manifest_and_bilingual_embedding(viz, monkeypatch, tmp_path, official_data):
    if not rv.MATPLOTLIB_AVAILABLE:
        pytest.skip("Matplotlib unavailable")
    monkeypatch.setattr(rv, "PLOTLY_AVAILABLE", False)
    agent = _agent(monkeypatch, official_data)
    items = viz.build_all("fixture", str(tmp_path), {"official_data": official_data})
    official = [i for i in items if i["source"] == "official_data"]
    assert official and all(i["type"] == "png" for i in official)
    markdown = agent._place_visualizations("## Official data\n\nAnalysis", str(tmp_path), official)
    assert "fred.stlouisfed.org" in markdown
    assert "[S1]" in markdown and "[S99]" not in markdown
    localized = rv.localize_chart_alt_text(markdown, "zh")
    assert "官方指标" in localized
    assert agent._translation_number_multiset(markdown) == agent._translation_number_multiset(localized)
    assert agent._place_visualizations(markdown, str(tmp_path), official) == markdown


def test_unavailable_or_malformed_data_does_not_publish_empty_chart(viz, tmp_path):
    for data in (None, {}, {"schema_version": 1, "series": [{"series": "fred:X", "observations": []}]}):
        items = viz.build_all("fixture", str(tmp_path), {"official_data": data})
        assert not any(i["source"] == "official_data" for i in items)


def test_unknown_projection_metadata_never_becomes_history(official_data):
    row = official_data["series"][0]
    row.update(series="imf:WEO/USA.NGDP_RPCH.A", frequency="A", projection_from="")
    row["observations"] = [{"date": "2025-01-01", "value": 3.5, "flag": ""}]
    panels = rv.ReportVisualizer._official_chart_panels(official_data, {})
    assert "historical observation" not in panels[0]["values"]
    assert panels[0]["values"]["unclassified publisher value"] == [3.5]


def test_dashboard_preserves_incompatible_units_in_separate_panels(viz, monkeypatch, tmp_path, official_data):
    if not rv.PLOTLY_AVAILABLE:
        pytest.skip("Plotly unavailable")
    second = deepcopy(official_data["series"][0])
    second.update(series="usgov:treasury/debt_to_penny", title="Debt", units="USD",
                  frequency="D", seasonal_adjustment="NSA", projection_from="")
    second["observations"] = [{"date": "2025-04-01", "value": 2000000, "flag": ""}]
    official_data["series"].append(second)
    panels = viz._official_chart_panels(official_data, {"binary_forecasts": [_binary(units="USD")]})
    assert all(not p["thresholds"] for p in panels)
    captured = {}
    def capture(self, fig, *_args):
        captured["figure"] = fig
        return "charts/official_indicators.html"
    monkeypatch.setattr(rv.ReportVisualizer, "_save_pair", capture)
    viz._build_official_plotly(panels, str(tmp_path), "official_indicators", "Official Indicators", {}, detail=False)
    fig = captured["figure"]
    assert fig.layout.yaxis.title.text == "Percent"
    assert fig.layout.yaxis2.title.text == "USD"
    assert fig.layout.xaxis.type == fig.layout.xaxis2.type == "date"
    assert fig.layout.yaxis2.matches is None


def test_chart_failure_is_explicit_and_does_not_leave_broken_links(viz, monkeypatch, tmp_path, official_data):
    monkeypatch.setattr(viz, "_interactive_ok", lambda: False)
    monkeypatch.setattr(viz, "_chart_ok", lambda: False)
    items = viz.build_all("fixture", str(tmp_path), {"official_data": official_data})
    assert not any(i["source"] == "official_data" for i in items)
    manifest = json.loads((tmp_path / "viz_manifest.json").read_text())
    skipped = [s for s in manifest["skipped"] if s["builder"].startswith("official_")]
    assert skipped and all(s["reason"] == "render_unavailable_or_failed" for s in skipped)


def test_scenario_bands_require_exact_metric_unit_and_annual_period(official_data):
    row = official_data["series"][0]
    forecast = {"horizon": "2026", "scenarios": [{"name": "Baseline", "resolution_criteria":
                                                 "Unemployment Rate between 4% and 6% in 2026"}]}
    bands = rv.ReportVisualizer._official_scenario_bands
    assert bands(row, forecast) == []  # Annual interval cannot describe a monthly series.
    annual = {**row, "frequency": "A"}
    assert bands(annual, forecast)[0]["low"] == 4.0
    assert bands({**annual, "units": "USD"}, forecast) == []
    assert bands({**annual, "title": "GDP Growth"}, forecast) == []
    assert bands({**annual, "transform": "yoy"}, forecast) == []


def test_nested_dataset_identity_keeps_transforms_distinct(monkeypatch, official_data):
    row = official_data["series"][0]
    sources = {"S2": {"title": "Raw rate", "url": row["source_url"],
                      "dataset": {"series": row["series"]}},
               "S3": {"title": "Yearly change", "url": row["source_url"],
                      "dataset": {"series": row["series"] + "#yoy"}}}
    assert fe.official_source_tag(row, sources) == "S2"
    assert fe.official_source_tag({**row, "series": row["series"] + "#yoy"}, sources) == "S3"
    agent = _agent(monkeypatch, official_data)
    agent._citation_index = sources
    claim = "fred:UNRATE: 4.25% on 2025-04-01 (historical observation, units: Percent)."
    assert agent._official_data_claim_tag(claim) == "S2"
    assert agent._report_citation_support(claim, sources["S2"]) is True
    assert agent._report_citation_support(claim, sources["S3"]) is not True


def test_official_contradictions_do_not_borrow_lexical_support(monkeypatch, official_data):
    agent = _agent(monkeypatch, official_data)
    actual = "fred:UNRATE: 4.25% on 2025-04-01 (historical observation, units: Percent)."
    projection = "fred:UNRATE: 4.5% on 2025-05-01 (publisher projection, units: Percent)."
    source = agent._citation_index["S1"]
    source["supports"] = [actual, projection]
    source["dataset"] = {"series": "fred:UNRATE"}
    wrong = projection.replace("publisher projection", "historical observation")
    assert agent._quantitative_semantic_decision(wrong) == ("", "unsupported")
    assert agent._audit_semantic_citations(wrong + " [S1]")["unsupported"] == 1
    repaired, audit = agent._repair_semantic_citations(wrong + " [S1]")
    assert "[S1]" not in repaired and audit["stripped"] == 1
    source["dataset"]["series"] = "fred:UNRATE#yoy"
    assert agent._report_citation_support(actual, source) is False
    assert agent._audit_semantic_citations(actual + " [S1]")["unsupported"] == 1


@pytest.mark.parametrize("changes", [{"threshold": 6.0}, {"comparator": "<"}, {"observation": "2026-05"}])
def test_dataset_valid_but_contradictory_anchor_is_dropped(official_data, changes):
    from app.services.official_data import validate_data_anchor
    binary = _binary(**changes)
    assert validate_data_anchor(binary["data_anchor"], official_data) is not None
    result = fe._normalize_binaries([binary], official_data=official_data)[0]
    assert "data_anchor" not in result
    assert result["resolution_criteria"] == binary["resolution_criteria"]


@pytest.mark.parametrize("statement", [
    "US unemployment rate >= 6% in April 2026",
    "US inflation rate >= 5% in April 2026",
    "US unemployment rate reaches six percent in April 2026",
    "US unemployment rate >= 5% in May 2026",
    "US unemployment rate is not >= 5% in April 2026",
    "US unemployment rate >= 5% in April 2026 unless inflation falls",
    "US unemployment rate >= 5% in April 2026 or inflation rises",
    "US unemployment rate >= 5% by April 2026",
])
def test_anchor_does_not_override_a_different_or_ambiguous_statement(official_data, statement):
    binary = _binary()
    binary["statement"] = statement
    result = fe._normalize_binaries([binary], official_data=official_data)[0]
    assert "data_anchor" not in result and result["statement"] == statement


def test_annual_anchor_cannot_settle_monthly_prose(official_data):
    row = official_data["series"][0]
    row.update(frequency="A", projection_from="")
    row["observations"] = [{"date": "2025-01-01", "value": 4, "flag": ""}]
    binary = _binary(observation="2026")
    from app.services.official_data import validate_data_anchor
    assert validate_data_anchor(binary["data_anchor"], official_data) is not None
    assert "data_anchor" not in fe._normalize_binaries([binary], official_data=official_data)[0]


@pytest.mark.parametrize("prefix,identifier", [("- ", "fred:UNRATE"), ("* ", "**fred:UNRATE**"),
                                              ("", "`fred:UNRATE`"), ("", "_fred:UNRATE_"),
                                              ("", "**`fred:UNRATE`**"), ("", "***fred:UNRATE***")])
def test_markdown_cannot_launder_projection_as_history(monkeypatch, official_data, prefix, identifier):
    agent = _agent(monkeypatch, official_data)
    projected = "fred:UNRATE: 4.5% on 2025-05-01 (publisher projection, units: Percent)."
    agent._citation_index["S1"]["supports"] = [projected]
    wrong = prefix + projected.replace("fred:UNRATE", identifier).replace("publisher projection", "historical observation")
    assert agent._quantitative_semantic_decision(wrong) == ("", "unsupported")
    assert agent._audit_semantic_citations(wrong + " [S1]")["unsupported"] == 1
    repaired, info = agent._repair_semantic_citations(wrong + " [S1]")
    assert "[S1]" not in repaired and info["stripped"] == 1


def test_decorated_dataset_identity_wins_over_generic_origin(official_data):
    row = official_data["series"][0]
    sources = {"S1": {"url": row["source_url"]}, "S2": {
        "url": row["source_url"] + "?drf_series=fred%3AUNRATE",
        "dataset": {"series": row["series"], "source_url": row["source_url"]},
    }}
    assert fe.official_source_tag(row, sources) == "S2"
    sources["S2"]["url"] += "&other=unrelated"
    assert fe.official_source_tag(row, sources) == "S1"
    sources["S2"]["url"] = row["source_url"] + "?drf_series=fred%3ADIFFERENT"
    assert fe.official_source_tag(row, sources) == "S1"


@pytest.mark.parametrize("binaries", [None, {}, "malformed", 1])
def test_malformed_optional_binaries_preserve_resolution_section(official_data, binaries):
    forecast = {"scenarios": [{"name": "Baseline", "probability": 1,
                               "resolution_criteria": "Resolve in 2026"}], "binary_forecasts": binaries}
    block = fe.render_resolution_block(forecast, language="English", official_data=official_data)
    assert "Per-Scenario Resolution Criteria" in block and "Official series to watch" not in block


def test_malformed_optional_metadata_does_not_lose_history_exhibits(viz, tmp_path, official_data):
    official_data["series"][0]["frequency"] = "A"
    official_data["series"][0]["kiqs"] = 4
    items = viz.build_all("fixture", str(tmp_path), {"official_data": official_data,
                                                   "forecast": {"horizon": "2026", "scenarios": {"name": "Baseline"}},
                                                   "sources": 1})
    # RPT-8 contract: unanchored, unbanded series appear on the dashboard only.
    assert any(i["id"] == "official_indicators" for i in items)
    official = [i for i in items if i["source"] == "official_data"]
    assert all("[S99]" not in i["source_caption"] for i in official)
    manifest = json.loads((tmp_path / "viz_manifest.json").read_text())
    assert {"builder": "official_source_captions", "reason": "malformed_source_metadata"} in manifest["skipped"]


@pytest.mark.parametrize("frequency", [[], {}, None, "unknown"])
def test_malformed_frequency_degrades_to_no_series(official_data, frequency):
    official_data["series"][0]["frequency"] = frequency
    assert fe.official_series_rows(official_data) == []


@pytest.mark.parametrize("provider,flag,cutoff,expected", [
    ("bls", "P", "", "publisher preliminary"),
    ("bls", "preliminary", "2025-01-01", "publisher preliminary"),
    ("imf", "estimate", "2025-01-01", "publisher estimate"),
    ("bis", "P", "", "unclassified publisher value"),
    ("imf", "unknown", "2025-01-01", "unclassified publisher value"),
    ("imf", "observed", "2025-01-01", "unclassified publisher value"),
    ("wb", "", "", "unclassified publisher value"),
    ("usgov", "", "", "unclassified publisher value"),
    ("imf", "projection", "", "publisher projection"),
])
def test_official_status_precedence_preserves_provider_fidelity(provider, flag, cutoff, expected):
    series = "usgov:spending/total" if provider == "usgov" else f"{provider}:TEST"
    row = {"series": series, "provider": provider, "projection_from": cutoff}
    assert fe.official_observation_kind(row, {"date": "2025-04-01", "value": 1, "flag": flag}) == expected


def test_report_legacy_weo_cutoff_cannot_restore_lost_status():
    row = {"series": "imf:WEO_2026_APR_VINTAGE/USA.NGDP_RPCH.A", "provider": "imf", "projection_from": "2024-01-01"}
    for date in ("2023-01-01", "2025-01-01"):
        assert fe.official_observation_kind(row, {"date": date, "value": 1, "flag": ""}) == "unclassified publisher value"


@pytest.mark.parametrize("partial", [False, True])
def test_report_fiscal_display_preserves_native_dates_and_numeric_tokens(viz, monkeypatch, tmp_path, partial):
    from tests.test_data_visuals_status import _fiscal
    row = _fiscal()
    period = row["provenance"]["periods"]["2024-10-01"]
    period.update(complete=not partial, covered_end="2025-03-31" if partial else "2025-09-30")
    carrier = {"schema_version": 1, "series": [row]}
    panels = viz._official_chart_panels(carrier, {})
    captured = {}
    def capture(self, fig, *_args):
        captured["figure"] = fig
        return "charts/fiscal.html"
    monkeypatch.setattr(rv.ReportVisualizer, "_save_pair", capture)
    viz._build_official_plotly(panels, str(tmp_path), "fiscal", "Official Indicators", {}, detail=False)
    fig = captured["figure"]
    assert fig.layout.xaxis.type == "date"
    assert list(fig.layout.xaxis.tickvals) == ["2023-10-01", "2024-10-01"]
    labels = list(fig.layout.xaxis.ticktext)
    assert "FY2024" == labels[0] and "FY2025" in labels[1]
    assert ("partial" in labels[1].lower()) == partial
    assert "FY2025" in str(fig.to_plotly_json())
    mpl_capture = {}
    def save(self, figure, *_args):
        mpl_capture["labels"] = [t.get_text() for t in figure.axes[0].get_xticklabels()]
        return "charts/fiscal.png"
    monkeypatch.setattr(rv.ReportVisualizer, "_save", save)
    viz._build_official_matplotlib(panels, str(tmp_path), "fiscal", "Official Indicators", {}, detail=False)
    assert mpl_capture["labels"] == labels
    items = []
    viz._run_official_data(str(tmp_path / "charts"), {"official_data": carrier}, items, [])
    source_caption = items[0]["source_caption"]
    assert "FY2025" in source_caption
    assert items[0]["provenance"][0]["periods"] == row["provenance"]["periods"]
    english = "![Official Indicators](charts/fiscal.png)\n\n" + source_caption
    chinese = rv.localize_chart_alt_text(english, "zh")
    assert ReportAgent._translation_number_multiset(english) == ReportAgent._translation_number_multiset(chinese)


def test_report_data_charts_flag_disables_only_official_exhibits(viz, monkeypatch, tmp_path, official_data):
    from app.config import Config
    monkeypatch.setattr(Config, "REPORT_DATA_CHARTS", False)
    forecast = {"scenarios": [{"name": "Baseline", "probability": 0.6},
                              {"name": "Alternative", "probability": 0.4}]}
    items = viz.build_all("fixture", str(tmp_path), {"official_data": official_data, "forecast": forecast})
    assert not any(i["source"] == "official_data" for i in items)
    assert any(i["id"] == "scenario_probabilities" for i in items)
    manifest = json.loads((tmp_path / "viz_manifest.json").read_text())
    assert {"builder": "official_indicators", "reason": "report_data_charts_disabled"} in manifest["skipped"]


def test_annual_scenario_band_only_spans_named_year(viz, monkeypatch, tmp_path, official_data):
    if not rv.PLOTLY_AVAILABLE:
        pytest.skip("Plotly unavailable")
    row = official_data["series"][0]
    row.update(frequency="A", projection_from="")
    row["observations"] = [{"date": "2025-01-01", "value": 4.0, "flag": ""}]
    forecast = {"horizon": "2026", "scenarios": [{"name": "Baseline", "resolution_criteria":
                                                 "Unemployment Rate between 4% and 6% in 2026"}]}
    captured = {}
    def capture(self, fig, *_args):
        captured["figure"] = fig
        return "charts/fixture.html"
    monkeypatch.setattr(rv.ReportVisualizer, "_save_pair", capture)
    panels = viz._official_chart_panels(official_data, forecast)
    viz._build_official_plotly(panels, str(tmp_path), "fixture", "Official Indicators", forecast, detail=True)
    rect = next(s for s in captured["figure"].layout.shapes if s.type == "rect" and s.fillcolor == "#22c55e")
    assert rect.x0 == "2026-01-01" and rect.x1 == "2027-01-01"


def test_executive_brief_values_carry_their_units():
    """A level read without its units misleads ('58522249' is $58.5 billion in Thousands of U.S.
    Dollars); percent series keep the bare percentage."""
    from pathlib import Path
    from app.services import exec_brief
    from app.services.report_agent import official_indicator_rows
    real = Path(__file__).parent / "fixtures" / "data_sources" / "real" / "agent_usage" / "carriers-2026-10-13.json"
    questions = json.loads(real.read_text(encoding="utf-8"))["questions"]
    semis = {"schema_version": 1, "series": questions["q5_semis"]["series"]}
    block = exec_brief._build_indicators_block(official_indicator_rows(semis, lang="en"), exec_brief._LABELS["en"])
    assert "| 58522249 Thousands of U.S. Dollars | 2024 |" in block
    assert "| 190.0987 Index 2017=100 | 2026-08 |" in block
    rates = {"schema_version": 1, "series": questions["q1_cpi_fed"]["series"]}
    assert "| 3.75% | 2026-09 |" in exec_brief._build_indicators_block(
        official_indicator_rows(rates, lang="en"), exec_brief._LABELS["en"])
    zh = exec_brief._build_indicators_block(official_indicator_rows(semis, lang="zh"), exec_brief._LABELS["zh"])
    assert "| 58522249 Thousands of U.S. Dollars | 2024 |" in zh
    datacenter = {"schema_version": 1, "series": questions["q2_datacenter"]["series"]}
    binary = fe._normalize_binaries([{
        "statement": "US commercial-sector retail electricity sales are at least 160,000 million kilowatt-hours "
                     "in July 2030.",
        "probability": 0.3,
        "resolution_criteria": "Resolves YES if usgov:eia/electricity_sales/US.COM >= 160000 Million kilowatt-hours "
                               "in 2030-07 (source: EIA).",
        "data_anchor": {"series": "usgov:eia/electricity_sales/US.COM", "comparator": ">=", "threshold": 160000,
                        "observation": "2030-07", "units": "Million kilowatt-hours"}}], official_data=datacenter)[0]
    line = exec_brief._anchor_watch_line(binary, exec_brief._LABELS["en"])[1]
    assert ("latest 150578.728 Million kilowatt-hours (2026-07); "
            "threshold >= 160000 Million kilowatt-hours (2030-07); historical base rate") in line


@pytest.mark.parametrize("row, expected", [
    # A usgov row without a stored provider_name names its publishing agency, as fresh rows do.
    ({"provider": "usgov", "series": "usgov:eia/electricity_sales/US.COM"},
     "U.S. Energy Information Administration (EIA)"),
    ({"provider": "usgov", "series": "usgov:treasury/debt_to_penny"},
     "U.S. Treasury Fiscal Data (Bureau of the Fiscal Service)"),
    ({"provider": "fred", "series": "fred:UNRATE"}, "FRED (Federal Reserve Bank of St. Louis)"),
    # A stored name is authoritative; an unknown provider falls back to its code.
    ({"provider": "usgov", "series": "usgov:eia/electricity_sales/US.COM", "provider_name": "Stored name"},
     "Stored name"),
    ({"provider": "unknown", "series": "unknown:x"}, "unknown"),
])
def test_official_provider_label_falls_back_to_the_catalog_publisher(row, expected):
    assert ReportAgent._official_provider_label(row) == expected
