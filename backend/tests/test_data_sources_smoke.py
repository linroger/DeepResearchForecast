"""backend/scripts/datamcp_smoke.py — the paced live catalog sweep (fix contract §3 "A2").

The script runs against an injected DataSources over a fake hub that answers with the
real captured payloads (fixtures/data_sources), so selection, batching, the JSON report
and the exit status are checked without any provider call.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

_BRIDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import data_sources as ds  # noqa: E402
from data_mcp import CallResult  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "datamcp_smoke.py"
FIXTURES = Path(__file__).parent / "fixtures" / "data_sources"
REAL = FIXTURES / "real" / "providers"
NOW = 1791763200.0  # 2026-10-12T00:00:00Z


def load_script():
    spec = importlib.util.spec_from_file_location("datamcp_smoke_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Hub:
    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def call(self, provider, tool, args, **kw):
        self.calls.append((provider, tool, json.loads(json.dumps(args))))
        data = self.handler(provider, tool, args)
        return data if isinstance(data, CallResult) else CallResult(True, json.dumps(data), None, 0.0)

    def status(self):
        return {p: {"state": "ready", "error": None, "calls": sum(c[0] == p for c in self.calls), "failures": 0}
                for p in ds.PROVIDERS}

    def start(self, names, **kw):
        pass

    def close(self):
        pass


def fake_source(tmp_path, handler):
    hub = Hub(handler)
    env = {"DATA_SOURCES_ENABLED": "true", "FRED_API_KEY": "synthetic-fred-key-0123", "BLS_API_KEY": "synthetic-bls-key"}
    return ds.DataSources(hub, env=env, cache_dir=tmp_path / "cache", clock=lambda: NOW), hub


def test_report_and_exit_status_follow_every_requested_id(tmp_path):
    payloads = json.loads((FIXTURES / "provider_responses.json").read_text())
    def handler(provider, tool, args):
        if args.get("series_id") == "UNRATE":
            return payloads["fred"]
        return CallResult(False, "", 'FRED API error (400): {"error_message":"Bad Request.  The series does not exist."}', 0.0)
    smoke = load_script()
    source, _ = fake_source(tmp_path, handler)
    report_path = tmp_path / "report.json"
    code = smoke.main(["--series", "fred:UNRATE", "fred:NOSUCHSERIES123", "--report", str(report_path),
                       "--cache-dir", str(tmp_path / "smoke")], source=source)
    assert code == 1
    report = json.loads(report_path.read_text())
    assert report["summary"] == {"fred": {"requested": 2, "ok": 1, "failed": 1, "skipped": 0}}
    ok, bad = report["results"]["fred:UNRATE"], report["results"]["fred:NOSUCHSERIES123"]
    assert ok["ok"] and ok["units_match_catalog"] and ok["latest_observed"]["date"] == "2024-12-01"
    assert bad == {**bad, "ok": False, "code": "unknown_series", "retryable": False}
    assert report["tool_calls"]["fred"]["calls"] == 2 and report["keys"]["FRED_API_KEY"] in ("set", "not set")
    source, _ = fake_source(tmp_path / "again", handler)
    assert smoke.main(["--series", "fred:UNRATE", "--report", str(report_path)], source=source) == 0


def test_catalog_selection_caps_imf_and_skips_unkeyed_recipes():
    smoke = load_script()
    caps = smoke._caps([])
    requested, skipped = smoke.select(providers=["imf", "usgov"], series=None, caps=caps, env={})
    imf = [sid for sid in requested if sid.startswith("imf:")]
    assert len(imf) == 6 and len({sid.split(":")[1].split("/")[0] for sid in imf}) >= 3  # spread over IMF flows
    assert all(reason.endswith("not configured") for sid, reason in skipped.items() if sid.startswith("usgov:"))
    assert any(sid.startswith("usgov:eia/") for sid in skipped) and not any(s.startswith("usgov:eia/") for s in requested)
    keyed, _ = smoke.select(providers=["usgov"], series=None, caps=caps,
                            env={"EIA_API_KEY": "x" * 12, "BEA_API_KEY": "y" * 12})
    assert any(sid.startswith("usgov:bea/") for sid in keyed)
    lifted, _ = smoke.select(providers=["imf"], series=None, caps=smoke._caps(["imf=all"]), env={})
    assert len(lifted) == sum(e.provider == "imf" for e in ds.catalog.CATALOG)
    explicit, none_skipped = smoke.select(providers=None, series=["FRED:unrate", "imf:PCPS/G001.PCOPP.USD.M"],
                                          caps={"imf": 1, "fred": 1}, env={})
    assert explicit == ["fred:UNRATE", "imf:PCPS/G001.PCOPP.USD.M"] and none_skipped == {}


def test_bls_ids_go_out_batched_in_one_year_chunk(tmp_path):
    capture = json.loads((REAL / "bls_ces_lns_2025_2026.json").read_text())
    smoke = load_script()
    source, hub = fake_source(tmp_path, lambda *a: capture["calls"][0]["response"])
    results = smoke.run(source, ["bls:CES0000000001", "bls:LNS14000000"], bls_start="2025-01-01", deadline_s=30,
                        log=lambda line: None)
    assert all(row["ok"] for row in results.values())
    assert [c[2] for c in hub.calls] == [{"series_ids": ["CES0000000001", "LNS14000000"],
                                          "start_year": "2025", "end_year": "2026"}]


@pytest.mark.parametrize("argv", [["--providers", "fred,nope"], ["--max-per-provider", "imf=0"],
                                  ["--bls-start", "last year"], ["--deadline", "0"]])
def test_usage_errors_exit_2_without_calls(tmp_path, argv):
    smoke = load_script()
    source, hub = fake_source(tmp_path, lambda *a: pytest.fail("no call expected"))
    assert smoke.main(argv, source=source) == 2 and hub.calls == []
