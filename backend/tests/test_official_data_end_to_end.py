"""One guarded integration: real MCP to publication, PNG APIs and demo export.

Run with main_offline_pytest.py, allowing fixtures/official_data_mcp.py and the
existing data-visuals/scripts/render_data.py. Every observation is synthetic.
Plain pytest skips it (``guarded_runner``): the runner's audit guard is what proves
the run touched no network, saved data or files outside its evidence directory.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import pytest


REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "backend/tests/fixtures/official_data_mcp.py"
RENDERER = REPO / "deerflow_bridge/skills/data-visuals/scripts/render_data.py"
SOURCES = (
    "deerflow_bridge/data_mcp.py", "deerflow_bridge/data_sources.py", "deerflow_bridge/data_catalog.py",
    "deerflow_bridge/research_gateway.py", "deerflow_bridge/linear_research.py",
    "deerflow_bridge/deerflow_research.py", "deerflow_bridge/data_tools.py",
    "deerflow_bridge/skills/data-visuals/scripts/render_data.py",
    "backend/app/services/pipeline_orchestrator.py", "backend/app/services/official_data.py",
    "backend/app/services/report_agent.py", "backend/app/services/report_visualizer.py",
    "backend/app/services/forecast_extractor.py", "backend/app/services/report_lint.py",
    "backend/app/api/report.py", "backend/app/__init__.py", "backend/app/config.py",
    "backend/scripts/export_demo_site_data.py", "backend/scripts/main_offline_pytest.py",
    "backend/tests/test_official_data_end_to_end.py", "backend/tests/fixtures/official_data_mcp.py",
)


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class NoExternalIntelligence:
    """Only the unrelated model/graph boundary is replaced; calls must stay zero."""
    model_name = "offline-no-model"

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        def forbidden(*args, **kwargs):
            self.calls.append(name)
            raise AssertionError("Unexpected external intelligence call: " + name)
        return forbidden


class Log:
    def __init__(self):
        self.lines = []

    def write(self, kind, message):
        self.lines.append([kind, str(message)])


def _synthetic_forecast(carrier):
    """Publication inputs only; use real normalization/quality, never a model."""
    from app.services import forecast_extractor as fe
    probabilities = [0.8, 0.76, 0.68, 0.64, 0.57, 0.42, 0.35, 0.27, 0.2, 0.12]
    binaries = fe._normalize_binaries([
        {"statement": f"Synthetic Unemployment Rate >= {4 + index / 4:g}% in April 2027",
         "probability": probability,
         "resolution_criteria": f"fred:UNRATE >= {4 + index / 4:g}% for 2027-04",
         "resolution_source": "FRED", "theme": ["labor", "policy", "macro"][index % 3],
         "horizon_year": 2027, "scenario_membership": {"derivable": False, "yes_scenarios": []},
         "data_anchor": {"series": "fred:UNRATE", "comparator": ">=", "threshold": 4 + index / 4,
                         "observation": "2027-04", "units": "Percent", "transform": ""}}
        for index, probability in enumerate(probabilities)
    ], official_data=carrier)
    quality = fe._binary_quality(binaries, min_count=10)
    assert len(binaries) == 10 and quality["passed"], quality
    return {"headline": "Synthetic labor outlook", "horizon": "2027-04-01", "confidence": "medium",
            "scenarios": [{"name": "Baseline", "probability": 0.6,
                           "resolution_criteria": "The official review records the baseline outcome at the horizon."},
                          {"name": "Stress", "probability": 0.4,
                           "resolution_criteria": "The official review records the alternative stress outcome at the horizon."}],
            "binary_forecasts": binaries, "binary_quality": quality}


@pytest.mark.guarded_runner
def test_guarded_mcp_to_promoted_research_and_report_png(tmp_path, monkeypatch):
    evidence_root = Path(os.environ["MAIN_OFFLINE_EVIDENCE"])
    before = {name: _hash(REPO / name) for name in SOURCES}
    identity = {key: os.environ.get(key) for key in ("HOME", "home", "CODEX_HOME", "USERPROFILE")}
    evidence = {"schema": "official-data-end-to-end/v1", "synthetic": True,
                "source_before": before, "stage": "imports", "artifacts": {}}
    hub = None
    try:
        # Real bridge modules (bare names, as deployed) and backend consumers; no substitutes.
        monkeypatch.syspath_prepend(str(REPO / "deerflow_bridge"))
        import data_mcp as dm
        import data_sources as ds
        import research_gateway as rg
        import linear_research as lr
        import deerflow_research as bridge
        from app.config import Config
        from app.services import pipeline_orchestrator as po
        from app.services.official_data import load_official_data
        from app.services.report_agent import Report, ReportAgent, ReportManager, ReportStatus
        from app.services.report_visualizer import ReportVisualizer

        # Select the production static-chart configuration, avoiding kaleido's
        # browser requirement without replacing either renderer.
        monkeypatch.setenv("RESEARCH_CHARTS_PYTHON", sys.executable)
        for key, value in {"REPORT_VIZ_INTERACTIVE": False, "REPORT_VIZ_PNG_EXPORT": False,
                           "REPORT_VIZ_PRICE_HISTORY": False, "REPORT_VIZ_CHARTS": True,
                           "REPORT_STRUCTURED_FORECAST": True, "REPORT_PUBLISH_GATE": True,
                           "REPORT_CITATION_FINALIZER": True, "REPORT_EDITORIAL_LINT": True,
                           "REPORT_FINAL_READ_ONLY_AUDIT": True}.items():
            monkeypatch.setattr(Config, key, value, raising=False)
        monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path / "empty-simulation"))

        server_cwd = tmp_path / "server"
        server_cwd.mkdir()
        transcript = server_cwd / "calls.jsonl"
        spec = dm.ServerSpec(name="fred", command=sys.executable, args=(str(FIXTURE),),
                             env={"OFFICIAL_DATA_FIXTURE_RECEIPT": str(transcript)}, cwd=str(server_cwd),
                             start_timeout=20.0, call_timeout=10.0, max_concurrency=1)
        hub = dm.McpHub({"fred": spec}, errlog_dir=tmp_path / "mcp-logs")
        client = ds.DataSources(hub, providers=["fred"],
                                env={"DATA_SOURCES_ENABLED": "true", "FRED_API_KEY": "synthetic-not-a-credential"},
                                cache_dir=tmp_path / "data-cache", clock=lambda: 1751328000.0)
        model, graph, log = NoExternalIntelligence(), NoExternalIntelligence(), Log()
        research, promoted = (tmp_path / name for name in ("research", "promoted"))
        report_id = "report_official_data"
        report_dir = tmp_path / "reports" / report_id
        monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(report_dir.parent))
        args = SimpleNamespace(model=model.model_name, depth="quick", target_language="English", no_actors=True)

        def tools_factory(ledger, pages, bridge, reporter, limits):
            return rg.ResearchTools(ledger, pages, bridge=bridge, plog=reporter, limits=limits, data_sources=client)

        engine = lr._Engine("Synthetic offline unemployment baseline", research, args, {}, log, lambda: None,
                            bridge, lambda args, reporter, bridge, preset: rg.ModelGateway(model, reporter),
                            tools_factory, {"DATA_SOURCES_ENABLED": "true"})
        evidence["stage"] = "real MCP retrieval"
        engine.ledger.register("https://example.org/uncited-context", "Unused synthetic context")
        output = engine.tools.data_get("fred:UNRATE", start="2024-01-01", end="2025-06-30", agent_id="K1")
        assert lr.tool_output_sids("data_get", output) == (2, [2]), (output, log.lines)
        assert engine.tools.data_get("fred:UNRATE", agent_id="K2") == output
        calls = [json.loads(line) for line in transcript.read_text().splitlines()]
        assert len(calls) == 1 and calls[0]["pid"] != os.getpid()
        assert calls[0]["tool"] == "fred_get_series"
        assert calls[0]["arguments"]["observation_start"] == "2024-01-01"
        assert calls[0]["arguments"]["observation_end"] == "2025-06-30"
        assert calls[0]["arguments"]["units"] == "lin"
        status = hub.status()["fred"]
        assert status["state"] == "ready" and "fred_get_series" in status["tools"] and status["calls"] == 1
        series, sid = engine.tools.data_rows()[0]
        assert series.route == "mcp" and len(series.observations) == 18
        expected_values = [3.8, 3.9, 3.9, 4.0, 4.1, 4.1, 4.2, None, 4.2, 4.1, 4.1, 4.0,
                           4.0, None, 4.1, 4.2, 4.3, 4.2]
        expected_observations = [(f"{2024 + index // 12}-{index % 12 + 1:02d}-01", value)
                                 for index, value in enumerate(expected_values)]
        assert [(obs.date, obs.value) for obs in series.observations] == expected_observations
        assert series.provenance["tool_responses"][0]["sha256"] == calls[0]["response_sha256"]
        assert [(obs.date, obs.value) for obs in series.observations if obs.value is None] == [
            ("2024-08-01", None), ("2025-02-01", None)]
        page = engine.tools.page_text(sid)
        row = engine.ledger.get(sid)
        assert page == ds.render_series_page(series)
        assert _hash(engine.work / row["page_path"]) == row["content_sha256"]
        assert ds.load_datasets(engine.work)[0]["source_id"] == "S2"
        evidence.update(mcp_calls=calls, hub_before_close=hub.status(), stored_page_sha256=row["content_sha256"])
        client.close()  # Everything from here must consume the stored generation.
        assert hub.status()["fred"]["state"] == "closed"

        evidence["stage"] = "research publication and actual research renderer"
        engine.plan = lr.build_plan(engine.question, lr.ENGLISH, "2025-07-01", engine.preset, 0, None, None)
        engine.kiqs = list(engine.plan.kiqs)
        engine.data_index = {engine.kiqs[0].id: [sid]}
        engine._prepare_data_exhibits()
        assert engine.data_charts, log.lines
        sections = [{"index": section.index, "title": section.title, "is_scenario": section.is_scenario,
                     "body": f"This synthetic {section.title.lower()} section exercises the stored-evidence path. "
                             "The figures below are invented acceptance inputs; they are not actual economic statistics. "
                             "Missing periods remain explicit gaps, and publication retains the original units and source identity."}
                    for section in engine.plan.sections]
        engine._embed_data_exhibits(sections)
        body = lr.render_report(engine.question, engine.language, "Offline synthetic acceptance only.",
                                sections, engine.plan.scenarios)
        body, order = lr.renumber_citations(body, lambda source_id: source_id == sid)
        assert order == [2]
        engine._finalize_data_citations(order)
        published_sources = engine._source_rows(order)
        engine.write_json(research / "sources.json", published_sources, internal=False)
        engine.write_text(research / "research_report.md", body + "\n" + lr.render_references(order, engine.ledger.get))
        carrier_before = load_official_data(research)
        assert carrier_before["series"][0]["source_id"] == "S1"
        assert "[S2]" not in body and "[S1]" in body
        for chart in engine.data_charts:
            png = research / chart["path"]
            assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") and png.stat().st_size > 5000
            evidence["artifacts"]["research:" + chart["path"]] = {"path": str(png), "sha256": _hash(png)}

        evidence["stage"] = "real research promotion and carrier load"
        seal = po._promote_research_contract(str(research), str(promoted))
        assert po._validate_research_contract(str(promoted))
        carrier = load_official_data(promoted)
        assert carrier == carrier_before
        assert carrier["series"][0]["observations"] == series.to_dict()["observations"]
        assert [(obs["date"], obs["value"]) for obs in carrier["series"][0]["observations"]] == expected_observations
        assert ds.render_series_page(ds.Series.from_dict(carrier["series"][0])) == page
        promoted_sources = json.loads((promoted / "sources.json").read_text())
        assert len(promoted_sources) == 1
        assert promoted_sources[0]["source_origin"] == "official_data"
        assert promoted_sources[0]["dataset"]["series"] == "fred:UNRATE"
        assert promoted_sources[0]["dataset"]["file"] == carrier["series"][0]["file"]
        assert promoted_sources[0]["content_sha256"] == row["content_sha256"]
        research_charts = [chart for chart in json.loads((promoted / "charts.json").read_text())
                           if str(chart.get("id", "")).startswith("data_")]
        assert research_charts
        for chart in research_charts:
            assert chart["source_ids"] == ["S1"] and chart["series"] == ["fred:UNRATE"]
            assert "[S1]" in chart["caption"] and "[S2]" not in chart["caption"]
        for relative, entry in seal["files"].items():
            assert _hash(promoted / relative) == entry["sha256"]
            assert (research / relative).read_bytes() == (promoted / relative).read_bytes()
        seal_hash = _hash(promoted / po._RESEARCH_CONTRACT_FILENAME)
        evidence["promotion"] = {"seal_path": str(promoted / po._RESEARCH_CONTRACT_FILENAME),
                                 "seal_sha256": seal_hash, "files": seal["files"]}

        evidence["stage"] = "real ReportAgent context and ReportVisualizer PNG"
        report_dir.mkdir(parents=True)
        agent = ReportAgent("synthetic-graph", "", engine.question, llm_client=model, zep_tools=graph,
                            research_report=(promoted / "research_report.md").read_text(),
                            sources=json.loads((promoted / "sources.json").read_text()),
                            charts_manifest=json.loads((promoted / "charts.json").read_text()), official_data=carrier)
        assert agent.official_data is carrier
        assert "4.2%" in agent._data_pack and "[S1]" in agent._data_pack
        assert agent._data_pack in agent._prepend_research_background("Offline analysis")
        agent._forecast_spine = _synthetic_forecast(carrier)
        (report_dir / "forecast.json").write_text(json.dumps(agent._forecast_spine))
        arts = agent._collect_viz_artifacts(report_id, str(report_dir))
        assert arts["official_data"] is carrier
        visualizer = ReportVisualizer()
        panels = visualizer._official_chart_panels(arts["official_data"], {})
        assert len(panels) == 1
        assert panels[0]["x"] == [period for period, _ in expected_observations]
        assert panels[0]["values"]["historical observation"] == expected_values
        items = visualizer.build_all(report_id, str(report_dir), arts)
        official = [item for item in items if item.get("source") == "official_data"]
        assert len(official) >= 2
        for item in official:
            assert item["type"] == "png" and "[S1]" in item["source_caption"]
            png = report_dir / item["path"]
            assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") and png.stat().st_size > 5000
            assert item["provenance"][0]["sha256"] == carrier["series"][0]["sha256"]
            assert item["provenance"][0]["units"] == "Percent"
            evidence["artifacts"]["report:" + item["path"]] = {"path": str(png), "sha256": _hash(png)}
        markdown = agent._place_visualizations("# Synthetic official-data report\n\n## Official data\n\nSynthetic observations only.",
                                               str(report_dir), official)
        assert "[S1]" in markdown and "[S2]" not in markdown
        paths = re.findall(r"!\[[^\]]*\]\((charts/[^)]+)\)", markdown)
        assert paths and all((report_dir / relative).is_file() for relative in paths)
        (report_dir / "official-data-acceptance.md").write_text(markdown)

        evidence["stage"] = "real structured-report publication gate"
        evidence["publication"] = {"mode": "real publication; no admission bypass", "bypass_applied": False}
        report = Report(report_id=report_id, simulation_id="synthetic-simulation", graph_id="synthetic-graph",
                        simulation_requirement=engine.question, status=ReportStatus.COMPLETED,
                        markdown_content=markdown, created_at="2025-07-01T00:00:00Z",
                        completed_at="2025-07-01T00:01:00Z")
        ReportManager.save_report(report)
        agent._prepend_binary_forecasts_section(report_id, report)
        agent._append_resolution_section(report_id, report)
        stages = {"before": report.markdown_content}
        agent._apply_report_lint(report_id, report)
        stages["after_initial_lint"] = report.markdown_content
        stabilization = agent._stabilize_publish_markdown(report_id, report, max_passes=6)
        stages["after_stabilization"] = report.markdown_content
        audit = agent._enforce_final_publish_audit(report_id, report)
        ReportManager.save_report(report)
        publication = ReportManager.publication_status(report_id)
        assert publication["publishable"], publication
        assert audit["hard_passed"] and not audit["lint"]["changed"]
        assert audit["official_chart_captions"]["passed"]
        assert audit["structured_forecast"]["required"] and audit["structured_forecast"]["valid"]
        assert audit["publish_gate"]["passed"] is True
        # Body [S1] markers: one per official chart caption plus one per "Official series to
        # watch" row (each anchored binary's row cites its stored series), none dangling.
        watch_rows = [line for line in report.markdown_content.splitlines()
                      if line.startswith("| Unemployment Rate — United States (fred:UNRATE) |")]
        assert len(watch_rows) == len(agent._forecast_spine["binary_forecasts"]) == 10
        assert all(line.endswith("[S1] |") for line in watch_rows)
        assert audit["citation_body_markers"]["counts"] == {"S1": len(official) + len(watch_rows)}
        assert audit["citation_body_markers"]["dangling"] == []
        assert audit["markdown_sha256"] == _hash(report_dir / "full_report.md")
        assert audit["forecast_sha256"] == _hash(report_dir / "forecast.json")
        (report_dir / "publication-stages.json").write_text(json.dumps(
            {"stages": stages, "stabilization": stabilization, "audit": audit}, indent=2))
        evidence["publication"].update(
            actual_status=publication, audit=audit,
            audit_path=str(report_dir / "final_audit.json"),
            audit_sha256=_hash(report_dir / "final_audit.json"))
        final_markdown = report.markdown_content
        assert "[S1]" in final_markdown and "[S2]" not in final_markdown
        assert (report_dir / "full_report.md").read_bytes() == final_markdown.encode("utf-8")
        manifest_bytes = (report_dir / "viz_manifest.json").read_bytes()

        from app import create_app
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as web:
            response = web.get(f"/api/report/{report_id}")
            assert response.status_code == 200
            assert response.get_json()["data"]["publishable"] is True
            assert response.get_json()["data"]["markdown_content"] == final_markdown
            response = web.get(f"/api/report/{report_id}/download")
            assert response.status_code == 200 and response.data == final_markdown.encode("utf-8")
            response = web.get(f"/api/report/{report_id}/viz-manifest")
            assert response.status_code == 200, response.get_data(as_text=True)
            api_manifest = response.get_json()
            assert api_manifest["success"] and api_manifest["schema_version"] == 2
            assert api_manifest["data"] == items
            assert api_manifest["skipped"] == json.loads(manifest_bytes)["skipped"]
            api_assets = {}
            for item in official:
                response = web.get(f"/api/report/{report_id}/{item['path']}")
                assert response.status_code == 200 and response.mimetype == "image/png"
                assert response.data == (report_dir / item["path"]).read_bytes()
                api_assets[item["path"]] = hashlib.sha256(response.data).hexdigest()
                api_item = next(row for row in api_manifest["data"] if row["id"] == item["id"])
                for field in ("path", "caption", "source_caption", "provenance"):
                    assert api_item[field] == item[field]
        assert (report_dir / "viz_manifest.json").read_bytes() == manifest_bytes

        evidence["stage"] = "real demo export copy and rebase"
        from scripts import export_demo_site_data as exporter
        monkeypatch.setattr(exporter, "UPLOADS", str(tmp_path))
        demo_key = "official-data-fixture"
        site = tmp_path / "site"
        demo = site / "demos" / demo_key
        demo.mkdir(parents=True)
        assets, languages = exporter.export_report(demo_key, report_id, str(demo))
        assert set(assets) == {item["path"] for item in official}
        exported_markdown = (demo / "report.md").read_text()
        # The only allowed Markdown change here is rebasing its local links.
        restored_links = exported_markdown.replace(f"demos/{demo_key}/charts/", "charts/")
        assert restored_links == final_markdown
        captions = [line for line in final_markdown.splitlines() if line.lstrip("*").startswith("Source:")]
        assert len(captions) == len(official) and all("[S1]" in line for line in captions)
        assert all(line in exported_markdown for line in captions)
        assert "[S2]" not in exported_markdown
        for item in official:
            path = item["path"]
            assert (demo / path).read_bytes() == (report_dir / path).read_bytes()
            assert _hash(demo / path) == api_assets[path]
            assert f"demos/{demo_key}/{path}" in exported_markdown
            evidence["artifacts"]["demo:" + path] = {"path": str(demo / path), "sha256": _hash(demo / path)}
        dossier_assets, dossier_languages = exporter.export_dossier(demo_key, str(promoted), str(demo))
        exported_dossier = (demo / "dossier.md").read_text()
        assert exported_dossier.replace(f"demos/{demo_key}/research-charts/", "charts/") == (
            promoted / "research_report.md").read_text()
        for chart in research_charts:
            path = "research-charts/" + Path(chart["path"]).name
            assert path in dossier_assets
            assert (demo / path).read_bytes() == (promoted / chart["path"]).read_bytes()
            assert f"demos/{demo_key}/{path}" in exported_dossier
        assert (report_dir / "viz_manifest.json").read_bytes() == manifest_bytes
        assert _hash(report_dir / "final_audit.json") == evidence["publication"]["audit_sha256"]
        assert ReportManager.is_publishable(report_id)
        evidence.update(flask_api={"manifest": api_manifest, "asset_sha256": api_assets},
                        demo_export={"root": str(demo), "report_assets": assets, "report_languages": languages,
                                     "dossier_assets": dossier_assets, "dossier_languages": dossier_languages,
                                     "markdown_sha256": _hash(demo / "report.md"), "source_captions": captions})
        assert _hash(promoted / po._RESEARCH_CONTRACT_FILENAME) == seal_hash
        assert po._validate_research_contract(str(promoted))
        assert len(transcript.read_text().splitlines()) == 1
        assert model.calls == graph.calls == []
        evidence.update(stage="complete", report_items=official, model_calls=model.calls, graph_calls=graph.calls,
                        carrier=carrier, report_markdown=str(report_dir / "full_report.md"),
                        report_markdown_sha256=_hash(report_dir / "full_report.md"))
    finally:
        if hub is not None:
            hub.close()
            evidence["hub_after_close"] = hub.status()
        after = {name: _hash(REPO / name) for name in SOURCES}
        evidence.update(source_after=after, source_unchanged=before == after,
                        identity_preserved=identity == {key: os.environ.get(key) for key in identity})
        (evidence_root / "official-data-end-to-end.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False))
        assert before == after, "Source drift during integrated acceptance; repeat on frozen bytes"
        assert evidence["identity_preserved"]
