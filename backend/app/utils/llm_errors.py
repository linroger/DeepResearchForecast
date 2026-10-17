"""Provider-agnostic description of LLM call failures (pure; no SDK imports).

Shared by ``app.utils.llm_client`` (failover classification and logging) and by the
simulation's world update / decision steps, whose failure records must say *what*
the provider rejected — exception class, HTTP status, provider error code,
content-filter classification and a bounded message snippet — instead of only
the exception type (the live run ``sim_d6ebcc77e22d`` recorded
``llm error: BadRequestError`` for two Zhipu content-filter rejections, which
hid the HTTP 400 / code 1301 cause).

The helpers inspect the exception duck-typed (``status_code``, ``body``,
``code``, ``response`` and the message text), so they work for the OpenAI SDK
error classes, ``RuntimeError`` wrappers from CLI providers and stub exceptions
in tests alike.  ``describe_llm_error`` also surfaces the failover note that
``LLMClient.chat`` attaches when the configured fallback provider could not
take the call over (``BaseException.add_note``).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

# Provider-specific content-moderation rejections that arrive as a plain HTTP 400.
# Zhipu / GLM 1301: 系统检测到输入或生成内容可能包含不安全或敏感内容.
CONTENT_FILTER_CODES = frozenset({"1301", "content_filter", "new_sensitive"})
_CONTENT_FILTER_MARKERS = (
    "new_sensitive", "contentfilter", "content_filter", "content filter", "content-filter",
    "unprocessable", "sensitive content", "敏感内容", "内容审查",
)
# 4xx statuses that are worth retrying (timeouts / rate limits); every other 4xx is a
# deterministic rejection of this request.
_RETRYABLE_4XX = frozenset({408, 425, 429})
_HTTP_STATUS_RE = re.compile(r"(?i)(?:error code|status(?: code)?|http)[:\s]+(\d{3})\b")
# ``'code': '1301'`` / ``"code": "content_filter"`` inside a serialised provider body; the
# quoted key excludes the SDK's own ``Error code: 400`` prefix.
_BODY_CODE_RE = re.compile(r"""['"]code['"]\s*:\s*['"]?([A-Za-z0-9_.-]{1,32})""")
_QUOTA_MARKERS = ("rate_limit", "rate limit", "quota", "usage limit", "insufficient balance", "429")
_AUTH_MARKERS = ("authenticationerror", "invalid authentication", "failed to authenticate", "401")

DEFAULT_SNIPPET_CHARS = 160


def _message(exc: BaseException) -> str:
    try:
        text = str(exc)
    except Exception:  # noqa: BLE001 — a broken __str__ must not mask the real failure
        text = ""
    if not text:
        text = repr(exc)
    return " ".join(text.split())


def error_status(exc: BaseException) -> Optional[int]:
    """HTTP status of a provider error (``status_code`` attribute, response or message)."""
    for candidate in (getattr(exc, "status_code", None),
                      getattr(getattr(exc, "response", None), "status_code", None)):
        try:
            if candidate is not None and not isinstance(candidate, bool):
                value = int(candidate)
                if 100 <= value <= 599:
                    return value
        except (TypeError, ValueError):
            continue
    match = _HTTP_STATUS_RE.search(_message(exc))
    if match:
        value = int(match.group(1))
        if 100 <= value <= 599:
            return value
    return None


def error_code(exc: BaseException) -> str:
    """Provider error code (``body.error.code`` for OpenAI-style bodies, MiniMax
    ``base_resp.status_code``, the SDK ``code`` attribute or the serialised body)."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("code") not in (None, ""):
            return str(err["code"])
        if body.get("code") not in (None, ""):
            return str(body["code"])
        base = body.get("base_resp")
        if isinstance(base, dict) and base.get("status_code") not in (None, "", 0):
            return str(base["status_code"])
    code = getattr(exc, "code", None)
    if code not in (None, "") and not isinstance(code, bool):
        return str(code)
    match = _BODY_CODE_RE.search(_message(exc))
    return match.group(1) if match else ""


def is_content_filter_error(exc: BaseException) -> bool:
    """Content-moderation rejection of the request (MiniMax 422 new_sensitive, Zhipu 400/1301,
    OpenAI ``content_filter`` …): retrying the same provider cannot help."""
    low = _message(exc).lower()
    if any(marker in low for marker in _CONTENT_FILTER_MARKERS):
        return True
    if " 422" in low or "code: 422" in low or error_status(exc) == 422:
        return True
    if error_code(exc).lower() in CONTENT_FILTER_CODES:
        return True
    body = getattr(exc, "body", None)
    return isinstance(body, dict) and "contentFilter" in body


def is_non_retryable_request_error(exc: BaseException) -> bool:
    """A deterministic 4xx rejection (content filter, bad request, auth, not found …) —
    the one error class where only a different provider can still answer."""
    if is_content_filter_error(exc):
        return True
    status = error_status(exc)
    return status is not None and 400 <= status <= 499 and status not in _RETRYABLE_4XX


def classify_llm_error(exc: BaseException) -> str:
    """Short failure class for logs and records: ``content filter`` / ``quota/rate limit`` /
    ``authentication`` / ``bad request`` / ``""`` (unclassified)."""
    if is_content_filter_error(exc):
        return "content filter"
    status = error_status(exc)
    low = _message(exc).lower()
    if status == 429 or any(marker in low for marker in _QUOTA_MARKERS):
        return "quota/rate limit"
    if status in (401, 403) or any(marker in low for marker in _AUTH_MARKERS):
        return "authentication"
    if status is not None and 400 <= status <= 499:
        return "bad request"
    return ""


def failover_notes(exc: BaseException) -> str:
    """Notes attached by ``LLMClient.chat`` about the fallback provider (``add_note``)."""
    notes = getattr(exc, "__notes__", None)
    if not isinstance(notes, list):
        return ""
    return "; ".join(" ".join(str(n).split()) for n in notes if str(n).strip())


def llm_error_details(exc: BaseException, *, max_chars: int = DEFAULT_SNIPPET_CHARS) -> Dict[str, Any]:
    """Structured view: ``{type, status, code, kind, failover, message}``."""
    return {
        "type": type(exc).__name__,
        "status": error_status(exc),
        "code": error_code(exc),
        "kind": classify_llm_error(exc),
        "failover": failover_notes(exc),
        "message": _message(exc)[: max(16, int(max_chars))],
    }


def describe_llm_error(exc: BaseException, *, max_chars: int = DEFAULT_SNIPPET_CHARS) -> str:
    """One bounded line for failure records, e.g.
    ``BadRequestError (HTTP 400, provider code 1301, content filter; fallback: not configured):
    Error code: 400 - {'contentFilter': …}``."""
    d = llm_error_details(exc, max_chars=max_chars)
    parts = []
    if d["status"] is not None:
        parts.append(f"HTTP {d['status']}")
    if d["code"]:
        parts.append(f"provider code {d['code']}")
    if d["kind"]:
        parts.append(d["kind"])
    head = d["type"]
    if parts:
        head += " (" + ", ".join(parts) + (f"; {d['failover']}" if d["failover"] else "") + ")"
    elif d["failover"]:
        head += f" ({d['failover']})"
    return f"{head}: {d['message']}" if d["message"] else head
