"""Actual publication, outside config seals, source binding and runtime loading."""
import asyncio
from copy import deepcopy
import hashlib
import json

import pytest

from app.services import world_anchor as host
from app.services.official_data import bind_simulation_research, bridge_module
from app.services.simulation_manager import SimulationManager, build_simulation_config_seal
from test_target_simulation import case as _target_case
from test_world_anchor_reflexive import _anchored_fixture, _anchor_config

target_case = _target_case


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")


@pytest.fixture
def wired(tmp_path, monkeypatch, target_case):
    from app.config import Config
    (tmp_path / "fixture").mkdir()
    original, case = _anchored_fixture(tmp_path / "fixture", target_case, temporal=False)
    pub = bridge_module("world_anchor_publication")
    # The fixture uses genuine issued receipt handles, never model JSON as proof.
    receipts = {h.manifest_hash: h for h in original.index._review_pins.values()}
    pipelines = tmp_path / "pipelines"
    handoff = pipelines / "pipe_anchor" / "handoff"
    result = pub.publish_completion(handoff, original.pack, requirements=original.requirements,
        index=original.index, policy=original.policy, receipts=tuple(receipts.values()))
    context = host.load_research_anchor(handoff, expected_manifest_sha256=result["manifest_sha256"])
    sims = tmp_path / "simulations"
    directory = sims / "sim_anchor"
    directory.mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sims))
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(pipelines))
    (directory / "actor_cast_manifest.json").write_bytes(original._cast_bytes)
    context = host.bind_actor_cast(context, directory)
    config = _anchor_config(monkeypatch, context, case).to_dict()
    config["simulation_id"] = "sim_anchor"
    _write(directory / "simulation_config.json", config)
    for name, content in {"research_report.md": "Synthetic complete research source.",
                          "actors.json": '{"actors":[]}', "sources.json": "[]",
                          "actor_dossier.md": "Synthetic source-bound actor registry."}.items():
        (handoff / name).write_text(content)
    bind_simulation_research("sim_anchor", handoff, pipeline_id=context.pack["scope"]["run_id"])
    config_sha, manifest_sha = build_simulation_config_seal(str(directory), simulation_id="sim_anchor",
        actor_cast_manifest_sha256=hashlib.sha256(original._cast_bytes).hexdigest(),
        actor_context_manifest_sha256=None, actor_role_manifest_sha256={})
    _write(directory / "state.json", {"simulation_id": "sim_anchor", "simulation_engine": "oasis-legacy",
        "simulation_config_sha256": config_sha, "simulation_config_manifest_sha256": manifest_sha})
    return {"context": context, "directory": directory, "handoff": handoff,
            "config": config, "publication": result}


def test_off_loader_has_no_disk_bridge_or_environment_side_effect(tmp_path, monkeypatch):
    monkeypatch.setenv("SIM_WORLD_ANCHOR", "true")
    monkeypatch.setattr(host, "_api", lambda: pytest.fail("off mode imported the anchor API"))
    monkeypatch.setattr(host, "_publication", lambda: pytest.fail("off mode read publication files"))
    assert host.load_runtime_anchor({}, tmp_path / "absent") is None


def test_raw_json_cannot_impersonate_host_context():
    with pytest.raises(host.WorldAnchorIntegrationError, match="invalid_anchor_context"):
        host.engine_projection({"pack_hash": "a" * 64}, engine="oasis-legacy")


def test_real_external_loader_reconstructs_provenance_and_one_to_one_join(wired):
    loaded = host.load_runtime_anchor(wired["config"], wired["directory"])
    assert loaded.pack_hash == wired["context"].pack_hash
    assert loaded.index is not wired["context"].index
    assert host.actor_ref_for(loaded, "entity-1") == "acme"
    assert host.anchor_config_pin(loaded) == wired["config"]["world_anchor"]
    assert loaded.pack["metering"]["physical_model_attempts"] == 0


@pytest.mark.parametrize("tamper", ["config_argument", "config_and_new_seal", "join", "source_page",
                                    "producer_response", "source_binding"])
def test_runtime_refuses_mutation_without_reconstruction_or_mutable_fallback(wired, tamper):
    directory, handoff = wired["directory"], wired["handoff"]
    config = deepcopy(wired["config"])
    if tamper == "config_argument":
        config["world_anchor"]["pack_hash"] = "b" * 64
    elif tamper == "config_and_new_seal":
        config["world_anchor"]["pack_hash"] = "b" * 64
        _write(directory / "simulation_config.json", config)
        build_simulation_config_seal(str(directory), simulation_id="sim_anchor",
            actor_cast_manifest_sha256=None, actor_context_manifest_sha256=None,
            actor_role_manifest_sha256={})
    elif tamper == "join":
        path = directory / "world_anchor_join.json"
        data = json.loads(path.read_text())
        data["rows"][0]["entity_uuid"] = "foreign-entity"
        _write(path, data)
    elif tamper == "source_page":
        path = handoff / "world_anchor_inputs/v3/pages/page.txt"
        path.write_text(path.read_text().replace("247.5", "248.5"))
    elif tamper == "producer_response":
        path = next((handoff / "world_anchor_producers").rglob("review-response.json"))
        _write(path, {"decisions": []})
    else:
        (directory / "official_research_binding.json").unlink()
    with pytest.raises(host.WorldAnchorIntegrationError):
        host.load_runtime_anchor(config, directory)


def test_actual_reflexive_coordinator_uses_real_published_loader(wired, monkeypatch):
    from test_world_model_loop import _patch_world, _WorldLLM, rps
    _patch_world(monkeypatch, str(wired["directory"]), [])
    coordinator = rps._ReflexiveWorldCoordinator(wired["config"], str(wired["directory"]), 1, lambda _: None)
    coordinator._brief = "DENIED_PRIVATE_CACHE"
    period = wired["config"]["temporal_config"]["round_dates"][0]

    async def decide():
        await coordinator.begin_round("twitter", 0, period)
        return await coordinator.decide("twitter", 0, period, [0], lambda _: "DENIED_OLD_ROLE", [])

    assert asyncio.run(decide())[0].ok
    calls = [call for call in _WorldLLM.calls if call["kind"] == "decision"]
    assert calls and "ACTOR_KNOWN_EXPANSION" in json.dumps(calls)
    assert "DENIED_" not in json.dumps(calls)
    coordinator._write_world_state()
    restored = rps._ReflexiveWorldCoordinator(wired["config"], str(wired["directory"]), 1, lambda _: None)
    assert restored.world.to_dict() == coordinator.world.to_dict()


def test_completion_is_immutable_and_loose_pack_is_not_authority(wired):
    pub = bridge_module("world_anchor_publication")
    handoff = wired["handoff"]
    manifest = handoff / pub.MANIFEST
    manifest.unlink()
    with pytest.raises(host.WorldAnchorIntegrationError):
        host.load_runtime_anchor(wired["config"], wired["directory"])
    assert (handoff / "world_anchor.json").exists()
