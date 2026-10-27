"""FMP research acceptance: real MCP SDK, Engine, gateway and legacy consumers.

Only the HTTP transport and model/provider responses are scripted. No live
calls, credential files, services or production data are used.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import sys
import types
import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

BRIDGE = Path(__file__).resolve().parents[2] / "deerflow_bridge"
sys.path.insert(0, str(BRIDGE))
import fmp_mcp
import fmp_research as fr
import fmp_tools as ft
import linear_research as lr
import research_gateway as rg
import deerflow_research as dr
from test_fmp_mcp import Server, ENV, KEY, tool

PUBLISHER = "https://publisher.example/company-release"
FINANCIAL = {"symbol": "NVDA", "revenue": 176, "calendarYear": "2023", "currency": "USD",
             "capex": 250, "growth": 12, "label": "FINANCIAL_CAPTURE_SENTINEL"}
NEWS = {"title": "Company expansion announcement", "url": PUBLISHER,
        "publishedDate": "2026-10-20T09:00:00Z", "text": "NEWS_DISCOVERY_SENTINEL"}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("NEWS_CONTEXT_ENABLED", "false")
    monkeypatch.setenv("DATA_SOURCES_ENABLED", "false")
    monkeypatch.setenv("RESEARCH_SKILLS", "off")
    monkeypatch.setenv("RESEARCH_LINEAR_GAP_ROUNDS", "0")
    monkeypatch.setenv("RESEARCH_BUDGET_ENABLED", "false")
    monkeypatch.delenv("DRF_BACKTEST_POLICY", raising=False)
    monkeypatch.setenv("FMP_API_KEY", KEY)
    monkeypatch.setenv("FMP_ENABLED", "true")
    monkeypatch.setattr(dr, "_collect_prediction_markets", lambda *a, **kw: None)
    monkeypatch.setattr(dr, "_render_research_charts", lambda *a, **kw: {})
    dr._reset_fetched_sources()
    guard = sys.modules.get("main_offline_guard")
    if guard:
        for name in ("fmp_research.py", "fmp_tools.py", "fmp_mcp.py", "linear_research.py",
                     "research_gateway.py", "deerflow_research.py", "cached_fetch.py"):
            path = BRIDGE / name
            guard.source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        path = Path(__file__).parent / "fixtures/fmp_official_catalog.json"
        guard.source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    yield
    dr._close_legacy_fmp()


@pytest.fixture
def protocol(monkeypatch):
    catalog = json.loads((Path(__file__).parent / "fixtures/fmp_official_catalog.json").read_text())
    server = Server(pages=[{"tools": catalog["tools"]}])
    async def hook(request, body):
        if body and body.get("method") == "tools/call":
            data = NEWS if body["params"]["name"] == "news" else FINANCIAL
            # Actual official response shape: JSON rows carried in MCP text,
            # with no structuredContent or isError field.
            server.result = {"content": [{"type": "text", "text": json.dumps([data])}]}
    server.hook = hook
    original = fmp_mcp.FmpMcpClient
    created = []
    def factory(env=None, transport=None):
        created.append(True)
        return original(env=env, transport=server)
    monkeypatch.setattr(fmp_mcp, "FmpMcpClient", factory)
    return server, created


def make_tools(root, *, limits=None, replay=False, question="NVDA financial outlook"):
    store = fr.CaptureStore(root, question, env=ENV, replay=replay)
    ledger = rg.SourceLedger(root / "ledger.json")
    result = rg.ResearchTools(ledger, root / "pages", fmp_store=store, limits=limits,
                              fetch_fn=lambda url: pytest.fail("FMP identity escaped into web transport"))
    result.restore_fmp()
    return result


def call(tools, name="statements", **kwargs):
    return tools.fmp_query("fmp_call", tool=name, arguments=json.dumps({"endpoint": "search-stock-news", "symbols": ["NVDA"], "limit": 1, "page": 0} if name == "news" else {"endpoint": "income-statement", "symbol": "NVDA", "period": "annual", "limit": 1}),
                           agent_id="K1", deadline=rg.Deadline(10), **kwargs)


def test_real_gateway_exact_capture_citable_vendor_and_read_only_replay(tmp_path, protocol):
    server, created = protocol
    tools = make_tools(tmp_path)
    output = call(tools)
    assert "FINANCIAL_CAPTURE_SENTINEL" in output and "[S1]" in output
    assert "not a public article" in output
    row = tools.ledger.get(1)
    assert row["source_origin"] == "fmp_vendor" and "dataset" not in row
    assert not row["eligibility"]["official_data"] and not row["eligibility"]["simulation_truth"]
    raw = (tmp_path / row["capture_path"]).read_text()
    response = json.loads(raw)
    assert "structuredContent" not in response
    assert json.loads(response["content"][0]["text"]) == [FINANCIAL]
    assert response["data"] == response["content"]
    assert row["capture_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert tools.fetch(row["url"], agent_id="K1") == output
    count = len(server.requests)
    assert call(tools) == output
    tools.fmp_store.close()
    replay = make_tools(tmp_path, replay=True)
    assert call(replay) == output and len(created) == 1 and len(server.requests) == count
    assert "stored_only" in replay.fmp_query("fmp_call", tool="news", arguments={"symbol": "NVDA"}, agent_id="K1")
    with pytest.raises(fr.CaptureIntegrityError, match="replacement"):
        replay.ledger.mark_fetched(1, content_sha256="0" * 64, chars=1, page_path="other")


@pytest.mark.parametrize("mutation", ["missing_response", "changed_response", "missing_manifest", "missing_binding", "changed_question", "changed_ledger"])
def test_replay_rejects_missing_changed_capture_without_client(tmp_path, protocol, mutation):
    server, created = protocol
    tools = make_tools(tmp_path)
    call(tools)
    row = tools.ledger.get(1)
    if mutation == "missing_response":
        (tmp_path / row["capture_path"]).unlink()
    elif mutation == "changed_response":
        (tmp_path / row["capture_path"]).write_text("{}")
    elif mutation == "missing_manifest":
        (tmp_path / "fmp/captures.json").unlink()
    elif mutation == "missing_binding":
        (tmp_path / "fmp_research_binding.json").unlink()
    elif mutation == "changed_ledger":
        ledger = json.loads(tools.ledger.path.read_text())
        ledger[0]["fmp_capture"]["sha256"] = "0" * 64
        tools.ledger.path.write_text(json.dumps(ledger))
    count = len(server.requests)
    with pytest.raises(fr.CaptureIntegrityError):
        make_tools(tmp_path, replay=True, question="Different question" if mutation == "changed_question" else "NVDA financial outlook")
    assert len(created) == 1 and len(server.requests) == count


def test_quota_deadline_cutoff_and_sensitive_args_are_pretransport(tmp_path, protocol):
    server, _ = protocol
    tools = make_tools(tmp_path, limits=rg.ToolLimits(max_fetches_total=0))
    assert "research_budget_exhausted" in call(tools)
    tools.limits = rg.ToolLimits()
    assert "research_deadline_exhausted" in tools.fmp_query("fmp_call", tool="statements", arguments={"symbol": "NVDA"},
        agent_id="K1", deadline=rg.Deadline(0))
    for arguments in ({"apikey": "do-not-persist"}, {"symbol": "NVDA", "nested": {"token": KEY}}):
        assert "sensitive_request_rejected" in tools.fmp_query("fmp_call", tool="statements", arguments=arguments, agent_id="K1")
    tools.backtest = object()
    assert "historical/backtest" in call(tools)
    assert server.requests == []
    assert not tools.fmp_store.data["captures"]
    assert "do-not-persist" not in (tmp_path / "fmp/captures.json").read_text()


def test_news_capture_does_not_mark_publisher_fetched(tmp_path, protocol):
    tools = make_tools(tmp_path)
    text = call(tools, "news")
    row = tools.ledger.get(1)
    assert row["kind"] == "news_snippet" and row["fetched"] is False
    assert row["response_captured"] and not row["publisher_fetched"]
    assert tools.ledger.find(PUBLISHER) is None
    assert "NEWS DISCOVERY ONLY" in text and "original publisher page has not been fetched" in text


@pytest.mark.parametrize("question", ["Forecast NVDA by 2027", "Nvidia outlook next year", "Will semiconductor capex increase?"])
def test_relevant_ticker_and_sector_questions(question):
    assert fr.relevant(question)
    assert not fr.relevant("Who will win the French election?")


def test_projection_keeps_complete_schemas_and_explicit_omission():
    response = {"provider": "fmp", "tools": [tool(f"financial_{i}", description="Get data " + "x" * 1000) for i in range(256)]}
    text = fr.discovery_projection(response, max_chars=4000)
    projected = json.loads(text)
    assert len(text) <= 4000 and projected["omitted_tools"] > 250
    assert all(row["inputSchema"] == response["tools"][0]["inputSchema"] for row in projected["tools"])


def test_real_engine_planning_kiq_synthesis_citations_and_provider_free_resume(tmp_path, monkeypatch, protocol):
    import test_research_engine_v3 as base
    server, created = protocol
    fetched = []
    class FmpWorld(base.World):
        def agent(self, request):
            results = [text for kind, text in request["messages"] if kind == "tool"]
            task = request["messages"][2][1]
            assert "fmp_call" in task and "prioritize" in task.lower()
            if not results:
                assert "statements" in task and "news" in task
                return base.ai(tool_calls=[{"name": "fmp_call", "args": {"tool": "statements", "arguments": '{"endpoint":"income-statement","symbol":"NVDA","period":"annual","limit":1}'}, "id": "fin"}])
            if len(results) == 1:
                return base.ai(tool_calls=[{"name": "fmp_call", "args": {"tool": "news", "arguments": '{"endpoint":"search-stock-news","symbols":["NVDA"],"limit":1,"page":0}'}, "id": "news"}])
            if len(results) == 2:
                assert PUBLISHER in results[-1]
                return base.ai(tool_calls=[{"name": "web_fetch", "args": {"url": PUBLISHER}, "id": "publisher"}])
            notes = self.notes(results)
            publisher_sid = re.match(r"\[S(\d+)\]", results[-1]).group(1)
            notes = notes.replace("## Conflicts", f"- The original publisher confirms expansion [S{publisher_sid}] (VERIFIED)\n## Conflicts")
            return base.ai(notes)
    def fetch(url):
        fetched.append(url)
        return base.page_text(url)
    world = FmpWorld()
    question = "Forecast NVDA company revenue and financial news in 2027"
    rc, meta, log, model, out = base.run_engine(tmp_path, dr, world, question=question, fetch=fetch)
    assert rc == 0, log.text()
    assert PUBLISHER in fetched
    for role, expected in (("PLANNING TASK", "statements"), ("SECTION WRITING TASK", "FINANCIAL_CAPTURE_SENTINEL")):
        assert any(expected in text for item in base.calls_of(model, role) for _, text in item["messages"])
    rows = json.loads((out / "sources.json").read_text())
    vendor = [row for row in rows if row.get("fmp_capture")]
    assert vendor and all(row["source_origin"] != "official_data" for row in vendor)
    assert any(row["url"] == PUBLISHER and row["source_origin"] == "fetched" for row in rows)
    assert all((out / row["capture_path"]).is_file() for row in vendor)
    assert "captured MCP response" in (out / "research_report.md").read_text()
    before, clients = len(server.requests), len(created)
    rc2, _, log2, _, _ = base.run_engine(tmp_path, dr, world, question=question, out_dir=out, fetch=fetch)
    assert rc2 == 0, log2.text()
    assert len(server.requests) == before and len(created) == clients
    state = json.loads((out / "v3/state.json").read_text())
    assert state["fmp_research_binding"] == fr.CaptureStore(out, question, env={}, replay=True).proof()
    (out / vendor[0]["capture_path"]).unlink()
    rc3, meta3, _, _, _ = base.run_engine(tmp_path, dr, world, question=question, out_dir=out, fetch=fetch)
    assert rc3 == 2 and "fmp_capture_corrupt" in meta3["error"]
    assert len(server.requests) == before


def test_legacy_stream_public_tool_and_source_boundaries(tmp_path, monkeypatch, protocol):
    import test_research_engine_v3 as base
    server, created = protocol
    args = types.SimpleNamespace(depth="standard", resume=False, synthesis_manifest=None, extract_only=False)
    log, meta = base.FakePlog(), {}
    question = "NVDA company financial outlook"
    dr._prepare_legacy_fmp(tmp_path, question, args, meta=meta, plog=log)
    # The vendored DeerFlow config/SDK is not installed in this checkout. Only
    # its plain config carrier and reflection object are substituted; actual
    # registration, wrappers, stream accounting and citation finalization run.
    module = types.ModuleType("deerflow.config.tool_config")
    module.ToolConfig = lambda **kw: types.SimpleNamespace(**kw)
    monkeypatch.setitem(sys.modules, "deerflow.config.tool_config", module)
    original = ft.__getattr__
    monkeypatch.setattr(ft, "__getattr__", lambda name: types.SimpleNamespace(name=name.removesuffix("_tool"))
                        if name in ("fmp_search_tools_tool", "fmp_call_tool") else original(name))
    scoped = types.SimpleNamespace(tools=["web_search", "web_fetch"], disallowed_tools=[], system_prompt="existing")
    app = types.SimpleNamespace(tools=[], subagents=types.SimpleNamespace(custom_agents={"scoped-researcher": scoped}), guardrails=None)
    client = types.SimpleNamespace(_agent=None, _app_config=app)
    assert dr._register_legacy_fmp_tools(client)["status"] == "ready"
    dr._prefetch_legacy_fmp(question)
    prompt = dr.build_scoped_worker_prompt(question, "financial baseline and recent news", "English")
    assert "statements" in prompt and "news" in prompt
    def stream(message, **kwargs):
        for name, arguments in (("statements", '{"endpoint":"income-statement","symbol":"NVDA","period":"annual","limit":1}'), ("news", '{"endpoint":"search-stock-news","symbols":["NVDA"],"limit":1,"page":0}')):
            yield types.SimpleNamespace(type="messages-tuple", data={"type": "ai", "tool_calls": [
                {"id": name, "name": "fmp_call", "args": {"tool": name, "arguments": arguments}}]})
            result = ft.fmp_call_impl(name, arguments)
            yield types.SimpleNamespace(type="messages-tuple", data={"type": "tool", "name": "fmp_call", "tool_call_id": name, "content": result})
        yield types.SimpleNamespace(type="messages-tuple", data={"type": "ai", "id": "final", "content":
            "# Financial outlook\n\n## Findings\n\nVendor revenue was 176 USD in fiscal 2023 [S1]."})
    client.stream = stream
    report = dr.run_streamed_turn(client, prompt, "controlled", 20, log, "FMP legacy")
    dr._finalize_legacy_context(report, plog=log)
    final = dr.finalize_report_citations(report, log)
    assert "[S1]" in final and "captured MCP response" in final
    sources, _ = dr.merge_fetched_into_sources([])
    assert {row["source_origin"] for row in sources} == {"fmp_vendor", "fmp_news_snippet"}
    exported = dr.export_fetched_sources_for_manifest()
    assert all(row.get("fmp_capture") and row["publisher_fetched"] is False for row in exported)
    before, clients = len(server.requests), len(created)
    args.resume = True
    dr._prepare_legacy_fmp(tmp_path, question, args, meta=meta, plog=log)
    assert dr._register_legacy_fmp_tools(client)["status"] == "ready"
    dr._prefetch_legacy_fmp(question)
    assert "FINANCIAL_CAPTURE_SENTINEL" in dr.build_research_prompt(question, "standard", "English")
    assert len(server.requests) == before and len(created) == clients


def test_same_request_different_lane_payloads_keep_distinct_sources(tmp_path, protocol):
    first = make_tools(tmp_path / "lane1")
    call(first)
    second = make_tools(tmp_path / "lane2")
    call(second)
    a, b = first.ledger.get(1), second.ledger.get(1)
    # Retrieval instants are part of the exact response even when data agrees.
    assert a["url"] != b["url"]
    merged = fr.merge_captures([tmp_path / "lane1", tmp_path / "lane2"], tmp_path / "synthesis", "Parent financial question")
    assert len(merged.data["captures"]) == 2
    assert {item["url"] for item in merged.data["captures"].values()} == {a["url"], b["url"]}
    artifacts = fr.capture_artifacts(tmp_path / "synthesis")
    assert artifacts[a["capture_path"]] == (tmp_path / "lane1" / a["capture_path"]).read_bytes()
    assert artifacts[b["capture_path"]] == (tmp_path / "lane2" / b["capture_path"]).read_bytes()


@pytest.mark.parametrize("mutation", ["url", "news_fetched", "duplicate"])
def test_ledger_trust_and_citation_identity_tampering_rejected(tmp_path, protocol, mutation):
    tools = make_tools(tmp_path)
    call(tools, "news")
    path = tools.ledger.path
    rows = json.loads(path.read_text())
    if mutation == "url":
        rows[0]["url"] = "https://misattributed.example/article"
    elif mutation == "news_fetched":
        rows[0]["fetched"] = True
    else:
        rows.append({**rows[0], "sid": 2})
    path.write_text(json.dumps(rows))
    with pytest.raises(fr.CaptureIntegrityError, match="corrupt"):
        make_tools(tmp_path, replay=True)


def test_text_json_numbers_and_news_no_fetched_support(tmp_path, protocol):
    tools = make_tools(tmp_path)
    call(tools)
    call(tools, "news")
    _, result = lr.postprocess_notes("K1", "## Findings\n- Revenue was 176 in 2023 [S1] (VERIFIED)\n"
                                    "- News reports 176 in 2023 [S2] (VERIFIED)", tools.ledger.get,
                                    lambda sid: lr.page_number_set(tools.page_text(sid)), tools.page_text)
    assert result["facts"][0]["verified_numbers"] is True
    assert result["facts"][1]["verification"] == "no_fetched_source"
    assert result["facts"][1]["tag"] == "REPORTED"


def test_lock_queue_obeys_short_deadline_and_no_second_acquisition(tmp_path, protocol):
    tools = make_tools(tmp_path)
    held, release = threading.Event(), threading.Event()
    def hold():
        with tools.fmp_store.lock:
            held.set()
            release.wait(2)
    with ThreadPoolExecutor(max_workers=1) as pool:
        job = pool.submit(hold)
        assert held.wait(1)
        start = time.monotonic()
        result, item = tools.fmp_store.request("call", {"tool": "statements", "arguments": {}},
                                              deadline=start + 0.05)
        elapsed = time.monotonic() - start
        release.set()
        job.result()
    assert result["status"]["state"] == "timeout" and item is None
    assert elapsed < 0.3 and protocol[0].requests == []


def test_parallel_capture_checkpoint_publication_is_serial(tmp_path, protocol):
    tools = make_tools(tmp_path)
    entered, release = threading.Event(), threading.Event()
    checkpoints = []
    def checkpoint():
        if not entered.is_set():
            entered.set()
            assert release.wait(2)
        checkpoints.append(tools.fmp_store.proof())
    tools.fmp_checkpoint = checkpoint
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(call, tools)
        assert entered.wait(1)
        second = pool.submit(call, tools, "news")
        time.sleep(0.03)
        # The second capture cannot replace a generation while the first is
        # publishing its checkpoint. This forces the old stale-write ordering.
        assert len(tools.fmp_store.data["captures"]) == 1
        release.set()
        first.result()
        second.result()
    assert len(checkpoints) == 2 and checkpoints[-1] == tools.fmp_store.proof()


def prepare_legacy_capture(root, protocol):
    args = types.SimpleNamespace(depth="standard", resume=False, synthesis_manifest=None, extract_only=False)
    dr._prepare_legacy_fmp(root, "NVDA financial outlook", args, meta={})
    dr._LEGACY_FMP_NAMES = fr.TOOL_NAMES
    text = ft.fmp_call_impl("statements", '{"endpoint":"income-statement","symbol":"NVDA","period":"annual","limit":1}')
    assert "[S1]" in text
    return dr._LEGACY_FMP_TOOLS.ledger.get(1)


@pytest.mark.parametrize("shared", [False, True])
def test_legacy_shared_web_merge_preserves_fmp_first_citation(tmp_path, monkeypatch, protocol, shared):
    row = prepare_legacy_capture(tmp_path, protocol)
    web = {"url": PUBLISHER, "title": "Publisher", "ok": True, "content_sha256": "a" * 64,
           "content_chars": 400, "provider": "fixture-web"}
    dr._FETCHED_SOURCES.append(web)
    monkeypatch.setattr(dr, "_research_budget", types.SimpleNamespace(list_fetched_sources=lambda: [web] if shared else []))
    before = dr.build_citation_index(dr._FETCHED_SOURCES)
    dr._merge_shared_fetched_sources()
    after = dr.build_citation_index(dr._FETCHED_SOURCES)
    assert [(r["n"], r["url"]) for r in before] == [(r["n"], r["url"]) for r in after]
    assert after[0]["url"] == row["url"] and after[1]["url"] == PUBLISHER


def test_legacy_registered_fetch_capture_never_calls_public_web(tmp_path, protocol):
    import cached_fetch
    row = prepare_legacy_capture(tmp_path, protocol)
    async def forbidden(url):
        pytest.fail("capture correlation URL escaped to the web")
    text = asyncio.run(cached_fetch.cached_fetch(row["url"], forbidden))
    assert "FINANCIAL_CAPTURE_SENTINEL" in text
    pending = []
    dr._pending_record_fetch(pending, "web_fetch", {"url": row["url"]}, "captured-read",
                             receipt_scope={"thread_id": "actor", "lane": "track-b", "purpose": "actor dossier"})
    dr._pending_mark_result(pending, "web_fetch", text, "captured-read")
    dr._merge_pending_fetches(pending)
    assert pending == [] and not dr._FETCHED_SOURCES[0].get("receipt_scopes")
    (tmp_path / row["capture_path"]).unlink()
    assert "fmp_capture_corrupt" in asyncio.run(cached_fetch.cached_fetch(row["url"], forbidden))
    dr._close_legacy_fmp()
    assert "fmp_capture_corrupt" in asyncio.run(cached_fetch.cached_fetch(row["url"], forbidden))


def test_actual_main_resume_binds_before_source_restore_without_client(tmp_path, monkeypatch, protocol):
    prepare_legacy_capture(tmp_path, protocol)
    sources = dr.export_fetched_sources_for_manifest()
    (tmp_path / "sources.json").write_text(json.dumps(sources))
    dr.write_research_checkpoint(tmp_path, thread_id="research-fmp-resume", completed_passes=["deep-opening"],
                                fetched_source_count=1, gaps=[], depth="standard",
                                question_hash=dr._question_hash("NVDA financial outlook"))
    dr._reset_fetched_sources()
    before, clients = len(protocol[0].requests), len(protocol[1])
    monkeypatch.setenv("RESEARCH_ENGINE", "legacy")
    monkeypatch.setenv("RESEARCH_CHECKPOINT", "true")
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["deerflow_research.py", "--resume", "--model", "minimax", "--depth", "standard",
                                     "--out-dir", str(tmp_path), "--prompt", "NVDA financial outlook"])
    # The deliberate missing-model preflight stops after real resume admission,
    # before importing a harness client or executing a model/provider call.
    assert dr.main() == 3
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert meta["resume"]["resumed"] and meta["resume"]["restored_sources"] == 1
    assert dr._FETCHED_SOURCES[0]["url"] == sources[0]["url"]
    assert len(protocol[0].requests) == before and len(protocol[1]) == clients


@pytest.mark.parametrize("policy", ["global_deny", "scoped_deny", "empty_scope", "disabled", "custom_conflict"])
def test_runtime_registration_preserves_explicit_policy(monkeypatch, policy):
    module = types.ModuleType("deerflow.config.tool_config")
    module.ToolConfig = lambda **kw: types.SimpleNamespace(**kw)
    monkeypatch.setitem(sys.modules, "deerflow.config.tool_config", module)
    monkeypatch.setattr(ft, "__getattr__", lambda name: types.SimpleNamespace(name=name.removesuffix("_tool")))
    scoped = types.SimpleNamespace(tools=["web_fetch"], disallowed_tools=[], system_prompt="existing")
    app = types.SimpleNamespace(tools=[], subagents=types.SimpleNamespace(custom_agents={"scoped-researcher": scoped}), guardrails=None)
    client = types.SimpleNamespace(_agent=None, _app_config=app)
    if policy == "global_deny":
        app.guardrails = types.SimpleNamespace(enabled=True, provider=types.SimpleNamespace(
            use="deerflow.guardrails.builtin:AllowlistProvider", config={"denied_tools": ["fmp_call"]}))
    elif policy == "scoped_deny":
        scoped.disallowed_tools = ["fmp_call"]
    elif policy == "empty_scope":
        scoped.tools = []
    elif policy == "disabled":
        app.tools.append(types.SimpleNamespace(name="fmp_call", use="fmp_tools:fmp_call_tool", enabled=False))
    elif policy == "custom_conflict":
        app.tools.append(types.SimpleNamespace(name="fmp_call", use="custom:implementation"))
    result = ft.register(client, enabled=True)
    assert "fmp_call" not in scoped.tools
    if policy in ("global_deny", "disabled", "custom_conflict"):
        assert "fmp_call" not in result["available_tools"]
    if policy == "empty_scope":
        assert scoped.tools == []
    ft.register(client, enabled=False)
    assert not any(r.use == f"fmp_tools:{r.name}_tool" for r in app.tools)
    if policy == "custom_conflict":
        assert app.tools[0].use == "custom:implementation"
