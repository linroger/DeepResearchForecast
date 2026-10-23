#!/usr/bin/env python3
"""Run trusted main-checkout tests under a CPython audit boundary, not an OS sandbox.

Invoke with backend/.venv/bin/python -I -S -B (no site/.pth startup). No packages
are installed. Only this interpreter's existing site-packages are added, without
executing .pth files. Use a NEW --evidence-dir for every run.
"""
from __future__ import annotations

import argparse
import ast
import atexit
import collections
import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import runpy
import stat
import subprocess
import sys
import tempfile
import threading
import types
from urllib.parse import urlsplit, unquote

REPO = Path(__file__).resolve().parents[2]
IDENTITY = ("HOME", "home", "CODEX_HOME", "USERPROFILE")
CONTROL_TEST = REPO / "backend/tests/test_main_offline_runner.py"
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


class RedirectImports(importlib.abc.MetaPathFinder):
    """Replace only known storage assignments while executing current main bytes.

    No application files change. The compiled source otherwise remains real;
    source hashes and redirects are recorded for reviewers.
    """
    def __init__(self, guard):
        self.guard = guard
        root = guard.root
        self.targets = {
            "app.config": (REPO / "backend/app/config.py", "Config", {
                "UPLOAD_FOLDER": str(root / "uploads"),
                "PIPELINE_DATA_DIR": str(root / "uploads/pipelines"),
                "OASIS_SIMULATION_DATA_DIR": str(root / "uploads/simulations"),
                "GRAPHITI_DATA_DIR": str(root / "uploads/graphiti_db"),
                "FORECAST_LEDGER_DIR": str(root / "uploads/ledger"),
                "EMBED_DISK_CACHE_PATH": str(root / "cache/embed.sqlite"),
                "DATA_SOURCES_CACHE_DIR": str(root / "cache/data"),
            }),
            "app.utils.logger": (REPO / "backend/app/utils/logger.py", None,
                                 {"LOG_DIR": str(root / "logs")}),
            "app.services.simulation_manager": (
                REPO / "backend/app/services/simulation_manager.py", "SimulationManager",
                {"SIMULATION_DATA_DIR": str(root / "uploads/simulations")}),
        }

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "oasis":
            # Delegate discovery directly to PathFinder, avoiding this finder
            # recursively. Execute the installed dependency's original loader;
            # only its import-time relative logs get a bounded working directory.
            spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
            if spec is None or spec.loader is None:
                return spec
            original_loader = spec.loader
            guard = self.guard

            class OasisImportLoader(importlib.abc.Loader):
                def create_module(self, module_spec):
                    create = getattr(original_loader, "create_module", None)
                    return create(module_spec) if create is not None else None

                def __getattr__(self, name):
                    return getattr(original_loader, name)

                def exec_module(self, module):
                    original_cwd = os.getcwd()
                    quarantine = guard.root / "import-cwd" / "oasis"
                    quarantine.mkdir(parents=True, exist_ok=True)
                    if spec.origin and Path(spec.origin).is_file():
                        source = Path(spec.origin).read_bytes()
                        guard.source_hashes[str(Path(spec.origin).resolve())] = hashlib.sha256(source).hexdigest()
                    os.chdir(quarantine)
                    try:
                        guard.record("quarantine:oasis_import_cwd")
                        original_loader.exec_module(module)
                    finally:
                        os.chdir(original_cwd)

            spec.loader = OasisImportLoader()
            return spec
        if fullname not in self.targets:
            return None
        source_path, class_name, replacements = self.targets[fullname]
        guard = self.guard

        class Loader(importlib.abc.Loader):
            def create_module(self, spec):
                return None

            def exec_module(self, module):
                source = source_path.read_bytes()
                guard.source_hashes[str(source_path)] = hashlib.sha256(source).hexdigest()
                tree = ast.parse(source, filename=str(source_path))
                body = tree.body if class_name is None else next(
                    node.body for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == class_name)
                found = set()
                for node in body:
                    if isinstance(node, ast.Assign) and len(node.targets) == 1:
                        name = getattr(node.targets[0], "id", None)
                        if name in replacements:
                            node.value = ast.copy_location(ast.Constant(replacements[name]), node.value)
                            found.add(name)
                if found != set(replacements):
                    raise RuntimeError(f"offline storage assignments changed in {fullname}")
                module.__file__ = str(source_path)
                exec(compile(ast.fix_missing_locations(tree), str(source_path), "exec", dont_inherit=True),
                     module.__dict__)
                guard.record("redirect:" + fullname)

        return importlib.util.spec_from_file_location(fullname, source_path, loader=Loader())


class GuardViolation(PermissionError):
    """An audited operation exceeded the declared offline boundary."""


class Guard:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.identity = {key: os.environ.get(key) for key in IDENTITY}
        self.counts = collections.Counter()
        self.probes = collections.Counter()
        self.read_roots = [REPO, Path(sys.base_prefix).resolve(), self.root,
                           Path("/System/Library"), Path("/Library/Fonts"),
                           Path("/usr/share"), Path("/private/etc/ssl"),
                           Path("/private/var/db/timezone")]
        # Python mimetypes on this Mac reads Apache's system MIME database when
        # Flask sends a report. This grants one file read, never /etc as a tree.
        self.read_files = {Path("/private/etc/apache2/mime.types")}
        saved = [REPO / "backend" / name for name in ("uploads", "logs", "data")]
        self.saved_roots = saved + [path.resolve() for path in saved]
        self.site_paths = []
        self.source_hashes = {}
        self.allowed_scripts = {}
        self.children = {}
        self.spawn_count = 0
        self.spawn_ticket = threading.local()
        self.open_ticket = threading.local()
        self.child_lock = threading.RLock()
        self.fd_dirs = {}
        self.configured = False
        self.exit_code = 1

    def record(self, kind: str, **details):
        self.counts[kind] += 1
        if details.get("program") in {"fc-list", "system_profiler"}:
            self.probes[details["program"]] += 1
        if details.get("category") == "font_discovery":
            self.probes["font_directory_scan"] += 1
        with (self.root / f"events-{os.getpid()}.jsonl").open("a") as stream:
            stream.write(json.dumps({"pid": os.getpid(), "event": kind, **details}) + "\n")

    def deny(self, kind: str, **details):
        self.record("blocked:" + kind, **details)
        raise GuardViolation("main offline guard blocked " + kind)

    def directory_fd(self, fd):
        entry = self.fd_dirs.get(fd)
        if entry is None:
            self.deny("unknown_directory_fd")
        path, device, inode = entry
        current = os.fstat(fd)
        if (current.st_dev, current.st_ino) != (device, inode):
            self.deny("changed_directory_fd")
        return path

    def protected_reason(self, path):
        # Check requested and resolved paths: resolving a symlink must not
        # erase a protected name, nor move a saved root outside its boundary.
        requested = Path(path).absolute()
        resolved = requested.resolve()
        for candidate in (requested, resolved):
            # The checkout is an explicit read root, even below ~/.codex or
            # ~/.claude. This never admits siblings or credentials within it,
            # and resolved symlink targets are checked independently.
            checked = candidate.relative_to(REPO) if candidate.is_relative_to(REPO) else candidate
            parts = {part.lower() for part in checked.parts}
            credential = (any(part == ".env" or (part.startswith(".env.") and part != ".env.example")
                              for part in parts)
                          or bool(parts & {".netrc", ".git-credentials", "credentials", "credentials.json",
                                           "auth.json", "id_rsa", "id_ed25519", ".ssh", ".aws", ".gnupg",
                                           ".codex", ".claude", "keychains"}))
            if credential:
                return "credential_path"
            if any("finharness" in part for part in parts):
                return "excluded_source"
            if any(candidate.is_relative_to(base) for base in self.saved_roots):
                return "saved_data"
        return None

    def path(self, path, *, write=False, dir_fd=None, allow_devnull=False):
        if dir_fd not in (None, -1):
            if not Path(os.fsdecode(path)).is_absolute():
                path = self.directory_fd(dir_fd) / os.fsdecode(path)
        if isinstance(path, int):
            path = self.directory_fd(path)
        raw = Path(os.fsdecode(path))
        reason = self.protected_reason(raw)
        if reason:
            self.deny(reason)
        candidate = raw.resolve()
        if allow_devnull and raw.absolute() == Path(os.devnull) and candidate == Path(os.devnull):
            return candidate
        if write:
            # unlink/rename operate on the directory entry, not its symlink
            # target. Both the entry and target must stay inside the boundary.
            entry = raw.parent.resolve() / raw.name
            if not entry.is_relative_to(self.root) or not candidate.is_relative_to(self.root):
                self.deny("external_write")
        elif candidate not in self.read_files and not any(candidate.is_relative_to(base) for base in self.read_roots):
            display = str(candidate).replace(str(REPO), "<REPO>")
            for name in IDENTITY:
                if self.identity.get(name):
                    display = display.replace(self.identity[name], "<IDENTITY>")
            category = "font_discovery" if candidate.name in {"fonts", "Fonts", ".fonts", "TTF", "truetype"} else "unclassified"
            self.deny("external_read", path=display[:240], category=category)
        return candidate

    def traversal_directory(self, path, flags, dir_fd=None):
        """Authorize only no-follow directory handles leading to allowed roots.

        This grants no directory listing, file read, write, or cwd permission:
        those operations still pass through path(). Secure openat readers need
        ancestor handles to reach an otherwise already-allowed fixture file.
        """
        required = getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        allowed = required | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
        if not getattr(os, "O_DIRECTORY", 0) or not getattr(os, "O_NOFOLLOW", 0):
            return None
        if flags & required != required or flags & ~allowed or isinstance(path, int):
            return None
        raw = Path(os.fsdecode(path))
        if dir_fd not in (None, -1) and not raw.is_absolute():
            raw = self.directory_fd(dir_fd) / raw
        if self.protected_reason(raw):
            return None
        candidate = raw.resolve()
        if candidate in self.read_files or any(candidate.is_relative_to(base) for base in self.read_roots):
            return None  # Ordinary read permission already covers this path.
        roots = [*self.read_roots, *(path.parent for path in self.read_files)]
        if not any(base.is_relative_to(candidate) for base in roots):
            return None
        self.record("allow:directory_traversal")
        return candidate

    def audit(self, event, args):
        if event in {"os.putenv", "os.unsetenv"} and self.configured:
            name = os.fsdecode(args[0])
            value = os.fsdecode(args[1]) if event == "os.putenv" else None
            if name in IDENTITY and self.identity[name] != value:
                self.deny("identity_environment")
        elif event == "open":
            path, mode, flags = args
            if isinstance(path, int):
                # Existing stdio/temp/subprocess pipe FDs do not name new files.
                return
            ticket = (os.fspath(path), flags & ~getattr(os, "O_CLOEXEC", 0))
            if getattr(self.open_ticket, "value", None) == ticket:
                self.open_ticket.value = None
                return
            self.path(path, write=bool(flags & WRITE_FLAGS), allow_devnull=True)
        elif event in {"os.listdir", "os.scandir"}:
            self.path(args[0] if args[0] is not None else os.getcwd())
        elif event == "os.mkdir":
            self.path(args[0], write=True, dir_fd=args[2])
        elif event in {"os.remove", "os.rmdir"}:
            self.path(args[0], write=True, dir_fd=args[1])
        elif event in {"os.rename", "os.link"}:
            self.path(args[0], write=True, dir_fd=args[2])
            self.path(args[1], write=True, dir_fd=args[3])
        elif event == "os.symlink":
            destination = self.path(args[1], write=True, dir_fd=args[2])
            target = Path(os.fsdecode(args[0]))
            if not target.is_absolute():
                target = destination.parent / target
            self.path(target, write=True)
        elif event in {"os.chmod", "os.chown", "os.utime", "os.truncate"}:
            fd_index = {"os.chmod": 2, "os.chown": 3, "os.utime": 3}.get(event)
            self.path(args[0], write=True, dir_fd=args[fd_index] if fd_index is not None else None)
        elif event in {"os.setxattr", "os.removexattr", "os.chflags"}:
            self.path(args[0], write=True)
        elif event == "os.chdir":
            self.path(args[0])
        elif event.startswith("socket."):
            # Asyncio uses anonymous AF_UNIX socketpairs for thread wakeups.
            # All connect/bind/DNS/sendto calls remain denied, even AF_UNIX.
            if event == "socket.__new__" and args[1] == 1:
                return
            if event != "socket.gethostname":
                self.deny("network:" + event)
        elif event == "subprocess.Popen":
            if getattr(self.spawn_ticket, "argv", None) != args[1]:
                self.deny("process:" + event)
            self.spawn_ticket.argv = None
        elif event in {"os.kill", "os.killpg"}:
            if event == "os.kill" and args == (os.getpid(), 0):
                return  # Read-only liveness probe of this guarded process.
            with self.child_lock:
                child = self.children.get(args[0])
            if event == "os.kill" and args[1] == 0 and child is not None:
                # Signal zero observes only existence/permission. Keep the owned
                # child's registration after reaping so ESRCH reaches real liveness
                # consumers; mutating signals to reaped/reused PIDs stay denied below.
                self.record("allowed:child_liveness", child_pid=args[0], reaped=child.poll() is not None)
                return
            if child is None or child.poll() is not None:
                self.deny("process:" + event)
        elif event in {"os.system", "os.exec", "os.posix_spawn", "os.fork", "os.forkpty", "pty.spawn"}:
            self.deny("process:" + event)
        elif event == "sqlite3.connect" and args[0] != ":memory:":
            if not args[0]:
                self.deny("sqlite_uri")
            raw = os.fsdecode(args[0])
            if raw.lower().startswith("file:"):
                parsed = urlsplit(raw)
                # SQLite URI options can select VFSes, bypass locking, attach
                # remote names or reinterpret paths. Admit only the canonical
                # local URI emitted by Path.as_uri plus a single access mode.
                decoded = unquote(parsed.path, errors="strict")
                candidate = Path(decoded)
                if (parsed.scheme != "file" or parsed.netloc or parsed.fragment
                        or parsed.query not in {"mode=ro", "mode=rw", "mode=rwc"}
                        or not candidate.is_absolute() or "\x00" in decoded
                        or candidate.as_uri() + "?" + parsed.query != raw
                        or not candidate.resolve().is_relative_to(self.root)):
                    self.deny("sqlite_uri")
                self.path(candidate, write=True)
            else:
                self.path(raw, write=True)

    def configure(self, *, child=False):
        # Start from a small non-secret environment. Preserve identity exactly,
        # including unset variables. Never log ambient values.
        keep = dict(os.environ) if child else {
            key: value for key, value in os.environ.items()
            if key in (*IDENTITY, "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT")}
        os.environ.clear()
        os.environ.update(keep)
        os.environ.update({
            "PATH": os.defpath, "DRF_TEST_PROCESS": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHON_DOTENV_DISABLED": "1", "MPLBACKEND": "Agg",
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
            "PREDICTION_MARKETS_ENABLED": "false", "DATA_SOURCES_ENABLED": "false",
            "MAIN_OFFLINE_EVIDENCE": str(self.root),
        })
        for key, subdir in {
            "TMPDIR": "tmp", "TMP": "tmp", "TEMP": "tmp",
            "XDG_CACHE_HOME": "cache", "XDG_CONFIG_HOME": "config",
            "MPLCONFIGDIR": "cache/matplotlib", "HF_HOME": "cache/huggingface",
            "PLOTLY_DIR": "cache/plotly",
            "TIKTOKEN_CACHE_DIR": "cache/tiktoken", "DATA_SOURCES_CACHE_DIR": "cache/data",
            "GRAPHITI_DATA_DIR": "uploads/graphiti_db", "FORECAST_LEDGER_DIR": "uploads/ledger",
        }.items():
            target = self.root / subdir
            target.mkdir(parents=True, exist_ok=True)
            os.environ[key] = str(target)
        tempfile.tempdir = str(self.root / "tmp")
        sys.dont_write_bytecode = True
        # -S avoids .pth execution; derive the venv path from the invoked
        # executable, not its resolved symlink to the base interpreter.
        site = Path(sys.executable).absolute().parent.parent / "lib" / (
            f"python{sys.version_info.major}.{sys.version_info.minor}") / "site-packages"
        if site.is_dir():
            self.site_paths.append(str(site.resolve()))
            self.read_roots.append(site.resolve())
            sys.path.append(str(site))
        sys.path[:0] = [str(REPO / "backend"), str(REPO)]
        # Disable dotenv consistently, including modules that load it directly.
        dotenv = types.ModuleType("dotenv")
        dotenv.__path__ = []
        dotenv.load_dotenv = lambda *a, **kw: False
        dotenv.find_dotenv = lambda *a, **kw: ""
        dotenv.dotenv_values = lambda *a, **kw: {}
        dotenv_main = types.ModuleType("dotenv.main")
        for name in ("load_dotenv", "find_dotenv", "dotenv_values"):
            setattr(dotenv_main, name, getattr(dotenv, name))
        dotenv.main = dotenv_main
        sys.modules["dotenv"] = dotenv
        sys.modules["dotenv.main"] = dotenv_main
        sys.meta_path.insert(0, RedirectImports(self))
        original_open, original_close = os.open, os.close

        def tracked_open(path, flags, mode=0o777, *, dir_fd=None):
            checked = self.traversal_directory(path, flags, dir_fd)
            if checked is None:
                checked = self.path(path, write=bool(flags & WRITE_FLAGS), dir_fd=dir_fd, allow_devnull=True)
            # Authorization resolves paths; execution retains the caller's
            # path/flags so O_NOFOLLOW and O_EXCL keep their normal semantics.
            self.open_ticket.value = (os.fspath(path), flags & ~getattr(os, "O_CLOEXEC", 0))
            try:
                fd = original_open(path, flags, mode, dir_fd=dir_fd)
            finally:
                self.open_ticket.value = None
            info = os.fstat(fd)
            if stat.S_ISDIR(info.st_mode):
                self.fd_dirs[fd] = (checked, info.st_dev, info.st_ino)
            return fd

        def tracked_close(fd):
            self.fd_dirs.pop(fd, None)
            return original_close(fd)

        os.open, os.close = tracked_open, tracked_close
        self.install_children()
        self.configured = True

    def allow_python_script(self, path):
        """Explicit opt-in, restricted to test fixtures or project renderers."""
        given = Path(path).absolute()
        canonical = self.path(given)
        permitted = (canonical.is_relative_to(REPO / "backend/tests")
                     or canonical.is_relative_to(self.root)
                     or (canonical.is_relative_to(REPO / "deerflow_bridge/skills")
                         and canonical.name.startswith("render") and canonical.parent.name == "scripts"))
        if given != canonical or canonical.suffix != ".py" or not permitted:
            self.deny("child_script_scope")
        self.allowed_scripts[str(canonical)] = hashlib.sha256(canonical.read_bytes()).hexdigest()

    def install_children(self):
        original = subprocess.Popen
        guard = self

        class GuardedPopen(original):
            def __init__(self, args, *positional, **kwargs):
                # Serialize admission through registration: pending launches
                # cannot race past the count/concurrency bounds.
                with guard.child_lock:
                    self._guarded_init(args, *positional, **kwargs)

            def _guarded_init(self, args, *positional, **kwargs):
                if (positional or not isinstance(args, (list, tuple)) or len(args) < 2
                        or kwargs.get("shell") or kwargs.get("preexec_fn")
                        or kwargs.get("executable") or kwargs.get("pass_fds")):
                    guard.deny("process:subprocess.Popen")
                command = [os.fsdecode(arg) for arg in args]
                if Path(command[0]).absolute() != Path(sys.executable).absolute():
                    basename = Path(command[0]).name
                    # Attribute known library discovery without logging argv,
                    # user payloads, command strings, environment or secrets.
                    program = basename if basename in {"fc-list", "system_profiler", "uname", "sw_vers", "ps"} else "unregistered-executable"
                    guard.deny("process:subprocess.Popen", program=program)
                tail = command[1:]
                while tail and tail[0] in {"-B", "-u"}:
                    tail.pop(0)
                if not tail or tail[0].startswith("-"):
                    guard.deny("process:subprocess.Popen")
                cwd = guard.path(kwargs.get("cwd") or guard.root / "tmp", write=True)
                target = Path(tail[0])
                script = str((target if target.is_absolute() else cwd / target).resolve())
                if script not in guard.allowed_scripts:
                    guard.deny("process:subprocess.Popen")
                if hashlib.sha256(Path(script).read_bytes()).hexdigest() != guard.allowed_scripts[script]:
                    guard.deny("changed_child_script")
                if guard.spawn_count >= 64 or sum(p.poll() is None for p in guard.children.values()) >= 8:
                    guard.deny("child_process_limit")
                env = dict(os.environ if kwargs.get("env") is None else kwargs["env"])
                shims = []
                for entry in env.pop("PYTHONPATH", "").split(os.pathsep):
                    if entry:
                        target = Path(entry)
                        shims.append(str(guard.path(target if target.is_absolute() else cwd / target, write=True)))
                for key, value in guard.identity.items():
                    env.pop(key, None)
                    if value is not None:
                        env[key] = value
                # The child needs only this explicitly named target. Recursive
                # provider/renderer launch remains denied unless registered there.
                env["MAIN_OFFLINE_CHILD"] = json.dumps({
                    "root": str(guard.root), "script": script,
                    "sha256": guard.allowed_scripts[script], "shims": shims,
                })
                executable = sys.executable
                wrapped = [executable, "-I", "-S", "-B", "-u", str(Path(__file__).resolve()),
                           "--guarded-child", script, *tail[1:]]
                guard.spawn_ticket.argv = wrapped
                try:
                    super().__init__(wrapped, **{**kwargs, "cwd": str(cwd), "env": env, "close_fds": True})
                finally:
                    guard.spawn_ticket.argv = None
                guard.children[self.pid] = self
                guard.spawn_count += 1
                guard.record("allowed:guarded_child", child_pid=self.pid, script=script)

        subprocess.Popen = GuardedPopen

    def close_children(self):
        for child in self.child_snapshot().values():
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=3)

    def child_snapshot(self):
        with self.child_lock:
            return dict(self.children)

    def receipt(self, status, exit_code=None, *, shutdown_complete=False):
        drift = [name for name, digest in self.source_hashes.items()
                 if not Path(name).is_file() or hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest]
        payload = {"schema": "main-offline/v1", "pid": os.getpid(), "status": status,
                   "exit_code": exit_code, "boundary": "CPython audit hooks; not an OS sandbox",
                   "shutdown_complete": shutdown_complete,
                   "events": dict(self.counts), "source_sha256": self.source_hashes,
                   "contained_library_probes": dict(self.probes),
                   "probe_note": "Blocked fc-list/system_profiler/font-directory discovery remains denied; nonzero counts are attempts, not zero probes.",
                   "source_drift": drift,
                   "allowed_scripts": self.allowed_scripts,
                   "children": {str(pid): {"exit_code": child.poll(),
                                 "receipt": f"process-{pid}.json"} for pid, child in self.child_snapshot().items()},
                   "identity_preserved": all(os.environ.get(k) == v for k, v in self.identity.items())}
        (self.root / f"process-{os.getpid()}.json").write_text(json.dumps(payload, indent=2) + "\n")
        return payload

    def finish(self, *, parent=False, shutdown_complete=False):
        self.close_children()
        payload = self.receipt("completed", self.exit_code, shutdown_complete=shutdown_complete)
        if parent:
            (self.root / "completed.json").write_text(json.dumps(payload, indent=2) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--self-test", action="store_true", help="Run stdlib controls without pytest/conftest")
    parser.add_argument("--allow-python-script", action="append", default=[], type=Path,
                        help="Allow an exact hashed Python fixture/render script; repeat as needed")
    options, pytest_args = parser.parse_known_args(argv)
    if not sys.flags.no_site or not sys.flags.isolated:
        parser.error("invoke the existing interpreter with -I -S -B before this script")
    root = options.evidence_dir.absolute()
    if root.exists() or root.is_symlink() or root.parent.resolve() != root.parent:
        parser.error("evidence directory must be new, with an existing canonical parent")
    guard = Guard(root)
    reason = guard.protected_reason(root)
    if reason:
        parser.error("evidence directory is protected: " + reason)
    root.mkdir(mode=0o700)
    sys.modules["main_offline_guard"] = guard
    sys.addaudithook(guard.audit)
    # Registered before app/pytest hooks so this refresh runs after their
    # shutdown handlers. The append-only event stream also preserves attempts
    # if a process is terminated before it can produce a completed receipt.
    atexit.register(guard.finish, parent=True, shutdown_complete=True)
    guard.configure()
    for path in options.allow_python_script:
        guard.allow_python_script(path)
    guard.source_hashes[str(Path(__file__).resolve())] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    source_paths = [CONTROL_TEST] if options.self_test else [
        Path(arg.split("::", 1)[0]).absolute() for arg in pytest_args
        if arg.split("::", 1)[0].endswith(".py") and not arg.startswith("-")]
    for path in source_paths:
        guard.path(path)
        guard.source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    guard.receipt("started")
    code = 1
    try:
        if options.self_test:
            sys.argv = [str(CONTROL_TEST)]
            runpy.run_path(str(CONTROL_TEST), run_name="__main__")
            code = 0
        else:
            import pytest
            args = pytest_args[1:] if pytest_args[:1] == ["--"] else pytest_args
            code = int(pytest.main([*args, "-p", "no:cacheprovider", "-o", "addopts=",
                                   "--basetemp", str(root / "pytest-tmp"),
                                   "--junitxml", str(root / "junit.xml")]))
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else int(exc.code is not None)
    finally:
        guard.exit_code = code
        guard.finish(parent=True)
    return code


def guarded_child():
    if not sys.flags.no_site or not sys.flags.isolated:
        raise RuntimeError("guarded child requires -I -S")
    context = json.loads(os.environ.pop("MAIN_OFFLINE_CHILD"))
    root = Path(context["root"])
    guard = Guard(root)
    sys.modules["main_offline_guard"] = guard
    sys.addaudithook(guard.audit)
    atexit.register(guard.finish, shutdown_complete=True)
    guard.configure(child=True)
    script = str(guard.path(context["script"]))
    source = Path(script).read_bytes()
    if script != sys.argv[2] or hashlib.sha256(source).hexdigest() != context["sha256"]:
        guard.deny("changed_child_script")
    sys.path[:0] = [str(Path(script).parent),
                   *[str(guard.path(entry, write=True)) for entry in context["shims"]]]
    guard.source_hashes[script] = context["sha256"]
    guard.receipt("started")
    code = 1
    try:
        sys.argv = sys.argv[2:]
        target = types.ModuleType("__main__")
        target.__file__, target.__package__, target.__spec__ = script, None, None
        target.__cached__, target.__loader__ = None, None
        sys.modules["__main__"] = target
        exec(compile(source, script, "exec", dont_inherit=True), target.__dict__)
        code = 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else int(exc.code is not None)
    finally:
        guard.exit_code = code
        guard.finish()
    return code


if __name__ == "__main__":
    raise SystemExit(guarded_child() if sys.argv[1:2] == ["--guarded-child"] else main())
