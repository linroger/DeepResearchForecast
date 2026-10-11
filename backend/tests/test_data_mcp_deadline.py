"""Offline absolute-deadline regressions through real MCP hub admission."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest


_BRIDGE = Path(__file__).resolve().parents[2] / "deerflow_bridge"
sys.path.insert(0, str(_BRIDGE))
import data_mcp as dm  # noqa: E402


class RecordingSession:
    def __init__(self):
        self.calls = []
        self.owner_starts = []
        self.entered = threading.Event()
        self.cancelled = threading.Event()

    async def call_tool(self, tool, arguments):
        self.calls.append((arguments.get("text", tool), time.monotonic()))
        self.entered.set()
        try:
            await asyncio.sleep(arguments.get("seconds", 0))
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return SimpleNamespace(content=[SimpleNamespace(text=arguments.get("text", "ok"))],
                               structuredContent=None, isError=False)


def bounded_call(hub, deadline, *, text="bounded", seconds=0):
    return hub.call("fake", "echo", {"text": text, "seconds": seconds},
                    timeout=max(0.001, deadline - time.monotonic()), deadline=deadline)


@pytest.fixture
def make_hub(tmp_path, monkeypatch):
    hubs = []

    def make(*, startup=0.0, ready=False, concurrency=2):
        cwd = tmp_path / str(len(hubs))
        cwd.mkdir()
        spec = dm.ServerSpec("fake", sys.executable, (), {}, str(cwd),
                             start_timeout=2, call_timeout=1, max_concurrency=concurrency)
        hub = dm.McpHub({"fake": spec}, clock=lambda: 100.0)
        session = RecordingSession()
        srv = hub._servers["fake"]

        async def own(server, owner):
            session.owner_starts.append(time.monotonic())
            owner.close_event = asyncio.Event()
            await asyncio.sleep(startup)
            with hub._lock:
                if hub._closed or server.owner is not owner:
                    return
                server.state, server.session, server.tools = "ready", session, ["echo"]
                owner.reached_ready = True
                server.ready.set()
            await owner.close_event.wait()

        monkeypatch.setattr(hub, "_own", own)
        if ready:
            with hub._lock:
                hub._ensure_loop()
                srv.state, srv.session, srv.tools = "ready", session, ["echo"]
        hubs.append(hub)
        return hub, session

    yield make
    for hub in hubs:
        if hub._loop is not None:
            # Flush cancellation before closing the loop; no request task or
            # synthetic owner may leak into a sibling case.
            asyncio.run_coroutine_threadsafe(asyncio.sleep(0), hub._loop).result(2)
        hub.close(timeout=1)
        assert hub._thread is None or not hub._thread.is_alive()


@pytest.mark.parametrize("state", ["idle", "failed"])
def test_expired_deadline_cannot_launch_or_restart(make_hub, state):
    hub, session = make_hub()
    srv = hub._servers["fake"]
    srv.state, srv.failed_at, srv.error = state, 94.0, "synthetic failure"
    result = bounded_call(hub, time.monotonic() - 1)
    assert not result.ok, result
    assert srv.generation == 0 and not srv.restarted
    assert session.calls == []


def test_cold_startup_consumes_original_deadline_without_late_dispatch(make_hub):
    hub, session = make_hub(startup=0.18)
    started = time.monotonic()
    result = bounded_call(hub, started + 0.04)
    assert not result.ok, result
    assert time.monotonic() - started < 0.13
    time.sleep(0.2)
    assert session.calls == []


def test_ready_to_failed_restart_race_preserves_original_deadline(make_hub):
    hub, session = make_hub(startup=0.18, ready=True)
    assert hub.status()["fake"]["state"] == "ready"  # API prewarm/status gate.
    srv = hub._servers["fake"]
    hub._mark_failed(srv, srv.generation, "failed after API prewarm")
    srv.failed_at = 94.0  # The real once-only restart policy admits this attempt.
    started = time.monotonic()
    result = bounded_call(hub, started + 0.04)
    assert not result.ok, result
    assert time.monotonic() - started < 0.13
    time.sleep(0.2)
    assert session.calls == []


def test_expiry_after_ready_wait_is_rechecked_before_invocation(make_hub, monkeypatch):
    hub, session = make_hub(ready=True)

    def raced_ready(_timeout):
        time.sleep(0.06)
        return True

    monkeypatch.setattr(hub._servers["fake"].ready, "wait", raced_ready)
    result = bounded_call(hub, time.monotonic() + 0.02)
    assert not result.ok, result
    assert session.calls == []


def test_event_loop_queue_cannot_reset_deadline(make_hub):
    hub, session = make_hub(ready=True)
    blocking = threading.Event()

    def stall():
        blocking.set()
        time.sleep(0.12)

    hub._loop.call_soon_threadsafe(stall)
    assert blocking.wait(1)
    result = bounded_call(hub, time.monotonic() + 0.03)
    assert not result.ok, result
    time.sleep(0.15)
    assert session.calls == []


@pytest.mark.parametrize("adopt", [False, True])
def test_queued_start_does_not_launch_expired_demand_but_keeps_valid_adopter(make_hub, adopt):
    hub, session = make_hub(startup=0.01)
    with hub._lock:
        hub._ensure_loop()
    blocking = threading.Event()

    def stall():
        blocking.set()
        time.sleep(0.12)

    hub._loop.call_soon_threadsafe(stall)
    assert blocking.wait(1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        short = pool.submit(bounded_call, hub, time.monotonic() + 0.03, text="expired")
        until = time.monotonic() + 0.02
        while hub.status()["fake"]["state"] != "starting" and time.monotonic() < until:
            time.sleep(0.001)
        valid = pool.submit(bounded_call, hub, time.monotonic() + 1, text="valid") if adopt else None
        assert not short.result(2).ok
        if valid is not None:
            assert valid.result(2).ok
    time.sleep(0.15)
    assert len(session.owner_starts) == int(adopt)
    assert [text for text, _when in session.calls] == (["valid"] if adopt else [])


def test_expired_lock_wait_returns_without_launch_or_bookkeeping_wait(make_hub):
    hub, session = make_hub()
    held, release = threading.Event(), threading.Event()

    def holder():
        with hub._lock:
            held.set()
            release.wait(1)

    thread = threading.Thread(target=holder)
    thread.start()
    assert held.wait(1)
    try:
        started = time.monotonic()
        result = bounded_call(hub, started + 0.03)
        assert not result.ok
        assert time.monotonic() - started < 0.15
        assert session.calls == [] and session.owner_starts == []
    finally:
        release.set()
        thread.join(1)


def test_semaphore_admission_rechecks_expired_budget_without_one_ms_dispatch(make_hub):
    hub, session = make_hub(ready=True)

    class DelayedAdmission:
        released = 0

        async def acquire(self):
            # Model a completion callback returning after the loop was stalled:
            # wait_for can see an already-done acquisition after its timer fired.
            time.sleep(0.08)
            return True

        def release(self):
            self.released += 1

    semaphore = hub._servers["fake"].semaphore = DelayedAdmission()
    result = bounded_call(hub, time.monotonic() + 0.03)
    assert not result.ok, result
    time.sleep(0.12)
    assert session.calls == []
    assert semaphore.released == 1


def test_short_cold_caller_does_not_cancel_independently_valid_caller(make_hub):
    hub, session = make_hub(startup=0.12)
    with ThreadPoolExecutor(max_workers=2) as pool:
        short = pool.submit(bounded_call, hub, time.monotonic() + 0.03, text="expired")
        long = pool.submit(bounded_call, hub, time.monotonic() + 1, text="valid")
        assert not short.result(2).ok
        assert long.result(2).ok
    assert [text for text, _when in session.calls] == ["valid"]
    assert hub.status()["fake"]["state"] == "ready"


def test_deadline_cancels_only_its_own_inflight_tool(make_hub):
    hub, session = make_hub(ready=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        short = pool.submit(bounded_call, hub, time.monotonic() + 0.04, text="short", seconds=1)
        assert session.entered.wait(1)
        valid = bounded_call(hub, time.monotonic() + 1, text="valid")
        assert valid.ok and valid.text == "valid"
        assert not short.result(2).ok
    assert session.cancelled.wait(1)
    assert hub.status()["fake"]["state"] == "ready"


def test_no_absolute_deadline_preserves_direct_call_startup_semantics(make_hub):
    hub, session = make_hub(startup=0.08)
    result = hub.call("fake", "echo", {"text": "legacy"}, timeout=0.02)
    assert result.ok and result.text == "legacy"
    assert [text for text, _when in session.calls] == ["legacy"]


def test_real_fake_mcp_transport_keeps_valid_calls_after_queued_expiry(tmp_path, monkeypatch):
    fixture = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"
    spec = dm.ServerSpec("fake", sys.executable, (str(fixture),), {}, str(tmp_path),
                         start_timeout=10, call_timeout=2, max_concurrency=1)
    hub = dm.McpHub({"fake": spec}, errlog_dir=tmp_path / "logs")
    try:
        hub.start(wait=12)
        assert hub.status()["fake"]["state"] == "ready", hub.status()
        session = hub._servers["fake"].session
        original = session.call_tool
        entered = threading.Event()
        sent = []

        async def recording(tool, arguments):
            sent.append((tool, arguments, time.monotonic()))
            entered.set()
            return await original(tool, arguments)

        monkeypatch.setattr(session, "call_tool", recording)
        with ThreadPoolExecutor(max_workers=2) as pool:
            valid = pool.submit(hub.call, "fake", "sleep", {"seconds": 0.12}, timeout=2)
            assert entered.wait(2)
            expired = bounded_call(hub, time.monotonic() + 0.03, text="never sent")
            assert not expired.ok
            assert valid.result(3).ok
        assert hub.call("fake", "echo", {"text": "still ready"}, timeout=2).ok
        assert [tool for tool, _args, _when in sent] == ["sleep", "echo"]
    finally:
        hub.close(timeout=2)
    assert hub._thread is None or not hub._thread.is_alive()


def test_writer_handoff_drops_expired_tool_message_and_preserves_valid_sibling(tmp_path, monkeypatch):
    import anyio
    import mcp.types

    written = []
    writer_received = threading.Event()
    original_open = anyio.open_process
    original_dump = mcp.types.JSONRPCMessage.model_dump_json

    async def observed_open(*args, **kwargs):
        process = await original_open(*args, **kwargs)
        original_send = process.stdin.send

        async def observed_send(payload):
            message = json.loads(payload)
            if message.get("method") == "tools/call":
                written.append((message["params"]["arguments"]["text"], time.monotonic()))
            await original_send(payload)

        monkeypatch.setattr(process.stdin, "send", observed_send)
        return process

    def stalled_dump(message, *args, **kwargs):
        payload = original_dump(message, *args, **kwargs)
        decoded = json.loads(payload)
        if decoded.get("method") == "tools/call" and decoded["params"]["arguments"].get("text") == "never sent":
            # Pause the real shared stdin writer after it received the SDK
            # message. Cancelling call_tool alone cannot retract that message.
            writer_received.set()
            time.sleep(0.12)
        return payload

    monkeypatch.setattr(anyio, "open_process", observed_open)
    monkeypatch.setattr(mcp.types.JSONRPCMessage, "model_dump_json", stalled_dump)
    fixture = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"
    spec = dm.ServerSpec("fake", sys.executable, (str(fixture),), {}, str(tmp_path),
                         start_timeout=10, call_timeout=2, max_concurrency=2)
    hub = dm.McpHub({"fake": spec}, errlog_dir=tmp_path / "logs")
    try:
        hub.start(wait=12)
        assert hub.status()["fake"]["state"] == "ready", hub.status()
        with ThreadPoolExecutor(max_workers=2) as pool:
            deadline = time.monotonic() + 0.04
            expired = pool.submit(bounded_call, hub, deadline, text="never sent")
            assert writer_received.wait(2)
            valid = pool.submit(bounded_call, hub, time.monotonic() + 1, text="valid sibling")
            assert not expired.result(2).ok
            assert valid.result(2).ok
        assert [text for text, _when in written] == ["valid sibling"]
        assert hub.call("fake", "echo", {"text": "still reusable"}, timeout=1).ok
    finally:
        hub.close(timeout=2)


def test_real_inflight_deadline_cancellation_preserves_sdk_session_and_valid_call(tmp_path, monkeypatch):
    fixture = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"
    spec = dm.ServerSpec("fake", sys.executable, (str(fixture),), {}, str(tmp_path),
                         start_timeout=10, call_timeout=2, max_concurrency=2)
    hub = dm.McpHub({"fake": spec}, errlog_dir=tmp_path / "logs")
    try:
        hub.start(wait=12)
        assert hub.status()["fake"]["state"] == "ready", hub.status()
        session = hub._servers["fake"].session
        original = session.call_tool
        entered, cancelled = threading.Event(), threading.Event()

        async def observed(tool, arguments):
            entered.set()
            try:
                return await original(tool, arguments)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        monkeypatch.setattr(session, "call_tool", observed)
        with ThreadPoolExecutor(max_workers=1) as pool:
            short = pool.submit(hub.call, "fake", "sleep", {"seconds": 0.5},
                                timeout=1, deadline=time.monotonic() + 0.08)
            assert entered.wait(2)
            valid = hub.call("fake", "echo", {"text": "independent"},
                             timeout=1, deadline=time.monotonic() + 1)
            assert valid.ok and valid.text == "independent"
            assert not short.result(2).ok
        assert cancelled.wait(1)
        assert hub.status()["fake"]["state"] == "ready"
        assert hub.call("fake", "echo", {"text": "after cancellation"}, timeout=1).ok
    finally:
        hub.close(timeout=2)


def test_expired_final_send_branch_never_enters_byte_stream(tmp_path, monkeypatch):
    import anyio

    original_open = anyio.open_process
    written = []
    checks = {}
    original_expired = dm._CallBudget.expired

    def expire_at_final_check(budget):
        count = checks[id(budget)] = checks.get(id(budget), 0) + 1
        return count >= 4 or original_expired(budget)

    async def observed_open(*args, **kwargs):
        process = await original_open(*args, **kwargs)
        original_send = process.stdin.send

        async def observed_send(payload):
            decoded = json.loads(payload)
            if decoded.get("method") == "tools/call":
                written.append(decoded["params"]["arguments"]["text"])
            await original_send(payload)

        monkeypatch.setattr(process.stdin, "send", observed_send)
        return process

    monkeypatch.setattr(anyio, "open_process", observed_open)
    monkeypatch.setattr(dm._CallBudget, "expired", expire_at_final_check)
    fixture = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"
    hub = dm.McpHub({"fake": dm.ServerSpec("fake", sys.executable, (str(fixture),), {},
                                          str(tmp_path), start_timeout=10, call_timeout=1)})
    try:
        hub.start(wait=12)
        assert hub.status()["fake"]["state"] == "ready", hub.status()
        assert not bounded_call(hub, time.monotonic() + 0.08, text="must not enter send").ok
        assert written == []
        assert hub.call("fake", "echo", {"text": "valid direct sibling"}, timeout=1).ok
    finally:
        hub.close(timeout=2)


def test_startup_rejection_cannot_overwrite_later_valid_adoption(tmp_path, monkeypatch):
    __import__("mcp")  # Prime SDK imports before the short synthetic startup budget.

    original_transport = dm._stdio_transport
    rejected, adopted = threading.Event(), threading.Event()
    attempts = []

    @asynccontextmanager
    async def raced_transport(*args, can_start=None, **kwargs):
        attempts.append(time.monotonic())
        if len(attempts) == 1:
            await asyncio.sleep(0.08)
            assert not can_start()
            rejected.set()
            until = time.monotonic() + 1
            while not adopted.is_set() and time.monotonic() < until:
                await asyncio.sleep(0.001)
            assert adopted.is_set()
            raise dm._StartupDeadlineExpired
        async with original_transport(*args, can_start=can_start, **kwargs) as streams:
            yield streams

    monkeypatch.setattr(dm, "_stdio_transport", raced_transport)
    fixture = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"
    hub = dm.McpHub({"fake": dm.ServerSpec("fake", sys.executable, (str(fixture),), {},
                                          str(tmp_path), start_timeout=10, call_timeout=2)})
    original_admit = hub._admit

    def observed_admit(server, deadline=None):
        result = original_admit(server, deadline)
        if rejected.is_set():
            adopted.set()
        return result

    monkeypatch.setattr(hub, "_admit", observed_admit)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            short = pool.submit(bounded_call, hub, time.monotonic() + 0.04, text="expired")
            assert rejected.wait(2)
            valid = pool.submit(bounded_call, hub, time.monotonic() + 1.5, text="valid adopter")
            assert not short.result(2).ok
            result = valid.result(3)
            assert result.ok and result.text == "valid adopter", result
        assert len(attempts) == 2
    finally:
        hub.close(timeout=2)


def test_generic_exception_failure_accounting_does_not_outlive_deadline(make_hub, monkeypatch):
    hub, session = make_hub(ready=True)
    start_holder, held, release = threading.Event(), threading.Event(), threading.Event()

    class BrokenArguments(Mapping):
        def __iter__(self):
            raise RuntimeError("synthetic mapping conversion failure")

        def __len__(self):
            return 1

        def __getitem__(self, key):
            raise KeyError(key)

    def hold():
        assert start_holder.wait(1)
        with hub._lock:
            held.set()
            release.wait(0.3)

    def log_exception(*_args, **_kwargs):
        start_holder.set()
        assert held.wait(1)

    monkeypatch.setattr(dm.logger, "warning", log_exception)
    thread = threading.Thread(target=hold)
    thread.start()
    try:
        started = time.monotonic()
        result = hub.call("fake", "echo", BrokenArguments(), timeout=1, deadline=started + 0.04)
        assert not result.ok and "synthetic mapping conversion failure" in result.error
        assert time.monotonic() - started < 0.15
        assert session.calls == []
    finally:
        release.set()
        thread.join(1)
