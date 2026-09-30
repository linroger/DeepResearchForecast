"""REPORT-11: the symmetric binary guard (FORECAST_BINARY_SYMMETRIC_GUARD, default off).

With the knob on, every binary draw prompt carries the SYMMETRY GUARD sentence right after
the round's contrarian-framing or low-probability rule (both rules stay verbatim); with it
off, every prompt is byte-identical. The policy is visible in forecast.quality.forecast_policy
whatever FORECAST_PROBABILITY_SHAPE says, and in the admission snapshot
(capture_safety_policy_v1), which forks inherit.

Offline: scripted chat_json stubs; no network, no real LLM.
"""

import json
import os

import pytest

from app.config import Config
from app.services import forecast_extractor as fe
from app.services import pipeline_orchestrator as po
from app.services.report_agent import ReportAgent, ReportManager


class _JsonLLM:
    """chat_json stub scripted per prompt marker; records every prompt."""

    def __init__(self, router):
        self.router = router
        self.prompts = []

    def chat_json(self, messages=None, temperature=0.2, max_tokens=2048, **kw):
        content = messages[-1]["content"]
        self.prompts.append(content)
        return self.router(content)


def _rows(probs, prefix="Forecast"):
    return [{"statement": f"{prefix} number {i} resolves by 2027 at over {i}%.",
             "probability": p, "resolution_criteria": "Index above 10% by 2027-12-31 (WTO)",
             "theme": "ai", "horizon_year": 2027}
            for i, p in enumerate(probs, 1)]


def _router(content):
    if "0.05-0.35 range" in content:  # the low-p reframe pass
        return {"binary_forecasts": _rows([0.1, 0.2, 0.25], prefix="Contrarian")}
    return {"binary_forecasts": _rows([0.7, 0.72, 0.74, 0.71, 0.73,
                                       0.7, 0.72, 0.74, 0.71, 0.73])}


def _draw_prompts(monkeypatch, *, guard, contrarian=True):
    monkeypatch.setattr(Config, "FORECAST_BINARY_CONTRARIAN", contrarian, raising=False)
    monkeypatch.setattr(Config, "FORECAST_BINARY_SYMMETRIC_GUARD", guard, raising=False)
    llm = _JsonLLM(_router)
    fe.extract_binary_forecasts("dossier", llm, min_count=10)
    prompts = [p for p in llm.prompts if p.startswith(fe._BINARY_FORECAST_INSTRUCTIONS[:80])]
    assert prompts and len(prompts) == len(llm.prompts)
    return prompts


def test_guard_text_never_trips_the_rule_markers():
    guard = fe._BINARY_SYMMETRIC_GUARD
    assert guard.startswith("\nSYMMETRY GUARD:")
    assert "Do not manufacture extremity to look decisive." in guard
    assert "0.05-0.35 range" not in guard and "CONTRARIAN FRAMING" not in guard


def test_knob_on_every_draw_prompt_carries_the_guard(monkeypatch):
    prompts = _draw_prompts(monkeypatch, guard=True)
    low_p = [p for p in prompts if "0.05-0.35 range" in p]
    first = [p for p in prompts if p not in low_p]
    assert len(low_p) == 1 and first  # the low-p reframe ran once
    assert all("SYMMETRY GUARD" in p for p in prompts)
    assert all("CONTRARIAN FRAMING" in p for p in first)
    # the guard follows the round's rule immediately; both rules stay verbatim
    assert all(fe._BINARY_CONTRARIAN_RULE + fe._BINARY_SYMMETRIC_GUARD in p for p in first)
    assert fe._BINARY_LOW_P_RULE + fe._BINARY_SYMMETRIC_GUARD in low_p[0]


def test_knob_off_prompts_are_byte_identical(monkeypatch):
    off = _draw_prompts(monkeypatch, guard=False)
    on = _draw_prompts(monkeypatch, guard=True)
    assert all("SYMMETRY GUARD" not in p for p in off)
    # the guard sentence is the only difference, so knob-off prompts are the pre-REPORT-11 bytes
    assert off == [p.replace(fe._BINARY_SYMMETRIC_GUARD, "") for p in on]


def test_guard_follows_the_rules_only(monkeypatch):
    """With contrarian framing off there is no rule to qualify: no guard either."""
    prompts = _draw_prompts(monkeypatch, guard=True, contrarian=False)
    assert all("SYMMETRY GUARD" not in p and "CONTRARIAN FRAMING" not in p for p in prompts)


def test_default_is_off_and_documented():
    assert Config.FORECAST_BINARY_SYMMETRIC_GUARD is False
    assert Config.FORECAST_PROBABILITY_SHAPE is True
    env_example = os.path.join(os.path.dirname(__file__), "..", "..", ".env.example")
    with open(env_example, encoding="utf-8") as fh:
        text = fh.read()
    assert "# FORECAST_BINARY_SYMMETRIC_GUARD=false" in text
    assert "# FORECAST_PROBABILITY_SHAPE=true" in text


# ------------------------------------------------------------------ policy visibility
def _bare_agent(tmp_path, report_id):
    a = ReportAgent.__new__(ReportAgent)
    spine = {"headline": "h", "horizon": "2030", "confidence": "medium",
             "confidence_rationale": "r", "schema_version": 1, "critiqued": True,
             "scenarios": [
                 {"name": "Adopted", "probability": 0.6, "summary": "s",
                  "resolution_criteria": "OJ publication by 2030"},
                 {"name": "Other / Status Quo", "probability": 0.4, "summary": "s",
                  "resolution_criteria": "no publication by 2030"}]}
    defaults = {
        "llm": None, "graph_id": "g1", "simulation_id": "sim1",
        "simulation_requirement": "Will the directive pass?", "situation_brief": "",
        "actors": None, "sources": [], "research_report": "", "output_language": "English",
        "scenario_label": "", "base_simulation_id": None, "_signal_pack": "",
        "_market_pack": "", "_forecast_spine": spine, "_forecast_spine_block": "",
        "_citation_index": None, "report_logger": None, "console_logger": None, "tools": {},
    }
    for key, value in defaults.items():
        setattr(a, key, value)
    (tmp_path / "reports" / report_id).mkdir(parents=True)
    return a


@pytest.fixture
def finalize_env(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    for name, value in (("FORECAST_EMIT_BINARY", False), ("REPORT_REPAIR_PASSES", False),
                        ("REPORT_FORECAST_SELF_CRITIQUE", False),
                        ("REPORT_PUBLISH_GATE", False), ("REPORT_FORECAST_LEDGER", False)):
        monkeypatch.setattr(Config, name, value, raising=False)
    return tmp_path


def _finalize(tmp_path, report_id):
    _bare_agent(tmp_path, report_id)._finalize_structured_forecast(report_id, "# T\n\nBody.")
    with open(os.path.join(str(tmp_path), "reports", report_id, "forecast.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.parametrize("shape_on", [False, True])
def test_forecast_policy_is_recorded_independent_of_telemetry(finalize_env, monkeypatch,
                                                               shape_on):
    monkeypatch.setattr(Config, "FORECAST_BINARY_SYMMETRIC_GUARD", True, raising=False)
    monkeypatch.setattr(Config, "FORECAST_PROBABILITY_SHAPE", shape_on, raising=False)
    quality = _finalize(finalize_env, f"r_policy_{shape_on}")["quality"]
    assert quality["forecast_policy"] == {"binary_symmetric_guard": True}
    if shape_on:
        assert quality["probability_shape"]["policy"] == {"binary_symmetric_guard": True}
    else:
        assert "probability_shape" not in quality


def test_guard_off_writes_no_policy_key(finalize_env, monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_BINARY_SYMMETRIC_GUARD", False, raising=False)
    monkeypatch.setattr(Config, "FORECAST_PROBABILITY_SHAPE", False, raising=False)
    forecast = _finalize(finalize_env, "r_no_policy")
    assert "forecast_policy" not in (forecast.get("quality") or {})
    assert "probability_shape" not in (forecast.get("quality") or {})


def test_admission_snapshot_pins_the_guard_and_forks_inherit_it(monkeypatch):
    assert po.capture_safety_policy_v1("admission")["forecast_binary_symmetric_guard"] is False
    monkeypatch.setattr(Config, "FORECAST_BINARY_SYMMETRIC_GUARD", True, raising=False)
    pinned = po.capture_safety_policy_v1("admission")
    assert pinned["forecast_binary_symmetric_guard"] is True
    json.dumps(pinned)
    # INFRA-9: a fork keeps the base's pin even after the ambient knob changes
    monkeypatch.setattr(Config, "FORECAST_BINARY_SYMMETRIC_GUARD", False, raising=False)
    fork = po.fork_safety_policy_v1({"safety_policy_v1": pinned})
    assert fork["forecast_binary_symmetric_guard"] is True and fork["origin"] == "fork_inherited"
