"""TIME-5: the numeric guard wired into binary extraction and ReportAgent finalization.

NUMERIC_GUARD_MODE=off keeps the binary prompt, the extracted rows and forecast.json exactly
as before (the extractor is not even passed the mode and the stamp never runs).  Shadow (the
default) asks each binary draw for an optional latest_actual, keeps it sanitized, stamps every
binary with numeric_guard and summarises in forecast.quality.numeric_guards -- while the Part-1
binary table, the publish-gate result and binary_quality stay identical to the off run.
Offline: FakeLLMClient routed by prompt, no network.
"""

import copy
import json
import os

import pytest

from app.config import Config
from app.services import forecast_extractor as fe
from app.services import report_agent as ra
from app.services.report_agent import ReportAgent, ReportManager
from app.utils import numeric_guards as ng
from tests.conftest import FakeLLMClient

_F13 = {
    "id": "F1",
    "statement": "US single-year data-centre capex falls below $1.5 trillion by end-2027",
    "probability": 0.22,
    "resolution_criteria": "Reported US data-centre capex for calendar 2027 per company filings, "
                           "resolved on 2028-03-31",
    "resolution_source": "Company filings",
    "theme": "capex",
    "horizon_year": 2027,
    "base_rate_anchor": "Capex compounded above 30% a year since 2023.",
    "adjustment_rationale": "Hyperscaler guidance points to continued acceleration.",
    "source": "research-prior",
    "latest_actual": {"value": "735–760", "unit": "USD billion", "as_of": "2026-02-01",
                      "source_ref": "S3", "note": "dropped by the sanitizer"},
}
_CPI = {
    "id": "F2", "statement": "US CPI inflation exceeds 3% in December 2027", "probability": 0.8,
    "resolution_criteria": "BLS CPI-U YoY above 3.0% for December 2027", "resolution_source": "BLS",
    "theme": "inflation", "horizon_year": 2027, "base_rate_anchor": "b",
    "adjustment_rationale": "a", "source": "research-prior", "latest_actual": None,
}
_CEASEFIRE = {
    "id": "F3", "statement": "A Russia-Ukraine ceasefire is signed by December 2027",
    "probability": 0.15, "resolution_criteria": "Signed ceasefire reported by Reuters by 2027-12-31",
    "resolution_source": "Reuters", "theme": "geopolitics", "horizon_year": 2027,
    "base_rate_anchor": "b", "adjustment_rationale": "a", "source": "research-prior",
}
_SPINE = {"headline": "h", "horizon": "2030", "confidence": "medium", "scenarios": [
    {"name": name, "probability": p, "summary": f"{name} summary", "key_drivers": ["driver"],
     "resolution_criteria": f"{name} resolves if capex is above ${10 + i} billion by 2030"}
    for i, (name, p) in enumerate(zip(("Rapid build-out", "Gradual build-out", "Other / Status Quo"),
                                      (0.5, 0.3, 0.2), strict=True))]}
_QUANT = [{"metric": "US CPI inflation", "value": "2.9", "unit": "%", "as_of_date": "2026-08-31",
           "value_type": "actual", "source_ref": "S5"}]


class _RoutedLLM(FakeLLMClient):
    """FakeLLMClient whose chat_json answers binary draws with ``binaries`` and anything else
    with the scenario spine; every call is recorded (FakeLLMClient.calls)."""

    def __init__(self, binaries):
        super().__init__()
        self.binaries = binaries

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, tier=None, **kwargs):
        super().chat_json(messages, temperature=temperature, max_tokens=max_tokens, tier=tier)
        content = messages[-1]["content"]
        if "[Research dossier]" in content and "binary_forecasts" in content:
            return {"binary_forecasts": copy.deepcopy(self.binaries)}
        return copy.deepcopy(_SPINE)

    def binary_prompts(self):
        return [call["messages"][-1]["content"] for call in self.calls
                if "[Research dossier]" in call["messages"][-1]["content"]]


def _agent(llm, **over):
    a = ReportAgent.__new__(ReportAgent)
    defaults = {
        "graph_id": "g1", "simulation_id": "sim1", "llm": llm,
        "simulation_requirement": "Will US data-centre capex keep accelerating through 2027?",
        "situation_brief": "", "actors": None, "sources": [],
        "research_report": "# Dossier\n\nUS data-centre capex reached $735-760 billion in 2025 [S3].",
        "output_language": "English", "scenario_label": "", "base_simulation_id": None,
        "_background_block": "", "_sources_index": "", "_signal_pack": "",
        "_market_pack": "", "_forecast_spine": None, "_forecast_spine_block": "",
        "_retrieval_query": None, "_outline_degraded": False, "_outline_summary": "",
        "_section_tool_calls": 0, "report_logger": None, "console_logger": None,
        "tools": {}, "quantitative": _QUANT,
    }
    defaults.update(over)
    for key, value in defaults.items():
        setattr(a, key, value)
    return a


@pytest.fixture
def report_env(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(tmp_path / "ledger"), raising=False)
    monkeypatch.setattr(Config, "REPORT_REPAIR_PASSES", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_SELF_CRITIQUE", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 1, raising=False)
    monkeypatch.setattr(Config, "FORECAST_EMIT_BINARY", True, raising=False)
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", False, raising=False)
    monkeypatch.setattr(Config, "FORECAST_BINARY_THEMES", None, raising=False)
    monkeypatch.setattr(Config, "BINARY_FORECASTS_MIN_COUNT", 3, raising=False)
    return tmp_path


def _forecast_bytes(tmp_path, report_id):
    with open(os.path.join(str(tmp_path), "reports", report_id, "forecast.json"),
              encoding="utf-8") as handle:
        return handle.read()


def _run(monkeypatch, tmp_path, report_id, mode, binaries=(_F13, _CPI, _CEASEFIRE), **agent_over):
    monkeypatch.setattr(Config, "NUMERIC_GUARD_MODE", mode, raising=False)
    llm = _RoutedLLM(list(binaries))
    agent = _agent(llm, **agent_over)
    agent._finalize_structured_forecast(report_id, "# Report\n\nBody [S3].")
    text = _forecast_bytes(tmp_path, report_id)
    return json.loads(text), text, llm


def _strip_time5(forecast):
    out = copy.deepcopy(forecast)
    quality = out.get("quality") or {}
    quality.pop("numeric_guards", None)
    if not quality:
        out.pop("quality", None)
    for binary in out.get("binary_forecasts") or []:
        binary.pop("numeric_guard", None)
        binary.pop("latest_actual", None)
    return out


def _gate(forecast):
    gated = ReportAgent._apply_publish_gate(copy.deepcopy(forecast))
    quality = dict(gated.get("quality") or {})
    quality.pop("numeric_guards", None)
    return gated.get("confidence"), quality


# ── extractor level ───────────────────────────────────────────────────────────
def test_extractor_off_is_identical_to_the_pre_change_call():
    responses = [{"binary_forecasts": [copy.deepcopy(_F13), copy.deepcopy(_CPI)]}] * 4
    baseline_llm = FakeLLMClient(json_responses=copy.deepcopy(responses))
    baseline = fe.extract_binary_forecasts("# Dossier\n\nBody.", baseline_llm, min_count=2)
    for mode in (None, "off", "OFF", "enforce"):
        llm = FakeLLMClient(json_responses=copy.deepcopy(responses))
        out = fe.extract_binary_forecasts("# Dossier\n\nBody.", llm, min_count=2,
                                          numeric_guard_mode=mode)
        assert [c["messages"] for c in llm.calls] == [c["messages"] for c in baseline_llm.calls], mode
        assert json.dumps(out, sort_keys=True) == json.dumps(baseline, sort_keys=True), mode
        assert "latest_actual" not in llm.calls[0]["messages"][0]["content"]
        assert all("latest_actual" not in b for b in out["binary_forecasts"])


def test_extractor_shadow_asks_for_and_keeps_a_sanitized_latest_actual(monkeypatch):
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)
    long_unit = dict(_CPI, latest_actual={"value": 2.9, "unit": "%" + "x" * 100, "as_of": "2026-08-31",
                                          "source_ref": "S5"})
    llm = FakeLLMClient(json_responses=[{"binary_forecasts": [copy.deepcopy(_F13), long_unit,
                                                              dict(_CEASEFIRE, latest_actual="n/a")]}])
    out = fe.extract_binary_forecasts("# Dossier\n\nBody.", llm, min_count=2, numeric_guard_mode="shadow",
                                      market_pack="| m1 | Will X | 0.40 |")
    prompt = llm.calls[0]["messages"][0]["content"]
    assert fe._BINARY_LATEST_ACTUAL_RULE in prompt and '"latest_actual"' in prompt
    # appended after the market rule, before the dossier
    assert prompt.index(fe._BINARY_MARKET_RULE) < prompt.index(fe._BINARY_LATEST_ACTUAL_RULE) < prompt.index(
        "[Research dossier]")
    rows = {b["id"]: b for b in out["binary_forecasts"]}
    assert rows["F1"]["latest_actual"] == {"value": "735–760", "unit": "USD billion",
                                           "as_of": "2026-02-01", "source_ref": "S3"}
    assert rows["F2"]["latest_actual"] == {"value": "2.9", "unit": ("%" + "x" * 100)[:80],
                                           "as_of": "2026-08-31", "source_ref": "S5"}
    assert "latest_actual" not in rows["F3"]
    assert "numeric_guard" not in rows["F1"]  # stamping belongs to ReportAgent, not the extractor


# ── ReportAgent finalization ─────────────────────────────────────────────────
def test_mode_off_leaves_prompt_forecast_and_call_shape_unchanged(monkeypatch, report_env):
    seen = {}
    real_ebf = fe.extract_binary_forecasts

    def spy(*args, **kwargs):
        seen["kwargs"] = set(kwargs)
        return real_ebf(*args, **kwargs)

    def no_stamp(*args, **kwargs):
        raise AssertionError("the numeric guard must not run in off mode")

    monkeypatch.setattr(fe, "extract_binary_forecasts", spy)
    monkeypatch.setattr(ng, "stamp_forecast", no_stamp)
    fc, text, llm = _run(monkeypatch, report_env, "report_off", "off")
    assert "numeric_guard_mode" not in seen["kwargs"]  # the pre-change call shape
    assert all("latest_actual" not in p for p in llm.binary_prompts())
    assert "numeric_guard" not in text and "latest_actual" not in text
    assert "numeric_guards" not in (fc.get("quality") or {})
    assert all("numeric_guard" not in b and "latest_actual" not in b for b in fc["binary_forecasts"])


def test_shadow_stamps_and_leaves_markdown_gate_and_binary_quality_unchanged(monkeypatch, report_env):
    off, _off_text, off_llm = _run(monkeypatch, report_env, "report_off", "off")
    shadow, _text, llm = _run(monkeypatch, report_env, "report_shadow", "shadow")

    prompts = llm.binary_prompts()
    assert prompts and all(fe._BINARY_LATEST_ACTUAL_RULE in p for p in prompts)
    rows = {b["id"]: b for b in shadow["binary_forecasts"]}
    assert rows["F1"]["latest_actual"] == {"value": "735–760", "unit": "USD billion",
                                           "as_of": "2026-02-01", "source_ref": "S3"}
    documented = {"ok", "flagged", "unbound", "not_numeric", "unchecked"}
    assert all(b["numeric_guard"]["schema"] == 1 and b["numeric_guard"]["status"] in documented
               for b in shadow["binary_forecasts"])
    f13 = rows["F1"]["numeric_guard"]
    assert f13["status"] == "flagged"
    assert [f["code"] for f in f13["findings"]] == ["status_quo_contradiction"]
    assert f13["latest_actual"]["basis"] == "llm_field"
    cpi = rows["F2"]["numeric_guard"]  # bound from the research quant rows
    assert cpi["status"] == "ok" and cpi["latest_actual"]["basis"] == "quant_row"
    assert rows["F3"]["numeric_guard"]["status"] == "not_numeric"

    summary = shadow["quality"]["numeric_guards"]
    assert summary["mode"] == "shadow" and summary["status"] == "ran"
    assert (summary["n_binaries"], summary["n_numeric"], summary["n_bound"]) == (3, 2, 2)
    assert summary["by_status"] == {"flagged": 1, "ok": 1, "not_numeric": 1}
    assert summary["findings_by_code"] == {"status_quo_contradiction": 1}
    assert summary["scenario_findings"] == []

    # Part-1 markdown, publish gate and binary_quality are exactly the off run's
    assert fe.render_binary_forecasts_block(shadow, language="English") == \
        fe.render_binary_forecasts_block(off, language="English")
    assert _gate(shadow) == _gate(off)
    assert shadow["binary_quality"] == off["binary_quality"]
    assert [b["probability"] for b in shadow["binary_forecasts"]] == \
        [b["probability"] for b in off["binary_forecasts"]]
    assert _strip_time5(shadow) == _strip_time5(off)
    # no extra LLM call: the latest_actual rides on the existing binary draw
    assert len(llm.calls) == len(off_llm.calls)


def test_shadow_with_no_binaries_records_not_run(monkeypatch, report_env):
    fc, _text, _ = _run(monkeypatch, report_env, "report_empty", "shadow", binaries=())
    assert "binary_forecasts" not in fc
    guards = fc["quality"]["numeric_guards"]
    assert guards["status"] == "not_run" and guards["n_binaries"] == 0
    monkeypatch.setattr(Config, "FORECAST_EMIT_BINARY", False, raising=False)
    fc, _text, _ = _run(monkeypatch, report_env, "report_no_emit", "shadow")
    assert fc["quality"]["numeric_guards"]["status"] == "not_run"


def test_stamp_failure_is_recorded_and_finalization_completes(monkeypatch, report_env):
    def boom(*args, **kwargs):
        raise RuntimeError("injected")

    monkeypatch.setattr(ng, "stamp_forecast", boom)
    fc, _text, _ = _run(monkeypatch, report_env, "report_error", "shadow")
    assert fc["quality"]["numeric_guards"] == {"mode": "shadow", "status": "error", "error": "RuntimeError"}
    assert len(fc["binary_forecasts"]) == 3 and fc["scenarios"]


def test_pinned_agent_mode_beats_ambient_config_and_invalid_mode_warns(monkeypatch, report_env):
    fc, text, llm = _run(monkeypatch, report_env, "report_pinned_off", "shadow", _numeric_guard_mode="off")
    assert "numeric_guard" not in text and all("latest_actual" not in p for p in llm.binary_prompts())
    fc, _text, _ = _run(monkeypatch, report_env, "report_pinned_on", "off", _numeric_guard_mode="shadow")
    assert fc["quality"]["numeric_guards"]["status"] == "ran"

    warnings = []
    monkeypatch.setattr(ra.logger, "warning", lambda msg, *a, **k: warnings.append(str(msg)))
    assert ReportAgent._normalize_numeric_guard_mode("enforce") == "shadow"
    assert warnings and "NUMERIC_GUARD_MODE" in warnings[0]
    assert ReportAgent._normalize_numeric_guard_mode("OFF") == "off"
    monkeypatch.setattr(Config, "NUMERIC_GUARD_MODE", "off", raising=False)
    assert ReportAgent._normalize_numeric_guard_mode() == "off"
    import inspect
    parameter = inspect.signature(ReportAgent.__init__).parameters["numeric_guard_mode"]
    assert parameter.default is None


def test_hindcast_run_judges_future_actuals_against_its_as_of(monkeypatch, report_env):
    seen = {}
    real = ng.stamp_forecast

    def spy(forecast, **kwargs):
        seen.update(kwargs)
        return real(forecast, **kwargs)

    monkeypatch.setattr(ng, "stamp_forecast", spy)
    monkeypatch.setattr(ReportAgent, "_hindcast_pin", lambda self: {"as_of": "2026-01-15"})
    monkeypatch.setattr(ra, "hindcast_forecast_block", lambda pin, **kw: {"as_of": pin["as_of"]})
    fc, _text, _ = _run(monkeypatch, report_env, "report_hindcast", "shadow")
    assert str(seen["today"]) == "2026-01-15"
    f13 = next(b for b in fc["binary_forecasts"] if b["id"] == "F1")["numeric_guard"]
    # the drafted actual is dated 2026-02-01, after the as_of: it never binds
    assert f13["status"] == "unbound" and f13["latest_actual"] is None


def test_env_example_documents_the_three_knobs():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, ".env.example"), encoding="utf-8") as handle:
        text = handle.read()
    for line in ("# NUMERIC_GUARD_MODE=shadow ", "# NUMERIC_GUARD_SCALE_RATIO=300 ",
                 "# NUMERIC_GUARD_STATUS_QUO_MARGIN=0.25 "):
        assert line in text, line
    assert Config.NUMERIC_GUARD_MODE == "shadow"
    assert (Config.NUMERIC_GUARD_SCALE_RATIO, Config.NUMERIC_GUARD_STATUS_QUO_MARGIN) == (300.0, 0.25)
