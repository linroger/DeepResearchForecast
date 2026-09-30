"""
LLM客户端封装

支持三种提供方（由 Config.LLM_PROVIDER 决定，默认 claude-cli）：
  - claude-cli: 通过本机 `claude` CLI 调用（Claude Code 订阅，无需 API Key）
  - codex-cli:  通过本机 `codex` CLI 调用（Codex 订阅，无需 API Key）
  - openai:     OpenAI 兼容 API（需要 LLM_API_KEY），保留作为回退

对外接口统一为 chat() / chat_json()，调用方无需关心底层提供方。
"""

import contextvars
import json
import os
import re
import subprocess
import threading
import time
from contextlib import contextmanager
from typing import Optional, Dict, Any, List, Tuple

from ..config import Config
from .llm_text import flatten_content, has_dangling_think, normalize_finish_reason, strip_think
from .logger import get_logger
# INFRA-8: claude_cli_model_arg lives with the other model-provenance helpers; it stays
# importable from here (backbone_sensitivity, eval_forecast_quality).
from .model_provenance import (
    claude_cli_model_arg,
    effective_model_label,
    served_models_from_claude_envelope,
)
from .provider_overrides import (
    FALLBACK_REASONING_EFFORTS,
    openai_compat_request_overrides,
    provider_temperature,
)

logger = get_logger('mirofish.llm_client')

# 单次 CLI 调用超时（秒）。从 300 降到 180 以便在模拟中卡住的 agent 调用更快释放并发槽；
# 仍足够长，可容纳报告章节这类长文生成。可用 LLM_CLI_TIMEOUT 覆盖（模拟密集场景可设 120）。
CLI_TIMEOUT = int(os.environ.get('LLM_CLI_TIMEOUT', '180'))

CLI_PROVIDERS = ('claude-cli', 'codex-cli')
# OpenAI 兼容的 HTTP 提供方（直接从 PROVIDER_META 的 openai_compat 标记派生，
# 新增提供方只需在 config.py 改一处：openai / kimi / minimax / deepseek / qwen / glm）
OPENAI_COMPATIBLE_PROVIDERS = tuple(
    pid for pid, meta in Config.PROVIDER_META.items() if meta.get('openai_compat')
) + (
    # Fallback-only identity: Antigravity is served through Quotio's local
    # OpenAI-compatible adapter. Keep it out of Config.PROVIDER_META so it does
    # not appear as a primary-provider setting or broaden runtime switching.
    'antigravity',
)

# CLI 调用的瞬时失败重试配置
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # 秒
RETRY_AFTER_CAP = 30.0  # 秒：尊重 429 的 Retry-After，但封顶避免硬额度耗尽时长时间挂起

# OpenAI 兼容提供方（kimi/minimax/…）的瞬时 API 错误：429 限流、超时、连接抖动、5xx。
# 这些异常默认不是 RuntimeError，历史上会绕过 chat() 的退避重试直达上层（报告章节因此
# 一遇 429 即降级为占位符 —— 见 2026-06-21 失败）。在此显式纳入退避重试。
# 注意：不含 BadRequestError(400)/AuthenticationError(401)/NotFoundError(404) —— 这些是
# 确定性错误，重试无益，应快速失败。openai 在极简环境可能缺失，故 import 容错。
try:
    import openai as _openai  # noqa: F401
    _RETRYABLE_API_ERRORS = (
        _openai.RateLimitError,
        _openai.APITimeoutError,
        _openai.APIConnectionError,
        _openai.InternalServerError,
    )
except Exception:  # noqa: BLE001 — openai 不可导入时退化为仅重试 RuntimeError
    _RETRYABLE_API_ERRORS = ()


# Per-context request timeout (seconds) for chat()'s OpenAI-compatible calls.  The
# client-wide 600 s read timeout suits long report sections, but a translation call
# that sits on a dead HTTP/2 stream should be retried in minutes, not after 10.
_CALL_TIMEOUT_S: "contextvars.ContextVar[Optional[float]]" = contextvars.ContextVar(
    "llm_call_timeout_s", default=None
)


@contextmanager
def llm_call_timeout(seconds: Optional[float]):
    """Bound every chat() request in this context (and copied contexts) to ``seconds``.

    A timeout raises ``APITimeoutError``, which chat() retries with backoff.
    ``None`` / 0 keeps the client default.
    """
    try:
        value = float(seconds) if seconds else None
    except (TypeError, ValueError):
        value = None
    token = _CALL_TIMEOUT_S.set(value if value and value > 0 else None)
    try:
        yield
    finally:
        _CALL_TIMEOUT_S.reset(token)


def _err_brief(exc: Exception) -> str:
    """Short, classified error description for failover logging (S9)."""
    s = str(exc)
    low = s.lower()
    if "new_sensitive" in low or "content" in low and "filter" in low:
        kind = "content-filter(422)"
    elif "429" in s or "rate_limit" in low or "quota" in low or "usage limit" in low:
        kind = "quota/rate-limit(429)"
    else:
        kind = type(exc).__name__
    return f"{kind}: {s[:160]}"


# QUALITY-OPT (live-surfaced): content-filter CIRCUIT BREAKER. When a provider blanket-filters a
# topic (MiniMax returned 422 new_sensitive on ~100% of a geopolitical run → 1585 futile primary
# attempts that flooded the single claude-cli fallback and exhausted it), trip a breaker after K
# consecutive 422s and route straight to the fallback for a cooldown — skipping the doomed primary
# call entirely. Halves latency + spares the fallback from a needless 2× call volume.
_CB_STATE: Dict[str, Dict[str, float]] = {}
# 2026-07-03 live-surfaced: graphiti 图谱阶段用 GRAPH_LLM_EXECUTOR_WORKERS/
# GRAPHITI_MAX_COROUTINES 并发调用 chat()，多线程下 `st["consec"] = st.get(...) + 1`
# 是无锁的「读-改-写」——并发 422 会互相踩掉彼此的自增（经典 lost-update），导致一次真实
# forecast run 里连续 30 次 minimax content-filter 失败也从未凑够 _CB_THRESHOLD=5 触发熔断，
# 每次都白白多付一次注定失败的 minimax 往返延迟才转回退。用一把锁保护 _CB_STATE 的全部读改写。
_CB_LOCK = threading.Lock()
try:
    _CB_THRESHOLD = max(1, int(os.environ.get("LLM_CB_422_THRESHOLD", "5") or "5"))
except ValueError:
    _CB_THRESHOLD = 5
try:
    _CB_COOLDOWN_S = float(os.environ.get("LLM_CB_COOLDOWN_S", "300") or "300")
except ValueError:
    _CB_COOLDOWN_S = 300.0


def _is_content_filter(exc: Exception) -> bool:
    s = str(exc).lower()
    return ("new_sensitive" in s or "unprocessable" in s
            or ("content" in s and "filter" in s) or " 422" in s or "code: 422" in s)


# LLM-3: 429/quota 熔断（与 422 熔断共用 tripped_until）。MiniMax 硬配额耗尽后 ~1h 内每次调用
# 仍会烧 3 次退避重试（≥6s）才失败转移——SIM 阶段的调用洪峰会把该延迟放大数百倍。连续配额类
# 失败达阈值后同样进入冷却、直连回退提供方。阈值比 422 高（限流可能是瞬时的，配额耗尽才持续）。
try:
    _CB_429_THRESHOLD = max(1, int(os.environ.get("LLM_CB_429_THRESHOLD", "8") or "8"))
except ValueError:
    _CB_429_THRESHOLD = 8
try:
    _CB_429_COOLDOWN_S = float(os.environ.get("LLM_CB_429_COOLDOWN_S", "120") or "120")
except ValueError:
    _CB_429_COOLDOWN_S = 120.0


def _is_quota(exc: Exception) -> bool:
    s = str(exc)
    low = s.lower()
    return ("429" in s or "rate_limit" in low or "rate limit" in low
            or "quota" in low or "usage limit" in low)


def _cb_tripped(provider: str) -> bool:
    with _CB_LOCK:
        st = _CB_STATE.get(provider)
        return bool(st and st.get("tripped_until", 0.0) > time.monotonic())


def _cb_record_422(provider: str) -> None:
    with _CB_LOCK:
        st = _CB_STATE.setdefault(provider, {"consec": 0.0, "tripped_until": 0.0})
        st["consec"] = st.get("consec", 0.0) + 1
        if st["consec"] >= _CB_THRESHOLD and st.get("tripped_until", 0.0) <= time.monotonic():
            st["tripped_until"] = time.monotonic() + _CB_COOLDOWN_S
            logger.warning("熔断器：提供方 %s 连续 %d 次内容审查(422)，冷却 %ds，期间直连回退提供方",
                           provider, int(st["consec"]), int(_CB_COOLDOWN_S))


def _cb_record_429(provider: str) -> None:
    """LLM-3: 记一次配额/限流失败；连续达 _CB_429_THRESHOLD 次即冷却（期间直连回退）。"""
    with _CB_LOCK:
        st = _CB_STATE.setdefault(provider, {"consec": 0.0, "tripped_until": 0.0})
        st["consec429"] = st.get("consec429", 0.0) + 1
        if st["consec429"] >= _CB_429_THRESHOLD and st.get("tripped_until", 0.0) <= time.monotonic():
            st["tripped_until"] = time.monotonic() + _CB_429_COOLDOWN_S
            logger.warning("熔断器：提供方 %s 连续 %d 次配额/限流(429)，冷却 %ds，期间直连回退提供方",
                           provider, int(st["consec429"]), int(_CB_429_COOLDOWN_S))


def _cb_reset(provider: str) -> None:
    with _CB_LOCK:
        st = _CB_STATE.get(provider)
        if st:
            st["consec"] = 0.0
            st["consec429"] = 0.0


def circuit_breaker_quiet(provider: str) -> bool:
    """True when ``provider``'s 422/429 circuit breaker holds no failure streak and no cooldown.

    The breaker is process-wide per provider: every chat() of any client of that provider counts
    its failures toward the trip and resets the streaks on success, and a trip decides which
    provider serves every later call. EVAL-11's shadow backbone check reads this so its own
    calls never feed a breaker that a throttled provider is already building toward.
    """
    with _CB_LOCK:
        st = _CB_STATE.get(str(provider or "").lower())
        if not st:
            return True
        return (st.get("consec", 0.0) <= 0 and st.get("consec429", 0.0) <= 0
                and st.get("tripped_until", 0.0) <= time.monotonic())


# LLM-3: 回退提供方的 OpenAI 连接池缓存。此前每次失败转移都重建 LLMClient/OpenAI 客户端
# （每次一个新 httpx 连接池 + TLS 握手）；键=(provider, model, base_url)。只缓存底层 OpenAI
# 客户端（官方文档保证线程安全），LLMClient 实例仍逐调用新建（逐调用元数据见 _CALL_META）。
_FB_OPENAI_CLIENTS: Dict[tuple, Any] = {}
# A deterministic fallback authentication failure is process-scoped, not request-scoped.
# Remember it long enough to keep parallel workers from repeating an expensive doomed CLI/API
# call. A service restart or credential repair naturally clears the cache.
_FB_AUTH_UNAVAILABLE_UNTIL: Dict[tuple, float] = {}
_FB_AUTH_COOLDOWN_S = 900.0


def _is_deterministic_auth_error(exc: Exception) -> bool:
    """Return true for credential failures that retries cannot repair."""
    text = str(exc or "").lower()
    return bool(
        "authenticationerror" in text
        or "invalid authentication credentials" in text
        or "failed to authenticate" in text
        or "api_error_status\":401" in text
        or "api_error_status': 401" in text
        or re.search(r"(?:error|status|code)[^\n]{0,24}\b401\b", text)
    )


def _is_deterministic_invalid_request_error(exc: Exception) -> bool:
    """400-class invalid-request failures (unknown/invalid model, malformed request)
    that retries cannot repair. Observed 2026-07-08: an openai-compatible fallback
    gateway rejecting an inherited primary model name returned 400 'unknown provider
    for model MiniMax-M2' on every failover — unlike 401s these never entered the
    deterministic cooldown and retried forever."""
    if getattr(exc, "status_code", None) == 400:
        return True
    text = str(exc or "").lower()
    return bool(
        "badrequesterror" in text
        or "unknown provider for model" in text
        or "model_not_found" in text
        or "invalid_request_error" in text
        or re.search(r"(?:error|status|code)[^\n]{0,24}\b400\b", text)
    )


# 每个误配置的回退提供方只告警一次（进程级）；并发 chat() 失败转移时避免刷屏。
_FB_MISCONFIG_WARNED: set = set()


def _retry_delay(exc: Exception, attempt: int) -> float:
    """退避时长：默认指数退避；若 429 错误带 Retry-After 头则尊重之（封顶 RETRY_AFTER_CAP）。"""
    base = RETRY_BASE_DELAY * (2 ** attempt)
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers:
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        if retry_after:
            try:
                return min(max(base, float(retry_after)), RETRY_AFTER_CAP)
            except (TypeError, ValueError):
                pass
    return base


# ---------------------------------------------------------------------------
# INFRA-1: typed completion failures and race-free per-call metadata.
# ---------------------------------------------------------------------------
class _CompletionDiagnostics:
    """Diagnostic attributes shared by the typed completion failures below."""

    def __init__(self, message: str, *, finish_reason: str = "unknown",
                 raw_finish_reason: Any = None, usage: Optional[Dict[str, int]] = None,
                 sent_max_tokens: Optional[int] = None, provider: str = "",
                 model: Optional[str] = None) -> None:
        super().__init__(message)
        self.finish_reason = finish_reason
        self.raw_finish_reason = raw_finish_reason
        self.usage = usage
        self.sent_max_tokens = sent_max_tokens
        self.provider = provider
        self.model = model


class EmptyCompletion(_CompletionDiagnostics, RuntimeError):
    """The provider answered but the reply carries no text.

    A RuntimeError, so chat() still retries it and then fails over. The message never carries
    outage vocabulary (quota / rate limit / auth / status-code-like numbers): the pipeline's
    outage breaker (_classify_provider_outage) and _is_quota must not count it as an outage.
    """


class LLMEmptyChoices(_CompletionDiagnostics, RuntimeError):
    """The response has no choices at all (e.g. a MiniMax base_resp error envelope).

    The provider's own error text is kept in the message, so quota/auth wording still reaches
    _is_quota, the 429 breaker and the pipeline outage classifier.

    ``deterministic`` marks an envelope that no retry can repair (see
    _DETERMINISTIC_ENVELOPE_CODES): chat() and chat_with_tools stop retrying at once, as they
    did when such an envelope surfaced as an IndexError, and chat() fails over.
    """

    def __init__(self, message: str, *, deterministic: bool = False, **diagnostics: Any) -> None:
        super().__init__(message, **diagnostics)
        self.deterministic = deterministic


class LLMContentFiltered(_CompletionDiagnostics, Exception):
    """The provider's content filter stopped the reply before any text.

    Deliberately not a RuntimeError: generic RuntimeError handlers (chat()'s transient retry
    loop among them) must not treat a filtered prompt as transient. chat() counts it toward the
    422 breaker and tries the fallback provider once, as for any non-retryable error.
    """


class LLMAbortedCompletion(_CompletionDiagnostics, RuntimeError):
    """The provider aborted the generation (finish_reason 'error') before any text."""


# The DISABLE_THINKING knob that governs each reasoning provider (Config.reasoning_extra_body).
_THINKING_KNOBS = {
    "kimi": "LLM_KIMI_DISABLE_THINKING",
    "minimax": "LLM_MINIMAX_DISABLE_THINKING",
    "deepseek": "LLM_DISABLE_THINKING",
    "qwen": "LLM_DISABLE_THINKING",
    "glm": "LLM_DISABLE_THINKING",
}
# Substrings that DRF's text classifiers read as HTTP status codes (_is_quota matches a bare
# '429'; the auth / invalid-request checks match delimited 401 / 400; ' 422' marks a content
# filter). A max_tokens value or model id containing one is left out of failure messages
# (it stays on the exception's attributes).
_STATUS_LIKE_CODES = ("400", "401", "422", "429")
# MiniMax base_resp status codes that no retry can repair, each mapped to wording DRF's text
# classifiers already recognise. The auth codes read as a 401, so _is_deterministic_auth_error
# stops chat()'s retries, puts a failing fallback into its cooldown and gives the pipeline
# outage classifier 'auth'. Insufficient balance reads as quota (_is_quota: 429 breaker, outage
# 'quota'). Invalid parameters read as a deterministic 400. 2056 (usage limit) is not listed:
# its own text already reads as quota and it stays retryable like every other quota error.
_DETERMINISTIC_ENVELOPE_CODES = {
    1004: "provider auth failure (status 401)",  # login fail / not authorized
    2049: "provider auth failure (status 401)",  # invalid api key
    1008: "provider quota exhausted (insufficient balance)",
    2013: "provider rejected the request parameters (status 400)",
}
# Finish reasons whose reply is complete enough to replay from LLMCache.
_CACHEABLE_FINISH_REASONS = frozenset({"stop", "tool_calls", "unknown"})

# INFRA-2: chat_json repair turn (LLM_JSON_REPAIR_TURN). The miss reasons are named in the
# repair note and in the ValueError; the rejected reply is echoed back at most this many chars.
# An empty echo is replaced by the placeholder: providers such as MiniMax reject an assistant
# turn with empty content (400), and chat() can return '' when LLM_TRANSPORT_STRICT is off.
_JSON_MISS_INVALID = "invalid JSON"
_JSON_MISS_NOT_OBJECT = "not a JSON object"
_JSON_REPAIR_REPLY_CHARS = 4000
_JSON_REPAIR_EMPTY_REPLY = "(empty reply)"
# Passed as _parse_json_response_ex(unparsed=...) so a reply of JSON null (parsed, but not an
# object) is told apart from text that does not parse at all.
_JSON_UNPARSED = object()
_JSON_REPAIR_NOTE = (
    "Your previous reply was not a single valid JSON object ({reason}). Reply again with "
    "exactly ONE complete JSON object that follows the schema requested above - no markdown "
    "fences, no commentary, no truncation."
)

# Per-thread metadata of the last successful call. Report sections and graphiti workers share
# one LLMClient across threads, so per-call state must never live on the instance.
_CALL_META = threading.local()


def _thinking_knob(provider: Optional[str]) -> Optional[str]:
    """Config knob that disables thinking for ``provider``; None when it has none."""
    return _THINKING_KNOBS.get((provider or "").strip().lower())


def _transport_strict() -> bool:
    return bool(getattr(Config, "LLM_TRANSPORT_STRICT", True))


def _is_json_response_format(response_format: Optional[Dict]) -> bool:
    return isinstance(response_format, dict) and response_format.get("type") in ("json_object", "json_schema")


def _status_safe(value: Any) -> bool:
    """True when ``str(value)`` holds none of _STATUS_LIKE_CODES, so a failure message may show it."""
    text = str(value)
    return not any(code in text for code in _STATUS_LIKE_CODES)


def _field(obj: Any, name: str) -> Any:
    """``obj[name]`` for a dict, else ``getattr(obj, name, None)``."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _usage_dict(prompt: int = 0, completion: int = 0, total: Optional[int] = None,
                reasoning: int = 0, cached: int = 0) -> Dict[str, int]:
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion if total is None else total,
        "reasoning_tokens": reasoning,
        "cached_tokens": cached,
    }


def _usage_from_response(response: Any) -> Optional[Dict[str, int]]:
    """Provider-reported usage of an OpenAI-compatible response; None when it reports none."""
    try:
        u = _field(response, "usage")
        if u is None:
            return None
        pt = _as_int(_field(u, "prompt_tokens"))
        ct = _as_int(_field(u, "completion_tokens"))
        return _usage_dict(
            pt, ct,
            total=_as_int(_field(u, "total_tokens")) or pt + ct,
            reasoning=_as_int(_field(_field(u, "completion_tokens_details"), "reasoning_tokens")),
            # DeepSeek reports prompt-cache hits as prompt_cache_hit_tokens.
            cached=_as_int(_field(_field(u, "prompt_tokens_details"), "cached_tokens"))
            or _as_int(_field(u, "prompt_cache_hit_tokens")),
        )
    except Exception:  # noqa: BLE001 — usage is observability; never fail the call over it
        return None


def _cli_envelope_usage(envelope: Any) -> tuple:
    """(usage, served_model) from a Claude CLI JSON result envelope; (None, None) if absent."""
    if not isinstance(envelope, dict):
        return None, None
    try:
        usage = None
        u = envelope.get("usage")
        if isinstance(u, dict):
            fresh = _as_int(u.get("input_tokens"))
            cache_read = _as_int(u.get("cache_read_input_tokens"))
            cache_write = _as_int(u.get("cache_creation_input_tokens"))
            usage = _usage_dict(fresh + cache_read + cache_write, _as_int(u.get("output_tokens")),
                                cached=cache_read)
        served = envelope.get("model") if isinstance(envelope.get("model"), str) else None
        # INFRA-8: every model the envelope's modelUsage reports; the one that produced the
        # most output is recorded as the call's served model.
        served_ids = served_models_from_claude_envelope(envelope)
        if not served and served_ids:
            per_model = envelope["modelUsage"]
            served = max(served_ids, key=lambda name: _as_int(_field(per_model[name], "outputTokens")))
        return usage, served
    except Exception:  # noqa: BLE001 — envelope shape drift must not fail a served call
        return None, None


def _empty_choices_error(response: Any, provider: str, model: Optional[str],
                         usage: Optional[Dict[str, int]]) -> Exception:
    """The typed error for a response without choices, carrying the provider's error envelope
    text (MiniMax base_resp, error). A content-filter envelope (MiniMax 'new_sensitive') gives
    LLMContentFiltered so chat() fails over at once instead of retrying a filtered prompt;
    anything else gives LLMEmptyChoices, marked deterministic (and tagged with classifier
    wording) for the codes in _DETERMINISTIC_ENVELOPE_CODES. The model id appears in the
    message only when it looks like no status code (a '...-0429' id must not read as quota)."""
    details: List[str] = []
    code = None
    try:
        extra = getattr(response, "model_extra", None)
        extra = extra if isinstance(extra, dict) else {}
        base = extra.get("base_resp") or _field(response, "base_resp")
        code, msg = _field(base, "status_code"), _field(base, "status_msg")
        if code not in (None, "") or msg:
            details.append(f"base_resp status_code={code} status_msg={msg}")
        err = extra.get("error") or _field(response, "error")
        if isinstance(err, str) and err:
            details.append(f"error: {err}")
        elif err is not None:
            err_msg, err_code = _field(err, "message"), _field(err, "code")
            if err_msg or err_code:
                details.append(f"error code={err_code} message={err_msg}")
    except Exception:  # noqa: BLE001 — best-effort diagnostics only
        pass
    detail = "; ".join(details)[:400] or "the response carried no error detail"
    source = f"provider={provider}, model={model}" if _status_safe(model) else f"provider={provider}"
    if details and _is_content_filter(Exception(detail)):
        return LLMContentFiltered(
            f"LLM response has no choices: provider content_filter envelope ({source}): {detail}",
            finish_reason="content_filter", usage=usage, provider=provider, model=model,
        )
    rejection = _DETERMINISTIC_ENVELOPE_CODES.get(_as_int(code))
    if rejection:
        detail = f"{rejection}; {detail}"
    return LLMEmptyChoices(
        f"LLM response has no choices ({source}): {detail}",
        finish_reason="error", usage=usage, provider=provider, model=model,
        deterministic=rejection is not None,
    )


def _completion_failure(provider: str, finish_reason: str, raw_finish_reason: Any,
                        usage: Optional[Dict[str, int]], max_tokens: Optional[int]) -> Exception:
    """The typed exception for a reply with no text, chosen by its normalized finish reason."""
    if finish_reason == "content_filter":
        return LLMContentFiltered(
            f"LLM reply stopped by the provider content_filter before any text "
            f"(provider={provider}, finish_reason={raw_finish_reason})",
            finish_reason=finish_reason, raw_finish_reason=raw_finish_reason, usage=usage,
            sent_max_tokens=max_tokens, provider=provider,
        )
    if finish_reason == "error":
        return LLMAbortedCompletion(
            f"LLM provider aborted the reply before any text "
            f"(provider={provider}, finish_reason={raw_finish_reason})",
            finish_reason=finish_reason, raw_finish_reason=raw_finish_reason, usage=usage,
            sent_max_tokens=max_tokens, provider=provider,
        )
    parts = [f"finish_reason={finish_reason}"]
    if max_tokens is not None and _status_safe(max_tokens):
        parts.append(f"max_tokens={max_tokens}")
    parts.append(f"provider={provider}")
    message = f"LLM returned empty content ({', '.join(parts)})."
    knob = _thinking_knob(provider)
    if knob and getattr(Config, knob, True):
        message += f" Hint: {knob}=true already disables provider thinking; raise max_tokens."
    elif knob:
        message += (f" Hint: reasoning may have used the whole output budget; set {knob}=true "
                    f"to disable provider thinking, or raise max_tokens.")
    else:
        message += " Hint: raise max_tokens if the output cap cut the reply."
    return EmptyCompletion(
        message, finish_reason=finish_reason, raw_finish_reason=raw_finish_reason, usage=usage,
        sent_max_tokens=max_tokens, provider=provider,
    )


class LLMClient:
    """LLM客户端 — 支持 claude-cli / codex-cli / openai"""

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        *,
        use_cache: bool = True,
        pinned: bool = False,
    ):
        self.provider = (provider or Config.LLM_PROVIDER or "claude-cli").lower()

        # INFRA-1: 逐调用元数据存于线程本地 _CALL_META（见 last_call_meta）。此处经 _last_usage
        # 兼容 setter 清掉本线程上可能残留的、恰好复用了本实例 id() 的旧客户端元数据。
        self._last_usage = None

        # openai 提供方所需的连接参数（CLI 模式下不使用）
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME

        if self.provider not in CLI_PROVIDERS and self.provider not in OPENAI_COMPATIBLE_PROVIDERS:
            _supported = " / ".join(repr(p) for p in (*CLI_PROVIDERS, *OPENAI_COMPATIBLE_PROVIDERS))
            raise ValueError(
                f"不支持的 LLM 提供方: {self.provider!r}。可选: {_supported}。"
            )

        # 仅在使用 OpenAI 兼容提供方（openai/kimi）时才创建 OpenAI 客户端（CLI 模式无需 API Key）
        self._openai_client = None
        if self.provider in OPENAI_COMPATIBLE_PROVIDERS:
            self._openai_client = self._build_openai_client(self.provider, self.api_key, self.base_url)

        # EXECPLAN2 I-6-2: 当 fast tier 指向一个完全不同的 OpenAI 兼容提供方时，按需懒构建
        # 的第二个客户端（如本地廉价抽取 + 远端旗舰合成）。仅在 tiered routing 开启且配齐
        # LLM_FAST_PROVIDER/BASE_URL/API_KEY 时才会真正实例化；否则保持 None（同提供方切模型）。
        self._fast_openai_client = None
        # INFRA-6: the provider the fast-tier second client was built for (its serving provider).
        self._fast_openai_provider: Optional[str] = None
        # S9: set True on a fallback client so failover never recurses.
        self._is_fallback = False
        # EVAL-10: per-instance isolation for callers whose calls must stay independent and
        # attributable (eval judges, replicate/control arms). use_cache=False makes every call a
        # real transport call even while LLM_CACHE_ENABLED is on (the cache key carries no run or
        # seed, so k identical judge passes collapsed into one). pinned=True serves every call
        # with this client's own provider and model: no tier re-route, no fast-tier second
        # client and no failover (errors surface instead of a silent backbone swap).
        self.use_cache = bool(use_cache)
        self._pinned = bool(pinned)

    @staticmethod
    def _build_openai_client(provider: str, api_key: Optional[str], base_url: Optional[str]):
        """构造一个 OpenAI 兼容客户端（供主客户端与 fast-tier 第二客户端复用）。"""
        from openai import OpenAI
        if not api_key:
            raise ValueError(f"LLM_PROVIDER={provider} 时必须配置 LLM_API_KEY")
        client_kwargs: Dict[str, Any] = {"api_key": api_key, "base_url": base_url}
        # GLM-run 2026-09-18: an explicit hard timeout on EVERY call. Without
        # it (HTTP/2 path off), a provider stream that dies mid-read can wedge
        # the calling pipeline thread forever — observed live on the report
        # planning call (38+ min silent hang, no SDK timeout fired, no retry).
        # chat()'s backoff loop owns recovery; this only bounds the wait.
        try:
            _http_timeout_s = float(getattr(Config, "LLM_HTTP_TIMEOUT_S", 600.0) or 600.0)
        except (TypeError, ValueError):
            _http_timeout_s = 600.0
        client_kwargs["timeout"] = _http_timeout_s
        # Kimi-for-coding 网关按 User-Agent 校验 coding-agent 身份；
        # 不带可识别的 UA 会被拒绝（access_terminated_error）。INFRA-6: 头部规则取自
        # provider_overrides（与 OASIS 建模、设置页/preflight 探针同源）。
        headers = openai_compat_request_overrides(provider)["default_headers"]
        if headers:
            client_kwargs["default_headers"] = headers
        # R2-EXEC-6: 当 LLM_HTTP2 开启时，注入一个调优过的 httpx 客户端（HTTP/2 多路复用 +
        # 更大 keepalive 池）并把 SDK 自带重试关掉（max_retries=0，由 chat() 的退避循环统一负责）。
        # 默认（未配置 LLM_HTTP2 / 为 false）返回 None → 沿用 OpenAI SDK 自带 httpx 客户端，
        # 行为与现状逐字节一致（degrade-safe）。
        http_client = LLMClient._build_http_client()
        if http_client is not None:
            client_kwargs["http_client"] = http_client
            client_kwargs["max_retries"] = 0
        return OpenAI(**client_kwargs)

    @staticmethod
    def _build_http_client():
        """R2-EXEC-6: 为同步 OpenAI 客户端构造调优过的 httpx 客户端，未启用时返回 None。

        默认 httpx 客户端把 keepalive 连接封顶在 20 且无多路复用，使 R2-EXEC-1 放开的并发
        实际上仍被连接池/每调用 TLS 握手卡住。开启 LLM_HTTP2 后：
          - http2=LLM_HTTP2（默认配置层置 true）：单连接多路复用，去掉逐调用 TLS 建连；
          - keepalive=LLM_HTTP_KEEPALIVE（默认 128，原 20）：去掉 20 槽 keepalive 抖动；
          - 显式设置宽松超时：自带 httpx.Client 默认 5s 读超时会腰斩长章节生成，故对齐
            OpenAI SDK 的 600s 量级；
          - h2 未安装 / HTTP/2 协商失败时优雅回退 HTTP/1.1（仍保留调优的 keepalive/超时）。

        gate：仅当 getattr(Config, 'LLM_HTTP2', False) 为真时才构造；否则返回 None 保持现状。
        """
        if not getattr(Config, "LLM_HTTP2", False):
            return None
        try:
            import httpx
        except Exception:  # httpx 理应随 openai 安装；缺失则回退 SDK 默认客户端
            return None
        keepalive = int(getattr(Config, "LLM_HTTP_KEEPALIVE", 128) or 128)
        limits = httpx.Limits(
            max_keepalive_connections=keepalive,
            max_connections=keepalive + 32,
        )
        # 连接快、读/写慢：长文生成需要大读超时，避免 httpx 默认 5s 腰斩。
        timeout = httpx.Timeout(600.0, connect=10.0)
        try:
            return httpx.Client(http2=True, limits=limits, timeout=timeout)
        except Exception as exc:  # h2 未安装或协商失败 → 回退 HTTP/1.1（不影响管线运行）
            logger.warning(f"HTTP/2 客户端构建失败，回退 HTTP/1.1: {exc}")
            try:
                return httpx.Client(http2=False, limits=limits, timeout=timeout)
            except Exception as exc2:  # 极端情况下连 http1 调优客户端也失败 → 回退 SDK 默认
                logger.warning(f"调优 httpx 客户端构建失败，回退 SDK 默认客户端: {exc2}")
                return None

    # ------------------------------------------------------------------
    # EXECPLAN2 I-6-2: 双层模型路由（fast / strong）
    # ------------------------------------------------------------------
    def _model_for_tier(self, tier: Optional[str], *, pinned: Optional[bool] = None) -> str:
        """按 tier 解析实际使用的模型名。

        - tiered routing 关闭（默认）→ 一律返回 self.model（行为与现状逐字节一致）。
        - tier='fast'  → Config.fast_model()（未配置 LLM_FAST_MODEL 时回退到当前模型，不报错）。
        - tier='strong'/None/未知 → Config.strong_model()（同样回退到当前模型）。
        CLI 订阅提供方只有单一订阅模型，tier 在 _chat_* 中被忽略，此处返回值仅用于计量一致性。

        ``pinned`` is the caller's once-per-call _routing_pinned() result, so the model and the
        fast-tier client of one transport call come from a single read (None = read it here).
        """
        # The fast/strong aliases belong to the primary provider. A routing-pinned client
        # (fallback, pinned=True, or any provider other than the current primary) keeps its
        # own resolved model: the alias sent MiniMax-M3 to Quotio's Antigravity endpoint and
        # made every production failover return HTTP 400, and sent the primary's strong model
        # to ensemble / judge / comparison clients of other providers (400 -> silent failover).
        if pinned is None:
            pinned = self._routing_pinned()
        if pinned:
            return self.model
        if not getattr(Config, "LLM_TIERED_ROUTING", False):
            return self.model
        if tier == "fast":
            return Config.fast_model() or self.model
        return Config.strong_model() or self.model

    def _routing_pinned(self) -> bool:
        """EVAL-10: True when this client's own provider and model must serve every call.

        The single predicate for tier routing: a pinned client never takes the primary
        provider's fast/strong model aliases or the fast-tier second client. Pinned are a
        fallback client, a client built with pinned=True, and a client whose provider is not
        the current global primary. Evaluated per call, so a settings hot-switch of
        LLM_PROVIDER cannot send the new primary's model names to an older client's endpoint.
        Default-provider clients built without pinned=True are not pinned (routing unchanged).
        """
        if getattr(self, "_is_fallback", False) or getattr(self, "_pinned", False):
            return True
        return self.provider != (Config.LLM_PROVIDER or "claude-cli").lower()

    def _tier_route(self, tier: Optional[str]) -> Tuple[str, bool]:
        """EVAL-10: resolve one call's tier routing from a single _routing_pinned() read.

        Returns ``(model, fast_tier)``: the model name the request carries, and whether the
        fast-tier second client (instead of this client's own endpoint) should serve it. chat()
        resolves the route once and hands it to _chat_openai, so the LLMCache key, the LLMMeter
        by_model entry and every retry of the request share one model even when a settings
        hot-switch of LLM_PROVIDER / LLM_MODEL_NAME lands mid-call.
        """
        pinned = self._routing_pinned()
        model = self._model_for_tier(tier, pinned=pinned)
        fast_tier = bool(not pinned and getattr(Config, "LLM_TIERED_ROUTING", False) and tier == "fast")
        return model, fast_tier

    def _fast_provider_client(self):
        """若 fast tier 指向不同的 OpenAI 兼容提供方，返回（懒构建的）第二客户端，否则 None。

        需要 LLM_FAST_PROVIDER + LLM_FAST_BASE_URL + LLM_FAST_API_KEY 三者齐备且该提供方
        为 OpenAI 兼容；缺任一则回退为「同提供方切模型」（返回 None）。构建失败同样回退 None，
        绝不让 fast tier 的误配置把整条调用打挂（graceful degradation）。
        """
        fp = getattr(Config, "LLM_FAST_PROVIDER", None)
        fb = getattr(Config, "LLM_FAST_BASE_URL", None)
        fk = getattr(Config, "LLM_FAST_API_KEY", None)
        if not (fp and fb and fk) or fp not in OPENAI_COMPATIBLE_PROVIDERS:
            return None
        if self._fast_openai_client is None:
            try:
                self._fast_openai_client = self._build_openai_client(fp, fk, fb)
                self._fast_openai_provider = fp
            except Exception as exc:  # 误配置不应中断调用，记录后回退主客户端
                logger.warning(f"fast-tier 第二客户端构建失败，回退主客户端: {exc}")
                return None
        return self._fast_openai_client

    def _serving_endpoint(self, fast_tier: bool) -> Tuple[Any, str]:
        """INFRA-6: ``(OpenAI client, provider)`` that serve one OpenAI-compatible call.

        ``fast_tier`` is the call's _tier_route() flag. When the fast-tier second client serves
        the call, its provider is LLM_FAST_PROVIDER: the request then carries that provider's
        extra_body and temperature rule, and the call metadata and meter attribute the call to
        it. Otherwise this client's own endpoint and provider serve it (a routing-pinned client
        never gets fast_tier, see _tier_route).
        """
        if fast_tier:
            fast_client = self._fast_provider_client()
            if fast_client is not None:
                provider = getattr(self, "_fast_openai_provider", None) or Config.LLM_FAST_PROVIDER
                return fast_client, provider
        return self._openai_client, self.provider

    def _requested_label(self, serving_provider: str, model: str) -> str:
        """INFRA-8: the requested-model label LLMMeter records for one call of this client.

        A CLI call ignores the tier route: claude-cli is given --model from this client's own
        model (or nothing: 'cli-default'), codex-cli never. An OpenAI-compatible call sends the
        routed ``model`` (EVAL-10 _tier_route) to ``serving_provider`` (INFRA-6).
        """
        if self.provider in CLI_PROVIDERS:
            return effective_model_label(self.provider, getattr(self, "model", None))
        return effective_model_label(serving_provider, model)

    # ------------------------------------------------------------------
    # INFRA-1: 逐调用元数据（线程本地，按客户端 id() 归属）
    # ------------------------------------------------------------------
    def last_call_meta(self) -> Optional[Dict[str, Any]]:
        """Metadata of this client's last successful call on the calling thread.

        Keys: client_id, provider (the provider whose endpoint served the call:
        LLM_FAST_PROVIDER when the fast-tier second client served it, INFRA-6), model,
        served_model, finish_reason (normalized, see llm_text.FINISH_REASONS),
        raw_finish_reason, usage {prompt_tokens, completion_tokens,
        total_tokens, reasoning_tokens, cached_tokens}, usage_source ('provider' = reported by
        the API, 'cli' = Claude CLI envelope, 'none' = not reported, all zeros), think_stripped,
        served_by ('primary' | 'fallback' | 'cache') and cacheable. chat_json adds
        json_truncation_repaired=True (INFRA-2) when it accepted a reply only after closing
        its unterminated brackets locally.

        Returns a copy, or None when the thread's last call belongs to another client or this
        client's last call on the thread did not complete.
        """
        meta = self._own_call_meta()
        if meta is None:
            return None
        out = dict(meta)
        out["usage"] = dict(meta.get("usage") or {})
        return out

    def _own_call_meta(self) -> Optional[Dict[str, Any]]:
        meta = getattr(_CALL_META, "meta", None)
        if isinstance(meta, dict) and meta.get("client_id") == id(self):
            return meta
        return None

    def _clear_own_call_meta(self) -> None:
        if self._own_call_meta() is not None:
            _CALL_META.meta = None

    def _stamp_call_meta(self, *, model: Optional[str], finish_reason: str,
                         raw_finish_reason: Any = None, usage: Optional[Dict[str, int]] = None,
                         usage_source: str = "none", served_model: Any = None,
                         think_stripped: bool = False, dangling: bool = False,
                         served_by: str = "primary", provider: Optional[str] = None) -> None:
        """Record a completed call as the calling thread's last call.

        ``provider`` is the serving provider (INFRA-6); None means this client's own provider.
        Never raises: a failure here is logged at debug level and leaves no metadata, so it
        can never mask the completion itself.
        """
        try:
            raw = getattr(raw_finish_reason, "value", raw_finish_reason)
            meta: Optional[Dict[str, Any]] = {
                "client_id": id(self),
                "provider": provider or getattr(self, "provider", None),
                "model": model,
                "served_model": served_model if isinstance(served_model, str) and served_model else None,
                "finish_reason": finish_reason,
                "raw_finish_reason": None if raw is None else str(raw),
                "usage": dict(usage) if usage else _usage_dict(),
                "usage_source": usage_source if usage else "none",
                "think_stripped": bool(think_stripped),
                "served_by": served_by,
                "cacheable": finish_reason in _CACHEABLE_FINISH_REASONS and not dangling,
            }
        except Exception as exc:  # noqa: BLE001 — metadata is observability only
            logger.debug(f"LLM 调用元数据构建失败（忽略）: {exc}")
            meta = None
        _CALL_META.meta = meta

    def _adopt_fallback_meta(self, fb: "LLMClient") -> None:
        """Re-stamp the fallback client's call metadata as this client's call (served_by='fallback')."""
        try:
            meta = fb.last_call_meta()
            if meta is None:
                return
            meta.update(client_id=id(self), served_by="fallback",
                        provider=fb.provider, model=fb.model)
            _CALL_META.meta = meta
        except Exception as exc:  # noqa: BLE001 — metadata is observability only
            logger.debug(f"回退调用元数据转写失败（忽略）: {exc}")

    @property
    def _last_usage(self) -> Optional[Dict[str, int]]:
        """Backward-compatible mirror of the calling thread's last provider-reported usage.

        Readers such as the simulation child's usage wrapper read ``client._last_usage`` right
        after chat(). The value comes from the thread-local call metadata, so concurrent calls
        on one shared client never see each other's usage. None when this client's last call
        on this thread reported no provider usage (CLI providers, a response without usage),
        exactly as before.
        """
        meta = self._own_call_meta()
        if meta is None or meta.get("usage_source") != "provider":
            return None
        return dict(meta.get("usage") or {})

    @_last_usage.setter
    def _last_usage(self, value: Optional[Dict[str, int]]) -> None:
        """None clears this client's metadata on the calling thread; a usage dict is stored as
        provider-reported usage for it. Never raises (clients built via object.__new__ too)."""
        try:
            if value is None:
                self._clear_own_call_meta()
                return
            usage = _usage_dict(_as_int(_field(value, "prompt_tokens")),
                                _as_int(_field(value, "completion_tokens")))
            meta = self._own_call_meta()
            if meta is None:
                self._stamp_call_meta(model=getattr(self, "model", None), finish_reason="unknown",
                                      usage=usage, usage_source="provider")
            else:
                meta["usage"] = usage
                meta["usage_source"] = "provider"
        except Exception:  # noqa: BLE001 — compatibility shim must never raise
            pass

    # ------------------------------------------------------------------
    # LLMCache 键（chat() 读写与 chat_json 丢弃坏回复共用同一实现）
    # ------------------------------------------------------------------
    def _cache_on(self) -> bool:
        """EVAL-10: use_cache=False opts this client out of LLMCache entirely (get and put)."""
        return bool(Config.LLM_CACHE_ENABLED and getattr(self, "use_cache", True))

    def _cache_key(self, model: str, messages: List[Dict[str, str]], temperature: float,
                   max_tokens: int, response_format: Optional[Dict]) -> str:
        """The LLMCache key chat() reads and writes for one request.

        The key carries the resolved model, so fast/strong tier replies never mix. EVAL-10: a
        pinned client reads and writes its own namespace. An unpinned client caches a
        fallback-served reply under its primary key, and a pinned client must never serve a
        fallback provider's reply, not even from the cache.
        """
        from .telemetry import LLMCache
        cache_provider = f"{self.provider}#pinned" if getattr(self, "_pinned", False) else self.provider
        return LLMCache.key(cache_provider, model, messages, temperature, max_tokens, response_format)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None,
        tier: str = "strong"
    ) -> str:
        """
        发送聊天请求，返回模型响应文本。

        所有提供方在瞬时失败（RuntimeError，含 CLI 错误、超时、推理模型空 content）
        时自动指数退避重试（3 次）。OpenAI SDK 自身的 APIError 子类不在此重试范围，
        会按原样抛出（SDK 内部已有自己的重试与限流处理）。

        tier（EXECPLAN2 I-6-2）: 'strong'（默认，= 当前模型，行为不变）| 'fast'（廉价/快速档）。
        仅当 Config.LLM_TIERED_ROUTING=true 且为 OpenAI 兼容提供方时，fast 才路由到更便宜的
        模型/提供方；CLI 订阅提供方与关闭路由时一律 no-op（graceful degradation）。

        INFRA-1: 空回复/无 choices/中止分别抛 EmptyCompletion / LLMEmptyChoices /
        LLMAbortedCompletion（均为 RuntimeError，照常退避重试；鉴权失败/余额不足/参数非法等
        确定性错误信封除外——不重试，直接回退）；审查拦截抛 LLMContentFiltered
        （非 RuntimeError：不重试，直接尝试一次回退）。本次调用的 finish_reason/usage 等见 last_call_meta()。
        """
        # EXECPLAN2 I-6-2: 解析本次调用实际使用的模型（fast/strong）。关闭路由时 = self.model。
        # EVAL-10: one routing read per call; the cache key, the meter and every transport retry
        # below use this route (see _tier_route).
        route = self._tier_route(tier)
        model = route[0]
        # EXECPLAN2 I-6-0/I-5-0/I-5-3: 内容寻址缓存命中直接返回；否则正常调用后记录
        # token/延迟/成本计量并做预算检查。计量默认开（开销极小），缓存/预算默认关。
        from .telemetry import LLMMeter, LLMCache, get_run_context, check_budget, estimate_tokens
        run_id, stage = get_run_context()
        cache_key = None
        # EVAL-10: use_cache=False opts this client out of LLMCache entirely (get and put).
        cache_on = self._cache_on()
        if cache_on:
            cache_key = self._cache_key(model, messages, temperature, max_tokens, response_format)
            hit = LLMCache.get(cache_key)
            if hit is not None:
                # INFRA-6: a replayed reply is attributed to the provider this route's real call
                # is served by (LLM_FAST_PROVIDER for a fast-tier route on the second client).
                hit_provider = (self._serving_endpoint(route[1])[1]
                                if self.provider in OPENAI_COMPATIBLE_PROVIDERS else self.provider)
                if Config.LLM_TELEMETRY_ENABLED:
                    LLMMeter.record(hit_provider, model, 0, 0, 0.0, cached=True, stage=stage, run_id=run_id,
                                    requested_model=self._requested_label(hit_provider, model))
                self._stamp_call_meta(model=model, finish_reason="unknown", served_by="cache",
                                      provider=hit_provider)
                return hit

        last_error: Optional[Exception] = None
        result: Optional[str] = None
        # LLM-2: 回退提供方接管时，回退客户端自己的 chat() 已经计量过这次调用（provider=回退方、
        # 精确 token）。外层若再按主提供方记一次，失败转移最多的 run 的 token/成本会 ~2x 虚增且
        # by_model 归属错乱。置位后跳过外层计量。
        served_by_fallback = False
        started = time.monotonic()
        self._clear_own_call_meta()
        # Circuit breaker: if the primary is in a content-filter/quota cooldown, skip the doomed
        # primary attempt entirely and go straight to the fallback (prevents the futile-call flood).
        if _cb_tripped(self.provider) and not self._is_fallback:
            _fb = self._try_fallback(messages, temperature, max_tokens, response_format,
                                     RuntimeError(f"circuit-breaker: {self.provider} in 422/429 cooldown"))
            if _fb is not None:
                result = _fb
                served_by_fallback = True
            else:
                # 双通道皆不可用：主提供方处于熔断冷却，回退失败/未配置。此前会继续掉进
                # 完整的 3 次主重试（指数退避睡眠）+ 第二次回退 —— 双中断期间每次 chat()
                # 白烧 5 次注定失败的调用（2026-07-08 实测：最高 231 错误/分钟持续 26 小时）。
                # 直接抛出（复用穷尽路径的异常类型），让调用方快速失败。
                if getattr(self, "_pinned", False):
                    # EVAL-10: a pinned client never fails over by design, even with a healthy
                    # LLM_FALLBACK_PROVIDER configured; say so instead of blaming the fallback.
                    raise RuntimeError(
                        f"LLM 调用失败：钉定客户端的提供方 {self.provider} 处于 422/429 熔断冷却"
                        f"（pinned：不做失败转移）"
                    )
                raise RuntimeError(
                    f"LLM 调用失败：主提供方 {self.provider} 处于 422/429 熔断冷却，"
                    f"且回退提供方不可用"
                )
        for attempt in range(MAX_RETRIES):
            if result is not None:
                break
            try:
                if self.provider in OPENAI_COMPATIBLE_PROVIDERS:
                    result = self._chat_openai(messages, temperature, max_tokens, response_format,
                                               tier=tier, route=route)
                elif self.provider == "codex-cli":
                    # CLI 订阅提供方只有单一订阅模型，tier 在此为 no-op。
                    result = self._chat_codex_cli(messages, temperature, max_tokens, response_format)
                else:
                    result = self._chat_claude_cli(messages, temperature, max_tokens, response_format)
                _cb_reset(self.provider)  # primary succeeded → clear its 422/429 streaks
                break
            except (RuntimeError, *_RETRYABLE_API_ERRORS) as exc:
                last_error = exc
                if _is_deterministic_auth_error(exc):
                    logger.warning(
                        "LLM authentication failure is deterministic; skipping retries: %s",
                        _err_brief(exc),
                    )
                    break
                if _is_quota(exc):
                    _cb_record_429(self.provider)  # LLM-3: 连续配额失败达阈值 → 冷却直连回退
                if isinstance(exc, LLMEmptyChoices) and exc.deterministic:
                    # INFRA-1: 确定性错误信封（余额不足/参数非法等）重试无益，直接转回退。
                    logger.warning(
                        "LLM provider rejection is deterministic; skipping retries: %s",
                        _err_brief(exc),
                    )
                    break
                if attempt < MAX_RETRIES - 1:
                    delay = _retry_delay(exc, attempt)
                    logger.warning(
                        f"LLM 调用失败 (第 {attempt + 1}/{MAX_RETRIES} 次)，{delay}s 后重试: {exc}"
                    )
                    time.sleep(delay)
            except Exception as exc:  # noqa: BLE001 — non-retryable (e.g. 422 content-filter): stop retrying, try fallback
                last_error = exc
                if _is_content_filter(exc):
                    _cb_record_422(self.provider)  # count toward tripping the breaker
                logger.warning(f"LLM 调用遇不可重试错误，转回退提供方: {_err_brief(exc)}")
                break
        if result is None:
            # QUALITY-OPT S9: provider failover. On exhausted quota (429) or a content-filter
            # rejection (422 new_sensitive) the same provider will keep failing; retry the SAME
            # request once on a configured fallback provider so the run recovers instead of
            # shipping placeholders. The pipeline health gate (S1) still catches the case where
            # neither provider succeeds. Off unless LLM_FALLBACK_PROVIDER is set.
            fb = self._try_fallback(messages, temperature, max_tokens, response_format, last_error)
            if fb is not None:
                result = fb
                served_by_fallback = True
            else:
                raise last_error if last_error is not None else RuntimeError("LLM 调用失败")

        # INFRA-1: 本次调用的元数据取自线程本地 _CALL_META（按本实例 id 归属），不再读实例属性
        # ——同一客户端被报告章节池 / graphiti 线程池并发调用时，实例级 usage 会被别的线程覆盖，
        # token 记到错误的调用上。回退接管时 _try_fallback 已把回退方元数据转写为本客户端的。
        meta = self._own_call_meta()
        if Config.LLM_TELEMETRY_ENABLED and not served_by_fallback:
            latency_ms = (time.monotonic() - started) * 1000.0
            # 仅 API 上报的精确 usage 顶替粗估；Claude CLI 信封的 usage 含 CLI 自身的系统提示/缓存，
            # 计入会抬高 run 预算口径，故 CLI 仍按文本长度粗估（与历史一致）。
            usage = meta["usage"] if meta and meta.get("usage_source") == "provider" else None
            if usage:
                pt, ct = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
            else:
                # 无精确 usage（CLI 提供方）→ 按文本长度粗估
                pt = sum(estimate_tokens(str(m.get("content", ""))) for m in messages)
                ct = estimate_tokens(result)
            # 用解析后的 model 计量，使 by_model 维度区分 fast/strong 用量与成本。
            # INFRA-6: 成本按实际服务的提供方计（fast-tier 第二客户端服务时为 LLM_FAST_PROVIDER）。
            meter_provider = (meta.get("provider") if meta else None) or self.provider
            # INFRA-8: requested label vs the model the provider reported serving the call.
            LLMMeter.record(meter_provider, model, pt, ct, latency_ms, cached=False, stage=stage,
                            run_id=run_id, finish_reason=meta.get("finish_reason") if meta else None,
                            served_model=meta.get("served_model") if meta else None,
                            requested_model=self._requested_label(meter_provider, model))
        if cache_on and cache_key is not None:
            # INFRA-1 (LLM_TRANSPORT_STRICT): 截断(length)/审查/中止/悬空 <think> 的回复不入缓存
            # ——否则同一 prompt 会从 LLMCache 永久重放这份残缺回复。无元数据时同样不缓存（失败安全）。
            if _transport_strict() and not (meta and meta.get("cacheable")):
                logger.debug(
                    "LLM 回复不入缓存（finish_reason=%s，无元数据=%s）",
                    meta.get("finish_reason") if meta else None, meta is None,
                )
            else:
                LLMCache.put(cache_key, result)
        if Config.LLM_RUN_BUDGET_TOKENS or Config.LLM_RUN_BUDGET_USD:
            check_budget(run_id)  # 超预算抛 BudgetExceeded
        return result

    def _try_fallback(self, messages: List[Dict[str, str]], temperature: float,
                      max_tokens: int, response_format: Optional[Dict],
                      primary_error: Optional[Exception]) -> Optional[str]:
        """QUALITY-OPT S9: retry the request once on a configured fallback provider when the
        primary exhausts retries / hits a content-filter. Off unless LLM_FALLBACK_PROVIDER is
        set; never recurses (the fallback client has failover disabled). Returns text or None.
        EVAL-10: a pinned client never fails over; the primary's error surfaces instead."""
        if getattr(self, "_is_fallback", False) or getattr(self, "_pinned", False):
            return None
        fb_provider = (os.environ.get("LLM_FALLBACK_PROVIDER", "") or "").strip().lower()
        if not fb_provider or fb_provider == self.provider:
            return None
        fb_model = (os.environ.get("LLM_FALLBACK_MODEL", "") or None)
        fb_base_url = (os.environ.get("LLM_FALLBACK_BASE_URL", "") or None)
        # LLM_FALLBACK_MODEL 未配置时 LLMClient.__init__ 会把 model 默认成主提供方的
        # Config.LLM_MODEL_NAME —— 对指向另一家网关的 OpenAI 兼容回退是必然的 400
        # （'unknown provider for model MiniMax-M2'，2026-07-08 生产实测），构建即注定失败。
        # 直接拒绝构建该回退客户端（进程内只告警一次）。CLI 回退（claude-cli/codex-cli）
        # 不受影响：订阅提供方不在请求里发 model 字段。
        if (fb_model is None and fb_provider in OPENAI_COMPATIBLE_PROVIDERS
                and (fb_provider != self.provider
                     or (fb_base_url or "") != (self.base_url or ""))):
            if fb_provider not in _FB_MISCONFIG_WARNED:
                _FB_MISCONFIG_WARNED.add(fb_provider)
                logger.warning(
                    "回退提供方 %s 未配置 LLM_FALLBACK_MODEL，拒绝继承主提供方模型名 %r"
                    "（会导致必然的 400 invalid-model）；请设置 LLM_FALLBACK_MODEL",
                    fb_provider, Config.LLM_MODEL_NAME,
                )
            return None
        auth_key = (fb_provider, fb_model or "", fb_base_url or "")
        with _CB_LOCK:
            auth_unavailable_until = _FB_AUTH_UNAVAILABLE_UNTIL.get(auth_key, 0.0)
        if auth_unavailable_until > time.monotonic():
            logger.warning(
                "Skipping fallback provider %s during deterministic-failure cooldown",
                fb_provider,
            )
            return None
        try:
            fb = LLMClient(
                provider=fb_provider,
                model=fb_model,
                api_key=(os.environ.get("LLM_FALLBACK_API_KEY", "") or None),
                base_url=fb_base_url,
                # EVAL-10: a use_cache=False client stays uncached through failover too (the
                # fallback's own chat() must not replay a cached fallback reply).
                use_cache=getattr(self, "use_cache", True),
            )
            fb._is_fallback = True  # prevent recursive failover
            # LLM-3: 复用回退提供方的 OpenAI 连接池（每次失败转移重建 httpx 池 = 每调用一次
            # TLS 握手放大）。OpenAI 同步客户端线程安全；LLMClient 实例本身仍逐调用新建。
            if fb._openai_client is not None:
                _fb_key = (fb.provider, fb.model, fb.base_url)
                _cached = _FB_OPENAI_CLIENTS.get(_fb_key)
                if _cached is None:
                    _FB_OPENAI_CLIENTS[_fb_key] = fb._openai_client
                else:
                    fb._openai_client = _cached
            logger.warning(f"主提供方 {self.provider} 失败（{_err_brief(primary_error) if primary_error else '?'}），"
                           f"切换到回退提供方 {fb_provider}")
            out = fb.chat(messages, temperature, max_tokens, response_format)
            self._adopt_fallback_meta(fb)
            with _CB_LOCK:
                _FB_AUTH_UNAVAILABLE_UNTIL.pop(auth_key, None)
            logger.info(f"回退提供方 {fb_provider} 成功接管本次调用")
            return out
        except Exception as e:  # noqa: BLE001 — fallback failed too; caller raises the primary error
            # 确定性失败（401 凭据坏 / 400 invalid-model 类）进入进程级冷却：重试修不好，
            # 并行 worker 不该反复对同一注定失败的回退发起昂贵调用。服务重启或修好配置自然清零。
            if _is_deterministic_auth_error(e) or _is_deterministic_invalid_request_error(e):
                with _CB_LOCK:
                    _FB_AUTH_UNAVAILABLE_UNTIL[auth_key] = (
                        time.monotonic() + _FB_AUTH_COOLDOWN_S
                    )
            logger.error(f"回退提供方 {fb_provider} 也失败: {_err_brief(e)}")
            return None

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        tier: str = "strong",
        *,
        label: Optional[str] = None,
        allow_non_dict: bool = False,
    ) -> Dict[str, Any]:
        """发送聊天请求并返回解析后的 JSON。

        解析失败时先做本地修复（提取 JSON 块、补全被 max_tokens 截断的括号）。

        INFRA-2（LLM_JSON_REPAIR_TURN，默认开）：首轮回复不是单个 JSON 对象（解析失败，或解析出
        list/标量/null；allow_non_dict=True 时只看解析失败与 null）即为未命中：先从 LLMCache 删掉
        这份坏回复，再以同温度发一次修复轮（原消息 + 坏回复 + 点名原因的纠正提示；空回复以占位文本
        代替）；两轮皆未命中则删掉第二份并抛 ValueError。靠补括号修复的截断回复照常采纳，并在
        last_call_meta() 标记 json_truncation_repaired=True。结局按 ``label``（缺省 'chat_json'）计入
        LLMMeter 的 structured_outputs（修复轮传输失败也计 failed）。关闭时为旧行为：降温 0.2 重发同一
        提示，可能返回非 dict。

        tier（EXECPLAN2 I-6-2）透传给 chat()：结构化/机械型 JSON 调用（子查询分解、
        受访者选择、图谱抽取）可传 tier='fast' 路由到廉价档；默认 'strong' 行为不变。
        """
        if getattr(Config, "LLM_JSON_REPAIR_TURN", True):
            return self._chat_json_with_repair(messages, temperature, max_tokens, tier,
                                               label=label or "chat_json",
                                               allow_non_dict=allow_non_dict)
        last_response = ""
        for attempt in range(2):
            response = self.chat(
                messages=messages,
                temperature=max(0.0, temperature - attempt * 0.2),
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                tier=tier
            )
            last_response = response
            parsed = self._parse_json_response(response)
            if parsed is not None:
                return parsed
            if attempt == 0:
                logger.warning("chat_json 解析失败，降温重发一次")
        raise ValueError(f"LLM返回的JSON格式无效: {last_response[:500]}")

    def _chat_json_with_repair(self, messages: List[Dict[str, str]], temperature: float,
                               max_tokens: int, tier: str, *, label: str,
                               allow_non_dict: bool) -> Any:
        """INFRA-2: chat_json under LLM_JSON_REPAIR_TURN (see chat_json).

        Both attempts run at the caller's temperature: the repair turn's messages differ from
        the first request, so its cache key differs too, and a temperature-0 caller still gets a
        fresh completion. A transport error from chat() propagates unchanged; when it hits the
        repair turn, the lost attempt is still counted as 'failed' first.

        A reply of JSON null is a miss ('not a JSON object') even with allow_non_dict=True:
        chat_json has never returned None (the legacy loop retried it like a parse failure).
        """
        response_format = {"type": "json_object"}
        attempt_messages = messages
        reasons: List[str] = []
        response = ""
        for attempt in range(2):
            try:
                response = self.chat(
                    messages=attempt_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    tier=tier,
                )
            except Exception:
                if attempt:
                    # Attempt 1 already missed: without this the failure would vanish from
                    # structured_outputs, which is what decides whether Phase B is needed.
                    self._record_structured(label, "failed", False)
                raise
            value, truncation_repaired = self._parse_json_response_ex(response, unparsed=_JSON_UNPARSED)
            if value is _JSON_UNPARSED:
                reason = _JSON_MISS_INVALID
            elif value is None or (not allow_non_dict and not isinstance(value, dict)):
                reason = _JSON_MISS_NOT_OBJECT
            else:
                if truncation_repaired:
                    self._mark_json_truncation_repaired()
                self._record_structured(label, "ok" if attempt == 0 else "repaired",
                                        truncation_repaired)
                return value
            reasons.append(reason)
            # A rejected reply must never stay in LLMCache: the next identical call (graphiti's
            # tenacity retry resends the same arguments) would replay it forever.
            self._discard_cached_reply(attempt_messages, temperature, max_tokens,
                                       response_format, tier)
            if attempt == 0:
                logger.warning(f"chat_json 回复不是单个合法 JSON 对象（{reason}），携纠正提示重发一次")
                echoed = str(response)[:_JSON_REPAIR_REPLY_CHARS]
                attempt_messages = list(messages) + [
                    {"role": "assistant", "content": echoed if echoed.strip() else _JSON_REPAIR_EMPTY_REPLY},
                    {"role": "user", "content": _JSON_REPAIR_NOTE.format(reason=reason)},
                ]
        self._record_structured(label, "failed", False)
        raise ValueError(
            f"LLM返回的JSON格式无效（首轮: {reasons[0]}; 修复轮: {reasons[1]}）: {response[:500]}"
        )

    def _mark_json_truncation_repaired(self) -> None:
        """Flag this client's last call on the calling thread as a locally repaired truncation."""
        meta = self._own_call_meta()
        if meta is not None:
            meta["json_truncation_repaired"] = True

    @staticmethod
    def _record_structured(label: str, outcome: str, truncation_repaired: bool) -> None:
        """Count one chat_json outcome in LLMMeter (run and stage from the calling context)."""
        if Config.LLM_TELEMETRY_ENABLED:
            from .telemetry import LLMMeter
            LLMMeter.record_structured(label, outcome, json_truncation_repaired=truncation_repaired)

    def _discard_cached_reply(self, messages: List[Dict[str, str]], temperature: float,
                              max_tokens: int, response_format: Optional[Dict], tier: str) -> None:
        """INFRA-2: drop a rejected reply from LLMCache. Never raises.

        Removes the key chat() wrote for this request and, when a fallback provider served
        it, also the key the fallback client's own chat() wrote (fallback clients are routing
        pinned, so that key carries their provider and model). Skipped for a use_cache=False
        client (EVAL-10) and while the cache is off.
        """
        if not self._cache_on():
            return
        try:
            from .telemetry import LLMCache
            model = self._tier_route(tier)[0]
            LLMCache.discard(self._cache_key(model, messages, temperature, max_tokens, response_format))
            meta = self._own_call_meta()
            if meta is not None and meta.get("served_by") == "fallback":
                LLMCache.discard(LLMCache.key(meta.get("provider"), meta.get("model"), messages,
                                              temperature, max_tokens, response_format))
        except Exception as exc:  # noqa: BLE001 — cache hygiene must never fail the call
            logger.debug(f"LLMCache 丢弃坏回复失败（忽略）: {exc}")

    # ------------------------------------------------------------------
    # 原生 tool calling（T4.5）—— 取代手搓 ReAct 的正则解析
    # ------------------------------------------------------------------
    def supports_native_tools(self) -> bool:
        """是否支持原生 function/tool calling。

        OpenAI 兼容提供方（openai/kimi/deepseek/qwen/glm）通过 OpenAI SDK 的 ``tools=``
        原生支持；CLI 提供方（claude-cli/codex-cli）无原生工具，返回 False → 报告退回 ReAct 兜底。
        受 Config.REPORT_NATIVE_TOOLS 总开关控制（config.py 默认开，REPORT-4）。

        LLM-6: 逐提供方能力位 PROVIDER_META[provider]['native_tools']（缺省 True）——MiniMax-M3
        的 agentic 工具调用不可靠（0-tool-call 推理残段），在 config 里置 False，退回 ReAct+回退链。
        可用 LLM_NATIVE_TOOLS_PROVIDERS（逗号分隔白名单）整体覆盖能力位。
        RPT-10: 提供方处于 422/429 熔断冷却时也返回 False——chat_with_tools 无法失败转移到 CLI
        回退（CLI 无 tools=），审查风暴期直接走 ReAct（其底层 chat() 自带回退链）。
        """
        if not (getattr(Config, "REPORT_NATIVE_TOOLS", False)
                and self.provider in OPENAI_COMPATIBLE_PROVIDERS
                and self._openai_client is not None):
            return False
        _override = (os.environ.get("LLM_NATIVE_TOOLS_PROVIDERS", "") or "").strip()
        if _override:
            _allowed = {p.strip().lower() for p in _override.split(",") if p.strip()}
            if self.provider not in _allowed:
                return False
        elif not Config.PROVIDER_META.get(self.provider, {}).get("native_tools", True):
            return False
        return not _cb_tripped(self.provider)

    def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools_schema: List[Dict[str, Any]],
        temperature: float = 0.4,
        max_tokens: int = 4096,
        tier: str = "strong",
    ) -> Dict[str, Any]:
        """原生 tool calling 单轮调用。

        Args:
            messages: OpenAI 格式消息（可含 role=tool 的工具结果回填）。
            tools_schema: OpenAI tools schema 列表（[{type:'function', function:{name,description,parameters}}]）。
            tier: EXECPLAN2 I-6-2 模型档位；默认 'strong'（报告合成保持旗舰模型，行为不变）。
        Returns:
            {"content": str, "tool_calls": [{"id","name","arguments"(dict),"raw_arguments","arguments_error"}],
             "finish_reason": str, "served_model": str|None}。无工具调用时 tool_calls=[]。
            arguments 解析失败时仍为 {}，arguments_error 给出原因、raw_arguments 保留模型原文（INFRA-1）。
        Raises:
            RuntimeError: 非原生提供方调用 / SDK 失败（含无 choices 的 LLMEmptyChoices）。
        """
        # INFRA-1: 与 chat() 一致——本次调用未完成时 last_call_meta() 不得返回上一次调用的元数据。
        self._clear_own_call_meta()
        if self._openai_client is None:
            raise RuntimeError("chat_with_tools 仅支持 OpenAI 兼容提供方")
        # LLM-1/RPT-10: 熔断预检——冷却期内直接抛错（调用方 report_agent 捕获后降级 ReAct，
        # ReAct 走 chat() 自带的重试+回退链），不再对被审查/限流的提供方发一次注定失败的原生调用。
        if _cb_tripped(self.provider):
            raise RuntimeError(f"chat_with_tools: 提供方 {self.provider} 处于 422/429 熔断冷却，回退 ReAct")
        # EXECPLAN2 I-6-2: 解析模型/客户端（默认 strong = 当前模型/主客户端，工具调用行为不变）。
        # EVAL-10: the fast-tier second client serves the primary provider's routing only; a
        # routing-pinned client (fallback, pinned, non-primary provider) keeps its own endpoint.
        # One _routing_pinned() read decides both (_tier_route), so a settings hot-switch
        # mid-call cannot pair a tier alias with this client's own endpoint (or the reverse).
        model, fast_tier = self._tier_route(tier)
        # INFRA-6: the serving provider's request overrides, metadata and meter entry.
        client, serving_provider = self._serving_endpoint(fast_tier)
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": tools_schema,
            "tool_choice": "auto",
        }
        extra_body = self._apply_reasoning_options(kwargs, serving_provider)
        # Kimi K2.7 Code 网关按推理开关硬校验温度（开=1/关=0.6），覆盖调用方温度。
        kwargs["temperature"] = self._coerce_temperature(temperature, serving_provider, extra_body)
        # LLM-1: 此前原生工具路径完全绕过 chat() 的韧性/观测栈（无重试、无熔断记账、无计量、
        # 无预算门）——REPORT_NATIVE_TOOLS 默认开时每章一次裸调用。对齐 chat()：瞬时错误退避重试、
        # 422 记入熔断、成功后计量+预算检查。原生工具没有 CLI 回退（CLI 无 tools=），最终失败原样
        # 抛出，由 report_agent 的 per-section 捕获降级 ReAct。
        from .telemetry import LLMMeter, get_run_context, check_budget
        _run_id, _stage = get_run_context()
        _started = time.monotonic()
        response = None
        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                _resp = client.chat.completions.create(**kwargs)
                # INFRA-1: 无 choices 的错误信封（MiniMax base_resp 配额等）按瞬时错误重试（审查信封
                # 为 LLMContentFiltered，记 422 后快速失败），不再在下方 choices[0] 处抛 IndexError。
                if not getattr(_resp, "choices", None):
                    raise _empty_choices_error(_resp, serving_provider, model, _usage_from_response(_resp))
                response = _resp
                _cb_reset(self.provider)
                break
            except (RuntimeError, *_RETRYABLE_API_ERRORS) as exc:
                last_error = exc
                if _is_quota(exc):
                    _cb_record_429(self.provider)
                if isinstance(exc, LLMEmptyChoices) and exc.deterministic:
                    logger.warning(f"chat_with_tools 遇确定性错误信封，不再重试: {_err_brief(exc)}")
                    break
                if attempt < MAX_RETRIES - 1:
                    delay = _retry_delay(exc, attempt)
                    logger.warning(
                        f"chat_with_tools 调用失败 (第 {attempt + 1}/{MAX_RETRIES} 次)，{delay}s 后重试: {_err_brief(exc)}"
                    )
                    time.sleep(delay)
            except Exception as exc:  # noqa: BLE001 — 不可重试（如 422 内容审查）：记熔断后快速失败
                last_error = exc
                if _is_content_filter(exc):
                    _cb_record_422(self.provider)
                logger.warning(f"chat_with_tools 遇不可重试错误: {_err_brief(exc)}")
                break
        if response is None:
            raise last_error if last_error is not None else RuntimeError("chat_with_tools 调用失败")
        choice = response.choices[0]
        msg = getattr(choice, "message", None)
        raw_finish = getattr(choice, "finish_reason", None)
        finish = normalize_finish_reason(raw_finish)
        usage = _usage_from_response(response)
        served_model = getattr(response, "model", None)
        served_model = served_model if isinstance(served_model, str) and served_model else None
        if Config.LLM_TELEMETRY_ENABLED:
            try:
                _pt = usage["prompt_tokens"] if usage else 0
                _ct = usage["completion_tokens"] if usage else 0
                LLMMeter.record(serving_provider, model, _pt, _ct,
                                (time.monotonic() - _started) * 1000.0,
                                cached=False, stage=_stage, run_id=_run_id, finish_reason=finish,
                                served_model=served_model,
                                requested_model=self._requested_label(serving_provider, model))
            except Exception:  # noqa: BLE001 — 计量失败不影响返回
                pass
        if Config.LLM_RUN_BUDGET_TOKENS or Config.LLM_RUN_BUDGET_USD:
            check_budget(_run_id)  # 超预算抛 BudgetExceeded
        tool_calls = []
        for tc in (getattr(msg, "tool_calls", None) or []):
            raw_args = tc.function.arguments
            # INFRA-1: 解析失败不再静默当作 {}——arguments 仍为 {}（兼容现有调用方），
            # 另附 raw_arguments（模型原文）与 arguments_error（失败原因）。
            args_error: Optional[str] = None
            try:
                args = json.loads(raw_args) if raw_args else {}
            except (json.JSONDecodeError, TypeError) as exc:
                args = {}
                args_error = f"{type(exc).__name__}: {exc}"
            if args_error is None and not isinstance(args, dict):
                args_error = f"arguments JSON is a {type(args).__name__}, not an object"
            tool_calls.append({"id": tc.id, "name": tc.function.name, "arguments": args,
                               "raw_arguments": raw_args, "arguments_error": args_error})
        raw_content = flatten_content(getattr(msg, "content", None))
        content, think_stripped = self._normalize_reply_text(raw_content, _transport_strict())
        self._stamp_call_meta(
            model=model, finish_reason=finish, raw_finish_reason=raw_finish, usage=usage,
            usage_source="provider", served_model=served_model, think_stripped=think_stripped,
            dangling=has_dangling_think(raw_content), provider=serving_provider,
        )
        return {
            "content": content,
            "tool_calls": tool_calls,
            "finish_reason": finish,
            "served_model": served_model,
        }

    @staticmethod
    def _parse_json_response(response: str) -> Optional[Dict[str, Any]]:
        """尽力把模型输出解析成 JSON 对象；失败返回 None（不抛异常）。"""
        return LLMClient._parse_json_response_ex(response)[0]

    @staticmethod
    def _parse_json_response_ex(response: str, *, unparsed: Any = None) -> Tuple[Any, bool]:
        """(value, repaired_truncation): the _parse_json_response value, plus whether the
        bracket-repair branch had to close an unterminated string / structure (or drop a
        dangling trailing comma) for it to parse. (unparsed, False) when nothing parses:
        (None, False) by default, the same as a reply of JSON null; chat_json passes a
        sentinel to tell the two apart."""
        cleaned = response.strip()
        # 清理 markdown 代码块标记
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\n?```\s*$', '', cleaned)
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned), False
        except json.JSONDecodeError:
            pass

        # 提取首个 JSON 对象（应对模型在 JSON 前后加说明文字）
        match = re.search(r'\{[\s\S]*\}', cleaned)
        if match:
            try:
                return json.loads(match.group()), False
            except json.JSONDecodeError:
                cleaned = match.group()
        else:
            # 没有闭合的 '}'：截断式输出，从首个 '{' 起修复
            brace = cleaned.find('{')
            if brace < 0:
                return unparsed, False
            cleaned = cleaned[brace:]

        # 补全被 max_tokens 截断的字符串/括号：扫描跟踪字符串态与括号栈，
        # 按嵌套逆序闭合（简单计数会按错误顺序拼接 ]} ）。
        stack: List[str] = []
        in_string = False
        escaped = False
        for ch in cleaned:
            if escaped:
                escaped = False
                continue
            if ch == '\\':
                escaped = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch in '{[':
                stack.append(ch)
            elif ch == '}' and stack and stack[-1] == '{':
                stack.pop()
            elif ch == ']' and stack and stack[-1] == '[':
                stack.pop()

        repaired = cleaned
        if in_string:
            repaired += '"'
        # 去掉悬空的尾逗号（如 '{"a": 1,' 截断）
        repaired = re.sub(r',\s*$', '', repaired)
        for opener in reversed(stack):
            repaired += '}' if opener == '{' else ']'
        try:
            return json.loads(repaired), repaired != cleaned
        except json.JSONDecodeError:
            return unparsed, False

    # ------------------------------------------------------------------
    # 共享辅助
    # ------------------------------------------------------------------
    def _split_system_message(self, messages: List[Dict[str, str]]):
        """从对话消息中拆分出 system 指令。"""
        system_text = None
        conversation = []
        for msg in messages:
            if msg.get("role") == "system":
                if system_text is None:
                    system_text = msg["content"]
                else:
                    system_text += "\n\n" + msg["content"]
            else:
                conversation.append(msg)
        return system_text, conversation

    def _flatten_prompt(
        self,
        messages: List[Dict[str, str]],
        response_format: Optional[Dict] = None
    ) -> str:
        """将多轮消息扁平化为单条 prompt（CLI 提供方使用）。"""
        system_text, conversation = self._split_system_message(messages)

        prompt_parts: List[str] = []
        if system_text:
            prompt_parts.append(f"SYSTEM INSTRUCTIONS:\n{system_text}\n")

        if response_format and response_format.get("type") == "json_object":
            prompt_parts.append(
                "IMPORTANT: Respond with valid JSON only. "
                "No markdown, no explanation, just pure JSON.\n"
            )

        for msg in conversation:
            role = msg.get("role", "user").upper()
            prompt_parts.append(f"{role}: {msg['content']}")

        return "\n\n".join(prompt_parts)

    def _clean_content(self, content: str) -> str:
        """移除推理模型的 <think> 标签。"""
        return re.sub(r'<think>[\s\S]*?</think>', '', content).strip()

    def _normalize_reply_text(self, raw: str, strict: bool, json_reply: bool = False) -> tuple:
        """(text, think_stripped) of an API reply's flattened content.

        ``strict`` (LLM_TRANSPORT_STRICT, default on): llm_text.strip_think also removes an
        orphan ``</think>`` and a dangling ``<think>`` cut by the output cap, except inside a
        ``json_reply`` that opens with its JSON value. Off: the legacy _clean_content, which
        removes closed blocks only.
        """
        if strict:
            return strip_think(raw, json_reply=json_reply)
        cleaned = self._clean_content(raw)
        return cleaned, cleaned != raw.strip()

    def _coerce_temperature(self, temperature: float, provider: str,
                            extra_body: Optional[Dict]) -> float:
        """按提供方约束修正采样温度（``provider`` 为实际服务本次请求的提供方）。

        Kimi K2.7 Code 网关（api.kimi.com/coding，model=kimi-k2.7 / kimi-for-coding）对
        temperature 做硬校验，只接受单一允许值：开启推理时必须 ``1``，关闭推理
        (thinking.type=disabled) 时必须 ``0.6``，传入其它值一律 400 invalid_request_error。
        本仓库各调用点（report/oasis/graphiti/zep）会传 0.0~0.7 等任意温度并对失败重试
        （graphiti 还做升温重试），全部会被网关拒绝。故对 kimi 提供方按本次实际发送的
        ``extra_body``（_apply_reasoning_options 的返回值，是否关推理）强制为网关允许值；其它
        提供方原样返回，行为不变。INFRA-6: 规则本身在 provider_overrides.provider_temperature
        （与 openai_compat_request_overrides 同源）；按已发送的 extra_body 判定而非再读一次
        推理开关，推理体与温度不会在同一请求内错配。
        """
        return provider_temperature(provider, temperature, extra_body)

    def _apply_reasoning_options(self, kwargs: Dict[str, Any], provider: str) -> Optional[Dict]:
        """Apply reasoning controls for ``provider``, the provider actually serving this request.

        A fallback client intentionally retains the global primary configuration, and the
        fast-tier second client serves as LLM_FAST_PROVIDER, so request options are resolved
        from the serving provider rather than Config.LLM_PROVIDER (INFRA-6: through
        provider_overrides, the rules every OpenAI-compatible caller shares). Quotio's
        Antigravity alias additionally accepts the OpenAI-compatible ``reasoning_effort``
        field. Returns the extra_body sent, or None when the request carries none.
        """
        extra_body = openai_compat_request_overrides(provider)["extra_body"] or None
        if extra_body:
            kwargs["extra_body"] = extra_body
        if self._is_fallback:
            reasoning_effort = (
                os.environ.get("LLM_FALLBACK_REASONING_EFFORT", "") or ""
            ).strip().lower()
            if reasoning_effort:
                # Config.validate rejects an invalid value at startup; this per-call guard
                # covers processes that never ran it (sim / script children).
                if reasoning_effort not in FALLBACK_REASONING_EFFORTS:
                    raise ValueError(
                        "LLM_FALLBACK_REASONING_EFFORT must be one of "
                        + "/".join(FALLBACK_REASONING_EFFORTS)
                    )
                kwargs["reasoning_effort"] = reasoning_effort
        return extra_body

    # ------------------------------------------------------------------
    # openai 提供方
    # ------------------------------------------------------------------
    def _chat_openai(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: Optional[Dict] = None,
        tier: str = "strong",
        route: Optional[Tuple[str, bool]] = None,
    ) -> str:
        # EXECPLAN2 I-6-2: 解析本次实际模型与客户端。fast tier 指向不同提供方时用第二客户端，
        # 否则同提供方仅切模型名；关闭路由时 model=self.model、client=self._openai_client。
        # EVAL-10: the fast-tier second client serves the primary provider's routing only; a
        # routing-pinned client (fallback, pinned, non-primary provider) keeps its own endpoint.
        # ``route`` is chat()'s once-per-call _tier_route() result, so the request carries the
        # model chat() caches and meters under (None = resolve it here, one read).
        model, fast_tier = route if route is not None else self._tier_route(tier)
        # INFRA-6: the serving provider (LLM_FAST_PROVIDER on the fast-tier second client) owns
        # the request overrides, the failure attribution and the call metadata below.
        client, serving_provider = self._serving_endpoint(fast_tier)
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            kwargs["response_format"] = response_format

        # 推理模型(kimi/minimax/deepseek/qwen/glm)：默认关闭推理，避免 reasoning 吃光
        # max_tokens 导致 content 为空。非推理提供方不带 extra_body。
        extra_body = self._apply_reasoning_options(kwargs, serving_provider)

        # Kimi K2.7 Code 网关按推理开关硬校验温度（开=1/关=0.6），覆盖调用方温度。
        kwargs["temperature"] = self._coerce_temperature(temperature, serving_provider, extra_body)

        timeout_override = _CALL_TIMEOUT_S.get()
        if timeout_override:
            kwargs["timeout"] = timeout_override
        response = client.chat.completions.create(**kwargs)
        # 捕获精确 token 用量供计量（I-5-0）；无 usage 字段时为 None，chat() 走粗估。
        usage = _usage_from_response(response)
        # INFRA-1: MiniMax 等在配额/鉴权失败时返回无 choices 的 base_resp 信封——抛带提供方原文的
        # LLMEmptyChoices（RuntimeError，可重试、可被配额分类器识别；审查信封则为 LLMContentFiltered），
        # 而非 choices[0] 的 IndexError。
        choices = getattr(response, "choices", None)
        if not choices:
            raise _empty_choices_error(response, serving_provider, model, usage)
        choice = choices[0]
        raw_content = flatten_content(getattr(getattr(choice, "message", None), "content", None))
        raw_finish = getattr(choice, "finish_reason", None)
        finish = normalize_finish_reason(raw_finish)
        strict = _transport_strict()
        json_reply = _is_json_response_format(response_format)
        content, think_stripped = self._normalize_reply_text(raw_content, strict, json_reply)
        # 推理模型在 content 被推理耗尽时会返回空串/None（finish_reason=length）。
        # 明确报错而不是把空串交给下游 JSON 解析，便于定位与重试。strict 模式按剥离推理后的正文判空；
        # 关闭时沿用历史判据（原文判空，返回 _clean_content 结果）。
        empty = not content if strict else not raw_content.strip()
        if empty:
            raise _completion_failure(serving_provider, finish, raw_finish, usage, max_tokens)
        self._stamp_call_meta(
            model=model, finish_reason=finish, raw_finish_reason=raw_finish, usage=usage,
            usage_source="provider", served_model=getattr(response, "model", None),
            think_stripped=think_stripped, dangling=has_dangling_think(raw_content, json_reply=json_reply),
            provider=serving_provider,
        )
        return content

    # ------------------------------------------------------------------
    # claude-cli 提供方
    # ------------------------------------------------------------------
    @staticmethod
    def _claude_cli_env() -> Dict[str, str]:
        """claude-cli 子进程环境：默认剥离 ANTHROPIC_API_KEY。

        历史事故：环境里游离的 ANTHROPIC_API_KEY 会让 `claude` CLI 弃用订阅 OAuth
        改走 API 计费，且 Key 失效时表现为难排查的 401。订阅是本提供方的设计前提，
        故默认剥离；确需 API Key 计费时设 LLM_CLI_USE_API_KEY=true 保留。
        """
        env = dict(os.environ)
        if os.environ.get('LLM_CLI_USE_API_KEY', '').strip().lower() != 'true':
            env.pop('ANTHROPIC_API_KEY', None)
        return env

    @staticmethod
    def _codex_cli_env() -> Dict[str, str]:
        """codex-cli 子进程环境：默认剥离 OPENAI_API_KEY（与 _claude_cli_env 对称，T6.5）。

        游离的 OPENAI_API_KEY 会让 `codex` CLI 弃用 ChatGPT 订阅 OAuth 改走 API 计费。
        订阅是本提供方的设计前提，故默认剥离；确需 API Key 计费时设 LLM_CLI_USE_API_KEY=true 保留。
        """
        env = dict(os.environ)
        if os.environ.get('LLM_CLI_USE_API_KEY', '').strip().lower() != 'true':
            env.pop('OPENAI_API_KEY', None)
        return env

    def _chat_claude_cli(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: Optional[Dict] = None
    ) -> str:
        """通过 Claude Code CLI 调用。

        prompt 经 stdin 传入而非 argv：报告后期的长 prompt 会超 Linux 的 ARG_MAX
        （E2BIG），且 argv 会把 prompt 暴露在进程列表里。
        """
        prompt = self._flatten_prompt(messages, response_format)

        # Pin the model when one is configured (e.g. LLM_MODEL_NAME=claude-opus-4-8) so the
        # CLI doesn't silently fall back to the account's default model. Pass through only
        # claude model ids/aliases; anything else → let the CLI choose (defensive).
        cmd = ["claude", "-p", "--output-format", "json"]
        # XRUN-3: 隔离操作员的全局 ~/.claude hooks——SessionEnd 钩子（claude-island-state.py）曾
        # 让 2769+ 次管线 CLI 调用以空 'Claude CLI failed: ' 失败（钩子被取消 → CLI 非零退出）。
        # --settings 内联 disableAllHooks 已实测保留 OAuth 登录（--bare 会丢登录态，不可用）。
        # LLM_CLI_ISOLATE_HOOKS=false 可恢复继承用户钩子的旧行为。
        if bool(getattr(Config, "LLM_CLI_ISOLATE_HOOKS", True)):
            cmd += ["--settings", '{"disableAllHooks": true}']
        _m = claude_cli_model_arg(self.model)
        if _m:
            cmd += ["--model", _m]

        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True, text=True, timeout=CLI_TIMEOUT,
                cwd="/tmp", env=self._claude_cli_env()
            )

            if result.returncode != 0:
                # stderr may be empty when claude-cli outputs errors to stdout as JSON
                err_detail = (result.stderr or result.stdout or "")[:300]
                logger.error(f"Claude CLI error (rc={result.returncode}): {err_detail}")
                # LLM-5/RPT-14: 两流全空时报告 rc + 合成占位说明，而非裸 'Claude CLI failed: '
                # （曾让整轮报告失败不可诊断）。
                raise RuntimeError(
                    f"Claude CLI failed (rc={result.returncode}): "
                    f"{err_detail or '<no output (timeout/rate-limit/hook suspected)>'}"
                )

            output = None
            try:
                output = json.loads(result.stdout)
                # Detect error envelopes (e.g. is_error / non-success subtype) so the
                # caller's exponential-backoff retry kicks in instead of silently
                # propagating an empty/invalid result (often rate-limit induced).
                if isinstance(output, dict) and (
                    output.get("is_error") or output.get("subtype") not in (None, "success")
                ):
                    # LLM-5: 附带 result/error 载荷——CLI 把人类可读原因放在 result 里
                    # （如 'Claude AI usage limit reached'），丢掉它 = 不可诊断的失败。
                    _payload = str(output.get("result") or output.get("error") or "")[:200]
                    raise RuntimeError(
                        f"Claude CLI error envelope: subtype={output.get('subtype')!r} "
                        f"is_error={output.get('is_error')!r} detail={_payload!r}"
                    )
                content = output.get("result", result.stdout) if isinstance(output, dict) else result.stdout
            except json.JSONDecodeError:
                content = result.stdout.strip()

            raw_content = content
            content = self._clean_content(content)
            if not content:
                raise RuntimeError("Claude CLI returned empty result")
            # INFRA-1: CLI 信封无 finish_reason（成功即 'stop'）；usage/served_model 取自 JSON 信封。
            cli_usage, served_model = _cli_envelope_usage(output)
            self._stamp_call_meta(
                model=getattr(self, "model", None), finish_reason="stop", usage=cli_usage,
                usage_source="cli",
                served_model=served_model, think_stripped=content != raw_content.strip(),
                dangling=has_dangling_think(
                    raw_content, json_reply=_is_json_response_format(response_format)),
            )
            return content

        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Claude CLI timed out after {CLI_TIMEOUT}s") from exc
        except FileNotFoundError as exc:
            raise RuntimeError(
                "未找到 `claude` 可执行文件，请确认已安装 Claude Code CLI 并加入 PATH"
            ) from exc
        except OSError as exc:
            raise RuntimeError(f"Claude CLI 进程启动失败: {exc}") from exc

    # ------------------------------------------------------------------
    # codex-cli 提供方
    # ------------------------------------------------------------------
    def _chat_codex_cli(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: Optional[Dict] = None
    ) -> str:
        """通过 Codex CLI 调用。"""
        prompt = self._flatten_prompt(messages, response_format)

        try:
            result = subprocess.run(
                ["codex", "exec", "--skip-git-repo-check"],
                input=prompt,
                capture_output=True, text=True, timeout=CLI_TIMEOUT,
                cwd="/tmp", env=self._codex_cli_env()
            )

            if result.returncode != 0:
                logger.error(f"Codex CLI error: {result.stderr[:200]}")
                raise RuntimeError(f"Codex CLI failed: {result.stderr[:200]}")

            raw = result.stdout.strip()
            parts = raw.split("\ncodex\n")
            if len(parts) > 1:
                content = parts[-1].strip()
                lines = content.split("\n")
                clean_lines = []
                for line in lines:
                    if line.strip() == "tokens used":
                        break
                    clean_lines.append(line)
                content = "\n".join(clean_lines).strip()
            else:
                content = raw
            cleaned = self._clean_content(content)
            # 与 claude 路径对称：空结果抛 RuntimeError 触发上层退避重试，避免把空串喂给下游 JSON 解析。
            if not cleaned or not cleaned.strip():
                logger.error(f"Codex CLI 返回空结果（stdout 前200: {raw[:200]}）")
                raise RuntimeError("Codex CLI 返回空结果")
            # INFRA-1: codex exec 输出纯文本，无 usage/模型信封。
            self._stamp_call_meta(
                model=getattr(self, "model", None), finish_reason="stop",
                think_stripped=cleaned != content.strip(), dangling=has_dangling_think(content),
            )
            return cleaned

        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Codex CLI timed out after {CLI_TIMEOUT}s") from exc
        except FileNotFoundError as exc:
            raise RuntimeError(
                "未找到 `codex` 可执行文件，请确认已安装 Codex CLI 并加入 PATH"
            ) from exc
        except OSError as exc:
            # 与 claude 路径对称（此前缺失）：非 ENOENT 的进程启动失败（EACCES/ENOMEM…）原本会以
            # 裸 OSError 冒泡，不在 chat() 的重试集合 (RuntimeError, *_RETRYABLE_API_ERRORS) 内
            # → 不重试且直接抛给调用方。包成 RuntimeError 让退避重试生效。
            raise RuntimeError(f"Codex CLI 进程启动失败: {exc}") from exc
