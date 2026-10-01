"""RESEARCH-13 (P09): report-stage wiring of the forecast-prompt context packs.

Flags off: no pack is built, no sidecar is written, forecast.json has no context_pack key and
both probability prompts keep their legacy slices. Flags on: the pack text replaces the slices,
the sidecar is written atomically, and forecast.context_pack carries the digest (no text) only
in the final write, never in the spine early write or a critique input. A packer that raises
or falls back leaves the legacy prompts in place. Also covers the as_of chronology split, the
hindcast cutoff, the REPORT-10 market-table strip, the EVAL-11 spine_kwargs amendment and the
offline replay script.

Offline: FakeLLMClient-based router; no network, no real LLM.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from app.config import Config
from app.services import forecast_context_packer as cp
from app.services import forecast_extractor as fe
from app.services import forecast_ledger
from app.services import pipeline_orchestrator as po
from app.services import report_agent as ra
from app.services.hindcast_policy import HINDCAST_POLICY_VERSION
from app.services.report_agent import ReportAgent, ReportManager
from tests.conftest import FakeLLMClient

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = datetime.now(timezone.utc).date()
AS_OF = TODAY - timedelta(days=10)


def _day(offset: int) -> str:
    return (AS_OF + timedelta(days=offset)).isoformat()


TIMELINE = [
    {"date": _day(-60), "event": "Older development: the spring framework agreement."},
    {"date": _day(-5), "event": "Newest development: the regulator's interim ruling."},
    {"date": _day(20), "event": "Scheduled: the final ruling hearing."},
    {"date": "", "event": "Undated background item."},
]

_REFS = "\n".join(f"[S{i}] Reference entry {i} — https://example.org/{i}" for i in range(1, 400))
DOSSIER = "\n\n".join([
    "# Forecast dossier",
    "## Executive Summary\n\n" + "Executive summary line about the outlook.\n" * 60,
    "## Background\n\n" + "Background analysis paragraph line.\n" * 900,
    "## Resolution-ready forecasts\n\n| F1 | The ruling is upheld by year end | 0.6 |\n"
    + "Resolution notes line.\n" * 40,
    "## Market structure\n\n" + "Market structure analysis line.\n" * 700,
    "## References\n\n" + _REFS,
    "## Visual Annex\n\n" + "Chart description line.\n" * 80,
])

SPINE_REPLY = {"headline": "h", "horizon": "2030", "confidence": "medium", "scenarios": [
    {"name": name, "probability": p, "summary": f"{name} summary", "key_drivers": ["driver"],
     "resolution_criteria": f"{name} resolves if the index is above {10 + i}% by 2030"}
    for i, (name, p) in enumerate(zip(("Upheld path", "Overturned path", "Other / Status Quo"),
                                      (0.5, 0.3, 0.2), strict=True))]}
BINARY_REPLY = {"binary_forecasts": [{
    "id": "F1", "statement": "The ruling is upheld by the end of 2027", "probability": 0.3,
    "resolution_criteria": "Court record shows the ruling upheld by 2027-12-31",
    "theme": "t1", "horizon_year": 2027}]}

# FU-4: page-verified research rows (REPORT-8) and the source list that resolves their [S#].
VERIFIED_SOURCES = [{"title": "Survey", "url": "https://survey.example/annual-survey", "tier": "S1"}]
UNLABELLED_TABLE_HEADER = "关键量化指标"


def _labelled_rows():
    return [{"metric": "Approval rate", "value": "61", "unit": "%", "as_of_date": _day(-3),
             "value_type": "actual", "tier": "S1", "source": "Survey", "source_ref": "S1",
             "source_url": "https://survey.example/annual-survey",
             "verification": "verified", "verified": True}]


class _RouterLLM(FakeLLMClient):
    """Routes chat_json by prompt: critic -> {}, binary draw -> one binary, else the spine."""

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, tier=None, **kwargs):
        super().chat_json(messages, temperature=temperature, max_tokens=max_tokens, tier=tier,
                          **kwargs)
        content = messages[-1]["content"]
        if content.startswith(fe._CRITIQUE_INSTRUCTIONS):
            return {}
        if "[Research dossier]" in content:
            return json.loads(json.dumps(BINARY_REPLY))
        return json.loads(json.dumps(SPINE_REPLY))


def _prompts(llm, marker):
    return [c["messages"][-1]["content"] for c in llm.calls
            if c["kind"] == "chat_json" and marker in c["messages"][-1]["content"]]


def _spine_prompts(llm):
    return [c["messages"][-1]["content"] for c in llm.calls
            if c["kind"] == "chat_json"
            and c["messages"][-1]["content"].startswith("你是预测校准专家")]


def _agent(llm):
    a = ReportAgent.__new__(ReportAgent)
    defaults = {
        "llm": llm, "graph_id": "g1", "simulation_id": "sim1",
        "simulation_requirement": "Will the ruling be upheld?",
        "situation_brief": "LEGACY BRIEF " * 40,
        "actors": {"as_of_date": AS_OF.isoformat(),
                   "situation_brief": {"current_situation": "The ruling is under review.",
                                       "context": "A long-running dispute."},
                   "key_events": []},
        "sources": [], "research_report": DOSSIER, "timeline_events": list(TIMELINE),
        "quantitative": [{"metric": "Approval rate", "value": "61", "unit": "%",
                          "as_of_date": _day(-3), "tier": "S1", "source": "Survey"}],
        "output_language": "English", "scenario_label": "", "base_simulation_id": None,
        "_background_block": "", "_sources_index": "", "_signal_pack": "",
        "_market_pack": "", "_forecast_spine": None, "_forecast_spine_block": "",
        "_retrieval_query": None, "_outline_degraded": False, "_outline_summary": "",
        "_section_tool_calls": 0, "report_logger": None, "console_logger": None,
        "tools": {}, "hindcast": None, "_hindcast_pin_cache": None,
        "evaluation_context": None, "_evaluation_context_looked_up": True,
        "_evaluation_context_lookup": None, "backbone_check_policy": None,
    }
    for key, value in defaults.items():
        setattr(a, key, value)
    return a


def _constructed_labelled(llm, **over):
    """A ReportAgent built by its real constructor (FU-4: __init__ decides whether REPORT-8's
    verified-figures block exists before the spine pack is assembled)."""
    kwargs = {
        "graph_id": "g1", "simulation_id": "sim_fu4",
        "simulation_requirement": "Will the ruling be upheld?", "llm_client": llm,
        "zep_tools": object(), "situation_brief": "Situation brief.",
        "actors": {"as_of_date": AS_OF.isoformat(),
                   "situation_brief": {"current_situation": "The ruling is under review."}},
        "sources": list(VERIFIED_SOURCES), "research_report": DOSSIER,
        "quantitative": _labelled_rows(), "timeline_events": list(TIMELINE),
    }
    kwargs.update(over)
    return ReportAgent(**kwargs)


@pytest.fixture
def report_env(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(tmp_path / "ledger"), raising=False)
    for name, value in {
        "REPORT_FORECAST_SELF_CRITIQUE": False, "REPORT_CRITIQUE_BEFORE_PROSE": True,
        "REPORT_PREMORTEM": False, "REPORT_SPINE_SELFCONSISTENCY_K": 1,
        "FORECAST_EMIT_BINARY": True, "FORECAST_BINARY_CONTRARIAN": False,
        "FORECAST_SIM_SENSITIVITY": False, "FORECAST_ENSEMBLE_MODELS": "",
        "PREDICTION_MARKETS_ENABLED": False, "FORECAST_BINARY_THEMES": None,
        "BINARY_FORECASTS_MIN_COUNT": 1, "REPORT_PUBLISH_GATE": False,
        "REPORT_REPAIR_PASSES": False, "REPORT_FORECAST_LEDGER": False,
        "FORECAST_CONTEXT_PACK_BINARY": False, "FORECAST_CONTEXT_PACK_SPINE": False,
        "REPORT_CHRONOLOGY_ASOF_SPLIT": False,
    }.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    monkeypatch.setattr(forecast_ledger, "append_forecast", lambda forecast, **kw: None)
    return tmp_path


def _flags(monkeypatch, on=True):
    monkeypatch.setattr(Config, "FORECAST_CONTEXT_PACK_BINARY", on, raising=False)
    monkeypatch.setattr(Config, "FORECAST_CONTEXT_PACK_SPINE", on, raising=False)


def _folder(tmp_path, report_id):
    return os.path.join(str(tmp_path), "reports", report_id)


def _read(tmp_path, report_id, name):
    with open(os.path.join(_folder(tmp_path, report_id), name), encoding="utf-8") as handle:
        return json.load(handle)


def _run(tmp_path, report_id, llm=None, agent=None):
    llm = llm or _RouterLLM()
    os.makedirs(_folder(tmp_path, report_id), exist_ok=True)
    agent = agent or _agent(llm)
    agent._derive_and_pin_forecast_spine(report_id)
    early = _read(tmp_path, report_id, "forecast.json")
    agent._finalize_structured_forecast(report_id, "# T\n\nBody text.")
    return agent, llm, early, _read(tmp_path, report_id, "forecast.json")


def _sidecars(tmp_path, report_id):
    return sorted(n for n in os.listdir(_folder(tmp_path, report_id))
                  if n.startswith("context_pack_"))


# ----------------------------------------------------------------------- flags off
def test_flags_off_no_context_pack_key_no_sidecar_and_legacy_prompts(report_env, monkeypatch):
    seen = {}
    real_ebf, real_spine = fe.extract_binary_forecasts, fe.derive_forecast_spine

    def ebf(*args, **kwargs):
        seen["binary"] = set(kwargs)
        return real_ebf(*args, **kwargs)

    def spine(*args, **kwargs):
        seen["spine"] = set(kwargs)
        return real_spine(*args, **kwargs)

    monkeypatch.setattr(fe, "extract_binary_forecasts", ebf)
    monkeypatch.setattr(fe, "derive_forecast_spine", spine)
    agent, llm, early, final = _run(report_env, "report_off")

    assert "context_pack" not in final and "context_pack" not in early
    assert _sidecars(report_env, "report_off") == []
    assert not getattr(agent, "_context_pack_digests", None)  # no pack was ever built
    assert "context_pack" not in seen["binary"] and "context_pack" not in seen["spine"]
    binary_prompt, = _prompts(llm, "[Research dossier]")
    assert "\n\n[Situation brief]\n" in binary_prompt and "…(中段略)…" in binary_prompt
    spine_prompt, = _spine_prompts(llm)
    assert "\n\n[态势简报]\n" in spine_prompt and "[研究证据包" not in spine_prompt
    assert final["binary_forecasts"]


# ----------------------------------------------------------------------- flags on
def test_flag_on_writes_sidecar_atomically_and_digest_matches(report_env, monkeypatch):
    _flags(monkeypatch)
    written = []
    real_write = ra.write_json_atomic

    def spy(path, obj, **kwargs):
        written.append(os.path.basename(path))
        return real_write(path, obj, **kwargs)

    monkeypatch.setattr(ra, "write_json_atomic", spy)
    _agent_, llm, early, final = _run(report_env, "report_on")

    assert {"context_pack_binary.json", "context_pack_spine.json"} <= set(written)
    assert _sidecars(report_env, "report_on") == ["context_pack_binary.json",
                                                   "context_pack_spine.json"]
    for kind in ("binary", "spine"):
        sidecar = _read(report_env, "report_on", f"context_pack_{kind}.json")
        digest = final["context_pack"][kind]
        assert sidecar["schema"] == "drf.context_pack/1" and sidecar["status"] == "ok"
        assert digest["text_sha256"] == sidecar["text_sha256"]
        assert digest["text_sha256"] == hashlib.sha256(sidecar["text"].encode("utf-8")).hexdigest()
        assert "text" not in digest and digest["applied"] is True
        assert digest["as_of_source"] == "actors"
        # "published" is recorded after the spine draw, so only the spine digest carries it
        assert {k: v for k, v in sidecar.items() if k != "text"} == {
            k: v for k, v in digest.items() if k != "published"}
    assert final["context_pack"]["spine"]["published"] is True
    assert "published" not in final["context_pack"]["binary"]
    assert final["context_pack"]["spine"]["situation_source"] == "situation_brief_block"

    binary_text = _read(report_env, "report_on", "context_pack_binary.json")["text"]
    binary_prompt, = _prompts(llm, "[Research dossier]")
    assert binary_prompt.endswith("\n\n[Research dossier]\n" + binary_text)
    assert "[Situation brief]" not in binary_prompt and "…(中段略)…" not in binary_prompt
    assert "## Resolution-ready forecasts" in binary_text and "[S1]" not in binary_text
    assert "Newest development: the regulator's interim ruling." in binary_text
    spine_text = _read(report_env, "report_on", "context_pack_spine.json")["text"]
    spine_prompt, = _spine_prompts(llm)
    assert "\n\n[研究证据包（按时点标注）]\n" + spine_text in spine_prompt
    assert "[态势简报]" not in spine_prompt
    assert "Newest development" in spine_text and "Scheduled: the final ruling hearing." in spine_text


def test_digest_absent_from_spine_early_write_and_critique_inputs(report_env, monkeypatch):
    _flags(monkeypatch)
    monkeypatch.setattr(Config, "REPORT_FORECAST_SELF_CRITIQUE", True, raising=False)
    critique_inputs = []

    def critique_spy(forecast, llm, *args, **kwargs):
        critique_inputs.append(json.dumps(forecast, ensure_ascii=False))
        return forecast

    monkeypatch.setattr(fe, "self_critique_forecast", critique_spy)
    agent, _llm, early, final = _run(report_env, "report_order")

    assert set(agent._context_pack_digests) == {"binary", "spine"}
    assert "context_pack" not in early
    assert critique_inputs and all('"context_pack"' not in raw for raw in critique_inputs)
    assert set(final["context_pack"]) == {"binary", "spine"}


def test_packer_that_raises_keeps_the_legacy_extraction(report_env, monkeypatch):
    _flags(monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError("packer exploded")

    monkeypatch.setattr(cp, "build_binary_pack", boom)
    monkeypatch.setattr(cp, "build_spine_pack", boom)
    _agent_, llm, _early, final = _run(report_env, "report_raise")

    binary_prompt, = _prompts(llm, "[Research dossier]")
    assert "\n\n[Situation brief]\n" in binary_prompt and "…(中段略)…" in binary_prompt
    spine_prompt, = _spine_prompts(llm)
    assert "\n\n[态势简报]\n" in spine_prompt
    assert final["binary_forecasts"] and final["scenarios"]
    assert final["context_pack"] == {
        "spine": {"kind": "spine", "status": "error:RuntimeError", "applied": False},
        "binary": {"kind": "binary", "status": "error:RuntimeError", "applied": False}}
    assert _sidecars(report_env, "report_raise") == []


class _NoScenarioSpineLLM(_RouterLLM):
    """The spine draw yields no scenarios (the post-hoc extraction, whose prompt opens with
    the same first sentence, is still answered)."""

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, tier=None, **kwargs):
        reply = super().chat_json(messages, temperature=temperature, max_tokens=max_tokens,
                                  tier=tier, **kwargs)
        if messages[-1]["content"].startswith(fe._SPINE_LEAD_PREFIX):
            return {"headline": "h", "scenarios": []}
        return reply


def test_spine_without_scenarios_marks_the_pack_unpublished(report_env, monkeypatch):
    _flags(monkeypatch)
    llm = _NoScenarioSpineLLM()
    agent = _agent(llm)
    os.makedirs(_folder(report_env, "report_noscen"), exist_ok=True)
    agent._derive_and_pin_forecast_spine("report_noscen")
    assert agent._forecast_spine is None  # no spine pinned: no early forecast.json either
    assert not os.path.exists(os.path.join(_folder(report_env, "report_noscen"), "forecast.json"))
    agent._finalize_structured_forecast("report_noscen", "# T\n\nBody text.")
    final = _read(report_env, "report_noscen", "forecast.json")

    spine_draws = [c["messages"][-1]["content"] for c in llm.calls if c["kind"] == "chat_json"
                   and c["messages"][-1]["content"].startswith(fe._SPINE_LEAD_PREFIX)]
    assert spine_draws
    assert all("[研究证据包（按时点标注）]" in prompt for prompt in spine_draws)
    spine = final["context_pack"]["spine"]
    assert spine["applied"] is True and spine["published"] is False
    assert final["scenarios"]  # the post-hoc extraction, which never saw the pack


def test_spine_situation_falls_back_to_the_legacy_brief_without_its_timeline(report_env):
    agent = _agent(_RouterLLM())
    agent.actors = {
        "as_of_date": AS_OF.isoformat(), "central_question": "Will the ruling be upheld?",
        "actors": [{"name": "Regulator Alpha", "type": "agency", "role": "decides the appeal"}],
        "key_events": [{"date": _day(3), "event": "KEY EVENT ONLY IN ACTORS JSON"}],
        "hot_topics": ["appeal timing"],
    }
    result, provenance = agent._context_pack_result("spine")
    assert result.ok and provenance["situation_source"] == "legacy_brief"
    assert "- Regulator Alpha（agency） 角色: decides the appeal" in result.text
    assert "appeal timing" in result.text
    # the dated rows reach the pack only through the as_of lanes, never unlabelled
    assert "KEY EVENT ONLY IN ACTORS JSON" not in result.text
    assert "研究截止日" not in result.text and "关键时间线" not in result.text
    assert "Newest development" in result.text

    agent.actors = None
    empty, provenance = agent._context_pack_result("spine")
    assert provenance["situation_source"] == "none"


def test_spine_pack_uses_the_verified_figures_block_when_the_report_has_one(report_env, monkeypatch):
    """FU-4 (REPORT-8 open issue): the spine pack gets REPORT-8's labelled verified-figures
    block (the block Part 2 gets) instead of the unlabelled key-metrics table."""
    monkeypatch.setattr(Config, "REPORT_VERIFIED_FACTS_BLOCK", True, raising=False)
    agent = _agent(_RouterLLM())
    baseline, provenance = agent._context_pack_result("spine")
    assert "| Approval rate | 61 |" in baseline.text and "key_metrics_source" not in provenance
    verified = "## Verified figures\n| Metric | Value |\n|---|---|\n| Approval rate (verified) | 61% [S1] |"
    agent._verified_figures = {"rendered": verified}
    packed, provenance = agent._context_pack_result("spine")
    assert "Approval rate (verified)" in packed.text and "| Approval rate | 61 |" not in packed.text
    assert provenance["key_metrics_source"] == "verified_figures"
    # No rendered block, a failed build (None) or the knob off: the table, byte-identical.
    for state in ({"rendered": ""}, None):
        agent._verified_figures = state
        again, provenance = agent._context_pack_result("spine")
        assert again.text == baseline.text and "key_metrics_source" not in provenance
    agent._verified_figures = {"rendered": verified}
    monkeypatch.setattr(Config, "REPORT_VERIFIED_FACTS_BLOCK", False, raising=False)
    off, provenance = agent._context_pack_result("spine")
    assert off.text == baseline.text and "key_metrics_source" not in provenance


def test_constructed_report_puts_its_verified_block_in_the_spine_prompt(report_env, monkeypatch):
    """FU-4 call order: ReportAgent.__init__ builds REPORT-8's block (in
    _build_background_block) before _derive_and_pin_forecast_spine assembles the spine pack, so
    the sidecar, the pack and the spine prompt carry the very text Part 2 injects, and no
    unlabelled table."""
    _flags(monkeypatch)
    monkeypatch.setattr(Config, "REPORT_VERIFIED_FACTS_BLOCK", True, raising=False)
    monkeypatch.setattr(Config, "RESEARCH_FORECAST_INPUTS", True, raising=False)
    llm = _RouterLLM()
    agent = _constructed_labelled(llm)
    rendered = agent._verified_figures["rendered"]
    assert rendered and rendered in agent._background_block
    os.makedirs(_folder(report_env, "report_fu4"), exist_ok=True)
    agent._derive_and_pin_forecast_spine("report_fu4")

    sidecar = _read(report_env, "report_fu4", "context_pack_spine.json")
    assert sidecar["applied"] is True and sidecar["key_metrics_source"] == "verified_figures"
    assert rendered in sidecar["text"] and UNLABELLED_TABLE_HEADER not in sidecar["text"]
    assert agent._verified_figures["rendered"] == rendered  # Part 2's input is untouched
    spine_prompt, = _spine_prompts(llm)
    assert rendered in spine_prompt and UNLABELLED_TABLE_HEADER not in spine_prompt


@pytest.mark.parametrize("init_skips", ["research_forecast_inputs_off", "no_situation_brief"])
def test_spine_pack_builds_the_verified_block_when_init_did_not(report_env, monkeypatch, init_skips):
    """FU-4: __init__ reaches REPORT-8's builder only through _build_background_block, which needs
    a situation brief and RESEARCH_FORECAST_INPUTS. Without it, labelled rows still give the spine
    pack the verified block (built by the same builder, the same text), and the agent is left as it
    was: no cached block, so Part 2 and the background block are unchanged."""
    monkeypatch.setattr(Config, "REPORT_VERIFIED_FACTS_BLOCK", True, raising=False)
    monkeypatch.setattr(Config, "RESEARCH_FORECAST_INPUTS",
                        init_skips != "research_forecast_inputs_off", raising=False)
    brief = "" if init_skips == "no_situation_brief" else "Situation brief."
    agent = _constructed_labelled(_RouterLLM(), situation_brief=brief)
    assert not hasattr(agent, "_verified_figures")
    background = agent._background_block
    reference = _constructed_labelled(_RouterLLM(), situation_brief=brief)
    expected = reference._build_verified_figures_block()
    assert expected

    os.makedirs(_folder(report_env, "report_lazy"), exist_ok=True)
    text = agent._forecast_context_pack("report_lazy", "spine")
    sidecar = _read(report_env, "report_lazy", "context_pack_spine.json")
    assert sidecar["applied"] is True and sidecar["key_metrics_source"] == "verified_figures"
    assert expected in text and UNLABELLED_TABLE_HEADER not in text
    assert not hasattr(agent, "_verified_figures") and agent._background_block == background
    assert expected not in background


def test_invalid_as_of_falls_back_with_a_recorded_digest(report_env, monkeypatch):
    _flags(monkeypatch)
    agent = _agent(_RouterLLM())
    agent.actors = dict(agent.actors, as_of_date=(TODAY + timedelta(days=3)).isoformat())
    _agent_, llm, _early, final = _run(report_env, "report_future", llm=agent.llm, agent=agent)

    binary_prompt, = _prompts(llm, "[Research dossier]")
    assert "\n\n[Situation brief]\n" in binary_prompt
    for kind in ("binary", "spine"):
        digest = final["context_pack"][kind]
        assert digest["status"] == cp.STATUS_AS_OF_INVALID and digest["applied"] is False
        assert "text" not in digest


def test_spine_pack_reaches_the_backbone_check_kwargs(report_env, monkeypatch):
    captured = {}

    def run_check(self, pre_critique_spine, spine_kwargs, **kwargs):
        captured["kwargs"] = dict(spine_kwargs)

    monkeypatch.setattr(ReportAgent, "_run_backbone_check", run_check)
    for on in (False, True):
        _flags(monkeypatch, on)
        llm = _RouterLLM()
        agent = _agent(llm)
        os.makedirs(_folder(report_env, f"report_bb_{on}"), exist_ok=True)
        agent._derive_and_pin_forecast_spine(f"report_bb_{on}")
        assert ("context_pack" in captured["kwargs"]) is on
        rebuilt, _anchor = fe.build_spine_user_prompt(**captured["kwargs"])
        assert rebuilt == _spine_prompts(llm)[0]


# ----------------------------------------------------------------------- inputs
def test_binary_pack_strips_the_machine_market_table(report_env, monkeypatch):
    agent = _agent(_RouterLLM())
    agent.research_report = ("## Executive Summary\n\n" + "Summary line.\n" * 20
                             + "\n## Prediction Market Signals\n\n"
                             + "| Will the market question resolve yes | 0.41 |\n" * 5)
    now = datetime.now(timezone.utc)
    kept, kept_prov = agent._context_pack_result("binary", now=now)
    stripped, prov = agent._context_pack_result("binary", now=now, strip_market_table=True)
    assert "## Prediction Market Signals" in kept.text and "market_table_stripped" not in kept_prov
    assert "## Prediction Market Signals" not in stripped.text
    assert prov["market_table_stripped"] == 1

    # the call site strips exactly when the extractor would (knob on + a market pack injected)
    seen = []
    monkeypatch.setattr(ReportAgent, "_forecast_context_pack",
                        lambda self, rid, kind, strip_market_table=False:
                        seen.append((kind, strip_market_table)))
    monkeypatch.setattr(fe, "extract_binary_forecasts",
                        lambda *a, **k: {"binary_forecasts": [], "binary_quality": {}})
    monkeypatch.setattr(Config, "FORECAST_CONTEXT_PACK_BINARY", True, raising=False)
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "FORECAST_DRAW_DOSSIER_STRIP_MARKET_TABLE", True, raising=False)
    for market_pack, expected in (("| Market | 0.41 |", True), ("", False)):
        agent = _agent(_RouterLLM())
        agent._market_pack = market_pack
        agent._forecast_spine = json.loads(json.dumps(SPINE_REPLY))
        monkeypatch.setattr(agent, "_build_market_pack", lambda: "", raising=False)
        os.makedirs(_folder(report_env, "report_strip"), exist_ok=True)
        agent._finalize_structured_forecast("report_strip", "# T\n\nBody.")
        assert seen[-1] == ("binary", expected)


def test_hindcast_pin_as_of_is_the_lane_cutoff(report_env):
    agent = _agent(_RouterLLM())
    cutoff = AS_OF - timedelta(days=30)
    agent.hindcast = {"version": HINDCAST_POLICY_VERSION, "hindcast": True,
                      "as_of": cutoff.isoformat()}
    assert agent._context_pack_as_of() == (cutoff.isoformat(), "hindcast_pin")
    result, provenance = agent._context_pack_result("binary")
    assert provenance["as_of_source"] == "hindcast_pin"
    assert "Newest development" not in result.text  # dated after the hindcast cutoff
    assert "Older development: the spring framework agreement." in result.text
    assert "Scheduled: the final ruling hearing." not in result.text  # retrospective: withheld
    assert result.telemetry["lanes"]["scheduled"]["post_as_of_rows_withheld"] == 2


def test_a_recent_hindcast_pin_withholds_rows_dated_after_its_cutoff(report_env, monkeypatch):
    agent = _agent(_RouterLLM())
    cutoff = TODAY - timedelta(days=5)
    agent.timeline_events = [
        {"date": (cutoff - timedelta(days=2)).isoformat(), "event": "Before the cutoff."},
        {"date": TODAY.isoformat(), "event": "AFTER CUTOFF - outcome reported."}]
    agent.actors = dict(agent.actors, as_of_date=cutoff.isoformat())
    live, _prov = agent._context_pack_result("binary")  # a live run at the same as_of shows it
    assert "[SCHEDULED" in live.text and "AFTER CUTOFF" in live.text

    agent.hindcast = {"version": HINDCAST_POLICY_VERSION, "hindcast": True,
                      "as_of": cutoff.isoformat()}
    for kind in ("binary", "spine"):
        result, provenance = agent._context_pack_result(kind)
        assert result.ok and provenance["as_of_source"] == "hindcast_pin"
        assert "AFTER CUTOFF" not in result.text and "Before the cutoff." in result.text
        scheduled = result.telemetry["lanes"]["scheduled"]
        assert scheduled["retrospective"] is True and scheduled["post_as_of_rows_withheld"] == 1
    monkeypatch.setattr(Config, "REPORT_CHRONOLOGY_ASOF_SPLIT", True, raising=False)
    block = agent._build_chronology_block()
    assert "AFTER CUTOFF" not in block and "### 已排期" not in block
    assert f"1 条日期在 {cutoff.isoformat()} 之后的条目" in block


def test_hindcast_pin_without_as_of_never_falls_back_to_the_research_date(report_env):
    agent = _agent(_RouterLLM())
    agent.hindcast = {"version": HINDCAST_POLICY_VERSION, "hindcast": True}
    assert agent._context_pack_as_of() == (None, "hindcast_pin")
    result, _prov = agent._context_pack_result("binary")
    assert result.status == cp.STATUS_AS_OF_INVALID and result.text == ""


def _constructed(**kwargs):
    """A ReportAgent built through __init__ (no network: fake LLM, dummy graph tools)."""
    return ReportAgent(graph_id="g1", simulation_id="sim_ctor",
                       simulation_requirement="Will the ruling be upheld?",
                       llm_client=FakeLLMClient(), zep_tools=object(), **kwargs)


def test_init_chronology_split_uses_the_constructor_hindcast_pin(report_env, monkeypatch):
    """The split block is built in __init__: it must already see the hindcast kwarg."""
    lookups = []

    def lookup(simulation_id):
        lookups.append(simulation_id)
        raise OSError("pipeline dir unreadable")

    monkeypatch.setattr(po, "hindcast_pin_for_simulation", lookup)
    monkeypatch.setattr(Config, "REPORT_CHRONOLOGY_ASOF_SPLIT", True, raising=False)
    cutoff = TODAY - timedelta(days=60)
    agent = _constructed(
        hindcast={"version": HINDCAST_POLICY_VERSION, "hindcast": True,
                  "as_of": cutoff.isoformat()},
        actors={"as_of_date": TODAY.isoformat()},
        timeline_events=[
            {"date": (cutoff - timedelta(days=10)).isoformat(), "event": "Before the cutoff."},
            {"date": (TODAY - timedelta(days=30)).isoformat(),
             "event": "AFTER CUTOFF - resolution leaked"}])
    block = agent._chronology_block
    assert f"日期在 {cutoff.isoformat()} 当日或之前" in block
    assert "Before the cutoff." in block and "AFTER CUTOFF" not in block
    assert lookups == [] and agent._hindcast_lookup_failed is False


def test_init_with_a_failed_pin_lookup_falls_back_fail_closed(report_env, monkeypatch):
    """No kwarg and a lookup that raises: hindcast status unknown, so neither the chronology
    split nor the packs cut at the research date, and TIME-6 still withholds markets."""
    def lookup(simulation_id):
        raise OSError("pipeline dir unreadable")

    monkeypatch.setattr(po, "hindcast_pin_for_simulation", lookup)
    monkeypatch.setattr(Config, "REPORT_CHRONOLOGY_ASOF_SPLIT", True, raising=False)
    rows = [{"date": _day(-5), "event": "Newest development."},
            {"date": _day(20), "event": "Scheduled hearing."}]
    agent = _constructed(actors={"as_of_date": AS_OF.isoformat()}, timeline_events=rows,
                         research_report=DOSSIER)
    monkeypatch.setattr(Config, "REPORT_CHRONOLOGY_ASOF_SPLIT", False, raising=False)
    assert agent._chronology_block == agent._build_chronology_block()  # the legacy block
    assert agent._hindcast_lookup_failed is True
    assert agent._markets_withheld_status() is not None
    assert agent._context_pack_as_of() == (None, "hindcast_lookup_failed")
    for kind in ("binary", "spine"):
        result, provenance = agent._context_pack_result(kind)
        assert result.status == cp.STATUS_AS_OF_INVALID and not result.ok
        assert provenance["as_of_source"] == "hindcast_lookup_failed"


def test_chronology_split_separates_past_and_scheduled_rows(report_env, monkeypatch):
    agent = _agent(_RouterLLM())
    legacy = agent._build_chronology_block()
    assert "### 已排期" not in legacy and "Scheduled: the final ruling hearing." in legacy

    monkeypatch.setattr(Config, "REPORT_CHRONOLOGY_ASOF_SPLIT", True, raising=False)
    split = agent._build_chronology_block()
    past, scheduled = split.split("### 已排期")
    assert past.startswith(f"## 关键事件时间线（研究实证，按时序；日期在 {AS_OF.isoformat()} 当日或之前")
    assert "Newest development" in past and "Older development" in past
    assert past.index("Older development") < past.index("Newest development")
    assert "Scheduled: the final ruling hearing." not in past
    assert "Scheduled: the final ruling hearing." in scheduled
    assert "1 条无日期、0 条跨越" in scheduled

    agent.actors = dict(agent.actors, as_of_date="2026")  # not a day: legacy block
    assert agent._build_chronology_block() == legacy


# ----------------------------------------------------------------------- replay script
def _write_handoff(root, *, dossier=DOSSIER, labelled=False):
    """A stored handoff under ``root``/pipe_test; ``labelled`` writes page-verified
    quantitative rows (REPORT-8) and the sources.json that resolves their [S#]."""
    handoff = root / "pipe_test" / "handoff"
    handoff.mkdir(parents=True)
    (handoff / "research_report.md").write_text(dossier, encoding="utf-8")
    actors = {"as_of_date": AS_OF.isoformat(),
              "situation_brief": {"current_situation": "The ruling is under review."}}
    (handoff / "actors.json").write_text(json.dumps(actors), encoding="utf-8")
    (handoff / "timeline.json").write_text(json.dumps(TIMELINE), encoding="utf-8")
    quantitative = (_labelled_rows() if labelled else
                    [{"metric": "Approval rate", "value": "61", "as_of_date": _day(-3), "tier": "S1"}])
    (handoff / "quantitative.json").write_text(json.dumps(quantitative), encoding="utf-8")
    if labelled:
        (handoff / "sources.json").write_text(json.dumps(VERIFIED_SOURCES), encoding="utf-8")
    return handoff


def test_replay_script_emits_metrics_with_zero_llm_calls(tmp_path, monkeypatch, capsys):
    from app.utils import llm_client
    import scripts.context_pack_replay as replay

    def no_llm(*args, **kwargs):
        raise AssertionError("the replay must not call an LLM")

    for name in ("__init__", "chat", "chat_json"):
        monkeypatch.setattr(llm_client.LLMClient, name, no_llm)
    handoff = _write_handoff(tmp_path)

    code = replay.main(["--handoff", str(handoff.parent), "--json", "--now", TODAY.isoformat()])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["errors"] == []
    row, = payload["handoffs"]
    binary, spine = row["binary"], row["spine"]
    assert binary["legacy"]["analyst_section_present"] is False
    assert binary["packed"]["analyst_section_present"] is True
    assert binary["legacy"]["references_chars"] > 0 and binary["packed"]["references_chars"] == 0
    assert binary["legacy"]["newest_past_row_in_lane"] is False
    assert binary["packed"]["newest_past_row_in_lane"] is True
    assert spine["packed"]["newest_past_row_in_lane"] is True
    assert binary["packed"]["audit_violations"] == 0
    assert set(binary["packed"]["streams"]) == set(cp.BINARY_PRIORITY)
    assert set(spine["packed"]["streams"]) == set(cp.SPINE_PRIORITY)
    assert row["newest_past_row"]["date"] == _day(-5)
    summary = payload["summary"]
    assert summary["binary"]["analyst_section_in_every_run_with_one"] is True
    for kind in ("binary", "spine"):
        assert summary[kind]["zero_references_chars"] is True
        assert summary[kind]["newest_past_row_in_every_lane"] is True
        assert summary[kind]["temporal_audit_clean"] is True

    assert replay.main(["--handoff", str(tmp_path / "missing"), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["errors"][0]["handoff"].endswith("missing")


ZH_DOSSIER = "\n\n".join([
    "# 预测档案",
    "## 执行摘要\n\n" + "该裁决在年底前维持的前景总体偏稳。\n" * 40,
    "## 背景\n\n" + "背景分析：监管机构的临时裁决仍在复核之中。\n" * 200,
])


@pytest.mark.parametrize("language", ["English", "Chinese"])
def test_replay_packs_the_verified_block_a_report_packs(report_env, monkeypatch, language):
    """FU-4: a handoff with page-verified rows gives the replayed spine pack exactly the pack a
    live report builds from the same inputs: REPORT-8's verified block with its [S#] resolved
    from sources.json, in the language ReportAgent.__init__ resolves from the pipeline prompt,
    the dossier and the brief (a Chinese run gets the Chinese block)."""
    import scripts.context_pack_replay as replay
    from app.utils import actors as actors_utils

    monkeypatch.delenv("REPORT_OUTPUT_LANGUAGE", raising=False)
    monkeypatch.setattr(Config, "REPORT_VERIFIED_FACTS_BLOCK", True, raising=False)
    monkeypatch.setattr(Config, "RESEARCH_FORECAST_INPUTS", True, raising=False)
    zh = language == "Chinese"
    handoff = _write_handoff(report_env / "runs", dossier=ZH_DOSSIER if zh else DOSSIER,
                             labelled=True)
    prompt = "该裁决会在年底前维持吗？" if zh else "Will the ruling be upheld?"
    (handoff.parent / "pipeline_state.json").write_text(
        json.dumps({"prompt": prompt, "options": {}}), encoding="utf-8")
    loaded = replay.load_handoff(str(handoff))
    assert loaded["prompt"] == prompt
    replayed = replay._agent(loaded)
    live = _constructed_labelled(
        _RouterLLM(), simulation_requirement=prompt,
        situation_brief=actors_utils.situation_brief(loaded["actors"]),
        actors=loaded["actors"], sources=loaded["sources"],
        research_report=loaded["research_report"],
        quantitative=loaded["quantitative"], timeline_events=loaded["timeline"])
    assert live.output_language == replayed.output_language == language
    rendered = live._verified_figures["rendered"]
    assert rendered.startswith("## 已核验指标" if zh else "## Verified-on-page figures")
    assert "[S1]" in rendered

    now = datetime.now(timezone.utc)
    live_pack, live_provenance = live._context_pack_result("spine", now=now)
    replay_pack, replay_provenance = replayed._context_pack_result("spine", now=now)
    assert replay_pack.ok and replay_pack.text == live_pack.text
    assert replay_provenance == live_provenance
    assert replay_provenance["key_metrics_source"] == "verified_figures"
    assert rendered in replay_pack.text and UNLABELLED_TABLE_HEADER not in replay_pack.text
    # Without labelled rows the replay packs the key-metrics table, as before.
    plain = replay._agent(replay.load_handoff(str(_write_handoff(report_env / "plain"))))
    plain_pack, provenance = plain._context_pack_result("spine", now=now)
    assert "key_metrics_source" not in provenance and UNLABELLED_TABLE_HEADER in plain_pack.text


def test_replay_json_stays_parseable_when_the_verified_block_logs(tmp_path):
    """FU-4: REPORT-8's builder logs an INFO line through report_agent's console handler, which
    app/utils/logger.py binds to stdout; the replay sends it to stderr, so ``--json`` prints one
    parseable document. Run in a child process, where that handler holds the real stdout."""
    handoff = _write_handoff(tmp_path, labelled=True)
    env = {key: value for key, value in os.environ.items() if key != "REPORT_OUTPUT_LANGUAGE"}
    env.update(DRF_TEST_PROCESS="1", REPORT_VERIFIED_FACTS_BLOCK="true")
    proc = subprocess.run(
        [sys.executable, os.path.join("scripts", "context_pack_replay.py"),
         "--handoff", str(handoff), "--json"],
        cwd=_BACKEND, env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    row, = payload["handoffs"]
    assert payload["errors"] == []
    assert row["provenance"]["spine"]["key_metrics_source"] == "verified_figures"
    assert "已核验指标块" in proc.stderr and "已核验指标块" not in proc.stdout


def test_replay_defaults_to_each_handoffs_as_of_day(tmp_path, capsys):
    """A stored run replayed at today's date would close the scheduled guard; by default the
    replay runs each handoff at its own as_of day, as its live report did."""
    import scripts.context_pack_replay as replay

    old_as_of = TODAY - timedelta(days=400)
    handoff = _write_handoff(tmp_path)
    (handoff / "actors.json").write_text(json.dumps({"as_of_date": old_as_of.isoformat()}),
                                         encoding="utf-8")
    (handoff / "timeline.json").write_text(json.dumps([
        {"date": (old_as_of - timedelta(days=3)).isoformat(), "event": "Past row."},
        {"date": (old_as_of + timedelta(days=20)).isoformat(), "event": "Scheduled row."}]),
        encoding="utf-8")

    assert replay.main(["--handoff", str(handoff), "--json", "--show-text"]) == 0
    payload = json.loads(capsys.readouterr().out)
    row, = payload["handoffs"]
    assert payload["now"] == "as_of"
    assert row["now"] == old_as_of.isoformat() and row["now_mode"] == "as_of"
    assert row["binary"]["packed"]["scheduled_guard"] == "open"
    assert "Scheduled row." in row["texts"]["binary"]

    assert replay.main(["--handoff", str(handoff), "--json", "--show-text",
                        "--now", TODAY.isoformat()]) == 0
    row, = json.loads(capsys.readouterr().out)["handoffs"]
    assert row["now_mode"] == "fixed" and row["binary"]["packed"]["scheduled_guard"] == "withheld"
    assert row["binary"]["packed"]["post_as_of_rows_withheld"] == 1
    assert "Scheduled row." not in row["texts"]["binary"]


def test_replay_reports_an_analyst_section_written_as_an_h3(tmp_path, capsys):
    """pipe_0f2b's binary calls are an H3 ("### Part 1 — Forecasts (12 binary calls …)") under
    a body H2: the metric reads the analyst-class sub-headings when no H2 is analyst-class."""
    import scripts.context_pack_replay as replay

    handoff = _write_handoff(tmp_path)
    (handoff / "research_report.md").write_text(DOSSIER.replace(
        "## Resolution-ready forecasts\n\n", "## Market outlook\n\n### Resolution-ready forecasts\n\n"),
        encoding="utf-8")
    assert replay.main(["--handoff", str(handoff), "--json", "--now", TODAY.isoformat()]) == 0
    row, = json.loads(capsys.readouterr().out)["handoffs"]
    assert row["analyst_level"] == "sub_heading" and row["analyst_sections"] == 1
    binary = row["binary"]
    assert binary["packed"]["analyst_section_present"] is True
    assert binary["packed"]["analyst_headings"] == [
        {"heading": "### Resolution-ready forecasts", "present": True}]
    assert binary["legacy"]["analyst_section_present"] is False


def test_replay_newest_row_metric_catches_a_lane_ordering_bug(tmp_path, monkeypatch, capsys):
    """The newest past row is found without the lane code, so a lane that sorts oldest first
    (and so drops the newest row past its item cap) fails the metric."""
    import scripts.context_pack_replay as replay

    handoff = _write_handoff(tmp_path)
    (handoff / "timeline.json").write_text(json.dumps(
        [{"date": _day(-i), "event": f"Development number {i:02d} of the review."}
         for i in range(1, 21)]), encoding="utf-8")
    monkeypatch.setattr(cp, "_past_sorted", lambda rows: sorted(
        rows, key=lambda r: (r[2].end, r[2].start, r[1])))
    assert replay.main(["--handoff", str(handoff), "--json", "--now", TODAY.isoformat()]) == 0
    payload = json.loads(capsys.readouterr().out)
    row, = payload["handoffs"]
    assert row["newest_past_row"]["date"] == _day(-1)
    assert row["newest_past_row"]["probe"] == "Development number 01 of the review."
    assert row["binary"]["packed"]["newest_past_row_in_lane"] is False
    assert row["spine"]["packed"]["newest_past_row_in_lane"] is False
    assert payload["summary"]["binary"]["newest_past_row_in_every_lane"] is False


@pytest.mark.parametrize("bad", ["2026-13-01", "yesterday", ""])
def test_replay_rejects_an_invalid_now_with_a_usage_error(tmp_path, capsys, bad):
    import scripts.context_pack_replay as replay

    handoff = _write_handoff(tmp_path)
    with pytest.raises(SystemExit) as exc:
        replay.main(["--handoff", str(handoff), "--now", bad])
    assert exc.value.code == 2
    assert "expected 'as_of' or a YYYY-MM-DD date" in capsys.readouterr().err
