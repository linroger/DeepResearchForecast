"""Actual-operation controls; executable with --self-test before pytest imports."""
import os
import json
import contextlib
import importlib.util
import io
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock


class MainOfflineControls(unittest.TestCase):
    def setUp(self):
        self.guard = sys.modules.get("main_offline_guard")
        if self.guard is None:
            self.fail("run via backend/scripts/main_offline_pytest.py")
        self.work = Path(tempfile.mkdtemp(prefix="control-"))

    def test_network(self):
        with self.assertRaisesRegex(PermissionError, "network"):
            socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with self.assertRaisesRegex(PermissionError, "network"):
            socket.getaddrinfo("offline.invalid", 443)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            with self.assertRaisesRegex(PermissionError, "network"):
                sock.bind(str(self.work / "blocked.sock"))

    def test_external_write_and_temporary_write(self):
        allowed = self.work / "allowed.txt"
        allowed.write_text("synthetic")
        self.assertEqual(allowed.read_text(), "synthetic")
        with self.assertRaisesRegex(PermissionError, "external_write"):
            (self.guard.root.parent / (self.guard.root.name + "-escape.txt")).write_text("blocked")

    def test_credential_read(self):
        ordinary = self.work / "synthetic.txt"
        ordinary.write_text("fixture-not-a-secret")
        # No real credential contents are needed or read by this control.
        with self.assertRaisesRegex(PermissionError, "credential_path"):
            (self.work / ".env").read_text()
        with self.assertRaisesRegex(PermissionError, "credential_path"):
            (Path(os.environ["HOME"]) / ".ssh" / "id_rsa").read_bytes()

    def test_symlink_and_directory_fd_containment(self):
        with tempfile.TemporaryDirectory() as path:
            child = Path(path) / "sub"
            child.mkdir()
            (child / "data.txt").write_text("temporary cleanup works")
        self.assertFalse(Path(path).exists())
        with self.assertRaisesRegex(PermissionError, "external_write"):
            (self.work / "escape").symlink_to(self.guard.root.parent)
        fd = os.open(self.work, os.O_RDONLY)
        try:
            with self.assertRaisesRegex(PermissionError, "external_write"):
                os.open("../../../escape.txt", os.O_WRONLY | os.O_CREAT, dir_fd=fd)
        finally:
            os.close(fd)
        fd = os.open(self.guard.root, os.O_RDONLY)
        try:
            with self.assertRaisesRegex(PermissionError, "external_write"):
                os.symlink("..", "relative-escape", dir_fd=fd)
        finally:
            os.close(fd)

    def test_guarded_child_propagation_with_minimal_env(self):
        script = self.work / "fixture.py"
        script.write_text('''import atexit, json, os, socket, sys, tempfile
from pathlib import Path
g = sys.modules['main_offline_guard']
assert os.environ['DRF_TEST_PROCESS'] == '1'
assert os.environ['FIXTURE_ONLY'] == 'synthetic'
assert 'PYTHONPATH' not in os.environ
for action in (
    lambda: socket.socket(socket.AF_INET),
    lambda: (g.root.parent / 'blocked-child-write.txt').write_text('blocked'),
    lambda: (g.root / '.env').read_text(),
):
    try:
        action()
    except PermissionError:
        pass
    else:
        raise AssertionError('child guard missing')
with tempfile.TemporaryDirectory() as tmp:
    (Path(tmp) / 'allowed.txt').write_text('yes')
assert all(os.environ.get(k) == v for k, v in g.identity.items())
def shutdown_probe():
    try:
        (g.root.parent / 'blocked-at-shutdown.txt').write_text('blocked')
    except PermissionError:
        pass
atexit.register(shutdown_probe)
print(json.dumps({'guarded': True, 'pid': os.getpid()}))
''')
        self.guard.allow_python_script(script)
        result = subprocess.run([sys.executable, str(script)], env={"FIXTURE_ONLY": "synthetic"},
                                cwd=self.work, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        receipt = json.loads((self.guard.root / f"process-{output['pid']}.json").read_text())
        self.assertEqual(receipt["exit_code"], 0)
        self.assertTrue(receipt["identity_preserved"])
        self.assertTrue(receipt["shutdown_complete"])
        self.assertEqual(receipt["events"]["blocked:external_write"], 2)
        for kind in ("credential_path", "network:socket.__new__"):
            self.assertEqual(receipt["events"]["blocked:" + kind], 1)

    def test_script_hash_and_shell_denial(self):
        script = self.work / "changed.py"
        script.write_text("raise SystemExit(0)\n")
        self.guard.allow_python_script(script)
        script.write_text("raise SystemExit(9)\n")
        with self.assertRaisesRegex(PermissionError, "changed_child_script"):
            subprocess.run([sys.executable, str(script)])
        with self.assertRaisesRegex(PermissionError, "process"):
            subprocess.run("true", shell=True)

    def test_external_directory_entry_and_devnull_mutations(self):
        outside_link = self.guard.root.parent / "synthetic-external-link"
        target = self.work / "target.txt"
        target.write_text("retained")
        original_resolve = Path.resolve

        def resolve(path, *args, **kwargs):
            # Model a pre-existing outside symlink without creating an outside
            # directory entry. Emit only the audit event, never the mutation.
            if path == outside_link:
                return target
            return original_resolve(path, *args, **kwargs)

        with mock.patch.object(Path, "resolve", resolve):
            with self.assertRaisesRegex(PermissionError, "external_write"):
                sys.audit("os.remove", str(outside_link), -1)
            with self.assertRaisesRegex(PermissionError, "external_write"):
                sys.audit("os.rename", str(target), str(outside_link), -1, -1)
        with self.assertRaisesRegex(PermissionError, "external_write"):
            sys.audit("os.remove", os.devnull, -1)
        self.assertEqual(target.read_text(), "retained")

    def test_os_open_keeps_symlink_flag_semantics(self):
        target = self.work / "target.txt"
        target.write_text("unchanged")
        link = self.work / "link.txt"
        link.symlink_to(target)
        with self.assertRaises(OSError):
            os.open(link, os.O_RDONLY | os.O_NOFOLLOW)
        dangling = self.work / "dangling.txt"
        missing = self.work / "missing.txt"
        dangling.symlink_to(missing)
        with self.assertRaises(FileExistsError):
            os.open(dangling, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        self.assertFalse(missing.exists())

    def test_relative_child_and_sibling_import(self):
        (self.work / "fixture_helper.py").write_text("VALUE = 'synthetic sibling'\n")
        script = self.work / "relative_fixture.py"
        script.write_text("import fixture_helper\nprint(fixture_helper.VALUE)\n")
        self.guard.allow_python_script(script)
        result = subprocess.run([sys.executable, script.name], cwd=self.work, env={},
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "synthetic sibling")

    def test_concurrent_child_admission_has_one_remaining_slot(self):
        script = self.work / "bounded_fixture.py"
        script.write_text("print('bounded')\n")
        self.guard.allow_python_script(script)
        barrier = threading.Barrier(4)
        original_count = self.guard.spawn_count
        original_children = set(self.guard.child_snapshot())
        self.guard.spawn_count = 63

        def attempt():
            barrier.wait(timeout=10)
            try:
                result = subprocess.run([sys.executable, str(script)], capture_output=True,
                                        text=True, timeout=20)
                return result.returncode
            except PermissionError:
                return "blocked"

        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda _: attempt(), range(4)))
            self.assertEqual(results.count(0), 1, results)
            self.assertEqual(results.count("blocked"), 3, results)
        finally:
            actual_launches = len(set(self.guard.child_snapshot()) - original_children)
            self.guard.spawn_count = original_count + actual_launches

    def test_saved_data_and_subprocess(self):
        repo = Path(__file__).resolve().parents[2]
        with self.assertRaisesRegex(PermissionError, "saved_data"):
            list((repo / "backend/uploads").iterdir())
        with self.assertRaisesRegex(PermissionError, "process"):
            subprocess.run([sys.executable, "-c", "raise SystemExit(0)"], check=True)

    def test_identity_and_environment(self):
        self.assertTrue(all(os.environ.get(k) == v for k, v in self.guard.identity.items()))
        self.assertEqual(os.environ["DRF_TEST_PROCESS"], "1")
        self.assertEqual(os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"], "1")
        import dotenv
        self.assertFalse(dotenv.load_dotenv())
        self.assertEqual(dotenv.dotenv_values(), {})
        with self.assertRaisesRegex(PermissionError, "identity_environment"):
            os.environ["HOME"] = str(self.work)
        self.assertEqual(os.environ.get("HOME"), self.guard.identity["HOME"])

    def test_sqlite_uri_denied_before_native_open(self):
        cwd = os.getcwd()
        os.chdir(self.work)
        try:
            # Emit the exact CPython event without letting native SQLite touch
            # an external file while demonstrating the pre-fix defect.
            with self.assertRaisesRegex(PermissionError, "sqlite_uri"):
                sys.audit("sqlite3.connect", "file:/outside.sqlite?mode=rwc")
        finally:
            os.chdir(cwd)

    def test_protected_lexical_path_is_not_erased(self):
        with self.assertRaisesRegex(PermissionError, "credential_path"):
            self.guard.path(self.work / ".env" / ".." / "synthetic.txt")

    def test_protected_evidence_destination(self):
        for name in (".env", ".ssh", "credentials"):
            candidate = self.work / name / "new-evidence"
            self.assertEqual(self.guard.protected_reason(candidate), "credential_path")
            self.assertFalse(candidate.exists())

    def test_bootstrap_refuses_reused_and_protected_roots(self):
        path = Path(__file__).resolve().parents[1] / "scripts/main_offline_pytest.py"
        spec = importlib.util.spec_from_file_location("runner_bootstrap_control", path)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        for candidate in (self.work, self.work / ".env"):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
                runner.main(["--evidence-dir", str(candidate), "--self-test"])
            self.assertEqual(result.exception.code, 2)
        self.assertFalse((self.work / ".env").exists())

    def test_original_annotation_and_dotenv_submodule_semantics(self):
        from app.utils import logger
        self.assertIs(logger.setup_logger.__annotations__["name"], str)
        import dotenv.main
        self.assertFalse(dotenv.main.load_dotenv())

    def test_system_mime_database_is_read_only(self):
        import mimetypes
        self.assertEqual(mimetypes.guess_type("report.md")[0], "text/markdown")
        with self.assertRaisesRegex(PermissionError, "external_write"):
            Path("/private/etc/apache2/mime.types").write_text("blocked")

    def test_application_import_roots(self):
        from app.config import Config
        from app.utils import logger
        for value in (Config.UPLOAD_FOLDER, Config.PIPELINE_DATA_DIR,
                      Config.OASIS_SIMULATION_DATA_DIR, Config.GRAPHITI_DATA_DIR,
                      Config.DATA_SOURCES_CACHE_DIR, Config.FORECAST_LEDGER_DIR,
                      Config.EMBED_DISK_CACHE_PATH, logger.LOG_DIR):
            self.assertTrue(Path(value).resolve().is_relative_to(self.guard.root), value)
        logger.get_logger("mirofish.offline-control").info("synthetic offline import control")


if __name__ == "__main__":
    unittest.main()
