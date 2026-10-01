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
import json
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


# =============================================================== dispatch and governance

def _scripted(*replies):
    """A model answering its i-th call with ``replies[i]`` (the last one repeats)."""
    state = {"n": 0}

    def responder(call):
        reply = replies[min(state["n"], len(replies) - 1)]
        state["n"] += 1
        return reply

    return v3.ScriptedModel(responder)


def _call(name, cid, **args):
    return {"name": name, "args": args, "id": cid}


NOTES = v3.ai("## Findings\n- Capacity was 176 GW in 2023 [S1] (REPORTED)\n## Conflicts\n## Open questions\n"
              "## Discovered")


def _agent_engine(tmp_path, model, fns, *, limits=None, data_tools=("macro_series", "company_filings")):
    """A minimal engine for KiqAgent: real tools and gateway; ``data_tools`` () is an engine without them."""
    ledger = rg.SourceLedger(tmp_path / "ledger.json")
    tools = rg.ResearchTools(ledger, tmp_path / "pages", search_fn=v3.fake_search, fetch_fn=v3.page_text,
                             limits=limits or rg.ToolLimits(max_data_total=10, max_data_per_agent=5), data_fns=fns)
    engine = types.SimpleNamespace(
        gateway=rg.ModelGateway(model, None, sleep=lambda s: None), tools=tools, ledger=ledger,
        brief="RUN BRIEF\nquestion", language="English", preset=types.SimpleNamespace(agent_max_steps=4, workers=1),
        log=lambda kind, message: None, units=float)
    if data_tools:
        engine.agent_tools = rg.data_tool_schema_list(["fred", "sec_edgar"])
        engine.data_tool_names = tuple(data_tools)
    return engine


def _tool_texts(call):
    return [content for kind, content in call["messages"] if kind == "tool"]


def test_data_calls_share_the_step_cap_and_are_fetch_shaped(tmp_path):
    fns = data_fns()
    model = _scripted(v3.ai(tool_calls=[_call("macro_series", "c1", series="cpi"),
                                        _call("macro_series", "c2", series="gdp"),
                                        _call("company_filings", "c3", company="AAPL"),
                                        _call("web_search", "c4", query="capacity 2023")]), NOTES)
    engine = _agent_engine(tmp_path, model, fns)
    outcome = lr.KiqAgent(engine, _kiq("data"), "Investigate K1: task", [], rg.Deadline(600)).run()
    texts = _tool_texts(model.calls[1])
    assert [text.split("\n", 1)[0].endswith("official data") for text in texts[:3]] == [True, True, True]
    assert texts[3] == lr.TOOL_CALLS_SKIPPED_TEXT
    assert [call["series"] for call in fns["macro_series"].calls] == ["cpi", "gdp"]
    assert engine.tools.stats()["searches"] == 0
    # Every call carries the engine's one tools list; the data rows count as read.
    assert all(call["tools"] is engine.agent_tools for call in model.calls)
    assert outcome.fetched == [1, 2, 3] and outcome.fallback is None
    assert lr.tool_output_sids("company_filings", texts[2]) == (3, [3])


def test_a_repeated_data_request_in_one_step_is_a_duplicate(tmp_path):
    fns = data_fns()
    model = _scripted(v3.ai(tool_calls=[_call("macro_series", "c1", series="cpi"),
                                        _call("macro_series", "c2", series=" CPI ")]),
                      v3.ai(tool_calls=[_call("company_filings", "c3", company="aapl", freq="annual"),
                                        _call("company_filings", "c4", company="AAPL")]), NOTES)
    engine = _agent_engine(tmp_path, model, fns)
    lr.KiqAgent(engine, _kiq("data"), "Investigate K1: task", [], rg.Deadline(600)).run()
    texts = _tool_texts(model.calls[2])
    assert texts[1] == texts[3] == lr.DUPLICATE_CALL_TEXT
    assert texts[0].startswith("[S1] ") and texts[2].startswith("[S2] ")
    assert len(fns["macro_series"].calls) == len(fns["company_filings"].calls) == 1


def test_the_per_kiq_data_allowance_is_enforced(tmp_path):
    fns = data_fns()
    model = _scripted(v3.ai(tool_calls=[_call("macro_series", "c1", series="cpi")]),
                      v3.ai(tool_calls=[_call("macro_series", "c2", series="gdp")]), NOTES)
    engine = _agent_engine(tmp_path, model, fns, limits=rg.ToolLimits(max_data_total=10, max_data_per_agent=1))
    lr.KiqAgent(engine, _kiq("data"), "Investigate K1: task", [], rg.Deadline(600)).run()
    assert _tool_texts(model.calls[2])[-1] == rg.MSG_DATA_BUDGET
    assert len(fns["macro_series"].calls) == 1
    assert engine.tools.stats()["data"]["per_agent"]["K1"]["data_calls"] == 1


def test_unknown_and_invalid_calls_name_the_bound_tools_and_are_counted(tmp_path):
    engine = _agent_engine(tmp_path, _scripted(NOTES), data_fns())
    agent = lr.KiqAgent(engine, _kiq("data"), "Investigate K1: task", [], rg.Deadline(600))
    assert agent._call_tool(_call("bloomberg", "c1", ticker="X")) == (
        "UNKNOWN_TOOL: only web_search, web_fetch, macro_series and company_filings are available.")
    assert agent._call_tool(_call("macro_series", "c2")).startswith("INVALID_TOOL_CALL: macro_series needs")
    assert agent.call_counts() == {"invalid_tool_calls": 1, "unknown_tool_calls": 1, "tool_exceptions": 0}
    assert lr.unknown_tool_text(("company_filings",)) == (
        "UNKNOWN_TOOL: only web_search, web_fetch and company_filings are available.")


def test_without_data_tools_a_data_call_is_unknown_and_takes_no_step_slot(tmp_path):
    fns = data_fns()
    model = _scripted(v3.ai(tool_calls=[_call("macro_series", "c1", series="cpi"),
                                        _call("web_search", "c2", query="a b"), _call("web_search", "c3", query="c d"),
                                        _call("web_search", "c4", query="e f")]), NOTES)
    engine = _agent_engine(tmp_path, model, fns, data_tools=())
    lr.KiqAgent(engine, _kiq("data"), "Investigate K1: task", [], rg.Deadline(600)).run()
    texts = _tool_texts(model.calls[1])
    assert texts[0] == "UNKNOWN_TOOL: only web_search and web_fetch are available."
    assert lr.TOOL_CALLS_SKIPPED_TEXT not in texts and fns["macro_series"].calls == []
    assert all(call["tools"] is lr.AGENT_TOOLS for call in model.calls)


@pytest.mark.parametrize("taxonomy", [False, True])
def test_data_failures_never_count_as_fetch_failures(tmp_path, taxonomy):
    env = {**ALL_ON, **({"RESEARCH_SOURCE_TAXONOMY": "true"} if taxonomy else {})}
    fns = data_fns(macro_series=DataFn(failed_result()), company_filings=DataFn(RuntimeError("boom")))
    engine, _ = make_engine(tmp_path, env, fns=fns)
    before = engine._tool_failures()
    assert engine.tools.data("macro_series", {"series": "cpi"}, agent_id="K1") == rg.MSG_DATA_UNAVAILABLE
    assert engine.tools.data("company_filings", {"company": "AAPL"}, agent_id="K1") == rg.MSG_DATA_UNAVAILABLE
    assert engine._tool_failures() == before and before["fetch_failed"] == 0
    assert engine.tools.stats()["data"]["data_failures"] == 2


def test_a_stopped_run_answers_data_calls_cancelled(tmp_path):
    fns = data_fns()
    engine, _ = make_engine(tmp_path, ALL_ON, fns=fns)
    engine.cancel()
    assert engine.tools.data("macro_series", {"series": "cpi"}, agent_id="K1") == lr.CANCELLED_TOOL_TEXT
    assert fns["macro_series"].calls == []


# =============================================================== the run's vintage pin

def _plan(as_of: str) -> lr.Plan:
    return lr.build_plan(QUESTION, "English", as_of, lr.resolve_preset("standard", {}), 20, {}, None)


def test_the_vintage_is_pinned_once_and_survives_a_resume(tmp_path, monkeypatch):
    engine, _ = make_engine(tmp_path, ALL_ON, fns=data_fns())
    assert engine._data_context() is None  # no plan yet: a data call answers unavailable
    today = _today()
    engine.plan = _plan(today.isoformat())
    context = engine._data_context()
    pit = dtools.fred_pit(today)
    assert context == {"as_of": today, "pit": pit, "language": "English"}
    pins = json.loads((engine.work / lr.DATA_PINS_FILENAME).read_text(encoding="utf-8"))
    assert pins == {"as_of": today.isoformat(), "cutoff": today.isoformat(), "same_day": None,
                    "pit": pit.isoformat()}
    # A resumed attempt (same identity, same work dir) keeps the first attempt's vintage,
    # whatever FRED's today is by then.
    monkeypatch.setattr(dtools, "fred_pit", lambda *a, **k: pytest.fail("pinned again on resume"))
    resumed, _ = make_engine(tmp_path, ALL_ON, fns=data_fns())
    assert resumed.resumed
    resumed.plan = _plan(today.isoformat())
    assert resumed._data_context() == context
    assert json.loads((resumed.work / lr.DATA_PINS_FILENAME).read_text(encoding="utf-8")) == pins


def test_a_pin_of_another_as_of_is_replaced(tmp_path):
    engine, plog = make_engine(tmp_path, ALL_ON, fns=data_fns())
    (engine.work / lr.DATA_PINS_FILENAME).write_text(json.dumps(
        {"as_of": "2020-01-01", "cutoff": "2020-01-01", "same_day": None, "pit": "2020-01-01"}), encoding="utf-8")
    engine.plan = _plan("2024-06-03")
    assert engine._data_context()["pit"] == dt.date(2024, 6, 3)
    assert "holds another as-of" in plog.text()


class FredTransport:
    """FRED's two endpoints, recorded: series metadata and 24 monthly observations ending before the window end."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, url, params, timeout, headers):
        self.calls.append({"url": url, "params": dict(params)})
        if url.endswith("/series"):
            return 200, {"seriess": [{"id": "CPIAUCSL", "title": "Consumer Price Index", "frequency": "Monthly",
                                      "units": "Index 1982-1984=100", "seasonal_adjustment_short": "SA"}]}, ""
        end = dt.date.fromisoformat(params["observation_end"])
        year, month, rows = end.year - 2, end.month, []
        for index in range(24):
            rows.append({"date": dt.date(year, month, 1).isoformat(), "value": f"{300 + index}.5"})
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return 200, {"observations": rows}, ""


def _gated_env(monkeypatch, as_of="2024-06-03", same_day="exclude"):
    for name, value in {**ALL_ON, "RESEARCH_AS_OF": as_of, "RESEARCH_PIT_GATES": "true",
                        "RESEARCH_PIT_SAME_DAY": same_day, "RESEARCH_PIT_UNDATED": "drop"}.items():
        monkeypatch.setenv(name, value)
    return dict(os.environ)


@pytest.mark.parametrize("same_day, cutoff", [("exclude", "2024-06-02"), ("include", "2024-06-03")])
def test_a_gated_hindcast_pins_every_data_call_before_the_as_of(tmp_path, monkeypatch, same_day, cutoff):
    """The production factory's FRED function in a gated hindcast: excluding same-day sources,
    the request's realtime bounds and window end are the day before the as-of, and the data row
    is dated (and admitted) strictly before it."""
    env = _gated_env(monkeypatch, same_day=same_day)
    transport = FredTransport()
    monkeypatch.setattr(dtools, "_httpx_transport", transport)
    engine, _ = make_engine(tmp_path, env, factory=lr._default_tools_factory)
    assert engine.pit is not None and engine.pit.same_day == same_day
    engine.plan = _plan("2024-06-03")
    text = engine.tools.data("macro_series", {"series": "cpi"}, agent_id="K1")
    assert text.startswith("[S1] ") and "official data" in text.split("\n", 1)[0]
    assert {(call["params"]["realtime_start"], call["params"]["realtime_end"]) for call in transport.calls} == {
        (cutoff, cutoff)}
    assert transport.calls[1]["params"]["observation_end"] == cutoff
    row = engine.ledger.get(1)
    assert (row["published"], row["data"]["date"], row["pit_status"]) == (
        cutoff, cutoff, "admitted" if same_day == "exclude" else "same_day")
    assert json.loads((engine.work / lr.DATA_PINS_FILENAME).read_text(encoding="utf-8")) == {
        "as_of": "2024-06-03", "cutoff": cutoff, "same_day": same_day, "pit": cutoff}


# =============================================================== whole runs

class CountingModel(v3.ScriptedModel):
    """A ScriptedModel recording every tools object it is bound with."""

    def __init__(self, responder):
        super().__init__(responder)
        self._state["binds"] = []

    @property
    def binds(self) -> list:
        return self._state["binds"]

    def bind_tools(self, tools):
        with self._state["lock"]:
            self._state["binds"].append(tools)
        return super().bind_tools(tools)


_DATA_HOSTS = r"(alfred\.stlouisfed\.org|(?:www\.)?sec\.gov)"


class DataWorld(v3.World):
    """K1 (the plan's data KIQ) calls both data tools, then writes a finding copying the CPI value,
    one altering it and one copying Apple's revenue; the writers also cite the data sources in
    their SOURCE INDEX; the fact extraction adds two model rows citing the CPI source, one with a
    number its page does not state."""

    def __init__(self, out_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self.out_dir = out_dir

    def agent(self, call):
        messages = call["messages"]
        kid = re.search(r"Investigate (\S+):", messages[2][1]).group(1)
        if kid != "K1":
            return super().agent(call)
        results = [content for kind, content in messages if kind == "tool"]
        if not results and not messages[-1][1].startswith("STOP"):
            return v3.ai(tool_calls=[{"name": "macro_series", "args": {"series": "cpi"}, "id": "K1-d1"},
                                     {"name": "company_filings", "args": {"company": "AAPL"}, "id": "K1-d2"}])
        sids = {}
        for text in results:
            match = re.match(rf"\[S(\d+)\] .* — {_DATA_HOSTS} \(tier 1\).* — official data$", text.split("\n", 1)[0])
            if match:
                sids["fred" if "alfred" in match.group(2) else "sec"] = int(match.group(1))
        cpi, sec = sids["fred"], sids["sec"]
        return v3.ai("\n".join([
            "## Findings",
            f"- The US Consumer Price Index (CPIAUCSL) stood at 323.5 [S{cpi}] (VERIFIED)",
            f"- The US Consumer Price Index (CPIAUCSL) stood at 329.7 [S{cpi}] (VERIFIED)",
            f"- Apple Inc. reported revenue of 416,161 million USD [S{sec}] (VERIFIED)",
            "## Conflicts", "## Open questions", "- Whether prices keep rising", "## Discovered"]))

    def writer(self, call):
        reply = super().writer(call)
        index = call["messages"][2][1].split("SOURCE INDEX", 1)[-1]
        sids = re.findall(rf"^\[S(\d+)\] .* — {_DATA_HOSTS} \(", index, re.M)
        if not sids:
            return reply
        extra = ("\n\nOfficial statistics put the consumer price index at 323.5 and Apple Inc. revenue at 416,161 "
                 "million USD " + "".join(f"[S{sid}]" for sid, _host in sids) + ".")
        return v3.ai(re.sub(r"(\n\n## |\Z)", lambda m: extra + m.group(1), reply.content, count=1), out=1500)

    def facts(self, call):
        reply = json.loads(super().facts(call).content)
        sources = json.loads((self.out_dir / "sources.json").read_text(encoding="utf-8"))
        cpi = next(position for position, row in enumerate(sources, 1) if "alfred" in row["url"])
        reply["quantitative_facts"] += [
            {"metric": "Consumer price index", "value": "329.7", "unit": "index", "value_type": "actual",
             "source_ref": f"S{cpi}"},
            {"metric": "Consumer price index", "value": "323.5", "unit": "index", "value_type": "actual",
             "source_ref": f"S{cpi}"}]
        return v3.ai(json.dumps(reply))


def run_engine(tmp_path, bridge, monkeypatch, world_factory, *, name="out", search_fn=v3.fake_search):
    """One v3 run on offline search/fetch, with tools built as _default_tools_factory builds them:
    the real data functions (official_data_fns) reading the engine's context."""
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")
    out = tmp_path / name
    out.mkdir(parents=True, exist_ok=True)
    model = CountingModel(world_factory(out))
    plog = v3.FakePlog()
    meta = {"status": "running", "question": QUESTION, "research_engine": "v3"}

    def write_meta():
        (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    def gateway_factory(args, plog_arg, bridge_arg, preset):
        return rg.ModelGateway(model, plog_arg, max_concurrency=preset.workers, budget_units=preset.budget_units,
                               reserve_share=lr.RESERVE_SHARE, sleep=lambda seconds: None)

    def tools_factory(ledger, pages_dir, bridge_arg, plog_arg, limits):
        holder = {}
        enabled = lr.data_tools_availability(os.environ)[0]
        fns = (lr.official_data_fns(os.environ, enabled, lambda: holder["tools"].data_context())
               if enabled else None)
        pit = lr._pit_policy(os.environ)
        holder["tools"] = rg.ResearchTools(
            ledger, pages_dir, search_fn=search_fn, fetch_fn=v3.page_text, bridge=bridge_arg, plog=plog_arg,
            limits=limits, source_dates=pit is not None, vintage_as_of=lr._hindcast_as_of(os.environ), pit=pit,
            data_fns=fns)
        return holder["tools"]

    rc = lr.run(QUESTION, out, v3.make_args(), meta, plog, write_meta, bridge=bridge,
                gateway_factory=gateway_factory, tools_factory=tools_factory)
    return rc, meta, plog, model, out


@pytest.fixture
def vendors(monkeypatch):
    """data_tools' two lookups, recorded: FRED answers at the pinned vintage, SEC EDGAR a filing 30 days before as_of."""
    calls: dict[str, list] = {"fred": [], "edgar": []}

    def fred_series(series, *, as_of, pit, key, language="English", **kwargs):
        calls["fred"].append({"series": series, "as_of": as_of, "pit": pit, "key": key, "language": language})
        return fred_result({"cpi": "CPIAUCSL"}.get(series, series.upper()), vintage=pit.isoformat())

    def edgar_statements(company, *, as_of, freq, user_agent, language="English", **kwargs):
        calls["edgar"].append({"company": company, "as_of": as_of, "freq": freq, "user_agent": user_agent,
                               "language": language})
        return edgar_result(filed=(as_of - dt.timedelta(days=30)).isoformat())

    monkeypatch.setattr(dtools, "fred_series", fred_series)
    monkeypatch.setattr(dtools, "edgar_statements", edgar_statements)
    return calls


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _agent_tasks(model) -> dict[str, str]:
    return {re.search(r"Investigate (\S+):", call["messages"][2][1]).group(1): call["messages"][2][1]
            for call in model.calls if v3.role_of(call) == "agent"}


def test_flag_off_run_artifacts_do_not_depend_on_an_unbound_request(tmp_path, bridge, monkeypatch):
    """RESEARCH_DATA_TOOLS unset: one AGENT_TOOLS binding, no data counters or meta.data_tools.  A
    request no credential can serve binds nothing either: sources.json, quantitative.json,
    meta['tools'] and the KIQ tasks are byte-identical to the unset run."""
    rc_off, meta_off, _, model_off, out_off = run_engine(tmp_path, bridge, monkeypatch, lambda out: v3.World(),
                                                         name="off")
    monkeypatch.setenv("RESEARCH_DATA_TOOLS", "all")
    rc_req, meta_req, plog_req, model_req, out_req = run_engine(tmp_path, bridge, monkeypatch,
                                                                lambda out: v3.World(), name="requested")
    assert rc_off == rc_req == 0
    for name in ("sources.json", "quantitative.json"):
        assert (out_off / name).read_bytes() == (out_req / name).read_bytes(), name
    assert meta_off["tools"] == meta_req["tools"] and "data" not in meta_off["tools"]
    assert "data_tools" not in meta_off
    assert meta_req["data_tools"] == {"enabled": [], "disabled": {"fred": "no_api_key", "sec_edgar": "no_user_agent"},
                                      "pit": None, "calls": 0, "cached": 0, "invalid": 0, "failures": 0,
                                      "quant_rows_added": 0, "quant_rows_rejected": []}
    for model in (model_off, model_req):
        assert model.binds and all(tools is rg.AGENT_TOOLS_SCHEMA for tools in model.binds)
        assert all(call["tools"] is rg.AGENT_TOOLS_SCHEMA for call in model.calls if v3.role_of(call) == "agent")
    assert _agent_tasks(model_off) == _agent_tasks(model_req)
    assert not any("Official data" in task for task in _agent_tasks(model_off).values())
    assert not (out_off / lr.WORK_DIRNAME / lr.DATA_PINS_FILENAME).exists()
    assert "data_tools" not in _read(out_req / lr.WORK_DIRNAME / lr.STATE_FILENAME)["identity"]
    assert "official-data tool macro_series (fred) not bound: no_api_key" in plog_req.text()


def test_flag_on_run_cites_verifies_and_publishes_the_data(tmp_path, bridge, monkeypatch, vendors):
    for name, value in ALL_ON.items():
        monkeypatch.setenv(name, value)
    rc, meta, plog, model, out = run_engine(tmp_path, bridge, monkeypatch, DataWorld)
    assert rc == 0, plog.text()
    as_of = dt.date.fromisoformat(meta["as_of_date"])
    pit = dtools.fred_pit(as_of)
    # One tools list, bound once, on every agent call; only the data KIQ's task names the tools.
    assert len(model.binds) == 1
    assert [tool["function"]["name"] for tool in model.binds[0]] == [
        "web_search", "web_fetch", "macro_series", "company_filings"]
    assert all(call["tools"] is model.binds[0] for call in model.calls if v3.role_of(call) == "agent")
    tasks = _agent_tasks(model)
    assert "Official data: macro_series(series)" in tasks["K1"]
    assert not any("Official data" in task for kid, task in tasks.items() if kid != "K1")
    assert _read(out / lr.WORK_DIRNAME / lr.STATE_FILENAME)["identity"]["data_tools"] == ["fred", "sec_edgar"]
    # The data calls are pinned to the plan's as-of, the run's vintage and its language.
    assert vendors["fred"] == [{"series": "cpi", "as_of": as_of, "pit": pit, "key": KEY, "language": "English"}]
    assert vendors["edgar"] == [{"company": "AAPL", "as_of": as_of, "freq": "annual", "user_agent": UA,
                                 "language": "English"}]
    assert _read(out / lr.WORK_DIRNAME / lr.DATA_PINS_FILENAME) == {
        "as_of": as_of.isoformat(), "cutoff": as_of.isoformat(), "same_day": None, "pit": pit.isoformat()}
    # A copied value stays VERIFIED; an altered one is not on the vendor's page.
    facts = {fact["text"]: fact["tag"] for fact in _read(out / lr.WORK_DIRNAME / "kiq" / "K1.json")["facts"]}
    assert [tag for text, tag in facts.items() if "323.5" in text] == ["VERIFIED"]
    assert [tag for text, tag in facts.items() if "329.7" in text] == ["UNVERIFIED"]
    assert [tag for text, tag in facts.items() if "416,161" in text] == ["VERIFIED"]
    # sources.json: S1, dated on or before the as-of, the vendor sentences first, a data block.
    sources = _read(out / "sources.json")
    data_rows = [(position, row) for position, row in enumerate(sources, 1) if "data" in row]
    assert [row["data"]["vendor"] for _, row in data_rows] == ["fred", "sec_edgar"]
    for _position, row in data_rows:
        assert (row["tier"], row["source_origin"]) == ("S1", "fetched")
        assert dt.date.fromisoformat(row["date"]) <= as_of and row["supports"]
        assert row["data"]["url"] == row["url"]
    fred_row, sec_row = data_rows[0][1], data_rows[1][1]
    assert fred_row["supports"] == list(fred_result(vintage=pit.isoformat()).supports)
    assert fred_row["data"] == {"vendor": "fred", "series_id": "CPIAUCSL", "vintage": pit.isoformat(),
                                "url": fred_row["url"]}
    assert sec_row["data"] == {"vendor": "sec_edgar", "cik": "0000320193", "filed": sec_row["date"],
                               "url": sec_row["url"]}
    # quantitative.json opens with the deterministic rows (citation order), verified like model rows.
    quant = _read(out / "quantitative.json")
    head = quant[:3]
    assert [lr.is_data_quant_row(row) for row in quant] == [True] * 3 + [False] * (len(quant) - 3)
    assert [(row["metric"], row["value"], row["source_ref"]) for row in head] == [
        ("Consumer Price Index", "323.5", f"S{data_rows[0][0]}"),
        ("Consumer Price Index, year-on-year change", "2.95", f"S{data_rows[0][0]}"),
        ("AAPL (CIK 0000320193, Apple Inc.): Revenue", "416161000000", f"S{data_rows[1][0]}")]
    assert all(row["tier"] == "S1" and row["value_type"] == "actual" and row["verification"] == "verified"
               for row in head)
    assert [row["provenance"]["kind"] for row in head] == ["structured", "derived", "structured"]
    assert head[0]["provenance"] == {"kind": "structured", "vendor": "fred", "series_id": "CPIAUCSL",
                                     "vintage": pit.isoformat(), "observation_date": "2026-08-01"}
    assert (head[0]["as_of_date"], head[0]["period_end"]) == (pit.isoformat(), "2026-08-01")
    # The model row contradicting the CPI page is dropped and listed; the one copying it stays.
    model_cpi = [row["value"] for row in quant[3:] if row["metric"] == "Consumer price index"]
    assert model_cpi == ["323.5"]
    assert meta["data_tools"] == {
        "enabled": ["fred", "sec_edgar"], "disabled": {}, "pit": pit.isoformat(), "calls": 2, "cached": 0,
        "invalid": 0, "failures": 0, "quant_rows_added": 3,
        "quant_rows_rejected": [{"metric": "Consumer price index", "value": "329.7", "unit": "index",
                                 "source_ref": f"S{data_rows[0][0]}", "source_url": fred_row["url"]}]}
    assert meta["tools"]["data"]["data_calls"] == 2
    assert not any("official-data" in event for event in meta.get("degradation_events") or [])
    # TIME-1: the graph anchor stays the plan's as-of whatever the data rows' dates.
    from app.services.pipeline_orchestrator import PipelineOrchestrator

    anchor, note = PipelineOrchestrator._validate_as_of_date(_read(out / "actors.json"), sources)
    assert (anchor.date(), note) == (as_of, None)


def test_quant_rows_cap_and_the_off_switch_of_the_contradiction_check(tmp_path, bridge, monkeypatch, vendors):
    """DATA_QUANT_ROWS_MAX caps the deterministic rows; with RESEARCH_VERIFIED_FACTS off the
    contradicted model row is still dropped (the same page check), and no row is stamped."""
    for name, value in {**ALL_ON, "DATA_QUANT_ROWS_MAX": "1", "RESEARCH_VERIFIED_FACTS": "false"}.items():
        monkeypatch.setenv(name, value)
    rc, meta, plog, _, out = run_engine(tmp_path, bridge, monkeypatch, DataWorld)
    assert rc == 0, plog.text()
    quant = _read(out / "quantitative.json")
    assert [lr.is_data_quant_row(row) for row in quant[:2]] == [True, False]
    assert not any("verification" in row for row in quant)
    assert [row["value"] for row in quant if row["metric"] == "Consumer price index"] == ["323.5"]
    assert meta["data_tools"]["quant_rows_added"] == 1
    assert [row["value"] for row in meta["data_tools"]["quant_rows_rejected"]] == ["329.7"]
