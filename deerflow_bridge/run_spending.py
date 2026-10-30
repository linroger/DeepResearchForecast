"""One run's immutable, retained-maximum spending authority (stdlib only).

Transactions/atomic publication transfer the bounded WAL/FULL/BEGIN IMMEDIATE
patterns from world_simulation/store.py. Unlike that store, no reservation is
refunded. Tariff truth and exact wire-envelope validation belong to the reviewed
launcher and transport adapters; this module never imports a provider.
"""
from __future__ import annotations

import contextvars
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import threading
import types
from contextlib import contextmanager
from fractions import Fraction
from uuid import uuid4

CODES = frozenset({
    "invalid_manifest", "invalid_binding", "missing_context", "invalid_request",
    "unsupported_route", "billing_class_unverified", "source_drift",
    "storage_unavailable", "authorization_consumed", "binding_conflict",
    "attempt_reused", "stale_generation", "participant_unverified",
    "lock_unavailable", "resume_denied", "budget_exhausted", "unknown_outcome",
    "usage_integrity", "observation_conflict", "halted_cancelled", "halted_error", "closed",
    "budget_scope_missing", "budget_scope_conflict", "stale_admission_epoch",
    "stage_model_attempts_exhausted", "stage_tokens_exhausted", "stage_tool_attempts_exhausted",
    "stage_followup_attempts_exhausted", "catalog_lookup_conflict", "stage_profile_oversize",
    "stage_usage_unverifiable", "tool_operation_conflict",
    "transport_receipt_missing",
})


class SpendingStop(RuntimeError):
    """Only an allowlisted code can leave the private accounting boundary."""
    def __init__(self, code):
        self.code = code if isinstance(code, str) and code in CODES else "invalid_request"
        super().__init__(self.code)


# Sibling deployed imports and backend bridge_module share exception/context identity.
_self = sys.modules[__name__]
for _alias in ("run_spending", "deerflow_bridge.run_spending"):
    _other = sys.modules.get(_alias)
    if _other is not None and _other is not _self:
        if Path(getattr(_other, "__file__", "")).resolve() != Path(__file__).resolve():
            _other._REQUIRED = True
            if getattr(_other, "_ACTIVE_AUTH", None):
                _other._LOCAL_STOPS[_other._ACTIVE_AUTH[0]] = "source_drift"
            raise getattr(_other, "SpendingStop", SpendingStop)("source_drift")
        raise SpendingStop("invalid_binding")  # independently executed duplicate is unsupported
if "deerflow_bridge" not in sys.modules:
    _package = types.ModuleType("deerflow_bridge")
    _package.__path__ = [str(Path(__file__).resolve().parent)]
    sys.modules["deerflow_bridge"] = _package
for _alias in ("run_spending", "deerflow_bridge.run_spending"):
    sys.modules[_alias] = _self

_MAX = (1 << 63) - 1
_SCHEMA = "target-run-spending/v1"
_BINDING_SCHEMA = "target-run-spending-binding/v1"
_SCHEMA_V2 = "target-run-spending/v2"
_BINDING_V2 = "target-run-spending-binding/v2"
_REQUIRED = False
_ACTIVE_AUTH = None
_V2_CONTROL_BINDING = None
_ENV_PIN = None
_LOCAL_STOPS = {}
_binding = contextvars.ContextVar("run_spending_binding", default=None)
_operation = contextvars.ContextVar("run_spending_operation", default=None)
_dispatch_captures = contextvars.ContextVar("run_spending_captures", default=())
_latch_lock = threading.RLock()
_LOCK_FDS = set()
_FORKED_PROCESS = False
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,160}\Z")
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]{0,18})(?:\.[0-9]{1,18})?\Z")
_BINDING_KEYS = {"schema", "root", "manifest_path", "db_path", "registry_dir",
                 "authorization_id", "manifest_sha256", "source_sha256", "routes_sha256",
                 "pipeline_id", "generation", "participant_id"}
_REQUEST_KEYS = {"endpoint", "model", "input_tokens", "max_output_tokens", "tool_units", "payload_sha256"}
_ROUTE_KEYS = {"kind", "endpoint", "model", "account_sha256", "billing_class", "basis_sha256",
               "input_bound", "input_ceiling", "max_output_tokens", "max_tool_units", "pricing", "coverage"}
_PRICE_KEYS = {"input_usd_per_million", "output_usd_per_million", "tool_usd_per_unit", "fixed_usd", "surcharge_usd"}
_TERMINAL = {"halted_cancelled", "halted_unknown", "halted_exhausted", "halted_error", "closed"}


def _after_fork():
    """Forked workers are unsupported; never let them retain the parent's flock.

    Close inherited descriptions WITHOUT LOCK_UN (which would unlock the live
    parent's shared description). Spawn/exec children use a fresh module.
    """
    global _FORKED_PROCESS, _latch_lock
    _FORKED_PROCESS = True
    _latch_lock = threading.RLock()
    for fd in tuple(_LOCK_FDS):
        try:
            os.close(fd)
        except OSError:
            pass
    _LOCK_FDS.clear()


os.register_at_fork(after_in_child=_after_fork)


def _need(ok, code="invalid_request"):
    if not ok:
        raise SpendingStop(code)


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, OverflowError):
        raise SpendingStop("invalid_request") from None


def hash_payload(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _copy(value):
    return json.loads(_json(value))


def _hash(value, code="invalid_manifest"):
    _need(isinstance(value, str) and _HEX.fullmatch(value), code)
    return value


def _count(value, code="invalid_request", *, positive=False):
    _need(type(value) is int and int(positive) <= value <= _MAX, code)
    return value


def _decimal(value, code="invalid_manifest"):
    _need(isinstance(value, str) and _DECIMAL.fullmatch(value), code)
    number = Fraction(value)
    _need(number <= _MAX, code)
    return number


def _cap(value):
    amount = _decimal(value) * 1_000_000
    _need(amount.denominator == 1 and 0 < amount <= _MAX, "invalid_manifest")
    return int(amount)


def _identity(value, code="invalid_binding"):
    _need(isinstance(value, str) and _ID.fullmatch(value), code)
    return value


def _endpoint(value):
    from urllib.parse import urlsplit
    _need(isinstance(value, str) and len(value) <= 2048, "unsupported_route")
    try:
        parsed = urlsplit(value)
        _need(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
              and not parsed.query and not parsed.fragment, "unsupported_route")
        _ = parsed.port
    except ValueError:
        raise SpendingStop("unsupported_route") from None
    _need(not parsed.path.endswith("//"), "unsupported_route")
    return value[:-1] if value.endswith("/") else value


def validate_manifest(manifest):
    if isinstance(manifest, dict) and manifest.get("schema") == _SCHEMA_V2:
        return _validate_v2_manifest(manifest)
    return _validate_v1_manifest(manifest)


def _validate_v1_manifest(manifest):
    m = _copy(manifest)
    _need(type(m) is dict and set(m) == {"schema", "authorization_id", "root", "currency", "cap_usd",
          "request_sha256", "source_files", "source_sha256", "routes_sha256", "resume_policy", "routes"}, "invalid_manifest")
    _need(m["schema"] == _SCHEMA and m["currency"] == "USD" and m["resume_policy"] == "explicit_clean_only", "invalid_manifest")
    _identity(m["authorization_id"], "invalid_manifest")
    _cap(m["cap_usd"])
    _need(isinstance(m["root"], str) and Path(m["root"]).is_absolute(), "invalid_manifest")
    for field in ("request_sha256", "source_sha256", "routes_sha256"):
        _hash(m[field])
    files = m["source_files"]
    _need(type(files) is dict and 0 < len(files) <= 10000, "invalid_manifest")
    for name, value in files.items():
        _need(isinstance(name, str) and name and not Path(name).is_absolute()
              and all(part not in {"..", "."} for part in name.split("/"))
              and not name.startswith("spend/"), "invalid_manifest")
        _hash(value)
    _need(hash_payload(files) == m["source_sha256"], "source_drift")
    routes = m["routes"]
    _need(type(routes) is dict and 0 < len(routes) <= 3, "invalid_manifest")
    kinds = set()
    for route_id, route in routes.items():
        _identity(route_id, "invalid_manifest")
        _need(type(route) is dict and set(route) == _ROUTE_KEYS, "invalid_manifest")
        kind = route["kind"]
        _need(isinstance(kind, str) and kind in {"openai_chat", "firecrawl_search", "firecrawl_scrape"}
              and kind not in kinds, "unsupported_route")
        kinds.add(kind)
        _endpoint(route["endpoint"])
        _hash(route["account_sha256"])
        _hash(route["basis_sha256"])
        _need(route["coverage"] == "all_billable_dimensions", "billing_class_unverified")
        _need(type(route["pricing"]) is dict and set(route["pricing"]) == _PRICE_KEYS, "invalid_manifest")
        prices = {key: _decimal(value) for key, value in route["pricing"].items()}
        for field in ("input_ceiling", "max_output_tokens", "max_tool_units"):
            _count(route[field], "invalid_manifest")
        if kind == "openai_chat":
            _need(route["billing_class"] == "external_model", "billing_class_unverified")
            _need(isinstance(route["model"], str) and 0 < len(route["model"]) <= 160
                  and route["input_bound"] == "enforced_context_ceiling"
                  and route["input_ceiling"] > 0 and route["max_output_tokens"] > 0
                  and route["max_tool_units"] == 0 and prices["tool_usd_per_unit"] == 0, "invalid_manifest")
            _need(prices["input_usd_per_million"] > 0 and prices["output_usd_per_million"] > 0, "billing_class_unverified")
        else:
            _need(route["billing_class"] == "external_tool", "billing_class_unverified")
            _need(route["model"] == "" and route["input_bound"] == "not_applicable"
                  and route["input_ceiling"] == route["max_output_tokens"] == 0
                  and route["max_tool_units"] > 0 and prices["input_usd_per_million"] == prices["output_usd_per_million"] == 0,
                  "invalid_manifest")
            _need(prices["tool_usd_per_unit"] > 0, "billing_class_unverified")
    _need(hash_payload(routes) == m["routes_sha256"], "source_drift")
    return m


def _path(value, *, directory=False, optional=False):
    _need(isinstance(value, (str, Path)), "invalid_binding")
    p = Path(value)
    _need(p.is_absolute() and str(p) == os.path.abspath(p), "invalid_binding")
    try:
        s = p.lstat()
        if optional and s.st_nlink == 0:
            # SQLite may unlink a last-connection sidecar during stat. Recheck
            # that optional name once; absence is valid, a replacement must
            # still pass every regular-file/owner/no-symlink check below.
            s = p.lstat()
        _need(not stat.S_ISLNK(s.st_mode) and p.resolve() == p, "invalid_binding")
        _need(stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode), "storage_unavailable")
        _need(s.st_uid == os.getuid(), "invalid_binding")
        _need(not s.st_mode & 0o022, "invalid_binding")
        if not directory:
            _need(s.st_nlink == 1, "invalid_binding")
    except FileNotFoundError:
        if optional:
            return None
        raise SpendingStop("storage_unavailable") from None
    except SpendingStop:
        raise
    except (OSError, RuntimeError, ValueError):
        raise SpendingStop("storage_unavailable") from None
    return p


def _read_json(path):
    p = _path(path)
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            raw = handle.read(4_000_001)
        _need(len(raw) <= 4_000_000, "invalid_manifest")
        def unique(pairs):
            d = {}
            for k, v in pairs:
                _need(k not in d, "invalid_manifest")
                d[k] = v
            return d
        return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(SpendingStop("invalid_manifest")))
    except (OSError, ValueError, UnicodeError):
        raise SpendingStop("invalid_manifest") from None


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _publish_json(path, value):
    """An interrupted O_EXCL publication consumes authority; never replace it."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_json(value))
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_dir(path.parent)
    except FileExistsError:
        raise SpendingStop("authorization_consumed") from None
    except OSError:
        raise SpendingStop("storage_unavailable") from None


def _registry_path(binding, suffix):
    return Path(binding["registry_dir"]) / (hash_payload(binding["authorization_id"]) + suffix)


def _verify_sources(m):
    root = _path(m["root"], directory=True)
    for name, expected in m["source_files"].items():
        p = _path(root / name)
        try:
            with p.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            _need(digest == expected, "source_drift")
        except OSError:
            raise SpendingStop("source_drift") from None


def _validate_binding(binding):
    b = _copy(binding)
    v2 = _is_v2(b)
    keys = _BINDING_KEYS | {"admission_epoch", "active_scope_id"} if v2 else _BINDING_KEYS
    _need(type(b) is dict and set(b) == keys and b["schema"] == (_BINDING_V2 if v2 else _BINDING_SCHEMA), "invalid_binding")
    if v2:
        _count(b["admission_epoch"], "invalid_binding")
        if b["active_scope_id"] is not None:
            _identity(b["active_scope_id"])
    _identity(b["authorization_id"])
    _identity(b["participant_id"])
    _need(b["pipeline_id"] == "" or _ID.fullmatch(b["pipeline_id"]), "invalid_binding")
    _count(b["generation"], "invalid_binding", positive=True)
    root = _path(b["root"], directory=True)
    _path(root / "spend", directory=True)
    registry = _path(b["registry_dir"], directory=True)
    _need(not registry.is_relative_to(root) and not root.is_relative_to(registry), "invalid_binding")
    _need(b["manifest_path"] == str(root / "spend/authorization.json")
          and b["db_path"] == str(root / "spend/run.sqlite3"), "invalid_binding")
    m = validate_manifest(_read_json(b["manifest_path"]))
    _need(v2 == (m["schema"] == _SCHEMA_V2), "invalid_binding")
    _need(m["root"] == str(root) and m["authorization_id"] == b["authorization_id"]
          and hash_payload(m) == b["manifest_sha256"]
          and m["source_sha256"] == b["source_sha256"] and m["routes_sha256"] == b["routes_sha256"], "source_drift")
    _verify_sources(m)
    consumed = _read_json(_registry_path(b, ".json"))
    _need(type(consumed) is dict and set(consumed) == {"root", "root_inode", "manifest_sha256", "nonce"}, "invalid_binding")
    rootstat = root.stat()
    _need(consumed["root"] == b["root"] and consumed["manifest_sha256"] == b["manifest_sha256"]
          and consumed["root_inode"] == [rootstat.st_dev, rootstat.st_ino], "invalid_binding")
    dbpath = _path(b["db_path"])
    for suffix in ("-wal", "-shm", "-journal"):
        # Last-connection close may remove a sidecar concurrently. Absence is
        # legal; any observed symlink/nonregular/unsafe existing file is not.
        _path(str(dbpath) + suffix, optional=True)
    identity = _read_json(_registry_path(b, ".ledger.json"))
    s = dbpath.stat()
    _need(identity == {"nonce": consumed["nonce"], "inode": [s.st_dev, s.st_ino]}, "invalid_binding")
    return b, m, consumed


_DDL = """
CREATE TABLE run_authorization (
 id INTEGER PRIMARY KEY CHECK(id=1), manifest_sha256 TEXT NOT NULL, nonce TEXT NOT NULL,
 cap INTEGER NOT NULL CHECK(cap>0), pipeline_id TEXT NOT NULL DEFAULT '',
 generation INTEGER NOT NULL DEFAULT 1, state TEXT NOT NULL DEFAULT 'prepared',
 stop_code TEXT, owner_pid INTEGER,
 created_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE attempts (
 attempt_id TEXT PRIMARY KEY, logical_hash TEXT NOT NULL, ordinal INTEGER NOT NULL,
 generation INTEGER NOT NULL, participant_id TEXT NOT NULL, stage_hash TEXT NOT NULL,
 route_id TEXT NOT NULL, request_sha256 TEXT NOT NULL, envelope TEXT NOT NULL,
 reserved INTEGER NOT NULL CHECK(reserved>0), state TEXT NOT NULL DEFAULT 'unknown',
 observation TEXT, observation_sha256 TEXT,
 created_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), observed_utc TEXT,
 UNIQUE(logical_hash,ordinal)
);
CREATE TABLE events (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, code TEXT, evidence_sha256 TEXT,
 created_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
CREATE TABLE participants (
 generation INTEGER NOT NULL, participant_id TEXT NOT NULL, pid INTEGER,
 state TEXT NOT NULL, spawn_sha256 TEXT NOT NULL, operation_sha256 TEXT,
 exit_sha256 TEXT, PRIMARY KEY(generation,participant_id)
);
CREATE TRIGGER retained_attempt_delete BEFORE DELETE ON attempts BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER retained_attempt_update BEFORE UPDATE OF attempt_id,logical_hash,ordinal,generation,
 participant_id,stage_hash,route_id,request_sha256,envelope,reserved,created_utc ON attempts BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER immutable_authority BEFORE UPDATE OF manifest_sha256,nonce,cap,created_utc ON run_authorization BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER no_authority_delete BEFORE DELETE ON run_authorization BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER no_event_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER no_event_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'immutable'); END;
"""


def create_authorization(manifest_path, *, registry_dir):
    m = validate_manifest(_read_json(manifest_path))
    root = _path(m["root"], directory=True)
    _need(str(manifest_path) == str(root / "spend/authorization.json"), "invalid_binding")
    _path(root / "spend", directory=True)
    registry = _path(registry_dir, directory=True)
    _need(not registry.is_relative_to(root) and not root.is_relative_to(registry), "invalid_binding")
    _verify_sources(m)
    b = dict(schema=_BINDING_SCHEMA, root=str(root), manifest_path=str(manifest_path),
             db_path=str(root / "spend/run.sqlite3"), registry_dir=str(registry),
             authorization_id=m["authorization_id"], manifest_sha256=hash_payload(m),
             source_sha256=m["source_sha256"], routes_sha256=m["routes_sha256"],
             pipeline_id="", generation=1, participant_id="parent")
    if m["schema"] == _SCHEMA_V2:
        b.update(schema=_BINDING_V2, admission_epoch=0, active_scope_id=None)
    _need(not os.path.lexists(b["db_path"]), "authorization_consumed")
    nonce = uuid4().hex
    s = root.stat()
    _publish_json(_registry_path(b, ".json"), {"root": str(root), "root_inode": [s.st_dev, s.st_ino],
                  "manifest_sha256": b["manifest_sha256"], "nonce": nonce})
    _publish_json(root / "spend/run.lock", {"nonce": nonce})
    temp = root / "spend" / (".initial-" + nonce + ".sqlite3")
    db = None
    try:
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        db = sqlite3.connect(str(temp), isolation_level=None)
        db.execute("PRAGMA synchronous=FULL")
        db.executescript(_DDL)
        if _is_v2(b):
            db.executescript(_DDL_V2)
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO run_authorization(id,manifest_sha256,nonce,cap) VALUES(1,?,?,?)",
                   (b["manifest_sha256"], nonce, _cap(m["cap_usd"])))
        db.execute("INSERT INTO participants(generation,participant_id,pid,state,spawn_sha256,operation_sha256,exit_sha256) VALUES(1,'parent',NULL,'registered',?,NULL,NULL)", (hash_payload({"nonce": nonce}),))
        if _is_v2(b):
            budget = m["anchor_budget"]
            db.execute("INSERT INTO budget_scopes(scope_id,policy_sha256,policy) VALUES(?,?,?)",
                       (budget["scope_id"], hash_payload(budget), _json(budget)))
        db.execute("PRAGMA user_version=" + ("2" if _is_v2(b) else "1"))
        db.execute("COMMIT")
        db.close()
        db = None
        with temp.open("rb") as handle:
            os.fsync(handle.fileno())
        os.link(temp, b["db_path"])
        temp.unlink()
        _fsync_dir(temp.parent)
        s = Path(b["db_path"]).stat()
        _publish_json(_registry_path(b, ".ledger.json"), {"nonce": nonce, "inode": [s.st_dev, s.st_ino]})
        return open_existing(b)
    except SpendingStop:
        raise
    except (OSError, sqlite3.Error):
        raise SpendingStop("storage_unavailable") from None
    finally:
        if db is not None:
            db.close()
        if temp.exists():
            temp.unlink()


def _stop(db, code):
    code = code if code in CODES else "halted_error"
    state = {"unknown_outcome": "halted_unknown", "budget_exhausted": "halted_exhausted",
             "halted_cancelled": "halted_cancelled", "closed": "closed"}.get(code, "halted_error")
    if code in {"stage_model_attempts_exhausted", "stage_tokens_exhausted", "stage_tool_attempts_exhausted", "stage_followup_attempts_exhausted"}:
        state = "halted_exhausted"
    if code == "stage_usage_unverifiable":
        state = "halted_unknown"
    db.execute("UPDATE run_authorization SET state=?,stop_code=? WHERE id=1 AND state NOT IN ('halted_unknown','halted_exhausted','halted_cancelled','halted_error','closed')", (state, code))
    db.execute("INSERT INTO events(kind,code) VALUES('stop',?)", (code,))


def _state_code(row):
    return row["stop_code"] or ("closed" if row["state"] == "closed" else "halted_error")


def _lock_held(b):
    p = _path(Path(b["root"]) / "spend/run.lock")
    fd = os.open(p, os.O_RDWR | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def _persist_validation_stop(binding, code):
    """Halt an already activated authority without trusting drifted source.

    Only the independent immutable registry/root/ledger identity is consulted.
    This function cannot admit or change money and does not recreate storage.
    """
    if not isinstance(binding, dict) or _ACTIVE_AUTH is None:
        return
    if (binding.get("authorization_id"), binding.get("manifest_sha256"), binding.get("root")) != _ACTIVE_AUTH:
        return
    _LOCAL_STOPS[_ACTIVE_AUTH[0]] = code
    db = None
    try:
        root = _path(binding["root"], directory=True)
        _need(binding["db_path"] == str(root / "spend/run.sqlite3"), "invalid_binding")
        consumed = _read_json(_registry_path(binding, ".json"))
        s = root.stat()
        _need(consumed["root"] == str(root) and consumed["root_inode"] == [s.st_dev, s.st_ino]
              and consumed["manifest_sha256"] == binding["manifest_sha256"], "invalid_binding")
        p = _path(binding["db_path"])
        s = p.stat()
        _need(_read_json(_registry_path(binding, ".ledger.json")) == {"nonce": consumed["nonce"], "inode": [s.st_dev, s.st_ino]}, "invalid_binding")
        for suffix in ("-wal", "-shm", "-journal"):
            _path(str(p) + suffix, optional=True)
        db = sqlite3.connect(p.as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=0.25)
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT nonce,manifest_sha256,generation FROM run_authorization WHERE id=1").fetchone()
        _need(row == (consumed["nonce"], binding["manifest_sha256"], binding["generation"]), "invalid_binding")
        _stop(db, code)
        db.execute("COMMIT")
    except (SpendingStop, OSError, sqlite3.Error, KeyError, TypeError, ValueError):
        if db is not None and db.in_transaction:
            db.execute("ROLLBACK")
    finally:
        if db is not None:
            db.close()


@contextmanager
def _tx(binding, *, active=False, fence=True, preparing_operation=False, scope_control=False):
    db = None
    b = None
    try:
        _need(not _FORKED_PROCESS, "invalid_binding")
        if active:
            _check_env_pin()
        b, m, consumed = _validate_binding(binding)
        db = sqlite3.connect(Path(b["db_path"]).as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=0.25)
        db.row_factory = sqlite3.Row
        _need(db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal", "storage_unavailable")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=250")
        db.execute("BEGIN IMMEDIATE")
        _need(db.execute("PRAGMA user_version").fetchone()[0] == (2 if _is_v2(b) else 1), "storage_unavailable")
        row = db.execute("SELECT * FROM run_authorization WHERE id=1").fetchone()
        _need(row is not None and row["manifest_sha256"] == b["manifest_sha256"]
              and row["nonce"] == consumed["nonce"] and row["cap"] == _cap(m["cap_usd"]), "invalid_binding")
        if _is_v2(b):
            scope = db.execute("SELECT policy_sha256,policy FROM budget_scopes WHERE scope_id=?", (m["anchor_budget"]["scope_id"],)).fetchone()
            _need(scope is not None and scope["policy_sha256"] == hash_payload(m["anchor_budget"])
                  and scope["policy"] == _json(m["anchor_budget"]), "invalid_binding")
        if fence:
            _need(row["generation"] == b["generation"], "stale_generation")
        if active and _is_v2(b):
            # Fence old phase workers before an exited participant or changed
            # phase state can turn their late call into a halt of the new owner.
            _need(b["admission_epoch"] == row["admission_epoch"], "stale_admission_epoch")
        _need(not b["pipeline_id"] or b["pipeline_id"] == row["pipeline_id"], "binding_conflict")
        if row["pipeline_id"]:
            _need(_read_json(_registry_path(b, ".pipeline.json")) == {"pipeline_id": row["pipeline_id"], "request_sha256": m["request_sha256"]}, "binding_conflict")
        if active:
            _need(b["authorization_id"] not in _LOCAL_STOPS, _LOCAL_STOPS.get(b["authorization_id"], "halted_error"))
            preparing = (preparing_operation and row["state"] == "prepared" and b["participant_id"] == "parent"
                         and b["pipeline_id"] == row["pipeline_id"] == "" and row["owner_pid"] == os.getpid())
            _need(row["state"] == "active" or preparing, _state_code(row))
            _need((b["pipeline_id"] == row["pipeline_id"] and bool(row["pipeline_id"])) or preparing, "missing_context")
            _need(row["owner_pid"] is not None and _lock_held(b), "lock_unavailable")
            p = db.execute("SELECT * FROM participants WHERE generation=? AND participant_id=?", (b["generation"], b["participant_id"])).fetchone()
            _need(p is not None and p["state"] == "running" and p["pid"] == os.getpid(), "participant_unverified")
            if _is_v2(b):
                _v2_admission(db, b, row, p, scope_control=scope_control)
        yield db, row, m
        db.execute("COMMIT")
    except SpendingStop as exc:
        if db is not None and db.in_transaction:
            # A stale worker or repeated claim must never poison a new owner.
            if exc.code not in {"stale_generation", "stale_admission_epoch", "attempt_reused", "resume_denied", "lock_unavailable"}:
                try:
                    _stop(db, exc.code)
                    db.execute("COMMIT")
                except sqlite3.Error:
                    db.execute("ROLLBACK")
            else:
                db.execute("ROLLBACK")
        elif exc.code not in {"stale_generation", "stale_admission_epoch", "attempt_reused", "resume_denied", "lock_unavailable"}:
            _persist_validation_stop(binding, exc.code)
        raise
    except (sqlite3.Error, OSError, KeyError, TypeError, ValueError):
        if db is not None and db.in_transaction:
            db.execute("ROLLBACK")
        _persist_validation_stop(binding, "storage_unavailable")
        raise SpendingStop("storage_unavailable") from None
    finally:
        if db is not None:
            db.close()


def open_existing(binding):
    with _tx(binding) as (_, row, _):
        result = _copy(binding)
        result["pipeline_id"] = row["pipeline_id"]
        return result


@contextmanager
def run_lock(binding):
    b = open_existing(binding)
    _need(b["participant_id"] == "parent", "participant_unverified")
    p = _path(Path(b["root"]) / "spend/run.lock")
    try:
        fd = os.open(p, os.O_RDWR | os.O_NOFOLLOW)
    except OSError:
        raise SpendingStop("lock_unavailable") from None
    _LOCK_FDS.add(fd)
    acquired = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SpendingStop("lock_unavailable") from None
        except OSError:
            raise SpendingStop("lock_unavailable") from None
        acquired = True
        with _tx(b) as (db, row, _):
            if db.execute("SELECT count(*) FROM attempts WHERE state='unknown'").fetchone()[0]:
                _stop(db, "unknown_outcome")
            if row["owner_pid"] is not None and row["state"] == "active":
                db.execute("UPDATE run_authorization SET state='paused_recoverable' WHERE id=1 AND state='active'")
            db.execute("UPDATE run_authorization SET owner_pid=? WHERE id=1", (os.getpid(),))
            db.execute("UPDATE participants SET pid=?,state='running' WHERE generation=? AND participant_id='parent'", (os.getpid(), b["generation"]))
        yield b
    finally:
        if acquired and fd in _LOCK_FDS:
            try:
                with _tx(b, fence=False) as (db, row, _):
                    if row["owner_pid"] == os.getpid():
                        if row["state"] == "active":
                            if db.execute("SELECT count(*) FROM attempts WHERE state='unknown'").fetchone()[0]:
                                _stop(db, "unknown_outcome")
                            else:
                                db.execute("UPDATE run_authorization SET state='paused_recoverable' WHERE id=1")
                        db.execute("UPDATE run_authorization SET owner_pid=NULL WHERE id=1")
            except SpendingStop:
                pass  # Missing/corrupt storage remains fail-closed on every open.
            fcntl.flock(fd, fcntl.LOCK_UN)
        if fd in _LOCK_FDS:
            _LOCK_FDS.discard(fd)
            os.close(fd)


def bind_pipeline(binding, pipeline_id, request):
    _identity(pipeline_id)
    with _tx(binding) as (db, row, m):
        _need(binding["participant_id"] == "parent" and _lock_held(binding)
              and row["owner_pid"] == os.getpid(), "lock_unavailable")
        _need(hash_payload(request) == m["request_sha256"], "binding_conflict")
        if _is_v2(binding):
            _validate_anchor_request(m, request)
        _need(row["pipeline_id"] in {"", pipeline_id}, "binding_conflict")
        _need(row["state"] in {"prepared", "active"}, _state_code(row))
        value = {"pipeline_id": pipeline_id, "request_sha256": m["request_sha256"]}
        path = _registry_path(binding, ".pipeline.json")
        if path.exists():
            _need(_read_json(path) == value, "binding_conflict")
        else:
            _publish_json(path, value)  # durable binding first, ledger second
        db.execute("UPDATE run_authorization SET pipeline_id=?,state='active' WHERE id=1", (pipeline_id,))
        result = _copy(binding)
        result["pipeline_id"] = pipeline_id
    _adopt_transition(binding, result)
    return result


def validate_bound_request(binding, request):
    """Validate actual normalized request against immutable approval, without
    rebinding or authorizing dispatch/resume. Paused runs can be checked before
    generation advance; mutable pipeline-state copies are never authority.
    """
    with _tx(binding) as (_, row, manifest):
        _need(bool(row["pipeline_id"]) and binding["pipeline_id"] == row["pipeline_id"], "binding_conflict")
        _need(type(request) is dict, "binding_conflict")
        try:
            request_sha256 = hash_payload(request)
        except (SpendingStop, UnicodeError, RecursionError):
            raise SpendingStop("binding_conflict") from None
        _need(request_sha256 == manifest["request_sha256"], "binding_conflict")
        if _is_v2(binding):
            _validate_anchor_request(manifest, request)
        return request_sha256


def required():
    global _REQUIRED
    with _latch_lock:
        if any(key in os.environ for key in ("DRF_RUN_SPENDING_REQUIRED", "DRF_RUN_SPENDING_BINDING",
                                             "DRF_RUN_SPENDING_MODULE_SHA256", "DRF_RUN_SPENDING_OPERATION")):
            _REQUIRED = True
        return _REQUIRED


def _operation_value(value):
    _need(type(value) is dict and set(value) == {"stage", "logical_key"}, "missing_context")
    for key in value:
        _need(isinstance(value[key], str) and 0 < len(value[key]) <= 1024 and not any(ord(c) < 32 for c in value[key]), "missing_context")
    return _copy(value)


def _environment_operation(b):
    raw = os.environ.get("DRF_RUN_SPENDING_OPERATION")
    if raw is None:
        _need(b["participant_id"] == "parent", "missing_context")
        return
    try:
        value = _operation_value(json.loads(raw))
    except (TypeError, ValueError):
        raise SpendingStop("missing_context") from None
    if b["participant_id"] != "parent":
        with _tx(b) as (db, _, _):
            row = db.execute("SELECT operation_sha256 FROM participants WHERE generation=? AND participant_id=?", (b["generation"], b["participant_id"])).fetchone()
            _need(row is not None and row[0] == hash_payload(value), "participant_unverified")
    _operation.set(value)


def _env_contract():
    return {key: os.environ.get(key) for key in ("DRF_RUN_SPENDING_REQUIRED", "DRF_RUN_SPENDING_BINDING",
                                                "DRF_RUN_SPENDING_MODULE_SHA256", "DRF_RUN_SPENDING_OPERATION")}


def _check_env_pin():
    with _latch_lock:
        if _ENV_PIN is None:
            return
        actual = _env_contract()
        if not _ENV_PIN.get("denied") and actual == _ENV_PIN["current"]:
            return
        _ENV_PIN["denied"] = True
        deny("missing_context")


def _adopt_transition(previous, committed):
    """Only bind/resume can advance a pinned parent carrier after DB commit.

    No caller-supplied reset or generic adoption API exists. A crash between
    commit and adoption fails closed; it never recreates or replenishes a run.
    """
    if _is_v2(previous):
        return _adopt_v2(previous, committed)
    with _latch_lock:
        if _ENV_PIN is None:
            return
        _check_env_pin()
        carrier = _ENV_PIN["current"]
        old = json.loads(carrier["DRF_RUN_SPENDING_BINDING"])
        _need(previous["participant_id"] == committed["participant_id"] == old["participant_id"] == "parent", "invalid_binding")
        fixed = _BINDING_KEYS - {"pipeline_id", "generation"}
        _need(all(old[key] == previous[key] == committed[key] for key in fixed), "invalid_binding")
        _need(old["generation"] == previous["generation"] and old["pipeline_id"] in {"", previous["pipeline_id"]}, "stale_generation")
        _need((committed["generation"] == previous["generation"] and previous["pipeline_id"] in {"", committed["pipeline_id"]})
              or (committed["generation"] == previous["generation"] + 1 and previous["pipeline_id"] == committed["pipeline_id"]), "invalid_binding")
        with _tx(committed) as (_, row, _):
            _need(row["pipeline_id"] == committed["pipeline_id"] and row["generation"] == committed["generation"], "invalid_binding")
        upgraded = dict(carrier)
        upgraded["DRF_RUN_SPENDING_BINDING"] = _json(committed)
        os.environ["DRF_RUN_SPENDING_BINDING"] = upgraded["DRF_RUN_SPENDING_BINDING"]
        _ENV_PIN["current"] = upgraded
        if _binding.get() is not None:
            _binding.set(_copy(committed))


def binding_from_environment():
    global _ENV_PIN
    if not required():
        return None
    _check_env_pin()
    _need(os.environ.get("DRF_RUN_SPENDING_REQUIRED") == "1", "missing_context")
    try:
        b = json.loads(os.environ["DRF_RUN_SPENDING_BINDING"])
        digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        _need(os.environ.get("DRF_RUN_SPENDING_MODULE_SHA256") == digest, "source_drift")
    except (KeyError, ValueError, OSError):
        raise SpendingStop("invalid_binding") from None
    b = open_existing(b)
    _environment_operation(b)
    if _ENV_PIN is None:
        _ENV_PIN = {"current": _env_contract(), "denied": False}
    return b


def activate_binding(binding):
    global _REQUIRED, _ACTIVE_AUTH
    with _latch_lock:
        _REQUIRED = True
        _check_env_pin()
        b = open_existing(binding)
        identity = (b["authorization_id"], b["manifest_sha256"], b["root"])
        _need(_ACTIVE_AUTH in {None, identity}, "binding_conflict")
        _ACTIVE_AUTH = identity
        if b["participant_id"] != "parent":
            participant_started(b)
        if "DRF_RUN_SPENDING_BINDING" in os.environ:
            env_binding = binding_from_environment()
            _need(env_binding == b, "invalid_binding")
        _binding.set(_copy(b))
        _remember_v2_binding(b)
        return b


def current_binding():
    if not required():
        return None
    _check_env_pin()
    b = _binding.get()
    if b is None and _ACTIVE_AUTH is not None:
        _LOCAL_STOPS[_ACTIVE_AUTH[0]] = "missing_context"
        remembered = _remembered_v2_binding()
        if remembered is not None:
            _persist_validation_stop(remembered, "missing_context")
    _need(b is not None, "missing_context")
    return _copy(b)


def check_active(binding=None, *, require_operation=False):
    b = binding if binding is not None else current_binding()
    if b is None:
        return None
    with _tx(b, active=True):
        if require_operation:
            _operation_value(_operation.get())
    return _copy(b)


def check_context():
    return check_active(require_operation=True)


def deny(code):
    stop = SpendingStop(code)
    b = _binding.get()
    if b is None:
        b = _remembered_v2_binding()
    if b is not None:
        try:
            halt(b, stop.code)
        except SpendingStop:
            pass
        _LOCAL_STOPS[b["authorization_id"]] = stop.code
    raise stop from None


def is_spending_stop(exc):
    return isinstance(exc, SpendingStop)


@contextmanager
def operation(stage, logical_key):
    value = _operation_value({"stage": stage, "logical_key": logical_key})
    if required():
        # The lock-owning parent may scope its first bind with operation
        # metadata. All qualification/claim/send paths still demand active,
        # committed pipeline identity through the default transaction checks.
        with _tx(current_binding(), active=True, preparing_operation=True, scope_control=True):
            pass
    parent = _operation.get()
    if parent is not None:
        value["logical_key"] = hash_payload({"parent": _operation_value(parent), "child": value})
    token = _operation.set(value)
    try:
        yield
    finally:
        _operation.reset(token)


def current_operation():
    if check_context() is None:
        return _copy(_operation.get())
    return _operation_value(_operation.get())


def get_route(route_id, binding=None):
    b = binding if binding is not None else current_binding()
    _need(b is not None, "missing_context")
    with _tx(b) as (_, _, m):
        _need(route_id in m["routes"], "unsupported_route")
        return _copy(m["routes"][route_id])


def qualify_route(kind, endpoint, model="", *, account_sha256=None):
    b = check_context()
    if b is None:
        return None
    with _tx(b, active=True) as (_, _, m):
        _hash(account_sha256, "billing_class_unverified")
        matches = [key for key, r in m["routes"].items() if r["kind"] == kind
                   and _endpoint(r["endpoint"]) == _endpoint(endpoint) and r["model"] == model
                   and account_sha256 == r["account_sha256"]]
        _need(len(matches) == 1, "unsupported_route")
        if _is_v2(b) and b["active_scope_id"] is not None:
            p = m["anchor_budget"]
            _need(matches[0] in [p["model_profile"]["route_id"], *p["catalog_route_ids"], *p["followup_route_ids"]], "unsupported_route")
        return matches[0]


def _quote(m, route_id, request):
    _need(route_id in m["routes"], "unsupported_route")
    r = m["routes"][route_id]
    _need(type(request) is dict and set(request) == _REQUEST_KEYS, "invalid_request")
    _need(_endpoint(request["endpoint"]) == _endpoint(r["endpoint"]) and request["model"] == r["model"], "unsupported_route")
    _hash(request["payload_sha256"], "invalid_request")
    inp = _count(request["input_tokens"])
    out = _count(request["max_output_tokens"])
    units = _count(request["tool_units"])
    if r["kind"] == "openai_chat":
        _need(inp == r["input_ceiling"] and 0 < out <= r["max_output_tokens"] and units == 0, "invalid_request")
    else:
        _need(inp == out == 0 and units == r["max_tool_units"], "invalid_request")
    p = {key: _decimal(value) for key, value in r["pricing"].items()}
    amount = inp*p["input_usd_per_million"] + out*p["output_usd_per_million"]
    amount += 1_000_000*(units*p["tool_usd_per_unit"] + p["fixed_usd"] + p["surcharge_usd"])
    maximum = (amount.numerator + amount.denominator - 1) // amount.denominator
    _count(maximum, "invalid_request", positive=True)
    return {"reserved_max_microusd": maximum, "input_tokens": inp, "max_output_tokens": out, "tool_units": units}


def quote_request(route_id, request, binding=None):
    b = binding if binding is not None else current_binding()
    _need(b is not None, "missing_context")
    with _tx(b) as (_, _, m):
        return _quote(m, route_id, request)


def reserve_and_claim(binding, route_id, request, *, stage, logical_key, attempt_id=None,
                      catalog_lookup_id=None, followup_operation_id=None):
    op = _operation_value({"stage": stage, "logical_key": logical_key})
    attempt_id = uuid4().hex if attempt_id is None else _identity(attempt_id, "invalid_request")
    with _tx(binding, active=True) as (db, row, m):
        _need(db.execute("SELECT 1 FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone() is None, "attempt_reused")
        quote = _quote(m, route_id, request)
        retained = sum(item[0] for item in db.execute("SELECT reserved FROM attempts"))
        _need(retained <= row["cap"], "usage_integrity")
        _need(quote["reserved_max_microusd"] <= row["cap"] - retained, "budget_exhausted")
        extra = (_v2_debits(db, binding, row, m, route_id, request, quote,
                           catalog_lookup_id, followup_operation_id) if _is_v2(binding) else {})
        if not _is_v2(binding):
            _need(catalog_lookup_id is None and followup_operation_id is None, "unsupported_route")
        logical = hash_payload(op)
        ordinal = db.execute("SELECT COALESCE(MAX(ordinal),0)+1 FROM attempts WHERE logical_hash=?", (logical,)).fetchone()[0]
        fields = ["attempt_id", "logical_hash", "ordinal", "generation", "participant_id", "stage_hash", "route_id", "request_sha256", "envelope", "reserved", *extra]
        values = [attempt_id, logical, ordinal, binding["generation"], binding["participant_id"], hash_payload(stage), route_id,
                  request["payload_sha256"], _json(request), quote["reserved_max_microusd"], *extra.values()]
        db.execute("INSERT INTO attempts(" + ",".join(fields) + ") VALUES(" + ",".join("?" for _ in fields) + ")", values)
        if extra.get("tool_operation_id"):
            db.execute("UPDATE scope_tool_operations SET state='in_flight',in_flight_attempt_id=? WHERE operation_id=?",
                       (attempt_id, extra["tool_operation_id"]))
        db.execute("INSERT INTO events(kind,evidence_sha256) VALUES('claimed',?)", (hash_payload(attempt_id),))
        return {"binding": _copy(binding), "attempt_id": attempt_id, "ordinal": ordinal,
                "reserved_max_microusd": quote["reserved_max_microusd"]}


def _observation(usage):
    if usage is None:
        return {"kind": "missing", "outcome": "response_observed"}
    _need(type(usage) is dict and set(usage) <= {"kind", "outcome", "input_tokens", "output_tokens", "tool_units", "provider_request_id"}, "usage_integrity")
    _need(usage.get("kind") in {"missing", "estimated", "provider_reported"}, "usage_integrity")
    result = {"kind": usage["kind"], "outcome": usage.get("outcome", "response_observed")}
    _need(result["outcome"] in {"response_observed", "unknown"}, "usage_integrity")
    for field in ("input_tokens", "output_tokens", "tool_units"):
        if field in usage:
            _need(result["kind"] != "missing", "usage_integrity")
            result[field] = _count(usage[field], "usage_integrity")
    if "provider_request_id" in usage:
        _need(isinstance(usage["provider_request_id"], str) and len(usage["provider_request_id"]) <= 2048, "usage_integrity")
        result["provider_request_id_sha256"] = hash_payload(usage["provider_request_id"])
    return result


def record_observation(claim, usage=None, *, response_fingerprint=None):
    _need(type(claim) is dict and set(claim) == {"binding", "attempt_id", "ordinal", "reserved_max_microusd"}, "invalid_request")
    with _tx(claim["binding"]) as (db, _, _):
        attempt = db.execute("SELECT * FROM attempts WHERE attempt_id=?", (claim["attempt_id"],)).fetchone()
        _need(attempt is not None and attempt["generation"] == claim["binding"]["generation"]
              and attempt["participant_id"] == claim["binding"]["participant_id"]
              and attempt["ordinal"] == claim["ordinal"] and attempt["reserved"] == claim["reserved_max_microusd"], "invalid_binding")
        scoped = _is_v2(claim["binding"]) and attempt["scope_id"] is not None
        disposition = None
        if scoped and isinstance(usage, dict) and "tool_result" in usage:
            usage = dict(usage)
            disposition = usage.pop("tool_result")
        obs = _observation(usage)
        if response_fingerprint is not None:
            _need(scoped and type(response_fingerprint) is dict and set(response_fingerprint) == {"basis", "sha256"}, "usage_integrity")
            _need(response_fingerprint["basis"] in {"provider_json/v1", "http_bytes/v1"}, "usage_integrity")
            _hash(response_fingerprint["sha256"], "usage_integrity")
            obs["response_fingerprint"] = _copy(response_fingerprint)
        if disposition is not None:
            _need(attempt["tool_operation_id"] is not None and disposition in {"complete", "retryable_known", "terminal_known"}, "usage_integrity")
            obs["tool_result"] = disposition
        envelope = json.loads(attempt["envelope"])
        breached = any(obs.get(field, 0) > envelope[bound] for field, bound in
                       (("input_tokens", "input_tokens"), ("output_tokens", "max_output_tokens"), ("tool_units", "tool_units")))
        raw = _json(obs)
        if attempt["observation"] is not None:
            _need(attempt["observation"] == raw, "observation_conflict")
        else:
            db.execute("UPDATE attempts SET state=?,observation=?,observation_sha256=?,observed_utc=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE attempt_id=?",
                       ("integrity_breach" if breached else obs["outcome"], raw, hash_payload(obs), claim["attempt_id"]))
            db.execute("INSERT INTO events(kind,evidence_sha256) VALUES('observed',?)", (hash_payload(obs),))
        _need(not breached, "usage_integrity")
        if obs["outcome"] == "unknown":
            _stop(db, "unknown_outcome")
        if scoped:
            _v2_observed(db, attempt, obs)
        return obs


def _claim_current(route_id, request, *, catalog_lookup_id=None, followup_operation_id=None):
    b = check_context()
    _need(b is not None, "missing_context")
    op = _operation_value(_operation.get())
    claim = reserve_and_claim(b, route_id, request, stage=op["stage"], logical_key=op["logical_key"],
                              catalog_lookup_id=catalog_lookup_id, followup_operation_id=followup_operation_id)
    try:
        for capture in _dispatch_captures.get():
            capture._add(claim)
    except SpendingStop:
        halt(b, "transport_receipt_missing")
        raise
    return claim


def _unknown(claim):
    try:
        halt(claim["binding"], "unknown_outcome")
    except SpendingStop:
        _LOCAL_STOPS[claim["binding"]["authorization_id"]] = "unknown_outcome"


def dispatch(route_id, request, send, *, usage=None, catalog_lookup_id=None, followup_operation_id=None,
             response_fingerprint=None):
    claim = _claim_current(route_id, request, catalog_lookup_id=catalog_lookup_id, followup_operation_id=followup_operation_id)
    try:
        result = send()
        _need(not hasattr(result, "__await__"), "invalid_request")
        obs = record_observation(claim, usage(result) if usage else None,
                                 response_fingerprint=response_fingerprint(result) if response_fingerprint else None)
        if obs["outcome"] == "unknown":
            raise SpendingStop("unknown_outcome")
        return result
    except BaseException as exc:
        _unknown(claim)
        if isinstance(exc, SpendingStop):
            raise
        raise SpendingStop("unknown_outcome") from None


async def dispatch_async(route_id, request, send, *, usage=None, catalog_lookup_id=None, followup_operation_id=None,
                         response_fingerprint=None):
    claim = _claim_current(route_id, request, catalog_lookup_id=catalog_lookup_id, followup_operation_id=followup_operation_id)
    try:
        result = await send()
        obs = record_observation(claim, usage(result) if usage else None,
                                 response_fingerprint=response_fingerprint(result) if response_fingerprint else None)
        if obs["outcome"] == "unknown":
            raise SpendingStop("unknown_outcome")
        return result
    except BaseException as exc:
        _unknown(claim)
        if isinstance(exc, SpendingStop):
            raise
        raise SpendingStop("unknown_outcome") from None


def halt(binding, reason):
    code = SpendingStop(reason).code
    with _tx(binding) as (db, _, _):
        _stop(db, code)


def close_run(binding):
    with _tx(binding) as (db, row, _):
        if row["state"] == "closed":
            return
        _need(row["state"] in {"active", "paused_recoverable"}, _state_code(row))
        _need(db.execute("SELECT count(*) FROM attempts WHERE state='unknown'").fetchone()[0] == 0, "unknown_outcome")
        _stop(db, "closed")


def mark_recoverable(binding):
    with _tx(binding) as (db, row, _):
        if row["state"] in _TERMINAL or row["state"] == "paused_recoverable":
            return
        _need(row["state"] == "active", "resume_denied")
        _need(db.execute("SELECT count(*) FROM attempts WHERE state='unknown'").fetchone()[0] == 0, "unknown_outcome")
        db.execute("UPDATE run_authorization SET state='paused_recoverable' WHERE id=1")
        db.execute("INSERT INTO events(kind) VALUES('paused')")


def register_participant(binding, participant_id, *, spawn_receipt_sha256, operation_context=None, scope_entry_ids=()):
    if _is_v2(binding):
        return _v2_register_participant(binding, participant_id, spawn_receipt_sha256, operation_context, scope_entry_ids)
    _need(not scope_entry_ids, "unsupported_route")
    _identity(participant_id)
    _need(participant_id != "parent", "participant_unverified")
    _hash(spawn_receipt_sha256, "participant_unverified")
    op = _operation_value(operation_context if operation_context is not None else _operation.get())
    with _tx(binding, active=True) as (db, row, _):
        _need(binding["participant_id"] == "parent" and row["owner_pid"] == os.getpid(), "participant_unverified")
        _need(db.execute("SELECT 1 FROM participants WHERE generation=? AND participant_id=?", (binding["generation"], participant_id)).fetchone() is None, "participant_unverified")
        db.execute("INSERT INTO participants VALUES(?,?,NULL,'registered',?,?,NULL)",
                   (binding["generation"], participant_id, spawn_receipt_sha256, hash_payload(op)))
        result = _copy(binding)
        result["participant_id"] = participant_id
        return result


def participant_started(binding):
    with _tx(binding) as (db, row, _):
        _need(row["state"] == "active" and _lock_held(binding), "participant_unverified")
        p = db.execute("SELECT * FROM participants WHERE generation=? AND participant_id=?", (binding["generation"], binding["participant_id"])).fetchone()
        _need(p is not None and p["state"] in {"registered", "running"} and p["pid"] in {None, os.getpid()}, "participant_unverified")
        if _is_v2(binding):
            _v2_epoch(binding, row, p)
        db.execute("UPDATE participants SET pid=?,state='running' WHERE generation=? AND participant_id=?", (os.getpid(), binding["generation"], binding["participant_id"]))
        return _copy(binding)


def participant_exited(binding, participant_id, *, exit_receipt_sha256):
    _hash(exit_receipt_sha256, "participant_unverified")
    with _tx(binding) as (db, row, _):
        _need(_lock_held(binding) and participant_id != "parent", "participant_unverified")
        p = db.execute("SELECT * FROM participants WHERE generation=? AND participant_id=?", (binding["generation"], participant_id)).fetchone()
        if _is_v2(binding):
            registrar = db.execute("SELECT * FROM participants WHERE generation=? AND participant_id=?", (binding["generation"], binding["participant_id"])).fetchone()
            _need(p is not None and registrar is not None and registrar["pid"] == os.getpid() and registrar["state"] == "running"
                  and (binding["participant_id"] == "parent" or p["parent_participant_id"] == binding["participant_id"]), "participant_unverified")
        else:
            _need(binding["participant_id"] == "parent" and row["owner_pid"] == os.getpid(), "participant_unverified")
        _need(p is not None and p["exit_sha256"] in {None, exit_receipt_sha256}, "participant_unverified")
        db.execute("UPDATE participants SET state='exited',exit_sha256=? WHERE generation=? AND participant_id=?", (exit_receipt_sha256, binding["generation"], participant_id))
        if db.execute("SELECT 1 FROM attempts WHERE generation=? AND participant_id=? AND state='unknown' LIMIT 1",
                      (binding["generation"], participant_id)).fetchone() is not None:
            _stop(db, "unknown_outcome")


def export_environment(binding, *, operation_context=None):
    b = open_existing(binding)
    env = {"DRF_RUN_SPENDING_REQUIRED": "1", "DRF_RUN_SPENDING_BINDING": _json(b),
           "DRF_RUN_SPENDING_MODULE_SHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    op = operation_context if operation_context is not None else _operation.get()
    if op is not None:
        op = _operation_value(op)
        if b["participant_id"] != "parent":
            with _tx(b) as (db, _, _):
                p = db.execute("SELECT operation_sha256 FROM participants WHERE generation=? AND participant_id=?", (b["generation"], b["participant_id"])).fetchone()
                _need(p is not None and p[0] == hash_payload(op), "participant_unverified")
        env["DRF_RUN_SPENDING_OPERATION"] = _json(op)
    _need(b["participant_id"] == "parent" or op is not None, "missing_context")
    return env


def _participants(db):
    columns = "generation,participant_id,state,spawn_sha256,operation_sha256,exit_sha256"
    if db.execute("PRAGMA user_version").fetchone()[0] == 2:
        columns += ",parent_participant_id,inherited_scope_id,admission_epoch,scope_entry_ids"
    return [dict(p) for p in db.execute("SELECT " + columns + " FROM participants ORDER BY generation,participant_id")]


def resume_existing(binding, proof):
    if _is_v2(binding):
        return _v2_resume(binding, proof)
    with _tx(binding) as (db, row, m):
        _need(type(proof) is dict and set(proof) == {"approval_sha256", "request_sha256", "source_sha256", "routes_sha256", "participants_sha256"}, "resume_denied")
        _hash(proof["approval_sha256"], "resume_denied")
        _need(binding["participant_id"] == "parent" and row["owner_pid"] == os.getpid() and _lock_held(binding), "lock_unavailable")
        _need(row["state"] == "paused_recoverable", "resume_denied")
        _need(all(proof[k] == m[k] for k in ("request_sha256", "source_sha256", "routes_sha256")), "resume_denied")
        _need(proof["participants_sha256"] == hash_payload(_participants(db)), "resume_denied")
        _need(db.execute("SELECT count(*) FROM attempts WHERE state='unknown'").fetchone()[0] == 0, "resume_denied")
        _need(db.execute("SELECT count(*) FROM participants WHERE participant_id!='parent' AND state!='exited'").fetchone()[0] == 0, "resume_denied")
        evidence = hash_payload(proof)
        _need(db.execute("SELECT 1 FROM events WHERE kind='resumed' AND evidence_sha256=?", (evidence,)).fetchone() is None, "resume_denied")
        generation = row["generation"] + 1
        db.execute("UPDATE run_authorization SET generation=?,state='active',stop_code=NULL WHERE id=1", (generation,))
        db.execute("UPDATE participants SET state='exited',exit_sha256=? WHERE participant_id='parent' AND generation=?", (evidence, row["generation"]))
        db.execute("INSERT INTO participants VALUES(?,'parent',?,'running',?,NULL,NULL)", (generation, os.getpid(), evidence))
        db.execute("INSERT INTO events(kind,evidence_sha256) VALUES('resumed',?)", (evidence,))
        result = _copy(binding)
        result["generation"] = generation
    _adopt_transition(binding, result)
    return result


def summary(binding):
    with _tx(binding, fence=False) as (db, row, _):
        attempts = list(db.execute("SELECT route_id,reserved,state,observation FROM attempts"))
        retained = sum(a["reserved"] for a in attempts)
        _need(retained <= row["cap"], "usage_integrity")
        states, routes, kinds = {}, {}, {"missing": 0, "estimated": 0, "provider_reported": 0}
        for a in attempts:
            states[a["state"]] = states.get(a["state"], 0) + 1
            routes[a["route_id"]] = routes.get(a["route_id"], 0) + a["reserved"]
            kinds[json.loads(a["observation"])["kind"] if a["observation"] else "missing"] += 1
        return {"schema": "target-run-spending-summary/v1", "authorization_sha256": hash_payload(binding["authorization_id"]),
                "manifest_sha256": binding["manifest_sha256"], "source_sha256": binding["source_sha256"],
                "routes_sha256": binding["routes_sha256"], "pipeline_id": row["pipeline_id"],
                "generation": row["generation"], "state": row["state"], "stop_code": row["stop_code"],
                "cap_microusd": row["cap"], "reserved_max_microusd": retained, "remaining_microusd": row["cap"]-retained,
                "attempt_count": len(attempts), "attempt_states": states, "route_reserved_microusd": routes,
                "usage_kinds": kinds, "participants": _participants(db)}


# v2 is opt-in for newly created authorizations only. No v1 DB is migrated.
_ANCHOR_LIMITS = {"model_attempt_limit": 20, "token_envelope_limit": 150000,
                  "catalog_attempt_limit": 8, "followup_attempt_limit": 12}
_ANCHOR_REQUEST_KEYS = {"mode", "anchor_budget_scope_id", "policy_version", "source_policy_sha256",
                        *_ANCHOR_LIMITS, "catalog_lookups_per_gap", "followup_round_limit"}
_SESSION_KEYS = {"session_id", "research_generation_id", "input_manifest_sha256", "requirement_registry_sha256",
                 "workers_quiesced_sha256", "restart_of_session_id"}


def _is_v2(binding):
    return isinstance(binding, dict) and binding.get("schema") == _BINDING_V2


def _remember_v2_binding(binding):
    global _V2_CONTROL_BINDING
    if _is_v2(binding):
        _V2_CONTROL_BINDING = _json(binding)


def _remembered_v2_binding():
    # Only a denial may use this last validated control descriptor. It must
    # never substitute for missing worker context or grant send permission.
    if _ACTIVE_AUTH is None or _V2_CONTROL_BINDING is None:
        return None
    b = json.loads(_V2_CONTROL_BINDING)
    if (b["authorization_id"], b["manifest_sha256"], b["root"]) == _ACTIVE_AUTH:
        return b
    return None


def _validate_v2_manifest(manifest):
    m = _copy(manifest)
    _need(set(m) == {"schema", "authorization_id", "root", "currency", "cap_usd", "request_sha256",
                    "source_files", "source_sha256", "routes_sha256", "resume_policy", "routes", "anchor_budget"}, "invalid_manifest")
    routes = m["routes"]
    _need(type(routes) is dict and 1 <= len(routes) <= 16, "invalid_manifest")
    seen = set()
    for name, route in routes.items():
        _need(type(route) is dict, "invalid_manifest")
        converted = _copy(route)
        if route.get("kind") == "catalog_lookup":
            _need(set(route) == _ROUTE_KEYS | {"catalog_contract"}, "invalid_manifest")
            contract = converted.pop("catalog_contract")
            _need(type(contract) is dict and set(contract) == {"provider_id", "operation_id", "catalog_sha256",
                  "request_schema_sha256", "response_bound_sha256", "retry_policy_sha256"}, "invalid_manifest")
            _identity(contract["provider_id"], "invalid_manifest")
            _identity(contract["operation_id"], "invalid_manifest")
            for field in ("catalog_sha256", "request_schema_sha256", "response_bound_sha256", "retry_policy_sha256"):
                _hash(contract[field])
            converted["kind"] = "firecrawl_search"
        else:
            _need(isinstance(route.get("kind"), str) and route["kind"] not in seen, "unsupported_route")
            seen.add(route["kind"])
        base = {k: v for k, v in m.items() if k != "anchor_budget"}
        base.update(schema=_SCHEMA, routes={name: converted}, routes_sha256=hash_payload({name: converted}))
        _validate_v1_manifest(base)
    _need(hash_payload(routes) == m["routes_sha256"], "source_drift")
    p = m["anchor_budget"]
    _need(type(p) is dict and set(p) == {"schema", "scope_id", "policy_version", "source_policy_sha256",
          *_ANCHOR_LIMITS, "catalog_lookups_per_gap", "followup_round_limit", "model_profile",
          "catalog_route_ids", "followup_route_ids", "usage_policy"}, "invalid_manifest")
    _need(p["schema"] == "anchor-budget/v1" and p["policy_version"] == "world-anchor-budget/v1"
          and p["usage_policy"] == "provider_reported_required", "invalid_manifest")
    _identity(p["scope_id"], "invalid_manifest")
    _hash(p["source_policy_sha256"])
    for key, maximum in _ANCHOR_LIMITS.items():
        _count(p[key], "invalid_manifest", positive=key in {"model_attempt_limit", "token_envelope_limit"})
        _need(p[key] <= maximum, "invalid_manifest")
    for field in ("catalog_lookups_per_gap", "followup_round_limit"):
        _need(type(p[field]) is int and p[field] == 1, "invalid_manifest")
    profile = p["model_profile"]
    _need(type(profile) is dict and set(profile) == {"route_id", "max_output_tokens"}, "invalid_manifest")
    _identity(profile["route_id"], "invalid_manifest")
    _need(profile["route_id"] in routes and routes[profile["route_id"]]["kind"] == "openai_chat", "unsupported_route")
    _count(profile["max_output_tokens"], "invalid_manifest", positive=True)
    _need(profile["max_output_tokens"] <= min(2000, routes[profile["route_id"]]["max_output_tokens"]), "invalid_manifest")
    for key, allowed in (("catalog_route_ids", {"catalog_lookup"}), ("followup_route_ids", {"firecrawl_search", "firecrawl_scrape"})):
        _need(type(p[key]) is list and len(p[key]) <= 16 and all(isinstance(x, str) for x in p[key])
              and len(set(p[key])) == len(p[key]), "invalid_manifest")
        _need(all(x in routes and routes[x]["kind"] in allowed for x in p[key]), "unsupported_route")
    return m


def _validate_anchor_request(manifest, request):
    _need(type(request) is dict and "world_anchor" in request, "binding_conflict")
    expected = {"mode": "v1", "anchor_budget_scope_id": manifest["anchor_budget"]["scope_id"],
                **{k: manifest["anchor_budget"][k] for k in _ANCHOR_REQUEST_KEYS - {"mode", "anchor_budget_scope_id"}}}
    _need(request["world_anchor"] == expected, "binding_conflict")


_DDL_V2 = """
ALTER TABLE run_authorization ADD COLUMN admission_epoch INTEGER NOT NULL DEFAULT 0;
ALTER TABLE run_authorization ADD COLUMN active_scope_id TEXT;
ALTER TABLE run_authorization ADD COLUMN active_scope_session_id TEXT;
ALTER TABLE run_authorization ADD COLUMN pending_restart_session_id TEXT;
ALTER TABLE attempts ADD COLUMN scope_id TEXT;
ALTER TABLE attempts ADD COLUMN scope_session_id TEXT;
ALTER TABLE attempts ADD COLUMN admission_epoch INTEGER NOT NULL DEFAULT 0;
ALTER TABLE attempts ADD COLUMN model_attempt_units INTEGER NOT NULL DEFAULT 0;
ALTER TABLE attempts ADD COLUMN token_envelope_units INTEGER NOT NULL DEFAULT 0;
ALTER TABLE attempts ADD COLUMN catalog_attempt_units INTEGER NOT NULL DEFAULT 0;
ALTER TABLE attempts ADD COLUMN followup_attempt_units INTEGER NOT NULL DEFAULT 0;
ALTER TABLE attempts ADD COLUMN tool_operation_id TEXT;
ALTER TABLE participants ADD COLUMN parent_participant_id TEXT;
ALTER TABLE participants ADD COLUMN inherited_scope_id TEXT;
ALTER TABLE participants ADD COLUMN admission_epoch INTEGER NOT NULL DEFAULT 0;
ALTER TABLE participants ADD COLUMN scope_entry_ids TEXT NOT NULL DEFAULT '[]';
CREATE TABLE budget_scopes(scope_id TEXT PRIMARY KEY, policy_sha256 TEXT NOT NULL, policy TEXT NOT NULL);
CREATE TABLE scope_sessions(session_id TEXT PRIMARY KEY, scope_id TEXT NOT NULL,
 context TEXT NOT NULL, owner_generation INTEGER NOT NULL, owner_participant_id TEXT NOT NULL,
 enter_epoch INTEGER NOT NULL, exit_epoch INTEGER, state TEXT NOT NULL,
 budget_receipt TEXT, completion TEXT);
CREATE TABLE scope_transitions(epoch INTEGER PRIMARY KEY, receipt TEXT NOT NULL);
CREATE TABLE anchor_followups(scope_id TEXT PRIMARY KEY, followup_id TEXT UNIQUE NOT NULL,
 gap_manifest_sha256 TEXT NOT NULL, gaps TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'open', result_sha256 TEXT);
CREATE TABLE scope_tool_operations(operation_id TEXT PRIMARY KEY, scope_id TEXT NOT NULL,
 followup_id TEXT NOT NULL, kind TEXT NOT NULL, gap_key TEXT NOT NULL,
 route_id TEXT NOT NULL, query_sha256 TEXT NOT NULL, state TEXT NOT NULL,
 in_flight_attempt_id TEXT, result_sha256 TEXT);
CREATE UNIQUE INDEX one_catalog_lookup_per_gap ON scope_tool_operations(scope_id,gap_key) WHERE kind='catalog';
CREATE UNIQUE INDEX one_followup_wire_operation ON scope_tool_operations(scope_id,kind,gap_key,route_id,query_sha256);
CREATE TRIGGER immutable_scope_update BEFORE UPDATE ON budget_scopes BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER immutable_scope_delete BEFORE DELETE ON budget_scopes BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER immutable_scope_debits BEFORE UPDATE OF scope_id,scope_session_id,admission_epoch,
 model_attempt_units,token_envelope_units,catalog_attempt_units,followup_attempt_units,tool_operation_id
 ON attempts BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER immutable_followup_update BEFORE UPDATE OF scope_id,followup_id,gap_manifest_sha256,gaps ON anchor_followups BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER immutable_followup_delete BEFORE DELETE ON anchor_followups BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER immutable_tool_identity BEFORE UPDATE OF operation_id,scope_id,followup_id,kind,gap_key,route_id,query_sha256
 ON scope_tool_operations BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER no_tool_operation_delete BEFORE DELETE ON scope_tool_operations BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER no_transition_update BEFORE UPDATE ON scope_transitions BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER no_transition_delete BEFORE DELETE ON scope_transitions BEGIN SELECT RAISE(ABORT,'immutable'); END;
"""


def _v2_epoch(b, row, participant):
    _need(b["admission_epoch"] == row["admission_epoch"] == participant["admission_epoch"], "stale_admission_epoch")
    _need(b["active_scope_id"] == row["active_scope_id"] == participant["inherited_scope_id"], "budget_scope_conflict")


def _v2_admission(db, b, row, participant, *, scope_control=False):
    _v2_epoch(b, row, participant)
    if row["active_scope_id"] is not None and not scope_control:
        session = db.execute("SELECT state FROM scope_sessions WHERE session_id=?", (row["active_scope_session_id"],)).fetchone()
        _need(session is not None and session["state"] == "open", "budget_scope_missing")


def _scope_totals(db, scope_id):
    rows = db.execute("SELECT reserved,model_attempt_units,token_envelope_units,catalog_attempt_units,followup_attempt_units FROM attempts WHERE scope_id=?", (scope_id,))
    totals = dict(model_attempts=0, token_envelope_units=0, catalog_attempts=0, followup_attempts=0, reserved_max_microusd=0)
    for r in rows:
        for key, col in (("reserved_max_microusd", 0), ("model_attempts", 1), ("token_envelope_units", 2), ("catalog_attempts", 3), ("followup_attempts", 4)):
            totals[key] += r[col]
            _count(totals[key], "usage_integrity")
    return totals


def _scope_view(db, row, m):
    p = m["anchor_budget"]
    retained = _scope_totals(db, p["scope_id"])
    mapping = {"model_attempts": "model_attempt_limit", "token_envelope_units": "token_envelope_limit",
               "catalog_attempts": "catalog_attempt_limit", "followup_attempts": "followup_attempt_limit"}
    _need(all(retained[k] <= p[v] for k, v in mapping.items()), "usage_integrity")
    sessions = [dict(r) for r in db.execute("SELECT session_id,owner_generation,owner_participant_id,enter_epoch,exit_epoch,state FROM scope_sessions ORDER BY enter_epoch")]
    followup = db.execute("SELECT followup_id,gap_manifest_sha256,state,result_sha256 FROM anchor_followups WHERE scope_id=?", (p["scope_id"],)).fetchone()
    active_session = next((s for s in sessions if s["session_id"] == row["active_scope_session_id"]), None)
    return {"schema": "anchor-budget-summary/v1", "scope_id": p["scope_id"], "policy_sha256": hash_payload(p),
            "generation": row["generation"], "admission_epoch": row["admission_epoch"], "active_scope_id": row["active_scope_id"],
            "active_session_id": row["active_scope_session_id"], "pending_restart_session_id": row["pending_restart_session_id"],
            "active_session_state": active_session["state"] if active_session is not None else None,
            "state": row["state"], "stop_code": row["stop_code"], "limits": {k: p[k] for k in _ANCHOR_LIMITS},
            "retained": retained, "remaining": {k: p[v] - retained[k] for k, v in mapping.items()},
            "sessions": sessions, "followup": dict(followup) if followup is not None else None}


def scope_summary(binding):
    _need(_is_v2(binding), "budget_scope_missing")
    with _tx(binding, fence=False) as (db, row, m):
        return _scope_view(db, row, m)


def _profile(m):
    p = m["anchor_budget"]
    profile = p["model_profile"]
    r = m["routes"][profile["route_id"]]
    tokens = r["input_ceiling"] + profile["max_output_tokens"]
    _need(tokens <= p["token_envelope_limit"] and tokens <= _MAX, "stage_profile_oversize")
    return {"schema": "anchor-profile/v1", "scope_id": p["scope_id"], "policy_sha256": hash_payload(p),
            "route_id": profile["route_id"], "routes_sha256": m["routes_sha256"],
            "input_upper_bound": r["input_ceiling"], "max_output_tokens": profile["max_output_tokens"], "token_envelope_units": tokens}


def preflight_anchor_profile(binding):
    _need(_is_v2(binding), "budget_scope_missing")
    with _tx(binding, active=True, scope_control=True) as (_, _, m):
        return _profile(m)


def _scope_owner(db, b, row, *, entering=False):
    participant = db.execute("SELECT * FROM participants WHERE generation=? AND participant_id=?", (b["generation"], b["participant_id"])).fetchone()
    _need(participant is not None, "participant_unverified")
    if entering:
        scope_id = db.execute("SELECT scope_id FROM budget_scopes").fetchone()[0]
        _need(b["participant_id"] == "parent" or scope_id in json.loads(participant["scope_entry_ids"]), "participant_unverified")
    else:
        s = db.execute("SELECT * FROM scope_sessions WHERE session_id=?", (row["active_scope_session_id"],)).fetchone()
        _need(s is not None and s["owner_generation"] == b["generation"] and s["owner_participant_id"] == b["participant_id"], "participant_unverified")
        return s


def _quiesced(db, b):
    ancestors = {b["participant_id"]}
    current = b["participant_id"]
    while current != "parent":
        p = db.execute("SELECT parent_participant_id FROM participants WHERE generation=? AND participant_id=?", (b["generation"], current)).fetchone()
        _need(p is not None and p[0] is not None and p[0] not in ancestors, "participant_unverified")
        current = p[0]
        ancestors.add(current)
    for p in db.execute("SELECT participant_id,state FROM participants WHERE generation=?", (b["generation"],)):
        _need(p[0] in ancestors or p[1] == "exited", "participant_unverified")
    _need(db.execute("SELECT 1 FROM attempts WHERE state='unknown' LIMIT 1").fetchone() is None, "unknown_outcome")


def _transition(db, b, row, *, scope_id, session_id, kind, proof_sha256):
    epoch = row["admission_epoch"] + 1
    _count(epoch, "budget_scope_conflict")
    receipt = {"schema": "scope-transition/v1", "authorization_id": b["authorization_id"], "pipeline_id": b["pipeline_id"],
               "generation": b["generation"], "session_id": session_id, "owner_participant_id": b["participant_id"],
               "kind": kind, "from_epoch": row["admission_epoch"], "to_epoch": epoch,
               "from_scope_id": row["active_scope_id"], "to_scope_id": scope_id, "proof_sha256": proof_sha256}
    db.execute("UPDATE run_authorization SET admission_epoch=?,active_scope_id=?,active_scope_session_id=?,pending_restart_session_id=NULL WHERE id=1",
               (epoch, scope_id, session_id if scope_id is not None else None))
    db.execute("UPDATE participants SET admission_epoch=?,inherited_scope_id=? WHERE generation=? AND participant_id=?",
               (epoch, scope_id, b["generation"], b["participant_id"]))
    db.execute("INSERT INTO scope_transitions(epoch,receipt) VALUES(?,?)", (epoch, _json(receipt)))
    db.execute("INSERT INTO events(kind,evidence_sha256) VALUES('scope_transition',?)", (hash_payload(receipt),))
    updated = _copy(b)
    updated.update(admission_epoch=epoch, active_scope_id=scope_id)
    return {"binding": updated, "transition_receipt": receipt}


def _adopt_v2(previous, committed):
    with _latch_lock:
        _check_env_pin()
        fixed = _BINDING_KEYS - {"generation", "pipeline_id"}
        _need(_is_v2(committed) and all(previous[k] == committed[k] for k in fixed), "invalid_binding")
        with _tx(committed) as (db, row, _):
            p = db.execute("SELECT * FROM participants WHERE generation=? AND participant_id=?", (committed["generation"], committed["participant_id"])).fetchone()
            _need(p is not None and p["pid"] == os.getpid() and p["state"] == "running", "participant_unverified")
            _v2_epoch(committed, row, p)
            _need(committed["pipeline_id"] == row["pipeline_id"], "binding_conflict")
        if _ENV_PIN is not None:
            carrier = _ENV_PIN["current"]
            old = json.loads(carrier["DRF_RUN_SPENDING_BINDING"])
            _need(all(old[k] == previous[k] for k in fixed) and old["generation"] == previous["generation"], "invalid_binding")
            upgraded = dict(carrier)
            upgraded["DRF_RUN_SPENDING_BINDING"] = _json(committed)
            os.environ["DRF_RUN_SPENDING_BINDING"] = upgraded["DRF_RUN_SPENDING_BINDING"]
            _ENV_PIN["current"] = upgraded
        if _binding.get() is not None:
            _binding.set(_copy(committed))
        _remember_v2_binding(committed)


def begin_anchor_scope(binding, *, session):
    _need(_is_v2(binding), "budget_scope_missing")
    with _tx(binding, active=True, scope_control=True) as (db, row, m):
        _need(type(session) is dict and set(session) == _SESSION_KEYS, "budget_scope_conflict")
        for field in ("session_id", "research_generation_id"):
            _identity(session[field], "budget_scope_conflict")
        for field in ("input_manifest_sha256", "requirement_registry_sha256", "workers_quiesced_sha256"):
            _hash(session[field], "budget_scope_conflict")
        _profile(m)
        _scope_owner(db, binding, row, entering=True)
        existing = db.execute("SELECT * FROM scope_sessions WHERE session_id=?", (session["session_id"],)).fetchone()
        if existing is not None:
            _need(row["active_scope_session_id"] == session["session_id"] and existing["context"] == _json(session)
                  and existing["state"] == "open" and existing["owner_generation"] == binding["generation"]
                  and existing["owner_participant_id"] == binding["participant_id"], "budget_scope_conflict")
            receipt = json.loads(db.execute("SELECT receipt FROM scope_transitions WHERE epoch=?", (existing["enter_epoch"],)).fetchone()[0])
            return {"binding": _copy(binding), "transition_receipt": receipt}
        _need(row["active_scope_session_id"] is None, "budget_scope_conflict")
        _need(session["restart_of_session_id"] == row["pending_restart_session_id"], "budget_scope_conflict")
        if session["restart_of_session_id"] is not None:
            old = db.execute("SELECT context,state FROM scope_sessions WHERE session_id=?", (session["restart_of_session_id"],)).fetchone()
            _need(old is not None and old["state"] == "interrupted", "budget_scope_conflict")
            previous = json.loads(old["context"])
            _need(all(previous[k] == session[k] for k in ("research_generation_id", "input_manifest_sha256", "requirement_registry_sha256")), "budget_scope_conflict")
        _quiesced(db, binding)
        scope_id = m["anchor_budget"]["scope_id"]
        result = _transition(db, binding, row, scope_id=scope_id, session_id=session["session_id"], kind="enter", proof_sha256=hash_payload(session))
        db.execute("INSERT INTO scope_sessions(session_id,scope_id,context,owner_generation,owner_participant_id,enter_epoch,state) VALUES(?,?,?,?,?,?,'open')",
                   (session["session_id"], scope_id, _json(session), binding["generation"], binding["participant_id"], result["binding"]["admission_epoch"]))
    _adopt_v2(binding, result["binding"])
    return result


def seal_anchor_budget(binding, *, seal):
    _need(_is_v2(binding), "budget_scope_missing")
    with _tx(binding, active=True, scope_control=True) as (db, row, m):
        _need(type(seal) is dict and set(seal) == {"session_id", "participants_exited_sha256", "workers_joined_sha256"}, "budget_scope_conflict")
        for field in ("participants_exited_sha256", "workers_joined_sha256"):
            _hash(seal[field], "participant_unverified")
        s = _scope_owner(db, binding, row)
        _need(s["session_id"] == seal["session_id"] and s["state"] in {"open", "sealing"}, "budget_scope_conflict")
        if s["budget_receipt"] is not None:
            return json.loads(s["budget_receipt"])
        _quiesced(db, binding)
        p = m["anchor_budget"]
        followup = db.execute("SELECT state FROM anchor_followups WHERE scope_id=?", (p["scope_id"],)).fetchone()
        _need(followup is None or followup[0] == "complete", "tool_operation_conflict")
        receipt = {"schema": "anchor-budget-receipt/v1", "authorization_sha256": hash_payload(binding["authorization_id"]),
                   "pipeline_id": binding["pipeline_id"], "scope_id": p["scope_id"], "session_id": s["session_id"],
                   "generation": binding["generation"], "policy_sha256": hash_payload(p), "source_sha256": m["source_sha256"],
                   "routes_sha256": m["routes_sha256"], "retained": _scope_totals(db, p["scope_id"]),
                   "limits": {k: p[k] for k in _ANCHOR_LIMITS}, "barrier_sha256": hash_payload(seal)}
        db.execute("UPDATE scope_sessions SET state='sealing',budget_receipt=? WHERE session_id=?", (_json(receipt), s["session_id"]))
        return receipt


def finish_anchor_scope(binding, *, completion):
    _need(_is_v2(binding), "budget_scope_missing")
    with _tx(binding, active=True, scope_control=True) as (db, row, _):
        _need(type(completion) is dict and set(completion) == {"session_id", "artifact_manifest_sha256", "budget_receipt_sha256", "result"}, "budget_scope_conflict")
        _need(completion["result"] in {"sealed", "non_ready"}, "budget_scope_conflict")
        _hash(completion["artifact_manifest_sha256"], "budget_scope_conflict")
        _hash(completion["budget_receipt_sha256"], "budget_scope_conflict")
        s = _scope_owner(db, binding, row)
        _need(s["state"] == "sealing" and s["session_id"] == completion["session_id"]
              and hash_payload(json.loads(s["budget_receipt"])) == completion["budget_receipt_sha256"], "budget_scope_conflict")
        _quiesced(db, binding)
        result = _transition(db, binding, row, scope_id=None, session_id=s["session_id"], kind="exit", proof_sha256=hash_payload(completion))
        db.execute("UPDATE scope_sessions SET state=?,exit_epoch=?,completion=? WHERE session_id=?",
                   (completion["result"], result["binding"]["admission_epoch"], _json(completion), s["session_id"]))
    _adopt_v2(binding, result["binding"])
    return result


def adopt_scope_handoff(binding, receipts):
    _need(_is_v2(binding), "budget_scope_missing")
    with _tx(binding) as (db, row, _):
        _need(binding["participant_id"] == "parent" and row["owner_pid"] == os.getpid() and _lock_held(binding), "participant_unverified")
        _need(type(receipts) is list and 1 <= len(receipts) <= 2, "budget_scope_conflict")
        epoch, scope = binding["admission_epoch"], binding["active_scope_id"]
        for receipt in receipts:
            _need(type(receipt) is dict and type(receipt.get("to_epoch")) is int, "budget_scope_conflict")
            stored = db.execute("SELECT receipt FROM scope_transitions WHERE epoch=?", (receipt["to_epoch"],)).fetchone()
            _need(stored is not None and stored[0] == _json(receipt), "budget_scope_conflict")
            _need(receipt["generation"] == binding["generation"] and receipt["from_epoch"] == epoch
                  and receipt["from_scope_id"] == scope, "stale_admission_epoch")
            epoch, scope = receipt["to_epoch"], receipt["to_scope_id"]
        _need(epoch == row["admission_epoch"] and scope == row["active_scope_id"], "stale_admission_epoch")
        db.execute("UPDATE participants SET admission_epoch=?,inherited_scope_id=? WHERE generation=? AND participant_id='parent'", (epoch, scope, binding["generation"]))
        updated = _copy(binding)
        updated.update(admission_epoch=epoch, active_scope_id=scope)
    _adopt_v2(binding, updated)
    return updated


def _v2_register_participant(binding, participant_id, spawn_hash, operation_context, scope_entry_ids):
    _identity(participant_id)
    _need(participant_id != "parent", "participant_unverified")
    _hash(spawn_hash, "participant_unverified")
    op = _operation_value(operation_context if operation_context is not None else _operation.get())
    with _tx(binding, active=True, scope_control=True) as (db, row, m):
        allowed = list(scope_entry_ids)
        _need(allowed in ([], [m["anchor_budget"]["scope_id"]]), "participant_unverified")
        _need(not allowed or (binding["participant_id"] == "parent" and row["owner_pid"] == os.getpid()), "participant_unverified")
        if binding["participant_id"] != "parent":
            _need(row["active_scope_id"] == m["anchor_budget"]["scope_id"], "participant_unverified")
        _need(db.execute("SELECT 1 FROM participants WHERE generation=? AND participant_id=?", (binding["generation"], participant_id)).fetchone() is None, "participant_unverified")
        db.execute("INSERT INTO participants(generation,participant_id,state,spawn_sha256,operation_sha256,parent_participant_id,inherited_scope_id,admission_epoch,scope_entry_ids) VALUES(?,?,'registered',?,?,?,?,?,?)",
                   (binding["generation"], participant_id, spawn_hash, hash_payload(op), binding["participant_id"], binding["active_scope_id"], binding["admission_epoch"], _json(allowed)))
        result = _copy(binding)
        result["participant_id"] = participant_id
        return result


def _v2_debits(db, b, row, m, route_id, request, quote, catalog_id, followup_id):
    result = {"scope_id": b["active_scope_id"], "scope_session_id": row["active_scope_session_id"],
              "admission_epoch": b["admission_epoch"], "model_attempt_units": 0, "token_envelope_units": 0,
              "catalog_attempt_units": 0, "followup_attempt_units": 0, "tool_operation_id": None}
    if b["active_scope_id"] is None:
        _need(catalog_id is None and followup_id is None and m["routes"][route_id]["kind"] != "catalog_lookup", "budget_scope_missing")
        return result
    p = m["anchor_budget"]
    _need(b["active_scope_id"] == p["scope_id"], "budget_scope_conflict")
    kind = m["routes"][route_id]["kind"]
    if kind == "openai_chat":
        _need(route_id == p["model_profile"]["route_id"] and catalog_id is None and followup_id is None, "unsupported_route")
        _need(request["max_output_tokens"] <= p["model_profile"]["max_output_tokens"], "stage_profile_oversize")
        result.update(model_attempt_units=1, token_envelope_units=request["input_tokens"] + request["max_output_tokens"])
    else:
        _need((catalog_id is None) != (followup_id is None), "tool_operation_conflict")
        operation_id = catalog_id if catalog_id is not None else followup_id
        _identity(operation_id, "tool_operation_conflict")
        op = db.execute("SELECT * FROM scope_tool_operations WHERE operation_id=?", (operation_id,)).fetchone()
        expected = "catalog" if catalog_id is not None else "followup"
        allowlist = p["catalog_route_ids"] if expected == "catalog" else p["followup_route_ids"]
        _need(route_id in allowlist and op is not None and op["scope_id"] == p["scope_id"] and op["kind"] == expected
              and op["route_id"] == route_id and op["query_sha256"] == request["payload_sha256"], "tool_operation_conflict")
        _need(op["state"] in {"ready", "retry_ready"}, "tool_operation_conflict")
        round_state = db.execute("SELECT state FROM anchor_followups WHERE followup_id=?", (op["followup_id"],)).fetchone()
        _need(round_state is not None and round_state[0] == "open", "tool_operation_conflict")
        _need((kind == "catalog_lookup") == (expected == "catalog"), "unsupported_route")
        result["catalog_attempt_units" if expected == "catalog" else "followup_attempt_units"] = 1
        result["tool_operation_id"] = operation_id
    totals = _scope_totals(db, p["scope_id"])
    for total, amount, limit, code in (
        ("model_attempts", "model_attempt_units", "model_attempt_limit", "stage_model_attempts_exhausted"),
        ("token_envelope_units", "token_envelope_units", "token_envelope_limit", "stage_tokens_exhausted"),
        ("catalog_attempts", "catalog_attempt_units", "catalog_attempt_limit", "stage_tool_attempts_exhausted"),
        ("followup_attempts", "followup_attempt_units", "followup_attempt_limit", "stage_followup_attempts_exhausted")):
        _need(totals[total] <= p[limit], "usage_integrity")
        _need(result[amount] <= p[limit] - totals[total], code)
    return result


def _v2_observed(db, attempt, obs):
    if obs["outcome"] == "unknown":
        if attempt["tool_operation_id"]:
            db.execute("UPDATE scope_tool_operations SET state='unknown' WHERE operation_id=? AND in_flight_attempt_id=?", (attempt["tool_operation_id"], attempt["attempt_id"]))
        return
    required_counts = {"input_tokens", "output_tokens"} if attempt["model_attempt_units"] else {"tool_units"}
    _need(obs["kind"] == "provider_reported" and required_counts <= set(obs), "stage_usage_unverifiable")
    if attempt["tool_operation_id"] is None:
        _need("tool_result" not in obs, "usage_integrity")
        return
    disposition = obs.get("tool_result", "complete")
    next_state = {"complete": "awaiting_admission", "retryable_known": "retry_ready", "terminal_known": "failed"}[disposition]
    db.execute("UPDATE scope_tool_operations SET state=?,in_flight_attempt_id=NULL WHERE operation_id=? AND in_flight_attempt_id=?",
               (next_state, attempt["tool_operation_id"], attempt["attempt_id"]))


def register_anchor_gaps(binding, *, gap_manifest_sha256, gaps):
    _need(_is_v2(binding), "budget_scope_missing")
    with _tx(binding, active=True) as (db, row, m):
        _scope_owner(db, binding, row)
        _need(type(gaps) is list and 1 <= len(gaps) <= 1024, "budget_scope_conflict")
        normalized = []
        for gap in gaps:
            _need(type(gap) is dict and set(gap) == {"gap_key", "requirement_id", "constraint_identity_sha256"}, "budget_scope_conflict")
            _identity(gap["requirement_id"], "budget_scope_conflict")
            _hash(gap["constraint_identity_sha256"], "budget_scope_conflict")
            expected = hash_payload({"schema": "anchor-gap-budget-key/v1", "request_sha256": m["request_sha256"],
                                     "constraint_identity_sha256": gap["constraint_identity_sha256"]})
            _need(gap["gap_key"] == expected, "budget_scope_conflict")
            normalized.append(_copy(gap))
        normalized.sort(key=lambda x: x["gap_key"])
        _need(len({g["gap_key"] for g in normalized}) == len(normalized) and hash_payload(normalized) == gap_manifest_sha256, "budget_scope_conflict")
        scope = m["anchor_budget"]["scope_id"]
        existing = db.execute("SELECT * FROM anchor_followups WHERE scope_id=?", (scope,)).fetchone()
        if existing is None:
            followup_id = "followup-" + uuid4().hex
            db.execute("INSERT INTO anchor_followups(scope_id,followup_id,gap_manifest_sha256,gaps) VALUES(?,?,?,?)", (scope, followup_id, gap_manifest_sha256, _json(normalized)))
        else:
            _need(existing["gap_manifest_sha256"] == gap_manifest_sha256 and existing["gaps"] == _json(normalized), "budget_scope_conflict")
            followup_id = existing["followup_id"]
        return {"scope_id": scope, "followup_id": followup_id, "gap_manifest_sha256": gap_manifest_sha256,
                "state": existing["state"] if existing is not None else "open"}


def _open_tool_operation(binding, followup_id, gap_key, route_id, query_hash, kind):
    _need(_is_v2(binding), "budget_scope_missing")
    _hash(query_hash, "tool_operation_conflict")
    with _tx(binding, active=True) as (db, row, m):
        _scope_owner(db, binding, row)
        p = m["anchor_budget"]
        followup = db.execute("SELECT * FROM anchor_followups WHERE followup_id=? AND scope_id=?", (followup_id, p["scope_id"])).fetchone()
        _need(followup is not None and gap_key in {g["gap_key"] for g in json.loads(followup["gaps"])}, "tool_operation_conflict")
        allowlist = p["catalog_route_ids"] if kind == "catalog" else p["followup_route_ids"]
        _need(route_id in allowlist, "unsupported_route")
        if kind == "catalog":
            existing = db.execute("SELECT * FROM scope_tool_operations WHERE scope_id=? AND gap_key=? AND kind='catalog'", (p["scope_id"], gap_key)).fetchone()
        else:
            existing = db.execute("SELECT * FROM scope_tool_operations WHERE scope_id=? AND gap_key=? AND kind=? AND route_id=? AND query_sha256=?",
                                  (p["scope_id"], gap_key, kind, route_id, query_hash)).fetchone()
        if existing is None:
            _need(followup["state"] == "open", "tool_operation_conflict")
            _need(db.execute("SELECT count(*) FROM scope_tool_operations WHERE scope_id=?", (p["scope_id"],)).fetchone()[0] < 1024, "tool_operation_conflict")
            operation_id = "lookup-" + uuid4().hex
            db.execute("INSERT INTO scope_tool_operations(operation_id,scope_id,followup_id,kind,gap_key,route_id,query_sha256,state) VALUES(?,?,?,?,?,?,?,'ready')",
                       (operation_id, p["scope_id"], followup_id, kind, gap_key, route_id, query_hash))
            state = "ready"
        else:
            _need(existing["route_id"] == route_id and existing["query_sha256"] == query_hash, "catalog_lookup_conflict")
            operation_id, state = existing["operation_id"], existing["state"]
        return {"scope_id": p["scope_id"], "followup_id": followup_id, "gap_key": gap_key,
                "operation_id": operation_id, "route_id": route_id, "query_sha256": query_hash, "state": state}


def open_catalog_lookup(binding, *, followup_id, gap_key, catalog_route_id, query_sha256):
    return _open_tool_operation(binding, followup_id, gap_key, catalog_route_id, query_sha256, "catalog")


def open_followup_operation(binding, *, followup_id, gap_key, route_id, query_sha256):
    return _open_tool_operation(binding, followup_id, gap_key, route_id, query_sha256, "followup")


def complete_tool_operation(binding, operation_id, *, result_sha256, outcome="complete"):
    _need(_is_v2(binding), "budget_scope_missing")
    _hash(result_sha256, "tool_operation_conflict")
    with _tx(binding, active=True) as (db, row, _):
        _scope_owner(db, binding, row)
        _need(outcome in {"complete", "abandoned"}, "tool_operation_conflict")
        op = db.execute("SELECT * FROM scope_tool_operations WHERE operation_id=?", (operation_id,)).fetchone()
        _need(op is not None and op["scope_id"] == binding["active_scope_id"], "tool_operation_conflict")
        target = "complete" if outcome == "complete" else "failed"
        permitted = {"awaiting_admission"} if outcome == "complete" else {"ready", "retry_ready", "awaiting_admission"}
        _need(op["state"] in permitted or (op["state"] == target and op["result_sha256"] == result_sha256), "tool_operation_conflict")
        db.execute("UPDATE scope_tool_operations SET state=?,result_sha256=? WHERE operation_id=?", (target, result_sha256, operation_id))


def complete_catalog_lookup(binding, lookup_id, *, result_sha256):
    complete_tool_operation(binding, lookup_id, result_sha256=result_sha256)


def complete_anchor_followup(binding, followup_id, *, result_sha256):
    _need(_is_v2(binding), "budget_scope_missing")
    _hash(result_sha256, "tool_operation_conflict")
    with _tx(binding, active=True) as (db, row, _):
        _scope_owner(db, binding, row)
        followup = db.execute("SELECT * FROM anchor_followups WHERE followup_id=?", (followup_id,)).fetchone()
        _need(followup is not None and followup["scope_id"] == binding["active_scope_id"]
              and (followup["state"] == "open" or followup["result_sha256"] == result_sha256), "tool_operation_conflict")
        _need(db.execute("SELECT 1 FROM scope_tool_operations WHERE followup_id=? AND state NOT IN ('complete','failed') LIMIT 1", (followup_id,)).fetchone() is None, "tool_operation_conflict")
        db.execute("UPDATE anchor_followups SET state='complete',result_sha256=? WHERE followup_id=?", (result_sha256, followup_id))


def _v2_resume(binding, proof):
    with _tx(binding) as (db, row, m):
        keys = {"approval_sha256", "request_sha256", "source_sha256", "routes_sha256", "participants_sha256", "scope_state_sha256", "anchor_recovery"}
        _need(type(proof) is dict and set(proof) == keys, "resume_denied")
        _hash(proof["approval_sha256"], "resume_denied")
        _need(binding["participant_id"] == "parent" and row["owner_pid"] == os.getpid() and _lock_held(binding), "lock_unavailable")
        _need(row["state"] == "paused_recoverable" and all(proof[k] == m[k] for k in ("request_sha256", "source_sha256", "routes_sha256")), "resume_denied")
        _need(proof["participants_sha256"] == hash_payload(_participants(db))
              and proof["scope_state_sha256"] == hash_payload(_scope_view(db, row, m)), "resume_denied")
        _need(db.execute("SELECT 1 FROM attempts WHERE state='unknown' LIMIT 1").fetchone() is None, "resume_denied")
        _need(db.execute("SELECT 1 FROM participants WHERE participant_id!='parent' AND state!='exited' LIMIT 1").fetchone() is None, "resume_denied")
        recovery = proof["anchor_recovery"]
        pending = None
        prior_session_id = row["active_scope_session_id"] or row["pending_restart_session_id"]
        if prior_session_id is not None:
            s = db.execute("SELECT * FROM scope_sessions WHERE session_id=?", (prior_session_id,)).fetchone()
            allowed_states = {"open", "sealing"} if row["active_scope_session_id"] is not None else {"interrupted"}
            _need(s is not None and s["state"] in allowed_states, "resume_denied")
            context = json.loads(s["context"])
            expected = {"kind": "restart_from_inputs", "previous_session_id": s["session_id"],
                        **{k: context[k] for k in ("research_generation_id", "input_manifest_sha256", "requirement_registry_sha256")}}
            _need(recovery == expected, "resume_denied")
            pending = s["session_id"]
            db.execute("UPDATE scope_sessions SET state='interrupted' WHERE session_id=?", (pending,))
        else:
            _need(recovery is None and row["pending_restart_session_id"] is None, "resume_denied")
        evidence = hash_payload(proof)
        _need(db.execute("SELECT 1 FROM events WHERE kind='resumed' AND evidence_sha256=?", (evidence,)).fetchone() is None, "resume_denied")
        generation, epoch = row["generation"] + 1, row["admission_epoch"] + 1
        _count(generation, "resume_denied", positive=True)
        _count(epoch, "resume_denied")
        db.execute("UPDATE run_authorization SET generation=?,admission_epoch=?,state='active',stop_code=NULL,active_scope_session_id=NULL,pending_restart_session_id=? WHERE id=1", (generation, epoch, pending))
        db.execute("UPDATE participants SET state='exited',exit_sha256=? WHERE participant_id='parent' AND generation=?", (evidence, row["generation"]))
        db.execute("INSERT INTO participants(generation,participant_id,pid,state,spawn_sha256,inherited_scope_id,admission_epoch) VALUES(?,'parent',?,'running',?,?,?)", (generation, os.getpid(), evidence, row["active_scope_id"], epoch))
        db.execute("INSERT INTO events(kind,evidence_sha256) VALUES('resumed',?)", (evidence,))
        result = _copy(binding)
        result.update(generation=generation, admission_epoch=epoch, active_scope_id=row["active_scope_id"])
    _adopt_v2(binding, result)
    return result


_RECEIPT_ISSUER = object()


class DispatchReceipt:
    """Opaque issuer-bound evidence, not a deserialization or authorization API."""
    __slots__ = ("_binding_json", "_manifest_json", "_issuer")

    def __init__(self, binding, manifest, *, _issuer=None):
        _need(_issuer is _RECEIPT_ISSUER, "transport_receipt_missing")
        object.__setattr__(self, "_binding_json", _json(binding))
        object.__setattr__(self, "_manifest_json", _json(manifest))
        object.__setattr__(self, "_issuer", _issuer)

    def __setattr__(self, name, value):
        raise SpendingStop("transport_receipt_missing")

    @property
    def _binding(self):
        return json.loads(self._binding_json)

    @property
    def _manifest(self):
        return json.loads(self._manifest_json)


class _DispatchCapture:
    __slots__ = ("_binding_json", "_claim_jsons", "_closed", "_lock")

    def __init__(self, binding):
        object.__setattr__(self, "_binding_json", _json(binding))
        object.__setattr__(self, "_claim_jsons", ())
        object.__setattr__(self, "_closed", False)
        object.__setattr__(self, "_lock", threading.Lock())

    def __setattr__(self, name, value):
        raise SpendingStop("transport_receipt_missing")

    @property
    def _binding(self):
        return json.loads(self._binding_json)

    @property
    def _claims(self):
        return [json.loads(value) for value in self._claim_jsons]

    def _add(self, claim):
        with self._lock:
            b = claim["binding"]
            _need(not self._closed and all(b[k] == self._binding[k] for k in
                  ("authorization_id", "manifest_sha256", "pipeline_id", "generation", "admission_epoch", "active_scope_id")), "transport_receipt_missing")
            object.__setattr__(self, "_claim_jsons", (*self._claim_jsons, _json(claim)))

    def receipt(self):
        with self._lock:
            _need(self._closed, "transport_receipt_missing")
            ids = [claim["attempt_id"] for claim in self._claims]
        manifest = _dispatch_receipt_manifest(self._binding, ids)
        return DispatchReceipt(self._binding, manifest, _issuer=_RECEIPT_ISSUER)


@contextmanager
def capture_dispatch_receipts(binding=None):
    """Capture committed physical IDs across copied thread/async contexts.

    Call receipt() only after leaving the capture and joining its workers.
    A separate process captures locally and publishes through its trusted
    producer receipt issuer; this object is not a cross-process reset API.
    """
    b = check_context() if binding is None else check_active(binding, require_operation=True)
    _need(_is_v2(b) and b["active_scope_id"] is not None, "budget_scope_missing")
    capture = _DispatchCapture(b)
    token = _dispatch_captures.set((*_dispatch_captures.get(), capture))
    try:
        yield capture
    finally:
        with capture._lock:
            object.__setattr__(capture, "_closed", True)
        _dispatch_captures.reset(token)


def _dispatch_receipt_manifest(binding, attempt_ids):
    with _tx(binding, fence=False) as (db, _, _):
        attempts = []
        for attempt_id in attempt_ids:
            row = db.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            _need(row is not None and row["scope_id"] == binding["active_scope_id"]
                  and row["generation"] == binding["generation"] and row["admission_epoch"] == binding["admission_epoch"]
                  and row["state"] == "response_observed", "transport_receipt_missing")
            obs = json.loads(row["observation"])
            _need("response_fingerprint" in obs and obs["kind"] == "provider_reported", "transport_receipt_missing")
            attempts.append({"attempt_id": row["attempt_id"], "logical_hash": row["logical_hash"], "ordinal": row["ordinal"],
                             "participant_id": row["participant_id"], "route_id": row["route_id"],
                             "scope_session_id": row["scope_session_id"], "request_sha256": row["request_sha256"],
                             "response_fingerprint": obs["response_fingerprint"], "observation_sha256": row["observation_sha256"],
                             "reserved_max_microusd": row["reserved"], "model_attempt_units": row["model_attempt_units"],
                             "token_envelope_units": row["token_envelope_units"], "catalog_attempt_units": row["catalog_attempt_units"],
                             "followup_attempt_units": row["followup_attempt_units"]})
        return {"schema": "anchor-dispatch-receipt/v1", "authorization_sha256": hash_payload(binding["authorization_id"]),
                "manifest_sha256": binding["manifest_sha256"], "source_sha256": binding["source_sha256"],
                "routes_sha256": binding["routes_sha256"], "pipeline_id": binding["pipeline_id"],
                "scope_id": binding["active_scope_id"], "generation": binding["generation"],
                "admission_epoch": binding["admission_epoch"], "attempts": attempts}


def inspect_dispatch_receipt(receipt):
    """Verify issuer and exact ledger facts before publishing detached metadata.

    Does not authenticate source claims, arbitrary output bytes or a dictionary
    supplied by a caller. The producer separately matches the output bytes to
    the transport-owned fingerprint and seals its source-bound artifact.
    """
    _need(type(receipt) is DispatchReceipt and receipt._issuer is _RECEIPT_ISSUER, "transport_receipt_missing")
    actual = _dispatch_receipt_manifest(receipt._binding, [a["attempt_id"] for a in receipt._manifest["attempts"]])
    _need(actual == receipt._manifest, "transport_receipt_missing")
    return _copy(actual)
