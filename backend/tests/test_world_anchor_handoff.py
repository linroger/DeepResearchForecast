"""Host adoption of genuine ledger transitions, with scripted child completion.

These tests exercise the real parent context, store, and saved pipeline state.
The guarded child uses real scope transitions with a synthetic output identity;
the full private research/SDK startup remains a separate gate.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.services import run_spending as lifecycle, world_anchor as anchor
from test_world_anchor_admission import prepared, runtime as _runtime, isolated as _isolated
from test_world_anchor_spending import session, sp
from test_world_anchor_lifecycle import wired as _wired, target_case as _target_case

runtime = _runtime
isolated = _isolated
wired = _wired
target_case = _target_case


def _complete_child(parent, handoff, *, complete=True):
    """Issue real DB receipts; synthetic output identity is never a ready pack."""
    with sp.operation("research", "handoff-regression"):
        child = sp.register_participant(parent, "research-handoff",
            spawn_receipt_sha256=sp.hash_payload("scripted-child"),
            scope_entry_ids=["anchor-one"])
        Path(handoff).mkdir(parents=True, exist_ok=True)
        control = Path(handoff) / "scripted-child-control.json"
        control.write_text(json.dumps({"session": session(), "complete": complete}))
        script = Path(__file__).with_name("fixtures") / "world_anchor_handoff_child.py"
        process = subprocess.Popen([sys.executable, "-B", str(script), str(control)],
            env={**os.environ, **sp.export_environment(child)},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr
        assert json.loads(stdout) == {"completed": complete}
        sp.participant_exited(parent, "research-handoff",
            exit_receipt_sha256=sp.hash_payload({"pid": process.pid, "exit_code": process.returncode}))
    return json.loads((Path(handoff) / "world_anchor_scope_handoff.json").read_text())


@pytest.mark.parametrize("complete", [True, False])
def test_parent_adopts_only_real_transition_and_keeps_lifecycle_pending(runtime, tmp_path, monkeypatch, complete):
    with prepared(tmp_path, monkeypatch, runtime) as (_, request):
        state = runtime.po.PipelineOrchestrator.start(**request)
        parent = state.options[lifecycle.BINDING_KEY]
        with lifecycle.pipeline_scope(state):
            packet = _complete_child(parent, state.handoff_dir, complete=complete)
            adopted = lifecycle._adopt_research_scope_handoff(parent, state.handoff_dir)
            assert adopted["participant_id"] == "parent"
            assert adopted["admission_epoch"] == (2 if complete else 1)
            assert adopted["active_scope_id"] == (None if complete else "anchor-one")
            saved = runtime.po.PipelineManager.load(state.pipeline_id)
            pending = saved["options"][anchor.LIFECYCLE_KEY]
            assert pending["status"] == "pending"
            expected = packet["completion"]["artifact_manifest_sha256"] if complete else None
            assert pending["completion_manifest_sha256"] == expected
            assert saved["options"][lifecycle.BINDING_KEY] == adopted
            assert sp.summary(adopted)["attempt_count"] == 0
            with pytest.raises(anchor.WorldAnchorIntegrationError, match="anchor_not_ready"):
                anchor.require_completed(state)


@pytest.mark.parametrize("mutation", ["completion", "receipt", "missing_completion", "reversed", "duplicate_key"])
def test_uncommitted_or_malformed_handoff_cannot_pin_completion(runtime, tmp_path, monkeypatch, mutation):
    with prepared(tmp_path, monkeypatch, runtime) as (_, request):
        state = runtime.po.PipelineOrchestrator.start(**request)
        parent = state.options[lifecycle.BINDING_KEY]
        before = deepcopy(state.options)
        with lifecycle.pipeline_scope(state):
            packet = _complete_child(parent, state.handoff_dir)
            if mutation == "completion":
                packet["completion"]["artifact_manifest_sha256"] = "a" * 64
            elif mutation == "receipt":
                packet["receipts"][0]["proof_sha256"] = "b" * 64
            elif mutation == "missing_completion":
                packet["completion"] = None
            elif mutation == "reversed":
                packet["receipts"].reverse()
            raw = json.dumps(packet)
            if mutation == "duplicate_key":
                raw = raw[:-1] + ', "completion": null}'
            (Path(state.handoff_dir) / "world_anchor_scope_handoff.json").write_text(raw)
            with pytest.raises(sp.SpendingStop):
                lifecycle._adopt_research_scope_handoff(parent, state.handoff_dir)
            assert state.options == before
            saved = runtime.po.PipelineManager.load(state.pipeline_id)
            assert saved["options"][anchor.LIFECYCLE_KEY]["completion_manifest_sha256"] is None
            assert sp.summary(parent)["attempt_count"] == 0


def test_removed_enabled_option_with_retained_lifecycle_cannot_become_off(runtime, tmp_path, monkeypatch):
    with prepared(tmp_path, monkeypatch, runtime) as (_, request):
        state = runtime.po.PipelineOrchestrator.start(**request)
        del state.options[anchor.CONFIG_KEY]
        with pytest.raises(anchor.WorldAnchorIntegrationError, match="anchor_binding_mismatch"):
            anchor.require_completed(state)


def test_ready_context_cannot_be_replayed_as_another_pipeline(wired):
    context = wired["context"]
    run_id = context.pack["scope"]["run_id"]
    state = SimpleNamespace(pipeline_id=run_id, handoff_dir=str(wired["handoff"]), options={
        anchor.CONFIG_KEY: {"mode": "v1"}, anchor.LIFECYCLE_KEY: {
            "schema_version": "world-anchor-lifecycle/v1", "status": "ready",
            "owner_pipeline_id": run_id, "pack_hash": context.pack_hash,
            "input_hash": context.pack["input_hash"],
            "input_generation_id": context.pack["scope"]["research_generation_id"],
            "completion_manifest_sha256": context.research_manifest_hash}})
    assert anchor.require_completed(state).pack_hash == context.pack_hash
    state.pipeline_id = "pipe_other"
    with pytest.raises(anchor.WorldAnchorIntegrationError, match="anchor_binding_mismatch"):
        anchor.require_completed(state)


@pytest.mark.parametrize("mutation", ["foreign", "missing", "duplicate"])
def test_actor_join_requires_the_exact_retained_alias_references(wired, mutation):
    context = wired["context"]
    join = context.join
    assert context.with_join(join, cast_bytes=context._cast_bytes).join == join
    aliases = join["rows"][0]["alias_ref_ids"]
    assert aliases
    if mutation == "foreign":
        aliases[0] = "alias_" + "0" * 64
    elif mutation == "missing":
        aliases.clear()
    else:
        aliases.append(aliases[0])
    with pytest.raises(anchor.WorldAnchorIntegrationError, match="invalid_anchor_join"):
        context.with_join(join, cast_bytes=context._cast_bytes)
