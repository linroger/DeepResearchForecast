"""Hermetic test-process harness (INFRA-12).

Stdlib-only helpers that ``backend/tests/conftest.py`` uses to make the offline
suite independent of the developer's shell and unable to reach the network:

* ``scrub_ambient_env`` pops every env name that steers DRF code (every name
  the application, scripts, DeerFlow bridge and drf2 sources mention, the
  knobs the shell scripts read, Config knobs, documented .env names,
  credentials, egress endpoints) *before* any ``app`` module is imported, so
  an exported ``LLM_PROVIDER``, API key or feature flag cannot change test
  behaviour.  Names are popped, not blanked: DRF reads
  ``os.environ.get(NAME, default)`` and treats ``''`` as a real value.
* ``env_mutations`` backs the collection-time check that importing test
  modules never mutates ``os.environ`` (the sim scripts used to inject the
  developer's .env this way).
* ``EgressGuard`` refuses TCP/UDP traffic, DNS lookups of real hostnames and
  provider-CLI / keychain / pipeline-child spawns from the conftest's import
  (before any test module is imported) to the end of the session (per-test
  markers widen the policy, integration tests are exempt), and records every
  refusal so a test that swallows the error, or a module import that does,
  still fails.
* ``reset_process_globals`` clears module-level breakers and caches that would
  otherwise leak from one test into the next.

Known limits: the guard patches Python-level entry points, so traffic from
native extensions that bypass the ``socket`` module (Rust/C HTTP clients) is
not seen; child Python interpreters run unguarded (with the scrubbed
environment); a refusal raised inside a forked child blocks the spawn but its
record stays in the child.  The spawn check reads the command as written: a
program named only at run time (``$(which claude)``, a shell variable) is not
recognized.  Tests outside backend/tests that share a session (``pytest .``
from the repo root also collects backend/scripts/test_*.py) are not under the
harness and run exempt; only their import falls under the guard, when it comes
after the conftest's.  HOME is kept (the offline model caches live under
it), so credential files there (~/.claude/.credentials.json,
~/.codex/auth.json) stay readable; the loader that reads them (DeerFlow's
credential_loader) is not importable in the backend venv, and its macOS
keychain fallback (``security``) is a refused spawn.

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
_EGRESS_SUFFIXES = ("_BASE_URL", "_API_BASE", "_API_URL", "_ENDPOINT")

# Source trees whose env reads steer the code under test (their .py and .sh
# files; the shell scripts at the repo root are scanned too).  backend/tests is
# not scanned: the tests' own env reads are assertions or explicit opt-ins.
_SOURCE_ROOTS = ("backend/app", "backend/scripts", "backend/run.py",
                 "deerflow_bridge", "drf2", "scripts")
_SOURCE_SUFFIXES = (".py", ".sh")
_SKIPPED_DIRS = frozenset({".venv", "node_modules", "__pycache__"})
# Configs whose $NAME / ${NAME} references the DeerFlow research child resolves
# from the environment.
_ENV_REFERENCING_CONFIGS = ("deerflow_bridge/config.yaml", "deerflow_bridge/extensions_config.json")

# Env names as they appear in DRF source: every UPPER_SNAKE string literal
# (os.environ.get('X'), local helpers such as _env_flag('X') or _cfg_int('X'),
# getattr(Config, 'X'), constants like PROMPT_CACHE_ENV = 'X', name tuples a
# loop reads), plus underscore-free names read straight from os.environ or
# os.getenv.  Deliberately broad: popping an ambient name that merely looks like
# a knob is harmless, missing a knob is not.
_SOURCE_ENV_NAME_RE = re.compile(
    r"(?<![\w'\"])[rRuU]?(['\"])([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\1"
    r"|(?:environ(?:\.get|\.setdefault|\.pop)?|getenv)\s*[(\[]\s*['\"]([A-Z][A-Z0-9_]*)['\"]")
_CONFIG_ENV_REF_RE = re.compile(r"\$\{?([A-Z][A-Z0-9_]*)")
# Knobs a shell script reads: ${NAME:-default} (also :=, :?, :+ and the forms
# without a colon), the idiom a `set -u` script such as scripts/start.sh needs
# for a variable that may be unset.  A bare $NAME is not collected: it is as
# likely a script-local variable or shell infrastructure ($PWD, $USER).
_SHELL_ENV_READ_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]*):?[-=?+]")

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
    """Load backend/scripts/check_env_drift.py (stdlib only) for its env-name parsers
    (config.py's knobs come from config_audit.extract_knobs through it)."""
    path = os.path.join(_BACKEND_DIR, "scripts", "check_env_drift.py")
    spec = importlib.util.spec_from_file_location("_drf_hermetic_check_env_drift", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_text(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _repo_path(repo_root: str, relative: str) -> str:
    return os.path.join(repo_root, *relative.split("/"))


def _source_files(repo_root: str):
    """The shell scripts at the repo root, then every .py / .sh file under
    _SOURCE_ROOTS (a root may also be a single file)."""
    if os.path.isdir(repo_root):
        for filename in sorted(os.listdir(repo_root)):
            path = os.path.join(repo_root, filename)
            if filename.endswith(".sh") and os.path.isfile(path):
                yield path
    for relative in _SOURCE_ROOTS:
        root = _repo_path(repo_root, relative)
        if os.path.isfile(root):
            yield root
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIPPED_DIRS]
            for filename in filenames:
                if filename.endswith(_SOURCE_SUFFIXES):
                    yield os.path.join(dirpath, filename)


def _steering_names(repo_root: str) -> set:
    """Env names DRF reads, references or documents.

    Config reads (config_audit.extract_knobs over config.py, through
    check_env_drift.config_knobs), .env.example, the local .env files, every
    env-shaped name in the application / script / bridge / drf2 Python sources,
    the ${NAME:-default} knobs of the shell scripts and the $NAME references in
    DeerFlow's configs.
    """
    drift = _env_drift()
    config_text = _read_text(os.path.join(repo_root, "backend", "app", "config.py"))
    names = set(drift.config_knobs(config_text))
    names |= set(drift._ENV_DOC_RE.findall(_read_text(os.path.join(repo_root, ".env.example"))))
    for env_file in (os.path.join(repo_root, ".env"), os.path.join(repo_root, "backend", ".env")):
        names |= set(drift.parse_env_file(env_file))
    for path in _source_files(repo_root):
        text = _read_text(path)
        if path.endswith(".sh"):
            names |= set(_SHELL_ENV_READ_RE.findall(text))
        else:
            names |= {m.group(2) or m.group(3) for m in _SOURCE_ENV_NAME_RE.finditer(text)}
    for relative in _ENV_REFERENCING_CONFIGS:
        names |= set(_CONFIG_ENV_REF_RE.findall(_read_text(_repo_path(repo_root, relative))))
    return names


def _is_protected(name: str) -> bool:
    return name in _PROTECTED_NAMES or name.startswith(_PROTECTED_PREFIXES)


def _is_egress_name(name: str) -> bool:
    return (name in _EGRESS_NAMES or name.startswith(_EGRESS_PREFIXES)
            or name.endswith(_EGRESS_SUFFIXES))


def scrub_ambient_env(environ: MutableMapping[str, str], *, repo_root: str = REPO_ROOT) -> list:
    """Pop every ambient name that could steer DRF code; return the popped names (sorted).

    Popped: names read by Config or documented in .env.example (parsed with
    check_env_drift's parsers), names in the repo-root and backend .env files,
    env-shaped names in the DRF sources, shell scripts and DeerFlow configs
    (_steering_names), per-provider LLM_<P>_DISABLE_THINKING knobs,
    credential-shaped names (check_env_drift.is_secret) and egress endpoints.
    Protected infrastructure names are always kept.  Also switches the Hugging
    Face stack offline.
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
    """A test tried to reach the network, a provider CLI or the keychain without opting in."""


# Programs whose spawn reaches a provider, the network or the user's login
# keychain (``security`` is the macOS keychain CLI DeerFlow's credential loader
# falls back to).
_REFUSED_EXECUTABLES = frozenset({"claude", "codex", "curl", "wget", "security"})
# Pipeline children that call providers or the network: the simulation runners,
# the DeerFlow research child and the resolution monitor.
_REFUSED_SCRIPT_RE = re.compile(
    r"^(?:run_[A-Za-z0-9_]+_simulation|deerflow_research|resolution_monitor)\.py$")
# A Python interpreter token (python, python3, python3.12, pythonw; .exe stripped by
# _exe_name).  Script names count as a spawn only when an interpreter runs them, so a
# command that merely names a script path (git log -- run_x_simulation.py) is allowed.
_PYTHON_EXE_RE = re.compile(r"^python(?:\d+(?:\.\d+)*)?w?$")
# The provider CLIs' npm packages, as a JavaScript launcher names them
# (npx @anthropic-ai/claude-code, node .../claude-code/cli.js, npx @openai/codex@latest).
_PROVIDER_CLI_PACKAGE_RE = re.compile(
    r"(?:^|[/\\])(?:(?:@anthropic-ai[/\\])?claude-code|@openai[/\\]codex)(?:@[\w.\-]+)?(?:[/\\]|$)")
_JS_LAUNCHERS = frozenset({"node", "npx", "bunx", "bun", "pnpm", "pnpx", "yarn", "deno"})
_JS_RUNNER_SUBCOMMANDS = frozenset({"dlx", "exec", "x"})
_JS_EXTENSIONS = (".js", ".mjs", ".cjs")
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish"})
# Shell long options that take a separate value (bash --rcfile/--init-file, zsh --emulate).
_SHELL_VALUE_LONG_OPTIONS = frozenset({"--rcfile", "--init-file", "--emulate"})
# Launchers that run another program, with their options that take a separate
# value; the spawn check looks through them to the program actually run.
_LAUNCHER_VALUE_OPTIONS = {
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "-P"}),
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "gtimeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
    "nice": frozenset({"-n", "--adjustment"}),
    "nohup": frozenset(),
    "stdbuf": frozenset({"-i", "-o", "-e"}),
    "xargs": frozenset({"-a", "--arg-file", "-d", "--delimiter", "-E", "-I", "-L", "-n",
                        "--max-args", "-P", "--max-procs", "-s", "--max-chars"}),
    "command": frozenset(),
    "exec": frozenset({"-a"}),
    "time": frozenset({"-f", "--format", "-o", "--output"}),
}
# Operands a launcher takes before the program (timeout DURATION PROGRAM ...).
_LAUNCHER_OPERANDS = {"timeout": 1, "gtimeout": 1}
# uv options (global or `uv run`) that take a separate value.
_UV_VALUE_OPTIONS = frozenset({
    "--directory", "--project", "--cache-dir", "--config-file", "--color", "--python", "-p",
    "--with", "--with-editable", "--with-requirements", "--env-file", "--extra", "--group",
    "--only-group", "--no-group", "--package", "--index", "--default-index", "--index-url",
    "-i", "--extra-index-url", "--find-links", "-f"})
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Shell words that can precede a command without being one.
_SHELL_KEYWORDS = frozenset({"!", "{", "}", "if", "then", "else", "elif", "fi",
                             "do", "done", "while", "until"})
_SHELL_PUNCTUATION = frozenset("();<>|&")
_OPT_IN_HINT = ("mark the test @pytest.mark.localhost (loopback sockets), "
                "@pytest.mark.subprocess_egress (provider CLIs / pipeline children) or "
                "@pytest.mark.integration, or stub the call")
_BEFORE_TESTS_NOTE = "before the first test"
_BETWEEN_TESTS_NOTE = "between tests: a thread or fixture outlived its test"


@dataclass(frozen=True)
class EgressPolicy:
    allow_loopback: bool = False
    allow_subprocess: bool = False
    # Set on the policies outside any test; appended to each refusal's record.
    outside_tests: str = ""


# Policies outside any test's run refuse everything guarded: from install to
# the end of collection, and between one test's teardown and the next setup.
_BEFORE_TESTS = EgressPolicy(outside_tests=_BEFORE_TESTS_NOTE)
_BETWEEN_TESTS = EgressPolicy(outside_tests=_BETWEEN_TESTS_NOTE)


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


def _command_tokens(args: Any) -> list:
    if isinstance(args, (str, bytes, os.PathLike)):
        return [os.fsdecode(args)]
    return [os.fsdecode(a) if isinstance(a, (str, bytes, os.PathLike)) else str(a) for a in args]


def _split_words(text: str) -> list:
    try:
        return shlex.split(text)
    except ValueError:  # unbalanced quotes
        return text.split()


def _uv_run_command(argv: list) -> Optional[list]:
    """The command of ``uv [options] run [options] COMMAND...``; None when argv is no uv run."""
    seen_run = False
    i = 1
    while i < len(argv):
        token = argv[i]
        if token == "--":
            return argv[i + 1:] if seen_run else None
        if token.startswith("-"):
            i += 2 if token in _UV_VALUE_OPTIONS else 1
        elif seen_run:
            return argv[i:]
        elif token == "run":
            seen_run = True
            i += 1
        else:
            return None
    return [] if seen_run else None


def _unwrap_launchers(argv: list) -> list:
    """Strip VAR=value words, shell keywords and launchers (env, timeout, nice, xargs,
    uv run, ...) off the front of ``argv``, leaving the program that actually runs."""
    argv = list(argv)
    while argv:
        head = argv[0]
        if _ASSIGNMENT_RE.match(head) or head in _SHELL_KEYWORDS:
            argv.pop(0)
            continue
        name = _exe_name(head)
        if name == "uv":
            command = _uv_run_command(argv)
            if command is None:
                return argv
            argv = command
            continue
        value_options = _LAUNCHER_VALUE_OPTIONS.get(name)
        if value_options is None:
            return argv
        i = 1
        while i < len(argv) and argv[i].startswith("-"):
            option = argv[i]
            if option == "--":
                i += 1
                break
            if option == "-":
                if name != "env":
                    break
                i += 1  # env's bare '-' is -i
                continue
            if name == "command" and {"v", "V"} & set(option[1:]):
                return []  # command -v / -V looks the program up without running it
            if name == "env" and option.startswith("-S"):
                # env -S 'PROGRAM ARGS' (or -S'...') splits one string into words.
                split, width = (argv[i + 1:i + 2], 2) if option == "-S" else ([option[2:]], 1)
                argv[i:i + width] = _split_words(" ".join(split))
                continue
            i += 2 if option in value_options else 1
        argv = argv[i + _LAUNCHER_OPERANDS.get(name, 0):]
    return argv


def _shell_inline_command(argv: list) -> Optional[str]:
    """LINE of ``sh [options] -c [options] [--] LINE``; None for a script run.

    As the shells parse it: options may follow -c (-c -x LINE), an o / O in an
    option cluster takes the next word (-o pipefail, -eo pipefail, -co pipefail
    LINE), --rcfile / --init-file / --emulate take a value, and -- or a bare -
    ends the options; LINE is the first word after them.
    """
    inline = False
    i = 1
    while i < len(argv):
        token = argv[i]
        if token in ("--", "-"):
            i += 1
            break
        if token in _SHELL_VALUE_LONG_OPTIONS:
            i += 2
        elif token.startswith("--"):
            i += 1
        elif token.startswith(("-", "+")) and len(token) > 1:
            cluster = token[1:]
            inline = inline or (token[0] == "-" and "c" in cluster)
            i += 2 if ("o" in cluster or "O" in cluster) else 1
        else:
            break
    return argv[i] if inline and i < len(argv) else None


def _shell_commands(line: str) -> list:
    """Split a shell command line into its simple commands (one argv each).

    Commands start the line and follow ; & && | || |& ( ) $( or a backtick or
    newline; a redirection's target is a file name, not a command.
    """
    text = line.replace("\n", ";").replace("`", ";")
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:  # unbalanced quotes: split on whitespace and operators
        tokens = re.findall(r"[^\s();<>|&]+|[();<>|&]+", text)
    commands, current, skip_target = [], [], False
    for token in tokens:
        if skip_target:
            skip_target = False
        elif token and set(token) <= _SHELL_PUNCTUATION:
            if "<" in token or ">" in token:
                skip_target = True
            else:
                commands.append(current)
                current = []
        else:
            current.append(token)
    commands.append(current)
    return [command for command in commands if command]


def _js_launcher_refusals(argv: list) -> list:
    """Provider CLIs run through a JavaScript launcher (npx, node, pnpm dlx, ...)."""
    refused = [t for t in argv[1:] if _PROVIDER_CLI_PACKAGE_RE.search(t)]
    operands = [t for t in argv[1:] if not t.startswith("-")]
    if operands and operands[0] in _JS_RUNNER_SUBCOMMANDS:
        operands = operands[1:]
    if operands:
        stem = _exe_name(operands[0]).split("@", 1)[0]
        for extension in _JS_EXTENSIONS:
            stem = stem.removesuffix(extension)
        if stem in _REFUSED_EXECUTABLES:
            refused.append(operands[0])
    return refused


def _spawn_refusals(argv: list) -> list:
    """Tokens that make ``argv`` a refused spawn: a provider CLI, the keychain CLI or a
    pipeline child, seen through launchers, ``sh -c`` lines and JavaScript launchers."""
    argv = _unwrap_launchers(argv)
    if not argv:
        return []
    program = _exe_name(argv[0])
    if program in _SHELLS:
        line = _shell_inline_command(argv)
        return _shell_line_refusals(line) if line is not None else []
    refused = [argv[0]] if program in _REFUSED_EXECUTABLES else []
    if program in _JS_LAUNCHERS:
        refused += _js_launcher_refusals(argv)
    # A pipeline child runs as the program itself or as a script handed to an
    # interpreter (python -u x.py; uv run x.py was unwrapped to x.py above).
    candidates = argv if _PYTHON_EXE_RE.match(program) else argv[:1]
    refused += [t for t in candidates if _REFUSED_SCRIPT_RE.match(os.path.basename(t))]
    return refused


def _shell_line_refusals(line: str) -> list:
    """_spawn_refusals for every simple command of a shell command line."""
    refused = []
    for command in _shell_commands(line):
        refused += _spawn_refusals(command)
    return refused


class EgressGuard:
    """Process-wide egress refusal.

    ``install`` patches, once per session: ``socket.socket.connect`` /
    ``connect_ex`` / ``sendto`` / ``sendmsg`` (AF_INET/AF_INET6), the resolvers
    ``socket.getaddrinfo`` / ``gethostbyname`` / ``gethostbyname_ex`` /
    ``gethostbyaddr``, and the spawners ``subprocess.Popen.__init__`` (which
    also covers os.popen and asyncio), ``os.system``, ``os.posix_spawn`` /
    ``posix_spawnp`` and ``os.execv`` / ``execve`` (the os.exec*/os.spawn*
    family calls these).  It starts in the before-tests policy, which refuses
    everything guarded while pytest starts up and imports the test modules.
    ``activate`` switches to a test's policy before any of its fixtures run,
    ``exempt`` lets an integration test through and ``idle`` switches to the
    between-tests policy (also refusing everything) at the end of collection
    and after each test's teardown.  Before ``install`` and after
    ``uninstall`` every call passes straight through.  Refusals raise
    :class:`EgressRefused` and are recorded until ``take_refusals``, so the
    harness can fail a test whose code swallowed the error.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._policy: Optional[EgressPolicy] = None
        self._refusals: list = []
        self._saved: list = []
        self._bypass = threading.local()
        self.real_connect: Callable = socket.socket.connect
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
        guard = self
        self.real_connect = socket.socket.connect
        self.real_popen_init = subprocess.Popen.__init__
        popen_signature = inspect.signature(self.real_popen_init)
        real_connect_ex = socket.socket.connect_ex
        real_sendto = socket.socket.sendto
        real_getaddrinfo = socket.getaddrinfo
        real_gethostbyaddr = socket.gethostbyaddr
        real_system = os.system

        def connect(sock, address):
            guard._check_address(sock, address, "connect to")
            return guard.real_connect(sock, address)

        def connect_ex(sock, address):
            guard._check_address(sock, address, "connect to")
            return real_connect_ex(sock, address)

        def sendto(sock, data, *args):
            # sendto(data, address) or sendto(data, flags, address)
            if args:
                guard._check_address(sock, args[-1], "sendto")
            return real_sendto(sock, data, *args)

        @functools.wraps(real_getaddrinfo)
        def getaddrinfo(host, port, *args, **kwargs):
            guard._check_resolve(host)
            return real_getaddrinfo(host, port, *args, **kwargs)

        def forward_resolver(real):
            @functools.wraps(real)
            def resolve(hostname):
                guard._check_resolve(hostname)
                return real(hostname)
            return resolve

        @functools.wraps(real_gethostbyaddr)
        def gethostbyaddr(address):
            guard._check_reverse_resolve(address)
            return real_gethostbyaddr(address)

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

        @functools.wraps(real_system)
        def system(command):
            guard._check_spawn(command, None, True)
            return real_system(command)

        def path_spawner(real):
            # posix_spawn(path, argv, ...), execv(path, argv), execve(path, argv, env)
            @functools.wraps(real)
            def spawn(path, argv, *args, **kwargs):
                guard._check_spawn(argv, path, False)
                return real(path, argv, *args, **kwargs)
            return spawn

        self._patch(socket.socket, "connect", connect)
        self._patch(socket.socket, "connect_ex", connect_ex)
        self._patch(socket.socket, "sendto", sendto)
        if hasattr(socket.socket, "sendmsg"):
            real_sendmsg = socket.socket.sendmsg

            def sendmsg(sock, buffers, *args):
                # sendmsg(buffers[, ancdata[, flags[, address]]])
                if len(args) >= 3:
                    guard._check_address(sock, args[2], "sendmsg")
                return real_sendmsg(sock, buffers, *args)

            self._patch(socket.socket, "sendmsg", sendmsg)
        self._patch(socket, "getaddrinfo", getaddrinfo)
        for name in ("gethostbyname", "gethostbyname_ex"):
            self._patch(socket, name, forward_resolver(getattr(socket, name)))
        self._patch(socket, "gethostbyaddr", gethostbyaddr)
        self._patch(subprocess.Popen, "__init__", popen_init)
        self._patch(os, "system", system)
        for name in ("posix_spawn", "posix_spawnp", "execv", "execve"):
            if hasattr(os, name):
                self._patch(os, name, path_spawner(getattr(os, name)))
        self._policy = _BEFORE_TESTS

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
        """Switch to the between-tests policy, which refuses everything guarded."""
        self._policy = _BETWEEN_TESTS

    def take_refusals(self) -> list:
        """Return and forget the refusals recorded so far."""
        with self._lock:
            refusals, self._refusals = self._refusals, []
        return refusals

    def popen_unguarded(self, *args: Any, **kwargs: Any) -> subprocess.Popen:
        """Build a ``subprocess.Popen`` through the original constructor, bypassing the
        guard (including the os-level spawn hooks Popen may use internally)."""
        proc = subprocess.Popen.__new__(subprocess.Popen)
        self._bypass.active = True
        try:
            self.real_popen_init(proc, *args, **kwargs)
        finally:
            self._bypass.active = False
        return proc

    # -- checks ------------------------------------------------------------
    def _refuse(self, what: str) -> None:
        if self._policy is not None and self._policy.outside_tests:
            what = f"{what} ({self._policy.outside_tests})"
        message = f"egress refused in test: {what}; {_OPT_IN_HINT}"
        with self._lock:
            self._refusals.append(what)
        raise EgressRefused(message)

    def _check_address(self, sock: Any, address: Any, action: str) -> None:
        policy = self._policy
        if policy is None or getattr(sock, "family", None) not in (socket.AF_INET, socket.AF_INET6):
            return
        host = address[0] if isinstance(address, tuple) and address else address
        if policy.allow_loopback and _is_loopback(_strip_host(host)):
            return
        self._refuse(f"socket {action} {address!r}")

    def _check_resolve(self, host: Any) -> None:
        if self._policy is None or host is None:
            return
        name = _strip_host(host)
        if not name or name.rstrip(".").lower() == "localhost" or _is_ip_literal(name):
            return
        self._refuse(f"DNS lookup of {name!r}")

    def _check_reverse_resolve(self, address: Any) -> None:
        """gethostbyaddr: a hostname is a forward lookup; only a loopback address resolves locally."""
        if self._policy is None:
            return
        name = _strip_host(address)
        if not _is_ip_literal(name):
            self._check_resolve(name)
        elif not _is_loopback(name):
            self._refuse(f"reverse DNS lookup of {name!r}")

    def _check_spawn(self, args: Any, executable: Any, shell: bool) -> None:
        policy = self._policy
        if policy is None or policy.allow_subprocess or getattr(self._bypass, "active", False):
            return
        tokens = _command_tokens(args)
        # os.execve also takes an open file descriptor (fexecve): argv names the program then.
        program = os.fsdecode(executable) if isinstance(executable, (str, bytes, os.PathLike)) else None
        if shell:
            # The shell runs tokens[0] as a command line; later items are its $0, $1, ...
            refused = _shell_line_refusals(tokens[0]) if tokens else []
            if program is not None:
                refused += _spawn_refusals([program])
        else:
            argv = tokens if program is None else [program, *tokens[1:]]
            refused = _spawn_refusals(argv)
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
