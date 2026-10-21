"""Oddsense/main boundary controls: live context cannot enter historical backtests."""
from types import SimpleNamespace
import json

import pytest
import test_backtest_engine as historical

rg = historical.rg
_hermetic_env = historical._hermetic_env
bridge = historical.bridge


@pytest.mark.parametrize("name", ["news_search", "social_search", "market_compare"])
def test_backtest_context_gateway_denies_before_provider_or_cached_replay(tmp_path, name):
    calls = []
    def acquire(*args, **kwargs):
        calls.append(args)
        raise AssertionError("Current context must not be acquired by a historical run")
    client = SimpleNamespace(search_news=acquire, search_social=acquire, compare_markets=acquire)
    ledger = rg.SourceLedger(tmp_path / "ledger.json")
    tools = rg.ResearchTools(ledger, tmp_path / "pages", context_client=client, backtest=object())
    tools._context_cache[(name, "election")] = "Future result known"
    text = tools.context_query(name, "election", agent_id="K1")
    assert "backtest_unsupported" in text and "Future result known" not in text
    assert calls == [] and ledger.rows() == []


def test_backtest_hides_context_tools_even_when_all_providers_enabled():
    env = {"DRF_BACKTEST_POLICY": '{"as_of":"2024-11-01"}',
           "NEWS_CONTEXT_ENABLED": "true", "NEWSAPI_ENABLED": "true",
           "REDDIT_SIGNALS_ENABLED": "true", "MARKET_INTELLIGENCE_ENABLED": "true"}
    assert rg.context_tool_names(env) == ()
    env.pop("DRF_BACKTEST_POLICY")
    assert set(rg.context_tool_names(env)) == {"news_search", "social_search", "market_compare"}


def test_full_historical_engine_never_constructs_live_context(tmp_path, bridge, monkeypatch):
    monkeypatch.setenv("DRF_BACKTEST_POLICY", historical._policy_env(tmp_path))
    for name in ("NEWS_CONTEXT_ENABLED", "NEWSAPI_ENABLED", "REDDIT_SIGNALS_ENABLED", "MARKET_INTELLIGENCE_ENABLED"):
        monkeypatch.setenv(name, "true")
    def forbidden():
        raise AssertionError("Historical run constructed a current context client")
    monkeypatch.setattr(rg, "_context_api", forbidden)
    rc, meta, _, model, out = historical._run(tmp_path, bridge)
    assert rc == 0, meta.get("error")
    assert meta["news_market_context"]["status"] == "disabled_backtest"
    assert not (out / "news_market_context.json").exists()
    sources = json.loads((out / "sources.json").read_text())
    assert sources and not any(row.get("context_id") for row in sources)
    assert all("late.example" not in row["url"] for row in sources)
    prompts = json.dumps([row["messages"] for row in model.calls], default=str)
    assert "Future result known" not in prompts and "Outcome recap" not in prompts


def test_historical_prompt_context_never_reads_an_injected_live_snapshot():
    from linear_research import _Engine
    calls = []
    def snapshot():
        calls.append("read current capture")
        return {}
    engine = object.__new__(_Engine)
    engine.backtest = object()
    engine.tools = SimpleNamespace(context_client=SimpleNamespace(snapshot=snapshot))
    engine.context_snapshot = {}
    assert engine._context_text() == ""
    assert calls == []
