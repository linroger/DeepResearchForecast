"""Bridge config-reflected tool: 跨 run 一手来源缓存（ITEM 10，透明包裹 jina web_fetch）。

深研究里同一 URL 常被跨 pass / 跨 run 反复抓取（续跑、双轨、fan-out、覆盖 top-up），Jina
reader 的重量级全文转写（监管文件 / 年报 / 长 PDF）单次可达数十秒。本模块把 harness 自带的
jina `web_fetch` 工具包成一层**磁盘缓存**：命中且未过期即秒回、且**返回类型与被包裹工具完全
一致**（str），对 agent 透明。

约束（对齐 market_tools.py / search_tools.py 的部署/自包含语义）：

* **config.yaml 里以裸模块名注册**：`use: cached_fetch:web_fetch_tool`（group: web，
  timeout: 30）。由于本包裹器以 `web_fetch` 之名注册，被委派的 jina 工具读到的正是**本**
  stanza 的 timeout（30s），与直接配置 jina 完全同参。
* **委派而非重实现**：真正抓取仍走 ``deerflow.community.jina_ai.tools:web_fetch_tool``
  （异步）；本模块只在其外侧加缓存读写。deerflow.* 延迟导入 → 无 deerflow / 无 langchain
  的离线环境也能 import；``web_fetch_tool`` 变量在无 langchain 时为 None。
* **缓存语义**：
    - 目录  env RESEARCH_SOURCE_CACHE_DIR（默认 <module_dir>/.cache/source_cache）
    - 键    sha256(url) 的 hexdigest（→ ``<hash>.json``）
    - 值    {url, content, fetched_at(epoch), content_len}
    - TTL   env RESEARCH_SOURCE_CACHE_TTL_H（默认 72h；0=关闭缓存，透明直连）
    - 上限  env RESEARCH_SOURCE_CACHE_MAX_MB（默认 500；<=0=不限；超限按 mtime LRU 淘汰）
* **绝不放入正缓存的失败/哨兵/死抓取**：jina 失败返回以 "Error:" 起头的串；正文 <200 字符
  视作死抓取。LOOP-007 账本启用时，此类 exact 结果允许一次真抓重试，随后在负缓存 TTL 内
  稳定抑制；账本未启用时仍维持原来的每次真抓行为。
* **抽取空壳（RESEARCH-1，RESEARCH_FETCH_SHELL_DETECTION 缺省开）**：reader 空壳、"page
  unavailable" 页、bot wall、短付费墙预告由 ``extraction_failure_reason`` 判定——不落盘、
  触发 provider 回退、缓存命中时视作未命中；全链只剩空壳时返回 "Error: fetch returned <reason>"。
* **LOOP-007 —— 跨进程预算**：正缓存命中只计 attempt、不计 network；miss 后才原子占用
  fetch global/lane 额度。预算拒绝不调用 jina delegate；账本故障 fail-open 并输出 degraded 遥测。
* **degrade-safe**：任何缓存读写/目录/淘汰异常都被吞掉并回退到「直接抓取并返回」，缓存层的
  故障绝不阻断研究主流程，也绝不改变抓取结果本身。
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import io
import ipaddress
import json
import logging
import os
import socket
import threading
import time
from html.parser import HTMLParser
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

try:  # copied beside this module by the bridge sync guard; absence is fail-open
    import research_budget as _research_budget
except ImportError:  # pragma: no cover - exercised only by incomplete deployments
    _research_budget = None  # type: ignore[assignment]

# 死抓取阈值：正文短于此长度（或以 "Error:" 起头）视作失败/空壳，不落盘。
DEAD_FETCH_MIN_CHARS = 200
# env 缺省
DEFAULT_TTL_HOURS = 72.0
DEFAULT_MAX_MB = 500.0
# —— Firecrawl 花费护栏（Session B：单 run 烧掉 ~$100 credit 的事后防线）——
# Firecrawl /scrape 按调用计费。两道闸：maxAge 让窗口内未变的页面由 Firecrawl 端缓存直接
# 返回（不触发全新计费抓取）；进程内调用硬上限兜住失控循环（每个研究子进程即一条 lane，
# 进程内计数就是 per-lane 计数，无需跨进程账本）。
DEFAULT_FIRECRAWL_MAX_AGE_SECONDS = 172_800.0  # 2 天；0=每次真抓（载荷不带 maxAge 字段）
DEFAULT_FIRECRAWL_FETCH_CALL_CEILING = 400     # 单进程 /scrape 计费调用上限；<=0=不限
_firecrawl_fetch_calls = 0         # 本进程已发出的真实 /scrape 计费调用数
_firecrawl_ceiling_warned = False  # 越线只 warn 一次，不逐调用刷屏
DEFAULT_LOW_QUALITY_DOMAINS = (
    "economicsummarizer.com",
    "insights.triplegains.com",
)
_TRANSPORT_FAILURE_MARKERS = (
    "connecttimeout",
    "readtimeout",
    "pooltimeout",
    "connecterror",
    "connection refused",
    "connection reset",
    "network is unreachable",
    "timed out",
    "timeout",
)
_CONTENT_FAILURE_MARKERS = (
    "access denied",
    "403 forbidden",
    "404 not found",
    "page not found",
    "verify you are human",
    "enable javascript and cookies",
    "captcha",
)
# —— RESEARCH-1：抽取空壳分类器（extraction_failure_reason）——
# Reader shells ("Markdown Content: undefined"), "page unavailable" pages, bot
# walls and short paywall teasers used to count as successful reads: cached for
# 72 h, marked fetched and published as fetched.  Every marker below is ASCII
# lowercase or CJK and is matched only inside a length window, so a long real
# article that merely mentions "captcha" or carries a subscribe footer passes.
_SHELL_PREFIX_CHARS = 3000
_SHELL_MIN_CONTENT_CHARS = 200
_SHELL_READER_ENVELOPE = "markdown content:"
_SHELL_METADATA_PREFIXES = (
    "title:",
    "url source:",
    "published time:",
    "warning:",
    "markdown content:",
)
_UNAVAILABLE_PAGE_MAX_CHARS = 1500
_UNAVAILABLE_PAGE_MARKERS = (
    "page unavailable",
    "this page is unavailable",
    "no longer available",
    "could not be found",
    "has been removed",
    "page not found",
    "404 not found",
)
_BOT_WALL_MAX_CHARS = 1500
_BOT_WALL_MARKERS = (
    "just a moment",
    "checking your browser",
    "attention required",
    "unusual traffic",
    "are you a robot",
    "request blocked",
    "verify you are human",
    "enable javascript and cookies",
    "captcha",
    "access denied",
    "403 forbidden",
)
_PAYWALL_MAX_CHARS = 3000
_PAYWALL_MARKERS = (
    "subscribe to continue",
    "to continue reading",
    "already a subscriber",
    "subscribers only",
    "sign in to continue reading",
    "register to continue reading",
    "登录后查看",
    "订阅后阅读",
    "付费阅读",
)
_SHELL_FALSY = frozenset({"0", "false", "no", "off"})
# ASCII-only lowercasing keeps every offset aligned with the original text (the
# reader-envelope body is sliced from the original); all markers are ASCII or CJK.
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
# Direct-fallback PDF parsing: pdfplumber/pypdfium2 are not thread-safe, and a
# pathological PDF must not hold the fetch past this bound.
PDF_PARSE_TIMEOUT_S = 20.0
_PDF_LOCK = threading.Lock()
_FETCH_PROVIDER: contextvars.ContextVar[str] = contextvars.ContextVar(
    "research_fetch_provider", default=""
)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float, minimum: float = 0.1) -> float:
    try:
        value = float(os.environ.get(name, str(default)) or str(default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, value)


def _is_transport_failure(value: Any) -> bool:
    lowered = str(value or "").lower()
    return any(marker in lowered for marker in _TRANSPORT_FAILURE_MARKERS)


def _shell_detection_on() -> bool:
    """RESEARCH_FETCH_SHELL_DETECTION（缺省开）。诚实性检查 fail-closed：只有显式假值
    （0/false/no/off）才恢复旧行为（逐字节一致）。"""
    raw = os.environ.get("RESEARCH_FETCH_SHELL_DETECTION", "").strip().lower()
    return raw not in _SHELL_FALSY


def extraction_failure_reason(text: Any) -> Optional[str]:
    """Why a fetched text is an extraction shell rather than a page, else None.

    Pure and stdlib-only: substring checks over an ASCII-lowercased prefix of at
    most 3,000 chars (no regex).  Non-str, empty and "Error:" texts return None
    (they are failures of their own kind).  Rules, first match wins:

    * ``empty_extraction`` — a reader envelope ("Markdown Content:") whose body
      is empty/undefined/null/none or under 200 chars; or fewer than 200 chars
      left after dropping the first line when it is a "#" title and every
      Title:/URL Source:/Published Time:/Warning:/Markdown Content: line;
    * ``unavailable_page`` — under 1,500 chars with a "page unavailable" marker;
    * ``bot_wall`` — under 1,500 chars with a bot-check/interstitial marker;
    * ``paywalled`` — under 3,000 chars with a paywall-teaser marker.
    """
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped or stripped.startswith("Error:"):
        return None
    prefix = stripped[:_SHELL_PREFIX_CHARS].translate(_ASCII_LOWER)
    envelope_at = prefix.find(_SHELL_READER_ENVELOPE)
    if envelope_at >= 0:
        # The length rule covers the empty/"undefined"/"null"/"none" bodies too.
        body = stripped[envelope_at + len(_SHELL_READER_ENVELOPE):].strip()
        if len(body) < _SHELL_MIN_CONTENT_CHARS:
            return "empty_extraction"
    lines = prefix.split("\n")
    if lines[0].startswith("#"):
        lines = lines[1:]
    content = "\n".join(
        line for line in lines
        if not line.strip().startswith(_SHELL_METADATA_PREFIXES)
    ).strip()
    # Text beyond the scanned prefix counts as content (never a false shell).
    unscanned = max(0, len(stripped) - _SHELL_PREFIX_CHARS)
    if len(content) + unscanned < _SHELL_MIN_CONTENT_CHARS:
        return "empty_extraction"
    length = len(stripped)
    if length < _UNAVAILABLE_PAGE_MAX_CHARS and any(
            marker in prefix for marker in _UNAVAILABLE_PAGE_MARKERS):
        return "unavailable_page"
    if length < _BOT_WALL_MAX_CHARS and any(
            marker in prefix for marker in _BOT_WALL_MARKERS):
        return "bot_wall"
    if length < _PAYWALL_MAX_CHARS and any(
            marker in prefix for marker in _PAYWALL_MARKERS):
        return "paywalled"
    return None


def _shell_error(text: Any) -> Optional[str]:
    """``"Error: fetch returned <reason>"`` when the failover chain's last text is
    a shell; None for real text, "Error:" strings and JSON object envelopes (an
    envelope's own error, e.g. research_budget_exhausted, must reach the tool
    layer unchanged)."""
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            if isinstance(json.loads(stripped), dict):
                return None
        except (TypeError, ValueError):
            pass
    reason = extraction_failure_reason(stripped)
    return f"Error: fetch returned {reason}" if reason else None


def _pdf_text_pypdf(content: bytes, max_pages: int) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    return "\n\n".join(str(page.extract_text() or "") for page in reader.pages[:max_pages])


def _pdf_text_pdfplumber(content: bytes, max_pages: int) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return "\n\n".join(str(page.extract_text() or "") for page in pdf.pages[:max_pages])


def _extract_pdf_text(content: bytes, max_pages: int = 80) -> str:
    """Text of the first ``max_pages`` pages: pypdf, else pdfplumber (the deer-flow
    research venv ships only pdfplumber).  Serialized by ``_PDF_LOCK``; when
    pdfplumber is missing too, pypdf's own failure is raised (a parse error says
    more than a missing library)."""
    with _PDF_LOCK:
        try:
            return _pdf_text_pypdf(content, max_pages)
        except Exception as exc:  # noqa: BLE001 — fall back to pdfplumber
            pypdf_failure = exc
        try:
            return _pdf_text_pdfplumber(content, max_pages)
        except ImportError:
            if isinstance(pypdf_failure, ImportError):
                raise
            raise pypdf_failure from None


class _TextExtractor(HTMLParser):
    """Small dependency-free fallback when DeerFlow readability cannot parse."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._suppressed += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._suppressed = max(0, self._suppressed - 1)

    def handle_data(self, data: str) -> None:
        if not self._suppressed and data.strip():
            self.parts.append(data.strip())


async def _host_is_public(host: str) -> bool:
    """Reject local/private direct-fallback targets before opening a socket."""
    normalized = str(host or "").strip().rstrip(".")
    if not normalized or normalized.lower() == "localhost":
        return False
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo, normalized, None, type=socket.SOCK_STREAM
        )
    except OSError:
        return False
    ips = {row[4][0] for row in addresses if row and row[4]}
    if not ips:
        return False
    try:
        return all(ipaddress.ip_address(ip).is_global for ip in ips)
    except ValueError:
        return False


async def _direct_http_fetch(url: str) -> str:
    """Keyless bounded fallback for a public page when Jina is unavailable."""
    try:
        import httpx

        timeout = _env_float("RESEARCH_DIRECT_FETCH_TIMEOUT_SECONDS", 12.0)
        max_bytes = int(float(os.environ.get(
            "RESEARCH_DIRECT_FETCH_MAX_MB", "8") or "8") * 1024 * 1024)
        current = str(url or "").strip()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; DeepAgentForecastResearch/1.0; "
                "+https://github.com/linroger/DeepAgentForecast)"
            )
        }
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            headers=headers,
            trust_env=True,
        ) as client:
            response = None
            for _ in range(6):
                parsed = urlparse(current)
                if parsed.scheme not in {"http", "https"} or not await _host_is_public(
                    parsed.hostname or ""
                ):
                    return "Error: direct fallback rejected a non-public URL"
                response = await client.get(current)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        return "Error: direct fallback redirect had no location"
                    current = urljoin(current, location)
                    continue
                break
            if response is None:
                return "Error: direct fallback produced no response"
            if response.status_code >= 400:
                return f"Error: direct fallback HTTP {response.status_code}"
            if len(response.content) > max(200_000, max_bytes):
                return "Error: direct fallback response exceeded size limit"
            content_type = response.headers.get("content-type", "").lower()
            if "pdf" in content_type or response.content.startswith(b"%PDF"):
                try:
                    text = await asyncio.wait_for(
                        asyncio.to_thread(_extract_pdf_text, response.content),
                        PDF_PARSE_TIMEOUT_S,
                    )
                except TimeoutError:
                    return "Error: direct fallback PDF parse timed out"
                except Exception as exc:  # noqa: BLE001
                    return f"Error: direct fallback PDF extraction failed: {type(exc).__name__}"
                return text[:12000] if len(text.strip()) >= 200 else (
                    "Error: direct fallback PDF had no extractable text"
                )
            raw = response.text
            if "html" not in content_type and "<html" not in raw[:1000].lower():
                return raw[:12000]
            try:
                from deerflow.utils.readability import ReadabilityExtractor

                article = await asyncio.to_thread(
                    ReadabilityExtractor().extract_article, raw
                )
                markdown = article.to_markdown()
                if len(str(markdown or "").strip()) >= 200:
                    return str(markdown)[:12000]
            except Exception:  # noqa: BLE001
                pass
            parser = _TextExtractor()
            parser.feed(raw)
            plain = "\n".join(parser.parts)
            return plain[:12000] if len(plain.strip()) >= 200 else (
                "Error: direct fallback extracted no usable content"
            )
    except Exception as exc:  # noqa: BLE001
        return f"Error: direct fallback failed: {type(exc).__name__}: {exc}"


async def _exa_fetch(url: str) -> str:
    """Fetch one public URL through Exa when its configured credential exists."""
    api_key = os.environ.get("EXA_API_KEY", "").strip()
    if not api_key:
        return "Error: Exa fallback unavailable (EXA_API_KEY is not configured)"
    try:
        from exa_py import Exa

        max_chars = max(
            4096,
            int(os.environ.get("RESEARCH_EXA_FETCH_MAX_CHARS", "12000") or "12000"),
        )

        def _request() -> Any:
            client = Exa(api_key=api_key)
            return client.get_contents(
                [url], text={"max_characters": max_chars}
            )

        result = await asyncio.wait_for(
            asyncio.to_thread(_request),
            timeout=_env_float("RESEARCH_EXA_FETCH_TIMEOUT_SECONDS", 15.0),
        )
        rows = list(getattr(result, "results", None) or [])
        if not rows:
            return "Error: Exa fallback returned no results"
        row = rows[0]
        title = str(getattr(row, "title", None) or "Untitled")
        body = str(getattr(row, "text", None) or "").strip()
        if not body:
            return "Error: Exa fallback returned no page text"
        return f"# {title}\n\n{body[:max_chars]}"
    except Exception as exc:  # noqa: BLE001
        # Do not include provider exception text: some clients echo request
        # headers or credentials in their exception representation.
        return f"Error: Exa fallback failed: {type(exc).__name__}"


def _firecrawl_max_age_ms() -> int:
    """RESEARCH_FIRECRAWL_MAX_AGE_SECONDS（秒，缺省 172800=2 天）→ Firecrawl 期望的毫秒。

    >0 → /scrape 载荷带 maxAge：页面在窗口内未变即由 Firecrawl 端缓存回放，不再产生一次
    全新计费抓取；0 → 不带该字段（每次真抓，与加此旋钮前逐字节一致）。非法值回退默认。
    """
    raw = os.environ.get("RESEARCH_FIRECRAWL_MAX_AGE_SECONDS", "").strip()
    try:
        seconds = float(raw) if raw else DEFAULT_FIRECRAWL_MAX_AGE_SECONDS
    except (TypeError, ValueError):
        seconds = DEFAULT_FIRECRAWL_MAX_AGE_SECONDS
    return int(max(0.0, seconds) * 1000.0)


def _firecrawl_fetch_call_ceiling() -> int:
    """单进程 /scrape 计费调用硬上限。RESEARCH_FIRECRAWL_MAX_FETCH_CALLS_PER_PROCESS
    缺省 400；<=0=不限。非法值回退默认。"""
    raw = os.environ.get(
        "RESEARCH_FIRECRAWL_MAX_FETCH_CALLS_PER_PROCESS", "").strip()
    try:
        value = int(float(raw)) if raw else DEFAULT_FIRECRAWL_FETCH_CALL_CEILING
    except (TypeError, ValueError):
        value = DEFAULT_FIRECRAWL_FETCH_CALL_CEILING
    return value


def _firecrawl_over_ceiling() -> Optional[str]:
    """越线 → 返回 "Error:" 哨兵串（与 transport 失败同形：不落缓存、_resilient_fetch
    顺链落 Jina/Exa）；未越线 → None。越线时刻只 warn 一次。"""
    global _firecrawl_ceiling_warned
    ceiling = _firecrawl_fetch_call_ceiling()
    if ceiling <= 0 or _firecrawl_fetch_calls < ceiling:
        return None
    if not _firecrawl_ceiling_warned:
        _firecrawl_ceiling_warned = True
        logger.warning(
            "cached_fetch: Firecrawl 本进程 scrape 计费调用已达上限 %d，"
            "后续抓取直接走 Jina/Exa 回退链（不再产生 Firecrawl 费用）", ceiling)
    return f"Error: Firecrawl per-run call ceiling reached ({ceiling})"


def get_firecrawl_call_counts() -> dict[str, int]:
    """进程内 Firecrawl 计费调用计数快照（供未来预算遥测导出；本模块只有 fetch 面）。"""
    return {"fetch": _firecrawl_fetch_calls}


async def _firecrawl_fetch(url: str) -> str:
    """Fetch one URL through Firecrawl v2 /scrape when its credential exists.

    托管抓取（渲染 JS、绕过常见反爬、直接产出 markdown），修复取证发现的 Jina 53%
    ConnectTimeout 失败率。直连 HTTP（httpx），不引入 firecrawl-py 依赖——deer-flow venv
    版本钉死，多一个 SDK 就多一个部署漂移面。错误串一律 "Error:" 开头（供
    _is_cacheable/_is_transport_failure 分类），且绝不回显异常正文（可能含请求头/凭据）。
    """
    global _firecrawl_fetch_calls
    api_key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if not api_key:
        return "Error: Firecrawl unavailable (FIRECRAWL_API_KEY is not configured)"
    ceiling_sentinel = _firecrawl_over_ceiling()
    if ceiling_sentinel is not None:
        return ceiling_sentinel
    try:
        import httpx

        max_chars = max(
            4096,
            int(os.environ.get(
                "RESEARCH_FIRECRAWL_FETCH_MAX_CHARS", "12000") or "12000"),
        )
        timeout = _env_float("RESEARCH_FIRECRAWL_FETCH_TIMEOUT_SECONDS", 25.0)
        payload_body: dict[str, Any] = {
            "url": str(url or "").strip(),
            "formats": ["markdown"],
            "onlyMainContent": True,
        }
        max_age_ms = _firecrawl_max_age_ms()
        if max_age_ms > 0:
            # Firecrawl 端缓存回放窗口（毫秒）：未变页面不再触发全新计费抓取。
            payload_body["maxAge"] = max_age_ms
        _firecrawl_fetch_calls += 1  # 计在发出请求前：HTTP 4xx/5xx 同样可能计费
        async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
            response = await client.post(
                os.environ.get(
                    "FIRECRAWL_API_URL", "https://api.firecrawl.dev/v2/scrape"
                ).strip() or "https://api.firecrawl.dev/v2/scrape",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload_body,
            )
        if response.status_code == 402:
            return "Error: Firecrawl failed: payment required / quota exhausted"
        if response.status_code == 429:
            return "Error: Firecrawl failed: rate limited (429 timeout)"
        if response.status_code >= 400:
            return f"Error: Firecrawl failed: HTTP {response.status_code}"
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return "Error: Firecrawl returned no scrape data"
        body = str(data.get("markdown") or "").strip()
        if not body:
            return "Error: Firecrawl returned no page text"
        metadata = data.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        title = str(metadata.get("title") or "").strip()
        return (f"# {title}\n\n{body[:max_chars]}" if title else body[:max_chars])
    except Exception as exc:  # noqa: BLE001
        # Do not include provider exception text (may echo the bearer header).
        return f"Error: Firecrawl failed: {type(exc).__name__}"


def _provider_circuit_open(provider: str) -> bool:
    return bool(
        _research_budget is not None
        and hasattr(_research_budget, "provider_circuit_open")
        and _research_budget.provider_circuit_open(provider)
    )


def _record_provider_failure(provider: str, result: str) -> None:
    if (
        _research_budget is not None
        and hasattr(_research_budget, "record_provider_transport_failure")
        and _is_transport_failure(result)
    ):
        _research_budget.record_provider_transport_failure(provider, result)


def _record_provider_success(provider: str) -> None:
    if _research_budget is not None and hasattr(
        _research_budget, "record_provider_success"
    ):
        _research_budget.record_provider_success(provider)


def _reserve_additional_physical_fetch(url: str) -> Optional[str]:
    """Count a fallback request after the outer reservation counted request one."""
    if _research_budget is None:
        return None
    admission = _research_budget.admit_network("fetch")
    if admission.allowed:
        return None
    return _research_budget.denial_result(
        "web_fetch", admission.reason, str(url or "").strip()
    )


async def _resilient_fetch(url: str) -> str:
    """Try Firecrawl (when keyed), then Jina, then Exa, then opt-in direct.

    ``cached_fetch`` reserves request one. Every additional physical provider
    request reserves another network unit here, so failover cannot silently
    double or triple the configured fetch allowance. Firecrawl leads when its
    key is configured: it is the managed, render-capable extractor; anonymous
    Jina (53% ConnectTimeout in the 2026-07-14 humanoid run) becomes fallback.
    """
    _FETCH_PROVIDER.set("")
    physical_attempts = 0
    firecrawl_result = ""
    if (os.environ.get("FIRECRAWL_API_KEY", "").strip()
            and not _provider_circuit_open("firecrawl")):
        ceiling_sentinel = _firecrawl_over_ceiling()
        if ceiling_sentinel is not None:
            # 花费护栏越线：不发请求、不计物理尝试（Jina 无需追加预算占用）、
            # 不喂 provider 熔断（本地上限≠传输故障，不应波及其他 lane）。
            firecrawl_result = ceiling_sentinel
        else:
            physical_attempts += 1
            firecrawl_result = await _firecrawl_fetch(url)
            if _is_cacheable(firecrawl_result):
                _FETCH_PROVIDER.set("firecrawl")
                _record_provider_success("firecrawl")
                return firecrawl_result
            _record_provider_failure("firecrawl", firecrawl_result)

    primary_result = ""
    if not _provider_circuit_open("jina"):
        if physical_attempts:
            denial = _reserve_additional_physical_fetch(url)
            if denial is not None:
                return denial
        physical_attempts += 1
        try:
            primary_result = await asyncio.wait_for(
                _jina_delegate_fetch(url),
                timeout=_env_float("RESEARCH_JINA_PRIMARY_TIMEOUT_SECONDS", 10.0),
            )
        except Exception as exc:  # noqa: BLE001
            primary_result = f"Error: Jina primary failed: {type(exc).__name__}: {exc}"
        if _is_cacheable(primary_result):
            _FETCH_PROVIDER.set("jina")
            _record_provider_success("jina")
            return primary_result
        _record_provider_failure("jina", primary_result)

    exa_result = ""
    if os.environ.get("EXA_API_KEY", "").strip() and not _provider_circuit_open("exa"):
        if physical_attempts:
            denial = _reserve_additional_physical_fetch(url)
            if denial is not None:
                return denial
        physical_attempts += 1
        exa_result = await _exa_fetch(url)
        if _is_cacheable(exa_result):
            _FETCH_PROVIDER.set("exa")
            _record_provider_success("exa")
            return exa_result
        _record_provider_failure("exa", exa_result)

    # Raw crawling has more variable robots/readability behavior than either
    # content provider, so it remains an explicit operator opt-in.
    direct_result = ""
    if _env_flag("RESEARCH_DIRECT_FETCH_FALLBACK", False):
        if physical_attempts:
            denial = _reserve_additional_physical_fetch(url)
            if denial is not None:
                return denial
        direct_result = await _direct_http_fetch(url)
        if _is_cacheable(direct_result):
            _FETCH_PROVIDER.set("direct")
            return direct_result

    final = direct_result or exa_result or primary_result or firecrawl_result or (
        "Error: no web-fetch provider was available"
    )
    if _shell_detection_on():
        # Every provider failed; a shell left as the last text is a failure too,
        # so legacy agents and the v3 tool layer never read it as a page.
        return _shell_error(final) or final
    return final


def _source_policy_rejection(url: str) -> Optional[str]:
    """Reject configured AI/SEO aggregators before they consume fetch/context."""
    if os.environ.get(
            "RESEARCH_ALLOW_LOW_QUALITY_SOURCES", "false").strip().lower() in {
                "1", "true", "yes", "on"}:
        return None
    try:
        from urllib.parse import urlparse

        host = (urlparse(str(url or "")).hostname or "").lower().rstrip(".")
    except Exception:
        return None
    raw = os.environ.get(
        "RESEARCH_SOURCE_DENY_DOMAINS",
        ",".join(DEFAULT_LOW_QUALITY_DOMAINS),
    )
    denied = {
        domain.strip().lower().lstrip(".")
        for domain in raw.split(",") if domain.strip()
    }
    for domain in denied:
        if host == domain or host.endswith("." + domain):
            return f"configured low-quality/AI-SEO source domain: {domain}"
    return None


def _source_policy_result(url: str, reason: str) -> str:
    return json.dumps(
        {
            "error": "source_quality_rejected",
            "url": url,
            "reason": reason,
            "message": (
                "Use the original filing, regulator, company, dataset, or a "
                "high-authority independent source instead."
            ),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _cache_root() -> str:
    """缓存目录：RESEARCH_SOURCE_CACHE_DIR 覆盖，缺省 <module_dir>/.cache/source_cache。

    以本模块文件所在目录为基（部署目录跨 run 稳定）故缓存天然跨 run 持久。绝不在此创建目录
    （留给写入时按需 makedirs），读侧不产生副作用。
    """
    raw = os.environ.get("RESEARCH_SOURCE_CACHE_DIR", "").strip()
    if raw:
        return os.path.expanduser(raw)
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, ".cache", "source_cache")


def _ttl_seconds() -> float:
    """TTL（秒）。RESEARCH_SOURCE_CACHE_TTL_H 缺省 72h；<=0 → 0（关闭缓存）。非法值回退默认。"""
    raw = os.environ.get("RESEARCH_SOURCE_CACHE_TTL_H", "").strip()
    try:
        hours = float(raw) if raw else DEFAULT_TTL_HOURS
    except (TypeError, ValueError):
        hours = DEFAULT_TTL_HOURS
    return max(0.0, hours) * 3600.0


def _max_bytes() -> int:
    """缓存目录字节上限。RESEARCH_SOURCE_CACHE_MAX_MB 缺省 500；<=0 → 0（不限）。非法值回退默认。"""
    raw = os.environ.get("RESEARCH_SOURCE_CACHE_MAX_MB", "").strip()
    try:
        mb = float(raw) if raw else DEFAULT_MAX_MB
    except (TypeError, ValueError):
        mb = DEFAULT_MAX_MB
    return int(max(0.0, mb) * 1024 * 1024)


def _cache_key(url: str) -> str:
    """URL → sha256 hexdigest（稳定、文件名安全的缓存键）。"""
    return hashlib.sha256(str(url or "").encode("utf-8")).hexdigest()


def _cache_path(root: str, url: str) -> str:
    return os.path.join(root, _cache_key(url) + ".json")


def _is_cacheable(content: Any) -> bool:
    """仅当是**成功的、非空壳**正文才可落盘：str、非空、非 "Error:" 起头、且 ≥200 字符。

    RESEARCH_FETCH_SHELL_DETECTION 开（缺省）时空壳由 extraction_failure_reason 判定（带长度
    窗口的标记，替代旧的无窗口前缀标记）；关时保持旧的 _CONTENT_FAILURE_MARKERS 前缀判定。
    """
    if not isinstance(content, str):
        return False
    stripped = content.strip()
    if not stripped or stripped.startswith("Error:"):
        return False
    if _shell_detection_on():
        if extraction_failure_reason(stripped) is not None:
            return False
    else:
        prefix = stripped[:1200].lower()
        if any(marker in prefix for marker in _CONTENT_FAILURE_MARKERS):
            return False
    if stripped.startswith("{"):
        try:
            envelope = json.loads(stripped)
            if isinstance(envelope, dict) and (
                envelope.get("error") or envelope.get("status") in {"error", "failed"}
            ):
                return False
        except (TypeError, ValueError):
            pass
    return len(content) >= DEAD_FETCH_MIN_CHARS


def _read_cache(path: str, ttl_seconds: float) -> Optional[str]:
    """命中且未过期 → 返回 content（并 touch mtime 供 LRU 记「近用」）；否则 None。任何异常 → None。

    过期判定基于落盘时记录的 ``fetched_at``（真实抓取时刻），**不**用 mtime——因为命中会 touch
    mtime 用作 LRU 近用标记，二者若混用会让被反复命中的条目永不过期。二者故意分离。
    """
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        fetched_at = float(obj.get("fetched_at") or 0.0)
        content = obj.get("content")
        if not isinstance(content, str):
            return None
        if (time.time() - fetched_at) > ttl_seconds:
            return None  # 过期 → 视作未命中（调用方将重抓覆盖）
        if _shell_detection_on() and extraction_failure_reason(content) is not None:
            # 修复前落盘的空壳：视作未命中并 best-effort 删除，让本次重抓走完整回退链。
            try:
                os.remove(path)
            except OSError:
                pass
            return None
        try:
            os.utime(path, None)  # LRU：命中即刷新 mtime 为「最近使用」（best-effort）
        except OSError:
            pass
        return content
    except Exception:  # noqa: BLE001 — 缓存读损坏/并发写中 → 当作未命中，degrade-safe
        return None


def _write_cache(path: str, url: str, content: str) -> None:
    """原子写缓存条目（temp+replace）。best-effort：任何失败静默跳过（不影响返回给 agent 的结果）。"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {
            "url": url,
            "content": content,
            "fetched_at": time.time(),
            "content_len": len(content),
        }
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception as e:  # noqa: BLE001
        logger.warning("cached_fetch: 写缓存失败（跳过，不影响抓取结果）: %s", e)


def _enforce_size_cap(root: str, max_bytes: int) -> None:
    """目录总字节超上限时，按 mtime 升序（最久未用）淘汰缓存文件直到回落上限内。best-effort。

    只淘汰 ``*.json`` 缓存文件；mtime 兼作 LRU 近用标记（命中会 touch）。任何异常静默跳过。
    """
    if max_bytes <= 0:
        return
    try:
        entries = []
        total = 0
        with os.scandir(root) as it:
            for e in it:
                if not e.name.endswith(".json") or not e.is_file():
                    continue
                try:
                    st = e.stat()
                except OSError:
                    continue
                entries.append((st.st_mtime, st.st_size, e.path))
                total += st.st_size
        if total <= max_bytes:
            return
        entries.sort(key=lambda t: t[0])  # 最久未用在前
        for _mtime, size, p in entries:
            if total <= max_bytes:
                break
            try:
                os.remove(p)
                total -= size
            except OSError:
                continue
    except Exception as e:  # noqa: BLE001
        logger.warning("cached_fetch: 淘汰缓存失败（跳过）: %s", e)


async def cached_fetch(
    url: str,
    fetch_fn: Callable[[str], Awaitable[str]],
    revisit_reason: str = "",
) -> str:
    """缓存核心流程（可注入 ``fetch_fn`` 供单测，无网络无 deerflow）。返回类型与被包裹工具一致（str）。

    TTL<=0 → 关闭正缓存（LOOP-007 预算仍独立生效）。否则：命中未过期即返回；否则真抓，成功且可缓存
    （非失败/非哨兵/≥200 字符）才落盘 + 触发 LRU 淘汰。缓存层任何异常都不改变返回结果。
    """
    exact_key = str(url or "").strip()
    policy_rejection = _source_policy_rejection(exact_key)
    if policy_rejection:
        return _source_policy_result(exact_key, policy_rejection)
    if _research_budget is not None:
        attempt = _research_budget.admit_attempt("fetch")
        if not attempt.allowed:
            return _research_budget.denial_result("web_fetch", attempt.reason, exact_key)

    ttl = _ttl_seconds()
    root = _cache_root()
    path = _cache_path(root, url)
    if ttl > 0:
        try:
            hit = _read_cache(path, ttl)
        except Exception:  # noqa: BLE001 — 极端情况下路径计算/读取异常也不阻断抓取
            hit = None
        if hit is not None:
            if _research_budget is not None:
                if hasattr(_research_budget, "record_fetched_source"):
                    _research_budget.record_fetched_source(
                        exact_key, hit, provider="cache", cache_hit=True
                    )
                if not str(revisit_reason or "").strip():
                    artifact_id = _research_budget.positive_repeat(
                        "fetch", exact_key)
                    if artifact_id:
                        return _research_budget.compact_positive_result(
                            "web_fetch", artifact_id)
                _research_budget.record_positive("fetch", exact_key)
            return hit

    if (_research_budget is not None
            and _research_budget.negative_suppressed("fetch", exact_key)):
        return _research_budget.negative_result("web_fetch", exact_key)

    claim_token = ""
    waited_for_claim = False
    if _research_budget is not None and ttl > 0:
        claim_token = _research_budget.claim_request("fetch", exact_key)
        if not claim_token:
            waited_for_claim = True
            try:
                wait_seconds = max(1, int(os.environ.get(
                    "RESEARCH_INFLIGHT_WAIT_SECONDS", "45") or "45"))
            except ValueError:
                wait_seconds = 45
            deadline = time.monotonic() + wait_seconds
            delay = 0.1
            while time.monotonic() < deadline:
                await asyncio.sleep(delay)
                delay = min(1.0, delay * 1.7)
                hit = _read_cache(path, ttl)
                if hit is not None:
                    # A singleflight follower may be an isolated subagent that
                    # cannot see the owner's model history. Share the fresh
                    # cache body in full; network dedupe must not become
                    # cross-context evidence loss.
                    _research_budget.record_positive("fetch", exact_key)
                    if hasattr(_research_budget, "record_fetched_source"):
                        _research_budget.record_fetched_source(
                            exact_key, hit, provider="cache", cache_hit=True
                        )
                    return hit
                claim_token = _research_budget.claim_request("fetch", exact_key)
                if claim_token:
                    break
            if not claim_token:
                return json.dumps({
                    "error": "research_inflight_timeout",
                    "tool": "web_fetch",
                    "message": "Timed out waiting for the identical in-flight fetch.",
                }, ensure_ascii=False, sort_keys=True)
    if (waited_for_claim and _research_budget is not None
            and _research_budget.negative_suppressed("fetch", exact_key)):
        _research_budget.release_request(claim_token)
        return _research_budget.negative_result("web_fetch", exact_key)

    # This reservation is deliberately after the positive-cache/singleflight
    # lookup: hits never spend real fetch allowance.
    if _research_budget is not None:
        network = _research_budget.admit_network("fetch")
        if not network.allowed:
            _research_budget.release_request(claim_token)
            return _research_budget.denial_result("web_fetch", network.reason, exact_key)

    try:
        content = await fetch_fn(url)
    except Exception:
        if _research_budget is not None:
            _research_budget.export_telemetry(force=True)
        raise
    finally:
        if "content" not in locals() and _research_budget is not None:
            _research_budget.release_request(claim_token)
    try:
        if _research_budget is not None:
            if _is_cacheable(content):
                _research_budget.clear_negative("fetch", exact_key)
                _research_budget.record_positive("fetch", exact_key)
                if hasattr(_research_budget, "record_fetched_source"):
                    _research_budget.record_fetched_source(
                        exact_key,
                        content,
                        provider=_FETCH_PROVIDER.get(),
                        cache_hit=False,
                    )
            else:
                _research_budget.record_negative("fetch", exact_key)
        if ttl > 0 and _is_cacheable(content):
            _write_cache(path, url, content)
            _enforce_size_cap(root, _max_bytes())
        return content
    finally:
        if _research_budget is not None:
            _research_budget.release_request(claim_token)


async def _jina_delegate_fetch(url: str) -> str:
    """委派给 harness 自带的 jina `web_fetch` 异步工具；其读本 `web_fetch` stanza 的 timeout(30)。"""
    import importlib

    mod = importlib.import_module("deerflow.community.jina_ai.tools")
    tool_obj = mod.web_fetch_tool
    fn = getattr(tool_obj, "coroutine", None)  # async @tool 的原协程函数
    if fn is not None:
        return await fn(url)
    return await tool_obj.ainvoke({"url": url})  # 兜底：走 BaseTool 的异步调用面


# ---------------------------------------------------------------------------
# harness 入口：langchain BaseTool（config.yaml `use:` 指向本变量）。
# 无 langchain 的离线环境 import 本模块仍需成功（纯缓存逻辑可测），故缺失时该变量为 None。
# ---------------------------------------------------------------------------
try:
    from langchain_core.tools import tool as _lc_tool

    @_lc_tool("web_fetch", parse_docstring=True)
    async def web_fetch_tool(url: str, revisit_reason: str = "") -> str:
        """Fetch the contents of a web page at a given URL.
        Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
        This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
        Do NOT add www. to URLs that do NOT have them.
        URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

        Args:
            url: The URL to fetch the contents of.
            revisit_reason: Optional specific reason the already-returned full page must be revisited. Leave empty for normal use.
        """
        return await cached_fetch(url, _resilient_fetch, revisit_reason)

except ImportError:  # noqa: BLE001 — 离线环境无 langchain：纯缓存逻辑仍可测
    web_fetch_tool = None  # type: ignore[assignment]
