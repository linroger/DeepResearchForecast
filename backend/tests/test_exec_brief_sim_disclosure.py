"""T7 (executive brief half) — the brief discloses what the simulation was for and
never promotes a simulated chart to the load-bearing chart (ADR 0003, S0.3).
"""
from __future__ import annotations

import json
import os

from app.services import exec_brief as eb
from app.services import sim_provenance as sp


def _report_dir_with_health(tmp_path, health: str = "ok", organic: int | None = 412):
    upload = tmp_path / "uploads"
    report_dir = upload / "reports" / "report_t7"
    report_dir.mkdir(parents=True)
    (report_dir / "telemetry.json").write_text(
        json.dumps({"totals": {"run_id": "pipe_t7"}}), encoding="utf-8")
    pipe = upload / "pipelines" / "pipe_t7"
    pipe.mkdir(parents=True)
    (pipe / "pipeline_state.json").write_text(json.dumps({"options": {"pipeline_health": {
        "status": "ok",
        "stages": {"run": {"health": health, "organic_actions": organic}},
    }}}), encoding="utf-8")
    return str(report_dir)


def test_honesty_note_discloses_simulation_role_en(tmp_path):
    note = eb._build_honesty_note(None, _report_dir_with_health(tmp_path), eb._LABELS["en"])
    expected = sp.BRIEF_SIM_LINE_EN.format(health="ok", detail=", 412 organic actions")
    assert expected in note
    assert "never probabilities" in note and "diagnostic_only" in note
    assert "simulation run ok" not in note  # the old bare health fragment is gone


def test_honesty_note_discloses_simulation_role_zh(tmp_path):
    note = eb._build_honesty_note(None, _report_dir_with_health(tmp_path, "hollow", 0), eb._LABELS["zh"])
    expected = sp.BRIEF_SIM_LINE_ZH.format(health="hollow", detail="，0 条有机行为")
    assert expected in note
    assert "从不进入概率" in note


def test_honesty_note_omits_detail_when_no_organic_count(tmp_path):
    report_dir = _report_dir_with_health(tmp_path, "ok", organic=None)
    note = eb._build_honesty_note(None, report_dir, eb._LABELS["en"])
    assert sp.BRIEF_SIM_LINE_EN.format(health="ok", detail="") in note


def _write_manifest(report_dir, entries, schema_v2=True):
    os.makedirs(os.path.join(report_dir, "charts"), exist_ok=True)
    for e in entries:
        with open(os.path.join(report_dir, e["path"]), "wb") as fh:
            fh.write(b"png")
    payload = {"schema_version": 2, "items": entries, "skipped": []} if schema_v2 else entries
    with open(os.path.join(report_dir, "viz_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def test_find_scenario_chart_skips_simulated_charts_even_with_stale_hint(tmp_path):
    report_dir = str(tmp_path)
    # A manifest written by the pre-ADR visualizer: simulated chart filed under "scenarios".
    _write_manifest(report_dir, [
        {"id": "worldstate_trajectory", "type": "png", "placement_hint": "scenarios",
         "title": "Forecast Outcome-Share Trajectory", "caption": "Forecast Outcome-Share Trajectory",
         "path": "charts/worldstate_trajectory.png"},
        {"id": "world_variables", "type": "png", "placement_hint": "scenarios",
         "title": sp.CHART_WORLD_VARIABLES_EN, "path": "charts/world_variables.png"},
    ])
    assert eb._find_scenario_chart(report_dir) is None


def test_find_scenario_chart_skips_simulated_charts_in_legacy_list_manifest(tmp_path):
    report_dir = str(tmp_path)
    _write_manifest(report_dir, [
        {"id": "worldstate_trajectory", "type": "png", "placement_hint": "scenarios",
         "title": "Forecast Outcome-Share Trajectory", "path": "charts/worldstate_trajectory.png"},
    ], schema_v2=False)
    assert eb._find_scenario_chart(report_dir) is None


def test_find_scenario_chart_still_returns_the_scenario_bars(tmp_path):
    report_dir = str(tmp_path)
    _write_manifest(report_dir, [
        {"id": "worldstate_trajectory", "type": "png", "placement_hint": sp.CHART_PLACEMENT_HINT,
         "title": sp.CHART_OUTCOME_SHARES_EN, "path": "charts/worldstate_trajectory.png"},
        {"id": "scenario_probabilities", "type": "png", "placement_hint": "scenarios",
         "title": "Scenario Probabilities", "caption": "Scenario Probabilities",
         "path": "charts/scenario_probabilities.png"},
    ])
    found = eb._find_scenario_chart(report_dir)
    assert found is not None
    rel, caption = found
    assert rel == "charts/scenario_probabilities.png"
    assert caption == "Scenario Probabilities"
