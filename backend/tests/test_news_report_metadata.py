"""Real report metadata ownership; authored headings confer no exemption."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from flask import Flask

from app.services.report_agent import ReportAgent, ReportManager, ReportOutline, ReportSection, ReportStatus
from tests.conftest import FakeLLMClient
from tests.test_news_context_reports import (  # fixtures retain the real report constructor
    _context, _report, report_agent_factory as _report_agent_factory,
    report_root as _report_root,
)

# Explicit fixture exports let pytest discover their original implementation.
report_agent_factory = _report_agent_factory
report_root = _report_root


@pytest.mark.parametrize("language", ["Chinese", "English"])
def test_mixed_official_and_context_metadata_preserves_foreign_sources_but_rejects_authored_foreign_text(
    report_agent_factory, report_root, monkeypatch, language,
):
    from app.api import report as api
    from app.services import official_data, report_lint
    from scripts import export_demo_site_data as exporter

    monkeypatch.setenv("REPORT_OUTPUT_LANGUAGE", language)
    item = _context()["items"][0]
    item.update(provider="kalshi", id="kalshi:fixture", kind="market_quote",
                title="监管部门正式公布新增产能许可" if language == "English" else "Fixture capacity contract",
                yes_bid=0.0, yes_ask=0.44, last_price=0.41, price_unit="USD_per_contract",
                quote_basis="provider_reported_dollars_per_contract", outcome="Yes", quote_at=None,
                rules_primary="Resolve from the official annual capacity release published at year end.",
                rules_secondary="Use the original public release and preserve the stated outcome.")
    context = _context(items=[item], providers={"kalshi": {"state": "ok", "attempted": True}})
    carrier = {"schema_version": 1, "series": [{
        "series": "fred:UNRATE", "provider": "fred", "title": "Unemployment Rate",
        "units": "Percent", "frequency": "M", "geography": "USA", "transform": "",
        "source_url": "https://fred.stlouisfed.org/series/UNRATE", "retrieved_at": "2026-10-18T00:00:00Z",
        "observations": [{"date": "2026-09-01", "value": 4.0, "status": "observed"}],
    }]}
    def forbidden(*args, **kwargs):
        pytest.fail("A report reader attempted upstream acquisition")
    monkeypatch.setattr(official_data, "get_data_sources", forbidden)
    agent = ReportAgent("graph_fixture", "sim_fixture", "Assess capacity",
                        llm_client=FakeLLMClient(), zep_tools=SimpleNamespace(),
                        official_data=carrier, news_market_context=context)
    chinese = language == "Chinese"
    title = "产能展望" if chinese else "Capacity outlook"
    narrative = "产能取决于实际投资和交付进度。未来结果仍存在不确定性。" if chinese else (
        "Capacity depends on executed investment and delivery schedules. The outcome remains uncertain.")
    monkeypatch.setattr(agent, "plan_outline", lambda **kw: ReportOutline(
        title=title, summary=narrative, sections=[ReportSection(title=title, description=narrative)]))
    monkeypatch.setattr(agent, "_generate_section_with_retry", lambda **kw: narrative)
    report = agent.generate_report(report_id="report_mixed_metadata")
    assert report.status == ReportStatus.COMPLETED, report.error
    folder = Path(ReportManager._get_report_folder(report.report_id))
    audit = json.loads((folder / "final_audit.json").read_text())
    assert audit["lint"]["language_contamination"]["lines"] == 0
    assert audit["news_market_context"]["valid"] and audit["news_market_context"]["markdown_present"]
    assert ReportManager.publication_status(report.report_id)["publishable"]
    assert item["rules_primary"] in report.markdown_content and item["title"] in report.markdown_content
    assert "yes_bid=0.0" in report.markdown_content and "quote_at=unknown" in report.markdown_content
    # The detector still recognizes the original-language metadata without the
    # exact carrier-aware policy; this is the reported mixed-carrier trigger.
    assert report_lint.detect_language_contamination(agent._news_context_block, language)["lines"] > 0
    app = Flask(__name__)
    app.register_blueprint(api.report_bp, url_prefix="/api/report")
    with app.test_client() as client:
        response = client.get(f"/api/report/{report.report_id}")
        assert response.status_code == 200 and response.get_json()["data"]["news_market_context"] == context
        downloaded = client.get(f"/api/report/{report.report_id}/download")
        assert downloaded.status_code == 200 and downloaded.data == report.markdown_content.encode()
    monkeypatch.setattr(exporter, "UPLOADS", str(report_root.parent))
    output = report_root.parent / "mixed-export"
    output.mkdir()
    exporter.export_report("mixed", report.report_id, str(output))
    assert (output / "report.md").read_text() == report.markdown_content
    foreign = ("This authored foreign language paragraph must still be rejected by the final language audit."
               if chinese else "这段未经验证的外语正文必须仍然被最终语言审计拒绝。")
    report.markdown_content = report.markdown_content.replace("\n\n", "\n\n" + foreign + "\n\n", 1)
    (folder / "full_report.md").write_text(report.markdown_content)
    with pytest.raises(RuntimeError):
        agent._enforce_final_publish_audit(report.report_id, report)
    rejected = json.loads((folder / "final_audit.json").read_text())
    assert rejected["lint"]["language_contamination"]["lines"] > 0


def test_authored_matching_heading_does_not_own_the_appended_capture(report_agent_factory):
    capture = _context()
    agent = report_agent_factory(capture)
    report = _report()
    authored = "\n\n### News and market context\n\nAn authored discussion of conflicting coverage.\n"
    report.markdown_content += authored
    ReportManager.save_news_market_context(report.report_id, capture)
    agent._append_news_market_context(report.report_id, report)
    # Citation/editorial cleanup damaged only the machine-owned timestamp row.
    report.markdown_content = report.markdown_content.replace("2026-10-17T00:00:00Z", "—")
    agent._restore_news_market_context(report.report_id, report)
    assert authored.strip() in report.markdown_content
    assert agent._news_context_block in report.markdown_content
    assert report.markdown_content.count("drf-news-market-context:") == 2
    assert agent.news_market_context == capture
    assert ReportManager.load_report_news_market_context(report.report_id) == capture


def test_restore_rejects_missing_owned_boundary_and_changed_valid_capture(report_agent_factory):
    capture = _context()
    agent = report_agent_factory(capture)
    report = _report()
    ReportManager.save_news_market_context(report.report_id, capture)
    agent._append_news_market_context(report.report_id, report)
    original = report.markdown_content
    report.markdown_content = original.replace("drf-news-market-context:", "untrusted-metadata:")
    with pytest.raises(ValueError, match="metadata"):
        agent._restore_news_market_context(report.report_id, report)
    report.markdown_content = original
    other = _context(generation_id="different-valid-generation")
    path = ReportManager._get_report_folder(report.report_id) + "/news_market_context.json"
    with open(path, "w") as handle:
        json.dump(other, handle)
    with pytest.raises(ValueError, match="changed"):
        agent._restore_news_market_context(report.report_id, report)
