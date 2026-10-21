"""Production coordinator/round-loop context controls with scripted model/platform I/O.

Run only through main_offline_pytest.py in a private source mirror. The real
round loop, prompt builders, parser, world kernel and artifact writers stay real.
"""

import asyncio
import copy
import json

import pytest

from test_world_model_loop import (
    _WorldLLM, _patch_world, _read_jsonl, _run, _world_config, rps,
)


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("resume", [False, True], ids=["fresh", "changed-config-resume"])
def test_new_config_cannot_consume_old_committed_world(tmp_path, monkeypatch, resume):
    envs = []
    _patch_world(monkeypatch, str(tmp_path), envs)
    original = _world_config()
    _run(original, str(tmp_path))
    assert len([c for c in _WorldLLM.calls if c["kind"] == "decision" and c["round"] == 1]) > 0
    prior_calls = len(_WorldLLM.calls)
    changed = copy.deepcopy(original)
    changed["world_model"]["state_variables"][0]["value"] = 7
    changed["world_model"]["question"] = "NEW_QUESTION_SENTINEL"
    _run(changed, str(tmp_path), resume=resume)
    fresh_decisions = [c for c in _WorldLLM.calls[prior_calls:] if c["kind"] == "decision"]
    assert fresh_decisions, "a fresh/config-invalidated platform run reused the old completed world"
    assert any(c["round"] == 1 and "Tariff rate: 7%" in c["content"] for c in fresh_decisions)
    state = _json(tmp_path / "world_state.json")
    assert state["world"]["question"] == "NEW_QUESTION_SENTINEL"
    assert [r["round"] for r in _read_jsonl(tmp_path / "world_state_history.jsonl")] == [1, 2, 3]


def test_stale_final_trajectory_cannot_roll_back_newer_world_checkpoint(tmp_path, monkeypatch):
    envs = []
    _patch_world(monkeypatch, str(tmp_path), envs)
    config = _world_config()
    _run(config, str(tmp_path))
    committed = _json(tmp_path / "world_state.json")
    trajectory = _json(tmp_path / "world_state_trajectory.json")
    trajectory["trajectory"] = trajectory["trajectory"][:2]
    trajectory["n_rounds"] = 1
    trajectory["decisions"] = [r for r in trajectory["decisions"] if r["round"] <= 1]
    (tmp_path / "world_state_trajectory.json").write_text(json.dumps(trajectory), encoding="utf-8")
    coordinator = rps._ReflexiveWorldCoordinator(config, str(tmp_path), 1, lambda _: None)
    asyncio.run(coordinator.finalize())
    restored = _json(tmp_path / "world_state.json")
    assert restored["world"]["scenario_shares"] == committed["world"]["scenario_shares"], (
        "an older finalization-only trajectory overwrote newer per-round committed shares")
    assert coordinator._prev_date == committed["world"]["period"]["period_end"]


def test_public_reactions_reach_next_decision_without_private_payload(tmp_path, monkeypatch):
    envs = []
    _patch_world(monkeypatch, str(tmp_path), envs)
    config = _world_config()
    coordinator = rps._ReflexiveWorldCoordinator(config, str(tmp_path), 1, lambda _: None)
    periods = config["temporal_config"]["round_dates"]

    async def drive():
        await coordinator.begin_round("twitter", 0, periods[0])
        await coordinator.decide("twitter", 0, periods[0], [0], lambda aid: "ROLE_ACCESS_SENTINEL", [])
        await coordinator.deliver("twitter", 0, periods[0], [
            {"agent_id": 1, "agent_name": "SPOOFED_ACTOR", "action_type": "CREATE_COMMENT",
             "action_args": {"content": "PUBLIC_REACTION_SENTINEL: capacity will be contested.",
                             "private_rationale": "DENIED_PRIVATE_SENTINEL", "shares": {"A": 0.987654}}},
            {"agent_id": 1, "action_type": "SEND_PRIVATE_MESSAGE",
             "action_args": {"content": "DENIED_MESSAGE_SENTINEL"}},
        ], [])
        await coordinator.begin_round("twitter", 1, periods[1])
        await coordinator.decide("twitter", 1, periods[1], [0], lambda aid: "ROLE_ACCESS_SENTINEL", [])
        await coordinator.finalize()

    asyncio.run(drive())
    prompt = [c for c in _WorldLLM.calls if c["kind"] == "decision" and c["round"] == 2][0]
    assert "PUBLIC_REACTION_SENTINEL" in prompt["content"], "delivered public reactions vanished before the next decision"
    assert "Actor1" in prompt["content"] and "SPOOFED_ACTOR" not in prompt["content"]
    assert "DENIED_PRIVATE_SENTINEL" not in prompt["content"]
    assert "DENIED_MESSAGE_SENTINEL" not in prompt["content"] and "0.987654" not in prompt["content"]
    assert prompt["system"] == "ROLE_ACCESS_SENTINEL"


@pytest.mark.parametrize("interrupted", [False, True], ids=["continuous", "restart"])
def test_own_decision_memory_reaches_the_next_structured_prompt(tmp_path, monkeypatch, interrupted):
    envs = []
    _patch_world(monkeypatch, str(tmp_path), envs)
    config = _world_config()
    if interrupted:
        original_commit = rps._ReflexiveWorldCoordinator._commit_round
        stop = asyncio.Event()

        async def commit_then_stop(self, round_num, buf):
            await original_commit(self, round_num, buf)
            if round_num == 0:
                stop.set()

        monkeypatch.setattr(rps._ReflexiveWorldCoordinator, "_commit_round", commit_then_stop)
        monkeypatch.setattr(rps, "_shutdown_event", stop)
        _run(config, str(tmp_path))
        monkeypatch.setattr(rps._ReflexiveWorldCoordinator, "_commit_round", original_commit)
        monkeypatch.setattr(rps, "_shutdown_event", None)
        _run(config, str(tmp_path), resume=True)
    else:
        _run(config, str(tmp_path))
    actor0 = next(c for c in _WorldLLM.calls if c["kind"] == "decision" and c["round"] == 2 and c["actor"] == "Actor0")
    assert "Your private reasoning: protect domestic producers" in actor0["content"], (
        "the structured decision bypassed the private move memory its own publisher recorded")
    for call in _WorldLLM.calls:
        if call["kind"] == "decision" and call["actor"] != "Actor0":
            assert "protect domestic producers" not in call["content"]
        elif call["kind"] == "arbiter":
            assert "protect domestic producers" not in call["content"]


def test_restart_restores_convergence_evidence_not_just_shares(tmp_path, monkeypatch):
    envs = []
    _patch_world(monkeypatch, str(tmp_path), envs)
    config = _world_config()
    _run(config, str(tmp_path))
    before = _json(tmp_path / "world_state_trajectory.json")["outcome"]
    coordinator = rps._ReflexiveWorldCoordinator(config, str(tmp_path), 1, lambda _: None)
    after = coordinator._ws.outcome()
    assert after["shares"] == before["shares"]
    assert after["round_accounting"] == before["round_accounting"]
    assert after["ewma_delta"] == before["ewma_delta"], "restart reset the persisted convergence history"


@pytest.mark.parametrize("foreign_field,foreign_value", [("simulation_id", "other-simulation"), ("config_hash", "0" * 64)])
def test_saved_world_identity_mismatch_stops_before_model_dispatch(tmp_path, monkeypatch, foreign_field, foreign_value):
    envs = []
    _patch_world(monkeypatch, str(tmp_path), envs)
    config = _world_config()
    _run(config, str(tmp_path))
    state = _json(tmp_path / "world_state.json")
    state[foreign_field] = foreign_value
    (tmp_path / "world_state.json").write_text(json.dumps(state), encoding="utf-8")
    previous_calls = len(_WorldLLM.calls)
    with pytest.raises(rps.WorldContextMismatch):
        rps._get_world_coordinator(config, str(tmp_path), 1, lambda _: None)
    assert len(_WorldLLM.calls) == previous_calls
    assert _json(tmp_path / "world_state.json")[foreign_field] == foreign_value


def test_public_observation_survives_checkpoint_reload_and_is_bounded(tmp_path, monkeypatch):
    envs = []
    _patch_world(monkeypatch, str(tmp_path), envs)
    config = _world_config()
    periods = config["temporal_config"]["round_dates"]
    first = rps._ReflexiveWorldCoordinator(config, str(tmp_path), 1, lambda _: None)

    async def commit():
        await first.begin_round("twitter", 0, periods[0])
        await first.decide("twitter", 0, periods[0], [0], lambda _: "ACTOR0_SYSTEM", [])
        await first.deliver("twitter", 0, periods[0], [
            {"agent_id": 1, "action_type": "CREATE_COMMENT", "action_args": {"content": f"OBSERVATION_{i}: " + "x" * 400}}
            for i in range(15)
        ], [])

    asyncio.run(commit())
    state = _json(tmp_path / "world_state.json")
    assert "[3 further public observations omitted]" in state["public_discourse"]
    assert "[truncated]" in state["public_discourse"] and len(state["public_discourse"]) < 4000
    assert "protect domestic producers" not in json.dumps(state)
    restored = rps._ReflexiveWorldCoordinator(config, str(tmp_path), 1, lambda _: None)

    async def decide():
        await restored.begin_round("twitter", 1, periods[1])
        await restored.decide("twitter", 1, periods[1], [0, 1], lambda aid: f"ACTOR{aid}_SYSTEM", [])

    asyncio.run(decide())
    second = [c for c in _WorldLLM.calls if c["kind"] == "decision" and c["round"] == 2]
    assert second and all("OBSERVATION_0:" in c["content"] for c in second)
    assert all("OBSERVATION_14:" not in c["content"] for c in second)
    assert all("OBSERVATION_0:" not in c["content"] for c in _WorldLLM.calls if c["kind"] == "decision" and c["round"] == 1)


def test_canonical_pack_role_seed_reaches_only_the_correct_actor_prompt(tmp_path, monkeypatch):
    from app.services.actor_context import build_actor_context_pack
    from app.services.actor_role_prompt import build_actor_role_contract, compile_actor_role_prompt
    from app.services.world_model_seed import build_world_model_seed
    from test_actor_context_runtime import REPORT, _dossier

    envs = []
    _patch_world(monkeypatch, str(tmp_path), envs)
    dossier = _dossier()
    alpha = dossier["actors"][0]
    denied = copy.deepcopy(alpha["intelligence"]["dimensions"]["future_plans"][0])
    denied["claim"] = "Alpha Systems will implement DENIED_PLAN_SENTINEL."
    denied["qualifiers"]["actor_knows"] = False
    alpha["intelligence"]["dimensions"]["future_plans"].append(denied)
    # A canonical actor's flat legacy field cannot bypass the typed pack.
    alpha["future_plans"] = ["FLAT_LEGACY_SENTINEL"]
    packs = {actor["actor_id"]: build_actor_context_pack(dossier, actor, REPORT) for actor in dossier["actors"]}
    systems = {i: compile_actor_role_prompt(build_actor_role_contract(actor, dossier, packs[actor["actor_id"]]))
               for i, actor in enumerate(dossier["actors"])}
    config = _world_config()
    config["agent_configs"] = [
        {"agent_id": i, "entity_name": actor["name"], "entity_type": "Organization", "cadence": "principal"}
        for i, actor in enumerate(dossier["actors"])
    ]
    config["world_model"] = build_world_model_seed(dossier, config["agent_configs"], actor_context_packs=packs,
                                                   question="Will permit deployment proceed?",
                                                   temporal_timeline=config["temporal_config"])
    coordinator = rps._ReflexiveWorldCoordinator(config, str(tmp_path), 1, lambda _: None)
    period = config["temporal_config"]["round_dates"][0]

    async def drive():
        await coordinator.begin_round("twitter", 0, period)
        await coordinator.decide("twitter", 0, period, [0, 1], systems.__getitem__, [])

    asyncio.run(drive())
    calls = [c for c in _WorldLLM.calls if c["kind"] == "decision"]
    assert len(calls) == 2
    alpha_call = next(c for c in calls if c["actor"] == "Alpha Systems")
    beta_call = next(c for c in calls if c["actor"] == "Beta Union")
    assert "Project Aurora" in alpha_call["system"] and "Project Aurora" in alpha_call["content"]
    assert "Fair Grid" in beta_call["system"] and "Project Aurora" not in beta_call["system"]
    assert "Project Aurora" not in beta_call["content"]
    for call in calls:
        assert "DENIED_PLAN_SENTINEL" not in call["system"] + call["content"]
        assert "FLAT_LEGACY_SENTINEL" not in call["system"] + call["content"]
    assert "Alpha Systems seeks durable institutional influence" not in alpha_call["content"]


def test_real_committed_artifacts_feed_summary_and_report_projection(tmp_path, monkeypatch):
    from app.config import Config
    from app.services.simulation_runner import SimulationRunner
    from test_world_model_downstream import _bare_report_agent

    config = _world_config()
    sim_dir = tmp_path / config["simulation_id"]
    envs = []
    _patch_world(monkeypatch, str(sim_dir), envs)
    (sim_dir / "simulation_config.json").write_text(json.dumps(config), encoding="utf-8")
    _run(config, str(sim_dir))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationRunner, "_run_states", {})
    summary = SimulationRunner.write_run_summary(config["simulation_id"])
    assert summary["world_model"]["committed_round"] == 3
    assert summary["world_model"]["arbiter_failed_rounds"] == 0
    block = _bare_report_agent(config["simulation_id"])._world_evolution_block()
    assert "elicited model projection" in block and "Tariff rate: 10%" in block
    assert "25%" in block and "2026-Q3" in block and "Actor0" in block
    assert "protect domestic producers" not in block
    assert "0.797478" not in block  # numeric scenario shares are not world-fact evidence


def test_dynamics_note_survives_actual_camel_context_selection():
    from camel.memories import ChatHistoryMemory, MemoryRecord, ScoreBasedContextCreator
    from camel.messages import BaseMessage
    from camel.types import OpenAIBackendRole
    from app.services.agent_dynamics import AgentDynamicsTracker

    class CharacterCounter:
        def count_tokens_from_messages(self, messages):
            return sum(len(str(m.get("content", ""))) for m in messages)

    # The installed memory and context selector remain real. Only token costing
    # is deterministic, avoiding any provider tokenizer/vocabulary download.
    memory = ChatHistoryMemory(ScoreBasedContextCreator(CharacterCounter(), token_limit=10_000))
    memory.write_records([
        MemoryRecord(message=BaseMessage.make_user_message(role_name="Actor0", content="SEALED_ROLE_SENTINEL"),
                     role_at_backend=OpenAIBackendRole.SYSTEM),
        MemoryRecord(message=BaseMessage.make_user_message(role_name="Actor0", content="PRIOR_MEMORY_SENTINEL"),
                     role_at_backend=OpenAIBackendRole.USER),
    ])

    class MemoryAgent:
        def update_memory(self, message, role):
            memory.write_records([MemoryRecord(message=message, role_at_backend=role)])

    tracker = AgentDynamicsTracker([0], initial={0: {"sentiment_bias": -0.7}})
    expected = tracker.state_line(0)
    rps._inject_agent_dynamics([(0, MemoryAgent())], tracker, lambda _: None)
    messages, _tokens = memory.get_context()
    assert any(expected == m.get("content") for m in messages), "CAMEL dropped the appended SYSTEM dynamics note"
    assert any(m.get("content") == "SEALED_ROLE_SENTINEL" and m["role"] == "system" for m in messages)
    assert any(m.get("content") == "PRIOR_MEMORY_SENTINEL" for m in messages)


def test_future_dated_research_fact_cannot_enter_initial_actor_context(tmp_path, monkeypatch):
    from app.services.world_model_seed import build_world_model_seed

    envs = []
    _patch_world(monkeypatch, str(tmp_path), envs)
    config = _world_config()
    actors = {"as_of_date": "2026-07-11", "actors": [], "quantitative_facts": [
        {"metric": "Current observed capacity", "value": 7, "unit": "GW", "as_of_date": "2026-07-10"},
        {"metric": "FUTURE_FACT_SENTINEL", "value": 999, "unit": "GW", "as_of_date": "2026-09-01", "value_type": "actual"},
    ]}
    config["world_model"] = build_world_model_seed(actors, config["agent_configs"], temporal_timeline=config["temporal_config"])
    coordinator = rps._ReflexiveWorldCoordinator(config, str(tmp_path), 1, lambda _: None)
    period = config["temporal_config"]["round_dates"][0]

    async def drive():
        await coordinator.begin_round("twitter", 0, period)
        await coordinator.decide("twitter", 0, period, [0], lambda _: "SEALED_ROLE_SENTINEL", [])

    asyncio.run(drive())
    call = next(c for c in _WorldLLM.calls if c["kind"] == "decision")
    assert "Current observed capacity: 7 GW" in call["content"]
    assert "FUTURE_FACT_SENTINEL" not in call["content"], "the seed admitted a fact dated after the research cutoff"


async def _both_platforms(config, sim_dir):
    from action_logger import PlatformActionLogger
    return await asyncio.gather(
        rps.run_twitter_simulation(config, str(sim_dir), action_logger=PlatformActionLogger("twitter", str(sim_dir)),
                                   semaphore_platforms=2),
        rps.run_reddit_simulation(config, str(sim_dir), action_logger=PlatformActionLogger("reddit", str(sim_dir)),
                                  semaphore_platforms=2),
    )


@pytest.mark.parametrize("first", ["twitter", "reddit"], ids=["resuming-first", "missing-first"])
@pytest.mark.parametrize("invalid", ["missing", "config-mismatch"])
def test_mixed_platform_resume_rejected_before_either_start_order_mutates_state(tmp_path, monkeypatch, first, invalid):
    import hashlib
    from test_world_model_loop import _patch_reddit

    envs = []
    _patch_world(monkeypatch, str(tmp_path), envs)
    _patch_reddit(monkeypatch, str(tmp_path))
    config = _world_config()
    asyncio.run(_both_platforms(config, tmp_path))
    monkeypatch.setenv("SIM_WORLD_BARRIER_TIMEOUT_S", "0.001")
    bad = tmp_path / "reddit/checkpoint.json"
    if invalid == "missing":
        bad.unlink()
    else:
        checkpoint = _json(bad)
        checkpoint["config_hash"] = "foreign-config-fingerprint"
        bad.write_text(json.dumps(checkpoint), encoding="utf-8")
    protected = [tmp_path / "world_state.json", tmp_path / "world_state_history.jsonl",
                 tmp_path / "world_actions.jsonl", tmp_path / "world_state_trajectory.json",
                 tmp_path / "twitter_simulation.db", tmp_path / "reddit_simulation.db",
                 tmp_path / "twitter/checkpoint.json"]
    if bad.exists():
        protected.append(bad)
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    old_calls = len(_WorldLLM.calls)
    run = rps.run_twitter_simulation if first == "twitter" else rps.run_reddit_simulation
    with pytest.raises(rps.WorldContextMismatch, match="mixed"):
        asyncio.run(run(config, str(tmp_path), semaphore_platforms=2, resume=True))
    assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    assert len(_WorldLLM.calls) == old_calls


def test_two_platform_full_resume_keeps_committed_world_and_skips_new_decisions(tmp_path, monkeypatch):
    from test_world_model_loop import _patch_reddit

    envs = []
    _patch_world(monkeypatch, str(tmp_path), envs)
    _patch_reddit(monkeypatch, str(tmp_path))
    config = _world_config()
    asyncio.run(_both_platforms(config, tmp_path))
    before = _json(tmp_path / "world_state.json")
    old_calls = len(_WorldLLM.calls)

    async def resume():
        await asyncio.gather(
            rps.run_twitter_simulation(config, str(tmp_path), semaphore_platforms=2, resume=True),
            rps.run_reddit_simulation(config, str(tmp_path), semaphore_platforms=2, resume=True),
        )

    asyncio.run(resume())
    after = _json(tmp_path / "world_state.json")
    assert after["world"]["variables"] == before["world"]["variables"]
    assert after["world"]["scenario_shares"] == before["world"]["scenario_shares"]
    assert after["committed_round"] == 3 and len(_WorldLLM.calls) == old_calls


def test_question_language_and_world_clock_reach_actual_decision_calls(tmp_path, monkeypatch):
    envs = []
    _patch_world(monkeypatch, str(tmp_path), envs)
    config = _world_config()
    config["output_language"] = "English"
    config["world_brief"] = "FORECAST_QUESTION_SENTINEL: will the permit clear by 2027-03-31? Cutoff 2026-07-11."
    _run(config, str(tmp_path))
    calls = [c for c in _WorldLLM.calls if c["kind"] == "decision"]
    assert calls and all("FORECAST_QUESTION_SENTINEL" in c["system"] for c in calls)
    for call in calls:
        assert "Write public_statement in English." in call["content"]
        assert "forecast horizon 2027-03-31" in call["content"]
        assert f"round {call['round']}/3" in call["content"]
        assert "Candidate scenarios: A; B" in call["content"]
    round2 = next(c for c in calls if c["round"] == 2)
    assert "# WORLD CLOCK — 2026-Q4 (2026-10-01 → 2026-12-31)" in round2["content"]


def test_expectation_and_response_comparison_reaches_only_its_actor_prompt(tmp_path, monkeypatch):
    envs = []
    _patch_world(monkeypatch, str(tmp_path), envs)
    config = _world_config()
    # This case compares a recorded hold with an earlier expectation. Activity
    # 1 still leaves sampled actors subject to the cap, so admit Actor1 every
    # period through the real principal cadence (Actor0 is already principal).
    config["agent_configs"][1]["cadence"] = "principal"

    class ExpectationLLM(_WorldLLM):
        def chat_json(self, messages, **kwargs):
            result = super().chat_json(messages, **kwargs)
            text = messages[-1]["content"]
            if "# DECIDE YOUR MOVE FOR THIS PERIOD — Actor0\n" in text and self._round_of(text) == 1:
                result["expected_reactions"] = [{"actor": "Actor1", "reaction": "EXPECTATION_SENTINEL_seek_talks"}]
            return result

    monkeypatch.setattr("app.utils.llm_client.LLMClient", ExpectationLLM)
    _run(config, str(tmp_path))
    actor1_round2 = [row for row in _read_jsonl(tmp_path / "world_actions.jsonl")
                     if row["agent_id"] == 1 and row["round"] == 2]
    assert len(actor1_round2) == 1
    assert actor1_round2[0]["option"]["id"] == "hold_position"
    actor0_round3 = next(c for c in _WorldLLM.calls if c["kind"] == "decision" and c["actor"] == "Actor0" and c["round"] == 3)
    assert 'you expected "EXPECTATION_SENTINEL_seek_talks"' in actor0_round3["content"]
    assert "Actor1 holds position" in actor0_round3["content"]
    for call in _WorldLLM.calls:
        if call["kind"] == "decision" and call["actor"] != "Actor0":
            assert "EXPECTATION_SENTINEL_seek_talks" not in call["content"]
