"""An unresolved consistency revision commits its decision flagged instead of ending the run.

Before the fix, a validated revision whose self-assessment stayed unresolved (an unknown or
inconsistent verdict) raised required_decision_failed, and resume refused the slot with
consistency_revision_exhausted: the world could never pass that round (model-facing review
M1). Now the revision is still recorded as failed with code consistency_unresolved and its
withheld receipt is kept, and its decision is committed with consistencyStatus "unresolved".
Temporary stores and scripted policies only, so both suites run this module.
"""
from copy import deepcopy

import pytest

from app.services.world_simulation.contracts import WorldError, canonical_json, validate_decision, validate_spec
from app.services.world_simulation.controller import run_round
from app.services.world_simulation.kernel import resolve_round
from app.services.world_simulation.observations import build_observation
from app.services.world_simulation.review import MODE, MODE_V2, MODE_V3, MODE_V4
from app.services.world_simulation.store import WorldStore
from test_world_consistency_controller import RevisingPolicy, specification

SLOT = "1:proposal:alice"
KNOWN = {"tokens": 10, "costUsd": "0.1"}
KINDS = ("goal_alignment", "conditional_timing", "quantity_consistency", "explanation_consistency")
BASIS = {"kind": "scenario_assumption", "refs": ["unresolved-commit-test/v1"]}


def world(mode):
    return validate_spec({
        "schemaVersion": "simulation-world-spec/v1", "engine": "world-v1",
        "simulationId": "unresolved-commit", "generationId": "unresolved-generation",
        "actors": [{"actorId": "alice", "name": "Alice", "objectives": ["Use admitted mechanisms"], "values": [],
                    "incentives": [], "constraints": [], "beliefs": [], "capabilities": ["wait"],
                    "evidenceGrade": "scenario-assumption", "basis": deepcopy(BASIS)}],
        "actionCatalog": [{"templateId": "wait", "kind": "wait", "actorIds": ["alice"], "parameters": {},
                           "basis": deepcopy(BASIS)}],
        "periods": [{"start": f"2030-01-0{day}T00:00:00Z", "end": f"2030-01-0{day + 1}T00:00:00Z"} for day in (1, 2)],
        "initialState": {"accounts": {}, "metrics": {}, "rules": {}, "relations": {}},
        "limits": {"maxAttemptsPerSlot": 2, "maxTokens": 100, "maxCostUsd": "1"},
        "policy": {"decisionReview": mode}})


def assessment(mode, verdict):
    """A structurally valid assessment in ``mode`` whose aggregate is unresolved unless consistent."""
    if mode in {MODE_V3, MODE_V4}:
        detail = ({"explanation": "PRIVATE_UNRESOLVED_REVIEW"} if mode == MODE_V3
                  else {"fields": {"note": "PRIVATE_UNRESOLVED_REVIEW"}})
        return {"checks": [{"kind": kind, "verdict": verdict if kind == "conditional_timing" else "consistent", **detail}
                           for kind in KINDS]}
    checks = [{"kind": kind, "explanation": "PRIVATE_UNRESOLVED_REVIEW"} for kind in KINDS]
    if mode == MODE:
        for check in checks:
            check.update(objectiveIndices=[0] if check["kind"] == "goal_alignment" else [],
                         intentIndices=[], evidencePaths=[["actor", "objectives", 0]])
    return {"status": "clear" if verdict == "consistent" else "unresolved", "checks": checks}


def wait_decision(store, rationale):
    observation = store.observation(SLOT)
    return validate_decision(store.spec, {"actorId": "alice", "observationId": observation["observationId"],
                                          "intents": [], "rationale": rationale}, "alice", observation, phase="proposal")


def unresolved_revision(store, fence, mode, verdict):
    store.freeze_phase(1, "proposal", ["alice"], fence)
    store.save_observation(SLOT, build_observation(store.spec, store.head(), "alice", 1), fence)
    attempt = store.reserve_consistency_attempt(SLOT, "candidate", fence, 20, "0.2")
    store.finish_consistency_attempt(attempt, status="succeeded", usage=KNOWN, fence=fence,
                                     decision=wait_decision(store, "Candidate waits."))
    attempt = store.reserve_consistency_attempt(SLOT, "revision", fence, 30, "0.3")
    final = wait_decision(store, "Final decision waits.")
    store.finish_consistency_attempt(attempt, status="failed", usage=KNOWN, fence=fence, decision=final,
                                     assessment=assessment(mode, verdict),
                                     error={"code": "consistency_unresolved", "message": "Private concern"})
    return final


@pytest.mark.parametrize("mode,verdict", [(MODE, "unresolved"), (MODE_V2, "unresolved"),
                                          (MODE_V3, "unknown"), (MODE_V3, "inconsistent"),
                                          (MODE_V4, "unknown"), (MODE_V4, "inconsistent")])
def test_unresolved_revision_is_committed_flagged_and_keeps_its_withheld_receipt(tmp_path, mode, verdict):
    path = tmp_path / "world.sqlite3"
    with WorldStore(path, world(mode)) as store:
        fence = store.acquire_writer("owner")
        final = unresolved_revision(store, fence, mode, verdict)
        flagged = {**final, "consistencyStatus": "unresolved"}
        assert store.decision(SLOT) == flagged
        withheld = store.withheld_consistency_receipt(SLOT)
        assert withheld["state"] == "withheld" and withheld["withheldDecision"] == final
        assert store.consistency_receipt(SLOT) is None  # Only a cleared revision has a final receipt.
        attempts = [a for a in store.budget_summary()["attempts"] if a["slot"] == SLOT]
        assert [(a["purpose"], a["status"]) for a in attempts] == [("candidate", "succeeded"), ("revision", "failed")]
        assert attempts[-1]["errorCode"] == "consistency_unresolved"
        with pytest.raises(WorldError) as caught:  # Still no third call.
            store.reserve_consistency_attempt(SLOT, "revision", fence)
        assert caught.value.code == "decision_already_saved"
        store.freeze_phase(1, "response", [], fence)
        result = resolve_round(store.spec, store.head(), [flagged], 1)
        store.commit_round(0, result["snapshot"], result["events"], result["resolutions"], [flagged], fence)
        assert store.read_bundle()["rounds"][0]["decisions"] == [flagged]
        assert "PRIVATE_UNRESOLVED_REVIEW" not in canonical_json(store.read_bundle())
    with WorldStore(path, read_only=True) as reopened:
        assert reopened.decision(SLOT) == flagged and reopened.withheld_consistency_receipt(SLOT) == withheld


def test_flag_cannot_be_forged_on_a_cleared_revision(tmp_path):
    import sqlite3

    path = tmp_path / "world.sqlite3"
    with WorldStore(path, world(MODE_V3)) as store:
        fence = store.acquire_writer("owner")
        store.freeze_phase(1, "proposal", ["alice"], fence)
        store.save_observation(SLOT, build_observation(store.spec, store.head(), "alice", 1), fence)
        attempt = store.reserve_consistency_attempt(SLOT, "candidate", fence, 20, "0.2")
        store.finish_consistency_attempt(attempt, status="succeeded", usage=KNOWN, fence=fence,
                                         decision=wait_decision(store, "Candidate waits."))
        attempt = store.reserve_consistency_attempt(SLOT, "revision", fence, 30, "0.3")
        final = wait_decision(store, "Final decision waits.")
        store.finish_consistency_attempt(attempt, status="succeeded", usage=KNOWN, fence=fence, decision=final,
                                         assessment=assessment(MODE_V3, "consistent"))
        assert store.decision(SLOT) == final
    forged = {**final, "consistencyStatus": "unresolved"}
    with sqlite3.connect(path) as db:
        db.execute("UPDATE slots SET decision=? WHERE slot=?", (canonical_json(forged), SLOT))
    db.close()
    with pytest.raises(WorldError) as caught:
        WorldStore(path, read_only=True)
    assert caught.value.code == "corrupt_consistency_journal"


def test_unresolved_revision_no_longer_stops_the_round(tmp_path):
    class Unresolved(RevisingPolicy):
        def decide(self, obs, *, review=None):
            result = super().decide(obs, review=review)
            if review is not None and obs["actorId"] == "buyer":
                result.assessment["status"] = "unresolved"
            return result

    policy = Unresolved("investment")
    path = tmp_path / "world.sqlite3"
    with WorldStore(path, specification()) as store:
        head = run_round(store, policy, store.acquire_writer("first"))
        assert head["round"] == 1
        buyer = store.decision("1:proposal:buyer")
        assert buyer["consistencyStatus"] == "unresolved"
        assert buyer in store.rounds()[0]["decisions"]
        assert store.withheld_consistency_receipt("1:proposal:buyer")["withheldDecision"] == {
            key: value for key, value in buyer.items() if key != "consistencyStatus"}
        # The revised (withheld) decision acts: two units, not the candidate's three.
        assert head["accounts"]["buyer_stock"]["balance"] == "2"
        assert [c[2] for c in policy.calls if c[:2] == ("buyer", "proposal")] == [False, True]
