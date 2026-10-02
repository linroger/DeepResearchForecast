"""INFRA-12 meta-tests: the offline suite is hermetic.

Covers the harness in tests/_hermetic.py and tests/conftest.py:

- the ambient scrub pops steering / credential / egress names (every env name
  the DRF sources read, pinned by an independent AST scan, and the knobs the
  shell scripts read) and keeps infra;
- importing a test module that mutates os.environ or reaches out stops the
  session (UsageError);
- sockets, datagrams, DNS and provider-CLI / keychain / pipeline-child spawns
  (also behind sh -c, env, timeout, uv run, npx/node and os-level spawners) are
  refused and recorded, so a test that swallows the error still fails; markers
  opt in narrowly; the policy covers fixtures of every scope, their teardown,
  the gap between tests and the end of the session; tests outside the
  harness's directory run exempt;
- process-global breakers and caches do not leak from one test into the next;
- FakeLLMClient accepts every parameter of the real LLMClient methods;
- load_project_dotenv is a no-op in the test process and plain load_dotenv
  outside it; Config._persist_env never writes the real .env;
- pytest markers are strict and CI runs the suite under two timezones.

The pytester runs use a subprocess so the inner session's scrub and egress
patches can never touch this process.
"""

import ast
import inspect
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import tomllib
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
import yaml

import _hermetic
from tests.conftest import FakeLLMClient

# Loaded here, not in conftest.py: pytest rejects pytest_plugins in a conftest
# that is not top-level (`pytest .` from the repo root).
pytest_plugins = ("pytester",)

_TESTS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _TESTS_DIR.parent
_REPO_ROOT = _BACKEND_DIR.parent

# conftest shim for pytester sessions: executes the real backend/tests/conftest.py
# and re-exports its hooks and fixtures, so the inner session runs the actual harness.
_CONFTEST_SHIM = """
import importlib.util
import sys

sys.path.insert(0, {tests_dir!r})
_spec = importlib.util.spec_from_file_location("drf_backend_conftest", {conftest!r})
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
globals().update({{k: v for k, v in vars(_module).items() if not k.startswith("__")}})
"""


def _pyproject_pytest_options():
    with open(_BACKEND_DIR / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)["tool"]["pytest"]["ini_options"]


def _make_inner_ini(pytester):
    markers = "\n".join(f"    {line}" for line in _pyproject_pytest_options()["markers"])
    pytester.makeini(f"[pytest]\naddopts = -p no:cacheprovider --strict-markers\nmarkers =\n{markers}\n")


def _conftest_shim(conftest_extra=""):
    return _CONFTEST_SHIM.format(tests_dir=str(_TESTS_DIR),
                                 conftest=str(_TESTS_DIR / "conftest.py")) + conftest_extra


def _run_inner_session(pytester, source, conftest_extra="", *args):
    """Run test modules under the real conftest in a child pytest.

    ``source`` is the text of test_inner.py or a {module name: text} mapping,
    ``conftest_extra`` is appended to the conftest shim (extra hooks for one
    run) and ``args`` are passed to the child pytest.
    """
    _make_inner_ini(pytester)
    pytester.makeconftest(_conftest_shim(conftest_extra))
    pytester.makepyfile(**(source if isinstance(source, dict) else {"test_inner": source}))
    return pytester.runpytest_subprocess("-rA", *args, timeout=180)


@contextmanager
def _loopback_listener():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        yield server
    finally:
        server.close()


# ---------------------------------------------------------------------------
# Ambient environment scrub
# ---------------------------------------------------------------------------

_KEPT_INFRA = {
    "PATH": "/usr/bin", "HOME": "/home/dev", "TMPDIR": "/tmp", "TZ": "Asia/Shanghai",
    "LANG": "en_US.UTF-8", "LC_ALL": "C", "VIRTUAL_ENV": "/venv", "UV_CACHE_DIR": "/uv",
    "PYTHONPATH": "/x", "CI": "true", "GITHUB_TOKEN": "gh-x", "HTTP_PROXY": "http://proxy:3128",
    "HTTPS_PROXY": "http://proxy:3128", "NO_PROXY": "localhost", "SHELL": "/bin/zsh",
}


def test_scrub_pops_steering_credential_and_egress_names_and_keeps_infra():
    environ = dict(_KEPT_INFRA)
    popped_expected = {
        "OPENAI_API_KEY": "sk-ambient",            # credential-shaped
        "LLM_PROVIDER": "openai",                  # read by Config
        "REPORT_PUBLISH_GATE": "false",            # read by Config ('' would not mean default)
        "LLM_FALLBACK_API_KEY": "sk-fb",           # credential + fallback egress
        "LLM_FALLBACK_NEW_KNOB": "x",              # fallback prefix, unknown to Config
        "OPENAI_BASE_URL": "https://proxy.example/v1",
        "ANTHROPIC_BASE_URL": "https://proxy.example",
        "ACME_BASE_URL": "https://acme.example",   # *_BASE_URL
        "ACME_API_URL": "https://acme.example",    # *_API_URL
        "OTEL_EXPORTER_OTLP_ENDPOINT": "https://otel.example",
        "SOME_SERVICE_TOKEN": "t", "DB_PASSWORD": "p", "APP_SECRET": "s",
        "LLM_ACME_DISABLE_THINKING": "true",       # per-provider dynamic knob
        "DRF_MCP_KG_GRAPH_ID": "g",
    }
    environ.update(popped_expected)

    popped = _hermetic.scrub_ambient_env(environ)

    assert popped == sorted(popped_expected)
    for name, value in _KEPT_INFRA.items():
        assert environ[name] == value, name
    assert environ["HF_HUB_OFFLINE"] == "1"
    assert environ["TRANSFORMERS_OFFLINE"] == "1"


def test_scrub_pops_names_from_config_docs_dotenv_files_and_sources(tmp_path):
    files = {
        "backend/app/config.py":
            "import os\nX = os.environ.get('CUSTOM_CONFIG_KNOB', 'a')\nY = os.environ['OTHER_CONFIG_KNOB']\n",
        "backend/app/services/svc.py": "flag = _env_flag('APP_HELPER_KNOB')\nkey = os.getenv('SHORTKNOB')\n",
        "backend/scripts/tool.py": "PROMPT_ENV = 'SCRIPT_CONSTANT_KNOB'\n",
        "backend/run.py": "if 'RUNNER_KNOB' in os.environ:\n    pass\n",
        "deerflow_bridge/bridge.py": "for name in ('BRIDGE_TUPLE_KNOB',):\n    pass\n",
        "deerflow_bridge/config.yaml": "model: $YAML_REF_MODEL\nurl: ${YAML_REF_TARGET}\n",
        "drf2/driver/cli.py": "limit = _cfg_int('DRF2_KNOB', 3)\n",
        "scripts/salvage.py": "x = getattr(Config, 'ROOT_SCRIPT_KNOB', 0)\n",
        # shell scripts: ${NAME:-default} and friends are knobs, a bare $NAME is not
        "scripts/start.sh": 'PORT="${SHELL_DEFAULT_KNOB:-5001}"\n: "${SHELL_ASSIGN_KNOB:=1}"\necho "$USER"\n',
        "setup.sh": '[ -n "${ROOT_SHELL_KNOB+x}" ] && echo set\n',
        "backend/tests/test_x.py": "os.environ.get('TEST_ONLY_OPT_IN')\n",       # tests are not scanned
        "backend/app/.venv/lib/site.py": "os.environ.get('VENDORED_KNOB')\n",   # nor virtualenvs
        ".env.example": "# DOC_ONLY_KNOB=1\nDOC_ACTIVE_KNOB=2\n",
        ".env": "export ROOT_DOTENV_KNOB='v'\n",
        "backend/.env": "BACKEND_DOTENV_KNOB=v\n",
    }
    for relative, text in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    names = ["CUSTOM_CONFIG_KNOB", "OTHER_CONFIG_KNOB", "APP_HELPER_KNOB", "SHORTKNOB",
             "SCRIPT_CONSTANT_KNOB", "RUNNER_KNOB", "BRIDGE_TUPLE_KNOB", "YAML_REF_MODEL",
             "YAML_REF_TARGET", "DRF2_KNOB", "ROOT_SCRIPT_KNOB", "DOC_ONLY_KNOB", "DOC_ACTIVE_KNOB",
             "ROOT_DOTENV_KNOB", "BACKEND_DOTENV_KNOB", "SHELL_DEFAULT_KNOB", "SHELL_ASSIGN_KNOB",
             "ROOT_SHELL_KNOB"]
    kept = {"TEST_ONLY_OPT_IN": "kept", "VENDORED_KNOB": "kept", "UNRELATED_NAME": "kept", "USER": "kept"}
    environ = {**dict.fromkeys(names, "ambient"), **kept}

    popped = _hermetic.scrub_ambient_env(environ, repo_root=str(tmp_path))

    assert popped == sorted(names)
    assert environ == {**kept, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}


def test_scrub_covers_the_knobs_start_sh_reads():
    """test_start_script_progress.py runs scripts/start.sh with a copy of os.environ;
    START_BACKEND_TIMEOUT_SECONDS=0 exported in the shell once failed four of its tests."""
    start_sh = (_REPO_ROOT / "scripts" / "start.sh").read_text(encoding="utf-8")
    knobs = set(re.findall(r"\$\{(\w+):-", start_sh))
    assert {"FLASK_PORT", "START_BACKEND_TIMEOUT_SECONDS", "START_FRONTEND_TIMEOUT_SECONDS",
            "START_HEALTH_CURL_TIMEOUT_SECONDS", "START_HEALTH_FAILURE_GRACE_SECONDS",
            "START_FOLLOWER_RESTART_LIMIT"} <= knobs
    environ = dict.fromkeys(knobs, "0")
    _hermetic.scrub_ambient_env(environ)
    assert set(environ) == {"HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"}


def test_scrub_covers_every_name_config_reads():
    drift = _hermetic._env_drift()
    environ = dict.fromkeys(drift.config_env_vars() | drift.documented_env_vars(), "ambient")
    _hermetic.scrub_ambient_env(environ)
    assert set(environ) == {"HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"}


# Independent oracle for the source scan: an AST walk, not _hermetic's regex.
_ORACLE_SOURCE_ROOTS = ("backend/app", "backend/scripts", "backend/run.py", "deerflow_bridge", "drf2", "scripts")
_ENV_NAME_SHAPE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _oracle_python_sources():
    for relative in _ORACLE_SOURCE_ROOTS:
        root = _REPO_ROOT / relative
        if root.is_file():
            yield root
            continue
        for path in sorted(root.rglob("*.py")):
            if not {".venv", "node_modules", "__pycache__"} & set(path.parts):
                yield path


def _is_environ(node):
    return ((isinstance(node, ast.Attribute) and node.attr == "environ")
            or (isinstance(node, ast.Name) and node.id == "environ"))


def _reads_environment(function):
    return any(_is_environ(node) or (isinstance(node, ast.Attribute) and node.attr == "getenv")
               for node in ast.walk(function))


def _env_names_read_by_sources():
    """Env names the DRF sources read, found by walking their ASTs.

    A name counts when it reaches os.environ.get / pop / setdefault,
    os.environ[...], ``in os.environ`` or os.getenv, either directly or as the
    first argument of a helper whose body reads the environment (_env_flag,
    _cfg_int, _resolve_credential_path, ...), as a literal or through a
    module-level string constant.
    """
    trees = [ast.parse(path.read_text(encoding="utf-8"), str(path)) for path in _oracle_python_sources()]
    helpers = {node.name for tree in trees for node in ast.walk(tree)
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.args.args and _reads_environment(node)}
    names = set()
    for tree in trees:
        constants = {target.id: node.value.value for node in tree.body if isinstance(node, ast.Assign)
                     and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
                     for target in node.targets if isinstance(target, ast.Name)}

        def resolve(expr, constants=constants):
            if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
                return expr.value
            return constants.get(expr.id) if isinstance(expr, ast.Name) else None

        for node in ast.walk(tree):
            key = None
            if isinstance(node, ast.Call) and node.args:
                func = node.func
                called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                environ_method = (isinstance(func, ast.Attribute) and _is_environ(func.value)
                                  and called in ("get", "pop", "setdefault"))
                if environ_method or called == "getenv" or called in helpers:
                    key = resolve(node.args[0])
            elif isinstance(node, ast.Subscript) and _is_environ(node.value):
                key = resolve(node.slice)
            elif (isinstance(node, ast.Compare) and any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops)
                  and any(_is_environ(c) for c in node.comparators)):
                key = resolve(node.left)
            if key and _ENV_NAME_SHAPE.match(key):
                names.add(key)
    return names


def test_scrub_covers_every_env_name_the_sources_read():
    read = _env_names_read_by_sources()
    # Knobs that once survived the scrub (read outside config.py, via helpers or constants).
    assert {"REPORT_META_CHARTS", "SIM_ACTOR_ROLE_PROMPT_MAX_CHARS", "GLOBAL_ACTOR_BLOCK_CHARS",
            "FIRECRAWL_API_URL", "DEERFLOW_RESEARCH_MODEL", "CODEX_AUTH_PATH",
            "DEERFLOW_CLAUDE_PROMPT_CACHE"} <= read
    environ = dict.fromkeys(read, "ambient")
    _hermetic.scrub_ambient_env(environ)
    survivors = sorted(name for name in environ
                       if name not in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE") and not _hermetic._is_protected(name))
    assert survivors == []


def test_hostile_ambient_knobs_never_reach_the_suite(pytester, monkeypatch):
    hostile = {
        "LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-hostile", "REPORT_META_CHARTS": "true",
        "SIM_ACTOR_ROLE_PROMPT_MAX_CHARS": "50", "GLOBAL_ACTOR_BLOCK_CHARS": "100",
        "DEERFLOW_RESEARCH_MODEL": "bogus-model", "FIRECRAWL_API_URL": "https://firecrawl.example",
        "CODEX_AUTH_PATH": "/nonexistent/auth.json", "START_BACKEND_TIMEOUT_SECONDS": "0",
    }
    for name, value in hostile.items():
        monkeypatch.setenv(name, value)
    result = _run_inner_session(pytester, f"""
import os


def test_ambient_knobs_were_scrubbed_before_app_import():
    assert sorted(set({sorted(hostile)!r}) & set(os.environ)) == []
""")
    result.assert_outcomes(passed=1)


def test_this_session_started_from_a_scrubbed_environment():
    baseline = _hermetic.ENV_BASELINE
    assert baseline is not None
    assert baseline["DRF_TEST_PROCESS"] == "1"
    assert baseline["HF_HUB_OFFLINE"] == "1" and baseline["TRANSFORMERS_OFFLINE"] == "1"
    drift = _hermetic._env_drift()
    set_by_the_harness = {"DRF_TEST_PROCESS", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"}
    steering = _hermetic._steering_names(_hermetic.REPO_ROOT) - set_by_the_harness
    leaked = [name for name in baseline
              if not _hermetic._is_protected(name)
              and (drift.is_secret(name) or _hermetic._is_egress_name(name) or name in steering)]
    assert leaked == []


# ---------------------------------------------------------------------------
# Collection-time env mutation check
# ---------------------------------------------------------------------------

def test_env_mutations_reports_new_or_changed_non_empty_values_only():
    baseline = {"KEPT": "1", "CHANGED": "old"}
    environ = {"KEPT": "1", "CHANGED": "new", "ADDED": "x", "BLANK_KEY": "",
               "GRAPHITI_MAX_COROUTINES": "16", "TOKENIZERS_PARALLELISM": "false"}
    assert _hermetic.env_mutations(baseline, environ) == ["ADDED", "CHANGED"]


def test_import_time_env_mutation_stops_the_session(pytester):
    result = _run_inner_session(pytester, """
import os

os.environ["FOO_KEY"] = "x"


def test_never_runs():
    pass
""")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*test collection mutated os.environ at import time: FOO_KEY*"])
    assert "test_never_runs" not in result.stdout.str()


def test_import_time_egress_stops_the_session(pytester):
    """The guard is armed when the conftest is imported, so a test module (or an app
    module it imports) that reaches out at import time is refused, even if it swallows
    the error, and the session stops before the first test."""
    result = _run_inner_session(pytester, """
import socket
import subprocess

# Stand-ins for an import-time model download and a provider CLI probe.
try:
    socket.getaddrinfo("import-time.invalid", 443)
except OSError:
    pass
try:
    subprocess.Popen(["claude", "--version"], env={"PATH": "/nonexistent-drf-test-path"})
except OSError:
    pass


def test_never_runs():
    pass
""")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert ("ERROR: egress refused during pytest start-up or test collection: "
            "DNS lookup of 'import-time.invalid' (before the first test); "
            "subprocess spawn of ['claude', '--version'] (refused: ['claude']) (before the first test)."
            in result.stderr.str())
    assert "test_never_runs" not in result.stdout.str()


# ---------------------------------------------------------------------------
# Egress guard: in-process checks
# ---------------------------------------------------------------------------

def test_loopback_connect_is_refused_without_localhost_marker(_no_egress):
    with _loopback_listener() as server:
        with pytest.raises(_hermetic.EgressRefused):
            socket.create_connection(server.getsockname(), timeout=2)
    refusals = _no_egress.take_refusals()
    assert len(refusals) == 1 and "127.0.0.1" in refusals[0]


@pytest.mark.localhost
def test_localhost_marker_allows_a_local_listening_socket():
    with _loopback_listener() as server:
        client = socket.create_connection(server.getsockname(), timeout=2)
        conn, _ = server.accept()
        try:
            client.sendall(b"ping")
            assert conn.recv(4) == b"ping"
        finally:
            conn.close()
            client.close()


@pytest.mark.localhost
def test_localhost_marker_still_refuses_non_loopback_addresses(_no_egress):
    with pytest.raises(_hermetic.EgressRefused):
        socket.create_connection(("192.0.2.1", 80), timeout=2)  # TEST-NET-1: never routable
    refusals = _no_egress.take_refusals()
    assert len(refusals) == 1 and "192.0.2.1" in refusals[0]


def test_connect_ex_is_guarded_too(_no_egress):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(_hermetic.EgressRefused):
            sock.connect_ex(("192.0.2.1", 80))
    finally:
        sock.close()
    assert len(_no_egress.take_refusals()) == 1


def test_unix_domain_sockets_are_not_guarded():
    workdir = tempfile.mkdtemp(prefix="drf", dir="/tmp")  # AF_UNIX paths are length-limited
    path = os.path.join(workdir, "s")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(path)
        server.listen(1)
        client.connect(path)
    finally:
        client.close()
        server.close()
        shutil.rmtree(workdir, ignore_errors=True)


def test_dns_lookup_of_a_hostname_is_refused(_no_egress):
    with pytest.raises(OSError):
        socket.getaddrinfo("example.com", 443)
    assert _no_egress.take_refusals() == ["DNS lookup of 'example.com'"]


def test_dns_allows_localhost_and_ip_literals():
    assert socket.getaddrinfo("127.0.0.1", 80)
    assert socket.getaddrinfo("::1", 80)
    assert socket.getaddrinfo("localhost", 80)
    assert socket.getaddrinfo(None, 80)
    assert socket.gethostbyname("127.0.0.1") == "127.0.0.1"


def test_the_other_resolvers_are_guarded_too(_no_egress):
    for resolve, name in ((socket.gethostbyname, "example.com"), (socket.gethostbyname_ex, "example.com"),
                          (socket.gethostbyaddr, "example.com"), (socket.gethostbyaddr, "192.0.2.1")):
        with pytest.raises(_hermetic.EgressRefused):
            resolve(name)
    assert _no_egress.take_refusals() == ["DNS lookup of 'example.com'"] * 3 + ["reverse DNS lookup of '192.0.2.1'"]


def test_reverse_lookup_is_allowed_for_loopback_only():
    guard = _hermetic.EgressGuard()  # never installed: the check is called directly
    guard.activate()
    for address in ("127.0.0.1", "::1", "localhost"):
        guard._check_reverse_resolve(address)
    assert guard.take_refusals() == []


def test_datagrams_to_the_network_are_refused(_no_egress):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(_hermetic.EgressRefused):
            sock.sendto(b"x", ("192.0.2.1", 9))
        with pytest.raises(_hermetic.EgressRefused):
            sock.sendto(b"x", 0, ("192.0.2.1", 9))
        with pytest.raises(_hermetic.EgressRefused):
            sock.sendmsg([b"x"], [], 0, ("192.0.2.1", 9))
    finally:
        sock.close()
    assert _no_egress.take_refusals() == [
        "socket sendto ('192.0.2.1', 9)", "socket sendto ('192.0.2.1', 9)", "socket sendmsg ('192.0.2.1', 9)"]


@pytest.mark.localhost
def test_localhost_marker_allows_loopback_datagrams():
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        server.bind(("127.0.0.1", 0))
        server.settimeout(5)
        client.sendto(b"ping", server.getsockname())
        assert server.recv(4) == b"ping"
    finally:
        client.close()
        server.close()


_MISSING_DIR = "/nonexistent-drf-test-path"
_NO_PATH = {"PATH": _MISSING_DIR}  # if the guard ever failed, nothing would spawn


@pytest.mark.parametrize("argv,kwargs", [
    (["claude", "-p", "x"], {}),
    (["/usr/local/bin/codex", "exec", "x"], {}),
    (["curl", "https://example.com"], {}),
    (["wget", "https://example.com"], {}),
    ("claude -p x", {"shell": True}),
    ("cd /tmp && codex exec x", {"shell": True}),
    (["python3", "/nonexistent/backend/scripts/run_parallel_simulation.py", "--config", "c.json"], {}),
    (["python3", "run_twitter_simulation.py"], {}),
    (["python3", "/nonexistent/deerflow_research.py", "--query", "q"], {}),
    (["python3", "/nonexistent/resolution_monitor.py", "run", "--all-recent"], {}),
    (["whatever"], {"executable": "claude"}),
    (["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"], {}),
    (["sh", "-c", "claude -p x"], {}),
    (["env", "FOO=1", "codex", "exec"], {}),
    (["timeout", "60", "claude", "-p", "x"], {}),
])
def test_provider_cli_and_pipeline_child_spawns_are_refused(_no_egress, argv, kwargs):
    with pytest.raises(PermissionError):
        subprocess.Popen(argv, env=_NO_PATH, **kwargs)
    assert len(_no_egress.take_refusals()) == 1


def test_os_level_spawners_are_guarded(_no_egress):
    # Every program path below is missing, so a guard failure could not start anything.
    with pytest.raises(_hermetic.EgressRefused):
        os.system(f"{_MISSING_DIR}/codex exec x")
    with pytest.raises(_hermetic.EgressRefused):
        os.posix_spawn(f"{_MISSING_DIR}/claude", ["claude", "-p", "x"], {})
    with pytest.raises(_hermetic.EgressRefused):
        os.posix_spawnp(f"{_MISSING_DIR}/claude", ["claude", "-p", "x"], {})
    with pytest.raises(_hermetic.EgressRefused):
        os.execv(f"{_MISSING_DIR}/curl", ["curl", "https://example.com"])
    with pytest.raises(_hermetic.EgressRefused):
        os.execve(f"{_MISSING_DIR}/wget", ["wget", "https://example.com"], {})
    assert len(_no_egress.take_refusals()) == 5


def test_subprocess_run_is_refused_through_popen(_no_egress):
    with pytest.raises(_hermetic.EgressRefused):
        subprocess.run(["claude", "-p", "x"], env=_NO_PATH, capture_output=True, check=False)
    assert len(_no_egress.take_refusals()) == 1


def test_ordinary_children_are_allowed():
    subprocess.run([sys.executable, "-c", "pass"], check=True)
    out = subprocess.check_output(iter([sys.executable, "-c", "print('ok')"]), text=True)
    assert out.strip() == "ok"


@pytest.mark.subprocess_egress
def test_subprocess_egress_marker_lets_provider_clis_through():
    with pytest.raises(FileNotFoundError):  # reached the real exec: not refused
        subprocess.Popen(["claude", "--version"], env=_NO_PATH)


def test_real_popen_fixture_bypasses_the_guard(_no_egress, real_popen):
    with pytest.raises(FileNotFoundError):
        real_popen(["codex", "--version"], env=_NO_PATH)
    proc = real_popen([sys.executable, "-c", "pass"])
    assert proc.wait(timeout=30) == 0
    assert _no_egress.take_refusals() == []


def test_real_popen_fixture_also_bypasses_the_os_level_spawn_hooks(_no_egress, real_popen):
    # A program path with close_fds=False lets Popen spawn through os.posix_spawn where available.
    with pytest.raises(FileNotFoundError):
        real_popen([f"{_MISSING_DIR}/codex", "--version"], close_fds=False)
    assert _no_egress.take_refusals() == []


def test_real_socket_connect_fixture_bypasses_the_guard(_no_egress, real_socket_connect):
    with _loopback_listener() as server:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            real_socket_connect(client, server.getsockname())
        finally:
            client.close()
    assert _no_egress.take_refusals() == []


def test_refusals_from_background_threads_are_recorded(_no_egress):
    errors = []

    def worker():
        try:
            socket.create_connection(("192.0.2.1", 80), timeout=2)
        except OSError as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=30)
    assert len(errors) == 1 and isinstance(errors[0], _hermetic.EgressRefused)
    assert len(_no_egress.take_refusals()) == 1


def test_guard_passes_everything_through_when_no_policy_is_active():
    guard = _hermetic.EgressGuard()
    guard._check_address(SimpleNamespace(family=socket.AF_INET), ("192.0.2.1", 80), "connect to")
    guard._check_resolve("example.com")
    guard._check_reverse_resolve("192.0.2.1")
    guard._check_spawn(["claude", "-p", "x"], None, False)
    assert guard.take_refusals() == []


def test_between_tests_policy_refuses_everything_and_labels_the_record():
    guard = _hermetic.EgressGuard()  # never installed: the checks are called directly
    guard.idle()
    with pytest.raises(_hermetic.EgressRefused):
        guard._check_address(SimpleNamespace(family=socket.AF_INET), ("127.0.0.1", 80), "connect to")
    with pytest.raises(_hermetic.EgressRefused):
        guard._check_resolve("example.com")
    with pytest.raises(_hermetic.EgressRefused):
        guard._check_spawn(["claude", "-p", "x"], None, False)
    guard.activate(allow_loopback=True, allow_subprocess=True)  # a policy switch keeps the record
    refusals = guard.take_refusals()
    assert len(refusals) == 3
    assert all(r.endswith("(between tests: a thread or fixture outlived its test)") for r in refusals)
    guard.exempt()
    guard._check_resolve("example.com")
    assert guard.policy is None and guard.take_refusals() == []


@pytest.mark.parametrize("argv,refused", [
    (["git", "log", "--", "backend/scripts/run_parallel_simulation.py"], False),
    (["ruff", "check", "deerflow_bridge/deerflow_research.py"], False),
    (["uv", "run", "python", "backend/scripts/run_twitter_simulation.py"], True),
    (["uv", "run", "backend/scripts/run_parallel_simulation.py"], True),
    (["uv", "--directory", "backend", "run", "--no-sync", "python", "-u", "x/deerflow_research.py"], True),
    (["uv", "run", "--no-sync", "pytest", "-q"], False),
    (["uv", "pip", "list"], False),
    (["/venv/bin/python3.12", "-u", "/x/deerflow_research.py", "--query", "q"], True),
    (["/x/backend/scripts/run_reddit_simulation.py", "--config", "c.json"], True),
])
def test_pipeline_child_scripts_are_refused_only_when_run(argv, refused):
    guard = _hermetic.EgressGuard()
    guard.activate()
    try:
        guard._check_spawn(argv, None, False)
    except _hermetic.EgressRefused:
        assert refused, argv
    else:
        assert not refused, argv
    assert len(guard.take_refusals()) == int(refused)


@pytest.mark.parametrize("args,shell,refused", [
    # shells running an inline command line
    (["sh", "-c", "claude -p x"], False, True),
    (["/bin/bash", "-lc", "curl https://example.com"], False, True),
    (["bash", "-o", "pipefail", "-c", "ls | wget https://example.com"], False, True),
    (["sh", "-c", "sh -c 'codex exec x'"], False, True),
    (["sh", "script.sh"], False, False),
    # launchers in front of the program
    (["env", "claude", "-p", "x"], False, True),
    (["env", "-i", "-u", "HOME", "FOO=1", "codex", "exec"], False, True),
    (["env", "-S", "claude -p x"], False, True),
    (["timeout", "-s", "KILL", "60", "claude", "-p", "x"], False, True),
    (["nice", "-n", "5", "nohup", "stdbuf", "-oL", "xargs", "-I", "{}", "codex", "{}"], False, True),
    (["env", "python3", "-c", "pass"], False, False),
    (["env", "-", "claude", "-p", "x"], False, True),             # env's bare '-' is -i
    (["command", "claude", "-p", "x"], False, True),
    # shell option parsing as bash / zsh / dash do it
    (["bash", "--rcfile", "rc.sh", "-c", "claude -p x"], False, True),
    (["bash", "--init-file", "rc.sh", "-c", "claude -p x"], False, True),
    (["zsh", "--emulate", "sh", "-c", "claude -p x"], False, True),
    (["bash", "-c", "--", "claude -p x"], False, True),
    (["sh", "-c", "-", "codex exec x"], False, True),
    (["bash", "-c", "-x", "claude -p x"], False, True),
    (["bash", "-eo", "pipefail", "-c", "claude -p x"], False, True),
    (["bash", "-co", "pipefail", "claude -p x"], False, True),
    (["bash", "-o", "pipefail", "script.sh", "claude"], False, False),
    (["bash", "--rcfile", "rc.sh", "script.sh"], False, False),
    # looking a provider CLI up does not run it
    (["command", "-v", "claude"], False, False),
    ("command -V codex", True, False),
    ("type claude", True, False),
    ("if command -v claude >/dev/null; then echo ok; fi", True, False),
    # provider CLIs through JavaScript launchers
    (["npx", "@anthropic-ai/claude-code"], False, True),
    (["npx", "-y", "@openai/codex@latest", "exec", "x"], False, True),
    (["node", "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js", "-p", "x"], False, True),
    (["node", "/x/claude-code/cli.js"], False, True),
    (["pnpm", "dlx", "codex"], False, True),
    (["node", "script.js", "--model", "claude"], False, False),
    # shell=True lines: only words in command position are programs
    ("ls /tmp/claude", True, False),
    ("echo claude codex", True, False),
    ("grep -r run_parallel_simulation.py backend", True, False),
    ("cd /tmp && FOO=1 codex exec x > out.txt", True, True),
    ("echo $(claude -p x)", True, True),
    ("echo `wget https://example.com`", True, True),
    ("if claude -p x; then echo ok; fi", True, True),
    ("python3 backend/scripts/run_reddit_simulation.py", True, True),
])
def test_spawn_check_looks_through_shells_and_launchers(args, shell, refused):
    guard = _hermetic.EgressGuard()  # never installed: the check is called directly
    guard.activate()
    try:
        guard._check_spawn(args, None, shell)
    except _hermetic.EgressRefused:
        assert refused, args
    else:
        assert not refused, args
    assert len(guard.take_refusals()) == int(refused)


def test_spawn_check_judges_an_exec_through_a_file_descriptor_by_argv():
    """os.execve(fd, argv, env) (fexecve) hands the check an int, not a path."""
    guard = _hermetic.EgressGuard()  # never installed: the check is called directly
    guard.activate()
    guard._check_spawn(["python3", "-c", "pass"], 7, False)
    with pytest.raises(_hermetic.EgressRefused):
        guard._check_spawn(["claude", "-p", "x"], 7, False)
    assert len(guard.take_refusals()) == 1


# ---------------------------------------------------------------------------
# Egress guard: swallowed refusals fail the test (pytester)
# ---------------------------------------------------------------------------

def test_swallowed_egress_attempts_still_fail_the_test(pytester):
    result = _run_inner_session(pytester, """
import os
import socket
import subprocess
import sys

import pytest

# Allowed import-time side effects: an allowlisted setdefault and an empty key_env.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("DRF_INNER_EMPTY_API_KEY", "")


def test_swallowed_dns():
    try:
        socket.create_connection(("example.com", 80), timeout=2)
    except OSError:
        pass


def test_swallowed_ip_connect():
    try:
        socket.create_connection(("192.0.2.1", 80), timeout=2)
    except OSError:
        pass


def test_swallowed_cli_spawn():
    try:
        subprocess.Popen(["claude", "-p", "x"], env={"PATH": "/nonexistent-drf-test-path"})
    except OSError:
        pass


def test_python_child_is_fine():
    subprocess.run([sys.executable, "-c", "pass"], check=True)


@pytest.mark.integration
def test_integration_tests_are_exempt(_no_egress):
    assert _no_egress.policy is None
""")
    result.assert_outcomes(passed=5, errors=3)
    result.stdout.fnmatch_lines([
        "*ERROR at teardown of test_swallowed_dns*",
        "*egress refused during this test*DNS lookup of 'example.com'*",
        "*ERROR at teardown of test_swallowed_ip_connect*",
        "*egress refused during this test*socket connect to ('192.0.2.1', 80)*",
        "*ERROR at teardown of test_swallowed_cli_spawn*",
        "*egress refused during this test*subprocess spawn of ['claude', '-p', 'x']*",
    ])
    result.stdout.fnmatch_lines([
        "PASSED test_inner.py::test_python_child_is_fine",
        "PASSED test_inner.py::test_integration_tests_are_exempt",
    ])


def test_policy_covers_higher_scoped_fixtures_and_the_gap_between_tests(pytester):
    """The policy is applied before any fixture of the test, whatever its scope, and
    egress between two tests is refused and reported by the next test."""
    result = _run_inner_session(pytester, """
import socket

import pytest

import _hermetic


@pytest.fixture(scope="module")
def module_resource():
    try:
        socket.getaddrinfo("example.com", 80)
    except OSError:
        pass
    return "resource"


def test_module_fixture_egress_is_charged_to_the_first_user(module_resource):
    pass


def test_later_user_of_the_module_fixture(module_resource):
    pass


@pytest.fixture(scope="class")
def class_scoped_policy():
    return _hermetic.EGRESS_GUARD.policy


@pytest.mark.integration
class TestIntegration:
    def test_higher_scoped_fixtures_of_an_integration_test_are_exempt(self, class_scoped_policy):
        assert class_scoped_policy is None


def test_leaves_work_running_after_its_teardown():
    pass


def test_next_test_reports_the_gap():
    pass
""", conftest_extra="""

def pytest_runtest_logreport(report):
    # Runs after the teardown hooks: stands in for a thread that outlived its test.
    if report.when == "teardown" and report.nodeid.endswith("test_leaves_work_running_after_its_teardown"):
        import socket
        try:
            socket.getaddrinfo("example.org", 80)
        except OSError:
            pass
""")
    result.assert_outcomes(passed=5, errors=2)
    result.stdout.fnmatch_lines([
        "*ERROR at teardown of test_module_fixture_egress_is_charged_to_the_first_user*",
        "*egress refused during this test*DNS lookup of 'example.com'*",
        "*ERROR at teardown of test_next_test_reports_the_gap*",
        "*egress refused during this test*DNS lookup of 'example.org' (between tests: *",
    ])
    result.stdout.fnmatch_lines([
        "PASSED test_inner.py::test_later_user_of_the_module_fixture",
        "PASSED test_inner.py::TestIntegration::test_higher_scoped_fixtures_of_an_integration_test_are_exempt",
        "PASSED test_inner.py::test_leaves_work_running_after_its_teardown",
    ])


def test_egress_while_higher_scoped_fixtures_are_torn_down_fails_that_teardown(pytester):
    """Refusals after _no_egress's check fail the teardown that finalized the fixture
    (as pytest reports its errors), never an innocent later test."""
    result = _run_inner_session(pytester, {
        "test_a": """
import socket

import pytest


def _swallowed_lookup(host):
    try:
        socket.getaddrinfo(host, 80)
    except OSError:
        pass


@pytest.fixture(scope="session")
def session_resource():
    yield
    _swallowed_lookup("session-teardown.example")


@pytest.fixture(scope="module")
def module_resource():
    yield
    _swallowed_lookup("module-teardown.example")


def test_a1(session_resource, module_resource):
    pass


def test_a2(module_resource):
    pass
""",
        "test_b": """
def test_b1():
    pass
""",
    })
    result.assert_outcomes(passed=3, errors=2)
    result.stdout.fnmatch_lines([
        "*ERROR at teardown of test_a2*",
        "*egress refused while tearing down this test's fixtures (any scope): "
        "DNS lookup of 'module-teardown.example'",
        "*ERROR at teardown of test_b1*",
        "*egress refused while tearing down this test's fixtures (any scope): "
        "DNS lookup of 'session-teardown.example'",
    ])
    result.stdout.fnmatch_lines(["PASSED test_a.py::test_a1", "PASSED test_a.py::test_a2", "PASSED test_b.py::test_b1"])
    assert "between tests" not in result.stdout.str()


def test_tests_outside_the_harness_directory_run_exempt(pytester):
    """pytest calls a conftest's runtest hooks only for the items under its directory.
    A sibling directory's tests in the same session (``pytest .`` from the repo root
    collects backend/scripts/test_*.py) run exempt instead of under the between-tests
    policy, nothing is charged to the next harness test, and the harness policy still
    applies to the harness tests after them."""
    _make_inner_ini(pytester)
    harness = pytester.mkdir("harness")
    (harness / "conftest.py").write_text(_conftest_shim(), encoding="utf-8")
    (harness / "test_before.py").write_text("def test_owned_before():\n    pass\n", encoding="utf-8")
    (harness / "test_after.py").write_text("""
import socket


def test_owned_after_is_guarded_again():
    try:
        socket.getaddrinfo("owned-after.invalid", 80)
    except OSError:
        pass
""", encoding="utf-8")
    outside = pytester.mkdir("outside")
    (outside / "test_outside.py").write_text("""
import socket

import pytest

import _hermetic


@pytest.mark.localhost
def test_marked_loopback_outside_the_harness():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        socket.create_connection(server.getsockname(), timeout=2).close()
    finally:
        server.close()


def test_unmarked_test_outside_the_harness_is_exempt():
    assert _hermetic.EGRESS_GUARD.installed and _hermetic.EGRESS_GUARD.policy is None
""", encoding="utf-8")
    result = pytester.runpytest_subprocess(
        "-rA", "harness/test_before.py", "outside", "harness/test_after.py", timeout=180)
    result.assert_outcomes(passed=4, errors=1)
    result.stdout.fnmatch_lines([
        "*ERROR at teardown of test_owned_after_is_guarded_again*",
        "*egress refused during this test*DNS lookup of 'owned-after.invalid'",
    ])
    result.stdout.fnmatch_lines([
        "PASSED harness/test_before.py::test_owned_before",
        "PASSED outside/test_outside.py::test_marked_loopback_outside_the_harness",
        "PASSED outside/test_outside.py::test_unmarked_test_outside_the_harness_is_exempt",
    ])
    assert "between tests" not in result.stdout.str()


def test_egress_after_the_last_test_fails_the_session(pytester):
    pytester.makepyfile(late_egress_plugin="""
import socket

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session):
    # Stands in for a thread that outlived the last test.
    try:
        socket.getaddrinfo("after-the-last-test.example", 80)
    except OSError:
        pass
""")
    result = _run_inner_session(pytester, "def test_passes():\n    pass\n", "", "-p", "late_egress_plugin")
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.stdout.fnmatch_lines([
        "*egress refused outside any test*",
        "egress refused after the last test's teardown: DNS lookup of 'after-the-last-test.example' (between tests*",
    ])
    result.assert_outcomes(passed=1)


# ---------------------------------------------------------------------------
# Process-global state reset
# ---------------------------------------------------------------------------

def test_process_global_state_does_not_leak_into_the_next_test(pytester):
    result = _run_inner_session(pytester, """
import time

from app.utils import llm_client as lc
from app.utils import telemetry as tel


def test_a_leaves_state_behind():
    lc._CB_STATE["leaky"] = {"consec": 9.0, "tripped_until": time.monotonic() + 600}
    lc._FB_OPENAI_CLIENTS[("p", "m", "u")] = object()
    lc._FB_AUTH_UNAVAILABLE_UNTIL[("p", "m", "u")] = time.monotonic() + 600
    lc._FB_MISCONFIG_WARNED.add("p")
    tel.LLMCache.put("leaky-key", "cached answer")
    tel._COST_OVERRIDE_CACHE["{}"] = {}


def test_b_starts_clean():
    assert "leaky" not in lc._CB_STATE
    assert lc._FB_OPENAI_CLIENTS == {} and lc._FB_AUTH_UNAVAILABLE_UNTIL == {}
    assert lc._FB_MISCONFIG_WARNED == set()
    assert tel.LLMCache.get("leaky-key") is None and tel.LLMCache._order == []
    assert tel._COST_OVERRIDE_CACHE == {}
""")
    result.assert_outcomes(passed=2)


def test_reset_uninstalls_the_outage_probe_and_clears_run_breakers():
    from app.services import pipeline_orchestrator as po
    from app.utils.llm_client import LLMClient

    original_chat = LLMClient.chat
    assert po._install_llm_outage_probe()
    with po._RUN_OUTAGE_LOCK:
        po._RUN_OUTAGE_BREAKERS["run-x"] = object()
    assert getattr(LLMClient.chat, "_drf_outage_probe", False)

    _hermetic.reset_process_globals()

    assert LLMClient.chat is original_chat
    assert po._RUN_OUTAGE_BREAKERS == {}


def test_reset_tolerates_a_patched_llm_client_class_and_removes_the_probe_next_pass():
    """The teardown pass runs before monkeypatch undo, so LLMClient may still be a double."""
    from app.services import pipeline_orchestrator as po
    from app.utils import llm_client as lc

    original_chat = lc.LLMClient.chat
    assert po._install_llm_outage_probe()
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(lc, "LLMClient", type("_ClientDoubleWithoutChat", (), {}))
            _hermetic.reset_process_globals()  # teardown pass: must not raise
        assert getattr(lc.LLMClient.chat, "_drf_outage_probe", False) is True
        _hermetic.reset_process_globals()      # the next test's setup pass
        assert lc.LLMClient.chat is original_chat
    finally:
        po._uninstall_llm_outage_probe()


def test_reset_touches_only_modules_that_are_already_imported():
    before = set(sys.modules)
    _hermetic.reset_process_globals({})
    assert set(sys.modules) == before

    lock = threading.Lock()
    fake_llm_client = SimpleNamespace(
        _CB_LOCK=lock, _CB_STATE={"p": {}}, _FB_OPENAI_CLIENTS={("k",): 1},
        _FB_AUTH_UNAVAILABLE_UNTIL={("k",): 1.0}, _FB_MISCONFIG_WARNED={"p"})
    _hermetic.reset_process_globals({"app.utils.llm_client": fake_llm_client})
    assert fake_llm_client._CB_STATE == {} and fake_llm_client._FB_OPENAI_CLIENTS == {}
    assert fake_llm_client._FB_AUTH_UNAVAILABLE_UNTIL == {} and fake_llm_client._FB_MISCONFIG_WARNED == set()


# ---------------------------------------------------------------------------
# FakeLLMClient parity
# ---------------------------------------------------------------------------

def _named_parameters(func):
    return {p.name for p in inspect.signature(func).parameters.values()
            if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)} - {"self"}


def test_fake_llm_client_accepts_every_parameter_of_the_real_client():
    from app.utils.llm_client import LLMClient

    public = {name for name, member in inspect.getmembers(LLMClient, inspect.isfunction)
              if not name.startswith("_")}
    assert {"chat", "chat_json", "chat_with_tools", "supports_native_tools"} <= public
    for name in sorted(public):
        fake_method = getattr(FakeLLMClient, name, None)
        assert fake_method is not None, f"FakeLLMClient lacks LLMClient.{name}"
        missing = _named_parameters(getattr(LLMClient, name)) - _named_parameters(fake_method)
        assert not missing, f"FakeLLMClient.{name} lacks parameters {sorted(missing)}"


def test_fake_llm_client_records_tier_and_scripts_tool_calls():
    tool_turn = {"content": "", "tool_calls": [{"id": "c1", "name": "search", "arguments": {"q": "x"}}]}
    fake = FakeLLMClient(responses=["r1"], json_responses=[{"a": 1}], tool_responses=[tool_turn])
    msgs = [{"role": "user", "content": "hi"}]

    assert fake.chat(messages=msgs, temperature=0.1, max_tokens=5, response_format=None, tier="fast") == "r1"
    assert fake.chat_json(msgs, tier="strong") == {"a": 1}
    assert fake.chat_with_tools(msgs, [{"type": "function"}], tier="strong") == tool_turn
    assert fake.chat_with_tools(msgs, tools_schema=[]) == {"content": "FAKE_RESPONSE", "tool_calls": []}
    assert fake.chat(msgs) == "FAKE_RESPONSE" and fake.chat_json(msgs) == {}
    assert [c["kind"] for c in fake.calls] == [
        "chat", "chat_json", "chat_with_tools", "chat_with_tools", "chat", "chat_json"]
    assert [c["tier"] for c in fake.calls] == ["fast", "strong", "strong", None, None, None]
    assert fake.calls[2]["tools_schema"] == [{"type": "function"}]
    assert fake.supports_native_tools() is False
    assert fake.last_call_meta() is None


def test_fake_llm_client_keeps_its_positional_constructor_order():
    fake = FakeLLMClient(["r"], [{"a": 1}], "prov", "model-x")
    assert (fake.provider, fake.model) == ("prov", "model-x")
    assert fake.chat([]) == "r" and fake.chat_json([]) == {"a": 1}
    tool_responses = inspect.signature(FakeLLMClient).parameters["tool_responses"]
    assert tool_responses.kind is inspect.Parameter.KEYWORD_ONLY


# ---------------------------------------------------------------------------
# load_project_dotenv
# ---------------------------------------------------------------------------

def _write_env(tmp_path):
    path = tmp_path / ".env"
    path.write_text("DRF_DOTENV_PROBE_NEW=from-file\nDRF_DOTENV_PROBE_SET=from-file\n", encoding="utf-8")
    return str(path)


def test_load_project_dotenv_is_a_no_op_in_the_test_process(tmp_path):
    from app.utils.env_loading import load_project_dotenv

    path = _write_env(tmp_path)
    with mock.patch.dict(os.environ, {"DRF_TEST_PROCESS": "1"}):
        assert load_project_dotenv(path) is False
        assert load_project_dotenv(path, override=True) is False
        assert "DRF_DOTENV_PROBE_NEW" not in os.environ


def test_load_project_dotenv_matches_load_dotenv_outside_the_test_process(tmp_path):
    from dotenv import load_dotenv

    from app.utils.env_loading import load_project_dotenv

    path = _write_env(tmp_path)
    results = {}
    for label, loader in (("helper", load_project_dotenv), ("dotenv", load_dotenv)):
        for override in (False, True):
            with mock.patch.dict(os.environ, {"DRF_DOTENV_PROBE_SET": "ambient"}):
                os.environ.pop("DRF_TEST_PROCESS")
                loaded = loader(path, override=override)
                results[(label, override)] = (
                    loaded, os.environ.get("DRF_DOTENV_PROBE_NEW"), os.environ["DRF_DOTENV_PROBE_SET"])
    assert results[("helper", False)] == results[("dotenv", False)] == (True, "from-file", "ambient")
    assert results[("helper", True)] == results[("dotenv", True)] == (True, "from-file", "from-file")
    assert os.environ["DRF_TEST_PROCESS"] == "1" and "DRF_DOTENV_PROBE_NEW" not in os.environ

    with mock.patch.dict(os.environ):
        os.environ.pop("DRF_TEST_PROCESS")
        assert load_project_dotenv(str(tmp_path / "missing.env")) is False
        assert load_project_dotenv("") is False


@pytest.mark.parametrize("script", [
    "run_parallel_simulation.py", "run_reddit_simulation.py", "run_twitter_simulation.py"])
def test_sim_scripts_load_dotenv_only_through_load_project_dotenv(script):
    tree = ast.parse((_BACKEND_DIR / "scripts" / script).read_text(encoding="utf-8"))
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                for alias in node.names}
    assert "load_project_dotenv" in called
    assert "load_dotenv" not in called and "load_dotenv" not in imported


# ---------------------------------------------------------------------------
# Config._persist_env stub
# ---------------------------------------------------------------------------

def test_persist_env_is_stubbed_and_the_original_is_exposed(real_persist_env):
    from app.config import Config

    env_path = _REPO_ROOT / ".env"
    before = env_path.read_bytes() if env_path.exists() else None
    assert Config._persist_env({"DRF_HERMETIC_PROBE": "1"}) is None
    after = env_path.read_bytes() if env_path.exists() else None
    assert after == before
    assert real_persist_env.__func__.__qualname__ == "Config._persist_env"
    assert Config._persist_env.__func__ is not real_persist_env.__func__


# ---------------------------------------------------------------------------
# Markers and CI
# ---------------------------------------------------------------------------

def test_markers_are_registered_strict_and_integration_is_opt_in(request):
    options = _pyproject_pytest_options()
    registered = {line.split(":", 1)[0] for line in request.config.getini("markers")}
    assert {"integration", "localhost", "subprocess_egress"} <= registered
    assert "--strict-markers" in options["addopts"]
    assert "-m 'not integration'" in options["addopts"]


def test_conftest_does_not_define_pytest_plugins():
    """pytest rejects pytest_plugins in a conftest that is not top-level, which
    breaks `pytest .` from the repo root; pytester is loaded by this module."""
    tree = ast.parse((_TESTS_DIR / "conftest.py").read_text(encoding="utf-8"))
    assigned = {target.id for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
                if isinstance(target, ast.Name)}
    assert "pytest_plugins" not in assigned


def test_ci_cancels_superseded_runs_and_tests_two_timezones():
    workflow = yaml.safe_load((_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    assert workflow["concurrency"]["cancel-in-progress"] is True
    assert "github.ref" in workflow["concurrency"]["group"]
    unit = workflow["jobs"]["unit"]
    assert unit["strategy"]["matrix"]["tz"] == ["", "America/New_York"]
    assert unit["env"]["TZ"] == "${{ matrix.tz }}"
    runs = [step.get("run", "") for step in unit["steps"]]
    assert not any("uv venv" in run or "uv pip install" in run for run in runs)
    assert any("uv run pytest" in run for run in runs)
