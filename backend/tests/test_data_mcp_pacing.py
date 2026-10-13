"""Hub pacing and rejected-key respawn (deerflow_bridge/data_mcp.py; fix contract §3 "A2").

``tests/fixtures/fake_mcp_server.py`` stands in for a data server (no network, no
node). Covers the per-spec rolling-minute call cap (FRED: 50 calls = 100 upstream
requests a minute under the key's 120) and :meth:`McpHub.restart_without`, which
respawns a server without an API key the provider rejected (BLS then serves keyless).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BRIDGE_DIR = os.path.join(_REPO_ROOT, "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import data_mcp as dm  # noqa: E402

FAKE_SERVER = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"
SECRET = "rejected-registration-key-0123456789"


def spec(name: str, cwd: Path, **kw) -> dm.ServerSpec:
    cwd.mkdir(parents=True, exist_ok=True)
    values = {"env": {}, "start_timeout": 20.0, "call_timeout": 10.0, **kw}
    return dm.ServerSpec(name=name, command=sys.executable, args=(str(FAKE_SERVER),), cwd=str(cwd), **values)


def probe(hub: dm.McpHub, name: str, var: str) -> dict:
    result = hub.call(name, "env_probe", {"name": var})
    assert result.ok, result
    return json.loads(result.text)


def test_rate_window_admits_limit_per_rolling_minute_then_fails_within_the_deadline(tmp_path):
    hub = dm.McpHub({"fred": spec("fred", tmp_path / "cwd", max_calls_per_minute=2)}, errlog_dir=tmp_path / "logs")
    try:
        assert hub.call("fred", "echo", {"text": "a"}).ok and hub.call("fred", "echo", {"text": "b"}).ok
        started = time.monotonic()
        third = hub.call("fred", "echo", {"text": "c"}, deadline=time.monotonic() + 0.5)
        assert not third.ok and "local rate limit of 2 fred calls per minute" in third.error
        assert time.monotonic() - started < 0.4  # refused at once: the slot frees only after a minute
        timed = hub.call("fred", "echo", {"text": "d"}, timeout=1.0)
        assert not timed.ok and "rate limit" in timed.error
        assert hub.status()["fred"]["calls"] == 4 and hub.status()["fred"]["failures"] == 2
    finally:
        hub.close()


def test_rate_window_waits_for_a_freed_slot_inside_the_deadline(monkeypatch):
    clock = [100.0]
    slept = []
    monkeypatch.setattr(dm.time, "monotonic", lambda: clock[0])
    def sleep(seconds):
        slept.append(seconds)
        clock[0] += seconds
    monkeypatch.setattr(dm.time, "sleep", sleep)
    window = dm._RateWindow(1)
    assert window.admit(wait_until=100.0)
    clock[0] = 130.0
    assert not window.admit(wait_until=150.0)  # the slot frees at 160
    assert window.admit(wait_until=161.0) and slept == [30.0]


def test_refused_calls_never_take_or_wait_for_a_rate_slot(tmp_path):
    # A FRED server that cannot run (not built) answers every call with its reason at once: the
    # data layer then falls back to the keyless CSV route, so a refusal must neither spend one of
    # the minute's slots nor sleep for a freed one.
    unavailable = "not built: run npm run setup:datamcps (missing fred-mcp-server-main/build/index.js)"
    hub = dm.McpHub({"fred": spec("fred", tmp_path / "cwd", max_calls_per_minute=1, unavailable_reason=unavailable)},
                    errlog_dir=tmp_path / "logs")
    try:
        started = time.monotonic()
        results = [hub.call("fred", "echo", {"text": str(i)}, deadline=time.monotonic() + 30) for i in range(3)]
        assert [r.error for r in results] == [unavailable] * 3
        assert time.monotonic() - started < 5 and not hub._rates["fred"]._admitted
    finally:
        hub.close()
    closed = hub.call("fred", "echo", {"text": "late"}, timeout=5)
    assert closed.error == "data hub is closed" and not hub._rates["fred"]._admitted


def test_unpaced_servers_are_unaffected(tmp_path):
    hub = dm.McpHub({"bis": spec("bis", tmp_path / "cwd")}, errlog_dir=tmp_path / "logs")
    try:
        assert all(hub.call("bis", "echo", {"text": str(i)}).ok for i in range(5))
    finally:
        hub.close()


def test_restart_without_respawns_the_server_without_the_rejected_key(tmp_path):
    hub = dm.McpHub({"bls": spec("bls", tmp_path / "cwd", env={"BLS_API_KEY": SECRET, "OTHER": "kept"})},
                    errlog_dir=tmp_path / "logs")
    try:
        first_pid = int(hub.call("bls", "pid", {}).text)
        assert probe(hub, "bls", "BLS_API_KEY") == {"set": True, "length": len(SECRET)}
        assert hub.restart_without("bls", ["BLS_API_KEY"]) is True
        assert probe(hub, "bls", "BLS_API_KEY") == {"set": False, "length": 0}
        assert probe(hub, "bls", "OTHER")["set"] is True
        assert int(hub.call("bls", "pid", {}).text) != first_pid
        assert hub.status()["bls"]["state"] == "ready"
        # Nothing left to drop, unknown server: no respawn.
        assert hub.restart_without("bls", ["BLS_API_KEY"]) is False
        assert hub.restart_without("nope", ["BLS_API_KEY"]) is False
        # The previous child is gone (its session was closed).
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(first_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            pytest.fail("the replaced server process is still alive")
    finally:
        hub.close()
    assert hub.restart_without("bls", ["OTHER"]) is False  # closed hub


def test_restart_without_before_first_start_and_secret_still_redacted(tmp_path):
    hub = dm.McpHub({"bls": spec("bls", tmp_path / "cwd", env={"BLS_API_KEY": SECRET})}, errlog_dir=tmp_path / "logs")
    try:
        assert hub.restart_without("bls", "BLS_API_KEY") is True  # idle server: next call spawns keyless
        assert probe(hub, "bls", "BLS_API_KEY")["set"] is False
        echoed = hub.call("bls", "echo", {"text": f"The key:{SECRET} provided by the User is invalid."})
        assert SECRET not in echoed.text
    finally:
        hub.close()


def test_restart_without_while_starting_never_serves_the_old_key(tmp_path):
    hub = dm.McpHub({"bls": spec("bls", tmp_path / "cwd", env={"BLS_API_KEY": SECRET})}, errlog_dir=tmp_path / "logs")
    try:
        hub.start(["bls"])  # background launch, superseded before or while it starts
        assert hub.restart_without("bls", ("BLS_API_KEY",)) is True
        assert probe(hub, "bls", "BLS_API_KEY")["set"] is False
        assert hub.status()["bls"]["state"] == "ready"
        # The superseded launch ends instead of spawning a second, keyed child.
        deadline = time.monotonic() + 5
        while len(hub._owners) > 1 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(hub._owners) == 1
    finally:
        hub.close()


def test_default_specs_pace_fred_only(tmp_path):
    root = tmp_path / "absent"
    env = {"DATA_SOURCES_DIR": str(root), "DATA_SOURCES_CACHE_DIR": str(tmp_path / "cache")}
    specs = dm.default_server_specs(env=env)
    assert specs["fred"].max_calls_per_minute == dm.FRED_CALLS_PER_MINUTE == 50
    assert all(specs[name].max_calls_per_minute == 0 for name in dm.PROVIDERS if name != "fred")
    assert dm.default_server_specs(env={**env, "DATA_SOURCES_FRED_PER_MINUTE": "30"})["fred"].max_calls_per_minute == 30
    for bogus in ("0", "500", "fast"):
        assert dm.default_server_specs(env={**env, "DATA_SOURCES_FRED_PER_MINUTE": bogus})["fred"].max_calls_per_minute == 50
