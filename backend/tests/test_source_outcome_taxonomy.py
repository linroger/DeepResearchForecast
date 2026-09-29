"""RESEARCH-2: typed source outcomes (RESEARCH_SOURCE_TAXONOMY, default off).

Offline, no network: httpx, the DDG delegate, the fetch providers and the
model are fakes.  Covers the Firecrawl search failure classes, the search
refusal latch, DDG unconfirmed empties, provider substitution events, the
infra-vs-content fetch table and sentinels, the counting fix, the evidence
failure detail, the Firecrawl fetch quota disable (process latch + shared
circuit), negative-cache exclusion of outages, meta.source_health and the
research child env forwarding.  Every case also pins flag-off legacy bytes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import sys
import types
from pathlib import Path

import pytest

import test_research_engine_v3 as v3
from test_orchestrator_research_wiring import _launch_capturing_child

# The bridge modules (test_research_engine_v3 put deerflow_bridge on sys.path).
import cached_fetch as cf
import research_budget as rb
import search_tools as st

lr = v3.lr
rg = v3.rg

# The v3 engine fixtures (hermetic engine env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge

QUESTION = "Will global data-centre capacity exceed 250 GW by the end of 2027?"
REFUSAL_402 = json.dumps({"error": "firecrawl search HTTP 402", "query": "q",
                          "failure_class": "not_configured", "provider": "firecrawl", "reason": "http_402"})
BUDGET_ENVELOPE = json.dumps({"error": "research_budget_exhausted", "tool": "web_search", "results": []})


@pytest.fixture(autouse=True)
def _clean_provider_state(monkeypatch):
    """Process-local provider events and the fetch quota latch start empty."""
    monkeypatch.delenv("RESEARCH_SOURCE_TAXONOMY", raising=False)
    st.reset_provider_events()
    cf.reset_provider_events()
    yield
    st.reset_provider_events()
    cf.reset_provider_events()


def _taxonomy(monkeypatch, on: bool) -> None:
    monkeypatch.setenv("RESEARCH_SOURCE_TAXONOMY", "true" if on else "false")


def _tools(tmp_path, *, search_fn=None, fetch_fn=None, taxonomy=True, limits=None):
    ledger = rg.SourceLedger(tmp_path / "sources.json")
    tools = rg.ResearchTools(ledger, tmp_path / "pages", search_fn=search_fn or v3.fake_search,
                             fetch_fn=fetch_fn or v3.page_text, limits=limits or rg.ToolLimits())
    tools.source_taxonomy = taxonomy
    return tools


class _Recorder:
    """A search/fetch backend replaying one payload and counting calls."""

    def __init__(self, payload):
        self.payload = payload
        self.calls: list = []

    def __call__(self, *args):
        self.calls.append(args)
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


# ---------------------------------------------------------------- A.1 Firecrawl search classes

class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


def _fake_httpx(monkeypatch, *, status=200, raises=None):
    calls: list = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, headers=None, json=None):
            calls.append(json)
            if raises is not None:
                raise raises
            return _FakeResponse(status)

    module = types.ModuleType("httpx")
    module.Client = Client
    monkeypatch.setitem(sys.modules, "httpx", module)
    return calls


@pytest.fixture
def firecrawl_search_env(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
    monkeypatch.setenv("RESEARCH_FIRECRAWL_CALLS_PER_MINUTE", "0")
    monkeypatch.setattr(st, "_firecrawl_search_calls", 0)
    monkeypatch.setattr(st, "_firecrawl_ceiling_warned", False)


def test_firecrawl_search_classes(monkeypatch, firecrawl_search_env):
    _taxonomy(monkeypatch, True)
    for status, failure_class in ((402, "not_configured"), (401, "not_configured"), (503, "unavailable"),
                                  (404, "unavailable")):
        _fake_httpx(monkeypatch, status=status)
        payload = json.loads(st._firecrawl_search("q", 5))
        assert payload == {"error": f"firecrawl search HTTP {status}", "query": "q",
                           "failure_class": failure_class, "provider": "firecrawl", "reason": f"http_{status}"}

    _fake_httpx(monkeypatch, raises=ConnectionError("boom"))
    assert json.loads(st._firecrawl_search("q", 5)) == {
        "error": "firecrawl search failed: ConnectionError", "query": "q",
        "failure_class": "unavailable", "provider": "firecrawl", "reason": "ConnectionError"}

    monkeypatch.setenv("RESEARCH_FIRECRAWL_MAX_SEARCH_CALLS_PER_PROCESS", "1")
    monkeypatch.setattr(st, "_firecrawl_search_calls", 1)
    calls = _fake_httpx(monkeypatch, status=200)
    assert json.loads(st._firecrawl_search("q", 5)) == {
        "error": "firecrawl search per-run call ceiling reached (1)", "query": "q",
        "failure_class": "budget", "provider": "firecrawl", "reason": "per_run_call_ceiling"}
    assert calls == []


def test_firecrawl_search_flag_off_keeps_legacy_bytes(monkeypatch, firecrawl_search_env):
    _taxonomy(monkeypatch, False)
    _fake_httpx(monkeypatch, status=402)
    assert st._firecrawl_search("q", 5) == json.dumps(
        {"error": "firecrawl search HTTP 402", "query": "q"}, ensure_ascii=False)
    _fake_httpx(monkeypatch, raises=ConnectionError("boom"))
    assert st._firecrawl_search("q", 5) == json.dumps(
        {"error": "firecrawl search failed: ConnectionError", "query": "q"}, ensure_ascii=False)


# ---------------------------------------------------------------- D.3 refusal latch

def test_refusal_latch(tmp_path):
    backend = _Recorder(REFUSAL_402)
    tools = _tools(tmp_path, search_fn=backend)
    expected = ("SEARCH_NOT_CONFIGURED(firecrawl: http_402): the search service refused this run; no further "
                "search will work. Not evidence that sources are absent; use the sources you have or finish.")
    assert tools.search("first query", agent_id="K1") == expected
    reserved = tools.stats()["searches"]
    for query in ("second query", "third query", "first query"):
        assert tools.search(query, agent_id="K2") == expected
    assert len(backend.calls) == 1 and tools.stats()["searches"] == reserved == 1
    assert tools.outcome_counts()["search_not_configured"] == 4
    assert tools.search_refusal() == ("firecrawl", "http_402")
    assert tools._search_cache == {}
    assert not expected.startswith("[S") and lr.tool_output_sids("web_search", expected) == (None, [])


def test_refusal_latch_flag_off_keeps_legacy_text_and_retries(tmp_path):
    backend = _Recorder(REFUSAL_402)
    tools = _tools(tmp_path, search_fn=backend, taxonomy=False)
    assert [tools.search(q, agent_id="K1") for q in ("a query", "b query")] == [rg.MSG_SEARCH_UNAVAILABLE] * 2
    assert len(backend.calls) == 2 and tools.search_refusal() is None
    # Outcomes are counted with the flag off too; stats() is unchanged.
    assert tools.outcome_counts()["search_not_configured"] == 2
    assert tools.stats()["failures"] == 2 and set(tools.stats()) == {
        "searches", "cached_searches", "fetches", "cached_fetches", "failures", "per_agent"}


# ---------------------------------------------------------------- A.3 / D.3 DDG unconfirmed empty

def _ddg_delegate(monkeypatch, payload):
    calls: list = []

    def web_search(query, max_results=10):
        calls.append(query)
        return payload

    module = types.SimpleNamespace(web_search_tool=types.SimpleNamespace(func=web_search))
    monkeypatch.setattr(st, "_select_search_provider", lambda: "ddg")
    monkeypatch.setattr(st, "_load_search_module", lambda provider: module if provider == "ddg" else None)
    return calls


def test_ddg_empty_unconfirmed(monkeypatch, tmp_path):
    empty = json.dumps({"error": "No results found", "query": "q"}, ensure_ascii=False)
    _ddg_delegate(monkeypatch, empty)
    _taxonomy(monkeypatch, False)
    assert st.web_search_impl("q") == empty
    _taxonomy(monkeypatch, True)
    annotated = json.loads(st.web_search_impl("q"))
    assert annotated == {"error": "No results found", "query": "q", "empty_unconfirmed": True, "provider": "ddg"}
    assert st._is_search_no_result(json.dumps(annotated)) is False
    assert st._is_search_cacheable(json.dumps(annotated)) is False

    backend = _Recorder(json.dumps(annotated))
    tools = _tools(tmp_path, search_fn=backend)
    assert tools.search("some query", agent_id="K1") == rg.MSG_SEARCH_EMPTY_UNCONFIRMED
    assert tools.search("some query", agent_id="K1") == rg.MSG_SEARCH_EMPTY_UNCONFIRMED
    assert len(backend.calls) == 2 and tools._search_cache == {}
    assert tools.outcome_counts()["search_empty_unconfirmed"] == 2
    assert lr.tool_output_sids("web_search", rg.MSG_SEARCH_EMPTY_UNCONFIRMED) == (None, [])

    # The unannotated mapping pinned in test_research_gateway.py is unchanged, flag on or off.
    for taxonomy in (True, False):
        plain = _Recorder(empty)
        tools = _tools(tmp_path / str(taxonomy), search_fn=plain, taxonomy=taxonomy)
        assert tools.search("some query", agent_id="K1") == rg.MSG_NO_RESULTS
        assert tools.search("some query", agent_id="K1").startswith("(cached result")
        assert len(plain.calls) == 1 and tools.outcome_counts()["search_no_result"] == 1


def test_ddg_real_results_are_not_annotated(monkeypatch):
    rows = json.dumps({"query": "q", "total_results": 1,
                       "results": [{"title": "T", "url": "https://a.org/x", "content": "c"}]})
    _ddg_delegate(monkeypatch, rows)
    _taxonomy(monkeypatch, True)
    assert st.web_search_impl("q") == rows


# ---------------------------------------------------------------- A.2 substitution counter

def test_substitution_counter(monkeypatch):
    _ddg_delegate(monkeypatch, json.dumps({"query": "q", "results": []}))
    monkeypatch.setattr(st, "_select_search_provider", lambda: "serper")
    st.web_search_impl("q")
    st.web_search_impl("q2")
    assert st.provider_events() == {"substitution:serper->ddg": 2}
    snapshot = st.provider_events()
    snapshot["substitution:serper->ddg"] = 99
    assert st.provider_events() == {"substitution:serper->ddg": 2}

    st.reset_provider_events()
    monkeypatch.setattr(st, "_select_search_provider", lambda: "firecrawl")
    monkeypatch.setattr(st, "_firecrawl_search_available", lambda: False)
    st.web_search_impl("q")
    assert st.provider_events() == {"substitution:firecrawl->ddg": 1}

    st.reset_provider_events()
    monkeypatch.setattr(st, "_select_search_provider", lambda: "ddg")
    st.web_search_impl("q")
    assert st.provider_events() == {}


# ---------------------------------------------------------------- D.4 fetch class table

def test_fetch_class_table():
    for prefix in rg._INFRA_FETCH_REASON_PREFIXES:
        assert rg._fetch_reason_is_infra(prefix), prefix
        assert rg._fetch_reason_is_infra(prefix + "_detail"), prefix
    for reason in ("firecrawl_failed_http_503", "firecrawl_failed_readtimeout", "jina_primary_failed_timeouterror",
                   "research_negative_cache_suppressed", "research_inflight_timeout",
                   "request_to_jina_api_failed_connecterror", "jina_api_returned_status_503_upstream",
                   "fetch_call_deadline_exceeded",
                   # Every Firecrawl exception ("Error: Firecrawl failed: <class name>").
                   "firecrawl_failed_connecterror", "firecrawl_failed_jsondecodeerror",
                   "firecrawl_failed_remoteprotocolerror"):
        assert rg._fetch_reason_is_infra(reason), reason
    for reason in ("too_short", "blocked_page", "empty_extraction", "unavailable_page", "bot_wall", "paywalled",
                   "firecrawl_returned_no_page_text", "direct_fallback_http_404", "direct_fallback_http_403",
                   "firecrawl_failed_http_404", "firecrawl_failed_http_403", "firecrawl_failed_http_410",
                   "jina_api_returned_status_422_blocked", "exa_fallback_returned_no_results",
                   "source_quality_rejected", "invalid_url", "empty"):
        assert not rg._fetch_reason_is_infra(reason), reason
    # cached_fetch keeps a copy of the table (neither module imports the other).
    assert cf._INFRA_FETCH_REASON_PREFIXES == rg._INFRA_FETCH_REASON_PREFIXES
    assert cf._TRANSIENT_FETCH_REASON_RE.pattern == rg._TRANSIENT_FETCH_REASON_RE.pattern
    assert cf._FIRECRAWL_FAILED_PREFIX == rg._FIRECRAWL_FAILED_PREFIX


# Fetch texts as the providers / research_budget produce them.
_FETCH_TEXTS = (
    "Error: Firecrawl failed: payment required / quota exhausted",
    "Error: Firecrawl failed: HTTP 401",
    "Error: Firecrawl failed: HTTP 503",
    "Error: Firecrawl failed: HTTP 404",
    "Error: Firecrawl failed: rate limited (429 timeout)",
    "Error: Firecrawl failed: ConnectError",
    "Error: Firecrawl returned no page text",
    "Error: Firecrawl unavailable (FIRECRAWL_API_KEY is not configured)",
    "Error: Jina primary failed: TimeoutError: ",
    "Error: Request to Jina API failed: ConnectError: [Errno 61] Connection refused",
    "Error: Jina API returned status 503: upstream",
    "Error: Jina API returned status 422: blocked",
    "Error: Exa fallback failed: ReadError",
    "Error: Exa fallback returned no results",
    "Error: direct fallback HTTP 404",
    "Error: direct fallback failed: ConnectError: x",
    "Error: fetch returned empty_extraction",
    "Error: no web-fetch provider was available",
    "Error: fetch call deadline exceeded",
    json.dumps({"error": "research_budget_exhausted", "tool": "web_fetch", "results": []}),
    json.dumps({"error": "research_negative_cache_suppressed", "tool": "web_fetch"}),
    json.dumps({"status": "already_available", "artifact_id": "a1"}),
    "tiny page",
    "",
)


def test_cached_fetch_classes_agree_with_the_gateway():
    """cached_fetch's provider-attempt class is the class the tool layer gives the same text."""
    for text in _FETCH_TEXTS:
        reason = rg.ResearchTools._failure_reason(text, rg._json_object(text))
        assert reason is not None, text
        expected = "unavailable" if rg._fetch_reason_is_infra(reason) else "content"
        assert cf._fetch_failure_class(text) == expected, (text, reason)
    # A short page that merely mentions a timeout is the page's failure, not a transport one.
    assert cf._fetch_failure_class("The request timed out, please reload.") == "content"


def test_fetch_call_deadline_is_infra_and_not_retried(tmp_path):
    backend = _Recorder(rg.FETCH_DEADLINE_ERROR)
    tools = _tools(tmp_path, fetch_fn=backend)
    url = "https://www.agency.org/report"
    first = tools.fetch(url, agent_id="K1")
    assert first.startswith("FETCH_UNAVAILABLE(fetch_call_deadline_exceeded): ")
    second = tools.fetch(url, agent_id="K1")
    assert len(backend.calls) == 1 and "already failed in this run" in second
    assert second.startswith("FETCH_UNAVAILABLE(fetch_call_deadline_exceeded): ")


# ---------------------------------------------------------------- D.5 fetch sentinels

def test_fetch_sentinels(tmp_path):
    infra = _Recorder("Error: Firecrawl failed: HTTP 503")
    tools = _tools(tmp_path / "infra", fetch_fn=infra)
    url = "https://www.agency.org/report"
    first = tools.fetch(url, agent_id="K1")
    assert first == ("FETCH_UNAVAILABLE(firecrawl_failed_http_503): the page-reading service failed, not this "
                     "page; work from the sources you have (snippet claims stay REPORTED).")
    assert "not this page" in first
    tools.fetch(url, agent_id="K1")                    # retried once
    third = tools.fetch(url, agent_id="K1")            # then answered from run memory
    assert len(infra.calls) == 2
    assert third.startswith("FETCH_UNAVAILABLE(firecrawl_failed_http_503): this URL already failed in this run")
    assert tools.outcome_counts()["fetch_unavailable"] == 2

    # An empty provider chain used to be remembered permanently; it is an outage now.
    chain = _Recorder("Error: no web-fetch provider was available")
    tools = _tools(tmp_path / "chain", fetch_fn=chain)
    tools.fetch(url, agent_id="K1")
    tools.fetch(url, agent_id="K1")
    assert len(chain.calls) == 2

    content = _Recorder("Error: direct fallback HTTP 404")
    tools = _tools(tmp_path / "content", fetch_fn=content)
    failed = tools.fetch(url, agent_id="K1")
    assert failed == ("FETCH_FAILED(direct_fallback_http_404): page unread; claims from its snippet stay "
                      "REPORTED; try another source.")
    again = tools.fetch(url, agent_id="K1")
    assert len(content.calls) == 1 and "REPORTED" in again and again.startswith("FETCH_FAILED(")
    assert tools.outcome_counts()["fetch_content"] == 1

    raised = _Recorder(ConnectionError("jina: connection refused"))
    tools = _tools(tmp_path / "raised", fetch_fn=raised)
    assert tools.fetch(url, agent_id="K1").startswith("FETCH_UNAVAILABLE(ConnectionError): ")

    # A URL the ledger rejects never reaches the service: a content failure.
    assert tools.fetch("ftp://s3.org/p", agent_id="K1") == (
        "FETCH_FAILED(invalid_url): page unread; claims from its snippet stay REPORTED; try another source.")
    assert tools.outcome_counts()["fetch_content"] == 1

    for text in (first, third, failed, again):
        assert not text.startswith("[S")
        assert lr.tool_output_sids("web_fetch", text) == (None, [])


def test_fetch_sentinels_flag_off_keep_legacy_text(tmp_path):
    url = "https://www.agency.org/report"
    for error, reason, calls in (("Error: Firecrawl failed: HTTP 503", "firecrawl_failed_http_503", 1),
                                 ("Error: no web-fetch provider was available",
                                  "no_web_fetch_provider_was_available", 1),
                                 ("Error: Jina primary failed: ReadTimeout: x", "jina_primary_failed_readtimeout_x",
                                  2)):
        backend = _Recorder(error)
        tools = _tools(tmp_path / reason, fetch_fn=backend, taxonomy=False)
        assert tools.fetch(url, agent_id="K1") == f"FETCH_FAILED({reason}): try another source."
        tools.fetch(url, agent_id="K1")
        assert len(backend.calls) == calls
        assert tools.fetch(url, agent_id="K1") == (f"FETCH_FAILED({reason}): this URL already failed in this "
                                                   "run; try another source.")


def test_fetch_budget_is_its_own_class(tmp_path):
    envelope = json.dumps({"error": "research_budget_exhausted", "tool": "web_fetch", "results": []})
    tools = _tools(tmp_path, fetch_fn=_Recorder(envelope))
    assert tools.fetch("https://www.agency.org/a", agent_id="K1") == rg.MSG_FETCH_BUDGET
    tools = _tools(tmp_path / "local", limits=rg.ToolLimits(max_fetches_total=0))
    assert tools.fetch("https://www.agency.org/a", agent_id="K1") == rg.MSG_FETCH_BUDGET
    assert tools.outcome_counts()["fetch_budget"] == 1


# ---------------------------------------------------------------- E counting fix / evidence detail

def _run(tmp_path, bridge, *, search=None, fetch=None, depth="standard"):
    """One scripted v3 run with injected search/fetch backends; (rc, meta)."""
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    model = v3.ScriptedModel(v3.World())
    meta = {"status": "running", "question": QUESTION, "research_engine": "v3"}

    def write_meta():
        (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    def gateway_factory(args, plog_arg, bridge_arg, preset):
        return rg.ModelGateway(model, plog_arg, max_concurrency=preset.workers, budget_units=preset.budget_units,
                               reserve_share=lr.RESERVE_SHARE, sleep=lambda seconds: None)

    def tools_factory(ledger, pages_dir, bridge_arg, plog_arg, limits):
        return rg.ResearchTools(ledger, pages_dir, search_fn=search or v3.fake_search,
                                fetch_fn=fetch or v3.page_text, bridge=bridge_arg, plog=plog_arg, limits=limits)

    rc = lr.run(meta["question"], out_dir, v3.make_args(depth), meta, v3.FakePlog(), write_meta, bridge=bridge,
                gateway_factory=gateway_factory, tools_factory=tools_factory)
    return rc, meta


def _events(meta):
    return list((meta.get("research_quality") or {}).get("degradation") or [])


def _budget_on_outlook(query, n):
    """Agent follow-up searches hit the research budget; every other search works."""
    return BUDGET_ENVELOPE if "market outlook" in query else v3.fake_search(query, n)


def test_counting_fix(tmp_path, bridge, monkeypatch):
    fetched: list = []

    def fetch(url):
        fetched.append(url)
        return v3.page_text(url)

    # Flag off: the budget envelopes are booked as page-fetch failures (the bug).
    rc, meta = _run(tmp_path / "off", bridge, search=_budget_on_outlook, fetch=fetch)
    assert rc == 0, meta.get("error")
    assert fetched and any("page fetches failed" in e for e in _events(meta))
    assert "source_health" not in meta

    _taxonomy(monkeypatch, True)
    fetched.clear()
    rc, meta = _run(tmp_path / "on", bridge, search=_budget_on_outlook, fetch=fetch)
    assert rc == 0, meta.get("error")
    counts = meta["source_health"]["tools"]
    assert fetched and counts["fetch_ok"] == len(fetched) > 0
    assert counts["fetch_content"] + counts["fetch_unavailable"] == 0      # fetch_failed == 0
    assert counts["search_budget"] > 0
    assert not any("page fetches failed" in e or "searches failed" in e for e in _events(meta))
    assert meta["source_health"]["version"] == 1 and meta["source_health"]["search_refused"] is None


def test_counting_fix_flag_off_keeps_partial_failure_events(tmp_path, bridge):
    """test_research_engine_v3_round3_robust::test_r3_partial_tool_failures_are_degradation_events, flag off."""
    import test_research_engine_v3_round3_robust as r3

    rc, meta, _, _, _ = r3.run(tmp_path, bridge, v3.World(), depth="quick", search=r3._flaky(2),
                               fetch=r3._fetch_down)
    assert rc == 0, meta.get("error")
    searches, fetches = meta["tools"]["searches"], meta["tools"]["fetches"]
    assert any(e.endswith(f"of {searches} searches failed") for e in _events(meta))
    assert f"{fetches} of {fetches} page fetches failed" in _events(meta)


def test_evidence_unavailable_detail(tmp_path, bridge, monkeypatch):
    _taxonomy(monkeypatch, True)
    rc, meta = _run(tmp_path, bridge, search=_Recorder(REFUSAL_402),
                    fetch=_Recorder(ConnectionError("jina: connection refused")), depth="quick")
    assert rc == 2 and meta["status"] == "failed"
    assert meta["error"].startswith("evidence_unavailable: no sourced evidence after gathering (")
    assert "search provider refused: firecrawl http_402" in meta["error"]
    health = meta["source_health"]
    assert health["search_refused"] == {"provider": "firecrawl", "reason": "http_402"}
    assert health["tools"]["search_not_configured"] >= 1


def test_refusal_mid_run_is_a_degradation_event(tmp_path, bridge, monkeypatch):
    _taxonomy(monkeypatch, True)
    backend_calls: list = []

    def search(query, n):
        backend_calls.append(query)
        return REFUSAL_402 if "market outlook" in query else v3.fake_search(query, n)

    rc, meta = _run(tmp_path, bridge, search=search)
    assert rc == 0, meta.get("error")
    assert "search provider firecrawl refused this run (http_402); no further search was possible" in _events(meta)
    assert sum("market outlook" in q for q in backend_calls) == 1        # latched after the first refusal
    assert meta["source_health"]["search_refused"] == {"provider": "firecrawl", "reason": "http_402"}


def test_source_events_name_substitution_and_broken_fetch_primary(tmp_path, bridge, monkeypatch):
    _taxonomy(monkeypatch, True)
    st._record_provider_event("substitution:serper->ddg")
    st._record_provider_event("substitution:serper->ddg")
    cf._record_fetch_event("firecrawl", "not_configured", "http_402")
    cf._record_fetch_event("jina", "ok")
    rc, meta = _run(tmp_path, bridge)
    assert rc == 0, meta.get("error")
    events = _events(meta)
    assert "configured search provider serper unavailable; 2 searches served by ddg" in events
    assert ("fetch primary firecrawl failed 1 times (not_configured: http_402); fallback providers served the "
            "pages") in events
    assert meta["source_health"]["search_providers"] == {"substitution:serper->ddg": 2}
    assert meta["source_health"]["fetch_providers"]["firecrawl"]["not_configured"] == {
        "count": 1, "reason": "http_402"}


def test_unconfirmed_empty_event_in_a_run(tmp_path, bridge, monkeypatch):
    _taxonomy(monkeypatch, True)
    unconfirmed = json.dumps({"error": "No results found", "query": "q", "empty_unconfirmed": True,
                              "provider": "ddg"})

    def search(query, n):
        return unconfirmed if "market outlook" in query else v3.fake_search(query, n)

    rc, meta = _run(tmp_path, bridge, search=search)
    assert rc == 0, meta.get("error")
    counts = meta["source_health"]["tools"]
    assert counts["search_empty_unconfirmed"] > 0
    assert any("searches came back empty from a backend that may have failed" in e for e in _events(meta))


def test_source_health_events_thresholds_and_classes():
    base = {"searches": 10, "search_refused": None}
    assert lr._source_health_events({**base, "search_empty_unconfirmed": 2}, {}, {}) == [
        "2 of 10 searches came back empty from a backend that may have failed (not evidence of absence)"]
    assert lr._source_health_events({**base, "search_empty_unconfirmed": 1}, {}, {}) == []
    # A page's own failure (content) is not a broken primary; no fallback success, no event.
    content = {"firecrawl": {"content": {"count": 5, "reason": "firecrawl_failed_http_404"}},
               "jina": {"ok": {"count": 3, "reason": ""}}}
    assert lr._source_health_events(base, {}, content) == []
    unserved = {"firecrawl": {"unavailable": {"count": 2, "reason": "firecrawl_failed_http_503"}}}
    assert lr._source_health_events(base, {}, unserved) == []
    served = {"jina": {"unavailable": {"count": 2, "reason": "jina_primary_failed_timeouterror"},
                       "ok": {"count": 1, "reason": ""}},
              "exa": {"ok": {"count": 2, "reason": ""}}}
    assert lr._source_health_events(base, {"other": 3}, served) == [
        "fetch primary jina failed 2 times (unavailable: jina_primary_failed_timeouterror); fallback providers "
        "served the pages"]
    assert lr._source_health_events(base, {}, {"firecrawl": "junk", "jina": {"ok": "junk"}}) == []


def test_flag_off_engine_meta_has_no_source_health(tmp_path, bridge):
    rc, meta = _run(tmp_path, bridge)
    assert rc == 0 and "source_health" not in meta
    assert not any("fetch primary" in e or "configured search provider" in e for e in _events(meta))


# ---------------------------------------------------------------- B / C Firecrawl fetch quota disable

@pytest.fixture
def budget_db(monkeypatch, tmp_path):
    monkeypatch.setenv("RESEARCH_BUDGET_DB", str(tmp_path / "budget.sqlite3"))
    monkeypatch.setenv("RESEARCH_BUDGET_TELEMETRY_PATH", str(tmp_path / "research_budget.json"))
    monkeypatch.setenv("RESEARCH_BUDGET_LANE_ID", "lane-a")
    monkeypatch.setenv("RESEARCH_SOURCE_CACHE_DIR", str(tmp_path / "source_cache"))
    monkeypatch.setenv("RESEARCH_SOURCE_CACHE_TTL_H", "0")
    return tmp_path / "budget.sqlite3"


def _fetch_providers(monkeypatch, firecrawl_text):
    calls = {"firecrawl": 0, "jina": 0}

    async def firecrawl(url):
        calls["firecrawl"] += 1
        return firecrawl_text

    async def jina(url):
        calls["jina"] += 1
        return v3.page_text(url)

    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.setattr(cf, "_firecrawl_fetch", firecrawl)
    monkeypatch.setattr(cf, "_jina_delegate_fetch", jina)
    return calls


def test_quota_disable(monkeypatch, budget_db, caplog):
    _taxonomy(monkeypatch, True)
    calls = _fetch_providers(monkeypatch, "Error: Firecrawl failed: payment required / quota exhausted")
    url = "https://www.agency.org/report"
    with caplog.at_level(logging.ERROR, logger=cf.logger.name):
        assert asyncio.run(cf._resilient_fetch(url)) == v3.page_text(url)
        events = cf.provider_events()
        assert events["firecrawl"] == {"not_configured": {"count": 1, "reason": "http_402"}}
        assert events["jina"]["ok"]["count"] == 1
        assert cf._DISABLED_FETCH_PROVIDERS == {"firecrawl": "http_402"}
        assert asyncio.run(cf._resilient_fetch(url + "/2")) == v3.page_text(url + "/2")
    assert calls == {"firecrawl": 1, "jina": 2}
    assert len([r for r in caplog.records if r.levelno >= logging.ERROR]) == 1
    assert rb.provider_circuit_open("firecrawl") is True
    telemetry = rb.export_telemetry(force=True)
    assert telemetry["global"]["provider_firecrawl_not_configured"] == 1
    assert telemetry["lanes"]["lane-a"]["provider_firecrawl_not_configured"] == 1
    assert telemetry["provider_health"]["firecrawl"]["circuit_open"] is True
    assert telemetry["provider_health"]["firecrawl"]["total_transport_failures"] == 0


def test_quota_disable_flag_off_keeps_asking_firecrawl(monkeypatch, budget_db):
    calls = _fetch_providers(monkeypatch, "Error: Firecrawl failed: payment required / quota exhausted")
    url = "https://www.agency.org/report"
    asyncio.run(cf._resilient_fetch(url))
    asyncio.run(cf._resilient_fetch(url + "/2"))
    assert calls == {"firecrawl": 2, "jina": 2}
    assert cf.provider_events() == {} and cf._DISABLED_FETCH_PROVIDERS == {}
    assert rb.provider_circuit_open("firecrawl") is False


def test_http_401_disables_and_other_failures_are_classified(monkeypatch, budget_db):
    _taxonomy(monkeypatch, True)
    calls = _fetch_providers(monkeypatch, "Error: Firecrawl failed: HTTP 401")
    asyncio.run(cf._resilient_fetch("https://www.agency.org/a"))
    assert cf._DISABLED_FETCH_PROVIDERS == {"firecrawl": "http_401"}
    assert rb.provider_circuit_open("firecrawl") is True
    # Without the shared ledger (its circuit is open now), a 5xx is an outage
    # but never a disable: Firecrawl is asked again.
    monkeypatch.delenv("RESEARCH_BUDGET_DB")
    cf.reset_provider_events()
    calls = _fetch_providers(monkeypatch, "Error: Firecrawl failed: HTTP 503")
    asyncio.run(cf._resilient_fetch("https://www.agency.org/b"))
    asyncio.run(cf._resilient_fetch("https://www.agency.org/c"))
    assert calls["firecrawl"] == 2 and cf._DISABLED_FETCH_PROVIDERS == {}
    assert cf.provider_events()["firecrawl"] == {"unavailable": {"count": 2, "reason": "firecrawl_failed_http_503"}}
    assert cf._fetch_failure_class("Error: Firecrawl failed: HTTP 404") == "content"
    assert cf._fetch_failure_class("Error: Request to Jina API failed: ConnectError: x") == "unavailable"
    assert cf._fetch_failure_class("tiny page") == "content"


def test_record_provider_quota_failure_never_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("RESEARCH_BUDGET_DB", raising=False)
    assert rb.record_provider_quota_failure("firecrawl", "HTTP 402") is None
    monkeypatch.setenv("RESEARCH_BUDGET_DB", str(tmp_path))                 # a directory: sqlite fails
    assert rb.record_provider_quota_failure("firecrawl", "HTTP 402") is None


def _negative_keys(db: Path) -> int:
    with sqlite3.connect(db) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM negative_results WHERE kind='fetch'").fetchone()[0])


def _cached_fetch(url, text):
    async def fetch_fn(_url):
        return text
    return asyncio.run(cf.cached_fetch(url, fetch_fn))


def test_outages_are_not_negative_cached(monkeypatch, budget_db):
    _taxonomy(monkeypatch, True)
    for i, outage in enumerate(("Error: Jina primary failed: ConnectTimeout: x",
                                "Error: Firecrawl failed: payment required / quota exhausted",
                                "Error: Firecrawl failed: HTTP 401",
                                "Error: Exa fallback unavailable (EXA_API_KEY is not configured)",
                                "Error: no web-fetch provider was available",
                                "Error: Jina API returned status 503: upstream",
                                "Error: Firecrawl failed: ConnectError",
                                json.dumps({"error": "research_budget_exhausted", "tool": "web_fetch",
                                            "results": []}))):
        assert _cached_fetch(f"https://www.agency.org/outage-{i}", outage) == outage
    assert _negative_keys(budget_db) == 0
    for i, gone in enumerate(("Error: direct fallback HTTP 404", "Error: Jina API returned status 422: blocked",
                              "Error: fetch returned empty_extraction")):
        _cached_fetch(f"https://www.agency.org/gone-{i}", gone)
    assert _negative_keys(budget_db) == 3


def test_outages_are_negative_cached_with_the_flag_off(monkeypatch, budget_db):
    _cached_fetch("https://www.agency.org/outage", "Error: Jina primary failed: ConnectTimeout: x")
    assert _negative_keys(budget_db) == 1


# ---------------------------------------------------------------- knob forwarding

@pytest.mark.parametrize("config_value, ambient, expected", [
    (True, "false", "true"),
    (False, "true", "false"),
])
@pytest.mark.parametrize("engine", ["v3", "legacy"])
def test_research_child_env_forwards_source_taxonomy(monkeypatch, tmp_path, config_value, ambient, expected,
                                                     engine):
    from app.services import pipeline_orchestrator as po

    monkeypatch.setattr(po.Config, "RESEARCH_ENGINE", engine, raising=False)
    monkeypatch.setattr(po.Config, "RESEARCH_SOURCE_TAXONOMY", config_value)
    monkeypatch.setenv("RESEARCH_SOURCE_TAXONOMY", ambient)
    child = _launch_capturing_child(monkeypatch, tmp_path, timeout=900)
    assert child["env"]["RESEARCH_SOURCE_TAXONOMY"] == expected
