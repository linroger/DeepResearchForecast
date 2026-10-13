"""Official-data MCP hub — one process-wide stdio client for the six data servers.

WHY THIS MODULE EXISTS
----------------------
Six vendored, unmodified third-party MCP servers in ``datamcps/`` (FRED, BLS,
BIS, IMF, World Bank Data360 ``wb`` and US Gov Open Data ``usgov``) supply the
official quantitative evidence of a run.  Registering them as raw harness MCP
servers was rejected (always-on cwd ``.env`` loading, all-or-nothing tool loss
when one server crashes, spawn failures that hang ``asyncio.run``).  Every
consumer — v3 engine, legacy tools, report side, resolver, all through
``data_sources.py`` — shares this hub instead (design.md §3):

* **One long-lived session per server.**  Spawning costs 0.4 s (BIS) to 21 s
  (Data360 cold imports) while calls are cheap, so sessions are reused.  One
  daemon thread runs one asyncio loop; one *owner task* per server enters and
  exits the transport and ``ClientSession`` in the same task (anyio's
  cancel-scope rule), runs ``initialize`` + ``list_tools`` and then waits for
  either a close request or the end of the child's stdout (a crash).
* **Lazy, with prewarm.**  Nothing spawns at import or construction;
  :meth:`McpHub.start` prewarms in the background and :meth:`McpHub.call`
  starts a server on first use.
* **Failure isolation.**  Every start, call and shutdown wait is bounded
  (start timeout, call timeout, shutdown grace).  A failed server gets ONE
  automatic restart on the next call after a 5 s backoff; after that its
  circuit stays open for the life of the hub.  :meth:`McpHub.call` never
  raises: it returns a :class:`CallResult` whose ``error`` is short and
  redacted.
* **Pacing and key rejection.**  A spec may cap its tool calls per rolling
  minute (FRED: each ``fred_get_series`` costs two upstream requests against
  the key's 120/min); a call that cannot be admitted within its own deadline
  fails fast with a rate-limit reason.  :meth:`McpHub.restart_without` respawns
  a server without a rejected API key (BLS then serves keyless).
* **Hygiene.**  A child gets a small base environment plus its spec's
  allowlisted keys — never the whole parent environment.  It runs in a
  DRF-owned working directory, never the repository root (the us-gov server
  loads ``.env`` from its cwd).  Its stderr goes to
  ``<errlog_dir>/<name>.stderr.log`` or devnull, never to the parent's stdout.
  Secret values and BLS's echoed-key message are redacted from every text and
  error.  Each child leads its own process group; :meth:`McpHub.close` ends
  the sessions, then kills any surviving group, so nothing is orphaned.

The transport is an in-module equivalent of ``mcp.client.stdio.stdio_client``
(same newline-delimited JSON-RPC framing, same new-session spawn).  The SDK
keeps the child process private, and the hub needs its pid for crash detection
and for the process-group kill fallback.

POSIX only (process groups).  Stdlib-only at import; ``mcp`` and ``anyio`` are
imported inside functions, so the module imports in both the backend venv and
the deer-flow venv.
"""

from __future__ import annotations

import asyncio
import atexit
import collections
import concurrent.futures
import contextlib
import contextvars
import dataclasses
import logging
import math
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

logger = logging.getLogger(__name__)

#: Provider ids in registry order (design.md §2).
PROVIDERS: tuple[str, ...] = ("fred", "bls", "bis", "imf", "wb", "usgov")

SETUP_HINT = "run npm run setup:datamcps"
#: A failed server is restarted once, on the first call at least this long after the failure.
RESTART_BACKOFF_S = 5.0
DEFAULT_CALL_TIMEOUT_S = 60.0
#: IMF calls take 30-50 s upstream (≈10 rate-limited requests per call).
IMF_MIN_CALL_TIMEOUT_S = 120.0
#: fetch (FRED) and tsx 4 (BIS) need node >= 18; the us-gov server declares engines node >= 22.
NODE_MIN_MAJOR = 18
USGOV_NODE_MIN_MAJOR = 22
#: Per-address TCP connect attempt (ms) for the node servers' fetch. Node's default of 250 ms
#: ("happy eyeballs") times out every address of a host farther away than that round trip:
#: on 2026-10-14 api.eia.gov and api.fiscaldata.treasury.gov failed with ETIMEDOUT on all four
#: addresses from this machine while curl connected in ~1.5 s, so 43 of 51 us-gov recipes failed.
NODE_CONNECT_ATTEMPT_MS = 2500
USGOV_BASE_MODULES: tuple[str, ...] = ("treasury", "usaspending", "sec", "fdic", "federal-register")
#: Keyed us-gov modules, loaded only when their key is non-empty (a keyless call only yields 401/503 noise).
USGOV_KEYED_MODULES: tuple[tuple[str, str], ...] = (
    ("eia", "EIA_API_KEY"), ("bea", "BEA_API_KEY"), ("census", "CENSUS_API_KEY"))
USGOV_MAX_RESPONSE_BYTES = "40000"
#: FRED tool calls admitted per rolling minute and hub (one hub per process); a fred_get_series
#: costs two upstream requests, so 50 calls stay under the API key's 120 requests a minute.
FRED_CALLS_PER_MINUTE = 50
DATA360_API_BASE_URL = "https://data360api.worldbank.org"
IMF_APP_NAME = "DeepResearchForecast"

_REPO_ROOT = Path(__file__).resolve().parents[1]  # deerflow_bridge/.. and deer-flow/.. alike
_DEFAULT_CACHE_DIR = _REPO_ROOT / "backend" / "uploads" / ".data_cache"
_NODE_FALLBACKS: tuple[str, ...] = ("~/.local/bin/node", "/opt/homebrew/bin/node", "/usr/local/bin/node")

# Parent variables every child inherits: mcp.client.stdio's POSIX defaults, plus
# locale/temp and the network plumbing (proxy, CA bundle) the servers need to
# reach their APIs from a managed network.  Nothing else leaks from the parent.
_BASE_ENV_KEYS: tuple[str, ...] = (
    "HOME", "LOGNAME", "PATH", "SHELL", "TERM", "USER",
    "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
)
_FRED_ENV_KEYS: tuple[str, ...] = (
    "FRED_API_KEY", "FRED_API_TIMEOUT_MS", "FRED_API_MAX_RETRIES", "FRED_API_RETRY_BASE_DELAY_MS",
    "FRED_RATE_LIMIT_PER_MINUTE", "FRED_CACHE_TTL_MS", "FRED_CACHE_MAX_ENTRIES")
_BLS_ENV_KEYS: tuple[str, ...] = ("BLS_API_KEY",)
_USGOV_ENV_KEYS: tuple[str, ...] = (
    "EIA_API_KEY", "BEA_API_KEY", "CENSUS_API_KEY", "DATA_GOV_API_KEY", "SEC_CONTACT_EMAIL")

_ERROR_MAX_CHARS = 300
_STDERR_TAIL_CHARS = 160
#: Safety net against a runaway payload; normal pages are KBs (BIS unbounded daily keys reach ~6.6 MB).
_MAX_TEXT_CHARS = 16_000_000
_ERRLOG_ROTATE_BYTES = 2_000_000
_START_GRACE_S = 5.0     # call() waits start_timeout + this for a starting server
_RESULT_GRACE_S = 5.0    # sync-side margin over the in-loop call deadline
_STDIN_EXIT_GRACE_S = 2.0
_TERM_GRACE_S = 2.0
_MAX_TOOL_PAGES = 20

_SECRET_NAME_MARKERS: tuple[str, ...] = ("KEY", "TOKEN", "SECRET", "PASSWORD")
_MIN_SECRET_LEN = 4
_REDACTED = "[REDACTED]"
# BLS echoes an invalid registration key verbatim: "The key:<key> provided by the User is invalid".
_BLS_KEY_ECHO = re.compile(r"(The key:)\s*\S+")
_URL_SECRET_PARAM = re.compile(
    r"(?i)\b(api_key|apikey|api-key|registrationkey|access_token|token)=[^&\s\"'<>]+")
_NODE_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")
_SAFE_FILE_NAME = re.compile(r"[^A-Za-z0-9._-]")


# =============================================================== public data model

@dataclass(frozen=True)
class ServerSpec:
    """How to launch one stdio MCP server (immutable; built by :func:`default_server_specs`)."""

    name: str                     # 'fred' | 'bls' | 'bis' | 'imf' | 'wb' | 'usgov' | test names
    command: str                  # absolute path (node / venv python / console script)
    args: tuple[str, ...]
    env: Mapping[str, str] = field(hash=False)  # explicit child env additions (keys only when non-empty)
    cwd: str                      # NEVER the repo root; a DRF-owned scratch dir
    start_timeout: float = 45.0
    call_timeout: float = 60.0
    max_concurrency: int = 4
    unavailable_reason: str | None = None   # set by default_server_specs when not runnable
    max_calls_per_minute: int = 0           # tool calls admitted per rolling minute; 0 = unpaced


@dataclass
class CallResult:
    """Outcome of :meth:`McpHub.call`; never an exception."""

    ok: bool                      # transport ok AND not isError
    text: str                     # joined text content ("" on failure)
    error: str | None             # short reason (≤300 chars), secrets redacted
    elapsed_s: float
    structured: Any = None        # structuredContent when present
    is_tool_error: bool = False   # server answered isError=True (text holds its message)


# =============================================================== redaction

def _is_secret_name(name: str) -> bool:
    upper = name.upper()
    return any(marker in upper for marker in _SECRET_NAME_MARKERS)


def _squash(text: str, limit: int) -> str:
    """One line, whitespace collapsed, at most ``limit`` characters."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 3].rstrip() + "..."


class _Redactor:
    """Removes secret env values and BLS's key echo from server output and errors."""

    def __init__(self, secrets: Iterable[str]) -> None:
        unique = {s for s in secrets if isinstance(s, str) and len(s) >= _MIN_SECRET_LEN}
        self._secrets = tuple(sorted(unique, key=len, reverse=True))

    def text(self, value: str) -> str:
        if not value:
            return value
        for secret in self._secrets:
            if secret in value:
                value = value.replace(secret, _REDACTED)
        if "The key:" in value:
            value = _BLS_KEY_ECHO.sub(r"\g<1>" + _REDACTED, value)
        return value

    def error(self, value: object) -> str:
        # Redact before truncating so a secret straddling the cut never leaks a prefix.
        cleaned = _URL_SECRET_PARAM.sub(r"\g<1>=" + _REDACTED, self.text(str(value)))
        return _squash(cleaned, _ERROR_MAX_CHARS)

    def structured(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {key: self.structured(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.structured(item) for item in value]
        return value


# =============================================================== spec resolution

@dataclass(frozen=True)
class _Layout:
    """Where a vendored server lives and how it runs (design.md §2 + notes-*.md)."""

    folder: str
    runtime: str                  # "node" (entry is a script for node) | "venv" (entry is the executable)
    entry: str
    args: tuple[str, ...]
    required: tuple[str, ...]     # build outputs that must exist, relative to the folder
    start_timeout: float
    max_concurrency: int


_LAYOUTS: dict[str, _Layout] = {
    "fred": _Layout("fred-mcp-server-main", "node", "build/index.js", (),
                    ("build/index.js", "node_modules"), 30.0, 4),
    "bls": _Layout("bls_mcp-main", "node", "dist/index.js", (),
                   ("dist/index.js", "node_modules"), 30.0, 2),
    "bis": _Layout("mcp-bis-main", "node", "bin/cli.js", (),
                   ("bin/cli.js", "node_modules/tsx/package.json"), 30.0, 4),
    "imf": _Layout("imf-data-mcp-main", "venv", ".venv/bin/imf-data-mcp", (),
                   (".venv/bin/imf-data-mcp",), 45.0, 1),
    "wb": _Layout("data360-mcp-dev", "venv", ".venv/bin/python",
                  ("-m", "data360.mcp_server", "--transport", "stdio"), (".venv/bin/python",), 60.0, 4),
    "usgov": _Layout("us-gov-open-data-mcp-main", "node", "dist/server.js", (),
                     ("dist/server.js", "node_modules"), 30.0, 4),
}

_NODE_VERSION_CACHE: dict[tuple[str, int, int], tuple[int, int, int]] = {}
_NODE_VERSION_LOCK = threading.Lock()


def _fred_calls_per_minute(source: Mapping[str, str]) -> int:
    raw = (source.get("DATA_SOURCES_FRED_PER_MINUTE") or "").strip()
    if not raw:
        return FRED_CALLS_PER_MINUTE
    if not re.fullmatch(r"\d{1,3}", raw) or not 1 <= int(raw) <= 120:
        logger.warning("DATA_SOURCES_FRED_PER_MINUTE=%r must be 1-120; using %d", raw, FRED_CALLS_PER_MINUTE)
        return FRED_CALLS_PER_MINUTE
    return int(raw)


def _source_path(source: Mapping[str, str], key: str, default: Path) -> Path:
    raw = (source.get(key) or "").strip()
    if not raw:
        return default
    path = Path(os.path.expanduser(raw))
    return path if path.is_absolute() else _REPO_ROOT / path


def _allowed_providers(source: Mapping[str, str]) -> set[str]:
    raw = (source.get("DATA_SOURCES") or "").strip()
    if not raw:
        return set(PROVIDERS)
    names = {part.strip().lower() for part in raw.split(",") if part.strip()}
    unknown = sorted(names - set(PROVIDERS))
    if unknown:
        logger.warning("DATA_SOURCES: ignoring unknown provider(s) %s (known: %s)",
                       ", ".join(unknown), ", ".join(PROVIDERS))
    return names & set(PROVIDERS)


def _call_timeout_from(source: Mapping[str, str]) -> float:
    raw = (source.get("DATA_SOURCES_CALL_TIMEOUT") or "").strip()
    if not raw:
        return DEFAULT_CALL_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        logger.warning("DATA_SOURCES_CALL_TIMEOUT=%r is not a number; using %gs", raw, DEFAULT_CALL_TIMEOUT_S)
        return DEFAULT_CALL_TIMEOUT_S
    if not math.isfinite(value) or value <= 0:
        logger.warning("DATA_SOURCES_CALL_TIMEOUT=%r must be > 0; using %gs", raw, DEFAULT_CALL_TIMEOUT_S)
        return DEFAULT_CALL_TIMEOUT_S
    return min(value, 900.0)


def _prepare_work_dir(work_dir: str | Path | None, cache_dir: Path) -> tuple[str | None, str | None]:
    """Create the children's cwd; never the repo root (the us-gov server reads ``.env`` from its cwd)."""
    target = Path(os.path.expanduser(str(work_dir))) if work_dir else cache_dir / "mcp-cwd"
    if not target.is_absolute():
        target = _REPO_ROOT / target
    target = target.resolve()
    if target == _REPO_ROOT:
        logger.warning("data MCP work dir must not be the repository root; using %s", _DEFAULT_CACHE_DIR / "mcp-cwd")
        target = _DEFAULT_CACHE_DIR / "mcp-cwd"
    for candidate in (target, Path(tempfile.gettempdir()) / "drf-data-mcp" / "mcp-cwd"):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return str(candidate), None
        except OSError as exc:
            logger.warning("data MCP work dir %s is not usable (%s)", candidate, exc.strerror or exc)
    return None, f"no writable working directory for data servers (tried {target})"


def _is_executable_file(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def _resolve_node(source: Mapping[str, str]) -> tuple[str | None, str | None]:
    """Return ``(node_path, None)`` or ``(None, reason)``; explicit DATA_SOURCES_NODE never falls back."""
    explicit = (source.get("DATA_SOURCES_NODE") or "").strip()
    search_path = source.get("PATH") or ""
    if explicit:
        candidate: str | None = os.path.expanduser(explicit)
        if os.sep not in candidate:  # a bare name is looked up on PATH, never relative to the cwd
            candidate = shutil.which(candidate, path=search_path) if search_path else None
        if candidate and _is_executable_file(candidate):
            return os.path.abspath(candidate), None
        return None, f"node not found: DATA_SOURCES_NODE={explicit!r} is not an executable file"
    candidates = [shutil.which("node", path=search_path) if search_path else None]
    home = source.get("HOME") or os.path.expanduser("~")
    for fallback in _NODE_FALLBACKS:
        candidates.append(os.path.join(home, fallback[2:]) if fallback.startswith("~/") else fallback)
    for candidate in candidates:
        if candidate and _is_executable_file(candidate):
            return os.path.abspath(candidate), None
    return None, "node not found (install Node.js >= 22 or set DATA_SOURCES_NODE)"


def _node_version(node: str) -> tuple[tuple[int, int, int] | None, str | None]:
    """``node --version`` once per binary identity (path, mtime, size); failures are not cached."""
    try:
        real = os.path.realpath(node)
        stat = os.stat(real)
    except OSError as exc:
        return None, f"node not usable: {exc.strerror or exc}"
    key = (real, stat.st_mtime_ns, stat.st_size)
    with _NODE_VERSION_LOCK:
        cached = _NODE_VERSION_CACHE.get(key)
    if cached is not None:
        return cached, None
    probe_env = {k: os.environ[k] for k in ("HOME", "PATH") if os.environ.get(k)}
    try:
        proc = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10.0,
                              stdin=subprocess.DEVNULL, env=probe_env, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, _squash(f"node not usable: {type(exc).__name__}: {exc}", _ERROR_MAX_CHARS)
    match = _NODE_VERSION_RE.match((proc.stdout or "").strip())
    if proc.returncode != 0 or not match:
        printed = (proc.stdout or proc.stderr or "").strip()[:40]
        return None, f"node not usable: '{node} --version' printed {printed!r} (exit {proc.returncode})"
    version = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    with _NODE_VERSION_LOCK:
        _NODE_VERSION_CACHE[key] = version
    return version, None


def _node_connect_flags(version: tuple[int, int, int]) -> tuple[str, ...]:
    """The connect-attempt flag (:data:`NODE_CONNECT_ATTEMPT_MS`) on the node versions that
    accept it (20.13+, 22.1+); older nodes keep their default rather than fail on the flag."""
    if version >= (22, 1, 0) or (20, 13, 0) <= version < (21, 0, 0):
        return (f"--network-family-autoselection-attempt-timeout={NODE_CONNECT_ATTEMPT_MS}",)
    return ()


def _stale_venv_reason(executable: Path) -> str | None:
    """A console script whose shebang interpreter is gone (a copied/moved venv) cannot start."""
    try:
        with open(executable, "rb") as handle:
            first = handle.readline(512)
    except OSError as exc:
        return f"not built: {SETUP_HINT} (cannot read {executable.name}: {exc.strerror or exc})"
    if not first.startswith(b"#!"):
        return None
    parts = first[2:].decode("utf-8", "replace").strip().split()
    if parts and os.path.isabs(parts[0]) and not os.path.exists(parts[0]):
        return f"not built: {SETUP_HINT} (stale venv: interpreter {parts[0]} is missing)"
    return None


def _pick_env(source: Mapping[str, str], keys: Iterable[str]) -> dict[str, str]:
    return {key: source[key] for key in keys if source.get(key)}


def _server_env(name: str, source: Mapping[str, str], node: str | None, cache_dir: Path) -> dict[str, str]:
    """Per-server allowlisted child env additions; only non-empty values."""
    env: dict[str, str] = {}
    if _LAYOUTS[name].runtime == "node" and node:
        node_dir = os.path.dirname(node)
        parent_path = source.get("PATH") or ""
        parts = [p for p in parent_path.split(os.pathsep) if p and p != node_dir]
        env["PATH"] = os.pathsep.join([node_dir, *parts])
    if name == "fred":
        env.update(_pick_env(source, _FRED_ENV_KEYS))
    elif name == "bls":
        env.update(_pick_env(source, _BLS_ENV_KEYS))
    elif name == "imf":
        env["IMF_APP_NAME"] = (source.get("IMF_APP_NAME") or "").strip() or IMF_APP_NAME
    elif name == "wb":
        env["DATA360_API_BASE_URL"] = (source.get("DATA360_API_BASE_URL") or "").strip() or DATA360_API_BASE_URL
        env["MCP_ENV"] = "local"
        env["FASTMCP_CHECK_FOR_UPDATES"] = "off"
    elif name == "usgov":
        env.update(_pick_env(source, _USGOV_ENV_KEYS))
        env["MAX_RESPONSE_BYTES"] = USGOV_MAX_RESPONSE_BYTES
        env["XDG_CACHE_HOME"] = str(cache_dir / "usgov-cache")
    return env


def _usgov_modules(source: Mapping[str, str]) -> list[str]:
    modules = list(USGOV_BASE_MODULES)
    modules.extend(module for module, key in USGOV_KEYED_MODULES if (source.get(key) or "").strip())
    return modules


def default_server_specs(*, env: Mapping[str, str] | None = None,
                         datamcps_dir: str | Path | None = None,
                         work_dir: str | Path | None = None) -> dict[str, ServerSpec]:
    """Specs for the six providers, in registry order; never raises, never omits a provider.

    A provider that cannot run (disabled by ``DATA_SOURCES``, not built, no
    suitable node, no work dir) is returned with ``unavailable_reason`` set.
    ``env`` defaults to ``os.environ``; ``datamcps_dir`` overrides
    ``DATA_SOURCES_DIR`` (default ``<repo>/datamcps``); ``work_dir`` overrides
    the children's cwd (default ``<DATA_SOURCES_CACHE_DIR>/mcp-cwd``, where the
    cache dir defaults to ``backend/uploads/.data_cache``).
    """
    source = {str(k): str(v) for k, v in (os.environ if env is None else env).items()}
    allowed = _allowed_providers(source)
    root = (Path(os.path.expanduser(str(datamcps_dir))) if datamcps_dir
            else _source_path(source, "DATA_SOURCES_DIR", _REPO_ROOT / "datamcps"))
    if not root.is_absolute():
        root = _REPO_ROOT / root
    cache_dir = _source_path(source, "DATA_SOURCES_CACHE_DIR", _DEFAULT_CACHE_DIR)
    base_timeout = _call_timeout_from(source)
    usable = [name for name in PROVIDERS if name in allowed]
    cwd, cwd_reason = _prepare_work_dir(work_dir, cache_dir) if usable else (str(cache_dir / "mcp-cwd"), None)

    node: str | None = None
    node_reason: str | None = None
    node_major = 0
    node_text = ""
    node_flags: tuple[str, ...] = ()
    # node is probed only when a node server could actually run (no probing of an absent tree).
    if cwd_reason is None and root.is_dir() and any(_LAYOUTS[name].runtime == "node" for name in usable):
        node, node_reason = _resolve_node(source)
        if node:
            version, version_reason = _node_version(node)
            if version is None:
                node, node_reason = None, version_reason
            else:
                node_major = version[0]
                node_text = "v%d.%d.%d" % version
                node_flags = _node_connect_flags(version)

    specs: dict[str, ServerSpec] = {}
    for name in PROVIDERS:
        layout = _LAYOUTS[name]
        folder = root / layout.folder
        entry = folder / layout.entry
        args: tuple[str, ...] = layout.args
        if layout.runtime == "node":
            command = node or "node"
            args = (*node_flags, str(entry), *args)
            if name == "usgov":
                args = (*args, "--modules", ",".join(_usgov_modules(source)))
        else:
            command = str(entry)

        reason: str | None = None
        if name not in allowed:
            reason = "disabled by DATA_SOURCES"
        elif cwd_reason:
            reason = cwd_reason
        elif not root.is_dir():
            reason = f"datamcps directory not found: {root} (set DATA_SOURCES_DIR)"
        elif layout.runtime == "node" and node is None:
            reason = node_reason
        elif layout.runtime == "node" and node_major < NODE_MIN_MAJOR:
            reason = f"node >= {NODE_MIN_MAJOR} required (found {node_text})"
        elif name == "usgov" and node_major < USGOV_NODE_MIN_MAJOR:
            reason = f"node >= {USGOV_NODE_MIN_MAJOR} required (found {node_text})"
        else:
            missing = [rel for rel in layout.required if not (folder / rel).exists()]
            if missing:
                reason = f"not built: {SETUP_HINT} (missing {layout.folder}/{missing[0]})"
            elif layout.runtime == "venv":
                if not _is_executable_file(str(entry)):
                    reason = f"not built: {SETUP_HINT} ({layout.folder}/{layout.entry} is not executable)"
                elif name == "imf":
                    reason = _stale_venv_reason(entry)

        call_timeout = max(base_timeout, IMF_MIN_CALL_TIMEOUT_S) if name == "imf" else base_timeout
        specs[name] = ServerSpec(
            name=name,
            command=command,
            args=args,
            env=_server_env(name, source, node, cache_dir),
            cwd=cwd or str(cache_dir / "mcp-cwd"),
            start_timeout=layout.start_timeout,
            call_timeout=call_timeout,
            max_concurrency=layout.max_concurrency,
            unavailable_reason=reason,
            max_calls_per_minute=_fred_calls_per_minute(source) if name == "fred" else 0,
        )
    return specs


# =============================================================== stdio transport

class _StartupDeadlineExpired(TimeoutError):
    """A queued owner lost all valid startup demand before spawning a child."""


@dataclass
class _CallBudget:
    deadline: float
    cancelled: bool = False
    cancel_send: Callable[[], None] | None = None

    def expired(self) -> bool:
        return self.cancelled or time.monotonic() >= self.deadline


_CALL_BUDGET: contextvars.ContextVar[_CallBudget | None] = contextvars.ContextVar(
    "data_mcp_call_budget", default=None)


@dataclass
class _Outbound:
    message: Any
    budget: _CallBudget | None


class _BudgetedSendStream:
    """Capture request-task budget at the SDK/shared-writer handoff."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream

    async def send(self, message: Any) -> None:
        budget = _CALL_BUDGET.get() if getattr(message.message.root, "method", None) == "tools/call" else None
        if budget is not None and budget.expired():
            raise TimeoutError("data request deadline exceeded before transport admission")
        await self._stream.send(_Outbound(message, budget))

    def clone(self):
        return type(self)(self._stream.clone())

    async def __aenter__(self):
        await self._stream.__aenter__()
        return self

    async def __aexit__(self, *exc):
        return await self._stream.__aexit__(*exc)

    def __getattr__(self, name):
        return getattr(self._stream, name)


class _ProcInfo:
    """What the owner task learns about its child: pid, exit code, stdout EOF."""

    def __init__(self) -> None:
        self.pid: int | None = None
        self.returncode: int | None = None
        self.eof = asyncio.Event()


def _kill_group(pid: int, sig: int) -> bool:
    try:
        os.killpg(pid, sig)  # the child leads its own session, so pgid == pid
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


async def _shutdown_process(process: Any, info: _ProcInfo) -> None:
    """MCP stdio shutdown: close stdin, wait, SIGTERM the group, wait, SIGKILL it; every wait bounded."""
    import anyio

    if process.stdin is not None:
        with contextlib.suppress(Exception):
            await process.stdin.aclose()
    with anyio.move_on_after(_STDIN_EXIT_GRACE_S):
        await process.wait()
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if process.returncode is not None:
            break
        _kill_group(process.pid, sig)
        with anyio.move_on_after(_TERM_GRACE_S):
            await process.wait()
    # Helpers the server forked into its group must not outlive it.
    _kill_group(process.pid, signal.SIGKILL)
    info.returncode = process.returncode


@asynccontextmanager
async def _stdio_transport(spec: ServerSpec, env: dict[str, str], errlog: Any, info: _ProcInfo, *,
                           can_start: Callable[[], bool] | None = None):
    """Spawn ``spec`` and yield ``(read_stream, write_stream)`` for ``ClientSession``."""
    import anyio
    import anyio.lowlevel
    import mcp.types as types
    from anyio.streams.text import TextReceiveStream
    from mcp.shared.message import SessionMessage

    read_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_reader = anyio.create_memory_object_stream(0)
    write_stream = _BudgetedSendStream(write_stream)
    streams = (read_stream, write_stream, read_writer, write_reader)
    try:
        if can_start is not None and not can_start():
            raise _StartupDeadlineExpired("data request deadline exceeded before process launch")
        process = await anyio.open_process(
            [spec.command, *spec.args], env=env, cwd=spec.cwd, stderr=errlog, start_new_session=True)
    except BaseException:
        for stream in streams:
            await stream.aclose()
        info.eof.set()
        raise
    info.pid = process.pid

    async def stdout_reader() -> None:
        try:
            async with read_writer:
                buffer = ""
                async for chunk in TextReceiveStream(process.stdout, encoding="utf-8", errors="replace"):
                    lines = (buffer + chunk).split("\n")
                    buffer = lines.pop()
                    for line in lines:
                        if not line.strip():
                            continue
                        try:
                            message = types.JSONRPCMessage.model_validate_json(line)
                        except Exception:  # noqa: BLE001 — a stray print() must not kill the session
                            logger.warning("data MCP %s: ignored a non-JSON-RPC stdout line (%d chars)",
                                           spec.name, len(line))
                            continue
                        await read_writer.send(SessionMessage(message))
        except (anyio.ClosedResourceError, anyio.BrokenResourceError):
            await anyio.lowlevel.checkpoint()
        finally:
            info.eof.set()

    async def stdin_writer() -> None:
        try:
            async with write_reader:
                async for outbound in write_reader:
                    budget = outbound.budget
                    if budget is not None and budget.expired():
                        continue
                    payload = outbound.message.message.model_dump_json(by_alias=True, exclude_none=True)
                    encoded = (payload + "\n").encode("utf-8")
                    if budget is None:
                        await process.stdin.send(encoded)
                        continue
                    # Serialization or a queued writer can exhaust the caller's
                    # budget after the SDK accepted the message. Never admit a
                    # fresh write then, and cancel blocked drain independently
                    # of the shared writer and its other requests.
                    if budget.expired():
                        continue
                    try:
                        with anyio.move_on_after(max(0.0, budget.deadline - time.monotonic())) as scope:
                            budget.cancel_send = scope.cancel
                            if budget.expired():
                                continue
                            await process.stdin.send(encoded)
                    finally:
                        budget.cancel_send = None
        except (anyio.ClosedResourceError, anyio.BrokenResourceError):
            await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as task_group, process:
        task_group.start_soon(stdout_reader)
        task_group.start_soon(stdin_writer)
        try:
            yield read_stream, write_stream
        finally:
            with anyio.CancelScope(shield=True):
                await _shutdown_process(process, info)
                for stream in streams:
                    await stream.aclose()


# =============================================================== hub

def _leaf_exception(exc: BaseException) -> BaseException:
    """The first concrete exception inside (nested) exception groups."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _describe_exception(exc: BaseException) -> str:
    exc = _leaf_exception(exc)
    mcp_error = getattr(getattr(exc, "error", None), "message", None)
    if isinstance(mcp_error, str):
        return f"MCP error: {mcp_error}"
    if type(exc).__name__ in ("ClosedResourceError", "BrokenResourceError", "EndOfStream"):
        return "connection to the server was lost"
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


class _Server:
    """Mutable per-server state.  Every field is guarded by ``McpHub._lock``."""

    def __init__(self, spec: ServerSpec, refusal: str | None) -> None:
        self.spec = spec
        reason = spec.unavailable_reason or refusal
        self.state = "unavailable" if reason else "idle"
        self.error: str | None = reason
        self.tools: list[str] = []
        self.ready_s: float | None = None
        self.calls = 0
        self.failures = 0
        self.generation = 0
        self.restarted = False            # the one automatic restart has been used
        self.failed_at: float | None = None
        self.started_at = 0.0
        self.session: Any = None
        self.owner: _Owner | None = None  # the current start attempt (older ones may still be exiting)
        self.ready = threading.Event()    # set whenever the state is not "starting"
        self.ready.set()
        self.semaphore = asyncio.Semaphore(max(1, int(spec.max_concurrency)))

    @property
    def pid(self) -> int | None:
        return self.owner.info.pid if self.owner is not None else None


class _RateWindow:
    """At most ``limit`` admissions in any rolling 60-second window (thread-safe)."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._admitted: collections.deque[float] = collections.deque()
        self._lock = threading.Lock()

    def admit(self, wait_until: float) -> bool:
        """Take a slot, sleeping until one frees; False when that would pass ``wait_until``."""
        while True:
            with self._lock:
                now = time.monotonic()
                while self._admitted and now - self._admitted[0] >= 60.0:
                    self._admitted.popleft()
                if len(self._admitted) < self.limit:
                    self._admitted.append(now)
                    return True
                free_at = self._admitted[0] + 60.0
            if free_at > wait_until:
                return False
            time.sleep(max(0.0, free_at - time.monotonic()))


class _Owner:
    """One start attempt: its owner task, its child and what close() needs to end them."""

    def __init__(self, generation: int) -> None:
        self.generation = generation
        self.info = _ProcInfo()
        self.done = threading.Event()     # set when the owner task has fully finished
        self.cancel: Callable[[], Any] | None = None
        self.close_event: asyncio.Event | None = None
        self.reached_ready = False
        self.start_deadline: float | None = None
        self.prior_state: tuple[str, str | None, bool] | None = None


def _spec_refusal(spec: ServerSpec) -> str | None:
    """Hub-side guard for invariant 5, whatever produced the spec."""
    cwd = (spec.cwd or "").strip()
    if not cwd or not os.path.isabs(cwd):
        return f"invalid spec: cwd must be an absolute directory (got {spec.cwd!r})"
    if Path(cwd).resolve() == _REPO_ROOT:
        return "invalid spec: refusing to run a data server with the repository root as cwd"
    return None


class McpHub:
    """Thread-safe stdio MCP client hub (see the module docstring for the lifecycle).

    ``clock`` drives the restart backoff; timeouts and measurements use real time.
    """

    def __init__(self, specs: Mapping[str, ServerSpec], *, errlog_dir: str | Path | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        servers: dict[str, _Server] = {}
        for name, spec in specs.items():
            if not isinstance(spec, ServerSpec):
                raise TypeError(f"spec for {name!r} must be a ServerSpec, got {type(spec).__name__}")
            if spec.name != name:
                raise ValueError(f"spec key {name!r} does not match spec.name {spec.name!r}")
            servers[name] = _Server(spec, _spec_refusal(spec))
        self._servers = servers
        # Per server name, so a respawn (restart_without) keeps the same budget.
        self._rates = {name: _RateWindow(int(spec.max_calls_per_minute))
                       for name, spec in specs.items() if int(spec.max_calls_per_minute or 0) > 0}
        self._errlog_dir = Path(errlog_dir) if errlog_dir else None
        self._clock = clock
        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._closed = False
        self._inflight: set[concurrent.futures.Future] = set()
        self._owners: set[_Owner] = set()  # every owner task not yet finished, any generation
        self._redact = _Redactor(
            value for spec in specs.values() for key, value in spec.env.items() if _is_secret_name(key))

    # ------------------------------------------------------------ public API

    def start(self, names: Iterable[str] | None = None, *, wait: float | None = None) -> None:
        """Prewarm idle servers in the background (all when ``names`` is None).

        ``wait=None`` returns immediately; ``wait=s`` blocks up to ``s`` seconds
        for the launched servers.  Failed servers are left to the restart policy
        of :meth:`call`; unknown names are ignored.
        """
        if isinstance(names, str):
            names = [names]
        targets = list(self._servers) if names is None else [n for n in names if n in self._servers]
        pending: list[_Server] = []
        with self._lock:
            if self._closed:
                return
            for name in targets:
                srv = self._servers[name]
                if srv.state == "idle":
                    self._launch(srv)
                if srv.state == "starting":
                    if srv.owner is not None:
                        srv.owner.start_deadline = None  # explicit prewarm is independent shared demand
                    pending.append(srv)
        if wait is not None and wait > 0:
            deadline = time.monotonic() + wait
            for srv in pending:
                srv.ready.wait(max(0.0, deadline - time.monotonic()))

    def status(self) -> dict[str, dict]:
        with self._lock:
            return {
                name: {"state": srv.state, "error": srv.error, "tools": list(srv.tools),
                       "ready_s": srv.ready_s, "calls": srv.calls, "failures": srv.failures}
                for name, srv in self._servers.items()
            }

    def tool_names(self, name: str) -> list[str]:
        """Tool names from the latest handshake ([] until first ready; cleared while restarting)."""
        with self._lock:
            srv = self._servers.get(name)
            return list(srv.tools) if srv is not None else []

    def restart_without(self, name: str, keys: Iterable[str]) -> bool:
        """Respawn ``name`` without the child env ``keys`` (e.g. an API key the provider rejected).

        Returns True when the spec carried one of them: the current session is closed and the
        next call starts a fresh child from the reduced spec with a fresh restart circuit (a
        configuration change, not a crash).  False for an unknown server, a closed hub or a
        spec without any of the keys.  A call racing the swap fails once as not ready.
        """
        drop = {key for key in keys if isinstance(key, str)} if not isinstance(keys, str) else {keys}
        with self._lock:
            srv = self._servers.get(name) if isinstance(name, str) else None
            if self._closed or srv is None or not drop & set(srv.spec.env):
                return False
            spec = dataclasses.replace(srv.spec, env={k: v for k, v in srv.spec.env.items() if k not in drop})
            replacement = _Server(spec, _spec_refusal(spec))
            replacement.calls, replacement.failures = srv.calls, srv.failures
            self._servers[name] = replacement
            owner, loop = srv.owner, self._loop
            step = None
            if owner is not None and not owner.done.is_set():
                step = owner.close_event.set if owner.reached_ready and owner.close_event is not None else owner.cancel
            srv.owner = None  # a launch still queued on the loop sees it was superseded and never spawns
            if srv.state != "unavailable":
                srv.state = "closed"
            srv.session = None
            srv.ready.set()
        logger.warning("data MCP %s: respawning without %s", name, ", ".join(sorted(drop & set(srv.spec.env))))
        if loop is not None:
            self._threadsafe(loop, step)
        return True

    def call(self, name: str, tool: str, args: Mapping[str, Any], *,
             timeout: float | None = None, deadline: float | None = None) -> CallResult:
        """Call a tool; optionally bound all admission to one monotonic deadline.

        ``None`` retains the separate startup/call timeouts. An absolute deadline
        also covers restart, event-loop queueing and semaphore admission. Expiry
        cancels this request, never another caller's shared session or startup.
        """
        started = time.monotonic()
        absolute_deadline = None
        try:
            if deadline is not None:
                absolute_deadline = float(deadline)
                if not math.isfinite(absolute_deadline):
                    return self._failure(None, "deadline must be a finite monotonic timestamp", started)
            return self._call(name, tool, args, timeout, started, absolute_deadline)
        except TimeoutError:
            srv = self._servers.get(name) if isinstance(name, str) else None
            return self._failure(srv, "data request deadline exceeded", started, deadline=absolute_deadline)
        except Exception as exc:  # noqa: BLE001 — the contract is a CallResult, always
            logger.warning("data MCP %r.%r: unexpected hub error %s", name, tool, type(exc).__name__)
            srv = self._servers.get(name) if isinstance(name, str) else None
            return self._failure(srv, f"internal hub error: {_describe_exception(exc)}", started,
                                 deadline=absolute_deadline)

    def close(self, timeout: float = 5.0) -> None:
        """End every session (≤ ``timeout`` s), then cancel and kill whatever survives; idempotent."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            loop, thread = self._loop, self._thread
            inflight = list(self._inflight)
            # Every live owner, including an older attempt still exiting after a failure; no new
            # owner can appear once _closed is set (spawn_owner checks it).
            owners = list(self._owners)
            # A ready session closes gracefully; a handshake in progress is simply aborted.
            first_steps = [owner.close_event.set if owner.reached_ready and owner.close_event is not None
                           else owner.cancel for owner in owners]
            for srv in self._servers.values():
                if srv.state != "unavailable":
                    srv.state = "closed"
                srv.session = None
                srv.ready.set()
        if loop is None or thread is None:
            return
        for future in inflight:
            future.cancel()
        for step in first_steps:
            self._threadsafe(loop, step)
        if threading.current_thread() is thread:  # cannot wait for the loop from inside it
            self._threadsafe(loop, loop.stop)
            return
        self._wait_owners(owners, timeout)
        stragglers = [owner for owner in owners if not owner.done.is_set()]
        if stragglers:
            # Killing the child unblocks every await of its owner (stdout EOF, process wait).
            _terminate_groups(owner.info.pid for owner in stragglers if owner.info.pid)
            self._wait_owners(stragglers, _TERM_GRACE_S)
            stuck = [owner for owner in stragglers if not owner.done.is_set()]
            for owner in stuck:
                with self._lock:
                    cancel = owner.cancel
                self._threadsafe(loop, cancel)
            self._wait_owners(stuck, _TERM_GRACE_S)
        # Last line of defence, a no-op for groups already gone: a native cancel can cut an owner's
        # cleanup short (anyio shields do not stop asyncio Task.cancel), leaving forked helpers alive.
        _terminate_groups(owner.info.pid for owner in owners if owner.info.pid)
        self._threadsafe(loop, loop.stop)
        thread.join(timeout=2.0)
        if not thread.is_alive() and all(owner.done.is_set() for owner in owners):
            with contextlib.suppress(Exception):
                loop.close()

    # ------------------------------------------------------------ internals

    @staticmethod
    def _wait_owners(owners: Iterable[_Owner], budget: float) -> None:
        deadline = time.monotonic() + max(0.0, budget)
        for owner in owners:
            owner.done.wait(max(0.0, deadline - time.monotonic()))

    @staticmethod
    def _threadsafe(loop: asyncio.AbstractEventLoop, callback: Callable[[], Any] | None) -> None:
        if callback is None:
            return
        with contextlib.suppress(RuntimeError):  # loop already closed
            loop.call_soon_threadsafe(callback)

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=self._run_loop, args=(loop,), name="drf-data-mcp-hub", daemon=True)
            thread.start()
            self._loop, self._thread = loop, thread
        return self._loop

    @staticmethod
    def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def _launch(self, srv: _Server, deadline: float | None = None) -> None:
        """Schedule a fresh owner task (lock held)."""
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("data request deadline exceeded before server launch")
        loop = self._ensure_loop()
        prior_state = (srv.state, srv.error, srv.restarted)
        srv.generation += 1
        srv.state = "starting"
        srv.error = None
        srv.tools = []
        srv.session = None
        srv.ready_s = None
        srv.started_at = time.monotonic()
        srv.ready.clear()
        owner = srv.owner = _Owner(srv.generation)
        owner.start_deadline, owner.prior_state = deadline, prior_state
        self._owners.add(owner)

        def spawn_owner() -> None:  # runs on the hub loop
            with self._lock:
                if self._closed or srv.owner is not owner:
                    self._owner_finished(owner)
                    return
                if owner.start_deadline is not None and time.monotonic() >= owner.start_deadline:
                    self._restore_unlaunched(srv, owner)
                    self._owner_finished(owner)
                    return
                task = loop.create_task(self._own(srv, owner))
                # A done-callback fires even when the task is cancelled before its first step.
                task.add_done_callback(lambda _task: self._owner_finished(owner))
                owner.cancel = task.cancel

        try:
            loop.call_soon_threadsafe(spawn_owner)
        except RuntimeError as exc:
            self._mark_failed(srv, owner.generation, f"cannot schedule server start: {exc}")
            self._owner_finished(owner)

    def _restore_unlaunched(self, srv: _Server, owner: _Owner) -> None:
        """An expired queued launch must not consume the shared restart circuit."""
        with self._lock:
            if srv.owner is owner and srv.state == "starting" and owner.info.pid is None:
                srv.state, srv.error, srv.restarted = owner.prior_state
                srv.ready.set()

    def _owner_finished(self, owner: _Owner) -> None:
        with self._lock:
            self._owners.discard(owner)
        owner.done.set()

    def _mark_failed(self, srv: _Server, generation: int, reason: str) -> None:
        with self._lock:
            if srv.generation != generation:
                return
            srv.session = None
            if srv.state != "closed":
                srv.state = "failed"
                srv.error = self._redact.error(reason)
                srv.failed_at = self._clock()
            srv.ready.set()

    def _open_errlog(self, name: str, generation: int) -> tuple[Any, Path | None, int]:
        if self._errlog_dir is not None:
            path = self._errlog_dir / f"{_SAFE_FILE_NAME.sub('_', name)}.stderr.log"
            try:
                self._errlog_dir.mkdir(parents=True, exist_ok=True)
                with contextlib.suppress(FileNotFoundError):
                    if path.stat().st_size > _ERRLOG_ROTATE_BYTES:
                        os.replace(path, path.with_name(path.name + ".1"))
                handle = open(path, "a", encoding="utf-8", errors="replace")
                stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                handle.write(f"\n--- {stamp} start {name} (attempt {generation}) ---\n")
                handle.flush()
                return handle, path, handle.tell()
            except OSError as exc:
                logger.warning("data MCP %s: errlog %s unusable (%s); stderr discarded",
                               name, path, exc.strerror or exc)
        return open(os.devnull, "w", encoding="utf-8"), None, 0

    @staticmethod
    def _stderr_tail(path: Path | None, offset: int) -> str:
        """Last stderr lines written since this attempt started (for actionable errors)."""
        if path is None:
            return ""
        try:
            with open(path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(offset, size - 4096))
                chunk = handle.read().decode("utf-8", "replace")
        except OSError:
            return ""
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        return _squash(" | ".join(lines[-2:]), _STDERR_TAIL_CHARS) if lines else ""

    def _child_env(self, spec: ServerSpec) -> dict[str, str]:
        env = {key: os.environ[key] for key in _BASE_ENV_KEYS
               if os.environ.get(key) and not os.environ[key].startswith("()")}
        env.update({str(k): str(v) for k, v in spec.env.items() if v not in (None, "")})
        return env

    async def _own(self, srv: _Server, owner: _Owner) -> None:
        """Owner task: spawn → initialize → list_tools → serve until close or crash → clean exit."""
        spec = srv.spec
        generation = owner.generation
        close_event = asyncio.Event()
        info = owner.info
        failure: str | None = None
        recorded = False
        reached_ready = False
        errlog, errlog_path, errlog_offset = None, None, 0

        def can_start() -> bool:
            with self._lock:
                if self._closed or srv.owner is not owner:
                    return False
                if owner.start_deadline is not None and time.monotonic() >= owner.start_deadline:
                    # Retire under this same lock: a later valid adopter must
                    # observe idle/failed and start a new owner, never get
                    # overwritten by the rejected owner's exception cleanup.
                    self._restore_unlaunched(srv, owner)
                    return False
                return True

        def record(reason: str) -> None:
            nonlocal recorded
            if reason.startswith("server exited") and info.returncode is not None:
                reason += f" (exit code {info.returncode})"
            tail = self._stderr_tail(errlog_path, errlog_offset)
            if tail:
                reason += f"; stderr: {tail}"
            logger.warning("data MCP %s: %s", spec.name, self._redact.error(reason))
            self._mark_failed(srv, generation, reason)
            recorded = True

        try:
            with self._lock:
                if srv.generation != generation or self._closed:
                    return
                owner.close_event = close_event
            if not can_start():
                raise _StartupDeadlineExpired
            errlog, errlog_path, errlog_offset = self._open_errlog(spec.name, generation)
            from mcp import ClientSession

            async with AsyncExitStack() as stack:
                read, write = await stack.enter_async_context(
                    _stdio_transport(spec, self._child_env(spec), errlog, info, can_start=can_start))
                session = await stack.enter_async_context(ClientSession(read, write))
                try:
                    tools = await asyncio.wait_for(self._handshake(session), spec.start_timeout)
                except TimeoutError:
                    # Record now: the shutdown of a hung child takes seconds and callers are waiting.
                    failure = f"start timeout after {spec.start_timeout:g}s"
                    record(failure)
                    raise
                with self._lock:
                    if srv.generation != generation or self._closed:
                        return
                    srv.session = session
                    srv.tools = tools
                    srv.state = "ready"
                    srv.ready_s = round(time.monotonic() - srv.started_at, 3)
                    srv.ready.set()
                    reached_ready = owner.reached_ready = True
                logger.info("data MCP %s ready in %.2fs (%d tools, pid %s)",
                            spec.name, srv.ready_s, len(tools), info.pid)
                await self._serve_until_closed(close_event, info)
        except _StartupDeadlineExpired:
            self._restore_unlaunched(srv, owner)
        except asyncio.CancelledError:  # only close() cancels an owner; that is not a server failure
            if not self._closed:
                failure = failure or ("session cancelled" if reached_ready else "start cancelled")
        except BaseException as exc:  # noqa: BLE001 — isolate this server only
            failure = failure or self._classify_failure(exc, info, reached_ready)
        finally:
            if failure is None and reached_ready and not close_event.is_set() and not self._closed:
                failure = "server exited unexpectedly"  # the session ended without a close request
            if failure is not None:
                if not recorded:
                    record(failure)
            else:
                with self._lock:
                    if srv.generation == generation:
                        srv.session = None
                        srv.ready.set()
            if errlog is not None:
                with contextlib.suppress(OSError):
                    errlog.close()

    @staticmethod
    def _classify_failure(exc: BaseException, info: _ProcInfo, reached_ready: bool) -> str:
        leaf = _leaf_exception(exc)
        if isinstance(leaf, OSError) and info.pid is None:
            return f"spawn failed: {_describe_exception(leaf)}"
        if reached_ready:
            return "server exited unexpectedly" if info.eof.is_set() else f"session failed: {_describe_exception(exc)}"
        if info.eof.is_set():
            return "server exited during startup"
        return f"start failed: {_describe_exception(exc)}"

    @staticmethod
    async def _handshake(session: Any) -> list[str]:
        import mcp.types as types

        await session.initialize()
        names: list[str] = []
        cursor: str | None = None
        for _ in range(_MAX_TOOL_PAGES):
            if cursor:
                listed = await session.list_tools(params=types.PaginatedRequestParams(cursor=cursor))
            else:
                listed = await session.list_tools()
            names.extend(tool.name for tool in listed.tools)
            cursor = getattr(listed, "nextCursor", None)
            if not cursor:
                break
        return names

    @staticmethod
    async def _serve_until_closed(close_event: asyncio.Event, info: _ProcInfo) -> None:
        """Hold the session until a close request or the child's stdout EOF (a crash)."""
        closing = asyncio.ensure_future(close_event.wait())
        exited = asyncio.ensure_future(info.eof.wait())
        try:
            await asyncio.wait({closing, exited}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for waiter in (closing, exited):
                waiter.cancel()
            await asyncio.gather(closing, exited, return_exceptions=True)

    def _admit(self, srv: _Server, deadline: float | None = None) -> str | None:
        """Gate a call (lock held): launch idle servers, apply restart backoff / circuit."""
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("data request deadline exceeded before admission")
        if self._closed:
            return "data hub is closed"
        if srv.state == "unavailable":
            return srv.error or "unavailable"
        if srv.state == "idle":
            self._launch(srv, deadline)
        elif srv.state == "failed":
            if srv.restarted:
                return f"circuit open: {srv.error}"
            remaining = RESTART_BACKOFF_S - (self._clock() - (srv.failed_at or 0.0))
            if remaining > 0:
                return f"{srv.error} (automatic restart allowed in {math.ceil(remaining)}s)"
            logger.warning("data MCP %s: restarting once after failure: %s", srv.spec.name, srv.error)
            self._launch(srv, deadline)
            srv.restarted = True
        elif srv.state == "starting" and srv.owner is not None:
            # Startup is shared. A longer-lived or unbounded caller may adopt a
            # queued owner, so one expired caller cannot retire valid demand.
            if deadline is None:
                srv.owner.start_deadline = None
            elif srv.owner.start_deadline is not None:
                srv.owner.start_deadline = max(srv.owner.start_deadline, deadline)
        return None

    @contextlib.contextmanager
    def _call_lock(self, deadline: float | None):
        if deadline is None:
            with self._lock:
                yield
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self._lock.acquire(timeout=remaining):
            raise TimeoutError("data request deadline exceeded waiting for admission")
        try:
            yield
        finally:
            self._lock.release()

    def _failure(self, srv: _Server | None, reason: str, started: float, *,
                 deadline: float | None = None) -> CallResult:
        self._record_failure(srv, deadline)
        return CallResult(ok=False, text="", error=self._redact.error(reason),
                          elapsed_s=round(time.monotonic() - started, 3))

    def _record_failure(self, srv: _Server | None, deadline: float | None) -> None:
        if srv is not None:
            acquired = self._lock.acquire() if deadline is None else self._lock.acquire(
                timeout=max(0.0, deadline - time.monotonic()))
            if acquired:
                try:
                    srv.failures += 1
                finally:
                    self._lock.release()

    def _discard_inflight(self, future: concurrent.futures.Future) -> None:
        with self._lock:
            self._inflight.discard(future)

    def _call(self, name: str, tool: str, args: Mapping[str, Any] | None,
              timeout: float | None, started: float, deadline: float | None = None) -> CallResult:
        srv = self._servers.get(name) if isinstance(name, str) else None

        def fail(reason: str) -> CallResult:
            return self._failure(srv, reason, started, deadline=deadline)

        if srv is None:
            return fail(f"unknown data server {name!r} (known: {', '.join(self._servers)})")
        with self._call_lock(deadline):
            srv.calls += 1
        if not isinstance(tool, str) or not tool.strip():
            return fail("tool name must be a non-empty string")
        if args is None:
            args = {}
        if not isinstance(args, Mapping):
            return fail(f"arguments must be a JSON object, got {type(args).__name__}")
        if self._thread is not None and threading.current_thread() is self._thread:
            return fail("call() must not run on the data hub's own event-loop thread")
        try:
            limit = float(srv.spec.call_timeout if timeout is None else timeout)
        except (TypeError, ValueError):
            limit = math.nan
        if not math.isfinite(limit) or limit <= 0:
            return fail(f"timeout must be > 0 seconds, got {timeout!r}")

        with self._call_lock(deadline):
            refusal = self._admit(srv, deadline)
        if refusal:
            return fail(refusal)
        # After admission, so a refused call (closed hub, unavailable server, open circuit) neither
        # spends one of the minute's slots nor waits for a freed one.
        rate = self._rates.get(name)
        if rate is not None and not rate.admit(started + limit if deadline is None else min(deadline, started + limit)):
            return fail(f"local rate limit of {rate.limit} {name} calls per minute reached within the call "
                        "deadline; retry later")
        start_budget = srv.spec.start_timeout + _START_GRACE_S
        if deadline is not None:
            start_budget = min(start_budget, max(0.0, deadline - time.monotonic()))
        if not srv.ready.wait(start_budget):
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("data request deadline exceeded during startup")
            return fail(f"server still starting after {start_budget:g}s")
        with self._call_lock(deadline):
            if self._closed:
                return fail("data hub is closed")
            if srv.state != "ready" or srv.session is None:
                return fail(srv.error or f"server not ready ({srv.state})")
            tools = list(srv.tools)
            if tools and tool not in tools:
                return fail(f"unknown tool {tool!r} for {name}; available: {', '.join(tools)}")
            # Submitted and registered under the lock, so close() either refuses this call or cancels it.
            invocation = self._invoke(srv, srv.session, tool, dict(args), limit, deadline)
            try:
                future = asyncio.run_coroutine_threadsafe(invocation, self._loop)
            except RuntimeError as exc:
                invocation.close()
                return fail(f"data hub loop unavailable: {exc}")
            self._inflight.add(future)
            if deadline is not None:
                # Cancellation callbacks can run on the waiting caller's thread.
                # Defer lock-taking cleanup to the loop, never past its deadline.
                future.add_done_callback(lambda done: self._threadsafe(
                    self._loop, lambda: self._discard_inflight(done)))
        try:
            result_budget = limit + _RESULT_GRACE_S
            if deadline is not None:
                result_budget = min(result_budget, max(0.0, deadline - time.monotonic()))
            result = future.result(result_budget)
        except concurrent.futures.CancelledError:
            return fail("call cancelled: data hub is closing")
        except TimeoutError:
            future.cancel()
            if deadline is not None and time.monotonic() >= deadline:
                return fail("data request deadline exceeded")
            return fail(f"tool call timed out after {limit:g}s")
        finally:
            if deadline is None:
                self._discard_inflight(future)
        if deadline is not None and time.monotonic() >= deadline:
            return fail("data request deadline exceeded")
        result.elapsed_s = round(time.monotonic() - started, 3)
        if not result.ok:
            self._record_failure(srv, deadline)
        return result

    async def _invoke(self, srv: _Server, session: Any, tool: str, arguments: dict[str, Any],
                      limit: float, deadline: float | None = None) -> CallResult:
        """Runs on the hub loop: slot (semaphore) + call, both inside one ``limit`` deadline."""
        if deadline is not None:
            return await self._invoke_until(srv, session, tool, arguments, min(deadline, time.monotonic() + limit))
        loop = asyncio.get_running_loop()
        begun = loop.time()
        try:
            await asyncio.wait_for(srv.semaphore.acquire(), limit)
        except TimeoutError:
            return CallResult(ok=False, text="", elapsed_s=0.0, error=self._redact.error(
                f"timed out after {limit:g}s waiting for a free slot "
                f"(max {srv.spec.max_concurrency} concurrent calls)"))
        try:
            remaining = max(0.001, limit - (loop.time() - begun))
            result = await asyncio.wait_for(session.call_tool(tool, arguments), remaining)
        except TimeoutError:
            return CallResult(ok=False, text="", elapsed_s=0.0,
                              error=f"tool call timed out after {limit:g}s")
        except Exception as exc:  # noqa: BLE001 — mapped to an error result
            return CallResult(ok=False, text="", elapsed_s=0.0, error=self._redact.error(_describe_exception(exc)))
        finally:
            srv.semaphore.release()
        return self._to_call_result(result)

    async def _invoke_until(self, srv: _Server, session: Any, tool: str,
                            arguments: dict[str, Any], deadline: float) -> CallResult:
        """Recheck on the loop and inside semaphore admission, never grant 1ms after expiry."""
        acquired = False
        budget = _CallBudget(deadline)
        token = _CALL_BUDGET.set(budget)
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            async with asyncio.timeout(remaining):
                await srv.semaphore.acquire()
                acquired = True
                if time.monotonic() >= deadline:
                    raise TimeoutError
                # Await directly in this task: a newly scheduled call_tool task
                # must not get a fresh opportunity to dispatch after expiry.
                result = await session.call_tool(tool, arguments)
            if time.monotonic() >= deadline:
                raise TimeoutError
            return self._to_call_result(result)
        except TimeoutError:
            return CallResult(ok=False, text="", elapsed_s=0.0, error="data request deadline exceeded")
        except Exception as exc:  # noqa: BLE001 — preserve the CallResult boundary
            return CallResult(ok=False, text="", elapsed_s=0.0,
                              error=self._redact.error(_describe_exception(exc)))
        finally:
            budget.cancelled = True
            if budget.cancel_send is not None:
                budget.cancel_send()
            _CALL_BUDGET.reset(token)
            if acquired:
                srv.semaphore.release()

    def _to_call_result(self, result: Any) -> CallResult:
        parts: list[str] = []
        for block in getattr(result, "content", None) or []:
            text = getattr(block, "text", None)
            if not isinstance(text, str):
                text = getattr(getattr(block, "resource", None), "text", None)
            if isinstance(text, str):
                parts.append(text)
        text = "\n".join(parts)
        if len(text) > _MAX_TEXT_CHARS:
            return CallResult(ok=False, text="", elapsed_s=0.0, error=(
                f"response too large ({len(text)} chars > {_MAX_TEXT_CHARS}); narrow the request"))
        text = self._redact.text(text)
        structured = self._redact.structured(getattr(result, "structuredContent", None))
        if getattr(result, "isError", False):
            message = text.strip() or "the tool reported an error without a message"
            return CallResult(ok=False, text=text, error=self._redact.error(message), elapsed_s=0.0,
                              structured=structured, is_tool_error=True)
        return CallResult(ok=True, text=text, error=None, elapsed_s=0.0, structured=structured)


def _terminate_groups(pids: Iterable[int]) -> None:
    """SIGTERM each surviving process group, then SIGKILL whatever is left after a short grace."""
    alive = [pid for pid in pids if _kill_group(pid, signal.SIGTERM)]
    deadline = time.monotonic() + 1.0
    while alive and time.monotonic() < deadline:
        time.sleep(0.05)
        alive = [pid for pid in alive if _kill_group(pid, 0)]
    for pid in alive:
        _kill_group(pid, signal.SIGKILL)


# =============================================================== process singleton

_SINGLETON: McpHub | None = None
_SINGLETON_PID: int | None = None
_SINGLETON_LOCK = threading.Lock()
_ATEXIT_REGISTERED = False
_INTERPRETER_EXITING = False


def get_hub(*, env: Mapping[str, str] | None = None) -> McpHub:
    """Process-wide lazy hub over :func:`default_server_specs` (``env`` applies at first creation).

    Server stderr goes to ``<DATA_SOURCES_CACHE_DIR>/mcp-logs``.  The hub is
    closed at interpreter exit; a forked child gets its own hub.
    """
    global _SINGLETON, _SINGLETON_PID, _ATEXIT_REGISTERED
    with _SINGLETON_LOCK:
        hub = _SINGLETON
        if hub is not None and _SINGLETON_PID == os.getpid() and (not hub._closed or _INTERPRETER_EXITING):
            return hub
        source = {str(k): str(v) for k, v in (os.environ if env is None else env).items()}
        errlog_dir = _source_path(source, "DATA_SOURCES_CACHE_DIR", _DEFAULT_CACHE_DIR) / "mcp-logs"
        hub = McpHub(default_server_specs(env=source), errlog_dir=errlog_dir)
        if _INTERPRETER_EXITING:
            hub.close()  # too late to spawn children that nothing would reap
        _SINGLETON, _SINGLETON_PID = hub, os.getpid()
        if not _ATEXIT_REGISTERED:
            atexit.register(_close_singleton_at_exit)
            _ATEXIT_REGISTERED = True
        return hub


def reset_hub_for_tests() -> None:
    """Close and forget the singleton (and the node-version cache)."""
    global _SINGLETON, _SINGLETON_PID
    with _SINGLETON_LOCK:
        hub, _SINGLETON, _SINGLETON_PID = _SINGLETON, None, None
    if hub is not None:
        hub.close(timeout=2.0)
    with _NODE_VERSION_LOCK:
        _NODE_VERSION_CACHE.clear()


def _close_singleton_at_exit() -> None:
    global _INTERPRETER_EXITING
    with _SINGLETON_LOCK:
        _INTERPRETER_EXITING = True
        hub = _SINGLETON if _SINGLETON_PID == os.getpid() else None
    if hub is not None:
        hub.close(timeout=3.0)
