"""Official data crosses the existing pipeline-to-consumer boundaries offline."""
import ast
import json
from pathlib import Path
import re
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

    def load(path, *, max_series=None):
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
    # G4: the carrier cap is the Config knob (default 24), not a hard-coded 12.
    assert calls == [(str(handoff), 24)]
    monkeypatch.setattr(pipeline.Config, "DATA_SOURCES_MAX_SERIES", 5)
    pipeline.load_research_dossier_for_simulation("sim_local")
    assert calls[-1] == (str(handoff), 5)


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
        get_run_state=lambda *a: types.SimpleNamespace(current_round=1, runner_status=pipeline.RunnerStatus.COMPLETED),
        # the orchestrator cross-checks the pipeline's engine pin against saved simulation state
        RUN_STATE_DIR=str(tmp_path / "simulations"), simulation_engine=lambda sid: "oasis-legacy"))
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
def test_invalid_binding_keeps_only_verifiable_core(tmp_path, monkeypatch, mutation):
    """Optional data may degrade; changed core or invalid proof cannot adopt replacements."""
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
    assert official_data.simulation_research_binding("sim_bound") == {"status": "invalid"}
    monkeypatch.setattr(pipeline.PipelineManager, "list_pipelines", lambda: [{"pipeline_id": "pipe_bound"}])
    monkeypatch.setattr(pipeline.PipelineManager, "load", lambda _: {
        "simulation_id": "sim_bound", "handoff_dir": str(handoff)})
    binding_bytes = path.read_bytes()
    if mutation != "new_manifest":
        with pytest.raises(ValueError, match="Consumed research generation core"):
            pipeline.load_research_dossier_for_simulation("sim_bound")
    else:
        result = pipeline.load_research_dossier_for_simulation("sim_bound")
        assert result["official_data"] is None
        assert result["research_report"] == "Generation one"
        assert result["report_artifacts"] == {}
    assert path.read_bytes() == binding_bytes
    assert list(directory.glob(".research-binding-*")) == []


def _pipeline_generation(root, pid="pipe_moved"):
    """A real persisted generation inside a pipelines root (fred:UNRATE capture)."""
    from official_data_replay import publish, replay
    handoff = root / "pipelines" / pid / "handoff"
    publish([replay("fred_unrate_2024", root)], handoff)
    (handoff / "research_report.md").write_text("Cited research [S1]")
    (handoff / "actors.json").write_text(json.dumps({"actors": []}))
    return handoff


def test_binding_survives_relocation_of_the_install(tmp_path, monkeypatch):
    """D3: the binding pins the handoff relative to the pipelines root, so moving the
    install keeps the dossier and the official data of every bound simulation."""
    from app.services import official_data
    from app.services.simulation_manager import SimulationManager
    before, after = tmp_path / "before", tmp_path / "after"
    handoff = _pipeline_generation(before)
    (before / "simulations" / "sim_moved").mkdir(parents=True)
    monkeypatch.setattr(pipeline.Config, "PIPELINE_DATA_DIR", str(before / "pipelines"))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(before / "simulations"))
    binding = official_data.bind_simulation_research("sim_moved", handoff, pipeline_id="pipe_moved")
    assert binding["schema_version"] == 2 and binding["handoff_dir"] == "pipe_moved/handoff"
    expected = official_data.load_official_data(handoff)
    assert expected["series"][0]["series"] == "fred:UNRATE"

    before.rename(after)
    monkeypatch.setattr(pipeline.Config, "PIPELINE_DATA_DIR", str(after / "pipelines"))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(after / "simulations"))
    monkeypatch.setattr(pipeline.PipelineManager, "list_pipelines", lambda: pytest.fail("valid binding fell back"))
    dossier = pipeline.load_research_dossier_for_simulation("sim_moved")
    assert dossier["research_report"] == "Cited research [S1]"
    assert dossier["official_data"] == expected
    assert official_data.simulation_research_binding("sim_moved")["handoff_dir"] == str(
        (after / "pipelines" / "pipe_moved" / "handoff").resolve())


def test_schema_one_binding_stays_valid_and_rebinds_after_relocation(tmp_path, monkeypatch):
    """A schema-1 (absolute) proof keeps working: a moved pipeline is found through its
    own handoff, and re-binding the same generation is not a conflict."""
    from app.services import official_data
    from app.services.simulation_manager import SimulationManager
    before, after = tmp_path / "before", tmp_path / "after"
    handoff = _pipeline_generation(before)
    directory = before / "simulations" / "sim_old_schema"
    directory.mkdir(parents=True)
    monkeypatch.setattr(pipeline.Config, "PIPELINE_DATA_DIR", str(before / "pipelines"))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(before / "simulations"))
    generation = official_data.capture_research_generation(handoff)
    (directory / "official_research_binding.json").write_text(json.dumps({
        "schema_version": 1, "simulation_id": "sim_old_schema", "pipeline_id": "pipe_moved", **generation}))
    assert official_data.simulation_research_binding("sim_old_schema")["status"] == "valid"
    official_data.bind_simulation_research("sim_old_schema", handoff, pipeline_id="pipe_moved")

    before.rename(after)
    monkeypatch.setattr(pipeline.Config, "PIPELINE_DATA_DIR", str(after / "pipelines"))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(after / "simulations"))
    binding = official_data.simulation_research_binding("sim_old_schema")
    assert binding["status"] == "valid"
    assert binding["handoff_dir"] == str((after / "pipelines" / "pipe_moved" / "handoff").resolve())
    with pytest.raises(official_data.ResearchBindingConflict):
        official_data.bind_simulation_research(
            "sim_old_schema", _pipeline_generation(tmp_path / "other", "pipe_moved"), pipeline_id="pipe_moved")


@pytest.mark.parametrize("case", ["bound", "ambiguous", "research_running", "other_project"])
def test_manual_simulation_binds_to_its_projects_completed_research(tmp_path, monkeypatch, case):
    """G6: a simulation created through the API for a pipeline's project gets the same
    research generation (dossier + official data) as the pipeline's own simulation."""
    from app.services import official_data
    from app.services.simulation_manager import SimulationManager
    root = tmp_path / "pipelines"
    monkeypatch.setattr(pipeline.Config, "PIPELINE_DATA_DIR", str(root))
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path / "simulations"))
    (tmp_path / "simulations" / "sim_manual").mkdir(parents=True)
    states = {}
    for pid in ("pipe_a", "pipe_b") if case == "ambiguous" else ("pipe_a",):
        _pipeline_generation(tmp_path, pid)
        states[pid] = {"pipeline_id": pid, "project_id": "proj_other" if case == "other_project" else "proj_1",
                       "simulation_id": f"sim_{pid}", "handoff_dir": str(root / pid / "handoff"),
                       "stages": {"research": {"status": "running" if case == "research_running" else "completed"}}}
    monkeypatch.setattr(pipeline.PipelineManager, "list_pipelines",
                        lambda: [{"pipeline_id": pid} for pid in states])
    monkeypatch.setattr(pipeline.PipelineManager, "load", lambda pid: states.get(pid))

    result = official_data.bind_project_simulation("sim_manual", "proj_1")
    dossier = pipeline.load_research_dossier_for_simulation("sim_manual")
    if case == "bound":
        assert result == {"status": "bound", "pipeline_id": "pipe_a"}
        assert dossier["research_report"] == "Cited research [S1]"
        assert dossier["official_data"]["series"][0]["series"] == "fred:UNRATE"
    else:
        assert result["status"] == "unbound"
        assert official_data.simulation_research_binding("sim_manual") == {"status": "missing"}
        assert dossier["official_data"] is None


def test_manual_create_endpoint_binds_pipeline_projects(tmp_path, monkeypatch):
    from flask import Flask
    from app.api import simulation_bp
    import app.api.simulation as api
    from app.services import official_data
    bound = []
    monkeypatch.setattr(api.ProjectManager, "get_project",
                        staticmethod(lambda pid: types.SimpleNamespace(graph_id="graph_1")))
    monkeypatch.setattr(api.SimulationManager, "create_simulation",
                        lambda self, **kw: types.SimpleNamespace(simulation_id="sim_api", to_dict=lambda: {"simulation_id": "sim_api"}))
    monkeypatch.setattr(official_data, "bind_project_simulation",
                        lambda sid, pid: bound.append((sid, pid)) or {"status": "bound", "pipeline_id": "pipe_a"})
    app = Flask(__name__)
    app.register_blueprint(simulation_bp, url_prefix="/api/simulation")
    response = app.test_client().post("/api/simulation/create", json={"project_id": "proj_1"})
    assert response.status_code == 200 and response.get_json()["data"] == {"simulation_id": "sim_api"}
    assert bound == [("sim_api", "proj_1")]


# Every environment knob the official-data bridge reads must be discoverable in
# .env.example. check_env_drift.py only audits Config; these knobs reach the
# research subprocess and the data servers through os.environ instead.
REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO_ROOT / ".env.example"
_DATA_KNOB_MODULES = (
    "deerflow_bridge/data_mcp.py",
    "deerflow_bridge/data_sources.py",
    "deerflow_bridge/data_tools.py",
    "deerflow_bridge/research_gateway.py",
    "deerflow_bridge/skills/data-visuals/scripts/render_data.py",
)
_ENV_READ = re.compile(
    r"""(?:(?:source|env|environ)\.get\(|_source_path\(source,\s*|_limit\()\s*["']([A-Z][A-Z0-9_]+)["']""")
# Process plumbing, not tuning knobs: the hub passes HOME/PATH to its children
# and the orchestrator sets the run artifact directory for each research run.
# DRF_BACKTEST_POLICY is an orchestrator-owned per-run identity, documented as
# non-user configuration in .env.example; it must not be set as a tuning knob.
_NOT_KNOBS = {"HOME", "PATH", "DEERFLOW_RUN_ARTIFACT_DIR", "DRF_BACKTEST_POLICY"}


def _official_data_env_knobs():
    names = set()
    for relative in _DATA_KNOB_MODULES:
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        names.update(_ENV_READ.findall(text))
        if relative.endswith("data_mcp.py"):
            # Per-server allowlists forwarded to the children when set.
            for node in ast.parse(text).body:
                if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                        and node.target.id.endswith("_ENV_KEYS") and node.target.id != "_BASE_ENV_KEYS"):
                    names.update(elt.value for elt in node.value.elts)
    return names - _NOT_KNOBS


def test_every_official_data_env_knob_is_documented_in_env_example():
    # The internal cutoff identity is documented as process plumbing, not an
    # editable environment default. Its exclusion cannot hide missing guidance.
    assert "DRF_BACKTEST_POLICY" in ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "切勿写进 .env" in ENV_EXAMPLE.read_text(encoding="utf-8")
    knobs = _official_data_env_knobs()
    documented = set(re.findall(r"^\s*#?\s*([A-Z][A-Z0-9_]+)=", ENV_EXAMPLE.read_text(encoding="utf-8"), re.M))

    # The scan must see the knobs it is meant to guard, or it proves nothing.
    assert {"DATA_SOURCES_FRED_PER_MINUTE", "DATA_SOURCES_CALL_TIMEOUT", "DATA_SOURCES_MAX_SERIES",
            "LEGACY_DATA_GETS_PER_THREAD", "FRED_API_KEY", "FRED_API_TIMEOUT_MS", "BLS_API_KEY",
            "EIA_API_KEY", "IMF_APP_NAME", "DATA360_API_BASE_URL"} <= knobs
    assert sorted(knobs - documented) == []


def _env_entry(name):
    """The commented .env.example entry for ``name``: its line plus continuation lines."""
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(rf"#\s*{name}=", line))
    entry = [lines[start]]
    for line in lines[start + 1:]:
        if not re.match(r"#\s{20,}\S", line):
            break
        entry.append(line)
    return "\n".join(entry)


def test_legacy_thread_budgets_and_fred_pacing_are_documented_as_they_behave(monkeypatch):
    """.env.example states the real defaults, ranges and buckets: a legacy budget belongs to
    one research thread, and that thread's delegated task sub-agents draw from one separate
    bucket per sub-agent type (never the lead's); FRED pacing counts MCP tool calls per hub."""
    bridge = str(REPO_ROOT / "deerflow_bridge")
    monkeypatch.syspath_prepend(bridge)
    import data_mcp
    import data_tools

    gets, searches = _env_entry("LEGACY_DATA_GETS_PER_THREAD"), _env_entry("LEGACY_DATA_SEARCHES_PER_THREAD")
    assert gets.startswith("# LEGACY_DATA_GETS_PER_THREAD=8 ") and "0~40" in gets
    assert searches.startswith("# LEGACY_DATA_SEARCHES_PER_THREAD=6 ") and "0~40" in searches
    assert "共享父线程额度" not in gets + searches
    assert "另一份同额度桶" in gets and "子代理另有一桶" in searches
    for name, default in (("LEGACY_DATA_GETS_PER_THREAD", 8), ("LEGACY_DATA_SEARCHES_PER_THREAD", 6)):
        for raw, expected in (("", default), ("x", default), ("-3", 0), ("99", 40), ("12", 12)):
            monkeypatch.setenv(name, raw)
            assert data_tools._limit(name, default, 40) == expected
    lead = data_tools._agent_key({"configurable": {"thread_id": "t1"}})
    worker = data_tools._agent_key({"configurable": {"thread_id": "t1"}, "tags": ["subagent:scoped-researcher"]})
    assert (lead, worker) == ("t1", "t1/subagent:scoped-researcher")
    assert data_tools._agent_key({"configurable": {"thread_id": "t2"}}) != lead

    fred = _env_entry("DATA_SOURCES_FRED_PER_MINUTE")
    assert fred.startswith("# DATA_SOURCES_FRED_PER_MINUTE=50 ") and "1~120" in fred and "rate_limited" in fred
    assert data_mcp.FRED_CALLS_PER_MINUTE == 50
    for raw, expected in (("", 50), ("0", 50), ("121", 50), ("abc", 50), ("1", 1), ("120", 120)):
        assert data_mcp._fred_calls_per_minute({"DATA_SOURCES_FRED_PER_MINUTE": raw}) == expected
