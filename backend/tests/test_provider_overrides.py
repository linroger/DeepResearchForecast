"""Offline tests for INFRA-6: one provider request-override helper for every OpenAI-compatible
caller (app/utils/provider_overrides.py).

The helper owns the Kimi coding-agent User-Agent, the reasoning ``extra_body`` and the Kimi
temperature rule. Golden tests compare it, and each call site that now uses it (LLMClient
client construction and request kwargs, the settings and preflight probes, the OASIS model
factory), with a frozen copy of the pre-INFRA-6 logic across every provider, temperature
and thinking-knob combination. The documented fixes are tested on their own: a fast-tier
call served by LLM_FAST_PROVIDER gets that provider's overrides, metering and error
attribution, the OASIS model gets the extra_body of the provider _resolve_provider picked, and
the doctor.sh inline probe sends the same request as the preflight probe (Kimi 0.6, not 0). No
network, no real LLM: every OpenAI client and the camel ModelFactory are fakes that record what
they receive.
"""

import ast
import importlib.util
import itertools
import json
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import openai
import pytest
from camel.models import ModelFactory

from app.config import Config
from app.utils import llm_client as lc
from app.utils import oasis_llm
from app.utils import telemetry as tel
from app.utils.provider_overrides import (
    FALLBACK_REASONING_EFFORTS,
    openai_compat_request_overrides,
    provider_temperature,
)

BACKEND = Path(__file__).resolve().parents[1]
DOCTOR_SH = BACKEND.parent / "scripts" / "doctor.sh"
UA = "golden-agent/9.9"
LOOPBACK = "http://127.0.0.1:9/v1"
# Every PROVIDER_META provider, the fallback-only Antigravity alias and an unknown id.
PROVIDERS = (*Config.PROVIDER_META, "antigravity", "not-a-provider")
OPENAI_COMPAT = tuple(p for p in lc.OPENAI_COMPATIBLE_PROVIDERS)
TEMPERATURES = (None, 0.0, 0.7)
THINKING_KNOBS = ("LLM_KIMI_DISABLE_THINKING", "LLM_MINIMAX_DISABLE_THINKING", "LLM_DISABLE_THINKING")
KNOB_STATES = tuple(itertools.product((True, False), repeat=len(THINKING_KNOBS)))


# ---------------------------------------------------------------- frozen legacy logic
# Verbatim copies of the pre-INFRA-6 rules (feat/finharness-transplants @ fedaef3), with
# ``self.provider`` replaced by an explicit ``provider``. Do not "fix" these: they are the
# reference the golden tests hold the helper and its call sites to.
def _legacy_client_headers(provider):
    """LLMClient._build_openai_client: the default_headers client kwarg (None = not passed)."""
    if provider == "kimi":
        return {"User-Agent": Config.LLM_USER_AGENT}
    return None


def _legacy_coerce_temperature(provider, temperature, extra_body):
    """LLMClient._coerce_temperature."""
    if provider != 'kimi':
        return temperature
    thinking_disabled = bool(extra_body and (extra_body.get("thinking") or {}).get("type") == "disabled")
    return 0.6 if thinking_disabled else 1.0


def _legacy_client_request(provider, temperature):
    """LLMClient._chat_openai: _apply_reasoning_options + _coerce_temperature on the kwargs."""
    kwargs = {"temperature": temperature}
    extra_body = Config.reasoning_extra_body(provider)
    if extra_body:
        kwargs["extra_body"] = extra_body
    kwargs["temperature"] = _legacy_coerce_temperature(provider, temperature, extra_body)
    return kwargs


def _legacy_probe(provider, api_key, base_url, model, timeout):
    """settings._test_openai_compat_provider and preflight._live_openai_compat (identical
    apart from the timeout): the (client kwargs, create kwargs) of the probe request."""
    client_kwargs = {"api_key": api_key, "base_url": base_url, "timeout": timeout, "max_retries": 0}
    if provider == 'kimi':
        client_kwargs["default_headers"] = {"User-Agent": Config.LLM_USER_AGENT}
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
        "temperature": 0,
        "max_tokens": 16,
    }
    extra_body = Config._DISABLE_THINKING_EXTRA_BODY.get(provider)
    if extra_body:
        kwargs["extra_body"] = extra_body
    if provider == 'kimi':
        thinking_disabled = bool(extra_body and (extra_body.get("thinking") or {}).get("type") == "disabled")
        kwargs["temperature"] = 0.6 if thinking_disabled else 1.0
    return client_kwargs, kwargs


def _legacy_oasis(provider):
    """oasis_llm.create_oasis_model: (swapped-client headers or None, extra_body or None). The
    extra_body came from the provider-less Config.reasoning_extra_body(), i.e. Config.LLM_PROVIDER."""
    headers = {"User-Agent": Config.LLM_USER_AGENT} if provider == 'kimi' else None
    return headers, Config.reasoning_extra_body()


def _canonical(value):
    """JSON text of a request part: equal dicts that differ in 0 vs 0.0 serialise differently."""
    return json.dumps(value, sort_keys=True)


# ---------------------------------------------------------------- fakes / fixtures
def _resp(content="ok", finish="stop"):
    message = SimpleNamespace(content=content, tool_calls=[])
    choice = SimpleNamespace(message=message, finish_reason=finish)
    usage = SimpleNamespace(prompt_tokens=11, completion_tokens=3, total_tokens=14)
    return SimpleNamespace(choices=[choice], usage=usage, model=None)


class _Transport:
    """A fake OpenAI client: returns one canned reply per call and records the kwargs."""

    def __init__(self):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return _resp()


class _RecordingOpenAI:
    """Stands in for openai.OpenAI / AsyncOpenAI: records constructor and create kwargs."""

    built = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.created = []
        type(self).built.append(self)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.created.append(kwargs)
        return _resp("pong")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(Config, "LLM_USER_AGENT", UA, raising=False)
    monkeypatch.setattr(Config, "LLM_HTTP2", False, raising=False)
    monkeypatch.setattr(Config, "APP_BLOCK_PRIVATE_URLS", False, raising=False)
    for knob in THINKING_KNOBS:
        monkeypatch.setattr(Config, knob, True, raising=False)
    for name in ("LLM_FALLBACK_PROVIDER", "LLM_FALLBACK_MODEL", "LLM_FALLBACK_BASE_URL",
                 "LLM_FALLBACK_API_KEY", "LLM_FALLBACK_REASONING_EFFORT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(_RecordingOpenAI, "built", [])
    lc._CB_STATE.clear()
    lc._CALL_META.meta = None
    yield
    lc._CB_STATE.clear()
    lc._CALL_META.meta = None


def _set_knobs(monkeypatch, states):
    for knob, state in zip(THINKING_KNOBS, states, strict=True):
        monkeypatch.setattr(Config, knob, state, raising=False)


# ---------------------------------------------------------------- the helper itself
def test_golden_helper_equals_legacy_rules(monkeypatch):
    """Every provider x temperature x thinking-knob combination: the helper's headers,
    extra_body and temperature equal the legacy LLMClient rules."""
    checked = 0
    for states in KNOB_STATES:
        _set_knobs(monkeypatch, states)
        for provider, temperature in itertools.product(PROVIDERS, TEMPERATURES):
            out = openai_compat_request_overrides(provider, temperature)
            legacy_body = Config.reasoning_extra_body(provider)
            assert (out["default_headers"] or None) == _legacy_client_headers(provider)
            assert (out["extra_body"] or None) == legacy_body
            # None stays None (the caller sends no temperature: the legacy OASIS path, which
            # never set one); a float follows the legacy _coerce_temperature rule.
            expected = (None if temperature is None
                        else _legacy_coerce_temperature(provider, temperature, legacy_body))
            assert _canonical(out["temperature"]) == _canonical(expected), (provider, temperature, states)
            checked += 1
    assert checked == len(KNOB_STATES) * len(PROVIDERS) * len(TEMPERATURES)


def test_kimi_gets_the_user_agent_and_no_other_provider_does():
    assert openai_compat_request_overrides("kimi")["default_headers"] == {"User-Agent": UA}
    assert openai_compat_request_overrides(" KIMI ")["default_headers"] == {"User-Agent": UA}
    for provider in PROVIDERS:
        if provider != "kimi":
            assert openai_compat_request_overrides(provider)["default_headers"] == {}


def test_kimi_temperature_rule_follows_the_thinking_knob(monkeypatch):
    assert openai_compat_request_overrides("kimi", 0.2)["temperature"] == 0.6
    monkeypatch.setattr(Config, "LLM_KIMI_DISABLE_THINKING", False, raising=False)
    assert openai_compat_request_overrides("kimi", 0.2)["temperature"] == 1.0
    assert openai_compat_request_overrides("kimi", None)["temperature"] is None
    # force_disable_thinking sends the disable body, so the thinking-off value applies
    assert openai_compat_request_overrides("kimi", 0, force_disable_thinking=True)["temperature"] == 0.6
    assert openai_compat_request_overrides("glm", 0.2)["temperature"] == 0.2
    # the rule LLMClient applies to the extra_body it attached (case-insensitive provider)
    disabled = {"thinking": {"type": "disabled"}}
    assert provider_temperature(" Kimi ", 0.2, disabled) == 0.6
    assert provider_temperature("kimi", 0.2, None) == 1.0
    assert provider_temperature("kimi", 0.2, {"thinking": {"type": "enabled"}}) == 1.0
    assert provider_temperature("kimi", None, disabled) is None
    assert provider_temperature("glm", 0.2, disabled) == 0.2


def test_returned_extra_body_is_a_fresh_copy():
    for force in (False, True):
        first = openai_compat_request_overrides("kimi", force_disable_thinking=force)
        first["extra_body"]["thinking"]["type"] = "enabled"
        first["extra_body"]["injected"] = True
        first["default_headers"]["User-Agent"] = "mutated"
        second = openai_compat_request_overrides("kimi", force_disable_thinking=force)
        assert second["extra_body"] == {"thinking": {"type": "disabled"}}
        assert second["default_headers"] == {"User-Agent": UA}
    assert Config._DISABLE_THINKING_EXTRA_BODY["kimi"] == {"thinking": {"type": "disabled"}}
    assert Config.reasoning_extra_body("kimi") == {"thinking": {"type": "disabled"}}
    one = openai_compat_request_overrides("qwen")["extra_body"]
    assert one == {"enable_thinking": False}
    assert one is not openai_compat_request_overrides("qwen")["extra_body"]


def test_force_disable_thinking_returns_the_disable_body_whatever_the_knob(monkeypatch):
    _set_knobs(monkeypatch, (False, False, False))
    for provider, body in Config._DISABLE_THINKING_EXTRA_BODY.items():
        assert openai_compat_request_overrides(provider)["extra_body"] == {}
        assert openai_compat_request_overrides(provider, force_disable_thinking=True)["extra_body"] == body
    for provider in ("openai", "claude-cli", "codex-cli", "antigravity"):
        assert openai_compat_request_overrides(provider, force_disable_thinking=True)["extra_body"] == {}


def test_unknown_or_empty_provider_gets_no_overrides(monkeypatch):
    # an empty provider never falls back to the global primary (here kimi, which has every override)
    monkeypatch.setattr(Config, "LLM_PROVIDER", "kimi", raising=False)
    for provider in ("", None, "   ", "not-a-provider"):
        for force in (False, True):
            out = openai_compat_request_overrides(provider, 0.3, force_disable_thinking=force)
            assert out == {"default_headers": {}, "extra_body": {}, "temperature": 0.3}


def test_helper_module_imports_no_llm_sdk_or_http_client():
    tree = ast.parse((BACKEND / "app" / "utils" / "provider_overrides.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add("." * node.level + (node.module or ""))
    assert imported == {"copy", "typing", "..config"}


def _doctor_inline_probe_source():
    """The Python heredoc doctor.sh runs when backend/scripts/preflight.py is absent."""
    blocks = re.findall(r"<<'PY'\n(.*?)\nPY\n", DOCTOR_SH.read_text(encoding="utf-8"), flags=re.S)
    matching = [block for block in blocks if "def probe_openai_compat" in block]
    assert len(matching) == 1
    return matching[0]


def test_call_sites_keep_no_copy_of_the_rules():
    """One source of truth: the call sites read the UA, the thinking bodies and the Kimi
    temperature rule only through the helper."""
    call_sites = {rel: (BACKEND / rel).read_text(encoding="utf-8")
                  for rel in ("app/utils/llm_client.py", "app/utils/oasis_llm.py", "app/api/settings.py",
                              "scripts/preflight.py")}
    call_sites["scripts/doctor.sh (inline probe)"] = _doctor_inline_probe_source()
    for rel, source in call_sites.items():
        for copy_marker in ("LLM_USER_AGENT", "_DISABLE_THINKING_EXTRA_BODY", "reasoning_extra_body(",
                            "== 'kimi'", '== "kimi"', "0.6 if"):
            assert copy_marker not in source, (rel, copy_marker)
        assert "openai_compat_request_overrides(" in source, rel


# ---------------------------------------------------------------- LLMClient call sites
def test_golden_client_construction_headers(monkeypatch):
    monkeypatch.setattr(openai, "OpenAI", _RecordingOpenAI)
    for provider in OPENAI_COMPAT:
        lc.LLMClient._build_openai_client(provider, "sk-golden", LOOPBACK)
        built = _RecordingOpenAI.built[-1].kwargs
        assert built.get("default_headers") == _legacy_client_headers(provider), provider
        assert ("default_headers" in built) == (provider == "kimi")


def _client_for(provider, monkeypatch, transports):
    monkeypatch.setattr(lc.LLMClient, "_build_openai_client",
                        staticmethod(lambda p, api_key, base_url: transports.setdefault(p, _Transport())))
    monkeypatch.setattr(Config, "LLM_PROVIDER", provider, raising=False)
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", f"{provider}-model", raising=False)
    return lc.LLMClient(provider=provider, api_key="sk-golden", base_url=LOOPBACK, model=f"{provider}-model")


def test_golden_client_request_kwargs(monkeypatch):
    """The request LLMClient sends (plain and native-tools paths) carries exactly the legacy
    extra_body and temperature for every OpenAI-compatible provider and knob combination."""
    monkeypatch.setattr(Config, "LLM_TIERED_ROUTING", False, raising=False)
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", False, raising=False)
    tools = [{"type": "function", "function": {"name": "noop", "parameters": {"type": "object"}}}]
    for states in KNOB_STATES:
        _set_knobs(monkeypatch, states)
        for provider in OPENAI_COMPAT:
            transports = {}
            client = _client_for(provider, monkeypatch, transports)
            for temperature in (0.0, 0.7):
                client._chat_openai([{"role": "user", "content": "q"}], temperature, 64)
                client.chat_with_tools([{"role": "user", "content": "q"}], tools, temperature=temperature)
                expected = _legacy_client_request(provider, temperature)
                for sent in transports[provider].calls[-2:]:
                    got = {k: sent[k] for k in ("temperature", "extra_body") if k in sent}
                    assert _canonical(got) == _canonical(expected), (provider, temperature, states)


def test_request_temperature_follows_the_extra_body_it_sends(monkeypatch):
    """The thinking knobs are read once per request and the Kimi temperature is derived from the
    extra_body that request carries, so a knob that changes between two reads can never pair
    thinking.type=disabled with temperature 1.0 (a 400 on the K2.7 Code gateway)."""
    transports = {}
    client = _client_for("kimi", monkeypatch, transports)
    monkeypatch.setattr(Config, "LLM_TIERED_ROUTING", False, raising=False)
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", False, raising=False)
    reads = []

    def body_that_flips_after_one_read(cls, provider=None):
        reads.append(provider)
        return {"thinking": {"type": "disabled"}} if len(reads) == 1 else None

    monkeypatch.setattr(Config, "reasoning_extra_body", classmethod(body_that_flips_after_one_read))
    messages = [{"role": "user", "content": "q"}]
    tools = [{"type": "function", "function": {"name": "noop", "parameters": {"type": "object"}}}]
    for send in (lambda: client._chat_openai(messages, 0.2, 64),
                 lambda: client.chat_with_tools(messages, tools, temperature=0.2)):
        reads.clear()
        send()
        sent = transports["kimi"].calls[-1]
        assert reads == ["kimi"]
        assert sent["extra_body"] == {"thinking": {"type": "disabled"}} and sent["temperature"] == 0.6


def _route_fast_tier_to_qwen(monkeypatch):
    """Tiered routing on, with the fast tier served by a qwen second client."""
    monkeypatch.setattr(Config, "LLM_TIERED_ROUTING", True, raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_MODEL", "qwen-fast", raising=False)
    monkeypatch.setattr(Config, "LLM_STRONG_MODEL", None, raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_PROVIDER", "qwen", raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_BASE_URL", "http://127.0.0.1:8/v1", raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_API_KEY", "sk-fast", raising=False)


def test_fast_tier_on_another_provider_uses_that_providers_overrides(monkeypatch):
    """Primary kimi, fast tier served by qwen: the fast-tier request carries qwen's extra_body
    and the caller's temperature (not kimi's 0.6), and the call metadata and meter name qwen.
    The strong tier on the same client keeps kimi's overrides."""
    transports = {}
    client = _client_for("kimi", monkeypatch, transports)
    _route_fast_tier_to_qwen(monkeypatch)
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "LLM_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "LLM_RUN_BUDGET_TOKENS", 0, raising=False)
    monkeypatch.setattr(Config, "LLM_RUN_BUDGET_USD", 0.0, raising=False)
    monkeypatch.setattr(tel.LLMCache, "_store", {})
    monkeypatch.setattr(tel.LLMCache, "_order", [])
    tools = [{"type": "function", "function": {"name": "noop", "parameters": {"type": "object"}}}]
    run_id = "run-infra6-fast-tier"
    tel.set_run_context(run_id, stage="graph")
    try:
        assert client.chat([{"role": "user", "content": "fast"}], temperature=0.2, tier="fast") == "ok"
        fast = transports["qwen"].calls[-1]
        assert fast["model"] == "qwen-fast"
        assert fast["extra_body"] == {"enable_thinking": False} and fast["temperature"] == 0.2
        meta = client.last_call_meta()
        assert meta["provider"] == "qwen" and meta["served_by"] == "primary"

        # a replay of the same fast-tier route is attributed to the same serving provider
        assert client.chat([{"role": "user", "content": "fast"}], temperature=0.2, tier="fast") == "ok"
        assert len(transports["qwen"].calls) == 1
        assert client.last_call_meta()["provider"] == "qwen"
        assert client.last_call_meta()["served_by"] == "cache"

        client.chat_with_tools([{"role": "user", "content": "fast-tools"}], tools, temperature=0.3, tier="fast")
        tool_call = transports["qwen"].calls[-1]
        assert tool_call["extra_body"] == {"enable_thinking": False} and tool_call["temperature"] == 0.3
        assert client.last_call_meta()["provider"] == "qwen"

        assert client.chat([{"role": "user", "content": "strong"}], temperature=0.2) == "ok"
        strong = transports["kimi"].calls[-1]
        assert strong["extra_body"] == {"thinking": {"type": "disabled"}} and strong["temperature"] == 0.6
        assert client.last_call_meta()["provider"] == "kimi"

        by_model = tel.LLMMeter.snapshot(run_id)["by_model"]
        assert set(by_model) == {"qwen:qwen-fast", "kimi:kimi-model"}
        assert by_model["qwen:qwen-fast"]["calls"] == 3  # chat, its cache replay, chat_with_tools
    finally:
        tel.set_run_context(None)
        tel.LLMMeter.reset(run_id)


def test_fast_tier_failures_name_the_serving_provider(monkeypatch):
    """Primary kimi, fast tier on qwen: an empty reply or a reply without choices raises an
    error attributed to qwen, whose hint names qwen's thinking knob, not kimi's."""
    transports = {}
    client = _client_for("kimi", monkeypatch, transports)
    _route_fast_tier_to_qwen(monkeypatch)
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", False, raising=False)
    qwen_transport, provider = client._serving_endpoint(True)
    assert provider == "qwen" and qwen_transport is transports["qwen"]
    messages = [{"role": "user", "content": "q"}]

    qwen_transport.chat.completions.create = lambda **kwargs: _resp("", "length")
    with pytest.raises(lc.EmptyCompletion) as empty:
        client._chat_openai(messages, 0.2, 64, tier="fast")
    assert empty.value.provider == "qwen" and "provider=qwen" in str(empty.value)
    assert "LLM_DISABLE_THINKING" in str(empty.value)
    assert "LLM_KIMI_DISABLE_THINKING" not in str(empty.value)

    # a MiniMax-style error envelope without choices (2049 = invalid key: deterministic)
    envelope = SimpleNamespace(choices=[], usage=None, model=None,
                               model_extra={"base_resp": {"status_code": 2049, "status_msg": "invalid api key"}})
    qwen_transport.chat.completions.create = lambda **kwargs: envelope
    with pytest.raises(lc.LLMEmptyChoices) as no_choices:
        client._chat_openai(messages, 0.2, 64, tier="fast")
    assert no_choices.value.provider == "qwen" and "provider=qwen" in str(no_choices.value)
    tools = [{"type": "function", "function": {"name": "noop", "parameters": {"type": "object"}}}]
    with pytest.raises(lc.LLMEmptyChoices) as tool_error:
        client.chat_with_tools(messages, tools, temperature=0.2, tier="fast")
    assert tool_error.value.provider == "qwen" and tool_error.value.deterministic
    assert "provider=qwen" in str(tool_error.value)
    assert transports["kimi"].calls == []


def test_fast_tier_kimi_second_client_gets_the_user_agent_and_temperature_rule(monkeypatch):
    real_build = lc.LLMClient._build_openai_client
    built = []

    def build(provider, api_key, base_url):
        built.append(provider)
        return _Transport()

    monkeypatch.setattr(lc.LLMClient, "_build_openai_client", staticmethod(build))
    monkeypatch.setattr(Config, "LLM_PROVIDER", "minimax", raising=False)
    monkeypatch.setattr(Config, "LLM_TIERED_ROUTING", True, raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_MODEL", "kimi-fast", raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_PROVIDER", "kimi", raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_BASE_URL", "http://127.0.0.1:8/v1", raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_API_KEY", "sk-fast", raising=False)
    client = lc.LLMClient(provider="minimax", api_key="sk", base_url=LOOPBACK, model="MiniMax-M3")
    fast_client, provider = client._serving_endpoint(True)
    assert provider == "kimi" and built == ["minimax", "kimi"]
    client._chat_openai([{"role": "user", "content": "q"}], 0.1, 64, tier="fast")
    sent = fast_client.calls[-1]
    assert sent["temperature"] == 0.6 and sent["extra_body"] == {"thinking": {"type": "disabled"}}
    # the second client itself is built through _build_openai_client(kimi, ...), whose
    # headers come from the helper (see test_golden_client_construction_headers)
    monkeypatch.setattr(openai, "OpenAI", _RecordingOpenAI)
    real_build("kimi", "sk-fast", "http://127.0.0.1:8/v1")
    assert _RecordingOpenAI.built[-1].kwargs["default_headers"] == {"User-Agent": UA}


def test_pinned_and_non_primary_clients_keep_their_own_overrides(monkeypatch):
    """EVAL-10 routing: a pinned client, or a client of a provider other than the primary,
    is served by its own provider and gets its own overrides even on a fast-tier call."""
    transports = {}
    monkeypatch.setattr(lc.LLMClient, "_build_openai_client",
                        staticmethod(lambda p, api_key, base_url: transports.setdefault(p, _Transport())))
    monkeypatch.setattr(Config, "LLM_PROVIDER", "kimi", raising=False)
    monkeypatch.setattr(Config, "LLM_TIERED_ROUTING", True, raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_MODEL", "qwen-fast", raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_PROVIDER", "qwen", raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_BASE_URL", "http://127.0.0.1:8/v1", raising=False)
    monkeypatch.setattr(Config, "LLM_FAST_API_KEY", "sk-fast", raising=False)
    pinned = lc.LLMClient(provider="kimi", api_key="sk", base_url=LOOPBACK, model="kimi-k2.7", pinned=True)
    pinned._chat_openai([{"role": "user", "content": "q"}], 0.2, 64, tier="fast")
    sent = transports["kimi"].calls[-1]
    assert sent["model"] == "kimi-k2.7" and sent["temperature"] == 0.6
    assert sent["extra_body"] == {"thinking": {"type": "disabled"}}
    assert pinned.last_call_meta()["provider"] == "kimi"

    other = lc.LLMClient(provider="deepseek", api_key="sk", base_url=LOOPBACK, model="deepseek-chat")
    other._chat_openai([{"role": "user", "content": "q"}], 0.2, 64, tier="fast")
    sent = transports["deepseek"].calls[-1]
    assert sent["model"] == "deepseek-chat" and sent["temperature"] == 0.2
    assert sent["extra_body"] == {"thinking": {"type": "disabled"}}
    assert other.last_call_meta()["provider"] == "deepseek"
    assert "qwen" not in transports


def test_fallback_reasoning_effort_guard_uses_the_shared_set(monkeypatch):
    client = object.__new__(lc.LLMClient)
    client.provider = "antigravity"
    client._is_fallback = True
    for effort in FALLBACK_REASONING_EFFORTS:
        monkeypatch.setenv("LLM_FALLBACK_REASONING_EFFORT", effort.upper())
        kwargs = {}
        assert client._apply_reasoning_options(kwargs, "antigravity") is None
        assert kwargs == {"reasoning_effort": effort}
    monkeypatch.setenv("LLM_FALLBACK_REASONING_EFFORT", "extreme")
    with pytest.raises(ValueError, match="minimal/low/medium/high"):
        client._apply_reasoning_options({}, "antigravity")


# ---------------------------------------------------------------- probes
def _load_preflight():
    spec = importlib.util.spec_from_file_location("drf_preflight_infra6", BACKEND / "scripts" / "preflight.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("probe", ["settings", "preflight"])
def test_golden_probe_requests_match_legacy_and_production_headers(monkeypatch, probe):
    """Both connectivity probes send the helper's headers and disable-thinking body with
    temperature 0 (kimi: 0.6), byte-identical to the legacy probe request for every
    provider and knob combination."""
    monkeypatch.setattr(openai, "OpenAI", _RecordingOpenAI)
    if probe == "settings":
        from app.api import settings as settings_api

        def run(provider):
            return settings_api._test_openai_compat_provider(provider, "sk-probe", LOOPBACK, "m-probe")
        timeout = settings_api._TEST_TIMEOUT_SECONDS
    else:
        preflight = _load_preflight()

        def run(provider):
            return preflight._live_openai_compat("LLM_PROVIDER", provider, "sk-probe", LOOPBACK, "m-probe")
        timeout = 25
    for states in KNOB_STATES:
        _set_knobs(monkeypatch, states)
        for provider in OPENAI_COMPAT:
            result = run(provider)
            assert (result["ok"] if probe == "settings" else result[0] == "ok"), result
            recorder = _RecordingOpenAI.built[-1]
            legacy_client, legacy_request = _legacy_probe(provider, "sk-probe", LOOPBACK, "m-probe", timeout)
            assert _canonical(recorder.kwargs) == _canonical(legacy_client), (probe, provider)
            assert _canonical(recorder.created[-1]) == _canonical(legacy_request), (probe, provider, states)
            helper = openai_compat_request_overrides(provider, 0, force_disable_thinking=True)
            assert recorder.kwargs.get("default_headers", {}) == helper["default_headers"]
            assert recorder.created[-1].get("extra_body", {}) == helper["extra_body"]
            assert recorder.created[-1]["temperature"] == helper["temperature"]
    kimi = [r for r in _RecordingOpenAI.built if r.kwargs.get("default_headers")]
    assert kimi and all(r.kwargs["default_headers"] == {"User-Agent": UA} for r in kimi)
    assert all(r.created[-1]["extra_body"] == {"thinking": {"type": "disabled"}} for r in kimi)


def test_doctor_inline_probe_sends_the_preflight_request(monkeypatch, capsys):
    """doctor.sh's inline fallback probe (used when backend/scripts/preflight.py is absent)
    imports the helper and sends exactly the preflight probe's request for every provider and
    knob combination; before INFRA-6 it sent temperature 0 to Kimi, which K2.7 Code rejects."""
    source = _doctor_inline_probe_source()
    tree = ast.parse(source)
    assert any(isinstance(node, ast.ImportFrom) and node.module == "app.utils.provider_overrides"
               and [alias.name for alias in node.names] == ["openai_compat_request_overrides"]
               for node in ast.walk(tree))
    functions = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name in ("emit", "probe_openai_compat")]
    assert len(functions) == 2
    namespace = {"Config": Config, "openai_compat_request_overrides": openai_compat_request_overrides,
                 "sys": sys, "time": time, "failures": 0}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(DOCTOR_SH), "exec"), namespace)
    monkeypatch.setattr(openai, "OpenAI", _RecordingOpenAI)
    for states in KNOB_STATES:
        _set_knobs(monkeypatch, states)
        for provider in OPENAI_COMPAT:
            namespace["probe_openai_compat"]("LLM_PROVIDER", provider, "sk-probe", LOOPBACK, "m-probe")
            recorder = _RecordingOpenAI.built[-1]
            legacy_client, legacy_request = _legacy_probe(provider, "sk-probe", LOOPBACK, "m-probe", 25)
            assert _canonical(recorder.kwargs) == _canonical(legacy_client), provider
            assert _canonical(recorder.created[-1]) == _canonical(legacy_request), (provider, states)
    assert namespace["failures"] == 0
    assert "live completion OK" in capsys.readouterr().out
    kimi = [r for r in _RecordingOpenAI.built if r.kwargs.get("default_headers")]
    assert kimi and all(r.created[-1]["temperature"] == 0.6 for r in kimi)


# ---------------------------------------------------------------- OASIS model factory
@pytest.fixture
def camel_factory(monkeypatch):
    """Replace camel's ModelFactory.create with a recorder returning a bare model object."""
    created = []

    def create(**kwargs):
        model = SimpleNamespace(
            model_config_dict={}, model_type=kwargs.get("model_type"), _timeout=60, _max_retries=3,
            _url=kwargs.get("url"), _api_key=kwargs.get("api_key"),
            _request_chat_completion=lambda *a, **k: None, _client="camel-sync", _async_client="camel-async",
        )
        created.append((kwargs, model))
        return model

    monkeypatch.setattr(ModelFactory, "create", create)
    monkeypatch.setattr(openai, "OpenAI", _RecordingOpenAI)
    monkeypatch.setattr(openai, "AsyncOpenAI", _RecordingOpenAI)
    for name in ("LLM_BOOST_API_KEY", "LLM_BOOST_BASE_URL", "LLM_BOOST_MODEL_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_API_KEY", "sk-sim")
    monkeypatch.setenv("LLM_BASE_URL", LOOPBACK)
    monkeypatch.setenv("LLM_MODEL_NAME", "sim-model")
    return created


def test_golden_oasis_model_when_the_sim_provider_is_the_primary(monkeypatch, camel_factory):
    for states in KNOB_STATES:
        _set_knobs(monkeypatch, states)
        for provider in (p for p in OPENAI_COMPAT if p in Config.PROVIDER_META):
            monkeypatch.setattr(Config, "LLM_PROVIDER", provider, raising=False)
            monkeypatch.setenv("LLM_PROVIDER", provider)
            before = len(_RecordingOpenAI.built)
            model = oasis_llm.create_oasis_model({})
            legacy_headers, legacy_body = _legacy_oasis(provider)
            assert model.model_config_dict.get("extra_body") == legacy_body, (provider, states)
            swapped = _RecordingOpenAI.built[before:]
            if legacy_headers is None:
                assert swapped == [] and model._client == "camel-sync"
            else:
                assert [r.kwargs["default_headers"] for r in swapped] == [legacy_headers, legacy_headers]
                assert model._client is swapped[0] and model._async_client is swapped[1]


def test_oasis_model_uses_the_resolved_providers_extra_body(monkeypatch, camel_factory):
    """The sim's provider (env LLM_PROVIDER, else config llm_provider) differs from the global
    primary: the model carries the resolved provider's extra_body and UA, not the primary's."""
    monkeypatch.setattr(Config, "LLM_PROVIDER", "minimax", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    model = oasis_llm.create_oasis_model({"llm_provider": "qwen"})
    factory_kwargs, _ = camel_factory[-1]
    assert (factory_kwargs["api_key"], factory_kwargs["model_type"]) == ("sk-sim", "sim-model")
    assert model.model_config_dict["extra_body"] == {"enable_thinking": False}
    assert _legacy_oasis("qwen")[1] == {"thinking": {"type": "disabled"}}  # the legacy bug
    assert _RecordingOpenAI.built == []  # qwen has no default headers: camel's clients stay

    monkeypatch.setenv("LLM_PROVIDER", "kimi")
    model = oasis_llm.create_oasis_model({"llm_provider": "qwen"})
    assert model.model_config_dict["extra_body"] == {"thinking": {"type": "disabled"}}
    assert [r.kwargs["default_headers"] for r in _RecordingOpenAI.built] == [{"User-Agent": UA}] * 2

    monkeypatch.setattr(Config, "LLM_PROVIDER", "kimi", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    model = oasis_llm.create_oasis_model({})
    assert "extra_body" not in model.model_config_dict  # openai has no thinking body


def test_oasis_warns_when_only_the_sim_config_names_another_provider(monkeypatch, camel_factory):
    """The OASIS endpoint and model still come from LLM_BASE_URL/LLM_MODEL_NAME, so a provider
    named only by the simulation config (env LLM_PROVIDER unset) that differs from the global
    LLM_PROVIDER is flagged; every consistent combination stays silent."""
    warnings = []
    monkeypatch.setattr(oasis_llm.logger, "warning", lambda message, *a, **k: warnings.append(str(message)))
    monkeypatch.setattr(Config, "LLM_PROVIDER", "minimax", raising=False)

    def mismatch_warnings(config, env_provider):
        warnings.clear()
        if env_provider is None:
            monkeypatch.delenv("LLM_PROVIDER", raising=False)
        else:
            monkeypatch.setenv("LLM_PROVIDER", env_provider)
        oasis_llm.create_oasis_model(config)
        return [w for w in warnings if "llm_provider=" in w]

    flagged = mismatch_warnings({"llm_provider": "qwen"}, None)
    assert len(flagged) == 1 and "llm_provider=qwen" in flagged[0] and "LLM_PROVIDER=minimax" in flagged[0]
    assert mismatch_warnings({"llm_provider": "MiniMax"}, None) == []
    assert mismatch_warnings({}, None) == []
    assert mismatch_warnings({"llm_provider": "qwen"}, "qwen") == []
    assert mismatch_warnings({"llm_provider": "qwen"}, "kimi") == []


def test_inject_coding_agent_ua_wrapper(monkeypatch):
    monkeypatch.setattr(openai, "OpenAI", _RecordingOpenAI)
    monkeypatch.setattr(openai, "AsyncOpenAI", _RecordingOpenAI)
    model = SimpleNamespace(_timeout=5, _max_retries=1, _url=LOOPBACK, _api_key="sk", _client="orig",
                            _async_client="orig-async")
    oasis_llm._inject_coding_agent_ua(model)  # legacy call shape: kimi by default
    assert [r.kwargs for r in _RecordingOpenAI.built] == [
        {"timeout": 5, "max_retries": 1, "base_url": LOOPBACK, "api_key": "sk",
         "default_headers": {"User-Agent": UA}},
    ] * 2
    plain = SimpleNamespace(_client="orig")
    oasis_llm._inject_coding_agent_ua(plain, "minimax")  # no headers: nothing is swapped
    assert plain._client == "orig" and len(_RecordingOpenAI.built) == 2


def test_oasis_extra_body_is_not_shared_with_config(monkeypatch, camel_factory):
    monkeypatch.setenv("LLM_PROVIDER", "kimi")
    model = oasis_llm.create_oasis_model({})
    model.model_config_dict["extra_body"]["thinking"]["type"] = "enabled"
    assert Config._DISABLE_THINKING_EXTRA_BODY["kimi"] == {"thinking": {"type": "disabled"}}


# ---------------------------------------------------------------- startup validation
def test_config_validate_rejects_an_invalid_fallback_effort(monkeypatch):
    def effort_errors():
        return [e for e in Config.validate() if "LLM_FALLBACK_REASONING_EFFORT" in e]

    monkeypatch.setenv("LLM_FALLBACK_REASONING_EFFORT", "extreme")
    errors = effort_errors()
    assert len(errors) == 1 and "'extreme'" in errors[0] and "minimal/low/medium/high" in errors[0]
    for ok in ("", "  ", "low", "HIGH", " minimal "):
        monkeypatch.setenv("LLM_FALLBACK_REASONING_EFFORT", ok)
        assert effort_errors() == []
    monkeypatch.delenv("LLM_FALLBACK_REASONING_EFFORT")
    assert effort_errors() == []
