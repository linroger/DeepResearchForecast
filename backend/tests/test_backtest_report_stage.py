"""Backtest mode after research (design §5, §7, §8): the report agent, the binary
extractor, the world seed and the resolution monitor.

Agents are built with ``__new__`` like the existing report tests; the market client,
the ledger and the LLM are fakes.  Each live-path test pins the unchanged behaviour.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

from app.config import Config
from app.services import backtest_mode as bm
from app.services import forecast_ledger
from app.services.forecast_extractor import extract_binary_forecasts
from app.services.report_agent import Report, ReportAgent, ReportManager, ReportStatus
from app.services.world_model_seed import build_world_model_seed
from app.utils import prediction_markets as pm
from test_audit_fixes_report import _JsonLLM, _bare_agent

TODAY = date(2026, 10, 21)
TARGET = {"golden_id": "us-pres-2024-trump", "question": "Will Donald Trump win the 2024 US presidential election?",
          "resolution_criteria": "YES if certified winner with >=270 electoral votes", "resolution_date": "2024-11-06"}


def _option(arm="production", target=None):
    return bm.normalize_backtest_request({"as_of": "2024-11-01", "arm": arm, "target": target}, today=TODAY)


def _agent(option=None, **attrs):
    agent = ReportAgent.__new__(ReportAgent)
    agent.output_language = "English"
    agent._prediction_markets = []
    agent._market_pack = ""
    agent._markets_stale = False
    agent.simulation_id = attrs.pop("simulation_id", "sim_x")
    for key, value in attrs.items():
        setattr(agent, key, value)
    agent.set_backtest_policy(option)
    return agent


@pytest.fixture
def markets_on(monkeypatch):
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_REQUOTE", True, raising=False)


@pytest.fixture
def no_market_api(monkeypatch):
    calls = []
    monkeypatch.setattr(pm.httpx, "get", lambda *args, **kwargs: calls.append(args) or pytest.fail("market API"))
    monkeypatch.setattr(pm.PolymarketClient, "snapshot_for_queries",
                        lambda *args, **kwargs: pytest.fail("live market search"))
    return calls


# ------------------------------------------------------------------ markets

def test_backtest_report_never_requotes(markets_on, no_market_api):
    rows = [{"market_id": "253591", "implied_yes_prob": 0.59, "price_basis": "clob_history_at_cutoff"}]
    agent = _agent(_option())
    assert agent._requote_snapshot(rows) == rows and agent._markets_stale is False
    agent._prediction_markets = list(rows)
    agent._refresh_market_prices_for_extraction()
    assert agent._prediction_markets == rows and no_market_api == []


def test_backtest_report_has_no_live_market_fallback(markets_on, no_market_api, monkeypatch):
    from app.services.pipeline_orchestrator import PipelineManager
    monkeypatch.setattr(PipelineManager, "list_pipelines", classmethod(lambda cls: []))
    agent = _agent(_option(), llm=object(), actors={}, simulation_requirement="Will Trump win?")
    assert agent._load_prediction_markets() == []


def test_markets_off_arm_sees_no_markets(markets_on, no_market_api, monkeypatch):
    from app.services.pipeline_orchestrator import PipelineManager
    monkeypatch.setattr(PipelineManager, "list_pipelines",
                        classmethod(lambda cls: pytest.fail("handoff read for a markets-off arm")))
    agent = _agent(_option("research_only"))
    assert agent._load_prediction_markets() == [] and agent._build_market_pack() == ""


def test_live_report_still_requotes(markets_on, monkeypatch):
    agent = _agent(None)
    monkeypatch.setattr(pm.PolymarketClient, "requote_markets",
                        lambda self, rows: [dict(rows[0], implied_yes_prob=0.97)])
    assert agent._requote_snapshot([{"market_id": "m1", "implied_yes_prob": 0.5}])[0]["implied_yes_prob"] == 0.97


# ------------------------------------------------------------------ arms

def test_arm_decides_the_simulation_effect(monkeypatch):
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "diagnostic_only", raising=False)
    assert _agent(_option("research_only"))._simulation_forecast_effect() == "no_update"
    assert _agent(_option("simulation"))._simulation_forecast_effect() == "legacy_prompt"
    assert _agent(_option("production"))._simulation_forecast_effect() == "diagnostic_only"
    assert _agent(None)._simulation_forecast_effect() == "diagnostic_only"


def test_extraction_keywords():
    assert _agent(None)._backtest_extraction_kwargs() == {} and _agent(None)._backtest_now_year() == {}
    agent = _agent(_option("simulation", TARGET))
    assert agent._backtest_extraction_kwargs() == {"simulation_effect": "legacy_prompt",
                                                   "pinned_questions": [TARGET]}
    assert agent._backtest_now_year() == {"now_year": 2024}


def test_unset_agent_finds_its_pipeline_by_simulation(monkeypatch):
    option = _option("markets")
    monkeypatch.setattr(bm, "policy_for_simulation", lambda sid: option if sid == "sim_bt" else None)
    agent = ReportAgent.__new__(ReportAgent)
    agent.simulation_id = "sim_bt"
    assert agent._backtest() == option
    other = ReportAgent.__new__(ReportAgent)
    other.simulation_id = "sim_live"
    assert other._backtest() is None


# ------------------------------------------------------------------ forecast.json and ledger

def _finalize(tmp_path, monkeypatch, option):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    for name, value in (("REPORT_FORECAST_SELF_CRITIQUE", False), ("FORECAST_EMIT_BINARY", False),
                        ("REPORT_PUBLISH_GATE", False), ("REPORT_FORECAST_LEDGER", True)):
        monkeypatch.setattr(Config, name, value, raising=False)
    appended = []
    monkeypatch.setattr(forecast_ledger, "append_forecast", lambda forecast, **kw: appended.append(kw) or {})
    monkeypatch.setattr(forecast_ledger, "calibration_summary",
                        lambda *a, **k: {"n_resolved": 3, "mean_brier": 0.2, "calibration_error": 0.1})
    spine = {"headline": "h", "horizon": "2024", "confidence": "medium", "confidence_rationale": "",
             "key_uncertainties": [], "critiqued": True, "schema_version": 1,
             "scenarios": [{"name": "A", "probability": 1.0, "summary": "", "key_drivers": [],
                            "resolution_criteria": ""}]}
    agent = _bare_agent(llm=_JsonLLM(lambda content: {}), _forecast_spine=dict(spine))
    agent.set_backtest_policy(option)
    (tmp_path / "reports" / "report_bt").mkdir(parents=True)
    agent._finalize_structured_forecast("report_bt", "# T\n\nBody")
    forecast = json.loads((tmp_path / "reports" / "report_bt" / "forecast.json").read_text(encoding="utf-8"))
    return forecast, appended


def test_backtest_forecast_is_marked_and_kept_out_of_the_production_ledger(tmp_path, monkeypatch):
    forecast, appended = _finalize(tmp_path, monkeypatch, _option("markets", TARGET))
    assert appended == []
    assert forecast["backtest"]["as_of"] == "2024-11-01" and forecast["backtest"]["golden_id"] == TARGET["golden_id"]
    assert forecast["backtest"]["arm"]["name"] == "markets"
    assert "historical_calibration" not in forecast  # today's track record postdates the cutoff
    assert bm.is_backtest_forecast(forecast)


def test_live_forecast_keeps_its_calibration_note(tmp_path, monkeypatch):
    forecast, appended = _finalize(tmp_path, monkeypatch, None)
    # Since the forecast-feedback loop, a live forecast enters the ledger at its audited
    # publication (ReportManager.save_report), not here; see the publication test below.
    assert appended == [] and "backtest" not in forecast
    assert forecast["historical_calibration"]["n_resolved"] == 3


def _save_completed(tmp_path, report_id, forecast):
    folder = tmp_path / "reports" / report_id
    folder.mkdir(parents=True)
    (folder / "forecast.json").write_text(json.dumps(forecast), encoding="utf-8")
    ReportManager.save_report(Report(
        report_id=report_id, simulation_id="sim_x", graph_id="g", simulation_requirement="q",
        status=ReportStatus.COMPLETED, markdown_content="# T\n\nBody",
        created_at="2026-10-21T00:00:00+00:00", completed_at="2026-10-21T00:00:00+00:00"))
    return json.loads((folder / "meta.json").read_text(encoding="utf-8"))


def test_publication_journal_takes_live_reports_not_backtest_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", True, raising=False)
    registered = []
    monkeypatch.setattr(ReportManager, "register_published_forecast",
                        classmethod(lambda cls, report_id: registered.append(report_id)))
    spine = {"headline": "h", "scenarios": [{"name": "A", "probability": 1.0}]}
    live_meta = _save_completed(tmp_path, "report_live", spine)
    bt_meta = _save_completed(tmp_path, "report_bt", dict(spine, backtest=bm.forecast_block(_option("markets", TARGET))))
    assert registered == ["report_live"]
    assert live_meta.get("forecast_feedback_required") is True
    assert not bt_meta.get("forecast_feedback_required")


class _TrackRecordRequested(Exception):
    pass


def test_backtest_report_gets_no_track_record(tmp_path, monkeypatch):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", True, raising=False)

    def _requested(**kwargs):
        raise _TrackRecordRequested()

    monkeypatch.setattr(forecast_ledger, "production_track_record", _requested)
    for report_id, option in (("report_bt", _option("markets", TARGET)), ("report_live", None)):
        folder = tmp_path / "reports" / report_id
        folder.mkdir(parents=True)
        forecast = {"headline": "h", "scenarios": [{"name": "A", "probability": 1.0}]}
        if option is not None:
            forecast["backtest"] = bm.forecast_block(option)
        (folder / "forecast.json").write_text(json.dumps(forecast), encoding="utf-8")
        report = Report(report_id=report_id, simulation_id="sim_x", graph_id="g", simulation_requirement="q",
                        status=ReportStatus.COMPLETED, markdown_content="# T\n\nBody")
        agent = _agent(option)
        agent._world_binding = None
        if option is not None:
            agent._prepare_forecast_track_record(report_id, report)   # skipped: nothing frozen or inserted
            assert not (folder / "forecast_track_record.json").exists()
            assert json.loads((folder / "forecast.json").read_text(encoding="utf-8")) == forecast
            assert report.markdown_content == "# T\n\nBody"
        else:
            with pytest.raises(_TrackRecordRequested):          # the live path still freezes one
                agent._prepare_forecast_track_record(report_id, report)


# ------------------------------------------------------------------ binary extraction

class _BinaryLLM:
    provider = "fake"

    def __init__(self, rows):
        self.rows = rows
        self.prompts: list[str] = []

    def chat_json(self, messages=None, temperature=0.2, max_tokens=2048, **kwargs):
        self.prompts.append(messages[-1]["content"])
        return {"binary_forecasts": self.rows}


ROWS = [
    {"id": "F1", "statement": "Donald Trump wins the 2024 US presidential election by 2024-11-06.",
     "probability": 0.55, "resolution_criteria": "Certified winner with at least 270 electoral votes by 2024-12-31",
     "proposition_id": "us-pres-2024-trump", "theme": "politics"},
    {"id": "F2", "statement": "Turnout exceeds 160 million votes in the 2024 US election by 2024-11-06.",
     "probability": 0.2, "resolution_criteria": "Official turnout above 160 million by 2024-12-31",
     "proposition_id": "turnout-160m", "theme": "politics"},
    {"id": "F3", "statement": "Republicans win at least 52 Senate seats in 2024 by 2024-11-06.",
     "probability": 0.8, "resolution_criteria": "At least 52 seats certified by 2024-12-31",
     "proposition_id": "senate-52", "theme": "politics"},
]


@pytest.fixture
def extractor_config(monkeypatch):
    for name, value in (("FORECAST_ENSEMBLE_MODELS", ""), ("FORECAST_BINARY_CONTRARIAN", False),
                        ("SIMULATION_FORECAST_EFFECT", "diagnostic_only"), ("FORECAST_SIM_SENSITIVITY", True),
                        ("PREDICTION_MARKETS_ENABLED", False)):
        monkeypatch.setattr(Config, name, value, raising=False)


def test_pinned_question_is_requested_and_marked(extractor_config):
    llm = _BinaryLLM(ROWS)
    out = extract_binary_forecasts("dossier", llm, min_count=3, pinned_questions=[TARGET])
    assert "PINNED QUESTIONS" in llm.prompts[0] and 'proposition_id "us-pres-2024-trump"' in llm.prompts[0]
    marked = [row for row in out["binary_forecasts"] if row.get("golden_id")]
    assert [(row["golden_id"], row["probability"]) for row in marked] == [("us-pres-2024-trump", 0.55)]


def test_live_extraction_prompt_is_unchanged(extractor_config):
    llm = _BinaryLLM(ROWS)
    out = extract_binary_forecasts("dossier", llm, min_count=3)
    assert "PINNED" not in llm.prompts[0] and all("golden_id" not in row for row in out["binary_forecasts"])


def test_simulation_effect_override_admits_the_signal_pack(extractor_config):
    pack = "## 模拟量化结果\nTop actor: X"
    live, arm = _BinaryLLM(ROWS), _BinaryLLM(ROWS)
    extract_binary_forecasts("dossier", live, min_count=3, signal_pack=pack)
    extract_binary_forecasts("dossier", arm, min_count=3, signal_pack=pack, simulation_effect="legacy_prompt")
    assert "[Simulation quantitative signals]" not in live.prompts[0]
    assert "[Simulation quantitative signals]" in arm.prompts[0]


# ------------------------------------------------------------------ world channel

def test_world_seed_pins_the_pressure_weight_only_when_asked():
    actors = {"actors": [{"name": "Party A", "agency_class": "state"}]}
    assert "pressure_weight" not in build_world_model_seed(actors, [])["settings"]
    assert build_world_model_seed(actors, [], pressure_weight=0.0)["settings"]["pressure_weight"] == 0.0


def test_generator_reads_the_arm_of_its_simulation(monkeypatch):
    from app.services.simulation_config_generator import SimulationConfigGenerator
    options = {"sim_off": _option("simulation"), "sim_on": _option("world_channel")}
    monkeypatch.setattr(bm, "policy_for_simulation", lambda sid: options.get(sid))
    assert SimulationConfigGenerator._backtest_pressure_weight("sim_off") == 0.0
    assert SimulationConfigGenerator._backtest_pressure_weight("sim_on") is None
    assert SimulationConfigGenerator._backtest_pressure_weight("sim_live") is None
    assert SimulationConfigGenerator._backtest_pressure_weight(None) is None


# ------------------------------------------------------------------ resolution monitor

def test_monitor_skips_backtest_reports(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import resolution_monitor as monitor

    class Client:
        def requote_markets(self, rows):
            raise AssertionError("re-quoted a backtest report")

        fetch_resolutions = requote_markets

    forecast = {"binary_forecasts": [{"id": "F1", "probability": 0.6,
                                      "market_anchor": {"market_id": "253591", "implied_yes_prob": 0.59}}],
                "backtest": bm.forecast_block(_option("markets", TARGET))}
    result = monitor.run_monitor("report_bt", forecast=forecast, report_folder=str(tmp_path), client=Client(),
                                 ledger_dir=str(tmp_path / "ledger"))
    assert result["skipped"] == "backtest" and result["resolved_count"] == 0
    assert monitor._summary_row(result)["skipped"] == "backtest"
    assert not (tmp_path / "ledger").exists() and list(tmp_path.iterdir()) == []
    if "resolution_monitor" in sys.modules:
        del sys.modules["resolution_monitor"]
