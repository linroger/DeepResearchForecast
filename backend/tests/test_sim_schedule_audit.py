"""SIM-3 (C16) — scheduled-event reachability audit and world_digest.jsonl rotation.

* ``audit_scheduled_events`` gives every event the first matching reason
  (invalid_round → beyond_total_rounds → missing_poster → missing_content), counts
  them per reason and keeps at most 10 deterministic samples; a row that makes
  ``fire_scheduled_events`` raise (non-mapping, or a round int() rejects) blocks
  every other row too (blocked_by_invalid_round), pinned against the real
  ``fire_scheduled_events``;
* ``unreachable_issue`` turns a stored ``schedule_audit`` block into the pipeline
  run-health issue only when the count is a positive int;
* a fresh start rotates world_digest.jsonl to ``.prev`` (the in-band evolver appends
  to it), while a resume keeps appending;
* both SIM-3 knobs are declared in Config and documented in .env.example.

Offline: pure functions, fire_scheduled_events on a stub env, and
SimulationRunner.start_simulation with Popen and the monitor thread stubbed (the
test_temporal_mode_contract harness). No LLM, no network.
"""

import asyncio
import json
import os
import sys

import pytest

from app.config import Config
from app.services import simulation_runner as sr_mod
from app.services.sim_schedule_audit import (
    MAX_SAMPLES,
    audit_scheduled_events,
    unreachable_issue,
)
from app.services.simulation_runner import SimulationRunner


def _ev(rnd, poster=3, content="Event text", **extra):
    row = {"round": rnd, "poster_agent_id": poster, "content": content, "date": "2026-07-01"}
    row.update(extra)
    return row


# ------------------------------------------------------------------ audit_scheduled_events
def test_event_beyond_total_rounds_is_the_only_unreachable():
    events = [_ev(0), _ev(5), _ev(99, is_scenario_injection=True)]
    audit = audit_scheduled_events(events, 36)
    assert audit["scheduled"] == 3
    assert audit["unreachable"] == 1
    assert audit["by_reason"] == {"beyond_total_rounds": 1}
    assert audit["samples"] == [{"round": 99, "date": events[2]["date"],
                                 "reason": "beyond_total_rounds",
                                 "is_scenario_injection": True}]


def test_last_executed_round_is_reachable_and_horizon_round_is_not():
    # The platform loop runs range(start_round, total_rounds) over 0-based rounds.
    assert audit_scheduled_events([_ev(35)], 36)["unreachable"] == 0
    assert audit_scheduled_events([_ev(36)], 36)["by_reason"] == {"beyond_total_rounds": 1}


def test_missing_poster_and_missing_content():
    audit = audit_scheduled_events(
        [_ev(1, poster=None), _ev(2, content=""), _ev(3, content="   "), _ev(4, content=None)],
        36)
    assert audit["unreachable"] == 4
    assert audit["by_reason"] == {"missing_poster": 1, "missing_content": 3}
    assert [s["reason"] for s in audit["samples"]] == [
        "missing_poster", "missing_content", "missing_content", "missing_content"]
    # agent id 0 is a real poster, not a missing one
    assert audit_scheduled_events([_ev(1, poster=0)], 36)["unreachable"] == 0


@pytest.mark.parametrize("bad_round", ["x", -1, None, [], "1.5", float("nan"), float("inf")])
def test_invalid_round(bad_round):
    audit = audit_scheduled_events([_ev(bad_round)], 36)
    assert audit["by_reason"] == {"invalid_round": 1}
    assert audit["samples"][0]["reason"] == "invalid_round"
    # a sample never breaks the run_summary.json dump or a strict JSON reader
    json.loads(json.dumps(audit, allow_nan=False))


@pytest.mark.parametrize("bad_round, stored", [(float("nan"), "nan"), (float("inf"), "inf"),
                                               (float("-inf"), "-inf")])
def test_non_finite_round_is_stored_as_a_string(bad_round, stored):
    assert audit_scheduled_events([_ev(bad_round)], 36)["samples"][0]["round"] == stored
    sample = audit_scheduled_events([_ev(1, poster=None, date=bad_round)], 36)["samples"][0]
    assert sample["date"] == stored


def test_missing_round_key_and_non_mapping_event_are_invalid():
    audit = audit_scheduled_events([{"poster_agent_id": 1, "content": "c"}, "junk"], 36)
    assert audit["by_reason"] == {"invalid_round": 2}
    assert audit["samples"][1] == {"round": None, "date": None, "reason": "invalid_round",
                                   "is_scenario_injection": False}


@pytest.mark.parametrize("blocker", [None, "x", [], "1.5", float("nan"), "junk-row"])
def test_row_that_breaks_the_due_list_blocks_every_event(blocker):
    # fire_scheduled_events runs int(e.get('round', -1)) over every row in every round,
    # so one such row makes each call raise and nothing on the schedule ever fires.
    bad = "junk-row" if blocker == "junk-row" else _ev(blocker)
    audit = audit_scheduled_events([_ev(0), bad, _ev(3)], 36)
    assert audit["scheduled"] == audit["unreachable"] == 3
    assert audit["by_reason"] == {"invalid_round": 1, "blocked_by_invalid_round": 2}
    assert [s["reason"] for s in audit["samples"]] == [
        "blocked_by_invalid_round", "invalid_round", "blocked_by_invalid_round"]
    json.loads(json.dumps(audit, allow_nan=False))
    # rows unreachable for their own reason keep it; only fireable rows become blocked
    audit = audit_scheduled_events([_ev(50), _ev(1, poster=None), bad, _ev(2)], 36)
    assert audit["by_reason"] == {"invalid_round": 1, "beyond_total_rounds": 1,
                                  "missing_poster": 1, "blocked_by_invalid_round": 1}
    assert list(audit["by_reason"])[-1] == "blocked_by_invalid_round"


def test_negative_or_missing_round_only_drops_its_own_row():
    # int() accepts -1 and the -1 default for a missing key, so the due list still builds
    for bad in (_ev(-1), {"poster_agent_id": 1, "content": "c"}):
        audit = audit_scheduled_events([_ev(0), bad, _ev(3)], 36)
        assert audit["unreachable"] == 1
        assert audit["by_reason"] == {"invalid_round": 1}


def test_int_coercible_round_follows_fire_scheduled_events():
    # fire_scheduled_events compares int(round) with the loop round, so "7" fires at 7.
    assert audit_scheduled_events([_ev("7")], 36)["unreachable"] == 0
    assert audit_scheduled_events([_ev("40")], 36)["by_reason"] == {"beyond_total_rounds": 1}


def test_first_matching_reason_wins():
    # invalid round beats everything; beyond-horizon beats a missing poster/content
    audit = audit_scheduled_events(
        [_ev(-3, poster=None, content=""), _ev(50, poster=None, content="")], 36)
    assert audit["by_reason"] == {"invalid_round": 1, "beyond_total_rounds": 1}
    assert audit_scheduled_events([_ev(1, poster=None, content="")], 36)["by_reason"] == {
        "missing_poster": 1}


@pytest.mark.parametrize("total_rounds", [None, 0, -5, "36", True])
def test_non_positive_int_total_rounds_skips_horizon_check(total_rounds):
    audit = audit_scheduled_events([_ev(500), _ev(1, poster=None)], total_rounds)
    assert audit["by_reason"] == {"missing_poster": 1}


def test_deterministic_and_samples_capped():
    events = [_ev(100 + i) for i in range(15)] + [_ev(2, poster=None)]
    first = audit_scheduled_events(events, 36)
    assert first == audit_scheduled_events(list(events), 36)
    assert first["unreachable"] == 16
    assert first["by_reason"] == {"beyond_total_rounds": 15, "missing_poster": 1}
    assert len(first["samples"]) == MAX_SAMPLES == 10
    assert [s["round"] for s in first["samples"]] == list(range(100, 110))  # schedule order
    assert list(first["by_reason"]) == ["beyond_total_rounds", "missing_poster"]


def test_empty_schedule():
    assert audit_scheduled_events([], 36) == {
        "scheduled": 0, "unreachable": 0, "by_reason": {}, "samples": []}
    assert audit_scheduled_events(None, 36)["scheduled"] == 0


# ------------------------------------------------- parity with the real fire_scheduled_events
class _Graph:
    def get_agent(self, aid):
        return f"agent-{aid}"


class _Env:
    def __init__(self):
        self.agent_graph = _Graph()

    async def step(self, actions):
        return None


def _fired_over_run(rps, events, total_rounds):
    """Events fire_scheduled_events posts over range(0, total_rounds), with the platform
    loop's own guard (an exception skips that round's schedule, the run goes on)."""
    fired = 0
    for loop_round in range(total_rounds):
        try:
            fired += asyncio.run(rps.fire_scheduled_events(
                _Env(), {"scheduled_events": events}, loop_round, {}, None, lambda _m: None))
        except Exception:  # noqa: BLE001 — mirrors the caller's '定时事件触发异常，跳过'
            continue
    return fired


@pytest.fixture(scope="module")
def rps():
    scripts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import run_parallel_simulation
    return run_parallel_simulation


@pytest.mark.parametrize("events", [
    [_ev(0), _ev(5), _ev(99)],
    [_ev(0), _ev(None)],
    [_ev(0), "junk"],
    [_ev(1), _ev(float("nan"))],
    [_ev(1), _ev("1.5"), _ev(2, poster=None)],
    [_ev(0), _ev(-1), {"poster_agent_id": 1, "content": "c"}],
    [_ev(2, poster=None), _ev(3, content=""), _ev("7"), _ev(4), _ev(4, poster=5)],
], ids=["horizon", "none-round", "non-mapping", "nan-round", "string-float", "negative",
        "poster-content"])
def test_audit_matches_fire_scheduled_events(rps, monkeypatch, events):
    """Drift guard: scheduled - unreachable equals what fire_scheduled_events really posts
    over the run. If fire_scheduled_events starts skipping bad rows one by one, this fails
    and blocked_by_invalid_round must go (whitespace-only content is the one deliberate
    difference and is left out here)."""
    monkeypatch.setenv("SIM_EVENT_PROVENANCE", "true")
    total_rounds = 10
    audit = audit_scheduled_events(events, total_rounds)
    assert _fired_over_run(rps, events, total_rounds) == audit["scheduled"] - audit["unreachable"]


# ------------------------------------------------------------------ unreachable_issue
def test_unreachable_issue_text_and_count():
    k, issue = unreachable_issue(
        {"unreachable": 2, "by_reason": {"beyond_total_rounds": 1, "missing_poster": 1}})
    assert k == 2
    assert issue == ("2 scheduled event(s) could never fire "
                     "(beyond_total_rounds=1, missing_poster=1) — "
                     "the simulated actors never saw them")


@pytest.mark.parametrize("block", [None, {}, [], "3", {"unreachable": 0},
                                   {"unreachable": -1}, {"unreachable": "2"},
                                   {"unreachable": True}])
def test_unreachable_issue_none_for_absent_zero_or_malformed(block):
    assert unreachable_issue(block) is None


def test_unreachable_issue_tolerates_malformed_by_reason():
    k, issue = unreachable_issue({"unreachable": 1, "by_reason": "junk"})
    assert k == 1 and "(reason unknown)" in issue


# ------------------------------------------------------------------ world_digest rotation
@pytest.fixture
def runner_env(tmp_path, monkeypatch):
    """Isolated RUN_STATE_DIR, clean registries, Popen and the monitor thread stubbed."""
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    for name in ("_run_states", "_run_state_last_save", "_processes", "_action_queues",
                 "_monitor_threads", "_stdout_files", "_stderr_files",
                 "_graph_memory_enabled"):
        monkeypatch.setattr(SimulationRunner, name, {})
    monkeypatch.setattr(SimulationRunner, "_cleanup_done", True, raising=False)

    class _Proc:
        def __init__(self, cmd, **_kwargs):
            self.cmd = cmd
            self.pid = os.getpid()

        def poll(self):
            return None

    monkeypatch.setattr(sr_mod.subprocess, "Popen", _Proc)
    monkeypatch.setattr(SimulationRunner, "_monitor_simulation", lambda simulation_id: None)
    monkeypatch.setattr(Config, "SIM_RESUME", False, raising=False)
    return tmp_path


def _prepare_rerun(root, sim_id):
    sim_dir = root / sim_id
    (sim_dir / "twitter").mkdir(parents=True)
    (sim_dir / "simulation_config.json").write_text(json.dumps(
        {"time_config": {"total_simulation_hours": 6, "minutes_per_round": 60}}),
        encoding="utf-8")
    (sim_dir / "twitter" / "checkpoint.json").write_text(
        json.dumps({"completed_round": 2}), encoding="utf-8")
    (sim_dir / "world_digest.jsonl").write_text('{"round": 1}\n', encoding="utf-8")
    return sim_dir


def test_fresh_start_rotates_world_digest(runner_env):
    sim_dir = _prepare_rerun(runner_env, "sim_digest_fresh")
    SimulationRunner.start_simulation("sim_digest_fresh", platform="parallel", resume=False)
    assert not (sim_dir / "world_digest.jsonl").exists()
    assert (sim_dir / "world_digest.jsonl.prev").read_text(encoding="utf-8") == '{"round": 1}\n'


def test_resume_keeps_appending_to_world_digest(runner_env):
    sim_dir = _prepare_rerun(runner_env, "sim_digest_resume")
    state = SimulationRunner.start_simulation("sim_digest_resume", platform="parallel",
                                              resume=True)
    assert state.resumed_from_round == 2
    assert (sim_dir / "world_digest.jsonl").read_text(encoding="utf-8") == '{"round": 1}\n'
    assert not (sim_dir / "world_digest.jsonl.prev").exists()


# ------------------------------------------------------------------ knobs
@pytest.mark.parametrize("name", ["SIM_SCHEDULE_AUDIT", "SIM_ORGANIC_EXCLUDES_ENGAGEMENT_SAMPLES"])
def test_knob_defaults_on_and_is_documented(name):
    import app.config as cfgmod
    with open(cfgmod.__file__, encoding="utf-8") as f:
        src = f.read()
    assert f"os.environ.get(\n        '{name}', 'true')" in src or \
        f"os.environ.get('{name}', 'true')" in src
    env_example = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(cfgmod.__file__)))), ".env.example")
    with open(env_example, encoding="utf-8") as f:
        assert f"# {name}=true" in f.read()
