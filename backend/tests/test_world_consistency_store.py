"""Pinned consistency journal acceptance; executed only by the parent's guard.

Temporary SQLite faults simulate persistence boundaries. No original run,
provider, process kill, or SDK transport is involved.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import sqlite3
import threading
from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.guarded_runner
SLOT = "1:proposal:alice"
ZERO = {"tokens": 0, "costUsd": "0"}


@pytest.fixture
def api():
    from app.services.world_simulation import store as module
    from app.services.world_simulation.contracts import canonical_json, digest, validate_decision, validate_spec
    from app.services.world_simulation.kernel import resolve_round
    from app.services.world_simulation.observations import build_observation
    from app.services.world_simulation.review import MODE

    return SimpleNamespace(Store=module.WorldStore, Error=module.WorldError, module=module, mode=MODE,
                           canonical=canonical_json, digest=digest, validate_decision=validate_decision,
                           validate_spec=validate_spec, resolve=resolve_round, observe=build_observation)


@pytest.fixture
def spec(api):
    basis = {"kind": "scenario_assumption", "refs": ["consistency-store-test/v1"]}
    actors = [{"actorId": aid, "name": aid, "objectives": ["Use only declared resources"],
               "values": [], "incentives": [], "constraints": [], "beliefs": [], "capabilities": ["wait"],
               "evidenceGrade": "scenario-assumption", "basis": deepcopy(basis)} for aid in ("alice", "bob")]
    return api.validate_spec({"schemaVersion": "simulation-world-spec/v1", "engine": "world-v1",
        "simulationId": "consistency-store-test", "generationId": "consistency-generation", "actors": actors,
        "periods": [{"start": f"2030-01-0{day}T00:00:00Z", "end": f"2030-01-0{day + 1}T00:00:00Z"} for day in (1, 2)],
        "initialState": {"accounts": {}, "metrics": {}, "rules": {}, "relations": {}},
        "actionCatalog": [{"templateId": "wait", "kind": "wait", "actorIds": ["alice", "bob"], "parameters": {}, "basis": basis}],
        "limits": {"maxAttemptsPerSlot": 2, "maxTokens": 100, "maxCostUsd": "1"},
        "policy": {"decisionReview": api.mode}})


def setup_slot(api, store, fence, *, actors=("alice",), round_index=1):
    store.freeze_phase(round_index, "proposal", list(actors), fence)
    for actor in actors:
        observation = api.observe(store.spec, store.head(), actor, round_index, "proposal")
        store.save_observation(f"{round_index}:proposal:{actor}", observation, fence)


def normalized(api, store, *, slot=SLOT, draft=False):
    obs = store.observation(slot)
    return api.validate_decision(store.spec, {"actorId": obs["actorId"], "observationId": obs["observationId"],
        "intents": [{"templateId": "wait"}] if draft else [],
        "rationale": "DRAFT_PRIVATE_SENTINEL" if draft else "The final decision waits."},
        obs["actorId"], obs, phase=obs["phase"])


def assessment(store, final, *, status="clear"):
    obs = store.observation(f"{final['round']}:{final['phase']}:{final['actorId']}")
    return {"status": status, "checks": [{"kind": kind,
        "objectiveIndices": list(range(len(obs["actor"]["objectives"]))) if kind == "goal_alignment" else [],
        "intentIndices": list(range(len(final["intents"]))) if kind == "explanation_consistency" else [],
        "evidencePaths": [["actor", "objectives", 0]], "explanation": f"AUDIT_PRIVATE_SENTINEL {kind}"}
        for kind in ("goal_alignment", "conditional_timing", "quantity_consistency", "explanation_consistency")]}


def candidate(api, store, fence, *, slot=SLOT, tokens=20, cost="0.2", usage=None):
    decision = normalized(api, store, slot=slot, draft=True)
    attempt = store.reserve_consistency_attempt(slot, "candidate", fence, tokens, cost)
    store.finish_consistency_attempt(attempt, status="succeeded", usage=usage or {"tokens": 10, "costUsd": "0.1"},
                                     fence=fence, decision=decision)
    return attempt, decision


def final_revision(api, store, fence, *, slot=SLOT):
    attempt = store.reserve_consistency_attempt(slot, "revision", fence, 30, "0.3")
    final = normalized(api, store, slot=slot)
    review = assessment(store, final)
    store.finish_consistency_attempt(attempt, status="succeeded", usage={"tokens": 15, "costUsd": "0.15"},
                                     fence=fence, decision=final, assessment=review)
    return attempt, final, review


def commit_wait_round(api, store, fence, final):
    store.freeze_phase(1, "response", [], fence)
    resolved = api.resolve(store.spec, store.head(), [final], 1)
    store.commit_round(0, resolved["snapshot"], resolved["events"], resolved["resolutions"], [final], fence)


def fails(api, code, call):
    with pytest.raises(api.Error) as error:
        call()
    assert error.value.code == code


def test_candidate_private_final_atomic_receipt_survives_commit_and_readonly_reopen(api, spec, tmp_path):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as store:
        fence = store.acquire_writer("owner")
        setup_slot(api, store, fence)
        assert store.consistency_state(SLOT) == {"candidate": None, "candidateAttempt": None, "reviewAttempt": None}
        assert store.consistency_receipt(SLOT) is None
        draft_attempt, draft = candidate(api, store, fence)
        assert store.decision(SLOT) is None
        assert store.consistency_receipt(SLOT) is None
        state = store.consistency_state(SLOT)
        assert state == {"candidate": draft, "candidateAttempt": {"attemptId": draft_attempt, "status": "succeeded", "stage": "candidate"}, "reviewAttempt": None}
        state["candidate"]["rationale"] = "caller mutation"
        assert store.consistency_state(SLOT)["candidate"] == draft
        review_attempt, final, review = final_revision(api, store, fence)
        assert final["intents"] == [] and draft["intents"]
        assert store.decision(SLOT) == final
        receipt = store.consistency_receipt(SLOT)
        assert receipt["candidate"] == draft and receipt["candidateHash"] == api.digest(draft)
        assert receipt["finalDecisionHash"] == api.digest(final) and receipt["assessment"] == review
        assert receipt["observationHash"] == api.digest(store.observation(SLOT))
        assert [item["attemptId"] for item in receipt["stages"]] == [draft_attempt, review_attempt]
        assert [item["stage"] for item in receipt["stages"]] == ["candidate", "revision"]
        assert receipt["stages"][1]["usage"] == {"tokens": 15, "costUsd": "0.15"}
        changed = store.consistency_receipt(SLOT)
        changed["assessment"]["checks"][0]["explanation"] = "caller mutation"
        assert store.consistency_receipt(SLOT) == receipt
        budget = store.budget_summary()
        assert [item["ordinal"] for item in budget["attempts"]] == [1, 2]
        assert [item["purpose"] for item in budget["attempts"]] == ["candidate", "revision"]
        assert {item["slot"] for item in budget["attempts"]} == {SLOT}
        assert budget["actual"] == {"tokens": 25, "costUsd": "0.25"}
        assert budget["unknown"] == ZERO
        commit_wait_round(api, store, fence, final)
        bundle = store.read_bundle()
        exported = api.canonical(bundle)
        assert "DRAFT_PRIVATE_SENTINEL" not in exported and "AUDIT_PRIVATE_SENTINEL" not in exported
        assert bundle["rounds"][0]["decisions"] == [final]
    with api.Store(path, read_only=True) as store:
        assert store.consistency_receipt(SLOT) == receipt
        assert store.decision(SLOT) == final and store.read_bundle() == bundle
        fails(api, "read_only", lambda: store.reserve_consistency_attempt("2:proposal:alice", "candidate", fence))


def test_legacy_apis_cannot_bypass_review_admission(api, spec, tmp_path):
    with api.Store(tmp_path / "world.sqlite", spec) as store:
        fence = store.acquire_writer("owner")
        setup_slot(api, store, fence)
        draft = normalized(api, store, draft=True)
        fails(api, "consistency_admission_required", lambda: store.save_decision(SLOT, draft, fence))
        fails(api, "consistency_admission_required", lambda: store.reserve_attempt(SLOT, fence))
        attempt = store.reserve_consistency_attempt(SLOT, "candidate", fence)
        fails(api, "consistency_admission_required", lambda: store.finish_attempt(attempt, "succeeded", ZERO, fence))
        assert store.decision(SLOT) is None
        assert store.consistency_state(SLOT)["candidate"] is None


@pytest.mark.parametrize("stage", ["candidate", "revision"])
@pytest.mark.parametrize("outcome", ["reserved", "unknown", "failed"])
def test_lost_or_failed_stage_never_regains_allowance_on_resume(api, spec, tmp_path, stage, outcome):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as store:
        fence = store.acquire_writer("owner")
        setup_slot(api, store, fence)
        if stage == "revision":
            candidate(api, store, fence)
        attempt = store.reserve_consistency_attempt(SLOT, stage, fence, 30, "0.3")
        if outcome != "reserved":
            store.finish_consistency_attempt(attempt, status=outcome, usage={"tokens": 7, "costUsd": "0.07"}, fence=fence,
                error={"code": "policy_decision_failed", "message": "provider-secret-SENTINEL should not persist"})
        before = store.budget_summary()
    with api.Store(path) as store:
        fence = store.acquire_writer("resume")
        assert store.budget_summary() == before
        assert store.decision(SLOT) is None
        assert store.consistency_receipt(SLOT) is None
        for next_stage in ("candidate", "revision"):
            fails(api, "consistency_stage_exhausted", lambda next_stage=next_stage: store.reserve_consistency_attempt(SLOT, next_stage, fence))
        if outcome in {"reserved", "unknown"}:
            assert before["unknown"] == {"tokens": 30, "costUsd": "0.3"}
        else:
            assert before["unknown"] == ZERO
        assert before["attempts"][-1]["purpose"] == stage
        if outcome != "reserved":
            assert before["attempts"][-1]["errorCode"] == "policy_decision_failed"
        with sqlite3.connect(path) as audit:
            errors = audit.execute("SELECT error FROM consistency_journal").fetchall()
        assert "provider-secret-SENTINEL" not in str(errors)


def test_revision_requires_completed_candidate_and_no_third_call(api, spec, tmp_path):
    with api.Store(tmp_path / "world.sqlite", spec) as store:
        fence = store.acquire_writer("owner")
        fails(api, "phase_not_frozen", lambda: store.reserve_consistency_attempt(SLOT, "candidate", fence))
        store.freeze_phase(1, "proposal", ["alice"], fence)
        fails(api, "missing_observation", lambda: store.reserve_consistency_attempt(SLOT, "candidate", fence))
        setup_slot(api, store, fence)
        fails(api, "invalid_consistency_stage", lambda: store.reserve_consistency_attempt(SLOT, "repair", fence))
        fails(api, "consistency_stage_exhausted", lambda: store.reserve_consistency_attempt(SLOT, "revision", fence))
        draft_id, _ = candidate(api, store, fence)
        fails(api, "consistency_stage_exhausted", lambda: store.reserve_consistency_attempt(SLOT, "candidate", fence))
        final_revision(api, store, fence)
        fails(api, "decision_already_saved", lambda: store.reserve_consistency_attempt(SLOT, "revision", fence))
        assert store.budget_summary()["attempts"][0]["attemptId"] == draft_id
        assert len(store.budget_summary()["attempts"]) == 2


def test_candidate_success_resumes_revision_after_simulated_crash_without_replacement(api, spec, tmp_path, monkeypatch):
    path = tmp_path / "world.sqlite"
    crashed = api.Store(path, spec)
    old_fence = crashed.acquire_writer("crashed")
    setup_slot(api, crashed, old_fence)
    attempt, draft = candidate(api, crashed, old_fence)
    crashed._db.close()  # Simulate process loss without orderly writer release.
    crashed._closed = True
    monkeypatch.setattr(api.module, "_alive", lambda pid: False)
    with api.Store(path) as resumed:
        fence = resumed.acquire_writer("replacement", takeover=True)
        assert fence > old_fence
        assert resumed.consistency_state(SLOT)["candidate"] == draft
        final_revision(api, resumed, fence)
        assert len(resumed.budget_summary()["attempts"]) == 2
        assert resumed.budget_summary()["attempts"][0]["attemptId"] == attempt


@pytest.mark.parametrize("stage", ["candidate", "revision"])
def test_sql_fault_cannot_split_usage_from_private_or_final_payload(api, spec, tmp_path, stage):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as store:
        fence = store.acquire_writer("owner")
        setup_slot(api, store, fence)
        if stage == "revision":
            candidate(api, store, fence)
        attempt = store.reserve_consistency_attempt(SLOT, stage, fence, 20, "0.2")
        final = normalized(api, store, draft=stage == "candidate")
        review = assessment(store, final) if stage == "revision" else None
        before = store.budget_summary(), store.consistency_state(SLOT)
        trigger = ("CREATE TRIGGER fail_consistency BEFORE UPDATE OF decision ON slots " if stage == "revision" else
                   "CREATE TRIGGER fail_consistency BEFORE UPDATE OF decision ON consistency_journal ")
        with sqlite3.connect(path) as fault:
            fault.execute(trigger + "BEGIN SELECT RAISE(ABORT, 'injected atomic failure'); END")
        with pytest.raises(sqlite3.IntegrityError, match="injected atomic failure"):
            store.finish_consistency_attempt(attempt, status="succeeded", usage={"tokens": 8, "costUsd": "0.08"},
                                             fence=fence, decision=final, assessment=review)
        assert (store.budget_summary(), store.consistency_state(SLOT)) == before
        assert store.decision(SLOT) is None
        with sqlite3.connect(path) as fault:
            fault.execute("DROP TRIGGER fail_consistency")
        store.finish_consistency_attempt(attempt, status="succeeded", usage={"tokens": 8, "costUsd": "0.08"},
                                         fence=fence, decision=final, assessment=review)
        assert store.consistency_state(SLOT)["candidateAttempt" if stage == "candidate" else "reviewAttempt"]["status"] == "succeeded"


def test_reservation_and_stage_purpose_rollback_together_before_dispatch(api, spec, tmp_path):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as store:
        fence = store.acquire_writer("owner")
        setup_slot(api, store, fence)
        with sqlite3.connect(path) as fault:
            fault.execute("CREATE TRIGGER fail_reservation BEFORE INSERT ON consistency_journal BEGIN SELECT RAISE(ABORT, 'injected reservation failure'); END")
        with pytest.raises(sqlite3.IntegrityError, match="injected reservation failure"):
            store.reserve_consistency_attempt(SLOT, "candidate", fence, 20, "0.2")
        assert store.budget_summary()["attempts"] == []
        assert store.consistency_state(SLOT)["candidateAttempt"] is None
        with sqlite3.connect(path) as fault:
            fault.execute("DROP TRIGGER fail_reservation")
        store.reserve_consistency_attempt(SLOT, "candidate", fence, 20, "0.2")
        assert store.budget_summary()["attempts"][0]["ordinal"] == 1


def test_exact_finish_repeat_is_readonly_and_conflicts_do_not_change_receipts(api, spec, tmp_path):
    with api.Store(tmp_path / "world.sqlite", spec) as store:
        fence = store.acquire_writer("owner")
        setup_slot(api, store, fence)
        draft_id, draft = candidate(api, store, fence)
        attempt, final, review = final_revision(api, store, fence)
        receipt = store.consistency_receipt(SLOT)
        statements = []
        store._db.set_trace_callback(statements.append)
        store.finish_consistency_attempt(draft_id, status="succeeded", usage={"tokens": 10, "costUsd": "0.1"}, fence=fence, decision=draft)
        store.finish_consistency_attempt(attempt, status="succeeded", usage={"tokens": 15, "costUsd": "0.15"}, fence=fence, decision=final, assessment=review)
        store._db.set_trace_callback(None)
        assert not any(sql.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")) for sql in statements)
        changed = deepcopy(final)
        changed["rationale"] = "different final response"
        fails(api, "attempt_conflict", lambda: store.finish_consistency_attempt(attempt, status="succeeded", usage={"tokens": 15, "costUsd": "0.15"}, fence=fence, decision=changed, assessment=review))
        fails(api, "attempt_conflict", lambda: store.finish_consistency_attempt(attempt, status="succeeded", usage={"tokens": 14, "costUsd": "0.15"}, fence=fence, decision=final, assessment=review))
        assert store.consistency_receipt(SLOT) == receipt


@pytest.mark.parametrize("invalid", ["unresolved", "evidence", "missing_check", "wrong_observation", "wrong_actor", "raw_decision", "overuse", "error_on_success"])
def test_invalid_revision_cannot_admit_and_known_failure_usage_is_retained(api, spec, tmp_path, invalid):
    with api.Store(tmp_path / "world.sqlite", spec) as store:
        fence = store.acquire_writer("owner")
        setup_slot(api, store, fence)
        candidate(api, store, fence)
        attempt = store.reserve_consistency_attempt(SLOT, "revision", fence, 30, "0.3")
        final = normalized(api, store)
        review = assessment(store, final)
        usage, error = {"tokens": 15, "costUsd": "0.15"}, None
        if invalid == "unresolved":
            review["status"] = "unresolved"
        elif invalid == "evidence":
            review["checks"][0]["evidencePaths"] = [["world", "missing"]]
        elif invalid == "missing_check":
            review["checks"].pop()
        elif invalid in {"wrong_observation", "wrong_actor"}:
            final["observationId" if invalid == "wrong_observation" else "actorId"] = "another"
        elif invalid == "raw_decision":
            final.pop("decisionId")
        elif invalid == "overuse":
            usage["tokens"] = 31
        else:
            error = {"code": "unexpected_error", "message": "not a successful completion"}
        before = store.budget_summary()
        with pytest.raises(api.Error):
            store.finish_consistency_attempt(attempt, status="succeeded", usage=usage, fence=fence, decision=final, assessment=review, error=error)
        assert store.budget_summary() == before and store.decision(SLOT) is None
        store.finish_consistency_attempt(attempt, status="failed", usage={"tokens": 15, "costUsd": "0.15"}, fence=fence,
                                         error={"code": "invalid_assessment", "message": "Known failure"})
        assert store.budget_summary()["actual"] == {"tokens": 25, "costUsd": "0.25"}
        assert store.budget_summary()["unknown"] == ZERO
        assert store.consistency_state(SLOT)["reviewAttempt"]["status"] == "failed"


@pytest.mark.parametrize("mutation", ["candidate", "assessment", "observation", "usage", "purpose", "predecessor", "final", "delete_revision", "drop_journal"])
def test_journal_tampering_denies_state_decision_and_readonly_reopen(api, spec, tmp_path, mutation):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as store:
        fence = store.acquire_writer("owner")
        setup_slot(api, store, fence)
        draft_id, _ = candidate(api, store, fence)
        final_id, _, _ = final_revision(api, store, fence)
        with sqlite3.connect(path) as corrupt:
            if mutation == "candidate":
                corrupt.execute("UPDATE consistency_journal SET decision='{}' WHERE attempt_id=?", (draft_id,))
            elif mutation == "assessment":
                corrupt.execute("UPDATE consistency_journal SET assessment='{}' WHERE attempt_id=?", (final_id,))
            elif mutation == "observation":
                obs = store.observation(SLOT)
                obs["privateState"]["plans"] = ["tampered"]
                corrupt.execute("UPDATE slots SET observation=? WHERE slot=?", (api.canonical(obs), SLOT))
            elif mutation == "usage":
                corrupt.execute("UPDATE attempts SET usage=? WHERE attempt_id=?", (json.dumps(ZERO), final_id))
            elif mutation == "purpose":
                corrupt.execute("UPDATE attempts SET ordinal=3 WHERE attempt_id=?", (draft_id,))
            elif mutation == "predecessor":
                corrupt.execute("UPDATE consistency_journal SET candidate_hash='wrong' WHERE attempt_id=?", (final_id,))
            elif mutation == "final":
                corrupt.execute("UPDATE slots SET decision='{}' WHERE slot=?", (SLOT,))
            elif mutation == "delete_revision":
                corrupt.execute("DELETE FROM consistency_journal WHERE attempt_id=?", (final_id,))
            else:
                corrupt.execute("DROP TABLE consistency_journal")
        for read in (lambda: store.consistency_state(SLOT), lambda: store.decision(SLOT), lambda: store.consistency_receipt(SLOT)):
            fails(api, "corrupt_consistency_journal", read)
    fails(api, "corrupt_consistency_journal", lambda: api.Store(path, read_only=True))


def test_forged_direct_final_cannot_be_committed_without_review_receipt(api, spec, tmp_path):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as store:
        fence = store.acquire_writer("owner")
        setup_slot(api, store, fence)
        final = normalized(api, store)
        with sqlite3.connect(path) as corrupt:
            corrupt.execute("UPDATE slots SET decision=? WHERE slot=?", (api.canonical(final), SLOT))
        fails(api, "corrupt_consistency_journal", lambda: commit_wait_round(api, store, fence, final))
        assert store.head()["round"] == 0


def test_fence_and_round_checks_cover_new_mutations(api, spec, tmp_path):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as old, api.Store(path) as current:
        stale = old.acquire_writer("old")
        setup_slot(api, old, stale)
        attempt = old.reserve_consistency_attempt(SLOT, "candidate", stale)
        draft = normalized(api, old, draft=True)
        old.release_writer(stale)
        fence = current.acquire_writer("current")
        fails(api, "stale_fence", lambda: old.reserve_consistency_attempt(SLOT, "candidate", stale))
        fails(api, "stale_fence", lambda: old.finish_consistency_attempt(attempt, status="succeeded", usage=ZERO, fence=stale, decision=draft))
        current.finish_consistency_attempt(attempt, status="succeeded", usage=ZERO, fence=fence, decision=draft)
        final_id, final, review = final_revision(api, current, fence)
        commit_wait_round(api, current, fence, final)
        fails(api, "stale_round", lambda: current.reserve_consistency_attempt(SLOT, "candidate", fence))
        # A completed exact repeat is read-only, even after its round committed.
        current.finish_consistency_attempt(final_id, status="succeeded", usage={"tokens": 15, "costUsd": "0.15"}, fence=fence, decision=final, assessment=review)


@pytest.mark.parametrize("same_slot", [False, True])
@pytest.mark.parametrize("separate_connections", [False, True])
def test_concurrent_stage_reservation_serializes_budget_and_slot_purpose(api, spec, tmp_path, same_slot, separate_connections):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as first, api.Store(path) as second:
        fence = first.acquire_writer("owner")
        setup_slot(api, first, fence, actors=("alice", "bob"))
        barrier = threading.Barrier(2)

        def reserve(store, slot):
            barrier.wait(timeout=10)
            try:
                return store.reserve_consistency_attempt(slot, "candidate", fence, 60, "0.6")
            except api.Error as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(reserve, first, SLOT), pool.submit(reserve, second if separate_connections else first, SLOT if same_slot else "1:proposal:bob")]
            results = [future.result(timeout=15) for future in futures]
        assert results.count("consistency_stage_exhausted" if same_slot else "run_budget_exhausted") == 1
        budget = first.budget_summary()
        assert len(budget["attempts"]) == 1 and budget["exposure"] == {"tokens": 60, "costUsd": "0.6"}


def test_old_mode_opens_without_journal_migration_or_output_changes(api, spec, tmp_path):
    spec["policy"].pop("decisionReview")
    path = tmp_path / "legacy.sqlite"
    with api.Store(path, spec) as store:
        fence = store.acquire_writer("owner")
        setup_slot(api, store, fence)
        attempt = store.reserve_attempt(SLOT, fence)
        store.finish_attempt(attempt, "succeeded", ZERO, fence)
        final = normalized(api, store)
        store.save_decision(SLOT, final, fence)
        commit_wait_round(api, store, fence, final)
        before = store.read_bundle()
        assert "purpose" not in before["budget"]["attempts"][0]
        assert "errorCode" not in before["budget"]["attempts"][0]
        assert not store._db.execute("SELECT 1 FROM sqlite_master WHERE name='consistency_journal'").fetchone()
        fails(api, "consistency_not_enabled", lambda: store.consistency_state(SLOT))
    with api.Store(path, read_only=True) as reopened:
        assert reopened.read_bundle() == before
        assert reopened.decision(SLOT) == final
        assert not reopened._db.execute("SELECT 1 FROM sqlite_master WHERE name='consistency_journal'").fetchone()


@pytest.mark.parametrize("mode,attempts,code", [("future-mode", 2, "invalid_policy_metadata"), (None, 2, "invalid_policy_metadata"), ("actor-consistency-v1", 1, "invalid_limit")])
def test_invalid_pin_or_budget_rejects_before_database_creation(api, spec, tmp_path, mode, attempts, code):
    spec["policy"]["decisionReview"] = mode
    spec["limits"]["maxAttemptsPerSlot"] = attempts
    path = tmp_path / "invalid.sqlite"
    fails(api, code, lambda: api.Store(path, spec))
    assert not path.exists()
