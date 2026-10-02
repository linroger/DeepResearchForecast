"""TIME-2: deerflow_bridge/source_dates.py — publication-date parsing and extraction.

Pure, offline tests: the UTC calendar rules (offsets applied, offset-less
values and epochs read as UTC whatever the host zone), the precision of each
accepted form, future / pre-1900 rejection, every candidate extractor, the
rank order of :func:`resolve` and linear-time behaviour on adversarial input.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import time

import pytest

_BRIDGE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "deerflow_bridge")
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

import source_dates as sd  # noqa: E402

NOW = dt.datetime(2026, 9, 30, 12, 0, tzinfo=dt.timezone.utc)


def parsed(value, now=NOW):
    date, reason = sd.parse_published(value, now=now, source="test")
    assert reason is None, (value, reason)
    return date


@pytest.fixture
def host_zone():
    """Switch the host time zone (TZ + time.tzset) and restore it afterwards."""
    if not hasattr(time, "tzset"):
        pytest.skip("time.tzset is POSIX-only")
    original = os.environ.get("TZ")

    def switch(zone: str) -> None:
        os.environ["TZ"] = zone
        time.tzset()

    yield switch
    if original is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = original
    time.tzset()


# =============================================================== parse_published

def test_offset_is_converted_to_utc_before_the_date_is_taken():
    date = parsed("2025-05-10T01:00:00+05:00")
    assert (date.value, date.precision, date.instant) == ("2025-05-09", "day", "2025-05-09T20:00:00Z")
    assert date.source == "test" and date.raw == "2025-05-10T01:00:00+05:00"


def test_zulu_end_of_day_stays_on_its_day():
    assert parsed("2025-05-09T23:59:59Z").value == "2025-05-09"
    assert parsed("2025-05-09T10:00:00.000Z").instant == "2025-05-09T10:00:00Z"


@pytest.mark.parametrize("zone", ["Asia/Tokyo", "America/New_York"])
def test_offset_less_timestamp_is_utc_whatever_the_host_zone(host_zone, zone):
    host_zone(zone)
    date = parsed("2025-05-09T23:00:00")
    assert (date.value, date.instant) == ("2025-05-09", "2025-05-09T23:00:00Z")
    naive = parsed(dt.datetime(2025, 5, 9, 23, 0))
    assert (naive.value, naive.instant) == ("2025-05-09", "2025-05-09T23:00:00Z")


@pytest.mark.parametrize("zone", ["Asia/Tokyo", "America/New_York"])
def test_epoch_seconds_and_milliseconds_are_the_same_utc_date_in_any_zone(host_zone, zone):
    host_zone(zone)
    seconds, millis = parsed(1715212800), parsed(1715212800000)
    as_text = parsed("1715212800")
    assert seconds.value == millis.value == as_text.value == "2024-05-09"
    assert seconds.instant == millis.instant == "2024-05-09T00:00:00Z"


@pytest.mark.parametrize("value, expected, precision", [
    ("May 9, 2025", "2025-05-09", "day"),
    ("Sept. 9, 2025", "2025-09-09", "day"),
    ("Friday, May 9, 2025", "2025-05-09", "day"),
    ("9 May 2025", "2025-05-09", "day"),
    ("May 9, 2025 10:00 AM ET", "2025-05-09", "day"),
    ("May 2025", "2025-05", "month"),
    ("2025年5月9日", "2025-05-09", "day"),
    ("2025年5月", "2025-05", "month"),
    ("2025/05/09", "2025-05-09", "day"),
    ("2025-05-09", "2025-05-09", "day"),
    ("20250509", "2025-05-09", "day"),
    ("2025-05", "2025-05", "month"),
    ("2025", "2025", "year"),
    (2025, "2025", "year"),
    (dt.date(2025, 5, 9), "2025-05-09", "day"),
])
def test_accepted_forms_keep_their_precision(value, expected, precision):
    date = parsed(value)
    assert (date.value, date.precision) == (expected, precision)
    if precision != "day" or not isinstance(value, str) or ":" not in value:
        assert date.instant is None


def test_rfc_2822_is_converted_to_utc():
    assert parsed("Fri, 09 May 2025 10:00:00 GMT").instant == "2025-05-09T10:00:00Z"
    assert parsed("Sat, 10 May 2025 01:00:00 +0500").value == "2025-05-09"


def test_future_and_pre_1900_are_rejected_never_clamped():
    two_days = (NOW + dt.timedelta(days=2)).date().isoformat()
    assert sd.parse_published(two_days, now=NOW) == (None, "future")
    assert sd.parse_published(NOW + dt.timedelta(days=2), now=NOW) == (None, "future")
    # The interval START decides: this month and this year are not future.
    assert parsed("2026-09").value == "2026-09" and parsed("2026").value == "2026"
    assert sd.parse_published("2026-10", now=NOW) == (None, "future")
    # A +05:00 time after midnight of tomorrow is still today in UTC.
    assert parsed("2026-10-01T03:00:00+05:00").value == "2026-09-30"
    assert sd.parse_published("1850-01-01", now=NOW) == (None, "pre_1900")


@pytest.mark.parametrize("value", [None, {}, [], "", "   ", "garbage", "Mayor 9, 2025", "2025-13-01", "2025-02-30",
                                   True, float("nan"), float("inf"), 0, -1, "2025-05-09T25:00:00Z", object(),
                                   "2025-05-09T10:00:00+99:00",
                                   # A month or day of 0 is no calendar date (never emitted as "2025-05-00").
                                   "2025-00", "2025-05-00", "2025-00-00", "2019/05/00", "20250500", "May 0, 2025",
                                   "00 May 2025", "2025年0月", "2025年5月0日"])
def test_garbage_is_unparseable_without_raising(value):
    assert sd.parse_published(value, now=NOW) == (None, "unparseable")


def test_raw_is_capped_at_80_chars():
    date, reason = sd.parse_published("x" * 500, now=NOW)
    assert date is None and reason == "unparseable"
    candidates = sd.from_provider_meta({"publishedTime": "2025-05-09" + " " * 5 + "y" * 500})
    assert all(len(raw) <= sd.RAW_CHARS for *_, raw in candidates)


def test_interval_bounds():
    assert sd.interval_bounds("2025") == (dt.date(2025, 1, 1), dt.date(2025, 12, 31))
    assert sd.interval_bounds("2024-02") == (dt.date(2024, 2, 1), dt.date(2024, 2, 29))
    assert sd.interval_bounds("2025-12") == (dt.date(2025, 12, 1), dt.date(2025, 12, 31))
    assert sd.interval_bounds("2025-05-09") == (dt.date(2025, 5, 9), dt.date(2025, 5, 9))
    for bad in ("", None, "May 2025", "2025-13", "2025-05-9"):
        assert sd.interval_bounds(bad) == (None, None)


def test_to_utc():
    naive = dt.datetime(2025, 5, 9, 23, 0)
    assert sd.to_utc(naive) == dt.datetime(2025, 5, 9, 23, 0, tzinfo=dt.timezone.utc)
    aware = dt.datetime(2025, 5, 10, 1, 0, tzinfo=dt.timezone(dt.timedelta(hours=5)))
    assert sd.to_utc(aware) == dt.datetime(2025, 5, 9, 20, 0, tzinfo=dt.timezone.utc)


# =============================================================== extractors

def test_provider_meta_list_values_and_both_roles():
    meta = {"title": "Page", "publishedTime": ["2025-05-09T10:00:00Z", "2025-05-01"],
            "MODIFIEDTIME": "2025-06-01", "ogUrl": "https://x", "article:published_time": None}
    assert sd.from_provider_meta(meta) == [
        (7, "provider_meta", "published", "2025-05-09T10:00:00Z"),
        (7, "provider_meta", "published", "2025-05-01"),
        (7, "provider_meta", "modified", "2025-06-01"),
    ]
    resolved = sd.resolve(sd.from_provider_meta(meta), now=NOW)
    assert resolved["published"].value == "2025-05-09" and resolved["modified"].value == "2025-06-01"
    assert resolved["rank"] == 7 and resolved["rejected"] == []
    assert sd.from_provider_meta(None) == [] and sd.from_provider_meta("x") == []


def test_every_listed_meta_key_is_recognised_case_insensitively():
    for key in sd.PUBLISHED_META_KEYS:
        assert sd.from_provider_meta({key.upper(): "2025-05-09"})[0][2] == "published", key
    for key in sd.MODIFIED_META_KEYS:
        assert sd.from_provider_meta({key.upper(): "2025-05-09"})[0][2] == "modified", key


def test_json_ld_dates():
    page = ('<html><head><script type="application/ld+json">{"@type": "NewsArticle", '
            '"datePublished": "2025-05-09T10:00:00+05:00", "dateModified" : "2025-06-01"}</script></head>')
    assert sd.from_html(page) == [(6, "json_ld", "published", "2025-05-09T10:00:00+05:00"),
                                  (6, "json_ld", "modified", "2025-06-01")]
    # Outside an ld+json script the same keys are not JSON-LD.
    assert sd.from_html('<script>var x = {"datePublished": "2025-05-09"};</script>') == []
    # Close tags match in any case: an upper-case </SCRIPT> ends its own script,
    # so the JSON-LD block after it is still read.
    for close in ("</SCRIPT>", "</Script >", "</script>"):
        page = (f'<SCRIPT>var x = 1;{close}<script type="application/ld+json">'
                '{"datePublished": "2025-05-09"}</script>')
        assert sd.from_html(page) == [(6, "json_ld", "published", "2025-05-09")], close
    assert sd.from_html('<SCRIPT TYPE="application/ld+json">{"datePublished": "2025-05-09"}</SCRIPT>'
                        '<script>var y = {"dateModified": "2025-06-01"};</script>') == [
        (6, "json_ld", "published", "2025-05-09")]


def test_meta_tags_in_both_attribute_orders():
    page = ('<meta property="article:published_time" content="2025-05-09T08:00:00Z">'
            "<meta content='2025-06-01' name='dateModified'>"
            '<meta itemprop="datePublished" content="2025-05-08"/>'
            '<meta name="description" content="2020-01-01">')
    assert sd.from_html(page) == [(5, "meta_tag", "published", "2025-05-09T08:00:00Z"),
                                  (5, "meta_tag", "modified", "2025-06-01"),
                                  (5, "meta_tag", "published", "2025-05-08")]


def test_time_tags():
    page = '<p>x</p><time class="t" datetime="2025-05-09T08:00:00Z">May 9</time><time>no attribute</time>'
    assert sd.from_html(page) == [(4, "time_tag", "published", "2025-05-09T08:00:00Z")]
    modified = '<time itemprop="dateModified" datetime="2025-06-01">'
    assert sd.from_html(modified) == [(4, "time_tag", "modified", "2025-06-01")]


def test_html_scan_is_limited_to_the_head_of_the_page():
    late = "x" * sd.HTML_SCAN_CHARS + '<meta property="article:published_time" content="2025-05-09">'
    assert sd.from_html(late) == []
    assert sd.from_html(None) == [] and sd.from_html(b"<meta>") == []


def test_text_head_datelines():
    text = "\n".join([
        "# Grid report",
        "",
        "Published: May 9, 2025",
        "**Posted on:** 3 May 2024",
        "发布时间：2025年5月9日",
        "Updated: 2025-06-01",
        "Last updated June 2, 2025",
        "更新时间: 2025-06-03",
        "Date: 2024-01-02",
        "Date of birth 1950-01-01",
        "The report was published: in 2020 (no date right after the label)",
        "Published Time: 2025-05-09T10:00:00.000Z",
    ])
    assert sd.from_text_head(text) == [
        (3, "text_head", "published", "May 9, 2025"),
        (3, "text_head", "published", "3 May 2024"),
        (3, "text_head", "published", "2025年5月9日"),
        (3, "text_head", "modified", "2025-06-01"),
        (3, "text_head", "modified", "June 2, 2025"),
        (3, "text_head", "modified", "2025-06-03"),
        (3, "text_head", "published", "2024-01-02"),
        (3, "text_head", "published", "2025-05-09T10:00:00.000Z"),
    ]


def test_text_head_reads_only_the_first_lines():
    text = "\n" * 40 + "Published: May 9, 2025"
    assert sd.from_text_head(text) == []
    assert sd.from_text_head(text, max_lines=41) == [(3, "text_head", "published", "May 9, 2025")]
    assert sd.from_text_head(None) == []


@pytest.mark.parametrize("url, expected", [
    ("https://news.example.com/2025/05/09/grid-queues", [(2, "url_path", "published", "2025-05-09")]),
    ("https://news.example.com/2025/5/9", [(2, "url_path", "published", "2025-05-09")]),
    ("https://news.example.com/2025/05/grid-queues", [(2, "url_path", "published", "2025-05")]),
    ("https://news.example.com/news/2025-05-09-grid", [(2, "url_path", "published", "2025-05-09")]),
    ("https://news.example.com/20250509/grid", [(2, "url_path", "published", "2025-05-09")]),
    ("https://news.example.com/20251399/grid", []),
    ("https://news.example.com/a/b?date=2025-01-01&y=2025/01/02", []),
    ("https://news.example.com/2025/13/09/x", []),
    ("https://news.example.com/2025/05/", []),
    ("https://news.example.com/report-2025.pdf", []),
    ("not a url", []),
    (None, []),
])
def test_url_path_dates(url, expected):
    assert sd.from_url(url) == expected


def test_fetch_meta_combines_provider_keys_and_stored_html_candidates():
    meta = {"publishedTime": "2025-05-09", sd.HTML_DATES_KEY: [
        [6, "json_ld", "published", "2025-05-08"], [5, "meta_tag", "modified", "2025-06-01"],
        [9, "json_ld", "published", "2025-01-01"],     # not an HTML rank
        [5, "meta_tag", "other", "2025-01-01"],        # unknown role
        [True, "json_ld", "published", "2025-01-01"],  # bool is no rank
        "garbage"]}
    assert sd.from_fetch_meta(meta) == [(7, "provider_meta", "published", "2025-05-09"),
                                        (6, "json_ld", "published", "2025-05-08"),
                                        (5, "meta_tag", "modified", "2025-06-01")]
    assert sd.from_fetch_meta(None) == []


# =============================================================== resolve

def test_resolve_honours_rank_order_and_keeps_the_first_on_a_tie():
    candidates = [
        (2, "url_path", "published", "2025-05"),
        (3, "text_head", "published", "May 1, 2025"),
        (7, "provider_meta", "published", "2099-01-01"),       # future: rejected
        (6, "json_ld", "published", "2025-05-09T10:00:00Z"),
        (6, "json_ld", "published", "2025-05-02"),              # tie: first wins
        (5, "meta_tag", "modified", "not a date"),
        (4, "time_tag", "modified", "2025-06-01"),
        (9, "provider_meta", "unknown-role", "2025-01-01"),
        "garbage", (1, 2), None,
    ]
    resolved = sd.resolve(candidates, now=NOW)
    assert resolved["published"].value == "2025-05-09" and resolved["published"].source == "json_ld"
    assert resolved["rank"] == 6
    assert resolved["modified"].value == "2025-06-01"
    assert resolved["rejected"] == ["future", "unparseable"]


def test_resolve_skips_an_invalid_high_rank_date_for_a_valid_url_date():
    # A provider "citation_publication_date" of 2019/05/00 is no date: it must
    # not become "2019-05-00" nor block the valid rank-2 URL date.
    candidates = (sd.from_provider_meta({"citation_publication_date": "2019/05/00"})
                  + sd.from_url("https://x.org/2019/05/12/story"))
    resolved = sd.resolve(candidates, now=NOW)
    assert resolved["published"].value == "2019-05-12" and resolved["published"].source == "url_path"
    assert resolved["rank"] == sd.RANK_URL and resolved["rejected"] == ["unparseable"]


def test_resolve_without_a_parseable_candidate():
    resolved = sd.resolve([(7, "provider_meta", "published", "1850-01-01")], now=NOW)
    assert resolved == {"published": None, "modified": None, "rank": 0, "rejected": ["pre_1900"]}
    assert sd.resolve([], now=NOW)["published"] is None
    assert sd.resolve(None, now=NOW)["rejected"] == []


# =============================================================== linear time

_ADVERSARIAL = {
    "script_open": '<script type="application/ld+json">' * 6000,
    "script_pairs": '<SCRIPT type="application/ld+json"></ScRiPt>' * 4500,
    "ld_no_close": '<script type="application/ld+json">' + '"datePublished": "' * 11000,
    "meta_open": "<meta " * 34000,
    "meta_attributes": "<meta " + "a=" * 100000,
    "meta_long": ("<meta " + "x" * 999 + " ") * 198,
    "time_open": "<time datetime=" * 13000,
    "angle_brackets": "<" * 200000,
    "digits": "1" * 200000,
    "dates": "2025-" * 40000,
    "months": "May " * 50000,
    "datelines": "Published: May 9, " * 11000,
    "cjk": "2025年" * 40000,
    "paths": "/2025" * 40000,
    "open_quote": '<meta content="' + "x" * 200000,
}


@pytest.mark.parametrize("name", sorted(_ADVERSARIAL))
def test_every_regex_finishes_quickly_on_a_200k_adversarial_string(name):
    text = _ADVERSARIAL[name]
    assert len(text) >= 190_000
    started = time.perf_counter()
    candidates = sd.from_html(text) + sd.from_text_head(text) + sd.from_url("https://x.org" + text)
    candidates += sd.from_provider_meta({"publishedTime": text})
    sd.resolve(candidates, now=NOW)
    sd.parse_published(text, now=NOW)
    sd.interval_bounds(text)
    assert time.perf_counter() - started < 1.0
