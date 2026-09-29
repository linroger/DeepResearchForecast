"""Hermetic test-process harness (INFRA-12).

Stdlib-only helpers that ``backend/tests/conftest.py`` uses to make the offline
suite independent of the developer's shell and unable to reach the network:

* ``scrub_ambient_env`` pops every env name that steers DRF code (Config knobs,
  documented .env names, credentials, egress endpoints) *before* any ``app``
  module is imported, so an exported ``LLM_PROVIDER`` or API key cannot change
  test behaviour.  Names are popped, not blanked: DRF reads
  ``os.environ.get(NAME, default)`` and treats ``''`` as a real value.
* ``env_mutations`` backs the collection-time check that importing test
  modules never mutates ``os.environ`` (the sim scripts used to inject the
  developer's .env this way).
* ``EgressGuard`` refuses TCP connects, DNS lookups of real hostnames and
  provider-CLI / pipeline-child spawns from the end of collection to the end
  of the session (per-test markers widen the policy, integration tests are
  exempt), and records every refusal so a test that swallows the error still
  fails.
* ``reset_process_globals`` clears module-level breakers and caches that would
  otherwise leak from one test into the next.

Nothing here imports ``app``: it runs before the application is importable.
"""

from __future__ import annotations

import collections.abc
import functools
import importlib.util
import inspect
import ipaddress
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Any, Callable, Mapping, MutableMapping, Optional

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_TESTS_DIR)
REPO_ROOT = os.path.dirname(_BACKEND_DIR)

# ---------------------------------------------------------------------------
# Ambient environment scrub
# ---------------------------------------------------------------------------

# Infrastructure names the scrub never touches even when a rule below matches
# them: the interpreter, the venv, locale/timezone, CI metadata and the user's
# proxy settings (a proxy only matters for traffic the egress guard refuses).
_PROTECTED_NAMES = frozenset({
    "PATH", "HOME", "TMPDIR", "TZ", "LANG", "VIRTUAL_ENV", "CI",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "no_proxy", "all_proxy",
})
_PROTECTED_PREFIXES = ("LC_", "UV_", "PYTHON", "GITHUB_")

# Names that point a client at a remote service or select a networked backend.
_EGRESS_NAMES = frozenset({
    "OPENAI_BASE_URL", "OPENAI_API_BASE", "OPENAI_ORG_ID", "OPENAI_ORGANIZATION",
    "ANTHROPIC_BASE_URL", "FALKORDB_HOST", "FALKORDB_PORT",
    "RESEARCH_BUDGET_DB", "RESEARCH_MODEL_LEASE_DB", "HF_ENDPOINT",
})
_EGRESS_PREFIXES = ("LLM_FALLBACK_", "LLM_FAST_", "DRF_MCP_")
_EGRESS_SUFFIXES = ("_BASE_URL", "_API_BASE", "_ENDPOINT")

# Offline switches for the Hugging Face stack (sentence-transformers et al.):
# a cache miss then fails fast instead of downloading a model.
_OFFLINE_SWITCHES = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}

# Names that modules legitimately set while test modules are being imported
# (checked by env_mutations):
#   GRAPHITI_MAX_COROUTINES  app/config.py pushes Config's default to the graph runtime;
#   TOKENIZERS_PARALLELISM   scripts/run_parallel_simulation.py silences tokenizers fork warnings;
#   EMBEDDING_DIM            app/services/graphiti_client/__init__.py pins graphiti's vector size;
#   KMP_DUPLICATE_LIB_OK, KMP_INIT_AT_FORK
#                            OpenMP-runtime setdefaults in scikit-learn and threadpoolctl.
# config.py also setdefaults every provider key_env to '' for the DeerFlow
# config loader; empty values are never reported, so those need no entry here.
IMPORT_TIME_ENV_ALLOWLIST = frozenset({
    "GRAPHITI_MAX_COROUTINES", "TOKENIZERS_PARALLELISM", "EMBEDDING_DIM",
    "KMP_DUPLICATE_LIB_OK", "KMP_INIT_AT_FORK",
})

# os.environ snapshot taken by conftest right after the scrub; None until then.
# Kept here (not in conftest) because `from tests.conftest import ...` re-executes
# conftest.py under a second module name and must not scrub a second time.
ENV_BASELINE: Optional[dict] = None


@functools.lru_cache(maxsize=1)
def _env_drift():
    """Load backend/scripts/check_env_drift.py (stdlib only) for its env-name parsers."""
    path = os.path.join(_BACKEND_DIR, "scripts", "check_env_drift.py")
    spec = importlib.util.spec_from_file_location("_drf_hermetic_check_env_drift", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_text(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _steering_names(repo_root: str) -> set:
    """Env names DRF reads or documents: Config reads, .env.example and the local .env files."""
    drift = _env_drift()
    config_text = _read_text(os.path.join(repo_root, "backend", "app", "config.py"))
    names = {m.group(1) or m.group(2) for m in drift._ENV_READ_RE.finditer(config_text)}
    names |= set(drift._ENV_DOC_RE.findall(_read_text(os.path.join(repo_root, ".env.example"))))
    for env_file in (os.path.join(repo_root, ".env"), os.path.join(repo_root, "backend", ".env")):
        names |= set(drift.parse_env_file(env_file))
    return names


def _is_protected(name: str) -> bool:
    return name in _PROTECTED_NAMES or name.startswith(_PROTECTED_PREFIXES)


def _is_egress_name(name: str) -> bool:
    return (name in _EGRESS_NAMES or name.startswith(_EGRESS_PREFIXES)
            or name.endswith(_EGRESS_SUFFIXES))


def scrub_ambient_env(environ: MutableMapping[str, str], *, repo_root: str = REPO_ROOT) -> list:
    """Pop every ambient name that could steer DRF code; return the popped names (sorted).

    Popped: names read by Config or documented in .env.example (parsed with
    check_env_drift's regexes), names in the repo-root and backend .env files,
    per-provider LLM_<P>_DISABLE_THINKING knobs, credential-shaped names
    (check_env_drift.is_secret) and egress endpoints.  Protected infrastructure
    names are always kept.  Also switches the Hugging Face stack offline.
    """
    drift = _env_drift()
    steering = _steering_names(repo_root)
    popped = []
    for name in list(environ):
        if _is_protected(name):
            continue
        if (name in steering
                or any(p.match(name) for p in drift._IGNORE_PATTERNS)
                or drift.is_secret(name)
                or _is_egress_name(name)):
            environ.pop(name, None)
            popped.append(name)
    environ.update(_OFFLINE_SWITCHES)
    return sorted(popped)


def env_mutations(baseline: Mapping[str, str], environ: Mapping[str, str],
                  allow: frozenset = IMPORT_TIME_ENV_ALLOWLIST) -> list:
    """Names whose value is new and non-empty relative to ``baseline`` (sorted), minus ``allow``."""
    return sorted(
        name for name, value in environ.items()
        if value != "" and baseline.get(name) != value and name not in allow
    )


# ---------------------------------------------------------------------------
# Egress guard
# ---------------------------------------------------------------------------

class EgressRefused(PermissionError):
    """A test tried to reach the network or spawn a provider CLI without opting in."""


_REFUSED_EXECUTABLES = frozenset({"claude", "codex", "curl", "wget"})
# Pipeline children that call providers or the network: the simulation runners,
# the DeerFlow research child and the resolution monitor.
_REFUSED_SCRIPT_RE = re.compile(
    r"^(?:run_[A-Za-z0-9_]+_simulation|deerflow_research|resolution_monitor)\.py$")
# A Python interpreter token (python, python3, python3.12, pythonw; .exe stripped by
# _exe_name).  Script names count as a spawn only when an interpreter runs them, so a
# command that merely names a script path (git log -- run_x_simulation.py) is allowed.
_PYTHON_EXE_RE = re.compile(r"^python(?:\d+(?:\.\d+)*)?w?$")
_OPT_IN_HINT = ("mark the test @pytest.mark.localhost (loopback sockets), "
                "@pytest.mark.subprocess_egress (provider CLIs / pipeline children) or "
                "@pytest.mark.integration, or stub the call")
_BETWEEN_TESTS_NOTE = "between tests: a thread or fixture outlived its test"


@dataclass(frozen=True)
class EgressPolicy:
    allow_loopback: bool = False
    allow_subprocess: bool = False
    between_tests: bool = False


# Policy outside any test's run (after install, between one test's teardown and
# the next test's setup): everything guarded is refused.
_BETWEEN_TESTS = EgressPolicy(between_tests=True)


def _strip_host(host: Any) -> str:
    if isinstance(host, (bytes, bytearray)):
        host = bytes(host).decode("ascii", "replace")
    return str(host).strip("[]").split("%", 1)[0]


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _is_loopback(host: str) -> bool:
    if host.rstrip(".").lower() == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return ip.is_loopback or bool(mapped and mapped.is_loopback)


def _exe_name(token: str) -> str:
    base = os.path.basename(token).lower()
    return base[:-4] if base.endswith(".exe") else base


def _command_tokens(args: Any, shell: bool) -> list:
    if isinstance(args, (str, bytes, os.PathLike)):
        items = [os.fsdecode(args)]
    else:
        items = [os.fsdecode(a) if isinstance(a, (str, bytes, os.PathLike)) else str(a) for a in args]
    if shell and items:
        try:
            return shlex.split(items[0]) + items[1:]
        except ValueError:
            return items[0].split() + items[1:]
    return items


class EgressGuard:
    """Process-wide egress refusal.

    ``install`` patches ``socket.socket.connect``/``connect_ex``,
    ``socket.getaddrinfo`` and ``subprocess.Popen.__init__`` once per session
    and starts in the between-tests policy, which refuses everything guarded.
    ``activate`` switches to a test's policy before any of its fixtures run,
    ``exempt`` lets an integration test through and ``idle`` returns to the
    between-tests policy after the test's teardown.  Before ``install`` (test
    collection) and after ``uninstall`` every call passes straight through.
    Refusals raise :class:`EgressRefused` and are recorded until
    ``take_refusals``, so the per-test fixture can fail a test whose code
    swallowed the error.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._policy: Optional[EgressPolicy] = None
        self._refusals: list = []
        self._saved: list = []
        self.real_connect: Callable = socket.socket.connect
        self.real_connect_ex: Callable = socket.socket.connect_ex
        self.real_getaddrinfo: Callable = socket.getaddrinfo
        self.real_popen_init: Callable = subprocess.Popen.__init__

    # -- lifecycle ---------------------------------------------------------
    @property
    def installed(self) -> bool:
        return bool(self._saved)

    @property
    def policy(self) -> Optional[EgressPolicy]:
        return self._policy

    def install(self) -> None:
        if self.installed:
            return
        self.real_connect = socket.socket.connect
        self.real_connect_ex = socket.socket.connect_ex
        self.real_getaddrinfo = socket.getaddrinfo
        self.real_popen_init = subprocess.Popen.__init__
        guard = self
        popen_signature = inspect.signature(self.real_popen_init)

        def connect(sock, address):
            guard._check_connect(sock, address)
            return guard.real_connect(sock, address)

        def connect_ex(sock, address):
            guard._check_connect(sock, address)
            return guard.real_connect_ex(sock, address)

        @functools.wraps(self.real_getaddrinfo)
        def getaddrinfo(host, port, *args, **kwargs):
            guard._check_resolve(host)
            return guard.real_getaddrinfo(host, port, *args, **kwargs)

        @functools.wraps(self.real_popen_init)
        def popen_init(popen_self, args, *rest, **kwargs):
            if not isinstance(args, (str, bytes, os.PathLike, collections.abc.Sequence)):
                args = list(args)  # an iterator must survive the inspection below
            try:
                bound = popen_signature.bind(popen_self, args, *rest, **kwargs)
            except TypeError:
                bound = None  # malformed call: let Popen raise its own TypeError
            if bound is not None:
                guard._check_spawn(args, bound.arguments.get("executable"),
                                   bool(bound.arguments.get("shell", False)))
            guard.real_popen_init(popen_self, args, *rest, **kwargs)

        self._patch(socket.socket, "connect", connect)
        self._patch(socket.socket, "connect_ex", connect_ex)
        self._patch(socket, "getaddrinfo", getaddrinfo)
        self._patch(subprocess.Popen, "__init__", popen_init)
        self.idle()

    def uninstall(self) -> None:
        while self._saved:
            owner, name, had_own, original = self._saved.pop()
            if had_own:
                setattr(owner, name, original)
            else:
                delattr(owner, name)
        self._policy = None

    def _patch(self, owner: Any, name: str, replacement: Callable) -> None:
        had_own = name in vars(owner)
        self._saved.append((owner, name, had_own, vars(owner).get(name)))
        setattr(owner, name, replacement)

    # -- policy ------------------------------------------------------------
    # Switching policy never clears recorded refusals: one recorded between
    # tests is reported by the next test's teardown instead of being lost.
    def activate(self, *, allow_loopback: bool = False, allow_subprocess: bool = False) -> None:
        """Apply a test's policy: refuse everything guarded except what its markers allow."""
        self._policy = EgressPolicy(allow_loopback=allow_loopback, allow_subprocess=allow_subprocess)

    def exempt(self) -> None:
        """Let everything through (an @pytest.mark.integration test)."""
        self._policy = None

    def idle(self) -> None:
        """Return to the between-tests policy, which refuses everything guarded."""
        self._policy = _BETWEEN_TESTS

    def take_refusals(self) -> list:
        """Return and forget the refusals recorded so far."""
        with self._lock:
            refusals, self._refusals = self._refusals, []
        return refusals

    def popen_unguarded(self, *args: Any, **kwargs: Any) -> subprocess.Popen:
        """Build a ``subprocess.Popen`` through the original constructor, bypassing the guard."""
        proc = subprocess.Popen.__new__(subprocess.Popen)
        self.real_popen_init(proc, *args, **kwargs)
        return proc

    # -- checks ------------------------------------------------------------
    def _refuse(self, what: str) -> None:
        if self._policy is not None and self._policy.between_tests:
            what = f"{what} ({_BETWEEN_TESTS_NOTE})"
        message = f"egress refused in test: {what}; {_OPT_IN_HINT}"
        with self._lock:
            self._refusals.append(what)
        raise EgressRefused(message)

    def _check_connect(self, sock: Any, address: Any) -> None:
        policy = self._policy
        if policy is None or getattr(sock, "family", None) not in (socket.AF_INET, socket.AF_INET6):
            return
        host = address[0] if isinstance(address, tuple) and address else address
        if policy.allow_loopback and _is_loopback(_strip_host(host)):
            return
        self._refuse(f"socket connect to {address!r}")

    def _check_resolve(self, host: Any) -> None:
        if self._policy is None or host is None:
            return
        name = _strip_host(host)
        if not name or name.rstrip(".").lower() == "localhost" or _is_ip_literal(name):
            return
        self._refuse(f"DNS lookup of {name!r}")

    def _check_spawn(self, args: Any, executable: Any, shell: bool) -> None:
        policy = self._policy
        if policy is None or policy.allow_subprocess:
            return
        tokens = _command_tokens(args, shell)
        programs = tokens if shell else tokens[:1]
        if executable is not None:
            programs = [os.fsdecode(executable), *programs]
        refused = [t for t in programs if _exe_name(t) in _REFUSED_EXECUTABLES]
        # A pipeline child runs as the program itself or as a script handed to an
        # interpreter (python -u x.py, uv run python x.py); a shell line is scanned whole.
        runs_python = any(_PYTHON_EXE_RE.match(_exe_name(t)) for t in [*programs, *tokens])
        scripts = tokens if shell or runs_python else programs
        refused += [t for t in scripts if _REFUSED_SCRIPT_RE.match(os.path.basename(t))]
        if refused:
            self._refuse(f"subprocess spawn of {tokens[:6]!r} (refused: {sorted(set(refused))})")


EGRESS_GUARD = EgressGuard()


# ---------------------------------------------------------------------------
# Process-global state reset
# ---------------------------------------------------------------------------

def reset_process_globals(modules: Mapping[str, Any] = sys.modules) -> None:
    """Clear module-level breakers and caches that leak between tests.

    Only modules that are already imported are touched (``modules.get``), so the
    reset never pulls a heavy module into a test that did not load it.
    """
    llm_client = modules.get("app.utils.llm_client")
    if llm_client is not None:
        with llm_client._CB_LOCK:
            llm_client._CB_STATE.clear()
        llm_client._FB_OPENAI_CLIENTS.clear()
        llm_client._FB_AUTH_UNAVAILABLE_UNTIL.clear()
        llm_client._FB_MISCONFIG_WARNED.clear()
    telemetry = modules.get("app.utils.telemetry")
    if telemetry is not None:
        with telemetry.LLMCache._lock:
            telemetry.LLMCache._store.clear()
            telemetry.LLMCache._order.clear()
        telemetry._COST_OVERRIDE_CACHE.clear()
    orchestrator = modules.get("app.services.pipeline_orchestrator")
    if orchestrator is not None:
        # The teardown pass runs before the test's monkeypatch undo, so
        # llm_client.LLMClient may still be a test double (possibly without a
        # chat attribute).  Uninstall only when the probe is really in place;
        # a probe hidden behind a double is removed by the next setup pass.
        client_cls = getattr(llm_client, "LLMClient", None)
        if getattr(getattr(client_cls, "chat", None), "_drf_outage_probe", False) is True:
            orchestrator._uninstall_llm_outage_probe()
        with orchestrator._RUN_OUTAGE_LOCK:
            orchestrator._RUN_OUTAGE_BREAKERS.clear()
