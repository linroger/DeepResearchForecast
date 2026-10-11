"""Exception controls for the sidecar supervisor; no native/app work executes."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify_deployment_fixtures.py"


@pytest.fixture
def sidecar(monkeypatch):
    spec = importlib.util.spec_from_file_location("sidecar_control_flow", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "sandbox_controls", lambda *args: {"synthetic_control": True})
    return module


def fault_handler(sidecar, failure):
    def run(manifest, output):
        output.update(transport_owned_result=True, exit_code=0, child_cleanup_complete=True)
        sidecar.write_json(Path(manifest["work"]) / "worker-result.json", output)
        raise failure
    return run


@pytest.mark.parametrize("suite", ["transport", "integration"])
def test_owned_failure_overrides_stale_success_in_worker_and_receipt(sidecar, monkeypatch, tmp_path, suite):
    work = tmp_path / "work"
    work.mkdir()
    manifest = work / "manifest.json"
    sidecar.write_json(manifest, {"work": str(work), "suite": suite, "copies": {},
                                 "identity": sidecar.identity_snapshot()})
    cleanup = []
    monkeypatch.setattr(sidecar.Processes, "cleanup", lambda self: cleanup.append("outer") or True)
    monkeypatch.setattr(sidecar, suite + "_worker", fault_handler(sidecar, RuntimeError("controlled failure after owned success")))
    assert sidecar.worker(manifest) == 1
    result = json.loads((work / "worker-result.json").read_text())
    assert result["exit_code"] == 1
    assert "controlled failure after owned success" in result["error"]
    assert result["child_cleanup_complete"] is True
    assert cleanup == [], "the owned worker already performed its cleanup"


def test_owned_finally_cannot_suppress_system_exit(sidecar, monkeypatch, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    manifest = work / "manifest.json"
    sidecar.write_json(manifest, {"work": str(work), "suite": "transport", "copies": {},
                                 "identity": sidecar.identity_snapshot()})
    monkeypatch.setattr(sidecar, "transport_worker", fault_handler(sidecar, SystemExit(23)))
    with pytest.raises(SystemExit) as raised:
        sidecar.worker(manifest)
    assert raised.value.code == 23


@pytest.mark.parametrize("suite", ["transport", "integration"])
def test_parent_supervisor_cannot_accept_failed_owned_worker(sidecar, monkeypatch, tmp_path, suite):
    """Run actual main/worker control flow; fake only native process dispatch."""
    monkeypatch.setattr(sidecar, suite + "_worker", fault_handler(sidecar, RuntimeError("controlled parent failure")))
    class Process:
        def __init__(self, command, **kwargs):
            self.command = command
            self.pid = 900001 if command[0] == "/bin/sleep" else 900002
            self.returncode = None
        def communicate(self, timeout=None):
            # The production worker code determines the simulated child's exit
            # status. No fixture script, native subprocess or model runs here.
            self.returncode = sidecar.worker(Path(self.command[-1]))
            return "", ""
        def terminate(self):
            self.returncode = -15
        def wait(self, timeout=None):
            return self.returncode
        def poll(self):
            return self.returncode
    monkeypatch.setattr(sidecar.subprocess, "Popen", Process)
    evidence = tmp_path / "parent"
    assert sidecar.main(["--suite", suite, "--evidence-dir", str(evidence)]) == 1
    completed = json.loads((evidence / "completed.json").read_text())
    worker = json.loads((evidence / "work/worker-result.json").read_text())
    assert completed["exit_code"] == worker["exit_code"] == 1
    assert "controlled parent failure" in worker["error"]
    assert completed["child_reaped"] and completed["sentinel_reaped"] and completed["ps_broker_stopped"]
