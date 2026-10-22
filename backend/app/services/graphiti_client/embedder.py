"""Fully-local embedder for Graphiti using sentence-transformers.

Zep Cloud computed embeddings server-side; locally we must supply an embedder. The app's
LLM provider may not expose an embeddings endpoint (e.g. minimax/kimi/claude-cli), so we
default to a local sentence-transformers model — no API key, provider-independent, and
multilingual (the app handles bilingual EN/中文 content).

Model + dimension are configurable via env:
  GRAPHITI_EMBED_MODEL  (default: paraphrase-multilingual-MiniLM-L12-v2, 384-dim)
  GRAPHITI_EMBED_DIM    (must match the model; also exported as EMBEDDING_DIM)

NOTE: ``EMBEDDING_DIM`` is read once, frozen at import, inside graphiti_core.embedder.client.
The package ``__init__`` sets it BEFORE importing graphiti, so this module's import is safe.

Performance (R2-EXEC-2 / GAP-2 / R2-EXEC-5):
- Encoding runs on a DEDICATED small ThreadPoolExecutor (EMBED_EXECUTOR_WORKERS) instead of
  the asyncio default pool, so the CPU-bound SentenceTransformer encode stops stealing the
  threads the graphiti LLM I/O pool needs (and torch intra-op threads are pinned so encode
  does not grab every core and serialize behind the GIL).
- Deterministic vectors are cached content-addressed by (model, normalized_text): a bounded
  in-memory LRU (GAP-2) backed by an optional write-through sqlite store (R2-EXEC-5) at
  EMBED_DISK_CACHE_PATH, so resumes/seeds/forks re-embed at near-zero cost.
All caching/threading is degrade-safe: any failure falls back to a plain encode.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import sqlite3
import struct
import threading
from collections import OrderedDict
from collections.abc import Iterable
from app.utils.concurrency import ContextThreadPoolExecutor as ThreadPoolExecutor  # LOG-16: run 上下文随任务传播

from graphiti_core.embedder.client import EmbedderClient

logger = logging.getLogger("mirofish.graphiti_embedder")

DEFAULT_EMBED_MODEL = os.environ.get(
    "GRAPHITI_EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"
)
DEFAULT_EMBED_DIM = int(os.environ.get("GRAPHITI_EMBED_DIM", "384"))

# GAP-2: bound the in-memory LRU so a long multi-seed run cannot grow it without limit.
_MEM_CACHE_MAX = 50000


# ---------------------------------------------------------------------------
# R2-EXEC-2: dedicated CPU pool for SentenceTransformer encode, isolated from the
# graphiti LLM I/O pool and the asyncio default executor.
# ---------------------------------------------------------------------------
_embed_pool: ThreadPoolExecutor | None = None
_embed_pool_lock = threading.Lock()
_torch_pinned = False


def get_embed_pool() -> ThreadPoolExecutor:
    """Return the process-global dedicated executor for local embedding encode.

    Size is read once from ``Config.EMBED_EXECUTOR_WORKERS`` (default 4); a
    bad/missing value degrades to 4. torch / OMP intra-op threads are pinned to the
    same width so the encode stays on its own small footprint instead of contending
    for every core with the LLM POST threads.
    """
    global _embed_pool, _torch_pinned
    if _embed_pool is None:
        with _embed_pool_lock:
            if _embed_pool is None:
                workers = _embed_workers()
                _pin_compute_threads(workers)
                _embed_pool = ThreadPoolExecutor(
                    max_workers=workers, thread_name_prefix="embed"
                )
                logger.info("embedding compute pool: %d workers", workers)
    return _embed_pool


def _embed_workers() -> int:
    try:
        from ...config import Config

        workers = int(getattr(Config, "EMBED_EXECUTOR_WORKERS", 4) or 4)
    except Exception:  # noqa: BLE001 — config unavailable → conservative default
        workers = 4
    return max(1, workers)


def _pin_compute_threads(workers: int) -> None:
    """Pin torch/OMP intra-op threads so encode does not monopolise every core.

    Best-effort: import/availability failures are non-fatal (encode still works,
    just without the pin).
    """
    global _torch_pinned
    if _torch_pinned:
        return
    os.environ.setdefault("OMP_NUM_THREADS", str(workers))
    try:
        import torch

        torch.set_num_threads(max(1, workers))
    except Exception as exc:  # noqa: BLE001 — torch optional / pin best-effort
        logger.debug("torch thread pin skipped: %s", exc)
    _torch_pinned = True


def _normalize_text(text: str) -> str:
    """Content-address key normalization: collapse surrounding/inner whitespace.

    Deterministic and cheap; keeps byte-identical-modulo-whitespace texts on one
    cache entry without altering what is actually encoded for a miss.
    """
    return " ".join((text or "").split())


class _DiskEmbedCache:
    """Write-through sqlite store keyed by (model, normalized_text) hash (R2-EXEC-5).

    Vectors are deterministic for a fixed model, so persisting them makes resumes and
    every seed beyond the first near-zero embedding cost. Fully degrade-safe: any
    sqlite error disables the disk layer for the rest of the process (in-memory LRU
    still applies) rather than failing the build.
    """

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._enabled = True
        self._conn: sqlite3.Connection | None = None
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            # check_same_thread=False: encode runs on pool threads; we guard with a lock.
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS embeddings (k TEXT PRIMARY KEY, v BLOB NOT NULL)"
            )
            self._conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("embed disk cache disabled (%s): %s", path, exc)
            self._enabled = False
            self._conn = None

    def get_many(self, keys: list[str]) -> dict[str, list[float]]:
        if not self._enabled or self._conn is None or not keys:
            return {}
        out: dict[str, list[float]] = {}
        try:
            with self._lock:
                # Chunk IN() clauses to stay well under SQLite's parameter limit.
                for i in range(0, len(keys), 400):
                    chunk = keys[i : i + 400]
                    placeholders = ",".join("?" * len(chunk))
                    cur = self._conn.execute(
                        f"SELECT k, v FROM embeddings WHERE k IN ({placeholders})", chunk
                    )
                    for k, blob in cur.fetchall():
                        out[k] = list(struct.unpack(f"{len(blob) // 4}f", blob))
        except Exception as exc:  # noqa: BLE001
            logger.debug("embed disk cache read failed, disabling: %s", exc)
            self._enabled = False
        return out

    def put_many(self, items: dict[str, list[float]]) -> None:
        if not self._enabled or self._conn is None or not items:
            return
        try:
            with self._lock:
                self._conn.executemany(
                    "INSERT OR REPLACE INTO embeddings (k, v) VALUES (?, ?)",
                    [
                        (k, struct.pack(f"{len(v)}f", *v))
                        for k, v in items.items()
                    ],
                )
                self._conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("embed disk cache write failed, disabling: %s", exc)
            self._enabled = False


def _disk_cache_path() -> str | None:
    """Resolve EMBED_DISK_CACHE_PATH (relative → anchored to the backend dir).

    Empty/falsy disables the disk layer (in-memory LRU still applies).
    """
    try:
        from ...config import Config

        raw = getattr(Config, "EMBED_DISK_CACHE_PATH", "uploads/graphiti_db/embed_cache.sqlite")
    except Exception:  # noqa: BLE001
        raw = os.environ.get("EMBED_DISK_CACHE_PATH", "uploads/graphiti_db/embed_cache.sqlite")
    if not raw:
        return None
    if os.path.isabs(raw):
        return raw
    # backend/app/services/graphiti_client/embedder.py -> backend/
    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    return os.path.join(backend_dir, raw)


class LocalSentenceTransformerEmbedder(EmbedderClient):
    """Embeds text locally with a sentence-transformers model.

    The model is loaded lazily on first use (so importing the package — e.g. for the
    Flask app boot — does not pay the model-load cost until a graph is actually built or
    searched). Encoding is offloaded to a dedicated thread pool so the async event loop
    stays responsive and the LLM I/O pool keeps its threads.
    """

    def __init__(self, model_name: str | None = None, embedding_dim: int | None = None):
        self.model_name = model_name or DEFAULT_EMBED_MODEL
        self.embedding_dim = embedding_dim or DEFAULT_EMBED_DIM
        self._model = None
        self._lock = threading.Lock()
        # GAP-2: bounded content-addressed in-memory LRU keyed by (model, normalized text).
        self._mem_cache: "OrderedDict[str, list[float]]" = OrderedDict()
        self._mem_lock = threading.Lock()
        # R2-EXEC-5: optional write-through sqlite layer (lazy, degrade-safe).
        self._disk_cache: _DiskEmbedCache | None = None
        self._disk_inited = False

    def _ensure_model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    # hf_transfer is an optional download accelerator; if the env opts into
                    # it (HF_HUB_ENABLE_HF_TRANSFER=1) but the package isn't installed, HF
                    # downloads hard-fail. Disable it when unavailable so the standard
                    # download path works on a fresh machine.
                    import importlib.util

                    if importlib.util.find_spec("hf_transfer") is None:
                        os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

                    from sentence_transformers import SentenceTransformer

                    self._model = SentenceTransformer(self.model_name)
        return self._model

    def _ensure_disk_cache(self) -> _DiskEmbedCache | None:
        if not self._disk_inited:
            with self._lock:
                if not self._disk_inited:
                    path = _disk_cache_path()
                    self._disk_cache = _DiskEmbedCache(path) if path else None
                    self._disk_inited = True
        return self._disk_cache

    def _cache_key(self, normalized: str) -> str:
        h = hashlib.sha256()
        h.update(self.model_name.encode("utf-8"))
        h.update(b"\x00")
        h.update(normalized.encode("utf-8"))
        return h.hexdigest()

    def _mem_get(self, key: str) -> list[float] | None:
        with self._mem_lock:
            vec = self._mem_cache.get(key)
            if vec is not None:
                self._mem_cache.move_to_end(key)  # LRU touch
            return vec

    def _mem_put(self, key: str, vec: list[float]) -> None:
        with self._mem_lock:
            self._mem_cache[key] = vec
            self._mem_cache.move_to_end(key)
            while len(self._mem_cache) > _MEM_CACHE_MAX:
                self._mem_cache.popitem(last=False)  # evict oldest

    def _raw_encode(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_model()
        # normalize_embeddings=True -> unit vectors, matching Graphiti's cosine search
        embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        out: list[list[float]] = []
        for row in embeddings:
            vec = [float(x) for x in row][: self.embedding_dim]
            out.append(vec)
        return out

    def _encode(self, texts: list[str]) -> list[list[float]]:
        """Encode ``texts`` to unit vectors, reusing cached vectors where possible.

        Order and length of the returned list always mirror ``texts`` exactly.
        """
        if not texts:
            return []
        normalized = [_normalize_text(t) for t in texts]
        keys = [self._cache_key(nt) for nt in normalized]

        results: list[list[float] | None] = [None] * len(texts)
        # 1) in-memory LRU
        missing_idx: list[int] = []
        for i, k in enumerate(keys):
            vec = self._mem_get(k)
            if vec is not None:
                results[i] = vec
            else:
                missing_idx.append(i)

        # 2) disk cache for the remaining misses
        if missing_idx:
            disk = self._ensure_disk_cache()
            if disk is not None:
                miss_keys = list({keys[i] for i in missing_idx})
                found = disk.get_many(miss_keys)
                if found:
                    still_missing: list[int] = []
                    for i in missing_idx:
                        vec = found.get(keys[i])
                        if vec is not None and len(vec) == self.embedding_dim:
                            results[i] = vec
                            self._mem_put(keys[i], vec)
                        else:
                            still_missing.append(i)
                    missing_idx = still_missing

        # 3) compute the genuine misses once (dedup identical texts within the batch)
        if missing_idx:
            uniq: "OrderedDict[str, int]" = OrderedDict()
            for i in missing_idx:
                uniq.setdefault(keys[i], i)
            uniq_idx = list(uniq.values())
            computed = self._raw_encode([texts[i] for i in uniq_idx])
            new_disk: dict[str, list[float]] = {}
            by_key: dict[str, list[float]] = {}
            for j, i in enumerate(uniq_idx):
                vec = computed[j]
                by_key[keys[i]] = vec
                self._mem_put(keys[i], vec)
                new_disk[keys[i]] = vec
            for i in missing_idx:
                results[i] = by_key[keys[i]]
            disk = self._ensure_disk_cache()
            if disk is not None and new_disk:
                disk.put_many(new_disk)

        # Defensive: any None left (should not happen) → zero vector.
        return [r if r is not None else [0.0] * self.embedding_dim for r in results]

    async def create(
        self, input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]]
    ) -> list[float]:
        # Mirror OpenAIEmbedder.create: return the embedding of the first input.
        if isinstance(input_data, str):
            texts = [input_data]
        else:
            texts = [str(x) for x in input_data]  # type: ignore[arg-type]
        if not texts:
            return [0.0] * self.embedding_dim
        loop = asyncio.get_event_loop()
        vecs = await loop.run_in_executor(get_embed_pool(), self._encode, texts)
        return vecs[0]

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        if not input_data_list:
            return []
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(get_embed_pool(), self._encode, list(input_data_list))
