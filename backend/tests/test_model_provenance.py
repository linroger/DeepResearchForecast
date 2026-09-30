"""INFRA-8: model provenance, requested vs served model per stage.

Covers the pure helpers (app.utils.model_provenance), the LLMMeter ``model_resolution``
snapshot block, LLMClient's per-call requested label and served id, the research gateway
ledger rows and ``models`` summary, the v3 work-dir identity (resolved ``model_id``,
backward compatible), the orchestrator's run.json stamps and ``run_provenance``, the
forecast.json ``model_provenance`` block, Config.validation_warnings with its preflight
rows, and GET /preflight's unknown-model 400. RECORD_MODEL_PROVENANCE off leaves every
artifact as it was before.

Offline: fake OpenAI clients, a patched CLI subprocess, scripted LangChain stand-ins and
FakeLLMClient; no network, no real LLM.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BRIDGE = os.path.join(os.path.dirname(_BACKEND), "deerflow_bridge")
for _path in (_BACKEND, _BRIDGE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import deerflow_research as dr  # noqa: E402
import linear_research as lr  # noqa: E402
import research_gateway as rg  # noqa: E402
from app.api import research as research_api  # noqa: E402
from app.api import research_bp  # noqa: E402
from app.config import Config  # noqa: E402
from app.services import pipeline_orchestrator as po  # noqa: E402
from app.services import run_shape  # noqa: E402
from app.utils import llm_client as lc  # noqa: E402
from app.utils import model_provenance as mp  # noqa: E402
from app.utils import telemetry as tel  # noqa: E402
from tests.test_final_publish_audit import _agent as _audit_agent  # noqa: E402
from tests.test_final_publish_audit import _prepare as _audit_prepare  # noqa: E402
from tests.test_report_context_pack_wiring import _RouterLLM, _agent  # noqa: E402
from tests.test_report_context_pack_wiring import _run as _finalize_run  # noqa: E402

SystemMessage, HumanMessage, AIMessage, ToolMessage = rg._msg_classes()


@pytest.fixture(autouse=True)
def _provenance_on(monkeypatch):
    monkeypatch.setattr(Config, "RECORD_MODEL_PROVENANCE", True, raising=False)
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", True, raising=False)


def _flag_off(monkeypatch):
    monkeypatch.setattr(Config, "RECORD_MODEL_PROVENANCE", False, raising=False)


# ======================================================================= pure helpers

def test_effective_model_label_follows_what_the_transport_sends():
    assert mp.effective_model_label("claude-cli", "glm-4.6") == "cli-default"
    assert mp.effective_model_label("claude-cli", "gpt-4o-mini") == "cli-default"
    assert mp.effective_model_label("claude-cli", None) == "cli-default"
    assert mp.effective_model_label("claude-cli", "claude-sonnet-4") == "claude-sonnet-4"
    assert mp.effective_model_label("Claude-CLI", "opus") == "opus"
    for model in ("claude-opus-4-8", "gpt-5", None):
        assert mp.effective_model_label("codex-cli", model) == "cli-default"
    assert mp.effective_model_label("kimi", "kimi-k2.7") == "kimi-k2.7"
    assert mp.effective_model_label("openai", None) == "unknown"


def test_claude_cli_guard_is_shared_with_llm_client():
    # One guard decides both the --model argument and the recorded label.
    assert lc.claude_cli_model_arg is mp.claude_cli_model_arg
    assert mp.claude_cli_model_arg("glm-5.3") is None
    assert mp.claude_cli_model_arg(" claude-opus-4-8 ") == "claude-opus-4-8"


def test_served_models_from_claude_envelope_parses_model_usage_keys():
    env = {"modelUsage": {"claude-haiku-4-5": {"outputTokens": 3},
                          "claude-opus-4-8": {"outputTokens": 90}, "": {}}}
    assert mp.served_models_from_claude_envelope(env) == ["claude-haiku-4-5", "claude-opus-4-8"]
    assert mp.served_models_from_claude_envelope({"model": "x"}) == []
    assert mp.served_models_from_claude_envelope({"modelUsage": []}) == []
    assert mp.served_models_from_claude_envelope(None) == []


def test_served_counts_are_capped_with_an_other_bucket():
    served: dict = {}
    for i in range(mp.MAX_SERVED_IDS + 3):
        mp.count_served(served, f"model-{i:02d}")
    mp.count_served(served, "model-00")
    mp.count_served(served, None)
    mp.count_served(served, "  ")
    assert len([k for k in served if k != mp.OTHER_SERVED_KEY]) == mp.MAX_SERVED_IDS
    assert served[mp.OTHER_SERVED_KEY] == 3 and served["model-00"] == 2
    ordered = mp.served_model_list(served)
    assert ordered[0] == "model-00" and ordered[-1] == mp.OTHER_SERVED_KEY


def test_research_resolution_merge_and_stage_record():
    lane = {"model": "glm", "model_id": "glm-5.3",
            "models": {"glm-5.3": {"calls": 4, "served": {"glm-5.3-0930": 3}}}}
    synth = {"model": "glm", "model_id": None,
             "models": {"glm-5.3": {"calls": 2, "served": {"glm-5.3-0930": 1, "glm-5.3-1001": 1}}}}
    merged = mp.merge_research_model_resolutions([None, lane, "junk", synth])
    assert merged == {"model": "glm", "model_id": "glm-5.3",
                      "models": {"glm-5.3": {"calls": 6, "served": {"glm-5.3-0930": 4,
                                                                   "glm-5.3-1001": 1}}}}
    assert mp.merge_research_model_resolutions([None, {}]) == {
        "model": None, "model_id": None, "models": {}}
    assert mp.merge_research_model_resolutions([None]) is None
    assert mp.research_stage_record(merged) == {
        "model_id": "glm-5.3", "served_models": ["glm-5.3-0930", "glm-5.3-1001"]}
    assert mp.research_stage_record(None) == {"model_id": None, "served_models": []}


def test_resolved_block_mapping_matches_run_shape():
    for stage, block in run_shape.RESOLVED_BLOCK_FOR_STAGE.items():
        assert mp.RESOLVED_BLOCK_FOR_STAGE[stage] == block
    assert set(mp.RESOLVED_BLOCK_FOR_STAGE) - set(run_shape.RESOLVED_BLOCK_FOR_STAGE) == {"prepare"}


def test_run_provenance_subset_leaves_the_report_to_the_agent():
    resolved = {
        "research": {"model": "glm", "depth": "deep", "model_id": "glm-5.3", "served_models": []},
        "ontology": {"provider": "kimi", "model_name": "k2", "requested_model": "k2",
                     "served_models": ["k2-0905"]},
        "simulation": {"max_agents": 7, "requested_model": "k2", "served_models": []},
        "report": {"provider": "old", "model_name": "stale"},
        "graph": "not-a-block",
    }
    drift = {"identity": {}, "provenance": {"LLM_MODEL_NAME": ["a", "b"]}}
    prov = mp.run_provenance(resolved, drift)
    assert prov["version"] == "model-provenance/v1" and prov["pin_drift"] == drift
    assert set(prov["stages"]) == {"research", "ontology", "run"}
    assert prov["stages"]["research"] == {"model": "glm", "model_id": "glm-5.3", "served_models": []}
    assert prov["stages"]["run"] == {"requested_model": "k2", "served_models": []}
    assert mp.run_provenance(None, {})["pin_drift"] is None
    full = mp.forecast_model_provenance(prov, {"requested_model": "r", "served_models": ["s"]})
    assert full["stages"]["report"] == {"requested_model": "r", "served_models": ["s"]}
    assert "report" not in prov["stages"]  # the orchestrator's copy is untouched
    assert mp.forecast_model_provenance(None, {}) is None


# ======================================================================= LLMMeter

def test_meter_snapshot_groups_model_resolution_by_stage_and_caps_served_ids():
    rid = "run-infra8-meter"
    try:
        tel.LLMMeter.record("kimi", "k2", 10, 5, 1.0, stage="graph", run_id=rid,
                            served_model="k2-0905")
        tel.LLMMeter.record("kimi", "k2", 10, 5, 1.0, stage="graph", run_id=rid,
                            served_model="k2-0905")
        tel.LLMMeter.record("kimi", "k2", 10, 5, 1.0, stage="graph", run_id=rid)
        tel.LLMMeter.record("claude-cli", "gpt-4o-mini", 10, 5, 1.0, stage="report", run_id=rid,
                            served_model="claude-opus-4-8")
        for i in range(mp.MAX_SERVED_IDS + 2):
            tel.LLMMeter.record("minimax", "M3", 1, 1, 1.0, stage="report", run_id=rid,
                                served_model=f"snap-{i}", requested_model="M3-label")
        snap = tel.LLMMeter.snapshot(rid)
    finally:
        tel.LLMMeter.reset(rid)
    resolution = snap["model_resolution"]
    assert resolution["graph"] == {"kimi:k2": {"calls": 3, "served": {"k2-0905": 2}}}
    assert resolution["report"]["claude-cli:cli-default"] == {
        "calls": 1, "served": {"claude-opus-4-8": 1}}
    capped = resolution["report"]["minimax:M3-label"]
    assert capped["calls"] == mp.MAX_SERVED_IDS + 2
    assert len(capped["served"]) == mp.MAX_SERVED_IDS + 1 and capped["served"]["_other"] == 2
    # by_model keys keep the configured model (unchanged).
    assert set(snap["by_model"]) == {"kimi:k2", "claude-cli:gpt-4o-mini", "minimax:M3"}


def test_meter_without_records_or_with_the_flag_off_has_no_model_resolution(monkeypatch):
    assert "model_resolution" not in tel.LLMMeter.snapshot("run-infra8-empty")
    _flag_off(monkeypatch)
    rid = "run-infra8-off"
    try:
        tel.LLMMeter.record("kimi", "k2", 10, 5, 1.0, stage="graph", run_id=rid,
                            served_model="k2-0905")
        snap = tel.LLMMeter.snapshot(rid)
    finally:
        tel.LLMMeter.reset(rid)
    assert "model_resolution" not in snap and snap["total"]["calls"] == 1


# ======================================================================= LLMClient

def _resp(content="ok", model=None):
    message = SimpleNamespace(content=content, tool_calls=None)
    fields = {"choices": [SimpleNamespace(message=message, finish_reason="stop")],
              "usage": SimpleNamespace(prompt_tokens=7, completion_tokens=3)}
    if model is not None:
        fields["model"] = model
    return SimpleNamespace(**fields)


def _openai_client(create, provider="minimax", model="MiniMax-M3"):
    client = lc.LLMClient(provider=provider, api_key="sk-test",
                          base_url="http://127.0.0.1:1/v1", model=model)
    client._openai_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return client


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.delenv("LLM_FALLBACK_PROVIDER", raising=False)
    monkeypatch.setattr(lc, "_retry_delay", lambda exc, attempt: 0.0)
    for name, value in {"LLM_TIERED_ROUTING": False, "LLM_CACHE_ENABLED": False,
                        "LLM_RUN_BUDGET_TOKENS": 0, "LLM_RUN_BUDGET_USD": 0.0,
                        "LLM_PROVIDER": "minimax"}.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    rid = "run-infra8-client"
    tel.set_run_context(rid, "ontology")
    yield rid
    tel.set_run_context(None)
    tel.LLMMeter.reset(rid)


def test_openai_compatible_call_records_requested_and_served_model(transport):
    client = _openai_client(lambda **kw: _resp(model="MiniMax-M3-20260901"))
    client.chat([{"role": "user", "content": "q"}])
    tools = client.chat_with_tools([{"role": "user", "content": "q"}], tools_schema=[])
    assert tools["served_model"] == "MiniMax-M3-20260901"
    entry = tel.LLMMeter.snapshot(transport)["model_resolution"]["ontology"]["minimax:MiniMax-M3"]
    assert entry == {"calls": 2, "served": {"MiniMax-M3-20260901": 2}}


def test_requested_label_follows_the_serving_provider_and_the_routing_pin(transport, monkeypatch):
    for name, value in {"LLM_TIERED_ROUTING": True, "LLM_FAST_MODEL": "fast-m",
                        "LLM_FAST_PROVIDER": "deepseek", "LLM_FAST_BASE_URL": "http://127.0.0.1:1/v1",
                        "LLM_FAST_API_KEY": "sk-fast"}.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    fast_create = []
    client = _openai_client(lambda **kw: _resp(model="primary-served"))
    # INFRA-6: the fast tier is served by the second client of LLM_FAST_PROVIDER.
    client._fast_openai_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: fast_create.append(kw) or _resp(model="fast-served"))))
    client._fast_openai_provider = "deepseek"
    client.chat([{"role": "user", "content": "q"}], tier="fast")
    # EVAL-10: a pinned client keeps its own provider and model for a fast-tier call.
    pinned = _openai_client(lambda **kw: _resp(model="primary-served"))
    pinned._pinned = True
    pinned.chat([{"role": "user", "content": "q"}], tier="fast")
    resolution = tel.LLMMeter.snapshot(transport)["model_resolution"]["ontology"]
    assert fast_create and fast_create[0]["model"] == "fast-m"
    assert resolution == {"deepseek:fast-m": {"calls": 1, "served": {"fast-served": 1}},
                          "minimax:MiniMax-M3": {"calls": 1, "served": {"primary-served": 1}}}


def test_claude_cli_call_records_cli_default_with_the_envelope_served_model(transport, monkeypatch):
    envelope = {"type": "result", "subtype": "success", "is_error": False, "result": "cli answer",
                "modelUsage": {"claude-haiku-4-5": {"outputTokens": 1},
                               "claude-opus-4-8": {"outputTokens": 40}}}
    monkeypatch.setattr(lc.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=json.dumps(envelope), stderr=""))
    monkeypatch.setattr(Config, "LLM_PROVIDER", "claude-cli", raising=False)
    monkeypatch.setattr(Config, "LLM_TIERED_ROUTING", True, raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_MODEL", "claude-haiku-4-5", raising=False)
    # A non-claude LLM_MODEL_NAME inherited by claude-cli is never passed via --model; the
    # fast-tier alias is ignored by the CLI too, so both calls request the account default.
    client = lc.LLMClient(provider="claude-cli", model="gpt-4o-mini")
    assert client.chat([{"role": "user", "content": "q"}], tier="fast") == "cli answer"
    assert client.chat([{"role": "user", "content": "q"}]) == "cli answer"
    snap = tel.LLMMeter.snapshot(transport)
    assert snap["model_resolution"]["ontology"] == {
        "claude-cli:cli-default": {"calls": 2, "served": {"claude-opus-4-8": 2}}}


# ======================================================================= research gateway

class _ScriptedChatModel:
    """LangChain stand-in: bind/bind_tools return self, invoke answers with ``served``."""

    def __init__(self, model_name, served):
        self.model_name = model_name
        self.served = served

    def bind(self, **kwargs):
        return self

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        meta = {"finish_reason": "stop"}
        if self.served:
            meta["model_name"] = self.served
        return AIMessage(content="answer text", tool_calls=[], invalid_tool_calls=[],
                         usage_metadata={"input_tokens": 50, "output_tokens": 5, "total_tokens": 55},
                         response_metadata=meta)


def _messages():
    return rg.build_messages("You are the engine core.", ["Shared brief."], "Do the task.")


def test_gateway_ledger_rows_carry_model_and_served_model_with_a_models_summary():
    gw = rg.ModelGateway(_ScriptedChatModel("glm-5.3", "glm-5.3-0930"), None, sleep=lambda s: None)
    gw.text(_messages(), kind="write", label="plan")
    gw.text(_messages(), kind="write", label="plan2")
    data = json.loads(json.dumps(gw.ledger.to_dict()))
    assert [(row["model"], row["served_model"]) for row in data["calls"]] == [
        ("glm-5.3", "glm-5.3-0930"), ("glm-5.3", "glm-5.3-0930")]
    assert data["models"] == {"glm-5.3": {"calls": 2, "served": {"glm-5.3-0930": 2}}}
    unreported = rg.ModelGateway(_ScriptedChatModel("glm-5.3", None), None, sleep=lambda s: None)
    unreported.text(_messages(), kind="write", label="plan")
    summary = unreported.ledger.to_dict()
    assert summary["calls"][0]["served_model"] is None
    assert summary["models"] == {"glm-5.3": {"calls": 1, "served": {}}}


def test_ledger_summary_counts_calls_beyond_the_row_cap_and_off_keeps_the_old_shape():
    ledger = rg.UsageLedger()
    ledger.MAX_ROWS = 1
    for i in range(3):
        ledger.record_call(phase="gather", label=f"K{i}", kind="agent", usage={"input": 1},
                           units=1.0, latency_s=0.1, served_by="primary", attempt=1,
                           estimated=False, model="m", served_model="s")
    assert ledger.to_dict()["models"] == {"m": {"calls": 3, "served": {"s": 3}}}
    off = rg.UsageLedger(record_models=False)
    off.record_call(phase="gather", label="K", kind="agent", usage={"input": 1}, units=1.0,
                    latency_s=0.1, served_by="primary", attempt=1, estimated=False,
                    model="m", served_model="s")
    data = off.to_dict()
    assert "models" not in data
    assert set(data["calls"][0]) == {"phase", "label", "kind", "input", "cached", "output",
                                     "latency_s", "served_by", "attempt"}
    off_gw = rg.ModelGateway(_ScriptedChatModel("glm-5.3", "x"), None, sleep=lambda s: None,
                             record_models=False)
    assert off_gw.ledger.record_models is False


# ======================================================================= v3 identity

class _Plog:
    def __init__(self):
        self.lines = []

    def write(self, kind, message):
        self.lines.append((kind, str(message)))

    def text(self):
        return "\n".join(f"[{k}] {m}" for k, m in self.lines)


def _identity(**extra):
    base = {"question_sha256": "q", "depth": "standard", "model": "glm", "language": "English",
            "engine_version": lr.ENGINE_VERSION}
    base.update(extra)
    return base


def _write_state(out: Path, identity: dict) -> None:
    work = out / lr.WORK_DIRNAME
    work.mkdir(parents=True)
    (work / lr.STATE_FILENAME).write_text(json.dumps(
        {"engine_version": lr.ENGINE_VERSION, "identity": identity, "phases": {"plan": {"status": "done"}},
         "kiqs": {}}), encoding="utf-8")


def _writer(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_old_identity_without_model_id_resumes_and_adopts_the_resolved_id(tmp_path):
    out = tmp_path / "out"
    _write_state(out, _identity())
    work, state, resumed = lr._open_work_dir(out, _identity(model_id="glm-5.3"), _writer,
                                             lr._Reporter(_Plog()))
    assert resumed and state.is_done("plan")
    stored = json.loads((work / lr.STATE_FILENAME).read_text(encoding="utf-8"))
    assert stored["identity"]["model_id"] == "glm-5.3"
    # A later resume that cannot resolve the id stays compatible and keeps the stored one.
    work, state, resumed = lr._open_work_dir(out, _identity(), _writer, lr._Reporter(_Plog()))
    assert resumed and state.snapshot()["identity"]["model_id"] == "glm-5.3"


def test_a_different_resolved_model_id_archives_the_work_dir(tmp_path):
    out = tmp_path / "out"
    _write_state(out, _identity(model_id="glm-5.3"))
    plog = _Plog()
    work, state, resumed = lr._open_work_dir(out, _identity(model_id="glm-5.4"), _writer,
                                             lr._Reporter(plog))
    assert not resumed and not state.is_done("plan")
    assert state.snapshot()["identity"]["model_id"] == "glm-5.4"
    stale = [p for p in out.iterdir() if p.name.startswith(f"{lr.WORK_DIRNAME}.stale-")]
    assert len(stale) == 1 and "archived it to" in plog.text()
    # Any other identity difference is still a mismatch even without model ids.
    assert not lr._identity_matches(_identity(depth="deep"), _identity())
    assert lr._identity_matches(_identity(model_id="a"), _identity(model_id="a"))


def _engine(tmp_path, env, served="glm-5.3-0930"):
    out = tmp_path / "out"
    meta: dict = {"status": "running"}
    plog = _Plog()

    def gateway_factory(args, reporter, bridge, preset):
        return rg.ModelGateway(_ScriptedChatModel("glm-5.3", served), reporter, sleep=lambda s: None)

    def tools_factory(ledger, pages_dir, bridge, reporter, limits):
        return rg.ResearchTools(ledger, pages_dir, search_fn=lambda q, n: "", fetch_fn=lambda url: "",
                                bridge=bridge, plog=reporter, limits=limits)

    args = types.SimpleNamespace(model="glm", depth="quick", target_language=None, no_actors=False)
    engine = lr._Engine("Will capacity exceed 250 GW by 2027?", out, args, meta, lr._Reporter(plog),
                        lambda: None, dr, gateway_factory, tools_factory, env)
    return engine, meta


def test_engine_identity_and_meta_carry_the_resolved_model(tmp_path, monkeypatch):
    monkeypatch.setattr(lr, "_resolved_model_id", lambda args: "glm-5.3")
    engine, meta = _engine(tmp_path, {})
    assert engine.state.snapshot()["identity"]["model_id"] == "glm-5.3"
    engine.gateway.text(_messages(), kind="write", label="plan")
    engine.attach_telemetry()
    assert meta["model_resolution"] == {
        "model": "glm", "model_id": "glm-5.3",
        "models": {"glm-5.3": {"calls": 1, "served": {"glm-5.3-0930": 1}}}}


def test_engine_with_the_flag_off_keeps_the_legacy_identity_and_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(lr, "_resolved_model_id", lambda args: pytest.fail("resolved with flag off"))
    engine, meta = _engine(tmp_path, {"RECORD_MODEL_PROVENANCE": "false"})
    assert set(engine.state.snapshot()["identity"]) == {
        "question_sha256", "depth", "model", "language", "engine_version"}
    engine.attach_telemetry()
    assert "model_resolution" not in meta


def test_resolved_model_id_reads_the_stanza_model_field(monkeypatch):
    assert lr._resolved_model_id(types.SimpleNamespace(model="glm")) is None  # no deerflow here

    class _Cfg:
        def get_model_config(self, name):
            return SimpleNamespace(model=" glm-5.3 ") if name == "glm" else None

    deerflow = types.ModuleType("deerflow")
    config_pkg = types.ModuleType("deerflow.config")
    config_pkg.get_app_config = lambda: _Cfg()
    app_config = types.ModuleType("deerflow.config.app_config")
    app_config.AppConfig = SimpleNamespace(from_file=lambda path: _Cfg())
    monkeypatch.setitem(sys.modules, "deerflow", deerflow)
    monkeypatch.setitem(sys.modules, "deerflow.config", config_pkg)
    monkeypatch.setitem(sys.modules, "deerflow.config.app_config", app_config)
    assert lr._resolved_model_id(types.SimpleNamespace(model="glm")) == "glm-5.3"
    assert lr._resolved_model_id(types.SimpleNamespace(model="glm", config="/x.yaml")) == "glm-5.3"
    assert lr._resolved_model_id(types.SimpleNamespace(model="nope")) is None


# ======================================================================= orchestrator

@pytest.fixture
def pipeline_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"), raising=False)
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"), raising=False)
    monkeypatch.setattr(po, "_repo_git_sha", lambda: "gitsha")
    monkeypatch.setattr(po, "_deerflow_ref", lambda: None)
    monkeypatch.setattr(po.PipelineOrchestrator, "_record_stage_artifacts",
                        lambda self, state, stage: None)
    monkeypatch.setattr(po.PipelineOrchestrator, "_flush_run_telemetry",
                        lambda self, state, **kwargs: None)
    for name, value in {"RUN_SHAPE_PIN": True, "RESUME_LINEAGE_GUARDS": True,
                        "RECORD_RUN_MANIFEST": True, "LLM_PROVIDER": "kimi",
                        "LLM_MODEL_NAME": "kimi-k2.7"}.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    pids = []
    yield pids
    for pid in pids:
        tel.LLMMeter.reset(pid)


def _state(pids, pid, **options):
    pids.append(pid)
    po.PipelineManager.ensure_dirs(pid)
    return po.PipelineState(pipeline_id=pid, prompt="q", mode="full", status="running",
                            options=dict(options))


def _manifest(pid):
    with open(po.PipelineManager.manifest_path(pid), encoding="utf-8") as fh:
        return json.load(fh)


RESEARCH_RESOLUTION = {"model": "glm", "model_id": "glm-5.3",
                       "models": {"glm-5.3": {"calls": 9, "served": {"glm-5.3-0930": 9}}}}


def _first_attempt(pid, state):
    orch = po.PipelineOrchestrator()
    orch._write_run_manifest(state)
    orch._record_research_telemetry(state, {"model": "glm", "tokens_in": 0, "tokens_out": 0,
                                            "model_resolution": RESEARCH_RESOLUTION})
    orch._complete_stage(state, po.STAGE_RESEARCH)
    for stage in (po.STAGE_ONTOLOGY, po.STAGE_PREPARE):
        tel.LLMMeter.record("kimi", "kimi-k2.7", 5, 5, 1.0, stage=stage, run_id=pid,
                            served_model="kimi-k2.7-0901")
        orch._complete_stage(state, stage)
    state.options["sim_llm_telemetry"] = {"provider": "minimax", "model": "MiniMax-M3"}
    orch._complete_stage(state, po.STAGE_RUN)
    return orch


def test_recomputed_stages_merge_requested_and_served_models_into_run_json(pipeline_roots):
    pid = "pipe_infra8_stamps"
    state = _state(pipeline_roots, pid, research_model="glm")
    _first_attempt(pid, state)
    resolved = _manifest(pid)["resolved"]
    assert resolved["research"]["model"] == "glm" and resolved["research"]["depth"]
    assert resolved["research"]["model_id"] == "glm-5.3"
    assert resolved["research"]["served_models"] == ["glm-5.3-0930"]
    # INFRA-7's provider pair stays; INFRA-8 merges next to it.
    assert resolved["ontology"] == {"provider": "kimi", "model_name": "kimi-k2.7",
                                    "requested_model": "kimi-k2.7",
                                    "served_models": ["kimi-k2.7-0901"]}
    assert resolved["prepare"] == {"requested_model": "kimi-k2.7",
                                   "served_models": ["kimi-k2.7-0901"]}
    assert resolved["simulation"]["requested_model"] == "MiniMax-M3"
    assert resolved["simulation"]["served_models"] == []
    assert "max_agents" in resolved["simulation"]


def test_reused_stages_keep_the_stamp_of_the_attempt_that_produced_them(pipeline_roots, monkeypatch):
    pid = "pipe_infra8_reuse"
    state = _state(pipeline_roots, pid, research_model="glm")
    _first_attempt(pid, state)
    tel.LLMMeter.reset(pid)
    monkeypatch.setattr(Config, "LLM_PROVIDER", "deepseek", raising=False)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "deepseek-v4", raising=False)
    second = po.PipelineOrchestrator()
    second._write_run_manifest(state)
    for stage in (po.STAGE_RESEARCH, po.STAGE_ONTOLOGY, po.STAGE_PREPARE):
        second._complete_stage(state, stage, reused=True)
    tel.LLMMeter.record("deepseek", "deepseek-v4", 5, 5, 1.0, stage=po.STAGE_GRAPH, run_id=pid,
                        served_model="deepseek-v4-0925")
    second._complete_stage(state, po.STAGE_GRAPH)
    resolved = _manifest(pid)["resolved"]
    assert resolved["research"]["model_id"] == "glm-5.3"
    assert resolved["ontology"]["served_models"] == ["kimi-k2.7-0901"]
    assert resolved["prepare"] == {"requested_model": "kimi-k2.7",
                                   "served_models": ["kimi-k2.7-0901"]}
    assert resolved["graph"] == {"provider": "deepseek", "model_name": "deepseek-v4",
                                 "requested_model": "deepseek-v4",
                                 "served_models": ["deepseek-v4-0925"]}


def test_research_recomputed_without_a_model_resolution_is_recorded_as_unknown(pipeline_roots):
    pid = "pipe_infra8_legacy_research"
    state = _state(pipeline_roots, pid)
    orch = po.PipelineOrchestrator()
    orch._write_run_manifest(state)
    orch._record_research_telemetry(state, {"model": "claude", "tokens_in": 0, "tokens_out": 0})
    orch._complete_stage(state, po.STAGE_RESEARCH)
    research = _manifest(pid)["resolved"]["research"]
    assert research["model_id"] is None and research["served_models"] == []


def test_run_provenance_for_the_report_agent(pipeline_roots):
    pid = "pipe_infra8_runprov"
    state = _state(pipeline_roots, pid, research_model="glm")
    orch = _first_attempt(pid, state)
    state.options["run_shape_drift"] = {"identity": {}, "provenance": {"LLM_MODEL_NAME": ["a", "b"]}}
    agent = SimpleNamespace()
    orch._assign_run_provenance(agent, state)
    prov = agent.run_provenance
    assert prov["version"] == "model-provenance/v1"
    assert prov["pin_drift"] == state.options["run_shape_drift"]
    assert set(prov["stages"]) == {"research", "ontology", "graph", "prepare", "run"}
    # GRAPH never ran: its run.json block is the unstamped skeleton, carried as-is.
    assert prov["stages"]["graph"] == {"provider": None, "model_name": None}
    assert prov["stages"]["research"]["model_id"] == "glm-5.3"
    assert prov["stages"]["run"] == {"requested_model": "MiniMax-M3", "served_models": []}


def test_generate_stage_report_hands_the_agent_its_run_provenance(pipeline_roots, monkeypatch):
    pid = "pipe_infra8_stage_report"
    state = _state(pipeline_roots, pid, research_model="glm")
    orch = _first_attempt(pid, state)
    monkeypatch.setattr(po.PipelineOrchestrator, "_report_ledger_context",
                        lambda self, *a, **k: {"pipeline_id": pid})
    seen = {}

    class _Agent:
        def generate_report(self, progress_callback=None, report_id=None):
            seen["provenance"] = self.run_provenance
            return "report"

    assert orch._generate_stage_report(state, _Agent(), "sim1", report_id="r1",
                                       progress_callback=lambda *a: None) == "report"
    assert seen["provenance"]["stages"]["ontology"]["requested_model"] == "kimi-k2.7"


def test_flag_off_leaves_run_json_and_the_agent_as_before(pipeline_roots, monkeypatch):
    _flag_off(monkeypatch)
    pid = "pipe_infra8_off"
    state = _state(pipeline_roots, pid, research_model="glm")
    orch = _first_attempt(pid, state)
    resolved = _manifest(pid)["resolved"]
    assert "prepare" not in resolved
    assert resolved["ontology"] == {"provider": "kimi", "model_name": "kimi-k2.7"}
    assert "model_id" not in resolved["research"] and "requested_model" not in resolved["simulation"]
    assert "model_resolution" not in tel.LLMMeter.snapshot(pid)
    agent = SimpleNamespace()
    orch._assign_run_provenance(agent, state)
    assert not hasattr(agent, "run_provenance")


# ======================================================================= forecast.json

@pytest.fixture
def forecast_env(monkeypatch, tmp_path):
    """The report-stage settings of test_report_context_pack_wiring's report_env."""
    from app.services import forecast_ledger
    from app.services.report_agent import ReportManager

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


RUN_PROVENANCE = {"version": "model-provenance/v1",
                  "stages": {"research": {"model": "glm", "model_id": "glm-5.3", "served_models": []}},
                  "pin_drift": None}


def test_forecast_json_carries_model_provenance_when_run_provenance_is_set(forecast_env):
    rid = "run-infra8-report"
    llm = _RouterLLM()
    agent = _agent(llm)
    agent.run_provenance = json.loads(json.dumps(RUN_PROVENANCE))
    tel.set_run_context(rid, "report")
    try:
        tel.LLMMeter.record("fake", "fake-1", 5, 5, 1.0, served_model="fake-1-0930")
        _agent_out, _llm, early, final = _finalize_run(forecast_env, "report_prov_on", agent=agent)
    finally:
        tel.set_run_context(None)
        tel.LLMMeter.reset(rid)
    for forecast in (early, final):
        block = forecast["model_provenance"]
        assert block["version"] == "model-provenance/v1" and block["pin_drift"] is None
        assert block["stages"]["research"]["model_id"] == "glm-5.3"
        assert block["stages"]["report"] == {"provider": "fake", "model_name": "fake-1",
                                             "requested_model": "fake-1",
                                             "served_models": ["fake-1-0930"]}
    assert "report" not in agent.run_provenance["stages"]


def test_forecast_json_has_no_model_provenance_without_run_provenance(forecast_env):
    _agent_out, _llm, early, final = _finalize_run(forecast_env, "report_prov_absent")
    assert "model_provenance" not in early and "model_provenance" not in final


def test_flag_off_forecast_json_has_no_model_provenance(forecast_env, monkeypatch):
    _flag_off(monkeypatch)
    agent = _agent(_RouterLLM())
    agent.run_provenance = json.loads(json.dumps(RUN_PROVENANCE))
    _agent_out, _llm, early, final = _finalize_run(forecast_env, "report_prov_off", agent=agent)
    assert "model_provenance" not in early and "model_provenance" not in final


def test_final_audit_seals_the_refreshed_model_provenance(monkeypatch, tmp_path):
    report_id = "report_infra8_audit"
    md = "# Forecast\n\nRevenue could reach 65% by 2030.\n"
    folder = _audit_prepare(monkeypatch, tmp_path, report_id, md)
    agent = _audit_agent()
    agent.llm = SimpleNamespace(provider="kimi", model="kimi-k2.7")
    agent.run_provenance = json.loads(json.dumps(RUN_PROVENANCE))
    audit = agent._audit_final_published_markdown(report_id, SimpleNamespace(markdown_content=md))
    raw = Path(folder, "forecast.json").read_bytes()
    forecast = json.loads(raw)
    assert forecast["model_provenance"]["stages"]["report"]["requested_model"] == "kimi-k2.7"
    assert audit["forecast_sha256"] == hashlib.sha256(raw).hexdigest()

    agent.run_provenance = None
    Path(folder, "forecast.json").write_text(json.dumps({"scenarios": [], "quality": {}}),
                                             encoding="utf-8")
    agent._audit_final_published_markdown(report_id, SimpleNamespace(markdown_content=md))
    assert "model_provenance" not in json.loads(Path(folder, "forecast.json").read_text("utf-8"))


# ======================================================================= config / preflight

def test_validation_warnings_flag_settings_that_silently_do_nothing(monkeypatch):
    monkeypatch.delenv("LLM_FALLBACK_MODEL", raising=False)
    monkeypatch.delenv("LLM_FALLBACK_PROVIDER", raising=False)
    monkeypatch.setattr(Config, "LLM_PROVIDER", "kimi", raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_MODEL", None, raising=False)
    monkeypatch.setattr(Config, "LLM_STRONG_MODEL", None, raising=False)
    assert Config.validation_warnings() == []

    monkeypatch.setenv("LLM_FALLBACK_MODEL", "glm-5.3")
    warnings = Config.validation_warnings()
    assert len(warnings) == 1 and "LLM_FALLBACK_PROVIDER" in warnings[0]
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "glm")
    assert Config.validation_warnings() == []

    monkeypatch.setattr(Config, "LLM_PROVIDER", "claude-cli", raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_MODEL", "MiniMax-M3", raising=False)
    monkeypatch.setattr(Config, "LLM_STRONG_MODEL", "claude-opus-4-8", raising=False)
    warnings = Config.validation_warnings()
    assert len(warnings) == 1 and "LLM_FAST_MODEL=MiniMax-M3" in warnings[0]
    assert "cli-default" in warnings[0]
    monkeypatch.setattr(Config, "LLM_PROVIDER", "codex-cli", raising=False)
    assert len(Config.validation_warnings()) == 2


def test_preflight_report_lists_validation_warnings_as_warn_rows(monkeypatch):
    scripts = os.path.join(_BACKEND, "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import preflight

    monkeypatch.setattr(preflight, "preflight_pipeline", lambda **kw: [])
    monkeypatch.setattr(Config, "validation_warnings", classmethod(lambda cls: ["fallback without provider"]))
    report = preflight.environment_report(mode="full", model="glm")
    rows = [c for c in report["checks"] if c["id"].startswith("config.warning.")]
    assert rows == [{"id": "config.warning.0", "severity": "warn", "ok": False,
                     "message": "fallback without provider", "fix": None}]
    assert report["exit_code"] == 2 and report["ready"] is True


@pytest.fixture
def api_client(monkeypatch):
    monkeypatch.setattr(research_api, "preflight_pipeline", lambda **kwargs: [])
    app = Flask(__name__)
    app.register_blueprint(research_bp, url_prefix="/api/research")
    return app.test_client()


def test_preflight_endpoint_refuses_an_unknown_model(api_client):
    resp = api_client.get("/api/research/preflight?model=unknown")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    assert all(name in body["error"] for name in Config.SUPPORTED_DEERFLOW_MODELS)
    assert api_client.get("/api/research/preflight?model=unknown&format=full").status_code == 400
    ok = api_client.get("/api/research/preflight?model=GLM")
    assert ok.status_code == 200 and ok.get_json()["data"]["ready"] is True
    assert api_client.get("/api/research/preflight").status_code == 200
