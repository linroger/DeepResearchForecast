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
import re
import sqlite3
import threading
from uuid import uuid4

from .contracts import (
    REFUSAL_CODES, WorldError as WorldError,
    actors_by_id, canonical_json, decimal, digest, identifier,
    parse_time, period_for, quantity, require, validate_decision,
    validate_snapshot, validate_spec, visibility,
)

# v2: attempts may be 'abandoned' (open when a later writer fence superseded theirs) or
# 'throttled' (refused for provider capacity, nothing metered); neither counts toward a
# slot's allowance, and a review stage left so is dispatched again under a new journal row.
# Readers accept v1 files unchanged; the first writer migrates them (_migrate).
_VERSION = 2
_READABLE_VERSIONS = (1, 2)
_APPLICATION_ID = 0x57524C44
_PHASES = ("proposal", "response")
_ATTEMPT_STATUSES = frozenset({"unknown", "succeeded", "failed", "abandoned", "throttled"})
_INACTIVE_ATTEMPTS = frozenset({"abandoned", "throttled"})
_ZERO_USAGE = {"tokens": 0, "costUsd": "0"}
# A committed review decision whose final assessment stayed unresolved carries this marker.
UNRESOLVED_MARKER = ("consistencyStatus", "unresolved")
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
# v1 also declared UNIQUE(slot,stage), which made an abandoned stage impossible to redispatch;
# the store now enforces one live candidate and one live revision per slot itself.
_REVIEW_TABLE = (
    "CREATE TABLE {name} (attempt_id TEXT PRIMARY KEY REFERENCES attempts(attempt_id), "
    "slot TEXT NOT NULL REFERENCES slots(slot), stage TEXT NOT NULL CHECK(stage IN ('candidate','revision')), "
    "observation_hash TEXT NOT NULL, candidate_attempt_id TEXT REFERENCES attempts(attempt_id), candidate_hash TEXT, "
    "decision TEXT, assessment TEXT, error TEXT, receipt_hash TEXT NOT NULL)"
)
_REVIEW_SCHEMA = (_REVIEW_TABLE.format(name="consistency_journal"),
                  "CREATE INDEX consistency_journal_slot ON consistency_journal(slot)")
_REVIEW_COLUMNS = {"attempt_id", "slot", "stage", "observation_hash", "candidate_attempt_id",
                   "candidate_hash", "decision", "assessment", "error", "receipt_hash"}


def _review_pin(spec):
    # Unpinned worlds have no dependency on, or migration to, the new journal.
    policy = spec.get("policy", {})
    if isinstance(policy, dict) and "candidateRepair" in policy:
        from .review import candidate_repair_enabled

        candidate_repair_enabled(spec)  # Reject an invalid explicit pin before creating/opening a database.
    if not isinstance(policy, dict) or "decisionReview" not in policy:
        return None
    from .review import review_mode

    return review_mode(spec)


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


def _live(entries):
    """Journal entries that are stages: abandoned and throttled attempts are closed records."""
    return [entry for entry in entries if entry["status"] not in _INACTIVE_ATTEMPTS]


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
        self._review_mode = _review_pin(supplied) if supplied is not None else None
        require(self.path.is_file() or (not self.read_only and supplied is not None),
                "missing_world", "Opening a new world requires a specification")
        if not self.read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                # A reader must never see a half-made world: sqlite3.connect creates an empty
                # file at once and the schema only appears when the init transaction commits,
                # so a status poll in between (or after a failed init) raised unsupported_store.
                self._create_atomically(supplied)
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
                    self._migrate()
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

    def _create_atomically(self, spec):
        """Build a new world in a temporary file next to its final path, then publish it with a
        hard link: readers see either no world (missing_world) or a complete, initialised one.

        os.link fails if the final path already exists, so a concurrent creator can never
        replace a world another writer has already opened; the loser discards its copy and
        opens the winner's, whose spec the normal open then verifies.  The temporary database
        uses rollback journalling so no -wal/-shm side files exist at publication; the normal
        writer connection switches the final file to WAL.  A failed initialisation leaves no
        file at the final path.
        """
        tmp = self.path.with_name(f".{self.path.name}.init-{os.getpid()}-{uuid4().hex[:8]}")
        db = sqlite3.connect(str(tmp), timeout=30, isolation_level=None, check_same_thread=False)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            self._db = db
            with self._transaction():
                self._initialize(spec)
            db.close()
            fd = os.open(str(tmp), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            try:
                os.link(str(tmp), str(self.path))
            except FileExistsError:
                pass  # another creator published first; its world is complete
            tmp.unlink()
            dir_fd = os.open(str(self.path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except BaseException:
            try:
                db.close()
            except Exception:  # noqa: BLE001 — already closed on the success path
                pass
            for leftover in (tmp, tmp.with_name(tmp.name + "-journal")):
                try:
                    leftover.unlink()
                except FileNotFoundError:
                    pass
            raise
        finally:
            self._db = None

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
        if self._review_mode is not None:
            for statement in _REVIEW_SCHEMA:
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

    def _migrate(self):
        """Bring a readable older file to _VERSION inside the opening writer transaction.

        v1 -> v2 rebuilds the review journal without UNIQUE(slot,stage), row for row; no
        receipt, revision or attempt changes. Readers never migrate.
        """
        require(self._db.execute("PRAGMA application_id").fetchone()[0] == _APPLICATION_ID,
                "unsupported_store", "Unsupported world database schema")
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version == _VERSION:
            return
        require(version in _READABLE_VERSIONS, "unsupported_store", "Unsupported world database schema")
        if self._db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='consistency_journal'").fetchone():
            columns = ",".join(("attempt_id", "slot", "stage", "observation_hash", "candidate_attempt_id",
                                "candidate_hash", "decision", "assessment", "error", "receipt_hash"))
            self._db.execute(_REVIEW_TABLE.format(name="consistency_journal_v2"))
            self._db.execute(f"INSERT INTO consistency_journal_v2 ({columns}) SELECT {columns} FROM consistency_journal")
            self._db.execute("DROP TABLE consistency_journal")
            self._db.execute("ALTER TABLE consistency_journal_v2 RENAME TO consistency_journal")
            self._db.execute(_REVIEW_SCHEMA[1])
        self._db.execute(f"PRAGMA user_version={_VERSION}")

    def _load(self, supplied):
        require(self._db.execute("PRAGMA application_id").fetchone()[0] == _APPLICATION_ID
                and self._db.execute("PRAGMA user_version").fetchone()[0] in _READABLE_VERSIONS,
                "unsupported_store", "Unsupported world database schema")
        require(self._db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
                and not self._db.execute("PRAGMA foreign_key_check").fetchall(),
                "corrupt_store", "World database integrity check failed")
        row = self._db.execute("SELECT * FROM model WHERE singleton=1").fetchone()
        require(row is not None, "corrupt_store", "World model is missing")
        self._spec = validate_spec(json.loads(row["spec"]))
        self._review_mode = _review_pin(self._spec)
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
        if self._review_mode is not None:
            self._verify_consistency_journal()

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
        context = self._consistency_read() if self._review_mode is not None else self._lock
        with context:
            self._check_open()
            if self._review_mode is not None:
                self._verify_consistency_journal()
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

    def acquire_writer(self, owner_id, pid=None, takeover=False, holds_launch_lock=False):
        """Advance the writer fence for ``owner_id``.

        ``holds_launch_lock``: the caller holds this world's exclusive launch flock
        (world_launch.lock). Every world child holds it for its whole life and the kernel
        drops it when the holder exits, also across a reboot, so an owner recorded by another
        process has exited and is taken over without probing its PID, which macOS soon reuses.
        An owner recorded with this very process's PID is another live store object. Without
        the lock, an owner whose PID still answers is protected (fail closed, see _alive).
        """
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
                live = writer["pid"] == os.getpid() if holds_launch_lock else _alive(writer["pid"])
                require(not live, "writer_active", "A live writer owns this world")
                require(takeover, "writer_takeover_required", "Dead writer requires explicit takeover")
            fence = writer["fence"] + 1
            self._abandon_open_attempts()
            self._db.execute("UPDATE writer SET fence=?,owner=?,pid=? WHERE singleton=1", (fence, owner_id, pid))
        self._owned_fence = fence
        return fence

    def _abandon_open_attempts(self):
        """Every attempt still 'unknown' belongs to a superseded fence: no writer can finish it.

        Its reservation stays in budget exposure (abandoned counts as unknown), it leaves its
        slot's allowance, and a pinned review stage can be dispatched again. Runs inside the
        transaction that advances the fence, before the new fence reserves anything.
        """
        open_attempts = [row[0] for row in self._db.execute("SELECT attempt_id FROM attempts WHERE status='unknown'")]
        if not open_attempts:
            return
        rehashed = []
        if self._review_mode is not None:
            slots = {row[0] for row in self._db.execute(
                f"SELECT slot FROM attempts WHERE attempt_id IN ({','.join('?' * len(open_attempts))})", open_attempts)}
            for slot in sorted(slots):
                _, entries = self._verified_consistency(slot)
                for entry in entries:
                    if entry["attempt_id"] in open_attempts:
                        rehashed.append((self._consistency_hash({**entry, "status": "abandoned"}), entry["attempt_id"]))
        self._db.execute("UPDATE attempts SET status='abandoned' WHERE status='unknown'")
        if rehashed:
            self._db.executemany("UPDATE consistency_journal SET receipt_hash=? WHERE attempt_id=?", rehashed)

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
        if self._review_mode is not None:
            with self._consistency_read():
                _, entries = self._verified_consistency(slot)
                final = self._final_decision(_live(entries))
                return _json(final) if final is not None else None
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
            require(self._review_mode is None, "consistency_admission_required",
                    "Pinned decisions require atomic consistency revision completion")
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
        review_entries = self._verify_consistency_journal() if self._review_mode is not None else {}
        attempts = []
        reserved_tokens = actual_tokens = unknown_tokens = 0
        with localcontext() as context:
            context.prec = 64
            reserved_cost = actual_cost = unknown_cost = Decimal(0)
            for row in self._db.execute("SELECT * FROM attempts ORDER BY slot,ordinal"):
                reserved_tokens += row["reserved_tokens"]
                reserved_cost += Decimal(row["reserved_cost"])
                usage = json.loads(row["usage"]) if row["usage"] is not None else None
                # 'throttled' is known zero usage; 'abandoned' keeps its whole reservation as unknown.
                if row["status"] in {"succeeded", "failed", "throttled"}:
                    actual_tokens += usage["tokens"]
                    actual_cost += Decimal(usage["costUsd"])
                else:
                    unknown_tokens += row["reserved_tokens"]
                    unknown_cost += Decimal(row["reserved_cost"])
                attempts.append({"attemptId": row["attempt_id"], "slot": row["slot"], "ordinal": row["ordinal"],
                                 "status": row["status"], "reserved": {"tokens": row["reserved_tokens"],
                                 "costUsd": row["reserved_cost"]}, "usage": usage})
                if self._review_mode is not None:
                    entry = review_entries[row["attempt_id"]]
                    attempts[-1]["purpose"] = entry["stage"]
                    if entry["error"] is not None:
                        attempts[-1]["errorCode"] = entry["error"]["code"]
                    if entry["stage"] == "revision" and self._candidate_repair_enabled():
                        first = review_entries[entry["candidate_attempt_id"]]
                        attempts[-1]["reviewInputKind"] = "candidate" if first["status"] == "succeeded" else "candidate_error"
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
        context = self._consistency_read() if self._review_mode is not None else self._lock
        with context:
            self._check_open()
            return self._budget()

    def reserve_attempt(self, slot, fence, reserved_tokens=0, reserved_cost="0"):
        reserved = self._usage(reserved_tokens, reserved_cost)
        with self._transaction():
            self._fence(fence)
            require(self._review_mode is None, "consistency_admission_required",
                    "Pinned attempts require an explicit consistency stage")
            row = self._slot(slot)
            require(row["observation"] is not None, "missing_observation", "Attempt requires its persisted observation")
            require(row["decision"] is None, "decision_already_saved", "A completed decision cannot dispatch again")
            count, last = self._db.execute(
                "SELECT COALESCE(SUM(status NOT IN ('abandoned','throttled')),0), COALESCE(MAX(ordinal),0) "
                "FROM attempts WHERE slot=?", (slot,)).fetchone()
            require(count < self._spec["limits"]["maxAttemptsPerSlot"], "attempt_budget_exhausted", "Decision slot allowance exhausted")
            exposure = self._budget()["exposure"]
            with localcontext() as context:
                context.prec = 64
                require(exposure["tokens"] + reserved["tokens"] <= self._spec["limits"]["maxTokens"]
                        and decimal(exposure["costUsd"]) + decimal(reserved["costUsd"]) <= decimal(self._spec["limits"]["maxCostUsd"]),
                        "run_budget_exhausted", "Run token or cost allowance exhausted")
            attempt_id = uuid4().hex
            self._db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,'unknown',NULL)",
                             (attempt_id, slot, last + 1, reserved["tokens"], reserved["costUsd"]))
        return attempt_id

    def finish_attempt(self, attempt_id, status, usage, fence):
        """Record an attempt outcome; 'throttled' means refused before metering (zero usage)."""
        require(status in {"succeeded", "failed", "unknown", "throttled"}, "invalid_attempt_status", "Invalid attempt outcome")
        require(isinstance(usage, dict) and set(usage) == {"tokens", "costUsd"},
                "invalid_usage", "Usage must contain tokens and costUsd")
        normalized = self._usage(usage["tokens"], usage["costUsd"])
        require(status != "throttled" or normalized == _ZERO_USAGE,
                "invalid_usage", "A throttled attempt was refused before metering")
        encoded = canonical_json(normalized)
        with self._transaction():
            self._fence(fence)
            require(self._review_mode is None, "consistency_admission_required",
                    "Pinned attempts require atomic consistency completion")
            row = self._db.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            require(row is not None, "unknown_attempt", "Attempt reservation does not exist")
            require(row["status"] != "abandoned", "attempt_abandoned",
                    "A superseded writer's attempt cannot be finished")
            self._slot(row["slot"])
            require(normalized["tokens"] <= row["reserved_tokens"]
                    and decimal(normalized["costUsd"]) <= decimal(row["reserved_cost"]),
                    "reservation_exceeded", "Reported usage exceeds the reserved allowance")
            if row["usage"] is not None:
                require(row["status"] == status and row["usage"] == encoded,
                        "attempt_conflict", "Finished attempt receipt cannot change")
                return
            self._db.execute("UPDATE attempts SET status=?,usage=? WHERE attempt_id=?", (status, encoded, attempt_id))

    @contextmanager
    def _consistency_read(self):
        """Read related journal/slot/attempt rows from a single SQLite snapshot."""
        with self._lock:
            self._check_open()
            owns_transaction = not self._db.in_transaction
            if owns_transaction:
                self._db.execute("BEGIN")
            try:
                yield
                if owns_transaction:
                    self._db.execute("COMMIT")
            except BaseException:
                if owns_transaction:
                    self._db.execute("ROLLBACK")
                raise

    def _require_consistency(self):
        require(self._review_mode is not None, "consistency_not_enabled", "Decision review is not pinned for this world")
        table = self._db.execute("SELECT type FROM sqlite_master WHERE name='consistency_journal'").fetchone()
        require(table is not None and table[0] == "table"
                and {row[1] for row in self._db.execute("PRAGMA table_info(consistency_journal)")} == _REVIEW_COLUMNS,
                "corrupt_consistency_journal", "Pinned consistency journal is missing or has an invalid schema")

    @staticmethod
    def _consistency_error(error, *, repair_eligible=False):
        if error is None:
            return None
        require(isinstance(error, dict) and set(error) == {"code", "message"}
                and isinstance(error["code"], str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", error["code"])
                and isinstance(error["message"], str), "invalid_consistency_error", "Failure requires a bounded error code and message")
        # Never store an opaque exception/provider/model string, even privately.
        safe = {"code": error["code"], "message": "Consistency attempt did not produce an admissible response."}
        if repair_eligible:
            safe["candidateRepairEligible"] = True
        return safe

    def _candidate_repair_enabled(self):
        policy = self._spec.get("policy", {})
        if not isinstance(policy, dict) or "candidateRepair" not in policy:
            return False
        from .review import candidate_repair_enabled

        return candidate_repair_enabled(self._spec)

    def _candidate_repair_context(self, entry, observation):
        """Validate a stored eligibility marker; code/usage alone never qualify."""
        from .review import CANDIDATE_OUTPUT_ERRORS, candidate_error_context, validate_candidate_error_context

        error = entry["error"]
        require(self._candidate_repair_enabled() and entry["stage"] == "candidate" and entry["status"] == "failed"
                and entry["usage"] is not None and entry["decision"] is None and entry["assessment"] is None
                and isinstance(error, dict) and set(error) == {"code", "message", "candidateRepairEligible"}
                and error["candidateRepairEligible"] is True and isinstance(error["code"], str)
                and error["code"] in CANDIDATE_OUTPUT_ERRORS,
                "invalid_candidate_repair", "Only explicitly eligible known candidate-output failures permit repair")
        safe = self._consistency_error({key: error[key] for key in ("code", "message")}, repair_eligible=True)
        require(safe == error, "invalid_candidate_repair", "Candidate repair diagnostic is not canonical")
        context = candidate_error_context(observation, error["code"])
        return validate_candidate_error_context(context, observation)

    def _consistency_review_input(self, entry, observation):
        if entry["stage"] == "candidate" and entry["status"] == "succeeded":
            return entry["decision"]
        if isinstance(entry["error"], dict) and "candidateRepairEligible" in entry["error"]:
            return self._candidate_repair_context(entry, observation)
        return None

    def _consistency_hash(self, entry):
        return digest({"schemaVersion": "world-consistency-receipt/v1", "mode": self._review_mode,
                       "specHash": digest(self._spec), **{key: entry[key] for key in (
                           "attempt_id", "slot", "stage", "observation_hash", "candidate_attempt_id", "candidate_hash",
                           "ordinal", "reserved_tokens", "reserved_cost", "status", "usage", "decision", "assessment", "error")}})

    def _validated_withheld_consistency(self, entry, observation):
        """A revision whose validated assessment stayed unresolved: private evidence plus the
        decision the slot commits with UNRESOLVED_MARKER (any review mode)."""
        from .review import assessment_status, validate_assessment

        require(entry["stage"] == "revision" and entry["status"] == "failed"
                and entry["usage"] is not None and entry["decision"] is not None and entry["assessment"] is not None
                and isinstance(entry["error"], dict) and entry["error"].get("code") == "consistency_unresolved",
                "invalid_consistency_payload", "Only validated unresolved revisions may retain private evidence")
        self._validated_decision(entry["decision"], observation, observation["actorId"], observation["phase"])
        assessment = validate_assessment(entry["assessment"], observation, entry["decision"], mode=self._review_mode)
        require(assessment_status(assessment, mode=self._review_mode) == "unresolved",
                "invalid_consistency_payload", "Withheld evidence must retain an unresolved verdict")

    def _verified_consistency(self, slot):
        """Validate private state before returning any candidate or final receipt.

        Entries follow attempt ordinal. An 'abandoned' or 'throttled' entry is a closed record
        that keeps its exposure and audit row but is not a stage; the live entries, a candidate
        and then a revision bound to it, decide the slot.
        """
        self._require_consistency()
        round_index, phase, actor = self._slot_parts(slot)
        state = {"candidate": None, "candidateAttempt": None, "reviewAttempt": None}
        try:
            row = self._db.execute("SELECT * FROM slots WHERE slot=?", (slot,)).fetchone()
            entries = [dict(item) for item in self._db.execute(
                "SELECT j.*,a.attempt_id AS linked_attempt,a.slot AS attempt_slot,a.ordinal,a.reserved_tokens,"
                "a.reserved_cost,a.status,a.usage FROM consistency_journal j LEFT JOIN attempts a "
                "ON a.attempt_id=j.attempt_id WHERE j.slot=? ORDER BY a.ordinal", (slot,))]
            attempts = self._db.execute("SELECT COUNT(*) FROM attempts WHERE slot=?", (slot,)).fetchone()[0]
            require(len(entries) == attempts, "corrupt_consistency_journal", "Consistency attempt linkage is incomplete")
            if row is None:
                require(not entries, "corrupt_consistency_journal", "Consistency slot is missing")
                return state, []
            require(row["round"] == round_index and row["phase"] == phase and row["actor"] == actor,
                    "corrupt_consistency_journal", "Consistency slot identity changed")
            observation = json.loads(row["observation"]) if row["observation"] is not None else None
            if entries:
                require(isinstance(observation, dict) and type(observation.get("round")) is int
                        and observation["round"] == round_index and observation.get("actorId") == actor
                        and observation.get("phase") == phase and isinstance(observation.get("observationId"), str),
                        "corrupt_consistency_journal", "Consistency observation binding is invalid")
            live = []
            for ordinal, entry in enumerate(entries, 1):
                for key in ("usage", "decision", "assessment", "error"):
                    entry[key] = json.loads(entry[key]) if entry[key] is not None else None
                require(len(live) < 2, "corrupt_consistency_journal", "Consistency attempt follows a final revision")
                stage = "candidate" if not live else "revision"
                require(entry["linked_attempt"] == entry["attempt_id"] and entry["attempt_slot"] == slot
                        and entry["ordinal"] == ordinal and entry["stage"] == stage
                        and entry["observation_hash"] == digest(observation)
                        and entry["status"] in _ATTEMPT_STATUSES,
                        "corrupt_consistency_journal", "Consistency purpose or attempt identity changed")
                self._usage(entry["reserved_tokens"], entry["reserved_cost"])
                if stage == "candidate":
                    require(entry["candidate_attempt_id"] is None and entry["candidate_hash"] is None,
                            "corrupt_consistency_journal", "Candidate has an invalid predecessor")
                else:
                    candidate = live[0]
                    review_input = self._consistency_review_input(candidate, observation)
                    require(review_input is not None
                            and entry["candidate_attempt_id"] == candidate["attempt_id"]
                            and entry["candidate_hash"] == digest(review_input),
                            "corrupt_consistency_journal", "Revision is not bound to its eligible review input")
                require(entry["receipt_hash"] == self._consistency_hash(entry),
                        "corrupt_consistency_journal", "Consistency receipt hash changed")
                if entry["usage"] is None:
                    require(entry["status"] in {"unknown", "abandoned"}
                            and all(entry[key] is None for key in ("decision", "assessment", "error")),
                            "corrupt_consistency_journal", "Unfinished consistency attempt has a payload")
                else:
                    usage = entry["usage"]
                    require(isinstance(usage, dict) and set(usage) == {"tokens", "costUsd"},
                            "corrupt_consistency_journal", "Consistency usage is invalid")
                    self._usage(usage["tokens"], usage["costUsd"])
                    require(usage["tokens"] <= entry["reserved_tokens"]
                            and decimal(usage["costUsd"]) <= decimal(entry["reserved_cost"]),
                            "corrupt_consistency_journal", "Consistency usage exceeds its reservation")
                    if entry["status"] == "succeeded":
                        require(entry["error"] is None, "corrupt_consistency_journal", "Successful consistency receipt contains an error")
                        self._validated_decision(entry["decision"], observation, actor, phase)
                        if stage == "candidate":
                            require(entry["assessment"] is None, "corrupt_consistency_journal", "Candidate contains a final assessment")
                        else:
                            from .review import assessment_status, validate_assessment

                            assessment = validate_assessment(entry["assessment"], observation, entry["decision"], mode=self._review_mode)
                            require(assessment_status(assessment, mode=self._review_mode) == "clear", "corrupt_consistency_journal", "Final assessment is not clear")
                    elif entry["status"] == "throttled":
                        require(usage == _ZERO_USAGE and entry["decision"] is None and entry["assessment"] is None
                                and isinstance(entry["error"], dict) and entry["error"].get("code") in REFUSAL_CODES
                                and self._consistency_error(entry["error"]) == entry["error"],
                                "corrupt_consistency_journal", "Throttled consistency attempt has an invalid payload")
                    else:
                        if isinstance(entry["error"], dict) and "candidateRepairEligible" in entry["error"]:
                            self._candidate_repair_context(entry, observation)
                        else:
                            require(self._consistency_error(entry["error"]) == entry["error"],
                                    "corrupt_consistency_journal", "Failed consistency attempt has an invalid payload")
                        if entry["decision"] is not None or entry["assessment"] is not None:
                            self._validated_withheld_consistency(entry, observation)
                if entry["status"] in _INACTIVE_ATTEMPTS:
                    continue
                live.append(entry)
                attempt = {"attemptId": entry["attempt_id"], "status": entry["status"], "stage": stage}
                if entry["error"] is not None:
                    attempt["errorCode"] = entry["error"]["code"]
                state["candidateAttempt" if stage == "candidate" else "reviewAttempt"] = attempt
                if stage == "candidate" and entry["status"] == "succeeded":
                    state["candidate"] = entry["decision"]
            final = self._final_decision(live)
            require(row["decision"] == (canonical_json(final) if final is not None else None),
                    "corrupt_consistency_journal", "Final decision lacks its matching completed revision")
            return state, entries
        except (ValueError, TypeError, KeyError, sqlite3.DatabaseError) as error:
            if isinstance(error, WorldError) and error.code == "corrupt_consistency_journal":
                raise
            raise WorldError("corrupt_consistency_journal", "Consistency journal validation failed") from None

    @staticmethod
    def _revision_decision(revision):
        """The decision a finished revision commits, or None.

        A cleared revision commits as is. A validated revision whose assessment stayed
        unresolved (failed, consistency_unresolved, withheld payload) commits its decision with
        UNRESOLVED_MARKER, so the round goes on and the record says the review did not clear.
        """
        if revision["status"] == "succeeded":
            return revision["decision"]
        if (revision["status"] == "failed" and revision["decision"] is not None
                and isinstance(revision["error"], dict) and revision["error"].get("code") == "consistency_unresolved"):
            key, value = UNRESOLVED_MARKER
            return {**revision["decision"], key: value}
        return None

    @classmethod
    def _final_decision(cls, live):
        """The slot's admitted decision: the one its live revision commits."""
        return cls._revision_decision(live[1]) if len(live) == 2 else None

    def _verify_consistency_journal(self):
        self._require_consistency()
        entries = {}
        slots = {row[0] for row in self._db.execute(
            "SELECT slot FROM slots UNION SELECT slot FROM attempts UNION SELECT slot FROM consistency_journal")}
        for slot in slots:
            _, rows = self._verified_consistency(slot)
            entries.update((row["attempt_id"], row) for row in rows)
        # A committed decision cannot outlive the private admission proof.
        for row in self._db.execute("SELECT decisions FROM commits WHERE round>0"):
            for decision in json.loads(row[0]):
                slot = f"{decision['round']}:{decision['phase']}:{decision['actorId']}"
                _, rows = self._verified_consistency(slot)
                require(self._final_decision(_live(rows)) == decision,
                        "corrupt_consistency_journal", "Committed decision lacks its consistency receipt")
        return entries

    def consistency_state(self, slot):
        with self._consistency_read():
            state, _ = self._verified_consistency(slot)
            return _json(state)

    def consistency_review_input(self, slot):
        """Private review input derived only from validated durable records."""
        with self._consistency_read():
            _, entries = self._verified_consistency(slot)
            live = _live(entries)
            if not live:
                return None
            observation = self._receipt(slot, "observation")
            return _json(self._consistency_review_input(live[0], observation))

    def consistency_receipt(self, slot):
        """Private audit only; public world/result exports never include this."""
        with self._consistency_read():
            state, entries = self._verified_consistency(slot)
            live = _live(entries)
            if len(live) != 2 or live[1]["status"] != "succeeded":
                return None
            candidate, final = live
            receipt = {"mode": self._review_mode, "slot": slot,
                          "observationId": final["decision"]["observationId"], "observationHash": final["observation_hash"],
                          "candidate": state["candidate"], "candidateHash": final["candidate_hash"],
                          "finalDecisionId": final["decision"]["decisionId"], "finalDecisionHash": digest(final["decision"]),
                          "assessment": final["assessment"], "receiptHash": final["receipt_hash"],
                          "stages": [{"attemptId": item["attempt_id"], "stage": item["stage"], "status": item["status"],
                                      "usage": item["usage"], "reserved": {"tokens": item["reserved_tokens"],
                                      "costUsd": item["reserved_cost"]}} for item in (candidate, final)]}
            if self._candidate_repair_enabled():
                review_input = self._consistency_review_input(candidate, self._receipt(slot, "observation"))
                kind = "candidate" if candidate["status"] == "succeeded" else "candidate_error"
                receipt.update(reviewInputKind=kind, reviewInput=review_input, reviewInputHash=final["candidate_hash"])
                if kind == "candidate_error":
                    receipt["candidateHash"] = None
            return _json(receipt)

    def withheld_consistency_receipt(self, slot):
        """Private evidence of an unresolved revision; never used by world/API exporters.

        The withheld decision itself is committed with UNRESOLVED_MARKER; its assessment stays here.
        """
        with self._consistency_read():
            _, entries = self._verified_consistency(slot)
            live = _live(entries)
            if len(live) != 2 or live[1]["status"] != "failed" or live[1]["assessment"] is None:
                return None
            entry = live[1]  # Full mode, provenance and unresolved validation happened above.
            return _json({"schemaVersion": "world-withheld-consistency-receipt/v1", "state": "withheld",
                          "mode": self._review_mode, "slot": slot, "observationHash": entry["observation_hash"],
                          "candidateHash": entry["candidate_hash"], "withheldDecision": entry["decision"],
                          "assessment": entry["assessment"], "usage": entry["usage"], "receiptHash": entry["receipt_hash"]})

    def reserve_consistency_attempt(self, slot, stage, fence, reserved_tokens=0, reserved_cost="0"):
        require(stage in ("candidate", "revision"), "invalid_consistency_stage", "Unknown consistency stage")
        reserved = self._usage(reserved_tokens, reserved_cost)
        with self._transaction():
            self._fence(fence)
            self._require_consistency()
            row = self._slot(slot)
            require(row["observation"] is not None, "missing_observation", "Attempt requires its persisted observation")
            _, entries = self._verified_consistency(slot)
            live = _live(entries)
            review_input = self._consistency_review_input(live[0], json.loads(row["observation"])) if live else None
            require(row["decision"] is None, "decision_already_saved", "A completed decision cannot dispatch again")
            # A closed (abandoned or throttled) attempt is not a stage: that stage is dispatched again.
            require((stage == "candidate" and not live) or (
                    stage == "revision" and len(live) == 1 and review_input is not None),
                    "consistency_stage_exhausted", "Consistency stages cannot be skipped or replaced")
            exposure = self._budget()["exposure"]
            with localcontext() as context:
                context.prec = 64
                require(exposure["tokens"] + reserved["tokens"] <= self._spec["limits"]["maxTokens"]
                        and decimal(exposure["costUsd"]) + decimal(reserved["costUsd"]) <= decimal(self._spec["limits"]["maxCostUsd"]),
                        "run_budget_exhausted", "Run token or cost allowance exhausted")
            attempt_id = uuid4().hex
            entry = {"attempt_id": attempt_id, "slot": slot, "stage": stage, "observation_hash": digest(json.loads(row["observation"])),
                     "candidate_attempt_id": live[0]["attempt_id"] if stage == "revision" else None,
                     "candidate_hash": digest(review_input) if stage == "revision" else None,
                     "ordinal": len(entries) + 1, "reserved_tokens": reserved["tokens"], "reserved_cost": reserved["costUsd"],
                     "status": "unknown", "usage": None, "decision": None, "assessment": None, "error": None}
            self._db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,'unknown',NULL)",
                             (attempt_id, slot, entry["ordinal"], reserved["tokens"], reserved["costUsd"]))
            self._db.execute("INSERT INTO consistency_journal VALUES (?,?,?,?,?,?,NULL,NULL,NULL,?)",
                             (attempt_id, slot, stage, entry["observation_hash"], entry["candidate_attempt_id"],
                              entry["candidate_hash"], self._consistency_hash(entry)))
        return attempt_id

    def finish_consistency_attempt(self, attempt_id, *, status, usage, fence, decision=None, assessment=None, error=None,
                                   repair_eligible=False):
        require(type(repair_eligible) is bool, "invalid_candidate_repair", "Candidate repair eligibility must be explicit boolean metadata")
        require(status in ("succeeded", "failed", "unknown", "throttled"), "invalid_attempt_status", "Invalid attempt outcome")
        require(isinstance(usage, dict) and set(usage) == {"tokens", "costUsd"}, "invalid_usage", "Usage must contain tokens and costUsd")
        normalized = self._usage(usage["tokens"], usage["costUsd"])
        decision = _json(decision) if decision is not None else None
        assessment = _json(assessment) if assessment is not None else None
        error = self._consistency_error(error)
        # Refused before metering: no usage, payload or repair, and a refusal code.
        require(status != "throttled" or (normalized == _ZERO_USAGE and decision is None and assessment is None
                                          and not repair_eligible and error is not None
                                          and error["code"] in REFUSAL_CODES),
                "invalid_consistency_payload", "A throttled consistency attempt was refused before metering")
        with self._transaction():
            self._fence(fence)
            self._require_consistency()
            attempt = self._db.execute("SELECT slot FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            require(attempt is not None, "unknown_attempt", "Attempt reservation does not exist")
            _, entries = self._verified_consistency(attempt["slot"])
            entry = next((item for item in entries if item["attempt_id"] == attempt_id), None)
            require(entry is not None, "corrupt_consistency_journal", "Attempt has no consistency purpose")
            require(entry["status"] != "abandoned", "attempt_abandoned", "A superseded writer's attempt cannot be finished")
            if repair_eligible:
                require(error is not None, "invalid_candidate_repair", "Eligible candidate failure requires a safe diagnostic")
                error = self._consistency_error(error, repair_eligible=True)
                marked = {**entry, "status": status, "usage": normalized, "decision": decision, "assessment": assessment, "error": error}
                self._candidate_repair_context(marked, self._receipt(entry["slot"], "observation"))
            payload = {"status": status, "usage": normalized, "decision": decision, "assessment": assessment, "error": error}
            if entry["usage"] is not None:
                require(all(entry[key] == value for key, value in payload.items()),
                        "attempt_conflict", "Finished consistency receipt cannot change")
                return
            row = self._slot(attempt["slot"])
            require(normalized["tokens"] <= entry["reserved_tokens"]
                    and decimal(normalized["costUsd"]) <= decimal(entry["reserved_cost"]),
                    "reservation_exceeded", "Reported usage exceeds the reserved allowance")
            if status == "succeeded":
                require(error is None, "invalid_consistency_payload", "Successful consistency attempts cannot contain errors")
                observation = json.loads(row["observation"])
                self._validated_decision(decision, observation, row["actor"], row["phase"])
                if entry["stage"] == "candidate":
                    require(assessment is None, "invalid_consistency_payload", "Candidate cannot contain a final assessment")
                else:
                    from .review import assessment_status, validate_assessment

                    assessment = validate_assessment(assessment, observation, decision, mode=self._review_mode)
                    require(assessment_status(assessment, mode=self._review_mode) == "clear", "consistency_unresolved", "Consistency assessment remains unresolved")
                    payload["assessment"] = assessment
            else:
                if decision is not None or assessment is not None:
                    self._validated_withheld_consistency({**entry, **payload}, json.loads(row["observation"]))
            entry.update(payload)
            self._db.execute("UPDATE attempts SET status=?,usage=? WHERE attempt_id=?", (status, canonical_json(normalized), attempt_id))
            self._db.execute("UPDATE consistency_journal SET decision=?,assessment=?,error=?,receipt_hash=? WHERE attempt_id=?",
                             (canonical_json(decision) if decision is not None else None,
                              canonical_json(assessment) if assessment is not None else None,
                              canonical_json(error) if error is not None else None, self._consistency_hash(entry), attempt_id))
            if entry["stage"] == "revision":
                # Same transaction as the receipt: a cleared revision, or an unresolved one
                # with its withheld decision, becomes the slot's final decision at once.
                final = self._revision_decision(entry)
                if final is not None:
                    self._db.execute("UPDATE slots SET decision=? WHERE slot=?", (canonical_json(final), entry["slot"]))

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
            if self._review_mode is not None:
                self._verify_consistency_journal()
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
            from .kernel import event_load, resolve_round

            require(event_load(events) <= self._spec["limits"]["maxEventsPerRound"], "event_limit",
                    "Round event limit exceeded")
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
