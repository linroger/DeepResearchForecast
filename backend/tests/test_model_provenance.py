"""INFRA-8: model provenance, requested vs served model per stage.

Covers the pure helpers (app.utils.model_provenance), the LLMMeter ``model_resolution``
snapshot block, LLMClient's per-call requested label and served id, the research gateway
ledger rows and ``models`` summary, the v3 work-dir identity (resolved ``model_id``,
backward compatible), the orchestrator's run.json stamps (the simulation child runs of one
simulation included) and ``run_provenance``, the forecast.json ``model_provenance`` block,
Config.validation_warnings with its preflight rows, and GET /preflight's unknown-model 400
and model normalisation. RECORD_MODEL_PROVENANCE off leaves every artifact as it was before.

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


def test_stage_record_follows_the_requested_labels_the_calls_recorded():
    entries = {"minimax:MiniMax-M3-Pro": {"calls": 5, "served": {"MiniMax-M3-Pro-0901": 5}},
               "deepseek:fast-m": {"calls": 2, "served": {"fast-m-0925": 2}},
               "minimax:MiniMax-M3": {"calls": 2, "served": {}},
               "junk": "not-an-entry", "zero:calls": {"calls": 0}}
    # EVAL-10 tier routing: the stage sent the strong model, not LLM_MODEL_NAME.
    record = mp.stage_record(entries, "minimax", "MiniMax-M3")
    assert record == {
        "requested_model": "MiniMax-M3-Pro", "requested_source": "metered",
        "requested_models": ["minimax:MiniMax-M3-Pro", "deepseek:fast-m", "minimax:MiniMax-M3"],
        "served_models": ["MiniMax-M3-Pro-0901", "fast-m-0925"],
        "model_resolution": {
            "minimax:MiniMax-M3-Pro": {"calls": 5, "served": {"MiniMax-M3-Pro-0901": 5}},
            "deepseek:fast-m": {"calls": 2, "served": {"fast-m-0925": 2}},
            "minimax:MiniMax-M3": {"calls": 2, "served": {}}}}
    # The per-request map keeps the order of requested_models (which id answered which request).
    assert list(record["model_resolution"]) == record["requested_models"]
    # No recorded call: the effective label of the configured pair, marked as configured and
    # nothing else claimed.
    assert mp.stage_record({}, "claude-cli", "glm-5.3") == {
        "requested_model": "cli-default", "requested_source": "configured",
        "requested_models": [], "served_models": [], "model_resolution": {}}
    assert mp.stage_record(None, "kimi", "kimi-k2.7")["requested_model"] == "kimi-k2.7"
    # A label may itself contain ':' (the provider part never does).
    assert mp.requested_label_of("openrouter:vendor/model:free") == "vendor/model:free"
    assert mp.resolution_entries({"graph": entries}, "graph")["deepseek:fast-m"]["calls"] == 2
    assert mp.resolution_entries({"graph": entries}, "report") == {}
    assert mp.resolution_entries(None, "graph") == {}
    merged: dict = {}
    mp.merge_resolution_entries(merged, {"a:x": {"calls": 1, "served": {"x1": 1}}})
    mp.merge_resolution_entries(merged, {"a:x": {"calls": 2, "served": {"x1": 1, "x2": 1}}})
    assert merged == {"a:x": {"calls": 3, "served": {"x1": 2, "x2": 1}}}


def test_reused_stage_record_fills_only_a_stamped_pair_without_model_keys():
    unknown_served = {"requested_source": "configured", "requested_models": [],
                      "served_models": [], "model_resolution": {}}
    assert mp.reused_stage_record({"provider": "kimi", "model_name": "kimi-k2.7"}) == {
        "requested_model": "kimi-k2.7", **unknown_served}
    assert mp.reused_stage_record({"provider": "claude-cli", "model_name": "glm"}) == {
        "requested_model": "cli-default", **unknown_served}
    assert mp.reused_stage_record({"provider": "kimi", "model_name": "k", "requested_model": "k"}) is None
    assert mp.reused_stage_record({"provider": None, "model_name": None}) is None
    assert mp.reused_stage_record(None) is None


def test_sim_stash_keys_merge_the_resumed_child_runs_of_one_simulation_once_per_token():
    first = {"minimax:MiniMax-M3": {"calls": 40, "served": {"MiniMax-M3-0901": 40}}}
    resumed = {"deepseek:deepseek-v4": {"calls": 10, "served": {"deepseek-v4-0925": 10}}}
    keys = mp.sim_stash_model_keys(None, "sim_a", "tok-1", first, resumed=False)
    assert keys == {"simulation_id": "sim_a", "model_resolution_tokens": ["tok-1"],
                    "model_resolution": first}
    # A SIM_RESUME child run of the same simulation adds its calls to the earlier rounds'.
    merged = mp.sim_stash_model_keys({"provider": "minimax", **keys}, "sim_a", "tok-2", resumed,
                                     resumed=True)
    assert merged == {"simulation_id": "sim_a", "model_resolution_tokens": ["tok-1", "tok-2"],
                      "model_resolution": {**first, **resumed}}
    # The same child run again (its marker save failed and rolled back) adds nothing.
    assert mp.sim_stash_model_keys(merged, "sim_a", "tok-2", resumed, resumed=True) == merged
    # A fresh start of the same simulation discarded the earlier rounds: it replaces them,
    # and recording it again changes nothing either.
    fresh = {"simulation_id": "sim_a", "model_resolution_tokens": ["tok-3"],
             "model_resolution": resumed}
    assert mp.sim_stash_model_keys(merged, "sim_a", "tok-3", resumed, resumed=False) == fresh
    assert mp.sim_stash_model_keys(fresh, "sim_a", "tok-3", resumed, resumed=False) == fresh
    # Another simulation, or a stash without the stamp, starts afresh even when resumed.
    assert mp.sim_stash_model_keys(merged, "sim_b", "tok-4", resumed, resumed=True) == {
        "simulation_id": "sim_b", "model_resolution_tokens": ["tok-4"], "model_resolution": resumed}
    assert mp.sim_stash_model_keys({"simulation_id": "sim_a", "model_resolution": first},
                                   "sim_a", "tok-5", None, resumed=True) == {
        "simulation_id": "sim_a", "model_resolution_tokens": ["tok-5"]}
    # The prior stash is never mutated in place.
    assert keys["model_resolution_tokens"] == ["tok-1"]
    assert keys["model_resolution"] == {
        "minimax:MiniMax-M3": {"calls": 40, "served": {"MiniMax-M3-0901": 40}}}
    assert mp.sim_stash_of(merged, "sim_a") is merged
    assert mp.sim_stash_of(merged, "sim_b") is None and mp.sim_stash_of(merged, None) is None
    assert mp.sim_stash_of({"model_resolution": first}, "sim_a") is None


def test_resolved_block_mapping_matches_run_shape():
    for stage, block in run_shape.RESOLVED_BLOCK_FOR_STAGE.items():
        assert mp.RESOLVED_BLOCK_FOR_STAGE[stage] == block
    assert set(mp.RESOLVED_BLOCK_FOR_STAGE) - set(run_shape.RESOLVED_BLOCK_FOR_STAGE) == {"prepare"}


def test_run_provenance_subset_leaves_the_report_to_the_agent():
    resolved = {
        "research": {"model": "glm", "depth": "deep", "model_id": "glm-5.3", "served_models": []},
        "ontology": {"provider": "kimi", "model_name": "k2", "requested_model": "k2",
                     "requested_source": "metered", "served_models": ["k2-0905"],
                     "model_resolution": {"kimi:k2": {"calls": 1, "served": {"k2-0905": 1}}}},
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
    assert prov["stages"]["ontology"] == resolved["ontology"]
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


def test_aggregate_records_never_count_in_model_resolution():
    rid = "run-infra8-aggregate"
    try:
        tel.LLMMeter.record("claude-cli", "claude-cli", 900, 300, 1.0, stage="run", run_id=rid,
                            aggregate=True)
        tel.LLMMeter.record("claude-cli", "claude", 900, 300, 1.0, stage="research", run_id=rid,
                            aggregate=True)
        snap = tel.LLMMeter.snapshot(rid)
    finally:
        tel.LLMMeter.reset(rid)
    assert "model_resolution" not in snap
    # Spend and by_model are recorded exactly as before.
    assert snap["total"]["calls"] == 2
    assert set(snap["by_model"]) == {"claude-cli:claude-cli", "claude-cli:claude"}


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
    assert engine.gateway.ledger.record_models is True
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
    # The factory built a recording ledger; the engine's flag (the env the parent forwards
    # from its Config) decides, so usage.json keeps its old rows and has no models summary.
    assert engine.gateway.ledger.record_models is False
    engine.gateway.text(_messages(), kind="write", label="plan")
    engine.attach_telemetry()
    assert "model_resolution" not in meta
    usage = json.loads((engine.work / "usage.json").read_text(encoding="utf-8"))
    assert "models" not in usage and len(usage["calls"]) == 1
    assert not {"model", "served_model"} & set(usage["calls"][0])


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
# The simulation child's own per-call record (sim_llm_telemetry.json model_resolution).
SIM_RESOLUTION = {"minimax:MiniMax-M3": {"calls": 40, "served": {"MiniMax-M3-0901": 40}},
                  "minimax:MiniMax-M3-Pro": {"calls": 3, "served": {}}}
RUN_RECORD = {"requested_model": "MiniMax-M3", "requested_source": "metered",
              "requested_models": ["minimax:MiniMax-M3", "minimax:MiniMax-M3-Pro"],
              "served_models": ["MiniMax-M3-0901"], "model_resolution": SIM_RESOLUTION}
SIM_ID = "sim_infra8_first"
# The RUN stash _record_sim_run_telemetry leaves for SIM_ID's child run.
SIM_STASH = {"provider": "minimax", "model": "MiniMax-M3-0901", "simulation_id": SIM_ID,
             "model_resolution_tokens": ["tok-first"], "model_resolution": SIM_RESOLUTION}


def _kimi_record(served):
    """What a recomputed stage of the pipeline_roots provider (kimi / kimi-k2.7) records."""
    return {"requested_model": "kimi-k2.7", "requested_source": "metered",
            "requested_models": ["kimi:kimi-k2.7"], "served_models": [served],
            "model_resolution": {"kimi:kimi-k2.7": {"calls": 1, "served": {served: 1}}}}


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
    state.simulation_id = SIM_ID
    state.options["sim_llm_telemetry"] = json.loads(json.dumps(SIM_STASH))
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
                                    **_kimi_record("kimi-k2.7-0901")}
    assert resolved["prepare"] == _kimi_record("kimi-k2.7-0901")
    assert {key: resolved["simulation"][key] for key in RUN_RECORD} == RUN_RECORD
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
    assert resolved["prepare"] == _kimi_record("kimi-k2.7-0901")
    assert resolved["graph"] == {
        "provider": "deepseek", "model_name": "deepseek-v4", "requested_model": "deepseek-v4",
        "requested_source": "metered", "requested_models": ["deepseek:deepseek-v4"],
        "served_models": ["deepseek-v4-0925"],
        "model_resolution": {"deepseek:deepseek-v4": {"calls": 1,
                                                      "served": {"deepseek-v4-0925": 1}}}}


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
    assert prov["stages"]["run"] == RUN_RECORD


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


def _tiered_ontology_call(pipeline_roots, monkeypatch, pid):
    """One ONTOLOGY call under LLM_TIERED_ROUTING with LLM_STRONG_MODEL set, then the stage's
    completion. Returns the models the transport sent and run.json's ontology block."""
    state = _state(pipeline_roots, pid)
    monkeypatch.delenv("LLM_FALLBACK_PROVIDER", raising=False)
    for name, value in {"LLM_PROVIDER": "minimax", "LLM_MODEL_NAME": "MiniMax-M3",
                        "LLM_TIERED_ROUTING": True, "LLM_STRONG_MODEL": "MiniMax-M3-Pro",
                        "LLM_FAST_MODEL": None, "LLM_CACHE_ENABLED": False,
                        "LLM_RUN_BUDGET_TOKENS": 0, "LLM_RUN_BUDGET_USD": 0.0}.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    sent = []
    client = _openai_client(lambda **kw: sent.append(kw["model"]) or _resp(model="MiniMax-M3-Pro-0901"))
    orch = po.PipelineOrchestrator()
    orch._write_run_manifest(state)
    tel.set_run_context(pid, po.STAGE_ONTOLOGY)
    try:
        client.chat([{"role": "user", "content": "q"}])
    finally:
        tel.set_run_context(None)
    orch._complete_stage(state, po.STAGE_ONTOLOGY)
    return sent, _manifest(pid)["resolved"]["ontology"]


def test_stage_requested_model_follows_tier_routing(pipeline_roots, monkeypatch):
    """LLM_TIERED_ROUTING (default on) sends LLM_STRONG_MODEL: run.json names that model as
    requested, not LLM_MODEL_NAME, next to INFRA-7's configured pair."""
    sent, ontology = _tiered_ontology_call(pipeline_roots, monkeypatch, "pipe_infra8_tiered")
    assert sent == ["MiniMax-M3-Pro"]
    assert ontology == {
        "provider": "minimax", "model_name": "MiniMax-M3",
        "requested_model": "MiniMax-M3-Pro", "requested_source": "metered",
        "requested_models": ["minimax:MiniMax-M3-Pro"], "served_models": ["MiniMax-M3-Pro-0901"],
        "model_resolution": {"minimax:MiniMax-M3-Pro": {"calls": 1,
                                                        "served": {"MiniMax-M3-Pro-0901": 1}}}}


def test_without_llm_telemetry_a_stage_marks_its_configured_pair(pipeline_roots, monkeypatch):
    """LLM_TELEMETRY_ENABLED=false meters no call, so the stage cannot know the tier-routed
    model it sent: run.json names the configured pair and says so (requested_source)."""
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", False, raising=False)
    sent, ontology = _tiered_ontology_call(pipeline_roots, monkeypatch, "pipe_infra8_no_meter")
    assert sent == ["MiniMax-M3-Pro"]
    assert ontology == {"provider": "minimax", "model_name": "MiniMax-M3",
                        "requested_model": "MiniMax-M3", "requested_source": "configured",
                        "requested_models": [], "served_models": [], "model_resolution": {}}


def test_run_requested_model_is_never_the_sim_telemetry_model(pipeline_roots, monkeypatch):
    """A claude-cli simulation's telemetry 'model' is the CLI bridge's provider label
    ('claude-cli'); without the child's own record RUN names what oasis_llm sends."""
    monkeypatch.setattr(Config, "LLM_PROVIDER", "claude-cli", raising=False)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "glm-5.3", raising=False)
    state = _state(pipeline_roots, "pipe_infra8_cli_sim",
                   sim_llm_telemetry={"provider": "claude-cli", "model": "claude-cli", "calls": 9,
                                      "simulation_id": "sim_cli"})
    state.simulation_id = "sim_cli"
    record = po.PipelineOrchestrator()._stage_model_record(state, po.STAGE_RUN)
    assert record == {"requested_model": "cli-default", "requested_source": "configured",
                      "requested_models": [], "served_models": [], "model_resolution": {}}
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "claude-sonnet-4-5", raising=False)
    record = po.PipelineOrchestrator()._stage_model_record(state, po.STAGE_RUN)
    assert record["requested_model"] == "claude-sonnet-4-5"
    # An OpenAI-compatible simulation's dominant served snapshot id is not the request either.
    monkeypatch.setattr(Config, "LLM_PROVIDER", "minimax", raising=False)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "MiniMax-M3", raising=False)
    state.options["sim_llm_telemetry"] = {"provider": "minimax", "model": "MiniMax-M3-0901",
                                          "simulation_id": "sim_cli"}
    assert po.PipelineOrchestrator()._stage_model_record(state, po.STAGE_RUN)["requested_model"] == "MiniMax-M3"
    # A provider the parent guessed from the model name is not trusted as the provider.
    state.options["sim_llm_telemetry"] = {"provider": "claude", "model": "claude",
                                          "simulation_id": "sim_cli"}
    assert po.PipelineOrchestrator()._stage_model_record(state, po.STAGE_RUN)["requested_model"] == "MiniMax-M3"


@pytest.fixture
def sim_root(tmp_path, monkeypatch):
    from app.services.simulation_runner import SimulationRunner

    root = tmp_path / "simulations"
    root.mkdir()
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(root))
    monkeypatch.setattr(SimulationRunner, "_run_states", {})
    return root


def _write_sim_telemetry(sim_root, sim_id, **fields):
    sim_dir = sim_root / sim_id
    sim_dir.mkdir()
    payload = {"schema_version": "sim-llm-telemetry/v1", "simulation_id": sim_id,
               "meter_run_token": f"tok-{sim_id}", "provider": "claude-cli", "model": "claude-cli",
               "calls": 12, "prompt_tokens": 900, "completion_tokens": 300, "total_tokens": 1200,
               "by_model": {"claude-cli": {"calls": 12}}, "wall_s": 60.0}
    payload.update(fields)
    (sim_dir / "sim_llm_telemetry.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_run_state(sim_root, sim_id, resumed_from_round):
    """The run_state.json a child start leaves (SimulationRunner.start_simulation), read back
    from disk as a later attempt would."""
    from app.services.simulation_runner import SimulationRunner

    (sim_root / sim_id / "run_state.json").write_text(json.dumps(
        {"runner_status": "completed", "resumed_from_round": resumed_from_round}),
        encoding="utf-8")
    SimulationRunner._run_states.pop(sim_id, None)


def test_sim_ingestion_stashes_the_child_record_and_meters_no_bogus_resolution(
        pipeline_roots, sim_root):
    pid = "pipe_infra8_sim_ingest"
    state = _state(pipeline_roots, pid)
    child_record = {"claude-cli:cli-default": {"calls": 12, "served": {"claude-opus-4-8": 12}}}
    _write_sim_telemetry(sim_root, "sim_infra8", model_resolution=child_record)
    state.simulation_id = "sim_infra8"
    orch = po.PipelineOrchestrator()
    orch._write_run_manifest(state)
    orch._record_sim_run_telemetry(state, "sim_infra8")
    snap = tel.LLMMeter.snapshot(pid)
    # The synthetic aggregate keeps its spend and by_model key but claims no requested model.
    assert snap["by_stage"]["run"]["calls"] == 1 and "claude-cli:claude-cli" in snap["by_model"]
    assert "model_resolution" not in snap
    stash = state.options["sim_llm_telemetry"]
    assert stash["model_resolution"] == child_record
    assert stash["simulation_id"] == "sim_infra8"
    assert stash["model_resolution_tokens"] == ["tok-sim_infra8"]
    orch._complete_stage(state, po.STAGE_RUN)
    simulation = _manifest(pid)["resolved"]["simulation"]
    assert simulation["requested_model"] == "cli-default"
    assert simulation["requested_models"] == ["claude-cli:cli-default"]
    assert simulation["served_models"] == ["claude-opus-4-8"]


def test_sim_ingestion_with_the_flag_off_stashes_as_before(pipeline_roots, sim_root, monkeypatch):
    _flag_off(monkeypatch)
    state = _state(pipeline_roots, "pipe_infra8_sim_off")
    _write_sim_telemetry(sim_root, "sim_infra8_off", model_resolution={
        "claude-cli:cli-default": {"calls": 12, "served": {}}})
    po.PipelineOrchestrator()._record_sim_run_telemetry(state, "sim_infra8_off")
    assert set(state.options["sim_llm_telemetry"]) == {
        "provider", "model", "calls", "errors", "prompt_tokens", "completion_tokens",
        "total_tokens", "by_source", "wall_s"}


FIRST_CHILD = {"minimax:MiniMax-M3": {"calls": 30, "served": {"MiniMax-M3-0901": 30}}}
SECOND_CHILD = {"minimax:MiniMax-M3-Pro": {"calls": 10, "served": {"MiniMax-M3-Pro-0901": 10}}}


def _two_child_runs(pipeline_roots, sim_root, pid, resumed_from_round):
    """Two child runs of one simulation, the second started in a later attempt after the
    operator switched LLM_MODEL_NAME (``resumed_from_round`` None = a fresh start). Returns
    the RUN stash and run.json's simulation block after RUN completes."""
    state = _state(pipeline_roots, pid)
    state.simulation_id = "sim_two_runs"
    _write_sim_telemetry(sim_root, "sim_two_runs", provider="minimax", model="MiniMax-M3-0901",
                         model_resolution=FIRST_CHILD)
    _write_run_state(sim_root, "sim_two_runs", None)
    orch = po.PipelineOrchestrator()
    orch._write_run_manifest(state)
    orch._record_sim_run_telemetry(state, "sim_two_runs")
    # The second child rewrites the telemetry file with its own counters and token.
    tel_path = sim_root / "sim_two_runs" / "sim_llm_telemetry.json"
    payload = json.loads(tel_path.read_text(encoding="utf-8"))
    payload.update(meter_run_token="tok-second", model="MiniMax-M3-Pro-0901",
                   model_resolution=SECOND_CHILD)
    tel_path.write_text(json.dumps(payload), encoding="utf-8")
    _write_run_state(sim_root, "sim_two_runs", resumed_from_round)
    orch._record_sim_run_telemetry(state, "sim_two_runs")
    orch._record_sim_run_telemetry(state, "sim_two_runs")  # a later boundary: already recorded
    stash = state.options["sim_llm_telemetry"]
    assert stash["model"] == "MiniMax-M3-Pro-0901"  # the token summary is the latest child's
    assert tel.LLMMeter.snapshot(pid)["by_stage"]["run"]["calls"] == 2  # both spends metered
    orch._complete_stage(state, po.STAGE_RUN)
    return stash, _manifest(pid)["resolved"]["simulation"]


def test_a_resumed_simulation_child_adds_to_the_run_record(pipeline_roots, sim_root):
    """SIM_RESUME starts a new child (new meter_run_token) whose telemetry covers only the
    resumed rounds; RUN keeps the model that served the earlier rounds as well."""
    stash, simulation = _two_child_runs(pipeline_roots, sim_root, "pipe_infra8_sim_resume", 6)
    assert stash["model_resolution_tokens"] == ["tok-sim_two_runs", "tok-second"]
    assert stash["model_resolution"] == {**FIRST_CHILD, **SECOND_CHILD}
    assert simulation["requested_model"] == "MiniMax-M3"
    assert simulation["requested_models"] == ["minimax:MiniMax-M3", "minimax:MiniMax-M3-Pro"]
    assert simulation["served_models"] == ["MiniMax-M3-0901", "MiniMax-M3-Pro-0901"]
    assert simulation["model_resolution"] == {**FIRST_CHILD, **SECOND_CHILD}


def test_a_fresh_restart_of_the_simulation_replaces_the_run_record(pipeline_roots, sim_root):
    """Without a resume the restarted child discards the earlier rounds (SIM_RESUME off, the
    default), so their model no longer describes the RUN output."""
    stash, simulation = _two_child_runs(pipeline_roots, sim_root, "pipe_infra8_sim_restart", None)
    assert stash["model_resolution_tokens"] == ["tok-second"]
    assert stash["model_resolution"] == SECOND_CHILD
    assert simulation["requested_model"] == "MiniMax-M3-Pro"
    assert simulation["requested_models"] == ["minimax:MiniMax-M3-Pro"]
    assert simulation["served_models"] == ["MiniMax-M3-Pro-0901"]
    assert simulation["model_resolution"] == SECOND_CHILD


def test_run_record_ignores_the_stash_of_an_earlier_simulation(pipeline_roots, sim_root):
    """A recomputed RUN whose telemetry is unreadable does not inherit the model record of
    the simulation an earlier attempt ran."""
    pid = "pipe_infra8_stale_stash"
    state = _state(pipeline_roots, pid, sim_llm_telemetry=json.loads(json.dumps(SIM_STASH)))
    state.simulation_id = "sim_rebuilt"
    orch = po.PipelineOrchestrator()
    orch._write_run_manifest(state)
    orch._record_sim_run_telemetry(state, "sim_rebuilt")  # no sim_llm_telemetry.json: no-op
    assert state.options["sim_llm_telemetry"]["simulation_id"] == SIM_ID
    assert orch._reused_stage_model_record(state, po.STAGE_RUN, {}) is None
    orch._complete_stage(state, po.STAGE_RUN)
    simulation = _manifest(pid)["resolved"]["simulation"]
    # The configured pair of this attempt (pipeline_roots: kimi / kimi-k2.7), not SIM_STASH's.
    assert {key: simulation[key] for key in RUN_RECORD} == {
        "requested_model": "kimi-k2.7", "requested_source": "configured",
        "requested_models": [], "served_models": [], "model_resolution": {}}


def test_research_synthetic_records_claim_no_requested_model(pipeline_roots):
    pid = "pipe_infra8_research_meter"
    state = _state(pipeline_roots, pid)
    po.PipelineOrchestrator()._record_research_telemetry(
        state, {"model": "claude", "tokens_in": 900, "tokens_out": 300})
    assert po._flush_failed_research_attempt_spend(
        {"model": "glm", "tokens_in": 50, "tokens_out": 10}, "failed", run_id=pid)
    snap = tel.LLMMeter.snapshot(pid)
    assert snap["by_stage"]["research"]["calls"] == 2
    assert "model_resolution" not in snap


def test_reused_stages_without_model_keys_are_filled_from_their_stamp(pipeline_roots, monkeypatch):
    """INFRA-7 restamps a reused ONTOLOGY (early stamp after save_project) or REPORT (pending
    mint) with its producer pair only; the reuse completion adds the requested label."""
    pid = "pipe_infra8_reuse_fill"
    state = _state(pipeline_roots, pid, sim_llm_telemetry=json.loads(json.dumps(SIM_STASH)))
    state.simulation_id = SIM_ID
    orch = po.PipelineOrchestrator()
    orch._write_run_manifest(state)
    orch._stamp_produced_artifact(state, po.STAGE_ONTOLOGY)
    state.report_id = "report_pending"
    orch._record_report_mint(state, "report_pending")
    monkeypatch.setattr(Config, "LLM_PROVIDER", "deepseek", raising=False)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "deepseek-v4", raising=False)
    second = po.PipelineOrchestrator()
    second._write_run_manifest(state)
    for stage in (po.STAGE_ONTOLOGY, po.STAGE_GRAPH, po.STAGE_RUN, po.STAGE_REPORT):
        second._complete_stage(state, stage, reused=True)
    resolved = _manifest(pid)["resolved"]
    unknown_served = {"requested_source": "configured", "requested_models": [],
                      "served_models": [], "model_resolution": {}}
    assert resolved["ontology"] == {"provider": "kimi", "model_name": "kimi-k2.7",
                                    "requested_model": "kimi-k2.7", **unknown_served}
    assert resolved["report"] == {"provider": "kimi", "model_name": "kimi-k2.7",
                                  "requested_model": "kimi-k2.7", **unknown_served}
    # GRAPH never ran: its skeleton block names no producer and stays as it is.
    assert resolved["graph"] == {"provider": None, "model_name": None}
    assert {key: resolved["simulation"][key] for key in RUN_RECORD} == RUN_RECORD
    # A block that already carries the keys keeps them (the producing attempt's record).
    before = _manifest(pid)["resolved"]
    second._complete_stage(state, po.STAGE_ONTOLOGY, reused=True)
    assert _manifest(pid)["resolved"] == before


def test_reused_stages_are_left_alone_with_the_flag_off(pipeline_roots, monkeypatch):
    _flag_off(monkeypatch)
    pid = "pipe_infra8_reuse_off"
    state = _state(pipeline_roots, pid)
    orch = po.PipelineOrchestrator()
    orch._write_run_manifest(state)
    orch._stamp_produced_artifact(state, po.STAGE_ONTOLOGY)
    orch._complete_stage(state, po.STAGE_ONTOLOGY, reused=True)
    assert _manifest(pid)["resolved"]["ontology"] == {"provider": "kimi", "model_name": "kimi-k2.7"}


def test_the_research_child_gets_the_knob_from_config(monkeypatch):
    assert ("RECORD_MODEL_PROVENANCE", "bool") in po.RESEARCH_CHILD_V3_KNOBS
    assert all(name != "RECORD_MODEL_PROVENANCE" for name, _kind in po.RESEARCH_CHILD_KNOBS)
    monkeypatch.setenv("RECORD_MODEL_PROVENANCE", "true")
    _flag_off(monkeypatch)
    env = dict(os.environ)
    po._forward_research_knobs(env, po.RESEARCH_CHILD_V3_KNOBS)
    assert env["RECORD_MODEL_PROVENANCE"] == "false"


def test_the_simulation_child_gets_the_knob_from_config(tmp_path, monkeypatch):
    from app.services import simulation_runner as sr_mod
    from app.services.simulation_runner import SimulationRunner

    for name, value in {"RUN_STATE_DIR": str(tmp_path), "_run_states": {}, "_run_state_last_save": {},
                        "_processes": {}, "_action_queues": {}, "_monitor_threads": {},
                        "_stdout_files": {}, "_stderr_files": {}, "_graph_memory_enabled": {},
                        "_cleanup_done": True}.items():
        monkeypatch.setattr(SimulationRunner, name, value, raising=False)
    monkeypatch.setattr(SimulationRunner, "_monitor_simulation", lambda simulation_id: None)
    monkeypatch.setattr(Config, "SIM_RESUME", False, raising=False)
    monkeypatch.setenv("RECORD_MODEL_PROVENANCE", "true")
    envs = []

    def _popen(cmd, **kwargs):
        envs.append(kwargs["env"])
        return SimpleNamespace(pid=os.getpid(), poll=lambda: None)

    monkeypatch.setattr(sr_mod.subprocess, "Popen", _popen)
    for sim_id, flag in (("sim_infra8_on", True), ("sim_infra8_off", False)):
        monkeypatch.setattr(Config, "RECORD_MODEL_PROVENANCE", flag, raising=False)
        (tmp_path / sim_id).mkdir()
        (tmp_path / sim_id / "simulation_config.json").write_text(json.dumps(
            {"time_config": {"total_simulation_hours": 2, "minutes_per_round": 60}}), encoding="utf-8")
        SimulationRunner.start_simulation(sim_id, platform="parallel")
    assert [env["RECORD_MODEL_PROVENANCE"] for env in envs] == ["true", "false"]


# ======================================================================= simulation child

def _sim_child(monkeypatch):
    """run_parallel_simulation with a fresh usage accumulator and direct-call record."""
    scripts = os.path.join(_BACKEND, "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import run_parallel_simulation as rps

    monkeypatch.setattr(rps, "_SIM_LLM_USAGE", {"calls": 0, "errors": 0, "prompt_tokens": 0,
                                                "completion_tokens": 0, "by_source": {},
                                                "by_model": {}})
    monkeypatch.setattr(rps, "_SIM_DIRECT_MODEL_RESOLUTION", {})
    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    return rps


def _drive_camel_model(rps, replies):
    import asyncio

    class _CamelModel:
        model_type = "MiniMax-M3"

        async def _arequest_chat_completion(self, messages, tools=None):
            return replies.pop(0)

    model = _CamelModel()
    rps._wrap_model_llm_counter(model)

    async def _calls():
        while replies:
            await model._arequest_chat_completion([])

    asyncio.run(_calls())


def _completion(cid, model):
    return SimpleNamespace(id=cid, model=model,
                           usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4))


def test_simulation_child_records_requested_and_served_models(tmp_path, monkeypatch):
    rps = _sim_child(monkeypatch)
    monkeypatch.setenv("RECORD_MODEL_PROVENANCE", "true")
    # Two direct provider calls and one synthetic completion (the LLMClient failover, whose
    # call the failover client meters itself).
    _drive_camel_model(rps, [_completion("chatcmpl-real-1", "MiniMax-M3-0901"),
                             _completion("chatcmpl-real-2", "MiniMax-M3-0901"),
                             _completion("chatcmpl-cli-x", "MiniMax-M3")])
    rid = "run-infra8-sim-child"
    tel.set_run_context(rid)
    try:
        # An LLMClient call of this process (CLI bridge / decision channel) under its own label.
        tel.LLMMeter.record("claude-cli", "gpt-4o-mini", 5, 5, 1.0, served_model="claude-opus-4-8")
        rps._write_sim_llm_telemetry(str(tmp_path), {"simulation_id": "sim_infra8_child"})
    finally:
        tel.set_run_context(None)
        tel.LLMMeter.reset(rid)
    data = json.loads((tmp_path / "sim_llm_telemetry.json").read_text(encoding="utf-8"))
    assert data["model_resolution"] == {
        "minimax:MiniMax-M3": {"calls": 2, "served": {"MiniMax-M3-0901": 2}},
        "claude-cli:cli-default": {"calls": 1, "served": {"claude-opus-4-8": 1}}}
    # The legacy fields are unchanged: 'model' stays the dominant by_model key (a served id).
    assert data["model"] == "MiniMax-M3-0901" and data["calls"] == 3


def test_simulation_child_with_the_flag_off_writes_the_old_snapshot(tmp_path, monkeypatch):
    rps = _sim_child(monkeypatch)
    monkeypatch.setenv("RECORD_MODEL_PROVENANCE", "false")
    _drive_camel_model(rps, [_completion("chatcmpl-real-1", "MiniMax-M3-0901")])
    rps._write_sim_llm_telemetry(str(tmp_path), {"simulation_id": "sim_infra8_child_off"})
    data = json.loads((tmp_path / "sim_llm_telemetry.json").read_text(encoding="utf-8"))
    assert set(data) == {"schema_version", "simulation_id", "meter_run_token", "provider", "model",
                         "calls", "errors", "prompt_tokens", "completion_tokens", "total_tokens",
                         "by_source", "by_model", "wall_s", "written_at"}


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
        assert block["stages"]["report"] == {
            "provider": "fake", "model_name": "fake-1", "requested_model": "fake-1",
            "requested_source": "metered", "requested_models": ["fake:fake-1"],
            "served_models": ["fake-1-0930"],
            "model_resolution": {"fake:fake-1": {"calls": 1, "served": {"fake-1-0930": 1}}}}
    assert "report" not in agent.run_provenance["stages"]


def test_report_stage_names_the_tier_routed_model_it_requested():
    from app.services.report_agent import ReportAgent

    agent = ReportAgent.__new__(ReportAgent)
    agent.llm = SimpleNamespace(provider="minimax", model="MiniMax-M3")
    agent.run_provenance = json.loads(json.dumps(RUN_PROVENANCE))
    rid = "run-infra8-report-tier"
    tel.set_run_context(rid, "report")
    try:
        # What LLMClient meters for a default-tier call under LLM_STRONG_MODEL (EVAL-10).
        tel.LLMMeter.record("minimax", "MiniMax-M3-Pro", 5, 5, 1.0, served_model="MiniMax-M3-Pro-0901")
        block = agent._model_provenance_block()
    finally:
        tel.set_run_context(None)
        tel.LLMMeter.reset(rid)
    assert block["stages"]["report"] == {
        "provider": "minimax", "model_name": "MiniMax-M3", "requested_model": "MiniMax-M3-Pro",
        "requested_source": "metered", "requested_models": ["minimax:MiniMax-M3-Pro"],
        "served_models": ["MiniMax-M3-Pro-0901"],
        "model_resolution": {"minimax:MiniMax-M3-Pro": {"calls": 1,
                                                        "served": {"MiniMax-M3-Pro-0901": 1}}}}


def test_report_stage_keeps_which_served_id_answered_which_request():
    """A shadow-check or ensemble model's served id is kept under its own request, not only
    in the flat served_models list."""
    from app.services.report_agent import ReportAgent

    agent = ReportAgent.__new__(ReportAgent)
    agent.llm = SimpleNamespace(provider="minimax", model="MiniMax-M3")
    agent.run_provenance = json.loads(json.dumps(RUN_PROVENANCE))
    rid = "run-infra8-report-shadow"
    tel.set_run_context(rid, "report")
    try:
        for _ in range(3):
            tel.LLMMeter.record("minimax", "MiniMax-M3", 5, 5, 1.0, served_model="MiniMax-M3-0901")
        tel.LLMMeter.record("deepseek", "deepseek-v4", 5, 5, 1.0, served_model="deepseek-v4-0925")
        report = agent._model_provenance_block()["stages"]["report"]
    finally:
        tel.set_run_context(None)
        tel.LLMMeter.reset(rid)
    assert report["requested_model"] == "MiniMax-M3"
    assert report["served_models"] == ["MiniMax-M3-0901", "deepseek-v4-0925"]
    assert report["model_resolution"] == {
        "minimax:MiniMax-M3": {"calls": 3, "served": {"MiniMax-M3-0901": 3}},
        "deepseek:deepseek-v4": {"calls": 1, "served": {"deepseek-v4-0925": 1}}}


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

    # A CLI primary never receives a tier model: any tier model other than LLM_MODEL_NAME is
    # ignored, a claude id included.
    monkeypatch.setattr(Config, "LLM_PROVIDER", "claude-cli", raising=False)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "claude-sonnet-4-5", raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_MODEL", "claude-haiku-4-5", raising=False)
    monkeypatch.setattr(Config, "LLM_STRONG_MODEL", "claude-sonnet-4-5", raising=False)
    warnings = Config.validation_warnings()
    assert len(warnings) == 1 and "LLM_FAST_MODEL=claude-haiku-4-5" in warnings[0]
    assert "ignored" in warnings[0] and "runs claude-sonnet-4-5 (from LLM_MODEL_NAME)" in warnings[0]
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "glm-5.3", raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_MODEL", "MiniMax-M3", raising=False)
    monkeypatch.setattr(Config, "LLM_STRONG_MODEL", "claude-opus-4-8", raising=False)
    warnings = Config.validation_warnings()
    assert len(warnings) == 2 and all("the CLI account's default model" in w for w in warnings)
    monkeypatch.setattr(Config, "LLM_PROVIDER", "codex-cli", raising=False)
    assert len(Config.validation_warnings()) == 2
    monkeypatch.setattr(Config, "LLM_FAST_MODEL", "glm-5.3", raising=False)
    monkeypatch.setattr(Config, "LLM_STRONG_MODEL", None, raising=False)
    assert Config.validation_warnings() == []
    # An OpenAI-compatible primary does route to the tier models: nothing to warn about.
    monkeypatch.setattr(Config, "LLM_PROVIDER", "kimi", raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_MODEL", "kimi-fast", raising=False)
    assert Config.validation_warnings() == []


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


def test_preflight_endpoint_checks_the_normalised_model_in_both_forms(monkeypatch):
    scripts = os.path.join(_BACKEND, "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import preflight

    seen = []
    monkeypatch.setattr(research_api, "preflight_pipeline", lambda **kw: seen.append(kw) or [])
    monkeypatch.setattr(preflight, "environment_report",
                        lambda **kw: seen.append(("full", kw)) or {"ready": True})
    app = Flask(__name__)
    app.register_blueprint(research_bp, url_prefix="/api/research")
    client = app.test_client()
    assert client.get("/api/research/preflight?model=GLM&mode=research_only").status_code == 200
    assert client.get("/api/research/preflight").status_code == 200
    assert client.get("/api/research/preflight?model=GLM&format=full").status_code == 200
    assert seen == [{"mode": "research_only", "model": "glm"}, {"mode": "full", "model": None},
                    ("full", {"mode": "full", "model": "glm", "deep": False})]
