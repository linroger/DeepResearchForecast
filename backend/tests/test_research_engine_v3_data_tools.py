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

import datetime as dt
import os
import re
import string
import sys
import threading
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_BRIDGE = str(_REPO / "deerflow_bridge")
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

import data_tools as dtools  # noqa: E402
import linear_research as lr  # noqa: E402
import research_gateway as rg  # noqa: E402
import test_research_engine_v3 as v3  # noqa: E402

_ENV_NAMES = ("RESEARCH_DATA_TOOLS", "FRED_API_KEY", "SEC_EDGAR_USER_AGENT", "DATA_QUANT_ROWS_MAX",
              "DATA_TOOLS_CACHE_DIR", "DATA_FRED_CACHE_TTL_H", "DATA_EDGAR_CACHE_TTL_H", "DATA_TOOL_TIMEOUT_S",
              "DATA_FRED_WINDOW_YEARS", "RESEARCH_AS_OF", "RESEARCH_PIT_GATES", "RESEARCH_PIT_SAME_DAY",
              "RESEARCH_PIT_UNDATED", "RESEARCH_PIT_PROVIDER_BOUNDS", "RESEARCH_PIT_OVERFETCH",
              "RESEARCH_SOURCE_DATES")
KEY = "0123456789abcdef0123456789abcdef"
UA = "DRF Research research-desk@example.com"
QUESTION = "Will global data-centre capacity exceed 250 GW by the end of 2027?"


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


# =============================================================== fakes

def _today() -> dt.date:
    return dt.date.fromisoformat(lr._utc_date())


VINTAGE = (_today() - dt.timedelta(days=1)).isoformat()
FILED = (_today() - dt.timedelta(days=40)).isoformat()


def fred_result(series_id: str = "CPIAUCSL", *, vintage: str = VINTAGE, value: str = "323.5") -> dtools.DataResult:
    """An ok FRED answer as data_tools renders one (a page whose numbers the verifier reads)."""
    url = dtools.alfred_url(series_id, dt.date.fromisoformat(vintage))
    title = f"Consumer Price Index ({series_id}), FRED/ALFRED vintage {vintage}"
    page = (f"FRED/ALFRED: Consumer Price Index ({series_id}) — Index 1982-1984=100, Monthly SA; values as published "
            f"on {vintage}\nLatest: {value} (2026-08-01)\nYear-on-year: 2.95% (derived by DRF from the pinned levels)"
            f"\n2026-07-01: 322.1\n2026-08-01: {value}")
    return dtools.DataResult(
        status="ok", key=f"fred:{series_id}@{vintage}", url=url, title=title, model_text=page, page_text=page,
        supports=(f"Consumer Price Index ({series_id}), FRED/ALFRED values as published on {vintage}: {value} in "
                  "August 2026.",
                  f"Consumer Price Index ({series_id}), FRED/ALFRED values as published on {vintage}: year-on-year "
                  "change 2.95% in August 2026 (derived by DRF from the pinned levels)."),
        date=vintage,
        provenance={"vendor": "fred", "series_id": series_id, "vintage": vintage, "observation_start": "2016-08-01",
                    "observation_end": vintage, "units": "Index 1982-1984=100", "frequency": "Monthly",
                    "fetched_at": "2026-09-30T17:00:00Z"},
        facts=({"series_id": series_id, "source": "FRED/ALFRED", "vintage": vintage, "url": url,
                "metric": "Consumer Price Index", "value": value, "unit": "Index 1982-1984=100", "text": value,
                "observation_date": "2026-08-01", "value_type": "actual", "provenance_kind": "structured"},
               {"series_id": series_id, "source": "FRED/ALFRED", "vintage": vintage, "url": url,
                "metric": "Consumer Price Index, year-on-year change", "value": "2.95", "unit": "percent",
                "text": "2.95%", "observation_date": "2026-08-01", "base_date": "2025-08-01",
                "value_type": "actual", "provenance_kind": "derived",
                "basis": "derived by DRF from the pinned levels; may differ from the publisher's headline basis"}))


def edgar_result(*, filed: str = FILED) -> dtools.DataResult:
    url = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193&type=10-K&dateb="
           + filed.replace("-", ""))
    who = "AAPL (CIK 0000320193, Apple Inc.)"
    sentence = (f"{who}: Revenue (us-gaap:Revenues), FY ending 2025-09-27, 10-K filed {filed} (accession "
                "0000320193-25-000079): 416,161 million USD (416.2 billion USD).")
    return dtools.DataResult(
        status="ok", key=f"edgar:0000320193:annual@{filed}", url=url,
        title=f"{who} annual statements as filed on or before {filed}, SEC EDGAR", model_text=sentence,
        page_text=sentence, supports=(sentence,), date=filed,
        provenance={"vendor": "sec_edgar", "company": "AAPL", "identity_basis": "sec_current_ticker_map",
                    "freq": "annual", "as_of": filed, "cik": "0000320193", "entity_name": "Apple Inc.",
                    "taxonomy": "us-gaap", "fetched_at": "2026-09-30T17:00:00Z", "filed": filed},
        facts=({"source": "SEC EDGAR", "cik": "0000320193", "company": who, "metric": "Revenue",
                "value": "416161000000", "unit": "USD", "text": "416,161 million USD (416.2 billion USD)",
                "observation_date": "2025-09-27", "period_start": "2024-09-29", "period": "fiscal year",
                "tag": "us-gaap:Revenues", "form": "10-K", "filed": filed, "accn": "0000320193-25-000079",
                "url": url, "value_type": "actual", "provenance_kind": "structured"},))


def failed_result(status: str = "unavailable") -> dtools.DataResult:
    return dtools.DataResult(status=status, key="", url="", title="", model_text="FRED: down", page_text="",
                             supports=(), date=None, provenance={}, facts=(), detail="down")


class DataFn:
    """Records every call; answers with ``answer`` (a DataResult, an exception, or a callable of the kwargs)."""

    def __init__(self, answer):
        self.calls: list[dict] = []
        self.answer = answer
        self._lock = threading.Lock()

    def __call__(self, **kwargs):
        with self._lock:
            self.calls.append(kwargs)
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer(**kwargs) if callable(self.answer) else self.answer


def data_fns(**overrides):
    fns = {"macro_series": DataFn(lambda series: fred_result({"cpi": "CPIAUCSL"}.get(series.lower(),
                                                                                     series.upper()))),
           "company_filings": DataFn(lambda company, freq: edgar_result())}
    fns.update(overrides)
    return fns


def make_engine(tmp_path, env, *, fns=None, depth="standard", factory=None, name="out"):
    """A real engine on a fake model and fake web/data tools (``env`` is its run env)."""
    def gateway_factory(args, reporter, bridge_arg, preset):
        return rg.ModelGateway(v3.ScriptedModel(lambda call: v3.ai("OK", out=1)), reporter, sleep=lambda s: None)

    def tools_factory(ledger, pages_dir, bridge_arg, reporter, limits):
        return rg.ResearchTools(ledger, pages_dir, search_fn=v3.fake_search, fetch_fn=v3.page_text,
                                bridge=bridge_arg, plog=reporter, limits=limits, data_fns=fns)

    plog = v3.FakePlog()
    engine = lr._Engine(QUESTION, tmp_path / name, v3.make_args(depth), {"status": "running"}, lr._Reporter(plog),
                        lambda: None, v3.dr, gateway_factory, factory or tools_factory, env)
    return engine, plog


ALL_ON = {"RESEARCH_DATA_TOOLS": "all", "FRED_API_KEY": KEY, "SEC_EDGAR_USER_AGENT": UA}

# The KIQ task template before TIME-13 (the off path must render exactly this).
_PRE_TIME13_KIQ_TASK = string.Template("""KIQ INVESTIGATION TASK
Investigate $kiq_id: $question
Why it matters: $why
Emphasis: $emphasis
Starting points (search results already registered for you; fetch the most authoritative ones directly by URL):
$seeds
Budget for this investigation: at most $max_searches web_search calls, $max_fetches web_fetch calls and $max_steps tool rounds. Use fewer when the evidence is already sufficient.
Tools: web_search(query) returns results tagged [S<n>] with their URLs; web_fetch(url, focus) returns the passages of one page that are relevant to focus, tagged with the page's [S<n>]; web_fetch also accepts a marker such as S12 in place of the URL.
When you are done, reply WITHOUT calling tools, with your notes in exactly this format (keep the four headings in English exactly as written; write the bullet text in $language):
## Findings
- <fact: number + unit + as-of date + context> [S<n>] (VERIFIED|REPORTED)
## Conflicts
- <sources that disagree, with their markers, and why they may differ>
## Open questions
- <what remains unknown and why it matters>
## Discovered
- <a new sub-question outside this KIQ that matters for the forecast>
Aim for 6 to 15 findings. Each finding must be specific and self-contained: a reader who sees only that bullet must understand it.""")


def _kiq(kind: str, kid: str = "K1") -> lr.Kiq:
    return lr.Kiq(id=kid, question="What is installed capacity today?", queries=["capacity"], kind=kind)


# =============================================================== binding (flag off / on)

def test_flag_off_binds_nothing_and_renders_the_pre_time13_kiq_task(tmp_path):
    engine, plog = make_engine(tmp_path, {})
    assert engine.agent_tools is rg.AGENT_TOOLS_SCHEMA is lr.AGENT_TOOLS
    assert engine.data_tool_names == () and not engine.data_tools_requested
    assert (engine.limits.max_data_total, engine.limits.max_data_per_agent) == (0, 0)
    assert "data_tools" not in engine.state.snapshot()["identity"]
    assert not hasattr(engine.tools, "data_context") and "data" not in vars(engine.tools)
    assert "data" not in engine.tools.stats()
    row = {"sid": 3, "title": "Capacity report", "domain": "agency.org", "tier": "S1",
           "url": "https://agency.org/r", "snippet": "176 GW installed"}
    for kind in ("data", "general", "actor"):
        task = engine._kiq_task(_kiq(kind), [row])
        expected = _PRE_TIME13_KIQ_TASK.substitute(
            kiq_id="K1", question="What is installed capacity today?", why="Background evidence for the report.",
            emphasis=lr._KIND_EMPHASIS[kind], seeds=rg.delimit_untrusted(lr.LABEL_SEEDS, "\n".join([
                "[S3] Capacity report — agency.org (tier 1)", "    https://agency.org/r", "    176 GW installed"])),
            max_searches=4, max_fetches=4, max_steps=7, language="English")
        assert task == expected
    assert "official-data" not in plog.text()


def test_requested_without_credentials_binds_nothing_and_says_why(tmp_path):
    engine, plog = make_engine(tmp_path, {"RESEARCH_DATA_TOOLS": "fred, sec_edgar, bloomberg"}, fns=data_fns())
    assert engine.agent_tools is lr.AGENT_TOOLS and engine.data_tool_names == ()
    assert engine.data_disabled == {"fred": "no_api_key", "sec_edgar": "no_user_agent"}
    assert (engine.limits.max_data_total, engine.limits.max_data_per_agent) == (0, 0)
    assert "data_tools" not in engine.state.snapshot()["identity"]
    text = plog.text()
    assert "macro_series (fred) not bound: no_api_key" in text and "company_filings (sec_edgar) not bound" in text
    assert "names no known vendor in bloomberg" in text
    # A user agent without a contact address is not one SEC accepts.
    engine, _ = make_engine(tmp_path, {**ALL_ON, "SEC_EDGAR_USER_AGENT": "DRF desk"}, fns=data_fns(), name="o2")
    assert engine.data_tool_names == ("macro_series",) and engine.data_disabled == {"sec_edgar": "no_user_agent"}


def test_flag_on_binds_one_tools_list_with_budgets_and_identity(tmp_path):
    engine, plog = make_engine(tmp_path, ALL_ON, fns=data_fns())
    names = [tool["function"]["name"] for tool in engine.agent_tools]
    assert names == ["web_search", "web_fetch", "macro_series", "company_filings"]
    assert engine.agent_tools is not rg.AGENT_TOOLS_SCHEMA and len(rg.AGENT_TOOLS_SCHEMA) == 2
    assert engine.data_tool_names == ("macro_series", "company_filings") and engine.data_disabled == {}
    assert (engine.limits.max_data_total, engine.limits.max_data_per_agent) == (30, 3)
    assert engine.state.snapshot()["identity"]["data_tools"] == ["fred", "sec_edgar"]
    assert engine.tools.data_context == engine._data_context
    assert "official-data tools bound: macro_series, company_filings (at most 3 calls per KIQ, 30 per run)" in (
        plog.text())
    # Only a data KIQ's task carries the guidance, right after the web tools' description.
    data_task = engine._kiq_task(_kiq("data"), [])
    guidance = lr.kiq_data_guidance(engine.data_tool_names, 3)
    assert guidance.startswith(" Official data: macro_series(series) returns an official FRED series")
    assert "company_filings(company, freq)" in guidance and "At most 3 calls." in guidance
    assert f"in place of the URL.{guidance}\nWhen you are done" in data_task
    for kind in ("general", "actor"):
        assert "Official data" not in engine._kiq_task(_kiq(kind), [])
    assert lr.ENGINE_CORE.count("macro_series") == 0


def test_a_missing_fred_key_binds_only_company_filings(tmp_path):
    env = {"RESEARCH_DATA_TOOLS": "all", "SEC_EDGAR_USER_AGENT": UA}
    engine, _ = make_engine(tmp_path, env, fns=data_fns())
    assert [tool["function"]["name"] for tool in engine.agent_tools] == ["web_search", "web_fetch", "company_filings"]
    assert engine.data_disabled == {"fred": "no_api_key"}
    assert engine.state.snapshot()["identity"]["data_tools"] == ["sec_edgar"]
    task = engine._kiq_task(_kiq("data"), [])
    assert "company_filings(company, freq)" in task and "macro_series" not in task


@pytest.mark.parametrize("why, env, factory_fns", [
    ("tools_unavailable", ALL_ON, None),
    ("no_call_budget", {**ALL_ON, "RESEARCH_LINEAR_DATA_CALLS_PER_KIQ": "0"}, "fns"),
])
def test_unusable_data_tools_are_not_bound(tmp_path, why, env, factory_fns):
    engine, plog = make_engine(tmp_path, env, fns=data_fns() if factory_fns else None)
    assert engine.agent_tools is lr.AGENT_TOOLS and engine.data_tool_names == ()
    assert engine.data_disabled == {"fred": why, "sec_edgar": why}
    assert "Official data" not in engine._kiq_task(_kiq("data"), [])
