"""Main's preparation/task authority composes with actual World Anchor producers.

Only graph/model responses are scripted. Admission, preparation, actor joins,
C5 classification, config seals and native fork/reload use production code.
"""
import hashlib
import json
from pathlib import Path
import sys

import pytest

from app.config import Config
from app.services import official_data
from app.services.actor_context import build_anchor_actor_payload
from app.services.forecast_task import KEY, validate_task_calendar
from app.services.preparation_adapter import load_config_preparation
from app.services.simulation_manager import SimulationManager, SimulationStatus, validate_simulation_config_seal
from tests import test_context_audit_prepare as preparation_cases
import test_target_simulation as target_cases
from test_world_anchor_reflexive import _anchored_fixture


prepare_env = preparation_cases.prepare_env
target_case = target_cases.case
QUESTION = "Will the target grow by 2027-12-31?"
REPORT = "# Acme\nAcme is a firm in the source registry. Its baseline is conditional.\n"


@pytest.fixture(autouse=True)
def record_merged_sources():
    guard = sys.modules.get("main_offline_guard")
    if guard:
        root = Path(__file__).resolve().parents[1] / "app/services"
        for name in ("simulation_manager", "simulation_config_generator", "actor_context",
                     "preparation_adapter", "research_preparation", "forecast_task", "world_anchor",
                     "official_data", "agency_classification", "world_model_seed", "world_model",
                     "world_simulation/service", "world_simulation/compiler", "world_simulation/artifacts",
                     "world_simulation/contracts"):
            path = root / (name + ".py")
            guard.source_hashes.setdefault(str(path), hashlib.sha256(path.read_bytes()).hexdigest())


def _files(directory):
    return {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in directory.rglob("*") if path.is_file() and path.name != "state.json"}


def _prepare(tmp_path, monkeypatch, target_case, *, anchored=True, explicit_none=False):
    monkeypatch.setattr(Config, "SIM_WORLD_MODEL", True)
    monkeypatch.setattr(Config, "SIM_AGENCY_CLASS_SOURCE", "ontology")
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))
    actors = {"as_of_date": "2026-10-27", "forecast_horizon": "2027-12-31",
              "central_question": QUESTION, "actors": [{"name": "Acme", "type": "Organization",
                  "role": "Source registry firm", "simulation_tier": 1}]}
    ontology = {"entity_types": [{"name": "Organization", "agency_class": "firm", "examples": ["Acme"]}]}
    context = case = None
    if anchored:
        import test_world_anchor as anchor_cases
        original_scope = anchor_cases.scope
        with monkeypatch.context() as patch:
            patch.setattr(anchor_cases, "scope", lambda: {**original_scope(), "run_id": "pipe_merge"})
            context, case = _anchored_fixture(tmp_path, target_case)
        handoff = tmp_path / "emission"
    else:
        handoff = tmp_path / "handoff"
        handoff.mkdir()
    (handoff / "research_report.md").write_text(REPORT)
    (handoff / "actors.json").write_text(json.dumps(actors))
    (handoff / "sources.json").write_text("[]")
    (handoff / "actor_dossier.md").write_text("Acme is the source registry firm.")
    manager = SimulationManager()
    created = manager.create_simulation("merge-project", "merge-graph")
    from app.services.pipeline_orchestrator import PipelineManager, PipelineState
    owner = PipelineState(pipeline_id="pipe_merge", prompt=QUESTION,
        project_id=created.project_id, simulation_id=created.simulation_id, handoff_dir=str(handoff))
    PipelineManager.save(owner)
    official_data.bind_simulation_research(created.simulation_id, handoff, pipeline_id="pipe_merge")
    options = ({"anchor_context": context, "forecast_case": case} if anchored or explicit_none else {})
    state = manager.prepare_simulation(created.simulation_id, QUESTION, REPORT, actors=actors,
        ontology=ontology, use_llm_for_profiles=False, research_language="English", max_rounds=4, **options)
    assert state.status == SimulationStatus.READY, state.error
    directory = Path(manager.SIMULATION_DATA_DIR) / state.simulation_id
    config = json.loads((directory / "simulation_config.json").read_text())
    return manager, state, actors, ontology, context, case, directory, handoff, config


def test_actual_prepare_keeps_task_research_c5_join_and_anchor_seals(
        prepare_env, tmp_path, monkeypatch, target_case):
    manager, state, actors, ontology, context, case, directory, handoff, config = _prepare(
        tmp_path, monkeypatch, target_case)
    task = validate_task_calendar(config)
    assert task == config[KEY] and task["horizon_date"] == "2027-12-31"
    preparation = load_config_preparation(directory, config)
    assert preparation["source"]["source_binding"]["kind"] == "bound_research"
    assert config["research_preparation"]["content_sha256"] == preparation["content_sha256"]
    manifest = validate_simulation_config_seal(str(directory), require=True)
    assert set(manifest["bindings"]["research_preparation"]) == {
        "research_preparation.json", "research_preparation_manifest.json"}
    assert manifest["bindings"]["world_anchor"]["research_identity"]["files"] == official_data.read_bound_research_core(
        state.simulation_id)["files"]
    join = json.loads((directory / "world_anchor_join.json").read_text())
    cast = json.loads((directory / "actor_cast_manifest.json").read_text())
    assert len(join["rows"]) == 1
    entity_uuid = config["agent_configs"][0]["entity_uuid"]
    assert join["rows"][0]["entity_uuid"] == entity_uuid
    assert cast["agency_classifications"][entity_uuid]["agency_class"] == "firm"
    assert config["agent_configs"][0]["agency_class"] == config["world_model"]["actors"][0]["agency_class"] == "firm"
    from app.services.world_anchor import bind_actor_cast
    joined = bind_actor_cast(context, directory)
    payload = build_anchor_actor_payload(joined, entity_uuid=entity_uuid, at="2026-10-28T00:00:00Z")
    assert "ACTOR_KNOWN_EXPANSION" in json.dumps(payload)
    assert "DENIED_ANALYST" not in json.dumps(payload)
    assert config["world_model"]["state_variables"][0]["id"] == "target"
    manager.validate_prepared_simulation_config(state.simulation_id)


@pytest.mark.parametrize("explicit_none", [False, True])
def test_unanchored_prepare_keeps_main_authority_without_anchor_artifacts(
        prepare_env, tmp_path, monkeypatch, target_case, explicit_none):
    manager, state, _, _, _, _, directory, _, config = _prepare(
        tmp_path, monkeypatch, target_case, anchored=False, explicit_none=explicit_none)
    assert validate_task_calendar(config) == config[KEY]
    assert load_config_preparation(directory, config)["source"]["source_binding"]["kind"] == "bound_research"
    assert "world_anchor" not in config
    assert not (directory / "world_anchor_join.json").exists()
    assert "world_anchor" not in validate_simulation_config_seal(str(directory), require=True)["bindings"]
    manager.validate_prepared_simulation_config(state.simulation_id)


def test_rejected_anchor_reprepare_revokes_without_replacing_preparation_or_join(
        prepare_env, tmp_path, monkeypatch, target_case):
    manager, state, actors, ontology, context, case, directory, _, config = _prepare(
        tmp_path, monkeypatch, target_case)
    before = _files(directory)
    with pytest.raises(ValueError, match="differ"):
        manager.prepare_simulation(state.simulation_id, QUESTION, REPORT + "Changed report.", actors=actors,
            ontology=ontology, anchor_context=context, forecast_case=case, use_llm_for_profiles=False)
    rejected = manager.get_simulation(state.simulation_id)
    assert rejected.status == SimulationStatus.FAILED and rejected.config_generated is False
    assert _files(directory) == before
    with pytest.raises(ValueError, match="revoked|not completed"):
        manager.validate_prepared_simulation_config(state.simulation_id)


@pytest.mark.parametrize("mutation", ["preparation", "anchor_join", "research_generation"])
def test_combined_config_seal_rejects_each_independent_authority_change(
        prepare_env, tmp_path, monkeypatch, target_case, mutation):
    manager, state, _, _, _, _, directory, handoff, config = _prepare(tmp_path, monkeypatch, target_case)
    if mutation == "preparation":
        path = directory / "research_preparation.json"
        path.write_bytes(path.read_bytes() + b" ")
    elif mutation == "anchor_join":
        path = directory / "world_anchor_join.json"
        path.write_bytes(path.read_bytes() + b" ")
    else:
        (handoff / "research_report.md").write_text(REPORT + "A replacement generation.")
        with pytest.raises(official_data.ResearchBindingConflict):
            official_data.bind_simulation_research(state.simulation_id, handoff, pipeline_id="pipe_merge")
        # An attacker can edit both mutable files; the earlier config seal must
        # still reject a self-consistent replacement research generation.
        binding_path = directory / "official_research_binding.json"
        binding = json.loads(binding_path.read_text())
        binding["files"]["research_report.md"] = hashlib.sha256((handoff / "research_report.md").read_bytes()).hexdigest()
        binding_path.write_text(json.dumps(binding))
        assert official_data.read_bound_research_core(state.simulation_id)["status"] == "valid"
    with pytest.raises(ValueError):
        validate_simulation_config_seal(str(directory), require=True)


def test_native_prepare_and_fork_preserve_both_source_authorities(tmp_path, monkeypatch):
    from test_world_anchor_world_v1 import _fixture, _public_prepare
    from app.services.world_simulation.artifacts import load_inputs, load_preparation
    fixture = _fixture(tmp_path)
    manager, state, directory = _public_prepare(fixture, tmp_path, monkeypatch)
    spec, _ = load_inputs(directory)
    preparation = load_preparation(directory, spec)
    assert preparation is not None
    assert spec["sourceBindings"]["worldAnchor"]["pin"]["pack_hash"] == fixture.context.pack_hash
    assert spec["sourceBindings"]["preparationContext"]["contentSha256"] == preparation["content_sha256"]
    originals = _files(directory)
    child = manager.fork_world_simulation(state.simulation_id, seed=17)
    child_directory = Path(manager.SIMULATION_DATA_DIR) / child.simulation_id
    child_spec, _ = load_inputs(child_directory)
    assert load_preparation(child_directory, child_spec) == preparation
    for key in ("pin", "consumedSources", "researchGenerationId", "anchorResearchGenerationId"):
        assert child_spec["sourceBindings"]["worldAnchor"][key] == spec["sourceBindings"]["worldAnchor"][key]
    assert child_spec["seed"] == 17
    assert child_spec["generationId"] != spec["generationId"]
    assert official_data.simulation_research_binding(child.simulation_id)["status"] == "valid"
    SimulationManager().validate_prepared_simulation_config(child.simulation_id)
    assert _files(directory) == originals


def test_invalid_anchor_is_rejected_before_new_task_model_dispatch(prepare_env, tmp_path):
    manager = SimulationManager()
    state = manager.create_simulation("merge-project", "merge-graph")
    directory = Path(manager.SIMULATION_DATA_DIR) / state.simulation_id
    before = _files(directory)
    with pytest.raises(ValueError, match="invalid_anchor_context"):
        manager.prepare_simulation(state.simulation_id, QUESTION, REPORT,
            actors={"as_of_date": "2026-10-27", "actors": [{"name": "Acme", "type": "Organization"}]},
            anchor_context={}, use_llm_for_profiles=False)
    assert prepare_env == []
    assert _files(directory) == before
