"""Offline tests for deerflow_bridge/backtest_cutoff.py (backtest mode, design §3–§5).

The module is imported by bare name, as the research child imports it.  No network:
the archive lookup and every clock are injected.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BRIDGE_DIR = os.path.join(_REPO_ROOT, "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import backtest_cutoff as bt  # noqa: E402

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _closed_archive_circuit():
    bt.reset_archive_circuit()
    yield
    bt.reset_archive_circuit()


def _policy(tmp_path=None, *, strict=True, archive="wayback", as_of="2024-11-01"):
    audit = str(tmp_path / "audit.jsonl") if tmp_path is not None else ""
    return bt.parse_policy({"as_of": as_of, "strict": strict, "archive": archive, "audit_path": audit})


# ------------------------------------------------------------------ policy

def test_policy_parses_and_round_trips_through_env():
    policy = bt.parse_policy('{"as_of": "2024-11-01", "strict": false, "archive": "off"}')
    assert policy.as_of == date(2024, 11, 1) and policy.strict is False and policy.archive == "off"
    assert policy.cutoff == datetime(2024, 11, 1, 23, 59, 59, tzinfo=timezone.utc)
    assert policy.tag == "backtest:2024-11-01:lenient"
    again = bt.policy_from_env({bt.POLICY_ENV: policy.to_env()})
    assert again == policy


def test_policy_defaults_are_strict_with_the_archive():
    policy = bt.parse_policy({"as_of": "2024-11-01"})
    assert policy.strict is True and policy.archive == "wayback" and policy.audit_path == ""


def test_live_run_has_no_policy():
    assert bt.policy_from_env({}) is None
    assert bt.policy_from_env({bt.POLICY_ENV: "  "}) is None


@pytest.mark.parametrize("raw", [
    "not json", "[]", '{"as_of": "2024/11/01"}', '{"as_of": "2024-02-30"}',
    '{"as_of": "2024-11-01", "strict": "yes"}', '{"as_of": "2024-11-01", "archive": "google-cache"}',
    '{"as_of": "2024-11-01", "audit_path": 3}',
])
def test_invalid_policy_fails_closed(raw):
    with pytest.raises(bt.BacktestPolicyError):
        bt.policy_from_env({bt.POLICY_ENV: raw})


# ------------------------------------------------------------------ dates

@pytest.mark.parametrize("value, expected", [
    ("2024-11-05", (date(2024, 11, 5), date(2024, 11, 5), "day")),
    ("2024-11-05T23:30:00-05:00", (date(2024, 11, 6), date(2024, 11, 6), "day")),
    ("2024-11-05T01:00:00Z", (date(2024, 11, 5), date(2024, 11, 5), "day")),
    ("Tue, 05 Nov 2024 14:00:00 GMT", (date(2024, 11, 5), date(2024, 11, 5), "day")),
    ("Nov 5, 2024", (date(2024, 11, 5), date(2024, 11, 5), "day")),
    ("Oct. 31, 2024", (date(2024, 10, 31), date(2024, 10, 31), "day")),
    ("Sept 3, 2024", (date(2024, 9, 3), date(2024, 9, 3), "day")),
    ("5 November 2024", (date(2024, 11, 5), date(2024, 11, 5), "day")),
    ("2024/11/05", (date(2024, 11, 5), date(2024, 11, 5), "day")),
    ("2024年11月5日", (date(2024, 11, 5), date(2024, 11, 5), "day")),
    ("November 2024", (date(2024, 11, 1), date(2024, 11, 30), "month")),
    ("2024-11", (date(2024, 11, 1), date(2024, 11, 30), "month")),
    ("2024", (date(2024, 1, 1), date(2024, 12, 31), "year")),
    (1730764800, (date(2024, 11, 5), date(2024, 11, 5), "day")),
    (1730764800000, (date(2024, 11, 5), date(2024, 11, 5), "day")),
    ("3 days ago", (date(2026, 10, 17), date(2026, 10, 17), "day")),
    ("an hour ago", (date(2026, 10, 20), date(2026, 10, 20), "day")),
    ("yesterday", (date(2026, 10, 19), date(2026, 10, 19), "day")),
    ("garbage", None), ("", None), (None, None), (True, None), ("2024-13-40", None),
])
def test_parse_date(value, expected):
    assert bt.parse_date(value, now=NOW) == expected


@pytest.mark.parametrize("url, expected", [
    ("https://www.nytimes.com/2024/11/05/us/politics/x.html", (date(2024, 11, 5), "day")),
    ("https://example.com/news/2024-10-31-fed-decision", (date(2024, 10, 31), "day")),
    ("https://example.com/20241031/story", (date(2024, 10, 31), "day")),
    ("https://example.com/2024/11/story", (date(2024, 11, 30), "month")),
    ("https://example.com/p/123456", None),
    ("https://example.com/2024-outlook", None),
])
def test_url_date(url, expected):
    span = bt.url_date(url)
    if expected is None:
        assert span is None
    else:
        assert (span.end, span.precision) == expected and span.basis == "url"


def _span(start, end=None, kind="published", precision="day"):
    return bt.DateSpan(start, end or start, precision, kind, "test")


def test_verdicts():
    policy = _policy()
    assert bt.verdict([], policy) == ("undated", None)
    assert bt.verdict([_span(date(2024, 11, 1))], policy)[0] == "before"  # the as-of day is admissible
    assert bt.verdict([_span(date(2024, 11, 2))], policy)[0] == "after"
    # Published before, modified after: the page may contain the outcome.
    assert bt.verdict([_span(date(2024, 10, 1)), _span(date(2024, 11, 7), kind="modified")], policy)[0] == "after"
    # A month that straddles the cutoff dates nothing.
    assert bt.verdict([_span(date(2024, 11, 1), date(2024, 11, 30), precision="month")], policy)[0] == "undated"
    assert bt.verdict([_span(date(2024, 10, 1), date(2024, 10, 31), precision="month")], policy)[0] == "before"
    # An archive capture decides alone, whatever the live page claims.
    captured = _span(date(2024, 10, 30), kind="captured")
    assert bt.verdict([_span(date(2025, 1, 1), kind="modified"), captured], policy) == ("before", captured)
    assert bt.admits("before", policy) and not bt.admits("undated", policy) and not bt.admits("after", policy)
    assert bt.admits("undated", _policy(strict=False))


# ------------------------------------------------------------------ search

SEARCH_FIXTURE = {
    "query": "2024 election polls",
    "total_results": 7,
    "results": [
        {"title": "Final polls", "url": "https://news.example/a", "content": "…", "date": "Oct 30, 2024"},
        {"title": "Trump wins", "url": "https://news.example/b", "content": "…", "date": "Nov 6, 2024"},
        {"title": "Recent recap", "url": "https://news.example/c", "content": "…", "date": "3 days ago"},
        {"title": "Undated explainer", "url": "https://wiki.example/d", "content": "…"},
        {"title": "Path dated after", "url": "https://blog.example/2024/11/08/results", "content": "…"},
        {"title": "Edited later", "url": "https://site.example/e", "content": "…",
         "published_date": "2024-09-01", "last_updated": "2025-01-10"},
        {"title": "Path dated before", "url": "https://blog.example/2024/10/15/preview", "content": "…"},
    ],
}


def test_strict_search_keeps_only_dated_before_rows(tmp_path):
    policy = _policy(tmp_path)
    out = json.loads(bt.filter_search_payload(json.dumps(SEARCH_FIXTURE), policy, query="q", now=NOW))
    assert [row["title"] for row in out["results"]] == ["Final polls", "Path dated before"]
    assert out["total_results"] == 2
    assert out["backtest"] == {"as_of": "2024-11-01", "strict": True, "kept": 2, "kept_undated": 0,
                               "dropped_after": 4, "dropped_undated": 1}
    assert out["results"][0]["backtest"]["verdict"] == "before"
    assert out["results"][0]["backtest"]["date"] == "2024-10-30"
    assert out["results"][1]["backtest"]["basis"] == "url"
    lines = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert len(lines) == 7 and {line["kind"] for line in lines} == {"search"}
    assert sum(line["action"] == "dropped" for line in lines) == 5


def test_lenient_search_keeps_and_flags_undated_rows():
    policy = _policy(strict=False)
    out = bt.filter_search_payload(SEARCH_FIXTURE, policy, now=NOW)
    titles = [row["title"] for row in out["results"]]
    assert titles == ["Final polls", "Undated explainer", "Path dated before"]
    assert out["results"][1]["backtest"]["verdict"] == "undated"
    assert out["backtest"]["kept_undated"] == 1 and out["backtest"]["dropped_after"] == 4


def test_search_payload_shapes():
    policy = _policy()
    rows = SEARCH_FIXTURE["results"]
    kept = json.loads(bt.filter_search_payload(json.dumps(rows), policy, now=NOW))
    assert isinstance(kept, list) and len(kept) == 2
    error = json.dumps({"error": "firecrawl search HTTP 500", "query": "q"})
    assert bt.filter_search_payload(error, policy) == error
    assert bt.filter_search_payload("not json", policy) == "not json"


def test_firecrawl_date_range():
    assert bt.firecrawl_tbs(_policy()) == "cdr:1,cd_max:11/1/2024"


# ------------------------------------------------------------------ pages

def test_page_dates_read_metadata_not_body_dates():
    page = ("# Election explainer\n\nPublished Time: 2024-10-02T09:00:00Z\n\n"
            '<script type="application/ld+json">{"datePublished": "2024-10-02", '
            '"dateModified": "2024-11-09T10:00:00Z"}</script>\n'
            "The vote is on November 5, 2024 and results follow on November 6, 2024.")
    spans = bt.page_dates(page, now=NOW)
    bases = {span.basis for span in spans}
    assert "page:jsonld.dateModified" in bases and "page:header.published time" in bases
    assert all(span.start != date(2024, 11, 5) for span in spans)  # body dates are about events
    assert bt.verdict(spans, _policy())[0] == "after"


def test_page_byline_and_updated_header():
    assert bt.verdict(bt.page_dates("Markets brace\nBy A. Writer, published Oct 28, 2024\nText", now=NOW),
                      _policy())[0] == "before"
    assert bt.verdict(bt.page_dates("Title\nLast updated: November 12, 2024\nBody", now=NOW),
                      _policy())[0] == "after"
    assert bt.page_dates("A page with no date at all.", now=NOW) == []


# ------------------------------------------------------------------ archive

def _cdx(*rows):
    return json.dumps([["timestamp", "original", "statuscode", "mimetype"], *rows])


def test_wayback_lookup_and_parse():
    policy = _policy()
    url = bt.wayback_lookup_url("https://en.wikipedia.org/wiki/X", policy)
    assert url.startswith(bt.WAYBACK_CDX_URL + "?")
    assert "to=20241101235959" in url and "limit=-1" in url and "filter=statuscode%3A200" in url
    snap = bt.parse_cdx(_cdx(["20241031222855", "https://en.wikipedia.org/wiki/X", "200", "text/html"]), policy)
    assert snap.timestamp == "20241031222855"
    assert snap.url == "https://web.archive.org/web/20241031222855id_/https://en.wikipedia.org/wiki/X"
    assert snap.span().kind == "captured" and snap.span().end == date(2024, 10, 31)
    # A capture after the cutoff is never trusted, whatever the server's bound.
    assert bt.parse_cdx(_cdx(["20241102000001", "https://x.example/", "200", "text/html"]), policy) is None
    assert bt.parse_cdx(_cdx(["20241030000000", "https://x.example/", "404", "text/html"]), policy) is None
    assert bt.parse_cdx("[]", policy) is None and bt.parse_cdx("oops", policy) is None


def test_find_snapshot_uses_the_injected_transport_and_never_raises():
    policy = _policy()
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return _cdx(["20241030120000", "https://x.example/page", "200", "text/html"])

    snap = bt.find_snapshot("https://x.example/page", policy, http_get=fake_get)
    assert snap is not None and len(calls) == 1

    def broken(url, timeout):
        raise OSError("archive down")

    assert bt.find_snapshot("https://x.example/page", policy, http_get=broken) is None
    assert bt.find_snapshot("https://x.example/page", _policy(archive="off"), http_get=fake_get) is None
    assert len(calls) == 1


# ------------------------------------------------------------------ official data

@pytest.mark.parametrize("period, frequency, end", [
    ("2024-10-01", "M", date(2024, 10, 31)), ("2024-07-01", "Q", date(2024, 9, 30)),
    ("2024-01-01", "A", date(2024, 12, 31)), ("2024-10-26", "W", date(2024, 10, 26)),
    ("2024-10-31", "D", date(2024, 10, 31)), ("2024-03-01", "", date(2024, 12, 31)),
])
def test_period_end(period, frequency, end):
    assert bt.period_end(period, frequency) == end


def test_observation_admission_rules():
    strict, lenient = _policy(), _policy(strict=False)
    # September CPI ended 2024-09-30: lenient admits it; strict needs 45 days.
    assert bt.observation_admitted("2024-09-01", "M", lenient, vintage=False)
    assert not bt.observation_admitted("2024-09-01", "M", strict, vintage=False)
    assert bt.observation_admitted("2024-08-01", "M", strict, vintage=False)
    # October ended the day before the as-of day: lenient admits it; the open month never.
    assert bt.observation_admitted("2024-10-01", "M", lenient, vintage=False)
    assert not bt.observation_admitted("2024-11-01", "M", lenient, vintage=False)
    # A projection year is never admitted.
    assert not bt.observation_admitted("2025-01-01", "A", lenient, vintage=False)
    # A vintage value was published by the cutoff; its period only has to have started.
    assert bt.observation_admitted("2024-10-01", "M", strict, vintage=True)
    assert not bt.observation_admitted("2024-11-02", "D", strict, vintage=True)
    assert not bt.observation_admitted("bad", "M", strict, vintage=False)


# ------------------------------------------------------------------ markets

RESOLVED_MARKET = {
    "id": "253591", "question": "Will Donald Trump win the 2024 US Presidential Election?",
    "closed": True, "closedTime": "2024-11-06 15:17:41+00", "startDate": "2024-01-04T22:58:00Z",
    "createdAt": "2024-01-04T17:33:51.332Z", "endDate": "2024-11-05T12:00:00Z",
    "outcomes": '["Yes", "No"]', "outcomePrices": '["1", "0"]', "volume": "1531479284.504353",
    "liquidity": "0", "oneDayPriceChange": "0.41", "bestBid": "0.999", "bestAsk": "1",
    "umaResolutionStatus": "resolved", "clobTokenIds": '["111", "222"]',
}


def test_market_eligibility_at_the_cutoff():
    policy = _policy()
    assert bt.market_open_at_cutoff(RESOLVED_MARKET, policy) == (True, "open_at_cutoff")
    assert bt.market_open_at_cutoff({**RESOLVED_MARKET, "closedTime": "2024-10-15 10:00:00+00"},
                                    policy) == (False, "closed_before_cutoff")
    assert bt.market_open_at_cutoff({**RESOLVED_MARKET, "startDate": "2024-11-03T00:00:00Z", "createdAt": ""},
                                    policy) == (False, "opened_after_cutoff")
    assert bt.market_open_at_cutoff({"id": "x"}, policy) == (False, "undated_market")


def test_price_at_cutoff_takes_the_last_point_before_it():
    policy = _policy()
    cutoff = policy.cutoff_ts
    history = [{"t": cutoff - 7200, "p": 0.6}, {"t": cutoff - 3600, "p": 0.59},
               {"t": cutoff + 60, "p": 0.99}, {"t": "bad", "p": 0.5}]
    assert bt.price_at_cutoff(history, policy) == (0.59, cutoff - 3600)
    assert bt.price_at_cutoff([{"t": cutoff - 8 * 86400, "p": 0.5}], policy) is None  # stale
    assert bt.price_at_cutoff([{"t": cutoff - 60, "p": 1.0}], policy) is None  # settled price
    assert bt.price_history_window(policy, 90) == {"startTs": cutoff - 90 * 86400, "endTs": cutoff}


def test_as_of_market_row_is_an_allow_list():
    policy = _policy()
    row = bt.as_of_market_row(RESOLVED_MARKET, price=0.59, price_ts=policy.cutoff_ts - 3600, policy=policy,
                              matched_query="election", event_title="Presidential Election Winner 2024",
                              event_slug="presidential-election-winner-2024")
    assert row["implied_yes_prob"] == 0.59 and row["price_basis"] == "clob_history_at_cutoff"
    assert row["clob_yes_token_id"] == "111" and row["outcomes"] == ["Yes", "No"]
    assert row["url"] == "https://polymarket.com/event/presidential-election-winner-2024"
    text = json.dumps(row)
    for leaked in ("outcomePrices", "outcome_prices", "closed", "one_day_price_change", "best_bid",
                   "best_ask", "umaResolutionStatus", "2024-11-06"):
        assert leaked not in text


# ------------------------------------------------------------------ audit

def test_audit_summary(tmp_path):
    policy = _policy(tmp_path)
    bt.record(policy, {"kind": "fetch", "action": "dropped", "verdict": "after"})
    bt.record(policy, {"kind": "fetch", "action": "kept", "verdict": "before"})
    bt.record(None, {"kind": "fetch"})  # live runs never write
    summary = bt.summarize_audit(policy.audit_path)
    assert summary == {"fetch": {"action:dropped": 1, "verdict:after": 1, "action:kept": 1, "verdict:before": 1}}
    assert bt.summarize_audit(tmp_path / "missing.jsonl") == {}


def _http_error(code, retry_after=None):
    import email.message
    import urllib.error
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError("https://web.archive.org/cdx", code, "throttled", headers, None)


def test_lookup_statuses_retry_and_circuit():
    policy = _policy()
    capture = _cdx(["20241030120000", "https://x.example/page", "200", "text/html"])
    assert bt.lookup_snapshot("https://x.example/page", policy, http_get=lambda u, t: capture)[1] == "hit"
    assert bt.lookup_snapshot("https://x.example/page", policy, http_get=lambda u, t: _cdx())[1] == "miss"
    assert bt.lookup_snapshot("ftp://x.example/page", policy)[1] == "off"
    assert bt.lookup_snapshot("https://x.example/page", _policy(archive="off"))[1] == "off"
    # A 429 is retried once after its Retry-After (capped at ARCHIVE_RETRY_WAIT_CAP_S).
    answers, waits = [_http_error(429, retry_after=60), capture], []

    def flaky(url, timeout):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    snapshot, status = bt.lookup_snapshot("https://x.example/page", policy, http_get=flaky, sleep=waits.append)
    assert status == "hit" and snapshot is not None and waits == [bt.ARCHIVE_RETRY_WAIT_CAP_S]
    # Two 429s: one retry, then unavailable; a timeout is not retried.
    calls = []

    def throttled(url, timeout):
        calls.append(url)
        raise _http_error(429)

    assert bt.lookup_snapshot("https://x.example/a", policy, http_get=throttled, sleep=lambda s: None)[1] == \
        "unavailable:HTTPError:429"
    assert len(calls) == 2

    def stalled(url, timeout):
        calls.append(url)
        raise TimeoutError()

    assert bt.lookup_snapshot("https://x.example/b", policy, http_get=stalled)[1] == "unavailable:TimeoutError"
    assert len(calls) == 3
    # The third consecutive failure opens the circuit; a success had reset the count before.
    bt.lookup_snapshot("https://x.example/c", policy, http_get=stalled)
    assert bt.lookup_snapshot("https://x.example/d", policy, http_get=stalled) == (None, "circuit_open")
    assert len(calls) == 4
    bt.reset_archive_circuit()
    assert bt.lookup_snapshot("https://x.example/page", policy, http_get=lambda u, t: capture)[1] == "hit"
