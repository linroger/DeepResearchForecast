"""REPORT-10 (C14): rendered-prompt pins for the estimation walls, plus the binary draw's
de-duplicated market exposure.

- Spine sim wall: under SIMULATION_FORECAST_EFFECT=diagnostic_only the spine prompt that
  ReportAgent actually sends carries no 【模拟量化信号】 block; legacy_prompt restores it.
- FORECAST_DRAW_DOSSIER_STRIP_MARKET_TABLE (default off): with a live market pack injected,
  the binary draw's dossier view drops the bridge's machine-appended
  "## Prediction Market Signals" table (fence-aware), so market prices reach _draw only
  through the live pack; binary_quality.market_table_stripped records the count and survives
  ReportAgent's rescore into forecast.json. Knob off → prompts byte-identical.
- seed_scenario_pin: names + resolution criteria only.

Offline: FakeLLMClient / routed chat_json stubs, no network.
"""

from __future__ import annotations

import copy
import json
import os

import pytest

from app.config import Config
from app.services import forecast_extractor as fe
from app.services import forecast_ledger
from app.services.forecast_extractor import strip_machine_market_table
from app.services.pipeline_orchestrator import seed_scenario_pin
from app.services.report_agent import ReportAgent, ReportManager

from tests.conftest import FakeLLMClient

_SPINE = {
    "headline": "h", "horizon": "2030", "confidence": "medium",
    "scenarios": [
        {"name": "Rapid adoption", "probability": 0.6, "summary": "s", "key_drivers": ["d"],
         "resolution_criteria": "Index above 12% by 2030"},
        {"name": "Status quo", "probability": 0.4, "summary": "s", "key_drivers": ["d"],
         "resolution_criteria": "Index at or below 12% by 2030"},
    ],
}
_SIGNAL_PACK = "【推演结果分布 P(outcome)】\n· Rapid adoption: 62%\n· Status quo: 38%"

# What the research bridge appends to research_report.md (deerflow_research._pm_render_section).
_BRIDGE_TABLE = (
    "## Prediction Market Signals\n"
    "\n"
    "> Machine-fetched from Polymarket (public Gamma API) as of 2026-09-01. Market-implied "
    "probabilities are **calibration anchors, not ground truth**.\n"
    "\n"
    "### Prediction Market Signals (Polymarket)\n"
    "\n"
    "| # | Market question | Venue | Implied P(yes) | Volume |\n"
    "|---|---|---|---|---|\n"
    "| 1 | Will the AI capex boom stall in 2027? (m-stale) | polymarket | 23% | 91,000 |\n"
)
_DOSSIER_BODY = (
    "# AI capex outlook\n"
    "\n"
    "## Conclusions\n"
    "\n"
    "Hyperscaler capex keeps growing through 2027 [S1].\n"
    "\n"
    "```markdown\n"
    "## Prediction Market Signals\n"
    "| quoted example row kept verbatim | 99% |\n"
    "```\n"
)
_DOSSIER = _DOSSIER_BODY + "\n" + _BRIDGE_TABLE
_LIVE_PACK = ("### Prediction Market Signals (Polymarket)\n\n"
              "| # | Market question | Venue | Implied P(yes) | Volume |\n|---|---|---|---|---|\n"
              "| 1 | Will the AI capex boom stall in 2027? (m-live) | polymarket | 31% | 95,000 |")
_BINARY = {"statement": "US hyperscaler capex exceeds $500B in 2027", "probability": 0.35,
           "resolution_criteria": "Sum of reported 2027 capex of the top four hyperscalers",
           "theme": "capex", "horizon_year": 2027}


# ------------------------------------------------------------------ spine sim wall

def _spine_agent(llm):
    agent = ReportAgent.__new__(ReportAgent)
    agent.actors = {}
    agent.llm = llm
    agent.simulation_requirement = "q"
    agent.situation_brief = ""
    agent._signal_pack = _SIGNAL_PACK
    agent._market_pack = ""
    agent._forecast_spine = None
    agent._forecast_spine_block = ""
    return agent


@pytest.mark.parametrize("effect, present", [("diagnostic_only", False), ("legacy_prompt", True)])
def test_spine_sim_wall_prompt_capture(effect, present, monkeypatch, tmp_path):
    monkeypatch.setattr(ReportAgent, "_temporal_horizon_date", lambda self: "")
    monkeypatch.setattr(ReportManager, "_get_report_folder",
                        classmethod(lambda cls, rid: str(tmp_path)))
    monkeypatch.setattr(Config, "REPORT_FORECAST_SELF_CRITIQUE", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 1, raising=False)
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", effect, raising=False)
    llm = FakeLLMClient(json_responses=[copy.deepcopy(_SPINE)])
    agent = _spine_agent(llm)

    agent._derive_and_pin_forecast_spine("r_wall")

    assert agent._forecast_spine and agent._forecast_spine["scenarios"]  # the draw really ran
    prompts = [m["content"] for call in llm.calls for m in call["messages"]]
    assert prompts, "the spine draw must reach the LLM"
    spine_prompt = prompts[0]
    assert ("[模拟量化信号]" in spine_prompt) is present
    assert ("推演结果分布 P(outcome)" in spine_prompt) is present
    if not present:
        assert not any("[模拟量化信号]" in p for p in prompts)


# ------------------------------------------------------- dossier market-table strip

def test_strip_machine_market_table_removes_bridge_section_only():
    out, n = strip_machine_market_table(_DOSSIER)
    assert n == 1
    assert out == _DOSSIER_BODY
    # the fenced heading (a quoted example) and its row survive
    assert "```markdown\n## Prediction Market Signals\n| quoted example row kept verbatim" in out
    assert "(m-stale)" not in out and "### Prediction Market Signals (Polymarket)" not in out


def test_strip_machine_market_table_block_bounds():
    text = ("intro\n"
            "## Prediction Market Signals  \n"
            "| stale | 20% |\n"
            "```\n"
            "## not a boundary inside a fence\n"
            "```\n"
            "### sub-table\n"
            "| stale | 21% |\n"
            "## Next Section\n"
            "kept\n"
            "## Prediction Market Signals\n"
            "| stale | 22% |\n"
            "# Appendix\n"
            "tail\n")
    out, n = strip_machine_market_table(text)
    assert n == 2
    assert out == "intro\n## Next Section\nkept\n# Appendix\ntail\n"


def test_strip_machine_market_table_no_match_is_identity():
    for text in ("", "# Report\n\nNo markets here.\n",
                 "## Prediction Market Signals and more\nbody\n",   # different title
                 "### Prediction Market Signals (Polymarket)\n| a | 1% |\n",  # H3 only
                 "~~~\n## Prediction Market Signals\n~~~\n"):       # fenced only
        out, n = strip_machine_market_table(text)
        assert n == 0 and out == text
    assert strip_machine_market_table(None) == ("", 0)


def _draw_prompts(llm):
    return [m["content"] for call in llm.calls for m in call["messages"]
            if "[Research dossier]" in m["content"]]


def _extract(monkeypatch, *, knob, market_pack=_LIVE_PACK, dossier=_DOSSIER):
    """Run the real binary extraction; ``knob=None`` leaves the Config default in place."""
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)
    if knob is not None:
        monkeypatch.setattr(Config, "FORECAST_DRAW_DOSSIER_STRIP_MARKET_TABLE", knob,
                            raising=False)
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_MODELS", "", raising=False)
    llm = FakeLLMClient(json_responses=[{"binary_forecasts": [dict(_BINARY)]}])
    out = fe.extract_binary_forecasts(dossier, llm, min_count=1, market_pack=market_pack)
    return out, _draw_prompts(llm)


def test_binary_draw_dossier_strip(monkeypatch):
    out, prompts = _extract(monkeypatch, knob=True)
    assert prompts, "the binary draw must reach the LLM"
    for prompt in prompts:
        pre, dossier_view = prompt.split("[Research dossier]", 1)
        # market prices reach the draw only through the live pack
        assert "[Prediction market signals]" in pre and "(m-live)" in pre
        assert "(m-stale)" not in prompt
        assert dossier_view == "\n" + _DOSSIER_BODY
        assert "\n## Prediction Market Signals\n| quoted example" in dossier_view
        dossier_outside_fence = dossier_view.replace(
            "```markdown\n## Prediction Market Signals\n", "")
        assert "## Prediction Market Signals" not in dossier_outside_fence
    assert out["binary_quality"]["market_table_stripped"] == 1
    assert out["binary_forecasts"][0]["statement"] == _BINARY["statement"]


def test_binary_draw_dossier_knob_off_keeps_legacy_prompt(monkeypatch):
    out, prompts = _extract(monkeypatch, knob=False)
    assert prompts
    for prompt in prompts:
        dossier_view = prompt.split("[Research dossier]", 1)[1]
        assert dossier_view == "\n" + _DOSSIER            # the dossier reaches _draw verbatim
        assert "(m-stale)" in dossier_view
    assert "market_table_stripped" not in out["binary_quality"]


def test_binary_draw_strip_knob_defaults_off(monkeypatch):
    assert Config.FORECAST_DRAW_DOSSIER_STRIP_MARKET_TABLE is False
    out_default, default = _extract(monkeypatch, knob=None)
    out_off, off = _extract(monkeypatch, knob=False)
    assert default == off and default
    assert out_default["binary_quality"] == out_off["binary_quality"]
    assert "market_table_stripped" not in out_default["binary_quality"]


def test_binary_draw_strip_needs_the_live_pack(monkeypatch):
    """Without an injected market pack the dossier table is the only market view: keep it,
    so the knob-on prompt is byte-identical to the knob-off prompt."""
    _, on = _extract(monkeypatch, knob=True, market_pack="")
    _, off = _extract(monkeypatch, knob=False, market_pack="")
    assert on == off and on
    assert all("(m-stale)" in prompt for prompt in on)


def test_binary_draw_strip_frees_tail_budget(monkeypatch):
    """The table sits at the end of the dossier; stripped before head+tail slicing, the
    conclusions it used to push out of the tail budget reach the draw again."""
    monkeypatch.setattr(Config, "FORECAST_BINARY_EXTRACT_BUDGET", 600, raising=False)
    long_body = ("# Report\n\n" + "Background paragraph.\n" * 60
                 + "\n## Conclusions\n\nKEY-CONCLUSION: capex keeps rising [S1].\n\n")
    dossier = long_body + _BRIDGE_TABLE
    _, off = _extract(monkeypatch, knob=False, dossier=dossier)
    _, on = _extract(monkeypatch, knob=True, dossier=dossier)
    assert all("KEY-CONCLUSION" not in p.split("[Research dossier]", 1)[1] for p in off)
    assert all("KEY-CONCLUSION" in p.split("[Research dossier]", 1)[1] for p in on)


# ------------------------------------ market_table_stripped survives the report rescore

class _RoutedLLM(FakeLLMClient):
    """Binary draws (prompts carrying the dossier) get one binary; every other call a spine."""

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, tier=None, **kwargs):
        self.calls.append({"kind": "chat_json", "messages": messages, "tier": tier})
        if "[Research dossier]" in messages[0]["content"]:
            return {"binary_forecasts": [dict(_BINARY)]}
        return copy.deepcopy(_SPINE)


def _finalize_agent(llm):
    agent = ReportAgent.__new__(ReportAgent)
    for key, value in {
        "graph_id": "g1", "simulation_id": "sim1", "llm": llm,
        "simulation_requirement": "Will AI capex keep rising?",
        "situation_brief": "", "actors": None, "sources": [], "research_report": _DOSSIER,
        "output_language": "English", "scenario_label": "", "base_simulation_id": None,
        "_background_block": "", "_sources_index": "", "_signal_pack": "",
        "_market_pack": _LIVE_PACK, "_prediction_markets": None,
        "_forecast_spine": None, "_forecast_spine_block": "",
        "_retrieval_query": None, "_outline_degraded": False, "_outline_summary": "",
        "_section_tool_calls": 0, "report_logger": None, "console_logger": None,
        "tools": {},
    }.items():
        setattr(agent, key, value)
    return agent


def test_market_table_stripped_survives_report_rescore(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(tmp_path / "ledger"), raising=False)
    for name, value in {
        "REPORT_PUBLISH_GATE": False, "REPORT_REPAIR_PASSES": False,
        "REPORT_FORECAST_SELF_CRITIQUE": False, "REPORT_SPINE_SELFCONSISTENCY_K": 1,
        "FORECAST_EMIT_BINARY": True, "FORECAST_BINARY_THEMES": None,
        "BINARY_FORECASTS_MIN_COUNT": 1, "FORECAST_ENSEMBLE_MODELS": "",
        "PREDICTION_MARKETS_ENABLED": True, "FORECAST_DRAW_DOSSIER_STRIP_MARKET_TABLE": True,
    }.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    monkeypatch.setattr(forecast_ledger, "append_forecast", lambda forecast, **kw: None)
    llm = _RoutedLLM()

    _finalize_agent(llm)._finalize_structured_forecast("report_strip", "# T\n\nBody.")

    path = os.path.join(str(tmp_path), "reports", "report_strip", "forecast.json")
    with open(path, encoding="utf-8") as handle:
        forecast = json.load(handle)
    assert forecast["binary_forecasts"], "the real extractor ran and produced a binary"
    assert forecast["binary_quality"]["market_table_stripped"] == 1
    draws = [m["content"] for c in llm.calls for m in c["messages"]
             if "[Research dossier]" in m["content"]]
    assert draws and all("(m-stale)" not in p and "(m-live)" in p for p in draws)


# ----------------------------------------------------------------- seed scenario pin

def test_seed_scenario_pin():
    primary = {"scenarios": [
        {"name": "A", "probability": 0.7, "resolution_criteria": "x > 1",
         "summary": "s", "adjustment_rationale": "r"},
        {"name": "", "probability": 0.2, "resolution_criteria": "unnamed rows are dropped"},
        "not-a-dict",
        {"name": "B", "probability": 0.3},
    ]}
    pin = seed_scenario_pin(primary)
    assert pin == [{"name": "A", "resolution_criteria": "x > 1"},
                   {"name": "B", "resolution_criteria": None}]
    assert all(set(row) == {"name", "resolution_criteria"} for row in pin)
    for empty in ({}, {"scenarios": []}, {"scenarios": None}, None,
                  {"scenarios": 5}, {"scenarios": [{"probability": 0.5}]}):
        assert seed_scenario_pin(empty) is None
