"""Durable quality policy at the real report caller, including old recovery."""
import json

import pytest

from app.config import Config
from app.services import forecast_extractor as fe
from app.services.pipeline_orchestrator import capture_safety_policy_v1
from app.services.report_agent import ReportManager
from tests.conftest import FakeLLMClient
from test_context_audit_report import make_agent, policy_fixture
from test_forecast_binary_resilience import _balanced_rows


@pytest.mark.parametrize("origin,expected", [("admission", fe.BINARY_QUALITY_POLICY),
    ("resume_reconstructed_safe", fe.LEGACY_BINARY_QUALITY_POLICY)])
def test_fresh_and_reconstructed_policy_are_durably_distinct(origin, expected):
    saved = json.loads(json.dumps(capture_safety_policy_v1(origin)))
    assert saved["binary_quality_policy"] == expected


@pytest.mark.parametrize("saved", [None, {}, {"binary_quality_policy": fe.BINARY_QUALITY_POLICY},
                                  {"binary_quality_policy": fe.LEGACY_BINARY_QUALITY_POLICY}])
def test_actual_finalize_retains_saved_policy(make_agent, monkeypatch, saved):
    monkeypatch.setattr(Config, "FORECAST_EMIT_BINARY", True)
    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", False)
    monkeypatch.setattr(Config, "REPORT_REPAIR_PASSES", 0)
    monkeypatch.setattr(fe, "_cfg", lambda name, default=None: default)
    policy = policy_fixture(**saved) if saved is not None else None
    expected = (saved or {}).get("binary_quality_policy", fe.LEGACY_BINARY_QUALITY_POLICY)
    agent = make_agent(report_policy=policy, research_report="Fixed research evidence is balanced.")
    # Mutation of caller-owned input must not change this report's methods.
    if policy is not None:
        policy["binary_quality_policy"] = "unknown/v99"
    agent._forecast_spine = {"schema_version": 1, "headline": "Capacity outlook", "horizon": "2027-06-30",
        "confidence": "low", "scenarios": [{"name": "Expansion", "probability": 1.0,
            "summary": "Conditional on permission", "resolution_criteria": "Capacity > 10 GW by 2027-06-30"}]}
    agent.llm = FakeLLMClient(json_responses=[{"binary_forecasts": _balanced_rows()}, {"binary_forecasts": []}])
    monkeypatch.setattr(agent, "_binary_min_count", lambda: 5)
    rid = "report_policy_saved"
    folder = ReportManager._ensure_report_folder(rid)
    agent._finalize_structured_forecast(rid, "# Capacity outlook\n\nEvidence remains uncertain.")
    from pathlib import Path
    forecast = json.loads((Path(folder) / "forecast.json").read_text())
    assert forecast["binary_forecasts"]
    assert {r["quality_policy"] for r in forecast["binary_forecasts"]} == {expected}
    requests = json.dumps(agent.llm.calls)
    if expected == fe.BINARY_QUALITY_POLICY:
        assert "justified uncertainty" in requests
        assert "CONTRARIAN FRAMING" not in requests
        assert forecast["binary_quality"]["distribution_diagnostics"]
    else:
        assert "CONTRARIAN FRAMING" in requests


def test_explicit_invalid_saved_policy_rejected_before_model(make_agent):
    with pytest.raises(ValueError, match="binary quality policy"):
        make_agent(report_policy=policy_fixture(binary_quality_policy="unknown/v99"))
