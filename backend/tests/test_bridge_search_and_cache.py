"""deerflow_bridge 的 search_tools（ITEM 6 后端调度）+ cached_fetch（ITEM 10 源缓存）离线单测。

与 test_bridge_prediction_markets.py 同构：桥模块模块级只 import 标准库（deerflow / langchain
相关 import 都在函数体内或 try/except 兜底），故可从 backend 测试里直接 import 做纯逻辑测试——
只需把 deerflow_bridge 目录挂到 sys.path。全部纯函数 / 注入式 fetch，零网络、零 LLM、零 deerflow。
"""

import asyncio
import json
import os
import sys
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BRIDGE_DIR = os.path.join(_REPO_ROOT, "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import cached_fetch as cf  # noqa: E402
import search_tools as st  # noqa: E402


# ================================================================ ITEM 6 —— 后端调度（monkeypatch env）

def test_select_provider_serper_when_key_set(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "sk-serper-xyz")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert st._select_search_provider() == "serper"


def test_select_provider_tavily_when_only_tavily_set(monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-abc")
    assert st._select_search_provider() == "tavily"


def test_select_provider_serper_beats_tavily_when_both_set(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "sk-serper")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly")
    assert st._select_search_provider() == "serper"


def test_select_provider_ddg_default_zero_keys(monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    assert st._select_search_provider() == "ddg"


def test_select_provider_blank_key_is_not_configured(monkeypatch):
    """空串 / 纯空白 key 视作未配（strip 后非空才算已配）。"""
    monkeypatch.setenv("SERPER_API_KEY", "   ")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    monkeypatch.setenv("FIRECRAWL_API_KEY", "")
    assert st._select_search_provider() == "ddg"


def test_web_search_impl_degrades_when_no_backend(monkeypatch):
    """无 deerflow → 所有 provider 模块导入失败 → 返回带说明的空结果 JSON（绝不抛）。"""
    monkeypatch.setenv("SERPER_API_KEY", "sk-serper")
    monkeypatch.setattr(st, "_load_search_module", lambda provider: None)
    out = st.web_search_impl("some query", max_results=10)
    obj = json.loads(out)
    assert obj["query"] == "some query"
    assert "error" in obj


def test_web_search_impl_falls_back_to_ddg(monkeypatch):
    """被选后端（serper）不可用 → 回退 DDG，并把调用委派给 DDG 的工具函数。"""
    monkeypatch.setenv("SERPER_API_KEY", "sk-serper")

    class _FakeTool:
        # 模拟 langchain StructuredTool：原函数在 .func 上，签名含 max_results
        @staticmethod
        def func(query, max_results=5):
            return json.dumps({"backend": "ddg", "query": query, "max_results": max_results})

    def _fake_load(provider):
        return type("M", (), {"web_search_tool": _FakeTool})() if provider == "ddg" else None

    monkeypatch.setattr(st, "_load_search_module", _fake_load)
    out = json.loads(st.web_search_impl("q", max_results=10))
    assert out["backend"] == "ddg"
    assert out["max_results"] == 10  # max_results 因签名含该形参而被透传


def test_web_search_impl_query_only_delegate(monkeypatch):
    """委派工具签名只有 query（如 tavily）→ 只传 query，不因多余 max_results 而 TypeError。"""
    monkeypatch.setenv("TAVILY_API_KEY", "tvly")
    monkeypatch.delenv("SERPER_API_KEY", raising=False)

    class _FakeTool:
        @staticmethod
        def func(query):  # 无 max_results 形参
            return json.dumps({"backend": "tavily", "query": query})

    monkeypatch.setattr(st, "_load_search_module",
                        lambda provider: type("M", (), {"web_search_tool": _FakeTool})())
    out = json.loads(st.web_search_impl("hello", max_results=10))
    assert out == {"backend": "tavily", "query": "hello"}


def test_search_filters_denied_domains_before_context_and_cache(monkeypatch, tmp_path):
    monkeypatch.delenv("RESEARCH_ALLOW_LOW_QUALITY_SOURCES", raising=False)
    monkeypatch.delenv("RESEARCH_SOURCE_DENY_DOMAINS", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("RESEARCH_SEARCH_CACHE_TTL_H", "6")
    monkeypatch.setenv("RESEARCH_SEARCH_CACHE_DIR", str(tmp_path / "search-cache"))
    calls = {"delegate": 0}

    class _FakeTool:
        @staticmethod
        def func(query, max_results=10):
            calls["delegate"] += 1
            return json.dumps({"results": [
                {"title": "AI summary", "url": "https://economicsummarizer.com/x"},
                {"title": "Primary filing", "url": "https://sec.gov/filing"},
            ]})

    monkeypatch.setattr(
        st, "_load_search_module",
        lambda _provider: type("M", (), {"web_search_tool": _FakeTool})(),
    )
    result = json.loads(st.web_search_impl("semiconductor filing", 10))

    assert calls["delegate"] == 1
    assert [row["url"] for row in result["results"]] == ["https://sec.gov/filing"]
    cache_path = st._search_cache_path(
        st._search_cache_root(),
        st._search_cache_key("ddg", "semiconductor filing", 10),
    )
    cached = json.loads(st._read_search_cache(cache_path, 6 * 3600))
    assert [row["url"] for row in cached["results"]] == ["https://sec.gov/filing"]


def test_old_all_denied_search_cache_is_a_miss(monkeypatch, tmp_path):
    monkeypatch.delenv("RESEARCH_ALLOW_LOW_QUALITY_SOURCES", raising=False)
    monkeypatch.delenv("RESEARCH_SOURCE_DENY_DOMAINS", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("RESEARCH_SEARCH_CACHE_TTL_H", "6")
    monkeypatch.setenv("RESEARCH_SEARCH_CACHE_DIR", str(tmp_path / "search-cache"))
    query = "replacement evidence"
    cache_path = st._search_cache_path(
        st._search_cache_root(), st._search_cache_key("ddg", query, 10))
    st._write_search_cache(
        cache_path, "ddg", query,
        json.dumps({"results": [{
            "title": "Old aggregator",
            "url": "https://insights.triplegains.com/old",
        }]}),
    )
    calls = {"delegate": 0}

    class _FakeTool:
        @staticmethod
        def func(query, max_results=10):
            calls["delegate"] += 1
            return json.dumps({"results": [{
                "title": "Authoritative replacement",
                "url": "https://www.imf.org/replacement",
            }]})

    monkeypatch.setattr(
        st, "_load_search_module",
        lambda _provider: type("M", (), {"web_search_tool": _FakeTool})(),
    )
    result = json.loads(st.web_search_impl(query, 10))

    assert calls["delegate"] == 1
    assert result["results"][0]["url"] == "https://www.imf.org/replacement"


# ================================================================ ITEM 10 —— 源缓存（tmp dir 注入 fetch）

def _fresh_cache_dir(monkeypatch, tmp_path):
    d = tmp_path / "source_cache"
    monkeypatch.setenv("RESEARCH_SOURCE_CACHE_DIR", str(d))
    return d


class _Counter:
    """注入式异步 fetch：记调用次数、返回可配置正文。"""
    def __init__(self, content):
        self.content = content
        self.calls = 0

    async def __call__(self, url):
        self.calls += 1
        return self.content


def test_known_ai_seo_aggregator_is_rejected_before_fetch(monkeypatch, tmp_path):
    _fresh_cache_dir(monkeypatch, tmp_path)
    monkeypatch.delenv("RESEARCH_ALLOW_LOW_QUALITY_SOURCES", raising=False)
    monkeypatch.delenv("RESEARCH_SOURCE_DENY_DOMAINS", raising=False)
    fetch = _Counter("should never be returned " * 30)

    result = json.loads(asyncio.run(cf.cached_fetch(
        "https://economicsummarizer.com/sk-hynix-stock-analysis/", fetch)))

    assert result["error"] == "source_quality_rejected"
    assert fetch.calls == 0


def test_cache_miss_then_hit(monkeypatch, tmp_path):
    """首调 miss → 抓取并落盘；次调 hit → 从缓存返回，fetch 不再被调用。"""
    _fresh_cache_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("RESEARCH_SOURCE_CACHE_TTL_H", "72")
    fetch = _Counter("A" * 500)  # ≥200 字符 → 可缓存
    url = "https://example.com/report"
    r1 = asyncio.run(cf.cached_fetch(url, fetch))
    r2 = asyncio.run(cf.cached_fetch(url, fetch))
    assert r1 == r2 == "A" * 500
    assert fetch.calls == 1  # 第二次命中缓存，未再抓取


def test_cache_ttl_expiry_refetches(monkeypatch, tmp_path):
    """落盘条目过 TTL → 视作未命中 → 重抓（fetch 再次被调用）。"""
    d = _fresh_cache_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("RESEARCH_SOURCE_CACHE_TTL_H", "1")  # 1h
    fetch = _Counter("B" * 500)
    url = "https://example.com/stale"
    asyncio.run(cf.cached_fetch(url, fetch))
    assert fetch.calls == 1
    # 把落盘的 fetched_at 改成 2h 前（早于 1h TTL）→ 过期
    path = cf._cache_path(str(d), url)
    obj = json.loads(open(path, encoding="utf-8").read())
    obj["fetched_at"] = time.time() - 2 * 3600
    open(path, "w", encoding="utf-8").write(json.dumps(obj))
    asyncio.run(cf.cached_fetch(url, fetch))
    assert fetch.calls == 2  # 过期后重抓


def test_cache_ttl_zero_disables(monkeypatch, tmp_path):
    """TTL=0 → 缓存关闭：每次都透明直连 fetch，且不写任何缓存文件。"""
    d = _fresh_cache_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("RESEARCH_SOURCE_CACHE_TTL_H", "0")
    fetch = _Counter("C" * 500)
    url = "https://example.com/nocache"
    asyncio.run(cf.cached_fetch(url, fetch))
    asyncio.run(cf.cached_fetch(url, fetch))
    assert fetch.calls == 2  # 每次都抓
    assert not os.path.exists(cf._cache_path(str(d), url))  # 未落盘


def test_cache_skips_error_sentinel(monkeypatch, tmp_path):
    """jina 失败哨兵（"Error:" 起头）绝不落盘 → 下次仍重抓。"""
    d = _fresh_cache_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("RESEARCH_SOURCE_CACHE_TTL_H", "72")
    fetch = _Counter("Error: 404 not found while crawling")
    url = "https://example.com/dead"
    asyncio.run(cf.cached_fetch(url, fetch))
    asyncio.run(cf.cached_fetch(url, fetch))
    assert fetch.calls == 2
    assert not os.path.exists(cf._cache_path(str(d), url))


def test_cache_skips_short_dead_fetch(monkeypatch, tmp_path):
    """正文 <200 字符（死抓取/空壳）不落盘 → 下次重抓。"""
    d = _fresh_cache_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("RESEARCH_SOURCE_CACHE_TTL_H", "72")
    fetch = _Counter("too short")  # <200 字符
    url = "https://example.com/thin"
    asyncio.run(cf.cached_fetch(url, fetch))
    asyncio.run(cf.cached_fetch(url, fetch))
    assert fetch.calls == 2
    assert not os.path.exists(cf._cache_path(str(d), url))


def test_is_cacheable_rules():
    assert cf._is_cacheable("X" * 200) is True
    assert cf._is_cacheable("X" * 199) is False       # 边界：199<200 不可缓存
    assert cf._is_cacheable("Error: boom" + "y" * 500) is False  # 哨兵
    assert cf._is_cacheable("") is False
    assert cf._is_cacheable("   ") is False
    assert cf._is_cacheable(None) is False            # 非 str
    assert cf._is_cacheable(b"x" * 500) is False      # bytes 非 str


def test_cache_key_is_sha256_hex():
    import hashlib
    url = "https://example.com/a"
    assert cf._cache_key(url) == hashlib.sha256(url.encode("utf-8")).hexdigest()


def test_enforce_size_cap_evicts_oldest(monkeypatch, tmp_path):
    """目录超上限 → 按 mtime 升序淘汰最久未用文件直到回落上限内。"""
    d = tmp_path / "sc"
    d.mkdir()
    # 写 3 个 ~100KB 的缓存文件，mtime 递增（old < mid < new）
    paths = []
    for i, name in enumerate(["old", "mid", "new"]):
        p = d / f"{name}.json"
        p.write_text("z" * 100_000, encoding="utf-8")
        ts = 1_000_000 + i * 100
        os.utime(p, (ts, ts))
        paths.append(p)
    # 上限 ~250KB → 只容 2 个文件，最久未用（old）应被淘汰
    cf._enforce_size_cap(str(d), 250_000)
    assert not paths[0].exists()      # old 淘汰
    assert paths[1].exists()          # mid 保留
    assert paths[2].exists()          # new 保留


def test_enforce_size_cap_zero_is_unlimited(monkeypatch, tmp_path):
    d = tmp_path / "sc2"
    d.mkdir()
    p = d / "a.json"
    p.write_text("z" * 100_000, encoding="utf-8")
    cf._enforce_size_cap(str(d), 0)   # 0 = 不限
    assert p.exists()


def test_cache_lru_eviction_end_to_end(monkeypatch, tmp_path):
    """端到端：小上限下多 URL 落盘，最久未用条目被淘汰（再取会重抓）。"""
    d = _fresh_cache_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("RESEARCH_SOURCE_CACHE_TTL_H", "72")
    # 上限设为 ~1.5 个 200KB 文件 → 写第二个时第一个被淘汰
    monkeypatch.setenv("RESEARCH_SOURCE_CACHE_MAX_MB", str(300_000 / (1024 * 1024)))
    big = "Q" * 200_000
    u1, u2 = "https://example.com/1", "https://example.com/2"
    asyncio.run(cf.cached_fetch(u1, _Counter(big)))
    # 让 u1 的 mtime 明显更旧，保证淘汰顺序确定
    p1 = cf._cache_path(str(d), u1)
    os.utime(p1, (1_000, 1_000))
    asyncio.run(cf.cached_fetch(u2, _Counter(big)))
    # u1 应被淘汰（超上限、最久未用）；u2 在盘
    assert not os.path.exists(p1)
    assert os.path.exists(cf._cache_path(str(d), u2))


# ================================================================ TIME-2 —— 来源发布日期旁路（_FETCH_META）

class _FakeResponse:
    def __init__(self, status_code=200, payload=None, *, text="", headers=None, content=b""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
        self.headers = headers or {}
        self.content = content or text.encode("utf-8")

    def json(self):
        return self._payload


def _fake_httpx(monkeypatch, response):
    """假 httpx（sys.modules 注入）：Client/AsyncClient 的 post/get 都回放 ``response``。"""
    import types

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def post(self, url, headers=None, json=None):
            return response

    class _AsyncClient(_Client):
        async def post(self, url, headers=None, json=None):
            return response

        async def get(self, url):
            return response

    mod = types.ModuleType("httpx")
    mod.Client = _Client
    mod.AsyncClient = _AsyncClient
    monkeypatch.setitem(sys.modules, "httpx", mod)


_FIRECRAWL_BODY = "Grid connection queues exceed 40 months in several regions. " * 10


def _scrape(metadata):
    return _FakeResponse(200, {"success": True, "data": {"markdown": _FIRECRAWL_BODY, "metadata": metadata}})


def _firecrawl_env(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
    monkeypatch.setattr(cf, "_firecrawl_fetch_calls", 0)
    monkeypatch.setattr(cf, "_research_budget", None)
    for name in ("RESEARCH_FIRECRAWL_MAX_FETCH_CALLS_PER_PROCESS", "RESEARCH_FIRECRAWL_FETCH_MAX_CHARS"):
        monkeypatch.delenv(name, raising=False)


def _in_one_task(coroutine_fn, *args):
    """Run ``coroutine_fn(*args)`` and read _FETCH_META in the same task (as cached_fetch does)."""
    async def run():
        result = await coroutine_fn(*args)
        return result, cf._FETCH_META.get()

    return asyncio.run(run())


def test_firecrawl_fetch_records_date_metadata_and_returns_the_unchanged_text(monkeypatch):
    _firecrawl_env(monkeypatch)
    metadata = {"title": "Grid report", "publishedTime": "2025-05-10T01:00:00+05:00",
                "article:modified_time": ["2025-06-01", "2025-06-02"], "sourceURL": "https://x.org/a",
                "og:updated_time": "x" * 500, "statusCode": 200, "timezone": None, "dateList": [None, True]}
    _fake_httpx(monkeypatch, _scrape(metadata))
    out, meta = _in_one_task(cf._firecrawl_fetch, "https://x.org/a")
    assert out == f"# Grid report\n\n{_FIRECRAWL_BODY.strip()}"
    assert meta == {"publishedTime": "2025-05-10T01:00:00+05:00",
                    "article:modified_time": ["2025-06-01", "2025-06-02"], "og:updated_time": "x" * 80}
    # Without date metadata the text is the same and the side channel stays empty.
    _fake_httpx(monkeypatch, _scrape({"title": "Grid report"}))
    plain, meta = _in_one_task(cf._firecrawl_fetch, "https://x.org/a")
    assert plain == out and meta == {}


def test_firecrawl_date_metadata_keeps_every_key_source_dates_reads():
    # Review round 1: the key filter dropped "dcterms.created" before source_dates saw it.
    sd = cf._source_dates
    assert sd is not None
    for key in sd.PUBLISHED_META_KEYS + sd.MODIFIED_META_KEYS:
        assert cf._date_metadata({"title": "t", key: "2025-05-09"}) == {key: "2025-05-09"}, key
    # Firecrawl's camel-cased Dublin Core keys are publication dates.
    kept = cf._date_metadata({"dcterms.created": "2025-05-09", "dcTermsCreated": "2025-05-08",
                              "dcDateCreated": "2025-05-07", "dcDate": "2025-05-06", "ogUrl": "https://x"})
    assert [candidate[2:] for candidate in sd.from_fetch_meta(kept)] == [
        ("published", "2025-05-09"), ("published", "2025-05-08"), ("published", "2025-05-07"),
        ("published", "2025-05-06")]


def test_firecrawl_date_metadata_keeps_at_most_twelve_keys():
    many = {f"date_{i:02d}": f"2025-05-{i + 1:02d}" for i in range(20)}
    kept = cf._date_metadata({"title": "t", **many})
    assert list(kept) == [f"date_{i:02d}" for i in range(12)]


def test_exa_fetch_records_published_date(monkeypatch):
    import types

    row = types.SimpleNamespace(title="Exa page", text="Body " * 100, published_date="2025-05-09T00:00:00.000Z")

    class Exa:
        def __init__(self, api_key):
            pass

        def get_contents(self, urls, text=None):
            return types.SimpleNamespace(results=[row])

    monkeypatch.setitem(sys.modules, "exa_py", types.SimpleNamespace(Exa=Exa))
    monkeypatch.setenv("EXA_API_KEY", "exa-test")
    out, meta = _in_one_task(cf._exa_fetch, "https://x.org/a")
    assert out.startswith("# Exa page\n\nBody") and meta == {"publishedDate": "2025-05-09T00:00:00.000Z"}


def test_direct_fetch_records_html_date_candidates(monkeypatch):
    page = ("<html><head><meta property=\"article:published_time\" content=\"2025-05-09\"></head><body>"
            + "<p>Grid connection queues exceed 40 months in several regions of the country.</p>" * 10
            + "</body></html>")
    _fake_httpx(monkeypatch, _FakeResponse(200, text=page, headers={"content-type": "text/html"}))

    async def public(host):
        return True

    monkeypatch.setattr(cf, "_host_is_public", public)
    out, meta = _in_one_task(cf._direct_http_fetch, "https://x.org/a")
    assert "Grid connection queues" in out
    assert meta == {"html_dates": [[5, "meta_tag", "published", "2025-05-09"]]}


def test_resilient_fetch_drops_a_failed_providers_metadata(monkeypatch):
    _firecrawl_env(monkeypatch)
    _fake_httpx(monkeypatch, _FakeResponse(200, {"success": True, "data": {
        "markdown": "Just a moment... checking your browser", "metadata": {"publishedTime": "2019-01-01"}}}))

    async def jina(url):
        return "# Jina page\n\n" + "usable body content " * 30

    monkeypatch.setattr(cf, "_jina_delegate_fetch", jina)
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    out, meta = _in_one_task(cf._resilient_fetch, "https://x.org/a")
    assert out.startswith("# Jina page") and meta == {}


def test_cached_fetch_with_meta_sees_the_providers_metadata_in_the_same_task(monkeypatch, tmp_path):
    """The ContextVar written inside _resilient_fetch -> _firecrawl_fetch is
    read by cached_fetch_with_meta right after awaiting the fetch."""
    _fresh_cache_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("RESEARCH_SOURCE_CACHE_TTL_H", "72")
    _firecrawl_env(monkeypatch)
    _fake_httpx(monkeypatch, _scrape({"title": "Grid report", "publishedTime": "2025-05-09T10:00:00Z"}))
    text, meta = asyncio.run(cf.cached_fetch_with_meta("https://x.org/a", cf._resilient_fetch))
    assert text.startswith("# Grid report") and meta == {"publishedTime": "2025-05-09T10:00:00Z"}


class _MetaFetch:
    """注入式 fetch：像 provider 一样写 _FETCH_META（为空则不写）。"""

    def __init__(self, content, meta):
        self.content, self.meta, self.calls = content, meta, 0

    async def __call__(self, url):
        self.calls += 1
        if self.meta:
            cf._FETCH_META.set(dict(self.meta))
        return self.content


def test_cache_entry_holds_meta_only_when_non_empty(monkeypatch, tmp_path):
    d = _fresh_cache_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("RESEARCH_SOURCE_CACHE_TTL_H", "72")
    monkeypatch.setattr(cf, "_research_budget", None)
    dated, plain = "https://x.org/dated", "https://x.org/plain"
    asyncio.run(cf.cached_fetch(dated, _MetaFetch("D" * 500, {"publishedTime": "2025-05-09"})))
    asyncio.run(cf.cached_fetch(plain, _MetaFetch("P" * 500, {})))
    with open(cf._cache_path(str(d), dated), encoding="utf-8") as f:
        assert json.load(f)["meta"] == {"publishedTime": "2025-05-09"}
    with open(cf._cache_path(str(d), plain), encoding="utf-8") as f:
        assert sorted(json.load(f)) == ["content", "content_len", "fetched_at", "url"]


def test_cached_fetch_with_meta_returns_meta_on_miss_and_hit(monkeypatch, tmp_path):
    _fresh_cache_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("RESEARCH_SOURCE_CACHE_TTL_H", "72")
    monkeypatch.setattr(cf, "_research_budget", None)
    fetch = _MetaFetch("M" * 500, {"publishedTime": "2025-05-09"})
    url = "https://x.org/m"
    miss = asyncio.run(cf.cached_fetch_with_meta(url, fetch))
    hit = asyncio.run(cf.cached_fetch_with_meta(url, fetch))
    assert miss == hit == ("M" * 500, {"publishedTime": "2025-05-09"})
    assert fetch.calls == 1
    # cached_fetch keeps its str contract and returns the identical text.
    assert asyncio.run(cf.cached_fetch(url, fetch)) == "M" * 500
    assert cf._read_cache(cf._cache_path(cf._cache_root(), url), 3600.0) == "M" * 500


def test_cached_fetch_returns_the_identical_string_on_every_path(monkeypatch, tmp_path):
    _fresh_cache_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("RESEARCH_SOURCE_CACHE_TTL_H", "72")
    monkeypatch.setattr(cf, "_research_budget", None)
    for url, content in (("https://x.org/ok", "O" * 500), ("https://x.org/err", "Error: 404 not found")):
        fetch = _MetaFetch(content, {"publishedTime": "2025-05-09"})
        text = asyncio.run(cf.cached_fetch(url, fetch))
        assert isinstance(text, str) and text == content
        assert asyncio.run(cf.cached_fetch_with_meta(url, fetch))[0] == content
    rejected = asyncio.run(cf.cached_fetch_with_meta("https://economicsummarizer.com/x", _MetaFetch("x", {})))
    assert json.loads(rejected[0])["error"] == "source_quality_rejected" and rejected[1] == {}


def test_a_stale_meta_never_leaks_into_the_next_fetch(monkeypatch, tmp_path):
    _fresh_cache_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("RESEARCH_SOURCE_CACHE_TTL_H", "0")
    monkeypatch.setattr(cf, "_research_budget", None)

    async def run():
        first = await cf.cached_fetch_with_meta("https://x.org/1", _MetaFetch("A" * 500, {"publishedTime": "2025"}))
        second = await cf.cached_fetch_with_meta("https://x.org/2", _MetaFetch("B" * 500, {}))
        return first, second

    first, second = asyncio.run(run())
    assert first[1] == {"publishedTime": "2025"} and second[1] == {}


_DATED_SEARCH = _FakeResponse(200, {"success": True, "data": {"web": [
    {"url": "https://a.example/x", "title": "A", "description": "alpha", "publishedDate": "2025-05-09"},
    {"url": "https://b.example/y", "title": "B", "description": "beta"},
    {"url": "https://c.example/z", "title": "C", "description": "gamma", "date": "May 9, 2025"},
    {"url": "https://d.example/w", "title": "D", "description": "delta", "published_date": " "},
]}})


def _firecrawl_search_env(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
    monkeypatch.setattr(st, "_firecrawl_search_calls", 0)
    monkeypatch.setenv("RESEARCH_FIRECRAWL_CALLS_PER_MINUTE", "0")
    _fake_httpx(monkeypatch, _DATED_SEARCH)


def test_firecrawl_search_adds_published_only_for_dated_rows(monkeypatch):
    _firecrawl_search_env(monkeypatch)
    monkeypatch.setenv("RESEARCH_SOURCE_DATES", "true")
    rows = json.loads(st._firecrawl_search("grid queues", 5))["results"]
    assert [row.get("published") for row in rows] == ["2025-05-09", None, "May 9, 2025", None]
    assert all("published" not in row for row in rows if row["url"] in ("https://b.example/y",
                                                                           "https://d.example/w"))


def test_firecrawl_search_rows_are_unchanged_with_source_dates_off(monkeypatch):
    _firecrawl_search_env(monkeypatch)
    monkeypatch.delenv("RESEARCH_SOURCE_DATES", raising=False)
    out = st._firecrawl_search("grid queues", 5)
    assert out == json.dumps({"query": "grid queues", "total_results": 4, "results": [
        {"title": "A", "url": "https://a.example/x", "content": "alpha"},
        {"title": "B", "url": "https://b.example/y", "content": "beta"},
        {"title": "C", "url": "https://c.example/z", "content": "gamma"},
        {"title": "D", "url": "https://d.example/w", "content": "delta"},
    ]}, ensure_ascii=False)


def test_dated_firecrawl_rows_are_cached_apart_from_flag_off_rows(monkeypatch, tmp_path):
    """A flag-off search never reads a row cached with dates (its cache key is unchanged)."""
    for name in ("SERPER_API_KEY", "TAVILY_API_KEY", "RESEARCH_ALLOW_LOW_QUALITY_SOURCES",
                 "RESEARCH_SOURCE_DENY_DOMAINS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RESEARCH_SEARCH_CACHE_TTL_H", "6")
    monkeypatch.setenv("RESEARCH_SEARCH_CACHE_DIR", str(tmp_path / "search-cache"))
    monkeypatch.setattr(st, "_research_budget", None)
    _firecrawl_search_env(monkeypatch)
    assert st._search_cache_provider("firecrawl") == "firecrawl"
    monkeypatch.setenv("RESEARCH_SOURCE_DATES", "true")
    assert (st._search_cache_provider("firecrawl"), st._search_cache_provider("ddg")) == ("firecrawl+dates", "ddg")
    dated = json.loads(st.web_search_impl("grid queues", 5))["results"]
    assert dated[0]["published"] == "2025-05-09"
    monkeypatch.delenv("RESEARCH_SOURCE_DATES")
    plain = json.loads(st.web_search_impl("grid queues", 5))["results"]
    assert [row["url"] for row in plain] == [row["url"] for row in dated]
    assert not any("published" in row for row in plain)
    assert st._firecrawl_search_calls == 2
    # Each flag reads its own entry back.
    assert not any("published" in row for row in json.loads(st.web_search_impl("grid queues", 5))["results"])
    assert st._firecrawl_search_calls == 2
