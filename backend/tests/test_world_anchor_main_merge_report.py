"""Combined main/World Anchor report contracts through real offline consumers."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.config import Config
from app.services import forecast_extractor as fe
from app.services import report_agent as ra
from tests.conftest import FakeLLMClient
from test_final_publish_audit import _agent
from test_target_report import simulation


@pytest.fixture
def case():
    return json.loads((Path(__file__).parent / "fixtures/target_case.json").read_text())


@pytest.mark.parametrize("mode", ["fail", "grade"])
@pytest.mark.parametrize("threshold", [0.0, 1.0])
def test_grounding_checks_independent_citation_scope_even_in_grade_mode(monkeypatch, mode, threshold):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MODE", mode)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", threshold)
    agent = _agent({"title": "Adoption", "url": "https://example.gov/adoption",
                    "supports": ["Official adoption reached 55.6%."]})
    source = ("# Evidence\n\n<span></span> **Official adoption reached 55.6%.** [S1] "
              "Unsupported adoption reached 99%.\n")
    # The legacy coverage splitter can give this entire atom the first claim's
    # citation. Grade mode and even a zero coverage threshold must still run
    # main's parsed inline ownership checks before any publication decision.
    with pytest.raises(ValueError, match="independent citation scope"):
        agent._repair_final_quantitative_grounding(source)


@pytest.mark.parametrize("mode", ["fail", "grade"])
def test_grounding_retains_grade_claims_and_exact_code_carriers(monkeypatch, mode):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MODE", mode)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 1.0)
    claim = "Unsupported adoption reached **99%.**\n\n"
    carrier = '```python\nvalue = "99%. ** [S77]"\n```\n'
    source = "# Evidence\n\n" + claim + carrier
    result, audit = _agent()._repair_final_quantitative_grounding(source)
    assert carrier in result
    assert audit["passed"] is True
    if mode == "grade":
        assert result == source
        assert audit["unverifiable_claims_preserved"] == 1
        assert audit["coverage_met"] is False
    else:
        assert claim not in result
        assert audit["sentences_removed"] == 1
        assert audit["coverage_met"] is True


@pytest.mark.parametrize("mode", ["fail", "grade"])
def test_evidence_quality_coexists_with_grade_scorecard(monkeypatch, mode):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MODE", mode)
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_MODELS", "")
    rows = [{"statement": f"Agency measure {i} exceeds 10 GW by 2027-06-30",
             "probability": 0.5,
             "resolution_criteria": "Agency operational capacity > 10 GW on 2027-06-30",
             "resolution_source": "Agency register", "theme": "capacity"}
            for i in range(5)]
    model = FakeLLMClient(json_responses=[{"binary_forecasts": rows}])
    result = fe.extract_binary_forecasts(
        "The evidence supports a balanced assessment.", model, min_count=5,
        binary_quality_policy=fe.BINARY_QUALITY_POLICY, forecast_case=None,
        report_policy={"report_spine_selfconsistency_k": 1, "ensemble_extremize_a": 1.0,
                       "simulation_forecast_effect": "diagnostic_only"})
    assert len(model.calls) == 1
    assert all(row["probability"] == 0.5 for row in result["binary_forecasts"])
    assert all(row["quality_policy"] == fe.BINARY_QUALITY_POLICY for row in result["binary_forecasts"])
    score = result["binary_quality"]
    verdict = "legacy_passed" if mode == "grade" else "passed"
    assert score[verdict] is True
    assert score["distribution_diagnostics"]
    assert score["policy_version"] == fe.BINARY_QUALITY_POLICY
    old = [{key: value for key, value in row.items() if key != "quality_policy"}
           for row in result["binary_forecasts"]]
    assert fe._binary_quality(old, min_count=5)[verdict] is False
    prompt = json.dumps(model.calls)
    assert "CONTRARIAN FRAMING" not in prompt and "do not cluster" not in prompt


def test_typed_extraction_accepts_both_keywords_without_model_calls(case, monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_BINARIES_SOURCE", "tree")
    model = FakeLLMClient()
    before = deepcopy(case)
    result = fe.extract_binary_forecasts(
        "Prose is not probability authority.", model, forecast_case=case,
        binary_quality_policy=fe.BINARY_QUALITY_POLICY)
    assert result["binary_forecasts"] == fe.derive_binaries_from_tree(case)["binary_forecasts"]
    assert result["binary_forecasts"][0]["probability"] == 0.6
    assert model.calls == [] and case == before


def test_typed_report_pins_main_quality_policy_and_keeps_zero_simulation_authority(case, monkeypatch, tmp_path):
    monkeypatch.setattr(ra.ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True)
    policy = {"report_spine_selfconsistency_k": 1, "ensemble_extremize_a": 1.0,
              "simulation_forecast_effect": "diagnostic_only",
              "binary_quality_policy": fe.BINARY_QUALITY_POLICY}

    def forbidden(*args, **kwargs):
        pytest.fail("Typed report attempted legacy state or provider acquisition")

    monkeypatch.setattr(ra, "LLMClient", forbidden)
    monkeypatch.setattr(ra, "ZepToolsService", forbidden)
    monkeypatch.setattr(ra, "load_simulation_world", forbidden)
    agent = ra.ReportAgent("graph_merge", "sim_merge", case["question"],
                           report_policy=policy, forecast_case=case,
                           target_simulation=simulation(case))
    policy["binary_quality_policy"] = "invalid-after-admission"
    assert agent._binary_quality_policy == fe.BINARY_QUALITY_POLICY
    report = agent.generate_report(report_id="report_merge_policy")
    assert report.status == ra.ReportStatus.COMPLETED, report.error
    assert ra.ReportManager.publication_status(report.report_id)["publishable"]
    folder = Path(ra.ReportManager._get_report_folder(report.report_id))
    forecast = json.loads((folder / "forecast.json").read_text())
    record = json.loads((folder / "target_report.json").read_text())
    assert [row["probability"] for row in forecast["scenarios"]] == [0.4, 0.6]
    assert forecast["binary_forecasts"][0]["probability"] == 0.6
    assert record["simulationWeight"] == 0.0
    assert agent._audit_target_authority(report.report_id, forecast, report.markdown_content)["valid"]


def test_typed_constructor_rejects_unsupported_main_quality_policy_before_dispatch(case, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid saved policy reached typed or provider initialization")

    monkeypatch.setattr(ra.ReportAgent, "_init_target_report", forbidden)
    monkeypatch.setattr(ra, "LLMClient", forbidden)
    with pytest.raises(ValueError, match="binary quality policy"):
        ra.ReportAgent("graph_merge", "sim_merge", case["question"], forecast_case=case,
                       report_policy={"report_spine_selfconsistency_k": 1,
                                      "ensemble_extremize_a": 1.0,
                                      "simulation_forecast_effect": "diagnostic_only",
                                      "binary_quality_policy": "unknown/v99"})
