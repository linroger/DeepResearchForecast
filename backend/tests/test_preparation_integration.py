"""PREPARE to executable config, actual arbiter requests, seals and replay."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import sys

import pytest

from app.config import Config
from app.services import preparation_adapter as adapter
from app.services import research_preparation as rp
from app.services import simulation_config_generator as sc
from app.services import world_update as wu
from app.services.actor_context import canonical_json_sha256
from app.services.simulation_manager import validate_simulation_config_seal
from tests.conftest import FakeLLMClient
from test_actor_context_runtime import _entity, _prepare_offline_simulation
from test_research_preparation import canonical_fixture, compile_bundle, series
from test_world_update import _world, _decisions, _PERIOD


@pytest.fixture(autouse=True)
def reviewed_task_model_boundary(monkeypatch):
    """Script only task-model output; keep real admission, source quotes and calendar checks."""
    from tests.forecast_task_fakes import task_protocol
    def respond(_self, prompt, _system_prompt):
        payload, _ = json.JSONDecoder().raw_decode(prompt.split("\n", 1)[1])
        inputs = payload["inputs"] if prompt.startswith("FORECAST TASK REVIEW") else payload
        requirement = inputs["requirement"]
        quote = next((text for text in ("December 31, 2026", "2026-12-31") if text in requirement), None)
        expected = ({"horizon_date": "2026-12-31", "source_field": "requirement", "source_quote": quote}
                    if quote else None)
        result = task_protocol(prompt, expected=expected)
        assert result is not None
        return result
    monkeypatch.setattr(sc.SimulationConfigGenerator, "_call_task_json", respond)


@pytest.fixture(autouse=True)
def source_receipt():
    guard = sys.modules.get("main_offline_guard")
    if guard:
        for name in ("preparation_adapter", "research_preparation", "simulation_manager",
                     "simulation_config_generator", "world_update"):
            path = Path(__file__).resolve().parents[1] / "app/services" / (name + ".py")
            guard.source_hashes.setdefault(str(path), hashlib.sha256(path.read_bytes()).hexdigest())


def test_actual_manager_prepares_before_profiles_and_seals_reload(tmp_path, monkeypatch):
    manager, state, _ = _prepare_offline_simulation(tmp_path, monkeypatch)
    directory = tmp_path / state.simulation_id
    config = json.loads((directory / "simulation_config.json").read_text())
    bundle = adapter.load_config_preparation(directory, config)
    roles = json.loads((directory / "reddit_profiles_roles.json").read_text())
    assert all(row["preparation_context_sha256"] == bundle["content_sha256"] for row in roles["roles"])
    manager.validate_prepared_simulation_config(state.simulation_id)
    assert "research_preparation" in validate_simulation_config_seal(str(directory))["bindings"]
    # A completed run cannot silently regain mutable upstream inputs on reuse.
    (directory / "research_preparation.json").unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        manager.validate_prepared_simulation_config(state.simulation_id)


def test_actual_config_requests_use_public_projection_and_pin_actor_ids(monkeypatch):
    actors, packs, report = canonical_fixture()
    question = "Will capacity expand by December 31, 2026?"
    bundle = rp.compile_preparation_context(question=question, research_report=report,
        actors=actors, actor_context_packs=packs, official_data={"series": [series(
            series="fred:CAPACITY", title="Capacity", units="MW")]})
    assert any(row["series"] == "fred:CAPACITY" for row in bundle["quantitative"]["observations"])
    llm = FakeLLMClient()
    monkeypatch.setattr(sc, "LLMClient", lambda **kw: llm)
    monkeypatch.setattr(Config, "SIM_TEMPORAL_MODE", "calendar")
    monkeypatch.setattr(Config, "SIM_WORLD_MODEL", True)
    monkeypatch.setattr(Config, "SIM_AUDIENCE_AGENTS", 0)
    monkeypatch.setattr(sc.SimulationConfigGenerator, "_load_prediction_markets", lambda *a: [])
    params = sc.SimulationConfigGenerator().generate_config(
        simulation_id="sim_grounded", project_id="project_grounded", graph_id="graph_grounded",
        simulation_requirement=question, document_text=report,
        entities=[_entity(a) for a in actors["actors"]], actors=actors,
        actor_context_packs=packs, preparation_context=bundle, research_language="English", max_rounds=3)
    config = params.to_dict()
    assert config["research_preparation"] == adapter.preparation_marker(bundle)
    assert [a["actor_id"] for a in config["agent_configs"]] == [a["actor_id"] for a in actors["actors"]]
    assert "fred:CAPACITY" in config["world_brief"] and '"unit":"MW"' in config["world_brief"]
    assert config["world_model"]["state_variables"]
    assert config["world_model"]["as_of_date"] == actors["as_of_date"]
    assert config["world_model"]["settings"]["research_information_cutoff"] == bundle["scope"]["as_of"]
    for secret in ("PRIVATE OWNER PLAN", "DENIED SECRET", "ANALYST GUESS"):
        assert secret not in config["world_brief"]
        assert secret not in json.dumps(llm.calls)
    assert llm.calls  # The actual event generation request was exercised.
    changed = deepcopy(bundle)
    changed["scope"]["question"] = "replacement"
    previous_calls = len(llm.calls)
    with pytest.raises(ValueError):
        sc.SimulationConfigGenerator().generate_config(
            simulation_id="sim_grounded", project_id="p", graph_id="g", simulation_requirement=question,
            document_text=report, entities=[], actors=actors, preparation_context=changed)
    assert len(llm.calls) == previous_calls


def test_bound_adapter_uses_exact_generation_and_pins_window(tmp_path, monkeypatch):
    actors = {"as_of_date": "2026-07-01", "actors": []}
    docs = {"actors.json": json.dumps(actors), "research_report.md": "exact report", "sources.json": "[]"}
    for name, value in docs.items():
        (tmp_path / name).write_text(value)
    binding = {"status": "valid", "pipeline_id": "pipe_test", "handoff_dir": str(tmp_path),
               "files": {name: hashlib.sha256(value.encode()).hexdigest() for name, value in docs.items()}}
    monkeypatch.setattr(adapter.official_data, "simulation_research_binding", lambda _: deepcopy(binding))
    monkeypatch.setattr(adapter.official_data, "load_official_data", lambda _, **kw: {"series": [series()]})
    window = {"started_at": "2026-07-01T00:00:00Z", "finished_at": "2026-07-02T00:00:00Z"}
    monkeypatch.setattr(adapter.official_data, "research_run_window", lambda _: deepcopy(window))
    bundle = adapter.prepare_research_context("s", question="GDP", research_report="exact report",
                                               actors=actors, research_generation_id="research_caller")
    assert bundle["source"]["source_binding"]["research_generation_id"] == "research_caller"
    assert bundle["scope"]["research_window"] == window
    assert bundle["quantitative"]["observations"]
    with pytest.raises(ValueError, match="differ"):
        adapter.prepare_research_context("s", question="GDP", research_report="changed", actors=actors)
    (tmp_path / "actors.json").write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        adapter.prepare_research_context("s", question="GDP", research_report="exact report", actors=actors)


def test_arbiter_consumes_research_and_accepted_update_replays_without_provider():
    bundle = compile_bundle(official_data={"series": [series()]})
    world = _world()
    llm = FakeLLMClient(json_responses=[{"narrative": "Capacity waits for a permit."}])
    record = wu.run_world_round(world, 1, _PERIOD, _decisions(), [], llm=llm, rng=random.Random(6),
                                preparation_context=bundle)
    prompt = llm.calls[0]["messages"][0]["content"]
    assert "Billions of Dollars" in prompt and "fred:GDP" in prompt
    assert "not hard bounds or causal coefficients" in prompt
    replay = json.loads(json.dumps(record["replay"]))
    assert wu.replay_world_round(replay, preparation_context=bundle).to_dict() == world.to_dict()
    assert len(llm.calls) == 1
    replay["accepted_arbiter_update"]["narrative"] = "forged"
    with pytest.raises(ValueError, match="fingerprint"):
        wu.replay_world_round(replay, preparation_context=bundle)


def test_failed_partial_apply_rolls_back_and_replay_cannot_gain_authority(monkeypatch):
    world = _world()
    before = next(iter(world.variables.values())).value
    def fail(self, *_args):
        next(iter(self.variables.values())).value = 999999
        raise ValueError("synthetic partial application")
    monkeypatch.setattr(type(world), "apply_arbiter_update", fail)
    record = wu.run_world_round(world, 1, _PERIOD, [], [],
        llm=FakeLLMClient(json_responses=[{"narrative": "attempt"}]), rng=random.Random(0))
    assert record["arbiter_status"] == "failed"
    assert record["narrative"] == ""
    assert next(iter(world.variables.values())).value == before
    assert record["replay"]["accepted_arbiter_update"] == {}
    assert wu.replay_world_round(record["replay"]).to_dict() == world.to_dict()


@pytest.mark.parametrize("marker", [None, {}, {"schema_version": "unknown"}])
def test_explicit_bad_marker_never_becomes_legacy(tmp_path, marker):
    with pytest.raises(ValueError):
        adapter.load_config_preparation(tmp_path, {"research_preparation": marker})
    assert adapter.load_config_preparation(tmp_path, {}) is None


def test_invalid_binding_is_checked_before_graph_or_actorless_fallback(tmp_path, monkeypatch):
    from app.services import simulation_manager as sm
    from test_actor_context_runtime import _dossier, REPORT
    calls = []
    def invalid(_):
        calls.append("binding")
        return {"status": "invalid"}
    monkeypatch.setattr(adapter.official_data, "simulation_research_binding", invalid)
    monkeypatch.setattr(sm.SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sm, "ZepEntityReader", lambda: calls.append("graph"))
    manager = sm.SimulationManager()
    state = manager.create_simulation(project_id="p", graph_id="g")
    before = {p.name: p.read_bytes() for p in (tmp_path / state.simulation_id).iterdir() if p.is_file()}
    with pytest.raises(ValueError, match="generation changed"):
        manager.prepare_simulation(state.simulation_id, "grid", REPORT, actors=_dossier(), use_llm_for_profiles=False)
    assert calls == ["binding"]
    assert {p.name: p.read_bytes() for p in (tmp_path / state.simulation_id).iterdir() if p.is_file()} == before
    with pytest.raises(ValueError, match="generation changed"):
        adapter.prepare_research_context(state.simulation_id, question="grid", research_report=REPORT, actors=None)


def test_pinned_dataset_corruption_cannot_be_resealed_as_absence(tmp_path, monkeypatch):
    from app.services.simulation_manager import SimulationManager
    simroot = tmp_path / "sims"
    (simroot / "sim_bound").mkdir(parents=True)
    handoff = tmp_path / "handoff"
    handoff.mkdir()
    actors = {"as_of_date": "2026-07-01", "actors": []}
    for name, content in {"research_report.md": "GDP report [S1]", "actors.json": json.dumps(actors),
                          "sources.json": "[]"}.items():
        (handoff / name).write_text(content)
    api = adapter.official_data.data_api()
    manifest = api.write_dataset_files([api.Series.from_dict(series())], handoff, citations={"fred:GDP": "S1"})
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(simroot))
    adapter.official_data.bind_simulation_research("sim_bound", handoff, pipeline_id="pipe_bound")
    before = adapter.prepare_research_context("sim_bound", question="GDP", research_report="GDP report [S1]", actors=actors)
    assert before["quantitative"]["observations"]
    (handoff / manifest["series"][0]["csv"]).write_text("corrupt")
    with pytest.raises(ValueError, match="dataset"):
        adapter.prepare_research_context("sim_bound", question="GDP", research_report="GDP report [S1]", actors=actors)
    assert not (simroot / "sim_bound" / "research_preparation.json").exists()


def test_shared_consequence_arbiter_never_receives_private_modeler_rows():
    actors, packs, report = canonical_fixture()
    bundle = rp.compile_preparation_context(question="Will capacity expand?", research_report=report,
                                            actors=actors, actor_context_packs=packs)
    assert "PRIVATE OWNER PLAN" in rp.render_preparation_context(bundle, audience="modeler", max_chars=100000)
    class ObservingArbiter:
        def chat_json(self, messages, **kw):
            prompt = messages[0]["content"]
            for hidden in ("PRIVATE OWNER PLAN", "DENIED SECRET", "ANALYST GUESS"):
                assert hidden not in prompt
            return {"narrative": "Public capacity remains conditional on permission."}
    record = wu.run_world_round(_world(), 1, _PERIOD, [], [], llm=ObservingArbiter(), rng=random.Random(0),
                                 preparation_context=bundle)
    assert record["arbiter_status"] == "applied"
    assert "PRIVATE OWNER PLAN" not in record["digest"]


def test_legacy_shared_events_use_filtered_dossier_and_reserve_numeric_context(monkeypatch):
    from app.services.actor_context import actor_id_for, build_actor_context_pack
    actors = {"as_of_date": "2026-07-01", "situation_brief": "Long public situation " * 2000,
              "actors": [{"actor_id": "legacy_alpha", "name": "Alpha", "type": "Organization", "role": "firm",
                          "goals": [{"claim": "PRIVATE_GOAL_SENTINEL", "visibility": "private"},
                                    {"claim": "PUBLIC_GOAL_SENTINEL", "visibility": "public"}]}],
              "key_events": [{"date": "2026-09-01", "event": "PRIVATE_EVENT_SENTINEL", "visibility": "private"},
                             {"date": "2026-09-02", "event": "PUBLIC_EVENT_SENTINEL", "visibility": "public"}]}
    actors["actors"][0]["stance"] = {"claim": "PRIVATE_STANCE_SENTINEL", "visibility": "private"}
    actors["hot_topics"] = [{"topic": "PRIVATE_TOPIC_SENTINEL", "visibility": "private"}, "Public capacity"]
    actors["actors"].append({"actor_id": "legacy_beta", "name": "Beta", "type": "Organization", "role": "firm",
                              "stance": "PUBLIC_STANCE_SENTINEL"})
    report, question = "Alpha research.", "Will capacity expand by December 31, 2026?"
    packs = {actor_id_for(a): build_actor_context_pack(actors, a, report) for a in actors["actors"]}
    bundle = rp.compile_preparation_context(question=question, research_report=report,
        actors=actors, actor_context_packs=packs,
        official_data={"series": [series(series="fred:CAPACITY", title="Capacity", units="MW")]})
    llm = FakeLLMClient(responses=['{"hot_topics":[],"initial_posts":[]}'])
    monkeypatch.setattr(sc, "LLMClient", lambda **kw: llm)
    monkeypatch.setattr(Config, "SIM_TEMPORAL_MODE", "calendar")
    monkeypatch.setattr(Config, "SIM_WORLD_MODEL", True)
    monkeypatch.setattr(Config, "SIM_AUDIENCE_AGENTS", 0)
    monkeypatch.setattr(sc.SimulationConfigGenerator, "_load_prediction_markets", lambda *a: [])
    params = sc.SimulationConfigGenerator().generate_config(
        simulation_id="sim_legacy_shared", project_id="p", graph_id="g", simulation_requirement=question,
        document_text=report, entities=[_entity(a) for a in actors["actors"]], actors=actors,
        actor_context_packs=packs, preparation_context=bundle, research_language="English")
    event_request = json.dumps(llm.calls[0]["messages"])
    assert "fred:CAPACITY" in event_request and "MW" in event_request
    assert "PRIVATE_GOAL_SENTINEL" not in event_request
    assert "PRIVATE_EVENT_SENTINEL" not in event_request
    assert "PUBLIC_GOAL_SENTINEL" in event_request
    events = json.dumps(params.event_config.scheduled_events)
    assert "PRIVATE_EVENT_SENTINEL" not in events
    assert "PUBLIC_EVENT_SENTINEL" in events
    shared = json.dumps({"posts": params.event_config.initial_posts,
                         "topics": params.event_config.hot_topics, "brief": params.world_brief})
    assert "PUBLIC_STANCE_SENTINEL" in shared and "Public capacity" in shared
    assert "PRIVATE_STANCE_SENTINEL" not in shared and "PRIVATE_TOPIC_SENTINEL" not in shared


def test_empty_prepared_actor_fields_never_reopen_raw_config_on_hydration():
    from app.services.world_model import WorldModel
    seed = {"preparation_context_sha256": "a" * 64,
            "actors": [{"agent_id": 0, "name": "Alpha", "posture": "", "incentives": {}}]}
    config = [{"agent_id": 0, "entity_name": "Alpha", "stance": "PRIVATE_POSTURE",
               "gains_if": "PRIVATE_INCENTIVE"}]
    world = WorldModel.from_seed(seed, config)
    for candidate in (world, WorldModel.from_dict(world.to_dict())):
        assert candidate.actors[0].posture == ""
        assert not candidate.actors[0].incentives
        assert "PRIVATE_" not in json.dumps(candidate.to_dict())
    old = WorldModel.from_seed({"actors": seed["actors"]}, config)
    assert old.actors[0].posture == "PRIVATE_POSTURE"  # Historical unmarked fallback is explicit.
