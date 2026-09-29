"""CAL-TEMPORAL spec §7 item 6 — 日历轮循环的端到端离线测试（stubbed env，零 LLM）。

驱动真实的 run_twitter_simulation 轮循环（FakeEnv + 真 sqlite trace 表），钉住：
  1) 轮数 = temporal_config.n_rounds（运行期 max_rounds 被忽略，绝不截断预测期）；
  2) round_start/round_end 事件带时段字段（period_label / period_end）落 actions.jsonl；
  3) 日历模式不做 active_hours 门控（active_hours=[] 的 agent 照常激活）；
  4) cadence=="principal" 的主角每轮无条件激活，sampled agent 受采样上限约束；
  5) 世界时钟头（# WORLD CLOCK，spec §5 verbatim）与一次性动作词汇表注入内容；
  6) in-band 世界演化（SIM_DECISION_CHANNEL_INBAND）：world_digest.jsonl /
     world_state_trajectory.json（schema v3）/ decisions.jsonl 落盘、摘要喂下一轮头部；
     演化故障注入 → 该轮照常完成、下一轮空摘要（"(first period)"）、绝不崩溃；
  7) 死轮与检查点/断点续跑路径完好（只按轮次索引记账，与演化解耦）；
  8) hours 模式（无 temporal_config）回归钉：无注入、无演化产物、max_rounds 照旧截断。

所有测试通过 monkeypatch 替换 LLM/OASIS 依赖（generate_twitter_agent_graph / oasis.make /
create_model / decision_channel.elicit_round），完全离线、确定性。
"""

import asyncio
import json
import os
import sqlite3
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_BACKEND, "scripts")
for _p in (_BACKEND, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import run_parallel_simulation as rps  # noqa: E402
from action_logger import PlatformActionLogger  # noqa: E402
from oasis import LLMAction, ManualAction  # noqa: E402
import app.services.decision_channel as dc  # noqa: E402


# ===========================================================================
# 测试替身：FakeAgent / FakeGraph / FakeEnv（真 sqlite trace 表）
# ===========================================================================
class _SysMsg:
    """camel BaseMessage 的最小替身（_inject_behavior_hint 只用 content/create_new_instance）。"""

    def __init__(self, content):
        self.content = content

    def create_new_instance(self, content):
        return _SysMsg(content)


class _FakeAgent:
    def __init__(self, agent_id, name):
        self.agent_id = agent_id
        self.name = name
        self._original_system_message = _SysMsg(f"You are {name}.")
        self._system_message = self._original_system_message
        self.memory_notes = []  # [(content, role)] — update_memory 注入的 SYSTEM 记忆

    def _generate_system_message_for_output_language(self):
        return self._original_system_message

    def init_messages(self):
        pass

    def update_memory(self, msg, role):
        self.memory_notes.append((getattr(msg, "content", str(msg)), role))


class _FakeGraph:
    def __init__(self, agents):
        self._agents = {a.agent_id: a for a in agents}

    def get_agent(self, aid):
        return self._agents[aid]

    def get_agents(self):
        return list(self._agents.items())


def _ensure_db(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS trace "
                "(user_id INTEGER, action TEXT, info TEXT, created_at TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS user "
                "(user_id INTEGER, agent_id INTEGER, name TEXT, user_name TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS post (post_id INTEGER, user_id INTEGER, "
                "content TEXT, original_post_id INTEGER, quote_content TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS comment "
                "(comment_id INTEGER, user_id INTEGER, content TEXT)")
    conn.commit()
    conn.close()


class _FakeEnv:
    """真实轮循环的环境替身：LLMAction 轮写 create_post trace 行（有机动作），
    ManualAction（种子帖/定时事件）按其真实 action_type 写行。"""

    def __init__(self, agent_graph, db_path):
        self.agent_graph = agent_graph
        self.db_path = db_path
        self.llm_steps = []  # 每个有机轮的活跃 agent_id 列表（激活断言用）

    async def reset(self):
        pass

    async def step(self, actions):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        llm_ids = []
        for agent, act in actions.items():
            for a in (act if isinstance(act, list) else [act]):
                if isinstance(a, ManualAction):
                    cur.execute(
                        "INSERT INTO trace VALUES (?, ?, ?, 't')",
                        (agent.agent_id, a.action_type.value, json.dumps(a.action_args)))
                else:  # LLMAction → 一条有机 CREATE_POST
                    llm_ids.append(agent.agent_id)
                    cur.execute(
                        "INSERT INTO trace VALUES (?, 'create_post', ?, 't')",
                        (agent.agent_id,
                         json.dumps({"content": f"{agent.name} strategic move"})))
        conn.commit()
        conn.close()
        if llm_ids:
            self.llm_steps.append(sorted(llm_ids))

    async def close(self):
        pass


class _DummyLLM:
    """LLMClient 替身——in-band 演化构造它但 elicit 被 monkeypatch，绝不触网。"""

    def __init__(self, *a, **k):
        pass

    def chat_json(self, *a, **k):  # pragma: no cover — 不应被真实调用
        raise AssertionError("test 不应触达真实 LLM")


# ===========================================================================
# 配置与运行 harness
# ===========================================================================
_ROUND_DATES = [
    {"round": 0, "period_start": "2026-07-12", "period_end": "2026-09-30", "label": "2026-Q3"},
    {"round": 1, "period_start": "2026-10-01", "period_end": "2026-12-31", "label": "2026-Q4"},
    {"round": 2, "period_start": "2027-01-01", "period_end": "2027-03-31", "label": "2027-Q1"},
]


def _calendar_config(activity=1.0, principal=True):
    agents = []
    for i in range(4):
        agents.append({
            "agent_id": i,
            "entity_name": f"Actor{i}",
            "activity_level": activity,
            "influence_weight": 0.9 if (principal and i == 0) else 1.0,
            "active_hours": [],  # 日历模式必须无 active_hours 门控（hours 模式将全员死锁）
            "cadence": "principal" if (principal and i == 0) else "sampled",
        })
    return {
        "simulation_id": "sim_test_calendar",
        "temporal_config": {
            "schema_version": 1, "mode": "calendar",
            "as_of_date": "2026-07-11", "horizon_date": "2027-03-31",
            "horizon_source": "anchored_period", "horizon_text": "Q1 2027",
            "horizon_defaulted": False,
            "unit": "quarter", "unit_stride": 1, "n_rounds": 3,
            "round_dates": _ROUND_DATES,
            "span_days": 263, "target_max_rounds": 36,
            "round_cap_coarsened": None, "beyond_horizon_events": [], "warnings": [],
        },
        # 兼容 shim（spec §3）：total_simulation_hours = n_rounds, minutes_per_round = 60
        "time_config": {"total_simulation_hours": 3, "minutes_per_round": 60,
                        "agents_per_hour_max": 2},
        "agent_configs": agents,
        "event_config": {
            "initial_posts": [],
            "scheduled_events": [{"round": 1, "date": "2026-11-05",
                                  "content": "[2026-11-05] 事件A发生",
                                  "poster_agent_id": 0}],
        },
        "world_state_seed": {"scenarios": ["A", "B"], "base_rates": {"A": 0.6, "B": 0.4},
                             "as_of_date": "2026-07-11", "horizon_date": "2027-03-31"},
    }


def _hours_config():
    cfg = _calendar_config()
    del cfg["temporal_config"]  # presence-keyed：缺 temporal_config → hours 旧路径
    cfg["time_config"] = {"total_simulation_hours": 2, "minutes_per_round": 60,
                          "agents_per_hour_max": 2, "start_hour": 9}
    for a in cfg["agent_configs"]:
        a["active_hours"] = list(range(24))
        a.pop("cadence", None)
    return cfg


def _patch_runtime(monkeypatch, sim_dir, envs):
    """把 run_twitter_simulation 的 LLM/OASIS 依赖替换为离线替身。
    envs: list 容器——每次 oasis.make 产出的 FakeEnv 都 append 进去（续跑第二个 env）。"""
    os.makedirs(sim_dir, exist_ok=True)
    with open(os.path.join(sim_dir, "twitter_profiles.csv"), "w", encoding="utf-8") as f:
        f.write("agent_id\n")

    async def _fake_graph_gen(profile_path=None, model=None, available_actions=None):
        return _FakeGraph([_FakeAgent(i, f"Actor{i}") for i in range(4)])

    def _fake_make(agent_graph=None, platform=None, database_path=None, semaphore=None):
        _ensure_db(database_path)
        env = _FakeEnv(agent_graph, database_path)
        envs.append(env)
        return env

    monkeypatch.setattr(rps, "create_model", lambda config, use_boost=False: object())
    monkeypatch.setattr(rps, "generate_twitter_agent_graph", _fake_graph_gen)
    monkeypatch.setattr(rps, "build_oasis_platform", lambda *a, **k: None)
    monkeypatch.setattr(rps.oasis, "make", _fake_make)
    monkeypatch.setattr(rps, "get_oasis_semaphore", lambda *a, **k: None)
    monkeypatch.setattr("app.utils.llm_client.LLMClient", _DummyLLM)
    # 减少活动部件：参与度采样关闭（有独立测试覆盖）；磁盘预检保持默认（真实磁盘充足）
    monkeypatch.setenv("SIM_ENGAGEMENT_SAMPLER", "false")


def _fake_elicit(calls):
    """决策通道 elicit 替身：记录 period_ctx，恒定向情景 A 承诺（确定性）。"""

    def _elicit(roster, period_ctx):
        calls.append({"roster": roster, "ctx": period_ctx})
        if not roster:
            return []
        aid = roster[0].get("agent_id")
        return [{"agent_id": aid, "scenario": "A", "magnitude": 1.0,
                 "confidence": 0.9, "round": period_ctx.get("round_num"),
                 "period_end": ((period_ctx.get("period") or {}).get("period_end")),
                 "weight": 0.9}]

    return _elicit


def _run(config, sim_dir, resume=False, max_rounds=None):
    logger = PlatformActionLogger("twitter", sim_dir)
    return asyncio.run(rps.run_twitter_simulation(
        config, sim_dir, action_logger=logger, main_logger=None,
        max_rounds=max_rounds, resume=resume))


def _read_events(sim_dir):
    out = []
    with open(os.path.join(sim_dir, "twitter", "actions.jsonl"), encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def _world_clock_notes(env):
    notes = []
    for _aid, agent in env.agent_graph.get_agents():
        for content, _role in agent.memory_notes:
            if content.startswith("# WORLD CLOCK"):
                notes.append(content)
    return notes


def _world_clock_roles(env):
    """本轮世界时钟注入所用的 backend role 列表（回归护栏见 test_world_clock_delivered_as_user）。"""
    roles = []
    for _aid, agent in env.agent_graph.get_agents():
        for content, role in agent.memory_notes:
            if content.startswith("# WORLD CLOCK"):
                roles.append(role)
    return roles


# ===========================================================================
# 1+2+3+4+5+6) 日历全链路：轮数/时段字段/激活/注入/in-band 演化产物
# ===========================================================================
def test_calendar_loop_full_run(tmp_path, monkeypatch):
    sim_dir = str(tmp_path)
    envs, calls = [], []
    _patch_runtime(monkeypatch, sim_dir, envs)
    monkeypatch.setattr(dc, "elicit_round", _fake_elicit(calls))

    # max_rounds=1 必须被日历模式忽略（cap 已在配置生成期粗化消化，绝不截断预测期）
    _run(_calendar_config(), sim_dir, max_rounds=1)
    env = envs[0]

    # ---- 轮数 = n_rounds（3），每轮都有有机 env.step ----
    assert len(env.llm_steps) == 3

    # ---- 主角每轮无条件激活；sampled 受上限（agents_per_hour_max=2）约束 ----
    for ids in env.llm_steps:
        assert 0 in ids                       # principal 每轮在场
        sampled = [i for i in ids if i != 0]
        assert 1 <= len(sampled) <= 2         # sampled 填上限，不越界
    # active_hours=[] 也照常激活 → 无 active_hours 门控（hours 模式下全员会被过滤成死轮）

    # ---- round_start/round_end 事件带时段字段落 actions.jsonl ----
    events = _read_events(sim_dir)
    starts = {e["round"]: e for e in events if e.get("event_type") == "round_start"}
    ends = {e["round"]: e for e in events if e.get("event_type") == "round_end"}
    assert set(starts) == {0, 1, 2, 3} and set(ends) == {0, 1, 2, 3}
    for i, rp in enumerate(_ROUND_DATES, start=1):
        assert starts[i]["period_label"] == rp["label"]
        assert ends[i]["period_end"] == rp["period_end"]
    assert "period_label" not in starts[0]    # round 0（种子阶段）无时段

    # ---- 一次性动作词汇表（spec §5 verbatim）注入 system prompt ----
    sys_prompt = env.agent_graph.get_agent(1)._original_system_message.content
    assert "In this simulation each round is one calendar quarter" in sys_prompt
    assert "DO_NOTHING = strategic patience." in sys_prompt

    # ---- 世界时钟头（spec §5 verbatim）：时段/进度/事件/上一时段摘要 ----
    notes = _world_clock_notes(env)
    r1 = [n for n in notes if "round 1/3" in n]
    r2 = [n for n in notes if "round 2/3" in n]
    assert r1 and r2
    assert r1[0].startswith(
        "# WORLD CLOCK — 2026-Q3 (2026-07-12 → 2026-09-30) | round 1/3 | "
        "one quarter per round | forecast horizon 2027-03-31 (2 periods remain)")
    assert "OVER THIS ENTIRE quarter" in r1[0]
    assert "## CONFIRMED EVENTS THIS PERIOD\n(none)" in r1[0]
    assert "## WHAT CHANGED LAST PERIOD\n(first period)" in r1[0]
    # 第 2 轮：日程事件到期 + 上一时段演化摘要（含定性动量线，绝无数字份额）
    assert "[2026-11-05] 事件A发生" in r2[0]
    assert "(first period)" not in r2[0]
    assert "Momentum: A strengthened this period." in r2[0]
    assert "%" not in r2[0].split("## WHAT CHANGED LAST PERIOD")[1]  # herding guard

    # ---- elicit 收到 spec §5 时段框架上下文 ----
    assert len(calls) == 3
    assert calls[0]["ctx"]["unit"] == "quarter"
    assert calls[0]["ctx"]["horizon_date"] == "2027-03-31"
    assert calls[0]["ctx"]["period"]["label"] == "2026-Q3"
    assert calls[0]["ctx"]["n_rounds"] == 3

    # ---- world_digest.jsonl：定量份额只活在审计产物里 ----
    with open(os.path.join(sim_dir, "world_digest.jsonl"), encoding="utf-8") as f:
        digest_rows = [json.loads(l) for l in f if l.strip()]
    assert [r["round"] for r in digest_rows] == [1, 2, 3]
    for r, rp in zip(digest_rows, _ROUND_DATES):
        assert r["period_start"] == rp["period_start"]
        assert r["period_end"] == rp["period_end"]
        assert set(r["shares"]) == {"A", "B"}
        assert r["leader"] == "A"
        assert set(r["delta"]) == {"A", "B"}
        assert isinstance(r["digest"], str)

    # ---- world_state_trajectory.json：schema v3（spec §6）----
    with open(os.path.join(sim_dir, "world_state_trajectory.json"), encoding="utf-8") as f:
        traj = json.load(f)
    assert traj["schema_version"] == 3
    assert traj["mode"] == "calendar"
    assert traj["calendar_unit"] == "quarter"
    assert traj["horizon_date"] == "2027-03-31"
    assert traj["horizon_source"] == "anchored_period"
    assert traj["horizon_defaulted"] is False
    rows = traj["trajectory"]
    assert rows[0]["round"] == 0 and rows[0]["as_of"] == "2026-07-11"
    assert "period_end" not in rows[0]
    for row, rp in zip(rows[1:], _ROUND_DATES):
        assert row["as_of"] == rp["period_end"] == row["period_end"]
        assert row["period_start"] == rp["period_start"]
        assert row["label"] == rp["label"]
    assert traj["n_rounds"] == 3
    # 份额确实向被承诺的情景演化（A 领先且高于种子先验）
    assert traj["outcome"]["leader"] == "A"
    assert traj["outcome"]["shares"]["A"] > 0.6
    # decisions 行带 period_end（spec §6），且落 decisions.jsonl
    assert traj["decisions"] and all(d.get("period_end") for d in traj["decisions"])
    assert all("weight" not in d for d in traj["decisions"])
    assert os.path.exists(os.path.join(sim_dir, "decisions.jsonl"))
    # SIM-1：顶层有效性裁定（与 post-hoc 决策通道同一 helper，诚实对齐，无开关）
    assert traj["validity"] == "valid"
    assert traj["forecast_effect"] == "diagnostic_only"
    assert traj["epistemic_status"] == "elicited_model_projection"
    assert traj["round_accounting"]["rounds_accounted"] == 3
    assert traj["validity_reasons"] == []
    assert "unaccounted_rounds" not in traj["round_accounting"]  # 全部轮次已步进


# ===========================================================================
# 3b) 回归护栏：世界时钟必须以 USER 角色投喂，否则模型收不到（camel 0.2.78
#     ScoreBasedContextCreator 只留 records[0] 作系统消息、丢弃其后所有 SYSTEM 记录）。
#     此前用 SYSTEM 角色注入，动态世界时钟被 get_context() 静默丢弃——特性形同虚设。
# ===========================================================================
def test_world_clock_delivered_as_user_role(tmp_path, monkeypatch):
    from camel.types import OpenAIBackendRole
    sim_dir = str(tmp_path)
    envs, calls = [], []
    _patch_runtime(monkeypatch, sim_dir, envs)
    monkeypatch.setattr(dc, "elicit_round", _fake_elicit(calls))
    _run(_calendar_config(), sim_dir, max_rounds=1)
    env = envs[0]

    roles = _world_clock_roles(env)
    assert roles, "世界时钟从未注入——特性未生效"
    # 关键断言：每一条世界时钟记忆都以 USER 角色写入（绝非 SYSTEM）。
    # 退回 SYSTEM 会让 camel 的上下文构造器丢弃它，模型永远收不到本轮时段/进度/演化摘要。
    assert all(r == OpenAIBackendRole.USER for r in roles), (
        f"世界时钟必须以 USER 角色投喂；发现非 USER 角色：{set(roles)}")


# ===========================================================================
# 6b) 世界演化故障注入：该轮照常完成、下一轮空摘要、绝不崩溃
# ===========================================================================
def test_world_evolution_failure_round_completes_with_empty_digest(tmp_path, monkeypatch):
    sim_dir = str(tmp_path)
    envs = []
    _patch_runtime(monkeypatch, sim_dir, envs)

    def _boom(roster, period_ctx):
        raise RuntimeError("elicit 爆炸（故障注入）")

    monkeypatch.setattr(dc, "elicit_round", _boom)

    _run(_calendar_config(), sim_dir)  # 不抛 → 演化故障被隔离
    env = envs[0]

    # 三轮全部照常完成并记账
    assert len(env.llm_steps) == 3
    events = _read_events(sim_dir)
    ends = [e for e in events if e.get("event_type") == "round_end" and e["round"] >= 1]
    assert len(ends) == 3
    # 每轮演化失败 → 下一轮世界时钟头回落 "(first period)"（空摘要）
    for n in _world_clock_notes(env):
        assert "## WHAT CHANGED LAST PERIOD\n(first period)" in n
    # 步进从未成功 → 不落轨迹/digest（post-hoc 决策通道可按旧门控回退）
    assert not os.path.exists(os.path.join(sim_dir, "world_state_trajectory.json"))
    assert not os.path.exists(os.path.join(sim_dir, "world_digest.jsonl"))


# ===========================================================================
# 6c) SIM_DECISION_CHANNEL_INBAND=false / 空 scenarios → 演化静默关闭
# ===========================================================================
def test_inband_gate_off_and_empty_scenarios_silently_disable(tmp_path, monkeypatch):
    envs = []
    sim_a = str(tmp_path / "a")
    _patch_runtime(monkeypatch, sim_a, envs)
    monkeypatch.setenv("SIM_DECISION_CHANNEL_INBAND", "false")
    _run(_calendar_config(), sim_a)
    assert not os.path.exists(os.path.join(sim_a, "world_digest.jsonl"))
    assert not os.path.exists(os.path.join(sim_a, "world_state_trajectory.json"))
    assert len(envs[0].llm_steps) == 3  # 模拟本身照常跑满

    monkeypatch.delenv("SIM_DECISION_CHANNEL_INBAND", raising=False)
    envs2 = []
    sim_b = str(tmp_path / "b")
    _patch_runtime(monkeypatch, sim_b, envs2)
    cfg = _calendar_config()
    cfg["world_state_seed"]["scenarios"] = []  # spec §4: 空 scenarios → 静默关
    _run(cfg, sim_b)
    assert not os.path.exists(os.path.join(sim_b, "world_digest.jsonl"))
    assert not os.path.exists(os.path.join(sim_b, "world_state_trajectory.json"))
    assert len(envs2[0].llm_steps) == 3


# ===========================================================================
# 7) 死轮与检查点/断点续跑完好
# ===========================================================================
class _NeverActivateRNG:
    """random() 恒 1.0 → 激活概率判定 random() < min(1.0, p) 永假 → 全员不激活（死轮）。
    activity_level=0 会被读取端的 `or 0.5` 回落成 0.5，无法用配置造死轮，故钉 RNG。"""

    def random(self):
        return 1.0

    def getstate(self):  # _capture_rng_state 兼容
        raise RuntimeError("no state")


def test_dead_rounds_checkpoint_advances_no_crash(tmp_path, monkeypatch):
    sim_dir = str(tmp_path)
    envs, calls = [], []
    _patch_runtime(monkeypatch, sim_dir, envs)
    monkeypatch.setattr(dc, "elicit_round", _fake_elicit(calls))
    monkeypatch.setattr(rps, "_RNG", _NeverActivateRNG())

    _run(_calendar_config(principal=False), sim_dir)  # 无主角 + 采样全不中 → 三轮全死
    env = envs[0]
    assert env.llm_steps == []  # 无有机轮
    events = _read_events(sim_dir)
    ends = {e["round"]: e for e in events if e.get("event_type") == "round_end"}
    assert set(ends) == {0, 1, 2, 3}
    for i, rp in enumerate(_ROUND_DATES, start=1):
        assert ends[i]["actions_count"] == 0  # 死轮按 0 动作记账（定时事件另行计入总数）
        assert ends[i]["period_end"] == rp["period_end"]
    # 死轮也推进检查点到 3（RUN-7 语义不受演化影响）
    with open(os.path.join(sim_dir, "twitter", "checkpoint.json"), encoding="utf-8") as f:
        ckpt = json.load(f)
    assert ckpt["completed_round"] == 3 and ckpt["total_rounds"] == 3
    # 全死轮（心跳 only）→ 无演化步进 → 不落轨迹（诚实降级）
    assert not os.path.exists(os.path.join(sim_dir, "world_state_trajectory.json"))


def test_checkpoint_resume_skips_completed_rounds(tmp_path, monkeypatch):
    sim_dir = str(tmp_path)
    envs, calls = [], []
    _patch_runtime(monkeypatch, sim_dir, envs)
    monkeypatch.setattr(dc, "elicit_round", _fake_elicit(calls))

    cfg = _calendar_config()
    _run(cfg, sim_dir)
    assert len(envs[0].llm_steps) == 3

    # 完成态检查点 → 续跑零轮（total_rounds 用日历 n_rounds 口径）
    _run(cfg, sim_dir, resume=True)
    assert len(envs[1].llm_steps) == 0

    # 伪造"崩溃在第 1 轮后"的检查点 → 续跑只执行第 2、3 轮
    ckpt_path = os.path.join(sim_dir, "twitter", "checkpoint.json")
    db_path = os.path.join(sim_dir, "twitter_simulation.db")
    ckpt = {"platform": "twitter", "completed_round": 1,
            "last_rowid": rps._max_trace_rowid(db_path),
            "total_rounds": 3, "total_actions": 0}
    with open(ckpt_path, "w", encoding="utf-8") as f:
        json.dump(ckpt, f)
    _run(cfg, sim_dir, resume=True)
    env3 = envs[2]
    assert len(env3.llm_steps) == 2  # 只跑第 2、3 轮
    # 续跑轮的世界时钟头从 round 2 开始（round 1 不重放）
    notes = _world_clock_notes(env3)
    assert notes and all("round 1/3" not in n for n in notes)
    assert any("round 2/3" in n for n in notes)


# ===========================================================================
# 7b) SIM-1：in-band 有效性裁定按覆盖率记账——未步进的轮次按 missing 计入分母
# ===========================================================================
def _read_traj(sim_dir):
    with open(os.path.join(sim_dir, "world_state_trajectory.json"), encoding="utf-8") as f:
        return json.load(f)


def test_inband_verdict_counts_unstepped_rounds_after_resume(tmp_path, monkeypatch):
    """有损续跑（WorldState 从种子重建）只步进续跑轮：覆盖 1/3 轮 → unaccounted_rounds=2、
    inconclusive（low_valid_coverage）、forecast_effect=no_update，不再被判 valid。
    嵌套 outcome.round_accounting 保留 WorldState 原始口径。"""
    sim_dir = str(tmp_path)
    envs, calls = [], []
    _patch_runtime(monkeypatch, sim_dir, envs)
    monkeypatch.setattr(dc, "elicit_round", _fake_elicit(calls))

    cfg = _calendar_config()
    _run(cfg, sim_dir)
    assert _read_traj(sim_dir)["validity"] == "valid"

    # 伪造"崩溃在第 2 轮后"的检查点 → 续跑只执行第 3 轮
    ckpt_path = os.path.join(sim_dir, "twitter", "checkpoint.json")
    db_path = os.path.join(sim_dir, "twitter_simulation.db")
    ckpt = {"platform": "twitter", "completed_round": 2,
            "last_rowid": rps._max_trace_rowid(db_path),
            "total_rounds": 3, "total_actions": 0}
    with open(ckpt_path, "w", encoding="utf-8") as f:
        json.dump(ckpt, f)
    _run(cfg, sim_dir, resume=True)
    assert len(envs[1].llm_steps) == 1  # 只跑第 3 轮

    traj = _read_traj(sim_dir)
    acct = traj["round_accounting"]
    assert acct["unaccounted_rounds"] == 2
    assert acct["rounds_accounted"] == 3
    assert acct["counts"]["missing"] == 2 and acct["missing_rounds"] == 2
    assert acct["valid_transitions"] == 1
    assert acct["valid_coverage"] == pytest.approx(0.333333)
    assert traj["validity"] == "inconclusive"
    assert "low_valid_coverage" in traj["validity_reasons"]
    assert traj["forecast_effect"] == "no_update"
    assert traj["epistemic_status"] == "elicited_model_projection"
    raw = traj["outcome"]["round_accounting"]
    assert raw["rounds_accounted"] == 1 and "unaccounted_rounds" not in raw


def test_inband_verdict_counts_heartbeat_only_rounds_as_missing(tmp_path, monkeypatch):
    """全平台死轮只推水位（heartbeat）、从不步进 → 裁定按 missing 入账；覆盖 2/3 仍达
    min_valid_coverage → valid，但 round_accounting 如实记 unaccounted_rounds=1。
    完成日志行带上 validity。"""
    sim_dir = str(tmp_path)
    _patch_runtime(monkeypatch, sim_dir, [])
    monkeypatch.setattr(dc, "elicit_round", _fake_elicit([]))
    logs = []
    evo = rps._InbandWorldEvolution(_calendar_config(), sim_dir, 1, logs.append)
    evo.heartbeat("twitter", 0)  # 第 1 轮：死轮，无动作交付
    for rn in (1, 2):
        evo.deliver("twitter", rn, _ROUND_DATES[rn],
                    [{"agent_id": 0, "agent_name": "Actor0",
                      "action_args": {"content": "Actor0 strategic move"}}], [])
    evo.platform_done("twitter")

    traj = _read_traj(sim_dir)
    acct = traj["round_accounting"]
    assert acct["unaccounted_rounds"] == 1 and acct["counts"]["missing"] == 1
    assert acct["rounds_accounted"] == 3 and acct["valid_transitions"] == 2
    assert acct["valid_coverage"] == pytest.approx(0.666667)
    assert traj["validity"] == "valid" and traj["validity_reasons"] == []
    assert traj["forecast_effect"] == "diagnostic_only"
    assert any("in-band 世界演化完成" in m and "validity=valid" in m for m in logs)


def test_inband_verdict_counts_trailing_heartbeat_only_round_as_missing(tmp_path, monkeypatch):
    """末轮全平台死轮（只 heartbeat、其后再无 deliver）：只有 heartbeat 抬升最高已见轮，
    该轮仍须按 missing 入账（钉住 heartbeat 对 _max_seen_round 的更新）。"""
    sim_dir = str(tmp_path)
    _patch_runtime(monkeypatch, sim_dir, [])
    monkeypatch.setattr(dc, "elicit_round", _fake_elicit([]))
    evo = rps._InbandWorldEvolution(_calendar_config(), sim_dir, 1, lambda _m: None)
    for rn in (0, 1):
        evo.deliver("twitter", rn, _ROUND_DATES[rn],
                    [{"agent_id": 0, "agent_name": "Actor0",
                      "action_args": {"content": "Actor0 strategic move"}}], [])
    evo.heartbeat("twitter", 2)  # 第 3 轮：死轮，无动作交付
    evo.platform_done("twitter")

    traj = _read_traj(sim_dir)
    acct = traj["round_accounting"]
    assert acct["unaccounted_rounds"] == 1 and acct["counts"]["missing"] == 1
    assert acct["rounds_accounted"] == 3 and acct["valid_transitions"] == 2
    assert acct["valid_coverage"] == pytest.approx(0.666667)
    assert traj["validity"] == "valid" and traj["validity_reasons"] == []
    raw = traj["outcome"]["round_accounting"]
    assert raw["rounds_accounted"] == 2 and "unaccounted_rounds" not in raw


def test_inband_verdict_failure_keeps_trajectory(tmp_path, monkeypatch):
    """裁定 helper 异常只丢裁定键，绝不丢轨迹（degrade-safe）。"""
    sim_dir = str(tmp_path)
    envs, calls = [], []
    _patch_runtime(monkeypatch, sim_dir, envs)
    monkeypatch.setattr(dc, "elicit_round", _fake_elicit(calls))

    def _boom(*a, **k):
        raise RuntimeError("verdict 爆炸（故障注入）")

    monkeypatch.setattr(dc, "decision_channel_verdict", _boom)
    _run(_calendar_config(), sim_dir)

    traj = _read_traj(sim_dir)
    assert traj["schema_version"] == 3 and len(traj["trajectory"]) == 4
    for key in ("validity", "validity_reasons", "forecast_effect", "round_accounting",
                "epistemic_status"):
        assert key not in traj
    assert os.path.exists(os.path.join(sim_dir, "decisions.jsonl"))


# ===========================================================================
# 7c) SIM-2：真实 elicit_round 的名册校验记录落轨迹行 / digest 行 / run 级汇总
# ===========================================================================
class _ScriptedDecisionLLM:
    """LLMClient 替身（SIM-2）：每轮批量调用返回同一份脚本回复——字符串 id "0"（名册内，
    规范化为 int 0）+ 名册外幻觉 id 999。calls 记录调用次数（零额外调用）。"""

    calls = []

    def __init__(self, *a, **k):
        pass

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, **kw):
        type(self).calls.append(max_tokens)
        return {"decisions": [
            {"agent_id": "0", "scenario": "A", "magnitude": 1, "confidence": 1},
            {"agent_id": 999, "scenario": "A", "magnitude": 1, "confidence": 1}]}


def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_inband_decision_validation_recorded(tmp_path, monkeypatch):
    sim_dir = str(tmp_path)
    envs = []
    _patch_runtime(monkeypatch, sim_dir, envs)
    monkeypatch.setattr("app.utils.llm_client.LLMClient", _ScriptedDecisionLLM)
    monkeypatch.setattr(_ScriptedDecisionLLM, "calls", [])
    monkeypatch.setattr(rps, "_SIM_LLM_USAGE", {   # 进程级 token 计量隔离
        "calls": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0,
        "by_source": {}, "by_model": {}})

    _run(_calendar_config(), sim_dir)
    assert len(_ScriptedDecisionLLM.calls) == 3          # 每轮恰一次批量调用
    assert _ScriptedDecisionLLM.calls == [2048] * 3      # 小名册 max_tokens 不变

    traj = _read_traj(sim_dir)
    rows = traj["trajectory"][1:]
    assert len(rows) == 3 and "decision_validation" not in traj["trajectory"][0]
    for row in rows:
        rec = row["decision_validation"]
        assert rec["measured"] is True
        assert rec["reasons"]["unknown_agent"] == 1
        assert rec["normalized"]["id_coerced"] == 1
        assert "0" in rec["roster_agent_ids"] and "999" not in rec["roster_agent_ids"]
        assert rec["accepted"] == 1 and rec["rejected"] == 1
        assert rec["missing_from_reply"] == rec["roster_size"] - 1
        assert row["round_status"] == "committed"
    digest_rows = _read_jsonl(os.path.join(sim_dir, "world_digest.jsonl"))
    assert [r["round"] for r in digest_rows] == [1, 2, 3]
    for drow, row in zip(digest_rows, rows, strict=True):
        rec = row["decision_validation"]
        assert drow["actor_coverage"] == {
            k: rec[k] for k in ("roster_size", "accepted", "abstained", "rejected",
                                "missing_from_reply")}
    decisions = _read_jsonl(os.path.join(sim_dir, "decisions.jsonl"))
    assert decisions and all(d["agent_id"] == 0 for d in decisions)  # 999 从不入账
    summary = traj["decision_validation"]
    assert summary["measured_rounds"] == 3 and summary["unmeasured_rounds"] == 0
    assert summary["reasons"]["unknown_agent"] == 3
    slots = sum(r["decision_validation"]["roster_size"] for r in rows)
    fallback = sum(r["decision_validation"]["fallback_slots"] for r in rows)
    assert summary["slots"] == slots
    assert summary["fallback_share"] == round(fallback / slots, 6)
    # run 级 fallback_share 折入裁定：超 DECISION_CHANNEL_FALLBACK_MAX_SHARE(0.5) → inconclusive
    if summary["fallback_share"] > 0.5:
        assert traj["validity"] == "inconclusive"
        assert traj["validity_reasons"] == ["fallback_share_exceeded"]
        assert traj["forecast_effect"] == "no_update"
    else:
        assert traj["validity"] == "valid"


def test_inband_verdict_folds_fallback_share(tmp_path, monkeypatch):
    """直接驱动演化器：每轮 4 人名册只答 1 人 → fallback_share 0.75 → inconclusive。"""
    sim_dir = str(tmp_path)
    _patch_runtime(monkeypatch, sim_dir, [])
    monkeypatch.setattr("app.utils.llm_client.LLMClient", _ScriptedDecisionLLM)
    monkeypatch.setattr(_ScriptedDecisionLLM, "calls", [])
    monkeypatch.setattr(rps, "_SIM_LLM_USAGE", {
        "calls": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0,
        "by_source": {}, "by_model": {}})
    evo = rps._InbandWorldEvolution(_calendar_config(), sim_dir, 1, lambda _m: None)
    for rn in range(3):
        evo.deliver("twitter", rn, _ROUND_DATES[rn],
                    [{"agent_id": a, "agent_name": f"Actor{a}",
                      "action_args": {"content": f"Actor{a} move"}} for a in range(4)], [])
    evo.platform_done("twitter")

    traj = _read_traj(sim_dir)
    assert traj["decision_validation"]["fallback_share"] == 0.75
    assert traj["round_accounting"]["valid_transitions"] == 3
    assert traj["validity"] == "inconclusive"
    assert traj["validity_reasons"] == ["fallback_share_exceeded"]
    assert traj["forecast_effect"] == "no_update"


def test_inband_legacy_elicit_double_adds_no_validation_keys(tmp_path, monkeypatch):
    """旧签名的 elicit 替身不写记录 → 轨迹/digest/汇总均无新键、裁定不变。"""
    sim_dir = str(tmp_path)
    _patch_runtime(monkeypatch, sim_dir, [])
    monkeypatch.setattr(dc, "elicit_round", _fake_elicit([]))
    _run(_calendar_config(), sim_dir)
    traj = _read_traj(sim_dir)
    assert "decision_validation" not in traj
    assert all("decision_validation" not in row for row in traj["trajectory"])
    digest_rows = _read_jsonl(os.path.join(sim_dir, "world_digest.jsonl"))
    assert digest_rows and all("actor_coverage" not in r for r in digest_rows)
    assert traj["validity"] == "valid" and traj["validity_reasons"] == []


# ===========================================================================
# 8) hours 模式回归钉：无 temporal_config → 旧路径（无注入/无演化/max_rounds 截断）
# ===========================================================================
def test_hours_mode_untouched(tmp_path, monkeypatch):
    sim_dir = str(tmp_path)
    envs = []
    _patch_runtime(monkeypatch, sim_dir, envs)

    _run(_hours_config(), sim_dir, max_rounds=1)  # hours 模式 max_rounds 照旧截断
    env = envs[0]
    assert len(env.llm_steps) == 1
    # 无世界时钟注入、无动作词汇表、无演化产物
    assert _world_clock_notes(env) == []
    assert "each round is one calendar" not in \
        env.agent_graph.get_agent(0)._original_system_message.content
    assert not os.path.exists(os.path.join(sim_dir, "world_digest.jsonl"))
    assert not os.path.exists(os.path.join(sim_dir, "world_state_trajectory.json"))
    # round 事件不带时段字段
    for e in _read_events(sim_dir):
        assert "period_label" not in e and "period_end" not in e


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-x", "-q"]))
