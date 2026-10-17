"""Fresh SDK v4 normalization crosses canonical-only persistence boundaries.

The parent guarded runner executes these twelve scenarios. HTTP uses the actual
SDK with MockTransport; original saved worlds and live providers are untouched.
"""
from collections import Counter
from copy import deepcopy
import json
import sqlite3

import pytest

from app.services.world_simulation import consistency_evaluation as directed
from app.services.world_simulation import review as review_module
from app.services.world_simulation.artifacts import atomic_json
from app.services.world_simulation.contracts import WorldError, canonical_json
from app.services.world_simulation.controller import run_round
from app.services.world_simulation.examples import ExamplePolicy, example_spec
from app.services.world_simulation.observations import build_observation
from app.services.world_simulation.store import WorldStore
from test_world_consistency_controller import raw
from test_world_consistency_evaluation import pricing
import test_world_policy as sdk_fixtures


pytestmark = pytest.mark.guarded_runner
actor_case = sdk_fixtures.actor_case
boundary = sdk_fixtures.boundary
V4 = "actor-consistency-v4"
V3 = "actor-consistency-v3"
SLOT = "1:proposal:buyer"
RESPONSE_SLOT = "1:response:producer"
KINDS = ("goal_alignment", "conditional_timing", "quantity_consistency", "explanation_consistency")


def raw_review(style="extra", verdict="consistent"):
    checks = []
    for kind in KINDS:
        check = {"kind": kind, "verdict": verdict}
        if style == "v3":
            check["explanation"] = "The declared decision is checked."
        elif style == "missing_explanation":
            check.update(commentary="PRIVATE_V4 alternative material, preserved without inventing explanation.",
                         fields={"note": "PRIVATE_V4 original fields member remains nested."})
        else:
            check.update(explanation="PRIVATE_V4 supplied explanation.",
                         extraNotes={"commentary": "PRIVATE_V4 contradicts the declared verdict; preserve for human review.",
                                     "status": "unknown"},
                         fields={"claim": "PRIVATE_V4 nested data is not authority.",
                                 "intents": [{"templateId": "invented_action", "parameters": {}}]})
        checks.append(check)
    return {"checks": checks}


def assert_lossless(canonical, original):
    assert set(canonical) == {"checks"}
    assert len(canonical["checks"]) == len(original["checks"]) == 4
    for saved, emitted in zip(canonical["checks"], original["checks"], strict=True):
        assert set(saved) == {"kind", "verdict", "fields"}
        assert {"kind": saved["kind"], "verdict": saved["verdict"], **saved["fields"]} == emitted
        assert saved["fields"] == {key: value for key, value in emitted.items() if key not in {"kind", "verdict"}}
        assert ("explanation" in saved["fields"]) == ("explanation" in emitted)
        if "fields" in emitted:
            assert saved["fields"]["fields"] == emitted["fields"]


def forbid_normalization(*args, **kwargs):
    raise AssertionError("Controller/store/cached replay must not normalize saved assessments")


def sdk_world(actor_case, boundary, *, style="extra", verdict="consistent", missing_verdict=False,
              repair=False, mode=V4):
    spec = example_spec("investment", periods=2)
    spec["policy"] = deepcopy(actor_case.spec["policy"])
    spec["policy"]["decisionReview"] = mode
    if repair:
        spec["policy"]["candidateRepair"] = "known-output-error-v1"
    spec["limits"].update(maxConcurrentCalls=1, maxOutputTokens=512, maxTokens=500000, maxCostUsd="25")
    spec["initialState"]["metrics"]["capacity"]["value"] = "3"
    next(actor for actor in spec["actors"] if actor["actorId"] == "buyer")["objectives"] = ["Buy capacity minus one units."]
    scripted = ExamplePolicy("investment")
    counts, wire_reviews, observations = Counter(), {}, []

    def content(request, _index):
        messages = json.loads(request.content)["messages"]
        observation = json.loads(messages[1]["content"])
        slot = f"{observation['round']}:{observation['phase']}:{observation['actorId']}"
        counts[slot] += 1
        assert counts[slot] <= 2
        observations.append(deepcopy(observation))
        decision = scripted.decide(observation)
        if slot == SLOT:
            quantity = "999999" if repair and counts[slot] == 1 else "2"
            decision["intents"] = [{"templateId": "purchase", "operation": "propose",
                                   "parameters": {"quantity": quantity, "price": quantity}}]
            decision["rationale"] = "Use the declared quantity."
        if counts[slot] == 1:
            return json.dumps(decision)
        assessment = raw_review(style, verdict if slot == SLOT else "consistent")
        if missing_verdict and slot == SLOT:
            assessment["checks"][0].pop("verdict")
        wire_reviews[slot] = deepcopy(assessment)
        return json.dumps({"decision": decision, "assessment": assessment})

    transport = boundary(spec=spec, content_factory=content)
    return spec, transport, counts, wire_reviews, observations


@pytest.mark.parametrize("style", ["extra", "missing_explanation"])
def test_actual_sdk_lossless_fields_remain_private_through_controller_store_and_reopen(
        tmp_path, actor_case, boundary, monkeypatch, style):
    spec, transport, counts, emitted, observations = sdk_world(actor_case, boundary, style=style)
    path = tmp_path / "world.sqlite3"
    with WorldStore(path, spec) as store:
        fence = store.acquire_writer("first")
        head = run_round(store, transport.policy, fence)
        assert head["accounts"]["buyer_stock"]["balance"] == "2"
        assert head["round"] == 1
        receipts = {slot: store.consistency_receipt(slot) for slot in emitted}
        for slot, receipt in receipts.items():
            assert_lossless(receipt["assessment"], emitted[slot])
            assert review_module.assessment_status(receipt["assessment"], mode=V4) == "clear"
        assert set(counts.values()) == {2}
        assert len(transport.sent) == len(store.budget_summary()["attempts"])
        assert all(item["usage"]["tokens"] == 140 for item in store.budget_summary()["attempts"])
        assert "PRIVATE_V4" not in canonical_json(store.read_bundle())
        assert "invented_action" not in canonical_json(store.rounds())
        for actor in spec["actors"]:
            later = build_observation(store.spec, head, actor["actorId"], 2)
            assert "PRIVATE_V4" not in canonical_json(later)
        assert "PRIVATE_V4" not in canonical_json(observations)
        assert all(b"PRIVATE_V4" not in request.content for request in transport.sent)
        assert {intent["templateId"] for intent in store.decision(SLOT)["intents"]} == {"purchase"}
    sent = len(transport.sent)
    monkeypatch.setattr(review_module, "normalize_v4_assessment_output", forbid_normalization)
    with WorldStore(path, read_only=True) as reopened:
        assert reopened.head() == head
        for slot, receipt in receipts.items():
            assert reopened.consistency_receipt(slot) == receipt
            assert_lossless(reopened.consistency_receipt(slot)["assessment"], emitted[slot])
    assert len(transport.sent) == sent


@pytest.mark.parametrize("verdict", ["unknown", "inconsistent"])
def test_v4_nonclear_verdict_is_retained_privately_without_commit_or_third_call(
        tmp_path, actor_case, boundary, monkeypatch, verdict):
    spec, transport, counts, emitted, _ = sdk_world(actor_case, boundary, verdict=verdict)
    path = tmp_path / "world.sqlite3"
    with WorldStore(path, spec) as store:
        fence = store.acquire_writer("first")
        with pytest.raises(WorldError, match="consistency stage"):
            run_round(store, transport.policy, fence)
        retained = store.withheld_consistency_receipt(SLOT)
        assert_lossless(retained["assessment"], emitted[SLOT])
        assert review_module.assessment_status(retained["assessment"], mode=V4) == "unresolved"
        assert store.decision(SLOT) is None and store.consistency_receipt(SLOT) is None
        assert store.head()["round"] == 0 and store.rounds() == []
        attempts = [item for item in store.budget_summary()["attempts"] if item["slot"] == SLOT]
        assert [item["status"] for item in attempts] == ["succeeded", "failed"]
        assert all(item["usage"]["tokens"] == 140 for item in attempts)
        assert "PRIVATE_V4" not in canonical_json(store.read_bundle())
    before = len(transport.sent)
    monkeypatch.setattr(review_module, "normalize_v4_assessment_output", forbid_normalization)
    with WorldStore(path) as resumed:
        assert resumed.withheld_consistency_receipt(SLOT) == retained
        fence = resumed.acquire_writer("resume")
        with pytest.raises(WorldError):
            run_round(resumed, transport.policy, fence)
        assert resumed.head()["round"] == 0
    assert len(transport.sent) == before and counts[SLOT] == 2


def test_missing_v4_verdict_is_not_synthesized_from_retained_commentary(tmp_path, actor_case, boundary):
    spec, transport, counts, _, _ = sdk_world(actor_case, boundary, missing_verdict=True)
    path = tmp_path / "world.sqlite3"
    with WorldStore(path, spec) as store:
        fence = store.acquire_writer("first")
        with pytest.raises(WorldError):
            run_round(store, transport.policy, fence)
        assert store.decision(SLOT) is None and store.withheld_consistency_receipt(SLOT) is None
        assert store.head()["round"] == 0 and counts[SLOT] == 2
        failed = [item for item in store.budget_summary()["attempts"] if item["slot"] == SLOT][-1]
        assert failed["status"] == "failed" and failed["usage"]["tokens"] == 140
        assert failed["errorCode"] == "invalid_assessment"
    before = len(transport.sent)
    with WorldStore(path) as store:
        fence = store.acquire_writer("resume")
        with pytest.raises(WorldError):
            run_round(store, transport.policy, fence)
        assert store.decision(SLOT) is None
    assert len(transport.sent) == before


def test_cached_v4_final_receipts_resume_without_normalization_or_dispatch(tmp_path, actor_case, boundary, monkeypatch):
    spec, transport, _, emitted, _ = sdk_world(actor_case, boundary, style="missing_explanation")
    path = tmp_path / "world.sqlite3"
    with WorldStore(path, spec) as store:
        fence = store.acquire_writer("first")
        with pytest.raises(WorldError) as error:
            run_round(store, transport.policy, fence, cancelled=lambda: store.decision(RESPONSE_SLOT) is not None)
        assert error.value.code == "cancelled"
        assert store.head()["round"] == 0
        receipts = {slot: store.consistency_receipt(slot) for slot in emitted}
        assert receipts[RESPONSE_SLOT] is not None
        budget = store.budget_summary()
    before = len(transport.sent)
    monkeypatch.setattr(review_module, "normalize_v4_assessment_output", forbid_normalization)
    monkeypatch.setattr(transport.policy, "decide", lambda *args, **kwargs: pytest.fail("Cached final receipt dispatched again"))
    with WorldStore(path) as store:
        fence = store.acquire_writer("resume")
        assert run_round(store, transport.policy, fence)["accounts"]["buyer_stock"]["balance"] == "2"
        assert store.budget_summary() == budget
        for slot, receipt in receipts.items():
            assert store.consistency_receipt(slot) == receipt
            assert_lossless(receipt["assessment"], emitted[slot])
    assert len(transport.sent) == before


@pytest.mark.parametrize("tamper", ["raw_wire_in_v4", "canonical_v4_in_v3"])
def test_saved_assessment_reader_never_normalizes_or_accepts_another_mode(
        tmp_path, actor_case, boundary, monkeypatch, tamper):
    mode = V4 if tamper == "raw_wire_in_v4" else V3
    spec, transport, _, emitted, _ = sdk_world(actor_case, boundary, mode=mode, style="extra" if mode == V4 else "v3")
    path = tmp_path / "world.sqlite3"
    with WorldStore(path, spec) as store:
        fence = store.acquire_writer("first")
        run_round(store, transport.policy, fence)
        entry = store._verified_consistency(SLOT)[1][-1]
        if tamper == "raw_wire_in_v4":
            entry["assessment"] = deepcopy(emitted[SLOT])
        else:
            entry["assessment"] = {"checks": [{"kind": check["kind"], "verdict": check["verdict"],
                "fields": {"explanation": check["explanation"]}} for check in emitted[SLOT]["checks"]]}
        changed_hash = store._consistency_hash(entry)
    with sqlite3.connect(path) as corrupt:
        corrupt.execute("UPDATE consistency_journal SET assessment=?,receipt_hash=? WHERE attempt_id=?",
                        (canonical_json(entry["assessment"]), changed_hash, entry["attempt_id"]))
    before = len(transport.sent)
    monkeypatch.setattr(review_module, "normalize_v4_assessment_output", forbid_normalization)
    with pytest.raises(WorldError):
        WorldStore(path, read_only=True)
    assert len(transport.sent) == before


def test_v4_actual_sdk_controlled_candidate_repair_keeps_two_original_slot_calls(tmp_path, actor_case, boundary):
    spec, transport, counts, emitted, _ = sdk_world(actor_case, boundary, repair=True)
    path = tmp_path / "world.sqlite3"
    with WorldStore(path, spec) as store:
        fence = store.acquire_writer("first")
        assert run_round(store, transport.policy, fence)["accounts"]["buyer_stock"]["balance"] == "2"
        assert counts[SLOT] == 2
        receipt = store.consistency_receipt(SLOT)
        assert receipt["reviewInputKind"] == "candidate_error" and receipt["candidate"] is None
        assert receipt["reviewInput"]["errorCode"] == "invalid_input"
        assert_lossless(receipt["assessment"], emitted[SLOT])
        attempts = [item for item in store.budget_summary()["attempts"] if item["slot"] == SLOT]
        assert [item["ordinal"] for item in attempts] == [1, 2]
        assert [item["status"] for item in attempts] == ["failed", "succeeded"]
        assert all(item["usage"]["tokens"] == 140 for item in attempts)
        assert attempts[1]["reviewInputKind"] == "candidate_error"
    before = len(transport.sent)
    with WorldStore(path, read_only=True) as store:
        assert store.consistency_receipt(SLOT) == receipt
    assert len(transport.sent) == before


@pytest.mark.parametrize("outcome", ["clear", "unknown", "missing_verdict"])
def test_directed_v4_journal_reads_canonical_fields_only_and_preserves_scores_and_privacy(
        tmp_path, boundary, monkeypatch, outcome):
    config = pricing()
    config["policy"]["decisionReview"] = V4
    manifest = directed.preregister(config, "1.25")
    config["authorization"] = {"manifestHash": manifest["manifestHash"], "offlineGatesPassed": True,
                               "pricingVerified": True, "evidenceRefs": ["fixture://v4-canonical-reader"]}
    sent, emitted = [], {}

    def content(request, _index):
        case = manifest["cases"][len(sent)]
        sent.append(request.content)
        obs = json.loads(json.loads(request.content)["messages"][1]["content"])
        assert obs == case["actorPayload"]["observation"]
        value = raw(case["actorPayload"]["candidateDecision"])
        if case["caseId"] == "investment-rationale-action-disagreement":
            value["intents"][0]["parameters"] = {"quantity": "2", "price": "2"}
        elif case["caseId"] == "coalition-opposition-before-trigger":
            value.update(intents=[], status="wait", rationale="The declared conditional trigger is not met.")
        assessment = raw_review("missing_explanation", "unknown" if outcome == "unknown" and len(sent) == 1 else "consistent")
        if outcome == "missing_verdict" and len(sent) == 1:
            assessment["checks"][0].pop("verdict")
        emitted[case["evaluationId"]] = deepcopy(assessment)
        return json.dumps({"decision": value, "assessment": assessment})

    def factory(spec):
        return boundary(spec=spec, content_factory=content).policy

    factory.evaluation_mode = "external"
    root = tmp_path / "directed"
    report = directed.run_evaluation(root, factory, config)
    journal = json.loads((root / "journal.json").read_text())
    assert len(sent) == report["attempts"] == 12 and report["retries"] == 0
    assert report["completedCases"] == report["matchedCases"] == (12 if outcome == "clear" else 11)
    assert report["diagnosticGate"] == "incomplete" and report["promotionAuthorized"] is False
    assert report["budget"]["unknown"] == {"tokens": 0, "costUsd": "0"}
    assert "PRIVATE_V4" not in canonical_json(report) and "reviewShape" not in canonical_json(journal)
    for case in manifest["cases"]:
        row = journal["cases"][case["evaluationId"]]
        if row["status"] == "completed":
            assert_lossless(row["assessment"], emitted[case["evaluationId"]])
        elif outcome == "unknown":
            assert row["errorCode"] == "consistency_unresolved" and "assessment" not in row and "matches" not in row
            assert_lossless(row["withheldReview"]["assessment"], emitted[case["evaluationId"]])
        else:
            assert row["errorCode"] == "invalid_assessment" and "withheldReview" not in row and "assessment" not in row
        assert row["usage"]["tokens"] == 140
    monkeypatch.setattr(review_module, "normalize_v4_assessment_output", forbid_normalization)
    assert directed.summarize_evaluation(root) == report
    assert directed.run_evaluation(root, factory, config) == report and len(sent) == 12
    # A structurally valid raw wire assessment is not a canonical durable record.
    case = next(case for case in manifest["cases"] if journal["cases"][case["evaluationId"]]["status"] == "completed")
    journal["cases"][case["evaluationId"]]["assessment"] = emitted[case["evaluationId"]]
    before_report = (root / "report.json").read_bytes()
    atomic_json(root / "journal.json", journal)
    with pytest.raises(WorldError):
        directed.summarize_evaluation(root)
    with pytest.raises(WorldError):
        directed.run_evaluation(root, factory, config)
    assert len(sent) == 12 and (root / "report.json").read_bytes() == before_report
