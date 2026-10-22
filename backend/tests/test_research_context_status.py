"""Read-only readiness reflects the actual research tool registry and parent controls."""
import json

import pytest
from flask import Flask

from app.config import Config
from app.services.news_market_context import research_tool_status
from app.services.pipeline_orchestrator import _news_context_subprocess_env
from deerflow_bridge.research_gateway import context_tool_names


@pytest.fixture
def configured(monkeypatch):
    for name, value in {
        "NEWS_CONTEXT_ENABLED": True, "NEWSAPI_ENABLED": True,
        "REDDIT_SIGNALS_ENABLED": False, "MARKET_INTELLIGENCE_ENABLED": True,
        "NEWSAPI_MAX_REQUESTS": 2, "MARKET_INTELLIGENCE_MAX_REQUESTS": 4,
    }.items():
        monkeypatch.setattr(Config, name, value)
    monkeypatch.setenv("NEWSAPI_API_KEY", "synthetic-newsapi-test-secret")


def test_status_uses_real_tool_registry_without_secret_or_acquisition(configured):
    status = research_tool_status()
    assert status["tools"] == list(context_tool_names(_news_context_subprocess_env()))
    assert status["tools"] == ["news_search", "market_compare"]
    assert status["newsapi"]["credential_configured"] is True
    assert status["availability_checked"] is False
    assert "synthetic-newsapi-test-secret" not in json.dumps(status)


@pytest.mark.parametrize("key", [None, "", "your_api_key"])
def test_missing_or_placeholder_key_is_honest_while_tool_remains_registered(configured, monkeypatch, key):
    if key is None:
        monkeypatch.delenv("NEWSAPI_API_KEY")
    else:
        monkeypatch.setenv("NEWSAPI_API_KEY", key)
    status = research_tool_status()
    assert status["newsapi"]["credential_configured"] is False
    assert "news_search" in status["tools"]


def test_disabled_and_opt_in_flags_follow_actual_registration(configured, monkeypatch):
    monkeypatch.setattr(Config, "REDDIT_SIGNALS_ENABLED", True)
    assert research_tool_status()["tools"] == ["news_search", "social_search", "market_compare"]
    monkeypatch.setattr(Config, "NEWS_CONTEXT_ENABLED", False)
    status = research_tool_status()
    assert status["enabled"] is False and status["tools"] == []
    assert status["newsapi"]["max_requests"] == status["markets"]["max_requests"] == 0


def test_actual_preflight_route_exposes_status_without_starting_research(configured, monkeypatch):
    import app.api.research as api
    # Match the route's existing script import; keep its actual report assembly.
    from pathlib import Path
    script_dir = str(Path(__file__).resolve().parents[1] / "scripts")
    monkeypatch.syspath_prepend(script_dir)
    import preflight
    monkeypatch.setattr(preflight, "preflight_pipeline", lambda **kwargs: [])
    monkeypatch.setattr(preflight, "simulation_readiness", lambda **kwargs: {
        "errors": [], "simulation_engine": "oasis-legacy", "default_simulation_engine": "oasis-legacy",
        "simulation_admission": {},
    }, raising=False)
    monkeypatch.setattr(preflight, "_append_placeholder_checks", lambda *args: None)
    monkeypatch.setattr(api.PipelineOrchestrator, "start", lambda *args, **kwargs: pytest.fail("GET started research"))
    app = Flask(__name__)
    app.register_blueprint(api.research_bp, url_prefix="/api/research")
    response = app.test_client().get("/api/research/preflight?mode=research_only&format=full")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["ready"] is True and data["exit_code"] == 0
    assert data["research_context"]["tools"] == ["news_search", "market_compare"]
    assert data["research_context"]["newsapi"]["credential_configured"] is True
    assert "synthetic-newsapi-test-secret" not in response.get_data(as_text=True)
