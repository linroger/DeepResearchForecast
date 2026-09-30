"""TIME-7: the v3 engine researches as of RESEARCH_AS_OF (a pinned hindcast).

The parent sets RESEARCH_AS_OF only for a pinned hindcast.  The engine then
dates its plan, briefs and actors to that day instead of the wall clock, adds
a point-in-time rule to the briefs, labels every fetched page as served live,
withholds prediction markets and records ``meta.point_in_time``; ENGINE_CORE
and the tools schema stay byte-identical, so the prompt-cache prefix does too.
An invalid or future value fails the run (exit 2).  Without the variable every
prompt is unchanged.  Offline: the scripted model, injected search/fetch and
real bridge of ``test_research_engine_v3``; "today" is patched to 2026-10-01.
"""

from __future__ import annotations

import json
import os
import re
import types
from datetime import date

import pytest

import test_research_engine_v3 as v3
from app.utils.point_in_time import validate_as_of

# The shared fixtures (hermetic env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
rg = v3.rg

AS_OF = "2024-06-01"
TODAY = "2026-10-01"
RULE = lr.point_in_time_rule(AS_OF)
LIVE_PAGE = f"LIVE PAGE: served as it is now, not as of {AS_OF}; ignore anything dated after {AS_OF}."
_FETCH_HEADER = re.compile(r"^\[S(\d+)\] .* — (?:full page|excerpt) ")


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    """The engine's UTC today is fixed after the hindcast date; the knob starts unset."""
    monkeypatch.setattr(lr, "_utc_date", lambda: TODAY)
    monkeypatch.delenv("RESEARCH_AS_OF", raising=False)


def _run(root, bridge, monkeypatch, *, as_of=None):
    """One engine run; ``as_of`` None leaves RESEARCH_AS_OF unset.  The tools are
    built like production (:func:`linear_research._default_tools_factory`): the
    fetched-page label follows the run env."""
    # One worker: KIQs run in plan order, so runs are comparable prompt for prompt.
    monkeypatch.setenv("RESEARCH_LINEAR_WORKERS", "1")
    if as_of is None:
        monkeypatch.delenv("RESEARCH_AS_OF", raising=False)
    else:
        monkeypatch.setenv("RESEARCH_AS_OF", as_of)
    out = root / "out"
    out.mkdir(parents=True, exist_ok=True)
    model = v3.ScriptedModel(v3.World())
    plog = v3.FakePlog()
    meta = {"status": "running", "question": "q", "research_engine": "v3"}

    def write_meta():
        (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    def gateway_factory(args, plog_arg, bridge_arg, preset):
        return rg.ModelGateway(model, plog_arg, max_concurrency=preset.workers, budget_units=preset.budget_units,
                               reserve_share=lr.RESERVE_SHARE, sleep=lambda seconds: None)

    def tools_factory(ledger, pages_dir, bridge_arg, plog_arg, limits):
        return rg.ResearchTools(ledger, pages_dir, search_fn=v3.fake_search, fetch_fn=v3.page_text,
                                bridge=bridge_arg, plog=plog_arg, limits=limits,
                                vintage_as_of=lr._hindcast_as_of(os.environ))

    question = "Will global data-centre capacity exceed 250 GW by the end of 2027?"
    rc = lr.run(question, out, v3.make_args(), meta, plog, write_meta, bridge=bridge,
                gateway_factory=gateway_factory, tools_factory=tools_factory)
    return rc, meta, plog, model, out


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _texts(model):
    return [content for call in model.calls for _kind, content in call["messages"]]


def _briefs(model):
    return [text for text in _texts(model) if text.startswith("RUN BRIEF")]


def _fetch_results(model):
    """Every web_fetch result the agents were shown (tool messages with a page header)."""
    return {content for call in model.calls for kind, content in call["messages"]
            if kind == "tool" and _FETCH_HEADER.match(content)}


def _prompts(model):
    """Every request as JSON text, as a multiset (call order is not the contract)."""
    return sorted(json.dumps(call["messages"], ensure_ascii=False) for call in model.calls)


# =============================================================== hindcast run

def test_hindcast_run_is_dated_to_the_pin_with_no_wall_clock_date(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("RESEARCH_AS_OF_PIN", "true")   # what the parent forwards for a hindcast
    rc, meta, _plog, model, out = _run(tmp_path, bridge, monkeypatch, as_of=AS_OF)
    assert rc == 0, meta.get("error")

    assert _load(out / "v3" / "plan.json")["as_of"] == AS_OF
    assert _load(out / "actors.json")["as_of_date"] == AS_OF
    assert meta["as_of_date"] == AS_OF

    briefs = _briefs(model)
    assert any(b.startswith("RUN BRIEF (planning stage)") for b in briefs)
    assert any(b.startswith("RUN BRIEF\n") for b in briefs)
    for brief in briefs:
        lines = brief.splitlines()
        at = lines.index(f"As-of date (UTC): {AS_OF}")
        assert lines[at + 1] == RULE
    assert (out / "v3" / "brief.md").read_text(encoding="utf-8").splitlines()[4] == RULE
    assert not [text for text in _texts(model) if TODAY in text]


def test_hindcast_keeps_engine_core_and_the_tools_object(tmp_path, bridge, monkeypatch):
    rc, meta, _plog, model, _out = _run(tmp_path, bridge, monkeypatch, as_of=AS_OF)
    assert rc == 0, meta.get("error")

    assert all(call["messages"][0] == ("system", lr.ENGINE_CORE) for call in model.calls)
    assert AS_OF not in lr.ENGINE_CORE and "Point-in-time" not in lr.ENGINE_CORE
    agent = [call for call in model.calls if call["tools"] is not None]
    assert agent and all(call["tools"] is rg.AGENT_TOOLS_SCHEMA for call in agent)
    assert lr.AGENT_TOOLS is rg.AGENT_TOOLS_SCHEMA
    assert AS_OF not in json.dumps(rg.AGENT_TOOLS_SCHEMA)


def test_hindcast_fetched_pages_carry_the_live_page_line(tmp_path, bridge, monkeypatch):
    rc, meta, _plog, model, _out = _run(tmp_path, bridge, monkeypatch, as_of=AS_OF)
    assert rc == 0, meta.get("error")

    pages = _fetch_results(model)
    assert pages
    for page in pages:
        lines = page.splitlines()
        # Trusted label on line 1: after the row header, before the untrusted page body.
        assert lines[1] == LIVE_PAGE
        assert lines[2].startswith(rg.UNTRUSTED_BEGIN)
        sid = int(_FETCH_HEADER.match(page).group(1))
        assert lr.tool_output_sids("web_fetch", page) == (sid, [sid])


def test_hindcast_withholds_markets_and_records_the_point_in_time_policy(tmp_path, bridge, monkeypatch):
    rc, meta, plog, _model, out = _run(tmp_path, bridge, monkeypatch, as_of=AS_OF)
    assert rc == 0, meta.get("error")

    assert bridge._v3_test_calls["markets"] == []
    assert f"prediction markets withheld (RESEARCH_AS_OF={AS_OF})" in plog.of("stage")
    expected = {"as_of": AS_OF, "hindcast": True, "markets": "withheld", "fetch": "label",
                "search": "unbounded"}
    assert meta["point_in_time"] == expected
    assert _load(out / "meta.json")["point_in_time"] == expected


def test_identity_carries_the_pin_only_when_pinned(tmp_path, bridge, monkeypatch):
    rc, meta, _plog, _model, out = _run(tmp_path / "hindcast", bridge, monkeypatch, as_of=AS_OF)
    assert rc == 0, meta.get("error")
    assert _load(out / lr.WORK_DIRNAME / lr.STATE_FILENAME)["identity"]["as_of"] == AS_OF

    rc, meta, _plog, _model, out = _run(tmp_path / "live", bridge, monkeypatch)
    assert rc == 0, meta.get("error")
    assert "as_of" not in _load(out / lr.WORK_DIRNAME / lr.STATE_FILENAME)["identity"]


def test_a_new_pin_does_not_reuse_a_live_work_dir(tmp_path, bridge, monkeypatch):
    rc, meta, _plog, _model, _out = _run(tmp_path, bridge, monkeypatch)
    assert rc == 0, meta.get("error")
    rc, meta, plog, _model, out = _run(tmp_path, bridge, monkeypatch, as_of=AS_OF)
    assert rc == 0, meta.get("error")
    assert any("belongs to another run identity" in line for line in plog.of("warn"))
    assert _load(out / "v3" / "plan.json")["as_of"] == AS_OF


@pytest.mark.parametrize("raw", ["2024-6-1", "2024-06-01 00:00", "June 2024", "2026-10-02", "2024-02-30"])
def test_invalid_research_as_of_exits_2_before_any_model_call(tmp_path, bridge, monkeypatch, raw):
    rc, meta, plog, model, out = _run(tmp_path, bridge, monkeypatch, as_of=raw)

    assert rc == 2
    assert meta["status"] == "failed" and meta["error"].startswith("invalid RESEARCH_AS_OF")
    assert _load(out / "meta.json")["error"] == meta["error"]
    assert model.calls == [] and not (out / "research_report.md").exists()
    assert any("invalid RESEARCH_AS_OF" in line for line in plog.of("error"))


# =============================================================== live runs

def test_live_prompts_are_byte_identical_without_the_variable(tmp_path, bridge, monkeypatch):
    """No RESEARCH_AS_OF, an empty one and a pin equal to today (pinned but live)
    send exactly the same requests: no point-in-time line, no page label."""
    rc, meta, _plog, unset, unset_out = _run(tmp_path / "unset", bridge, monkeypatch)
    assert rc == 0, meta.get("error")
    rc, meta, _plog, empty, _out = _run(tmp_path / "empty", bridge, monkeypatch, as_of="")
    assert rc == 0, meta.get("error")
    rc, today_meta, _plog, today, _out = _run(tmp_path / "today", bridge, monkeypatch, as_of=TODAY)
    assert rc == 0, today_meta.get("error")

    assert _prompts(unset) == _prompts(empty) == _prompts(today)
    assert not [text for text in _texts(unset) if "Point-in-time rule" in text or "LIVE PAGE" in text]
    assert _load(unset_out / "v3" / "plan.json")["as_of"] == TODAY
    assert "point_in_time" not in meta
    # A pin equal to today is recorded as live retrieval (markets still withheld).
    assert today_meta["point_in_time"] == {"as_of": TODAY, "hindcast": False, "markets": "withheld",
                                           "fetch": "live", "search": "unbounded"}
    assert len(bridge._v3_test_calls["markets"]) == 2   # the unset and empty runs only


def test_live_brief_rendering_is_unchanged():
    plan = lr.Plan(question="Q?", language=lr.ENGLISH, as_of=TODAY, restated_question="", horizon="",
                   kiqs=[], sections=[], scenarios=[], actors=[], key_entities=[], scout_queries=[])
    live = lr.render_brief(plan)
    assert live == lr.render_brief(plan, point_in_time=False)
    assert live.splitlines()[:5] == ["RUN BRIEF", "Research question: Q?", "Output language: English",
                                     f"As-of date (UTC): {TODAY}",
                                     "Forecast horizon: not stated in the question"]
    pinned = lr.render_brief(plan, point_in_time=True).splitlines()
    assert pinned == live.splitlines()[:4] + [lr.point_in_time_rule(TODAY)] + live.splitlines()[4:]
    pre = lr.render_pre_brief("Q?", "English", AS_OF)
    assert pre == f"RUN BRIEF (planning stage)\nResearch question: Q?\nOutput language: English\nAs-of date (UTC): {AS_OF}"
    assert lr.render_pre_brief("Q?", "English", AS_OF, point_in_time=True) == f"{pre}\n{RULE}"


# =============================================================== helpers

@pytest.mark.parametrize("value", [
    "2024-06-01", "2024-6-1", "2024-06-01 00:00", "2024-02-29", "2023-02-29", " 2024-06-01",
    "2024/06/01", "", None, 20240601, "June 2024", "2024-06-01\n",
])
def test_bridge_canonical_date_matches_the_backend_rule(value):
    try:
        validate_as_of(value, today_utc=date.max)
        backend = True
    except ValueError:
        backend = False
    assert lr._canonical_date(value) is backend


@pytest.mark.parametrize("raw, expected", [
    (None, None), ("", None), ("  ", None), (AS_OF, AS_OF), (f" {AS_OF} ", AS_OF),
    (TODAY, None),            # today is live
    ("2026-10-02", None),     # the future is never a vintage (the engine refuses it)
    ("2024-6-1", None),
])
def test_default_tools_factory_labels_pages_only_for_a_hindcast(monkeypatch, tmp_path, raw, expected):
    recorded = {}

    def fake_tools(*args, **kwargs):
        recorded.update(kwargs)
        return types.SimpleNamespace()

    monkeypatch.setattr(rg, "ResearchTools", fake_tools)
    if raw is None:
        monkeypatch.delenv("RESEARCH_AS_OF", raising=False)
    else:
        monkeypatch.setenv("RESEARCH_AS_OF", raw)
    lr._default_tools_factory(None, tmp_path, None, None, rg.ToolLimits())
    assert recorded["vintage_as_of"] == expected
