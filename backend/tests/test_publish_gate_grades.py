"""F1: epistemic shortfalls disclose uncertainty; integrity still blocks publication."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from app.config import Config
from app.services.report_agent import Report, ReportAgent, ReportManager, ReportStatus


def forecast():
    return {"schema_version": 1, "headline": "Regional revenue", "horizon": "2027-12-31",
            "confidence": "high", "confidence_rationale": "Source-backed range.",
            "scenarios": [
                {"name": "Expansion", "probability": 0.6, "resolution_criteria": "Positive annual revenue growth."},
                {"name": "Other / status quo", "probability": 0.4, "resolution_criteria": "All other outcomes."}],
            "binary_forecasts": [{"id": f"B{i}", "statement": f"Region {chr(65+i)} grows next year.",
                                  "probability": 0.45 + i / 120,
                                  "resolution_criteria": "First audited annual revenue release."}
                                 for i in range(13)],
            "binary_quality": {"passed": False, "issues": ["probability spread too low (stdev 0.03) — hedging"],
                               "prob_stdev": 0.03, "midband_share": 1.0, "conviction_count": 0},
            "citation_audit": {"resolved_coverage": 0.7}, "quality": {}}


@pytest.mark.parametrize("mode,passed", [("grade", True), ("fail", False)])
def test_grade_classification_and_rollback(monkeypatch, mode, passed):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MODE", mode, raising=False)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.75)
    original = forecast()
    result = ReportAgent._apply_publish_gate(deepcopy(original))
    quality = result["quality"]
    assert quality["grade"] == "C" and len(quality["disclosures"]) == 2
    assert quality["passed"] is passed
    assert quality["hard_passed"] and quality["hard_issues"] == []
    assert result["scenarios"] == original["scenarios"]
    assert result["binary_forecasts"] == original["binary_forecasts"]
    audit = {"hard_issues": [], "publish_gate": {"enabled": True, "mode": mode, **quality}}
    if mode == "fail":
        with pytest.raises(RuntimeError, match="质量门未通过"):
            ReportAgent._require_final_publish_audit(audit)
    else:
        ReportAgent._require_final_publish_audit(audit)


@pytest.mark.parametrize("quality", [{"quote_provenance": {"ungrounded": 1}},
                                     {"numeric_consistency": {"mismatch_count": 1}}])
def test_integrity_cannot_be_downgraded_to_grade(monkeypatch, quality):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MODE", "grade", raising=False)
    original = forecast()
    original["quality"] = quality
    result = ReportAgent._apply_publish_gate(original)
    assert result["quality"]["passed"] is False
    with pytest.raises(RuntimeError, match="完整性门"):
        ReportAgent._require_final_publish_audit({"hard_issues": [],
            "publish_gate": {"enabled": True, "mode": "grade", **result["quality"]}})


def _prepared(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MODE", "grade", raising=False)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.75)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    report = Report("report_graded", "sim_graded", "graph_graded", "Regional revenue?",
                    ReportStatus.GENERATING, created_at=datetime.now(timezone.utc).isoformat())
    agent = ReportAgent.__new__(ReportAgent)
    agent.output_language = "English"
    agent._outline_summary = ""
    agent._citation_index = {}
    agent.sources = []
    body = ["# Regional revenue", ""]
    for i in range(10):
        claim = f"Region {chr(65+i)} revenue was {101+i} million in 2026."
        if i < 7:
            source = {"title": f"Region {chr(65+i)} annual release", "url": f"https://example.gov/region/{i}",
                      "date": "2026-10-01", "content": claim}
            agent.sources.append(source)
            agent._citation_index[f"S{i+1}"] = source
            claim = claim[:-1] + f" [S{i+1}]."
        body += [claim, ""]
    agent.research_report = "\n".join(body)
    agent._forecast_spine = forecast()
    agent.set_backtest_policy(None)
    report.markdown_content = agent.research_report
    ReportManager.save_report(report)
    folder = tmp_path / "reports" / report.report_id
    (folder / "forecast.json").write_text(json.dumps(forecast()))
    agent._finalize_citations(report.report_id, report)
    return agent, report, folder


def test_low_coverage_and_spread_publish_with_disclosures_and_journal(monkeypatch, tmp_path):
    agent, report, folder = _prepared(monkeypatch, tmp_path)
    repaired, repair = agent._repair_final_quantitative_grounding(report.markdown_content)
    assert repaired == report.markdown_content
    assert repair["sentences_removed"] == 0 and repair["unverifiable_claims_preserved"] == 3
    assert repair["passed"] is True and repair["coverage_met"] is False
    audit = agent._enforce_final_publish_audit(report.report_id, report)
    assert audit["citation_grounding"]["resolved_coverage"] == 0.7
    assert audit["hard_passed"] and audit["quality_notes"]["passed"]
    assert audit["publish_gate"]["grade"] == "C"
    assert len(audit["publish_gate"]["disclosures"]) == 2
    assert report.markdown_content.index("## Quality notes") < report.markdown_content.index("## References")
    assert "Region J revenue was 110 million" in report.markdown_content
    report.status = ReportStatus.COMPLETED
    report.completed_at = datetime.now(timezone.utc).isoformat()
    ReportManager.save_report(report)
    status = ReportManager.publication_status(report.report_id)
    assert status["publishable"], status
    assert status["grade"] == "C" and len(status["disclosures"]) == 2
    from app.services.forecast_ledger import read_published_forecast
    issued = read_published_forecast(report.report_id)
    assert issued["forecast"]["publication"]["grade"] == "C"
    final = json.loads((folder / "forecast.json").read_text())
    assert final["scenarios"] == forecast()["scenarios"]
    # Removing the signed disclosure is an integrity violation.
    report.markdown_content = report.markdown_content.replace("Quality grade: C.", "Quality grade: A.")
    (folder / "full_report.md").write_text(report.markdown_content)
    audit = agent._audit_final_published_markdown(report.report_id, report)
    assert not audit["quality_notes"]["passed"] and not audit["hard_passed"]


def test_low_coverage_rollback_still_fails(monkeypatch, tmp_path):
    agent, report, folder = _prepared(monkeypatch, tmp_path)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE_MODE", "fail", raising=False)
    with pytest.raises(RuntimeError, match="质量门未通过"):
        agent._enforce_final_publish_audit(report.report_id, report)
    assert "## Quality notes" not in report.markdown_content


def test_nonverbatim_citation_remains_hard_in_grade_mode(monkeypatch, tmp_path):
    agent, report, folder = _prepared(monkeypatch, tmp_path)
    report.markdown_content = report.markdown_content.replace(
        "Region A revenue was 101 million in 2026 [S1].", '"Revenue was secretly 999 million in 2026" [S1].')
    (folder / "full_report.md").write_text(report.markdown_content)
    with pytest.raises(RuntimeError, match="完整性门"):
        agent._enforce_final_publish_audit(report.report_id, report)


@pytest.mark.parametrize("contradiction", ["cited_number", "forecast_probability"])
def test_grade_quantitative_retention_cannot_bypass_final_integrity(monkeypatch, tmp_path, contradiction):
    agent, report, folder = _prepared(monkeypatch, tmp_path)
    if contradiction == "cited_number":
        bad_claim = "Region A revenue was 999 million in 2026 [S1]."
        report.markdown_content = report.markdown_content.replace(
            "Region A revenue was 101 million in 2026 [S1].", bad_claim)
    else:
        bad_claim = "Expansion scenario probability is 85%."
        report.markdown_content = report.markdown_content.replace(
            "## References", "## Outlook\n\n" + bad_claim + "\n\n## References", 1)
    repaired, repair = agent._repair_final_quantitative_grounding(report.markdown_content)
    # Repair success is an epistemic result; final publication still audits the
    # cited source bytes and the probabilities pinned in forecast.json.
    assert bad_claim in repaired and repair["passed"] is True
    assert repair["sentences_removed"] == 0
    report.markdown_content = repaired
    (folder / "full_report.md").write_text(repaired)
    with pytest.raises(RuntimeError, match="完整性门"):
        agent._enforce_final_publish_audit(report.report_id, report)
    audit = json.loads((folder / "final_audit.json").read_text())
    if contradiction == "cited_number":
        assert audit["semantic_citations"]["unsupported"] >= 1
    else:
        assert audit["numeric_consistency"]["mismatch_count"] == 1
    assert audit["hard_passed"] is False and audit["publish_gate"]["hard_issues"]
    assert audit["publish_gate"]["passed"] is False
