"""TIME-6: hindcast policy pin and report-stage containment.

A hindcast (a question answered as of a past date) is pinned once at admission
into ``state.options['hindcast_policy_v1']``. Under that pin the report stage
never reads, requotes or live-fetches Polymarket odds, labels forecast.json with
a ``hindcast`` block, checks horizon years against the as-of year, and run.json
records ``resolved.as_of_enforcement``. Without a pin every path is unchanged.

Offline: no LLM (FakeLLMClient / stubs), no network (the Polymarket client and
query helpers are patched to record and raise), per-test data directories.
"""

import inspect
import json
import os
from datetime import date, datetime, timedelta, timezone

import pytest

from app.config import Config
from app.services import forecast_extractor as fe
from app.services import hindcast_policy as hp
from app.services import pipeline_orchestrator as po
from app.services.report_agent import ReportAgent, ReportManager
from app.utils import absence
from app.utils import prediction_markets as pm
from tests.conftest import FakeLLMClient

QUESTION = "Will the ECB cut its deposit rate below 3% by the end of 2024?"
MARKDOWN = "# Forecast report\n\nThe analysis weighs the rate path and the inflation prints.\n"
TODAY = date(2026, 9, 30)
PIN = hp.capture_hindcast_policy_v1("2024-06-01", research_engine="v3", today_utc=TODAY)
LIVE_PIN = hp.capture_hindcast_policy_v1("2026-09-30", research_engine="v3", today_utc=TODAY)
BLOCK = {"as_of": "2024-06-01", "policy_version": "hindcast-policy/v1", "markets": "withheld",
         "retrieval": "live_labelled", "integrity": "labelled", "contamination": "not_assessed",
         "characterization_only": True}
ENFORCEMENT = {"schema": "as-of-enforcement/v1", "as_of": "2024-06-01",
               "retrieval_clamped": False, "live_data_withheld": True, "research_engine": "v3"}
WITHHELD = absence.SlotStatus("not_run", "hindcast_markets_withheld")
MARKET_ROW = {"market_id": "m1", "question": "ECB deposit rate below 3%?", "implied_yes_prob": 0.4}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"), raising=False)
    # Markets on, so every live path would reach the (patched) client: only the pin stops it.
    monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "true")
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_REQUOTE", True, raising=False)
    monkeypatch.setattr(po.PipelineOrchestrator, "_run", classmethod(lambda cls, state: None))
    return tmp_path


@pytest.fixture
def market_calls(monkeypatch):
    """Every Polymarket entry point records its call and raises (no request can succeed)."""
    calls = []

    class _Client:
        def __init__(self, *args, **kwargs):
            calls.append("client")
            raise RuntimeError("Polymarket client constructed")

    def _helper(name):
        def _raise(*args, **kwargs):
            calls.append(name)
            raise RuntimeError(f"{name} called")
        return _raise

    monkeypatch.setattr(pm, "PolymarketClient", _Client)
    monkeypatch.setattr(pm, "derive_market_queries_llm", _helper("derive_queries"))
    monkeypatch.setattr(pm, "score_market_relevance", _helper("score_relevance"))
    return calls


def _settle(pipeline_id):
    thread = po.PipelineOrchestrator._threads.pop(pipeline_id, None)
    if thread is not None:
        thread.join(timeout=5)
    po.PipelineOrchestrator._cancel_events.pop(pipeline_id, None)


def _save_pipeline(pipeline_id, simulation_id, *, created_at=None, **options):
    state = po.PipelineState(pipeline_id=pipeline_id, prompt=QUESTION)
    state.simulation_id = simulation_id
    if created_at:
        state.created_at = created_at
    state.options.update(options)
    po.PipelineManager.save(state)
    return state


def _spine():
    return {
        "horizon": "2024",
        "confidence": "low",
        "scenarios": [
            {"name": "Cut below 3%", "probability": 0.4, "resolution_criteria": "ECB decision"},
            {"name": "Hold at or above 3%", "probability": 0.6, "resolution_criteria": "no cut"},
        ],
    }


def _bare_agent(**over):
    a = ReportAgent.__new__(ReportAgent)
    for key, value in {
        "graph_id": "g1", "simulation_id": "sim_1", "simulation_requirement": QUESTION,
        "situation_brief": "", "actors": None, "sources": [], "research_report": "dossier",
        "output_language": "English", "scenario_label": "", "base_simulation_id": None,
        "_background_block": "", "_sources_index": "", "_signal_pack": "", "_market_pack": "",
        "_prediction_markets": [], "_markets_stale": False, "_charts_block": "",
        "_forecast_spine": _spine(), "_forecast_spine_block": "", "_retrieval_query": None,
        "_outline_degraded": False, "_outline_summary": "", "_section_tool_calls": 0,
        "report_logger": None, "console_logger": None, "tools": {}, "llm": FakeLLMClient(),
        "_citation_index": None,
    }.items():
        setattr(a, key, value)
    for key, value in over.items():
        setattr(a, key, value)
    return a


def _finalize_env(monkeypatch):
    for name, value in (("FORECAST_EMIT_BINARY", True), ("REPORT_REPAIR_PASSES", False),
                        ("REPORT_FORECAST_SELF_CRITIQUE", False), ("FORECAST_SIM_SENSITIVITY", False),
                        ("FORECAST_BINARY_THEMES", "monetary policy"), ("FORECAST_HORIZON_CHECK", True)):
        monkeypatch.setattr(Config, name, value, raising=False)
    monkeypatch.setattr(ReportAgent, "_temporal_horizon_date", lambda self: "")


def _fake_extract(calls):
    def fake(*args, **kwargs):
        calls.append(kwargs)
        return {"binary_forecasts": [{"id": "F1", "statement": QUESTION, "probability": 0.4,
                                      "resolution_criteria": "ECB press release", "horizon_year": 2024}],
                "binary_quality": {"count": 1, "issues": []}}
    return fake


def _horizon_spy(monkeypatch):
    calls = []
    real = fe.apply_horizon_consistency

    def spy(forecast, requirement_text, **kwargs):
        calls.append(kwargs)
        return real(forecast, requirement_text, **kwargs)

    monkeypatch.setattr(fe, "apply_horizon_consistency", spy)
    return calls


def _read_forecast_text(report_id):
    with open(os.path.join(ReportManager._get_report_folder(report_id), "forecast.json"),
              encoding="utf-8") as fh:
        return fh.read()


def _read_forecast(report_id):
    return json.loads(_read_forecast_text(report_id))


# ───────────────────────────── policy module ─────────────────────────────────
def test_capture_pins_a_past_as_of_as_a_hindcast():
    assert list(PIN) == ["version", "origin", "pinned_at", "as_of", "hindcast", "research_engine",
                         "markets", "fetch", "search", "pit"]
    assert {k: v for k, v in PIN.items() if k != "pinned_at"} == {
        "version": "hindcast-policy/v1", "origin": "admission", "as_of": "2024-06-01",
        "hindcast": True, "research_engine": "v3", "markets": "withheld", "fetch": "label",
        "search": "unbounded",
        # TIME-8: Config's point-in-time gate knobs at admission (defaults here).
        "pit": {"gates": True, "same_day": "exclude", "undated": "drop", "provider_bounds": True,
                "overfetch": 1}}
    assert datetime.fromisoformat(PIN["pinned_at"]).utcoffset() == timedelta(0)
    assert hp.hindcast_policy({hp.HINDCAST_POLICY_OPTION: PIN}) == PIN


def test_as_of_today_is_pinned_but_live():
    assert LIVE_PIN["hindcast"] is False
    assert hp.hindcast_policy({hp.HINDCAST_POLICY_OPTION: LIVE_PIN}) is None
    # A datetime "today" is reduced to its UTC date; the default is the current UTC date.
    late = datetime(2026, 9, 30, 23, 59, tzinfo=timezone.utc)
    assert hp.capture_hindcast_policy_v1(
        "2026-09-30", research_engine="v3", today_utc=late)["hindcast"] is False
    assert hp.capture_hindcast_policy_v1(
        "2026-09-30", research_engine="v3", today_utc=late.replace(tzinfo=None))["hindcast"] is False
    # An aware datetime in another zone counts by its UTC date, not its local one:
    # 2026-09-30T23:00-05:00 is already 2026-10-01 in UTC, so 09-30 lies in the past ...
    new_york_late = datetime(2026, 9, 30, 23, 0, tzinfo=timezone(timedelta(hours=-5)))
    assert hp.capture_hindcast_policy_v1(
        "2026-09-30", research_engine="v3", today_utc=new_york_late)["hindcast"] is True
    # ... while 2026-10-01T01:00+09:00 is still 2026-09-30 in UTC.
    tokyo_early = datetime(2026, 10, 1, 1, 0, tzinfo=timezone(timedelta(hours=9)))
    assert hp.capture_hindcast_policy_v1(
        "2026-09-30", research_engine="v3", today_utc=tokyo_early)["hindcast"] is False
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    assert hp.capture_hindcast_policy_v1(yesterday, research_engine="v3")["hindcast"] is True


@pytest.mark.parametrize("options", [
    None, {}, [(hp.HINDCAST_POLICY_OPTION, PIN)], {hp.HINDCAST_POLICY_OPTION: None},
    {hp.HINDCAST_POLICY_OPTION: "2024-06-01"},
    {hp.HINDCAST_POLICY_OPTION: dict(PIN, version="hindcast-policy/v0")},
    {hp.HINDCAST_POLICY_OPTION: dict(PIN, hindcast="true")},
])
def test_hindcast_policy_ignores_anything_but_a_hindcast_pin(options):
    assert hp.hindcast_policy(options) is None


@pytest.mark.parametrize("value", [
    None, {}, "2024-06-01", [("version", "hindcast-policy/v1")], LIVE_PIN,
    dict(PIN, version="hindcast-policy/v0"), dict(PIN, hindcast="true"),
])
def test_as_hindcast_pin_accepts_only_a_hindcast_pin(value):
    assert hp.as_hindcast_pin(value) is None


def test_as_hindcast_pin_returns_a_copy():
    pin = hp.as_hindcast_pin(PIN)
    assert pin == PIN and pin is not PIN


def test_hindcast_policy_returns_a_copy():
    options = {hp.HINDCAST_POLICY_OPTION: dict(PIN)}
    hp.hindcast_policy(options)["as_of"] = "2020-01-01"
    assert options[hp.HINDCAST_POLICY_OPTION]["as_of"] == "2024-06-01"


def test_forecast_block_and_enforcement_record():
    assert hp.hindcast_forecast_block(PIN) == BLOCK
    # TIME-9 maps a recognised research audit to ``integrity``; one without a verdict stays labelled.
    assert hp.hindcast_forecast_block(PIN, research_audit={"verdict": "clean"}) == BLOCK
    assert hp.as_of_enforcement_record(PIN) == ENFORCEMENT


# ───────────────────────────── report-stage markets ──────────────────────────
NOT_A_PIN = [LIVE_PIN, {}, dict(PIN, version="hindcast-policy/v0"), "2024-06-01"]


def _constructed(**kwargs):
    return ReportAgent(graph_id="g1", simulation_id="sim_1", simulation_requirement=QUESTION,
                       llm_client=FakeLLMClient(), zep_tools=object(), **kwargs)


def test_constructor_stores_only_a_hindcast_pin(env):
    agent = _constructed(hindcast=PIN)
    assert agent.hindcast == PIN and agent._hindcast_pin() == PIN
    assert agent._markets_withheld_status() == WITHHELD
    assert "hindcast" in inspect.signature(ReportAgent.__init__).parameters
    # A live pin (as-of today), {} or anything else is stored as "not given".
    for value in NOT_A_PIN:
        assert _constructed(hindcast=value).hindcast is None


@pytest.mark.parametrize("value", NOT_A_PIN)
def test_kwarg_that_is_not_a_hindcast_pin_behaves_as_no_pin(env, market_calls, monkeypatch, value):
    """A live pin or {} passed as the kwarg changes nothing: no withholding, label or as-of year."""
    agent = _constructed(hindcast=value)
    assert agent._hindcast_pin() is None and agent._markets_withheld_status() is None
    assert agent._load_prediction_markets() == []
    assert market_calls == ["client"]                     # the live fallback still ran
    assert agent._market_status == absence.unavailable("report_fallback_error")
    # The same holds when the attribute is set on an agent built without __init__.
    _finalize_env(monkeypatch)
    monkeypatch.setattr(fe, "extract_binary_forecasts", _fake_extract([]))
    horizon_calls = _horizon_spy(monkeypatch)
    for report_id in ("r_value", "r_none"):
        os.makedirs(ReportManager._get_report_folder(report_id), exist_ok=True)
    _bare_agent(hindcast=value)._finalize_structured_forecast("r_value", MARKDOWN)
    _bare_agent()._finalize_structured_forecast("r_none", MARKDOWN)
    assert "hindcast" not in _read_forecast("r_value")
    assert horizon_calls == [{"horizon_date": None}, {"horizon_date": None}]
    assert _read_forecast_text("r_value") == _read_forecast_text("r_none")


def test_pinned_report_makes_no_market_call(env, market_calls, monkeypatch):
    def no_scan(cls):
        pytest.fail("pipeline handoff scanned for markets under a hindcast pin")

    monkeypatch.setattr(po.PipelineManager, "list_pipelines", classmethod(no_scan))
    agent = _bare_agent(hindcast=PIN)
    assert agent._load_prediction_markets() == []
    assert agent._market_status == WITHHELD and agent._markets_stale is False
    assert agent._build_market_pack() == ""
    assert agent._market_slot_status() == WITHHELD
    # The section prompts say the slot is not part of this run, never "no market prices this".
    marker = absence.absence_marker("prediction markets", agent._market_slot_status(), "en")
    assert "not part of this run" in marker
    # Extraction-time requote: a cached snapshot is never refreshed under a pin.
    agent._prediction_markets = [dict(MARKET_ROW)]
    agent._market_pack = "cached pack"
    agent._refresh_market_prices_for_extraction()
    assert agent._prediction_markets == [MARKET_ROW] and agent._market_pack == "cached pack"
    assert market_calls == []


def test_live_report_market_paths_unchanged(env, market_calls):
    # A research handoff snapshot is read and requoted (the client is constructed) ...
    state = _save_pipeline("pipe_live", "sim_1")
    handoff = po.PipelineManager.handoff_dir(state.pipeline_id)
    os.makedirs(handoff, exist_ok=True)
    with open(os.path.join(handoff, "prediction_markets.json"), "w", encoding="utf-8") as fh:
        json.dump({"markets": [MARKET_ROW], "status": {"state": "markets_selected"}}, fh)
    agent = _bare_agent()
    assert agent._load_prediction_markets() == [MARKET_ROW]
    assert agent._market_status == absence.present("research_snapshot")
    assert agent._markets_stale is True          # the requote failed: research-time prices
    assert market_calls == ["client"]
    agent._prediction_markets = [dict(MARKET_ROW)]
    agent._refresh_market_prices_for_extraction()
    assert market_calls == ["client", "client"]
    # ... and without a snapshot the report-time live fallback still runs.
    fallback = _bare_agent(simulation_id="sim_other")
    assert fallback._load_prediction_markets() == []
    assert fallback._market_status == absence.unavailable("report_fallback_error")
    assert market_calls == ["client", "client", "client"]


# ───────────────────────────── pin discovery ─────────────────────────────────
def test_pin_discovered_from_the_owning_pipeline(env, market_calls, monkeypatch):
    _save_pipeline("pipe_hind", "sim_hind", created_at="2026-09-30T10:00:00+00:00",
                   **{hp.HINDCAST_POLICY_OPTION: PIN,
                      "ensemble_member_simulations": {"sim_member": 7}})
    _save_pipeline("pipe_live", "sim_live", created_at="2026-09-30T10:00:01+00:00")
    _save_pipeline("pipe_today", "sim_today", created_at="2026-09-30T10:00:02+00:00",
                   **{hp.HINDCAST_POLICY_OPTION: LIVE_PIN})
    # A newer shared-simulation batch child without its own pin defers to its base.
    _save_pipeline("pipe_child", "sim_hind", created_at="2026-09-30T11:00:00+00:00",
                   shared_simulation=True, shared_simulation_from="pipe_hind")
    _save_pipeline("pipe_live_child", "sim_live", created_at="2026-09-30T11:00:01+00:00",
                   shared_simulation=True, shared_simulation_from="pipe_live")

    assert po.hindcast_pin_for_simulation("sim_hind") == PIN
    assert po.hindcast_pin_for_simulation("sim_member") == PIN
    for simulation_id in ("sim_live", "sim_today", "sim_unknown", None):
        assert po.hindcast_pin_for_simulation(simulation_id) is None

    # /api/report regenerate and chat build a ReportAgent without the kwarg: it finds the
    # pin of the pipeline that ran its simulation, once per agent.
    lookups = []
    real_lookup = po.hindcast_pin_for_simulation
    monkeypatch.setattr(po, "hindcast_pin_for_simulation",
                        lambda sid: lookups.append(sid) or real_lookup(sid))
    agent = _bare_agent(simulation_id="sim_hind")
    assert agent._hindcast_pin() == PIN and agent._hindcast_pin() == PIN
    assert lookups == ["sim_hind"]
    assert agent._load_prediction_markets() == [] and agent._market_status == WITHHELD
    assert market_calls == []
    live = _bare_agent(simulation_id="sim_live")
    assert live._hindcast_pin() is None and live._hindcast_pin() is None
    assert lookups == ["sim_hind", "sim_live"]


def test_pin_lookup_failure_withholds_markets_only(env, market_calls, monkeypatch):
    """A lookup that raises is no pin (no label, no as-of year), but markets fail closed."""
    def boom(simulation_id):
        raise OSError("pipeline dir unreadable")

    monkeypatch.setattr(po, "_ledger_owner_of_simulation", boom)
    lookup_failed = absence.unavailable("hindcast_lookup_failed")
    agent = _bare_agent()
    assert agent._hindcast_pin() is None
    assert agent._markets_withheld_status() == lookup_failed
    assert agent._load_prediction_markets() == []
    assert agent._market_status == lookup_failed and agent._markets_stale is False
    agent._prediction_markets = [dict(MARKET_ROW)]
    agent._refresh_market_prices_for_extraction()
    assert agent._prediction_markets == [MARKET_ROW]
    assert market_calls == []
    # Finalization: the market slot says why it is empty; no hindcast block, today's year.
    _finalize_env(monkeypatch)
    monkeypatch.setattr(fe, "extract_binary_forecasts", _fake_extract([]))
    horizon_calls = _horizon_spy(monkeypatch)
    os.makedirs(ReportManager._get_report_folder("r_lookup_failed"), exist_ok=True)
    _bare_agent()._finalize_structured_forecast("r_lookup_failed", MARKDOWN)
    forecast = _read_forecast("r_lookup_failed")
    assert "hindcast" not in forecast
    assert horizon_calls == [{"horizon_date": None}]
    assert forecast["quality"]["prompt_slot_states"]["market"] == lookup_failed.to_dict()
    assert market_calls == []
    # The kwarg wins without any scan, so no lookup can fail.
    assert _bare_agent(hindcast=PIN)._hindcast_pin() == PIN
    assert _bare_agent(hindcast=PIN)._markets_withheld_status() == WITHHELD


# ───────────────────────────── forecast.json ─────────────────────────────────
def test_finalize_under_pin_labels_forecast_and_uses_as_of_year(env, market_calls, monkeypatch):
    _finalize_env(monkeypatch)
    extract_calls = []
    monkeypatch.setattr(fe, "extract_binary_forecasts", _fake_extract(extract_calls))
    horizon_calls = _horizon_spy(monkeypatch)
    os.makedirs(ReportManager._get_report_folder("r_hind"), exist_ok=True)
    _bare_agent(hindcast=PIN)._finalize_structured_forecast("r_hind", MARKDOWN)
    forecast = _read_forecast("r_hind")
    assert forecast["hindcast"] == BLOCK
    assert forecast["hindcast"]["integrity"] == "labelled"
    assert forecast["hindcast"]["contamination"] == "not_assessed"
    assert horizon_calls == [{"horizon_date": None, "now_year": 2024}]
    # No market reached the extraction, and no Polymarket call was made.
    assert extract_calls[0]["markets"] is None and extract_calls[0]["market_pack"] is None
    # FU-7: the extraction is told to drop any market anchor the model volunteers.
    assert extract_calls[0]["withhold_market_anchors"] is True
    assert forecast["quality"]["prompt_slot_states"]["market"] == WITHHELD.to_dict()
    assert market_calls == []


def test_finalize_without_pin_is_unchanged(env, market_calls, monkeypatch):
    _finalize_env(monkeypatch)
    live_calls = []
    monkeypatch.setattr(fe, "extract_binary_forecasts", _fake_extract(live_calls))
    horizon_calls = _horizon_spy(monkeypatch)
    _save_pipeline("pipe_live", "sim_1")
    for report_id in ("r_live", "r_ref"):
        os.makedirs(ReportManager._get_report_folder(report_id), exist_ok=True)
    _bare_agent()._finalize_structured_forecast("r_live", MARKDOWN)
    forecast = _read_forecast("r_live")
    assert "hindcast" not in forecast
    assert horizon_calls == [{"horizon_date": None}]      # no now_year: today's year as before
    assert "client" in market_calls                        # the live market path still runs
    assert "withhold_market_anchors" not in live_calls[0]  # FU-7: live call unchanged
    # Byte-identical to the same agent with the hindcast machinery bypassed entirely.
    monkeypatch.setattr(ReportAgent, "_hindcast_pin", lambda self: None)
    _bare_agent()._finalize_structured_forecast("r_ref", MARKDOWN)
    assert _read_forecast_text("r_live") == _read_forecast_text("r_ref")


def test_early_spine_copy_is_labelled(env, market_calls, monkeypatch):
    """A report whose finalize never runs still leaves a labelled forecast.json."""
    monkeypatch.setattr(fe, "derive_forecast_spine", lambda *a, **k: _spine())
    monkeypatch.setattr(fe, "render_forecast_spine_block", lambda s: "[spine]")
    monkeypatch.setattr(ReportAgent, "_temporal_horizon_date", lambda self: "")
    monkeypatch.setattr(Config, "REPORT_CRITIQUE_BEFORE_PROSE", False, raising=False)
    for report_id in ("r_spine_hind", "r_spine_live"):
        os.makedirs(ReportManager._get_report_folder(report_id), exist_ok=True)
    _bare_agent(hindcast=PIN, _forecast_spine=None)._derive_and_pin_forecast_spine("r_spine_hind")
    assert _read_forecast("r_spine_hind")["hindcast"] == BLOCK
    assert market_calls == []
    # Live: the early write is byte-identical to the unlabelled spine.
    _save_pipeline("pipe_live", "sim_1")
    live = _bare_agent(_forecast_spine=None)
    live._derive_and_pin_forecast_spine("r_spine_live")
    assert _read_forecast_text("r_spine_live") == json.dumps(_spine(), ensure_ascii=False, indent=2)
    assert "hindcast" not in live._forecast_spine


# ───────────────────────────── orchestrator ──────────────────────────────────
def test_fork_carries_the_pin(env):
    for pipeline_id, options in (("pipe_hind_base", {hp.HINDCAST_POLICY_OPTION: PIN}),
                                 ("pipe_live_base", {})):
        base = _save_pipeline(pipeline_id, f"sim_{pipeline_id}", **options)
        base.graph_id = "graph_1"
        po.PipelineManager.save(base)
        fork = po.PipelineOrchestrator.fork(pipeline_id, {"label": "Surprise hike"})
        _settle(fork.pipeline_id)
        persisted = po.PipelineManager.load(fork.pipeline_id)["options"]
        if options:
            assert persisted[hp.HINDCAST_POLICY_OPTION] == PIN
            assert persisted[hp.HINDCAST_POLICY_OPTION] is not PIN
        else:
            assert hp.HINDCAST_POLICY_OPTION not in persisted


@pytest.mark.parametrize("shared_simulation", [False, True])
def test_question_fork_carries_the_pin(env, market_calls, shared_simulation):
    """A batch question fork answers from the base's as-of research: it stays a hindcast."""
    import scripts.batch_runs as batch_runs

    for pipeline_id, options in (("pipe_hind_base", {hp.HINDCAST_POLICY_OPTION: PIN}),
                                 ("pipe_live_base", {})):
        base = _save_pipeline(pipeline_id, f"sim_{pipeline_id}", **options)
        base.graph_id = "graph_1"
        po.PipelineManager.save(base)
        fork = batch_runs.fork_question(pipeline_id, "Will the ECB cut again by mid-2025?",
                                        shared_simulation=shared_simulation)
        _settle(fork.pipeline_id)
        fork_state = po.PipelineState.from_dict(po.PipelineManager.load(fork.pipeline_id))
        persisted = fork_state.options
        if not options:
            assert hp.HINDCAST_POLICY_OPTION not in persisted
            assert po.PipelineOrchestrator._hindcast_agent_kwargs(fork_state) == {}
            continue
        assert persisted[hp.HINDCAST_POLICY_OPTION] == PIN
        assert persisted[hp.HINDCAST_POLICY_OPTION] is not PIN
        # The fork's own report stage passes the pin, so its report withholds markets ...
        assert po.PipelineOrchestrator._hindcast_agent_kwargs(fork_state) == {"hindcast": PIN}
        # ... and a regeneration on the simulation the fork ran finds the pin as well.
        if not shared_simulation:
            fork_state.simulation_id = "sim_question_fork"
            po.PipelineManager.save(fork_state)
        agent = _bare_agent(simulation_id=fork_state.simulation_id)
        assert agent._hindcast_pin() == PIN
        assert agent._load_prediction_markets() == [] and agent._market_status == WITHHELD
    assert market_calls == []


def test_run_manifest_records_as_of_enforcement_only_when_pinned(env, monkeypatch):
    monkeypatch.setattr(po, "_repo_git_sha", lambda: "gitsha")
    monkeypatch.setattr(po, "_deerflow_ref", lambda: None)
    pinned = po.PipelineState(pipeline_id="pipe_m1", prompt=QUESTION,
                              options={hp.HINDCAST_POLICY_OPTION: PIN})
    assert po._build_run_manifest(pinned)["resolved"]["as_of_enforcement"] == ENFORCEMENT
    for options in ({}, {hp.HINDCAST_POLICY_OPTION: LIVE_PIN}):
        state = po.PipelineState(pipeline_id="pipe_m2", prompt=QUESTION, options=options)
        assert "as_of_enforcement" not in po._build_run_manifest(state)["resolved"]


def test_agent_kwargs_helper():
    pinned = po.PipelineState(pipeline_id="p", prompt=QUESTION,
                              options={hp.HINDCAST_POLICY_OPTION: PIN})
    assert po.PipelineOrchestrator._hindcast_agent_kwargs(pinned) == {"hindcast": PIN}
    for options in ({}, {hp.HINDCAST_POLICY_OPTION: LIVE_PIN}):
        state = po.PipelineState(pipeline_id="p", prompt=QUESTION, options=options)
        assert po.PipelineOrchestrator._hindcast_agent_kwargs(state) == {}


@pytest.mark.parametrize("pinned", [True, False])
def test_seed_report_agent_receives_the_pin(env, monkeypatch, pinned):
    monkeypatch.setattr(Config, "SIM_GRAPH_FEEDBACK", False, raising=False)
    constructed = []

    class _Sim:
        simulation_id = "sim_seed"

    class _SimManager:
        def create_simulation(self, *a, **k):
            return _Sim()

        def prepare_simulation(self, **k):
            return None

    class _RunState:
        current_round = 1
        runner_status = po.RunnerStatus.COMPLETED

    class _Runner:
        start_simulation = staticmethod(lambda **k: None)
        get_run_state = staticmethod(lambda sim_id: _RunState())
        write_run_summary = staticmethod(lambda sim_id: None)

    class _FakeAgent:
        def __init__(self, **kwargs):
            constructed.append(kwargs)
            self.ledger_context = None
            self.evaluation_context = None

        def generate_report(self, report_id=None, **kw):
            return None

    monkeypatch.setattr(po, "SimulationManager", _SimManager)
    monkeypatch.setattr(po, "SimulationRunner", _Runner)
    monkeypatch.setattr(po, "ReportAgent", _FakeAgent)
    state = po.PipelineState(pipeline_id="pipe_ens", prompt=QUESTION)
    if pinned:
        state.options[hp.HINDCAST_POLICY_OPTION] = PIN
    po.PipelineOrchestrator()._run_one_seed(
        state, type("P", (), {"project_id": "proj"})(), "graph_1", None, {}, "report md",
        seed=11, max_rounds=None)
    (kwargs,) = constructed
    if pinned:
        assert kwargs["hindcast"] == PIN
    else:
        assert "hindcast" not in kwargs


@pytest.mark.parametrize("pinned", [True, False])
def test_report_stage_passes_the_pin_and_run_json_records_it(monkeypatch, tmp_path, pinned):
    """The real _run state machine (every service faked) builds the report agent."""
    from tests.test_orchestrator_research_wiring import _exercise_prepare_run_resume

    created = []

    class _Recording(po.ReportAgent):
        def __new__(cls, *args, **kwargs):
            agent = super().__new__(cls)
            created.append(agent)
            return agent

    monkeypatch.setattr(po, "ReportAgent", _Recording)
    result = _exercise_prepare_run_resume(
        monkeypatch, tmp_path, rebuild_prepare=True, real_run_manifest=True,
        extra_options={hp.HINDCAST_POLICY_OPTION: PIN} if pinned else None)
    assert result.report_generations, "the stage must build a fresh report"
    report_kwargs = created[-1].kwargs
    with open(po.PipelineManager.manifest_path(result.pid), encoding="utf-8") as fh:
        resolved = json.load(fh)["resolved"]
    if pinned:
        assert report_kwargs["hindcast"] == PIN
        assert resolved["as_of_enforcement"] == ENFORCEMENT
    else:
        assert "hindcast" not in report_kwargs
        assert "as_of_enforcement" not in resolved


# ------------------------------------------------- FU-7: volunteered anchors under a pin
_VOLUNTEERED = {"binary_forecasts": [
    {"id": "F1", "statement": "The ECB cuts its deposit rate in June 2024.", "probability": 0.7,
     "resolution_criteria": "ECB press release on 2024-06-06", "theme": "rates", "horizon_year": 2024,
     "adjustment_rationale": "guidance", "market_anchor": {"market_id": "pm-ecb", "implied_yes_prob": 0.8}},
    {"id": "F2", "statement": "Euro-area HICP is below 2.5% in May 2024.", "probability": 0.4,
     "resolution_criteria": "Eurostat flash estimate", "theme": "inflation", "horizon_year": 2024,
     "adjustment_rationale": "base rate"},
]}


def _extract_volunteered(monkeypatch, **kwargs):
    from tests.conftest import FakeLLMClient
    monkeypatch.setattr(Config, "FORECAST_BINARY_CONTRARIAN", False, raising=False)
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_MODELS", "", raising=False)
    return fe.extract_binary_forecasts("dossier", FakeLLMClient(json_responses=[_VOLUNTEERED]),
                                       min_count=2, language="English", **kwargs)


def test_pinned_extraction_drops_model_volunteered_market_anchors(monkeypatch):
    """FU-7 (TIME-6 open issue): markets are withheld for a whole hindcast, so an anchor on
    a binary is the model's own (possibly post-as-of) knowledge; it is dropped and counted."""
    live = _extract_volunteered(monkeypatch)
    assert live["binary_forecasts"][0]["market_anchor"]["market_id"] == "pm-ecb"
    assert "hindcast_market_anchor_dropped" not in live["binary_quality"]
    pinned = _extract_volunteered(monkeypatch, withhold_market_anchors=True)
    assert all("market_anchor" not in b for b in pinned["binary_forecasts"])
    assert pinned["binary_quality"]["hindcast_market_anchor_dropped"] == 1
    assert "market_comparison" not in pinned
    # Everything else is the live extraction's.
    strip = [{k: v for k, v in b.items() if k != "market_anchor"} for b in live["binary_forecasts"]]
    assert pinned["binary_forecasts"] == strip

