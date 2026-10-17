"""Downstream consumers of the reflexive world (design §2.9, acceptance A9).

Offline.  Pins: the world-state API (containment, 404 before commit, bounded happy path),
run_summary's ``world_model`` block, the run-state projection of ``world_update`` rows,
the report's world-evolution signal block, the world-variables chart builder and the
orchestrator's decision-channel summary.
"""

import json
import os

import pytest

from app.config import Config
from app.services.simulation_runner import SimulationRunner


def _world_state_payload(committed=3):
    return {
        "schema_version": "world-state-file/v1",
        "simulation_id": "sim_ws",
        "committed_round": committed,
        "brief": "# WORLD STATE — as of 2027-03-31\n## Key facts\n- Tariff rate: 25%",
        "digest": "Tariff shock ripples.",
        "headline": "2027-Q1: 3 decisions · 1 facts changed · arbiter=applied",
        "summary": {"schema_version": "world-model-summary/v1", "rounds_committed": committed, "variables": 2,
                    "actors": 3, "relationships": 1, "events": 5, "pending_effects": 1,
                    "arbiter_enabled": True, "arbiter_failed_rounds": 1, "decision_actors_max": 24},
        "world": {
            "schema_version": "world-model-state/v1", "question": "Will A happen?", "as_of_date": "2026-07-11",
            "horizon_date": "2027-03-31", "scenarios": ["A", "B"], "round": committed, "committed_round": committed,
            "period": {"label": "2027-Q1", "period_end": "2027-03-31"},
            "period_labels": {"1": "2026-Q3", "2": "2026-Q4", "3": "2027-Q1"},
            "variables": [
                {"id": "tariff_rate", "name": "Tariff rate", "value": 25.0, "unit": "%", "kind": "numeric",
                 "provenance": "arbiter", "as_of": "2026-07-01",
                 "history": [{"round": 0, "value": 10.0, "cause": "seed", "source": "research"},
                             {"round": 1, "value": 25.0, "cause": "decree", "source": "arbiter"},
                             {"round": 2, "value": 25.0, "cause": "hold", "source": "arbiter"}]},
                {"id": "permit", "name": "Permit", "value": "pending", "unit": "", "kind": "categorical",
                 "provenance": "research", "history": [{"round": 0, "value": "pending", "cause": "seed", "source": "research"}]},
            ],
            "actors": [
                {"agent_id": 0, "name": "Actor0", "agency_class": "sovereign_government", "archetype": "actor",
                 "capacity_per_round": 3, "capacity_used": 3, "reputation": 0.52,
                 "commitments": [{"id": "c0", "description": "Publish schedule", "due_round": 4, "status": "pending"},
                                 {"id": "c1", "description": "Old", "due_round": 1, "status": "fulfilled"}],
                 "last_action": {"round": 3, "option_id": "impose_measure", "label": "Impose tariff", "resolution": "success"}},
                {"agent_id": 1, "name": "Actor1", "agency_class": "firm", "commitments": [], "last_action": None},
            ],
            "relationships": [{"source": 0, "target": 1, "kind": "REGULATES", "valence": "adversarial",
                               "polarity": -0.3, "strength": 0.6, "last_changed_round": 3, "history": []}],
            "pending_effects": [{"id": "fx1", "due_round": 4, "description": "Importers relocate", "probability": 0.5}],
            "events": [{"round": r, "kind": "action", "description": f"Actor0 move {r}", "actors": ["Actor0"],
                        "targets": ["Actor1"], "statement": "Tariff raised"} for r in (1, 2, 3)],
        },
    }


def _history_rows():
    return [
        {"round": 1, "period_label": "2026-Q3", "headline": "2026-Q3: 3 decisions", "narrative": "Shock.",
         "arbiter_status": "applied", "decisions": {"total": 3, "ok": 3, "held": 2},
         "deterministic": {"actions": ["Impose or raise a tariff → Actor1", "Actor1 holds position"],
                           "scheduled_events": [], "commitments_lapsed": [], "effects_fired": []},
         "diff": {"variables_changed": [{"id": "tariff_rate", "name": "Tariff rate", "from": 10.0, "to": 25.0, "unit": "%"}],
                  "variables_added": [], "relationships_changed": [{"source": "Actor0", "target": "Actor1", "from": "directional",
                                                                    "to": "adversarial", "direction": "farther"}]},
         "scenario_pressure": {"A": "up"}},
        {"round": 2, "period_label": "2026-Q4", "headline": "2026-Q4: quiet", "narrative": "",
         "arbiter_status": "failed", "arbiter_problems": ["llm error: BadRequestError"],
         "error": "BadRequestError: content filter",
         "decisions": {"total": 3}, "deterministic": {"actions": []}, "diff": {}, "shares": {"A": 0.6, "B": 0.4}},
        {"round": 3, "period_label": "2027-Q1", "headline": "2027-Q1: 3 decisions", "narrative": "Importers protest.",
         "arbiter_status": "applied", "arbiter_problems": ["unknown variable 'x'"],
         "decisions": {"total": 3}, "deterministic": {"actions": ["Open an inquiry → Actor0"]},
         "diff": {"variables_changed": [], "variables_added": [], "relationships_changed": []}},
    ]


def _digest_rows():
    # one audit row per stepped round (round 2 has none: the shares step was isolated that round),
    # plus a duplicate for round 3 (the later row wins) and junk lines the reader must skip
    return [
        {"round": 1, "period_end": "2026-09-30", "digest": "Digest 1.", "shares": {"A": 0.5, "B": 0.5}},
        {"round": 3, "period_end": "2027-03-31", "digest": "Stale digest 3.", "shares": {"A": 0.7, "B": 0.3}},
        {"round": 3, "period_end": "2027-03-31", "digest": "Digest 3.\nMoves:\n- Actor0: Open an inquiry", "shares": {"A": 0.7, "B": 0.3}},
        {"round": 9, "digest": "Digest of a round outside the slice."},
    ]


def _write_world(sim_dir, with_history=True, committed=3, with_digest=False):
    os.makedirs(sim_dir, exist_ok=True)
    with open(os.path.join(sim_dir, "world_state.json"), "w", encoding="utf-8") as f:
        json.dump(_world_state_payload(committed), f, ensure_ascii=False)
    if with_history:
        with open(os.path.join(sim_dir, "world_state_history.jsonl"), "w", encoding="utf-8") as f:
            for row in _history_rows():
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    if with_digest:
        with open(os.path.join(sim_dir, "world_digest.jsonl"), "w", encoding="utf-8") as f:
            f.write("{not json\n\n[1, 2]\n")
            for row in _digest_rows():
                f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ----------------------------------------------------------------------------- API
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_world_state_api_happy_path_is_bounded(client, tmp_path):
    _write_world(str(tmp_path / "sim_ws"))
    res = client.get("/api/simulation/sim_ws/world-state?rows=2")
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert data["committed_round"] == 3 and data["headline"].startswith("2027-Q1")
    assert data["brief"].startswith("# WORLD STATE") and data["summary"]["arbiter_failed_rounds"] == 1
    assert [v["id"] for v in data["variables"]] == ["tariff_rate", "permit"]
    assert len(data["variables"][0]["history"]) == 3
    assert data["actors"][0]["pending_commitments"] == [
        {"id": "c0", "description": "Publish schedule", "due_round": 4, "status": "pending"}]
    assert data["actors"][0]["last_action"]["option_id"] == "impose_measure"
    assert data["relationships"][0]["valence"] == "adversarial" and "history" not in data["relationships"][0]
    assert [h["round"] for h in data["history"]] == [2, 3]                     # last N rows only
    assert data["history"][1]["narrative"] == "Importers protest."
    assert len(data["recent_events"]) == 3 and data["pending_effects"][0]["id"] == "fx1"
    assert data["period"]["label"] == "2027-Q1" and data["question"] == "Will A happen?"


def test_world_state_api_404_before_commit_and_containment(client, tmp_path):
    os.makedirs(str(tmp_path / "sim_empty"))
    assert client.get("/api/simulation/sim_empty/world-state").status_code == 404
    assert client.get("/api/simulation/nope/world-state").status_code == 404
    assert client.get("/api/simulation/..%2F..%2Fetc/world-state").status_code == 404
    assert client.get("/api/simulation/%2E%2E/world-state").status_code == 404
    _write_world(str(tmp_path / "real"))
    os.symlink(str(tmp_path / "real" / "world_state.json"), str(tmp_path / "sim_link_target"))
    os.makedirs(str(tmp_path / "sim_link"))
    os.symlink(str(tmp_path / "real" / "world_state.json"), str(tmp_path / "sim_link" / "world_state.json"))
    assert client.get("/api/simulation/sim_link/world-state").status_code == 404


def test_world_state_api_bad_json_and_bad_rows(client, tmp_path):
    sim_dir = tmp_path / "sim_bad"
    sim_dir.mkdir()
    (sim_dir / "world_state.json").write_text("{not json", encoding="utf-8")
    res = client.get("/api/simulation/sim_bad/world-state")
    assert res.status_code == 500 and "traceback" not in res.get_json()
    _write_world(str(tmp_path / "sim_ok"), with_history=False)
    res = client.get("/api/simulation/sim_ok/world-state?rows=zzz")
    assert res.status_code == 200 and res.get_json()["data"]["history"] == []


def test_world_state_api_history_rows_carry_problems_and_digests(client, tmp_path):
    """The panel's round selector needs each committed round's arbiter problems, the update
    error (when the update itself failed) and the agent-facing digest of that round."""
    _write_world(str(tmp_path / "sim_hist"), with_digest=True)
    data = client.get("/api/simulation/sim_hist/world-state?rows=2").get_json()["data"]
    rows = {h["round"]: h for h in data["history"]}
    assert list(rows) == [2, 3]
    assert rows[2]["arbiter_status"] == "failed" and rows[2]["arbiter_problems"] == ["llm error: BadRequestError"]
    assert rows[2]["error"] == "BadRequestError: content filter"
    assert rows[3]["arbiter_problems"] == ["unknown variable 'x'"] and "error" not in rows[3]
    assert rows[2]["digest"] == ""                                              # no digest row → empty, never missing
    assert rows[3]["digest"] == "Digest 3.\nMoves:\n- Actor0: Open an inquiry"   # the later duplicate wins
    assert "shares" not in rows[2] and "shares" not in rows[3]                 # quantitative shares never travel
    assert data["digest"] == "Tariff shock ripples."                            # top-level latest digest unchanged
    # rows without a problems list (older runs) → []
    _write_world(str(tmp_path / "sim_plain"))
    plain = client.get("/api/simulation/sim_plain/world-state").get_json()["data"]["history"]
    assert [h["arbiter_problems"] for h in plain][0] == [] and all(h["digest"] == "" for h in plain)
    # bounds: at most 12 problems of 200 chars, digest text capped at 2000 chars, error at 200
    sim_big = tmp_path / "sim_big"
    _write_world(str(sim_big), with_history=False)
    with open(sim_big / "world_state_history.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"round": 1, "arbiter_status": "invalid", "arbiter_problems": ["p" * 500] * 20,
                            "error": "e" * 500, "diff": {}}) + "\n")
    with open(sim_big / "world_digest.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"round": 1, "digest": "d" * 5000}) + "\n")
    big = client.get("/api/simulation/sim_big/world-state").get_json()["data"]["history"][0]
    assert len(big["arbiter_problems"]) == 12 and all(len(p) == 200 for p in big["arbiter_problems"])
    assert len(big["error"]) == 200 and len(big["digest"]) == 2000
    # a non-list problems field is tolerated; a symlinked digest file is refused like the other artifacts
    sim_link = tmp_path / "sim_dlink"
    _write_world(str(sim_link), with_history=False)
    with open(sim_link / "world_state_history.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"round": 1, "arbiter_status": "applied", "arbiter_problems": "oops", "diff": {}}) + "\n")
    os.symlink(str(sim_big / "world_digest.jsonl"), str(sim_link / "world_digest.jsonl"))
    linked = client.get("/api/simulation/sim_dlink/world-state").get_json()["data"]["history"][0]
    assert linked["arbiter_problems"] == [] and linked["digest"] == ""


# ----------------------------------------------------------------------------- run summary + run state
@pytest.fixture
def sim_env(tmp_path, monkeypatch):
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(SimulationRunner, "_run_states", {})
    monkeypatch.setattr(SimulationRunner, "_run_state_last_save", {})
    monkeypatch.setattr(SimulationRunner, "_processes", {})
    monkeypatch.setattr(SimulationRunner, "_action_queues", {})
    monkeypatch.setattr(SimulationRunner, "_monitor_threads", {})
    monkeypatch.setattr(SimulationRunner, "_stdout_files", {})
    return tmp_path


def _write_actions(sim_dir, rows):
    os.makedirs(os.path.join(sim_dir, "twitter"), exist_ok=True)
    with open(os.path.join(sim_dir, "twitter", "actions.jsonl"), "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_run_summary_carries_world_model_block(sim_env):
    sim_id = "sim_summary_world"
    sim_dir = str(sim_env / sim_id)
    _write_actions(sim_dir, [
        {"round": 1, "timestamp": "t", "event_type": "round_start", "simulated_hour": 0},
        {"round": 1, "timestamp": "t", "agent_id": 0, "agent_name": "Actor0", "action_type": "CREATE_POST",
         "action_args": {"content": "x", "is_world_decision": True}, "result": None, "success": True},
        {"round": 1, "timestamp": "t", "event_type": "world_update", "headline": "2026-Q3: 1 decisions",
         "period_label": "2026-Q3", "arbiter_status": "applied"},
        {"round": 1, "timestamp": "t", "event_type": "round_end", "actions_count": 1, "simulated_hours": 1.0},
    ])
    with open(os.path.join(sim_dir, "simulation_config.json"), "w", encoding="utf-8") as f:
        json.dump({"time_config": {"total_simulation_hours": 1, "minutes_per_round": 60}}, f)
    with open(os.path.join(sim_dir, "run_state.json"), "w", encoding="utf-8") as f:
        json.dump({"current_round": 1, "total_rounds": 1}, f)
    _write_world(sim_dir, with_history=False, committed=1)
    summary = SimulationRunner.write_run_summary(sim_id)
    assert summary["world_model"]["rounds_committed"] == 1 and summary["world_model"]["committed_round"] == 1
    assert summary["world_model"]["headline"].startswith("2027-Q1")
    assert summary["world_model"]["arbiter_failed_rounds"] == 1
    assert summary["organic_action_count"] == 1                                  # the published statement counts
    # legacy run without the file → no key
    sim2 = str(sim_env / "sim_legacy")
    _write_actions(sim2, [{"round": 1, "timestamp": "t", "event_type": "round_end", "actions_count": 0}])
    with open(os.path.join(sim2, "run_state.json"), "w", encoding="utf-8") as f:
        json.dump({"current_round": 1, "total_rounds": 1}, f)
    assert "world_model" not in SimulationRunner.write_run_summary("sim_legacy")


def test_action_log_projects_latest_world_update_into_run_state(sim_env):
    from app.services.simulation_runner import SimulationRunState
    sim_id = "sim_proj"
    sim_dir = str(sim_env / sim_id)
    _write_actions(sim_dir, [
        {"round": 1, "timestamp": "t", "event_type": "world_update", "headline": "r1", "period_label": "2026-Q3",
         "arbiter_status": "applied", "decisions": 3, "facts_changed": 1},
        {"round": 2, "timestamp": "t", "event_type": "world_update", "headline": "r2", "period_label": "2026-Q4",
         "arbiter_status": "failed", "decisions": 3, "facts_changed": 0},
        {"round": 1, "timestamp": "t", "event_type": "world_update", "headline": "stale duplicate"},
    ])
    state = SimulationRunState(simulation_id=sim_id)
    SimulationRunner._read_action_log(os.path.join(sim_dir, "twitter", "actions.jsonl"), 0, state, "twitter")
    wm = state.options["world_model"]
    assert wm["round"] == 2 and wm["headline"] == "r2" and wm["arbiter_status"] == "failed"
    assert wm["period_label"] == "2026-Q4" and wm["decisions"] == 3
    assert state.to_dict()["options"]["world_model"]["round"] == 2


def test_stale_world_artifacts_are_rotated_on_rerun():
    stale = set(SimulationRunner._STALE_DERIVED_ARTIFACTS)
    assert {"world_state.json", "world_state_history.jsonl", "world_actions.jsonl", "world_digest.jsonl"} <= stale


# ----------------------------------------------------------------------------- report block
def _bare_report_agent(sim_id):
    from app.services.report_agent import ReportAgent
    a = ReportAgent.__new__(ReportAgent)
    a.simulation_id = sim_id
    a.graph_id = "g"
    a.base_simulation_id = None
    return a


def test_world_evolution_block_renders_and_is_labeled(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    _write_world(str(tmp_path / "sim_rep"))
    block = _bare_report_agent("sim_rep")._world_evolution_block()
    assert block.startswith("【世界演化轨迹（elicited model projection")
    assert "已推演 3 个时段" in block and "追踪变量 2 个" in block
    assert "⚠️ 其中 1 个时段的仲裁更新失败" in block
    assert "· Tariff rate: 10% → 25%（2026-Q3） → 25%（2026-Q4）" in block
    assert "决定性行动：" in block and "2026-Q3: Impose or raise a tariff → Actor1" in block
    assert "Actor1 holds position" not in block
    assert "联盟/对立变动：" in block and "2026-Q3: Actor0 — Actor1 → adversarial" in block
    assert block.rstrip().endswith("现实世界的定量声明只能来自研究来源。")
    # absent artifacts → empty (legacy / hours runs unchanged)
    assert _bare_report_agent("sim_none")._world_evolution_block() == ""


def test_collect_viz_artifacts_includes_world_state(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    _write_world(str(tmp_path / "sim_viz"))
    agent = _bare_report_agent("sim_viz")
    agent.actors = None
    agent._forecast_spine = None
    agent.official_data = None
    monkeypatch.setattr(type(agent), "_locate_timeline", lambda self: None, raising=False)
    monkeypatch.setattr(type(agent), "_locate_handoff_dir", lambda self: None, raising=False)
    arts = agent._collect_viz_artifacts("rep", str(tmp_path / "report"))
    assert arts["world_state"]["committed_round"] == 3
    assert "world_state_trajectory" not in arts


# ----------------------------------------------------------------------------- chart
def test_world_variables_chart_indexes_numeric_histories(tmp_path):
    from app.services.report_visualizer import ReportVisualizer
    viz = ReportVisualizer()
    if not viz._interactive_ok():
        pytest.skip("plotly unavailable")
    charts = str(tmp_path / "charts")
    rel = viz.build_world_variables_html(_world_state_payload(), charts)
    assert rel is not None
    html = open(os.path.join(str(tmp_path), rel), encoding="utf-8").read()
    assert "Simulated World Variables" in html and "Tariff rate" in html
    assert "2026-Q3" in html and "250" in html                                 # 25/10 → index 250
    assert "Permit" not in html                                                 # categorical variables are not charted
    assert viz.build_world_variables_html({"world": {"variables": []}}, charts) is None
    assert viz.build_world_variables_html("garbage", charts) is None


# ----------------------------------------------------------------------------- orchestrator summary
def test_decision_channel_outcome_logs_world_model(tmp_path, monkeypatch):
    from app.services import pipeline_orchestrator as po
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    sim_dir = str(tmp_path / "sim_orch")
    _write_world(sim_dir)
    with open(os.path.join(sim_dir, "simulation_config.json"), "w", encoding="utf-8") as f:
        json.dump({"world_state_seed": {"scenarios": ["A", "B"]}}, f)
    saved = {}
    monkeypatch.setattr(po.PipelineManager, "save", lambda state: saved.setdefault("state", state))

    class _State:
        pipeline_id = "pipe_x"
        options = {}

    orch = po.PipelineOrchestrator.__new__(po.PipelineOrchestrator)
    orch._log_decision_channel_outcome(_State(), "sim_orch")
    summary = _State.options["decision_channel_summary"]
    assert summary["world_model"]["rounds_committed"] == 3 and summary["world_model"]["arbiter_failed_rounds"] == 1
    assert summary["world_headline"].startswith("2027-Q1")
    assert summary["trajectory_produced"] is False                              # no trajectory file written here


def test_world_variable_series_seed_at_as_of_and_one_point_per_period():
    from app.services.report_visualizer import world_variable_series
    world = {
        "as_of_date": "2026-07-11", "round": 4, "committed_round": 4,
        "period_labels": {"1": "2026-Q3", "2": "2026-Q4", "3": "2027-Q1", "4": "2027-Q2"},
        "variables": [
            {"id": "tariff_rate", "name": "Tariff rate", "unit": "%", "kind": "numeric", "history": [
                {"round": 0, "value": 10.0, "cause": "seed", "source": "research"},
                {"round": 2, "value": 25.0, "cause": "effect fired", "source": "effect"},
                {"round": 2, "value": 30.0, "cause": "decree", "source": "arbiter"},     # same period: last wins
                {"round": 4, "value": 40.0, "cause": "snapback", "source": "arbiter"},
                {"round": 4, "value": "bad", "cause": "ignored"}]},
            {"id": "licences", "name": "Licences issued", "unit": "count", "kind": "numeric", "history": [
                {"round": 3, "value": 5, "cause": "arbiter created the fact", "source": "arbiter"},
                {"round": 4, "value": 6, "cause": "more", "source": "arbiter"}]},
            {"id": "permit", "name": "Permit", "unit": "", "kind": "categorical",
             "history": [{"round": 0, "value": "pending"}, {"round": 1, "value": "granted"}]},
            {"id": "flat", "name": "Seed only", "unit": "%", "kind": "numeric",
             "history": [{"round": 0, "value": 3.0, "cause": "seed"}]},
            "garbage",
        ],
    }
    rows = world_variable_series(world)
    assert [r["id"] for r in rows] == ["tariff_rate", "licences"]              # categorical / seed-only / junk skipped
    tariff = rows[0]
    assert tariff["x"] == ["2026-07-11", "2026-Q3", "2026-Q4", "2027-Q1", "2027-Q2"]   # seed at the as-of date
    assert tariff["rounds"] == [0, 1, 2, 3, 4] and len(set(tariff["x"])) == len(tariff["x"])
    assert tariff["y"] == [100.0, 100.0, 300.0, 300.0, 400.0]                 # last value of the period, carried
    assert tariff["raw"] == [10.0, 10.0, 30.0, 30.0, 40.0]
    assert tariff["hover"] == ["10 % — seed (research, as of 2026-07-11)", "10 % — unchanged", "30 % — decree",
                               "30 % — unchanged", "40 % — snapback"]
    created = rows[1]                                                          # an arbiter-created variable starts later
    assert created["x"] == ["2027-Q1", "2027-Q2"] and created["y"] == [100.0, 120.0]
    assert created["hover"][0] == "5 count — arbiter created the fact"
    # no committed round recorded → the history's last round bounds the axis; no as-of → "seed"
    bare = world_variable_series({"variables": [{"kind": "numeric", "history": [
        {"round": 0, "value": 2}, {"round": 2, "value": 1}]}]})
    assert bare[0]["x"] == ["seed", "period 1", "period 2"] and bare[0]["y"] == [100.0, 100.0, 50.0]
    assert world_variable_series("garbage") == [] and world_variable_series({"variables": []}) == []


def test_world_variables_chart_starts_at_seed_without_duplicates(tmp_path):
    from app.services.report_visualizer import ReportVisualizer
    viz = ReportVisualizer()
    if not viz._interactive_ok():
        pytest.skip("plotly unavailable")
    payload = _world_state_payload()
    payload["world"]["variables"][0]["history"].append(
        {"round": 2, "value": 30.0, "cause": "second row of the period", "source": "arbiter"})
    charts = str(tmp_path / "charts")
    rel = viz.build_world_variables_html(payload, charts)
    assert rel is not None
    html = open(os.path.join(str(tmp_path), rel), encoding="utf-8").read()
    assert '"2026-07-11"' in html and '"2026-Q3"' in html and '"2027-Q1"' in html   # seed at as-of, one x per period
    assert '"categoryarray":["2026-07-11","2026-Q3","2026-Q4","2027-Q1"]' in html
    assert "300" in html and "second row of the period" in html and "unchanged" in html
    assert html.count('"2026-Q4"') == 2                                       # one point + the axis order, no duplicate
