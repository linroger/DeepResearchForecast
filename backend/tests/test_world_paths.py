"""A distribution of futures: K seeded world paths per committed round (design §2.12).

Pure part: the settings clamps, per-path RNG streams (path 0 keeps the single-path stream) and the
aggregation of shares, shocks and facts across paths.  Loop part (the real calendar round loop with the
scripted LLM of ``test_world_model_loop``): with ``SIM_WORLD_PATHS=K`` each round runs K world updates
that share the actors' decisions — no extra decision call, K arbiter calls at most, the siblings at the
bounded sampling temperature — path 0 and everything the agents see stay byte-identical to a one-path
run (herding guard), trajectory rows and the summary carry ``paths``, the siblings are reproducible for
a seed and restored on resume, K is capped, and a failing sibling never touches path 0.
"""

import asyncio
import json
import math
import os
import random
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_BACKEND, "scripts")
for _p in (_BACKEND, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import run_parallel_simulation as rps  # noqa: E402
from app.services import world_paths as wp  # noqa: E402
from app.services.world_model import WorldModel  # noqa: E402
from test_calendar_round_loop import _run, _world_clock_notes  # noqa: E402
from test_world_model_loop import _WorldLLM, _patch_world, _read_jsonl, _world_config  # noqa: E402


# ============================================================================ pure
@pytest.mark.parametrize("raw,expected", [
    (None, (1, "")), ("", (1, "")), ("1", (1, "")), ("3", (3, "")), ("4.0", (4, "")), ("8", (8, "")),
    ("0", (1, "SIM_WORLD_PATHS=0 is below 1; running one path")),
    ("-2", (1, "SIM_WORLD_PATHS=-2 is below 1; running one path")),
    ("many", (1, "SIM_WORLD_PATHS='many' is not a number; running one path")),
    ("20", (8, "SIM_WORLD_PATHS=20 exceeds the cap; running 8 paths")),
])
def test_path_count_is_clamped(raw, expected):
    assert wp.resolve_path_count(raw) == expected


@pytest.mark.parametrize("raw,expected", [("0.7", 0.7), ("0.3", 0.3), ("5", 1.0), ("-1", 0.0), ("hot", 0.7),
                                          ("nan", 0.7), (None, 0.7)])
def test_sibling_temperature_is_bounded(raw, expected):
    assert wp.resolve_path_temperature(raw) == expected


def test_path_rng_keeps_the_single_path_stream_and_separates_siblings():
    assert wp.path_rng(5, 0, 2).random() == random.Random(5 * 1000003 + 2).random()
    draws = {(p, r): wp.path_rng(5, p, r).random() for p in range(4) for r in (1, 2)}
    assert len(set(draws.values())) == len(draws)                       # every (path, round) its own stream
    assert wp.path_rng(5, 3, 2).random() == draws[(3, 2)]               # reproducible
    assert wp.path_rng(6, 3, 2).random() != draws[(3, 2)]               # and seeded


def test_share_distribution_statistics_and_leaders():
    rows = [{"A": 0.7, "B": 0.3}, {"A": 0.5, "B": 0.5}, {"A": 0.4, "B": 0.6}, {"A": 0.2, "B": 0.8}]
    dist = wp.share_distribution(rows, ["A", "B"])
    a = dist["shares"]["A"]
    assert dist["k"] == 4 and a["mean"] == 0.45 and a["min"] == 0.2 and a["max"] == 0.7
    assert a["sd"] == round(math.sqrt(((0.25 ** 2) + (0.05 ** 2) + (0.05 ** 2) + (0.25 ** 2)) / 4), 6)
    assert a["p50"] == 0.45 and a["p10"] == 0.26 and a["p90"] == 0.64       # linear interpolation
    assert dist["leaders"] == {"A": 2, "B": 2}                              # the 0.5 / 0.5 tie counts for A
    # a tie goes to the first scenario, as in WorldState.outcome
    assert wp.share_distribution([{"A": 0.5, "B": 0.5}], ["A", "B"])["leaders"] == {"A": 1}
    assert wp.share_distribution([], ["A"]) == {"k": 0, "shares": {}, "leaders": {}}


def _mini_world(value, fired=False):
    world = WorldModel.from_seed({
        "state_variables": [{"name": "Tariff rate", "value": value, "unit": "%"},
                            {"name": "Ports open", "value": 12, "unit": ""}],
        "actors": [{"agent_id": 0, "name": "Actor0"}],
        "shocks": [{"id": "shock_x", "event": "Port strike", "hazard_per_day": 0.01,
                    "base_rate": {"text": "5%", "window": "month"}, "source": "S1"}],
    }, [{"agent_id": 0, "entity_name": "Actor0"}])
    if fired:
        world.shocks[0].fired_rounds = [2]
    return world


def test_shock_frequency_and_variable_spread_across_paths():
    worlds = [_mini_world(20, fired=True), _mini_world(30), _mini_world(25, fired=True)]
    assert wp.shock_frequency(worlds) == {"shock_x": {"event": "Port strike", "base_rate": "5% per month",
                                                      "paths_fired": 2, "first_rounds": {"0": 2, "2": 2}}}
    # facts identical in every path are left out
    assert wp.variable_spread(worlds) == {"tariff_rate": {"name": "Tariff rate", "unit": "%", "min": 20.0,
                                                          "p50": 25.0, "max": 30.0}}


# ============================================================================ loop
class _PathLLM(_WorldLLM):
    """The loop test's scripted LLM; the siblings' arbiter (sampled above 0.3) leans to B instead of A."""
    temperatures = []
    fail_siblings = False

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, **kwargs):
        content = messages[-1]["content"]
        if "consequence arbiter" in content:
            _PathLLM.temperatures.append(temperature)
            if temperature != wp.BASE_ARBITER_TEMPERATURE:
                if _PathLLM.fail_siblings:
                    _WorldLLM.calls.append({"kind": "arbiter", "round": None, "actor": None, "content": content})
                    raise RuntimeError("sibling arbiter down")
                out = super().chat_json(messages, temperature, max_tokens, **kwargs)
                return {**out, "scenario_pressure": {"B": "up"}}
        return super().chat_json(messages, temperature, max_tokens, **kwargs)


def _run_paths(monkeypatch, sim_dir, *, k=None, temperature=None, cfg=None, resume=False, keep_calls=False):
    envs = []
    calls_before = list(_WorldLLM.calls) if keep_calls else []
    _patch_world(monkeypatch, str(sim_dir), envs)
    monkeypatch.setattr("app.utils.llm_client.LLMClient", _PathLLM)
    _WorldLLM.calls = calls_before
    _PathLLM.temperatures = []
    monkeypatch.setattr(rps, "_RNG", random.Random(7))                  # the activity sampler, reproducible
    for name, value in (("SIM_WORLD_PATHS", k), ("SIM_WORLD_PATH_TEMPERATURE", temperature)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    _run(cfg or _world_config(), str(sim_dir), resume=resume)
    return envs


def _json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _decision_pairs(calls):
    return sorted((c["actor"], c["round"]) for c in calls if c["kind"] == "decision")


def test_k_paths_share_decisions_and_report_a_distribution(tmp_path, monkeypatch):
    one, three = tmp_path / "one", tmp_path / "three"
    envs1 = _run_paths(monkeypatch, one, k="1")
    calls1, temps1 = list(_WorldLLM.calls), list(_PathLLM.temperatures)
    envs3 = _run_paths(monkeypatch, three, k="3", temperature="0.9")
    calls3, temps3 = list(_WorldLLM.calls), list(_PathLLM.temperatures)

    # cost: no extra decision call; one arbiter call per path and round (K per round)
    assert _decision_pairs(calls3) == _decision_pairs(calls1) and _decision_pairs(calls1)
    assert temps1 == [0.3] * 3
    assert sorted(temps3) == [0.3] * 3 + [0.9] * 6
    assert len([c for c in calls3 if c["kind"] == "arbiter"]) == 9

    # the agents live in path 0: everything they were shown, and every path-0 artifact, is byte-identical
    assert _world_clock_notes(envs3[0]) == _world_clock_notes(envs1[0]) and _world_clock_notes(envs1[0])
    for name in ("world_state_history.jsonl", "world_digest.jsonl", "world_actions.jsonl", "decisions.jsonl"):
        assert (three / name).read_bytes() == (one / name).read_bytes(), name
    s1, s3 = _json(one / "world_state.json"), _json(three / "world_state.json")
    assert {k: v for k, v in s3.items() if k != "summary"} == {k: v for k, v in s1.items() if k != "summary"}
    assert {k: v for k, v in s3["summary"].items() if k != "paths"} == s1["summary"]
    assert "paths" not in s1["summary"] and not (one / "world_paths.json").exists()

    # trajectory: path 0 rows unchanged, plus each scenario's share across the three paths
    t1, t3 = _json(one / "world_state_trajectory.json"), _json(three / "world_state_trajectory.json")
    assert t3["outcome"] == t1["outcome"]
    assert [{k: v for k, v in r.items() if k != "paths"} for r in t3["trajectory"]] == t1["trajectory"]
    assert [r.get("paths", {}).get("k") for r in t3["trajectory"]] == [None, 3, 3, 3]
    assert all("paths" not in r for r in t1["trajectory"]) and "paths" not in t1["world_model"]
    last = t3["trajectory"][-1]
    dist = last["paths"]["shares"]["A"]
    assert dist["max"] == pytest.approx(last["shares"]["A"], abs=1e-6)  # path 0 is the one the world pushed to A
    assert dist["min"] < dist["max"] and dist["sd"] > 0                  # the siblings' world leaned to B
    assert sum(last["paths"]["leaders"].values()) == 3

    # summary (world_state.json, trajectory world_model, run summary all read this block)
    paths = s3["summary"]["paths"]
    assert paths == t3["world_model"]["paths"]
    assert paths["k"] == 3 and paths["rounds"] == 3 and paths["arbiter_calls_per_round_max"] == 3
    assert paths["arbiter_temperature"] == {"path_0": 0.3, "siblings": 0.9}
    assert paths["shares"] == last["paths"]["shares"] and paths["leaders"] == last["paths"]["leaders"]
    assert [p["path"] for p in paths["per_path"]] == [0, 1, 2]
    assert paths["per_path"][0]["shares"] == {s: round(v, 6) for s, v in last["shares"].items()}
    assert all(p["arbiter_failed_rounds"] == 0 for p in paths["per_path"])
    assert paths["shocks"] == {} and "restarted_at_round" not in paths

    saved = _json(three / "world_paths.json")
    assert saved["k"] == 3 and saved["committed_round"] == 3 and saved["seed"] == 0
    assert [p["path"] for p in saved["paths"]] == [1, 2] and saved["arbiter_temperature"] == 0.9
    assert all(p["world"]["committed_round"] == 3 for p in saved["paths"])
    assert all(len(p["history"]) == 4 for p in saved["paths"])         # seed + three rounds
    # the herding guard holds with K paths: nothing about paths or shares reaches an agent
    notes = "\n".join(_world_clock_notes(envs3[0]))
    assert "path" not in notes.casefold() and "0.6" not in notes


def test_paths_are_reproducible_for_a_seed(tmp_path, monkeypatch):
    monkeypatch.setenv("SIM_SEED", "11")
    _run_paths(monkeypatch, tmp_path / "a", k="3")
    _run_paths(monkeypatch, tmp_path / "b", k="3")
    for name in ("world_paths.json", "world_state_trajectory.json", "world_state.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name
    assert _json(tmp_path / "a" / "world_paths.json")["seed"] == 11


def _stop_after_round_one(monkeypatch):
    orig_commit = rps._ReflexiveWorldCoordinator._commit_round
    stop = asyncio.Event()

    async def _commit_then_stop(self, round_num, buf):
        await orig_commit(self, round_num, buf)
        if round_num == 0:
            stop.set()

    monkeypatch.setattr(rps._ReflexiveWorldCoordinator, "_commit_round", _commit_then_stop)
    monkeypatch.setattr(rps, "_shutdown_event", stop)
    return orig_commit


def test_resume_restores_the_siblings_from_world_paths(tmp_path, monkeypatch):
    sim_dir = tmp_path / "sim"
    orig_commit = _stop_after_round_one(monkeypatch)
    _run_paths(monkeypatch, sim_dir, k="3")
    saved = _json(sim_dir / "world_paths.json")
    assert saved["committed_round"] == 1
    # mark path 1's world so a restore is told apart from a copy of path 0
    tariff = next(v for v in saved["paths"][0]["world"]["variables"] if v["id"] == "tariff_rate")
    tariff["value"] = 99.0
    tariff["history"].append({"round": 1, "value": 99.0, "cause": "marker", "source": "arbiter"})
    with open(sim_dir / "world_paths.json", "w", encoding="utf-8") as f:
        json.dump(saved, f)
    monkeypatch.setattr(rps._ReflexiveWorldCoordinator, "_commit_round", orig_commit)
    monkeypatch.setattr(rps, "_shutdown_event", None)
    rps._WORLD_COORDINATORS.clear()
    _run_paths(monkeypatch, sim_dir, k="3", resume=True, keep_calls=True)
    after = _json(sim_dir / "world_paths.json")
    assert after["committed_round"] == 3 and "restarted_at_round" not in after
    worlds = {p["path"]: {v["id"]: v for v in p["world"]["variables"]} for p in after["paths"]}
    assert worlds[1]["tariff_rate"]["value"] == 99.0
    assert any(h["cause"] == "marker" for h in worlds[1]["tariff_rate"]["history"])
    assert worlds[2]["tariff_rate"]["value"] == 25.0
    traj = _json(sim_dir / "world_state_trajectory.json")
    assert [r.get("paths", {}).get("k") for r in traj["trajectory"]] == [None, 3, 3, 3]
    assert traj["world_model"]["paths"]["variables"]["tariff_rate"]["max"] == 99.0


def test_resume_without_world_paths_restarts_the_siblings_from_path_0(tmp_path, monkeypatch):
    sim_dir = tmp_path / "sim"
    orig_commit = _stop_after_round_one(monkeypatch)
    _run_paths(monkeypatch, sim_dir, k="3")
    os.unlink(sim_dir / "world_paths.json")
    monkeypatch.setattr(rps._ReflexiveWorldCoordinator, "_commit_round", orig_commit)
    monkeypatch.setattr(rps, "_shutdown_event", None)
    rps._WORLD_COORDINATORS.clear()
    _run_paths(monkeypatch, sim_dir, k="3", resume=True, keep_calls=True)
    after = _json(sim_dir / "world_paths.json")
    assert after["restarted_at_round"] == 1 and after["committed_round"] == 3
    assert _json(sim_dir / "world_state.json")["summary"]["paths"]["restarted_at_round"] == 1


def test_path_count_is_capped_and_failing_sibling_arbiters_never_touch_path_0(tmp_path, monkeypatch):
    _PathLLM.fail_siblings = True
    try:
        _run_paths(monkeypatch, tmp_path, k="20")
    finally:
        _PathLLM.fail_siblings = False
    assert len([c for c in _WorldLLM.calls if c["kind"] == "arbiter"]) == 8 * 3   # capped at 8 paths
    history = _read_jsonl(os.path.join(tmp_path, "world_state_history.jsonl"))
    assert [h["arbiter_status"] for h in history] == ["applied"] * 3
    paths = _json(tmp_path / "world_state.json")["summary"]["paths"]
    assert paths["k"] == 8 and len(paths["per_path"]) == 8
    assert [p["arbiter_failed_rounds"] for p in paths["per_path"]] == [0] + [3] * 7
    # the failed siblings still committed every round deterministically and stepped their shares
    saved = _json(tmp_path / "world_paths.json")
    assert all(p["world"]["committed_round"] == 3 and len(p["history"]) == 4 for p in saved["paths"])
    tariff = {p["path"]: next(v["value"] for v in p["world"]["variables"] if v["id"] == "tariff_rate")
              for p in saved["paths"]}
    assert set(tariff.values()) == {10.0}                                  # no arbiter → no fabricated effect


def test_a_sibling_whose_update_raises_freezes_alone(tmp_path, monkeypatch):
    from app.services import world_update as wu
    real = wu.run_world_round

    def _flaky(world, rnd, *args, arbiter_temperature=0.3, **kwargs):
        if arbiter_temperature != 0.3 and rnd == 2:
            raise RuntimeError("kernel bug in a sibling")
        return real(world, rnd, *args, arbiter_temperature=arbiter_temperature, **kwargs)

    monkeypatch.setattr(wu, "run_world_round", _flaky)
    _run_paths(monkeypatch, tmp_path / "flaky", k="2")
    history = _read_jsonl(os.path.join(tmp_path / "flaky", "world_state_history.jsonl"))
    assert [h["arbiter_status"] for h in history] == ["applied"] * 3
    saved = _json(tmp_path / "flaky" / "world_paths.json")
    assert saved["paths"][0]["arbiter_failed_rounds"] == 1 and saved["paths"][0]["world"]["committed_round"] == 3


def test_shocks_make_paths_diverge_without_extra_sampling(tmp_path, monkeypatch):
    cfg = _world_config()
    cfg["world_model"]["shocks"] = [{
        "id": "shock_port_strike", "event": "Port strike", "hazard_per_day": -math.log(0.5) / 91.3125,
        "base_rate": {"probability": 0.5, "window": "quarter", "window_days": 91.3125, "text": "50%"},
        "source": "Port authority [S9]", "affects": ["Actor1"],
        "effects": [{"variable_id": "tariff_rate", "op": "add", "value": 5, "direction": "up"}]}]
    _run_paths(monkeypatch, tmp_path, k="4", temperature="0.3", cfg=cfg)
    assert _PathLLM.temperatures == [0.3] * 12                            # no extra sampling: rolls alone differ
    saved = _json(tmp_path / "world_paths.json")
    state = _json(tmp_path / "world_state.json")
    worlds = [state["world"]] + [p["world"] for p in saved["paths"]]
    fired = [w["shocks"][0]["fired_rounds"] for w in worlds]
    paths = state["summary"]["paths"]
    assert paths["shocks"]["shock_port_strike"]["paths_fired"] == sum(1 for f in fired if f)
    assert paths["shocks"]["shock_port_strike"]["base_rate"] == "50% per quarter"
    # the seeded rolls split the paths in time: three draw the strike in the first period, path 3 two
    # periods later, after the arbiter had already moved the tariff it hits (10% → 25%, then +5)
    assert fired == [[1], [1], [1], [3]]
    assert paths["shocks"]["shock_port_strike"]["first_rounds"] == {"0": 1, "1": 1, "2": 1, "3": 3}
    assert paths["variables"]["tariff_rate"] == {"name": "Tariff rate", "unit": "%", "min": 15.0, "p50": 15.0,
                                                 "max": 30.0}
    # every fired shock reached that path's arbiter as a confirmed event
    shock_prompts = [c for c in _WorldLLM.calls if c["kind"] == "arbiter" and "Exogenous shock: Port strike" in c["content"]]
    assert len(shock_prompts) == sum(len(f) for f in fired)
    # path 0's agents saw the shock only if path 0 drew it
    history = _read_jsonl(os.path.join(tmp_path, "world_state_history.jsonl"))
    assert [bool(h["deterministic"]["shocks_fired"]) for h in history] == [r in fired[0] for r in (1, 2, 3)]
