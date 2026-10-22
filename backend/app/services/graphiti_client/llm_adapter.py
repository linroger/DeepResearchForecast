"""Provider-agnostic Graphiti LLM client backed by the app's own ``LLMClient``.

Graphiti needs an LLM to extract entities/edges from episodes and return schema-conforming
JSON. Rather than bind Graphiti to one provider, we delegate to the app's existing
``app.utils.llm_client.LLMClient``, which already supports every configured provider
(claude-cli / codex-cli / openai / kimi / minimax / deepseek / qwen / glm), with
disable-thinking handling, Kimi User-Agent injection, retries, and JSON repair.

This means local graph building works with whatever provider the user configured —
including the no-API-key CLI providers — and needs NO embeddings endpoint (embeddings are
handled separately by the local sentence-transformers embedder).

The Graphiti base ``LLMClient.generate_response`` already injects the response model's JSON
schema and a multilingual instruction into the messages before calling ``_generate_response``,
so here we only translate messages and invoke the app client's ``chat_json``.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import threading
import typing
from app.utils.concurrency import ContextThreadPoolExecutor as ThreadPoolExecutor  # LOG-16: run 上下文随任务传播

from pydantic import BaseModel

from graphiti_core.llm_client.client import LLMClient as GraphitiLLMClient
from graphiti_core.llm_client.config import LLMConfig, ModelSize
from graphiti_core.llm_client.errors import EmptyResponseError, RateLimitError

from ...utils.llm_client import LLMClient as AppLLMClient
from ...config import Config

logger = logging.getLogger("mirofish.graphiti_llm")


# ---------------------------------------------------------------------------
# R2-EXEC-1: dedicated I/O thread pool for the blocking graphiti LLM HTTP calls.
#
# Graphiti drives episode extraction by awaiting ``_generate_response`` from the
# runtime's single bg event loop. Each call offloads a *blocking* ``chat_json``
# POST onto a thread via ``loop.run_in_executor``. Previously this passed
# ``None`` → the asyncio DEFAULT ThreadPoolExecutor, whose size is
# ``min(32, os.cpu_count()+4)`` (~12-20 on typical hosts) and which is SHARED with
# every other ``run_in_executor`` user (incl. the embedder's CPU encode). That
# shared, ~20-slot pool is the hard ceiling that silently caps GRAPH_BUILD_CONCURRENCY
# × GRAPHITI_MAX_COROUTINES no matter how high those knobs are set — the wedge root.
#
# A dedicated, larger pool (GRAPH_LLM_EXECUTOR_WORKERS, default 64) lets the
# concurrency knobs actually reach the proxy. Lazily built, process-global, and
# exposed via an accessor so every AppGraphitiLLMClient instance shares ONE pool.
# ---------------------------------------------------------------------------
_io_pool: ThreadPoolExecutor | None = None
_io_pool_lock = threading.Lock()


def get_graph_llm_io_pool() -> ThreadPoolExecutor:
    """Return the process-global dedicated executor for blocking graphiti LLM POSTs.

    Size is read once from ``Config.GRAPH_LLM_EXECUTOR_WORKERS`` (default 64); a
    bad/missing value degrades to 64. Safe to call from any thread.
    """
    global _io_pool
    if _io_pool is None:
        with _io_pool_lock:
            if _io_pool is None:
                try:
                    workers = int(getattr(Config, "GRAPH_LLM_EXECUTOR_WORKERS", 64) or 64)
                except (TypeError, ValueError):
                    workers = 64
                workers = max(1, workers)
                _io_pool = ThreadPoolExecutor(
                    max_workers=workers, thread_name_prefix="graphiti-llm"
                )
                logger.info("graphiti LLM I/O pool: %d workers", workers)
    return _io_pool

# Transient OpenAI-SDK errors that should be retried rather than aborting a whole graph
# build. Graphiti's tenacity retry fires on RateLimitError, so we normalize to it.
try:  # pragma: no cover - import guard for environments without openai
    from openai import (
        APIConnectionError as _OpenAIConnError,
        APITimeoutError as _OpenAITimeout,
        InternalServerError as _OpenAIServerError,
        RateLimitError as _OpenAIRateLimit,
    )

    _TRANSIENT_LLM_ERRORS: tuple[type[Exception], ...] = (
        _OpenAITimeout,
        _OpenAIConnError,
        _OpenAIServerError,
        _OpenAIRateLimit,
    )
except Exception:  # pragma: no cover
    _TRANSIENT_LLM_ERRORS = ()


class AppGraphitiLLMClient(GraphitiLLMClient):
    """Adapts the app's synchronous ``LLMClient`` to Graphiti's async LLM interface."""

    def __init__(self, app_llm: AppLLMClient | None = None, max_tokens: int = 8192):
        config = LLMConfig(
            api_key=Config.LLM_API_KEY or "local",
            model=Config.LLM_MODEL_NAME,
            base_url=Config.LLM_BASE_URL,
            max_tokens=max_tokens,
        )
        super().__init__(config, cache=False)
        self._app_llm = app_llm or AppLLMClient()
        self._max_tokens = max_tokens

    async def _generate_response(
        self,
        messages: list,
        response_model: type[BaseModel] | None = None,
        max_tokens: int = 0,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, typing.Any]:
        # Graphiti Message objects expose .role / .content; the schema (if any) and the
        # multilingual instruction are already baked into message content by the base class.
        msg_dicts = [{"role": m.role, "content": m.content} for m in messages]
        if msg_dicts:
            # Non-premium models sometimes echo the injected JSON *schema* back instead of
            # producing a conforming instance. Add an explicit guard to the final message.
            msg_dicts[-1] = {
                "role": msg_dicts[-1]["role"],
                "content": msg_dicts[-1]["content"]
                + (
                    "\n\nIMPORTANT: Output ONLY a single JSON object that is a concrete "
                    "INSTANCE conforming to the schema above — with real extracted values. "
                    "Do NOT output the schema itself; never include keys like \"$defs\", "
                    "\"properties\", \"$ref\", or \"type\": \"object\"."
                ),
            }
        tokens = max_tokens or self._max_tokens

        # GAP-1 / model_size->tier mapping: mechanical extraction (graphiti's
        # entity/edge extraction & dedup prompts run at small/medium) routes to the
        # FAST tier; only genuinely large/quality calls stay 'strong'. This is a
        # no-op unless LLM_TIERED_ROUTING is on AND a fast model is configured
        # (llm_client._model_for_tier falls back to the main model otherwise), so
        # the default path is byte-identical.
        tier = "strong"
        if model_size in (ModelSize.small, ModelSize.medium):
            tier = "fast"

        loop = asyncio.get_event_loop()
        io_pool = get_graph_llm_io_pool()  # R2-EXEC-1: dedicated pool, not the shared default
        # Internal rising-temperature retry for the schema-echo failure mode: eager models
        # (e.g. MiniMax-M3) sometimes echo the injected JSON *schema* instead of a conforming
        # instance, and at temperature 0.0 they do so DETERMINISTICALLY — so graphiti's own
        # tenacity retry (same args) re-hits the identical schema every time and hard-fails the
        # whole graph build. Retrying here with rising temperature + a stronger nudge breaks the
        # determinism so a real instance is produced.
        #
        # GRAPH-11: cap the combined inner-retry budget at 2 attempts (was 3). With
        # graphiti's own tenacity retry on top (4 outer), 3 inner attempts multiplied
        # failure latency on a wedged op; one corrective retry at a higher temperature
        # still breaks the schema-echo determinism while bounding worst-case latency.
        temps = (0.0, 0.4)
        for attempt, temp in enumerate(temps):
            try:
                # ``ThreadPoolExecutor`` does not inherit ContextVars. Without
                # an explicit copy, graph calls lose pipeline/stage attribution
                # and accumulate in telemetry's cross-run ``_global`` bucket.
                call_context = contextvars.copy_context()
                result = await loop.run_in_executor(
                    io_pool,
                    call_context.run,
                    lambda t=temp: self._app_llm.chat_json(
                        msg_dicts, temperature=t, max_tokens=tokens, tier=tier
                    ),
                )
            except ValueError as exc:
                # Unparseable / empty JSON — retryable by graphiti's tenacity (4 attempts).
                raise EmptyResponseError(str(exc)) from exc
            except _TRANSIENT_LLM_ERRORS as exc:
                # Transient provider hiccups (timeouts, connection drops, 5xx, rate limits)
                # → graphiti's RateLimitError (exponential backoff) handles them.
                raise RateLimitError(str(exc)) from exc

            if not isinstance(result, dict):
                raise EmptyResponseError(f"Expected JSON object, got {type(result).__name__}")
            if self._looks_like_schema(result):
                # GRAPH-12: MiniMax-M3 sometimes wraps genuine extracted values inside a
                # schema-shaped envelope instead of a bare instance — e.g.
                # {"type": "object", "properties": {"name": "Elon Musk", ...}} where
                # `properties` already holds concrete values, not nested sub-schemas.
                # Salvage the call by unwrapping instead of burning a retry / hard-failing;
                # under concurrent graph-build load (GRAPH_BUILD_CONCURRENCY) the rising-
                # temperature retry budget (GRAPH-11) is the first thing to run out.
                unwrapped = self._try_unwrap_schema_echo(result, response_model)
                if unwrapped is not None:
                    logger.info(
                        "graphiti extraction: unwrapped schema-echo envelope into instance (tier=%s)",
                        tier,
                    )
                    result = unwrapped
            if not self._looks_like_schema(result):
                # JSON parsed and is not a schema echo. If a response_model is provided,
                # confirm it actually CONFORMS before returning — graphiti validates the
                # dict with ``response_model(**llm_response)`` *outside* its retry loop
                # (utils/maintenance/combined_extraction.py), so a schema-valid-but-
                # wrong-shaped reply hard-fails the whole graph build with no recovery.
                # MiniMax-M3 hits this: it returns ExtractedEdges missing the required
                # ``target_entity_name`` (and bleeds node-only keys like ``labels`` into
                # edges). Pre-validate here and retry with the concrete pydantic errors as
                # a corrective nudge (same rising-temperature trick as the schema-echo case).
                if response_model is not None:
                    try:
                        response_model(**result)
                    except Exception as ve:  # noqa: BLE001 — pydantic ValidationError / TypeError
                        if attempt < len(temps) - 1:
                            msg_dicts[-1] = {
                                "role": msg_dicts[-1]["role"],
                                "content": msg_dicts[-1]["content"]
                                + "\n\n(Your previous JSON did NOT conform to the required "
                                "schema. Validation errors:\n" + str(ve)[:900]
                                + "\nReturn a corrected JSON instance with EVERY required "
                                "field populated for EVERY item NOW. In particular each edge "
                                "MUST include source_entity_name, target_entity_name and "
                                "relation_type; do not put node-only fields on edges.)",
                            }
                            continue
                        raise EmptyResponseError(
                            f"LLM output failed {response_model.__name__} validation after "
                            f"temperature retries: {str(ve)[:300]}"
                        ) from ve
                if attempt:  # GRAPH-11: surface inner-retry counts to telemetry
                    logger.info(
                        "graphiti extraction succeeded after %d inner retr%s (tier=%s)",
                        attempt, "y" if attempt == 1 else "ies", tier,
                    )
                return result
            # Schema echo — strengthen the instruction and retry at a higher temperature.
            if attempt < len(temps) - 1:
                msg_dicts[-1] = {
                    "role": msg_dicts[-1]["role"],
                    "content": msg_dicts[-1]["content"]
                    + "\n\n(Your previous reply was the SCHEMA, not data. Output the concrete "
                    "JSON INSTANCE with the real extracted values NOW — no schema keywords.)",
                }
        # Still a schema after all temperatures — surface as retryable for graphiti's outer retry.
        raise EmptyResponseError("LLM returned a JSON schema instead of an instance (after temperature retries)")

    @staticmethod
    def _looks_like_schema(obj: dict) -> bool:
        if "$defs" in obj or "$schema" in obj:
            return True
        if obj.get("type") == "object" and "properties" in obj:
            return True
        return False

    @staticmethod
    def _try_unwrap_schema_echo(
        obj: dict, response_model: type[BaseModel] | None
    ) -> dict | None:
        """Best-effort salvage for a schema-echo envelope whose ``properties`` key
        already holds concrete extracted values (not nested sub-schema descriptors).
        Returns the unwrapped instance dict, or None if the envelope doesn't actually
        contain usable data (in which case the caller falls back to retrying)."""
        inner = obj.get("properties")
        if not isinstance(inner, dict) or not inner:
            return None
        for v in inner.values():
            if isinstance(v, dict) and ("type" in v or "$ref" in v or "properties" in v):
                return None  # still schema-shaped one level down — not real data
        if response_model is not None:
            try:
                response_model(**inner)
            except Exception:  # noqa: BLE001 — unwrap didn't actually conform, don't force it
                return None
        return inner
