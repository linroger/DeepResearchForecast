"""Focused regressions for the post-citation, read-only report publish audit."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.services.report_agent import ReportAgent, ReportManager  # noqa: E402


def _agent(source: dict | None = None) -> ReportAgent:
    agent = ReportAgent.__new__(ReportAgent)
    agent.output_language = "English"
    agent.research_report = "Revenue evidence from the official source."
    agent._outline_summary = ""
    agent.sources = [source] if source else []
    agent._citation_index = {"S1": source} if source else {}
    agent._forecast_spine = None
    return agent


def _forecast() -> dict:
    return {
        "headline": "Base case leads",
        "confidence": "high",
        "confidence_rationale": "Evidence is broad.",
        "scenarios": [
            {
                "name": "Base case",
                "probability": 0.6,
                "resolution_criteria": "The audited 2030 filing records the base-case outcome.",
            },
            {
                "name": "Other / status quo",
                "probability": 0.4,
                "resolution_criteria": "Any other measurable outcome in the audited 2030 filing.",
            },
        ],
        "binary_forecasts": [{
            "id": "F1",
            "statement": "Revenue reaches 65% by 2030.",
            "probability": 0.65,
            "resolution_criteria": "The audited 2030 filing reports revenue at 65%.",
        }],
        "quality": {},
    }


def _prepare(monkeypatch, tmp_path, report_id: str, md: str) -> str:
    reports = tmp_path / "reports"
    folder = reports / report_id
    folder.mkdir(parents=True)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports), raising=False)
    (folder / "full_report.md").write_text(md, encoding="utf-8")
    (folder / "meta.json").write_text(json.dumps({
        "report_id": report_id,
        "status": "completed",
        "failed_sections": [],
        "partial": False,
    }), encoding="utf-8")
    (folder / "forecast.json").write_text(
        json.dumps(_forecast()), encoding="utf-8"
    )
    return str(folder)


def test_final_audit_fingerprints_exact_post_citation_markdown_without_mutation(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True, raising=False)
    monkeypatch.setattr(
        Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.5, raising=False
    )
    source = {
        "title": "Official outlook",
        "url": "https://example.gov/outlook",
        "date": "2026-06-30",
        "tier": "S1",
        "content": "Revenue could reach 65% by 2030 according to the official source.",
    }
    report_id = "report_final_audit_clean"
    initial = "# Forecast\n\nRevenue could reach 65% by 2030 [S1].\n"
    folder = _prepare(monkeypatch, tmp_path, report_id, initial)
    report = SimpleNamespace(markdown_content=initial)
    agent = _agent(source)

    # Citation finalization is the last sanctioned report mutation.  The audit
    # that follows must fingerprint that exact References-bearing byte sequence.
    agent._finalize_citations(report_id, report)
    published = report.markdown_content
    disk_before = (tmp_path / "reports" / report_id / "full_report.md").read_bytes()
    assert "## References" in published

    audit = agent._audit_final_published_markdown(report_id, report)

    assert report.markdown_content == published
    assert (tmp_path / "reports" / report_id / "full_report.md").read_bytes() == disk_before
    assert audit["read_only"] is True
    assert audit["disk_matches_memory"] is True
    assert audit["markdown_sha256"] == hashlib.sha256(
        published.encode("utf-8")
    ).hexdigest()
    # References metadata is excluded from the claim denominator; complete
    # marker integrity still includes body + appendix occurrences.
    assert audit["citation_grounding"]["quantitative_claims"] == 1
    assert audit["citation_grounding"]["resolved_coverage"] == 1.0
    assert audit["citation_markers"]["counts"]["S1"] == 2
    assert audit["citation_markers"]["dangling"] == []
    assert audit["lint"]["changed"] is False
    assert audit["hard_passed"] is True
    assert audit["publish_gate"]["passed"] is True
    assert audit["publish_gate"]["hard_passed"] is True
    forecast_bytes = (tmp_path / "reports" / report_id / "forecast.json").read_bytes()
    assert audit["forecast_sha256"] == hashlib.sha256(forecast_bytes).hexdigest()
    agent._require_final_publish_audit(audit)

    forecast = json.loads((tmp_path / "reports" / report_id / "forecast.json").read_text())
    final = forecast["quality"]["final_audit"]
    assert final["markdown_sha256"] == audit["markdown_sha256"]
    assert forecast["citation_audit"] == audit["citation_grounding"]
    assert forecast["confidence"] == "high"
    assert os.path.exists(os.path.join(folder, "final_audit.json"))
    assert ReportManager.publication_status(report_id)["publishable"] is True

    # Structured data is part of the published bundle. A post-audit ensemble or
    # manual edit must invalidate the report even when Markdown is unchanged.
    forecast_path = tmp_path / "reports" / report_id / "forecast.json"
    mutated = json.loads(forecast_path.read_text(encoding="utf-8"))
    mutated["confidence"] = "low"
    forecast_path.write_text(json.dumps(mutated), encoding="utf-8")
    status = ReportManager.publication_status(report_id)
    assert status["publishable"] is False
    assert any("structured forecast" in reason for reason in status["reasons"])


def test_final_audit_does_not_launder_adjacent_sentences_or_table_cells(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True, raising=False)
    monkeypatch.setattr(
        Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.75, raising=False
    )
    source = {
        "title": "Official outlook",
        "url": "https://example.gov/outlook",
        "supports": ["Official adoption reached 55.6% in 2025."],
    }
    report_id = "report_final_audit_claim_units"
    initial = (
        "# Evidence\n\n"
        "Official adoption reached 55.6% in 2025. [S1] "
        "Unsupported lunar adoption reached 99% in 2027.\n\n"
        "| Metric | 2025 actual | 2026 forecast |\n"
        "|---|---:|---:|\n"
        "| Official adoption | 55.6%. [S1] | 99% |\n"
    )
    _prepare(monkeypatch, tmp_path, report_id, initial)
    report = SimpleNamespace(markdown_content=initial)
    agent = _agent(source)

    agent._finalize_citations(report_id, report)
    audit = agent._audit_final_published_markdown(report_id, report)

    grounding = audit["citation_grounding"]
    assert grounding["quantitative_claims"] == 4
    assert grounding["resolved_cited"] == 2
    assert grounding["resolved_coverage"] == 0.5
    assert audit["publish_gate"]["passed"] is False
    assert any("引用覆盖率" in issue for issue in audit["publish_gate"]["issues"])


def test_final_audit_fails_gate_but_never_repairs_published_markdown(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True, raising=False)
    monkeypatch.setattr(
        Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.0, raising=False
    )
    report_id = "report_final_audit_dirty"
    dirty = (
        "# Simulation Dynamics\n\n"
        "Round 3 produced 48 actions and the most active agents amplified posts.\n"
    )
    _prepare(monkeypatch, tmp_path, report_id, dirty)
    report = SimpleNamespace(markdown_content=dirty)
    agent = _agent()
    disk_before = (tmp_path / "reports" / report_id / "full_report.md").read_bytes()

    audit = agent._audit_final_published_markdown(report_id, report)

    assert audit["lint"]["changed"] is True
    assert audit["publish_gate"]["passed"] is False
    assert audit["publish_gate"]["hard_passed"] is False
    assert any("lint" in issue for issue in audit["publish_gate"]["issues"])
    assert report.markdown_content == dirty
    assert (tmp_path / "reports" / report_id / "full_report.md").read_bytes() == disk_before
    forecast = json.loads(
        (tmp_path / "reports" / report_id / "forecast.json").read_text()
    )
    # Artifact-integrity failures block publication; they do not masquerade as
    # lower epistemic confidence in the forecast itself.
    assert forecast["confidence"] == "high"
    try:
        agent._require_final_publish_audit(audit)
    except RuntimeError as exc:
        assert "发布完整性门" in str(exc)
    else:  # pragma: no cover - explicit regression failure branch
        raise AssertionError("dirty final audit must block completed publication")


def test_final_gate_rejects_language_contamination_even_when_lint_is_read_only(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True, raising=False)
    monkeypatch.setattr(
        Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.0, raising=False
    )
    report_id = "report_final_audit_language"
    mixed = "# Forecast\n\nThe outlook is mixed. 市场情绪仍然疲弱。\n"
    _prepare(monkeypatch, tmp_path, report_id, mixed)
    report = SimpleNamespace(markdown_content=mixed)
    audit = _agent()._audit_final_published_markdown(report_id, report)

    assert audit["lint"]["language_contamination"]["lines"] == 1
    assert audit["publish_gate"]["passed"] is False
    assert audit["publish_gate"]["hard_passed"] is False
    assert any("目标语言污染" in issue for issue in audit["publish_gate"]["issues"])
    assert report.markdown_content == mixed


def test_missing_final_audit_result_blocks_completed_publication():
    try:
        ReportAgent._require_final_publish_audit({})
    except RuntimeError as exc:
        assert "未产生结果" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("missing audit must not publish")


def test_enabled_professional_quality_gate_blocks_epistemic_failure():
    audit = {
        "hard_issues": [],
        "publish_gate": {
            "enabled": True,
            "passed": False,
            "hard_issues": [],
            "issues": ["binary criteria are not objective"],
        },
    }
    with pytest.raises(RuntimeError, match="质量门未通过"):
        ReportAgent._require_final_publish_audit(audit)


def test_final_audit_execution_failure_is_a_hard_stop(monkeypatch):
    agent = _agent()

    def _boom(report_id, report):
        raise OSError("simulated audit persistence failure")

    monkeypatch.setattr(agent, "_audit_final_published_markdown", _boom)
    try:
        agent._enforce_final_publish_audit(
            "rid_audit_failure", SimpleNamespace(markdown_content="# Report")
        )
    except RuntimeError as exc:
        assert "不标记为 completed" in str(exc)
        assert "simulated audit persistence failure" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("audit execution failure must block publication")


def test_citation_finalizer_failure_with_body_markers_is_a_hard_stop(monkeypatch):
    agent = _agent({
        "title": "Official source",
        "url": "https://example.gov/source",
    })
    report = SimpleNamespace(markdown_content="# Report\n\nClaim [S1].\n")

    def _boom(report_id, candidate):
        raise OSError("simulated citations.json write failure")

    monkeypatch.setattr(agent, "_finalize_citations", _boom)
    try:
        agent._finalize_citations_for_publish("rid_citation_failure", report)
    except RuntimeError as exc:
        assert "正文含引用记号" in str(exc)
        assert "simulated citations.json write failure" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("dead body citations must block publication")


def test_publish_stabilizer_removes_quote_exposed_by_semantic_citation_repair(
    monkeypatch, tmp_path
):
    source = {
        "title": "Official revenue outlook",
        "url": "https://example.gov/revenue-outlook",
        "content": "Audited revenue evidence for the official outlook.",
    }
    report_id = "report_publish_convergence"
    initial = (
        "# Forecast\n\n"
        "> The lunar authority secretly seized every terrestrial data center. [S1]\n\n"
        "The outcome remains uncertain.\n"
    )
    folder = _prepare(monkeypatch, tmp_path, report_id, initial)
    report = SimpleNamespace(markdown_content=initial)
    agent = _agent(source)

    result = agent._stabilize_publish_markdown(report_id, report)

    assert result["stable"] is True
    assert result["passes"] >= 1
    assert result["quotes_removed"] == 1
    assert result["semantic_unsupported"] == 0
    assert "lunar authority" not in report.markdown_content
    assert "[S1]" not in report.markdown_content
    assert result["lint"]["changed"] is False
    assert (tmp_path / "reports" / report_id / "full_report.md").read_text(
        encoding="utf-8"
    ) == report.markdown_content
    citations = json.loads(
        (tmp_path / "reports" / report_id / "citations.json").read_text(
            encoding="utf-8"
        )
    )
    assert citations["markers"] == []
    assert os.path.isdir(folder)


def test_publish_stabilizer_repairs_exact_final_quantitative_surface(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.75, raising=False
    )
    source = {
        "title": "Official battery adoption report",
        "url": "https://example.gov/battery-adoption",
        "date": "2026-01-02",
        "supports": ["Official battery adoption reached 55.6% in 2025."],
    }
    report_id = "report_publish_quantitative_convergence"
    initial = (
        "# Forecast\n\n"
        "## Part 1 — Binary Forecasts\n\n"
        "| F1 | Authored outcome | 72% | Resolve above 40% by 2030 |\n\n"
        "## Part 2 — Framework & Synthesis\n\n"
        "Official battery adoption reached 55.6% in 2025.\n\n"
        "Unsupported lunar adoption reached 99% in 2027. "
        "The competitive mechanism remains material.\n\n"
        "## How to Verify This Forecast (Resolution Criteria & Indicators)\n\n"
        "Resolve the authored scenario at a 90% threshold by 2035.\n"
    )
    _prepare(monkeypatch, tmp_path, report_id, initial)
    report = SimpleNamespace(markdown_content=initial)
    agent = _agent(source)

    result = agent._stabilize_publish_markdown(report_id, report)

    assert result["stable"] is True
    assert result["quantitative_rewrites"] == 1
    assert result["quantitative_grounding"]["passed"] is True
    assert result["quantitative_grounding"]["after"]["resolved_coverage"] == 1.0
    assert "Official battery adoption reached 55.6% in 2025. [S1]" in report.markdown_content
    assert "Unsupported lunar adoption" not in report.markdown_content
    assert "The competitive mechanism remains material." in report.markdown_content
    assert "| F1 | Authored outcome | 72% | Resolve above 40% by 2030 |" in report.markdown_content
    assert "90% threshold by 2035" in report.markdown_content
    assert "## References" in report.markdown_content


def test_final_audit_requires_visible_reference_and_citation_artifacts(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True, raising=False)
    monkeypatch.setattr(
        Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.0, raising=False
    )
    source = {
        "title": "Official source",
        "url": "https://example.gov/source",
        "date": "2026-01-01",
        "content": "Evidence.",
    }
    report_id = "report_missing_citation_artifacts"
    md = "# Forecast\n\nThe measured outcome reached 65% [S1].\n"
    _prepare(monkeypatch, tmp_path, report_id, md)
    report = SimpleNamespace(markdown_content=md)

    audit = _agent(source)._audit_final_published_markdown(report_id, report)

    artifacts = audit["citation_artifacts"]
    assert artifacts["required"] is True
    assert artifacts["references_present"] is False
    assert artifacts["citations_json_present"] is False
    assert artifacts["passed"] is False
    assert audit["hard_passed"] is False
    assert any("References" in issue for issue in audit["hard_issues"])
    assert any("citations.json" in issue for issue in audit["hard_issues"])


def test_citation_artifact_audit_hard_fails_invalid_url_flag(tmp_path):
    source = {
        "title": "Official source",
        "url": "https://example.gov/source",
    }
    (tmp_path / "citations.json").write_text(json.dumps({
        "markers": [{
            "tag": "S1",
            "url": source["url"],
            "url_valid": False,
        }],
    }), encoding="utf-8")
    reference_text = (
        "## References\n\n"
        "1. [S1] Official source — "
        "[https://example.gov/source](https://example.gov/source)\n"
    )

    result = ReportAgent._audit_final_citation_artifacts(
        str(tmp_path), reference_text,
        {"order": ["S1"]}, {"S1": source}, enabled=True,
    )

    assert result["invalid_artifact_urls"] == ["S1"]
    assert result["passed"] is False
    assert any("无效或截断" in issue for issue in result["issues"])


def test_final_integrity_hard_fails_truncated_cells_and_scenario_drift():
    issues = ReportAgent._final_audit_integrity_issues({
        "failed_sections": ["Scenario Two"],
        "disk_matches_memory": True,
        "citation_markers": {"dangling": []},
        "citation_artifacts": {"issues": []},
        "semantic_citations": {"unsupported": 2},
        "quote_provenance": {"cited_unverbatim": 1},
        "scenario_contract": {"issue_count": 2},
        "lint": {
            "changed": False,
            "leakage_flags": 0,
            "language_contamination": {"lines": 0},
            "table_cell_truncations": ["criterion cut at NVI"],
            "scenario_prob_mismatches": ["Base case prose 70% vs spine 55%"],
        },
    })

    assert any("截断表格" in issue for issue in issues)
    assert any("概率/骨架不一致" in issue for issue in issues)
    assert any("来源与论断不匹配" in issue for issue in issues)
    assert any("无法逐字接地" in issue for issue in issues)
    assert any("生成失败章节" in issue for issue in issues)
    assert any("结构化情景契约" in issue for issue in issues)

    missing_contract = ReportAgent._final_audit_integrity_issues({
        "structured_forecast": {"required": True, "valid": True},
        "disk_matches_memory": True,
        "citation_markers": {"dangling": []},
        "citation_artifacts": {"issues": []},
        "lint": {"changed": False},
    })
    assert any("情景契约缺失" in issue for issue in missing_contract)


def test_final_audit_blocks_invalid_scenario_contract(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True, raising=False)
    monkeypatch.setattr(
        Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.0, raising=False
    )
    report_id = "report_invalid_scenario_contract"
    md = "# Forecast\n\nThe outcome remains uncertain.\n"
    folder = _prepare(monkeypatch, tmp_path, report_id, md)
    forecast = _forecast()
    forecast["scenarios"] = [
        {
            "name": "Base case",
            "probability": 0.7,
            "resolution_criteria": "Revenue: $1.0T-$1.4T by 2030",
        },
        {
            "name": "Upside",
            "probability": 0.4,
            "resolution_criteria": "Revenue: $1.2T-$1.6T by 2030",
        },
    ]
    (tmp_path / "reports" / report_id / "forecast.json").write_text(
        json.dumps(forecast), encoding="utf-8"
    )

    audit = _agent()._audit_final_published_markdown(
        report_id, SimpleNamespace(markdown_content=md)
    )

    assert audit["scenario_contract"]["valid"] is False
    assert audit["scenario_contract"]["issue_count"] >= 2
    assert audit["hard_passed"] is False
    assert any("结构化情景契约" in issue for issue in audit["hard_issues"])
    persisted = json.loads(
        (tmp_path / "reports" / report_id / "final_audit.json").read_text(
            encoding="utf-8"
        )
    )
    assert persisted["scenario_contract"] == audit["scenario_contract"]
    assert os.path.isdir(folder)


def test_stat_plausibility_distinguishes_cited_extremes_from_unsupported_ones():
    agent = _agent()
    result = agent._audit_stat_plausibility(
        "Revenue increased 303% year over year [S1].\n"
        "Another segment reported growth 420% without provenance.\n"
    )

    assert result["count"] == 1
    assert "420%" in result["implausible_stats"][0]
    assert "303%" in result["cited_extreme_stats"][0]


def test_final_gate_scans_chinese_target_headings_tables_quotes_and_links(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True, raising=False)
    monkeypatch.setattr(
        Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.0, raising=False
    )
    report_id = "report_final_audit_structured_language"
    md = (
        "## This English heading contains enough prose words to trigger detection\n"
        "| This English table cell contains enough prose words to trigger detection |\n"
        "> This English blockquote contains enough prose words to trigger detection.\n"
        "Read [this English linked passage contains enough prose words for detection]"
        "(https://example.com/English-url-remains-protected) now.\n"
    )
    _prepare(monkeypatch, tmp_path, report_id, md)
    report = SimpleNamespace(markdown_content=md)
    agent = _agent()
    agent.output_language = "Chinese"

    audit = agent._audit_final_published_markdown(report_id, report)

    assert audit["lint"]["language_contamination"]["lines"] == 4
    assert audit["hard_passed"] is False
    assert audit["publish_gate"]["hard_passed"] is False


# ── ADR 0003 slice S3, T13: the fenced scenario-simulation bridge ───────────

def _bridge_audit_base() -> dict:
    return {
        "disk_matches_memory": True,
        "citation_markers": {"dangling": []},
        "citation_artifacts": {"issues": []},
        "lint": {"changed": False},
    }


def test_final_integrity_flags_bridge_count_and_bytes_by_policy():
    def issues(bridge: dict) -> list:
        return ReportAgent._final_audit_integrity_issues({**_bridge_audit_base(), "simulation_bridge": bridge})

    diagnostic = {"policy": "diagnostic_only", "expected_count": 1, "sha256": "abc"}
    assert issues({**diagnostic, "count": 1, "bytes_match": True}) == []
    for count in (0, 2):
        found = issues({**diagnostic, "count": count, "bytes_match": False})
        assert len(found) == 1 and "simulation bridge block count" in found[0] and "requires 1" in found[0]
    found = issues({**diagnostic, "count": 1, "bytes_match": False})
    assert found == ["simulation bridge bytes differ from the deterministic renderer"]
    no_update = {"policy": "no_update", "expected_count": 0, "sha256": None}
    assert issues({**no_update, "count": 0, "bytes_match": True}) == []
    found = issues({**no_update, "count": 1, "bytes_match": False})
    assert len(found) == 1 and "requires 0" in found[0] and "no_update" in found[0]
    # an audit without the field (older audits) adds nothing
    assert ReportAgent._final_audit_integrity_issues(_bridge_audit_base()) == []


def test_sim_bridge_audit_block_counts_blocks_and_compares_bytes():
    from app.services import sim_provenance as sp
    from app.services.report_agent import _sim_bridge_blocks, render_sim_bridge
    with open(os.path.join(os.path.dirname(__file__), "fixtures", "sim",
                           "simulation_record.paths.json"), encoding="utf-8") as handle:
        record = json.load(handle)
    block = render_sim_bridge(record, chinese=False, spine=_forecast(), chart_rel_paths=None,
                              whatif_table_md="", record_sha256="feed")
    body = "# R\n\n## A\n\nProse.\n\n"
    one = body + block + "\n"
    two = one + "\n" + block + "\n"
    mutated = body + block.replace("| Escalation |", "| Escalation (edited) |") + "\n"
    none = body
    assert _sim_bridge_blocks(two) == [block, block]
    expect_one = ReportAgent._sim_bridge_audit_block(one, block)
    assert expect_one == {"expected_count": 1, "count": 1, "bytes_match": True,
                          "sha256": hashlib.sha256(block.encode("utf-8")).hexdigest()}
    assert ReportAgent._sim_bridge_audit_block(two, block)["count"] == 2
    assert ReportAgent._sim_bridge_audit_block(two, block)["bytes_match"] is False
    assert ReportAgent._sim_bridge_audit_block(none, block) == {
        "expected_count": 1, "count": 0, "bytes_match": False,
        "sha256": hashlib.sha256(block.encode("utf-8")).hexdigest()}
    assert ReportAgent._sim_bridge_audit_block(mutated, block)["bytes_match"] is False
    # no_update / other engines expect none: a stray block is counted, nothing is expected
    assert ReportAgent._sim_bridge_audit_block(none, "") == {
        "expected_count": 0, "count": 0, "bytes_match": True, "sha256": None}
    assert ReportAgent._sim_bridge_audit_block(one, "")["bytes_match"] is False
    # the marker pair is the fence: nothing inside it reaches the final lint
    assert sp.BRIDGE_START in block and sp.BRIDGE_END in block
    for audit_md in (one, two):
        issues = ReportAgent._final_audit_integrity_issues({
            **_bridge_audit_base(),
            "simulation_bridge": {**ReportAgent._sim_bridge_audit_block(audit_md, block),
                                  "policy": "diagnostic_only"}})
        assert (issues == []) is (audit_md == one)
