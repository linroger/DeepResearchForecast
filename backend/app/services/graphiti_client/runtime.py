"""Process-global runtime that bridges the app's synchronous, threaded code to the
async, in-process Graphiti knowledge graph.

Responsibilities:
- Own a persistent asyncio event loop on a background thread (sync -> async bridge).
- Select & construct a LOCAL graph DB backend (no API key, no external service by default):
    * ``falkordblite`` (embedded FalkorDB via ``redislite.AsyncFalkorDB``) — preferred,
      Python >= 3.12, no Docker. This is the same engine Zep Cloud is built on.
    * a FalkorDB server (``FALKORDB_HOST``/``FALKORDB_PORT``) when one is provided/reachable.
    * ``kuzu`` (embedded, file-based) — optional fallback.
  Selected via ``GRAPH_BACKEND`` (default ``auto``).
- Provide the local LLM (provider-agnostic via the app's LLMClient), local embedder
  (sentence-transformers), and a local/no-op cross-encoder.
- Cache one ``Graphiti`` instance per graph_id and the per-graph custom ontology.

graph_id maps to BOTH the FalkorDB database/tenant name and the Graphiti ``group_id``
(identical string), so search/listing stay scoped per graph just like Zep's ``graph_id``.
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import contextlib
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("mirofish.graphiti_runtime")

_VALID_BACKENDS = ("auto", "falkordblite", "falkordb", "kuzu")

_GRAPH_INGEST_RATE_LIMIT_COOLDOWN_DEFAULT_S = 15.0
_GRAPH_INGEST_RATE_LIMIT_COOLDOWN_MAX_S = 60.0

# R2-KG-1 / R2-KG-3: causal attributes (sign / strength / lag / polarity / valence)
# are folded into an edge's ``fact`` text by graph_builder.seed_actors (e.g.
# "…（sign=-，strength=high，lag=2w，polarity=-0.80）"). The traversal primitives
# project the fact and parse those attributes back out so a multi-hop path carries
# per-hop sign/strength/lag and a computed NET polarity + cumulative lag — the
# difference between "A reaches B" and "A reaches B with this transmission sign/lag".
import re as _re

_FACT_ATTR_RE = {
    "sign": _re.compile(r"\bsign=([^\s，,）)、]+)", _re.IGNORECASE),
    "strength": _re.compile(r"\bstrength=([^\s，,）)、]+)", _re.IGNORECASE),
    "lag": _re.compile(r"\blag=([^\s，,）)、]+)", _re.IGNORECASE),
    "polarity": _re.compile(r"\bpolarity=([^\s，,）)、]+)", _re.IGNORECASE),
    "valence": _re.compile(r"\bvalence=([^\s，,）)、]+)", _re.IGNORECASE),
}


def _parse_edge_attrs(fact: str | None) -> dict:
    """Extract folded causal attrs from an edge fact. Missing keys → None (degrade-safe)."""
    out: dict = {"sign": None, "strength": None, "lag": None, "polarity": None, "valence": None}
    if not fact:
        return out
    for key, rx in _FACT_ATTR_RE.items():
        m = rx.search(fact)
        if m:
            out[key] = m.group(1).strip()
    return out


def _edge_polarity_sign(attrs: dict) -> int | None:
    """Map an edge's parsed attrs to a polarity sign in {+1,-1,None} for net-polarity math.

    Prefers a numeric ``polarity``; falls back to the ``sign`` token (+/-/positive/
    negative or a signed number). ``None`` when genuinely unknown (so net polarity can
    flag incomplete chains rather than silently assuming positive)."""
    pol = attrs.get("polarity")
    if pol is not None:
        try:
            v = float(pol)
            if v > 0:
                return 1
            if v < 0:
                return -1
        except (TypeError, ValueError):
            pass
    sign = (attrs.get("sign") or "").strip().lower()
    if sign in ("+", "positive", "pos", "up", "+1"):
        return 1
    if sign in ("-", "negative", "neg", "down", "-1"):
        return -1
    try:
        v = float(sign)
        if v > 0:
            return 1
        if v < 0:
            return -1
    except (TypeError, ValueError):
        pass
    return None


def _lag_numeric(lag: str | None) -> float | None:
    """Best-effort numeric magnitude of a lag token (unit-agnostic leading number)."""
    if not lag:
        return None
    m = _re.search(r"-?\d+(?:\.\d+)?", str(lag))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _data_dir() -> str:
    d = os.environ.get("GRAPHITI_DATA_DIR")
    if not d:
        try:
            from ...config import Config

            d = Config.GRAPHITI_DATA_DIR
        except Exception:
            # backend/app/services/graphiti_client -> backend/uploads/graphiti_db
            d = os.path.join(os.path.dirname(__file__), "..", "..", "..", "uploads", "graphiti_db")
    d = os.path.abspath(d)
    os.makedirs(d, exist_ok=True)
    return d


def _default_op_timeout() -> float | None:
    """每个 Graphiti 操作（一次 add_episode / search / list…）的默认挂钟上限（秒）。

    读 Config.GRAPHITI_OP_TIMEOUT_S（config 默认 900 = 15 分钟，GRAPH-9 调低；本函数的
    getattr 兜底 1800 仅在 Config 缺该属性时生效）；0/负 = 不设上限（旧行为，无限等待）。
    给 sync→async 桥一个兜底，避免某次 LLM/DB 调用卡死时永久阻塞调用线程。
    """
    try:
        from ...config import Config
        v = float(getattr(Config, "GRAPHITI_OP_TIMEOUT_S", 1800) or 0)
        return v if v > 0 else None
    except Exception:  # noqa: BLE001 — 读不到配置就用保守的 30 分钟兜底
        return 1800.0


def _chunk_attempt_budget() -> int | None:
    """W10-COST: per-chunk cap on TOTAL full-extraction attempts (outermost layer).

    One "attempt" = one complete ``_add_episode_once`` pass (which internally
    still runs graphiti's tenacity ×4 and the llm_adapter temperature ladder ×2
    per extraction call). The budget spans the episode-level schema re-roll,
    the fallback-provider swap AND the concurrent batch's rate-limit replay, so
    a doomed chunk can no longer stack ladders (measured: 23,496 rate-limit/
    connection-error log lines in one day). Reads Config.GRAPH_CHUNK_MAX_ATTEMPTS
    (default 2); <=0 → None = uncapped legacy topology.
    """
    try:
        from ...config import Config

        value = int(getattr(Config, "GRAPH_CHUNK_MAX_ATTEMPTS", 2) or 0)
    except Exception:  # noqa: BLE001 — 读不到配置时保守封顶
        return 2
    return value if value > 0 else None


def _graph_ingest_rate_limit_cooldown_s() -> float:
    """Return the single post-fan-out 429 cooldown, clamped to a safe bound.

    This knob intentionally lives in the graph runtime so the recovery remains a
    self-contained ingestion repair: ``GRAPH_INGEST_RATE_LIMIT_COOLDOWN_S`` may
    tune the wait from 0 to 60 seconds, while invalid values retain the bounded
    15-second default.
    """
    raw = os.environ.get(
        "GRAPH_INGEST_RATE_LIMIT_COOLDOWN_S",
        str(_GRAPH_INGEST_RATE_LIMIT_COOLDOWN_DEFAULT_S),
    )
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = _GRAPH_INGEST_RATE_LIMIT_COOLDOWN_DEFAULT_S
    if value != value:  # NaN
        value = _GRAPH_INGEST_RATE_LIMIT_COOLDOWN_DEFAULT_S
    return min(_GRAPH_INGEST_RATE_LIMIT_COOLDOWN_MAX_S, max(0.0, value))


class GraphitiRuntime:
    """Singleton bridge to Graphiti. Access via ``get_runtime()``."""

    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="graphiti-loop", daemon=True
        )
        self._thread.start()

        self._graphs: dict = {}        # graph_id -> Graphiti
        self._ontologies: dict = {}    # graph_id -> (entity_types, edge_types, edge_type_map)
        self._falkor_client = None
        self._embedder = None
        self._llm = None
        self._cross_encoder = None
        self._ensure_lock: asyncio.Lock | None = None
        # EXECPLAN2 F-12-8 / F-2-5: per-graph_id write lock registry. The cached
        # Graphiti instance is shared by all callers, and add_episode does a
        # search→resolve→write dedup sequence across await points; two concurrent
        # writers on the SAME graph_id (e.g. a scenario fork's feedback updater
        # overlapping the base run, or add_episodes_concurrent's fan-out) can both
        # miss the dedup lookup and create duplicate entity nodes. We serialize
        # mutating access per graph_id (different graph_ids still proceed in
        # parallel). The dict is only mutated on the single bg-loop thread, so its
        # creation needs no extra lock.
        self._graph_locks: dict = {}   # graph_id -> asyncio.Lock
        self._resolved_backend: str | None = None
        # Wave9-KG（抽取加固）：episode 级 skip 原因计数（graph_id -> {reason: count}），
        # 供 graph_builder 把「为什么 48-60% 的 chunk 被跳过」写进 ingest 审计；以及
        # LLM_FALLBACK_PROVIDER 兜底客户端（懒构建）与换入引用计数（fan-out 并发安全）。
        self._ingest_skip_reasons: dict = {}   # graph_id -> {reason: count}
        self._fallback_llm = None              # AppGraphitiLLMClient | False(不可用) | None(未探测)
        self._fb_depth: dict = {}              # graph_id -> 当前处于兜底模式的 episode 数
        self._fb_primary: dict = {}            # graph_id -> 换出的主 LLM client
        atexit.register(self._shutdown)

    # ------------------------------------------------------------------
    # sync -> async bridge
    # ------------------------------------------------------------------
    def run(self, coro, timeout: float | None = None):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        # 默认给每个操作一个挂钟上限（Config.GRAPHITI_OP_TIMEOUT_S，config 默认 900s；0=旧的无限等待），
        # 避免某次 LLM/DB 调用卡死时永久阻塞调用它的 Flask 线程。超时抛 TimeoutError，调用方一般已
        # try/except 降级（检索→本地回退、构图→失败可见）。显式传 timeout 时以显式值为准。
        if timeout is None:
            timeout = _default_op_timeout()
        eff = timeout if (timeout and timeout > 0) else None
        try:
            return future.result(eff)
        except concurrent.futures.TimeoutError:
            # CRITICAL: future.result() timing out does NOT stop the coroutine — it keeps
            # running on the single bg loop, and if it holds the per-graph write lock
            # (add_episode / merge_nodes / build_communities) that lock is NEVER released,
            # so every subsequent op + read on that graph_id deadlocks and times out in a
            # cascade (observed: graph builds fine, then all post-build reads time out for
            # 15min×retries while the DB itself answers the same query in 0.01s). Cancel
            # the asyncio task threadsafely so its `async with lock` unwinds via __aexit__.
            future.cancel()
            logger.warning("graphiti op exceeded %.0fs wall-clock; cancelled to release the "
                           "per-graph lock (avoids deadlocking later reads)", eff or 0)
            raise TimeoutError(f"graphiti operation exceeded {eff:.0f}s") from None

    # EXECPLAN2 F-12-8 / F-2-5: lazily create/return the per-graph_id write lock.
    # Must be awaited from the bg loop (the only thread that touches _graph_locks).
    def _graph_lock(self, graph_id: str) -> asyncio.Lock:
        lock = self._graph_locks.get(graph_id)
        if lock is None:
            lock = asyncio.Lock()
            self._graph_locks[graph_id] = lock
        return lock

    @staticmethod
    def _serialize_reads() -> bool:
        # EXECPLAN2 F-12-8: opt-in flag. When enabled, reads take the per-graph
        # write lock too (serializing reads against in-flight writes on the same
        # graph to avoid dirty/mid-transaction reads). Default off preserves
        # current read latency/behavior (reads proceed without blocking on writes).
        return (os.environ.get("GRAPH_SERIALIZE_READS", "0") or "0").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

    @contextlib.asynccontextmanager
    async def _read_guard(self, graph_id: str):
        # EXECPLAN2 F-12-8: when GRAPH_SERIALIZE_READS is enabled, take the per-graph
        # write lock for the duration of a read so it cannot observe a write's
        # mid-transaction state; otherwise this is a no-op (default behavior).
        if self._serialize_reads():
            async with self._graph_lock(graph_id):
                yield
        else:
            yield

    # ------------------------------------------------------------------
    # backend resolution + driver construction
    # ------------------------------------------------------------------
    def _resolve_backend(self) -> str:
        if self._resolved_backend:
            return self._resolved_backend
        choice = (os.environ.get("GRAPH_BACKEND", "auto") or "auto").strip().lower()
        if choice not in _VALID_BACKENDS:
            choice = "auto"

        if choice == "auto":
            if os.environ.get("FALKORDB_HOST"):
                choice = "falkordb"
            elif self._can_import("redislite.async_falkordb_client"):
                choice = "falkordblite"
            elif self._can_import("kuzu"):
                choice = "kuzu"
            else:
                raise RuntimeError(
                    "No local graph backend available. Install one of: "
                    "'falkordblite' (embedded, recommended, Python>=3.12) or 'kuzu', "
                    "or run a FalkorDB server and set FALKORDB_HOST."
                )
        self._resolved_backend = choice
        logger.info("Graphiti graph backend: %s", choice)
        return choice

    @staticmethod
    def _can_import(module: str) -> bool:
        import importlib.util

        try:
            return importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            return False

    async def _get_falkor_client(self):
        if self._falkor_client is None:
            from redislite.async_falkordb_client import AsyncFalkorDB

            dbfile = os.path.join(_data_dir(), "falkor.db")
            self._falkor_client = AsyncFalkorDB(dbfilename=dbfile)
            logger.info("Started embedded FalkorDB (falkordblite) at %s", dbfile)
        return self._falkor_client

    async def _make_driver(self, graph_id: str):
        backend = self._resolve_backend()

        if backend == "falkordb":
            from .falkor_driver import SanitizingFalkorDriver

            host = os.environ.get("FALKORDB_HOST", "localhost")
            port = int(os.environ.get("FALKORDB_PORT", "6379"))
            password = os.environ.get("FALKORDB_PASSWORD") or None
            username = os.environ.get("FALKORDB_USERNAME") or None
            return SanitizingFalkorDriver(
                host=host, port=port, username=username, password=password, database=graph_id
            )

        if backend == "falkordblite":
            from .falkor_driver import SanitizingFalkorDriver

            client = await self._get_falkor_client()
            return SanitizingFalkorDriver(falkor_db=client, database=graph_id)

        if backend == "kuzu":
            from graphiti_core.driver.kuzu_driver import KuzuDriver

            from ...utils.security import contained_child

            # INFRA-10: graph_id arrives from API requests and MCP tool calls; it must
            # stay a single path component under <data>/kuzu (UnsafeIdError otherwise).
            path = contained_child(os.path.join(_data_dir(), "kuzu"), graph_id, "graph")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            driver = KuzuDriver(db=path)
            # Pin _database so add_episode does not attempt to clone the driver by group_id
            # (Kuzu has no per-database multi-tenancy; partitioning is by group_id property).
            driver._database = graph_id
            return driver

        raise RuntimeError(f"Unsupported graph backend: {backend}")

    def _get_clients(self):
        if self._embedder is None:
            from .embedder import LocalSentenceTransformerEmbedder
            from .llm_adapter import AppGraphitiLLMClient

            self._embedder = LocalSentenceTransformerEmbedder()
            self._llm = AppGraphitiLLMClient()

            reranker = (os.environ.get("GRAPHITI_RERANKER", "rrf") or "rrf").strip().lower()
            if reranker == "bge":
                from graphiti_core.cross_encoder.bge_reranker_client import BGERerankerClient

                self._cross_encoder = BGERerankerClient()
            else:
                from .cross_encoder import NoOpCrossEncoder

                self._cross_encoder = NoOpCrossEncoder()
        return self._embedder, self._llm, self._cross_encoder

    async def _ensure_graph(self, graph_id: str):
        if graph_id in self._graphs:
            return self._graphs[graph_id]
        if self._ensure_lock is None:
            self._ensure_lock = asyncio.Lock()
        async with self._ensure_lock:
            if graph_id in self._graphs:
                return self._graphs[graph_id]
            driver = await self._make_driver(graph_id)
            embedder, llm, cross_encoder = self._get_clients()
            from graphiti_core import Graphiti

            # Cap concurrent LLM extraction calls. Graph building drives the configured
            # LLM provider; unbounded concurrency to a hosted endpoint causes timeouts/
            # throttling. GRAPH-3: the previous effective default of 8 throttled
            # intra-episode per-node/edge fan-out to ~3-4 waves; graphiti's own default
            # is 20. Promote to a documented default of 16 (sized jointly with
            # GRAPH_BUILD_CONCURRENCY and the dedicated LLM I/O pool); override via env.
            try:
                max_coros = int(os.environ.get("GRAPHITI_MAX_COROUTINES", "16"))
            except ValueError:
                max_coros = 16
            g = Graphiti(
                graph_driver=driver,
                llm_client=llm,
                embedder=embedder,
                cross_encoder=cross_encoder,
                max_coroutines=max_coros,
            )
            # Keep group_id == driver._database so add_episode never clones the driver.
            try:
                g.driver._database = graph_id
            except Exception:  # pragma: no cover - defensive
                pass
            try:
                await g.build_indices_and_constraints()
            except Exception as exc:  # indices may already exist; non-fatal
                logger.debug("build_indices_and_constraints note for %s: %s", graph_id, exc)
            self._graphs[graph_id] = g
            return g

    async def _candidate_graph_ids(self, graph_id: str | None) -> list[str]:
        if graph_id:
            return [graph_id]
        ids = list(self._graphs.keys())
        if ids:
            return ids
        # Cold cache (e.g. fresh process): try to discover existing FalkorDB graphs.
        try:
            if self._resolve_backend() in ("falkordblite", "falkordb"):
                client = await self._get_falkor_client() if self._resolve_backend() == "falkordblite" else None
                if client is not None and hasattr(client, "list_graphs"):
                    names = await client.list_graphs()
                    return [n for n in names if isinstance(n, str)]
        except Exception:  # pragma: no cover - discovery is best-effort
            pass
        return []

    # ------------------------------------------------------------------
    # public sync API (used by the Zep facade)
    # ------------------------------------------------------------------
    def create_graph(self, graph_id: str) -> None:
        """Pre-warm a graph (build indices) so it 'exists' immediately after create()."""
        self.run(self._ensure_graph(graph_id))

    def set_ontology(self, graph_id: str, entities, edges) -> None:
        entity_types = entities or None
        edge_types = None
        edge_type_map = None
        if edges:
            edge_types = {}
            edge_type_map = {}
            for name, value in edges.items():
                # value is (EdgeModelSubclass, [EntityEdgeSourceTarget, ...])
                if isinstance(value, (tuple, list)) and len(value) == 2:
                    model, source_targets = value
                else:
                    model, source_targets = value, []
                edge_types[name] = model
                for st in source_targets or []:
                    key = (getattr(st, "source", None) or "Entity", getattr(st, "target", None) or "Entity")
                    edge_type_map.setdefault(key, []).append(name)
            if not edge_type_map:
                edge_type_map = {("Entity", "Entity"): list(edge_types.keys())}
        self._ontologies[graph_id] = (entity_types, edge_types, edge_type_map)

    def add_episode(
        self,
        graph_id: str,
        *,
        name: str,
        body: str,
        source_type: str = "text",
        source_description: str = "",
        reference_time: datetime | None = None,
    ) -> str:
        return self.run(
            self._add_episode(
                graph_id,
                name=name,
                body=body,
                source_type=source_type,
                source_description=source_description,
                reference_time=reference_time,
            )
        )

    async def _add_episode(
        self, graph_id, *, name, body, source_type, source_description, reference_time
    ) -> str:
        # EXECPLAN2 F-12-8 / F-2-5: serialize writes per graph_id so the
        # search→resolve→write dedup sequence is never interleaved with another
        # writer on the same graph (which would create duplicate same-name nodes).
        # asyncio.Lock is non-reentrant, so the actual write lives in the
        # lock-free _add_episode_locked helper that the concurrent fan-out (which
        # already holds the lock) calls directly.
        async with self._graph_lock(graph_id):
            return await self._add_episode_locked(
                graph_id,
                name=name,
                body=body,
                source_type=source_type,
                source_description=source_description,
                reference_time=reference_time,
            )

    # ------------------------------------------------------------------
    # Wave9-KG 抽取加固：episode 级重试阶梯。llm_adapter 内部已有「schema-echo 检测 +
    # 纠正提示 + 升温(0.0→0.4)」的调用级阶梯，但一次 episode 的抽取由多个 LLM 调用组成，
    # 任一调用耗尽内层阶梯就让整个 episode 报废（实测一次完整 run 有 48-60% 的 chunk
    # 因 'LLM returned a JSON schema instead of an instance' 被跳过）。这里在 episode
    # 层再补两级：(1) 整 episode 重试（重滚内层非确定性的 0.4 档升温）；(2) 重试耗尽后
    # 换入 LLM_FALLBACK_PROVIDER 兜底客户端再抽一次（GRAPH_INGEST_FALLBACK，默认开）。
    # 最终仍失败才记 skip 原因并上抛（调用方照旧隔离/记账）。
    # ------------------------------------------------------------------
    @staticmethod
    def _classify_ingest_error(exc: BaseException) -> str:
        """把 episode 抽取异常归类为可审计的 skip 原因（用于计数与重试路由）。"""
        attached_reason = getattr(exc, "_graphiti_ingest_reason", None)
        if isinstance(attached_reason, str) and attached_reason:
            return attached_reason

        # Graphiti/tenacity may wrap the useful provider exception. Inspect a
        # bounded cause/context/last_attempt chain so EmptyResponseError and 429
        # classifications survive those wrappers without making arbitrary errors
        # retryable.
        errors: list[BaseException] = []
        pending: list[BaseException] = [exc]
        seen: set[int] = set()
        while pending and len(errors) < 8:
            current = pending.pop(0)
            if id(current) in seen:
                continue
            seen.add(id(current))
            errors.append(current)
            nested = current.__cause__ or current.__context__
            if isinstance(nested, BaseException):
                pending.append(nested)
            last_attempt = getattr(current, "last_attempt", None)
            if last_attempt is not None:
                with contextlib.suppress(Exception):
                    nested = last_attempt.exception()
                    if isinstance(nested, BaseException):
                        pending.append(nested)

        msg = " | ".join(str(error).lower() for error in errors)
        error_names = {type(error).__name__.lower() for error in errors}
        if "schema instead of an instance" in msg or "schema echo" in msg:
            return "schema_echo"
        if "validation" in msg and ("failed" in msg or "error" in msg):
            return "schema_validation"
        if (
            "rate limit" in msg
            or "rate_limit" in msg
            or "429" in msg
            or any("ratelimit" in name for name in error_names)
        ):
            return "rate_limit"
        if (
            any(isinstance(error, (asyncio.TimeoutError, TimeoutError)) for error in errors)
            or "timeout" in msg
        ):
            return "timeout"
        if "content" in msg and ("filter" in msg or "sensitive" in msg):
            return "content_filter"
        parse_markers = (
            "invalid json",
            "unparseable json",
            "failed to parse json",
            "json parse failed",
            "json decode",
            "jsondecodeerror",
            "expected json object",
            "empty response",
            "response was empty",
            "llm返回的json格式无效",
            "json格式无效",
            "无法解析json",
            "json解析失败",
        )
        if (
            "emptyresponseerror" in error_names
            or "jsondecodeerror" in error_names
            or any(marker in msg for marker in parse_markers)
        ):
            return "schema_parse"
        return "other"

    def _record_skip_reason(self, graph_id: str, reason: str) -> None:
        by_reason = self._ingest_skip_reasons.setdefault(graph_id, {})
        by_reason[reason] = by_reason.get(reason, 0) + 1

    def pop_ingest_skip_reasons(self, graph_id: str) -> dict:
        """取走并清零该图累计的 episode skip 原因计数（graph_builder 折进 ingest 审计）。"""
        return dict(self._ingest_skip_reasons.pop(graph_id, {}) or {})

    def _get_fallback_llm(self):
        """懒构建 LLM_FALLBACK_PROVIDER 的 graphiti 适配客户端；不可用返回 None。"""
        if self._fallback_llm is False:
            return None
        if self._fallback_llm is not None:
            return self._fallback_llm
        try:
            from ...config import Config

            if not getattr(Config, "GRAPH_INGEST_FALLBACK", True):
                self._fallback_llm = False
                return None
            provider = (os.environ.get("LLM_FALLBACK_PROVIDER", "") or "").strip().lower()
            if not provider or provider == (getattr(Config, "LLM_PROVIDER", "") or "").strip().lower():
                self._fallback_llm = False
                return None
            from ...utils.llm_client import LLMClient as AppLLMClient
            from .llm_adapter import AppGraphitiLLMClient

            app_llm = AppLLMClient(
                provider=provider,
                model=(os.environ.get("LLM_FALLBACK_MODEL", "") or None),
                api_key=(os.environ.get("LLM_FALLBACK_API_KEY", "") or None),
                base_url=(os.environ.get("LLM_FALLBACK_BASE_URL", "") or None),
            )
            app_llm._is_fallback = True  # 与 llm_client S9 一致：兜底客户端禁止再失败转移
            self._fallback_llm = AppGraphitiLLMClient(app_llm=app_llm)
            logger.info("graphiti ingest fallback LLM ready: provider=%s", provider)
            return self._fallback_llm
        except Exception as exc:  # noqa: BLE001 — 兜底不可用 → 只用重试阶梯
            logger.warning("graphiti ingest fallback LLM unavailable: %s", exc)
            self._fallback_llm = False
            return None

    @contextlib.asynccontextmanager
    async def _fallback_llm_swapped(self, graph_id: str, g):
        """把该图的 Graphiti LLM 客户端临时换成兜底客户端（引用计数，fan-out 安全）。

        仅在 bg loop 单线程上执行；计数 0→1 换入、归 0 换回，期间其他并发 episode
        也走兜底（可接受——它们同样处于主提供方 schema-echo 风暴中）。"""
        fb = self._get_fallback_llm()
        if fb is None:
            yield False
            return
        depth = self._fb_depth.get(graph_id, 0)
        if depth == 0:
            self._fb_primary[graph_id] = g.llm_client
            with contextlib.suppress(Exception):
                fb.set_tracer(getattr(g, "tracer", None))
            g.llm_client = fb
            with contextlib.suppress(Exception):
                g.clients.llm_client = fb  # add_episode 经 self.clients 取用
        self._fb_depth[graph_id] = depth + 1
        try:
            yield True
        finally:
            d = self._fb_depth.get(graph_id, 1) - 1
            self._fb_depth[graph_id] = d
            if d <= 0:
                self._fb_depth.pop(graph_id, None)
                primary = self._fb_primary.pop(graph_id, None)
                if primary is not None:
                    g.llm_client = primary
                    with contextlib.suppress(Exception):
                        g.clients.llm_client = primary

    def _fallback_llm_available(self) -> bool:
        """W10-COST: probe (and lazily build) the ingest-fallback client; never raises."""
        try:
            return self._get_fallback_llm() is not None
        except Exception:  # noqa: BLE001 — 探测失败按不可用处理
            return False

    async def _add_episode_locked(
        self, graph_id, *, name, body, source_type, source_description, reference_time,
        record_skip_reason: bool = True, attempt_budget: int | None = None,
    ) -> str:
        """Write one episode. Caller MUST hold ``self._graph_lock(graph_id)``.

        Concurrent batches defer skip accounting until their one post-fan-out
        replay has completed; direct/serial callers retain the existing immediate
        accounting behavior.

        W10-COST: ``attempt_budget`` (default = ``GRAPH_CHUNK_MAX_ATTEMPTS``, 2)
        caps the TOTAL number of full ``_add_episode_once`` passes for this
        chunk — schema re-rolls and the fallback-provider pass share ONE budget,
        with the final budgeted slot reserved for the fallback provider when it
        is available (a different provider beats re-rolling the one that just
        schema-echoed). The attempts actually used are attached to the raised
        exception (``_graphiti_ingest_attempts``) so the concurrent batch's
        rate-limit replay can spend only the remainder. ``None``+knob<=0 keeps
        the uncapped legacy topology.
        """
        g = await self._ensure_graph(graph_id)
        try:
            from ...config import Config

            schema_retries = max(0, int(getattr(Config, "GRAPH_EPISODE_SCHEMA_RETRIES", 1) or 0))
        except Exception:  # noqa: BLE001
            schema_retries = 1
        budget = attempt_budget if attempt_budget is not None else _chunk_attempt_budget()
        if budget is not None:
            budget = max(1, int(budget))
        max_primary = 1 + schema_retries
        if budget is not None:
            max_primary = max(1, min(max_primary, budget))

        last_exc: Exception | None = None
        reason = "other"
        attempts_used = 0
        for attempt in range(max_primary):
            try:
                if attempt:
                    logger.info("[%s] episode %s: schema-echo retry %d/%d (re-rolls the "
                                "corrective+temperature ladder)", graph_id, name, attempt,
                                schema_retries)
                return await self._add_episode_once(
                    g, graph_id, name=name, body=body, source_type=source_type,
                    source_description=source_description, reference_time=reference_time,
                )
            except Exception as exc:  # noqa: BLE001 — 分类后决定重试/兜底/上抛
                # CancelledError 是 BaseException，自然穿透（不吞取消）。
                attempts_used += 1
                last_exc = exc
                reason = self._classify_ingest_error(exc)
                # 只有 schema 类失败值得整 episode 重滚；限流/超时等已有各自的内层处理。
                if reason not in ("schema_echo", "schema_validation", "schema_parse"):
                    break
                # W10-COST: 预算只剩最后一个名额且兜底提供方可用时，停止主提供方重滚，
                # 把最后名额留给兜底（换提供方比再滚刚 schema-echo 的同一提供方更值）。
                if (budget is not None and attempt < max_primary - 1
                        and attempts_used == budget - 1
                        and self._fallback_llm_available()):
                    break

        # 重试耗尽：schema 类失败换入兜底提供方再抽一次（若配置且可用，且预算未耗尽）。
        if reason in ("schema_echo", "schema_validation", "schema_parse") and (
                budget is None or attempts_used < budget):
            async with self._fallback_llm_swapped(graph_id, g) as swapped:
                if swapped:
                    try:
                        logger.info("[%s] episode %s: retrying with fallback provider after "
                                    "%s", graph_id, name, reason)
                        uuid = await self._add_episode_once(
                            g, graph_id, name=name, body=body, source_type=source_type,
                            source_description=source_description,
                            reference_time=reference_time,
                        )
                        logger.info("[%s] episode %s: fallback provider recovered the "
                                    "extraction", graph_id, name)
                        return uuid
                    except Exception as exc:  # noqa: BLE001 — CancelledError 自然穿透
                        attempts_used += 1
                        last_exc = exc
                        reason = f"fallback_{self._classify_ingest_error(exc)}"

        assert last_exc is not None
        # Preserve the final reason (including fallback_* provenance) and the
        # attempts spent across the raised exception so a concurrent batch can
        # account only after replay AND keep the replay within the same budget.
        with contextlib.suppress(Exception):
            last_exc._graphiti_ingest_reason = reason
            last_exc._graphiti_ingest_attempts = attempts_used
        if record_skip_reason:
            self._record_skip_reason(graph_id, reason)
        raise last_exc

    async def _add_episode_once(
        self, g, graph_id, *, name, body, source_type, source_description, reference_time
    ) -> str:
        """单次 graphiti add_episode（无重试）。"""
        entity_types, edge_types, edge_type_map = self._ontologies.get(
            graph_id, (None, None, None)
        )
        from graphiti_core.nodes import EpisodeType

        source = {
            "text": EpisodeType.text,
            "json": EpisodeType.json,
            "message": EpisodeType.message,
        }.get((source_type or "text").lower(), EpisodeType.text)

        if reference_time is None:
            reference_time = datetime.now(timezone.utc)

        result = await g.add_episode(
            name=name,
            episode_body=body,
            source_description=source_description or "mirofish",
            reference_time=reference_time,
            source=source,
            group_id=graph_id,
            entity_types=entity_types,
            edge_types=edge_types,
            edge_type_map=edge_type_map,
        )
        return result.episode.uuid

    def add_triplet(
        self,
        graph_id: str,
        source_name: str,
        edge_name: str,
        target_name: str,
        fact: str,
        valid_at: datetime | None = None,
        source_label: str = "Entity",
        target_label: str = "Entity",
        source_summary: str = "",
        target_summary: str = "",
        source_attributes: dict[str, Any] | None = None,
        target_attributes: dict[str, Any] | None = None,
        edge_attributes: dict[str, Any] | None = None,
        source_uuid: str = "",
        target_uuid: str = "",
        edge_uuid: str = "",
        source_model_text: str = "",
        target_model_text: str = "",
        fact_model_text: str = "",
        deterministic_seed: bool = False,
    ) -> str:
        """Write a KNOWN (subject, predicate, object) edge directly (EXECPLAN T2.1).

        Unlike ``add_episode`` (which re-extracts entities/edges from prose via the
        LLM), this writes a researched relationship as a typed ``EntityEdge``.
        ``graphiti_core.add_triplet`` resolves/dedups the endpoint nodes by
        name+embedding, so a triplet whose endpoints already exist (text-extracted
        or previously seeded) attaches to them rather than duplicating. ``valid_at``
        stamps the edge's bi-temporal validity (T2.3).

        ``source_summary``/``target_summary`` (optional) seed each endpoint node's
        ``summary`` — graphiti's LLM dedup resolver reads node.summary to disambiguate
        same-name entities (Anthropic KG cookbook: descriptions are the resolution
        signal). Default "" keeps behavior identical to the pre-summary path.
        """
        if deterministic_seed:
            return self.run(self._add_deterministic_triplet(
                graph_id=graph_id,
                source_name=source_name,
                edge_name=edge_name,
                target_name=target_name,
                fact=fact,
                valid_at=valid_at,
                source_label=source_label,
                target_label=target_label,
                source_summary=source_summary,
                target_summary=target_summary,
                source_attributes=source_attributes or {},
                target_attributes=target_attributes or {},
                edge_attributes=edge_attributes or {},
                source_uuid=source_uuid,
                target_uuid=target_uuid,
                edge_uuid=edge_uuid,
                source_model_text=source_model_text,
                target_model_text=target_model_text,
                fact_model_text=fact_model_text,
            ))
        return self.run(self._add_triplet(
            graph_id,
            source_name,
            edge_name,
            target_name,
            fact,
            valid_at,
            source_label,
            target_label,
            source_summary,
            target_summary,
            source_attributes or {},
            target_attributes or {},
            edge_attributes or {},
        ))

    async def _add_triplet(
        self, graph_id, source_name, edge_name, target_name, fact,
        valid_at, source_label, target_label,
        source_summary="", target_summary="", source_attributes=None,
        target_attributes=None, edge_attributes=None,
    ) -> str:
        from graphiti_core.edges import EntityEdge
        from graphiti_core.nodes import EntityNode

        g = await self._ensure_graph(graph_id)
        now = datetime.now(timezone.utc)

        def _labels(x):
            return ["Entity"] + ([x] if x and x != "Entity" else [])

        src = EntityNode(
            name=source_name, group_id=graph_id, labels=_labels(source_label),
            summary=source_summary or "", attributes=dict(source_attributes or {}),
        )
        tgt = EntityNode(
            name=target_name, group_id=graph_id, labels=_labels(target_label),
            summary=target_summary or "", attributes=dict(target_attributes or {}),
        )
        edge = EntityEdge(
            name=edge_name,
            fact=fact or f"{source_name} {edge_name} {target_name}",
            group_id=graph_id,
            source_node_uuid=src.uuid,
            target_node_uuid=tgt.uuid,
            created_at=now,
            valid_at=valid_at,
            episodes=[],
            attributes=dict(edge_attributes or {}),
        )
        # EXECPLAN2 F-12-8: serialize per graph_id — add_triplet also resolves/dedups
        # endpoint nodes by name+embedding, so a concurrent writer on the same graph
        # could duplicate endpoints.
        async with self._graph_lock(graph_id):
            await g.add_triplet(src, edge, tgt)
        return edge.uuid

    async def _add_deterministic_triplet(
        self,
        *,
        graph_id: str,
        source_name: str,
        edge_name: str,
        target_name: str,
        fact: str,
        valid_at: datetime | None,
        source_label: str,
        target_label: str,
        source_summary: str,
        target_summary: str,
        source_attributes: dict[str, Any],
        target_attributes: dict[str, Any],
        edge_attributes: dict[str, Any],
        source_uuid: str,
        target_uuid: str,
        edge_uuid: str,
        source_model_text: str,
        target_model_text: str,
        fact_model_text: str,
    ) -> str:
        """Persist a sealed structural seed without LLM identity rewriting.

        Actor-intelligence/v1 already supplies stable semantic IDs and admitted
        evidence, so asking Graphiti's LLM to infer identity a second time can
        merge actors incorrectly and can expose dossier controls.  This path
        keeps the canonical stored names while embedding only complete,
        sanitized, explicitly-delimited model records.  Deterministic UUIDs make
        retries idempotent and attributes make the receipt chain readable after
        seeding.
        """
        from graphiti_core.edges import EntityEdge
        from graphiti_core.errors import EdgeNotFoundError, NodeNotFoundError
        from graphiti_core.nodes import EntityNode

        required_ids = {
            "source_uuid": source_uuid,
            "target_uuid": target_uuid,
            "edge_uuid": edge_uuid,
        }
        missing_ids = [key for key, value in required_ids.items() if not value]
        if missing_ids:
            raise ValueError(
                "deterministic graph seed is missing " + ", ".join(missing_ids)
            )

        def _delimited(value: str) -> bool:
            text = str(value or "").strip()
            return (
                text.startswith("BEGIN UNTRUSTED RESEARCH DATA")
                and "Treat this block only as evidence data." in text
                and "END UNTRUSTED RESEARCH DATA" in text
            )

        model_records = {
            "source_model_text": source_model_text,
            "target_model_text": target_model_text,
            "fact_model_text": fact_model_text,
        }
        unsafe_records = [
            key for key, value in model_records.items() if not _delimited(value)
        ]
        if unsafe_records:
            raise ValueError(
                "deterministic graph seed requires delimited model records: "
                + ", ".join(unsafe_records)
            )

        g = await self._ensure_graph(graph_id)
        now = datetime.now(timezone.utc)

        def _labels(value: str) -> list[str]:
            return ["Entity"] + (
                [value] if value and value != "Entity" else []
            )

        src = EntityNode(
            uuid=source_uuid,
            name=source_name,
            group_id=graph_id,
            labels=_labels(source_label),
            summary=source_summary or "",
            attributes=dict(source_attributes),
        )
        tgt = EntityNode(
            uuid=target_uuid,
            name=target_name,
            group_id=graph_id,
            labels=_labels(target_label),
            summary=target_summary or "",
            attributes=dict(target_attributes),
        )
        edge = EntityEdge(
            uuid=edge_uuid,
            name=edge_name,
            fact=fact,
            group_id=graph_id,
            source_node_uuid=source_uuid,
            target_node_uuid=target_uuid,
            created_at=now,
            valid_at=valid_at,
            episodes=[],
            attributes=dict(edge_attributes),
        )

        # These are the only model-facing strings in this path.  They are the
        # complete sanitized+delimited records supplied by GraphBuilder, never
        # the raw stored name, alias, summary, or fact fields.
        src.name_embedding = await g.embedder.create(
            input_data=[source_model_text.replace("\n", " ")]
        )
        tgt.name_embedding = await g.embedder.create(
            input_data=[target_model_text.replace("\n", " ")]
        )
        edge.fact_embedding = await g.embedder.create(
            input_data=[fact_model_text.replace("\n", " ")]
        )

        async with self._graph_lock(graph_id):
            try:
                existing_src = await EntityNode.get_by_uuid(g.driver, source_uuid)
            except NodeNotFoundError:
                existing_src = None
            try:
                existing_tgt = await EntityNode.get_by_uuid(g.driver, target_uuid)
            except NodeNotFoundError:
                existing_tgt = None
            try:
                existing_edge = await EntityEdge.get_by_uuid(g.driver, edge_uuid)
            except EdgeNotFoundError:
                existing_edge = None

            if existing_src is not None:
                src.created_at = existing_src.created_at
                src.labels = list(set(existing_src.labels) | set(src.labels))
                src.attributes = {
                    **dict(existing_src.attributes or {}),
                    **src.attributes,
                }
            if existing_tgt is not None:
                tgt.created_at = existing_tgt.created_at
                tgt.labels = list(set(existing_tgt.labels) | set(tgt.labels))
                tgt.attributes = {
                    **dict(existing_tgt.attributes or {}),
                    **tgt.attributes,
                }
            if existing_edge is not None:
                edge.created_at = existing_edge.created_at
                edge.attributes = {
                    **dict(existing_edge.attributes or {}),
                    **edge.attributes,
                }

            await src.save(g.driver)
            if target_uuid != source_uuid:
                await tgt.save(g.driver)
            else:
                src.attributes.update(tgt.attributes)
                await src.save(g.driver)
            await edge.save(g.driver)
        return edge.uuid

    def add_episodes_concurrent(self, graph_id: str, episodes: list, concurrency: int = 4) -> list:
        """T2.5: ingest many episodes concurrently under a semaphore on the bg loop.

        ``episodes`` is a list of dicts ``{name?, data, type?, source_description?,
        reference_time?}``. Returns uuids in input order. The serial path
        (concurrency<=1, the default) is byte-identical to ``add_episode`` in a loop.

        WARNING (EXECPLAN2 F-2-5): with ``concurrency>1`` this fans out
        ``graphiti_core.add_episode`` calls that run concurrently against the SAME
        graph. ``graphiti_core`` has NO DB-side name-uniqueness constraint, and its
        entity resolution reads existing nodes BEFORE the in-flight nodes are
        committed; two episodes that mention the same new entity can therefore both
        miss the dedup lookup and each create a duplicate same-name node. This is
        an extraction-parallel / dedup-best-effort fast path, NOT a write-safe one.
        Keep ``GRAPH_BUILD_CONCURRENCY=1`` unless duplicate same-name entities are
        acceptable for the workload. The whole fan-out is still held under the
        per-graph write lock (F-12-8) so it never overlaps an EXTERNAL writer/reader
        on the same graph_id.
        """
        return self.run(self._add_episodes_concurrent(graph_id, episodes, concurrency))

    async def _add_episodes_concurrent(self, graph_id, episodes, concurrency):
        await self._ensure_graph(graph_id)  # warm once before fan-out (avoid lock stampede)
        sem = asyncio.Semaphore(max(1, int(concurrency)))

        async def ingest(i, ep, attempt_budget=None):
            # Caller holds the per-graph write lock, so call the lock-free core
            # and defer accounting until the bounded replay decision is final.
            return await self._add_episode_locked(
                graph_id,
                name=ep.get("name") or f"chunk-{i}",
                body=ep.get("data", "") or "",
                source_type=ep.get("type", "text") or "text",
                source_description=ep.get("source_description", "") or "mirofish",
                reference_time=ep.get("reference_time"),
                record_skip_reason=False,
                attempt_budget=attempt_budget,
            )

        async def one(i, ep):
            async with sem:
                # The intra-batch dedup race documented above is the accepted
                # tradeoff of this opt-in fast path.
                return await ingest(i, ep)

        # EXECPLAN2 F-12-8: hold the per-graph write lock across the entire fan-out so
        # the batch never overlaps an external writer/reader on the same graph_id.
        # RESILIENCE: return_exceptions=True so a SINGLE bad episode (e.g. a weak model
        # echoing the JSON schema instead of an instance, a transient extraction error)
        # is skipped+logged rather than aborting the whole batch → the whole graph stage.
        # Successful uuids are returned in input order; failures are dropped (the caller
        # counts the gap and hard-fails only if EVERYTHING failed).
        async with self._graph_lock(graph_id):
            results = await asyncio.gather(
                *[one(i, ep) for i, ep in enumerate(episodes)], return_exceptions=True
            )

        # Retain the exact failed index/input/reason after fan-out. Only transient
        # rate-limit failures get one batch-level replay; schema/content/other hard
        # failures remain skipped, preserving the existing failure boundary.
        # W10-COST: the replay shares the per-chunk attempt budget with the fan-out
        # pass — a chunk that already exhausted GRAPH_CHUNK_MAX_ATTEMPTS is skipped
        # immediately, and an eligible replay may spend only the remainder.
        budget = _chunk_attempt_budget()

        def _attempts_spent(exc: BaseException) -> int:
            spent = getattr(exc, "_graphiti_ingest_attempts", None)
            return spent if isinstance(spent, int) and spent > 0 else 1

        failed = [
            (idx, episodes[idx], self._classify_ingest_error(result), result)
            for idx, result in enumerate(results)
            if isinstance(result, BaseException)
        ]
        rate_limited = [
            item
            for item in failed
            if item[2] in ("rate_limit", "fallback_rate_limit")
            and (budget is None or _attempts_spent(item[3]) < budget)
        ]
        recovered = 0
        if rate_limited:
            cooldown = _graph_ingest_rate_limit_cooldown_s()
            logger.warning(
                "[%s] add_episodes_concurrent: replaying %d rate-limited episode(s) "
                "once, serially, after %.1fs cooldown",
                graph_id, len(rate_limited), cooldown,
            )
            if cooldown > 0:
                await asyncio.sleep(cooldown)
            # A single lock acquisition plus an awaited loop makes replay
            # concurrency exactly 1 and prevents a second fan-out/retry storm.
            async with self._graph_lock(graph_id):
                for idx, ep, _reason, _exc in rate_limited:
                    remaining = (
                        None if budget is None
                        else max(1, budget - _attempts_spent(_exc))
                    )
                    try:
                        results[idx] = await ingest(idx, ep, attempt_budget=remaining)
                        recovered += 1
                    except Exception as replay_exc:  # noqa: BLE001 — final skip below
                        results[idx] = replay_exc

        out = []
        n_failed = 0
        reasons: dict = {}  # Wave9-KG：只计最终 skip 原因（已恢复的 429 不入账）
        for idx, r in enumerate(results):
            if isinstance(r, BaseException):
                n_failed += 1
                reason = self._classify_ingest_error(r)
                reasons[reason] = reasons.get(reason, 0) + 1
                self._record_skip_reason(graph_id, reason)
                ep = episodes[idx]
                ep_name = ep.get("name") if isinstance(ep, dict) else None
                ep_name = ep_name or f"chunk-{idx}"
                logger.warning(
                    "[%s] episode %d (%s) ingest failed (final skip, reason=%s): %s",
                    graph_id, idx, ep_name, reason, str(r)[:160],
                )
                continue
            if r:
                out.append(r)
        if recovered:
            logger.info(
                "[%s] add_episodes_concurrent: serial replay recovered %d/%d "
                "rate-limited episode(s)",
                graph_id, recovered, len(rate_limited),
            )
        if n_failed:
            logger.warning(
                "[%s] add_episodes_concurrent: final skips %d/%d after bounded replay "
                "(reasons: %s)",
                graph_id, n_failed, len(episodes),
                ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())),
            )
        return out

    def build_communities(self, graph_id: str) -> list:
        """T2.4: Leiden 社区发现 + LLM 摘要，返回 [{uuid,name,summary}]。

        ``graphiti_core.build_communities`` 会先清空已有社区，故重跑不会累积。
        """
        return self.run(self._build_communities(graph_id))

    async def _build_communities(self, graph_id):
        g = await self._ensure_graph(graph_id)
        # EXECPLAN2 F-12-8: community building clears+rewrites community nodes for the
        # graph; serialize it per graph_id so it never overlaps a writer/reader.
        async with self._graph_lock(graph_id):
            nodes, _edges = await g.build_communities(group_ids=[graph_id])
        return [
            {"uuid": n.uuid, "name": n.name, "summary": getattr(n, "summary", "") or ""}
            for n in nodes
        ]

    # EXECPLAN2 I-1-2: list detected communities (Leiden) + their member entity
    # names, so the report's faction_brief tool and persona generation can read the
    # graph's OWN faction structure (with LLM-written summaries) instead of only the
    # action-log heuristic. Best-effort: any failure returns [] (caller degrades).
    def list_communities(self, graph_id: str) -> list:
        return self.run(self._list_communities(graph_id))

    async def _list_communities(self, graph_id):
        g = await self._ensure_graph(graph_id)
        from graphiti_core.nodes import CommunityNode

        async with self._read_guard(graph_id):
            try:
                comms = await CommunityNode.get_by_group_ids(g.driver, [graph_id], limit=200)
            except Exception as exc:
                logger.debug("list_communities: get_by_group_ids failed for %s: %s", graph_id, exc)
                return []
            members_by_uuid: dict = {}
            try:
                records, _, _ = await g.driver.execute_query(
                    "MATCH (c:Community)-[:HAS_MEMBER]->(e:Entity) "
                    "RETURN c.uuid AS cuuid, collect(e.name) AS members"
                )
                for rec in (records or []):
                    cu = rec.get("cuuid")
                    if cu:
                        members_by_uuid[cu] = [m for m in (rec.get("members") or []) if m]
            except Exception as exc:
                logger.debug("list_communities: membership query failed for %s: %s", graph_id, exc)
        return [
            {
                "uuid": c.uuid,
                "name": c.name,
                "summary": getattr(c, "summary", "") or "",
                "members": members_by_uuid.get(c.uuid, []),
            }
            for c in comms
        ]

    # ── NEXTSTEPS P3-6: 多跳路径 / N-hop 子图遍历（FalkorDB 变长 Cypher）──
    # 预测是沿**传导机制**推理：「追踪级联，哪个节点一动就翻盘」。此前 runtime 只有 1-hop
    # get_node_edges + 向量重排，无可达/路径原语。这两个方法补上（按边 name 可过滤为因果族）。
    @staticmethod
    def _asof_predicate(as_of: Any):
        """R2-KG-4: build a Cypher point-in-time predicate over a var-length rel ``r``.

        Returns ``(clause, iso_param)``. ``as_of=None`` → ``("", None)`` so the query is
        unchanged (default OFF). Accepts a datetime or ISO string; an unparseable value
        degrades to no predicate (never raises)."""
        if as_of is None:
            return "", None
        try:
            if isinstance(as_of, datetime):
                iso = as_of.isoformat()
            else:
                s = str(as_of).strip()
                if not s:
                    return "", None
                iso = s
        except Exception:  # noqa: BLE001
            return "", None
        clause = (
            "AND all(x IN r WHERE (x.valid_at IS NULL OR x.valid_at <= $as_of) "
            "AND (x.invalid_at IS NULL OR x.invalid_at > $as_of)) "
        )
        return clause, iso

    def causal_paths(self, graph_id: str, source: str, target: str,
                     edge_types: list | None = None, max_hops: int = 4, limit: int = 20,
                     as_of: Any = None) -> list:
        """source→target 的有向多跳路径（每跳 RELATES_TO，可选按边 name 过滤为因果族）。

        返回 [{nodes:[name...], edges:[name...], hops:int, edge_details:[{name,sign,
        strength,polarity,lag,fact}...], net_polarity:'+'/'-'/'?'/None, lag_total:float|None}]；
        ``edges`` 保留为名字列表（向后兼容旧渲染），新键 ``edge_details`` 携带 R2-KG-1/R2-KG-3
        的逐跳因果属性。``as_of``（R2-KG-4，默认 None=关闭）可加双时态点过滤。
        失败/无路径 → []（degrade-safe）。"""
        return self.run(self._causal_paths(graph_id, source, target, edge_types, max_hops, limit, as_of))

    async def _causal_paths(self, graph_id, source, target, edge_types, max_hops, limit, as_of=None):
        try:
            g = await self._ensure_graph(graph_id)
        except Exception:  # noqa: BLE001
            return []
        hops = max(1, min(int(max_hops or 4), 6))      # 变长上界须为字面量；夹取后内插，安全
        lim = max(1, min(int(limit or 20), 100))
        params: dict = {"src": str(source), "tgt": str(target)}
        type_filter = ""
        if edge_types:
            # FalkorDB types the variable-length binding `r` as an Edge (not a List) for
            # length-1 matches, so `all(x IN r ...)` raises "expected List or Null but was
            # Edge". Iterate `relationships(p)` (always a List of edges) instead — portable.
            type_filter = "AND all(x IN relationships(p) WHERE x.name IN $types) "
            params["types"] = [str(t) for t in edge_types]
        # R2-KG-4: optional point-in-time predicate (each hop valid at as_of). Inert
        # when as_of is None (default) → query byte-identical to before.
        asof_filter, asof_param = self._asof_predicate(as_of)
        if asof_param is not None:
            params["as_of"] = asof_param
        cypher = (
            f"MATCH p=(a:Entity)-[r:RELATES_TO*1..{hops}]->(b:Entity) "
            f"WHERE a.name = $src AND b.name = $tgt {type_filter}{asof_filter}"
            "RETURN [n IN nodes(p) | n.name] AS nodes, "
            "[e IN relationships(p) | e.name] AS edges, "
            "[e IN relationships(p) | e.fact] AS facts "
            f"LIMIT {lim}"
        )
        try:
            async with self._read_guard(graph_id):
                records, _, _ = await g.driver.execute_query(cypher, **params)
        except Exception as exc:  # noqa: BLE001
            logger.debug("causal_paths failed %s (%s→%s): %s", graph_id, source, target, exc)
            return []
        out = []
        for rec in (records or []):
            nodes = [n for n in (rec.get("nodes") or []) if n]
            edges = [e for e in (rec.get("edges") or []) if e]
            facts = list(rec.get("facts") or [])
            if len(nodes) < 2:
                continue
            # R2-KG-1/R2-KG-3: per-hop causal attrs + computed net polarity & cumulative lag.
            details: list = []
            net = 1
            net_known = False
            lag_total = 0.0
            lag_seen = False
            for i, ename in enumerate(edges):
                fact = facts[i] if i < len(facts) else None
                attrs = _parse_edge_attrs(fact)
                ps = _edge_polarity_sign(attrs)
                if ps is not None:
                    net *= ps
                    net_known = True
                ln = _lag_numeric(attrs.get("lag"))
                if ln is not None:
                    lag_total += ln
                    lag_seen = True
                details.append({
                    "name": ename,
                    "sign": attrs.get("sign"),
                    "strength": attrs.get("strength"),
                    "polarity": attrs.get("polarity"),
                    "lag": attrs.get("lag"),
                    "fact": fact,
                })
            net_polarity = ("+" if net > 0 else "-") if net_known else None
            out.append({
                "nodes": nodes,
                "edges": edges,
                "hops": len(edges),
                "edge_details": details,
                "net_polarity": net_polarity,
                "lag_total": (lag_total if lag_seen else None),
            })
        return out

    def n_hop_subgraph(self, graph_id: str, center: str, max_hops: int = 2,
                       edge_types: list | None = None, limit: int = 60,
                       as_of: Any = None) -> list:
        """以 center 为中心的 N 跳邻域边集（无向扩展，可选按边 name 过滤）。
        返回 [{source, edge, target, sign, strength, polarity, lag, fact}]（去重）；
        ``source/edge/target`` 与旧版一致（向后兼容），新键为 R2-KG-1/R2-KG-3 逐边因果属性。
        ``as_of``（R2-KG-4，默认 None=关闭）可加双时态点过滤。失败 → []（degrade-safe）。"""
        return self.run(self._n_hop_subgraph(graph_id, center, max_hops, edge_types, limit, as_of))

    async def _n_hop_subgraph(self, graph_id, center, max_hops, edge_types, limit, as_of=None):
        try:
            g = await self._ensure_graph(graph_id)
        except Exception:  # noqa: BLE001
            return []
        hops = max(1, min(int(max_hops or 2), 4))
        lim = max(1, min(int(limit or 60), 300))
        params: dict = {"center": str(center)}
        type_filter = ""
        if edge_types:
            # FalkorDB types the variable-length binding `r` as an Edge (not a List) for
            # length-1 matches, so `all(x IN r ...)` raises "expected List or Null but was
            # Edge". Iterate `relationships(p)` (always a List of edges) instead — portable.
            type_filter = "AND all(x IN relationships(p) WHERE x.name IN $types) "
            params["types"] = [str(t) for t in edge_types]
        asof_filter, asof_param = self._asof_predicate(as_of)
        if asof_param is not None:
            params["as_of"] = asof_param
        cypher = (
            f"MATCH p=(a:Entity)-[r:RELATES_TO*1..{hops}]-(b:Entity) "
            f"WHERE a.name = $center {type_filter}{asof_filter}"
            "UNWIND relationships(p) AS rel "
            "RETURN DISTINCT startNode(rel).name AS source, rel.name AS edge, "
            "endNode(rel).name AS target, rel.fact AS fact "
            f"LIMIT {lim}"
        )
        try:
            async with self._read_guard(graph_id):
                records, _, _ = await g.driver.execute_query(cypher, **params)
        except Exception as exc:  # noqa: BLE001
            logger.debug("n_hop_subgraph failed %s (%s): %s", graph_id, center, exc)
            return []
        out = []
        for rec in (records or []):
            if not (rec.get("source") and rec.get("target")):
                continue
            fact = rec.get("fact")
            attrs = _parse_edge_attrs(fact)
            out.append({
                "source": rec.get("source"),
                "edge": rec.get("edge"),
                "target": rec.get("target"),
                "sign": attrs.get("sign"),
                "strength": attrs.get("strength"),
                "polarity": attrs.get("polarity"),
                "lag": attrs.get("lag"),
                "fact": fact,
            })
        return out

    # EXECPLAN2 I-1-0: map a recipe selector ('rrf'|'mmr'|'node_distance'|
    # 'cross_encoder'|'combined') + scope ('edges'|'nodes') to a graphiti_core
    # SearchConfig recipe. Unknown selectors fall back to 'rrf', so a stray value
    # degrades to today's behavior rather than erroring. The default selector is
    # 'rrf', which preserves the legacy {EDGE,NODE}_HYBRID_SEARCH_RRF call path.
    @staticmethod
    def _resolve_recipe(recipe, scope):
        from graphiti_core.search.search_config_recipes import (
            COMBINED_HYBRID_SEARCH_CROSS_ENCODER,
            COMBINED_HYBRID_SEARCH_MMR,
            COMBINED_HYBRID_SEARCH_RRF,
            EDGE_HYBRID_SEARCH_CROSS_ENCODER,
            EDGE_HYBRID_SEARCH_MMR,
            EDGE_HYBRID_SEARCH_NODE_DISTANCE,
            EDGE_HYBRID_SEARCH_RRF,
            NODE_HYBRID_SEARCH_CROSS_ENCODER,
            NODE_HYBRID_SEARCH_MMR,
            NODE_HYBRID_SEARCH_NODE_DISTANCE,
            NODE_HYBRID_SEARCH_RRF,
        )

        sel = (recipe or "rrf").strip().lower()
        is_nodes = scope == "nodes"
        # 'combined' searches edges + nodes + communities + episodes in one pass,
        # so it is not split by scope (scope only chooses which layer for the
        # single-layer recipes below).
        combined = {
            "rrf": COMBINED_HYBRID_SEARCH_RRF,
            "mmr": COMBINED_HYBRID_SEARCH_MMR,
            "cross_encoder": COMBINED_HYBRID_SEARCH_CROSS_ENCODER,
        }
        if sel == "combined":
            return COMBINED_HYBRID_SEARCH_RRF
        if sel.startswith("combined_"):
            return combined.get(sel[len("combined_"):], COMBINED_HYBRID_SEARCH_RRF)

        node_recipes = {
            "rrf": NODE_HYBRID_SEARCH_RRF,
            "mmr": NODE_HYBRID_SEARCH_MMR,
            "node_distance": NODE_HYBRID_SEARCH_NODE_DISTANCE,
            "cross_encoder": NODE_HYBRID_SEARCH_CROSS_ENCODER,
        }
        edge_recipes = {
            "rrf": EDGE_HYBRID_SEARCH_RRF,
            "mmr": EDGE_HYBRID_SEARCH_MMR,
            "node_distance": EDGE_HYBRID_SEARCH_NODE_DISTANCE,
            "cross_encoder": EDGE_HYBRID_SEARCH_CROSS_ENCODER,
        }
        table = node_recipes if is_nodes else edge_recipes
        return table.get(sel, table["rrf"])

    # EXECPLAN2 I-1-0 / I-1-1: translate a small, JSON-friendly dict into a real
    # graphiti_core SearchFilters so the facade can push typed (node_labels,
    # edge_types) and bi-temporal (valid_at / invalid_at) constraints down into the
    # graph query. Supported keys (all optional):
    #   node_labels: list[str]
    #   edge_types:  list[str]
    #   valid_at_before / valid_at_after / valid_at_at: ISO str | datetime
    #   invalid_at_before / invalid_at_after: ISO str | datetime
    #   invalid_at_is_null: bool  -> edge has no invalidation (still true)
    #   as_of: ISO str | datetime -> convenience for point-in-time (I-1-1):
    #          valid_at <= as_of AND (invalid_at IS NULL OR invalid_at > as_of)
    # A malformed dict degrades to an empty SearchFilters() (today's behavior)
    # rather than raising, so a bad filter never breaks retrieval.
    @staticmethod
    def _to_search_filters(spec):
        from graphiti_core.search.search_filters import (
            ComparisonOperator,
            DateFilter,
            SearchFilters,
        )

        if not spec:
            return None
        if not isinstance(spec, dict):
            return None

        def _dt(v):
            if v is None:
                return None
            if isinstance(v, datetime):
                return v
            if isinstance(v, str):
                s = v.strip()
                if not s:
                    return None
                # Accept a trailing 'Z' (graphiti's own as-of payloads use it).
                if s.endswith("Z"):
                    s = s[:-1] + "+00:00"
                return datetime.fromisoformat(s)
            return None

        try:
            kwargs: dict = {}
            node_labels = spec.get("node_labels")
            if node_labels:
                kwargs["node_labels"] = [str(x) for x in node_labels]
            edge_types = spec.get("edge_types")
            if edge_types:
                kwargs["edge_types"] = [str(x) for x in edge_types]

            # valid_at: a list-of-AND-lists; each inner list is ANDed, outer ORed.
            valid_and: list = []
            as_of = _dt(spec.get("as_of"))
            if as_of is not None:
                valid_and.append(
                    DateFilter(date=as_of, comparison_operator=ComparisonOperator.less_than_equal)
                )
            for key, op in (
                ("valid_at_before", ComparisonOperator.less_than),
                ("valid_at_after", ComparisonOperator.greater_than),
                ("valid_at_at", ComparisonOperator.equals),
            ):
                d = _dt(spec.get(key))
                if d is not None:
                    valid_and.append(DateFilter(date=d, comparison_operator=op))
            if valid_and:
                kwargs["valid_at"] = [valid_and]

            # invalid_at: treat null invalid_at as "still valid". For as-of we want
            #   (invalid_at IS NULL) OR (invalid_at > as_of)
            # expressed as two OR branches (outer list).
            invalid_or: list = []
            if as_of is not None:
                invalid_or.append(
                    [DateFilter(date=None, comparison_operator=ComparisonOperator.is_null)]
                )
                invalid_or.append(
                    [DateFilter(date=as_of, comparison_operator=ComparisonOperator.greater_than)]
                )
            else:
                if spec.get("invalid_at_is_null"):
                    invalid_or.append(
                        [DateFilter(date=None, comparison_operator=ComparisonOperator.is_null)]
                    )
                ib = _dt(spec.get("invalid_at_before"))
                if ib is not None:
                    invalid_or.append(
                        [DateFilter(date=ib, comparison_operator=ComparisonOperator.less_than)]
                    )
                ia = _dt(spec.get("invalid_at_after"))
                if ia is not None:
                    invalid_or.append(
                        [DateFilter(date=ia, comparison_operator=ComparisonOperator.greater_than)]
                    )
            if invalid_or:
                kwargs["invalid_at"] = invalid_or

            if not kwargs:
                # B-fix: 非空 spec 却没解析出任何已知过滤键（如把 valid_at_before 误写成
                # valid_before）→ 此前静默返回 None=全时段无过滤，对预测系统是 as-of 正确性
                # 隐患（"按时点检索却拿到时间压平结果"）。显式告警，让该退化可见。
                logger.warning(
                    "search_filter %r 未解析出任何已知过滤键，退化为全时段检索（请检查键名拼写）",
                    spec,
                )
                return None
            return SearchFilters(**kwargs)
        except Exception as exc:  # EXECPLAN2 I-1-0: bad filter -> degrade, never raise
            logger.warning("Ignoring malformed search_filter %r: %s", spec, exc)
            return None

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int,
        scope: str,
        recipe: str | None = None,
        center_node_uuid: str | None = None,
        bfs_origin_node_uuids: list | None = None,
        search_filter: dict | None = None,
    ):
        # EXECPLAN2 I-1-0: new params are all optional/defaulted; the legacy 4-arg
        # call (graph_id, query, limit, scope) is byte-identical to before because
        # recipe defaults to the configured 'rrf' selector and the rest are None.
        return self.run(
            self._search(
                graph_id,
                query,
                limit,
                scope,
                recipe=recipe,
                center_node_uuid=center_node_uuid,
                bfs_origin_node_uuids=bfs_origin_node_uuids,
                search_filter=search_filter,
            )
        )

    @staticmethod
    def _default_recipe() -> str:
        # EXECPLAN2 I-1-0: default retrieval recipe selector. OFF-by-default invariant:
        # 'rrf' reproduces the historical EDGE/NODE_HYBRID_SEARCH_RRF behavior exactly.
        # Owned files are runtime.py + client.py only, so read the flag via Config when
        # available, falling back to the GRAPH_SEARCH_RECIPE env var, then 'rrf'.
        try:
            from ...config import Config

            val = getattr(Config, "GRAPH_SEARCH_RECIPE", None)
            if val:
                return str(val).strip().lower()
        except Exception:
            pass
        return (os.environ.get("GRAPH_SEARCH_RECIPE", "rrf") or "rrf").strip().lower()

    async def _search(
        self,
        graph_id,
        query,
        limit,
        scope,
        recipe=None,
        center_node_uuid=None,
        bfs_origin_node_uuids=None,
        search_filter=None,
    ):
        g = await self._ensure_graph(graph_id)

        # EXECPLAN2 I-1-0: resolve the recipe selector. node_distance reranking only
        # works with a center node; without one, silently degrade to rrf to avoid a
        # graphiti SearchRerankerError that would break the legacy/default path.
        selector = (recipe or self._default_recipe() or "rrf").strip().lower()
        if selector == "node_distance" and not center_node_uuid:
            selector = "rrf"
        # KG-1: cross-encoder recipes with a NO-OP reranker are strictly worse than RRF —
        # graphiti truncates candidates to the first `limit` in dict-insertion order BEFORE
        # reranking, so a no-op rank means: no RRF fusion AND no semantic rerank. Degrade to
        # the RRF twin unless a real reranker (GRAPHITI_RERANKER=bge) is active.
        if selector in ("cross_encoder", "combined_cross_encoder"):
            try:
                from .cross_encoder import NoOpCrossEncoder

                if isinstance(self._get_clients()[2], NoOpCrossEncoder):
                    degraded = "combined" if selector == "combined_cross_encoder" else "rrf"
                    if not getattr(self, "_noop_ce_degrade_logged", False):
                        self._noop_ce_degrade_logged = True
                        logger.info(
                            "cross_encoder recipe requested but the active reranker is a "
                            "no-op (GRAPHITI_RERANKER!=bge); degrading '%s' -> '%s' to keep "
                            "real RRF fusion", selector, degraded,
                        )
                    selector = degraded
            except Exception:  # pragma: no cover - defensive; never break search on the guard
                pass
        config = self._resolve_recipe(selector, scope).model_copy(deep=True)
        config.limit = limit

        # EXECPLAN2 I-1-0: build a real SearchFilters from the dict spec; a malformed
        # spec degrades to None (no filter) so retrieval still returns results.
        filters = self._to_search_filters(search_filter)

        kwargs: dict = {"config": config, "group_ids": [graph_id]}
        if center_node_uuid:
            kwargs["center_node_uuid"] = center_node_uuid
        if bfs_origin_node_uuids:
            kwargs["bfs_origin_node_uuids"] = list(bfs_origin_node_uuids)
        if filters is not None:
            kwargs["search_filter"] = filters

        # EXECPLAN2 F-12-8: optionally serialize read-vs-write on this graph_id.
        async with self._read_guard(graph_id):
            results = await g.search_(query, **kwargs)
        return list(results.edges), list(results.nodes)

    # ------------------------------------------------------------------
    # Wave9-KG PAGINATION FIX（实测验证的 falkordblite bug）：graphiti 的
    # get_by_group_ids 用 `WHERE uuid < $cursor ... ORDER BY uuid DESC LIMIT n`
    # 做游标分页，但 falkordblite 在 ORDER BY+LIMIT 计划里会**丢弃该属性谓词**
    # （实测 graph mirofish_2ef732b011fc4182：第 2 页返回的首行 uuid 大于游标，
    # 分页循环因此反复取回同一批行，直到 10,000 上限——UI 边负载 ~3x 重复、
    # graph_edge_count/components 指标全被污染）。修复：不再依赖 WHERE 范围谓词，
    # 先取全量**有序 uuid 列表**（本地嵌入库，代价可忽略），在 Python 侧定位游标
    # 偏移（= ORDER BY uuid SKIP $offset LIMIT $limit 的等价语义），再按 uuid IN
    # 批量取回（等值/IN 谓词不受该 bug 影响——merge/get_by_uuid 全线依赖它们）。
    # ------------------------------------------------------------------
    async def _list_uuids_ordered(self, g, graph_id: str, kind: str) -> list:
        """返回该图全部 node/edge uuid，按 uuid DESC 排序（与 graphiti 游标语义一致）。

        刻意**不带任何 WHERE 属性谓词**：实测（gdb 副本，graph mirofish_2ef732b011fc4182）
        falkordblite 连 `WHERE e.group_id = $gid` 这样的**等值**谓词都会静默丢行
        （3,306 条边只回 3,123，而按 group_id 聚合证明全部 3,306 条的 group_id 正确）。
        本仓库两个 falkor 后端都是「一图一租户库」（driver database=graph_id），Kuzu 也
        按图分目录，group 过滤本就冗余；仍取回 group_id 在 Python 侧过滤，双保险。
        """
        if kind != "node":
            raise ValueError("edges 不走 uuid 分页——WHERE uuid IN 对边同样丢行，"
                             "请用 _fetch_edges_unfiltered（零谓词全量取回）")
        cypher = (
            "MATCH (n:Entity) "
            "RETURN n.uuid AS uuid, n.group_id AS gid ORDER BY n.uuid DESC"
        )
        records, _, _ = await g.driver.execute_query(cypher)
        # Python 侧 group 过滤（属性读取可靠，谓词不可靠）+ 去重保序（防御：异常后端把
        # 同一 uuid 返回多次时，分页也绝不放大它）。
        return list(dict.fromkeys(
            r.get("uuid") for r in (records or [])
            if r.get("uuid") and (r.get("gid") in (graph_id, None))
        ))

    async def _fetch_edges_unfiltered(
        self,
        g,
        graph_id: str,
        *,
        deduplicate: bool = True,
    ) -> list:
        """一次性取回该图全部 RELATES_TO 实体边（EntityEdge 对象，uuid DESC 排序）。

        为什么不用 EntityEdge.get_by_uuids / get_by_group_ids：falkordblite 对**边**
        属性的任何 WHERE 谓词（含 `e.uuid IN $uuids` 与 `e.group_id = $gid` 等值匹配）
        都会静默丢行（实测 3,306 条丢到 3,123）。此处查询零 WHERE，投影复用 graphiti
        自己的 return query / record parser，group 过滤与去重在 Python 侧完成。
        本地嵌入库全量扫描代价可忽略（数千行）。
        """
        from graphiti_core.edges import (
            get_entity_edge_from_record,
            get_entity_edge_return_query,
        )

        provider = getattr(getattr(g, "driver", None), "provider", None)
        provider_name = str(getattr(provider, "value", provider) or "").lower()
        if provider_name == "kuzu":
            match = ("MATCH (n:Entity)-[:RELATES_TO]->(e:RelatesToNode_)"
                     "-[:RELATES_TO]->(m:Entity) ")
        else:
            match = "MATCH (n:Entity)-[e:RELATES_TO]->(m:Entity) "
        cypher = (match + "RETURN " + get_entity_edge_return_query(provider)
                  + " ORDER BY e.uuid DESC")
        records, _, _ = await g.driver.execute_query(cypher)
        edges = []
        seen: set = set()
        for rec in (records or []):
            try:
                e = get_entity_edge_from_record(rec, provider)
            except Exception as exc:  # noqa: BLE001 — 单条坏记录不中断全量读取
                logger.debug("edge record parse failed for %s: %s", graph_id, exc)
                continue
            gid = getattr(e, "group_id", None)
            if gid not in (graph_id, None):
                continue
            if deduplicate and e.uuid in seen:
                continue
            seen.add(e.uuid)
            edges.append(e)
        edges.sort(key=lambda e: getattr(e, "uuid", "") or "", reverse=True)
        return edges

    @staticmethod
    def _page_after_cursor(uuids_desc: list, uuid_cursor, limit: int) -> list:
        """在 DESC 有序 uuid 列表上取「游标之后」的一页（游标本身不含在内）。

        游标不在列表中（并发删除/合并）时按序定位到第一个 < 游标的元素，语义仍单调
        前进、绝不回绕——这是旧 WHERE 谓词方案在本后端上做不到的保证。
        """
        lim = max(0, int(limit or 0))
        if not uuids_desc or lim == 0:
            return []
        if not uuid_cursor:
            return uuids_desc[:lim]
        try:
            start = uuids_desc.index(uuid_cursor) + 1
        except ValueError:
            # DESC 序：> cursor 的元素全部在前，跳过它们即为游标位置。
            start = sum(1 for u in uuids_desc if u > uuid_cursor)
        return uuids_desc[start:start + lim]

    def list_nodes(self, graph_id: str, limit: int, uuid_cursor):
        return self.run(self._list_nodes(graph_id, limit, uuid_cursor))

    async def _list_nodes(self, graph_id, limit, uuid_cursor):
        g = await self._ensure_graph(graph_id)
        from graphiti_core.nodes import EntityNode

        # EXECPLAN2 F-12-8: optionally serialize read-vs-write on this graph_id.
        async with self._read_guard(graph_id):
            uuids = await self._list_uuids_ordered(g, graph_id, "node")
            page = self._page_after_cursor(uuids, uuid_cursor, limit)
            if not page:
                return []
            nodes = await EntityNode.get_by_uuids(g.driver, page)
        # get_by_uuids 不保证顺序；恢复 DESC 序，保证 batch[-1] 游标语义稳定。
        nodes.sort(key=lambda n: getattr(n, "uuid", "") or "", reverse=True)
        return nodes

    def list_edges(self, graph_id: str, limit: int, uuid_cursor):
        return self.run(self._list_edges(graph_id, limit, uuid_cursor))

    async def _list_edges(self, graph_id, limit, uuid_cursor):
        g = await self._ensure_graph(graph_id)

        # EXECPLAN2 F-12-8: optionally serialize read-vs-write on this graph_id.
        async with self._read_guard(graph_id):
            # 边不能走 get_by_uuids（falkordblite 对边属性谓词静默丢行，见
            # _fetch_edges_unfiltered 注释）——全量取回后在 Python 侧按游标切页。
            edges = await self._fetch_edges_unfiltered(g, graph_id)
        by_uuid = {e.uuid: e for e in edges}
        page = self._page_after_cursor([e.uuid for e in edges], uuid_cursor, limit)
        return [by_uuid[u] for u in page]

    def get_node(self, uuid: str, graph_id: str | None = None):
        return self.run(self._get_node(uuid, graph_id))

    async def _get_node(self, uuid, graph_id=None):
        from graphiti_core.errors import NodeNotFoundError
        from graphiti_core.nodes import EntityNode

        for gid in await self._candidate_graph_ids(graph_id):
            try:
                g = await self._ensure_graph(gid)
                # EXECPLAN2 F-12-8: optionally serialize read-vs-write on this graph_id.
                async with self._read_guard(gid):
                    return await EntityNode.get_by_uuid(g.driver, uuid)
            except NodeNotFoundError:
                continue
            except Exception:  # pragma: no cover - defensive
                continue
        return None

    def get_node_edges(self, node_uuid: str, graph_id: str | None = None):
        return self.run(self._get_node_edges(node_uuid, graph_id))

    async def _get_node_edges(self, node_uuid, graph_id=None):
        from graphiti_core.edges import EntityEdge

        for gid in await self._candidate_graph_ids(graph_id):
            try:
                g = await self._ensure_graph(gid)
                # EXECPLAN2 F-12-8: optionally serialize read-vs-write on this graph_id.
                async with self._read_guard(gid):
                    edges = await EntityEdge.get_by_node_uuid(g.driver, node_uuid)
                if edges:
                    return edges
            except Exception:  # pragma: no cover - defensive
                continue
        return []

    # ------------------------------------------------------------------
    # EXECPLAN2 I-1-4: entity-resolution primitives (list all nodes, embed
    # names, merge a duplicate node into a survivor). Used by zep_entity_resolver.
    # ------------------------------------------------------------------
    def all_entity_nodes(self, graph_id: str) -> list:
        """Return ALL entity nodes for a graph (paginated), as lightweight dicts."""
        return self.run(self._all_entity_nodes(graph_id))

    async def _all_entity_nodes(self, graph_id, page: int = 500):
        g = await self._ensure_graph(graph_id)
        from graphiti_core.nodes import EntityNode

        out: list = []
        async with self._read_guard(graph_id):
            # Wave9-KG：改走「有序 uuid 全列表 + IN 批量取回」——旧的 uuid_cursor 分页
            # 在 falkordblite 上因谓词被丢弃而重复取页（entity_merges.json 实测
            # nodes_scanned=823 vs 真实 740）。
            uuids = await self._list_uuids_ordered(g, graph_id, "node")
            for i in range(0, len(uuids), page):
                batch = await EntityNode.get_by_uuids(g.driver, uuids[i:i + page])
                for n in batch:
                    out.append({
                        "uuid": n.uuid,
                        "name": n.name,
                        "labels": list(getattr(n, "labels", []) or []),
                        "summary": getattr(n, "summary", "") or "",
                        # 2026-07-03 live-surfaced：此前不带 attributes，导致
                        # zep_entity_resolver._node_aliases() 永远读不到任何别名信号
                        # （同一真实主体的多个别名表面形——如「China」「CCP」「Beijing」
                        # 「MOFCOM」——因此从未被识别为待合并对象，各自独立成节点，
                        # 挤占模拟 agent 池席位）。带上 attributes 让 alias-aware 合并
                        # 真正生效；缺失时默认 {}，与现状完全一致（degrade-safe）。
                        "attributes": dict(getattr(n, "attributes", {}) or {}),
                    })
        return out

    def all_entity_edges(self, graph_id: str) -> list:
        """Wave9-KG：返回该图全部 RELATES_TO 实体边（轻量 dict），供剪枝/子图分析。"""
        return self.run(self._all_entity_edges(graph_id))

    async def _all_entity_edges(self, graph_id):
        g = await self._ensure_graph(graph_id)
        async with self._read_guard(graph_id):
            edges = await self._fetch_edges_unfiltered(g, graph_id)
        return [{
            "uuid": e.uuid,
            "name": getattr(e, "name", "") or "",
            "fact": getattr(e, "fact", "") or "",
            "source_node_uuid": getattr(e, "source_node_uuid", "") or "",
            "target_node_uuid": getattr(e, "target_node_uuid", "") or "",
            "attributes": dict(getattr(e, "attributes", {}) or {}),
        } for e in edges]

    def actor_graph_seed_state(self, graph_id: str) -> dict:
        """Return uncapped physical seed rows, retaining duplicate edge UUIDs."""
        return self.run(self._actor_graph_seed_state(graph_id))

    async def _actor_graph_seed_state(self, graph_id: str) -> dict:
        g = await self._ensure_graph(graph_id)
        from graphiti_core.nodes import EntityNode

        nodes: list[dict] = []
        edges: list[dict] = []
        async with self._read_guard(graph_id):
            uuids = await self._list_uuids_ordered(g, graph_id, "node")
            for index in range(0, len(uuids), 500):
                batch = await EntityNode.get_by_uuids(
                    g.driver, uuids[index:index + 500]
                )
                for node in batch:
                    attrs = dict(getattr(node, "attributes", {}) or {})
                    if attrs.get("seed_schema_version") != "actor-graph-seed/v1":
                        continue
                    nodes.append({
                        "uuid": node.uuid,
                        "name": node.name,
                        "labels": list(getattr(node, "labels", []) or []),
                        "summary": getattr(node, "summary", "") or "",
                        "attributes": attrs,
                    })
            raw_edges = await self._fetch_edges_unfiltered(
                g,
                graph_id,
                deduplicate=False,
            )
            for edge in raw_edges:
                attrs = dict(getattr(edge, "attributes", {}) or {})
                if attrs.get("seed_schema_version") != "actor-graph-seed/v1":
                    continue
                edges.append({
                    "uuid": edge.uuid,
                    "name": getattr(edge, "name", "") or "",
                    "fact": getattr(edge, "fact", "") or "",
                    "source_node_uuid": (
                        getattr(edge, "source_node_uuid", "") or ""
                    ),
                    "target_node_uuid": (
                        getattr(edge, "target_node_uuid", "") or ""
                    ),
                    "attributes": attrs,
                })
        nodes.sort(key=lambda row: (row["uuid"], row["name"]))
        edges.sort(key=lambda row: (
            row["uuid"], row["source_node_uuid"], row["target_node_uuid"]
        ))
        return {"nodes": nodes, "edges": edges}

    def mention_counts(self, graph_id: str) -> dict:
        """Wave9-KG：每个实体节点被 Episodic MENTIONS 的次数（重要度信号之一）。

        失败返回 {}（degrade-safe：剪枝重要度退化为 度数+is_core）。"""
        return self.run(self._mention_counts(graph_id))

    async def _mention_counts(self, graph_id):
        try:
            g = await self._ensure_graph(graph_id)
            async with self._read_guard(graph_id):
                # 不用 WHERE 谓词（falkordblite 连等值谓词都可能静默丢行，见
                # _list_uuids_ordered）；group 过滤在 Python 侧做（一图一租户库，冗余双保险）。
                records, _, _ = await g.driver.execute_query(
                    "MATCH (ep:Episodic)-[:MENTIONS]->(n:Entity) "
                    "RETURN n.uuid AS uuid, n.group_id AS gid, count(ep) AS c",
                )
            return {
                r.get("uuid"): int(r.get("c") or 0)
                for r in (records or [])
                if r.get("uuid") and (r.get("gid") in (graph_id, None))
            }
        except Exception as exc:  # noqa: BLE001 — 重要度先验缺失不应中断剪枝
            logger.warning("mention_counts failed for %s: %s", graph_id, exc)
            return {}

    def embed_texts(self, texts: list) -> list:
        """Embed a list of strings into unit vectors (local sentence-transformer)."""
        return self.run(self._embed_texts(texts))

    async def _embed_texts(self, texts):
        embedder, _, _ = self._get_clients()
        if not texts:
            return []
        return await embedder.create_batch(list(texts))

    def merge_nodes(self, graph_id: str, survivor_uuid: str, victim_uuid: str) -> dict:
        """Merge ``victim`` entity node into ``survivor`` (EXECPLAN2 I-1-4).

        Rewires the victim's RELATES_TO edges onto the survivor (via graphiti_core's
        own EntityEdge.save — so the backend dialect, incl. reified RelatesToNode_
        backends, is handled by the library, not hand-written Cypher), unions
        attributes/labels onto the survivor, then DETACH-DELETEs the victim. A fresh
        edge uuid is assigned on rewire so the re-save can never collide with the
        victim's original edge uuid. Per-edge and overall best-effort: a failed step
        is logged and skipped (never half-corrupts beyond the offending edge). The
        whole pass is serialized on the per-graph write lock. Episodic MENTIONS edges
        to the victim are not rewired (provenance only) and drop with the victim.
        """
        return self.run(self._merge_nodes(graph_id, survivor_uuid, victim_uuid))

    async def _merge_nodes(self, graph_id, survivor_uuid, victim_uuid):
        import uuid as _uuidlib

        from graphiti_core.edges import EntityEdge
        from graphiti_core.nodes import EntityNode

        if survivor_uuid == victim_uuid:
            return {"rewired": 0, "deleted": False, "skipped": "same uuid"}
        g = await self._ensure_graph(graph_id)
        async with self._graph_lock(graph_id):
            try:
                survivor = await EntityNode.get_by_uuid(g.driver, survivor_uuid)
                victim = await EntityNode.get_by_uuid(g.driver, victim_uuid)
            except Exception as exc:
                logger.warning("merge_nodes: could not load nodes (%s): %s", graph_id, exc)
                return {"rewired": 0, "deleted": False, "skipped": "node load failed"}
            if survivor is None or victim is None:
                return {"rewired": 0, "deleted": False, "skipped": "node missing"}

            def _seed_kind(value) -> str:
                attrs = dict(getattr(value, "attributes", None) or {})
                if attrs.get("seed_schema_version") != "actor-graph-seed/v1":
                    return ""
                return str(attrs.get("seed_kind") or "")

            survivor_seed_kind = _seed_kind(survivor)
            victim_seed_kind = _seed_kind(victim)
            swapped_for_seed = False
            if victim_seed_kind == "actor" and survivor_seed_kind != "actor":
                # Defense in depth: the pure planner should already select this
                # order, but a direct caller may not. Canonical seed identity can
                # never be deleted in favour of a prose-extracted duplicate.
                survivor, victim = victim, survivor
                survivor_uuid, victim_uuid = victim_uuid, survivor_uuid
                survivor_seed_kind, victim_seed_kind = (
                    victim_seed_kind,
                    survivor_seed_kind,
                )
                swapped_for_seed = True
            if victim_seed_kind == "entity_type":
                return {
                    "rewired": 0,
                    "deleted": False,
                    "skipped": "seed entity-type node is protected",
                }
            if victim_seed_kind == "actor":
                return {
                    "rewired": 0,
                    "deleted": False,
                    "skipped": "canonical actor seed cannot be a merge victim",
                }
            if victim_seed_kind == "actor_alias":
                survivor_attrs = dict(
                    getattr(survivor, "attributes", None) or {}
                )
                victim_attrs = dict(getattr(victim, "attributes", None) or {})
                if (
                    survivor_seed_kind != "actor"
                    or survivor_attrs.get("actor_id")
                    != victim_attrs.get("actor_id")
                ):
                    return {
                        "rewired": 0,
                        "deleted": False,
                        "skipped": "seed alias may merge only into its canonical actor",
                    }

            try:
                edges = await EntityEdge.get_by_node_uuid(g.driver, victim_uuid)
            except Exception as exc:
                logger.warning("merge_nodes: could not list victim edges (%s): %s", graph_id, exc)
                edges = []

            # A canonical relationship edge may be attached to a duplicate only
            # in a damaged/pre-cutover graph. It can be moved to the canonical
            # survivor with the SAME UUID, but never collapsed into a self-loop.
            for edge in edges:
                attrs = dict(getattr(edge, "attributes", None) or {})
                if not (
                    attrs.get("seed_schema_version") == "actor-graph-seed/v1"
                    and attrs.get("seed_kind") == "relationship"
                ):
                    continue
                new_source = (
                    survivor_uuid
                    if edge.source_node_uuid == victim_uuid
                    else edge.source_node_uuid
                )
                new_target = (
                    survivor_uuid
                    if edge.target_node_uuid == victim_uuid
                    else edge.target_node_uuid
                )
                if new_source == new_target:
                    return {
                        "rewired": 0,
                        "deleted": False,
                        "skipped": "seed relationship would collapse to self-loop",
                    }

            rewired = 0
            seed_rewire_failed = False
            for e in edges:
                edge_attrs = dict(getattr(e, "attributes", None) or {})
                is_seed_edge = (
                    edge_attrs.get("seed_schema_version")
                    == "actor-graph-seed/v1"
                )
                try:
                    touched = False
                    if e.source_node_uuid == victim_uuid:
                        e.source_node_uuid = survivor_uuid
                        touched = True
                    if e.target_node_uuid == victim_uuid:
                        e.target_node_uuid = survivor_uuid
                        touched = True
                    if not touched:
                        continue
                    if e.source_node_uuid == e.target_node_uuid:
                        continue  # self-loop after merge — drop (removed with victim)
                    if not is_seed_edge:
                        # Extracted/legacy edge has no external identity contract.
                        e.uuid = str(_uuidlib.uuid4())
                    # Seeded edges retain UUID+attributes. Saving the same UUID on
                    # the canonical endpoints before victim deletion leaves the
                    # manifest identity intact after the old attachment disappears.
                    await e.save(g.driver)
                    rewired += 1
                except Exception as exc:
                    logger.warning("merge_nodes: edge rewire failed (%s): %s", graph_id, exc)
                    if is_seed_edge:
                        seed_rewire_failed = True

            if seed_rewire_failed:
                return {
                    "rewired": rewired,
                    "deleted": False,
                    "survivor_uuid": survivor_uuid,
                    "victim_uuid": victim_uuid,
                    "swapped_for_seed": swapped_for_seed,
                    "skipped": "seed edge rewire failed",
                }

            # union victim attributes/labels onto survivor (never overwrite survivor's)
            try:
                v_attrs = dict(getattr(victim, "attributes", None) or {})
                s_attrs = dict(getattr(survivor, "attributes", None) or {})
                for k, val in v_attrs.items():
                    s_attrs.setdefault(k, val)
                if hasattr(survivor, "attributes"):
                    survivor.attributes = s_attrs
                survivor.labels = list(dict.fromkeys(
                    list(survivor.labels or []) + list(victim.labels or [])
                ))
                await survivor.save(g.driver)
            except Exception as exc:
                logger.warning("merge_nodes: survivor union failed (%s): %s", graph_id, exc)

            deleted = False
            try:
                await victim.delete(g.driver)
                deleted = True
            except Exception as exc:
                logger.warning("merge_nodes: victim delete failed (%s): %s", graph_id, exc)
        return {
            "rewired": rewired,
            "deleted": deleted,
            "survivor_uuid": survivor_uuid,
            "victim_uuid": victim_uuid,
            "swapped_for_seed": swapped_for_seed,
        }

    def delete_entity_nodes(self, graph_id: str, uuids: list) -> dict:
        """Wave9-KG（graph_pruner 的删除原语，与 merge_nodes 同族）：批量 DETACH-DELETE
        实体节点。走 graphiti 自己的 ``EntityNode.delete``（各后端方言——含 Kuzu 的
        reified 边节点——由库处理，而非手写 Cypher），整批持有 per-graph 写锁串行化；
        逐节点 best-effort：单个删除失败只记账，绝不中断其余删除。
        返回 {"requested": n, "deleted": d, "failed": f}。"""
        return self.run(self._delete_entity_nodes(graph_id, uuids))

    async def _delete_entity_nodes(self, graph_id, uuids, page: int = 200):
        from graphiti_core.nodes import EntityNode

        wanted = [u for u in dict.fromkeys(uuids or []) if u]
        if not wanted:
            return {"requested": 0, "deleted": 0, "failed": 0}
        g = await self._ensure_graph(graph_id)
        deleted = 0
        failed = 0
        async with self._graph_lock(graph_id):
            for i in range(0, len(wanted), page):
                chunk = wanted[i:i + page]
                try:
                    nodes = await EntityNode.get_by_uuids(g.driver, chunk)
                except Exception as exc:  # noqa: BLE001 — 加载失败整批记为 failed
                    logger.warning("delete_entity_nodes: load batch failed (%s): %s",
                                   graph_id, exc)
                    failed += len(chunk)
                    continue
                loaded = {getattr(n, "uuid", None) for n in nodes}
                failed += len([u for u in chunk if u not in loaded])
                for n in nodes:
                    try:
                        await n.delete(g.driver)
                        deleted += 1
                    except Exception as exc:  # noqa: BLE001 — 单点失败不中断
                        failed += 1
                        logger.warning("delete_entity_nodes: delete %s failed (%s): %s",
                                       getattr(n, "uuid", "?"), graph_id, exc)
        return {"requested": len(wanted), "deleted": deleted, "failed": failed}

    def list_graph_ids(self) -> list:
        """Wave9-KG（陈旧图谱 GC）：枚举后端上的全部图谱名（GRAPH.LIST）。

        best-effort：不支持枚举的后端返回 []（GC 会自然 no-op，绝不误删）。"""
        return self.run(self._list_graph_ids())

    async def _list_graph_ids(self):
        try:
            backend = self._resolve_backend()
            if backend == "falkordblite":
                client = await self._get_falkor_client()
                if hasattr(client, "list_graphs"):
                    names = await client.list_graphs()
                    return [n for n in (names or []) if isinstance(n, str)]
            elif backend == "falkordb":
                from falkordb.asyncio import FalkorDB  # type: ignore

                host = os.environ.get("FALKORDB_HOST", "localhost")
                port = int(os.environ.get("FALKORDB_PORT", "6379"))
                db = FalkorDB(
                    host=host, port=port,
                    username=os.environ.get("FALKORDB_USERNAME") or None,
                    password=os.environ.get("FALKORDB_PASSWORD") or None,
                )
                try:
                    names = await db.list_graphs()
                    return [n for n in (names or []) if isinstance(n, str)]
                finally:
                    with contextlib.suppress(Exception):
                        await db.connection.aclose()
        except Exception as exc:  # noqa: BLE001 — 枚举失败 → GC no-op
            logger.warning("list_graph_ids failed: %s", exc)
        return []

    def graph_last_created_at(self, graph_id: str) -> str | None:
        """Wave9-KG（GC 的新旧排序信号）：该图最新节点的 created_at（ISO 字符串）。

        直接经 falkor 客户端查询，避免为 40 个死图各自实例化 Graphiti（建索引/预热
        embedder 的代价）。失败返回 None（GC 把它当作最旧的）。"""
        return self.run(self._graph_last_created_at(graph_id))

    async def _graph_last_created_at(self, graph_id):
        try:
            if self._resolve_backend() != "falkordblite":
                # 非嵌入后端退回完整 driver 路径（图已缓存时零额外成本）。
                g = await self._ensure_graph(graph_id)
                records, _, _ = await g.driver.execute_query(
                    "MATCH (n) RETURN max(n.created_at) AS latest"
                )
            else:
                client = await self._get_falkor_client()
                graph = client.select_graph(graph_id)
                result = await graph.query("MATCH (n) RETURN max(n.created_at) AS latest")
                rows = getattr(result, "result_set", None) or []
                records = [{"latest": rows[0][0]}] if rows and rows[0] else []
            latest = records[0].get("latest") if records else None
            if latest is None:
                return None
            if isinstance(latest, datetime):
                return latest.isoformat()
            return str(latest)
        except Exception as exc:  # noqa: BLE001 — 排序信号缺失即视为最旧
            logger.debug("graph_last_created_at failed for %s: %s", graph_id, exc)
            return None

    def delete_graph(self, graph_id: str) -> None:
        self.run(self._delete_graph(graph_id))

    async def _delete_graph(self, graph_id):
        # EXECPLAN2 F-12-8: serialize the delete against any in-flight writer/reader
        # on this graph_id so we never tear data out from under a live operation.
        async with self._graph_lock(graph_id):
            g = self._graphs.pop(graph_id, None)
            self._ontologies.pop(graph_id, None)

            # EXECPLAN2 F-2-1: drop the server-side FalkorDB graph data BEFORE closing
            # the driver. The previous code gated this on ``self._falkor_client``, which
            # is populated ONLY on the embedded (falkordblite) path — so on the
            # ``falkordb`` server backend (each driver builds its own client) the data
            # deletion was skipped entirely and the graph leaked on the server forever,
            # while the surrounding ``except: pass`` falsely reported success.
            #
            # Resolve the FalkorDB connection from the LIVE driver, which works for both
            # backends (driver.client is the AsyncFalkorDB/FalkorDB for embedded AND
            # server). Fall back to the shared embedded client when the graph was never
            # cached in this process.
            falkor_client = None
            if g is not None:
                falkor_client = getattr(getattr(g, "driver", None), "client", None)
            if falkor_client is None:
                falkor_client = self._falkor_client

            if falkor_client is not None and hasattr(falkor_client, "select_graph"):
                try:
                    graph = falkor_client.select_graph(graph_id)
                    await graph.delete()
                except Exception as exc:  # EXECPLAN2 F-2-1: surface the leak, don't swallow it
                    logger.warning("Failed to delete FalkorDB graph %s: %s", graph_id, exc)

            # EXECPLAN2 F-2-1: only close the driver when it does NOT wrap the shared
            # embedded client. On falkordblite every cached graph reuses the single
            # ``self._falkor_client``; closing one driver would aclose() that shared
            # connection and break every other graph. On the server backend each driver
            # owns its own client, so closing it frees the connection (no leak).
            if g is not None:
                driver_client = getattr(getattr(g, "driver", None), "client", None)
                shares_embedded_client = (
                    self._falkor_client is not None
                    and driver_client is self._falkor_client
                )
                if not shares_embedded_client:
                    try:
                        await g.close()
                    except Exception as exc:
                        logger.debug("Error closing graph %s after delete: %s", graph_id, exc)

        # NOTE (EXECPLAN2 F-12-8): intentionally retain the per-graph lock in the
        # registry. Popping it here could hand a freshly-created lock to a new caller
        # while another coroutine is still blocked on the old one for the same
        # graph_id, defeating the mutual exclusion. The registry is bounded by the
        # number of distinct graph_ids (same lifetime concern as self._graphs), so
        # the leak is negligible; correctness wins.

    # ------------------------------------------------------------------
    def _shutdown(self):  # pragma: no cover - process teardown
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass


_runtime: GraphitiRuntime | None = None
_runtime_lock = threading.Lock()


def get_runtime() -> GraphitiRuntime:
    global _runtime
    if _runtime is None:
        with _runtime_lock:
            if _runtime is None:
                _runtime = GraphitiRuntime()
    return _runtime
