"""Official data crosses the existing pipeline-to-consumer boundaries offline."""
import json
import sys
import types
import pytest

from app.services import pipeline_orchestrator as pipeline


def test_manual_dossier_carries_the_same_stored_official_snapshot(tmp_path, monkeypatch):
    from app.services import official_data
    from app.services.simulation_manager import SimulationManager
    handoff = tmp_path / "handoff"
    handoff.mkdir()
    (handoff / "research_report.md").write_text("# Research\n\nA cited quantitative baseline.")
    (handoff / "actors.json").write_text(json.dumps({"actors": []}))
    snapshot = {"schema_version": 1, "series": [{"series": "fred:UNRATE", "units": "Percent"}]}
    calls = []
    module = types.ModuleType("deerflow_bridge.data_sources")

    def load(path, *, max_series=12):
        calls.append((str(path), max_series))
        return snapshot

    module.load_official_data = load
    monkeypatch.setitem(sys.modules, "deerflow_bridge.data_sources", module)
    monkeypatch.setattr(pipeline.PipelineManager, "list_pipelines", lambda: [{"pipeline_id": "pipe_local"}])
    monkeypatch.setattr(pipeline.PipelineManager, "load", lambda _: {
        "simulation_id": "sim_local", "handoff_dir": str(handoff),
    })
    simulations = tmp_path / "simulations"
    (simulations / "sim_local").mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(simulations))
    official_data.bind_simulation_research("sim_local", handoff, pipeline_id="pipe_local")

    dossier = pipeline.load_research_dossier_for_simulation("sim_local")

    assert dossier.get("official_data") == snapshot
    assert calls == [(str(handoff), 12)]


def test_outer_source_merge_keeps_distinct_dataset_generations_and_provenance():
    first = {
        "url": "https://fred.stlouisfed.org/series/UNRATE?drf_series=fred%3AUNRATE&drf_snapshot=aaa",
        "tier": "S1", "source_origin": "official_data", "content": "exact data page",
        "content_sha256": "a" * 64, "content_chars": 15,
        "provisional_source_number": 1000042,
        "dataset": {"series": "fred:UNRATE", "snapshot": {"observations": [{"date": "2026-01-01", "value": 4.2}]}},
    }
    second = {**first, "url": first["url"].replace("aaa", "bbb"), "content_sha256": "b" * 64}
    merged = pipeline.merge_sources_union([[first], [first, second]])
    assert merged == [first, second]
    assert merged[0]["dataset"]["snapshot"]["observations"][0]["value"] == 4.2


@pytest.mark.parametrize("corrupt", [False, True])
@pytest.mark.parametrize("replace_before_seed", [False, True])
def test_seed_report_receives_only_valid_persisted_official_generation(
    tmp_path, monkeypatch, corrupt, replace_before_seed,
):
    from app.services import official_data
    from app.services.simulation_manager import SimulationManager
    api = official_data.data_api()
    handoff = tmp_path / "handoff"
    series = api.Series(series="fred:UNRATE", units="Percent", frequency="M",
                        retrieved_at="2026-03-01T00:00:00Z",
                        source_url="https://fred.stlouisfed.org/series/UNRATE",
                        observations=[api.Observation("2026-01-01", 4.2)])
    manifest = api.write_dataset_files([series], handoff, citations={series.series: "S1"})
    expected = official_data.load_official_data(handoff)
    if corrupt:
        (handoff / manifest["series"][0]["file"]).write_text("{}")
        expected = None

    sim_root = tmp_path / "simulations"
    (sim_root / "sim_seed").mkdir(parents=True)
    (sim_root / "sim_primary").mkdir()
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sim_root))
    (handoff / "research_report.md").write_text("Cited research")
    (handoff / "actors.json").write_text("{}")
    (handoff / "sources.json").write_text(json.dumps([{"url": series.source_url}]))
    official_data.bind_simulation_research("sim_primary", handoff, pipeline_id="pipe_seed")
    if replace_before_seed:
        series.observations[0].value = 8.8
        api.write_dataset_files([series], handoff, citations={series.series: "S1"})
    monkeypatch.setattr(pipeline.PipelineManager, "list_pipelines", lambda: [{"pipeline_id": "pipe_seed"}])
    monkeypatch.setattr(pipeline.PipelineManager, "load", lambda _: {
        "simulation_id": "sim_primary", "handoff_dir": str(handoff),
    })
    preparation_carriers = []

    # Only the unrelated simulation/model execution is replaced. The seed
    # orchestration method, dataset loader and content validation remain real.
    monkeypatch.setattr(pipeline, "SimulationManager", lambda: types.SimpleNamespace(
        create_simulation=lambda *a, **kw: types.SimpleNamespace(simulation_id="sim_seed"),
        prepare_simulation=lambda **kw: preparation_carriers.append(
            official_data.load_for_simulation(kw["simulation_id"]))))
    monkeypatch.setattr(pipeline, "SimulationRunner", types.SimpleNamespace(
        start_simulation=lambda **kw: None, write_run_summary=lambda *a: None,
        get_run_state=lambda *a: types.SimpleNamespace(current_round=1, runner_status=pipeline.RunnerStatus.COMPLETED)))
    captured = []

    def report(**kwargs):
        captured.append(kwargs)
        return types.SimpleNamespace(generate_report=lambda **kw: None)

    monkeypatch.setattr(pipeline, "ReportAgent", report)
    orchestrator = object.__new__(pipeline.PipelineOrchestrator)
    monkeypatch.setattr(orchestrator, "_pinned_safety", lambda *a: False)
    monkeypatch.setattr(orchestrator, "_read_report_forecast", lambda rid: {"headline": "synthetic"})
    state = types.SimpleNamespace(pipeline_id="pipe_seed", simulation_id="sim_primary",
                                  handoff_dir=str(handoff), prompt="Question", options={})
    if replace_before_seed:
        with pytest.raises(ValueError, match="generation"):
            orchestrator._run_one_seed(
                state, types.SimpleNamespace(project_id="project_seed"), "graph_seed", {},
                {"sources": [{"url": series.source_url}]}, "Cited research", seed=2, max_rounds=1)
        assert preparation_carriers == captured == []
        assert state.simulation_id == "sim_primary"
        return
    result = orchestrator._run_one_seed(
        state, types.SimpleNamespace(project_id="project_seed"), "graph_seed", {},
        {"sources": [{"url": series.source_url}]}, "Cited research", seed=2, max_rounds=1,
        scenario_spine=[{"name": "Baseline"}])
    assert result[0] == "sim_seed"
    assert len(captured) == 1
    assert captured[0]["official_data"] == expected
    assert captured[0]["scenario_spine"] == [{"name": "Baseline"}]
    assert preparation_carriers == [expected]
    # The durable seed association also serves manual report/chat after reload.
    assert pipeline.load_research_dossier_for_simulation("sim_seed")["official_data"] == expected
    assert pipeline.PipelineManager.load("pipe_seed")["simulation_id"] == "sim_primary"
    if not corrupt:
        # A different, internally valid generation must not replace the one
        # consumed during PREPARE, even though its own dataset hashes validate.
        series.observations[0].value = 8.8
        api.write_dataset_files([series], handoff, citations={series.series: "S1"})
        assert official_data.load_official_data(handoff)["series"][0]["observations"][0]["value"] == 8.8
        assert pipeline.load_research_dossier_for_simulation("sim_seed")["official_data"] is None
        with pytest.raises(ValueError, match="already bound"):
            official_data.bind_simulation_research("sim_seed", handoff, pipeline_id="pipe_seed")


def test_unbound_legacy_simulation_does_not_adopt_current_official_generation(tmp_path, monkeypatch):
    from app.services import official_data
    api = official_data.data_api()
    handoff = tmp_path / "handoff"
    series = api.Series(series="fred:UNRATE", units="Percent", frequency="M",
                        source_url="https://fred.stlouisfed.org/series/UNRATE",
                        observations=[api.Observation("2026-01-01", 4.2)])
    api.write_dataset_files([series], handoff)
    (handoff / "research_report.md").write_text("Legacy dossier remains available")
    monkeypatch.setattr(pipeline.PipelineManager, "list_pipelines", lambda: [{"pipeline_id": "pipe_unbound"}])
    monkeypatch.setattr(pipeline.PipelineManager, "load", lambda _: {
        "simulation_id": "sim_unbound", "handoff_dir": str(handoff),
    })
    result = pipeline.load_research_dossier_for_simulation("sim_unbound")
    assert result["official_data"] is None
    assert result["research_report"] == "Legacy dossier remains available"


@pytest.mark.parametrize("mutation", ["identity", "extra_status", "symlink", "new_report", "new_manifest"])
def test_generation_binding_rejects_changes_without_mutable_lookup_fallback(tmp_path, monkeypatch, mutation):
    from app.services import official_data
    from app.services.simulation_manager import SimulationManager
    handoff = tmp_path / "handoff"
    handoff.mkdir()
    (handoff / "research_report.md").write_text("Generation one")
    simulations = tmp_path / "simulations"
    directory = simulations / "sim_bound"
    directory.mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(simulations))
    original = official_data.bind_simulation_research("sim_bound", handoff, pipeline_id="pipe_bound")
    assert official_data.bind_simulation_research("sim_bound", handoff, pipeline_id="pipe_bound") == original
    path = directory / "official_research_binding.json"
    if mutation == "identity":
        original["simulation_id"] = "sim_other"
        path.write_text(json.dumps(original))
    elif mutation == "extra_status":
        original["status"] = "missing"
        path.write_text(json.dumps(original))
    elif mutation == "symlink":
        sibling = directory / "other.json"
        sibling.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(sibling)
    elif mutation == "new_report":
        (handoff / "research_report.md").write_text("Generation two")
    else:
        (handoff / "data").mkdir()
        (handoff / "data/datasets.json").write_text('{"schema_version":1,"series":[]}')
    monkeypatch.setattr(pipeline.PipelineManager, "list_pipelines", lambda: pytest.fail("invalid binding fell back"))
    result = pipeline.load_research_dossier_for_simulation("sim_bound")
    assert result["official_data"] is None and result["research_report"] is None
    assert list(directory.glob(".research-binding-*")) == []
