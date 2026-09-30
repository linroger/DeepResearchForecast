"""Offline tests for EVAL-10: LLMClient per-instance isolation in app/utils/llm_client.py.

Covers the keyword-only ``use_cache`` / ``pinned`` constructor options, the single
``_routing_pinned()`` predicate (fallback, pinned, or a provider other than the current
global primary keeps its own model and endpoint under LLM_TIERED_ROUTING), the pinned
no-failover rule (the circuit-breaker shortcut included) and the pinned cache namespace,
plus the byte-identical defaults of a default-provider client built without the new options.
Every OpenAI response is a SimpleNamespace fed through a fake client: no network, no real LLM.
"""

import inspect
from types import SimpleNamespace

import pytest

from app.config import Config
from app.utils import llm_client as lc
from app.utils import telemetry as tel

PRIMARY = "minimax"
PRIMARY_MODEL = "MiniMax-M3"
STRONG_ALIAS = "primary-strong-alias"
FAST_ALIAS = "primary-fast-alias"


# ---------------------------------------------------------------- fakes / fixtures
def _resp(content="ok", finish="stop"):
    message = SimpleNamespace(content=content, tool_calls=[])
    choice = SimpleNamespace(message=message, finish_reason=finish)
    return SimpleNamespace(choices=[choice], usage=None)


class _Transport:
    """A fake OpenAI client: serves scripted responses (the last one repeats), records kwargs."""

    def __init__(self, *responses):
        self.responses = list(responses) or [_resp()]
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.responses[min(len(self.calls), len(self.responses)) - 1]
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture
def transports(monkeypatch):
    """Route every OpenAI client LLMClient builds to a per-provider fake transport."""
    fakes = {}

    def build(provider, api_key, base_url):
        return fakes.setdefault(provider, _Transport())

    monkeypatch.setattr(lc.LLMClient, "_build_openai_client", staticmethod(build))
    return fakes


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    for name in ("LLM_FALLBACK_PROVIDER", "LLM_FALLBACK_MODEL", "LLM_FALLBACK_BASE_URL",
                 "LLM_FALLBACK_API_KEY", "LLM_FALLBACK_REASONING_EFFORT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(lc, "_retry_delay", lambda exc, attempt: 0.0)
    monkeypatch.setattr(Config, "LLM_PROVIDER", PRIMARY, raising=False)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", PRIMARY_MODEL, raising=False)
    monkeypatch.setattr(Config, "LLM_API_KEY", "sk-primary", raising=False)
    monkeypatch.setattr(Config, "LLM_BASE_URL", "http://127.0.0.1:1/v1", raising=False)
    monkeypatch.setattr(Config, "LLM_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "LLM_TRANSPORT_STRICT", True, raising=False)
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "LLM_RUN_BUDGET_TOKENS", 0, raising=False)
    monkeypatch.setattr(Config, "LLM_RUN_BUDGET_USD", 0.0, raising=False)
    monkeypatch.setattr(Config, "LLM_TIERED_ROUTING", False, raising=False)
    monkeypatch.setattr(Config, "LLM_STRONG_MODEL", None, raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_MODEL", None, raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_PROVIDER", None, raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_BASE_URL", None, raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_API_KEY", None, raising=False)
    monkeypatch.setattr(tel.LLMCache, "_store", {})
    monkeypatch.setattr(tel.LLMCache, "_order", [])
    lc._CB_STATE.clear()
    lc._CALL_META.meta = None
    yield
    lc._CB_STATE.clear()
    lc._CALL_META.meta = None


def _tiered(monkeypatch):
    monkeypatch.setattr(Config, "LLM_TIERED_ROUTING", True, raising=False)
    monkeypatch.setattr(Config, "LLM_STRONG_MODEL", STRONG_ALIAS, raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_MODEL", FAST_ALIAS, raising=False)


def _fast_tier_provider(monkeypatch):
    """Configure a distinct fast-tier provider so _fast_provider_client() returns a client."""
    monkeypatch.setattr(Config, "LLM_FAST_PROVIDER", "deepseek", raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_BASE_URL", "http://127.0.0.1:3/v1", raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_API_KEY", "sk-fast", raising=False)


def _fallback_env(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "kimi")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "kimi-fallback-model")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "sk-fallback")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "http://127.0.0.1:2/v1")


def _msgs(tag):
    return [{"role": "user", "content": f"isolation-{tag}"}]


def _tools_schema():
    return [{"type": "function", "function": {"name": "noop", "parameters": {"type": "object"}}}]


# ---------------------------------------------------------------- constructor contract
def test_new_options_are_keyword_only_with_legacy_defaults(transports):
    params = inspect.signature(lc.LLMClient.__init__).parameters
    assert list(params)[:5] == ["self", "provider", "api_key", "base_url", "model"]
    for name, default in (("use_cache", True), ("pinned", False)):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert params[name].default is default
    client = lc.LLMClient()
    assert (client.use_cache, client._pinned, client._routing_pinned()) == (True, False, False)
    pinned = lc.LLMClient(pinned=True, use_cache=False)
    assert (pinned.use_cache, pinned._pinned, pinned._routing_pinned()) == (False, True, True)


# ---------------------------------------------------------------- cache bypass
def test_use_cache_false_makes_real_calls(transports):
    default = lc.LLMClient()
    assert default.chat(_msgs("cache")) == "ok"
    assert default.chat(_msgs("cache")) == "ok"
    assert len(transports[PRIMARY].calls) == 1  # 1 transport call + 1 cache hit
    assert default.last_call_meta()["served_by"] == "cache"
    # a default client's cache key is byte-identical to the pre-EVAL-10 key
    legacy_key = tel.LLMCache.key(PRIMARY, PRIMARY_MODEL, _msgs("cache"), 0.7, 4096, None)
    assert list(tel.LLMCache._store) == [legacy_key]

    no_cache = lc.LLMClient(use_cache=False)
    assert no_cache.chat(_msgs("cache")) == "ok"  # never reads the default client's entry
    assert no_cache.chat(_msgs("cache")) == "ok"
    assert len(transports[PRIMARY].calls) == 3  # 2 more real transport calls
    assert no_cache.last_call_meta()["served_by"] == "primary"
    no_cache.chat(_msgs("never-cached"))
    assert list(tel.LLMCache._store) == [legacy_key]  # and never writes an entry


def test_cache_disabled_globally_still_bypasses_every_client(transports, monkeypatch):
    monkeypatch.setattr(Config, "LLM_CACHE_ENABLED", False, raising=False)
    client = lc.LLMClient()
    client.chat(_msgs("off"))
    client.chat(_msgs("off"))
    assert len(transports[PRIMARY].calls) == 2 and tel.LLMCache._store == {}


# ---------------------------------------------------------------- no failover
def test_pinned_never_fails_over(transports, monkeypatch):
    _fallback_env(monkeypatch)
    transports[PRIMARY] = _Transport(_resp(content="", finish="content_filter"))
    transports["kimi"] = _Transport(_resp(content="fallback answer"))

    # sanity: the same failure on an unpinned client is served by the configured fallback
    assert lc.LLMClient().chat(_msgs("failover")) == "fallback answer"
    assert len(transports["kimi"].calls) == 1

    pinned = lc.LLMClient(pinned=True, use_cache=False)
    with pytest.raises(lc.LLMContentFiltered):
        pinned.chat(_msgs("pinned-failover"))
    assert len(transports["kimi"].calls) == 1  # the fallback spy was not used again
    assert pinned.last_call_meta() is None  # nothing was served

    # a retryable failure exhausts the retries and surfaces the primary's own error
    transports[PRIMARY] = _Transport(RuntimeError("primary transport down"))
    pinned = lc.LLMClient(pinned=True, use_cache=False)
    with pytest.raises(RuntimeError, match="primary transport down"):
        pinned.chat(_msgs("pinned-retries"))
    assert len(transports[PRIMARY].calls) == lc.MAX_RETRIES
    assert len(transports["kimi"].calls) == 1
    assert pinned._try_fallback(_msgs("direct"), 0.3, 64, None, RuntimeError("x")) is None


def test_pinned_client_fails_fast_during_breaker_cooldown(transports, monkeypatch):
    _fallback_env(monkeypatch)
    transports["kimi"] = _Transport(_resp(content="fallback answer"))
    monkeypatch.setattr(lc, "_cb_tripped", lambda provider: provider == PRIMARY)

    assert lc.LLMClient().chat(_msgs("breaker")) == "fallback answer"
    # the pinned error names the real reason (no failover by design), not a missing fallback
    with pytest.raises(RuntimeError, match="钉定客户端的提供方 minimax 处于 422/429 熔断冷却"
                                           "（pinned：不做失败转移）") as pinned_err:
        lc.LLMClient(pinned=True).chat(_msgs("breaker-pinned"))
    assert "回退提供方不可用" not in str(pinned_err.value)
    assert len(transports["kimi"].calls) == 1
    assert PRIMARY not in transports or transports[PRIMARY].calls == []

    # an unpinned client whose fallback is unavailable keeps the existing message
    monkeypatch.delenv("LLM_FALLBACK_PROVIDER")
    with pytest.raises(RuntimeError, match="主提供方 minimax 处于 422/429 熔断冷却，且回退提供方不可用"):
        lc.LLMClient().chat(_msgs("breaker-no-fallback"))


def test_pinned_client_never_serves_a_cached_fallback_reply(transports, monkeypatch):
    _fallback_env(monkeypatch)
    transports[PRIMARY] = _Transport(_resp(content="", finish="content_filter"),
                                     _resp(content="primary answer"))
    transports["kimi"] = _Transport(_resp(content="fallback answer"))

    unpinned = lc.LLMClient()
    assert unpinned.chat(_msgs("shared")) == "fallback answer"  # cached under the primary key
    assert unpinned.chat(_msgs("shared")) == "fallback answer"  # default behaviour unchanged
    assert unpinned.last_call_meta()["served_by"] == "cache"

    pinned = lc.LLMClient(pinned=True)  # cache on, but its own namespace
    assert pinned.chat(_msgs("shared")) == "primary answer"
    assert pinned.last_call_meta()["served_by"] == "primary"
    assert pinned.chat(_msgs("shared")) == "primary answer"
    assert pinned.last_call_meta()["served_by"] == "cache"  # served from its own entry
    assert len(transports[PRIMARY].calls) == 2 and len(transports["kimi"].calls) == 1


def test_no_cache_client_stays_uncached_through_failover(transports, monkeypatch):
    _fallback_env(monkeypatch)
    transports[PRIMARY] = _Transport(_resp(content="", finish="content_filter"))
    transports["kimi"] = _Transport(_resp(content="fallback answer"))

    # default client: the fallback's own chat() caches under the fallback key (unchanged)
    assert lc.LLMClient().chat(_msgs("failover-cache")) == "fallback answer"
    assert len(transports["kimi"].calls) == 1
    stored = dict(tel.LLMCache._store)
    assert len(stored) == 2  # the primary key and the fallback client's own key

    no_cache = lc.LLMClient(use_cache=False)  # unpinned, so it may still fail over
    for expected_calls in (2, 3):
        assert no_cache.chat(_msgs("failover-cache")) == "fallback answer"
        assert len(transports["kimi"].calls) == expected_calls  # a real fallback call each time
        assert no_cache.last_call_meta()["served_by"] == "fallback"
    assert tel.LLMCache._store == stored  # and nothing new was written


# ---------------------------------------------------------------- tier routing
def test_non_default_provider_keeps_own_model(transports, monkeypatch):
    _tiered(monkeypatch)
    secondary = lc.LLMClient(provider="deepseek", api_key="sk-ds",
                             base_url="http://127.0.0.1:4/v1", model="deepseek-chat")
    secondary.chat(_msgs("secondary-strong"))
    secondary.chat(_msgs("secondary-fast"), tier="fast")
    assert [c["model"] for c in transports["deepseek"].calls] == ["deepseek-chat", "deepseek-chat"]

    # the default-provider client is still routed to the primary's tier aliases
    default = lc.LLMClient()
    default.chat(_msgs("default-strong"))
    default.chat(_msgs("default-fast"), tier="fast")
    assert [c["model"] for c in transports[PRIMARY].calls] == [STRONG_ALIAS, FAST_ALIAS]
    assert default._model_for_tier("strong") == STRONG_ALIAS

    # an explicitly pinned default-provider client keeps its own model too
    pinned = lc.LLMClient(pinned=True)
    pinned.chat(_msgs("pinned-strong"))
    assert transports[PRIMARY].calls[-1]["model"] == PRIMARY_MODEL
    assert pinned._model_for_tier("fast") == PRIMARY_MODEL


def test_settings_hot_switch_pins_the_old_client(transports, monkeypatch):
    _tiered(monkeypatch)
    old = lc.LLMClient()
    assert old._model_for_tier("strong") == STRONG_ALIAS
    # the operator switches the primary provider; the old client now belongs to a secondary
    monkeypatch.setattr(Config, "LLM_PROVIDER", "kimi", raising=False)
    assert old._routing_pinned() is True
    old.chat(_msgs("after-switch"))
    assert transports[PRIMARY].calls[-1]["model"] == PRIMARY_MODEL


def test_fast_client_skipped_when_pinned(transports, monkeypatch):
    _tiered(monkeypatch)
    _fast_tier_provider(monkeypatch)
    secondary_kwargs = {"provider": "kimi", "api_key": "sk-k",
                        "base_url": "http://127.0.0.1:5/v1", "model": "kimi-own"}
    for client, own in ((lc.LLMClient(pinned=True), PRIMARY), (lc.LLMClient(**secondary_kwargs), "kimi")):
        before = len(transports[own].calls)
        client.chat(_msgs(f"fast-chat-{own}"), tier="fast")
        out = client.chat_with_tools(_msgs(f"fast-tools-{own}"), _tools_schema(), tier="fast")
        assert out["content"] == "ok"
        served = transports[own].calls[before:]
        assert [c["model"] for c in served] == [client.model, client.model]
        assert "tools" in served[1]
        assert "deepseek" not in transports  # the fast-tier second client was never built

    # an unpinned default-provider client still takes the fast-tier second client (unchanged)
    default = lc.LLMClient()
    default.chat(_msgs("fast-chat-default"), tier="fast")
    default.chat_with_tools(_msgs("fast-tools-default"), _tools_schema(), tier="fast")
    assert [c["model"] for c in transports["deepseek"].calls] == [FAST_ALIAS, FAST_ALIAS]


def test_one_routing_read_decides_model_and_endpoint(transports, monkeypatch):
    """A hot-switch between two _routing_pinned() reads must not split one call's routing."""
    _tiered(monkeypatch)
    _fast_tier_provider(monkeypatch)
    client = lc.LLMClient()
    reads = []

    def flipping():  # unpinned on the first read, pinned on any second read of the same call
        reads.append(len(reads))
        return len(reads) % 2 == 0

    monkeypatch.setattr(client, "_routing_pinned", flipping)
    client._chat_openai(_msgs("one-read"), 0.2, 64, tier="fast")
    assert len(reads) == 1
    reads.clear()
    client.chat_with_tools(_msgs("one-read-tools"), _tools_schema(), tier="fast")
    assert len(reads) == 1
    # both calls: the fast alias went to the fast-tier client, never to the primary endpoint
    assert [c["model"] for c in transports["deepseek"].calls] == [FAST_ALIAS, FAST_ALIAS]
    assert PRIMARY not in transports or transports[PRIMARY].calls == []


def test_chat_caches_meters_and_retries_under_the_model_the_request_carried(transports, monkeypatch):
    """chat() resolves the route once: its cache key, its meter entry and every transport
    retry share one model, even when a hot-switch lands between two routing reads."""
    _tiered(monkeypatch)
    _fast_tier_provider(monkeypatch)
    transports["deepseek"] = _Transport(RuntimeError("transient fast-tier failure"), _resp("fast-ok"))
    client = lc.LLMClient()
    reads = []

    def flipping():  # unpinned on the first read of a call, pinned on any second read
        reads.append(len(reads))
        return len(reads) % 2 == 0

    monkeypatch.setattr(client, "_routing_pinned", flipping)
    run_id = "run-eval10-one-route"
    tel.set_run_context(run_id, stage="report")
    try:
        assert client.chat(_msgs("one-route"), tier="fast") == "fast-ok"
        assert len(reads) == 1  # one read served the cache key, the meter and both attempts
        assert [c["model"] for c in transports["deepseek"].calls] == [FAST_ALIAS, FAST_ALIAS]
        assert PRIMARY not in transports or transports[PRIMARY].calls == []
        # INFRA-6: the meter names the serving provider (the fast-tier second client's).
        assert set(tel.LLMMeter.snapshot(run_id)["by_model"]) == {f"deepseek:{FAST_ALIAS}"}
        key = tel.LLMCache.key(PRIMARY, FAST_ALIAS, _msgs("one-route"), 0.7, 4096, None)
        assert tel.LLMCache.get(key) == "fast-ok"
        reads.clear()
        assert client.chat(_msgs("one-route"), tier="fast") == "fast-ok"  # replayed from the cache
        assert len(transports["deepseek"].calls) == 2
    finally:
        tel.set_run_context(None)
        tel.LLMMeter.reset(run_id)


def test_routing_off_leaves_every_client_on_its_own_model(transports):
    for client in (lc.LLMClient(), lc.LLMClient(pinned=True),
                   lc.LLMClient(provider="deepseek", api_key="sk", model="deepseek-chat")):
        for tier in ("strong", "fast"):
            assert client._model_for_tier(tier) == client.model
