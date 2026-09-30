"""INFRA-3: max_tokens escalation on empty length-truncated replies, and fail-closed handling
of truncated JSON in forecast extraction.

Covers LLMClient._chat_openai_escalating inside chat() and failover (LLM_LENGTH_ESCALATION /
LLM_MAX_ESCALATIONS / LLM_MAX_TOKENS_CEILING), LLMMeter.record_recovery, the report preflight
that treats an empty length reply as a reachable provider, and the forecast_extractor
LLM_JSON_TRUNCATION_FAIL_CLOSED paths (spine, binaries, market match and divergence passes,
critique, premortem, post-hoc) with the report agent carrying a lost spine's count into
forecast.json.
Every OpenAI response is a SimpleNamespace fed through a fake transport, and the forecast
paths use FakeLLMClient subclasses: no network, no real LLM.
"""

import json
import logging
import os
import re
from types import SimpleNamespace

import pytest

from app.config import Config
from app.services import forecast_extractor as fe
from app.utils import llm_client as lc
from app.utils import telemetry as tel
from tests.conftest import FakeLLMClient

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_KNOBS = {
    "LLM_LENGTH_ESCALATION": True,
    "LLM_MAX_ESCALATIONS": 2,
    "LLM_MAX_TOKENS_CEILING": 32768,
    "LLM_JSON_TRUNCATION_FAIL_CLOSED": True,
}


# ---------------------------------------------------------------- transport fakes
def _usage(pt, ct):
    return SimpleNamespace(prompt_tokens=pt, completion_tokens=ct)


def _resp(content="ok", finish="stop", usage=None):
    message = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)],
                           usage=usage)


def _empty_length(pt=90, ct=512):
    return _resp(content="", finish="length", usage=_usage(pt, ct))


def _fake_openai(create):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


class _Script:
    """A fake ``create`` serving scripted responses in order (the last repeats); records kwargs."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        item = self.responses[min(len(self.calls), len(self.responses)) - 1]
        if isinstance(item, BaseException):
            raise item
        return item

    @property
    def max_tokens(self):
        return [call["max_tokens"] for call in self.calls]


def _client(create, provider="minimax", model="MiniMax-M3"):
    client = lc.LLMClient(provider=provider, api_key="sk-test",
                          base_url="http://127.0.0.1:1/v1", model=model)
    client._openai_client = _fake_openai(create)
    return client


def _with_fallback(monkeypatch, primary_script, fallback_script):
    """A minimax primary whose failover goes to a real kimi fallback client on ``fallback_script``."""
    fakes = {"minimax": primary_script, "kimi": fallback_script}
    monkeypatch.setattr(lc.LLMClient, "_build_openai_client",
                        staticmethod(lambda provider, api_key, base_url: _fake_openai(fakes[provider])))
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "kimi")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "kimi-fallback-model")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "sk-fallback")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "http://127.0.0.1:2/v1")
    return lc.LLMClient(provider="minimax", api_key="sk-test",
                        base_url="http://127.0.0.1:1/v1", model="MiniMax-M3")


@pytest.fixture(autouse=True)
def _isolated_transport(monkeypatch):
    lc._CB_STATE.clear()
    lc._CALL_META.meta = None
    for env in ("LLM_FALLBACK_PROVIDER", "LLM_FALLBACK_MODEL", "LLM_FALLBACK_API_KEY",
                "LLM_FALLBACK_BASE_URL", "LLM_FALLBACK_REASONING_EFFORT"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(lc, "_retry_delay", lambda exc, attempt: 0.0)
    monkeypatch.setattr(lc, "_FB_OPENAI_CLIENTS", {})
    monkeypatch.setattr(lc, "_FB_AUTH_UNAVAILABLE_UNTIL", {})
    for name, value in {
        "LLM_TRANSPORT_STRICT": True, "LLM_TIERED_ROUTING": False, "LLM_TELEMETRY_ENABLED": True,
        "LLM_CACHE_ENABLED": True, "LLM_RUN_BUDGET_TOKENS": 0, "LLM_RUN_BUDGET_USD": 0.0,
        "LLM_MINIMAX_DISABLE_THINKING": True, "LLM_KIMI_DISABLE_THINKING": True, **_KNOBS,
    }.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    monkeypatch.setattr(tel.LLMCache, "_store", {})
    monkeypatch.setattr(tel.LLMCache, "_order", [])
    yield
    lc._CB_STATE.clear()
    lc._CALL_META.meta = None


@pytest.fixture
def run_meter():
    """A fresh LLMMeter run bound to the calling context (stage 'report'); yields its id."""
    rid = "run-infra3-escalation"
    tel.LLMMeter.reset(rid)
    tel.set_run_context(rid, stage="report")
    try:
        yield rid
    finally:
        tel.set_run_context(None)
        tel.LLMMeter.reset(rid)


@pytest.fixture
def sleeps(monkeypatch):
    """Every backoff sleep chat() takes (escalation itself must never sleep)."""
    recorded = []
    monkeypatch.setattr(lc.time, "sleep", lambda seconds: recorded.append(seconds))
    return recorded


_MESSAGES = [{"role": "user", "content": "q"}]


# ---------------------------------------------------------------- knobs
def _read(*parts):
    with open(os.path.join(_REPO_ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_knob_defaults_and_env_example_documentation():
    source = _read("backend", "app", "config.py")
    example = _read(".env.example")
    for name, default in _KNOBS.items():
        literal = str(default).lower()
        assert f"os.environ.get('{name}', '{literal}')" in source, name
        match = re.search(rf"^#\s*{name}=(\S+)\s+#\s*\S", example, re.M)
        assert match and match.group(1) == literal, f"{name} missing or wrong default in .env.example"


@pytest.mark.parametrize("escalations, ceiling, expected", [
    ("-3", "0", (0, 32768)),          # out of range: clamped / replaced by the default
    ("abc", "", (2, 32768)),          # unparseable / blank: the code defaults
    ("1", "4096", (1, 4096)),
])
def test_escalation_int_knobs_parse_guarded(monkeypatch, escalations, ceiling, expected):
    import importlib.util

    monkeypatch.setenv("LLM_MAX_ESCALATIONS", escalations)
    monkeypatch.setenv("LLM_MAX_TOKENS_CEILING", ceiling)
    spec = importlib.util.spec_from_file_location(
        "_infra3_config_copy", os.path.join(_REPO_ROOT, "backend", "app", "config.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (module.Config.LLM_MAX_ESCALATIONS, module.Config.LLM_MAX_TOKENS_CEILING) == expected


# ---------------------------------------------------------------- recovery by escalation
def test_empty_length_reply_is_recovered_at_twice_the_cap(run_meter, sleeps):
    script = _Script(_empty_length(90, 512), _resp("answer", "stop", _usage(95, 300)))
    client = _client(script)

    assert client.chat(_MESSAGES, max_tokens=512) == "answer"
    assert script.max_tokens == [512, 1024]
    assert sleeps == [], "an escalation is re-sent at once, without backoff"
    meta = client.last_call_meta()
    assert meta["finish_reason"] == "stop" and meta["served_by"] == "primary"

    snap = tel.LLMMeter.snapshot(run_meter)
    # The rejected attempt is metered with the usage the provider reported for it.
    assert snap["total"]["calls"] == 2
    assert snap["total"]["prompt_tokens"] == 90 + 95
    assert snap["total"]["completion_tokens"] == 512 + 300
    assert snap["by_model"]["minimax:MiniMax-M3"]["calls"] == 2
    assert snap["finish_reasons"] == {"report": {"length": 1, "stop": 1}}
    assert snap["recovery"] == {"length_escalation": {"recovered": 1}}
    assert snap["recovery_by_stage"] == {"length_escalation": {"report": {"recovered": 1}}}
    assert snap["total"]["latency_ms"] >= 0


def test_recovered_reply_is_cached_under_the_original_key_only_when_complete(run_meter):
    script = _Script(_empty_length(), _resp("answer", "stop", _usage(95, 300)))
    client = _client(script)
    assert client.chat(_MESSAGES, max_tokens=512) == "answer"
    # A later identical call (same original max_tokens) is served from the cache.
    assert client.chat(_MESSAGES, max_tokens=512) == "answer"
    assert len(script.calls) == 2
    assert client.last_call_meta()["served_by"] == "cache"

    # finish_reason missing ('unknown') is cacheable for a plain reply, but an escalated
    # reply is replayed only when the provider said it stopped.
    answer = _resp("answer?", None, _usage(95, 300))
    unknown = _Script(_empty_length(), answer, _empty_length(), answer)
    uncached = _client(unknown)
    messages = [{"role": "user", "content": "unknown-finish"}]
    assert uncached.chat(messages, max_tokens=512) == "answer?"
    assert uncached.chat(messages, max_tokens=512) == "answer?"
    assert unknown.max_tokens == [512, 1024, 512, 1024]


def test_escalation_is_clamped_to_the_provider_ceiling(monkeypatch, run_meter):
    monkeypatch.setitem(Config.PROVIDER_META["minimax"], "max_output_tokens", 1536)
    script = _Script(_empty_length())
    with pytest.raises(lc.EmptyCompletion) as ei:
        _client(script).chat(_MESSAGES, max_tokens=512)
    assert script.max_tokens == [512, 1024, 1536]
    assert ei.value.escalation_exhausted is True

    monkeypatch.delitem(Config.PROVIDER_META["minimax"], "max_output_tokens")
    monkeypatch.setattr(Config, "LLM_MAX_TOKENS_CEILING", 1200, raising=False)
    fallback_ceiling = _Script(_empty_length())
    with pytest.raises(lc.EmptyCompletion):
        _client(fallback_ceiling).chat([{"role": "user", "content": "ceiling"}], max_tokens=512)
    assert fallback_ceiling.max_tokens == [512, 1024, 1200]


def test_escalation_is_clamped_to_the_context_window(monkeypatch, run_meter):
    monkeypatch.setitem(Config.PROVIDER_CONTEXT_WINDOWS, "minimax", 4000)
    script = _Script(_empty_length(pt=2000, ct=512))
    with pytest.raises(lc.EmptyCompletion) as ei:
        _client(script).chat(_MESSAGES, max_tokens=512)
    # 4000 - 2000 prompt - 1024 reserve = 976; the next doubling has no headroom left.
    assert script.max_tokens == [512, 976]
    assert ei.value.escalation_exhausted is True


def test_exhausted_escalation_fails_over_once_without_primary_retries(monkeypatch, run_meter, sleeps):
    primary = _Script(_empty_length())
    fallback = _Script(_resp("fallback answer", "stop", _usage(12, 4)))
    client = _with_fallback(monkeypatch, primary, fallback)

    assert client.chat(_MESSAGES, max_tokens=512) == "fallback answer"
    # LLM_MAX_ESCALATIONS=2: the original attempt plus two escalations, then straight to
    # failover (no same-cap backoff retries of the primary).
    assert primary.max_tokens == [512, 1024, 2048]
    assert len(fallback.calls) == 1 and fallback.max_tokens == [512]
    assert sleeps == []
    assert client.last_call_meta()["served_by"] == "fallback"

    snap = tel.LLMMeter.snapshot(run_meter)
    assert snap["recovery"] == {"length_escalation": {"exhausted": 1}}
    assert snap["by_model"]["minimax:MiniMax-M3"]["calls"] == 3
    assert snap["by_model"]["minimax:MiniMax-M3"]["completion_tokens"] == 3 * 512
    assert snap["by_model"]["kimi:kimi-fallback-model"]["calls"] == 1


def test_exhausted_escalation_without_fallback_raises_the_typed_error(run_meter, sleeps):
    script = _Script(_empty_length())
    client = _client(script)
    with pytest.raises(lc.EmptyCompletion) as ei:
        client.chat(_MESSAGES, max_tokens=512)
    assert ei.value.escalation_exhausted is True and ei.value.finish_reason == "length"
    assert script.max_tokens == [512, 1024, 2048]
    assert sleeps == []


def test_zero_escalations_meters_the_attempt_and_fails_over(monkeypatch, run_meter):
    monkeypatch.setattr(Config, "LLM_MAX_ESCALATIONS", 0, raising=False)
    primary = _Script(_empty_length())
    fallback = _Script(_resp("fallback answer"))
    assert _with_fallback(monkeypatch, primary, fallback).chat(_MESSAGES, max_tokens=512) == (
        "fallback answer")
    assert primary.max_tokens == [512] and len(fallback.calls) == 1
    snap = tel.LLMMeter.snapshot(run_meter)
    assert snap["recovery"] == {"length_escalation": {"exhausted": 1}}
    assert snap["by_model"]["minimax:MiniMax-M3"]["calls"] == 1


def test_budget_exceeded_after_a_rejected_attempt_stops_escalation(monkeypatch, run_meter):
    monkeypatch.setattr(Config, "LLM_RUN_BUDGET_TOKENS", 100, raising=False)
    primary = _Script(_empty_length(90, 512), _resp("never sent"))
    fallback = _Script(_resp("fallback answer"))
    client = _with_fallback(monkeypatch, primary, fallback)

    with pytest.raises(tel.BudgetExceeded):
        client.chat(_MESSAGES, max_tokens=512)
    assert primary.max_tokens == [512], "no escalation, no retry"
    assert fallback.calls == [], "a run over budget never fails over"
    snap = tel.LLMMeter.snapshot(run_meter)
    assert snap["total"]["total_tokens"] == 602
    assert "recovery" not in snap


def test_transient_error_mid_escalation_resumes_at_the_escalated_cap(run_meter, sleeps):
    script = _Script(_empty_length(), RuntimeError("connection reset by peer"),
                     _resp("answer", "stop", _usage(95, 300)))
    client = _client(script)
    assert client.chat(_MESSAGES, max_tokens=512) == "answer"
    # The transient error takes chat()'s normal backoff retry, which resumes at 1024
    # (one shared escalation budget per call) instead of starting over at 512.
    assert script.max_tokens == [512, 1024, 1024]
    assert len(sleeps) == 1
    assert tel.LLMMeter.snapshot(run_meter)["recovery"] == {"length_escalation": {"recovered": 1}}


def _bad_request(message="Error code: 400 - max_tokens exceeds the model's output limit"):
    import httpx
    import openai

    request = httpx.Request("POST", "http://127.0.0.1:1/v1/chat/completions")
    return openai.BadRequestError(message, response=httpx.Response(400, request=request), body=None)


def test_refused_escalated_cap_ends_the_ladder_with_the_empty_reply(run_meter, sleeps):
    script = _Script(_empty_length(90, 512), _bad_request())
    with pytest.raises(lc.EmptyCompletion) as ei:
        _client(script).chat(_MESSAGES, max_tokens=512)
    # The 400 answers the raised cap, not the request: the caller sees the typed empty
    # reply (so a report preflight still reads the provider as reachable), with the 400 as cause.
    assert ei.value.escalation_exhausted is True and ei.value.finish_reason == "length"
    assert ei.value.sent_max_tokens == 512
    assert getattr(ei.value.__cause__, "status_code", None) == 400
    assert script.max_tokens == [512, 1024]
    assert sleeps == []
    assert tel.LLMMeter.snapshot(run_meter)["recovery"] == {"length_escalation": {"exhausted": 1}}

    # A 400 on a request that was never escalated is the provider's verdict and stays one.
    import openai

    refused = _Script(_bad_request())
    with pytest.raises(openai.BadRequestError):
        _client(refused).chat([{"role": "user", "content": "plain"}], max_tokens=512)
    assert refused.max_tokens == [512]


def test_fallback_escalation_past_its_output_cap_never_cools_the_fallback_down(
        monkeypatch, run_meter, sleeps):
    primary = _Script(_empty_length(90, 4096))
    fallback = _Script(_empty_length(90, 4096), _empty_length(90, 8192), _bad_request(),
                       _resp("fallback answer", "stop", _usage(12, 4)))
    client = _with_fallback(monkeypatch, primary, fallback)

    with pytest.raises(lc.EmptyCompletion) as ei:
        client.chat(_MESSAGES, max_tokens=4096)
    assert ei.value.provider == "minimax", "the primary's error surfaces when both fail"
    assert fallback.max_tokens == [4096, 8192, 16384]
    # The fallback failed on an escalation artefact, not on its credentials or model name:
    # no process-wide deterministic-failure cooldown.
    assert lc._FB_AUTH_UNAVAILABLE_UNTIL == {}

    # So the next, unrelated call still fails over.
    assert client.chat([{"role": "user", "content": "next"}], max_tokens=4096) == "fallback answer"
    assert len(fallback.calls) == 4
    assert sleeps == []


def test_partial_reply_after_escalation_is_not_counted_as_recovered(run_meter):
    script = _Script(_empty_length(90, 512), _resp("partial {", "length", _usage(95, 1024)))
    client = _client(script)
    assert client.chat(_MESSAGES, max_tokens=512) == "partial {"
    assert client.last_call_meta()["finish_reason"] == "length"
    assert script.max_tokens == [512, 1024]
    snap = tel.LLMMeter.snapshot(run_meter)
    assert snap["recovery"] == {"length_escalation": {"partial": 1}}
    assert snap["recovery_by_stage"] == {"length_escalation": {"report": {"partial": 1}}}


@pytest.mark.parametrize("escalation_on", [True, False])
def test_fallback_over_budget_raises_budget_exceeded(monkeypatch, run_meter, escalation_on):
    monkeypatch.setattr(Config, "LLM_LENGTH_ESCALATION", escalation_on, raising=False)
    monkeypatch.setattr(Config, "LLM_RUN_BUDGET_TOKENS", 100, raising=False)
    primary = _Script(RuntimeError("connection reset by peer"))
    fallback = _Script(_resp("fallback answer", "stop", _usage(90, 512)))
    client = _with_fallback(monkeypatch, primary, fallback)

    if escalation_on:
        with pytest.raises(tel.BudgetExceeded):
            client.chat(_MESSAGES, max_tokens=512)
    else:
        # Legacy: the fallback's BudgetExceeded is swallowed and the primary's error raised.
        with pytest.raises(RuntimeError, match="connection reset") as ei:
            client.chat(_MESSAGES, max_tokens=512)
        assert not isinstance(ei.value, tel.BudgetExceeded)
    assert len(primary.calls) == lc.MAX_RETRIES and len(fallback.calls) == 1


def test_fallback_rejected_escalation_over_budget_raises_budget_exceeded(monkeypatch, run_meter):
    monkeypatch.setattr(Config, "LLM_RUN_BUDGET_TOKENS", 100, raising=False)
    primary = _Script(RuntimeError("connection reset by peer"))
    fallback = _Script(_empty_length(90, 512), _resp("never sent"))
    client = _with_fallback(monkeypatch, primary, fallback)
    with pytest.raises(tel.BudgetExceeded):
        client.chat(_MESSAGES, max_tokens=512)
    assert fallback.max_tokens == [512], "the rejected attempt is metered, then the budget stops it"


def test_non_length_empty_reply_is_not_escalated(run_meter):
    script = _Script(_resp(content="", finish="stop", usage=_usage(40, 0)))
    with pytest.raises(lc.EmptyCompletion) as ei:
        _client(script).chat(_MESSAGES, max_tokens=512)
    assert ei.value.finish_reason == "stop"
    assert not getattr(ei.value, "escalation_exhausted", False)
    # Legacy handling: MAX_RETRIES backoff retries at the same cap, nothing metered.
    assert script.max_tokens == [512] * lc.MAX_RETRIES
    snap = tel.LLMMeter.snapshot(run_meter)
    assert snap["total"]["calls"] == 0 and "recovery" not in snap


def test_escalation_off_keeps_the_legacy_retry_and_failover_path(monkeypatch, run_meter, sleeps):
    monkeypatch.setattr(Config, "LLM_LENGTH_ESCALATION", False, raising=False)
    primary = _Script(_empty_length())
    fallback = _Script(_resp("fallback answer", "stop", _usage(12, 4)))
    client = _with_fallback(monkeypatch, primary, fallback)
    seen = []
    real_try_fallback = lc.LLMClient._try_fallback
    monkeypatch.setattr(lc.LLMClient, "_try_fallback",
                        lambda self, *args: seen.append(args[-1]) or real_try_fallback(self, *args))

    assert client.chat(_MESSAGES, max_tokens=512) == "fallback answer"
    # No escalation: the EmptyCompletion takes the legacy same-cap retries into failover.
    assert primary.max_tokens == [512] * lc.MAX_RETRIES
    assert len(sleeps) == lc.MAX_RETRIES - 1
    assert len(seen) == 1 and isinstance(seen[0], lc.EmptyCompletion)
    assert not hasattr(seen[0], "escalation_exhausted")
    snap = tel.LLMMeter.snapshot(run_meter)
    assert "minimax:MiniMax-M3" not in snap["by_model"], "legacy: failed attempts unmetered"
    assert "recovery" not in snap


def test_escalation_off_is_exactly_one_transport_call(monkeypatch):
    monkeypatch.setattr(Config, "LLM_LENGTH_ESCALATION", False, raising=False)
    script = _Script(_empty_length())
    client = _client(script)
    with pytest.raises(lc.EmptyCompletion):
        client._chat_openai_escalating(_MESSAGES, 0.2, 512)
    assert script.max_tokens == [512]


def test_plain_replies_are_unchanged_with_escalation_on(run_meter):
    script = _Script(_resp("answer", "stop", _usage(10, 5)))
    client = _client(script)
    assert client.chat(_MESSAGES, max_tokens=512) == "answer"
    assert script.max_tokens == [512]
    snap = tel.LLMMeter.snapshot(run_meter)
    assert snap["total"]["calls"] == 1 and "recovery" not in snap


def test_record_recovery_rejects_unknown_outcomes_silently():
    rid = "run-infra3-recovery-unknown"
    try:
        tel.LLMMeter.record_recovery("length_escalation", "bogus", run_id=rid)
        tel.LLMMeter.record_recovery("length_escalation", "exhausted", run_id=rid, stage="graph")
        tel.LLMMeter.record_recovery("length_escalation", "exhausted", run_id=rid, stage="report")
        snap = tel.LLMMeter.snapshot(rid)
    finally:
        tel.LLMMeter.reset(rid)
    assert snap["recovery"] == {"length_escalation": {"exhausted": 2}}
    assert snap["recovery_by_stage"] == {
        "length_escalation": {"graph": {"exhausted": 1}, "report": {"exhausted": 1}}}


# ---------------------------------------------------------------- report preflight
def _preflight_run(monkeypatch, tmp_path, error):
    from tests.test_orchestrator_research_wiring import _exercise_prepare_run_resume

    # corrupt_run: RUN is recomputed, so the report is regenerated and the preflight probes.
    return _exercise_prepare_run_resume(
        monkeypatch, tmp_path, rebuild_prepare=False, corrupt_run=True,
        report_preflight_failures=1, report_preflight_error=error)


def test_report_preflight_passes_on_an_empty_length_reply(monkeypatch, tmp_path):
    from app.services import pipeline_orchestrator as po

    error = lc.EmptyCompletion("LLM returned empty content (finish_reason=length, provider=glm).",
                               finish_reason="length", raw_finish_reason="length",
                               sent_max_tokens=64, provider="glm")
    records = []
    handler = logging.Handler(level=logging.INFO)
    handler.emit = records.append
    po.logger.addHandler(handler)
    try:
        result = _preflight_run(monkeypatch, tmp_path, error)
    finally:
        po.logger.removeHandler(handler)
    assert result.state.status == "completed", result.state.error
    assert result.report_generations == [result.old_id]
    assert result.state.report_id not in (None, "report_existing")
    assert any("报告前置探测：提供方可达" in record.getMessage() for record in records)


def test_report_preflight_still_fails_on_other_empty_replies(monkeypatch, tmp_path):
    error = lc.EmptyCompletion("LLM returned empty content (finish_reason=stop, provider=glm).",
                               finish_reason="stop", raw_finish_reason="stop",
                               sent_max_tokens=64, provider="glm")
    result = _preflight_run(monkeypatch, tmp_path, error)
    assert result.state.status == "failed"
    assert "报告前置探测失败" in result.state.error
    assert result.report_generations == []


# ---------------------------------------------------------------- forecast fail-closed
class _MetaLLM(FakeLLMClient):
    """FakeLLMClient whose chat_json replies each come with scripted call metadata.

    ``replies`` is a list of (json reply, meta) pairs served in order; ``last_call_meta`` is a
    method, like LLMClient.last_call_meta (INFRA-1), returning the last served meta.
    """

    def __init__(self, replies):
        super().__init__()
        self._replies = list(replies)
        self._meta = None

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, tier=None, **kwargs):
        super().chat_json(messages, temperature=temperature, max_tokens=max_tokens, tier=tier,
                          **kwargs)
        reply, self._meta = self._replies.pop(0) if self._replies else ({}, None)
        return reply

    def last_call_meta(self):
        return None if self._meta is None else dict(self._meta)


_STOP = {"finish_reason": "stop"}
_CUT = {"finish_reason": "length"}
_REPAIRED = {"finish_reason": "stop", "json_truncation_repaired": True}
_NAMES = ("Rapid adoption path", "Gradual adoption path", "Other / Status Quo")


def _rows(probs):
    return [
        {"name": name, "probability": p, "summary": f"{name} summary", "key_drivers": ["driver"],
         "resolution_criteria": f"{name} resolves if the index is above {10 + i}% by 2030"}
        for i, (name, p) in enumerate(zip(_NAMES, probs, strict=True))
    ]


def _spine(probs):
    return {"headline": "h", "horizon": "2030", "confidence": "medium", "scenarios": _rows(probs)}


def _probs(forecast):
    return [row["probability"] for row in forecast["scenarios"]]


def _forecast(probs=(0.5, 0.3, 0.2)):
    return {"headline": "Adoption outlook", "horizon": "2030", "confidence": "medium",
            "confidence_rationale": "Evidence is mixed.", "key_uncertainties": ["policy"],
            "scenarios": _rows(list(probs)), "schema_version": 1}


@pytest.fixture
def spine_config(monkeypatch):
    for name, value in {"FORECAST_PROB_STRICT_PARSE": True, "REPORT_SPINE_SELFCONSISTENCY_K": 1,
                        "FORECAST_PROB_FLOOR": 0.0}.items():
        monkeypatch.setattr(Config, name, value, raising=False)


def test_reply_truncated_reads_method_dict_and_missing_metadata():
    assert fe._reply_truncated(_MetaLLM([])) is False              # no call yet: meta None
    llm = _MetaLLM([({}, _CUT), ({}, _REPAIRED), ({}, _STOP)])
    for expected in (True, True, False):
        llm.chat_json([{"role": "user", "content": "x"}])
        assert fe._reply_truncated(llm) is expected
    assert fe._reply_truncated(FakeLLMClient()) is False          # last_call_meta() -> None
    assert fe._reply_truncated(object()) is False                 # no last_call_meta at all
    assert fe._reply_truncated(SimpleNamespace(last_call_meta=dict(_CUT))) is True

    def broken():
        raise RuntimeError("meta unavailable")
    assert fe._reply_truncated(SimpleNamespace(last_call_meta=broken)) is False


def test_truncated_spine_draw_is_discarded_and_retried(spine_config):
    llm = _MetaLLM([(_spine([0.6, 0.3, 0.1]), _CUT), (_spine([0.5, 0.3, 0.2]), _STOP)])
    out = fe.derive_forecast_spine(llm, central_question="Will adoption accelerate?")
    assert _probs(out) == [0.5, 0.3, 0.2]
    assert out["quality"]["llm_truncation"] == {"spine_draws_discarded": 1}
    assert "_llm_truncated" not in out
    assert len(llm.calls) == 2
    assert llm.calls[1]["messages"][0]["content"].endswith(fe._SPINE_RETRY_NOTE)


def test_truncated_self_consistency_draw_is_never_pooled(spine_config, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 2, raising=False)
    llm = _MetaLLM([(_spine([0.5, 0.3, 0.2]), _STOP), (_spine([0.1, 0.1, 0.8]), _REPAIRED)])
    out = fe.derive_forecast_spine(llm, central_question="Will adoption accelerate?")
    assert _probs(out) == [0.5, 0.3, 0.2]
    assert "self_consistency_k" not in out
    assert out["quality"]["llm_truncation"] == {"spine_draws_discarded": 1}


def test_all_spine_draws_truncated_is_a_failed_spine(spine_config):
    llm = _MetaLLM([(_spine([0.6, 0.3, 0.1]), _CUT), (_spine([0.5, 0.3, 0.2]), _CUT)])
    out = fe.derive_forecast_spine(llm, central_question="Will adoption accelerate?")
    assert out["scenarios"] == [] and out["derived_from"] == "spine"
    assert out["quality"]["llm_truncation"] == {"spine_draws_discarded": 2}


def test_spine_fail_closed_off_keeps_the_truncated_draw(spine_config, monkeypatch):
    monkeypatch.setattr(Config, "LLM_JSON_TRUNCATION_FAIL_CLOSED", False, raising=False)
    cut = _MetaLLM([(_spine([0.6, 0.3, 0.1]), _CUT)])
    legacy = FakeLLMClient(json_responses=[_spine([0.6, 0.3, 0.1])])
    out = fe.derive_forecast_spine(cut, central_question="Q?")
    assert out == fe.derive_forecast_spine(legacy, central_question="Q?")
    assert _probs(out) == [0.6, 0.3, 0.1] and "quality" not in out
    assert len(cut.calls) == 1


def test_spine_draw_of_a_real_client_with_a_length_cut_reply(spine_config):
    """A real LLMClient on a stubbed transport: the cut first reply is bracket-repaired by
    chat_json (finish_reason length), discarded, and the complete retry is used."""
    cut = '{"headline": "h", "scenarios": [{"name": "Rapid adoption path", "probability": 0.9'
    complete = json.dumps(_spine([0.5, 0.3, 0.2]))
    script = _Script(_resp(cut, "length", _usage(50, 6144)), _resp(complete, "stop", _usage(52, 900)))
    client = _client(script)
    out = fe.derive_forecast_spine(client, central_question="Will adoption accelerate?")
    assert _probs(out) == [0.5, 0.3, 0.2]
    assert out["quality"]["llm_truncation"] == {"spine_draws_discarded": 1}
    assert len(script.calls) == 2


def _binary(bid, stmt, prob):
    return {"id": bid, "statement": stmt, "probability": prob,
            "resolution_criteria": f"metric > 10% by 2027 ({bid})", "theme": "t1",
            "horizon_year": 2027}


_BINARIES = {"binary_forecasts": [
    _binary("F1", "Alpha exceeds 10% by 2027", 0.2),
    _binary("F2", "Beta exceeds 500 units by 2027", 0.8),
    _binary("F3", "Gamma exceeds 40 plants by 2027", 0.5),
]}


def test_truncated_binary_draw_drops_its_last_item(monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_MODELS", "", raising=False)
    llm = _MetaLLM([(_BINARIES, _CUT)])
    out = fe.extract_binary_forecasts("dossier", llm, min_count=2, language="English")
    statements = [row["statement"] for row in out["binary_forecasts"]]
    assert statements == ["Alpha exceeds 10% by 2027", "Beta exceeds 500 units by 2027"]
    assert out["binary_quality"]["llm_truncation_trimmed"] is True
    assert out["binary_quality"]["llm_truncation_trimmed_draws"] == 1
    assert len([c for c in llm.calls if c["kind"] == "chat_json"]) == 1


def test_binary_fail_closed_off_keeps_every_item(monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_MODELS", "", raising=False)
    monkeypatch.setattr(Config, "LLM_JSON_TRUNCATION_FAIL_CLOSED", False, raising=False)
    out = fe.extract_binary_forecasts("dossier", _MetaLLM([(_BINARIES, _CUT)]), min_count=2,
                                      language="English")
    legacy = fe.extract_binary_forecasts("dossier", FakeLLMClient(json_responses=[_BINARIES]),
                                         min_count=2, language="English")
    assert out == legacy
    assert len(out["binary_forecasts"]) == 3
    assert "llm_truncation_trimmed" not in out["binary_quality"]


def test_complete_binary_draw_is_untouched(monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_MODELS", "", raising=False)
    out = fe.extract_binary_forecasts("dossier", _MetaLLM([(_BINARIES, _STOP)]), min_count=2,
                                      language="English")
    legacy = fe.extract_binary_forecasts("dossier", FakeLLMClient(json_responses=[_BINARIES]),
                                         min_count=2, language="English")
    assert out == legacy and len(out["binary_forecasts"]) == 3


def test_truncated_critique_returns_the_input_uncritiqued(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_CRITIQUE_SINGLE_PASS", True, raising=False)
    critique = {"scenarios": _rows([0.45, 0.3, 0.25]), "confidence": "low"}
    forecast = _forecast()
    before = [dict(row) for row in forecast["scenarios"]]

    out = fe.self_critique_forecast(forecast, _MetaLLM([(critique, _CUT)]))
    assert out is forecast
    assert "critiqued" not in out and out["scenarios"] == before
    assert out["critique_attempted"] is True        # INFRA-2 single-pass stamp still applies

    monkeypatch.setattr(Config, "LLM_JSON_TRUNCATION_FAIL_CLOSED", False, raising=False)
    legacy = fe.self_critique_forecast(_forecast(), _MetaLLM([(critique, _CUT)]))
    assert legacy["critiqued"] is True and legacy["confidence"] == "low"


def test_truncated_premortem_returns_the_input_unchanged(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_PREMORTEM", True, raising=False)
    reply = {"missed_signals": ["grid delays"], "overconfident_scenario": _NAMES[0],
             "underweighted_scenario": _NAMES[2]}
    forecast = _forecast()
    assert fe.premortem_forecast(forecast, _MetaLLM([(reply, _REPAIRED)])) is forecast
    assert "premortem" not in forecast

    monkeypatch.setattr(Config, "LLM_JSON_TRUNCATION_FAIL_CLOSED", False, raising=False)
    legacy = fe.premortem_forecast(_forecast(), _MetaLLM([(reply, _REPAIRED)]))
    assert legacy["premortem"]["missed_signals"] == ["grid delays"]
    assert _probs(legacy) != [0.5, 0.3, 0.2]


def test_truncated_post_hoc_extraction_is_flagged_not_silent(monkeypatch):
    reply = _spine([0.5, 0.3, 0.2])
    out = fe.extract_structured_forecast("report", _MetaLLM([(reply, _CUT)]))
    assert _probs(out) == [0.5, 0.3, 0.2]
    assert out["quality"]["llm_truncation"] == {"posthoc_reply_truncated": True}

    monkeypatch.setattr(Config, "LLM_JSON_TRUNCATION_FAIL_CLOSED", False, raising=False)
    legacy = fe.extract_structured_forecast("report", _MetaLLM([(reply, _CUT)]))
    assert legacy == fe.extract_structured_forecast("report", FakeLLMClient(json_responses=[reply]))
    assert "llm_truncation" not in (legacy.get("quality") or {})


# ---------------------------------------------------------------- market passes fail closed
_MARKETS = [
    {"market_id": "mkt-a", "question": "Will Alpha exceed 10% by 2027?", "implied_yes_prob": 0.6,
     "end_date": "2099-12-31"},
    {"market_id": "mkt-b", "question": "Will Beta exceed 500 units by 2027?",
     "implied_yes_prob": 0.3, "end_date": "2099-12-31"},
]
_MATCHES = {"matches": [
    {"forecast_id": "F1", "market_id": "mkt-a", "resolution_equivalence": "exact", "confidence": 0.9},
    {"forecast_id": "F2", "market_id": "mkt-b", "resolution_equivalence": "exact", "confidence": 0.9},
]}
_MARKET_RATIONALE = "The market implies {pct}; I move toward it but keep the base-rate view."


def _market_binaries():
    return [dict(_binary("F1", "Alpha exceeds 10% by 2027", 0.2), adjustment_rationale="base rate"),
            dict(_binary("F2", "Beta exceeds 500 units by 2027", 0.8),
                 adjustment_rationale="base rate")]


def _anchored_binaries():
    binaries = _market_binaries()
    assert fe.anchor_binaries_to_markets(binaries, _MARKETS, _MetaLLM([(_MATCHES, _STOP)])) == 2
    return binaries


# The cut lands inside F2's rationale: its probability is complete and the fragment already
# names the market, so without the fail-closed drop it would pass every check below.
_REVISIONS = {"revisions": [
    {"id": "F1", "probability": 0.45, "adjustment_rationale": _MARKET_RATIONALE.format(pct="60%")},
    {"id": "F2", "probability": 0.55, "adjustment_rationale": "The market implies 30%; I mo"},
]}


def test_truncated_market_match_reply_drops_its_last_match(monkeypatch):
    binaries, counts = _market_binaries(), {}
    anchored = fe.anchor_binaries_to_markets(binaries, _MARKETS, _MetaLLM([(_MATCHES, _CUT)]),
                                             truncation_counts=counts)
    assert anchored == 1
    assert binaries[0]["market_anchor"]["market_id"] == "mkt-a"
    assert "market_anchor" not in binaries[1]
    assert counts == {"market_match": 1}

    complete, counts = _market_binaries(), {}
    assert fe.anchor_binaries_to_markets(complete, _MARKETS, _MetaLLM([(_MATCHES, _STOP)]),
                                         truncation_counts=counts) == 2
    assert counts == {}

    monkeypatch.setattr(Config, "LLM_JSON_TRUNCATION_FAIL_CLOSED", False, raising=False)
    legacy, counts = _market_binaries(), {}
    assert fe.anchor_binaries_to_markets(legacy, _MARKETS, _MetaLLM([(_MATCHES, _CUT)]),
                                         truncation_counts=counts) == 2
    assert legacy == complete and counts == {}


def test_truncated_divergence_revision_never_moves_the_cut_item(monkeypatch):
    binaries, counts = _anchored_binaries(), {}
    revised = fe.enforce_market_divergence(binaries, _MetaLLM([(_REVISIONS, _REPAIRED)]),
                                           truncation_counts=counts)
    assert revised == 1
    assert binaries[0]["probability"] == 0.45 and "market_influence" in binaries[0]
    # The cut revision is dropped: probability, rationale and influence stamp stay untouched.
    assert binaries[1]["probability"] == 0.8
    assert binaries[1]["adjustment_rationale"] == "base rate"
    assert "market_influence" not in binaries[1]
    assert counts == {"market_divergence": 1}

    monkeypatch.setattr(Config, "LLM_JSON_TRUNCATION_FAIL_CLOSED", False, raising=False)
    legacy = _anchored_binaries()
    assert fe.enforce_market_divergence(legacy, _MetaLLM([(_REVISIONS, _REPAIRED)])) == 2
    assert legacy[1]["probability"] == 0.55
    assert legacy[1]["adjustment_rationale"] == "The market implies 30%; I mo"


def test_market_truncation_is_recorded_in_binary_quality(monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_MODELS", "", raising=False)
    llm = _MetaLLM([(_BINARIES, _STOP), (_MATCHES, _CUT), (_REVISIONS, _CUT)])
    out = fe.extract_binary_forecasts("dossier", llm, min_count=2, language="English",
                                      markets=_MARKETS)
    by_id = {row["id"]: row for row in out["binary_forecasts"]}
    assert by_id["F1"]["market_anchor"]["market_id"] == "mkt-a"
    assert "market_anchor" not in by_id["F2"]
    assert out["binary_quality"]["llm_truncation_market_trimmed"] == {
        "market_match": 1, "market_divergence": 1}
    assert "llm_truncation_trimmed" not in out["binary_quality"]

    monkeypatch.setattr(Config, "LLM_JSON_TRUNCATION_FAIL_CLOSED", False, raising=False)
    legacy = fe.extract_binary_forecasts(
        "dossier", _MetaLLM([(_BINARIES, _STOP), (_MATCHES, _CUT), (_REVISIONS, _CUT)]),
        min_count=2, language="English", markets=_MARKETS)
    assert "llm_truncation_market_trimmed" not in legacy["binary_quality"]


# ---------------------------------------------------------------- truncation bookkeeping
def test_llm_truncation_never_reaches_the_critic():
    forecast = dict(_forecast(), quality={"llm_truncation": {"spine_draws_discarded": 1}})
    assert "quality" not in fe._llm_forecast_view(forecast)
    kept = dict(_forecast(), quality={"llm_truncation": {"spine_draws_discarded": 1},
                                      "grounding": 0.9})
    assert fe._llm_forecast_view(kept)["quality"] == {"grounding": 0.9}

    llm = _MetaLLM([({"scenarios": _rows([0.45, 0.3, 0.25])}, _STOP)])
    fe.self_critique_forecast(forecast, llm)
    prompt = llm.calls[0]["messages"][-1]["content"]
    assert "llm_truncation" not in prompt and "spine_draws_discarded" not in prompt


@pytest.fixture
def report_env(monkeypatch, tmp_path, spine_config):
    from app.services.report_agent import ReportManager

    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    for name, value in {"FORECAST_LEDGER_DIR": str(tmp_path / "ledger"),
                        "REPORT_PUBLISH_GATE": False, "REPORT_REPAIR_PASSES": False,
                        "REPORT_FORECAST_SELF_CRITIQUE": False,
                        "REPORT_CRITIQUE_BEFORE_PROSE": False, "REPORT_FORECAST_LEDGER": False,
                        "FORECAST_EMIT_BINARY": False}.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    return tmp_path


def test_spine_lost_to_truncation_is_recorded_in_the_post_hoc_forecast(report_env):
    from tests.test_forecast_needs_review import _agent

    llm = _MetaLLM([(_spine([0.6, 0.3, 0.1]), _CUT), (_spine([0.6, 0.3, 0.1]), _CUT),
                    (_spine([0.5, 0.3, 0.2]), _CUT)])
    agent = _agent(llm=llm)
    agent._derive_and_pin_forecast_spine("report_cut")
    assert agent._forecast_spine is None
    assert agent._spine_llm_truncation == {"spine_draws_discarded": 2}

    agent._finalize_structured_forecast("report_cut", "# T\n\nBody text.")
    path = os.path.join(str(report_env), "reports", "report_cut", "forecast.json")
    with open(path, encoding="utf-8") as fh:
        forecast = json.load(fh)
    assert _probs(forecast) == [0.5, 0.3, 0.2]
    assert forecast["quality"]["llm_truncation"] == {
        "posthoc_reply_truncated": True, "spine_draws_discarded": 2}


def test_spine_that_survives_truncation_carries_its_own_count(report_env):
    from tests.test_forecast_needs_review import _agent

    agent = _agent(llm=_MetaLLM([(_spine([0.6, 0.3, 0.1]), _CUT), (_spine([0.5, 0.3, 0.2]), _STOP)]))
    agent._derive_and_pin_forecast_spine("report_kept")
    assert _probs(agent._forecast_spine) == [0.5, 0.3, 0.2]
    assert agent._forecast_spine["quality"]["llm_truncation"] == {"spine_draws_discarded": 1}
    assert agent._spine_llm_truncation is None
