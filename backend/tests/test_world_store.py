"""SQLite world authority scenarios, executed only by the guarded coordinator.

Crash cases simulate lost connection/process ownership without spawning or
killing host processes. SQL fault injection tests the actual commit transaction.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import sqlite3
import threading
from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.guarded_runner


@pytest.fixture
def api():
    from app.services.world_simulation import store as module
    from app.services.world_simulation.contracts import digest, validate_decision, validate_spec
    from app.services.world_simulation.kernel import resolve_round
    from app.services.world_simulation.observations import build_observation

    return SimpleNamespace(Store=module.WorldStore, Error=module.WorldError, module=module,
                           digest=digest, validate_decision=validate_decision,
                           validate_spec=validate_spec, resolve=resolve_round, observe=build_observation)


@pytest.fixture
def spec(api):
    basis = {"kind": "scenario_assumption", "refs": ["world-store-test/v1"]}
    public = {"kind": "public"}
    actors = [{"actorId": aid, "name": aid, "objectives": [], "values": [], "incentives": [],
               "constraints": [], "beliefs": [], "capabilities": ["wait", "pay"] if aid == "alice" else ["wait"],
               "evidenceGrade": "scenario-assumption", "basis": deepcopy(basis)} for aid in ("alice", "bob")]
    accounts = {aid: {"ownerId": aid, "unit": "currency", "balance": "10" if aid == "alice" else "0",
                      "visibility": deepcopy(public), "basis": deepcopy(basis)} for aid in ("alice", "bob")}
    return api.validate_spec({
        "schemaVersion": "simulation-world-spec/v1", "engine": "world-v1",
        "simulationId": "store-test", "generationId": "store-generation", "actors": actors,
        "periods": [{"start": f"2030-01-0{day}T00:00:00Z", "end": f"2030-01-0{day + 1}T00:00:00Z"}
                    for day in (1, 2, 3)],
        "initialState": {"accounts": accounts, "metrics": {}, "rules": {}, "relations": {}},
        "actionCatalog": [
            {"templateId": "wait", "kind": "wait", "actorIds": ["alice", "bob"], "parameters": {}, "basis": deepcopy(basis)},
            {"templateId": "pay", "kind": "transfer", "actorIds": ["alice"],
             "parameters": {"fromAccount": "alice", "toAccount": "bob", "amount": "2"}, "basis": deepcopy(basis)},
        ], "limits": {"maxTokens": 100, "maxCostUsd": "1"},
    })


def observations(api, store, fence, *, actors=("alice", "bob"), phase="proposal"):
    round_index = store.head()["round"] + 1
    store.freeze_phase(round_index, phase, list(actors), fence)
    result = {}
    for actor in actors:
        slot = f"{round_index}:{phase}:{actor}"
        obs = api.observe(store.spec, store.head(), actor, round_index, phase)
        store.save_observation(slot, obs, fence)
        result[slot] = obs
    return result


def decide(api, store, fence, slot, *, intents=None):
    obs = store.observation(slot)
    decision = api.validate_decision(store.spec, {"actorId": obs["actorId"],
        "observationId": obs["observationId"], "intents": intents or []}, obs["actorId"], obs, phase=obs["phase"])
    store.save_decision(slot, decision, fence)
    return decision


def prepared_round(api, store, fence, *, pay=False):
    obs = observations(api, store, fence)
    decisions = [decide(api, store, fence, slot,
                       intents=[{"templateId": "pay"}] if pay and item["actorId"] == "alice" else [])
                 for slot, item in obs.items()]
    store.freeze_phase(store.head()["round"] + 1, "response", [], fence)
    result = api.resolve(store.spec, store.head(), decisions, store.head()["round"] + 1)
    return result, decisions


def commit(store, fence, result, decisions):
    return store.commit_round(store.head()["round"], result["snapshot"], result["events"],
                              result["resolutions"], decisions, fence)


def assert_error(api, code, call):
    with pytest.raises(api.Error) as error:
        call()
    assert error.value.code == code


def test_new_store_requires_spec_and_binds_exact_generation(api, spec, tmp_path):
    path = tmp_path / "world.sqlite"
    assert_error(api, "missing_world", lambda: api.Store(path))
    assert not path.exists()
    with api.Store(path, spec) as store:
        assert store.head()["round"] == 0
        assert len(store.head()["revision"]) == 64
        assert store.history() == [store.head()]
        assert store.rounds() == store.events() == store.resolutions() == []
        assert store._db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert store._db.execute("PRAGMA synchronous").fetchone()[0] == 2
    altered = deepcopy(spec)
    altered["generationId"] = "other-generation"
    assert_error(api, "world_identity_mismatch", lambda: api.Store(path, altered))


def test_committed_round_is_detached_durable_and_exact_result_shape(api, spec, tmp_path):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as store:
        fence = store.acquire_writer("writer")
        result, decisions = prepared_round(api, store, fence, pay=True)
        assert commit(store, fence, result, list(reversed(decisions))) is None
        expected = store.read_bundle()
        assert expected["head"]["accounts"]["alice"]["balance"] == "8"
        assert expected["head"]["accounts"]["bob"]["balance"] == "2"
        assert set(expected) == {"spec", "head", "rounds", "history", "budget"}
        assert set(expected["rounds"][0]) == {"round", "revision", "snapshot", "events", "resolutions", "decisions"}
        assert [item["round"] for item in expected["history"]] == [0, 1]
        assert expected["history"][-1] == expected["head"]
        assert store.events() == result["events"]
        assert store.resolutions() == result["resolutions"]
        dirty = store.read_bundle()
        dirty["head"]["accounts"]["alice"]["balance"] = "999"
        dirty["spec"]["actors"].clear()
        dirty["rounds"][0]["decisions"].clear()
        assert store.read_bundle() == expected
    with api.Store(path, read_only=True) as reopened:
        assert reopened.read_bundle() == expected


def test_read_only_does_not_create_or_configure_journal(api, spec, tmp_path, monkeypatch):
    missing = tmp_path / "missing" / "world.sqlite"
    assert_error(api, "missing_world", lambda: api.Store(missing, spec, read_only=True))
    assert not missing.parent.exists()
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec):
        pass
    statements, connections = [], []
    connect = sqlite3.connect

    def trace_connect(*args, **kwargs):
        connections.append((args, kwargs))
        connection = connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(api.module.sqlite3, "connect", trace_connect)
    with api.Store(path, read_only=True) as store:
        store.read_bundle()
        assert_error(api, "read_only", lambda: store.acquire_writer("reader"))
    assert "mode=ro" in connections[0][0][0]
    assert not any("journal_mode=" in sql.lower() or "synchronous=" in sql.lower()
                   or sql.lstrip().upper().startswith(("CREATE", "INSERT", "UPDATE", "DELETE")) for sql in statements)


def test_live_owner_cannot_be_stolen_even_with_same_identity(api, spec, tmp_path):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as first, api.Store(path) as second:
        fence = first.acquire_writer("owner")
        assert first.acquire_writer("owner") == fence
        for owner in ("other", "owner"):
            assert_error(api, "writer_active", lambda owner=owner: second.acquire_writer(owner, takeover=True))
        first.release_writer(fence)
        newer = second.acquire_writer("next")
        assert newer > fence
        assert_error(api, "stale_fence", lambda: first.release_writer(fence))


def test_uncertain_process_liveness_fails_closed(api, monkeypatch):
    def denied(pid, sig):
        raise PermissionError("not permitted")

    monkeypatch.setattr(api.module.os, "kill", denied)
    assert api.module._alive(12345) is True


def test_takeover_fences_every_tentative_and_commit_mutation(api, spec, tmp_path, monkeypatch):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as first, api.Store(path) as second:
        stale = first.acquire_writer("old")
        observations(api, first, stale)
        attempt = first.reserve_attempt("1:proposal:alice", stale, 10, "0.1")
        obs = first.observation("1:proposal:alice")
        decision = api.validate_decision(first.spec, {"actorId": "alice", "observationId": obs["observationId"], "intents": []},
                                         "alice", obs, phase="proposal")
        monkeypatch.setattr(api.module, "_alive", lambda pid: False)
        assert_error(api, "writer_takeover_required", lambda: second.acquire_writer("new"))
        fence = second.acquire_writer("new", takeover=True)
        assert fence > stale
        snapshot = first.head()
        snapshot.update(round=1, simulatedAt=spec["periods"][0]["end"])
        operations = [
            lambda: first.freeze_phase(1, "proposal", ["alice", "bob"], stale),
            lambda: first.save_observation("1:proposal:alice", obs, stale),
            lambda: first.save_decision("1:proposal:alice", decision, stale),
            lambda: first.reserve_attempt("1:proposal:alice", stale),
            lambda: first.finish_attempt(attempt, "succeeded", {"tokens": 2, "costUsd": "0.01"}, stale),
            lambda: first.commit_round(0, snapshot, [], [], [], stale),
            lambda: first.release_writer(stale),
        ]
        for operation in operations:
            assert_error(api, "stale_fence", operation)
        assert second.budget_summary()["unknown"] == {"tokens": 10, "costUsd": "0.1"}
        first.close()  # A stale context cannot release its successor's fence.
        second.save_decision("1:proposal:alice", decision, fence)


def test_crash_resume_preserves_success_receipts_unknown_exposure_and_restores_the_lost_attempt(api, spec, tmp_path, monkeypatch):
    path = tmp_path / "world.sqlite"
    first = api.Store(path, spec)
    fence = first.acquire_writer("old")
    observations(api, first, fence)
    alice = decide(api, first, fence, "1:proposal:alice")
    attempt = first.reserve_attempt("1:proposal:bob", fence, 20, "0.2")
    first._db.close()  # Simulated abrupt loss: no release_writer/close cleanup.
    first._closed = True
    monkeypatch.setattr(api.module, "_alive", lambda pid: False)
    with api.Store(path) as recovered:
        fence = recovered.acquire_writer("recovered", takeover=True)
        assert recovered.decision("1:proposal:alice") == alice
        lost = recovered.budget_summary()["attempts"][0]
        assert lost["attemptId"] == attempt and lost["status"] == "abandoned"
        assert recovered.budget_summary()["unknown"] == {"tokens": 20, "costUsd": "0.2"}
        # The lost call keeps its exposure but not the slot's allowance: two fresh attempts.
        recovered.reserve_attempt("1:proposal:bob", fence, 20, "0.2")
        recovered.reserve_attempt("1:proposal:bob", fence, 20, "0.2")
        assert_error(api, "attempt_budget_exhausted", lambda: recovered.reserve_attempt("1:proposal:bob", fence))
        assert recovered.head()["round"] == 0
        assert recovered.rounds() == recovered.events() == recovered.resolutions() == []


def test_frozen_phases_and_observation_decision_identities(api, spec, tmp_path):
    with api.Store(tmp_path / "world.sqlite", spec) as store:
        fence = store.acquire_writer("owner")
        assert_error(api, "missing_decisions", lambda: store.freeze_phase(1, "response", [], fence))
        observations(api, store, fence)
        store.freeze_phase(1, "proposal", ["bob", "alice"], fence)
        assert_error(api, "phase_conflict", lambda: store.freeze_phase(1, "proposal", ["alice"], fence))
        assert_error(api, "invalid_phase", lambda: store.freeze_phase(1, "proposal", ["alice", "alice"], fence))
        obs = store.observation("1:proposal:alice")
        assert store.save_observation("1:proposal:alice", obs, fence) is None
        wrong = deepcopy(obs)
        wrong["actorId"] = "bob"
        assert_error(api, "observation_identity_mismatch", lambda: store.save_observation("1:proposal:alice", wrong, fence))
        changed = deepcopy(obs)
        changed["privateState"]["plans"] = ["different"]
        changed["observationId"] = api.digest({key: value for key, value in changed.items() if key != "observationId"})
        assert_error(api, "observation_conflict", lambda: store.save_observation("1:proposal:alice", changed, fence))
        decision = decide(api, store, fence, "1:proposal:alice", intents=[{"templateId": "wait"}])
        assert store.save_decision("1:proposal:alice", decision, fence) is None
        for key, value in (("round", 2), ("phase", "response"), ("actorId", "bob"),
                           ("observationId", "other"), ("decisionId", "forged")):
            bad = deepcopy(decision)
            bad[key] = value
            assert_error(api, "decision_identity_mismatch", lambda bad=bad: store.save_decision("1:proposal:alice", bad, fence))
        bad = deepcopy(decision)
        bad["intents"][0]["intentId"] = "forged-intent"
        assert_error(api, "decision_identity_mismatch", lambda: store.save_decision("1:proposal:alice", bad, fence))
        bad = deepcopy(decision)
        bad["rationale"] = "changed"
        assert_error(api, "decision_conflict", lambda: store.save_decision("1:proposal:alice", bad, fence))


@pytest.mark.parametrize("separate_connections", [False, True])
@pytest.mark.parametrize("resource", ["tokens", "cost"])
def test_concurrent_reservations_cannot_oversubscribe_run(api, spec, tmp_path, separate_connections, resource):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as first, api.Store(path) as second:
        fence = first.acquire_writer("owner")
        observations(api, first, fence)
        barrier = threading.Barrier(2)

        def reserve(actor, store):
            barrier.wait(timeout=10)
            try:
                return store.reserve_attempt(f"1:proposal:{actor}", fence,
                    reserved_tokens=60 if resource == "tokens" else 1,
                    reserved_cost="0.6" if resource == "cost" else "0")
            except api.Error as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(reserve, "alice", first),
                       pool.submit(reserve, "bob", second if separate_connections else first)]
            outcomes = [future.result(timeout=15) for future in futures]
        assert outcomes.count("run_budget_exhausted") == 1
        budget = first.budget_summary()
        assert len(budget["attempts"]) == 1
        assert budget["exposure"] == {"tokens": 60 if resource == "tokens" else 1,
                                      "costUsd": "0.6" if resource == "cost" else "0"}


def test_actual_usage_releases_only_known_exposure_and_unknown_is_not_billing(api, spec, tmp_path):
    with api.Store(tmp_path / "world.sqlite", spec) as store:
        fence = store.acquire_writer("owner")
        observations(api, store, fence)
        first = store.reserve_attempt("1:proposal:alice", fence, 80, "0.8")
        assert_error(api, "run_budget_exhausted", lambda: store.reserve_attempt("1:proposal:bob", fence, 30, "0.3"))
        assert_error(api, "reservation_exceeded", lambda: store.finish_attempt(first, "succeeded", {"tokens": 81, "costUsd": "0.1"}, fence))
        assert_error(api, "reservation_exceeded", lambda: store.finish_attempt(first, "failed", {"tokens": 1, "costUsd": "0.9"}, fence))
        store.finish_attempt(first, "failed", {"tokens": 20, "costUsd": "0.2"}, fence)
        store.finish_attempt(first, "failed", {"tokens": 20, "costUsd": "0.2"}, fence)
        assert_error(api, "attempt_conflict", lambda: store.finish_attempt(first, "succeeded", {"tokens": 20, "costUsd": "0.2"}, fence))
        second = store.reserve_attempt("1:proposal:bob", fence, 80, "0.8")
        store.finish_attempt(second, "unknown", {"tokens": 0, "costUsd": "0"}, fence)
        budget = store.budget_summary()
        assert budget["reserved"] == {"tokens": 160, "costUsd": "1.6"}
        assert budget["actual"] == {"tokens": 20, "costUsd": "0.2"}
        assert budget["unknown"] == {"tokens": 80, "costUsd": "0.8"}
        assert budget["exposure"] == {"tokens": 100, "costUsd": "1"}
        assert_error(api, "run_budget_exhausted", lambda: store.reserve_attempt("1:proposal:alice", fence, 1, "0"))


def test_cumulative_reserved_audit_total_can_exceed_scalar_input_limit(api, spec, tmp_path):
    ceiling = str(10 ** 30)
    spec["limits"]["maxCostUsd"] = ceiling
    with api.Store(tmp_path / "world.sqlite", spec) as store:
        fence = store.acquire_writer("owner")
        observations(api, store, fence)
        first = store.reserve_attempt("1:proposal:alice", fence, 1, ceiling)
        store.finish_attempt(first, "failed", {"tokens": 0, "costUsd": "0"}, fence)
        store.reserve_attempt("1:proposal:bob", fence, 1, ceiling)
        budget = store.budget_summary()
        assert budget["reserved"] == {"tokens": 2, "costUsd": str(2 * 10 ** 30)}
        assert budget["actual"] == {"tokens": 0, "costUsd": "0"}
        assert budget["exposure"] == {"tokens": 1, "costUsd": ceiling}
        assert_error(api, "run_budget_exhausted", lambda: store.reserve_attempt("1:proposal:alice", fence, 1, "0.01"))


def test_commit_rejects_missing_phases_missing_receipts_and_substitutions(api, spec, tmp_path):
    with api.Store(tmp_path / "world.sqlite", spec) as store:
        fence = store.acquire_writer("owner")
        empty_result = api.resolve(spec, store.head(), [], 1)
        assert_error(api, "phase_not_frozen", lambda: commit(store, fence, empty_result, []))
        observations(api, store, fence)
        decide(api, store, fence, "1:proposal:alice")
        assert_error(api, "missing_decisions", lambda: store.freeze_phase(1, "response", [], fence))
        decide(api, store, fence, "1:proposal:bob")
        store.freeze_phase(1, "response", ["bob"], fence)
        assert_error(api, "missing_decisions", lambda: commit(store, fence, empty_result, []))
        obs = api.observe(spec, store.head(), "bob", 1, "response")
        store.save_observation("1:response:bob", obs, fence)
        decide(api, store, fence, "1:response:bob")
        decisions = [store.decision(slot) for slot in ("1:proposal:alice", "1:proposal:bob", "1:response:bob")]
        result = api.resolve(spec, store.head(), decisions, 1)
        for receipts in (decisions[:-1], decisions + [decisions[0]]):
            assert_error(api, "decision_set_mismatch", lambda receipts=receipts: commit(store, fence, result, receipts))
        replaced = deepcopy(decisions)
        replaced[0]["rationale"] = "substitution"
        assert_error(api, "decision_set_mismatch", lambda: commit(store, fence, result, replaced))
        assert store.head()["round"] == 0
        commit(store, fence, result, decisions)
        assert store.head()["round"] == 1


@pytest.mark.parametrize("mutation", ["balance", "account", "owner", "unit", "actor", "pending", "sampling", "time", "spec", "round"])
def test_rejects_corrupt_snapshot_without_partial_commit(api, spec, tmp_path, mutation):
    with api.Store(tmp_path / "world.sqlite", spec) as store:
        fence = store.acquire_writer("owner")
        result, decisions = prepared_round(api, store, fence, pay=True)
        before = store.read_bundle()
        broken = deepcopy(result)
        snapshot = broken["snapshot"]
        if mutation == "balance":
            snapshot["accounts"]["bob"]["balance"] = "3"
        elif mutation == "account":
            snapshot["accounts"]["new"] = deepcopy(snapshot["accounts"]["bob"])
        elif mutation in {"owner", "unit"}:
            snapshot["accounts"]["bob"]["ownerId" if mutation == "owner" else "unit"] = "external" if mutation == "owner" else "goods"
        elif mutation == "actor":
            snapshot["actorStates"].pop("bob")
        elif mutation == "pending":
            snapshot.pop("interactions")
        elif mutation == "sampling":
            snapshot["sampling"].pop("draws")
        elif mutation == "time":
            snapshot["simulatedAt"] = spec["periods"][1]["end"]
        elif mutation == "spec":
            snapshot["specHash"] = "wrong"
        else:
            snapshot["round"] = 2
        with pytest.raises(api.Error):
            commit(store, fence, broken, decisions)
        assert store.read_bundle() == before


def test_duplicate_events_and_missing_resolutions_fail_atomically(api, spec, tmp_path):
    with api.Store(tmp_path / "world.sqlite", spec) as store:
        fence = store.acquire_writer("owner")
        result, decisions = prepared_round(api, store, fence, pay=True)
        before = store.read_bundle()
        broken = deepcopy(result)
        broken["events"].append(deepcopy(broken["events"][0]))
        assert_error(api, "duplicate_event", lambda: commit(store, fence, broken, decisions))
        broken = deepcopy(result)
        broken["resolutions"] = []
        assert_error(api, "resolution_set_mismatch", lambda: commit(store, fence, broken, decisions))
        assert store.read_bundle() == before
        commit(store, fence, result, decisions)
        second, receipts = prepared_round(api, store, fence, pay=True)
        second["events"][0]["eventId"] = result["events"][0]["eventId"]
        assert_error(api, "duplicate_event", lambda: commit(store, fence, second, receipts))


def test_sql_fault_rolls_back_commit_and_event_index_then_retry_succeeds(api, spec, tmp_path):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as store:
        fence = store.acquire_writer("owner")
        result, decisions = prepared_round(api, store, fence, pay=True)
        before = store.read_bundle()
        with sqlite3.connect(path) as fault:
            fault.execute("CREATE TRIGGER injected_failure BEFORE INSERT ON event_ids BEGIN SELECT RAISE(ABORT, 'injected crash boundary'); END")
        with pytest.raises(sqlite3.IntegrityError, match="injected crash boundary"):
            commit(store, fence, result, decisions)
        assert store.read_bundle() == before
        with sqlite3.connect(path) as fault:
            assert fault.execute("SELECT COUNT(*) FROM commits").fetchone()[0] == 1
            assert fault.execute("SELECT COUNT(*) FROM event_ids").fetchone()[0] == 0
            fault.execute("DROP TRIGGER injected_failure")
        commit(store, fence, result, decisions)
        assert store.head()["round"] == 1


def test_stale_round_and_late_receipts_never_reapply(api, spec, tmp_path):
    with api.Store(tmp_path / "world.sqlite", spec) as store:
        fence = store.acquire_writer("owner")
        result, decisions = prepared_round(api, store, fence, pay=True)
        commit(store, fence, result, decisions)
        before = store.read_bundle()
        assert_error(api, "stale_round", lambda: store.commit_round(0, result["snapshot"], result["events"], result["resolutions"], decisions, fence))
        assert_error(api, "stale_round", lambda: store.save_decision("1:proposal:alice", decisions[0], fence))
        assert_error(api, "stale_round", lambda: store.freeze_phase(1, "proposal", ["alice", "bob"], fence))
        assert store.read_bundle() == before


def test_semantic_revision_ignores_fences_attempt_ids_and_stale_revision_field(api, spec, tmp_path):
    with api.Store(tmp_path / "one.sqlite", spec) as one, api.Store(tmp_path / "two.sqlite", spec) as two:
        first_fence = one.acquire_writer("one")
        old = two.acquire_writer("old")
        two.release_writer(old)
        second_fence = two.acquire_writer("two")
        assert first_fence != second_fence
        result, decisions = prepared_round(api, one, first_fence, pay=True)
        observations(api, two, second_fence)
        attempt = two.reserve_attempt("1:proposal:alice", second_fence)
        two.finish_attempt(attempt, "failed", {"tokens": 0, "costUsd": "0"}, second_fence)
        other_result, other_decisions = prepared_round(api, two, second_fence, pay=True)
        other_result["snapshot"]["revision"] = "derived-stale-head-field"
        commit(one, first_fence, result, decisions)
        commit(two, second_fence, other_result, list(reversed(other_decisions)))
        assert one.head() == two.head()
        assert one.rounds() == two.rounds()
        assert one.budget_summary() != two.budget_summary()


def test_completed_world_cannot_acquire_new_writer(api, spec, tmp_path):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as store:
        fence = store.acquire_writer("owner")
        for _ in spec["periods"]:
            result, decisions = prepared_round(api, store, fence)
            commit(store, fence, result, decisions)
    with api.Store(path) as store:
        assert_error(api, "horizon_complete", lambda: store.acquire_writer("again"))
        assert len(store.history()) == 4


def test_initial_scheduled_effects_settle_before_observation_and_survive_reopen(api, spec, tmp_path):
    spec["scheduledEvents"] = [{"eventId": "initial-transfer", "at": spec["asOf"], "kind": "transfer",
        "parameters": {"fromAccount": "alice", "toAccount": "bob", "amount": "3"},
        "visibility": {"kind": "public"}, "basis": {"kind": "scenario_assumption", "refs": ["opening-effect"]}}]
    spec = api.validate_spec(spec)
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as store:
        fence = store.acquire_writer("owner")
        assert store.head()["accounts"]["alice"]["balance"] == "7"
        obs = observations(api, store, fence)["1:proposal:alice"]
        assert obs["world"]["accounts"]["bob"]["balance"] == "3"
        assert store.events() == store.head()["initialEvents"]
        assert len(store.events()) == 1
        before = store.head()
    with api.Store(path) as store:
        assert store.head() == before


def test_read_bundle_stays_on_one_revision_during_concurrent_commit(api, spec, tmp_path, monkeypatch):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as writer, api.Store(path, read_only=True) as reader:
        fence = writer.acquire_writer("owner")
        result, decisions = prepared_round(api, writer, fence, pay=True)
        captured = threading.Event()
        committed = threading.Event()
        original = reader.head

        def capture_head():
            head = original()
            captured.set()
            assert committed.wait(timeout=10)
            return head

        monkeypatch.setattr(reader, "head", capture_head)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(reader.read_bundle)
            assert captured.wait(timeout=10)
            try:
                commit(writer, fence, result, decisions)
            finally:
                committed.set()
            bundle = future.result(timeout=10)
        assert writer.head()["round"] == 1
        assert bundle["head"]["round"] == 0
        assert len(bundle["history"]) == 1
        assert bundle["rounds"] == []


def test_open_detects_tampered_semantic_head(api, spec, tmp_path):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec):
        pass
    with sqlite3.connect(path) as corrupted:
        corrupted.execute("UPDATE commits SET revision='tampered'")
    assert_error(api, "corrupt_store", lambda: api.Store(path, read_only=True))


@pytest.mark.parametrize("read_only", [False, True])
def test_open_verifies_historical_content_not_just_stored_revision_strings(api, spec, tmp_path, read_only):
    path = tmp_path / "world.sqlite"
    with api.Store(path, spec) as store:
        fence = store.acquire_writer("owner")
        for _ in range(2):
            result, decisions = prepared_round(api, store, fence, pay=True)
            commit(store, fence, result, decisions)
    with sqlite3.connect(path) as corrupted:
        corrupted.execute("UPDATE commits SET events='[]' WHERE round=1")
    assert_error(api, "corrupt_store", lambda: api.Store(path, read_only=read_only))


@pytest.mark.parametrize("mutation", ["commitment", "interaction", "settlement", "actor_state", "scheduled", "malformed_record"])
def test_replay_closure_rejects_lost_pending_work_and_unearned_state_changes(api, tmp_path, mutation):
    from app.services.world_simulation.controller import run_round
    from app.services.world_simulation.examples import ExamplePolicy, example_spec

    spec = example_spec(periods=4)
    for template in spec["actionCatalog"]:
        if template["kind"] in {"investment", "agreement"}:
            template["parameters"]["durationDays"] = "3"
    spec = api.validate_spec(spec)
    with api.Store(tmp_path / "world.sqlite", spec) as store:
        fence = store.acquire_writer("owner")
        run_round(store, ExamplePolicy("investment"), fence)
        assert any(item["status"] == "pending" for item in store.head()["commitments"].values())
        obs = observations(api, store, fence, actors=tuple(actor["actorId"] for actor in spec["actors"]))
        decisions = [decide(api, store, fence, slot) for slot in obs]
        store.freeze_phase(2, "response", [], fence)
        result = api.resolve(spec, store.head(), decisions, 2)
        before = store.read_bundle()
        snapshot = result["snapshot"]
        if mutation == "commitment":
            snapshot["commitments"].clear()
        elif mutation == "interaction":
            snapshot["interactions"].clear()
        elif mutation == "settlement":
            for item in snapshot["commitments"].values():
                item["status"] = "settled"
        elif mutation == "actor_state":
            snapshot["actorStates"]["producer"]["plans"] = [{"plan": "unobserved"}]
        elif mutation == "scheduled":
            snapshot["scheduledEvents"].append({"eventId": "unauthorized-future-effect"})
        else:
            snapshot["interactions"]["bad-offer"] = None
        expected_code = "invalid_snapshot" if mutation == "malformed_record" else "transition_mismatch"
        assert_error(api, expected_code, lambda: commit(store, fence, result, decisions))
        assert store.read_bundle() == before


@pytest.mark.parametrize("mutation", ["basis", "intent", "applied_history"])
def test_event_provenance_and_causal_closure_reject_substitutions(api, spec, tmp_path, mutation):
    with api.Store(tmp_path / "world.sqlite", spec) as store:
        fence = store.acquire_writer("owner")
        result, decisions = prepared_round(api, store, fence, pay=True)
        before = store.read_bundle()
        if mutation == "basis":
            result["events"][0]["basis"] = {"refs": "not-a-list"}
        elif mutation == "intent":
            result["events"][0]["sourceIntentId"] = "nonexistent-intent"
        else:
            result["snapshot"]["appliedEvents"] = []
        expected_code = "invalid_event" if mutation == "basis" else "transition_mismatch"
        assert_error(api, expected_code, lambda: commit(store, fence, result, decisions))
        assert store.read_bundle() == before
