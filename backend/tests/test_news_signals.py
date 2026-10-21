"""Offline OS-1 scenarios through the frozen public context API.

Run with ``backend/scripts/main_offline_pytest.py`` from a fresh source mirror.
All provider responses and authentication values below are synthetic. Child
fixtures are admitted by that same runner, retaining its audit boundary.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import errno
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import types
from urllib.parse import parse_qs, urlsplit

import pytest

from deerflow_bridge import news_signals as news


QUESTION = "Will semiconductor capacity grow by the end of 2026?"
AS_OF = "2026-10-18T12:00:00Z"
SENTINEL = "offline-newsapi-sentinel"
CANONICAL_STATES = {
    "ok", "verified_empty", "disabled", "unavailable", "forbidden",
    "rate_limited", "timeout", "budget_exhausted", "partial", "unsupported",
}


def article(number=1, **changes):
    value = {
        "source": {"id": "fixture-publisher", "name": "Fixture Publisher"},
        "author": "Fixture Author",
        "title": f"Capacity announcement {number}",
        "description": "An attributed article discovery snippet.",
        "url": f"https://publisher.example/news/capacity-{number}",
        "publishedAt": "2026-10-17T09:00:00Z",
        "content": "A search result is not a fetched publisher page.",
    }
    value.update(changes)
    return value


def response(*articles):
    return 200, json.dumps({
        "status": "ok", "totalResults": len(articles), "articles": list(articles),
    }).encode()


class Transport:
    def __init__(self, *replies, delay=0):
        self.replies = replies or (response(article()),)
        self.delay = delay
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, url, *, headers, timeout, max_bytes):
        with self.lock:
            index = len(self.calls)
            self.calls.append({
                "url": url, "headers": dict(headers),
                "timeout": timeout, "max_bytes": max_bytes,
            })
        if self.delay:
            time.sleep(self.delay)
        reply = self.replies[min(index, len(self.replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            return reply(max_bytes)
        return reply


@pytest.fixture(autouse=True)
def isolated_provider_config(monkeypatch):
    monkeypatch.setenv("NEWSAPI_ENABLED", "true")
    monkeypatch.setenv("REDDIT_SIGNALS_ENABLED", "false")
    monkeypatch.setenv("NEWSAPI_MAX_REQUESTS", "2")
    monkeypatch.setenv("NEWSAPI_API_KEY", SENTINEL)
    monkeypatch.delenv("DEERFLOW_RUN_ARTIFACT_DIR", raising=False)


def client(root, transport=None, **options):
    arguments = {
        "question": QUESTION, "language": "en", "as_of": AS_OF,
        "transport": transport if transport is not None else Transport(),
        "api_key": SENTINEL, "news_enabled": True,
        "social_enabled": False, "max_news_requests": 2,
    }
    arguments.update(options)
    return news.ContextClient(root, **arguments)


def state(result, expected, *, attempted):
    assert result["status"]["state"] in CANONICAL_STATES
    assert result["status"]["state"] == expected
    assert result["status"]["attempted"] is attempted
    assert isinstance(result["items"], list)
    assert result["provider"]
    assert result["query"]
    assert result["retrieved_at"]


def digest(envelope):
    payload = {key: value for key, value in envelope.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode()).hexdigest()


def sealed_capture(root, *articles, query="capacity", source_refs=None):
    instance = client(root, Transport(response(*(articles or (article(),)))))
    instance.search_news(query)
    return instance.seal(source_refs=source_refs)


def test_news_request_uses_fixed_host_header_auth_and_bounded_page(tmp_path):
    transport = Transport()
    result = client(tmp_path, transport).search_news("capacity https://untrusted.example")
    state(result, "ok", attempted=True)
    assert len(transport.calls) == 1
    call = transport.calls[0]
    url = urlsplit(call["url"])
    assert (url.scheme, url.hostname, url.path) == (
        "https", "newsapi.org", "/v2/everything",
    )
    assert url.username is None and url.password is None
    parameters = parse_qs(url.query)
    assert not {key.lower() for key in parameters} & {"apikey", "api_key", "token"}
    assert SENTINEL not in call["url"]
    assert call["headers"]["X-Api-Key"] == SENTINEL
    assert parameters["language"] == ["en"]
    assert int(parameters["pageSize"][0]) <= 20
    assert parameters.get("page", ["1"]) == ["1"]
    assert parameters["to"][0].startswith("2026-10-18")
    assert 0 < call["timeout"] <= 5
    assert 0 < call["max_bytes"] <= 2 * 1024 * 1024
    assert SENTINEL not in json.dumps(result)


def test_articles_keep_evidence_identity_dates_language_and_context_eligibility(tmp_path):
    instance = client(tmp_path, Transport(response(article())))
    result = instance.search_news("capacity")
    item = result["items"][0]
    assert item["id"].startswith(result["provider"] + ":")
    assert item["provider"] == result["provider"]
    assert item["kind"] == "news_snippet"
    assert item["url"] == article()["url"]
    assert item["title"] == article()["title"]
    assert item["published_at"] == article()["publishedAt"]
    assert item["retrieved_at"]
    assert item["language"] == "en"
    assert item["query"] == "capacity"
    assert item["snippet"]
    assert item["eligibility"] == {
        "context_only": True, "anchor": False, "resolution": False,
    }
    assert item.get("fetched") is not True
    assert item.get("probability") is None
    assert SENTINEL not in json.dumps(instance.snapshot())


def test_future_articles_are_excluded_unknown_dates_are_never_invented_and_urls_dedupe(tmp_path):
    transport = Transport(response(
        article(), article(title="Duplicate article from the same publisher URL"),
        article(2, publishedAt="2026-10-19T09:00:00Z"),
        article(3, publishedAt=None), article(4, publishedAt="not-a-date"),
    ))
    items = client(tmp_path, transport).search_news("capacity")["items"]
    urls = [item["url"] for item in items]
    assert len(urls) == len(set(urls))
    assert article()["url"] in urls
    assert article(2)["url"] not in urls
    for item in items:
        if item["url"] in {article(3)["url"], article(4)["url"]}:
            assert item["published_at"] is None
        if item["published_at"] is not None:
            assert datetime.fromisoformat(item["published_at"].replace("Z", "+00:00")) <= (
                datetime.fromisoformat(AS_OF.replace("Z", "+00:00")))


def test_explicit_language_is_sent_and_preserved_without_synthetic_tone(tmp_path):
    transport = Transport(response(article(title="芯片产能扩建计划", description="已公布扩建计划。")))
    result = client(tmp_path, transport, language="zh").search_news("芯片产能")
    assert parse_qs(urlsplit(transport.calls[0]["url"]).query)["language"] == ["zh"]
    assert result["items"][0]["language"] == "zh"
    assert result["items"][0].get("probability") is None


def test_items_per_request_are_bounded_even_if_transport_ignores_page_size(tmp_path):
    transport = Transport(response(*(article(number) for number in range(35))))
    assert len(client(tmp_path, transport).search_news("capacity")["items"]) <= 20
    assert len(transport.calls) == 1


@pytest.mark.parametrize("status,expected", [(401, "forbidden"), (403, "forbidden"), (429, "rate_limited")])
def test_nonretryable_http_status_is_preserved_and_replayed(tmp_path, status, expected):
    transport = Transport((status, b'{"message":"untrusted-provider-body"}'))
    instance = client(tmp_path, transport)
    first = instance.search_news("capacity")
    state(first, expected, attempted=True)
    assert instance.search_news("capacity") == first
    assert len(transport.calls) == 1
    assert "untrusted-provider-body" not in json.dumps(first)
    assert instance.snapshot()["queries"]


@pytest.mark.parametrize("reply", [
    (200, b"not-json"), (200, b"[]"), (200, b"null"),
    (200, b'{"status":"ok","articles":"not-a-list"}'),
    (500, b"private-provider-response"),
    RuntimeError("untrusted-transport-detail"),
])
def test_failed_provider_is_unavailable_never_verified_empty_or_raw_error(tmp_path, reply):
    transport = Transport(reply)
    result = client(tmp_path, transport).search_news("capacity")
    state(result, "unavailable", attempted=True)
    assert result["items"] == []
    encoded = json.dumps(result)
    assert "private-provider-response" not in encoded
    assert "untrusted-transport-detail" not in encoded
    assert SENTINEL not in encoded


def test_oversized_transport_response_is_rejected_not_parsed(tmp_path):
    transport = Transport(lambda maximum: (200, b" " * (maximum + 1)))
    result = client(tmp_path, transport).search_news("capacity")
    state(result, "unavailable", attempted=True)
    assert result["items"] == []
    assert len(transport.calls) == 1


def test_genuine_empty_response_remains_distinct_from_failure(tmp_path):
    transport = Transport(response())
    instance = client(tmp_path, transport)
    result = instance.search_news("capacity")
    state(result, "verified_empty", attempted=True)
    assert result["items"] == []
    assert instance.search_news("capacity") == result
    assert len(transport.calls) == 1


def test_missing_key_is_unavailable_without_network(tmp_path):
    transport = Transport()
    result = client(tmp_path, transport, api_key="").search_news("capacity")
    state(result, "unavailable", attempted=False)
    assert transport.calls == []


def test_disabled_news_and_default_off_social_do_not_dispatch(tmp_path):
    transport = Transport()
    instance = client(tmp_path, transport, news_enabled=False)
    state(instance.search_news("capacity"), "disabled", attempted=False)
    state(instance.search_social("capacity"), "disabled", attempted=False)
    assert transport.calls == []


def test_missing_artifact_directory_is_unavailable_without_implicit_cwd_writes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    transport = Transport()
    result = client(None, transport).search_news("capacity")
    state(result, "unavailable", attempted=False)
    assert transport.calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("limit", [0, 1, 2, 10])
def test_distinct_news_queries_obey_configured_allowance_and_hard_cap(tmp_path, limit):
    transport = Transport()
    instance = client(tmp_path, transport, max_news_requests=limit)
    results = [instance.search_news(f"capacity query {number}") for number in range(4)]
    admitted = min(limit, 2)
    assert len(transport.calls) == admitted
    for result in results[admitted:]:
        state(result, "budget_exhausted", attempted=False)
    assert len(instance.snapshot()["items"]) <= 120


def test_failed_requests_still_consume_the_generation_allowance(tmp_path):
    transport = Transport((429, b"{}"))
    instance = client(tmp_path, transport)
    instance.search_news("first query")
    instance.search_news("second query")
    state(instance.search_news("third query"), "budget_exhausted", attempted=False)
    assert len(transport.calls) == 2


@pytest.mark.parametrize("restriction", ["attempts", "search-global", "search-lane"])
def test_existing_research_budget_can_deny_dispatch(tmp_path, monkeypatch, restriction):
    monkeypatch.setenv("RESEARCH_BUDGET_DB", str(tmp_path / "research-budget.sqlite3"))
    monkeypatch.setenv("RESEARCH_BUDGET_TELEMETRY_PATH", str(tmp_path / "research-budget.json"))
    monkeypatch.setenv("RESEARCH_BUDGET_ATTEMPTS_GLOBAL", "0" if restriction == "attempts" else "10")
    monkeypatch.setenv("RESEARCH_BUDGET_SEARCH_GLOBAL", "0" if restriction == "search-global" else "10")
    monkeypatch.setenv("RESEARCH_BUDGET_SEARCH_LANE", "0" if restriction == "search-lane" else "10")
    transport = Transport()
    result = client(tmp_path / "run", transport).search_news("capacity")
    state(result, "budget_exhausted", attempted=False)
    assert transport.calls == []


def test_reopened_clients_share_durable_replay_and_the_two_request_allowance(tmp_path):
    transport = Transport()
    original = client(tmp_path, transport)
    first = original.search_news("first query")
    reopened = client(tmp_path, transport)
    assert reopened.search_news("first query") == first
    reopened.search_news("second query")
    state(client(tmp_path, transport).search_news("third query"), "budget_exhausted", attempted=False)
    assert len(transport.calls) == 2


def test_identical_thread_queries_are_singleflight(tmp_path):
    transport = Transport(delay=0.04)
    clients = [client(tmp_path, transport) for _ in range(6)]
    barrier = threading.Barrier(len(clients))

    def request(instance):
        barrier.wait(timeout=3)
        return instance.search_news("same capacity query")

    with ThreadPoolExecutor(max_workers=len(clients)) as pool:
        results = list(pool.map(request, clients))
    assert len(transport.calls) == 1
    assert all(result == results[0] for result in results)
    assert len(news.load_context(tmp_path, require_sealed=False)["items"]) == 1


def test_distinct_thread_queries_cannot_race_past_two_requests(tmp_path):
    transport = Transport(delay=0.04)
    clients = [client(tmp_path, transport) for _ in range(6)]
    barrier = threading.Barrier(len(clients))

    def request(pair):
        number, instance = pair
        barrier.wait(timeout=3)
        return instance.search_news(f"capacity thread {number}")

    with ThreadPoolExecutor(max_workers=len(clients)) as pool:
        results = list(pool.map(request, enumerate(clients)))
    assert len(transport.calls) == 2
    assert sum(result["status"]["state"] == "budget_exhausted" for result in results) == 4


class RemainingDeadline:
    def __init__(self, seconds):
        self.seconds = seconds

    def remaining(self):
        return self.seconds


@pytest.mark.parametrize("deadline", [0.0, RemainingDeadline(0)])
def test_expired_deadline_never_dispatches(tmp_path, deadline):
    transport = Transport()
    result = client(tmp_path, transport).search_news("capacity", deadline=deadline)
    state(result, "timeout", attempted=False)
    assert transport.calls == []


@pytest.mark.parametrize("kind", ["absolute", "remaining"])
def test_shorter_caller_deadline_restricts_transport_timeout(tmp_path, kind):
    transport = Transport()
    deadline = time.monotonic() + 0.25 if kind == "absolute" else RemainingDeadline(0.25)
    client(tmp_path, transport).search_news("capacity", deadline=deadline)
    assert len(transport.calls) == 1
    assert 0 < transport.calls[0]["timeout"] <= 0.25


@pytest.fixture
def acquisition_clock(monkeypatch):
    """Advance source time and model-idle time without sleeping or changing identity."""
    clock = [100.0]
    epoch = datetime.now(timezone.utc)
    class ClockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = epoch + timedelta(seconds=clock[0] - 100)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    monkeypatch.setattr(news, "datetime", ClockDateTime)
    monkeypatch.setattr(news, "time", types.SimpleNamespace(
        monotonic=lambda: clock[0], sleep=time.sleep))
    return clock


@pytest.mark.parametrize("next_provider", ["newsapi", "kalshi"])
def test_model_planning_gap_does_not_consume_source_allowance(tmp_path, acquisition_clock, next_provider):
    transport = Transport()
    instance = client(tmp_path, transport)
    assert instance.search_news("prefetch")["status"]["state"] == "ok"
    acquisition_clock[0] += 120  # The real engine plans between prefetch and tools.
    reopened = client(tmp_path, transport)
    if next_provider == "newsapi":
        result = reopened.search_news("investigator")
        assert len(transport.calls) == 2
    else:
        def acquire(reserve):
            assert reserve()["allowed"] is True
            return external_result("kalshi", "investigator")
        result = reopened.capture_market("kalshi", "investigator", acquire)
        assert result["request_count"] == 1
    assert result["status"]["state"] == ("ok" if next_provider == "newsapi" else "verified_empty")


def test_real_acquisition_time_is_shared_and_survives_idle_restart(tmp_path, monkeypatch, acquisition_clock):
    monkeypatch.setenv("NEWS_CONTEXT_DEADLINE_SECONDS", "2")
    def acquire_news(_):
        acquisition_clock[0] += .75
        return response(article())
    instance = client(tmp_path, Transport(acquire_news))
    assert instance.search_news("first")["status"]["state"] == "ok"
    acquisition_clock[0] += 120
    reopened = client(tmp_path, Transport(acquire_news))
    assert reopened.search_news("second")["status"]["state"] == "ok"
    def acquire_market(reserve):
        admission = reserve()
        assert admission["allowed"] is True
        assert admission["deadline"] == pytest.approx(acquisition_clock[0] + .5)
        acquisition_clock[0] += .5
        assert reserve() == {"allowed": False, "state": "timeout", "reason": "stage_deadline"}
        return external_result("kalshi", "third")
    result = reopened.capture_market("kalshi", "third", acquire_market)
    assert result["request_count"] == 1
    assert reopened.snapshot()["acquisition_seconds"] == pytest.approx(2)
    denied = client(tmp_path).capture_market("polymarket", "fourth", lambda _: pytest.fail("spent deadline"))
    state(denied, "timeout", attempted=False)


def test_interrupted_market_retains_reserved_time_across_restart(tmp_path, acquisition_clock):
    class Interrupted(BaseException):
        pass
    def crash(reserve):
        assert reserve()["allowed"] is True
        raise Interrupted
    with pytest.raises(Interrupted):
        client(tmp_path).capture_market("kalshi", "interrupted", crash)
    acquisition_clock[0] += 120
    reopened = client(tmp_path)
    assert reopened.snapshot()["acquisition_seconds"] == 10
    replay = reopened.capture_market("kalshi", "interrupted", lambda _: pytest.fail("replay"))
    assert replay["status"]["reason"] == "capture_interrupted"
    state(reopened.search_news("fresh"), "timeout", attempted=False)


def test_interrupted_news_retains_timeout_reservation(tmp_path, acquisition_clock):
    class Interrupted(BaseException):
        pass
    def crash(_):
        raise Interrupted
    with pytest.raises(Interrupted):
        client(tmp_path, Transport(crash)).search_news("interrupted")
    reopened = client(tmp_path)
    assert reopened.snapshot()["acquisition_seconds"] == 5
    acquisition_clock[0] += 120
    assert reopened.search_news("another")["status"]["state"] == "ok"
    assert reopened.snapshot()["network_requests"]["newsapi"] == 2


@pytest.mark.parametrize("seconds", [-1, True, "0", None])
def test_invalid_acquisition_accounting_is_rejected(tmp_path, seconds):
    value = client(tmp_path).snapshot()
    value["acquisition_seconds"] = seconds
    value["sha256"] = digest(value)
    (tmp_path / news.CONTEXT_FILENAME).write_text(json.dumps(value))
    with pytest.raises(news.ContextIntegrityError, match="invalid_context_schema"):
        client(tmp_path)


def test_legacy_elapsed_budget_cannot_be_reset_by_upgrade(tmp_path):
    instance = client(tmp_path)
    instance.search_news("legacy")
    value = instance.snapshot()
    value.pop("acquisition_seconds", None)
    value["network_started_at"] = value["created_at"]
    value["sha256"] = digest(value)
    (tmp_path / news.CONTEXT_FILENAME).write_text(json.dumps(value))
    transport = Transport()
    state(client(tmp_path, transport).search_news("after upgrade"), "timeout", attempted=False)
    assert transport.calls == []


@pytest.mark.parametrize("transport_seconds,expected", [(.5, "ok"), (.8, "timeout")])
def test_pending_write_and_transport_share_one_absolute_deadline(
    tmp_path, monkeypatch, acquisition_clock, transport_seconds, expected,
):
    monkeypatch.setenv("NEWS_CONTEXT_HTTP_TIMEOUT_SECONDS", "1")
    write = news._write
    writes = []
    def slow_pending(descriptor, value):
        write(descriptor, value)
        if not writes:
            acquisition_clock[0] += .3
        writes.append(1)
    def acquire(_):
        acquisition_clock[0] += transport_seconds
        return response(article())
    monkeypatch.setattr(news, "_write", slow_pending)
    transport = Transport(acquire)
    instance = client(tmp_path, transport)
    state(instance.search_news("bounded"), expected, attempted=True)
    assert len(transport.calls) == 1
    assert transport.calls[0]["timeout"] == pytest.approx(.7)
    assert instance.snapshot()["acquisition_seconds"] == pytest.approx(.3 + transport_seconds)


@pytest.mark.parametrize("counter", ["root", "request_count", "network_requests"])
def test_legacy_positive_market_counts_without_time_marker_cannot_regain_time(tmp_path, counter):
    instance = client(tmp_path)
    instance.record_result("kalshi", "legacy", external_result("kalshi", "legacy"))
    value = instance.snapshot()
    value.pop("acquisition_seconds", None)
    value.pop("network_started_at", None)
    if counter == "root":
        value["network_requests"] = {"market": 1}
    else:
        value["queries"][0][counter] = 1
    value["sha256"] = digest(value)
    (tmp_path / news.CONTEXT_FILENAME).write_text(json.dumps(value))
    reopened = client(tmp_path)
    replay = reopened.capture_market("kalshi", "legacy", lambda _: pytest.fail("replay"))
    assert replay["status"]["state"] == "verified_empty"
    state(reopened.capture_market("polymarket", "fresh", lambda _: pytest.fail("unknown spent time")),
          "timeout", attempted=False)


def test_untouched_legacy_generation_still_has_acquisition_allowance(tmp_path):
    value = client(tmp_path).snapshot()
    value.pop("acquisition_seconds", None)
    value["network_requests"] = {"market": 0}
    value["sha256"] = digest(value)
    (tmp_path / news.CONTEXT_FILENAME).write_text(json.dumps(value))
    transport = Transport()
    instance = client(tmp_path, transport)
    state(instance.search_news("first"), "ok", attempted=True)
    state(client(tmp_path, transport).search_news("second"), "ok", attempted=True)
    assert len(transport.calls) == 2
    assert instance.snapshot()["acquisition_seconds"] < 1


def test_sealed_legacy_counts_replay_preserves_exact_bytes(tmp_path):
    instance = client(tmp_path)
    instance.record_result("kalshi", "legacy", dict(external_result("kalshi", "legacy"), network_requests=1))
    value = instance.seal()
    value.pop("acquisition_seconds", None)
    value.pop("network_started_at", None)
    value["sha256"] = digest(value)
    path = tmp_path / news.CONTEXT_FILENAME
    path.write_text(json.dumps(value))
    before = path.read_bytes()
    reopened = client(tmp_path)
    assert reopened.capture_market("kalshi", "legacy", lambda _: pytest.fail("sealed replay"))["status"]["state"] == "verified_empty"
    assert reopened.seal() == value
    assert path.read_bytes() == before


def test_transport_timeout_has_canonical_status_and_no_exception_text(tmp_path):
    result = client(tmp_path, Transport(TimeoutError("private-timeout-detail"))).search_news("capacity")
    state(result, "timeout", attempted=True)
    assert "private-timeout-detail" not in json.dumps(result)


def test_seal_is_idempotent_canonical_and_replays_without_rewriting(tmp_path):
    transport = Transport()
    instance = client(tmp_path, transport)
    first = instance.search_news("capacity")
    sealed = instance.seal(source_refs={article()["url"]: "S7"})
    context_file = tmp_path / news.CONTEXT_FILENAME
    before = context_file.read_bytes()
    stamp = context_file.stat().st_mtime_ns
    assert sealed["sealed"] is True
    assert sealed["sha256"] == digest(sealed)
    assert sealed["items"][0]["source_ref"] == "S7"
    assert news.load_context(tmp_path) == sealed
    assert instance.seal() == sealed
    replay = client(tmp_path, transport).search_news("capacity")
    assert replay["status"] == first["status"]
    assert [item["id"] for item in replay["items"]] == [item["id"] for item in first["items"]]
    assert len(transport.calls) == 1
    late = instance.search_news("a new query after seal")
    assert late["status"]["attempted"] is False
    assert late["status"]["state"] not in {"ok", "verified_empty"}
    assert len(transport.calls) == 1
    assert context_file.read_bytes() == before
    assert context_file.stat().st_mtime_ns == stamp


def test_snapshots_are_detached_and_unsealed_load_requires_explicit_opt_in(tmp_path):
    instance = client(tmp_path)
    instance.search_news("capacity")
    snapshot = instance.snapshot()
    assert snapshot["sha256"] == digest(snapshot)
    assert news.load_context(tmp_path, require_sealed=False) == snapshot
    with pytest.raises(news.ContextIntegrityError):
        news.load_context(tmp_path)
    snapshot["items"][0]["title"] = "mutated by consumer"
    assert instance.snapshot()["items"][0]["title"] != "mutated by consumer"


def test_load_missing_context_is_compatible_and_does_not_create_directory(tmp_path):
    missing = tmp_path / "missing-off-run"
    assert news.load_context(missing) == {}
    assert not missing.exists()


@pytest.mark.parametrize("corruption", ["malformed", "oversized", "tamper", "nan"])
def test_invalid_present_proof_fails_closed_without_refetch(tmp_path, corruption):
    sealed = sealed_capture(tmp_path)
    context_file = tmp_path / news.CONTEXT_FILENAME
    if corruption == "malformed":
        context_file.write_bytes(b"{broken")
    elif corruption == "oversized":
        context_file.write_bytes(b" " * (2 * 1024 * 1024 + 1))
    elif corruption == "tamper":
        sealed["items"][0]["title"] = "changed after sealing"
        context_file.write_text(json.dumps(sealed))
    else:
        sealed["created_at"] = float("nan")
        context_file.write_text(json.dumps(sealed))
    with pytest.raises(news.ContextIntegrityError):
        news.load_context(tmp_path)
    transport = Transport()
    with pytest.raises(news.ContextIntegrityError):
        client(tmp_path, transport).search_news("capacity")
    assert transport.calls == []


def test_context_file_symlink_is_rejected_without_touching_target(tmp_path):
    target = tmp_path / "unowned-target.json"
    target.write_text('{"unowned": true}')
    root = tmp_path / "run"
    root.mkdir()
    (root / news.CONTEXT_FILENAME).symlink_to(target)
    before = target.read_bytes()
    with pytest.raises(news.ContextIntegrityError):
        news.load_context(root)
    transport = Transport()
    with pytest.raises(news.ContextIntegrityError):
        client(root, transport).search_news("capacity")
    assert target.read_bytes() == before
    assert transport.calls == []


@pytest.mark.parametrize("through_parent", [False, True])
def test_artifact_root_symlink_is_rejected_and_cannot_escape_owner(tmp_path, through_parent):
    target = tmp_path / "other-owner"
    target.mkdir()
    link = tmp_path / "linked-owner"
    link.symlink_to(target, target_is_directory=True)
    root = link / "child" if through_parent else link
    transport = Transport()
    with pytest.raises(news.ContextIntegrityError):
        client(root, transport).search_news("capacity")
    assert list(target.iterdir()) == []
    assert transport.calls == []


def test_cached_client_none_identity_reuses_and_explicit_root_beats_environment(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit"
    ambient = tmp_path / "ambient"
    monkeypatch.setenv("DEERFLOW_RUN_ARTIFACT_DIR", str(ambient))
    original = news.get_context_client(explicit, question=QUESTION, language="en", as_of=AS_OF)
    initial = original.snapshot()
    reused = news.get_context_client(explicit, question=None, language=None, as_of=None)
    assert reused.snapshot()["generation_id"] == initial["generation_id"]
    assert reused.snapshot()["question_sha256"] == initial["question_sha256"]
    assert reused.snapshot()["language"] == initial["language"]
    assert reused.snapshot()["as_of"] == initial["as_of"]
    assert not ambient.exists()


@pytest.mark.parametrize("change", [
    {"question": "A different forecast question"},
    {"language": "zh"},
    {"as_of": "2026-10-17T12:00:00Z"},
])
def test_explicit_changed_identity_never_silently_reuses_a_cached_generation(tmp_path, change):
    original = news.get_context_client(tmp_path, question=QUESTION, language="en", as_of=AS_OF)
    sealed = original.seal()
    before = (tmp_path / news.CONTEXT_FILENAME).read_bytes()
    identity = {"question": QUESTION, "language": "en", "as_of": AS_OF, **change}
    try:
        changed = news.get_context_client(tmp_path, **identity).snapshot()
    except news.ContextIntegrityError:
        assert (tmp_path / news.CONTEXT_FILENAME).read_bytes() == before
    else:
        assert changed["generation_id"] != sealed["generation_id"]
        if "question" in change:
            assert changed["question_sha256"] != sealed["question_sha256"]
        for field in ("language", "as_of"):
            if field in change:
                assert changed[field] == change[field]


def test_record_result_replays_provider_identity_and_cannot_mutate_a_sealed_capture(tmp_path):
    transport = Transport()
    instance = client(tmp_path, transport)
    supplied = {
        "provider": "kalshi", "query": "capacity",
        "status": {"state": "verified_empty", "attempted": True},
        "items": [], "retrieved_at": "2026-10-18T11:00:00Z",
    }
    first = instance.record_result("kalshi", "capacity", supplied)
    assert instance.record_result("kalshi", "capacity", supplied) == first
    sealed = instance.seal()
    before = (tmp_path / news.CONTEXT_FILENAME).read_bytes()
    assert instance.record_result("kalshi", "capacity", supplied) == first
    try:
        late = instance.record_result("kalshi", "different query", {**supplied, "query": "different query"})
    except news.ContextIntegrityError:
        pass
    else:
        assert late["status"]["attempted"] is False
        assert late["status"]["state"] not in {"ok", "verified_empty"}
    assert instance.snapshot() == sealed
    assert (tmp_path / news.CONTEXT_FILENAME).read_bytes() == before
    assert transport.calls == []


def test_market_comparison_lazily_delegates_to_its_frozen_owner(tmp_path, monkeypatch):
    delegated = []
    expected = {
        "provider": "market_compare", "query": "capacity",
        "status": {"state": "verified_empty", "attempted": False},
        "items": [], "retrieved_at": "2026-10-18T11:00:00Z",
    }
    owner = types.ModuleType("market_intelligence")

    def compare_markets(instance, query, *, deadline=None):
        delegated.append((instance, query, deadline))
        return expected

    owner.compare_markets = compare_markets
    monkeypatch.setitem(sys.modules, "market_intelligence", owner)
    monkeypatch.setitem(sys.modules, "deerflow_bridge.market_intelligence", owner)
    transport = Transport()
    instance = client(tmp_path, transport)
    deadline = RemainingDeadline(1)
    assert instance.market_compare("capacity", deadline=deadline) == expected
    assert delegated == [(instance, "capacity", deadline)]
    assert transport.calls == []


def test_merge_is_deterministic_deduplicates_and_preserves_inputs(tmp_path):
    first, second = tmp_path / "lane-a", tmp_path / "lane-b"
    sealed_capture(first, article(), query="first lane", source_refs={article()["url"]: "S1"})
    sealed_capture(second, article(), article(2), query="second lane", source_refs={article(2)["url"]: "S1"})
    inputs = [(root / news.CONTEXT_FILENAME).read_bytes() for root in (first, second)]
    merged = news.merge_contexts([first, second], tmp_path / "merged")
    reversed_order = news.merge_contexts([second, first], tmp_path / "merged-reversed")
    assert merged == reversed_order
    assert merged["sealed"] is True
    assert merged["sha256"] == digest(merged)
    assert {item["url"] for item in merged["items"]} == {article()["url"], article(2)["url"]}
    # Same article in distinct captures remains distinct provenance.
    assert len(merged["items"]) == 3
    assert len({item["id"] for item in merged["items"]}) == 2
    assert len({(item["id"], item["capture_id"]) for item in merged["items"]}) == 3
    assert news.load_context(tmp_path / "merged") == merged
    assert [(root / news.CONTEXT_FILENAME).read_bytes() for root in (first, second)] == inputs


def test_merge_does_not_silently_skip_corrupt_supplied_generation(tmp_path):
    first, corrupt = tmp_path / "good", tmp_path / "bad"
    sealed_capture(first)
    sealed_capture(corrupt)
    (corrupt / news.CONTEXT_FILENAME).write_text("{broken")
    with pytest.raises(news.ContextIntegrityError):
        news.merge_contexts([first, corrupt], tmp_path / "output")


def test_render_empty_context_and_attempted_failure_are_honest(tmp_path):
    assert news.render_context({}) == ""
    instance = client(tmp_path, api_key="")
    instance.search_news("capacity")
    rendered = news.render_context(instance.seal(), lang="en")
    assert "unavailable" in rendered.lower()
    assert SENTINEL not in rendered
    assert "verified_empty" not in rendered


def test_render_has_attribution_limits_context_warning_and_escapes_untrusted_markup(tmp_path):
    unsafe = '<script>alert(1)</script> [injected](javascript:alert(2))'
    sealed = sealed_capture(tmp_path, article(title=unsafe, description=unsafe), article(2))
    rendered = news.render_context(sealed, lang="en", max_items=1)
    lowered = rendered.lower()
    assert "newsapi" in lowered and "news_snippet" in lowered
    assert "2026-10-17" in rendered
    assert "context" in lowered
    assert article()["url"] in rendered
    assert article(2)["url"] not in rendered
    assert "<script>" not in lowered
    assert "](javascript:" not in lowered


def test_provider_article_unsafe_url_cannot_be_rendered_as_active_link(tmp_path):
    sealed = sealed_capture(tmp_path, article(url="javascript:alert(1)"), article(2))
    rendered = news.render_context(sealed)
    assert "](javascript:" not in rendered.lower()
    assert article(2)["url"] in rendered


@pytest.mark.guarded_runner
@pytest.mark.parametrize("same_query", [False, True])
def test_separate_processes_share_singleflight_and_generation_allowance(tmp_path, same_query):
    guard = sys.modules.get("main_offline_guard")
    assert guard is not None, "process fixture requires the existing guarded runner"
    script = Path(__file__).resolve()
    guard.allow_python_script(script)
    root = tmp_path / "shared-generation"
    calls = tmp_path / "physical-calls.txt"
    ready = tmp_path / "start-gate"
    children = []
    try:
        for number in range(4):
            query = "shared query" if same_query else f"process query {number}"
            children.append(subprocess.Popen(
                [sys.executable, "-B", str(script), "--news-signal-child", str(root),
                 str(calls), str(ready), query],
                cwd=str(tmp_path), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True,
            ))
        ready.touch()
        results = []
        for child in children:
            stdout, stderr = child.communicate(timeout=20)
            assert child.returncode == 0, stderr
            results.append(json.loads(stdout))
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
    count = len(calls.read_text().splitlines())
    assert count == (1 if same_query else 2)
    if same_query:
        assert all(result == results[0] for result in results)
    else:
        assert sum(result["status"]["state"] == "budget_exhausted" for result in results) == 2
    stored = news.load_context(root, require_sealed=False)
    assert stored["sha256"] == digest(stored)


def _process_fixture(root, calls, ready, query):
    def fake_transport(url, *, headers, timeout, max_bytes):
        with Path(calls).open("a") as stream:
            stream.write("request\n")
        time.sleep(0.04)
        return response(article())

    expires = time.monotonic() + 5
    while not Path(ready).exists():
        if time.monotonic() >= expires:
            raise RuntimeError("offline fixture start gate timed out")
        time.sleep(0.01)
    print(json.dumps(client(root, fake_transport).search_news(query)))


if __name__ == "__main__" and sys.argv[1:2] == ["--news-signal-child"]:
    _process_fixture(*sys.argv[2:])


def test_long_question_identity_matches_engine_and_survives_restart(tmp_path):
    question = "  ".join(["A complex forecast question with full identity"] * 40)
    instance = client(tmp_path, question=question)
    expected = hashlib.sha256(" ".join(question.split()).encode()).hexdigest()
    assert instance.snapshot()["question_sha256"] == expected
    instance.search_news("capacity")
    sealed = instance.seal()
    reopened = client(tmp_path, question=question)
    assert reopened.snapshot()["question_sha256"] == expected
    assert reopened.snapshot()["generation_id"] == sealed["generation_id"]
    assert reopened.snapshot()["language"] == "en"
    assert reopened.snapshot()["as_of"] == AS_OF
    with pytest.raises(news.ContextIntegrityError):
        client(tmp_path, question=question + " altered suffix past query limit")


def test_master_off_has_no_writes_or_network_for_any_entrypoint(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_CONTEXT_ENABLED", "false")
    root = tmp_path / "disabled-generation"
    transport = Transport()
    instance = client(root, transport)
    assert instance.search_news("capacity")["status"]["state"] == "disabled"
    assert instance.search_social("capacity")["status"]["state"] == "disabled"
    assert instance.market_compare("capacity")["status"]["state"] == "disabled"
    assert instance.record_result("newsapi", "capacity", {
        "status": {"state": "verified_empty", "attempted": False}, "items": [],
    })["status"]["state"] == "disabled"
    instance.snapshot()
    assert instance.seal() == {}
    assert not root.exists()
    assert transport.calls == []


def test_lookback_and_page_knobs_cannot_expand_hard_caps(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWSAPI_LOOKBACK_DAYS", "999")
    monkeypatch.setenv("NEWSAPI_PAGE_SIZE", "999")
    transport = Transport()
    instance = client(tmp_path, transport)
    instance.search_news("capacity")
    params = parse_qs(urlsplit(transport.calls[0]["url"]).query)
    start = datetime.fromisoformat(params["from"][0])
    end = datetime.fromisoformat(params["to"][0])
    assert (end - start).days == 30
    assert params["pageSize"] == ["20"]


def test_market_metadata_survives_real_store_and_raw_hash_is_preserved(tmp_path):
    instance = client(tmp_path)
    raw_hash = "a" * 64
    raw = {"id": "kalshi:CONTRACT", "provider": "kalshi", "kind": "market_quote",
           "title": "Capacity above threshold?", "url": "https://external-api.kalshi.com/trade-api/v2/markets/CONTRACT",
           "published_at": None, "language": "en", "snippet": None,
           "probability": .43, "probability_basis": "last_price_dollars/1_USD_binary_payout",
           "price_unit": "USD_per_contract", "quote_units": "USD_per_contract", "volume_unit": "contracts",
           "rules_primary": "Resolve from the specified official release.", "rules_secondary": None,
           "yes_label": "Above 3", "no_label": "At most 3", "quote_at": None,
           "yes_bid": .42, "no_ask": .58, "floor_strike": 3, "evidence_sha256": raw_hash,
           "source_price_fields": {"yes_bid_dollars": "0.4200", "last_price_dollars": "0.4300"}}
    result = instance.record_result("kalshi", "capacity", {
        "provider": "kalshi", "query": "capacity", "status": {"state": "ok", "attempted": True},
        "items": [raw], "retrieved_at": "2026-10-18T10:00:00Z", "request_count": 3,
        "recall_complete": False, "search_method": "bounded_catalog_token_overlap_candidates_only"})
    stored = instance.seal()["items"][0]
    for key in ("price_unit", "probability_basis", "rules_primary", "rules_secondary", "yes_label", "no_label", "quote_units",
                "volume_unit", "quote_at", "source_price_fields", "no_ask", "floor_strike"):
        assert stored[key] == raw[key]
    assert result["request_count"] == 3
    assert stored["evidence_sha256"] == raw_hash
    content = {key: val for key, val in stored.items() if key not in {"source_ref", "normalized_sha256"}}
    assert stored["normalized_sha256"] == hashlib.sha256(news._canonical(content)).hexdigest()


def test_renderer_accepts_citation_presentation_copy_without_changing_proof(tmp_path):
    instance = client(tmp_path)
    instance.search_news("capacity")
    sealed = instance.seal()
    before = (tmp_path / news.CONTEXT_FILENAME).read_bytes()
    presentation = json.loads(json.dumps(sealed))
    presentation["items"][0]["source_ref"] = "S9"
    assert "S9" in news.render_context(presentation)
    assert (tmp_path / news.CONTEXT_FILENAME).read_bytes() == before
    assert news.load_context(tmp_path) == sealed


def test_legacy_wrappers_use_trusted_cached_client_and_json_strings(tmp_path, monkeypatch):
    from deerflow_bridge import news_tools
    monkeypatch.setenv("DEERFLOW_RUN_ARTIFACT_DIR", str(tmp_path))
    instance = news.get_context_client(tmp_path, question=QUESTION, language="en", as_of=AS_OF)
    transport = Transport()
    monkeypatch.setattr(instance, "_transport", transport)
    result = json.loads(news_tools.news_search_impl("capacity"))
    assert result["items"] and len(transport.calls) == 1
    assert json.loads(news_tools.social_search_impl("capacity"))["status"]["state"] == "disabled"
    assert news.get_context_client(tmp_path, question=None, language=None, as_of=None) is instance


def test_provider_transport_rejects_nonallowlisted_url_before_any_network():
    for url in ("http://newsapi.org/v2/everything", "https://attacker.example/v2/everything",
                "https://newsapi.org/other", "https://user:pass@newsapi.org/v2/everything"):
        with pytest.raises(ValueError, match="provider_endpoint_not_allowed"):
            news._http_get(url, headers={}, timeout=1, max_bytes=100)


@pytest.mark.parametrize("alias,code", [("English", "en"), ("english", "en"), ("Chinese", "zh"), ("中文", "zh"), ("zh-CN", "zh")])
def test_language_alias_normalization_applies_to_requests_cache_and_restart(tmp_path, alias, code):
    transport = Transport()
    instance = news.get_context_client(tmp_path, question=QUESTION, language=alias, as_of=AS_OF)
    assert instance.snapshot()["language"] == code
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(instance, "_transport", transport)
        result = instance.search_news("capacity")
        assert parse_qs(urlsplit(transport.calls[0]["url"]).query)["language"] == [code]
        assert result["items"][0]["language"] == code
        instance.seal()
        assert news.get_context_client(tmp_path, language=code) is instance
        assert news.get_context_client(tmp_path, language=alias) is instance
        reopened = client(tmp_path, language=alias)
        assert reopened.snapshot()["language"] == code
        assert reopened.snapshot()["as_of"] == AS_OF
        assert reopened.snapshot()["question_sha256"] == instance.question_sha256
    finally:
        monkey.undo()



@pytest.mark.parametrize("error", [errno.EAGAIN, errno.ENOENT])
def test_transient_lock_open_contention_waits_without_weakening_no_follow(tmp_path, monkeypatch, error):
    original = news.os.open
    attempts = []
    def contended(path, flags, *args, **kwargs):
        if path == ".news-context.lock":
            attempts.append(flags)
            if len(attempts) < 3:
                raise OSError(error, "fixture contention")
            assert flags & news.os.O_NOFOLLOW
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(news.os, "open", contended)
    transport = Transport()
    result = client(tmp_path, transport).search_news("capacity")
    assert result["status"]["state"] == "ok"
    assert len(attempts) == 3 and len(transport.calls) == 1


def test_lock_wait_cannot_extend_caller_deadline(tmp_path, monkeypatch):
    original = news.os.open
    def contended(path, flags, *args, **kwargs):
        if path == ".news-context.lock":
            raise BlockingIOError(errno.EAGAIN, "fixture contention")
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(news.os, "open", contended)
    transport = Transport()
    started = time.monotonic()
    result = client(tmp_path, transport).search_news("capacity", deadline=started + .05)
    assert result["status"]["state"] == "timeout"
    assert result["status"]["attempted"] is False
    assert time.monotonic() - started < .5
    assert not transport.calls


def test_deleted_bound_capture_is_rejected_without_reacquisition(tmp_path):
    transport = Transport()
    instance = client(tmp_path, transport)
    instance.search_news("capacity")
    (tmp_path / news.CONTEXT_FILENAME).unlink()
    with pytest.raises(news.ContextIntegrityError, match="bound_context_missing"):
        instance.search_news("capacity")
    assert len(transport.calls) == 1


def test_master_off_does_not_rewrite_an_existing_unsealed_capture(tmp_path, monkeypatch):
    instance = client(tmp_path)
    instance.search_news("capacity")
    before = (tmp_path / news.CONTEXT_FILENAME).read_bytes()
    monkeypatch.setenv("NEWS_CONTEXT_ENABLED", "false")
    assert instance.seal()["sealed"] is False
    assert (tmp_path / news.CONTEXT_FILENAME).read_bytes() == before


@pytest.mark.parametrize("status", [403, 429])
def test_opted_in_reddit_preserves_denied_status_without_retries(tmp_path, status):
    transport = Transport((status, b"private-reddit-response"))
    instance = client(tmp_path, transport, social_enabled=True)
    first = instance.search_social("capacity")
    assert first["status"]["state"] == {403: "forbidden", 429: "rate_limited"}[status]
    assert first["status"]["attempted"] is True
    assert instance.search_social("capacity") == first
    assert len(transport.calls) == 1
    assert "private-reddit-response" not in json.dumps(first)


@pytest.mark.parametrize("replacement", ["unsealed_predecessor", "resealed_modified"])
def test_observed_seal_rejects_same_id_rollback_or_resealed_modified_capture(tmp_path, replacement):
    transport = Transport()
    instance = client(tmp_path, transport)
    instance.search_news("capacity")
    target = tmp_path / news.CONTEXT_FILENAME
    predecessor = target.read_bytes()
    sealed = instance.seal()
    if replacement == "unsealed_predecessor":
        target.write_bytes(predecessor)
    else:
        sealed["items"][0]["title"] = "validly resealed but different evidence"
        sealed["sha256"] = digest(sealed)
        target.write_text(json.dumps(sealed))
    with pytest.raises(news.ContextIntegrityError, match="sealed_context_changed"):
        instance.search_news("capacity another query")
    assert len(transport.calls) == 1
    with pytest.raises(news.ContextIntegrityError, match="sealed_context_changed"):
        instance.snapshot()


def test_shared_renderer_retains_market_quote_contract_fields_and_unknowns(tmp_path):
    instance = client(tmp_path)
    instance.record_result("kalshi", "capacity", {
        "status": {"state": "ok", "attempted": True}, "items": [{
            "id": "kalshi:K-CAP", "provider": "kalshi", "kind": "market_quote", "title": "Capacity threshold",
            "url": "https://external-api.kalshi.com/trade-api/v2/markets/K-CAP", "published_at": None,
            "probability": .43, "bid": .42, "ask": .44, "last": .43,
            "outcome": "Yes", "yes_label": "above 3", "no_label": "at most 3", "quote_at": None,
            "probability_basis": "last_price_dollars/1_USD_binary_payout", "quote_basis": "provider_reported_dollars_per_contract",
            "price_unit": "USD_per_contract", "volume": 1.5, "volume_unit": "contracts",
            "rules_primary": "Resolve using the official October release.", "rules_secondary": "Use first published figure.",
            "end_date": "2026-12-31T23:59:59Z", "floor_strike": 3, "strike_type": "greater"}],
        "retrieved_at": "2026-10-18T10:00:00Z"})
    sealed = instance.seal()
    text = news.render_context(sealed)
    for expected in ("0.43", "0.42", "0.44", "Yes", "USD", "contract", "1.5", "2026-12-31", "official October", "unknown", "above 3"):
        assert expected in text
    assert "context" in text.lower()
    assert sealed == news.load_context(tmp_path)


def test_parent_question_binding_allows_angle_lanes_but_rejects_foreign_identity(tmp_path, monkeypatch):
    parent = hashlib.sha256(QUESTION.encode()).hexdigest()
    monkeypatch.setenv("NEWS_CONTEXT_QUESTION_SHA256", parent)
    dirs = []
    for index, angle in enumerate(("Baseline: ", "Skeptical analyst: ")):
        root = tmp_path / str(index)
        instance = client(root, question=angle + QUESTION)
        instance.search_news("capacity")
        assert instance.seal()["question_sha256"] == parent
        dirs.append(root)
    merged = news.merge_contexts(dirs, tmp_path / "combined")
    assert merged["question_sha256"] == parent
    assert len(merged["input_generations"]) == 2
    monkeypatch.setenv("NEWS_CONTEXT_QUESTION_SHA256", "f" * 64)
    foreign = client(tmp_path / "foreign")
    foreign.search_news("capacity")
    foreign.seal()
    with pytest.raises(news.ContextIntegrityError, match="merge_identity_mismatch"):
        news.merge_contexts(dirs + [tmp_path / "foreign"], tmp_path / "bad-merge")
    with pytest.raises(news.ContextIntegrityError, match="context_identity_mismatch"):
        news.ContextClient(dirs[0])


@pytest.mark.parametrize("invalid", ["", "invalid", "A" * 64, "a" * 63, "a" * 65, " " + "a" * 64])
def test_invalid_parent_question_override_fails_closed(tmp_path, monkeypatch, invalid):
    monkeypatch.setenv("NEWS_CONTEXT_QUESTION_SHA256", invalid)
    with pytest.raises(news.ContextIntegrityError, match="invalid_parent_question_identity"):
        client(tmp_path)


def external_result(provider, query, *, state="verified_empty", reason=None):
    status = {"state": state, "attempted": True}
    if reason:
        status["reason"] = reason
    return {"provider": provider, "query": query, "status": status,
            "items": [], "retrieved_at": "2026-10-18T10:00:00Z"}


def test_market_capture_reserves_each_physical_request_and_replays(tmp_path):
    instance = client(tmp_path)
    physical = []
    def acquire(reserve):
        for number in range(3):
            allowed = reserve()
            assert {key: allowed[key] for key in ("allowed", "state", "reason")} == {
                "allowed": True, "state": "ok", "reason": ""}
            assert time.monotonic() < allowed["deadline"] <= time.monotonic() + 10
            # Admission is durable before this physical transport stand-in.
            disk = news.load_context(tmp_path, require_sealed=False)
            assert disk["network_requests"]["market"] == number + 1
            assert disk["queries"][-1]["request_count"] == number + 1
            assert disk["queries"][-1]["status"]["reason"] == "capture_interrupted"
            physical.append(number)
        return external_result("kalshi", "capacity")
    captured = instance.capture_market("kalshi", "capacity", acquire)
    assert captured["request_count"] == 3
    assert len(physical) == 3
    assert instance.capture_market("kalshi", "capacity", lambda _: pytest.fail("must replay")) == captured
    reopened = client(tmp_path)
    def remaining(reserve):
        assert reserve()["allowed"] is True
        physical.append(4)
        denied = reserve()
        assert denied == {"allowed": False, "state": "budget_exhausted", "reason": "market_request_limit"}
        return external_result("polymarket", "second", state="budget_exhausted")
    result = reopened.capture_market("polymarket", "second", remaining)
    assert result["request_count"] == 1
    assert len(physical) == 4
    assert news.load_context(tmp_path, require_sealed=False)["network_requests"]["market"] == 4
    assert reopened.capture_market("kalshi", "third", lambda _: pytest.fail("cap before callback"))["status"]["state"] == "budget_exhausted"


def test_market_capture_full_query_table_and_seal_reject_before_callback(tmp_path):
    instance = client(tmp_path)
    for number in range(news.MAX_QUERIES):
        instance.record_result("kalshi", str(number), external_result("kalshi", str(number)))
    denied = instance.capture_market("kalshi", "too many", lambda _: pytest.fail("full table before callback"))
    assert denied["status"]["state"] == "budget_exhausted"
    sealed = instance.seal()
    instance.capture_market("kalshi", "sealed query", lambda _: pytest.fail("sealed before callback"))
    assert news.load_context(tmp_path) == sealed


def test_market_capture_existing_research_budget_denies_before_physical_io(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_BUDGET_DB", str(tmp_path / "budget.sqlite3"))
    monkeypatch.setenv("RESEARCH_BUDGET_SEARCH_GLOBAL", "0")
    physical = []
    instance = client(tmp_path / "run")
    def acquire(reserve):
        result = reserve()
        assert result["allowed"] is False
        if result["allowed"]:
            physical.append(1)
        return external_result("kalshi", "capacity", state=result["state"], reason=result["reason"])
    result = instance.capture_market("kalshi", "capacity", acquire)
    assert result["status"]["state"] == "budget_exhausted"
    assert result["request_count"] == 0 and physical == []


@pytest.mark.guarded_runner
@pytest.mark.parametrize("same_query", [False, True])
def test_market_capture_separate_processes_share_global_four_request_admission(tmp_path, same_query):
    guard = sys.modules["main_offline_guard"]
    script = Path(__file__).resolve()
    guard.allow_python_script(script)
    root, calls, gate = tmp_path / "capture", tmp_path / "calls", tmp_path / "gate"
    children = []
    try:
        for number in range(4):
            query = "same query" if same_query else f"market query {number}"
            children.append(subprocess.Popen(
                [sys.executable, "-B", str(script), "--market-capture-child", str(root), str(calls), str(gate), query, "no"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(tmp_path)))
        gate.touch()
        results = []
        for child in children:
            stdout, stderr = child.communicate(timeout=20)
            assert child.returncode == 0, stderr
            results.append(json.loads(stdout))
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
    physical = len(calls.read_text().splitlines())
    assert physical == (3 if same_query else 4)
    stored = news.load_context(root, require_sealed=False)
    assert stored["network_requests"]["market"] == physical
    assert sum(row["request_count"] for row in stored["queries"]) == physical
    if same_query:
        assert all(result == results[0] for result in results)


@pytest.mark.guarded_runner
def test_market_capture_process_death_keeps_spent_allowance_and_interrupted_replay(tmp_path):
    guard = sys.modules["main_offline_guard"]
    script = Path(__file__).resolve()
    guard.allow_python_script(script)
    root, calls, gate = tmp_path / "capture", tmp_path / "calls", tmp_path / "gate"
    gate.touch()
    child = subprocess.Popen(
        [sys.executable, "-B", str(script), "--market-capture-child", str(root), str(calls), str(gate), "crash query", "yes"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(tmp_path))
    stdout, stderr = child.communicate(timeout=20)
    assert child.returncode == 23, stderr
    assert len(calls.read_text().splitlines()) == 2
    instance = client(root)
    replay = instance.capture_market("kalshi", "crash query", lambda _: pytest.fail("interrupted capture must replay"))
    assert replay["status"]["reason"] == "capture_interrupted" and replay["request_count"] == 2
    def acquire(reserve):
        for _ in range(3):
            admission = reserve()
            if not admission["allowed"]:
                return external_result("polymarket", "after crash", state=admission["state"], reason=admission["reason"])
            with calls.open("a") as stream:
                stream.write("request\n")
        return external_result("polymarket", "after crash")
    after = instance.capture_market("polymarket", "after crash", acquire)
    # The process died with unmeasurable elapsed acquisition time. Keep its full
    # residual time reservation; a restart cannot turn a crash into extra I/O.
    assert after["status"]["state"] == "timeout"
    assert len(calls.read_text().splitlines()) == 2
    assert instance.snapshot()["network_requests"]["market"] == 2
    assert instance.snapshot()["acquisition_seconds"] == 10


def _market_process_fixture(root, calls, gate, query, crash):
    import os
    expires = time.monotonic() + 5
    while not Path(gate).exists():
        if time.monotonic() >= expires:
            raise RuntimeError("fixture gate timeout")
        time.sleep(.01)
    def acquire(reserve):
        for number in range(3):
            admission = reserve()
            if not admission["allowed"]:
                return external_result("kalshi", query, state=admission["state"], reason=admission["reason"])
            with Path(calls).open("a") as stream:
                stream.write("request\n")
            if crash == "yes" and number == 1:
                os._exit(23)  # Deliberate abrupt process death after two admissions.
            time.sleep(.02)
        return external_result("kalshi", query)
    print(json.dumps(client(root).capture_market("kalshi", query, acquire)))


if __name__ == "__main__" and sys.argv[1:2] == ["--market-capture-child"]:
    _market_process_fixture(*sys.argv[2:])


def test_early_client_binds_a_later_capture_when_replaying_then_rejects_deletion(tmp_path):
    early = client(tmp_path)
    producer = client(tmp_path)
    captured = producer.search_news("capacity")
    assert early.search_news("capacity") == captured
    (tmp_path / news.CONTEXT_FILENAME).unlink()
    with pytest.raises(news.ContextIntegrityError, match="bound_context_missing"):
        early.search_news("capacity")


def test_reopened_sealed_capture_pins_digest_and_allows_identical_replay(tmp_path):
    original = client(tmp_path)
    original.search_news("capacity")
    sealed = original.seal()
    transport = Transport()
    reopened = client(tmp_path, transport)
    assert reopened.search_news("capacity")["status"]["state"] == "ok"
    assert reopened.snapshot() == sealed and transport.calls == []
    replacement = json.loads(json.dumps(sealed))
    replacement["sealed"] = False
    replacement["sha256"] = digest(replacement)
    (tmp_path / news.CONTEXT_FILENAME).write_text(json.dumps(replacement))
    with pytest.raises(news.ContextIntegrityError, match="sealed_context_changed"):
        reopened.seal()


@pytest.mark.parametrize("request_count,network_requests,spent", [
    (3, 2, 3), (2, 3, 3), (2, 2, 2), (0, 3, 3),
    (True, 3, 3), (-2, 1, 1), (None, 3, 3),
])
def test_market_capture_migration_preserves_legacy_counts_without_double_charging(
    tmp_path, request_count, network_requests, spent,
):
    original = client(tmp_path)
    original.record_result("kalshi", "old query", dict(
        external_result("kalshi", "old query"),
        request_count=request_count, network_requests=network_requests))
    physical = []
    reopened = client(tmp_path)
    def acquire(reserve):
        for number in range(5):
            admission = reserve()
            if not admission["allowed"]:
                return external_result("polymarket", "new query", state=admission["state"], reason=admission["reason"])
            physical.append(number)
        pytest.fail("four-request shared ceiling was not enforced")
    result = reopened.capture_market("polymarket", "new query", acquire)
    assert len(physical) == 4 - spent
    assert result["request_count"] == 4 - spent
    assert result["status"]["state"] == "budget_exhausted"
    assert reopened.snapshot()["network_requests"]["market"] == 4
    # Reconciliation on a second restart must not count either representation twice.
    final = client(tmp_path).capture_market("kalshi", "last query", lambda _: pytest.fail("shared allowance already spent"))
    assert final["status"]["state"] == "budget_exhausted"
    assert len(physical) == 4 - spent


def test_market_capture_migration_preserves_existing_counter_high_water_mark(tmp_path):
    original = client(tmp_path)
    original.record_result("kalshi", "old query", dict(external_result("kalshi", "old query"), network_requests=1))
    snapshot = original.snapshot()
    snapshot["network_requests"] = {"market": 3}
    snapshot["sha256"] = digest(snapshot)
    (tmp_path / news.CONTEXT_FILENAME).write_text(json.dumps(snapshot))
    physical = []
    def acquire(reserve):
        assert reserve()["allowed"] is True
        physical.append(1)
        assert reserve()["allowed"] is False
        return external_result("polymarket", "new query", state="budget_exhausted")
    result = client(tmp_path).capture_market("polymarket", "new query", acquire)
    assert result["request_count"] == 1 and physical == [1]
    assert news.load_context(tmp_path, require_sealed=False)["network_requests"]["market"] == 4


def test_explicit_context_archive_preserves_bytes_and_retires_only_old_cache(tmp_path, monkeypatch):
    old = news.get_context_client(tmp_path, question=QUESTION, language="en", as_of=AS_OF)
    transport = Transport()
    monkeypatch.setattr(old, "_transport", transport)
    old.search_news("capacity")
    sealed = old.seal()
    raw = (tmp_path / news.CONTEXT_FILENAME).read_bytes()
    archive = tmp_path / "v3.stale-fixture"
    archive.mkdir()
    state = b'{"identity":{"question":"old"},"retained":"state proof"}'
    (archive / "state.json").write_bytes(state)
    assert news.archive_context(tmp_path, archive, expected_generation_id=sealed["generation_id"], expected_sha256=sealed["sha256"]) == sealed
    assert not (tmp_path / news.CONTEXT_FILENAME).exists()
    assert (archive / news.CONTEXT_FILENAME).read_bytes() == raw
    assert (archive / "state.json").read_bytes() == state
    assert news.load_context(archive) == sealed
    with pytest.raises(news.ContextIntegrityError):
        old.snapshot()
    fresh = news.get_context_client(tmp_path, question=QUESTION + " new run", language="en", as_of=AS_OF)
    assert fresh is not old and fresh.snapshot()["generation_id"] != sealed["generation_id"]
    monkeypatch.setattr(fresh, "_transport", transport)
    fresh.search_news("new capacity")
    assert len(transport.calls) == 2
    with pytest.raises(news.ContextIntegrityError):
        old.search_news("capacity")
    assert (archive / news.CONTEXT_FILENAME).read_bytes() == raw


@pytest.mark.parametrize("failure", ["wrong_generation", "wrong_digest", "corrupt_source", "missing_source", "existing_destination", "linked_destination", "symlink_archive", "external_archive", "missing_archive"])
def test_context_archive_failures_preserve_proof_and_cached_registration(tmp_path, failure):
    root = tmp_path / "run"
    old = news.get_context_client(root, question=QUESTION, language="en", as_of=AS_OF)
    sealed = old.seal()
    archive = root / "v3.stale-fixture"
    archive.mkdir()
    source = root / news.CONTEXT_FILENAME
    generation, expected = sealed["generation_id"], sealed["sha256"]
    destination = archive / news.CONTEXT_FILENAME
    if failure == "wrong_generation":
        generation = "different-generation"
    elif failure == "wrong_digest":
        expected = "f" * 64
    elif failure == "corrupt_source":
        source.write_bytes(b"{broken")
    elif failure == "missing_source":
        source.unlink()
    elif failure == "existing_destination":
        destination.write_bytes(b"unowned archive destination")
    elif failure == "linked_destination":
        destination.symlink_to(source)
    elif failure == "symlink_archive":
        actual = root / "other-directory"
        actual.mkdir()
        archive.rmdir()
        archive.symlink_to(actual, target_is_directory=True)
    elif failure == "external_archive":
        archive = tmp_path / "foreign-owner"
        archive.mkdir()
    elif failure == "missing_archive":
        archive.rmdir()
    before = source.read_bytes() if source.exists() else None
    existing = destination.read_bytes() if destination.exists() else None
    with pytest.raises(news.ContextIntegrityError):
        news.archive_context(root, archive, expected_generation_id=generation, expected_sha256=expected)
    assert (source.read_bytes() if source.exists() else None) == before
    assert (destination.read_bytes() if destination.exists() else None) == existing
    assert news._CLIENTS[str(root)] is old
    assert old._retired is False


def test_context_archive_move_failure_keeps_original_proof_and_client(tmp_path, monkeypatch):
    old = news.get_context_client(tmp_path, question=QUESTION, language="en", as_of=AS_OF)
    sealed = old.seal()
    raw = (tmp_path / news.CONTEXT_FILENAME).read_bytes()
    archive = tmp_path / "v3.stale-fixture"
    archive.mkdir()
    original = news.os.unlink
    def reject_retirement(path, *, dir_fd=None):
        # The first unlink is source retirement; cleanup of the created archive
        # link must remain possible so the original regular proof stays valid.
        if path == news.CONTEXT_FILENAME:
            info = news.os.fstat(dir_fd)
            root_info = tmp_path.stat()
            if (info.st_dev, info.st_ino) == (root_info.st_dev, root_info.st_ino):
                raise PermissionError("fixture archive failure")
        return original(path, dir_fd=dir_fd)
    monkeypatch.setattr(news.os, "unlink", reject_retirement)
    with pytest.raises(news.ContextIntegrityError, match="context_archive_io_failed"):
        news.archive_context(tmp_path, archive, expected_generation_id=sealed["generation_id"], expected_sha256=sealed["sha256"])
    assert (tmp_path / news.CONTEXT_FILENAME).read_bytes() == raw
    assert not (archive / news.CONTEXT_FILENAME).exists()
    assert news.get_context_client(tmp_path) is old and old.snapshot() == sealed


@pytest.mark.parametrize("cached", [False, True])
def test_client_lookup_does_not_hold_global_cache_lock_during_context_io(tmp_path, monkeypatch, cached):
    first, sibling = tmp_path / "first-root", tmp_path / "sibling-root"
    if cached:
        news.get_context_client(first, question=QUESTION, language="en", as_of=AS_OF)
    original_load = news.load_context
    sibling_finished = threading.Event()
    workers, errors = [], []
    def sibling_lookup():
        try:
            news.get_context_client(sibling, question="Independent sibling question", language="en", as_of=AS_OF)
        except BaseException as exc:
            errors.append(type(exc).__name__)
        finally:
            sibling_finished.set()
    def observed_load(artifact_dir, *, require_sealed=True):
        if artifact_dir == first:
            worker = threading.Thread(target=sibling_lookup)
            workers.append(worker)
            worker.start()
            assert sibling_finished.wait(1), "global cache lock held while reading another context root"
        return original_load(artifact_dir, require_sealed=require_sealed)
    monkeypatch.setattr(news, "load_context", observed_load)
    try:
        instance = news.get_context_client(first, question=QUESTION, language="en", as_of=AS_OF)
        assert instance.question_sha256 == hashlib.sha256(QUESTION.encode()).hexdigest()
    finally:
        for worker in workers:
            worker.join(timeout=2)
    assert not errors and all(not worker.is_alive() for worker in workers)
