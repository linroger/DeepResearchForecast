"""T7 — simulated charts are titled "Simulated …" and never become the report's
load-bearing chart (ADR 0003; design §3.5, change S0.2/S0.3).
"""
from __future__ import annotations

import json
import os

import pytest

from app.services import report_visualizer as rv
from app.services import sim_provenance as sp
from app.services.report_visualizer import ReportVisualizer

TRAJECTORY = {"trajectory": [
    {"round": 0, "shares": {"Base case": 0.6, "Tail case": 0.4}},
    {"round": 1, "shares": {"Base case": 0.7, "Tail case": 0.3}},
]}

WORLD_STATE = {
    "schema_version": "world-state-file/v1", "committed_round": 2,
    "world": {
        "round": 2, "committed_round": 2,
        "period_labels": {"1": "2026-Q3", "2": "2026-Q4"},
        "variables": [
            {"id": "tariff_rate", "name": "Tariff rate", "value": 15.0, "unit": "%", "kind": "numeric",
             "provenance": "arbiter", "as_of": "2026-07-01",
             "history": [{"round": 0, "value": 10.0, "cause": "seed", "source": "research"},
                         {"round": 1, "value": 12.0, "cause": "decree", "source": "arbiter"},
                         {"round": 2, "value": 15.0, "cause": "hold", "source": "arbiter"}]},
        ],
    },
}


def test_title_map_uses_the_constants():
    assert rv.CHART_TITLES_ZH[sp.CHART_OUTCOME_SHARES_EN] == sp.CHART_OUTCOME_SHARES_ZH
    assert rv.CHART_TITLES_ZH[sp.CHART_WORLD_VARIABLES_EN] == sp.CHART_WORLD_VARIABLES_ZH
    assert "Forecast Outcome-Share Trajectory" not in rv.CHART_TITLES_ZH


@pytest.mark.skipif(not rv.MATPLOTLIB_AVAILABLE, reason="matplotlib not installed")
def test_png_fallback_manifest_entry_is_simulated(tmp_path, monkeypatch):
    monkeypatch.setattr(rv, "PLOTLY_AVAILABLE", False)
    items = ReportVisualizer().build_all("t7-png", str(tmp_path),
                                         {"world_state_trajectory": TRAJECTORY})
    item = {e["id"]: e for e in items}["worldstate_trajectory"]
    assert item["title"] == sp.CHART_OUTCOME_SHARES_EN
    assert item["placement_hint"] == sp.CHART_PLACEMENT_HINT
    assert sp.is_simulated_chart(item)


@pytest.mark.skipif(not rv.PLOTLY_AVAILABLE, reason="plotly not installed")
def test_html_builders_carry_the_simulated_titles(tmp_path):
    viz = ReportVisualizer()
    charts = str(tmp_path / "charts")
    rel = viz.build_worldstate_area_html(TRAJECTORY, charts)
    assert rel
    html = (tmp_path / rel).read_text(encoding="utf-8")
    assert sp.CHART_OUTCOME_SHARES_EN in html
    assert "Forecast Outcome-Share Trajectory" not in html
    rel2 = viz.build_world_variables_html(WORLD_STATE, charts)
    assert rel2
    assert sp.CHART_WORLD_VARIABLES_EN in (tmp_path / rel2).read_text(encoding="utf-8")


@pytest.mark.skipif(not rv.PLOTLY_AVAILABLE, reason="plotly not installed")
def test_interactive_manifest_entries_are_simulated(tmp_path):
    items = ReportVisualizer().build_all(
        "t7-html", str(tmp_path),
        {"world_state_trajectory": TRAJECTORY, "world_state": WORLD_STATE})
    by_id = {e["id"]: e for e in items}
    for cid in ("worldstate_trajectory", "world_variables"):
        assert cid in by_id, cid
        assert by_id[cid]["placement_hint"] == sp.CHART_PLACEMENT_HINT
        assert by_id[cid]["title"].lower().startswith("simulated")
        assert sp.is_simulated_chart(by_id[cid])
    manifest = json.loads((tmp_path / "viz_manifest.json").read_text(encoding="utf-8"))
    entries = manifest["items"] if isinstance(manifest, dict) else manifest  # schema v2 wraps items
    sim_entries = [e for e in entries if sp.is_simulated_chart(e)]
    assert {e["id"] for e in sim_entries} == {"worldstate_trajectory", "world_variables"}
    for e in sim_entries:
        assert os.path.exists(os.path.join(str(tmp_path), e["path"]))
