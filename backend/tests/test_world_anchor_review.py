"""Coordinator review regressions over real preparation and native report inputs."""
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from app.services import world_anchor as host, target_report
from app.services.official_data import read_bound_research_core
from app.services.simulation_manager import validate_simulation_config_seal
from test_world_anchor_lifecycle import wired as _wired, target_case as _target_case
from test_world_anchor_records import native_target as _native_target

wired = _wired
target_case = _target_case
native_target = _native_target


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True))


@pytest.mark.parametrize("reader", ["seal", "runtime"])
def test_preparation_rejects_self_consistent_replacement_research(wired, reader):
    directory = wired["directory"]
    manifest = directory / "simulation_config_manifest.json"
    before = manifest.read_bytes()
    assert validate_simulation_config_seal(str(directory), require=True)
    assert host.load_runtime_anchor(wired["config"], directory)
    report = wired["handoff"] / "research_report.md"
    report.write_text(report.read_text() + "\nA replacement after preparation.")
    binding_path = directory / "official_research_binding.json"
    binding = json.loads(binding_path.read_text())
    binding["files"]["research_report.md"] = hashlib.sha256(report.read_bytes()).hexdigest()
    _write(binding_path, binding)
    assert read_bound_research_core("sim_anchor")["status"] == "valid"
    with pytest.raises(ValueError):
        if reader == "seal":
            validate_simulation_config_seal(str(directory), require=True)
        else:
            host.load_runtime_anchor(wired["config"], directory)
    assert manifest.read_bytes() == before


def test_preparation_content_identity_survives_supported_source_relocation(wired):
    directory, original = wired["directory"], wired["handoff"]
    moved = original.parent / "relocated-handoff"
    shutil.copytree(original, moved)
    binding_path = directory / "official_research_binding.json"
    binding = json.loads(binding_path.read_text())
    # Schema 2 accepts a fixed absolute location or a pipelines-root-relative
    # location. Only the locator changes; every retained source byte is equal.
    binding["handoff_dir"] = str(moved)
    _write(binding_path, binding)
    assert read_bound_research_core("sim_anchor")["status"] == "valid"
    assert validate_simulation_config_seal(str(directory), require=True)
    assert host.load_runtime_anchor(wired["config"], directory).pack_hash == wired["context"].pack_hash


def test_consumed_research_must_match_seal_even_if_replaced_after_validation(wired, monkeypatch):
    from app.services import simulation_manager
    original = simulation_manager.validate_simulation_config_seal

    def replace_after_validation(*args, **kwargs):
        manifest = original(*args, **kwargs)
        report = wired["handoff"] / "research_report.md"
        report.write_text(report.read_text() + "\nChanged after the preparation-seal check.")
        path = wired["directory"] / "official_research_binding.json"
        binding = json.loads(path.read_text())
        binding["files"]["research_report.md"] = hashlib.sha256(report.read_bytes()).hexdigest()
        _write(path, binding)
        return manifest

    monkeypatch.setattr(simulation_manager, "validate_simulation_config_seal", replace_after_validation)
    with pytest.raises(host.WorldAnchorIntegrationError):
        host.load_runtime_anchor(wired["config"], wired["directory"])


def test_historical_off_target_report_does_not_require_pipeline_state_or_publication(native_target, monkeypatch):
    from app.services.pipeline_orchestrator import PipelineManager
    from app.services.target_simulation import run_paths
    case = native_target["case"]
    result = run_paths(case, paths=1, periods=1, seed=7, identity_mode="named",
        decision_provider=lambda obs: [])
    before = target_report.build_target_report(case, result)
    directory = native_target["directory"]
    inputs = json.loads((directory / "target_input.json").read_text())
    inputs.pop("worldAnchor")
    _write(directory / "target_input.json", inputs)
    _write(directory / "target_simulation.json", result)
    Path(PipelineManager.state_path(native_target["pipeline_state"].pipeline_id)).unlink()
    monkeypatch.setattr(host, "_publication", lambda: pytest.fail("off report acquired anchor publication"))
    after = target_report.build_target_report(case, result, simulation_dir=directory)
    assert target_report.canonical_json(after) == target_report.canonical_json(before)


def test_target_missing_owner_with_remaining_enabled_result_is_not_off(native_target):
    from app.services.pipeline_orchestrator import PipelineManager
    directory = native_target["directory"]
    inputs = json.loads((directory / "target_input.json").read_text())
    inputs.pop("worldAnchor")
    _write(directory / "target_input.json", inputs)
    assert "worldAnchor" in native_target["result"]
    Path(PipelineManager.state_path(native_target["pipeline_state"].pipeline_id)).unlink()
    with pytest.raises(host.WorldAnchorIntegrationError):
        host.load_target_anchor(directory)


def test_target_off_owner_with_remaining_enabled_result_is_not_off(native_target):
    from app.services.pipeline_orchestrator import PipelineManager
    directory = native_target["directory"]
    inputs = json.loads((directory / "target_input.json").read_text())
    inputs.pop("worldAnchor")
    _write(directory / "target_input.json", inputs)
    state = native_target["pipeline_state"]
    state.options.pop("world_anchor")
    state.options.pop("world_anchor_lifecycle")
    PipelineManager.save(state)
    assert "worldAnchor" in native_target["result"]
    with pytest.raises(host.WorldAnchorIntegrationError):
        host.load_target_anchor(directory)
