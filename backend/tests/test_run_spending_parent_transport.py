"""Parent SB-03/07/11: real LLMClient, SDK and ledger, synthetic HTTP only.

Run through main_offline_pytest.py. Fixture tariffs and bounds are assertions
about a synthetic route, never qualification of a live provider or invoice.
"""
from contextlib import ExitStack
import builtins
import contextvars
from copy import deepcopy
import hashlib
import importlib
import json
import logging
from pathlib import Path
import sqlite3
import sys
import threading
import traceback
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.config import Config
from app.utils import llm_client as lc


pytestmark = pytest.mark.guarded_runner
ENDPOINT = "https://synthetic.invalid/v1"
MODEL = "glm-4.7"
SECRET = "synthetic-canary-never-real-secret"
MESSAGES = [{"role": "user", "content": "private prompt " + SECRET}]


@pytest.fixture
def api(monkeypatch):
    # The production latch has no reset API. Isolate only these inspected core
    # globals between tests; every test still exercises real activation/denial.
    spending = lc._spending()
    monkeypatch.setattr(spending, "_REQUIRED", False)
    monkeypatch.setattr(spending, "_ACTIVE_AUTH", None)
    monkeypatch.setattr(spending, "_LOCAL_STOPS", {})
    monkeypatch.setattr(spending, "_binding", contextvars.ContextVar("parent-test-binding", default=None))
    monkeypatch.setattr(spending, "_operation", contextvars.ContextVar("parent-test-operation", default=None))
    for name in ("REQUIRED", "BINDING", "MODULE_SHA256", "OPERATION"):
        monkeypatch.delenv("DRF_RUN_SPENDING_" + name, raising=False)
    return spending


def _response(content='{"ok": true}', *, usage=True):
    body = {"id": "private-request-" + SECRET, "object": "chat.completion", "created": 0,
            "model": MODEL, "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": content}}]}
    if usage:
        body["usage"] = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    return httpx.Response(200, json=body)


@pytest.fixture
def configured(monkeypatch):
    for key, value in {
        "LLM_PROVIDER": "glm", "LLM_API_KEY": SECRET, "LLM_BASE_URL": ENDPOINT,
        "LLM_MODEL_NAME": MODEL, "LLM_CACHE_ENABLED": False, "LLM_TELEMETRY_ENABLED": False,
        "LLM_TIERED_ROUTING": False, "LLM_HTTP2": False, "LLM_RUN_BUDGET_TOKENS": 0,
        "LLM_RUN_BUDGET_USD": 0, "LLM_DISABLE_THINKING": True,
        "LLM_ALWAYS_THINKING_MODELS": "glm-5", "LLM_THINKING_REQUIRED_EFFORT": "low",
        "LLM_THINKING_HEADROOM_TOKENS": 2048, "_thinking_refused": set(),
    }.items():
        monkeypatch.setattr(Config, key, value)
    monkeypatch.setattr(lc, "_CB_STATE", {})
    monkeypatch.setattr(lc, "_FB_OPENAI_CLIENTS", {})
    monkeypatch.setattr(lc, "_FB_AUTH_UNAVAILABLE_UNTIL", {})
    monkeypatch.delenv("LLM_FALLBACK_PROVIDER", raising=False)
    # Platform discovery in SDK headers is unrelated to transport admission.
    monkeypatch.setattr(openai._base_client, "platform_headers", lambda *a, **k: {})


@pytest.fixture
def ledger_case(api, configured, tmp_path, monkeypatch):
    stack = ExitStack()
    ledger_violations = []

    def build(*, cap="1.000000", operation=True):
        root = tmp_path / "runtime"
        (root / "spend").mkdir(parents=True)
        (root / "app").mkdir()
        source = Path(lc.__file__).read_bytes()
        (root / "app" / "llm_client.py").write_bytes(source)
        source_files = {"app/llm_client.py": hashlib.sha256(source).hexdigest()}
        routes = {"model-main": {
            "kind": "openai_chat", "endpoint": ENDPOINT, "model": MODEL,
            "account_sha256": hashlib.sha256(SECRET.encode("utf-8")).hexdigest(), "billing_class": "external_model",
            "basis_sha256": "b" * 64, "input_bound": "enforced_context_ceiling",
            "input_ceiling": 1000, "max_output_tokens": 8192, "max_tool_units": 0,
            "pricing": {"input_usd_per_million": "1", "output_usd_per_million": "2",
                        "tool_usd_per_unit": "0", "fixed_usd": "0", "surcharge_usd": "0"},
            "coverage": "all_billable_dimensions",
        }}
        pipeline_request = {"question": "synthetic fixture", "forecast_authority": "target-first-v1"}
        manifest = {"schema": "target-run-spending/v1", "authorization_id": "parent-fixture",
                    "root": str(root), "currency": "USD", "cap_usd": cap,
                    "request_sha256": api.hash_payload(pipeline_request), "source_files": source_files,
                    "source_sha256": api.hash_payload(source_files), "routes_sha256": api.hash_payload(routes),
                    "resume_policy": "explicit_clean_only", "routes": routes}
        path = root / "spend" / "authorization.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        (tmp_path / "registry").mkdir()
        binding = api.create_authorization(path, registry_dir=tmp_path / "registry")
        stack.enter_context(api.run_lock(binding))
        binding = api.bind_pipeline(binding, "pipe_parent_fixture", pipeline_request)
        api.activate_binding(binding)
        if operation:
            stack.enter_context(api.operation("parent-method", "method-001"))
        sent, before, clients = [], [], []

        def rows():
            with sqlite3.connect(binding["db_path"]) as db:
                db.row_factory = sqlite3.Row
                return [{**dict(row), **json.loads(row["envelope"]),
                         "reserved_max_microusd": row["reserved"]}
                        for row in db.execute("SELECT * FROM attempts ORDER BY ordinal")]

        def client(responses=None):
            script = list(responses or [_response()])

            def transport(request):
                # Separate connection: an uncommitted reservation cannot satisfy
                # this check. Count real HTTP callbacks, not SDK .create calls.
                index = len(sent)
                sent.append(None)  # Count entry before ANY parsing/assertion.
                try:
                    committed = rows()
                    assert len(committed) == len(sent)
                    assert committed[-1]["reserved_max_microusd"] > 0
                    body = json.loads(request.content)
                    assert committed[-1]["payload_sha256"] == api.hash_payload(body)
                    assert committed[-1]["max_output_tokens"] == body["max_tokens"]
                    assert committed[-1]["input_tokens"] == 1000
                except Exception:
                    # An SDK wrapper may turn an assertion into the expected
                    # stop. Teardown MUST independently fail such a violation.
                    ledger_violations.append(index)
                    raise
                before.append(committed)
                sent[index] = body
                action = script.pop(0)
                if isinstance(action, BaseException):
                    raise action
                return action(request) if callable(action) else action

            http = httpx.Client(transport=httpx.MockTransport(transport), trust_env=False,
                                follow_redirects=False)
            stack.callback(http.close)
            monkeypatch.setattr(lc.LLMClient, "_build_http_client", staticmethod(lambda: http))
            instance = lc.LLMClient()
            clients.append(instance)
            stack.callback(instance._openai_client.close)
            return instance

        return SimpleNamespace(binding=binding, api=api, rows=rows, sent=sent, before=before,
                               client=client, clients=clients, manifest=manifest)

    try:
        yield build
    finally:
        stack.close()
        assert ledger_violations == [], "HTTP callback lacked its exact committed reservation"


def test_committed_full_ceiling_before_real_sdk_send(ledger_case):
    case = ledger_case()
    client = case.client()
    assert client.chat_json(MESSAGES, max_tokens=100) == {"ok": True}
    row, = case.rows()
    assert row["reserved_max_microusd"] == 1200
    assert len(case.sent) == 1
    assert client._openai_client.max_retries == 0
    assert SECRET not in json.dumps(case.api.summary(case.binding))


@pytest.mark.parametrize("failure", [
    httpx.Response(429, json={"error": {"message": SECRET}}, headers={"retry-after": "0"}),
    httpx.Response(503, json={"error": {"message": SECRET}}),
    httpx.ReadTimeout(SECRET),
    httpx.ConnectError(SECRET),
    RuntimeError("this model always thinks " + SECRET),
    httpx.Response(200, content="malformed HTTP JSON " + SECRET),
])
def test_unknown_response_halts_before_retry_or_fallback(ledger_case, monkeypatch, failure):
    case = ledger_case()
    client = case.client([failure])
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "claude-cli")
    sleeps = []
    monkeypatch.setattr(lc.time, "sleep", sleeps.append)
    with pytest.raises(case.api.SpendingStop) as error:
        client.chat_json(MESSAGES, max_tokens=100)
    assert error.value.code == "unknown_outcome"
    assert SECRET not in "".join(traceback.format_exception(error.value))
    with pytest.raises(case.api.SpendingStop):
        client.chat(MESSAGES, max_tokens=100)
    assert len(case.sent) == 1 and sleeps == []
    assert case.rows()[0]["reserved_max_microusd"] == 1200
    assert case.api.summary(case.binding)["state"] == "halted_unknown"


def _refusal():
    return httpx.Response(400, json={"error": {"code": "1210", "message":
        "该模型始终思考，不支持关闭思考；请使用 low、high 或 max。 " + SECRET}})


def test_reasoning_refusal_resend_has_new_final_quote(ledger_case):
    case = ledger_case()
    client = case.client([_refusal(), _response()])
    assert client.chat_json(MESSAGES, max_tokens=100) == {"ok": True}
    first, second = case.rows()
    assert [c["max_tokens"] for c in case.sent] == [100, 2148]
    assert [first["reserved_max_microusd"], second["reserved_max_microusd"]] == [1200, 5296]
    assert first["attempt_id"] != second["attempt_id"]
    assert first["ordinal"] != second["ordinal"]
    assert first["payload_sha256"] != second["payload_sha256"]
    assert SECRET not in json.dumps(case.rows())


def test_reasoning_resend_denied_when_widened_quote_does_not_fit(ledger_case):
    case = ledger_case(cap="0.005000")
    client = case.client([_refusal()])
    with pytest.raises(case.api.SpendingStop) as error:
        client.chat_json(MESSAGES, max_tokens=100)
    assert error.value.code == "budget_exhausted"
    assert len(case.sent) == len(case.rows()) == 1


@pytest.mark.parametrize("content", ["", "not JSON " + SECRET])
def test_empty_and_json_repair_are_separate_physical_attempts(ledger_case, monkeypatch, content):
    case = ledger_case()
    client = case.client([_response(content), _response()])
    monkeypatch.setattr(lc.time, "sleep", lambda _: None)
    assert client.chat_json(MESSAGES, max_tokens=100) == {"ok": True}
    rows = case.rows()
    assert len(rows) == len(case.sent) == 2
    assert sum(r["reserved_max_microusd"] for r in rows) == 2400
    assert rows[0]["attempt_id"] != rows[1]["attempt_id"]
    # The first usage observation must already be durable before the repair send.
    observed = json.loads(case.before[1][0]["observation"])
    assert observed["kind"] == "provider_reported"
    assert observed["input_tokens"] == 3 and observed["output_tokens"] == 2
    assert case.before[0][0]["observation"] is None


def test_missing_usage_is_explicit_without_token_estimation(ledger_case, monkeypatch):
    from app.utils import telemetry

    case = ledger_case()
    client = case.client([_response(usage=False)])
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", True)
    monkeypatch.setattr(telemetry, "estimate_tokens", lambda _: pytest.fail("bound missing usage was estimated"))
    assert client.chat_json(MESSAGES, max_tokens=100) == {"ok": True}
    assert client._last_usage is None
    row, = case.rows()
    assert row["reserved_max_microusd"] == 1200
    assert "missing" in json.dumps(row)
    assert "verified_billed" not in json.dumps(row)


def test_invalid_model_json_error_does_not_echo_response(ledger_case):
    case = ledger_case()
    client = case.client([_response(SECRET), _response(SECRET)])
    with pytest.raises(ValueError) as error:
        client.chat_json(MESSAGES, max_tokens=100)
    assert SECRET not in "".join(traceback.format_exception(error.value))
    assert len(case.rows()) == 2


@pytest.mark.parametrize("route", ["cli", "endpoint", "model", "tier", "credential"])
def test_invalid_route_denies_before_sdk_construction(ledger_case, monkeypatch, route):
    case = ledger_case()
    constructions = []
    monkeypatch.setattr(lc.LLMClient, "_build_openai_client", staticmethod(lambda *a, **k: constructions.append(k)))
    kwargs = {}
    if route == "cli":
        kwargs["provider"] = "claude-cli"
    elif route == "endpoint":
        kwargs["base_url"] = "https://other.invalid/v1"
    elif route == "model":
        kwargs["model"] = "other-model"
    elif route == "tier":
        monkeypatch.setattr(Config, "LLM_TIERED_ROUTING", True)
    else:
        kwargs["api_key"] = "unbound-credential"
    with pytest.raises(case.api.SpendingStop):
        lc.LLMClient(**kwargs)
    assert constructions == [] and case.rows() == []


def test_missing_operation_denies_before_construction(ledger_case, monkeypatch):
    case = ledger_case(operation=False)
    constructions = []
    monkeypatch.setattr(lc.LLMClient, "_build_openai_client", staticmethod(lambda *a, **k: constructions.append(k)))
    with pytest.raises(case.api.SpendingStop) as error:
        lc.LLMClient()
    assert error.value.code == "missing_context"
    assert constructions == [] and case.rows() == []


def test_lost_thread_context_denies_before_construction(ledger_case, monkeypatch):
    case = ledger_case()
    constructions, errors = [], []
    monkeypatch.setattr(lc.LLMClient, "_build_openai_client", staticmethod(lambda *a, **k: constructions.append(k)))

    def worker():
        try:
            lc.LLMClient()
        except case.api.SpendingStop as exc:
            errors.append(exc.code)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert errors == ["missing_context"] and constructions == [] and case.rows() == []


@pytest.mark.parametrize("extra", [
    {"stream": True}, {"n": 2}, {"tools": []}, {"max_completion_tokens": 500},
    {"extra_body": {"max_tokens": 500}}, {"extra_body": {"model": "other"}},
    {"extra_body": {"stream": True}}, {"extra_body": {"service_tier": "priority"}},
    {"extra_headers": {"X-Stainless-Raw-Response": "stream"}},
    {"extra_query": {"api-version": "other"}},
])
def test_unproved_wire_dimensions_deny_before_send(ledger_case, extra):
    case = ledger_case()
    client = case.client()
    kwargs = {"model": MODEL, "messages": MESSAGES, "max_tokens": 100, "temperature": 0.3, **extra}
    with pytest.raises(case.api.SpendingStop):
        client._create_completion(client._openai_client, kwargs, 0.3, 100)
    assert case.sent == [] and case.rows() == []


@pytest.mark.parametrize("method", ["tools", "fallback", "fast", "claude", "codex"])
def test_unsupported_entry_points_deny(ledger_case, method):
    case = ledger_case()
    client = case.client()
    with pytest.raises(case.api.SpendingStop):
        if method == "tools":
            client.chat_with_tools(MESSAGES, [], max_tokens=100)
        elif method == "fallback":
            client._try_fallback(MESSAGES, 0.3, 100, None, RuntimeError(SECRET))
        elif method == "fast":
            client._fast_provider_client()
        elif method == "claude":
            client._chat_claude_cli(MESSAGES, 0.3, 100)
        else:
            client._chat_codex_cli(MESSAGES, 0.3, 100)
    assert case.sent == [] and case.rows() == []


@pytest.mark.parametrize("change", ["retry", "redirect", "auth", "hook", "key_callback", "query", "header",
                                   "http_query", "http_header", "cookie", "endpoint"])
def test_changed_sdk_cannot_add_hidden_physical_requests(ledger_case, change):
    case = ledger_case()
    client = case.client()
    sdk = client._openai_client
    callbacks = []
    if change == "retry":
        sdk.max_retries = 2
    elif change == "redirect":
        sdk._client.follow_redirects = True
    elif change == "auth":
        sdk._client.auth = httpx.DigestAuth("fixture", SECRET)
    elif change == "hook":
        sdk._client.event_hooks["request"] = [lambda _: callbacks.append(True)]
    elif change == "key_callback":
        sdk._api_key_provider = lambda: callbacks.append(True) or SECRET
    elif change == "query":
        sdk._custom_query = {"extra": SECRET}
    elif change == "header":
        sdk._custom_headers = {"X-Stainless-Raw-Response": "stream"}
    elif change == "http_query":
        sdk._client.params = {"unpriced": SECRET}
    elif change == "http_header":
        sdk._client.headers["X-Unpriced-Option"] = SECRET
    elif change == "cookie":
        sdk._client.cookies.set("account", SECRET)
    else:
        sdk.base_url = "https://other.invalid/v1"
    with pytest.raises(case.api.SpendingStop):
        client.chat(MESSAGES, max_tokens=100)
    assert case.sent == [] and callbacks == [] and case.rows() == []


@pytest.mark.parametrize("status", [307, 308])
def test_redirect_response_has_one_reserved_http_call(ledger_case, status):
    case = ledger_case()
    client = case.client([httpx.Response(status, headers={"location": "https://other.invalid/v1"})])
    with pytest.raises(case.api.SpendingStop):
        client.chat(MESSAGES, max_tokens=100)
    assert len(case.sent) == len(case.rows()) == 1


def test_wrapped_shared_stop_preserves_identity(ledger_case, monkeypatch):
    case = ledger_case()
    stop = case.api.SpendingStop("budget_exhausted")
    client = case.client([stop])
    sleeps = []
    monkeypatch.setattr(lc.time, "sleep", sleeps.append)
    with pytest.raises(case.api.SpendingStop) as error:
        client.chat_json(MESSAGES, max_tokens=100)
    assert error.value is stop
    assert len(case.sent) == 1 and sleeps == []
    with pytest.raises(case.api.SpendingStop):
        client.chat(MESSAGES, max_tokens=100)
    assert len(case.sent) == 1


def test_local_cache_hit_has_no_physical_reservation(ledger_case, monkeypatch):
    from app.utils.telemetry import LLMCache

    case = ledger_case()
    client = case.client()
    monkeypatch.setattr(Config, "LLM_CACHE_ENABLED", True)
    monkeypatch.setattr(LLMCache, "get", classmethod(lambda cls, key: '{"cached": true}'))
    assert client.chat_json(MESSAGES, max_tokens=100) == {"cached": True}
    assert case.sent == [] and case.rows() == []


def test_debug_body_logging_denies_before_send(ledger_case):
    case = ledger_case()
    client = case.client()
    log = logging.getLogger("openai._base_client")
    original = log.level
    try:
        log.setLevel(logging.DEBUG)
        with pytest.raises(case.api.SpendingStop):
            client.chat(MESSAGES, max_tokens=100)
    finally:
        log.setLevel(original)
    assert case.sent == [] and case.rows() == []


@pytest.mark.parametrize("http2,failures", [(False, 0), (True, 0), (True, 1), (True, 2)])
def test_sdk_retry_disabled_in_every_http_construction_branch(ledger_case, monkeypatch, http2, failures):
    case = ledger_case()
    monkeypatch.setattr(Config, "LLM_HTTP2", http2)
    original = httpx.Client.__init__
    attempted = []

    def construct(instance, *args, **kwargs):
        if "http2" in kwargs:
            attempted.append(kwargs["http2"])
            if len(attempted) <= failures:
                raise RuntimeError(SECRET)
        original(instance, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", construct)
    client = lc.LLMClient()
    try:
        sdk = client._openai_client
        assert sdk.max_retries == 0
        assert sdk._client.follow_redirects is False and sdk._client._trust_env is False
        assert case.rows() == []
        assert len(attempted) == (0 if not http2 else 1 if not failures else 2)
    finally:
        client._openai_client.close()


def test_constructor_preserves_shared_stop(ledger_case, monkeypatch):
    case = ledger_case()
    stop = case.api.SpendingStop("budget_exhausted")

    def fail():
        raise stop

    monkeypatch.setattr(lc.LLMClient, "_build_http_client", staticmethod(fail))
    with pytest.raises(case.api.SpendingStop) as error:
        lc.LLMClient()
    assert error.value is stop and case.rows() == []


def test_preconstructed_legacy_sdk_cannot_keep_hidden_retries(api, configured, ledger_case):
    # Configured HTTP/2 is false, so an ordinary legacy SDK retains its default
    # retries. Activation must not let that already-created client bypass checks.
    client = lc.LLMClient()
    assert client._openai_client.max_retries == 2
    try:
        case = ledger_case()
        with pytest.raises(api.SpendingStop):
            client.chat(MESSAGES, max_tokens=100)
        assert case.rows() == []
    finally:
        client._openai_client.close()


def test_unset_environment_cannot_disable_required_latch(ledger_case, monkeypatch):
    case = ledger_case()
    client = case.client()
    for name in ("REQUIRED", "BINDING", "MODULE_SHA256", "OPERATION"):
        monkeypatch.delenv("DRF_RUN_SPENDING_" + name, raising=False)
    assert client.chat(MESSAGES, max_tokens=100) == '{"ok": true}'
    assert len(case.rows()) == len(case.sent) == 1


def test_usage_integrity_stops_without_refund_or_repeat(ledger_case):
    case = ledger_case()
    response = _response()
    body = json.loads(response.content)
    body["usage"]["completion_tokens"] = 101
    client = case.client([httpx.Response(200, json=body)])
    with pytest.raises(case.api.SpendingStop) as error:
        client.chat(MESSAGES, max_tokens=100)
    assert error.value.code == "usage_integrity"
    assert len(case.sent) == 1 and case.rows()[0]["reserved_max_microusd"] == 1200


def test_static_reasoning_headroom_is_quoted_on_first_send(ledger_case, monkeypatch):
    case = ledger_case()
    monkeypatch.setattr(Config, "LLM_ALWAYS_THINKING_MODELS", "glm-4.7")
    client = case.client()
    assert client.chat(MESSAGES, max_tokens=100) == '{"ok": true}'
    assert case.sent[0]["max_tokens"] == 2148
    assert case.rows()[0]["reserved_max_microusd"] == 5296


@pytest.mark.parametrize("descriptor", [None, "not JSON " + SECRET])
def test_present_required_marker_without_valid_binding_denies_before_construction(api, configured, monkeypatch, descriptor):
    monkeypatch.setenv("DRF_RUN_SPENDING_REQUIRED", "1")
    if descriptor is not None:
        monkeypatch.setenv("DRF_RUN_SPENDING_BINDING", descriptor)
    constructions = []
    monkeypatch.setattr(lc.LLMClient, "_build_openai_client", staticmethod(lambda *a, **k: constructions.append(k)))
    with pytest.raises(api.SpendingStop) as error:
        lc.LLMClient()
    assert constructions == []
    assert SECRET not in "".join(traceback.format_exception(error.value))


def test_snapshot_prevents_mutation_between_quote_and_http_send(ledger_case, monkeypatch):
    case = ledger_case()
    client = case.client()
    messages = deepcopy(MESSAGES)
    original = case.api.dispatch

    def dispatch(route_id, request, send, **kwargs):
        # This changes the caller's source after envelope/hash creation.
        messages[0]["content"] = "changed by another owner"
        return original(route_id, request, send, **kwargs)

    monkeypatch.setattr(case.api, "dispatch", dispatch)
    client.chat(messages, max_tokens=100)
    assert case.sent[0]["messages"] == MESSAGES


@pytest.mark.parametrize("extension", ["mount", "proxy", "transport_retry", "transport_subclass", "http_subclass"])
def test_unproved_transport_extensions_deny_before_send(ledger_case, extension):
    case = ledger_case()
    client = case.client()
    http = client._openai_client._client
    replacements = []
    try:
        if extension == "mount":
            http._mounts[httpx._utils.URLPattern("all://")] = httpx.MockTransport(lambda _: pytest.fail("mounted send"))
        elif extension == "proxy":
            transport = httpx.HTTPTransport(proxy="https://proxy.invalid", trust_env=False)
            replacements.append(transport)
            http._transport = transport
        elif extension == "transport_retry":
            transport = httpx.HTTPTransport(retries=2, trust_env=False)
            replacements.append(transport)
            http._transport = transport
        elif extension == "transport_subclass":
            class OpaqueTransport(httpx.MockTransport):
                pass
            http._transport = OpaqueTransport(lambda _: pytest.fail("opaque send"))
        else:
            class OpaqueClient(httpx.Client):
                pass
            alternate = OpaqueClient(transport=httpx.MockTransport(lambda _: pytest.fail("subclass send")),
                                     trust_env=False, follow_redirects=False)
            replacements.append(alternate)
            client._openai_client._client = alternate
        with pytest.raises(case.api.SpendingStop):
            client.chat(MESSAGES, max_tokens=100)
        assert case.sent == [] and case.rows() == []
    finally:
        for replacement in replacements:
            replacement.close()


def test_bound_telemetry_uses_supplied_pipeline_identity(ledger_case, monkeypatch):
    from app.utils import telemetry

    case = ledger_case()
    client = case.client()
    records = []
    monkeypatch.setattr(Config, "LLM_TELEMETRY_ENABLED", True)
    monkeypatch.setattr(telemetry, "get_run_context", lambda: (None, None))
    monkeypatch.setattr(telemetry.LLMMeter, "record", classmethod(lambda cls, *a, **k: records.append((a, k))))
    client.chat(MESSAGES, max_tokens=100)
    args, kwargs = records[0]
    assert kwargs["run_id"] == case.binding["pipeline_id"]
    assert kwargs["stage"] == "parent-method"
    assert args[2:4] == (3, 2)
    assert len(case.rows()) == 1


@pytest.mark.parametrize("malformation", ["error", "choices", "message", "usage", "model"])
def test_malformed_sdk_completion_preserves_usage_and_halts(ledger_case, malformation):
    case = ledger_case()
    body = json.loads(_response().content)
    if malformation == "error":
        body["error"] = {"message": SECRET}
        body.pop("choices")
    elif malformation == "choices":
        body.pop("choices")
    elif malformation == "message":
        body["choices"][0]["message"] = SECRET
    elif malformation == "usage":
        body["usage"] = SECRET
    else:
        body["model"] = "unqualified-model"
    client = case.client([httpx.Response(200, json=body)])
    with pytest.raises(case.api.SpendingStop) as error:
        client.chat(MESSAGES, max_tokens=100)
    assert error.value.code == "unknown_outcome"
    row, = case.rows()
    observed = json.loads(row["observation"])
    assert observed["outcome"] == "unknown"
    if malformation != "usage":
        assert observed["input_tokens"] == 3 and observed["output_tokens"] == 2
    else:
        assert observed["kind"] == "missing"
    assert len(case.sent) == 1 and row["reserved_max_microusd"] == 1200
    assert SECRET not in "".join(traceback.format_exception(error.value))


def test_implicit_and_explicit_exception_links_preserve_stop(ledger_case):
    case = ledger_case()
    stop = case.api.SpendingStop("budget_exhausted")

    def wrap(_):
        try:
            raise stop
        except case.api.SpendingStop:
            raise RuntimeError(SECRET)

    client = case.client([wrap])
    with pytest.raises(case.api.SpendingStop) as error:
        client.chat(MESSAGES, max_tokens=100)
    assert error.value is stop
    assert SECRET not in "".join(traceback.format_exception(error.value))
    with pytest.raises(case.api.SpendingStop):
        client.chat(MESSAGES, max_tokens=100)
    assert len(case.sent) == 1


def test_changed_config_credential_cannot_replace_manifest_identity(ledger_case, monkeypatch):
    case = ledger_case()
    monkeypatch.setattr(Config, "LLM_API_KEY", "different-configured-credential")
    constructions = []
    monkeypatch.setattr(lc.LLMClient, "_build_openai_client", staticmethod(lambda *a, **k: constructions.append(k)))
    with pytest.raises(case.api.SpendingStop):
        lc.LLMClient()
    assert constructions == [] and case.rows() == []


def test_changed_client_and_config_credential_denied_before_send(ledger_case, monkeypatch):
    case = ledger_case()
    client = case.client()
    monkeypatch.setattr(Config, "LLM_API_KEY", "different-configured-credential")
    client.api_key = Config.LLM_API_KEY
    client._openai_client.api_key = Config.LLM_API_KEY
    with pytest.raises(case.api.SpendingStop):
        client.chat(MESSAGES, max_tokens=100)
    assert case.sent == [] and case.rows() == []


@pytest.mark.parametrize("name,level", [("httpcore.http11", logging.DEBUG), ("httpcore.http2", logging.DEBUG),
                                       ("httpx", logging.INFO), ("openai._response", logging.DEBUG)])
def test_transport_log_settings_deny_without_canary_leak(ledger_case, caplog, name, level):
    case = ledger_case()
    response = httpx.Response(200, json=json.loads(_response().content),
                              headers={"x-private": SECRET}, extensions={"reason_phrase": SECRET.encode()})
    client = case.client([response])
    with caplog.at_level(level, logger=name):
        with pytest.raises(case.api.SpendingStop):
            client.chat(MESSAGES, max_tokens=100)
    assert case.sent == [] and case.rows() == []
    assert SECRET not in caplog.text


@pytest.mark.parametrize("existing_stop", [False, True])
def test_optional_sdk_import_does_not_initialize_services(api, monkeypatch, existing_stop):
    import app.utils

    stop = api.SpendingStop("budget_exhausted")
    original_import = builtins.__import__

    def without_sdk(name, *args, **kwargs):
        if name == "openai" or name.startswith("openai."):
            raise stop if existing_stop else ImportError("synthetic optional SDK unavailable")
        return original_import(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(app.utils, "llm_client", lc)
        for name in list(sys.modules):
            if name == "app.utils.llm_client" or name == "app.services" or name.startswith("app.services."):
                patch.delitem(sys.modules, name)
        if not existing_stop:
            patch.delitem(sys.modules, "deerflow_bridge.run_spending", raising=False)
            patch.delitem(sys.modules, "run_spending", raising=False)
        patch.setattr(builtins, "__import__", without_sdk)
        if existing_stop:
            with pytest.raises(api.SpendingStop) as error:
                importlib.import_module("app.utils.llm_client")
            assert error.value is stop
        else:
            fresh = importlib.import_module("app.utils.llm_client")
            assert fresh._RETRYABLE_API_ERRORS == () and fresh.LLMClient
        assert "app.services" not in sys.modules
