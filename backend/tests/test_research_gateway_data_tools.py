"""TIME-12: research gateway plumbing for the official-data tools (deerflow_bridge/research_gateway.py).

Offline: every data function is a fake returning data_tools.DataResult objects (one end-to-end test
drives the real FRED renderer through a fake transport).  Pinned here: an ok result becomes a fetched
S1 ledger row with its provenance, its page stored and verifiable like a fetched page, its answer
headed by a row header linear_research.tool_output_sids reads; run-level dedup (free, singleflight);
separate data budgets with a refund for invalid input; the vendor's absences, failures and malformed
results answered with sentinels that register nothing and never raise or touch the search/fetch
failure accounting; a data URL never adopts or overwrites a web row; and without data_fns the tools'
stats and the ledger are byte-identical to before.  data_tool_schema_list extends
AGENT_TOOLS_SCHEMA without modifying it and imports data_tools only when called.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import datetime as dt
import hashlib
import json
import sys
import threading
from pathlib import Path
from types import MappingProxyType

import pytest

_REPO = Path(__file__).resolve().parents[2]
_BRIDGE = str(_REPO / "deerflow_bridge")
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

import data_tools as dtools  # noqa: E402
import linear_research as lr  # noqa: E402
import research_gateway as rg  # noqa: E402

VINTAGE = "2026-09-30"
CPI_URL = f"https://alfred.stlouisfed.org/series?seid=CPIAUCSL&vintage={VINTAGE}"
CPI_TITLE = f"Consumer Price Index for All Urban Consumers (CPIAUCSL), FRED/ALFRED vintage {VINTAGE}"
CPI_PAGE = (f"FRED/ALFRED: Consumer Price Index (CPIAUCSL) — Index 1982-1984=100, Monthly SA; values as "
            f"published on {VINTAGE}\nLatest: 323.5 (2026-08-01)\n2026-07-01: 322.1\n2026-08-01: 323.5\n")
PRE_TIME12_STATS_KEYS = {"searches", "cached_searches", "fetches", "cached_fetches", "failures", "per_agent"}
DATA_LIMITS = rg.ToolLimits(max_data_total=10, max_data_per_agent=5)


def ok_result(series_id="CPIAUCSL", *, url=CPI_URL, title=CPI_TITLE, page=CPI_PAGE,
              model_text=None, provenance=None, supports=None, facts=None) -> dtools.DataResult:
    return dtools.DataResult(
        status="ok", key=f"fred:{series_id}@{VINTAGE}", url=url, title=title,
        model_text=(page.strip() + "\n[S1] is how the vendor labels a footnote.") if model_text is None
        else model_text,
        page_text=page,
        supports=tuple(supports if supports is not None
                       else (f"CPI ({series_id}), FRED/ALFRED values as published on {VINTAGE}: 323.5 in "
                             "August 2026.",)),
        date=VINTAGE,
        provenance=provenance if provenance is not None else {
            "vendor": "fred", "series_id": series_id, "vintage": VINTAGE, "observation_start": "2016-09-30",
            "observation_end": VINTAGE, "units": "Index 1982-1984=100", "frequency": "Monthly",
            "fetched_at": "2026-09-30T17:00:00Z"},
        facts=tuple(facts if facts is not None else (
            {"series_id": series_id, "metric": "CPI", "value": "323.5", "text": "323.5",
             "observation_date": "2026-08-01", "value_type": "actual", "provenance_kind": "structured"},)))


def failed(status: str, detail: str = "", key: str = "") -> dtools.DataResult:
    return dtools.DataResult(status=status, key=key, url="", title="", model_text=f"FRED: {detail}", page_text="",
                             supports=(), date=None, provenance={}, facts=(), detail=detail)


class DataFn:
    """Records every call; answers from a script (the last item repeats), raising exceptions."""

    def __init__(self, *answers):
        self.calls: list[dict] = []
        self.answers = list(answers) or [ok_result()]
        self._lock = threading.Lock()

    def __call__(self, **kwargs):
        with self._lock:
            self.calls.append(kwargs)
            answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer


def search_payload() -> str:
    return json.dumps({"results": [{"title": f"Result {i}", "url": f"https://source{i}.org/doc{i}",
                                    "content": f"Snippet {i} with 2030 data"} for i in range(1, 4)]})


def web_page(n: int = 1) -> str:
    return f"Article {n}\n\n" + "The grid reached 4.2 GW of storage in 2025. " * 30


def make_tools(tmp_path, *, limits=DATA_LIMITS, name="sources.json", **kwargs):
    ledger = rg.SourceLedger(tmp_path / name)
    tools = rg.ResearchTools(ledger, tmp_path / "pages", search_fn=lambda query, n: search_payload(),
                             fetch_fn=lambda url: web_page(), limits=limits, **kwargs)
    return tools, ledger


def data_stats(**counts) -> dict:
    return {"data_calls": 0, "cached_data": 0, "data_invalid": 0, "data_failures": 0, **counts}


def assert_web_accounting_untouched(tools) -> None:
    stats = tools.stats()
    assert (stats["searches"], stats["fetches"], stats["failures"]) == (0, 0, 0)
    assert (stats["cached_searches"], stats["cached_fetches"], stats["per_agent"]) == (0, 0, {})
    assert set(tools.outcome_counts().values()) == {0}


# ================================================================ an ok result is a citable fetched row

def test_ok_result_registers_a_fetched_s1_data_row_citable_like_a_fetched_page(tmp_path):
    fn = DataFn()
    tools, ledger = make_tools(tmp_path, data_fns={"macro_series": fn})
    text = tools.data("macro_series", {"series": "  cpi\n", "extra": "ignored"}, agent_id="K1")
    assert fn.calls == [{"series": "cpi"}]
    head, body = text.split("\n", 1)
    assert head == f"[S1] {CPI_TITLE} — alfred.stlouisfed.org (tier 1) — official data"
    assert lr._ROW_HEADER_RE.match(head)
    assert lr.tool_output_sids("web_fetch", text) == (1, [1])
    assert lr.tool_output_sids("macro_series", text) == (None, [1])
    assert body.startswith(f"{rg.UNTRUSTED_BEGIN} — official data\n") and body.endswith(
        f"{rg.UNTRUSTED_END} — official data")
    assert "Latest: 323.5 (2026-08-01)" in body
    # The vendor text's own citation-like label cannot cite ledger row 1.
    assert "[page-S1] is how the vendor labels" in body and "\n[S1]" not in body

    stored = CPI_PAGE.strip()
    digest = hashlib.sha256(stored.encode("utf-8")).hexdigest()
    row = ledger.get(1)
    assert {key: row[key] for key in ("sid", "url", "title", "domain", "tier", "via", "fetched", "content_sha256",
                                      "chars", "page_path", "snippet", "first_seen_by")} == {
        "sid": 1, "url": CPI_URL, "title": CPI_TITLE, "domain": "alfred.stlouisfed.org", "tier": "S1",
        "via": "data", "fetched": True, "content_sha256": digest, "chars": len(stored),
        "page_path": f"pages/{digest[:16]}.txt", "snippet": "", "first_seen_by": "K1"}
    result = ok_result()
    assert row["data"] == {**dict(result.provenance), "date": VINTAGE, "supports": list(result.supports),
                           "facts": [dict(fact) for fact in result.facts]}
    # Verifiable like a fetched page: the stored text is the page, and the facts' numbers are on it.
    assert tools.page_text(1) == stored
    assert (tmp_path / "pages" / f"{digest[:16]}.txt").read_text("utf-8") == stored
    page_numbers = lr.page_number_set(tools.page_text(1))
    for sentence in [*result.supports, *(fact["text"] for fact in result.facts)]:
        tokens = lr.fact_number_tokens(sentence)
        assert tokens and set(tokens) <= page_numbers
    # Persisted: a reload keeps the data block and the row.
    ledger.flush()
    reloaded = rg.SourceLedger(tmp_path / "sources.json").get(1)
    assert reloaded == row
    assert tools.stats()["data"] == {**data_stats(data_calls=1), "per_agent": {"K1": data_stats(data_calls=1)}}
    assert_web_accounting_untouched(tools)


def test_a_real_fred_result_flows_through_the_gateway_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(dtools, "_FRED_THROTTLE", dtools._Throttle(0))
    today = dt.date(2026, 9, 30)
    rows = [{"date": f"{2024 + (month - 1) // 12}-{(month - 1) % 12 + 1:02d}-01", "value": f"{300 + month}.5"}
            for month in range(1, 25)]

    def transport(url, params, timeout, headers):
        if url.endswith("/series"):
            return 200, {"seriess": [{"id": "CPIAUCSL", "title": "Consumer Price Index", "units":
                                      "Index 1982-1984=100", "frequency": "Monthly",
                                      "seasonal_adjustment_short": "SA"}]}, ""
        return 200, {"observations": rows}, ""

    class NoCache:
        def get(self, key, max_age_s=None):
            return None

        def put(self, key, payload, ttl_s=None):
            return False

    def macro_series(series):
        return dtools.fred_series(series, as_of=today, pit=today, key="0123456789abcdef0123456789abcdef",
                                  transport=transport, cache=NoCache(),
                                  now=dt.datetime(2026, 9, 30, 17, 0, tzinfo=dt.timezone.utc))

    tools, ledger = make_tools(tmp_path, data_fns={"macro_series": macro_series})
    text = tools.data("macro_series", {"series": "cpi"}, agent_id="K1")
    assert lr.tool_output_sids("web_fetch", text) == (1, [1])
    row = ledger.get(1)
    assert row["url"] == dtools.alfred_url("CPIAUCSL", today) and row["tier"] == "S1" and row["fetched"]
    data = row["data"]
    assert (data["vendor"], data["series_id"], data["vintage"], data["date"]) == ("fred", "CPIAUCSL", VINTAGE, VINTAGE)
    assert data["supports"] and data["facts"] and "fetched_at" in data
    page_numbers = lr.page_number_set(tools.page_text(1))
    assert set(lr.fact_number_tokens(data["facts"][0]["text"])) <= page_numbers
    assert set(lr.fact_number_tokens(data["supports"][0])) <= page_numbers


# ================================================================ run-level dedup, singleflight, budgets

def test_a_repeated_request_is_answered_from_run_memory_without_budget(tmp_path):
    fn = DataFn()
    tools, _ = make_tools(tmp_path, data_fns={"macro_series": fn},
                          limits=rg.ToolLimits(max_data_total=1, max_data_per_agent=1))
    first = tools.data("macro_series", {"series": "cpi"}, agent_id="K1")
    again = tools.data("macro_series", {"series": " CPI "}, agent_id="K2")
    head, body = first.split("\n", 1)
    # The row header stays line 0 (tool_output_sids reads a fetch-shaped answer there).
    assert again == f"{head}\n(cached result; this data request was already made)\n{body}"
    assert lr.tool_output_sids("web_fetch", again) == (1, [1])
    assert len(fn.calls) == 1
    assert tools.stats()["data"] == {**data_stats(data_calls=1, cached_data=1), "per_agent": {
        "K1": data_stats(data_calls=1), "K2": data_stats(cached_data=1)}}


def test_concurrent_identical_requests_reach_the_vendor_once(tmp_path):
    entered, release = threading.Event(), threading.Event()

    def slow(**kwargs):
        entered.set()
        release.wait(5)
        return ok_result()

    calls: list[dict] = []

    def recorded(**kwargs):
        calls.append(kwargs)
        return slow(**kwargs)

    tools, ledger = make_tools(tmp_path, data_fns={"macro_series": recorded})
    answers: list[str] = []

    def ask(agent):
        answers.append(tools.data("macro_series", {"series": "cpi"}, agent_id=agent))

    owner = threading.Thread(target=ask, args=("K1",))
    owner.start()
    assert entered.wait(5)
    followers = [threading.Thread(target=ask, args=(f"K{i}",)) for i in range(2, 5)]
    for thread in followers:
        thread.start()
    release.set()
    for thread in [owner, *followers]:
        thread.join(10)
    assert len(calls) == 1 and len(answers) == 4 and len(ledger) == 1
    assert all(lr.tool_output_sids("web_fetch", answer) == (1, [1]) for answer in answers)
    assert tools.stats()["data"]["data_calls"] == 1 and tools.stats()["data"]["cached_data"] == 3


def test_data_budgets_are_per_agent_and_run_wide_and_default_to_none(tmp_path):
    fn = DataFn()
    tools, _ = make_tools(tmp_path, data_fns={"macro_series": fn},
                          limits=rg.ToolLimits(max_data_total=2, max_data_per_agent=1))
    assert tools.data("macro_series", {"series": "cpi"}, agent_id="K1").startswith("[S1] ")
    assert tools.data("macro_series", {"series": "gdp"}, agent_id="K1") == rg.MSG_DATA_BUDGET
    assert rg.MSG_DATA_BUDGET == "DATA_BUDGET_EXHAUSTED: stop requesting official data; use what you have."
    assert tools.data("macro_series", {"series": "gdp"}, agent_id="K2").startswith("[S1] ")
    assert tools.data("macro_series", {"series": "unrate"}, agent_id="K3") == rg.MSG_DATA_BUDGET
    assert [call["series"] for call in fn.calls] == ["cpi", "gdp"]
    # The web budgets are untouched by data calls, and vice versa.
    assert tools.search("grid storage 2030", agent_id="K1").startswith("[S")
    assert tools.stats()["searches"] == 1 and tools.stats()["data"]["data_calls"] == 2

    none_fn = DataFn()
    default, _ = make_tools(tmp_path / "default", limits=rg.ToolLimits(), data_fns={"macro_series": none_fn})
    assert default.data("macro_series", {"series": "cpi"}, agent_id="K1") == rg.MSG_DATA_BUDGET
    assert none_fn.calls == []


def test_tool_limits_data_caps_default_to_zero_and_reject_negatives():
    limits = rg.ToolLimits()
    assert (limits.max_data_total, limits.max_data_per_agent) == (0, 0)
    for name in ("max_data_total", "max_data_per_agent"):
        with pytest.raises(ValueError, match=name):
            rg.ToolLimits(**{name: -1})


# ================================================================ invalid, absent and failed answers

def test_invalid_input_refunds_the_unit_and_names_the_argument(tmp_path):
    series_fn = DataFn(failed("invalid_input", "'bank of japan rate' is not a FRED series; pass an alias"),
                       ok_result())
    company_fn = DataFn(failed("invalid_input", "'??' is neither a CIK nor a ticker."))
    tools, ledger = make_tools(tmp_path, data_fns={"macro_series": series_fn, "company_filings": company_fn},
                               limits=rg.ToolLimits(max_data_total=1, max_data_per_agent=1))
    assert tools.data("macro_series", {"series": "bank of japan rate"}, agent_id="K1") == (
        "INVALID_SERIES: 'bank of japan rate' is not a FRED series; pass an alias")
    assert tools.data("company_filings", {"company": "??"}, agent_id="K1") == (
        "INVALID_COMPANY: '??' is neither a CIK nor a ticker")
    assert len(ledger) == 0
    assert tools.stats()["data"] == {**data_stats(data_invalid=2), "per_agent": {"K1": data_stats(data_invalid=2)}}
    # Both units were refunded, so the agent's single unit still buys a real answer.
    assert tools.data("macro_series", {"series": "cpi"}, agent_id="K1").startswith("[S1] ")
    assert_web_accounting_untouched(tools)


@pytest.mark.parametrize("status, detail, key, expected", [
    ("no_vintage", "FRED/ALFRED lists no vintage of CPIAUCSL as published on 2020-03-15",
     "fred:CPIAUCSL@2020-03-15",
     "NO_VINTAGE: fred:CPIAUCSL@2020-03-15 had no published value by the vintage date; report it as "
     "unavailable, do not estimate."),
    ("not_found", "FRED has no series XYZ123", "fred:XYZ123@2026-09-30",
     "NOT_FOUND: FRED has no series XYZ123; do not estimate or fabricate."),
    ("not_a_filer", "ZZZZ is not in the SEC ticker map.", "",
     "NOT_A_FILER: ZZZZ is not in the SEC ticker map; do not estimate or fabricate."),
    ("no_xbrl_facts", "us-gaap facts absent (IFRS filers not supported in v1)", "",
     "NO_XBRL_FACTS: us-gaap facts absent (IFRS filers not supported in v1); do not estimate or fabricate."),
])
def test_vendor_absences_answer_sentinels_register_nothing_and_are_remembered(tmp_path, status, detail, key,
                                                                              expected):
    fn = DataFn(failed(status, detail, key))
    tools, ledger = make_tools(tmp_path, data_fns={"macro_series": fn, "company_filings": fn})
    tool, args = (("macro_series", {"series": "XYZ123"}) if status in ("no_vintage", "not_found")
                  else ("company_filings", {"company": "zzzz"}))
    assert tools.data(tool, args, agent_id="K1") == expected
    assert tools.data(tool, args, agent_id="K1") == f"(cached result; this data request was already made)\n{expected}"
    assert len(fn.calls) == 1 and len(ledger) == 0
    assert list((tmp_path / "pages").glob("*.txt")) == []
    assert tools.stats()["data"]["data_calls"] == 1 and tools.stats()["data"]["cached_data"] == 1
    assert tools.stats()["data"]["data_failures"] == 0
    assert_web_accounting_untouched(tools)


def test_no_vintage_without_a_key_names_the_request(tmp_path):
    tools, _ = make_tools(tmp_path, data_fns={"company_filings": DataFn(failed("no_vintage"))})
    assert tools.data("company_filings", {"company": "aapl", "freq": "Quarterly"}, agent_id="K1").startswith(
        "NO_VINTAGE: AAPL quarterly had no published value")


@pytest.mark.parametrize("answer", [RuntimeError("boom api_key=0123456789abcdef0123456789abcdef"),
                                    failed("unavailable", "FRED answered HTTP 503")])
def test_a_service_that_does_not_answer_is_retried_once_then_remembered(tmp_path, answer):
    fn = DataFn(answer)
    tools, ledger = make_tools(tmp_path, data_fns={"macro_series": fn})
    first = tools.data("macro_series", {"series": "cpi"}, agent_id="K1")
    assert first == rg.MSG_DATA_UNAVAILABLE == (
        "DATA_UNAVAILABLE: the official data service did not answer; do not estimate or fabricate the value.")
    assert tools.data("macro_series", {"series": "cpi"}, agent_id="K2") == rg.MSG_DATA_UNAVAILABLE
    remembered = tools.data("macro_series", {"series": "cpi"}, agent_id="K3")
    assert remembered == ("DATA_UNAVAILABLE: this request already failed in this run; the official data service "
                          "did not answer; do not estimate or fabricate the value.")
    assert len(fn.calls) == 2 and len(ledger) == 0
    assert tools.stats()["data"] == {**data_stats(data_calls=2, cached_data=1, data_failures=2), "per_agent": {
        "K1": data_stats(data_calls=1, data_failures=1), "K2": data_stats(data_calls=1, data_failures=1),
        "K3": data_stats(cached_data=1)}}
    # Never a search/fetch failure: _tool_failures derives fetch_failed from stats()["failures"].
    assert_web_accounting_untouched(tools)


def test_a_retry_that_succeeds_forgets_the_failure(tmp_path):
    fn = DataFn(TimeoutError("slow"), ok_result())
    tools, _ = make_tools(tmp_path, data_fns={"macro_series": fn})
    assert tools.data("macro_series", {"series": "cpi"}, agent_id="K1") == rg.MSG_DATA_UNAVAILABLE
    assert tools.data("macro_series", {"series": "cpi"}, agent_id="K1").startswith("[S1] ")
    assert tools.data("macro_series", {"series": "cpi"}, agent_id="K1").split("\n")[1].startswith("(cached result")
    assert len(fn.calls) == 2


@pytest.mark.parametrize("answer, reason", [
    (None, "malformed_result"),
    ({"status": "ok"}, "malformed_result"),
    (dataclasses.replace(ok_result(), status="exploded"), "malformed_result"),
    (dataclasses.replace(ok_result(), page_text="  \n"), "incomplete_result"),
    (dataclasses.replace(ok_result(), url=""), "incomplete_result"),
    (dataclasses.replace(ok_result(), url="not a url"), "invalid_url"),
])
def test_unusable_results_fail_closed_register_nothing_and_are_final(tmp_path, answer, reason):
    fn = DataFn(answer)
    tools, ledger = make_tools(tmp_path, data_fns={"macro_series": fn})
    expected = (f"DATA_UNAVAILABLE({reason}): the answer could not be recorded as a citable source; do not "
                "estimate or fabricate the value.")
    assert tools.data("macro_series", {"series": "cpi"}, agent_id="K1") == expected
    assert tools.data("macro_series", {"series": "cpi"}, agent_id="K1") == expected.replace(
        "): the answer", "): this request already failed in this run; the answer")
    assert len(fn.calls) == 1 and len(ledger) == 0
    assert tools.stats()["data"]["data_failures"] == 1
    assert_web_accounting_untouched(tools)


def test_a_page_that_cannot_be_stored_registers_nothing(tmp_path, monkeypatch):
    def refuse(path, text):
        raise OSError("disk full")

    tools, ledger = make_tools(tmp_path, data_fns={"macro_series": DataFn()})
    monkeypatch.setattr(rg, "_atomic_write_text", refuse)
    assert tools.data("macro_series", {"series": "cpi"}, agent_id="K1") == rg.MSG_DATA_UNAVAILABLE
    assert len(ledger) == 0 and tools.stats()["data"]["data_failures"] == 1


def test_an_internal_error_never_raises(tmp_path, monkeypatch):
    tools, ledger = make_tools(tmp_path, data_fns={"macro_series": DataFn()})

    def broken(*args, **kwargs):
        raise RuntimeError("ledger bug")

    monkeypatch.setattr(ledger, "register", broken)
    assert tools.data("macro_series", {"series": "cpi"}, agent_id="K1") == rg.MSG_DATA_UNAVAILABLE
    assert tools.stats()["data"]["data_failures"] == 1
    assert_web_accounting_untouched(tools)


def test_unknown_tools_and_malformed_calls_never_reach_the_vendor(tmp_path):
    series_fn, company_fn = DataFn(), DataFn(ok_result(url="https://www.sec.gov/cgi-bin/browse-edgar?"
                                                           "action=getcompany&CIK=0000320193&type=10-K&dateb=20260930"))
    tools, _ = make_tools(tmp_path, data_fns={"macro_series": series_fn})
    assert tools.data("company_filings", {"company": "AAPL"}, agent_id="K1") == (
        "UNKNOWN_TOOL: company_filings is not available; the official data tools are macro_series.")
    assert tools.data("web_search\n<x>", {}, agent_id="K1") == (
        "UNKNOWN_TOOL: web_searchx is not available; the official data tools are macro_series.")
    bad_calls = [("cpi", "INVALID_TOOL_CALL: macro_series needs a 'series' string"),
                 ({"series": 5}, "INVALID_TOOL_CALL: macro_series needs"),
                 ({"series": "   "}, "INVALID_TOOL_CALL: macro_series needs"),
                 ({"series": "x" * 101}, "INVALID_TOOL_CALL: 'series' is longer than 100 characters.")]
    for args, expected in bad_calls:
        assert tools.data("macro_series", args, agent_id="K1").startswith(expected)
    assert series_fn.calls == []
    assert tools.stats()["data"] == {**data_stats(data_invalid=4), "per_agent": {"K1": data_stats(data_invalid=4)}}

    both, _ = make_tools(tmp_path / "both", data_fns={"company_filings": company_fn})
    for args in ({"company": "AAPL", "freq": "monthly"}, {"company": "AAPL", "freq": 4}, {"company": True},
                 {"freq": "annual"}):
        assert both.data("company_filings", args, agent_id="K1").startswith("INVALID_TOOL_CALL: ")
    assert company_fn.calls == []
    assert both.data("company_filings", {"company": " aapl ", "freq": " Quarterly "}, agent_id="K1").startswith("[S1] ")
    assert both.data("company_filings", {"company": 320193, "freq": None}, agent_id="K1").startswith("[S1] ")
    assert company_fn.calls == [{"company": "AAPL", "freq": "quarterly"}, {"company": "320193", "freq": "annual"}]


def test_data_fns_are_validated_and_a_none_function_is_a_missing_tool(tmp_path):
    ledger = rg.SourceLedger(tmp_path / "sources.json")
    with pytest.raises(ValueError, match="unknown data tool"):
        rg.ResearchTools(ledger, tmp_path / "pages", data_fns={"web_search": DataFn()})
    with pytest.raises(TypeError, match="callable"):
        rg.ResearchTools(ledger, tmp_path / "pages", data_fns={"macro_series": "fred"})
    tools = rg.ResearchTools(ledger, tmp_path / "pages", data_fns={"macro_series": None})
    assert tools.data("macro_series", {"series": "cpi"}, agent_id="K1") == (
        "UNKNOWN_TOOL: macro_series is not available; this run has no official data tools.")
    assert "data" not in tools.stats()


# ================================================================ a data row never shares a web row's identity

def test_a_data_url_colliding_with_a_web_row_is_refused_and_leaves_the_web_row_untouched(tmp_path):
    fn = DataFn()
    tools, ledger = make_tools(tmp_path, data_fns={"macro_series": fn})
    web = ledger.register(CPI_URL.replace("https://", "http://"), "ALFRED chart page", "a web snippet", "search",
                          "K0")
    assert web["via"] == "search" and web["tier"] == "S3"
    text = tools.data("macro_series", {"series": "cpi"}, agent_id="K1")
    assert text == ("DATA_UNAVAILABLE(collision): the answer could not be recorded as a citable source; do not "
                    "estimate or fabricate the value.")
    assert ledger.rows() == [web] and "data" not in ledger.get(1)
    assert tools.data("macro_series", {"series": "cpi"}, agent_id="K1").startswith(
        "DATA_UNAVAILABLE(collision): this request already failed in this run;")
    assert len(fn.calls) == 1 and tools.stats()["data"]["data_failures"] == 1


def test_a_web_sighting_of_a_data_row_leaves_it_unchanged(tmp_path):
    tools, ledger = make_tools(tmp_path, data_fns={"macro_series": DataFn()})
    tools.data("macro_series", {"series": "cpi"}, agent_id="K1")
    before = ledger.get(1)
    for via in ("search", "fetch"):
        assert ledger.register(CPI_URL, "A web title", "a web snippet", via, "K2", tier="S3") == before
    assert ledger.get(1) == before and len(ledger) == 1
    # The same data URL registered again as data is the same row.
    assert ledger.register(CPI_URL, "Another title", "", "data", "K3", tier="S1") == before


def test_ledger_register_tier_override_applies_only_when_creating(tmp_path):
    ledger = rg.SourceLedger(tmp_path / "sources.json")
    created = ledger.register("https://example.org/a", "A", "", "data", "K1", tier="S1")
    assert (created["tier"], created["via"]) == ("S1", "data")
    web = ledger.register("https://example.org/b", "B", "", "search", "K1")
    assert web["tier"] == "S3"
    assert ledger.register("https://example.org/b", "B", "", "search", "K1", tier="S1")["tier"] == "S3"
    assert ledger.register("https://example.org/c", "C", "", "anything", "K1")["via"] == "search"
    with pytest.raises(ValueError, match="tier"):
        ledger.register("https://example.org/d", tier="S9")
    assert len(ledger) == 3


def test_set_data_stores_plain_json_that_survives_a_reload(tmp_path):
    ledger = rg.SourceLedger(tmp_path / "sources.json")
    sid = ledger.register("https://example.org/a", "A", "", "data", "K1", tier="S1")["sid"]
    row = ledger.set_data(sid, MappingProxyType({"supports": ("one", "two"), "facts": (MappingProxyType({"v": 1}),),
                                                 "nan": float("nan"), "when": dt.date(2026, 9, 30), 7: None}))
    expected = {"supports": ["one", "two"], "facts": [{"v": 1}], "nan": "nan", "when": "2026-09-30", "7": None}
    assert row["data"] == expected
    assert ledger.set_data(99, {}) is None
    with pytest.raises(TypeError):
        ledger.set_data(sid, ["not", "a", "mapping"])
    ledger.flush()
    assert rg.SourceLedger(tmp_path / "sources.json").get(sid)["data"] == expected
    # Only set_data writes the block: a row loaded with anything else in it has none.
    rows = json.loads((tmp_path / "sources.json").read_text("utf-8"))
    rows[0]["data"] = "garbage"
    (tmp_path / "sources.json").write_text(json.dumps(rows), "utf-8")
    assert "data" not in rg.SourceLedger(tmp_path / "sources.json").get(sid)


# ================================================================ without data_fns nothing changes

def _web_session(tools) -> None:
    tools.search("grid storage 2030", agent_id="K1")
    tools.search("grid storage 2030", agent_id="K2")
    tools.fetch("https://source1.org/doc1", focus="storage", agent_id="K1")
    tools.fetch("https://source1.org/doc1", focus="storage", agent_id="K2")
    tools.fetch("not a url", agent_id="K2")


@pytest.mark.parametrize("data_fns", [None, {}, {"macro_series": None, "company_filings": None}])
def test_without_data_fns_stats_and_the_ledger_are_byte_identical(tmp_path, data_fns):
    baseline_dir, probe_dir = tmp_path / "baseline", tmp_path / "probe"
    baseline_dir.mkdir()
    probe_dir.mkdir()
    baseline, baseline_ledger = make_tools(baseline_dir, limits=rg.ToolLimits())
    probe, probe_ledger = make_tools(probe_dir, limits=rg.ToolLimits(), data_fns=data_fns)
    _web_session(baseline)
    _web_session(probe)
    assert probe.data("macro_series", {"series": "cpi"}, agent_id="K1").startswith("UNKNOWN_TOOL: ")
    assert set(probe.stats()) == PRE_TIME12_STATS_KEYS
    assert all(list(counters) == ["searches", "fetches", "cached_searches", "cached_fetches", "failures"]
               for counters in probe.stats()["per_agent"].values())
    assert json.dumps(probe.stats(), sort_keys=False) == json.dumps(baseline.stats(), sort_keys=False)
    assert probe.outcome_counts() == baseline.outcome_counts()
    baseline_ledger.flush()
    probe_ledger.flush()
    assert (probe_dir / "sources.json").read_bytes() == (baseline_dir / "sources.json").read_bytes()
    assert all("data" not in row and row["via"] in ("search", "fetch") for row in probe_ledger.rows())


def test_data_calls_leave_the_web_stats_exactly_as_without_data_tools(tmp_path):
    baseline_dir, probe_dir = tmp_path / "baseline", tmp_path / "probe"
    baseline_dir.mkdir()
    probe_dir.mkdir()
    baseline, _ = make_tools(baseline_dir)
    probe, _ = make_tools(probe_dir, data_fns={"macro_series": DataFn(RuntimeError("down"), ok_result())})
    _web_session(baseline)
    _web_session(probe)
    probe.data("macro_series", {"series": "cpi"}, agent_id="K1")
    probe.data("macro_series", {"series": "cpi"}, agent_id="K3")
    probe.data("macro_series", {"series": "cpi"}, agent_id="K3")
    stats = probe.stats()
    assert stats.pop("data") == {**data_stats(data_calls=2, cached_data=1, data_failures=1), "per_agent": {
        "K1": data_stats(data_calls=1, data_failures=1), "K3": data_stats(data_calls=1, cached_data=1)}}
    assert stats == baseline.stats() and probe.outcome_counts() == baseline.outcome_counts()


# ================================================================ schemas

@pytest.fixture
def fresh_schemas():
    rg._data_tool_schemas.cache_clear()
    yield
    rg._data_tool_schemas.cache_clear()


def test_data_tool_schema_list_extends_a_copy_of_the_agent_tools(fresh_schemas):
    pristine = copy.deepcopy(rg.AGENT_TOOLS_SCHEMA)
    tools = rg.data_tool_schema_list(["sec_edgar", "fred"])
    assert tools is not rg.AGENT_TOOLS_SCHEMA and tools[:2] == rg.AGENT_TOOLS_SCHEMA
    assert [tool["function"]["name"] for tool in tools] == ["web_search", "web_fetch", "macro_series",
                                                            "company_filings"]
    assert rg.data_tool_schema_list(("company_filings", "macro_series")) == tools
    assert rg.data_tool_schema_list(["fred"]) == tools[:3]
    assert rg.data_tool_schema_list("company_filings") == [*tools[:2], tools[3]]
    empty = rg.data_tool_schema_list([])
    assert empty == rg.AGENT_TOOLS_SCHEMA and empty is not rg.AGENT_TOOLS_SCHEMA
    # Fresh copies every call: mutating one never reaches the constant or a later list.
    tools[0]["function"]["name"] = "mutated"
    tools[2]["function"]["description"] = "mutated"
    assert rg.AGENT_TOOLS_SCHEMA == pristine
    again = rg.data_tool_schema_list(["fred", "sec_edgar"])
    assert again is not tools and again[0]["function"]["name"] == "web_search"
    assert again[2]["function"]["description"] != "mutated"
    with pytest.raises(ValueError, match="unknown data tool"):
        rg.data_tool_schema_list(["fred", "bloomberg"])

    macro, company = again[2]["function"], again[3]["function"]
    assert macro["description"] == (
        "Official US/major macro series from FRED as published on the run's vintage date. Use an alias: "
        + ", ".join(sorted(dtools.MACRO_ALIASES)) + " or a FRED series id.")
    assert macro["parameters"] == {"type": "object", "properties": {"series": {
        "type": "string", "description": "A macro alias or a FRED series id."}}, "required": ["series"]}
    assert company["description"] == "Statements of a US SEC filer as filed on or before the as-of date."
    assert company["parameters"]["required"] == ["company"]
    assert company["parameters"]["properties"]["company"]["type"] == "string"
    assert company["parameters"]["properties"]["freq"]["enum"] == ["annual", "quarterly"]
    assert json.loads(json.dumps(again)) == again


def test_without_data_tools_the_macro_description_names_the_raw_id_form(fresh_schemas, monkeypatch):
    real = rg.importlib.import_module

    def no_data_tools(name, *args, **kwargs):
        if name == "data_tools":
            raise ImportError("data_tools is not deployed")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(rg.importlib, "import_module", no_data_tools)
    macro = rg.data_tool_schema_list(["macro_series"])[2]["function"]
    assert macro["description"] == ("Official US/major macro series from FRED as published on the run's vintage "
                                    "date. Use a FRED series id.")


def test_research_gateway_imports_data_tools_only_inside_the_schema_builder():
    tree = ast.parse((_REPO / "deerflow_bridge" / "research_gateway.py").read_text("utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Import):
            assert all(alias.name != "data_tools" for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "data_tools"
    literal_targets = {(call.args[0].value, owner.name) for owner in ast.walk(tree)
                       if isinstance(owner, ast.FunctionDef)
                       for call in ast.walk(owner) if isinstance(call, ast.Call) and call.args
                       and isinstance(call.args[0], ast.Constant) and call.args[0].value == "data_tools"}
    assert literal_targets == {("data_tools", "_data_tool_schemas")}


def test_gateway_statuses_match_the_data_tools_contract():
    gateway = {rg._DATA_OK, rg._DATA_INVALID, rg._DATA_NO_VINTAGE, rg._DATA_UNAVAILABLE, *rg._DATA_ABSENT_STATUSES}
    assert gateway == set(dtools.STATUSES)
    assert set(rg._INVALID_DATA_LABELS) == set(rg.DATA_TOOL_NAMES) == set(rg.DATA_TOOL_VENDORS.values())


def test_normalize_data_args_is_the_call_identity():
    assert rg.normalize_data_args("macro_series", {"series": " Fed\tFunds "}) == ({"series": "Fed Funds"}, "")
    assert rg.normalize_data_args("company_filings", {"company": "brk.b"}) == (
        {"company": "BRK.B", "freq": "annual"}, "")
    assert rg.normalize_data_args("company_filings", {"company": "BRK.B", "freq": ""}) == (
        {"company": "BRK.B", "freq": "annual"}, "")
    assert rg.normalize_data_args("web_fetch", {"url": "x"})[0] is None
    assert rg._data_key("macro_series", {"series": "CPI"}) == rg._data_key("macro_series", {"series": "cpi"})
    assert rg._data_key("company_filings", {"company": "AAPL", "freq": "annual"}) != rg._data_key(
        "company_filings", {"company": "AAPL", "freq": "quarterly"})
