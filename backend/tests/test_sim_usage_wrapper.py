"""INFRA-2: the simulation child's LLMClient usage wrapper counts each request exactly once.

run_parallel_simulation._wrap_llm_client_usage wraps chat and chat_json on the decision-channel
/ in-band clients. A real LLMClient's chat_json sends every request through self.chat, which the
wrapper already counts, so wrapping chat_json as well double counted every chat_json call. The
wrapper now leaves chat_json alone on LLMClient instances and reads provider usage from INFRA-1's
per-call metadata (last_call_meta) before the legacy _last_usage attribute.

Offline: a real LLMClient on a fake OpenAI transport; no network, no real LLM, no subprocess.
"""

import os
import sys
from types import SimpleNamespace

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_BACKEND, "scripts")
for _p in (_BACKEND, _SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import run_parallel_simulation as rps  # noqa: E402

from app.config import Config  # noqa: E402
from app.utils import llm_client as lc  # noqa: E402
from app.utils import telemetry as tel  # noqa: E402


def _resp(content, prompt_tokens=None, completion_tokens=None):
    usage = (None if prompt_tokens is None
             else SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens))
    choice = SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=[]),
                             finish_reason="stop")
    return SimpleNamespace(choices=[choice], usage=usage)


class _Transport:
    def __init__(self):
        self.responses = []
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses[min(len(self.calls), len(self.responses)) - 1]


@pytest.fixture
def fresh_usage(monkeypatch):
    fresh = {"calls": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0,
             "by_source": {}, "by_model": {}}
    monkeypatch.setattr(rps, "_SIM_LLM_USAGE", fresh)
    return fresh


@pytest.fixture
def transport(monkeypatch):
    fake = _Transport()
    monkeypatch.setattr(lc.LLMClient, "_build_openai_client",
                        staticmethod(lambda provider, api_key, base_url: fake))
    monkeypatch.setattr(Config, "LLM_PROVIDER", "minimax", raising=False)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "MiniMax-M3", raising=False)
    monkeypatch.setattr(Config, "LLM_API_KEY", "sk-test", raising=False)
    monkeypatch.setattr(Config, "LLM_BASE_URL", "http://127.0.0.1:1/v1", raising=False)
    monkeypatch.setattr(Config, "LLM_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "LLM_TIERED_ROUTING", False, raising=False)
    monkeypatch.setattr(Config, "LLM_JSON_REPAIR_TURN", True, raising=False)
    monkeypatch.setattr(tel.LLMCache, "_store", {})
    monkeypatch.setattr(tel.LLMCache, "_order", [])
    lc._CALL_META.meta = None
    yield fake
    lc._CALL_META.meta = None


def _client():
    return rps._wrap_llm_client_usage(lc.LLMClient(provider="minimax"))


def test_llm_client_chat_json_call_is_counted_once(fresh_usage, transport):
    transport.responses = [_resp('{"decisions": []}', 800, 150)]
    client = _client()

    assert client.chat_json([{"role": "user", "content": "decide"}]) == {"decisions": []}

    assert len(transport.calls) == 1
    assert fresh_usage["calls"] == 1
    assert fresh_usage["by_source"] == {
        "provider": {"calls": 1, "prompt_tokens": 800, "completion_tokens": 150}}
    assert fresh_usage["by_model"]["MiniMax-M3"]["calls"] == 1


def test_repair_turn_counts_each_real_request_once(fresh_usage, transport):
    transport.responses = [_resp("[1]", 100, 10), _resp('{"a": 1}', 120, 12)]
    client = _client()

    assert client.chat_json([{"role": "user", "content": "decide"}]) == {"a": 1}

    assert len(transport.calls) == 2
    assert fresh_usage["calls"] == 2
    assert (fresh_usage["prompt_tokens"], fresh_usage["completion_tokens"]) == (220, 22)


def test_llm_client_chat_is_still_counted(fresh_usage, transport):
    transport.responses = [_resp("world update", 50, 5)]
    client = _client()

    assert client.chat([{"role": "user", "content": "evolve"}]) == "world update"
    assert fresh_usage["by_source"]["provider"]["calls"] == 1


def test_llm_client_without_provider_usage_is_estimated(fresh_usage, transport):
    transport.responses = [_resp('{"decisions": []}')]
    client = _client()

    client.chat_json([{"role": "user", "content": "x" * 400}])
    assert fresh_usage["calls"] == 1
    est = fresh_usage["by_source"]["estimate"]
    assert est["calls"] == 1 and est["prompt_tokens"] > 0


def test_non_llm_client_chat_json_is_still_wrapped(fresh_usage):
    class DuckClient:
        provider = "claude-cli"
        model = ""
        _last_usage = None

        def chat_json(self, messages, **kwargs):
            return {"commitments": []}

    client = rps._wrap_llm_client_usage(DuckClient())
    client.chat_json([{"role": "user", "content": "q"}])
    assert fresh_usage["calls"] == 1


def test_call_metadata_usage_preferred_over_last_usage(fresh_usage):
    class MetaClient:
        provider = "minimax"
        model = "MiniMax-M3"
        _last_usage = {"prompt_tokens": 1, "completion_tokens": 1}

        def __init__(self, meta):
            self._meta = meta

        def last_call_meta(self):
            return self._meta

        def chat(self, messages, **kwargs):
            return "reply"

    provider_meta = {"usage_source": "provider",
                     "usage": {"prompt_tokens": 700, "completion_tokens": 70}}
    rps._wrap_llm_client_usage(MetaClient(provider_meta)).chat([{"role": "user", "content": "q"}])
    assert fresh_usage["by_source"]["provider"]["prompt_tokens"] == 700

    # Metadata without provider usage (CLI envelope, cache hit) -> length estimate, not _last_usage.
    cli_meta = {"usage_source": "cli", "usage": {"prompt_tokens": 9, "completion_tokens": 9}}
    rps._wrap_llm_client_usage(MetaClient(cli_meta)).chat([{"role": "user", "content": "q"}])
    assert fresh_usage["by_source"]["estimate"]["calls"] == 1

    # No metadata for this call -> the legacy _last_usage attribute.
    rps._wrap_llm_client_usage(MetaClient(None)).chat([{"role": "user", "content": "q"}])
    assert fresh_usage["by_source"]["provider"] == {
        "calls": 2, "prompt_tokens": 701, "completion_tokens": 71}


def test_raising_call_metadata_falls_back_to_last_usage(fresh_usage):
    class BrokenMeta:
        provider = "minimax"
        model = "m"
        _last_usage = {"prompt_tokens": 30, "completion_tokens": 3}

        def last_call_meta(self):
            raise RuntimeError("meta exploded")

        def chat(self, messages, **kwargs):
            return "reply"

    rps._wrap_llm_client_usage(BrokenMeta()).chat([])
    assert fresh_usage["by_source"]["provider"]["prompt_tokens"] == 30
