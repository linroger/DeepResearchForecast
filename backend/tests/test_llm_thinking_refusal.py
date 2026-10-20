"""Models that always reason refuse requests that disable reasoning (offline).

Since 2026-10-18 ~20:37 +08 glm-5.3 answers ``thinking: {"type": "disabled"}`` with HTTP 400,
code 1210: "该模型始终思考，不支持关闭思考；请使用 low、high 或 max"
(docs/handoff/world-engines-consolidation/real-dossier-replay/live-2026-10-18/diagnose-400.json).
The app sent that payload on every GLM call (LLMClient, the OASIS agents' model, the settings
probe and preflight), so a live run's agent posts, world decisions, arbiter and report calls were
all refused.  Pinned here: the classification, the static rule for glm-5.x, the resend-once
recovery that learns any other refusing model, and that nothing else changes.
"""

import asyncio
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.config import Config
from app.utils import llm_client as lc
from app.utils.llm_errors import is_thinking_required_error

REFUSAL_TEXT = "该模型始终思考，不支持关闭思考；请使用 low、high 或 max。"
DISABLED = {"thinking": {"type": "disabled"}}


def _bad_request(code, message, status=400):
    response = httpx.Response(status, request=httpx.Request("POST", "http://127.0.0.1:1/v1/chat/completions"))
    body = {"error": {"code": code, "message": message}}
    cls = openai.BadRequestError if status == 400 else openai.RateLimitError
    return cls(f"Error code: {status} - {body}", response=response, body=body)


@pytest.fixture(autouse=True)
def _reasoning_config(monkeypatch):
    monkeypatch.setattr(Config, "_thinking_refused", set())
    monkeypatch.setattr(Config, "LLM_DISABLE_THINKING", True)
    monkeypatch.setattr(Config, "LLM_ALWAYS_THINKING_MODELS", "glm-5")
    monkeypatch.setattr(Config, "LLM_THINKING_REQUIRED_EFFORT", "low")
    monkeypatch.setattr(Config, "LLM_THINKING_HEADROOM_TOKENS", 2048)
    monkeypatch.setattr(Config, "LLM_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr(Config, "LLM_TIERED_ROUTING", False, raising=False)   # the request model is the client's
    monkeypatch.setattr(lc, "_CB_STATE", {})
    monkeypatch.delenv("LLM_FALLBACK_PROVIDER", raising=False)


# -- classification ---------------------------------------------------------------------------

def test_the_1210_thinking_refusal_is_recognised_by_its_message():
    assert is_thinking_required_error(_bad_request("1210", REFUSAL_TEXT))
    assert is_thinking_required_error(RuntimeError("provider says: this model always thinks"))


@pytest.mark.parametrize("exc", [
    _bad_request("1210", "API 调用参数有误，请检查文档"),            # 1210 is Zhipu's generic parameter code
    _bad_request("1301", "系统检测到输入或生成内容可能包含不安全或敏感内容"),   # content filter
    _bad_request("1302", REFUSAL_TEXT, status=429),                  # a 429 is never this refusal
    ValueError("totally unrelated"),
])
def test_other_failures_are_not_the_thinking_refusal(exc):
    assert not is_thinking_required_error(exc)


# -- the shared setting -------------------------------------------------------------------------

def test_glm5_models_get_reasoning_on_at_low_effort_instead_of_a_refused_disable():
    body = Config.reasoning_extra_body("glm", "glm-5.3")
    assert body == {"thinking": {"type": "enabled"}, "reasoning_effort": "low"}
    assert Config.reasoning_forced("glm", "GLM-5") is True
    assert Config.minimal_reasoning_body("glm", "glm-5.3") == body


def test_other_models_and_providers_are_unchanged():
    assert Config.reasoning_extra_body("glm", "glm-4.6") == DISABLED
    assert Config.reasoning_extra_body("kimi", "kimi-for-coding") == DISABLED
    assert Config.reasoning_extra_body("qwen", "qwen3-max") == {"enable_thinking": False}
    assert Config.reasoning_extra_body("openai", "gpt-4o-mini") is None
    assert Config.reasoning_forced("glm", "glm-4.6") is False


def test_the_switch_and_the_static_rule_stay_configurable(monkeypatch):
    monkeypatch.setattr(Config, "LLM_DISABLE_THINKING", False)
    assert Config.reasoning_extra_body("glm", "glm-5.3") is None   # reasoning left at the provider default
    assert Config.reasoning_forced("glm", "glm-5.3") is False
    monkeypatch.setattr(Config, "LLM_DISABLE_THINKING", True)
    monkeypatch.setattr(Config, "LLM_ALWAYS_THINKING_MODELS", "")
    assert Config.reasoning_extra_body("glm", "glm-5.3") == DISABLED
    monkeypatch.setattr(Config, "LLM_ALWAYS_THINKING_MODELS", "glm-5")
    monkeypatch.setattr(Config, "LLM_THINKING_REQUIRED_EFFORT", "extreme")   # not an accepted level
    assert Config.reasoning_extra_body("glm", "glm-5.3")["reasoning_effort"] == "low"


def test_a_learned_refusal_applies_to_that_model_only():
    assert Config.note_thinking_refused("deepseek", "deepseek-r9") is True
    assert Config.note_thinking_refused("deepseek", "deepseek-r9") is False
    assert Config.reasoning_extra_body("deepseek", "deepseek-r9") is None      # its own default reasoning
    assert Config.reasoning_extra_body("deepseek", "deepseek-chat") == DISABLED
    assert Config.reasoning_extra_body("glm", "deepseek-r9") == DISABLED      # keyed by provider too


def test_headroom_never_shrinks_a_budget_and_stops_at_the_ceiling():
    assert Config.thinking_headroom(1200) == 3248
    assert Config.thinking_headroom(32000) == 32768
    assert Config.thinking_headroom(64000) == 64000


# -- LLMClient ----------------------------------------------------------------------------------

def _completion(content="ok"):
    msg = SimpleNamespace(content=content, tool_calls=[])
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                           usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2), model="m")


class _Gateway:
    """Fake chat.completions: refuses disabled reasoning the way glm-5.3 does."""

    def __init__(self, refuse_with=None):
        self.calls = []
        self.refuse_with = refuse_with

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if Config.disables_thinking(kwargs.get("extra_body")):
            raise self.refuse_with or _bad_request("1210", REFUSAL_TEXT)
        return _completion('{"ok": true}')


def _client(model, gateway):
    client = lc.LLMClient(provider="glm", api_key="sk-test", base_url="http://127.0.0.1:1/v1", model=model)
    client._openai_client = SimpleNamespace(chat=SimpleNamespace(completions=gateway))
    return client


def test_a_refusing_model_is_resent_once_then_remembered():
    gateway = _Gateway()
    client = _client("glm-4.7", gateway)       # not covered by the static glm-5 rule
    assert client.chat_json([{"role": "user", "content": "hi"}], max_tokens=1200) == {"ok": True}
    first, resent = gateway.calls
    assert first["extra_body"] == DISABLED and first["max_tokens"] == 1200
    assert resent["extra_body"] == {"thinking": {"type": "enabled"}, "reasoning_effort": "low"}
    assert resent["max_tokens"] == 3248                       # reasoning headroom on the resend
    client.chat([{"role": "user", "content": "again"}], max_tokens=500)
    assert len(gateway.calls) == 3                            # later calls go straight to the accepted body
    assert gateway.calls[-1]["extra_body"]["thinking"] == {"type": "enabled"}
    assert gateway.calls[-1]["max_tokens"] == 2548


def test_glm5_never_sends_the_refused_payload():
    gateway = _Gateway()
    client = _client("glm-5.3", gateway)
    client.chat([{"role": "user", "content": "hi"}], max_tokens=1200)
    assert len(gateway.calls) == 1
    assert gateway.calls[0]["extra_body"]["thinking"] == {"type": "enabled"}
    assert gateway.calls[0]["max_tokens"] == 3248


def test_any_other_bad_request_is_raised_without_a_resend():
    gateway = _Gateway(refuse_with=_bad_request("1210", "API 调用参数有误，请检查文档"))
    client = _client("glm-4.7", gateway)
    with pytest.raises(openai.BadRequestError):
        client.chat([{"role": "user", "content": "hi"}], max_tokens=100)
    assert len(gateway.calls) == 1
    assert Config.thinking_required("glm", "glm-4.7") is False


def test_native_tool_calls_recover_the_same_way(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_NATIVE_TOOLS", True, raising=False)
    gateway = _Gateway()
    client = _client("glm-4.7", gateway)
    out = client.chat_with_tools([{"role": "user", "content": "hi"}], tools_schema=[], max_tokens=800)
    assert out["content"] == '{"ok": true}'
    assert [Config.disables_thinking(c.get("extra_body")) for c in gateway.calls] == [True, False]


# -- the OASIS agents' model ------------------------------------------------------------------

class _AgentModel:
    model_type = "glm-4.7"

    def __init__(self, gateway):
        self.model_config_dict = {"extra_body": dict(DISABLED)}
        self.gateway = gateway

        def _request(messages, tools=None):
            return self.gateway.create(messages=messages, **dict(self.model_config_dict))

        async def _arequest(messages, tools=None):
            return self.gateway.create(messages=messages, **dict(self.model_config_dict))

        self._request_chat_completion = _request
        self._arequest_chat_completion = _arequest


def test_agent_posts_switch_to_the_accepted_reasoning_body(monkeypatch):
    from app.utils import oasis_llm

    monkeypatch.setenv("SIM_LLM_FALLBACK", "true")
    gateway = _Gateway()
    model = _AgentModel(gateway)
    oasis_llm._wrap_openai_fallback_guard(model, "glm")
    assert model._request_chat_completion([{"role": "user", "content": "post"}]).choices
    assert model.model_config_dict["extra_body"] == {"thinking": {"type": "enabled"}, "reasoning_effort": "low"}
    assert asyncio.run(model._arequest_chat_completion([{"role": "user", "content": "post"}])).choices
    assert len(gateway.calls) == 3          # one refusal, then accepted requests only


def test_agent_model_reraises_an_unrelated_bad_request(monkeypatch):
    from app.utils import oasis_llm

    monkeypatch.setenv("SIM_LLM_FALLBACK", "true")
    model = _AgentModel(_Gateway(refuse_with=_bad_request("1214", "messages 参数非法")))
    oasis_llm._wrap_openai_fallback_guard(model, "glm")
    with pytest.raises(openai.BadRequestError):
        model._request_chat_completion([{"role": "user", "content": "post"}])
    assert model.model_config_dict["extra_body"] == DISABLED
