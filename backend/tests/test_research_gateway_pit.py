"""TIME-8: point-in-time gates of the v3 research tools (``ResearchTools.pit``).

A gated hindcast never gives a source known to be available only after the
as-of date an ``[S<n>]`` id or a stored page: late search rows are skipped
before registration (render slots filled window-first), a search whose rows
were all late says that is not evidence, URL-dated-late fetches are refused
without budget, and late or (under ``drop``) undated pages are withheld before
storage, with the verdict persisted as the ledger row's ``pit_status``.
Without a policy every text is the pre-TIME-8 text.  Also covers the
production tools factory's env contract and one offline engine run.  Zero
network, zero LLM.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import types

import pytest

import test_research_engine_v3 as v3

# The shared fixtures (hermetic env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
rg = v3.rg

NOW = dt.datetime(2026, 9, 30, 12, 0, tzinfo=dt.timezone.utc)
AS_OF = dt.date(2024, 6, 1)
BODY = ("Grid connection queues exceed forty months in several regions according to the operators. "
        "Operators reported substantial capital expenditure across the first half of the period. "
        "The agency expects demand growth to continue while grid approvals remain the binding constraint.")
UNDATED_PAGE = f"# Grid connection report\n\n{BODY}"
_PIT_ENV = ("RESEARCH_PIT_GATES", "RESEARCH_PIT_SAME_DAY", "RESEARCH_PIT_UNDATED",
            "RESEARCH_PIT_PROVIDER_BOUNDS", "RESEARCH_PIT_OVERFETCH", "RESEARCH_SOURCE_DATES",
            "RESEARCH_SOURCE_DATE_TEXT_FALLBACK", "RESEARCH_AS_OF")


@pytest.fixture(autouse=True)
def _pit_env(monkeypatch):
    for name in _PIT_ENV:
        monkeypatch.delenv(name, raising=False)


def dated_page(*lines: str) -> str:
    head = "\n".join(lines)
    return f"# Grid connection report\n\n{head}\n\n{BODY}"


def policy(**overrides) -> rg.PitPolicy:
    return rg.PitPolicy(as_of=AS_OF, **overrides)


def make_tools(tmp_path, *, pit=None, search_fn=None, fetch_fn=None, name="t"):
    ledger = rg.SourceLedger(tmp_path / name / "sources_ledger.json")
    tools = rg.ResearchTools(ledger, tmp_path / name / "pages", search_fn=search_fn or (lambda q, n: "{}"),
                             fetch_fn=fetch_fn or (lambda url: UNDATED_PAGE), clock=lambda: NOW, pit=pit)
    return tools, ledger


def hit(i: int, path: str = "", **dates) -> dict:
    return {"title": f"Hit {i}", "url": f"https://site{i}.example/{path or f'page-{i}'}",
            "content": f"snippet {i}", **dates}


def searcher(*rows, calls=None):
    def search(query, n):
        if calls is not None:
            calls.append(n)
        return json.dumps({"query": query, "results": list(rows)})
    return search


class CountingFetch:
    def __init__(self, result):
        self.result = result
        self.urls: list[str] = []

    def __call__(self, url):
        self.urls.append(url)
        return self.result


def entry_titles(text: str) -> list[str]:
    return [line.split(" — ", 1)[0] for line in text.split("\n") if line.startswith("[S")]


def pages_on_disk(tools) -> list:
    return sorted(tools.pages_dir.iterdir())


# =============================================================== policy + ledger

def test_pit_policy_validates_its_fields(tmp_path):
    assert policy() == rg.PitPolicy(as_of=AS_OF, same_day="exclude", undated="drop", provider_bounds=True,
                                    overfetch=1)
    for bad in ({"same_day": "maybe"}, {"undated": "keep"}, {"overfetch": 0}, {"overfetch": 5},
                {"overfetch": 2.0}, {"overfetch": True}, {"provider_bounds": "yes"}):
        with pytest.raises(ValueError):
            policy(**bad)
    for as_of in ("2024-06-01", dt.datetime(2024, 6, 1), None):
        with pytest.raises(ValueError):
            rg.PitPolicy(as_of=as_of)
    with pytest.raises(TypeError):
        rg.ResearchTools(rg.SourceLedger(tmp_path / "l.json"), tmp_path / "pages", pit={"as_of": AS_OF})


def test_set_pit_sticks_except_unverifiable_to_admitted_and_survives_a_reload(tmp_path):
    path = tmp_path / "l.json"
    ledger = rg.SourceLedger(path)
    late = ledger.register("https://a.example/x", "A")["sid"]
    flagged = ledger.register("https://b.example/y", "B")["sid"]
    assert ledger.set_pit(late, "late")["pit_status"] == "late"
    # A recorded withhold is never re-admitted.
    for status in ("admitted", "same_day", "unverifiable", "undated_withheld"):
        assert ledger.set_pit(late, status)["pit_status"] == "late"
    assert ledger.set_pit(flagged, "unverifiable")["pit_status"] == "unverifiable"
    assert ledger.set_pit(flagged, "late")["pit_status"] == "unverifiable"
    assert ledger.set_pit(flagged, "admitted")["pit_status"] == "admitted"
    assert ledger.set_pit(flagged, "unverifiable")["pit_status"] == "admitted"
    assert ledger.set_pit(99, "late") is None
    with pytest.raises(ValueError):
        ledger.set_pit(late, "maybe")
    ledger.flush()
    reloaded = rg.SourceLedger(path)
    assert (reloaded.get(late)["pit_status"], reloaded.get(flagged)["pit_status"]) == ("late", "admitted")


def test_tools_without_a_policy_have_no_gates(tmp_path):
    tools, _ledger = make_tools(tmp_path)
    assert tools.pit is None and "pit" not in tools.stats()
    gated, _ledger = make_tools(tmp_path, pit=policy(), name="g")
    # A gated run always records source dates (the gates read them).
    assert gated.source_dates is True
    assert gated.stats()["pit"] == dict.fromkeys(rg.PIT_COUNTERS, 0)


# =============================================================== search gate

LATE_HITS = {
    0: {"published": "2024-06-01"},                        # the as-of day itself: late under exclude
    2: {"publishedDate": "2024-07-02"},
    4: {"date": "Q3 2024"},
    5: {"path": "2024/06/15/story"},                       # URL path date
    7: {"date": "3 days ago"},                             # relative to the 2026 clock
    8: {"published_date": "2025"},
    10: {"published": "2024-05-20", "date": "2024-06-02"},  # the latest date field counts
    11: {"date": "June 2024"},                             # a month counts as its last day
    13: {"published": "2024-06-01T23:30:00-05:00"},         # 2024-06-02 in UTC
    14: {"published": "2027-01-01"},                       # after today: after any as-of
}
IN_WINDOW_HITS = {
    1: {"published": "2024-05-01"},
    3: {"publishedDate": "2024-03"},
    6: {"date": "Q1 2024"},
    9: {"path": "2024/05/31/story"},
    12: {"published": "2023"},
}


def fifteen_hits() -> list[dict]:
    rows = []
    for i in range(15):
        spec = dict(LATE_HITS.get(i) or IN_WINDOW_HITS[i])
        rows.append(hit(i, spec.pop("path", ""), **spec))
    return rows


def test_late_rows_never_get_an_id_and_slots_fill_window_first(tmp_path):
    calls: list[int] = []
    tools, ledger = make_tools(tmp_path, pit=policy(overfetch=3), search_fn=searcher(*fifteen_hits(), calls=calls))

    text = tools.search("grid queues", agent_id="k1")

    assert calls == [15]  # SEARCH_RESULTS_PER_QUERY x overfetch
    assert entry_titles(text) == ["[S1] Hit 1", "[S2] Hit 3", "[S3] Hit 6", "[S4] Hit 9", "[S5] Hit 12"]
    in_window = {f"https://site{i}.example/{spec.get('path', f'page-{i}')}" for i, spec in IN_WINDOW_HITS.items()}
    assert {row["url"] for row in ledger.rows()} == in_window
    assert not any(f"site{i}.example" in text for i in LATE_HITS)
    pit = tools.stats()["pit"]
    # Rows 0..12 were read before the five slots filled: 8 of them were late.
    assert (pit["search_late_dropped"], pit["search_undated_shown"], pit["no_in_window_results"]) == (8, 0, 0)
    assert (pit["searches_bounded"], pit["searches_unbounded"]) == (0, 1)
    assert tools.outcome_counts()["search_ok"] == 1


def test_all_late_rows_answer_that_absence_is_not_evidence(tmp_path):
    rows = [hit(0, published="2024-07-01"), hit(1, "2025/01/02/x"), hit(2, date="H2 2024")]
    calls: list[int] = []
    tools, ledger = make_tools(tmp_path, pit=policy(), search_fn=searcher(*rows, calls=calls))

    text = tools.search("grid queues", agent_id="k1")

    assert text == ("NO_IN_WINDOW_RESULTS: 3 results were dated after the as-of date; this is not evidence "
                    "that nothing happened. Rephrase, or search primary sources and archives.")
    assert "not evidence" in text and len(ledger) == 0
    # Cacheable and counted as an empty search, like NO_RESULTS.
    assert tools.search("grid queues", agent_id="k2") == f"{rg._CACHED_SEARCH_NOTE}\n{text}"
    assert calls == [5]
    assert tools.outcome_counts()["search_no_result"] == 1
    assert tools.stats()["failures"] == 0
    assert tools.stats()["pit"]["no_in_window_results"] == 1

    single, _ledger = make_tools(tmp_path, pit=policy(), search_fn=searcher(hit(0, published="2025")), name="one")
    assert single.search("grid queues", agent_id="k1").startswith(
        "NO_IN_WINDOW_RESULTS: 1 result was dated after the as-of date; this is not evidence")


def test_an_empty_search_under_the_gates_keeps_its_no_results_text(tmp_path):
    tools, _ledger = make_tools(tmp_path, pit=policy(), search_fn=searcher())
    assert tools.search("grid queues", agent_id="k1") == rg.MSG_NO_RESULTS
    assert tools.stats()["pit"]["no_in_window_results"] == 0


def test_undated_and_same_day_rows_are_labelled(tmp_path):
    rows = [hit(0), hit(1, published="2024-05-01"), hit(2, published="2024-06-01")]
    tools, ledger = make_tools(tmp_path, pit=policy(same_day="include"), search_fn=searcher(*rows))

    lines = [line for line in tools.search("grid queues", agent_id="k1").split("\n") if line.startswith("[S")]

    assert lines[0] == "[S1] Hit 0 — site0.example (tier 3) — undated"
    assert lines[1] == "[S2] Hit 1 — site1.example (tier 3) — published 2024-05-01"
    assert lines[2] == "[S3] Hit 2 — site2.example (tier 3) — published 2024-06-01 — same-day"
    assert tools.stats()["pit"]["search_undated_shown"] == 1
    # Search rows carry no pit_status (the fetch decides it).
    assert all("pit_status" not in row for row in ledger.rows())

    strict, _ledger = make_tools(tmp_path, pit=policy(), search_fn=searcher(*rows), name="strict")
    assert entry_titles(strict.search("grid queues", agent_id="k1")) == ["[S1] Hit 0", "[S2] Hit 1"]


def test_a_source_the_ledger_knows_as_late_stays_out_of_later_searches(tmp_path):
    tools, ledger = make_tools(tmp_path, pit=policy(), search_fn=searcher(hit(0), hit(1)))
    sid = ledger.register("https://site0.example/page-0", "Hit 0")["sid"]
    ledger.set_pit(sid, "late")
    assert entry_titles(tools.search("grid queues", agent_id="k1")) == ["[S2] Hit 1"]


def test_search_as_of_reaches_only_a_bounded_gated_search(tmp_path):
    calls = []

    def bounded(query, max_results, as_of=None):
        calls.append((max_results, as_of))
        return json.dumps({"results": [hit(len(calls), published="2024-01-02")],
                           "date_bound": "provider" if as_of else "unsupported"})

    live, _ledger = make_tools(tmp_path, search_fn=bounded, name="live")
    live.search("q one", agent_id="a")
    gated, _ledger = make_tools(tmp_path, pit=policy(overfetch=2), search_fn=bounded, name="gated")
    gated.search("q one", agent_id="a")
    unbounded, _ledger = make_tools(tmp_path, pit=policy(provider_bounds=False), search_fn=bounded, name="nb")
    unbounded.search("q one", agent_id="a")
    assert calls == [(5, None), (10, "2024-06-01"), (5, None)]
    assert (gated.stats()["pit"]["searches_bounded"], gated.stats()["pit"]["searches_unbounded"]) == (1, 0)
    assert (unbounded.stats()["pit"]["searches_bounded"], unbounded.stats()["pit"]["searches_unbounded"]) == (0, 1)

    seen = []
    kwargs_fn = lambda query, n, **kw: seen.append(kw) or json.dumps({"results": []})  # noqa: E731
    tools, _ledger = make_tools(tmp_path, pit=policy(), search_fn=kwargs_fn, name="kw")
    tools.search("q two", agent_id="a")
    assert seen == [{"as_of": "2024-06-01"}]

    # A search function without an as_of parameter is called as before (no TypeError).
    plain_calls: list[int] = []
    plain, _ledger = make_tools(tmp_path, pit=policy(), search_fn=searcher(hit(0), calls=plain_calls), name="p")
    assert entry_titles(plain.search("q three", agent_id="a")) == ["[S1] Hit 0"]
    assert plain_calls == [5]


def test_default_search_fn_forwards_as_of_only_when_given(monkeypatch):
    calls = []

    def impl(query, max_results=10, revisit_reason="", as_of=None):
        calls.append((query, max_results, revisit_reason, as_of))
        return "{}"

    monkeypatch.setattr(rg.importlib, "import_module", lambda name: types.SimpleNamespace(web_search_impl=impl))
    rg._default_search_fn("q", 5)
    rg._default_search_fn("q", 15, as_of="2024-06-01")
    assert calls == [("q", 5, rg._ENGINE_REVISIT_REASON, None), ("q", 15, rg._ENGINE_REVISIT_REASON, "2024-06-01")]

    # A deployed search_tools without the parameter searches unbounded instead of failing.
    old = []
    monkeypatch.setattr(rg.importlib, "import_module", lambda name: types.SimpleNamespace(
        web_search_impl=lambda query, max_results=10, revisit_reason="": old.append(max_results) or "{}"))
    assert rg._default_search_fn("q", 15, as_of="2024-06-01") == "{}" and old == [15]


# =============================================================== fetch gate

def test_a_url_dated_late_is_refused_before_any_budget(tmp_path):
    fetch = CountingFetch(UNDATED_PAGE)
    tools, ledger = make_tools(tmp_path, pit=policy(), fetch_fn=fetch)
    before = (tools.stats(), tools.outcome_counts())

    url = "https://news.example/2024/06/15/story"
    assert tools.fetch(url, agent_id="k1") == rg.MSG_OUT_OF_WINDOW
    assert tools.fetch(url, agent_id="k1") == rg.MSG_OUT_OF_WINDOW

    assert fetch.urls == [] and len(ledger) == 0 and pages_on_disk(tools) == []
    after = tools.stats()
    assert {key: value for key, value in after.items() if key != "pit"} == {
        key: value for key, value in before[0].items() if key != "pit"}
    assert tools.outcome_counts() == before[1]
    assert after["pit"]["fetch_prefetch_refused"] == 2
    # A path date before the as-of is fetched as usual.
    assert tools.fetch("https://news.example/2024/05/15/story", agent_id="k1").startswith("[S1] ")
    assert fetch.urls == ["https://news.example/2024/05/15/story"]


def test_a_page_updated_after_as_of_is_withheld_and_stays_withheld(tmp_path):
    fetch = CountingFetch(dated_page("Published: 2024-05-01", "Updated: 2024-07-15"))
    tools, ledger = make_tools(tmp_path, pit=policy(), search_fn=searcher(hit(0)), fetch_fn=fetch)
    assert entry_titles(tools.search("grid queues", agent_id="k1")) == ["[S1] Hit 0"]
    url = "https://site0.example/page-0"

    assert tools.fetch(url, agent_id="k1") == rg.MSG_FETCH_WITHHELD_LATE
    assert tools.fetch(url, agent_id="k2") == rg.MSG_FETCH_WITHHELD_LATE  # remembered, never retried

    assert fetch.urls == [url]
    assert pages_on_disk(tools) == []
    row = ledger.get(1)
    assert (row["fetched"], row["page_path"], row["pit_status"]) == (False, None, "late")
    stats = tools.stats()
    # The reserved unit stays spent; a withhold is no fetch failure.
    assert (stats["fetches"], stats["failures"]) == (1, 0)
    outcomes = tools.outcome_counts()
    assert (outcomes["fetch_ok"], outcomes["fetch_content"], outcomes["fetch_unavailable"]) == (0, 0, 0)
    assert {key: stats["pit"][key] for key in ("fetch_late_withheld", "fetch_units_spent_withheld",
                                               "fetch_prefetch_refused")} == {
        "fetch_late_withheld": 1, "fetch_units_spent_withheld": 1, "fetch_prefetch_refused": 1}

    ledger.flush()
    reloaded = rg.SourceLedger(ledger.path)
    assert reloaded.get(1)["pit_status"] == "late" and reloaded.get(1)["fetched"] is False
    # A resumed run refuses it from the ledger without a fetch.
    resumed = rg.ResearchTools(reloaded, tmp_path / "t" / "pages", search_fn=searcher(hit(0)), fetch_fn=fetch,
                               clock=lambda: NOW, pit=policy())
    assert resumed.fetch(url, agent_id="k1") == rg.MSG_OUT_OF_WINDOW_SOURCE
    assert fetch.urls == [url] and resumed.stats()["fetches"] == 0
    # ... and never shows it in a search again.
    assert resumed.search("grid queues", agent_id="k1").startswith("NO_IN_WINDOW_RESULTS: 1 result was")


def test_a_modified_date_in_fetch_metadata_makes_a_page_late(tmp_path):
    fetch = CountingFetch((UNDATED_PAGE, {"article:published_time": "2024-04-01",
                                          "article:modified_time": "2024-06-20T08:00:00Z"}))
    tools, _ledger = make_tools(tmp_path, pit=policy(), fetch_fn=fetch)
    assert tools.fetch("https://a.example/story", agent_id="k1") == rg.MSG_FETCH_WITHHELD_LATE
    admitted = CountingFetch((UNDATED_PAGE, {"article:published_time": "2024-04-01"}))
    tools, ledger = make_tools(tmp_path, pit=policy(), fetch_fn=admitted, name="ok")
    assert tools.fetch("https://a.example/story", agent_id="k1").startswith(
        "[S1] Grid connection report — a.example (tier 3) — published 2024-04-01 — full page")
    assert ledger.get(1)["pit_status"] == "admitted"


def test_a_late_page_first_seen_by_fetch_gets_no_row(tmp_path):
    tools, ledger = make_tools(tmp_path, pit=policy(), fetch_fn=CountingFetch(dated_page("Published: 2024-08-01")))
    assert tools.fetch("https://a.example/story", agent_id="k1") == rg.MSG_FETCH_WITHHELD_LATE
    assert len(ledger) == 0 and pages_on_disk(tools) == []


def test_undated_pages_are_withheld_under_drop_and_flagged_under_flag(tmp_path):
    url = "https://site0.example/page-0"
    dropped, ledger = make_tools(tmp_path, pit=policy(), search_fn=searcher(hit(0)),
                                 fetch_fn=CountingFetch(UNDATED_PAGE), name="drop")
    dropped.search("grid queues", agent_id="k1")
    assert dropped.fetch(url, agent_id="k1") == rg.MSG_FETCH_WITHHELD_UNDATED
    assert pages_on_disk(dropped) == [] and ledger.get(1)["fetched"] is False
    assert ledger.get(1)["pit_status"] == "undated_withheld"
    assert dropped.stats()["pit"]["fetch_undated_withheld"] == 1
    assert dropped.stats()["pit"]["fetch_units_spent_withheld"] == 1
    ledger.flush()
    resumed = rg.ResearchTools(rg.SourceLedger(ledger.path), tmp_path / "drop" / "pages",
                               fetch_fn=CountingFetch(UNDATED_PAGE), clock=lambda: NOW, pit=policy())
    assert resumed.fetch(url, agent_id="k1") == rg.MSG_FETCH_WITHHELD_UNDATED
    assert resumed.stats()["fetches"] == 0

    flagged, ledger = make_tools(tmp_path, pit=policy(undated="flag"), search_fn=searcher(hit(0)),
                                 fetch_fn=CountingFetch(UNDATED_PAGE), name="flag")
    flagged.search("grid queues", agent_id="k1")
    text = flagged.fetch(url, agent_id="k1")
    assert text.split("\n", 1)[0].startswith("[S1] Grid connection report — site0.example (tier 3) — undated — ")
    row = ledger.get(1)
    assert (row["fetched"], row["pit_status"]) == (True, "unverifiable")
    assert len(pages_on_disk(flagged)) == 1
    assert flagged.stats()["pit"]["fetch_undated_admitted"] == 1
    # The stored copy keeps its label.
    assert flagged.fetch(url, agent_id="k1").split("\n", 1)[0].startswith(
        "[S1] Grid connection report — site0.example (tier 3) — undated — ")


def test_admitted_and_same_day_pages_are_stored_with_their_status(tmp_path):
    tools, ledger = make_tools(tmp_path, pit=policy(), fetch_fn=CountingFetch(dated_page("Published: 2024-05-01")))
    text = tools.fetch("https://a.example/story", agent_id="k1")
    assert text.split("\n", 1)[0].startswith(
        "[S1] Grid connection report — a.example (tier 3) — published 2024-05-01 — full page")
    assert ledger.get(1)["pit_status"] == "admitted" and ledger.get(1)["fetched"] is True
    assert tools.stats()["pit"]["fetch_admitted"] == 1

    include, ledger = make_tools(tmp_path, pit=policy(same_day="include"),
                                 fetch_fn=CountingFetch(dated_page("Published: 2024-06-01")), name="inc")
    text = include.fetch("https://a.example/story", agent_id="k1")
    assert text.split("\n", 1)[0].startswith(
        "[S1] Grid connection report — a.example (tier 3) — published 2024-06-01 — same-day — full page")
    assert ledger.get(1)["pit_status"] == "same_day"
    assert include.stats()["pit"]["fetch_same_day"] == 1

    exclude, ledger = make_tools(tmp_path, pit=policy(), fetch_fn=CountingFetch(dated_page("Published: 2024-06-01")),
                                 name="exc")
    assert exclude.fetch("https://a.example/story", agent_id="k1") == rg.MSG_FETCH_WITHHELD_LATE


def test_a_fetch_failure_is_still_a_failure_under_the_gates(tmp_path):
    tools, _ledger = make_tools(tmp_path, pit=policy(), fetch_fn=CountingFetch("Error: timed out"))
    assert tools.fetch("https://a.example/story", agent_id="k1").startswith("FETCH_FAILED(timed_out)")
    assert tools.stats()["failures"] == 1
    assert tools.stats()["pit"]["fetch_units_spent_withheld"] == 0


def test_unreadable_dates_are_undated_not_admitted(tmp_path, monkeypatch):
    monkeypatch.setattr(rg, "_source_dates", lambda: None)
    tools, _ledger = make_tools(tmp_path, pit=policy(), search_fn=searcher(hit(0, published="2025-01-01")),
                                fetch_fn=CountingFetch(dated_page("Published: 2025-01-01")))
    # Without the dating module nothing can be verified: labelled at search, withheld at fetch.
    assert tools.search("grid queues", agent_id="k1").split("\n", 1)[0].endswith(" — undated")
    assert tools.fetch("https://site0.example/page-0", agent_id="k1") == rg.MSG_FETCH_WITHHELD_UNDATED


# =============================================================== no policy: unchanged

def test_without_a_policy_search_and_fetch_texts_are_unchanged(tmp_path):
    calls = []

    def search(query, max_results, as_of=None):
        calls.append((max_results, as_of))
        return json.dumps({"results": [hit(0, "2024/07/01/story", published="2025-01-01"), hit(1)]})

    fetch = CountingFetch(dated_page("Published: 2025-01-01", "Updated: 2025-02-01"))
    tools, ledger = make_tools(tmp_path, search_fn=search, fetch_fn=fetch)

    text = tools.search("grid queues", agent_id="k1")
    assert text == ("[S1] Hit 0 — site0.example (tier 3)\n    https://site0.example/2024/07/01/story\n"
                    "    snippet 0\n"
                    "[S2] Hit 1 — site1.example (tier 3)\n    https://site1.example/page-1\n    snippet 1")
    assert calls == [(5, None)]
    page = tools.fetch("https://site0.example/2024/07/01/story", agent_id="k1")
    total = len(fetch.result.strip())
    assert page.split("\n", 1)[0] == f"[S1] Grid connection report — site0.example (tier 3) — full page ({total} chars)."
    assert "FETCH_WITHHELD" not in page and "OUT_OF_WINDOW" not in page
    assert all("pit_status" not in row for row in ledger.rows())
    assert "pit" not in tools.stats() and len(pages_on_disk(tools)) == 1


# =============================================================== production factory + engine

@pytest.mark.parametrize("env, expected", [
    ({}, None),
    ({"RESEARCH_PIT_GATES": "true"}, None),                                   # no hindcast
    ({"RESEARCH_AS_OF": "2024-06-01"}, None),                                 # hindcast without gates
    ({"RESEARCH_AS_OF": "2024-06-01", "RESEARCH_PIT_GATES": "false"}, None),
    ({"RESEARCH_AS_OF": "2024-06-01", "RESEARCH_PIT_GATES": "true"},
     rg.PitPolicy(as_of=dt.date(2024, 6, 1))),
    ({"RESEARCH_AS_OF": "2024-06-01", "RESEARCH_PIT_GATES": "true", "RESEARCH_PIT_SAME_DAY": "include",
      "RESEARCH_PIT_UNDATED": "flag", "RESEARCH_PIT_PROVIDER_BOUNDS": "false", "RESEARCH_PIT_OVERFETCH": "3"},
     rg.PitPolicy(as_of=dt.date(2024, 6, 1), same_day="include", undated="flag", provider_bounds=False,
                  overfetch=3)),
    # Unknown text reads strict; the over-fetch is clamped.
    ({"RESEARCH_AS_OF": "2024-06-01", "RESEARCH_PIT_GATES": "1", "RESEARCH_PIT_SAME_DAY": "yes",
      "RESEARCH_PIT_UNDATED": "keep", "RESEARCH_PIT_OVERFETCH": "9"},
     rg.PitPolicy(as_of=dt.date(2024, 6, 1), overfetch=4)),
    ({"RESEARCH_AS_OF": "2024-06-01", "RESEARCH_PIT_GATES": "true", "RESEARCH_PIT_OVERFETCH": "lots"},
     rg.PitPolicy(as_of=dt.date(2024, 6, 1))),
])
def test_pit_policy_from_the_child_env(env, expected):
    assert lr._pit_policy(env) == expected


def test_pit_policy_needs_a_past_as_of(monkeypatch):
    monkeypatch.setattr(lr, "_utc_date", lambda: "2026-10-01")
    assert lr._pit_policy({"RESEARCH_AS_OF": "2026-10-01", "RESEARCH_PIT_GATES": "true"}) is None
    assert lr._pit_policy({"RESEARCH_AS_OF": "2024-6-1", "RESEARCH_PIT_GATES": "true"}) is None


def test_default_tools_factory_passes_the_policy_and_forces_source_dates(monkeypatch, tmp_path):
    recorded = {}

    def fake_tools(*args, **kwargs):
        recorded.clear()
        recorded.update(kwargs)
        return types.SimpleNamespace()

    monkeypatch.setattr(rg, "ResearchTools", fake_tools)
    monkeypatch.setenv("RESEARCH_AS_OF", "2024-06-01")
    lr._default_tools_factory(None, tmp_path, None, None, rg.ToolLimits())
    assert (recorded["pit"], recorded["source_dates"]) == (None, False)
    monkeypatch.setenv("RESEARCH_PIT_GATES", "true")
    monkeypatch.setenv("RESEARCH_PIT_UNDATED", "flag")
    lr._default_tools_factory(None, tmp_path, None, None, rg.ToolLimits())
    assert recorded["pit"] == rg.PitPolicy(as_of=dt.date(2024, 6, 1), undated="flag")
    assert recorded["source_dates"] is True and recorded["vintage_as_of"] == "2024-06-01"
    # A live run never gets gates, whatever the ambient env says.
    monkeypatch.delenv("RESEARCH_AS_OF")
    lr._default_tools_factory(None, tmp_path, None, None, rg.ToolLimits())
    assert (recorded["pit"], recorded["source_dates"]) == (None, False)


def _dated_search(query: str, n: int) -> str:
    """Per query: an undated row (the one the scripted agents fetch), one dated
    after the as-of by its URL path and one dated before it."""
    rows = json.loads(v3.fake_search(query, n))["results"]
    rows[1]["url"] = rows[1]["url"].replace("/data/", "/2024/07/01/")
    rows[2]["published"] = "2024-04-15"
    return json.dumps({"query": query, "results": rows})


def _engine_run(root, bridge, monkeypatch, *, gated: bool):
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")
    monkeypatch.setattr(lr, "_utc_date", lambda: "2026-10-01")
    monkeypatch.setenv("RESEARCH_AS_OF", "2024-06-01")
    if gated:
        monkeypatch.setenv("RESEARCH_PIT_GATES", "true")
        monkeypatch.setenv("RESEARCH_PIT_UNDATED", "flag")
    out = root / "out"
    out.mkdir(parents=True, exist_ok=True)
    model = v3.ScriptedModel(v3.World())
    plog = v3.FakePlog()
    meta = {"status": "running", "question": "q", "research_engine": "v3"}

    def write_meta():
        (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    def gateway_factory(args, plog_arg, bridge_arg, preset):
        return rg.ModelGateway(model, plog_arg, max_concurrency=preset.workers, budget_units=preset.budget_units,
                               reserve_share=lr.RESERVE_SHARE, sleep=lambda seconds: None)

    def tools_factory(ledger, pages_dir, bridge_arg, plog_arg, limits):
        # Built like production (_default_tools_factory), with offline search/fetch.
        return rg.ResearchTools(ledger, pages_dir, search_fn=_dated_search, fetch_fn=v3.page_text,
                                bridge=bridge_arg, plog=plog_arg, limits=limits,
                                vintage_as_of=lr._hindcast_as_of(os.environ), pit=lr._pit_policy(os.environ))

    question = "Will global data-centre capacity exceed 250 GW by the end of 2027?"
    rc = lr.run(question, out, v3.make_args(), meta, plog, write_meta, bridge=bridge,
                gateway_factory=gateway_factory, tools_factory=tools_factory)
    return rc, meta, plog, model, out


def test_gated_engine_run_keeps_late_sources_out_and_records_the_counts(tmp_path, bridge, monkeypatch):
    rc, meta, plog, model, out = _engine_run(tmp_path, bridge, monkeypatch, gated=True)
    assert rc == 0, meta.get("error")

    ledger_rows = json.loads(next(out.rglob("sources_ledger.json")).read_text(encoding="utf-8"))
    sources = json.loads((out / "sources.json").read_text(encoding="utf-8"))
    assert ledger_rows and not any("/2024/07/01/" in row["url"] for row in ledger_rows)
    assert not any("/2024/07/01/" in str(row.get("url")) for row in sources)
    tool_texts = [content for call in model.calls for kind, content in call["messages"] if kind == "tool"]
    assert not any("/2024/07/01/" in text for text in tool_texts)
    assert any(" — undated" in text for text in tool_texts)
    # Source dates are on for the gates although RESEARCH_SOURCE_DATES is unset.
    assert "source_dates" in meta
    pit = meta["tools"]["pit"]
    assert set(pit) == set(rg.PIT_COUNTERS)
    assert pit["search_late_dropped"] > 0 and pit["fetch_undated_admitted"] > 0
    assert pit["fetch_late_withheld"] == pit["fetch_undated_withheld"] == 0
    fetched = [row for row in ledger_rows if row.get("fetched")]
    assert fetched and {row["pit_status"] for row in fetched} <= {"admitted", "unverifiable"}
    assert any("point-in-time gates on (as of 2024-06-01" in message for kind, message in plog.lines
               if kind == "stage")


def test_ungated_hindcast_run_has_no_gates(tmp_path, bridge, monkeypatch):
    rc, meta, plog, model, out = _engine_run(tmp_path, bridge, monkeypatch, gated=False)
    assert rc == 0, meta.get("error")
    assert "pit" not in meta["tools"] and "source_dates" not in meta
    ledger_rows = json.loads(next(out.rglob("sources_ledger.json")).read_text(encoding="utf-8"))
    assert any("/2024/07/01/" in row["url"] for row in ledger_rows)
    assert all("pit_status" not in row for row in ledger_rows)
    assert not any("point-in-time gates" in message for _kind, message in plog.lines)
