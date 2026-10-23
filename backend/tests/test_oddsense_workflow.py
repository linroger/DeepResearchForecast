"""Controlled Oddsense production-to-publication acceptance, never live-provider proof.

Only external transport/model/search/fetch responses are scripted. Research phase
ordering, tools, budgets, ledger, QA, sealing, promotion, report admission,
citations, Flask routing and Markdown export remain production implementations.
Run with the existing main_offline_pytest.py guard from an exact source mirror.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

REPO = Path(__file__).resolve().parents[2]
QUESTION = "Will semiconductor capacity grow by the end of 2027?"
NEWS_URLS = [f"https://publisher.example/news/capacity-{index}" for index in (1, 2)]
TICKER = "CAPACITY-27-GROW"
MARKET_URL = f"https://external-api.kalshi.com/trade-api/v2/markets/{TICKER}"
ELIGIBILITY = {"context_only": True, "anchor": False, "resolution": False}
SOURCES = (
    "deerflow_bridge/news_signals.py", "deerflow_bridge/news_tools.py",
    "deerflow_bridge/market_intelligence.py", "deerflow_bridge/research_gateway.py",
    "deerflow_bridge/linear_research.py", "deerflow_bridge/deerflow_research.py",
    "deerflow_bridge/research_budget.py", "backend/app/services/pipeline_orchestrator.py",
    "backend/app/services/news_market_context.py", "backend/app/services/official_data.py",
    "backend/app/services/report_agent.py", "backend/app/services/forecast_extractor.py",
    "backend/app/services/report_lint.py", "backend/app/api/research.py",
    "backend/app/api/report.py", "backend/scripts/export_demo_site_data.py",
    "backend/scripts/main_offline_pytest.py", "backend/tests/test_oddsense_workflow.py",
    "backend/app/services/forecast_feedback.py", "backend/app/services/forecast_ledger.py",
    "backend/app/services/forecast_track_record.py", "backend/app/api/sdk.py",
    "backend/scripts/backfill_report_visuals.py",
)


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json(path):
    return json.loads(Path(path).read_text())


class Log:
    def __init__(self):
        self.lines = []

    def write(self, kind, message):
        self.lines.append([kind, str(message)])


class NoExternalIntelligence:
    model_name = "scripted-offline-only"

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        def reject(*args, **kwargs):
            self.calls.append(name)
            raise AssertionError("Unscripted external intelligence: " + name)
        return reject


def _articles():
    published = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat() + "T09:00:00Z"
    return [{"source": {"id": "controlled-publisher", "name": "Controlled Publisher"},
             "author": "Acceptance fixture", "title": f"Synthetic capacity announcement {index}",
             "description": f"Controlled publisher discovery {index}; fetch the article for details.",
             "url": url, "publishedAt": published,
             "content": "A discovery snippet is not a fetched publisher body."}
            for index, url in enumerate(NEWS_URLS, 1)]


def _kalshi():
    return {"ticker": TICKER, "event_ticker": "CAPACITY-27", "market_type": "binary",
            "title": "Will semiconductor capacity grow by the end of 2027?", "subtitle": "Synthetic fixture",
            "yes_sub_title": "Capacity grows", "no_sub_title": "Capacity does not grow",
            "yes_bid_dollars": "0.4000", "yes_ask_dollars": "0.4400",
            "no_bid_dollars": "0.5600", "no_ask_dollars": "0.6000", "last_price_dollars": "0.4100",
            "volume_fp": "123.00", "open_interest_fp": "45.00", "status": "open",
            "created_time": "2026-10-16T00:00:00Z", "updated_time": "2026-10-18T00:00:00Z",
            "close_time": "2027-12-31T23:59:59Z",
            "rules_primary": "Synthetic capacity index at year end must exceed its previous year end value.",
            "rules_secondary": "Use the synthetic publisher annual release; no real trade or resolution."}


def _quote_lines(text):
    """Copy supplied quote evidence only; never synthesize absent provider fields."""
    names = (TICKER, "quote_basis", "price_unit", "probability_basis", "quote_at", "quote time",
             "outcome", "rules_primary", "rules_secondary", "yes_bid", "yes_ask", "last_price")
    return "\n".join(line for line in text.splitlines() if any(name in line for name in names))


def _require_native_quote(text):
    # Renderers may escape Markdown underscores, while values remain identical.
    shown = html.unescape(text).replace("\\_", "_")
    for value in (TICKER, "0.41", "0.4", "0.44", "USD_per_contract",
                  "provider_reported_dollars_per_contract", "last_price_dollars/1_USD_binary_payout",
                  _kalshi()["rules_primary"], _kalshi()["rules_secondary"]):
        assert value in shown, (value, shown)
    for field, value in (("yes_bid", "0.4"), ("yes_ask", "0.44"), ("last_price", "0.41")):
        pattern = rf'\b{field}["\s]*[:=]\s*"?{re.escape(value)}0*(?![\d.])'
        assert re.search(pattern, shown), (field, shown)
    assert re.search(r"\boutcome\b[^\n]{0,20}\bYes\b", shown), shown
    assert re.search(r"quote(?:[ _-]*(?:at|time))[^\n]{0,40}\b(?:unknown|null)\b", shown, re.I), shown


class NativeTransport:
    """Native NewsAPI/Reddit responses at ContextClient's transport boundary."""
    def __init__(self, social_status=403):
        self.calls = []
        self.social_status = social_status

    def __call__(self, url, *, headers, timeout, max_bytes):
        parts = urlsplit(url)
        assert timeout <= 5 and max_bytes <= 2 * 1024 * 1024
        assert "offline-news-sentinel" not in url
        self.calls.append({"provider_host": parts.hostname, "path": parts.path,
                           "query": parts.query, "header_names": sorted(headers)})
        if parts.hostname == "newsapi.org":
            assert parts.path == "/v2/everything"
            assert parse_qs(parts.query)["language"] == ["en"]
            assert headers["X-Api-Key"] == "offline-news-sentinel"
            return 200, json.dumps({"status": "ok", "totalResults": 2, "articles": _articles()}).encode()
        assert parts.hostname in {"www.reddit.com", "reddit.com", "oauth.reddit.com"}, parts.hostname
        if self.social_status != 200:
            return self.social_status, b'{"message":"fixture-denied-private-body"}'
        return 200, json.dumps({"kind": "Listing", "data": {"children": [{"kind": "t3", "data": {
            "id": "controlledpost", "name": "t3_controlledpost", "title": "Synthetic capacity discussion",
            "permalink": "/r/semiconductors/comments/controlledpost/capacity/",
            "subreddit": "semiconductors", "selftext": "An attributed opinion, with unknown publication time.",
            "created_utc": None, "score": 7, "num_comments": 2,
        }}], "after": None}}).encode()


def _market_http(monkeypatch, market, trace):
    """Keep real _Transport and its admission/normalization; replace HTTPS I/O."""
    class Connection:
        sock = None

        def __init__(self, host, timeout):
            self.host = host
            assert host in {"gamma-api.polymarket.com", "external-api.kalshi.com"}
            assert 0 < timeout <= 5

        def request(self, method, path, headers):
            assert method == "GET"
            trace.append({"host": self.host, "path": path, "method": method})
            if self.host == "gamma-api.polymarket.com":
                payload = {"events": []}
            elif urlsplit(path).path == "/trade-api/v2/markets":
                payload = {"markets": [_kalshi()], "cursor": ""}
            else:
                assert urlsplit(path).path == f"/trade-api/v2/markets/{TICKER}"
                payload = {"market": _kalshi()}
            self.body = json.dumps(payload).encode()

        def getresponse(self):
            return self

        @property
        def status(self):
            return 200

        def read1(self, size):
            result, self.body = self.body[:size], self.body[size:]
            return result

        def close(self):
            pass

    monkeypatch.setattr(market.http.client, "HTTPSConnection", Connection)


class ScriptedModel:
    """Content-routed provider responses; the real ModelGateway owns every call."""
    model_name = "scripted-oddsense"

    def __init__(self, gateway, trace):
        self.gateway, self.trace, self.tools = gateway, trace, None

    def bind(self, **kwargs):
        return copy.copy(self)

    def bind_tools(self, tools):
        clone = copy.copy(self)
        clone.tools = tools
        return clone

    def invoke(self, messages):
        _, _, AI, _ = self.gateway._msg_classes()
        last = messages[-1].content
        all_text = "\n".join(str(message.content) for message in messages)
        tool_results = [message.content for message in messages if message.type == "tool"]
        role = "agent" if self.tools is not None else str(last).split("\n", 1)[0]
        self.trace.append({"role": role, "tool_results": len(tool_results),
                           "tools": [row["function"]["name"] for row in self.tools or []]})
        calls = []
        if last.startswith("CACHE WARM-UP"):
            text = "OK"
        elif self.tools is not None:
            if not tool_results and not last.startswith("STOP"):
                calls = [{"name": name, "args": {"query": "capacity"}, "id": "call-" + name}
                         for name in ("news_search", "market_compare")]
                text = ""
            elif len(tool_results) == 2 and not last.startswith("STOP"):
                calls = [{"name": "web_fetch", "args": {"url": MARKET_URL, "focus": "capacity rules quote"},
                          "id": "call-fetch-market"}]
                text = ""
            else:
                sids = list(dict.fromkeys(re.findall(r"\[S(\d+)\]", "\n".join(tool_results))))
                assert sids, "Scripted agent was never shown any real tool evidence"
                text = ("## Findings\n" + "\n".join(
                    f"- Synthetic capacity source retains attributed context [S{sid}] (REPORTED)" for sid in sids)
                    + "\n## Conflicts\n- Contract equivalence is unestablished.\n## Open questions\n"
                    "- Future capacity remains uncertain.\n## Discovered\n- Publisher methods need continued review.")
        elif last.startswith("SCOPE TASK"):
            text = json.dumps({"restated_question": QUESTION, "horizon": "2027-12-31",
                               "scout_queries": ["capacity"]})
        elif last.startswith("PLANNING TASK"):
            self.on_plan()
            text = json.dumps({"kiqs": [
                {"question": "What do capacity publishers report?", "queries": ["capacity"], "kind": "general"},
                {"question": "What are capacity market contract limitations?", "queries": ["capacity rules"], "kind": "general"}],
                "sections": [{"title": title, "kiqs": [1, 2], "focus": title} for title in
                             ("Publisher evidence", "Market contract limitations", "Scenarios and probabilities", "Signposts")],
                "scenarios": [{"name": "Baseline", "weight": 60, "thesis": "Gradual expansion."},
                              {"name": "Stress", "weight": 40, "thesis": "Expansion is delayed."}],
                "actors": [], "key_entities": ["Synthetic capacity publisher"]})
        elif last.startswith("SECTION WRITING TASK") or last.startswith("EXECUTIVE SUMMARY TASK"):
            sids = list(dict.fromkeys(re.findall(r"\[S(\d+)\]", all_text)))
            assert sids, "Writers must consume the actual research digest"
            cites = " ".join(f"[S{sid}]" for sid in sids)
            quote_evidence = _quote_lines(all_text)
            if last.startswith("SECTION WRITING TASK"):
                self.trace[-1]["supplied_quote_context"] = quote_evidence
            titles = [line[3:] for line in last.split("Rules:")[0].splitlines() if line.startswith("## ")]
            if last.startswith("EXECUTIVE SUMMARY TASK"):
                titles = ["Executive Summary"]
            text = "\n\n".join(
                f"## {title}\n\n" + self._paragraph(title, cites) for title in titles)
        elif last.startswith("FACT EXTRACTION TASK"):
            text = json.dumps({"key_events": [], "quantitative_facts": [], "contested_claims": []})
        else:
            raise AssertionError("Unscripted model task: " + str(last)[:120])
        return AI(content=text, tool_calls=calls,
                  usage_metadata={"input_tokens": 300, "output_tokens": 200, "total_tokens": 500},
                  response_metadata={"finish_reason": "stop"})

    @staticmethod
    def _paragraph(title, cites):
        details = {
            "Publisher evidence": "The publisher announcements describe construction schedules and commissioning conditions. Fetched pages retain the attributed descriptions of factory projects and their stated assumptions.",
            "Market contract limitations": "The quoted contract defines a distinct annual measurement and settlement rule. Its last trade has no known trade timestamp, and topical similarity does not establish equivalence with this research question.",
            "Scenarios and probabilities": "The canonical scenario frame describes alternative project outcomes and keeps their weights explicit. Implementation delays may change the route to expansion while the settlement definition remains a separate issue.",
            "Signposts": "Monitor the annual release, permit decisions and completed construction milestones. The order of these observations matters because a project announcement alone cannot establish successful commissioning.",
            "Executive Summary": "The controlled publisher records and market contract provide attributed context for a synthetic capacity outlook. The evidence supports checking construction schedules and settlement definitions while preserving unknown timing and uncertainty.",
        }
        return f"{details.get(title, details['Publisher evidence'])} {cites} This is scripted acceptance evidence only."


def _forecast():
    """Publication input from scripted synthesis; keep real forecast quality checks."""
    from app.services import forecast_extractor as fe
    binaries = fe._normalize_binaries([
        {"statement": f"Synthetic capacity index >= {100 + index * 5} at year end 2027",
         "probability": probability, "theme": ["capacity", "construction", "demand"][index % 3],
         "horizon_year": 2027, "resolution_criteria": f"The synthetic annual publisher release records index >= {100 + index * 5} on 2027-12-31.",
         "resolution_source": "Synthetic annual publisher release",
         "scenario_membership": {"derivable": False, "yes_scenarios": []}}
        for index, probability in enumerate([.8, .76, .68, .64, .57, .42, .35, .27, .2, .12])])
    quality = fe._binary_quality(binaries, min_count=10)
    assert quality["passed"], quality
    assert all(not row.get("market_anchor") and not row.get("data_anchor") for row in binaries)
    return {"headline": "Synthetic capacity outlook", "horizon": "2027-12-31", "confidence": "medium",
            "scenarios": [{"name": "Baseline", "probability": .6,
                           "resolution_criteria": "The synthetic annual review records gradual expansion."},
                          {"name": "Stress", "probability": .4,
                           "resolution_criteria": "The synthetic annual review records delayed expansion."}],
            "binary_forecasts": binaries, "binary_quality": quality}


def _config(monkeypatch):
    env = {"NEWS_CONTEXT_ENABLED": "true", "NEWSAPI_ENABLED": "true", "NEWSAPI_MAX_REQUESTS": "2",
           "REDDIT_SIGNALS_ENABLED": "false", "MARKET_INTELLIGENCE_ENABLED": "true",
           "MARKET_INTELLIGENCE_MAX_REQUESTS": "4", "RESEARCH_SKILLS": "off", "DATA_SOURCES_ENABLED": "false",
           "PREDICTION_MARKETS_ENABLED": "false", "RESEARCH_CHARTS_MIN": "0",
           "RESEARCH_LINEAR_MAX_KIQS": "2", "RESEARCH_LINEAR_WORKERS": "1", "RESEARCH_LINEAR_GAP_ROUNDS": "0",
           "RESEARCH_LINEAR_CRITIQUE": "false", "RESEARCH_LINEAR_SECTIONS_MIN": "4",
           "RESEARCH_LINEAR_SECTIONS_MAX": "4", "REPORT_OUTPUT_LANGUAGE": "English"}
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return env


def _feedback_next_report(app, original_id, original, research_markdown, sources, capture,
                          external, demo, exporter, handoff, monkeypatch):
    """Exercise real SDK settlement and the next audited context-bearing report."""
    from app.services import forecast_ledger, forecast_track_record as history_api
    from app.services import news_market_context as context_api
    from app.services.report_agent import Report, ReportAgent, ReportManager, ReportStatus
    from app.config import Config

    ledger = Path(Config.FORECAST_LEDGER_DIR) / "published_forecasts.jsonl"
    stored = forecast_ledger.read_published_forecast(original_id)
    assert stored is not None
    assert stored["forecast"]["scenarios"] == _forecast()["scenarios"]
    assert stored["forecast"]["binary_forecasts"] == _forecast()["binary_forecasts"]
    untouched = ledger.read_bytes()
    resolved_path = Path(ReportManager._get_report_folder(original_id)) / "resolved.json"
    assert not resolved_path.exists()
    submitted_source = "https://publisher.example/synthetic-adjudication"
    submitted_evidence = {"fixture": True, "note": "Controlled manual adjudication only."}
    expected_evidence = {"adjudication": "manual_user", "externally_verified": False,
                         "source": submitted_source, "evidence": submitted_evidence}
    with app.test_client() as web:
        unknown = web.post(f"/api/v1/resolve/{original_id}", json={"outcome": "Unknown"})
        assert unknown.status_code == 400, unknown.get_json()
        assert ledger.read_bytes() == untouched
        assert not resolved_path.exists()
        settled = web.post(f"/api/v1/resolve/{original_id}", json={
            "outcome": "Baseline", "source": submitted_source, "evidence": submitted_evidence,
        })
        assert settled.status_code == 200, settled.get_json()
        score = settled.get_json()["data"]["scoring"]
        assert score["brier"] == pytest.approx(.32)
        assert score["realized_probability"] == .6
        committed = ledger.read_bytes()
        assert committed.startswith(untouched)
        resolved = _json(resolved_path)
        assert resolved["forecast"] == stored["forecast"]
        assert resolved["evidence"] == expected_evidence
        assert resolved["publication_sha256"] == stored["publication_sha256"]
        resolved_raw = resolved_path.read_bytes()
        duplicate = web.post(f"/api/v1/resolve/{original_id}", json={"outcome": "Baseline"})
        assert duplicate.status_code == 200 and duplicate.get_json()["data"]["scoring"] == score
        assert resolved_path.read_bytes() == resolved_raw
        conflict = web.post(f"/api/v1/resolve/{original_id}", json={"outcome": "Stress"})
        assert conflict.status_code == 409, conflict.get_json()
        assert ledger.read_bytes() == committed
        assert resolved_path.read_bytes() == resolved_raw
    assert forecast_ledger.read_published_forecast(original_id) == stored
    outcomes = forecast_ledger.read_published_resolutions(original_id)
    assert len(outcomes) == 1 and outcomes[0]["kind"] == "scenario"
    assert outcomes[0]["evidence"] == resolved["evidence"] == expected_evidence
    assert outcomes[0]["resolved_at"] == resolved["resolved_at"]
    assert outcomes[0]["publication_sha256"] == resolved["publication_sha256"]

    next_id = "report_oddsense_next"
    folder = Path(ReportManager._ensure_report_folder(next_id))
    agent = ReportAgent(original.graph_id, original.simulation_id, QUESTION,
                        llm_client=external, zep_tools=external, research_report=research_markdown,
                        sources=sources, news_market_context=capture)
    agent._forecast_spine = _forecast()
    (folder / "forecast.json").write_text(json.dumps(agent._forecast_spine))
    ReportManager.save_news_market_context(next_id, agent.news_market_context)
    outline = copy.deepcopy(original.outline)
    ReportManager.save_outline(next_id, outline)
    for index, section in enumerate(outline.sections, 1):
        ReportManager.save_section(next_id, index, section)
    report = Report(report_id=next_id, simulation_id=original.simulation_id, graph_id=original.graph_id,
                    simulation_requirement=QUESTION, status=ReportStatus.GENERATING,
                    outline=outline, markdown_content=ReportManager.assemble_full_report(next_id, outline),
                    created_at=datetime.now(timezone.utc).isoformat())
    ReportManager.save_report(report)
    assert forecast_ledger.read_published_forecast(next_id) is None
    agent._append_news_market_context(next_id, report)
    agent._prepend_binary_forecasts_section(next_id, report)
    agent._append_resolution_section(next_id, report)
    agent._apply_report_lint(next_id, report)
    stabilization = agent._stabilize_publish_markdown(next_id, report, max_passes=6)
    audit = agent._enforce_final_publish_audit(next_id, report)
    report.status = ReportStatus.COMPLETED
    report.completed_at = datetime.now(timezone.utc).isoformat()
    ReportManager.save_report(report)
    publication = ReportManager.publication_status(next_id)
    assert publication["publishable"], publication
    assert audit["hard_passed"] and audit["publish_gate"]["passed"]
    assert audit["news_market_context"]["valid"] and audit["news_market_context"]["markdown_present"]
    assert audit["forecast_track_record"]["passed"] and audit["forecast_track_record"]["required"]
    assert audit["forecast_sha256"] == _hash(folder / "forecast.json")
    assert audit["markdown_sha256"] == _hash(folder / "full_report.md")
    forecast = _json(folder / "forecast.json")
    history = forecast["historical_calibration"]["forecast_track_record"]
    frozen_history = (folder / "forecast_track_record.json").read_bytes()
    frozen_context = (folder / "news_market_context.json").read_bytes()
    assert _json(folder / "forecast_track_record.json") == history
    assert history["n_reports"] == 1 and history["excluded_report_id"] == next_id
    assert history["tracks"]["scenario"]["n_resolved"] == 1
    assert history["tracks"]["scenario"]["mean_brier"] == pytest.approx(.32)
    assert history["tracks"]["unanchored_binary"]["n_forecasts"] == 10
    assert history["tracks"]["unanchored_binary"]["n_resolved"] == 0
    for kind in ("market_binary", "official_data_binary"):
        assert history["tracks"][kind]["n_forecasts"] == 0
    assert forecast_ledger.verify_production_track_record(history, exclude_report_id=next_id)
    markdown = report.markdown_content
    assert history_api.render(history, "English") in markdown
    assert context_api.render_context(capture) in markdown
    assert markdown.count(history_api.START) == markdown.count(history_api.END) == 1
    _require_native_quote(markdown)
    # Reapplying real finalization must preserve both exact canonical blocks.
    agent._stabilize_publish_markdown(next_id, report, max_passes=6)
    repeated_audit = agent._enforce_final_publish_audit(next_id, report)
    assert repeated_audit["hard_passed"] and report.markdown_content == markdown
    ReportManager.save_report(report)
    assert (folder / "forecast_track_record.json").read_bytes() == frozen_history
    assert (folder / "news_market_context.json").read_bytes() == frozen_context
    # Reconstruct through the actual persisted-report replay consumer. Its
    # stabilization/audit must retain both frozen canonical metadata owners.
    from scripts import backfill_report_visuals as backfill
    reconstructed = backfill._offline_report_agent(
        "English", sources, handoff, {}, _json(folder / "forecast.json"), report_id=next_id)
    assert reconstructed.news_market_context == capture
    reconstructed._stabilize_publish_markdown(next_id, report, max_passes=6)
    replay_audit = reconstructed._enforce_final_publish_audit(next_id, report)
    assert replay_audit["hard_passed"] and report.markdown_content == markdown
    ReportManager.save_report(report)
    assert (folder / "forecast_track_record.json").read_bytes() == frozen_history
    assert (folder / "news_market_context.json").read_bytes() == frozen_context
    # A fresh audit updates diagnostic quality fields in forecast.json; the
    # forecast response must match those current persisted bytes.
    forecast = _json(folder / "forecast.json")
    assert forecast["historical_calibration"]["forecast_track_record"] == history
    with app.test_client() as web:
        detail = web.get(f"/api/report/{next_id}")
        assert detail.status_code == 200
        payload = detail.get_json()["data"]
        assert payload["publishable"] and payload["markdown_content"] == markdown
        assert payload["news_market_context"] == capture
        response = web.get(f"/api/report/{next_id}/forecast")
        assert response.status_code == 200 and response.get_json()["data"]["forecast"] == forecast
        download = web.get(f"/api/report/{next_id}/download")
        assert download.status_code == 200 and download.data == markdown.encode()
    exporter.export_report("oddsense-next-controlled", next_id, str(demo))
    assert (demo / "report.md").read_bytes() == download.data == (folder / "full_report.md").read_bytes()

    # Drive the actual replay transaction to its PDF boundary, then simulate an
    # external export failure. Real repair/audit and backup/rollback remain active.
    pipeline_id = handoff.parent.name
    from app.services.pipeline_orchestrator import PipelineManager, PipelineState
    PipelineManager.save(PipelineState(
        pipeline_id=pipeline_id, report_id=next_id, simulation_id=original.simulation_id,
        prompt=QUESTION, handoff_dir=str(handoff)))
    def bundle():
        return {str(path.relative_to(folder)): path.read_bytes() for path in folder.rglob("*")
                if path.is_file() and not any(part.startswith(".codex-backup-") for part in path.parts)}
    before_replay, journal_before_replay = bundle(), ledger.read_bytes()
    pdf_attempts, replay_calls, mutated_paths = [], [], []
    real_stabilize = ReportAgent._stabilize_publish_markdown
    real_audit = ReportAgent._enforce_final_publish_audit
    def observe_stabilize(self, rid, value, *args, **kwargs):
        result = real_stabilize(self, rid, value, *args, **kwargs)
        replay_calls.append({"stage": "stabilize", "report_id": rid})
        return result
    def observe_audit(self, rid, value, *args, **kwargs):
        result = real_audit(self, rid, value, *args, **kwargs)
        replay_calls.append({"stage": "audit", "report_id": rid, "hard_passed": result["hard_passed"]})
        return result
    def fail_pdf(cls, rid, force=False, lang=None):
        # Prove that the failure occurs after the real canonical audit.
        assert replay_calls == [{"stage": "stabilize", "report_id": rid},
                                {"stage": "audit", "report_id": rid, "hard_passed": True}]
        current_audit = _json(folder / "final_audit.json")
        assert current_audit["hard_passed"] and current_audit["forecast_track_record"]["passed"]
        assert current_audit["news_market_context"]["valid"]
        current_bundle = bundle()
        mutated_paths.extend(sorted(name for name in before_replay.keys() | current_bundle.keys()
                                    if before_replay.get(name) != current_bundle.get(name)))
        assert mutated_paths, "Rollback must undo an observed real replay mutation"
        pdf_attempts.append({"report_id": rid, "lang": lang})
        raise OSError("synthetic replay PDF write failure")
    with monkeypatch.context() as replay_patch:
        replay_patch.setattr(Config, "REPORT_VIZ_PNG_EXPORT", False)
        replay_patch.setattr(ReportAgent, "_stabilize_publish_markdown", observe_stabilize)
        replay_patch.setattr(ReportAgent, "_enforce_final_publish_audit", observe_audit)
        replay_patch.setattr(ReportManager, "export_pdf", classmethod(fail_pdf))
        with pytest.raises(OSError, match="synthetic replay PDF write failure"):
            backfill.backfill_one(pipeline_id, next_id, apply=True)
    assert pdf_attempts == [{"report_id": next_id, "lang": None}]
    assert bundle() == before_replay and ledger.read_bytes() == journal_before_replay
    backups = list(folder.glob(".codex-backup-*/replay_failure.json"))
    assert len(backups) == 1 and _json(backups[0])["restored"] is True
    assert ReportManager.is_publishable(next_id)
    companion = folder / "forecast_track_record.json"
    frozen = companion.read_bytes()
    forged = copy.deepcopy(history)
    forged["tracks"]["scenario"]["mean_brier"] = 0.0
    companion.write_text(json.dumps(forged))
    assert not ReportManager.publication_status(next_id)["publishable"]
    with app.test_client() as web:
        denied = web.get(f"/api/report/{next_id}/download")
        assert denied.status_code == 409
    companion.write_bytes(frozen)
    assert ReportManager.is_publishable(next_id)
    assert forecast_ledger.read_published_forecast(original_id) == stored
    assert external.calls == []
    return {"original_snapshot": stored, "resolution": outcomes[0], "score": score,
            "unknown_outcome_status": unknown.status_code, "conflict_status": conflict.status_code,
            "next_report_id": next_id, "next_history": history, "publication": publication,
            "final_audit": replay_audit, "stabilization": stabilization,
            "reconstructed_replay": {"canonical_blocks_preserved": True,
                                     "audit": replay_audit},
            "transactional_replay_recovery": {"pdf_attempts": pdf_attempts,
                "delegated_real_calls": replay_calls, "observed_mutated_paths": mutated_paths,
                "restored_exact_bundle": True, "journal_unchanged": True,
                "failure_receipt": str(backups[0])},
            "download_sha256": hashlib.sha256(download.data).hexdigest(),
            "export_sha256": _hash(demo / "report.md"), "history_tamper_status": denied.status_code,
            "next_snapshot": forecast_ledger.read_published_forecast(next_id)}


@pytest.mark.guarded_runner
def test_scripted_engine_to_published_report_api_and_export(tmp_path, monkeypatch):
    evidence_root = Path(os.environ["MAIN_OFFLINE_EVIDENCE"])
    before = {name: _hash(REPO / name) for name in SOURCES}
    receipt = {"schema": "oddsense-workflow/v1", "controlled_scripted": True,
               "live_provider_proof": False, "source_before": before, "stage": "imports"}
    log = Log()
    try:
        monkeypatch.syspath_prepend(str(REPO / "deerflow_bridge"))
        import news_signals as news
        import market_intelligence as market
        import research_gateway as rg
        import linear_research as lr
        import deerflow_research as bridge
        # Simulate the wall-clock planning gap that occurs after real prefetch,
        # without sleeping or changing actual engine/QA/deadline implementations.
        planning_gap = [0]
        class SourceClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz) + timedelta(seconds=planning_gap[0])
        monkeypatch.setattr(news, "datetime", SourceClock)
        from app.config import Config
        from app.services import pipeline_orchestrator as po
        from app.services import news_market_context as carrier_api
        from app.services import forecast_ledger
        from app.services.report_agent import (
            Report, ReportAgent, ReportManager, ReportOutline, ReportSection, ReportStatus)
        from app.services.official_data import capture_research_generation, bind_simulation_research
        from app.services.simulation_manager import SimulationManager

        env = _config(monkeypatch)
        transport, market_trace, model_trace, fetch_trace, tool_trace = NativeTransport(), [], [], [], []
        receipt.update(provider_transport=transport.calls, market_transport=market_trace,
                       model_trace=model_trace, fetch_trace=fetch_trace, tool_trace=tool_trace)
        _market_http(monkeypatch, market, market_trace)
        research = tmp_path / "research"
        client = news.ContextClient(research, question=QUESTION, language="English", as_of=lr._utc_date(),
                                  transport=transport, api_key="offline-news-sentinel",
                                  news_enabled=True, social_enabled=False, max_news_requests=2)
        model = ScriptedModel(rg, model_trace)
        model.on_plan = lambda: planning_gap.__setitem__(0, 120)
        receipt["simulated_planning_gap_seconds"] = 120
        original_context = rg.ResearchTools.context_query

        def observed_context(self, name, query, *, agent_id, deadline=None):
            result = original_context(self, name, query, agent_id=agent_id, deadline=deadline)
            tool_trace.append({"name": name, "query": query, "agent_id": agent_id, "output": result})
            return result
        monkeypatch.setattr(rg.ResearchTools, "context_query", observed_context)

        def fetch(url):
            assert url in [*NEWS_URLS, MARKET_URL], url
            fetch_trace.append(url)
            if url == MARKET_URL:
                return "# Synthetic capacity market\n\n" + _kalshi()["rules_primary"] + "\n\n" + ScriptedModel._paragraph("Market contract limitations", "")
            return "# Synthetic capacity announcement\n\n" + ScriptedModel._paragraph("Publisher evidence", "")

        def tools_factory(ledger, pages, bridge, reporter, limits):
            return rg.ResearchTools(ledger, pages, bridge=bridge, plog=reporter, limits=limits,
                                    context_client=client, fetch_fn=fetch,
                                    search_fn=lambda query, n: json.dumps({"query": query, "results": [
                                        {"url": url, "title": article["title"], "content": article["description"]}
                                        for url, article in zip(NEWS_URLS, _articles())]}))
        args = SimpleNamespace(model=model.model_name, depth="quick", target_language="English", no_actors=True)
        def gateway_factory(args, reporter, bridge, preset):
            return rg.ModelGateway(model, reporter, max_concurrency=1, budget_units=preset.budget_units,
                                   reserve_share=lr.RESERVE_SHARE, sleep=lambda seconds: None)
        metadata = {}
        def write_metadata():
            # The CLI supplies this persistence callback in production. The
            # assessment sidecar must keep its actual producer metadata pin.
            (research / "meta.json").write_text(json.dumps(metadata, ensure_ascii=False))
        engine = lr._Engine(QUESTION, research, args, metadata, log, write_metadata, bridge,
                            gateway_factory, tools_factory, env)
        receipt["stage"] = "full production engine"
        assert engine.execute() == 0, (engine.meta, log.lines)
        receipt["research_qa"] = engine.qa
        assert engine.qa["passed"], engine.qa
        assert all(engine.state.is_done(phase) for phase in lr.PHASES)
        assert {row["name"] for row in tool_trace} >= {"news_search", "market_compare"}
        assert any(row["agent_id"] == "context-prefetch" for row in tool_trace)
        assert any(row["agent_id"].startswith("K") and row["name"] == "market_compare" for row in tool_trace)
        assert any(row["tool_results"] >= 2 for row in model_trace if row["role"] == "agent")
        for call in tool_trace:
            if call["name"] == "market_compare":
                _require_native_quote(call["output"])
        writer_calls = [call for call in model_trace if call["role"] == "SECTION WRITING TASK"]
        assert writer_calls
        for call in writer_calls:
            _require_native_quote(call["supplied_quote_context"])
        assert set(fetch_trace) == {*NEWS_URLS, MARKET_URL}
        assert any(row["host"] == "external-api.kalshi.com" for row in market_trace)
        assert len([row for row in transport.calls if row["provider_host"] == "newsapi.org"]) <= 2

        capture = news.load_context(research)
        assert capture["sealed"] is True and capture["as_of"] == engine.plan.as_of
        assert engine.qa["news_market_context_sha256"] == capture["sha256"]
        provider_status = {row["provider"]: row["status"] for row in capture["queries"]}
        assert provider_status["newsapi"]["state"] == "ok"
        assert provider_status["kalshi"]["state"] == "ok"
        assert provider_status["polymarket"]["state"] == "verified_empty"
        assert provider_status["metaculus"]["state"] == "unsupported"
        assert provider_status["metaculus"]["attempted"] is False
        reservations = {row["provider"]: row["network_requests"] for row in capture["queries"]
                        if row["provider"] in {"polymarket", "kalshi", "metaculus"}}
        assert reservations == {"polymarket": 1, "kalshi": 2, "metaculus": 0}
        assert sum(reservations.values()) == len(market_trace)
        receipt["market_network_admissions"] = reservations
        items = {item["url"]: item for item in capture["items"]}
        assert set(items) == {*NEWS_URLS, MARKET_URL}, capture
        kalshi = items[MARKET_URL]
        assert kalshi["id"] == "kalshi:" + TICKER and kalshi["probability"] == .41
        assert kalshi["yes_bid"] == .4 and kalshi["yes_ask"] == .44
        assert kalshi["quote_at"] is None and kalshi["rules_primary"] == _kalshi()["rules_primary"]
        assert all(item["eligibility"] == ELIGIBILITY for item in items.values())
        assert all(item["provider"] == "newsapi" for url, item in items.items() if url in NEWS_URLS)
        assert "offline-news-sentinel" not in json.dumps(capture)
        research_markdown = (research / "research_report.md").read_text()
        _require_native_quote(research_markdown)
        sources = _json(research / "sources.json")
        refs = {row["url"]: f"S{index}" for index, row in enumerate(sources, 1)}
        assert set(refs) == set(items)
        source_proofs = []
        for row in sources:
            item = items[row["url"]]
            assert row["context_id"] == item["id"] and row["provider"] == item["provider"]
            assert row["eligibility"] == ELIGIBILITY and row["source_origin"] == "fetched"
            # Repeated discovery may retain several captures of one native item.
            # The cited ledger row must match an actual retained capture exactly.
            retained = [record for query in capture["queries"] for record in query["items"]
                        if record["id"] == row["context_id"]
                        and record["url"] == row["url"]
                        and record["published_at"] == row["published_at"]
                        and record["retrieved_at"] == row["retrieved_at"]]
            assert retained, (row, capture["queries"])
            source_proofs.append({"source_ref": refs[row["url"]], "capture": retained[0]})
            assert f"[{refs[row['url']]}]" in research_markdown
            ledger_row = engine.ledger.find(row["url"])
            assert ledger_row["fetched"] is True
            assert _hash(engine.work / ledger_row["page_path"]) == row["content_sha256"]
            if row["provider"] == "kalshi":
                _require_native_quote(json.dumps(row))
                for field in ("yes_bid", "yes_ask", "last_price", "price_unit", "quote_basis",
                              "probability_basis", "outcome", "quote_at", "rules_primary", "rules_secondary"):
                    assert row["context_metadata"][field] == kalshi[field]
                    assert ledger_row["context_metadata"][field] == kalshi[field]
                assert row["context_evidence_sha256"] == retained[0]["evidence_sha256"]
        reloaded_ledger = rg.SourceLedger(engine.work / "sources_ledger.json", bridge=bridge)
        assert reloaded_ledger.rows() == engine.ledger.rows()
        assert not (research / "prediction_markets.json").exists()
        assert _json(research / "quantitative.json") == []

        receipt["stage"] = "parent promotion and consumed generation"
        monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))
        monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(tmp_path / "ledger"))
        pipeline_id = "pipe_oddsense"
        promoted = Path(po.PipelineManager.handoff_dir(pipeline_id))
        seal = po._promote_research_contract(str(research), str(promoted))
        assert po._validate_research_contract(str(promoted))
        capture_raw = (research / news.CONTEXT_FILENAME).read_bytes()
        assert (promoted / news.CONTEXT_FILENAME).read_bytes() == capture_raw
        assert seal["files"][news.CONTEXT_FILENAME]["sha256"] == hashlib.sha256(capture_raw).hexdigest()
        assert carrier_api.load_context(promoted) == capture
        sims = tmp_path / "simulations"
        (sims / "sim_oddsense").mkdir(parents=True)
        monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(sims))
        monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(sims))
        consumed = capture_research_generation(promoted)
        po.PipelineManager.save(po.PipelineState(
            pipeline_id=pipeline_id, prompt=QUESTION, simulation_id="sim_oddsense",
            handoff_dir=str(promoted)))
        bind_simulation_research("sim_oddsense", promoted, pipeline_id=pipeline_id, expected_generation=consumed)
        assert carrier_api.load_for_simulation("sim_oddsense") == capture
        receipt.update(capture=capture, research_sources=sources, final_source_refs=refs,
                       source_capture_proofs=source_proofs,
                       promotion=seal, consumed_generation=consumed)

        receipt["stage"] = "real report publication"
        for name, value in {"REPORT_STRUCTURED_FORECAST": True, "REPORT_PUBLISH_GATE": True,
                            "REPORT_CITATION_FINALIZER": True, "REPORT_EDITORIAL_LINT": True,
                            "REPORT_FINAL_READ_ONLY_AUDIT": True, "REPORT_VIZ_CHARTS": False,
                            "REPORT_FORECAST_LEDGER": True, "API_V1_ENABLED": True}.items():
            monkeypatch.setattr(Config, name, value, raising=False)
        monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
        report_id = "report_oddsense"
        report_dir = Path(ReportManager._ensure_report_folder(report_id))
        external = NoExternalIntelligence()
        agent = ReportAgent("graph_oddsense", "sim_oddsense", QUESTION, llm_client=external, zep_tools=external,
                            research_report=research_markdown, sources=_json(promoted / "sources.json"),
                            news_market_context=carrier_api.load_for_simulation("sim_oddsense"))
        assert agent.news_market_context == capture
        assert all(url in agent._prepend_research_background("Scripted analysis") for url in items)
        assert not agent._prediction_markets and not agent._market_pack and not agent._data_pack
        agent._forecast_spine = _forecast()
        (report_dir / "forecast.json").write_text(json.dumps(agent._forecast_spine))
        ReportManager.save_news_market_context(report_id, agent.news_market_context)
        assert ReportManager.load_report_news_market_context(report_id) == capture
        report_capture_raw = (report_dir / news.CONTEXT_FILENAME).read_bytes()
        # A report consumes the dossier as background. Its own narrative is
        # assembled from authored sections; its metadata section has one owner.
        titles = {section.title for section in engine.plan.sections} | {"Executive Summary"}
        outline = ReportOutline(title="Synthetic capacity outlook", summary="Controlled acceptance only.",
                                sections=[ReportSection(title=title, content=body)
                                          for title, body in lr.report_sections(research_markdown)
                                          if title in titles])
        assert len(outline.sections) == len(engine.plan.sections) + 1
        ReportManager.save_outline(report_id, outline)
        for index, section in enumerate(outline.sections, 1):
            ReportManager.save_section(report_id, index, section)
        assembled = ReportManager.assemble_full_report(report_id, outline)
        report = Report(report_id=report_id, simulation_id="sim_oddsense", graph_id="graph_oddsense",
                        simulation_requirement=QUESTION, status=ReportStatus.GENERATING,
                        outline=outline, markdown_content=assembled, created_at="2026-10-18T00:00:00Z",
                        completed_at="2026-10-18T00:01:00Z")
        ReportManager.save_report(report)
        assert forecast_ledger.read_published_forecast(report_id) is None
        # These are the same deterministic finalization/publication entrypoints
        # exercised by the official-data acceptance test; no admission bypass.
        agent._append_news_market_context(report_id, report)
        agent._prepend_binary_forecasts_section(report_id, report)
        agent._append_resolution_section(report_id, report)
        agent._apply_report_lint(report_id, report)
        stabilization = agent._stabilize_publish_markdown(report_id, report, max_passes=6)
        audit = agent._enforce_final_publish_audit(report_id, report)
        report.status = ReportStatus.COMPLETED
        ReportManager.save_report(report)
        publication = ReportManager.publication_status(report_id)
        receipt.update(publication=publication, final_audit=audit, stabilization=stabilization)
        assert publication["publishable"], publication
        assert audit["hard_passed"] and audit["publish_gate"]["passed"]
        assert audit["structured_forecast"]["valid"] and not audit["lint"]["changed"]
        assert audit["citation_body_markers"]["dangling"] == []
        assert audit["news_market_context"]["valid"] and audit["news_market_context"]["markdown_present"]
        assert audit["news_market_context"]["sha256"] == capture["sha256"]
        assert audit["markdown_sha256"] == _hash(report_dir / "full_report.md")
        assert audit["forecast_sha256"] == _hash(report_dir / "forecast.json")
        final_markdown = report.markdown_content
        _require_native_quote(final_markdown)
        citations = _json(report_dir / "citations.json")
        citation_json = json.dumps(citations)
        assert all(url in final_markdown and url in citation_json for url in items)
        assert all(item["title"] in final_markdown for item in items.values())
        citation_urls = {row["tag"]: row["url"] for row in citations["markers"]}
        assert set(citation_urls.values()) == set(items)
        for item in capture["items"]:
            lines = [line for line in final_markdown.splitlines()
                     if line.startswith("|") and item["url"] in line
                     and item["retrieved_at"] in line]
            assert lines, (item, final_markdown)
            assert any((item["published_at"] or "unknown") in line for line in lines)
            for line in lines:
                assert all(citation_urls[tag] == item["url"]
                           for tag in re.findall(r"\[(S\d+)\]", line))
        assert "context" in final_markdown.lower() and "unknown" in final_markdown.lower()
        forecast = _json(report_dir / "forecast.json")
        assert all(not row.get("data_anchor") and not row.get("market_anchor") for row in forecast["binary_forecasts"])
        assert "kalshi" not in json.dumps(forecast).lower() and "newsapi" not in json.dumps(forecast).lower()
        assert external.calls == []

        receipt["stage"] = "real Flask consumer and Markdown export"
        from app import create_app
        app = create_app()
        app.config["TESTING"] = True
        api_evidence = {}
        with app.test_client() as web:
            for url in (f"/api/research/{pipeline_id}/dossier", f"/api/report/{report_id}"):
                response = web.get(url)
                assert response.status_code == 200, response.get_data(as_text=True)
                payload = response.get_json()["data"]
                assert payload["news_market_context"] == capture
                _require_native_quote(json.dumps(payload["news_market_context"]))
                if "/research/" in url:
                    assert payload["report"] == research_markdown and payload["sources"] == sources
                    assert payload["sealed"] is True
                api_evidence[url] = {"status": response.status_code, "payload": payload}
            assert payload["publishable"] is True and payload["markdown_content"] == final_markdown
            download = web.get(f"/api/report/{report_id}/download")
            assert download.status_code == 200 and download.data == final_markdown.encode()
            api_evidence["download"] = {"status": download.status_code, "sha256": hashlib.sha256(download.data).hexdigest()}
        from scripts import export_demo_site_data as exporter
        monkeypatch.setattr(exporter, "UPLOADS", str(tmp_path))
        demo = tmp_path / "demo"
        demo.mkdir()
        exporter.export_report("oddsense-controlled", report_id, str(demo))
        exporter.export_dossier("oddsense-controlled", str(promoted), str(demo))
        _require_native_quote((demo / "report.md").read_text())
        _require_native_quote((demo / "dossier.md").read_text())
        assert (demo / "report.md").read_text() == final_markdown
        assert (demo / "dossier.md").read_text() == research_markdown
        assert all(url in (demo / "report.md").read_text() for url in items)
        receipt.update(flask=api_evidence, citations=citations,
                       report_markdown={"path": str(report_dir / "full_report.md"), "sha256": _hash(report_dir / "full_report.md")},
                       export={name: {"path": str(demo / name), "sha256": _hash(demo / name)}
                               for name in ("report.md", "dossier.md")})

        receipt["stage"] = "forecast feedback and next canonical report"
        next_demo = tmp_path / "next-demo"
        next_demo.mkdir()
        receipt["forecast_feedback"] = _feedback_next_report(
            app, report_id, report, research_markdown, sources, capture, external, next_demo, exporter, promoted, monkeypatch)

        receipt["stage"] = "immutable replay and fail-closed tamper"
        counts = (len(transport.calls), len(market_trace), len(fetch_trace), len(model_trace))
        assert client.seal() == capture
        assert client.search_news("capacity")["items"]
        assert client.market_compare("capacity")["items"]
        # Reconstruct the actual engine/client/ledger over the same stored generation.
        client = news.ContextClient(research, question=QUESTION, language="English", as_of=engine.plan.as_of,
                                    transport=transport, api_key="offline-news-sentinel")
        resumed = lr._Engine(QUESTION, research, args, {}, log, lambda: None, bridge,
                             gateway_factory, tools_factory, env)
        assert resumed.resumed and resumed.execute() == 0
        assert resumed.qa["passed"]
        with pytest.raises(news.ContextIntegrityError):
            news.ContextClient(research, question=QUESTION, language="English", as_of="2026-10-17",
                               transport=transport, api_key="offline-news-sentinel")
        assert (research / news.CONTEXT_FILENAME).read_bytes() == capture_raw
        assert counts == (len(transport.calls), len(market_trace), len(fetch_trace), len(model_trace))
        altered = dict(capture, generation_id="tampered-generation")
        (promoted / news.CONTEXT_FILENAME).write_text(json.dumps(altered))
        with pytest.raises(ValueError):
            carrier_api.load_context(promoted)
        assert not po._validate_research_contract(str(promoted))
        with pytest.raises(ValueError):
            carrier_api.load_for_simulation("sim_oddsense")
        with app.test_client() as web:
            denied = web.get(f"/api/research/{pipeline_id}/dossier")
            assert denied.status_code == 409
        (promoted / news.CONTEXT_FILENAME).write_bytes(capture_raw)
        assert carrier_api.load_context(promoted) == capture
        assert po._validate_research_contract(str(promoted))
        assert ReportManager.is_publishable(report_id)
        assert (report_dir / news.CONTEXT_FILENAME).read_bytes() == report_capture_raw
        assert _json(report_dir / news.CONTEXT_FILENAME) == capture
        # Publication also binds the exact report-local generation, after all
        # normal producer/consumer and positive download checks have succeeded.
        (report_dir / news.CONTEXT_FILENAME).write_text(json.dumps(altered))
        assert not ReportManager.publication_status(report_id)["publishable"]
        with app.test_client() as web:
            withheld = web.get(f"/api/report/{report_id}/download")
            assert withheld.status_code == 409
        (report_dir / news.CONTEXT_FILENAME).write_bytes(report_capture_raw)
        assert ReportManager.is_publishable(report_id)
        receipt["tamper_report_download_status"] = withheld.status_code
        receipt.update(stage="complete", replay_no_new_calls=True, tamper_dossier_status=denied.status_code,
                       external_intelligence_calls=external.calls)
    finally:
        after = {name: _hash(REPO / name) for name in SOURCES}
        receipt.update(source_after=after, source_unchanged=before == after, engine_log=log.lines)
        (evidence_root / "oddsense-workflow.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False))
        assert before == after, "Source drift: repeat acceptance on a fresh frozen mirror"


@pytest.mark.guarded_runner
@pytest.mark.parametrize("social_status,state", [(403, "forbidden"), (200, "partial")])
def test_optional_reddit_denial_and_unknown_time_reach_real_tool_and_store(tmp_path, monkeypatch, social_status, state):
    monkeypatch.syspath_prepend(str(REPO / "deerflow_bridge"))
    import news_signals as news
    import research_gateway as rg
    _config(monkeypatch)
    monkeypatch.setenv("REDDIT_SIGNALS_ENABLED", "true")
    transport = NativeTransport(social_status)
    client = news.ContextClient(tmp_path, question=QUESTION, language="English", as_of="2026-10-18",
                               transport=transport, api_key=None, news_enabled=False, social_enabled=True)
    ledger = rg.SourceLedger(tmp_path / "ledger.json")
    tools = rg.ResearchTools(ledger, tmp_path / "pages", context_client=client)
    output = tools.context_query("social_search", "capacity", agent_id="K1", deadline=rg.Deadline(10))
    assert state in output
    capture = client.seal()
    assert news.load_context(tmp_path) == capture
    assert len(transport.calls) == 1
    statuses = list(capture["providers"].values())
    assert any(row.get("state") == state or row.get("status", {}).get("state") == state for row in statuses)
    if social_status == 403:
        assert capture["items"] == [] and ledger.rows() == []
        assert "verified_empty" not in output and "fixture-denied-private-body" not in json.dumps(capture)
    else:
        item, = capture["items"]
        assert item["kind"] == "social_post" and item["provider"] == "reddit"
        assert item["published_at"] is None and item.get("probability") is None
        assert item["eligibility"] == ELIGIBILITY
        assert item["id"].startswith("reddit:") and "controlledpost" in item["id"]
        assert ledger.find(item["url"])["fetched"] is False
    (Path(os.environ["MAIN_OFFLINE_EVIDENCE"]) / f"oddsense-reddit-{social_status}.json").write_text(
        json.dumps({"controlled_scripted": True, "tool_output": output, "capture": capture,
                    "transport": transport.calls}, indent=2))


@pytest.mark.guarded_runner
def test_off_engine_preserves_missing_context_without_acquisition(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(REPO / "deerflow_bridge"))
    import research_gateway as rg
    import linear_research as lr
    import deerflow_research as bridge
    env = _config(monkeypatch)
    env["NEWS_CONTEXT_ENABLED"] = "false"
    monkeypatch.setenv("NEWS_CONTEXT_ENABLED", "false")
    external, log = NoExternalIntelligence(), Log()
    args = SimpleNamespace(model=external.model_name, depth="quick", target_language="English", no_actors=True)
    engine = lr._Engine(QUESTION, tmp_path, args, {}, log, lambda: None, bridge,
                        lambda args, reporter, bridge, preset: rg.ModelGateway(external, reporter),
                        lambda ledger, pages, bridge, reporter, limits: rg.ResearchTools(
                            ledger, pages, bridge=bridge, plog=reporter, limits=limits), env)
    engine.phase_context()
    engine._seal_context()
    assert engine.context_names == () and engine.tools.context_client is None
    assert not (tmp_path / "news_market_context.json").exists()
    assert len(engine.ledger) == 0 and external.calls == []
