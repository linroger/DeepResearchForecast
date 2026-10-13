"""Real official-data rows for downstream consumer tests (slice H).

Replays the real MCP captures of fixtures/data_sources/real/providers/*.json through the
current data layer at their capture clock (the adapter issues the requests it made live),
then persists them exactly as research does, so consumers see real normalized carriers.
Bridge modules load by bare name from deerflow_bridge/ (tests/test_research_gateway.py).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_BRIDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import data_sources as ds  # noqa: E402
from data_mcp import CallResult  # noqa: E402

REAL = Path(__file__).parent / "fixtures" / "data_sources" / "real"


class _Hub:
    def __init__(self, recorded):
        self.recorded = recorded

    def call(self, provider, tool, args, **kw):
        response = next(c["response"] for c in self.recorded["calls"] if (c["provider"], c["tool"]) == (provider, tool))
        return CallResult(True, json.dumps(response), None, 0.0)

    def status(self):
        return {p: {"state": "ready", "error": None} for p in ds.PROVIDERS}

    def start(self, names, **kw):
        pass

    def close(self):
        pass


def replay(name: str, tmp_path: Path) -> "ds.Series":
    """One real provider capture normalized by the current data layer."""
    recorded = json.loads((REAL / "providers" / f"{name}.json").read_text())
    source = ds.DataSources(_Hub(recorded), env={"DATA_SOURCES_ENABLED": "true", "FRED_API_KEY": "synthetic-key-123456"},
                            cache_dir=tmp_path / f"cache-{name}", clock=lambda: recorded["clock"])
    series = source.get(recorded["series"], **recorded["request"])
    assert not isinstance(series, ds.DataError), series
    return series


def stored_row(name: str) -> dict:
    """A trimmed stored row captured live (real/downstream/<name>.json)."""
    return json.loads((REAL / "downstream" / f"{name}.json").read_text())["row"]


def publish(series_list, handoff: Path) -> Path:
    """Persist like research does (data/datasets.json + hashed JSON/CSV, citations S1..Sn)."""
    rows = [s if isinstance(s, ds.Series) else ds.Series.from_dict(s) for s in series_list]
    manifest = ds.write_dataset_files(rows, handoff, citations={s.series: f"S{i}" for i, s in enumerate(rows, 1)})
    assert "error" not in manifest, manifest
    return handoff
