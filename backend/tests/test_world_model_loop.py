"""Reflexive world model in the real calendar round loop (design §2.1, acceptance A1–A4, A7).

Drives ``run_twitter_simulation`` / ``run_reddit_simulation`` with the FakeEnv harness
from ``test_calendar_round_loop`` and a scripted LLM stand-in that answers both the
per-actor decision prompts and the arbiter prompt.  Pins:

  A1 a round-1 decision (tariff raised) is a world fact in the round-2 WORLD STATE brief
     every agent receives, and in the round-2 decision prompt (reflexivity);
  A2 one decision per actor per round even with two platforms (shared future);
  A3 no platform begins round r+1 before world update r is committed (barrier);
  A4 arbiter failure → the round still commits with the deterministic update;
  A7 SIM_WORLD_MODEL=false / hours mode → no world artifacts, legacy path intact;
  resume: already-committed rounds are not re-decided or re-committed;
  live follow-ups (sim_d6ebcc77e22d): a provider content-filter rejection of the arbiter is
     recorded with class / HTTP status / provider code, and a public statement in the wrong
     script for the run language is rejected with a typed status → organic post.
"""

import asyncio
import json
import os
import re
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_BACKEND, "scripts")
for _p in (_BACKEND, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import run_parallel_simulation as rps  # noqa: E402
from action_logger import PlatformActionLogger  # noqa: E402
import app.services.decision_channel as dc  # noqa: E402
from tests.conftest import content_filter_error  # noqa: E402
from test_calendar_round_loop import (  # noqa: E402
    _FakeAgent,
    _FakeGraph,
    _calendar_config,
    _fake_elicit,
    _hours_config,
    _patch_runtime,
    _read_events,
    _run,
    _world_clock_notes,
)


# ===========================================================================
# scripted LLM: answers decision prompts per actor and the arbiter prompt
# ===========================================================================
class _WorldLLM:
    calls = []            # [{"kind", "round", "actor", "content"}]
    arbiter_fail = False
    arbiter_error = None          # callable → exception raised by the arbiter call (provider rejection)
    wrong_language_rounds = ()    # rounds in which Actor0's statement comes out in Chinese

    def __init__(self, *a, **k):
        self.provider = "fake"
        self.model = "fake-1"

    @staticmethod
    def _round_of(content):
        m = re.search(r"round (\d+)/(\d+)", content)
        return int(m.group(1)) if m else None

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, **kwargs):
        content = messages[-1]["content"]
        rnd = self._round_of(content)
        if "# DECIDE YOUR MOVE FOR THIS PERIOD" in content:
            actor = re.search(r"# DECIDE YOUR MOVE FOR THIS PERIOD — (.+)", content).group(1).strip()
            _WorldLLM.calls.append({"kind": "decision", "round": rnd, "actor": actor, "content": content,
                                    "system": messages[0]["content"] if messages[0]["role"] == "system" else ""})
            if actor == "Actor0":
                option = "impose_measure" if "[impose_measure]" in content else re.search(r"\[(\w+)\]", content).group(1)
                statement = (f"关税上调至25%（第{rnd}轮）。" if rnd in _WorldLLM.wrong_language_rounds
                             else f"Tariff raised to 25% on imports (round {rnd}).")
                return {"option_id": option, "targets": ["Actor1"], "magnitude": 0.9,
                        "public_statement": statement,
                        "private_rationale": "protect domestic producers",
                        "commitment": {"description": "Publish the tariff schedule", "due_periods": 1},
                        "alliance_moves": [{"target": "Actor2", "move": "propose"}],
                        "scenario_commitment": {"scenario": "A", "confidence": 0.9}}
            return {"option_id": "hold_position", "scenario_commitment": "abstain"}
        if "consequence arbiter" in content:
            _WorldLLM.calls.append({"kind": "arbiter", "round": None, "actor": None, "content": content})
            if _WorldLLM.arbiter_error is not None:
                raise _WorldLLM.arbiter_error()
            if _WorldLLM.arbiter_fail:
                raise RuntimeError("arbiter provider down")
            moved = "Actor0: Impose or raise a tariff" in content
            return {
                "narrative": "Tariff shock ripples through importers." if moved else "Quiet period.",
                "variable_changes": ([{"variable_id": "tariff_rate", "new_value": 25, "rationale": "decree"}]
                                     if moved and "tariff_rate: Tariff rate = 10%" in content else []),
                "events": [{"description": "Importers protest the tariff", "kind": "emergent",
                            "actors": ["Actor1"], "targets": ["Actor0"]}] if moved else [],
                "action_resolutions": [{"actor": "Actor0", "outcome": "success"}] if moved else [],
                "scenario_pressure": {"A": "up"},
            }
        raise AssertionError(f"unexpected prompt: {content[:80]}")


def _world_config(**kw):
    cfg = _calendar_config(**kw)
    cfg["world_model"] = {
        "schema_version": "world-model-seed/v1",
        "question": "Will scenario A happen by Q1 2027?",
        "as_of_date": "2026-07-11",
        "horizon_date": "2027-03-31",
        "state_variables": [{"name": "Tariff rate", "value": 10, "unit": "%", "provenance": "research"}],
        "actors": [
            {"agent_id": 0, "name": "Actor0", "agency_class": "sovereign_government", "capacity_per_round": 3},
            {"agent_id": 1, "name": "Actor1", "agency_class": "firm"},
            {"agent_id": 2, "name": "Actor2", "agency_class": "industry_coalition"},
            {"agent_id": 3, "name": "Actor3", "agency_class": "ngo_advocacy"},
        ],
        "relationships": [{"source": "Actor0", "target": "Actor1", "type": "REGULATES", "valence": "directional"}],
        "settings": {"max_change_ratio": 5.0, "arbiter_enabled": True},
    }
    return cfg


def _patch_world(monkeypatch, sim_dir, envs):
    _patch_runtime(monkeypatch, sim_dir, envs)
    _WorldLLM.calls = []
    _WorldLLM.arbiter_fail = False
    _WorldLLM.arbiter_error = None
    _WorldLLM.wrong_language_rounds = ()
    monkeypatch.setattr("app.utils.llm_client.LLMClient", _WorldLLM)
    monkeypatch.setattr(dc, "elicit_round", lambda *a, **k: pytest.fail("legacy elicit must not run in world mode"))
    rps._WORLD_COORDINATORS.clear()
    rps._WORLD_TRAJ_WRITTEN.clear()


def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ===========================================================================
# A1 + artifacts: single platform, three rounds
# ===========================================================================
def test_world_model_round_loop_is_reflexive(tmp_path, monkeypatch):
    sim_dir = str(tmp_path)
    envs = []
    _patch_world(monkeypatch, sim_dir, envs)
    _run(_world_config(), sim_dir)
    env = envs[0]

    # every active agent decided → no organic LLMAction step was needed; statements were ManualActions
    assert env.llm_steps == []
    decisions = [c for c in _WorldLLM.calls if c["kind"] == "decision"]
    arbiters = [c for c in _WorldLLM.calls if c["kind"] == "arbiter"]
    assert [c["round"] for c in decisions if c["actor"] == "Actor0"] == [1, 2, 3]
    assert len(arbiters) == 3
    assert all(c["system"].startswith("You are Actor") for c in decisions)   # the sealed role brief is the system turn

    # ---- reflexivity: round-2 WORLD CLOCK carries the committed world of round 1 ----
    notes = _world_clock_notes(env)
    r2 = [n for n in notes if "round 2/3" in n]
    assert r2
    assert "# WORLD STATE — as of 2026-09-30 (after 2026-Q3)" in r2[0]
    assert "- Tariff rate: 25% (was 10% last period)" in r2[0]
    assert "## Moves last period" in r2[0] and 'Actor0: Impose or raise a tariff' in r2[0]
    assert "Tariff raised to 25% on imports (round 1)." in r2[0]
    assert "Importers protest the tariff" in r2[0]
    assert "## Alliances and rivalries" in r2[0] and "Actor0 — Actor2" in r2[0]
    assert "## Pending and announced" in r2[0] and "Publish the tariff schedule (due 2026-Q4)" in r2[0]
    assert "## WHAT CHANGED LAST PERIOD\nTariff shock ripples through importers." in r2[0]
    # herding guard: the scenario distribution never appears in agent-facing text
    assert not re.search(r"\bA\b\s*[:=]\s*\d", r2[0]) and "60%" not in r2[0] and "0.6" not in r2[0]
    # round 1 shows the seeded world and no moves yet
    r1 = [n for n in notes if "round 1/3" in n][0]
    assert "- Tariff rate: 10%" in r1
    assert "## Moves last period" not in r1 and "(first period)" in r1

    # ---- the round-2 decision prompt sees the changed world and the actor's own outcome ----
    d2 = [c for c in decisions if c["actor"] == "Actor0" and c["round"] == 2][0]["content"]
    assert "- Tariff rate: 25% (was 10% last period)" in d2
    assert "# YOUR SITUATION — Actor0" in d2 and "outcome so far: success" in d2
    assert "Publish the tariff schedule" in d2 and "(DUE NOW)" in d2
    assert "Relationships that moved last period: Actor2 (neutral)" in d2   # a proposal is not yet an alliance
    assert "[hold_position]" in d2 and "Candidate scenarios: A; B" in d2

    # ---- artifacts ----
    state = json.load(open(os.path.join(sim_dir, "world_state.json"), encoding="utf-8"))
    assert state["committed_round"] == 3 and state["summary"]["rounds_committed"] == 3
    assert state["world"]["variables"][0]["value"] == 25.0
    assert state["world"]["variables"][0]["history"][-1]["source"] == "arbiter"
    history = _read_jsonl(os.path.join(sim_dir, "world_state_history.jsonl"))
    assert [h["round"] for h in history] == [1, 2, 3]
    assert history[0]["arbiter_status"] == "applied" and history[0]["diff"]["variables_changed"][0]["to"] == 25.0
    assert history[0]["scenario_round_status"] == "committed" and history[0]["shares"]["A"] > 0.6
    assert history[0]["period_label"] == "2026-Q3"
    actions_rows = _read_jsonl(os.path.join(sim_dir, "world_actions.jsonl"))
    round1_actors = [r["actor_name"] for r in actions_rows if r["round"] == 1]
    assert "Actor0" in round1_actors and 2 <= len(round1_actors) <= 3   # principal + sampled (agents_per_hour_max=2)
    assert len(round1_actors) == len(set(round1_actors))
    a0 = [r for r in actions_rows if r["actor_name"] == "Actor0" and r["round"] == 1][0]
    assert a0["option"]["id"] == "impose_measure" and a0["targets"] == ["Actor1"] and a0["scenario"] == "A"

    events = _read_events(sim_dir)
    posts = [e for e in events if e.get("action_type") == "CREATE_POST" and e.get("action_args", {}).get("is_world_decision")]
    assert [p["round"] for p in posts] == [1, 2, 3] and posts[0]["agent_name"] == "Actor0"
    assert posts[0]["action_args"]["option_id"] == "impose_measure"
    updates = [e for e in events if e.get("event_type") == "world_update"]
    assert [u["round"] for u in updates] == [1, 2, 3]
    assert updates[0]["period_label"] == "2026-Q3" and updates[0]["arbiter_status"] == "applied"
    assert "1 facts changed" in updates[0]["headline"]
    # round_end counts the published decision post
    ends = {e["round"]: e for e in events if e.get("event_type") == "round_end"}
    assert ends[1]["actions_count"] >= 1

    # scenario-share trajectory keeps its contract and moves toward A
    traj = json.load(open(os.path.join(sim_dir, "world_state_trajectory.json"), encoding="utf-8"))
    assert traj["schema_version"] == 3 and traj["mode"] == "calendar" and traj["calendar_unit"] == "quarter"
    assert traj["outcome"]["leader"] == "A" and traj["outcome"]["shares"]["A"] > 0.6
    assert traj["world_model"]["rounds_committed"] == 3 and traj["world_model"]["arbiter_failed_rounds"] == 0
    assert [r["round_status"] for r in traj["trajectory"][1:]] == ["committed"] * 3
    dec_rows = _read_jsonl(os.path.join(sim_dir, "decisions.jsonl"))
    assert dec_rows and all(r["scenario"] == "A" and r["period_end"] for r in dec_rows)
    digest_rows = _read_jsonl(os.path.join(sim_dir, "world_digest.jsonl"))
    assert [r["round"] for r in digest_rows] == [1, 2, 3] and "Tariff shock" in digest_rows[0]["digest"]
    # the agent's private memory carries its own move for the response step
    agent0 = env.agent_graph.get_agent(0)
    moves = [c for c, _r in agent0.memory_notes if c.startswith("# YOUR MOVE THIS PERIOD")]
    assert moves and "You chose: Impose or raise a tariff" in moves[0] and "Directed at: Actor1" in moves[0]


# ===========================================================================
# A2 + A3: two platforms share one decision per actor and run in lockstep
# ===========================================================================
def _patch_reddit(monkeypatch, sim_dir):
    with open(os.path.join(sim_dir, "reddit_profiles.json"), "w", encoding="utf-8") as f:
        json.dump([{"username": f"actor{i}", "name": f"Actor{i}", "persona": f"You are Actor{i}."} for i in range(4)], f)

    async def _fake_reddit_graph(profile_path=None, model=None, available_actions=None):
        return _FakeGraph([_FakeAgent(i, f"Actor{i}") for i in range(4)])

    monkeypatch.setattr(rps, "generate_reddit_agent_graph", _fake_reddit_graph)


def test_two_platforms_share_decisions_and_respect_barrier(tmp_path, monkeypatch):
    sim_dir = str(tmp_path)
    envs = []
    _patch_world(monkeypatch, sim_dir, envs)
    _patch_reddit(monkeypatch, sim_dir)
    seq = []
    orig_begin = rps._ReflexiveWorldCoordinator.begin_round
    orig_commit = rps._ReflexiveWorldCoordinator._commit_round

    async def _begin(self, platform, round_num, period, action_logger=None):
        out = await orig_begin(self, platform, round_num, period, action_logger)
        seq.append(("begin", platform, round_num))
        return out

    async def _commit(self, round_num, buf):
        await orig_commit(self, round_num, buf)
        seq.append(("commit", None, round_num))

    monkeypatch.setattr(rps._ReflexiveWorldCoordinator, "begin_round", _begin)
    monkeypatch.setattr(rps._ReflexiveWorldCoordinator, "_commit_round", _commit)

    cfg = _world_config()

    async def _both():
        return await asyncio.gather(
            rps.run_twitter_simulation(cfg, sim_dir, action_logger=PlatformActionLogger("twitter", sim_dir),
                                       main_logger=None, semaphore_platforms=2),
            rps.run_reddit_simulation(cfg, sim_dir, action_logger=PlatformActionLogger("reddit", sim_dir),
                                      main_logger=None, semaphore_platforms=2),
        )

    asyncio.run(_both())

    decisions = [c for c in _WorldLLM.calls if c["kind"] == "decision"]
    # A2: each actor decided exactly once per round although two platforms ran
    assert sorted(c["round"] for c in decisions if c["actor"] == "Actor0") == [1, 2, 3]
    pairs = [(c["actor"], c["round"]) for c in decisions]
    assert len(pairs) == len(set(pairs)) and 6 <= len(pairs) <= 9       # one decision per (actor, round)
    assert len([c for c in _WorldLLM.calls if c["kind"] == "arbiter"]) == 3
    # A3: for every round r ≥ 1, both platforms began r only after commit r-1
    commits = {r: i for i, (kind, _p, r) in enumerate(seq) if kind == "commit"}
    assert sorted(commits) == [0, 1, 2]
    for i, (kind, platform, r) in enumerate(seq):
        if kind == "begin" and r > 0:
            assert commits[r - 1] < i, f"{platform} began round {r + 1} before world update {r} committed"
    # both platforms published the same statement and logged the same world update rows
    for plat in ("twitter", "reddit"):
        rows = _read_jsonl(os.path.join(sim_dir, plat, "actions.jsonl"))
        posts = [e for e in rows if e.get("action_type") == "CREATE_POST" and e.get("action_args", {}).get("is_world_decision")]
        assert [p["round"] for p in posts] == [1, 2, 3], plat
        assert [u["round"] for u in rows if u.get("event_type") == "world_update"] == [1, 2, 3], plat
    history = _read_jsonl(os.path.join(sim_dir, "world_state_history.jsonl"))
    assert [h["round"] for h in history] == [1, 2, 3]
    state = json.load(open(os.path.join(sim_dir, "world_state.json"), encoding="utf-8"))
    assert state["committed_round"] == 3 and state["world"]["variables"][0]["value"] == 25.0
    assert os.path.exists(os.path.join(sim_dir, "world_state_trajectory.json"))


# ===========================================================================
# A4: arbiter failure → deterministic commit, loop survives
# ===========================================================================
def test_arbiter_failure_round_commits_deterministically(tmp_path, monkeypatch):
    sim_dir = str(tmp_path)
    envs = []
    _patch_world(monkeypatch, sim_dir, envs)
    _WorldLLM.arbiter_fail = True
    _run(_world_config(), sim_dir)
    env = envs[0]
    history = _read_jsonl(os.path.join(sim_dir, "world_state_history.jsonl"))
    assert [h["arbiter_status"] for h in history] == ["failed"] * 3
    assert history[0]["arbiter_problems"] == ["llm error: RuntimeError: arbiter provider down"]
    state = json.load(open(os.path.join(sim_dir, "world_state.json"), encoding="utf-8"))
    assert state["committed_round"] == 3
    assert state["world"]["variables"][0]["value"] == 10.0                 # no fabricated numeric effect
    assert state["summary"]["arbiter_failed_rounds"] == 3
    # the deterministic world still moved: Actor0's move, its commitment and the scheduled event are visible
    notes = _world_clock_notes(env)
    r2 = [n for n in notes if "round 2/3" in n][0]
    assert "## Moves last period" in r2 and "Tariff raised to 25% on imports (round 1)." in r2
    assert "Publish the tariff schedule" in r2
    r3 = [n for n in notes if "round 3/3" in n][0]
    assert "[2026-11-05] 事件A发生" in r3                                    # scheduled event of round 2 → round-3 brief
    traj = json.load(open(os.path.join(sim_dir, "world_state_trajectory.json"), encoding="utf-8"))
    assert traj["world_model"]["arbiter_failed_rounds"] == 3 and traj["outcome"]["leader"] == "A"


def test_arbiter_content_filter_rejection_is_recorded_precisely(tmp_path, monkeypatch):
    """Live run sim_d6ebcc77e22d: two arbiter calls were rejected by the provider content filter
    (HTTP 400, code 1301) and the history only said ``llm error: BadRequestError``.  The record now
    names class, status, code and classification; the round still commits deterministically."""
    sim_dir = str(tmp_path)
    envs = []
    _patch_world(monkeypatch, sim_dir, envs)
    _WorldLLM.arbiter_error = content_filter_error
    _run(_world_config(), sim_dir)
    history = _read_jsonl(os.path.join(sim_dir, "world_state_history.jsonl"))
    assert [h["arbiter_status"] for h in history] == ["failed"] * 3
    for row in history:
        [problem] = row["arbiter_problems"]
        assert problem.startswith("llm error: BadRequestError (HTTP 400, provider code 1301, content filter): "
                                  "Error code: 400 - {'contentFilter'")
        assert "'code': '1301'" in problem and len(problem) <= 320
    state = json.load(open(os.path.join(sim_dir, "world_state.json"), encoding="utf-8"))
    assert state["committed_round"] == 3 and state["world"]["variables"][0]["value"] == 10.0
    assert state["summary"]["arbiter_failed_rounds"] == 3
    updates = [e for e in _read_events(sim_dir) if e.get("event_type") == "world_update"]
    assert [u["arbiter_status"] for u in updates] == ["failed"] * 3
    # the deterministic world still moved and the loop kept deciding
    assert [c["round"] for c in _WorldLLM.calls if c["kind"] == "decision" and c["actor"] == "Actor0"] == [1, 2, 3]


def test_wrong_language_statement_is_rejected_and_actor_posts_organically(tmp_path, monkeypatch):
    """A Chinese public_statement in an English run (live: MOFCOM, round 4) is rejected with a typed
    status: no decision post, the actor falls back to its organic post, and the rejected text never
    enters the shared world."""
    sim_dir = str(tmp_path)
    envs = []
    _patch_world(monkeypatch, sim_dir, envs)
    _WorldLLM.wrong_language_rounds = (2,)
    cfg = _world_config()
    cfg["output_language"] = "English"
    _run(cfg, sim_dir)
    env = envs[0]
    d2 = [c for c in _WorldLLM.calls if c["kind"] == "decision" and c["actor"] == "Actor0" and c["round"] == 2][0]
    assert "Write public_statement in English." in d2["content"]
    rows = _read_jsonl(os.path.join(sim_dir, "world_actions.jsonl"))
    a0 = {r["round"]: r for r in rows if r["actor_name"] == "Actor0"}
    assert a0[1]["status"] == "ok" and a0[3]["status"] == "ok"
    assert a0[2]["status"] == "language_mismatch" and a0[2]["option"]["id"] == "hold_position"
    assert a0[2]["raw_option_id"] not in ("", "hold_position") and a0[2]["public_statement"] == ""   # the move it tried
    assert a0[2]["problems"] == ['public_statement is cjk-script but the run language is English: "关税上调至25%（第2轮）。"']
    # publication: no decision post in round 2; Actor0 fell back to the organic post instead
    posts = [e for e in _read_events(sim_dir)
             if e.get("action_type") == "CREATE_POST" and e.get("action_args", {}).get("is_world_decision")]
    assert [p["round"] for p in posts] == [1, 3]
    assert env.llm_steps == [[0]]
    # the rejected text never reaches the shared world: round 2 records no move for Actor0 (typed),
    # and the round-3 WORLD STATE brief carries the typed non-move instead of the Chinese statement
    history = _read_jsonl(os.path.join(sim_dir, "world_state_history.jsonl"))
    assert history[1]["decisions"]["language_mismatch"] == 1
    assert history[1]["decisions"]["ok"] == history[1]["decisions"]["total"] - 1
    r3 = [n for n in _world_clock_notes(env) if "round 3/3" in n][0]
    assert "- Actor0: Actor0 makes no recorded move (language_mismatch)" in r3
    digest_rows = _read_jsonl(os.path.join(sim_dir, "world_digest.jsonl"))
    assert "关税上调至25%" not in r3 and "关税" not in digest_rows[1]["digest"]
    state = json.load(open(os.path.join(sim_dir, "world_state.json"), encoding="utf-8"))
    assert state["committed_round"] == 3


# ===========================================================================
# A7: switch off / hours mode → legacy behaviour, no world artifacts
# ===========================================================================
def test_world_model_off_falls_back_to_legacy_inband(tmp_path, monkeypatch):
    sim_dir = str(tmp_path)
    envs, calls = [], []
    _patch_runtime(monkeypatch, sim_dir, envs)
    monkeypatch.setenv("SIM_WORLD_MODEL", "false")
    monkeypatch.setattr(dc, "elicit_round", _fake_elicit(calls))
    rps._WORLD_COORDINATORS.clear()
    _run(_world_config(), sim_dir)
    assert not os.path.exists(os.path.join(sim_dir, "world_state.json"))
    assert not os.path.exists(os.path.join(sim_dir, "world_actions.jsonl"))
    assert len(calls) == 3                                                 # legacy in-band elicitation ran
    assert len(envs[0].llm_steps) == 3                                     # agents posted organically
    assert os.path.exists(os.path.join(sim_dir, "world_state_trajectory.json"))
    assert not any(e.get("event_type") == "world_update" for e in _read_events(sim_dir))


def test_hours_mode_ignores_world_model_block(tmp_path, monkeypatch):
    sim_dir = str(tmp_path)
    envs = []
    _patch_world(monkeypatch, sim_dir, envs)
    cfg = _hours_config()
    cfg["world_model"] = _world_config()["world_model"]
    _run(cfg, sim_dir, max_rounds=1)
    assert len(envs[0].llm_steps) == 1
    assert _WorldLLM.calls == []
    assert not os.path.exists(os.path.join(sim_dir, "world_state.json"))


# ===========================================================================
# resume: committed rounds are not re-decided or re-committed
# ===========================================================================
def test_resume_skips_committed_world_rounds(tmp_path, monkeypatch):
    sim_dir = str(tmp_path)
    envs = []
    _patch_world(monkeypatch, sim_dir, envs)
    cfg = _world_config()
    _run(cfg, sim_dir)
    before = json.load(open(os.path.join(sim_dir, "world_state.json"), encoding="utf-8"))
    n_calls = len(_WorldLLM.calls)
    # fake a crash after round 1 on this platform; the world itself already committed all three rounds
    ckpt_path = os.path.join(sim_dir, "twitter", "checkpoint.json")
    db_path = os.path.join(sim_dir, "twitter_simulation.db")
    with open(ckpt_path, "w", encoding="utf-8") as f:
        json.dump({"platform": "twitter", "completed_round": 1, "last_rowid": rps._max_trace_rowid(db_path),
                   "total_rounds": 3, "total_actions": 0}, f)
    rps._WORLD_COORDINATORS.clear()
    _run(cfg, sim_dir, resume=True)
    env2 = envs[1]
    assert len(_WorldLLM.calls) == n_calls                                 # no re-decision, no re-arbitration
    assert len(env2.llm_steps) == 2                                        # replayed rounds post organically
    after = json.load(open(os.path.join(sim_dir, "world_state.json"), encoding="utf-8"))
    assert after["committed_round"] == 3 and after["world"]["variables"] == before["world"]["variables"]
    assert len(_read_jsonl(os.path.join(sim_dir, "world_state_history.jsonl"))) == 3
    # the replayed rounds still observe the committed world brief
    notes = _world_clock_notes(env2)
    assert any("# WORLD STATE" in n for n in notes)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-x", "-q"]))
