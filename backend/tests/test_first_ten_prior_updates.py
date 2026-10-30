"""The actual default spine path must preserve its frozen update contract."""
from copy import deepcopy
import json

import pytest

from app.config import Config
from app.services import forecast_extractor as fe
from app.services.report_agent import ReportAgent, ReportManager


@pytest.fixture
def original():
    rows = [{"name": "Expansion", "probability": 0.6,
             "resolution_criteria": "Revenue > 100 in 2027."},
            {"name": "Other / status quo", "probability": 0.4,
             "resolution_criteria": "Revenue <= 100 in 2027."}]
    result = {"headline": "Revenue?", "horizon": "2027-12-31", "scenarios": rows}
    prior = {"scenarioWeights": {r["name"]: r["probability"] for r in rows}, "asOf": "2026-10-27"}
    return fe.validate_prior_posterior_updates(result, prior, [
        {"name": r["name"], "prior": r["probability"], "posterior": r["probability"], "reason": ""}
        for r in rows])


class Gateway:
    def __init__(self, replies):
        self.replies, self.calls = deepcopy(replies), []

    def chat_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies.pop(0)


def critique(original, *, reason=True):
    result = deepcopy(original)
    for row in result["scenarios"]:
        row["probability"] = 0.5
        if reason:
            row["critique_note"] = "S1: audited revenue revision weakens the expansion case."
    return result


def test_default_spine_persists_current_ledger(original, monkeypatch, tmp_path):
    for name, value in {"REPORT_SPINE_RESEARCH_PRIOR": True, "REPORT_FORECAST_SELF_CRITIQUE": True,
                        "REPORT_CRITIQUE_BEFORE_PROSE": True, "REPORT_PREMORTEM": False,
                        "REPORT_SPINE_SELFCONSISTENCY_K": 1}.items():
        monkeypatch.setattr(Config, name, value)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    agent = ReportAgent.__new__(ReportAgent)
    agent.actors = {"as_of_date": "2026-10-27", "forecast_inputs": {"scenarios": original["scenarios"]}}
    agent.simulation_requirement, agent.output_language = "Revenue?", "English"
    agent.llm = Gateway([original, critique(original)])
    agent._market_pack, agent._data_pack = "No stored markets.", ""
    agent._forecast_situation_brief = lambda: ""
    agent._temporal_horizon_date = lambda: "2027-12-31"
    agent._simulation_forecast_effect = lambda: "diagnostic_only"
    agent._official_pack_kwargs = lambda: {}
    folder = tmp_path / "reports" / "report_prior"
    folder.mkdir(parents=True)
    agent._derive_and_pin_forecast_spine("report_prior")
    saved = json.loads((folder / "forecast.json").read_text())
    assert len(agent.llm.calls) == 2
    assert [r["probability"] for r in saved["scenarios"]] == [0.5, 0.5]
    assert [r["prior"] for r in saved["scenarios"]] == [0.6, 0.4]
    assert fe.validate_prior_posterior_updates(deepcopy(saved), saved["research_prior"], saved["scenario_updates"]) == saved
    assert all("S1: audited revenue revision" in u["reason"] for u in saved["scenario_updates"])


@pytest.mark.parametrize("mutation", ["missing_reason", "blank_reason", "renamed", "added", "removed"])
def test_unaccounted_critique_keeps_original(original, mutation):
    changed = critique(original, reason=mutation != "missing_reason")
    if mutation == "blank_reason":
        changed["scenarios"][0]["critique_note"] = "  "
    if mutation == "renamed":
        changed["scenarios"][0]["name"] = "A different event"
    if mutation == "added":
        changed["scenarios"].append({"name": "New", "probability": 0.1})
    if mutation == "removed":
        changed["scenarios"].pop()
    before = deepcopy(original)
    assert fe.self_critique_forecast(original, Gateway([changed])) == before
    assert original == before


def test_unchanged_precise_prior_retains_exact_probabilities(original):
    for row, p in zip(original["scenarios"], [0.00123456789, 0.99876543211]):
        row["probability"] = p
    prior = {"scenarioWeights": {r["name"]: r["probability"] for r in original["scenarios"]}, "asOf": "2026-10-27"}
    fe.validate_prior_posterior_updates(original, prior, [
        {"name": r["name"], "prior": r["probability"], "posterior": r["probability"], "reason": ""}
        for r in original["scenarios"]])
    result = fe.self_critique_forecast(original, Gateway([original]))
    assert result["scenarios"] == original["scenarios"]
    assert result["scenario_updates"] == original["scenario_updates"]


@pytest.mark.parametrize("reasons", [[], ["S2: new audited downside observation."], "Unstructured rationale", [17]])
def test_premortem_requires_actual_rationale_and_rebinds_ledger(original, monkeypatch, reasons):
    monkeypatch.setattr(Config, "REPORT_PREMORTEM", True)
    reply = {"underweighted_scenario": "Other / status quo", "overconfident_scenario": "Expansion",
             "missed_signals": reasons}
    result = fe.premortem_forecast(original, Gateway([reply]))
    if isinstance(reasons, list) and reasons and isinstance(reasons[0], str):
        assert [r["probability"] for r in result["scenarios"]] == [0.55, 0.45]
        assert all(reasons[0] in u["reason"] for u in result["scenario_updates"])
        fe.validate_prior_posterior_updates(deepcopy(result), result["research_prior"], result["scenario_updates"])
    else:
        assert result == original


def test_prior_free_critique_keeps_legacy_behavior(original, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SPINE_RESEARCH_PRIOR", False)
    legacy = {k: v for k, v in original.items() if k not in ("research_prior", "scenario_updates")}
    for row in legacy["scenarios"]:
        row.pop("prior", None)
    result = fe.self_critique_forecast(legacy, Gateway([critique(legacy, reason=False)]))
    assert result["critiqued"] is True
    assert [r["probability"] for r in result["scenarios"]] == [0.5, 0.5]
    assert "research_prior" not in result and "scenario_updates" not in result
