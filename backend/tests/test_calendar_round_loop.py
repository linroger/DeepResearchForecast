"""CAL-TEMPORAL spec §7 item 6 — 日历轮循环的端到端离线测试（stubbed env，零 LLM）。

驱动真实的 run_twitter_simulation 轮循环（FakeEnv + 真 sqlite trace 表），钉住：
  1) 轮数 = temporal_config.n_rounds（运行期 max_rounds 被忽略，绝不截断预测期）；
  2) round_start/round_end 事件带时段字段（period_label / period_end）落 actions.jsonl；
  3) 日历模式不做 active_hours 门控（active_hours=[] 的 agent 照常激活）；
  4) cadence=="principal" 的主角每轮无条件激活，sampled agent 受采样上限约束；
  5) 世界时钟头（# WORLD CLOCK，spec §5 verbatim）与一次性动作词汇表注入内容；
  6) in-band 世界演化（SIM_DECISION_CHANNEL_INBAND）：world_digest.jsonl /
     world_state_trajectory.json（schema v3）/ decisions.jsonl 落盘、摘要喂下一轮头部；
     演化故障注入 → 该轮照常完成、下一轮空摘要、绝不崩溃；
  6b) REPORT-6 空段标记（SIM_ABSENCE_MARKERS，默认开）：首轮 / 平静期 / 摘要不可用 /
     本次运行不产出 / 本时段无日程事件各有具名标记，round >= 2 绝不自称首轮；空摘要只在
     本轮确无可报内容时算平静期，否则失败关闭为摘要不可用；开关关 →
     头部与轨迹逐字节回到旧文本（"(none)" / "(first period)"）；轨迹附加 delta_state_counts；
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
import types

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
from app.services import sim_period_context as spc  # noqa: E402


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
def _set_knob(monkeypatch, name, value):
    """value None → 删除环境变量，取 Config 默认（开）。"""
    if value is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize("period_v2,absence_markers", [
    (None, None), ("true", "false"), ("false", "true"), ("false", "false")])
def test_calendar_loop_full_run(tmp_path, monkeypatch, period_v2, absence_markers):
    sim_dir = str(tmp_path)
    envs, calls = [], []
    _patch_runtime(monkeypatch, sim_dir, envs)
    monkeypatch.setattr(dc, "elicit_round", _fake_elicit(calls))
    # REPORT-6：false = 旧占位逐字节（"(none)" / "(first period)"）；true/默认 = 具名空段标记。
    # SIM-6：SIM_PERIOD_CONTEXT_V2 只管事件段标题（预期事件，非 CONFIRMED）与摘要分段。
    _set_knob(monkeypatch, "SIM_PERIOD_CONTEXT_V2", period_v2)
    _set_knob(monkeypatch, "SIM_ABSENCE_MARKERS", absence_markers)
    v2_on = period_v2 != "false"
    markers_on = absence_markers != "false"
    heading = spc.SCHEDULED_EVENTS_HEADING_V2 if v2_on else "## CONFIRMED EVENTS THIS PERIOD"

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
    if v2_on:
        assert ("## SCHEDULED EVENTS THIS PERIOD (research timeline — expected; "
                "outcomes not known in advance)\n") in r1[0]
        assert "CONFIRMED" not in "".join(notes)
    if not markers_on:
        assert r1[0].endswith(heading + "\n(none)\n## WHAT CHANGED LAST PERIOD\n(first period)")
    else:
        assert (heading + "\n" + spc.WORLD_CLOCK_NO_EVENTS) in r1[0]
        assert r1[0].endswith("## WHAT CHANGED LAST PERIOD\n"
                              "(first period — nothing has happened in this simulation yet)")
        assert "(none)" not in r1[0]
    # 第 2 轮：日程事件到期 + 上一时段演化摘要（含定性动量线，绝无数字份额）
    assert "[2026-11-05] 事件A发生" in r2[0]
    assert "(first period" not in r2[0]
    assert spc.WORLD_CLOCK_NO_EVENTS not in r2[0]  # 有到期事件 → 不出空段标记
    assert "Momentum: A strengthened this period." in r2[0]
    assert "%" not in r2[0].split("## WHAT CHANGED LAST PERIOD")[1]  # herding guard
    r3 = [n for n in notes if "round 3/3" in n]
    assert r3 and "(first period" not in r3[0]
    assert "Momentum: A strengthened this period." in r3[0]
    assert "%" not in r3[0].split("## WHAT CHANGED LAST PERIOD")[1]

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
    # SIM-6：V2 摘要分段（事件/帖文各自整行封顶）；关 → 旧的平铺摘要
    if v2_on:
        assert digest_rows[1]["digest"].startswith(
            "### Scheduled events last period\n[2026-11-05] 事件A发生\n"
            "### Most-influential actor posts last period (peer claims, unverified)\n")
        assert "### Scheduled events" not in digest_rows[0]["digest"]  # 无事件 → 无事件小节
    else:
        assert digest_rows[1]["digest"].startswith("[2026-11-05] 事件A发生\nActor")
        assert all("###" not in r["digest"] for r in digest_rows)

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
    # REPORT-6：摘要来源状态计数是附加键，与空段标记同一开关（关 → 轨迹键集不变）
    if not markers_on:
        assert "delta_state_counts" not in traj
    else:
        assert traj["delta_state_counts"] == {"stepped": 3, "quiet": 0, "failed": 0}


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
@pytest.mark.parametrize("period_v2,absence_markers", [
    (None, None), ("true", "false"), ("false", "true"), ("false", "false")])
def test_world_evolution_failure_round_completes_with_empty_digest(tmp_path, monkeypatch,
                                                                   period_v2, absence_markers):
    sim_dir = str(tmp_path)
    envs = []
    _patch_runtime(monkeypatch, sim_dir, envs)
    _set_knob(monkeypatch, "SIM_PERIOD_CONTEXT_V2", period_v2)
    _set_knob(monkeypatch, "SIM_ABSENCE_MARKERS", absence_markers)

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
    notes = _world_clock_notes(env)
    assert all(any(f"round {r}/3" in n for n in notes) for r in (1, 2, 3))
    if period_v2 == "false":  # V2 关：无补报块，旧头部逐字节收尾于 WHAT CHANGED 段
        assert all(n.endswith("## WHAT CHANGED LAST PERIOD\n" + _what_changed(n)) for n in notes)
    if absence_markers == "false":
        # 旧占位（开关关，逐字节）：每轮演化失败 → 下一轮世界时钟头回落 "(first period)"
        for n in notes:
            assert _what_changed(n) == "(first period)"
    else:
        # REPORT-6：只有第 1 轮自称首轮；此后失败轮如实标"摘要不可用"，绝不再称首轮
        for n in notes:
            if "round 1/3" in n:
                assert _what_changed(n) == spc.WORLD_CLOCK_FIRST_PERIOD
            else:
                assert _what_changed(n) == spc.WORLD_CLOCK_SUMMARY_UNAVAILABLE
                assert "unavailable in this run" in n
                assert "(first period" not in n
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
    # 名册规模确定：主角 0 必激活 + sampled 配额恰 2 人（3 名候选激活概率均为 1.0，
    # target_count=agents_per_hour_max=2）；采样只决定是哪 2 人，不影响计数。每轮只有
    # agent 0 有效作答 → fallback 2/3 → run 级 0.666667 > DECISION_CHANNEL_FALLBACK_MAX_SHARE(0.5)
    assert [r["decision_validation"]["roster_size"] for r in rows] == [3, 3, 3]
    assert [r["decision_validation"]["fallback_slots"] for r in rows] == [2, 2, 2]
    assert summary["slots"] == 9 and summary["fallback_share"] == 0.666667
    assert traj["round_accounting"]["valid_transitions"] == 3   # 每轮都已提交 …
    assert traj["validity"] == "inconclusive"                    # … 仍因名册覆盖不足降级
    assert traj["validity_reasons"] == ["fallback_share_exceeded"]
    assert traj["forecast_effect"] == "no_update"


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
# 7d) REPORT-6：世界时钟空段具名标记（SIM_ABSENCE_MARKERS，默认开）
# ===========================================================================
_ABSENCE_MARKERS = (spc.WORLD_CLOCK_NO_EVENTS, spc.WORLD_CLOCK_FIRST_PERIOD,
                    spc.WORLD_CLOCK_QUIET_PERIOD, spc.WORLD_CLOCK_SUMMARY_UNAVAILABLE,
                    spc.WORLD_CLOCK_SUMMARY_NOT_PRODUCED)
_EVENT_DUE = [{"date": "2026-11-05", "content": "事件A发生"}]
_ACTOR0_POST = [{"agent_id": 0, "agent_name": "Actor0",
                 "action_args": {"content": "Actor0 strategic move"}}]


def _clock_text(round_num, fired_events, world_delta, **kw):
    """直接调用 _inject_period_context，取单个 agent 收到的世界时钟全文。"""
    agent = _FakeAgent(0, "Actor0")
    env = types.SimpleNamespace(agent_graph=_FakeGraph([agent]))
    rps._inject_period_context(env, [0], round_num, _ROUND_DATES[round_num],
                               _calendar_config()["temporal_config"], fired_events,
                               world_delta, **kw)
    (content, _role), = agent.memory_notes
    return content


def _what_changed(note):
    """WHAT CHANGED LAST PERIOD 段正文（去掉 SIM-6 追加在记忆条末尾的漏报补报块）。"""
    body = note.split("## WHAT CHANGED LAST PERIOD\n", 1)[1]
    return body.split("\n\n" + spc.CATCHUP_HEADING, 1)[0]


def _notes_for_round(env, r):
    return [n for n in _world_clock_notes(env) if f"| round {r}/3 |" in n]


def test_absence_markers_default_on_and_documented():
    from app.config import Config
    assert Config.SIM_ABSENCE_MARKERS is True
    with open(os.path.join(os.path.dirname(_BACKEND), ".env.example"), encoding="utf-8") as f:
        assert "# SIM_ABSENCE_MARKERS=true" in f.read()


def test_absence_markers_carry_no_digits_or_percent():
    """herding guard：空段标记绝不含数字或百分号。"""
    for marker in _ABSENCE_MARKERS:
        assert not any(ch.isdigit() for ch in marker), marker
        assert "%" not in marker, marker


@pytest.mark.parametrize("world_delta", ["", "   ", "Actor1: announced a deal"])
@pytest.mark.parametrize("round_num", [0, 1, 2])
def test_absence_markers_off_is_byte_identical(monkeypatch, round_num, world_delta):
    """开关关：任何 delta_state 下的头部都与旧路径（delta_state=None）逐字节相同。"""
    legacy_quiet = _clock_text(round_num, [], world_delta)
    legacy_event = _clock_text(round_num, _EVENT_DUE, world_delta)
    tail = world_delta.strip() or "(first period)"
    assert legacy_quiet.endswith("## CONFIRMED EVENTS THIS PERIOD\n(none)\n"
                                 "## WHAT CHANGED LAST PERIOD\n" + tail)
    assert legacy_event.endswith("## CONFIRMED EVENTS THIS PERIOD\n[2026-11-05] 事件A发生\n"
                                 "## WHAT CHANGED LAST PERIOD\n" + tail)
    monkeypatch.setenv("SIM_ABSENCE_MARKERS", "false")
    for state in (None, "not_stepped", "stepped", "quiet", "failed", "no_inband"):
        assert _clock_text(round_num, [], world_delta, delta_state=state) == legacy_quiet
        assert _clock_text(round_num, _EVENT_DUE, world_delta, delta_state=state) == legacy_event
    monkeypatch.setenv("SIM_WORLD_DELTA", "false")
    assert (_clock_text(round_num, [], world_delta, delta_state="failed")
            == _clock_text(round_num, [], world_delta))


def test_absence_marker_selection(monkeypatch):
    monkeypatch.delenv("SIM_ABSENCE_MARKERS", raising=False)  # 取 Config 默认（开）

    def wc(round_num, delta, state):
        return _what_changed(_clock_text(round_num, [], delta, delta_state=state))

    for state in ("not_stepped", "stepped", "quiet", "failed", "no_inband"):
        assert wc(0, "", state) == spc.WORLD_CLOCK_FIRST_PERIOD
        assert wc(1, "  Actor1: announced a deal ", state) == "Actor1: announced a deal"
    assert wc(1, "", "quiet") == spc.WORLD_CLOCK_QUIET_PERIOD
    assert wc(2, "", "failed") == spc.WORLD_CLOCK_SUMMARY_UNAVAILABLE
    assert wc(2, "", "not_stepped") == spc.WORLD_CLOCK_SUMMARY_UNAVAILABLE
    # 双平台错峰：另一平台刚步进（stepped）但本平台上一轮末取到的摘要为空 → 失败关闭为不可用
    assert wc(2, "", "stepped") == spc.WORLD_CLOCK_SUMMARY_UNAVAILABLE
    assert wc(2, "", "no_inband") == spc.WORLD_CLOCK_SUMMARY_NOT_PRODUCED
    # CONFIRMED EVENTS 空段 → 具名标记；有到期事件 → 事件原样、无标记
    text = _clock_text(1, [], "", delta_state="failed")
    assert ("## CONFIRMED EVENTS THIS PERIOD\n" + spc.WORLD_CLOCK_NO_EVENTS + "\n") in text
    assert "(none)" not in text
    text = _clock_text(1, _EVENT_DUE, "", delta_state="failed")
    assert "## CONFIRMED EVENTS THIS PERIOD\n[2026-11-05] 事件A发生\n" in text
    assert spc.WORLD_CLOCK_NO_EVENTS not in text
    # 未给 delta_state 的调用方 → 旧文本（开关开也不变）
    assert _clock_text(1, [], "").endswith(
        "## CONFIRMED EVENTS THIS PERIOD\n(none)\n## WHAT CHANGED LAST PERIOD\n(first period)")
    # SIM_WORLD_DELTA 关 → 无 WHAT CHANGED 段，事件空段标记照常
    monkeypatch.setenv("SIM_WORLD_DELTA", "false")
    text = _clock_text(1, [], "", delta_state="failed")
    assert "## WHAT CHANGED LAST PERIOD" not in text
    assert text.endswith("## CONFIRMED EVENTS THIS PERIOD\n" + spc.WORLD_CLOCK_NO_EVENTS)


def test_inband_delta_state_tracks_step_outcomes(tmp_path, monkeypatch):
    """演化器逐次记录摘要来源状态：not_stepped → stepped；deliver 自身异常 → failed。"""
    sim_dir = str(tmp_path)
    _patch_runtime(monkeypatch, sim_dir, [])
    monkeypatch.setattr(dc, "elicit_round", _fake_elicit([]))
    evo = rps._InbandWorldEvolution(_calendar_config(), sim_dir, 1, lambda _m: None)
    assert evo.latest_delta_state() == "not_stepped" and evo.latest_delta() == ""

    evo.deliver("twitter", 0, _ROUND_DATES[0], _ACTOR0_POST, [])
    assert evo.latest_delta_state() == "stepped" and evo.latest_delta()

    def _boom(*a, **k):
        raise RuntimeError("advance 爆炸（故障注入）")

    evo._advance = _boom  # deliver 的缓冲/推进阶段出错 → 其自身异常处理
    evo.deliver("twitter", 1, _ROUND_DATES[1], _ACTOR0_POST, [])
    assert evo.latest_delta_state() == "failed" and evo.latest_delta() == ""
    del evo._advance

    evo.deliver("twitter", 2, _ROUND_DATES[2], _ACTOR0_POST, [])  # 冲刷滞留的第 2 轮 + 第 3 轮
    assert evo.latest_delta_state() == "stepped"
    evo.platform_done("twitter")
    traj = _read_traj(sim_dir)
    # stepped + quiet = 实际步进轮数；failed = 失败次数（此处交付失败的轮次随后仍被步进）
    assert traj["delta_state_counts"] == {"stepped": 3, "quiet": 0, "failed": 1}
    assert len(traj["trajectory"]) - 1 == 3


def test_stepped_delta_state_fails_closed():
    """步进成功后的摘要来源判定：空摘要只在本轮确无可报内容时算 quiet，否则失败关闭为 failed。"""
    state = rps._stepped_delta_state
    post = [{"content": "Actor0 strategic move"}]
    event = [{"date": "2026-11-05", "content": "事件A发生"}]
    lead = {"leader": "A", "direction": "flat"}
    assert state("Momentum: A held this period.", post, event, lead) == "stepped"
    assert state("Actor1: announced a deal", [], [], None) == "stepped"
    assert state("", [], [], None) == "quiet"
    assert state(None, None, None, None) == "quiet"
    # 与 build_world_delta 同口径：空白正文 / 非 dict 事件不算可报内容
    assert state("  \n", [{"content": "  "}], [{"content": ""}, "junk", None], None) == "quiet"
    assert state("", post, [], None) == "failed"
    assert state("", [], event, None) == "failed"
    assert state("", [], [], lead) == "failed"
    assert state("   ", post, event, lead) == "failed"


def test_quiet_period_named_as_quiet(tmp_path, monkeypatch):
    """步进成功且本轮确无可报内容（无帖文、无到期事件、无领先者动量）→ 真实 build_world_delta
    返回空摘要、状态 quiet，下一轮头部标平静期而非首轮；轨迹计数记 quiet。"""
    sim_dir = str(tmp_path)
    logs = []
    _patch_runtime(monkeypatch, sim_dir, [])
    monkeypatch.setattr(dc, "elicit_round", _fake_elicit([]))
    evo = rps._InbandWorldEvolution(_calendar_config(), sim_dir, 1, logs.append)
    real_outcome = evo._ws.outcome
    # 有情景的 WorldState 恒有领先者（动量线恒在）；去掉领先者才构造出真正无可报内容的一期
    monkeypatch.setattr(evo._ws, "outcome", lambda: {**real_outcome(), "leader": None})

    evo.deliver("twitter", 0, _ROUND_DATES[0], [], [])
    assert evo.latest_delta() == "" and evo.latest_delta_state() == "quiet"
    assert not any("摘要生成失败" in m for m in logs)
    note = _clock_text(1, [], evo.latest_delta(), delta_state=evo.latest_delta_state())
    assert _what_changed(note) == spc.WORLD_CLOCK_QUIET_PERIOD
    assert "(first period" not in note
    evo.platform_done("twitter")
    traj = _read_traj(sim_dir)
    assert traj["delta_state_counts"] == {"stepped": 0, "quiet": 1, "failed": 0}
    assert len(traj["trajectory"]) - 1 == 1


def test_empty_digest_with_content_fails_closed(tmp_path, monkeypatch, capsys):
    """步进成功、本轮有帖文与领先者动量，摘要却为空（build_world_delta 吞掉自身异常的唯一
    情形）→ 失败关闭：下一轮标"摘要不可用"，绝不声称平静期；轨迹计数记 failed 并告警。"""
    sim_dir = str(tmp_path)
    envs, calls = [], []
    _patch_runtime(monkeypatch, sim_dir, envs)
    monkeypatch.setattr(dc, "elicit_round", _fake_elicit(calls))
    monkeypatch.setattr("app.services.world_delta.build_world_delta", lambda *a, **k: "")
    _run(_calendar_config(), sim_dir)
    env = envs[0]

    assert len(calls) == 3  # 每轮都成功 elicit 并步进
    r1 = _notes_for_round(env, 1)
    assert r1 and all(_what_changed(n) == spc.WORLD_CLOCK_FIRST_PERIOD for n in r1)
    for r in (2, 3):
        notes = _notes_for_round(env, r)
        assert notes
        for n in notes:
            assert _what_changed(n) == spc.WORLD_CLOCK_SUMMARY_UNAVAILABLE
            assert "unavailable in this run" in n
            assert spc.WORLD_CLOCK_QUIET_PERIOD not in n and "(first period" not in n
    traj = _read_traj(sim_dir)
    assert traj["delta_state_counts"] == {"stepped": 0, "quiet": 0, "failed": 3}
    assert len(traj["trajectory"]) - 1 == 3  # WorldState 照常步进，只是摘要不可用
    assert capsys.readouterr().out.count("摘要生成失败") == 3


def test_no_inband_named_as_not_produced(tmp_path, monkeypatch):
    """in-band 演化关闭（SIM_DECISION_CHANNEL_INBAND=false）→ 第 2 轮起标"本次运行不产出摘要"。"""
    sim_dir = str(tmp_path)
    envs = []
    _patch_runtime(monkeypatch, sim_dir, envs)
    monkeypatch.setenv("SIM_DECISION_CHANNEL_INBAND", "false")
    _run(_calendar_config(), sim_dir)
    env = envs[0]

    r1 = _notes_for_round(env, 1)
    assert r1 and all(_what_changed(n) == spc.WORLD_CLOCK_FIRST_PERIOD for n in r1)
    for r in (2, 3):
        notes = _notes_for_round(env, r)
        assert notes
        for n in notes:
            assert _what_changed(n) == spc.WORLD_CLOCK_SUMMARY_NOT_PRODUCED
            assert "not produced in this run" in n and "(first period" not in n
    assert not os.path.exists(os.path.join(sim_dir, "world_state_trajectory.json"))


def test_delta_state_counts_mixed_run(tmp_path, monkeypatch):
    """第 1 轮有摘要、第 2 轮 elicit 失败、第 3 轮步进成功但摘要生成失败（有内容却空摘要）
    → 头部与轨迹计数逐一对应（平静期计数见 test_quiet_period_named_as_quiet）。"""
    import app.services.world_delta as wd

    sim_dir = str(tmp_path)
    envs, calls = [], []
    _patch_runtime(monkeypatch, sim_dir, envs)
    ok = _fake_elicit(calls)

    def _elicit(roster, period_ctx):
        if period_ctx.get("round_num") == 2:
            raise RuntimeError("elicit 爆炸（第 2 轮故障注入）")
        return ok(roster, period_ctx)

    real_build = wd.build_world_delta
    built = []

    def _build(*a, **k):  # 只在步进成功的轮被调用：第 1 轮真实摘要，第 3 轮空摘要
        built.append(1)
        return real_build(*a, **k) if len(built) == 1 else ""

    monkeypatch.setattr(dc, "elicit_round", _elicit)
    monkeypatch.setattr(wd, "build_world_delta", _build)
    _run(_calendar_config(), sim_dir)
    env = envs[0]

    r2, r3 = _notes_for_round(env, 2), _notes_for_round(env, 3)
    assert r2 and all("Momentum: A strengthened this period." in _what_changed(n) for n in r2)
    assert r3 and all(_what_changed(n) == spc.WORLD_CLOCK_SUMMARY_UNAVAILABLE for n in r3)
    traj = _read_traj(sim_dir)
    counts = traj["delta_state_counts"]
    assert counts == {"stepped": 1, "quiet": 0, "failed": 2}
    # 第 2 轮步进失败（不入轨迹）；第 3 轮照常步进，只是摘要不可用 → 计 failed
    assert [row["round"] for row in traj["trajectory"][1:]] == [1, 3]
    assert sum(counts.values()) == 3  # 每个运行轮恰计一次


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


# ===========================================================================
# 9) SIM-5：定时事件来源标注 / 同帖者同轮多事件 / 缺发帖者记日志 / 情感投递遥测
# ===========================================================================
def _event_feed_posts(sim_dir):
    """FakeEnv 为 ManualAction（定时事件）写的 create_post trace 行内容（有机行除外）。"""
    conn = sqlite3.connect(os.path.join(sim_dir, "twitter_simulation.db"))
    rows = conn.execute("SELECT action, info FROM trace").fetchall()
    conn.close()
    posts = []
    for action, info in rows:
        content = json.loads(info).get("content") or ""
        if action == "create_post" and "strategic move" not in content:
            posts.append(content)
    return posts


def _logged_event_rows(sim_dir):
    return [e for e in _read_events(sim_dir)
            if (e.get("action_args") or {}).get("is_scheduled_event")]


def test_same_poster_events_in_one_round_all_fire(tmp_path, monkeypatch):
    sim_dir = str(tmp_path)
    envs = []
    _patch_runtime(monkeypatch, sim_dir, envs)
    monkeypatch.setenv("SIM_DECISION_CHANNEL_INBAND", "false")
    cfg = _calendar_config()
    cfg["event_config"]["scheduled_events"] = [
        {"round": 1, "date": "2026-11-05", "content": "[2026-11-05] 事件A发生", "poster_agent_id": 0},
        {"round": 1, "date": "2026-11-20", "content": "[2026-11-20] 事件B发生", "poster_agent_id": 0},
    ]
    _run(cfg, sim_dir)

    posted = _event_feed_posts(sim_dir)
    assert len(posted) == 2                               # 此前按 agent 覆盖只发出最后一条
    logged = _logged_event_rows(sim_dir)
    assert [(e["round"], e["agent_id"]) for e in logged] == [(2, 0), (2, 0)]
    assert sorted(e["action_args"]["content"] for e in logged) == sorted(posted)
    assert posted[0].endswith("事件A发生") and posted[1].endswith("事件B发生")

    # 情感状态行以 SYSTEM 记录注入、被 camel 丢弃——摘要如实记录（SIM_AGENT_DYNAMICS 默认开）
    with open(os.path.join(sim_dir, "twitter_dynamics_summary.json"), encoding="utf-8") as f:
        summary = json.load(f)
    assert summary["prompt_delivery"] == "system_record_dropped_by_context_creator"
    assert {"rounds_observed", "rounds_with_received_signal", "active"} <= set(summary)


@pytest.mark.parametrize("flag", [None, "false"])
def test_event_posts_labelled_by_default_and_verbatim_when_off(tmp_path, monkeypatch, flag):
    sim_dir = str(tmp_path)
    envs = []
    _patch_runtime(monkeypatch, sim_dir, envs)
    monkeypatch.setenv("SIM_DECISION_CHANNEL_INBAND", "false")
    if flag is not None:
        monkeypatch.setenv("SIM_EVENT_PROVENANCE", flag)
    _run(_calendar_config(), sim_dir)

    logged = _logged_event_rows(sim_dir)
    assert len(logged) == 1
    args = logged[0]["action_args"]
    if flag is None:
        assert args["content"] == ("[WORLD EVENT · scheduled on the research timeline · "
                                   "not a statement by any actor] [2026-11-05] 事件A发生")
        assert args["event_provenance"] == "research_timeline"
    else:
        assert args == {"content": "[2026-11-05] 事件A发生", "is_scheduled_event": True}
    assert _event_feed_posts(sim_dir) == [args["content"]]  # 帖文与落账同一字符串
    # 世界时钟的事件段仍是研究时间线原文（不带 feed 来源前缀；SIM-6 默认标题为预期事件）
    notes = [n for n in _world_clock_notes(envs[0]) if "round 2/3" in n]
    assert notes and (spc.SCHEDULED_EVENTS_HEADING_V2 + "\n[2026-11-05] 事件A发生") in notes[0]


def test_event_without_poster_or_content_is_skipped_and_logged(tmp_path, monkeypatch, capsys):
    sim_dir = str(tmp_path)
    envs = []
    _patch_runtime(monkeypatch, sim_dir, envs)
    monkeypatch.setenv("SIM_DECISION_CHANNEL_INBAND", "false")
    cfg = _calendar_config()
    cfg["event_config"]["scheduled_events"] = [
        {"round": 1, "date": "2026-11-05", "content": "[2026-11-05] 事件A发生", "poster_agent_id": None},
        {"round": 1, "date": "2026-11-06", "content": "", "poster_agent_id": 1},
        # poster id no longer in the agent graph (pruned/renumbered): get_agent raises
        {"round": 1, "date": "2026-11-07", "content": "[2026-11-07] 事件C发生", "poster_agent_id": 9},
    ]
    _run(cfg, sim_dir)

    assert _event_feed_posts(sim_dir) == []
    assert _logged_event_rows(sim_dir) == []
    out = capsys.readouterr().out
    assert "第 2 轮定时事件缺发帖者，跳过: '[2026-11-05] 事件A发生'" in out
    assert "第 2 轮定时事件缺内容，跳过: '2026-11-06'" in out
    assert "第 2 轮定时事件（发帖者 9）注入失败，跳过: KeyError: 9" in out


# ===========================================================================
# 10) SIM-6：逐时段上下文如实送达（SIM_PERIOD_CONTEXT_V2，默认开）
# ===========================================================================
def _script_active(monkeypatch, schedule):
    """get_active_agents_for_round 替身：schedule[round_num]（0 基）= 本轮活跃 agent id。"""

    def _active(env, config, current_hour, round_num, last_active_ids=None, calendar=False):
        return [(aid, env.agent_graph.get_agent(aid)) for aid in schedule[round_num]]

    monkeypatch.setattr(rps, "get_active_agents_for_round", _active)


def _agent_notes(env, aid):
    return [c for c, _r in env.agent_graph.get_agent(aid).memory_notes
            if c.startswith("# WORLD CLOCK")]


def test_period_context_v2_off_is_legacy(tmp_path, monkeypatch):
    """两个开关都关：agent 可见文本逐字节是旧文本——CONFIRMED 标题、"(none)"/"(first period)"、
    无补报块、无落后标注、平铺摘要；死轮事件不暂存。"""
    sim_dir = str(tmp_path)
    envs, calls = [], []
    _patch_runtime(monkeypatch, sim_dir, envs)
    monkeypatch.setattr(dc, "elicit_round", _fake_elicit(calls))
    monkeypatch.setenv("SIM_PERIOD_CONTEXT_V2", "false")
    monkeypatch.setenv("SIM_ABSENCE_MARKERS", "false")
    _script_active(monkeypatch, {0: [0, 1], 1: [0, 1], 2: [0, 1, 2]})
    _run(_calendar_config(), sim_dir)
    env = envs[0]

    r1 = _notes_for_round(env, 1)
    assert r1 and all(n.endswith("## CONFIRMED EVENTS THIS PERIOD\n(none)\n"
                                 "## WHAT CHANGED LAST PERIOD\n(first period)") for n in r1)
    r2 = _notes_for_round(env, 2)
    assert r2 and all("## CONFIRMED EVENTS THIS PERIOD\n[2026-11-05] 事件A发生\n"
                      "## WHAT CHANGED LAST PERIOD\nActor" in n for n in r2)
    notes = _world_clock_notes(env)
    for n in notes:
        for v2_text in ("SCHEDULED EVENTS THIS PERIOD", "EARLIER SCHEDULED EVENTS",
                        "latest available digest covers", "SCENARIO ASSUMPTION", "###",
                        "\n\n"):
            assert v2_text not in n
    # 旧的平铺摘要（无分段标题）
    digest_rows = _read_jsonl(os.path.join(sim_dir, "world_digest.jsonl"))
    assert digest_rows[1]["digest"].startswith("[2026-11-05] 事件A发生\nActor")
    assert all("###" not in r["digest"] for r in digest_rows)


def test_sampled_agent_gets_missed_event_catchup(tmp_path, monkeypatch):
    """sampled agent 2 缺席第 1、2 轮（事件在第 2 轮触发）→ 第 3 轮首次激活时补报；
    主角 0 每轮在场，从无补报块；补报在注入成功后才记为已告知。"""
    sim_dir = str(tmp_path)
    envs, calls = [], []
    _patch_runtime(monkeypatch, sim_dir, envs)
    monkeypatch.setattr(dc, "elicit_round", _fake_elicit(calls))
    monkeypatch.delenv("SIM_PERIOD_CONTEXT_V2", raising=False)
    _script_active(monkeypatch, {0: [0, 1], 1: [0, 1], 2: [0, 1, 2]})
    _run(_calendar_config(), sim_dir)
    env = envs[0]

    (note2,) = _agent_notes(env, 2)
    assert "| round 3/3 |" in note2
    block = note2.split("\n\n")[-1]
    assert block == ("## EARLIER SCHEDULED EVENTS YOU HAVE NOT BEEN BRIEFED ON\n"
                     "[2026-11-05] 事件A发生")
    assert "EARLIER SCHEDULED EVENTS" in note2 and "[2026-11-05] 事件A发生" in note2
    # 补报块追加在 WHAT CHANGED 段之后（空一行），头部其余部分不变
    assert note2.index(spc.WHAT_CHANGED_HEADING) < note2.index(spc.CATCHUP_HEADING)
    for aid in (0, 1):
        notes = _agent_notes(env, aid)
        assert len(notes) == 3
        assert all("EARLIER SCHEDULED EVENTS" not in n for n in notes)
    # 本期事件在第 2 轮的记忆条里仍以预期事件标题出现（agent 0/1 已被告知）
    assert (spc.SCHEDULED_EVENTS_HEADING_V2 + "\n[2026-11-05] 事件A发生") in _agent_notes(env, 0)[1]


def test_catchup_budget_knob_and_failed_injection_not_marked(monkeypatch):
    """SIM_EVENT_CATCHUP_MAX_CHARS 非法 → 默认 1200；注入失败的 agent 不记为已告知（下轮重补）。"""
    monkeypatch.setenv("SIM_EVENT_CATCHUP_MAX_CHARS", "lots")
    cu = rps._build_event_catchup(_calendar_config()["event_config"], lambda _m: None)
    assert cu is not None and cu._max_chars == 1200
    monkeypatch.setenv("SIM_EVENT_CATCHUP_MAX_CHARS", "80")
    cu = rps._build_event_catchup(_calendar_config()["event_config"], lambda _m: None)
    assert cu._max_chars == 80

    class _Broken(_FakeAgent):
        def update_memory(self, msg, role):
            raise RuntimeError("memory full")

    good, broken = _FakeAgent(0, "Actor0"), _Broken(1, "Actor1")
    env = types.SimpleNamespace(agent_graph=_FakeGraph([good, broken]))
    state = {}
    rps._world_clock_round(
        env, [(0, good), (1, broken)], 2, _ROUND_DATES[2], _calendar_config()["temporal_config"],
        _calendar_config()["event_config"], "", 0, {}, None, cu, state,
        v2=True, response_step=False, language="")
    assert "EARLIER SCHEDULED EVENTS" in good.memory_notes[0][0]
    assert cu.missed(0, 3) == [] and len(cu.missed(1, 3)) == 1
    assert "period_context" not in state  # 回应阶段关 → 不给本期上下文


@pytest.mark.parametrize("period_v2", ["true", "false"])
def test_dead_round_event_carried_into_next_digest(tmp_path, monkeypatch, period_v2):
    """事件轮（第 2 轮）全员缺席：V2 开 → 事件随心跳暂存，进入下一次步进（第 3 轮）的摘要；
    轨迹行数不变（死轮从不步进）。第 3 轮头部注明摘要覆盖的是更早时段，缺席者补报事件。"""
    sim_dir = str(tmp_path)
    envs, calls = [], []
    _patch_runtime(monkeypatch, sim_dir, envs)
    monkeypatch.setattr(dc, "elicit_round", _fake_elicit(calls))
    monkeypatch.setenv("SIM_PERIOD_CONTEXT_V2", period_v2)
    _script_active(monkeypatch, {0: [0, 1], 1: [], 2: [0, 1]})
    _run(_calendar_config(), sim_dir)
    env = envs[0]

    digest_rows = _read_jsonl(os.path.join(sim_dir, "world_digest.jsonl"))
    assert [r["round"] for r in digest_rows] == [1, 3]
    traj = _read_traj(sim_dir)
    assert [row["round"] for row in traj["trajectory"]] == [0, 1, 3]  # 无新增轨迹行
    r3 = _notes_for_round(env, 3)
    assert len(r3) == 2
    if period_v2 == "true":
        assert digest_rows[1]["digest"].startswith(
            "### Scheduled events last period\n[2026-11-05] 事件A发生\n")
        for n in r3:
            # 摘要出自第 1 轮（2026-Q3），不是刚过去的死轮时段
            assert (spc.WHAT_CHANGED_HEADING + "\n(latest available digest covers 2026-Q3; "
                    "no digest of the most recent period is available)\n###") in n
            assert n.endswith(spc.CATCHUP_HEADING + "\n[2026-11-05] 事件A发生")
    else:
        assert "事件A发生" not in digest_rows[1]["digest"]
        assert all("latest available digest covers" not in n and "EARLIER" not in n for n in r3)


def test_inject_period_context_v2_direct():
    """v2：预期事件标题 + 情景标注 + 落后标注 + 逐 agent 补报；返回成功注入的 id；
    v2=False 与不带新参数的旧调用逐字节相同。"""
    events = [{"date": "2026-11-05", "content": "事件A发生"},
              {"date": "2026-11-20", "content": "Export ban extended",
               "is_scenario_injection": True}]
    legacy = _clock_text(2, events, "Actor1: deal", delta_state="stepped")
    assert _clock_text(2, events, "Actor1: deal", delta_state="stepped", v2=False,
                       delta_stale_label="2026-Q3") == legacy  # 落后标注只在 v2 下渲染
    assert "## CONFIRMED EVENTS THIS PERIOD\n[2026-11-05] 事件A发生\n[2026-11-20] Export" in legacy

    note = _clock_text(2, events, "Actor1: deal", delta_state="stepped", v2=True,
                       delta_stale_label="2026-Q3", per_agent_suffix={0: "CATCH", 5: "other"})
    assert note.startswith(legacy.split("## CONFIRMED EVENTS")[0])  # 框架行不变
    assert note.endswith(
        spc.SCHEDULED_EVENTS_HEADING_V2 + "\n[2026-11-05] 事件A发生\n"
        "SCENARIO ASSUMPTION (what-if, not observed): [2026-11-20] Export ban extended\n"
        "## WHAT CHANGED LAST PERIOD\n(latest available digest covers 2026-Q3; no digest of "
        "the most recent period is available)\nActor1: deal\n\nCATCH")
    assert "CONFIRMED" not in note

    agents = [_FakeAgent(i, f"Actor{i}") for i in range(2)]
    env = types.SimpleNamespace(agent_graph=_FakeGraph(agents))
    ids = rps._inject_period_context(env, [0, 1, 7], 1, _ROUND_DATES[1],
                                     _calendar_config()["temporal_config"], [], "", v2=True,
                                     delta_state="failed")
    assert ids == [0, 1]  # 7 不在图中 → 跳过、不计入
    assert rps._inject_period_context(env, [0], 1, None, {}, [], "") == []


def test_inject_period_context_v2_renderer_failure_falls_back_to_legacy(monkeypatch):
    legacy = _clock_text(1, _EVENT_DUE, "", delta_state="failed")
    real = spc.render_event_lines

    def _flaky(events, *, markers, scenario_labels=True):
        if scenario_labels:
            raise RuntimeError("renderer 爆炸（故障注入）")
        return real(events, markers=markers, scenario_labels=False)

    monkeypatch.setattr(spc, "render_event_lines", _flaky)
    assert _clock_text(1, _EVENT_DUE, "", delta_state="failed", v2=True) == legacy


def test_reaction_period_context_shares_the_world_clock_renderer(monkeypatch):
    """回应阶段本期上下文：与世界时钟同一渲染器——情景标注、落后标注、具名占位；
    SIM_WORLD_DELTA 关 → 无变化段；SIM_ABSENCE_MARKERS 关 → 旧占位。"""
    monkeypatch.delenv("SIM_ABSENCE_MARKERS", raising=False)
    monkeypatch.delenv("SIM_WORLD_DELTA", raising=False)
    due = [{"date": "2026-12-01", "content": "Export ban extended", "is_scenario_injection": True}]
    ctx = rps._reaction_period_context(due, "Actor1: deal", "stepped", 2, "2026-Q3")
    assert ctx == (
        "## THIS PERIOD — scheduled events (research timeline)\n"
        "SCENARIO ASSUMPTION (what-if, not observed): [2026-12-01] Export ban extended\n"
        "## WHAT CHANGED LAST PERIOD\n(latest available digest covers 2026-Q3; no digest of "
        "the most recent period is available)\nActor1: deal")
    assert rps._reaction_period_context([], "", "failed", 2, "").endswith(
        spc.WORLD_CLOCK_NO_EVENTS + "\n## WHAT CHANGED LAST PERIOD\n"
        + spc.WORLD_CLOCK_SUMMARY_UNAVAILABLE)
    monkeypatch.setenv("SIM_ABSENCE_MARKERS", "false")
    assert rps._reaction_period_context([], "", "failed", 2, "").endswith(
        "(none)\n## WHAT CHANGED LAST PERIOD\n(first period)")
    monkeypatch.setenv("SIM_WORLD_DELTA", "false")
    assert rps._reaction_period_context([], "x", "stepped", 2, "") == (
        spc.THIS_PERIOD_HEADING + "\n(none)")


def test_period_stale_label():
    periods = dict(enumerate(_ROUND_DATES))
    assert rps._period_stale_label("digest", 1, 2, periods) == "2026-Q3"
    assert rps._period_stale_label("digest", 2, 2, periods) == ""      # 正是上一时段的摘要
    assert rps._period_stale_label("digest", 0, 2, periods) == ""      # 尚未步进
    assert rps._period_stale_label("   ", 1, 2, periods) == ""         # 无摘要 → 由占位负责
    assert rps._period_stale_label("digest", 3, 2, periods) == ""
    assert rps._period_stale_label("digest", 1, 2, {}) == "round 1"    # 缺时段表 → 轮号
    assert rps._period_stale_label("digest", "x", 2, periods) == ""


def _evo(sim_dir, monkeypatch, platforms=1):
    _patch_runtime(monkeypatch, sim_dir, [])
    monkeypatch.setattr(dc, "elicit_round", _fake_elicit([]))
    return rps._InbandWorldEvolution(_calendar_config(), sim_dir, platforms, lambda _m: None)


def test_inband_heartbeat_events_dedup_into_existing_buffer(tmp_path, monkeypatch):
    """双平台：twitter 交付第 1 轮（含事件）、reddit 该轮死轮心跳带同一事件 → 去重并入同一缓冲。"""
    monkeypatch.delenv("SIM_PERIOD_CONTEXT_V2", raising=False)
    sim_dir = str(tmp_path)
    evo = _evo(sim_dir, monkeypatch, platforms=2)
    ev = {"round": 0, "date": "2026-08-01", "content": "[2026-08-01] 事件0"}
    evo.deliver("twitter", 0, _ROUND_DATES[0], _ACTOR0_POST, [ev])
    assert evo.latest_delta_round() == 0 and 0 in evo._pending  # 等 reddit 水位
    evo.heartbeat("reddit", 0, [dict(ev), dict(ev)])
    assert evo._carry_events == {}
    rows = _read_jsonl(os.path.join(sim_dir, "world_digest.jsonl"))
    assert [r["round"] for r in rows] == [1]
    assert rows[0]["digest"].count("[2026-08-01] 事件0") == 1
    assert evo.latest_delta_round() == 1


def test_inband_carried_events_merge_only_into_a_later_round(tmp_path, monkeypatch):
    monkeypatch.delenv("SIM_PERIOD_CONTEXT_V2", raising=False)
    sim_dir = str(tmp_path)
    evo = _evo(sim_dir, monkeypatch)
    ev = {"round": 1, "date": "2026-11-05", "content": "[2026-11-05] 事件A发生"}
    evo.heartbeat("twitter", 1, [ev, ev])      # 全平台死轮：无缓冲 → 暂存
    assert evo._carry_events == {1: [ev, ev]} and evo.latest_delta_round() == 0
    evo.deliver("twitter", 0, _ROUND_DATES[0], _ACTOR0_POST, [])
    assert evo._carry_events == {1: [ev, ev]}  # 更早的轮次不并入
    evo.deliver("twitter", 2, _ROUND_DATES[2], _ACTOR0_POST, [ev])
    assert evo._carry_events == {}
    rows = _read_jsonl(os.path.join(sim_dir, "world_digest.jsonl"))
    assert [r["round"] for r in rows] == [1, 3]
    assert "事件A发生" not in rows[0]["digest"]
    assert rows[1]["digest"].count("[2026-11-05] 事件A发生") == 1  # 与本轮同一事件去重
    evo.platform_done("twitter")
    assert [row["round"] for row in _read_traj(sim_dir)["trajectory"]] == [0, 1, 3]


def test_inband_latest_delta_round_tracks_successful_steps(tmp_path, monkeypatch):
    monkeypatch.delenv("SIM_PERIOD_CONTEXT_V2", raising=False)
    sim_dir = str(tmp_path)
    evo = _evo(sim_dir, monkeypatch)
    assert evo.latest_delta_round() == 0
    evo.deliver("twitter", 0, _ROUND_DATES[0], _ACTOR0_POST, [])
    assert (evo.latest_delta_round(), evo.latest_delta_state()) == (1, "stepped")
    evo.heartbeat("twitter", 1)
    assert evo.latest_delta_round() == 1

    def _boom(roster, period_ctx):
        raise RuntimeError("elicit 爆炸（故障注入）")

    monkeypatch.setattr(dc, "elicit_round", _boom)
    evo.deliver("twitter", 2, _ROUND_DATES[2], _ACTOR0_POST, [])
    # 失败步进不改轮号；摘要清空、状态 failed（世界时钟据此标"不可用"而非落后）
    assert (evo.latest_delta_round(), evo.latest_delta_state(), evo.latest_delta()) == (
        1, "failed", "")


def test_inband_v2_off_ignores_heartbeat_events(tmp_path, monkeypatch):
    monkeypatch.setenv("SIM_PERIOD_CONTEXT_V2", "false")
    sim_dir = str(tmp_path)
    evo = _evo(sim_dir, monkeypatch)
    ev = {"round": 1, "date": "2026-11-05", "content": "[2026-11-05] 事件A发生"}
    evo.heartbeat("twitter", 1, [ev])
    assert evo._carry_events == {}
    evo.deliver("twitter", 2, _ROUND_DATES[2], _ACTOR0_POST, [])
    rows = _read_jsonl(os.path.join(sim_dir, "world_digest.jsonl"))
    assert "事件A发生" not in rows[0]["digest"] and "###" not in rows[0]["digest"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-x", "-q"]))
