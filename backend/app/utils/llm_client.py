"""
LLM客户端封装

支持三种提供方（由 Config.LLM_PROVIDER 决定，默认 claude-cli）：
  - claude-cli: 通过本机 `claude` CLI 调用（Claude Code 订阅，无需 API Key）
  - codex-cli:  通过本机 `codex` CLI 调用（Codex 订阅，无需 API Key）
  - openai:     OpenAI 兼容 API（需要 LLM_API_KEY），保留作为回退

对外接口统一为 chat() / chat_json()，调用方无需关心底层提供方。
"""

import contextvars
from copy import deepcopy
import hashlib
import json
import logging
import math
import os
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from typing import Optional, Dict, Any, List

from ..config import Config
from .llm_errors import describe_llm_error, is_content_filter_error, is_thinking_required_error
from .logger import get_logger

logger = get_logger('mirofish.llm_client')


def _spending():
    # One fixed-root import identity owns the process latch, context and stop type.
    from ..services.official_data import bridge_module
    return bridge_module("run_spending")


def _raise_spending_stop(exc, *, during_import=False):
    """Preserve the shared stop, including one wrapped by the installed SDK."""
    # Before LLMClient is defined, importing services.official_data would run
    # services/__init__ and import LLMClient back. An optional SDK import failure
    # may only consult an already-loaded shared exception identity.
    spending = sys.modules.get("deerflow_bridge.run_spending") if during_import else _spending()
    if spending is None:
        return
    seen = set()
    pending = [exc]
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if spending.is_spending_stop(current):
            raise current from None
        pending.extend((current.__context__, current.__cause__))


class _ObservedThinkingRefusal(Exception):
    """A recognized HTTP 400 response, with its full quote already retained."""

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
except Exception as exc:  # noqa: BLE001 — openai 不可导入时退化为仅重试 RuntimeError
    _raise_spending_stop(exc, during_import=True)
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
    if is_content_filter_error(exc):
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
    """Content-moderation rejection (MiniMax 422 new_sensitive, Zhipu 400/1301, OpenAI
    content_filter …); the shared classification lives in ``llm_errors``."""
    return is_content_filter_error(exc)


def _note_failover(exc: Optional[BaseException], note: str) -> None:
    """Attach the failover outcome to the primary error that is about to propagate
    (``BaseException.add_note``), so callers' failure records can say whether the fallback
    provider took the call over and, if not, why (unconfigured / skipped / failed).  One
    note per error; a note is a courtesy and never becomes a new failure."""
    if exc is None:
        return
    try:
        if not any(str(n).startswith("fallback") for n in (getattr(exc, "__notes__", None) or [])):
            exc.add_note(note)
    except Exception as exc:  # noqa: BLE001
        _raise_spending_stop(exc)
        pass


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


def reset_provider_circuit_breakers(provider: Optional[str] = None) -> None:
    """人工重试（resume / 新尝试）时清空进程级 422/429 冷却与回退-auth 冷却。

    2026-10-18 事故：run 级断路器每次尝试都重建，但本进程级 _CB_STATE 不随 resume
    重置——冷却到点后放行的唯一一次探测是 llm_client 自己的合成 fast-fail（零网络），
    被分类为 circuit_breaker 喂给新 run 断路器，10 次秒级累积后新尝试立刻再熔断，
    只能重启后端解困。resume 是操作者「提供方可能已修复」的显式声明，应获得一次
    真实探测；若确实仍故障，达到阈值次数后会按设计重新熔断（代价可控）。"""
    with _CB_LOCK:
        if provider:
            _CB_STATE.pop(provider, None)
        else:
            _CB_STATE.clear()
        _FB_AUTH_UNAVAILABLE_UNTIL.clear()


# LLM-3: 回退提供方的 OpenAI 连接池缓存。此前每次失败转移都重建 LLMClient/OpenAI 客户端
# （每次一个新 httpx 连接池 + TLS 握手）；键=(provider, model, base_url)。只缓存底层 OpenAI
# 客户端（官方文档保证线程安全），LLMClient 实例仍逐调用新建，避免 _last_usage 跨线程串档。
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


class EmptyCompletionError(RuntimeError):
    """An OpenAI-compatible provider answered, but with empty content.

    ``finish_reason`` is kept so a caller can tell a reply cut off by its token cap
    (``"length"``, typically a reasoning model spending the budget on reasoning tokens) from
    other empty answers.  It subclasses RuntimeError, so every existing retry and fallback
    path treats it exactly as before.
    """

    def __init__(self, message: str, *, provider: str = "", finish_reason: Optional[str] = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.finish_reason = finish_reason


class LLMClient:
    """LLM客户端 — 支持 claude-cli / codex-cli / openai"""

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.provider = (provider or Config.LLM_PROVIDER or "claude-cli").lower()

        # 最近一次调用的精确 token 用量（OpenAI 兼容路径填充；CLI 路径为 None→按文本粗估）。
        self._last_usage: Optional[Dict[str, int]] = None

        # openai 提供方所需的连接参数（CLI 模式下不使用）
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME

        self._qualified_spending_route()

        if self.provider not in CLI_PROVIDERS and self.provider not in OPENAI_COMPATIBLE_PROVIDERS:
            _supported = " / ".join(repr(p) for p in (*CLI_PROVIDERS, *OPENAI_COMPATIBLE_PROVIDERS))
            raise ValueError(
                f"不支持的 LLM 提供方: {self.provider!r}。可选: {_supported}。"
            )

        # 仅在使用 OpenAI 兼容提供方（openai/kimi）时才创建 OpenAI 客户端（CLI 模式无需 API Key）
        self._openai_client = None
        if self.provider in OPENAI_COMPATIBLE_PROVIDERS:
            if _spending().required():
                self._openai_client = self._build_openai_client(
                    self.provider, self.api_key, self.base_url, model=self.model)
            else:
                self._openai_client = self._build_openai_client(self.provider, self.api_key, self.base_url)

        # EXECPLAN2 I-6-2: 当 fast tier 指向一个完全不同的 OpenAI 兼容提供方时，按需懒构建
        # 的第二个客户端（如本地廉价抽取 + 远端旗舰合成）。仅在 tiered routing 开启且配齐
        # LLM_FAST_PROVIDER/BASE_URL/API_KEY 时才会真正实例化；否则保持 None（同提供方切模型）。
        self._fast_openai_client = None
        # S9: set True on a fallback client so failover never recurses.
        self._is_fallback = False

    @staticmethod
    def _build_openai_client(provider: str, api_key: Optional[str], base_url: Optional[str], *, model=None):
        """构造一个 OpenAI 兼容客户端（供主客户端与 fast-tier 第二客户端复用）。"""
        spending = _spending()
        bound = spending.required()
        if bound:
            spending.check_context()
            if provider not in OPENAI_COMPATIBLE_PROVIDERS:
                spending.deny("unsupported_route")
            if type(api_key) is not str or api_key != Config.LLM_API_KEY:
                spending.deny("unsupported_route")
            spending.qualify_route("openai_chat", base_url, model or Config.LLM_MODEL_NAME,
                                   account_sha256=hashlib.sha256(api_key.encode("utf-8")).hexdigest())
        try:
            from openai import OpenAI
        except Exception as exc:
            _raise_spending_stop(exc)
            if bound:
                spending.deny("unsupported_route")
            raise
        if not api_key:
            if bound:
                spending.deny("invalid_request")
            raise ValueError(f"LLM_PROVIDER={provider} 时必须配置 LLM_API_KEY")
        client_kwargs: Dict[str, Any] = {"api_key": api_key, "base_url": base_url}
        if bound:
            # Independent of HTTP/2/custom-client availability. Ambient account
            # headers cannot silently change the reviewed private route.
            client_kwargs.update(max_retries=0, organization="", project="")
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
        # 不带可识别的 UA 会被拒绝（access_terminated_error）。
        if provider == "kimi":
            client_kwargs["default_headers"] = {"User-Agent": Config.LLM_USER_AGENT}
        # R2-EXEC-6: 当 LLM_HTTP2 开启时，注入一个调优过的 httpx 客户端（HTTP/2 多路复用 +
        # 更大 keepalive 池）并把 SDK 自带重试关掉（max_retries=0，由 chat() 的退避循环统一负责）。
        # 默认（未配置 LLM_HTTP2 / 为 false）返回 None → 沿用 OpenAI SDK 自带 httpx 客户端，
        # 行为与现状逐字节一致（degrade-safe）。
        try:
            http_client = LLMClient._build_http_client()
            if bound and http_client is None:
                from openai import DefaultHttpxClient
                http_client = DefaultHttpxClient(follow_redirects=False, trust_env=False)
            if http_client is not None:
                client_kwargs["http_client"] = http_client
                client_kwargs["max_retries"] = 0
            return OpenAI(**client_kwargs)
        except Exception as exc:
            _raise_spending_stop(exc)
            if bound:
                spending.deny("invalid_request")
            raise

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
        except Exception as exc:  # httpx 理应随 openai 安装；缺失则回退 SDK 默认客户端
            _raise_spending_stop(exc)
            return None
        keepalive = int(getattr(Config, "LLM_HTTP_KEEPALIVE", 128) or 128)
        limits = httpx.Limits(
            max_keepalive_connections=keepalive,
            max_connections=keepalive + 32,
        )
        # 连接快、读/写慢：长文生成需要大读超时，避免 httpx 默认 5s 腰斩。
        timeout = httpx.Timeout(600.0, connect=10.0)
        strict_http = {"follow_redirects": False, "trust_env": False} if _spending().required() else {}
        try:
            return httpx.Client(http2=True, limits=limits, timeout=timeout, **strict_http)
        except Exception as exc:  # h2 未安装或协商失败 → 回退 HTTP/1.1（不影响管线运行）
            _raise_spending_stop(exc)
            logger.warning("HTTP/2 client construction failed; trying HTTP/1.1: %s",
                           type(exc).__name__ if strict_http else str(exc))
            try:
                return httpx.Client(http2=False, limits=limits, timeout=timeout, **strict_http)
            except Exception as exc2:  # 极端情况下连 http1 调优客户端也失败 → 回退 SDK 默认
                _raise_spending_stop(exc2)
                logger.warning("HTTP client construction failed; using SDK default: %s",
                               type(exc2).__name__ if strict_http else str(exc2))
                return None

    def _qualified_spending_route(self, *, model=None, endpoint=None):
        spending = _spending()
        if not spending.required():
            return None
        spending.check_context()
        if (self.provider not in OPENAI_COMPATIBLE_PROVIDERS
                or getattr(self, "_is_fallback", False)
                or getattr(Config, "LLM_TIERED_ROUTING", False)
                or type(self.api_key) is not str or self.api_key != Config.LLM_API_KEY):
            spending.deny("unsupported_route")
        return spending.qualify_route(
            "openai_chat", self.base_url if endpoint is None else endpoint,
            self.model if model is None else model,
            account_sha256=hashlib.sha256(self.api_key.encode("utf-8")).hexdigest())

    # ------------------------------------------------------------------
    # EXECPLAN2 I-6-2: 双层模型路由（fast / strong）
    # ------------------------------------------------------------------
    def _model_for_tier(self, tier: Optional[str]) -> str:
        """按 tier 解析实际使用的模型名。

        - tiered routing 关闭（默认）→ 一律返回 self.model（行为与现状逐字节一致）。
        - tier='fast'  → Config.fast_model()（未配置 LLM_FAST_MODEL 时回退到当前模型，不报错）。
        - tier='strong'/None/未知 → Config.strong_model()（同样回退到当前模型）。
        CLI 订阅提供方只有单一订阅模型，tier 在 _chat_* 中被忽略，此处返回值仅用于计量一致性。
        """
        # The fallback client is already fully resolved from LLM_FALLBACK_MODEL.
        # Never replace it with the primary provider's global fast/strong alias:
        # that sent MiniMax-M3 to Quotio's Antigravity endpoint and made every
        # production failover return HTTP 400.
        if getattr(self, "_is_fallback", False):
            return self.model
        if not getattr(Config, "LLM_TIERED_ROUTING", False):
            return self.model
        if tier == "fast":
            return Config.fast_model() or self.model
        return Config.strong_model() or self.model

    def _fast_provider_client(self):
        """若 fast tier 指向不同的 OpenAI 兼容提供方，返回（懒构建的）第二客户端，否则 None。

        需要 LLM_FAST_PROVIDER + LLM_FAST_BASE_URL + LLM_FAST_API_KEY 三者齐备且该提供方
        为 OpenAI 兼容；缺任一则回退为「同提供方切模型」（返回 None）。构建失败同样回退 None，
        绝不让 fast tier 的误配置把整条调用打挂（graceful degradation）。
        """
        if _spending().required():
            _spending().deny("unsupported_route")
        fp = getattr(Config, "LLM_FAST_PROVIDER", None)
        fb = getattr(Config, "LLM_FAST_BASE_URL", None)
        fk = getattr(Config, "LLM_FAST_API_KEY", None)
        if not (fp and fb and fk) or fp not in OPENAI_COMPATIBLE_PROVIDERS:
            return None
        if self._fast_openai_client is None:
            try:
                self._fast_openai_client = self._build_openai_client(fp, fk, fb)
            except Exception as exc:  # 误配置不应中断调用，记录后回退主客户端
                _raise_spending_stop(exc)
                logger.warning(f"fast-tier 第二客户端构建失败，回退主客户端: {exc}")
                return None
        return self._fast_openai_client

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
        """
        # EXECPLAN2 I-6-2: 解析本次调用实际使用的模型（fast/strong）。关闭路由时 = self.model。
        bound = self._qualified_spending_route() is not None
        model = self._model_for_tier(tier)
        # EXECPLAN2 I-6-0/I-5-0/I-5-3: 内容寻址缓存命中直接返回；否则正常调用后记录
        # token/延迟/成本计量并做预算检查。计量默认开（开销极小），缓存/预算默认关。
        from .telemetry import LLMMeter, LLMCache, get_run_context, check_budget, estimate_tokens
        run_id, stage = get_run_context()
        if bound:
            # Reuse the caller's durable binding even if observational telemetry
            # context was not copied. Never invent a spending/global run identity.
            run_id = _spending().current_binding()["pipeline_id"]
            stage = _spending().current_operation()["stage"]
        cache_key = None
        if Config.LLM_CACHE_ENABLED:
            # 缓存键纳入解析后的 model，避免 fast/strong 两档结果互相串档。
            cache_key = LLMCache.key(self.provider, model, messages, temperature, max_tokens, response_format)
            hit = LLMCache.get(cache_key)
            if hit is not None:
                if Config.LLM_TELEMETRY_ENABLED:
                    LLMMeter.record(self.provider, model, 0, 0, 0.0, cached=True, stage=stage, run_id=run_id)
                return hit

        last_error: Optional[Exception] = None
        result: Optional[str] = None
        # LLM-2: 回退提供方接管时，回退客户端自己的 chat() 已经计量过这次调用（provider=回退方、
        # 精确 token）。外层若再按主提供方记一次，失败转移最多的 run 的 token/成本会 ~2x 虚增且
        # by_model 归属错乱。置位后跳过外层计量。
        served_by_fallback = False
        started = time.monotonic()
        self._last_usage = None
        # Circuit breaker: if the primary is in a content-filter/quota cooldown, skip the doomed
        # primary attempt entirely and go straight to the fallback (prevents the futile-call flood).
        if _cb_tripped(self.provider) and not self._is_fallback:
            _cb_err = RuntimeError(f"circuit-breaker: {self.provider} in 422/429 cooldown")
            _fb = self._try_fallback(messages, temperature, max_tokens, response_format, _cb_err)
            if _fb is not None:
                result = _fb
                served_by_fallback = True
            else:
                # 双通道皆不可用：主提供方处于熔断冷却，回退失败/未配置。此前会继续掉进
                # 完整的 3 次主重试（指数退避睡眠）+ 第二次回退 —— 双中断期间每次 chat()
                # 白烧 5 次注定失败的调用（2026-07-08 实测：最高 231 错误/分钟持续 26 小时）。
                # 直接抛出（复用穷尽路径的异常类型），让调用方快速失败。
                _err = RuntimeError(
                    f"LLM 调用失败：主提供方 {self.provider} 处于 422/429 熔断冷却，"
                    f"且回退提供方不可用"
                )
                for _note in getattr(_cb_err, "__notes__", None) or []:
                    _note_failover(_err, str(_note))
                raise _err
        for attempt in range(MAX_RETRIES):
            if result is not None:
                break
            try:
                if self.provider in OPENAI_COMPATIBLE_PROVIDERS:
                    result = self._chat_openai(messages, temperature, max_tokens, response_format, tier=tier)
                elif self.provider == "codex-cli":
                    # CLI 订阅提供方只有单一订阅模型，tier 在此为 no-op。
                    result = self._chat_codex_cli(messages, temperature, max_tokens, response_format)
                else:
                    result = self._chat_claude_cli(messages, temperature, max_tokens, response_format)
                _cb_reset(self.provider)  # primary succeeded → clear its 422/429 streaks
                break
            except (RuntimeError, *_RETRYABLE_API_ERRORS) as exc:
                _raise_spending_stop(exc)
                if bound and not isinstance(exc, EmptyCompletionError):
                    _spending().deny("invalid_request")
                last_error = exc
                if _is_deterministic_auth_error(exc):
                    logger.warning(
                        "LLM authentication failure is deterministic; skipping retries: %s",
                        _err_brief(exc),
                    )
                    break
                if _is_quota(exc):
                    _cb_record_429(self.provider)  # LLM-3: 连续配额失败达阈值 → 冷却直连回退
                if attempt < MAX_RETRIES - 1:
                    delay = _retry_delay(exc, attempt)
                    logger.warning(
                        f"LLM 调用失败 (第 {attempt + 1}/{MAX_RETRIES} 次)，{delay}s 后重试: {exc}"
                    )
                    time.sleep(delay)
            except Exception as exc:  # noqa: BLE001 — non-retryable (e.g. 422 content-filter): stop retrying, try fallback
                _raise_spending_stop(exc)
                if bound:
                    _spending().deny("invalid_request")
                last_error = exc
                if _is_content_filter(exc):
                    _cb_record_422(self.provider)  # count toward tripping the breaker
                # 2026-10-18 修复：先确认回退提供方真的配置了再宣称「转回退」——此前
                # LLM_FALLBACK_PROVIDER 未配置时这行日志仍打印 26 次「转回退提供方」，
                # 与事实相反（_try_fallback 立即返回 None），排障时误导严重。
                _fb_configured = bool(
                    (os.environ.get("LLM_FALLBACK_PROVIDER", "") or "").strip()
                ) and not getattr(self, "_is_fallback", False)
                if _fb_configured:
                    logger.warning(f"LLM 调用遇不可重试错误，转回退提供方: {_err_brief(exc)}")
                else:
                    logger.warning(
                        "LLM 调用遇不可重试错误（回退提供方未配置，保留原始错误）: %s",
                        _err_brief(exc),
                    )
                break
        if result is None:
            if bound:
                _spending().deny("invalid_request")
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

        if Config.LLM_TELEMETRY_ENABLED and not served_by_fallback:
            latency_ms = (time.monotonic() - started) * 1000.0
            usage = self._last_usage
            if usage:
                pt, ct = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
            elif not bound:
                # 无精确 usage（CLI 提供方）→ 按文本长度粗估
                pt = sum(estimate_tokens(str(m.get("content", ""))) for m in messages)
                ct = estimate_tokens(result)
            # 用解析后的 model 计量，使 by_model 维度区分 fast/strong 用量与成本。
            if usage or not bound:
                LLMMeter.record(self.provider, model, pt, ct, latency_ms, cached=False, stage=stage, run_id=run_id)
        if Config.LLM_CACHE_ENABLED and cache_key is not None:
            LLMCache.put(cache_key, result)
        if Config.LLM_RUN_BUDGET_TOKENS or Config.LLM_RUN_BUDGET_USD:
            check_budget(run_id)  # 超预算抛 BudgetExceeded
        return result

    def _try_fallback(self, messages: List[Dict[str, str]], temperature: float,
                      max_tokens: int, response_format: Optional[Dict],
                      primary_error: Optional[Exception]) -> Optional[str]:
        """QUALITY-OPT S9: retry the request once on a configured fallback provider when the
        primary exhausts retries / hits a content-filter. Off unless LLM_FALLBACK_PROVIDER is
        set; never recurses (the fallback client has failover disabled). Returns text or None."""
        if primary_error is not None:
            _raise_spending_stop(primary_error)
        if _spending().required():
            _spending().deny("unsupported_route")
        if getattr(self, "_is_fallback", False):
            return None  # the fallback client never recurses (its error is reported by the primary)
        fb_provider = (os.environ.get("LLM_FALLBACK_PROVIDER", "") or "").strip().lower()
        if not fb_provider:
            _note_failover(primary_error, "fallback: not configured (LLM_FALLBACK_PROVIDER unset)")
            return None
        if fb_provider == self.provider:
            _note_failover(primary_error,
                           f"fallback: skipped (LLM_FALLBACK_PROVIDER={fb_provider} is the primary provider)")
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
            _note_failover(primary_error, f"fallback {fb_provider}: skipped (LLM_FALLBACK_MODEL unset)")
            return None
        auth_key = (fb_provider, fb_model or "", fb_base_url or "")
        with _CB_LOCK:
            auth_unavailable_until = _FB_AUTH_UNAVAILABLE_UNTIL.get(auth_key, 0.0)
        if auth_unavailable_until > time.monotonic():
            logger.warning(
                "Skipping fallback provider %s during deterministic-failure cooldown",
                fb_provider,
            )
            _note_failover(primary_error, f"fallback {fb_provider}: skipped (deterministic-failure cooldown)")
            return None
        try:
            fb = LLMClient(
                provider=fb_provider,
                model=fb_model,
                api_key=(os.environ.get("LLM_FALLBACK_API_KEY", "") or None),
                base_url=fb_base_url,
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
            with _CB_LOCK:
                _FB_AUTH_UNAVAILABLE_UNTIL.pop(auth_key, None)
            logger.info(f"回退提供方 {fb_provider} 成功接管本次调用")
            return out
        except Exception as e:  # noqa: BLE001 — fallback failed too; caller raises the primary error
            _raise_spending_stop(e)
            # 确定性失败（401 凭据坏 / 400 invalid-model 类）进入进程级冷却：重试修不好，
            # 并行 worker 不该反复对同一注定失败的回退发起昂贵调用。服务重启或修好配置自然清零。
            if _is_deterministic_auth_error(e) or _is_deterministic_invalid_request_error(e):
                with _CB_LOCK:
                    _FB_AUTH_UNAVAILABLE_UNTIL[auth_key] = (
                        time.monotonic() + _FB_AUTH_COOLDOWN_S
                    )
            logger.error(f"回退提供方 {fb_provider} 也失败: {_err_brief(e)}")
            _note_failover(primary_error,
                           f"fallback {fb_provider}: failed ({describe_llm_error(e, max_chars=80)})")
            return None

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        tier: str = "strong"
    ) -> Dict[str, Any]:
        """发送聊天请求并返回解析后的 JSON。

        解析失败时先做本地修复（提取 JSON 块、补全被 max_tokens 截断的括号），
        仍失败则降温重发一次。单次格式抖动不再让上层（如报告大纲）直接退化。

        tier（EXECPLAN2 I-6-2）透传给 chat()：结构化/机械型 JSON 调用（子查询分解、
        受访者选择、图谱抽取）可传 tier='fast' 路由到廉价档；默认 'strong' 行为不变。
        """
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
        if _spending().required():
            raise ValueError("LLM returned invalid JSON") from None
        raise ValueError(f"LLM返回的JSON格式无效: {last_response[:500]}")

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
        if _spending().required():
            _spending().check_context()
            return False
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
            {"content": str, "tool_calls": [{"id","name","arguments"(dict)}]}。无工具调用时 tool_calls=[]。
        Raises:
            RuntimeError: 非原生提供方调用 / SDK 失败。
        """
        if _spending().required():
            _spending().deny("unsupported_route")
        if self._openai_client is None:
            raise RuntimeError("chat_with_tools 仅支持 OpenAI 兼容提供方")
        # LLM-1/RPT-10: 熔断预检——冷却期内直接抛错（调用方 report_agent 捕获后降级 ReAct，
        # ReAct 走 chat() 自带的重试+回退链），不再对被审查/限流的提供方发一次注定失败的原生调用。
        if _cb_tripped(self.provider):
            raise RuntimeError(f"chat_with_tools: 提供方 {self.provider} 处于 422/429 熔断冷却，回退 ReAct")
        # EXECPLAN2 I-6-2: 解析模型/客户端（默认 strong = 当前模型/主客户端，工具调用行为不变）。
        model = self._model_for_tier(tier)
        client = self._openai_client
        if (not self._is_fallback
                and getattr(Config, "LLM_TIERED_ROUTING", False)
                and tier == "fast"):
            fast_client = self._fast_provider_client()
            if fast_client is not None:
                client = fast_client
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": tools_schema,
            "tool_choice": "auto",
        }
        extra_body = self._apply_reasoning_options(kwargs, max_tokens)
        # Kimi K2.7 Code 网关按推理开关硬校验温度（开=1/关=0.6），覆盖调用方温度。
        kwargs["temperature"] = self._coerce_temperature(temperature, extra_body)
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
                response = self._create_completion(client, kwargs, temperature, max_tokens)
                _cb_reset(self.provider)
                break
            except (RuntimeError, *_RETRYABLE_API_ERRORS) as exc:
                _raise_spending_stop(exc)
                last_error = exc
                if _is_quota(exc):
                    _cb_record_429(self.provider)
                if attempt < MAX_RETRIES - 1:
                    delay = _retry_delay(exc, attempt)
                    logger.warning(
                        f"chat_with_tools 调用失败 (第 {attempt + 1}/{MAX_RETRIES} 次)，{delay}s 后重试: {_err_brief(exc)}"
                    )
                    time.sleep(delay)
            except Exception as exc:  # noqa: BLE001 — 不可重试（如 422 内容审查）：记熔断后快速失败
                _raise_spending_stop(exc)
                last_error = exc
                if _is_content_filter(exc):
                    _cb_record_422(self.provider)
                logger.warning(f"chat_with_tools 遇不可重试错误: {_err_brief(exc)}")
                break
        if response is None:
            raise last_error if last_error is not None else RuntimeError("chat_with_tools 调用失败")
        if Config.LLM_TELEMETRY_ENABLED:
            try:
                _u = getattr(response, "usage", None)
                _pt = int(getattr(_u, "prompt_tokens", 0) or 0) if _u is not None else 0
                _ct = int(getattr(_u, "completion_tokens", 0) or 0) if _u is not None else 0
                LLMMeter.record(self.provider, model, _pt, _ct,
                                (time.monotonic() - _started) * 1000.0,
                                cached=False, stage=_stage, run_id=_run_id)
            except Exception as exc:  # noqa: BLE001 — 计量失败不影响返回
                _raise_spending_stop(exc)
                pass
        if Config.LLM_RUN_BUDGET_TOKENS or Config.LLM_RUN_BUDGET_USD:
            check_budget(_run_id)  # 超预算抛 BudgetExceeded
        choice = response.choices[0]
        msg = choice.message
        tool_calls = []
        for tc in (getattr(msg, "tool_calls", None) or []):
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except (json.JSONDecodeError, TypeError):
                args = {}
            tool_calls.append({"id": tc.id, "name": tc.function.name, "arguments": args})
        return {
            "content": self._clean_content(msg.content or ""),
            "tool_calls": tool_calls,
        }

    @staticmethod
    def _parse_json_response(response: str) -> Optional[Dict[str, Any]]:
        """尽力把模型输出解析成 JSON 对象；失败返回 None（不抛异常）。"""
        cleaned = response.strip()
        # 清理 markdown 代码块标记
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\n?```\s*$', '', cleaned)
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 提取首个 JSON 对象（应对模型在 JSON 前后加说明文字）
        match = re.search(r'\{[\s\S]*\}', cleaned)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                cleaned = match.group()
        else:
            # 没有闭合的 '}'：截断式输出，从首个 '{' 起修复
            brace = cleaned.find('{')
            if brace < 0:
                return None
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
            return json.loads(repaired)
        except json.JSONDecodeError:
            return None

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

    def _coerce_temperature(self, temperature: float, extra_body: Optional[Dict]) -> float:
        """按提供方约束修正采样温度。

        Kimi K2.7 Code 网关（api.kimi.com/coding，model=kimi-k2.7 / kimi-for-coding）对
        temperature 做硬校验，只接受单一允许值：开启推理时必须 ``1``，关闭推理
        (thinking.type=disabled) 时必须 ``0.6``，传入其它值一律 400 invalid_request_error。
        本仓库各调用点（report/oasis/graphiti/zep）会传 0.0~0.7 等任意温度并对失败重试
        （graphiti 还做升温重试），全部会被网关拒绝。故在此对 kimi 提供方按本次实际发送的
        ``extra_body``（是否关推理）强制为网关允许值；其它提供方原样返回，行为不变。
        """
        if self.provider != 'kimi':
            return temperature
        thinking_disabled = bool(extra_body and (extra_body.get("thinking") or {}).get("type") == "disabled")
        return 0.6 if thinking_disabled else 1.0

    def _apply_reasoning_options(self, kwargs: Dict[str, Any], max_tokens: Optional[int] = None) -> Optional[Dict]:
        """Apply reasoning controls for the provider actually serving this request.

        A fallback client intentionally retains the global primary configuration, so request
        options must be resolved from ``self.provider`` rather than Config.LLM_PROVIDER.
        Quotio's Antigravity alias additionally accepts the OpenAI-compatible
        ``reasoning_effort`` field.  A model that must reason although reasoning was meant to be
        off (``Config.reasoning_forced``: glm-5.x, or a refusal learned at runtime) gets the
        accepted reasoning body and ``max_tokens`` (the caller's value) plus reasoning headroom.
        """
        model = kwargs.get("model") or self.model
        extra_body = Config.reasoning_extra_body(self.provider, model)
        if extra_body:
            kwargs["extra_body"] = extra_body
        else:
            kwargs.pop("extra_body", None)
        if max_tokens is not None and "max_tokens" in kwargs:
            kwargs["max_tokens"] = (Config.thinking_headroom(max_tokens)
                                    if Config.reasoning_forced(self.provider, model) else max_tokens)
        if self._is_fallback:
            reasoning_effort = (
                os.environ.get("LLM_FALLBACK_REASONING_EFFORT", "") or ""
            ).strip().lower()
            if reasoning_effort:
                if reasoning_effort not in {"minimal", "low", "medium", "high"}:
                    raise ValueError(
                        "LLM_FALLBACK_REASONING_EFFORT must be one of "
                        "minimal/low/medium/high"
                    )
                kwargs["reasoning_effort"] = reasoning_effort
        return extra_body

    def _create_completion(self, client: Any, kwargs: Dict[str, Any], temperature: float,
                           max_tokens: Optional[int]) -> Any:
        """``client.chat.completions.create``, resent once when the model refuses a request that
        disabled reasoning (glm-5.3 since 2026-10-18: HTTP 400 / 1210).  The refusal is remembered
        for this process (``Config.note_thinking_refused``), so later calls for the same model send
        the accepted body straight away; any other error propagates unchanged."""
        try:
            return self._physical_completion(client, kwargs)
        except Exception as exc:  # noqa: BLE001 — only the thinking refusal is handled here
            _raise_spending_stop(exc)
            observed = isinstance(exc, _ObservedThinkingRefusal)
            if not (observed or (not _spending().required()
                    and Config.disables_thinking(kwargs.get("extra_body"))
                    and is_thinking_required_error(exc))):
                raise
            model = kwargs.get("model") or self.model
            if Config.note_thinking_refused(self.provider, model):
                logger.warning(
                    "%s/%s refuses requests that disable reasoning (%s); resending with reasoning on "
                    "at the lowest accepted effort, and later calls do the same",
                    self.provider, model, "observed HTTP 400" if observed else _err_brief(exc))
        extra_body = self._apply_reasoning_options(kwargs, max_tokens)
        kwargs["temperature"] = self._coerce_temperature(temperature, extra_body)
        return self._physical_completion(client, kwargs)

    def _check_spending_sdk(self, client, model):
        """Reject hidden sends and overrides in the closed synchronous SDK profile."""
        import httpcore
        import httpx
        from openai import DefaultHttpxClient, OpenAI

        spending = _spending()
        if type(client) is not OpenAI:
            spending.deny("unsupported_route")
        route_id = self._qualified_spending_route(model=model, endpoint=str(client.base_url))
        http = client._client
        expected_headers = {"User-Agent": Config.LLM_USER_AGENT} if self.provider == "kimi" else {}
        if (client.max_retries != 0 or client.default_query
                or client._custom_headers != expected_headers
                or client.organization or client.project
                or client._api_key_provider is not None or client.api_key != self.api_key
                or type(http) not in {httpx.Client, DefaultHttpxClient}
                or http._trust_env is not False
                or http.follow_redirects is not False or http.auth is not None
                or http.params or http.cookies
                or set(http.headers) - {"accept", "accept-encoding", "connection", "user-agent"}
                or any(http.event_hooks.values()) or any(http._mounts.values())
                or self._unsafe_transport_logging()):
            spending.deny("unsupported_route")
        # Follow the existing strict world-policy transport proof without changing
        # that policy. An arbitrary transport/subclass can hide more than one send.
        transport = http._transport
        if (type(transport) not in {httpx.HTTPTransport, httpx.MockTransport}
                or (type(transport) is httpx.HTTPTransport
                    and (type(transport._pool) is not httpcore.ConnectionPool
                         or transport._pool._retries != 0))):
            spending.deny("unsupported_route")
        return route_id

    @staticmethod
    def _unsafe_transport_logging():
        # SDK debug logs contain request bodies, httpcore debug traces include
        # headers/errors, and httpx INFO includes a provider-controlled reason
        # phrase. Reject these settings; never mutate shared legacy log levels.
        names = set(logging.Logger.manager.loggerDict) | {"openai", "httpcore", "httpx"}
        for name in names:
            for prefix, level in (("openai", logging.DEBUG), ("httpcore", logging.DEBUG),
                                  ("httpx", logging.INFO)):
                if (name == prefix or name.startswith(prefix + ".")) and logging.getLogger(name).isEnabledFor(level):
                    return True
        return False

    @staticmethod
    def _spending_usage(response, *, model):
        """Raw provider counts only; no text estimator, absent-as-zero or invoice."""
        if isinstance(response, _ObservedThinkingRefusal):
            return None
        from openai.types.chat import ChatCompletion, ChatCompletionMessage
        from openai.types.completion_usage import CompletionUsage

        usage = getattr(response, "usage", None)
        counts = {}
        for raw_name, field in (("prompt_tokens", "input_tokens"),
                                ("completion_tokens", "output_tokens")):
            value = getattr(usage, raw_name, None)
            if value is not None:
                counts[field] = value
        observation = {"kind": "provider_reported" if counts else "missing", **counts}
        request_id = getattr(response, "id", None)
        if request_id is not None:
            observation["provider_request_id"] = request_id
        # SDK construction is permissive: even HTTP 200 {"error": ...} can
        # become a ChatCompletion. Preserve any usage but mark malformed or
        # unqualified response envelopes unknown before application parsing.
        choices = getattr(response, "choices", None)
        message = getattr(choices[0], "message", None) if isinstance(choices, list) and len(choices) == 1 else None
        if (not isinstance(response, ChatCompletion) or getattr(response, "model", None) != model
                or not isinstance(message, ChatCompletionMessage)
                or getattr(message, "role", None) != "assistant"
                or (getattr(message, "content", None) is not None and not isinstance(message.content, str))
                or getattr(message, "tool_calls", None) or getattr(message, "function_call", None)
                or getattr(response, "error", None) is not None
                or (usage is not None and not isinstance(usage, CompletionUsage))):
            observation["outcome"] = "unknown"
        return observation

    def _physical_completion(self, client, kwargs):
        spending = _spending()
        if not spending.required():
            return client.chat.completions.create(**kwargs)
        spending.check_context()
        try:
            # Freeze nested inputs so the hash, quote and physical body use the
            # same request even if a caller later mutates its message list.
            wire = deepcopy(kwargs)
            allowed = {"model", "messages", "temperature", "max_tokens",
                       "response_format", "extra_body", "timeout"}
            if set(wire) - allowed:
                spending.deny("unsupported_route")
            messages = wire.get("messages")
            if (not isinstance(messages, list) or not messages
                    or any(not isinstance(m, dict) or set(m) != {"role", "content"}
                           or m["role"] not in {"system", "user", "assistant"}
                           or not isinstance(m["content"], str) for m in messages)):
                spending.deny("unsupported_route")
            output = wire.get("max_tokens")
            if type(output) is not int or output <= 0:
                spending.deny("invalid_request")
            for field in ("temperature", "timeout"):
                value = wire.get(field)
                if field in wire and (type(value) not in (int, float) or not math.isfinite(value)
                                      or (field == "timeout" and value <= 0)):
                    spending.deny("invalid_request")
            if "response_format" in wire and wire["response_format"] != {"type": "json_object"}:
                spending.deny("unsupported_route")
            extra = wire.get("extra_body", {})
            if (not isinstance(extra, dict)
                    or set(extra) - {"thinking", "reasoning_effort", "enable_thinking"}
                    or ("thinking" in extra and extra["thinking"] not in
                        ({"type": "enabled"}, {"type": "disabled"}))
                    or ("enable_thinking" in extra and type(extra["enable_thinking"]) is not bool)
                    or ("reasoning_effort" in extra and extra["reasoning_effort"] not in
                        {"minimal", "low", "medium", "high", "max"})):
                spending.deny("unsupported_route")
            route_id = self._check_spending_sdk(client, wire.get("model"))
            route = spending.get_route(route_id)
            # Extra JSON wins in the SDK. Only checked reasoning keys may be
            # merged; transport timeout is not part of the physical JSON body.
            body = {k: v for k, v in wire.items() if k not in {"extra_body", "timeout"}}
            body.update(extra)
            request = {"endpoint": str(client.base_url), "model": wire["model"],
                       "input_tokens": route["input_ceiling"], "max_output_tokens": output,
                       "tool_units": 0, "payload_sha256": spending.hash_payload(body)}
        except Exception as exc:
            _raise_spending_stop(exc)
            spending.deny("invalid_request")

        def send():
            from openai import BadRequestError

            try:
                return client.chat.completions.create(**wire)
            except Exception as exc:
                _raise_spending_stop(exc)
                if (isinstance(exc, BadRequestError) and exc.status_code == 400
                        and getattr(getattr(exc, "response", None), "status_code", None) == 400
                        and Config.disables_thinking(wire.get("extra_body"))
                        and is_thinking_required_error(exc)):
                    return _ObservedThinkingRefusal("reasoning_parameter_refused")
                raise

        response = spending.dispatch(route_id, request, send,
                                     usage=lambda raw: self._spending_usage(raw, model=wire["model"]))
        if isinstance(response, _ObservedThinkingRefusal):
            raise response from None
        return response

    # ------------------------------------------------------------------
    # openai 提供方
    # ------------------------------------------------------------------
    def _chat_openai(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: Optional[Dict] = None,
        tier: str = "strong"
    ) -> str:
        # EXECPLAN2 I-6-2: 解析本次实际模型与客户端。fast tier 指向不同提供方时用第二客户端，
        # 否则同提供方仅切模型名；关闭路由时 model=self.model、client=self._openai_client。
        self._qualified_spending_route()
        model = self._model_for_tier(tier)
        client = self._openai_client
        if (not self._is_fallback
                and getattr(Config, "LLM_TIERED_ROUTING", False)
                and tier == "fast"):
            fast_client = self._fast_provider_client()
            if fast_client is not None:
                client = fast_client
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            kwargs["response_format"] = response_format

        # 推理模型(kimi/minimax/deepseek/qwen/glm)：默认关闭推理，避免 reasoning 吃光
        # max_tokens 导致 content 为空。reasoning_extra_body() 对非推理提供方返回 None。
        extra_body = self._apply_reasoning_options(kwargs, max_tokens)

        # Kimi K2.7 Code 网关按推理开关硬校验温度（开=1/关=0.6），覆盖调用方温度。
        kwargs["temperature"] = self._coerce_temperature(temperature, extra_body)

        timeout_override = _CALL_TIMEOUT_S.get()
        if timeout_override:
            kwargs["timeout"] = timeout_override
        response = self._create_completion(client, kwargs, temperature, max_tokens)
        # 捕获精确 token 用量供计量（I-5-0）；无 usage 字段时留空走粗估。
        try:
            _u = getattr(response, "usage", None)
            if _u is not None:
                if _spending().required():
                    pt, ct = getattr(_u, "prompt_tokens", None), getattr(_u, "completion_tokens", None)
                    self._last_usage = ({"prompt_tokens": pt, "completion_tokens": ct}
                                        if type(pt) is int and type(ct) is int else None)
                else:
                    self._last_usage = {
                        "prompt_tokens": int(getattr(_u, "prompt_tokens", 0) or 0),
                        "completion_tokens": int(getattr(_u, "completion_tokens", 0) or 0),
                    }
        except Exception as exc:
            _raise_spending_stop(exc)
            self._last_usage = None
        choice = response.choices[0]
        content = choice.message.content
        # 推理模型在 content 被推理耗尽时会返回空串/None（finish_reason=length）。
        # 明确报错而不是把空串交给下游 JSON 解析，便于定位与重试。
        if content is None or not content.strip():
            finish = getattr(choice, "finish_reason", None)
            if _spending().required():
                raise EmptyCompletionError("Provider returned empty content", provider=self.provider,
                                           finish_reason=finish if finish in {"stop", "length"} else None)
            # kimi/minimax keep their own switches; deepseek/qwen/glm share LLM_DISABLE_THINKING
            # (Config.reasoning_extra_body).  Some gateways still emit reasoning tokens with
            # thinking disabled (glm-5.3 on the coding plan, 2026-10-18) and those count against
            # max_tokens, so the budget can be the fix even when the switch is on.
            knob = {"kimi": "LLM_KIMI_DISABLE_THINKING",
                    "minimax": "LLM_MINIMAX_DISABLE_THINKING"}.get(self.provider, "LLM_DISABLE_THINKING")
            raise EmptyCompletionError(
                f"OpenAI 兼容提供方({self.provider})返回空 content（finish_reason={finish}）。"
                f"推理 token 计入 max_tokens：请确认已关闭推理({knob}=true)或增大 max_tokens"
                "（部分网关关闭推理后仍会输出推理内容）。",
                provider=self.provider, finish_reason=finish,
            )
        return self._clean_content(content)

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
        if _spending().required():
            _spending().deny("unsupported_route")
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
        _m = (self.model or "").strip()
        if _m and (_m.startswith("claude") or _m in ("opus", "sonnet", "haiku")):
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

            content = self._clean_content(content)
            if not content:
                raise RuntimeError("Claude CLI returned empty result")
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
        if _spending().required():
            _spending().deny("unsupported_route")
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
