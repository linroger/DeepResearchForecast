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

from app.services import exec_brief as eb
from app.services import report_lint as rl
from app.services import report_visualizer as rv
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


# ── Consumers (S0.2–S0.5): no literal copies, no laundering labels ───────────

BACKEND = REPO_ROOT / "backend" / "app" / "services"


def test_visualizer_and_brief_take_their_strings_from_the_constants():
    assert rv.CHART_TITLES_ZH[sp.CHART_OUTCOME_SHARES_EN] == sp.CHART_OUTCOME_SHARES_ZH
    assert rv.CHART_TITLES_ZH[sp.CHART_WORLD_VARIABLES_EN] == sp.CHART_WORLD_VARIABLES_ZH
    assert eb._LABELS["en"]["sim_line"] == sp.BRIEF_SIM_LINE_EN
    assert eb._LABELS["zh"]["sim_line"] == sp.BRIEF_SIM_LINE_ZH
    for name in ("report_visualizer.py", "exec_brief.py"):
        src = (BACKEND / name).read_text(encoding="utf-8")
        assert "Forecast Outcome-Share Trajectory" not in src, name
        assert "预测结果份额轨迹" not in src, name
        assert "simulation run" not in src, name


def test_frontend_gallery_captions_carry_the_simulated_titles():
    js = (REPO_ROOT / "frontend" / "src" / "utils" / "vizManifest.js").read_text(encoding="utf-8")
    assert f"'{sp.CHART_OUTCOME_SHARES_EN}': '{sp.CHART_OUTCOME_SHARES_ZH}'" in js
    assert f"'{sp.CHART_WORLD_VARIABLES_EN}': '{sp.CHART_WORLD_VARIABLES_ZH}'" in js
    assert "Forecast Outcome-Share Trajectory" not in js


def test_report_agent_quote_labels_are_the_constants():
    from app.services.report_agent import ReportAgent
    assert tuple(ReportAgent._SIM_QUOTE_LABELS) == tuple(sp.SIM_QUOTE_LABELS)
    src = (BACKEND / "report_agent.py").read_text(encoding="utf-8")
    # The laundering *instructions* are gone (the system prompt may still name
    # "scenario panel" inside its ban list, which is the opposite of an instruction).
    for bad in ("our scenario analysis indicates", "attribute analytical viewpoints to our",
                "情景推演专家视角——", '"scenario panel", "analytical perspective"',
                "转写为专家小组式的分析视角", "只能作为**证据输入**"):
        assert bad not in src, bad
    assert "【预测结果分布" not in src  # the shares header comes from the constant


def test_lint_has_no_relabel_as_evidence_rewrites():
    assert not hasattr(rl, "rewrite_sim_labels")
    for _pattern, replacement in rl._SIMULATION_OUTCOME_REWRITES:
        low = str(replacement).lower()
        # "the evidence base" for the research *dossier* is legitimate (the dossier is
        # evidence); the forbidden targets are the ones that dressed simulation output.
        for bad in ("the evidence indicates", "available evidence", "forecast evidence base",
                    "evidence-based", "public position", "现有证据", "研究证据", "证据分析"):
            assert bad not in low, replacement


def test_visualizer_and_extractor_still_load_standalone_from_their_file_paths():
    """report_visualizer and forecast_extractor are loaded by path (no package) in
    tests/test_kaleido_exit.py; the constants import must survive that."""
    import importlib.util
    for name in ("report_visualizer.py", "forecast_extractor.py"):
        spec = importlib.util.spec_from_file_location(f"standalone_{name[:-3]}", BACKEND / name)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module._sp.CHART_OUTCOME_SHARES_EN == sp.CHART_OUTCOME_SHARES_EN


def test_every_reader_facing_string_survives_the_final_lint():
    """A provenance label the lint deletes is worse than none: the content stays
    and the label goes.  Every string this module hands to report prose or to a
    chart caption must produce no leakage hit and must come through
    lint_report(mode='final') byte-identical."""
    strings = [
        sp.CHART_OUTCOME_SHARES_EN, sp.CHART_OUTCOME_SHARES_ZH,
        sp.CHART_WORLD_VARIABLES_EN, sp.CHART_WORLD_VARIABLES_ZH,
        sp.WHATIF_TABLE_TITLE_ZH, sp.WHATIF_TABLE_NOTE_ZH.lstrip("> "),
        sp.BRIDGE_TITLE_EN, sp.BRIDGE_TITLE_ZH, sp.SIM_BANNER_EN, sp.SIM_BANNER_ZH,
        sp.BRIEF_SIM_LINE_EN.format(health="ok", detail=""), sp.BRIEF_SIM_LINE_ZH.format(health="ok", detail=""),
    ]
    for text in strings:
        assert rl.leakage_hits(text) == [], text
        for lang in ("English", "Chinese"):
            out, rep = rl.lint_report(text, lang, mode="final")
            assert out == text, (lang, text, out)
            assert rep["simulation_mechanics"]["sentences_removed"] == 0
    for alt in (sp.CHART_OUTCOME_SHARES_EN, sp.CHART_OUTCOME_SHARES_ZH,
                sp.CHART_WORLD_VARIABLES_EN, sp.CHART_WORLD_VARIABLES_ZH):
        line = f"![{alt}](charts/x.png)"
        out, _rep = rl.lint_report(line, "English", mode="final")
        assert out == line, line
