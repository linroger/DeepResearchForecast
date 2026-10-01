"""REPORT-13 (C09): the counter-case pass inside ReportAgent.

``_run_counter_case`` (called in generate_report right after the spine is pinned) makes one
strong-tier call over the [S#] evidence packet and writes reports/<id>/counter_case.json; its
validated triggers join forecast.indicators and the How-to-Verify table (suffixed
"counter-case review [S#]"), forecast.counter_case records the artifact sha256, and the
strongest cited claims reach the Part-2 synthesis prompt. Probabilities never move. With
REPORT_COUNTER_CASE off there is no extra call and forecast.json, the Part-2 prompt and the
resolution section are byte-identical to a run without the hook.

Offline: a FakeLLMClient router (spine / binary / counter-case replies) and the
_derive_and_pin_forecast_spine -> _run_counter_case -> _finalize_structured_forecast ->
_append_resolution_section -> _build_part2_synthesis sequence of a ReportAgent built with
__new__ (the harness of test_question_spec_downstream).
"""

from __future__ import annotations

import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from app.config import Config
from app.services import forecast_counter_case as fc
from app.services import forecast_ledger
from app.services.report_agent import ReportAgent, ReportManager, ReportStatus
from tests.conftest import FakeLLMClient

QUESTION = "Will global electric car sales keep rising through 2027?"
SIM_SENTINEL = "SIMULATION-SIGNAL-PACK-SENTINEL"

SOURCES = [
    {"title": "Global EV Outlook 2026", "url": "https://www.iea.org/reports/global-ev-outlook-2026",
     "supports": ["Global electric car sales reached 17 million units in 2024, led by China."]},
    {"title": "Battery pack price survey", "url": "https://about.bnef.com/blog/battery-pack-prices-2025",
     "supports": ["Average lithium-ion pack prices fell to 115 dollars per kilowatt-hour."]},
    {"title": "Grid interconnection queues", "url": "https://emp.lbl.gov/reports/queued-up-2025",
     "supports": ["Interconnection queues lengthened across most regional grids."]},
]
RESEARCH = (
    "# Dossier\n\n## Demand\n\n"
    "Global electric car sales reached 17 million units in 2024, led by China [S1].\n\n"
    "## Costs\n\nAverage lithium-ion pack prices fell to 115 dollars per kilowatt-hour [S2].\n\n"
    "## Grid\n\nInterconnection queues lengthened across most regional grids [S3].\n\n"
    "## References\n\n- [S1] Global EV Outlook 2026\n- [S2] Battery pack price survey")
ACTORS = {"as_of_date": "2026-09-01", "forecast_inputs": {"indicators": [
    {"indicator": "Quarterly EV registrations", "signals_what": "demand",
     "date_or_trigger": "2027-03-31", "discriminates": "Upside path"}]}}

SPINE_REPLY = {"headline": "h", "horizon": "2027", "confidence": "medium", "scenarios": [
    {"name": name, "probability": p, "summary": f"{name} summary", "key_drivers": ["driver"],
     "resolution_criteria": f"{name} resolves on the IEA estimate for 2027-12-31"}
    for name, p in (("Upside path", 0.5), ("Downside path", 0.3), ("Other / Status Quo", 0.2))]}
BINARY_REPLY = {"binary_forecasts": [{
    "id": "F1", "statement": "Electric car sales exceed 25 million units in 2027", "probability": 0.3,
    "resolution_criteria": "The IEA estimate shows at least 25 million units on 2027-12-31",
    "theme": "t1", "horizon_year": 2027}]}
COUNTER_REPLY = {"targets": [
    {"scenario": "Upside path",
     "case_for_higher": [
         {"text": "Global electric car sales reached 17 million units in 2024, led by China.",
          "sources": ["S1"]},
         {"text": "Momentum alone justifies 65% for this path", "sources": ["S1"]}],
     "case_for_lower": [
         {"text": "Interconnection queues lengthened across most regional grids.", "sources": ["S3"]},
         {"text": "A regulator memo will block sales next year", "sources": ["S42"]}],
     "what_would_change": [
         {"signal": "Annual electric car sales", "direction": "raises",
          "threshold_or_event": "above 25 million units", "by": "2027-12-31", "sources": ["S1"]},
         {"signal": "Vague sentiment shift", "direction": "lowers",
          "threshold_or_event": "the mood sours", "by": "", "sources": ["S1"]}]},
    {"scenario": "Downside path",
     "case_for_lower": [
         {"text": "Average lithium-ion pack prices fell to 115 dollars per kilowatt-hour.",
          "sources": ["S2"]}],
     "what_would_change": [
         {"signal": "Battery pack prices", "direction": "raises",
          "threshold_or_event": "back above 140 dollars per kilowatt-hour", "by": "",
          "sources": ["[S2]", "S77"]}]},
]}


def _is_counter_case(messages):
    return messages[0].get("role") == "system" and messages[0]["content"].startswith(fc._SYSTEM_RULES)


class _RouterLLM(FakeLLMClient):
    """chat_json by prompt: counter-case -> COUNTER_REPLY, binary draw -> one binary, else the spine."""

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, tier=None, **kwargs):
        super().chat_json(messages, temperature=temperature, max_tokens=max_tokens, tier=tier, **kwargs)
        if _is_counter_case(messages):
            return json.loads(json.dumps(COUNTER_REPLY))
        if "[Research dossier]" in messages[-1]["content"]:
            return json.loads(json.dumps(BINARY_REPLY))
        return json.loads(json.dumps(SPINE_REPLY))


def _agent(llm):
    agent = ReportAgent.__new__(ReportAgent)
    for key, value in {
        "llm": llm, "graph_id": "g1", "simulation_id": "sim_counter_case",
        "simulation_requirement": QUESTION, "situation_brief": "Sales are growing quickly.",
        "actors": json.loads(json.dumps(ACTORS)), "sources": json.loads(json.dumps(SOURCES)),
        "research_report": RESEARCH, "timeline_events": [], "quantitative": [],
        "output_language": "English", "scenario_label": "", "base_simulation_id": None,
        "_background_block": "", "_signal_pack": SIM_SENTINEL, "_market_pack": "",
        "_contested_table_block": "", "_forecast_spine": None, "_forecast_spine_block": "",
        "_retrieval_query": None, "_outline_degraded": False, "_outline_summary": "",
        "_section_tool_calls": 0, "report_logger": None, "console_logger": None, "tools": {},
        "hindcast": None, "_hindcast_pin_cache": None, "evaluation_context": None,
        "_evaluation_context_looked_up": True, "_evaluation_context_lookup": None,
        "backbone_check_policy": None,
    }.items():
        setattr(agent, key, value)
    agent._sources_index, agent._citation_index = agent._build_sources_index()
    return agent


@pytest.fixture
def report_env(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path / "sims"), raising=False)
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
        "REPORT_CHRONOLOGY_ASOF_SPLIT": False, "REPORT_VERIFIED_FACTS_BLOCK": False,
        "REPORT_COUNTER_CASE_EVIDENCE_CHARS": 12000,
    }.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    monkeypatch.setattr(forecast_ledger, "append_forecast", lambda forecast, **kw: None)
    return tmp_path


def _path(root, report_id, name):
    return os.path.join(str(root), "reports", report_id, name)


def _read(root, report_id, name):
    with open(_path(root, report_id, name), encoding="utf-8") as fh:
        return fh.read()


BODY = "# T\n\n## Demand outlook\n\nElectric car sales keep rising across major markets.\n"


def _report(root, monkeypatch, report_id, *, flag, hook=True):
    """Spine, the counter-case hook, final forecast.json, the resolution section and the
    Part-2 prompt. ``hook=False`` replays the sequence without the REPORT-13 hook at all."""
    monkeypatch.setattr(Config, "REPORT_COUNTER_CASE", flag, raising=False)
    llm = _RouterLLM()
    agent = _agent(llm)
    os.makedirs(os.path.join(str(root), "reports", report_id), exist_ok=True)
    agent._derive_and_pin_forecast_spine(report_id)
    spine = json.loads(json.dumps(agent._forecast_spine))
    if hook:
        agent._run_counter_case(report_id)
    spine_after_hook = json.loads(json.dumps(agent._forecast_spine))
    counter_calls = [c for c in llm.calls if _is_counter_case(c["messages"])]
    agent._finalize_structured_forecast(report_id, BODY)
    forecast_text = _read(root, report_id, "forecast.json")
    report = SimpleNamespace(markdown_content=BODY)
    agent._append_resolution_section(report_id, report)
    full = _read(root, report_id, "full_report.md")
    assert full == report.markdown_content
    agent._build_part2_synthesis(report.markdown_content)
    part2_prompt = llm.calls[-1]["messages"][-1]["content"]
    assert llm.calls[-1]["kind"] == "chat"
    return SimpleNamespace(agent=agent, llm=llm, spine=spine, spine_after_hook=spine_after_hook,
                           counter_calls=counter_calls,
                           forecast_text=forecast_text, forecast=json.loads(forecast_text),
                           full=full, part2=part2_prompt)


def test_off_is_identical(report_env, monkeypatch):
    baseline = _report(report_env, monkeypatch, "r_base", flag=False, hook=False)
    off = _report(report_env, monkeypatch, "r_off", flag=False)
    assert len(off.llm.calls) == len(baseline.llm.calls) and off.counter_calls == []
    assert [c["messages"] for c in off.llm.calls] == [c["messages"] for c in baseline.llm.calls]
    assert off.forecast_text == baseline.forecast_text
    assert off.part2 == baseline.part2
    assert off.full == baseline.full
    assert "counter_case" not in off.forecast
    assert all(row.get("source") != "counter_case" for row in off.forecast.get("indicators") or [])
    assert not os.path.exists(_path(report_env, "r_off", "counter_case.json"))
    assert off.agent._counter_case is None and off.agent._counter_case_sha256 is None
    # Off or on, the hook never runs without a pinned spine.
    monkeypatch.setattr(Config, "REPORT_COUNTER_CASE", True, raising=False)
    llm = _RouterLLM()
    bare = _agent(llm)
    bare._run_counter_case("r_nospine")
    assert llm.calls == [] and bare._counter_case is None


def test_on_outputs(report_env, monkeypatch):
    off = _report(report_env, monkeypatch, "r_off2", flag=False)
    on = _report(report_env, monkeypatch, "r_on", flag=True)

    # Exactly one extra LLM call, the counter-case call, with no simulation input in it.
    assert len(on.llm.calls) == len(off.llm.calls) + 1
    (call,) = on.counter_calls
    assert (call["kind"], call["temperature"], call["max_tokens"], call["tier"]) == (
        "chat_json", 0.1, 3000, None)
    prompt_text = "\n".join(m["content"] for m in call["messages"])
    assert SIM_SENTINEL not in prompt_text
    assert "[S1] Global EV Outlook 2026" in prompt_text
    assert "Global electric car sales reached 17 million units in 2024, led by China [S1]." in prompt_text

    # Published probabilities are untouched.
    assert on.spine == off.spine and on.spine_after_hook == on.spine
    assert on.forecast["scenarios"] == off.forecast["scenarios"]
    assert on.forecast["binary_forecasts"] == off.forecast["binary_forecasts"]

    # counter_case.json (schema v1) and its sha256 in forecast.json.
    with open(_path(report_env, "r_on", "counter_case.json"), "rb") as fh:
        artifact_bytes = fh.read()
    artifact = json.loads(artifact_bytes)
    assert artifact["schema"] == "drf.counter_case/v1" and artifact["status"] == "complete"
    summary = on.forecast["counter_case"]
    assert summary == {
        "schema": "drf.counter_case/v1", "status": "complete", "artifact": "counter_case.json",
        "artifact_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "claims_valid": 3, "claims_unverifiable": 0, "claims_dropped": 2, "triggers": 2}
    assert artifact["dropped"] == {"unknown_source": 1, "unverified_number": 1}
    assert artifact_bytes.decode("utf-8") == fc.artifact_text(artifact)

    # Only validated claims anywhere downstream.
    claims = [c for t in artifact["targets"] for side in ("higher", "lower") for c in t["claims"][side]]
    assert [c["id"] for c in claims] == ["T1.H1", "T1.L1", "T2.L1"]
    for rejected in ("65%", "regulator memo", "S42", "Vague sentiment", "S77"):
        assert rejected not in on.part2 and rejected not in on.full
        assert rejected not in json.dumps(on.forecast)

    # Triggers join forecast.indicators after the research indicators, each dated or thresholded
    # and citing an admissible [S#].
    indicators = on.forecast["indicators"]
    assert indicators[0] == off.forecast["indicators"][0] == ACTORS["forecast_inputs"]["indicators"][0]
    counter_rows = [row for row in indicators if row.get("source") == "counter_case"]
    assert [(r["indicator"], r["date_or_trigger"], r["discriminates"], r["sources"])
            for r in counter_rows] == [
        ("Annual electric car sales", "2027-12-31", "Upside path", ["S1"]),
        ("Battery pack prices", "back above 140 dollars per kilowatt-hour", "Downside path", ["S2"])]
    for row in counter_rows:
        assert row["sources"] and set(row["sources"]) <= set(on.agent._citation_index)

    # How-to-Verify table: research row unchanged, counter-case rows suffixed with their [S#].
    assert "| Quarterly EV registrations | 2027-03-31 | Upside path |" in on.full
    assert ("| Annual electric car sales (counter-case review [S1]) | 2027-12-31 | Upside path |"
            in on.full)
    assert ("| Battery pack prices (counter-case review [S2]) | back above 140 dollars per "
            "kilowatt-hour | Downside path |") in on.full
    assert on.full.replace(
        "| Annual electric car sales (counter-case review [S1]) | 2027-12-31 | Upside path |\n", ""
    ).replace("\n| Battery pack prices (counter-case review [S2]) | back above 140 dollars per "
              "kilowatt-hour | Downside path |", "") == off.full

    # Part-2 prompt carries the strongest cited claims and the rule.
    header = "[Counter-case: strongest cited arguments against the leading scenarios]\n"
    assert header + fc.render_counter_case_block(artifact, "English") in on.part2
    assert "Address the strongest counter-case explicitly and keep its [S#] markers." in on.part2
    assert ("Case for higher: Global electric car sales reached 17 million units in 2024, "
            "led by China. [S1]") in on.part2
    assert header not in off.part2 and "counter-case" not in off.part2


def test_failed_pass_degrades_to_the_off_outputs(report_env, monkeypatch):
    class _FailingRouter(_RouterLLM):
        def chat_json(self, messages, temperature=0.3, max_tokens=4096, tier=None, **kwargs):
            if _is_counter_case(messages):
                FakeLLMClient.chat_json(self, messages, temperature=temperature,
                                        max_tokens=max_tokens, tier=tier, **kwargs)
                raise RuntimeError("provider down")
            return super().chat_json(messages, temperature=temperature, max_tokens=max_tokens,
                                     tier=tier, **kwargs)

    off = _report(report_env, monkeypatch, "r_off3", flag=False)
    monkeypatch.setattr(Config, "REPORT_COUNTER_CASE", True, raising=False)
    llm = _FailingRouter()
    agent = _agent(llm)
    os.makedirs(os.path.join(str(report_env), "reports", "r_fail"), exist_ok=True)
    agent._derive_and_pin_forecast_spine("r_fail")
    agent._run_counter_case("r_fail")
    artifact = json.loads(_read(report_env, "r_fail", "counter_case.json"))
    assert artifact["status"] == "failed" and "RuntimeError" in artifact["error"]
    agent._finalize_structured_forecast("r_fail", BODY)
    forecast = json.loads(_read(report_env, "r_fail", "forecast.json"))
    assert forecast["counter_case"]["status"] == "failed" and forecast["counter_case"]["triggers"] == 0
    assert forecast["indicators"] == off.forecast["indicators"]
    assert forecast["scenarios"] == off.forecast["scenarios"]
    report = SimpleNamespace(markdown_content=BODY)
    agent._append_resolution_section("r_fail", report)
    assert report.markdown_content == off.full
    agent._build_part2_synthesis(report.markdown_content)
    assert llm.calls[-1]["messages"][-1]["content"] == off.part2


def test_artifact_write_failure_publishes_nothing(report_env, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_COUNTER_CASE", True, raising=False)
    llm = _RouterLLM()
    agent = _agent(llm)
    os.makedirs(os.path.join(str(report_env), "reports", "r_nowrite"), exist_ok=True)
    agent._derive_and_pin_forecast_spine("r_nowrite")

    def _refuse(path, text, **kwargs):
        raise OSError("read-only disk")

    import app.services.report_agent as report_agent_module
    monkeypatch.setattr(report_agent_module, "write_text_atomic", _refuse)
    agent._run_counter_case("r_nowrite")
    assert agent._counter_case is None and agent._counter_case_sha256 is None
    assert not os.path.exists(_path(report_env, "r_nowrite", "counter_case.json"))
    assert agent._with_counter_case_indicators([]) == []


def test_generate_report_runs_the_hook_right_after_the_spine(report_env, monkeypatch):
    for name, value in (("REPORT_STRUCTURED_FORECAST", True), ("REPORT_FORECAST_SPINE_FIRST", True),
                        ("REPORT_SIGNAL_PACK", False), ("LLM_TELEMETRY_ENABLED", False)):
        monkeypatch.setattr(Config, name, value, raising=False)
    calls = []
    agent = _agent(FakeLLMClient())
    agent._derive_and_pin_forecast_spine = lambda report_id: calls.append(("spine", report_id))
    agent._run_counter_case = lambda report_id: calls.append(("counter_case", report_id))
    agent._commit_forecast_ledger = lambda *a, **k: None

    def _outline(progress_callback=None, forecast_spine_block="", require_forecast_structure=False):
        calls.append(("outline", None))
        raise RuntimeError("stop after planning")

    agent.plan_outline = _outline
    report = agent.generate_report(report_id="r_order")
    assert report.status == ReportStatus.FAILED
    assert calls == [("spine", "r_order"), ("counter_case", "r_order"), ("outline", None)]
