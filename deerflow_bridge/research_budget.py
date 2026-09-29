"""Cross-process research tool budget and negative-result ledger.

The DeerFlow harness can multiply one research request across outer tracks,
dual workflows, phases, and subagents.  Process-local counters cannot bound
that fan-out, so search_tools.py and cached_fetch.py use this small SQLite
ledger for atomic admission.  The module is intentionally stdlib-only and can
be copied next to the deployed ``deerflow_research.py``.

The ledger is enabled only when ``RESEARCH_BUDGET_DB`` is set.  Orchestration
sets one DB path for the whole research stage and a distinct
``RESEARCH_BUDGET_LANE_ID`` for each outer track.  Any ledger failure fails
open (research continues) and emits degraded telemetry instead of turning an
observability/control enhancement into a pipeline outage.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager, closing, contextmanager
from dataclasses import dataclass
from typing import Any, Optional


DEFAULT_ATTEMPTS_GLOBAL = 1800
DEFAULT_SEARCH_GLOBAL = 900
DEFAULT_SEARCH_LANE = 360
DEFAULT_FETCH_GLOBAL = 450
DEFAULT_FETCH_LANE = 180
DEFAULT_NEGATIVE_TTL_SECONDS = 600
DEFAULT_NEGATIVE_RETRIES = 1
DEFAULT_MODEL_CONCURRENCY_GLOBAL = 12
DEFAULT_MODEL_LEASE_WAIT_SECONDS = 10800
DEFAULT_MODEL_LEASE_TTL_SECONDS = 120
DEFAULT_SUBAGENT_CONCURRENCY_GLOBAL = 9
DEFAULT_SUBAGENT_LEASE_WAIT_SECONDS = 10800
DEFAULT_SUBAGENT_LEASE_TTL_SECONDS = 120
DEFAULT_INFLIGHT_TTL_SECONDS = 120
DEFAULT_PROVIDER_FAILURE_THRESHOLD = 5
DEFAULT_PROVIDER_COOLDOWN_SECONDS = 120
DEFAULT_PROVIDER_PROBE_LEASE_SECONDS = 30
# RESEARCH-2: a credential/quota refusal (HTTP 401/402) does not heal in the
# transport cooldown, so the shared circuit stays open this long instead.
QUOTA_COOLDOWN_SECONDS = 3600
# provider_health.last_error of a quota-opened circuit starts with this mark.
# Until open_until passes, another lane's in-flight transport failure or
# success (record_provider_transport_failure / record_provider_success) keeps
# the circuit, its opened_at and its last_error; once it passes,
# provider_circuit_open gives one caller the half-open probe lease, as after a
# transport-opened circuit.  Rows without the mark (every row with
# RESEARCH_SOURCE_TAXONOMY off) are read and updated exactly as before.
QUOTA_ERROR_MARK = "quota refusal: "
_QUOTA_CIRCUIT_OPEN_SQL = (
    f"(provider_health.last_error LIKE '{QUOTA_ERROR_MARK}%' "
    "AND provider_health.open_until > excluded.updated_at)"
)
TELEMETRY_MIN_INTERVAL_SECONDS = 1.0

_TELEMETRY_LOCK = threading.Lock()
_LAST_TELEMETRY_EXPORT: dict[str, float] = {}
_SCHEMA_INIT_LOCK = threading.Lock()
_SCHEMA_INITIALIZED_PATHS: set[str] = set()


@dataclass(frozen=True)
class Admission:
    """Result of one atomic budget admission decision."""

    allowed: bool
    reason: str = ""
    degraded: bool = False


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        value = int(os.environ.get(name, str(default)) or str(default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _db_path() -> str:
    return os.path.expanduser(os.environ.get("RESEARCH_BUDGET_DB", "").strip())


def _model_db_path() -> str:
    raw = os.environ.get("RESEARCH_MODEL_LEASE_DB", "").strip()
    return os.path.expanduser(raw) if raw else _db_path()


def _telemetry_path() -> str:
    raw = os.environ.get("RESEARCH_BUDGET_TELEMETRY_PATH", "").strip()
    return os.path.expanduser(raw) if raw else ""


def _lane_id() -> str:
    lane = os.environ.get("RESEARCH_BUDGET_LANE_ID", "track-1").strip()
    return lane or "track-1"


def enabled() -> bool:
    """Return whether orchestration configured a shared ledger for this run."""

    return bool(_db_path())


def model_leases_enabled() -> bool:
    """Model concurrency remains enforceable when tool budgets are disabled."""
    return bool(_model_db_path())


def subagent_leases_enabled() -> bool:
    """Subagent lifecycle admission shares the application lease database."""
    return bool(_model_db_path())


def _initialize_schema(conn: sqlite3.Connection) -> None:
    """Run one-time DDL/migrations for a ledger path in this process."""
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError as exc:
        if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
            raise
    conn.execute(
        """CREATE TABLE IF NOT EXISTS counters (
               scope TEXT NOT NULL, lane TEXT NOT NULL, name TEXT NOT NULL,
               value INTEGER NOT NULL DEFAULT 0,
               PRIMARY KEY (scope, lane, name)
           )""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS negative_results (
               kind TEXT NOT NULL, key_hash TEXT NOT NULL,
               key_preview TEXT NOT NULL, failures INTEGER NOT NULL,
               retry_admissions INTEGER NOT NULL DEFAULT 0,
               last_failure REAL NOT NULL,
               PRIMARY KEY (kind, key_hash)
           )""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS positive_results (
               kind TEXT NOT NULL, key_hash TEXT NOT NULL, lane TEXT NOT NULL,
               artifact_id TEXT NOT NULL, first_seen REAL NOT NULL,
               last_seen REAL NOT NULL, repeat_hits INTEGER NOT NULL DEFAULT 0,
               PRIMARY KEY (kind, key_hash, lane)
           )""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS global_request_claims (
               kind TEXT NOT NULL, key_hash TEXT NOT NULL,
               owner_lane TEXT NOT NULL, token TEXT PRIMARY KEY,
               acquired_at REAL NOT NULL, expires_at REAL NOT NULL,
               UNIQUE (kind, key_hash)
           )""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS fetched_sources (
               url_hash TEXT NOT NULL, lane TEXT NOT NULL, url TEXT NOT NULL,
               content_sha256 TEXT NOT NULL, content_chars INTEGER NOT NULL,
               title TEXT NOT NULL DEFAULT '', excerpt TEXT NOT NULL DEFAULT '',
               provider TEXT NOT NULL DEFAULT '', receipt_id TEXT NOT NULL DEFAULT '',
               cache_hits INTEGER NOT NULL DEFAULT 0,
               first_seen REAL NOT NULL, last_seen REAL NOT NULL,
               observations INTEGER NOT NULL DEFAULT 1,
               PRIMARY KEY (url_hash, lane)
           )""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS provider_health (
               provider TEXT PRIMARY KEY,
               consecutive_transport_failures INTEGER NOT NULL DEFAULT 0,
               total_transport_failures INTEGER NOT NULL DEFAULT 0,
               opened_at REAL,
               open_until REAL,
               probe_until REAL,
               last_error TEXT NOT NULL DEFAULT '',
               updated_at REAL NOT NULL
           )""")
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(negative_results)")
    }
    if "retry_admissions" not in columns:
        conn.execute(
            "ALTER TABLE negative_results ADD COLUMN "
            "retry_admissions INTEGER NOT NULL DEFAULT 0")
    fetched_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(fetched_sources)")
    }
    for name, ddl in (
        ("provider", "TEXT NOT NULL DEFAULT ''"),
        ("receipt_id", "TEXT NOT NULL DEFAULT ''"),
        ("cache_hits", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if name not in fetched_columns:
            conn.execute(f"ALTER TABLE fetched_sources ADD COLUMN {name} {ddl}")
    provider_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(provider_health)")
    }
    if "probe_until" not in provider_columns:
        conn.execute("ALTER TABLE provider_health ADD COLUMN probe_until REAL")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS metadata (
               key TEXT PRIMARY KEY, value TEXT NOT NULL
           )""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS model_leases (
               token TEXT PRIMARY KEY, lane TEXT NOT NULL, pid INTEGER NOT NULL,
               thread_id INTEGER NOT NULL, weight INTEGER NOT NULL,
               acquired_at REAL NOT NULL, expires_at REAL NOT NULL
           )""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS subagent_leases (
               token TEXT PRIMARY KEY, lane TEXT NOT NULL, pid INTEGER NOT NULL,
               thread_id INTEGER NOT NULL, acquired_at REAL NOT NULL,
               expires_at REAL NOT NULL
           )""")
    conn.execute(
        "INSERT OR IGNORE INTO metadata(key, value) VALUES ('created_at', ?)",
        (str(time.time()),),
    )


def _connect(path: Optional[str] = None) -> sqlite3.Connection:
    path = path or _db_path()
    if not path:
        raise RuntimeError("RESEARCH_BUDGET_DB is not configured")
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0, isolation_level=None)
    try:
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA synchronous=NORMAL")
        identity = os.path.realpath(path)
        if identity not in _SCHEMA_INITIALIZED_PATHS:
            with _SCHEMA_INIT_LOCK:
                if identity not in _SCHEMA_INITIALIZED_PATHS:
                    _initialize_schema(conn)
                    _SCHEMA_INITIALIZED_PATHS.add(identity)
        return conn
    except Exception:
        conn.close()
        raise


def _counter(conn: sqlite3.Connection, scope: str, lane: str, name: str) -> int:
    row = conn.execute(
        "SELECT value FROM counters WHERE scope=? AND lane=? AND name=?",
        (scope, lane, name),
    ).fetchone()
    return int(row[0]) if row else 0


def _increment(
    conn: sqlite3.Connection, scope: str, lane: str, name: str, amount: int = 1
) -> None:
    conn.execute(
        """INSERT INTO counters(scope, lane, name, value) VALUES (?, ?, ?, ?)
           ON CONFLICT(scope, lane, name)
           DO UPDATE SET value=value+excluded.value""",
        (scope, lane, name, int(amount)),
    )


def _deny(conn: sqlite3.Connection, lane: str, reason: str) -> Admission:
    name = "denied_" + reason
    _increment(conn, "global", "", name)
    _increment(conn, "lane", lane, name)
    return Admission(False, reason)


def admit_attempt(tool_kind: str) -> Admission:
    """Atomically admit one search/fetch tool attempt across all processes.

    Attempts include cache hits and negative-cache suppressions.  This bounds
    agent looping independently of network traffic.  If the ledger is disabled
    or unavailable the call is admitted with ``degraded=True``.
    """

    if not enabled():
        return Admission(True)
    lane = _lane_id()
    cap = _env_int("RESEARCH_BUDGET_ATTEMPTS_GLOBAL", DEFAULT_ATTEMPTS_GLOBAL)
    try:
        with closing(_connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if _counter(conn, "global", "", "attempts") >= cap:
                result = _deny(conn, lane, "attempts_global")
            else:
                _increment(conn, "global", "", "attempts")
                _increment(conn, "global", "", f"{tool_kind}_attempts")
                _increment(conn, "lane", lane, "attempts")
                _increment(conn, "lane", lane, f"{tool_kind}_attempts")
                result = Admission(True)
            conn.commit()
        export_telemetry(force=not result.allowed)
        return result
    except Exception as exc:  # ledger is an enhancement: fail open
        _emit_degraded(f"attempt-ledger: {type(exc).__name__}: {exc}")
        return Admission(True, "ledger_unavailable", True)


def admit_network(kind: str) -> Admission:
    """Atomically reserve one real network call under global and lane caps."""

    if not enabled():
        return Admission(True)
    if kind not in {"search", "fetch"}:
        raise ValueError(f"unsupported network budget kind: {kind}")
    lane = _lane_id()
    if kind == "search":
        global_cap = _env_int("RESEARCH_BUDGET_SEARCH_GLOBAL", DEFAULT_SEARCH_GLOBAL)
        lane_cap = _env_int("RESEARCH_BUDGET_SEARCH_LANE", DEFAULT_SEARCH_LANE)
    else:
        global_cap = _env_int("RESEARCH_BUDGET_FETCH_GLOBAL", DEFAULT_FETCH_GLOBAL)
        lane_cap = _env_int("RESEARCH_BUDGET_FETCH_LANE", DEFAULT_FETCH_LANE)
    name = f"{kind}_network"
    try:
        with closing(_connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if _counter(conn, "global", "", name) >= global_cap:
                result = _deny(conn, lane, f"{kind}_global")
            elif _counter(conn, "lane", lane, name) >= lane_cap:
                result = _deny(conn, lane, f"{kind}_lane")
            else:
                _increment(conn, "global", "", name)
                _increment(conn, "lane", lane, name)
                result = Admission(True)
            conn.commit()
        export_telemetry(force=not result.allowed)
        return result
    except Exception as exc:  # ledger is an enhancement: fail open
        _emit_degraded(f"network-ledger: {type(exc).__name__}: {exc}")
        return Admission(True, "ledger_unavailable", True)


def _negative_hash(kind: str, exact_key: str) -> str:
    return hashlib.sha256(f"{kind}\n{exact_key}".encode("utf-8")).hexdigest()


def negative_suppressed(kind: str, exact_key: str) -> bool:
    """Return True after the configured retry count is exhausted within TTL.

    ``RESEARCH_NEGATIVE_CACHE_RETRIES=1`` means: initial empty/dead result,
    allow one more real request, then suppress further exact repeats for ten
    minutes.  Expired rows are deleted atomically and start a fresh cycle.
    """

    if not enabled() or not exact_key:
        return False
    ttl = _env_int(
        "RESEARCH_NEGATIVE_CACHE_TTL_SECONDS", DEFAULT_NEGATIVE_TTL_SECONDS
    )
    retries = _env_int("RESEARCH_NEGATIVE_CACHE_RETRIES", DEFAULT_NEGATIVE_RETRIES)
    if ttl <= 0:
        return False
    key_hash = _negative_hash(kind, exact_key)
    try:
        with closing(_connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT failures, retry_admissions, last_failure FROM negative_results "
                "WHERE kind=? AND key_hash=?",
                (kind, key_hash),
            ).fetchone()
            suppressed = False
            if row:
                failures = int(row[0])
                retry_admissions = int(row[1])
                last_failure = float(row[2])
                if time.time() - last_failure > ttl:
                    conn.execute(
                        "DELETE FROM negative_results WHERE kind=? AND key_hash=?",
                        (kind, key_hash),
                    )
                else:
                    suppressed = failures > retries or retry_admissions >= retries
                    if suppressed:
                        _increment(conn, "global", "", f"{kind}_negative_suppressed")
                        _increment(
                            conn, "lane", _lane_id(), f"{kind}_negative_suppressed"
                        )
                    else:
                        # Claim the bounded retry inside the same write lock so
                        # concurrent subagents cannot all consume "one" retry.
                        conn.execute(
                            "UPDATE negative_results SET retry_admissions="
                            "retry_admissions+1 WHERE kind=? AND key_hash=?",
                            (kind, key_hash),
                        )
            conn.commit()
        export_telemetry(force=suppressed)
        return suppressed
    except Exception as exc:
        _emit_degraded(f"negative-read: {type(exc).__name__}: {exc}")
        return False


def record_negative(kind: str, exact_key: str) -> None:
    """Record one empty/dead network result for an exact request key."""

    if not enabled() or not exact_key:
        return
    key_hash = _negative_hash(kind, exact_key)
    # Keep only a non-reversible identifier. Search queries and signed source
    # URLs can contain sensitive material and do not belong in telemetry state.
    preview = f"sha256:{key_hash}"
    try:
        with closing(_connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO negative_results(
                       kind, key_hash, key_preview, failures,
                       retry_admissions, last_failure
                   ) VALUES (?, ?, ?, 1, 0, ?)
                   ON CONFLICT(kind, key_hash) DO UPDATE SET
                       key_preview=excluded.key_preview,
                       failures=negative_results.failures+1,
                       last_failure=excluded.last_failure""",
                (kind, key_hash, preview, time.time()),
            )
            conn.commit()
        export_telemetry(force=True)
    except Exception as exc:
        _emit_degraded(f"negative-write: {type(exc).__name__}: {exc}")


def clear_negative(kind: str, exact_key: str) -> None:
    """Clear stale negative history after a successful non-empty result."""

    if not enabled() or not exact_key:
        return
    try:
        with closing(_connect()) as conn:
            conn.execute(
                "DELETE FROM negative_results WHERE kind=? AND key_hash=?",
                (kind, _negative_hash(kind, exact_key)),
            )
        export_telemetry(force=True)
    except Exception as exc:
        _emit_degraded(f"negative-clear: {type(exc).__name__}: {exc}")


def positive_repeat(kind: str, exact_key: str) -> Optional[str]:
    """Return the compact artifact id after this lane already saw full content."""
    if not enabled() or not exact_key or os.environ.get(
            "RESEARCH_COMPACT_REPEAT_RESULTS", "false").strip().lower() in {
                "0", "false", "no", "off"}:
        return None
    key_hash = _negative_hash(kind, exact_key)
    lane = _lane_id()
    try:
        with closing(_connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT artifact_id FROM positive_results "
                "WHERE kind=? AND key_hash=? AND lane=?",
                (kind, key_hash, lane),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE positive_results SET repeat_hits=repeat_hits+1, "
                    "last_seen=? WHERE kind=? AND key_hash=? AND lane=?",
                    (time.time(), kind, key_hash, lane),
                )
                _increment(conn, "global", "", f"{kind}_positive_compacted")
                _increment(conn, "lane", lane, f"{kind}_positive_compacted")
            conn.commit()
        export_telemetry(force=False)
        return str(row[0]) if row else None
    except Exception as exc:
        _emit_degraded(f"positive-read: {type(exc).__name__}: {exc}")
        return None


def record_positive(kind: str, exact_key: str) -> str:
    """Mark that the current lane has received one full successful payload."""
    key_hash = _negative_hash(kind, exact_key)
    artifact_id = f"{kind}:{key_hash[:16]}"
    if not enabled() or not exact_key:
        return artifact_id
    lane = _lane_id()
    now = time.time()
    try:
        with closing(_connect()) as conn:
            conn.execute(
                """INSERT OR IGNORE INTO positive_results(
                       kind, key_hash, lane, artifact_id,
                       first_seen, last_seen, repeat_hits
                   ) VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (kind, key_hash, lane, artifact_id, now, now),
            )
        export_telemetry(force=False)
    except Exception as exc:
        _emit_degraded(f"positive-write: {type(exc).__name__}: {exc}")
    return artifact_id


def _source_title(content: str, url: str) -> str:
    """Derive a compact stable title without model or network work."""
    for line in str(content or "").splitlines()[:12]:
        candidate = line.strip().lstrip("#").strip()
        if 3 <= len(candidate) <= 240:
            return candidate
    try:
        from urllib.parse import urlparse

        return (urlparse(url).hostname or url)[:240]
    except Exception:
        return str(url or "")[:240]


def record_fetched_source(
    url: str,
    content: str,
    *,
    provider: str = "",
    cache_hit: bool = False,
) -> None:
    """Persist exact successful fetch provenance across isolated subagents.

    Unlike counters, URLs intentionally remain in the run-local SQLite
    artifact: the outer evidence lane needs them to produce an auditable
    ``sources.json``. They are never copied into generic budget telemetry.
    """
    exact_url = str(url or "").strip()
    body = str(content or "")
    if not enabled() or not exact_url.startswith(("http://", "https://")):
        return
    if len(body.strip()) < 200 or body.lstrip().startswith("Error:"):
        return
    url_hash = hashlib.sha256(exact_url.encode("utf-8")).hexdigest()
    content_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    provider_name = str(provider or "").strip().lower()[:40]
    receipt_id = hashlib.sha256(
        f"{exact_url}\n{content_sha}\n{provider_name}".encode("utf-8")
    ).hexdigest()
    compact = " ".join(body.split())
    now = time.time()
    try:
        with closing(_connect()) as conn:
            conn.execute(
                """INSERT INTO fetched_sources(
                       url_hash, lane, url, content_sha256, content_chars,
                       title, excerpt, provider, receipt_id, cache_hits,
                       first_seen, last_seen, observations
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                   ON CONFLICT(url_hash, lane) DO UPDATE SET
                       url=excluded.url,
                       content_sha256=excluded.content_sha256,
                       content_chars=excluded.content_chars,
                       title=excluded.title,
                       excerpt=excluded.excerpt,
                       provider=CASE
                           WHEN excluded.provider IN ('', 'cache')
                           THEN fetched_sources.provider
                           ELSE excluded.provider
                       END,
                       receipt_id=CASE
                           WHEN excluded.provider IN ('', 'cache')
                                AND fetched_sources.receipt_id != ''
                           THEN fetched_sources.receipt_id
                           ELSE excluded.receipt_id
                       END,
                       cache_hits=fetched_sources.cache_hits+excluded.cache_hits,
                       last_seen=excluded.last_seen,
                       observations=fetched_sources.observations+1""",
                (
                    url_hash,
                    _lane_id(),
                    exact_url,
                    content_sha,
                    len(body),
                    _source_title(body, exact_url),
                    compact[:1200],
                    provider_name,
                    receipt_id,
                    1 if cache_hit else 0,
                    now,
                    now,
                ),
            )
        export_telemetry(force=False)
    except Exception as exc:
        _emit_degraded(f"fetched-source-write: {type(exc).__name__}: {exc}")


def list_fetched_sources(lane: Optional[str] = None) -> list[dict[str, Any]]:
    """Return successful provenance for one lane (current lane by default)."""
    if not enabled():
        return []
    selected_lane = _lane_id() if lane is None else str(lane)
    try:
        with closing(_connect()) as conn:
            if selected_lane == "*":
                rows = conn.execute(
                    """SELECT url, content_sha256, content_chars, title,
                              excerpt, lane, observations, last_seen,
                              provider, receipt_id, cache_hits
                       FROM fetched_sources ORDER BY first_seen, url"""
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT url, content_sha256, content_chars, title,
                              excerpt, lane, observations, last_seen,
                              provider, receipt_id, cache_hits
                       FROM fetched_sources WHERE lane=?
                       ORDER BY first_seen, url""",
                    (selected_lane,),
                ).fetchall()
        return [
            {
                "url": str(row[0]),
                "content_sha256": str(row[1]),
                "content_chars": int(row[2]),
                "title": str(row[3]),
                "excerpt": str(row[4]),
                "lane": str(row[5]),
                "observations": int(row[6]),
                "last_seen": float(row[7]),
                "provider": str(row[8]),
                "receipt_id": str(row[9]),
                "cache_hits": int(row[10]),
            }
            for row in rows
        ]
    except Exception as exc:
        _emit_degraded(f"fetched-source-read: {type(exc).__name__}: {exc}")
        return []


def provider_circuit_open(provider: str) -> bool:
    """Return True while cooling down or another worker owns the half-open probe.

    Once cooldown expires, exactly one caller atomically acquires a short probe
    lease and receives ``False``. Other concurrent callers continue to skip the
    unhealthy provider until that probe records success/failure or its lease
    expires. This prevents a resume wave from stampeding a recovering API.
    """
    name = str(provider or "").strip().lower()
    if not enabled() or not name:
        return False
    try:
        with closing(_connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT consecutive_transport_failures, open_until, probe_until, last_error "
                "FROM provider_health WHERE provider=?",
                (name,),
            ).fetchone()
            now = time.time()
            failures = int(row[0] or 0) if row else 0
            open_until = float(row[1] or 0.0) if row else 0.0
            probe_until = float(row[2] or 0.0) if row else 0.0
            # A quota-opened circuit (RESEARCH-2) records no transport failure
            # but is half-open after its window all the same: one probe first.
            quota_opened = bool(row) and str(row[3] or "").startswith(QUOTA_ERROR_MARK)
            is_open = open_until > now
            if not is_open and (failures > 0 or quota_opened):
                if probe_until > now:
                    is_open = True
                else:
                    lease = _env_int(
                        "RESEARCH_PROVIDER_PROBE_LEASE_SECONDS",
                        DEFAULT_PROVIDER_PROBE_LEASE_SECONDS,
                        minimum=1,
                    )
                    conn.execute(
                        "UPDATE provider_health SET probe_until=?, updated_at=? "
                        "WHERE provider=?",
                        (now + lease, now, name),
                    )
            if is_open:
                _increment(conn, "global", "", f"provider_{name}_circuit_skips")
                _increment(
                    conn, "lane", _lane_id(), f"provider_{name}_circuit_skips"
                )
            conn.commit()
        export_telemetry(force=is_open)
        return is_open
    except Exception as exc:
        _emit_degraded(f"provider-circuit-read: {type(exc).__name__}: {exc}")
        return False


def record_provider_transport_failure(provider: str, error: str) -> bool:
    """Record a transport failure and return whether it opened the circuit."""
    name = str(provider or "").strip().lower()
    if not enabled() or not name:
        return False
    threshold = _env_int(
        "RESEARCH_PROVIDER_FAILURE_THRESHOLD",
        DEFAULT_PROVIDER_FAILURE_THRESHOLD,
        minimum=1,
    )
    cooldown = _env_int(
        "RESEARCH_PROVIDER_COOLDOWN_SECONDS",
        DEFAULT_PROVIDER_COOLDOWN_SECONDS,
        minimum=1,
    )
    now = time.time()
    try:
        with closing(_connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT consecutive_transport_failures FROM provider_health "
                "WHERE provider=?",
                (name,),
            ).fetchone()
            consecutive = (int(row[0]) if row else 0) + 1
            opened = consecutive >= threshold
            conn.execute(
                """INSERT INTO provider_health(
                       provider, consecutive_transport_failures,
                       total_transport_failures, opened_at, open_until, probe_until,
                       last_error, updated_at
                   ) VALUES (?, ?, 1, ?, ?, NULL, ?, ?)
                   ON CONFLICT(provider) DO UPDATE SET
                       consecutive_transport_failures=excluded.consecutive_transport_failures,
                       total_transport_failures=provider_health.total_transport_failures+1,
                       opened_at=CASE WHEN {q} THEN provider_health.opened_at
                                 ELSE excluded.opened_at END,
                       open_until=CASE WHEN {q} THEN provider_health.open_until
                                  ELSE excluded.open_until END,
                       probe_until=NULL,
                       last_error=CASE WHEN {q} THEN provider_health.last_error
                                  ELSE excluded.last_error END,
                       updated_at=excluded.updated_at""".format(q=_QUOTA_CIRCUIT_OPEN_SQL),
                (
                    name,
                    consecutive,
                    now if opened else None,
                    now + cooldown if opened else None,
                    str(error or "")[:500],
                    now,
                ),
            )
            _increment(conn, "global", "", f"provider_{name}_transport_failures")
            _increment(
                conn,
                "lane",
                _lane_id(),
                f"provider_{name}_transport_failures",
            )
            if opened:
                _increment(conn, "global", "", f"provider_{name}_circuit_opens")
                _increment(
                    conn, "lane", _lane_id(), f"provider_{name}_circuit_opens"
                )
            conn.commit()
        export_telemetry(force=True)
        return opened
    except Exception as exc:
        _emit_degraded(f"provider-circuit-write: {type(exc).__name__}: {exc}")
        return False


def record_provider_quota_failure(provider: str, error: str) -> None:
    """Open ``provider``'s shared circuit for QUOTA_COOLDOWN_SECONDS after a
    credential/quota refusal, so every lane skips it (provider_circuit_open);
    its last_error carries QUOTA_ERROR_MARK, so no in-flight transport
    failure or success closes it early, and once the window passes exactly
    one lane probes the provider (the half-open lease) before the others.

    Counts ``provider_<name>_not_configured`` for the run and the lane and
    leaves the transport-failure counters alone.  Never raises: a ledger
    failure is reported as degraded telemetry.
    """
    name = str(provider or "").strip().lower()
    if not enabled() or not name:
        return
    now = time.time()
    try:
        with closing(_connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO provider_health(
                       provider, consecutive_transport_failures,
                       total_transport_failures, opened_at, open_until, probe_until,
                       last_error, updated_at
                   ) VALUES (?, 0, 0, ?, ?, NULL, ?, ?)
                   ON CONFLICT(provider) DO UPDATE SET
                       opened_at=excluded.opened_at,
                       open_until=excluded.open_until,
                       probe_until=NULL,
                       last_error=excluded.last_error,
                       updated_at=excluded.updated_at""",
                (name, now, now + QUOTA_COOLDOWN_SECONDS,
                 (QUOTA_ERROR_MARK + str(error or ""))[:500], now),
            )
            _increment(conn, "global", "", f"provider_{name}_not_configured")
            _increment(conn, "lane", _lane_id(), f"provider_{name}_not_configured")
            conn.commit()
        export_telemetry(force=True)
    except Exception as exc:
        _emit_degraded(f"provider-quota-write: {type(exc).__name__}: {exc}")


def record_provider_success(provider: str) -> None:
    """Reset consecutive failures after a successful provider response."""
    name = str(provider or "").strip().lower()
    if not enabled() or not name:
        return
    try:
        with closing(_connect()) as conn:
            conn.execute(
                """INSERT INTO provider_health(
                       provider, consecutive_transport_failures,
                       total_transport_failures, opened_at, open_until, probe_until,
                       last_error, updated_at
                   ) VALUES (?, 0, 0, NULL, NULL, NULL, '', ?)
                   ON CONFLICT(provider) DO UPDATE SET
                       consecutive_transport_failures=0,
                       opened_at=CASE WHEN {q} THEN provider_health.opened_at ELSE NULL END,
                       open_until=CASE WHEN {q} THEN provider_health.open_until ELSE NULL END,
                       probe_until=NULL,
                       last_error=CASE WHEN {q} THEN provider_health.last_error ELSE '' END,
                       updated_at=excluded.updated_at""".format(q=_QUOTA_CIRCUIT_OPEN_SQL),
                (name, time.time()),
            )
    except Exception as exc:
        _emit_degraded(f"provider-success-write: {type(exc).__name__}: {exc}")


def compact_positive_result(tool: str, artifact_id: str) -> str:
    """Small stable result that prevents the same payload re-entering history."""
    return json.dumps(
        {
            "status": "already_available",
            "tool": tool,
            "artifact_id": artifact_id,
            "message": (
                "Another call in this research lane already returned the full "
                "successful payload. Reuse it when it is in your current context. "
                "If it came from a parallel worker and is not visible here, call "
                "once with a specific revisit_reason to retrieve the cached payload."
            ),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def claim_request(kind: str, exact_key: str) -> str:
    """Atomically claim one global exact network request; ``""`` means wait."""
    token = uuid.uuid4().hex
    if not enabled() or not exact_key:
        return "uncontrolled:" + token
    ttl = _env_int(
        "RESEARCH_INFLIGHT_TTL_SECONDS",
        DEFAULT_INFLIGHT_TTL_SECONDS,
        minimum=15,
    )
    lane = _lane_id()
    key_hash = _negative_hash(kind, exact_key)
    now = time.time()
    try:
        with closing(_connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM global_request_claims WHERE expires_at <= ?", (now,))
            existing = conn.execute(
                "SELECT token FROM global_request_claims "
                "WHERE kind=? AND key_hash=?",
                (kind, key_hash),
            ).fetchone()
            if existing:
                _increment(conn, "global", "", f"{kind}_singleflight_waits")
                _increment(
                    conn, "lane", lane, f"{kind}_singleflight_waits")
                conn.commit()
                return ""
            conn.execute(
                """INSERT INTO global_request_claims(
                       kind, key_hash, owner_lane, token, acquired_at, expires_at
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (kind, key_hash, lane, token, now, now + ttl),
            )
            conn.commit()
        return token
    except Exception as exc:
        _emit_degraded(f"request-claim: {type(exc).__name__}: {exc}")
        return "uncontrolled:" + token


def release_request(token: str) -> None:
    """Release a claim; uncontrolled/degraded claims require no DB mutation."""
    if not token or token.startswith("uncontrolled:") or not enabled():
        return
    try:
        with closing(_connect()) as conn:
            conn.execute(
                "DELETE FROM global_request_claims WHERE token=?", (token,))
    except Exception as exc:
        _emit_degraded(f"request-release: {type(exc).__name__}: {exc}")


def denial_result(tool: str, reason: str, request: str) -> str:
    """Stable tool-result shape returned without invoking a network delegate."""

    return json.dumps(
        {
            "error": "research_budget_exhausted",
            "tool": tool,
            "budget": reason,
            "request": request,
            "results": [],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def negative_result(tool: str, request: str) -> str:
    """Stable result for an exact request suppressed by the negative cache."""

    return json.dumps(
        {
            "error": "research_negative_cache_suppressed",
            "tool": tool,
            "request": request,
            "results": [],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _model_capacity() -> int:
    return _env_int(
        "RESEARCH_MODEL_CONCURRENCY_GLOBAL",
        DEFAULT_MODEL_CONCURRENCY_GLOBAL,
        minimum=1,
    )


def _cleanup_expired_model_leases(conn: sqlite3.Connection, now: float) -> None:
    """Remove abandoned leases after their heartbeat expires.

    The owning process can be SIGKILLed by the outer research watchdog, so a
    normal ``finally`` release cannot be the only recovery path.
    """

    conn.execute("DELETE FROM model_leases WHERE expires_at <= ?", (now,))


def _release_model_lease(token: str) -> None:
    if not token or not model_leases_enabled():
        return
    try:
        with closing(_connect(_model_db_path())) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM model_leases WHERE token=?", (token,))
            conn.commit()
        export_telemetry(force=False)
    except Exception as exc:
        _emit_degraded(f"model-lease-release: {type(exc).__name__}: {exc}")


@contextmanager
def model_call_lease(weight: int = 1):
    """Reserve model-call capacity across every outer research process.

    ``weight`` is conservative by design. A harness-enabled lead stream uses
    ``1 + max_concurrent_subagents`` because those nested calls are created
    inside DeerFlow and cannot acquire bridge leases individually. Bare model
    calls use weight 1. Leases heartbeat while held and expire after an abrupt
    process death, preventing a killed run from deadlocking the next attempt.

    The ledger remains fail-open only when SQLite itself is unavailable. A
    healthy, saturated ledger waits rather than silently violating the global
    concurrency envelope.
    """

    if not model_leases_enabled():
        yield Admission(True)
        return
    capacity = _model_capacity()
    requested = max(1, int(weight or 1))
    if requested > capacity:
        raise ValueError(
            f"model lease weight {requested} exceeds global capacity {capacity}; "
            "reduce actual concurrency before invoking the provider"
        )
    wait_seconds = _env_int(
        "RESEARCH_MODEL_LEASE_WAIT_SECONDS",
        DEFAULT_MODEL_LEASE_WAIT_SECONDS,
        minimum=1,
    )
    ttl_seconds = _env_int(
        "RESEARCH_MODEL_LEASE_TTL_SECONDS",
        DEFAULT_MODEL_LEASE_TTL_SECONDS,
        minimum=15,
    )
    deadline = time.monotonic() + wait_seconds
    wait_started = time.monotonic()
    token = uuid.uuid4().hex
    waited = False
    poll_delay = 0.1
    poll_jitter = 0.85 + (int(token[:4], 16) % 31) / 100.0

    while True:
        now = time.time()
        try:
            with closing(_connect(_model_db_path())) as conn:
                conn.execute("BEGIN IMMEDIATE")
                _cleanup_expired_model_leases(conn, now)
                row = conn.execute(
                    "SELECT COALESCE(SUM(weight), 0) FROM model_leases"
                ).fetchone()
                active = int(row[0]) if row else 0
                if active + requested <= capacity:
                    conn.execute(
                        """INSERT INTO model_leases(
                               token, lane, pid, thread_id, weight,
                               acquired_at, expires_at
                           ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            token,
                            _lane_id(),
                            os.getpid(),
                            threading.get_ident(),
                            requested,
                            now,
                            now + ttl_seconds,
                        ),
                    )
                    _increment(conn, "global", "", "model_lease_acquisitions")
                    _increment(conn, "lane", _lane_id(), "model_lease_acquisitions")
                    if waited:
                        _increment(conn, "global", "", "model_lease_waits")
                        _increment(conn, "lane", _lane_id(), "model_lease_waits")
                        waited_ms = max(
                            1, int((time.monotonic() - wait_started) * 1000))
                        _increment(
                            conn, "global", "", "model_lease_wait_ms", waited_ms)
                        _increment(
                            conn, "lane", _lane_id(),
                            "model_lease_wait_ms", waited_ms)
                    peak_row = conn.execute(
                        "SELECT value FROM metadata WHERE key='model_peak_weight'"
                    ).fetchone()
                    peak = int(peak_row[0]) if peak_row else 0
                    new_active = active + requested
                    if new_active > peak:
                        conn.execute(
                            """INSERT INTO metadata(key, value)
                               VALUES ('model_peak_weight', ?)
                               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                            (str(new_active),),
                        )
                    conn.commit()
                    break
                conn.commit()
        except sqlite3.OperationalError as exc:
            # A busy WAL is contention, not a control-plane outage. Retrying
            # preserves the cap; failing open here would multiply calls at the
            # exact moment several pipelines are racing for admission.
            detail = str(exc).lower()
            if "locked" not in detail and "busy" not in detail:
                _emit_degraded(f"model-lease-acquire: OperationalError: {exc}")
                yield Admission(True, "ledger_unavailable", True)
                return
            waited = True
        except Exception as exc:
            _emit_degraded(f"model-lease-acquire: {type(exc).__name__}: {exc}")
            yield Admission(True, "ledger_unavailable", True)
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"timed out waiting {wait_seconds}s for research model capacity "
                f"({requested} requested, {capacity} global)"
            )
        waited = True
        time.sleep(poll_delay * poll_jitter)
        poll_delay = min(1.0, poll_delay * 1.7)

    stop = threading.Event()

    def _heartbeat() -> None:
        interval = max(5.0, ttl_seconds / 3.0)
        while not stop.wait(interval):
            try:
                with closing(_connect(_model_db_path())) as conn:
                    conn.execute(
                        "UPDATE model_leases SET expires_at=? WHERE token=?",
                        (time.time() + ttl_seconds, token),
                    )
            except Exception as exc:
                _emit_degraded(
                    f"model-lease-heartbeat: {type(exc).__name__}: {exc}"
                )

    heartbeat = threading.Thread(
        target=_heartbeat,
        name="research-model-lease-heartbeat",
        daemon=True,
    )
    heartbeat.start()
    export_telemetry(force=False)
    try:
        yield Admission(True)
    finally:
        stop.set()
        heartbeat.join(timeout=1.0)
        _release_model_lease(token)


@asynccontextmanager
async def async_model_call_lease(weight: int = 1):
    """Async adapter that never blocks the LangGraph event loop while waiting."""

    manager = model_call_lease(weight)
    admission = await asyncio.to_thread(manager.__enter__)
    try:
        yield admission
    except BaseException as exc:
        suppress = await asyncio.to_thread(
            manager.__exit__, type(exc), exc, exc.__traceback__)
        if not suppress:
            raise
    else:
        await asyncio.to_thread(manager.__exit__, None, None, None)


def _subagent_capacity() -> int:
    return _env_int(
        "RESEARCH_GLOBAL_SUBAGENT_CAP",
        DEFAULT_SUBAGENT_CONCURRENCY_GLOBAL,
        minimum=1,
    )


def _cleanup_expired_subagent_leases(
        conn: sqlite3.Connection, now: float) -> None:
    conn.execute("DELETE FROM subagent_leases WHERE expires_at <= ?", (now,))


def _release_subagent_lease(token: str) -> None:
    if not token or not subagent_leases_enabled():
        return
    try:
        with closing(_connect(_model_db_path())) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM subagent_leases WHERE token=?", (token,))
            conn.commit()
        export_telemetry(force=False)
    except Exception as exc:
        _emit_degraded(f"subagent-lease-release: {type(exc).__name__}: {exc}")


@contextmanager
def subagent_call_lease():
    """Reserve one complete harness subagent lifecycle across all pipelines.

    DeerFlow's built-in limiter constrains the tasks spawned by one lead-agent
    response. It does not coordinate simultaneous lead streams, outer tracks,
    or separate pipeline processes. This application-level lease is acquired
    before a subagent builds context and is held through its final result, so
    the configured global cap describes real live subagents rather than a
    per-response approximation.
    """

    if not subagent_leases_enabled():
        yield Admission(True)
        return
    capacity = _subagent_capacity()
    wait_seconds = _env_int(
        "RESEARCH_SUBAGENT_LEASE_WAIT_SECONDS",
        DEFAULT_SUBAGENT_LEASE_WAIT_SECONDS,
        minimum=1,
    )
    ttl_seconds = _env_int(
        "RESEARCH_SUBAGENT_LEASE_TTL_SECONDS",
        DEFAULT_SUBAGENT_LEASE_TTL_SECONDS,
        minimum=15,
    )
    deadline = time.monotonic() + wait_seconds
    wait_started = time.monotonic()
    token = uuid.uuid4().hex
    waited = False
    poll_delay = 0.1
    poll_jitter = 0.85 + (int(token[:4], 16) % 31) / 100.0

    while True:
        now = time.time()
        try:
            with closing(_connect(_model_db_path())) as conn:
                conn.execute("BEGIN IMMEDIATE")
                _cleanup_expired_subagent_leases(conn, now)
                row = conn.execute(
                    "SELECT COUNT(*) FROM subagent_leases"
                ).fetchone()
                active = int(row[0]) if row else 0
                if active < capacity:
                    conn.execute(
                        """INSERT INTO subagent_leases(
                               token, lane, pid, thread_id, acquired_at, expires_at
                           ) VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            token,
                            _lane_id(),
                            os.getpid(),
                            threading.get_ident(),
                            now,
                            now + ttl_seconds,
                        ),
                    )
                    _increment(
                        conn, "global", "", "subagent_lease_acquisitions")
                    _increment(
                        conn, "lane", _lane_id(),
                        "subagent_lease_acquisitions")
                    if waited:
                        _increment(
                            conn, "global", "", "subagent_lease_waits")
                        _increment(
                            conn, "lane", _lane_id(), "subagent_lease_waits")
                        waited_ms = max(
                            1, int((time.monotonic() - wait_started) * 1000))
                        _increment(
                            conn, "global", "",
                            "subagent_lease_wait_ms", waited_ms)
                        _increment(
                            conn, "lane", _lane_id(),
                            "subagent_lease_wait_ms", waited_ms)
                    peak_row = conn.execute(
                        "SELECT value FROM metadata "
                        "WHERE key='subagent_peak_count'"
                    ).fetchone()
                    peak = int(peak_row[0]) if peak_row else 0
                    new_active = active + 1
                    if new_active > peak:
                        conn.execute(
                            """INSERT INTO metadata(key, value)
                               VALUES ('subagent_peak_count', ?)
                               ON CONFLICT(key)
                               DO UPDATE SET value=excluded.value""",
                            (str(new_active),),
                        )
                    conn.commit()
                    break
                conn.commit()
        except sqlite3.OperationalError as exc:
            detail = str(exc).lower()
            if "locked" not in detail and "busy" not in detail:
                _emit_degraded(
                    f"subagent-lease-acquire: OperationalError: {exc}")
                yield Admission(True, "ledger_unavailable", True)
                return
            waited = True
        except Exception as exc:
            _emit_degraded(
                f"subagent-lease-acquire: {type(exc).__name__}: {exc}")
            yield Admission(True, "ledger_unavailable", True)
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"timed out waiting {wait_seconds}s for research subagent "
                f"capacity ({capacity} global)"
            )
        waited = True
        time.sleep(poll_delay * poll_jitter)
        poll_delay = min(1.0, poll_delay * 1.7)

    stop = threading.Event()

    def _heartbeat() -> None:
        interval = max(5.0, ttl_seconds / 3.0)
        while not stop.wait(interval):
            try:
                with closing(_connect(_model_db_path())) as conn:
                    conn.execute(
                        "UPDATE subagent_leases SET expires_at=? WHERE token=?",
                        (time.time() + ttl_seconds, token),
                    )
            except Exception as exc:
                _emit_degraded(
                    f"subagent-lease-heartbeat: {type(exc).__name__}: {exc}")

    heartbeat = threading.Thread(
        target=_heartbeat,
        name="research-subagent-lease-heartbeat",
        daemon=True,
    )
    heartbeat.start()
    export_telemetry(force=False)
    try:
        yield Admission(True)
    finally:
        stop.set()
        heartbeat.join(timeout=1.0)
        _release_subagent_lease(token)


@asynccontextmanager
async def async_subagent_call_lease():
    """Async lifecycle adapter that does not block the agent event loop."""

    manager = subagent_call_lease()
    admission = await asyncio.to_thread(manager.__enter__)
    try:
        yield admission
    except BaseException as exc:
        suppress = await asyncio.to_thread(
            manager.__exit__, type(exc), exc, exc.__traceback__)
        if not suppress:
            raise
    else:
        await asyncio.to_thread(manager.__exit__, None, None, None)


def _snapshot() -> dict[str, Any]:
    tool_path = _db_path()
    model_path = _model_db_path()
    # The tool budget is deliberately per run, while provider/subagent leases
    # are application-global. Read and merge both ledgers; the old single-path
    # lookup silently reported zero model activity whenever those paths differed.
    specs: dict[str, dict[str, Any]] = {}
    if tool_path:
        key = os.path.realpath(tool_path)
        specs[key] = {"path": tool_path, "tool": True, "leases": False}
    if model_path:
        key = os.path.realpath(model_path)
        spec = specs.setdefault(
            key, {"path": model_path, "tool": False, "leases": False})
        spec["leases"] = True

    counter_rows: list[tuple[Any, ...]] = []
    negative_rows: list[tuple[Any, ...]] = []
    provider_rows: list[tuple[Any, ...]] = []
    fetched_source_row: Optional[tuple[Any, ...]] = None
    tool_created: Optional[tuple[Any, ...]] = None
    model_created: Optional[tuple[Any, ...]] = None
    peak_row: Optional[tuple[Any, ...]] = None
    subagent_peak_row: Optional[tuple[Any, ...]] = None
    active_model_row: Optional[tuple[Any, ...]] = None
    active_subagent_row: Optional[tuple[Any, ...]] = None
    for spec in specs.values():
        with closing(_connect(str(spec["path"]))) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if spec["leases"]:
                now = time.time()
                _cleanup_expired_model_leases(conn, now)
                _cleanup_expired_subagent_leases(conn, now)
            counter_rows.extend(conn.execute(
                "SELECT scope, lane, name, value FROM counters "
                "ORDER BY scope, lane, name"
            ).fetchall())
            created = conn.execute(
                "SELECT value FROM metadata WHERE key='created_at'"
            ).fetchone()
            if spec["tool"]:
                tool_created = created
                negative_rows.extend(conn.execute(
                    "SELECT kind, COUNT(*), COALESCE(SUM(failures), 0) "
                    "FROM negative_results GROUP BY kind ORDER BY kind"
                ).fetchall())
                provider_rows.extend(conn.execute(
                    """SELECT provider, consecutive_transport_failures,
                              total_transport_failures, open_until, last_error
                       FROM provider_health ORDER BY provider"""
                ).fetchall())
                fetched_source_row = conn.execute(
                    "SELECT COUNT(DISTINCT url_hash), COUNT(*) "
                    "FROM fetched_sources"
                ).fetchone()
            if spec["leases"]:
                model_created = created
                peak_row = conn.execute(
                    "SELECT value FROM metadata "
                    "WHERE key='model_peak_weight'"
                ).fetchone()
                subagent_peak_row = conn.execute(
                    "SELECT value FROM metadata "
                    "WHERE key='subagent_peak_count'"
                ).fetchone()
                active_model_row = conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(weight), 0) "
                    "FROM model_leases"
                ).fetchone()
                active_subagent_row = conn.execute(
                    "SELECT COUNT(*) FROM subagent_leases"
                ).fetchone()
            conn.commit()
    created = tool_created or model_created
    global_counts: dict[str, int] = {}
    lanes: dict[str, dict[str, int]] = {}
    application_counts: dict[str, int] = {}
    application_lanes: dict[str, dict[str, int]] = {}
    for scope, lane, name, value in counter_rows:
        is_application_counter = str(name).startswith(
            ("model_lease_", "subagent_lease_"))
        if is_application_counter:
            target = (
                application_counts
                if scope == "global"
                else application_lanes.setdefault(lane, {})
            )
        else:
            target = (
                global_counts
                if scope == "global"
                else lanes.setdefault(lane, {})
            )
        target[name] = target.get(name, 0) + int(value)
    return {
        "schema_version": 1,
        "run_id": os.environ.get("RESEARCH_BUDGET_RUN_ID", ""),
        "epoch": os.environ.get("RESEARCH_BUDGET_EPOCH", ""),
        "created_at": float(created[0]) if created else None,
        "updated_at": time.time(),
        "degraded": False,
        "tool_budget_enabled": enabled(),
        "model_leases_enabled": model_leases_enabled(),
        "subagent_leases_enabled": subagent_leases_enabled(),
        "limits": {
            "attempts_global": _env_int(
                "RESEARCH_BUDGET_ATTEMPTS_GLOBAL", DEFAULT_ATTEMPTS_GLOBAL
            ),
            "search_global": _env_int(
                "RESEARCH_BUDGET_SEARCH_GLOBAL", DEFAULT_SEARCH_GLOBAL
            ),
            "search_lane": _env_int(
                "RESEARCH_BUDGET_SEARCH_LANE", DEFAULT_SEARCH_LANE
            ),
            "fetch_global": _env_int(
                "RESEARCH_BUDGET_FETCH_GLOBAL", DEFAULT_FETCH_GLOBAL
            ),
            "fetch_lane": _env_int(
                "RESEARCH_BUDGET_FETCH_LANE", DEFAULT_FETCH_LANE
            ),
            "negative_ttl_seconds": _env_int(
                "RESEARCH_NEGATIVE_CACHE_TTL_SECONDS",
                DEFAULT_NEGATIVE_TTL_SECONDS,
            ),
            "negative_retries": _env_int(
                "RESEARCH_NEGATIVE_CACHE_RETRIES", DEFAULT_NEGATIVE_RETRIES
            ),
            "provider_failure_threshold": _env_int(
                "RESEARCH_PROVIDER_FAILURE_THRESHOLD",
                DEFAULT_PROVIDER_FAILURE_THRESHOLD,
                minimum=1,
            ),
            "provider_cooldown_seconds": _env_int(
                "RESEARCH_PROVIDER_COOLDOWN_SECONDS",
                DEFAULT_PROVIDER_COOLDOWN_SECONDS,
                minimum=1,
            ),
            "model_concurrency_global": _model_capacity(),
            "subagent_concurrency_global": _subagent_capacity(),
        },
        "global": global_counts,
        "lanes": lanes,
        # These counters and peaks intentionally live in the stable,
        # application-wide lease DB. Keep them visibly separate from the
        # run-local tool budget so a later run never presents lifetime totals
        # as its own acquisitions/waits.
        "lease_application_lifetime": {
            "created_at": float(model_created[0]) if model_created else None,
            "global": application_counts,
            "lanes": application_lanes,
        },
        "negative_cache": {
            kind: {"keys": int(keys), "failures": int(failures)}
            for kind, keys, failures in negative_rows
        },
        "fetched_source_provenance": {
            "distinct_urls": (
                int(fetched_source_row[0]) if fetched_source_row else 0
            ),
            "lane_rows": int(fetched_source_row[1]) if fetched_source_row else 0,
        },
        "provider_health": {
            str(provider): {
                "consecutive_transport_failures": int(consecutive),
                "total_transport_failures": int(total),
                "open_until": float(open_until) if open_until else None,
                "circuit_open": bool(open_until and float(open_until) > time.time()),
                "last_error": str(last_error),
            }
            for provider, consecutive, total, open_until, last_error
            in provider_rows
        },
        "model_concurrency": {
            "scope": "application",
            "active_leases": int(active_model_row[0]) if active_model_row else 0,
            "active_weight": int(active_model_row[1]) if active_model_row else 0,
            "peak_weight": int(peak_row[0]) if peak_row else 0,
        },
        "subagent_concurrency": {
            "scope": "application",
            "active_leases": (
                int(active_subagent_row[0]) if active_subagent_row else 0),
            "peak_count": (
                int(subagent_peak_row[0]) if subagent_peak_row else 0),
        },
    }


def _write_json_atomic(path: str, payload: dict[str, Any]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".research-budget-", suffix=".tmp", dir=parent or "."
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def export_telemetry(*, force: bool = False) -> Optional[dict[str, Any]]:
    """Export shared counters, throttling hot cache/read paths.

    Actual delegate outcomes and all denials force a flush.  The one-second
    throttle therefore reduces fsync amplification for rapid cache hits and
    within-call admission checks without losing the final network accounting.
    """

    path = _telemetry_path()
    if not (
            enabled() or model_leases_enabled() or subagent_leases_enabled()
    ) or not path:
        return None
    with _TELEMETRY_LOCK:
        now = time.monotonic()
        last = _LAST_TELEMETRY_EXPORT.get(path, 0.0)
        if not force and now - last < TELEMETRY_MIN_INTERVAL_SECONDS:
            return None
        try:
            payload = _snapshot()
            _write_json_atomic(path, payload)
            _LAST_TELEMETRY_EXPORT[path] = now
            return payload
        except Exception as exc:
            _emit_degraded(f"telemetry-export: {type(exc).__name__}: {exc}")
            return None


def _emit_degraded(message: str) -> None:
    """Best-effort fail-open marker when SQLite or telemetry itself is unavailable."""

    path = _telemetry_path()
    if not path:
        return
    payload: dict[str, Any] = {
        "schema_version": 1,
        "run_id": os.environ.get("RESEARCH_BUDGET_RUN_ID", ""),
        "updated_at": time.time(),
        "degraded": True,
        "degradation": [message[:500]],
        "writer": {"pid": os.getpid(), "thread": threading.get_ident()},
    }
    try:
        _write_json_atomic(path, payload)
    except Exception:
        return
