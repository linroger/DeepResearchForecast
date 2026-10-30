"""Join parent completion to the selected real ledger budget seal.

Run only through main_offline_pytest.py. One authorization covers all cases so
the spending core's process-wide authority is never reset between scenarios.
"""

from contextvars import copy_context
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.services import run_spending as spending, world_anchor as host
from app.services.official_data import bridge_module
from test_world_anchor import digest, dump, make_fixture, wa
from test_world_anchor_admission import prepared, runtime as _runtime
from test_world_anchor_spending import model_request, reported, sp

runtime = _runtime
publication = bridge_module("world_anchor_publication")
pytestmark = pytest.mark.guarded_runner


def _source(tmp_path, pipeline_id):
    fixture = make_fixture(tmp_path / "source", with_contract=False)
    fixture["scope"]["run_id"] = pipeline_id
    fixture["manifest"]["scope"] = deepcopy(fixture["scope"])
    fixture["requirements"] = wa.requirements_from_contract(None, scope=fixture["scope"])
    fixture["index"] = wa.index_snapshot(
        fixture["root"], fixture["manifest"],
        expected_manifest_hash=wa.anchor_hash(fixture["manifest"]),
        expected_scope=fixture["scope"], requirements=fixture["requirements"],
        policy=fixture["policy"],
    )
    return fixture


def _receipts(fixture, budget):
    """Use the established producer schema with untouched DB receipt values."""
    root = fixture["root"] / budget["session_id"]
    root.mkdir()
    retained = budget["retained"]
    summary = {
        "schema_version": "world-anchor-metering/v1",
        "anchor_budget_scope_id": budget["scope_id"],
        "physical_model_attempts": retained["model_attempts"],
        "reserved_tokens": retained["token_envelope_units"],
        "physical_catalog_attempts": retained["catalog_attempts"],
        "physical_followup_attempts": retained["followup_attempts"],
        "budget_receipt_artifact_id": "stage-budget",
        "budget_receipt_hash": digest(dump(budget)),
    }
    files = []
    for artifact_id, value in (("stage-budget", budget), ("stage-metering", summary)):
        raw = dump(value)
        path = artifact_id + ".json"
        (root / path).write_bytes(raw)
        files.append({"artifact_id": artifact_id, "path": path, "sha256": digest(raw),
                      "bytes": len(raw), "role": "metering_receipt"})
    manifest = {
        "schema_version": "world-anchor-producer-receipts/v1", "scope": fixture["scope"],
        "policy_hash": wa.anchor_hash(fixture["policy"]), "files": files,
        "transport_artifact_ids": [],
    }
    handle = wa.producer_receipts(root, manifest,
        expected_manifest_hash=wa.anchor_hash(manifest), expected_scope=fixture["scope"])
    assert json.loads(handle.artifact_bytes("stage-budget")) == budget
    meter = {key: summary[key] for key in (
        "anchor_budget_scope_id", "physical_model_attempts", "reserved_tokens",
        "physical_catalog_attempts", "physical_followup_attempts",
    )}
    meter.update(mode="metered", receipt_artifact_id="stage-metering",
                 receipt_hash=digest(dump(summary)))
    return handle, meter


def _pack(fixture, handles, meter):
    index = wa.attach_producer_receipts(fixture["index"], receipts=list(handles))
    candidates = wa.candidates_for_requirements(fixture["requirements"], index)
    proposal = {
        "schema_version": "world-anchor-proposal/v1",
        "requirements_hash": wa.anchor_hash(fixture["requirements"]),
        "input_hash": index.snapshot()["input_hash"],
        "candidate_hash": wa.anchor_hash(candidates), "rows": [],
    }
    pack = wa.admit_bindings(fixture["requirements"], index, candidates, proposal,
        policy=fixture["policy"], attempts=[], metering=meter)
    return pack, index


def _publish(fixture, directory, handles, meter):
    pack, index = _pack(fixture, handles, meter)
    return publication.publish_completion(directory, pack,
        requirements=fixture["requirements"], index=index,
        policy=fixture["policy"], receipts=handles)


def _begin_and_seal(fixture, binding, session_id, *, dispatch=False):
    entered = sp.begin_anchor_scope(binding, session={
        "session_id": session_id,
        "research_generation_id": fixture["scope"]["research_generation_id"],
        "input_manifest_sha256": wa.anchor_hash(fixture["manifest"]),
        "requirement_registry_sha256": wa.anchor_hash(fixture["requirements"]),
        "workers_quiesced_sha256": sp.hash_payload([]),
        "restart_of_session_id": None,
    })
    active = entered["binding"]
    if dispatch:
        observed = []

        def send():
            observed.append(deepcopy(sp.scope_summary(active)["retained"]))
            return "offline response"

        assert sp.dispatch("model", model_request(), send, usage=reported) == "offline response"
        assert len(observed) == 1 and observed[0]["model_attempts"] == 1
    budget = sp.seal_anchor_budget(active, seal={
        "session_id": session_id,
        "participants_exited_sha256": sp.hash_payload(sp.summary(active)["participants"]),
        "workers_joined_sha256": sp.hash_payload([]),
    })
    assert budget["retained"] == sp.scope_summary(active)["retained"]
    return entered, budget


def _finish(entered, budget, published, directory):
    completion = {
        "session_id": budget["session_id"],
        "artifact_manifest_sha256": published["manifest_sha256"],
        "budget_receipt_sha256": sp.hash_payload(budget), "result": "non_ready",
    }
    exited = sp.finish_anchor_scope(entered["binding"], completion=completion)
    assert exited["transition_receipt"]["proof_sha256"] == sp.hash_payload(completion)
    packet = {"schema_version": "world-anchor-scope-handoff/v1",
              "receipts": [entered["transition_receipt"], exited["transition_receipt"]],
              "completion": completion}
    (directory / "world_anchor_scope_handoff.json").write_bytes(dump(packet))
    return packet


def _adopt(state, directory, packet):
    state.handoff_dir = str(directory)
    spending._adopt_research_scope_handoff(spending.state_binding(state), directory)
    assert state.options[host.LIFECYCLE_KEY]["status"] == "pending"
    assert state.options[host.LIFECYCLE_KEY]["completion_manifest_sha256"] == (
        packet["completion"]["artifact_manifest_sha256"]
    )
    assert spending.state_binding(state)["admission_epoch"] == packet["receipts"][-1]["to_epoch"]


def _loaded_state(runtime, state):
    """Read the actual parent save; do not manufacture a lifecycle or budget pin."""
    return runtime.po.PipelineState.from_dict(runtime.po.PipelineManager.load(state.pipeline_id))


def test_parent_completion_joins_selected_budget_to_actual_scope_exit(runtime, tmp_path, monkeypatch):
    unexpected_acceptances = []
    with prepared(tmp_path, monkeypatch, runtime) as (_, request):
        state = runtime.po.PipelineOrchestrator.start(**request)
        fixture = _source(tmp_path, state.pipeline_id)
        original_directory = Path(state.handoff_dir)
        with spending.pipeline_scope(state):

            def first_scope():
                with sp.operation("research", "first-zero-call"):
                    entered, budget = _begin_and_seal(
                        fixture, deepcopy(spending.state_binding(state)), "zero-call-original")
                    handle, meter = _receipts(fixture, budget)
                    published = _publish(fixture, original_directory, (handle,), meter)
                    packet = _finish(entered, budget, published, original_directory)
                    return budget, handle, meter, published, packet

            old_budget, old_handle, old_meter, old_publication, packet = copy_context().run(first_scope)
            _adopt(state, original_directory, packet)

            # A real current zero-call seal must be accepted before any rollback
            # assertion. The saved pending state remains the producer's owner.
            control = _loaded_state(runtime, state)
            accepted = host.accept_completion(control,
                expected_manifest_sha256=old_publication["manifest_sha256"])
            assert accepted.pack["metering"] == old_meter
            assert accepted.pack["metering"]["mode"] == "metered"
            assert old_budget["retained"]["model_attempts"] == 0
            assert control.options[host.LIFECYCLE_KEY]["status"] == "ready"
            assert state.options[host.LIFECYCLE_KEY]["status"] == "pending"

            def equal_counter_scope():
                with sp.operation("research", "same-counters-new-session"):
                    entered, budget = _begin_and_seal(
                        fixture, deepcopy(spending.state_binding(state)), "zero-call-current")
                    current_handle, _ = _receipts(fixture, budget)
                    assert budget["retained"] == old_budget["retained"]
                    assert sp.hash_payload(budget) != sp.hash_payload(old_budget)
                    directory = tmp_path / "both-bundles-publication"
                    published = _publish(fixture, directory, (old_handle, current_handle), old_meter)
                    packet = _finish(entered, budget, published, directory)
                    return directory, published, packet

            directory, published, packet = copy_context().run(equal_counter_scope)
            _adopt(state, directory, packet)
            candidate = _loaded_state(runtime, state)
            try:
                host.accept_completion(candidate, expected_manifest_sha256=published["manifest_sha256"])
            except host.WorldAnchorIntegrationError as error:
                assert error.code == "anchor_artifact_invalid"
                assert candidate.options[host.LIFECYCLE_KEY]["status"] == "pending"
            else:
                unexpected_acceptances.append("both bundles, equal counters, old session selected")

            def retained_dispatch_scope():
                with sp.operation("research", "retained-fake-dispatch"):
                    entered, budget = _begin_and_seal(fixture,
                        deepcopy(spending.state_binding(state)), "one-call-current", dispatch=True)
                    current_handle, current_meter = _receipts(fixture, budget)
                    assert budget["retained"]["model_attempts"] > old_budget["retained"]["model_attempts"]
                    # This rollback already fails at pure admission, before
                    # publication or parent completion, because counters grew.
                    with pytest.raises(wa.AnchorError, match="E_BUDGET_RECEIPT") as rejected:
                        _pack(fixture, (old_handle, current_handle), old_meter)
                    assert rejected.value.path == "stale_metering"
                    assert _pack(fixture, (old_handle, current_handle), current_meter)[0]["metering"] == current_meter
                    return _finish(entered, budget, old_publication, original_directory)

            packet = copy_context().run(retained_dispatch_scope)
            _adopt(state, original_directory, packet)
            assert packet["completion"]["budget_receipt_sha256"] != sp.hash_payload(old_budget)
            candidate = _loaded_state(runtime, state)
            try:
                host.accept_completion(candidate,
                    expected_manifest_sha256=old_publication["manifest_sha256"])
            except host.WorldAnchorIntegrationError as error:
                assert error.code == "anchor_artifact_invalid"
                assert candidate.options[host.LIFECYCLE_KEY]["status"] == "pending"
            else:
                unexpected_acceptances.append("old-only publication, current retained dispatch omitted")
            assert sp.summary(spending.state_binding(state))["attempt_count"] == 1

    assert not unexpected_acceptances, "Parent accepted stale selected budget seals: " + "; ".join(
        unexpected_acceptances)
