"""SIM-5 (C42 a): no actor is credited with a scheduled event where DRF reads sim behaviour.

Research key_events are replayed as CREATE_POSTs under a real actor's account (name
match, or the top-influence fallback).  These tests pin the report-side consumers
(SimulationRunner.get_agent_stats -> ZepToolsService.simulation_outcomes -> the report
salience tiers, and coalition_map) and the child-side ones (post-hoc decision roster,
stance trajectory), each with SIM_EVENT_PROVENANCE on (default) and off (legacy bytes).
"""

import json
import os
import sys

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_BACKEND, "scripts")
for _p in (_BACKEND, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import run_parallel_simulation as rps  # noqa: E402
from app.config import Config  # noqa: E402
from app.services.report_agent import _parse_outcome_actors, salience_tiers_from_outcomes  # noqa: E402
from app.services.simulation_runner import SimulationRunner  # noqa: E402
from app.services.zep_tools import ZepToolsService  # noqa: E402

EVENT = ("[WORLD EVENT · scheduled on the research timeline · not a statement by any actor] "
         "Commerce adds three quantum firms to the Entity List.")
EVENT_2 = ("[WORLD EVENT · scheduled on the research timeline · not a statement by any actor] "
           "EU launches its quantum chips act.")
FALLBACK = "Top Influence Corp"


def _row(rnd, aid, name, kind, **args):
    return {"round": rnd, "timestamp": f"2026-07-02T00:{rnd:02d}:{aid:02d}", "agent_id": aid,
            "agent_name": name, "action_type": kind, "action_args": args}


# The fallback poster (agent 0) has only injected rows; agents 1-3 act organically.
ROWS = [
    _row(0, 1, "Alpha", "CREATE_POST", content="Alpha seed post"),
    _row(0, 2, "Beta", "FOLLOW", is_seed_action=True, target_user_name="Alpha"),
    _row(1, 0, FALLBACK, "CREATE_POST", content=EVENT, is_scheduled_event=True,
         event_provenance="research_timeline"),
    _row(2, 0, FALLBACK, "CREATE_POST", content=EVENT_2, is_scheduled_event=True,
         event_provenance="research_timeline"),
    _row(3, 0, FALLBACK, "CREATE_POST", content=EVENT + " (replay)", is_scheduled_event=True),
    _row(1, 1, "Alpha", "CREATE_POST", content="Alpha sees strong growth and support."),
    _row(1, 2, "Beta", "LIKE_POST", post_id=3, post_content=EVENT, post_author_name=FALLBACK),
    _row(1, 3, "Gamma", "CREATE_COMMENT", content="Gamma: this hurts our supply chain.",
         post_id=3, post_content=EVENT, post_author_name=FALLBACK),
    _row(2, 2, "Beta", "CREATE_POST", content="Beta warns of a loss and decline."),
    _row(2, 3, "Gamma", "LIKE_POST", post_id=9, post_content="Delta roadmap",
         post_author_name="Delta", is_engagement_sample=True),
    _row(2, 1, "Alpha", "LIKE_POST", post_id=9, post_content="Delta roadmap",
         post_author_name="Delta", is_engagement_sample=True),
]


@pytest.fixture
def sim_env(tmp_path, monkeypatch):
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationRunner, "_run_states", {})
    return tmp_path


def _write_actions(sim_dir, rows, platform="twitter"):
    plat_dir = os.path.join(str(sim_dir), platform)
    os.makedirs(plat_dir, exist_ok=True)
    with open(os.path.join(plat_dir, "actions.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"round": 1, "event_type": "round_start"}) + "\n")
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _svc():
    return ZepToolsService.__new__(ZepToolsService)


# ---------------------------------------------------------------------------
# simulation_outcomes (-> report salience tiers)
# ---------------------------------------------------------------------------
def test_outcomes_rank_by_organic_actions_and_drop_the_fallback_poster(sim_env):
    _write_actions(sim_env / "sim_prov", ROWS)
    text = _svc().simulation_outcomes("sim_prov")

    assert "### 最活跃 Agent（Top 15，按自发动作数）" in text
    assert f"{FALLBACK}(id=0)" not in text          # only event rows → never listed
    actors = dict(_parse_outcome_actors(text))
    # Alpha: 1 organic post + 1 sampled like + 1 round-0 seed post → 1 organic action
    assert actors == {"Alpha": 1, "Beta": 2, "Gamma": 1}
    assert "- Beta(id=2): 共 2 次动作 [" in text
    assert "LIKE_POST×1" in text.split("- Beta(id=2)")[1].splitlines()[0]
    # injected rows: 3 event replays + 1 seed post + 1 seed follow + 2 sampled likes
    assert "（已剔除注入动作 7 次：种子/时间线事件回放/采样点赞——非行为者自发）" in text
    breakdown = text.split("### 全局动作类型分布\n")[1].splitlines()[0]
    assert breakdown == "CREATE_POST: 2、LIKE_POST: 1、CREATE_COMMENT: 1"
    # the salience tiers read the same lines: the fallback poster cannot top them
    assert FALLBACK not in salience_tiers_from_outcomes(text)


def test_outcomes_without_injected_rows_have_no_note(sim_env):
    _write_actions(sim_env / "sim_clean", [
        _row(1, 1, "Alpha", "CREATE_POST", content="a"),
        _row(2, 2, "Beta", "CREATE_POST", content="b"),
    ])
    text = _svc().simulation_outcomes("sim_clean")
    assert "已剔除注入动作" not in text
    assert dict(_parse_outcome_actors(text)) == {"Alpha": 1, "Beta": 1}


def test_outcomes_flag_off_is_legacy(sim_env, monkeypatch):
    monkeypatch.setattr(Config, "SIM_EVENT_PROVENANCE", False)
    _write_actions(sim_env / "sim_legacy", ROWS)
    text = _svc().simulation_outcomes("sim_legacy")
    expected_head = "\n".join([
        "## 模拟量化结果（结构化，可直接引用）",
        "",
        "### 最活跃 Agent（Top 15，按总动作数）",
        f"- {FALLBACK}(id=0): 共 3 次动作 [CREATE_POST×3]",
        "- Beta(id=2): 共 3 次动作 [CREATE_POST×1、LIKE_POST×1、FOLLOW×1]",
        "- Alpha(id=1): 共 3 次动作 [CREATE_POST×2、LIKE_POST×1]",
        "- Gamma(id=3): 共 2 次动作 [LIKE_POST×1、CREATE_COMMENT×1]",
        "",
        "### 全局动作类型分布",
        "CREATE_POST: 6、LIKE_POST: 3、FOLLOW: 1、CREATE_COMMENT: 1",
    ])
    assert text.startswith(expected_head + "\n")
    assert "已剔除注入动作" not in text
    stats = SimulationRunner.get_agent_stats("sim_legacy")
    assert all("organic_actions" not in s and "injected_actions" not in s
               and "organic_action_types" not in s for s in stats)


# ---------------------------------------------------------------------------
# coalition_map
# ---------------------------------------------------------------------------
def test_coalition_ignores_event_targets_and_sampled_likes(sim_env):
    _write_actions(sim_env / "sim_coal", ROWS)
    text = _svc().coalition_map("g", "sim_coal")
    # Beta and Gamma only share the event post's account; Alpha and Gamma only share a
    # sampled like of Delta's post. Beta's seed FOLLOW of Alpha is a real directed target.
    assert "派系" in text and "（2 人）" not in text and "（3 人）" not in text
    assert "（未发现 ≥2 人的互动派系）" in text


def test_coalition_keeps_real_shared_targets(sim_env):
    rows = ROWS + [
        _row(3, 2, "Beta", "LIKE_POST", post_id=5, post_content="Alpha sees strong growth and support.",
             post_author_name="Alpha"),
        _row(3, 3, "Gamma", "CREATE_COMMENT", content="agreed", post_id=5,
             post_content="Alpha sees strong growth and support.", post_author_name="Alpha"),
        # a quote of the event is reaction to news, not alignment with the posting account
        _row(3, 1, "Alpha", "QUOTE_POST", quoted_id=3, original_content=EVENT,
             original_author_name=FALLBACK, quote_content="Alpha: this is overdue."),
    ]
    _write_actions(sim_env / "sim_coal2", rows)
    text = _svc().coalition_map("g", "sim_coal2")
    assert "- 派系 1（2 人）: Beta、Gamma" in text or "- 派系 1（2 人）: Gamma、Beta" in text
    assert "Alpha" not in text.split("派系 1")[1]


def test_coalition_flag_off_is_legacy(sim_env, monkeypatch):
    monkeypatch.setattr(Config, "SIM_EVENT_PROVENANCE", False)
    _write_actions(sim_env / "sim_coal_legacy", ROWS)
    text = _svc().coalition_map("g", "sim_coal_legacy")
    # legacy: Beta+Gamma via the event account, Alpha+Gamma via Delta, Beta→Alpha via FOLLOW
    assert text == "## 派系/联盟图（按共享互动对象聚类，确定性）\n- 派系 1（3 人）: Gamma、Alpha、Beta"


# ---------------------------------------------------------------------------
# opinion_shift / scenario_diff (per-actor readers of the same logs)
# ---------------------------------------------------------------------------
def test_opinion_shift_drops_injected_rows(sim_env):
    _write_actions(sim_env / "sim_shift", ROWS)
    assert _svc().opinion_shift("sim_shift", FALLBACK) == (
        f"（「{FALLBACK}」名下没有自发动作：3 次均为注入动作——种子/时间线事件回放/采样点赞）")
    alpha = _svc().opinion_shift("sim_shift", "Alpha")
    assert alpha.splitlines()[1:] == [
        "- round 1: CREATE_POST×1",
        "合计 1 次动作，跨 1 轮。",
        "（已剔除注入动作 2 次：种子/时间线事件回放/采样点赞——非行为者自发）",
    ]


def test_opinion_shift_flag_off_is_legacy(sim_env, monkeypatch):
    monkeypatch.setattr(Config, "SIM_EVENT_PROVENANCE", False)
    _write_actions(sim_env / "sim_shift_legacy", ROWS)
    assert _svc().opinion_shift("sim_shift_legacy", FALLBACK).splitlines()[1:] == [
        "- round 1: CREATE_POST×1",
        "- round 2: CREATE_POST×1",
        "- round 3: CREATE_POST×1",
        "合计 3 次动作，跨 3 轮。",
    ]


def _scenario_rows():
    # the scenario run injects one what-if event under Alpha's account
    return ROWS + [_row(3, 1, "Alpha", "CREATE_POST", is_scheduled_event=True,
                        event_provenance="scenario_assumption",
                        content="[SCENARIO ASSUMPTION · what-if, not observed] Blockade.")]


@pytest.mark.parametrize("provenance_on", [True, False])
def test_scenario_diff_compares_organic_activity(sim_env, monkeypatch, provenance_on):
    monkeypatch.setattr(Config, "SIM_EVENT_PROVENANCE", provenance_on)
    _write_actions(sim_env / "sim_base", ROWS)
    _write_actions(sim_env / "sim_scen", _scenario_rows())
    text = _svc().scenario_diff("sim_base", "sim_scen")
    if provenance_on:
        assert "### Top-actor 活跃度 delta（按变化幅度，仅自发动作）" in text
        assert "- Alpha: 1 → 1（Δ +0）" in text          # the injected what-if is not Alpha's move
    else:
        assert "### Top-actor 活跃度 delta（按变化幅度）\n- Alpha: 3 → 4（Δ +1）" in text


# ---------------------------------------------------------------------------
# child consumers: post-hoc decision roster, stance trajectory
# ---------------------------------------------------------------------------
def test_decision_channel_roster_drops_event_and_sampled_rows(tmp_path):
    _write_actions(tmp_path, ROWS)
    acts = rps._read_actions_for_decision_channel(str(tmp_path))
    assert all(a["agent_id"] != 0 for a in acts)          # the fallback poster never acted
    assert len(acts) == len(ROWS) - 3 - 2                 # 3 event replays, 2 sampled likes
    assert {"round": 0, "agent_id": 2, "agent_name": "Beta"} in acts   # seed rows kept (as before)


def test_decision_channel_roster_flag_off_is_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("SIM_EVENT_PROVENANCE", "false")
    _write_actions(tmp_path, ROWS)
    acts = rps._read_actions_for_decision_channel(str(tmp_path))
    assert acts == [{"round": r["round"], "agent_id": r["agent_id"], "agent_name": r["agent_name"]}
                    for r in ROWS]


STANCES = {0: "supportive", 1: "supportive", 2: "opposing", 3: "neutral"}


def test_stance_trajectory_ignores_injected_rows(tmp_path):
    _write_actions(tmp_path, ROWS)
    trajectory, _polarization, net = rps._score_stance_trajectory(
        os.path.join(str(tmp_path), "twitter", "actions.jsonl"), STANCES)
    by_round = {row["round"]: row["by_stance"] for row in trajectory}
    assert set(by_round) == {1, 2}                        # no round-0 seeding, no replay-only round 3
    assert by_round[1] == {"supportive": 1, "opposing": 0, "neutral": 1, "observer": 0}
    assert by_round[2] == {"supportive": 0, "opposing": 1, "neutral": 0, "observer": 0}
    assert 0 not in net


def test_stance_trajectory_flag_off_is_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("SIM_EVENT_PROVENANCE", "false")
    _write_actions(tmp_path, ROWS)
    trajectory, _polarization, net = rps._score_stance_trajectory(
        os.path.join(str(tmp_path), "twitter", "actions.jsonl"), STANCES)
    by_round = {row["round"]: row["by_stance"] for row in trajectory}
    assert set(by_round) == {0, 1, 2, 3}
    assert by_round[1] == {"supportive": 2, "opposing": 0, "neutral": 1, "observer": 0}
    assert by_round[3] == {"supportive": 1, "opposing": 0, "neutral": 0, "observer": 0}
    assert 0 in net
