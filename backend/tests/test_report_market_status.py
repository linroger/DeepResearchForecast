"""REPORT-4 (C): the report records the market slot's typed status.

_load_prediction_markets classifies the research handoff payload (or the report-time
fallback) into self._market_status; _prepend_research_background writes one
market-absence line only when that slot is not present; _finalize_structured_forecast
records forecast.quality.prompt_slot_states.  All offline: PipelineManager and the
Polymarket helpers are monkeypatched, the client stays disabled unless a test opts in.
"""

from __future__ import annotations

import inspect
import json

import pytest

from app.config import Config
from app.services.report_agent import ReportAgent, ReportManager
from app.utils import absence
from app.utils import prediction_markets as pm

_ABSENCE_RULE = "正文不得引用或编造预测市场价格/隐含概率（研究材料中带 [S#] 的数字除外）。"


def _agent(**over):
    a = ReportAgent.__new__(ReportAgent)
    a.simulation_id = "sim1"
    a.simulation_requirement = "Will X happen by 2030?"
    a.situation_brief = ""
    a.actors = {}
    a.sources = []
    a.research_report = ""
    a.output_language = "English"
    a._background_block = "BG"
    a._sources_index = ""
    a._forecast_spine = None
    a._forecast_spine_block = ""
    a._signal_pack = ""
    a._market_pack = ""
    a._prediction_markets = []
    a._markets_stale = False
    a._charts_block = ""
    for k, v in over.items():
        setattr(a, k, v)
    return a


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "true")
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)


@pytest.fixture
def handoff(tmp_path, monkeypatch):
    """A pipeline whose handoff dir is tmp_path; returns a writer for prediction_markets.json."""
    from app.services.pipeline_orchestrator import PipelineManager

    monkeypatch.setattr(PipelineManager, "list_pipelines",
                        classmethod(lambda cls: [{"pipeline_id": "p1"}]))
    monkeypatch.setattr(PipelineManager, "load", classmethod(
        lambda cls, pid: {"simulation_id": "sim1", "handoff_dir": str(tmp_path)}))

    def _write(payload):
        (tmp_path / "prediction_markets.json").write_text(
            json.dumps(payload), encoding="utf-8")
    return _write


def _status(agent):
    agent._load_prediction_markets()
    st = agent._market_status
    return st.state, st.reason


# ------------------------------------------------------------ _load_prediction_markets
def test_handoff_rows_are_present(handoff):
    handoff({"markets": [{"market_id": "m1", "question": "Will A?", "implied_yes_prob": 0.3}],
             "status": {"state": "markets_selected"}})
    a = _agent()
    rows = a._load_prediction_markets()
    assert [r["market_id"] for r in rows] == ["m1"]
    assert (a._market_status.state, a._market_status.reason) == ("present", "research_snapshot")


@pytest.mark.parametrize("payload,expected", [
    ({"markets": [], "no_relevant_markets": True,
      "status": {"empty_reason": "no_equivalent_market", "query_count": 3,
                 "successful_query_count": 1, "transport_failure_count": 2}},
     ("unavailable", "partial_transport_failure")),
    ({"markets": [], "status": {"state": "inflight_timeout",
                                "empty_reason": "no_equivalent_market"}},
     ("unavailable", "inflight_timeout")),
    ({"markets": [], "no_relevant_markets": True,
      "status": {"empty_reason": "no_derivable_queries"}},
     ("empty", "no_derivable_queries")),
    ({"markets": [], "status": {"state": "verified_empty"}}, ("empty", "verified_empty")),
])
def test_handoff_without_rows_mirrors_research_payload(handoff, payload, expected):
    # Client disabled (conftest) -> the fallback returns [] and the handoff status is kept.
    handoff(payload)
    assert _status(_agent()) == expected


def test_no_handoff_file_is_unavailable(handoff):
    assert _status(_agent()) == ("unavailable", "no_market_snapshot")


def test_no_pipeline_is_unavailable(monkeypatch):
    from app.services.pipeline_orchestrator import PipelineManager

    monkeypatch.setattr(PipelineManager, "list_pipelines", classmethod(lambda cls: []))
    assert _status(_agent()) == ("unavailable", "no_market_snapshot")


def test_fallback_exception_is_unavailable(enabled, handoff, monkeypatch):
    handoff({"markets": [], "status": {"state": "verified_empty"}})

    def _boom(*_a, **_k):
        raise RuntimeError("query derivation down")

    monkeypatch.setattr(pm, "derive_market_queries_llm", _boom)
    a = _agent(llm=object())
    assert a._load_prediction_markets() == []
    assert (a._market_status.state, a._market_status.reason) == (
        "unavailable", "report_fallback_error")


def test_fallback_without_queries_keeps_handoff_status(enabled, handoff, monkeypatch):
    handoff({"markets": [], "status": {"state": "verified_empty"}})
    monkeypatch.setattr(pm, "derive_market_queries_llm", lambda *_a, **_k: [])
    a = _agent(llm=object())
    assert a._load_prediction_markets() == []
    assert (a._market_status.state, a._market_status.reason) == ("empty", "verified_empty")


def test_fallback_rows_are_present(enabled, monkeypatch):
    from app.services.pipeline_orchestrator import PipelineManager

    monkeypatch.setattr(PipelineManager, "list_pipelines", classmethod(lambda cls: []))
    monkeypatch.setattr(pm, "derive_market_queries_llm", lambda *_a, **_k: ["q"])
    row = {"market_id": "good", "question": "Will A?", "implied_yes_prob": 0.2, "volume": 900}
    monkeypatch.setattr(pm.PolymarketClient, "snapshot_for_queries", lambda *_a, **_k: [row])
    monkeypatch.setattr(pm, "score_market_relevance",
                        lambda *_a, **_k: [{**row, "relevance_score": 8.0}])
    a = _agent(llm=object())
    assert [r["market_id"] for r in a._load_prediction_markets()] == ["good"]
    assert (a._market_status.state, a._market_status.reason) == ("present", "report_fallback")


def test_market_slot_status_rules(enabled):
    a = _agent()
    assert a._market_slot_status().to_dict()["reason"] == "no_market_snapshot"
    a._market_status = absence.present("research_snapshot")
    assert a._market_slot_status().reason == "market_pack_empty"
    a._market_pack = "table"
    assert a._market_slot_status().state == "present"


def test_market_slot_status_disabled_is_not_run():
    a = _agent(_market_status=absence.present("research_snapshot"), _market_pack="table")
    st = a._market_slot_status()
    assert (st.state, st.reason) == ("not_run", "prediction_markets_disabled")


def test_frozen_status_wins_over_a_later_reload(enabled):
    a = _agent(_market_status=absence.unavailable("report_fallback_error"))
    a._freeze_market_slot_status()
    a._market_status = absence.unavailable("no_market_snapshot")  # a later reload
    assert a._market_slot_status().reason == "report_fallback_error"
    assert a._live_market_slot_status().reason == "no_market_snapshot"


def test_generate_report_freezes_status_right_after_the_market_pack_build():
    src = inspect.getsource(ReportAgent.generate_report)
    build = src.index("self._market_pack = self._build_market_pack()")
    freeze = src.index("self._freeze_market_slot_status()")
    spine = src.index("self._derive_and_pin_forecast_spine(report_id)")
    assert build < freeze < spine
    assert src.count("self._freeze_market_slot_status()") == 1


# ------------------------------------------------------------ _prepend_research_background
def test_prepend_has_absence_line_only_when_not_present(enabled):
    missing = _agent(_market_status=absence.unavailable("partial_transport_failure"))
    out = missing._prepend_research_background("PROMPT")
    line = (absence.absence_marker("预测市场信号", missing._market_slot_status(), "zh")
            + "\n" + _ABSENCE_RULE)
    assert out == "BG\n\n" + line + "\n\nPROMPT"
    assert missing._prepend_research_background("PROMPT") == out  # byte-stable across sections

    present = _agent(_market_status=absence.present("research_snapshot"),
                     _market_pack="【预测市场信号】\n| m1 | 30% |")
    out_p = present._prepend_research_background("PROMPT")
    assert out_p == "BG\n\n【预测市场信号】\n| m1 | 30% |\n\nPROMPT"
    assert _ABSENCE_RULE not in out_p


def test_prepend_never_pairs_a_market_table_with_an_absence_line(enabled):
    a = _agent(_market_status=absence.unavailable("report_fallback_error"),
               _market_pack="【预测市场信号】\n| m1 | 30% |")
    assert _ABSENCE_RULE not in a._prepend_research_background("PROMPT")


def test_prepend_absence_line_when_markets_disabled():
    out = _agent()._prepend_research_background("PROMPT")
    assert "（预测市场信号：本次运行未启用该步骤——不是空结果，不可据此推断任何结论）" in out
    assert _ABSENCE_RULE in out


def test_prepend_knob_off_is_legacy(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_ABSENCE_MARKERS", False, raising=False)
    assert _agent()._prepend_research_background("PROMPT") == "BG\n\nPROMPT"
    assert _agent(_background_block="")._prepend_research_background("PROMPT") == "PROMPT"


# ------------------------------------------------------------ _finalize_structured_forecast
_SPINE = {"headline": "h", "horizon": "2030", "confidence": "medium",
          "confidence_rationale": "", "key_uncertainties": [],
          "scenarios": [{"name": "A", "probability": 1.0, "summary": "",
                         "key_drivers": [], "resolution_criteria": ""}],
          "critiqued": True, "schema_version": 1}


@pytest.fixture
def finalize_env(tmp_path, monkeypatch):
    monkeypatch.setattr(ReportManager, "_get_report_folder",
                        classmethod(lambda cls, rid: str(tmp_path)))
    for knob in ("FORECAST_EMIT_BINARY", "REPORT_FORECAST_SELF_CRITIQUE",
                 "REPORT_REPAIR_PASSES", "REPORT_FORECAST_LEDGER"):
        monkeypatch.setattr(Config, knob, False, raising=False)
    return tmp_path


def _finalize(folder, agent):
    agent._finalize_structured_forecast("r1", "# T\n\nBody.")
    return json.loads((folder / "forecast.json").read_text(encoding="utf-8"))


def test_finalize_records_prompt_slot_states(finalize_env, enabled):
    a = _agent(llm=None, _forecast_spine=dict(_SPINE),
               _market_status=absence.empty("no_equivalent_market"),
               actors={"forecast_inputs": {"base_rates": [{"reference_class": "rc"}]}})
    states = _finalize(finalize_env, a)["quality"]["prompt_slot_states"]
    assert states["market"] == {"state": "empty", "reason": "no_equivalent_market", "detail": ""}
    assert states["base_rates"] == {"state": "present"}
    assert states["market"]["state"] in absence.SLOT_STATES


def test_finalize_records_not_run_without_base_rates(finalize_env):
    a = _agent(llm=None, _forecast_spine=dict(_SPINE))
    states = _finalize(finalize_env, a)["quality"]["prompt_slot_states"]
    assert states["market"]["state"] == "not_run"
    assert states["market"]["reason"] == "prediction_markets_disabled"
    assert states["base_rates"] == {"state": "not_run"}


def test_finalize_knob_off_writes_no_slot_states(finalize_env, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_ABSENCE_MARKERS", False, raising=False)
    a = _agent(llm=None, _forecast_spine=dict(_SPINE))
    assert "prompt_slot_states" not in (_finalize(finalize_env, a).get("quality") or {})


class _QuietLLM:
    """Any LLM step finalize might reach answers with nothing usable (offline)."""

    def chat(self, *_a, **_k):
        return ""

    def chat_json(self, *_a, **_k):
        return {}


def test_finalize_rebuild_cannot_rewrite_the_recorded_slot_state(
        finalize_env, enabled, handoff, monkeypatch):
    """The binary-extraction rebuild in finalize re-runs _load_prediction_markets; the
    recorded prompt_slot_states.market must stay what the section prompts saw."""
    from app.services import forecast_extractor as fe

    calls = []

    def _queries(*_a, **_k):
        calls.append(1)
        if len(calls) == 1:  # generate_report's build: the report-time fallback errors
            raise RuntimeError("query derivation down")
        return []            # finalize's rebuild: no queries -> no_market_snapshot

    monkeypatch.setattr(pm, "derive_market_queries_llm", _queries)
    monkeypatch.setattr(Config, "FORECAST_EMIT_BINARY", True, raising=False)
    monkeypatch.setattr(Config, "FORECAST_SIM_SENSITIVITY", False, raising=False)
    monkeypatch.setattr(fe, "extract_binary_forecasts", lambda *_a, **_k: {})
    a = _agent(llm=_QuietLLM(), _forecast_spine=dict(_SPINE))
    a._market_pack = a._build_market_pack()  # as generate_report does
    assert a._market_pack == ""
    a._freeze_market_slot_status()
    prefix = a._prepend_research_background("PROMPT")
    assert "（预测市场信号：本次运行中不可用（report_fallback_error）" in prefix

    states = _finalize(finalize_env, a)["quality"]["prompt_slot_states"]
    assert len(calls) == 2  # finalize really re-ran the market load ...
    assert (a._market_status.state, a._market_status.reason) == (
        "unavailable", "no_market_snapshot")  # ... and the live status drifted
    assert states["market"] == {"state": "unavailable", "reason": "report_fallback_error",
                                "detail": ""}
    assert a._prepend_research_background("PROMPT") == prefix
