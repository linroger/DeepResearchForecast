"""TIME-13: the v3 research engine's official-data tools (macro_series / company_filings).

Offline: the data functions are fakes returning data_tools.DataResult objects, or the real FRED /
SEC EDGAR renderers driven through fake transports; every model call is a ScriptedModel.  Pinned
here: with RESEARCH_DATA_TOOLS unset the agents' tools object is AGENT_TOOLS_SCHEMA itself and the
KIQ task, sources.json, quantitative.json and meta['tools'] are what they were; enabled, one tools
list is bound once per run, only data-kind KIQ tasks carry the guidance, a tool without its
credential is never bound (meta.data_tools.disabled says why) and the run identity names the
enabled tools; a step runs at most MAX_TOOL_CALLS_PER_STEP calls of any tool, a repeated data call
of a step is a DUPLICATE, the per-KIQ data allowance is enforced, data failures never count as
fetch failures and a stopped run answers CANCELLED; findings copying a data value verify, cited
data rows reach sources.json (S1, dated on or before the as-of, vendor supports and a data block)
and head quantitative.json, model rows contradicting a data page are dropped and listed; the
vintage pin is fixed once per run and survives a resume, and in a gated hindcast every data row
is dated strictly before the as-of.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_BRIDGE = str(_REPO / "deerflow_bridge")
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

import data_tools as dtools  # noqa: E402
import linear_research as lr  # noqa: E402
import test_research_engine_v3 as v3  # noqa: E402

_ENV_NAMES = ("RESEARCH_DATA_TOOLS", "FRED_API_KEY", "SEC_EDGAR_USER_AGENT", "DATA_QUANT_ROWS_MAX",
              "DATA_TOOLS_CACHE_DIR", "DATA_FRED_CACHE_TTL_H", "DATA_EDGAR_CACHE_TTL_H", "DATA_TOOL_TIMEOUT_S",
              "DATA_FRED_WINDOW_YEARS", "RESEARCH_AS_OF", "RESEARCH_PIT_GATES", "RESEARCH_PIT_SAME_DAY",
              "RESEARCH_PIT_UNDATED", "RESEARCH_PIT_PROVIDER_BOUNDS", "RESEARCH_PIT_OVERFETCH",
              "RESEARCH_SOURCE_DATES")


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    """Engine and vendor knobs only from the test; no throttle waits; the vendor cache in tmp_path."""
    for name in list(os.environ):
        if name.startswith("RESEARCH_LINEAR_") or name in v3._ENV_EXACT or name in _ENV_NAMES:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATA_TOOLS_CACHE_DIR", str(tmp_path / "data_cache"))
    monkeypatch.setattr(dtools, "_FRED_THROTTLE", dtools._Throttle(0))
    monkeypatch.setattr(dtools, "_EDGAR_THROTTLE", dtools._Throttle(0))


bridge = v3.bridge


# =============================================================== presets

def test_presets_carry_the_data_call_allowances_and_their_overrides():
    assert [(lr.resolve_preset(depth, {}).data_calls_per_kiq, lr.resolve_preset(depth, {}).max_data_calls_total)
            for depth in ("quick", "standard", "deep")] == [(2, 12), (3, 30), (4, 60)]
    preset = lr.resolve_preset("standard", {"RESEARCH_LINEAR_DATA_CALLS_PER_KIQ": "7",
                                            "RESEARCH_LINEAR_MAX_DATA_CALLS_TOTAL": "9999"})
    assert (preset.data_calls_per_kiq, preset.max_data_calls_total) == (7, 500)
    assert any("RESEARCH_LINEAR_MAX_DATA_CALLS_TOTAL=9999 is outside [0, 500]" in note for note in preset.notes)
    assert lr._KNOB_BOUNDS["data_calls_per_kiq"] == (0, 20)
