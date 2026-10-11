"""Offline legacy official-data consumer regressions; synthetic evidence only."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "deerflow_bridge"


@pytest.fixture
def legacy():
    spec = importlib.util.spec_from_file_location("legacy_data_research", BRIDGE / "deerflow_research.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_enabled_prompt_routes_official_data_without_shell(legacy, monkeypatch):
    # The feature switch is the prompt boundary; provider startup stays lazy.
    monkeypatch.setenv("DATA_SOURCES_ENABLED", "true")
    phase = {"label": "primary-evidence", "focus": "Verify observations"}
    for text in [legacy.build_research_prompt("Jobs", "standard", "en"),
                 legacy.build_research_prompt("Jobs", "deep", "en", evidence_only=True),
                 legacy.build_deep_phase_prompt("Jobs", phase, 1, 3, "en")]:
        assert "data_get" in text
        assert "/mnt/skills/public/data-sources/SKILL.md" in text
        assert "via bash" not in text


def test_disabled_prompt_has_no_data_instructions(legacy, monkeypatch):
    monkeypatch.setenv("DATA_SOURCES_ENABLED", "false")
    assert "data_get" not in legacy.build_research_prompt("Jobs", "standard", "en")


def test_official_chart_satisfies_quantitative_visual_requirement(legacy, monkeypatch):
    monkeypatch.setenv("RESEARCH_CHARTS_MIN", "1")
    audit = legacy._visual_contract_audit("Chart a time series", [{"id": "data_fred_unrate"}])
    assert audit["passed"], audit
    assert audit["rendered_decision_ids"] == ["data_fred_unrate"]


def test_legacy_config_registers_bounded_data_tools_and_skill():
    config = yaml.safe_load((BRIDGE / "config.yaml").read_text())
    names = {item["name"] for item in config["tools"]}
    assert {"data_search", "data_get"} <= names
    researcher = config["subagents"]["custom_agents"]["scoped-researcher"]
    assert {"data_search", "data_get"} <= set(researcher["tools"])
    assert "data-sources" in researcher["skills"]
    for name in ("data_search", "data_get"):
        assert config["loop_detection"]["tool_freq_overrides"][name] == {"warn": 30, "hard_limit": 45}
    assert (BRIDGE / "skills/data-sources/SKILL.md").is_file()


@pytest.fixture
def tools_api(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(BRIDGE))
    import data_tools
    import data_sources
    monkeypatch.setenv("DATA_SOURCES_ENABLED", "true")
    monkeypatch.setenv("DEERFLOW_RUN_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setenv("RESEARCH_LINEAR_DATA_CALLS_PER_KIQ", "4")
    monkeypatch.setenv("RESEARCH_LINEAR_MAX_DATA_CALLS_TOTAL", "50")
    class Provider:
        def __init__(self):
            self.calls = []
            self.fail = False
        def enabled(self):
            return True
        def search(self, **kwargs):
            self.calls.append(("search", kwargs))
            return [data_sources.SearchHit(series="fred:UNRATE", title="Unemployment", units="Percent", frequency="M", coverage="2025–2026", provider="fred")]
        def get(self, series, **kwargs):
            self.calls.append((series, kwargs))
            if self.fail:
                return data_sources.DataError(series, "synthetic failure")
            return data_sources.Series(
                series=series + ("#" + kwargs["transform"] if kwargs.get("transform") else ""),
                provider="fred", provider_name="Synthetic official provider", title="Unemployment", title_zh="失业率",
                units="Percent", frequency="M", seasonal_adjustment="SA",
                observations=[data_sources.Observation("2025-01-01", 3.0),
                              data_sources.Observation("2026-01-01", None),
                              data_sources.Observation("2026-02-01", 4.0, "projection")],
                source_url="https://fred.stlouisfed.org/series/" + series.split(":", 1)[1],
                retrieved_at="2026-10-12T00:00:00Z", projection_from="2026-02-01",
                transform=kwargs.get("transform") or "")
    provider = Provider()
    # Deliberately fake the provider factory: this suite exercises the real
    # normalized model/persistence and legacy consumer, not provider transport.
    monkeypatch.setattr(data_sources, "get_data_sources", lambda **kw: provider)
    return data_tools, data_sources, provider


def test_search_is_discovery_get_is_exact_persisted_evidence(tools_api, tmp_path):
    tools, api, provider = tools_api
    result = tools.data_search_impl(" unemployment ")
    assert "fred:UNRATE" in result and "[S" not in result
    assert not (tmp_path / tools.CANDIDATES).exists()
    result = tools.data_get_impl("fred:UNRATE")
    row, = tools.load_candidates(tmp_path, strict=True)
    assert row["text"] == api.render_series_page(row["value"])
    assert row["text"] in result
    assert "projection" in result.lower() and "VERIFIED" not in result
    assert row["value"].source_url == "https://fred.stlouisfed.org/series/UNRATE"
    assert "drf_snapshot=" in row["url"] and "drf_series=" in row["url"]
    assert tools.validated_source(tools.candidate_sources(tmp_path)[0])


def test_restart_dedup_transform_and_window_binding(tools_api, tmp_path, monkeypatch):
    tools, _, provider = tools_api
    first = tools.data_get_impl("fred:UNRATE", start="2025-01-01", end="2026-03-01")
    import importlib
    tools = importlib.reload(tools)
    assert tools.data_get_impl("fred:UNRATE", start="2025-01-01", end="2026-03-01") == first
    assert len(provider.calls) == 1
    assert tools.data_get_impl("fred:UNRATE", start="2020-01-01").startswith("DATA_UNAVAILABLE")
    transformed = tools.data_get_impl("fred:UNRATE", transform="yoy")
    assert transformed.startswith("[S") and transformed != first
    rows = tools.load_candidates(tmp_path, strict=True)
    assert len({r["source_number"] for r in rows}) == 2
    assert len({r["url"] for r in rows}) == 2
    assert len(provider.calls) == 2


def test_concurrent_repeats_and_failures_do_not_repeat_provider_work(tools_api):
    tools, _, provider = tools_api
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: tools.data_get_impl("fred:UNRATE"), range(3)))
    assert len(set(results)) == 1 and len(provider.calls) == 1
    provider.fail = True
    for _ in range(2):
        assert tools.data_get_impl("fred:CPIAUCSL").startswith("DATA_UNAVAILABLE")
    assert len(provider.calls) == 2


def test_budgets_and_disabled_do_not_call_provider(tools_api, monkeypatch):
    tools, _, provider = tools_api
    monkeypatch.setenv("RESEARCH_LINEAR_DATA_CALLS_PER_KIQ", "1")
    assert tools.data_search_impl("unemployment", _agent_id="one").startswith("fred:")
    assert tools.data_get_impl("fred:UNRATE", _agent_id="one").startswith("DATA_BUDGET_EXHAUSTED")
    monkeypatch.setenv("RESEARCH_LINEAR_MAX_DATA_CALLS_TOTAL", "1")
    assert tools.data_get_impl("fred:UNRATE", _agent_id="two").startswith("DATA_BUDGET_EXHAUSTED")
    monkeypatch.setenv("DATA_SOURCES_ENABLED", "false")
    assert tools.data_search_impl("inflation").startswith("DATA_UNAVAILABLE")
    assert tools.data_get_impl("fred:UNRATE").startswith("DATA_UNAVAILABLE")
    assert len(provider.calls) == 1


@pytest.mark.parametrize("damage", ["page", "snapshot", "state_missing", "negative_budget", "wrong_cache_target", "oversize_journal"])
def test_corruption_never_refreshes_or_returns_wrong_data(tools_api, tmp_path, damage):
    tools, _, provider = tools_api
    tools.data_get_impl("fred:UNRATE")
    tools.data_get_impl("fred:CPIAUCSL")
    rows = tools.load_candidates(tmp_path, strict=True)
    state_path = tmp_path / "data_tool_state.json"
    state = json.loads(state_path.read_text())
    if damage == "page":
        (tmp_path / rows[0]["page"]).write_text("fake page")
    elif damage == "snapshot":
        (tmp_path / rows[0]["file"]).write_text("{}")
    elif damage == "state_missing":
        state_path.unlink()
    elif damage == "negative_budget":
        state["calls"] = -1
        state_path.write_text(json.dumps(state))
    elif damage == "wrong_cache_target":
        first, second = state["cache"].values()
        first["url"] = second["url"]
        first["page_sha256"] = second["page_sha256"]
        state_path.write_text(json.dumps(state))
    else:
        (tmp_path / tools.CANDIDATES).write_text("x" * (tools._MAX_FILE + 1))
    result = tools.data_get_impl("fred:UNRATE")
    assert result.startswith("DATA_UNAVAILABLE"), result
    assert len(provider.calls) == 2


def test_forced_provisional_collision_rejected(tools_api, tmp_path, monkeypatch):
    tools, _, provider = tools_api
    monkeypatch.setattr(tools, "provisional_number", lambda *args: 1_000_001)
    assert tools.data_get_impl("fred:UNRATE").startswith("[S1000001]")
    assert tools.data_get_impl("fred:CPIAUCSL").startswith("DATA_UNAVAILABLE")
    assert len(tools.load_candidates(tmp_path, strict=True)) == 1


def test_multibyte_page_obeys_same_capture_and_load_limit(tools_api, tmp_path, monkeypatch):
    tools, api, _ = tools_api
    monkeypatch.setattr(api, "render_series_page", lambda s: "观测值" * 3000)
    assert tools.data_get_impl("fred:UNRATE").startswith("[S")
    assert len(tools.load_candidates(tmp_path, strict=True)) == 1


def test_source_export_synthesis_global_merge_and_finalization(tools_api, legacy, tmp_path, monkeypatch):
    tools, api, provider = tools_api
    legacy._FETCHED_SOURCES[:] = [{"url": "https://example.org/other", "title": "Other", "ok": True}]
    monkeypatch.setattr(legacy, "_research_budget", None)
    response = tools.data_get_impl("fred:UNRATE")
    provisional = tools.load_candidates(tmp_path)[0]["source_number"]
    lane = legacy.export_fetched_sources_for_manifest()
    data_row = next(r for r in lane if r.get("dataset"))
    assert data_row["content"] == api.render_series_page(tools.load_candidates(tmp_path)[0]["value"])
    assert data_row["source_origin"] == "official_data" and data_row["tier"] == "S1"
    assert "receipt_scopes" not in data_row and "purpose" not in data_row
    globals_ = [data_row, {"url": "https://example.org/global", "title": "Global"}] + [r for r in lane if not r.get("dataset")]
    entries = legacy.build_citation_index(globals_)
    text = f"Official value [S{provisional}]."
    assert legacy.remap_lane_citations(text, lane, entries) == "Official value [S1]."
    legacy.seed_manifest_sources(globals_)
    assert legacy._FETCHED_SOURCES[0]["dataset"]["snapshot"] == data_row["dataset"]["snapshot"]
    legacy._set_pinned_citation_index(entries)
    log = type("Log", (), {"write": lambda *args: None})()
    assert f"[S{provisional}]" not in legacy.finalize_report_citations(text, log)
    # Global finalization consumes the transported exact snapshot, even when
    # the original candidate directory is not present in the global output.
    final = tmp_path / "global"
    final.mkdir()
    (final / "sources.json").write_text(json.dumps(globals_))
    (final / "research_report.md").write_text(text)
    manifest = legacy._finalize_data_series(final, plog=log)
    assert len(manifest) == 1 and manifest[0]["source_id"] == "S1"
    assert "[S1]" in (final / "research_report.md").read_text()
    loaded = api.load_datasets(final)
    assert loaded[0]["observations"][1]["value"] is None
    assert loaded[0]["projection_from"] == "2026-02-01"
    assert len(provider.calls) == 1
    before = (final / "sources.json").read_bytes()
    legacy._finalize_data_series(final, plog=log)
    assert (final / "sources.json").read_bytes() == before


def test_two_lanes_provisional_ids_are_content_bound_and_remap_once(tools_api, legacy, tmp_path, monkeypatch):
    tools, _, _ = tools_api
    tools.data_get_impl("fred:UNRATE")
    one = tools.candidate_sources(tmp_path)
    second = tmp_path / "lane2"
    second.mkdir()
    monkeypatch.setenv("DEERFLOW_RUN_ARTIFACT_DIR", str(second))
    tools.data_get_impl("fred:CPIAUCSL")
    two = tools.candidate_sources(second)
    p1, p2 = one[0]["provisional_source_number"], two[0]["provisional_source_number"]
    assert p1 != p2 and min(p1, p2) > 1_000_000
    assert legacy.remap_lane_citations(f"A [S{p1}]", one, legacy.build_citation_index(two + one)) == "A [S2]"
    assert legacy.remap_lane_citations(f"B [S{p2}]", two, legacy.build_citation_index(two + one)) == "B [S1]"
    with pytest.raises(ValueError, match="collision"):
        legacy.remap_lane_citations(f"A [S{p1}]", one + [{**two[0], "provisional_source_number": p1}], legacy.build_citation_index(two + one))


def test_finalize_rejects_tampered_transported_snapshot(tools_api, legacy, tmp_path):
    tools, _, _ = tools_api
    tools.data_get_impl("fred:UNRATE")
    rows = tools.candidate_sources(tmp_path)
    rows[0]["dataset"]["snapshot"]["observations"][0]["value"] = 999
    final = tmp_path / "final"
    final.mkdir()
    (final / "sources.json").write_text(json.dumps(rows))
    assert legacy._finalize_data_series(final) == []
    assert not (final / "data/datasets.json").exists()


def test_renderer_filters_missing_unsafe_paths_and_binds_current_citations(tools_api, legacy, tmp_path, monkeypatch):
    tools, _, _ = tools_api
    tools.data_get_impl("fred:UNRATE")
    legacy._finalize_data_series(tmp_path)
    def run(*args, **kwargs):
        assert "render_data.py" in args[0][1] and kwargs["timeout"] > 0
        (tmp_path / "charts").mkdir(exist_ok=True)
        (tmp_path / "charts/data_valid.png").write_bytes(b"fixture")
        rows = [{"id": "timeline", "path": "charts/timeline.png"},
                {"id": "data_valid", "path": "charts/data_valid.png", "html_path": "charts/data_missing.html", "series": ["fred:UNRATE"], "caption": "Observed and projection [S999]"},
                {"id": "data_missing", "path": "charts/data_missing.png", "series": ["fred:UNRATE"]},
                {"id": "data_escape", "path": "../outside.png", "series": ["fred:UNRATE"]}]
        (tmp_path / "charts.json").write_text(json.dumps(rows))
        return type("Result", (), {"returncode": 0})()
    monkeypatch.setattr("subprocess.run", run)
    rows = legacy._render_data_charts(tmp_path)
    assert len(rows) == 1 and rows[0]["id"] == "data_valid"
    assert "html_path" not in rows[0]
    assert "[S1]" in rows[0]["caption"] and "S999" not in rows[0]["caption"]
    assert json.loads((tmp_path / "charts.json").read_text())[0]["id"] == "timeline"
    assert "data_missing" not in legacy.embed_chart_refs("Body", rows)


def test_renderer_failure_does_not_return_stale_chart(tools_api, legacy, tmp_path, monkeypatch):
    tools, _, _ = tools_api
    tools.data_get_impl("fred:UNRATE")
    legacy._finalize_data_series(tmp_path)
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: type("Result", (), {"returncode": 3})())
    assert legacy._render_data_charts(tmp_path) == []


def test_extract_only_finalizes_data_before_final_identity(tools_api, legacy, tmp_path, monkeypatch):
    from types import SimpleNamespace
    tools, _, provider = tools_api
    tools.data_get_impl("fred:UNRATE")
    provisional = tools.load_candidates(tmp_path)[0]["source_number"]
    (tmp_path / "research_report.md").write_text(f"Observed and projected values [S{provisional}]. " * 50)
    (tmp_path / "sources.json").write_text(json.dumps([{"url": "https://example.org/other", "title": "Other"}]))
    monkeypatch.setattr(legacy, "_collect_prediction_markets", lambda *a, **kw: None)
    monkeypatch.setattr(legacy, "_render_research_charts", lambda *a, **kw: {})
    monkeypatch.setattr(legacy, "_render_data_charts", lambda *a, **kw: [])
    log = SimpleNamespace(write=lambda *a: None, close=lambda: None)
    args = SimpleNamespace(no_actors=True, model="unused", depth="standard", target_language="en")
    meta = {}
    assert legacy.run_extract_only("Jobs", tmp_path, args, meta, log, lambda: None) == 0
    report = (tmp_path / "research_report.md").read_text()
    assert f"[S{provisional}]" not in report and "[S2]" in report
    assert json.loads((tmp_path / "data/datasets.json").read_text())["series"][0]["source_id"] == "S2"
    assert meta["status"] == "completed" and len(provider.calls) == 1


def test_real_evidence_manifest_routes_dataset_citation(tools_api, legacy, tmp_path):
    import hashlib
    tools, _, _ = tools_api
    tools.data_get_impl("fred:UNRATE")
    rows = tools.candidate_sources(tmp_path)
    provisional = rows[0]["provisional_source_number"]
    sources_bytes = json.dumps(rows).encode()
    (tmp_path / "sources.json").write_bytes(sources_bytes)
    evidence = legacy.render_evidence_pack([f"Official projection retains its label [S{provisional}]."])
    evidence_bytes = evidence.encode()
    (tmp_path / "evidence.md").write_bytes(evidence_bytes)
    globals_ = [{"url": "https://example.org/web", "title": "Web"}] + rows
    canonical = json.dumps(globals_, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    manifest = {"version": 2, "sources": globals_, "sources_count": len(globals_),
                "sources_sha256": hashlib.sha256(canonical).hexdigest(),
                "lanes": [{"path": "evidence.md", "bytes": len(evidence_bytes),
                           "sha256": hashlib.sha256(evidence_bytes).hexdigest(),
                           "sources_path": "sources.json", "sources_bytes": len(sources_bytes),
                           "sources_sha256": hashlib.sha256(sources_bytes).hexdigest()}]}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    blocks, sources = legacy.load_evidence_manifest(path)
    assert any("[S2]" in block for block in blocks)
    assert all(str(provisional) not in block for block in blocks)
    assert sources[1]["content_sha256"] == rows[0]["content_sha256"]


def test_dataset_source_cannot_supply_track_b_actor_receipt(tools_api, legacy, tmp_path):
    tools, _, _ = tools_api
    tools.data_get_impl("fred:UNRATE")
    row = tools.candidate_sources(tmp_path)[0]
    # A stored data page is evidence, but its seal cannot supply Track-B
    # purpose/thread/search-result receipts required for actor behavior claims.
    lookup = legacy._canonical_source_lookup([row],
        required_receipt_purpose="track-b", required_receipt_thread_id="actor-thread")
    assert not lookup


def test_real_renderer_publishes_stored_series_chart(tools_api, legacy, tmp_path):
    tools, _, _ = tools_api
    tools.data_get_impl("fred:UNRATE")
    assert legacy._finalize_data_series(tmp_path)
    rows = legacy._render_data_charts(tmp_path, question="Show unemployment", lang="en")
    assert rows, "Invoke guard with --allow-python-script deerflow_bridge/skills/data-visuals/scripts/render_data.py"
    image = tmp_path / rows[0]["path"]
    assert image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert "[S1]" in rows[0]["caption"]
    assert rows[0]["series"] == ["fred:UNRATE"]


def test_seed_refresh_preserves_citation_order_and_dataset_fields(tools_api, legacy, tmp_path, monkeypatch):
    tools, _, _ = tools_api
    tools.data_get_impl("fred:UNRATE")
    row = tools.candidate_sources(tmp_path)[0]
    web = {"url": "https://example.org/web", "title": "Web", "ok": True}
    monkeypatch.setattr(legacy, "_research_budget", None)
    legacy.seed_manifest_sources([row, web])
    legacy.distinct_fetched_count()
    exported = legacy.export_fetched_sources_for_manifest()
    grounded, _ = legacy.merge_fetched_into_sources([])
    assert [r["url"] for r in exported] == [row["url"], web["url"]]
    assert [r["url"] for r in grounded] == [row["url"], web["url"]]
    assert grounded[0]["dataset"]["snapshot"] == row["dataset"]["snapshot"]


def test_same_url_different_body_never_inherits_actor_scope(tools_api, legacy, tmp_path):
    tools, _, _ = tools_api
    tools.data_get_impl("fred:UNRATE")
    row = tools.candidate_sources(tmp_path)[0]
    web = {"url": row["url"], "title": "Web fetched body", "source_origin": "fetched", "reachable": True,
           "content": "Different body", "content_sha256": "b" * 64, "receipt_id": "web-receipt",
           "receipt_scopes": [{"purpose": "track-b", "lane": "track-b", "thread_id": "actor-thread", "receipt_id": "web-receipt", "content_sha256": "b" * 64}]}
    (tmp_path / "sources.json").write_text(json.dumps([web]))
    before = (tmp_path / "sources.json").read_bytes()
    assert legacy._finalize_data_series(tmp_path) == []
    assert (tmp_path / "sources.json").read_bytes() == before
    assert not (tmp_path / "data/datasets.json").exists()


def test_report_namespace_wins_before_provisional_remap(tools_api, legacy, tmp_path, monkeypatch):
    tools, _, _ = tools_api
    tools.data_get_impl("fred:UNRATE")
    row = tools.candidate_sources(tmp_path)[0]
    monkeypatch.setattr(legacy, "_research_budget", None)
    legacy._set_pinned_citation_index([{"n": 1, "url": row["url"], "title": "Dataset"}])
    text = f"Dataset value [S{row['provisional_source_number']}]; web claim [S1].\n\n## References\n\n1. Web — https://example.org/web\n"
    log = type("Log", (), {"write": lambda *a: None})()
    final = legacy.finalize_report_citations(text, log)
    refs = legacy.parse_references_section(final)
    assert "web claim [S1]" in final
    assert "Dataset value [S2]" in final
    assert row["url"] in refs[2]


@pytest.mark.parametrize("separator", [".", ")"])
def test_numbered_references_and_body_are_remapped_together_and_idempotent(tools_api, legacy, tmp_path, separator):
    tools, _, _ = tools_api
    tools.data_get_impl("fred:UNRATE")
    row = tools.candidate_sources(tmp_path)[0]
    (tmp_path / "sources.json").write_text(json.dumps([{"url": "https://example.org/web", "title": "Web"}, row]))
    report = f"Dataset [S1]. Web [S2].\n\n## References\n\n1{separator} Dataset — {row['url']}\n2{separator} Web — https://example.org/web\n"
    path = tmp_path / "research_report.md"
    path.write_text(report)
    assert legacy._finalize_data_series(tmp_path)
    final = path.read_text()
    assert "Dataset [S2]" in final and "Web [S1]" in final
    refs = legacy.parse_references_section(final)
    assert row["url"] in refs[2] and "example.org/web" in refs[1]
    assert legacy._finalize_data_series(tmp_path)
    assert path.read_text() == final


def test_shared_web_refresh_cannot_replace_prior_dataset_with_actor_scopes(tools_api, legacy, tmp_path, monkeypatch):
    from types import SimpleNamespace
    tools, _, _ = tools_api
    tools.data_get_impl("fred:UNRATE")
    row = tools.candidate_sources(tmp_path)[0]
    legacy.seed_manifest_sources([row])
    web = {"url": row["url"], "title": "Web body", "content_sha256": "b" * 64,
           "receipt_id": "web", "receipt_scopes": [{"purpose": "track-b", "thread_id": "actor-thread"}]}
    monkeypatch.setattr(legacy, "_research_budget", SimpleNamespace(list_fetched_sources=lambda: [web]))
    exported = legacy.export_fetched_sources_for_manifest()
    assert len(exported) == 1 and tools.validated_source(exported[0])
    assert "receipt_scopes" not in exported[0]
    assert exported[0]["content"] == row["content"]


def test_transported_dataset_cannot_publish_injected_track_b_scope(tools_api, legacy, tmp_path):
    tools, _, _ = tools_api
    tools.data_get_impl("fred:UNRATE")
    row = tools.candidate_sources(tmp_path)[0]
    row["receipt_scopes"] = [{"purpose": "actor-ontology", "lane": "track-b", "thread_id": "actor-thread", "receipt_id": row["receipt_id"], "content_sha256": row["content_sha256"]}]
    row.update(purpose="actor-ontology", lane="track-b", thread_id="actor-thread")
    # Valid positive control: this injected scope really matches the legacy
    # actor predicate, so the regression cannot pass on a misspelled purpose.
    assert legacy._canonical_source_lookup([row], required_receipt_purpose="track-b", required_receipt_thread_id="actor-thread")
    final = tmp_path / "transported-only"
    final.mkdir()
    (final / "sources.json").write_text(json.dumps([row]))
    assert legacy._finalize_data_series(final)
    published = json.loads((final / "sources.json").read_text())
    assert not legacy._canonical_source_lookup(published, required_receipt_purpose="track-b", required_receipt_thread_id="actor-thread")
    assert not any(k in published[0] for k in ("receipt_scopes", "thread_id", "lane", "purpose"))
    assert published[0]["content"] == row["content"]


@pytest.fixture
def runtime_config(monkeypatch):
    """Load actual pure vendored schema modules, avoiding config dotenv startup."""
    from types import SimpleNamespace
    directory = ROOT / "deer-flow/backend/packages/harness/deerflow/config"
    loaded = {}
    for name in ("tool_config", "subagents_config", "guardrails_config"):
        fullname = "deerflow.config." + name
        spec = importlib.util.spec_from_file_location(fullname, directory / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, fullname, module)
        spec.loader.exec_module(module)
        loaded[name] = module
    from pydantic import ConfigDict, create_model
    Tool = loaded["tool_config"].ToolConfig
    Subagents = loaded["subagents_config"].SubagentsAppConfig
    Guardrails = loaded["guardrails_config"].GuardrailsConfig
    App = create_model("RuntimeAppConfig", tools=(list[Tool], ...), subagents=(Subagents, ...),
                       guardrails=(Guardrails, ...), models=(list[dict], ...), __config__=ConfigDict(extra="allow"))
    def make(**kw):
        custom = {"description": "Existing researcher", "system_prompt": "Keep existing investigation rules.",
                  "tools": ["web_search", "web_fetch", "read_file"], "skills": ["deep-research"],
                  "model": "custom-provider", "timeout_seconds": 321, "max_turns": 17}
        custom.update(kw.pop("custom", {}))
        config = App(
            tools=[Tool(name="web_search", group="web", use="custom.search:tool", timeout=19)],
            subagents=Subagents(custom_agents={"scoped-researcher": custom}, **kw.pop("subagents", {})),
            guardrails=Guardrails(**kw.pop("guardrails", {})),
            models=[{"name": "private-model", "provider": "preserved", "temperature": 0.6}],
            **kw)
        return SimpleNamespace(_app_config=config, _agent=None), Tool
    return make


def _execute_native_client_construction(legacy, client):
    """Execute the real main() construction-to-ready block, without a model."""
    import ast
    from types import SimpleNamespace
    tree = ast.parse((BRIDGE / "deerflow_research.py").read_text())
    block = None
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        start = next((i for i, stmt in enumerate(body)
                      if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "client" for t in stmt.targets)
                      and isinstance(stmt.value, ast.Call) and getattr(stmt.value.func, "id", "") == "DeerFlowClient"), None)
        if start is None:
            continue
        end = next(i for i in range(start + 1, len(body)) if "client ready;" in ast.unparse(body[i]))
        block = body[start:end + 1]
        break
    assert block is not None
    namespace = dict(legacy.__dict__)
    namespace.update(DeerFlowClient=lambda **kwargs: client,
        args=SimpleNamespace(config=None, model="synthetic", subagents=True),
        plog=SimpleNamespace(write=lambda *a: None), meta={}, write_meta=lambda: None)
    exec(compile(ast.Module(body=block, type_ignores=[]), "<native-client-construction>", "exec"), namespace)
    return namespace


def test_runtime_registration_reaches_old_config_before_first_agent(legacy, runtime_config, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setenv("DATA_SOURCES_ENABLED", "true")
    client, _ = runtime_config()
    monkeypatch.setattr(legacy, "_data_tools_module", lambda: SimpleNamespace(
        data_search_tool=SimpleNamespace(name="data_search"), data_get_tool=SimpleNamespace(name="data_get")))
    before_models = client._app_config.models.copy()
    _execute_native_client_construction(legacy, client)
    configs = {t.name: t for t in client._app_config.tools}
    assert {"data_search", "data_get"} <= set(configs)
    assert configs["data_get"].use == "data_tools:data_get_tool"
    scoped = client._app_config.subagents.custom_agents["scoped-researcher"]
    assert {"data_search", "data_get"} <= set(scoped.tools)
    assert "data-sources" in scoped.skills and "OFFICIAL DATA" in scoped.system_prompt
    assert scoped.model == "custom-provider" and scoped.timeout_seconds == 321 and scoped.max_turns == 17
    assert client._app_config.models == before_models
    assert configs["web_search"].model_extra["timeout"] == 19
    assert client._agent is None


@pytest.fixture
def runtime_tools(legacy, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setenv("DATA_SOURCES_ENABLED", "true")
    monkeypatch.setattr(legacy, "_data_tools_module", lambda: SimpleNamespace(
        data_search_tool=SimpleNamespace(name="data_search"), data_get_tool=SimpleNamespace(name="data_get")))


def _runtime_snapshot(client):
    import copy
    app = client._app_config
    return {"tools": [t.model_dump() for t in app.tools],
            "subagents": app.subagents.model_dump(), "guardrails": app.guardrails.model_dump(),
            "models": copy.deepcopy(app.models)}


def test_runtime_registration_disabled_is_noop(legacy, runtime_config, monkeypatch):
    client, _ = runtime_config()
    before = _runtime_snapshot(client)
    monkeypatch.setenv("DATA_SOURCES_ENABLED", "false")
    monkeypatch.setattr(legacy, "_data_tools_module", lambda: pytest.fail("disabled must not import tools"))
    result = legacy._register_legacy_data_tools(client)
    assert result["status"] == "disabled" and result["code"] == "feature_disabled"
    assert _runtime_snapshot(client) == before and client._agent is None
    assert legacy._official_data_prompt_block() == ""


def test_runtime_registration_idempotent_and_preserves_custom_settings(legacy, runtime_config, runtime_tools, tmp_path):
    client, Tool = runtime_config()
    app = client._app_config
    original_tool = Tool(name="data_get", group="custom-data", use="data_tools:data_get_tool", timeout=7, custom_option="preserve")
    app.tools.append(original_tool)
    existing_prompt = app.subagents.custom_agents["scoped-researcher"].system_prompt
    # A synthetic deployed config receipt is deliberately not passed to the
    # helper: all mutation must concern the already-loaded schema object only.
    path = tmp_path / "config.yaml"
    path.write_text("models:\n  - name: private-provider\n")
    file_before = path.read_bytes()
    first = legacy._register_legacy_data_tools(client)
    state = _runtime_snapshot(client)
    second = legacy._register_legacy_data_tools(client)
    assert first["status"] == second["status"] == "ready"
    assert first["added_tools"] == ["data_search"] and second["added_tools"] == []
    assert _runtime_snapshot(client) == state
    assert next(t for t in app.tools if t.name == "data_get") is original_tool
    assert original_tool.group == "custom-data" and original_tool.model_extra == {"timeout": 7, "custom_option": "preserve"}
    scoped = app.subagents.custom_agents["scoped-researcher"]
    assert scoped.system_prompt.startswith(existing_prompt)
    assert scoped.system_prompt.count("OFFICIAL DATA TOOLS (runtime):") == 1
    assert path.read_bytes() == file_before


@pytest.mark.parametrize("conflict", ["custom", "duplicate", "disabled"])
def test_runtime_registration_respects_existing_tool_conflicts(legacy, runtime_config, runtime_tools, conflict):
    client, Tool = runtime_config()
    app = client._app_config
    if conflict == "custom":
        app.tools.append(Tool(name="data_get", group="private", use="private.plugin:custom", endpoint="retain"))
    elif conflict == "duplicate":
        app.tools.extend([Tool(name="data_get", group="web", use="data_tools:data_get_tool") for _ in range(2)])
    else:
        app.tools.append(Tool(name="data_get", group="web", use="data_tools:data_get_tool", enabled=False))
    before = _runtime_snapshot(client)
    result = legacy._register_legacy_data_tools(client)
    assert result["status"] == "unavailable"
    assert result["code"] == ("tool_explicitly_disabled" if conflict == "disabled" else "tool_name_conflict")
    if conflict == "disabled":
        before["tools"] = [row for row in before["tools"] if row["name"] != "data_get"]
    assert _runtime_snapshot(client) == before
    assert legacy._official_data_prompt_block() == ""


@pytest.mark.parametrize("policy", [{"denied_tools": ["data_get"]}, {"allowed_tools": ["web_search"]}])
def test_runtime_registration_respects_guardrail_denial(legacy, runtime_config, runtime_tools, policy):
    client, _ = runtime_config(guardrails={"enabled": True, "provider": {
        "use": "deerflow.guardrails.builtin:AllowlistProvider", "config": policy}})
    before = _runtime_snapshot(client)
    result = legacy._register_legacy_data_tools(client)
    assert result["status"] == "unavailable" and result["code"] == "guardrail_tool_denial"
    assert _runtime_snapshot(client) == before


def test_runtime_registration_does_not_infer_custom_guardrail_permission(legacy, runtime_config, runtime_tools):
    client, _ = runtime_config(guardrails={"enabled": True, "provider": {
        "use": "private.guardrail:Provider", "config": {"custom_policy": "preserve"}}})
    before = _runtime_snapshot(client)
    result = legacy._register_legacy_data_tools(client)
    assert result["code"] == "guardrail_policy_unavailable"
    assert _runtime_snapshot(client) == before


def test_runtime_registration_scoped_denial_keeps_effective_filter(legacy, runtime_config, runtime_tools):
    import ast
    from types import SimpleNamespace
    client, _ = runtime_config(custom={"disallowed_tools": ["data_get", "task"]})
    result = legacy._register_legacy_data_tools(client)
    scoped = client._app_config.subagents.custom_agents["scoped-researcher"]
    assert result["status"] == "partial" and result["scoped"]["denied_tools"] == ["data_get"]
    assert "data_get" not in scoped.tools and "data_search" in scoped.tools
    assert scoped.disallowed_tools == ["data_get", "task"]
    # Exercise the actual vendored executor's pure filter with those schemas.
    tree = ast.parse((ROOT / "deer-flow/backend/packages/harness/deerflow/subagents/executor.py").read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_filter_tools")
    scope = {"BaseTool": object}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<native-tool-filter>", "exec"), scope)
    filtered = scope["_filter_tools"]([SimpleNamespace(name=t.name) for t in client._app_config.tools], scoped.tools, scoped.disallowed_tools)
    assert "data_search" in {t.name for t in filtered} and "data_get" not in {t.name for t in filtered}


@pytest.mark.parametrize("custom,code", [({"tools": []}, "scoped_tool_denial"), ({"skills": []}, "scoped_skills_disabled")])
def test_runtime_registration_preserves_explicit_empty_permissions(legacy, runtime_config, runtime_tools, custom, code):
    client, _ = runtime_config(custom=custom)
    result = legacy._register_legacy_data_tools(client)
    scoped = client._app_config.subagents.custom_agents["scoped-researcher"]
    assert result["status"] == "partial" and result["code"] == code
    for field in custom:
        assert getattr(scoped, field) == []
    if custom.get("tools") == []:
        assert scoped.system_prompt == "Keep existing investigation rules."
        assert scoped.skills == ["deep-research"]


def test_runtime_registration_preserves_inheritance_and_effective_override(legacy, runtime_config, runtime_tools):
    client, _ = runtime_config(custom={"tools": None, "skills": None})
    assert legacy._register_legacy_data_tools(client)["status"] == "ready"
    scoped = client._app_config.subagents.custom_agents["scoped-researcher"]
    assert scoped.tools is None and scoped.skills is None
    client2, _ = runtime_config(subagents={"agents": {"scoped-researcher": {"skills": ["custom-skill"], "model": "override-model"}}})
    assert legacy._register_legacy_data_tools(client2)["status"] == "ready"
    override = client2._app_config.subagents.agents["scoped-researcher"]
    assert override.skills == ["custom-skill", "data-sources"] and override.model == "override-model"
    assert client2._app_config.subagents.custom_agents["scoped-researcher"].skills == ["deep-research"]
    client3, _ = runtime_config(subagents={"agents": {"scoped-researcher": {"skills": []}}})
    assert legacy._register_legacy_data_tools(client3)["code"] == "scoped_skills_disabled"
    assert client3._app_config.subagents.agents["scoped-researcher"].skills == []


def test_runtime_registration_rejects_live_agent_and_missing_implementation(legacy, runtime_config, runtime_tools, monkeypatch):
    from types import SimpleNamespace
    client, _ = runtime_config()
    client._agent = object()
    before = _runtime_snapshot(client)
    assert legacy._register_legacy_data_tools(client)["code"] == "agent_already_created"
    assert _runtime_snapshot(client) == before
    client._agent = None
    monkeypatch.setattr(legacy, "_data_tools_module", lambda: SimpleNamespace(data_get_tool=None, data_search_tool=None))
    assert legacy._register_legacy_data_tools(client)["code"] == "tool_implementation_unavailable"
    assert _runtime_snapshot(client) == before


def _native_loaded_tool_names(config):
    """Use the vendored loader with inert reflection; no tools/models invoked."""
    import ast
    from types import SimpleNamespace
    tree = ast.parse((ROOT / "deer-flow/backend/packages/harness/deerflow/tools/tools.py").read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "get_available_tools")
    config.get_model_config = lambda name: None
    by_use = {row.use: row.name for row in config.tools}
    scope = {"AppConfig": object, "BaseTool": object, "get_app_config": lambda: config,
             "is_host_bash_allowed": lambda app: True,
             "resolve_variable": lambda use, expected: SimpleNamespace(name=by_use[use]),
             "_ensure_sync_invocable_tool": lambda tool: tool,
             "BUILTIN_TOOLS": [], "SUBAGENT_TOOLS": [],
             "logger": SimpleNamespace(info=lambda *a: None, warning=lambda *a: None, error=lambda *a: None)}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<native-tool-loader>", "exec"), scope)
    return {t.name for t in scope["get_available_tools"](app_config=config, model_name="synthetic", include_mcp=False)}


def test_runtime_registration_disabled_definition_is_absent_from_native_tools(legacy, runtime_config, runtime_tools):
    client, Tool = runtime_config()
    disabled = Tool(name="data_get", group="web", use="data_tools:data_get_tool", enabled=False, timeout=9)
    client._app_config.tools.append(disabled)
    assert "data_get" in _native_loaded_tool_names(client._app_config), "positive control for native enabled-extra behavior"
    result = legacy._register_legacy_data_tools(client)
    assert result["code"] == "tool_explicitly_disabled"
    assert "data_get" not in _native_loaded_tool_names(client._app_config)
    assert "web_search" in _native_loaded_tool_names(client._app_config)
    # Repeated registration, including another client sharing the native
    # cached AppConfig, must never turn the removed denial into a missing tool.
    assert legacy._register_legacy_data_tools(client)["code"] == "tool_explicitly_disabled"
    from types import SimpleNamespace
    second = SimpleNamespace(_app_config=client._app_config, _agent=None)
    assert legacy._register_legacy_data_tools(second)["code"] == "tool_explicitly_disabled"
    assert "data_get" not in _native_loaded_tool_names(second._app_config)
    assert disabled.model_extra == {"enabled": False, "timeout": 9}


@pytest.mark.parametrize("custom_name,disabled_name", [("data_search", "data_get"), ("data_get", "data_search")])
def test_runtime_conflict_does_not_bypass_other_disabled_definition(legacy, runtime_config, runtime_tools, custom_name, disabled_name):
    client, Tool = runtime_config()
    custom = Tool(name=custom_name, group="private", use="private.plugin:custom", custom_setting="preserve")
    disabled = Tool(name=disabled_name, group="web", use=f"data_tools:{disabled_name}_tool", enabled=False)
    client._app_config.tools.extend([custom, disabled])
    result = legacy._register_legacy_data_tools(client)
    assert result["code"] == "tool_name_conflict"
    loaded = _native_loaded_tool_names(client._app_config)
    assert custom_name in loaded and disabled_name not in loaded
    assert custom in client._app_config.tools and custom.model_extra == {"custom_setting": "preserve"}
    assert legacy._register_legacy_data_tools(client)["code"] == "tool_name_conflict"
    assert disabled_name not in _native_loaded_tool_names(client._app_config)
