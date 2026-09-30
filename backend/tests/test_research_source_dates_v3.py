"""TIME-2: source publication dates in the v3 research engine (RESEARCH_SOURCE_DATES).

Covers the source ledger (:meth:`SourceLedger.set_dates`: rank upgrades, never
downgrades), the research tools (provider metadata, text-head and URL
fallbacks, search-row dates, dated row headers outside the untrusted block,
degrade-safe skips), and full offline engine runs on the scripted model of
``test_research_engine_v3``: sources.json date keys, dated SOURCE INDEX and
References, quant ``source_date`` / ``as_of_after_source``,
``meta.source_dates``, and the flag-off (and flag-on-without-dates) runs being
byte-identical to the standard run.  Zero network, zero LLM.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re

import pytest

import test_research_engine_v3 as v3

# The shared fixtures (hermetic env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
rg = v3.rg

NOW = dt.datetime(2026, 9, 30, 12, 0, tzinfo=dt.timezone.utc)
# The standard fake search (the engine runs below swap v3.fake_search).
_STANDARD_SEARCH = v3.fake_search
PAGE = ("# Grid connection report\n\n"
        "Interconnection queues exceed forty months in several regions according to the operators. "
        "Operators reported substantial capital expenditure across the first half of the period.\n\n"
        "The agency expects demand growth to continue while grid approvals remain the binding constraint.")
# meta.json keys that differ between two runs of the same code (wall clock).
_VOLATILE_META = frozenset({"finished_at", "phases"})
_DATE_KEYS = ("date_precision", "date_source", "modified_at", "date_rejected")
_LEDGER_DATE_KEYS = ("published", "date_precision", "date_source", "date_rank", "modified_at", "date_rejected")


@pytest.fixture(autouse=True)
def _dates_env(monkeypatch):
    for name in ("RESEARCH_SOURCE_DATES", "RESEARCH_SOURCE_DATE_TEXT_FALLBACK"):
        monkeypatch.delenv(name, raising=False)


def _tools(tmp_path, *, fetch_fn=None, search_fn=None, source_dates=True, fallback=True, name="t"):
    ledger = rg.SourceLedger(tmp_path / name / "sources_ledger.json")
    tools = rg.ResearchTools(ledger, tmp_path / name / "pages", search_fn=search_fn or (lambda q, n: "{}"),
                             fetch_fn=fetch_fn or (lambda url: PAGE), source_dates=source_dates,
                             date_text_fallback=fallback, clock=lambda: NOW)
    return tools, ledger


def _search(*rows):
    return lambda query, n: json.dumps({"query": query, "results": list(rows)})


def _header(text: str) -> str:
    return text.split("\n", 1)[0]


# =============================================================== ledger

def test_set_dates_upgrades_by_rank_and_never_downgrades(tmp_path):
    ledger = rg.SourceLedger(tmp_path / "l.json")
    sid = ledger.register("https://x.org/a", "A")["sid"]
    row = ledger.set_dates(sid, published="2025-05", precision="month", date_source="url_path", rank=2)
    assert (row["published"], row["date_precision"], row["date_source"], row["date_rank"]) == (
        "2025-05", "month", "url_path", 2)
    # A lower or equal rank never replaces it.
    for rank, source in ((1, "search_provider"), (2, "url_path")):
        row = ledger.set_dates(sid, published="2020-01-01", precision="day", date_source=source, rank=rank)
        assert row["published"] == "2025-05" and row["date_rank"] == 2
    row = ledger.set_dates(sid, published="2025-05-09", precision="day", date_source="provider_meta", rank=7,
                           modified="2025-06-01")
    assert (row["published"], row["date_source"], row["date_rank"], row["modified_at"]) == (
        "2025-05-09", "provider_meta", 7, "2025-06-01")
    # modified_at keeps its first value; rejections are sorted, unique, at most 3.
    row = ledger.set_dates(sid, published=None, precision=None, date_source=None, rank=0, modified="2026-01-01",
                           rejected=["future", "unparseable", "future"])
    assert row["modified_at"] == "2025-06-01" and row["date_rejected"] == ["future", "unparseable"]
    row = ledger.set_dates(sid, published=None, precision=None, date_source=None, rank=0,
                           rejected=["pre_1900", "zzz", "aaa"])
    assert row["date_rejected"] == ["aaa", "future", "pre_1900"]
    assert ledger.set_dates(999, published="2025", precision="year", date_source="x", rank=9) is None


def test_set_dates_writes_only_on_change_and_survives_a_reload(tmp_path):
    path = tmp_path / "l.json"
    ledger = rg.SourceLedger(path, clock=lambda: 0.0)
    sid = ledger.register("https://x.org/a", "A")["sid"]
    ledger.flush()
    ledger.set_dates(sid, published="2025-05-09", precision="day", date_source="provider_meta", rank=7)
    ledger.flush()
    before = path.read_bytes()
    ledger.set_dates(sid, published="2024-01-01", precision="day", date_source="url_path", rank=2)
    assert not ledger._dirty
    ledger.flush()
    assert path.read_bytes() == before
    reloaded = rg.SourceLedger(path).get(sid)
    assert reloaded["published"] == "2025-05-09" and reloaded["date_rank"] == 7


# =============================================================== tools: fetch

def test_provider_metadata_dates_a_fetched_page(tmp_path):
    tools, ledger = _tools(tmp_path, fetch_fn=lambda url: (PAGE, {"publishedTime": "2025-05-09T10:00:00Z"}))
    out = tools.fetch("https://www.reuters.com/markets/grid", focus="queues", agent_id="K1")
    row = ledger.get(1)
    assert (row["published"], row["date_precision"], row["date_source"], row["date_rank"]) == (
        "2025-05-09", "day", "provider_meta", 7)
    assert _header(out) == (f"[S1] Grid connection report — reuters.com (tier 3) — published 2025-05-09 — "
                            f"full page ({len(PAGE)} chars).")


def test_offset_timestamp_just_after_midnight_is_the_previous_utc_day(tmp_path):
    tools, ledger = _tools(tmp_path, fetch_fn=lambda url: (PAGE, {"publishedTime": "2025-05-10T01:00:00+05:00"}))
    tools.fetch("https://x.org/a", agent_id="K1")
    assert ledger.get(1)["published"] == "2025-05-09"


def test_modified_date_is_shown_only_when_later(tmp_path):
    meta = {"publishedTime": "2019-03-01", "modifiedTime": "2025-06-01"}
    tools, ledger = _tools(tmp_path, fetch_fn=lambda url: (PAGE, meta))
    out = tools.fetch("https://x.org/stats", agent_id="K1")
    assert " — published 2019-03-01; updated 2025-06-01 — full page" in _header(out)
    assert ledger.get(1)["modified_at"] == "2025-06-01"
    same, _ = _tools(tmp_path, fetch_fn=lambda url: (PAGE, {"publishedTime": "2025-06", "modifiedTime": "2025-06-10"}),
                     name="same")
    assert "updated" not in _header(same.fetch("https://x.org/b", agent_id="K1"))


def test_text_head_and_url_fallbacks_and_their_switch(tmp_path):
    page = PAGE.replace("\n\n", "\n\nPublished: May 9, 2025\n\n", 1)
    tools, ledger = _tools(tmp_path, fetch_fn=lambda url: page)
    tools.fetch("https://x.org/a", agent_id="K1")
    assert (ledger.get(1)["published"], ledger.get(1)["date_source"]) == ("2025-05-09", "text_head")
    tools.fetch("https://x.org/2024/03/grid-story", agent_id="K1")
    # The page's dateline (rank 3) outranks its URL month (rank 2).
    assert ledger.get(2)["published"] == "2025-05-09"
    url_only, url_ledger = _tools(tmp_path, name="url")
    url_only.fetch("https://x.org/2024/03/grid-story", agent_id="K1")
    assert (url_ledger.get(1)["published"], url_ledger.get(1)["date_precision"]) == ("2024-03", "month")
    off, off_ledger = _tools(tmp_path, fetch_fn=lambda url: page, fallback=False, name="off")
    out = off.fetch("https://x.org/2024/03/grid-story", agent_id="K1")
    assert "published" not in off_ledger.get(1) and "published" not in _header(out)


def test_future_dates_are_rejected_against_the_clock(tmp_path):
    tools, ledger = _tools(tmp_path, fetch_fn=lambda url: (PAGE, {"publishedTime": "2026-10-02"}))
    out = tools.fetch("https://x.org/a", agent_id="K1")
    row = ledger.get(1)
    assert "published" not in row and row["date_rejected"] == ["future"]
    assert "published" not in _header(out)


def test_header_date_stays_outside_the_untrusted_block_and_page_numbers(tmp_path):
    tools, ledger = _tools(tmp_path, fetch_fn=lambda url: (PAGE, {"publishedTime": "2025-05-09"}))
    out = tools.fetch("https://x.org/a", agent_id="K1")
    body = out.split("\n", 1)[1]
    assert "2025" not in body and "published" not in body
    numbers = lr.page_number_set(tools.page_text(1))
    assert not {"2025", "05", "09", "2025-05-09"} & set(numbers)
    # The stored copy is the page only, and a re-read shows the same dated header.
    assert tools.page_text(1) == PAGE.strip()
    again = tools.fetch("https://x.org/a", agent_id="K2")
    assert _header(again) == _header(out)


def test_missing_source_dates_module_skips_and_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(rg, "_source_dates", lambda: None)
    tools, ledger = _tools(tmp_path, fetch_fn=lambda url: (PAGE, {"publishedTime": "2025-05-09"}))
    out = tools.fetch("https://x.org/a", agent_id="K1")
    assert out.startswith("[S1] Grid connection report — x.org (tier 3) — full page")
    assert "published" not in ledger.get(1) and tools.date_stats() == {"skipped": 1}


def test_an_extractor_error_never_breaks_a_fetch(tmp_path, monkeypatch):
    class Broken:
        def resolve(self, candidates, *, now):
            raise RuntimeError("boom")

        def __getattr__(self, name):
            return lambda *args, **kwargs: []

    monkeypatch.setattr(rg, "_source_dates", lambda: Broken())
    tools, ledger = _tools(tmp_path, fetch_fn=lambda url: (PAGE, {"publishedTime": "2025-05-09"}))
    assert tools.fetch("https://x.org/a", agent_id="K1").startswith("[S1] Grid connection report")
    assert tools.date_stats() == {"skipped": 1}


def test_the_tuple_is_unpacked_before_every_failure_check(tmp_path):
    tools, ledger = _tools(tmp_path, fetch_fn=lambda url: ("Error: Firecrawl failed: HTTP 500", {"a": "b"}))
    assert tools.fetch("https://x.org/a", agent_id="K1").startswith("FETCH_FAILED(firecrawl_failed_http_500)")
    shell = "Markdown Content: undefined"
    shells, _ = _tools(tmp_path, fetch_fn=lambda url: (shell, {"publishedTime": "2025-05-09"}), name="shell")
    shells.shell_detection = True
    assert shells.fetch("https://x.org/a", agent_id="K1").startswith("FETCH_FAILED(")


# =============================================================== tools: search

def test_search_rows_are_dated_from_the_provider_and_the_url(tmp_path):
    rows = [{"title": "Provider dated", "url": "https://a.org/x", "content": "alpha", "published": "May 9, 2025"},
            {"title": "URL dated", "url": "https://b.org/2025/04/30/y", "content": "beta"},
            {"title": "Future", "url": "https://c.org/z", "content": "gamma", "date": "2099-01-01"},
            {"title": "Undated", "url": "https://d.org/w", "content": "delta"}]
    tools, ledger = _tools(tmp_path, search_fn=_search(*rows))
    out = tools.search("grid queues", agent_id="K1")
    headers = [line for line in out.splitlines() if line.startswith("[S")]
    assert headers == ["[S1] Provider dated — a.org (tier 3) — published 2025-05-09",
                       "[S2] URL dated — b.org (tier 3) — published 2025-04-30",
                       "[S3] Future — c.org (tier 3)",
                       "[S4] Undated — d.org (tier 3)"]
    assert (ledger.get(1)["date_source"], ledger.get(1)["date_rank"]) == ("search_provider", 1)
    assert (ledger.get(2)["date_source"], ledger.get(2)["date_rank"]) == ("url_path", 2)
    assert ledger.get(3)["date_rejected"] == ["future"] and "published" not in ledger.get(3)
    assert not any(key in ledger.get(4) for key in _LEDGER_DATE_KEYS)


def test_dated_headers_parse_to_the_same_sids(tmp_path):
    rows = [{"title": "Provider dated", "url": "https://a.org/x", "content": "alpha", "publishedDate": "2025-05-09"},
            {"title": "Undated", "url": "https://d.org/w", "content": "delta"}]
    tools, _ = _tools(tmp_path, search_fn=_search(*rows),
                      fetch_fn=lambda url: (PAGE, {"publishedTime": "2019-03-01", "modifiedTime": "2025-06-01"}))
    search = tools.search("grid queues", agent_id="K1")
    fetch = tools.fetch("https://d.org/w", agent_id="K1")
    assert " — published 2025-05-09" in search and " — published 2019-03-01; updated 2025-06-01" in fetch
    assert lr.tool_output_sids("web_search", search) == (None, [1, 2])
    assert lr.tool_output_sids("web_fetch", fetch) == (2, [2])


def test_fetch_upgrades_a_search_date_and_a_later_search_never_reverses_it(tmp_path):
    first = [{"title": "Story", "url": "https://a.org/x", "content": "alpha", "published": "2025-01-01"}]
    again = [{"title": "Story", "url": "https://a.org/x", "content": "alpha", "published": "2024-01-01"}]
    queue = [json.dumps({"results": first}), json.dumps({"results": again})]
    tools, ledger = _tools(tmp_path, search_fn=lambda q, n: queue.pop(0),
                           fetch_fn=lambda url: (PAGE, {"datePublished": "2025-05-09"}))
    tools.search("first query", agent_id="K1")
    assert (ledger.get(1)["published"], ledger.get(1)["date_rank"]) == ("2025-01-01", 1)
    tools.fetch("https://a.org/x", agent_id="K1")
    assert (ledger.get(1)["published"], ledger.get(1)["date_rank"]) == ("2025-05-09", 7)
    out = tools.search("second query", agent_id="K1")
    assert (ledger.get(1)["published"], ledger.get(1)["date_source"]) == ("2025-05-09", "provider_meta")
    # The fetch retitled the row from the page; the date is still the provider one.
    assert _header(out) == "[S1] Grid connection report — a.org (tier 3) — published 2025-05-09"


def test_flag_off_ignores_every_date_input(tmp_path):
    rows = [{"title": "Provider dated", "url": "https://a.org/2025/05/09/x", "content": "alpha",
             "published": "2025-05-09"}]
    dated = lambda url: (PAGE, {"publishedTime": "2025-05-09"})  # noqa: E731
    off, off_ledger = _tools(tmp_path, search_fn=_search(*rows), fetch_fn=dated, source_dates=False, name="off")
    plain, plain_ledger = _tools(tmp_path, search_fn=_search(*rows), fetch_fn=lambda url: PAGE,
                                 source_dates=False, name="plain")
    outputs = []
    for tools, ledger in ((off, off_ledger), (plain, plain_ledger)):
        outputs.append((tools.search("grid", agent_id="K1"), tools.fetch("https://a.org/2025/05/09/x", agent_id="K1")))
        ledger.flush()
    assert outputs[0] == outputs[1]
    assert _header(outputs[0][0]) == "[S1] Provider dated — a.org (tier 3)"
    assert _header(outputs[0][1]) == f"[S1] Grid connection report — a.org (tier 3) — full page ({len(PAGE)} chars)."
    assert ((tmp_path / "off" / "sources_ledger.json").read_bytes()
            == (tmp_path / "plain" / "sources_ledger.json").read_bytes())
    assert not any(key in off_ledger.get(1) for key in _LEDGER_DATE_KEYS)


# =============================================================== default fetch function

def _fake_cached_fetch(monkeypatch, *, with_meta: bool):
    import sys
    import types

    calls: list[str] = []

    async def resilient(url):
        return PAGE

    async def cached_fetch(url, fetch_fn, revisit_reason=""):
        calls.append("plain")
        return await fetch_fn(url)

    fake = types.ModuleType("cached_fetch")
    fake.cached_fetch = cached_fetch
    fake._resilient_fetch = resilient
    if with_meta:
        async def cached_fetch_with_meta(url, fetch_fn, revisit_reason=""):
            calls.append("meta")
            return await fetch_fn(url), {"publishedTime": "2025-05-09"}

        fake.cached_fetch_with_meta = cached_fetch_with_meta
    monkeypatch.setitem(sys.modules, "cached_fetch", fake)
    return calls


@pytest.mark.parametrize("source_dates, expected_call, expected_date", [(True, "meta", "2025-05-09"),
                                                                       (False, "plain", None)])
def test_default_fetch_uses_the_metadata_variant_only_with_dates_on(tmp_path, monkeypatch, source_dates,
                                                                    expected_call, expected_date):
    calls = _fake_cached_fetch(monkeypatch, with_meta=True)
    ledger = rg.SourceLedger(tmp_path / "l.json")
    tools = rg.ResearchTools(ledger, tmp_path / "pages", search_fn=lambda q, n: "{}", clock=lambda: NOW)
    # The engine turns the knob on after construction, as it does shell_detection.
    tools.source_dates = source_dates
    tools.fetch("https://x.org/a", agent_id="K1")
    assert calls == [expected_call] and ledger.get(1).get("published") == expected_date


def test_default_fetch_falls_back_when_cached_fetch_has_no_metadata_variant(tmp_path, monkeypatch):
    calls = _fake_cached_fetch(monkeypatch, with_meta=False)
    tools = rg.ResearchTools(rg.SourceLedger(tmp_path / "l.json"), tmp_path / "pages", source_dates=True)
    assert tools.fetch("https://x.org/a", agent_id="K1").startswith("[S1] Grid connection report")
    assert calls == ["plain"]


def test_production_tools_factory_reads_both_knobs(tmp_path, monkeypatch):
    def build():
        return lr._default_tools_factory(rg.SourceLedger(tmp_path / "l.json"), tmp_path / "pages", None, None,
                                         rg.ToolLimits())

    tools = build()
    assert (tools.source_dates, tools.date_text_fallback) == (False, True)
    monkeypatch.setenv("RESEARCH_SOURCE_DATES", "true")
    monkeypatch.setenv("RESEARCH_SOURCE_DATE_TEXT_FALLBACK", "false")
    tools = build()
    assert (tools.source_dates, tools.date_text_fallback) == (True, False)


# =============================================================== pure engine helpers

def test_source_rows_date_fields_and_digest_and_references_rendering():
    dated = {"sid": 1, "url": "https://a.org/x", "title": "A", "domain": "a.org", "tier": "S2", "fetched": True,
             "published": "2025-05-09", "date_precision": "day", "date_source": "provider_meta", "date_rank": 7,
             "modified_at": "2025-06-01", "date_rejected": ["future"]}
    undated = {"sid": 2, "url": "https://b.org/y", "title": "B", "domain": "b.org", "tier": "S3", "fetched": False,
               "date_rejected": ["unparseable"]}
    assert lr._source_date_fields(dated) == {"date": "2025-05-09", "date_precision": "day",
                                             "date_source": "provider_meta", "modified_at": "2025-06-01",
                                             "date_rejected": ["future"]}
    assert lr._source_date_fields(undated) == {}
    assert lr._source_date_fields({"published": "May 2025"}) == {}
    rows = {1: dated, 2: undated}
    references = lr.render_references([1, 2], rows.get, dates=True).splitlines()
    assert references[2] == "- [S1] A — https://a.org/x (tier 2; fetched; published 2025-05-09)"
    assert references[3] == "- [S2] B — https://b.org/y (tier 3; search snippet)"
    assert lr.render_references([1, 2], rows.get) == lr.render_references([1, 2], rows.get, dates=False)
    assert "published" not in lr.render_references([1, 2], rows.get)
    record = {"id": "K1", "question": "q", "facts": [{"text": "x [S1][S2]", "tag": "VERIFIED", "sids": [1, 2]}]}
    digest, _ = lr.build_digest([record], rows.get, 20000, "English", dates=True)
    index = digest.split("SOURCE INDEX\n", 1)[1].splitlines()
    assert index == ["[S1] A — a.org (tier 2, fetched, published 2025-05-09)", "[S2] B — b.org (tier 3, snippet)"]
    plain, _ = lr.build_digest([record], rows.get, 20000, "English")
    assert "published" not in plain and plain == lr.build_digest([record], rows.get, 20000, "English",
                                                                  dates=False)[0]


def test_source_date_summary_counts():
    rows = [{"published": "2025-05-09", "date_source": "provider_meta", "date_precision": "day"},
            {"published": "2025-05", "date_source": "url_path", "date_precision": "month",
             "date_rejected": ["future"]},
            {"published": "2025", "date_source": "provider_meta", "date_precision": "year"},
            {"date_rejected": ["future", "unparseable"]},
            {"date_rejected": ["pre_1900"]},
            {}]
    assert lr.source_date_summary(rows) == {
        "dated": 3, "undated": 3, "rejected_future": 2, "rejected_other": 2,
        "by_source": {"provider_meta": 2, "url_path": 1}, "by_precision": {"day": 1, "month": 1, "year": 1}}


def test_quant_source_dates_stamp_and_flag_never_drop():
    sources = [{"url": "https://a.org/x", "date": "2025-05-09"},
               {"url": "https://b.org/y", "date": "2019-03-01", "modified_at": "2025-06-01"},
               {"url": "https://c.org/z", "date": None}]
    quant = [{"metric": "m1", "value": 1, "as_of_date": "2025-06-01", "source_url": "https://a.org/x"},
             {"metric": "m2", "value": 2, "as_of_date": "2025-05", "source_url": "https://a.org/x"},
             {"metric": "m3", "value": 3, "as_of_date": "2025-05-01", "source_url": "https://b.org/y"},
             {"metric": "m4", "value": 4, "as_of_date": "2026", "source_url": "https://b.org/y"},
             {"metric": "m5", "value": 5, "as_of_date": "2030", "source_url": "https://c.org/z"},
             {"metric": "m6", "value": 6, "source_url": "https://a.org/x"}]
    assert lr.quant_source_dates(quant, sources) == 2
    assert [row.get("source_date") for row in quant] == ["2025-05-09", "2025-05-09", "2019-03-01", "2019-03-01",
                                                         None, "2025-05-09"]
    # m1 dated after its source; m2's month contains the source day; m3 is before
    # the source's modified date; m4 is after it; m5's source is undated; m6 has no as-of.
    assert [row.get("as_of_after_source") for row in quant] == [True, None, None, True, None, None]
    assert len(quant) == 6


# =============================================================== full engine runs

def dated_search(query: str, n: int) -> str:
    """The standard fake search with dated rows: agency2 URLs carry a date
    path, agency3 rows a provider date (a future one for half the queries)."""
    digest = hashlib.sha1(query.encode("utf-8")).hexdigest()[:6]
    results = []
    for i in range(1, 4):
        path = f"2025/05/0{i + 1}/report-{digest}" if i == 2 else f"data/report-{digest}"
        row = {"title": f"Capacity report {digest}-{i}", "url": f"https://www.agency{i}-{digest}.org/{path}",
               "content": f"Capacity statistics 2023: 176 GW installed; outlook note {i}."}
        if i == 3:
            row["published"] = "2099-01-01" if int(digest, 16) % 2 else "2025-04-01"
        results.append(row)
    return json.dumps({"query": query, "results": results})


def dated_fetch(url: str):
    """agency1 pages come with provider metadata (+05:00 just after midnight);
    agency2 pages carry an Updated dateline; agency3 pages are undated."""
    text = v3.page_text(url)
    if "agency1-" in url:
        return text, {"publishedTime": "2025-05-10T01:00:00+05:00", "title": "x"}
    if "agency2-" in url:
        return text.replace("\n\n", "\n\nUpdated: 2025-06-01\n\n", 1)
    return text


def meta_fetch(url: str):
    """The standard page with provider metadata (ignored with the flag off)."""
    return v3.page_text(url), {"publishedTime": "2025-05-10T01:00:00+05:00"}


def plain_search_with_dates(query: str, n: int) -> str:
    """The standard fake search rows (same URLs) with provider dates added."""
    payload = json.loads(_STANDARD_SEARCH(query, n))
    for row in payload["results"]:
        row["published"] = "2025-05-09"
    return json.dumps(payload)


class DatedWorld(v3.World):
    """The standard world whose research notes also cite every searched source
    (so URL-dated, search-dated and future-rejected rows reach the report) and
    whose fact extraction cites S1-S4 twice each: once dated long before any
    source, once dated after every source."""

    def notes(self, tool_results) -> str:
        searched = list(dict.fromkeys(int(s) for r in tool_results for s in re.findall(r"^\[S(\d+)\]", r, re.M)))
        cites = "".join(f"[S{sid}]" for sid in searched)
        finding = f"- Regional operators report queue data for 2024 {cites} (REPORTED)"
        return super().notes(tool_results).replace("## Findings\n", f"## Findings\n{finding}\n", 1)

    def facts(self, call):
        reply = json.loads(super().facts(call).content)
        reply["quantitative_facts"] = [
            {"metric": f"Installed capacity {ref}-{kind}", "value": "176", "unit": "GW", "as_of_date": as_of,
             "value_type": "actual", "source_ref": ref}
            for ref in ("S1", "S2", "S3", "S4") for kind, as_of in (("old", "2023-12-31"), ("new", "2026-01"))]
        return v3.ai(json.dumps(reply))


def _run(tmp_path, bridge, monkeypatch, *, dates: str | None, search=None, fetch=None, world=None, name="run"):
    # One worker: KIQs run in plan order, so two runs cite their sources in the
    # same order and are comparable byte for byte.
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")
    if dates is None:
        monkeypatch.delenv("RESEARCH_SOURCE_DATES", raising=False)
    else:
        monkeypatch.setenv("RESEARCH_SOURCE_DATES", dates)
    monkeypatch.setattr(v3, "fake_search", search or _STANDARD_SEARCH)
    rc, meta, plog, model, out = v3.run_engine(tmp_path / name, bridge, world or v3.World(), fetch=fetch)
    assert rc == 0, meta.get("error")
    return meta, plog, model, out


def _tool_texts(model) -> list[str]:
    seen: list[str] = []
    for call in model.calls:
        for kind, content in call["messages"]:
            if kind == "tool" and content not in seen:
                seen.append(content)
    return seen


def _artifacts(out) -> dict[str, bytes]:
    names = ("sources.json", "research_report.md", "actors.json", "quantitative.json", "timeline.json",
             "contested.json", "v3/sources_ledger.json", "v3/digest.md")
    return {name: (out / name).read_bytes() for name in names}


def _stable_meta(meta: dict) -> dict:
    return {key: value for key, value in meta.items() if key not in _VOLATILE_META}


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_flag_off_and_undated_flag_on_runs_are_byte_identical_to_the_standard_run(tmp_path, bridge, monkeypatch):
    base_meta, _plog, base_model, base = _run(tmp_path, bridge, monkeypatch, dates=None, name="base")
    # Flag off: provider metadata and search dates are ignored entirely.
    off_meta, _plog, off_model, off = _run(tmp_path, bridge, monkeypatch, dates="false",
                                           search=plain_search_with_dates, fetch=meta_fetch, name="off")
    # Flag on over the standard (undated) fixtures: nothing to date, nothing changes.
    on_meta, _plog, on_model, on = _run(tmp_path, bridge, monkeypatch, dates="true", name="on")

    base_artifacts = _artifacts(base)
    assert _artifacts(off) == base_artifacts
    assert _artifacts(on) == base_artifacts
    assert _tool_texts(off_model) == _tool_texts(base_model) == _tool_texts(on_model)
    assert _stable_meta(off_meta) == _stable_meta(base_meta)
    assert "source_dates" not in base_meta and "source_dates" not in off_meta
    assert on_meta.pop("source_dates")["dated"] == 0
    assert _stable_meta(on_meta) == _stable_meta(base_meta)
    # The standard output carries none of the new keys.
    for row in _load(base / "sources.json"):
        assert row["date"] is None and not any(key in row for key in _DATE_KEYS)
    for row in _load(base / "v3" / "sources_ledger.json"):
        assert not any(key in row for key in _LEDGER_DATE_KEYS)
    assert not any("source_date" in row or "as_of_after_source" in row for row in _load(base / "quantitative.json"))
    assert "published" not in (base / "research_report.md").read_text(encoding="utf-8")


def test_dated_run_publishes_dates_everywhere(tmp_path, bridge, monkeypatch):
    meta, plog, model, out = _run(tmp_path, bridge, monkeypatch, dates="true", search=dated_search,
                                  fetch=dated_fetch, world=DatedWorld())
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    ledger = {row["url"]: row for row in _load(out / "v3" / "sources_ledger.json")}
    sources = _load(out / "sources.json")
    assert sources
    for row in sources:
        fixture_dated = ("agency1-" in row["url"] and ledger[row["url"]]["fetched"]) or "agency2-" in row["url"]
        if fixture_dated:
            assert row["date"] and row["date_source"] and row["date_precision"], row
        if row["date"] is None:
            assert not any(key in row for key in _DATE_KEYS), row
            continue
        assert row["date"] <= today
        assert row["date_source"] == ledger[row["url"]]["date_source"]
        if "agency1-" in row["url"] and ledger[row["url"]]["fetched"]:
            # +05:00 at 01:00 is the previous UTC day.
            assert (row["date"], row["date_source"]) == ("2025-05-09", "provider_meta")
        if "agency2-" in row["url"] and ledger[row["url"]]["fetched"]:
            assert row["modified_at"] == "2025-06-01" and row["date_source"] == "url_path"
    assert any(row["date"] for row in sources)

    # Every ledger date is on or before the run's UTC date; future provider dates were rejected.
    for row in ledger.values():
        assert row.get("published", "") <= today
        if "agency3-" in row["url"] and not row.get("published"):
            assert row["date_rejected"] == ["future"]

    # Dated row headers in the tool texts; tool_output_sids reads them.
    texts = _tool_texts(model)
    dated_headers = [text for text in texts if re.search(r"^\[S\d+\] .* — published \d{4}", text, re.M)]
    assert dated_headers
    for text in texts:
        if text.startswith("[S") and (" — full page (" in _header(text) or " — excerpt " in _header(text)):
            sid, shown = lr.tool_output_sids("web_fetch", text)
            assert sid == int(re.match(r"\[S(\d+)\]", text).group(1)) and shown == [sid]

    # SOURCE INDEX and References show the dates of dated rows only.
    by_sid = {row["sid"]: row for row in ledger.values()}
    index = (out / "v3" / "digest.md").read_text(encoding="utf-8").split("SOURCE INDEX\n", 1)[1].splitlines()
    assert index
    for line in index:
        sid = int(re.match(r"\[S(\d+)\]", line).group(1))
        published = by_sid[sid].get("published")
        assert line.endswith(f", published {published})") if published else "published" not in line
    report = (out / "research_report.md").read_text(encoding="utf-8")
    references = report.split("## References", 1)[1].strip().splitlines()
    assert len(references) == len(sources)
    for line, row in zip(references, sources, strict=True):
        assert line.endswith(f"; published {row['date']})") if row["date"] else "published" not in line

    # Quant rows citing dated sources carry source_date; the 2026 ones are flagged.
    quant = _load(out / "quantitative.json")
    by_url = {row["url"]: row for row in sources}
    stamped = [row for row in quant if row.get("source_date")]
    assert stamped and any(row.get("as_of_after_source") for row in stamped)
    for row in quant:
        source = by_url.get(row.get("source_url"))
        assert row.get("source_date") == (source["date"] if source else None)
        if row.get("source_date"):
            assert bool(row.get("as_of_after_source")) == row["as_of_date"].startswith("2026"), row
    actors_quant = _load(out / "actors.json")["quantitative_facts"]
    assert [row.get("source_date") for row in actors_quant] == [row.get("source_date") for row in quant]

    # meta.source_dates summarises the published sources' ledger rows.
    cited = [ledger[row["url"]] for row in sources]
    assert meta["source_dates"] == lr.source_date_summary(cited)
    assert meta["source_dates"]["dated"] == sum(1 for row in sources if row["date"])
    assert meta["source_dates"]["dated"] + meta["source_dates"]["undated"] == len(sources)
    assert sum(meta["source_dates"]["by_source"].values()) == meta["source_dates"]["dated"]
    # The fixtures put provider-metadata and URL-path dates and rejected future
    # provider dates among the cited sources.
    assert {"provider_meta", "url_path"} <= set(meta["source_dates"]["by_source"])
    assert meta["source_dates"]["rejected_future"] >= 1
    assert _load(out / "meta.json")["source_dates"] == meta["source_dates"]
    assert any(line.startswith("source dates: ") for line in plog.of("ok"))


def test_backend_references_show_a_v3_source_date(tmp_path, monkeypatch):
    """report_agent's References render sources.json ``date`` as written by v3."""
    from app.services.report_agent import ReportAgent, ReportManager

    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    (tmp_path / "reports").mkdir()
    rid = "report_time2"
    ReportManager._ensure_report_folder(rid)
    source = {"source_id": "src_1", "url": "https://www.reuters.com/markets/grid-2025", "title": "Grid queue report",
              "tier": "S2", "date": "2025-05-09", "date_precision": "day", "date_source": "provider_meta",
              "source_origin": "fetched", "reachable": True,
              "supports": ["Interconnection queues exceed forty months in several regions"], "independent": None}
    agent = ReportAgent.__new__(ReportAgent)
    agent.sources, agent.research_report, agent.situation_brief = [source], "", ""
    agent._background_block, agent._outline_summary, agent.output_language = "", "", "English"
    agent._citation_index = {"S1": source}

    class Report:
        markdown_content = "## Outlook\n\nInterconnection queues exceed forty months in several regions [S1].\n"

    report = Report()
    agent._finalize_citations(rid, report)
    references = report.markdown_content.split("## References", 1)[1]
    assert "[S1] Grid queue report — reuters.com, 2025-05-09 — [https://www.reuters.com/markets/grid-2025]" \
        in references
