"""Attempts left open by a superseded writer fence are abandoned, not burned.

Before the fix, an attempt reserved or left 'unknown' by a writer that died (crash, reboot,
cancel mid-call) counted toward maxAttemptsPerSlot forever; with review pinned the stage
could never be dispatched again (consistency_candidate_unavailable /
consistency_revision_exhausted), so a resume after any crash could stop the world for good
(persistence review M2). Now a new fence marks them 'abandoned': their reservation stays in
budget exposure, they leave the slot's count, and the stage is re-dispatched. Stores live in
tmp_path only, so both suites run this module.
"""
from copy import deepcopy
import sqlite3
from types import SimpleNamespace

import pytest

from app.services.world_simulation import store as store_module
from app.services.world_simulation.contracts import WorldError, validate_decision, validate_spec
from app.services.world_simulation.controller import PolicyResponse, run_round
from app.services.world_simulation.examples import ExamplePolicy, example_spec
from app.services.world_simulation.observations import build_observation
from app.services.world_simulation.review import MODE
from app.services.world_simulation.store import WorldStore
from test_world_consistency_controller import RevisingPolicy, specification as review_specification
from test_world_consistency_store import SLOT, candidate, final_revision, setup_slot

ZERO = {"tokens": 0, "costUsd": "0"}
BASIS = {"kind": "scenario_assumption", "refs": ["resume-attempts-test/v1"]}


def world_spec(*, review):
    actors = [{"actorId": aid, "name": aid, "objectives": ["Use only declared resources"], "values": [],
               "incentives": [], "constraints": [], "beliefs": [], "capabilities": ["wait"],
               "evidenceGrade": "scenario-assumption", "basis": deepcopy(BASIS)} for aid in ("alice", "bob")]
    raw = {"schemaVersion": "simulation-world-spec/v1", "engine": "world-v1",
           "simulationId": "resume-attempts", "generationId": "resume-generation", "actors": actors,
           "periods": [{"start": f"2030-01-0{day}T00:00:00Z", "end": f"2030-01-0{day + 1}T00:00:00Z"} for day in (1, 2)],
           "initialState": {"accounts": {}, "metrics": {}, "rules": {}, "relations": {}},
           "actionCatalog": [{"templateId": "wait", "kind": "wait", "actorIds": ["alice", "bob"], "parameters": {},
                              "basis": deepcopy(BASIS)}],
           "limits": {"maxAttemptsPerSlot": 2, "maxTokens": 1000, "maxCostUsd": "10"}}
    if review:
        raw["policy"] = {"decisionReview": MODE}
    return validate_spec(raw)


@pytest.fixture
def api():
    from app.services.world_simulation.contracts import canonical_json, digest
    from app.services.world_simulation.kernel import resolve_round

    return SimpleNamespace(Store=WorldStore, Error=WorldError, module=store_module, mode=MODE,
                           canonical=canonical_json, digest=digest, validate_decision=validate_decision,
                           validate_spec=validate_spec, resolve=resolve_round, observe=build_observation)


@pytest.fixture
def dead_owner(monkeypatch):
    """The crashed writer's PID is gone (the crash-recovery path the existing tests use)."""
    monkeypatch.setattr(store_module, "_alive", lambda pid: False)


def crash(store):
    """Lose the process without releasing its writer fence."""
    store._db.close()
    store._closed = True


def statuses(store, slot):
    return [a["status"] for a in store.budget_summary()["attempts"] if a["slot"] == slot]


def open_proposal(store, fence, actor="bob"):
    store.freeze_phase(1, "proposal", ["alice", "bob"], fence)
    for aid in ("alice", "bob"):
        store.save_observation(f"1:proposal:{aid}", build_observation(store.spec, store.head(), aid, 1), fence)
    return f"1:proposal:{actor}"


@pytest.mark.parametrize("left", ["reserved", "finished_unknown"])
def test_open_attempt_from_a_superseded_fence_keeps_exposure_but_not_the_slot_allowance(tmp_path, dead_owner, left):
    path = tmp_path / "world.sqlite"
    first = WorldStore(path, world_spec(review=False))
    fence = first.acquire_writer("first")
    slot = open_proposal(first, fence)
    attempt = first.reserve_attempt(slot, fence, 20, "0.2")
    if left == "finished_unknown":  # A transport failure: dispatched, outcome unknown.
        first.finish_attempt(attempt, "unknown", {"tokens": 20, "costUsd": "0.2"}, fence)
    crash(first)
    with WorldStore(path) as resumed:
        fence = resumed.acquire_writer("resumed", takeover=True)
        assert statuses(resumed, slot) == ["abandoned"]
        assert resumed.budget_summary()["unknown"] == {"tokens": 20, "costUsd": "0.2"}
        second = resumed.reserve_attempt(slot, fence, 20, "0.2")
        third = resumed.reserve_attempt(slot, fence, 20, "0.2")
        with pytest.raises(WorldError) as caught:
            resumed.reserve_attempt(slot, fence)
        assert caught.value.code == "attempt_budget_exhausted"
        assert [a["ordinal"] for a in resumed.budget_summary()["attempts"]] == [1, 2, 3]
        assert resumed.budget_summary()["unknown"] == {"tokens": 60, "costUsd": "0.6"}
        with pytest.raises(WorldError) as caught:
            resumed.finish_attempt(attempt, "succeeded", ZERO, fence)
        assert caught.value.code == "attempt_abandoned"
        resumed.finish_attempt(second, "failed", {"tokens": 5, "costUsd": "0.05"}, fence)
        resumed.finish_attempt(third, "succeeded", {"tokens": 5, "costUsd": "0.05"}, fence)
        assert statuses(resumed, slot) == ["abandoned", "failed", "succeeded"]
        assert resumed.budget_summary()["unknown"] == {"tokens": 20, "costUsd": "0.2"}


def test_settled_attempts_still_count_after_a_clean_resume(tmp_path):
    path = tmp_path / "world.sqlite"
    with WorldStore(path, world_spec(review=False)) as store:
        fence = store.acquire_writer("first")
        slot = open_proposal(store, fence)
        failed = store.reserve_attempt(slot, fence, 20, "0.2")
        store.finish_attempt(failed, "failed", {"tokens": 5, "costUsd": "0.05"}, fence)
        store.release_writer(fence)
    with WorldStore(path) as store:
        fence = store.acquire_writer("resumed")
        assert statuses(store, slot) == ["failed"]
        store.reserve_attempt(slot, fence, 20, "0.2")
        with pytest.raises(WorldError):
            store.reserve_attempt(slot, fence)


@pytest.mark.parametrize("stage", ["candidate", "revision"])
def test_review_stage_left_open_is_dispatched_again_after_resume(api, tmp_path, dead_owner, stage):
    path = tmp_path / "world.sqlite"
    first = WorldStore(path, world_spec(review=True))
    fence = first.acquire_writer("first")
    setup_slot(api, first, fence)
    if stage == "revision":
        candidate(api, first, fence)
    first.reserve_consistency_attempt(SLOT, stage, fence, 30, "0.3")
    crash(first)
    with WorldStore(path) as resumed:
        fence = resumed.acquire_writer("resumed", takeover=True)
        state = resumed.consistency_state(SLOT)
        assert state["reviewAttempt"] is None
        assert (state["candidateAttempt"] is None) == (stage == "candidate")
        if stage == "candidate":
            candidate(api, resumed, fence)
        _, final, _ = final_revision(api, resumed, fence)
        assert resumed.decision(SLOT) == final
        attempts = [a for a in resumed.budget_summary()["attempts"] if a["slot"] == SLOT]
        assert [a["status"] for a in attempts] == (["abandoned", "succeeded", "succeeded"] if stage == "candidate"
                                                   else ["succeeded", "abandoned", "succeeded"])
        assert [a["purpose"] for a in attempts] == (["candidate", "candidate", "revision"] if stage == "candidate"
                                                    else ["candidate", "revision", "revision"])
        assert resumed.budget_summary()["unknown"] == {"tokens": 30, "costUsd": "0.3"}
        receipt = resumed.consistency_receipt(SLOT)
        assert [item["stage"] for item in receipt["stages"]] == ["candidate", "revision"]
    with WorldStore(path, read_only=True) as reopened:  # The journal verifies with its abandoned row.
        assert reopened.consistency_receipt(SLOT) == receipt and reopened.decision(SLOT) == final


class Interrupted(BaseException):
    """Process loss during an HTTP call: no handler records the attempt's outcome."""


@pytest.mark.parametrize("review", [False, True])
def test_controller_resumes_a_slot_whose_call_died_with_its_writer(tmp_path, dead_owner, review):
    spec = review_specification() if review else example_spec("investment", periods=1)
    spec["limits"]["maxConcurrentCalls"] = 1
    base = RevisingPolicy if review else ExamplePolicy

    class Dying(base):
        alive = False

        def decide(self, obs, **kwargs):
            if obs["actorId"] == "buyer" and not self.alive:
                raise Interrupted()
            result = super().decide(obs, **kwargs)
            return result if isinstance(result, PolicyResponse) else PolicyResponse(result, ZERO)

    path = tmp_path / "world.sqlite3"
    policy = Dying("investment")
    first = WorldStore(path, spec)
    with pytest.raises(Interrupted):
        run_round(first, policy, first.acquire_writer("first"))
    crash(first)
    policy.alive = True
    with WorldStore(path) as resumed:
        head = run_round(resumed, policy, resumed.acquire_writer("resumed", takeover=True))
        assert head["round"] == 1
        buyer = statuses(resumed, "1:proposal:buyer")
        assert buyer[0] == "abandoned" and buyer[-1] == "succeeded"


def _downgrade_to_v1(path):
    """Rewrite a current database into the exact v1 layout written before the fix."""
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute(
            "CREATE TABLE journal_v1 (attempt_id TEXT PRIMARY KEY REFERENCES attempts(attempt_id), "
            "slot TEXT NOT NULL REFERENCES slots(slot), stage TEXT NOT NULL CHECK(stage IN ('candidate','revision')), "
            "observation_hash TEXT NOT NULL, candidate_attempt_id TEXT REFERENCES attempts(attempt_id), candidate_hash TEXT, "
            "decision TEXT, assessment TEXT, error TEXT, receipt_hash TEXT NOT NULL, UNIQUE(slot,stage))")
        db.execute("INSERT INTO journal_v1 SELECT * FROM consistency_journal")
        db.execute("DROP TABLE consistency_journal")
        db.execute("ALTER TABLE journal_v1 RENAME TO consistency_journal")
        db.execute("PRAGMA user_version=1")
    db.close()


def _schema(path):
    with sqlite3.connect(path) as db:
        result = (db.execute("PRAGMA user_version").fetchone()[0],
                  db.execute("SELECT sql FROM sqlite_master WHERE name='consistency_journal'").fetchone()[0])
    db.close()
    return result


def test_v1_review_store_reads_unchanged_and_migrates_on_first_write(api, tmp_path, dead_owner):
    path = tmp_path / "world.sqlite"
    first = WorldStore(path, world_spec(review=True))
    fence = first.acquire_writer("first")
    setup_slot(api, first, fence)
    first.reserve_consistency_attempt(SLOT, "candidate", fence, 30, "0.3")
    crash(first)
    _downgrade_to_v1(path)
    assert _schema(path)[0] == 1 and "UNIQUE(slot,stage)" in _schema(path)[1]
    with WorldStore(path, read_only=True) as old:
        assert [a["status"] for a in old.budget_summary()["attempts"]] == ["unknown"]
    assert _schema(path)[0] == 1  # A reader never migrates.
    with WorldStore(path) as migrated:
        version, journal = _schema(path)
        assert version == 2 and "UNIQUE(slot,stage)" not in journal
        fence = migrated.acquire_writer("resumed", takeover=True)
        candidate(api, migrated, fence)
        _, final, _ = final_revision(api, migrated, fence)
        assert migrated.decision(SLOT) == final
    with WorldStore(path, read_only=True) as reopened:
        assert [a["status"] for a in reopened.budget_summary()["attempts"]] == ["abandoned", "succeeded", "succeeded"]


def test_unsupported_future_schema_still_fails_closed(tmp_path):
    path = tmp_path / "world.sqlite"
    WorldStore(path, world_spec(review=False)).close()
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=3")
    db.close()
    for read_only in (True, False):
        with pytest.raises(WorldError) as caught:
            WorldStore(path, read_only=read_only)
        assert caught.value.code == "unsupported_store"
