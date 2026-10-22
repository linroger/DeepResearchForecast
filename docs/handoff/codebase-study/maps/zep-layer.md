# zep-layer — Zep-compatible entity reader/resolver/memory updater/tools and paging/rate-limit utils

Slice (branch `main`, read in full from disk on 2026-10-11):

| File | Lines | Role |
|---|---|---|
| `backend/app/services/zep_entity_reader.py` | 613 | Reads typed entity nodes and their edges back out of the graph so PREPARE can build agent profiles. Also applies the ontology "tier gate". |
| `backend/app/services/zep_entity_resolver.py` | 542 | Post-build entity resolution: clusters duplicate entity nodes and merges them into the `actors.json` canonical name. |
| `backend/app/services/zep_graph_memory_updater.py` | 719 | Simulation → graph feedback writer: a queue/worker that writes agent actions as episodes, plus a dead-letter file. Off by default. |
| `backend/app/services/zep_tools.py` | 2854 | `ZepToolsService`, the retrieval toolkit the ReACT report agent, the MCP KG server and two report API routes call. |
| `backend/app/utils/zep_paging.py` | 247 | Cursor-paged full reads of nodes and edges, with per-page retry and uuid de-duplication. |
| `backend/app/utils/zep_rate_limit.py` | 52 | Detects Zep-Cloud-style HTTP 429 errors and computes the delay before a retry. |

**Anchor convention.** `zep_entity_reader.py:N`, `zep_entity_resolver.py:N`, `zep_graph_memory_updater.py:N` and `zep_tools.py:N` mean `backend/app/services/<file>:N`. `zep_paging.py:N` and `zep_rate_limit.py:N` mean `backend/app/utils/<file>:N`. Every other anchor is a full path relative to the repo root.

**Naming heritage.** None of this talks to Zep Cloud any more. `Zep` is imported from `backend/app/services/graphiti_client`. That is a drop-in facade over a process-global local Graphiti runtime (FalkorDB/falkordblite) (`backend/app/services/graphiti_client/__init__.py:1-14`, `backend/app/services/graphiti_client/client.py:349-357`). `Zep(api_key=...)` accepts the key and ignores it (`backend/app/services/graphiti_client/client.py:350-357`). `Config.ZEP_API_KEY` defaults to the sentinel `'local-graphiti'`, so the `if not self.api_key: raise ValueError` guards in this slice always pass (`backend/app/config.py:1034-1038`).

---

## Purpose & position in the pipeline

This slice is the graph read/write layer between the knowledge graph (built in the GRAPH stage) and the later stages:

1. **GRAPH stage tail: entity resolution.** After the graph build and community detection, `pipeline_orchestrator` calls `resolve_entities(graph_id, actors)` when `Config.GRAPH_RESOLVE_ENTITIES` is true (`backend/app/services/pipeline_orchestrator.py:12590-12609`). The default is **true** (`backend/app/config.py:1282`). It merges duplicate nodes (for example "China"/"CCP"/"Beijing") into the dossier canonical. The audit goes to `handoff/entity_merges.json` (`backend/app/services/pipeline_orchestrator.py:12599-12603`). `graph_pruner` reuses this slice's `canonical_norm_set` and `actor_alias_map` as its own "core set" definition (`backend/app/services/graph_pruner.py:31,58-60`).
2. **PREPARE stage: entity read-back.** `SimulationManager.prepare_simulation` builds a `ZepEntityReader` and calls `filter_defined_entities(graph_id, defined_entity_types, enrich_with_edges=True)` (`backend/app/services/simulation_manager.py:916-924`). The resulting `EntityNode`s (with `related_edges`/`related_nodes`) go through dossier stand-ins and agent-pool selection, then into the OASIS profile generator. That generator turns the neighbor edges and nodes into persona context (`backend/app/services/oasis_profile_generator.py:1258-1312`). The orchestrator also uses the reader as a cheap "does the reused graph have >0 entities" health check (`backend/app/services/pipeline_orchestrator.py:12431-12437`).
3. **RUN stage: optional feedback loop.** If the run's pinned safety policy `sim_graph_feedback` is true (default `Config.SIM_GRAPH_FEEDBACK=false`, `backend/app/config.py:1385`), the orchestrator passes `enable_graph_memory_update=True` (`backend/app/services/pipeline_orchestrator.py:8803-8807`) [verifier: 8803-8807 is the ensemble-seed path inside `_run_one_seed` (backend/app/services/pipeline_orchestrator.py:8762); the main RUN start is backend/app/services/pipeline_orchestrator.py:12985-12989. Separately, `POST /api/simulation/start` reads `enable_graph_memory_update` straight from the request body with no `SIM_GRAPH_FEEDBACK` or pinned-policy check, so the updater can also run outside the policy (backend/app/api/simulation.py:1540,1621-1645)]. `SimulationRunner` then creates a `ZepGraphMemoryUpdater` (`backend/app/services/simulation_runner.py:860`) and feeds it every parsed action-log line (`backend/app/services/simulation_runner.py:1279-1280`). Batches that fail for good are dead-lettered to `uploads/simulations/_zep_dead_letter/<graph_id>.jsonl`. RUN health counts that file (`backend/app/services/pipeline_orchestrator.py:9412-9441`), and `backend/scripts/replay_zep_dead_letters.py` replays it.
4. **REPORT stage: retrieval tools.** `ReportAgent` builds one `ZepToolsService` per agent (`backend/app/services/report_agent.py:1672`). It dispatches the LLM's tool calls to it (`backend/app/services/report_agent.py:9553-9700`). It also calls the service directly for outline planning (`get_simulation_context` and `insight_forge`, `backend/app/services/report_agent.py:9887,9910`), the signal pack (`simulation_outcomes`, `coalition_map` and `scenario_diff`, `backend/app/services/report_agent.py:2412,2429,2447`) and the causal spine (`trace_cascade`, `backend/app/services/report_agent.py:2816,2825`). The deer-flow-facing MCP server keeps one long-lived `ZepToolsService` singleton (`backend/app/mcp/kg_server.py:90-103`).

---

## Walkthrough (source order)

### 1. `backend/app/utils/zep_rate_limit.py`

- **`_RETRY_AFTER_RE` / `_RESET_RE`** (`zep_rate_limit.py:10-11`): case-insensitive regexes. They pull a number after `retry-after` / `x-ratelimit-reset` (optionally quoted, `:` or `=`) out of an exception's **string form**.
- **`is_zep_rate_limit_error(exc)`** (`zep_rate_limit.py:14-23`): returns True if `str(exc).lower()` contains any of `status_code: 429`, `status code: 429`, `rate limit exceeded`, `x-ratelimit-remaining': '0'` or `"x-ratelimit-remaining": "0"`. This is pure string sniffing with no exception-type check.
- **`zep_retry_delay_seconds(exc, *, fallback, buffer_seconds=1.0, max_sleep_seconds=None)`** (`zep_rate_limit.py:26-52`):
  1. If `retry-after` is found, delay = that value.
  2. Otherwise, if `x-ratelimit-reset` is found, delay = `max(0, reset - time.time())`. This treats the header as an **epoch timestamp**.
  3. Otherwise delay = `fallback`.
  4. It then adds `max(0, buffer_seconds)`, clamps to `max_sleep_seconds` when given, and floors at 0.
- **Side effects:** none (pure).

### 2. `backend/app/utils/zep_paging.py`

Module constants:

| Name | Value | Anchor | Meaning |
|---|---|---|---|
| `_DEFAULT_PAGE_SIZE` | 100 | `zep_paging.py:20` | `limit` per page request |
| `_MAX_NODES` | 8000 | `zep_paging.py:25` | Fallback node cap when Config is unreadable |
| `_MAX_EDGES` | 10000 | `zep_paging.py:28` | Edge cap. A hard constant, **not** Config-driven |
| `_DEFAULT_MAX_RETRIES` | 3 | `zep_paging.py:43` | Attempts per page |
| `_DEFAULT_RETRY_DELAY` | 2.0 s | `zep_paging.py:44` | Doubles after each failed attempt |
| `_DEFAULT_RATE_LIMIT_BUFFER` | 1.0 s | `zep_paging.py:45` | Added to a 429 delay |
| `_DEFAULT_RATE_LIMIT_MAX_SLEEP` | 90.0 s | `zep_paging.py:46` | Cap on a 429 delay |

- **`_resolve_max_nodes()`** (`zep_paging.py:31-42`): `max(1, int(Config.GRAPH_MAX_NODES or 8000))`. On any exception it returns 8000. Because of the `or`, a configured `0` becomes 8000.
- **`_fetch_page_with_retry(api_call, *args, max_retries, retry_delay, rate_limit_buffer, rate_limit_max_sleep, page_description, **kwargs)`** (`zep_paging.py:49-97`):
  - Raises `ValueError` if `max_retries < 1` (`zep_paging.py:60-61`).
  - Loops `max_retries` attempts. It retries **only** `ConnectionError`, `TimeoutError`, `OSError`, the facade's `InternalServerError`, or anything `is_zep_rate_limit_error` matches. Any other exception is re-raised at once (`zep_paging.py:70-74`).
  - The sleep before the next attempt is `zep_retry_delay_seconds(...)` for 429s, otherwise the current `delay`. `delay *= 2` after every failed attempt (`zep_paging.py:77-92`). It logs WARNING per retry and ERROR on the final failure, then re-raises the last exception (`zep_paging.py:93-97`).
- **`fetch_all_nodes(client, graph_id, page_size=100, max_items=None, ...)`** (`zep_paging.py:100-175`):
  - `max_items=None` resolves `Config.GRAPH_MAX_NODES` at call time (`zep_paging.py:116-117`).
  - Each page calls `client.graph.node.get_by_graph_id(graph_id, limit=page_size[, uuid_cursor=cursor])` through `_fetch_page_with_retry` (`zep_paging.py:123-138`).
  - **Wave9-KG belt-and-braces de-dup:** it keeps `seen_uuids` and skips any item already seen (`uuid_`, else `uuid`). If a whole page produced no new uuid, it logs WARNING ("cursor ineffective, falkordblite cursor bug guard") and stops (`zep_paging.py:142-162`).
  - Stop conditions, in order: empty page; page with no new uuids; reached `max_items` (truncate plus WARNING); `len(batch) < page_size`; last item has no uuid (WARNING) (`zep_paging.py:139-173`).
  - The cursor is the **last item's** uuid (`zep_paging.py:170`). That matches the runtime's DESC-ordered `_page_after_cursor` (`backend/app/services/graphiti_client/runtime.py:1790-1806`).
  - Returns the raw facade `_ZepNode` objects.
- **`fetch_all_edges(...)`** (`zep_paging.py:178-247`): same algorithm over `client.graph.edge.get_by_graph_id`. The cap is `max_items=_MAX_EDGES` (10000), and **no Config knob controls it** (`zep_paging.py:182`).

### 3. `backend/app/services/zep_entity_reader.py`

- **`_NODE_ARCHETYPE_KEYS = ("archetype","entity_archetype")`, `_NODE_TIER_KEYS = ("simulation_tier","entity_simulation_tier")`** (`zep_entity_reader.py:30-31`). These are the node attribute keys that count as explicit ontology classification. The `entity_` variants are the reserved-word prefixes added by `graph_builder.safe_attr_name`.
- **`_explicit_classification(node, actors)`** (`zep_entity_reader.py:34-90`): returns an actor-like dict for `actors.is_agent_eligible`, or `None` meaning "no signal, keep the node".
  1. **From node attributes:** the first non-empty string archetype key goes to `signal["archetype"]`. The first tier key that is an int in {1,2,3,4} or a non-empty string goes to `signal["simulation_tier"]`. `bool` is rejected explicitly. A non-empty signal is returned at once (`zep_entity_reader.py:51-71`).
  2. **From the matching `actors.json` row** (`match_actor(node["name"], actors)`): the row counts as a signal if it has a non-empty `archetype`, a non-None `simulation_tier`, or (when `Config.ACTOR_EXCLUDE_MEDIA`, default true) `is_media_entity(row)`. The **whole row** is returned (`zep_entity_reader.py:78-88`).
  3. Otherwise it returns `None`.
- **`_ontology_type_signals(ontology)`** (`zep_entity_reader.py:93-123`): ONT-7. For each `ontology["entity_types"][]` entry with a `name`, it collects the explicit `archetype` (non-empty str) and/or `simulation_tier` (int 1-4 or non-empty str, not bool) into `{type_name: signal}`. Types without either field produce nothing.
- **`EntityNode` dataclass** (`zep_entity_reader.py:126-155`): `uuid, name, labels, summary, attributes, related_edges=[], related_nodes=[]`. `to_dict()` (`:139-148`). `get_entity_type()` returns the first label not in {"Entity","Node"} (`:150-155`).
- **`FilteredEntities` dataclass** (`zep_entity_reader.py:158-172`): `entities, entity_types (set), total_count, filtered_count`. `to_dict()` turns the set into a list.
- **`ZepEntityReader.__init__(api_key=None)`** (`zep_entity_reader.py:185-190`): raises `ValueError("ZEP_API_KEY 未配置")` if no key (never happens with the sentinel). It builds `Zep(...)`, which instantiates the process-global `GraphitiRuntime` and its background event-loop thread on first use (`backend/app/services/graphiti_client/runtime.py:2381-2387,187-192`).
- **`_call_with_retry(func, operation_name, max_retries=3, initial_delay=2.0)`** (`zep_entity_reader.py:192-229`): retries **any** exception. It sleeps 2 s and then 4 s between the 3 attempts, logs WARNING/ERROR, then re-raises the last exception.
- **`get_all_nodes(graph_id)`** (`zep_entity_reader.py:231-256`): `fetch_all_nodes(self.client, graph_id)` with the **module defaults** (3 attempts, not `Config.ZEP_MAX_RETRIES`). It maps each node to a dict `{uuid, name, labels, summary, attributes}` (`uuid_` falls back to `uuid`).
- **`get_all_edges(graph_id)`** (`zep_entity_reader.py:258-284`): `fetch_all_edges` mapped to `{uuid, name, fact, source_node_uuid, target_node_uuid, attributes}`. No temporal fields.
- **`get_node_edges(node_uuid)`** (`zep_entity_reader.py:286-317`): `client.graph.node.get_entity_edges(node_uuid=...)` with `_call_with_retry`. It passes no `graph_id`, so the runtime searches every graph already open in the process (`backend/app/services/graphiti_client/runtime.py:418-423,1860-1874`). Edges map to the same dict shape. Any exception gives a WARNING and `[]`.
- **`filter_defined_entities(graph_id, defined_entity_types=None, enrich_with_edges=True, actors=None, ontology=None)`** (`zep_entity_reader.py:319-499`). This is the main read-back for profile generation.
  1. `tier_gate_on = Config.SIM_TIER_ELIGIBILITY` (default True) (`zep_entity_reader.py:358`).
  2. `type_signals = _ontology_type_signals(ontology)` only when the gate is on **and** `Config.SIM_TIER_FROM_ONTOLOGY` (default false) (`zep_entity_reader.py:363-365`).
  3. Read all nodes, and all edges if `enrich_with_edges` (`zep_entity_reader.py:368-372`). Build `node_map` by uuid (`:375`).
  4. **KG-11 edge index:** one pass builds `edges_by_node[uuid] -> [("outgoing"|"incoming", edge)]` in `all_edges` order. A self-loop is recorded **only** as outgoing (`zep_entity_reader.py:381-388`).
  5. For each node (`zep_entity_reader.py:394-484`):
     - `custom_labels` = labels minus {"Entity","Node"}. If empty, skip (`:398-402`).
     - If `defined_entity_types` is given, it keeps only nodes with a matching label. `entity_type` = first matching label; otherwise the first custom label (`:405-411`).
     - **Tier gate** (`:417-431`): `classification = _explicit_classification(node, actors)`. If None and `type_signals` exists, it falls back to `type_signals.get(entity_type)`. If a classification exists and `not is_agent_eligible(classification)`, it drops the node (`gate_dropped += 1`, DEBUG log). `is_agent_eligible` means `entity_simulation_tier(...) in (1,2)` (`backend/app/utils/actors.py:961-967`). Tier is inferred from the explicit tier, else archetype (source→3, non-actor/collective→4), else media→3 under `ACTOR_EXCLUDE_MEDIA`, else 1/2 by influence (`backend/app/utils/actors.py:928-958`).
     - It builds an `EntityNode`. When enriching, it walks only that node's bucket. Outgoing edges become `{direction:"outgoing", edge_name, fact, target_node_uuid}` and incoming edges become `{direction:"incoming", edge_name, fact, source_node_uuid}`. Neighbor uuids are collected into a **set**, then `related_nodes` = `[{uuid,name,labels,summary}]` for neighbors present in `node_map` (`:445-482`).
  6. It logs the gate-drop count at INFO, then returns `FilteredEntities(entities, entity_types_found, total_count=len(all_nodes), filtered_count)` (`zep_entity_reader.py:486-499`).
  - **Invariant ("NO-OP guarantee"):** when no node or actor row carries an explicit signal, the gate keeps everything (`zep_entity_reader.py:338-340,416`).
- **`get_entity_with_context(graph_id, entity_uuid)`** (`zep_entity_reader.py:501-579`): `client.graph.node.get(uuid_=entity_uuid)` with retry (no graph_id). Then `get_node_edges`, then **the whole graph's nodes** (`get_all_nodes`) just to resolve neighbor names. An edge is `outgoing` iff `source_node_uuid == entity_uuid`, otherwise `incoming`. Any exception gives ERROR and `None`.
- **`get_entities_by_type(graph_id, entity_type, enrich_with_edges=True, actors=None, ontology=None)`** (`zep_entity_reader.py:581-611`): a thin wrapper, `filter_defined_entities(defined_entity_types=[entity_type], ...).entities`.

### 4. `backend/app/services/zep_entity_resolver.py`

The module docstring (`zep_entity_resolver.py:1-24`) states the guardrails: merge only within the same primary label; require a name match **and** an embedding cosine ≥ threshold; never merge two canonicals; the canonical always survives; audit every merge.

- **`_ACTOR_GRAPH_SEED_SCHEMA_VERSION = "actor-graph-seed/v1"`** (`zep_entity_resolver.py:36`).
- **`_seed_kind(node)`** (`zep_entity_resolver.py:39-45`): returns `attributes.seed_kind` only if `attributes.seed_schema_version == "actor-graph-seed/v1"`, else `""`.
- **`_seed_survivor_priority(node)`** (`zep_entity_resolver.py:48-55`): `actor` gives 0 (best), unseeded gives 1, `actor_alias` gives 2 (worst survivor).
- **`canonical_norm_set(actors)`** (`zep_entity_resolver.py:59-62`): the set of `normalize_name(row.name)` over `extract_actor_rows(actors)`, with empties removed. `normalize_name` = NFKC + lowercase + strip whitespace and common CJK/ASCII punctuation (`backend/app/utils/actors.py:145-156`).
- **`actor_alias_map(actors)`** (`zep_entity_resolver.py:65-95`): `{normalize_name(alias): normalize_name(canonical)}` from each row's `aliases` list. It skips aliases equal to the canonical. If two rows share an alias, **the later row wins** (plain dict assignment, `:94`).
- **`_cosine(a, b)`** (`zep_entity_resolver.py:98-107`): returns None when a vector is missing or empty, the lengths differ, or a norm is 0.
- **`_name_match(a, b)`** (`zep_entity_resolver.py:110-119`): exact normalized equality, or the shorter string (≥2 chars) is contained in the longer.
- **`_primary_label(node)`** (`zep_entity_resolver.py:122-124`): first label other than `"Entity"`, else `"Entity"`. **Note:** "Node" is *not* excluded here, unlike in the reader.
- **`_node_aliases(node)`** (`zep_entity_resolver.py:127-156`): normalized aliases from `node.aliases` (list), `attributes.aliases` (list) and `attributes.alias` (str). The runtime's `all_entity_nodes` now includes `attributes` for exactly this purpose (`backend/app/services/graphiti_client/runtime.py:1903-1910`).
- **`_alias_match(...)`** (`zep_entity_resolver.py:159-172`): exact only. One node's name is in the other's alias set, or the two alias sets intersect.
- **`_labels_mergeable(a, b)`** (`zep_entity_resolver.py:175-181`): same label, or one side is `"Entity"`.
- **`_UnionFind`** (`zep_entity_resolver.py:184-197`): path halving. `union(a,b)` makes root(a) the parent.
- **`plan_merges(nodes, embeddings, canonical_norms, threshold, alias_map=None)`** (`zep_entity_resolver.py:200-301`). This is the full **O(N²)** planner. It is pure.
  - Embeddings are used only if `len(embeddings) == n`, otherwise all None (`:223`).
  - Per node it precomputes `norms`, `labels`, `aliases`, `dossier_canon` (the alias_map hit, or itself when canonical), `is_canon`, seed kinds and priorities (`:224-234`).
  - `typed_by_root` tracks the set of distinct typed labels per union-find root. `_try_union` refuses a union that would put two distinct typed labels in one component (`:241-256`).
  - Pair filters for `i<j` (`:258-290`):
    - skip when `norms[i]` is empty;
    - skip when either seed kind is `entity_type`;
    - skip when **both** are `actor` seeds;
    - skip when labels are not mergeable;
    - skip two **distinct** canonicals;
    - require `name_ok or alias_ok or dossier_ok`.
  - Cosine gate: with no embeddings, it requires an exact signal (equal norms, alias, or dossier) and uses `cos=1.0`. With embeddings, `cos < threshold` is rejected **unless `dossier_ok`**, which bypasses the gate (`:278-289`).
  - Then it calls `_finalize_clusters`.
- **`_finalize_clusters(...)`** (`zep_entity_resolver.py:304-349`): groups union-find components with ≥2 members.
  - A component holding ≥2 **distinct** canonical norms is split. Each canonical anchors a group, and each non-canonical member joins the canonical with the highest `_sim` (`:324-342`).
  - `_sim(a,b)` returns the cached pair cosine, **defaulting to 1.0** for pairs never compared directly (`:315-316`).
  - It picks a survivor per group with `_pick_survivor` and emits `_make_cluster`.
- **`plan_merges_fast(...)`** (`zep_entity_resolver.py:352-438`): the **O(N)** path for large graphs.
  - Buckets are keyed by the exact normalized name, by each explicit alias, and by `"__dossier__"+dossier_canon` (`:399-406`).
  - Within each bucket it compares **only `idxs[0]` against each other member** (a star, not all pairs) (`:408-427`). Seed, label and canonical filters are the same as the full planner.
  - Cosine None gives 1.0. Cosine `< threshold` gives skip, **with no dossier bypass** (`:422-426`).
- **`_pick_survivor(...)`** (`zep_entity_resolver.py:441-455`): min over `(seed priority, non-canonical, label=="Entity", -len(norm), norm, uuid)`. The actor seed wins, then the canonical, then a typed label, then the longest name, then deterministic tie-breaks.
- **`_make_cluster(...)`** (`zep_entity_resolver.py:458-476`): returns `{survivor_uuid, survivor_name, primary_label, cross_label (any victim label differs), victims:[{uuid,name,similarity,label}]}`.
- **`resolve_entities(graph_id, actors, threshold=None, runtime=None)`** (`zep_entity_resolver.py:480-542`). This is the orchestration entry point.
  1. `threshold = Config.GRAPH_RESOLVE_SIM_THRESHOLD` (0.88) and `runtime = get_runtime()` (`:489-494`).
  2. `nodes = runtime.all_entity_nodes(graph_id)`, a list of dicts `{uuid,name,labels,summary,attributes}` read by ordered-uuid IN batches of 500 (`backend/app/services/graphiti_client/runtime.py:1882-1911`). With fewer than 2 nodes it returns the empty audit (`:496-499`).
  3. `embeddings = runtime.embed_texts([names])` (local sentence-transformer, `backend/app/services/graphiti_client/runtime.py:2010-2018`). An exception gives a WARNING and `None`, which means the exact-signal fallback (`:501-505`).
  4. `cap = int(Config.GRAPH_RESOLVE_MAX_NODES or 1200)`. More nodes than the cap goes to `plan_merges_fast`, otherwise `plan_merges` (`:512-522`).
  5. For each victim in each cluster it calls `runtime.merge_nodes(graph_id, survivor_uuid, victim_uuid)`. Failures are isolated per merge, and `merged` counts results with `deleted` set. Each cluster gets `execution: [{victim_uuid, ...result}]` (`:524-537`).
  6. Returns `{nodes_scanned, clusters, merged_nodes, merges: plan, threshold}` (`:541-542`).
  - `merge_nodes` itself (outside the slice) holds the per-graph write lock. It refuses to delete actor seeds or entity-type seeds, rewires `RELATES_TO` edges with fresh uuids (seed edges keep their uuid), drops self-loops, unions attributes and labels onto the survivor, and DETACH-DELETEs the victim (`backend/app/services/graphiti_client/runtime.py:2020-2205`).

### 5. `backend/app/services/zep_graph_memory_updater.py`

- **`AgentActivity` dataclass** (`zep_graph_memory_updater.py:23-198`): `platform, agent_id, agent_name, action_type, action_args, round_num, timestamp`.
  - `to_episode_text()` (`:34-61`) dispatches on `action_type` to one of 12 describers (CREATE_POST, LIKE_POST, DISLIKE_POST, REPOST, QUOTE_POST, FOLLOW, CREATE_COMMENT, LIKE_COMMENT, DISLIKE_COMMENT, SEARCH_POSTS, SEARCH_USER, MUTE). Anything else uses `_describe_generic` → `执行了{type}操作` (`:196-198`). It returns `"{agent_name}: {description}"`, **deliberately with no "simulation" prefix** (`:60-61`).
  - All templates are **Chinese** prose that embed post, comment and author text from `action_args`. The keys read are `content`, `post_content`, `post_author_name`, `original_content`, `original_author_name`, `quote_content`, `target_user_name`, `comment_content`, `comment_author_name`, `query`/`keyword`/`username` (`:63-194`).
- **`ZepGraphMemoryUpdater`** (`zep_graph_memory_updater.py:201-641`):
  - Class constants (`:216-232`): `BATCH_SIZE=5`, `PLATFORM_DISPLAY_NAMES={'twitter':'世界1','reddit':'世界2'}`, `SEND_INTERVAL=0.5`, `MAX_RETRIES=3`, `RETRY_DELAY=2`, `MAX_BUFFERED_RETRY=500`.
  - `__init__(graph_id, api_key=None)` (`:234-281`) sets up a `Queue`, per-platform buffers `{'twitter':[], 'reddit':[]}` with `threading.Lock` `_buffer_lock`, the counters (`_total_activities`, `_total_sent` batches, `_total_items_sent`, `_failed_count` batches, `_failed_items`, `_dead_lettered`, `_skipped_count`) and `_dead_letter_path = Config.OASIS_SIMULATION_DATA_DIR/_zep_dead_letter/{graph_id}.jsonl` (`:275-279`). `OASIS_SIMULATION_DATA_DIR` = `backend/uploads/simulations` (`backend/app/config.py:1080`). The file is **graph-scoped**, not sim-scoped.
  - `start()` (`:287-299`): idempotent. Starts a daemon thread `ZepMemoryUpdater-<graph_id[:8]>` running `_worker_loop`.
  - `stop()` (`:301-318`): sets `_running=False`, calls `_flush_remaining()` **on the caller's thread**, joins the worker for at most 10 s, and logs all counters.
  - `add_activity(activity)` (`:320-348`): `DO_NOTHING` gives `_skipped_count += 1`. Otherwise it enqueues and increments `_total_activities`.
  - `add_activity_from_dict(data, platform)` (`:350-372`): ignores lines with an `event_type` key. It maps `agent_id`, `agent_name`, `action_type`, `action_args`, `round` and `timestamp` (default `now().isoformat()`) to an `AgentActivity`.
  - `_worker_loop()` (`:374-403`): `while _running or queue not empty`. It does `get(timeout=1)` and appends to the platform buffer **inside `with _buffer_lock`**. When the buffer reaches ≥ `BATCH_SIZE`, it slices off the first 5 and calls `_send_batch_activities` followed by `time.sleep(0.5)`, **still under the lock** (`:384-396`). An outer `except Exception` logs and sleeps 1 s.
  - `_send_batch_activities(activities, platform)` (`:405-448`): joins the `to_episode_text()` lines with `\n` (computed **outside** the retry try). Up to 3 attempts call `client.graph.add(graph_id=..., type="text", data=combined_text)`. That reaches `runtime.add_episode(name="activity", source_description="mirofish-activity")`, a full graphiti LLM extraction pass (`backend/app/services/graphiti_client/client.py:200-208`). On success it updates the counters and calls `_write_typed_edges` **inside the same try** (`:436`). On failure it sleeps `2*(attempt+1)` s (2 s, 4 s). On the final failure it increments `_failed_count` and `_failed_items += len` and calls `_recover_failed_batch`.
  - `_recover_failed_batch(activities, platform)` (`:450-481`): documented as running under the caller's lock (it must not re-acquire the non-reentrant lock). While running, it re-appends the failed activities to the end of the platform buffer, up to `MAX_BUFFERED_RETRY - len(buf)`, and dead-letters the overflow. When stopping (`_running=False`), it dead-letters everything. It never raises.
  - `_write_dead_letter(activities, platform)` (`:483-513`): `makedirs`, then appends one JSON line per activity: `{graph_id, platform, dead_lettered_at, combined_text (this activity's episode text), agent_name, action_type, round, timestamp}` with `ensure_ascii=False`. It flushes and `fsync`s, then increments `_dead_lettered`. Errors are logged and swallowed.
  - `_TYPED_EDGE_MAP` (`:516-530`) maps an action to `(edge name, candidate target keys)`: LIKE_POST→LIKED, DISLIKE_POST→DISLIKED, REPOST→REPOSTED, QUOTE_POST→QUOTED, CREATE_COMMENT→REPLIED_TO, LIKE_COMMENT→LIKED, DISLIKE_COMMENT→DISLIKED, FOLLOW→FOLLOWED, MUTE→MUTED. `target_user_name` comes first for FOLLOW and MUTE (F-4-0 fix).
  - `_write_typed_edges(activities)` (`:532-564`): only when `Config.SIM_TYPED_FEEDBACK_EDGES` (default false, `backend/app/config.py:1388`). Per activity it picks the first non-empty target key and skips missing or self targets. `valid_at = datetime.fromisoformat(timestamp)`, falling back to None. It then calls `client.graph.add_triplet(graph_id, author, EDGE, target, f"{author} {EDGE} {target} (round N)", valid_at=...)`. Exceptions go to DEBUG.
  - `write_interview_fact(agent_name, statement, valid_at=None)` (`:566-596`): gated by `Config.SIM_INTERVIEW_GRAPH_FEEDBACK` (default false, `backend/app/config.py:1391-1392`). It writes the triplet `<agent> STATED_AT_END_OF_SIM 模拟终局陈述` with fact `"{agent}: {statement[:1500]}"` and Entity labels. It returns True or False.
  - `_flush_remaining()` (`:598-621`): drains the queue into the buffers, then under the lock sends **each platform's whole remaining buffer as one batch**, whatever its size, and clears all buffers.
  - `get_stats()` (`:623-641`): a counters snapshot (buffer sizes read under the lock).
- **`ZepGraphMemoryManager`** (`zep_graph_memory_updater.py:644-719`): class-level registry `_updaters: {simulation_id: updater}` plus `_lock`.
  - `create_updater(sim_id, graph_id)` (`:654-676`): stops an existing updater for that sim first, then creates and starts a new one.
  - `get_updater` (`:678-681`): no lock.
  - `stop_updater` (`:683-690`): stops and removes.
  - `stop_all()` (`:695-711`): a one-shot guarded by class flag `_stop_all_done`, which is never reset.
  - `get_all_stats()` (`:713-719`).

### 6. `backend/app/services/zep_tools.py`

#### 6.1 Module helpers and result types

- **`compact_graph_query(text, max_chars=350)`** (`zep_tools.py:36-51`): deterministic. It collapses whitespace. If the text is over the limit, it cuts at the last sentence separator (`。`, `. `, `! `, `? `, `！`, `？`, `；`, `; `) that sits at index ≥40 inside the first `max_chars`, else at the last space. Used by `ReportAgent._compact_retrieval_query` with `max_chars=280` (`backend/app/services/report_agent.py:2192-2193`).
- **`_semantic_clamp_query(query, max_chars)`** (`zep_tools.py:54-72`): keeps a head of `max(80, 0.7*max_chars)` cut at a space. It then appends de-duplicated tail tokens matching `[A-Z][A-Za-z0-9\-\.]{2,}` (capitalized words) or `\d[\d.,/%]*` (numbers) until `max_chars` is reached.
- **`SearchResult`** (`zep_tools.py:75-108`): `facts, edges, nodes, query, total_count, degraded=False`. `to_text()` renders only the query (with a `（降级搜索）` marker when degraded), the count and the numbered facts.
- **`NodeInfo`** (`zep_tools.py:111-132`) and **`EdgeInfo`** (`zep_tools.py:135-189`). `EdgeInfo` carries `created_at/valid_at/invalid_at/expired_at`. The facade has already converted these to ISO strings (`backend/app/services/graphiti_client/client.py:24-31,63-66`). It has `is_expired`/`is_invalid` properties and `to_text(include_temporal)`.
- **`InsightForgeResult`** (`zep_tools.py:192-265`): `to_text()` emits the Chinese headed sections 子问题 / 【关键事实】 (quoted) / 【核心实体】 / 【关系链】.
- **`PanoramaResult`** (`zep_tools.py:268-346`): `to_text()` emits **all** active and historical facts in the result, **every node name** (`:329-333`) and the first **40** edges as `[E<uuid8>] src --[REL]--> tgt` (`:337-344`).
- **`AgentInterview`** (`zep_tools.py:349-402`): `to_text()` strips quote marks and leading punctuation from key quotes, drops quotes containing `问题1..9`, trims quotes over 150 chars at the first `。` after index 80 (or hard-cuts at 147 + `...`), and keeps quotes ≥10 chars.
- **`InterviewResult`** (`zep_tools.py:405-463`).

#### 6.2 `ZepToolsService` core

- Class constants `MAX_RETRIES = Config.ZEP_MAX_RETRIES` (default 2) and `RETRY_DELAY = Config.ZEP_RETRY_DELAY_SECONDS` (2.0) are **bound at import** (`zep_tools.py:487-488`; `backend/app/config.py:1041-1042`).
- **`__init__(api_key=None, llm_client=None)`** (`zep_tools.py:490-517`) sets up `client = Zep(...)`, a lazy `LLMClient`, `_nodes_cache {graph_id: [NodeInfo]}`, `_edges_cache {(graph_id, include_temporal): [EdgeInfo]}`, `_search_cache`, `_forge_cache`, `_cache_lock = RLock`, `_coverage {graph_id: {entity_uuids, entity_names, community_ids, edge_types}}`, `_fact_embed_cache`, and a lazy `_embedder`.
- Flag readers (`zep_tools.py:520-556`): `REPORT_RETRIEVAL_CACHE` (False), `REPORT_RETRIEVAL_PARALLEL` (False), `REPORT_RETRIEVAL_PARALLEL_WORKERS` (4, min 1), `GRAPH_SEARCH_RECIPE` (`"rrf"`; `_mmr_enabled` iff `"mmr"`), and `REPORT_MIN_ACTOR_COVERAGE` (0.6, clamped to [0,1]). All are read with `getattr(Config, name, default)`.
- **`invalidate_search_cache(graph_id=None)`** (`zep_tools.py:558-571`): clears `_search_cache` and `_forge_cache` (all, or only keys whose `[0] == graph_id`). It does **not** touch `_nodes_cache`/`_edges_cache`.
- **`llm`** (`zep_tools.py:573-578`): a lazy `LLMClient()`.
- **`_call_with_retry(func, operation_name, max_retries=None)`** (`zep_tools.py:580-611`): retries **every** exception up to `max_retries or MAX_RETRIES` attempts. 429s sleep `zep_retry_delay_seconds(fallback=delay, buffer=Config.ZEP_RATE_LIMIT_BUFFER_SECONDS, max=Config.ZEP_RATE_LIMIT_MAX_SLEEP_SECONDS)`. Everything else sleeps `delay`, and `delay` doubles each time. It re-raises the last exception.

#### 6.3 Search primitives

- **`search_graph(graph_id, query, limit=10, scope="edges", recipe=None, search_filter=None)`** (`zep_tools.py:613-747`):
  1. **Query clamp:** `_default_max = 380 if Config.GRAPHITI_REMOTE else 1200`, and `GRAPH_QUERY_MAX_CHARS` (0 = auto) overrides it. A longer query is `_semantic_clamp_query`'d when `GRAPH_QUERY_CLAMP_SEMANTIC` (default true), otherwise prefix-cut at a space (`:646-655`).
  2. Cache key `(graph_id, query.strip().lower(), limit, scope, recipe.lower(), json(search_filter))`. A hit returns a copy, but only when the cache is enabled (`:661-670`).
  3. It calls `client.graph.search(graph_id, query, limit, scope, reranker="cross_encoder"[, recipe][, search_filter])` through `_call_with_retry` (`:676-690`).
  4. Parsing: each edge with a non-empty `fact` adds the fact to `facts` and an edge dict `{uuid,name,fact,source_node_uuid,target_node_uuid}` to `edges`. Each node adds `{uuid,name,labels,summary}` and, when it has a summary, the fact `"[name]: summary"` (`:697-720`). `total_count = len(facts)`.
  5. Errors: `ApiError`, `InternalServerError`, `ConnectionError`, `TimeoutError` and `OSError` go to `_fallback_local_search` (WARNING) (`:736-739`). Other exceptions also fall back if they look like a rate limit (`:743-745`). Anything else logs ERROR with a traceback and **re-raises** (F-4-6, `:746-747`).
- **`_copy_search_result`** (`zep_tools.py:749-759`): copies the lists and dicts.
- **`_fallback_local_search`** (`zep_tools.py:761-776`): `_local_search` with `degraded=True`. **It caches the degraded result** under the same key when the cache is on.
- **`_local_search(graph_id, query, limit=10, scope="edges")`** (`zep_tools.py:778-880`): keyword scoring over the **cached full graph**. Keywords are the query lowercased with `,`/`，` replaced by spaces, split on whitespace, keeping tokens >1 char. Score = 100 if the whole query is a substring, plus 10 per keyword hit. [verifier: `match_score` returns 100 early when the whole query is a substring and adds no keyword points; only otherwise does it score 10 per keyword. The edge score is `match_score(fact) + match_score(name)` (zep_tools.py:809-822,830)] Edges score `fact + name`, nodes score `name + summary`. Results are sorted by score and the top `limit` kept. Scope `"both"` covers edges and nodes. Every exception becomes an ERROR log and an empty result. [verifier: the result is not necessarily empty. Facts and edges collected before the exception are kept, for example the edge hits when the node pass fails (zep_tools.py:824-880)]
- **`search_from_cache(...)`** (`zep_tools.py:882-898`): `_local_search` + `degraded=True`. There is **no caller** in `backend/app` (it was planned for `PROFILE_ENRICH_FROM_CACHE`).
- **`_as_of_filter(as_of)`** (`zep_tools.py:908-916`): returns `{"as_of": iso}`. The runtime's `_to_search_filters` translates that into `valid_at <= D AND (invalid_at IS NULL OR invalid_at > D)` (`backend/app/services/graphiti_client/runtime.py:1493-1507`).
- **`as_of_search(graph_id, query, as_of, limit=20, scope="edges")`** (`zep_tools.py:918-952`): `parse_as_of` (lenient; a datetime passes through, a string keeps date precision only, `backend/app/utils/dates.py:38-68`). If parsing fails it does a plain `search_graph` (WARNING when `as_of` was non-empty). Otherwise it calls `search_graph(search_filter=_as_of_filter(...))`. Used by the MCP `kg_search` (`backend/app/mcp/kg_server.py:145-151`).

#### 6.4 MMR de-dup and coverage tracking

- **`_get_embedder`** (`zep_tools.py:960-972`): lazily builds a **new** `LocalSentenceTransformerEmbedder()`, a separate instance from the runtime's. Its model is loaded lazily per instance (`backend/app/services/graphiti_client/embedder.py:214-241`). On failure it sets `_embedder_unavailable` for good.
- **`_embed_facts(facts)`** (`zep_tools.py:974-996`): cache look-ups run under the lock. The un-cached facts are embedded **outside** the lock via `get_runtime().run(embedder.create_batch(todo))`. Any failure sets `_embedder_unavailable=True` and returns `{}`.
- **`_cosine`** (`zep_tools.py:998-1004`): a dot product over `min(len)`, which assumes unit vectors.
- **`_dedupe_facts_mmr(facts, threshold=0.92)`** (`zep_tools.py:1006-1035`): always does exact de-dup in order. The semantic pass (drop a fact whose cosine is >0.92 against any kept fact) runs only when `_mmr_enabled()` and embeddings are available.
- **`record_coverage(graph_id, *, entity_uuids, entity_names, community_ids, edge_types)`** (`zep_tools.py:1043-1071`): adds to per-graph sets (names lowercased). Never raises.
- **`get_coverage_report(graph_id, high_influence_actors=None)`** (`zep_tools.py:1073-1121`): `surfaced_entity_count` (uuids, else names) and the sorted lists. When actors are given it computes coverage by exact name or **bidirectional substring** match, and logs a WARNING when coverage is below `REPORT_MIN_ACTOR_COVERAGE`.
- **`flush_coverage(graph_id, output_path, ...)`** (`zep_tools.py:1123-1140`): `write_json_atomic`. It never raises. **There is no caller in `backend/app`**, so `handoff/retrieval_coverage.json` is never produced.

#### 6.5 Graph snapshot readers

- **`get_all_nodes(graph_id)`** (`zep_tools.py:1142-1185`): a per-instance cache hit returns a list copy. A miss runs `fetch_all_nodes(..., max_retries=Config.ZEP_MAX_RETRIES, retry_delay=Config.ZEP_RETRY_DELAY_SECONDS, rate_limit_*)`, maps the nodes to `NodeInfo`, and stores them first-writer-wins under the lock.
- **`get_all_edges(graph_id, include_temporal=True)`** (`zep_tools.py:1187-1241`): the same pattern, keyed `(graph_id, include_temporal)`. It copies the temporal fields when `include_temporal`.
- **`get_node_detail(node_uuid)`** (`zep_tools.py:1243-1273`): `client.graph.node.get(uuid_=...)` with retry and no graph_id. Any error gives ERROR and `None`.
- **`get_node_edges(graph_id, node_uuid)`** (`zep_tools.py:1275-1305`): filters the cached full edge list to edges where the node is source or target. An error gives `[]`.
- **`get_entities_by_type(graph_id, entity_type)`** (`zep_tools.py:1307-1333`): the nodes whose `labels` contain `entity_type`.
- **`get_entity_summary(graph_id, entity_name)`** (`zep_tools.py:1335-1380`): `search_graph(query=entity_name, limit=20)`, plus the first node whose name equals `entity_name` case-insensitively, plus that node's edges. Returns `{entity_name, entity_info, related_facts, related_edges, total_relations}`.
- **`_build_graph_statistics` / `get_graph_statistics`** (`zep_tools.py:1382-1421`): counts per typed label (excluding Entity/Node) and per edge `name`.
- **`get_simulation_context(graph_id, simulation_requirement, limit=30, search_query=None)`** (`zep_tools.py:1423-1478`): `search_graph(query = search_query or requirement, limit)` plus statistics plus typed entities `[:limit]` and `total_entities`.

#### 6.6 Report-agent tools (the "core" set and the deterministic set)

| Tool (report_agent name) | Method | Query it runs | Output |
|---|---|---|---|
| `insight_forge` | `insight_forge` `zep_tools.py:1482-1743` | 1 LLM call for sub-queries. Then `search_graph(scope=edges)` for each sub-query (limit 15) and for the original query (limit 20), optional MMR recipe and as-of filter. Then a full-graph node snapshot. Then one node-scope `search_graph(limit=10)`. | `InsightForgeResult.to_text()`: sub-queries, de-duplicated facts, entity insights (with related facts), `[E<uuid8>]` relationship chains |
| `panorama_search` | `panorama_search` `zep_tools.py:1803-1920` | No semantic search. Loads **all** nodes and edges and splits facts into active and historical. | `PanoramaResult.to_text()`: active/historical facts (top `limit=50` each by keyword relevance), all node names, 40 typed edges |
| `quick_search` (and legacy `search_graph`) | `quick_search` `zep_tools.py:1922-1955` | `search_graph(scope="edges", limit)` | `SearchResult.to_text()` |
| `interview_agents` | `interview_agents` `zep_tools.py:1957-2191` | Reads profiles. 1 LLM call to select agents, 1 for questions, 1 for the summary. One IPC batch interview to the live OASIS env. | `InterviewResult.to_text()` |
| `simulation_outcomes` | `zep_tools.py:2457-2491` | `SimulationRunner.get_agent_stats` + `get_timeline` (no graph, no LLM) | Markdown: top-N agents, global action-type mix, per-round volume, peak round |
| `coalition_map` | `zep_tools.py:2493-2552` | `SimulationRunner.get_actions(limit=100000)` (no graph) | Union-find "factions" of agents that share any interaction target |
| `faction_brief` | `zep_tools.py:2554-2595` | `runtime.list_communities` when `GRAPH_COMMUNITY_RETRIEVAL`, else `coalition_map` | Top 8 communities with summary and members, plus the inter-community tension matrix |
| `opinion_shift` | `zep_tools.py:2770-2794` | `SimulationRunner.get_actions(limit=100000)` filtered by normalized-name substring | Per-round action-type counts for one actor |
| `trace_cascade` | `zep_tools.py:2719-2768` | `runtime.causal_paths` / `runtime.n_hop_subgraph` (FalkorDB variable-length Cypher), causal edge family first | Path list (≤12) or neighborhood edges (≤40) |
| `scenario_diff` | `zep_tools.py:2796-2854` | Timelines and agent stats of the base sim and the scenario sim | Total/peak/per-round deltas (≤48 rounds) and the top 10 actor deltas |
| `get_graph_statistics` / `get_entity_summary` / `get_entities_by_type` (legacy aliases) | §6.5 | snapshot / search | JSON dumps (`backend/app/services/report_agent.py:9669-9696`) |
| `get_simulation_context` (legacy alias) | redirected by report_agent to `insight_forge` with a compact query | — | (`backend/app/services/report_agent.py:9681-9686`) |

Details:

- **`insight_forge(graph_id, query, simulation_requirement, report_context="", max_sub_queries=5, as_of=None)`** (`zep_tools.py:1482-1743`):
  1. `as_of_dt = parse_as_of(as_of)` and its filter. `recipe = "mmr"` iff `GRAPH_SEARCH_RECIPE == "mmr"`, else None (`:1516-1519`).
  2. Forge cache key `(graph_id, query.lower, requirement.lower, hash(report_context), max_sub_queries, as_of_iso, recipe)`. A hit returns the **same object** (no copy) (`:1524-1533`).
  3. `_generate_sub_queries` (`:1542-1548`).
  4. `search_specs = [(sq,15)...] + [(query,20)]`. In **parallel** mode (a `ThreadPoolExecutor` with `min(workers, n)` threads) each future's exception is caught and skipped. In **serial** mode (the default) a `search_graph` exception propagates out of `insight_forge` (`:1556-1588`).
  5. Merges the facts in spec order and runs `_dedupe_facts_mmr` (`:1591-1601`).
  6. Collects source and target uuids from every edge dict into a **set** (`:1604-1612`). It takes one `get_all_nodes` snapshot and falls back to `get_node_detail` for uuids not in it (F-4-3). Each node becomes `{uuid,name,type,summary,related_facts = facts whose lowercase contains node.name.lower()}` (`:1621-1648`).
  7. **R2-KG-9 node scope:** `search_graph(scope="nodes", limit=10)`. It drops candidates already present by uuid or name, MMR/exact-dedupes the `"[name]: summary"` blobs, and appends new insights (`:1658-1700`). Wrapped in try/except, with failures at DEBUG.
  8. Relationship chains: `"[E<uuid8>] src --[REL]--> tgt"`, de-duplicated, for every edge. Names come from `node_map`, falling back to `uuid[:8]` (`:1703-1723`).
  9. `record_coverage(...)`, then the cache write (`:1729-1742`).
- **`_generate_sub_queries(...)`** (`zep_tools.py:1745-1801`): `llm.chat_json` (system prompt asking for `{"sub_queries": [...]}`, user prompt with the requirement, `report_context[:500]` and the question), `temperature=0.3`, `tier="fast"`. Returns `[str(sq) for sq in resp["sub_queries"][:max]]`. On any exception it falls back to the 4 variants of `compact_graph_query(query, 300)`: base, `的主要参与者`, `的原因和影响`, `的发展过程`.
- **`panorama_search(graph_id, query, include_expired=True, limit=50, as_of=None)`** (`zep_tools.py:1803-1920`):
  - With **`as_of`**, an edge is active if `valid_dt` is None or ≤ D and it has not ended (`invalid_at` or `expired_at` ≤ D). It is historical (`"[valid - end] fact"`) if it ended. Edges that start after D are dropped (`:1860-1874`).
  - Without `as_of`, historical means `expired_at` or `invalid_at` is set (`:1877-1886`).
  - Both lists are sorted by the same keyword relevance as `_local_search` and cut to `limit`. [verifier: the relevance is similar but not the same. Panorama's `relevance_score` adds 100 plus 10 per keyword. `_local_search` returns 100 alone on a whole-query hit (zep_tools.py:1892-1900 vs zep_tools.py:809-822)] `include_expired=False` blanks the historical list but keeps `historical_count` (`:1889-1909`). Coverage is recorded for the whole graph (`:1912-1917`).
- **`interview_agents(simulation_id, interview_requirement, simulation_requirement="", max_agents=5, custom_questions=None, graph_id=None)`** (`zep_tools.py:1957-2191`):
  1. `_load_agent_profiles` (`zep_tools.py:2214-2258`) reads `backend/uploads/simulations/<sim_id>/reddit_profiles.json` (preferred) or `twitter_profiles.csv`. The path is hard-coded relative to `__file__` rather than `Config.OASIS_SIMULATION_DATA_DIR`, though it resolves to the same directory. CSV rows map to `{realname, username, bio, persona, profession:"未知"}`. No profiles gives the summary "未找到可采访的Agent人设文件" (`zep_tools.py:2005-2008`).
  2. `_select_agents_for_interview` (`zep_tools.py:2260-2344`): an LLM `chat_json` (temp 0.3, tier fast) over **all** profile summaries (bio[:200]). It returns `selected_indices[:max_agents]` filtered to valid indices, with the **profile list index used as the OASIS agent_id**. On an exception it takes the first `max_agents`.
  3. `_generate_interview_questions` (`zep_tools.py:2346-2396`): `chat_json` (temp 0.5, tier fast) → `questions`. On an exception it uses 3 fixed Chinese questions.
  4. Builds a numbered prompt with the fixed Chinese `INTERVIEW_PROMPT_PREFIX` (answer in plain text, prefix each answer with `问题X：`) (`zep_tools.py:2035-2049`).
  5. `SimulationRunner.interview_agents_batch(simulation_id, [{agent_id, prompt}], platform=None, timeout=600.0)` interviews both platforms (`zep_tools.py:2065-2073`).
     - `success=False` returns a failure summary.
     - Results are parsed as `results["twitter_<id>"/"reddit_<id>"].response`, cleaned by `_clean_tool_call_response` (`zep_tools.py:2193-2212`), and shown as `【Twitter平台回答】…【Reddit平台回答】…`.
     - Key quotes are the 3 longest 20–150-char sentences, splitting on `。！？` only, with curly/corner-bracket quotes as a fallback (`zep_tools.py:2111-2137`).
  6. When `graph_id` is given and `SIM_INTERVIEW_GRAPH_FEEDBACK` is set, it builds a throw-away `ZepGraphMemoryUpdater(graph_id)` (never started) and calls `write_interview_fact` for each response. If anything was written it calls `invalidate_search_cache(graph_id)` (`zep_tools.py:2155-2169`).
  7. `ValueError` means "env not running" and gives a summary; any other exception gives an error summary (`zep_tools.py:2171-2181`).
  8. `_generate_interview_summary` (`zep_tools.py:2398-2450`): `llm.chat` (temp 0.3, `max_tokens=800`, **no tier**) over each response cut to [:500]. On failure it falls back to a simple list of names.
- **`simulation_outcomes`** (`zep_tools.py:2457-2491`): sorts the stats by `total_actions`, prints the top N with the 5 most frequent action types, sums the action types globally, and prints `round:total/active` volumes plus the peak round.
- **`coalition_map(graph_id, simulation_id)`** (`zep_tools.py:2493-2552`): for each action it collects the target names under keys `post_author_name`, `original_author_name`, `comment_author_name`, `quoted_author_name`, `target_user_name`, `followee_name` and `target_name`. Union-find joins any two agents that share a target. Output lists the clusters of ≥2 agents, largest first, with up to 15 names each. `graph_id` is unused.
- **`faction_brief(graph_id, query="", simulation_id="")`** (`zep_tools.py:2554-2595`): when `GRAPH_COMMUNITY_RETRIEVAL` is off (it defaults to `GRAPH_BUILD_COMMUNITIES`, default **false**, `backend/app/config.py:1266,1273-1277`), it degrades to `coalition_map`. Otherwise it takes `list_communities` (≤200, with members from the `HAS_MEMBER` Cypher, `backend/app/services/graphiti_client/runtime.py:1231-1264`), sorts by `(count of query occurrences, member count)` descending, and shows the top 8 (≤20 members each) plus `_inter_community_tension`.
- **`_inter_community_tension(graph_id, communities)`** (`zep_tools.py:2597-2663`): uses ≤12 non-empty communities. It maps normalized member names to a community (first one wins). For every cross-community edge it accumulates `relation_polarity({"type": edge.name})`. Each pair is labelled `对抗` (net < -0.05), `结盟` (> 0.05) or `中性/混合`. It shows the top 12, most adversarial first. Errors return `[]`.
- **`_resolve_entity_name(graph_id, name)`** (`zep_tools.py:2668-2702`): an exact normalized match, else the longest node name (≥2 chars) in bidirectional containment, else the raw name.
- **`_fmt_edge_label(edge)`** (`zep_tools.py:2704-2717`): renders a dict edge as `NAME, sign=…, strength=…, lag=…, polarity=…, family=…`, and anything else as `str(edge)`.
- **`trace_cascade(graph_id, source="", target="", center="", causal_only=True)`** (`zep_tools.py:2719-2768`):
  - `_CAUSAL_EDGE_NAMES = [CAUSES, ENABLES, CONSTRAINS, TRIGGERS, ACCELERATES]` (`:2666`).
  - Given source and target, it resolves both names and calls `rt.causal_paths(...)` with the default `max_hops=4` (`backend/app/services/graphiti_client/runtime.py:1294-1306`). If the causal family returns nothing it retries with all edge types and notes that. It shows ≤12 paths.
  - Given only a center, it calls `rt.n_hop_subgraph` (default 2 hops, limit 60) with the same fallback and shows ≤40 edges.
  - Every failure becomes a Chinese placeholder string. It never raises.
- **`opinion_shift(simulation_id, actor_name)`** (`zep_tools.py:2770-2794`): an empty normalized name returns a usage message (RPT-13). Otherwise it matches agents whose normalized name **contains** the target and outputs per-round action-type counts.
- **`scenario_diff(base_sim_id, scenario_sim_id)`** (`zep_tools.py:2796-2854`): total delta and percent, peak rounds, round counts, per-round `base→scen` for the first 48 rounds of the union, and the top 10 absolute per-agent deltas.

---

## Control flow

**A. PREPARE read-back** (simulation profile path):
`SimulationManager.prepare_simulation` → `ZepEntityReader()` (`backend/app/services/simulation_manager.py:916`) → `filter_defined_entities(graph_id, defined_entity_types, enrich_with_edges=True)` (`:920-924`). That calls `get_all_nodes` → `fetch_all_nodes` → `_fetch_page_with_retry` → facade `node.get_by_graph_id` → `runtime.list_nodes` (`zep_entity_reader.py:243`, `zep_paging.py:129-138`, `backend/app/services/graphiti_client/client.py:100-104`, `backend/app/services/graphiti_client/runtime.py:1808-1824`). Then `get_all_edges` → `fetch_all_edges` → `runtime.list_edges` (`backend/app/services/graphiti_client/runtime.py:1826-1839`). Then the label filter, the tier gate and the edge enrichment. The caller then runs `ensure_dossier_actor_entities` and `select_agent_pool`, where the `related_edges` count is a tie-break (`backend/app/services/simulation_manager.py:456,481`), and the profile generator turns `related_edges`/`related_nodes` into persona context (`backend/app/services/oasis_profile_generator.py:1258-1312`). **Note:** this production call passes neither `actors` nor `ontology` (`backend/app/services/simulation_manager.py:920-924`). Other callers of the reader:

- `GET /api/simulation/entities/<graph_id>` → `backend/app/api/simulation.py:71-76`;
- `GET /entities/<graph_id>/<entity_uuid>` → `get_entity_with_context` (`backend/app/api/simulation.py:102-103`);
- `GET /entities/<graph_id>/by-type/<entity_type>` (`backend/app/api/simulation.py:137-138`);
- `POST /prepare` (count preview, `backend/app/api/simulation.py:515-521`);
- `POST /generate-profiles` (`backend/app/api/simulation.py:1440-1445`);
- the orchestrator reuse check (`backend/app/services/pipeline_orchestrator.py:12431-12432`).

**B. GRAPH tail: resolution** (`backend/app/services/pipeline_orchestrator.py:12594-12609`):
`resolve_entities` → `runtime.all_entity_nodes` → `runtime.embed_texts` → `plan_merges` (≤1200 nodes) or `plan_merges_fast` → `_finalize_clusters` → `runtime.merge_nodes` per victim → audit dict. The orchestrator writes `handoff/entity_merges.json` only when `audit["merges"]` is non-empty and stores `state.options["entity_merges"] = merged_nodes`. Any exception is caught there and logged as "entity resolution skipped" (`:12608-12609`).

**C. RUN feedback** (only when `sim_graph_feedback` is pinned true):
1. `SimulationRunner.start_simulation(enable_graph_memory_update=True, graph_id)` (`backend/app/services/pipeline_orchestrator.py:8804-8808`) → `ZepGraphMemoryManager.create_updater` → `start()` (`backend/app/services/simulation_runner.py:855-868`). [verifier: 8804-8808 is the ensemble-seed path. The main run sets the same kwargs at backend/app/services/pipeline_orchestrator.py:12985-12989. The API route `POST /api/simulation/start` can also enable it from the request body (backend/app/api/simulation.py:1540,1644)]
2. The monitor thread tails `actions.jsonl` and calls `add_activity_from_dict(action_data, platform)` (`backend/app/services/simulation_runner.py:1170-1172,1279-1280`).
3. `_worker_loop` → `_send_batch_activities` → `graph.add` → `_write_typed_edges`; on final failure → `_recover_failed_batch` → re-buffer or `_write_dead_letter`.
4. At the end: `stop_updater` from the runner's `finally` (`backend/app/services/simulation_runner.py:1121-1128`), from stop (`:1720-1726`) and from the orchestrator's confluence barrier after `join_monitor_thread(timeout=30)` (`backend/app/services/pipeline_orchestrator.py:8856-8862`) [verifier: 8856-8862 is the seed-path barrier. The main-run barrier is backend/app/services/pipeline_orchestrator.py:13082-13092], or `stop_all` at cleanup (`backend/app/services/simulation_runner.py:2411-2415`).
5. RUN health then counts the dead-letter lines into `dead_letter_count`, marks health `degraded` and adds an issue (`backend/app/services/pipeline_orchestrator.py:9412-9442`).

**D. REPORT retrieval:**
`ReportAgent.__init__` → `ZepToolsService()` (`backend/app/services/report_agent.py:1672`). The order is:
1. `plan_outline` → `get_simulation_context` (`:9887`) → `insight_forge` global sweep (`:9910`) → `simulation_outcomes` (`:9922`) → `scenario_diff` (`:9940`).
2. The signal pack and causal spine (`:2412-2447`, `:2816-2825`).
3. Per section, the ReACT loop's `_execute_tool` dispatch (`:9553-9700`).

`search_graph` → `client.graph.search(reranker="cross_encoder")`. The facade maps the reranker to recipe `"cross_encoder"` (`backend/app/services/graphiti_client/client.py:316-346`). The runtime downgrades that to `"rrf"` unless a real BGE reranker is active (`backend/app/services/graphiti_client/runtime.py:1663-1684`).

**E. MCP / API:** the `kg_server` singleton calls `search_graph`/`as_of_search`, `trace_cascade`, `get_entity_summary`, `get_entities_by_type`/`get_all_nodes`, `get_all_edges` (centrality) and `get_graph_statistics` (`backend/app/mcp/kg_server.py:145-216`). `POST /api/report/tools/search` → `search_graph` (`backend/app/api/report.py:2116-2122`). `POST /api/report/tools/statistics` → `get_graph_statistics` (`backend/app/api/report.py:2160-2163`).

---

## Data & artifacts

| Artifact | Path pattern | Format / key fields | Writer / reader |
|---|---|---|---|
| Dead-letter queue | `backend/uploads/simulations/_zep_dead_letter/<graph_id>.jsonl` (`zep_graph_memory_updater.py:275-279`, `backend/app/config.py:1080`) | JSONL, one activity per line: `graph_id, platform, dead_lettered_at, combined_text, agent_name, action_type, round, timestamp` (`zep_graph_memory_updater.py:492-501`) | Written by `_write_dead_letter` (append + fsync). Counted by `backend/app/services/pipeline_orchestrator.py:9415-9422`. Replayed and archived as `.replayed-<ts>` by `backend/scripts/replay_zep_dead_letters.py:1-24` |
| Entity merge audit | `<handoff_dir>/entity_merges.json` | `{nodes_scanned, clusters, merged_nodes, threshold, merges:[{survivor_uuid, survivor_name, primary_label, cross_label, victims:[{uuid,name,similarity,label}], execution:[{victim_uuid, rewired, deleted, survivor_uuid, victim_uuid, swapped_for_seed, skipped?/error?}]}]}` (`zep_entity_resolver.py:470-476,532-542`) | Built by `resolve_entities`. Written by the orchestrator only when merges is non-empty (`backend/app/services/pipeline_orchestrator.py:12599-12603`) |
| Retrieval coverage | `handoff/retrieval_coverage.json` (intended) | `{graph_id, surfaced_entity_count, surfaced_entity_uuids, surfaced_community_count, surfaced_edge_types, high_influence_* …}` (`zep_tools.py:1090-1115`) | `flush_coverage` exists (`zep_tools.py:1123-1140`), but nothing calls it, so the file is never written |
| Agent profiles (read) | `backend/uploads/simulations/<sim_id>/reddit_profiles.json` or `twitter_profiles.csv` (`zep_tools.py:2220-2256`) | JSON list or CSV (`name, username, description, user_char`) | Read by `interview_agents` |
| Simulation action logs (read, indirect) | via `SimulationRunner.get_actions/get_timeline/get_agent_stats` | `AgentAction` objects; timeline dicts `{round_num,total_actions,active_agents_count,action_types,...}` (`backend/app/services/simulation_runner.py:1863-1990`) | `simulation_outcomes`, `coalition_map`, `opinion_shift`, `scenario_diff` |

In-memory structures:

- `EntityNode.related_edges` items are `{direction, edge_name, fact, target_node_uuid | source_node_uuid}`. `related_nodes` items are `{uuid,name,labels,summary}` (`zep_entity_reader.py:452-479`).
- The `ZepToolsService` caches are per instance (`zep_tools.py:498-516`). The node and edge snapshot caches live as long as the instance. The search and forge caches are only populated when `REPORT_RETRIEVAL_CACHE` is set.
- `ZepGraphMemoryUpdater` holds the queue and per-platform buffers. A buffer can grow to `MAX_BUFFERED_RETRY` (500) plus new arrivals (`zep_graph_memory_updater.py:466-473`).
- `ZepGraphMemoryManager._updaters` is a class-level, process-wide dict (`zep_graph_memory_updater.py:651`).

---

## Config / env knobs

| Name | Default | Effect | Anchor (read) / (defined) |
|---|---|---|---|
| `ZEP_API_KEY` | `'local-graphiti'` sentinel | Satisfies the constructor guards; the facade ignores it | `zep_entity_reader.py:186-188`, `zep_graph_memory_updater.py:243-246`, `zep_tools.py:491-493` / `backend/app/config.py:1038` |
| `ZEP_MAX_RETRIES` | 2 | `ZepToolsService` attempts per call and per page. **Not** used by `ZepEntityReader` (3) | `zep_tools.py:487,1163,1210` / `backend/app/config.py:1041` |
| `ZEP_RETRY_DELAY_SECONDS` | 2.0 | Base backoff in `ZepToolsService` | `zep_tools.py:488,1164,1211` / `backend/app/config.py:1042` |
| `ZEP_RATE_LIMIT_BUFFER_SECONDS` | 1.0 | Added to a 429 delay | `zep_tools.py:596,1165,1212` / `backend/app/config.py:1043` |
| `ZEP_RATE_LIMIT_MAX_SLEEP_SECONDS` | 90.0 | Cap on a 429 delay | `zep_tools.py:597,1166,1213` / `backend/app/config.py:1044` |
| `GRAPH_MAX_NODES` | 8000 | Node read-back cap (`0` → 8000) | `zep_paging.py:39` / `backend/app/config.py:1259` |
| (edge cap) | 10000 | Hard-coded `_MAX_EDGES`, no knob | `zep_paging.py:28,182` |
| `SIM_TIER_ELIGIBILITY` | true | Turns on the ontology tier gate in `filter_defined_entities` | `zep_entity_reader.py:358` / `backend/app/config.py:1513` |
| `SIM_TIER_FROM_ONTOLOGY` | false | ONT-7 type-level fallback signal (needs an `ontology=` arg) | `zep_entity_reader.py:364` / `backend/app/config.py:578` |
| `ACTOR_EXCLUDE_MEDIA` | true | A media actor row counts as a classification signal (tier 3) | `zep_entity_reader.py:84` / `backend/app/config.py:1368` |
| `GRAPH_RESOLVE_ENTITIES` | **true** | Runs `resolve_entities` after the build | `backend/app/services/pipeline_orchestrator.py:12594` / `backend/app/config.py:1282` |
| `GRAPH_RESOLVE_SIM_THRESHOLD` | 0.88 | Cosine gate for merges | `zep_entity_resolver.py:491` / `backend/app/config.py:1284` |
| `GRAPH_RESOLVE_MAX_NODES` | 1200 | Above this, the O(N) fast planner (`0` → 1200) | `zep_entity_resolver.py:512` / `backend/app/config.py:1289` |
| `SIM_GRAPH_FEEDBACK` | false | Orchestrator enables the memory updater for the run (pinned policy) [verifier: the API route `/api/simulation/start` bypasses this knob (backend/app/api/simulation.py:1540)] | `backend/app/services/pipeline_orchestrator.py:8804-8805` [verifier: seed path; main run at backend/app/services/pipeline_orchestrator.py:12985-12986] / `backend/app/config.py:1385` |
| `SIM_TYPED_FEEDBACK_EDGES` | false | Writes typed LIKED/REPLIED_TO/FOLLOWED… triplets after each batch | `zep_graph_memory_updater.py:534` / `backend/app/config.py:1388` |
| `SIM_INTERVIEW_GRAPH_FEEDBACK` | false | Writes interview answers as `STATED_AT_END_OF_SIM` facts | `zep_graph_memory_updater.py:575`, `zep_tools.py:2156` / `backend/app/config.py:1391-1392` |
| `OASIS_SIMULATION_DATA_DIR` | `backend/uploads/simulations` | Dead-letter root | `zep_graph_memory_updater.py:276` / `backend/app/config.py:1080` |
| `GRAPH_SEARCH_RECIPE` | `rrf` | Only `"mmr"` has an effect in this slice (insight_forge recipe plus semantic de-dup) | `zep_tools.py:540,545` / `backend/app/config.py:347` |
| `GRAPHITI_REMOTE` | false | Query clamp default 380 (remote) vs 1200 (local) | `zep_tools.py:646` / `backend/app/config.py:1345` |
| `GRAPH_QUERY_MAX_CHARS` | 0 (auto) | Overrides the clamp length | `zep_tools.py:647` / `backend/app/config.py:580` |
| `GRAPH_QUERY_CLAMP_SEMANTIC` | true | Semantic clamp vs plain prefix cut | `zep_tools.py:650` / `backend/app/config.py:581` |
| `GRAPH_COMMUNITY_RETRIEVAL` | follows `GRAPH_BUILD_COMMUNITIES` (false) | `faction_brief` uses graph communities vs `coalition_map` | `zep_tools.py:2558` / `backend/app/config.py:1273-1277` |
| `REPORT_RETRIEVAL_CACHE` | False (getattr default) | Cross-section search/forge cache. **Not declared in Config** | `zep_tools.py:522` |
| `REPORT_RETRIEVAL_PARALLEL` | False (getattr default) | Parallel sub-query fan-out. **Not declared in Config** | `zep_tools.py:526` |
| `REPORT_RETRIEVAL_PARALLEL_WORKERS` | 4 (getattr default) | Fan-out thread count. **Not declared in Config** | `zep_tools.py:531` |
| `REPORT_MIN_ACTOR_COVERAGE` | 0.6 (getattr default) | Coverage warning threshold. **Not declared in Config** | `zep_tools.py:552` |
| `GRAPHITI_OP_TIMEOUT_S` (indirect) | 900 (Config) / 1800 (fallback) | Every facade call times out with `TimeoutError`, which paging and `search_graph` retry | `backend/app/services/graphiti_client/runtime.py:128-141,224-245` |
| `GRAPHITI_RERANKER` (indirect) | not `bge` → NoOp | Whether `search_graph`'s `cross_encoder` recipe really reranks or degrades to RRF | `backend/app/services/graphiti_client/runtime.py:1667-1684` |

A grep of `backend/app` and `backend/scripts` finds `REPORT_RETRIEVAL_CACHE`, `REPORT_RETRIEVAL_PARALLEL[_WORKERS]` and `REPORT_MIN_ACTOR_COVERAGE` only inside `zep_tools.py`. `config.py` has no env-wide loader. Setting these env vars therefore has no effect. Only test monkeypatching of `Config` reaches them.

---

## External calls

| Target | Kind | Anchor | Notes |
|---|---|---|---|
| Facade `client.graph.node.get_by_graph_id` / `edge.get_by_graph_id` | Local graph DB (Graphiti/FalkorDB via the bg event loop) | `zep_paging.py:130,201` | Runtime pages from an ordered uuid list. Edges fetch the **full edge set on every page** and slice in Python (`backend/app/services/graphiti_client/runtime.py:1826-1839`) |
| `client.graph.node.get(uuid_=…)` | Graph DB | `zep_entity_reader.py:519`, `zep_tools.py:1257` | No graph_id: tries every graph open in the process (`backend/app/services/graphiti_client/runtime.py:418-423,1841-1858`) |
| `client.graph.node.get_entity_edges(node_uuid=…)` | Graph DB | `zep_entity_reader.py:299` | The same cross-graph candidate scan |
| `client.graph.search(...)` | Graph DB: hybrid BM25 + embedding (local sentence-transformer) | `zep_tools.py:687-690` | Always `reranker="cross_encoder"` |
| `client.graph.add(type="text", data=…)` | Graph write that triggers a **graphiti LLM extraction** pass and embeddings | `zep_graph_memory_updater.py:423-427` | Serialized per graph by the runtime write lock (`backend/app/services/graphiti_client/runtime.py:484-502`) |
| `client.graph.add_triplet(...)` | Graph write (endpoint resolution by name and embedding) | `zep_graph_memory_updater.py:558-562,583-592` | Legacy positional facade path (`backend/app/services/graphiti_client/client.py:243-266`) |
| `runtime.all_entity_nodes / embed_texts / merge_nodes` | Graph DB and local embedding model | `zep_entity_resolver.py:496,502,529` | `merge_nodes` holds the per-graph write lock |
| `runtime.list_communities` | Graph DB (Cypher `HAS_MEMBER`) | `zep_tools.py:2563` | |
| `runtime.causal_paths` / `n_hop_subgraph` | Graph DB (variable-length Cypher) | `zep_tools.py:2735,2738,2754,2756` | Hop bound is clamped to ≤6 in the runtime, default 4 / 2 |
| `get_runtime().run(embedder.create_batch(...))` | Local sentence-transformer (second instance) | `zep_tools.py:986-987` | MMR mode only |
| `LLMClient.chat_json(tier="fast")` | LLM provider | `zep_tools.py:1778-1785` (sub-queries), `:2317-2324` (agent selection), `:2379-2386` (questions) | Each has a deterministic fallback |
| `LLMClient.chat(max_tokens=800)` | LLM provider | `zep_tools.py:2437-2444` | Interview summary; no tier |
| `SimulationRunner.interview_agents_batch(timeout=600)` | IPC to the running OASIS subprocess | `zep_tools.py:2065-2073` | Both platforms when `platform=None` |
| `SimulationRunner.get_actions / get_timeline / get_agent_stats` | Local files via the runner | `zep_tools.py:2461-2462,2497,2774,2804-2807` | |
| Filesystem | Dead-letter append + fsync; profile reads; atomic coverage write (dead) | `zep_graph_memory_updater.py:504-507`, `zep_tools.py:2229-2256`, `zep_tools.py:1134-1135` | |
| Zep Cloud HTTP | **None** | — | `zep_rate_limit` sniffs 429 strings that only the old Zep Cloud SDK produced |

---

## Cross-module edges

**Into this slice (callers):**

- `backend/app/services/simulation_manager.py:19,916-924`: `ZepEntityReader.filter_defined_entities` (main PREPARE read-back). `EntityNode` is used at `:242,300-301` for stand-ins.
- `backend/app/api/simulation.py:12,71-76,102-103,137-138,515-521,1440-1445`: the entity routes, the prepare preview and generate-profiles.
- `backend/app/services/pipeline_orchestrator.py:12431-12432` (reuse health check); `:12597-12598` (`resolve_entities`); `:68,8860,13090` (`ZepGraphMemoryManager.stop_updater`); `:9413-9441` (dead-letter count).
- `backend/app/services/oasis_profile_generator.py:54,1258-1312` and `backend/app/services/simulation_config_generator.py:42,872` consume `EntityNode.related_edges/related_nodes`.
- `backend/app/services/graph_pruner.py:31,60`: `actor_alias_map`, `canonical_norm_set`.
- `backend/app/services/simulation_runner.py:24,860,1124,1172,1279-1280,1723,2413`: memory manager lifecycle and `add_activity_from_dict`.
- `backend/app/services/report_agent.py:34-35,1672,2192-2193,2412-2447,2816-2825,9553-9700,9887,9910-9940`: the ZepToolsService tools and `compact_graph_query`.
- `backend/app/mcp/kg_server.py:90-103,145-216`: MCP singleton wrapper.
- `backend/app/api/report.py:2116-2122,2160-2163`: `/tools/search`, `/tools/statistics`.
- `backend/app/services/graph_builder.py:24,2459-2462,2610-2611`: `fetch_all_nodes/fetch_all_edges` for graph info and UI data.
- `backend/app/services/__init__.py:8,26-29`: re-exports.
- Scripts: `backend/scripts/replay_zep_dead_letters.py`, `backend/scripts/test_zep_rate_limit.py:9-10`, `backend/scripts/test_graphiti_services.py:23-25`, `backend/scripts/test_graphiti_migration.py:22`.

**Out of this slice:**

- `graphiti_client` (`Zep`, `InternalServerError`, `ApiError`, `get_runtime`, `LocalSentenceTransformerEmbedder`).
- `backend/app/utils/actors.py`: `entity_archetype`, `entity_simulation_tier`, `is_agent_eligible`, `is_media_entity`, `match_actor`, `extract_actor_rows`, `normalize_name`, `relation_polarity`.
- `backend/app/utils/dates.py:38` (`parse_as_of`).
- `backend/app/utils/llm_client.py` (`LLMClient`).
- `backend/app/utils/atomic.py` (`write_json_atomic`).
- `backend/app/services/simulation_runner.py` (`SimulationRunner`).
- `backend/app/config.py` (`Config`).

---

## Invariants, gates, validation

- **Tier-gate NO-OP:** a node is dropped only if an explicit classification (node attribute > actor row > ontology type) exists **and** `is_agent_eligible` is false (`zep_entity_reader.py:417-431`). With no signal, every typed node is kept.
- **Typed-node-only read-back:** nodes whose labels are only `Entity`/`Node` are never returned as entities (`zep_entity_reader.py:398-402`).
- **Paging cannot loop:** a page with zero new uuids stops pagination (`zep_paging.py:156-162,225-231`). The totals are capped at 8000 nodes (configurable) and 10000 edges, with a WARNING on truncation (`zep_paging.py:163-166,235-238`).
- **Resolver over-merge guards** (`zep_entity_resolver.py:258-290,241-256,324-342`):
  - two distinct canonicals are never merged;
  - two actor seeds are never merged; [verifier: this is a pair-level filter only. A non-seed bridge node can union two same-name actor seeds transitively, and `_finalize_clusters` splits only components with two *distinct* canonical norms, so the plan can list an actor seed as a victim. The runtime then refuses it with "canonical actor seed cannot be a merge victim" (zep_entity_resolver.py:264-265,324-325; backend/app/services/graphiti_client/runtime.py:2080-2085)]
  - entity-type seeds are never candidates;
  - one component never holds two distinct typed labels;
  - a component that ends up with ≥2 canonicals is split.
  The runtime adds a second layer: actor and entity-type seeds can never be victims, and an alias seed may merge only into its own actor (`backend/app/services/graphiti_client/runtime.py:2063-2101`).
- **Survivor determinism:** `_pick_survivor` uses a total order ending in name and uuid (`zep_entity_resolver.py:448-455`).
- **Lock discipline in the updater:** `_recover_failed_batch` must not take `_buffer_lock`, because both callers already hold it and the lock is not reentrant (`zep_graph_memory_updater.py:453-456,465`).
- **Feedback containment (Foglamp WP1/I-11):** the episode feedback, typed edges and interview facts are each gated off by default (`backend/app/config.py:1379-1392`; `zep_graph_memory_updater.py:534,575`; `zep_tools.py:2155-2156`). [verifier: only the episode gate reads the pinned policy. The typed-edge and interview gates read live `Config`, although the policy snapshot pins `sim_typed_feedback_edges` and `sim_interview_graph_feedback`, which nothing reads (backend/app/services/pipeline_orchestrator.py:789-792). The episode gate itself is bypassable through `POST /api/simulation/start` (backend/app/api/simulation.py:1540)]
- **search_graph error taxonomy (F-4-6):** expected backend errors and 429s degrade to keyword search marked `degraded=True`. Unknown exceptions are re-raised (`zep_tools.py:736-747`).
- **Bounded memory:** the failed-batch re-buffer is capped at 500 per platform, with the overflow dead-lettered (`zep_graph_memory_updater.py:232,466-476`).

---

## Failure modes & recovery

| Failure | Behavior | Anchor |
|---|---|---|
| Transient page error (connection, timeout, OSError, InternalServerError, 429) | Up to 3 attempts (paging defaults) or 2 (ZepToolsService), with exponential sleep, then raise | `zep_paging.py:66-97`; `zep_tools.py:1160-1167` |
| Graphiti op hangs | The runtime cancels after `GRAPHITI_OP_TIMEOUT_S` (900 s) and raises `TimeoutError`, which paging **retries**. A reader page fetch can block for up to about 3×900 s plus backoff | `backend/app/services/graphiti_client/runtime.py:224-245`; `zep_paging.py:71` |
| Non-transient error in paging | Raised at once. `filter_defined_entities` lets it propagate to the caller (PREPARE fails) | `zep_paging.py:70-74`; `zep_entity_reader.py:368-372` |
| `get_node_edges` / `get_entity_with_context` errors | Return `[]` / `None` with a log | `zep_entity_reader.py:315-317,577-579` |
| Embedding failure in resolution | Falls back to exact-signal matching only | `zep_entity_resolver.py:501-505` |
| Single merge failure | Isolated. Recorded as `{"victim_uuid", "error"}` in the cluster's `execution` list | `zep_entity_resolver.py:533-536` |
| `all_entity_nodes` failure in resolution | Not caught inside `resolve_entities`; the orchestrator catches it and logs "entity resolution skipped" | `zep_entity_resolver.py:496`; `backend/app/services/pipeline_orchestrator.py:12608-12609` |
| Feedback batch fails 3× while running | Re-buffered to the end of the buffer (cap 500) and retried on the next ≥5-buffer trigger or the final flush | `zep_graph_memory_updater.py:439-448,464-476` |
| Feedback batch fails at shutdown | Dead-lettered (JSONL + fsync). The RUN health check reports it; replay with `replay_zep_dead_letters.py` | `zep_graph_memory_updater.py:477-479,483-513`; `backend/app/services/pipeline_orchestrator.py:9437-9441` |
| Dead-letter write itself fails | ERROR log; the activities are lost | `zep_graph_memory_updater.py:512-513` |
| Typed-edge / interview-fact write fails | DEBUG log, skipped / returns False | `zep_graph_memory_updater.py:563-564,594-596` |
| Semantic search backend error | Keyword `_local_search` over the full cached snapshot, `degraded=True`. If that also fails, an empty result | `zep_tools.py:736-745,871-880` |
| Unknown search error | Re-raised. In serial `insight_forge` this aborts the whole tool, and `ReportAgent._execute_tool` turns it into the string `工具执行失败: …` | `zep_tools.py:746-747,1582-1588`; `backend/app/services/report_agent.py:9702-9704` |
| LLM failure in sub-query / selection / question / summary generation | Deterministic fallbacks: 4 query variants; the first N agents; 3 fixed questions; a joined name list | `zep_tools.py:1791-1801,2339-2344,2390-2396,2447-2450` |
| Interview env offline | `ValueError` gives a summary string; `success=False` gives a summary string | `zep_tools.py:2078-2082,2171-2175` |
| Community read failure / no communities | `faction_brief` degrades to `coalition_map` (or a placeholder without a sim id) | `zep_tools.py:2561-2570` |
| Traversal failure | Placeholder string, never raises | `zep_tools.py:2724-2728,2766-2768` |

---

## Surprises

1. **Doc drift: `GRAPH_RESOLVE_ENTITIES` default.** The resolver docstring says "default off → never invoked" (`zep_entity_resolver.py:13-14`). Config defaults it to **true** (`backend/app/config.py:1282`), and the orchestrator comment agrees with Config (`backend/app/services/pipeline_orchestrator.py:12592-12594`).
2. **Suspected: the fast planner drops the dossier bypass.** `plan_merges` lets a dossier-alias match skip the cosine gate (`zep_entity_resolver.py:285-289`). `plan_merges_fast` rejects any pair with `cos < threshold` with no dossier exception (`zep_entity_resolver.py:422-426`). Its docstring nevertheless promises that zero-overlap alias forms "still land in the same bucket and get merged" (`zep_entity_resolver.py:360-362`). On graphs over 1200 nodes (the default cap) with working embeddings, "China" ↔ "MOFCOM"-style dossier merges probably fail.
3. **Suspected: the fast planner compares a star, not all pairs.** Only `idxs[0]` is compared with the other bucket members (`zep_entity_resolver.py:411-413`). If the first member is refused for some pair (label conflict, canonical conflict, cosine), the remaining members of that bucket are never compared with each other in that bucket.
4. **Audit similarity defaults to 1.0.** `_sim` returns 1.0 for pairs that were unioned only transitively (`zep_entity_resolver.py:315-316`). So `victims[].similarity` in `entity_merges.json` can show 1.0 for pairs never compared. The same default makes the canonical-split step hand uncompared members to the *first* canonical in `canon_members` (`zep_entity_resolver.py:334`).
5. **`resolve_entities` can raise despite its docstring.** The docstring says "Any failure degrades to a no-op partial result rather than raising" (`zep_entity_resolver.py:485-488`). `runtime.all_entity_nodes` and the planners are not wrapped (`zep_entity_resolver.py:496,512-522`); only the orchestrator's try/except saves it.
6. **The production read-back never passes `actors` or `ontology`.** Every production caller of `filter_defined_entities` omits them (`backend/app/services/simulation_manager.py:920-924`; `backend/app/api/simulation.py:72-76,517-521,1441-1445`; `backend/app/services/pipeline_orchestrator.py:12432`). Only tests pass `ontology=` (`backend/tests/test_audit_fixes_graph.py:285,292,303`). In production the actor-row branch (`zep_entity_reader.py:78-88`) and ONT-7 (`:363-365,419-422`) are therefore dead. The tier gate fires only on node-attribute archetype/tier.
7. **Nondeterministic ordering feeds prompts.** `related_node_uuids` (`zep_entity_reader.py:447,472`) and `insight_forge`'s `entity_uuids` (`zep_tools.py:1604,1623`) are sets of uuid strings, so the order of `related_nodes` and `entity_insights` changes with `PYTHONHASHSEED`. The KG-11 comment's "byte-identical" claim covers the edges only (`zep_entity_reader.py:377-380`).
8. **Stale comment: the updater sends while holding the lock.** The comment "释放锁后再发送" ("send after releasing the lock") at `zep_graph_memory_updater.py:393` is wrong. `_send_batch_activities` (up to 3 `graph.add` attempts, each a graphiti LLM extraction, with sleeps of 2 s and 4 s) and the 0.5 s `SEND_INTERVAL` both run inside `with self._buffer_lock` (`zep_graph_memory_updater.py:384-396`). `_recover_failed_batch`'s docstring does acknowledge this (`:453-456`).
9. **Suspected shutdown race in the updater.** `stop()` sets `_running=False` and runs `_flush_remaining` on the caller thread while the worker may still be running (`zep_graph_memory_updater.py:301-309`). Suppose the worker has already dequeued an activity and is blocked on `_buffer_lock` while the flush sends and clears. It then appends into a cleared buffer, the buffer is below `BATCH_SIZE` so nothing is sent, and the worker exits because the queue is empty and `_running` is False (`:376,384-392`). That activity would be lost **without** being dead-lettered or counted.
10. **Suspected: `_failed_items` overcounts.** Items re-buffered after a failure and later sent successfully are still counted in `_failed_items` (`zep_graph_memory_updater.py:447`), so it is not a count of "lost" items as its comment claims (`:269`).
11. **Suspected double episode on a typed-edge exception.** `_write_typed_edges` runs inside the `graph.add` retry `try` (`zep_graph_memory_updater.py:422-437`). An exception raised in it but outside its own inner try, for example `action_args` being a non-dict so that `.get` raises (`:543`), would be caught by the retry handler. The batch's episode, already added, would then be **re-added**. [verifier: the mechanism is real, but this example cannot happen. For every action type in `_TYPED_EDGE_MAP`, the describer already calls `self.action_args.get` inside `to_episode_text`, before the try, so a non-dict `action_args` raises there first. `None` is handled by `(act.action_args or {})`. A reachable trigger is a non-str truthy `agent_name`, where `.strip()` raises at line 547 (zep_graph_memory_updater.py:417,543,547)]
12. **Suspected batch loss on a malformed `action_args`.** `to_episode_text` runs before the retry try (`zep_graph_memory_updater.py:417`). If `action_args` is `None` (`data.get("action_args", {})` returns None when the key holds null, `:367`), the describers' `.get` raises AttributeError. The batch has already been sliced out of the buffer (`:391-392`), so it is lost with only `工作循环异常` logged (`:401-403`). [verifier: low likelihood. The OASIS action logger writes `action_args or {}`, so a null `action_args` does not come from the normal writer (backend/scripts/action_logger.py:60,249). On the `_flush_remaining` path the same exception escapes `stop()` before the buffers are cleared and the worker is joined, and `stop_updater` then skips the `del` (zep_graph_memory_updater.py:306,613-621,688-689)]
13. **Final flush sends one giant episode.** `_flush_remaining` sends each platform's whole buffer as a single `graph.add` (`zep_graph_memory_updater.py:613-618`). After repeated failures that can be 500 or more lines in one episode.
14. **The dead-letter file is graph-scoped, not sim-scoped.** Comments call it "sim-scoped" (`zep_graph_memory_updater.py:273-274`; `backend/scripts/replay_zep_dead_letters.py:3`), but the path is keyed by `graph_id` (`zep_graph_memory_updater.py:275-279`), so scenario forks on the same graph share one file. The `combined_text` field holds a single activity's text, not a batch.
15. **Feedback text is always Chinese.** The episode templates (`zep_graph_memory_updater.py:63-198`), the interview prefix (`zep_tools.py:2038-2048`) and the sub-query fallbacks (`zep_tools.py:1796-1801`) are Chinese whatever the run language. Interview key-quote extraction splits only on `。！？` (`zep_tools.py:2123`), so English answers mostly yield no key quotes.
16. **`stop_all` is one-shot per process.** `_stop_all_done` is set and never reset (`zep_graph_memory_updater.py:693-701`). `get_stats` and `get_all_stats` have no callers in `backend/app`.
17. **`GRAPH_SEARCH_RECIPE` is ignored by plain `search_graph`.** `search_graph` always passes `reranker="cross_encoder"` (`zep_tools.py:681`). The facade maps that to recipe `cross_encoder` whenever `recipe` is None (`backend/app/services/graphiti_client/client.py:335-337`), so the runtime's `_default_recipe()` (GRAPH_SEARCH_RECIPE) is never consulted (`backend/app/services/graphiti_client/runtime.py:1663`). With the default NoOp reranker it degrades to RRF; with `GRAPHITI_RERANKER=bge` it really reranks. The docstring claim "None 时由 runtime 用 Config.GRAPH_SEARCH_RECIPE … 决定" is therefore drift (`zep_tools.py:633-634,674-675`). Only `insight_forge`'s explicit `recipe="mmr"` honors the knob.
18. **Ghost knobs.** `REPORT_RETRIEVAL_CACHE`, `REPORT_RETRIEVAL_PARALLEL`, `REPORT_RETRIEVAL_PARALLEL_WORKERS` and `REPORT_MIN_ACTOR_COVERAGE` are read through `getattr` (`zep_tools.py:522,526,531,552`) but are not declared in `backend/app/config.py`. Env values never reach them, so the cache and the parallel fan-out are effectively always off.
19. **Dead observation code.** `flush_coverage`/`get_coverage_report` (`zep_tools.py:1073-1140`) and `search_from_cache` (`zep_tools.py:882-898`) have no callers in `backend/app`. `record_coverage` keeps accumulating, but its output is never written.
20. **Snapshot caches never invalidate.** `invalidate_search_cache` clears only the search and forge caches (`zep_tools.py:558-571`). `_nodes_cache`/`_edges_cache` (`zep_tools.py:1153-1156,1200-1203`) live for the whole instance. The MCP server keeps one process-wide instance (`backend/app/mcp/kg_server.py:90-103`), so suspected: its `get_all_nodes`/`get_all_edges`/`panorama`/`_local_search` data goes stale after rebuilds, merges or feedback writes on the same `graph_id`. A degraded fallback result is also cached under the normal key when caching is on (`zep_tools.py:773-775`).
21. **Suspected context blow-up in `panorama_search`.** `PanoramaResult.to_text()` lists **every** node name (`zep_tools.py:329-333`), up to `GRAPH_MAX_NODES` (8000). The edge list is the first 40 in DESC-uuid order, not by relevance (`zep_tools.py:339`). The docstring "完整版本，不截断" ("full version, not truncated") contradicts the 40-edge cut.
22. **Doc drift in `trace_cascade`.** The empty-result message says "≤6 跳" ("≤6 hops") (`zep_tools.py:2741`). `causal_paths` is called with the default `max_hops=4` (`zep_tools.py:2735`; `backend/app/services/graphiti_client/runtime.py:1294-1306`); 6 is only the runtime's clamp ceiling.
23. **Asymmetric failure handling in `insight_forge`.** The parallel fan-out swallows per-query exceptions (`zep_tools.py:1575-1579`), but the default serial path does not (`zep_tools.py:1582-1588`). `_call_with_retry` also retries *every* exception, programming bugs included, before the F-4-6 classifier re-raises (`zep_tools.py:586-607`).
24. **`_generate_sub_queries` trusts the LLM's shape.** If `sub_queries` comes back as a string, `[:max_queries]` slices characters and each character becomes a sub-query (`zep_tools.py:1787-1789`). The selection step's `0 <= idx < len` raises TypeError on string indices and falls back to the first N agents (`zep_tools.py:2332-2344`).
25. **`coalition_map` semantics.** A shared target of *any* interaction, including MUTE and DISLIKE, puts agents in the same "faction" (`zep_tools.py:2504-2536`). One popular post can therefore collapse most agents into one cluster. The `graph_id` parameter is unused, and `get_actions(limit=100000)` silently truncates larger logs (`zep_tools.py:2497`).
26. **Inconsistent retry budgets.** `ZepEntityReader` paging uses the module default of 3 attempts (`zep_entity_reader.py:243`), while `ZepToolsService` uses `Config.ZEP_MAX_RETRIES` (2) (`zep_tools.py:1163`). With `ZEP_MAX_RETRIES=0`, `ZepToolsService` paging raises `ValueError` (`zep_paging.py:60-61`) and `_call_with_retry` would `raise None`, a TypeError (`zep_tools.py:582-611`).
27. **Paging cost on the local backend (outside the slice, it affects it).** `runtime.list_edges` fetches **all** edges on every page call and slices in Python (`backend/app/services/graphiti_client/runtime.py:1826-1839`). `fetch_all_edges` at page size 100 is therefore O(pages × E): about 100 full-edge fetches for 10k edges. `list_nodes` re-lists all node uuids for each page (`backend/app/services/graphiti_client/runtime.py:1811-1824`).
28. **Vestigial rate-limit module.** `zep_rate_limit` matches Zep Cloud SDK exception text (`zep_rate_limit.py:14-23`). The local facade raises nothing of that shape, so the 429 branches are effectively dead unless a remote Graphiti produces such strings. `x-ratelimit-reset` is assumed to be an epoch (`zep_rate_limit.py:45-47`).
29. **The MMR embedder duplicates the model.** In MMR mode `_get_embedder` builds a second `LocalSentenceTransformerEmbedder` per `ZepToolsService` (`zep_tools.py:966-967`), which loads its own model instance (`backend/app/services/graphiti_client/embedder.py:226-241`). One failure disables MMR for the rest of that instance (`zep_tools.py:991-994`).
30. **Day-granular as-of in `panorama_search`.** `parse_as_of` keeps only the date part of ISO timestamps (`backend/app/utils/dates.py:22,57-59`). Edge `valid_at`/`invalid_at` strings are therefore compared at midnight UTC, and intraday ordering is lost (`zep_tools.py:1863-1866`).
31. **Architecture doc drift.** `DRF_ARCHITECTURE.md:753` and `ARCHITECTURE_MAP.md:230` name the class `GraphMemoryUpdater`; the code has `ZepGraphMemoryUpdater` (`zep_graph_memory_updater.py:201`). Several stale anchors in `DRF_ARCHITECTURE.md`:

    | Doc says | Code is at |
    |---|---|
    | `to_episode_text` at `:24-45` (`DRF_ARCHITECTURE.md:755`) | `zep_graph_memory_updater.py:34-61` |
    | dead-letter at `pipeline_orchestrator.py:4835` (`DRF_ARCHITECTURE.md:757`) | `backend/app/services/pipeline_orchestrator.py:9412-9441` |
    | `resolve_entities :418` / `plan_merges :179` / `plan_merges_fast :311` (`DRF_ARCHITECTURE.md:699-702`) | `zep_entity_resolver.py:480,200,352` |
    | resolution orchestrated at `:6940-6955` (`DRF_ARCHITECTURE.md:699-700`) | `backend/app/services/pipeline_orchestrator.py:12590-12609` |
    | `ZepToolsService` instantiated at `report_agent.py:1644` (`DRF_ARCHITECTURE.md:1131`) | `backend/app/services/report_agent.py:1672` |
    | `trace_cascade` at `:2716` (`DRF_ARCHITECTURE.md:1134,1566`) [verifier: the doc line is DRF_ARCHITECTURE.md:1135, not 1134 (DRF_ARCHITECTURE.md:1135)] | `zep_tools.py:2719` |

    `DRF_ARCHITECTURE.md:756-759` also says the graph "keeps evolving while the simulation runs". With the default `SIM_GRAPH_FEEDBACK=false` that does not happen (`backend/app/config.py:1385`). [verifier: that sentence is not drift. The doc conditions it on "when `SIM_GRAPH_FEEDBACK` is on" (DRF_ARCHITECTURE.md:753-758; ARCHITECTURE_MAP.md:230). A real stale anchor the table misses: the confluence barrier is cited as `:7275-7287` (DRF_ARCHITECTURE.md:761), while the code is at backend/app/services/pipeline_orchestrator.py:13076-13092. The doc anchor for `trace_cascade :2716` is DRF_ARCHITECTURE.md:1135, not 1134. ARCHITECTURE_MAP.md also says `GraphMemoryUpdater` at ARCHITECTURE_MAP.md:230, and DRF_ARCHITECTURE.md repeats the name at :886 and :1438]

---

## Verification

An adversarial verifier checked this map against the code on `main` on 2026-10-11. The checks were read-only and ran no pipelines.

**Verdict counts (46 statements checked).** 38 confirmed, 8 imprecise, 0 refuted, 0 unverifiable. The 46 are the 15 key claims, the 19 key surprises and 12 extra Walkthrough and Control-flow statements. Of the 12 extras, 9 were confirmed and 3 were imprecise.

### Non-confirmed statements and corrections

1. **Key claim: the tier gate drops a node only when an explicit archetype/tier signal exists and is ineligible** (imprecise).
   - An `actors.json` row also counts as a signal when it is a media entity under `ACTOR_EXCLUDE_MEDIA`, even with no archetype or tier (`zep_entity_reader.py:80-88`).
   - The gate only runs when `SIM_TIER_ELIGIBILITY` is set (default true) (`zep_entity_reader.py:358,417`).
   - Nodes are also dropped earlier, by the `defined_entity_types` label filter (`zep_entity_reader.py:405-408`).
2. **Key claim and invariant: the resolver never merges two actor seeds** (imprecise).
   - The actor-seed and `entity_type` checks are **pair-level** only (`zep_entity_resolver.py:262-265,414-417`).
   - A non-seed bridge can union two same-name actor seeds transitively. `_finalize_clusters` splits only components that hold two *distinct* canonical norms (`zep_entity_resolver.py:324-325`), so a plan can list an actor seed as a victim.
   - The runtime refuses that merge (`backend/app/services/graphiti_client/runtime.py:2063-2101`). The protection is real, but it is enforced at execution, not by the planner.
   - Survivor ranking: actor seed (0), then unseeded (1), then `actor_alias` seed (2) (`zep_entity_resolver.py:48-55`).
3. **Key claim: the updater only runs when the pinned `sim_graph_feedback` policy is true** (imprecise).
   - The cited `backend/app/services/pipeline_orchestrator.py:8804-8807` is the ensemble-seed path inside `_run_one_seed` (`backend/app/services/pipeline_orchestrator.py:8762`). The main RUN path is `backend/app/services/pipeline_orchestrator.py:12985-12989`, and its barrier is at `:13082-13092`.
   - `POST /api/simulation/start` takes `enable_graph_memory_update` from the request body with no policy or `SIM_GRAPH_FEEDBACK` check (`backend/app/api/simulation.py:1540,1621-1645`).
   - The typed-edge and interview gates read live `Config`, not the pinned snapshot (`zep_graph_memory_updater.py:534,575`; `zep_tools.py:2156`; snapshot at `backend/app/services/pipeline_orchestrator.py:789-792`).
4. **Key surprise and map Surprise 11/12: typed-edge exception re-adds the episode; `None` action_args loses the batch** (imprecise).
   - The re-add mechanism is real (`zep_graph_memory_updater.py:422-437`).
   - The non-dict `action_args` example cannot happen. Every `_TYPED_EDGE_MAP` action's describer calls `self.action_args.get` inside `to_episode_text` first, before the try (`zep_graph_memory_updater.py:417`), and `None` is guarded by `(act.action_args or {})` (`:543`). A reachable trigger is a non-str truthy `agent_name`, where `.strip()` raises (`:547`).
   - The `None`-args batch loss is structurally possible but unlikely, because the action logger writes `action_args or {}` (`backend/scripts/action_logger.py:60,249`).
5. **Key surprise and map Surprise 31: doc drift** (imprecise).
   - The class name and the stale anchors are confirmed (`DRF_ARCHITECTURE.md:700,753,755,757,1131,1135,1566`; `ARCHITECTURE_MAP.md:230`).
   - The "keeps evolving while the simulation runs" sentence is *conditioned* on "when `SIM_GRAPH_FEEDBACK` is on" (`DRF_ARCHITECTURE.md:753-758`), so it is not drift.
   - The `trace_cascade :2716` doc line is 1135, not 1134.
   - Missed stale anchor: the confluence barrier is cited as `:7275-7287` (`DRF_ARCHITECTURE.md:761`). The code is at `backend/app/services/pipeline_orchestrator.py:13076-13092`.
6. **Map Purpose §3, Control flow C.1/C.4 and the `SIM_GRAPH_FEEDBACK` config row** (imprecise). They anchor only the seed path (`backend/app/services/pipeline_orchestrator.py:8803-8808,8856-8862`) and omit the main path (`:12985-12989,13082-13092`) and the API bypass (`backend/app/api/simulation.py:1540`).
7. **Map §6.3 `_local_search` scoring** (imprecise).
   - `match_score` returns 100 *instead of* keyword points on a whole-query hit. It does not return 100 plus keyword points (`zep_tools.py:809-822`).
   - On an exception, facts gathered before it are kept, so the result is not necessarily empty (`zep_tools.py:824-880`).
8. **Map §6.6 `panorama_search` "same keyword relevance as `_local_search`"** (imprecise). Panorama's score is additive: 100 plus 10 per keyword (`zep_tools.py:1892-1900`). `_local_search` uses an early return (`zep_tools.py:815-816`).

### Confirmed spot-checks (extra statements)

- `_UnionFind.union` makes root(a) the parent (`zep_entity_resolver.py:194-197`).
- `actor_alias_map`: the later row wins (`zep_entity_resolver.py:94`).
- Reader `get_node_edges` passes no `graph_id`, and the runtime returns the first open graph with any edges (`backend/app/services/graphiti_client/runtime.py:418-423,1860-1874`).
- `_flush_remaining` sends each platform's whole buffer as one batch (`zep_graph_memory_updater.py:613-618`).
- Interview key quotes: the 3 longest 20–150-char sentences, split only on `。！？` (`zep_tools.py:2123-2131`).
- `n_hop_subgraph` defaults to 2 hops with limit 60 (`backend/app/services/graphiti_client/runtime.py:1383-1384`). `list_communities` takes ≤200 (`:1240`).
- `merge_nodes` seed guards (`backend/app/services/graphiti_client/runtime.py:2063-2101`).
- `GRAPHITI_OP_TIMEOUT_S` is 900 in Config with a 1800 fallback, and raises `TimeoutError` (`backend/app/services/graphiti_client/runtime.py:128-141,224-245`; `backend/app/config.py:1350`).
- `_generate_interview_summary` uses `llm.chat(max_tokens=800)` with no tier (`zep_tools.py:2437-2444`).
- The `_load_agent_profiles` path resolves to the same `backend/uploads/simulations` (`zep_tools.py:2220-2223`; `backend/app/config.py:1080`).

### Omissions (significant behavior the map did not cover)

1. **The API route bypasses feedback containment.** `POST /api/simulation/start` can create a `ZepGraphMemoryUpdater` whatever `SIM_GRAPH_FEEDBACK` or the pinned policy says (`backend/app/api/simulation.py:1540,1621-1645`). The frontend only declares `startSimulation` and has no caller (`frontend/src/api/simulation.js:84-86`).
2. **Pinned typed-edge and interview policies are never read.** `capture_safety_policy_v1` pins `sim_typed_feedback_edges` and `sim_interview_graph_feedback` (`backend/app/services/pipeline_orchestrator.py:789-792`). The gates read live `Config` instead (`zep_graph_memory_updater.py:534,575`; `zep_tools.py:2156`), so a reload with a changed env changes semantics for runs already admitted.
3. **The canonical split prefers *uncompared* canonicals.** `_sim` defaults to 1.0, which beats any real cosine. A member compared with canonical B (for example cos 0.95) but never compared with canonical A is assigned to A, not just "the first canonical" (`zep_entity_resolver.py:315-316,334`).
4. **The activity queue is unbounded and the final flush is huge even without failures.**
   - `Queue()` has no cap (`zep_graph_memory_updater.py:251`), and the worker sends 5 at a time under the lock, each send a full LLM extraction (`:384-396`). The backlog can grow during a run.
   - At `stop()`, `_flush_remaining` drains the whole backlog into the buffers and sends each platform's buffer as one episode (`:601-618`).
5. **An exception in `_flush_remaining` escapes `stop()`.** A send-path exception raised outside the retry try (for example `to_episode_text`) propagates out of `stop()` before the buffers are cleared and the worker is joined. `ZepGraphMemoryManager.stop_updater` then skips `del cls._updaters[...]` (`zep_graph_memory_updater.py:301-309,613-621,686-689`).
6. **All LLM prompts in the toolkit are Chinese, not just the fallbacks.** This covers sub-query generation (`zep_tools.py:1757-1773`), agent selection (`:2289-2312`), question generation (`:2356-2374`) and the summary (`:2413-2434`). On English graphs, sub-queries may come back in Chinese, which weakens the BM25 leg.
7. **The dead-letter health count is graph-scoped across runs.** RUN health counts every line in `_zep_dead_letter/<graph_id>.jsonl`, so a run on a reused graph inherits earlier runs' dead letters into `dead_letter_count` and a `degraded` health (`backend/app/services/pipeline_orchestrator.py:9414-9441`).
8. **`coalition_map`/`opinion_shift` truncation keeps the newest actions.** `get_actions(limit=100000)` sorts by timestamp descending and slices, so the *oldest* actions are dropped (`backend/app/services/simulation_runner.py:1858,1894-1895`).
