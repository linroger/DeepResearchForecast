"""Reader-facing signals of the reflexive world model (offline; 2026-10-20 reader iteration).

The kernel records red-line crossings, per-actor track records and expectation checks
(tests/test_world_reflexivity.py); this module pins how they reach readers:

* the report's world-evolution block lists red-line crossings and the actors with broken or
  lapsed commitments, bounded and still labelled an elicited model projection, and renders
  byte-for-byte what it rendered before when a run carries neither;
* GET /world-state returns each actor's track record and, per history row, the red lines the
  period crossed (the panel's past-period view once the round's events left the event window);
* ``frontend/tests/fixtures/world/world_state.reflexive.json``, the payload the panel tests read,
  is exactly what this API returns for the reflexivity scenario run through the real kernel.
  Regenerate it with ``DRF_WRITE_FIXTURES=1`` after a deliberate change.
"""

import json
import os

import pytest

from app.config import Config
from app.services import world_update as wu
from app.services.agent_decision import build_option_menu
from tests.test_world_model_downstream import _bare_report_agent, _world_state_payload, _write_world
from tests.test_world_reflexivity import SCENARIOS, _Arbiter, _decision, _world

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "frontend", "tests", "fixtures",
                       "world", "world_state.reflexive.json")

# what _world_evolution_block rendered for the downstream fixture before red lines and track
# records reached it (b8cc994; the same bytes, SHA-256 df3d715f…, from the old and the new code)
LEGACY_BLOCK = "\n".join([
    "【世界演化轨迹（elicited model projection——模型引出的推演投影，非观察证据；仅供机制分析，不得据此调整概率）】",
    "已推演 3 个时段；追踪变量 2 个，世界事件 5 条",
    "⚠️ 其中 1 个时段的仲裁更新失败（仅机械推进），该段轨迹可信度下调",
    "· Tariff rate: 10% → 25%（2026-Q3） → 25%（2026-Q4）",
    "决定性行动：",
    "· 2026-Q3: Impose or raise a tariff → Actor1",
    "· 2027-Q1: Open an inquiry → Actor0",
    "联盟/对立变动：",
    "· 2026-Q3: Actor0 — Actor1 → adversarial",
    "注：世界变量由推演仲裁逐期更新并有界钳制，不是观察到的现实指标；现实世界的定量声明只能来自研究来源。",
])


def _write_payload(sim_dir, payload):
    os.makedirs(sim_dir, exist_ok=True)
    with open(os.path.join(sim_dir, "world_state.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def _record(kept=0, lapsed=0, broken=0, released=0, open_=0, outcomes=None):
    resolved = kept + lapsed + broken
    return {"kept": kept, "lapsed": lapsed, "broken": broken, "released": released, "open": open_,
            "resolved": resolved, "reliability": round(kept / resolved, 3) if resolved else None,
            "outcomes": outcomes or {}, "reputation": 0.5}


# ----------------------------------------------------------------------------- report block
def test_the_block_is_byte_identical_without_red_lines_or_breakers(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    _write_world(str(tmp_path / "sim_legacy"))                      # a run from before (no new fields)
    assert _bare_report_agent("sim_legacy")._world_evolution_block() == LEGACY_BLOCK
    # a new run whose actors kept or released every commitment, plus junk records: nothing is added
    payload = _world_state_payload()
    payload["world"]["actors"][0]["track_record"] = _record(kept=2, released=1, open_=1, outcomes={"success": 2})
    payload["world"]["actors"][1]["track_record"] = "junk"
    payload["world"]["actors"].append({"agent_id": 2, "name": "Actor2", "track_record": {"broken": True, "lapsed": -3}})
    payload["world"]["actors"].append("junk")
    payload["world"]["events"].append({"round": 3, "kind": "red_line", "description": "   "})   # blank → no line
    _write_payload(str(tmp_path / "sim_clean"), payload)
    with open(tmp_path / "sim_legacy" / "world_state_history.jsonl", encoding="utf-8") as src, \
            open(tmp_path / "sim_clean" / "world_state_history.jsonl", "w", encoding="utf-8") as dst:
        dst.write(src.read())
    assert _bare_report_agent("sim_clean")._world_evolution_block() == LEGACY_BLOCK


def test_the_block_lists_red_line_crossings_and_breakers_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    payload = _world_state_payload()
    world = payload["world"]
    for r in range(1, 6):
        world["events"].append({
            "round": r, "kind": "red_line", "actors": ["Actor0"], "targets": ["Actor1"], "source": "arbiter",
            "description": f"Actor0 crossed Actor1's red line: No tariffs above {r}0%" + (" — " + "x" * 400 if r == 5 else ""),
            **({"period_label": f"P{r}"} if r != 3 else {})})
    world["actors"][0]["track_record"] = _record(kept=1, lapsed=1, broken=1, outcomes={"success": 1})
    world["actors"][1]["track_record"] = _record(lapsed=2)
    world["actors"] += [
        {"agent_id": 2, "name": "Actor2", "track_record": _record(kept=3)},                 # clean → not listed
        {"agent_id": 3, "name": "Actor3"},                                                   # no record → not listed
        {"agent_id": 4, "name": "Actor4", "track_record": _record(broken=3)},
        {"agent_id": 5, "track_record": _record(kept=4, lapsed=1)},                          # unnamed → "Agent 5"
    ]
    _write_payload(str(tmp_path / "sim_sig"), payload)
    block = _bare_report_agent("sim_sig")._world_evolution_block()
    lines = block.split("\n")
    assert lines[0] == LEGACY_BLOCK.split("\n")[0]                                       # still a model projection
    assert lines[-1] == LEGACY_BLOCK.split("\n")[-1]                                     # the closing caveat stays last
    head = lines.index("红线越界（推演仲裁认定，共 5 次，列最近 4 次）：")
    assert lines[head + 1:head + 5] == [
        "· P2: Actor0 crossed Actor1's red line: No tariffs above 20%",
        "· 2027-Q1: Actor0 crossed Actor1's red line: No tariffs above 30%",           # no label → the world's
        "· P4: Actor0 crossed Actor1's red line: No tariffs above 40%",
        "· P5: " + ("Actor0 crossed Actor1's red line: No tariffs above 50% — " + "x" * 400)[:220],
    ]
    rec = lines.index("承诺履约（推演内记录，非现实信誉评估）：")
    assert rec == head + 5
    # breakers first: most broken + lapsed, then most broken, then most kept
    assert lines[rec + 1:-1] == ["· Actor4：兑现 0/3，违约 3", "· Actor0：兑现 1/3，违约 1，失效 1",
                                 "· Actor1：兑现 0/2，失效 2", "· Agent 5：兑现 4/5，失效 1"]
    assert "Actor2" not in block and "Actor3" not in block
    # the bounds are parameters
    small = _bare_report_agent("sim_sig")._world_evolution_block(max_red_lines=1, max_records=1).split("\n")
    assert "红线越界（推演仲裁认定，共 5 次，列最近 1 次）：" in small
    assert small[small.index("承诺履约（推演内记录，非现实信誉评估）：") + 1:-1] == ["· Actor4：兑现 0/3，违约 3"]


def test_four_or_fewer_crossings_are_listed_without_a_cut_note(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    payload = _world_state_payload()
    payload["world"]["events"].append({"round": 2, "kind": "red_line", "description": "A crossed B's red line: x"})
    _write_payload(str(tmp_path / "sim_one"), payload)
    lines = _bare_report_agent("sim_one")._world_evolution_block().split("\n")
    head = lines.index("红线越界（推演仲裁认定，共 1 次）：")
    assert lines[head + 1] == "· 2026-Q4: A crossed B's red line: x"
    assert not any(line.startswith("承诺履约") for line in lines)


# ----------------------------------------------------------------------------- the real kernel, end to end
def _history_row(record, label):
    """The fields of a world_state_history.jsonl row the readers use, as the runner writes them."""
    det = record.get("deterministic") or {}
    return {"round": record["round"], "period": record.get("period"), "period_label": label,
            "decisions": record.get("decisions"),
            "deterministic": {k: v for k, v in det.items()
                              if k in ("scheduled_events", "actions", "commitments_lapsed", "offers_opened",
                                       "offers_answered", "offers_lapsed", "breaches")}
            | {"effects_fired": [fx.get("description") for fx in det.get("effects_fired", [])]},
            "behaviour": record.get("behaviour") or {}, "arbiter_status": record.get("arbiter_status"),
            "arbiter_problems": record.get("arbiter_problems") or [], "arbiter": record.get("arbiter") or {},
            "narrative": record.get("narrative") or "", "diff": record.get("diff") or {},
            "scenario_pressure": record.get("scenario_pressure") or {}, "headline": record.get("headline") or ""}


def _reflexive_run(sim_dir):
    """Periods 1–4 of the reflexivity scenario: a 145% tariff crosses China's red line, China answers
    (the US expected it to back down), talks open, and the US withdraws when China accepts."""
    world = _world()
    arbiter = _Arbiter([
        {"narrative": "The tariff jumps; Beijing calls it a red line.",
         "variable_changes": [{"variable_id": "us_tariff_on_chinese_goods", "new_value": 145,
                               "caused_by": "United States Government", "rationale": "executive order"}],
         "red_line_crossings": [{"actor": "China Ministry of Commerce", "by": "United States Government",
                                 "red_line": "tariffs above 100% on Chinese goods", "rationale": "145% announced"}],
         "action_resolutions": [{"actor": "United States Government", "outcome": "success"}],
         "scenario_pressure": {"Escalation": "up", "Truce": "down"}},
        {"narrative": "Retaliation follows.",
         "action_resolutions": [{"actor": "China Ministry of Commerce", "outcome": "partial"}],
         "scenario_pressure": {"Escalation": "up"}},
        {"narrative": "Talks open.", "scenario_pressure": {"Truce": "up"}},
        {"narrative": "Washington walks away.", "scenario_pressure": {"Escalation": "up"}},
    ])
    us, cn = "United States Government", "China Ministry of Commerce"

    def response(round_num, option_id, *, statement, scenario=None):
        option = next(o for o in build_option_menu(world.actors[1], world, round_num)
                      if o["id"] == option_id)
        return _decision(1, cn, option["id"], option["kind"], targets=[us], statement=statement,
                         scenario=scenario, option=option)

    plan = [
        ("2026-04", lambda: [_decision(0, us, "impose_measure", "policy", targets=[cn],
                                       statement="Tariffs on Chinese goods rise to 145% from Thursday.",
                                       expected=[(cn, "back down and seek talks")], scenario="Escalation")]),
        ("2026-05", lambda: [response(2, "respond_1_counter",
                                       statement="Counter-tariffs of 125% take effect.", scenario="Escalation"),
                             _decision(0, us, "hold_position", "wait")]),
        ("2026-06", lambda: [_decision(0, us, "open_talks", "coalition", targets=[cn],
                                       statement="We propose a 90-day pause.",
                                       terms="Both sides cut tariffs to 10% for 90 days", scenario="Truce")]),
        ("2026-07", lambda: [response(4, f"accept:{next(i for i, it in world.interactions.items() if it.is_open())}",
                                     statement="Agreed."),
                             _decision(0, us, "break_alliance", "coalition", targets=[cn],
                                       statement="We withdraw from the pause.")]),
    ]
    rows, record = [], {}
    for rnd, (label, decisions) in enumerate(plan, start=1):
        record = wu.run_world_round(world, rnd, {"label": label}, decisions(), [], llm=arbiter, rng=None,
                                    scenarios=SCENARIOS)
        rows.append(_history_row(record, label))
    behaviour: dict = {"rounds_scored": 0, "moves": 0, "responsive_moves": 0, "offers_answered": 0,
                 "expectations_checked": 0, "expectations_reacted": 0}
    for row in rows:                                   # the run summary's sums (runner _world_summary)
        beh = row["behaviour"]
        if beh.get("responsive_share") is not None:
            behaviour["rounds_scored"] += 1
            for key in ("moves", "responsive_moves", "offers_answered"):
                behaviour[key] += int(beh.get(key) or 0)
        behaviour["expectations_checked"] += int(beh.get("expectations_checked") or 0)
        behaviour["expectations_reacted"] += int(beh.get("expectations_reacted") or 0)
    behaviour["responsive_share"] = (round(behaviour["responsive_moves"] / behaviour["moves"], 3)
                                     if behaviour["moves"] else None)
    summary = {"schema_version": "world-model-summary/v1", "rounds_committed": len(rows),
               "variables": len(world.variables), "actors": len(world.actors),
               "relationships": len(world.relationships), "events": len(world.events),
               "pending_effects": len(world.pending_effects), "arbiter_enabled": True, "arbiter_failed_rounds": 0,
               "seed_gaps": 0, "behaviour": behaviour}
    _write_payload(sim_dir, {"schema_version": "world-state-file/v1", "simulation_id": os.path.basename(sim_dir),
                             "committed_round": len(rows), "brief": world.render_public_brief(upto_round=len(rows)),
                             "digest": record["digest"], "headline": record["headline"], "summary": summary,
                             "world": world.to_dict()})
    with open(os.path.join(sim_dir, "world_state_history.jsonl"), "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return world


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_the_kernel_run_reaches_the_report_block(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    world = _reflexive_run(str(tmp_path / "sim_reflexive"))
    assert world.track_record(0)["broken"] == 1 and world.track_record(1)["released"] == 1
    lines = _bare_report_agent("sim_reflexive")._world_evolution_block().split("\n")
    head = lines.index("红线越界（推演仲裁认定，共 1 次）：")
    assert lines[head + 1] == ("· 2026-04: United States Government crossed China Ministry of Commerce's red line: "
                               "No tariffs above 100% on Chinese goods — 145% announced")
    rec = lines.index("承诺履约（推演内记录，非现实信誉评估）：")
    assert lines[rec + 1:-1] == ["· United States Government：兑现 0/2，违约 1，失效 1"]  # tariff pledge lapsed; China released
    assert "%" not in "".join(lines[rec:-1])                                           # no shares, no probabilities


def test_the_api_carries_track_records_and_red_lines_per_period(client, tmp_path):
    _reflexive_run(str(tmp_path / "sim_reflexive"))
    data = client.get("/api/simulation/sim_reflexive/world-state").get_json()["data"]
    records = {a["name"]: a["track_record"] for a in data["actors"]}
    assert records["United States Government"]["broken"] == 1 and records["United States Government"]["kept"] == 0
    assert records["United States Government"]["outcomes"] == {"success": 1}
    assert records["China Ministry of Commerce"]["released"] == 1
    assert data["summary"]["behaviour"]["expectations_checked"] == 1
    assert data["summary"]["behaviour"]["expectations_reacted"] == 1
    rows = {h["round"]: h for h in data["history"]}
    assert rows[1]["red_lines_crossed"] == [{"actor": "China Ministry of Commerce", "by": "United States Government",
                                             "red_line": "No tariffs above 100% on Chinese goods"}]
    assert all("red_lines_crossed" not in rows[r] for r in (2, 3, 4))                # absent when none
    assert "arbiter" not in rows[1] and "shares" not in rows[1]
    assert [e["kind"] for e in data["recent_events"]].count("red_line") == 1


def test_the_round_headline_counts_red_line_crossings(tmp_path):
    """The headline's "events" are the arbiter's emergent events; a crossing used to leave the
    period reading "0 events".  It now has its own count, and only when there is one."""
    _reflexive_run(str(tmp_path / "sim_headline"))
    with open(tmp_path / "sim_headline" / "world_state_history.jsonl", encoding="utf-8") as f:
        headlines = [json.loads(line)["headline"] for line in f]
    assert headlines[0].startswith("2026-04: 1 decisions · 0 facts changed · 0 events · 1 red line crossed · "
                                   "arbiter=applied · ")
    assert all("red line" not in h.split(" · arbiter=")[0] for h in headlines[1:])
    record = {"deterministic": {"decisions": 2}, "diff": {}, "arbiter_status": "applied",
              "arbiter": {"events": 1, "red_lines_crossed": [{"actor": "A", "by": "B", "red_line": "x"}] * 2}}
    world = _world()
    world.period = {"label": "P1"}
    assert wu.world_update_headline(world, 1, record) == "P1: 2 decisions · 0 facts changed · 1 events · " \
                                                         "2 red lines crossed · arbiter=applied"
    record["arbiter"] = {"events": 1}                                                # none → unchanged form
    assert wu.world_update_headline(world, 1, record) == "P1: 2 decisions · 0 facts changed · 1 events · arbiter=applied"


def test_the_api_bounds_red_line_rows_and_skips_junk(client, tmp_path):
    sim = tmp_path / "sim_rl"
    _write_world(str(sim), with_history=False)
    crossing = {"actor": "A" * 300, "by": "B", "red_line": "No x", "rationale": "dropped", "extra": 1}
    with open(sim / "world_state_history.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"round": 1, "arbiter": {"red_lines_crossed": ["junk", crossing] + [crossing] * 5}}) + "\n")
        f.write(json.dumps({"round": 2, "arbiter": {"red_lines_crossed": "junk"}}) + "\n")
        f.write(json.dumps({"round": 3, "arbiter": "junk"}) + "\n")
    rows = client.get("/api/simulation/sim_rl/world-state").get_json()["data"]["history"]
    assert rows[0]["red_lines_crossed"] == [{"actor": "A" * 160, "by": "B", "red_line": "No x"}] * 3   # 4 scanned
    assert "red_lines_crossed" not in rows[1] and "red_lines_crossed" not in rows[2]


def test_the_panel_fixture_is_what_the_api_returns(client, tmp_path):
    if not os.path.isdir(os.path.dirname(os.path.dirname(FIXTURE))):
        pytest.skip("frontend tests are not part of this copy")
    _reflexive_run(str(tmp_path / "sim_reflexive"))
    data = client.get("/api/simulation/sim_reflexive/world-state?rows=48").get_json()["data"]
    # Export the actual API payload inside pytest's evidence root. Copy this file
    # deliberately after review; DRF_WRITE_FIXTURES still requires a repo write.
    actual_fixture = tmp_path / "world_state.reflexive.actual.json"
    actual_fixture.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                              encoding="utf-8")
    if os.environ.get("DRF_WRITE_FIXTURES") == "1":
        os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
        with open(FIXTURE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
    with open(FIXTURE, encoding="utf-8") as f:
        assert json.load(f) == data, f"review the actual API export at {actual_fixture} before updating the fixture"
