"""Actual official-chart generation through the real report publication sequence.

All values are synthetic. Sources use the production official-data ledger shape
(dataset identity + excerpt, not a fabricated full-text evidence field). No model,
provider, graph service, saved run or publishability bypass is used.
"""
from copy import deepcopy
from collections import Counter
import hashlib
import json
from pathlib import Path

import pytest

from app.config import Config
from app.services import report_lint
from app.services.report_agent import Report, ReportAgent, ReportManager, ReportStatus
from app.services.official_data import data_api, load_official_data, simulation_research_binding
from app.services.simulation_manager import SimulationManager
from app.services.simulation_runner import SimulationRunner


SIMULATION_ID = "sim_synthetic_publication"


class NoExternalCalls:
    def __getattr__(self, name):
        raise AssertionError(f"Unexpected external intelligence call: {name}")


@pytest.fixture
def report_case(tmp_path, monkeypatch, request):
    api = data_api()
    values = [3.8, 3.9, 3.9, 4.0, 4.1, 4.1, 4.2, None, 4.2, 4.1, 4.1, 4.0,
              4.0, None, 4.1, 4.2, 4.3, 4.2]
    series = api.Series(
        series="fred:UNRATE", provider="fred", provider_name="FRED",
        title="Synthetic Unemployment Rate", units="Percent", frequency="M", seasonal_adjustment="SA",
        source_url="https://fred.stlouisfed.org/series/UNRATE", retrieved_at="2025-07-01T00:00:00Z",
        observations=[api.Observation(f"{2024 + i // 12}-{i % 12 + 1:02d}-01", value, "observed")
                      for i, value in enumerate(values)],
    )
    handoff = tmp_path / "handoff"
    datasets = [series]
    if getattr(request, "param", "") in {"mixed", "mixed_unindexed"}:
        datasets.append(api.Series(series="fred:GDPC1", provider="fred", provider_name="FRED",
                                  title="Synthetic Real Gross Domestic Product",
                                  units="Billions of Chained 2017 Dollars", frequency="Q", seasonal_adjustment="SAAR",
                                  source_url="https://fred.stlouisfed.org/series/GDPC1", retrieved_at=series.retrieved_at,
                                  observations=[api.Observation("2025-01-01", 23000, "observed"),
                                                api.Observation("2025-04-01", 23400, "observed")]))
    api.write_dataset_files(datasets, handoff, citations={row.series: f"S{i}" for i, row in enumerate(datasets, 1)})
    carrier = load_official_data(handoff)
    assert carrier
    source = {"source_id": "src_synthetic", "url": series.source_url, "title": series.title,
              "source_origin": "official_data", "tier": "S1", "reachable": True,
              "content_sha256": hashlib.sha256(api.render_series_page(series).encode()).hexdigest(),
              "excerpt": "Latest: 4.2% (2025-06-01); see observation status below.; "
                         "Year earlier: 4.1% (2024-06-01); change 0.1% (2.44%).; "
                         "5-year range: 3.8% (2024-01-01) to 4.3% (2025-05-01).",
              "dataset": {"series": series.series, "provider": "fred", "units": "Percent",
                          "frequency": "M", "source_url": series.source_url,
                          "file": next(row["file"] for row in carrier["series"] if row["series"] == series.series)}, "supports": []}
    source_rows = [source]
    if len(datasets) > 1 and getattr(request, "param", "") != "mixed_unindexed":
        gdp = datasets[1]
        source_rows.append({"url": gdp.source_url, "title": gdp.title, "tier": "S1", "source_origin": "official_data",
                            "excerpt": "Latest: 23400 (2025-04-01).", "supports": [],
                            "dataset": {"series": gdp.series, "provider": "fred", "units": gdp.units,
                                        "frequency": "Q", "source_url": gdp.source_url,
                                        "file": next(row["file"] for row in carrier["series"] if row["series"] == gdp.series)}})
    (handoff / "sources.json").write_text(json.dumps(source_rows))
    sources = json.loads((handoff / "sources.json").read_text())
    for name, value in {"REPORT_VIZ_INTERACTIVE": False, "REPORT_VIZ_PNG_EXPORT": False,
                        "REPORT_VIZ_PRICE_HISTORY": False, "REPORT_VIZ_CHARTS": True,
                        "REPORT_VISUALIZER": True, "REPORT_VISUALIZATIONS": True, "REPORT_DATA_CHARTS": True,
                        "REPORT_STRUCTURED_FORECAST": False, "REPORT_CITATION_FINALIZER": True,
                        "REPORT_EDITORIAL_LINT": True, "REPORT_FINAL_READ_ONLY_AUDIT": True}.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    simulation_root = str(tmp_path / "empty-simulation")
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", simulation_root)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", simulation_root)
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", simulation_root)
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))
    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(tmp_path / "forecast-ledger"))
    monkeypatch.setattr(ReportAgent, "_define_tools", lambda self: {})
    monkeypatch.setattr(ReportAgent, "_locate_timeline", lambda self: None)
    monkeypatch.setattr(ReportAgent, "_locate_handoff_dir", lambda self: None)
    # This carrier-only fixture has no simulation admission or research binding.
    assert simulation_research_binding(SIMULATION_ID) == {"status": "missing"}
    agent = ReportAgent("synthetic_graph", SIMULATION_ID, "Assess the unemployment outlook",
                        llm_client=NoExternalCalls(), zep_tools=NoExternalCalls(),
                        sources=sources, official_data=carrier)
    report = Report(report_id="report_data_publication", simulation_id=SIMULATION_ID, graph_id="synthetic_graph",
                    simulation_requirement="Assess the unemployment outlook", status=ReportStatus.COMPLETED,
                    markdown_content="# Official data report\n\n## Official data\n\nThe stored series shows the labour market baseline.\n",
                    created_at="2025-07-01T00:00:00Z", completed_at="2025-07-01T00:01:00Z")
    ReportManager.save_report(report)
    folder = Path(ReportManager._get_report_folder(report.report_id))
    agent._inject_visualizations(report.report_id, report)
    manifest = json.loads((folder / "viz_manifest.json").read_text())
    official = [item for item in manifest["items"] if item.get("source") == "official_data"]
    # Without a forecast anchor the visualizer renders only the dashboard (RPT-8).
    assert [item["id"] for item in official] == ["official_indicators"]
    assert report.markdown_content.count("[S1]") == _exhibits_citing(manifest, "S1") == 1
    assert all((folder / item["path"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for item in official)
    (folder / "before-publication.md").write_text(report.markdown_content)
    return agent, report, folder, manifest


def _exhibits_citing(manifest, tag):
    return sum(any(row.get("source_id") == tag for row in item["provenance"])
               for item in manifest["items"] if item.get("source") == "official_data")


def _finalize(agent, report, folder):
    # Same deterministic order as generate_report after all authored sections,
    # forecasts and visualizations have been assembled.
    stages = {"before": report.markdown_content}
    agent._apply_report_lint(report.report_id, report)
    stages["after_initial_lint"] = report.markdown_content
    stabilized = agent._stabilize_publish_markdown(report.report_id, report, max_passes=6)
    stages["after_stabilization"] = report.markdown_content
    audit = agent._enforce_final_publish_audit(report.report_id, report)
    (folder / "publication-stages.json").write_text(json.dumps({"stages": stages, "stabilization": stabilized,
                                                               "audit": audit}, indent=2))
    ReportManager.save_report(report)
    return audit


def test_real_chart_captions_survive_complete_publication_sequence(report_case):
    agent, report, folder, manifest = report_case
    before_manifest = (folder / "viz_manifest.json").read_bytes()
    audit = _finalize(agent, report, folder)
    assert audit["hard_passed"] and not audit["lint"]["changed"]
    assert ReportManager.is_publishable(report.report_id)
    for item in manifest["items"]:
        if item.get("source") != "official_data":
            continue
        marker = f"<!-- viz:{item['path']} -->"
        block = report.markdown_content.split(marker, 1)[1].split("<!-- viz:", 1)[0].split("## References", 1)[0]
        assert "Source:" in block and "[S1]" in block, block
        assert "*" + item["source_caption"] + "*" in block  # MISSED-4: one caption helper
    assert audit["citation_body_markers"]["counts"]["S1"] == _exhibits_citing(manifest, "S1")
    citations = json.loads((folder / "citations.json").read_text())
    assert [row["tag"] for row in citations["markers"]] == ["S1"]
    assert (folder / "viz_manifest.json").read_bytes() == before_manifest
    assert report_lint.lint_report(report.markdown_content, "English", mode="final")[0] == report.markdown_content


def test_missing_stabilization_rejects_unstable_prose(report_case):
    agent, report, folder, _manifest = report_case
    sentence = "The interpretation depends on whether the labour market adjustment persists through changing economic conditions."
    report.markdown_content += "\n" + sentence + "\n\n" + sentence + "\n"
    ReportManager.save_report(report)
    agent._finalize_citations_for_publish(report.report_id, report)
    ReportManager.save_report(report)
    audit = agent._audit_final_published_markdown(report.report_id, report)
    assert audit["lint"]["changed"] and not audit["hard_passed"]
    # This characterization intentionally omits the real production stabilizer.
    assert not ReportManager.is_publishable(report.report_id)
    assert _finalize(agent, report, folder)["hard_passed"]
    assert report.markdown_content.count(sentence) == 1


@pytest.mark.parametrize("marker", ["S999", "S2"])
def test_invalid_chart_source_marker_is_not_admitted(report_case, marker):
    agent, report, folder, manifest = report_case
    if marker == "S2":
        source = deepcopy(agent.sources[0])
        source.update(url="https://fred.stlouisfed.org/series/INDPRO", title="Industrial Production")
        source["dataset"]["series"] = "fred:INDPRO"
        agent._citation_index["S2"] = source
    report.markdown_content = report.markdown_content.replace("[S1]", f"[{marker}]")
    ReportManager.save_report(report)
    audit = agent._audit_final_published_markdown(report.report_id, report)
    assert not audit["hard_passed"]
    assert not ReportManager.is_publishable(report.report_id)
    if marker == "S2":
        assert audit["semantic_citations"]["unsupported"] == _exhibits_citing(manifest, "S1")
    else:
        assert audit["citation_markers"]["dangling"] == ["S999"]


def test_invalid_chart_attribution_cannot_be_laundered_by_finalization(report_case):
    agent, report, folder, manifest = report_case
    report.markdown_content = report.markdown_content.replace("[S1]", "[S999]")
    ReportManager.save_report(report)
    with pytest.raises(RuntimeError, match="官方数据图表来源"):
        _finalize(agent, report, folder)
    assert not ReportManager.is_publishable(report.report_id)
    audit = json.loads((folder / "final_audit.json").read_text())
    assert audit["official_chart_captions"]["passed"] is False
    assert len(audit["official_chart_captions"]["issues"]) == _exhibits_citing(manifest, "S1")


@pytest.mark.parametrize("before,after", [
    ("; Percent;", "; Dollars;"),
    ("; Monthly;", "; Quarterly;"),
    ("/series/UNRATE>", "/series/INDPRO>"),
    ("; SA*", "; SA. GDP rose 99%*"),
])
def test_canonical_caption_validation_does_not_whitelist_altered_metadata(report_case, before, after):
    agent, report, folder, _manifest = report_case
    report.markdown_content = report.markdown_content.replace(before, after)
    captions = [line for line in report.markdown_content.splitlines() if line.startswith("*Source:")]
    assert captions and all(agent._official_source_caption_support(line, "S1") is False for line in captions)
    ReportManager.save_report(report)
    with pytest.raises(RuntimeError, match="官方数据图表来源|quant_coverage=0.0"):
        _finalize(agent, report, folder)
    assert not ReportManager.is_publishable(report.report_id)


@pytest.mark.parametrize("keep_live_caption", [False, True])
def test_fenced_attribution_is_not_a_live_chart_caption(report_case, keep_live_caption):
    agent, report, folder, _manifest = report_case
    lines = []
    for line in report.markdown_content.splitlines():
        if line.startswith("*Source:"):
            if keep_live_caption:
                lines.append(line)
            lines.extend(["```markdown", line, "```"])
        else:
            lines.append(line)
    report.markdown_content = "\n".join(lines) + "\n"
    ReportManager.save_report(report)
    if keep_live_caption:
        audit = _finalize(agent, report, folder)
        assert audit["official_chart_captions"]["passed"]
        assert audit["citation_body_markers"]["counts"] == {"S1": _exhibits_citing(_manifest, "S1")}
        assert ReportManager.is_publishable(report.report_id)
    else:
        with pytest.raises(RuntimeError, match="官方数据图表来源"):
            _finalize(agent, report, folder)
        assert not ReportManager.is_publishable(report.report_id)


@pytest.mark.parametrize("report_case", ["mixed"], indirect=True)
def test_multiple_sources_and_numeric_units_survive_publication(report_case):
    agent, report, folder, manifest = report_case
    counts = Counter(p["source_id"] for item in manifest["items"] if item.get("source") == "official_data"
                     for p in item["provenance"])
    audit = _finalize(agent, report, folder)
    assert audit["citation_body_markers"]["counts"] == dict(counts)
    assert report.markdown_content.count("Billions of Chained 2017 Dollars") == _exhibits_citing(manifest, "S2")
    assert ReportManager.is_publishable(report.report_id)


@pytest.mark.parametrize("report_case", ["mixed_unindexed"], indirect=True)
def test_unindexed_series_does_not_strip_indexed_dashboard_source(report_case):
    agent, report, folder, manifest = report_case
    audit = _finalize(agent, report, folder)
    # RPT-16: the dataset no research source identifies is still citable, after
    # the research positions; the indexed series keeps its own marker.
    assert audit["citation_body_markers"]["counts"] == {"S1": 1, "S2": 1}
    assert agent._citation_index["S2"]["dataset"]["series"] == "fred:GDPC1"
    assert agent._citation_index["S2"]["source_origin"] == "official_data"
    assert report.markdown_content.count("Billions of Chained 2017 Dollars") == _exhibits_citing(manifest, "S2")


def test_structured_forecast_and_real_api_publish_without_bypass(report_case, monkeypatch):
    from app.services import forecast_extractor as fe
    agent, report, folder, _manifest = report_case
    monkeypatch.setattr(Config, "REPORT_STRUCTURED_FORECAST", True)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True)
    probabilities = [0.8, 0.76, 0.68, 0.64, 0.57, 0.42, 0.35, 0.27, 0.2, 0.12]
    binaries = fe._normalize_binaries([
        {"statement": f"Synthetic Unemployment Rate >= {4 + i / 4:g}% in April 2027",
         "probability": probability, "resolution_criteria": f"fred:UNRATE >= {4 + i / 4:g}% for 2027-04",
         "resolution_source": "FRED", "theme": ["labor", "policy", "macro"][i % 3], "horizon_year": 2027,
         "scenario_membership": {"derivable": False, "yes_scenarios": []},
         "data_anchor": {"series": "fred:UNRATE", "comparator": ">=", "threshold": 4 + i / 4,
                         "observation": "2027-04", "units": "Percent", "transform": ""}}
        for i, probability in enumerate(probabilities)
    ], official_data=agent.official_data)
    forecast = {"headline": "Synthetic labor outlook", "horizon": "2027-04-01", "confidence": "medium",
                "scenarios": [{"name": "Baseline", "probability": 0.6,
                               "resolution_criteria": "The official review records the baseline outcome at the horizon."},
                              {"name": "Stress", "probability": 0.4,
                               "resolution_criteria": "The official review records the alternative stress outcome at the horizon."}],
                "binary_forecasts": binaries, "binary_quality": fe._binary_quality(binaries, min_count=10)}
    # F1: the binary scorecard reports sharpness; the final publication gate
    # owns passed. Retain the historical metric check through legacy_passed.
    assert forecast["binary_quality"].get("legacy_passed", forecast["binary_quality"].get("passed")), forecast["binary_quality"]
    agent._forecast_spine = forecast
    (folder / "forecast.json").write_text(json.dumps(forecast))
    report.markdown_content = "# Labor market outlook\n\n## Official data\n\nThe stored series provides the historical baseline.\n"
    ReportManager.save_report(report)
    agent._prepend_binary_forecasts_section(report.report_id, report)
    agent._inject_visualizations(report.report_id, report)
    agent._append_resolution_section(report.report_id, report)
    audit = _finalize(agent, report, folder)
    assert audit["structured_forecast"]["required"] and audit["structured_forecast"]["valid"]
    assert audit["publish_gate"]["passed"] is True
    manifest = json.loads((folder / "viz_manifest.json").read_text())
    # RPT-16: every anchored 'Official series to watch' row carries the series' [S#].
    watch_rows = [line for line in report.markdown_content.split("\n") if line.startswith("| ")
                  and "(fred:UNRATE)" in line]
    assert len(watch_rows) == len(binaries) and all(row.endswith(" [S1] |") for row in watch_rows)
    assert (audit["citation_body_markers"]["counts"]["S1"]
            == _exhibits_citing(manifest, "S1") + len(watch_rows))
    assert _exhibits_citing(manifest, "S1") >= 2
    assert ReportManager.is_publishable(report.report_id)
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        response = client.get(f"/api/report/{report.report_id}")
        assert response.status_code == 200
        assert response.get_json()["data"]["publishable"] is True
        assert response.get_json()["data"]["markdown_content"] == report.markdown_content
        assert client.get(f"/api/report/{report.report_id}/download").status_code == 200
        response = client.get(f"/api/report/{report.report_id}/viz-manifest")
        assert response.status_code == 200
        for item in response.get_json()["data"]:
            if item.get("source") == "official_data":
                assert "[S1]" in item["source_caption"]
                assert client.get(f"/api/report/{report.report_id}/{item['path']}").data == (folder / item["path"]).read_bytes()
