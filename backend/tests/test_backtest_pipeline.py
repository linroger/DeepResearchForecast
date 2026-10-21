"""Backtest mode at the pipeline layer (design §3, §7): the pinned ``backtest_v1``
option, admission, the SDK route and the research child's environment.

The child test spawns the real bridge entry point (``deerflow_research.main`` → v3)
through a shim whose model, search, fetch and archive are offline fakes, exactly as
``test_research_engine_v3_round2`` accepts a v3 run; the shim records the variables
the parent handed it.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_research_engine_v3 as v3
from app.services import backtest_mode as bm

_REPO = Path(__file__).resolve().parents[2]
TODAY = date(2026, 10, 21)


def _request(**extra):
    return {"as_of": "2024-11-01", **extra}


# ------------------------------------------------------------------ the option

def test_request_defaults_and_shape():
    option = bm.normalize_backtest_request(_request(), today=TODAY)
    assert option["version"] == bm.BACKTEST_VERSION and option["as_of"] == "2024-11-01"
    assert option["strict"] is True and option["archive"] == "wayback" and option["target"] is None
    assert option["arm"] == {"name": "production", "markets": True, "simulation": None, "world_channel": True}
    target = {"golden_id": "us-pres-2024-trump", "question": "Will Donald Trump win the 2024 US election?",
              "resolution_criteria": "YES if certified", "resolution_date": "2024-11-06"}
    option = bm.normalize_backtest_request(_request(arm="research_only", target=target, strict=False,
                                                    archive="off", run_label="smoke"), today=TODAY)
    assert option["target"] == target and option["arm"]["name"] == "research_only"
    assert option["strict"] is False and option["archive"] == "off" and option["run_label"] == "smoke"


@pytest.mark.parametrize("raw, message", [
    ("2024-11-01", "must be an object"),
    ({"as_of": "2026-10-21"}, "before today"),
    ({"as_of": "2027-01-01"}, "before today"),
    ({"as_of": "Nov 1 2024"}, "YYYY-MM-DD"),
    ({"as_of": "2024-11-01", "arm": "everything"}, "arm must be one of"),
    ({"as_of": "2024-11-01", "strict": "no"}, "strict"),
    ({"as_of": "2024-11-01", "archive": "cache"}, "archive"),
    ({"as_of": "2024-11-01", "cutoff": "x"}, "unknown backtest field"),
    ({"as_of": "2024-11-01", "target": {"golden_id": "Bad Id", "question": "q"}}, "golden_id"),
    ({"as_of": "2024-11-01", "target": {"golden_id": "a", "question": ""}}, "question"),
    ({"as_of": "2024-11-01", "target": {"golden_id": "a", "question": "q",
                                        "resolution_date": "2024-11-01"}}, "resolve after"),
])
def test_invalid_requests_are_refused(raw, message):
    with pytest.raises(bm.BacktestRequestError, match=message):
        bm.normalize_backtest_request(raw, today=TODAY)


def test_arm_accessors():
    def option(arm):
        return bm.normalize_backtest_request(_request(arm=arm), today=TODAY)

    assert [bm.markets_enabled(option(arm)) for arm in bm.ABLATION_ARMS] == [False, True, True, True]
    assert [bm.simulation_effect(option(arm)) for arm in bm.ABLATION_ARMS] == [
        "no_update", "no_update", "legacy_prompt", "legacy_prompt"]
    assert [bm.world_pressure_weight(option(arm)) for arm in bm.ABLATION_ARMS] == [0.0, 0.0, 0.0, None]
    assert bm.simulation_effect(option("production")) is None
    # A live run: nothing to switch.
    assert bm.markets_enabled(None) is True and bm.simulation_effect(None) is None
    assert bm.world_pressure_weight(None) is None and bm.backtest_of({}) is None


def test_child_policy_is_accepted_by_the_bridge_parser(tmp_path):
    option = bm.normalize_backtest_request(_request(strict=False), today=TODAY)
    text = bm.research_child_policy(option, audit_path=str(tmp_path / "audit.jsonl"))
    from app.services.official_data import bridge_module
    policy = bridge_module("backtest_cutoff").parse_policy(text)
    assert (policy.as_of.isoformat(), policy.strict, policy.audit_path) == (
        "2024-11-01", False, str(tmp_path / "audit.jsonl"))


def test_policy_for_simulation_reads_the_owning_pipeline(tmp_path, monkeypatch):
    from app.config import Config
    from app.services import pipeline_orchestrator as po
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))
    option = bm.normalize_backtest_request(_request(arm="markets"), today=TODAY)
    for pid, sim, options in (("pipe_live", "sim_live", {}), ("pipe_bt", "sim_bt", {bm.BACKTEST_OPTION: option})):
        po.PipelineManager.ensure_dirs(pid)
        state = po.PipelineState(pipeline_id=pid, prompt="q", simulation_id=sim)
        state.options.update(options)
        po.PipelineManager.save(state)
    assert bm.policy_for_simulation("sim_bt") == option
    assert bm.policy_for_simulation("sim_live") is None and bm.policy_for_simulation("sim_none") is None
    assert bm.policy_for_simulation(None) is None


# ------------------------------------------------------------------ admission

@pytest.fixture
def admission(monkeypatch, tmp_path):
    from app.config import Config
    from app.services import pipeline_orchestrator as po
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))
    monkeypatch.setattr(Config, "DEFAULT_SIMULATION_ENGINE", "oasis-legacy")
    monkeypatch.setattr(Config, "RESEARCH_ENGINE", "v3")
    monkeypatch.setattr(po.PipelineOrchestrator, "_threads", {})
    monkeypatch.setattr(po.PipelineOrchestrator, "_cancel_events", {})
    started = []

    class ParkedThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            started.append(self.kwargs["name"])

    monkeypatch.setattr(po, "TaskManager", lambda: SimpleNamespace(create_task=lambda **kwargs: "task_fixture"))
    monkeypatch.setattr(po, "threading", SimpleNamespace(Thread=ParkedThread, Event=threading.Event,
                                                         Lock=threading.Lock))
    return SimpleNamespace(po=po, config=Config, root=tmp_path / "pipelines", started=started)


def test_admission_pins_the_option(admission):
    state = admission.po.PipelineOrchestrator.start("Will X happen?", mode="research_only",
                                                    backtest=_request(arm="research_only"))
    saved = admission.po.PipelineManager.load(state.pipeline_id)
    assert saved["options"][bm.BACKTEST_OPTION]["arm"]["name"] == "research_only"
    assert admission.started == [f"pipeline-{state.pipeline_id}"]
    live = admission.po.PipelineOrchestrator.start("Will Y happen?", mode="research_only")
    assert bm.BACKTEST_OPTION not in admission.po.PipelineManager.load(live.pipeline_id)["options"]


@pytest.mark.parametrize("setting, request_extra, message", [
    (("RESEARCH_ENGINE", "legacy"), {}, "v3 research engine"),
    (None, {"as_of": "2999-01-01"}, "before today"),
])
def test_admission_refuses_before_creating_anything(admission, monkeypatch, setting, request_extra, message):
    if setting:
        monkeypatch.setattr(admission.config, *setting)
    with pytest.raises(bm.BacktestRequestError, match=message):
        admission.po.PipelineOrchestrator.start("Will X happen?", backtest={**_request(), **request_extra})
    assert not admission.root.exists() and admission.started == []


def test_admission_refuses_the_world_v1_engine(admission, monkeypatch):
    monkeypatch.setattr(admission.po, "_fresh_simulation_options",
                        lambda **kwargs: {"simulation_engine": "world-v1"})
    with pytest.raises(bm.BacktestRequestError, match="OASIS"):
        admission.po.PipelineOrchestrator.start("Will X happen?", backtest=_request())
    assert not admission.root.exists()


def test_a_scenario_fork_keeps_the_cutoff(admission):
    po = admission.po
    base = po.PipelineOrchestrator.start("Will X happen?", backtest=_request(arm="markets"))
    live = po.PipelineOrchestrator.start("Will Y happen?")
    for state in (base, live):
        state.graph_id = "graph_fixture"
        po.PipelineManager.save(state)
    child = po.PipelineOrchestrator.fork(base.pipeline_id, {"label": "what-if"})
    assert child.options[bm.BACKTEST_OPTION] == po.PipelineManager.load(base.pipeline_id)["options"][bm.BACKTEST_OPTION]
    assert bm.BACKTEST_OPTION not in po.PipelineOrchestrator.fork(live.pipeline_id, {"label": "x"}).options


def test_sdk_route_answers_400_for_an_invalid_request(admission, monkeypatch):
    from flask import Flask
    from app.api import sdk
    monkeypatch.setattr(sdk, "preflight_pipeline", lambda mode="full", model=None: [])
    app = Flask(__name__)
    app.register_blueprint(sdk.sdk_bp, url_prefix="/api/v1")
    client = app.test_client()
    bad = client.post("/api/v1/run", json={"prompt": "Will X happen?", "backtest": {"as_of": "soon"}})
    assert bad.status_code == 400 and "invalid backtest request" in bad.get_json()["error"]
    assert not admission.root.exists()
    good = client.post("/api/v1/run", json={"prompt": "Will X happen?", "mode": "research_only",
                                            "backtest": _request(arm="markets")})
    assert good.status_code == 200
    pid = good.get_json()["data"]["pipeline_id"]
    assert admission.po.PipelineManager.load(pid)["options"][bm.BACKTEST_OPTION]["arm"]["name"] == "markets"


# ------------------------------------------------------------------ the research child

_CHILD_SHIM = """
import json
import os
import sys

sys.path[:0] = {paths!r}
import deerflow_research as dr
import linear_research as lr
import research_gateway as rg
import test_research_engine_v3 as v3
import test_backtest_engine as be

out_dir = sys.argv[sys.argv.index("--out-dir") + 1]
with open(os.path.join(out_dir, "child_env.json"), "w", encoding="utf-8") as stream:
    json.dump({{name: os.environ.get(name) for name in ("DRF_BACKTEST_POLICY", "PREDICTION_MARKETS_ENABLED")}},
              stream)
model = v3.ScriptedModel(v3.World())


def gateway_factory(args, plog, bridge_arg, preset):
    return rg.ModelGateway(model, plog, max_concurrency=preset.workers, budget_units=preset.budget_units,
                           reserve_share=lr.RESERVE_SHARE, sleep=lambda seconds: None)


def tools_factory(ledger, pages_dir, bridge_arg, plog, limits):
    return rg.ResearchTools(ledger, pages_dir, search_fn=be.dated_search, fetch_fn=be.dated_page,
                            bridge=bridge_arg, plog=plog, limits=limits, archive_get=lambda url, timeout: "[]")


lr._default_gateway_factory = gateway_factory
lr._default_tools_factory = tools_factory
dr._collect_prediction_markets = lambda out_dir, question, report, meta, plog, model_name="": None
dr._render_research_charts = lambda out_dir, meta, plog, question="": {{}}
sys.exit(dr.main())
"""


@pytest.fixture
def child_pipeline(tmp_path, monkeypatch):
    po = v3.po
    deerflow_dir = tmp_path / "deerflow"
    deerflow_dir.mkdir()
    paths = [str(_REPO / "deerflow_bridge"), str(_REPO / "backend"), str(_REPO / "backend" / "tests")]
    (deerflow_dir / "deerflow_research.py").write_text(_CHILD_SHIM.format(paths=paths), encoding="utf-8")
    for name, value in (("PIPELINE_DATA_DIR", str(tmp_path / "pipelines")),
                        ("UPLOAD_FOLDER", str(tmp_path / "uploads")),
                        ("RESEARCH_MODEL_LEASE_DB", str(tmp_path / "leases.sqlite3")),
                        ("DEERFLOW_DIR", str(deerflow_dir)), ("DEERFLOW_PYTHON", sys.executable),
                        ("DEERFLOW_MODEL", "minimax"), ("DEERFLOW_RESEARCH_LANGUAGE", None),
                        ("RESEARCH_ENGINE", "v3"), ("DEERFLOW_DUAL_TRACK", True),
                        ("RESEARCH_PARALLEL_TRACKS", 1), ("EMBED_WARM_AT_RESEARCH", False),
                        ("PREDICTION_MARKETS_ENABLED", True)):
        monkeypatch.setattr(po.Config, name, value, raising=False)
    monkeypatch.setattr(po, "_sync_deerflow_bridge_if_stale", lambda deerflow_dir: None)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key-not-used")
    monkeypatch.delenv("DEERFLOW_RESEARCH_TIMEOUT", raising=False)

    def run(pid, options):
        po.PipelineManager.ensure_dirs(pid)
        state = po.PipelineState(pipeline_id=pid, prompt="Will global data-centre capacity exceed 250 GW by "
                                 "the end of 2027?", mode="research_only", status="running",
                                 handoff_dir=po.PipelineManager.handoff_dir(pid),
                                 stages={name: po.StageState(name=name) for name in po.RESEARCH_ONLY_BANDS})
        state.options.update({"depth": "standard", "research_language": None, "research_model": None,
                              "actor_intelligence_policy_v1": po.admission_actor_intelligence_policy_v1(),
                              "safety_policy_v1": po.capture_safety_policy_v1("admission"), **options})
        po.PipelineManager.save(state)
        po.PipelineOrchestrator._run(state)
        handoff = Path(state.handoff_dir)
        child_env = json.loads((handoff / "child_env.json").read_text(encoding="utf-8"))
        meta = json.loads((handoff / "meta.json").read_text(encoding="utf-8"))
        return state, handoff, child_env, meta

    return run


def test_research_child_runs_at_the_pinned_cutoff(child_pipeline):
    option = bm.normalize_backtest_request(_request(arm="research_only"))
    state, handoff, child_env, meta = child_pipeline("pipe_backtestchild", {bm.BACKTEST_OPTION: option})
    assert state.status == "completed", state.error
    policy = json.loads(child_env["DRF_BACKTEST_POLICY"])
    assert policy["as_of"] == "2024-11-01" and policy["strict"] is True
    assert policy["audit_path"] == os.path.join(os.path.realpath(handoff), "backtest_audit.jsonl")
    assert child_env["PREDICTION_MARKETS_ENABLED"] == "false"  # the research_only arm
    assert meta["backtest"]["as_of"] == "2024-11-01" and meta["as_of_date"] == "2024-11-01"
    assert meta["backtest"]["audit"]["search"]["action:dropped"] >= 1
    assert (handoff / "backtest_audit.jsonl").is_file()
    sources = json.loads((handoff / "sources.json").read_text(encoding="utf-8"))
    assert sources and all("late.example" not in row["url"] for row in sources)


def test_a_live_child_never_inherits_an_ambient_policy(child_pipeline, monkeypatch):
    monkeypatch.setenv("DRF_BACKTEST_POLICY", '{"as_of": "2024-11-01"}')
    state, _, child_env, meta = child_pipeline("pipe_livechild", {})
    assert state.status == "completed", state.error
    assert child_env == {"DRF_BACKTEST_POLICY": None, "PREDICTION_MARKETS_ENABLED": "true"}
    assert "backtest" not in meta


def test_a_legacy_lane_contract_refuses_a_backtest(tmp_path, monkeypatch):
    po = v3.po
    deerflow_dir = tmp_path / "deerflow"
    deerflow_dir.mkdir()
    (deerflow_dir / "deerflow_research.py").write_text("raise SystemExit('must not run')\n", encoding="utf-8")
    monkeypatch.setattr(po.Config, "DEERFLOW_DIR", str(deerflow_dir), raising=False)
    monkeypatch.setattr(po, "_sync_deerflow_bridge_if_stale", lambda deerflow_dir: None)
    option = bm.normalize_backtest_request(_request())
    with pytest.raises(RuntimeError, match="v3 research engine"):
        po.DeerFlowResearchRunner._run_attempt("q", str(tmp_path / "lane"), on_progress=lambda *a: None,
                                               evidence_only=True, backtest=option)
