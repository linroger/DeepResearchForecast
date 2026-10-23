"""PREPARE audit: real manager, pack, role, profile and config producers.

Only external graph responses and model responses are scripted. Run exclusively
through main_offline_pytest.py in a private source mirror.
"""
from copy import deepcopy
import hashlib
import json

import pytest

from app.config import Config
from app.services.actor_context import (
    actor_id_for, build_actor_context_pack, canonical_json_sha256,
    validate_actor_context_artifacts,
)
from app.services.oasis_profile_generator import OasisProfileGenerator
from app.services.simulation_config_generator import SimulationConfigGenerator
from app.services.simulation_manager import SimulationManager, SimulationStatus
from app.services.zep_entity_reader import FilteredEntities
from tests.test_actor_context_runtime import REPORT, _dossier, _entity
from tests.test_sim_context_persona import FakeAgent, FakeGraph
from scripts.run_parallel_simulation import _inject_world_brief


QUESTION = "Will the grid permit unlock deployment?"


def _packs(dossier):
    return {actor_id_for(a): build_actor_context_pack(dossier, a, REPORT)
            for a in dossier["actors"]}


def _gen():
    return SimulationConfigGenerator.__new__(SimulationConfigGenerator)


@pytest.fixture
def prepare_env(tmp_path, monkeypatch):
    calls = []

    class ScriptedModel:
        def __init__(self, **_kwargs):
            pass

        def chat(self, messages, **_kwargs):
            calls.append(deepcopy(messages))
            from tests.forecast_task_fakes import task_protocol
            task = task_protocol(messages[-1]["content"])
            if task is not None:
                return json.dumps(task)
            # A response, not a substitute for a producer. Real retry/parser,
            # timeline fallback, event compiler and config builder still run.
            return json.dumps({
                "total_simulation_hours": 72, "minutes_per_round": 60,
                "hot_topics": [], "initial_posts": [],
                "reasoning": "scripted external response",
            })

    monkeypatch.setattr("app.services.oasis_profile_generator.LLMClient", ScriptedModel)
    monkeypatch.setattr("app.services.simulation_config_generator.LLMClient", ScriptedModel)
    monkeypatch.setattr(Config, "ZEP_API_KEY", "", raising=False)
    monkeypatch.setattr(Config, "LLM_PROVIDER", "fixture", raising=False)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "fixture", raising=False)
    monkeypatch.setattr(Config, "LLM_BASE_URL", None, raising=False)
    monkeypatch.setattr(Config, "SIM_TEMPORAL_MODE", "calendar", raising=False)
    monkeypatch.setattr(Config, "SIM_WORLD_MODEL", False, raising=False)
    monkeypatch.setattr(Config, "SIM_WORLD_BRIEF", True, raising=False)
    monkeypatch.setattr(Config, "SIM_AUDIENCE_AGENTS", 0, raising=False)
    monkeypatch.setattr(Config, "ACTOR_CAST_MAX", 20, raising=False)
    monkeypatch.setattr(Config, "OASIS_MAX_AGENTS", 80, raising=False)
    monkeypatch.setattr(OasisProfileGenerator, "_print_generated_profile", lambda *a, **k: None)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path))

    class GraphResponse:
        def filter_defined_entities(self, **_kwargs):
            # Missing graph nodes exercises the real dossier stand-in producer.
            return FilteredEntities(entities=[], entity_types=set(), total_count=0, filtered_count=0)

    monkeypatch.setattr("app.services.simulation_manager.ZepEntityReader", GraphResponse)
    return calls


def _prepare(dossier, simulation_id=None, report=REPORT):
    manager = SimulationManager()
    if simulation_id is None:
        simulation_id = manager.create_simulation(
            project_id="audit-project", graph_id="audit-graph",
            enable_twitter=True, enable_reddit=True,
        ).simulation_id
    state = manager.prepare_simulation(
        simulation_id, QUESTION, report, actors=dossier,
        research_language="English", max_rounds=12,
    )
    return manager, state


def _config(manager, state):
    from pathlib import Path
    directory = Path(manager._get_simulation_dir(state.simulation_id))
    return directory, json.loads((directory / "simulation_config.json").read_text())


def test_real_prepare_retains_task_context_without_public_claims(prepare_env):
    dossier = _dossier()  # Source-bound actor rows, none explicitly public.
    manager, state = _prepare(dossier)
    directory, config = _config(manager, state)
    assert state.status == SimulationStatus.READY
    assert config["simulation_requirement"] == QUESTION
    assert QUESTION in config.get("world_brief", "")
    assert dossier["as_of_date"] in config["world_brief"]
    assert dossier["forecast_horizon"] in config["world_brief"]
    assert config["output_language"] == "English"
    # Task metadata must not reopen graph/report/dossier prose as public facts.
    assert "Project Aurora" not in config["world_brief"]
    assert "Fair Grid" not in config["world_brief"]
    messages = json.dumps(prepare_env)
    assert dossier["as_of_date"] in messages
    assert dossier["forecast_horizon"] in messages
    assert "Project Aurora" not in messages
    assert state.actor_context_count == state.actor_role_count == 2
    profiles = json.loads((directory / "reddit_profiles.json").read_text())
    agents = [FakeAgent(profile["persona"]) for profile in profiles]
    _inject_world_brief(FakeGraph(agents), config["world_brief"], lambda message: None)
    for agent in agents:
        actual = agent._original_system_message.content
        assert QUESTION in actual
        assert dossier["as_of_date"] in actual
        assert dossier["forecast_horizon"] in actual
    manifest = manager.validate_prepared_simulation_config(state.simulation_id)
    assert manifest["simulation_config_sha256"] == state.simulation_config_sha256
    (directory / "audit-model-inputs.json").write_text(json.dumps(prepare_env, indent=2))


def test_calendar_uses_dossier_horizon_before_model_default(prepare_env):
    dossier = _dossier()
    dossier["forecast_horizon"] = "through 2029"
    manager, state = _prepare(dossier)
    _, config = _config(manager, state)
    assert config["temporal_config"]["horizon_date"] == "2029-12-31"
    assert config["temporal_config"]["as_of_date"] == "2026-07-01"
    assert config["temporal_config"]["n_rounds"] <= 12


def test_question_horizon_keeps_priority_over_dossier_horizon(monkeypatch):
    generator = _gen()
    monkeypatch.setattr(generator, "_llm_extract_horizon", lambda *a: pytest.fail("unneeded LLM"))
    dossier = _dossier()
    dossier["forecast_horizon"] = "through 2029"
    timeline = generator._build_temporal_timeline("Will it happen by 2028-06-30?", dossier, "", 12)
    assert timeline.horizon_date == "2028-06-30"


@pytest.mark.parametrize("field", ["actor_knows", "qualifiers"])
def test_explicit_denial_cannot_schedule_public_event(field):
    dossier = _dossier()
    dossier["key_events"][0].update(visibility="public", evidence_type="verified_fact")
    dossier["key_events"][0][field] = False if field == "actor_knows" else {"actor_knows": False}
    packs = _packs(dossier)
    events = _gen()._canonical_context_event_rows(dossier, packs)
    assert not any("Alpha Systems" in row["event"] for row in events)


@pytest.mark.parametrize("field", ["actor_knows", "qualifiers"])
def test_explicit_denial_cannot_create_public_relationship(field):
    dossier = _dossier()
    row = dossier["relationships"][0]
    row.update(visibility="public", evidence_type="verified_fact")
    row[field] = False if field == "actor_knows" else {"actor_knows": False}
    assert _gen()._canonical_context_relationship_rows(dossier, _packs(dossier)) == []


def test_valid_public_events_and_relationships_reach_real_config(prepare_env):
    dossier = _dossier()
    dossier["key_events"][0].update(visibility="public", evidence_type="verified_fact")
    dossier["relationships"][0].update(visibility="public", evidence_type="verified_fact")
    manager, state = _prepare(dossier)
    _, config = _config(manager, state)
    assert config["event_config"]["scheduled_events"]
    assert config["event_config"]["initial_follows"]


def test_denied_events_and_relationships_stay_out_of_real_config(prepare_env):
    dossier = _dossier()
    dossier["key_events"][0].update(visibility="public", evidence_type="verified_fact", actor_knows=False)
    dossier["relationships"][0].update(visibility="public", evidence_type="verified_fact", actor_knows=False)
    manager, state = _prepare(dossier)
    _, config = _config(manager, state)
    assert not config["event_config"]["scheduled_events"]
    assert not config["event_config"]["initial_follows"]


def test_real_prepare_reload_reprepare_and_failure_controls(prepare_env, monkeypatch):
    dossier = _dossier()
    for actor, marker in zip(dossier["actors"], ("ALPHA_LOCAL_ONLY", "BETA_LOCAL_ONLY")):
        actor["intelligence"]["dimensions"]["current_actions"][0]["claim"] = f"{actor['name']} performs {marker}."
    manager, state = _prepare(dossier)
    directory, config = _config(manager, state)
    before = {p.name: p.read_bytes() for p in directory.glob("*.json")}
    reloaded = SimulationManager()
    reloaded.validate_prepared_simulation_config(state.simulation_id)
    assert before == {p.name: p.read_bytes() for p in directory.glob("*.json")}
    assert [c["agent_id"] for c in config["agent_configs"]] == [0, 1]
    manifest, packs = validate_actor_context_artifacts(str(directory), expected_actor_ids=["actor_alpha", "actor_beta"])
    assert manifest["report_sha256"] == hashlib.sha256(REPORT.encode()).hexdigest()
    for actor_id, token, forbidden in (("actor_alpha", "ALPHA_LOCAL_ONLY", "BETA_LOCAL_ONLY"),
                                       ("actor_beta", "BETA_LOCAL_ONLY", "ALPHA_LOCAL_ONLY")):
        assert token in json.dumps(packs[actor_id])
        profile_index = ["actor_alpha", "actor_beta"].index(actor_id)
        reddit = json.loads((directory / "reddit_profiles.json").read_text())
        persona = reddit[profile_index]["persona"]
        assert token in persona
        assert forbidden not in persona
    dossier["forecast_horizon"] = "through 2028"
    _, updated = _prepare(dossier, state.simulation_id)
    assert updated.actor_context_manifest_sha256 != state.actor_context_manifest_sha256
    # State objects are cached by the manager, so retain the old config bytes as
    # the independent before-image rather than relying on mutable alias state.
    assert (directory / "simulation_config.json").read_bytes() != before["simulation_config.json"]
    reloaded.validate_prepared_simulation_config(updated.simulation_id)

    def fail_completion(self, saved):
        if saved.status == SimulationStatus.READY:
            raise OSError("completion-write fixture")
        return original_save(self, saved)

    original_save = SimulationManager._save_simulation_state
    monkeypatch.setattr(SimulationManager, "_save_simulation_state", fail_completion)
    with pytest.raises(OSError, match="completion-write fixture"):
        _prepare(dossier, state.simulation_id)
    assert reloaded._load_simulation_state(state.simulation_id).status == SimulationStatus.FAILED


@pytest.mark.parametrize("kind", ["report", "roster", "future_cutoff"])
def test_prepare_rejects_invalid_inputs_before_generation(prepare_env, kind):
    dossier = _dossier()
    if kind == "report":
        dossier["actor_intelligence_contract"]["report_sha256"] = "0" * 64
    elif kind == "roster":
        dossier["actors"][1]["actor_id"] = dossier["actors"][0]["actor_id"]
    else:
        dossier["actors"][0]["intelligence"]["dimensions"]["current_actions"][0]["as_of_date"] = "2027-01-01"
    with pytest.raises((ValueError, RuntimeError), match="fingerprint mismatch|missing from simulation cast|duplicate actor identities|exceeds as-of cutoff"):
        _prepare(dossier)
    assert prepare_env == []


def test_foreign_pack_rejected_by_actual_config_consumer():
    dossier = _dossier()
    packs = _packs(dossier)
    packs["actor_alpha"] = packs["actor_beta"]
    with pytest.raises(ValueError, match="identity mismatch"):
        _gen()._generate_agent_configs_batch("", [_entity(dossier["actors"][0])], 0, QUESTION,
                                             actors=dossier, actor_context_packs=packs)


def test_direct_prepare_argument_omission_reaches_actual_generator_prompts(prepare_env, monkeypatch):
    """Characterize the missing-argument API boundary; parent owns its repair.

    This invokes the actual downstream method with the legacy direct-route
    argument shape. It does not claim an HTTP route admission test.
    """
    dossier = _dossier()
    dossier["forecast_horizon"] = "through 2029"

    class GraphResponse:
        def filter_defined_entities(self, **_kwargs):
            return FilteredEntities(entities=[_entity(a) for a in dossier["actors"]],
                                    entity_types={"Organization"}, total_count=2, filtered_count=2)

    monkeypatch.setattr("app.services.simulation_manager.ZepEntityReader", GraphResponse)
    manager = SimulationManager()
    question = "电网许可是否会推动项目投产？"
    created = manager.create_simulation("audit-direct", "audit-graph", enable_twitter=False, enable_reddit=True)
    from app.services.forecast_task import ForecastTaskError
    # Missing task metadata now fails before sealing instead of inventing a
    # one-year endpoint. Keep the real successful bound control below.
    with pytest.raises(ForecastTaskError, match="unresolved"):
        manager.prepare_simulation(created.simulation_id, question, REPORT,
                                   use_llm_for_profiles=False)
    missing = manager.get_simulation(created.simulation_id)
    omitted_calls = json.dumps(prepare_env, ensure_ascii=False)
    assert dossier["forecast_horizon"] not in omitted_calls
    assert missing.actor_context_count == missing.actor_role_count == 0
    assert missing.status == SimulationStatus.FAILED

    prepare_env.clear()
    bound = manager.prepare_simulation(created.simulation_id, question, REPORT,
                                       actors=dossier, research_language="English", max_rounds=12)
    directory, bound_config = _config(manager, bound)
    actual_calls = json.dumps(prepare_env, ensure_ascii=False)
    assert dossier["forecast_horizon"] in actual_calls
    assert dossier["as_of_date"] in actual_calls
    assert bound.actor_context_count == bound.actor_role_count == 2
    assert bound_config["output_language"] == "English"
    assert bound_config["temporal_config"]["horizon_date"] == "2029-12-31"
    (directory / "audit-direct-input-comparison.json").write_text(json.dumps({
        "omitted_argument_prompts": json.loads(omitted_calls),
        "bound_argument_prompts": prepare_env,
        "boundary_limit": "actual prepare generators; HTTP admission belongs to coordinator",
    }, ensure_ascii=False, indent=2))


def test_graph_priors_reorder_real_cast_without_cross_actor_roles(prepare_env, monkeypatch):
    dossier = _dossier()
    monkeypatch.setattr(Config, "GRAPH_CENTRALITY_PRIORS", True, raising=False)
    manager = SimulationManager()
    created = manager.create_simulation("audit-priors", "audit-graph")
    state = manager.prepare_simulation(
        created.simulation_id, QUESTION, REPORT, actors=dossier,
        graph_priors={"Beta Union": 1.0, "Alpha Systems": 0.0},
        research_language="English", max_rounds=12,
    )
    directory, config = _config(manager, state)
    profiles = json.loads((directory / "reddit_profiles.json").read_text())
    roles = json.loads((directory / "reddit_profiles_roles.json").read_text())["roles"]
    assert [c["entity_name"] for c in config["agent_configs"]] == ["Beta Union", "Alpha Systems"]
    assert [row["actor_id"] for row in roles] == ["actor_beta", "actor_alpha"]
    assert [p["name"] for p in profiles] == [c["entity_name"] for c in config["agent_configs"]]
    assert [row["profile_index"] for row in roles] == [c["agent_id"] for c in config["agent_configs"]]
    manager.validate_prepared_simulation_config(state.simulation_id)


def test_late_relevant_report_paragraph_reaches_actual_persona(prepare_env, monkeypatch):
    dossier = _dossier()
    report = (
        "# Alpha Systems evidence\n\n"
        + ("General background without an actor-specific signal.\n\n" * 300)
        + "Alpha Systems has the LATE_RELEVANT_CONTEXT permit obligation.\n\n"
        + "# Beta Union evidence\n\nBeta Union has a separate reporting obligation.\n"
    )
    dossier["actor_intelligence_contract"]["report_sha256"] = hashlib.sha256(report.encode()).hexdigest()
    # Exercise the supported larger role budget so report findings survive the
    # compiler's documented category compaction, instead of testing JSON alone.
    monkeypatch.setenv("SIM_ACTOR_ROLE_PROMPT_MAX_CHARS", "12000")
    manager, state = _prepare(dossier, report=report)
    directory, _ = _config(manager, state)
    profiles = json.loads((directory / "reddit_profiles.json").read_text())
    assert "LATE_RELEVANT_CONTEXT" in profiles[0]["persona"]
    manifest, packs = validate_actor_context_artifacts(str(directory))
    assert manifest["report_sha256"] == dossier["actor_intelligence_contract"]["report_sha256"]
    alpha = packs["actor_alpha"]
    assert "omitted_paragraph_count" in alpha["relevant_sections"][0]
    assert alpha["relevant_sections"][0]["selection_mode"] == "relevance_selected_paragraphs"
    assert alpha["bounded_context_chars"] <= alpha["bounded_context_max_chars"]
