"""Settings test/save keep the configured endpoint when re-used for the current provider.

With LLM_PROVIDER=glm on the GLM Coding Plan (open.bigmodel.cn/api/coding/paas/v4 +
glm-5.3), "Test connection" with blank Base URL/Model probed PROVIDER_META's defaults
(api.z.ai + glm-4.6) and reported a false "quota exhausted" 429 (upstream code 1113);
re-saving with blank fields wrote those defaults into .env. Blank fields must fall back
to the configured values for the current provider, and to the defaults only when
switching to a different provider.
"""

import pytest

from app.config import Config

CODING_URL = "https://open.bigmodel.cn/api/coding/paas/v4"
CODING_MODEL = "glm-5.3"


@pytest.fixture
def glm_configured(monkeypatch):
    monkeypatch.setattr(Config, "LLM_PROVIDER", "glm")
    monkeypatch.setattr(Config, "LLM_BASE_URL", CODING_URL)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", CODING_MODEL)
    monkeypatch.setattr(Config, "LLM_API_KEY", "sk-test")
    for attr in ("DEERFLOW_MODEL", "_is_kimi", "_is_minimax", "_is_deepseek", "_is_qwen", "_is_glm"):
        monkeypatch.setattr(Config, attr, getattr(Config, attr))
    persisted = []
    monkeypatch.setattr(Config, "_persist_env", classmethod(lambda cls, u: persisted.append(dict(u))))
    for key in ("LLM_PROVIDER", "DEERFLOW_MODEL", "LLM_BASE_URL", "LLM_MODEL_NAME",
                "LLM_API_KEY", "ZHIPUAI_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.setenv(key, "")  # records the original value so the writes below are undone
        monkeypatch.delenv(key)  # apply_provider writes os.environ
    return persisted


def test_resolve_endpoint_prefers_explicit_then_configured_then_default(glm_configured):
    assert Config.resolve_endpoint("glm") == (CODING_URL, CODING_MODEL)
    assert Config.resolve_endpoint("glm", "  ", "") == (CODING_URL, CODING_MODEL)
    assert Config.resolve_endpoint("glm", "https://x.example/v1", "m") == ("https://x.example/v1", "m")
    meta = Config.PROVIDER_META["deepseek"]
    assert Config.resolve_endpoint("deepseek") == (meta["default_base"], meta["default_model"])


def test_llm_test_probes_the_configured_endpoint(glm_configured, monkeypatch):
    from app.api import settings as settings_api

    seen = {}

    def fake_probe(provider, api_key, base_url, model):
        seen.update(provider=provider, api_key=api_key, base_url=base_url, model=model)
        return {"ok": True}

    monkeypatch.setattr(settings_api, "_test_openai_compat_provider", fake_probe)
    from app import create_app
    client = create_app().test_client()
    resp = client.post("/api/settings/llm/test", json={"provider": "glm"})
    assert resp.status_code == 200 and resp.get_json()["data"]["ok"] is True
    assert seen == {"provider": "glm", "api_key": "sk-test", "base_url": CODING_URL, "model": CODING_MODEL}


def test_resaving_current_provider_with_blank_fields_keeps_endpoint(glm_configured):
    Config.apply_provider("glm")
    assert (Config.LLM_BASE_URL, Config.LLM_MODEL_NAME) == (CODING_URL, CODING_MODEL)
    assert glm_configured[-1]["LLM_BASE_URL"] == CODING_URL
    assert glm_configured[-1]["LLM_MODEL_NAME"] == CODING_MODEL


def test_switching_provider_with_blank_fields_uses_its_defaults(glm_configured):
    Config.apply_provider("deepseek", api_key="sk-other")
    meta = Config.PROVIDER_META["deepseek"]
    assert (Config.LLM_BASE_URL, Config.LLM_MODEL_NAME) == (meta["default_base"], meta["default_model"])
