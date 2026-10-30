"""Combined prepared research and anchor authority through real native consumers."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

from app.config import Config
from app.services import world_anchor as host
from app.services.official_data import bind_simulation_research
from app.services.research_preparation import compile_preparation_context
from app.services.simulation_manager import SimulationManager
from app.services.world_simulation import compiler, modeler, service
from app.services.world_simulation.artifacts import load_inputs, seal_inputs
from app.services.world_simulation.contracts import WorldError, canonical_json, initial_snapshot
from app.services.world_simulation.observations import build_observation
from app.services.world_simulation.store import WorldStore
from tests import test_world_anchor_world_v1 as anchored
from tests import test_world_preparation_context as grounded
from tests.test_world_modeler_repair import Scripted, policy_spec

pytestmark = pytest.mark.guarded_runner
GENERATION = "final-report-consumed-hash"


@pytest.fixture(autouse=True)
def private_roots_and_source_pins(tmp_path, monkeypatch):
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path / "simulations"))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path / "simulations"))
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))
    guard = sys.modules.get("main_offline_guard")
    if guard is not None:
        repo = Path(__file__).resolve().parents[2]
        paths = [*sorted((repo / "backend/app").rglob("*.py")),
                 *sorted((repo / "deerflow_bridge").glob("*.py")), Path(__file__),
                 Path(anchored.__file__), Path(grounded.__file__),
                 repo / "backend/scripts/main_offline_pytest.py"]
        for path in paths:
            guard.source_hashes.setdefault(str(path), hashlib.sha256(path.read_bytes()).hexdigest())


def combined(tmp_path, **kwargs):
    f = anchored._fixture(tmp_path, **kwargs)
    official = grounded.official_data()
    row = official["series"][0]
    row["retrieved_at"] = "2026-10-20T12:00:00Z"
    for observation, date in zip(row["observations"], ("2026-04-01", "2026-07-01", "2027-01-01")):
        observation["date"] = date
    prepared = compile_preparation_context(
        question="Study the admitted spending baseline and a separate output scenario.",
        research_report=f.report, actors=f.bundle, official_data=official,
        source_binding={"research_generation_id": GENERATION}, as_of="2026-10-27")
    observation = prepared["quantitative"]["observations"][0]
    f.raw["initialState"]["metrics"]["output"] = {
        "kind": "quantity", "unit": observation["unit"], "value": str(observation["value"]),
        "basis": grounded.reference(prepared), "visibility": {"kind": "public"}}
    f.raw["scheduledEvents"] = [{"eventId": "output_scenario", "kind": "metric_delta",
        "at": "2026-10-28T12:00:00Z", "parameters": {"targetMetric": "output", "delta": "3"},
        "basis": deepcopy(anchored.world_cases.ASSUMPTION), "visibility": {"kind": "public"}}]
    return f, prepared


def arguments(f, prepared):
    return {"research_report": f.report, "research_generation_id": GENERATION,
            "research_engine": "v3", "actor_bundle": f.bundle,
            "preparation_context": prepared, "anchor_context": f.context}


def public_prepare(f, prepared):
    manager = SimulationManager()
    state = manager.create_simulation("merge-project", "merge-graph", simulation_engine="world-v1")
    bind_simulation_research(state.simulation_id, f.handoff, pipeline_id="run-test")
    state = manager.prepare_world_simulation(state.simulation_id, raw_spec=f.raw, **arguments(f, prepared))
    return manager, state, Path(manager.SIMULATION_DATA_DIR) / state.simulation_id


def test_combined_compile_seal_reload_requires_both_exact_authorities(tmp_path):
    f, prepared = combined(tmp_path)
    spec = anchored._compile(f, preparation_context=prepared)
    original = deepcopy(spec)
    manifest = seal_inputs(tmp_path / "sealed", spec, **{
        "preparation_context": prepared, "anchor_context": f.context})
    loaded, _ = load_inputs(tmp_path / "sealed", anchor_context=f.context)
    assert canonical_json(loaded) == canonical_json(original)
    assert compiler.anchor_preparation_bytes(loaded) == compiler.anchor_preparation_bytes(spec)
    assert manifest["sourceBindings"]["preparationContext"]["contentSha256"] == prepared["content_sha256"]
    assert manifest["worldAnchor"]["pack_hash"] == f.context.pack_hash
    assert loaded["initialState"]["metrics"]["output"]["baseline"]["observation"]["value"] == "30000.25"
    assert loaded["initialState"]["metrics"]["baseline"]["value"] == "247.5"
    assert json.loads(compiler.anchor_preparation_bytes(loaded))["inputs"]["preparation_context"] == prepared


@pytest.mark.parametrize("mutation", ["plain_json", "official_value", "research_projection", "anchor_parameter"])
def test_compiled_receipt_cannot_authorize_mutated_combined_derivative(tmp_path, mutation):
    f, prepared = combined(tmp_path)
    spec = anchored._compile(f, preparation_context=prepared)
    if mutation == "plain_json":
        spec = json.loads(canonical_json(spec))
    elif mutation == "official_value":
        spec["initialState"]["metrics"]["output"]["value"] = "1"
    elif mutation == "research_projection":
        spec["researchContext"]["actors"]["a"] = "Unauthorized replacement context."
    else:
        spec["initialState"]["metrics"]["baseline"]["value"] = "248.5"
    with pytest.raises(WorldError) as error:
        seal_inputs(tmp_path / "forged", spec, preparation_context=prepared, anchor_context=f.context)
    assert error.value.code == "anchor_binding_mismatch"
    assert not (tmp_path / "forged/world_spec.json").exists()


@pytest.mark.parametrize("artifact", ["research_preparation.json", "research_preparation_manifest.json",
                                      "world_anchor_preparation.json"])
def test_combined_reload_requires_each_independent_proof(tmp_path, artifact):
    f, prepared = combined(tmp_path)
    spec = anchored._compile(f, preparation_context=prepared)
    seal_inputs(tmp_path / "sealed", spec, preparation_context=prepared, anchor_context=f.context)
    (tmp_path / "sealed" / artifact).unlink()
    with pytest.raises(WorldError) as error:
        load_inputs(tmp_path / "sealed", anchor_context=f.context)
    expected = "anchor_binding_mismatch" if artifact.startswith("world_anchor") else "invalid_preparation_context"
    assert error.value.code == expected


def test_combined_public_manager_runtime_result_replay_and_native_fork(tmp_path):
    f, prepared = combined(tmp_path)
    manager, state, directory = public_prepare(f, prepared)
    policy = anchored._Policy()
    assert service.run_child(directory, policy=policy) == 0
    assert len(policy.observations) == 2
    first, second = policy.observations
    assert first["world"]["metrics"]["baseline"]["value"] == "247.5"
    assert "output" not in first["world"]["metrics"]
    assert second["world"]["metrics"]["output"]["value"] == "30003.25"
    assert second["world"]["metrics"]["output"]["evidenceType"] == "simulated"
    for observation in policy.observations:
        text = canonical_json(observation)
        assert "researchContext" not in observation["actor"]
        assert "PRIVATE_SELF_INFERENCE" not in text and "secret loss" not in text
        assert prepared["content_sha256"] not in text and f.context.pack_hash not in text
        assert "baseline" not in observation["world"]["metrics"].get("output", {})
    result = service.WorldSimulationService.require_complete(state.simulation_id)
    assert result["completed"] and result["world"]["metrics"]["output"]["value"] == "30003.25"
    spec, _ = load_inputs(directory)
    with WorldStore(directory / "world.sqlite3", spec, read_only=True) as store:
        assert store.head()["metrics"]["output"]["baseline"]["observation"]["value"] == "30000.25"
    original_bytes = {p.name: p.read_bytes() for p in directory.glob("*.json")}
    child = manager.fork_world_simulation(state.simulation_id, seed=71)
    child_dir = Path(manager.SIMULATION_DATA_DIR) / child.simulation_id
    loaded, manifest = load_inputs(child_dir)
    assert loaded["seed"] == 71 and loaded["generationId"] != state.world_generation_id
    assert manifest["worldAnchor"]["pack_hash"] == f.context.pack_hash
    assert loaded["sourceBindings"]["preparationContext"] == spec["sourceBindings"]["preparationContext"]
    for name in ("research_preparation.json", "research_preparation_manifest.json"):
        assert (child_dir / name).read_bytes() == (directory / name).read_bytes()
    assert {p.name: p.read_bytes() for p in directory.glob("*.json")} == original_bytes
    SimulationManager().validate_prepared_simulation_config(child.simulation_id)


def test_real_modeler_consumes_both_contexts_and_reuses_only_exact_inputs(tmp_path, monkeypatch):
    from app.services.world_simulation import policy as policy_module

    f, prepared = combined(tmp_path)
    transport = Scripted(f.raw)
    monkeypatch.setattr(policy_module, "StrictHTTPModeler", lambda _: transport)
    result = service.WorldSimulationService.prepare_model("sim_modeler", raw_spec=None,
        root=tmp_path / "simulations", policy_spec=policy_spec(), **arguments(f, prepared))
    assert len(transport.requests) == 1
    body = json.loads(transport.requests[0][1]["content"])
    assert body["preparationContext"]["contentSha256"] == prepared["content_sha256"]
    assert body["worldAnchor"]["pack_hash"] == f.context.pack_hash
    assert "official_observation" in transport.requests[0][0]["content"]
    assert "structuralBasis" in transport.requests[0][0]["content"]
    options = {**arguments(f, prepared), "ontology": None, "simulation_requirement": "", "policy_spec": policy_spec()}
    raw, receipt = modeler.generate_candidate(tmp_path / "simulations/sim_modeler", **options)
    assert receipt == result["spec"]["sourceBindings"]["modelPreparation"]
    assert raw["initialState"]["metrics"]["output"]["basis"] == grounded.reference(prepared)
    assert len(transport.requests) == 1
    changed = compile_preparation_context(question="A different question with the same source generation.",
        research_report=f.report, actors=f.bundle,
        source_binding={"research_generation_id": GENERATION}, as_of="2026-10-27")
    with pytest.raises(WorldError) as error:
        modeler.generate_candidate(tmp_path / "simulations/sim_modeler", **{**options, "preparation_context": changed})
    assert error.value.code == "modeling_binding_mismatch" and len(transport.requests) == 1


def test_prepared_off_path_is_identical_with_explicit_none_and_keeps_official_actor_context(tmp_path, monkeypatch):
    prepared = grounded.bundle()
    raw = grounded.proposal(prepared)
    monkeypatch.setattr(host, "validate_anchor_context", lambda *a, **k: pytest.fail("off path invoked anchor API"))
    spec = grounded.compile_model(raw, prepared)
    explicit = compiler.compile_world_spec(raw, simulation_id="native_fixture", generation_id="world_fixture",
        research_report=grounded.REPORT, research_generation_id="research1", research_engine="v3",
        actor_bundle=grounded.source_bundle(), preparation_context=prepared, anchor_context=None)
    assert canonical_json(spec) == canonical_json(explicit)
    observation = build_observation(spec, initial_snapshot(spec), "a", 1)
    assert observation["actor"]["researchContext"]
    assert observation["world"]["metrics"]["output"]["baseline"]["observation"]["value"] == "30000.25"
    for name, candidate in (("implicit", spec), ("explicit", explicit)):
        seal_inputs(tmp_path / name, candidate, preparation_context=prepared)
    for name in ("world_spec.json", "world_input_manifest.json", "research_preparation.json"):
        assert (tmp_path / "implicit" / name).read_bytes() == (tmp_path / "explicit" / name).read_bytes()


def test_prepared_research_does_not_relax_required_unsupported_anchor_mapping(tmp_path):
    f, prepared = combined(tmp_path, extra_parameters=[{"object": "baseline", "target": "threshold",
        "metric": "unsupported_indicator", "value": "1", "role": "observation"}])
    with pytest.raises(WorldError, match="consumer role") as error:
        anchored._compile(f, preparation_context=prepared)
    assert error.value.code == "modeling_gap"


def test_official_preparation_cannot_replace_a_required_anchor_parameter(tmp_path):
    f, prepared = combined(tmp_path)
    f.raw["initialState"]["metrics"]["baseline"] = deepcopy(f.raw["initialState"]["metrics"]["output"])
    with pytest.raises(WorldError, match="Required anchor parameter") as error:
        anchored._compile(f, preparation_context=prepared)
    assert error.value.code == "modeling_gap"
