"""Durable world authority; external calls and graph writes never occur here.

Every mutation is serialized by BEGIN IMMEDIATE and checks its fence inside the
transaction. The connection lock also permits one store to be shared by policy
worker threads. JSON is canonical; SQLite/WAL bytes are not semantic identity.
"""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal, localcontext
import json
import os
from pathlib import Path
import sqlite3
import threading
from uuid import uuid4

from .contracts import (
    WorldError as WorldError,
    actors_by_id, canonical_json, decimal, digest, identifier,
    parse_time, period_for, quantity, require, validate_decision,
    validate_snapshot, validate_spec, visibility,
)

_VERSION = 1
_APPLICATION_ID = 0x57524C44
_PHASES = ("proposal", "response")
_SCHEMA = (
    "CREATE TABLE model (singleton INTEGER PRIMARY KEY CHECK(singleton=1), spec TEXT NOT NULL, spec_hash TEXT NOT NULL)",
    "CREATE TABLE writer (singleton INTEGER PRIMARY KEY CHECK(singleton=1), fence INTEGER NOT NULL, owner TEXT, pid INTEGER)",
    "CREATE TABLE commits (round INTEGER PRIMARY KEY, revision TEXT UNIQUE NOT NULL, previous_revision TEXT, snapshot TEXT NOT NULL, events TEXT NOT NULL, resolutions TEXT NOT NULL, decisions TEXT NOT NULL)",
    "CREATE TABLE head (singleton INTEGER PRIMARY KEY CHECK(singleton=1), round INTEGER NOT NULL REFERENCES commits(round))",
    "CREATE TABLE phases (round INTEGER NOT NULL, phase TEXT NOT NULL, actors TEXT NOT NULL, PRIMARY KEY(round,phase))",
    "CREATE TABLE slots (slot TEXT PRIMARY KEY, round INTEGER NOT NULL, phase TEXT NOT NULL, actor TEXT NOT NULL, observation TEXT, decision TEXT, UNIQUE(round,phase,actor), FOREIGN KEY(round,phase) REFERENCES phases(round,phase))",
    "CREATE TABLE attempts (attempt_id TEXT PRIMARY KEY, slot TEXT NOT NULL REFERENCES slots(slot), ordinal INTEGER NOT NULL, reserved_tokens INTEGER NOT NULL, reserved_cost TEXT NOT NULL, status TEXT NOT NULL, usage TEXT, UNIQUE(slot,ordinal))",
    "CREATE TABLE event_ids (event_id TEXT PRIMARY KEY, round INTEGER NOT NULL REFERENCES commits(round))",
)


def _json(value):
    """Detach and reject noncanonical JSON values before writing."""
    return json.loads(canonical_json(value))


def _alive(pid: int) -> bool:
    """Fail closed on permission errors and PID reuse: any live PID is protected.

    No timeout makes a living owner stealable. An explicit release or a proven
    absent process is necessary. This conservative policy avoids subprocesses
    and platform-specific process-start-time guesses.
    """
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _revision(snapshot, previous_revision, events, resolutions, decisions):
    return digest({"snapshot": snapshot, "previousRevision": previous_revision,
                   "events": events, "resolutions": resolutions, "decisions": decisions})


class WorldStore:
    def __init__(self, path, spec=None, read_only=False):
        self.path = Path(path).expanduser().absolute()
        self.read_only = bool(read_only)
        self._lock = threading.RLock()
        self._closed = False
        self._owned_fence = None
        supplied = validate_spec(spec) if spec is not None else None
        require(self.path.is_file() or (not self.read_only and supplied is not None),
                "missing_world", "Opening a new world requires a specification")
        if not self.read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        target = self.path.as_uri() + "?mode=ro" if self.read_only else str(self.path)
        self._db = sqlite3.connect(target, uri=self.read_only,
                                   timeout=30, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        try:
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA busy_timeout=30000")
            if self.read_only:
                self._db.execute("PRAGMA query_only=ON")
                self._db.execute("BEGIN")
                try:
                    self._load(supplied)
                    self._db.execute("COMMIT")
                except BaseException:
                    self._db.execute("ROLLBACK")
                    raise
            else:
                require(self._db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal",
                        "unsupported_storage", "World storage requires SQLite WAL")
                self._db.execute("PRAGMA synchronous=FULL")
                with self._transaction():
                    tables = self._db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                    if not tables:
                        require(supplied is not None, "missing_world", "New world requires a specification")
                        self._initialize(supplied)
                    self._load(supplied)
        except BaseException:
            self._db.close()
            self._closed = True
            raise

    def __enter__(self):
        self._check_open()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def _check_open(self):
        require(not self._closed, "closed_store", "World store is closed")

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._check_open()
            require(not self.read_only, "read_only", "World store is read-only")
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def _initialize(self, spec):
        # The pure kernel settles effects at asOf before any observation exists.
        from .kernel import initialize_world

        snapshot = _json(initialize_world(spec))
        snapshot.pop("revision", None)
        self._spec = spec
        self._validate_closure(snapshot)
        require(snapshot["round"] == 0, "invalid_round", "Initial world must be round zero")
        for statement in _SCHEMA:
            self._db.execute(statement)
        self._db.execute(f"PRAGMA application_id={_APPLICATION_ID}")
        self._db.execute(f"PRAGMA user_version={_VERSION}")
        self._db.execute("INSERT INTO model VALUES (1,?,?)", (canonical_json(spec), digest(spec)))
        self._db.execute("INSERT INTO writer VALUES (1,0,NULL,NULL)")
        events = snapshot.get("initialEvents", [])
        revision = _revision(snapshot, None, events, [], [])
        self._db.execute("INSERT INTO commits VALUES (0,?,NULL,?,?,'[]','[]')",
                         (revision, canonical_json(snapshot), canonical_json(events)))
        self._db.executemany("INSERT INTO event_ids VALUES (?,0)", [(event["eventId"],) for event in events])
        self._db.execute("INSERT INTO head VALUES (1,0)")

    def _load(self, supplied):
        require(self._db.execute("PRAGMA application_id").fetchone()[0] == _APPLICATION_ID
                and self._db.execute("PRAGMA user_version").fetchone()[0] == _VERSION,
                "unsupported_store", "Unsupported world database schema")
        require(self._db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
                and not self._db.execute("PRAGMA foreign_key_check").fetchall(),
                "corrupt_store", "World database integrity check failed")
        row = self._db.execute("SELECT * FROM model WHERE singleton=1").fetchone()
        require(row is not None, "corrupt_store", "World model is missing")
        self._spec = validate_spec(json.loads(row["spec"]))
        require(digest(self._spec) == row["spec_hash"], "corrupt_store", "World model hash changed")
        require(supplied is None or digest(supplied) == row["spec_hash"],
                "world_identity_mismatch", "Provided specification differs from stored world")
        head = self._head_row()
        previous_revision, previous_snapshot, indexed = None, None, {}
        rows = self._db.execute("SELECT * FROM commits ORDER BY round").fetchall()
        require(len(rows) == head["round"] + 1, "corrupt_store", "World commit sequence is incomplete")
        for index, row in enumerate(rows):
            snapshot = json.loads(row["snapshot"])
            events = json.loads(row["events"])
            require(row["round"] == index and snapshot.get("round") == index
                    and row["previous_revision"] == previous_revision, "corrupt_store", "World commit ancestry is inconsistent")
            require(row["revision"] == _revision(snapshot, previous_revision, events,
                    json.loads(row["resolutions"]), json.loads(row["decisions"])),
                    "corrupt_store", "World commit semantic revision is inconsistent")
            self._validate_closure(snapshot, previous_snapshot)
            for event in events:
                require(event["eventId"] not in indexed, "corrupt_store", "Duplicate committed event identity")
                indexed[event["eventId"]] = index
            previous_revision, previous_snapshot = row["revision"], snapshot
        require(indexed == {row[0]: row[1] for row in self._db.execute("SELECT event_id,round FROM event_ids")},
                "corrupt_store", "Committed event index is inconsistent")
        require(self._db.execute("SELECT 1 FROM writer WHERE singleton=1").fetchone() is not None,
                "corrupt_store", "Writer fence record is missing")

    def close(self):
        with self._lock:
            if self._closed:
                return
            try:
                if self._owned_fence is not None:
                    with self._transaction():
                        self._db.execute("UPDATE writer SET owner=NULL,pid=NULL WHERE singleton=1 AND fence=?",
                                         (self._owned_fence,))
            finally:
                self._db.close()
                self._closed = True

    @property
    def spec(self):
        with self._lock:
            self._check_open()
            return _json(self._spec)

    def _head_row(self):
        row = self._db.execute("SELECT c.* FROM commits c JOIN head h ON c.round=h.round WHERE h.singleton=1").fetchone()
        require(row is not None, "corrupt_store", "World has no committed head")
        return row

    @staticmethod
    def _snapshot(row):
        return {**json.loads(row["snapshot"]), "revision": row["revision"]}

    def head(self):
        with self._lock:
            self._check_open()
            return self._snapshot(self._head_row())

    def history(self):
        with self._lock:
            self._check_open()
            return [self._snapshot(row) for row in self._db.execute("SELECT * FROM commits ORDER BY round")]

    def _records(self, column):
        with self._lock:
            self._check_open()
            return [record for row in self._db.execute(f"SELECT {column} FROM commits ORDER BY round")
                    for record in json.loads(row[0])]

    def events(self):
        return self._records("events")

    def resolutions(self):
        return self._records("resolutions")

    def rounds(self):
        with self._lock:
            self._check_open()
            return [{"round": row["round"], "revision": row["revision"], "snapshot": json.loads(row["snapshot"]),
                     "events": json.loads(row["events"]), "resolutions": json.loads(row["resolutions"]),
                     "decisions": json.loads(row["decisions"])}
                    for row in self._db.execute("SELECT * FROM commits WHERE round>0 ORDER BY round")]

    def read_bundle(self):
        """Bind all result-reader inputs to one committed SQLite read snapshot."""
        with self._lock:
            self._check_open()
            self._db.execute("BEGIN")
            try:
                result = {"spec": self.spec, "head": self.head(), "rounds": self.rounds(),
                          "history": self.history(), "budget": self.budget_summary()}
                self._db.execute("COMMIT")
                return result
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def acquire_writer(self, owner_id, pid=None, takeover=False):
        require(isinstance(owner_id, str) and 0 < len(owner_id) <= 256,
                "invalid_writer", "Writer owner identity is required")
        pid = os.getpid() if pid is None else pid
        require(type(pid) is int and pid > 0, "invalid_writer", "Writer PID must be positive")
        with self._transaction():
            require(self._head_row()["round"] < len(self._spec["periods"]),
                    "horizon_complete", "Completed worlds cannot acquire a writer")
            writer = self._db.execute("SELECT * FROM writer WHERE singleton=1").fetchone()
            if writer["owner"] is not None:
                if (self._owned_fence == writer["fence"] and writer["owner"] == owner_id
                        and writer["pid"] == pid):
                    return writer["fence"]
                require(not _alive(writer["pid"]), "writer_active", "A live writer owns this world")
                require(takeover, "writer_takeover_required", "Dead writer requires explicit takeover")
            fence = writer["fence"] + 1
            self._db.execute("UPDATE writer SET fence=?,owner=?,pid=? WHERE singleton=1", (fence, owner_id, pid))
        self._owned_fence = fence
        return fence

    def _fence(self, fence):
        writer = self._db.execute("SELECT fence,owner FROM writer WHERE singleton=1").fetchone()
        require(type(fence) is int and writer is not None and writer["owner"] is not None
                and writer["fence"] == fence, "stale_fence", "Writer fence is no longer current")

    def release_writer(self, fence):
        with self._transaction():
            self._fence(fence)
            self._db.execute("UPDATE writer SET owner=NULL,pid=NULL WHERE singleton=1")
        if self._owned_fence == fence:
            self._owned_fence = None

    def _next_round(self, round_index):
        period_for(self._spec, round_index)
        require(round_index == self._head_row()["round"] + 1, "stale_round", "Only the next round may be written")

    def _slot_parts(self, slot):
        require(isinstance(slot, str), "invalid_slot", "Decision slot must be a string")
        parts = slot.split(":", 2)
        require(len(parts) == 3 and parts[0].isascii() and parts[0].isdigit(),
                "invalid_slot", "Invalid decision slot")
        round_index = int(parts[0])
        require(parts[0] == str(round_index) and parts[1] in _PHASES
                and parts[2] in actors_by_id(self._spec), "invalid_slot", "Unknown decision slot identity")
        return round_index, parts[1], parts[2]

    def _slot(self, slot):
        round_index, _, _ = self._slot_parts(slot)
        self._next_round(round_index)
        row = self._db.execute("SELECT * FROM slots WHERE slot=?", (slot,)).fetchone()
        require(row is not None, "phase_not_frozen", "Slot is not in a frozen phase roster")
        return row

    def freeze_phase(self, round_index, phase, actor_ids, fence):
        require(phase in _PHASES and isinstance(actor_ids, list)
                and all(isinstance(actor, str) and actor in actors_by_id(self._spec) for actor in actor_ids)
                and len(actor_ids) == len(set(actor_ids)), "invalid_phase", "Invalid phase participant roster")
        roster = canonical_json(sorted(actor_ids))
        with self._transaction():
            self._fence(fence)
            self._next_round(round_index)
            prior = self._db.execute("SELECT actors FROM phases WHERE round=? AND phase=?", (round_index, phase)).fetchone()
            if prior:
                require(prior[0] == roster, "phase_conflict", "Frozen participant roster cannot change")
                return
            if phase == "response":
                require(self._db.execute("SELECT 1 FROM phases WHERE round=? AND phase='proposal'", (round_index,)).fetchone()
                        and not self._db.execute("SELECT 1 FROM slots WHERE round=? AND phase='proposal' AND decision IS NULL", (round_index,)).fetchone(),
                        "missing_decisions", "Proposal receipts must complete before freezing responses")
            self._db.execute("INSERT INTO phases VALUES (?,?,?)", (round_index, phase, roster))
            self._db.executemany("INSERT INTO slots(slot,round,phase,actor) VALUES (?,?,?,?)",
                                 [(f"{round_index}:{phase}:{actor}", round_index, phase, actor) for actor in sorted(actor_ids)])

    def save_observation(self, slot, observation, fence):
        value = _json(observation)
        require(isinstance(value, dict), "invalid_observation", "Observation must be an object")
        identifier(value.get("observationId"), "observationId")
        with self._transaction():
            self._fence(fence)
            row = self._slot(slot)
            require(type(value.get("round")) is int and value["round"] == row["round"]
                    and value.get("phase") == row["phase"] and value.get("actorId") == row["actor"],
                    "observation_identity_mismatch", "Observation is bound to a different slot")
            encoded = canonical_json(value)
            require(row["observation"] is None or row["observation"] == encoded,
                    "observation_conflict", "Persisted observation cannot change")
            self._db.execute("UPDATE slots SET observation=? WHERE slot=?", (encoded, slot))

    def _receipt(self, slot, column):
        with self._lock:
            self._check_open()
            self._slot_parts(slot)
            row = self._db.execute(f"SELECT {column} FROM slots WHERE slot=?", (slot,)).fetchone()
            return json.loads(row[0]) if row and row[0] is not None else None

    def observation(self, slot):
        return self._receipt(slot, "observation")

    def decision(self, slot):
        return self._receipt(slot, "decision")

    def _validated_decision(self, value, observation, actor, phase):
        require(isinstance(value, dict), "invalid_decision", "Decision must be an object")
        raw = {key: item for key, item in value.items() if key not in {"round", "phase", "decisionId"}}
        require(isinstance(raw.get("intents"), list), "invalid_decision", "Decision intents must be a list")
        require(all(isinstance(intent, dict) for intent in raw["intents"]), "invalid_intent", "Intent must be an object")
        raw["intents"] = [{key: item for key, item in intent.items() if key not in {"intentId", "actorId", "phase"}}
                          for intent in raw["intents"]]
        normalized = validate_decision(self._spec, raw, actor, observation, phase=phase)
        require(canonical_json(normalized) == canonical_json(value),
                "decision_identity_mismatch", "Decision must match its validated observation and slot identity")

    def save_decision(self, slot, decision, fence):
        value = _json(decision)
        with self._transaction():
            self._fence(fence)
            row = self._slot(slot)
            require(row["observation"] is not None, "missing_observation", "Decision requires its persisted observation")
            self._validated_decision(value, json.loads(row["observation"]), row["actor"], row["phase"])
            encoded = canonical_json(value)
            require(row["decision"] is None or row["decision"] == encoded,
                    "decision_conflict", "Persisted decision cannot change")
            self._db.execute("UPDATE slots SET decision=? WHERE slot=?", (encoded, slot))

    @staticmethod
    def _usage(tokens, cost):
        require(type(tokens) is int and tokens >= 0, "invalid_usage", "Token usage must be a nonnegative integer")
        return {"tokens": tokens, "costUsd": quantity(decimal(cost, nonnegative=True))}

    def _budget(self):
        attempts = []
        reserved_tokens = actual_tokens = unknown_tokens = 0
        with localcontext() as context:
            context.prec = 64
            reserved_cost = actual_cost = unknown_cost = Decimal(0)
            for row in self._db.execute("SELECT * FROM attempts ORDER BY slot,ordinal"):
                reserved_tokens += row["reserved_tokens"]
                reserved_cost += Decimal(row["reserved_cost"])
                usage = json.loads(row["usage"]) if row["usage"] is not None else None
                if row["status"] in {"succeeded", "failed"}:
                    actual_tokens += usage["tokens"]
                    actual_cost += Decimal(usage["costUsd"])
                else:
                    unknown_tokens += row["reserved_tokens"]
                    unknown_cost += Decimal(row["reserved_cost"])
                attempts.append({"attemptId": row["attempt_id"], "slot": row["slot"], "ordinal": row["ordinal"],
                                 "status": row["status"], "reserved": {"tokens": row["reserved_tokens"],
                                 "costUsd": row["reserved_cost"]}, "usage": usage})
            # Historical allowance may exceed the per-run exposure ceiling as
            # known usage releases unused reservations. Do not apply the scalar
            # input magnitude limit to this cumulative audit total.
            return {"reserved": {"tokens": reserved_tokens, "costUsd": format(reserved_cost.normalize(), "f")},
                    "actual": {"tokens": actual_tokens, "costUsd": quantity(actual_cost)},
                    "unknown": {"tokens": unknown_tokens, "costUsd": quantity(unknown_cost)},
                    "exposure": {"tokens": actual_tokens + unknown_tokens, "costUsd": quantity(actual_cost + unknown_cost)},
                    "attempts": attempts}

    def budget_summary(self):
        """Reserved is lifetime allowance; exposure = actual + unknown (not reserved + actual)."""
        with self._lock:
            self._check_open()
            return self._budget()

    def reserve_attempt(self, slot, fence, reserved_tokens=0, reserved_cost="0"):
        reserved = self._usage(reserved_tokens, reserved_cost)
        with self._transaction():
            self._fence(fence)
            row = self._slot(slot)
            require(row["observation"] is not None, "missing_observation", "Attempt requires its persisted observation")
            require(row["decision"] is None, "decision_already_saved", "A completed decision cannot dispatch again")
            count = self._db.execute("SELECT COUNT(*) FROM attempts WHERE slot=?", (slot,)).fetchone()[0]
            require(count < self._spec["limits"]["maxAttemptsPerSlot"], "attempt_budget_exhausted", "Decision slot allowance exhausted")
            exposure = self._budget()["exposure"]
            with localcontext() as context:
                context.prec = 64
                require(exposure["tokens"] + reserved["tokens"] <= self._spec["limits"]["maxTokens"]
                        and decimal(exposure["costUsd"]) + decimal(reserved["costUsd"]) <= decimal(self._spec["limits"]["maxCostUsd"]),
                        "run_budget_exhausted", "Run token or cost allowance exhausted")
            attempt_id = uuid4().hex
            self._db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,'unknown',NULL)",
                             (attempt_id, slot, count + 1, reserved["tokens"], reserved["costUsd"]))
        return attempt_id

    def finish_attempt(self, attempt_id, status, usage, fence):
        require(status in {"succeeded", "failed", "unknown"}, "invalid_attempt_status", "Invalid attempt outcome")
        require(isinstance(usage, dict) and set(usage) == {"tokens", "costUsd"},
                "invalid_usage", "Usage must contain tokens and costUsd")
        normalized = self._usage(usage["tokens"], usage["costUsd"])
        encoded = canonical_json(normalized)
        with self._transaction():
            self._fence(fence)
            row = self._db.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            require(row is not None, "unknown_attempt", "Attempt reservation does not exist")
            self._slot(row["slot"])
            require(normalized["tokens"] <= row["reserved_tokens"]
                    and decimal(normalized["costUsd"]) <= decimal(row["reserved_cost"]),
                    "reservation_exceeded", "Reported usage exceeds the reserved allowance")
            if row["usage"] is not None:
                require(row["status"] == status and row["usage"] == encoded,
                        "attempt_conflict", "Finished attempt receipt cannot change")
                return
            self._db.execute("UPDATE attempts SET status=?,usage=? WHERE attempt_id=?", (status, encoded, attempt_id))

    def _validate_closure(self, snapshot, previous=None):
        require(isinstance(snapshot, dict), "invalid_snapshot", "World snapshot must be an object")
        for field in ("accounts", "metrics", "rules", "relations", "commitments", "interactions", "actorStates", "sampling"):
            require(isinstance(snapshot.get(field), dict), "incomplete_snapshot", f"Snapshot requires {field}")
            if field != "sampling":
                require(all(isinstance(record, dict) for record in snapshot[field].values()),
                        "invalid_snapshot", f"Snapshot {field} records must be objects")
        for field in ("scheduledEvents", "appliedEvents"):
            require(isinstance(snapshot.get(field), list), "incomplete_snapshot", f"Snapshot requires {field}")
        require(all("balance" in account and "reserved" in account for account in snapshot["accounts"].values()),
                "incomplete_snapshot", "Accounts require balances and reservations")
        validate_snapshot(self._spec, snapshot)
        expected_time = self._spec["asOf"] if snapshot["round"] == 0 else period_for(self._spec, snapshot["round"])["end"]
        require(snapshot.get("simulatedAt") == expected_time, "invalid_time", "Snapshot must end at its declared period boundary")
        baseline = self._spec["initialState"]["accounts"]
        require(set(snapshot["accounts"]) == set(baseline), "resource_violation", "Account roster cannot change")
        with localcontext() as context:
            context.prec = 64
            totals, initial_totals = {}, {}
            for aid, account in snapshot["accounts"].items():
                original = baseline[aid]
                require(account.get("ownerId") == original["ownerId"] and account.get("unit") == original["unit"],
                        "resource_violation", "Account ownership and units cannot change")
                unit = original["unit"]
                totals[unit] = totals.get(unit, Decimal(0)) + decimal(account["balance"], nonnegative=True)
                initial_totals[unit] = initial_totals.get(unit, Decimal(0)) + decimal(original["balance"], nonnegative=True)
            require(totals == initial_totals, "resource_violation", "Account resources are not conserved by unit")
        for state in snapshot["actorStates"].values():
            require(isinstance(state, dict) and all(isinstance(state.get(key), list) for key in
                    ("beliefs", "plans", "priorityChanges", "observedEvents")),
                    "incomplete_snapshot", "Actor state closure is incomplete")
        sampling = snapshot["sampling"]
        require(sampling.get("seed") == self._spec["seed"] and isinstance(sampling.get("draws"), list),
                "invalid_sampling", "Snapshot sampling closure is incomplete")
        require(all(isinstance(event, str) for event in snapshot["appliedEvents"])
                and len(set(snapshot["appliedEvents"])) == len(snapshot["appliedEvents"]),
                "invalid_event", "Applied event identities must be unique")
        if previous is not None:
            require(set(previous["appliedEvents"]) <= set(snapshot["appliedEvents"]),
                    "invalid_event", "Applied event history cannot be removed")
            draws = previous["sampling"]["draws"]
            require(sampling["draws"][:len(draws)] == draws, "invalid_sampling", "Recorded draws cannot change")

    def commit_round(self, expected_round, snapshot, events, resolutions, decisions, fence):
        value = _json(snapshot)
        require(isinstance(value, dict), "invalid_snapshot", "World snapshot must be an object")
        value.pop("revision", None)
        events, resolutions, decisions = _json(events), _json(resolutions), _json(decisions)
        require(type(expected_round) is int and all(isinstance(items, list) for items in (events, resolutions, decisions)),
                "invalid_commit", "Round evidence must be lists and expected round an integer")
        with self._transaction():
            self._fence(fence)
            head = self._head_row()
            require(head["round"] == expected_round, "stale_round", "Committed head changed")
            round_index = expected_round + 1
            self._next_round(round_index)
            require(value.get("round") == round_index, "invalid_round", "Snapshot does not advance exactly one round")
            self._validate_closure(value, json.loads(head["snapshot"]))
            phases = self._db.execute("SELECT phase FROM phases WHERE round=?", (round_index,)).fetchall()
            require({row[0] for row in phases} == set(_PHASES), "phase_not_frozen", "Both phase rosters must be frozen")
            receipts = self._db.execute("SELECT * FROM slots WHERE round=? ORDER BY phase,actor", (round_index,)).fetchall()
            require(all(row["decision"] is not None and row["observation"] is not None for row in receipts),
                    "missing_decisions", "Required phase decisions are missing")
            require(all(isinstance(decision, dict) for decision in decisions), "invalid_decision", "Decision receipt must be an object")
            persisted = [json.loads(row["decision"]) for row in receipts]
            require(sorted(canonical_json(decision) for decision in decisions) == sorted(row["decision"] for row in receipts),
                    "decision_set_mismatch", "Commit must include exactly the persisted decision receipts")
            # Persist normalized causal order, independent of worker arrival order.
            decisions = sorted(persisted, key=lambda item: (_PHASES.index(item["phase"]), item["actorId"]))
            intents = {intent["intentId"]: intent for decision in decisions for intent in decision["intents"]}
            require(len(resolutions) == len(intents), "resolution_set_mismatch", "Every intent requires exactly one resolution")
            resolved = set()
            for resolution in resolutions:
                require(isinstance(resolution, dict), "invalid_resolution", "Resolution must be an object")
                intent_id = resolution.get("intentId")
                require(isinstance(intent_id, str) and intent_id in intents and intent_id not in resolved
                        and resolution.get("actorId") == intents[intent_id]["actorId"]
                        and type(resolution.get("round")) is int and resolution["round"] == round_index
                        and type(resolution.get("accepted")) is bool and isinstance(resolution.get("code"), str)
                        and isinstance(resolution.get("explanation"), str), "invalid_resolution", "Resolution identity or outcome is invalid")
                resolved.add(intent_id)
            require(len(events) <= self._spec["limits"]["maxEventsPerRound"], "event_limit", "Round event limit exceeded")
            event_ids = set()
            period = period_for(self._spec, round_index)
            for event in events:
                require(isinstance(event, dict), "invalid_event", "Event must be an object")
                event_id = identifier(event.get("eventId"), "eventId")
                require(event_id not in event_ids and not self._db.execute("SELECT 1 FROM event_ids WHERE event_id=?", (event_id,)).fetchone(),
                        "duplicate_event", "Event identity was already committed")
                require(type(event.get("round")) is int and event["round"] == round_index
                        and parse_time(period["start"]) <= parse_time(event.get("at")) <= parse_time(period["end"]),
                        "invalid_event", "Event does not belong to this round")
                require(isinstance(event.get("kind"), str) and isinstance(event.get("description"), str)
                        and isinstance(event.get("basis"), dict)
                        and event["basis"].get("kind") in {"scenario_assumption", "source_claim", "report_excerpt", "simulation_event"}
                        and isinstance(event["basis"].get("refs"), list) and bool(event["basis"]["refs"]),
                        "invalid_event", "Event requires a kind, explanation, and provenance")
                visibility(event.get("visibility"), set(actors_by_id(self._spec)))
                if event.get("actorId") is not None:
                    require(event["actorId"] in actors_by_id(self._spec), "invalid_event", "Unknown event actor")
                event_ids.add(event_id)
            # Re-execute only the bounded, pure kernel against durable inputs.
            # This checks the entire pending/actor/event closure without inventing
            # a second mechanism implementation in the persistence boundary.
            # It performs no provider, graph, clock, or filesystem operations.
            from .kernel import resolve_round

            expected = resolve_round(self._spec, json.loads(head["snapshot"]), decisions, round_index)
            require(canonical_json(value) == canonical_json(expected["snapshot"])
                    and canonical_json(events) == canonical_json(expected["events"])
                    and canonical_json(resolutions) == canonical_json(expected["resolutions"]),
                    "transition_mismatch", "Committed closure differs from replay of its durable decisions")
            revision = _revision(value, head["revision"], events, resolutions, decisions)
            self._db.execute("INSERT INTO commits VALUES (?,?,?,?,?,?,?)", (round_index, revision, head["revision"],
                             canonical_json(value), canonical_json(events), canonical_json(resolutions), canonical_json(decisions)))
            self._db.executemany("INSERT INTO event_ids VALUES (?,?)", [(event_id, round_index) for event_id in sorted(event_ids)])
            self._db.execute("UPDATE head SET round=? WHERE singleton=1", (round_index,))
