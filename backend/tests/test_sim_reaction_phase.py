"""SIM-REACT：每轮发帖后的回应阶段 + 模拟输出语言。

取证（pipe_6c4190b31f0b / sim_0170a91d15a3，GLM-5.3）：OASIS 每个 agent 每轮只有一次模型调用
（SocialAgent max_iteration=1），世界时钟又把它定性为本时段的通告——19 轮 Twitter 有机动作
200 帖 : 9 评论、Reddit 190 : 37；英文运行的种子帖/热点话题却是中文。这些测试钉住：
  1) 候选挑选：点名/回复自己的帖子优先、不重复自己、同帖回应者分散；
  2) 帖子线程读取：引用帖取引用语、纯转发跳过、评论按序挂载；
  3) 回应提示：主帖原文、已有回复、原因、作答要求、语言、平台工具；
  4) 回应执行：辅助 agent 只拿到互动工具（没有 create_post），动作落 actions.jsonl、
     回写简短 USER 记忆，下一轮作者能回应别人的回复；
  5) 轮循环集成：真实 run_twitter_simulation 每轮都跑回应阶段并计入 round_end；
  6) 采样赞默认随回应阶段关闭；输出语言判定；世界时钟附加说明；
  7) 配置生成：输出语言判定、英文世界简报标题、事件配置提示的语言要求、to_dict 字段。
"""

import asyncio
import json
import os
import re
import sqlite3
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_BACKEND, "scripts")
for _p in (_BACKEND, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import random  # noqa: E402

import run_parallel_simulation as rps  # noqa: E402
from action_logger import PlatformActionLogger  # noqa: E402
from camel.types import OpenAIBackendRole  # noqa: E402
from oasis import ManualAction  # noqa: E402
from oasis.social_platform.database import create_db  # noqa: E402

from app.services.simulation_config_generator import (  # noqa: E402
    SimulationConfigGenerator,
    SimulationParameters,
)

AGENTS = {
    0: {"name": "US Department of Commerce / BIS", "stance": "opposing",
        "topics": ["export controls", "Entity List"], "gains": "controls slow rival programs"},
    1: {"name": "Origin Quantum", "stance": "supportive",
        "topics": ["superconducting", "domestic supply chain"], "gains": "domestic refrigerators"},
    2: {"name": "IBM", "stance": "supportive",
        "topics": ["fault-tolerant roadmap", "qLDPC"], "gains": "Starling delivers at spec"},
}
AGENT_NAMES = {aid: a["name"] for aid, a in AGENTS.items()}


def _config():
    return {
        "simulation_requirement": "Forecast quantum computing in the US, China and the EU through 2040.",
        "agent_configs": [
            {"agent_id": aid, "entity_name": a["name"], "stance": a["stance"],
             "interested_topics": a["topics"], "gains_if": a["gains"], "loses_if": ""}
            for aid, a in AGENTS.items()
        ],
    }


# ---------------------------------------------------------------------------
# OASIS 真实库表（create_db）上的帖子/评论/关注/trace 构造
# ---------------------------------------------------------------------------
def _make_db(path):
    create_db(str(path))
    conn = sqlite3.connect(str(path))
    for aid, a in AGENTS.items():
        conn.execute(
            "INSERT INTO user (user_id, agent_id, user_name, name, bio, created_at, "
            "num_followings, num_followers) VALUES (?, ?, ?, ?, '', '2026-01-01', 0, 0)",
            (aid, aid, f"user{aid}", a["name"]),
        )
    conn.commit()
    conn.close()
    return str(path)


def _add_post(db, author, content, original=None, quote=None):
    conn = sqlite3.connect(db)
    cur = conn.execute(
        "INSERT INTO post (user_id, original_post_id, content, quote_content, created_at, "
        "num_likes, num_dislikes, num_shares) VALUES (?, ?, ?, ?, '2026-01-01', 0, 0, 0)",
        (author, original, content, quote),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def _add_comment(db, author, post_id, content, trace=True):
    conn = sqlite3.connect(db)
    cur = conn.execute(
        "INSERT INTO comment (post_id, user_id, content, created_at, num_likes, num_dislikes) "
        "VALUES (?, ?, ?, '2026-01-01', 0, 0)",
        (post_id, author, content),
    )
    cid = cur.lastrowid
    if trace:
        conn.execute(
            "INSERT INTO trace (user_id, created_at, action, info) VALUES (?, '2026-01-01', ?, ?)",
            (author, "create_comment",
             json.dumps({"post_id": post_id, "content": content, "comment_id": cid})),
        )
    conn.commit()
    conn.close()
    return cid


def _add_follow(db, follower, followee):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO follow (follower_id, followee_id, created_at) VALUES (?, ?, '2026-01-01')",
        (follower, followee),
    )
    conn.commit()
    conn.close()


def _trace_rowid(db):
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT MAX(rowid) FROM trace").fetchone()
    conn.close()
    return int(row[0] or 0)


# ---------------------------------------------------------------------------
# 1) 候选挑选（纯函数）
# ---------------------------------------------------------------------------
def _thread(pid, author, content, comments=(), recent=True):
    return {"post_id": pid, "author_id": author, "content": content, "quoted": "",
            "quoted_author_id": None, "recent": recent,
            "comments": [{"comment_id": i + 1, "author_id": a, "content": c}
                         for i, (a, c) in enumerate(comments)]}


def test_candidates_rank_mentions_first_and_skip_own_post_without_replies():
    profiles = rps._build_reaction_profiles(_config())
    threads = {
        1: _thread(1, 1, "Origin Quantum ships domestic dilution refrigerators despite BIS rules."),
        2: _thread(2, 2, "IBM says the Starling roadmap remains on schedule."),
        3: _thread(3, 0, "BIS adds three quantum firms to the Entity List."),
    }
    cands = rps.select_reaction_candidates(0, threads, profiles, set(), {})
    assert [c["post_id"] for c in cands] == [1, 2]      # 自己的帖子（无人回复）不入选
    assert "it mentions you" in cands[0]["reasons"]      # 缩写 BIS 被识别为点名


def test_candidates_reply_back_to_own_post_and_do_not_repeat_self():
    profiles = rps._build_reaction_profiles(_config())
    threads = {
        # 别人回复了 Origin 的帖子，Origin 尚未回应 → 高优先级
        1: _thread(1, 1, "Origin Quantum ships domestic refrigerators.",
                   comments=[(0, "BIS will review whether these units used controlled parts.")]),
        # Origin 已回应过、之后无人接话 → 不重复自己
        2: _thread(2, 2, "IBM says the Starling roadmap remains on schedule.",
                   comments=[(1, "Origin: our roadmap is faster.")]),
        # Origin 回应过、但 IBM 又回复了 → 讨论延续，入选
        3: _thread(3, 2, "IBM: qLDPC codes cut overhead tenfold.",
                   comments=[(1, "Origin: we replicated it."), (2, "IBM: show the data.")]),
    }
    cands = rps.select_reaction_candidates(1, threads, profiles, set(), {})
    ids = [c["post_id"] for c in cands]
    assert ids[0] == 1 and "other actors replied to your post" in cands[0]["reasons"]
    assert 2 not in ids
    assert 3 in ids
    assert "new replies in a discussion you joined" in next(c for c in cands if c["post_id"] == 3)["reasons"]


def test_candidates_spread_reactors_across_posts():
    profiles = rps._build_reaction_profiles(_config())
    threads = {
        10: _thread(10, 2, "IBM announces a new cryogenic plant."),
        11: _thread(11, 2, "IBM opens a quantum center in Europe."),
    }
    first = rps.select_reaction_candidates(1, threads, profiles, set(), {})
    assert first[0]["post_id"] == 11                     # 同分：新帖优先
    assigned = {11: 1}
    second = rps.select_reaction_candidates(0, threads, profiles, set(), assigned)
    assert second[0]["post_id"] == 10                    # 已分配过的帖被分散惩罚


def test_name_aliases_are_precise():
    aliases = rps._reaction_name_aliases("Chinese government (NDRC/MOST)")
    assert ("NDRC", True) in aliases and ("MOST", True) in aliases
    assert not rps._text_mentions("most analysts expect delays", aliases)   # 小写 most 不算点名
    assert rps._text_mentions("MOST and NDRC issued a plan", aliases)
    assert not any(alias == "Chinese" for alias, _cs in aliases)            # 泛称首词不单列
    google = rps._reaction_name_aliases("Google Quantum AI")
    assert rps._text_mentions("Google's Willow chip", google)
    ostp = rps._reaction_name_aliases("White House OSTP / NQI")
    assert rps._text_mentions("OSTP guidance", ostp) and not rps._text_mentions("a white paper", ostp)


# ---------------------------------------------------------------------------
# 2) 线程读取（真实 OASIS 表结构）
# ---------------------------------------------------------------------------
def test_fetch_threads_handles_quotes_reposts_and_comments(tmp_path):
    db = _make_db(tmp_path / "t.db")
    p1 = _add_post(db, 2, "IBM: Starling ships in 2029.")
    p2 = _add_post(db, 1, "IBM: Starling ships in 2029.", original=p1,
                   quote="Origin: we will match that by 2028.")
    _add_post(db, 0, "", original=p1)                    # 纯转发
    _add_comment(db, 0, p1, "BIS: first comment", trace=False)
    _add_comment(db, 1, p1, "Origin: second comment", trace=False)
    threads = rps._fetch_reaction_threads(db, 0, p1)
    assert set(threads) == {p1, p2}                      # 纯转发不是可回应的新发言
    assert threads[p2]["content"] == "Origin: we will match that by 2028."
    assert threads[p2]["quoted"] == "IBM: Starling ships in 2029."
    assert threads[p2]["quoted_author_id"] == 2
    assert [c["author_id"] for c in threads[p1]["comments"]] == [0, 1]
    assert threads[p1]["recent"] is False and threads[p2]["recent"] is True
    assert rps._fetch_reaction_threads(str(tmp_path / "missing.db"), 0, 0) == {}


# ---------------------------------------------------------------------------
# 3) 回应提示
# ---------------------------------------------------------------------------
def test_prompt_contains_post_replies_reasons_and_rules():
    cand = {**_thread(7, 2, "IBM says Starling remains on schedule for 2029.",
                      comments=[(1, "Origin: our 2028 date stands.")]),
            "reasons": ["it touches your priorities (roadmap)"]}
    prompt = rps.build_reaction_prompt(0, "US Department of Commerce / BIS", [cand], AGENT_NAMES,
                                       "twitter", "2027-H1", "English")
    assert prompt.startswith("# RESPONSE ROUND — 2027-H1")
    assert "post_id=7 — IBM wrote:" in prompt
    assert "Starling remains on schedule" in prompt
    assert "Origin Quantum: \"Origin: our 2028 date stands.\"" in prompt
    assert "Why it may concern you: it touches your priorities (roadmap)" in prompt
    assert "create_comment(post_id, content)" in prompt
    assert "quote_post" not in prompt                    # 回复必须是帖子下的评论，不是新的引用帖
    assert "Add something the post does not already say" in prompt
    assert "written in English" in prompt
    assert "You cannot publish a new standalone post in this step." in prompt
    assert "never like your own post" in prompt
    assert "[comment_id=" not in prompt                  # Twitter 无 like_comment → 不列评论 id
    reddit = rps.build_reaction_prompt(0, "BIS", [cand], AGENT_NAMES, "reddit", "", "")
    assert reddit.startswith("# RESPONSE ROUND\n")
    assert "[comment_id=1]" in reddit and "like_comment" in reddit
    assert "written in" not in reddit


# ---------------------------------------------------------------------------
# 4) 回应执行（辅助 agent 替身，真实库表 + 动作日志）
# ---------------------------------------------------------------------------
class _Agent:
    def __init__(self, aid, tool_names):
        self.agent_id = aid
        self._internal_tools = {name: f"tool:{name}" for name in tool_names}
        self.model_backend = object()
        self.system_message = f"You are {AGENT_NAMES[aid]}."
        self.memory = []

    def update_memory(self, msg, role):
        self.memory.append((msg.content, role))


class _Env:
    def __init__(self):
        self.llm_semaphore = asyncio.Semaphore(2)


ALL_TWITTER_TOOLS = ["create_post", "like_post", "repost", "follow", "do_nothing",
                     "quote_post", "create_comment", "search_posts", "trend"]


def _install_fake_helper(monkeypatch, db, calls):
    """_make_reaction_agent 替身：记录拿到的工具与提示，并像模型那样回应提示里第一条候选帖。"""

    class _Helper:
        def __init__(self, agent, tools):
            self.agent = agent
            self.tools = list(tools)

        async def astep(self, message):
            calls.append({"agent": self.agent.agent_id, "tools": self.tools,
                          "prompt": message.content})
            post_id = int(re.search(r"post_id=(\d+)", message.content).group(1))
            _add_comment(db, self.agent.agent_id, post_id,
                         f"{AGENT_NAMES[self.agent.agent_id]} responds with a new figure.")

    monkeypatch.setattr(rps, "_make_reaction_agent", lambda agent, tools: _Helper(agent, tools))


def test_reaction_phase_uses_only_interaction_tools_and_logs(tmp_path, monkeypatch):
    db = _make_db(tmp_path / "twitter_simulation.db")
    _add_post(db, 1, "Origin Quantum ships refrigerators despite BIS controls.")
    _add_post(db, 2, "IBM: Starling on schedule.")
    calls = []
    _install_fake_helper(monkeypatch, db, calls)
    agents = {aid: _Agent(aid, ALL_TWITTER_TOOLS) for aid in AGENTS}
    logger = PlatformActionLogger("twitter", str(tmp_path))
    state = {"window_start": 0, "round_start": 0}
    last_rowid = _trace_rowid(db)

    actions, new_rowid = asyncio.run(rps.run_reaction_phase(
        _Env(), db, sorted(agents.items()), _config(), 0, "2026-H2", "twitter",
        AGENT_NAMES, state, last_rowid, logger, random.Random(7), lambda _m: None))

    assert len(calls) == 3                               # 每个有候选的活跃 agent 回应一次
    for call in calls:
        assert "tool:create_post" not in call["tools"]
        assert set(call["tools"]) == {"tool:create_comment", "tool:like_post"}
    bis_prompt = next(c["prompt"] for c in calls if c["agent"] == 0)
    assert bis_prompt.index("Origin Quantum wrote") < bis_prompt.index("IBM wrote")  # 点名 BIS 的帖在前
    assert "written in English" in bis_prompt            # 语言按英文预测问题判定

    assert new_rowid > last_rowid
    assert [a["action_type"] for a in actions] == ["CREATE_COMMENT"] * 3
    assert all(a["action_args"].get("post_author_name") for a in actions)
    with open(os.path.join(str(tmp_path), "twitter", "actions.jsonl"), encoding="utf-8") as f:
        logged = [json.loads(line) for line in f if line.strip()]
    assert [(row["round"], row["action_type"]) for row in logged] == [(1, "CREATE_COMMENT")] * 3

    # 记忆回写：一条简短 USER 记录（不是整段候选提示）
    for agent in agents.values():
        assert len(agent.memory) == 1
        content, role = agent.memory[0]
        assert content.startswith("# YOUR RESPONSES THIS PERIOD\nYou replied to ")
        assert role == OpenAIBackendRole.USER
        assert "RESPONSE ROUND" not in content

    # 下一轮：Origin 的帖子收到了别人的回复 → Origin 被提示回应对方
    calls.clear()
    rps._advance_reaction_window(state, db)
    asyncio.run(rps.run_reaction_phase(
        _Env(), db, [(1, agents[1])], _config(), 1, "2027-H1", "twitter",
        AGENT_NAMES, state, new_rowid, logger, random.Random(7), lambda _m: None))
    assert "other actors replied to your post" in calls[0]["prompt"]
    assert "you wrote:" in calls[0]["prompt"]


def test_reaction_phase_skips_agents_without_reply_tools_and_survives_failures(tmp_path, monkeypatch):
    db = _make_db(tmp_path / "reddit_simulation.db")
    _add_post(db, 2, "IBM: Starling on schedule.")
    calls = []

    class _Boom:
        def __init__(self, agent, tools):
            self.agent = agent

        async def astep(self, message):
            calls.append(self.agent.agent_id)
            raise RuntimeError("provider outage")

    monkeypatch.setattr(rps, "_make_reaction_agent", lambda agent, tools: _Boom(agent, tools))
    muted = _Agent(0, ["like_post", "quote_post"])        # 没有 create_comment → 跳过
    failing = _Agent(1, ["create_comment", "like_post", "like_comment", "create_post"])
    msgs = []
    actions, rowid = asyncio.run(rps.run_reaction_phase(
        _Env(), db, [(0, muted), (1, failing)], _config(), 3, "", "reddit", AGENT_NAMES,
        {"window_start": 0, "round_start": 0}, 0, None, random.Random(1), msgs.append))
    assert calls == [1]
    assert actions == [] and rowid == 0
    assert any("provider outage" in m for m in msgs)


# ---------------------------------------------------------------------------
# 5) 轮循环集成：真实 run_twitter_simulation（替身 env 写真实 OASIS 库表）
# ---------------------------------------------------------------------------
class _LoopAgent(_Agent):
    def __init__(self, aid):
        super().__init__(aid, ALL_TWITTER_TOOLS)
        self.name = AGENT_NAMES[aid]
        self._original_system_message = None


class _LoopGraph:
    def __init__(self):
        self._agents = {aid: _LoopAgent(aid) for aid in AGENTS}

    def get_agent(self, aid):
        return self._agents[aid]

    def get_agents(self):
        return list(self._agents.items())


class _LoopEnv:
    """LLMAction → 一条真实 post 行 + create_post trace 行；ManualAction 按类型写 trace。"""

    def __init__(self, agent_graph, db_path):
        self.agent_graph = agent_graph
        self.db_path = db_path
        self.llm_semaphore = asyncio.Semaphore(2)

    async def reset(self):
        pass

    async def step(self, actions):
        conn = sqlite3.connect(self.db_path)
        for agent, act in actions.items():
            for a in (act if isinstance(act, list) else [act]):
                if isinstance(a, ManualAction):
                    conn.execute(
                        "INSERT INTO trace (user_id, created_at, action, info) VALUES (?, 't', ?, ?)",
                        (agent.agent_id, a.action_type.value, json.dumps(a.action_args)))
                    continue
                content = f"{agent.name} announces its move for the period."
                cur = conn.execute(
                    "INSERT INTO post (user_id, content, created_at, num_likes, num_dislikes, "
                    "num_shares) VALUES (?, ?, 't', 0, 0, 0)", (agent.agent_id, content))
                conn.execute(
                    "INSERT INTO trace (user_id, created_at, action, info) VALUES (?, 't', "
                    "'create_post', ?)",
                    (agent.agent_id, json.dumps({"content": content, "post_id": cur.lastrowid})))
        conn.commit()
        conn.close()

    async def close(self):
        pass


def _loop_config():
    cfg = _config()
    rounds = [
        {"round": 0, "period_start": "2026-10-01", "period_end": "2027-03-31", "label": "2026-H2"},
        {"round": 1, "period_start": "2027-04-01", "period_end": "2027-09-30", "label": "2027-H1"},
    ]
    cfg.update({
        "simulation_id": "sim_test_reaction",
        "temporal_config": {
            "schema_version": 1, "mode": "calendar", "as_of_date": "2026-09-30",
            "horizon_date": "2027-09-30", "horizon_source": "anchored_period",
            "horizon_text": "2027", "horizon_defaulted": False, "unit": "half_year",
            "unit_stride": 1, "n_rounds": 2, "round_dates": rounds, "span_days": 365,
            "target_max_rounds": 36, "round_cap_coarsened": None,
            "beyond_horizon_events": [], "warnings": [],
        },
        "time_config": {"total_simulation_hours": 2, "minutes_per_round": 60,
                        "agents_per_hour_max": 3},
        "event_config": {"initial_posts": [], "scheduled_events": []},
    })
    for row in cfg["agent_configs"]:
        row.update({"activity_level": 1.0, "influence_weight": 1.0, "active_hours": [],
                    "cadence": "principal"})
    return cfg


def test_round_loop_runs_reaction_phase_every_round(tmp_path, monkeypatch):
    sim_dir = str(tmp_path)
    with open(os.path.join(sim_dir, "twitter_profiles.csv"), "w", encoding="utf-8") as f:
        f.write("agent_id\n")
    envs, calls = [], []

    async def _fake_graph_gen(profile_path=None, model=None, available_actions=None):
        return _LoopGraph()

    def _fake_make(agent_graph=None, platform=None, database_path=None, semaphore=None):
        _make_db(database_path)
        env = _LoopEnv(agent_graph, database_path)
        envs.append(env)
        _install_fake_helper(monkeypatch, database_path, calls)
        return env

    monkeypatch.setattr(rps, "create_model", lambda config, use_boost=False: object())
    monkeypatch.setattr(rps, "generate_twitter_agent_graph", _fake_graph_gen)
    monkeypatch.setattr(rps, "build_oasis_platform", lambda *a, **k: None)
    monkeypatch.setattr(rps.oasis, "make", _fake_make)
    monkeypatch.setattr(rps, "get_oasis_semaphore", lambda *a, **k: None)
    monkeypatch.delenv("SIM_REACTION_PHASE", raising=False)
    monkeypatch.delenv("SIM_ENGAGEMENT_SAMPLER", raising=False)
    monkeypatch.delenv("SIM_OUTPUT_LANGUAGE", raising=False)
    monkeypatch.setenv("SIM_DECISION_CHANNEL_INBAND", "false")

    logger = PlatformActionLogger("twitter", sim_dir)
    asyncio.run(rps.run_twitter_simulation(_loop_config(), sim_dir, action_logger=logger))

    with open(os.path.join(sim_dir, "twitter", "actions.jsonl"), encoding="utf-8") as f:
        events = [json.loads(line) for line in f if line.strip()]
    actions = [e for e in events if e.get("action_type")]
    for rnd in (1, 2):
        kinds = [a["action_type"] for a in actions if a["round"] == rnd]
        assert kinds.count("CREATE_POST") == 3
        assert kinds.count("CREATE_COMMENT") == 3        # 每个活跃 agent 都回应了一次
        end = next(e for e in events if e.get("event_type") == "round_end" and e["round"] == rnd)
        assert end["actions_count"] == 6                 # 回应动作计入本轮
    # 采样赞默认随回应阶段关闭：没有 is_engagement_sample 行
    assert not any((a.get("action_args") or {}).get("is_engagement_sample") for a in actions)
    # 世界时钟告知回应阶段与输出语言
    notes = [c for _aid, ag in envs[0].agent_graph.get_agents() for c, _r in ag.memory
             if c.startswith("# WORLD CLOCK")]
    assert notes and all("separate response step" in n and "in English." in n for n in notes)
    # 第 2 轮的回应里出现「别人回复了你的帖子」
    assert any("other actors replied to your post" in c["prompt"] for c in calls[3:])


def test_round_loop_reaction_phase_off_restores_old_behavior(tmp_path, monkeypatch):
    sim_dir = str(tmp_path)
    with open(os.path.join(sim_dir, "twitter_profiles.csv"), "w", encoding="utf-8") as f:
        f.write("agent_id\n")
    envs, calls = [], []

    async def _fake_graph_gen(profile_path=None, model=None, available_actions=None):
        return _LoopGraph()

    def _fake_make(agent_graph=None, platform=None, database_path=None, semaphore=None):
        _make_db(database_path)
        env = _LoopEnv(agent_graph, database_path)
        envs.append(env)
        _install_fake_helper(monkeypatch, database_path, calls)
        return env

    monkeypatch.setattr(rps, "create_model", lambda config, use_boost=False: object())
    monkeypatch.setattr(rps, "generate_twitter_agent_graph", _fake_graph_gen)
    monkeypatch.setattr(rps, "build_oasis_platform", lambda *a, **k: None)
    monkeypatch.setattr(rps.oasis, "make", _fake_make)
    monkeypatch.setattr(rps, "get_oasis_semaphore", lambda *a, **k: None)
    monkeypatch.setenv("SIM_REACTION_PHASE", "false")
    monkeypatch.setenv("SIM_ENGAGEMENT_SAMPLER", "false")
    monkeypatch.setenv("SIM_DECISION_CHANNEL_INBAND", "false")

    asyncio.run(rps.run_twitter_simulation(
        _loop_config(), sim_dir, action_logger=PlatformActionLogger("twitter", sim_dir)))
    assert calls == []
    notes = [c for _aid, ag in envs[0].agent_graph.get_agents() for c, _r in ag.memory
             if c.startswith("# WORLD CLOCK")]
    assert notes and not any("separate response step" in n for n in notes)


# ---------------------------------------------------------------------------
# 6) 开关、语言、世界时钟
# ---------------------------------------------------------------------------
def test_engagement_sampler_defaults_off_while_reaction_phase_on(monkeypatch):
    monkeypatch.delenv("SIM_ENGAGEMENT_SAMPLER", raising=False)
    monkeypatch.delenv("SIM_REACTION_PHASE", raising=False)
    assert rps._reaction_phase_enabled() is True
    assert rps._engagement_sampler_enabled() is False
    monkeypatch.setenv("SIM_REACTION_PHASE", "false")
    assert rps._engagement_sampler_enabled() is True
    monkeypatch.setenv("SIM_REACTION_PHASE", "true")
    monkeypatch.setenv("SIM_ENGAGEMENT_SAMPLER", "true")
    assert rps._engagement_sampler_enabled() is True     # 显式值永远优先


def test_sim_output_language_resolution(monkeypatch):
    monkeypatch.delenv("SIM_OUTPUT_LANGUAGE", raising=False)
    assert rps._sim_output_language({"simulation_requirement": "Forecast quantum computing"}) == "English"
    assert rps._sim_output_language({"simulation_requirement": "预测2040年量子计算发展与经济影响"}) == "Chinese"
    assert rps._sim_output_language({"simulation_requirement": "2040"}) == ""
    assert rps._sim_output_language({"output_language": "Chinese",
                                     "simulation_requirement": "Forecast"}) == "Chinese"
    monkeypatch.setenv("SIM_OUTPUT_LANGUAGE", "english")
    assert rps._sim_output_language({"output_language": "Chinese"}) == "English"   # env 覆盖
    assert rps._world_brief_header({}) == rps._WORLD_BRIEF_HEADER_EN
    monkeypatch.delenv("SIM_OUTPUT_LANGUAGE")
    assert rps._world_brief_header({}) == rps._WORLD_BRIEF_HEADER                 # 旧配置不变


class _ClockAgent:
    def __init__(self):
        self.notes = []

    def update_memory(self, msg, role):
        self.notes.append(msg.content)


class _ClockGraph:
    def __init__(self):
        self.agent = _ClockAgent()

    def get_agent(self, _aid):
        return self.agent


class _ClockEnv:
    def __init__(self):
        self.agent_graph = _ClockGraph()


def test_world_clock_mentions_response_step_and_language_only_when_asked():
    period = {"label": "2027-H1", "period_start": "2027-01-01", "period_end": "2027-06-30"}
    timeline = {"unit": "half_year", "horizon_date": "2040-12-31", "n_rounds": 29}
    env = _ClockEnv()
    rps._inject_period_context(env, [0], 0, period, timeline, [], "")
    rps._inject_period_context(env, [0], 1, period, timeline, [], "", response_step=True,
                               language="English")
    old, new = env.agent_graph.agent.notes
    assert "separate response step" not in old and "Write all of your posts" not in old
    assert "separate response step to answer other actors' posts" in new
    assert "Write all of your posts and replies in English." in new
    assert new.index("in English.") < new.index("## CONFIRMED EVENTS THIS PERIOD")


# ---------------------------------------------------------------------------
# 7) 配置生成：输出语言
# ---------------------------------------------------------------------------
def _gen(language=None):
    gen = SimulationConfigGenerator.__new__(SimulationConfigGenerator)
    if language is not None:
        gen._output_language = language
    return gen


def test_resolve_output_language():
    resolve = SimulationConfigGenerator._resolve_output_language
    assert resolve("English", "预测量子计算") == "English"
    assert resolve("Chinese", "Forecast quantum computing") == "Chinese"
    assert resolve("", "Forecast quantum computing through 2040") == "English"
    assert resolve(None, "预测2040年量子计算") == "Chinese"
    assert resolve("auto", "2040") == ""


ACTORS = {
    "situation_brief": {"current_situation": "Logical qubits are scaling.",
                        "fault_lines": ["Vendor timelines vs independent verification"]},
}


def test_world_brief_uses_english_headings_for_english_runs():
    brief = _gen("English")._build_world_brief(
        "Forecast quantum computing through 2040.", ACTORS, ["export controls", "PQC migration"])
    assert "## Forecast question (what this world is debating)" in brief
    assert "## Situation brief (deep-research evidence, authoritative background)" in brief
    assert "### Current situation\nLogical qubits are scaling." in brief
    assert "### Fault lines" in brief
    assert "## Hot topics\nexport controls; PQC migration" in brief
    assert not re.search(r"[一-鿿]", brief)
    legacy = _gen()._build_world_brief("预测量子计算", ACTORS, ["出口管制"])
    assert "## 核心预测问题" in legacy and "## 热点话题\n出口管制" in legacy   # 未判定语言 → 旧标题


class _Entity:
    name = "IBM"

    def get_entity_type(self):
        return "Organization"


@pytest.mark.parametrize("language, expected", [
    ("English", "**Output language: English.**"),
    ("Chinese", "**输出语言：中文。**"),
])
def test_event_config_prompt_states_output_language(language, expected):
    gen = _gen(language)
    captured = {}

    def _call(prompt, system_prompt):
        captured["prompt"] = prompt
        return {"hot_topics": [], "narrative_direction": "", "initial_posts": []}

    gen._call_llm_with_retry = _call
    gen._generate_event_config("context", "Forecast quantum computing.", [_Entity()])
    assert expected in captured["prompt"]


def test_event_config_prompt_unchanged_without_language():
    gen = _gen()
    captured = {}
    gen._call_llm_with_retry = lambda prompt, system_prompt: captured.setdefault("p", prompt) and {}
    gen._generate_event_config("context", "预测量子计算", [_Entity()])
    assert "Output language" not in captured["p"] and "输出语言" not in captured["p"]


def test_parameters_serialize_output_language_only_when_set():
    base = {"simulation_id": "s", "project_id": "p", "graph_id": "g", "simulation_requirement": "q"}
    assert "output_language" not in SimulationParameters(**base).to_dict()
    assert SimulationParameters(**base, output_language="English").to_dict()["output_language"] == "English"
