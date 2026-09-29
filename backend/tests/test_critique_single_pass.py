"""INFRA-2: the red-team critique runs at most once per report (REPORT_CRITIQUE_SINGLE_PASS).

Before: a failed or reverted pre-prose critique (report_agent._derive_and_pin_forecast_spine)
left the spine un-``critiqued``, so _finalize_structured_forecast ran the critic a second time
after the prose was written: double cost, and a post-hoc probability move the prose did not
defend. Now self_critique_forecast stamps ``critique_attempted`` once the critic LLM has been
called (after the call, so prompts and cache keys are unchanged) and a later call on an
attempted-but-not-critiqued forecast makes no LLM call and records
``quality.critique_pre_prose='reverted_or_failed'``. Flag off: legacy double critique, no stamp.

Offline: FakeLLMClient-based stubs; no network, no real LLM.
"""

import json
import os

import pytest

from app.config import Config
from app.services import forecast_extractor as fe
from app.services.report_agent import ReportAgent, ReportManager
from tests.conftest import FakeLLMClient

_NAMES = ("Rapid adoption path", "Gradual adoption path", "Other / Status Quo")


def _rows(probs):
    return [
        {"name": name, "probability": p, "summary": f"{name} summary",
         "key_drivers": ["driver"],
         "resolution_criteria": f"{name} resolves if the index is above {10 + i}% by 2030"}
        for i, (name, p) in enumerate(zip(_NAMES, probs, strict=True))
    ]


def _forecast(probs=(0.5, 0.3, 0.2)):
    return {"headline": "Adoption outlook", "horizon": "2030", "confidence": "medium",
            "confidence_rationale": "Evidence is mixed.", "key_uncertainties": ["policy"],
            "scenarios": _rows(list(probs)), "schema_version": 1}


class _RouterLLM(FakeLLMClient):
    """FakeLLMClient whose chat_json reply is chosen by the prompt; every call is recorded."""

    def __init__(self, router):
        super().__init__()
        self._router = router

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, tier=None, **kwargs):
        super().chat_json(messages, temperature=temperature, max_tokens=max_tokens, tier=tier,
                          **kwargs)
        reply = self._router(messages[-1]["content"])
        if isinstance(reply, Exception):
            raise reply
        return reply


def _critic_calls(llm):
    return [c for c in llm.calls if c["kind"] == "chat_json"
            and c["messages"][0]["content"].startswith(fe._CRITIQUE_INSTRUCTIONS)]


def _critic(reply):
    return _RouterLLM(lambda content: reply)


@pytest.fixture
def single_pass(monkeypatch):
    def _set(on=True):
        monkeypatch.setattr(Config, "REPORT_CRITIQUE_SINGLE_PASS", on, raising=False)
    _set(True)
    return _set


# ------------------------------------------------------------------ self_critique_forecast
@pytest.mark.parametrize("reply", [{}, {"scenarios": []}, ["not", "a", "dict"],
                                   ValueError("LLM返回的JSON格式无效")])
def test_failed_critique_stamps_input_and_second_call_is_free(single_pass, reply):
    forecast = _forecast()
    llm = _critic(reply)

    first = fe.self_critique_forecast(forecast, llm)
    assert first is forecast and forecast["critique_attempted"] is True
    assert "critiqued" not in forecast

    second = fe.self_critique_forecast(dict(forecast), llm)
    assert len(_critic_calls(llm)) == 1
    assert second["quality"]["critique_pre_prose"] == "reverted_or_failed"
    assert second["scenarios"] == forecast["scenarios"]


def test_reverted_critique_is_also_single_pass(single_pass, monkeypatch):
    # A critique whose output fails the scenario contract audit is reverted to the input.
    monkeypatch.setattr(fe, "audit_scenario_contract", lambda forecast: {"valid": False})
    critique = {"scenarios": _rows([0.4, 0.35, 0.25]), "confidence": "low"}
    forecast = _forecast()
    llm = _critic(critique)

    assert fe.self_critique_forecast(forecast, llm) is forecast
    assert forecast["critique_attempted"] is True
    fe.self_critique_forecast(forecast, llm)
    assert len(_critic_calls(llm)) == 1
    assert forecast["quality"]["critique_pre_prose"] == "reverted_or_failed"


def test_successful_critique_stamps_only_the_result(single_pass):
    forecast = _forecast()
    llm = _critic({"scenarios": _rows([0.45, 0.3, 0.25]), "confidence": "low"})

    out = fe.self_critique_forecast(forecast, llm)
    assert out is not forecast
    assert out["critiqued"] is True and out["critique_attempted"] is True
    assert "critique_attempted" not in forecast


def test_stamp_never_reaches_the_critic_or_premortem_prompt(single_pass, monkeypatch):
    prompts = {}
    for on in (True, False):
        single_pass(on)
        llm = _critic({})
        fe.self_critique_forecast(_forecast(), llm)
        prompts[on] = _critic_calls(llm)[0]["messages"]
    assert prompts[True] == prompts[False]

    stamped = {**_forecast(), "critiqued": True, "critique_attempted": True}
    view = fe._llm_forecast_view(stamped)
    assert "critique_attempted" not in view and view["critiqued"] is True
    monkeypatch.setattr(Config, "REPORT_PREMORTEM", True, raising=False)
    premortem = _RouterLLM(lambda content: {})
    fe.premortem_forecast(stamped, premortem)
    assert "critique_attempted" not in premortem.calls[0]["messages"][0]["content"]


def test_flag_off_keeps_legacy_double_critique(single_pass):
    single_pass(False)
    forecast = _forecast()
    llm = _critic({})

    assert fe.self_critique_forecast(forecast, llm) is forecast
    assert "critique_attempted" not in forecast
    fe.self_critique_forecast(forecast, llm)
    assert len(_critic_calls(llm)) == 2
    assert "quality" not in forecast


def test_flag_off_ignores_an_existing_stamp(single_pass):
    single_pass(False)
    forecast = {**_forecast(), "critique_attempted": True}
    llm = _critic({})

    fe.self_critique_forecast(forecast, llm)
    assert len(_critic_calls(llm)) == 1
    assert "quality" not in forecast


def test_needs_review_forecast_is_not_stamped(single_pass, monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_PROB_STRICT_PARSE", True, raising=False)
    forecast = {**_forecast(), "probability_status": fe.PROB_REVIEW}
    llm = _critic({})

    assert fe.self_critique_forecast(forecast, llm) is forecast
    assert llm.calls == [] and "critique_attempted" not in forecast


def test_short_circuit_keeps_existing_quality_without_aliasing(single_pass):
    shared_quality = {"quote_provenance": {"ungrounded": 0}}
    spine = {**_forecast(), "critique_attempted": True, "quality": shared_quality}
    forecast = dict(spine)

    fe.self_critique_forecast(forecast, _critic({}))
    assert forecast["quality"] == {"quote_provenance": {"ungrounded": 0},
                                   "critique_pre_prose": "reverted_or_failed"}
    assert shared_quality == {"quote_provenance": {"ungrounded": 0}}  # the pinned spine is untouched


# ------------------------------------------------------------------ report level
def _agent(llm):
    a = ReportAgent.__new__(ReportAgent)
    defaults = {
        "llm": llm, "graph_id": "g1", "simulation_id": "sim1",
        "simulation_requirement": "Will adoption accelerate?",
        "situation_brief": "", "actors": None, "sources": [], "research_report": "",
        "output_language": "English", "scenario_label": "", "base_simulation_id": None,
        "_background_block": "", "_sources_index": "", "_signal_pack": "",
        "_market_pack": "", "_forecast_spine": None, "_forecast_spine_block": "",
        "_retrieval_query": None, "_outline_degraded": False, "_outline_summary": "",
        "_section_tool_calls": 0, "report_logger": None, "console_logger": None,
        "tools": {},
    }
    for key, value in defaults.items():
        setattr(a, key, value)
    return a


@pytest.fixture
def report_env(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_SELF_CRITIQUE", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_CRITIQUE_BEFORE_PROSE", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_PREMORTEM", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 1, raising=False)
    monkeypatch.setattr(Config, "FORECAST_EMIT_BINARY", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_REPAIR_PASSES", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", False, raising=False)
    return tmp_path


def _run_report(tmp_path, report_id):
    spine = _forecast()

    def router(content):
        if content.startswith(fe._CRITIQUE_INSTRUCTIONS):
            return {}  # the critic reply carries no scenarios: the critique fails
        return json.loads(json.dumps(spine))

    llm = _RouterLLM(router)
    (tmp_path / "reports" / report_id).mkdir(parents=True)
    agent = _agent(llm)
    agent._derive_and_pin_forecast_spine(report_id)
    assert agent._forecast_spine and agent._forecast_spine.get("scenarios")
    agent._finalize_structured_forecast(report_id, "# T\n\nBody text.")
    with open(os.path.join(str(tmp_path), "reports", report_id, "forecast.json"),
              encoding="utf-8") as handle:
        return llm, json.load(handle)


def test_report_runs_the_critic_once_after_a_failed_pre_prose_critique(report_env, single_pass):
    llm, forecast = _run_report(report_env, "report_single_pass")

    assert len(_critic_calls(llm)) == 1
    assert forecast["quality"]["critique_pre_prose"] == "reverted_or_failed"
    assert forecast["critique_attempted"] is True and not forecast.get("critiqued")


def test_report_flag_off_runs_the_legacy_post_hoc_critique(report_env, single_pass):
    single_pass(False)
    llm, forecast = _run_report(report_env, "report_double_pass")

    assert len(_critic_calls(llm)) == 2
    assert "critique_pre_prose" not in (forecast.get("quality") or {})
    assert "critique_attempted" not in forecast
