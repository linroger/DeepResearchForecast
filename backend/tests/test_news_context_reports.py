"""Offline consumer scenarios for the sealed news/market carrier.

All paths are fresh fixtures. Never fetch providers, inspect saved runs or alter
identity controls. Run only through the unchanged main_offline_pytest guard.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app.services.report_agent import Report, ReportAgent, ReportManager, ReportStatus
from tests.conftest import FakeLLMClient


def _context(**changes):
    context = {
        "schema_version": 1, "generation_id": "fixture-generation",
        "question_sha256": hashlib.sha256(b"Fixture outlook").hexdigest(),
        "language": "English", "as_of": "2026-10-18", "created_at": "2026-10-18T00:00:00Z",
        "sealed": True,
        "providers": {"newsapi": {"state": "ok", "attempted": True}},
        "queries": [],
        "items": [{"id": "newsapi:fixture", "provider": "newsapi", "kind": "news_snippet",
                   "title": "Fixture capacity outlook", "url": "https://example.org/fixture",
                   "published_at": "2026-10-17T00:00:00Z", "retrieved_at": "2026-10-18T00:00:00Z",
                   "language": "en", "query": "capacity", "snippet": "A synthetic article snippet.",
                   "eligibility": {"context_only": True, "anchor": False, "resolution": False}}],
    }
    context.update(changes)
    context.pop("sha256", None)
    context["sha256"] = hashlib.sha256(json.dumps(context, ensure_ascii=False, sort_keys=True,
                                                separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return context


def _report():
    return Report(report_id="report_fixture", simulation_id="sim_fixture", graph_id="graph_fixture",
                  simulation_requirement="Fixture outlook", status=ReportStatus.COMPLETED,
                  markdown_content="# Fixture\n\nStored context.")


@pytest.fixture
def report_root(tmp_path, monkeypatch):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    return tmp_path / "reports"


def test_existing_report_endpoint_exposes_exact_local_envelope(report_root, monkeypatch):
    from app.api import report as api
    report = _report()
    ReportManager.save_report(report)
    folder = Path(ReportManager._get_report_folder(report.report_id))
    context = _context()
    (folder / "news_market_context.json").write_text(json.dumps(context))
    monkeypatch.setattr(ReportManager, "publication_status", lambda *a, **kw: {"publishable": True})
    monkeypatch.setattr(ReportManager, "translation_status", lambda *a, **kw: {})
    with Flask(__name__).test_request_context():
        result = api.get_report(report.report_id).get_json()
    assert result["data"].get("news_market_context") == context
    assert result["data"]["markdown_content"] == report.markdown_content


def test_dossier_endpoint_exposes_exact_sealed_context(tmp_path, monkeypatch):
    from app.api import research as api
    context = _context()
    (tmp_path / "research_report.md").write_text("# Fixture research")
    (tmp_path / "news_market_context.json").write_text(json.dumps(context))
    monkeypatch.setattr(api.PipelineManager, "resolve_handoff_dir", lambda pid: str(tmp_path))
    monkeypatch.setattr(api, "research_dossier_is_sealed", lambda path: True)
    with Flask(__name__).test_request_context():
        result = api.get_dossier("pipe_fixture").get_json()
    assert result["data"].get("news_market_context") == context


@pytest.fixture
def report_agent_factory(monkeypatch, report_root):
    from app.config import Config
    monkeypatch.setattr(ReportAgent, "_define_tools", lambda self: {})
    monkeypatch.setattr(ReportAgent, "_locate_timeline", lambda self: None)
    monkeypatch.setattr(ReportAgent, "_locate_handoff_dir", lambda self: None)
    for name, value in {"REPORT_STRUCTURED_FORECAST": False, "REPORT_CITATION_FINALIZER": True,
                        "REPORT_EDITORIAL_LINT": True, "REPORT_FINAL_READ_ONLY_AUDIT": True,
                        "REPORT_BILINGUAL": False, "REPORT_SIGNAL_PACK": False,
                        "PREDICTION_MARKETS_ENABLED": False, "REPORT_VISUALIZATIONS": False,
                        "REPORT_SECTION_CONCURRENCY": 1, "REPORT_SECTION_CONTEXT_MODE": "full",
                        "REPORT_PUBLISH_GATE": False, "LLM_TELEMETRY": False}.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    def make(context=None, sources=None):
        return ReportAgent("graph_fixture", "sim_fixture", "Assess the capacity outlook",
                           llm_client=FakeLLMClient(), zep_tools=SimpleNamespace(),
                           sources=sources, news_market_context=context)
    return make


def test_constructor_detaches_and_rejects_tampered_unbounded_or_anchor_carriers(report_agent_factory):
    context = _context()
    expected = json.loads(json.dumps(context))
    agent = report_agent_factory(context)
    context["items"][0]["title"] = "Caller mutation"
    assert agent.news_market_context == expected
    exposed = agent.news_market_context
    exposed["items"].clear()
    assert agent.news_market_context == expected
    assert "Fixture capacity outlook" in agent._prepend_research_background("Draft a context section")
    for invalid in (_context(sealed=False), _context(items=[{"provider": "newsapi"}]),
                    _context(extra="x" * 2_000_001)):
        with pytest.raises(ValueError):
            report_agent_factory(invalid)
    expected["items"][0]["title"] = "Tampered"
    with pytest.raises(ValueError, match="digest"):
        report_agent_factory(expected)


def test_reordered_cited_only_ledger_keeps_direct_links_and_original_capture_hash(report_agent_factory):
    context = _context()
    context["items"][0]["source_ref"] = "S87"
    context = _context(**context)
    agent = report_agent_factory(context, sources=[
        {"title": "Different source", "url": "https://example.org/different"},
        {"title": "Fixture capacity outlook", "url": "https://example.org/fixture"},
    ])
    block = agent._news_context_block
    assert "https://example.org/fixture" in block
    assert "S87" not in block and "[S1]" not in block and "[S2]" not in block
    assert "original research ledger" in block
    agent._citation_index = {"S1": agent.sources[1]}
    assert agent._news_context_block == block
    assert agent.news_market_context["sha256"] == context["sha256"]
    assert agent.news_market_context["items"][0]["source_ref"] == "S87"


@pytest.mark.parametrize("market_context", [False, True])
def test_real_report_sequence_seals_context_and_api_markdown_export(
    report_agent_factory, report_root, monkeypatch, market_context,
):
    from app.api import report as api
    from app.services.report_agent import ReportOutline, ReportSection
    context = _context()
    sources = None
    if market_context:
        news_item = {**context["items"][0], "id": "newsapi:capacity-2026", "source_ref": "S87",
                     "title": "Capacity grows 80% by 2028", "url": "https://example.org/news-2026"}
        from deerflow_bridge.market_intelligence import normalize_kalshi_market
        from app.services import official_data, pipeline_orchestrator as po
        from app.services.news_market_context import _bridge_api, load_for_simulation
        from app.services.simulation_manager import SimulationManager
        from tests.test_market_intelligence import kalshi
        market_item = normalize_kalshi_market(kalshi(
            yes_bid_dollars="0.4000", yes_ask_dollars="0.4400", last_price_dollars="0.4100"),
            "capacity", retrieved_at="2026-10-18T00:00:00Z", language="en")
        sources = [{"url": market_item["url"], "title": market_item["title"]},
                   {"url": news_item["url"], "title": news_item["title"]}]
        research = report_root.parent / "captured-research"
        client = _bridge_api().ContextClient(research, question="Fixture outlook", language="en", as_of="2026-10-18")
        for provider, item in (("newsapi", news_item), ("kalshi", market_item)):
            client.record_result(provider, "capacity", {"provider": provider, "query": "capacity",
                "status": {"state": "ok", "attempted": True}, "items": [item],
                "retrieved_at": "2026-10-18T00:00:00Z"})
        context = client.seal(source_refs={market_item["url"]: "S87", news_item["url"]: "S1"})
        (research / "research_report.md").write_text("# Original research\n" + "Original research evidence. " * 40)
        (research / "actors.json").write_text('{"actors":[]}')
        (research / "sources.json").write_text(json.dumps(sources))
        promoted = report_root.parent / "promoted"
        po._promote_research_contract(str(research), str(promoted))
        simulations = report_root.parent / "simulations"
        (simulations / "sim_fixture").mkdir(parents=True)
        monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(simulations))
        official_data.bind_simulation_research("sim_fixture", promoted, pipeline_id="pipe_fixture")
        assert load_for_simulation("sim_fixture") == context
    agent = report_agent_factory(context, sources=sources)
    monkeypatch.setattr(agent, "plan_outline", lambda **kw: ReportOutline(
        title="Capacity outlook", summary="A bounded outlook from stored evidence.",
        sections=[ReportSection(title="Outlook", description="Assess the outlook")]))
    monkeypatch.setattr(agent, "_generate_section_with_retry", lambda **kw:
                        "Capacity depends on executed investment and delivery schedules. The outcome remains uncertain.")
    report = agent.generate_report(report_id="report_context_sequence")
    assert report.status == ReportStatus.COMPLETED, report.error
    assert "### News and market context" in report.markdown_content
    assert all(item["url"] in report.markdown_content for item in context["items"])
    assert all((item.get("published_at") or "unknown") in report.markdown_content for item in context["items"])
    assert all(item["retrieved_at"] in report.markdown_content for item in context["items"])
    assert all(item["id"] in report.markdown_content for item in context["items"])
    assert "S87" not in report.markdown_content
    assert agent._news_context_block.strip() in report.markdown_content
    if market_context:
        visible = report.markdown_content.replace("\\_", "_")
        for token in ("0.41", "0.4", "0.44", "USD_per_contract",
                      "provider_reported_dollars_per_contract", "last_price_dollars/1_USD_binary_payout",
                      "Yes", market_item["rules_primary"], market_item["rules_secondary"]):
            assert token in visible
        assert "quote_at=unknown" in visible
        assert "2026-10-18T11:00:00Z" not in visible  # metadata-updated is not a quote timestamp
    assert "not probability anchors or resolution evidence" in report.markdown_content
    assert ReportManager.load_report_news_market_context(report.report_id) == context
    folder = Path(ReportManager._get_report_folder(report.report_id))
    audit = json.loads((folder / "final_audit.json").read_text())
    assert audit["hard_passed"] is True, audit["hard_issues"]
    assert audit["news_market_context"]["sha256"] == context["sha256"]
    assert audit["news_market_context"]["markdown_present"] is True
    assert ReportManager.publication_status(report.report_id)["publishable"] is True
    with Flask(__name__).test_request_context():
        payload = api.get_report(report.report_id).get_json()["data"]
        response = api.download_report(report.report_id)
        response.direct_passthrough = False
        exported = response.get_data(as_text=True)
    assert payload["news_market_context"] == context
    assert payload["markdown_content"] == exported == report.markdown_content
    # An internally valid replacement is still another consumed generation.
    replacement = _context(generation_id="another-generation")
    (folder / "news_market_context.json").write_text(json.dumps(replacement))
    status = ReportManager.publication_status(report.report_id)
    assert status["publishable"] is False
    assert any("news context" in reason for reason in status["reasons"])
    with Flask(__name__).test_request_context():
        response, code = api.get_report(report.report_id)
    assert code == 500 and response.get_json()["success"] is False


@pytest.mark.parametrize("case", ["missing", "tamper", "unsealed", "symlink", "oversized"])
def test_report_local_loader_old_and_invalid_cases(report_root, case):
    from app.services.news_market_context import load_context
    folder = Path(ReportManager._ensure_report_folder("report_invalid"))
    path = folder / "news_market_context.json"
    if case == "missing":
        assert load_context(folder) == {}
        assert ReportManager.load_report_news_market_context("report_invalid") is None
        return
    context = _context()
    if case == "tamper":
        context["generation_id"] = "tampered"
    elif case == "unsealed":
        context = _context(sealed=False)
    if case == "oversized":
        path.write_text("x" * 2_000_001)
    elif case == "symlink":
        original = folder / "original.json"
        original.write_text(json.dumps(context))
        path.symlink_to(original)
    else:
        path.write_text(json.dumps(context))
    with pytest.raises(ValueError):
        ReportManager.load_report_news_market_context("report_invalid")


def test_report_capture_write_is_idempotent_and_cannot_rebind(report_root):
    context = _context()
    ReportManager.save_news_market_context("report_immutable", context)
    ReportManager.save_news_market_context("report_immutable", context)
    with pytest.raises(ValueError, match="another news context"):
        ReportManager.save_news_market_context("report_immutable", _context(generation_id="replacement"))
    assert ReportManager.load_report_news_market_context("report_immutable") == context


@pytest.mark.parametrize("entrypoint", ["generate", "chat"])
def test_manual_api_entrypoints_forward_context(report_agent_factory, monkeypatch, entrypoint):
    from app.api import report as api
    context = _context()
    captured = []
    monkeypatch.setattr(api, "SimulationManager", lambda: SimpleNamespace(
        get_simulation=lambda sid: SimpleNamespace(project_id="project_fixture", graph_id="graph_fixture")))
    monkeypatch.setattr(api.ProjectManager, "get_project", lambda pid: SimpleNamespace(
        graph_id="graph_fixture", simulation_requirement="Assess the capacity outlook"))
    monkeypatch.setattr(api, "load_research_dossier_for_simulation", lambda sid:
                        {"news_market_context": context})
    def capture(**kw):
        captured.append(kw)
        return SimpleNamespace(generate_report=lambda **kw: _report(), chat=lambda **kw: {"reply": "fixture"})
    monkeypatch.setattr(api, "ReportAgent", capture)
    tasks = SimpleNamespace(create_task=lambda **kw: "task_fixture", update_task=lambda *a, **kw: None,
                            complete_task=lambda *a, **kw: None, fail_task=lambda *a, **kw: None)
    monkeypatch.setattr(api, "TaskManager", lambda: tasks)
    class InlineThread:
        def __init__(self, target, **kw):
            self.target = target
        def start(self):
            self.target()
    monkeypatch.setattr(api.threading, "Thread", InlineThread)
    with Flask(__name__).test_request_context(json={"simulation_id": "sim_fixture", "message": "Discuss context"}):
        response = api.generate_report() if entrypoint == "generate" else api.chat_with_report_agent()
        if isinstance(response, tuple):
            response = response[0]
        assert response.get_json()["success"] is True
    assert len(captured) == 1 and captured[0]["news_market_context"] == context


def test_report_capture_publication_race_keeps_one_generation(report_root):
    from concurrent.futures import ThreadPoolExecutor
    contexts = [_context(generation_id=name) for name in ("generation-a", "generation-b")]
    def save(context):
        try:
            ReportManager.save_news_market_context("report_race", context)
            return context
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, contexts))
    winners = [context for context in results if context]
    assert len(winners) == 1
    assert ReportManager.load_report_news_market_context("report_race") == winners[0]
