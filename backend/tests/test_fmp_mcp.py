"""Official FMP client acceptance through real SDK + scripted HTTP transport.

No provider/network calls. Run under scripts/main_offline_pytest.py using the
primary backend interpreter with -I -S -B and a unique private evidence root.
"""
from __future__ import annotations

import asyncio
import builtins
import copy
import hashlib
import importlib.util
import json
import logging
import math
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit, quote

import httpx
import pytest

BRIDGE = Path(__file__).resolve().parents[2] / "deerflow_bridge"
sys.path.insert(0, str(BRIDGE))
import fmp_mcp as fmp

_guard = sys.modules.get("main_offline_guard")
if _guard is not None:
    _source = BRIDGE / "fmp_mcp.py"
    _guard.source_hashes[str(_source)] = hashlib.sha256(_source.read_bytes()).hexdigest()

KEY = "synthetic-fmp-test-key+A/B"
ENV = {"FMP_API_KEY": KEY, "FMP_TIMEOUT_SECONDS": "3"}
SCHEMA = {"type": "object", "properties": {
    "symbol": {"type": "string", "pattern": "^[A-Z.]+$"},
    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
    "date": {"type": "string", "format": "date"},
    "period": {"type": "string", "enum": ["annual", "quarter"]},
}, "required": ["symbol"], "additionalProperties": False}


def tool(name="quote", **changes):
    return {"name": name, "description": "Current company market data.",
            "inputSchema": copy.deepcopy(SCHEMA), **changes}


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0):
        self.chunks, self.delay, self.closed = chunks, delay, False

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self):
        self.closed = True


class Server(httpx.AsyncBaseTransport):
    """Script real JSON-RPC; all SDK serialization/session work stays real."""
    def __init__(self, pages=None, result=None, *, sse=False):
        self.pages = pages if pages is not None else [{"tools": [tool()]}]
        self.result = result if result is not None else {
            "content": [{"type": "text", "text": "Exact provider text"}],
            "structuredContent": {"data": [{"symbol": "AAPL", "price": 201.25,
                "currency": "USD", "date": "2025-12-31", "estimatedEpsAvg": 3.2,
                "url": "https://example.org/news?article=1"}]}, "isError": False}
        self.sse = sse
        self.requests = []
        self.closed = threading.Event()
        self.hook = None

    async def handle_async_request(self, request):
        body = json.loads(request.content) if request.method == "POST" else None
        self.requests.append((request, body))
        assert urlsplit(str(request.url))._replace(query="").geturl() == fmp.SOURCE_URL
        assert parse_qs(request.url.query.decode())["apikey"] == [KEY]
        assert request.headers["accept-encoding"] == "identity"
        if self.hook:
            special = await self.hook(request, body)
            if special is not None:
                return special
        if request.method == "DELETE":
            assert request.headers["mcp-session-id"] == "script-session"
            return httpx.Response(204, request=request)
        assert request.method == "POST"  # optional GET must stay local
        assert request.headers["accept"] == "application/json, text/event-stream"
        assert body["jsonrpc"] == "2.0"
        method = body["method"]
        if method == "initialize":
            assert body["params"]["capabilities"] == {}
            result = {"protocolVersion": body["params"]["protocolVersion"],
                      "capabilities": {"tools": {}}, "serverInfo": {"name": "official-fixture", "version": "1"}}
        else:
            assert request.headers["mcp-session-id"] == "script-session"
            assert request.headers.get("mcp-protocol-version")
            if method == "notifications/initialized":
                assert "id" not in body
                return httpx.Response(202, request=request)
            if method == "tools/list":
                cursor = body.get("params", {}).get("cursor")
                result = self.pages[0 if cursor is None else int(cursor)]
            elif method == "tools/call":
                result = self.result
            else:
                raise AssertionError("Unexpected protocol method")
        payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
        headers = {"mcp-session-id": "script-session"}
        if self.sse and method != "initialize":
            payload = b": keepalive\n\nevent: message\ndata: " + payload + b"\n\n"
            headers["content-type"] = "text/event-stream"
        else:
            headers["content-type"] = "application/json"
        # Chunked stream, not httpx.Response(json=...) which caches body bytes.
        return httpx.Response(200, headers=headers, stream=Chunks([payload[:19], payload[19:]]), request=request)

    async def aclose(self):
        self.closed.set()

    def methods(self):
        return [body["method"] if body else request.method for request, body in self.requests]


def assert_state(result, state, reason=None):
    assert result["provider"] == "fmp"
    assert result["source_url"] == fmp.SOURCE_URL
    assert result["retrieved_at"]
    assert result["status"]["state"] == state, result
    if reason:
        assert result["status"]["reason"] == reason
    assert KEY not in json.dumps(result)
    assert quote(KEY, safe="") not in json.dumps(result)


@pytest.mark.parametrize("sse", [False, True])
def test_actual_sdk_protocol_preserves_provider_fields_and_closes(sse):
    server = Server(sse=sse)
    client = fmp.FmpMcpClient(env=ENV, transport=server)
    result = client.call("quote", {"symbol": "AAPL", "limit": 2})
    assert_state(result, "ok")
    assert result["data"] == server.result["structuredContent"]
    assert result["structuredContent"] == server.result["structuredContent"]
    assert result["content"] == server.result["content"]
    assert server.methods() == ["initialize", "notifications/initialized", "tools/list", "tools/call", "DELETE"]
    call = server.requests[3][1]
    assert call["params"] == {"name": "quote", "arguments": {"symbol": "AAPL", "limit": 2}}
    assert server.closed.is_set()
    client.close()
    client.close()
    assert_state(client.discover(), "unavailable", "client_closed")


def test_import_and_disabled_construction_are_stdlib_only(monkeypatch):
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        assert name.split(".")[0] not in {"mcp", "httpx", "jsonschema", "dotenv"}
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    spec = importlib.util.spec_from_file_location("isolated_fmp_client", BRIDGE / "fmp_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert not module.configured({})
    assert_state(module.FmpMcpClient(env={}).discover(), "disabled")


@pytest.mark.parametrize("setting", ["false", "0", "off", "no"])
def test_explicit_disable_and_supplied_env_isolation(monkeypatch, setting):
    monkeypatch.setenv("FMP_API_KEY", "ambient-secret-should-never-be-used")
    server = Server()
    assert not fmp.configured({})
    assert fmp.configured(ENV)
    assert_state(fmp.FmpMcpClient(env={}, transport=server).discover(), "disabled")
    assert_state(fmp.FmpMcpClient(env={**ENV, "FMP_ENABLED": setting}, transport=server).discover(), "disabled")
    assert not server.requests


@pytest.mark.parametrize("key,value", [("FMP_TIMEOUT_SECONDS", "nan"), ("FMP_TIMEOUT_SECONDS", "inf"),
    ("FMP_MAX_CALLS", "1.5"), ("FMP_MAX_RESPONSE_BYTES", "-1"), ("FMP_MAX_TOOL_PAGES", "100"),
    ("FMP_ENABLED", "maybe"), ("FMP_API_KEY", "key\nheader")])
def test_invalid_configuration_no_network(key, value):
    server = Server()
    assert_state(fmp.FmpMcpClient(env={**ENV, key: value}, transport=server).discover(), "invalid_input")
    assert not server.requests


def test_paginated_catalog_ranking_complete_schema_cache_and_copy():
    first = [tool("company_profile_" + str(i)) for i in range(12)]
    second = [tool("company_news"), tool("company_estimates")]
    server = Server(pages=[{"tools": first, "nextCursor": "1"}, {"tools": second}])
    client = fmp.FmpMcpClient(ENV, server)
    result = client.discover("company news")
    assert_state(result, "ok")
    assert result["tools"][0]["name"] == "company_news"
    assert result["tools"][0]["inputSchema"] == SCHEMA
    assert result["returned_count"] == 8 and result["matched_total"] == 14 and result["truncated"]
    assert server.methods().count("tools/list") == 2
    count = len(server.requests)
    result["tools"][0]["inputSchema"].clear()
    assert client.discover("news")["tools"][0]["inputSchema"] == SCHEMA
    assert len(server.requests) == count
    assert client.discover("no-match")["tools"] == []


@pytest.mark.parametrize("pages,config,reason", [
    ([{"tools": [tool()], "nextCursor": "1"}, {"tools": [], "nextCursor": "1"}], {}, "invalid_pagination_cursor"),
    ([{"tools": [tool()], "nextCursor": "1"}], {"FMP_MAX_TOOL_PAGES": "1"}, "tool_page_limit"),
    ([{"tools": [tool(), tool()]}], {}, "duplicate_tool"),
    ([{"tools": [tool(), tool("news")]}], {"FMP_MAX_TOOLS": "1"}, "tool_count_limit"),
])
def test_catalog_failures_are_not_partial_success(pages, config, reason):
    client = fmp.FmpMcpClient({**ENV, **config}, Server(pages=pages))
    result = client.discover()
    assert_state(result, "unavailable", reason)
    assert result["tools"] == []


def test_only_discovered_read_only_tools_no_alias_dispatch():
    server = Server(pages=[{"tools": [tool(), tool("company_news"),
        tool("delete_quote", annotations={"readOnlyHint": True}),
        tool("financial_bulk"), tool("mystery", description="Unknown capability"),
        tool("company_profile", annotations={"readOnlyHint": False}),
        tool("get_data", description="Retrieve a bounded data item")]}])
    client = fmp.FmpMcpClient(ENV, server)
    assert [item["name"] for item in client.discover()["tools"]] == ["quote", "company_news", "get_data"]
    for name in ["getQuote", "delete_quote", "financial_bulk", "mystery", "company_profile"]:
        assert_state(client.call(name, {"symbol": "AAPL"}), "invalid_input", "unknown_or_non_read_only_tool")
    assert "tools/call" not in server.methods()


@pytest.mark.parametrize("arguments", [{}, {"symbol": 12}, {"symbol": "aapl"},
    {"symbol": "AAPL", "limit": True}, {"symbol": "AAPL", "limit": "2"},
    {"symbol": "AAPL", "limit": 11}, {"symbol": "AAPL", "extra": "x"},
    {"symbol": "AAPL", "period": "monthly"}, {"symbol": "AAPL", "date": "2025-02-30"}])
def test_exact_discovered_schema_rejects_bad_arguments(arguments):
    server = Server()
    assert_state(fmp.FmpMcpClient(ENV, server).call("quote", arguments), "invalid_input")
    assert "tools/call" not in server.methods()


@pytest.mark.parametrize("arguments", [{"apikey": "fake"}, {"FMP_API_KEY": "fake"}, {"apiToken": "fake"},
    {"nested": {"endpoint": "/stable/quote"}},
    {"symbol": "AAPL", "limit": 101}, {"symbol": "AAPL", "offset": -1},
    {"value": math.nan}, {"value": math.inf}, {"query": KEY},
    {"query": "https://attacker.test"}, {"symbols": ["AAPL"] * 11}, {"query": "x" * 2049}])
def test_unsafe_inputs_rejected_before_network(arguments):
    server = Server()
    assert_state(fmp.FmpMcpClient(ENV, server).call("quote", arguments), "invalid_input")
    assert not server.requests


def test_schema_local_refs_supported_remote_and_recursive_rejected():
    schema = {"type": "object", "properties": {"symbol": {"$ref": "#/$defs/symbol"}},
              "$defs": {"symbol": {"type": "string", "enum": ["AAPL"]}}, "required": ["symbol"]}
    server = Server(pages=[{"tools": [tool(inputSchema=schema)]}])
    assert_state(fmp.FmpMcpClient(ENV, server).call("quote", {"symbol": "AAPL"}), "ok")
    for ref in ["https://attacker.test/schema", "#/$defs/symbol"]:
        bad = copy.deepcopy(schema)
        bad["$defs"]["symbol"] = {"$ref": ref}
        server = Server(pages=[{"tools": [tool(inputSchema=bad)]}])
        assert_state(fmp.FmpMcpClient(ENV, server).discover(), "unavailable", "unsupported_schema_reference")


@pytest.mark.parametrize("code,state", [(401, "auth"), (402, "forbidden"), (403, "forbidden"),
    (429, "rate_limited"), (408, "timeout"), (504, "timeout"), (500, "unavailable"), (307, "unavailable")])
def test_http_errors_redacted_no_redirect_no_retry(code, state, caplog):
    server = Server()
    async def reject(request, body):
        logging.getLogger("httpx").error("secret %s", str(request.url))
        return httpx.Response(code, headers={"location": fmp.SOURCE_URL + "/redirect?apikey=" + KEY},
                              content=KEY.encode(), request=request)
    server.hook = reject
    client = fmp.FmpMcpClient(ENV, server)
    assert_state(client.discover(), state, "http_" + str(code))
    assert len(server.requests) == 1
    assert KEY not in caplog.text and quote(KEY, safe="") not in caplog.text
    if state in {"auth", "forbidden", "rate_limited"}:
        assert_state(client.discover(), state)
        assert len(server.requests) == 1


@pytest.mark.parametrize("payload,state", [
    ({"structuredContent": {"Error Message": "Invalid API KEY " + KEY}, "content": []}, "auth"),
    ({"structuredContent": {"data": [{"error": "rate limit exceeded"}]}, "content": []}, "rate_limited"),
    ({"isError": True, "content": [{"type": "text", "text": "Premium endpoint subscription required"}]}, "forbidden"),
    ({"content": [{"type": "text", "text": '{"error":"internal failure"}'}]}, "unavailable"),
])
def test_error_shaped_results_are_not_success(payload, state):
    assert_state(fmp.FmpMcpClient(ENV, Server(result=payload)).call("quote", {"symbol": "AAPL"}), state)


def test_forbidden_statement_does_not_disable_news_and_exact_retry_is_suppressed():
    server = Server(pages=[{"tools": [tool("income_statement"), tool("stock_news")]}])
    async def permission_denied(request, body):
        if body and body["method"] == "tools/call" and body["params"]["name"] == "income_statement":
            return httpx.Response(403, content=b"permission scope unknown", request=request)
    server.hook = permission_denied
    client = fmp.FmpMcpClient(ENV, server)
    assert_state(client.call("income_statement", {"symbol": "AAPL", "limit": 2}), "forbidden", "http_403")
    count = len(server.requests)
    assert_state(client.call("income_statement", {"limit": 2, "symbol": "AAPL"}), "forbidden", "http_403")
    assert len(server.requests) == count
    assert_state(client.call("stock_news", {"symbol": "AAPL"}), "ok")
    assert server.methods().count("tools/call") == 2


def test_legitimate_news_error_terms_and_fields_survive():
    text = "A company faces rate limits and access denied messages for premium subscriptions."
    data = {"data": [{"title": text, "text": text, "url": "https://example.com/story?date=2025-01-01",
                      "publishedDate": "2025-01-01 01:02:03", "currency": "USD"}]}
    payload = {"structuredContent": data, "content": [{"type": "text", "text": text}]}
    result = fmp.FmpMcpClient(ENV, Server(result=payload)).call("quote", {"symbol": "AAPL"})
    assert_state(result, "ok")
    assert result["structuredContent"] == data and result["content"] == payload["content"]


def test_secret_echo_in_success_payload_and_sdk_exception_never_leaks(caplog):
    payload = {"content": [{"type": "text", "text": KEY + " " + quote(KEY, safe="")}],
               "structuredContent": {"apikey": KEY, "url": fmp.SOURCE_URL + "?apikey=" + quote(KEY, safe="")}}
    client = fmp.FmpMcpClient(ENV, Server(result=payload))
    result = client.call("quote", {"symbol": "AAPL"})
    assert_state(result, "ok")
    assert "[REDACTED]" in json.dumps(result)
    server = Server()
    async def explode(request, body):
        raise RuntimeError("remote echoed " + KEY + " " + str(request.url))
    server.hook = explode
    assert_state(fmp.FmpMcpClient(ENV, server).discover(), "unavailable")
    assert KEY not in caplog.text and quote(KEY, safe="") not in caplog.text


def test_mcp_extension_fields_cannot_spoof_client_envelope():
    payload = {"content": [], "structuredContent": {"data": [1]},
               "provider": "attacker", "status": {"state": "forbidden"},
               "source_url": "https://attacker.invalid", "tool": "spoofed", "data": "spoofed"}
    result = fmp.FmpMcpClient(ENV, Server(result=payload)).call("quote", {"symbol": "AAPL"})
    assert_state(result, "ok")
    assert result["tool"] == "quote" and result["data"] == {"data": [1]}


@pytest.mark.parametrize("mode", ["length", "stream", "compressed"])
def test_response_limit_before_sdk_parse(mode):
    server = Server()
    async def oversized(request, body):
        headers = {"content-type": "application/json"}
        if mode == "length":
            headers["content-length"] = "5000"
        if mode == "compressed":
            headers["content-encoding"] = "gzip"
        return httpx.Response(200, headers=headers, stream=Chunks([b"x" * 600] * 2), request=request)
    server.hook = oversized
    reason = "encoded_response_rejected" if mode == "compressed" else "response_size_limit"
    assert_state(fmp.FmpMcpClient({**ENV, "FMP_MAX_RESPONSE_BYTES": "1000"}, server).discover(), "unavailable", reason)
    assert len(server.requests) == 1


@pytest.mark.parametrize("phase", ["initialize", "tools/list", "tools/call", "DELETE"])
def test_deadline_bounds_entire_operation_and_shutdown(phase):
    server = Server()
    entered = threading.Event()
    async def slow(request, body):
        method = body["method"] if body else request.method
        if method == phase:
            entered.set()
            await asyncio.sleep(3)
    server.hook = slow
    client = fmp.FmpMcpClient(ENV, server)
    start = time.monotonic()
    result = client.call("quote", {"symbol": "AAPL"}, deadline=start + .12)
    assert_state(result, "timeout")
    assert time.monotonic() - start < .5
    assert entered.is_set()
    client.close()
    assert server.closed.wait(.4)


def test_discovery_and_call_share_absolute_deadline_and_expired_no_io():
    server = Server()
    client = fmp.FmpMcpClient(ENV, server)
    assert_state(client.discover(deadline=time.monotonic() - 1), "timeout")
    assert not server.requests
    assert_state(client.discover(deadline=float("nan")), "invalid_input")
    end = time.monotonic() + .15
    assert_state(client.discover(deadline=end), "ok")
    async def slow(request, body):
        await asyncio.sleep(.2)
    server.hook = slow
    assert_state(client.call("quote", {"symbol": "AAPL"}, deadline=end), "timeout")
    client.close()


def test_client_operation_cap_cache_does_not_spend():
    server = Server()
    client = fmp.FmpMcpClient({**ENV, "FMP_MAX_CALLS": "1"}, server)
    assert_state(client.discover(), "ok")
    count = len(server.requests)
    assert_state(client.discover("quote"), "ok")
    assert_state(client.call("quote", {"symbol": "AAPL"}), "rate_limited", "client_call_cap")
    assert len(server.requests) == count


def test_close_cancels_active_call_and_cannot_start_second_worker():
    server = Server()
    entered = threading.Event()
    async def slow(request, body):
        entered.set()
        await asyncio.sleep(10)
    server.hook = slow
    client = fmp.FmpMcpClient(ENV, server)
    results = []
    thread = threading.Thread(target=lambda: results.append(client.discover()))
    thread.start()
    assert entered.wait(1)
    assert_state(client.discover(), "unavailable", "operation_in_progress")
    start = time.monotonic()
    client.close()
    thread.join(.5)
    assert not thread.is_alive() and time.monotonic() - start < .6
    assert_state(results[0], "timeout")
    assert server.closed.is_set()


@pytest.mark.parametrize("message,state", [("Invalid API KEY", "auth"), ("Too many requests", "rate_limited"),
    ("Premium endpoint", "forbidden"), ("request timed out", "timeout")])
def test_jsonrpc_error_status_classification(message, state):
    server = Server()
    async def rpc_error(request, body):
        if body and body["method"] == "tools/call":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"],
                "error": {"code": -32001, "message": message + " " + KEY}}, request=request)
    server.hook = rpc_error
    assert_state(fmp.FmpMcpClient(ENV, server).call("quote", {"symbol": "AAPL"}), state, "provider_rpc_error")


def test_network_transport_explicitly_disables_environment_proxies(monkeypatch):
    constructed = []
    server = Server()
    def factory(**kwargs):
        constructed.append(kwargs)
        return server
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", factory)
    monkeypatch.setenv("HTTPS_PROXY", "http://unused.invalid:8080")
    assert_state(fmp.FmpMcpClient(ENV).discover(), "ok")
    assert constructed == [{"retries": 0, "trust_env": False}]


def test_shared_budget_charged_per_actual_http_and_denial_blocks(monkeypatch):
    attempts, networks = [], []
    budget = SimpleNamespace(enabled=lambda: True,
        admit_attempt=lambda kind: (attempts.append(kind) or SimpleNamespace(allowed=True)),
        admit_network=lambda kind: (networks.append(kind) or SimpleNamespace(allowed=True)))
    monkeypatch.setitem(sys.modules, "research_budget", budget)
    server = Server()
    assert_state(fmp.FmpMcpClient(ENV, server).call("quote", {"symbol": "AAPL"}), "ok")
    assert attempts == ["fmp_fetch"] * 5 and networks == ["fetch"] * 5
    budget.admit_network = lambda kind: SimpleNamespace(allowed=False)
    server = Server()
    assert_state(fmp.FmpMcpClient(ENV, server).discover(), "rate_limited", "shared_network_budget")
    assert not server.requests


def test_malformed_sdk_notification_and_late_logger_cannot_leak(caplog):
    server = Server()
    async def notify(request, body):
        if body and body["method"] == "tools/call":
            logging.getLogger("httpcore.created_after_client_import").error("late secret %s", KEY)
            invalid = {"jsonrpc": "2.0", "method": "notifications/progress",
                       "params": {"progressToken": KEY, "progress": "invalid-" + KEY}}
            valid = {"jsonrpc": "2.0", "id": body["id"], "result": server.result}
            chunks = [b"event: message\ndata: " + json.dumps(item).encode() + b"\n\n" for item in (invalid, valid)]
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Chunks(chunks), request=request)
    server.hook = notify
    assert_state(fmp.FmpMcpClient(ENV, server).call("quote", {"symbol": "AAPL"}), "ok")
    logging.warning("unrelated caller logging still works")
    assert "unrelated caller logging still works" in caplog.text
    assert KEY not in caplog.text and "created_after_client_import" not in caplog.text


@pytest.mark.parametrize("field", ["inputSchema", "outputSchema"])
@pytest.mark.parametrize("pattern", ["^(a+)+$", "a+!", "^a*a*$", "^a{1,200}a{1,200}$"])
def test_rejects_cpu_unbounded_regex_before_sdk_validation(field, pattern):
    schema = {"type": "object", "properties": {"query": {"type": "string", "pattern": pattern}}}
    server = Server(pages=[{"tools": [tool(**{field: schema})]}])
    start = time.monotonic()
    result = fmp.FmpMcpClient(ENV, server).call("quote", {"query": "a" * 100 + "!"})
    assert_state(result, "unavailable", "unsupported_schema_pattern")
    assert time.monotonic() - start < .5
    assert "tools/call" not in server.methods()


def test_output_schema_remote_reference_rejected_before_call():
    schema = {"type": "object", "properties": {"data": {"$ref": "https://attacker.invalid/schema"}}}
    server = Server(pages=[{"tools": [tool(outputSchema=schema)]}])
    assert_state(fmp.FmpMcpClient(ENV, server).call("quote", {"symbol": "AAPL"}), "unavailable", "unsupported_schema_reference")
    assert "tools/call" not in server.methods()


def test_package_import_resolves_sibling_budget_without_bridge_path(monkeypatch):
    monkeypatch.syspath_prepend(str(BRIDGE.parent))
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != str(BRIDGE)])
    module = importlib.import_module("deerflow_bridge.fmp_mcp")
    package = importlib.import_module("deerflow_bridge")
    budget = SimpleNamespace(enabled=lambda: True, admit_attempt=lambda kind: SimpleNamespace(allowed=False))
    monkeypatch.setitem(sys.modules, "deerflow_bridge.research_budget", budget)
    monkeypatch.setattr(package, "research_budget", budget, raising=False)
    original = builtins.__import__
    def no_top_level(name, *args, **kwargs):
        if name == "research_budget":
            raise ImportError("standalone name absent in package mode")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_top_level)
    server = Server()
    assert_state(module.FmpMcpClient(ENV, server).discover(), "rate_limited", "shared_attempt_budget")
    assert not server.requests


def official_tools():
    fixture = Path(__file__).parent / "fixtures/fmp_official_catalog.json"
    if _guard is not None:
        _guard.source_hashes[str(fixture)] = hashlib.sha256(fixture.read_bytes()).hexdigest()
    payload = json.loads(fixture.read_text())
    return payload["tools"]


@pytest.mark.parametrize("name,arguments", [
    ("quote", {"endpoint": "quote", "symbol": "AAPL"}),
    ("news", {"endpoint": "search-stock-news", "symbols": ["AAPL"], "limit": 1, "page": 0}),
    ("statements", {"endpoint": "income-statement", "symbol": "AAPL", "period": "annual", "limit": 1}),
])
def test_actual_official_category_schema_allows_only_discovered_selector(name, arguments):
    server = Server(pages=[{"tools": official_tools()}])
    result = fmp.FmpMcpClient(ENV, server).call(name, arguments)
    assert_state(result, "ok")
    assert next(body["params"] for _, body in server.requests if body and body["method"] == "tools/call") == {"name": name, "arguments": arguments}


@pytest.mark.parametrize("arguments", [
    {"endpoint": "unknown-enum", "symbol": "AAPL"},
    {"endpoint": "https://financialmodelingprep.com/stable/quote", "symbol": "AAPL"},
    {"endpoint": "full-exchange-quotes", "exchange": "NASDAQ"},
    {"endpoint": "full-etf-quotes"}, {"endpoint": "batch-quote", "symbols": ["AAPL"]},
    {"endpoint": "quote"}, {"endpoint": "quote", "symbol": ""},
])
def test_actual_official_selector_rejects_bulk_unknown_url_and_missing_required(arguments):
    server = Server(pages=[{"tools": official_tools()}])
    assert_state(fmp.FmpMcpClient(ENV, server).call("quote", arguments), "invalid_input")
    assert "tools/call" not in server.methods()


def test_plain_endpoint_parameter_needs_schema_enum_not_just_string():
    schema = {"type": "object", "properties": {"endpoint": {"type": "string"}}, "required": ["endpoint"]}
    server = Server(pages=[{"tools": [tool(inputSchema=schema)]}])
    assert_state(fmp.FmpMcpClient(ENV, server).call("quote", {"endpoint": "quote"}), "invalid_input", "endpoint_not_in_discovered_enum")
