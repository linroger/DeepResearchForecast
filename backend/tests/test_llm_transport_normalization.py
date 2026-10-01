"""Offline tests for INFRA-1: LLM transport normalization in app/utils/llm_client.py.

Covers the typed completion failures (EmptyCompletion / LLMEmptyChoices / LLMContentFiltered /
LLMAbortedCompletion), the race-free per-thread call metadata (last_call_meta and the
_last_usage compatibility property), the LLM_TRANSPORT_STRICT think-stripping and cache-skip,
chat_with_tools' additive fields and the telemetry finish-reason tally. Every OpenAI response
is a SimpleNamespace (or a real openai pydantic model) fed through a fake client: no network,
no real LLM.
"""

import json
import os
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from app.config import Config
from app.services.pipeline_orchestrator import _classify_provider_outage
from app.utils import llm_client as lc
from app.utils import telemetry as tel
from tests.test_json_parse_never_raises import default_int_digit_limit

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_OUTAGE_WORDS = ("quota", "rate limit", "rate_limit", "unauthorized", "401", "429", "usage limit")


# ---------------------------------------------------------------- fakes / fixtures
def _usage(pt, ct, **extra):
    return SimpleNamespace(prompt_tokens=pt, completion_tokens=ct, **extra)


def _resp(content="ok", finish="stop", usage=None, model=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason=finish)
    fields = {"choices": [choice], "usage": usage}
    if model is not None:
        fields["model"] = model
    return SimpleNamespace(**fields)


def _fake_openai(create):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


class _Script:
    """A fake ``create`` that serves scripted responses (the last one repeats) and counts calls."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        item = self.responses[min(len(self.calls), len(self.responses)) - 1]
        if isinstance(item, BaseException):
            raise item
        return item


def _client(create, provider="minimax", model="MiniMax-M3"):
    client = lc.LLMClient(provider=provider, api_key="sk-test",
                          base_url="http://127.0.0.1:1/v1", model=model)
    client._openai_client = _fake_openai(create)
    return client


@pytest.fixture(autouse=True)
def _isolated_transport(monkeypatch):
    lc._CB_STATE.clear()
    lc._CALL_META.meta = None
    monkeypatch.delenv("LLM_FALLBACK_PROVIDER", raising=False)
    monkeypatch.setattr(lc, "_retry_delay", lambda exc, attempt: 0.0)
    monkeypatch.setattr(lc, "_FB_OPENAI_CLIENTS", {})
    monkeypatch.setattr(lc, "_FB_AUTH_UNAVAILABLE_UNTIL", {})
    monkeypatch.setattr(Config, "LLM_TRANSPORT_STRICT", True, raising=False)
    monkeypatch.setattr(Config, "LLM_TIERED_ROUTING", False, raising=False)
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "LLM_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "LLM_RUN_BUDGET_TOKENS", 0, raising=False)
    monkeypatch.setattr(Config, "LLM_RUN_BUDGET_USD", 0.0, raising=False)
    monkeypatch.setattr(Config, "LLM_MINIMAX_DISABLE_THINKING", True, raising=False)
    monkeypatch.setattr(tel.LLMCache, "_store", {})
    monkeypatch.setattr(tel.LLMCache, "_order", [])
    yield
    lc._CB_STATE.clear()
    lc._CALL_META.meta = None


# ---------------------------------------------------------------- empty choices
def test_minimax_empty_choices_envelope_raises_llm_empty_choices_with_provider_text():
    envelope = SimpleNamespace(
        choices=[], usage=None,
        model_extra={"base_resp": {"status_code": 2056, "status_msg": "usage limit exceeded (2056)"}},
    )
    client = _client(_Script(envelope))
    with pytest.raises(lc.LLMEmptyChoices) as ei:
        client._chat_openai([{"role": "user", "content": "q"}], 0.2, 256)
    exc = ei.value
    assert "2056" in str(exc) and "usage limit exceeded" in str(exc)
    assert isinstance(exc, RuntimeError)
    # The quota wording still reaches the existing classifiers.
    assert lc._is_quota(exc)
    assert _classify_provider_outage(exc) == "quota"


def test_real_openai_model_with_empty_choices_and_error_body():
    from openai.types.chat import ChatCompletion

    completion = ChatCompletion.model_validate({
        "id": "x", "object": "chat.completion", "created": 0, "model": "MiniMax-M3",
        "choices": [],
        "base_resp": {"status_code": 1004, "status_msg": "login fail: invalid api key"},
    })
    client = _client(_Script(completion))
    with pytest.raises(lc.LLMEmptyChoices, match="1004.*login fail"):
        client._chat_openai([{"role": "user", "content": "q"}], 0.2, 256)

    error_body = SimpleNamespace(choices=None, usage=None,
                                 model_extra={"error": {"message": "overloaded", "code": "busy"}})
    with pytest.raises(lc.LLMEmptyChoices, match="overloaded"):
        _client(_Script(error_body))._chat_openai([{"role": "user", "content": "q"}], 0.2, 256)


def test_content_filter_envelope_without_choices_fails_over_without_retries(monkeypatch):
    envelope = SimpleNamespace(
        choices=None, usage=None,
        model_extra={"base_resp": {"status_code": 1027, "status_msg": "output new_sensitive"}},
    )
    script = _Script(envelope)
    client = _client(script)
    fallback_calls = []
    monkeypatch.setattr(lc.LLMClient, "_try_fallback",
                        lambda self, *a: fallback_calls.append(a[-1]) or "fallback text")
    assert client.chat([{"role": "user", "content": "filtered-envelope"}]) == "fallback text"
    assert len(script.calls) == 1
    assert isinstance(fallback_calls[0], lc.LLMContentFiltered)
    assert "new_sensitive" in str(fallback_calls[0]) and "content_filter" in str(fallback_calls[0])
    assert lc._CB_STATE["minimax"]["consec"] == 1.0


def test_chat_retries_empty_choices_then_raises_typed_error_not_index_error():
    script = _Script(SimpleNamespace(choices=[], usage=None))
    client = _client(script)
    with pytest.raises(lc.LLMEmptyChoices, match="no error detail"):
        client.chat([{"role": "user", "content": "empty-choices"}])
    assert len(script.calls) == lc.MAX_RETRIES
    assert client.last_call_meta() is None


def _envelope(code, status_msg):
    return SimpleNamespace(choices=None, usage=None,
                           model_extra={"base_resp": {"status_code": code, "status_msg": status_msg}})


@pytest.mark.parametrize("code, status_msg", [
    (1004, "login fail: Please carry the API secret key in the 'Authorization' field"),
    (2049, "invalid api key"),
])
def test_minimax_auth_envelope_fails_over_after_a_single_attempt(monkeypatch, code, status_msg):
    script = _Script(_envelope(code, status_msg))
    client = _client(script)
    fallback_calls = []
    monkeypatch.setattr(lc.LLMClient, "_try_fallback",
                        lambda self, *a: fallback_calls.append(a[-1]) or "fallback text")
    assert client.chat([{"role": "user", "content": f"auth-envelope-{code}"}]) == "fallback text"
    assert len(script.calls) == 1
    exc, = fallback_calls
    assert isinstance(exc, lc.LLMEmptyChoices) and exc.deterministic
    assert str(code) in str(exc) and status_msg in str(exc) and "model=MiniMax-M3" in str(exc)
    assert lc._is_deterministic_auth_error(exc) and not lc._is_quota(exc)
    assert _classify_provider_outage(exc) == "auth"


def test_insufficient_balance_envelope_counts_as_quota_without_retries():
    script = _Script(_envelope(1008, "insufficient balance"))
    client = _client(script)
    with pytest.raises(lc.LLMEmptyChoices, match="1008") as ei:
        client.chat([{"role": "user", "content": "balance-envelope"}])
    assert len(script.calls) == 1
    assert ei.value.deterministic and lc._is_quota(ei.value)
    assert not lc._is_deterministic_auth_error(ei.value)
    assert _classify_provider_outage(ei.value) == "quota"
    assert lc._CB_STATE["minimax"]["consec429"] == 1.0  # counted toward the 429 breaker


def test_invalid_params_envelope_is_not_retried_and_is_no_outage():
    script = _Script(_envelope(2013, "invalid params, temperature out of range"))
    client = _client(script)
    with pytest.raises(lc.LLMEmptyChoices, match="2013") as ei:
        client.chat([{"role": "user", "content": "invalid-params-envelope"}])
    assert len(script.calls) == 1
    assert ei.value.deterministic and lc._is_deterministic_invalid_request_error(ei.value)
    assert not lc._is_deterministic_auth_error(ei.value) and not lc._is_quota(ei.value)
    assert _classify_provider_outage(ei.value) is None


@pytest.mark.parametrize("code, status_msg", [
    (2056, "usage limit exceeded (2056)"), (1002, "rate limit exceeded"), (1013, "internal error"),
])
def test_transient_envelopes_keep_the_retry_budget(code, status_msg):
    script = _Script(_envelope(code, status_msg))
    client = _client(script)
    with pytest.raises(lc.LLMEmptyChoices) as ei:
        client.chat([{"role": "user", "content": f"transient-envelope-{code}"}])
    assert not ei.value.deterministic
    assert len(script.calls) == lc.MAX_RETRIES


def test_fallback_auth_envelope_enters_the_deterministic_cooldown(monkeypatch):
    primary_script = _Script(_resp(content="", finish="content_filter"))
    fallback_script = _Script(_envelope(2049, "invalid api key"))
    fakes = {"kimi": primary_script, "minimax": fallback_script}
    monkeypatch.setattr(lc.LLMClient, "_build_openai_client",
                        staticmethod(lambda provider, api_key, base_url: _fake_openai(fakes[provider])))
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "minimax")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "MiniMax-M3")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "sk-bad")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "http://127.0.0.1:2/v1")
    client = lc.LLMClient(provider="kimi", api_key="sk-test",
                          base_url="http://127.0.0.1:1/v1", model="kimi-k2")
    with pytest.raises(lc.LLMContentFiltered):
        client.chat([{"role": "user", "content": "fallback-auth-envelope"}])
    assert len(primary_script.calls) == 1 and len(fallback_script.calls) == 1
    assert ("minimax", "MiniMax-M3", "http://127.0.0.1:2/v1") in lc._FB_AUTH_UNAVAILABLE_UNTIL


@pytest.mark.parametrize("model", ["abab6.5s-chat-0429", "MiniMax-M2-2401", "glm-4-1422"])
def test_status_like_model_id_stays_out_of_envelope_messages(model):
    script = _Script(SimpleNamespace(choices=[], usage=None))
    client = _client(script, model=model)
    with pytest.raises(lc.LLMEmptyChoices) as ei:
        client.chat([{"role": "user", "content": f"status-like-model-{model}"}])
    exc = ei.value
    assert model not in str(exc) and exc.model == model
    assert not lc._is_quota(exc) and not lc._is_content_filter(exc)
    assert _classify_provider_outage(exc) is None
    assert lc._CB_STATE.get("minimax", {}).get("consec429", 0.0) == 0.0  # no 429-breaker count

    filtered = lc._empty_choices_error(_envelope(1027, "output new_sensitive"), "minimax", model, None)
    assert isinstance(filtered, lc.LLMContentFiltered) and filtered.model == model
    assert model not in str(filtered) and not lc._is_quota(filtered)
    assert _classify_provider_outage(filtered) is None


# ---------------------------------------------------------------- empty completion
def test_length_with_empty_content_raises_empty_completion_without_outage_words():
    script = _Script(_resp(content="", finish="length", usage=_usage(90, 512)))
    client = _client(script)
    with pytest.raises(lc.EmptyCompletion) as ei:
        client._chat_openai([{"role": "user", "content": "q"}], 0.2, 512)
    exc = ei.value
    assert exc.finish_reason == "length" and exc.raw_finish_reason == "length"
    assert exc.sent_max_tokens == 512 and exc.provider == "minimax"
    assert exc.usage["prompt_tokens"] == 90 and exc.usage["completion_tokens"] == 512
    text = str(exc)
    assert "finish_reason=length" in text and "max_tokens=512" in text
    assert "LLM_MINIMAX_DISABLE_THINKING" in text
    assert not any(word in text.lower() for word in _OUTAGE_WORDS)
    assert _classify_provider_outage(exc) is None
    assert not lc._is_quota(exc)
    assert not lc._is_deterministic_auth_error(exc)
    assert isinstance(exc, RuntimeError)


@pytest.mark.parametrize("max_tokens", [4290, 4010, 1400, 4220])
def test_empty_completion_omits_status_like_max_tokens(max_tokens):
    client = _client(_Script(_resp(content=None, finish="length")))
    with pytest.raises(lc.EmptyCompletion) as ei:
        client._chat_openai([{"role": "user", "content": "q"}], 0.2, max_tokens)
    exc = ei.value
    assert str(max_tokens) not in str(exc)
    assert exc.sent_max_tokens == max_tokens
    assert _classify_provider_outage(exc) is None
    assert lc._is_quota(exc) is False
    assert not lc._is_deterministic_auth_error(exc)
    assert not lc._is_deterministic_invalid_request_error(exc)


def test_thinking_knob_names_the_real_config_flags(monkeypatch):
    assert lc._thinking_knob("kimi") == "LLM_KIMI_DISABLE_THINKING"
    assert lc._thinking_knob("MiniMax") == "LLM_MINIMAX_DISABLE_THINKING"
    for provider in ("deepseek", "qwen", "glm"):
        assert lc._thinking_knob(provider) == "LLM_DISABLE_THINKING"
    assert lc._thinking_knob("openai") is None and lc._thinking_knob(None) is None
    # Every provider Config can switch thinking off for has a knob, and every knob exists.
    for provider in Config._DISABLE_THINKING_EXTRA_BODY:
        assert hasattr(Config, lc._thinking_knob(provider))

    monkeypatch.setattr(Config, "LLM_MINIMAX_DISABLE_THINKING", False, raising=False)
    enabled = lc._completion_failure("minimax", "length", "length", None, 256)
    assert "set LLM_MINIMAX_DISABLE_THINKING=true" in str(enabled)
    plain = lc._completion_failure("openai", "stop", "stop", None, 256)
    assert "DISABLE_THINKING" not in str(plain) and "raise max_tokens" in str(plain)


def test_content_filter_empty_reply_is_not_a_runtime_error_and_fails_over_once(monkeypatch):
    script = _Script(_resp(content="", finish="sensitive"))
    client = _client(script)
    with pytest.raises(lc.LLMContentFiltered) as ei:
        client._chat_openai([{"role": "user", "content": "q"}], 0.2, 256)
    assert not isinstance(ei.value, RuntimeError)
    assert "content_filter" in str(ei.value) and ei.value.raw_finish_reason == "sensitive"

    fallback_calls = []

    def no_fallback(self, messages, temperature, max_tokens, response_format, primary_error):
        fallback_calls.append(primary_error)
        return None

    monkeypatch.setattr(lc.LLMClient, "_try_fallback", no_fallback)
    script.calls.clear()
    with pytest.raises(lc.LLMContentFiltered):
        client.chat([{"role": "user", "content": "filtered"}])
    assert len(script.calls) == 1  # no transient retries on a filtered prompt
    assert len(fallback_calls) == 1 and isinstance(fallback_calls[0], lc.LLMContentFiltered)
    assert lc._CB_STATE["minimax"]["consec"] == 1.0  # counted toward the 422 breaker


def test_aborted_empty_reply_raises_retryable_aborted_completion():
    script = _Script(_resp(content="", finish="network_error"))
    client = _client(script)
    with pytest.raises(lc.LLMAbortedCompletion) as ei:
        client.chat([{"role": "user", "content": "aborted"}])
    assert isinstance(ei.value, RuntimeError)
    assert len(script.calls) == lc.MAX_RETRIES
    assert _classify_provider_outage(ei.value) is None


def test_list_content_is_flattened_instead_of_crashing():
    parts = [{"type": "reasoning", "text": "hidden"}, {"type": "text", "text": "visible"}]
    client = _client(_Script(_resp(content=parts)))
    assert client._chat_openai([{"role": "user", "content": "q"}], 0.2, 256) == "visible"


# ---------------------------------------------------------------- cache policy
def test_length_reply_is_returned_but_never_cached_and_stop_reply_is_cached():
    truncated = _Script(_resp(content="partial answer", finish="length", usage=_usage(5, 7)))
    client = _client(truncated)
    messages = [{"role": "user", "content": "cache-length"}]
    assert client.chat(messages) == "partial answer"
    assert client.last_call_meta()["cacheable"] is False
    assert client.chat(messages) == "partial answer"
    assert len(truncated.calls) == 2  # LLMCache was not populated

    complete = _Script(_resp(content="full answer", finish="stop"))
    client = _client(complete)
    messages = [{"role": "user", "content": "cache-stop"}]
    assert client.chat(messages) == "full answer"
    assert client.chat(messages) == "full answer"
    assert len(complete.calls) == 1
    meta = client.last_call_meta()
    assert meta["served_by"] == "cache" and meta["usage"]["total_tokens"] == 0


@pytest.mark.parametrize("finish, content", [
    ("content_filter", "half a sentence"),
    ("error", "fragment"),
    ("stop", "answer <think> reasoning cut by the cap"),
])
def test_other_non_cacheable_replies_are_not_cached(finish, content):
    script = _Script(_resp(content=content, finish=finish))
    client = _client(script)
    messages = [{"role": "user", "content": f"cache-{finish}"}]
    first = client.chat(messages)
    assert client.chat(messages) == first
    assert len(script.calls) == 2


def test_flag_off_keeps_legacy_unconditional_caching(monkeypatch):
    monkeypatch.setattr(Config, "LLM_TRANSPORT_STRICT", False, raising=False)
    script = _Script(_resp(content="partial answer", finish="length"))
    client = _client(script)
    messages = [{"role": "user", "content": "cache-legacy"}]
    assert client.chat(messages) == client.chat(messages) == "partial answer"
    assert len(script.calls) == 1


def test_failed_meta_construction_never_masks_the_completion(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("meta boom")

    monkeypatch.setattr(lc, "_usage_dict", boom)
    script = _Script(_resp(content="answer", finish="stop", usage=None))
    client = _client(script)
    messages = [{"role": "user", "content": "meta-failure"}]
    assert client.chat(messages) == "answer"
    assert client.last_call_meta() is None
    assert client.chat(messages) == "answer"
    assert len(script.calls) == 2  # no metadata -> not cached (fail-safe)


# ---------------------------------------------------------------- think stripping
def test_closed_think_block_is_stripped_in_both_modes(monkeypatch):
    for strict in (True, False):
        monkeypatch.setattr(Config, "LLM_TRANSPORT_STRICT", strict, raising=False)
        client = _client(_Script(_resp(content="<think>x</think>answer")))
        assert client._chat_openai([{"role": "user", "content": "q"}], 0.2, 256) == "answer"
        assert client.last_call_meta()["think_stripped"] is True


def test_orphan_closer_is_stripped_only_in_strict_mode(monkeypatch):
    client = _client(_Script(_resp(content="reasoning</think>answer")))
    assert client._chat_openai([{"role": "user", "content": "q"}], 0.2, 256) == "answer"
    assert client.last_call_meta()["think_stripped"] is True

    client = _client(_Script(_resp(content="İ</think>ok")))
    assert client.chat([{"role": "user", "content": "unicode-orphan"}]) == "ok"

    monkeypatch.setattr(Config, "LLM_TRANSPORT_STRICT", False, raising=False)
    client = _client(_Script(_resp(content="reasoning</think>answer")))
    assert client._chat_openai([{"role": "user", "content": "q"}], 0.2, 256) == "reasoning</think>answer"
    assert client.last_call_meta()["think_stripped"] is False


def test_chat_json_keeps_a_literal_think_tag_inside_the_json_value():
    script = _Script(_resp(content='{"k": "</think>", "v": "<think>"}'))
    client = _client(script)
    assert client.chat_json([{"role": "user", "content": "json-literal-tag"}]) == {"k": "</think>", "v": "<think>"}
    assert len(script.calls) == 1 and script.calls[0]["response_format"] == {"type": "json_object"}
    meta = client.last_call_meta()
    assert meta["think_stripped"] is False and meta["cacheable"] is True

    fenced = _client(_Script(_resp(content='```json\n{"k": "</think>"}\n```')))
    assert fenced.chat_json([{"role": "user", "content": "json-fenced-tag"}]) == {"k": "</think>"}

    # JSON mode still removes leading reasoning that lacks its opening tag.
    orphan = _client(_Script(_resp(content='plan the {"k": ...} shape</think>{"k": 1}')))
    assert orphan.chat_json([{"role": "user", "content": "json-orphan"}]) == {"k": 1}

    # Documented trade-off: a plain reply keeps the gateway's orphan rule and loses its head.
    plain = _client(_Script(_resp(content='{"k": "</think>"}')))
    assert plain.chat([{"role": "user", "content": "plain-literal-tag"}]) == '"}'


def test_unterminated_think_raises_in_strict_mode_and_passes_through_legacy(monkeypatch):
    client = _client(_Script(_resp(content="<think>unterminated", finish="length")))
    with pytest.raises(lc.EmptyCompletion) as ei:
        client._chat_openai([{"role": "user", "content": "q"}], 0.2, 256)
    assert ei.value.finish_reason == "length"

    monkeypatch.setattr(Config, "LLM_TRANSPORT_STRICT", False, raising=False)
    assert client._chat_openai([{"role": "user", "content": "q"}], 0.2, 256) == "<think>unterminated"
    assert client.last_call_meta()["cacheable"] is False


def test_flag_off_returns_exactly_the_legacy_clean_content(monkeypatch):
    """LLM_TRANSPORT_STRICT=false: the reply is exactly _clean_content(raw), with the legacy
    empty check on the raw text (a closed-block-only reply still returns '')."""
    monkeypatch.setattr(Config, "LLM_TRANSPORT_STRICT", False, raising=False)
    corpus = ["plain", "  padded  \n", "<think>a</think>b", "a<think>b</think>c<think>d</think>e",
              "<think>only reasoning</think>", "x </think> y", "<THINK>upper</THINK>z"]
    for raw in corpus + ['{"k": "</think>"}', '{"k": "<think>"}']:
        for response_format in (None, {"type": "json_object"}):
            client = _client(_Script(_resp(content=raw)))
            out = client._chat_openai([{"role": "user", "content": "q"}], 0.2, 256, response_format)
            assert out == client._clean_content(raw)


def test_strict_output_equals_legacy_output_for_well_formed_replies(monkeypatch):
    corpus = ["plain", "  padded  \n", "<think>a</think>b", "a<think>b</think>c<think>d</think>e",
              "multi\nline\n\nanswer", '{"json": [1, 2, 3]}']
    outputs = {}
    for strict in (True, False):
        monkeypatch.setattr(Config, "LLM_TRANSPORT_STRICT", strict, raising=False)
        outputs[strict] = [
            _client(_Script(_resp(content=raw)))._chat_openai([{"role": "user", "content": "q"}], 0.2, 256)
            for raw in corpus
        ]
    assert outputs[True] == outputs[False]


# ---------------------------------------------------------------- per-call metadata
def test_last_call_meta_fields_and_foreign_client():
    script = _Script(_resp(content="answer", finish="stop", model="MiniMax-M3-served",
                           usage=_usage(40, 9, total_tokens=49,
                                        completion_tokens_details=SimpleNamespace(reasoning_tokens=3),
                                        prompt_tokens_details=SimpleNamespace(cached_tokens=30))))
    client = _client(script)
    assert client.chat([{"role": "user", "content": "meta"}]) == "answer"
    meta = client.last_call_meta()
    assert meta == {
        "client_id": id(client), "provider": "minimax", "model": "MiniMax-M3",
        "served_model": "MiniMax-M3-served", "finish_reason": "stop", "raw_finish_reason": "stop",
        "usage": {"prompt_tokens": 40, "completion_tokens": 9, "total_tokens": 49,
                  "reasoning_tokens": 3, "cached_tokens": 30},
        "usage_source": "provider", "think_stripped": False, "served_by": "primary",
        "cacheable": True,
    }
    meta["usage"]["prompt_tokens"] = -1  # a copy: callers cannot corrupt the stored metadata
    assert client.last_call_meta()["usage"]["prompt_tokens"] == 40
    assert client._last_usage["prompt_tokens"] == 40 and client._last_usage["completion_tokens"] == 9

    other = _client(_Script(_resp()))
    assert other.last_call_meta() is None
    assert other._last_usage is None

    # Per-thread: another thread never sees this thread's call metadata for the same client.
    seen = []
    worker = threading.Thread(target=lambda: seen.append((client.last_call_meta(), client._last_usage)))
    worker.start()
    worker.join(timeout=10)
    assert seen == [(None, None)]
    assert client.last_call_meta()["usage"]["prompt_tokens"] == 40


def test_concurrent_chat_on_one_client_meters_each_call_own_usage(monkeypatch):
    """Two threads share one client; a barrier holds both after their completion so both have
    finished before either is metered. The old instance-level _last_usage made one thread
    meter the other's tokens here."""
    monkeypatch.setattr(Config, "LLM_CACHE_ENABLED", False, raising=False)
    usage_by_tag = {"A": (111, 11), "B": (2222, 222)}

    def create(**kwargs):
        tag = kwargs["messages"][0]["content"]
        return _resp(content=f"answer-{tag}", usage=_usage(*usage_by_tag[tag]))

    client = _client(create)
    barrier = threading.Barrier(2)
    original = client._chat_openai

    def gated(*args, **kwargs):
        out = original(*args, **kwargs)
        barrier.wait(timeout=10)
        return out

    monkeypatch.setattr(client, "_chat_openai", gated)
    results, errors = {}, []

    def worker(tag):
        tel.set_run_context(f"run-infra1-race-{tag}", stage="report")
        try:
            out = client.chat([{"role": "user", "content": tag}])
            results[tag] = (out, client.last_call_meta(), client._last_usage)
        except Exception as exc:  # noqa: BLE001 — surfaced by the assertion below
            errors.append(exc)
        finally:
            tel.set_run_context(None)

    threads = [threading.Thread(target=worker, args=(tag,)) for tag in usage_by_tag]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    try:
        assert not errors
        for tag, (pt, ct) in usage_by_tag.items():
            out, meta, legacy_usage = results[tag]
            assert out == f"answer-{tag}"
            assert (meta["usage"]["prompt_tokens"], meta["usage"]["completion_tokens"]) == (pt, ct)
            assert (legacy_usage["prompt_tokens"], legacy_usage["completion_tokens"]) == (pt, ct)
            total = tel.LLMMeter.snapshot(f"run-infra1-race-{tag}")["total"]
            assert (total["calls"], total["prompt_tokens"], total["completion_tokens"]) == (1, pt, ct)
    finally:
        for tag in usage_by_tag:
            tel.LLMMeter.reset(f"run-infra1-race-{tag}")


def test_fallback_served_reply_is_restamped_as_this_clients_call(monkeypatch):
    fallback_script = _Script(_resp(content="fallback answer", finish="stop", model="kimi-served",
                                    usage=_usage(12, 4)))
    primary_script = _Script(_resp(content="", finish="content_filter"))
    fakes = {"minimax": primary_script, "kimi": fallback_script}
    monkeypatch.setattr(lc.LLMClient, "_build_openai_client",
                        staticmethod(lambda provider, api_key, base_url: _fake_openai(fakes[provider])))
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "kimi")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "kimi-fallback-model")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "sk-fallback")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "http://127.0.0.1:2/v1")
    client = lc.LLMClient(provider="minimax", api_key="sk-test",
                          base_url="http://127.0.0.1:1/v1", model="MiniMax-M3")

    messages = [{"role": "user", "content": "failover"}]
    assert client.chat(messages) == "fallback answer"
    assert len(primary_script.calls) == 1 and len(fallback_script.calls) == 1
    meta = client.last_call_meta()
    assert meta["client_id"] == id(client)
    assert meta["served_by"] == "fallback"
    assert (meta["provider"], meta["model"], meta["served_model"]) == ("kimi", "kimi-fallback-model", "kimi-served")
    assert meta["usage"]["prompt_tokens"] == 12
    assert client._last_usage["completion_tokens"] == 4

    # A fallback that also filters: the primary's typed error propagates, nothing is served.
    fakes["kimi"] = _Script(_resp(content="", finish="content_filter"))
    monkeypatch.setattr(lc, "_FB_OPENAI_CLIENTS", {})
    lc._CB_STATE.clear()
    with pytest.raises(lc.LLMContentFiltered):
        client.chat([{"role": "user", "content": "failover-filtered"}])
    assert client.last_call_meta() is None


def test_chat_meters_finish_reason_and_provider_usage():
    client = _client(_Script(_resp(content="answer", finish="max_tokens", usage=_usage(21, 8))))
    tel.set_run_context("run-infra1-finish", stage="ontology")
    try:
        client.chat([{"role": "user", "content": "meter"}])
        snap = tel.LLMMeter.snapshot("run-infra1-finish")
    finally:
        tel.set_run_context(None)
        tel.LLMMeter.reset("run-infra1-finish")
    assert snap["total"]["prompt_tokens"] == 21 and snap["total"]["completion_tokens"] == 8
    assert snap["finish_reasons"] == {"ontology": {"length": 1}}


def test_last_usage_property_is_writable_on_bare_clients():
    client = object.__new__(lc.LLMClient)
    client._last_usage = None  # the pattern existing tests use; must never raise
    assert client._last_usage is None and client.last_call_meta() is None
    client._last_usage = {"prompt_tokens": 3, "completion_tokens": 2}
    assert client._last_usage["prompt_tokens"] == 3 and client._last_usage["completion_tokens"] == 2
    client._last_usage = None
    assert client._last_usage is None


# ---------------------------------------------------------------- CLI providers
def test_claude_cli_meta_reads_envelope_but_metering_keeps_text_estimate(monkeypatch):
    envelope = {
        "type": "result", "subtype": "success", "is_error": False, "result": "cli answer",
        "usage": {"input_tokens": 4, "cache_read_input_tokens": 100,
                  "cache_creation_input_tokens": 20, "output_tokens": 7},
        "modelUsage": {"claude-haiku-x": {"outputTokens": 1}, "claude-opus-x": {"outputTokens": 7}},
    }
    monkeypatch.setattr(lc.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(envelope), stderr=""))
    client = lc.LLMClient(provider="claude-cli", model="claude-opus-x")
    recorded = []
    monkeypatch.setattr(tel.LLMMeter, "record",
                        classmethod(lambda cls, *a, **k: recorded.append((a, k))))
    messages = [{"role": "user", "content": "x" * 400}]
    assert client.chat(messages) == "cli answer"
    meta = client.last_call_meta()
    assert meta["finish_reason"] == "stop" and meta["served_by"] == "primary"
    assert meta["served_model"] == "claude-opus-x"
    assert meta["usage_source"] == "cli"
    assert meta["usage"] == {"prompt_tokens": 124, "completion_tokens": 7, "total_tokens": 131,
                             "reasoning_tokens": 0, "cached_tokens": 100}
    assert client._last_usage is None  # CLI usage was never exposed through _last_usage
    (args, kwargs), = recorded
    assert args[2] == tel.estimate_tokens("x" * 400) and args[3] == tel.estimate_tokens("cli answer")
    assert kwargs["finish_reason"] == "stop"


def test_codex_cli_meta_has_no_usage(monkeypatch):
    monkeypatch.setattr(lc.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout="codex answer", stderr=""))
    client = lc.LLMClient(provider="codex-cli")
    assert client._chat_codex_cli([{"role": "user", "content": "q"}], 0.2, 64) == "codex answer"
    meta = client.last_call_meta()
    assert meta["finish_reason"] == "stop" and meta["served_model"] is None
    assert meta["usage_source"] == "none" and meta["usage"]["total_tokens"] == 0


# ---------------------------------------------------------------- chat_with_tools
def _tool_call(arguments, call_id="call_1", name="search"):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


def test_chat_with_tools_reports_malformed_arguments_instead_of_hiding_them():
    malformed = '{"query": "oil prices"'
    calls = [_tool_call(malformed), _tool_call('{"query": "ok"}', "call_2"),
             _tool_call("[1, 2]", "call_3")]
    client = _client(_Script(_resp(content="", finish="tool_calls", model="MiniMax-M3-served",
                                   tool_calls=calls, usage=_usage(30, 6))))
    out = client.chat_with_tools([{"role": "user", "content": "q"}], tools_schema=[])
    bad, good, non_object = out["tool_calls"]
    assert bad["arguments"] == {} and bad["arguments_error"] and bad["raw_arguments"] == malformed
    assert good["arguments"] == {"query": "ok"} and good["arguments_error"] is None
    assert good["raw_arguments"] == '{"query": "ok"}'
    assert non_object["arguments"] == [1, 2] and "not an object" in non_object["arguments_error"]
    assert out["finish_reason"] == "tool_calls" and out["served_model"] == "MiniMax-M3-served"
    assert out["content"] == ""
    meta = client.last_call_meta()
    assert meta["finish_reason"] == "tool_calls" and meta["usage"]["prompt_tokens"] == 30


def test_tool_call_arguments_past_the_parser_limits_are_reported_not_raised():
    # FU-12: an oversized integer or too-deep nesting is an arguments_error, never a raise.
    huge = '{"query": ' + "9" * 5000 + "}"
    deep = '{"query": ' + "[" * 100_000 + "]" * 100_000 + "}"
    calls = [_tool_call(huge), _tool_call(deep, "call_2"), _tool_call('{"query": "ok"}', "call_3")]
    client = _client(_Script(_resp(content="", finish="tool_calls", model="MiniMax-M3",
                                   tool_calls=calls, usage=_usage(30, 6))))
    with default_int_digit_limit():
        out = client.chat_with_tools([{"role": "user", "content": "q"}], tools_schema=[])
    big, nested, good = out["tool_calls"]
    assert big["arguments"] == {} and big["raw_arguments"] == huge
    assert big["arguments_error"].startswith("ValueError: ")
    assert nested["arguments"] == {} and nested["raw_arguments"] == deep
    assert nested["arguments_error"].startswith("RecursionError: ")
    assert good["arguments"] == {"query": "ok"} and good["arguments_error"] is None


def test_chat_with_tools_guards_empty_choices():
    script = _Script(_resp(content="first", finish="stop"),
                     SimpleNamespace(choices=[], usage=None,
                                     model_extra={"base_resp": {"status_code": 2056,
                                                                "status_msg": "usage limit exceeded"}}))
    client = _client(script)
    assert client.chat_with_tools([{"role": "user", "content": "q"}], tools_schema=[])["content"] == "first"
    assert client.last_call_meta()["finish_reason"] == "stop"
    with pytest.raises(lc.LLMEmptyChoices, match="2056"):
        client.chat_with_tools([{"role": "user", "content": "q"}], tools_schema=[])
    assert len(script.calls) == 1 + lc.MAX_RETRIES
    # A failed call never leaves the previous call's metadata behind.
    assert client.last_call_meta() is None


def test_chat_with_tools_content_filter_envelope_fails_fast():
    script = _Script(SimpleNamespace(choices=[], usage=None,
                                     model_extra={"base_resp": {"status_code": 1026,
                                                                "status_msg": "input new_sensitive"}}))
    client = _client(script)
    with pytest.raises(lc.LLMContentFiltered):
        client.chat_with_tools([{"role": "user", "content": "q"}], tools_schema=[])
    assert len(script.calls) == 1
    assert lc._CB_STATE["minimax"]["consec"] == 1.0


def test_chat_with_tools_deterministic_envelope_fails_fast():
    script = _Script(_envelope(1004, "login fail"))
    client = _client(script)
    with pytest.raises(lc.LLMEmptyChoices, match="status 401"):
        client.chat_with_tools([{"role": "user", "content": "q"}], tools_schema=[])
    assert len(script.calls) == 1


def test_chat_with_tools_strips_think_like_chat(monkeypatch):
    client = _client(_Script(_resp(content="plan</think>final section", tool_calls=[])))
    out = client.chat_with_tools([{"role": "user", "content": "q"}], tools_schema=[])
    assert out["content"] == "final section"
    monkeypatch.setattr(Config, "LLM_TRANSPORT_STRICT", False, raising=False)
    out = client.chat_with_tools([{"role": "user", "content": "q"}], tools_schema=[])
    assert out["content"] == "plan</think>final section"


# ---------------------------------------------------------------- telemetry
def test_snapshot_gains_finish_reasons_only_after_a_record_with_one():
    rid = "run-infra1-telemetry"
    try:
        tel.LLMMeter.record("minimax", "m", 10, 5, 1.0, stage="graph", run_id=rid)
        snap = tel.LLMMeter.snapshot(rid)
        assert "finish_reasons" not in snap
        status_keys = set(tel.LLMMeter.status_snapshot(rid))
        tel.LLMMeter.record("minimax", "m", 1, 1, 1.0, stage="graph", run_id=rid, finish_reason="stop")
        tel.LLMMeter.record("minimax", "m", 1, 1, 1.0, stage="graph", run_id=rid, finish_reason="length")
        tel.LLMMeter.record("minimax", "m", 1, 1, 1.0, stage="report", run_id=rid, finish_reason="stop")
        snap = tel.LLMMeter.snapshot(rid)
        assert snap["finish_reasons"] == {"graph": {"stop": 1, "length": 1}, "report": {"stop": 1}}
        assert set(tel.LLMMeter.status_snapshot(rid)) == status_keys == {
            "run_id", "total", "by_stage", "cost_estimated"}
    finally:
        tel.LLMMeter.reset(rid)


# ---------------------------------------------------------------- knob
@pytest.mark.parametrize("value, expected", [(None, "True"), ("false", "False"), (" TRUE ", "True")])
def test_transport_strict_knob_default_and_parsing(value, expected):
    env = {k: v for k, v in os.environ.items() if k != "LLM_TRANSPORT_STRICT"}
    env["DRF_TEST_PROCESS"] = "1"
    if value is not None:
        env["LLM_TRANSPORT_STRICT"] = value
    proc = subprocess.run(
        [sys.executable, "-c", "from app.config import Config; print(Config.LLM_TRANSPORT_STRICT)"],
        cwd=os.path.join(_REPO_ROOT, "backend"), env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == expected


def test_transport_strict_knob_is_documented_in_env_example():
    with open(os.path.join(_REPO_ROOT, ".env.example"), encoding="utf-8") as f:
        assert "# LLM_TRANSPORT_STRICT=true" in f.read()
