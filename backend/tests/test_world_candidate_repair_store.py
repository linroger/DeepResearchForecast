"""Known-output repair journal scenarios; parent guard owns all execution.

Only temporary stores are used. There is no provider, original-run access, or
host process dispatch; crash tests simulate connection loss and dead ownership.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import sqlite3
import threading
from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.guarded_runner
SLOT = "1:proposal:alice"
ZERO = {"tokens": 0, "costUsd": "0"}
KNOWN = {"tokens": 10, "costUsd": "0.1"}
ALLOWED_CODES = (
    "policy_invalid_response", "invalid_decision", "invalid_intent", "invalid_input", "invalid_quantity",
    "invalid_actor_update", "invalid_actor_provenance", "unauthorized_actor_update", "unauthorized_priority",
    "unavailable_offer", "closed_offer", "undelivered_offer", "stale_terms",
)


@pytest.fixture
def api():
    from app.services.world_simulation import store as module
    from app.services.world_simulation.contracts import canonical_json, digest, validate_decision, validate_spec
    from app.services.world_simulation.kernel import resolve_round
    from app.services.world_simulation.observations import build_observation
    from app.services.world_simulation.review import CANDIDATE_REPAIR_MODE, MODE_V3

    return SimpleNamespace(Store=module.WorldStore, Error=module.WorldError, module=module,
        canonical=canonical_json, digest=digest, validate_decision=validate_decision, validate_spec=validate_spec,
        observe=build_observation, resolve=resolve_round, mode=MODE_V3, repair_mode=CANDIDATE_REPAIR_MODE)


@pytest.fixture
def spec(api):
    basis = {"kind": "scenario_assumption", "refs": ["candidate-repair-store-test/v1"]}
    return api.validate_spec({"schemaVersion": "simulation-world-spec/v1", "engine": "world-v1",
        "simulationId": "candidate-repair-store", "generationId": "candidate-repair-generation",
        "actors": [{"actorId": "alice", "name": "Alice", "objectives": ["Use admitted mechanisms"], "values": [],
                    "incentives": [], "constraints": [], "beliefs": [], "capabilities": ["wait"],
                    "evidenceGrade": "scenario-assumption", "basis": deepcopy(basis)}],
        "actionCatalog": [{"templateId": "wait", "kind": "wait", "actorIds": ["alice"], "parameters": {}, "basis": basis}],
        "periods": [{"start": f"2030-01-0{day}T00:00:00Z", "end": f"2030-01-0{day + 1}T00:00:00Z"} for day in (1, 2)],
        "initialState": {"accounts": {}, "metrics": {}, "rules": {}, "relations": {}},
        "limits": {"maxAttemptsPerSlot": 2, "maxTokens": 100, "maxCostUsd": "1"},
        "policy": {"decisionReview": api.mode, "candidateRepair": api.repair_mode}})


def prepare(api, store, fence):
    store.freeze_phase(1, "proposal", ["alice"], fence)
    observation = api.observe(store.spec, store.head(), "alice", 1, "proposal")
    store.save_observation(SLOT, observation, fence)
    return observation


def decision(api, store):
    observation = store.observation(SLOT)
    return api.validate_decision(store.spec, {"actorId": "alice", "observationId": observation["observationId"],
        "intents": [], "rationale": "Final complete decision."}, "alice", observation, phase="proposal")


def assessment(mode, verdict="consistent"):
    kinds = ("goal_alignment", "conditional_timing", "quantity_consistency", "explanation_consistency")
    checks = [{"kind": kind, "explanation": "PRIVATE_VALIDATED_ASSESSMENT"} for kind in kinds]
    if mode == "actor-consistency-v3":
        for check in checks:
            check["verdict"] = verdict
        return {"checks": checks}
    if mode == "actor-consistency-v1":
        for check in checks:
            check.update(objectiveIndices=[0] if check["kind"] == "goal_alignment" else [],
                         intentIndices=[], evidencePaths=[["actor", "objectives", 0]])
    return {"status": "clear" if verdict == "consistent" else "unresolved", "checks": checks}


def candidate_failure(store, fence, *, code="invalid_input", marked=True):
    attempt = store.reserve_consistency_attempt(SLOT, "candidate", fence, 30, "0.3")
    store.finish_consistency_attempt(attempt, status="failed", usage=KNOWN, fence=fence,
        error={"code": code, "message": "RAW_FAILED_MODEL_OUTPUT_SECRET_SENTINEL"}, repair_eligible=marked)
    return attempt


def candidate_success(api, store, fence):
    value = decision(api, store)
    attempt = store.reserve_consistency_attempt(SLOT, "candidate", fence, 30, "0.3")
    store.finish_consistency_attempt(attempt, status="succeeded", usage=KNOWN, fence=fence, decision=value)
    return attempt, value


def revision_success(api, store, fence):
    attempt = store.reserve_consistency_attempt(SLOT, "revision", fence, 30, "0.3")
    value = decision(api, store)
    store.finish_consistency_attempt(attempt, status="succeeded", usage=KNOWN, fence=fence, decision=value,
                                     assessment=assessment(store.spec["policy"]["decisionReview"]))
    return attempt, value


def fails(api, code, call):
    with pytest.raises(api.Error) as error:
        call()
    assert error.value.code == code


def test_eligible_failure_derives_safe_input_and_final_receipt_survives_commit_and_reopen(api, spec, tmp_path):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as store:
        fence = store.acquire_writer("owner")
        obs = prepare(api, store, fence)
        assert store.consistency_review_input(SLOT) is None
        first = candidate_failure(store, fence)
        state = store.consistency_state(SLOT)
        assert state["candidate"] is None and state["candidateAttempt"]["status"] == "failed"
        assert store.decision(SLOT) is None and store.consistency_receipt(SLOT) is None
        context = store.consistency_review_input(SLOT)
        assert context == {"schemaVersion": "actor-candidate-error/v1", "actorId": "alice",
                           "observationId": obs["observationId"], "errorCode": "invalid_input"}
        assert first not in api.canonical(context) and "message" not in context and "candidate" not in context
        mutated = store.consistency_review_input(SLOT)
        mutated["errorCode"] = "caller_mutation"
        assert store.consistency_review_input(SLOT) == context
        entry = store._verified_consistency(SLOT)[1][0]
        assert entry["decision"] is None and entry["assessment"] is None
        assert entry["error"]["candidateRepairEligible"] is True
        assert "RAW_FAILED_MODEL_OUTPUT_SECRET_SENTINEL" not in api.canonical(entry)
        assert entry["receipt_hash"] == store._consistency_hash(entry)
        second, final = revision_success(api, store, fence)
        linked = store._verified_consistency(SLOT)[1][1]
        assert linked["candidate_attempt_id"] == first and linked["candidate_hash"] == api.digest(context)
        receipt = store.consistency_receipt(SLOT)
        assert receipt["reviewInputKind"] == "candidate_error"
        assert receipt["reviewInput"] == context and receipt["reviewInputHash"] == api.digest(context)
        assert receipt["candidate"] is None and receipt["candidateHash"] is None
        assert receipt["finalDecisionHash"] == api.digest(final)
        assert [row["status"] for row in receipt["stages"]] == ["failed", "succeeded"]
        assert [row["usage"] for row in receipt["stages"]] == [KNOWN, KNOWN]
        budget = store.budget_summary()
        assert len(budget["attempts"]) == 2 and [row["attemptId"] for row in budget["attempts"]] == [first, second]
        assert budget["attempts"][0]["errorCode"] == "invalid_input"
        assert budget["attempts"][1]["reviewInputKind"] == "candidate_error"
        assert budget["actual"] == {"tokens": 20, "costUsd": "0.2"} and budget["unknown"] == ZERO
        store.freeze_phase(1, "response", [], fence)
        resolved = api.resolve(store.spec, store.head(), [final], 1)
        store.commit_round(0, resolved["snapshot"], resolved["events"], resolved["resolutions"], [final], fence)
        head = store.head()
        assert "PRIVATE_VALIDATED_ASSESSMENT" not in api.canonical(store.read_bundle())
    with api.Store(path, read_only=True) as store:
        assert store.head() == head and store.decision(SLOT) == final
        assert store.consistency_review_input(SLOT) == context and store.consistency_receipt(SLOT) == receipt
        assert store.budget_summary() == budget


@pytest.mark.parametrize("code", ALLOWED_CODES)
def test_only_explicit_allowed_output_failure_marker_creates_context(api, spec, tmp_path, code):
    with api.Store(tmp_path / "world.sqlite", spec) as store:
        fence = store.acquire_writer("owner")
        prepare(api, store, fence)
        candidate_failure(store, fence, code=code)
        assert store.consistency_review_input(SLOT)["errorCode"] == code
        assert store.consistency_state(SLOT)["candidate"] is None


@pytest.mark.parametrize("code", ["cancelled", "decision_identity_mismatch", "missing_usage", "reservation_exceeded",
                                  "stale_fence", "corrupt_consistency_journal", "policy_decision_failed", "transport_error"])
def test_non_output_errors_cannot_be_marked_even_with_known_usage(api, spec, tmp_path, code):
    with api.Store(tmp_path / "world.sqlite", spec) as store:
        fence = store.acquire_writer("owner")
        prepare(api, store, fence)
        attempt = store.reserve_consistency_attempt(SLOT, "candidate", fence, 30, "0.3")
        before = store.budget_summary()
        fails(api, "invalid_candidate_repair", lambda: store.finish_consistency_attempt(attempt,
            status="failed", usage=KNOWN, fence=fence, error={"code": code, "message": "Untrusted origin"}, repair_eligible=True))
        assert store.budget_summary() == before and store.consistency_review_input(SLOT) is None
        store.finish_consistency_attempt(attempt, status="failed", usage=KNOWN, fence=fence, error={"code": code, "message": "Failure"})
        fails(api, "consistency_stage_exhausted", lambda: store.reserve_consistency_attempt(SLOT, "revision", fence))


@pytest.mark.parametrize("defect", ["unknown", "succeeded", "decision", "assessment", "revision", "no_usage", "overuse", "no_error", "nonboolean", "spoofed_marker"])
def test_eligibility_is_strictly_known_failed_candidate_metadata(api, spec, tmp_path, defect):
    with api.Store(tmp_path / "world.sqlite", spec) as store:
        fence = store.acquire_writer("owner")
        prepare(api, store, fence)
        stage = "candidate"
        if defect == "revision":
            candidate_success(api, store, fence)
            stage = "revision"
        attempt = store.reserve_consistency_attempt(SLOT, stage, fence, 30, "0.3")
        kwargs = {"status": "failed", "usage": KNOWN, "fence": fence,
                  "error": {"code": "invalid_input", "message": "failure"}, "repair_eligible": True}
        if defect in {"unknown", "succeeded"}:
            kwargs["status"] = defect
        elif defect == "decision":
            kwargs["decision"] = decision(api, store)
        elif defect == "assessment":
            kwargs["assessment"] = assessment(api.mode)
        elif defect == "no_usage":
            kwargs["usage"] = None
        elif defect == "overuse":
            kwargs["usage"] = {"tokens": 31, "costUsd": "0.1"}
        elif defect == "no_error":
            kwargs["error"] = None
        elif defect == "nonboolean":
            kwargs["repair_eligible"] = 1
        elif defect == "spoofed_marker":
            kwargs["error"]["candidateRepairEligible"] = True
        before = store.budget_summary()
        with pytest.raises(api.Error):
            store.finish_consistency_attempt(attempt, **kwargs)
        assert store.budget_summary() == before
        assert store.decision(SLOT) is None


def test_unmarked_failure_cannot_be_promoted_and_exact_marked_repeats_do_not_write(api, spec, tmp_path):
    for marked in (False, True):
        with api.Store(tmp_path / f"{marked}.sqlite", spec) as store:
            fence = store.acquire_writer("owner")
            prepare(api, store, fence)
            attempt = candidate_failure(store, fence, marked=marked)
            before = store.budget_summary()
            statements = []
            store._db.set_trace_callback(statements.append)
            store.finish_consistency_attempt(attempt, status="failed", usage=KNOWN, fence=fence,
                error={"code": "invalid_input", "message": "Repeat sanitized failure"}, repair_eligible=marked)
            store._db.set_trace_callback(None)
            assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements)
            fails(api, "attempt_conflict", lambda store=store, attempt=attempt, fence=fence, marked=marked: store.finish_consistency_attempt(attempt,
                status="failed", usage=KNOWN, fence=fence, error={"code": "invalid_input", "message": "Changed marker"}, repair_eligible=not marked))
            assert store.budget_summary() == before
            if not marked:
                assert store.consistency_review_input(SLOT) is None
                fails(api, "consistency_stage_exhausted", lambda store=store, fence=fence: store.reserve_consistency_attempt(SLOT, "revision", fence))


@pytest.mark.parametrize("mode", ["actor-consistency-v1", "actor-consistency-v2", "actor-consistency-v3"])
def test_absent_new_pin_keeps_failed_candidate_abort_and_old_success_receipt_shape(api, spec, tmp_path, mode):
    spec["policy"] = {"decisionReview": mode}
    with api.Store(tmp_path / "failed.sqlite", spec) as store:
        fence = store.acquire_writer("owner")
        prepare(api, store, fence)
        attempt = store.reserve_consistency_attempt(SLOT, "candidate", fence, 30, "0.3")
        fails(api, "invalid_candidate_repair", lambda: store.finish_consistency_attempt(attempt,
            status="failed", usage=KNOWN, fence=fence, error={"code": "invalid_input", "message": "old"}, repair_eligible=True))
        store.finish_consistency_attempt(attempt, status="failed", usage=KNOWN, fence=fence,
                                         error={"code": "invalid_input", "message": "old"})
        assert store.consistency_review_input(SLOT) is None
        assert set(store._verified_consistency(SLOT)[1][0]["error"]) == {"code", "message"}
        fails(api, "consistency_stage_exhausted", lambda: store.reserve_consistency_attempt(SLOT, "revision", fence))
    with api.Store(tmp_path / "valid.sqlite", spec) as store:
        fence = store.acquire_writer("owner")
        prepare(api, store, fence)
        _, value = candidate_success(api, store, fence)
        assert store.consistency_review_input(SLOT) == value
        revision_success(api, store, fence)
        receipt = store.consistency_receipt(SLOT)
        assert set(receipt) == {"mode", "slot", "observationId", "observationHash", "candidate", "candidateHash",
                                "finalDecisionId", "finalDecisionHash", "assessment", "receiptHash", "stages"}
        assert receipt["candidate"] == value and receipt["candidateHash"] == api.digest(value)
        assert all("reviewInputKind" not in row for row in store.budget_summary()["attempts"])
        before = store.read_bundle()
    with api.Store(tmp_path / "valid.sqlite", read_only=True) as store:
        assert store.read_bundle() == before and store.consistency_receipt(SLOT) == receipt


def test_successful_candidate_with_new_pin_is_labeled_as_candidate_not_repair(api, spec, tmp_path):
    with api.Store(tmp_path / "world.sqlite", spec) as store:
        fence = store.acquire_writer("owner")
        prepare(api, store, fence)
        _, value = candidate_success(api, store, fence)
        assert store.consistency_review_input(SLOT) == value
        revision_success(api, store, fence)
        receipt = store.consistency_receipt(SLOT)
        assert receipt["reviewInputKind"] == "candidate" and receipt["reviewInput"] == value
        assert receipt["candidate"] == value and receipt["candidateHash"] == receipt["reviewInputHash"] == api.digest(value)
        assert store.budget_summary()["attempts"][1]["reviewInputKind"] == "candidate"


def test_old_pin_absent_row_cannot_gain_repair_from_forged_marker_even_if_rehashed(api, spec, tmp_path):
    spec["policy"].pop("candidateRepair")
    path = tmp_path / "old-generation.sqlite"
    with api.Store(path, spec) as store:
        fence = store.acquire_writer("owner")
        prepare(api, store, fence)
        candidate_failure(store, fence, marked=False)
        assert store.consistency_review_input(SLOT) is None
        entry = deepcopy(store._verified_consistency(SLOT)[1][0])
        entry["error"]["candidateRepairEligible"] = True
        with sqlite3.connect(path) as corrupt:
            corrupt.execute("UPDATE consistency_journal SET error=?,receipt_hash=? WHERE attempt_id=?",
                            (api.canonical(entry["error"]), store._consistency_hash(entry), entry["attempt_id"]))
        fails(api, "corrupt_consistency_journal", lambda: store.consistency_review_input(SLOT))
    fails(api, "corrupt_consistency_journal", lambda: api.Store(path, read_only=True))


@pytest.mark.parametrize("mode,pin", [(None, "known-output-error-v1"), ("actor-consistency-v1", "known-output-error-v1"),
                                     ("actor-consistency-v2", "known-output-error-v1"), ("actor-consistency-v3", "future-repair"),
                                     ("actor-consistency-v3", None)])
def test_wrong_mode_or_new_pin_rejects_before_database_creation(api, spec, tmp_path, mode, pin):
    spec["policy"] = {"candidateRepair": pin}
    if mode is not None:
        spec["policy"]["decisionReview"] = mode
    path = tmp_path / "world.sqlite"
    fails(api, "invalid_policy_metadata", lambda: api.Store(path, spec))
    assert not path.exists()


def test_crash_after_eligible_failure_resumes_only_unused_revision(api, spec, tmp_path, monkeypatch):
    path = tmp_path / "world.sqlite"
    crashed = api.Store(path, spec)
    stale = crashed.acquire_writer("crashed")
    prepare(api, crashed, stale)
    first = candidate_failure(crashed, stale)
    context, budget = crashed.consistency_review_input(SLOT), crashed.budget_summary()
    crashed._db.close()
    crashed._closed = True
    monkeypatch.setattr(api.module, "_alive", lambda pid: False)
    with api.Store(path) as store:
        fence = store.acquire_writer("replacement", takeover=True)
        assert fence > stale
        assert store.budget_summary() == budget and store.consistency_review_input(SLOT) == context
        fails(api, "consistency_stage_exhausted", lambda: store.reserve_consistency_attempt(SLOT, "candidate", fence))
        revision_success(api, store, fence)
        assert store.budget_summary()["attempts"][0]["attemptId"] == first
        assert len(store.budget_summary()["attempts"]) == 2


@pytest.mark.parametrize("candidate_outcome", ["reserved", "unknown"])
def test_unknown_candidate_never_produces_repair_input_across_reopen(api, spec, tmp_path, candidate_outcome):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as store:
        fence = store.acquire_writer("owner")
        prepare(api, store, fence)
        attempt = store.reserve_consistency_attempt(SLOT, "candidate", fence, 30, "0.3")
        if candidate_outcome == "unknown":
            store.finish_consistency_attempt(attempt, status="unknown", usage=KNOWN, fence=fence,
                                             error={"code": "invalid_input", "message": "Not known output origin"})
    with api.Store(path) as store:
        fence = store.acquire_writer("resume")
        assert store.consistency_review_input(SLOT) is None
        assert store.budget_summary()["unknown"] == {"tokens": 30, "costUsd": "0.3"}
        fails(api, "consistency_stage_exhausted", lambda: store.reserve_consistency_attempt(SLOT, "revision", fence))


@pytest.mark.parametrize("outcome", ["reserved", "unknown", "failed", "succeeded"])
def test_finished_second_attempt_never_opens_third_call_and_a_lost_one_is_redispatched(api, spec, tmp_path, outcome):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as store:
        fence = store.acquire_writer("owner")
        prepare(api, store, fence)
        candidate_failure(store, fence)
        if outcome == "succeeded":
            revision_success(api, store, fence)
        else:
            attempt = store.reserve_consistency_attempt(SLOT, "revision", fence, 30, "0.3")
            if outcome != "reserved":
                store.finish_consistency_attempt(attempt, status=outcome, usage=KNOWN, fence=fence,
                                                 error={"code": "invalid_input", "message": "Second failure"})
        before = store.budget_summary()
    lost = outcome in {"reserved", "unknown"}  # Still open when the resume superseded its fence.
    with api.Store(path) as store:
        fence = store.acquire_writer("resume")
        fails(api, "decision_already_saved" if outcome == "succeeded" else "consistency_stage_exhausted",
              lambda: store.reserve_consistency_attempt(SLOT, "candidate", fence))
        after = store.budget_summary()
        assert [a["status"] for a in after["attempts"]] == ["failed", "abandoned" if lost else outcome]
        assert {key: after[key] for key in ("actual", "unknown", "exposure")} == {
            key: before[key] for key in ("actual", "unknown", "exposure")} and len(before["attempts"]) == 2
        assert before["unknown"] == ({"tokens": 30, "costUsd": "0.3"} if lost else ZERO)
        if lost:
            # The lost revision keeps its exposure; the unused repair review is dispatched again.
            assert store.consistency_review_input(SLOT)["errorCode"] == "invalid_input"
            store.reserve_consistency_attempt(SLOT, "revision", fence, 30, "0.3")
        else:
            fails(api, "decision_already_saved" if outcome == "succeeded" else "consistency_stage_exhausted",
                  lambda: store.reserve_consistency_attempt(SLOT, "revision", fence))


@pytest.mark.parametrize("defect", ["marker_false", "marker_string", "marker_missing", "code", "unknown", "unsafe_message", "usage", "context_hash", "attempt_link", "observation"])
def test_marker_and_context_tampering_rejects_on_reads_and_reopen(api, spec, tmp_path, defect):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as store:
        fence = store.acquire_writer("owner")
        prepare(api, store, fence)
        candidate_failure(store, fence)
        store.reserve_consistency_attempt(SLOT, "revision", fence, 30, "0.3")
        entries = store._verified_consistency(SLOT)[1]
        entry = deepcopy(entries[1] if defect in {"context_hash", "attempt_link"} else entries[0])
        with sqlite3.connect(path) as corrupt:
            if defect == "observation":
                obs = store.observation(SLOT)
                obs["observationId"] = "different-observation"
                corrupt.execute("UPDATE slots SET observation=? WHERE slot=?", (api.canonical(obs), SLOT))
            elif defect == "usage":
                corrupt.execute("UPDATE attempts SET usage=? WHERE attempt_id=?", (api.canonical(ZERO), entry["attempt_id"]))
            else:
                if defect == "marker_false":
                    entry["error"]["candidateRepairEligible"] = False
                elif defect == "marker_string":
                    entry["error"]["candidateRepairEligible"] = "true"
                elif defect == "marker_missing":
                    entry["error"].pop("candidateRepairEligible")
                elif defect == "code":
                    entry["error"]["code"] = "stale_fence"
                elif defect == "unknown":
                    entry["status"] = "unknown"
                    corrupt.execute("UPDATE attempts SET status='unknown' WHERE attempt_id=?", (entry["attempt_id"],))
                elif defect == "unsafe_message":
                    entry["error"]["message"] = "RAW_MODEL_OR_PROVIDER_TEXT"
                elif defect == "context_hash":
                    context = store.consistency_review_input(SLOT)
                    context["observationId"] = "another-observation"
                    entry["candidate_hash"] = api.digest(context)
                else:
                    entry["candidate_attempt_id"] = entry["attempt_id"]
                # Even a recomputed content hash cannot waive semantic mode,
                # status, marker, context, canonical-message or linkage checks.
                corrupt.execute("UPDATE consistency_journal SET error=?,candidate_hash=?,candidate_attempt_id=?,receipt_hash=? WHERE attempt_id=?",
                    (api.canonical(entry["error"]) if entry["error"] is not None else None, entry["candidate_hash"],
                     entry["candidate_attempt_id"], store._consistency_hash(entry), entry["attempt_id"]))
        for read in (lambda: store.consistency_review_input(SLOT), lambda: store.consistency_state(SLOT), lambda: store.decision(SLOT), store.budget_summary):
            fails(api, "corrupt_consistency_journal", read)
    fails(api, "corrupt_consistency_journal", lambda: api.Store(path, read_only=True))


def test_known_usage_and_eligibility_marker_are_atomic_and_fenced(api, spec, tmp_path):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as old, api.Store(path) as store:
        stale = old.acquire_writer("old")
        prepare(api, old, stale)
        old.release_writer(stale)
        fence = store.acquire_writer("replacement")
        attempt = store.reserve_consistency_attempt(SLOT, "candidate", fence, 30, "0.3")
        kwargs = {"status": "failed", "usage": KNOWN, "error": {"code": "invalid_input", "message": "output failure"}, "repair_eligible": True}
        fails(api, "stale_fence", lambda: old.finish_consistency_attempt(attempt, fence=stale, **kwargs))
        before = store.budget_summary()
        with sqlite3.connect(path) as fault:
            fault.execute("CREATE TRIGGER fail_marker BEFORE UPDATE OF error ON consistency_journal BEGIN SELECT RAISE(ABORT, 'injected marker failure'); END")
        with pytest.raises(sqlite3.IntegrityError, match="injected marker failure"):
            store.finish_consistency_attempt(attempt, fence=fence, **kwargs)
        assert store.budget_summary() == before and store.consistency_review_input(SLOT) is None
        with sqlite3.connect(path) as fault:
            fault.execute("DROP TRIGGER fail_marker")
        store.finish_consistency_attempt(attempt, fence=fence, **kwargs)
        fails(api, "stale_fence", lambda: old.reserve_consistency_attempt(SLOT, "revision", stale))
        _, final = revision_success(api, store, fence)
        store.freeze_phase(1, "response", [], fence)
        result = api.resolve(store.spec, store.head(), [final], 1)
        store.commit_round(0, result["snapshot"], result["events"], result["resolutions"], [final], fence)
        fails(api, "stale_round", lambda: store.reserve_consistency_attempt(SLOT, "revision", fence))


@pytest.mark.parametrize("verdict", ["unknown", "inconsistent"])
@pytest.mark.parametrize("path_kind", ["old_pin_absent", "valid_candidate", "failed_candidate"])
def test_parent_private_withheld_retention_stays_private_and_its_decision_commits_flagged(api, spec, tmp_path, path_kind, verdict):
    if path_kind == "old_pin_absent":
        spec["policy"].pop("candidateRepair")
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as store:
        fence = store.acquire_writer("owner")
        prepare(api, store, fence)
        if path_kind == "failed_candidate":
            candidate_failure(store, fence)
        else:
            candidate_success(api, store, fence)
        review_input = store.consistency_review_input(SLOT)
        attempt = store.reserve_consistency_attempt(SLOT, "revision", fence, 30, "0.3")
        final, review = decision(api, store), assessment(api.mode, verdict)
        store.finish_consistency_attempt(attempt, status="failed", usage=KNOWN, fence=fence, decision=final, assessment=review,
                                         error={"code": "consistency_unresolved", "message": "Private concern"})
        receipt = store.withheld_consistency_receipt(SLOT)
        assert receipt["state"] == "withheld" and receipt["withheldDecision"] == final and receipt["assessment"] == review
        assert receipt["candidateHash"] == api.digest(review_input)
        flagged = {**final, "consistencyStatus": "unresolved"}
        assert store.decision(SLOT) == flagged and store.consistency_receipt(SLOT) is None
        fails(api, "decision_already_saved", lambda: store.reserve_consistency_attempt(SLOT, "revision", fence))
        store.freeze_phase(1, "response", [], fence)
        result = api.resolve(store.spec, store.head(), [flagged], 1)
        store.commit_round(0, result["snapshot"], result["events"], result["resolutions"], [flagged], fence)
        assert store.rounds()[0]["decisions"] == [flagged]
        assert "PRIVATE_VALIDATED_ASSESSMENT" not in api.canonical(store.read_bundle())
        budget = store.budget_summary()
    with api.Store(path, read_only=True) as store:
        assert store.withheld_consistency_receipt(SLOT) == receipt and store.budget_summary() == budget
        assert store.decision(SLOT) == flagged and store.consistency_receipt(SLOT) is None


def test_concurrent_repair_reservations_share_original_second_ordinal_and_budget(api, spec, tmp_path):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as first, api.Store(path) as second:
        fence = first.acquire_writer("owner")
        prepare(api, first, fence)
        candidate_failure(first, fence)
        fails(api, "run_budget_exhausted", lambda: first.reserve_consistency_attempt(SLOT, "revision", fence, 91, "0.91"))
        assert len(first.budget_summary()["attempts"]) == 1
        barrier = threading.Barrier(2)

        def reserve(store):
            barrier.wait(timeout=10)
            try:
                return store.reserve_consistency_attempt(SLOT, "revision", fence, 90, "0.9")
            except api.Error as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(reserve, first), pool.submit(reserve, second)]
            results = [future.result(timeout=15) for future in futures]
        assert results.count("consistency_stage_exhausted") == 1
        budget = first.budget_summary()
        assert [row["ordinal"] for row in budget["attempts"]] == [1, 2]
        assert budget["exposure"] == {"tokens": 100, "costUsd": "1"}
