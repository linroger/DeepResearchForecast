"""TIME-11: deerflow_bridge/data_tools.py — SEC EDGAR company statements as filed on or before as_of.

Fixtures modelled on TradingAgents 0.5.1 tests/test_sec_edgar.py (Apache-2.0; attribution in
NOTICE): the Apple restatement, filing-date, quarter/year-to-date, tag-fallback, twelve-month and
recast cases, with the accession numbers DRF requires added.

Offline: every request goes to a fake transport that records it.  Pinned here: the as-filed rules
(filed on or before as_of, dates compared as dates, the first (tag, unit) pair owns a period with
its own unit, span and annual-form gates, the latest filing wins) and the fail-closed
post-condition; that no fourth quarter or quarterly cash flow is derived and untagged lines are
explicit; identity, status mapping, cache and throttle; and the rendering (tag, form, filing date
and accession on every page line; numbers DRF's page-number parser verifies).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_BRIDGE = str(_REPO / "deerflow_bridge")
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

import data_tools as dtools  # noqa: E402
import linear_research as lr  # noqa: E402

_MODULE_EDGAR_THROTTLE = dtools._EDGAR_THROTTLE  # before the autouse fixture replaces it

UA = "DRF Research research-desk@example.com"
UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 30, 17, 0, tzinfo=UTC)
TICKER_MAP = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
              "1": {"cik_str": 1067983, "ticker": "BRK-B", "title": "Berkshire Hathaway Inc."}}
# One accession per filing (the 2024 10-K's is the spec's example).
ACCN = {"2008-11-05": "0001193125-08-224958", "2010-01-25": "0001193125-10-012085",
        "2015-10-28": "0001193125-15-356351", "2017-06-15": "0001193125-17-201111",
        "2019-09-30": "0001193125-19-257777", "2022-04-29": "0000320193-22-000059",
        "2024-11-01": "0000320193-24-000123", "2025-02-07": "0001018724-25-000004",
        "2025-02-10": "0001045810-25-000023", "2025-05-02": "0001018724-25-000036",
        "2026-01-29": "0000320193-26-000006"}
# The head of the page SEC serves an address over its request rate (HTTP 403).
RATE_LIMIT_PAGE = ('<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" '
                   '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">\n<html xmlns="http://www.w3.org/1999/xhtml">'
                   "\n<head>\n<title>SEC.gov | Request Rate Threshold Exceeded</title>")
LINE_RE = re.compile(r"^(?P<who>.+?): (?P<label>.+?) \(us-gaap:(?P<tag>\w+)\), (?P<period>.+?), (?P<form>[0-9A-Z/-]+) "
                     r"filed (?P<filed>\d{4}-\d{2}-\d{2}) \(accession (?P<accn>\d{10}-\d{2}-\d{6})\): (?P<value>.+)\.$")


def _fact(end, val, filed, form="10-K", fp="FY", start=None, accn=None):
    fact = {"end": end, "val": val, "filed": filed, "form": form, "fy": int(end[:4]), "fp": fp,
            "accn": accn or ACCN[filed]}
    if start:
        fact["start"] = start
    return fact


FACTS = {
    "cik": 320193,
    "entityName": "Apple Inc.",
    "facts": {"us-gaap": {
        "Assets": {"units": {"USD": [
            _fact("2008-09-27", 39_572_000_000, "2008-11-05"),
            _fact("2008-09-27", 36_171_000_000, "2010-01-25", form="10-K/A"),
            _fact("2022-03-26", 350_662_000_000, "2022-04-29", form="10-Q", fp="Q2"),
            _fact("2024-09-28", 364_980_000_000, "2024-11-01"),
        ]}},
        "Liabilities": {"units": {"USD": [_fact("2024-09-28", 308_030_000_000, "2024-11-01")]}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": [
            _fact("2024-09-28", 6.08, "2024-11-01", start="2023-09-30"),
        ]}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            # One filing reports the quarter and the year to date under one end date.
            _fact("2025-12-31", 81_300_000_000, "2026-01-29", form="10-Q", fp="Q2", start="2025-10-01"),
            _fact("2025-12-31", 158_900_000_000, "2026-01-29", form="10-Q", fp="Q2", start="2025-07-01"),
            _fact("2024-09-28", 391_035_000_000, "2024-11-01", start="2023-09-30"),
        ]}},
    }},
}


@pytest.fixture(autouse=True)
def _offline_vendor(monkeypatch, tmp_path):
    """No throttle waits, and the default cache directory inside tmp_path."""
    monkeypatch.setattr(dtools, "_EDGAR_THROTTLE", dtools._Throttle(0))
    monkeypatch.setenv("DATA_TOOLS_CACHE_DIR", str(tmp_path / "default_cache"))
    for name in ("DATA_EDGAR_CACHE_TTL_H", "DATA_TOOL_TIMEOUT_S"):
        monkeypatch.delenv(name, raising=False)


class NoCache:
    def get(self, key, max_age_s=None):
        return None

    def put(self, key, payload, ttl_s=None):
        return False


class FakeSEC:
    """Records every request; answers the ticker map and companyfacts (a tuple or a callable of the URL)."""

    def __init__(self, facts=None, tickers=None):
        self.calls = []
        self.tickers = tickers if tickers is not None else (200, TICKER_MAP, "")
        self.facts = facts if facts is not None else (200, FACTS, "")

    def __call__(self, url, params, timeout, headers):
        self.calls.append({"url": url, "params": dict(params), "timeout": timeout, "headers": dict(headers)})
        answer = self.tickers if "company_tickers" in url else self.facts
        return answer(url) if callable(answer) else answer

    def urls(self, part):
        return [call["url"] for call in self.calls if part in call["url"]]


def with_facts(us_gaap, cik=320193):
    return FakeSEC(facts=(200, {"cik": cik, "entityName": "Test Filer", "facts": {"us-gaap": us_gaap}}, ""))


def call(transport=None, *, company="AAPL", as_of=dt.date(2024, 11, 15), freq="annual", cache=None, **kwargs):
    """edgar_statements with the test User-Agent; uncached unless a cache is given."""
    return dtools.edgar_statements(company, as_of=as_of, freq=freq, user_agent=UA,
                                   transport=transport if transport is not None else FakeSEC(),
                                   cache=cache if cache is not None else NoCache(), now=kwargs.pop("now", NOW),
                                   **kwargs)


def row(result, label):
    """The cells of one table row (the first table holding ``label``)."""
    line = next(text for text in result.model_text.splitlines() if text.startswith(f"| {label} |"))
    return [cell.strip() for cell in line.strip("|").split("|")[1:]]


def columns(result, table=0):
    headers = [text for text in result.model_text.splitlines() if text.startswith("| Line |")]
    return [cell.strip() for cell in headers[table].strip("|").split("|")[1:]]


def sentences(result, label=None):
    found = [LINE_RE.match(text) for text in result.page_text.splitlines()]
    assert all(found), result.page_text
    return [match for match in found if label is None or match["label"] == label]


def usd_rows(tag_rows):
    return [(tag, {"USD": rows}) for tag, rows in tag_rows]


# ---------------------------------------------------------------------------
# TradingAgents outcomes, reproduced
# ---------------------------------------------------------------------------

def test_a_restated_figure_reads_as_it_did_at_the_time():
    """Apple's 2008 total assets: 39,572 as filed in 2008, 36,171 after the 2010 10-K/A."""
    as_filed = call(as_of=dt.date(2009, 6, 30))
    restated = call(as_of=dt.date(2011, 1, 1))
    assert as_filed.status == restated.status == dtools.STATUS_OK
    assert row(as_filed, "Total assets") == ["39,572"] and "36,171" not in as_filed.model_text + as_filed.page_text
    assert row(restated, "Total assets") == ["36,171"] and "39,572" not in restated.model_text + restated.page_text
    [amended] = sentences(restated, "Total assets")
    assert (amended["form"], amended["filed"], amended["accn"]) == ("10-K/A", "2010-01-25", ACCN["2010-01-25"])


def test_a_period_that_ended_but_was_not_filed_yet_is_not_served():
    """The fiscal year ended 2024-09-28; it reached the public on 2024-11-01."""
    before = call(as_of=dt.date(2024, 10, 15))
    after = call(as_of=dt.date(2024, 11, 15))
    assert "2024-09-28" not in before.model_text + before.page_text
    assert columns(after)[0] == "2024-09-28" and row(after, "Total assets")[0] == "364,980"


def test_the_quarter_is_not_confused_with_the_year_to_date():
    result = call(as_of=dt.date(2026, 6, 1), freq="quarterly")
    assert row(result, "Revenue")[0] == "81,300"
    assert "158,900" not in result.model_text + result.page_text


def test_a_period_reported_under_two_tags_takes_the_preferred_one_never_both():
    rows = usd_rows([("RevenueFromContractWithCustomerExcludingAssessedTax",
                      [_fact("2024-09-28", 999, "2024-11-01", start="2023-09-30")]),
                     ("Revenues", [_fact("2024-09-28", 111, "2024-11-01", start="2023-09-30")])])
    served = dtools._as_filed(rows, dt.date(2026, 1, 1), dtools.SPAN_ANNUAL)
    assert {end: fact.val for end, fact in served.items()} == {dt.date(2024, 9, 28): Decimal(999)}
    assert served[dt.date(2024, 9, 28)].tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
    result = call(with_facts(dict(reversed([(tag, {"units": units}) for tag, units in rows]))),
                  as_of=dt.date(2026, 1, 1))
    assert row(result, "Revenue") == ["0.000999"]  # 999 USD, in millions: never 1,110


def test_older_periods_fall_back_to_the_tag_the_filer_used_then():
    rows = usd_rows([("RevenueFromContractWithCustomerExcludingAssessedTax",
                      [_fact("2024-09-28", 391_035_000_000, "2024-11-01", start="2023-09-30")]),
                     ("Revenues", [_fact("2015-09-26", 233_715_000_000, "2015-10-28", start="2014-09-28")])])
    served = dtools._as_filed(rows, dt.date(2026, 1, 1), dtools.SPAN_ANNUAL)
    assert {end: (fact.val, fact.tag) for end, fact in served.items()} == {
        dt.date(2015, 9, 26): (Decimal(233_715_000_000), "Revenues"),
        dt.date(2024, 9, 28): (Decimal(391_035_000_000), "RevenueFromContractWithCustomerExcludingAssessedTax")}


def test_a_twelve_month_total_from_a_quarterly_report_is_not_a_fiscal_year():
    """Amazon's 10-Qs report trailing twelve months, which pass the annual span gate."""
    transport = with_facts({"NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
        _fact("2024-12-31", 115_000_000_000, "2025-02-07", start="2024-01-01"),
        _fact("2025-03-31", 113_000_000_000, "2025-05-02", form="10-Q", fp="Q1", start="2024-04-01"),
    ]}}}, cik=1018724)
    result = call(transport, company="1018724", as_of=dt.date(2025, 6, 1))
    assert columns(result) == ["2024-12-31"] and row(result, "Operating cash flow") == ["115,000"]


def test_a_quarter_end_balance_is_not_an_annual_column():
    annual = call(as_of=dt.date(2024, 11, 15))
    quarterly = call(as_of=dt.date(2024, 11, 15), freq="quarterly")
    assert "2022-03-26" not in columns(annual) and "2024-09-28" in columns(annual)
    assert "2022-03-26" in columns(quarterly)


def test_a_recast_outside_the_annual_report_counts_from_its_filing_date():
    """A 6-K recast after a split: the annual report decides the column, the latest filing the value."""
    transport = with_facts({"EarningsPerShareDiluted": {"units": {"USD/shares": [
        _fact("2017-03-31", 16.97, "2017-06-15", form="20-F", start="2016-04-01"),
        _fact("2017-03-31", 2.12, "2019-09-30", form="6-K", start="2016-04-01"),
    ]}}}, cik=1577552)
    before = call(transport, company="1577552", as_of=dt.date(2019, 1, 1))
    after = call(transport, company="1577552", as_of=dt.date(2020, 1, 1))
    assert row(before, "Diluted EPS") == ["16.97 USD/shares"]
    assert row(after, "Diluted EPS") == ["2.12 USD/shares"]
    [recast] = sentences(after, "Diluted EPS")
    assert (recast["form"], recast["filed"]) == ("6-K", "2019-09-30")


def test_a_per_share_figure_keeps_its_own_unit():
    result = call(as_of=dt.date(2024, 11, 15))
    assert row(result, "Diluted EPS")[0] == "6.08 USD/shares"
    [eps] = sentences(result, "Diluted EPS")
    assert eps["value"] == "6.08 USD/shares"
    fact = next(item for item in result.facts if item["metric"] == "Diluted EPS")
    assert (fact["value"], fact["unit"]) == ("6.08", "USD/shares")


def test_a_line_the_filer_does_not_tag_reads_not_tagged_in_every_column():
    result = call(as_of=dt.date(2024, 11, 15))
    width = len(columns(result))
    assert width == 2
    for label in ("Stockholders' equity", "Gross profit", "Capex"):
        assert row(result, label) == [dtools.EDGAR_UNTAGGED] * width
    assert row(result, "Total assets") == ["364,980", "36,171"]  # the rest of the statement still returns
    assert all(len(row(result, line.label)) == width for line in dtools.EDGAR_LINES_US_GAAP)


def test_capital_expenditure_is_found_under_either_tag_filers_use():
    transport = with_facts({"PaymentsToAcquireProductiveAssets": {"units": {"USD": [
        _fact("2024-12-31", 70_000_000, "2025-02-10", start="2024-01-01")]}}}, cik=1045810)
    result = call(transport, company="1045810", as_of=dt.date(2025, 3, 1))
    assert row(result, "Capex") == ["70"]
    assert sentences(result, "Capex")[0]["tag"] == "PaymentsToAcquireProductiveAssets"


# ---------------------------------------------------------------------------
# DRF fixes
# ---------------------------------------------------------------------------

def test_a_tag_with_a_second_unit_records_the_unit_of_each_period():
    """TradingAgents applied the last unit to every period of the line."""
    rows = [("Revenues", {"USD": [_fact("2024-09-28", 391_035_000_000, "2024-11-01", start="2023-09-30")],
                          "EUR": [_fact("2024-09-28", 360_000_000_000, "2024-11-01", start="2023-09-30"),
                                  _fact("2015-09-26", 1_000_000_000, "2015-10-28", start="2014-09-28")]})]
    served = dtools._as_filed(rows, dt.date(2026, 1, 1), dtools.SPAN_ANNUAL)
    assert {end: (fact.unit, fact.val) for end, fact in served.items()} == {
        dt.date(2015, 9, 26): ("EUR", Decimal(1_000_000_000)),
        dt.date(2024, 9, 28): ("USD", Decimal(391_035_000_000))}
    result = call(with_facts({tag: {"units": units} for tag, units in rows}), as_of=dt.date(2026, 1, 1))
    assert row(result, "Revenue") == ["391,035", "1,000 million EUR"]
    assert [match["value"] for match in sentences(result, "Revenue")] == [
        "391,035 million USD (391.0 billion USD)", "1,000 million EUR (1.0 billion EUR)"]


@pytest.mark.parametrize("units", [("USD", "CNY"), ("CNY", "USD")])
def test_a_cache_hit_serves_the_unit_the_fetch_served(units, tmp_path):
    """A 20-F filer under US GAAP tags a USD convenience translation next to its reporting currency.
    The cache writes JSON with sorted keys: kept as an object, the units would come back in
    alphabetical order and a hit would hand the period to another unit than the fetch did."""
    values = {"USD": 130_350_000_000, "CNY": 941_168_000_000}
    revenues = {unit: [_fact("2024-03-31", values[unit], "2024-05-23", form="20-F", start="2023-04-01",
                             accn="0001104659-24-000001")] for unit in units}
    transport = with_facts({"Revenues": {"units": revenues}}, cik=1577552)
    cache = dtools._DiskCache(str(tmp_path / "cache"), 3600)
    miss = call(transport, company="1577552", as_of=dt.date(2024, 6, 1), cache=cache)
    hit = call(transport, company="1577552", as_of=dt.date(2024, 6, 1), cache=cache)
    assert len(transport.urls("companyfacts")) == 1 and miss.status == dtools.STATUS_OK
    assert (hit.model_text, hit.page_text, hit.supports, hit.facts) == (
        miss.model_text, miss.page_text, miss.supports, miss.facts)
    [revenue] = [fact for fact in hit.facts if fact["metric"] == "Revenue"]
    assert revenue["unit"] == units[0]  # the filer's first unit owns the period, fetched or cached
    assert row(hit, "Revenue") == (["130,350"] if units[0] == "USD" else ["941,168 million CNY"])
    stored = json.loads(Path(cache.path("edgar|companyfacts|0001577552")).read_text(encoding="utf-8"))
    assert [unit for unit, _ in stored["payload"]["facts"]["Revenues"]] == list(units)


@pytest.mark.parametrize("filed, served_at", [
    ("2024-11-01", dt.date(2024, 11, 1)),
    (" 2024-11-01 ", dt.date(2024, 11, 1)),  # as a string it sorts before "2024-10-15"
    ("20241101", dt.date(2024, 11, 1)),      # date.fromisoformat reads the basic format
    ("2024-11-1", None),
    ("2024/11/01", None),
    ("2024-11-01T00:00:00", None),
    (20241101, None),
    (None, None),
])
def test_a_non_canonical_filed_date_is_parsed_or_skipped_never_string_compared(filed, served_at):
    fact = _fact("2024-09-28", 391_035_000_000, "2024-11-01", start="2023-09-30")
    fact["filed"] = filed
    rows = usd_rows([("Revenues", [fact])])
    assert dtools._as_filed(rows, dt.date(2024, 10, 15), dtools.SPAN_ANNUAL) == {}
    later = dtools._as_filed(rows, dt.date(2030, 1, 1), dtools.SPAN_ANNUAL)
    assert ([fact.filed for fact in later.values()] or [None]) == [served_at]
    result = call(with_facts({"Revenues": {"units": {"USD": [fact]}}}), as_of=dt.date(2024, 10, 15))
    assert result.status == dtools.STATUS_NOT_FOUND


def test_malformed_facts_are_skipped():
    good = _fact("2024-09-28", 391_035_000_000, "2024-11-01", start="2023-09-30")
    bad = [dict(good, val="391035000000"), dict(good, val=True), dict(good, val=float("nan")),
           dict(good, val=10 ** 18), dict(good, val=1e-200), dict(good, val=0.1234567),
           dict(good, accn="320193-24-123"), {k: v for k, v in good.items() if k != "accn"},
           dict(good, form=""), dict(good, start="2025-01-01"), dict(good, start="not a date"), dict(good, end=None),
           "not a fact"]
    assert dtools._as_filed(usd_rows([("Revenues", bad)]), dt.date(2030, 1, 1), dtools.SPAN_ANNUAL) == {}
    assert not dtools._tagged_by(usd_rows([("Revenues", bad)]), dt.date(2030, 1, 1))
    assert list(dtools._as_filed(usd_rows([("Revenues", [*bad, good])]), dt.date(2030, 1, 1),
                                 dtools.SPAN_ANNUAL)) == [dt.date(2024, 9, 28)]


def test_a_value_is_bounded_in_magnitude_and_decimal_places():
    """A number with a 200-digit fixed-point rendering is malformed, not a figure."""
    for value, number in ((6.08, "6.08"), (0.000001, "0.000001"), (-2.123456, "-2.123456"), (1e17, "1E+17"),
                          (10 ** 18 - 1, "999999999999999999"), (0, "0"), (0.0, "0.0")):
        assert dtools._fact_value(value) == Decimal(number), value
    for value in (1e-200, 1.5e-7, 0.1234567, -2.0000001, 10 ** 18, -1e18):
        assert dtools._fact_value(value) is None, value


def test_a_period_ending_after_its_own_filing_is_never_served():
    """A context-date typo (a 10-K filed 2024-11-01 reporting a balance "at" 2204-09-28) passes the
    filing-date gate; a period is filed as an actual only once it has ended, so the fact is skipped."""
    on_the_day = _fact("2024-11-01", 1, "2024-11-01")
    assert dtools._parse_fact(on_the_day, "Assets", "USD").end == dt.date(2024, 11, 1)
    assert dtools._parse_fact(dict(on_the_day, end="2024-11-02"), "Assets", "USD") is None
    typo = _fact("2204-09-28", 36_498_000_000, "2024-11-01")
    transport = with_facts({"Assets": {"units": {"USD": [
        _fact("2023-09-30", 352_583_000_000, "2024-11-01"), _fact("2024-09-28", 364_980_000_000, "2024-11-01"), typo]}},
        "GrossProfit": {"units": {"USD": [dict(typo, start="2203-10-01")]}}})
    for freq in ("annual", "quarterly"):
        result = call(transport, company="320193", as_of=dt.date(2025, 1, 1), freq=freq)
        assert result.status == dtools.STATUS_OK
        assert columns(result) == ["2024-09-28", "2023-09-30"] and row(result, "Total assets") == ["364,980", "352,583"]
        assert "2204" not in result.model_text + result.page_text and "36,498" not in result.model_text
        [assets] = [fact for fact in result.facts if fact["metric"] == "Total assets"]
        assert (assets["observation_date"], assets["value"]) == ("2024-09-28", "364980000000")
        assert row(result, "Gross profit") == [dtools.EDGAR_UNTAGGED] * 2  # its only fact is malformed


@pytest.mark.parametrize("freq", ["annual", "quarterly"])
def test_a_balance_dated_after_the_period_its_filing_reports_is_not_a_column(freq):
    """A 10-K's liquidity, going-concern or debt note tags cash "as of" a date after the fiscal year,
    without a dimension, and companyfacts carries that fact: it is no fiscal-year (or quarter) end."""
    transport = with_facts({
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            _fact("2024-09-28", 391_035_000_000, "2024-11-01", start="2023-09-30"),
            _fact("2023-09-30", 383_285_000_000, "2024-11-01", start="2022-09-25")]}},
        "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
            _fact("2024-09-28", 29_943_000_000, "2024-11-01"), _fact("2023-09-30", 29_965_000_000, "2024-11-01"),
            _fact("2024-10-25", 31_000_000_000, "2024-11-01")]}}})
    result = call(transport, company="320193", as_of=dt.date(2024, 11, 15), freq=freq)
    assert result.status == dtools.STATUS_OK
    assert columns(result) == ["2024-09-28", "2023-09-30"] and row(result, "Cash") == ["29,943", "29,965"]
    assert "2024-10-25" not in result.model_text + result.page_text and "31,000" not in result.model_text
    assert not any("FY end 2024-10-25" in text or "quarter end 2024-10-25" in text for text in result.supports)
    [cash] = [fact for fact in result.facts if fact["metric"] == "Cash"]
    assert (cash["observation_date"], cash["value"]) == ("2024-09-28", "29943000000")
    assert cash["period"] == ("fiscal year end" if freq == "annual" else "quarter end")


def test_one_note_date_per_annual_report_never_displaces_a_fiscal_year(monkeypatch):
    """With a note's later balance date in every 10-K, the columns are still the five fiscal years
    (and six quarters), each with the statement's values."""
    monkeypatch.setattr(dtools, "MODEL_TEXT_MAX_CHARS", 4000)  # the periods are under test, not the cap
    transport = _filer()
    transport.facts[1]["facts"]["us-gaap"]["CashAndCashEquivalentsAtCarryingValue"] = {"units": {"USD": [
        _fact(day, 20_000_000_000 + year, f"{year}-11-04", accn=f"0000999999-{year % 100:02d}-000100")
        for year in range(2019, 2026) for day in (f"{year}-09-30", f"{year}-11-01")]}}
    annual = call(transport, company="999999", as_of=dt.date(2026, 1, 1))
    assert columns(annual) == ["2025-09-30", "2024-09-30", "2023-09-30", "2022-09-30", "2021-09-30"]
    assert dtools._NO_VALUE not in row(annual, "Revenue") and row(annual, "Cash")[0] == "20,000.002025"
    quarterly = call(transport, company="999999", as_of=dt.date(2026, 1, 1), freq="quarterly")
    assert columns(quarterly) == ["2025-09-30", "2025-06-30", "2025-03-31", "2024-12-31", "2024-09-30", "2024-06-30"]
    for result in (annual, quarterly):
        assert "-11-01" not in result.model_text + result.page_text


@pytest.mark.parametrize("freq", ["annual", "quarterly"])
def test_a_balance_dated_inside_the_period_its_filing_reports_is_not_a_column(freq):
    """A debt note tags a balance at an issuance date inside the year, without a dimension: that date
    is no boundary of the 10-K's periods, so it is no fiscal-year (or quarter) column."""
    transport = with_facts({
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            _fact("2024-09-28", 391_035_000_000, "2024-11-01", start="2023-10-01"),
            _fact("2023-09-30", 383_285_000_000, "2024-11-01", start="2022-09-25")]}},
        "LongTermDebt": {"units": {"USD": [
            _fact("2024-09-28", 96_700_000_000, "2024-11-01"), _fact("2023-09-30", 106_000_000_000, "2024-11-01"),
            _fact("2024-05-10", 4_500_000_000, "2024-11-01")]}}})
    result = call(transport, company="320193", as_of=dt.date(2024, 11, 15), freq=freq)
    assert result.status == dtools.STATUS_OK
    assert columns(result) == ["2024-09-28", "2023-09-30"] and row(result, "Long-term debt") == ["96,700", "106,000"]
    assert "2024-05-10" not in result.model_text + result.page_text and "4,500" not in result.model_text
    assert not any("2024-05-10" in text for text in result.supports)
    assert {fact["observation_date"] for fact in result.facts} == {"2024-09-28"}


@pytest.mark.parametrize("freq", ["annual", "quarterly"])
def test_a_stub_after_the_year_in_an_annual_report_moves_no_period_end(freq):
    """A 10-K filed late tags "the two months ended" 2024-11-30 in a subsequent-events note, a quarter
    by its span, with a balance on that date: the fiscal year still ends 2024-09-28, so neither the
    stub nor the balance is a column."""
    k_accn = "0000320193-24-000140"
    transport = with_facts({
        "Revenues": {"units": {"USD": [
            _fact("2024-06-29", 85_777_000_000, "2024-08-02", form="10-Q", start="2024-03-31",
                  accn="0000320193-24-000090"),
            _fact("2024-09-28", 391_035_000_000, "2024-12-20", start="2023-10-01", accn=k_accn),
            _fact("2023-09-30", 383_285_000_000, "2024-12-20", start="2022-09-25", accn=k_accn),
            _fact("2024-11-30", 70_000_000_000, "2024-12-20", start="2024-09-29", accn=k_accn)]}},
        "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
            _fact("2024-09-28", 29_943_000_000, "2024-12-20", accn=k_accn),
            _fact("2024-11-30", 31_000_000_000, "2024-12-20", accn=k_accn)]}}})
    result = call(transport, company="320193", as_of=dt.date(2025, 1, 15), freq=freq)
    assert result.status == dtools.STATUS_OK
    if freq == "annual":
        assert columns(result) == ["2024-09-28", "2023-09-30"] and row(result, "Revenue") == ["391,035", "383,285"]
    else:
        assert columns(result) == ["2024-09-28", "2024-06-29"] and row(result, "Revenue") == ["—", "85,777"]
    assert row(result, "Cash")[0] == "29,943"
    assert "2024-11-30" not in result.model_text + result.page_text and "70,000" not in result.model_text
    assert "31,000" not in result.model_text and not any("2024-11-30" in text for text in result.supports)
    assert "2024-11-30" not in {fact["observation_date"] for fact in result.facts}


def test_a_filings_period_and_its_balance_dates_come_from_its_durations_of_a_quarter_or_more():
    """An annual report's period ends with its latest fiscal year, any other filing's (or an annual
    report's without one) with its latest duration; a subsequent-events note's month to date says
    nothing.  The boundaries are each duration's end and the day before its start.  A filing
    reporting only balances (TradingAgents' Apple 2008 fixture) has no period, so its balances all
    count."""
    k_accn, q_accn, first_accn = ACCN["2024-11-01"], "0000320193-24-000090", "0001234567-24-000001"
    facts = {"NetIncomeLoss": [["USD", [
        _fact("2024-09-28", 1, "2024-11-01", start="2023-10-01"),
        _fact("2023-09-30", 1, "2024-11-01", start="2022-09-25"),
        _fact("2024-10-25", 2, "2024-11-01", start="2024-09-29"),  # 26 days: no period end
        _fact("2024-06-29", 3, "2024-08-02", form="10-Q", start="2024-03-31", accn=q_accn),
        _fact("2024-06-29", 3, "2024-08-02", form="10-Q", start="2023-10-01", accn=q_accn),
        _fact("2024-12-31", 4, "2025-03-28", start="2024-06-15", accn=first_accn),  # a first fiscal year
        _fact("2025-06-28", 5, "2025-08-01", form="10-Q", start="2025-03-30", accn="0000320193-25-000070"),
        _fact("2024-09-28", 6, "2024-11-01", start="2023-10-01", accn="not an accession")]]],
        "Assets": [["USD", [_fact("2024-10-25", 7, "2024-11-01"), _fact("2008-09-27", 8, "2008-11-05")]]]}
    as_of = dt.date(2025, 4, 1)
    periods = dtools._filing_periods(facts, as_of)
    day = dt.date
    assert periods == {  # the 2025 10-Q was filed after as_of
        k_accn: dtools._FilingPeriod(day(2024, 9, 28), frozenset({day(2024, 9, 28), day(2023, 9, 30), day(2022, 9, 24)})),
        q_accn: dtools._FilingPeriod(day(2024, 6, 29), frozenset({day(2024, 6, 29), day(2024, 3, 30), day(2023, 9, 30)})),
        first_accn: dtools._FilingPeriod(day(2024, 12, 31), frozenset({day(2024, 12, 31), day(2024, 6, 14)}))}
    rows = usd_rows([("Assets", [
        _fact("2024-09-28", 10, "2024-11-01"), _fact("2024-10-25", 11, "2024-11-01"),
        _fact("2024-05-10", 12, "2024-11-01"), _fact("2008-09-27", 13, "2008-11-05"),
        _fact("2024-06-29", 14, "2024-08-02", form="10-Q", accn=q_accn),
        _fact("2023-09-30", 15, "2024-08-02", form="10-Q", accn=q_accn),  # the comparative: the year's start - 1
        _fact("2024-05-03", 16, "2024-08-02", form="10-Q", accn=q_accn)])])
    annual = dtools._as_filed(rows, as_of, dtools.SPAN_ANNUAL, periods=periods)
    assert {end: fact.val for end, fact in annual.items()} == {day(2008, 9, 27): 13, day(2024, 9, 28): 10}
    quarterly = dtools._as_filed(rows, as_of, dtools.SPAN_QUARTER, (), periods=periods)
    assert {end: fact.val for end, fact in quarterly.items()} == {
        day(2008, 9, 27): 13, day(2023, 9, 30): 15, day(2024, 6, 29): 14, day(2024, 9, 28): 10}
    unfiltered = dtools._as_filed(rows, as_of, dtools.SPAN_QUARTER, ())  # without the filings' periods
    assert {day(2024, 10, 25), day(2024, 5, 10), day(2024, 5, 3)} <= set(unfiltered)


def test_the_latest_filing_wins_ties_to_the_later_accession():
    first = _fact("2024-09-28", 1_000_000, "2024-11-01", start="2023-09-30", accn="0000320193-24-000123")
    second = dict(first, val=2_000_000, accn="0000320193-24-000124")
    for order in ([first, second], [second, first]):
        served = dtools._as_filed(usd_rows([("Revenues", order)]), dt.date(2025, 1, 1), dtools.SPAN_ANNUAL)
        assert served[dt.date(2024, 9, 28)].accn == "0000320193-24-000124"


def test_a_same_day_amendment_wins_whoever_submitted_either_filing():
    """An accession starts with its submitter's CIK (here a filing agent's for the original and the
    filer's own for the amendment), so the accession order alone would keep the original."""
    original = _fact("2024-09-28", 1_000_000, "2024-11-01", start="2023-10-01", accn="0001193125-24-000200")
    amendment = dict(original, val=2_000_000, form="10-K/A", accn="0000320193-24-000124")
    for order in ([original, amendment], [amendment, original]):
        served = dtools._as_filed(usd_rows([("Revenues", order)]), dt.date(2025, 1, 1), dtools.SPAN_ANNUAL)
        assert (served[dt.date(2024, 9, 28)].form, served[dt.date(2024, 9, 28)].val) == ("10-K/A", 2_000_000)


def test_an_injected_fact_filed_after_as_of_fails_closed(monkeypatch, caplog):
    real = dtools._as_filed

    def leaky(tag_rows, as_of, span, annual_forms=dtools.EDGAR_ANNUAL_FORMS, **kwargs):
        served = real(tag_rows, as_of, span, annual_forms, **kwargs)
        if tag_rows and tag_rows[0][0] == "Assets":
            served[dt.date(2024, 9, 28)] = dtools._FiledValue(
                val=Decimal(1), unit="USD", tag="Assets", form="10-K", filed=as_of + dt.timedelta(days=1),
                accn="0000320193-24-000999", end=dt.date(2024, 9, 28), start=None, span_days=None)
        return served

    monkeypatch.setattr(dtools, "_as_filed", leaky)
    result = call(as_of=dt.date(2024, 11, 15))
    assert result.status == dtools.STATUS_UNAVAILABLE and "post-condition" in result.detail
    assert result.page_text == "" and result.facts == () and result.supports == ()
    assert "post-condition" in caplog.text


def test_a_served_value_without_its_filing_identity_fails_closed(monkeypatch):
    real = dtools._as_filed

    def anonymous(tag_rows, as_of, span, annual_forms=dtools.EDGAR_ANNUAL_FORMS, **kwargs):
        served = real(tag_rows, as_of, span, annual_forms, **kwargs)
        return {end: dtools._FiledValue(**{**fact.__dict__, "accn": ""}) for end, fact in served.items()}

    monkeypatch.setattr(dtools, "_as_filed", anonymous)
    assert call(as_of=dt.date(2024, 11, 15)).status == dtools.STATUS_UNAVAILABLE


def test_an_injected_period_ending_after_its_filing_fails_closed(monkeypatch):
    """Filed by as_of, but of a period that had not ended: the post-condition refuses it too."""
    real = dtools._as_filed

    def future_period(tag_rows, as_of, span, annual_forms=dtools.EDGAR_ANNUAL_FORMS, **kwargs):
        served = real(tag_rows, as_of, span, annual_forms, **kwargs)
        if tag_rows and tag_rows[0][0] == "Assets":
            served[dt.date(2204, 9, 28)] = dtools._FiledValue(
                val=Decimal(1), unit="USD", tag="Assets", form="10-K", filed=dt.date(2024, 11, 1),
                accn="0000320193-24-000123", end=dt.date(2204, 9, 28), start=None, span_days=None)
        return served

    monkeypatch.setattr(dtools, "_as_filed", future_period)
    result = call(as_of=dt.date(2024, 11, 15))
    assert result.status == dtools.STATUS_UNAVAILABLE and "post-condition" in result.detail
    assert "2204" not in result.model_text and result.facts == ()


@pytest.mark.parametrize("answer, status, detail", [
    ((404, None, "Not Found"), dtools.STATUS_NO_XBRL_FACTS, "SEC EDGAR holds no XBRL company facts for CIK 0000320193"),
    ((403, None, "Undeclared Automated Tool"), dtools.STATUS_UNAVAILABLE, "sec_user_agent_rejected"),
    # SEC answers an address over 10 requests a second with 403 too: the User-Agent is not at fault.
    ((403, None, RATE_LIMIT_PAGE), dtools.STATUS_UNAVAILABLE,
     "SEC EDGAR answered HTTP 403 for companyfacts with its rate-limit page (Request Rate Threshold Exceeded): "
     "retry later"),
    ((429, None, ""), dtools.STATUS_UNAVAILABLE, "SEC EDGAR answered HTTP 429 for companyfacts"),
    ((503, None, ""), dtools.STATUS_UNAVAILABLE, "SEC EDGAR answered HTTP 503 for companyfacts"),
    ((500, None, ""), dtools.STATUS_UNAVAILABLE, "SEC EDGAR answered HTTP 500 for companyfacts"),
    ((0, None, "ConnectTimeout"), dtools.STATUS_UNAVAILABLE, "SEC EDGAR is unreachable (ConnectTimeout)"),
    ((200, ["not", "an", "object"], ""), dtools.STATUS_UNAVAILABLE,
     "SEC EDGAR answered companyfacts with a body that is not a JSON object"),
    ((200, {"cik": 320193}, ""), dtools.STATUS_UNAVAILABLE, "SEC EDGAR answered companyfacts without a facts object"),
    ((200, {"cik": 789019, "facts": {"us-gaap": {}}}, ""), dtools.STATUS_UNAVAILABLE,
     "SEC EDGAR answered with the company facts of another CIK"),
    ((200, {"cik": 320193, "facts": {"us-gaap": ["x"]}}, ""), dtools.STATUS_UNAVAILABLE,
     "SEC EDGAR answered with us-gaap facts that are not an object"),
])
def test_companyfacts_status_mapping(answer, status, detail, tmp_path):
    cache = dtools._DiskCache(str(tmp_path / "cache"), 3600)
    transport = FakeSEC(facts=answer)
    result = call(transport, cache=cache)
    assert (result.status, result.detail) == (status, detail)
    assert result.model_text == f"SEC EDGAR: {detail}" and result.page_text == "" and result.date is None
    assert result.key == "edgar:0000320193:annual@2024-11-15" and result.provenance["cik"] == "0000320193"
    call(transport, cache=cache)  # failures are never cached
    assert len(transport.urls("companyfacts")) == 2


@pytest.mark.parametrize("answer, detail", [
    ((403, None, ""), "sec_user_agent_rejected"),
    ((403, None, RATE_LIMIT_PAGE.upper()), "SEC EDGAR answered HTTP 403 for the ticker map with its rate-limit page "
                                           "(Request Rate Threshold Exceeded): retry later"),
    ((404, None, ""), "SEC EDGAR answered HTTP 404 for the ticker map"),
    ((503, None, ""), "SEC EDGAR answered HTTP 503 for the ticker map"),
    ((200, {"0": {"ticker": "AAPL"}}, ""), "SEC EDGAR answered the ticker map without a usable entry"),
    ((200, {}, ""), "SEC EDGAR answered the ticker map without a usable entry"),
])
def test_ticker_map_failures_are_unavailable_never_not_a_filer(answer, detail):
    transport = FakeSEC(tickers=answer)
    result = call(transport)
    assert (result.status, result.detail) == (dtools.STATUS_UNAVAILABLE, detail)
    assert transport.urls("companyfacts") == []


def test_an_unknown_ticker_is_not_a_filer_with_no_facts_request():
    transport = FakeSEC()
    result = call(transport, company="0700.HK")
    assert result.status == dtools.STATUS_NOT_A_FILER and "0700.HK" in result.detail and "CIK" in result.detail
    assert transport.urls("companyfacts") == [] and len(transport.urls("company_tickers")) == 1
    assert result.provenance["identity_basis"] == "sec_current_ticker_map"


@pytest.mark.parametrize("facts", [
    {"ifrs-full": {"Revenue": {"units": {"EUR": [_fact("2024-12-31", 1, "2025-02-10", start="2024-01-01")]}}},
     "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": []}}}},
    {},
    {"us-gaap": {}},
])
def test_a_filer_without_us_gaap_facts_is_no_xbrl_facts(facts):
    result = call(FakeSEC(facts=(200, {"cik": 320193, "facts": facts}, "")))
    assert (result.status, result.detail) == (dtools.STATUS_NO_XBRL_FACTS,
                                              "us-gaap facts absent (IFRS filers not supported in v1)")


def test_nothing_filed_by_as_of_is_not_found():
    result = call(as_of=dt.date(2005, 1, 1))
    assert result.status == dtools.STATUS_NOT_FOUND and "2005-01-01" in result.detail


def test_company_facts_are_fetched_once_for_three_as_of_values(tmp_path):
    cache = dtools._DiskCache(str(tmp_path / "cache"), 3600)
    transport = FakeSEC()
    results = [call(transport, cache=cache, as_of=day)
               for day in (dt.date(2024, 11, 15), dt.date(2025, 1, 15), dt.date(2009, 6, 30))]
    assert [result.status for result in results] == [dtools.STATUS_OK] * 3
    assert len(transport.urls("companyfacts")) == 1 and len(transport.urls("company_tickers")) == 1
    assert row(results[2], "Total assets") == ["39,572"]  # the cached history is still read as of each date
    assert results[0].provenance["fetched_at"] == results[2].provenance["fetched_at"] == "2026-09-30T17:00:00Z"


def test_the_default_cache_lives_in_DATA_TOOLS_CACHE_DIR_and_never_holds_the_user_agent(tmp_path):
    transport = FakeSEC()
    for _ in range(2):
        result = dtools.edgar_statements("AAPL", as_of=dt.date(2024, 11, 15), freq="annual", user_agent=UA,
                                         transport=transport, now=NOW)
        assert result.status == dtools.STATUS_OK
    assert len(transport.calls) == 2  # the ticker map and companyfacts, once each
    files = sorted((tmp_path / "default_cache").glob("*.json"))
    assert len(files) == 2
    for path in files:
        assert "research-desk@example.com" not in path.read_text(encoding="utf-8")
    stored = [json.loads(path.read_text(encoding="utf-8"))["payload"] for path in files]
    facts = next(payload for payload in stored if payload["kind"] == "companyfacts")
    assert set(facts["facts"]) <= set(dtools._EDGAR_TAGS) and facts["entity_name"] == "Apple Inc."
    assert facts["facts"]["Assets"] == [["USD", [{key: value for key, value in fact.items() if key in dtools._FACT_FIELDS}
                                                  for fact in FACTS["facts"]["us-gaap"]["Assets"]["units"]["USD"]]]]
    assert "research-desk@example.com" not in repr(result)


@pytest.mark.parametrize("env, ttl_s", [(None, 86400.0), ("", 86400.0), ("  ", 86400.0), ("1", 3600.0),
                                        ("0", 0.0), ("abc", 86400.0), ("99999", 720 * 3600.0), ("-5", 0.0)])
def test_edgar_cache_ttl_knob(env, ttl_s, monkeypatch):
    if env is not None:
        monkeypatch.setenv("DATA_EDGAR_CACHE_TTL_H", env)
    assert dtools._edgar_ttl_s() == ttl_s


def test_ttl_zero_does_not_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_EDGAR_CACHE_TTL_H", "0")
    cache = dtools._DiskCache(str(tmp_path / "cache"), 3600)
    transport = FakeSEC()
    call(transport, cache=cache)
    call(transport, cache=cache)
    assert len(transport.urls("companyfacts")) == 2


def test_a_lowered_ttl_shortens_entries_already_cached(tmp_path, monkeypatch):
    clock = [1_000_000.0]
    cache = dtools._DiskCache(str(tmp_path / "cache"), 3600, clock=lambda: clock[0])
    transport = FakeSEC()
    call(transport, cache=cache)
    clock[0] += 2 * 3600
    call(transport, cache=cache)
    assert len(transport.urls("companyfacts")) == 1
    monkeypatch.setenv("DATA_EDGAR_CACHE_TTL_H", "1")
    call(transport, cache=cache)
    assert len(transport.urls("companyfacts")) == 2


def _stored_companyfacts(**changes):
    payload = {"status": "ok", "kind": "companyfacts", "cik": "0000320193", "tags": list(dtools._EDGAR_TAGS),
               "fields": list(dtools._FACT_FIELDS), "entity_name": "", "us_gaap_present": True, "facts": {},
               "fetched_at": "2026-09-30T17:00:00Z", **changes}
    return json.dumps({"stored_at": 0, "ttl_s": 3600,
                       "payload": {key: value for key, value in payload.items() if value is not None}})


@pytest.mark.parametrize("stored", [
    '{"stored_at": 1', "[]",
    '{"stored_at": 0, "ttl_s": 3600, "payload": {"status": "ok", "kind": "companyfacts"}}',
    _stored_companyfacts(cik="0000789019"),
    _stored_companyfacts(tags=None, fields=None),  # written before entries recorded their reduction
    _stored_companyfacts(tags=["Assets"]),
    _stored_companyfacts(fields=["end", "val", "filed", "form", "accn"]),
    _stored_companyfacts(facts={"Assets": {"USD": []}}),  # written before units were kept in the filer's order
    _stored_companyfacts(facts={"Assets": [["USD"]]}),
    _stored_companyfacts(facts={"Assets": [["USD", {}]]}),
    _stored_companyfacts(entity_name=None),  # written before entries named the filer
    _stored_companyfacts(entity_name="Apple\nInc."),
])
def test_a_corrupt_or_foreign_cache_entry_is_a_miss(stored, tmp_path):
    cache = dtools._DiskCache(str(tmp_path / "cache"), 3600, clock=lambda: 5.0)
    Path(cache.root).mkdir(parents=True)
    Path(cache.path("edgar|companyfacts|0000320193")).write_text(stored, encoding="utf-8")
    transport = FakeSEC()
    assert call(transport, company="320193", cache=cache).status == dtools.STATUS_OK
    assert len(transport.urls("companyfacts")) == 1


def test_a_well_formed_cache_entry_is_a_hit(tmp_path):
    """The entry the misses above vary, one field each: read without a request."""
    cache = dtools._DiskCache(str(tmp_path / "cache"), 3600, clock=lambda: 5.0)
    Path(cache.root).mkdir(parents=True)
    Path(cache.path("edgar|companyfacts|0000320193")).write_text(_stored_companyfacts(), encoding="utf-8")
    transport = FakeSEC()
    assert call(transport, company="320193", cache=cache).status == dtools.STATUS_NOT_FOUND  # its facts: none
    assert transport.urls("companyfacts") == []
    assets = [["USD", [_fact("2024-09-28", 364_980_000_000, "2024-11-01")]]]
    Path(cache.path("edgar|companyfacts|0000320193")).write_text(
        _stored_companyfacts(entity_name="Apple Inc.", facts={"Assets": assets}), encoding="utf-8")
    result = call(transport, company="320193", cache=cache)
    assert row(result, "Total assets") == ["364,980"] and sentences(result)[0]["who"] == "CIK 0000320193 (Apple Inc.)"
    assert transport.urls("companyfacts") == []


def test_a_snapshot_reduced_to_another_tag_set_is_refetched(tmp_path, monkeypatch):
    """An entry cut to an earlier line table must not read a line or fallback tag added since as untagged."""
    cache = dtools._DiskCache(str(tmp_path / "cache"), 3600)
    transport = FakeSEC()
    with monkeypatch.context() as earlier:
        earlier.setattr(dtools, "_EDGAR_TAGS", tuple(tag for tag in dtools._EDGAR_TAGS if tag != "Assets"))
        cut = call(transport, cache=cache)
        assert row(cut, "Total assets") == [dtools.EDGAR_UNTAGGED] * len(columns(cut))
    assert row(call(transport, cache=cache), "Total assets") == ["364,980", "36,171"]
    assert len(transport.urls("companyfacts")) == 2
    call(transport, cache=cache)  # the refetched entry, cut to the current tags, is reused
    assert len(transport.urls("companyfacts")) == 2


# ---------------------------------------------------------------------------
# Identity and inputs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("user_agent", [None, "", "DRF Research", "DRF research at example.com", 42,
                                        "DRF a@b.com\r\nX-Injected: 1", "DRF réseau@example.com", "x@" + "a" * 250])
def test_a_user_agent_without_a_contact_address_is_invalid_input_with_zero_calls(user_agent):
    transport = FakeSEC()
    result = dtools.edgar_statements("AAPL", as_of=dt.date(2024, 11, 15), freq="annual", user_agent=user_agent,
                                     transport=transport, cache=NoCache(), now=NOW)
    assert result.status == dtools.STATUS_INVALID_INPUT and "'@'" in result.detail
    assert transport.calls == []


def test_every_request_carries_the_user_agent():
    transport = FakeSEC()
    result = dtools.edgar_statements("AAPL", as_of=dt.date(2024, 11, 15), freq="annual", user_agent=f"  {UA} ",
                                     transport=transport, cache=NoCache(), now=NOW)
    assert result.status == dtools.STATUS_OK
    assert [call["url"] for call in transport.calls] == [
        "https://www.sec.gov/files/company_tickers.json",
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"]
    assert all(call["headers"]["User-Agent"] == UA for call in transport.calls)


@pytest.mark.parametrize("company", ["Apple Inc", "", "   ", "ABCDEFGHIJK", "0", "00000", "12345678901", "AAPL?x=1",
                                     "ＡＡＰＬ", "\ufb00", "\ufb01t", "stra\u00dfe", "appl\u0131", 320193, None,
                                     ["AAPL"]])
def test_input_that_is_neither_a_cik_nor_a_ticker_is_invalid_with_zero_calls(company):
    transport = FakeSEC()
    result = call(transport, company=company)
    assert result.status == dtools.STATUS_INVALID_INPUT and transport.calls == []


@pytest.mark.parametrize("as_of, freq", [("2024-13-01", "annual"), (None, "annual"), ("yesterday", "annual"),
                                         (dt.date(2024, 11, 15), "monthly"), (dt.date(2024, 11, 15), None)])
def test_as_of_must_be_a_date_and_freq_annual_or_quarterly(as_of, freq):
    transport = FakeSEC()
    result = call(transport, as_of=as_of, freq=freq)
    assert result.status == dtools.STATUS_INVALID_INPUT and transport.calls == []


def test_a_cik_is_used_as_given_and_zero_padded():
    transport = FakeSEC()
    result = call(transport, company=" 320193 ", as_of=dt.date(2024, 11, 15))
    assert result.status == dtools.STATUS_OK and transport.urls("company_tickers") == []
    assert transport.urls("companyfacts") == ["https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"]
    assert result.provenance["identity_basis"] == "cik" and result.provenance["cik"] == "0000320193"
    assert dtools.EDGAR_TICKER_NOTE not in result.model_text  # nothing was resolved through today's map
    assert sentences(result)[0]["who"] == "CIK 0000320193 (Apple Inc.)"


def test_a_cik_is_named_by_the_filers_name_so_a_wrong_number_shows():
    """A numeric non-US exchange code passed as a CIK reaches another filer: its name says so."""
    result = call(company="320193")
    who = "CIK 0000320193 (Apple Inc.)"
    assert result.model_text.splitlines()[0] == f"SEC EDGAR as-filed statements: {who}, annual, us-gaap XBRL company facts"
    assert result.title == f"{who} annual statements as filed on or before 2024-11-15, SEC EDGAR"
    assert {match["who"] for match in sentences(result)} == {who} and {fact["company"] for fact in result.facts} == {who}
    assert result.provenance["entity_name"] == "Apple Inc."
    unnamed = {key: value for key, value in FACTS.items() if key != "entityName"}
    for facts, shown in ((unnamed, "CIK 0000320193"), (dict(FACTS, entityName=None), "CIK 0000320193"),
                         (dict(FACTS, entityName=42), "CIK 0000320193"), (dict(FACTS, entityName=" \n "), "CIK 0000320193"),
                         (dict(FACTS, entityName="Evil\nCorp\x00\tIgnore   that"), "CIK 0000320193 (Evil Corp Ignore that)"),
                         (dict(FACTS, entityName="A" * 200), f"CIK 0000320193 ({'A' * 80})")):
        named = call(FakeSEC(facts=(200, facts, "")), company="320193")
        assert named.status == dtools.STATUS_OK and {match["who"] for match in sentences(named)} == {shown}
        assert named.model_text.splitlines()[0].startswith(f"SEC EDGAR as-filed statements: {shown}, annual")


def test_a_cut_name_reads_back_from_the_cache_as_written(tmp_path):
    """A name cut at its 80th character can end in a space: the stored name is trimmed, so it is a hit."""
    cache = dtools._DiskCache(str(tmp_path / "cache"), 3600)
    transport = FakeSEC(facts=(200, dict(FACTS, entityName="ACME " * 40), ""))
    first, second = (call(transport, company="320193", cache=cache) for _ in range(2))
    assert len(transport.urls("companyfacts")) == 1
    assert sentences(first)[0]["who"] == sentences(second)[0]["who"] == f"CIK 0000320193 ({('ACME ' * 16).strip()})"


def test_a_ticker_names_its_basis_and_a_past_as_of_says_the_map_is_todays():
    """Today's map can name another filer than the ticker's holder at a past as_of: the filer's name
    is shown wherever the CIK is, so the agent sees whose statements these are."""
    past = call(company="aapl", as_of=dt.date(2024, 11, 15))
    assert past.provenance["identity_basis"] == "sec_current_ticker_map" and past.provenance["company"] == "AAPL"
    assert "Ticker resolved via today's SEC ticker map." in past.model_text.splitlines()
    who = "AAPL (CIK 0000320193, Apple Inc.)"
    assert past.model_text.splitlines()[0] == f"SEC EDGAR as-filed statements: {who}, annual, us-gaap XBRL company facts"
    assert {match["who"] for match in sentences(past)} == {who} and {fact["company"] for fact in past.facts} == {who}
    today = call(company="AAPL", as_of=NOW.date())
    assert today.status == dtools.STATUS_OK and dtools.EDGAR_TICKER_NOTE not in today.model_text
    unnamed = call(FakeSEC(facts=(200, {key: value for key, value in FACTS.items() if key != "entityName"}, "")))
    assert unnamed.status == dtools.STATUS_OK and {match["who"] for match in sentences(unnamed)} == {"AAPL (CIK 0000320193)"}
    assert unnamed.model_text.splitlines()[0].startswith("SEC EDGAR as-filed statements: AAPL (CIK 0000320193), annual")


def test_a_ticker_map_entry_that_is_not_ascii_names_no_ticker():
    """Upper-cased, "\ufb00" would read as FF: the map's own first FF entry would go to its filer."""
    tickers = dtools._parse_ticker_map({"0": {"cik_str": 1, "ticker": "\ufb00"}, "1": {"cik_str": 2, "ticker": "FF"},
                                        "2": {"cik_str": 3, "ticker": "stra\u00dfe"}})
    assert tickers == {"FF": "0000000002"}
    transport = FakeSEC(tickers=(200, {"0": {"cik_str": 320193, "ticker": "\ufb00"}}, ""))
    result = call(transport, company="FF")
    assert (result.status, result.detail) == (dtools.STATUS_UNAVAILABLE,
                                              "SEC EDGAR answered the ticker map without a usable entry")


def test_a_share_class_ticker_resolves_with_a_dot_or_a_hyphen():
    for company in ("BRK.B", "brk-b"):
        transport = FakeSEC(facts=(200, dict(FACTS, cik=1067983), ""))
        result = call(transport, company=company)
        assert result.status == dtools.STATUS_OK
        assert transport.urls("companyfacts") == ["https://data.sec.gov/api/xbrl/companyfacts/CIK0001067983.json"]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _filer(first_year=2019, last_year=2025, last_filed=None):
    """A synthetic filer (fiscal years ending 30 September): each year's 10-K reports the fiscal-year
    durations and balances; three 10-Qs report the quarter and the year to date under one end date
    and cash flow year to date only.  No fourth quarter is reported anywhere."""
    lines = {tag: {} for tag in ("Revenues", "NetIncomeLoss", "EarningsPerShareDiluted", "Assets",
                                 "NetCashProvidedByUsedInOperatingActivities",
                                 "WeightedAverageNumberOfDilutedSharesOutstanding")}

    def add(tag, unit, fact):
        if last_filed is None or fact["filed"] <= last_filed:
            lines[tag].setdefault(unit, []).append(fact)

    for year in range(first_year, last_year + 1):
        fy_start, fy_end = f"{year - 1}-10-01", f"{year}-09-30"
        k_accn = f"0000999999-{year % 100:02d}-000100"
        k_filed = f"{year}-11-04"
        revenue = 100_000_000_000 + year * 1_000_000
        # Quarters of revenue + 1, 2, 3 (million); the fourth quarter would be revenue + 4 million.
        add("Revenues", "USD", _fact(fy_end, revenue * 4 + 10_000_000, k_filed, start=fy_start, accn=k_accn))
        add("NetIncomeLoss", "USD", _fact(fy_end, revenue, k_filed, start=fy_start, accn=k_accn))
        add("EarningsPerShareDiluted", "USD/shares", _fact(fy_end, 6.08, k_filed, start=fy_start, accn=k_accn))
        add("WeightedAverageNumberOfDilutedSharesOutstanding", "shares",
            _fact(fy_end, 15_408_095_000, k_filed, start=fy_start, accn=k_accn))
        add("Assets", "USD", _fact(fy_end, 300_000_000_000 + year, k_filed, accn=k_accn))
        add("NetCashProvidedByUsedInOperatingActivities", "USD",
            _fact(fy_end, 118_000_000_000, k_filed, start=fy_start, accn=k_accn))
        for quarter, (q_start, q_end, q_filed) in enumerate(
                ((f"{year - 1}-10-01", f"{year - 1}-12-31", f"{year}-01-30"),
                 (f"{year}-01-01", f"{year}-03-31", f"{year}-05-01"),
                 (f"{year}-04-01", f"{year}-06-30", f"{year}-07-31")), start=1):
            q_accn = f"0000999999-{int(q_filed[2:4]):02d}-00000{quarter}"
            add("Revenues", "USD", _fact(q_end, revenue + quarter * 1_000_000, q_filed, "10-Q", f"Q{quarter}",
                                         q_start, q_accn))
            if quarter > 1:
                year_to_date = revenue * quarter + sum(range(1, quarter + 1)) * 1_000_000
                add("Revenues", "USD", _fact(q_end, year_to_date, q_filed, "10-Q", f"Q{quarter}", fy_start, q_accn))
            add("NetIncomeLoss", "USD", _fact(q_end, revenue // 4, q_filed, "10-Q", f"Q{quarter}", q_start, q_accn))
            add("Assets", "USD", _fact(q_end, 290_000_000_000 + year * 10 + quarter, q_filed, "10-Q", f"Q{quarter}",
                                       accn=q_accn))
            add("NetCashProvidedByUsedInOperatingActivities", "USD",
                _fact(q_end, 30_000_000_000 * quarter, q_filed, "10-Q", f"Q{quarter}", fy_start, q_accn))
    return with_facts({tag: {"units": units} for tag, units in lines.items()}, cik=999999)


@pytest.mark.parametrize("freq", ["annual", "quarterly"])
@pytest.mark.parametrize("as_of", [dt.date(2023, 11, 3), dt.date(2023, 11, 4), dt.date(2024, 5, 15),
                                   dt.date(2026, 1, 1)])
def test_every_value_was_filed_by_as_of_and_names_its_filing(freq, as_of):
    result = call(_filer(), company="999999", as_of=as_of, freq=freq)
    assert result.status == dtools.STATUS_OK
    matches = sentences(result)
    assert len(matches) == len(result.page_text.splitlines()) == len(result.supports) > 0
    assert list(result.supports) == result.page_text.splitlines()
    for match in matches:
        assert dt.date.fromisoformat(match["filed"]) <= as_of
        assert match["form"] in ("10-K", "10-Q") and match["accn"].startswith("0000999999-")
        line = next(line for line in dtools.EDGAR_LINES_US_GAAP if line.label == match["label"])
        assert match["tag"] in line.tags
    for fact in result.facts:
        assert dt.date.fromisoformat(fact["filed"]) <= as_of
        assert fact["tag"].startswith("us-gaap:") and fact["form"] and dtools._ACCN_RE.fullmatch(fact["accn"])
        assert (fact["value_type"], fact["provenance_kind"], fact["source"]) == ("actual", "structured", "SEC EDGAR")
    assert result.date == max(match["filed"] for match in matches) <= as_of.isoformat()
    latest = re.search(r"Latest filing served: \S+ filed (\d{4}-\d{2}-\d{2})", result.model_text)
    assert latest and latest.group(1) == result.date
    for cell_date in re.findall(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", result.model_text):
        assert cell_date <= as_of.isoformat()


def test_the_10k_filed_on_as_of_counts_and_the_day_before_does_not():
    before = call(_filer(), company="999999", as_of=dt.date(2023, 11, 3))
    on_the_day = call(_filer(), company="999999", as_of=dt.date(2023, 11, 4))
    assert columns(before)[0] == "2022-09-30" and columns(on_the_day)[0] == "2023-09-30"


def test_annual_mode_shows_the_last_five_fiscal_years_latest_first():
    result = call(_filer(), company="999999", as_of=dt.date(2026, 1, 1))
    assert columns(result) == ["2025-09-30", "2024-09-30", "2023-09-30", "2022-09-30", "2021-09-30"]
    assert "Older periods are omitted." not in result.model_text
    assert result.page_text.splitlines()[0].startswith(
        "CIK 0000999999 (Test Filer): Revenue (us-gaap:Revenues), FY ending 2025-09-30")


def test_quarterly_mode_never_derives_a_fourth_quarter_or_a_cash_flow_quarter(monkeypatch):
    # The periods served are under test here, not the cap (test_model_text_is_capped_dropping_the_oldest_
    # periods_first): this filer's seven untagged rows put its six quarters just over MODEL_TEXT_MAX_CHARS.
    monkeypatch.setattr(dtools, "MODEL_TEXT_MAX_CHARS", 4000)
    result = call(_filer(), company="999999", as_of=dt.date(2026, 1, 1), freq="quarterly")
    assert columns(result) == ["2025-09-30", "2025-06-30", "2025-03-31", "2024-12-31", "2024-09-30", "2024-06-30"]
    revenue = row(result, "Revenue")
    assert revenue[0] == "—" and revenue[4] == "—"  # fiscal-year ends: only the balance sheet reports them
    assert revenue[1:4] == ["102,028", "102,027", "102,026"]  # the quarters, never the year to date
    assert row(result, "Total assets")[0] == "300,000.002025"
    # Neither the fourth quarter of FY2025 (FY - nine months: 102,029) nor any year-to-date total is shown.
    for derived in ("102,029", "306,081", "204,053"):
        assert derived not in result.model_text and derived not in result.page_text
    assert all(match["period"] != "quarter ending 2025-09-30" for match in sentences(result))
    assert columns(result, 1) == ["2025-09-30", "2024-09-30", "2023-09-30", "2022-09-30", "2021-09-30"]
    assert row(result, "Operating cash flow")[0] == "118,000"
    assert dtools.EDGAR_CASH_FLOW_NOTE in result.model_text
    cash = sentences(result, "Operating cash flow")
    assert cash and all(match["period"].startswith("FY ending") and match["form"] == "10-K" for match in cash)
    assert "30,000 million USD" not in result.page_text  # the first quarter's cash flow passes the span but is not served


def test_the_annual_mode_prints_no_cash_flow_note():
    result = call(_filer(), company="999999", as_of=dt.date(2026, 1, 1))
    assert dtools.EDGAR_CASH_FLOW_NOTE not in result.model_text
    assert "Fiscal years (columns: fiscal-year end dates, latest first):" in result.model_text


def test_share_counts_keep_their_unit():
    result = call(_filer(), company="999999", as_of=dt.date(2026, 1, 1))
    assert row(result, "Diluted shares")[0] == "15,408,095,000 shares"
    assert sentences(result, "Diluted shares")[0]["value"] == "15,408,095,000 shares (15.4 billion shares)"


def test_a_row_mixing_tags_marks_the_other_tags_cells_and_names_every_tag():
    """LongTermDebt includes the current portion: a change of concept the table must not hide."""
    transport = with_facts({
        "LongTermDebtNoncurrent": {"units": {"USD": [_fact("2024-09-28", 85_750_000_000, "2024-11-01")]}},
        "LongTermDebt": {"units": {"USD": [_fact("2008-09-27", 105_103_000_000, "2008-11-05")]}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            _fact("2024-09-28", 391_035_000_000, "2024-11-01", start="2023-09-30")]}},
        "Revenues": {"units": {"USD": [_fact("2015-09-26", 233_715_000_000, "2015-10-28", start="2014-09-28")]}},
        "SalesRevenueNet": {"units": {"USD": [_fact("2008-09-27", 32_479_000_000, "2008-11-05", start="2007-09-30")]}},
        "Assets": {"units": {"USD": [_fact("2024-09-28", 364_980_000_000, "2024-11-01"),
                                     _fact("2015-09-26", 290_479_000_000, "2015-10-28")]}}})
    result = call(transport, company="320193", as_of=dt.date(2025, 1, 1))
    assert columns(result) == ["2024-09-28", "2015-09-26", "2008-09-27"]
    assert row(result, "Long-term debt") == ["85,750", "—", "105,103†"]
    assert row(result, "Revenue") == ["391,035", "233,715†", "32,479‡"]
    assert row(result, "Total assets") == ["364,980", "290,479", "—"]  # one tag: nothing marked
    legend = result.model_text.splitlines()
    assert ("Long-term debt mixes tags: † = us-gaap:LongTermDebt (includes the current portion); "
            "unmarked = us-gaap:LongTermDebtNoncurrent.") in legend
    assert ("Revenue mixes tags: † = us-gaap:Revenues; ‡ = us-gaap:SalesRevenueNet; "
            "unmarked = us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax.") in legend
    assert not any(text.startswith("Total assets") for text in legend)
    assert "†" not in result.page_text and "‡" not in result.page_text  # each sentence names its own tag
    assert {match["tag"] for match in sentences(result, "Revenue")} == {
        "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"}


def test_a_row_under_one_tag_is_marked_only_when_the_tag_says_more_than_its_label():
    transport = with_facts({"LongTermDebt": {"units": {"USD": [
        _fact("2024-09-28", 106_629_000_000, "2024-11-01"), _fact("2008-09-27", 105_103_000_000, "2008-11-05")]}}})
    result = call(transport, company="320193", as_of=dt.date(2025, 1, 1))
    assert row(result, "Long-term debt") == ["106,629", "105,103"]
    assert "Long-term debt: us-gaap:LongTermDebt (includes the current portion)." in result.model_text.splitlines()
    plain = call(as_of=dt.date(2024, 11, 15))
    assert "mixes tags" not in plain.model_text and "us-gaap:" not in plain.model_text


def test_the_marks_follow_the_shown_columns_and_suffice_for_every_line():
    assert max(len(line.tags) for line in dtools.EDGAR_LINES_US_GAAP) - 1 <= len(dtools._EDGAR_TAG_MARKS)
    line = next(line for line in dtools.EDGAR_LINES_US_GAAP if line.label == "Long-term debt")
    served = dtools._as_filed(usd_rows([("LongTermDebtNoncurrent", [_fact("2024-09-28", 1, "2024-11-01")]),
                                        ("LongTermDebt", [_fact("2008-09-27", 2, "2008-11-05")])]),
                              dt.date(2025, 1, 1), dtools.SPAN_ANNUAL)
    latest, older = dt.date(2024, 9, 28), dt.date(2008, 9, 27)
    assert dtools._row_tags(line, served, [latest, older]) == ("LongTermDebtNoncurrent", {"LongTermDebt": "†"})
    assert dtools._row_tags(line, served, [latest]) == ("LongTermDebtNoncurrent", {})  # the older column is cut
    assert dtools._tag_legend(line, served, [latest]) is None
    assert dtools._row_tags(line, served, []) == (None, {})


def test_the_spec_sentence_and_the_structured_facts():
    result = call(as_of=dt.date(2024, 11, 15))
    assert ("AAPL (CIK 0000320193, Apple Inc.): Revenue (us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax), "
            "FY ending 2024-09-28, 10-K filed 2024-11-01 (accession 0000320193-24-000123): 391,035 million USD "
            "(391.0 billion USD).") in result.page_text.splitlines()
    assert "USD millions; facts filed on or before 2024-11-15, at the values filed then" in result.model_text
    assert result.url == ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193&type=10-K"
                          "&dateb=20241115")
    assert call(as_of=dt.date(2024, 11, 15), freq="quarterly").url.endswith("&type=10-Q&dateb=20241115")
    assert result.key == "edgar:0000320193:annual@2024-11-15" and result.date == "2024-11-01"
    assert result.title == "AAPL (CIK 0000320193, Apple Inc.) annual statements as filed on or before 2024-11-15, SEC EDGAR"
    assert result.provenance == {"vendor": "sec_edgar", "company": "AAPL", "identity_basis": "sec_current_ticker_map",
                                 "freq": "annual", "as_of": "2024-11-15", "cik": "0000320193",
                                 "entity_name": "Apple Inc.", "taxonomy": "us-gaap",
                                 "fetched_at": "2026-09-30T17:00:00Z", "filed": "2024-11-01"}
    by_metric = {fact["metric"]: fact for fact in result.facts}
    assert set(by_metric) == {"Revenue", "Diluted EPS", "Total assets", "Total liabilities"}  # one per served line
    assert by_metric["Revenue"] == {
        "source": "SEC EDGAR", "cik": "0000320193", "company": "AAPL (CIK 0000320193, Apple Inc.)", "metric": "Revenue",
        "value": "391035000000", "unit": "USD", "text": "391,035 million USD (391.0 billion USD)",
        "observation_date": "2024-09-28", "period_start": "2023-09-30", "period": "fiscal year",
        "tag": "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "form": "10-K", "filed": "2024-11-01",
        "accn": "0000320193-24-000123", "url": result.url, "value_type": "actual", "provenance_kind": "structured"}
    assert by_metric["Total assets"]["observation_date"] == "2024-09-28"  # the latest period of the line
    assert by_metric["Total assets"]["period_start"] is None
    assert by_metric["Total assets"]["period"] == "fiscal year end"  # a balance, as its sentence says ("at FY end")
    quarterly = {fact["metric"]: fact for fact in call(as_of=dt.date(2024, 11, 15), freq="quarterly").facts}
    assert quarterly["Total assets"]["period"] == "quarter end"


def test_a_billion_figure_verifies_through_the_page_number_parser():
    available = lr.page_number_set(call(as_of=dt.date(2024, 11, 15)).page_text)
    for fact in ("Apple's fiscal 2024 revenue was $391.0 billion.", "Apple's fiscal 2024 revenue was $391,035 million.",
                 "Diluted EPS was $6.08 in fiscal 2024.", "Total assets were $365.0 billion."):
        assert lr._missing_numbers(fact, lr.fact_number_tokens(fact), available) == [], fact
    wrong = "Apple's fiscal 2024 revenue was $392.0 billion."
    assert lr._missing_numbers(wrong, lr.fact_number_tokens(wrong), available) == ["392"]


def test_supports_follow_the_run_language():
    result = call(as_of=dt.date(2024, 11, 15), language=dtools.CHINESE)
    assert result.page_text.splitlines()[0] == (
        "AAPL (CIK 0000320193, Apple Inc.)：营业收入（us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax），"
        "截至 2024-09-28 的财年，10-K 于 2024-11-01 提交（申报编号 0000320193-24-000123）：391,035百万美元（3,910.4亿美元）。")
    assert "6.08 美元/股" in result.page_text and "364,980百万美元（3,649.8亿美元）" in result.page_text
    assert "2024-09-28 财年末" in result.page_text
    available = lr.page_number_set(result.page_text)
    for fact in ("苹果2024财年营收3910.35亿美元。", "苹果2024财年营收3,910.4亿美元。"):
        assert lr._missing_numbers(fact, lr.fact_number_tokens(fact), available) == [], fact
    assert "USD millions; facts filed on or before 2024-11-15" in result.model_text  # the agent's table stays English
    assert result.facts[0]["text"] == "391,035 million USD (391.0 billion USD)"


def test_supports_start_with_the_latest_period_of_every_line():
    result = call(_filer(), company="999999", as_of=dt.date(2026, 1, 1))
    first = [LINE_RE.match(text) for text in result.supports[:5]]
    assert [match["label"] for match in first] == ["Revenue", "Net income", "Diluted EPS", "Total assets",
                                                  "Diluted shares"]
    assert {match["period"][-10:] for match in first} == {"2025-09-30"}


def test_model_text_is_capped_dropping_the_oldest_periods_first(monkeypatch):
    monkeypatch.setattr(dtools, "MODEL_TEXT_MAX_CHARS", 4000)
    full = call(_filer(), company="999999", as_of=dt.date(2026, 1, 1), freq="quarterly")
    assert len(columns(full)) == 6 and "Older periods are omitted." not in full.model_text
    monkeypatch.setattr(dtools, "MODEL_TEXT_MAX_CHARS", 2000)
    capped = call(_filer(), company="999999", as_of=dt.date(2026, 1, 1), freq="quarterly")
    assert len(full.model_text) > 2000 >= len(capped.model_text)
    assert capped.model_text.endswith("Older periods are omitted.")
    shown = columns(capped)
    assert shown == columns(full)[:len(shown)] and len(shown) < 6
    shown_cash = columns(capped, 1)
    assert shown_cash == columns(full, 1)[:len(shown_cash)]
    # The page holds exactly the values shown.
    assert {match["period"][-10:] for match in sentences(capped)} <= set(shown) | set(shown_cash)
    assert len(capped.supports) < len(full.supports)


def _widest_filer():
    """Every line at the widest cell a well-formed fact can make (18 digits in a 40-character unit) in
    every column of six fiscal years and quarters (a fourth quarter tagged as filed, so no quarter
    column has a gap), the long-term debt row under its noted tag, the latest filing under the longest
    form (a recast of each fiscal year) and the longest ticker naming a CIK at the name's full length."""
    unit, value, form = "X" * 40, -999_999_999_999_999_999, "ABCDEFGHIJKLMNOPQRST"
    us_gaap = {}
    for line in dtools.EDGAR_LINES_US_GAAP:
        tag = "LongTermDebt" if line.label == "Long-term debt" else line.tags[0]
        instant = line.statement == "balance"
        rows = []
        for year in range(2020, 2026):
            accn = f"0000000001-{year % 100:02d}-00000"  # + the filing's number in the year
            k_filed, recast_filed, q_filed = f"{year + 1}-02-01", f"{year + 1}-02-02", f"{year}-08-01"
            fiscal_year = None if instant else f"{year}-01-01"
            rows += [_fact(f"{year}-12-31", value, k_filed, start=fiscal_year, accn=accn + "1"),
                     _fact(f"{year}-12-31", value, recast_filed, form=form, start=fiscal_year, accn=accn + "3"),
                     _fact(f"{year}-06-30", value, q_filed, form=form, start=None if instant else f"{year}-04-01",
                           accn=accn + "2")]
            if not instant:
                rows.append(_fact(f"{year}-12-31", value, recast_filed, form=form, start=f"{year}-10-01",
                                  accn=accn + "3"))
        us_gaap[tag] = {"units": {unit: rows}}
    return FakeSEC(facts=(200, {"cik": 1, "entityName": "W" * 80, "facts": {"us-gaap": us_gaap}}, ""),
                   tickers=(200, {"0": {"cik_str": 1, "ticker": "ABCDEFGHIJ"}}, ""))


@pytest.mark.parametrize("freq", ["annual", "quarterly"])
def test_the_widest_well_formed_statement_fits_without_a_cut(freq, tmp_path):
    """The cap drops whole periods down to one column, and one column of the widest cells fits: the
    agent's text is never cut mid-table, so its legend and latest-filing lines always arrive.  The
    widest header too: a ten-character ticker named at the name's full length, resolved for a past
    as_of (the ticker note) from a snapshot SEC answered that day (the as-fetched clause)."""
    transport, cache = _widest_filer(), dtools._DiskCache(str(tmp_path / "cache"), 86400)
    as_of = dt.date(2026, 9, 29)
    call(transport, company="ABCDEFGHIJ", as_of=as_of, freq=freq, cache=cache,
         now=dt.datetime(2026, 9, 29, 23, 0, tzinfo=UTC))
    result = call(transport, company="ABCDEFGHIJ", as_of=as_of, freq=freq, cache=cache)  # NOW: the next UTC day
    assert len(transport.urls("companyfacts")) == 1 and result.status == dtools.STATUS_OK
    assert result.model_text.splitlines()[:3] == [
        f"SEC EDGAR as-filed statements: ABCDEFGHIJ (CIK 0000000001, {'W' * 80}), {freq}, us-gaap XBRL company facts",
        "USD millions; facts filed on or before 2026-09-29, at the values filed then; SEC data as fetched "
        "2026-09-29T23:00:00Z (a filing made after that is not included)",
        dtools.EDGAR_TICKER_NOTE]
    tables = sum(text.startswith("| Line |") for text in result.model_text.splitlines())
    assert tables == (2 if freq == "quarterly" else 1)
    assert all(len(columns(result, table)) == 1 for table in range(tables))  # cut down to one column ...
    assert len(result.model_text) <= dtools.MODEL_TEXT_MAX_CHARS  # ... which fits whole
    assert result.model_text.splitlines()[-2] == ("Latest filing served: ABCDEFGHIJKLMNOPQRST filed 2026-02-02 "
                                                  "(accession 0000000001-25-000003).")
    assert result.model_text.endswith("Older periods are omitted.")
    widest = f"-999,999,999,999,999,999 {'X' * 40}"
    assert {line.label: row(result, line.label) for line in dtools.EDGAR_LINES_US_GAAP} == {
        line.label: [widest] for line in dtools.EDGAR_LINES_US_GAAP}  # every cell of the column at its widest
    assert "Long-term debt: us-gaap:LongTermDebt (includes the current portion)." in result.model_text.splitlines()


def test_a_snapshot_that_may_predate_a_filing_says_when_sec_answered(tmp_path):
    """A live run's as_of is today: a cached snapshot fetched earlier cannot hold a filing made since."""
    header = "USD millions; facts filed on or before {day}, at the values filed then"
    fresh = call(company="320193", as_of=NOW.date())
    assert (header.format(day="2026-09-30") + "; SEC data as fetched 2026-09-30T17:00:00Z (a filing made after "
            "that is not included)") in fresh.model_text.splitlines()
    cache = dtools._DiskCache(str(tmp_path / "cache"), 3600)
    transport = FakeSEC()
    evening = dt.datetime(2026, 9, 29, 23, 0, tzinfo=UTC)
    first = call(transport, company="320193", as_of=dt.date(2026, 9, 29), cache=cache, now=evening)
    assert "SEC data as fetched 2026-09-29T23:00:00Z" in first.model_text
    for day, shown in ((dt.date(2026, 9, 30), True), (dt.date(2026, 9, 28), False), (dt.date(2024, 11, 15), False)):
        result = call(transport, company="320193", as_of=day, cache=cache, now=NOW)  # served from the cache
        assert ("SEC data as fetched 2026-09-29T23:00:00Z" in result.model_text) is shown, day
        assert header.format(day=day.isoformat()) in result.model_text.splitlines()[1]
        assert result.provenance["fetched_at"] == "2026-09-29T23:00:00Z"
    assert len(transport.urls("companyfacts")) == 1


def test_a_section_with_no_period_names_each_line():
    result = call(as_of=dt.date(2024, 11, 15), freq="quarterly")
    assert "Operating cash flow: not tagged by this filer" in result.model_text.splitlines()
    transport = with_facts({"Assets": FACTS["facts"]["us-gaap"]["Assets"],
                            "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
                                _fact("2024-06-29", 1_000_000, "2024-11-01", start="2024-03-31", form="10-Q",
                                      accn="0000320193-24-000090")]}}})
    tagged = call(transport, as_of=dt.date(2024, 11, 15), freq="quarterly")
    assert "Operating cash flow: no value filed on or before 2024-11-15" in tagged.model_text.splitlines()


def test_a_tag_first_used_after_as_of_reads_not_tagged():
    """Whether the filer tags a line later must not show through: untagged is judged as of as_of."""
    facts = dict(FACTS["facts"]["us-gaap"], GrossProfit={"units": {"USD": [
        _fact("2025-12-31", 1_000_000, "2026-01-29", form="10-Q", start="2025-10-01")]}})
    result = call(with_facts(facts), as_of=dt.date(2024, 11, 15))
    assert row(result, "Gross profit") == [dtools.EDGAR_UNTAGGED] * 2


# ---------------------------------------------------------------------------
# Robustness, throttle, attribution
# ---------------------------------------------------------------------------

def test_a_raising_or_malformed_transport_or_cache_never_raises():
    def boom(url, params, timeout, headers):
        raise RuntimeError("https://www.sec.gov/files/company_tickers.json?leak")

    result = call(boom)
    assert (result.status, result.detail) == (dtools.STATUS_UNAVAILABLE, "SEC EDGAR is unreachable (RuntimeError)")
    for answer in (None, (200, FACTS), (True, FACTS, ""), "200"):
        assert call(lambda *args, answer=answer: answer).status == dtools.STATUS_UNAVAILABLE

    class BrokenCache:
        def get(self, key, max_age_s=None):
            raise OSError("disk gone")

    broken = call(cache=BrokenCache())
    assert broken.status == dtools.STATUS_UNAVAILABLE and "internally (OSError)" in broken.detail
    assert broken.model_text.startswith("SEC EDGAR: ")


def test_the_throttle_is_two_tenths_of_a_second_and_every_request_waits(monkeypatch):
    assert isinstance(_MODULE_EDGAR_THROTTLE, dtools._Throttle) and _MODULE_EDGAR_THROTTLE.min_interval_s == 0.2
    assert _MODULE_EDGAR_THROTTLE is not dtools._FRED_THROTTLE

    class Counting:
        waits = 0

        def wait(self):
            Counting.waits += 1

    monkeypatch.setattr(dtools, "_EDGAR_THROTTLE", Counting())
    transport = FakeSEC()
    call(transport)
    assert Counting.waits == len(transport.calls) == 2
    call(transport, company="320193", cache=NoCache())
    assert Counting.waits == len(transport.calls) == 3


def test_the_timeout_knob_reaches_the_transport(monkeypatch):
    monkeypatch.setenv("DATA_TOOL_TIMEOUT_S", "7")
    transport = FakeSEC()
    call(transport)
    assert {call["timeout"] for call in transport.calls} == {7.0}


def test_fred_failures_keep_their_text():
    """Flag-off equivalent for the shared helper: FRED's failure text is unchanged."""
    assert dtools._failure(dtools.STATUS_UNAVAILABLE, "x").model_text == "FRED: x"


def test_notice_and_header_carry_the_sec_edgar_attribution():
    notice = (_REPO / "NOTICE").read_text(encoding="utf-8")
    assert "tradingagents/dataflows/vendors/sec_edgar.py" in notice
    assert "backend/tests/test_data_tools_edgar.py" in notice and "tests/test_sec_edgar.py" in notice
    header = (_REPO / "deerflow_bridge" / "data_tools.py").read_text(encoding="utf-8")[:1200]
    assert "Portions adapted from TradingAgents 0.5.1\ntradingagents/dataflows/vendors/sec_edgar.py (Apache-2.0)" in header


def test_the_env_example_documents_the_edgar_ttl():
    example = (_REPO / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^# DATA_EDGAR_CACHE_TTL_H=24\s+# TIME-11", example, re.MULTILINE)
