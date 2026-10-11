#!/usr/bin/env python3
"""Standalone OS-sandbox acceptance for nine deployment fixtures.

Run with an existing Python using -I -S -B. This never imports pytest or the app,
never installs dependencies, and does not modify the frozen CPython runner.
The trusted parent copies source bytes into a new scratch tree; a macOS sandbox
worker runs AST-selected original assertions with a controlled process harness.
Failure to establish the OS boundary stops acceptance rather than falling back.
"""
from __future__ import annotations

import argparse
import atexit
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import threading
import textwrap
import types
import collections
import traceback
import uuid
from types import SimpleNamespace

IDENTITY = ("HOME", "home", "CODEX_HOME", "USERPROFILE")
DATA_TESTS = (
    "_built_bls_layout",
    "test_shell_scripts_parse",
    "test_setup_datamcps_check_mode_is_idempotent_and_detects_staleness",
    "test_setup_datamcps_gates_old_node_and_opt_out",
    "test_datamcps_build_outputs_are_ignored_and_sources_are_not",
)
SKILL_TESTS = (
    "_write_skill", "_public_root", "_tree_bytes",
    "test_concurrent_cli_syncs_serialize_and_end_on_one_verified_bundle",
    "test_session_hook_litter_is_never_deployed",
)
PARSE_SCRIPTS = ("setup.sh", "init.sh", "scripts/doctor.sh", "scripts/setup_datamcps.sh")

TRANSPORT_HELPERS = ("FakeClock", "fake_spec", "wait_for", "pid_gone", "make_executable", "fake_node", "build_datamcps", "tree", "_run_python")
TRANSPORT_PURE = ("test_default_specs_resolve_all_six", "test_default_specs_defaults_from_env", "test_default_specs_missing_builds", "test_node_resolution_and_version_gating", "test_node_version_checked_once", "test_data_sources_allowlist")
TRANSPORT_NATIVE = ("test_crash_restarts_once_then_circuit_opens", "test_spawn_failure_returns_quickly", "test_start_timeout_kills_the_child", "test_close_kills_children_and_is_idempotent", "test_interpreter_exits_promptly_and_leaves_no_orphans", "test_default_specs_drive_the_hub_end_to_end", "test_terminate_groups_kills_a_survivor")

INTEGRATION_TEST_MODULES = (
    "backend/tests/test_research_engine_v3.py",
    "backend/tests/test_research_engine_v3_round2.py",
    "backend/tests/test_research_engine_v3_round3_robust.py",
)
INTEGRATION_CASES = (
    ("test_research_engine_v3_round2", "test_r2_parent_pipeline_accepts_a_v3_research_run", "clean"),
    ("test_research_engine_v3_round2", "test_r2_parent_pipeline_accepts_a_v3_research_run", "cut"),
    ("test_research_engine_v3_round3_robust", "test_r3_sigint_during_a_fan_out_starts_no_queued_kiq_and_no_new_call", None),
    ("test_research_engine_v3_round3_robust", "test_r3_sigterm_leaves_a_terminal_status_and_a_closed_progress_log", None),
)
FROZEN_RUNNER_SHA256 = "53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity_snapshot():
    return {k: {"present": k in os.environ,
                "sha256": hashlib.sha256(os.environ.get(k, "").encode()).hexdigest()}
            for k in IDENTITY}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def selected_functions(source, names):
    tree = ast.parse(Path(source).read_text())
    by_name = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    chosen = []
    identities = {}
    for name in names:
        fn = by_name[name]
        identities[name] = hashlib.sha256(ast.dump(ast.Module(body=fn.body, type_ignores=[]), include_attributes=False).encode()).hexdigest()
        fn.decorator_list = []  # Parametrization is performed explicitly below.
        chosen.append(fn)
    return chosen, identities


def fake_executable(path, *, node=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # No installer body exists. Any invocation besides fake node -v fails and
    # is visible in the receipt, including an accidental non-check build path.
    body = ('#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$DRF_FIXTURE_TOOL_LOG"\n'
            + ('if [ "$#" -eq 1 ] && [ "$1" = "-v" ]; then echo v22.0.0; exit 0; fi\n' if node else '')
            + 'exit 93\n')
    path.write_text(body)
    path.chmod(0o755)
    return path


def clean_env(work, extra=None):
    work = Path(work)
    env = {k: os.environ[k] for k in IDENTITY if k in os.environ}
    env.update(PATH=str(work / "bin") + ":/usr/bin:/bin", LC_ALL="C", LANG="C",
               TMPDIR=str(work / "tmp"), XDG_CONFIG_HOME=str(work / "config"),
               XDG_CACHE_HOME=str(work / "cache"), PYTHONDONTWRITEBYTECODE="1",
               PYTHONNOUSERSITE="1", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null",
               GIT_TERMINAL_PROMPT="0", DRF_FIXTURE_TOOL_LOG=str(work / "toolchain.log"))
    if extra:
        if set(extra) & set(IDENTITY):
            raise ValueError("Identity overrides forbidden")
        env.update(extra)
    return env


class Processes:
    PIPE = subprocess.PIPE
    STDOUT = subprocess.STDOUT
    DEVNULL = subprocess.DEVNULL

    def __init__(self, manifest):
        self.manifest = manifest
        self.work = Path(manifest["work"])
        self.records = []
        self.children = []

    def command(self, args):
        args = list(map(str, args))
        if args[0] == "bash":
            args[0] = "/bin/bash"
        elif args[0] == "git":
            args[0] = self.manifest["git"]
        elif Path(args[0]).resolve() == Path(sys.executable).resolve():
            args = [sys.executable, "-I", "-S", "-B", *args[1:]]
        else:
            raise AssertionError("Unapproved fixture executable")
        return args

    def run(self, args, **kwargs):
        command = self.command(args)
        env = kwargs.pop("env", clean_env(self.work))
        assert {k: env.get(k) for k in IDENTITY} == {k: os.environ.get(k) for k in IDENTITY}
        kwargs.update(env=env, cwd=str(self.work))
        kwargs["timeout"] = min(float(kwargs.get("timeout", 30)), 60)
        # These fixture commands are closed-form check-only operations. The
        # enclosing worker session has an additional parent deadline.
        completed = subprocess.run(command, **kwargs)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        self.records.append({"command": command, "exit_code": completed.returncode,
                             "stdout": stdout.decode(errors="replace") if isinstance(stdout, bytes) else stdout,
                             "stderr": stderr.decode(errors="replace") if isinstance(stderr, bytes) else stderr})
        return completed

    def Popen(self, args, **kwargs):
        command = self.command(args)
        kwargs.update(env=clean_env(self.work), cwd=str(self.work))
        process = subprocess.Popen(command, **kwargs)
        self.children.append(process)
        self.records.append({"command": command, "pid": process.pid, "concurrent": True})
        return process

    def cleanup(self):
        for process in self.children:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        return all(p.poll() is not None for p in self.children)


def registered_pids(work):
    journal = Path(work) / "transport-processes.jsonl"
    if not journal.exists():
        return set()
    return {r["pid"] for line in journal.read_text().splitlines()
            if (r := json.loads(line)).get("event") == "spawned"}


def native_ps(manifest, pid):
    if type(pid) is not int or pid <= 0 or pid not in registered_pids(manifest["work"]):
        raise PermissionError("PS requires a registered fixture PID")
    os.kill(pid, 0)  # Kernel same-sandbox signal permission is the second gate.
    directory = Path(manifest["work"]) / "ps-requests"
    directory.mkdir(exist_ok=True)
    token = uuid.uuid4().hex
    request, reply = directory / (token + ".request.json"), directory / (token + ".reply.json")
    temporary = directory / (token + ".tmp")
    write_json(temporary, {"pid": pid})
    temporary.replace(request)
    deadline = time.monotonic() + 7
    while not reply.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("PS broker did not reply")
        time.sleep(0.01)
    result = json.loads(reply.read_text())
    if result.get("error"):
        raise PermissionError(result["error"])
    return subprocess.CompletedProcess(["ps", "-o", "stat=", "-p", str(pid)],
                                       result["exit_code"], result["stdout"], result["stderr"])


def ps_broker(manifest, stopped):
    directory = Path(manifest["work"]) / "ps-requests"
    directory.mkdir(exist_ok=True)
    processed = set()
    while not stopped.is_set():
        for request in directory.glob("*.request.json"):
            if request.name in processed:
                continue
            processed.add(request.name)
            result = {}
            try:
                payload = json.loads(request.read_text())
                pid = payload.get("pid")
                if set(payload) != {"pid"} or type(pid) is not int or pid not in registered_pids(manifest["work"]) or pid == manifest["outside_pid"]:
                    raise PermissionError("Unowned PS request")
                command = ["/bin/ps", "-o", "stat=", "-p", str(pid)]
                observed = subprocess.run(command, env=clean_env(manifest["work"]), cwd=manifest["work"],
                                          capture_output=True, text=True, timeout=5)
                result = {"command": command, "exit_code": observed.returncode,
                          "stdout": observed.stdout, "stderr": observed.stderr}
                with (Path(manifest["work"]) / "ps-broker.jsonl").open("a") as log:
                    log.write(json.dumps(result) + "\n")
            except Exception as exc:
                result = {"error": type(exc).__name__}
            reply = request.with_name(request.name.replace(".request.json", ".reply.json"))
            temporary = reply.with_suffix(".tmp")
            write_json(temporary, result)
            temporary.replace(reply)
        stopped.wait(0.01)


def sandbox_controls(manifest, checks=None):
    root = Path(manifest["work"])
    checks = {} if checks is None else checks
    (root / "positive-control").write_text("scratch write permitted")
    assert (root / "positive-control").read_text() == "scratch write permitted"
    checks["scratch_read_write"] = True
    try:
        Path(manifest["outside_sentinel"]).read_text()
    except PermissionError:
        checks["outside_read_denied"] = True
    else:
        raise AssertionError("OS sandbox allowed outside read")
    try:
        (Path(manifest["outside_sentinel"]).parent / "outside-write").write_text("forbidden")
    except PermissionError:
        checks["outside_write_denied"] = True
    else:
        raise AssertionError("OS sandbox allowed outside write")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", 0))
        except PermissionError:
            checks["inet_bind_denied"] = True
        else:
            raise AssertionError("OS sandbox allowed an INET bind")
    try:
        subprocess.run(["/usr/bin/true"], check=True, capture_output=True, timeout=5)
    except PermissionError:
        checks["unapproved_exec_denied"] = True
    else:
        raise AssertionError("OS sandbox allowed an unapproved executable")
    try:
        os.kill(manifest["outside_pid"], 0)
    except PermissionError:
        checks["outside_signal_denied"] = True
    else:
        raise AssertionError("OS sandbox allowed a signal to the separately owned sentinel")
    pair = socket.socketpair()
    try:
        pair[0].send(b"x")
        assert pair[1].recv(1) == b"x"
        checks["anonymous_unix_pair"] = True
    finally:
        for sock in pair:
            sock.close()
    owned = subprocess.Popen([sys.executable, "-I", "-S", "-B", "-c", "import time; time.sleep(60)"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        os.kill(owned.pid, 0)
        with (root / "transport-processes.jsonl").open("a") as journal:
            journal.write(json.dumps({"event": "spawned", "pid": owned.pid, "observer": os.getpid(), "control": True}) + "\n")
        state = native_ps(manifest, owned.pid)
        assert state.returncode == 0 and state.stdout.strip(), f"owned ps observation unavailable: {state.returncode}, {state.stderr[:300]}"
        checks["owned_ps_and_signal"] = True
        try:
            native_ps(manifest, manifest["outside_pid"])
        except PermissionError:
            checks["outside_ps_request_denied"] = True
        else:
            raise AssertionError("PS broker accepted the outside sentinel")
    finally:
        owned.terminate()
        owned.wait(timeout=5)
    return checks


class AttributePatch:
    def __init__(self):
        self.previous = []

    def setattr(self, obj, name, value):
        self.previous.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, value in reversed(self.previous):
            setattr(obj, name, value)


class TransportProcesses:
    """Preserve transport argv/cwd/env; observe only closed scratch commands."""
    def __init__(self, manifest):
        self.manifest = manifest
        self.work = Path(manifest["work"])
        self.journal = self.work / "transport-processes.jsonl"
        self.original = subprocess.Popen
        self.original_run = subprocess.run
        self.handles = []
        self.installed = False

    def record(self, value):
        data = (json.dumps({"observer": os.getpid(), **value}, separators=(",", ":")) + "\n").encode()
        fd = os.open(self.journal, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            assert os.write(fd, data) == len(data)
        finally:
            os.close(fd)

    def known_pids(self):
        if not self.journal.exists():
            return set()
        return {r["pid"] for line in self.journal.read_text().splitlines()
                if (r := json.loads(line)).get("event") == "spawned"}

    def checked(self, args, kwargs):
        if not isinstance(args, (list, tuple)) or not args or kwargs.get("shell"):
            raise PermissionError("Transport fixture requires explicit argv")
        argv = [os.fsdecode(a) for a in args]
        executable = argv[0]
        if executable in {"ps", "/bin/ps", str(self.work / "bin/ps")}:
            if len(argv) != 5 or argv[1:4] != ["-o", "stat=", "-p"] or int(argv[4]) not in self.known_pids():
                raise PermissionError("ps is restricted to exact owned-PID status queries")
            argv[0] = "/bin/ps"
        elif executable in {"/nonexistent/drf-node", "/nonexistent/drf"}:
            pass  # Keep the real kernel ENOENT outcome; never synthesize it.
        elif not Path(executable).is_absolute() or not Path(executable).resolve().is_relative_to(self.work):
            raise PermissionError("Transport executable is not a copied scratch fixture")
        cwd = Path(kwargs.get("cwd") or os.getcwd()).resolve()
        if not cwd.is_relative_to(self.work):
            raise PermissionError("Transport cwd escapes scratch")
        if kwargs.get("env") is not None:
            env = dict(kwargs["env"])
            for key in IDENTITY:
                if key in env and env[key] != os.environ.get(key):
                    raise PermissionError("Identity override forbidden")
                if key in os.environ:
                    env[key] = os.environ[key]
            kwargs["env"] = env
        display = list(argv)
        if "-c" in display:
            index = display.index("-c") + 1
            if index < len(display):
                display[index] = "<code sha256=" + hashlib.sha256(display[index].encode()).hexdigest() + ">"
        script_hashes = {arg: digest(arg) for arg in argv[1:] if arg.endswith(".py") and Path(arg).is_file() and Path(arg).resolve().is_relative_to(self.work)}
        self.record({"event": "attempt", "command": display, "cwd": str(cwd), "script_sha256": script_hashes,
                     "env_supplied": kwargs.get("env") is not None,
                     "identity_preserved": True})
        return argv

    def install(self):
        controller = self
        class ObservedPopen(self.original):
            def __init__(self, args, *pos, **kwargs):
                argv = controller.checked(args, kwargs)
                try:
                    super().__init__(argv, *pos, **kwargs)
                except Exception as exc:
                    controller.record({"event": "spawn_failed", "error_type": type(exc).__name__})
                    raise
                controller.handles.append(self)
                controller.record({"event": "spawned", "pid": self.pid,
                                   "new_session": bool(kwargs.get("start_new_session"))})
        subprocess.Popen = ObservedPopen
        def observed_run(args, *pos, **kwargs):
            if isinstance(args, (list, tuple)) and args and os.fsdecode(args[0]) in {"ps", "/bin/ps"}:
                checked = controller.checked(args, dict(kwargs))
                result = native_ps(controller.manifest, int(checked[-1]))
                if kwargs.get("check") and result.returncode:
                    raise subprocess.CalledProcessError(result.returncode, args, result.stdout, result.stderr)
                return result
            return controller.original_run(args, *pos, **kwargs)
        subprocess.run = observed_run
        self.installed = True

    def cleanup(self):
        for handle in self.handles:
            if handle.poll() is None:
                try:
                    if os.getpgid(handle.pid) == handle.pid:
                        os.killpg(handle.pid, signal.SIGTERM)
                    else:
                        handle.terminate()
                    handle.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    if os.getpgid(handle.pid) == handle.pid:
                        os.killpg(handle.pid, signal.SIGKILL)
                    else:
                        handle.kill()
                    handle.wait(timeout=3)
                except ProcessLookupError:
                    pass
        # Bootstrap children also record descendants here. Signal permission
        # is OS-limited to this sandbox; a reused/outside PID is denied.
        survivors = []
        for pid in (self.known_pids() if os.getpid() == self.manifest.get("root_worker_pid") else set()):
            if pid == os.getpid():
                continue
            try:
                os.kill(pid, 0)
                os.kill(pid, signal.SIGTERM)
                survivors.append(pid)
            except (ProcessLookupError, PermissionError):
                pass
        if survivors:
            time.sleep(0.1)
            for pid in survivors:
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        if self.installed:
            subprocess.Popen = self.original
            subprocess.run = self.original_run
            self.installed = False
        return all(p.poll() is not None for p in self.handles)


def write_bootstrap(work, manifest):
    bootstrap = work / "python_bootstrap.py"
    shim = work / "python-fixture"
    bootstrap.write_text(
        "import atexit,json,runpy,sys\nfrom pathlib import Path\n"
        + f"manifest=json.loads(Path({str(work / 'manifest.json')!r}).read_text())\n"
        + "sys.path.insert(0,manifest['site_packages'])\nsys.path.insert(0,manifest['work'])\n"
        + "import verify_deployment_fixtures as fixture\n"
        + "if manifest['suite']=='integration': fixture.install_app_redirects(manifest)\n"
        + "controller=fixture.TransportProcesses(manifest)\n"
        + "controller.install()\n"
        + f"sys.executable={str(shim)!r}\n"
        + "args=sys.argv[1:]\n"
        + "if args[0]=='-c':\n sys.argv=['-c',*args[2:]]\n exec(compile(args[1],'<string>','exec'),{'__name__':'__main__'})\n"
        + "else:\n sys.argv=args\n runpy.run_path(args[0],run_name='__main__')\n")
    shim.write_text("#!/bin/sh\nexec " + shlex.quote(manifest["real_python"])
                    + " -I -S -B " + shlex.quote(str(bootstrap)) + ' "$@"\n')
    shim.chmod(0o755)


def transport_worker(manifest, output):
    work = Path(manifest["work"])
    names = TRANSPORT_PURE + (TRANSPORT_NATIVE if manifest["suite"] == "transport" else ())
    controller = TransportProcesses(manifest)
    manifest["root_worker_pid"] = os.getpid()
    write_json(work / "manifest.json", manifest)
    original_executable = sys.executable
    sys.executable = str(work / "python-fixture")
    sys.path.insert(0, manifest["site_packages"])
    sys.path.insert(0, str(work / "bridge"))
    exit_code = 1
    try:
        controller.install()
        import data_mcp as dm
        functions, _ = selected_functions(work / "test_data_mcp.py", TRANSPORT_HELPERS + names)
        future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
        program = ast.fix_missing_locations(ast.Module(body=[future, *functions], type_ignores=[]))
        namespace = {"Path": Path, "dm": dm, "os": os, "sys": sys, "time": time,
                     "subprocess": subprocess, "threading": threading, "textwrap": textwrap,
                     "json": json, "signal": signal, "FAKE_SERVER": work / "fake_mcp_server.py",
                     "_BRIDGE_DIR": str(work / "bridge")}
        exec(compile(program, "<selected-original-transport-assertions>", "exec"), namespace)
        for name in names:
            directory = work / "cases" / name
            directory.mkdir(parents=True)
            patch = AttributePatch()
            fn = namespace[name]
            kwargs = {}
            parameters = fn.__code__.co_varnames[:fn.__code__.co_argcount]
            if "tmp_path" in parameters:
                kwargs["tmp_path"] = directory
            if "tree" in parameters:
                kwargs["tree"] = namespace["tree"](directory)
            if "monkeypatch" in parameters:
                kwargs["monkeypatch"] = patch
            started = time.monotonic()
            try:
                fn(**kwargs)
                result = {"test": name, "status": "passed"}
            except Exception:
                result = {"test": name, "status": "failed", "traceback": traceback.format_exc(limit=8)}
            finally:
                patch.undo()
            result["elapsed_seconds"] = round(time.monotonic() - started, 4)
            output["results"].append(result)
            write_json(work / "transport-progress.json", output)
        exit_code = 0 if all(r["status"] == "passed" for r in output["results"]) else 1
    except Exception:
        output["error"] = traceback.format_exc(limit=8)
    finally:
        output["child_cleanup_complete"] = controller.cleanup()
        output["identity_preserved"] = identity_snapshot() == manifest["identity"]
        output["exit_code"] = exit_code
        output["process_journal"] = "transport-processes.jsonl"
        output["transport_owned_result"] = True
        sys.executable = original_executable
        write_json(work / "worker-result.json", output)
    return exit_code


def install_app_redirects(manifest):
    """Use the frozen storage transformer, without its audit-hook policy."""
    marker = "_drf_sidecar_app_redirects"
    if marker in sys.modules:
        return sys.modules[marker]
    if any(name == "app" or name.startswith("app.") for name in sys.modules):
        raise RuntimeError("Application imported before storage redirects")
    work = Path(manifest["work"])
    repo = work / "repo"
    root = work / "app-state" / str(os.getpid())
    root.mkdir(parents=True, exist_ok=True)
    os.environ.update(DRF_TEST_PROCESS="1", DATA_SOURCES_ENABLED="false",
                      PREDICTION_MARKETS_ENABLED="false", PYTHON_DOTENV_DISABLED="1",
                      PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1",
                      HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", MPLBACKEND="Agg")
    for key, relative in {"TMPDIR": "tmp", "TMP": "tmp", "TEMP": "tmp",
                          "XDG_CACHE_HOME": "cache", "XDG_CONFIG_HOME": "config",
                          "MPLCONFIGDIR": "cache/matplotlib", "HF_HOME": "cache/huggingface",
                          "PLOTLY_DIR": "cache/plotly", "TIKTOKEN_CACHE_DIR": "cache/tiktoken",
                          "DATA_SOURCES_CACHE_DIR": "cache/data", "GRAPHITI_DATA_DIR": "uploads/graphiti_db",
                          "FORECAST_LEDGER_DIR": "uploads/ledger"}.items():
        path = root / relative
        path.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(path)
    sys.path[:0] = [str(repo / "backend"), str(repo), str(repo / "backend/tests"),
                   str(repo / "deerflow_bridge"), manifest["site_packages"]]
    dotenv = types.ModuleType("dotenv")
    dotenv.__path__ = []
    dotenv.load_dotenv = lambda *a, **k: False
    dotenv.find_dotenv = lambda *a, **k: ""
    dotenv.dotenv_values = lambda *a, **k: {}
    dotenv_main = types.ModuleType("dotenv.main")
    for name in ("load_dotenv", "find_dotenv", "dotenv_values"):
        setattr(dotenv_main, name, getattr(dotenv, name))
    dotenv.main = dotenv_main
    sys.modules["dotenv"] = dotenv
    sys.modules["dotenv.main"] = dotenv_main
    runner_path = repo / "backend/scripts/main_offline_pytest.py"
    if digest(runner_path) != FROZEN_RUNNER_SHA256:
        raise RuntimeError("Frozen redirect source changed")
    spec = importlib.util.spec_from_file_location("sidecar_frozen_redirect_source", runner_path)
    frozen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(frozen)
    if frozen.REPO != repo:
        raise RuntimeError("Frozen redirect root is not the scratch replica")
    guard = types.ModuleType(marker)
    guard.root = root
    guard.source_hashes = {}
    guard.events = collections.Counter()
    guard.socket_events = collections.Counter()
    receipt = work / f"app-imports-{os.getpid()}.json"

    def flush():
        write_json(receipt, {"pid": os.getpid(), "root": str(root),
                            "redirects": dict(guard.events), "source_sha256": guard.source_hashes,
                            "observed_socket_events": dict(guard.socket_events),
                            "identity_preserved": identity_snapshot() == manifest["identity"],
                            "audit_policy_installed": False})

    def record(event, **details):
        guard.events[event] += 1
        flush()

    def observe(event, args):
        # Observation only: native signals/processes remain governed by SBPL.
        if event in {"socket.connect", "socket.bind", "socket.getaddrinfo"}:
            guard.socket_events[event] += 1
            flush()

    guard.record = record
    sys.modules[marker] = guard
    sys.meta_path.insert(0, frozen.RedirectImports(guard))
    sys.addaudithook(observe)
    flush()
    return guard


def integration_worker(manifest, output):
    work = Path(manifest["work"])
    manifest["root_worker_pid"] = os.getpid()
    write_json(work / "manifest.json", manifest)
    original_executable = sys.executable
    sys.executable = str(work / "python-fixture")
    controller = TransportProcesses(manifest)
    exit_code = 1
    try:
        install_app_redirects(manifest)
        controller.install()
        import pytest
        import test_research_engine_v3 as v3
        modules = {name: importlib.import_module(name) for name in {r[0] for r in INTEGRATION_CASES}}
        for module_name, function_name, parameter in INTEGRATION_CASES:
            case = function_name + (f"[{parameter}]" if parameter is not None else "")
            directory = work / "cases" / case
            directory.mkdir(parents=True)
            patch = pytest.MonkeyPatch()
            started = time.monotonic()
            try:
                v3._hermetic_env.__wrapped__(patch)
                function = getattr(modules[module_name], function_name)
                kwargs = {"tmp_path": directory}
                if parameter is not None:
                    kwargs.update(monkeypatch=patch, world=parameter)
                function(**kwargs)
                result = {"test": case, "status": "passed"}
            except Exception:
                result = {"test": case, "status": "failed", "traceback": traceback.format_exc(limit=10)}
            finally:
                patch.undo()
            result["elapsed_seconds"] = round(time.monotonic() - started, 4)
            output["results"].append(result)
            write_json(work / "integration-progress.json", output)
        exit_code = 0 if len(output["results"]) == 4 and all(r["status"] == "passed" for r in output["results"]) else 1
    except Exception:
        output["error"] = traceback.format_exc(limit=10)
    finally:
        output["child_cleanup_complete"] = controller.cleanup()
        output["identity_preserved"] = identity_snapshot() == manifest["identity"]
        output["exit_code"] = exit_code
        output["process_journal"] = "transport-processes.jsonl"
        output["app_redirect_receipts"] = [p.name for p in work.glob("app-imports-*.json")]
        output["transport_owned_result"] = True
        sys.executable = original_executable
        write_json(work / "worker-result.json", output)
    return exit_code


def worker(manifest_path):
    manifest = json.loads(Path(manifest_path).read_text())
    work = Path(manifest["work"])
    output = {"schema": "deployment-sidecar/v1", "boundary": "macOS sandbox-exec",
              "results": [], "controls": {}, "identity_preserved": False}
    processes = Processes(manifest)
    exit_code = 1
    try:
        assert identity_snapshot() == manifest["identity"]
        output["controls"] = sandbox_controls(manifest, output["controls"])
        for relative, expected in manifest["copies"].items():
            assert digest(work / relative) == expected, relative
        if manifest["suite"] == "integration":
            return integration_worker(manifest, output)
        if manifest["suite"] in {"transport", "transport-pure"}:
            return transport_worker(manifest, output)
        if manifest["suite"] == "controls":
            output["identity_preserved"] = identity_snapshot() == manifest["identity"]
            exit_code = 0
            return exit_code
        namespace = {"Path": Path, "os": os, "json": json, "sys": sys,
                     "subprocess": processes, "REPO_ROOT": work / "repo",
                     "SETUP_DATAMCPS": work / "repo/scripts/setup_datamcps.sh",
                     "HELPER_PATH": work / "runtime_skill_sync.py",
                     "pytest": SimpleNamespace(skip=lambda reason: (_ for _ in ()).throw(AssertionError("Skip forbidden: " + reason)))}
        nodes = []
        for file, names in ((work / "test_data_sources_config.py", DATA_TESTS),
                            (work / "test_runtime_skill_sync.py", SKILL_TESTS)):
            functions, _ = selected_functions(file, names)
            nodes.extend(functions)
        future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
        program = ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[]))
        exec(compile(program, "<selected-original-assertions>", "exec"), namespace)
        namespace["_executable"] = lambda path: fake_executable(path, node=Path(path).name == "node")

        def run_setup(tmp_path, *args, **overrides):
            # Only this fixture harness changes: preserve identity and point at
            # the byte-identical scratch script, never the real repo .env.
            assert not (work / "repo/.env").exists()
            return processes.run(["bash", str(namespace["SETUP_DATAMCPS"]), *args], capture_output=True,
                                 text=True, timeout=30, env=clean_env(work, overrides), check=False)
        namespace["_run_setup_datamcps"] = run_setup
        spec = importlib.util.spec_from_file_location("deployment_sidecar_skill_sync", namespace["HELPER_PATH"])
        sync = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sync)

        cases = [(f"test_shell_scripts_parse[{p}]", namespace["test_shell_scripts_parse"], [p]) for p in PARSE_SCRIPTS]
        for name in DATA_TESTS[2:4]:
            directory = work / "cases" / name
            directory.mkdir(parents=True)
            cases.append((name, namespace[name], [directory]))
        cases.append((DATA_TESTS[4], namespace[DATA_TESTS[4]], []))
        for name in SKILL_TESTS[-2:]:
            directory = work / "cases" / name
            directory.mkdir(parents=True)
            args = [directory] if name.startswith("test_concurrent") else [directory, sync]
            cases.append((name, namespace[name], args))
        for name, fn, args in cases:
            started = time.monotonic()
            try:
                fn(*args)
                result = {"test": name, "status": "passed"}
            except Exception:
                result = {"test": name, "status": "failed", "traceback": traceback.format_exc(limit=8)}
            result["elapsed_seconds"] = round(time.monotonic() - started, 4)
            output["results"].append(result)
        tool_log = (work / "toolchain.log").read_text() if (work / "toolchain.log").exists() else ""
        assert all(line.endswith("/node -v") for line in tool_log.splitlines()), tool_log
        output["fake_tool_invocations"] = tool_log.splitlines()
        output["identity_preserved"] = identity_snapshot() == manifest["identity"]
        exit_code = 0 if len(output["results"]) == 9 and all(r["status"] == "passed" for r in output["results"]) else 1
    except Exception:
        exit_code = 1
        output["error"] = traceback.format_exc(limit=8)
        if output.get("transport_owned_result"):
            output["exit_code"] = exit_code
            write_json(work / "worker-result.json", output)
    finally:
        if not output.get("transport_owned_result"):
            output["child_cleanup_complete"] = processes.cleanup()
            output["commands"] = processes.records
            output["identity_preserved"] = identity_snapshot() == manifest["identity"]
            output["exit_code"] = exit_code
            write_json(work / "worker-result.json", output)
    return exit_code


def profile_text(work, python, git, site_packages):
    quote = lambda p: json.dumps(str(p))
    runtime = Path(sys.base_prefix).resolve()
    read_roots = [work, runtime, site_packages, Path("/System"), Path("/usr/lib"), Path("/usr/share")]
    # Homebrew git's linked libraries are code/runtime dependencies, not user
    # config. Execution remains limited to the exact selected git binary.
    if str(git).startswith("/opt/homebrew/"):
        read_roots += [Path("/opt/homebrew/Cellar"), Path("/opt/homebrew/opt"), Path("/opt/homebrew/lib")]
    executables = [python, git, Path("/bin/bash"), Path("/bin/sh"), Path("/usr/bin/dirname"),
                   Path("/usr/bin/sed"), Path("/usr/bin/find"), Path("/usr/bin/head"),
                   Path("/nonexistent/drf-node"), Path("/nonexistent/drf")]
    read_filters = " ".join(f"(subpath {quote(p)})" for p in read_roots)
    read_filters += " " + " ".join(f"(literal {quote(p)})" for p in executables)
    return f'''(version 1)
(deny default)
(allow file-read-metadata)
(allow file-read* {read_filters} (literal "/") (literal "/dev/null") (literal "/dev/urandom") (literal "/private/etc/localtime"))
(allow file-map-executable {read_filters})
(allow file-write* (subpath {quote(work)}) (literal "/dev/null"))
(allow process-fork)
(allow process-info* (target same-sandbox))
(allow process-exec* {" ".join(f"(literal {quote(p)})" for p in executables)} (subpath {quote(work)}))
(allow signal (target same-sandbox))
(allow sysctl-read)
(allow mach-lookup)
(deny network*)
'''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--suite", choices=("deployment", "transport-pure", "transport", "integration", "controls"), default="deployment")
    parser.add_argument("--prepare-only", action="store_true", help="Copy/hash declared inputs only; no worker or fixture execution")
    args = parser.parse_args(argv)
    if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode:
        parser.error("Use an existing Python with -I -S -B")
    if args.worker:
        return worker(args.worker)
    if args.evidence_dir is None:
        parser.error("--evidence-dir is required")
    root = args.evidence_dir.absolute()
    if root.exists() or root.is_symlink() or root.parent != root.parent.resolve():
        parser.error("Use a fresh evidence directory under an existing canonical parent")
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
        parser.error("This sidecar requires macOS sandbox-exec; no weaker fallback is allowed")
    repo = Path(__file__).resolve().parents[2]
    root.mkdir(mode=0o700)
    work = root / "work"
    for relative in ("", "repo", "bin", "tmp", "cache", "config"):
        (work / relative).mkdir(exist_ok=True)
    originals = {}
    copies = {}
    pairs = [(p, "repo/" + p) for p in PARSE_SCRIPTS]
    pairs += [("backend/tests/test_data_mcp.py", "test_data_mcp.py"),
              ("backend/tests/fixtures/fake_mcp_server.py", "fake_mcp_server.py"),
              ("deerflow_bridge/data_mcp.py", "bridge/data_mcp.py"),
              ("backend/tests/test_data_sources_config.py", "test_data_sources_config.py"),
              ("backend/tests/test_runtime_skill_sync.py", "test_runtime_skill_sync.py"),
              ("deerflow_bridge/runtime_skill_sync.py", "runtime_skill_sync.py"),
              ("backend/scripts/verify_deployment_fixtures.py", "verify_deployment_fixtures.py"),
              (".gitignore", "repo/.gitignore")]
    if args.suite == "integration":
        app_sources = [path for path in (repo / "backend/app").rglob("*.py")
                       if not any(part in {"__pycache__", "uploads", "logs", "data", ".claude"}
                                  for part in path.relative_to(repo / "backend/app").parts)]
        bridge_sources = list((repo / "deerflow_bridge").glob("*.py"))
        for path in sorted(app_sources + bridge_sources):
            relative = path.relative_to(repo).as_posix()
            pairs.append((relative, "repo/" + relative))
        for relative in (*INTEGRATION_TEST_MODULES, "backend/scripts/main_offline_pytest.py",
                         "deerflow_bridge/skills/deep-research/references/final-dossier-contract.md"):
            pairs.append((relative, "repo/" + relative))
        assert digest(repo / "backend/scripts/main_offline_pytest.py") == FROZEN_RUNNER_SHA256
    test_source = repo / "backend/tests/test_data_sources_config.py"
    node = next(n for n in ast.parse(test_source.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == DATA_TESTS[4])
    git_paths = [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("datamcps/")]
    for relative in git_paths:
        for directory in (Path(relative).parent, *Path(relative).parent.parents):
            if not directory.parts:
                continue
            path = directory / ".gitignore"
            if (repo / path).is_file():
                pairs.append((path.as_posix(), "repo/" + path.as_posix()))
    for source, target in dict(pairs).items():
        original = repo / source
        assert not original.is_symlink() and original.resolve().is_relative_to(repo)
        destination = work / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(original.read_bytes())
        originals[source] = digest(original)
        copies[target] = digest(destination)
        assert originals[source] == copies[target]
    assert not (work / "repo/.env").exists()
    git_dir = work / "repo/.git"
    (git_dir / "objects").mkdir(parents=True)
    (git_dir / "refs/heads").mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    (git_dir / "config").write_text("[core]\n\trepositoryformatversion = 0\n\tbare = false\n")
    for tool in ("node", "npm", "pnpm", "uv"):
        fake_executable(work / "bin" / tool, node=tool == "node")
    sentinel = root / "outside-sentinel"
    sentinel.write_text("Synthetic boundary control; no credentials or saved data.\n")
    git = Path(shutil.which("git") or "/usr/bin/git").resolve()
    python = Path(sys.executable).resolve()
    profile = root / "sandbox.sb"
    site_packages = repo / "backend/.venv/lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    if not (site_packages / "mcp").is_dir() or not (site_packages / "anyio").is_dir():
        raise RuntimeError("Existing mcp/anyio dependency runtime unavailable; no install allowed")
    profile.write_text(profile_text(work, python, git, site_packages))
    selected = {}
    for source, names in ((repo / "backend/tests/test_data_sources_config.py", DATA_TESTS),
                          (repo / "backend/tests/test_runtime_skill_sync.py", SKILL_TESTS)):
        _, hashes = selected_functions(source, names)
        selected.update(hashes)
    _, hashes = selected_functions(repo / "backend/tests/test_data_mcp.py", TRANSPORT_HELPERS + TRANSPORT_PURE + TRANSPORT_NATIVE)
    selected.update(hashes)
    if args.suite == "integration":
        for module, function, _parameter in INTEGRATION_CASES:
            _, hashes = selected_functions(repo / "backend/tests" / (module + ".py"), (function,))
            selected.update(hashes)
        for source, names in ((INTEGRATION_TEST_MODULES[0], ("_hermetic_env",)),
                              (INTEGRATION_TEST_MODULES[1], ("_positional_citations_ok",)),
                              (INTEGRATION_TEST_MODULES[2], ("_child",))):
            _, hashes = selected_functions(repo / source, names)
            selected.update(hashes)
    sentinel_process = None
    manifest = {"work": str(work), "git": str(git), "identity": identity_snapshot(),
                "copies": copies, "original_sources": originals, "selected_body_sha256": selected,
                "outside_sentinel": str(sentinel), "outside_pid": None,
                "suite": args.suite, "site_packages": str(site_packages), "real_python": str(python),
                "integration_cases": INTEGRATION_CASES if args.suite == "integration" else [],
                "source_copy_policy": "only explicit files; integration adds filtered backend/app *.py and bridge root *.py; no env/storage/credential trees"}
    write_json(work / "manifest.json", manifest)
    write_bootstrap(work, manifest)
    if args.prepare_only:
        write_json(root / "prepared.json", {"status": "prepared_not_executed", "suite": args.suite,
                   "source_sha256": originals, "selected_body_sha256": selected,
                   "profile_sha256": digest(profile), "manifest": "work/manifest.json",
                   "sidecar_sha256": digest(Path(__file__)), "identity_preserved": identity_snapshot() == manifest["identity"],
                   "no_worker_started": True, "no_app_imports": True})
        print(root / "prepared.json")
        return 0
    sentinel_process = subprocess.Popen(["/bin/sleep", "240"], env=clean_env(work), cwd=work,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    manifest["outside_pid"] = sentinel_process.pid
    write_json(work / "manifest.json", manifest)
    broker_stop = threading.Event()
    broker = threading.Thread(target=ps_broker, args=(manifest, broker_stop), daemon=True)
    broker.start()
    command = ["/usr/bin/sandbox-exec", "-f", str(profile), str(python), "-I", "-S", "-B",
               str(work / "verify_deployment_fixtures.py"), "--worker", str(work / "manifest.json")]
    started = time.monotonic()
    proc = subprocess.Popen(command, env=clean_env(work), cwd=work, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=180)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            stdout, stderr = proc.communicate(timeout=10)
    finally:
        broker_stop.set()
        broker.join(timeout=7)
        sentinel_process.terminate()
        sentinel_process.wait(timeout=5)
    write_json(root / "completed.json", {
        "schema": "deployment-sidecar-parent/v1", "boundary": "macOS sandbox-exec; distinct from CPython guard",
        "command": command, "worker_pid": proc.pid, "exit_code": proc.returncode, "stdout": stdout, "stderr": stderr,
        "elapsed_seconds": round(time.monotonic() - started, 3), "identity_preserved": identity_snapshot() == manifest["identity"],
        "source_sha256": originals, "source_drift": [p for p, h in originals.items() if digest(repo / p) != h],
        "profile_sha256": digest(profile), "selected_body_sha256": selected,
        "worker_receipt": "work/worker-result.json", "child_reaped": proc.poll() is not None,
        "sentinel_reaped": sentinel_process.poll() is not None, "suite": args.suite,
        "ps_broker_stopped": not broker.is_alive(), "ps_boundary": "parent read-only native ps, exact registered same-sandbox PID only",
    })
    print(root / "completed.json")
    return proc.returncode if proc.returncode is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
