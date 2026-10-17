"""Bounded real-SDK/journal evidence for private revision-shape diagnostics.

All execution belongs to the parent guarded runner. MockTransport exercises
the actual SDK and policy without network or original-run mutation.
"""
from copy import deepcopy
import json

import pytest

from app.services.world_simulation import consistency_evaluation as replay
from app.services.world_simulation.artifacts import atomic_json
from app.services.world_simulation.contracts import WorldError, digest
from test_world_consistency_evaluation import factory_for, pricing


pytestmark = pytest.mark.guarded_runner


def admitted(mode="actor-consistency-v3"):
    config = pricing()
    config["policy"]["decisionReview"] = mode
    manifest = replay.preregister(config, "1.25")
    config["authorization"] = {"manifestHash": manifest["manifestHash"], "offlineGatesPassed": True,
        "pricingVerified": True, "evidenceRefs": ["fixture://revision-shape-journal"]}
    return config, manifest


def test_real_sdk_known_invalid_v3_check_records_private_bound_shape(tmp_path):
    """RED must be missing reviewShape after a known charged validation failure."""
    config, manifest = admitted()
    calls = []
    factory, clients = factory_for(manifest, calls, first_failure="invalid_assessment")
    root = tmp_path / "run"
    try:
        report = replay.run_evaluation(root, factory, config)
        journal = json.loads((root / "journal.json").read_text())
        case = manifest["cases"][0]
        row = journal["cases"][case["evaluationId"]]
        assert len(calls) == report["attempts"] == 12 and report["retries"] == 0
        assert row["status"] == "failed" and row["errorCode"] == "invalid_assessment"
        assert row["errorMessage"] == "Unsupported assessment check fields"
        assert row["usage"]["tokens"] == 30 and row["usage"]["costUsd"] != "0"
        assert report["completedCases"] == 11 and report["diagnosticGate"] == "incomplete"
        assert "withheldReview" not in row and "decision" not in row and "matches" not in row
        assert "SENTINEL_PROVIDER_BODY" not in json.dumps(journal)
        assert "reviewShape" in row, (
            "A real SDK v3 check-field validation failure was charged and saved, "
            "but its optional private structural reviewShape evidence was discarded"
        )
        retained = row["reviewShape"]
        assert set(retained) == {"schemaVersion", "manifestHash", "evaluationId", "purpose", "observationHash",
                                 "candidateHash", "errorCode", "usage", "shape", "receiptHash"}
        assert retained["schemaVersion"] == "world-review-shape-diagnostic/v1"
        assert retained["manifestHash"] == manifest["manifestHash"]
        assert retained["evaluationId"] == case["evaluationId"] and retained["purpose"] == "revision"
        assert retained["observationHash"] == digest(case["actorPayload"]["observation"])
        assert retained["candidateHash"] == digest(case["actorPayload"]["candidateDecision"])
        assert retained["errorCode"] == row["errorCode"] and retained["usage"] == row["usage"]
        assert retained["receiptHash"] == digest({key: value for key, value in retained.items() if key != "receiptHash"})
        shape = retained["shape"]
        assert shape["schemaVersion"] == "actor-revision-shape/v1"
        assert shape["checksItemCount"] == 4
        assert shape["nodes"]["check0"]["type"] == "object"
        assert shape["nodes"]["check0"]["recognizedKeys"] == ["evidencePaths", "explanation", "kind", "verdict"]
        assert shape["nodes"]["check0"]["missingRequiredKeys"] == []
        assert "SENTINEL_PROVIDER_BODY" not in json.dumps(retained)
        assert "reviewShape" not in json.dumps(report)
        assert replay.run_evaluation(root, factory, config) == report and len(calls) == 12
    finally:
        for client in clients:
            client.close()


def test_old_failed_rows_without_shape_remain_compatible_and_never_redispatch(tmp_path):
    config, manifest = admitted()
    calls = []
    factory, clients = factory_for(manifest, calls, first_failure="invalid_assessment")
    root = tmp_path / "run"
    try:
        report = replay.run_evaluation(root, factory, config)
        journal = json.loads((root / "journal.json").read_text())
        row = journal["cases"][manifest["cases"][0]["evaluationId"]]
        assert "reviewShape" in row
        row.pop("reviewShape")  # Simulate a historical failed row predating diagnostics.
        atomic_json(root / "journal.json", journal)
        assert replay.summarize_evaluation(root) == report
        assert replay.run_evaluation(root, factory, config) == report and len(calls) == 12
        assert json.loads((root / "journal.json").read_text()) == journal
    finally:
        for client in clients:
            client.close()


@pytest.mark.parametrize("group", ["bindings", "shape", "row"])
def test_saved_shape_tampering_rejects_before_summary_or_resume_without_new_calls(tmp_path, group):
    config, manifest = admitted()
    calls = []
    factory, clients = factory_for(manifest, calls, first_failure="invalid_assessment")
    root = tmp_path / "run"
    try:
        replay.run_evaluation(root, factory, config)
        original = json.loads((root / "journal.json").read_text())
        target = manifest["cases"][0]["evaluationId"]
        assert "reviewShape" in original["cases"][target]
        report_before = (root / "report.json").read_bytes()
        defects = {
            "bindings": ["manifestHash", "evaluationId", "purpose", "observationHash", "candidateHash", "usage", "receiptHash"],
            "shape": ["partial_wrapper", "extra_wrapper", "boolean_count", "unknown_name", "partial_shape", "parent_type"],
            "row": ["unknown", "other_code", "withheld", "completed"],
        }[group]
        for defect in defects:
            journal = deepcopy(original)
            row = journal["cases"][target]
            retained = row["reviewShape"]
            if group == "bindings":
                if defect == "usage":
                    retained["usage"]["tokens"] = row["usage"]["tokens"] - 1
                else:
                    retained[defect] = "mismatched-server-binding"
            elif group == "shape":
                if defect == "partial_wrapper":
                    retained.pop("purpose")
                elif defect == "extra_wrapper":
                    retained["rawOutput"] = "FORBIDDEN_RAW_OUTPUT"
                elif defect == "boolean_count":
                    retained["shape"]["nodes"]["root"]["unknownKeyCount"] = False
                elif defect == "unknown_name":
                    retained["shape"]["nodes"]["check0"]["recognizedKeys"].append("FORBIDDEN_UNKNOWN_KEY")
                elif defect == "partial_shape":
                    retained["shape"]["nodes"].pop("check3")
                else:
                    retained["shape"]["nodes"]["assessment"] = {"type": "null", "recognizedKeys": [],
                        "missingRequiredKeys": ["checks"], "unknownKeyCount": 0, "unknownKeyOverflow": False}
            elif defect == "unknown":
                row.update(status="unknown", usage=None)
            elif defect == "other_code":
                row.update(errorCode="invalid_input", errorMessage=replay._GENERIC_FAILURE)
                retained["errorCode"] = "invalid_input"
            elif defect == "withheld":
                row["withheldReview"] = {}
            else:
                completed = manifest["cases"][1]["evaluationId"]
                journal["cases"][completed]["reviewShape"] = deepcopy(retained)
                row.pop("reviewShape")
            if defect != "receiptHash":
                retained["receiptHash"] = digest({key: value for key, value in retained.items() if key != "receiptHash"})
            atomic_json(root / "journal.json", journal)
            with pytest.raises(WorldError):
                replay.summarize_evaluation(root)
            with pytest.raises(WorldError):
                replay.run_evaluation(root, factory, config)
            assert len(calls) == 12 and (root / "report.json").read_bytes() == report_before
        atomic_json(root / "journal.json", original)
        assert replay.summarize_evaluation(root)["completedCases"] == 11
    finally:
        for client in clients:
            client.close()


@pytest.mark.parametrize("ineligible", ["old_mode", "unknown", "unresolved", "spoofed"])
def test_wrong_mode_unknown_withheld_or_unmarked_failure_never_gets_shape(tmp_path, ineligible):
    config, manifest = admitted("actor-consistency-v2" if ineligible == "old_mode" else "actor-consistency-v3")
    calls = []
    first_failure = ineligible if ineligible in {"unknown", "unresolved"} else "invalid_assessment"
    original_factory, clients = factory_for(manifest, calls, first_failure=first_failure)
    factory = original_factory
    if ineligible == "spoofed":
        from app.services.world_simulation.policy import PolicyFailure

        def factory(spec):
            policy = original_factory(spec)
            original_decide = policy.decide

            def unmarked(*args, **kwargs):
                try:
                    return original_decide(*args, **kwargs)
                except PolicyFailure as error:
                    # Same real charged failure, but a different unmarked
                    # exception instance must not inherit controlled origin.
                    raise PolicyFailure(error.code, str(error), usage=error.usage) from None

            policy.decide = unmarked
            return policy

        factory.evaluation_mode = "external"
    root = tmp_path / "run"
    try:
        report = replay.run_evaluation(root, factory, config)
        journal = json.loads((root / "journal.json").read_text())
        row = journal["cases"][manifest["cases"][0]["evaluationId"]]
        assert len(calls) == 12 and report["retries"] == 0
        assert "reviewShape" not in row
        assert row["status"] == ("unknown" if ineligible == "unknown" else "failed")
        assert row["usage"] is None if ineligible == "unknown" else row["usage"]["tokens"] == 30
        assert ("withheldReview" in row) == (ineligible == "unresolved")
        assert replay.run_evaluation(root, factory, config) == report and len(calls) == 12
        if ineligible == "old_mode":
            # Even a correctly hashed wrapper is forbidden under an old mode.
            from app.services.world_simulation.review import build_revision_shape

            shape = build_revision_shape({"decision": {"intents": []}, "assessment": {"checks": []}})
            row["reviewShape"] = replay._review_shape(manifest, manifest["cases"][0], row["errorCode"], row["usage"], shape)
            atomic_json(root / "journal.json", journal)
            with pytest.raises(WorldError):
                replay.summarize_evaluation(root)
            with pytest.raises(WorldError):
                replay.run_evaluation(root, factory, config)
            assert len(calls) == 12
    finally:
        for client in clients:
            client.close()


@pytest.mark.parametrize("component", ["getter", "wrapper"])
def test_optional_diagnostic_failure_preserves_original_error_known_charge_and_no_retry(tmp_path, monkeypatch, component):
    from app.services.world_simulation import policy as policy_module

    config, manifest = admitted()
    calls, diagnostic_calls = [], []
    factory, clients = factory_for(manifest, calls, first_failure="invalid_assessment")

    def broken(*args, **kwargs):
        diagnostic_calls.append(component)
        raise RuntimeError("PRIVATE_DIAGNOSTIC_CONSTRUCTION_FAILURE")

    if component == "getter":
        monkeypatch.setattr(policy_module, "revision_shape_diagnostic", broken)
    else:
        monkeypatch.setattr(replay, "_review_shape", broken)
    root = tmp_path / "run"
    try:
        report = replay.run_evaluation(root, factory, config)
        journal = json.loads((root / "journal.json").read_text())
        row = journal["cases"][manifest["cases"][0]["evaluationId"]]
        assert diagnostic_calls == [component]
        assert row["status"] == "failed" and row["errorCode"] == "invalid_assessment"
        assert row["errorMessage"] == "Unsupported assessment check fields"
        assert row["usage"]["tokens"] == 30 and row["usage"]["costUsd"] != "0"
        assert "reviewShape" not in row and "PRIVATE_DIAGNOSTIC_CONSTRUCTION_FAILURE" not in json.dumps(journal)
        assert report["completedCases"] == 11 and report["budget"]["unknown"] == {"costUsd": "0", "tokens": 0}
        assert report["attempts"] == 12 and report["retries"] == 0
        assert replay.run_evaluation(root, factory, config) == report and len(calls) == 12
        assert diagnostic_calls == [component]
    finally:
        for client in clients:
            client.close()
