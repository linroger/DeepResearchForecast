"""POST /api/settings/data-sources/test and the shared doctor --deep data probe (I4).

The probe is advisory and bounded: per enabled provider an MCP handshake plus one
cache-first catalog sample (BLS: handshake only), key NAMES with set / not set /
invalid, never key values. Fakes stand in for the hub and DataSources; their
results are real ``data_sources.Series`` / ``DataError`` objects so the probe reads
the production data model. One test drives the real McpHub + DataSources over the
synthetic stdio fixture server; another runs doctor.sh's embedded probe program
against a stub backend. Nothing here reaches a provider.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from app.api import settings as settings_api
from app.config import Config

_BRIDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import data_catalog as catalog  # noqa: E402
import data_mcp as dm  # noqa: E402
import data_sources as ds  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "official_data_mcp.py"
FRED_SECRET = "fred-secret-value-0123456789"
BLS_SECRET = "bls-secret-value-9876543210"
EIA_SECRET = "eia-secret-value-5555555555"


def _series(series_id, route, values=(("2026-07-01", 4.2), ("2026-08-01", 4.3))):
    return ds.Series(series_id, observations=[{"date": d, "value": v} for d, v in values], route=route)


class FakeHub:
    def __init__(self, states):
        self.states = states
        self.started = []
        self.closed = False

    def start(self, names, wait=None):
        self.started.append((tuple(names), wait))

    def status(self):
        return {name: dict(state) for name, state in self.states.items()}

    def close(self, timeout=5.0):
        self.closed = True


class FakeDataSources:
    def __init__(self, statuses, results, *, after=None, block=None):
        self.statuses = statuses
        self.after = after
        self.results = results
        self.block = block or {}
        self.calls = []
        self.closed = False

    def providers(self):
        return dict(self.after if self.after is not None and self.calls else self.statuses)

    def get_many(self, ids, *, deadline_s, **kwargs):
        self.calls.append((list(ids), deadline_s, kwargs))
        for sid in ids:
            event = self.block.get(sid)
            if event is not None:
                event.wait(10)
        return {sid: self.results[sid] for sid in ids}

    def close(self):
        self.closed = True


def _ready(tools=3):
    return {"state": "ready", "error": None, "tools": [f"t{i}" for i in range(tools)], "ready_s": 0.4,
            "calls": 0, "failures": 0}


@pytest.fixture
def data_env(monkeypatch):
    monkeypatch.setattr(Config, "DATA_SOURCES_ENABLED", True)
    monkeypatch.setattr(Config, "DATA_SOURCES", "fred,bls,bis,imf,wb,usgov")
    monkeypatch.setenv("FRED_API_KEY", FRED_SECRET)
    monkeypatch.setenv("BLS_API_KEY", BLS_SECRET)
    monkeypatch.setenv("EIA_API_KEY", EIA_SECRET)


def _install(monkeypatch, hub, client):
    built = []

    def factory(env):
        built.append(env)
        return hub, client

    monkeypatch.setattr(settings_api, "_default_data_probe_clients", factory)
    return built


def _post(path="/api/settings/data-sources/test", **kwargs):
    from app import create_app
    return create_app().test_client().post(path, **kwargs)


def test_probe_samples_are_catalog_series_and_bls_is_handshake_only():
    assert set(settings_api._DATA_PROBE_SAMPLES) | {"bls"} == set(settings_api._DATA_PROVIDERS)
    assert set(settings_api._DATA_PROVIDERS) == set(catalog.PROVIDERS)
    for provider, series_id in settings_api._DATA_PROBE_SAMPLES.items():
        entry = catalog.lookup(series_id)
        assert entry is not None and entry.provider == provider, series_id
    assert "bls" not in settings_api._DATA_PROBE_SAMPLES
    keyed = {key for _, key in dm.USGOV_KEYED_MODULES}
    assert set(settings_api._DATA_PROBE_KEYS["usgov"]) == keyed


def test_endpoint_reports_every_provider_with_key_names_never_values(monkeypatch, data_env):
    hub = FakeHub({"fred": _ready(), "bls": _ready(6), "bis": _ready(4),
                   "imf": {"state": "failed", "error": "process exited during startup", "tools": []},
                   "wb": {"state": "idle", "error": None, "tools": []}, "usgov": _ready(36)})
    results = {
        "fred:UNRATE": _series("fred:UNRATE", "mcp"),
        "bis:WS_CBPOL/M.US": ds.DataError(
            series="bis:WS_CBPOL/M.US", retryable=True, code="rate_limited",
            message=f"HTTP 429 from https://x.example/data?api_key={FRED_SECRET}&f=json"),
        "imf:WEO/G001.NGDP_RPCH.A": ds.DataError(series="imf:WEO/G001.NGDP_RPCH.A", retryable=True,
                                                 code="timeout", message="Data request deadline exceeded"),
        "usgov:treasury/debt_to_penny": _series("usgov:treasury/debt_to_penny", "cache"),
    }
    client = FakeDataSources({"fred": "ready", "bls": "ready", "bis": "ready", "imf": "process exited",
                              "wb": "disabled", "usgov": "ready"}, results)
    built = _install(monkeypatch, hub, client)

    response = _post()

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    data = body["data"]
    assert data["enabled"] is True and data["deadline_s"] == settings_api._DATA_TEST_DEADLINE_SECONDS
    rows = data["providers"]
    assert set(rows) == {"fred", "bls", "bis", "imf", "wb", "usgov"}
    for row in rows.values():
        assert set(row) == {"state", "detail", "latency_s", "keys"}
        assert isinstance(row["latency_s"], float) and row["latency_s"] >= 0
    assert {name: row["state"] for name, row in rows.items()} == {
        "fred": "ok", "bls": "ok", "bis": "degraded", "imf": "unavailable", "wb": "disabled", "usgov": "ok"}
    assert "3 tools" in rows["fred"]["detail"] and "2 observations to 2026-08-01 (live via mcp)" in rows["fred"]["detail"]
    assert "handshake only" in rows["bls"]["detail"]
    assert "DATA_UNAVAILABLE[rate_limited]" in rows["bis"]["detail"] and "api_key=[redacted]" in rows["bis"]["detail"]
    assert "process exited during startup" in rows["imf"]["detail"]
    assert "DATA_UNAVAILABLE[timeout]" in rows["imf"]["detail"]
    assert rows["wb"]["detail"] == "disabled by DATA_SOURCES"
    assert "(from cache)" in rows["usgov"]["detail"]
    assert rows["fred"]["keys"] == {"FRED_API_KEY": "set"}
    assert rows["bls"]["keys"] == {"BLS_API_KEY": "set"}
    assert rows["usgov"]["keys"] == {"EIA_API_KEY": "set", "BEA_API_KEY": "not set", "CENSUS_API_KEY": "not set"}
    assert rows["bis"]["keys"] == rows["imf"]["keys"] == rows["wb"]["keys"] == {}
    text = response.get_data(as_text=True)
    for secret in (FRED_SECRET, BLS_SECRET, EIA_SECRET):
        assert secret not in text
    # BLS is never fetched (keyless quota); wb is disabled; one sample per remaining provider.
    requested = [ids for ids, _, _ in client.calls]
    assert sorted(requested) == [["bis:WS_CBPOL/M.US"], ["fred:UNRATE"], ["imf:WEO/G001.NGDP_RPCH.A"],
                                 ["usgov:treasury/debt_to_penny"]]
    assert all(0 < deadline <= settings_api._DATA_TEST_DEADLINE_SECONDS for _, deadline, _ in client.calls)
    assert hub.started[0] == (("fred", "bls", "bis", "imf", "usgov"), None)
    assert client.closed and hub.closed
    # The probe sees the research subprocess's data env (Config is the source of truth).
    assert built[0]["DATA_SOURCES_ENABLED"] == "true" and built[0]["FRED_API_KEY"] == FRED_SECRET


def test_keyless_and_rejected_keys_degrade_without_misattributing_refusals(monkeypatch):
    env = {"DATA_SOURCES_ENABLED": "true", "BLS_API_KEY": ""}
    hub = FakeHub({name: _ready() for name in settings_api._DATA_PROVIDERS})
    results = {
        "fred:UNRATE": _series("fred:UNRATE", "fred_csv"),
        "bis:WS_CBPOL/M.US": ds.DataError(series="bis:WS_CBPOL/M.US", code="key_invalid",
                                          message="HTTP 403 Forbidden"),
        "imf:WEO/G001.NGDP_RPCH.A": _series("imf:WEO/G001.NGDP_RPCH.A", "mcp", (("2025-01-01", 3.1),)),
        "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA": _series("wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA", "mcp",
                                                   (("2024-01-01", 2.8),)),
        "usgov:treasury/debt_to_penny": _series("usgov:treasury/debt_to_penny", "mcp"),
    }
    client = FakeDataSources({name: "ready" for name in settings_api._DATA_PROVIDERS} | {"fred": "keyless"},
                             results)
    rows = settings_api.probe_data_sources(env=env, clients=lambda _env: (hub, client))["providers"]
    assert rows["fred"]["state"] == "degraded" and rows["fred"]["keys"] == {"FRED_API_KEY": "not set"}
    assert "live via fred_csv" in rows["fred"]["detail"] and "FRED_API_KEY not set" in rows["fred"]["detail"]
    assert rows["bls"]["state"] == "degraded" and "20 requests per day" in rows["bls"]["detail"]
    # A keyless provider's 403 is a provider refusal, never a "bad key".
    assert rows["bis"]["state"] == "degraded" and rows["bis"]["keys"] == {}
    assert "rejected" not in rows["bis"]["detail"]

    # A configured FRED key the provider rejects: error code or the data layer's own flag.
    env = {"DATA_SOURCES_ENABLED": "true", "FRED_API_KEY": FRED_SECRET, "BLS_API_KEY": BLS_SECRET}
    results["fred:UNRATE"] = ds.DataError(series="fred:UNRATE", code="key_invalid",
                                          message="The api_key provided is invalid")
    client = FakeDataSources({name: "ready" for name in settings_api._DATA_PROVIDERS}, results)
    rows = settings_api.probe_data_sources(env=env, clients=lambda _env: (FakeHub(hub.states), client))["providers"]
    assert rows["fred"]["state"] == "degraded" and rows["fred"]["keys"] == {"FRED_API_KEY": "invalid"}
    assert "FRED_API_KEY rejected by the provider" in rows["fred"]["detail"]
    assert rows["bls"]["state"] == "ok" and rows["bls"]["keys"] == {"BLS_API_KEY": "set"}

    results["fred:UNRATE"] = _series("fred:UNRATE", "fred_csv")
    client = FakeDataSources({name: "ready" for name in settings_api._DATA_PROVIDERS}, results,
                             after={name: "ready" for name in settings_api._DATA_PROVIDERS} | {"fred": "key_invalid"})
    rows = settings_api.probe_data_sources(env=env, clients=lambda _env: (FakeHub(hub.states), client))["providers"]
    assert rows["fred"]["state"] == "degraded" and rows["fred"]["keys"] == {"FRED_API_KEY": "invalid"}
    assert FRED_SECRET not in json.dumps(rows)


def test_disabled_switch_reports_disabled_without_starting_servers(monkeypatch):
    monkeypatch.setattr(Config, "DATA_SOURCES_ENABLED", False)

    def forbidden(env):
        raise AssertionError("a disabled probe must not build a hub")

    monkeypatch.setattr(settings_api, "_default_data_probe_clients", forbidden)
    response = _post()
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["enabled"] is False
    assert {row["state"] for row in data["providers"].values()} == {"disabled"}
    assert data["providers"]["fred"]["detail"] == "DATA_SOURCES_ENABLED=false"


def test_probe_is_bounded_when_a_provider_hangs(monkeypatch):
    monkeypatch.setattr(settings_api, "_DATA_TEST_GRACE_SECONDS", 0.2)
    release = threading.Event()
    hub = FakeHub({name: _ready() for name in settings_api._DATA_PROVIDERS})
    results = {sid: _series(sid, "cache", (("2025-01-01", 1.0),))
               for sid in settings_api._DATA_PROBE_SAMPLES.values()}
    client = FakeDataSources({name: "ready" for name in settings_api._DATA_PROVIDERS}, results,
                             block={"imf:WEO/G001.NGDP_RPCH.A": release})
    env = {"DATA_SOURCES_ENABLED": "true", "FRED_API_KEY": FRED_SECRET, "BLS_API_KEY": BLS_SECRET}
    started = time.monotonic()
    try:
        result = settings_api.probe_data_sources(env=env, deadline_s=0.5, clients=lambda _env: (hub, client))
    finally:
        release.set()
    assert time.monotonic() - started < 3.0
    rows = result["providers"]
    assert rows["imf"]["state"] == "unavailable" and rows["imf"]["detail"] == "probe deadline exceeded"
    assert rows["fred"]["state"] == "ok" and rows["usgov"]["state"] == "ok"
    assert result["deadline_s"] == 0.5 and client.closed and hub.closed


def test_private_hub_is_closed_within_the_probe_close_bound(monkeypatch, tmp_path):
    """The endpoint's own wall-clock bound includes closing its private hub. The hub is
    closed with _DATA_TEST_CLOSE_SECONDS before the real DataSources is closed (whose close()
    would otherwise close the shared hub first with McpHub's default timeout)."""
    monkeypatch.setattr(settings_api, "_DATA_TEST_CLOSE_SECONDS", 0.25)

    class RecordingHub(FakeHub):
        def __init__(self, states):
            super().__init__(states)
            self.close_timeouts = []

        def close(self, timeout=5.0):
            self.close_timeouts.append(timeout)
            self.closed = True

    hub = RecordingHub({"bls": _ready()})
    env = {"DATA_SOURCES_ENABLED": "true", "DATA_SOURCES": "bls"}
    client = ds.DataSources(hub, env=env, providers=["bls"], cache_dir=tmp_path / "cache")
    rows = settings_api.probe_data_sources(env=env, deadline_s=5, clients=lambda _env: (hub, client))["providers"]
    assert rows["bls"]["state"] == "degraded" and "handshake only" in rows["bls"]["detail"]
    assert hub.close_timeouts[0] == 0.25


def test_endpoint_bound_is_documented_and_within_its_clients_timeouts():
    """Worst case: probe budget + worker grace + private-hub close (its timeout plus McpHub's
    kill/join grace). The Settings card and doctor --deep must wait at least that long."""
    bound = settings_api._DATA_TEST_MAX_SECONDS
    assert bound == (settings_api._DATA_TEST_DEADLINE_SECONDS + settings_api._DATA_TEST_GRACE_SECONDS
                     + settings_api._DATA_TEST_CLOSE_SECONDS + settings_api._DATA_HUB_CLOSE_OVERHEAD_SECONDS) == 90.0
    # McpHub.close beyond its timeout: ≤ 1 s SIGTERM wait, TERM grace, cancel grace, a final
    # ≤ 1 s SIGTERM wait and the 2 s event-loop thread join.
    assert settings_api._DATA_HUB_CLOSE_OVERHEAD_SECONDS == 1.0 + dm._TERM_GRACE_S * 2 + 1.0 + 2.0
    root = Path(__file__).resolve().parents[2]
    frontend = (root / "frontend" / "src" / "api" / "settings.js").read_text(encoding="utf-8")
    call = frontend[frontend.index("export function testDataSources"):]
    timeout_ms = int(call[call.index("timeout:") + len("timeout:"):].split("}")[0].strip())
    assert timeout_ms >= bound * 1000
    assert "up to ~90s" in (root / "scripts" / "doctor.sh").read_text(encoding="utf-8")


def test_concurrent_probe_is_refused_with_409(monkeypatch, data_env):
    _install(monkeypatch, FakeHub({}), FakeDataSources({}, {}))
    assert settings_api._DATA_PROBE_LOCK.acquire(blocking=False)
    try:
        response = _post()
    finally:
        settings_api._DATA_PROBE_LOCK.release()
    assert response.status_code == 409
    assert response.get_json()["success"] is False


def test_missing_data_layer_reports_unavailable_rows_not_a_server_error(monkeypatch, data_env):
    def broken(env):
        raise RuntimeError("official-data bridge module unavailable")

    monkeypatch.setattr(settings_api, "_default_data_probe_clients", broken)
    response = _post()
    assert response.status_code == 200
    rows = response.get_json()["data"]["providers"]
    assert {row["state"] for row in rows.values()} == {"unavailable"}
    assert rows["wb"]["detail"] == "official-data layer unavailable (RuntimeError)"


def test_endpoint_uses_the_same_remote_gate_as_llm_test(monkeypatch, data_env):
    hub = FakeHub({name: _ready() for name in settings_api._DATA_PROVIDERS})
    results = {sid: _series(sid, "cache") for sid in settings_api._DATA_PROBE_SAMPLES.values()}
    _install(monkeypatch, hub, FakeDataSources({name: "ready" for name in settings_api._DATA_PROVIDERS}, results))
    remote = {"REMOTE_ADDR": "203.0.113.7"}
    monkeypatch.setattr(Config, "APP_API_TOKEN", "")
    assert _post(environ_base=remote).status_code == 403
    assert _post("/api/settings/llm/test", environ_base=remote).status_code == 403
    monkeypatch.setattr(Config, "APP_API_TOKEN", "synthetic-token")
    assert _post(environ_base=remote, headers={"X-API-Token": "wrong"}).status_code == 401
    response = _post(environ_base=remote, headers={"X-API-Token": "synthetic-token"})
    assert response.status_code == 200 and response.get_json()["data"]["providers"]["fred"]["state"] == "ok"


def test_real_hub_and_data_sources_probe_then_serve_the_sample_from_cache(tmp_path):
    receipt = tmp_path / "calls.jsonl"
    server_cwd = tmp_path / "server"
    server_cwd.mkdir()
    env = {"DATA_SOURCES_ENABLED": "true", "FRED_API_KEY": FRED_SECRET, "DATA_SOURCES": "fred"}

    def clients(probe_env):
        spec = dm.ServerSpec(name="fred", command=sys.executable, args=(str(FIXTURE),),
                             env={"OFFICIAL_DATA_FIXTURE_RECEIPT": str(receipt)}, cwd=str(server_cwd),
                             start_timeout=20.0, call_timeout=10.0, max_concurrency=1)
        hub = dm.McpHub({"fred": spec}, errlog_dir=tmp_path / "mcp-logs")
        return hub, ds.DataSources(hub, env=probe_env, providers=["fred"], cache_dir=tmp_path / "cache")

    first = settings_api.probe_data_sources(env=env, deadline_s=30, clients=clients)["providers"]
    assert first["fred"]["state"] == "ok", first["fred"]
    assert "1 tools" in first["fred"]["detail"] and "live via mcp" in first["fred"]["detail"]
    assert "16 observations to 2025-06-01" in first["fred"]["detail"]
    assert {first[name]["state"] for name in ("bls", "bis", "imf", "wb", "usgov")} == {"disabled"}
    second = settings_api.probe_data_sources(env=env, deadline_s=30, clients=clients)["providers"]
    assert second["fred"]["state"] == "ok" and "(from cache)" in second["fred"]["detail"]
    # The repeat probe still handshakes, but the sample costs no second upstream call.
    assert len(receipt.read_text().splitlines()) == 1
    assert FRED_SECRET not in json.dumps([first, second])


def _doctor_probe_script(tmp_path):
    """doctor.sh's embedded probe program, as a file the guarded runner can admit by hash."""
    text = (Path(__file__).resolve().parents[2] / "scripts" / "doctor.sh").read_text(encoding="utf-8")
    start = text.index("DOCTOR_DATA_PROBE='") + len("DOCTOR_DATA_PROBE='")
    script = tmp_path / "doctor_data_probe.py"
    script.write_text(text[start:text.index("'\n", start)], encoding="utf-8")
    guard = sys.modules.get("main_offline_guard")
    if guard is not None:
        guard.allow_python_script(script)
    return script


def test_doctor_deep_renders_the_shared_probe_as_advisory_level_lines(tmp_path):
    import subprocess

    backend = tmp_path / "backend"
    (backend / "app" / "api").mkdir(parents=True)
    (backend / "app" / "__init__.py").write_text("print('[04:53:53] INFO: backend log noise on stdout')\n")
    (backend / "app" / "api" / "__init__.py").write_text("")
    rows = {
        "fred": {"state": "ok", "detail": "MCP handshake ok", "latency_s": 1.2, "keys": {"FRED_API_KEY": "set"}},
        "bls": {"state": "degraded", "detail": "BLS_API_KEY not set", "latency_s": 0.3,
                "keys": {"BLS_API_KEY": "not set"}},
        "bis": {"state": "unavailable", "detail": "MCP server unavailable:\tnot built", "latency_s": 0.0, "keys": {}},
        "wb": {"state": "disabled", "detail": "disabled by DATA_SOURCES", "latency_s": 0.0, "keys": {}},
    }
    (backend / "app" / "api" / "settings.py").write_text(
        "import json\nprint('INFO: settings import noise')\n"
        f"def probe_data_sources():\n    return {{'providers': json.loads({json.dumps(json.dumps(rows))})}}\n")
    script = _doctor_probe_script(tmp_path)
    env = {"DOCTOR_BACKEND_DIR": str(backend), "PATH": os.environ.get("PATH", "")}
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=30, env=env)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines == [
        "ok\tdata fred: ok (1.2s) — MCP handshake ok [FRED_API_KEY set]",
        "warn\tdata bls: degraded (0.3s) — BLS_API_KEY not set [BLS_API_KEY not set]",
        "warn\tdata bis: unavailable (0.0s) — MCP server unavailable: not built",
        "ok\tdata wb: disabled (0.0s) — disabled by DATA_SOURCES",
    ]
    assert "noise" in result.stderr  # backend stdout logging is parked on stderr, off the protocol

    (backend / "app" / "api" / "settings.py").write_text("raise ImportError('broken backend')\n")
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=30, env=env)
    assert result.returncode == 0
    assert result.stdout.splitlines() == ["warn\tofficial-data probe unavailable (ImportError)"]
