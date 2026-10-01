"""SIM-7 (C31): human-authored ``outcome_power_overrides`` in scenario overlays.

``PipelineOrchestrator.apply_scenario_overlay_to_config`` gains the counterfactual
lever a what-if fork lacked: a declared, whole-run outcome power per actor in
[0, 10], labelled ``outcome_power_basis="scenario_overlay"``. Pins the
normalize_name matching, the per-entry fail-closed validation (skip + warning,
never a PREPARE crash), idempotent reapplication, the I-15 wall (visibility via
influence_overrides never becomes power), the unchanged no-key path, and the
pickup by both decision-channel producers: the post-hoc ``run_decision_channel``
replay and the in-band calendar evolver (``_InbandWorldEvolution``), whose
decisions rows carry the override. Offline and deterministic (FakeLLMClient).
"""

import copy
import json
import math
import os
import sys

import pytest

from app.services import decision_channel as dc
from app.services import pipeline_orchestrator as _po
from tests.conftest import FakeLLMClient

_apply = _po.PipelineOrchestrator.apply_scenario_overlay_to_config


def _config():
    return {
        "simulation_id": "sim_overlay_power",
        "agent_configs": [
            {"agent_id": 1, "entity_name": "Policy actor", "influence_weight": 2.0,
             "stance": "supportive"},
            {"agent_id": 2, "entity_name": "Market Maker", "influence_weight": 1.0,
             "stance": "opposing"},
        ],
        "event_config": {"initial_posts": [], "scheduled_events": []},
    }


class _RecordingLogger:
    """The orchestrator logger does not propagate (caplog misses ``mirofish.*``)."""

    def __init__(self):
        self.warnings = []

    def warning(self, msg, *args, **_kwargs):
        self.warnings.append(msg % args if args else msg)

    def info(self, *_args, **_kwargs):
        pass

    def debug(self, *_args, **_kwargs):
        pass


@pytest.fixture
def log(monkeypatch):
    rec = _RecordingLogger()
    monkeypatch.setattr(_po, "logger", rec)
    return rec


# ───────────────────────────────────────────────────────────── matching
@pytest.mark.parametrize("name", ["Policy actor", "  POLICY   ACTOR ", "policy-actor"])
def test_override_sets_power_and_basis_by_normalized_name(name, log):
    config = _config()
    out = _apply(config, {"outcome_power_overrides": {name: 0.2}})

    assert out is config  # in place, returned (unchanged contract)
    policy, market = config["agent_configs"]
    assert policy["outcome_power"] == 0.2
    assert policy["outcome_power_basis"] == "scenario_overlay"
    assert policy["influence_weight"] == 2.0  # visibility untouched
    assert "outcome_power" not in market and "outcome_power_basis" not in market
    assert log.warnings == []


def test_override_changes_only_the_two_power_fields(log):
    """The key adds exactly outcome_power + outcome_power_basis to the matched actor;
    every other overlay effect is the same as the overlay without the key."""
    overlay = {
        "label": "regulator weakened",
        "influence_overrides": {"Market Maker": 3.5},
        "stance_overrides": {"Policy actor": "neutral"},
        "injected_events": [{"round": 2, "poster_name": "Policy actor",
                             "content": "Agency budget cut"}],
    }
    without = _apply(_config(), copy.deepcopy(overlay))
    with_key = _apply(_config(), dict(copy.deepcopy(overlay),
                                      outcome_power_overrides={"Policy actor": 0.0}))

    policy = with_key["agent_configs"][0]
    assert policy.pop("outcome_power") == 0.0
    assert policy.pop("outcome_power_basis") == "scenario_overlay"
    assert json.dumps(with_key, sort_keys=True) == json.dumps(without, sort_keys=True)


# ─────────────────────────────────────────────────────────── validation
@pytest.mark.parametrize("value", [
    "abc", float("nan"), float("inf"), float("-inf"), -1, -1e-9, 11, 10.000001,
    True, None, [0.5], {"power": 1}, 10 ** 400,
])
def test_invalid_value_is_skipped_with_a_warning(value, log):
    config = _config()
    before = copy.deepcopy(config)

    _apply(config, {"outcome_power_overrides": {"Policy actor": value}})

    assert config == before
    assert len(log.warnings) == 1
    assert "outcome_power_overrides: skipped" in log.warnings[0]
    assert "'Policy actor'" in log.warnings[0]


def test_unknown_name_is_skipped_with_a_warning(log):
    config = _config()
    before = copy.deepcopy(config)

    _apply(config, {"outcome_power_overrides": {"Ghost regulator": 0.5, "---": 0.5}})

    assert config == before
    assert log.warnings == ["outcome_power_overrides: no agent named 'Ghost regulator'",
                            "outcome_power_overrides: no agent named '---'"]


def test_punctuation_only_name_never_matches_an_agent_whose_name_normalizes_empty(log):
    config = _config()
    config["agent_configs"].append({"agent_id": 3, "entity_name": "-"})
    before = copy.deepcopy(config)

    _apply(config, {"outcome_power_overrides": {"()": 1.0}})

    assert config == before
    assert log.warnings == ["outcome_power_overrides: no agent named '()'"]


@pytest.mark.parametrize("bad", [["Policy actor", 0.2], "Policy actor=0.2", 0.2])
def test_non_dict_overrides_are_ignored_with_a_warning(bad, log):
    config = _config()
    before = copy.deepcopy(config)

    _apply(config, {"outcome_power_overrides": bad})

    assert config == before
    assert len(log.warnings) == 1 and "outcome_power_overrides ignored" in log.warnings[0]


@pytest.mark.parametrize("value, expected", [
    (0, 0.0), (0.0, 0.0), (-0.0, 0.0), (10, 10.0), ("0.5", 0.5), (1.23456789, 1.234568),
])
def test_boundary_and_numeric_values_are_accepted(value, expected, log):
    config = _config()

    _apply(config, {"outcome_power_overrides": {"Policy actor": value}})

    power = config["agent_configs"][0]["outcome_power"]
    assert power == expected and isinstance(power, float)
    assert math.copysign(1.0, power) == 1.0  # -0.0 is folded into 0.0
    assert config["agent_configs"][0]["outcome_power_basis"] == "scenario_overlay"
    assert log.warnings == []


def test_zero_keeps_the_actor_in_the_roster(log):
    config = _config()
    _apply(config, {"outcome_power_overrides": {"Policy actor": 0}})

    assert [a["agent_id"] for a in config["agent_configs"]] == [1, 2]
    assert dc._outcome_power_map(config["agent_configs"]) == {1: 0.0}


def test_one_bad_entry_does_not_block_the_valid_ones(log):
    config = _config()

    _apply(config, {"outcome_power_overrides": {
        "Ghost": 1.0, "Policy actor": "abc", "Market Maker": 4.0}})

    policy, market = config["agent_configs"]
    assert "outcome_power" not in policy
    assert market["outcome_power"] == 4.0
    assert market["outcome_power_basis"] == "scenario_overlay"
    assert len(log.warnings) == 2


def test_two_spellings_of_one_actor_warn_and_the_later_wins(log):
    config = _config()

    _apply(config, {"outcome_power_overrides": {"Policy actor": 0.2, "POLICY ACTOR": 3}})

    assert config["agent_configs"][0]["outcome_power"] == 3.0
    assert len(log.warnings) == 1 and "name the same agent" in log.warnings[0]


# ─────────────────────────────────────────── reapply and independence
def test_reapplying_the_same_overlay_is_idempotent(log):
    overlay = {"outcome_power_overrides": {"Policy actor": 0.2, "Market Maker": 7},
               "influence_overrides": {"Market Maker": 0.5}}
    config = _config()
    _apply(config, overlay)
    once = copy.deepcopy(config)

    _apply(config, overlay)  # the corrupt-RUN path re-runs the prepare-stage application

    assert config == once


def test_influence_overrides_alone_never_set_outcome_power(log):
    """I-15 wall: visibility is never outcome power."""
    config = _config()
    _apply(config, {"influence_overrides": {"Policy actor": 50.0, "Market Maker": 0.0}})

    agents = config["agent_configs"]
    assert agents[0]["influence_weight"] == 50.0
    assert all("outcome_power" not in a and "outcome_power_basis" not in a for a in agents)
    assert dc._outcome_power_map(agents) == {}


@pytest.mark.parametrize("overlay", [
    None, {}, {"label": "no levers"}, {"outcome_power_overrides": {}},
    {"outcome_power_overrides": None},
])
def test_overlay_without_power_leaves_config_deep_equal(overlay, log):
    config = _config()
    before = json.dumps(config, ensure_ascii=False, indent=2)

    _apply(config, overlay)

    assert json.dumps(config, ensure_ascii=False, indent=2) == before
    assert log.warnings == []


# ───────────────────────────────────────────────── decision-channel pickup
def test_outcome_power_map_picks_up_the_override(log):
    config = _config()
    _apply(config, {"outcome_power_overrides": {"Policy actor": 0.2}})

    power = dc._outcome_power_map(config["agent_configs"])
    assert power == {1: 0.2}

    entries = list(dc._agent_meta_map(config["agent_configs"]).values())
    roster = dc._build_active_roster(
        entries, dc._activation_weight_map(config["agent_configs"]), power, 60)
    by_id = {e["agent_id"]: e for e in roster}
    assert by_id[1]["outcome_power"] == 0.2 and by_id[1]["outcome_power_known"] is True
    assert by_id[2]["outcome_power"] == 1.0 and by_id[2]["outcome_power_known"] is False


_SEED = {"scenarios": ["S1", "S2"], "base_rates": {"S1": 0.5, "S2": 0.5}}
_ROUNDS = (1, 2, 3)
_ACTIONS = [{"round": r, "agent_id": aid, "agent_name": name}
            for r in _ROUNDS for aid, name in ((1, "Policy actor"), (2, "Market Maker"))]
_BOTH = {"decisions": [
    {"agent_id": 1, "scenario": "S1", "magnitude": 0.6, "confidence": 0.8},
    {"agent_id": 2, "scenario": "S2", "magnitude": 1.0, "confidence": 1.0},
]}
_ONLY_1 = {"decisions": [_BOTH["decisions"][0]]}


def _replay(configs, reply):
    fake = FakeLLMClient(json_responses=[copy.deepcopy(reply) for _ in _ROUNDS])
    # concurrency=1 (SIM-2): FIFO fake replies land on their own round's roster
    return dc.run_decision_channel(copy.deepcopy(_ACTIONS), configs, copy.deepcopy(_SEED),
                                   fake, inertia=0.5, concurrency=1)


def test_post_hoc_replay_zero_power_actor_has_no_outcome_weight(log):
    """End to end: agent 2 overridden to 0.0 commits every round, yet the outcome is the
    run in which only agent 1 committed; its decisions rows carry outcome_power 0.0."""
    overridden = _config()
    _apply(overridden, {"outcome_power_overrides": {"Market Maker": 0.0}})

    res = _replay(overridden["agent_configs"], _BOTH)
    only_1 = _replay(_config()["agent_configs"], _ONLY_1)
    baseline = _replay(_config()["agent_configs"], _BOTH)

    rows_2 = [d for d in res["decisions"] if d["agent_id"] == 2]
    assert [d["round"] for d in rows_2] == list(_ROUNDS)
    assert all(d["outcome_power"] == 0.0 for d in rows_2)
    assert all(d["outcome_power"] == 1.0 for d in res["decisions"] if d["agent_id"] == 1)
    assert res["outcome"]["shares"] == only_1["outcome"]["shares"]
    assert ([t["shares"] for t in res["trajectory"]]
            == [t["shares"] for t in only_1["trajectory"]])
    # the override is what removed agent 2's pull: without it agent 2 moves the outcome
    assert baseline["outcome"]["shares"] != res["outcome"]["shares"]
    assert res["round_accounting"]["valid_transitions"] == len(_ROUNDS)


def test_inband_evolver_reads_the_override_into_decisions_rows(tmp_path, monkeypatch, log):
    """The in-band calendar producer (default path) consumes the same explicit power and
    writes it to decisions.jsonl, so the override is auditable per row."""
    scripts = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import run_parallel_simulation as rps

    period = {"round": 0, "period_start": "2026-10-01", "period_end": "2026-12-31",
              "label": "2026-Q4"}

    def _run_inband(sim_dir, reply, overlay):
        config = _config()
        config["temporal_config"] = {
            "schema_version": 1, "mode": "calendar", "as_of_date": "2026-09-30",
            "horizon_date": "2026-12-31", "unit": "quarter", "n_rounds": 1,
            "round_dates": [period]}
        config["world_state_seed"] = dict(_SEED, as_of_date="2026-09-30",
                                          horizon_date="2026-12-31")
        _apply(config, overlay)
        fake = FakeLLMClient(json_responses=[copy.deepcopy(reply)])
        monkeypatch.setattr("app.utils.llm_client.LLMClient", lambda *a, **k: fake)
        monkeypatch.setattr(rps, "_wrap_llm_client_usage", lambda client: client)
        os.makedirs(sim_dir, exist_ok=True)
        evo = rps._InbandWorldEvolution(config, sim_dir, 1, lambda _m: None)
        evo.deliver("twitter", 0, period, [
            {"agent_id": 1, "agent_name": "Policy actor",
             "action_args": {"content": "Agency issues guidance"}},
            {"agent_id": 2, "agent_name": "Market Maker",
             "action_args": {"content": "Desk widens spreads"}},
        ], [])
        evo.platform_done("twitter")
        with open(os.path.join(sim_dir, "decisions.jsonl"), encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        with open(os.path.join(sim_dir, "world_state_trajectory.json"), encoding="utf-8") as f:
            traj = json.load(f)
        return rows, traj

    rows, traj = _run_inband(str(tmp_path / "overridden"), _BOTH,
                             {"outcome_power_overrides": {"Market Maker": 0.0}})
    _rows_1, traj_1 = _run_inband(str(tmp_path / "only_1"), _ONLY_1, {})

    by_id = {r["agent_id"]: r for r in rows}
    assert by_id[2]["outcome_power"] == 0.0 and by_id[2]["scenario"] == "S2"
    assert by_id[1]["outcome_power"] == 1.0
    assert all("weight" not in r for r in rows)  # audit rows strip the step weight
    assert traj["outcome"]["shares"] == traj_1["outcome"]["shares"]
    assert traj["round_accounting"]["valid_transitions"] == 1
