"""Report pre-flight probe vs. reasoning tokens (ORCH-8).

Live failure (pipe_fd2799f3ad41, 2026-10-18 01:51): glm-5.3 on the coding plan still emits
reasoning tokens with ``thinking: disabled``; with a 64-token cap all three probe attempts
ended with empty content (finish_reason=length) and the report stage failed although the
provider was healthy.  Pins: the probe uses the configured budget (default 1024, floor 16)
with a fresh nonce; a reply cut off by its cap passes (the provider answered); other empty
answers and real failures still fail the stage with the resumable message; the client raises
EmptyCompletionError (a RuntimeError, so retries and fallback are unchanged) naming the
switch each provider really has.
"""

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.services import pipeline_orchestrator as po  # noqa: E402
from app.utils import llm_client as lc  # noqa: E402


def _fake_llm(monkeypatch, behaviour):
    calls = []

    class _LLM:
        def chat(self, messages, temperature=0.7, max_tokens=4096, **kw):
            calls.append({"messages": messages, "temperature": temperature, "max_tokens": max_tokens})
            if isinstance(behaviour, Exception):
                raise behaviour
            return behaviour

    monkeypatch.setattr(lc, "LLMClient", _LLM)
    return calls


def test_probe_uses_the_configured_budget_and_a_fresh_nonce(monkeypatch):
    assert Config.REPORT_LLM_PREFLIGHT_MAX_TOKENS >= 512          # room for reasoning tokens
    calls = _fake_llm(monkeypatch, "pong")
    po._report_llm_preflight()
    assert calls[0]["max_tokens"] == Config.REPORT_LLM_PREFLIGHT_MAX_TOKENS
    assert calls[0]["temperature"] == 0.0 and calls[0]["messages"][0]["content"].startswith("ping ")
    monkeypatch.setattr(Config, "REPORT_LLM_PREFLIGHT_MAX_TOKENS", 2048, raising=False)
    po._report_llm_preflight()
    assert calls[1]["max_tokens"] == 2048
    monkeypatch.setattr(Config, "REPORT_LLM_PREFLIGHT_MAX_TOKENS", 1, raising=False)
    po._report_llm_preflight()
    assert calls[2]["max_tokens"] == 16                                # floor
    monkeypatch.setattr(Config, "REPORT_LLM_PREFLIGHT_MAX_TOKENS", "junk", raising=False)
    po._report_llm_preflight()
    assert calls[3]["max_tokens"] == 1024                              # unparseable → default
    assert len({c["messages"][0]["content"] for c in calls}) == 4      # no cache replay


def test_reply_cut_off_by_the_cap_proves_the_provider_is_reachable(monkeypatch):
    seen = []
    monkeypatch.setattr(po.logger, "warning", lambda *a, **k: seen.append(a))
    _fake_llm(monkeypatch, lc.EmptyCompletionError("empty", provider="glm", finish_reason="length"))
    po._report_llm_preflight()                                         # no raise: the provider answered
    assert seen and "可达" in seen[0][0] and seen[0][1] == "glm"


@pytest.mark.parametrize("error", [
    lc.EmptyCompletionError("empty", provider="glm", finish_reason="stop"),
    lc.EmptyCompletionError("empty", provider="glm", finish_reason=None),
    RuntimeError("LLM 调用失败：主提供方 glm 处于 422/429 熔断冷却，且回退提供方不可用"),
    ValueError("quota exhausted"),
])
def test_other_failures_still_fail_the_stage_resumably(monkeypatch, error):
    _fake_llm(monkeypatch, error)
    with pytest.raises(RuntimeError) as info:
        po._report_llm_preflight()
    message = str(info.value)
    assert message.startswith("报告前置探测失败：主/回退 LLM 提供方均不可用")
    assert "稍后 resume 可从 REPORT 续跑" in message
    assert info.value.__cause__ is error


def _client(monkeypatch, provider, content, finish):
    class _Completions:
        @staticmethod
        def create(**kwargs):
            message = SimpleNamespace(content=content)
            choice = SimpleNamespace(message=message, finish_reason=finish)
            return SimpleNamespace(choices=[choice],
                                   usage=SimpleNamespace(prompt_tokens=10, completion_tokens=64))

    client = object.__new__(lc.LLMClient)
    client.provider = provider
    client.model = "m"
    client._openai_client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    client._fast_openai_client = None
    client._is_fallback = False
    client._last_usage = None
    monkeypatch.setattr(Config, "LLM_TIERED_ROUTING", False, raising=False)
    return client


@pytest.mark.parametrize("provider,knob", [
    ("glm", "LLM_DISABLE_THINKING"), ("deepseek", "LLM_DISABLE_THINKING"), ("qwen", "LLM_DISABLE_THINKING"),
    ("kimi", "LLM_KIMI_DISABLE_THINKING"), ("minimax", "LLM_MINIMAX_DISABLE_THINKING"),
])
def test_client_raises_empty_completion_with_reason_and_the_real_switch(monkeypatch, provider, knob):
    client = _client(monkeypatch, provider, "", "length")
    with pytest.raises(lc.EmptyCompletionError) as info:
        client._chat_openai([{"role": "user", "content": "ping"}], 0.0, 64)
    err = info.value
    assert isinstance(err, RuntimeError)                                # retry/fallback paths unchanged
    assert err.finish_reason == "length" and err.provider == provider
    assert f"({knob}=true)" in str(err)
    assert "返回空 content（finish_reason=length）" in str(err)
    assert "LLM_GLM_DISABLE_THINKING" not in str(err)


def test_client_still_returns_normal_content(monkeypatch):
    client = _client(monkeypatch, "glm", "pong", "stop")
    assert client._chat_openai([{"role": "user", "content": "ping"}], 0.0, 64) == "pong"
    blank = _client(monkeypatch, "glm", "   ", "stop")
    with pytest.raises(lc.EmptyCompletionError) as info:
        blank._chat_openai([{"role": "user", "content": "ping"}], 0.0, 64)
    assert info.value.finish_reason == "stop"
