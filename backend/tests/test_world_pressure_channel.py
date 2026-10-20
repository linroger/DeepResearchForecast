"""The world channel: what the world did reaches the scenario shares (offline).

Before 2026-10-20 the shares moved only with the actors' self-declared ``scenario_commitment``s; the
arbiter's world-grounded ``scenario_pressure`` was recorded and ignored, so a period in which a deal
took shape but every actor abstained left the outcome untouched.  Now an applied arbiter's pressure
enters ``WorldState.step`` as one more commitment set (``worldstate.pressure_commitments``), weighted
at ``SIM_WORLD_PRESSURE_WEIGHT`` (default 0.35) of the actors' committed weight; failed arbiter
rounds and rounds the Foglamp statuses freeze add nothing, and 0 turns the channel off.
"""

import json
import os
import re

import pytest

from app.services.worldstate import (
    ROUND_STATUS_ABSTAINED,
    ROUND_STATUS_COMMITTED,
    ROUND_STATUS_SILENT,
    WorldState,
    commitment_mass,
    pressure_commitments,
)
from test_calendar_round_loop import _run
from test_world_model_loop import _WorldLLM, _patch_world, _world_config

# -- the pure helper ---------------------------------------------------------------------------

def test_pressure_tilts_the_current_shares_and_renormalises():
    rows = pressure_commitments({"A": "up", "B": "down"}, {"A": 0.5, "B": 0.5}, 2.0, weight_ratio=0.35)
    assert {r["scenario"]: r["magnitude"] for r in rows} == {"A": 0.625, "B": 0.375}
    assert {r["weight"] for r in rows} == {0.7} and {r["channel"] for r in rows} == {"world"}
    assert commitment_mass(rows) == pytest.approx(0.7)          # the channel's whole weight


@pytest.mark.parametrize("pressure, ratio", [
    ({}, 0.35), (None, 0.35), ({"A": "flat", "B": "flat"}, 0.35), ({"A": "up"}, 0.0), ({"Z": "up"}, 0.35),
])
def test_no_pressure_or_a_disabled_channel_adds_nothing(pressure, ratio):
    assert pressure_commitments(pressure, {"A": 0.5, "B": 0.5}, 1.0, weight_ratio=ratio) == []


def test_without_actor_commitments_the_world_alone_sets_the_target():
    ws = WorldState(["A", "B"], {"A": 0.5, "B": 0.5}, inertia=0.7)
    rows = pressure_commitments({"B": "up"}, ws.shares, 0.0, weight_ratio=0.35)
    ws.step(rows, round_status=ROUND_STATUS_ABSTAINED)
    assert ws.shares["B"] == pytest.approx(0.7 * 0.5 + 0.3 * (0.625 / 1.125), abs=1e-6)   # B up, A untouched


def test_with_actor_commitments_the_world_leans_the_step_against_them():
    actors = [{"scenario": "A", "magnitude": 1.0, "weight": 1.0}]
    plain = WorldState(["A", "B"], {"A": 0.5, "B": 0.5}, inertia=0.7)
    plain.step(actors, round_status=ROUND_STATUS_COMMITTED)
    leaned = WorldState(["A", "B"], {"A": 0.5, "B": 0.5}, inertia=0.7)
    world = pressure_commitments({"B": "up"}, leaned.shares, commitment_mass(actors), weight_ratio=0.35)
    leaned.step(actors + world, round_status=ROUND_STATUS_COMMITTED)
    assert plain.shares["A"] == pytest.approx(0.7 * 0.5 + 0.3 * 1.0)
    assert 0.5 < leaned.shares["A"] < plain.shares["A"]          # still the actors' way, less far


def test_a_frozen_round_ignores_the_world_channel():
    ws = WorldState(["A", "B"], {"A": 0.5, "B": 0.5})
    ws.step(pressure_commitments({"B": "up"}, ws.shares, 0.0, weight_ratio=0.35), round_status=ROUND_STATUS_SILENT)
    assert ws.shares == {"A": 0.5, "B": 0.5}


# -- the round loop ----------------------------------------------------------------------------

class _AbstainLLM(_WorldLLM):
    """Every actor speaks but abstains on the outcome; the arbiter sees a deal taking shape."""

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, **kwargs):
        content = messages[-1]["content"]
        if "# DECIDE YOUR MOVE FOR THIS PERIOD" in content:
            match = re.search(r"# DECIDE YOUR MOVE FOR THIS PERIOD — (.+)", content)
            actor = match.group(1).strip() if match else "?"
            _WorldLLM.calls.append({"kind": "decision", "round": self._round_of(content), "actor": actor,
                                    "content": content, "system": ""})
            return {"option_id": "public_statement", "public_statement": f"{actor} is watching the talks.",
                    "scenario_commitment": "abstain"}
        if "consequence arbiter" in content:
            _WorldLLM.calls.append({"kind": "arbiter", "round": None, "actor": None, "content": content})
            if _WorldLLM.arbiter_fail:
                raise RuntimeError("arbiter provider down")
            return {"narrative": "A deal takes shape.", "scenario_pressure": {"B": "up", "A": "down"}}
        raise AssertionError(f"unexpected prompt: {content[:80]}")


def _trajectory(sim_dir):
    with open(os.path.join(sim_dir, "world_state_trajectory.json"), encoding="utf-8") as f:
        return json.load(f)


def _run_abstaining(tmp_path, monkeypatch, *, weight=None, arbiter_fail=False):
    sim_dir = str(tmp_path)
    _patch_world(monkeypatch, sim_dir, [])
    monkeypatch.setattr("app.utils.llm_client.LLMClient", _AbstainLLM)
    _WorldLLM.arbiter_fail = arbiter_fail
    if weight is not None:
        monkeypatch.setenv("SIM_WORLD_PRESSURE_WEIGHT", str(weight))
    _run(_world_config(), sim_dir)
    return _trajectory(sim_dir)


def test_abstaining_actors_no_longer_freeze_the_outcome_when_the_world_moves(tmp_path, monkeypatch):
    traj = _run_abstaining(tmp_path, monkeypatch)
    rows = traj["trajectory"][1:]
    assert [r["round_status"] for r in rows] == ["abstained"] * 3       # the actors' status is unchanged
    b = [traj["trajectory"][0]["shares"]["B"]] + [r["shares"]["B"] for r in rows]
    assert b[0] < b[1] < b[2] < b[3]                                   # the world leaned it every period
    assert rows[0]["channels"] == {"actors": 0.0, "world": 0.35, "pressure": {"B": "up", "A": "down"}}


def test_the_channel_can_be_switched_off(tmp_path, monkeypatch):
    traj = _run_abstaining(tmp_path, monkeypatch, weight=0)
    rows = traj["trajectory"][1:]
    start = traj["trajectory"][0]["shares"]["B"]
    assert all(abs(r["shares"]["B"] - start) < 0.02 for r in rows)    # only the calendar entropy floor
    assert all("channels" not in r for r in rows)


def test_a_failed_arbiter_adds_no_world_pressure(tmp_path, monkeypatch):
    traj = _run_abstaining(tmp_path, monkeypatch, arbiter_fail=True)
    rows = traj["trajectory"][1:]
    start = traj["trajectory"][0]["shares"]["B"]
    assert all(abs(r["shares"]["B"] - start) < 0.02 for r in rows)
    assert all("channels" not in r for r in rows)
