# graphiti-client — Graphiti client package (FalkorDB driver, LLM adapter, embedder, runtime)

Slice: `backend/app/services/graphiti_client/` (9 files, 3,642 lines, all read line by line on branch `main`):

| File | Lines | Role |
|---|---|---|
| `__init__.py` | 33 | Pins `EMBEDDING_DIM` before graphiti imports, re-exports the Zep-compatible names |
| `client.py` | 357 | `Zep` facade: a drop-in `client.graph.*` surface that returns Zep-shaped wrapper objects |
| `compat.py` | 56 | `EpisodeData`, `EntityEdgeSourceTarget`, `ApiError`, `InternalServerError` |
| `ontology.py` | 47 | `EntityModel` / `EdgeModel` pydantic bases, `EntityText = str` |
| `cross_encoder.py` | 26 | `NoOpCrossEncoder` passthrough reranker |
| `embedder.py` | 362 | Local sentence-transformers embedder with a dedicated thread pool, an LRU cache, and a sqlite disk cache |
| `falkor_driver.py` | 99 | `SanitizingFalkorDriver`: JSON-encodes non-primitive property values before writes |
| `llm_adapter.py` | 275 | `AppGraphitiLLMClient`: graphiti `LLMClient` backed by the app's `LLMClient`, with schema-echo handling |
| `runtime.py` | 2,387 | `GraphitiRuntime` singleton: background event loop, backend selection, ingestion retry ladder, search, traversal, pagination workaround, merge/delete/GC primitives |

Installed upstream: `graphiti-core==0.29.2` (`backend/pyproject.toml:28`), `falkordblite>=0.5.0` (`backend/pyproject.toml:29`), `sentence-transformers>=3.0.0` (`backend/pyproject.toml:31`). Upstream behaviour quoted below was read from `backend/.venv/lib/python3.12/site-packages/graphiti_core/...` (cited as `site-packages/graphiti_core/...`).

---

## Purpose & position in the pipeline

- This package replaces the Zep Cloud SDK with a **local, in-process Graphiti temporal knowledge graph**, so no `ZEP_API_KEY` or external service is needed (`backend/app/services/graphiti_client/__init__.py:1-15`). Call sites only changed their import path from `zep_cloud` to `app.services.graphiti_client` (`__init__.py:6-14`).
- It serves the **GRAPH stage** (stage 3) of the pipeline. `graph_builder.py` creates the graph, sets the ontology, seeds actor triplets, ingests dossier chunks as episodes, and can build communities (`backend/app/services/graph_builder.py:1225`, `:1339`, `:1427-1531`, `:2351`, `:2451`). After that, `zep_entity_resolver.py` merges duplicate nodes (`backend/app/services/zep_entity_resolver.py:493-529`) and `graph_pruner.py` prunes the graph (`backend/app/services/graph_pruner.py:267-356`).
- It also serves **downstream readers**: profile generation (`oasis_profile_generator.py:984-1187`), the report agent's retrieval tools (`zep_tools.py:688`, `:1257`, `:2563`, `:2735-2756`), entity reading (`zep_entity_reader.py:299`, `:519`), simulation feedback writes (`zep_graph_memory_updater.py:423`, `:558`, `:583`), paging (`backend/app/utils/zep_paging.py:130`, `:201`), and stale-graph GC (`graph_builder.py:2834-2872`).
- Architecture: the synchronous Flask/pipeline threads call the facade (`client.py`). The facade calls `GraphitiRuntime` sync methods. Each sync method submits a coroutine to **one process-global asyncio loop on a daemon thread** (`runtime.py:187-192`, `:224-245`). [verifier: not every sync method — `set_ontology` and `pop_ingest_skip_reasons` run directly on the caller thread without `run()` or a timeout, mutating/reading `_ontologies` / `_ingest_skip_reasons` that the loop thread also uses (runtime.py:442-461, :589-591)] The coroutines drive `graphiti_core.Graphiti` instances, one cached per `graph_id` (`runtime.py:377-416`), on top of the FalkorDB/Kuzu drivers.
- `graph_id` is used verbatim as both the FalkorDB database/tenant name and the Graphiti `group_id` (`client.py:10`; `runtime.py:16-17`, `:337`, `:343`, `:406-410`).

---

## Walkthrough (source order)

### `__init__.py`

- **Module docstring** (`__init__.py:1-15`): the import migration map from `zep_cloud`.
- **`EMBEDDING_DIM` pin** (`__init__.py:22`): `os.environ["EMBEDDING_DIM"] = os.environ.get("GRAPHITI_EMBED_DIM", "384")`.
  - It always overwrites any pre-existing `EMBEDDING_DIM`.
  - It must run before any `graphiti_core` import, because `graphiti_core.embedder.client` freezes `EMBEDDING_DIM` at import (`site-packages/graphiti_core/embedder/client.py:23`). `search.py` uses that frozen value to build its zero search vector (`site-packages/graphiti_core/search/search.py:27,152`).
  - No module outside the slice imports `graphiti_core` directly. A grep found only comments in `backend/app/config.py:1261-1264`.
- **Re-exports** (`__init__.py:24-33`): `Zep`, `EpisodeData`, `EntityEdgeSourceTarget`, `InternalServerError`, `ApiError`. The ontology bases are imported from the submodule `graphiti_client.ontology` (`__init__.py:11-12`).

### `client.py` — Zep facade

- **`logger`** (`client.py:21`): the name is `mirofish.graphiti_client`.
- **`_iso(v)`** (`client.py:24-29`): converts a `datetime` to `isoformat()` and passes other values through. This restores the Zep contract that temporal fields are ISO strings (EXECPLAN F-2-2).
- **`_ZepNode(n)`** (`client.py:35-46`) copies these fields from a graphiti node:
  - `uuid_` and `uuid`: both set to `n.uuid or n.uuid_ or ""`.
  - `name`, `labels` (as a list), `summary`, `attributes` (as a dict).
  - `created_at`, converted with `_iso`.
  - It never raises on missing attributes, because it uses `getattr` defaults throughout.
- **`_ZepEdge(e)`** (`client.py:49-70`):
  - Fields: `uuid_`/`uuid`, `name`, `fact`, `fact_type` (= `name`), `source_node_uuid`, `target_node_uuid`, `attributes`, and the bi-temporal `created_at`, `valid_at`, `invalid_at`, `expired_at` (all converted with `_iso`).
  - `episodes` and `episode_ids` refer to the **same list object** (`client.py:68-70`).
- **`_ZepEpisode(uuid)`** (`client.py:73-80`): `uuid_`, `uuid`, and `processed=True` always, because Graphiti ingests synchronously.
- **`_SearchResult(edges, nodes)`** (`client.py:83-86`): a plain holder.
- **`_NodeNamespace`** (`client.py:92-110`):
  - `get(uuid_, graph_id=None)` calls `rt.get_node`. It returns a `_ZepNode`, or `None` if not found (`client.py:96-98`).
  - `get_by_graph_id(graph_id, limit=100, uuid_cursor=None)` calls `rt.list_nodes` and returns a list of `_ZepNode` (`client.py:100-104`).
  - `get_entity_edges(node_uuid, graph_id=None)` calls `rt.get_node_edges` and returns a list of `_ZepEdge` (`client.py:106-110`).
  - All methods swallow unknown kwargs via `**_`.
- **`_EdgeNamespace.get_by_graph_id`** (`client.py:113-121`): calls `rt.list_edges` and returns a list of `_ZepEdge`.
- **`_EpisodeNamespace.get`** (`client.py:124-130`): never touches the DB. It returns `_ZepEpisode(uuid_ or "")` with `processed=True`.
- **`_GraphNamespace`** (`client.py:133-346`) holds `node`, `edge` and `episode` sub-namespaces (`client.py:134-138`).
  - `create(graph_id, ...)` (`client.py:141-143`): calls `rt.create_graph`, which pre-warms the graph and builds indices. It returns `_ZepEpisode(graph_id)` as a truthy handle; `name` and `description` are ignored.
  - `set_ontology(graph_ids, entities, edges)` (`client.py:145-147`): calls `rt.set_ontology(gid, entities, edges)` for each id.
  - `delete(graph_id)` (`client.py:149-150`): calls `rt.delete_graph`.
  - `add_batch(graph_id, episodes)` (`client.py:153-198`):
    - Builds one dict per `EpisodeData`: `name=f"chunk-{i}"` (index within this batch), `data`, `type` (default `"text"`), `source_description="mirofish-text"`, `reference_time` (`client.py:154-163`).
    - Reads `Config.GRAPH_BUILD_CONCURRENCY`; any exception falls back to 1 (`client.py:166-171`).
    - If concurrency > 1 and there is more than one episode, it calls `rt.add_episodes_concurrent` (`client.py:172-174`). That call runs as **one** runtime op under one timeout, and any exception it raises propagates.
    - Otherwise it uses the serial loop (`client.py:175-198`): one `rt.add_episode` per episode. Exceptions are caught per episode, counted and logged, then skipped. Only truthy uuids are returned.
  - `add(graph_id, type, data)` (`client.py:200-208`): one episode named `"activity"` with `source_description="mirofish-activity"` and no `reference_time` (the runtime uses UTC now). Failures are **not** isolated and propagate to the caller.
  - `add_triplet(...)` (`client.py:210-290`):
    - If none of the extended kwargs are set (`deterministic_seed`, the attribute dicts, the three uuids, or the three `*_model_text` fields), it calls the runtime with the **legacy 10 positional args** (`client.py:243-268`), so it still works with legacy runtimes and test doubles.
    - Otherwise it passes everything as kwargs (`client.py:269-290`).
    - Returns the edge uuid.
  - `build_communities(graph_id)` (`client.py:292-294`) and `actor_graph_seed_state(graph_id)` (`client.py:296-298`): pass-throughs.
  - `_RERANKER_TO_RECIPE` (`client.py:304-314`): maps legacy `reranker` strings to recipe selectors: `rrf`, `mmr`, `node_distance` (plus 2 aliases), `cross_encoder` (plus 2 aliases), `combined`.
  - `search(graph_id, query, limit=10, scope="edges", reranker=None, recipe=None, center_node_uuid=None, bfs_origin_node_uuids=None, search_filter=None)` (`client.py:316-346`):
    - An explicit `recipe` wins. Otherwise the lower-cased `reranker` is mapped; unknown values map to `None`, which means the runtime default.
    - Calls `rt.search` and wraps the result in a `_SearchResult` of `_ZepEdge`/`_ZepNode`.
- **`Zep(api_key=None, **_)`** (`client.py:349-357`): stores `api_key`, which is ignored. Sets `self.graph = _GraphNamespace(get_runtime())`, so the **first construction anywhere starts the runtime thread**.

### `compat.py`

- **`EpisodeData`** dataclass (`compat.py:16-27`): `data: str`, `type: str = "text"`, `reference_time: Optional[datetime] = None`.
- **`EntityEdgeSourceTarget`** dataclass (`compat.py:30-36`): `source`, `target` (both optional strings).
- **`ApiError(message, status_code=None)`** (`compat.py:39-48`): documented as "effectively dead but importable" (`compat.py:43`).
- **`InternalServerError`** (`compat.py:51-56`): an empty `Exception` subclass. Neither exception is raised anywhere in `app/` or `scripts/`. They are only caught, at `zep_tools.py:736`, `scripts/export_demo_site_data.py:970` and `backend/app/utils/zep_paging.py:71`.

### `ontology.py`

- **`EntityModel(BaseModel)`** (`ontology.py:22-33`) and **`EdgeModel(BaseModel)`** (`ontology.py:36-42`): `model_config = {"extra": "ignore"}`. This drops undeclared LLM-invented attributes so that FalkorDB only receives the declared `Optional[str]` attributes.
- **`EntityText = str`** (`ontology.py:47`).
- `graph_builder` builds subclasses dynamically, for example `type(class_name, (EdgeModel,), attrs)` with `Optional[str]` annotations and `Field(description=..., default=None)` (`graph_builder.py:1300-1318`).

### `cross_encoder.py`

- **`NoOpCrossEncoder(CrossEncoderClient)`** (`cross_encoder.py:17-26`): `rank(query, passages)` returns `[(p, float(n - i))]`, which keeps the original order with descending placeholder scores. No model and no key are needed.
- The docstring notes that cross-encoder recipes can reach `rank`. That is why `runtime._search` degrades those recipes when the no-op is active (`cross_encoder.py:19-22`; `runtime.py:1666-1685`).

### `embedder.py`

- **Module constants** (`embedder.py:43-49`):
  - `DEFAULT_EMBED_MODEL` = env `GRAPHITI_EMBED_MODEL`, default `paraphrase-multilingual-MiniLM-L12-v2`.
  - `DEFAULT_EMBED_DIM` = env `GRAPHITI_EMBED_DIM`, default 384. Both are read from `os.environ` at import, not from `Config`.
  - `_MEM_CACHE_MAX = 50000`.
- **`get_embed_pool()`** (`embedder.py:61-79`): a lazily built, double-checked-locked, process-global `ThreadPoolExecutor(max_workers=_embed_workers(), thread_name_prefix="embed")`. It calls `_pin_compute_threads` first.
- **`_embed_workers()`** (`embedder.py:82-89`): `Config.EMBED_EXECUTOR_WORKERS`, default 4 (Config default `config.py:1250`). Any exception gives 4; the result is at least 1.
- **`_pin_compute_threads(workers)`** (`embedder.py:92-108`):
  - `os.environ.setdefault("OMP_NUM_THREADS", str(workers))`, then `torch.set_num_threads(workers)`, which is best-effort.
  - Runs once per process, guarded by the `_torch_pinned` flag.
  - This is **process-wide**: every torch user in the process is pinned.
- **`_normalize_text(text)`** (`embedder.py:111-117`): `" ".join(text.split())`. This is used for the cache key only. On a miss, the original text is encoded.
- **`_DiskEmbedCache(path)`** (`embedder.py:120-182`):
  - `__init__` creates the directory and opens `sqlite3.connect(path, check_same_thread=False)`, then runs `CREATE TABLE IF NOT EXISTS embeddings (k TEXT PRIMARY KEY, v BLOB NOT NULL)`. Any exception disables the cache (`embedder.py:129-145`).
  - `get_many(keys)` runs `SELECT k, v ... WHERE k IN (...)` in chunks of 400 under a lock and unpacks blobs with `struct.unpack(f"{n}f")` (native float32). Any error **permanently disables** the disk layer for this instance (`embedder.py:147-165`).
  - `put_many(items)` runs `INSERT OR REPLACE` with `executemany`, then commits. Any error disables the layer (`embedder.py:167-182`).
- **`_disk_cache_path()`** (`embedder.py:185-202`):
  - Takes `Config.EMBED_DISK_CACHE_PATH`. Only if Config cannot be imported does it fall back to env, defaulting to `uploads/graphiti_db/embed_cache.sqlite`.
  - A falsy value gives `None` (disabled). A relative path is anchored at `backend/`.
- **`LocalSentenceTransformerEmbedder(model_name=None, embedding_dim=None)`** (`embedder.py:205-362`):
  - `__init__` (`embedder.py:214-224`) sets the model name and dim, a lazy `_model`, `_lock`, the `_mem_cache` `OrderedDict` with `_mem_lock`, and a lazy disk cache.
  - `_ensure_model()` (`embedder.py:226-242`) is a double-checked lazy load.
    - If `hf_transfer` is not installed, it forces `HF_HUB_ENABLE_HF_TRANSFER=0` (`embedder.py:234-237`).
    - Then it calls `SentenceTransformer(self.model_name)`, which may **download from Hugging Face** on first use.
  - `_ensure_disk_cache()` (`embedder.py:244-251`): a lazy, one-time init.
  - `_cache_key(normalized)` (`embedder.py:253-258`): `sha256(model_name + b"\x00" + normalized).hexdigest()`.
  - `_mem_get` / `_mem_put` (`embedder.py:260-272`): LRU with move-to-end; evicts the oldest entries beyond 50,000.
  - `_raw_encode(texts)` (`embedder.py:274-282`): `model.encode(texts, normalize_embeddings=True, show_progress_bar=False)`. Each row is truncated to `embedding_dim` (`[: self.embedding_dim]`), but never padded.
  - `_encode(texts)` (`embedder.py:284-342`) is a three-tier lookup that preserves order and length:
    1. Memory LRU.
    2. Disk cache. A disk hit is accepted only if `len(vec) == embedding_dim`, and is then promoted to memory (`embedder.py:304-319`).
    3. Batch-encode the unique missing keys once, write them to memory and to disk (`embedder.py:321-339`).
    - Any slot still `None` becomes a zero vector (`embedder.py:341-342`).
  - `create(input_data)` (`embedder.py:344-356`) returns the embedding of the **first** input. A `str` is wrapped in a list; other iterables are converted with `str()` per element. An empty input returns a zero vector. Encoding runs on `get_embed_pool()` via `loop.run_in_executor`.
  - `create_batch(list)` (`embedder.py:358-362`) uses the same pool and returns all vectors. An empty input gives `[]`.

### `falkor_driver.py`

- **`_is_primitive(v)`** (`falkor_driver.py:28-30`): `None`, `str`, `int`, `float`, `bool`.
- **`_coerce_property_value(v)`** (`falkor_driver.py:33-50`):
  - Primitive: unchanged.
  - list/tuple of primitives: `list(v)`.
  - list containing non-primitives: JSON string.
  - dict: JSON string, using `ensure_ascii=False, default=str`.
  - datetime/date: unchanged, left to the base driver.
  - Anything else: `str(v)`.
- **`_sanitize_row`** (`falkor_driver.py:53-54`): coerces every value of one row dict.
- **`_sanitize_params(kwargs)`** (`falkor_driver.py:57-69`):
  - A non-empty list whose items are all dicts is treated as UNWIND rows and each row is sanitized.
  - A dict is treated as a single row and sanitized.
  - Everything else (scalars, uuid lists, `group_ids`) passes through.
- **`SanitizingFalkorSession.run(query, **kwargs)`** (`falkor_driver.py:72-80`):
  - For a batched `list[(cypher, params)]`, it sanitizes each params dict with `_sanitize_params`.
  - Otherwise it sanitizes the kwargs.
  - Upstream bulk writes go through `driver.session()` (`site-packages/graphiti_core/utils/bulk_utils.py:136`), and `driver.transaction()` also wraps `self.session()` (`site-packages/graphiti_core/driver/driver.py:147-163,213-219`). Both write paths are therefore covered.
- **`SanitizingFalkorDriver(FalkorDriver)`** (`falkor_driver.py:83-99`):
  - `session()` returns the sanitizing session.
  - `execute_query()` sanitizes kwargs. Upstream FalkorDB entity-node ops call `executor.execute_query(...)`, for example `site-packages/graphiti_core/driver/falkordb/operations/entity_node_ops.py:58`.
  - `clone(database)` returns `self` if `database` is the same; for the default group id `'_'` it returns a fresh sanitizing driver on the same client; otherwise a new sanitizing driver with that `database`. This keeps sanitization when graphiti clones the driver (`site-packages/graphiti_core/graphiti.py:1080-1082`).
  - `provider = GraphProvider.FALKORDB`.

### `llm_adapter.py`

- **`get_graph_llm_io_pool()`** (`llm_adapter.py:55-78`): a lazy, double-checked, process-global `ThreadPoolExecutor(max_workers=Config.GRAPH_LLM_EXECUTOR_WORKERS (default 64), thread_name_prefix="graphiti-llm")`. A `TypeError`/`ValueError` gives 64; the minimum is 1. This replaces asyncio's shared default pool, which is roughly `min(32, cpu+4)` (`llm_adapter.py:40-54`).
- **`_TRANSIENT_LLM_ERRORS`** (`llm_adapter.py:82-97`): openai `APITimeoutError`, `APIConnectionError`, `InternalServerError`, `RateLimitError`. It is an empty tuple if openai cannot be imported.
- **`AppGraphitiLLMClient(app_llm=None, max_tokens=8192)`** (`llm_adapter.py:100-112`):
  - Builds a graphiti `LLMConfig(api_key=Config.LLM_API_KEY or "local", model=Config.LLM_MODEL_NAME, base_url=Config.LLM_BASE_URL, max_tokens)`.
  - Calls `super().__init__(config, cache=False)`.
  - Wraps `app_llm`, defaulting to `AppLLMClient()`, i.e. the app's `backend/app/utils/llm_client.py:LLMClient`.
- **`_generate_response(messages, response_model=None, max_tokens=0, model_size=medium)`** (`llm_adapter.py:114-246`):
  1. Converts graphiti `Message` objects to `{"role", "content"}` dicts. Appends an anti-schema-echo instruction to the last message (`llm_adapter.py:123-136`). The JSON schema itself was already appended by graphiti's base `generate_response` (`site-packages/graphiti_core/llm_client/client.py:215-224`).
  2. Sets `tokens = max_tokens or 8192`.
  3. Computes the tier: `model_size` small or medium gives `"fast"`, anything else gives `"strong"` (`llm_adapter.py:145-147`). Graphiti 0.29.2's `ModelSize` only has `small` and `medium` (`site-packages/graphiti_core/llm_client/config.py:23-25`), so the tier is **always `fast`**.
  4. Loops over temperatures `(0.0, 0.4)` (`llm_adapter.py:162-163`). Each attempt runs `self._app_llm.chat_json(msg_dicts, temperature=t, max_tokens=tokens, tier=tier)` on the dedicated I/O pool inside `contextvars.copy_context().run`, which preserves telemetry attribution (`llm_adapter.py:165-175`).
     - A `ValueError` (unparseable JSON from `chat_json`, `backend/app/utils/llm_client.py:627`) is re-raised as graphiti `EmptyResponseError` (`llm_adapter.py:176-178`).
     - A transient openai error is re-raised as graphiti `RateLimitError` (`llm_adapter.py:179-182`).
     - Any other exception propagates raw. This includes the `RuntimeError` from CLI providers and `BudgetExceeded(RuntimeError)` (`backend/app/utils/telemetry.py:86`).
     - A non-dict result raises `EmptyResponseError` (`llm_adapter.py:184-185`).
     - If the result looks like a schema, it tries `_try_unwrap_schema_echo`. On success the inner dict replaces the result (`llm_adapter.py:186-200`).
     - If the result is not a schema and a `response_model` is given, it pre-validates with `response_model(**result)`. On failure at attempt 0, it appends the validation errors (truncated to 900 chars) plus an edge-field nudge and retries. On failure at the last attempt, it raises `EmptyResponseError("LLM output failed <Model> validation after temperature retries: ...")` (`llm_adapter.py:211-230`).
     - On success it returns the dict, logging the inner-retry count if non-zero (`llm_adapter.py:231-236`).
     - If it is still a schema echo, it appends a "you returned the SCHEMA" nudge and continues (`llm_adapter.py:238-244`).
  5. If the loop is exhausted, it raises `EmptyResponseError("LLM returned a JSON schema instead of an instance (after temperature retries)")` (`llm_adapter.py:246`).
- **`_looks_like_schema(obj)`** (`llm_adapter.py:248-254`): true if `$defs` or `$schema` is a key, or if `type == "object"` and a `properties` key is present.
- **`_try_unwrap_schema_echo(obj, response_model)`** (`llm_adapter.py:256-275`):
  - Returns `obj["properties"]` only if it is a non-empty dict and none of its values is a schema-like dict (one containing `type`, `$ref` or `properties`).
  - If a `response_model` is given, the inner dict must also validate.
  - Otherwise it returns `None`.

### `runtime.py`

**Module-level helpers**

- `_VALID_BACKENDS = ("auto", "falkordblite", "falkordb", "kuzu")` (`runtime.py:34`).
- Cooldown constants: default 15.0 s, maximum 60.0 s (`runtime.py:36-37`).
- **`_FACT_ATTR_RE`** (`runtime.py:47-53`): case-insensitive regexes for `sign=`, `strength=`, `lag=`, `polarity=`, `valence=`. Each value runs until whitespace, an ASCII or fullwidth comma, an ASCII or fullwidth closing parenthesis, or `、`. Each regex is prefixed with `\b`.
- **`_parse_edge_attrs(fact)`** (`runtime.py:56-65`): returns a dict of those five keys; any key not found is `None`.
- **`_edge_polarity_sign(attrs)`** (`runtime.py:68-97`):
  - A numeric `polarity` > 0 gives +1 and < 0 gives -1. Zero or non-numeric falls through to `sign`.
  - `sign` tokens `+`, `positive`, `pos`, `up`, `+1` give +1; `-`, `negative`, `neg`, `down`, `-1` give -1. A signed number also works.
  - Otherwise `None`.
- **`_lag_numeric(lag)`** (`runtime.py:100-110`): the first `-?\d+(\.\d+)?` in the token, unit-agnostic.
- **`_data_dir()`** (`runtime.py:113-125`): env `GRAPHITI_DATA_DIR`, then `Config.GRAPHITI_DATA_DIR`, then `backend/uploads/graphiti_db`. The path is made absolute and the directory is created (`os.makedirs`).
- **`_default_op_timeout()`** (`runtime.py:128-140`): `Config.GRAPHITI_OP_TIMEOUT_S`. The Config default is 900 (`config.py:1350`); if the attribute is missing the fallback is 1800. A value ≤ 0 means `None` (no cap). An exception gives 1800.
- **`_chunk_attempt_budget()`** (`runtime.py:143-160`): `Config.GRAPH_CHUNK_MAX_ATTEMPTS` (default 2, `config.py:1342`). A value ≤ 0 means `None` (uncapped). An exception gives 2.
- **`_graph_ingest_rate_limit_cooldown_s()`** (`runtime.py:163-181`): env `GRAPH_INGEST_RATE_LIMIT_COOLDOWN_S`, read directly and not via Config. Invalid values and NaN give 15. The result is clamped to [0, 60].

**`GraphitiRuntime.__init__`** (`runtime.py:187-219`)

- Creates `asyncio.new_event_loop()` and starts `threading.Thread(target=loop.run_forever, name="graphiti-loop", daemon=True)`.
- State:
  - `_graphs`: `graph_id` to `Graphiti`.
  - `_ontologies`: `graph_id` to `(entity_types, edge_types, edge_type_map)`.
  - Lazy clients: `_falkor_client`, `_embedder`, `_llm`, `_cross_encoder`.
  - `_ensure_lock`: created lazily.
  - `_graph_locks`: `graph_id` to `asyncio.Lock`.
  - `_resolved_backend`.
  - `_ingest_skip_reasons`: `graph_id` to `{reason: count}`.
  - `_fallback_llm`: `None` (not probed), `False` (unavailable), or a client.
  - `_fb_depth` and `_fb_primary`: refcounted LLM swap state.
- Registers `atexit` → `_shutdown`.

**Sync→async bridge and locks**

- **`run(coro, timeout=None)`** (`runtime.py:224-245`):
  - Calls `asyncio.run_coroutine_threadsafe(coro, loop)`, then `future.result(eff)`. `eff` is the `timeout` argument or `_default_op_timeout()`; a value ≤ 0 or `None` means wait forever.
  - On `concurrent.futures.TimeoutError` it calls `future.cancel()`. This cancels the asyncio task, so `async with lock` unwinds. It logs a warning and raises the built-in `TimeoutError("graphiti operation exceeded Ns")`.
- **`_graph_lock(graph_id)`** (`runtime.py:249-254`): a lazy per-graph `asyncio.Lock`. It is only touched on the loop thread. It is **non-reentrant**.
- **`_serialize_reads()`** (`runtime.py:256-267`): env `GRAPH_SERIALIZE_READS` set to `1`, `true`, `yes` or `on` turns it on. The default is `"0"` (off).
- **`_read_guard(graph_id)`** (`runtime.py:269-278`): an async context manager. It takes the per-graph write lock only when `_serialize_reads()` is on; otherwise it does nothing.

**Backend and driver construction**

- **`_resolve_backend()`** (`runtime.py:283-305`):
  - Reads env `GRAPH_BACKEND`, default `auto`. Invalid values become `auto` silently.
  - For `auto`, in order: if `FALKORDB_HOST` is set, use `falkordb`; else if `redislite.async_falkordb_client` is importable, use `falkordblite`; else if `kuzu` is importable, use `kuzu`; else raise `RuntimeError("No local graph backend available...")`.
  - The result is cached per process.
- **`_can_import(module)`** (`runtime.py:307-314`): `importlib.util.find_spec`, guarded against exceptions.
- **`_get_falkor_client()`** (`runtime.py:316-323`): lazily creates one `redislite.async_falkordb_client.AsyncFalkorDB(dbfilename=<data_dir>/falkor.db)` and caches it in `_falkor_client`. This starts an **embedded redis-server subprocess** via redislite (`site-packages/redislite/client.py:218-258`), which has its own `atexit` cleanup (`site-packages/redislite/client.py:448`).
- **`_make_driver(graph_id)`** (`runtime.py:325-356`):
  - `falkordb`: `SanitizingFalkorDriver(host=FALKORDB_HOST or localhost, port=FALKORDB_PORT or 6379, username, password, database=graph_id)`. This is a **new connection per graph**.
  - `falkordblite`: `SanitizingFalkorDriver(falkor_db=<shared embedded client>, database=graph_id)`.
  - `kuzu`: `KuzuDriver(db=<data_dir>/kuzu/<graph_id>)` with `driver._database = graph_id` pinned so graphiti does not clone it.
  - Anything else raises `RuntimeError`.
- **`_get_clients()`** (`runtime.py:358-375`): a one-time build of `LocalSentenceTransformerEmbedder()`, `AppGraphitiLLMClient()`, and the cross-encoder. The cross-encoder is `BGERerankerClient()` if env `GRAPHITI_RERANKER == "bge"`, otherwise `NoOpCrossEncoder()`. These three are **shared by all graphs**. The BGE client loads `BAAI/bge-reranker-v2-m3` synchronously (`site-packages/graphiti_core/cross_encoder/bge_reranker_client.py:36`).
- **`_ensure_graph(graph_id)`** (`runtime.py:377-416`):
  - Fast path: the instance is already cached. Otherwise it takes the global `_ensure_lock`, which serializes graph creation across **all** graph_ids, and re-checks.
  - Builds the driver and clients, then `Graphiti(graph_driver, llm_client, embedder, cross_encoder, max_coroutines=int(env GRAPHITI_MAX_COROUTINES or "16"))`. A `ValueError` gives 16.
  - Pins `g.driver._database = graph_id`.
  - Calls `await g.build_indices_and_constraints()`; exceptions are logged at debug level and ignored.
  - Caches the instance forever; there is no eviction.
- **`_candidate_graph_ids(graph_id)`** (`runtime.py:418-433`):
  - If `graph_id` is given, returns `[graph_id]`.
  - Else the list of cached graph ids.
  - Else (cold cache), only for falkordblite, `client.list_graphs()`.
  - Otherwise `[]`. On the server backend the cold path always gives `[]`, because the client variable is `None` there.

**Public write API**

- **`create_graph(graph_id)`** (`runtime.py:438-440`): `run(_ensure_graph)`.
- **`set_ontology(graph_id, entities, edges)`** (`runtime.py:442-461`), synchronous and in-memory only:
  - `entity_types = entities or None`.
  - For each edge `name → (Model, [EntityEdgeSourceTarget])`, or a bare model: `edge_types[name] = Model`, and `edge_type_map[(source or "Entity", target or "Entity")]` gets `name` appended.
  - If no source/target pairs are given, `edge_type_map = {("Entity", "Entity"): all edge names}`.
  - Stored in `_ontologies[graph_id]`.
- **`add_episode(graph_id, *, name, body, source_type, source_description, reference_time)`** (`runtime.py:463-482`) calls `run(_add_episode)`. `_add_episode` (`runtime.py:484-501`) takes the per-graph lock, then calls `_add_episode_locked`.
- **`_classify_ingest_error(exc)`** (`runtime.py:512-583`):
  - If an attached `_graphiti_ingest_reason` string exists, it wins.
  - Otherwise it walks up to 8 exceptions through `__cause__`/`__context__` and tenacity `last_attempt.exception()`, joins their lower-cased messages, and collects the type names.
  - First match wins, in this order:
    1. `schema_echo`: the message contains "schema instead of an instance" or "schema echo".
    2. `schema_validation`: "validation" plus "failed" or "error".
    3. `rate_limit`: "rate limit", "rate_limit" or "429" in the text, or "ratelimit" in a type name.
    4. `timeout`: a `TimeoutError` instance or "timeout" in the text.
    5. `content_filter`: "content" plus "filter" or "sensitive".
    6. `schema_parse`: `EmptyResponseError`/`JSONDecodeError` type names, or English/Chinese parse markers.
    7. `other`.
- **`_record_skip_reason`** / **`pop_ingest_skip_reasons(graph_id)`** (`runtime.py:585-591`): a counter per graph. `pop` returns a copy and clears it. It is read once per build by `graph_builder.py:2392`.
- **`_get_fallback_llm()`** (`runtime.py:593-625`): lazy, memoized.
  - Returns `None`, and memoizes `False`, if `Config.GRAPH_INGEST_FALLBACK` is false, or env `LLM_FALLBACK_PROVIDER` is empty or equal to `Config.LLM_PROVIDER`.
  - Otherwise builds `AppLLMClient(provider, model=LLM_FALLBACK_MODEL or None, api_key=LLM_FALLBACK_API_KEY or None, base_url=LLM_FALLBACK_BASE_URL or None)`, sets `_is_fallback = True` to block nested failover, and wraps it in `AppGraphitiLLMClient`.
  - Any exception gives a warning and memoizes `False`.
- **`_fallback_llm_swapped(graph_id, g)`** (`runtime.py:627-657`): an async context manager that yields `False` if no fallback exists.
  - On refcount 0→1 it saves `g.llm_client` in `_fb_primary`, sets the tracer, and replaces both `g.llm_client` and `g.clients.llm_client` with the fallback.
  - The `finally` decrements the count and restores the primary at 0. While the swap is active, **every concurrent episode on that graph uses the fallback**.
- **`_fallback_llm_available()`** (`runtime.py:659-664`): a probe that never raises.
- **`_add_episode_locked(..., record_skip_reason=True, attempt_budget=None)`** (`runtime.py:666-758`). The caller must hold the graph lock.
  - Setup:
    - `schema_retries = Config.GRAPH_EPISODE_SCHEMA_RETRIES` (default 1; an exception gives 1).
    - `budget = attempt_budget` or `_chunk_attempt_budget()`, clamped to at least 1.
    - `max_primary = min(1 + schema_retries, budget)`.
  - Primary loop (`runtime.py:703-726`): each attempt calls `_add_episode_once`.
    - A non-schema failure reason (`rate_limit`, `timeout`, `content_filter`, `other`) breaks after **one** attempt.
    - If `attempts_used == budget - 1` and a fallback exists, it stops early to reserve the last slot for the fallback.
  - Fallback pass (`runtime.py:729-747`): runs only if the reason is schema-related and the budget has room. It runs inside `_fallback_llm_swapped`. A failure sets the reason to `fallback_<cls>`.
  - On final failure (`runtime.py:749-758`): attaches `_graphiti_ingest_reason` and `_graphiti_ingest_attempts` to the exception, records the skip unless deferred, and re-raises the last exception. `CancelledError` is a `BaseException`, so it is not swallowed (`runtime.py:714`, `:744`).
- **`_add_episode_once(g, graph_id, ...)`** (`runtime.py:760-789`):
  - Maps `source_type` `text`/`json`/`message` to `EpisodeType`; the default is `text`. `reference_time` defaults to UTC now.
  - Calls `g.add_episode(name, episode_body, source_description or "mirofish", reference_time, source, group_id=graph_id, entity_types, edge_types, edge_type_map)` with the stored ontology, or `(None, None, None)` if none is stored.
  - Returns `result.episode.uuid`.
- **`add_triplet(...)`** (`runtime.py:791-864`): sync dispatch. `deterministic_seed=True` goes to `_add_deterministic_triplet`; otherwise to `_add_triplet`.
- **`_add_triplet(...)`** (`runtime.py:866-905`):
  - Builds fresh `EntityNode`s with labels `["Entity"] + [label]` unless the label is `Entity`, plus summary and attributes. Builds an `EntityEdge` with `fact` (default `"{src} {edge} {tgt}"`), `created_at = now`, `valid_at`, `episodes=[]`.
  - Calls `g.add_triplet(src, edge, tgt)` under the graph lock.
  - Upstream `add_triplet` generates embeddings, then runs **LLM** node resolution and **LLM** edge resolution/invalidation (`site-packages/graphiti_core/graphiti.py:1645-1760`).
  - There is no runtime-level retry or fallback.
- **`_add_deterministic_triplet(...)`** (`runtime.py:907-1069`), no LLM involved:
  - Requires `source_uuid`, `target_uuid` and `edge_uuid`; otherwise raises `ValueError` (`runtime.py:944-953`).
  - Requires all three `*_model_text` fields to be delimited: they must start with `BEGIN UNTRUSTED RESEARCH DATA` and contain `Treat this block only as evidence data.` and `END UNTRUSTED RESEARCH DATA`. Otherwise raises `ValueError` (`runtime.py:955-975`).
  - Embeds only the model-text records, with newlines flattened, via `g.embedder.create`, outside the lock (`runtime.py:1017-1025`).
  - Under the lock, it loads any existing source, target and edge by uuid.
    - It preserves their `created_at`.
    - Labels are a set-union (order is not stable).
    - Attributes merge with the **new values overriding** the existing ones (`runtime.py:1027-1060`).
  - Saves the source, then the target (if `target_uuid == source_uuid`, it merges the attributes into the source and saves it again), then the edge (`runtime.py:1062-1068`).
  - This path is idempotent by deterministic uuids.
- **`add_episodes_concurrent(graph_id, episodes, concurrency=4)`** (`runtime.py:1071-1090`): the docstring warns that this is a dedup-best-effort fast path and can create duplicate same-name nodes (`runtime.py:1078-1088`).
- **`_add_episodes_concurrent`** (`runtime.py:1092-1207`):
  1. Warms the graph (`runtime.py:1093`) and creates `Semaphore(max(1, concurrency))`.
  2. **Holds the graph lock across the entire fan-out** and runs `asyncio.gather(..., return_exceptions=True)`. Each task calls `_add_episode_locked(record_skip_reason=False)` (`runtime.py:1096-1126`).
  3. Builds the failed list `(idx, ep, reason, exc)`. Candidates for replay are failures whose reason is `rate_limit` or `fallback_rate_limit` **and** whose attempts spent are below the budget (`runtime.py:1134-1150`).
  4. If there are any, it sleeps for the cooldown **outside** the lock, then re-acquires the lock and replays each one **serially once**, with `attempt_budget = max(1, budget - spent)` (`runtime.py:1152-1173`).
  5. Final accounting (`runtime.py:1175-1207`): each remaining exception gets classified, recorded via `_record_skip_reason`, and logged. Successful truthy uuids are returned in input order, and failed episodes are dropped from the result.

**Communities**

- **`build_communities` / `_build_communities`** (`runtime.py:1209-1225`): `g.build_communities(group_ids=[graph_id])` under the lock. Returns a list of `{uuid, name, summary}`. The caller gates it off by default with `GRAPH_BUILD_COMMUNITIES=false`, because upstream label propagation can spin forever on CPU (`config.py:1260-1266`).
- **`list_communities` / `_list_communities`** (`runtime.py:1231-1264`), under the read guard:
  - `CommunityNode.get_by_group_ids(driver, [graph_id], limit=200)`; a failure returns `[]`.
  - Then the membership Cypher `MATCH (c:Community)-[:HAS_MEMBER]->(e:Entity) RETURN c.uuid, collect(e.name)`; a failure logs at debug level and leaves members empty.
  - Returns `{uuid, name, summary, members}`.

**Traversal**

- **`_asof_predicate(as_of)`** (`runtime.py:1269-1292`): `None`, empty or unparseable input gives `("", None)`. [verifier: nothing is parsed — any non-empty string is passed verbatim as `$as_of` and still yields the clause; only an exception from `str()` degrades to `("", None)`. The docstring's "unparseable value degrades" claim is itself drift (runtime.py:1274-1287)] Otherwise it returns the clause `AND all(x IN r WHERE (x.valid_at IS NULL OR x.valid_at <= $as_of) AND (x.invalid_at IS NULL OR x.invalid_at > $as_of))` and the ISO string. It iterates **`r`**, not `relationships(p)` (see Surprises).
- **`causal_paths(graph_id, source, target, edge_types=None, max_hops=4, limit=20, as_of=None)`** (`runtime.py:1294-1381`):
  - `hops` is clamped to [1, 6] and `limit` to [1, 100]; both are interpolated as literals.
  - The query is `MATCH p=(a:Entity)-[r:RELATES_TO*1..H]->(b:Entity) WHERE a.name=$src AND b.name=$tgt`, plus an optional `all(x IN relationships(p) WHERE x.name IN $types)` filter and the optional as-of clause. It returns node names, edge names and facts per path, with `LIMIT L`.
  - Paths with fewer than 2 nodes are skipped.
  - For each hop it parses the folded attributes, multiplies the known polarity signs, and sums the numeric lags.
  - Output per path: `{nodes, edges, hops, edge_details[{name, sign, strength, polarity, lag, fact}], net_polarity: "+"/"-"/None, lag_total: float|None}`.
  - Any exception (including from `_ensure_graph`) gives `[]`.
- **`n_hop_subgraph(graph_id, center, max_hops=2, edge_types=None, limit=60, as_of=None)`** (`runtime.py:1383-1440`):
  - `hops` is clamped to [1, 4] and `limit` to [1, 300].
  - Undirected `MATCH p=(a:Entity)-[r:RELATES_TO*1..H]-(b:Entity) WHERE a.name=$center ... UNWIND relationships(p) AS rel RETURN DISTINCT startNode(rel).name, rel.name, endNode(rel).name, rel.fact LIMIT L`.
  - Output rows: `{source, edge, target, sign, strength, polarity, lag, fact}`. Rows missing a source or target are dropped. Any exception gives `[]`.

**Search**

- **`_resolve_recipe(recipe, scope)`** (`runtime.py:1447-1491`):
  - The selector is the lower-cased recipe, default `rrf`.
  - `combined` gives `COMBINED_HYBRID_SEARCH_RRF`. `combined_<rrf|mmr|cross_encoder>` gives the combined twin; any other suffix falls back to combined RRF.
  - Otherwise it picks the node or edge table according to `scope == "nodes"` (any other scope means edges), with entries `rrf`, `mmr`, `node_distance`, `cross_encoder`. Unknown selectors give `rrf`.
- **`_to_search_filters(spec)`** (`runtime.py:1506-1602`):
  - A non-dict or empty spec gives `None`.
  - Recognized keys: `node_labels`, `edge_types`, `as_of`, `valid_at_before`/`_after`/`_at` (combined into one AND list), `invalid_at_is_null`/`_before`/`_after` (each its **own OR branch**).
  - `as_of` adds `valid_at <= as_of` to the AND list and sets `invalid_at` to the OR of `IS NULL` and `> as_of`. When `as_of` is set, the other `invalid_at_*` keys are ignored.
  - ISO strings may end in `Z`.
  - A dict with no recognized keys logs a warning and gives `None`. Any exception logs a warning and gives `None`.
  - Otherwise it returns `SearchFilters(**kwargs)`.
- **`search(...)`** (`runtime.py:1604-1629`): `run(_search(...))`.
- **`_default_recipe()`** (`runtime.py:1631-1645`): `Config.GRAPH_SEARCH_RECIPE` (default `rrf`, `config.py:347`), then env, then `rrf`.
- **`_search(...)`** (`runtime.py:1647-1704`):
  - The selector is the given recipe, or the default, or `rrf`.
  - `node_distance` without a `center_node_uuid` degrades to `rrf` (`runtime.py:1664-1665`).
  - `cross_encoder` or `combined_cross_encoder` degrades to `rrf` or `combined` when the active reranker is `NoOpCrossEncoder`. This is logged once per process via `_noop_ce_degrade_logged` (`runtime.py:1670-1685`).
  - It deep-copies the recipe config, sets `config.limit = limit`, builds the filters, and calls `g.search_(query, config=..., group_ids=[graph_id], center_node_uuid?, bfs_origin_node_uuids?, search_filter?)` under the read guard.
  - Returns `(list(edges), list(nodes))`.

**Pagination workaround and readers** (Wave9-KG; `runtime.py:1706-1716`)

- **`_list_uuids_ordered(g, graph_id, kind)`** (`runtime.py:1717-1739`):
  - Only `kind="node"` is allowed; anything else raises `ValueError`.
  - Runs `MATCH (n:Entity) RETURN n.uuid, n.group_id ORDER BY n.uuid DESC` with **no WHERE clause**.
  - Filters in Python to rows whose `group_id` is `graph_id` or `None`, and dedups while keeping order.
- **`_fetch_edges_unfiltered(g, graph_id, *, deduplicate=True)`** (`runtime.py:1741-1787`):
  - The match is `(n:Entity)-[e:RELATES_TO]->(m:Entity)`, or for Kuzu the reified `RelatesToNode_` form. The projection is graphiti's own `get_entity_edge_return_query(provider)`, ordered by `e.uuid DESC`, with no WHERE clause.
  - Each record is parsed with `get_entity_edge_from_record`; a bad record is skipped with a debug log.
  - Filters by group id in Python, optionally dedups by uuid, and re-sorts DESC.
- **`_page_after_cursor(uuids_desc, cursor, limit)`** (`runtime.py:1789-1806`):
  - No cursor: the first `limit`.
  - Cursor present in the list: the slice starting right after it.
  - Cursor missing (deleted or merged): starts after all uuids greater than the cursor. Paging is therefore monotonic and never wraps.
- **`list_nodes`** (`runtime.py:1808-1824`): ordered uuids, then the page, then `EntityNode.get_by_uuids(page)` (an IN predicate), re-sorted DESC.
- **`list_edges`** (`runtime.py:1826-1839`): a **full edge scan on every page**, then slices by cursor.
- **`get_node(uuid, graph_id=None)`** (`runtime.py:1841-1858`): tries each candidate graph with `EntityNode.get_by_uuid`. `NodeNotFoundError` and any other exception mean `continue`. Returns `None` if nothing is found.
- **`get_node_edges(node_uuid, graph_id=None)`** (`runtime.py:1860-1876`): `EntityEdge.get_by_node_uuid` (upstream uses `{uuid: $node_uuid}`, `site-packages/graphiti_core/edges.py:543-557`). Returns the first non-empty result across the candidate graphs, otherwise `[]`.
- **`all_entity_nodes(graph_id)`** (`runtime.py:1882-1912`): ordered uuids, fetched in batches of 500 with `get_by_uuids`. Returns dicts `{uuid, name, labels, summary, attributes}`; `attributes` was added so the resolver's alias detection works (`runtime.py:1904-1910`).
- **`all_entity_edges(graph_id)`** (`runtime.py:1914-1929`): the full edge scan, returned as dicts `{uuid, name, fact, source_node_uuid, target_node_uuid, attributes}`.
- **`actor_graph_seed_state(graph_id)`** (`runtime.py:1931-1983`): nodes and edges whose `attributes.seed_schema_version == "actor-graph-seed/v1"`. Edges are **not** deduplicated (`deduplicate=False`), so physical duplicates are retained. The result is sorted by uuid. It is used for strict manifest validation (`graph_builder.py:1586`).
- **`mention_counts(graph_id)`** (`runtime.py:1985-2008`): `MATCH (ep:Episodic)-[:MENTIONS]->(n:Entity) RETURN n.uuid, n.group_id, count(ep)`, filtered in Python. Any exception gives a warning and `{}`.
- **`embed_texts(texts)`** (`runtime.py:2010-2018`): `embedder.create_batch(texts)`, with `[]` for empty input.

**Mutations used by the resolver, pruner and GC**

- **`merge_nodes(graph_id, survivor_uuid, victim_uuid)`** (`runtime.py:2020-2205`), under the graph lock:
  - The same uuid gives `skipped: "same uuid"`. A load exception gives `skipped: "node load failed"`.
  - Seed protection (`runtime.py:2054-2100`):
    - If the victim is a seed `actor` and the survivor is not, the two are **swapped** (`swapped_for_seed=True`).
    - A victim of kind `entity_type` or `actor` is refused.
    - A victim of kind `actor_alias` may only merge into its canonical actor with the same `actor_id`.
  - Loads the victim's edges with `get_by_node_uuid` (a failure gives `[]`). If any seed `relationship` edge would become a self-loop, the merge is refused (`runtime.py:2111-2133`).
  - Rewires each touched edge onto the survivor (`runtime.py:2135-2166`):
    - Self-loops are dropped.
    - Non-seed edges get a **new uuid4**; seed edges keep their uuid.
    - Each edge is saved with `e.save(driver)`.
    - If a seed edge fails to rewire, it returns without deleting the victim (`runtime.py:2168-2176`).
  - Unions attributes (the survivor wins) and labels (order-preserving) onto the survivor and saves it (`runtime.py:2178-2191`).
  - Then `victim.delete(driver)` (DETACH DELETE).
  - Returns `{rewired, deleted, survivor_uuid, victim_uuid, swapped_for_seed}`.
- **`delete_entity_nodes(graph_id, uuids)`** (`runtime.py:2207-2244`):
  - Dedups the uuids and drops falsy ones. Under the graph lock, for each page of 200: `get_by_uuids`, then `n.delete` for each node.
  - Unloadable or missing uuids and per-node failures count as `failed`.
  - Returns `{requested, deleted, failed}`.
- **`list_graph_ids()`** (`runtime.py:2246-2278`):
  - falkordblite: `client.list_graphs()`.
  - falkordb server: a temporary `falkordb.asyncio.FalkorDB` connection, closed in `finally`.
  - Kuzu, or any failure: `[]`.
- **`graph_last_created_at(graph_id)`** (`runtime.py:2280-2309`):
  - falkordblite: a direct `select_graph(...).query("MATCH (n) RETURN max(n.created_at)")`, which avoids building a Graphiti instance.
  - Other backends: via `_ensure_graph`.
  - Returns an ISO string or `None` (also on error).
- **`delete_graph(graph_id)`** (`runtime.py:2311-2367`), under the graph lock:
  - Pops the cached graph and ontology.
  - Resolves a falkor client from the live driver's `client`, otherwise the shared embedded client. If it has `select_graph`, calls `select_graph(graph_id).delete()`; a failure is **logged, not raised**.
  - Closes the driver only if it does not wrap the shared embedded client.
  - The lock entry is deliberately kept (`runtime.py:2362-2367`).
- **`_shutdown()`** (`runtime.py:2370-2374`): `loop.call_soon_threadsafe(loop.stop)`. It does not close drivers.
- **`get_runtime()`** (`runtime.py:2377-2387`): a double-checked, `threading.Lock`-guarded module singleton.

---

## Control flow

1. **Startup.** `import app.services.graphiti_client` pins `EMBEDDING_DIM` (`__init__.py:22`), then imports `client.py`, which imports `runtime.py` (lightweight: no graphiti import at module level). The first `Zep(...)` call (for example `graph_builder.py:1072`, `zep_tools.py:495`) or `get_runtime()` call creates the loop thread (`client.py:357`; `runtime.py:2381-2387`).
2. **Graph creation.** `graph.create` → `create_graph` → `run(_ensure_graph)` (`client.py:141-143`; `runtime.py:438-440`). Inside, in order: `_resolve_backend` (`runtime.py:283`), `_make_driver` (`:325`), `_get_clients` (`:358`; embedder, LLM adapter and cross-encoder built on first use), `Graphiti(...)` (`:399-405`), `build_indices_and_constraints` (`:412`).
3. **Ontology.** `graph.set_ontology` → `rt.set_ontology` stores the in-memory tuple (`client.py:145-147`; `runtime.py:442-461`). Nothing is written to the DB.
4. **Seeding.** `graph.add_triplet` (`client.py:210-290`) → `rt.add_triplet` (`runtime.py:791-864`), which goes either to `_add_deterministic_triplet` (embed, then upsert under the lock, no LLM) or to `_add_triplet` (graphiti `add_triplet` with LLM resolution under the lock).
5. **Text ingest.** `graph.add_batch` (`client.py:153-198`):
   - With concurrency > 1 (Config default 4): `add_episodes_concurrent` (one `run` and one timeout for the whole batch) → `_add_episodes_concurrent` (lock held for the fan-out; semaphore) → `_add_episode_locked` per episode → `_add_episode_once` → `Graphiti.add_episode`. That calls `AppGraphitiLLMClient._generate_response` many times, bounded by graphiti's `max_coroutines` (16) [verifier: per `semaphore_gather` call, not globally — each call builds a fresh `asyncio.Semaphore(max_coroutines)`, so concurrent episodes multiply it (up to ~concurrency × 16); the effective process cap is the 64-thread `graphiti-llm` pool (site-packages/graphiti_core/helpers.py:123-133; config.py:1245-1247)], and `LocalSentenceTransformerEmbedder.create/create_batch` on the embed pool. Then the optional cooldown and serial rate-limit replay, then skip accounting.
   - Otherwise serial: `rt.add_episode` per episode, each its own `run`, lock and timeout (`runtime.py:463-501`).
   - Per extraction LLM call, the retry layers stack from outermost to innermost:
     - the chunk attempt budget, default 2 (`runtime.py:693-698`);
     - graphiti tenacity, 4 attempts with `wait_random_exponential(multiplier=10, min=5, max=120)` on `RateLimitError`, `EmptyResponseError`, `JSONDecodeError` and httpx 5xx (`site-packages/graphiti_core/llm_client/client.py:62-74,120-131`);
     - adapter temperatures (0.0, 0.4) (`llm_adapter.py:162`);
     - `chat_json` parse retries, 2 (`backend/app/utils/llm_client.py:613-627`);
     - `chat()` transport retries, `MAX_RETRIES = 3` plus provider failover (`backend/app/utils/llm_client.py:44`, `:459-500`).
6. **Audit.** `graph_builder` calls `pop_ingest_skip_reasons(graph_id)` after ingest (`graph_builder.py:2389-2392`).
7. **Post-build.** The resolver calls `all_entity_nodes` → `embed_texts` → `merge_nodes` (`zep_entity_resolver.py:496-529`). The pruner calls `all_entity_nodes`, `all_entity_edges`, `mention_counts`, then `delete_entity_nodes` (`graph_pruner.py:270-356`). Communities are optional (`graph_builder.py:2451`).
8. **Reads.** Readers call `graph.search` (`zep_tools.py:688`, which defaults to `reranker="cross_encoder"` (`zep_tools.py:681`) and is degraded to `rrf` by the runtime) → `_search`. Paging uses `node.get_by_graph_id` / `edge.get_by_graph_id` → `list_nodes` / `list_edges` (`zep_paging.py:130`, `:201`). Traversal uses `rt.causal_paths` and `rt.n_hop_subgraph` (`zep_tools.py:2735-2756`). Communities use `list_communities` (`zep_tools.py:2563`, `oasis_profile_generator.py:1102`).
9. **GC.** `graph_builder` calls `list_graph_ids` → `graph_last_created_at` per unreferenced graph → `graph.delete` → `delete_graph` (`graph_builder.py:2834-2872`).
10. **Shutdown.** `atexit` stops the loop (`runtime.py:219`, `:2370-2374`). redislite's own `atexit` stops the embedded redis-server (`site-packages/redislite/client.py:448`).

---

## Data & artifacts

| Artifact | Path pattern | Format / key fields | Writer / anchor |
|---|---|---|---|
| Embedded graph DB | `<GRAPHITI_DATA_DIR>/falkor.db` (default `backend/uploads/graphiti_db/falkor.db`) | Redis RDB with the FalkorDB module; one graph (tenant) per `graph_id`; nodes `Entity`/`Episodic`/`Community`, edges `RELATES_TO`/`MENTIONS`/`HAS_MEMBER` | `runtime.py:320-321` (redislite also creates socket/registry files; locations not verified) |
| Kuzu DB (fallback) | `<GRAPHITI_DATA_DIR>/kuzu/<graph_id>` | Kuzu file DB; edges reified as `RelatesToNode_` | `runtime.py:348-353`, `:1763-1765` |
| Embedding disk cache | `Config.EMBED_DISK_CACHE_PATH` (default `<GRAPHITI_DATA_DIR>/embed_cache.sqlite`, `config.py:1253-1256`) | sqlite table `embeddings(k TEXT PRIMARY KEY, v BLOB NOT NULL)`; `k = sha256(model ‖ 0x00 ‖ normalized_text)`; `v` = native float32 array | `embedder.py:138-140`, `:172-178`, `:253-258` |
| HF model cache | Hugging Face default cache | sentence-transformers model (and the BGE reranker if enabled) | `embedder.py:239-241`; `runtime.py:368-370` |
| Process env mutations | `EMBEDDING_DIM` (always set), `OMP_NUM_THREADS` (`setdefault`), `HF_HUB_ENABLE_HF_TRANSFER=0` (when `hf_transfer` is missing) | — | `__init__.py:22`; `embedder.py:101`, `:236-237` |

Persisted node and edge properties written by this slice (beyond graphiti's own):
- Seed attributes. `_add_deterministic_triplet` copies whatever `source_attributes`, `target_attributes` and `edge_attributes` dicts the caller passes (`runtime.py:985-1012`). `actor_graph_seed_state` and `merge_nodes` read `seed_schema_version == "actor-graph-seed/v1"`, `seed_kind ∈ {actor, actor_alias, entity_type, relationship}` and `actor_id` (`runtime.py:1949`, `:1965`, `:2054-2100`, `:2113-2116`).
- Causal attributes are **folded into `fact` text**, for example `sign=-, strength=high, lag=2w, polarity=-0.80`, by the graph builder and parsed back by regex (`runtime.py:39-53`).

Important in-memory structures:
- `_graphs`, `_ontologies`, `_graph_locks`, `_ingest_skip_reasons`, `_fb_depth`, `_fb_primary` (`runtime.py:194-218`). None are persisted; the ontology is lost on restart.
- Embedder `_mem_cache`, an LRU of at most 50,000 vectors per embedder instance (`embedder.py:49`, `:220`, `:267-272`).
- Pools: `graphiti-llm` (64) (`llm_adapter.py:55-78`) and `embed` (4) (`embedder.py:56-79`), both process-global.

Return shapes (facade): `_ZepNode` (`client.py:35-46`), `_ZepEdge` (`client.py:49-70`), `_ZepEpisode` (`client.py:73-80`), `_SearchResult` (`client.py:83-86`). Runtime dict shapes are listed in the Walkthrough (`runtime.py:1222-1225`, `:1256-1264`, `:1373-1380`, `:1430-1439`, `:1899-1911`, `:1922-1929`, `:1983`, `:2199-2205`, `:2244`).

---

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `GRAPHITI_EMBED_DIM` | `384` | Exported as `EMBEDDING_DIM` before the graphiti import; vector dimension and truncation length | `__init__.py:22`; `embedder.py:46` |
| `GRAPHITI_EMBED_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | sentence-transformers model, read from env at import | `embedder.py:43-45` |
| `EMBED_EXECUTOR_WORKERS` (Config) | `4` | Embed pool size; also the torch/OMP thread pin | `embedder.py:82-89`; `config.py:1250` |
| `EMBED_DISK_CACHE_PATH` (Config) | `<GRAPHITI_DATA_DIR>/embed_cache.sqlite` | sqlite cache location; relative paths are anchored to `backend/` | `embedder.py:185-202`; `config.py:1253-1256` |
| `GRAPH_LLM_EXECUTOR_WORKERS` (Config) | `64` | Graph LLM I/O pool size | `llm_adapter.py:59-78`; `config.py:1247` |
| `LLM_API_KEY` / `LLM_MODEL_NAME` / `LLM_BASE_URL` (Config) | provider-dependent | Graphiti `LLMConfig` metadata only (actual calls go through the app LLMClient) | `llm_adapter.py:104-109` |
| `LLM_TIERED_ROUTING` (Config, outside slice) | `True` | Makes the adapter's always-`fast` tier route to `LLM_FAST_MODEL` [verifier: only when `LLM_FAST_MODEL` is set (default unset → `Config.fast_model()` falls back to `LLM_MODEL_NAME`, config.py:96, :146-147) and only on OpenAI-compatible providers; CLI providers ignore tier (llm_client.py:369-374, :459-466). The fallback client always uses its own model (llm_client.py:368-369)] | `llm_adapter.py:145-147`; `config.py:92`; `llm_client.py:356-374` |
| `GRAPH_BUILD_CONCURRENCY` (Config) | `4` | Above 1, `add_batch` takes the concurrent fan-out path | `client.py:166-174`; `config.py:1240` |
| `GRAPHITI_MAX_COROUTINES` (env) | `16` (`config.py:1656` setdefaults the env from Config) | Graphiti intra-episode fan-out cap | `runtime.py:395-398` |
| `GRAPH_BACKEND` (env) | `auto` | `auto` / `falkordblite` / `falkordb` / `kuzu`; invalid values become `auto` | `runtime.py:286-305` |
| `FALKORDB_HOST` / `FALKORDB_PORT` / `FALKORDB_USERNAME` / `FALKORDB_PASSWORD` (env) | unset / `6379` / unset / unset | Server backend; under `auto`, a set host wins over embedded | `runtime.py:291-292`, `:331-337`, `:2263-2269` |
| `GRAPHITI_DATA_DIR` (env, then Config) | `backend/uploads/graphiti_db` | Location of the falkor.db and Kuzu files | `runtime.py:113-125`; `config.py:1021-1024` |
| `GRAPHITI_RERANKER` (env) | `rrf` | `bge` gives `BGERerankerClient`; anything else gives `NoOpCrossEncoder` | `runtime.py:366-374` |
| `GRAPHITI_OP_TIMEOUT_S` (Config) | `900` (fallback 1800) | Wall-clock cap per `run()`; ≤ 0 means unbounded | `runtime.py:128-140`, `:229-231`; `config.py:1350` |
| `GRAPH_CHUNK_MAX_ATTEMPTS` (Config) | `2` | Total full extraction passes per chunk, including fallback and replay; ≤ 0 means uncapped | `runtime.py:143-160`, `:693-698`, `:1134-1149`; `config.py:1342` |
| `GRAPH_EPISODE_SCHEMA_RETRIES` (Config) | `1` | Extra primary re-rolls on schema-type failures | `runtime.py:687-692`; `config.py:1324` |
| `GRAPH_INGEST_FALLBACK` (Config) | `True` | Enables the episode-level fallback-provider pass | `runtime.py:602-604`; `config.py:1326` |
| `LLM_FALLBACK_PROVIDER` / `_MODEL` / `_API_KEY` / `_BASE_URL` (env) | empty | Fallback client construction; disabled if empty or equal to the primary provider | `runtime.py:605-617` |
| `GRAPH_INGEST_RATE_LIMIT_COOLDOWN_S` (env only) | `15` (clamped 0–60) | Sleep before the serial 429 replay | `runtime.py:163-181`, `:1153-1160` |
| `GRAPH_SERIALIZE_READS` (env only) | `0` | Reads take the per-graph write lock | `runtime.py:256-278` |
| `GRAPH_SEARCH_RECIPE` (Config, then env) | `rrf` | Default retrieval recipe selector | `runtime.py:1631-1645`; `config.py:347` |

---

## External calls

| Target | Kind | Anchor |
|---|---|---|
| App `LLMClient.chat_json(..., tier=...)`, which reaches the claude-cli/codex-cli subprocess or the OpenAI-compatible HTTP providers | LLM (blocking, on the `graphiti-llm` pool) | `llm_adapter.py:169-175`; `backend/app/utils/llm_client.py:597-627` |
| Fallback `LLMClient(provider=LLM_FALLBACK_PROVIDER, ...)` | LLM | `runtime.py:612-619` |
| `graphiti_core.Graphiti.add_episode` / `add_triplet` / `search_` / `build_communities` / `build_indices_and_constraints` | Library (LLM, embedder and DB inside) | `runtime.py:778-788`, `:904`, `:1703`, `:1221`, `:412` |
| graphiti model helpers: `EntityNode`/`EntityEdge` `get_by_uuid(s)`, `get_by_node_uuid`, `save`, `delete`, `CommunityNode.get_by_group_ids` | DB via driver | `runtime.py:1029-1068`, `:1240`, `:1821`, `:1853`, `:1871`, `:1897`, `:2046-2047`, `:2103`, `:2161`, `:2189`, `:2195`, `:2228`, `:2238` |
| Raw Cypher via `driver.execute_query` (membership, causal paths, n-hop, uuid listing, edge scan, mention counts, max `created_at`) | DB | `runtime.py:1246-1249`, `:1336`, `:1420`, `:1733`, `:1770`, `:1997-2000`, `:2292-2294` |
| `redislite.async_falkordb_client.AsyncFalkorDB(dbfilename=...)`, which spawns an embedded redis-server subprocess | Subprocess and DB | `runtime.py:316-323`; `site-packages/redislite/client.py:218-258` |
| `falkordb.asyncio.FalkorDB(host, port, ...)`, a temporary connection for `GRAPH.LIST` | Network DB | `runtime.py:2261-2275` |
| `client.select_graph(g).query(...)` / `.delete()` | DB | `runtime.py:2297-2298`, `:2340-2341` |
| `SentenceTransformer(model_name)`, which may download from Hugging Face on first use | Network (one-time), CPU | `embedder.py:239-241` |
| `BGERerankerClient()`, which loads `BAAI/bge-reranker-v2-m3` (only when `GRAPHITI_RERANKER=bge`) | Network (one-time), CPU | `runtime.py:367-370` |
| `sqlite3` embed cache | Local file DB | `embedder.py:137-182` |
| `torch.set_num_threads` | Process-global setting | `embedder.py:102-105` |

---

## Cross-module edges

**Callers into this slice** (found by grep over `backend/app` and `backend/scripts`):

- `Zep` facade constructed by: `graph_builder.py:1072`, `zep_tools.py:495`, `oasis_profile_generator.py:384`, `zep_graph_memory_updater.py:248`, `zep_entity_reader.py:190`, `scripts/test_graphiti_migration.py:71`, `scripts/replay_zep_dead_letters.py:144`.
- Facade methods:
  - `graph.create` / `set_ontology` / `add_triplet` / `actor_graph_seed_state` / `add_batch` / `build_communities` / `delete`: `graph_builder.py:1225`, `:1339`, `:1427`, `:1476`, `:1500`, `:1531`, `:1586`, `:2351`, `:2451`, `:2872`.
  - `graph.add`: `zep_graph_memory_updater.py:423`, `scripts/replay_zep_dead_letters.py:90`.
  - `graph.add_triplet`: `zep_graph_memory_updater.py:558`, `:583`.
  - `graph.search`: `zep_tools.py:688`, `oasis_profile_generator.py:984`, `:1008`, `:1134`, `:1187`.
  - `graph.node.get`: `zep_tools.py:1257`, `zep_entity_reader.py:519` (both **without** `graph_id`).
  - `graph.node.get_entity_edges`: `zep_entity_reader.py:299` (no `graph_id`).
  - `graph.node.get_by_graph_id` / `graph.edge.get_by_graph_id`: `backend/app/utils/zep_paging.py:130`, `:201`.
- Direct `get_runtime()` users:
  - `zep_entity_resolver.py:493-529`: `all_entity_nodes`, `embed_texts`, `merge_nodes`.
  - `graph_pruner.py:267-356`: `all_entity_nodes`, `all_entity_edges`, `mention_counts`, `delete_entity_nodes`.
  - `graph_builder.py:2390-2392`: `pop_ingest_skip_reasons`.
  - `graph_builder.py:2831-2854`: `list_graph_ids`, `graph_last_created_at`.
  - `zep_tools.py:2562-2563`: `list_communities`.
  - `zep_tools.py:2725-2756`: `causal_paths`, `n_hop_subgraph`.
  - `zep_tools.py:986`: `get_runtime().run(embedder.create_batch(...))`, i.e. the public `run()` with a foreign coroutine.
  - `oasis_profile_generator.py:1101-1102`: `list_communities`.
  - `pipeline_orchestrator.py:12664-12665`: `all_entity_nodes`.
- Direct `LocalSentenceTransformerEmbedder()` constructions outside the runtime: `zep_tools.py:966-967` (MMR dedup), and `pipeline_orchestrator.py:11866-11871` (research-stage warm-up that calls the private `_encode` directly on a background thread).
- Ontology bases: `graph_builder.py:1238`. Compat types: `graph_builder.py:19-20`; `zep_tools.py:22`; `backend/app/utils/zep_paging.py:13`; `scripts/export_demo_site_data.py:965`.
- Tests importing the slice: `backend/tests/test_audit_fixes_report.py`, `test_faction_brief.py`, `test_graph_cost_containment.py`, `test_graph_actor_v1_seed.py`, `test_wave9_kg.py`, `test_zep_entity_resolver.py`, `test_export_demo_site_data.py`, `test_graph_optimizations.py` (8 files, found by grep).

**What this slice calls out to:**
- `app.config.Config`: `llm_adapter.py:34`; lazy imports at `client.py:167`, `embedder.py:84`, `:191`, `runtime.py:117`, `:136`, `:155`, `:600`, `:688`, `:1638`.
- `app.utils.llm_client.LLMClient`: `llm_adapter.py:33`, `runtime.py:609`.
- `graphiti_core` (`Graphiti`, nodes, edges, errors, search recipes and filters, LLM client base and errors, `EmbedderClient`, `CrossEncoderClient`, FalkorDB driver), `redislite`, `falkordb`, `kuzu`, `sentence_transformers`, `torch`, `openai` (error types only), `sqlite3`.

---

## Invariants, gates, validation

- **Single event loop.** All graphiti coroutines for all graphs run on one daemon thread (`runtime.py:188-192`). Calling `run()` from that thread would deadlock; there is no guard (`runtime.py:224-233`). [verifier: with the default 900 s cap it blocks the loop for the op timeout and then raises `TimeoutError`; it is a true deadlock only when `GRAPHITI_OP_TIMEOUT_S <= 0` (runtime.py:229-245)]
- **`group_id == driver._database`** is enforced after construction so graphiti never clones the driver in `add_episode` (`runtime.py:406-410`; upstream clone logic `site-packages/graphiti_core/graphiti.py:1077-1082`). Kuzu pins the same field (`runtime.py:353`). A `graph_id` must pass graphiti's `validate_group_id`: ASCII alphanumerics, `-` and `_` only (`site-packages/graphiti_core/helpers.py:136-160`).
- **Per-graph write serialization**:
  - Held by `_add_episode` (`runtime.py:493`), `_add_triplet` (`:903`), `_add_deterministic_triplet` (`:1027`), the entire concurrent fan-out (`:1123`), the replay (`:1163`), `_build_communities` (`:1220`), `_merge_nodes` (`:2044`), `_delete_entity_nodes` (`:2224`) and `_delete_graph` (`:2317`).
  - Reads take it only with `GRAPH_SERIALIZE_READS` on (`:262-278`).
  - Inside the concurrent fan-out, episodes on the **same** graph run in parallel, so name-dedup there is best-effort (`runtime.py:1078-1088`).
- **Lock registry is never pruned**, even on delete, so mutual exclusion is preserved (`runtime.py:2362-2367`).
- **Timeout ⇒ cancel.** Every sync op is bounded by `GRAPHITI_OP_TIMEOUT_S` and cancels its task on timeout, so held locks are released (`runtime.py:233-245`).
- **FalkorDB property primitives.** Every write through the sanitizing driver or session coerces dict values and lists of objects to JSON strings (`falkor_driver.py:33-80`). [verifier: coercion is one level deep — it applies to the values inside a dict-valued kwarg or inside each row of a non-empty all-dict list kwarg; a top-level kwarg that is a list holding non-dict non-primitives (or a mixed list) passes through unsanitized (falkor_driver.py:57-69). Upstream spreads `attributes` into the row dict, so attribute values are covered (site-packages/graphiti_core/driver/falkordb/operations/entity_node_ops.py:50-58)] Ontology models ignore extra fields (`ontology.py:33`, `:42`).
- **Deterministic seed gates.** All three uuids are required, and all three model-text records must carry the "UNTRUSTED RESEARCH DATA" delimiters. Only those delimited records are embedded (`runtime.py:944-975`, `:1014-1025`).
- **Seed identity protection in merges.** A canonical actor seed is never a victim; an `entity_type` seed is never a victim; an alias may only merge into its canonical actor; a seed relationship is never collapsed into a self-loop; a seed-edge rewire failure aborts the victim delete (`runtime.py:2054-2176`).
- **LLM output gates.** A non-dict raises `EmptyResponseError`. A schema echo is unwrapped or retried. With a `response_model`, the output must pass `response_model(**result)` before it is returned, because graphiti validates outside its retry loop (`llm_adapter.py:184-236`).
- **Embedding dimension.** A disk-cache hit is accepted only if `len(vec) == embedding_dim`. Freshly encoded vectors are truncated to `embedding_dim` (`embedder.py:280`, `:314`).
- **Pagination.** Uuid lists are deduped and the cursor never wraps (`runtime.py:1736-1739`, `:1789-1806`). Python-side group filtering applies everywhere the unfiltered scans are used (`runtime.py:1738`, `:1779-1781`, `:2004`).
- **Traversal safety.** Hop and limit values are clamped integers before interpolation into Cypher (`runtime.py:1311-1312`, `:1397-1398`). Names, types and `as_of` are passed as parameters.
- **Search filter degradation.** A malformed filter or one with no recognized keys gives no filter plus a warning, never an error (`runtime.py:1590-1602`).

---

## Failure modes & recovery

| Failure | Behaviour | Anchor |
|---|---|---|
| A single episode fails on the serial path | Logged and skipped; the batch continues; `graph_builder` counts the gap | `client.py:177-198`; `graph_builder.py:2365` |
| A single episode fails on the concurrent path | `gather(return_exceptions=True)` isolates it, then classification and final skip | `runtime.py:1124-1126`, `:1175-1191` |
| The whole concurrent batch exceeds `GRAPHITI_OP_TIMEOUT_S` | `TimeoutError` from `run`, which cancels the gather and every episode in it. The facade does not catch it, so `graph_builder` marks the **entire batch** failed (episodes already written stay in the DB but their uuids are lost) | `runtime.py:233-245`; `client.py:172-174`; `graph_builder.py:2371-2380` |
| Schema echo or validation failure | Inner temperature ladder, then graphiti tenacity ×4, then episode re-roll up to the budget (the last slot goes to the fallback provider if one exists), then skip with a reason | `llm_adapter.py:162-246`; `runtime.py:703-758` |
| 429 on the concurrent path | One serial replay after a 0–60 s cooldown, within the remaining budget | `runtime.py:1145-1173` |
| 429 / timeout on the serial path | No episode-level retry (break after the first attempt); inner layers only | `runtime.py:718-720` |
| Wedged LLM or DB call | Op timeout cancels the coroutine; **blocking threads in the `graphiti-llm` pool keep running** until the HTTP or CLI call returns (cancellation cannot interrupt them) | `runtime.py:242`; `llm_adapter.py:169-175` |
| CPU-bound synchronous code on the loop (for example graphiti label propagation) | Cannot be cancelled, so **every graph op in the process stalls**; mitigated only by the caller's gate `GRAPH_BUILD_COMMUNITIES=false` | `config.py:1260-1266`; `runtime.py:1221` |
| No backend importable | `RuntimeError` on first graph op | `runtime.py:297-302` |
| Disk embed cache error | Disables the disk layer for that embedder instance; memory LRU continues | `embedder.py:142-145`, `:162-164`, `:180-182` |
| Fallback LLM cannot be built | Warning; memoized as unavailable; retry ladder only | `runtime.py:622-625` |
| Read helpers fail (traversal, communities, mention counts, `last_created_at`) | Return `[]`, `{}` or `None` | `runtime.py:1309-1310`, `:1337-1339`, `:1241-1243`, `:2006-2008`, `:2307-2309` |
| `get_node` / `get_node_edges` errors | Swallowed per candidate graph; `None` or `[]` | `runtime.py:1854-1857`, `:1874-1876` |
| Graph delete fails | Logged as a warning; **not raised**, so callers count it as deleted | `runtime.py:2342-2343`; `graph_builder.py:2860-2862` |
| `merge_nodes` partial failure | Per-edge failures are logged; the survivor union is best-effort; a victim-delete failure leaves `deleted=False` | `runtime.py:2163-2198` |
| Process restart mid-build | Ontology (`_ontologies`) and skip counters are lost; graphs are re-opened lazily | `runtime.py:194-195`, `:215`, `:461` |

---

## Surprises

1. **Doc-vs-code drift: concurrency default.** `client.py:164-165` says "Default 1 → the serial path", and the `add_episodes_concurrent` docstring says the serial path is "the default" (`runtime.py:1075-1076`). But `Config.GRAPH_BUILD_CONCURRENCY` defaults to **4** (`config.py:1240`), so the concurrent fan-out path, with its documented dedup race, is the default. `ARCHITECTURE_MAP.md:221` also cites `GRAPH_BUILD_CONCURRENCY=1`.
2. **Doc-vs-code drift: backend order.** `ARCHITECTURE_MAP.md:226`, `ARCHITECTURE_MAP.md:674-676` and `DRF_ARCHITECTURE.md` §7.1 list "falkordblite → external FalkorDB → kuzu". The code checks `FALKORDB_HOST` **first** under `auto` (`runtime.py:290-296`). `.env.example:82` matches the code.
3. **Doc-vs-code drift: stale line anchors.** `ARCHITECTURE_MAP.md:38`, `:619` and `DRF_ARCHITECTURE.md:90` cite `runtime.py:180-201` for the bridge; the code is at `runtime.py:187-245`. `DRF_ARCHITECTURE.md` (section 7.1) cites `get_runtime()` at `:1796`; it is at `runtime.py:2381`. It also cites `Zep` at `client.py:292-300`; it is at `client.py:349-357`.
4. **Doc-vs-code drift: `GRAPHITI_MAX_COROUTINES` default.** `config.py:1652-1653` says runtime.py reads it with default `"8"`; the code default is `"16"` (`runtime.py:396`).
5. **Doc-vs-code drift: tier routing.** The model-size tier comment says it is "a no-op unless LLM_TIERED_ROUTING is on … so the default path is byte-identical" (`llm_adapter.py:139-144`). But `LLM_TIERED_ROUTING` defaults to `True` (`config.py:92`). Graphiti 0.29.2's `ModelSize` has only `small`/`medium`, so the `"strong"` branch is dead and graph extraction always requests the `fast` tier (`llm_adapter.py:145-147`; `site-packages/graphiti_core/llm_client/config.py:23-25`). [verifier: the comment's no-op condition is a conjunction ("LLM_TIERED_ROUTING is on AND a fast model is configured"). `LLM_FAST_MODEL` defaults to unset, so `fast_model()` resolves to `LLM_MODEL_NAME` and no fast-provider client is built; the default path really is unchanged. Only the `strong`-unreachable part is real drift (config.py:96, :146-147; llm_client.py:370-374, :922-929)]
6. **Doc-vs-code drift: disk cache cannot be disabled via env.** The embedder docstring says an empty `EMBED_DISK_CACHE_PATH` disables the disk layer (`embedder.py:186-188`). But `Config.EMBED_DISK_CACHE_PATH` uses `env.strip() or <default path>` (`config.py:1253-1256`), so an empty env still yields the default path whenever Config imports.
7. **Doc-vs-code drift: community algorithm.** `build_communities` says "Leiden" (`runtime.py:1210`, `:1228`). The Config comment states that upstream uses label propagation (`config.py:1261`).
8. **Suspected: `as_of` traversal predicate iterates `r` instead of `relationships(p)`** (`runtime.py:1288-1291`). The same file documents that FalkorDB types `r` as an Edge for length-1 matches, so `all(x IN r ...)` raises (`runtime.py:1316-1318`). Any `causal_paths` or `n_hop_subgraph` call with `as_of` would probably error, and the error is swallowed into `[]` (`runtime.py:1337-1339`, `:1421-1423`). This is latent: current callers do not pass `as_of` (`zep_tools.py:2735-2756`).
9. **Suspected: as-of semantics differ between search and traversal.** The search filter builds `e.valid_at <= $as_of` (`runtime.py:1546-1549`), which drops edges with NULL `valid_at` (upstream `date_filter_query_constructor`, `site-packages/graphiti_core/search/search_filters.py:107-117,149-178`). The traversal predicate treats NULL `valid_at` as valid (`runtime.py:1289`).
10. **Suspected: `invalid_at_before` + `invalid_at_after` together.** They become two OR branches (union, not window) (`runtime.py:1577-1586`). Upstream names each branch's parameter `invalid_at_{j}` with `j` the inner index, so both branches bind to `$invalid_at_0` and the last date wins (`site-packages/graphiti_core/search/search_filters.py:180-205`).
11. **Suspected: error classifier can misroute parse failures.** The classifier's text haystack includes `__cause__` messages. `chat_json`'s `ValueError` embeds up to 500 chars of raw LLM output (`backend/app/utils/llm_client.py:627`), and the adapter re-wraps it (`llm_adapter.py:176-178`). Any output containing `429`, `rate limit`, `timeout` or `validation … error` can therefore be classified `rate_limit`, `timeout` or `schema_validation` before the `schema_parse` check (`runtime.py:542-583`). That changes whether it is re-rolled, replayed or sent to the fallback. [verifier: only the `rate_limit` / `timeout` / `content_filter` misroutes change routing. `schema_validation` is in the same schema class as `schema_parse` (runtime.py:719, :729), so that misroute changes only the audit label]
12. **Suspected: runtime fallback client lacks LLMClient's misconfiguration guard.** `LLMClient._try_fallback` refuses an OpenAI-compatible fallback without `LLM_FALLBACK_MODEL`, because it would be a guaranteed 400 (`backend/app/utils/llm_client.py:535-550`), and it honours auth cooldowns (`:553-560`). `_get_fallback_llm` constructs the client unconditionally. With unset model, key or base URL, `LLMClient.__init__` inherits the **primary** `Config.LLM_MODEL_NAME`, `LLM_API_KEY` and `LLM_BASE_URL` (`backend/app/utils/llm_client.py:263-265`; `runtime.py:612-617`). This is duplicated logic that diverged.
13. **Suspected: graph deletion can silently no-op.**
    - On falkordblite in a fresh process with no prior graph op, `_falkor_client` is `None`, so no `select_graph(...).delete()` runs and no warning is logged (`runtime.py:2332-2343`).
    - The same happens on the server backend for a graph not cached in this process.
    - A Kuzu graph's files are never removed.
    - Delete exceptions are logged, not raised, so GC records the graph as deleted (`graph_builder.py:2860-2862`).
    - [verifier: on falkordblite the GC path is not affected by the fresh-process no-op, because GC first calls `list_graph_ids`, which populates `_falkor_client` (runtime.py:2255-2256; graph_builder.py:2834). The fresh-process no-op hits direct deletes such as `api/graph.py:713`. On the server backend, GC deletes of uncached graphs are silent no-ops, yet they are counted as `deleted` (runtime.py:2332-2338; graph_builder.py:2858-2862)]
14. **Suspected: inconsistent belief about falkordblite predicate bugs.**
    - Comments say even equality and `IN` predicates silently drop rows, for edges and for `group_id` (`runtime.py:1720-1727`, `:1750-1754`).
    - Yet nodes are still fetched via `get_by_uuids` (an `IN` predicate) (`runtime.py:1821`, `:1897`, `:1944`, `:2228`), which `:1714-1715` assumes unaffected.
    - `merge_nodes` and `get_node_edges` rely on `EntityEdge.get_by_node_uuid` (a property-map predicate) (`runtime.py:1871`, `:2103`).
    - If that predicate drops rows, a merge could miss victim edges, which `DETACH DELETE` then destroys.
    - [verifier: the comments limit the row-dropping to **edge**-property predicates ("对边属性的任何 WHERE 谓词", runtime.py:1750-1752). They explicitly assert that node equality/IN predicates are safe (runtime.py:1714-1715). Upstream `get_by_node_uuid` filters on the **node** property `(n:Entity {uuid: $node_uuid})` (site-packages/graphiti_core/edges.py:552-554), so by the code's own model it is safe. The tension is in `_list_uuids_ordered`, which cites edge evidence to avoid a node `group_id` predicate (runtime.py:1720-1724)]
15. **Suspected: merge leaves duplicates after an aborted seed rewire.** Non-seed edges are re-saved with **new uuids** before the victim delete (`runtime.py:2155-2161`). If a seed-edge rewire fails, the function returns without deleting the victim (`runtime.py:2168-2176`), leaving duplicated non-seed edges on the survivor and the victim. The same applies if `victim.delete` fails (`runtime.py:2194-2198`).
16. **`net_polarity` docstring promises `'?'`** (`runtime.py:1300`), but the code only emits `+`, `-` or `None`. Chains with some unknown hops still get a definite sign from the known hops (`runtime.py:1355-1372`), contrary to the helper's stated intent to "flag incomplete chains" (`runtime.py:71-73`).
17. **`list_edges` performs a full edge scan per page** (`runtime.py:1833-1839`), so `zep_paging`'s cursor loop is O(pages × E). `get_node` / `get_node_edges` without `graph_id` scan **every cached graph**, or on a cold falkordblite cache build a Graphiti instance plus indices for **every graph on disk** (`runtime.py:418-433`, `:1848-1857`). Two production callers omit `graph_id` (`zep_tools.py:1257`; `zep_entity_reader.py:299`, `:519`).
18. **Multiple embedder instances.** `zep_tools.py:967` and `pipeline_orchestrator.py:11867` each construct a separate `LocalSentenceTransformerEmbedder`. Each loads its own copy of the model and opens its own sqlite connection to the same cache file. A sqlite lock or write error permanently disables that instance's disk layer (`embedder.py:162-182`). `pipeline_orchestrator` calls the private `_encode` on its own thread, bypassing the embed pool.
19. **Process-wide side effects.** `torch.set_num_threads(EMBED_EXECUTOR_WORKERS)` pins torch for the whole process (`embedder.py:102-105`). The BGE reranker, when enabled, runs `predict` on asyncio's **default** executor, not the dedicated pools (`site-packages/graphiti_core/cross_encoder/bge_reranker_client.py:46`), and is constructed synchronously on the event loop (`runtime.py:367-370`).
20. **Dead compatibility surface.** `ApiError` and `InternalServerError` are never raised; the `except` branches that catch them are dead (`compat.py:39-56`; `zep_tools.py:736`; `scripts/export_demo_site_data.py:970`). [verifier: only `export_demo_site_data.py:970` (`except ApiError`) is wholly dead. `zep_tools.py:736` and `zep_paging.py:71` catch these types in a tuple with `ConnectionError`/`TimeoutError`/`OSError`, so those branches are live. `run()`'s `TimeoutError` lands in them (runtime.py:245); only the two compat members are dead] `_EpisodeNamespace.get` never checks the DB (`client.py:128-130`). `_ZepEdge.episodes` and `episode_ids` alias the same list (`client.py:68-70`).
21. **Episode names are not unique.** Each batch names its chunks `chunk-0..n` per batch (`client.py:156`; `runtime.py:1101`). Every simulation feedback episode is named `"activity"` (`client.py:203`).
22. **The ontology lives only in process memory** (`runtime.py:461`). A resumed ingest in a new process without a fresh `set_ontology` call extracts with no custom entity or edge types (`runtime.py:764-766`).
23. **`_merge_nodes` "node missing" branch is likely unreachable.** Upstream `EntityNode.get_by_uuid` raises `NodeNotFoundError` (which `_get_node` handles at `runtime.py:1854`), and here that error is caught by the generic `except` → `"node load failed"` (`runtime.py:2045-2052`).
24. **`_add_deterministic_triplet` attribute precedence is the reverse of `merge_nodes`.** The seed path lets new attributes override existing ones (`runtime.py:1044-1047`); the merge path lets the survivor win (`runtime.py:2182-2183`). Seed labels are merged through `set()`, so their order is non-deterministic (`runtime.py:1043`, `:1050`).
25. **`_parse_edge_attrs` uses `\b` before keys** (`runtime.py:48-52`). A key glued directly to a CJK character, as in `符号sign=…`, would not match, because CJK characters count as word characters in Python's Unicode regex. Low impact, since the builder writes `（sign=…`.

## Verification

Adversarial verification on branch `main` (2026-10-11). The verifier re-read all 9 slice files, the cited `config.py` / `llm_client.py` / `graph_builder.py` / caller lines, and upstream `graphiti_core` 0.29.2 under `backend/.venv`. It ran nothing beyond read-only greps.

**Verdict counts (34 checked):** 22 confirmed, 12 imprecise, 0 refuted, 0 unverifiable.
- The 15 key claims: 12 confirmed, 3 imprecise.
- The 15 key surprises: 10 confirmed, 5 imprecise.
- 4 extra statements from the Walkthrough, Control flow, Config table and Invariants: all 4 imprecise.
- 16 further spot-checks of the Walkthrough and Control flow were confirmed (listed at the end).

### Non-confirmed claims and corrections

1. **"Every sync runtime op goes through `run()`"** — imprecise.
   - `set_ontology` and `pop_ingest_skip_reasons` are synchronous and bypass `run()` and its timeout. They run on the caller thread and touch dicts the loop thread also uses (`runtime.py:442-461`, `:589-591`).
   - The rest of the claim holds: 900 s default, 1800 s when the attribute is missing or Config raises, ≤0 means no cap, and `future.cancel()` then the built-in `TimeoutError` (`runtime.py:128-140`, `:224-245`; `config.py:1350`).
2. **`SanitizingFalkorDriver` "JSON-encodes dict values and lists containing non-primitives in every kwarg"** — imprecise.
   - Coercion is one level deep. It reaches the values of a dict-valued kwarg and the values of each row in a non-empty all-dict list kwarg.
   - A top-level kwarg that is a mixed list, or a list of non-dict non-primitives, passes through unchanged (`falkor_driver.py:57-69`).
   - Upstream spreads `attributes` into the row dict, so entity attribute values are covered (`site-packages/graphiti_core/driver/falkordb/operations/entity_node_ops.py:50-58`).
   - The `clone()` part is confirmed (`falkor_driver.py:92-97`).
3. **"`list_edges` and `all_entity_edges` … page in Python with a cursor that never wraps"** — imprecise.
   - Only `list_edges` pages (`runtime.py:1836-1839`). `all_entity_edges` returns the whole scan (`runtime.py:1918-1929`).
   - `actor_graph_seed_state` also performs the full edge scan, with `deduplicate=False` (`runtime.py:1958-1962`).
4. **Surprise "llm_adapter comment says tier routing is a no-op by default"** — imprecise.
   - The comment's condition is a conjunction: routing on **and** a fast model configured.
   - `LLM_FAST_MODEL` defaults to unset, so `Config.fast_model()` returns `LLM_MODEL_NAME`. No fast-provider client is built either, so the default path is unchanged (`config.py:96`, `:146-147`; `llm_client.py:370-374`, `:922-929`).
   - The real drift is limited to the `strong` branch being unreachable (`llm_adapter.py:145-147`; `site-packages/graphiti_core/llm_client/config.py:23-25`).
5. **Surprise "classifier misroutes … changes retry, replay and fallback routing"** — imprecise.
   - The `rate_limit`, `timeout` and `content_filter` misroutes do change routing.
   - A misroute to `schema_validation` stays in the same schema class as `schema_parse` (`runtime.py:719`, `:729`), so only the audit label changes.
6. **Surprise "`delete_graph` silently no-ops … GC then counts the graph as deleted"** — imprecise.
   - On falkordblite, GC calls `list_graph_ids` first, which creates `_falkor_client` (`runtime.py:2255-2256`; `graph_builder.py:2834`). GC deletes therefore do run there.
   - The fresh-process no-op affects direct deletes (`api/graph.py:713`).
   - On the server backend, GC deletes of uncached graphs are silent no-ops that are still recorded as `deleted` (`runtime.py:2332-2338`; `graph_builder.py:2858-2862`).
   - Kuzu graph files are never removed: `KuzuDriver.client` has no `select_graph` (`site-packages/graphiti_core/driver/kuzu_driver.py:157`).
7. **Surprise "comments say falkordblite drops rows for equality and IN predicates, yet … `get_by_node_uuid`"** — imprecise.
   - The comments scope the drop to **edge**-property predicates (`runtime.py:1750-1752`) and assert that node equality/IN predicates are safe (`runtime.py:1714-1715`).
   - `get_by_node_uuid` filters on a node property (`site-packages/graphiti_core/edges.py:552-554`).
   - The real inconsistency is that `_list_uuids_ordered` uses edge evidence to avoid a node `group_id` predicate (`runtime.py:1720-1724`).
8. **Surprise "`ApiError`/`InternalServerError` … their except branches are dead"** — imprecise.
   - Only `scripts/export_demo_site_data.py:970` is wholly dead.
   - `zep_tools.py:736` and `utils/zep_paging.py:71` catch these types together with `ConnectionError`/`TimeoutError`/`OSError`. Both branches are live and receive `run()`'s `TimeoutError` (`runtime.py:245`).
   - The other dead-surface items are confirmed: `episode.get` never touches the DB (`client.py:128-130`); `net_polarity` never emits `'?'` (`runtime.py:1300` vs `:1372`); the ontology is in-memory only (`runtime.py:461`); episode names are per-batch `chunk-<i>` or `activity` (`client.py:156`, `:203`).
9. **Walkthrough `_asof_predicate`: "unparseable input gives `("", None)`"** — imprecise.
   - No parsing happens: any non-empty string is bound verbatim as `$as_of`. Only an exception from `str()` degrades. The function's own docstring drifts the same way (`runtime.py:1274-1292`).
10. **Control flow step 5: LLM calls "bounded by graphiti's `max_coroutines` (16)"** — imprecise.
    - `semaphore_gather` creates a fresh semaphore per call (`site-packages/graphiti_core/helpers.py:123-133`), so the 16 does not bound the process.
    - With concurrent episodes the in-flight count can reach about concurrency × 16. The real cap is the 64-thread `graphiti-llm` pool (`llm_adapter.py:59-78`; `config.py:1245-1247`).
11. **Config table `LLM_TIERED_ROUTING`: "routes the always-`fast` tier to `LLM_FAST_MODEL`"** — imprecise.
    - This happens only when `LLM_FAST_MODEL` is set, and only on OpenAI-compatible providers (`config.py:146-147`; `llm_client.py:370-374`, `:459-466`).
    - The runtime fallback client always uses its own model (`llm_client.py:368-369`).
12. **Invariants: "Calling `run()` from the loop thread would deadlock"** — imprecise.
    - With the default 900 s cap it stalls the loop for the timeout and then raises `TimeoutError`. It is a true deadlock only when `GRAPHITI_OP_TIMEOUT_S <= 0` (`runtime.py:229-245`).

### Confirmed key claims and surprises (one-line evidence)

**Key claims:**
- Backend order under `auto`, with invalid values silently becoming `auto` (`runtime.py:286-302`).
- A `Graphiti` instance is cached per graph with no eviction other than `delete_graph`, built with `max_coroutines` from env (default 16), with `_database` pinned and index errors logged at debug (`runtime.py:377-416`, `:2318`).
- `add_batch` takes the concurrent path when Config is above 1 (default 4) and there are more than 1 episodes (`client.py:166-174`; `config.py:1240`).
- Attempt budget and fallback-slot reservation (`runtime.py:690-747`). Caveat: with `GRAPH_CHUNK_MAX_ATTEMPTS=1` the fallback never runs.
- The rate-limit replay (`runtime.py:1134-1173`, `:163-181`).
- Temperatures, error mapping and tenacity 4× (`llm_adapter.py:162-182`; `site-packages/graphiti_core/llm_client/client.py:62-74`, `:120-141`).
- `response_model` pre-validation and envelope unwrap (`llm_adapter.py:186-236`, `:256-275`).
- The tier is always `fast` (`llm_adapter.py:145-147`).
- Pools are 64 and 4 workers, with `copy_context` and a process-wide torch pin (`llm_adapter.py:59-78`, `:165-175`; `embedder.py:61-108`).
- Embedder defaults, cache key, and the three-tier lookup (`embedder.py:43-49`, `:120-182`, `:253-342`).
- Search degradation (`runtime.py:1663-1686`, `:1447-1491`).
- `delete_graph` mechanics (`runtime.py:2314-2360`).

**Surprises:**
- Concurrency default drift (`client.py:164-165`; `runtime.py:1075-1076`; `ARCHITECTURE_MAP.md:221`).
- Backend-order and anchor drift (`ARCHITECTURE_MAP.md:38`, `:226`, `:619`, `:674-676`; `DRF_ARCHITECTURE.md:90`, `:611`, `:624`, `:639-642`; `.env.example:82`).
- The `EMBED_DISK_CACHE_PATH` docstring, and `config.py:1652-1653` claiming `"8"` (`config.py:1253-1256`; `runtime.py:396`).
- `all(x IN r …)` in `_asof_predicate`. No caller passes `as_of`: `zep_tools.py:2735-2756` do not, and `kg_server.py:149` uses search filters, not traversal.
- As-of NULL semantics and the shared `$invalid_at_0` binding (`site-packages/graphiti_core/search/search_filters.py:107-117`, `:149-205`).
- The fallback guard gap (`llm_client.py:263-265`, `:535-560`; `runtime.py:605-619`).
- Merge duplicates after an abort (`runtime.py:2155-2198`).
- One op and one timeout per concurrent batch (`runtime.py:233-245`, `:1123-1126`; `graph_builder.py:2371-2376`).
- `list_edges` O(pages×E) and graph-id-less lookups (`runtime.py:418-433`, `:1836`; `zep_tools.py:1257`; `zep_entity_reader.py:299`, `:519`).
- Separate embedder instances (`zep_tools.py:966-967`; `pipeline_orchestrator.py:11866-11870`).

### Omissions (significant behaviour the map does not cover)

1. **Kuzu merges can destroy inbound edges.**
   - On Kuzu, upstream `EntityEdge.get_by_node_uuid` matches only `(n)-[:RELATES_TO]->(e:RelatesToNode_)-[:RELATES_TO]->(m)`, i.e. outgoing edges (`site-packages/graphiti_core/edges.py:555-558`). FalkorDB's match is undirected (`:552-554`).
   - `merge_nodes` (`runtime.py:2103`) therefore never sees edges where the victim is the **target**. `victim.delete` then DETACH-DELETEs them (`runtime.py:2195`).
   - `get_node_edges` likewise returns only outgoing edges on Kuzu (`runtime.py:1871`).
2. **Fan-out and timeout scope are set by the caller's batch size.**
   - The pipeline ingests with `batch_size=10` (`pipeline_orchestrator.py:12545`) and the API with `batch_size=3` (`api/graph.py:438`). `graph_builder` runs the batches sequentially (`graph_builder.py:2331-2353`).
   - Effective concurrency is therefore `min(GRAPH_BUILD_CONCURRENCY, batch)`. Each 900 s `run()` covers at most 10 episodes plus the 0-60 s cooldown and the serial replay (`runtime.py:1090`, `:1152-1173`).
3. **A timed-out concurrent batch leaves no skip-reason audit.**
   - Per-episode accounting is deferred (`record_skip_reason=False`, `runtime.py:1106`). The final accounting loop (`runtime.py:1175-1191`) is cancelled together with the op.
   - As a result, `pop_ingest_skip_reasons` (`graph_builder.py:2392`) has no entry for a batch that `graph_builder` counts as entirely failed (`graph_builder.py:2371-2376`).

### Further spot-checks confirmed

- The `EMBEDDING_DIM` pin always overwrites (`__init__.py:22`).
- No `graphiti_core` import exists outside the slice (grep over `app/` and `scripts/`).
- The legacy 10-positional `add_triplet` dispatch (`client.py:243-268`).
- `_disk_cache_path` uses the env only when Config cannot be imported (`embedder.py:190-195`).
- The cold server-backend path in `_candidate_graph_ids` returns `[]` (`runtime.py:426-430`).
- The `"node missing"` branch is unreachable, because `get_by_uuid` raises `NodeNotFoundError` (`site-packages/graphiti_core/nodes.py:605`; `runtime.py:2045-2052`).
- Seed and merge attribute precedence are reversed (`runtime.py:1044-1047` vs `:2182-2183`).
- The monotonic cursor (`runtime.py:1789-1806`).
- `list_communities` uses `limit=200` (`runtime.py:1240`).
- Traversal clamps (`runtime.py:1311-1312`, `:1397-1398`).
- `as_of` overrides the `invalid_at_*` keys (`runtime.py:1565-1586`).
- BGE `predict` runs on the default executor (`bge_reranker_client.py:46`).
- Upstream `add_triplet` performs LLM resolution (`site-packages/graphiti_core/graphiti.py:1658-1741`).
- `zep_tools` search defaults to `reranker="cross_encoder"` (`zep_tools.py:681`).
- Whole-batch failure accounting (`graph_builder.py:2371-2380`).
- Eight test files import the slice.
