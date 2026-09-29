"""Bridge config-reflected tool: web_search 后端调度器（ITEM 6，degrade-safe）。

harness 的 `web_search` 只能在 config.yaml 里**静态**选一个 provider（serper / tavily /
ddg 各自一段 `use:`，YAML 无法按 env 条件挑选）。本模块提供**单一** `web_search` 工具，
在**调用时**按 env 里配了哪把 key 挑后端，再把调用**原样委派**给 harness 自带的对应
community 工具函数——因此行为与直接在 config 里选那个 provider **逐字节一致**：

    SERPER_API_KEY 已配 → deerflow.community.serper.tools:web_search_tool
    否则 TAVILY_API_KEY 已配 → deerflow.community.tavily.tools:web_search_tool
    否则 FIRECRAWL_API_KEY 已配 → 本模块直连 Firecrawl v2 /search（无 community 模块）
    都没配（零 key）→ deerflow.community.ddg_search.tools:web_search_tool（社区 DDG，无需 key）

约束（对齐 market_tools.py 的部署/自包含语义）：

* **config.yaml 里以裸模块名注册**：`use: search_tools:web_search_tool`（group: web，
  max_results: 10）。deerflow_research.py 以 ``python <deer-flow>/deerflow_research.py``
  启动，``sys.path[0]`` 即脚本目录，本模块与 config.yaml 一同同步到该目录后即可被
  harness 的 reflection 以裸模块名导入。
* **委派而非重实现**：把调用转交 harness 自己的 community 工具函数，max_results / region /
  backend 等仍由它们各自读 ``get_app_config().get_tool_config("web_search")``——由于本调度器
  以 `web_search` 之名注册，读到的正是**本** stanza（max_results: 10），故与直接配置该 provider
  完全同参。
* **deerflow.* 延迟导入**：community 工具只在调用时才 import，因此本模块在无 deerflow /
  无 langchain 的离线环境（纯逻辑单测）也能成功 import；``web_search_tool`` 变量在无
  langchain 时为 None（与 market_tools.py 同构）。
* **degrade-safe**：被选后端导入失败 → 回退 DDG；连 DDG 也不可用 → 返回带说明的空结果
  JSON，绝不向 agent 循环抛异常。零 key 配置下即 byte-equivalent 的 DDG 行为。
* **env 旋钮沿用既有 provider key 名**：SERPER_API_KEY / TAVILY_API_KEY（与 config.yaml
  注释里的 $VAR 同名，与各 community 工具自身读取的 env 同名）。
* **WAVE9 —— 搜索结果磁盘缓存**（镜像 cached_fetch.py）：RESEARCH_SEARCH_CACHE_TTL_H
  （默认 6h，0=关闭）/ RESEARCH_SEARCH_CACHE_DIR / RESEARCH_SEARCH_CACHE_MAX_MB（默认 200）。
  键 = sha256(实际后端 + 归一化 query + max_results)；只缓存成功非空结果；缓存层任何异常
  → 透明直连，绝不改变搜索结果本身。
* **LOOP-007 —— 跨进程预算**：编排器提供 RESEARCH_BUDGET_DB 后，每次工具调用先计 attempt；
  正缓存 miss 后才原子占用 global/lane 网络额度。exact 空结果只放行一次重试，随后在 10 分钟
  TTL 内稳定抑制。账本故障 fail-open，并写 research_budget.json degraded 遥测。
* **RESEARCH-2 —— 类型化来源结果**（RESEARCH_SOURCE_TAXONOMY，缺省关）：开启时 Firecrawl
  错误 JSON 在原 "error" 之外追加 failure_class（not_configured / unavailable / budget）、
  provider、reason；DDG 的 "No results found" 标注 empty_unconfirmed（可能是故障而非真空）。
  后端替换（configured→ddg）总是记入进程内 provider_events()。关 = 输出逐字节不变。
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import random
import re
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:  # copied beside this module by the bridge sync guard; absence is fail-open
    import research_budget as _research_budget
except ImportError:  # pragma: no cover - exercised only by incomplete deployments
    _research_budget = None  # type: ignore[assignment]

try:  # keep search discovery aligned with fetch/final source admission
    from cached_fetch import _source_policy_rejection
except ImportError:  # pragma: no cover - incomplete deployment remains usable
    _source_policy_rejection = None  # type: ignore[assignment]

# provider → harness community 模块路径（延迟导入，见 _load_search_module）
_PROVIDER_MODULES = {
    "serper": "deerflow.community.serper.tools",
    "tavily": "deerflow.community.tavily.tools",
    "ddg": "deerflow.community.ddg_search.tools",
}

# 默认 max_results：与 config.yaml 本 stanza 对齐（深研究单轮吃 10 条覆盖面翻倍）。
DEFAULT_MAX_RESULTS = 10

# —— Firecrawl 花费护栏（Session B：单 run 烧掉 ~$100 credit 的事后防线）——
# Firecrawl /search 按**返回结果条数**计费：实际上送 limit=min(调用方 max_results, 条数
# 上限)。调用硬上限兜住失控循环（每个研究子进程即一条 lane，进程内计数就是 per-lane 计数）。
DEFAULT_FIRECRAWL_SEARCH_LIMIT = 5           # 单次 /search 计费结果条数上限
DEFAULT_FIRECRAWL_SEARCH_CALL_CEILING = 300  # 单进程 /search 计费调用上限；<=0=不限
_firecrawl_search_calls = 0        # 本进程已发出的真实 /search 计费调用数
_firecrawl_ceiling_warned = False  # 越线只 warn 一次，不逐调用刷屏

# —— Firecrawl 限流护栏（2026-09-17：实测 key 为 25 req/min，3 条 lane × fan-out 并发
# 搜索时 429 连片，主 agent 的直连搜索几乎全军覆没）——
# 1) 进程内滚动窗口节流：本进程每 60s 最多 RESEARCH_FIRECRAWL_CALLS_PER_MINUTE（默认 8）
#    次真实 /search（3 lane × 8 ≈ 24，留 1 次余量给本机其他进程）；<=0 关闭。窗口满则
#    sleep 到最早一次调用滑出 60s 窗口（带上限，绝不无限等）。
# 2) 429 有界重试：firecrawl 的 429 body 带 "please retry after Ns" 提示——解析后按
#    min(提示 + 抖动, 上限) 退避重试，至多 RESEARCH_FIRECRAWL_SEARCH_MAX_RETRIES
#    （默认 4）次；仍失败才向 agent 返回 {"error"}。
DEFAULT_FIRECRAWL_CALLS_PER_MINUTE = 8
DEFAULT_FIRECRAWL_SEARCH_MAX_RETRIES = 4
_FIRECRAWL_RETRY_AFTER_RE = re.compile(r"retry after (\d+)\s*s", re.IGNORECASE)
_firecrawl_window: list[float] = []  # 本进程最近 60s 内发出请求的 monotonic 时间戳

# —— RESEARCH-2：类型化来源结果（RESEARCH_SOURCE_TAXONOMY，缺省关）——
# Firecrawl 401/402 = credential/quota refusal: no later search in this run can
# succeed, so the v3 tool layer latches it instead of retrying every query.
_FIRECRAWL_NOT_CONFIGURED_STATUSES = frozenset({401, 402})
_TAXONOMY_TRUTHY = frozenset({"1", "true", "yes", "on"})
# Process-local provider events ("substitution:<configured>->ddg" -> count).
# Always recorded; linear_research reads them only with the taxonomy on.
_PROVIDER_EVENTS: dict[str, int] = {}
_PROVIDER_EVENTS_LOCK = threading.Lock()


def _source_taxonomy_on() -> bool:
    """RESEARCH_SOURCE_TAXONOMY (default off; the orchestrator forwards Config's value)."""
    return os.environ.get("RESEARCH_SOURCE_TAXONOMY", "").strip().lower() in _TAXONOMY_TRUTHY


def _record_provider_event(name: str) -> None:
    with _PROVIDER_EVENTS_LOCK:
        _PROVIDER_EVENTS[name] = _PROVIDER_EVENTS.get(name, 0) + 1


def provider_events() -> dict[str, int]:
    """Snapshot (deep copy) of this process's search provider events."""
    with _PROVIDER_EVENTS_LOCK:
        return copy.deepcopy(_PROVIDER_EVENTS)


def reset_provider_events() -> None:
    """Forget this process's search provider events (a new process starts empty)."""
    with _PROVIDER_EVENTS_LOCK:
        _PROVIDER_EVENTS.clear()


def _firecrawl_error(error: str, query: str, failure_class: str, reason: str) -> str:
    """Firecrawl's legacy ``{"error", "query"}`` envelope; with the taxonomy on,
    also its failure_class, provider and reason (legacy keys first, unchanged)."""
    payload: dict[str, Any] = {"error": error, "query": query}
    if _source_taxonomy_on():
        payload.update({"failure_class": failure_class, "provider": "firecrawl",
                        "reason": reason})
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# WAVE9 —— web_search 结果磁盘缓存（镜像 cached_fetch.py 的模式，自包含不 import 桥）。
# 3 条并行研究轨 × 至多 8 个 fan-out worker 围着同一 brief 搜索，近重复 query 大量重发；
# fetch 侧早有 72h 缓存（cached_fetch.py），search 侧此前没有。这里加一层短 TTL 磁盘缓存：
#   目录  env RESEARCH_SEARCH_CACHE_DIR（默认 <module_dir>/.cache/search_cache）
#   键    sha256(provider + 归一化 query + max_results)
#   值    {provider, query, result, fetched_at(epoch), result_len}
#   TTL   env RESEARCH_SEARCH_CACHE_TTL_H（默认 6h；0=关闭缓存，透明直连）
#   上限  env RESEARCH_SEARCH_CACHE_MAX_MB（默认 200；<=0=不限；超限按 mtime LRU 淘汰）
# 绝不缓存失败/空结果（error JSON、空 results 列表、过短正文）；缓存层任何异常都被吞掉并
# 回退「直接委派并返回」，绝不改变搜索结果本身（degrade-safe）。
# ---------------------------------------------------------------------------
SEARCH_CACHE_DEFAULT_TTL_HOURS = 6.0
SEARCH_CACHE_DEFAULT_MAX_MB = 200.0
# 可缓存结果的最短长度：短于此的返回体多半是空壳/瞬时失败，不值得固化。
SEARCH_CACHE_MIN_CHARS = 20

_WS_RE = re.compile(r"\s+")


def _search_cache_root() -> str:
    """缓存目录：RESEARCH_SEARCH_CACHE_DIR 覆盖，缺省 <module_dir>/.cache/search_cache。"""
    raw = os.environ.get("RESEARCH_SEARCH_CACHE_DIR", "").strip()
    if raw:
        return os.path.expanduser(raw)
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, ".cache", "search_cache")


def _search_ttl_seconds() -> float:
    """TTL（秒）。RESEARCH_SEARCH_CACHE_TTL_H 缺省 6h；<=0 → 0（关闭缓存）。非法值回退默认。

    测试卫生：pytest 会以裸 monkeypatch 直接调 web_search_impl（不设缓存 env）——若默认
    TTL 生效会把假 payload 固化进 <module_dir>/.cache 并跨测试串味。故未显式设置 TTL 且
    处于 pytest 进程内（PYTEST_CURRENT_TEST）时视为关闭；显式设置 env 的缓存单测不受影响。
    生产/子进程运行不设 PYTEST_CURRENT_TEST，默认 6h 照常生效。
    """
    raw = os.environ.get("RESEARCH_SEARCH_CACHE_TTL_H", "").strip()
    if not raw and "PYTEST_CURRENT_TEST" in os.environ:
        return 0.0
    try:
        hours = float(raw) if raw else SEARCH_CACHE_DEFAULT_TTL_HOURS
    except (TypeError, ValueError):
        hours = SEARCH_CACHE_DEFAULT_TTL_HOURS
    return max(0.0, hours) * 3600.0


def _search_max_bytes() -> int:
    """缓存目录字节上限。RESEARCH_SEARCH_CACHE_MAX_MB 缺省 200；<=0 → 0（不限）。"""
    raw = os.environ.get("RESEARCH_SEARCH_CACHE_MAX_MB", "").strip()
    try:
        mb = float(raw) if raw else SEARCH_CACHE_DEFAULT_MAX_MB
    except (TypeError, ValueError):
        mb = SEARCH_CACHE_DEFAULT_MAX_MB
    return int(max(0.0, mb) * 1024 * 1024)


def _normalize_query(query: Any) -> str:
    """query 归一化（纯函数）：strip + 空白折叠 + 小写——让仅大小写/空白不同的近重复 query 命中同键。"""
    return _WS_RE.sub(" ", str(query or "").strip()).lower()


def _search_cache_key(provider: str, query: str, max_results: int) -> str:
    """(provider, 归一化 query, max_results) → sha256 hexdigest（稳定、文件名安全）。"""
    raw = f"{provider}\n{_normalize_query(query)}\n{int(max_results)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _search_cache_path(root: str, key: str) -> str:
    return os.path.join(root, key + ".json")


def _is_search_cacheable(result: Any) -> bool:
    """仅缓存**成功且非空**的结果：str、≥最短长度、非 error JSON、非空结果列表（纯函数）。"""
    if not isinstance(result, str):
        return False
    stripped = result.strip()
    if not stripped or len(stripped) < SEARCH_CACHE_MIN_CHARS:
        return False
    try:
        obj = json.loads(stripped)
    except ValueError:
        return True  # 非 JSON 正文（某些后端返回格式化文本）——非空即可缓存
    if isinstance(obj, dict):
        if "error" in obj:
            return False
        results = obj.get("results")
        if isinstance(results, list) and not results:
            return False
        return True
    if isinstance(obj, list):
        return bool(obj)
    return True


def _is_search_no_result(result: Any) -> bool:
    """Identify an actual empty result without negative-caching transient errors."""
    if not isinstance(result, str):
        return False
    stripped = result.strip()
    if not stripped:
        return True
    try:
        obj = json.loads(stripped)
    except ValueError:
        return len(stripped) < 200 and bool(re.search(
            r"\b(?:no|zero)\s+(?:search\s+)?results?\b|\bnothing\s+found\b",
            stripped,
            re.I,
        ))
    if isinstance(obj, dict):
        if obj.get("error"):
            return False
        results = obj.get("results")
        return isinstance(results, list) and not results
    return isinstance(obj, list) and not obj


def _filter_denied_search_results(result: Any) -> str:
    """Remove structured result rows whose URL violates source policy.

    This runs on both old cache entries and fresh provider output, preventing a
    denied AI/SEO aggregator from entering model context simply because it was
    discovered by search rather than fetched. Non-JSON provider text remains
    byte-for-byte unchanged because it has no reliable row boundary.
    """
    text = result if isinstance(result, str) else str(result)
    if _source_policy_rejection is None:
        return text
    try:
        obj = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return text

    def allowed(row: Any) -> bool:
        if not isinstance(row, dict):
            return True
        url = row.get("url") or row.get("link") or row.get("href")
        return not (url and _source_policy_rejection(str(url)))

    changed = False
    if isinstance(obj, dict) and isinstance(obj.get("results"), list):
        original = obj["results"]
        filtered = [row for row in original if allowed(row)]
        changed = len(filtered) != len(original)
        if changed:
            obj = dict(obj)
            obj["results"] = filtered
    elif isinstance(obj, list):
        filtered = [row for row in obj if allowed(row)]
        changed = len(filtered) != len(obj)
        if changed:
            obj = filtered
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True)
            if changed else text)


def _mark_unconfirmed_empty(result: str) -> str:
    """Annotate the community DDG tool's ``{"error": "No results found", ...}``.

    The DDG tool swallows every engine error (throttling included) into the
    same payload as a genuine empty result, so the payload proves nothing
    about absence: add ``empty_unconfirmed`` and ``provider`` (other keys kept).
    Such payloads carry "error", so they are neither negative- nor disk-cached.
    """
    try:
        obj = json.loads(result)
    except (TypeError, ValueError):
        return result
    if not isinstance(obj, dict):
        return result
    if not str(obj.get("error") or "").casefold().startswith("no results"):
        return result
    return json.dumps({**obj, "empty_unconfirmed": True, "provider": "ddg"},
                      ensure_ascii=False)


def _budget_denial(tool: str, reason: str, request: str) -> str:
    if _research_budget is not None:
        return _research_budget.denial_result(tool, reason, request)
    return json.dumps({
        "error": "research_budget_exhausted", "tool": tool,
        "budget": reason, "request": request, "results": [],
    }, ensure_ascii=False, sort_keys=True)


def _read_search_cache(path: str, ttl_seconds: float) -> Optional[str]:
    """命中且未过期 → 返回 result（并 touch mtime 供 LRU 记「近用」）；否则 None。任何异常 → None。

    过期判定基于落盘时记录的 ``fetched_at``（真实搜索时刻），不用 mtime——与 cached_fetch.py
    同一设计：命中会 touch mtime 作 LRU 近用标记，二者混用会让被反复命中的条目永不过期。
    """
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        fetched_at = float(obj.get("fetched_at") or 0.0)
        result = obj.get("result")
        if not isinstance(result, str):
            return None
        if (time.time() - fetched_at) > ttl_seconds:
            return None  # 过期 → 视作未命中（调用方将重搜覆盖）
        try:
            os.utime(path, None)
        except OSError:
            pass
        return result
    except Exception:  # noqa: BLE001 — 缓存读损坏/并发写中 → 当作未命中，degrade-safe
        return None


def _write_search_cache(path: str, provider: str, query: str, result: str) -> None:
    """原子写缓存条目（temp+replace）。best-effort：任何失败静默跳过（不影响返回结果）。"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {
            "provider": provider,
            "query": query,
            "result": result,
            "fetched_at": time.time(),
            "result_len": len(result),
        }
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception as e:  # noqa: BLE001
        logger.warning("search_tools: 写搜索缓存失败（跳过，不影响结果）: %s", e)


def _enforce_search_cache_cap(root: str, max_bytes: int) -> None:
    """目录总字节超上限时，按 mtime 升序（最久未用）淘汰缓存文件。best-effort，任何异常静默跳过。"""
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
        logger.warning("search_tools: 淘汰搜索缓存失败（跳过）: %s", e)


def _select_search_provider() -> str:
    """按 env 里配了哪把 key 选后端：serper > tavily > firecrawl > ddg（纯函数，可离线单测）。

    只读 env，不触网、不 import deerflow——供 monkeypatch 环境变量的调度单测直接调用。
    键值取 strip 后非空才算「已配」（空串=未配，与桥的 provider-key 预置空串卫生一致）。
    firecrawl 无 harness community 模块，走本模块的直连实现（_firecrawl_search）；取证
    显示零 key 的社区 DDG 在 2026-07-14 人形机器人 run 中 78% 返回空结果，配置 Firecrawl
    key 后它取代 DDG 成为实际后端。
    """
    if os.environ.get("SERPER_API_KEY", "").strip():
        return "serper"
    if os.environ.get("TAVILY_API_KEY", "").strip():
        return "tavily"
    if os.environ.get("FIRECRAWL_API_KEY", "").strip():
        return "firecrawl"
    return "ddg"


def _firecrawl_search_available() -> bool:
    """firecrawl 后端可用 = key 已配 + httpx 可导入（不触网，供调度回退判断）。"""
    if not os.environ.get("FIRECRAWL_API_KEY", "").strip():
        return False
    try:
        import httpx  # noqa: F401

        return True
    except ImportError:
        return False


def _firecrawl_search_limit_cap() -> int:
    """单次 /search 计费结果条数上限。RESEARCH_FIRECRAWL_SEARCH_LIMIT 缺省 5；下限 1。
    非法值回退默认。Firecrawl 按条计费，实际上送 limit=min(调用方 max_results, 此上限)。"""
    raw = os.environ.get("RESEARCH_FIRECRAWL_SEARCH_LIMIT", "").strip()
    try:
        value = int(float(raw)) if raw else DEFAULT_FIRECRAWL_SEARCH_LIMIT
    except (TypeError, ValueError):
        value = DEFAULT_FIRECRAWL_SEARCH_LIMIT
    return max(1, value)


def _firecrawl_search_call_ceiling() -> int:
    """单进程 /search 计费调用硬上限。RESEARCH_FIRECRAWL_MAX_SEARCH_CALLS_PER_PROCESS
    缺省 300；<=0=不限。非法值回退默认。"""
    raw = os.environ.get(
        "RESEARCH_FIRECRAWL_MAX_SEARCH_CALLS_PER_PROCESS", "").strip()
    try:
        value = int(float(raw)) if raw else DEFAULT_FIRECRAWL_SEARCH_CALL_CEILING
    except (TypeError, ValueError):
        value = DEFAULT_FIRECRAWL_SEARCH_CALL_CEILING
    return value


def get_firecrawl_call_counts() -> dict[str, int]:
    """进程内 Firecrawl 计费调用计数快照（供未来预算遥测导出；本模块只有 search 面）。"""
    return {"search": _firecrawl_search_calls}


def _firecrawl_calls_per_minute() -> int:
    """进程内每分钟 /search 配额。RESEARCH_FIRECRAWL_CALLS_PER_MINUTE 缺省 8；<=0 关闭节流。"""
    raw = os.environ.get("RESEARCH_FIRECRAWL_CALLS_PER_MINUTE", "").strip()
    try:
        return int(float(raw)) if raw else DEFAULT_FIRECRAWL_CALLS_PER_MINUTE
    except (TypeError, ValueError):
        return DEFAULT_FIRECRAWL_CALLS_PER_MINUTE


def _firecrawl_search_max_retries() -> int:
    """429 有界重试次数。RESEARCH_FIRECRAWL_SEARCH_MAX_RETRIES 缺省 4；0=不重试。"""
    raw = os.environ.get("RESEARCH_FIRECRAWL_SEARCH_MAX_RETRIES", "").strip()
    try:
        return max(0, int(float(raw)) if raw else DEFAULT_FIRECRAWL_SEARCH_MAX_RETRIES)
    except (TypeError, ValueError):
        return DEFAULT_FIRECRAWL_SEARCH_MAX_RETRIES


def _firecrawl_throttle() -> None:
    """滚动窗口节流：60s 内超过配额则睡到最早一次调用滑出窗口（封顶 65s，防时钟异常卡死）。"""
    global _firecrawl_window
    cap = _firecrawl_calls_per_minute()
    if cap <= 0:
        return
    now = time.monotonic()
    _firecrawl_window = [t for t in _firecrawl_window if now - t < 60.0]
    if len(_firecrawl_window) < cap:
        _firecrawl_window.append(now)
        return
    wait = min(60.0 - (now - _firecrawl_window[0]) + 0.05, 65.0)
    if wait > 0:
        logger.info(
            "search_tools: Firecrawl 进程内 %d/min 节流，等待 %.1fs", cap, wait)
        time.sleep(wait)
    now = time.monotonic()
    _firecrawl_window = [t for t in _firecrawl_window if now - t < 60.0]
    _firecrawl_window.append(now)


def _firecrawl_search(query: str, max_results: int) -> str:
    """Firecrawl v2 /search 直连实现，输出与 community 工具同形的 JSON 字符串。

    成功 → {"query", "total_results", "results":[{title,url,content}]}；真实空结果 →
    total_results=0 + results=[]（可被负缓存抑制重复空查询）；传输/HTTP 错误 →
    {"error", "query"}（不负缓存，交由上层按瞬态处理）。绝不抛异常、绝不回显凭据。
    花费护栏：limit 被 RESEARCH_FIRECRAWL_SEARCH_LIMIT 钳制（按条计费）；进程内计费调用
    数达上限后直接返回瞬态 {"error"} 形状（不触网、不负缓存），越线只 warn 一次。
    """
    global _firecrawl_search_calls, _firecrawl_ceiling_warned
    api_key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    q = str(query or "").strip()
    ceiling = _firecrawl_search_call_ceiling()
    if ceiling > 0 and _firecrawl_search_calls >= ceiling:
        if not _firecrawl_ceiling_warned:
            _firecrawl_ceiling_warned = True
            logger.warning(
                "search_tools: Firecrawl 本进程 search 计费调用已达上限 %d，"
                "后续搜索直接返回瞬态错误（不再产生 Firecrawl 费用）", ceiling)
        return _firecrawl_error(
            f"firecrawl search per-run call ceiling reached ({ceiling})", q,
            "budget", "per_run_call_ceiling")
    try:
        import httpx

        timeout = float(os.environ.get(
            "RESEARCH_FIRECRAWL_SEARCH_TIMEOUT_SECONDS", "20") or "20")
        endpoint = os.environ.get(
            "FIRECRAWL_SEARCH_API_URL", "https://api.firecrawl.dev/v2/search"
        ).strip() or "https://api.firecrawl.dev/v2/search"
        limit = max(1, min(int(max_results), _firecrawl_search_limit_cap()))
        _firecrawl_search_calls += 1  # 计在发出请求前：HTTP 4xx/5xx 同样可能计费
        max_retries = _firecrawl_search_max_retries()
        attempt = 0
        while True:
            _firecrawl_throttle()
            with httpx.Client(timeout=timeout, trust_env=True) as client:
                response = client.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "query": q,
                        "limit": limit,
                        "sources": ["web"],
                    },
                )
            if response.status_code != 429 or attempt >= max_retries:
                break
            # 429：优先信 body 里的 "please retry after Ns" 提示，缺省退避 5s×2^n + 抖动。
            hint = 5.0 * (2 ** attempt)
            m = _FIRECRAWL_RETRY_AFTER_RE.search(response.text or "")
            if m:
                hint = float(m.group(1)) + 1.0
            backoff = min(hint + random.uniform(0.0, 2.0), 70.0)
            logger.warning(
                "search_tools: Firecrawl /search 429（第 %d/%d 次重试，退避 %.1fs）",
                attempt + 1, max_retries, backoff)
            attempt += 1
            time.sleep(backoff)
        if response.status_code >= 400:
            status = response.status_code
            return _firecrawl_error(
                f"firecrawl search HTTP {status}", q,
                "not_configured" if status in _FIRECRAWL_NOT_CONFIGURED_STATUSES
                else "unavailable",
                f"http_{status}")
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        # v2 按 source 分组（{"web":[...]}）；容忍 v1 风格的裸列表。
        rows = data.get("web") if isinstance(data, dict) else data
        results = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            if not url:
                continue
            results.append({
                "title": str(row.get("title") or "").strip() or url,
                "url": url,
                "content": str(row.get("description") or row.get("snippet")
                               or "").strip(),
            })
        return json.dumps(
            {"query": q, "total_results": len(results), "results": results},
            ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 — 不回显异常正文（可能含 bearer 头）
        return _firecrawl_error(
            f"firecrawl search failed: {type(exc).__name__}", q,
            "unavailable", type(exc).__name__)


def _load_search_module(provider: str) -> Optional[Any]:
    """延迟 import 指定 provider 的 harness community 工具模块；失败返回 None（degrade-safe）。"""
    path = _PROVIDER_MODULES.get(provider)
    if not path:
        return None
    try:
        import importlib

        return importlib.import_module(path)
    except Exception as e:  # noqa: BLE001 — 无 deerflow / provider 依赖缺失 → 交由上层回退
        logger.warning("search_tools: 导入 %s 失败（%s）", path, e)
        return None


def _call_delegate(tool_obj: Any, query: str, max_results: int) -> str:
    """调用一个 harness community `web_search` 工具对象，把结果原样返回。

    community 工具是 langchain `@tool` 装饰出的 StructuredTool；其未装饰的原函数在
    ``.func`` 上。ddg/serper 的原函数签名含 max_results，tavily 只有 query（自 config 读
    max_results）——故仅在被调函数确有 max_results 形参时才传，避免 TypeError。无论是否传，
    community 工具都以 config 的 max_results 覆盖（本 stanza=10），因此结果与直接配置一致。
    """
    fn = getattr(tool_obj, "func", None) or tool_obj
    kwargs: dict[str, Any] = {"query": query}
    try:
        import inspect

        if "max_results" in inspect.signature(fn).parameters:
            kwargs["max_results"] = int(max_results)
    except (TypeError, ValueError):  # 签名不可内省/取整失败 → 只传 query（community 工具读 config）
        pass
    return fn(**kwargs)


def web_search_impl(
    query: str,
    max_results: int = DEFAULT_MAX_RESULTS,
    revisit_reason: str = "",
) -> str:
    """纯逻辑入口：选后端 → 查缓存 → 委派 → 落缓存 → 返回结果字符串。任何内部错误 → 带说明的空结果，绝不抛。

    调度纪律：选中的 provider 若导入不可用（无 deerflow / provider 依赖缺失），回退 DDG；
    连 DDG 也不可用则返回空结果 JSON（与 community 工具的「无结果」形状一致）。
    WAVE9：委派前后各加一层短 TTL 磁盘缓存（键含**实际使用**的 provider，回退 DDG 时按 ddg 记）；
    缓存关闭（TTL<=0）或 query 归一化后为空时绕过正缓存；LOOP-007 预算仍独立生效。
    """
    provider = _select_search_provider()
    configured = provider
    if _research_budget is not None:
        attempt = _research_budget.admit_attempt("search")
        if not attempt.allowed:
            return _budget_denial("web_search", attempt.reason, query)
    if provider == "firecrawl" and not _firecrawl_search_available():
        # firecrawl 依赖缺失（无 httpx）→ 与 community 模块导入失败同类，回退 DDG。
        logger.warning("search_tools: 后端 firecrawl 不可用（httpx 缺失），回退 DDG")
        provider = "ddg"
    tool_obj = None
    if provider != "firecrawl":
        mod = _load_search_module(provider)
        if (mod is None or getattr(mod, "web_search_tool", None) is None) and provider != "ddg":
            # 被选后端不可用 → 回退社区 DDG（零 key 兜底路径，无需任何依赖之外的东西）
            logger.warning("search_tools: 后端 %s 不可用，回退 DDG", provider)
            provider = "ddg"  # WAVE9：缓存键按实际委派的后端记，避免跨后端串味
            mod = _load_search_module("ddg")
        tool_obj = getattr(mod, "web_search_tool", None) if mod is not None else None
        if tool_obj is None:
            return json.dumps({"error": "no web_search backend available", "query": query},
                              ensure_ascii=False)
    if provider != configured:
        # RESEARCH-2: a silent substitution is visible to the engine's health events.
        _record_provider_event(f"substitution:{configured}->{provider}")
    # Provider fallback changes the actual request identity; negative-cache the
    # delegate that was really used, just like the positive disk-cache key.
    exact_key = f"{provider}\n{_normalize_query(query)}\n{int(max_results)}"
    # WAVE9：缓存读——TTL<=0（关闭）或空 query 时完全绕过；缓存层异常绝不阻断搜索。
    _ttl = _search_ttl_seconds()
    _cache_path_str = ""
    if _ttl > 0 and _normalize_query(query):
        try:
            _root = _search_cache_root()
            _cache_path_str = _search_cache_path(_root, _search_cache_key(provider, query, max_results))
            hit = _read_search_cache(_cache_path_str, _ttl)
            if hit is not None:
                hit = _filter_denied_search_results(hit)
                # A cache written under an older policy may contain only newly
                # denied domains. Treat that as a miss so replacements can be
                # discovered instead of returning an empty stale artifact.
                if not _is_search_cacheable(hit):
                    hit = None
            if hit is not None:
                if _research_budget is not None:
                    if not str(revisit_reason or "").strip():
                        artifact_id = _research_budget.positive_repeat(
                            "search", exact_key)
                        if artifact_id:
                            return _research_budget.compact_positive_result(
                                "web_search", artifact_id)
                    _research_budget.record_positive("search", exact_key)
                return hit
        except Exception as e:  # noqa: BLE001 — 缓存故障 → 当作未命中直连
            logger.warning("search_tools: 搜索缓存读取异常（跳过缓存）: %s", e)
            _cache_path_str = ""

    # An exact empty query receives one bounded retry inside the negative TTL.
    # This check happens after the positive cache, and before network admission.
    if (_research_budget is not None
            and _research_budget.negative_suppressed("search", exact_key)):
        return _research_budget.negative_result("web_search", query)

    claim_token = ""
    waited_for_claim = False
    if _research_budget is not None and _cache_path_str:
        claim_token = _research_budget.claim_request("search", exact_key)
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
                time.sleep(delay)
                delay = min(1.0, delay * 1.7)
                hit = _read_search_cache(_cache_path_str, _ttl)
                if hit is not None:
                    hit = _filter_denied_search_results(hit)
                    if not _is_search_cacheable(hit):
                        hit = None
                if hit is not None:
                    # Identical in-flight callers may be isolated subagents;
                    # each needs the fresh body even though only one network
                    # request is allowed.
                    _research_budget.record_positive("search", exact_key)
                    return hit
                claim_token = _research_budget.claim_request(
                    "search", exact_key)
                if claim_token:
                    break
            if not claim_token:
                return json.dumps({
                    "error": "research_inflight_timeout",
                    "tool": "web_search",
                    "message": "Timed out waiting for the identical in-flight search.",
                }, ensure_ascii=False, sort_keys=True)
    if (waited_for_claim and _research_budget is not None
            and _research_budget.negative_suppressed("search", exact_key)):
        _research_budget.release_request(claim_token)
        return _research_budget.negative_result("web_search", query)

    # Positive cache hits and singleflight followers never reach this
    # reservation and therefore do not consume network allowance.
    if _research_budget is not None:
        network = _research_budget.admit_network("search")
        if not network.allowed:
            _research_budget.release_request(claim_token)
            return _budget_denial("web_search", network.reason, query)

    try:
        result = (_firecrawl_search(query, max_results)
                  if provider == "firecrawl"
                  else _call_delegate(tool_obj, query, max_results))
        result = result if isinstance(result, str) else str(result)
        result = _filter_denied_search_results(result)
        if provider == "ddg" and _source_taxonomy_on():
            result = _mark_unconfirmed_empty(result)
    except Exception as e:  # noqa: BLE001 — 工具层最后兜底：绝不向 agent 循环抛异常
        logger.warning("search_tools: 委派 %s 失败（降级为空结果）: %s", provider, e)
        if _research_budget is not None:
            _research_budget.export_telemetry(force=True)
            _research_budget.release_request(claim_token)
        return json.dumps({"error": str(e), "query": query}, ensure_ascii=False)

    if _research_budget is not None:
        if _is_search_no_result(result):
            _research_budget.record_negative("search", exact_key)
        elif _is_search_cacheable(result):
            _research_budget.clear_negative("search", exact_key)
            _research_budget.record_positive("search", exact_key)
        else:
            _research_budget.export_telemetry(force=True)

    # WAVE9：缓存写——仅成功且非空的结果落盘；失败/空壳原样返回但不固化。
    try:
        if _cache_path_str:
            if _is_search_cacheable(result):
                _write_search_cache(_cache_path_str, provider, query, result)
                _enforce_search_cache_cap(_search_cache_root(), _search_max_bytes())
        return result
    except Exception as e:  # noqa: BLE001 — 落盘/淘汰失败绝不影响已取得的结果
        logger.warning("search_tools: 搜索缓存写入路径异常（跳过）: %s", e)
        return result
    finally:
        if _research_budget is not None:
            _research_budget.release_request(claim_token)


# ---------------------------------------------------------------------------
# harness 入口：langchain BaseTool（config.yaml `use:` 指向本变量）。
# deer-flow venv 必有 langchain_core；无 langchain 的环境（离线跑纯逻辑单测）import
# 本模块仍需成功，故 langchain 缺失时该变量为 None（与 market_tools.py 同构）。
# ---------------------------------------------------------------------------
try:
    from langchain_core.tools import tool as _lc_tool

    @_lc_tool("web_search", parse_docstring=True)
    def web_search_tool(
        query: str,
        max_results: int = DEFAULT_MAX_RESULTS,
        revisit_reason: str = "",
    ) -> str:
        """Search the web for information. Use this tool to find current information, news, articles, and facts from the internet.

        Args:
            query: Search keywords describing what you want to find. Be specific for better results.
            max_results: Maximum number of results to return. Default is 10.
            revisit_reason: Optional specific reason an identical successful result set must be returned again. Leave empty for normal use.
        """
        return web_search_impl(query, max_results, revisit_reason)

except ImportError:  # noqa: BLE001 — 离线环境无 langchain：纯逻辑仍可测
    web_search_tool = None  # type: ignore[assignment]
