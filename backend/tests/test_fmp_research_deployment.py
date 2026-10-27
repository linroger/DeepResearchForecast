"""FMP deployment and parent-owned capture integrity; synthetic offline evidence."""
import hashlib
import json
from pathlib import Path
import sys
import tomllib

import pytest
from packaging.requirements import Requirement

from app.services import official_data as od
from app.services import pipeline_orchestrator as po

pytestmark = pytest.mark.guarded_runner
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module", autouse=True)
def _pin_reviewed_sources():
    guard = sys.modules.get("main_offline_guard")
    assert guard is not None
    for relative in ("backend/app/services/pipeline_orchestrator.py", "backend/app/services/official_data.py",
                     "backend/app/config.py", "backend/pyproject.toml", "backend/requirements.txt", "backend/uv.lock",
                     "deerflow_bridge/config.yaml", "deerflow_bridge/fmp_research.py",
                     "deerflow_bridge/requirements-fmp.txt", "setup.sh"):
        path = REPO / relative
        guard.source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()


def _api():
    return od.bridge_module("fmp_research")


class CapturedClient:
    def __init__(self, value):
        self.value = value

    def sanitize(self, value):
        return value

    def call(self, tool, arguments, **kwargs):
        return {"provider": "fmp", "source_url": _api().ENDPOINT,
                "retrieved_at": "2026-10-27T00:00:00Z", "status": {"state": "ok"},
                "data": {"revenue": self.value, "currency": "USD"}}


def _generation(root, value=1, question="Will revenue grow?"):
    root.mkdir(parents=True, exist_ok=True)
    (root / "research_report.md").write_text("# Research\n" + "Captured vendor evidence [S1]. " * 35)
    (root / "actors.json").write_text('{"actors": []}')
    store = _api().CaptureStore(root, question, env={}, client=CapturedClient(value))
    _, item = store.request("call", {"tool": "financials", "arguments": {"symbol": "TEST"}})
    store.freeze()
    sources = [{"url": item["url"], "title": "Financials", "tier": "S2", **_api().metadata(item)}]
    (root / "sources.json").write_text(json.dumps(sources))
    return store, item, sources


def _all_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_dependency_manifests_and_locked_versions_agree():
    required = {"mcp": ">=1.30.0,<2", "httpx": ">=0.28,<1", "jsonschema": ">=4.20,<5"}
    project = tomllib.loads((REPO / "backend/pyproject.toml").read_text())
    lock = tomllib.loads((REPO / "backend/uv.lock").read_text())
    manifests = [project["project"]["dependencies"]]
    for path in ("backend/requirements.txt", "deerflow_bridge/requirements-fmp.txt"):
        manifests.append([line for line in (REPO / path).read_text().splitlines()
                          if line.strip() and not line.lstrip().startswith("#")])
    packages = {row["name"]: row for row in lock["package"]}
    root = packages["mirofish-backend"]
    metadata = {row["name"]: row.get("specifier") for row in root["metadata"]["requires-dist"]}
    for name, spec in required.items():
        expected = Requirement(name + spec).specifier
        for manifest in manifests:
            rows = [Requirement(row) for row in manifest if Requirement(row).name == name]
            assert len(rows) == 1 and rows[0].specifier == expected
        assert Requirement(name + metadata[name]).specifier == expected
        assert name in {row["name"] for row in root["dependencies"]}
        assert packages[name]["version"] in expected


def test_setup_targets_research_venv_after_sync():
    setup = (REPO / "setup.sh").read_text()
    assert 'cp "$BRIDGE_DIR/requirements-fmp.txt" "$DEERFLOW_DIR/requirements-fmp.txt"' in setup
    install = 'uv pip install --python "$DEERFLOW_DIR/backend/.venv/bin/python"'
    assert setup.index(install) > setup.index('uv sync --project "$DEERFLOW_DIR/backend"')
    assert '-r "$DEERFLOW_DIR/requirements-fmp.txt"' in setup


def test_backend_sync_copies_dependency_manifest_and_modules(tmp_path, monkeypatch):
    from tests.test_deerflow_bridge_sync_guard import _write
    source, target = tmp_path / "deerflow_bridge", tmp_path / "deer-flow"
    _write(source / "deerflow_research.py", "same\n")
    _write(target / "deerflow_research.py", "same\n")
    names = ("fmp_mcp.py", "fmp_research.py", "fmp_tools.py", "requirements-fmp.txt")
    for name in names:
        _write(source / name, "# current " + name)
        _write(target / name, "stale")
    monkeypatch.setattr(po, "__file__", str(tmp_path / "backend/app/services/pipeline_orchestrator.py"))
    po._sync_deerflow_bridge_if_stale(str(target))
    assert all((target / name).read_bytes() == (source / name).read_bytes() for name in names)


def test_uv_fallback_consumes_deployed_requirements(tmp_path, monkeypatch):
    monkeypatch.setattr(po.Config, "DEERFLOW_PYTHON", "")
    manifest = tmp_path / "requirements-fmp.txt"
    manifest.write_text("mcp>=1.30.0,<2\n")
    assert po._detect_deerflow_python(str(tmp_path)) == [
        "uv", "run", "--project", str(tmp_path / "backend"),
        "--with-requirements", str(manifest), "python"]


@pytest.mark.parametrize("location", ["backend/.venv/bin/python", ".venv/bin/python"])
def test_existing_runtime_keeps_fmp_dependency_overlay(tmp_path, monkeypatch, location):
    monkeypatch.setattr(po.Config, "DEERFLOW_PYTHON", "")
    interpreter = tmp_path / location
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("fixture")
    manifest = tmp_path / "requirements-fmp.txt"
    manifest.write_text("mcp>=1.30.0,<2\n")
    command = po._detect_deerflow_python(str(tmp_path))
    assert command[:2] == ["uv", "run"]
    assert command[command.index("--with-requirements") + 1] == str(manifest)
    if location.startswith("backend/"):
        assert "--no-sync" in command
        assert command[command.index("--project") + 1] == str(tmp_path / "backend")
    else:
        assert command[command.index("--python") + 1] == str(interpreter)


def test_explicit_interpreter_override_is_preserved(tmp_path, monkeypatch):
    interpreter = tmp_path / "custom-python"
    interpreter.write_text("fixture")
    monkeypatch.setattr(po.Config, "DEERFLOW_PYTHON", str(interpreter))
    (tmp_path / "requirements-fmp.txt").write_text("mcp>=1.30.0,<2\n")
    assert po._detect_deerflow_python(str(tmp_path)) == [str(interpreter)]


def test_promote_finalize_and_generation_bind_exact_fmp_bytes(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    _, item, _ = _generation(source)
    # Semantically equivalent formatting must be preserved, not regenerated.
    payload = source / item["file"]
    payload.write_text(json.dumps(json.loads(payload.read_bytes()), indent=3) + "\n")
    artifacts = od.fmp_capture_artifacts(source)
    manifest = po._promote_research_contract(str(source), str(target))
    assert po._validate_research_contract(str(target))
    generation = od.capture_research_generation(target)
    for name, raw in artifacts.items():
        assert (target / name).read_bytes() == raw
        digest = hashlib.sha256(raw).hexdigest()
        assert manifest["files"][name] == {"bytes": len(raw), "sha256": digest}
        assert generation["files"][name] == digest
    po._finalize_research_contract(str(target), {"report": "# Final\n" + "Updated prose. " * 50})
    assert od.fmp_capture_artifacts(target) == artifacts
    assert po._validate_research_contract(str(target))


@pytest.mark.parametrize("damage", ["payload", "whitespace", "manifest", "binding", "missing", "extra", "symlink"])
def test_contract_rejects_fmp_capture_damage(tmp_path, damage):
    source, target = tmp_path / "source", tmp_path / "target"
    _, item, _ = _generation(source)
    po._promote_research_contract(str(source), str(target))
    path = target / item["file"]
    if damage == "payload":
        path.write_text("{}")
    elif damage == "whitespace":
        path.write_bytes(path.read_bytes() + b"\n")
    elif damage == "manifest":
        (target / "fmp/captures.json").write_text("{}")
    elif damage == "binding":
        (target / "fmp_research_binding.json").unlink()
    elif damage == "missing":
        path.unlink()
    elif damage == "extra":
        (target / "fmp/extra.json").write_text("{}")
    else:
        path.unlink()
        path.symlink_to(source / item["file"])
    assert not po._validate_research_contract(str(target))


@pytest.mark.parametrize("phase", ["install", "seal"])
def test_failed_promotion_restores_previous_fmp_generation(tmp_path, monkeypatch, phase):
    source, previous, target = tmp_path / "source", tmp_path / "previous", tmp_path / "target"
    _generation(previous, 1)
    _generation(source, 2)
    po._promote_research_contract(str(previous), str(target))
    before = _all_bytes(target)
    if phase == "install":
        replace = po.os.replace
        def fail(src, dst, *args, **kwargs):
            if ".research-stage-" in str(src) and Path(src).name == "fmp":
                raise OSError("synthetic FMP install failure")
            return replace(src, dst, *args, **kwargs)
        monkeypatch.setattr(po.os, "replace", fail)
    else:
        from app.utils import atomic
        write = atomic.write_json_atomic
        def fail(path, value, *args, **kwargs):
            if Path(path) == target / "research_contract_manifest.json":
                raise OSError("synthetic seal failure")
            return write(path, value, *args, **kwargs)
        monkeypatch.setattr(atomic, "write_json_atomic", fail)
    with pytest.raises(OSError):
        po._promote_research_contract(str(source), str(target))
    assert _all_bytes(target) == before
    assert po._validate_research_contract(str(target))


def test_old_off_generation_has_no_fmp_hashes_and_removes_previous_capture(tmp_path):
    source, old, target = tmp_path / "source", tmp_path / "old", tmp_path / "target"
    _generation(old)
    po._promote_research_contract(str(old), str(target))
    source.mkdir()
    (source / "research_report.md").write_text("Old research. " * 50)
    (source / "sources.json").write_text("[]")
    before = od.capture_research_generation(source)
    assert not any(name.startswith("fmp") for name in before["files"])
    po._promote_research_contract(str(source), str(target))
    assert not (target / "fmp").exists()
    assert not (target / "fmp_research_binding.json").exists()
    assert po._validate_research_contract(str(target))


def test_same_request_different_responses_survive_parent_union_and_promotion(tmp_path, monkeypatch):
    for name in ("RESEARCH_GLOBAL_SYNTHESIS", "RESEARCH_TRACK_RECONCILE",
                 "RESEARCH_COMPACT_MERGED_DOSSIER", "DEERFLOW_SUBAGENTS", "DEERFLOW_DUAL_TRACK"):
        monkeypatch.setattr(po.Config, name, False)
    monkeypatch.setattr(po, "_sync_deerflow_bridge_if_stale", lambda _path: None)
    monkeypatch.setattr(po.PipelineManager, "save", classmethod(lambda cls, state: None))
    question = "Will revenue grow?"

    def run(prompt, handoff_dir, **kwargs):
        root = Path(handoff_dir)
        lane = int(root.name.split("_")[-1])
        _, _, sources = _generation(root, lane, question)
        return {"report": (root / "research_report.md").read_text(), "report_path": str(root / "research_report.md"),
                "actor_dossier": "", "actors": {"actors": [], "relationships": []}, "sources": sources,
                "timeline": None, "exit_code": 0, "research_telemetry": {"wall_s": 1}}

    monkeypatch.setattr(po.DeerFlowResearchRunner, "run", staticmethod(run))
    handoff = tmp_path / "handoff"
    state = po.PipelineState(pipeline_id="pipe_fmp_union", prompt=question, handoff_dir=str(handoff), options={})
    result = po.PipelineOrchestrator()._run_parallel_research_tracks(state, str(handoff), lambda *_: None, 2)
    assert len(result["sources"]) == 2
    assert len({row["url"] for row in result["sources"]}) == 2
    items = [row["fmp_capture"] for row in result["sources"]]
    assert len({item["request_sha256"] for item in items}) == 1
    assert len({item["capture_id"] for item in items}) == 2
    assert set(_api().CaptureStore(handoff, question, env={}, replay=True).data["captures"]) == {
        item["capture_id"] for item in items}
    target = tmp_path / "promoted"
    po._promote_research_contract(str(handoff), str(target))
    for lane in (1, 2):
        lane_dir = handoff / f"track_{lane}"
        # Compare every lane payload, independent of completion/source ordering.
        for name, raw in od.fmp_capture_artifacts(lane_dir).items():
            if name not in {"fmp/captures.json", "fmp_research_binding.json"}:
                assert (target / name).read_bytes() == raw
    assert po._validate_research_contract(str(target))
    from app.services.simulation_manager import SimulationManager
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path / "simulations"))
    (tmp_path / "simulations/sim_fmp_ensemble").mkdir(parents=True)
    consumed = od.capture_research_generation(target, report=result["report"], sources=result["sources"])
    od.bind_simulation_research("sim_fmp_ensemble", target, pipeline_id=state.pipeline_id,
                               expected_generation=consumed, report=result["report"], sources=result["sources"])
    bound = od.simulation_research_binding("sim_fmp_ensemble")
    assert bound["status"] == "valid"
    assert bound["files"] == consumed["files"]
    for item in items:
        assert bound["files"][item["file"]] == hashlib.sha256((target / item["file"]).read_bytes()).hexdigest()
    (target / items[0]["file"]).write_text("{}")
    assert od.simulation_research_binding("sim_fmp_ensemble")["status"] == "invalid"
    assert od.read_bound_research_core("sim_fmp_ensemble")["status"] == "invalid"


def test_generation_replacement_and_deleted_capture_are_not_silently_rebound(tmp_path):
    root = tmp_path / "generation"
    _, item, _ = _generation(root)
    before = od.capture_research_generation(root)
    payload = root / item["file"]
    payload.write_bytes(payload.read_bytes() + b"\n")
    assert od.capture_research_generation(root) != before
    payload.unlink()
    with pytest.raises(ValueError):
        od.capture_research_generation(root)


def test_fork_isolation_preserves_fmp_capture_bytes(tmp_path, monkeypatch):
    source = tmp_path / "parent"
    _generation(source)
    before = _all_bytes(source)
    monkeypatch.setattr(po.Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))
    po.PipelineManager.ensure_dirs("pipe_fmp_child")
    monkeypatch.setattr(po.PipelineOrchestrator, "_simulation_engine", staticmethod(lambda _state: "oasis"))
    state = po.PipelineState(pipeline_id="pipe_fmp_child", prompt="Will revenue grow?",
                             handoff_dir=str(source), options={"base_pipeline_id": "pipe_fmp_parent"})
    po.PipelineOrchestrator._isolate_fork_handoff(state)
    assert Path(state.handoff_dir) != source
    assert od.fmp_capture_artifacts(state.handoff_dir) == od.fmp_capture_artifacts(source)
    assert _all_bytes(source) == before


def test_invalid_fmp_cannot_degrade_to_unbound_or_core_only_research(tmp_path, monkeypatch):
    from app.services.simulation_manager import SimulationManager
    root = tmp_path / "generation"
    _, item, _ = _generation(root)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path / "simulations"))
    (tmp_path / "simulations/sim_fmp_case").mkdir(parents=True)
    state = po.PipelineState(pipeline_id="pipe_fmp_bound", prompt="Question", handoff_dir=str(root))
    consumed = od.capture_research_generation(root)
    od.bind_simulation_research("sim_fmp_case", root, pipeline_id=state.pipeline_id, expected_generation=consumed)
    assert od.read_bound_research_core("sim_fmp_case")["status"] == "valid"
    (root / item["file"]).unlink()
    assert od.read_bound_research_core("sim_fmp_case")["status"] == "invalid"
    assert po._research_requires_context_binding(state, str(root), consumed)
    with pytest.raises(ValueError):
        po._load_research_handoff(str(root))
    with pytest.raises(ValueError, match="consumed generation changed"):
        po.PipelineOrchestrator()._bind_world_research(
            state, "sim_fmp_case", (root / "research_report.md").read_text(),
            json.loads((root / "sources.json").read_text()), consumed)


def test_declared_but_deleted_capture_rejects_old_off_downgrade(tmp_path):
    root = tmp_path / "declared"
    root.mkdir()
    (root / "sources.json").write_text(json.dumps([{"provider": "fmp", "source_origin": "fmp_vendor"}]))
    with pytest.raises(ValueError, match="FMP captures are missing"):
        od.capture_research_generation(root)


def test_deleted_entire_capture_cannot_override_parent_contract(tmp_path):
    import shutil
    source, target = tmp_path / "source", tmp_path / "target"
    _generation(source)
    po._promote_research_contract(str(source), str(target))
    shutil.rmtree(target / "fmp")
    (target / "fmp_research_binding.json").unlink()
    (target / "sources.json").write_text("[]")
    with pytest.raises(ValueError, match="FMP captures are missing"):
        od.capture_research_generation(target)


def test_corrupt_incoming_capture_preserves_existing_generation(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    _, item, _ = _generation(source)
    po._promote_research_contract(str(source), str(target))
    previous = _all_bytes(target)
    (source / item["file"]).write_text("{}")
    with pytest.raises(ValueError):
        po._promote_research_contract(str(source), str(target))
    assert _all_bytes(target) == previous


def test_world_seed_rejects_deleted_fmp_parent_handoff(tmp_path, monkeypatch):
    import shutil
    from app.services.simulation_manager import SimulationManager
    root = tmp_path / "generation"
    _, _, sources = _generation(root)
    report = (root / "research_report.md").read_text()
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(tmp_path / "simulations"))
    for name in ("sim_fmp_parent", "sim_fmp_seed"):
        (tmp_path / "simulations" / name).mkdir(parents=True)
    state = po.PipelineState(pipeline_id="pipe_fmp_seed", prompt="Question", handoff_dir=str(root),
                             simulation_id="sim_fmp_parent")
    od.bind_simulation_research(state.simulation_id, root, pipeline_id=state.pipeline_id)
    shutil.rmtree(root)
    assert od.simulation_research_binding(state.simulation_id) == {"status": "invalid"}
    row = {}
    with pytest.raises(ValueError, match="consumed generation changed"):
        po.PipelineOrchestrator._bind_world_seed_research(state, row, "sim_fmp_seed", report, sources)
    assert "official_data_binding" not in row
