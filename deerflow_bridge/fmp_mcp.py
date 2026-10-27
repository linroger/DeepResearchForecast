"""Bounded, synchronous research client for FMP's *official* remote MCP.

Only stdlib imports occur at module load. MCP/httpx/jsonschema are loaded on
first use. No dotenv, REST fallback, arbitrary endpoint, or automatic retry.
``deadline`` is an absolute ``time.monotonic()`` float, covering initialization,
paginated discovery, invocation and session shutdown. Each operation owns a
fresh SDK session; no session or event loop survives a successful operation.

``transport`` is an optional httpx.AsyncBaseTransport (or zero-argument factory
returning one), intended for scripted offline HTTP tests. It is wrapped by the
same endpoint, byte, status and deadline guards as the real transport.

FMP_API_KEY is read only from env (os.environ when omitted). FMP_ENABLED defaults
on with a key; false/0/no/off disables it. Configurable hard-bounded settings:
FMP_TIMEOUT_SECONDS=20 (<=60), FMP_MAX_CALLS=12 (<=50, external operations),
FMP_MAX_RESPONSE_BYTES=524288 (<=2097152, total wire bytes per operation),
FMP_MAX_TOOL_PAGES=8 (<=20), FMP_MAX_TOOLS=256 (<=512).

Only discovered names are dispatched. Read-only annotations are authoritative
for this fixed official provider. Unannotated tools must describe retrieval or
belong to a bounded financial research family, with no mutation/bulk name.
Ambiguous tools fail closed. Dependency APIs verified with mcp 1.30.0,
httpx 0.28.1 and jsonschema 4.26.0; the standalone skill needs those packages.
"""
from __future__ import annotations

import asyncio
import copy
import contextvars
import json
import logging
import math
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, quote_plus, urlencode

SOURCE_URL = "https://financialmodelingprep.com/mcp"
_FALSE = {"false", "0", "no", "off"}
_TRUE = {"true", "1", "yes", "on"}
_CREDENTIAL = re.compile(r"^(?:api[-_]?key|access[-_]?token|token|secret|password|authorization|credential)s?$", re.I)
_ENDPOINT = re.compile(r"^(?:url|uri|endpoint|base[-_]?url|host|proxy|headers?|method|path)$", re.I)
_UNSAFE_TOOL = re.compile(r"(?:^|[_\W])(?:bulk|batch|download|all|create|delete|remove|write|execute|submit|send|order|buy|sell|trade|set|update|configure|subscribe|unsubscribe)(?:$|[_\W])", re.I)
_READ_DESCRIPTION = re.compile(r"^\s*(?:get|fetch|retrieve|search|find|list|look up|access|returns?|provides?)\b", re.I)
# Admission families, never dispatch aliases: the exact name still must be in
# this authenticated session's tools/list. The official docs' `quote` example
# has an arbitrary description and does not promise read-only annotations.
_RESEARCH_FAMILY = re.compile(r"(?:^|[_\W])(?:quote|quotes|profile|financials?|statements?|income|balance|cash|ratios?|metrics?|valuation|estimates?|earnings|transcripts?|news|filings?|sec|insider|institutional|congressional|senate|house|stock|stocks|company|companies|market|economic|economics|treasury|forex|crypto|commodities|commodity|etf|fund|dividends?|splits?|historical|analyst|ratings?|screener|calendar)(?:$|[_\W])", re.I)
_URL_SECRET = re.compile(r"(?i)([?&](?:api[-_]?key|access[-_]?token|token|secret|password)=)[^&\s\"'<>]*")
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_SELECTOR = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$")
_BULK_SELECTOR = re.compile(r"(?:^|[-_])(?:bulk|batch|all|universe)(?:$|[-_])|^full-.*quotes$", re.I)


class _Fault(Exception):
    def __init__(self, state, reason):
        self.state, self.reason = state, reason
        super().__init__(reason)  # Constant codes only, never remote strings.


def configured(env=None):
    """Whether an explicit/process mapping supplies an enabled, nonempty key."""
    values = os.environ if env is None else env
    key = values.get("FMP_API_KEY", "")
    enabled = str(values.get("FMP_ENABLED", "true")).strip().lower()
    return isinstance(key, str) and bool(key.strip()) and enabled in _TRUE


def _admit_network(kind):
    # Optional in a standalone installed skill. The application's shared ledger
    # owns its environment and fail-open telemetry; no credentials are passed.
    try:
        import research_budget
    except ImportError:
        try:
            from . import research_budget
        except ImportError:
            return
    if not research_budget.enabled():
        return
    if not research_budget.admit_attempt("fmp_" + kind).allowed:
        raise _Fault("rate_limited", "shared_attempt_budget")
    if not research_budget.admit_network(kind).allowed:
        raise _Fault("rate_limited", "shared_network_budget")


def _json_bytes(value):
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise _Fault("invalid_input", "non_json_value") from None


def _check_tree(value, *, inputs=False, depth=0):
    if depth > 24:
        raise _Fault("invalid_input", "nesting_limit")
    if isinstance(value, dict):
        if len(value) > 256 or any(not isinstance(k, str) for k in value):
            raise _Fault("invalid_input", "object_limit")
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            sensitive = any(part in normalized for part in ("apikey", "apitoken", "accesstoken", "authorization", "password", "credential", "secret", "endpoint", "baseurl", "proxy", "headers"))
            selector = depth == 0 and key == "endpoint" and isinstance(child, str) and _SELECTOR.fullmatch(child)
            if inputs and selector and _BULK_SELECTOR.search(child):
                raise _Fault("invalid_input", "bulk_endpoint_rejected")
            if inputs and not selector and (sensitive or normalized in {"auth", "token", "bearer", "key", "fmpkey", "hostname"} or _CREDENTIAL.fullmatch(key) or _ENDPOINT.fullmatch(key)):
                raise _Fault("invalid_input", "credential_or_endpoint_argument")
            if inputs and key.lower() in {"limit", "pagesize", "page_size", "count", "size"}:
                if type(child) is not int or not 1 <= child <= 100:
                    raise _Fault("invalid_input", "request_size_limit")
            if inputs and key.lower() in {"page", "offset"}:
                if type(child) is not int or not 0 <= child <= 100:
                    raise _Fault("invalid_input", "pagination_argument_limit")
            if inputs and key.lower() in {"symbol", "symbols", "ticker", "tickers"}:
                symbols = child if isinstance(child, list) else str(child).split(",")
                if len(symbols) > 10 or any(not re.fullmatch(r"[A-Za-z0-9.^:_/-]{1,32}", str(s)) for s in symbols):
                    raise _Fault("invalid_input", "symbol_limit")
            _check_tree(child, inputs=inputs, depth=depth + 1)
    elif isinstance(value, list):
        if inputs and len(value) > 100:
            raise _Fault("invalid_input", "array_limit")
        for child in value:
            _check_tree(child, inputs=inputs, depth=depth + 1)
    elif isinstance(value, str):
        if inputs and (len(value) > 2048 or re.search(r"(?i)(?:https?://|\bapikey\s*=)", value)):
            raise _Fault("invalid_input", "string_or_endpoint_limit")
    elif type(value) is float and not math.isfinite(value):
        raise _Fault("invalid_input", "non_finite_number")
    elif value is not None and type(value) not in (bool, int, float):
        raise _Fault("invalid_input", "non_json_value")


def _read_only(tool):
    name = tool.get("name", "")
    words = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    if not _NAME.fullmatch(name) or _UNSAFE_TOOL.search(words):
        return False
    annotations = tool.get("annotations") or {}
    if annotations.get("readOnlyHint") is False or annotations.get("destructiveHint") is True:
        return False
    return annotations.get("readOnlyHint") is True or bool(_READ_DESCRIPTION.match(tool.get("description") or "")) or bool(_RESEARCH_FAMILY.search(words))


def _validate_selector(tool, arguments):
    """FMP category tools expose a discovered enum, not an arbitrary URL.

    Actual FMP descriptions document endpoint-specific required fields as
    ``- quote (symbol*): ...`` although the category schema requires only
    endpoint. Enforce those explicit markers without inventing defaults.
    """
    if "endpoint" not in arguments:
        return
    selector = arguments["endpoint"]
    prop = tool["inputSchema"].get("properties", {}).get("endpoint", {})
    if not isinstance(prop, dict) or prop.get("type") != "string" or selector not in prop.get("enum", []):
        raise _Fault("invalid_input", "endpoint_not_in_discovered_enum")
    if not _SELECTOR.fullmatch(selector) or _BULK_SELECTOR.search(selector):
        raise _Fault("invalid_input", "bulk_or_arbitrary_endpoint")
    line = re.search(r"(?m)^\s*-\s*" + re.escape(selector) + r"\s*\(([^)\n]*)\)\s*:", tool.get("description") or "")
    if line:
        for required in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\*", line.group(1)):
            if required not in arguments or arguments[required] in (None, "", []):
                raise _Fault("invalid_input", "endpoint_required_argument_missing")


def _safe_pattern(pattern):
    """A small linear/bounded regex subset; Python re can otherwise hold the GIL.

    No groups, alternation, assertions, backreferences or multiple variable
    repeats. Repeated patterns must be anchored. This applies to input *and*
    output schemas before the SDK gets a chance to validate a tool result.
    """
    if not isinstance(pattern, str) or len(pattern) > 256:
        raise _Fault("unavailable", "unsupported_schema_pattern")
    index, variable, repeated = 0, 0, False
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 1
            if index >= len(pattern) or pattern[index].isdigit() or pattern[index] in "gkNpP":
                raise _Fault("unavailable", "unsupported_schema_pattern")
        elif char == "[":
            index += 1
            while index < len(pattern) and pattern[index] != "]":
                if pattern[index] == "\\":
                    index += 1
                index += 1
            if index >= len(pattern):
                raise _Fault("unavailable", "unsupported_schema_pattern")
        elif char in "()|":
            raise _Fault("unavailable", "unsupported_schema_pattern")
        elif char in "*+?":
            variable += 1
            repeated = True
        elif char == "{":
            end = pattern.find("}", index)
            bounds = pattern[index + 1:end] if end >= 0 else ""
            if not re.fullmatch(r"\d{1,3}(?:,\d{0,3})?", bounds):
                raise _Fault("unavailable", "unsupported_schema_pattern")
            if any(int(n) > 256 for n in bounds.split(",") if n):
                raise _Fault("unavailable", "unsupported_schema_pattern")
            variable += int("," in bounds)
            repeated = True
            index = end
        index += 1
    if variable > 1 or (repeated and not (pattern.startswith("^") and pattern.endswith("$"))):
        raise _Fault("unavailable", "unsupported_schema_pattern")
    try:
        re.compile(pattern)
    except re.error:
        raise _Fault("unavailable", "unsupported_schema_pattern") from None


def _schema_validator(schema):
    """Validate the supported schema subset, with bounded regexes/local refs."""
    from jsonschema.validators import validator_for
    from jsonschema import FormatChecker

    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise _Fault("unavailable", "unsupported_tool_schema")
    if len(_json_bytes(schema)) > 65536:
        raise _Fault("unavailable", "schema_limit")

    visited = 0

    def walk(node, active=(), depth=0):
        nonlocal visited
        visited += 1
        if visited > 2048:
            raise _Fault("unavailable", "schema_complexity_limit")
        if depth > 32:
            raise _Fault("unavailable", "schema_depth_limit")
        if isinstance(node, dict):
            if "pattern" in node:
                _safe_pattern(node["pattern"])
            for pattern in node.get("patternProperties", {}):
                _safe_pattern(pattern)
            if any(k in node for k in ("$id", "$recursiveRef", "$dynamicRef")):
                raise _Fault("unavailable", "unsupported_schema_reference")
            ref = node.get("$ref")
            if ref is not None:
                if not isinstance(ref, str) or not ref.startswith("#/") or ref in active:
                    raise _Fault("unavailable", "unsupported_schema_reference")
                target = schema
                try:
                    for part in ref[2:].split("/"):
                        target = target[part.replace("~1", "/").replace("~0", "~")]
                except (KeyError, TypeError):
                    raise _Fault("unavailable", "unsupported_schema_reference") from None
                walk(target, (*active, ref), depth + 1)
            for child in node.values():
                walk(child, active, depth + 1)
        elif isinstance(node, list):
            for child in node:
                walk(child, active, depth + 1)

    walk(schema)
    try:
        cls = validator_for(schema)
        cls.check_schema(schema)
        return cls(schema, format_checker=FormatChecker())
    except Exception:
        raise _Fault("unavailable", "invalid_tool_schema") from None


def _error_state(value, *, diagnostic=False):
    """Reject provider errors even when wrapped in successful MCP results."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in ("{", "["):
            try:
                return _error_state(json.loads(stripped), diagnostic=diagnostic)
            except (ValueError, RecursionError):
                return None
        text = stripped.lower()
        if not diagnostic and not text.startswith(("error:", "error message:", "internal server error")):
            return None
        if re.search(r"(?:invalid|missing|unauthorized|incorrect).{0,40}(?:api.?key|credential)|unauthorized", text):
            return "auth"
        if re.search(r"rate.?limit|too many requests|limit (?:reach|exceed)", text):
            return "rate_limited"
        if re.search(r"forbidden|access denied|subscription required|premium (?:endpoint|query)|upgrade your", text):
            return "forbidden"
        if re.search(r"timed? ?out|timeout", text):
            return "timeout"
        if text.startswith(("error:", "error message:", "internal server error")):
            return "unavailable"
    elif isinstance(value, dict):
        lowered = {str(k).lower().replace("_", " "): v for k, v in value.items()}
        if lowered.get("success") is False or lowered.get("status") in ("error", "failed"):
            return _error_state(str(lowered.get("message", "")), diagnostic=True) or "unavailable"
        for key in ("error", "error message", "errormessage", "errors"):
            if lowered.get(key):
                return _error_state(lowered[key], diagnostic=True) or "unavailable"
        for key in ("data", "result"):
            if key in value:
                state = _error_state(value[key], diagnostic=diagnostic)
                if state:
                    return state
    elif isinstance(value, list):
        for child in value:
            state = _error_state(child, diagnostic=diagnostic)
            if state:
                return state
    return None


class _QuietSdk(logging.Filter):
    def filter(self, record):
        return not record.threadName.startswith("drf-fmp-")


_QUIET = _QuietSdk()


class FmpMcpClient:
    """Thread-safe synchronous facade. ``ok`` is the only success state.

    Results are JSON copies, with credential redaction applied before return.
    Authentication and rate-limit errors open this client's circuit. Forbidden
    responses suppress only the same operation/request, not unrelated tools.
    (Create a new client explicitly to try again.) close() is idempotent and
    cancels active work without waiting beyond its original deadline.
    """

    def __init__(self, env=None, transport=None):
        values = dict(os.environ if env is None else env)
        self._key = values.get("FMP_API_KEY", "")
        self._transport = transport
        self._lock = threading.Lock()
        self._active = None
        self._closed = False
        self._attempts = 0
        self._circuit = None
        self._denials = {}
        self._tools = None
        self._config_error = None
        self._enabled = configured(values)
        try:
            mode = str(values.get("FMP_ENABLED", "true")).strip().lower()
            if mode not in _TRUE | _FALSE:
                raise ValueError
            if not isinstance(self._key, str) or len(self._key) > 512 or any(ord(c) < 32 for c in self._key):
                raise ValueError
            self._key = self._key.strip()
            for attr, name, default, maximum, integral in (
                ("_timeout", "FMP_TIMEOUT_SECONDS", 20, 60, False),
                ("_max_calls", "FMP_MAX_CALLS", 12, 50, True),
                ("_max_bytes", "FMP_MAX_RESPONSE_BYTES", 524288, 2097152, True),
                ("_max_pages", "FMP_MAX_TOOL_PAGES", 8, 20, True),
                ("_max_tools", "FMP_MAX_TOOLS", 256, 512, True),
            ):
                raw = values.get(name, default)
                if isinstance(raw, bool):
                    raise ValueError
                number = float(raw)
                if not math.isfinite(number) or not 0 < number <= maximum or (integral and not number.is_integer()):
                    raise ValueError
                setattr(self, attr, int(number) if integral else number)
        except (ValueError, TypeError, OverflowError):
            self._config_error = _Fault("invalid_input", "invalid_configuration")
        self._secrets = tuple(sorted({self._key, quote(self._key, safe=""), quote_plus(self._key)} - {""}, key=len, reverse=True)) if isinstance(self._key, str) else ()

    def sanitize(self, value):
        """Return a redacted JSON copy; ordinary dates, units and URLs survive."""
        if isinstance(value, str):
            for secret in self._secrets:
                value = value.replace(secret, "[REDACTED]")
            return _URL_SECRET.sub(r"\1[REDACTED]", value)
        if isinstance(value, dict):
            return {self.sanitize(str(k)): "[REDACTED]" if _CREDENTIAL.fullmatch(str(k)) else self.sanitize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.sanitize(v) for v in value]
        return value

    def _envelope(self, state="ok", reason="", **payload):
        return self.sanitize({"provider": "fmp", "status": {"state": state, "reason": reason},
                              "retrieved_at": datetime.now(timezone.utc).isoformat(),
                              "source_url": SOURCE_URL, **payload})

    def discover(self, query="", *, deadline=None):
        return self._run("discover", query, None, deadline)

    def call(self, tool, arguments, *, deadline=None):
        return self._run("call", tool, arguments, deadline)

    def _run(self, operation, name, arguments, deadline):
        fallback = {"tools": []} if operation == "discover" else {}
        try:
            if self._config_error:
                raise self._config_error
            if not self._enabled:
                raise _Fault("disabled", "disabled_or_missing_api_key")
            end = time.monotonic() + self._timeout
            if deadline is not None:
                if type(deadline) not in (int, float) or not math.isfinite(deadline):
                    raise _Fault("invalid_input", "invalid_deadline")
                end = min(end, deadline)
            if time.monotonic() >= end:
                raise _Fault("timeout", "deadline_exhausted")
            if not isinstance(name, str) or len(name) > (512 if operation == "discover" else 128):
                raise _Fault("invalid_input", "invalid_query_or_tool")
            if operation == "call":
                if not _NAME.fullmatch(name) or not isinstance(arguments, dict):
                    raise _Fault("invalid_input", "invalid_tool_or_arguments")
                _check_tree(arguments, inputs=True)
                if len(_json_bytes(arguments)) > 16384 or self._key in _json_bytes(arguments).decode():
                    raise _Fault("invalid_input", "argument_limit_or_credential")
                arguments = copy.deepcopy(arguments)
            request_key = (operation,) if operation == "discover" else (operation, name, json.dumps(arguments, sort_keys=True, allow_nan=False))
            with self._lock:
                if self._closed:
                    raise _Fault("unavailable", "client_closed")
                if self._circuit:
                    raise self._circuit
                if request_key in self._denials:
                    raise self._denials[request_key]
                if self._active is not None:
                    raise _Fault("unavailable", "operation_in_progress")
                if operation == "discover" and self._tools is not None:
                    return self._discovery_result(self._tools, name)
                if self._attempts >= self._max_calls:
                    raise _Fault("rate_limited", "client_call_cap")
                self._attempts += 1
                job = {"done": threading.Event(), "end": end, "loop": None, "task": None, "cancel": False, "request_key": request_key}
                self._active = job
            context = contextvars.copy_context()
            thread = threading.Thread(target=context.run, args=(self._worker, job, operation, name, arguments), name="drf-fmp-operation", daemon=True)
            thread.start()
            if not job["done"].wait(max(0, end - time.monotonic())):
                self._cancel(job)
                raise _Fault("timeout", "deadline_exhausted")
            if "fault" in job:
                raise job["fault"]
            return job["result"]
        except _Fault as fault:
            return self._envelope(fault.state, fault.reason, **fallback)
        except Exception:
            return self._envelope("unavailable", "client_failure", **fallback)

    def _discovery_result(self, tools, query):
        words = re.findall(r"\w+", query.lower())
        ranked = []
        for index, tool in enumerate(tools):
            name = tool["name"].lower()
            description = (tool.get("description") or "").lower()
            score = sum((4 if word in name else 0) + (1 if word in description else 0) for word in words)
            if not words or score:
                ranked.append((-score, index, tool))
        ranked.sort(key=lambda entry: entry[:2])
        return self._envelope(tools=copy.deepcopy([entry[2] for entry in ranked[:8]]),
                              matched_total=len(ranked), returned_count=min(len(ranked), 8), truncated=len(ranked) > 8)

    def _cancel(self, job):
        job["cancel"] = True
        loop, task = job["loop"], job["task"]
        if loop is not None and task is not None:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass

    def close(self):
        with self._lock:
            self._closed = True
            job = self._active
        if job:
            self._cancel(job)
            job["done"].wait(max(0, min(0.1, job["end"] - time.monotonic())))

    def _worker(self, job, operation, name, arguments):
        # Own the loop explicitly: asyncio.run() can wait without a deadline for
        # executor shutdown (DNS). The caller's hard bound also covers imports.
        loop = asyncio.new_event_loop()
        job["loop"] = loop
        try:
            task = loop.create_task(self._execute(job, operation, name, arguments))
            job["task"] = task
            if job["cancel"]:
                task.cancel()
            job["result"] = loop.run_until_complete(task)
        except BaseException as exc:
            fault = exc if isinstance(exc, _Fault) else _Fault("timeout" if isinstance(exc, (TimeoutError, asyncio.CancelledError)) else "unavailable", "deadline_exhausted" if isinstance(exc, (TimeoutError, asyncio.CancelledError)) else "transport_failure")
            job["fault"] = fault
            if fault.state in {"auth", "rate_limited"}:
                self._circuit = fault
            elif fault.state == "forbidden":
                self._denials[job["request_key"]] = fault
        finally:
            loop.close()
            with self._lock:
                self._active = None
            job["done"].set()

    async def _execute(self, job, operation, name, arguments):
        import anyio
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        # Suppress SDK/HTTP messages in our worker only: the SDK logs full URLs,
        # session IDs and provider exception text. Other clients keep logging.
        for logger_name in tuple(logging.Logger.manager.loggerDict):
            if logger_name.split(".", 1)[0] in {"mcp", "httpx", "httpcore", "asyncio"}:
                logging.getLogger(logger_name).addFilter(_QUIET)
        # mcp.shared.session also emits root logging.warning() for malformed
        # server notifications. Handler filters cover later-created HTTP loggers.
        root_logger = logging.getLogger()
        root_logger.addFilter(_QUIET)
        for handler in root_logger.handlers:
            handler.addFilter(_QUIET)
        if logging.lastResort is not None:
            logging.lastResort.addFilter(_QUIET)
        end = job["end"]
        remaining = end - time.monotonic()
        if remaining <= 0 or job["cancel"]:
            raise _Fault("timeout", "deadline_exhausted")
        url = SOURCE_URL + "?" + urlencode({"apikey": self._key})
        base = self._transport() if callable(self._transport) else self._transport
        if base is None:
            base = httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        owner = self

        class BoundedTransport(httpx.AsyncBaseTransport):
            total = 0
            posts = 0
            failure = None

            def fail(self, state, reason):
                if self.failure is None:
                    self.failure = _Fault(state, reason)
                # Some SDK stream-reader failures are logged rather than routed
                # to the outstanding initialize future. Cancel its owner so a
                # rejected stream terminates promptly with this fixed reason.
                job["loop"].call_soon(job["task"].cancel)
                raise self.failure

            async def handle_async_request(self, request):
                if time.monotonic() >= end or job["cancel"]:
                    self.fail("timeout", "deadline_exhausted")
                if str(request.url) != url:
                    self.fail("unavailable", "endpoint_rejected")
                # An optional server notification stream is unnecessary for
                # request/response research. Refuse locally, so no GET reconnect.
                if request.method == "GET":
                    return httpx.Response(405, request=request)
                if request.method not in {"POST", "DELETE"}:
                    self.fail("unavailable", "method_rejected")
                self.posts += 1
                if self.posts > owner._max_pages + 5:
                    self.fail("unavailable", "protocol_request_cap")
                try:
                    _admit_network("search" if operation == "discover" else "fetch")
                except _Fault as fault:
                    self.fail(fault.state, fault.reason)
                if time.monotonic() >= end or job["cancel"]:
                    self.fail("timeout", "deadline_exhausted")
                try:
                    response = await base.handle_async_request(request)
                    code = response.status_code
                    if code >= 300 and not (request.method == "DELETE" and code == 405):
                        await response.aclose()
                        self.fail({401: "auth", 403: "forbidden", 402: "forbidden", 429: "rate_limited", 408: "timeout", 504: "timeout"}.get(code, "unavailable"), "http_" + str(code))
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        await response.aclose()
                        self.fail("unavailable", "encoded_response_rejected")
                    length = response.headers.get("content-length")
                    if length and (not length.isdigit() or int(length) > owner._max_bytes - self.total):
                        await response.aclose()
                        self.fail("unavailable", "response_size_limit")
                    outer = self
                    original = response.stream

                    class LimitedStream(httpx.AsyncByteStream):
                        async def __aiter__(self):
                            async for chunk in original:
                                outer.total += len(chunk)
                                if outer.total > owner._max_bytes:
                                    outer.fail("unavailable", "response_size_limit")
                                if time.monotonic() >= end:
                                    outer.fail("timeout", "deadline_exhausted")
                                yield chunk

                        async def aclose(self):
                            await original.aclose()

                    response.stream = LimitedStream()
                    return response
                except httpx.TimeoutException:
                    self.fail("timeout", "transport_timeout")

            async def aclose(self):
                await base.aclose()

        bounded = BoundedTransport()
        try:
            # anyio cancellation encloses both SDK context exits and transport
            # close. The synchronous watchdog bounds uncooperative test adapters.
            with anyio.fail_after(remaining):
                async with httpx.AsyncClient(transport=bounded, trust_env=False, follow_redirects=False, max_redirects=0,
                                            timeout=remaining, headers={"Accept-Encoding": "identity"}) as http:
                    async with streamable_http_client(url, http_client=http, terminate_on_close=True) as streams:
                        async with ClientSession(streams[0], streams[1], read_timeout_seconds=timedelta(seconds=remaining)) as session:
                            await session.initialize()
                            tools = await self._list_tools(session)
                            if operation == "discover":
                                result = self._discovery_result(tools, name)
                            else:
                                tool = next((item for item in tools if item["name"] == name), None)
                                if tool is None:
                                    raise _Fault("invalid_input", "unknown_or_non_read_only_tool")
                                validator = _schema_validator(tool["inputSchema"])
                                if not validator.is_valid(arguments):
                                    raise _Fault("invalid_input", "arguments_do_not_match_schema")
                                _validate_selector(tool, arguments)
                                raw = (await session.call_tool(name, arguments)).model_dump(mode="json", by_alias=True, exclude_none=True, exclude_unset=True)
                                try:
                                    raw_bytes = _json_bytes(raw)
                                except _Fault:
                                    raise _Fault("unavailable", "invalid_response_value") from None
                                if len(raw_bytes) > self._max_bytes:
                                    raise _Fault("unavailable", "response_size_limit")
                                state = _error_state(raw.get("structuredContent"), diagnostic=bool(raw.get("isError")))
                                for block in raw.get("content", []):
                                    state = state or _error_state(block.get("text", ""), diagnostic=bool(raw.get("isError")))
                                if raw.get("isError") or state:
                                    raise _Fault(state or "unavailable", "provider_error")
                                # MCP permits extension fields. They must not
                                # replace our provider/status/provenance envelope.
                                payload = {key: raw[key] for key in ("content", "structuredContent", "isError", "_meta") if key in raw}
                                result = self._envelope(tool=name, data=raw.get("structuredContent", raw.get("content", [])), **payload)
                if bounded.failure:
                    raise bounded.failure
                self._tools = tools
                return result
        except BaseException as exc:
            if bounded.failure:
                raise bounded.failure from None
            if isinstance(exc, (_Fault, TimeoutError, asyncio.CancelledError)):
                raise
            # AnyIO wraps task failures in ExceptionGroup; retain only our fixed
            # error codes, never SDK messages, URL-bearing traces or response text.
            pending = [exc]
            while pending:
                error = pending.pop()
                if isinstance(error, _Fault):
                    raise error from None
                remote = getattr(error, "error", None)
                if remote is not None:
                    state = _error_state(getattr(remote, "message", ""), diagnostic=True)
                    raise _Fault(state or "unavailable", "provider_rpc_error") from None
                pending.extend(getattr(error, "exceptions", ()))
            raise _Fault("unavailable", "protocol_or_transport_failure") from None

    async def _list_tools(self, session):
        from mcp.types import PaginatedRequestParams

        tools, names, cursors = [], set(), set()
        cursor = None
        total = 0
        for _ in range(self._max_pages):
            response = await session.list_tools(params=PaginatedRequestParams(cursor=cursor))
            page = response.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_unset=True)
            total += len(page["tools"])
            if total > self._max_tools:
                raise _Fault("unavailable", "tool_count_limit")
            for tool in page["tools"]:
                name = tool["name"]
                if name in names:
                    raise _Fault("unavailable", "duplicate_tool")
                names.add(name)
                if _read_only(tool):
                    _schema_validator(tool["inputSchema"])
                    if tool.get("outputSchema") is not None:
                        _schema_validator(tool["outputSchema"])
                    tools.append(tool)
            cursor = page.get("nextCursor")
            if cursor is None:
                return tools
            if not isinstance(cursor, str) or not cursor or len(cursor) > 2048 or cursor in cursors:
                raise _Fault("unavailable", "invalid_pagination_cursor")
            cursors.add(cursor)
        raise _Fault("unavailable", "tool_page_limit")
