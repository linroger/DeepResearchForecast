"""Authentic anchor cast admission must precede task-model dispatch.

Only external graph/model responses are scripted. The anchor publication/reload,
research binding, selected cast, task admission and both seals remain real.
"""
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from app.config import Config
from app.services import official_data, world_anchor
from app.services.forecast_task import KEY, validate_task_calendar
from app.services.pipeline_orchestrator import PipelineManager, PipelineState
from app.services.preparation_adapter import load_config_preparation
from app.services.simulation_manager import SimulationManager, SimulationStatus, validate_simulation_config_seal
from tests import test_context_audit_prepare as preparation_cases
import test_target_simulation as target_cases
import test_world_anchor as anchor_cases
import test_world_anchor_reflexive as reflexive_cases


prepare_env = preparation_cases.prepare_env
target_case = target_cases.case
QUESTION = "Will the target grow by 2027-12-31?"
PIPELINE_ID = "pipe_cast_preflight"


@pytest.fixture(autouse=True)
def pin_producers_and_consumers():
    guard = sys.modules.get("main_offline_guard")
    if guard is not None:
        repo = Path(__file__).resolve().parents[2]
        paths = [*sorted((repo / "backend/app").rglob("*.py")),
                 *sorted((repo / "deerflow_bridge").glob("*.py")), Path(__file__),
                 *[Path(module.__file__) for module in
                   (preparation_cases, target_cases, anchor_cases, reflexive_cases)]]
        for path in paths:
            guard.source_hashes.setdefault(str(path), hashlib.sha256(path.read_bytes()).hexdigest())


def _source_bound_request(tmp_path, monkeypatch, target_case, *, actor_name):
    monkeypatch.setattr(Config, "SIM_TEMPORAL_MODE", "calendar")
    monkeypatch.setattr(Config, "SIM_WORLD_MODEL", True)
    monkeypatch.setattr(Config, "SIM_AGENCY_CLASS_SOURCE", "ontology")
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))
    original_scope = anchor_cases.scope
    with monkeypatch.context() as patch:
        patch.setattr(anchor_cases, "scope", lambda: {**original_scope(), "run_id": PIPELINE_ID})
        issued_context, case = reflexive_cases._anchored_fixture(tmp_path, target_case)
    handoff = tmp_path / "emission"
    # Reopen the authentic completion without the helper's separate dummy cast.
    # The manager must establish the actual selected actor join itself.
    context = world_anchor.load_research_anchor(handoff,
        expected_manifest_sha256=issued_context.research_manifest_hash)
    assert context.join is None
    assert world_anchor.validate_anchor_context(context, engine="oasis-legacy") is context
    actors = {"as_of_date": "2026-10-27", "forecast_horizon": "2027-12-31",
        "central_question": QUESTION, "actors": [{"name": actor_name, "type": "Organization",
            "role": "Selected source actor", "simulation_tier": 1}]}
    report = f"# {actor_name}\n{actor_name} is the actor selected by this research generation.\n"
    ontology = {"entity_types": [{"name": "Organization", "agency_class": "firm", "examples": [actor_name]}]}
    (handoff / "research_report.md").write_text(report)
    (handoff / "actors.json").write_text(json.dumps(actors))
    (handoff / "sources.json").write_text("[]")
    (handoff / "actor_dossier.md").write_text(report)
    manager = SimulationManager()
    created = manager.create_simulation("cast-project", "cast-graph")
    PipelineManager.save(PipelineState(pipeline_id=PIPELINE_ID, prompt=QUESTION,
        project_id=created.project_id, simulation_id=created.simulation_id, handoff_dir=str(handoff)))
    official_data.bind_simulation_research(created.simulation_id, handoff, pipeline_id=PIPELINE_ID)
    assert official_data.simulation_research_binding(created.simulation_id)["status"] == "valid"
    return SimpleNamespace(manager=manager, simulation_id=created.simulation_id,
        directory=Path(manager.SIMULATION_DATA_DIR) / created.simulation_id,
        context=context, arguments={"simulation_id": created.simulation_id,
            "simulation_requirement": QUESTION, "document_text": report, "actors": actors,
            "ontology": ontology, "anchor_context": context, "forecast_case": case,
            "use_llm_for_profiles": False, "research_language": "English", "max_rounds": 4})


def _task_phases(calls):
    phases = []
    for messages in calls:
        prompt = messages[-1]["content"]
        if prompt.startswith(("FORECAST TASK EXTRACTION\n", "FORECAST TASK REVIEW\n")):
            phases.append(prompt.split("\n", 1)[0])
    return phases


def test_authentic_ready_anchor_rejects_incompatible_selected_cast_before_any_model_call(
        prepare_env, tmp_path, monkeypatch, target_case):
    request = _source_bound_request(tmp_path, monkeypatch, target_case, actor_name="Unregistered Vendor")
    assert prepare_env == []
    with pytest.raises(world_anchor.WorldAnchorIntegrationError) as error:
        request.manager.prepare_simulation(**request.arguments)
    assert error.value.code == "invalid_anchor_join"
    rejected = request.manager.get_simulation(request.simulation_id)
    assert rejected.status == SimulationStatus.FAILED and rejected.config_generated is False
    assert not (request.directory / "simulation_config.json").exists()
    assert prepare_env == [], (
        "A deterministic selected-cast rejection dispatched model calls: "
        f"task phases={_task_phases(prepare_env)}, total calls={len(prepare_env)}")


def test_authentic_ready_anchor_valid_cast_still_reviews_task_and_seals_both_authorities(
        prepare_env, tmp_path, monkeypatch, target_case):
    request = _source_bound_request(tmp_path, monkeypatch, target_case, actor_name="Acme")
    assert prepare_env == []
    ready = request.manager.prepare_simulation(**request.arguments)
    assert ready.status == SimulationStatus.READY and ready.config_generated is True
    assert _task_phases(prepare_env) == ["FORECAST TASK EXTRACTION", "FORECAST TASK REVIEW"]
    config = json.loads((request.directory / "simulation_config.json").read_text())
    assert validate_task_calendar(config) == config[KEY]
    preparation = load_config_preparation(request.directory, config)
    assert config["research_preparation"]["content_sha256"] == preparation["content_sha256"]
    assert config["world_anchor"]["pack_hash"] == request.context.pack_hash
    manifest = validate_simulation_config_seal(str(request.directory), require=True)
    assert {"research_preparation", "world_anchor"} <= manifest["bindings"].keys()
    cast = json.loads((request.directory / "actor_cast_manifest.json").read_text())
    join = json.loads((request.directory / "world_anchor_join.json").read_text())
    selected = [row for row in cast["decisions"] if row["status"] == "selected"]
    assert len(selected) == len(join["rows"]) == 1
    entity_uuid = selected[0]["entity_uuid"]
    assert selected[0]["actor_name"] == "Acme"
    assert join["rows"][0]["entity_uuid"] == entity_uuid
    assert cast["agency_classifications"][entity_uuid]["agency_class"] == "firm"
    request.manager.validate_prepared_simulation_config(request.simulation_id)
