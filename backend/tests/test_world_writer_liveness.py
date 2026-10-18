"""World liveness comes from the launch flock, not from a PID that macOS reuses.

Before the fix, status() and the store's writer takeover asked os.kill(pid, 0) whether the
recorded child lived. After a reboot (or any crash) that PID soon belongs to another live
process, so the world reported running forever and every start's child failed writer_active
before acquiring a fence, silently (persistence review B1). The child had no SIGTERM handler,
so a shutdown left its writer fence held. PID 1 (always alive, never ours) stands in for a
reused PID: os.kill on it fails with a permission error, which the old probe read as alive.
"""
import json
import logging
import os
import signal
import sqlite3

import pytest

from app.services.world_simulation.artifacts import atomic_json, exclusive_file, read_json
from app.services.world_simulation.examples import ExamplePolicy
from app.services.world_simulation.service import WorldSimulationService as Service, run_child
from app.services.world_simulation.store import WorldStore
from test_world_service_results import prepare

pytestmark = pytest.mark.guarded_runner
REUSED_PID = 1


def projection(state, directory, **fields):
    atomic_json(directory / "world_run.json", {"simulation_id": state.simulation_id,
                "generation_id": state.world_generation_id, "launch_id": "launch_before_reboot",
                "runner_status": "running", "process_pid": REUSED_PID, "error": None, **fields})


def crashed_writer(directory):
    """A child that died holding its fence (no release), its PID now reused."""
    from app.services.world_simulation.artifacts import load_inputs

    spec, _ = load_inputs(directory)
    store = WorldStore(directory / "world.sqlite3", spec)
    store.acquire_writer("child_before_reboot", pid=REUSED_PID)
    store._db.close()
    store._closed = True


def writer_owner(directory):
    with sqlite3.connect(directory / "world.sqlite3") as db:
        owner = db.execute("SELECT owner, pid FROM writer").fetchone()
    db.close()
    return owner


def test_status_reports_a_dead_child_even_when_its_pid_was_reused(tmp_path):
    _, state, directory = prepare(tmp_path)
    projection(state, directory)
    status = Service.status(state.simulation_id, root=tmp_path)
    assert status["runner_status"] == "failed"
    assert status["error"] == "child_exited_before_committed_horizon"


def test_status_reports_running_while_a_child_holds_the_launch_lock(tmp_path):
    _, state, directory = prepare(tmp_path)
    projection(state, directory, process_pid=99999999)  # Not even a live PID: the lock decides.
    with exclusive_file(directory / "world_launch.lock", blocking=False):
        assert Service.status(state.simulation_id, root=tmp_path)["runner_status"] == "running"
    assert Service.status(state.simulation_id, root=tmp_path)["runner_status"] == "failed"


def test_next_child_takes_over_a_writer_whose_pid_was_reused(tmp_path):
    _, state, directory = prepare(tmp_path)
    crashed_writer(directory)
    projection(state, directory)
    assert run_child(directory, policy=ExamplePolicy("investment")) == 0
    assert Service.status(state.simulation_id, root=tmp_path)["runner_status"] == "completed"
    assert writer_owner(directory) == (None, None)


def test_inherited_descriptor_must_hold_the_launch_lock(tmp_path):
    _, state, directory = prepare(tmp_path)
    with exclusive_file(directory / "world_launch.lock", blocking=False):  # Someone else's live launch.
        stray = os.open(directory / "world_launch.lock", os.O_RDWR)
        try:
            assert run_child(directory, policy=ExamplePolicy("investment"), launch_lock_fd=stray) == 1
        finally:
            os.close(stray)
    assert not (directory / "world.sqlite3").exists()


def test_failure_before_the_fence_is_logged_without_touching_the_projection(tmp_path, caplog):
    _, state, directory = prepare(tmp_path)
    projection(state, directory, launch_id="the_current_launch")
    before = (directory / "world_run.json").read_bytes()
    with caplog.at_level(logging.WARNING, logger="app.services.world_simulation.service"):
        assert run_child(directory, policy=ExamplePolicy("investment"), launch_id="a_stale_launch") == 1
    assert (directory / "world_run.json").read_bytes() == before
    failures = [record for record in caplog.records if "before acquiring its writer fence" in record.getMessage()]
    assert len(failures) == 1 and "launch_changed" in failures[0].getMessage()


def test_sigterm_becomes_cancel_and_release(tmp_path):
    _, state, directory = prepare(tmp_path)
    received = []

    def fallback(signum, frame):  # Keeps the test process alive should the child ignore SIGTERM.
        received.append(signum)

    class Terminated(ExamplePolicy):
        def decide(self, obs):
            if not received and obs["actorId"] == "buyer":
                received.append("raised")
                signal.raise_signal(signal.SIGTERM)
            return super().decide(obs)

    previous = signal.signal(signal.SIGTERM, fallback)
    try:
        assert run_child(directory, policy=Terminated("investment")) == 1
        assert signal.getsignal(signal.SIGTERM) is fallback  # The child's handler was scoped to the run.
    finally:
        signal.signal(signal.SIGTERM, previous)
    assert received == ["raised"]
    record = read_json(directory / "world_run.json")
    assert record["runner_status"] == "stopped" and record["error"] == "terminated"
    assert writer_owner(directory) == (None, None)
    assert Service.status(state.simulation_id, root=tmp_path)["runner_status"] == "stopped"
    assert run_child(directory, policy=ExamplePolicy("investment")) == 0  # And it resumes.


def test_a_writer_in_this_same_process_is_never_taken_over(tmp_path):
    from app.services.world_simulation.artifacts import load_inputs

    _, state, directory = prepare(tmp_path)
    spec, _ = load_inputs(directory)
    with WorldStore(directory / "world.sqlite3", spec) as store:
        fence = store.acquire_writer("live_owner")
        assert run_child(directory, policy=ExamplePolicy("investment")) == 1
        store.release_writer(fence)
    assert json.loads((directory / "state.json").read_text())["status"] == "ready"
