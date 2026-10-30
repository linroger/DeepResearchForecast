"""Real coordinator/decision/kernel consumers; only the model is scripted offline."""
import asyncio
import copy
import hashlib
import json
import re
from pathlib import Path
import sys

import pytest

from test_world_model_loop import _WorldLLM, _patch_world, _world_config, rps
from app.services import research_preparation as prep
from app.services import world_paths as paths
from app.services.world_update import replay_world_round
from app.services.agent_decision import DECISION_SYSTEM_PROMPT


@pytest.fixture(autouse=True)
def source_receipt():
    guard = sys.modules.get("main_offline_guard")
    if guard:
        root = Path(__file__).resolve().parents[2]
        for name in ("backend/scripts/run_parallel_simulation.py", "backend/app/services/world_paths.py",
                     "backend/app/services/research_preparation.py", "backend/app/services/world_update.py",
                     "backend/app/services/agent_decision.py", "backend/app/services/world_model.py"):
            path = root / name
            guard.source_hashes.setdefault(str(path), hashlib.sha256(path.read_bytes()).hexdigest())


def adaptive_config(**overrides):
    cfg = _world_config()
    cfg["world_model"]["settings"].update(branch_policy="adaptive-v1", path_count=2, path_seed=19,
        branch_decision_budget=12, branch_max_actors=2, branch_max_rounds=3)
    cfg["world_model"]["settings"].update(overrides)
    return cfg


class BranchLLM(_WorldLLM):
    def chat_json(self, messages, temperature=0.3, max_tokens=4096, **kwargs):
        content = messages[-1]["content"]
        raw = super().chat_json(messages, temperature, max_tokens, **kwargs)
        if "# DECIDE YOUR MOVE FOR THIS PERIOD" in content:
            tariff = re.search(r"Tariff rate: ([0-9.]+)%", content)
            local = bool(tariff and float(tariff.group(1)) < 10)
            return {"option_id": "hold_position", "public_statement": "LOCAL_LOW" if local else "PRIMARY_HIGH",
                    "private_rationale": "PRIVATE_LOW" if local else "PRIVATE_HIGH",
                    "scenario_commitment": {"scenario": "B" if local else "A", "confidence": 0.9}}
        if content.startswith("You are the consequence arbiter"):
            return {"narrative": "Changed tariff.", "variable_changes": [
                {"variable_id": "tariff_rate", "new_value": 7 if temperature > 0.3 else 25,
                 "rationale": "scripted controlled difference"}], "scenario_pressure": {}}
        return raw


def coordinator(tmp_path, monkeypatch, cfg=None):
    _patch_world(monkeypatch, str(tmp_path), [])
    monkeypatch.setattr("app.utils.llm_client.LLMClient", BranchLLM)
    return rps._ReflexiveWorldCoordinator(cfg or adaptive_config(), str(tmp_path), 1, lambda _: None)


async def step(coord, round_num, *, lookup=None, actions=None):
    period = coord._period_for(round_num)
    await coord.decide("twitter", round_num, period, [0, 1],
                       lookup or (lambda aid: "BEGIN UNTRUSTED DOSSIER DATA\n"
                                  f"STATIC_PERSONA_{aid}\nEND UNTRUSTED DOSSIER DATA"), [])
    await coord._commit_round(round_num, {"period": period, "events": [], "actions": actions or []})


def read(path):
    return json.loads(path.read_text())


@pytest.mark.parametrize("key,value", [("branch_decision_budget", 0), ("branch_decision_budget", True),
    ("branch_decision_budget", float("inf")), ("branch_max_actors", 0), ("branch_max_rounds", -1),
    ("path_count", 1), ("path_count", 9), ("path_seed", None), ("path_temperature", float("nan"))])
def test_invalid_adaptive_envelope_fails_closed(tmp_path, monkeypatch, key, value):
    cfg = adaptive_config()
    cfg["world_model"]["settings"][key] = value
    with pytest.raises((rps.WorldContextMismatch, ValueError)):
        coordinator(tmp_path, monkeypatch, cfg)


def test_default_policy_and_no_environment_activation(monkeypatch):
    monkeypatch.setenv("SIM_WORLD_BRANCH_POLICY", "adaptive-v1")
    assert paths.resolve_branch_policy({}) == {"branch_policy": "shared-v1"}


def test_branch_local_decisions_late_personas_discourse_shares_and_replay(tmp_path, monkeypatch):
    coord = coordinator(tmp_path, monkeypatch)
    async def run():
        await step(coord, 0, actions=[{"agent_id": 0, "action_type": "CREATE_POST",
                                     "action_args": {"content": "PATH0_ORGANIC_SECRET"}}])
        await step(coord, 1, lookup=lambda aid: f"PATH0_EVOLVING_PERSONA_{aid}")
        await step(coord, 2, lookup=lambda aid: f"PATH0_EVOLVING_PERSONA_{aid}")
    asyncio.run(run())
    saved = read(tmp_path / "world_paths.json")
    branch = saved["paths"][0]
    assert saved["decision_attempts_used"] == 6
    assert [d["agent_id"] for d in branch["records"][1]["actor_decisions"]] == [2, 3]
    calls = [c for c in _WorldLLM.calls if c["kind"] == "decision"]
    later = [c for c in calls if c["round"] == 2 and c["actor"] in ("Actor2", "Actor3")]
    assert len(later) == 2
    assert all(
        "PATH0_ORGANIC_SECRET" not in c["system"] + c["content"]
        and "PATH0_EVOLVING" not in c["system"] + c["content"]
        for c in later
    )
    assert all(c["system"].startswith(DECISION_SYSTEM_PROMPT) for c in later)
    assert all(f"STATIC_PERSONA_{2 if c['actor'] == 'Actor2' else 3}" in c["content"] for c in later)
    third = [c for c in calls if c["round"] == 3 and "STATIC_PERSONA_0" in c["content"]][0]
    assert "LOCAL_LOW" in third["content"]
    assert "PATH0_ORGANIC_SECRET" not in third["system"] + third["content"]
    assert branch["shares"]["B"] > coord._ws.shares["B"]
    assert all(d["scenario"] == "B" for d in branch["records"][1]["actor_decisions"])
    history = [json.loads(line) for line in (tmp_path / "world_state_history.jsonl").read_text().splitlines()]
    for record in history + branch["records"]:
        assert record["replay"]["schema_version"] == "world-replay/v1"
        replay_world_round(record["replay"])
    assert "not calibrated" in coord._paths_summary(0)["basis"]


def test_budget_reserved_then_restored_and_environment_cannot_expand_it(tmp_path, monkeypatch):
    cfg = adaptive_config()
    cfg["world_model"]["settings"]["branch_decision_budget"] = 3
    coord = coordinator(tmp_path, monkeypatch, cfg)
    asyncio.run(step(coord, 0))
    assert read(tmp_path / "world_paths.json")["decision_attempts_used"] == 2
    monkeypatch.setenv("SIM_WORLD_PATHS", "inf")
    monkeypatch.setenv("SIM_SEED", "999")
    monkeypatch.setenv("SIM_WORLD_PATH_TEMPERATURE", "0.01")
    resumed = coordinator(tmp_path, monkeypatch, cfg)
    assert resumed._k == 2 and resumed._seed_value == 19 and resumed._path_temperature == 0.7
    assert resumed._branch_used == 2
    async def run():
        await step(resumed, 1, lookup=lambda aid: "PATH0_EVOLVING")
        await step(resumed, 2)
    asyncio.run(run())
    saved = read(tmp_path / "world_paths.json")
    assert saved["decision_attempts_used"] == 3
    assert saved["paths"][0]["stop_reason"] == "decision_budget_exhausted"
    assert [len(r["actor_decisions"]) for r in saved["paths"][0]["records"]] == [2, 1]
    assert saved["personas"]["2"] == "BEGIN UNTRUSTED DOSSIER DATA\nSTATIC_PERSONA_2\nEND UNTRUSTED DOSSIER DATA"


def test_private_prior_decision_and_discourse_survive_restart_locally(tmp_path, monkeypatch):
    cfg = adaptive_config(branch_max_actors=4)
    coord = coordinator(tmp_path, monkeypatch, cfg)
    async def first():
        await step(coord, 0)
        await step(coord, 1)
    asyncio.run(first())
    resumed = coordinator(tmp_path, monkeypatch, cfg)
    asyncio.run(step(resumed, 2, lookup=lambda aid: "PRIMARY_EVOLVING_SYSTEM"))
    branch_calls = [c for c in _WorldLLM.calls if c["kind"] == "decision" and "STATIC_PERSONA_" in c["content"]]
    assert len(branch_calls) == 4
    for call in branch_calls:
        assert "Your private reasoning: PRIVATE_LOW" in call["content"]
        assert "Your private reasoning: PRIVATE_HIGH" not in call["content"]
        assert "LOCAL_LOW" in call["content"]


def test_budget_is_global_across_siblings_and_failed_calls_count(tmp_path, monkeypatch):
    cfg = adaptive_config(path_count=3, branch_decision_budget=3)
    coord = coordinator(tmp_path, monkeypatch, cfg)
    original = coord._llm.chat_json
    def failing(messages, **kwargs):
        if "STATIC_PERSONA_" in messages[-1].get("content", "") and coord._branch_inflight:
            raise RuntimeError("scripted branch model unavailable")
        return original(messages, **kwargs)
    monkeypatch.setattr(coord._llm, "chat_json", failing)
    async def run():
        await step(coord, 0)
        await step(coord, 1)
    asyncio.run(run())
    saved = read(tmp_path / "world_paths.json")
    assert saved["decision_attempts_used"] == 3
    assert [len(p["records"][0]["actor_decisions"]) for p in saved["paths"]] == [2, 1]
    assert all(p["stop_reason"] == "decision_budget_exhausted" for p in saved["paths"])
    assert all(d["status"] == "failed" for p in saved["paths"] for d in p["records"][0]["actor_decisions"])


def test_failed_reservation_write_prevents_branch_calls(tmp_path, monkeypatch):
    coord = coordinator(tmp_path, monkeypatch)
    def fail():
        raise OSError("reservation write failed")
    monkeypatch.setattr(coord, "_write_paths", fail)
    with pytest.raises(OSError, match="reservation write"):
        asyncio.run(step(coord, 0))
    assert len([c for c in _WorldLLM.calls if c["kind"] == "decision"]) == 2
    with pytest.raises(rps.WorldContextMismatch, match="already reserved"):
        asyncio.run(coord._prepare_branch_decisions(1, coord._period_for(0), []))


def test_max_rounds_freezes_branch_without_extra_calls(tmp_path, monkeypatch):
    cfg = adaptive_config()
    cfg["world_model"]["settings"]["branch_max_rounds"] = 1
    coord = coordinator(tmp_path, monkeypatch, cfg)
    async def run():
        await step(coord, 0)
        before = copy.deepcopy(coord._paths[0]["world"].to_dict())
        await step(coord, 1)
        assert coord._paths[0]["world"].to_dict() == before
    asyncio.run(run())
    assert coord._branch_used == 2 and coord._paths[0]["stop_reason"] == "max_rounds"


@pytest.mark.parametrize("damage", ["missing", "wrong_round", "wrong_policy", "budget", "inflight", "records", "personas", "hash"])
def test_adaptive_resume_never_silently_rebuilds_or_refunds(tmp_path, monkeypatch, damage):
    cfg = adaptive_config()
    coord = coordinator(tmp_path, monkeypatch, cfg)
    asyncio.run(step(coord, 0))
    path = tmp_path / "world_paths.json"
    saved = read(path)
    if damage == "missing":
        path.unlink()
    else:
        if damage == "wrong_round": saved["committed_round"] = 0
        elif damage == "wrong_policy": saved["branch_settings"]["branch_decision_budget"] = 100
        elif damage == "budget": saved["decision_attempts_used"] = 0
        elif damage == "inflight": saved["inflight_round"] = {"round": 2}
        elif damage == "records": saved["paths"][0]["records"] = []
        elif damage == "personas": saved["personas"] = {}
        elif damage == "hash": saved["content_sha256"] = "0" * 64
        if damage != "hash":
            # Reach structural/accounting checks, not just the outer hash guard.
            from app.services.actor_context import canonical_json_sha256
            saved["content_sha256"] = canonical_json_sha256({k: v for k, v in saved.items() if k != "content_sha256"})
        path.write_text(json.dumps(saved))
    with pytest.raises(rps.WorldContextMismatch):
        coordinator(tmp_path, monkeypatch, cfg)


def test_reservation_precedes_call_and_interruption_cannot_refund(tmp_path, monkeypatch):
    cfg = adaptive_config()
    coord = coordinator(tmp_path, monkeypatch, cfg)
    original = coord._run_decisions
    async def interrupt(*args, **kwargs):
        if kwargs.get("path") is not None:
            saved = read(tmp_path / "world_paths.json")
            assert saved["decision_attempts_used"] == 2 and saved["inflight_round"]["round"] == 1
            raise RuntimeError("simulated process interruption")
        return await original(*args, **kwargs)
    monkeypatch.setattr(coord, "_run_decisions", interrupt)
    with pytest.raises(RuntimeError, match="interruption"):
        asyncio.run(step(coord, 0))
    with pytest.raises(rps.WorldContextMismatch):
        coordinator(tmp_path, monkeypatch, cfg)
    with pytest.raises(rps.WorldContextMismatch, match="cannot reset"):
        rps._get_world_coordinator(cfg, str(tmp_path), 1, lambda _: None, resume=False)


def preparation(tmp_path, cfg):
    from app.services.actor_context import canonical_json_sha256
    actors = {"actors": [{"actor_id": f"actor_{i}", "name": f"Actor{i}"} for i in range(4)]}
    actors["quantitative_facts"] = [{"metric": "Installed capacity", "entity": "Public grid",
        "series": "PUBLIC_CAPACITY_SERIES", "value": 120, "unit": "MW", "value_type": "actual",
        "as_of_date": "2026-07-01", "period_end": "2026-06-30", "visibility": "public",
        "source_refs": ["PLANT_SOURCE_PUBLIC"], "source": "Public grid report"}]
    bundle = prep.compile_preparation_context(question="Question", research_report="Report", actors=actors,
                                               as_of="2026-07-11")
    # Audience projections emulate the already tested compiler's admitted output;
    # persistence, validation, renderers and every runtime consumer remain real.
    bundle["qualitative"]["public"] = [{"claim": "PUBLIC_RESEARCH_ROW", "visibility": "public"}]
    bundle["qualitative"]["modeler"] = [{"claim": "MODELER_ONLY_ROW", "visibility": "research_only"}]
    for i in range(4):
        bundle["qualitative"]["actors"][f"actor_{i}"] = [
            {"claim": f"OWNER_ONLY_{i}", "actor_id": f"actor_{i}", "visibility": "actor_known"}]
        cfg["agent_configs"][i]["actor_id"] = f"actor_{i}"
    bundle["content_sha256"] = canonical_json_sha256({k: v for k, v in bundle.items() if k != "content_sha256"})
    prep.write_preparation_context(tmp_path, bundle)
    cfg["research_preparation"] = {k: bundle[k] for k in ("schema_version", "content_sha256", "source")}
    return bundle


def test_research_is_loaded_once_and_consumed_in_actual_prompts(tmp_path, monkeypatch):
    cfg = adaptive_config()
    bundle = preparation(tmp_path, cfg)
    original = prep.load_preparation_context
    loads = []
    def load(*args, **kwargs):
        loads.append(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(prep, "load_preparation_context", load)
    coord = coordinator(tmp_path, monkeypatch, cfg)
    async def run():
        await step(coord, 0)
        await step(coord, 1)
    asyncio.run(run())
    assert len(loads) == 1 and loads[0]["expected_sources"] == bundle["source"]
    for call in _WorldLLM.calls:
        if call["kind"] == "decision":
            aid = int(call["actor"][-1])
            assert "PUBLIC_RESEARCH_ROW" in call["content"] and f"OWNER_ONLY_{aid}" in call["content"]
            assert "MODELER_ONLY_ROW" not in call["content"]
            assert all(f"OWNER_ONLY_{i}" not in call["content"] for i in range(4) if i != aid)
        else:
            # Shared arbiter output enters public world facts/digests; it receives
            # only public research even though the full bundle binds replay.
            assert "PUBLIC_RESEARCH_ROW" in call["content"]
            assert "PUBLIC_CAPACITY_SERIES" in call["content"] and "PLANT_SOURCE_PUBLIC" in call["content"]
            assert '"value":120' in call["content"] and '"unit":"MW"' in call["content"]
            assert "MODELER_ONLY_ROW" not in call["content"] and "OWNER_ONLY" not in call["content"]
    records = read(tmp_path / "world_paths.json")["paths"][0]["records"]
    for record in records:
        replay_world_round(record["replay"], preparation_context=bundle)


@pytest.mark.parametrize("damage", ["missing", "tampered", "source", "mapping", "marker"])
def test_required_preparation_fails_outside_fallback_catches(tmp_path, monkeypatch, damage):
    cfg = _world_config()
    preparation(tmp_path, cfg)
    if damage == "missing": (tmp_path / prep.BUNDLE_FILE).unlink()
    elif damage == "tampered": (tmp_path / prep.BUNDLE_FILE).write_text('{}')
    elif damage == "source": cfg["research_preparation"]["source"]["report_sha256"] = "0" * 64
    elif damage == "mapping": cfg["agent_configs"][0].pop("actor_id")
    else: cfg["research_preparation"] = {}
    _patch_world(monkeypatch, str(tmp_path), [])
    with pytest.raises(rps.WorldContextMismatch):
        rps._get_world_coordinator(cfg, str(tmp_path), 1, lambda _: None)


def test_final_checkpoint_failure_latches_through_platform_delivery(tmp_path, monkeypatch):
    coord = coordinator(tmp_path, monkeypatch)
    original = coord._write_paths
    writes = []
    def fail_second(*args, **kwargs):
        writes.append(1)
        if len(writes) == 2:
            raise OSError("final branch checkpoint failed")
        return original(*args, **kwargs)
    monkeypatch.setattr(coord, "_write_paths", fail_second)
    async def run():
        period = coord._period_for(0)
        await coord.begin_round("twitter", 0, period)
        await coord.decide("twitter", 0, period, [0, 1], lambda aid: f"BEGIN UNTRUSTED DOSSIER DATA\nSTATIC_PERSONA_{aid}\nEND UNTRUSTED DOSSIER DATA", [])
        with pytest.raises(rps.WorldContextMismatch):
            await coord.deliver("twitter", 0, period, [], [])
        assert not coord._is_committed(0)
        calls = len(_WorldLLM.calls)
        for operation in (coord.begin_round("twitter", 1, coord._period_for(1)),
                          coord.decide("twitter", 1, coord._period_for(1), [0], lambda _: "role", []),
                          coord.heartbeat("twitter", 1), coord.finalize()):
            with pytest.raises(rps.WorldContextMismatch):
                await operation
        assert len(_WorldLLM.calls) == calls
        assert not coord._finalized
    asyncio.run(run())


def test_missing_paths_fresh_start_preserves_prior_artifacts(tmp_path, monkeypatch):
    cfg = adaptive_config()
    coord = coordinator(tmp_path, monkeypatch, cfg)
    asyncio.run(step(coord, 0))
    (tmp_path / "world_paths.json").unlink()
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    with pytest.raises(rps.WorldContextMismatch):
        rps._get_world_coordinator(cfg, str(tmp_path), 1, lambda _: None, resume=False)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}


@pytest.mark.parametrize("missing_bundle", [False, True])
def test_pinned_runtime_cannot_be_disabled_by_environment(tmp_path, monkeypatch, missing_bundle):
    cfg = adaptive_config()
    if missing_bundle:
        preparation(tmp_path, cfg)
        (tmp_path / prep.BUNDLE_FILE).unlink()
    _patch_world(monkeypatch, str(tmp_path), [])
    monkeypatch.setenv("SIM_WORLD_MODEL", "false")
    if missing_bundle:
        with pytest.raises(rps.WorldContextMismatch):
            rps._get_world_coordinator(cfg, str(tmp_path), 1, lambda _: None)
    else:
        assert rps._get_world_coordinator(cfg, str(tmp_path), 1, lambda _: None)._adaptive


def test_branch_capacity_resets_before_actual_next_decision_menu(tmp_path, monkeypatch):
    cfg = adaptive_config(branch_max_actors=4)
    coord = coordinator(tmp_path, monkeypatch, cfg)
    monkeypatch.setattr("app.utils.llm_client.LLMClient", _WorldLLM)
    coord._llm = _WorldLLM()
    async def run():
        await step(coord, 0)
        assert coord._paths[0]["world"].actors[0].capacity_used > 0
        await step(coord, 1, lookup=lambda _: "PRIMARY_SYSTEM")
    asyncio.run(run())
    call = next(c for c in _WorldLLM.calls if c["kind"] == "decision" and c["round"] == 2
                and c["actor"] == "Actor0" and "STATIC_PERSONA_0" in c["content"])
    assert "Capacity this period: 3/3 action units" in call["content"]
    assert coord._paths[0]["records"][1]["actor_decisions"][0]["status"] == "ok"


def test_actual_platform_loop_inactive_first_round_is_contiguous(tmp_path, monkeypatch):
    from test_world_model_loop import _run
    _patch_world(monkeypatch, str(tmp_path), [])
    monkeypatch.setattr("app.utils.llm_client.LLMClient", BranchLLM)
    original = rps.get_active_agents_for_round
    def inactive_first(env, config, simulated_hour, round_num, *args, **kwargs):
        return [] if round_num == 0 else original(env, config, simulated_hour, round_num, *args, **kwargs)
    monkeypatch.setattr(rps, "get_active_agents_for_round", inactive_first)
    # Any pre-fix barrier failure should be immediate, not a 30-minute test hang.
    monkeypatch.setenv("SIM_WORLD_BARRIER_TIMEOUT_S", "0.01")
    _run(adaptive_config(), str(tmp_path))
    saved = read(tmp_path / "world_paths.json")
    assert saved["committed_round"] == 3 and saved["decision_attempts_used"] == 6
    assert [r["round"] for r in saved["paths"][0]["records"]] == [1, 2, 3]
    assert read(tmp_path / "world_state.json")["committed_round"] == 3


def test_actual_platform_does_not_checkpoint_failed_adaptive_commit(tmp_path, monkeypatch):
    from test_world_model_loop import _run
    _patch_world(monkeypatch, str(tmp_path), [])
    original = rps._ReflexiveWorldCoordinator._write_paths
    def fail_committed(self, *args, **kwargs):
        if kwargs.get("committed"):
            raise OSError("final checkpoint unavailable")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(rps._ReflexiveWorldCoordinator, "_write_paths", fail_committed)
    with pytest.raises(rps.WorldContextMismatch):
        _run(adaptive_config(), str(tmp_path))
    assert not (tmp_path / "twitter/checkpoint.json").exists()
    assert not (tmp_path / "world_state_trajectory.json").exists()
    assert all(c["round"] == 1 for c in _WorldLLM.calls if c["kind"] == "decision")
    with pytest.raises(rps.WorldContextMismatch):
        asyncio.run(rps._finalize_world_coordinator(str(tmp_path), lambda _: None))


def test_adaptive_dual_delivery_waits_for_durable_commit(tmp_path, monkeypatch):
    coord = coordinator(tmp_path, monkeypatch)
    coord._expected = 2
    async def run():
        period = coord._period_for(0)
        await coord.begin_round("twitter", 0, period)
        await coord.decide("twitter", 0, period, [0, 1], lambda aid: f"BEGIN UNTRUSTED DOSSIER DATA\nSTATIC_PERSONA_{aid}\nEND UNTRUSTED DOSSIER DATA", [])
        first = asyncio.create_task(coord.deliver("twitter", 0, period, [], []))
        await asyncio.sleep(0)
        assert not first.done() and not coord._is_committed(0)
        await coord.deliver("reddit", 0, period, [], [])
        await first
        assert coord._is_committed(0)
        assert read(tmp_path / "world_paths.json")["inflight_round"] is None
    asyncio.run(run())


def test_invalid_platform_resume_preserves_database_before_reset(tmp_path, monkeypatch):
    from test_world_model_loop import _run
    cfg = adaptive_config()
    _patch_world(monkeypatch, str(tmp_path), [])
    _run(cfg, str(tmp_path))
    (tmp_path / "world_paths.json").unlink()
    (tmp_path / "twitter/checkpoint.json").unlink()
    db = tmp_path / "twitter_simulation.db"
    before = db.read_bytes()
    with pytest.raises(rps.WorldContextMismatch):
        _run(cfg, str(tmp_path), resume=True)
    assert db.read_bytes() == before


def test_primary_decision_journal_failure_stops_actual_platform_before_publish(tmp_path, monkeypatch):
    from test_world_model_loop import _run, _read_jsonl
    _patch_world(monkeypatch, str(tmp_path), [])
    original = rps._append_jsonl
    def fail_journal(path, row):
        if Path(path).name == "world_actions.jsonl":
            raise OSError("decision journal unavailable")
        return original(path, row)
    monkeypatch.setattr(rps, "_append_jsonl", fail_journal)
    with pytest.raises(rps.WorldContextMismatch):
        _run(adaptive_config(), str(tmp_path))
    assert not (tmp_path / "world_paths.json").exists()
    assert not (tmp_path / "twitter/checkpoint.json").exists()
    actions = _read_jsonl(tmp_path / "twitter/actions.jsonl")
    assert not any((row.get("action_args") or {}).get("is_world_decision") for row in actions)


def test_dual_main_propagates_pre_registration_admission_failure(tmp_path, monkeypatch):
    from test_world_model_loop import _run
    from app.services.actor_context import canonical_json_sha256
    cfg = adaptive_config()
    _patch_world(monkeypatch, str(tmp_path), [])
    _run(cfg, str(tmp_path))
    # Both platform checkpoints/DBs match; only the shared adaptive artifact is incomplete.
    (tmp_path / "reddit").mkdir(exist_ok=True)
    (tmp_path / "reddit/checkpoint.json").write_bytes((tmp_path / "twitter/checkpoint.json").read_bytes())
    (tmp_path / "reddit_simulation.db").write_bytes((tmp_path / "twitter_simulation.db").read_bytes())
    (tmp_path / "reddit_profiles.json").write_text('[]')
    monkeypatch.setattr(rps, "generate_reddit_agent_graph", rps.generate_twitter_agent_graph)
    saved = read(tmp_path / "world_paths.json")
    saved["inflight_round"] = {"round": 4}
    saved["content_sha256"] = canonical_json_sha256({k: v for k, v in saved.items() if k != "content_sha256"})
    (tmp_path / "world_paths.json").write_text(json.dumps(saved))
    config_path = tmp_path / "simulation_config.json"
    config_path.write_text(json.dumps(cfg))
    monkeypatch.setattr(sys, "argv", ["run_parallel_simulation", "--config", str(config_path), "--resume", "--no-wait"])
    monkeypatch.setenv("SIM_DECISION_CHANNEL", "true")
    monkeypatch.setenv("SIM_TERMINAL_ARTIFACTS_TOKEN", "offline-test-token")
    calls = []
    monkeypatch.setattr("app.services.decision_channel.run_decision_channel", lambda *a, **k: calls.append(1))
    rps._WORLD_TRAJ_WRITTEN.clear()
    with pytest.raises(rps.WorldContextMismatch, match="adaptive"):
        asyncio.run(rps.main())
    assert calls == []
    assert not (tmp_path / "simulation_artifacts_ready.json").exists()
    assert str(tmp_path) not in rps._WORLD_COORDINATORS


@pytest.mark.parametrize("mode", ["public", "unmarked", "public_with_actor_id"])
def test_graph_extra_requires_explicit_public_only_preparation_mapping(tmp_path, monkeypatch, mode):
    cfg = _world_config()
    preparation(tmp_path, cfg)
    extra = {"agent_id": 4, "entity_name": "GraphExtra", "entity_type": "Organization", "actor_id": ""}
    if mode != "unmarked":
        extra["preparation_audience"] = "public"
    if mode == "public_with_actor_id":
        extra["actor_id"] = "actor_0"
    cfg["agent_configs"].append(extra)
    if mode != "public":
        with pytest.raises(rps.WorldContextMismatch):
            coordinator(tmp_path, monkeypatch, cfg)
        return
    coord = coordinator(tmp_path, monkeypatch, cfg)
    assert coord._preparation_actors[4] == coord._preparation_public
    asyncio.run(coord.decide("twitter", 0, coord._period_for(0), [4], lambda _: "EXTRA_PERSONA", []))
    call = next(c for c in _WorldLLM.calls if c["kind"] == "decision" and c["actor"] == "GraphExtra")
    assert "PUBLIC_RESEARCH_ROW" in call["content"]
    assert "OWNER_ONLY" not in call["content"] and "MODELER_ONLY" not in call["content"]
