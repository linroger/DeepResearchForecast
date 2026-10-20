"""Backtest mode in web search (search_tools) and the v3 tool layer (research_gateway).

Design: docs/handoff/backtest/design.md §5.  Zero network: httpx is a stand-in module,
the archive lookup and the fetch backend are injected.  Each live-path test pins that a
run without ``DRF_BACKTEST_POLICY`` sends and returns exactly what it did before.
"""

from __future__ import annotations

import json
import os
import sys
import types

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BRIDGE_DIR = os.path.join(_REPO_ROOT, "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import backtest_cutoff as bt  # noqa: E402
import research_gateway as rg  # noqa: E402
import search_tools as st  # noqa: E402


def _policy(tmp_path, *, strict=True, archive="wayback"):
    return bt.parse_policy({"as_of": "2024-11-01", "strict": strict, "archive": archive,
                            "audit_path": str(tmp_path / "backtest_audit.jsonl")})


def _audit(tmp_path):
    path = tmp_path / "backtest_audit.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


# ================================================================ search_tools

class _FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeClient:
    calls: list = []
    payload: dict = {}

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, headers=None, json=None):
        type(self).calls.append(json)
        return _FakeResponse(type(self).payload)


FIRECRAWL_PAYLOAD = {"data": {
    "web": [{"url": "https://wiki.example/election", "title": "Election explainer", "description": "undated"},
            {"url": "https://blog.example/2024/11/07/results", "title": "Results", "description": "after"}],
    "news": [{"url": "https://news.example/final-polls", "title": "Final polls", "snippet": "tight race",
              "date": "Oct 30, 2024"},
             {"url": "https://news.example/winner", "title": "Winner declared", "snippet": "outcome",
              "date": "Nov 6, 2024"}],
}}


@pytest.fixture()
def firecrawl(monkeypatch, tmp_path):
    for name in ("SERPER_API_KEY", "TAVILY_API_KEY", st._BACKTEST_POLICY_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
    monkeypatch.setenv("RESEARCH_SEARCH_CACHE_TTL_H", "1")
    monkeypatch.setenv("RESEARCH_SEARCH_CACHE_DIR", str(tmp_path / "search_cache"))
    monkeypatch.setenv("RESEARCH_FIRECRAWL_CALLS_PER_MINUTE", "0")
    monkeypatch.setattr(st, "_research_budget", None)
    monkeypatch.setattr(st, "_firecrawl_search_calls", 0)
    _FakeClient.calls = []
    _FakeClient.payload = FIRECRAWL_PAYLOAD
    module = types.ModuleType("httpx")
    module.Client = _FakeClient
    monkeypatch.setitem(sys.modules, "httpx", module)
    return _FakeClient


def test_live_search_payload_and_rows_are_unchanged(firecrawl):
    out = json.loads(st.web_search_impl("2024 election", 5))
    assert firecrawl.calls == [{"query": "2024 election", "limit": 5, "sources": ["web"]}]
    # Live: only web rows, no date field, no backtest block.
    assert [row["url"] for row in out["results"]] == ["https://wiki.example/election",
                                                      "https://blog.example/2024/11/07/results"]
    assert "backtest" not in out and all("date" not in row for row in out["results"])


def test_backtest_search_uses_the_provider_filter_and_drops_late_rows(firecrawl, monkeypatch, tmp_path):
    monkeypatch.setenv(st._BACKTEST_POLICY_ENV, _policy(tmp_path).to_env())
    out = json.loads(st.web_search_impl("2024 election", 5))
    body = firecrawl.calls[0]
    assert body["tbs"] == "cdr:1,cd_max:11/1/2024" and body["sources"] == ["web", "news"]
    # Strict: the dated news row before the cutoff only.
    assert [row["url"] for row in out["results"]] == ["https://news.example/final-polls"]
    assert out["results"][0]["backtest"]["verdict"] == "before"
    assert out["backtest"]["dropped_after"] == 2 and out["backtest"]["dropped_undated"] == 1
    assert {line["url"] for line in _audit(tmp_path) if line["action"] == "dropped"} == {
        "https://wiki.example/election", "https://blog.example/2024/11/07/results",
        "https://news.example/winner"}


def test_backtest_search_never_reuses_live_cache_entries(firecrawl, monkeypatch, tmp_path):
    st.web_search_impl("2024 election", 5)  # live, cached
    st.web_search_impl("2024 election", 5)  # live cache hit
    assert len(firecrawl.calls) == 1
    monkeypatch.setenv(st._BACKTEST_POLICY_ENV, _policy(tmp_path, strict=False).to_env())
    lenient = json.loads(st.web_search_impl("2024 election", 5))
    assert len(firecrawl.calls) == 2 and "tbs" in firecrawl.calls[1]
    assert [row["url"] for row in lenient["results"]] == ["https://wiki.example/election",
                                                          "https://news.example/final-polls"]
    st.web_search_impl("2024 election", 5)  # same policy: its own cache entry
    assert len(firecrawl.calls) == 2
    monkeypatch.setenv(st._BACKTEST_POLICY_ENV, _policy(tmp_path, strict=True).to_env())
    st.web_search_impl("2024 election", 5)  # strictness is part of the key
    assert len(firecrawl.calls) == 3


def test_backtest_search_fails_closed(firecrawl, monkeypatch):
    monkeypatch.setenv(st._BACKTEST_POLICY_ENV, '{"as_of": "next tuesday"}')
    assert "backtest policy unusable" in json.loads(st.web_search_impl("q", 5))["error"]
    monkeypatch.setenv(st._BACKTEST_POLICY_ENV, '{"as_of": "2024-11-01"}')
    monkeypatch.setattr(st, "_backtest_cutoff", None)
    assert "not deployed" in json.loads(st.web_search_impl("q", 5))["error"]
    assert firecrawl.calls == []


# ================================================================ ResearchTools

PAGE_BODY = ("Polling averages show a statistical tie in the seven battleground states, with turnout "
             "models diverging by more than three points. Early voting reached 70 million ballots.\n\n") * 3


def _search_fn(rows):
    def search(query, n):
        return json.dumps({"query": query, "results": rows})
    return search


class _Fetch:
    def __init__(self, pages=None, fail=()):
        self.pages = dict(pages or {})
        self.fail = set(fail)
        self.urls: list[str] = []

    def __call__(self, url):
        self.urls.append(url)
        if url in self.fail:
            raise TimeoutError("timed out")
        return self.pages.get(url, "# Page\n\n" + PAGE_BODY)


def _cdx(timestamp, original):
    return json.dumps([["timestamp", "original", "statuscode", "mimetype"],
                       [timestamp, original, "200", "text/html"]])


def _tools(tmp_path, *, policy=None, rows=(), fetch=None, archive=None):
    ledger = rg.SourceLedger(tmp_path / "ledger.json")
    tools = rg.ResearchTools(ledger, tmp_path / "pages", search_fn=_search_fn(list(rows)),
                             fetch_fn=fetch or _Fetch(), archive_get=archive, backtest=policy)
    return tools, ledger


SEARCH_ROWS = [
    {"title": "Final polls", "url": "https://news.example/final-polls", "content": "tight race",
     "date": "2024-10-30"},
    {"title": "Winner declared", "url": "https://news.example/winner", "content": "Trump wins",
     "date": "2024-11-06"},
    {"title": "Explainer", "url": "https://wiki.example/election", "content": "how it works"},
]


def test_live_tools_render_exactly_as_before(tmp_path):
    tools, _ = _tools(tmp_path, rows=SEARCH_ROWS)
    text = tools.search("election", agent_id="K1")
    assert "Winner declared" in text and "dated" not in text and "undated" not in text
    fetch = _Fetch()
    tools, _ = _tools(tmp_path / "b", fetch=fetch, archive=lambda url, timeout: pytest.fail("archive used"))
    assert tools.fetch("https://wiki.example/election", agent_id="K1").startswith("[S1]")
    assert fetch.urls == ["https://wiki.example/election"]


def test_backtest_search_rendering_shows_dates_and_hides_late_hits(tmp_path):
    tools, ledger = _tools(tmp_path, policy=_policy(tmp_path, strict=False), rows=SEARCH_ROWS)
    text = tools.search("election", agent_id="K1")
    assert "Winner declared" not in text and "Trump wins" not in text
    assert "Final polls — news.example (" in text and "— dated 2024-10-30" in text
    assert "Explainer" in text and "— undated" in text
    rows = {row["url"]: row for row in ledger.rows()}
    assert rows["https://news.example/final-polls"]["backtest"]["verdict"] == "before"
    assert "https://news.example/winner" not in rows


def test_rows_the_search_tool_judged_are_not_judged_twice(tmp_path):
    policy = _policy(tmp_path)
    judged = bt.filter_search_payload({"results": SEARCH_ROWS}, policy)
    tools, _ = _tools(tmp_path, policy=policy, rows=judged["results"])
    before = len(_audit(tmp_path))
    tools.search("election", agent_id="K1")
    assert len(_audit(tmp_path)) == before


def test_backtest_fetch_reads_the_archive_capture(tmp_path):
    url = "https://wiki.example/election"
    snapshot = f"https://web.archive.org/web/20241031222855id_/{url}"
    fetch = _Fetch({snapshot: "# Election (archived)\n\n" + PAGE_BODY,
                    url: "# Election\n\nThe winner was announced on November 6.\n\n" + PAGE_BODY})
    archive_calls = []

    def archive(lookup, timeout):
        archive_calls.append(lookup)
        return _cdx("20241031222855", url)

    tools, ledger = _tools(tmp_path, policy=_policy(tmp_path), fetch=fetch, archive=archive)
    text = tools.fetch(url, agent_id="K1")
    assert text.startswith("[S1] Election (archived)") and "winner was announced" not in text
    assert fetch.urls == [snapshot] and len(archive_calls) == 1
    row = ledger.rows()[0]
    assert row["url"] == url  # cited by its own URL; the capture is in the backtest note
    assert row["backtest"] == {"verdict": "before", "via": "archive", "date": "2024-10-31",
                               "basis": "archive", "snapshot": snapshot}
    # The stored copy answers re-reads without the network.
    tools.fetch(url, focus="turnout", agent_id="K2")
    assert fetch.urls == [snapshot]


def test_unreadable_capture_falls_back_to_a_dated_live_page(tmp_path):
    url = "https://news.example/preview"
    snapshot = f"https://web.archive.org/web/20241020000000id_/{url}"
    fetch = _Fetch({url: "# Preview\n\nPublished Time: 2024-10-20T08:00:00Z\n\n" + PAGE_BODY}, fail={snapshot})
    tools, ledger = _tools(tmp_path, policy=_policy(tmp_path), fetch=fetch,
                           archive=lambda lookup, timeout: _cdx("20241020000000", url))
    assert tools.fetch(url, agent_id="K1").startswith("[S1] Preview")
    assert fetch.urls == [snapshot, url]
    assert ledger.rows()[0]["backtest"]["via"] == "live"
    assert ledger.rows()[0]["backtest"]["basis"] == "page:header.published time"


def test_live_page_modified_after_the_cutoff_is_refused_and_remembered(tmp_path):
    url = "https://site.example/guide"
    page = ('# Guide\n\n<script type="application/ld+json">{"datePublished": "2024-06-01", '
            '"dateModified": "2024-11-08"}</script>\n\n' + PAGE_BODY)
    fetch = _Fetch({url: page})
    tools, ledger = _tools(tmp_path, policy=_policy(tmp_path, strict=False), fetch=fetch,
                           archive=lambda lookup, timeout: "[]")
    assert tools.fetch(url, agent_id="K1") == "FETCH_FAILED(published_after_cutoff): try another source."
    assert tools.fetch(url, agent_id="K2").startswith("FETCH_FAILED(published_after_cutoff): this URL already failed")
    assert fetch.urls == [url] and ledger.rows() == []
    dropped = [line for line in _audit(tmp_path) if line["kind"] == "fetch"]
    assert dropped == [dict(dropped[0], action="dropped", verdict="after", via="live",
                            basis="page:jsonld.dateModified")]


def test_undated_page_strict_versus_lenient(tmp_path):
    url = "https://wiki.example/election"
    strict, _ = _tools(tmp_path / "s", policy=_policy(tmp_path / "s"), archive=lambda lookup, timeout: "[]")
    assert strict.fetch(url, agent_id="K1") == "FETCH_FAILED(undated_source): try another source."
    lenient, ledger = _tools(tmp_path / "l", policy=_policy(tmp_path / "l", strict=False),
                             archive=lambda lookup, timeout: "[]")
    assert lenient.fetch(url, agent_id="K1").startswith("[S1]")
    assert ledger.rows()[0]["backtest"]["verdict"] == "undated"


def test_a_dated_search_hit_dates_its_undated_page(tmp_path):
    tools, ledger = _tools(tmp_path, policy=_policy(tmp_path), rows=SEARCH_ROWS,
                           archive=lambda lookup, timeout: "[]")
    tools.search("election", agent_id="K1")
    assert tools.fetch("https://news.example/final-polls", agent_id="K1").startswith("[S1]")
    row = ledger.find("https://news.example/final-polls")
    assert row["backtest"]["verdict"] == "before" and row["backtest"]["basis"] == "result.date"


def test_archive_off_reads_live_pages_only(tmp_path):
    fetch = _Fetch({"https://news.example/2024/10/12/story": "# Story\n\n" + PAGE_BODY})
    tools, _ = _tools(tmp_path, policy=_policy(tmp_path, archive="off"), fetch=fetch,
                      archive=lambda lookup, timeout: pytest.fail("archive used"))
    assert tools.fetch("https://news.example/2024/10/12/story", agent_id="K1").startswith("[S1]")
    assert fetch.urls == ["https://news.example/2024/10/12/story"]
