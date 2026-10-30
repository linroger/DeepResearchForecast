"""Actual default tools retain bounded provider metadata only in approved v2 mode."""
from contextlib import contextmanager
import hashlib
import json

import httpx
import pytest

from deerflow_bridge import research_gateway as rg, target_research as target
from test_run_spending_child_transports import KEY, isolated as _isolated, run_authority
from test_world_anchor_spending import make_authority, sp
import cached_fetch as cf
import search_tools as st

isolated = _isolated
URL = "https://www.energy.gov/capacity"
BODY = "Capacity Agency reports installed capacity of 176 GW. " * 8
METADATA = {"publication_type": "government_report", "source_type": "official_statistics", "published_at": "2026-10-26",
            "origin_cluster": "capacity-agency"}


@contextmanager
def authority(tmp_path, monkeypatch):
    manifest, path, registry, request = make_authority(tmp_path / "authority")
    for route in manifest["routes"].values():
        route["account_sha256"] = hashlib.sha256(KEY.encode()).hexdigest()
    manifest["routes"]["search"]["max_tool_units"] = 5
    manifest["routes_sha256"] = sp.hash_payload(manifest["routes"])
    path.write_text(json.dumps(manifest))
    monkeypatch.setenv("FIRECRAWL_SEARCH_API_URL", manifest["routes"]["search"]["endpoint"])
    monkeypatch.setenv("FIRECRAWL_API_URL", manifest["routes"]["scrape"]["endpoint"])
    binding = sp.create_authorization(path, registry_dir=registry)
    with sp.run_lock(binding):
        binding = sp.bind_pipeline(binding, "metadata-pipeline", request)
        sp.activate_binding(binding)
        with sp.operation("research", "metadata-tool-proof"):
            yield binding


def http_fixture(monkeypatch, metadata, fetch_metadata=None):
    sends = []
    def handle(request):
        sends.append(request)
        if request.url.path.endswith("search"):
            return httpx.Response(200, json={"creditsUsed": 1, "data": {"web": [{"url": URL, "title": "Capacity report",
                "description": "Installed capacity", "metadata": metadata}]}})
        return httpx.Response(200, json={"creditsUsed": 1, "data": {"markdown": BODY,
            "metadata": metadata if fetch_metadata is None else fetch_metadata}})
    monkeypatch.setattr(httpx, "HTTPTransport", lambda **kwargs: httpx.MockTransport(handle))
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(handle))
    client, async_client = httpx.Client, httpx.AsyncClient
    def sync_factory(**kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handle))
        return client(**kwargs)
    def async_factory(**kwargs):
        kwargs.setdefault("transport", httpx.MockTransport(handle))
        return async_client(**kwargs)
    monkeypatch.setattr(httpx, "Client", sync_factory)
    monkeypatch.setattr(httpx, "AsyncClient", async_factory)
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(key, raising=False)
    return sends


@pytest.mark.parametrize("metadata,expected", [(METADATA, "primary"), ({}, "unknown"),
    ({"publication_type": {"bad": "government_report"}, "source_type": "unqualified", "published_at": "not-a-date"}, "unknown")])
def test_default_v2_http_cache_reload_ledger_and_target_source(tmp_path, monkeypatch, metadata, expected):
    with authority(tmp_path, monkeypatch) as binding:
        sends = http_fixture(monkeypatch, metadata)
        ledger = rg.SourceLedger(tmp_path / "first/ledger.json", capture_evidence=True)
        tools = rg.ResearchTools(ledger, tmp_path / "first/pages")
        assert tools._search_fn is rg._default_search_fn and tools._fetch_fn is rg._default_fetch_fn
        tools.search("capacity report", agent_id="K1")
        tools.fetch(URL, agent_id="K1")
        ledger.flush()
        first = target.source_rows(ledger.rows())[0]
        assert first["tier"] == expected and first["fetched"] is True
        assert target._supported({"sourceIds": [first["sourceId"]], "passage": BODY.strip()},
            {first["sourceId"]: first}, pivotal=True) is (expected == "primary")
        assert len(sends) == 2 and sp.summary(binding)["attempt_count"] == 2
        # A new tool instance and ledger exercise disk caches, not local memoization.
        second = rg.SourceLedger(tmp_path / "second/ledger.json", capture_evidence=True)
        restored = rg.ResearchTools(second, tmp_path / "second/pages")
        restored.search("capacity report", agent_id="K1")
        restored.fetch(URL, agent_id="K1")
        second.flush()
        reloaded = rg.SourceLedger(tmp_path / "second/ledger.json", capture_evidence=True)
        row = target.source_rows(reloaded.rows())[0]
        assert row["tier"] == expected and row["publishedAt"] == ("2026-10-26" if expected == "primary" else None)
        assert row["passage"] == first["passage"]
        assert len(sends) == 2 and sp.summary(binding)["attempt_count"] == 2
        assert cf._RETAIN_SOURCE_METADATA.get() is False


def test_explicit_false_keeps_v2_legacy_wire_result_and_cache_shape(tmp_path, monkeypatch):
    with authority(tmp_path, monkeypatch) as binding:
        sends = http_fixture(monkeypatch, METADATA)
        search = st.web_search_impl("capacity report", 1, retain_source_metadata=False)
        fetched = rg._run_coroutine_blocking(lambda: cf.cached_fetch(URL, cf._resilient_fetch, retain_source_metadata=False))
        assert set(json.loads(search)["results"][0]) == {"title", "url", "content"}
        assert fetched == BODY.strip() and not fetched.startswith("{")
        assert st.web_search_impl("capacity report", 1, retain_source_metadata=False) == search
        assert rg._run_coroutine_blocking(lambda: cf.cached_fetch(URL, cf._resilient_fetch, retain_source_metadata=False)) == fetched
        assert len(sends) == 2 and sp.summary(binding)["attempt_count"] == 2


def test_v1_defaults_remain_plain_and_metadata_opt_in_denies(tmp_path, monkeypatch):
    with run_authority(tmp_path, monkeypatch) as binding:
        sends = http_fixture(monkeypatch, METADATA)
        search = st.web_search_impl("capacity report", 1)
        fetched = rg._run_coroutine_blocking(lambda: cf.cached_fetch(URL, cf._resilient_fetch))
        assert set(json.loads(search)["results"][0]) == {"title", "url", "content"}
        assert fetched == BODY.strip()
        assert len(sends) == 2 and sp.summary(binding)["attempt_count"] == 2
        with pytest.raises(sp.SpendingStop, match="unsupported_route"):
            st.web_search_impl("another report", 1, retain_source_metadata=True)
        assert len(sends) == 2


def test_unbound_defaults_do_not_select_metadata_from_environment(tmp_path, monkeypatch):
    sends = http_fixture(monkeypatch, METADATA)
    for key in ("SERPER_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("WORLD_ANCHOR_ENABLED", "1")
    result = st.web_search_impl("capacity report", 1)
    fetched = rg._run_coroutine_blocking(lambda: cf.cached_fetch(URL, cf._resilient_fetch))
    assert "results" in json.loads(result), result
    assert set(json.loads(result)["results"][0]) == {"title", "url", "content"}
    assert fetched == BODY.strip() and len(sends) == 2


def test_invalid_context_never_uses_schema_label_to_enable_or_dispatch(tmp_path, monkeypatch):
    with authority(tmp_path, monkeypatch) as binding:
        sends = http_fixture(monkeypatch, METADATA)
        forged = dict(binding, admission_epoch=binding["admission_epoch"] + 1)
        token = sp._binding.set(forged)
        try:
            with pytest.raises(sp.SpendingStop):
                st.web_search_impl("capacity report", 1)
        finally:
            sp._binding.reset(token)
        assert not sends


@pytest.mark.parametrize("classification,date_field", [("publication_type", "published_at"), ("source_type", "published_date"),
    ("@type", "publishedDate"), ("kind", "publication_date"), ("source_type", "publishedAt"),
    ("source_type", "datePublished"), ("source_type", "published"), ("source_type", "date")])
def test_raw_metadata_aliases_reach_same_provenance(tmp_path, monkeypatch, classification, date_field):
    with authority(tmp_path, monkeypatch):
        http_fixture(monkeypatch, {classification: "government_report", date_field: "2026-10-26"})
        ledger = rg.SourceLedger(tmp_path / "ledger.json", capture_evidence=True)
        tools = rg.ResearchTools(ledger, tmp_path / "pages")
        tools.search("capacity report", agent_id="K1")
        tools.fetch(URL, agent_id="K1")
        row = target.source_rows(ledger.rows())[0]
        assert row["tier"] == "primary" and row["publishedAt"] == "2026-10-26"
        receipts = ledger.rows()[0]["source_metadata_receipts"]
        assert {r["source_metadata_origin"] for r in receipts} == {"firecrawl_search", "firecrawl_scrape"}
        assert all(r[classification] == "government_report" and r[date_field] == "2026-10-26" for r in receipts)


@pytest.mark.parametrize("search_type,fetch_type", [("government_report", "news_article"), ("news_article", "government_report")])
def test_conflicting_classification_cannot_admit_primary_actor_support(tmp_path, monkeypatch, search_type, fetch_type):
    with authority(tmp_path, monkeypatch):
        http_fixture(monkeypatch, {"publication_type":search_type}, {"publication_type":fetch_type})
        ledger = rg.SourceLedger(tmp_path / "ledger.json", capture_evidence=True)
        tools = rg.ResearchTools(ledger, tmp_path / "pages")
        tools.search("capacity report", agent_id="K1")
        tools.fetch(URL, agent_id="K1")
        ledger.flush()
        raw = ledger.rows()[0]
        assert raw["source_metadata_status"] == "conflict" and raw["evidence_tier"] == "unknown"
        assert {r["publication_type"] for r in raw["source_metadata_receipts"]} == {search_type, fetch_type}
        reloaded = rg.SourceLedger(tmp_path / "ledger.json", capture_evidence=True)
        source = target.source_rows(reloaded.rows())[0]
        assert source["tier"] == "unknown"
        assert not target._supported({"sourceIds":[source["sourceId"]],"passage":BODY.strip()}, {source["sourceId"]:source}, pivotal=True)
        reloaded.register(URL, metadata={"source_metadata_version":"world-anchor-source-metadata/v1", "publication_type":"government_report"})
        assert reloaded.rows()[0]["evidence_tier"] == "unknown"
        detached = reloaded.rows()[0]
        detached["source_metadata_receipts"][0]["publication_type"] = "tampered"
        assert reloaded.rows()[0]["source_metadata_receipts"][0]["publication_type"] != "tampered"


def test_enabled_fetch_coordination_keys_separate_plain_and_metadata_cache(tmp_path, monkeypatch):
    import research_budget as rb
    from test_loop007_research_budget import _set_budget_env
    _set_budget_env(monkeypatch, tmp_path)
    monkeypatch.setenv("RESEARCH_BUDGET_ENABLED", "true")
    monkeypatch.setenv("RESEARCH_COMPACT_REPEAT_RESULTS", "true")
    with authority(tmp_path, monkeypatch):
        sends = http_fixture(monkeypatch, METADATA)
        def fetch(retain, reason=""):
            return rg._run_coroutine_blocking(lambda: cf.cached_fetch(URL, cf._resilient_fetch, reason,
                                                                      retain_source_metadata=retain))
        plain = fetch(False, "populate")
        marked = fetch(True, "populate")
        assert plain == BODY.strip() and json.loads(marked)["markdown"] == BODY.strip()
        # Clear lane sightings to exercise first reads from already populated disk caches.
        from contextlib import closing
        with closing(rb._connect()) as db:
            db.execute("DELETE FROM positive_results")
        assert fetch(False) == plain
        assert json.loads(fetch(True))["metadata"]["publication_type"] == "government_report"
        assert len(sends) == 2
        assert json.loads(fetch(False))["status"] == "already_available"
        assert json.loads(fetch(True))["status"] == "already_available"
        assert len(sends) == 2


def test_concurrent_plain_and_metadata_fetches_have_separate_claims(tmp_path, monkeypatch):
    import asyncio
    from test_loop007_research_budget import _set_budget_env
    _set_budget_env(monkeypatch, tmp_path)
    monkeypatch.setenv("RESEARCH_COMPACT_REPEAT_RESULTS", "true")
    with authority(tmp_path, monkeypatch) as binding:
        async def execute():
            arrived = []
            both = asyncio.Event()
            async def handle(request):
                arrived.append(cf._RETAIN_SOURCE_METADATA.get())
                if len(arrived) == 2:
                    both.set()
                await asyncio.wait_for(both.wait(), 3)
                return httpx.Response(200, json={"creditsUsed":1,"data":{"markdown":BODY,"metadata":METADATA}})
            monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(handle))
            plain, marked = await asyncio.gather(
                cf.cached_fetch(URL, cf._resilient_fetch, retain_source_metadata=False),
                cf.cached_fetch(URL, cf._resilient_fetch, retain_source_metadata=True))
            assert plain == BODY.strip() and json.loads(marked)["metadata"]["publication_type"] == "government_report"
            assert sorted(arrived) == [False, True]
            assert cf._RETAIN_SOURCE_METADATA.get() is False
        asyncio.run(execute())
        assert sp.summary(binding)["attempt_count"] == 2


def test_unmarked_enabled_caches_are_reacquired_without_primary_promotion(tmp_path, monkeypatch):
    from pathlib import Path
    with authority(tmp_path, monkeypatch) as binding:
        sends = http_fixture(monkeypatch, {})
        query = "capacity report"
        provider = "firecrawl|source-metadata-v1"
        search_path = st._search_cache_path(st._search_cache_root(), st._search_cache_key(provider, query, rg.SEARCH_RESULTS_PER_QUERY))
        st._write_search_cache(search_path, provider, query, json.dumps({"results":[{"url":URL,"title":"Old search",
            "content":"Old primary declaration", "metadata":{"publication_type":"government_report"}}]}))
        fetch_path = cf._cache_path(str(Path(cf._cache_root()) / "source-metadata-v1"), URL)
        cf._write_cache(fetch_path, URL, json.dumps({"markdown":BODY,"metadata":{"publication_type":"news_article"}}))
        ledger = rg.SourceLedger(tmp_path / "ledger.json", capture_evidence=True)
        tools = rg.ResearchTools(ledger, tmp_path / "pages")
        tools.search(query, agent_id="K1")
        tools.fetch(URL, agent_id="K1")
        source = target.source_rows(ledger.rows())[0]
        assert source["tier"] == "unknown" and len(sends) == 2
        assert sp.summary(binding)["attempt_count"] == 2
        assert all(r["source_metadata_version"] == "world-anchor-source-metadata/v1" for r in ledger.rows()[0]["source_metadata_receipts"])
        assert not target._supported({"sourceIds":[source["sourceId"]],"passage":BODY.strip()}, {source["sourceId"]:source}, pivotal=True)


def test_enabled_singleflight_follower_never_accepts_unmarked_cached_body(tmp_path, monkeypatch):
    import asyncio
    from pathlib import Path
    from test_loop007_research_budget import _set_budget_env
    _set_budget_env(monkeypatch, tmp_path)
    with authority(tmp_path, monkeypatch) as binding:
        cf._write_cache(cf._cache_path(str(Path(cf._cache_root()) / "source-metadata-v1"), URL), URL,
                        json.dumps({"markdown":BODY,"metadata":{"publication_type":"government_report"}}))
        sends = []
        async def handle(request):
            sends.append(request)
            await asyncio.sleep(.15)
            return httpx.Response(200,json={"creditsUsed":1,"data":{"markdown":BODY,"metadata":{"publication_type":"news_article"}}})
        monkeypatch.setattr(httpx,"AsyncHTTPTransport",lambda **kwargs:httpx.MockTransport(handle))
        async def execute():
            return await asyncio.gather(cf.cached_fetch(URL,cf._resilient_fetch),cf.cached_fetch(URL,cf._resilient_fetch))
        replies = asyncio.run(execute())
        assert all(json.loads(reply)["metadata"]["publication_type"] == "news_article" for reply in replies)
        assert len(sends) == sp.summary(binding)["attempt_count"] == 1
