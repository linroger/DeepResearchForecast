"""T9 — one source of truth for simulation provenance strings (ADR 0003, design §3.5).

Every consumer of a simulation label — chart titles, the executive brief, the
lint whitelist, the dashboard badge — must take it from
``app.services.sim_provenance``.  A literal copy anywhere else is the drift
this test exists to catch.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services import sim_provenance as sp

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend" / "src" / "components" / "research"

# Wording that presents simulation output as analysis, evidence or a viewpoint.
LAUNDERING_LABELS = (
    "scenario panel", "analytical perspective", "evidence-based assessment",
    "scenario analysis", "情景推演专家视角", "专家小组", "证据分析",
)


def test_every_english_constant_has_a_chinese_twin():
    names = [n for n in dir(sp)
             if n.isupper() and n.endswith("_EN") and isinstance(getattr(sp, n), str)]
    assert names, "no *_EN string constants found"
    for name in names:
        twin = name[:-3] + "_ZH"
        assert hasattr(sp, twin), f"{name} has no {twin}"
        assert getattr(sp, name).strip() and getattr(sp, twin).strip()


def test_simulated_chart_titles_say_simulated():
    for title in (sp.CHART_OUTCOME_SHARES_EN, sp.CHART_WORLD_VARIABLES_EN):
        assert title.lower().startswith("simulated"), title
        assert "forecast" not in title.lower(), title
    for title in (sp.CHART_OUTCOME_SHARES_ZH, sp.CHART_WORLD_VARIABLES_ZH):
        assert title.startswith(("模拟", "推演")), title
        assert "预测" not in title, title
    assert sp.CHART_PLACEMENT_HINT == "simulation"
    assert sp.chart_title("worldstate_trajectory") == sp.CHART_OUTCOME_SHARES_EN
    assert sp.chart_title("worldstate_trajectory", "zh") == sp.CHART_OUTCOME_SHARES_ZH
    assert sp.chart_title("world_variables", "zh-CN") == sp.CHART_WORLD_VARIABLES_ZH
    with pytest.raises(KeyError):
        sp.chart_title("scenario_probabilities")


def test_is_simulated_chart_recognises_id_hint_title_and_legacy_title():
    assert sp.is_simulated_chart({"id": "worldstate_trajectory"})
    assert sp.is_simulated_chart({"id": "world_variables"})
    assert sp.is_simulated_chart({"placement_hint": "simulation", "id": "x"})
    assert sp.is_simulated_chart({"title": sp.CHART_OUTCOME_SHARES_EN, "id": "x"})
    # A manifest written before the retitle must still be recognised.
    assert sp.is_simulated_chart({"title": "Forecast Outcome-Share Trajectory", "id": "x"})
    assert not sp.is_simulated_chart({"id": "scenario_probabilities", "placement_hint": "scenarios",
                                      "title": "Scenario Probabilities"})
    assert not sp.is_simulated_chart("not a dict")
    assert not sp.is_simulated_chart(None)


def test_quote_labels_carry_no_laundering_wording():
    joined = " | ".join(sp.SIM_QUOTE_LABELS).lower()
    for bad in LAUNDERING_LABELS:
        assert bad.lower() not in joined, bad
    assert sp.SIM_LABEL_EN in sp.SIM_QUOTE_LABELS
    assert sp.SIM_LABEL_ZH in sp.SIM_QUOTE_LABELS


def test_banner_and_brief_line_deny_evidence_and_probability_status():
    for text in (sp.SIM_BANNER_EN.lower(), sp.BRIEF_SIM_LINE_EN.lower()):
        assert ("not " in text or "never " in text) and "probabilit" in text
    assert "非观察事实" in sp.SIM_BANNER_ZH and "非校准概率" in sp.SIM_BANNER_ZH
    assert "{health}" in sp.BRIEF_SIM_LINE_EN and "{health}" in sp.BRIEF_SIM_LINE_ZH
    assert "{detail}" in sp.BRIEF_SIM_LINE_EN and "{detail}" in sp.BRIEF_SIM_LINE_ZH
    assert sp.BRIDGE_START.startswith("<!--") and sp.BRIDGE_END.startswith("<!--")
    assert sp.OUTCOME_SHARES_HEADER_ZH != sp.OUTCOME_SHARES_HEADER_LEGACY_ZH


@pytest.mark.skipif(not FRONTEND.is_dir(), reason="frontend sources not present")
def test_dashboard_badge_and_caveat_match_the_constants():
    panel = (FRONTEND / "WorldStatePanel.vue").read_text(encoding="utf-8")
    world = (FRONTEND / "WorldSimulationView.vue").read_text(encoding="utf-8")
    # L('<zh>', '<en>') i18n call sites; both languages must match the constants.
    badge_call = re.compile(
        r"L\(\s*'" + re.escape(sp.SIM_BADGE_ZH) + r"'\s*,\s*'" + re.escape(sp.SIM_BADGE_EN) + r"'\s*\)")
    caveat_call = re.compile(
        r"L\(\s*'" + re.escape(sp.SIM_CAVEAT_ZH) + r"'\s*,\s*'" + re.escape(sp.SIM_CAVEAT_EN) + r"'\s*\)")
    assert badge_call.search(panel), "WorldStatePanel badge drifted from sim_provenance"
    assert caveat_call.search(world), "WorldSimulationView caveat drifted from sim_provenance"
