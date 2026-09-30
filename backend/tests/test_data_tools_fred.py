"""TIME-10: deerflow_bridge/data_tools.py — FRED/ALFRED vintage-pinned macro series.

Offline: every request goes to a fake transport that records it.  Pinned here:
the alias table and the pre-call rejection of anything that is not a series
id; the vintage invariant (both realtime bounds equal the pin, the pin never
after as_of, no unpinned retry, no answer stamped outside the pin served) and
the America/Chicago vendor clock with its fallback; the conservative status
mapping; the deterministic rendering (units DRF's page-number parser reads,
true change endpoints, exact derived arithmetic labelled derived, the
2600-character cap, English or Chinese support sentences); the secrecy of the
API key in results, cache files and logs, whole or in part across any cut; the
cache and throttle rules; and that the module stays inert and self-contained
until the research engine binds it (TIME-13).
"""

from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_BRIDGE = str(_REPO / "deerflow_bridge")
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

import data_tools as dtools  # noqa: E402
import linear_research as lr  # noqa: E402

KEY = "0123456789abcdef0123456789abcdef"
UTC = dt.timezone.utc
# 12:00 in Chicago (CDT) on 2026-09-30: FRED's today is 2026-09-30.
NOW = dt.datetime(2026, 9, 30, 17, 0, tzinfo=UTC)
TODAY = dt.date(2026, 9, 30)
PAST = dt.date(2020, 3, 15)


@pytest.fixture(autouse=True)
def _offline_vendor(monkeypatch, tmp_path):
    """No throttle waits, and the default cache directory inside tmp_path."""
    monkeypatch.setattr(dtools, "_FRED_THROTTLE", dtools._Throttle(0))
    monkeypatch.setenv("DATA_TOOLS_CACHE_DIR", str(tmp_path / "default_cache"))
    for name in ("DATA_FRED_CACHE_TTL_H", "DATA_TOOL_TIMEOUT_S", "DATA_FRED_WINDOW_YEARS"):
        monkeypatch.delenv(name, raising=False)


def meta(series_id="CPIAUCSL", title="Consumer Price Index for All Urban Consumers: All Items in U.S. City Average",
         units="Index 1982-1984=100", frequency="Monthly", seasonal="SA"):
    return 200, {"seriess": [{"id": series_id, "title": title, "units": units, "frequency": frequency,
                              "seasonal_adjustment_short": seasonal}]}, ""


def monthly(first: dt.date, values):
    rows, year, month = [], first.year, first.month
    for value in values:
        rows.append({"date": dt.date(year, month, 1).isoformat(), "value": value})
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return rows


def observations(rows):
    return 200, {"observations": rows}, ""


def window_rows(params):
    """24 monthly observations ending the month before the requested window end."""
    end = dt.date.fromisoformat(params["observation_end"])
    return observations(monthly(dt.date(end.year - 2, end.month, 1), [f"{300 + i}.5" for i in range(24)]))


class NoCache:
    def get(self, key, max_age_s=None):
        return None

    def put(self, key, payload, ttl_s=None):
        return False


class FakeTransport:
    """Records every request; answers by endpoint (a tuple, or a callable of the params)."""

    def __init__(self, series=None, obs=None):
        self.calls = []
        self.answers = {"series": series or meta(), "series/observations": obs or window_rows}

    def __call__(self, url, params, timeout, headers):
        self.calls.append({"url": url, "params": dict(params), "timeout": timeout, "headers": dict(headers)})
        answer = self.answers[url.split("/fred/", 1)[1]]
        return answer(params) if callable(answer) else answer


def call(transport, *, series="cpi", as_of=TODAY, pit=TODAY, now=NOW, cache=None, cache_dir=None, **kwargs):
    """fred_series with the test key; uncached unless a cache or a cache directory is given."""
    if cache is None:
        cache = dtools._DiskCache(cache_dir, 3600) if cache_dir else NoCache()
    return dtools.fred_series(series, as_of=as_of, pit=pit, key=KEY, transport=transport, now=now, cache=cache,
                              **kwargs)


@pytest.fixture
def cache(tmp_path):
    return dtools._DiskCache(str(tmp_path / "cache"), 3600)


def assert_pinned(calls, pit, as_of):
    for request in calls:
        params = request["params"]
        assert params["realtime_start"] == params["realtime_end"] == pit.isoformat()
        assert dt.date.fromisoformat(params["realtime_end"]) <= as_of


# ---------------------------------------------------------------------------
# Aliases and input rejection
# ---------------------------------------------------------------------------

EXPECTED_ALIASES = {
    "fed_funds": "FEDFUNDS", "fed_funds_rate": "FEDFUNDS", "federal_funds_rate": "FEDFUNDS",
    "effective_fed_funds": "DFF", "3m_treasury": "DGS3MO", "2y_treasury": "DGS2",
    "10y_treasury": "DGS10", "10_year_treasury": "DGS10", "30y_treasury": "DGS30",
    "yield_curve": "T10Y2Y", "10y_2y": "T10Y2Y", "cpi": "CPIAUCSL", "cpi_nsa": "CPIAUCNS",
    "core_cpi": "CPILFESL", "pce": "PCEPI", "core_pce": "PCEPILFE", "breakeven_5y": "T5YIE",
    "breakeven_10y": "T10YIE", "gdp": "GDP", "real_gdp": "GDPC1", "industrial_production": "INDPRO",
    "unemployment": "UNRATE", "payrolls": "PAYEMS", "initial_claims": "ICSA", "m2": "M2SL",
    "vix": "VIXCLS", "dollar_index": "DTWEXBGS", "consumer_sentiment": "UMCSENT",
    "housing_starts": "HOUST", "retail_sales": "RSAFS", "wti": "DCOILWTICO", "brent": "DCOILBRENTEU",
    "ecb_deposit_rate": "ECBDFR", "usd_cny": "DEXCHUS", "eur_usd": "DEXUSEU",
}


def test_alias_table_is_pinned_and_excludes_licence_limited_series():
    assert dict(dtools.MACRO_ALIASES) == EXPECTED_ALIASES
    assert not any(value in ("SP500", "NASDAQCOM") or value.startswith("BAML")
                   for value in dtools.MACRO_ALIASES.values())
    with pytest.raises(TypeError):
        dtools.MACRO_ALIASES["sp500"] = "SP500"


@pytest.mark.parametrize("text, expected", [
    ("Fed Funds Rate", "FEDFUNDS"),
    ("10y-treasury", "DGS10"),
    ("  cpi ", "CPIAUCSL"),
    ("core–pce", "PCEPILFE"),
    ("CPIAUCSL", "CPIAUCSL"),
    ("dgs10", "DGS10"),
    ("A" * 30, "A" * 30),
])
def test_resolve_series(text, expected):
    assert dtools.resolve_series(text) == expected


@pytest.mark.parametrize("text", ["bank of japan rate", "X" * 31, "CPI?&x=1", "", "   ", None, 42, "cpi\nx"])
def test_rejected_series_is_invalid_input_with_zero_transport_calls(text):
    transport = FakeTransport()
    result = call(transport, series=text)
    assert dtools.resolve_series(text) is None
    assert result.status == dtools.STATUS_INVALID_INPUT
    assert transport.calls == []
    assert "fed_funds" in result.detail and "10y_treasury" in result.detail and "CPIAUCSL" in result.detail
    assert result.page_text == "" and result.supports == () and result.facts == ()


# ---------------------------------------------------------------------------
# Vintage
# ---------------------------------------------------------------------------

def test_both_requests_carry_the_pin_and_the_window(tmp_path):
    transport = FakeTransport()
    result = call(transport, cache_dir=str(tmp_path / "c"))
    assert result.status == dtools.STATUS_OK
    assert [request["url"] for request in transport.calls] == [
        "https://api.stlouisfed.org/fred/series", "https://api.stlouisfed.org/fred/series/observations"]
    assert_pinned(transport.calls, TODAY, TODAY)
    series_params, obs_params = (request["params"] for request in transport.calls)
    assert series_params == {"series_id": "CPIAUCSL", "realtime_start": "2026-09-30", "realtime_end": "2026-09-30",
                             "api_key": KEY, "file_type": "json"}
    assert obs_params["observation_start"] == "2016-09-30"
    assert obs_params["observation_end"] == "2026-09-30"
    assert obs_params["sort_order"] == "asc"
    assert all(request["timeout"] == 20 for request in transport.calls)


def test_utc_ahead_of_chicago_clamps_the_pin_but_not_the_window_end(tmp_path):
    now = dt.datetime(2026, 10, 1, 3, 0, tzinfo=UTC)  # 22:00 on 30 September in Chicago
    as_of = now.date()
    assert dtools.vendor_today_chicago(now) == dt.date(2026, 9, 30)
    pit = dtools.fred_pit(as_of, now)
    assert pit == dt.date(2026, 9, 30)
    transport = FakeTransport()
    result = call(transport, as_of=as_of, pit=pit, now=now, cache_dir=str(tmp_path / "c"))
    assert result.status == dtools.STATUS_OK
    assert_pinned(transport.calls, pit, as_of)
    assert transport.calls[1]["params"]["observation_end"] == "2026-10-01"
    assert result.date == "2026-09-30" and "vintage=2026-09-30" in result.url


def test_mocked_chicago_date_clamps_the_pin(monkeypatch):
    monkeypatch.setattr(dtools, "vendor_today_chicago", lambda now=None: dt.date(2026, 9, 30))
    assert dtools.fred_pit(dt.date(2026, 10, 1)) == dt.date(2026, 9, 30)
    assert dtools.fred_pit(PAST) == PAST


def test_past_as_of_passes_through_and_pins_every_request(tmp_path):
    assert dtools.fred_pit(PAST, NOW) == PAST
    transport = FakeTransport(obs=observations(monthly(dt.date(2018, 1, 1), [str(250 + i) for i in range(26)])))
    result = call(transport, as_of=PAST, pit=PAST, cache_dir=str(tmp_path / "c"))
    assert result.status == dtools.STATUS_OK
    assert_pinned(transport.calls, PAST, PAST)
    assert transport.calls[1]["params"]["observation_end"] == PAST.isoformat()


def test_pin_dates_are_compared_as_dates_never_as_strings():
    now = dt.datetime(2025, 10, 1, 18, 0, tzinfo=UTC)
    # As strings, min("2025-9-30", "2025-10-01") is the later day: a non-padded date is refused.
    assert dtools.fred_pit("2025-9-30", now) is None
    assert dtools.fred_pit("2025-09-30", now) == dt.date(2025, 9, 30)
    assert dtools.fred_pit(dt.datetime(2025, 9, 30, 23, 0), now) == dt.date(2025, 9, 30)
    assert dtools.fred_pit("20250930", now) is None


def test_zoneinfo_fallback_is_never_later_than_the_chicago_date(monkeypatch):
    instants = [start + dt.timedelta(minutes=30 * step)
                for start in (dt.datetime(2026, 1, 10, tzinfo=UTC), dt.datetime(2026, 3, 7, tzinfo=UTC),
                              dt.datetime(2026, 7, 10, tzinfo=UTC), dt.datetime(2026, 10, 31, tzinfo=UTC))
                for step in range(5 * 48)]
    truth = [dtools.vendor_today_chicago(instant) for instant in instants]

    def missing_zone(name):
        raise dtools.ZoneInfoNotFoundError(name)

    monkeypatch.setattr(dtools, "ZoneInfo", missing_zone)
    fallback = [dtools.vendor_today_chicago(instant) for instant in instants]
    assert all(guess <= real for guess, real in zip(fallback, truth, strict=True))
    assert sum(guess == real for guess, real in zip(fallback, truth, strict=True)) > len(instants) * 0.9
    assert dtools.fred_pit(dt.date(2027, 1, 1), instants[0]) == fallback[0]


def test_no_request_is_ever_sent_with_realtime_end_after_as_of():
    transport = FakeTransport()
    # A pin after as_of, or after FRED's today, is refused before any request.
    after = call(transport, as_of=dt.date(2026, 9, 1), pit=TODAY)
    future = call(transport, as_of=dt.date(2026, 12, 31), pit=dt.date(2026, 10, 2))
    malformed = call(transport, pit="2026-9-30")
    assert {after.status, future.status, malformed.status} == {dtools.STATUS_INVALID_INPUT}
    assert transport.calls == []
    # The request guard itself refuses anything but realtime_start == realtime_end == pit <= as_of.
    for params, pit, as_of in (({"series_id": "GDP"}, TODAY, TODAY),
                               ({"realtime_start": "2026-09-30", "realtime_end": "2026-10-01"}, TODAY, TODAY),
                               ({"realtime_start": "2026-09-30", "realtime_end": "2026-09-30"}, TODAY,
                                dt.date(2026, 9, 29))):
        answer = dtools._fred_get(transport, "series", params, key=KEY, pit=pit, as_of=as_of, timeout=1)
        assert answer[0] == dtools._REFUSED
    assert transport.calls == []
    code, payload, text = dtools._fred_get(transport, "series", {"realtime_start": "2026-09-30",
                                                                 "realtime_end": "2026-09-30"},
                                           key=KEY, pit=TODAY, as_of=TODAY, timeout=1)
    assert code == 200 and len(transport.calls) == 1
    assert dtools._http_failure(dtools._REFUSED, None, "", series_id="GDP", pit=TODAY,
                                historical=False)[0] == dtools.STATUS_UNAVAILABLE


def _stamped(row, start, end):
    return {**row, "realtime_start": start, "realtime_end": end}


def test_answers_stamped_with_the_pinned_period_are_accepted():
    pin = PAST.isoformat()
    _, series_payload, _ = meta()
    series_payload = {"realtime_start": pin, "realtime_end": pin,
                      "seriess": [_stamped(series_payload["seriess"][0], pin, pin)]}
    rows = monthly(dt.date(2018, 1, 1), [str(250 + i) for i in range(26)])
    # FRED clips a row's real-time period to the request; an unclipped period holding the pin agrees too.
    rows = [_stamped(row, pin, pin) for row in rows[:13]] + [_stamped(row, "2019-06-01", "9999-12-31")
                                                             for row in rows[13:]]
    transport = FakeTransport(series=(200, series_payload, ""),
                              obs=(200, {"realtime_start": pin, "realtime_end": pin, "observations": rows}, ""))
    result = call(transport, as_of=PAST, pit=PAST)
    assert result.status == dtools.STATUS_OK and "Latest: 275 (2020-02-01)" in result.page_text


def _off_pin_answers(stage, where, stamp):
    """The fake answers of one request whose response or one of whose rows carries ``stamp``."""
    status, series_payload, text = meta()
    if stage == "series":
        if where == "response":
            series_payload.update(stamp)
        else:
            series_payload["seriess"][0].update(stamp)
        return {"series": (status, series_payload, text)}
    rows = monthly(dt.date(2018, 1, 1), [str(250 + i) for i in range(26)])
    payload = {"observations": rows}
    if where == "response":
        payload.update(stamp)
    else:
        rows[-1].update(stamp)
    return {"series/observations": (200, payload, "")}


@pytest.mark.parametrize("stage", ["series", "series/observations"])
@pytest.mark.parametrize("where", ["response", "row"])
@pytest.mark.parametrize("pin, stamp, expected", [
    # A historical pin answered with today's revision: never labelled the pinned vintage.
    (PAST, {"realtime_start": "2026-09-30", "realtime_end": "2026-09-30"}, dtools.STATUS_NO_VINTAGE),
    # Today's pin answered with a period that ended before it.
    (TODAY, {"realtime_start": "2020-01-01", "realtime_end": "2026-09-29"}, dtools.STATUS_UNAVAILABLE),
])
def test_an_answer_stamped_outside_the_pin_is_never_served_as_the_pinned_vintage(stage, where, pin, stamp,
                                                                                  expected, cache):
    transport = FakeTransport()
    transport.answers.update(_off_pin_answers(stage, where, stamp))
    result = call(transport, as_of=pin, pit=pin, cache=cache)
    assert result.status == expected and result.page_text == "" and result.facts == ()
    assert "outside" in result.detail and pin.isoformat() in result.detail
    assert ("never substituted" in result.detail) == (pin == PAST)
    assert len(transport.calls) == (1 if stage == "series" else 2)
    assert_pinned(transport.calls, pin, pin)
    assert not os.path.isdir(cache.root) or not os.listdir(cache.root)


@pytest.mark.parametrize("stamp", [{"realtime_start": "yesterday", "realtime_end": "2026-09-30"},
                                   {"realtime_start": "2026-09-30"},
                                   {"realtime_start": "2026-09-30", "realtime_end": 20260930}])
def test_a_malformed_real_time_stamp_contradicts_the_pin(stamp):
    status, payload, text = meta()
    payload["seriess"][0].update(stamp)
    result = call(FakeTransport(series=(status, payload, text)))
    assert result.status == dtools.STATUS_UNAVAILABLE and "outside the requested vintage" in result.detail


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="setting the host time zone needs time.tzset")
def test_a_naive_now_is_local_time_like_datetime_now():
    saved = os.environ.get("TZ")
    os.environ["TZ"] = "Asia/Shanghai"
    time.tzset()
    try:
        # 07:30 on 1 October in Shanghai is 23:30 UTC and 18:30 in Chicago on 30 September; read as
        # UTC it would be 02:30 on 1 October in Chicago, a day ahead of FRED.
        naive = dt.datetime(2026, 10, 1, 7, 30)
        assert dtools.vendor_today_chicago(naive) == dt.date(2026, 9, 30)
        assert dtools.fred_pit(dt.date(2026, 10, 1), naive) == dt.date(2026, 9, 30)
        transport = FakeTransport()
        ahead = call(transport, as_of=dt.date(2026, 10, 1), pit=dt.date(2026, 10, 1), now=naive)
        assert ahead.status == dtools.STATUS_INVALID_INPUT and transport.calls == []
        # A naive instant that has no UTC equivalent reads as the current instant; nothing raises.
        assert dtools.fred_pit(PAST, dt.datetime.min) == PAST
    finally:
        if saved is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = saved
        time.tzset()


def test_the_vendor_clock_never_raises_at_the_datetime_limits(monkeypatch):
    assert dtools.vendor_today_chicago(dt.datetime.min.replace(tzinfo=UTC)) == dt.date.min
    assert dtools.vendor_today_chicago(dt.datetime.max.replace(tzinfo=UTC)) == dt.date(9999, 12, 31)

    def missing_zone(name):
        raise dtools.ZoneInfoNotFoundError(name)

    monkeypatch.setattr(dtools, "ZoneInfo", missing_zone)
    assert dtools.vendor_today_chicago(dt.datetime.min.replace(tzinfo=UTC)) == dt.date.min


# ---------------------------------------------------------------------------
# Honesty: status mapping
# ---------------------------------------------------------------------------

_DOES_NOT_EXIST = (400, {"error_code": 400, "error_message": "Bad Request.  The series does not exist in ALFRED "
                                                             "but may exist in FRED."}, "")


@pytest.mark.parametrize("stage, sent", [("series", 1), ("series/observations", 2)])
def test_does_not_exist_at_a_historical_pin_is_no_vintage_without_an_unpinned_retry(stage, sent, cache):
    transport = FakeTransport()
    transport.answers[stage] = _DOES_NOT_EXIST
    result = call(transport, as_of=PAST, pit=PAST, cache=cache)
    assert result.status == dtools.STATUS_NO_VINTAGE
    assert len(transport.calls) == sent
    assert_pinned(transport.calls, PAST, PAST)
    assert "never substituted" in result.detail and result.page_text == ""
    assert not os.path.isdir(cache.root) or not os.listdir(cache.root)


@pytest.mark.parametrize("stage, sent", [("series", 1), ("series/observations", 2)])
def test_does_not_exist_at_todays_pin_is_not_found(stage, sent):
    transport = FakeTransport()
    transport.answers[stage] = _DOES_NOT_EXIST
    result = call(transport)
    assert result.status == dtools.STATUS_NOT_FOUND
    assert len(transport.calls) == sent


def test_empty_series_metadata_is_no_vintage_historically_and_not_found_today():
    empty = (200, {"seriess": []}, "")
    historical = FakeTransport(series=empty)
    assert call(historical, as_of=PAST, pit=PAST).status == dtools.STATUS_NO_VINTAGE
    today = FakeTransport(series=empty)
    assert call(today).status == dtools.STATUS_NOT_FOUND
    assert len(historical.calls) == len(today.calls) == 1


@pytest.mark.parametrize("answer", [
    (500, None, "Internal Server Error"),
    (503, None, "unavailable"),
    (429, {"error_code": 429, "error_message": "Too Many Requests"}, ""),
    (0, None, "ReadTimeout"),
    (400, {"error_code": 400, "error_message": "Bad Request.  Variable api_key has not been registered."}, ""),
    (200, None, "<html>maintenance</html>"),
    (302, None, ""),
    ("not a status", None, ""),
])
@pytest.mark.parametrize("stage", ["series", "series/observations"])
def test_transport_and_server_failures_are_unavailable(answer, stage, tmp_path):
    transport = FakeTransport()
    transport.answers[stage] = answer
    result = call(transport, cache_dir=str(tmp_path / "c"))
    assert result.status == dtools.STATUS_UNAVAILABLE
    assert len(transport.calls) == (1 if stage == "series" else 2)
    assert_pinned(transport.calls, TODAY, TODAY)
    assert not (tmp_path / "c").exists()


def test_a_raising_transport_or_cache_never_raises():
    def boom(*_args):
        raise RuntimeError("socket closed; url had api_key=" + KEY)

    result = call(boom)
    assert result.status == dtools.STATUS_UNAVAILABLE and KEY not in repr(result)

    class BrokenCache:
        def get(self, key, max_age_s=None):
            raise OSError("disk gone")

    broken = call(FakeTransport(), cache=BrokenCache())
    assert broken.status == dtools.STATUS_UNAVAILABLE


@pytest.mark.parametrize("key", ["", None, "short", KEY.upper(), KEY + "0", " " + KEY])
def test_a_missing_or_malformed_key_is_unavailable_with_zero_calls(key):
    transport = FakeTransport()
    result = dtools.fred_series("cpi", as_of=TODAY, pit=TODAY, key=key, transport=transport, now=NOW)
    assert result.status == dtools.STATUS_UNAVAILABLE
    assert transport.calls == []


def test_no_usable_observation_is_not_found_naming_the_frequency():
    transport = FakeTransport(series=meta(series_id="GDP", title="Gross Domestic Product", units="Billions of Dollars",
                                          frequency="Quarterly", seasonal="SAAR"),
                              obs=observations([{"date": "2025-01-01", "value": "."},
                                                {"date": "2025-04-01", "value": ""},
                                                {"date": "2025-07-01", "value": "n/a"},
                                                {"date": "2025-10-01", "value": "\uff14.\uff13"}]))
    result = call(transport, series="gdp")
    assert result.status == dtools.STATUS_NOT_FOUND
    assert "Quarterly" in result.detail
    assert len(transport.calls) == 2


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _cpi_transport(values, first=dt.date(2022, 9, 1)):
    return FakeTransport(obs=observations(monthly(first, values)))


def test_missing_values_are_skipped_and_changes_use_true_endpoints():
    values = [f"{300 + i}.000" for i in range(36)]
    values[-1] = "."          # 2025-08: not published at this vintage
    values[20] = "."          # 2024-05
    result = call(_cpi_transport(values))
    lines = result.page_text.split("\n")
    observation_lines = [line for line in lines if re.fullmatch(r"\d{4}-\d{2}-\d{2}: .+", line)]
    assert len(observation_lines) == 24      # the last 24 published observations
    assert observation_lines[0] == "2023-07-01: 310.000" and observation_lines[-1] == "2025-07-01: 334.000"
    assert "2024-05-01" not in result.page_text and ": ." not in result.page_text
    assert "Latest: 334.000 (2025-07-01)" in lines
    # The window change starts at the first observation of the full window, not of the shown rows.
    window = next(line for line in lines if line.startswith("Change over the window:"))
    assert window == ("Change over the window: +34.000 (+11.33%) from 300.000 (2022-09-01) to 334.000 "
                      "(2025-07-01) (derived by DRF from the pinned levels)")
    assert not any(line.startswith("2022-09-01") for line in observation_lines)
    twelve = next(line for line in lines if line.startswith("Change over 12 months:"))
    assert twelve == ("Change over 12 months: +12.000 (+3.73%) from 322.000 (2024-07-01) to 334.000 "
                      "(2025-07-01) (derived by DRF from the pinned levels)")
    assert "Older observations in the window are omitted." in result.model_text


def test_no_year_on_year_without_the_same_period_a_year_earlier():
    values = [f"{300 + i}.0" for i in range(13)]
    values[0] = "."           # 2024-08 is missing: never a 13-month "year-on-year"
    result = call(_cpi_transport(values, first=dt.date(2024, 8, 1)))
    assert "Latest: 312.0 (2025-08-01)" in result.page_text
    assert "Year-on-year" not in result.page_text and "Change over 12 months" not in result.page_text
    assert "Change over the window: +11.0 (+3.65%) from 301.0 (2024-09-01)" in result.page_text
    assert len(result.facts) == 1


def test_header_yoy_and_facts_label_source_vintage_and_derivation():
    result = call(_cpi_transport([f"{300 + i}.5" for i in range(24)], first=dt.date(2023, 9, 1)))
    lines = result.page_text.split("\n")
    assert lines[0] == ("FRED/ALFRED: Consumer Price Index for All Urban Consumers: All Items in U.S. City Average "
                        "(CPIAUCSL) — Index 1982-1984=100, Monthly SA; values as published on 2026-09-30")
    assert lines[1] == "Latest: 323.5 (2025-08-01)"
    assert lines[2] == ("Year-on-year: 3.85% (derived by DRF from the pinned levels; may differ from the "
                        "publisher's headline basis)")
    assert all("(derived by DRF" in line for line in lines if line.startswith(("Year-on-year", "Change over")))
    assert result.key == "fred:CPIAUCSL@2026-09-30"
    assert result.url == "https://alfred.stlouisfed.org/series?seid=CPIAUCSL&vintage=2026-09-30"
    assert "2026-09-30" in result.title and "CPIAUCSL" in result.title
    assert result.date == "2026-09-30"
    assert result.provenance == {"vendor": "fred", "series_id": "CPIAUCSL", "vintage": "2026-09-30",
                                 "observation_start": "2016-09-30", "observation_end": "2026-09-30",
                                 "units": "Index 1982-1984=100", "frequency": "Monthly",
                                 "fetched_at": "2026-09-30T17:00:00Z"}
    level, yoy = result.facts
    assert (level["value"], level["value_type"], level["provenance_kind"]) == ("323.5", "actual", "structured")
    assert (yoy["value"], yoy["provenance_kind"], yoy["base_date"]) == ("3.85", "derived", "2024-08-01")
    assert "derived by DRF" in yoy["basis"]
    for fact in result.facts:
        assert (fact["source"], fact["series_id"], fact["vintage"]) == ("FRED/ALFRED", "CPIAUCSL", "2026-09-30")
    # Every support sentence names the source, the series id and the vintage; derived ones say so.
    assert all("FRED/ALFRED" in s and "CPIAUCSL" in s and "2026-09-30" in s for s in result.supports)
    assert all("derived by DRF" in s for s in result.supports if "year-on-year" in s or "change over" in s)
    assert result.supports[0].endswith(": 323.5 for August 2025.")


def test_derived_lines_are_exact_at_the_limits_of_a_value():
    # 32 significant digits: the default 28-digit context rounds the difference and cannot quantize
    # the percent change (InvalidOperation), which dropped the whole lookup.
    transport = FakeTransport(obs=observations([{"date": "2024-09-01", "value": "0.000000000001"},
                                               {"date": "2025-09-01", "value": "99999999999999999999.999999999999"}]))
    result = call(transport)
    assert result.status == dtools.STATUS_OK
    lines = result.page_text.split("\n")
    assert lines[2].startswith("Year-on-year: 9999999999999999999999999999999800.00% (derived by DRF")
    assert lines[3] == ("Change over 12 months: +99999999999999999999.999999999998 "
                        "(+9999999999999999999999999999999800.00%) from 0.000000000001 (2024-09-01) to "
                        "99999999999999999999.999999999999 (2025-09-01) (derived by DRF from the pinned levels)")
    assert result.facts[1]["value"] == "9999999999999999999999999999999800.00"


def test_percent_series_verify_through_the_page_number_parser():
    transport = FakeTransport(series=meta(series_id="UNRATE", title="Unemployment Rate", units="Percent",
                                          frequency="Monthly", seasonal="SA"),
                              obs=observations(monthly(dt.date(2024, 8, 1), ["4.2", "4.1", "4.1", "4.2", "4.2", "4.1",
                                                                             "4.0", "4.1", "4.2", "4.2", "4.1", "4.2",
                                                                             "4.3"])))
    result = call(transport, series="unemployment")
    assert "Latest: 4.3% (2025-08-01)" in result.page_text
    # A rate has no year-on-year percent change: its changes are in percentage points.
    assert "Year-on-year" not in result.page_text and len(result.facts) == 1
    assert ("Change over 12 months: +0.1 percentage points from 4.2% (2024-08-01) to 4.3% (2025-08-01) "
            "(derived by DRF from the pinned levels)") in result.page_text
    available = lr.page_number_set(result.page_text)
    fact = "The US unemployment rate was 4.3% in August 2025."
    assert lr._missing_numbers(fact, lr.fact_number_tokens(fact), available) == []
    wrong = "The US unemployment rate was 4.7% in August 2025."
    assert lr._missing_numbers(wrong, lr.fact_number_tokens(wrong), available) == ["4.7"]


def test_scaled_units_verify_through_the_page_number_parser():
    payrolls = FakeTransport(series=meta(series_id="PAYEMS", title="All Employees, Total Nonfarm",
                                         units="Thousands of Persons", frequency="Monthly", seasonal="SA"),
                             obs=observations(monthly(dt.date(2025, 6, 1), ["158800", "158900", "159000"])))
    result = call(payrolls, series="payrolls")
    assert "Latest: 159,000 thousand persons (2025-08-01)" in result.page_text
    available = lr.page_number_set(result.page_text)
    for fact in ("Nonfarm payrolls were 159,000 thousand persons in August 2025.",
                 "Nonfarm payrolls reached 159 million in August 2025."):
        assert lr._missing_numbers(fact, lr.fact_number_tokens(fact), available) == [], fact

    gdp = FakeTransport(series=meta(series_id="GDP", title="Gross Domestic Product", units="Billions of Dollars",
                                    frequency="Quarterly", seasonal="SAAR"),
                        obs=observations([{"date": "2025-01-01", "value": "28700.1"},
                                          {"date": "2025-04-01", "value": "29000.5"}]))
    result = call(gdp, series="gdp")
    assert "Latest: 29,000.5 billion USD (2025-04-01)" in result.page_text
    fact = "US GDP was $29,000.5 billion (SAAR) in 2025 Q2."
    assert lr._missing_numbers(fact, lr.fact_number_tokens(fact), lr.page_number_set(result.page_text)) == []


@pytest.mark.parametrize("units, value, rendered", [
    ("Percent", "4.3", "4.3%"),
    ("Percent Change from Year Ago", "-0.25", "-0.25%"),
    ("Thousands of Persons", "159000", "159,000 thousand persons"),
    ("Billions of Dollars", "29000.5", "29,000.5 billion USD"),
    ("Millions of Dollars", "712345", "712,345 million USD"),
    ("Billions of Chained 2017 Dollars", "23500.2", "23,500.2 billion chained 2017 USD"),
    ("Thousands of Units", "1300", "1,300 thousand units"),
    ("Dollars per Barrel", "65.25", "65.25 USD per barrel"),
    ("U.S. Dollars to 1 Euro", "1.0850", "1.0850 USD per euro"),
    ("Chinese Yuan Renminbi to 1 U.S. Dollar", "7.1234", "7.1234 CNY per USD"),
    ("Index 1982-1984=100", "321.465", "321.465"),
    ("Index 2017=100", "1234.5", "1234.5"),
    ("Number", "230000", "230,000"),
    ("Some future unit", "12345", "12345"),
])
def test_unit_rendering(units, value, rendered):
    assert dtools._fmt(dtools.Decimal(value), dtools._unit_style(units)) == rendered


def test_model_text_is_capped_dropping_the_oldest_observation_lines_first(monkeypatch):
    long_title = "Index " + "very long title " * 20
    transport = FakeTransport(series=meta(title=long_title), obs=observations(monthly(dt.date(2020, 1, 1),
                                                                                    [f"{100 + i}.25" for i in range(68)])))
    result = call(transport)
    assert len(result.model_text) <= dtools.MODEL_TEXT_MAX_CHARS == 2600
    monkeypatch.setattr(dtools, "MODEL_TEXT_MAX_CHARS", 900)
    capped = call(transport)
    assert len(capped.model_text) <= 900
    kept = [line for line in capped.page_text.split("\n") if re.fullmatch(r"\d{4}-\d{2}-\d{2}: .+", line)]
    assert kept and len(kept) < 24
    assert kept[-1] == "2025-08-01: 167.25"          # the newest lines survive
    assert capped.model_text.split("\n")[:-1] == capped.page_text.split("\n")
    assert capped.model_text.endswith("Older observations in the window are omitted.")
    # Supports cite only values the page holds.
    for support in capped.supports:
        numbers = lr.fact_number_tokens(support.split(": ", 1)[1])
        assert not lr._missing_numbers(support, numbers, lr.page_number_set(capped.page_text)), support


_PAGE_LINE_RES = (
    re.compile(r"FRED/ALFRED: .+ \([A-Z0-9_]+\) — .+; values as published on \d{4}-\d{2}-\d{2}"),
    re.compile(r"Latest: .+ \(\d{4}-\d{2}-\d{2}\)"),
    re.compile(r"Year-on-year: -?\d+\.\d\d% \(derived by DRF from the pinned levels; may differ from the "
               r"publisher's headline basis\)"),
    re.compile(r"Change over (?:12 months|the window): .+ \(derived by DRF from the pinned levels\)"),
    re.compile(r"\d{4}-\d{2}-\d{2}: -?[\d,]+(?:\.\d+)?(?:%| .+)?"),
)


def test_page_text_holds_only_rendered_value_lines():
    rows = monthly(dt.date(2016, 10, 1), [str(200 + i) if i % 7 else "." for i in range(120)])
    result = call(FakeTransport(obs=observations(rows)))
    for line in result.page_text.split("\n"):
        assert any(pattern.fullmatch(line) for pattern in _PAGE_LINE_RES), line
    assert "omitted" not in result.page_text and "api_key" not in result.page_text


def test_supports_follow_the_run_language():
    transport = _cpi_transport([f"{300 + i}.5" for i in range(30)], first=dt.date(2023, 3, 1))
    english = call(transport)
    chinese = call(transport, language="Chinese")
    cjk = re.compile(r"[一-鿿]")
    assert english.supports and not any(cjk.search(s) for s in english.supports)
    assert chinese.supports and all(cjk.search(s) for s in chinese.supports)
    assert all("FRED/ALFRED" in s and "CPIAUCSL" in s and "2026-09-30" in s for s in chinese.supports)
    assert chinese.supports[0].endswith("2025年8月的数值为 329.5。")
    assert any("同比变化 3.78%" in s and "推算" in s for s in chinese.supports)
    assert len(english.supports) == len(chinese.supports) <= dtools.SUPPORTS_MAX
    assert english.page_text == chinese.page_text


def test_weekly_and_daily_periods_render_without_yoy():
    weekly = FakeTransport(series=meta(series_id="ICSA", title="Initial Claims", units="Number",
                                       frequency="Weekly, Ending Saturday", seasonal="SA"),
                           obs=observations([{"date": "2025-08-16", "value": "224000"},
                                             {"date": "2025-08-23", "value": "231000"}]))
    result = call(weekly, series="initial_claims")
    assert "Latest: 231,000 (2025-08-23)" in result.page_text and "Year-on-year" not in result.page_text
    assert result.supports[0].endswith(": 231,000 for the week ending 2025-08-23.")
    daily = FakeTransport(series=meta(series_id="DGS10", title="Market Yield on U.S. Treasury Securities at 10-Year",
                                      units="Percent", frequency="Daily", seasonal="NSA"),
                          obs=observations([{"date": "2024-09-27", "value": "3.75"},
                                            {"date": "2025-09-29", "value": "4.14"}]))
    result = call(daily, series="10y_treasury")
    assert result.supports[0].endswith(": 4.14% on 2025-09-29.")
    assert "Change over 12 months: +0.39 percentage points from 3.75% (2024-09-27)" in result.page_text


# ---------------------------------------------------------------------------
# Secrecy and cache
# ---------------------------------------------------------------------------

def test_the_key_never_appears_in_results_cache_files_or_logs(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    cache_dir = tmp_path / "c"
    echo = FakeTransport(series=(400, {"error_message": f"Bad Request. api_key {KEY} is not registered"},
                                 f'{{"error_message": "api_key={KEY}"}}'))
    results = [call(echo, cache_dir=str(cache_dir)),
               call(FakeTransport(), cache_dir=str(cache_dir)),
               call(FakeTransport(), as_of=PAST, pit=PAST, cache_dir=str(cache_dir)),
               call(FakeTransport(series=(0, None, f"ConnectError api_key={KEY}")), cache_dir=str(cache_dir))]
    assert results[0].status == dtools.STATUS_UNAVAILABLE and "[redacted]" in results[0].detail
    for result in results:
        assert KEY not in repr(dataclasses.asdict(result))
    files = list(cache_dir.iterdir())
    assert files and all(KEY not in path.read_text(encoding="utf-8") for path in files)
    assert KEY not in caplog.text


def key_fragments(text, size=8):
    """The ``size``-character pieces of KEY that ``text`` holds."""
    return sorted({KEY[i:i + size] for i in range(len(KEY) - size + 1) if KEY[i:i + size] in text})


def _proxy_page(offset):
    """A proxy's HTML error page echoing the request URL, with the key starting at ``offset``."""
    head = "<html><body><h1>400 Bad Request</h1>"
    echo = "<p>GET /fred/series?series_id=CPIAUCSL&realtime_start=2026-09-30&realtime_end=2026-09-30&api_key="
    page = head + "-" * (offset - len(head) - len(echo)) + echo + KEY + "&file_type=json</p></body></html>"
    assert page.index(KEY) == offset
    return page


_BODY_TAIL_ECHO = "\n" * 480 + "key " + KEY + " is not registered"


@pytest.mark.parametrize("stage", ["series", "series/observations"])
@pytest.mark.parametrize("answer", [
    # The 160-character clip of a 400's message falls inside the echoed key.
    (400, {"error_message": "E" * 129 + KEY}, ""),
    (400, None, _proxy_page(145)),
    (400, None, _proxy_page(150).replace("api_key=", "key: ")),
    (0, None, "E" * 150 + KEY),
    # A body longer than 500 characters: the cut falls inside the key, and whitespace collapses after it.
    (400, None, _BODY_TAIL_ECHO),
    # A transport that already cut its body at 500 characters, inside the key.
    (400, None, _BODY_TAIL_ECHO[:500]),
    (0, None, _BODY_TAIL_ECHO[:500]),
])
def test_no_part_of_the_key_survives_a_cut(stage, answer, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    transport = FakeTransport()
    transport.answers[stage] = answer
    result = call(transport, cache_dir=str(tmp_path / "c"))
    assert result.status == dtools.STATUS_UNAVAILABLE
    assert key_fragments(repr(dataclasses.asdict(result))) == []
    assert key_fragments(caplog.text) == []


def test_no_part_of_the_key_survives_a_metadata_clip(tmp_path):
    cache_dir = tmp_path / "c"
    transport = FakeTransport(series=meta(title="T" * 230 + KEY, units="U" * 150 + KEY))
    result = call(transport, cache_dir=str(cache_dir))
    assert result.status == dtools.STATUS_OK
    assert key_fragments(repr(dataclasses.asdict(result))) == []
    assert all(key_fragments(path.read_text(encoding="utf-8")) == [] for path in cache_dir.iterdir())


@pytest.mark.parametrize("stage, payload", [
    ("series", {"error_message": "partial answer"}),
    ("series", {"seriess": None}),
    ("series", {"seriess": {"id": "CPIAUCSL"}}),
    ("series", {"seriess": [None]}),
    ("series", {"seriess": ["CPIAUCSL"]}),
    ("series/observations", {"error_message": "partial answer"}),
    ("series/observations", {"observations": None}),
    ("series/observations", {"observations": {"date": "2020-03-01", "value": "1.0"}}),
])
@pytest.mark.parametrize("pin", [PAST, TODAY])
def test_a_200_without_the_list_is_unavailable_never_an_absence(stage, payload, pin, cache):
    transport = FakeTransport()
    transport.answers[stage] = (200, payload, "")
    result = call(transport, as_of=pin, pit=pin, cache=cache)
    assert result.status == dtools.STATUS_UNAVAILABLE and result.detail.startswith("FRED answered ")
    assert not any(claim in result.detail for claim in ("no vintage", "no series", "no observation"))
    assert len(transport.calls) == (1 if stage == "series" else 2)
    assert_pinned(transport.calls, pin, pin)
    assert not os.path.isdir(cache.root) or not os.listdir(cache.root)


@pytest.mark.parametrize("pin", [PAST, TODAY])
def test_an_empty_observation_list_is_not_found(pin):
    transport = FakeTransport(obs=observations([]))
    result = call(transport, as_of=pin, pit=pin)
    assert result.status == dtools.STATUS_NOT_FOUND and "holds no observation" in result.detail
    assert "Monthly" in result.detail and len(transport.calls) == 2


def test_the_default_transport_redacts_an_echoed_key_before_its_own_cut(monkeypatch):
    import httpx

    monkeypatch.setattr(logging.getLogger("httpx"), "filters", list(logging.getLogger("httpx").filters))

    class Echo:
        status_code = 400
        text = _BODY_TAIL_ECHO

        def json(self):
            raise ValueError("no JSON")

    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: Echo())
    code, payload, text = dtools._httpx_transport("https://x.test/fred/series", {"api_key": KEY}, 1, {})
    assert (code, payload, len(text)) == (400, None, 500) and key_fragments(text) == []
    result = dtools.fred_series("cpi", as_of=TODAY, pit=TODAY, key=KEY, now=NOW, cache=NoCache())
    assert result.status == dtools.STATUS_UNAVAILABLE
    assert key_fragments(repr(dataclasses.asdict(result))) == []


@pytest.mark.parametrize("series", [
    "x" * 60 + KEY,
    # Not strings: their text form would hold the key where the 80-character clip falls.
    ["x" * 55 + KEY],
    b"x" * 60 + KEY.encode(),
    {"q": "x" * 55 + KEY},
    ("x" * 55 + KEY,),
    type("x" * 60 + KEY, (), {})(),
])
def test_an_invalid_series_echo_never_holds_part_of_the_key(series):
    transport = FakeTransport()
    result = call(transport, series=series)
    assert result.status == dtools.STATUS_INVALID_INPUT and transport.calls == []
    assert key_fragments(repr(dataclasses.asdict(result))) == []
    if isinstance(series, str):
        assert result.detail.startswith("'" + "x" * 60 + "[redacted]'")
    else:
        assert result.detail.startswith("a ") and " value is not a FRED series" in result.detail


def test_a_past_vintage_repeat_call_makes_zero_transport_calls(cache):
    first, second = FakeTransport(), FakeTransport()
    one = call(first, as_of=PAST, pit=PAST, cache=cache)
    two = call(second, as_of=PAST, pit=PAST, cache=cache)
    assert len(first.calls) == 2 and second.calls == []
    assert one == two
    entry = json.loads(Path(cache.path(f"fred|CPIAUCSL|{PAST}|{PAST}|10")).read_text(encoding="utf-8"))
    assert entry["ttl_s"] == 30 * 86400


def test_values_below_one_millionth_round_trip_through_the_cache(cache):
    # str(Decimal("0.0000002")) is "2E-7": cached that way, the entry failed its own parse on every read.
    values = ["0.0000001"] + ["0.0000000"] * 11 + ["0.0000002"]
    first = FakeTransport(obs=observations(monthly(dt.date(2019, 3, 1), values)))
    one = call(first, as_of=PAST, pit=PAST, cache=cache)
    assert one.status == dtools.STATUS_OK and "Latest: 0.0000002 (2020-03-01)" in one.page_text
    assert one.facts[0]["value"] == "0.0000002" and one.facts[0]["text"] == "0.0000002"
    entry = json.loads(Path(cache.path(f"fred|CPIAUCSL|{PAST}|{PAST}|10")).read_text(encoding="utf-8"))
    assert [value for _, value in entry["payload"]["observations"]] == values
    second = FakeTransport()
    assert call(second, as_of=PAST, pit=PAST, cache=cache) == one
    assert second.calls == []


def test_a_same_day_vintage_expires_after_the_ttl(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_FRED_CACHE_TTL_H", "1")
    clock = [1_000_000.0]
    cache = dtools._DiskCache(str(tmp_path / "c"), 3600, clock=lambda: clock[0])
    transports = [FakeTransport() for _ in range(3)]
    call(transports[0], cache=cache)
    clock[0] += 3599
    call(transports[1], cache=cache)
    clock[0] += 2
    call(transports[2], cache=cache)
    assert [len(t.calls) for t in transports] == [2, 0, 2]


def test_ttl_zero_does_not_cache_todays_vintage(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_FRED_CACHE_TTL_H", "0")
    cache = dtools._DiskCache(str(tmp_path / "c"), 3600)
    first, second = FakeTransport(), FakeTransport()
    call(first, cache=cache)
    call(second, cache=cache)
    assert len(first.calls) == len(second.calls) == 2


def test_a_lowered_ttl_shortens_entries_already_cached_at_todays_vintage(tmp_path, monkeypatch):
    clock = [1_000_000.0]
    cache = dtools._DiskCache(str(tmp_path / "c"), 3600, clock=lambda: clock[0])
    call(FakeTransport(), cache=cache)
    entry = json.loads(Path(cache.path(f"fred|CPIAUCSL|{TODAY}|{TODAY}|10")).read_text(encoding="utf-8"))
    assert entry["ttl_s"] == 6 * 3600                 # written under the default 6 hours
    clock[0] += 3601
    monkeypatch.setenv("DATA_FRED_CACHE_TTL_H", "1")
    second = FakeTransport()
    call(second, cache=cache)
    assert len(second.calls) == 2                     # older than the current 1 hour: a miss
    monkeypatch.setenv("DATA_FRED_CACHE_TTL_H", "0")
    third = FakeTransport()
    call(third, cache=cache)
    assert len(third.calls) == 2                      # 0: today's vintage is never served from the cache


def test_the_open_vintage_ttl_never_shortens_a_closed_vintage(cache, monkeypatch):
    call(FakeTransport(), as_of=PAST, pit=PAST, cache=cache)
    monkeypatch.setenv("DATA_FRED_CACHE_TTL_H", "0")
    again = FakeTransport()
    assert call(again, as_of=PAST, pit=PAST, cache=cache).status == dtools.STATUS_OK
    assert again.calls == []


def test_provenance_says_when_fred_answered_and_a_cache_hit_keeps_it(cache):
    one = call(FakeTransport(), as_of=PAST, pit=PAST, cache=cache)
    later = FakeTransport()
    two = call(later, as_of=PAST, pit=PAST, cache=cache, now=NOW + dt.timedelta(hours=3))
    assert later.calls == []
    assert one.provenance["fetched_at"] == two.provenance["fetched_at"] == "2026-09-30T17:00:00Z"
    path = Path(cache.path(f"fred|CPIAUCSL|{PAST}|{PAST}|10"))
    entry = json.loads(path.read_text(encoding="utf-8"))
    del entry["payload"]["fetched_at"]
    path.write_text(json.dumps(entry), encoding="utf-8")
    refetch = FakeTransport()
    assert call(refetch, as_of=PAST, pit=PAST, cache=cache).status == dtools.STATUS_OK
    assert len(refetch.calls) == 2                    # an entry without fetched_at is a miss


def test_failures_are_never_cached(cache):
    failing = FakeTransport(obs=(503, None, ""))
    assert call(failing, as_of=PAST, pit=PAST, cache=cache).status == dtools.STATUS_UNAVAILABLE
    assert not os.path.isdir(cache.root) or not os.listdir(cache.root)
    retry = FakeTransport()
    assert call(retry, as_of=PAST, pit=PAST, cache=cache).status == dtools.STATUS_OK
    assert len(retry.calls) == 2
    assert not cache.put("k", {"status": dtools.STATUS_NO_VINTAGE})


@pytest.mark.parametrize("content", [
    "not json",
    '{"stored_at": 1, "ttl_s": 99999999999, "payload": {"status": "ok", "series_id"',
    '{"stored_at": 1, "ttl_s": 99999999999, "payload": {"status": "ok"}}',
    '[1, 2, 3]',
    '{"stored_at": "yesterday", "ttl_s": 1, "payload": {"status": "ok"}}',
])
def test_a_corrupt_cache_file_is_a_miss(content, cache):
    path = Path(cache.path(f"fred|CPIAUCSL|{PAST}|{PAST}|10"))
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    transport = FakeTransport()
    result = call(transport, as_of=PAST, pit=PAST, cache=cache)
    assert result.status == dtools.STATUS_OK and len(transport.calls) == 2
    assert json.loads(path.read_text(encoding="utf-8"))["payload"]["series_id"] == "CPIAUCSL"


def test_a_cached_snapshot_of_another_series_is_a_miss(cache):
    call(FakeTransport(), as_of=PAST, pit=PAST, cache=cache)
    path = Path(cache.path(f"fred|CPIAUCSL|{PAST}|{PAST}|10"))
    entry = json.loads(path.read_text(encoding="utf-8"))
    entry["payload"]["series_id"] = "GDP"
    path.write_text(json.dumps(entry), encoding="utf-8")
    transport = FakeTransport()
    assert call(transport, as_of=PAST, pit=PAST, cache=cache).status == dtools.STATUS_OK
    assert len(transport.calls) == 2


def test_the_default_cache_lives_in_DATA_TOOLS_CACHE_DIR(tmp_path):
    first, second = FakeTransport(), FakeTransport()
    for transport in (first, second):
        dtools.fred_series("cpi", as_of=PAST, pit=PAST, key=KEY, transport=transport, now=NOW)
    assert len(first.calls) == 2 and second.calls == []
    assert len(list((tmp_path / "default_cache").glob("*.json"))) == 1
    assert dtools._DiskCache(dtools._cache_root(), 1).root == str(tmp_path / "default_cache")


# ---------------------------------------------------------------------------
# Knobs, transport and throttle
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("env, argument, as_of, expected_start", [
    (None, None, dt.date(2026, 9, 30), "2016-09-30"),
    (None, 1, dt.date(2024, 2, 29), "2023-02-28"),
    ("99", None, dt.date(2024, 2, 29), "1984-02-29"),
    ("abc", None, dt.date(2026, 9, 30), "2016-09-30"),
    (None, 0, dt.date(2026, 9, 30), "2025-09-30"),
    ("3", None, dt.date(2026, 9, 30), "2023-09-30"),
    # A whole number that arrives as a float or a string (a tool argument) is honoured, never the default.
    ("3", 5.0, dt.date(2026, 9, 30), "2021-09-30"),
    ("3", "5", dt.date(2026, 9, 30), "2021-09-30"),
    ("3", " 7.0 ", dt.date(2026, 9, 30), "2019-09-30"),
    (None, 500.0, dt.date(2026, 9, 30), "1986-09-30"),
])
def test_window_years_knob_is_clamped_and_leap_day_safe(env, argument, as_of, expected_start, monkeypatch):
    if env is not None:
        monkeypatch.setenv("DATA_FRED_WINDOW_YEARS", env)
    transport = FakeTransport()
    call(transport, as_of=as_of, pit=min(as_of, TODAY), window_years=argument)
    assert transport.calls[1]["params"]["observation_start"] == expected_start


@pytest.mark.parametrize("value", [5.5, "abc", "", "5 years", True, float("nan"), float("inf"), [5]])
def test_an_unusable_window_is_invalid_input_with_zero_calls(value):
    transport = FakeTransport()
    result = call(transport, window_years=value)
    assert result.status == dtools.STATUS_INVALID_INPUT and "window_years" in result.detail
    assert transport.calls == []


def test_timeout_knob(monkeypatch):
    monkeypatch.setenv("DATA_TOOL_TIMEOUT_S", "7")
    transport = FakeTransport()
    call(transport)
    assert [request["timeout"] for request in transport.calls] == [7.0, 7.0]


def test_default_transport_offline(monkeypatch):
    import httpx

    monkeypatch.setattr(logging.getLogger("httpx"), "filters", list(logging.getLogger("httpx").filters))

    def refuse(*_args, **_kwargs):
        raise httpx.ConnectTimeout(f"timed out: https://api.stlouisfed.org/fred/series?api_key={KEY}")

    monkeypatch.setattr(httpx, "get", refuse)
    assert dtools._httpx_transport("https://api.stlouisfed.org/fred/series", {"api_key": KEY}, 1, {}) == (
        0, None, "ConnectTimeout")

    class Response:
        status_code = 200
        text = '{"seriess": []}' + " " * 600

        def json(self):
            return {"seriess": []}

    seen = {}

    def answer(url, **kwargs):
        seen.update(kwargs, url=url)
        return Response()

    monkeypatch.setattr(httpx, "get", answer)
    code, payload, text = dtools._httpx_transport("https://x.test/fred/series", {"series_id": "GDP"}, 3.0,
                                                  {"Accept": "application/json"})
    assert (code, payload, len(text)) == (200, {"seriess": []}, 500)
    assert seen["timeout"] == 3.0 and seen["params"] == {"series_id": "GDP"}
    assert "follow_redirects" not in seen          # httpx.get does not follow redirects by default

    class NotJson(Response):
        def json(self):
            raise ValueError("no JSON")

    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: NotJson())
    assert dtools._httpx_transport("https://x.test", {}, 1, {})[1] is None


def test_httpx_request_log_line_is_redacted(caplog):
    httpx_logger = logging.getLogger("httpx")
    before = list(httpx_logger.filters)
    try:
        dtools._install_httpx_redaction()
        dtools._install_httpx_redaction()
        assert sum(isinstance(item, dtools._RedactSecretParams) for item in httpx_logger.filters) == 1
        with caplog.at_level(logging.INFO, logger="httpx"):
            httpx_logger.info('HTTP Request: %s %s "%s %d %s"', "GET",
                              f"https://api.stlouisfed.org/fred/series?series_id=GDP&api_key={KEY}&file_type=json",
                              "HTTP/1.1", 200, "OK")
        assert KEY not in caplog.text
        assert "api_key=REDACTED&file_type=json" in caplog.text and '"HTTP/1.1 200 OK"' in caplog.text
    finally:
        httpx_logger.filters[:] = before


def test_throttle_spaces_requests():
    now = [100.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(round(seconds, 6))
        now[0] += seconds

    throttle = dtools._Throttle(0.5, clock=lambda: now[0], sleep=sleep)
    throttle.wait()
    now[0] += 0.2
    throttle.wait()
    now[0] += 1.0
    throttle.wait()
    assert sleeps == [0.3]
    assert dtools._FRED_THROTTLE.min_interval_s == 0 and dtools._Throttle(0.5).min_interval_s == 0.5


class CountingThrottle(dtools._Throttle):
    def __init__(self):
        super().__init__(0)
        self.waits = 0

    def wait(self):
        self.waits += 1


def test_every_sent_request_and_only_those_waits_on_the_throttle(monkeypatch, cache):
    throttle = CountingThrottle()
    monkeypatch.setattr(dtools, "_FRED_THROTTLE", throttle)
    fresh = FakeTransport()
    call(fresh, as_of=PAST, pit=PAST, cache=cache)
    assert throttle.waits == len(fresh.calls) == 2
    hit, refused = FakeTransport(), FakeTransport()
    call(hit, as_of=PAST, pit=PAST, cache=cache)       # a cache hit sends nothing
    call(refused, series="bank of japan rate")        # rejected before any request
    dtools._fred_get(refused, "series", {"series_id": "GDP"}, key=KEY, pit=TODAY, as_of=TODAY, timeout=1)
    assert hit.calls == refused.calls == [] and throttle.waits == 2
    failing = FakeTransport(series=(503, None, ""))
    call(failing, cache=cache)
    assert len(failing.calls) == 1 and throttle.waits == 3


# ---------------------------------------------------------------------------
# Inert, self-contained, attributed
# ---------------------------------------------------------------------------

def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_module_is_self_contained_and_inert_until_bound():
    """Flag-off equivalent: nothing in the runtime imports data_tools yet (TIME-13 binds it), so
    every run is unchanged; the module itself imports only the stdlib and httpx."""
    source = _REPO / "deerflow_bridge" / "data_tools.py"
    assert _imported_modules(source) <= set(sys.stdlib_module_names) | {"httpx"}
    importers = []
    for root in ("backend/app", "backend/scripts", "deerflow_bridge", "drf2"):
        for path in (_REPO / root).rglob("*.py"):
            parts = path.relative_to(_REPO).parts
            if any(part.startswith(".") or part in ("node_modules", "__pycache__") for part in parts):
                continue
            if path != source and "data_tools" in _imported_modules(path):
                importers.append(str(path.relative_to(_REPO)))
    assert importers == []


def test_notice_and_header_carry_the_tradingagents_attribution():
    notice = (_REPO / "NOTICE").read_text(encoding="utf-8")
    assert "TradingAgents" in notice and "Apache License, Version 2.0" in notice
    assert "deerflow_bridge/data_tools.py" in notice and "tradingagents/dataflows/vendors/fred.py" in notice
    header = (_REPO / "deerflow_bridge" / "data_tools.py").read_text(encoding="utf-8")[:600]
    assert ("Portions adapted from TradingAgents 0.5.1 tradingagents/dataflows/vendors/fred.py (Apache-2.0)"
            in header)
