"""Offline tests for INFRA-2: the chat_json structured-output repair turn in app/utils/llm_client.py.

Covers LLM_JSON_REPAIR_TURN (default on): a reply that is not one JSON object (unparseable, or
a list / scalar) is dropped from LLMCache and re-asked once at the SAME temperature with the bad
reply and a repair note appended; a second miss raises ValueError naming both reasons; locally
repaired truncations are accepted and flagged in last_call_meta(); every outcome is counted in
LLMMeter's structured_outputs. Also pins the flag-off legacy path (blind retry at temperature-0.2,
non-dict values returned), the byte-identical first-try-valid request, the fallback-key discard,
the use_cache=False opt-out (EVAL-10) and the never-raise guarantees. Review round 1: a JSON null
reply is named 'not a JSON object', an empty reply is echoed as a placeholder, and a transport
failure in the repair turn is still counted 'failed'. Every OpenAI response is a SimpleNamespace
fed through a fake client: no network, no real LLM.
"""

import os
from types import SimpleNamespace

import pytest

from app.config import Config
from app.utils import llm_client as lc
from app.utils import telemetry as tel

PRIMARY = "minimax"
PRIMARY_MODEL = "MiniMax-M3"
RUN_ID = "infra2-json-run"
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_JSON_FORMAT = {"type": "json_object"}


# ---------------------------------------------------------------- fakes / fixtures
def _resp(content, finish="stop"):
    message = SimpleNamespace(content=content, tool_calls=[])
    choice = SimpleNamespace(message=message, finish_reason=finish)
    return SimpleNamespace(choices=[choice], usage=None)


class _Transport:
    """A fake OpenAI client: serves scripted responses (the last one repeats), records kwargs."""

    def __init__(self, *responses):
        self.responses = list(responses) or [_resp("{}")]
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def script(self, *contents):
        self.responses = [c if isinstance(c, SimpleNamespace) else _resp(c) for c in contents]

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses[min(len(self.calls), len(self.responses)) - 1]


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
    monkeypatch.setattr(Config, "LLM_JSON_REPAIR_TURN", True, raising=False)
    monkeypatch.setattr(Config, "LLM_RUN_BUDGET_TOKENS", 0, raising=False)
    monkeypatch.setattr(Config, "LLM_RUN_BUDGET_USD", 0.0, raising=False)
    monkeypatch.setattr(Config, "LLM_TIERED_ROUTING", False, raising=False)
    monkeypatch.setattr(tel.LLMCache, "_store", {})
    monkeypatch.setattr(tel.LLMCache, "_order", [])
    lc._CB_STATE.clear()
    lc._CALL_META.meta = None
    tel.LLMMeter.reset(RUN_ID)
    tel.set_run_context(RUN_ID, "graph")
    yield
    tel.set_run_context(None)
    tel.LLMMeter.reset(RUN_ID)
    lc._CB_STATE.clear()
    lc._CALL_META.meta = None


def _client(**kwargs):
    return lc.LLMClient(provider=PRIMARY, **kwargs)


def _msgs(tag):
    return [{"role": "system", "content": "Return JSON."}, {"role": "user", "content": f"infra2-{tag}"}]


def _key(messages, temperature, provider=PRIMARY, model=PRIMARY_MODEL, max_tokens=4096):
    return tel.LLMCache.key(provider, model, messages, temperature, max_tokens, _JSON_FORMAT)


def _structured(label="chat_json"):
    return tel.LLMMeter.snapshot(RUN_ID).get("structured_outputs", {}).get(label)


def _structured_by_stage(label="chat_json"):
    return tel.LLMMeter.snapshot(RUN_ID).get("structured_outputs_by_stage", {}).get(label)


def _repair_note(reason):
    return lc._JSON_REPAIR_NOTE.format(reason=reason)


# ---------------------------------------------------------------- repair turn
def test_list_reply_gets_a_repair_turn_at_the_same_temperature(transports):
    client = _client()
    transports[PRIMARY].script("[1,2]", '{"a":1}')
    messages = _msgs("list")

    assert client.chat_json(messages, temperature=0.4) == {"a": 1}

    first, second = transports[PRIMARY].calls
    assert first["messages"] == messages
    assert second["messages"] == messages + [
        {"role": "assistant", "content": "[1,2]"},
        {"role": "user", "content": _repair_note("not a JSON object")},
    ]
    assert first["temperature"] == second["temperature"] == 0.4
    assert first["response_format"] == second["response_format"] == _JSON_FORMAT
    assert _structured() == {"ok": 0, "repaired": 1, "failed": 0, "truncation_repaired": 0}
    assert _structured_by_stage() == {"graph": {"ok": 0, "repaired": 1, "failed": 0,
                                                "truncation_repaired": 0}}


def test_repair_note_names_invalid_json_and_caps_the_echoed_reply(transports):
    client = _client()
    bad = "not json at all " * 400
    transports[PRIMARY].script(bad, '{"ok": true}')

    assert client.chat_json(_msgs("invalid")) == {"ok": True}

    echoed, note = transports[PRIMARY].calls[1]["messages"][-2:]
    assert echoed == {"role": "assistant", "content": bad.strip()[:4000]}
    assert note == {"role": "user", "content": _repair_note("invalid JSON")}


@pytest.mark.parametrize("allow_non_dict", [False, True])
def test_json_null_reply_is_a_miss_named_not_an_object(transports, allow_non_dict):
    """JSON null parses, so the note must not claim the reply was invalid JSON; chat_json
    never returns None, not even for an allow_non_dict caller."""
    client = _client()
    transports[PRIMARY].script(" null ", '{"a": 1}')

    assert client.chat_json(_msgs(f"null-{allow_non_dict}"), allow_non_dict=allow_non_dict) == {"a": 1}

    echoed, note = transports[PRIMARY].calls[1]["messages"][-2:]
    assert echoed == {"role": "assistant", "content": "null"}
    assert note == {"role": "user", "content": _repair_note("not a JSON object")}
    assert _structured()["repaired"] == 1


def test_two_null_replies_name_not_an_object_in_the_value_error(transports):
    client = _client()
    transports[PRIMARY].script("null", "garbage")

    with pytest.raises(ValueError) as excinfo:
        client.chat_json(_msgs("null-twice"))
    assert "首轮: not a JSON object; 修复轮: invalid JSON" in str(excinfo.value)


def test_empty_reply_is_echoed_as_a_placeholder_in_non_strict_transport(transports, monkeypatch):
    """LLM_TRANSPORT_STRICT=false: a think-only reply passes chat()'s legacy raw-text empty
    check and is cleaned to ''. The repair turn must not send an empty assistant message
    (MiniMax answers that with a 400)."""
    monkeypatch.setattr(Config, "LLM_TRANSPORT_STRICT", False, raising=False)
    client = _client()
    transports[PRIMARY].script("<think>only reasoning, no answer</think>", '{"a": 1}')

    assert client.chat_json(_msgs("think-only")) == {"a": 1}

    echoed, note = transports[PRIMARY].calls[1]["messages"][-2:]
    assert echoed == {"role": "assistant", "content": lc._JSON_REPAIR_EMPTY_REPLY}
    assert echoed["content"].strip()
    assert note == {"role": "user", "content": _repair_note("invalid JSON")}


class _TransportDown(RuntimeError):
    pass


def _fail_on_call(monkeypatch, client, failing_call):
    """Make client.chat raise _TransportDown on its ``failing_call``-th call (1-based)."""
    real_chat = client.chat
    calls = []

    def chat(**kwargs):
        calls.append(kwargs)
        if len(calls) == failing_call:
            raise _TransportDown("provider down")
        return real_chat(**kwargs)

    monkeypatch.setattr(client, "chat", chat)
    return calls


def test_repair_turn_transport_failure_propagates_and_is_counted_failed(transports, monkeypatch):
    client = _client()
    transports[PRIMARY].script("[1]")
    calls = _fail_on_call(monkeypatch, client, 2)
    messages = _msgs("repair-transport")

    with pytest.raises(_TransportDown, match="provider down"):
        client.chat_json(messages, temperature=0.0)

    assert len(calls) == 2 and len(transports[PRIMARY].calls) == 1
    assert tel.LLMCache.get(_key(messages, 0.0)) is None  # the missed attempt 1 was still discarded
    assert _structured() == {"ok": 0, "repaired": 0, "failed": 1, "truncation_repaired": 0}


def test_first_attempt_transport_failure_records_no_structured_outcome(transports, monkeypatch):
    client = _client()
    _fail_on_call(monkeypatch, client, 1)

    with pytest.raises(_TransportDown):
        client.chat_json(_msgs("first-transport"))
    assert "structured_outputs" not in tel.LLMMeter.snapshot(RUN_ID)


def test_temperature_zero_miss_gets_a_fresh_completion_and_is_never_replayed(transports):
    client = _client()
    transports[PRIMARY].script("[]", '{"entities": []}')
    messages = _msgs("temp0")

    assert client.chat_json(messages, temperature=0.0) == {"entities": []}
    assert len(transports[PRIMARY].calls) == 2
    assert tel.LLMCache.get(_key(messages, 0.0)) is None  # the bad attempt is gone

    # The graphiti adapter resends identical arguments: attempt 1 is a real call again.
    transports[PRIMARY].script('{"entities": [1]}')
    assert client.chat_json(messages, temperature=0.0) == {"entities": [1]}
    assert len(transports[PRIMARY].calls) == 3
    assert tel.LLMCache.get(_key(messages, 0.0)) == '{"entities": [1]}'


def test_two_misses_raise_value_error_and_leave_no_cache_entry(transports):
    client = _client()
    transports[PRIMARY].script('"just a string"', "still not json")
    messages = _msgs("two-miss")

    with pytest.raises(ValueError) as excinfo:
        client.chat_json(messages, temperature=0.0)

    text = str(excinfo.value)
    assert "LLM返回的JSON格式无效" in text
    assert "not a JSON object" in text and "invalid JSON" in text
    repair_messages = transports[PRIMARY].calls[1]["messages"]
    assert tel.LLMCache.get(_key(messages, 0.0)) is None
    assert tel.LLMCache.get(_key(repair_messages, 0.0)) is None
    assert tel.LLMCache._store == {} and tel.LLMCache._order == []
    assert _structured()["failed"] == 1


def test_truncated_reply_is_repaired_locally_and_flagged(transports):
    client = _client()
    transports[PRIMARY].script('{"a": [1, 2')

    assert client.chat_json(_msgs("truncated")) == {"a": [1, 2]}

    assert len(transports[PRIMARY].calls) == 1
    assert client.last_call_meta()["json_truncation_repaired"] is True
    counts = _structured()
    assert counts["ok"] == 1 and counts["truncation_repaired"] == 1


def test_first_try_valid_object_sends_the_legacy_request(transports, monkeypatch):
    messages = _msgs("valid")
    reply = '{"sections": [{"title": "t"}]}'

    requests, results, metas = [], [], []
    for flag in (True, False):
        monkeypatch.setattr(Config, "LLM_JSON_REPAIR_TURN", flag, raising=False)
        monkeypatch.setattr(tel.LLMCache, "_store", {})
        monkeypatch.setattr(tel.LLMCache, "_order", [])
        client = _client()
        transports[PRIMARY].calls.clear()
        transports[PRIMARY].script(reply)
        results.append(client.chat_json(messages, temperature=0.3, max_tokens=1024, tier="fast"))
        requests.append(list(transports[PRIMARY].calls))
        metas.append(client.last_call_meta())

    assert requests[0] == requests[1] and len(requests[0]) == 1
    assert results[0] == results[1] == {"sections": [{"title": "t"}]}
    assert "json_truncation_repaired" not in metas[0]
    assert metas[0].keys() == metas[1].keys()


def test_flag_off_reproduces_the_legacy_temperature_retry(transports, monkeypatch):
    monkeypatch.setattr(Config, "LLM_JSON_REPAIR_TURN", False, raising=False)
    client = _client()
    transports[PRIMARY].script("garbage", '{"a": 1}')
    messages = _msgs("legacy")

    assert client.chat_json(messages, temperature=0.5) == {"a": 1}
    first, second = transports[PRIMARY].calls
    assert first["messages"] == second["messages"] == messages  # blind identical resend
    assert (first["temperature"], second["temperature"]) == (0.5, pytest.approx(0.3))

    # Legacy: a non-dict value is returned as-is and nothing is counted.
    transports[PRIMARY].script("[1, 2]")
    assert client.chat_json(_msgs("legacy-list")) == [1, 2]
    assert "structured_outputs" not in tel.LLMMeter.snapshot(RUN_ID)


def test_flag_off_temperature_zero_replays_the_cached_bad_reply(transports, monkeypatch):
    """The defect the repair turn fixes: at temperature 0 the legacy retry is a cache replay."""
    monkeypatch.setattr(Config, "LLM_JSON_REPAIR_TURN", False, raising=False)
    client = _client()
    transports[PRIMARY].script("garbage", '{"a": 1}')

    with pytest.raises(ValueError):
        client.chat_json(_msgs("legacy-temp0"), temperature=0.0)
    assert len(transports[PRIMARY].calls) == 1


def test_allow_non_dict_accepts_a_list_without_repair(transports):
    client = _client()
    transports[PRIMARY].script("[1, 2]")

    assert client.chat_json(_msgs("allow-list"), allow_non_dict=True) == [1, 2]
    assert len(transports[PRIMARY].calls) == 1
    assert _structured()["ok"] == 1


def test_label_and_stage_attribution(transports):
    client = _client()
    transports[PRIMARY].script('{"a": 1}')
    client.chat_json(_msgs("label-ok"), label="critique")
    tel.set_stage("report")
    transports[PRIMARY].script("[]", "[]")
    with pytest.raises(ValueError):
        client.chat_json(_msgs("label-fail"), label="critique")

    counts = _structured("critique")
    assert (counts["ok"], counts["repaired"], counts["failed"]) == (1, 0, 1)
    by_stage = _structured_by_stage("critique")
    assert by_stage["graph"]["ok"] == 1
    assert by_stage["report"]["failed"] == 1
    assert _structured() is None  # the default label was never used


def test_telemetry_disabled_records_no_structured_outcome(transports, monkeypatch):
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", False, raising=False)
    client = _client()
    transports[PRIMARY].script("[]", '{"a": 1}')

    assert client.chat_json(_msgs("no-telemetry")) == {"a": 1}
    assert "structured_outputs" not in tel.LLMMeter.snapshot(RUN_ID)


# ---------------------------------------------------------------- cache discard
def test_fallback_served_miss_discards_the_fallback_key_too(transports, monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "kimi")
    monkeypatch.setenv("LLM_FALLBACK_MODEL", "kimi-fallback-model")
    monkeypatch.setenv("LLM_FALLBACK_API_KEY", "sk-fallback")
    monkeypatch.setenv("LLM_FALLBACK_BASE_URL", "http://127.0.0.1:2/v1")
    client = _client()
    transports[PRIMARY].script(_resp("", finish="content_filter"))  # primary always filtered
    transports["kimi"] = _Transport()
    transports["kimi"].script("[1]", '{"a": 1}')
    messages = _msgs("fallback")

    assert client.chat_json(messages, temperature=0.0) == {"a": 1}
    assert len(transports["kimi"].calls) == 2
    assert tel.LLMCache.get(_key(messages, 0.0)) is None
    assert tel.LLMCache.get(_key(messages, 0.0, provider="kimi", model="kimi-fallback-model")) is None
    repair_messages = transports["kimi"].calls[1]["messages"]
    assert tel.LLMCache.get(_key(repair_messages, 0.0)) == '{"a": 1}'


def test_use_cache_false_client_never_touches_the_cache(transports, monkeypatch):
    discarded = []
    monkeypatch.setattr(tel.LLMCache, "discard", classmethod(lambda cls, key: discarded.append(key)))
    client = _client(use_cache=False)
    transports[PRIMARY].script("[]", '{"a": 1}')

    assert client.chat_json(_msgs("uncached")) == {"a": 1}
    assert discarded == [] and tel.LLMCache._store == {}


def test_discard_failure_never_breaks_the_call(transports, monkeypatch):
    def boom(cls, key):
        raise RuntimeError("cache exploded")

    monkeypatch.setattr(tel.LLMCache, "discard", classmethod(boom))
    client = _client()
    transports[PRIMARY].script("[]", '{"a": 1}')

    assert client.chat_json(_msgs("discard-boom")) == {"a": 1}


def test_record_structured_failure_never_breaks_the_call(transports, monkeypatch):
    monkeypatch.setattr(tel, "STRUCTURED_OUTCOMES", ())  # every outcome now "unknown"
    client = _client()
    transports[PRIMARY].script('{"a": 1}')

    assert client.chat_json(_msgs("record-boom")) == {"a": 1}
    assert "structured_outputs" not in tel.LLMMeter.snapshot(RUN_ID)


def test_chat_and_repair_path_share_one_cache_key_helper(transports):
    client = _client(pinned=True)
    transports[PRIMARY].script('{"a": 1}')
    messages = _msgs("pinned")

    client.chat_json(messages, temperature=0.1)
    pinned_key = _key(messages, 0.1, provider=f"{PRIMARY}#pinned")
    assert client._cache_key(PRIMARY_MODEL, messages, 0.1, 4096, _JSON_FORMAT) == pinned_key
    assert tel.LLMCache.get(pinned_key) == '{"a": 1}'


# ---------------------------------------------------------------- parse helper
@pytest.mark.parametrize("text, expected", [
    ('{"a": 1}', ({"a": 1}, False)),
    ('```json\n{"a": 1}\n```', ({"a": 1}, False)),
    ('Sure: {"a": 1} done', ({"a": 1}, False)),
    ("[1, 2]", ([1, 2], False)),
    ('{"a": [1, 2', ({"a": [1, 2]}, True)),
    ('{"a": "unterminated', ({"a": "unterminated"}, True)),
    ('{"a": 1,', ({"a": 1}, True)),
    ("no json here", (None, False)),
    ("null", (None, False)),
    ("", (None, False)),
])
def test_parse_json_response_ex_reports_truncation_repair(text, expected):
    assert lc.LLMClient._parse_json_response_ex(text) == expected
    assert lc.LLMClient._parse_json_response(text) == expected[0]


@pytest.mark.parametrize("text, expected_value", [
    ("null", None),                 # parsed: JSON null
    ("```json\nnull\n```", None),   # parsed: fenced JSON null
    ("[1]", [1]),
    ("no json here", "UNPARSED"),
    ("", "UNPARSED"),
    ('{"a": "x" "b"}', "UNPARSED"),  # has braces, repair branch still fails
])
def test_parse_json_response_ex_unparsed_sentinel_tells_null_from_garbage(text, expected_value):
    sentinel = object()
    value, repaired = lc.LLMClient._parse_json_response_ex(text, unparsed=sentinel)
    assert repaired is False
    if expected_value == "UNPARSED":
        assert value is sentinel
    else:
        assert value == expected_value and value is not sentinel


def test_new_chat_json_options_are_keyword_only():
    import inspect

    params = inspect.signature(lc.LLMClient.chat_json).parameters
    assert params["label"].kind is inspect.Parameter.KEYWORD_ONLY and params["label"].default is None
    assert params["allow_non_dict"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["allow_non_dict"].default is False


@pytest.mark.parametrize("value, expected", [(None, "True True"), (" FALSE ", "False False")])
def test_knobs_default_on_and_documented_in_env_example(value, expected):
    import subprocess
    import sys

    knobs = ("LLM_JSON_REPAIR_TURN", "REPORT_CRITIQUE_SINGLE_PASS")
    env = {k: v for k, v in os.environ.items() if k not in knobs}
    env["DRF_TEST_PROCESS"] = "1"
    if value is not None:
        env.update(dict.fromkeys(knobs, value))
    probe = ("from app.config import Config; "
             "print(Config.LLM_JSON_REPAIR_TURN, Config.REPORT_CRITIQUE_SINGLE_PASS)")
    proc = subprocess.run([sys.executable, "-c", probe], cwd=os.path.join(_REPO_ROOT, "backend"),
                          env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == expected
    with open(os.path.join(_REPO_ROOT, ".env.example"), encoding="utf-8") as f:
        text = f.read()
    assert "# LLM_JSON_REPAIR_TURN=true" in text
    assert "# REPORT_CRITIQUE_SINGLE_PASS=true" in text
