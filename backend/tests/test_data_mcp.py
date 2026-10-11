"""Hermetic tests for deerflow_bridge/data_mcp.py (official-data MCP hub, design.md §3).

The bridge directory is put on sys.path and the module is imported by bare name
(same pattern as test_research_gateway.py).  No network, no node, no built data
servers: ``tests/fixtures/fake_mcp_server.py`` (a FastMCP stdio server run with
this interpreter) stands in for them, and ``default_server_specs`` is exercised
against a temporary ``datamcps`` tree with fake entry files and a fake ``node``.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BRIDGE_DIR = os.path.join(_REPO_ROOT, "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import data_mcp as dm  # noqa: E402

FAKE_SERVER = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"
SECRET = "s3cr3t-value-0123456789abcdef"
PARENT_ONLY = "DRF_TEST_PARENT_ONLY_VAR"


# =============================================================== helpers

class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def fake_spec(name: str, cwd: Path, *, extra_args: tuple[str, ...] = (), env: dict | None = None,
              start_timeout: float = 20.0, call_timeout: float = 10.0, max_concurrency: int = 4,
              command: str | None = None, unavailable_reason: str | None = None) -> dm.ServerSpec:
    cwd.mkdir(parents=True, exist_ok=True)
    return dm.ServerSpec(
        name=name,
        command=command or sys.executable,
        args=(str(FAKE_SERVER), *extra_args) if command is None else extra_args,
        env=dict(env or {}),
        cwd=str(cwd),
        start_timeout=start_timeout,
        call_timeout=call_timeout,
        max_concurrency=max_concurrency,
        unavailable_reason=unavailable_reason,
    )


def wait_for(predicate, timeout: float = 5.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def pid_gone(pid: int) -> bool:
    """True when ``pid`` no longer exists (or is only a zombie awaiting its reaper)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return state.startswith("Z") or state == ""


def make_executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)
    return path


def fake_node(directory: Path, version: str = "v22.4.0", counter: Path | None = None) -> Path:
    count_line = f'echo x >> "{counter}"\n' if counter else ""
    return make_executable(directory / "node", (
        "#!/bin/sh\n" + count_line +
        f'if [ "$1" = "--version" ]; then echo {version}; exit 0; fi\nexit 1\n'))


def build_datamcps(root: Path, *, server_launcher: str | None = None) -> Path:
    """A datamcps tree whose every build output exists (contents are placeholders)."""
    for layout in dm._LAYOUTS.values():
        folder = root / layout.folder
        for rel in layout.required:
            target = folder / rel
            if rel == "node_modules":
                target.mkdir(parents=True, exist_ok=True)
            elif layout.runtime == "venv" and rel == layout.entry:
                make_executable(target, server_launcher or "#!/bin/sh\nexit 0\n")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("// placeholder\n")
    return root


@pytest.fixture
def tree(tmp_path):
    """(datamcps root, base env) with a fake node v22 on PATH and a tmp cache dir."""
    root = build_datamcps(tmp_path / "datamcps")
    node = fake_node(tmp_path / "nodebin")
    env = {"PATH": os.pathsep.join([str(node.parent), "/usr/bin", "/bin"]), "HOME": str(tmp_path / "home"),
           "DATA_SOURCES_CACHE_DIR": str(tmp_path / "cache")}
    return root, env


@pytest.fixture(scope="module")
def shared(tmp_path_factory):
    """One ready fake server shared by the read-only tests (saves a spawn per test)."""
    base = tmp_path_factory.mktemp("hub")
    spec = fake_spec("fake", base / "cwd", env={"FAKE_API_KEY": SECRET, "LISTED_VAR": "abc", "EMPTY_VAR": ""},
                     call_timeout=10.0, max_concurrency=4)
    hub = dm.McpHub({"fake": spec}, errlog_dir=base / "logs")
    os.environ[PARENT_ONLY] = "must-not-leak"
    try:
        hub.start(wait=30)
    finally:
        os.environ.pop(PARENT_ONLY, None)
    assert hub.status()["fake"]["state"] == "ready", hub.status()
    yield hub, base
    hub.close()


# =============================================================== hub: happy path

def test_start_list_and_call(shared):
    hub, _ = shared
    status = hub.status()["fake"]
    assert status["state"] == "ready" and status["error"] is None
    assert isinstance(status["ready_s"], float) and status["ready_s"] > 0
    assert {"echo", "sleep", "fail", "crash", "env_probe", "cwd_probe", "pid", "table"} <= set(hub.tool_names("fake"))
    assert set(status) == {"state", "error", "tools", "ready_s", "calls", "failures"}

    result = hub.call("fake", "echo", {"text": "hello"})
    assert result.ok and result.text == "hello" and result.error is None and not result.is_tool_error
    assert result.elapsed_s >= 0

    table = hub.call("fake", "table", {"rows": 2})
    assert table.ok and json.loads(table.text)["rows"][1]["value"] == 1.5
    assert table.structured == {"rows": [{"i": 0, "value": 0.0}, {"i": 1, "value": 1.5}]}
    assert hub.tool_names("nope") == []


def test_concurrent_calls_from_eight_threads(shared):
    hub, _ = shared
    results: list = [None] * 8

    def worker(index: int) -> None:
        results[index] = hub.call("fake", "sleep", {"seconds": 0.4})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    started = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    elapsed = time.monotonic() - started
    assert all(r is not None and r.ok and r.text == "slept 0.4" for r in results), results
    # max_concurrency=4 → two waves of 0.4 s, never all eight at once.
    assert 0.75 <= elapsed < 10, elapsed


def test_call_timeout_then_server_still_usable(shared):
    hub, _ = shared
    started = time.monotonic()
    result = hub.call("fake", "sleep", {"seconds": 5}, timeout=0.5)
    assert not result.ok and "timed out after 0.5s" in result.error
    assert time.monotonic() - started < 3
    assert hub.call("fake", "echo", {"text": "still here"}).text == "still here"
    for bad_timeout in (0, -1, float("nan"), "soon"):
        bad = hub.call("fake", "echo", {"text": "x"}, timeout=bad_timeout)
        assert not bad.ok and "timeout must be > 0" in bad.error


def test_tool_error_and_input_errors(shared):
    hub, _ = shared
    before = hub.status()["fake"]
    failed = hub.call("fake", "fail", {"message": "series not found"})
    assert not failed.ok and failed.is_tool_error
    assert "series not found" in failed.text and "series not found" in failed.error

    unknown = hub.call("fake", "no_such_tool", {})
    assert not unknown.ok and not unknown.is_tool_error and "unknown tool 'no_such_tool'" in unknown.error
    assert not hub.call("fake", "echo", ["not", "a", "mapping"]).ok
    assert not hub.call("fake", "", {}).ok
    missing = hub.call("missing-server", "echo", {"text": "x"})
    assert not missing.ok and "unknown data server" in missing.error
    assert not hub.call(["unhashable"], "echo", {}).ok  # never raises, even on nonsense input

    after = hub.status()["fake"]
    assert after["calls"] - before["calls"] == 4
    assert after["failures"] - before["failures"] == 4


def test_redaction_of_secrets_and_bls_key_echo(shared):
    hub, _ = shared
    echoed = hub.call("fake", "env_echo", {"name": "FAKE_API_KEY"})
    assert echoed.ok and SECRET not in echoed.text and "[REDACTED]" in echoed.text
    assert SECRET not in json.dumps(echoed.structured)

    bls = hub.call("fake", "echo", {"text": "The key:abcdef0123 provided by the User is invalid."})
    assert bls.text == "The key:[REDACTED] provided by the User is invalid."

    failed = hub.call("fake", "fail", {"message": f"bad {SECRET} at https://x.test/q?api_key=zzz9&a=1"})
    assert SECRET not in failed.error and SECRET not in failed.text
    assert "api_key=[REDACTED]&a=1" in failed.error and len(failed.error) <= 300

    redactor = dm._Redactor(["abc", "longer-secret"])  # values under 4 chars are never treated as secrets
    assert redactor.text("abc longer-secret") == "abc [REDACTED]"
    assert len(redactor.error("x" * 1000)) == 300


def test_child_env_is_allowlisted(shared):
    hub, _ = shared

    def probe(name: str) -> dict:
        result = hub.call("fake", "env_probe", {"name": name})
        assert result.ok, result
        return json.loads(result.text)

    assert probe(PARENT_ONLY) == {"set": False, "length": 0}  # set in the parent at spawn time
    assert probe("LISTED_VAR") == {"set": True, "length": 3}
    assert probe("EMPTY_VAR")["set"] is False                 # empty spec values are not passed
    assert probe("PATH")["set"] is True                      # base keys are inherited


def test_cwd_and_errlog(shared):
    hub, base = shared
    cwd = hub.call("fake", "cwd_probe", {})
    assert os.path.realpath(cwd.text) == os.path.realpath(base / "cwd")
    log = (base / "logs" / "fake.stderr.log").read_text()
    assert "start fake (attempt 1)" in log and "fake-mcp starting pid=" in log


# =============================================================== hub: failure handling

def test_crash_restarts_once_then_circuit_opens(tmp_path):
    clock = FakeClock()
    hub = dm.McpHub({"fake": fake_spec("fake", tmp_path / "cwd")}, errlog_dir=tmp_path / "logs", clock=clock)
    try:
        first_pid = int(hub.call("fake", "pid", {}).text)
        crashed = hub.call("fake", "crash", {"code": 3})
        assert not crashed.ok
        assert wait_for(lambda: hub.status()["fake"]["state"] == "failed")
        error = hub.status()["fake"]["error"]
        assert "server exited unexpectedly (exit code 3)" in error and "fake-mcp crashing" in error

        backoff = hub.call("fake", "echo", {"text": "x"})  # inside the 5 s backoff: fail fast
        assert not backoff.ok and "automatic restart allowed in 5s" in backoff.error
        assert backoff.elapsed_s < 0.5

        clock.now += dm.RESTART_BACKOFF_S
        restarted = hub.call("fake", "pid", {})
        assert restarted.ok and int(restarted.text) != first_pid
        assert pid_gone(first_pid)
        assert "start fake (attempt 2)" in (tmp_path / "logs" / "fake.stderr.log").read_text()

        hub.call("fake", "crash", {"code": 4})
        assert wait_for(lambda: hub.status()["fake"]["state"] == "failed")
        clock.now += 60
        for _ in range(2):
            started = time.monotonic()
            blocked = hub.call("fake", "echo", {"text": "x"})
            assert not blocked.ok and blocked.error.startswith("circuit open: server exited unexpectedly (exit code 4)")
            assert time.monotonic() - started < 0.2
    finally:
        hub.close()


def test_spawn_failure_returns_quickly(tmp_path):
    spec = fake_spec("broken", tmp_path / "cwd", command="/nonexistent/drf-node")
    hub = dm.McpHub({"broken": spec})
    started = time.monotonic()
    result = hub.call("broken", "echo", {"text": "x"})
    assert not result.ok and result.error.startswith("spawn failed: FileNotFoundError")
    assert time.monotonic() - started < 3
    assert hub.status()["broken"]["state"] == "failed"
    started = time.monotonic()
    hub.close()
    assert time.monotonic() - started < 3


def test_exit_during_startup_reports_exit_code_and_stderr(tmp_path):
    spec = fake_spec("dies", tmp_path / "cwd", extra_args=("--exit-at-start", "7"))
    hub = dm.McpHub({"dies": spec}, errlog_dir=tmp_path / "logs")
    try:
        result = hub.call("dies", "echo", {"text": "x"})
        assert not result.ok
        assert result.error.startswith("server exited during startup (exit code 7)")
        assert "configured to exit at start" in result.error
    finally:
        hub.close()


def test_start_timeout_kills_the_child(tmp_path):
    spec = fake_spec("slow", tmp_path / "cwd", extra_args=("--startup-delay", "30"), start_timeout=1.0)
    hub = dm.McpHub({"slow": spec})
    try:
        started = time.monotonic()
        hub.start()
        assert time.monotonic() - started < 0.5  # wait=None returns immediately
        assert hub.status()["slow"]["state"] == "starting"
        result = hub.call("slow", "echo", {"text": "x"})
        assert not result.ok and result.error == "start timeout after 1s"
        assert time.monotonic() - started < 8
        pid = hub._servers["slow"].pid
        assert pid and wait_for(lambda: pid_gone(pid))
    finally:
        hub.close()


def test_unavailable_and_unsafe_specs_fail_instantly(tmp_path):
    specs = {
        "off": fake_spec("off", tmp_path / "cwd", unavailable_reason="not built: run npm run setup:datamcps"),
        "root": dm.ServerSpec(name="root", command=sys.executable, args=(str(FAKE_SERVER),), env={},
                              cwd=str(dm._REPO_ROOT)),
        "relative": dm.ServerSpec(name="relative", command=sys.executable, args=(), env={}, cwd="relative/dir"),
    }
    hub = dm.McpHub(specs)
    status = hub.status()
    assert status["off"] == {"state": "unavailable", "error": "not built: run npm run setup:datamcps",
                             "tools": [], "ready_s": None, "calls": 0, "failures": 0}
    assert "repository root" in status["root"]["error"] and status["root"]["state"] == "unavailable"
    assert "absolute directory" in status["relative"]["error"]
    for name in specs:
        started = time.monotonic()
        result = hub.call(name, "echo", {"text": "x"})
        assert not result.ok and result.error == status[name]["error"]
        assert time.monotonic() - started < 0.05
    hub.start(wait=1)
    assert hub._loop is None  # nothing runnable → no loop thread, no child
    hub.close()
    with pytest.raises(ValueError):
        dm.McpHub({"a": fake_spec("b", tmp_path / "cwd")})


# =============================================================== hub: shutdown

def test_close_kills_children_and_is_idempotent(tmp_path):
    specs = {
        "fake": fake_spec("fake", tmp_path / "a", call_timeout=30),
        "slow": fake_spec("slow", tmp_path / "b", extra_args=("--startup-delay", "30"), start_timeout=60),
    }
    hub = dm.McpHub(specs)
    pid = int(hub.call("fake", "pid", {}).text)
    hub.start(["slow"])
    assert wait_for(lambda: hub._servers["slow"].pid is not None)
    slow_pid = hub._servers["slow"].pid

    in_flight: list = []
    worker = threading.Thread(target=lambda: in_flight.append(hub.call("fake", "sleep", {"seconds": 20})))
    worker.start()
    time.sleep(0.3)
    started = time.monotonic()
    hub.close(timeout=3)
    assert time.monotonic() - started < 8
    worker.join(5)
    assert in_flight and not in_flight[0].ok and "closing" in in_flight[0].error
    assert wait_for(lambda: pid_gone(pid) and pid_gone(slow_pid), timeout=3)
    assert {s["state"] for s in hub.status().values()} == {"closed"}
    assert not hub._thread.is_alive()

    hub.close()  # idempotent
    after = hub.call("fake", "echo", {"text": "x"})
    assert not after.ok and after.error == "data hub is closed"
    hub.start(wait=1)
    assert hub.status()["fake"]["state"] == "closed"


def _run_python(script: str, env: dict, cwd: Path, timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=timeout,
                          env=env, cwd=cwd)


def test_interpreter_exits_promptly_and_leaves_no_orphans(tmp_path):
    """The harness probe saw asyncio.run hang after a spawn failure; the hub must not."""
    root = build_datamcps(tmp_path / "datamcps", server_launcher=(
        f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_SERVER}" "$@"\n'))
    env = {key: value for key, value in os.environ.items() if key != "IMF_APP_NAME"}
    env.update(DATA_SOURCES_DIR=str(root), DATA_SOURCES="imf", DATA_SOURCES_CACHE_DIR=str(tmp_path / "cache"))
    script = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {_BRIDGE_DIR!r})
        import data_mcp as dm
        broken = dm.McpHub({{"x": dm.ServerSpec(name="x", command="/nonexistent/drf", args=(), env={{}},
                                                 cwd={str(tmp_path)!r})}})
        print("broken", broken.call("x", "t", {{}}).ok)
        hub = dm.get_hub()
        assert dm.get_hub() is hub
        print("pid", hub.call("imf", "pid", {{}}).text)
        print("app", hub.call("imf", "env_probe", {{"name": "IMF_APP_NAME"}}).text)
    """)
    started = time.monotonic()
    proc = _run_python(script, env, tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert time.monotonic() - started < 20
    lines = dict(line.split(" ", 1) for line in proc.stdout.splitlines())
    assert lines["broken"] == "False"
    assert json.loads(lines["app"]) == {"set": True, "length": len(dm.IMF_APP_NAME)}
    assert wait_for(lambda: pid_gone(int(lines["pid"])), timeout=3)  # atexit closed the singleton
    assert (tmp_path / "cache" / "mcp-logs" / "imf.stderr.log").is_file()
    assert (tmp_path / "cache" / "mcp-cwd").is_dir()


# =============================================================== default_server_specs

def test_default_specs_resolve_all_six(tree, tmp_path):
    root, env = tree
    env = {**env, "FRED_API_KEY": "k" * 32, "BLS_API_KEY": "", "EIA_API_KEY": "eia-key", "CENSUS_API_KEY": "",
           "FRED_API_TIMEOUT_MS": "15000", "UNRELATED_SECRET": "nope"}
    specs = dm.default_server_specs(env=env, datamcps_dir=root, work_dir=tmp_path / "work")
    assert list(specs) == list(dm.PROVIDERS)
    assert all(spec.unavailable_reason is None for spec in specs.values()), {
        n: s.unavailable_reason for n, s in specs.items()}
    node = str(tmp_path / "nodebin" / "node")
    work = str((tmp_path / "work").resolve())
    assert all(spec.cwd == work for spec in specs.values()) and os.path.isdir(work)

    fred, bls, bis, imf, wb, usgov = (specs[n] for n in dm.PROVIDERS)
    assert fred.command == node and fred.args == (str(root / "fred-mcp-server-main/build/index.js"),)
    assert bls.args == (str(root / "bls_mcp-main/dist/index.js"),)
    assert bis.args == (str(root / "mcp-bis-main/bin/cli.js"),)
    assert imf.command == str(root / "imf-data-mcp-main/.venv/bin/imf-data-mcp") and imf.args == ()
    assert wb.command == str(root / "data360-mcp-dev/.venv/bin/python")
    assert wb.args == ("-m", "data360.mcp_server", "--transport", "stdio")
    assert usgov.args == (str(root / "us-gov-open-data-mcp-main/dist/server.js"), "--modules",
                          "treasury,usaspending,sec,fdic,federal-register,eia")

    assert fred.env["FRED_API_KEY"] == "k" * 32 and fred.env["FRED_API_TIMEOUT_MS"] == "15000"
    assert fred.env["PATH"].split(os.pathsep)[0] == str(tmp_path / "nodebin")
    assert "BLS_API_KEY" not in bls.env and set(bis.env) == {"PATH"}
    assert imf.env == {"IMF_APP_NAME": "DeepResearchForecast"}
    assert wb.env == {"DATA360_API_BASE_URL": "https://data360api.worldbank.org", "MCP_ENV": "local",
                      "FASTMCP_CHECK_FOR_UPDATES": "off"}
    assert usgov.env["EIA_API_KEY"] == "eia-key" and "CENSUS_API_KEY" not in usgov.env
    assert usgov.env["MAX_RESPONSE_BYTES"] == "40000"
    assert usgov.env["XDG_CACHE_HOME"] == str(tmp_path / "cache" / "usgov-cache")
    assert all("UNRELATED_SECRET" not in spec.env and "FRED_API_KEY" not in spec.env
               for spec in (bls, bis, imf, wb, usgov))

    assert (wb.start_timeout, imf.start_timeout, fred.start_timeout, usgov.start_timeout) == (60, 45, 30, 30)
    assert imf.call_timeout == 120 and {s.call_timeout for s in (fred, bls, bis, wb, usgov)} == {60}
    assert (imf.max_concurrency, bls.max_concurrency, fred.max_concurrency, wb.max_concurrency) == (1, 2, 4, 4)

    slow = dm.default_server_specs(env={**env, "DATA_SOURCES_CALL_TIMEOUT": "200", "IMF_APP_NAME": "Mine"},
                                   datamcps_dir=root, work_dir=tmp_path / "work")
    assert slow["imf"].call_timeout == 200 and slow["fred"].call_timeout == 200
    assert slow["imf"].env["IMF_APP_NAME"] == "Mine"
    bogus = dm.default_server_specs(env={**env, "DATA_SOURCES_CALL_TIMEOUT": "soon"}, datamcps_dir=root,
                                    work_dir=tmp_path / "work")
    assert bogus["fred"].call_timeout == dm.DEFAULT_CALL_TIMEOUT_S


def test_default_specs_defaults_from_env(tree, tmp_path, monkeypatch):
    root, env = tree
    specs = dm.default_server_specs(env={**env, "DATA_SOURCES_DIR": str(root)})
    assert specs["bis"].unavailable_reason is None
    assert specs["bis"].cwd == str((tmp_path / "cache" / "mcp-cwd").resolve())
    assert (tmp_path / "cache" / "mcp-cwd").is_dir()

    # The repo root is never accepted as the children's cwd.
    monkeypatch.setattr(dm, "_DEFAULT_CACHE_DIR", tmp_path / "default-cache")
    guarded = dm.default_server_specs(env=env, datamcps_dir=root, work_dir=dm._REPO_ROOT)
    assert guarded["bis"].cwd == str(tmp_path / "default-cache" / "mcp-cwd")

    missing = dm.default_server_specs(env=env, datamcps_dir=tmp_path / "nowhere", work_dir=tmp_path / "w")
    assert all(s.unavailable_reason.startswith("datamcps directory not found") for s in missing.values())


def test_default_specs_missing_builds(tree, tmp_path):
    root, env = tree
    (root / "fred-mcp-server-main/build/index.js").unlink()
    (root / "mcp-bis-main/node_modules/tsx/package.json").unlink()
    make_executable(root / "imf-data-mcp-main/.venv/bin/imf-data-mcp", "#!/gone/venv/bin/python\n")
    (root / "data360-mcp-dev/.venv/bin/python").chmod(0o644)
    specs = dm.default_server_specs(env=env, datamcps_dir=root, work_dir=tmp_path / "work")
    reasons = {name: spec.unavailable_reason for name, spec in specs.items()}
    assert reasons["fred"] == ("not built: run npm run setup:datamcps "
                               "(missing fred-mcp-server-main/build/index.js)")
    assert reasons["bis"].startswith("not built: run npm run setup:datamcps (missing mcp-bis-main/node_modules/tsx")
    assert reasons["imf"].startswith("not built: run npm run setup:datamcps (stale venv")
    assert reasons["wb"].startswith("not built: run npm run setup:datamcps") and "not executable" in reasons["wb"]
    assert reasons["bls"] is None and reasons["usgov"] is None


def test_node_resolution_and_version_gating(tree, tmp_path, monkeypatch):
    root, env = tree
    old = fake_node(tmp_path / "node20", "v20.11.1")
    specs = dm.default_server_specs(env={**env, "DATA_SOURCES_NODE": str(old)}, datamcps_dir=root,
                                    work_dir=tmp_path / "w")
    assert specs["usgov"].unavailable_reason == "node >= 22 required (found v20.11.1)"
    assert specs["fred"].unavailable_reason is None and specs["fred"].command == str(old)

    ancient = fake_node(tmp_path / "node16", "v16.20.2")
    specs = dm.default_server_specs(env={**env, "DATA_SOURCES_NODE": str(ancient)}, datamcps_dir=root,
                                    work_dir=tmp_path / "w")
    for name in ("fred", "bls", "bis", "usgov"):
        assert specs[name].unavailable_reason == "node >= 18 required (found v16.20.2)"
    assert specs["imf"].unavailable_reason is None and specs["wb"].unavailable_reason is None

    broken = make_executable(tmp_path / "nodebad" / "node", "#!/bin/sh\necho garbage\n")
    specs = dm.default_server_specs(env={**env, "DATA_SOURCES_NODE": str(broken)}, datamcps_dir=root,
                                    work_dir=tmp_path / "w")
    assert specs["fred"].unavailable_reason.startswith("node not usable")

    specs = dm.default_server_specs(env={**env, "DATA_SOURCES_NODE": "/nonexistent/node"}, datamcps_dir=root,
                                    work_dir=tmp_path / "w")
    assert specs["bls"].unavailable_reason.startswith("node not found")
    assert specs["imf"].unavailable_reason is None

    # No node on PATH: the fixed fallbacks are searched (pointed at the fake node here).
    monkeypatch.setattr(dm, "_NODE_FALLBACKS", ("~/nodehome/node", str(tmp_path / "nodebin" / "node")))
    specs = dm.default_server_specs(env={**env, "PATH": ""}, datamcps_dir=root, work_dir=tmp_path / "w")
    assert specs["fred"].command == str(tmp_path / "nodebin" / "node")
    assert specs["fred"].env["PATH"] == str(tmp_path / "nodebin")
    monkeypatch.setattr(dm, "_NODE_FALLBACKS", ("/nonexistent/drf/node",))
    specs = dm.default_server_specs(env={**env, "PATH": ""}, datamcps_dir=root, work_dir=tmp_path / "w")
    assert specs["usgov"].unavailable_reason.startswith("node not found")


def test_node_version_checked_once(tree, tmp_path):
    root, env = tree
    counter = tmp_path / "node-calls.txt"
    node = fake_node(tmp_path / "counted", "v22.9.0", counter=counter)
    for _ in range(3):
        specs = dm.default_server_specs(env={**env, "DATA_SOURCES_NODE": str(node)}, datamcps_dir=root,
                                        work_dir=tmp_path / "w")
        assert specs["usgov"].unavailable_reason is None
    assert counter.read_text().count("x") == 1


def test_data_sources_allowlist(tree, tmp_path):
    root, env = tree
    specs = dm.default_server_specs(env={**env, "DATA_SOURCES": " fred, BIS ,bogus"}, datamcps_dir=root,
                                    work_dir=tmp_path / "w")
    assert list(specs) == list(dm.PROVIDERS)
    assert specs["fred"].unavailable_reason is None and specs["bis"].unavailable_reason is None
    for name in ("bls", "imf", "wb", "usgov"):
        assert specs[name].unavailable_reason == "disabled by DATA_SOURCES"
    python_only = dm.default_server_specs(env={**env, "DATA_SOURCES": "wb", "DATA_SOURCES_NODE": "/nope"},
                                          datamcps_dir=root, work_dir=tmp_path / "w")
    assert python_only["wb"].unavailable_reason is None  # node is not even resolved
    assert python_only["fred"].unavailable_reason == "disabled by DATA_SOURCES"


def test_default_specs_drive_the_hub_end_to_end(tmp_path):
    """default_server_specs → McpHub: the venv launcher runs the fake server with the spec env."""
    root = build_datamcps(tmp_path / "datamcps", server_launcher=(
        f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_SERVER}" "$@"\n'))
    env = {"PATH": "/usr/bin:/bin", "DATA_SOURCES_CACHE_DIR": str(tmp_path / "cache"), "DATA_SOURCES": "imf,wb"}
    specs = dm.default_server_specs(env=env, datamcps_dir=root)
    hub = dm.McpHub({n: specs[n] for n in ("imf", "wb")}, errlog_dir=tmp_path / "logs")
    try:
        hub.start(wait=30)
        assert hub.status()["imf"]["state"] == "ready"
        probe = hub.call("imf", "env_probe", {"name": "IMF_APP_NAME"})
        assert json.loads(probe.text) == {"set": True, "length": len("DeepResearchForecast")}
        cwd = hub.call("imf", "cwd_probe", {}).text
        assert os.path.realpath(cwd) == os.path.realpath(tmp_path / "cache" / "mcp-cwd")
        # wb's "venv python" is the same launcher, so the fake server's argparse rejects
        # ``-m data360.mcp_server ...`` and exits: a startup failure isolated from imf.
        wb = hub.status()["wb"]
        assert wb["state"] == "failed" and wb["error"].startswith("server exited during startup (exit code 2)")
    finally:
        hub.close()


# =============================================================== singleton

def test_get_hub_singleton_and_reset(tmp_path):
    env = {"DATA_SOURCES_DIR": str(tmp_path / "absent"), "DATA_SOURCES_CACHE_DIR": str(tmp_path / "cache")}
    dm.reset_hub_for_tests()
    try:
        hub = dm.get_hub(env=env)
        assert dm.get_hub() is hub
        assert {s["state"] for s in hub.status().values()} == {"unavailable"}
        hub.close()
        reopened = dm.get_hub(env=env)
        assert reopened is not hub
        dm.reset_hub_for_tests()
        assert dm.get_hub(env=env) is not reopened
    finally:
        dm.reset_hub_for_tests()


def test_terminate_groups_kills_a_survivor():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        dm._terminate_groups([proc.pid])
        assert proc.wait(timeout=5) in (-signal.SIGTERM, -signal.SIGKILL)
    finally:
        if proc.poll() is None:
            proc.kill()
