"""Real parent promotion, reuse and consumed-generation proof for contextual sources."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from app.services import official_data, pipeline_orchestrator as po
from app.services.simulation_manager import SimulationManager


def _record_exact_sources():
    guard = sys.modules.get("main_offline_guard")
    if guard is None:
        return
    root = Path(__file__).resolve().parents[2]
    for relative in (
        "backend/app/services/pipeline_orchestrator.py", "backend/app/services/official_data.py",
        "backend/app/services/news_market_context.py", "backend/app/services/report_agent.py",
        "backend/app/api/research.py", "backend/app/api/report.py", "deerflow_bridge/news_signals.py",
    ):
        path = root / relative
        guard.source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()


_record_exact_sources()


def _capture(root, *, generation="capture-one", as_of="2026-10-18", question_digest=None):
    root.mkdir(parents=True, exist_ok=True)
    envelope = {"schema_version": 1, "generation_id": generation,
                "question_sha256": question_digest or hashlib.sha256(b"fixture question").hexdigest(),
                "language": "en", "as_of": as_of, "created_at": "2026-10-18T00:00:00Z",
                "sealed": True, "providers": {}, "queries": [], "items": []}
    envelope["sha256"] = hashlib.sha256(json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode()).hexdigest()
    (root / "news_market_context.json").write_text(json.dumps(envelope))
    return envelope


def _research(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "research_report.md").write_text("# Research\n" + "bounded original evidence " * 40)
    (root / "actors.json").write_text(json.dumps({"actors": []}))
    (root / "sources.json").write_text("[]")


def test_parent_promotes_and_fingerprints_exact_capture(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    _research(source)
    _capture(source)
    raw = (source / "news_market_context.json").read_bytes()
    seal = po._promote_research_contract(str(source), str(target))
    assert "news_market_context.json" in seal["files"]
    assert (target / "news_market_context.json").read_bytes() == raw
    assert seal["files"]["news_market_context.json"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert po._validate_research_contract(str(target))
    (target / "news_market_context.json").write_text("{}")
    assert not po._validate_research_contract(str(target))


def test_parent_rejects_invalid_capture_without_replacing_old_generation(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    _research(source)
    _capture(source)
    _research(target)
    po._promote_research_contract(str(target), str(target))
    before = {p.name: p.read_bytes() for p in target.iterdir() if p.is_file()}
    (source / "news_market_context.json").write_text("{}")
    with pytest.raises((ValueError, RuntimeError)):
        po._promote_research_contract(str(source), str(target))
    assert {p.name: p.read_bytes() for p in target.iterdir() if p.is_file()} == before


def test_stage_reuse_validates_present_context_without_legacy_manifest(tmp_path, monkeypatch):
    _research(tmp_path)
    _capture(tmp_path)
    state = po.PipelineState(pipeline_id="pipe_news", prompt="fixture question", handoff_dir=str(tmp_path))
    monkeypatch.setattr(po.PipelineManager, "load_artifact_manifest", lambda _: {})
    specs = dict(po.PipelineOrchestrator._stage_artifact_specs(state, po.STAGE_RESEARCH))
    assert specs.get("news_market_context") == str(tmp_path / "news_market_context.json")
    orchestrator = po.PipelineOrchestrator()
    assert orchestrator._validate_reuse(state, po.STAGE_RESEARCH)
    (tmp_path / "news_market_context.json").write_text("{}")
    with pytest.raises(ValueError):
        orchestrator._validate_reuse(state, po.STAGE_RESEARCH)


def test_consumed_generation_rejects_replacement_before_prepare(tmp_path, monkeypatch):
    handoff, sims = tmp_path / "handoff", tmp_path / "simulations"
    _research(handoff)
    _capture(handoff)
    (sims / "sim_news").mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sims))
    consumed = official_data.capture_research_generation(handoff)
    assert consumed["files"].get("news_market_context.json")
    _capture(handoff, generation="capture-two")
    with pytest.raises(ValueError, match="generation changed"):
        official_data.bind_simulation_research(
            "sim_news", handoff, pipeline_id="pipe_news", expected_generation=consumed)
    assert not (sims / "sim_news" / "official_research_binding.json").exists()


def test_old_missing_capture_remains_compatible(tmp_path, monkeypatch):
    handoff, sims = tmp_path / "handoff", tmp_path / "simulations"
    _research(handoff)
    (sims / "sim_old").mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sims))
    binding = official_data.bind_simulation_research("sim_old", handoff, pipeline_id="pipe_old")
    # Records written before this feature lack the optional fingerprint key.
    binding["files"].pop("news_market_context.json", None)
    (sims / "sim_old" / "official_research_binding.json").write_text(json.dumps(binding))
    assert official_data.simulation_research_binding("sim_old")["status"] == "valid"


@pytest.mark.parametrize("lane,expected", [(None, "2"), ("outer-track-1", "2"),
                                            ("outer-track-2", "0"), ("outer-track-3", "0")])
def test_parent_gives_news_allowance_only_to_baseline(monkeypatch, lane, expected):
    monkeypatch.setattr(po.Config, "NEWS_CONTEXT_ENABLED", True, raising=False)
    monkeypatch.setattr(po.Config, "NEWSAPI_MAX_REQUESTS", 17, raising=False)
    env = po._news_context_subprocess_env(budget_lane_id=lane)
    assert env["NEWSAPI_MAX_REQUESTS"] == expected
    assert "NEWSAPI_API_KEY" not in env
    assert env["NEWSAPI_PAGE_SIZE"] == "20"
    assert env["NEWS_CONTEXT_DEADLINE_SECONDS"] == "10"
    assert env["NEWS_CONTEXT_HTTP_TIMEOUT_SECONDS"] == "5"


@pytest.mark.parametrize("disabled,synthesis", [(True, False), (False, True)])
def test_off_and_synthesis_admit_no_fresh_context_requests(monkeypatch, disabled, synthesis):
    monkeypatch.setattr(po.Config, "NEWS_CONTEXT_ENABLED", not disabled, raising=False)
    env = po._news_context_subprocess_env(synthesis=synthesis)
    assert all(env[name] == "0" for name in (
        "NEWSAPI_MAX_REQUESTS", "REDDIT_MAX_REQUESTS", "MARKET_INTELLIGENCE_MAX_REQUESTS"))


@pytest.mark.parametrize("damage", ["deleted", "resealed", "changed_cutoff", "symlink"])
def test_registered_context_cannot_silently_trigger_refetch(tmp_path, monkeypatch, damage):
    _research(tmp_path)
    _capture(tmp_path)
    state = po.PipelineState(pipeline_id="pipe_news", prompt="fixture question", handoff_dir=str(tmp_path))
    path = tmp_path / "news_market_context.json"
    entry = po._manifest_entry_for("news_market_context", str(path), po.STAGE_RESEARCH)
    monkeypatch.setattr(po.PipelineManager, "load_artifact_manifest", lambda _: {"news_market_context": entry})
    if damage == "deleted":
        path.unlink()
    elif damage == "resealed":
        _capture(tmp_path, generation="capture-two")
    elif damage == "changed_cutoff":
        _capture(tmp_path, as_of="2026-10-17")
    else:
        original = tmp_path / "original.json"
        path.rename(original)
        path.symlink_to(original)
    with pytest.raises(ValueError):
        po.PipelineOrchestrator()._validate_reuse(state, po.STAGE_RESEARCH)


def test_stage_record_and_reload_retains_context_hash(tmp_path, monkeypatch):
    _research(tmp_path)
    _capture(tmp_path)
    state = po.PipelineState(pipeline_id="pipe_news", prompt="fixture question", handoff_dir=str(tmp_path))
    records = {}
    monkeypatch.setattr(po.PipelineManager, "load_artifact_manifest", lambda _: dict(records))
    monkeypatch.setattr(po.PipelineManager, "write_artifact_manifest", lambda _, manifest: records.update(manifest))
    monkeypatch.setattr(po.Config, "PIPELINE_VALIDATE_ARTIFACTS", True)
    orchestrator = po.PipelineOrchestrator()
    orchestrator._record_stage_artifacts(state, po.STAGE_RESEARCH)
    assert records["news_market_context"]["sha256"] == hashlib.sha256(
        (tmp_path / "news_market_context.json").read_bytes()).hexdigest()
    restored = po.PipelineState.from_dict(state.to_dict())
    assert orchestrator._validate_reuse(restored, po.STAGE_RESEARCH)


def test_orchestrator_deploys_context_modules_with_setup_parity():
    root = Path(po.__file__).resolve().parents[3]
    setup = (root / "setup.sh").read_text()
    for name in ("news_signals.py", "news_tools.py", "market_intelligence.py"):
        assert name in po._DEPLOYED_BRIDGE_MODULES
        assert name in setup


def test_seed_and_manual_dossier_use_the_same_consumed_capture(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.services.news_market_context import load_for_simulation
    handoff, sims = tmp_path / "handoff", tmp_path / "simulations"
    _research(handoff)
    context = _capture(handoff)
    for name in ("sim_parent", "sim_seed"):
        (sims / name).mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sims))
    report_md = (handoff / "research_report.md").read_text()
    official_data.bind_simulation_research("sim_parent", handoff, pipeline_id="pipe_news")
    prepared, reports = [], []
    monkeypatch.setattr(po, "SimulationManager", lambda: SimpleNamespace(
        create_simulation=lambda *args, **kw: SimpleNamespace(simulation_id="sim_seed"),
        prepare_simulation=lambda **kw: prepared.append(load_for_simulation(kw["simulation_id"]))))
    monkeypatch.setattr(po, "SimulationRunner", SimpleNamespace(
        start_simulation=lambda **kw: None, write_run_summary=lambda *args: None,
        get_run_state=lambda *args: SimpleNamespace(current_round=1, runner_status=po.RunnerStatus.COMPLETED)))
    def capture_report(**kw):
        reports.append(kw)
        return SimpleNamespace(generate_report=lambda **kw: None)
    monkeypatch.setattr(po, "ReportAgent", capture_report)
    runner = po.PipelineOrchestrator()
    monkeypatch.setattr(runner, "_pinned_safety", lambda *args: False)
    monkeypatch.setattr(runner, "_read_report_forecast", lambda rid: {"headline": "fixture"})
    state = SimpleNamespace(pipeline_id="pipe_news", simulation_id="sim_parent", handoff_dir=str(handoff),
                            prompt="fixture question", options={})
    runner._run_one_seed(state, SimpleNamespace(project_id="project_fixture"), "graph_fixture", {},
                         {"sources": []}, report_md, seed=2, max_rounds=1)
    assert prepared == [context]
    assert len(reports) == 1 and reports[0]["news_market_context"] == context
    assert po.load_research_dossier_for_simulation("sim_seed")["news_market_context"] == context
    _capture(handoff, generation="changed-generation")
    with pytest.raises(ValueError, match="binding|generation"):
        po.load_research_dossier_for_simulation("sim_seed")
    with pytest.raises(ValueError, match="generation"):
        runner._run_one_seed(state, SimpleNamespace(project_id="project_fixture"), "graph_fixture", {},
                             {"sources": []}, report_md, seed=3, max_rounds=1)
    assert len(reports) == len(prepared) == 1


def test_parent_merges_provider_qualified_captures_without_touching_markets(tmp_path, monkeypatch):
    from app.services.news_market_context import _bridge_api, load_context
    api = _bridge_api()
    monkeypatch.setenv("NEWS_CONTEXT_ENABLED", "true")
    lanes = []
    for provider in ("kalshi", "polymarket"):
        directory = tmp_path / provider
        client = api.ContextClient(directory, question="fixture question", language="en", as_of="2026-10-18")
        client.record_result(provider, "capacity", {
            "provider": provider, "query": "capacity", "status": {"state": "ok", "attempted": True},
            "items": [{"id": "same-native", "provider": provider, "kind": "market_quote",
                       "title": "Capacity outlook", "url": f"https://example.org/{provider}",
                       "published_at": None, "retrieved_at": "2026-10-18T00:00:00Z",
                       "language": "en", "query": "capacity", "snippet": "Context comparison",
                       "eligibility": {"context_only": True, "anchor": False, "resolution": False}}],
            "retrieved_at": "2026-10-18T00:00:00Z"})
        client.seal(source_refs={f"https://example.org/{provider}": "S87"})
        lanes.append(str(directory))
    output = tmp_path / "merged"
    output.mkdir()
    canonical = b'{"markets":[{"id":"canonical-polymarket"}]}'
    (output / "prediction_markets.json").write_bytes(canonical)
    sources = [{"url": "https://example.org/polymarket"}, {"url": "https://example.org/kalshi"}]
    merged = po._merge_track_news_context(lanes + lanes[:1], str(output), sources)
    assert {item["id"] for item in merged["items"]} == {"kalshi:same-native", "polymarket:same-native"}
    assert len(merged["items"]) == 2
    assert all(item["eligibility"] == {"context_only": True, "anchor": False, "resolution": False}
               for item in merged["items"])
    assert load_context(output) == merged
    assert (output / "prediction_markets.json").read_bytes() == canonical
    assert json.loads((output / "sources.json").read_text()) == sources
    assert po._merge_track_news_context(lanes, str(output), sources) == merged
    # A corrupt supplied lane fails before replacing any output proof.
    before = (output / "news_market_context.json").read_bytes()
    (Path(lanes[0]) / "news_market_context.json").write_text("{}")
    with pytest.raises(ValueError):
        po._merge_track_news_context(lanes, str(output), sources)
    assert (output / "news_market_context.json").read_bytes() == before


@pytest.mark.parametrize("canonical", [None, "a" * 64])
def test_real_child_env_uses_parent_question_identity_and_ignores_ambient(tmp_path, monkeypatch, canonical):
    from tests.test_data_sources_config import _run_research_capturing_env
    monkeypatch.setenv("NEWS_CONTEXT_QUESTION_SHA256", "f" * 64)
    if canonical:
        run = po.DeerFlowResearchRunner.run
        monkeypatch.setattr(po.DeerFlowResearchRunner, "run", lambda *args, **kw:
                            run(*args, context_question_sha256=canonical, **kw))
    captured = _run_research_capturing_env(monkeypatch, tmp_path)
    assert captured["NEWS_CONTEXT_QUESTION_SHA256"] == (canonical or po._news_context_question_digest("forecast question"))
    assert captured["NEWS_CONTEXT_QUESTION_SHA256"] != "f" * 64
    assert captured["NEWSAPI_MAX_REQUESTS"] == "2"


@pytest.fixture
def actual_parent_case(tmp_path, monkeypatch):
    """Keep real _run, promotion, finalization, capture and binding; stub external services."""
    from types import SimpleNamespace
    for name, value in {"PIPELINE_DATA_DIR": str(tmp_path / "pipelines"),
                        "UPLOAD_FOLDER": str(tmp_path / "uploads"), "RESEARCH_ENGINE": "v3",
                        "RESEARCH_PARALLEL_TRACKS": 1, "REPORT_LINT": False,
                        "CAST_RECONCILE": False, "EMBED_WARM_AT_RESEARCH": False,
                        "PIPELINE_VIZ_ARTIFACTS": False, "DEERFLOW_DUAL_TRACK": False}.items():
        monkeypatch.setattr(po.Config, name, value, raising=False)
    for name, replacement in {
        "_start_heartbeat": lambda self, state: None,
        "_init_telemetry_flush": lambda self, state: None,
        "_write_run_manifest": lambda self, state: None,
        "_update_manifest": lambda self, state, stage, **kw: None,
        "_record_research_telemetry": lambda self, state, value: None,
        "_maybe_warm_embedder": lambda self, state, actors: None,
        "_surface_research_quality": lambda self, state, hd: {},
        "_surface_forecast_confidence_penalty": lambda self, state, hd: None,
        "_flush_run_telemetry": lambda self, state, **kw: None,
    }.items():
        monkeypatch.setattr(po.PipelineOrchestrator, name, replacement)
    monkeypatch.setattr(po, "_register_outage_breaker", lambda pid: None)
    calls = []
    def forbidden_dispatch(*args, **kw):
        calls.append("research_or_report_dispatch")
        raise AssertionError("Source acquisition/recovery/report must not run")
    monkeypatch.setattr(po.DeerFlowResearchRunner, "run", forbidden_dispatch)
    monkeypatch.setattr(po.PipelineOrchestrator, "_run_research_synthesis_recovery", forbidden_dispatch)
    monkeypatch.setattr(po.PipelineOrchestrator, "_run_parallel_research_tracks", forbidden_dispatch)
    monkeypatch.setattr(po, "ReportAgent", forbidden_dispatch)
    pid = "pipe_real_context"
    po.PipelineManager.ensure_dirs(pid)
    hd = Path(po.PipelineManager.handoff_dir(pid))
    hd.mkdir(parents=True, exist_ok=True)
    _research(hd)
    state = po.PipelineState(pipeline_id=pid, prompt="fixture question", mode="research_only",
                             status="running", handoff_dir=str(hd), stages={
        name: po.StageState(name=name, status="completed", progress=100)
        for name in (po.STAGE_RESEARCH, po.STAGE_ONTOLOGY, po.STAGE_GRAPH)})
    state.options["actor_intelligence_policy_v1"] = po.capture_actor_intelligence_policy_v1("fixture", required=False)
    return SimpleNamespace(state=state, hd=hd, calls=calls, tmp_path=tmp_path)


@pytest.mark.parametrize("declared", [True, False])
def test_real_run_declared_deleted_capture_fails_before_recovery(actual_parent_case, declared):
    case = actual_parent_case
    if declared:
        _capture(case.hd)
    po._promote_research_contract(str(case.hd), str(case.hd))
    if declared:
        (case.hd / "news_market_context.json").unlink()
    po.PipelineOrchestrator._run(case.state)
    assert case.calls == []
    if declared:
        assert case.state.status == "failed" and "Declared news context capture is missing" in case.state.error
    else:
        assert case.state.status == "completed", case.state.error


@pytest.mark.parametrize("late", ["valid_capture", "malformed_capture", "old_official_only"])
def test_real_prepare_rejects_late_context_addition(actual_parent_case, monkeypatch, late):
    from types import SimpleNamespace
    from app.services import zep_entity_reader
    case = actual_parent_case
    po._promote_research_contract(str(case.hd), str(case.hd))
    case.state.mode = "full"
    case.state.project_id, case.state.graph_id = "project_fixture", "graph_fixture"
    project = SimpleNamespace(project_id="project_fixture", graph_id="graph_fixture", ontology={"entity_types": ["Actor"]})
    monkeypatch.setattr(po.ProjectManager, "get_project", lambda pid: project)
    monkeypatch.setattr(zep_entity_reader, "ZepEntityReader", lambda: SimpleNamespace(
        filter_defined_entities=lambda *a, **kw: SimpleNamespace(entities=[{}])))
    monkeypatch.setattr(po, "GraphBuilderService", lambda **kw: SimpleNamespace(set_ontology=lambda *a: None))
    sims = case.tmp_path / "simulations"
    (sims / "sim_late").mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sims))
    prepared = []
    def create(*args, **kw):
        if late == "valid_capture":
            _capture(case.hd)
        elif late == "malformed_capture":
            (case.hd / "news_market_context.json").write_text("{}")
        else:
            (case.hd / "research_report.md").write_text("Changed official-only research generation")
        return SimpleNamespace(simulation_id="sim_late")
    def prepare(**kw):
        prepared.append(kw)
        raise RuntimeError("fixture stops after permitted legacy preparation")
    monkeypatch.setattr(po, "SimulationManager", lambda: SimpleNamespace(
        create_simulation=create, prepare_simulation=prepare))
    po.PipelineOrchestrator._run(case.state)
    assert case.calls == [] and case.state.status == "failed"
    assert not (sims / "sim_late" / "official_research_binding.json").exists()
    if late == "old_official_only":
        assert len(prepared) == 1 and "fixture stops" in case.state.error
        assert case.state.options["official_data_binding"]["status"] == "unavailable"
    else:
        assert prepared == []
        assert "News context consumed generation changed before preparation" in case.state.error


def test_actual_multitrack_parent_passes_one_original_question_digest(tmp_path, monkeypatch):
    from app.services.news_market_context import load_context
    monkeypatch.setattr(po.Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))
    for name, value in {"RESEARCH_GLOBAL_SYNTHESIS": False, "RESEARCH_TRACK_RECONCILE": False,
                        "RESEARCH_COMPACT_MERGED_DOSSIER": False, "DEERFLOW_DUAL_TRACK": False}.items():
        monkeypatch.setattr(po.Config, name, value, raising=False)
    monkeypatch.setattr(po, "_sync_deerflow_bridge_if_stale", lambda path: None)
    monkeypatch.setattr(po, "_activate_research_budget_epoch", lambda *args:
                        (str(tmp_path / "budget.sqlite"), str(tmp_path / "budget.json"), "fixture-epoch"))
    monkeypatch.setattr(po, "_research_budget_exhaustion", lambda *args: None)
    state = po.PipelineState(pipeline_id="pipe_angles", prompt="  Original forecast question by 2030?  ",
                             handoff_dir=str(tmp_path / "handoff"), options={"research_engine": "legacy"})
    expected = po._news_context_question_digest(state.prompt)
    calls = []
    def run(prompt, handoff_dir, **kwargs):
        calls.append((prompt, kwargs["context_question_sha256"], kwargs["budget_lane_id"]))
        directory = Path(handoff_dir)
        _research(directory)
        _capture(directory, generation=directory.name, question_digest=kwargs["context_question_sha256"])
        return {"report": (directory / "research_report.md").read_text(), "actor_dossier": "",
                "actors": {"actors": []}, "sources": [], "timeline": [], "exit_code": 0}
    monkeypatch.setattr(po.DeerFlowResearchRunner, "run", run)
    result = po.PipelineOrchestrator()._run_parallel_research_tracks(
        state, state.handoff_dir, lambda *args: None, 3)
    assert len(calls) == 3 and len({prompt for prompt, _, _ in calls}) == 3
    assert {identity for _, identity, _ in calls} == {expected}
    assert {lane for _, _, lane in calls} == {"outer-track-1", "outer-track-2", "outer-track-3"}
    merged = load_context(state.handoff_dir)
    assert merged["question_sha256"] == expected
    assert len(merged["input_generations"]) == 3
    assert result["news_market_context"] == merged



def test_old_bound_simulation_rejects_a_new_present_capture(tmp_path, monkeypatch):
    handoff, sims = tmp_path / "handoff", tmp_path / "simulations"
    _research(handoff)
    (sims / "sim_old").mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sims))
    official_data.bind_simulation_research("sim_old", handoff, pipeline_id="pipe_old")
    assert po.load_research_dossier_for_simulation("sim_old")["news_market_context"] is None
    _capture(handoff)
    assert official_data.simulation_research_binding("sim_old")["status"] == "invalid"
    with pytest.raises(ValueError, match="binding"):
        po.load_research_dossier_for_simulation("sim_old")
