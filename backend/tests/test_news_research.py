"""Controlled research-consumer checks; no provider HTTP or live model calls."""
from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

BRIDGE = Path(__file__).resolve().parents[2] / "deerflow_bridge"
if str(BRIDGE) not in sys.path:
    sys.path.insert(0, str(BRIDGE))
import linear_research as lr
import research_gateway as rg


def test_context_tool_reaches_real_kiq_dispatch():
    calls = []
    def context_query(name, query, *, agent_id, deadline):
        calls.append((name, query, agent_id))
        return "NEWS_CONTEXT: ok"
    engine = types.SimpleNamespace(tools=types.SimpleNamespace(context_query=context_query),
                                   agent_tools=[{"function": {"name": "news_search"}}])
    kiq = types.SimpleNamespace(id="K1", question="Capacity outlook")
    agent = lr.KiqAgent(engine, kiq, "task", [], rg.Deadline(30))
    result = agent._call_tool({"name": "news_search", "args": {"query": "Capacity outlook"}})
    assert result == "NEWS_CONTEXT: ok"
    assert calls == [("news_search", "Capacity outlook", "K1")]


def context_item(number=1):
    return {"id": f"newsapi:capacity-{number}", "native_id": f"capacity-{number}",
            "provider": "newsapi", "kind": "news_snippet", "title": f"Publisher capacity release {number}",
            "url": f"https://publisher.example/capacity-{number}",
            "snippet": "Publisher discovery snippet; the complete article must be fetched.",
            "published_at": "2026-10-17T09:00:00Z", "retrieved_at": "2026-10-18T10:00:00Z",
            "publisher": "Fixture Publisher", "language": "en", "query": "capacity",
            "eligibility": {"context_only": True, "anchor": False, "resolution": False}}


def test_ledger_snippet_fetch_reload_and_final_projection(tmp_path):
    ledger = rg.SourceLedger(tmp_path / "ledger.json")
    item = context_item()
    row = ledger.register_context(item, by="K1")
    assert row["fetched"] is False and row["content_sha256"] is None
    assert row["provider"] == "newsapi" and row["kind"] == "news_snippet"
    tools = rg.ResearchTools(ledger, tmp_path / "pages", fetch_fn=lambda url: ("The publisher reports 176 GW installed capacity in 2023. "
                                                   "The annual survey covers grid connections, construction permits and "
                                                   "operator investment. Demand grew 12% during the reporting period. " * 5))
    tools.fetch(item["url"], agent_id="K1")
    ledger.flush()
    restored = rg.SourceLedger(ledger.path)
    row = restored.get(row["sid"])
    assert row["fetched"] is True and row["provider"] == "newsapi"
    assert row["published_at"] == item["published_at"]
    engine = object.__new__(lr._Engine)
    engine.ledger, engine.tools, engine.bridge = restored, tools, None
    result = engine._source_rows([row["sid"]])[0]
    assert result["source_origin"] == "fetched"
    assert result["kind"] == "news_snippet" and result["retrieved_at"] == item["retrieved_at"]
    assert result["published_at"] == item["published_at"] and result["content_sha256"]
    assert result["eligibility"]["anchor"] is False


def test_static_schema_selection_preserves_disabled_identity_and_optional_tools():
    assert rg.context_tool_names({"NEWS_CONTEXT_ENABLED": "false"}) == ()
    assert rg.agent_tools_schema(False, ()) is rg.AGENT_TOOLS_SCHEMA
    assert rg.agent_tools_schema(True, ()) is rg.AGENT_TOOLS_WITH_DATA_SCHEMA
    names = rg.context_tool_names({"REDDIT_SIGNALS_ENABLED": "true"})
    tools = rg.agent_tools_schema(True, names)
    assert tools is rg.agent_tools_schema(True, names)
    assert {row["function"]["name"] for row in tools} >= {"news_search", "social_search", "market_compare", "data_get"}
    for row in rg.CONTEXT_TOOLS_SCHEMA:
        assert set(row["function"]["parameters"]["properties"]) == {"query"}


def test_context_gateway_budget_deadline_cancellation_and_cache(tmp_path):
    calls = []
    client = types.SimpleNamespace(search_news=lambda query, **kwargs: (
        calls.append(query) or {"provider": "newsapi", "status": {"state": "ok"}, "items": [context_item()]}))
    ledger = rg.SourceLedger(tmp_path / "ledger.json")
    tools = rg.ResearchTools(ledger, tmp_path / "pages", context_client=client,
                             limits=rg.ToolLimits(max_searches_total=2, max_searches_per_agent=1))
    assert "timeout" in tools.context_query("news_search", "expired", agent_id="K1", deadline=rg.Deadline(0))
    first = tools.context_query("news_search", "capacity", agent_id="K1", deadline=rg.Deadline(10))
    assert "[S1]" in first and ledger.get(1)["fetched"] is False
    assert tools.context_query("news_search", "capacity", agent_id="K1") == first
    assert "budget_exhausted" in tools.context_query("news_search", "other", agent_id="K1")
    assert calls == ["capacity"]
    engine = object.__new__(lr._Engine)
    engine.cancelled = True
    assert engine._watch_tool(tools.context_query, "context_query")("news_search", "cancel", agent_id="K2") == lr.CANCELLED_TOOL_TEXT
    assert calls == ["capacity"]
    tools.freeze_context()
    assert "stored_only" in tools.context_query("news_search", "new", agent_id="K2")


def test_context_agent_parallel_step_limits_and_duplicate_admission():
    calls = []
    schema = rg.agent_tools_schema(False, ("news_search", "social_search", "market_compare"))
    tools = types.SimpleNamespace(context_query=lambda name, query, **kw: calls.append((name, query)) or "CONTEXT ok")
    engine = types.SimpleNamespace(tools=tools, agent_tools=schema, preset=types.SimpleNamespace(workers=4))
    agent = lr.KiqAgent(engine, lr.Kiq("K1", "Capacity", []), "", [], rg.Deadline(30))
    inputs = [{"name": "news_search", "args": {"query": f"q{i}"}, "id": str(i)} for i in range(10)]
    agent._execute(inputs)
    assert len(calls) == lr.MAX_TOOL_CALLS_PER_STEP
    calls.clear()
    agent._execute([{"name": "news_search", "args": {"query": "same"}, "id": str(i)} for i in range(2)])
    assert calls == [("news_search", "same")]


@pytest.fixture
def stored_context_api(monkeypatch):
    """Actual ContextClient store/renderer; only source acquisition is scripted."""
    import news_signals as api
    calls = []
    def search_news(self, query, *, deadline=None):
        calls.append(query)
        return self.record_result("newsapi", query, {
            "provider": "newsapi", "query": query,
            "status": {"state": "ok", "attempted": True},
            "items": [dict(context_item(n), query=query) for n in (1, 2)],
            "retrieved_at": "2026-10-18T10:00:00Z"})
    monkeypatch.setattr(api.ContextClient, "search_news", search_news)
    monkeypatch.setattr(rg, "_context_api", lambda: api)
    monkeypatch.setenv("NEWS_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("NEWSAPI_ENABLED", "true")
    monkeypatch.setenv("REDDIT_SIGNALS_ENABLED", "true")
    monkeypatch.setenv("DATA_SOURCES_ENABLED", "false")
    monkeypatch.setenv("RESEARCH_SKILLS", "off")
    monkeypatch.setenv("RESEARCH_LINEAR_GAP_ROUNDS", "0")
    return api, calls


def test_real_engine_context_tools_to_fetched_publisher_to_cited_report(tmp_path, monkeypatch, stored_context_api):
    import test_research_engine_v3 as base
    import deerflow_research as dr
    api, queries = stored_context_api
    monkeypatch.setattr(dr, "_collect_prediction_markets", lambda *a, **kw: None)
    monkeypatch.setattr(dr, "_render_research_charts", lambda *a, **kw: {})
    fetched_urls = []
    original_tools = rg.ResearchTools
    def reordered_ledger(ledger, pages_dir, **kwargs):
        # This discovery is intentionally never shown/cited. Publisher ledger
        # IDs now differ from their cited-only final positions.
        ledger.register("https://uncited.example/discovery", "Uncited discovery")
        return original_tools(ledger, pages_dir, **kwargs)
    monkeypatch.setattr(rg, "ResearchTools", reordered_ledger)
    class NewsWorld(base.World):
        def agent(self, call):
            tools = [value for kind, value in call["messages"] if kind == "tool"]
            if not tools:
                return base.ai(tool_calls=[{"name": "news_search", "args": {"query": "capacity release"}, "id": "news"}])
            if len(tools) == 1:
                assert context_item()["url"] in tools[0] and "newsapi" in tools[0]
                return base.ai(tool_calls=[{"name": "web_fetch", "args": {"url": context_item()["url"], "focus": "capacity"}, "id": "page"}])
            return base.ai(self.notes(tools))
    world = NewsWorld()
    model = base.ScriptedModel(world)
    def fetch(url):
        fetched_urls.append(url)
        return base.page_text(url)
    rc, meta, plog, model, out = base.run_engine(tmp_path, dr, world, model=model, fetch=fetch)
    assert rc == 0, plog.text()
    snapshot = api.load_context(out)
    assert snapshot["sealed"] is True and snapshot["items"]
    assert all("source_ref" not in item for item in snapshot["items"])
    assert context_item()["url"] in fetched_urls
    assert "capacity release" in queries and queries[0] != "capacity release"
    report = (out / "research_report.md").read_text()
    sources = json.loads((out / "sources.json").read_text())
    source = next(row for row in sources if row.get("context_id") == context_item()["id"])
    assert source["source_origin"] == "fetched" and source["content_sha256"]
    assert source["published_at"] == context_item()["published_at"]
    assert source["provider"] == "newsapi" and source["kind"] == "news_snippet"
    assert len(sources) >= 2
    assert all(row["url"] != "https://uncited.example/discovery" for row in sources)
    ledger = json.loads((out / "v3/sources_ledger.json").read_text())
    original_sid = next(row["sid"] for row in ledger if row["url"] == source["url"])
    assert original_sid != sources.index(source) + 1
    assert f"[S{sources.index(source) + 1}]" in report and source["url"] in report
    assert "News and market context" in report
    for role in ("PLANNING TASK", "agent", "SECTION WRITING TASK"):
        assert any("Publisher capacity" in text for call in base.calls_of(model, role) for _, text in call["messages"])
    bound = [call["tools"] for call in base.calls_of(model, "agent")]
    assert bound and all(schema is bound[0] for schema in bound)
    qa = json.loads((out / "v3/qa.json").read_text())
    assert qa["passed"] is True, qa["failures"]
    assert qa["news_market_context_sha256"] == snapshot["sha256"]
    assert qa["news_market_context_citations"][rg.canonical_url(source["url"])] == f"S{sources.index(source) + 1}"
    before = list(queries)
    rc2, _, log2, _, _ = base.run_engine(tmp_path, dr, world, out_dir=out)
    assert rc2 == 0, log2.text()
    assert queries == before
    assert api.load_context(out)["sha256"] == snapshot["sha256"]
    # Source identities are pinned: a present altered generation is rejected,
    # without obtaining a replacement article from the scripted acquisition.
    path = out / "news_market_context.json"
    raw = path.read_text()
    state = json.loads((out / "v3/state.json").read_text())
    assert state["news_market_context_binding"] == {
        "generation_id": snapshot["generation_id"], "sha256": snapshot["sha256"]}
    rollback = json.loads(raw)
    rollback["sealed"] = False
    rollback["sha256"] = hashlib.sha256(json.dumps(
        {key: value for key, value in rollback.items() if key != "sha256"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    path.write_text(json.dumps(rollback))
    rolled_rc, rolled_meta, _, _, _ = base.run_engine(tmp_path, dr, world, out_dir=out)
    assert rolled_rc == 2 and "news_context_evidence_corrupt" in str(rolled_meta.get("error"))
    assert queries == before
    path.write_text(raw.replace("Fixture Publisher", "Changed Publisher"))
    rc3, meta3, _, _, _ = base.run_engine(tmp_path, dr, world, out_dir=out)
    assert rc3 == 2 and "news_context_evidence_corrupt" in str(meta3.get("error"))
    assert queries == before
    path.write_text(raw)
    # Changing the saved planning cutoff cannot acquire a replacement capture.
    plan_path = out / "v3/plan.json"
    plan_raw = plan_path.read_text()
    plan = json.loads(plan_raw)
    plan["as_of"] = "2025-01-01"
    plan_path.write_text(json.dumps(plan))
    rc4, meta4, _, _, _ = base.run_engine(tmp_path, dr, world, out_dir=out)
    assert rc4 == 2 and "news_context_evidence_corrupt" in str(meta4.get("error"))
    assert queries == before
    plan_path.write_text(plan_raw)
    path.unlink()
    rc5, meta5, _, _, _ = base.run_engine(tmp_path, dr, world, out_dir=out)
    assert rc5 == 2 and "captured generation is missing" in str(meta5.get("error"))
    assert queries == before


def test_interrupted_gather_resumes_by_sealing_existing_capture(tmp_path, monkeypatch, stored_context_api):
    import test_research_engine_v3 as base
    import deerflow_research as dr
    api, calls = stored_context_api
    monkeypatch.setattr(dr, "_collect_prediction_markets", lambda *a, **kw: None)
    monkeypatch.setattr(dr, "_render_research_charts", lambda *a, **kw: {})
    original_seal = lr._Engine._seal_context
    original_synthesize = lr._Engine.phase_synthesize
    monkeypatch.setattr(lr._Engine, "_seal_context", lambda self: None)
    def stop(self):
        raise lr._EngineFailure("fixture interruption after gather")
    monkeypatch.setattr(lr._Engine, "phase_synthesize", stop)
    world = base.World()
    rc, meta, log, _, out = base.run_engine(tmp_path, dr, world)
    assert rc == 2 and "fixture interruption" in meta["error"], log.text()
    snapshot = api.load_context(out, require_sealed=False)
    assert snapshot["sealed"] is False
    before = list(calls)
    monkeypatch.setattr(lr._Engine, "_seal_context", original_seal)
    monkeypatch.setattr(lr._Engine, "phase_synthesize", original_synthesize)
    rc2, _, log2, _, _ = base.run_engine(tmp_path, dr, world, out_dir=out)
    assert rc2 == 0, log2.text()
    assert api.load_context(out)["sealed"] is True
    assert calls == before


def legacy_runtime(monkeypatch):
    """Minimal native configuration boundary; no vendored code is executed."""
    import deerflow_research as dr
    import news_tools
    module = types.ModuleType("deerflow.config.tool_config")
    module.ToolConfig = lambda **kw: types.SimpleNamespace(**kw)
    monkeypatch.setitem(sys.modules, "deerflow.config.tool_config", module)
    for name in rg.CONTEXT_TOOL_METHODS:
        monkeypatch.setattr(news_tools, name + "_tool", types.SimpleNamespace(name=name), raising=False)
    scoped = types.SimpleNamespace(tools=["web_search", "web_fetch"], disallowed_tools=[], system_prompt="existing")
    app = types.SimpleNamespace(tools=[types.SimpleNamespace(name="web_search", use="search_tools:web_search_tool")],
        subagents=types.SimpleNamespace(custom_agents={"scoped-researcher": scoped}), guardrails=None)
    return dr, types.SimpleNamespace(_agent=None, _app_config=app), scoped


def test_legacy_preserved_config_trusted_registration_allowlist_and_off(monkeypatch):
    dr, client, scoped = legacy_runtime(monkeypatch)
    monkeypatch.setenv("NEWS_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("REDDIT_SIGNALS_ENABLED", "true")
    monkeypatch.setattr(dr, "_LEGACY_CONTEXT_REPLAY_ONLY", False)
    record = dr._register_legacy_context_tools(client)
    assert record["status"] == "ready"
    assert set(record["available_tools"]) == set(rg.CONTEXT_TOOL_METHODS)
    assert set(scoped.tools) >= set(rg.CONTEXT_TOOL_METHODS)
    assert "existing" in scoped.system_prompt and "context only" in scoped.system_prompt
    dr._register_legacy_context_tools(client)
    assert len({row.name for row in client._app_config.tools}) == len(client._app_config.tools)
    monkeypatch.setenv("NEWS_CONTEXT_ENABLED", "false")
    assert dr._register_legacy_context_tools(client)["status"] == "disabled"
    assert [row.name for row in client._app_config.tools] == ["web_search"]
    assert not set(scoped.tools) & set(rg.CONTEXT_TOOL_METHODS)
    # Explicit scoped denial survives trusted registration of preserved YAML.
    monkeypatch.setenv("NEWS_CONTEXT_ENABLED", "true")
    scoped.disallowed_tools = ["social_search"]
    scoped.tools = ["web_search"]
    dr._register_legacy_context_tools(client)
    assert "social_search" not in scoped.tools and "news_search" in scoped.tools


def test_legacy_real_stream_prefetch_fetch_and_pre_qa_cited_context(tmp_path, monkeypatch, stored_context_api):
    import test_research_engine_v3 as base
    api, calls = stored_context_api
    dr, client, scoped = legacy_runtime(monkeypatch)
    monkeypatch.setattr(dr, "_FETCHED_SOURCES", [])
    monkeypatch.setattr(dr, "_PINNED_CITATION_INDEX", [])
    monkeypatch.setattr(dr, "_LEGACY_CONTEXT_CLIENT", None)
    monkeypatch.setattr(dr, "_LEGACY_CONTEXT_TOOLS", None)
    monkeypatch.setattr(dr, "_LEGACY_CONTEXT_NAMES", ())
    monkeypatch.setattr(dr, "_LEGACY_CONTEXT_ROOT", None)
    monkeypatch.setattr(dr, "_LEGACY_CONTEXT_REPLAY_ONLY", False)
    monkeypatch.setattr(dr, "_LEGACY_CONTEXT_LANGUAGE", "en")
    monkeypatch.setattr(rg, "_default_fetch_fn", base.page_text)
    question = "Will capacity exceed 250 GW in 2027?"
    args = types.SimpleNamespace(target_language="English", resume=False, synthesis_manifest=None, extract_only=False)
    log = base.FakePlog()
    monkeypatch.setenv("DEERFLOW_RUN_ARTIFACT_DIR", str(tmp_path))
    dr._prepare_legacy_context(tmp_path, question, args, plog=log)
    assert dr._register_legacy_context_tools(client)["status"] == "ready"
    dr._prefetch_legacy_context(question, log, {})
    assert len(calls) == 1
    manifest = dr.export_fetched_sources_for_manifest()
    assert len(manifest) == 2 and all(row["provider"] == "newsapi" for row in manifest)
    assert all(row["source_origin"] == "fetched" and row["content_sha256"] for row in manifest)
    prompt = dr.build_scoped_worker_prompt(question, "Publisher capacity", "English")
    assert "Publisher capacity release" in prompt
    # Execute the real streamed-turn accounting and pre-QA finalizer. Only
    # chat events/acquisition and the judge's external model call are scripted.
    def stream(message, **kwargs):
        import news_tools
        yield types.SimpleNamespace(type="messages-tuple", data={"type": "ai", "tool_calls": [
            {"id": "news", "name": "news_search", "args": {"query": "capacity release"}}]})
        result = news_tools.news_search_impl("capacity release")
        yield types.SimpleNamespace(type="messages-tuple", data={"type": "tool", "name": "news_search", "tool_call_id": "news", "content": result})
        yield types.SimpleNamespace(type="messages-tuple", data={"type": "ai", "tool_calls": [
            {"id": "page", "name": "web_fetch", "args": {"url": context_item()["url"]}}]})
        yield types.SimpleNamespace(type="messages-tuple", data={"type": "tool", "name": "web_fetch", "tool_call_id": "page", "content": base.page_text(context_item()["url"])})
        yield types.SimpleNamespace(type="messages-tuple", data={"type": "ai", "id": "final", "content": (
            "# Capacity research\n\n## Findings\n\nCapacity reached 176 GW in 2023 [S1].\n\n"
            "## References\n\n[S1] Publisher release — " + context_item()["url"])})
    client.stream = stream
    report = dr.run_streamed_turn(client, prompt, "controlled", 20, log, "controlled legacy")
    observed = []
    def judge(report, *args, **kwargs):
        assert api.load_context(tmp_path)["sealed"] is True
        observed.append(report)
        return {"verdict": "PASS"}
    monkeypatch.setattr(dr, "judge_research_report", judge)
    final, verdict = dr._finalize_and_judge_report(report, question, "English", "quick", "scripted", log, context="controlled")
    assert verdict["verdict"] == "PASS" and final == observed[0]
    assert context_item()["url"] in final and "[S1]" in final
    assert "news-market-context:start" in final
    snapshot = api.load_context(tmp_path)
    assert all("source_ref" not in item for item in snapshot["items"])
    assert len(calls) == 2
    # A restarted consumer loads the same sealed bytes, with no acquisition.
    args.resume = True
    dr._prepare_legacy_context(tmp_path, question, args, plog=log)
    dr._prefetch_legacy_context(question, log, {})
    assert len(calls) == 2


def test_parent_identity_survives_angle_lanes_and_synthesis_never_refetches(tmp_path, monkeypatch, stored_context_api):
    import hashlib
    import test_research_engine_v3 as base
    import deerflow_research as dr
    api, calls = stored_context_api
    question = "Will capacity exceed 250 GW by the end of 2027?"
    parent = hashlib.sha256(question.encode()).hexdigest()
    monkeypatch.setenv("NEWS_CONTEXT_QUESTION_SHA256", parent)
    monkeypatch.setattr(dr, "_collect_prediction_markets", lambda *a, **kw: None)
    monkeypatch.setattr(dr, "_render_research_charts", lambda *a, **kw: {})
    lane_dirs = []
    for index, angle in enumerate(("Demand angle", "Supply angle")):
        root = tmp_path / f"lane-{index}"
        rc, _, log, _, _ = base.run_engine(tmp_path, dr, base.World(),
                                         question=f"{angle}: {question}", out_dir=root)
        assert rc == 0, log.text()
        assert api.load_context(root)["question_sha256"] == parent
        lane_dirs.append(root)
    synthesis = tmp_path / "synthesis"
    merged = api.merge_contexts(lane_dirs, synthesis)
    assert merged["sealed"] and merged["question_sha256"] == parent
    before = list(calls)
    monkeypatch.setattr(dr, "_LEGACY_CONTEXT_CLIENT", None)
    monkeypatch.setattr(dr, "_LEGACY_CONTEXT_TOOLS", None)
    monkeypatch.setattr(dr, "_LEGACY_CONTEXT_NAMES", ())
    monkeypatch.setattr(dr, "_LEGACY_CONTEXT_ROOT", None)
    monkeypatch.setattr(dr, "_LEGACY_CONTEXT_REPLAY_ONLY", False)
    monkeypatch.setattr(dr, "_LEGACY_CONTEXT_LANGUAGE", "en")
    monkeypatch.setenv("DEERFLOW_RUN_ARTIFACT_DIR", str(synthesis))
    # Existing merged generation means the consumer does not open the manifest
    # again; parent orchestration already validated and merged those lanes.
    args = types.SimpleNamespace(target_language="English", resume=False,
                                 synthesis_manifest="already-merged-context", extract_only=False)
    dr._prepare_legacy_context(synthesis, question, args)
    dr._prefetch_legacy_context(question, base.FakePlog(), {})
    assert dr._LEGACY_CONTEXT_REPLAY_ONLY is True
    assert api.load_context(synthesis) == merged and calls == before
    assert "Publisher capacity release" in dr._legacy_context_prompt_block()


def test_market_contract_reaches_real_gateway_kiq_synthesis_and_source_projection(tmp_path, monkeypatch):
    import news_signals as api
    import market_intelligence as market
    import test_market_intelligence as fixtures
    monkeypatch.setenv("NEWS_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("MARKET_INTELLIGENCE_ENABLED", "true")
    monkeypatch.setenv("MARKET_INTELLIGENCE_MAX_REQUESTS", "4")
    monkeypatch.delenv("NEWS_CONTEXT_QUESTION_SHA256", raising=False)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "backend"))
    replies = [
        {"events": [{"title": "Inflation", "slug": "inflation", "markets": [fixtures.poly()]}]},
        {"markets": [fixtures.kalshi()], "cursor": ""},
        {"market": fixtures.kalshi(rules_secondary="Distinct Kalshi detail rules")},
    ]
    physical = []
    class Connection:
        sock = None
        status = 200
        def __init__(self, host, timeout):
            assert host in ("gamma-api.polymarket.com", "external-api.kalshi.com")
            assert 0 < timeout <= 5
            self.host = host
        def request(self, method, path, headers):
            assert method == "GET"
            physical.append((self.host, path))
            self.body = json.dumps(replies.pop(0)).encode()
        def getresponse(self):
            return self
        def read1(self, size):
            value, self.body = self.body[:size], self.body[size:]
            return value
        def close(self):
            pass
    monkeypatch.setattr(market.http.client, "HTTPSConnection", Connection)
    # Exercise the actual market normalization and actual ContextClient store.
    root = tmp_path / "market"
    client = api.ContextClient(root, question="CPI 2026", language="en", as_of=lr._utc_date())
    ledger = rg.SourceLedger(root / "ledger.json")
    tools = rg.ResearchTools(ledger, root / "pages", context_client=client)
    output = tools.context_query("market_compare", "CPI 2026", agent_id="K1", deadline=rg.Deadline(10))
    assert len(physical) == 3
    assert client.snapshot()["network_requests"]["market"] == 3
    for text in ("outcome: Yes", "probability: 0.2", "probability: 0.43", "yes_bid: 0.42", "yes_ask: 0.44",
                 "USD_per_contract", "provider_reported_dollars_per_contract", "last_price_dollars/1_USD_binary_payout",
                 "volume: 1.5", "contracts", "quote_at: unknown", "CPI strictly above 3 at the specified release.",
                 "Distinct Kalshi detail rules", "2026-12-31", "floor_strike: 3"):
        assert text in output
    assert '"No", "Yes"' in output and "0.8, 0.2" in output
    ledger.flush()
    restored = rg.SourceLedger(ledger.path)
    kalshi = next(row for row in restored.rows() if row.get("provider") == "kalshi")
    metadata = kalshi["context_metadata"]
    assert metadata["quote_at"] is None and metadata["probability"] == .43
    assert metadata["volume"] == 1.5 and metadata["volume_unit"] == "contracts"
    assert metadata["rules_secondary"] == "Distinct Kalshi detail rules"
    snapshot = client.seal()
    engine = object.__new__(lr._Engine)
    engine.backtest = None  # This source-projection case is an ordinary current run.
    engine.tools, engine.ledger, engine.language = tools, restored, lr.ENGLISH
    engine.context_snapshot = snapshot
    engine.bridge = None
    engine.agent_tools = rg.agent_tools_schema(False, ("market_compare",))
    monkeypatch.setattr(rg, "_context_api", lambda: api)
    text = engine._context_text()
    assert "probability: 0.2" in text and "probability: 0.43" in text
    assert "quote_at: unknown" in text and "Distinct Kalshi detail rules" in text
    agent = lr.KiqAgent(engine, lr.Kiq("K1", "Compare CPI market contracts", []), "", [], rg.Deadline(10))
    actual_tool_message = agent._call_tool({"name": "market_compare", "args": {"query": "CPI 2026"}})
    assert actual_tool_message == output  # replay, no second physical request
    assert len(physical) == 3
    # The digest consumed by section writers retains the same exact captured fields.
    engine._synth_context_cache = None
    engine.work = root
    engine.records, engine.kiqs = {}, []
    engine.preset = types.SimpleNamespace(digest_cap=10000)
    engine.meta = {}
    engine._with_official_data = lambda value: (value, 0)
    engine._data_rows = lambda: []
    digest = engine.synth_context()
    for text in ("probability: 0.43", "last_price_dollars/1_USD_binary_payout", "quote_at: unknown", "USD_per_contract"):
        assert text in digest
    final_sources = engine._source_rows([row["sid"] for row in restored.rows()])
    projected = next(row for row in final_sources if row["provider"] == "kalshi")
    assert projected["context_metadata"] == metadata
    assert projected["eligibility"]["anchor"] is False
    assert projected["source_origin"] == "context_quote"  # quote capture is not a fetched page
    zero = rg.context_evidence_metadata({"kind": "market_quote", "probability": 0.0, "quote_at": None})
    assert zero == {"probability": 0.0, "quote_at": None}


def test_context_on_changed_question_archives_capture_and_uses_new_generation(tmp_path, monkeypatch, stored_context_api):
    import test_research_engine_v3 as base
    import deerflow_research as dr
    api, queries = stored_context_api
    monkeypatch.setenv("NEWS_CONTEXT_ENABLED", "true")
    monkeypatch.delenv("NEWS_CONTEXT_QUESTION_SHA256", raising=False)
    monkeypatch.setattr(dr, "_collect_prediction_markets", lambda *a, **kw: None)
    monkeypatch.setattr(dr, "_render_research_charts", lambda *a, **kw: {})
    out = tmp_path / "reused-output"
    old_question = "Will capacity exceed 250 GW by 2027?"
    rc1, _, log1, _, _ = base.run_engine(tmp_path, dr, base.World(), question=old_question, out_dir=out)
    assert rc1 == 0, log1.text()
    old_capture_bytes = (out / "news_market_context.json").read_bytes()
    old_capture = api.load_context(out)
    old_client = api.get_context_client(out)
    old_state = json.loads((out / "v3/state.json").read_text())
    before = len(queries)
    new_question = "Will EU data-centre capacity double by 2030?"
    rc2, _, log2, _, _ = base.run_engine(tmp_path, dr, base.World(), question=new_question, out_dir=out)
    assert rc2 == 0, log2.text()
    archives = sorted(out.glob("v3.stale-*"))
    assert len(archives) == 1
    assert (archives[0] / "news_market_context.json").read_bytes() == old_capture_bytes
    assert api.load_context(archives[0]) == old_capture
    assert json.loads((archives[0] / "state.json").read_text()) == old_state
    new_capture = api.load_context(out)
    assert new_capture["generation_id"] != old_capture["generation_id"]
    assert new_capture["question_sha256"] == hashlib.sha256(new_question.encode()).hexdigest()
    assert len(queries) > before and new_capture["sealed"] is True
    assert api.get_context_client(out) is not old_client
    with pytest.raises(api.ContextIntegrityError):
        old_client.snapshot()
    new_state = json.loads((out / "v3/state.json").read_text())
    assert new_state["news_market_context_binding"]["sha256"] == new_capture["sha256"]
    assert "archived it to v3.stale-" in log2.text()
