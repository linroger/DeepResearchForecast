"""Scenario rebuilds must preserve parent/sibling evidence through real _run.

The inherited simulation/report fixtures script unrelated services. Research
promotion/reuse, fork construction, graph seeding/readback, graph statistics,
artifact writes and pipeline state transitions are production implementations.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import graph_builder as gb
from app.services import pipeline_orchestrator as po
from app.services.graphiti_client.client import _ZepEdge, _ZepNode
from tests.test_graph_actor_v1_seed import _CaptureGraph, _service
from tests.test_orchestrator_research_wiring import _exercise_prepare_run_resume
from tests.test_pipeline_actor_contract import _write_producer_valid_bundle, dr


pytestmark = pytest.mark.guarded_runner


def _snapshot(root):
    root = Path(root)
    return {
        str(path.relative_to(root)): {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns,
        }
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def _json(path, payload):
    Path(path).write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


class _ScriptedGraph(_CaptureGraph):
    """External graph backend; seeded production args become readback rows."""

    def __init__(self, parent_graph_id, mode):
        super().__init__()
        self.parent_graph_id = parent_graph_id
        self.mode = mode
        self.created = []
        self.ingested = []
        self.readbacks = []
        self.node = SimpleNamespace(get_by_graph_id=self.nodes)
        self.edge = SimpleNamespace(get_by_graph_id=self.edges)

    def create(self, graph_id, **kwargs):
        self.created.append(graph_id)
        if self.mode == "create_failure":
            raise RuntimeError("SCRIPTED_GRAPH_CREATE_FAILURE")

    def set_ontology(self, **kwargs):
        pass

    def _stored(self, graph_id):
        capture = _CaptureGraph()
        capture.calls = [call for call in self.calls if call[0][0] == graph_id]
        return capture.actor_graph_seed_state(graph_id)

    def actor_graph_seed_state(self, graph_id):
        self.readbacks.append(graph_id)
        if graph_id == self.parent_graph_id and self.mode != "reuse":
            # An external backend with lost seed rows makes the actual strict
            # readback validator reject GRAPH reuse before _run rebuilds it.
            return {"nodes": [], "edges": []}
        return self._stored(graph_id)

    def nodes(self, graph_id, **kwargs):
        return [_ZepNode(SimpleNamespace(**row)) for row in self._stored(graph_id)["nodes"]]

    def edges(self, graph_id, **kwargs):
        return [_ZepEdge(SimpleNamespace(**row)) for row in self._stored(graph_id)["edges"]]

    def add_batch(self, graph_id, episodes):
        self.ingested.append({"graph_id": graph_id, "episodes": [ep.data for ep in episodes]})
        if self.mode == "ingest_failure":
            raise RuntimeError("SCRIPTED_GRAPH_INGEST_FAILURE")
        return [SimpleNamespace(uuid_=f"episode-{len(self.ingested)}-{i}")
                for i, _ in enumerate(episodes)]


def _exercise_shared_handoff(monkeypatch, tmp_path, dr, mode):
    monkeypatch.setattr(po.Config, "DEFAULT_SIMULATION_ENGINE", "oasis-legacy")
    # Reuse the existing real-_run fixture for simulation config seals, the
    # completion evidence gate and unrelated report/telemetry responses.
    baseline = _exercise_prepare_run_resume(monkeypatch, tmp_path, rebuild_prepare=False)
    assert baseline.state.status == "completed", baseline.state.error
    parent = copy.deepcopy(baseline.state)
    parent.pipeline_id = "pipe_parent_acceptance"
    parent.graph_id = "graph-parent-frozen"
    parent.handoff_dir = po.PipelineManager.handoff_dir(parent.pipeline_id)
    parent.report_id = "report_existing"
    parent.task_id = None
    parent.options["simulation_engine"] = "oasis-legacy"
    # A supported pre-policy run can contain a sealed producer bundle. Keep
    # that product compatibility path; do not replace reception/seeding guards.
    assert "actor_intelligence_policy_v1" not in parent.options
    po.PipelineManager.ensure_dirs(parent.pipeline_id)
    bundle = _write_producer_valid_bundle(Path(po.PipelineManager._dir(parent.pipeline_id)), dr, monkeypatch)
    assert bundle["handoff_dir"] == parent.handoff_dir
    parent.prompt = bundle["question"]
    parent.options["depth"] = bundle["depth"]

    backend = _ScriptedGraph(parent.graph_id, mode)
    seed_service = _service(backend)
    seed_service.seed_actors(parent.graph_id, bundle["actors"])
    # Persist the real producer manifest before installing the scripted lost-row
    # readback. Initial physical state must be independently valid.
    initial_state = backend._stored(parent.graph_id)
    validation_backend = _CaptureGraph()
    validation_backend.state_override = initial_state
    initial_builder = _service(validation_backend)
    po._validate_actor_graph_seed_contract(
        initial_builder, parent.graph_id, bundle["actors"], phase="post_seed",
        state=parent, persist=True,
    )
    shared = Path(parent.handoff_dir)
    _json(shared / "graph_priors.json", {"Acme": 0.125, "Beta": 0.25})
    _json(shared / "graph_priors_structural.json", {
        "betweenness": {"Acme": 0.125}, "chokepoints": ["parent-original"],
    })
    _json(shared / "communities.json", [{"name": "parent-community"}])
    _json(shared / "graph_prune.json", {"graph_id": parent.graph_id, "owner": parent.pipeline_id})
    parent.artifacts.update({
        "graph_priors": str(shared / "graph_priors.json"),
        "graph_priors_structural": str(shared / "graph_priors_structural.json"),
    })
    po.PipelineManager.save(parent)

    class ParkedThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            pass

    # Only suppress async dispatch so each real fork can be driven synchronously
    # below. Real fork construction, saved state, stage bits and shared path stay.
    with monkeypatch.context() as parked:
        parked.setattr(po, "threading", SimpleNamespace(
            Thread=ParkedThread, Event=po.threading.Event, Lock=po.threading.Lock,
        ))
        child = po.PipelineOrchestrator.fork(parent.pipeline_id, {"label": "child-rebuild"})
        sibling = po.PipelineOrchestrator.fork(parent.pipeline_id, {"label": "untouched-sibling"})
    assert child.handoff_dir == sibling.handoff_dir == parent.handoff_dir

    sibling_local = Path(po.PipelineManager.handoff_dir(sibling.pipeline_id))
    for filename in ("graph_priors.json", "graph_priors_structural.json", "actor_graph_seed_manifest.json"):
        _json(sibling_local / filename, {"owner": sibling.pipeline_id, "sentinel": filename})
    sibling.artifacts["graph_priors"] = str(sibling_local / "graph_priors.json")
    po.PipelineManager.save(sibling)
    parent_state_before = Path(po.PipelineManager.state_path(parent.pipeline_id)).read_bytes()
    sibling_state_before = Path(po.PipelineManager.state_path(sibling.pipeline_id)).read_bytes()
    before = {"parent_handoff": _snapshot(shared), "sibling_own_handoff": _snapshot(sibling_local),
              "sibling_shared_view": _snapshot(sibling.handoff_dir)}

    project = SimpleNamespace(project_id="proj", name="Shared fixture project",
                              ontology={"entity_types": [{"name": "Company"}], "edge_types": []},
                              graph_id=parent.graph_id)
    monkeypatch.setattr(po.ProjectManager, "get_project", classmethod(lambda cls, project_id: project))
    monkeypatch.setattr(po.ProjectManager, "save_project", classmethod(lambda cls, value: None))

    def builder(**kwargs):
        return _service(backend)

    monkeypatch.setattr(po, "GraphBuilderService", builder)
    monkeypatch.setattr(po.Config, "GRAPH_SEED_FROM_ACTORS", True)
    monkeypatch.setattr(po.Config, "GRAPH_CHOKEPOINT_PRIORS", True)
    monkeypatch.setattr(po.Config, "GRAPH_BUILD_CONCURRENCY", 1)
    monkeypatch.setattr(po.Config, "GRAPHITI_REMOTE", False)
    from app.services.graphiti_client import runtime as runtime_module
    monkeypatch.setattr(runtime_module, "get_runtime", lambda: SimpleNamespace(
        pop_ingest_skip_reasons=lambda graph_id: {},
    ))
    manager = po.SimulationManager()
    prepare_calls = []
    original_prepare = manager.prepare_simulation

    def prepare(**kwargs):
        prepare_calls.append(copy.deepcopy(kwargs))
        if mode == "prepare_failure":
            raise RuntimeError("SCRIPTED_PREPARE_FAILURE_AFTER_GRAPH")
        return original_prepare(**kwargs)

    monkeypatch.setattr(manager, "prepare_simulation", prepare)
    # Script unrelated final-report lookup as a completed report for this child.
    monkeypatch.setattr(po.ReportManager, "get_report_by_simulation", classmethod(
        lambda cls, simulation_id: SimpleNamespace(
            report_id="report_scripted_child", status=po.ReportStatus.COMPLETED,
        ) if simulation_id == baseline.new_id else None,
    ))

    po.PipelineOrchestrator._run(child)

    after = {"parent_handoff": _snapshot(shared), "sibling_own_handoff": _snapshot(sibling_local),
             "sibling_shared_view": _snapshot(sibling.handoff_dir)}
    changed = {scope: sorted(name for name in set(before[scope]) | set(after[scope])
                             if before[scope].get(name) != after[scope].get(name)) for scope in before}
    _json(tmp_path / "fork-preservation-receipt.json", {
        "mode": mode, "parent_id": parent.pipeline_id, "child_id": child.pipeline_id,
        "sibling_id": sibling.pipeline_id, "parent_graph_id": parent.graph_id,
        "child_graph_id": child.graph_id, "child_status": child.status, "child_error": child.error,
        "stages": child.to_dict()["stages"],
        "created_graphs": backend.created, "readback_graphs": backend.readbacks,
        "ingested": backend.ingested, "prepare_calls": prepare_calls,
        "child_artifacts": child.artifacts, "child_handoff_dir": child.handoff_dir,
        "before": before, "after": after, "changed": changed,
    })
    assert Path(po.PipelineManager.state_path(parent.pipeline_id)).read_bytes() == parent_state_before
    assert Path(po.PipelineManager.state_path(sibling.pipeline_id)).read_bytes() == sibling_state_before
    return SimpleNamespace(child=child, backend=backend, before=before, after=after,
                           changed=changed, prepare_calls=prepare_calls,
                           parent=parent, sibling=sibling)


@pytest.mark.parametrize("mode", ["success", "ingest_failure", "prepare_failure", "reuse", "create_failure"])
def test_child_graph_rebuild_preserves_parent_and_sibling(monkeypatch, tmp_path, dr, mode):
    result = _exercise_shared_handoff(monkeypatch, tmp_path, dr, mode)
    child = result.child
    if mode == "reuse":
        assert child.status == "completed", child.error
        assert result.backend.created == []
        assert child.options["graph_seed_readback"]["reuse"]["status"] == "ok"
    else:
        assert len(result.backend.created) == 1, child.error
        assert child.options["resumed_stage_validation"] == "graph_rebuilt_actor_seed_readback_mismatch"
        if mode == "success":
            assert child.status == "completed", child.error
            assert child.stages[po.STAGE_GRAPH].status == "completed"
            assert result.prepare_calls
        elif mode == "prepare_failure":
            assert child.status == "failed" and "SCRIPTED_PREPARE_FAILURE" in child.error
            assert child.stages[po.STAGE_GRAPH].status == "completed"
        elif mode == "ingest_failure":
            assert result.backend.ingested
            assert child.status == "failed" and child.stages[po.STAGE_GRAPH].status == "failed"
            assert child.options["graph_seed_readback"]["post_seed"]["status"] == "ok"
        else:
            assert child.status == "failed" and "SCRIPTED_GRAPH_CREATE_FAILURE" in child.error
    # These are the desired ownership invariants. Fail only after proving the
    # intended actual _run branch/outcome, never on an irrelevant fixture error.
    assert result.after == result.before, result.changed


def test_successful_child_private_graph_reused_after_fresh_state_reload(monkeypatch, tmp_path, dr):
    result = _exercise_shared_handoff(monkeypatch, tmp_path, dr, "success")
    child = result.child
    assert child.status == "completed", child.error
    assert result.after == result.before, result.changed
    private = Path(child.handoff_dir)
    assert private.is_relative_to(Path(po.PipelineManager._dir(child.pipeline_id)))
    assert private != Path(result.parent.handoff_dir)
    graph_id = child.graph_id
    artifact_paths = {name: Path(child.artifacts[name]) for name in (
        "graph_priors", "graph_priors_structural", "actor_graph_seed_manifest",
    )}
    assert all(path.is_relative_to(private) for path in artifact_paths.values())
    before_child = _snapshot(private)
    seed_manifest = json.loads(artifact_paths["actor_graph_seed_manifest"].read_text())
    priors = json.loads(artifact_paths["graph_priors"].read_text())
    assert seed_manifest["graph_id"] == graph_id
    assert result.prepare_calls[0]["graph_priors"] == priors
    created_before = list(result.backend.created)
    ingested_before = len(result.backend.ingested)
    writes_before = len(result.backend.calls)
    prepare_before = len(result.prepare_calls)
    state_bytes = {
        state.pipeline_id: Path(po.PipelineManager.state_path(state.pipeline_id)).read_bytes()
        for state in (result.parent, result.sibling)
    }

    reloaded = po.PipelineState.from_dict(po.PipelineManager.load(child.pipeline_id))
    assert reloaded is not child
    assert reloaded.handoff_dir == str(private) and reloaded.graph_id == graph_id
    po.PipelineOrchestrator._run(reloaded)

    after = {"parent_handoff": _snapshot(result.parent.handoff_dir),
             "sibling_own_handoff": _snapshot(po.PipelineManager.handoff_dir(result.sibling.pipeline_id)),
             "sibling_shared_view": _snapshot(result.sibling.handoff_dir)}
    _json(tmp_path / "fork-reload-reuse-receipt.json", {
        "graph_id_before": graph_id, "graph_id_after": reloaded.graph_id,
        "status": reloaded.status, "error": reloaded.error,
        "private_handoff": reloaded.handoff_dir,
        "artifact_paths": reloaded.artifacts,
        "seed_readback": reloaded.options.get("graph_seed_readback"),
        "before_private": before_child, "after_private": _snapshot(private),
        "before_protected": result.before, "after_protected": after,
        "created_before": created_before, "created_after": result.backend.created,
        "ingested_before": ingested_before, "ingested_after": len(result.backend.ingested),
        "seed_writes_before": writes_before, "seed_writes_after": len(result.backend.calls),
    })
    assert reloaded.status == "completed", reloaded.error
    assert reloaded.graph_id == graph_id and reloaded.handoff_dir == str(private)
    assert result.backend.created == created_before
    assert len(result.backend.ingested) == ingested_before
    assert len(result.backend.calls) == writes_before
    assert len(result.prepare_calls) == prepare_before
    readback = reloaded.options["graph_seed_readback"]["reuse"]
    assert readback["status"] == "ok" and readback["graph_id"] == graph_id
    assert readback["manifest_sha256"] == seed_manifest["manifest_sha256"]
    assert _snapshot(private) == before_child
    assert after == result.before
    for state in (result.parent, result.sibling):
        assert Path(po.PipelineManager.state_path(state.pipeline_id)).read_bytes() == state_bytes[state.pipeline_id]
