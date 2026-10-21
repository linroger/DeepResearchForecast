"""Merged Oddsense cutoff and persisted report replay controls.

Run only with unchanged main_offline_pytest.py in a fresh private source mirror.
The report/engine/tool consumers are real; no provider or service is contacted.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_oddsense_workflow import (
    Log, NativeTransport, NoExternalIntelligence, QUESTION, ScriptedModel, _config,
)

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.guarded_runner


def test_backtest_engine_disables_fresh_context_and_rejects_retained_current_capture(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(REPO / "deerflow_bridge"))
    import linear_research as lr
    import research_gateway as rg
    import deerflow_research as bridge
    import news_signals as news

    env = _config(monkeypatch)
    env["DRF_BACKTEST_POLICY"] = json.dumps({
        "as_of": "2024-11-01", "strict": True, "archive": "wayback",
        "audit_path": str(tmp_path / "cutoff-audit.jsonl"),
    })
    external = NoExternalIntelligence()
    args = SimpleNamespace(model=external.model_name, depth="quick", target_language="English", no_actors=True)

    def engine(out):
        return lr._Engine(QUESTION, out, args, {}, Log(), lambda: None, bridge,
                          lambda args, log, bridge, preset: rg.ModelGateway(external, log),
                          lambda ledger, pages, bridge, log, limits: rg.ResearchTools(
                                  ledger, pages, bridge=bridge, plog=log, limits=limits), env)

    fresh = tmp_path / "fresh"
    run = engine(fresh)
    run.phase_context()
    run._seal_context()
    assert run.context_names == () and run.context_snapshot == {}
    assert run.meta["news_market_context"] == {"status": "disabled_backtest"}
    assert not (fresh / news.CONTEXT_FILENAME).exists()
    schemas = {row["function"]["name"] for row in run.agent_tools}
    assert not schemas.intersection({"news_search", "social_search", "market_compare"})
    stored = tmp_path / "stored-current"
    client = news.ContextClient(stored, question=QUESTION, language="English", as_of="2026-10-21",
                               news_enabled=False, social_enabled=False, api_key=None)
    client.seal()
    capture_path = stored / news.CONTEXT_FILENAME
    retained = capture_path.read_bytes()
    with pytest.raises(lr._EngineFailure, match="backtest_context_unsupported"):
        engine(stored)
    assert capture_path.read_bytes() == retained and external.calls == []


def test_backtest_engine_cannot_seal_prebound_current_context(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(REPO / "deerflow_bridge"))
    import linear_research as lr
    import research_gateway as rg
    import deerflow_research as bridge
    import news_signals as news

    env = _config(monkeypatch)
    env["DRF_BACKTEST_POLICY"] = json.dumps({"as_of": "2024-11-01", "strict": True,
        "audit_path": str(tmp_path / "cutoff-audit.jsonl")})
    out = tmp_path / "prebound"
    # A populated native-shaped future capture is deliberately prebound outside
    # the historical output root, so its current-context file guard alone cannot
    # protect planning prompts. Acquisition here is scripted fixture preparation.
    transport = NativeTransport()
    client = news.ContextClient(tmp_path / "future-native-proof", question=QUESTION,
                               language="English", as_of="2026-10-21", transport=transport,
                               news_enabled=True, social_enabled=False, api_key="offline-news-sentinel")
    acquired = client.search_news("capacity")
    assert acquired["items"] and all(row["published_at"] > "2024-11-01" for row in acquired["items"])
    future_capture = client.seal()
    native_requests = len(transport.calls)
    assert not (out / news.CONTEXT_FILENAME).exists()
    prompts, trace = [], []
    class RecordingModel(ScriptedModel):
        def invoke(self, messages):
            prompts.append([str(message.content) for message in messages])
            return super().invoke(messages)
    model = RecordingModel(rg, trace)
    model.on_plan = lambda: None
    args = SimpleNamespace(model=model.model_name, depth="quick", target_language="English", no_actors=True)
    run = lr._Engine(QUESTION, out, args, {}, Log(), lambda: None, bridge,
                    lambda args, log, bridge, preset: rg.ModelGateway(model, log),
                    lambda ledger, pages, bridge, log, limits: rg.ResearchTools(
                        ledger, pages, bridge=bridge, plog=log, limits=limits, context_client=client,
                        search_fn=lambda query, n: json.dumps({"query": query, "results": []})), env)
    run.phase_context()
    assert run._context_text() == ""
    run.phase_plan()
    assert prompts and any(row["role"] == "PLANNING TASK" for row in trace)
    shown = json.dumps(prompts)
    for item in future_capture["items"]:
        assert item["title"] not in shown and item["url"] not in shown
    assert "NEWS AND MARKET CONTEXT" not in shown
    assert run.plan.as_of == "2024-11-01" and run.ledger.rows() == []
    run._seal_context()
    assert run.context_snapshot == {} and not (out / news.CONTEXT_FILENAME).exists()
    assert run.meta["news_market_context"] == {"status": "disabled_backtest"}
    assert not run.state.snapshot().get("news_market_context_binding")
    run.context_snapshot = future_capture
    assert run._context_text() == ""
    with pytest.raises(lr._EngineFailure, match="backtest_context_unsupported"):
        run._seal_context()
    assert not (out / news.CONTEXT_FILENAME).exists()
    assert not run.state.snapshot().get("news_market_context_binding")
    assert len(transport.calls) == native_requests
    (Path(os.environ["MAIN_OFFLINE_EVIDENCE"]) / "oddsense-backtest-native.json").write_text(json.dumps({
        "controlled_scripted": True, "future_capture": future_capture, "cutoff": run.plan.as_of,
        "model_inputs": prompts, "model_trace": trace, "new_provider_requests": 0,
        "context_binding_absent": True, "historical_capture_absent": True,
    }, indent=2))
