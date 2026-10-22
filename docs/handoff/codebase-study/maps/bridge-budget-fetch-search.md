# bridge-budget-fetch-search — research_budget.py, cached_fetch.py, search_tools.py

Slice owner files (all lines read):

| File | Lines | Role |
|---|---|---|
| `deerflow_bridge/research_budget.py` | 1–1508 | Stdlib-only SQLite control plane: tool-attempt/network budgets, negative/positive result ledgers, single-flight claims, fetched-source provenance, provider circuit breaker, model-call and subagent leases, telemetry JSON export |
| `deerflow_bridge/cached_fetch.py` | 1–854 | `web_fetch` DeerFlow tool: source-policy gate, budget admission, 72 h disk cache, single-flight, provider failover chain Firecrawl → Jina → Exa → direct HTTP |
| `deerflow_bridge/search_tools.py` | 1–746 | `web_search` DeerFlow tool: env-key provider dispatch Serper > Tavily > Firecrawl > DDG, 6 h disk cache, budget admission, single-flight, Firecrawl spend/rate guards, denied-domain row filtering |

Code is ground truth; the deployed copies `deer-flow/research_budget.py`, `deer-flow/cached_fetch.py`, `deer-flow/search_tools.py` were byte-identical to the bridge sources at study time (checked with `cmp`).

---

## Purpose & position in the pipeline

These three modules are the **tool layer of the research stage** (stage 1 of the pipeline). The Flask orchestrator (`backend/app/services/pipeline_orchestrator.py`) launches research subprocesses (`deerflow_research.py`, run from the deployed `deer-flow/` directory). Before launch it copies the three modules next to the deployed script (`backend/app/services/pipeline_orchestrator.py:1359-1362`, `:1530-1533`; `setup.sh:597` does the same at install time). DeerFlow's config reflection then imports the tools by bare module name: `use: search_tools:web_search_tool` (`deerflow_bridge/config.yaml:730-735`) and `use: cached_fetch:web_fetch_tool` with `timeout: 30` (`deerflow_bridge/config.yaml:799-802`).

- **search_tools.py** gives the agent one `web_search` tool. It picks a backend at call time from whichever API key is set, then hands the call to DeerFlow's own community tool, or for Firecrawl to its own HTTP client.
- **cached_fetch.py** gives the agent one `web_fetch` tool. It wraps the providers in a disk cache and a failover chain.
- **research_budget.py** is the shared, cross-process SQLite "control plane" that both tools call for admission and accounting. The tool budget is keyed by `RESEARCH_BUDGET_DB`. The control plane also provides **model-call and subagent concurrency leases**, keyed by `RESEARCH_MODEL_LEASE_DB`. DeerFlow middleware patches (`deerflow_bridge/patches/middlewares/model_concurrency_middleware.py:25-53`) and `deerflow_bridge/deerflow_research.py:4549-4557` use those leases.

The v3 "linear" engine skips the LangChain tool objects. It calls `search_tools.web_search_impl` and `cached_fetch.cached_fetch(url, cached_fetch._resilient_fetch, …)` directly (`deerflow_bridge/research_gateway.py:3390-3407`). The legacy LangGraph engine reaches the same code through the registered tools. Both engines therefore share the same caches, budgets and provider chain.

The orchestrator owns budget **epochs**: one SQLite ledger per pipeline task, at most `RESEARCH_BUDGET_MAX_EPOCHS` (default 3) (`backend/app/services/pipeline_orchestrator.py:1815-1903`). It injects the ledger env contract into each research process (`backend/app/services/pipeline_orchestrator.py:1986-2026`, `:2379-2410`). It then reads the exported telemetry JSON before launch and after research (`:1764-1798`, `:10583-10605`).

Note on "$ budget": **no dollar or token accounting lives in this slice.** The budgets here count **tool calls**: attempts, network searches and network fetches. The Firecrawl spend guards are per-process call counters (`deerflow_bridge/cached_fetch.py:62-65`, `deerflow_bridge/search_tools.py:75-78`). Token budgets live elsewhere, for example `RESEARCH_LINEAR_BUDGET_UNITS` in the v3 engine (`.env.example:155`).

---

## Walkthrough (source order)

### A. `deerflow_bridge/research_budget.py`

**Module docstring (`:1-14`).** States the design contract. The module is stdlib-only and copied next to the deployed script. It is enabled only when `RESEARCH_BUDGET_DB` is set. There is one DB per research stage and one `RESEARCH_BUDGET_LANE_ID` per outer track. A ledger failure **fails open** and emits degraded telemetry.

**Constants (`:32-49`).**

| Constant | Value | Used by |
|---|---|---|
| `DEFAULT_ATTEMPTS_GLOBAL` | 1800 | `admit_attempt` `:271` |
| `DEFAULT_SEARCH_GLOBAL` / `DEFAULT_SEARCH_LANE` | 900 / 360 | `admit_network` `:300-301` |
| `DEFAULT_FETCH_GLOBAL` / `DEFAULT_FETCH_LANE` | 450 / 180 | `admit_network` `:303-304` |
| `DEFAULT_NEGATIVE_TTL_SECONDS` | 600 | `negative_suppressed` `:339-341` |
| `DEFAULT_NEGATIVE_RETRIES` | 1 | `:342` |
| `DEFAULT_MODEL_CONCURRENCY_GLOBAL` | 12 | `_model_capacity` `:870-875` |
| `DEFAULT_MODEL_LEASE_WAIT_SECONDS` / `_TTL_SECONDS` | 10800 / 120 | `model_call_lease` `:926-935` |
| `DEFAULT_SUBAGENT_CONCURRENCY_GLOBAL` | 9 | `_subagent_capacity` `:1067-1072` |
| `DEFAULT_SUBAGENT_LEASE_WAIT_SECONDS` / `_TTL_SECONDS` | 10800 / 120 | `subagent_call_lease` `:1109-1118` |
| `DEFAULT_INFLIGHT_TTL_SECONDS` | 120 | `claim_request` `:790-794` |
| `DEFAULT_PROVIDER_FAILURE_THRESHOLD` | 5 | `:676-680` |
| `DEFAULT_PROVIDER_COOLDOWN_SECONDS` | 120 | `:681-685` |
| `DEFAULT_PROVIDER_PROBE_LEASE_SECONDS` | 30 | `:648-652` |
| `TELEMETRY_MIN_INTERVAL_SECONDS` | 1.0 | `export_telemetry` `:1479` |

**Process-global state (`:51-54`).**
- `_TELEMETRY_LOCK` and `_LAST_TELEMETRY_EXPORT`: per-telemetry-path throttle timestamps.
- `_SCHEMA_INIT_LOCK` and `_SCHEMA_INITIALIZED_PATHS`: realpaths whose DDL already ran in this process.

**`Admission` (`:57-63`).** A frozen dataclass `(allowed: bool, reason: str = "", degraded: bool = False)`. It is the return type of the admission APIs and is also yielded by the lease context managers.

**`_env_int(name, default, *, minimum=0)` (`:66-71`).** Parses an env int. An empty or invalid value falls back to the default. The result is clamped to `>= minimum`. Note that **0 is a legal cap** for the budget caps, and a cap of 0 means "deny everything" (see Surprises).

**Path and lane helpers.**
- `_db_path()` (`:74-75`) returns `expanduser(RESEARCH_BUDGET_DB.strip())`.
- `_model_db_path()` (`:78-80`) returns `RESEARCH_MODEL_LEASE_DB`, or falls back to `_db_path()`.
- `_telemetry_path()` (`:83-85`) returns `RESEARCH_BUDGET_TELEMETRY_PATH`, or `""`.
- `_lane_id()` (`:88-90`) returns `RESEARCH_BUDGET_LANE_ID`, default `"track-1"`. The orchestrator's default is `"outer-track-1"` (`backend/app/services/pipeline_orchestrator.py:2010`).

**Feature gates.**
- `enabled()` (`:93-96`) is true when `RESEARCH_BUDGET_DB` is non-empty. It controls the tool budget, negative/positive ledgers, claims, provenance and the provider circuit.
- `model_leases_enabled()` (`:99-101`) and `subagent_leases_enabled()` (`:104-106`) are true when `_model_db_path()` is non-empty. Leases therefore still work when the tool budget is disabled, provided the lease DB env is set.

**`_initialize_schema(conn)` (`:109-208`).** DDL that runs once per path per process.
- Sets `PRAGMA journal_mode=WAL` and tolerates only "locked"/"busy" errors (`:111-115`).
- Creates the tables:
  - `counters(scope, lane, name, value)`, PK (scope, lane, name) (`:116-121`).
  - `negative_results(kind, key_hash, key_preview, failures, retry_admissions, last_failure)`, PK (kind, key_hash) (`:122-129`).
  - `positive_results(kind, key_hash, lane, artifact_id, first_seen, last_seen, repeat_hits)`, PK (kind, key_hash, lane) (`:130-136`).
  - `global_request_claims(kind, key_hash, owner_lane, token PK, acquired_at, expires_at, UNIQUE(kind, key_hash))` (`:137-143`).
  - `fetched_sources(url_hash, lane, url, content_sha256, content_chars, title, excerpt, provider, receipt_id, cache_hits, first_seen, last_seen, observations)`, PK (url_hash, lane) (`:144-154`).
  - `provider_health(provider PK, consecutive_transport_failures, total_transport_failures, opened_at, open_until, probe_until, last_error, updated_at)` (`:155-165`).
  - `metadata(key PK, value)` (`:189-192`).
  - `model_leases(token PK, lane, pid, thread_id, weight, acquired_at, expires_at)` (`:193-198`).
  - `subagent_leases(token PK, lane, pid, thread_id, acquired_at, expires_at)` (`:199-204`).
- Additive migrations: `negative_results.retry_admissions` (`:166-173`); `fetched_sources.provider`, `receipt_id`, `cache_hits` (`:174-183`); `provider_health.probe_until` (`:184-188`).
- Seeds `metadata.created_at` with `INSERT OR IGNORE` (`:205-208`).

**`_connect(path=None)` (`:211-231`).**
- Raises `RuntimeError` if no path is configured (`:213-214`). It `makedirs` the parent directory.
- Opens `sqlite3.connect(path, timeout=10.0, isolation_level=None)` (autocommit; explicit `BEGIN IMMEDIATE` is used by callers) (`:218`).
- Sets `PRAGMA busy_timeout=10000` and `synchronous=NORMAL` (`:220-221`).
- Runs schema init behind double-checked locking keyed on `realpath` (`:222-227`). The connection is closed on any setup error.

**Counter helpers.**
- `_counter` (`:234-239`) reads a counter, returning 0 if the row is absent.
- `_increment` (`:242-250`) does an UPSERT `value = value + amount`.
- `_deny(conn, lane, reason)` (`:253-257`) increments `denied_<reason>` in both the global and the lane scope, then returns `Admission(False, reason)`.

**`admit_attempt(tool_kind)` (`:260-288`).** Counts **every** tool invocation, including cache hits and negative suppressions, against one **global** cap.
- If the budget is disabled it returns `Admission(True)` (`:268-269`).
- Inside `BEGIN IMMEDIATE`: if global `attempts >= RESEARCH_BUDGET_ATTEMPTS_GLOBAL` it denies with reason `attempts_global` (`:275-276`). Otherwise it increments global `attempts`, global `<kind>_attempts`, lane `attempts` and lane `<kind>_attempts` (`:278-282`).
- It then calls `export_telemetry(force=not allowed)` (`:284`).
- Any exception triggers `_emit_degraded` and returns `Admission(True, "ledger_unavailable", True)` (`:286-288`).
- There is **no lane cap on attempts**.

**`admit_network(kind)` (`:291-322`).** Reserves one **real network call**.
- `kind` must be `"search"` or `"fetch"`; anything else raises `ValueError` **outside** the fail-open try (`:296-297`).
- Caps come from `RESEARCH_BUDGET_{SEARCH|FETCH}_{GLOBAL|LANE}` (`:299-304`). The counter name is `<kind>_network` (`:305`).
- The global cap is checked first and denies with `<kind>_global`; the lane cap second and denies with `<kind>_lane` (`:309-312`). Otherwise it increments both scopes (`:314-316`).
- Telemetry and fail-open behaviour are the same as `admit_attempt` (`:318-322`).

**`_negative_hash(kind, exact_key)` (`:325-326`).** Returns `sha256(f"{kind}\n{exact_key}")`. It is reused as the key hash for the negative, positive and claim tables.

**`negative_suppressed(kind, exact_key)` (`:329-384`).** The bounded retry gate for exact keys that came back empty or dead.
- Returns False when the budget is disabled, the key is empty, or TTL ≤ 0 (`:337-344`).
- Inside `BEGIN IMMEDIATE`:
  - If the row is older than TTL (measured from `last_failure`) it is deleted, so a fresh cycle starts (`:359-363`).
  - Otherwise `suppressed = failures > retries or retry_admissions >= retries` (`:365`). When suppressed it increments `<kind>_negative_suppressed` in both scopes (`:366-370`).
  - When not suppressed it **claims the retry** with `retry_admissions += 1` inside the same lock (`:371-378`).
- With the default retries=1: the first empty result is recorded, the next identical call is allowed (as the claimed retry), and later calls are suppressed until TTL expires.
- Fails open by returning False (`:382-384`).

**`record_negative(kind, exact_key)` (`:387-413`).**
- UPSERTs `failures += 1` and `last_failure = now`. Each failure therefore refreshes the TTL window.
- `retry_admissions` is not reset (`:399-409`).
- Stores only `key_preview = "sha256:<hash>"`, never the raw query or URL (`:393-395`).
- Forces a telemetry export (`:411`).

**`clear_negative(kind, exact_key)` (`:416-429`).** Deletes the negative row after a successful non-empty result. It **always forces a telemetry export** (`:427`).

**`positive_repeat(kind, exact_key)` (`:432-461`).** Opt-in compaction.
- Returns None unless `RESEARCH_COMPACT_REPEAT_RESULTS` is set to a value outside `{0,false,no,off}`. The default `"false"` keeps it **off** (`:434-437`).
- When on and the current lane already has a `positive_results` row, it bumps `repeat_hits`, increments `<kind>_positive_compacted`, and returns the stored `artifact_id` (`:443-458`).

**`record_positive(kind, exact_key)` (`:464-484`).**
- Computes `artifact_id = f"{kind}:{key_hash[:16]}"` (`:466-467`).
- `INSERT OR IGNORE` into `positive_results` for the current lane (`:474-480`).
- Returns the artifact_id even when the budget is disabled (`:468-469`).

**`_source_title(content, url)` (`:487-498`).** Takes the first of the first 12 lines whose `#`-stripped length is 3–240 characters. Otherwise it falls back to the URL hostname, truncated to 240.

**`record_fetched_source(url, content, *, provider="", cache_hit=False)` (`:501-573`).** Cross-process fetch provenance; URLs are intentionally stored here.
- Skips the write unless the budget is enabled, the URL starts with `http(s)://`, the stripped body is at least 200 characters, and the body does not start with `Error:` (`:516-519`).
- Computes `url_hash = sha256(url)`, `content_sha256 = sha256(body)`, and `receipt_id = sha256(url\ncontent_sha\nprovider)` (`:520-525`).
- Builds an excerpt: whitespace collapsed, first 1200 characters (`:526`, `:563`).
- UPSERT on (url_hash, lane) (`:531-555`):
  - URL, hash, length, title and excerpt are overwritten.
  - `provider` and `receipt_id` are kept when the new provider is `''` or `'cache'`.
  - `cache_hits += cache_hit`, `observations += 1`.
- Fails open (`:572-573`).

**`list_fetched_sources(lane=None)` (`:576-617`).** Returns dicts with url, content_sha256, content_chars, title, excerpt, lane, observations, last_seen, provider, receipt_id and cache_hits.
- `lane=None` selects the current lane; `"*"` selects all lanes.
- Rows are ordered by `first_seen, url`.
- Returns `[]` on error.

**`provider_circuit_open(provider)` (`:620-668`).** A cross-process circuit breaker with a half-open probe lease. Inside `BEGIN IMMEDIATE`:
- `is_open = open_until > now` (`:643`).
- If the circuit is not open and `consecutive_transport_failures > 0`:
  - If another worker holds `probe_until > now`, report open (`:644-646`).
  - Otherwise take the probe lease, `probe_until = now + RESEARCH_PROVIDER_PROBE_LEASE_SECONDS` (min 1, default 30), and report closed to this caller (`:647-657`).
- An open result increments `provider_<name>_circuit_skips` in both scopes (`:658-662`).
- Fails open by returning False (`:666-668`).

**`record_provider_transport_failure(provider, error)` (`:671-737`).**
- Computes `consecutive = old + 1`; `opened = consecutive >= RESEARCH_PROVIDER_FAILURE_THRESHOLD` (min 1, default 5) (`:676-696`).
- UPSERT:
  - sets `consecutive`;
  - `total += 1`;
  - `opened_at = now` and `open_until = now + RESEARCH_PROVIDER_COOLDOWN_SECONDS` (min 1, default 120) **only if opened**, otherwise NULL;
  - `probe_until = NULL`;
  - `last_error` truncated to 500 characters (`:697-719`).
- Increments `provider_<name>_transport_failures`, plus `_circuit_opens` when opened (`:720-731`).
- Forces telemetry and returns `opened` (`:733-734`).

**`record_provider_success(provider)` (`:740-763`).** UPSERT that resets `consecutive=0` and `opened_at/open_until/probe_until=NULL`, and clears `last_error`.

**`compact_positive_result(tool, artifact_id)` (`:766-782`).** Returns the JSON `{"status":"already_available","tool","artifact_id","message"}`. The message tells the agent to reuse the earlier result or pass `revisit_reason`.

**`claim_request(kind, exact_key)` (`:785-824`).** A global single-flight claim.
- Returns `"uncontrolled:<uuid>"` when the budget is disabled, the key is empty (`:788-789`), or on error (`:822-824`).
- Inside `BEGIN IMMEDIATE`:
  - Purges expired claims (`:801-802`).
  - If a claim already exists for (kind, key_hash), increments `<kind>_singleflight_waits` and returns `""`, meaning the caller should wait (`:803-813`).
  - Otherwise inserts a claim with TTL `RESEARCH_INFLIGHT_TTL_SECONDS` (min 15, default 120) (`:790-794`, `:814-819`).
- Claims have **no heartbeat**.

**`release_request(token)` (`:827-836`).** Deletes by token. It does nothing for empty or `uncontrolled:` tokens, or when the budget is disabled.

**`denial_result(tool, reason, request)` (`:839-852`).** Returns the JSON `{"error":"research_budget_exhausted","tool","budget":reason,"request","results":[]}`. This is the stable shape that downstream code pattern-matches (see Cross-module edges).

**`negative_result(tool, request)` (`:855-867`).** Returns the JSON `{"error":"research_negative_cache_suppressed","tool","request","results":[]}`.

**Model leases.**
- `_model_capacity()` (`:870-875`) reads `RESEARCH_MODEL_CONCURRENCY_GLOBAL` (min 1, default 12).
- `_cleanup_expired_model_leases` (`:878-885`) deletes rows with `expires_at <= now`.
- `_release_model_lease(token)` (`:888-898`) deletes the token's row.

**`model_call_lease(weight=1)` (`:901-1047`).** A `@contextmanager` that holds a weighted, cross-process model-call permit.
- If leases are disabled it yields `Admission(True)` (`:916-918`).
- `weight > capacity` raises `ValueError` and does **not** fail open (`:919-925`).
- Wait budget is `RESEARCH_MODEL_LEASE_WAIT_SECONDS` (min 1, default 10800). TTL is `RESEARCH_MODEL_LEASE_TTL_SECONDS` (min 15, default 120) (`:926-935`).
- Poll loop (`:943-1017`):
  - Opens `BEGIN IMMEDIATE` and cleans expired leases.
  - Computes `SUM(weight)`. If `active + requested <= capacity`, it inserts the lease and increments `model_lease_acquisitions`. If the caller waited, it also increments `model_lease_waits` and adds the wait to `model_lease_wait_ms`.
  - Updates `metadata.model_peak_weight` (`:953-994`).
  - A busy/locked `OperationalError` counts as contention and the loop keeps waiting (`:996-1005`).
  - Any other error fails open by yielding `Admission(True,"ledger_unavailable",True)` (`:1001-1009`).
  - Past the deadline it raises `TimeoutError` (`:1010-1014`).
  - Sleep is `poll_delay × jitter`. `poll_delay` starts at 0.1 s and grows ×1.7 up to 1.0 s. Jitter is 0.85–1.15, derived from the token (`:940-941`, `:1016-1017`).
- After acquisition a daemon heartbeat thread refreshes `expires_at` every `max(5, ttl/3)` seconds (`:1019-1040`).
- `finally`: stop the heartbeat, join with a 1 s timeout, release the lease (`:1042-1047`).

**`async_model_call_lease(weight=1)` (`:1050-1064`).** An async adapter that runs `__enter__` and `__exit__` through `asyncio.to_thread`, so the event loop never blocks.

**Subagent leases.**
- `_subagent_capacity()` (`:1067-1072`) reads `RESEARCH_GLOBAL_SUBAGENT_CAP` (min 1, default 9).
- `_cleanup_expired_subagent_leases` (`:1075-1077`) and `_release_subagent_lease` (`:1080-1090`) mirror the model-lease helpers.

**`subagent_call_lease()` (`:1093-1234`).** The same algorithm as `model_call_lease`, but it counts rows (`COUNT(*)`) instead of summing weights. Its counters are `subagent_lease_*` and its peak key is `metadata.subagent_peak_count`. Wait and TTL come from `RESEARCH_SUBAGENT_LEASE_WAIT_SECONDS` / `_TTL_SECONDS`.

**`async_subagent_call_lease()` (`:1237-1251`).** The async adapter for `subagent_call_lease`.

**`_snapshot()` (`:1254-1439`).** Builds the telemetry payload.
- Merges the tool DB and the lease DB when their paths differ (`:1257-1268`). Each DB is read inside `BEGIN IMMEDIATE`. On the lease DB it first purges expired model and subagent leases (`:1280-1286`).
- Counters whose names start with `model_lease_` or `subagent_lease_` go into `lease_application_lifetime`; all others go into `global` / `lanes` (`:1332-1347`).
- Payload keys (`:1348-1439`):
  - `schema_version` (1);
  - `run_id` (from `RESEARCH_BUDGET_RUN_ID`);
  - `epoch` (from `RESEARCH_BUDGET_EPOCH`);
  - `created_at`, `updated_at`, `degraded:false`;
  - the `*_enabled` flags;
  - `limits` (all caps re-read from env);
  - `global`, `lanes`, `lease_application_lifetime`;
  - `negative_cache{kind:{keys,failures}}`;
  - `fetched_source_provenance{distinct_urls,lane_rows}`;
  - `provider_health{…circuit_open = open_until > now}`;
  - `model_concurrency{active_leases,active_weight,peak_weight}`;
  - `subagent_concurrency{active_leases,peak_count}`.

**`_write_json_atomic(path, payload)` (`:1442-1460`).** Writes via `mkstemp(prefix=".research-budget-", suffix=".tmp")` in the target directory, then fsync and `os.replace`. Any leftover tmp file is removed.

**`export_telemetry(*, force=False)` (`:1463-1488`).**
- Does nothing when no budget or lease feature is enabled, or when no telemetry path is set (`:1471-1475`).
- Throttles exports to one per second per path, unless `force` is set (`:1476-1480`).
- On success it writes the snapshot. On exception it calls `_emit_degraded` (`:1481-1488`).

**`_emit_degraded(message)` (`:1491-1508`).** Overwrites the telemetry file with a minimal payload: `{"schema_version":1,"run_id","updated_at","degraded":true,"degradation":[msg[:500]],"writer":{pid,thread}}`. It swallows its own failures.

### B. `deerflow_bridge/cached_fetch.py`

**Module docstring (`:1-29`).** Written in Chinese. It describes the design as a "transparent Jina web_fetch wrapper" with these settings:
- cache dir `RESEARCH_SOURCE_CACHE_DIR`;
- key `sha256(url)`;
- value `{url, content, fetched_at, content_len}`;
- TTL 72 h; size cap 500 MB with LRU eviction;
- dead fetches (`Error:` prefix or fewer than 200 characters) are never cached;
- the LOOP-007 budget, which is fail-open.

The docstring predates the Firecrawl/Exa/direct chain (see Surprises).

**Optional budget import (`:48-51`).** `import research_budget as _research_budget`. On `ImportError` the module sets it to None and all budget calls are skipped.

**Constants (`:53-92`).**
- `DEAD_FETCH_MIN_CHARS=200` (`:54`).
- `DEFAULT_TTL_HOURS=72.0` and `DEFAULT_MAX_MB=500.0` (`:56-57`).
- `DEFAULT_FIRECRAWL_MAX_AGE_SECONDS=172_800.0` (2 days) and `DEFAULT_FIRECRAWL_FETCH_CALL_CEILING=400` (`:62-63`).
- Process globals `_firecrawl_fetch_calls` and `_firecrawl_ceiling_warned` (`:64-65`).
- `DEFAULT_LOW_QUALITY_DOMAINS = ("economicsummarizer.com","insights.triplegains.com")` (`:66-69`).
- `_TRANSPORT_FAILURE_MARKERS`: connecttimeout, readtimeout, pooltimeout, connecterror, connection refused/reset, network is unreachable, timed out, timeout (`:70-80`).
- `_CONTENT_FAILURE_MARKERS`: access denied, 403 forbidden, 404 not found, page not found, verify you are human, enable javascript and cookies, captcha (`:81-89`).
- The contextvar `_FETCH_PROVIDER` records which provider succeeded (`:90-92`).

**Small helpers.**
- `_env_flag` (`:95-99`) is truthy for `{1,true,yes,on}`.
- `_env_float(name, default, minimum=0.1)` (`:102-107`).
- `_is_transport_failure(value)` (`:110-112`) does a case-insensitive substring match on the transport markers.

**`_TextExtractor(HTMLParser)` (`:115-133`).** A dependency-free text extractor. It suppresses text inside script, style, noscript and svg, and keeps non-blank text nodes.

**`_host_is_public(host)` (`:136-153`).** Rejects `""` and `localhost`. It resolves the host via `getaddrinfo` in a thread, and every resolved IP must be `is_global`. Any error returns False.

**`_direct_http_fetch(url)` (`:156-234`).** The opt-in raw HTTP fallback.
- Timeout is `RESEARCH_DIRECT_FETCH_TIMEOUT_SECONDS` (default 12). The byte cap is `RESEARCH_DIRECT_FETCH_MAX_MB` (default 8, floor 200 000 bytes) (`:161-163`, `:196`).
- Sends a fixed User-Agent that mentions `DeepAgentForecast` (`:165-170`). Uses httpx with `follow_redirects=False` and `trust_env=True` (`:171-176`).
- Redirects are followed manually for up to 6 hops. Every hop's host must pass `_host_is_public` (an SSRF guard) (`:178-191`).
- HTTP status ≥ 400 returns `Error: direct fallback HTTP <code>` (`:194-195`).
- PDF responses go through `pypdf`, first 80 pages, truncated to 12 000 characters if the text is at least 200 characters (`:199-212`).
- Non-HTML responses return `raw[:12000]` (`:214-215`).
- HTML responses go through DeerFlow `ReadabilityExtractor` → markdown if at least 200 characters (`:216-226`), else `_TextExtractor` (`:227-232`).
- Every failure returns an `Error: …` string; the function never raises (`:233-234`).

**`_exa_fetch(url)` (`:237-272`).** Requires `EXA_API_KEY` (`:239-241`).
- Calls `exa_py.Exa(api_key).get_contents([url], text={"max_characters": max_chars})` in a thread. `max_chars` is `RESEARCH_EXA_FETCH_MAX_CHARS` (default 12 000, floor 4096). The call is wrapped in `asyncio.wait_for(timeout=RESEARCH_EXA_FETCH_TIMEOUT_SECONDS`, default 15) (`:245-259`).
- Returns `# <title>\n\n<body[:max_chars]>`.
- Errors return `Error: Exa fallback failed: <ExcType>`. The exception text is deliberately omitted (`:269-272`).

**Firecrawl knobs.**
- `_firecrawl_max_age_ms()` (`:275-286`) converts seconds to ms (default 2 days; 0 omits the `maxAge` field).
- `_firecrawl_fetch_call_ceiling()` (`:289-298`) reads `RESEARCH_FIRECRAWL_MAX_FETCH_CALLS_PER_PROCESS` (default 400; ≤ 0 means unlimited).
- `_firecrawl_over_ceiling()` (`:301-313`) returns the sentinel `Error: Firecrawl per-run call ceiling reached (N)` and warns once.
- `get_firecrawl_call_counts()` (`:316-318`) returns `{"fetch": n}`. Only tests call it.

**`_firecrawl_fetch(url)` (`:321-386`).**
- Requires `FIRECRAWL_API_KEY` (`:330-332`) and checks the ceiling (`:333-335`).
- POSTs to `FIRECRAWL_API_URL` (default `https://api.firecrawl.dev/v2/scrape`) with a Bearer token. Body: `{url, formats:["markdown"], onlyMainContent:true, maxAge?}` (`:345-365`).
- The call counter is incremented **before** the request (`:354`).
- Timeout is `RESEARCH_FIRECRAWL_FETCH_TIMEOUT_SECONDS` (default 25) (`:344`).
- Error mapping:
  - 402 → `"payment required / quota exhausted"`;
  - 429 → `"rate limited (429 timeout)"`. The word "timeout" deliberately classifies it as a transport failure;
  - other ≥ 400 → `HTTP <code>` (`:366-371`).
- Parses `data.markdown`; adds `# title` when `metadata.title` is present; truncates to `RESEARCH_FIRECRAWL_FETCH_MAX_CHARS` (default 12 000, floor 4096) (`:372-383`).
- Exceptions return `Error: Firecrawl failed: <ExcType>` (`:384-386`).

**Circuit adapters (`:389-410`).**
- `_provider_circuit_open` calls `research_budget.provider_circuit_open` if available.
- `_record_provider_failure` records only results that `_is_transport_failure` matches.
- `_record_provider_success` calls `research_budget.record_provider_success`.

**`_reserve_additional_physical_fetch(url)` (`:413-422`).** Calls `admit_network("fetch")` for the second and later physical provider attempts. On denial it returns the `denial_result` JSON.

**`_resilient_fetch(url)` (`:425-502`).** The provider failover chain. The first physical attempt is already covered by `cached_fetch`'s reservation.
1. Resets `_FETCH_PROVIDER` (`:434`).
2. **Firecrawl**, if keyed and its circuit is closed (`:437-451`). A per-process ceiling hit becomes a sentinel with no request, no physical attempt counted and no circuit feed (`:439-443`). Otherwise it is the first physical attempt; a cacheable result sets the provider to `firecrawl`, records success and returns.
3. **Jina**, if its circuit is closed (`:453-471`). If an earlier attempt happened, it reserves one more network unit, and a denial returns the denial JSON immediately (`:455-458`). It wraps `_jina_delegate_fetch` in `asyncio.wait_for(timeout=RESEARCH_JINA_PRIMARY_TIMEOUT_SECONDS`, default 10.0) (`:461-466`).
4. **Exa**, if keyed and its circuit is closed (`:473-485`). Same extra-reservation logic as Jina.
5. **Direct HTTP**, only if `RESEARCH_DIRECT_FETCH_FALLBACK` is truthy (`:489-498`). It does not increment `physical_attempts` and does not touch the circuit.
6. Returns the most recent non-empty error: `direct or exa or jina or firecrawl`, else `"Error: no web-fetch provider was available"` (`:500-502`).

**Source policy.**
- `_source_policy_rejection(url)` (`:505-528`):
  - returns None if `RESEARCH_ALLOW_LOW_QUALITY_SOURCES` is truthy;
  - otherwise reads the denied set from `RESEARCH_SOURCE_DENY_DOMAINS`, defaulting to the 2 domains above;
  - matches the hostname exactly or as a subdomain, and returns a reason string.
- `_source_policy_result(url, reason)` (`:531-544`) returns `{"error":"source_quality_rejected","url","reason","message"}`.

**Cache config helpers.**
- `_cache_root()` (`:547-557`) returns `RESEARCH_SOURCE_CACHE_DIR`, or `<module dir>/.cache/source_cache`, which is `deer-flow/.cache/source_cache` when deployed.
- `_ttl_seconds()` (`:560-567`): hours → seconds, default 72; ≤ 0 disables.
- `_max_bytes()` (`:570-577`): default 500 MB; ≤ 0 means unlimited.
- `_cache_key(url)` (`:580-582`) is `sha256(url)`.
- `_cache_path(root, url)` (`:585-586`) is `<root>/<hash>.json`.

**`_is_cacheable(content)` (`:589-608`).** True only when all of these hold:
- the value is a str and is non-empty after stripping;
- it does not start with `Error:`;
- the first 1200 lowercased characters contain no content-failure marker;
- if it parses as a JSON object, it has no `error` and no `status ∈ {error, failed}`;
- the unstripped `len(content) >= 200`.

**`_read_cache(path, ttl)` (`:611-634`).** Loads the JSON. Expiry is judged from the stored `fetched_at`, **not** the file mtime. On a hit it touches the mtime (LRU recency) and returns `content`. Any exception returns None.

**`_write_cache(path, url, content)` (`:637-654`).** Atomic write through `<path>.<pid>.tmp` with fsync and `os.replace`. A failure logs a warning only.

**`_enforce_size_cap(root, max_bytes)` (`:657-689`).** Scans `*.json`. If the total size exceeds the cap, it deletes files in oldest-mtime-first order until the total fits. Best-effort.

**`cached_fetch(url, fetch_fn, revisit_reason="")` (`:692-817`).** The core flow.
1. `exact_key = url.strip()`. A source-policy rejection returns the rejection JSON before anything else, with no attempt counted (`:702-705`).
2. `admit_attempt("fetch")`. On denial it returns `denial_result` (`:706-709`).
3. If TTL > 0, try the disk cache (`:711-732`). On a hit:
   - `record_fetched_source(provider="cache", cache_hit=True)`;
   - if `revisit_reason` is empty, `positive_repeat` (off by default) may return the compact envelope;
   - `record_positive`;
   - return the cached body. **No network unit is used and the negative cache is not consulted.**
4. `negative_suppressed("fetch", exact_key)` returns `negative_result` (`:734-736`).
5. Single-flight, only if the budget module is present **and** TTL > 0 (`:738-774`). `claim_request`; on `""` the caller polls the disk cache for up to `RESEARCH_INFLIGHT_WAIT_SECONDS` (default 45). Delay starts at 0.1 s and grows ×1.7 up to 1 s.
   - A cache hit means `record_positive` + `record_fetched_source(cache)` and returns the full body.
   - Otherwise it retries the claim.
   - On timeout it returns `{"error":"research_inflight_timeout","tool":"web_fetch",…}`.
6. A follower that waited re-checks `negative_suppressed`, because the owner may have recorded a negative (`:775-778`).
7. `admit_network("fetch")`. On denial it releases the claim and returns `denial_result` (`:782-786`).
8. `content = await fetch_fn(url)`. On exception it forces telemetry, releases the claim and **re-raises** (`:788-796`).
9. Bookkeeping (`:797-810`):
   - cacheable → `clear_negative`, `record_positive`, `record_fetched_source(provider=_FETCH_PROVIDER.get())`;
   - otherwise → `record_negative`.
10. If TTL > 0 and the result is cacheable: `_write_cache` and `_enforce_size_cap` (`:811-813`). Returns the content. `finally` releases the claim (`:815-817`).

**`_jina_delegate_fetch(url)` (`:820-829`).** Imports `deerflow.community.jina_ai.tools.web_fetch_tool` and awaits its `.coroutine(url)`, or falls back to `ainvoke({"url": url})`. The Jina tool reads `timeout` from the `web_fetch` config stanza (30), per `deer-flow/backend/packages/harness/deerflow/community/jina_ai/tools.py:56-61`.

**`web_fetch_tool` (`:836-854`).** `@langchain_core.tools.tool("web_fetch", parse_docstring=True)`, async.
- Arguments: `url: str` and `revisit_reason: str = ""`.
- The docstring shown to the model says to fetch only exact URLs from the user or from earlier tool results, that auth-walled content cannot be fetched, not to add `www.`, and that the URL scheme is required.
- Body: `await cached_fetch(url, _resilient_fetch, revisit_reason)`.
- Without langchain the variable is set to `None` (`:853-854`).

### C. `deerflow_bridge/search_tools.py`

**Module docstring (`:1-37`).** Describes:
- the key-based dispatch serper > tavily > firecrawl > ddg (`:8-11`);
- bare-module registration;
- delegation to community tools, which read `max_results` from the `web_search` stanza;
- lazy deerflow imports and degrade-safe fallback to DDG;
- the WAVE9 disk cache (6 h / 200 MB);
- the LOOP-007 budget.

**Optional imports.**
- `research_budget` (`:52-55`).
- `cached_fetch._source_policy_rejection` (`:57-60`). This shares one domain denylist between search and fetch; on `ImportError` the value is None and search does no filtering.

**Constants.**
- `_PROVIDER_MODULES` = serper/tavily/ddg → `deerflow.community.<x>.tools` (`:63-67`). Firecrawl has no module.
- `DEFAULT_MAX_RESULTS=10` (`:70`).
- Firecrawl: `DEFAULT_FIRECRAWL_SEARCH_LIMIT=5` (results billed per row) and `DEFAULT_FIRECRAWL_SEARCH_CALL_CEILING=300` (`:75-76`).
- Process globals `_firecrawl_search_calls` and `_firecrawl_ceiling_warned` (`:77-78`).
- `DEFAULT_FIRECRAWL_CALLS_PER_MINUTE=8` and `DEFAULT_FIRECRAWL_SEARCH_MAX_RETRIES=4` (`:88-89`).
- `_FIRECRAWL_RETRY_AFTER_RE = r"retry after (\d+)\s*s"` (`:90`).
- `_firecrawl_window` holds monotonic timestamps (`:91`).
- Cache: `SEARCH_CACHE_DEFAULT_TTL_HOURS=6.0`, `SEARCH_CACHE_DEFAULT_MAX_MB=200.0`, `SEARCH_CACHE_MIN_CHARS=20` (`:105-108`).
- `_WS_RE` (`:110`).

**Cache config helpers.**
- `_search_cache_root()` (`:113-119`) returns `RESEARCH_SEARCH_CACHE_DIR`, or `<module dir>/.cache/search_cache`.
- `_search_ttl_seconds()` (`:122-137`): default 6 h. It returns **0 inside pytest** (`PYTEST_CURRENT_TEST` set) unless the TTL env is set explicitly.
- `_search_max_bytes()` (`:140-147`).
- `_normalize_query()` (`:150-152`): strip, collapse whitespace, lowercase.
- `_search_cache_key(provider, query, max_results)` (`:155-158`): `sha256(provider\nnormalized\nmax_results)`.
- `_search_cache_path` (`:161-162`).

**Result classifiers.**
- `_is_search_cacheable` (`:165-185`):
  - false for a str shorter than 20 characters after strip;
  - true for non-JSON text;
  - for a JSON dict: false if it has an `error` key or an empty `results` list, otherwise true;
  - for a JSON list: true if non-empty.
- `_is_search_no_result` (`:188-208`) identifies a genuinely empty result:
  - blank text;
  - non-JSON text under 200 characters matching `no/zero (search) results` or `nothing found`;
  - a dict without `error` whose `results` list is empty;
  - an empty list.
  - Error JSON is **not** treated as "no result", so transient errors are never negative-cached.

**`_filter_denied_search_results(result)` (`:211-247`).**
- If the result is JSON, it drops rows whose `url`/`link`/`href` fails `_source_policy_rejection`. This works for both `{"results":[…]}` and a top-level list.
- It re-serializes (sorted keys) **only when something was removed**. Non-JSON text passes through unchanged.

**`_budget_denial(tool, reason, request)` (`:250-256`).** Delegates to `research_budget.denial_result`, or builds the same JSON shape locally.

**Cache I/O.** `_read_search_cache` (`:259-282`), `_write_search_cache` (`:285-303`, value `{provider, query, result, fetched_at, result_len}`) and `_enforce_search_cache_cap` (`:306-335`) mirror the cached_fetch equivalents.

**`_select_search_provider()` (`:338-353`).** A pure env check, where a key counts only if it is non-empty after strip: `SERPER_API_KEY` → serper; else `TAVILY_API_KEY` → tavily; else `FIRECRAWL_API_KEY` → firecrawl; else ddg.

**Firecrawl knobs.**
- `_firecrawl_search_available()` (`:356-365`): key set and httpx importable.
- `_firecrawl_search_limit_cap()` (`:368-376`): default 5, min 1.
- `_firecrawl_search_call_ceiling()` (`:379-388`): default 300; ≤ 0 means unlimited.
- `get_firecrawl_call_counts()` (`:391-393`): only tests call it.
- `_firecrawl_calls_per_minute()` (`:396-402`): default 8; ≤ 0 disables throttling.
- `_firecrawl_search_max_retries()` (`:405-411`): default 4, min 0.

**`_firecrawl_throttle()` (`:414-432`).** A per-process rolling 60 s window. When the window is full it `time.sleep`s until the oldest entry ages out, capped at 65 s. It holds **no lock**.

**`_firecrawl_search(query, max_results)` (`:435-527`).** Synchronous Firecrawl v2 `/search`.
- Ceiling check: returns `{"error":"firecrawl search per-run call ceiling reached (N)","query"}` and warns once (`:447-457`).
- Endpoint is `FIRECRAWL_SEARCH_API_URL` (default `https://api.firecrawl.dev/v2/search`). Timeout is `RESEARCH_FIRECRAWL_SEARCH_TIMEOUT_SECONDS` (default 20) (`:461-465`).
- `limit = max(1, min(max_results, cap))` (`:466`). The counter is incremented **once per tool call, before the request**; retries are not counted (`:467`).
- Retry loop (`:470-497`): throttle, then POST `{query, limit, sources:["web"]}`. On a 429 with retries left it backs off for the server hint `retry after Ns` + 1 s, or `5×2^attempt`, plus up to 2 s jitter, capped at 70 s, then sleeps.
- HTTP ≥ 400 returns `{"error":"firecrawl search HTTP <code>","query"}` (`:498-502`).
- Parses `data.web` (v2) or a bare `data` list (v1). Rows map to `{title (or url), url, content: description|snippet}`, and rows without a URL are skipped (`:503-519`).
- Returns `{"query","total_results","results"}` (`:520-522`).
- Exceptions return `{"error":"firecrawl search failed: <ExcType>"}`; the exception text is not echoed (`:523-527`).

**`_load_search_module(provider)` (`:530-541`).** Lazy `importlib.import_module`; returns None on failure with a warning.

**`_call_delegate(tool_obj, query, max_results)` (`:544-561`).** Calls `tool_obj.func`, or the object itself. It passes `max_results` only when the function signature has that parameter: serper and ddg do, tavily does not. Note that the community tools then **override** `max_results` with the config stanza value (10): `deer-flow/backend/packages/harness/deerflow/community/serper/tools.py:42-44`, `ddg_search/tools.py:144-151`, `tavily/tools.py:24-27`.

**`web_search_impl(query, max_results=10, revisit_reason="")` (`:564-719`).** The core flow.
1. `provider = _select_search_provider()` (`:576`).
2. `admit_attempt("search")`. On denial it returns the budget denial (`:577-580`).
3. Firecrawl without httpx falls back to ddg (`:581-584`).
4. For non-Firecrawl providers it loads the module. If the module or `web_search_tool` is missing and the provider is not ddg, it falls back to ddg. If still unavailable it returns `{"error":"no web_search backend available","query"}` (`:585-596`).
5. `exact_key = f"{provider}\n{normalized}\n{max_results}"`, using the provider actually used (`:599`).
6. Cache read, only if TTL > 0 and the normalized query is non-empty (`:601-627`).
   - Filter denied rows from the hit. If the result is no longer cacheable, treat it as a miss.
   - On a hit: optional `positive_repeat` compaction, then `record_positive` and return.
   - A cache exception skips the cache, and `_cache_path_str = ""` also disables single-flight.
7. `negative_suppressed` returns `negative_result` (`:631-633`).
8. Single-flight, only if `_cache_path_str` is set (`:635-671`). Same algorithm as fetch but with synchronous `time.sleep`. A follower that gets a hit calls `record_positive` and returns the full body. On timeout it returns `research_inflight_timeout` with `tool:"web_search"`.
9. A follower re-checks `negative_suppressed` (`:672-675`).
10. `admit_network("search")`. On denial it releases the claim and returns the denial (`:679-683`).
11. Calls `_firecrawl_search` or `_call_delegate`, coerces the result to str and filters denied rows (`:685-690`). An exception returns `{"error": str(e), "query"}` after a forced telemetry export and claim release; the function never raises (`:691-696`).
12. Budget bookkeeping (`:698-705`):
    - no-result → `record_negative`;
    - cacheable → `clear_negative` + `record_positive`;
    - anything else (an error) → forced telemetry only.
13. If cacheable: write the cache and enforce the cap. Return the result. `finally` releases the claim (`:707-719`).

**`web_search_tool` (`:727-746`).** `@langchain_core.tools.tool("web_search", parse_docstring=True)`, **sync**. Arguments: `query`, `max_results=10`, `revisit_reason=""`. It returns `web_search_impl(...)`. Without langchain the variable is set to `None`.

---

## Control flow

### Registration and import

1. The orchestrator syncs bridge modules into the deployed directory: `_DEPLOYED_BRIDGE_MODULES` is used at `backend/app/services/pipeline_orchestrator.py:1530-1533`. `setup.sh:597` does the same at install time.
2. DeerFlow loads `config.yaml` tools by reflection: `search_tools:web_search_tool` (`deerflow_bridge/config.yaml:732`) and `cached_fetch:web_fetch_tool` (`:801`). Module import triggers `import research_budget` (`deerflow_bridge/search_tools.py:52-55`, `deerflow_bridge/cached_fetch.py:48-51`).
3. The v3 engine imports the same modules lazily by name: `importlib.import_module("search_tools")` and `("cached_fetch")` (`deerflow_bridge/research_gateway.py:3397`, `:3405`). It always passes a non-empty `revisit_reason` (`_ENGINE_REVISIT_REASON`, `deerflow_bridge/research_gateway.py:3354`), so lane compaction can never replace a payload.

### Env contract (orchestrator → research process)

- Orchestrator `_activate_research_budget_epoch` creates `<handoff>/research_budget_epochs/epoch-NNN-<task>/research_budget.sqlite3` and seeds `<handoff>/research_budget.json` (`backend/app/services/pipeline_orchestrator.py:1815-1903`).
- `_configure_research_budget_env` sets the following (`backend/app/services/pipeline_orchestrator.py:1986-2026`):
  - `RESEARCH_BUDGET_DB`, `_TELEMETRY_PATH`, `_LANE_ID` (`outer-track-<k>`, `global-synthesis`, `global-synthesis-recovery`; `:11179`, `:11502`, `:10948`);
  - `_RUN_ID`, `_EPOCH`;
  - the five caps and the two negative-cache knobs.
  - When `RESEARCH_BUDGET_ENABLED=false` it pops all of them instead (`:2002-2005`).
- `RESEARCH_MODEL_LEASE_DB` is **always** set to the application-wide `backend/uploads/research_model_leases.sqlite3`, unless overridden (`backend/app/services/pipeline_orchestrator.py:2404-2410`; `backend/app/config.py:1216-1219`). `RESEARCH_GLOBAL_SUBAGENT_CAP` and, optionally, `RESEARCH_MODEL_CONCURRENCY_GLOBAL` are also set (`backend/app/services/pipeline_orchestrator.py:2369-2373`).

### `web_fetch` call order (per call)

```
web_fetch_tool(url, revisit_reason)                    cached_fetch.py:840
 └ cached_fetch(url, _resilient_fetch, revisit_reason)  :692
    1 _source_policy_rejection → rejection JSON          :703-705
    2 research_budget.admit_attempt("fetch")             :707  (deny → denial_result)
    3 _read_cache (TTL>0) → hit: record_fetched_source(cache), positive_repeat?, record_positive, return  :714-732
    4 negative_suppressed("fetch")                       :734-736
    5 claim_request / follower poll loop (TTL>0)         :740-774
    6 [follower] negative_suppressed again               :775-778
    7 admit_network("fetch")                             :783-786
    8 _resilient_fetch(url)                              :789 → :425
        Firecrawl? → [admit_network] Jina → [admit_network] Exa? → [admit_network] direct?
        each: provider_circuit_open / record_provider_{success,transport_failure}
    9 cacheable? clear_negative+record_positive+record_fetched_source : record_negative   :798-810
   10 _write_cache + _enforce_size_cap                   :811-813
   11 release_request                                    :815-817
```

### `web_search` call order (per call)

```
web_search_tool → web_search_impl                        search_tools.py:743 → :564
  select provider → admit_attempt("search") → (fallback to ddg) → cache read+filter
  → negative_suppressed → claim/follow → admit_network("search")
  → _firecrawl_search | _call_delegate → filter → negative/positive bookkeeping
  → cache write → release_request
```

### Leases

- **Exact provider model calls.** `ModelConcurrencyMiddleware.wrap_model_call/awrap_model_call` → `provider_model_lease()` / `async_provider_model_lease()` → `research_budget.model_call_lease(1)` / `async_model_call_lease(1)` (`deerflow_bridge/patches/middlewares/model_concurrency_middleware.py:25-75`).
- **Bare model invocations in the legacy bridge.** `_invoke_model` → `_model_call_lease(1)` (`deerflow_bridge/deerflow_research.py:4549-4557`).
- **v3 engine.** `_bridge_lease` wraps `bridge._model_call_lease`. It caps `RESEARCH_MODEL_LEASE_WAIT_SECONDS` at 300 s for the process and stops leasing after the first capacity timeout (`deerflow_bridge/linear_research.py:6141-6215`).
- **Subagent lifecycle.** The patched `SubagentExecutor._aexecute` wraps `_aexecute_under_lease` in `async_subagent_lifecycle_lease()` → `research_budget.async_subagent_call_lease()` (`deerflow_bridge/patches/apply_subagent_overlays.py:143-153`; `deerflow_bridge/patches/middlewares/model_concurrency_middleware.py:46-53`).

### Telemetry

- Admission, negative and provider operations call `export_telemetry`. It is forced on denials, negative writes and clears, provider failures, delegate exceptions and search errors (e.g. `deerflow_bridge/research_budget.py:284`, `:411`, `:427`, `:733`; `deerflow_bridge/cached_fetch.py:792`; `deerflow_bridge/search_tools.py:694`, `:705`).
- The legacy bridge forces final exports at stream end (`deerflow_bridge/deerflow_research.py:17374-17376`, `:17531-17533`, `:17953-17966`).
- The orchestrator reads the JSON in two places:
  - **pre-launch guard** `_research_budget_exhaustion`, which compares `global.attempts / search_network / fetch_network` against `limits` for the expected epoch (`backend/app/services/pipeline_orchestrator.py:1764-1798`, used at `:11104-11110`);
  - **post-research summary**, which sums `denied_*` counters and degraded flags into `meta["research_budget"]` (`backend/app/services/pipeline_orchestrator.py:10583-10605`). That summary feeds a 0.05 confidence penalty (`:10676-10679`).

---

## Data & artifacts

| Artifact | Path pattern | Format / key fields | Writer / reader | Anchor |
|---|---|---|---|---|
| Tool-budget ledger | `<handoff>/research_budget_epochs/epoch-NNN-<task-slug>/research_budget.sqlite3`, plus `-wal`/`-shm` sidecars (WAL mode) | Tables `counters`, `negative_results`, `positive_results`, `global_request_claims`, `fetched_sources`, `provider_health`, `metadata`, plus lease tables (created but unused in this DB when a separate lease DB is configured) | All research processes of one pipeline task | `deerflow_bridge/research_budget.py:109-208`; path from `backend/app/services/pipeline_orchestrator.py:1859-1881` |
| Legacy root ledger | `<handoff>/research_budget.sqlite3` | same | Default if `budget_db_path` is not passed; recorded as `legacy_research_budget_db` | `backend/app/services/pipeline_orchestrator.py:1893-1895`, `:2006-2007` |
| Application lease DB | `backend/uploads/research_model_leases.sqlite3` (default) | `model_leases(token, lane, pid, thread_id, weight, acquired_at, expires_at)`, `subagent_leases(…)`, `metadata.model_peak_weight / subagent_peak_count`, `counters` `model_lease_*` / `subagent_lease_*` | All pipelines on the machine | `backend/app/config.py:1216-1219`; `deerflow_bridge/research_budget.py:193-204` |
| Budget telemetry | `<handoff>/research_budget.json` (shared by all lanes; last writer wins) | `_snapshot` payload (see walkthrough) or the degraded-only payload | `export_telemetry` / `_emit_degraded`; read by the orchestrator | `deerflow_bridge/research_budget.py:1348-1439`, `:1497-1504` |
| Telemetry temp files | `<telemetry dir>/.research-budget-*.tmp` | transient | `_write_json_atomic` | `deerflow_bridge/research_budget.py:1446-1448` |
| Fetch disk cache | `$RESEARCH_SOURCE_CACHE_DIR` or `deer-flow/.cache/source_cache/<sha256(url)>.json` (4 888 files present at study time) | `{url, content, fetched_at (epoch s), content_len}` | `cached_fetch` | `deerflow_bridge/cached_fetch.py:547-557`, `:641-646` |
| Fetch cache temp | `<entry>.json.<pid>.tmp` | transient | `_write_cache` | `deerflow_bridge/cached_fetch.py:647` |
| Search disk cache | `$RESEARCH_SEARCH_CACHE_DIR` or `deer-flow/.cache/search_cache/<sha256(provider\nnormq\nmax)>.json` (10 026 files present) | `{provider, query (raw), result, fetched_at, result_len}` | `web_search_impl` | `deerflow_bridge/search_tools.py:113-119`, `:289-295` |

**Important in-memory state.**
- `_SCHEMA_INITIALIZED_PATHS` (`deerflow_bridge/research_budget.py:54`).
- `_LAST_TELEMETRY_EXPORT` (`:52`).
- `_FETCH_PROVIDER` contextvar (`deerflow_bridge/cached_fetch.py:90-92`).
- `_firecrawl_fetch_calls` (`deerflow_bridge/cached_fetch.py:64`).
- `_firecrawl_search_calls` and `_firecrawl_window` (`deerflow_bridge/search_tools.py:77`, `:91`).

**Counter name catalogue.** All names exist in both global (`lane=""`) and lane scope.
- `attempts`, `{search,fetch}_attempts`, `{search,fetch}_network`.
- `denied_{attempts_global, search_global, search_lane, fetch_global, fetch_lane}`.
- `{kind}_negative_suppressed`, `{kind}_positive_compacted`, `{kind}_singleflight_waits`.
- `provider_<p>_{circuit_skips, transport_failures, circuit_opens}`.
- `model_lease_{acquisitions, waits, wait_ms}`, `subagent_lease_{acquisitions, waits, wait_ms}`.

Anchors: `deerflow_bridge/research_budget.py:255-256`, `:278-281`, `:314-315`, `:367-370`, `:454-455`, `:809-811`, `:659-662`, `:720-731`, `:969-980`, `:1150-1167`.

**Hash keys.**
- The negative, positive and claim tables use `sha256(kind\nexact_key)` (`deerflow_bridge/research_budget.py:325-326`).
- `fetched_sources.url_hash` and the fetch disk cache use `sha256(url)` (`:520`; `deerflow_bridge/cached_fetch.py:580-582`).
- The fetch `exact_key` is `url.strip()` (`deerflow_bridge/cached_fetch.py:702`).
- The search `exact_key` is `provider\nnormalized_query\nmax_results` (`deerflow_bridge/search_tools.py:599`).

---

## Config / env knobs

### research_budget.py

| Env | Default | Effect | Anchor |
|---|---|---|---|
| `RESEARCH_BUDGET_DB` | unset (disabled) | Enables the tool budget, ledgers, claims, provenance and provider circuit | `deerflow_bridge/research_budget.py:74-75`, `:93-96` |
| `RESEARCH_MODEL_LEASE_DB` | falls back to `RESEARCH_BUDGET_DB` (orchestrator: `uploads/research_model_leases.sqlite3`) | Lease DB; enables model and subagent leases | `:78-80`, `:99-106` |
| `RESEARCH_BUDGET_TELEMETRY_PATH` | unset (no export) | Telemetry JSON target | `:83-85` |
| `RESEARCH_BUDGET_LANE_ID` | `track-1` | Lane scope for caps, positive rows and provenance | `:88-90` |
| `RESEARCH_BUDGET_RUN_ID` / `RESEARCH_BUDGET_EPOCH` | `""` | Written into telemetry only | `:1350-1351` |
| `RESEARCH_BUDGET_ATTEMPTS_GLOBAL` | 1800 | Global attempt cap; 0 denies everything | `:271` |
| `RESEARCH_BUDGET_SEARCH_GLOBAL` / `_LANE` | 900 / 360 | Network search caps | `:300-301` |
| `RESEARCH_BUDGET_FETCH_GLOBAL` / `_LANE` | 450 / 180 | Network fetch caps | `:303-304` |
| `RESEARCH_NEGATIVE_CACHE_TTL_SECONDS` | 600 | Suppression window; ≤ 0 disables suppression | `:339-344` |
| `RESEARCH_NEGATIVE_CACHE_RETRIES` | 1 | Exact retries allowed after the first empty result | `:342`, `:365` |
| `RESEARCH_COMPACT_REPEAT_RESULTS` | `false` | Enables lane-scoped compaction of repeat cache hits | `:434-437` |
| `RESEARCH_INFLIGHT_TTL_SECONDS` | 120 (min 15) | Single-flight claim lifetime | `:790-794` |
| `RESEARCH_PROVIDER_FAILURE_THRESHOLD` | 5 (min 1) | Consecutive transport failures before the circuit opens | `:676-680` |
| `RESEARCH_PROVIDER_COOLDOWN_SECONDS` | 120 (min 1) | Open duration | `:681-685` |
| `RESEARCH_PROVIDER_PROBE_LEASE_SECONDS` | 30 (min 1) | Half-open probe lease | `:648-652` |
| `RESEARCH_MODEL_CONCURRENCY_GLOBAL` | 12 (min 1) | Model lease capacity (weight units) | `:870-875` |
| `RESEARCH_MODEL_LEASE_WAIT_SECONDS` | 10800 (min 1) | Max wait before `TimeoutError` | `:926-930` |
| `RESEARCH_MODEL_LEASE_TTL_SECONDS` | 120 (min 15) | Lease expiry without heartbeat | `:931-935` |
| `RESEARCH_GLOBAL_SUBAGENT_CAP` | 9 (min 1) | Subagent lease capacity | `:1067-1072` |
| `RESEARCH_SUBAGENT_LEASE_WAIT_SECONDS` / `_TTL_SECONDS` | 10800 / 120 | Subagent wait and TTL | `:1109-1118` |

### cached_fetch.py

| Env | Default | Effect | Anchor |
|---|---|---|---|
| `RESEARCH_SOURCE_CACHE_DIR` | `<module dir>/.cache/source_cache` | Cache root | `deerflow_bridge/cached_fetch.py:553-557` |
| `RESEARCH_SOURCE_CACHE_TTL_H` | 72 | Cache TTL; ≤ 0 disables the cache **and** fetch single-flight | `:560-567`, `:740` |
| `RESEARCH_SOURCE_CACHE_MAX_MB` | 500 | LRU size cap; ≤ 0 means unlimited | `:570-577` |
| `RESEARCH_INFLIGHT_WAIT_SECONDS` | 45 (min 1) | Follower wait | `:745-748` |
| `RESEARCH_ALLOW_LOW_QUALITY_SOURCES` | false | Bypasses the domain denylist | `:507-510` |
| `RESEARCH_SOURCE_DENY_DOMAINS` | `economicsummarizer.com,insights.triplegains.com` | Denylist (exact host or subdomain) | `:517-527` |
| `FIRECRAWL_API_KEY` | unset | Makes Firecrawl the first fetch provider | `:330`, `:437` |
| `FIRECRAWL_API_URL` | `https://api.firecrawl.dev/v2/scrape` | Endpoint | `:357-359` |
| `RESEARCH_FIRECRAWL_FETCH_TIMEOUT_SECONDS` | 25 | httpx timeout | `:344` |
| `RESEARCH_FIRECRAWL_FETCH_MAX_CHARS` | 12000 (floor 4096) | Truncation | `:339-343` |
| `RESEARCH_FIRECRAWL_MAX_AGE_SECONDS` | 172800 | Firecrawl-side cache `maxAge` (sent in ms); 0 omits it | `:275-286` |
| `RESEARCH_FIRECRAWL_MAX_FETCH_CALLS_PER_PROCESS` | 400 | Per-process ceiling; ≤ 0 means unlimited | `:289-298` |
| `RESEARCH_JINA_PRIMARY_TIMEOUT_SECONDS` | 10.0 | Outer `wait_for` around Jina | `:463` |
| `EXA_API_KEY` | unset | Enables Exa fallback | `:239`, `:474` |
| `RESEARCH_EXA_FETCH_MAX_CHARS` / `_TIMEOUT_SECONDS` | 12000 / 15 | Exa limits | `:245-258` |
| `RESEARCH_DIRECT_FETCH_FALLBACK` | false | Enables the raw-HTTP last resort | `:490` |
| `RESEARCH_DIRECT_FETCH_TIMEOUT_SECONDS` / `_MAX_MB` | 12 / 8 | Direct fetch limits | `:161-163` |

### search_tools.py

| Env | Default | Effect | Anchor |
|---|---|---|---|
| `SERPER_API_KEY` / `TAVILY_API_KEY` / `FIRECRAWL_API_KEY` | unset | Provider precedence serper > tavily > firecrawl > ddg | `deerflow_bridge/search_tools.py:347-353` |
| `RESEARCH_SEARCH_CACHE_DIR` | `<module dir>/.cache/search_cache` | Cache root | `:113-119` |
| `RESEARCH_SEARCH_CACHE_TTL_H` | 6 (0 under pytest unless set) | TTL; 0 disables the cache **and** search single-flight | `:122-137`, `:637` |
| `RESEARCH_SEARCH_CACHE_MAX_MB` | 200 | LRU cap | `:140-147` |
| `RESEARCH_INFLIGHT_WAIT_SECONDS` | 45 | Follower wait | `:642-645` |
| `FIRECRAWL_SEARCH_API_URL` | `https://api.firecrawl.dev/v2/search` | Endpoint | `:463-465` |
| `RESEARCH_FIRECRAWL_SEARCH_TIMEOUT_SECONDS` | 20 | httpx timeout | `:461-462` |
| `RESEARCH_FIRECRAWL_SEARCH_LIMIT` | 5 (min 1) | Billed result rows per search | `:368-376` |
| `RESEARCH_FIRECRAWL_MAX_SEARCH_CALLS_PER_PROCESS` | 300 | Per-process ceiling; ≤ 0 means unlimited | `:379-388` |
| `RESEARCH_FIRECRAWL_CALLS_PER_MINUTE` | 8 | Rolling-window throttle; ≤ 0 disables it | `:396-402` |
| `RESEARCH_FIRECRAWL_SEARCH_MAX_RETRIES` | 4 | 429 retries | `:405-411` |
| `PYTEST_CURRENT_TEST` | (set by pytest) | Forces the cache off unless the TTL is explicit | `:131-132` |

Orchestrator-side knobs that shape this slice:
- `RESEARCH_BUDGET_ENABLED` (default true; `backend/app/config.py:528-529`).
- `RESEARCH_BUDGET_MAX_EPOCHS` (default 3; `backend/app/config.py:543-544`, enforced at `backend/app/services/pipeline_orchestrator.py:1851-1856`).

---

## External calls

| Target | Where | Notes |
|---|---|---|
| SQLite (stdlib `sqlite3`), tool ledger and lease DB | `deerflow_bridge/research_budget.py:211-231`, and every API | WAL, busy_timeout 10 s, `BEGIN IMMEDIATE` per admission |
| Filesystem: telemetry JSON (atomic) | `deerflow_bridge/research_budget.py:1442-1460` | fsync and `os.replace` |
| Filesystem: fetch and search disk caches | `deerflow_bridge/cached_fetch.py:611-689`; `deerflow_bridge/search_tools.py:259-335` | fsync, `os.replace`, LRU delete |
| Firecrawl `POST /v2/scrape` (httpx async) | `deerflow_bridge/cached_fetch.py:355-365` | Bearer `FIRECRAWL_API_KEY`; billed per call |
| Firecrawl `POST /v2/search` (httpx sync) | `deerflow_bridge/search_tools.py:472-484` | Bearer key; billed per result row |
| Jina reader via DeerFlow `deerflow.community.jina_ai.tools.web_fetch_tool` | `deerflow_bridge/cached_fetch.py:820-829` | Lazy import; 10 s outer timeout |
| Exa `exa_py.Exa.get_contents` | `deerflow_bridge/cached_fetch.py:250-259` | Run in a thread with a 15 s timeout |
| Arbitrary public HTTP (httpx async, manual redirects) and DNS `getaddrinfo` | `deerflow_bridge/cached_fetch.py:136-153`, `:171-191` | Opt-in only |
| `pypdf.PdfReader` and DeerFlow `ReadabilityExtractor` | `deerflow_bridge/cached_fetch.py:200-224` | Direct fallback only |
| Serper / Tavily / DDG via DeerFlow community tools (`.func`) | `deerflow_bridge/search_tools.py:530-561` | The community tools make the actual HTTP calls |
| No LLM calls | — | The leases only gate LLM calls made elsewhere |
| No subprocesses | — | — |

---

## Cross-module edges

### Inbound (who calls this slice)

- **DeerFlow config reflection.**
  - `deerflow_bridge/config.yaml:730-735` → `search_tools:web_search_tool`.
  - `deerflow_bridge/config.yaml:799-802` → `cached_fetch:web_fetch_tool`.
- **v3 engine gateway.**
  - `deerflow_bridge/research_gateway.py:3390-3398` → `search_tools.web_search_impl(query, max_results, revisit_reason=_ENGINE_REVISIT_REASON)`.
  - `deerflow_bridge/research_gateway.py:3401-3407` → `cached_fetch.cached_fetch(url, cached_fetch._resilient_fetch, _ENGINE_REVISIT_REASON)` through `_run_coroutine_blocking`.
  - The gateway maps the result envelopes: `research_budget_exhausted` → `MSG_SEARCH_BUDGET` / `MSG_FETCH_BUDGET`; `research_negative_cache_suppressed` → `MSG_NO_RESULTS`; `status:"already_available"` → treated as unavailable (`deerflow_bridge/research_gateway.py:3600-3604`, `:3720-3724`).
  - The v3 production tool factory is at `deerflow_bridge/linear_research.py:6277-6279`.
- **Legacy bridge `deerflow_research.py`.**
  - Imports `research_budget` (`deerflow_bridge/deerflow_research.py:67-73`).
  - `_merge_shared_fetched_sources` → `list_fetched_sources()` (`:1931-1960`).
  - `_model_call_lease` / `_invoke_model` → `model_call_lease` (`:4549-4557`).
  - Final `export_telemetry(force=True)` (`:17374-17376`, `:17531-17533`, `:17953-17966`).
  - It pattern-matches `research_budget_exhausted` in tool results to break loops (`:10003-10011`, `:10278-10284`).
- **DeerFlow patches.**
  - `deerflow_bridge/patches/middlewares/model_concurrency_middleware.py:19-53` (model and subagent leases).
  - `deerflow_bridge/patches/apply_subagent_overlays.py:143-153` (subagent lifecycle wrapper).
  - `deerflow_bridge/patches/apply_subagent_overlays.py:220-240` (counts `web_search`/`web_fetch` denials versus successes from the `research_budget_exhausted` envelope).
  - Lease middleware is also used from summarization, title and tool-error middleware (`deerflow_bridge/patches/middlewares/summarization_middleware.py:215`, `:236`; `title_middleware.py:174`; `tool_error_handling_middleware.py:138`).
- **Orchestrator.** It does not import these modules. It configures env and reads telemetry and envelopes:
  - `backend/app/services/pipeline_orchestrator.py:1764-1798` (exhaustion guard);
  - `:1815-1903` (epochs);
  - `:1986-2026` (env);
  - `:2404-2410` (lease DB);
  - `:2762-2790` (`research_budget_exhausted` treated as a blocked subagent outcome);
  - `:10583-10605` (summary).
- **Tests exercising this slice.** `backend/tests/test_loop007_research_budget.py`, `test_bridge_search_and_cache.py`, `test_sessionb_firecrawl.py`, `test_sessionb_firecrawl_guardrails.py`, `test_wave9_research_speed.py`, `test_deerflow_bridge_sync_guard.py:157-181`.

### Outbound (what this slice calls)

- `search_tools` → `cached_fetch._source_policy_rejection` (`deerflow_bridge/search_tools.py:57-60`).
- `search_tools` → `research_budget` (`deerflow_bridge/search_tools.py:52-55`).
- `cached_fetch` → `research_budget` (`deerflow_bridge/cached_fetch.py:48-51`).
- `search_tools` → `deerflow.community.{serper,tavily,ddg_search}.tools` (`deerflow_bridge/search_tools.py:63-67`).
- `cached_fetch` → `deerflow.community.jina_ai.tools` (`deerflow_bridge/cached_fetch.py:824`).
- `cached_fetch` → `deerflow.utils.readability` (`deerflow_bridge/cached_fetch.py:217`).
- Both tool modules → `langchain_core.tools.tool` (`deerflow_bridge/cached_fetch.py:837`, `deerflow_bridge/search_tools.py:728`).
- `cached_fetch` → `httpx`, `exa_py`, `pypdf`.

---

## Invariants, gates, validation

1. **Every tool invocation counts one attempt** before any cache lookup. The only exception is a source-policy rejection in fetch, which returns before `admit_attempt` (`deerflow_bridge/cached_fetch.py:703-709`; `deerflow_bridge/search_tools.py:577-580`).
2. **Positive disk-cache hits and single-flight followers never use network allowance.** `admit_network` sits after both paths (`deerflow_bridge/cached_fetch.py:780-786`; `deerflow_bridge/search_tools.py:677-683`). [verifier: imprecise — only followers satisfied from the disk cache skip the reservation. A follower that wins the claim after the owner released it without writing the cache (failed or non-cacheable result) re-checks `negative_suppressed`, takes the single retry (`failures=1`, `retry_admissions=0` is not suppressed), then calls `admit_network` and fetches (`deerflow_bridge/cached_fetch.py:766-786`; `deerflow_bridge/search_tools.py:662-683`; `deerflow_bridge/research_budget.py:365-378`). The code comment at `search_tools.py:677-678` overstates this the same way.]
3. **Each additional physical fetch provider request reserves one more network unit.** Failover cannot silently multiply the fetch allowance (`deerflow_bridge/cached_fetch.py:413-422`, `:455-458`, `:475-478`, `:491-494`).
4. **Admission checks and increments happen in one `BEGIN IMMEDIATE` transaction**, which serializes across processes (`deerflow_bridge/research_budget.py:274-283`, `:308-317`).
5. **Global caps are checked before lane caps** for network admission (`deerflow_bridge/research_budget.py:309-312`).
6. **A negative retry claim is taken inside the same write lock**, so concurrent workers cannot all consume the single retry (`deerflow_bridge/research_budget.py:371-378`).
7. **Only cacheable content is written to disk.** Fetch content must be at least 200 characters, not `Error:`, free of content-failure markers in the first 1200 characters, and not an error JSON envelope. Search results must be at least 20 characters, not error JSON, and not an empty `results` list (`deerflow_bridge/cached_fetch.py:589-608`, `:811`; `deerflow_bridge/search_tools.py:165-185`, `:709-711`).
8. **Cache expiry uses the stored `fetched_at`; mtime is only the LRU marker**, so repeated hits cannot keep an entry alive forever (`deerflow_bridge/cached_fetch.py:611-634`; `deerflow_bridge/search_tools.py:259-282`).
9. **Search negative-caching is limited to true empties.** Error JSON does not count as "no result" (`deerflow_bridge/search_tools.py:188-208`, `:699-705`).
10. **Denied domains are filtered from both fresh and cached search rows.** A cache entry that becomes empty after filtering is treated as a miss (`deerflow_bridge/search_tools.py:609-614`, `:690`).
11. **The model lease weight must not exceed capacity**, otherwise `ValueError` (`deerflow_bridge/research_budget.py:921-925`). A saturated but healthy ledger **waits** instead of failing open (`:996-1005`).
12. **Provider secrets are never echoed.** Firecrawl, Exa and Firecrawl-search errors include only the exception type (`deerflow_bridge/cached_fetch.py:269-272`, `:384-386`; `deerflow_bridge/search_tools.py:523-527`). Negative rows store only a sha256 preview (`deerflow_bridge/research_budget.py:393-395`).
13. **The direct fallback refuses non-public targets** on every redirect hop (`deerflow_bridge/cached_fetch.py:178-183`).
14. **Fetched-source provenance requires an http(s) URL, at least 200 stripped characters, and no `Error:` prefix** (`deerflow_bridge/research_budget.py:516-519`).
15. **Orchestrator-side gates:**
    - at most `RESEARCH_BUDGET_MAX_EPOCHS` ledgers per pipeline (`backend/app/services/pipeline_orchestrator.py:1851-1856`);
    - the pre-launch exhaustion guard is matched by epoch (`:1764-1798`, `:11104-11110`).

---

## Failure modes & recovery

| Failure | Behavior | Anchor |
|---|---|---|
| SQLite unavailable or corrupt during tool admission, negative, positive, claim, provenance or circuit calls | **Fail open**: admitted with `degraded=True`, `negative_suppressed`→False, claim→`uncontrolled:`, circuit→closed; `_emit_degraded` writes a degraded telemetry payload | `deerflow_bridge/research_budget.py:286-288`, `:320-322`, `:382-384`, `:666-668`, `:822-824`, `:1491-1508` |
| SQLite busy or locked while acquiring a lease | Retries until the deadline, then `TimeoutError` (not fail-open) | `deerflow_bridge/research_budget.py:996-1005`, `:1010-1014` |
| Other lease-ledger error | Fail open: yields `Admission(True,"ledger_unavailable",True)` | `:1006-1009`, `:1193-1197` |
| Process SIGKILLed while holding a lease or claim | The lease expires after its TTL (120 s) without a heartbeat. The claim expires after 120 s and is purged at the next `claim_request` | `:878-885`, `:801-802` |
| Budget exhausted | Tool returns the `research_budget_exhausted` JSON with `results: []`. The legacy bridge breaks streams after N consecutive denials (`RESEARCH_BUDGET_DENIAL_BREAK_AT`, `.env.example:337`). The orchestrator refuses the next launch for the same epoch; an explicit resume opens a new epoch | `deerflow_bridge/research_budget.py:839-852`; `backend/app/services/pipeline_orchestrator.py:11104-11110` |
| Identical in-flight request stalls more than 45 s | Follower returns `research_inflight_timeout` JSON (not negative-cached) | `deerflow_bridge/cached_fetch.py:769-774`; `deerflow_bridge/search_tools.py:666-671` |
| Provider transport failures (timeouts, connection errors, Firecrawl 429) | Counted per provider. At 5 consecutive the circuit opens for 120 s and others skip that provider. After cooldown one 30 s probe lease is granted. Success resets it | `deerflow_bridge/research_budget.py:620-763`; `deerflow_bridge/cached_fetch.py:389-410` |
| Firecrawl per-process ceiling | Fetch: `Error:` sentinel, then the chain continues to Jina or Exa. Search: transient error JSON (no fallback to another search provider) | `deerflow_bridge/cached_fetch.py:301-313`, `:439-443`; `deerflow_bridge/search_tools.py:447-457` |
| Firecrawl search 429 | Up to 4 retries with backoff (hint+1 s or 5×2^n, plus 0–2 s jitter, capped at 70 s) | `deerflow_bridge/search_tools.py:485-497` |
| Search provider module import failure | Falls back to DDG; if DDG is also missing, returns `{"error":"no web_search backend available"}` | `deerflow_bridge/search_tools.py:586-596` |
| Search delegate raises | Returns `{"error": str(e), "query"}` and never raises | `deerflow_bridge/search_tools.py:691-696` |
| `fetch_fn` raises (rare; `_resilient_fetch` catches internally) | `cached_fetch` re-raises after releasing the claim and exporting telemetry | `deerflow_bridge/cached_fetch.py:788-796` |
| Cache read, write or evict error | Treated as a miss or skipped; the result is unchanged | `deerflow_bridge/cached_fetch.py:633-634`, `:653-654`, `:688-689`; `deerflow_bridge/search_tools.py:625-627`, `:714-716` |
| Without langchain or deerflow | Modules still import; the tool variables are `None` | `deerflow_bridge/cached_fetch.py:853-854`; `deerflow_bridge/search_tools.py:745-746` |
| Without the `research_budget` module beside the tools | All budget logic is skipped, leaving plain cache-plus-provider behaviour | `deerflow_bridge/cached_fetch.py:48-51`; `deerflow_bridge/search_tools.py:52-55` |

---

## Surprises

1. **Doc-vs-code drift (search provider order).** `DRF_ARCHITECTURE.md:484-490`, `ARCHITECTURE_MAP.md:1003`, the `config.yaml` comment at `deerflow_bridge/config.yaml:718-724`, and `.env.example:399-400` all describe search precedence as Serper > Tavily > DDG. The code includes **Firecrawl** between Tavily and DDG (`deerflow_bridge/search_tools.py:347-353`). `README.md:652` is correct. [verifier: imprecise for `.env.example` — it is internally inconsistent rather than uniformly stale: `.env.example:402` correctly documents Firecrawl as the search backend when no Serper/Tavily key is set and as the primary fetch provider, while `:399-400` keep the old Serper > Tavily > DDG wording (`.env.example:399-402`). DRF_ARCHITECTURE's registration anchor `config.yaml:726` is also stale; the stanza is at `deerflow_bridge/config.yaml:730-735`.]

2. **Doc-vs-code drift (fetch path).** The module docstring (`deerflow_bridge/cached_fetch.py:1-15`), `DRF_ARCHITECTURE.md:491-492`, `ARCHITECTURE_MAP.md:1004` and `.env.example:415-416` describe `web_fetch` as a transparent cache over **Jina**, or "Jina→Exa" [verifier: `.env.example:402` contradicts its own `:415` by correctly naming Firecrawl `/scrape` as the primary fetch provider (`.env.example:402`, `:415`)]. In code, **Firecrawl leads when keyed**, then Jina, Exa and opt-in direct (`deerflow_bridge/cached_fetch.py:425-502`). The DRF_ARCHITECTURE line anchors are also stale: `_select_search_provider` is cited `:315` but is at 338; `_filter_denied_search_results` is cited `:188` but is at 211; `_jina_delegate_fetch` is cited `:347` but is at 820; `_configure_research_budget_env` is cited `:887-928` but is at orchestrator 1986-2026.

3. **The effective Jina timeout is 10 s, not 30 s.** `deerflow_bridge/config.yaml:792-802` argues for a 30 s Jina timeout, and the delegated Jina tool does read 30 from the stanza. However `_resilient_fetch` wraps it in `asyncio.wait_for(timeout=RESEARCH_JINA_PRIMARY_TIMEOUT_SECONDS`, default 10) (`deerflow_bridge/cached_fetch.py:461-464`), so heavy documents time out at 10 s unless the env is raised.

4. **DRF_ARCHITECTURE §5.6 overstates three behaviours** (`DRF_ARCHITECTURE.md:510-519`):
   - "Positive-repeat dedup" is **off by default** (`RESEARCH_COMPACT_REPEAT_RESULTS=false`, `deerflow_bridge/research_budget.py:434-437`) and applies only to positive disk-cache hits.
   - "The same DB arbitrates LLM concurrency" is wrong in orchestrated runs: leases use the separate application-wide `RESEARCH_MODEL_LEASE_DB` (`backend/app/services/pipeline_orchestrator.py:2404-2410`).
   - "Fails open on any ledger error" is wrong for leases: they wait on contention and raise `TimeoutError` or `ValueError` (`deerflow_bridge/research_budget.py:921-925`, `:1010-1014`). [verifier: imprecise — leases still fail open on every non-contention ledger error: any `OperationalError` without "busy"/"locked", and any other exception, yields `Admission(True,"ledger_unavailable",True)` (`deerflow_bridge/research_budget.py:996-1009`, `:1185-1197`). Only busy/locked contention and a saturated ledger wait and then raise `TimeoutError`. The `ValueError` is a caller-side weight-over-capacity check, not a ledger error (`:919-925`).]

5. **Suspected: the half-open gating applies below the threshold.** `provider_circuit_open` enters probe-lease mode whenever `consecutive_transport_failures > 0`, even if the circuit never opened (`deerflow_bridge/research_budget.py:644-657`). After a single Jina timeout, only one caller per 30 s probe window may use Jina, and every other concurrent caller skips it (counted as `circuit_skips`). This lasts until a success. [verifier: imprecise — the limit is one in-flight probe at a time, not one per 30 s. A transport failure resets `probe_until=NULL` (`deerflow_bridge/research_budget.py:708`), so the next caller takes a new probe immediately. The 30 s lease only bounds a probe that ends in neither a success nor a transport failure. A scratch-DB run after one `ReadTimeout` gave: caller A closed, B open; after A's failure was recorded, C closed, D open. The gating below the threshold is confirmed.] A non-transport failure (for example a short or dead page) clears neither the probe nor the failure count (`deerflow_bridge/cached_fetch.py:397-403`). The docstring (`:621-626`) describes this as post-cooldown behaviour only.

6. **Suspected: control outcomes pollute the negative cache.** When `_resilient_fetch` returns a **budget denial** from `_reserve_additional_physical_fetch`, or `"Error: no web-fetch provider was available"` because every circuit was open, `cached_fetch` treats the result as non-cacheable and calls `record_negative` for the URL (`deerflow_bridge/cached_fetch.py:456-458`, `:500-502`, `:809-810`). A healthy URL can then be suppressed for 10 minutes. In the all-skipped case, a network unit was also already spent at `:783` even though no request was made.

7. **Suspected: an exhausted Firecrawl quota halves the effective fetch budget.** Firecrawl 402 and 5xx errors are not transport failures (`deerflow_bridge/cached_fetch.py:366-371`, `:70-80`), so the circuit never opens. Every fetch then makes a Firecrawl call **and** reserves a second network unit for Jina (`:455-458`), until the 400-call per-process ceiling is reached. With the 180-per-lane fetch cap, a lane can be exhausted after about 90 URLs.

8. **Cap semantics are inconsistent.**
   - `_env_int(minimum=0)` lets a cap of `0` mean "deny everything" (`deerflow_bridge/research_budget.py:66-71`, `:275`, `:309-312`).
   - The orchestrator's `_research_budget_exhaustion` ignores limits ≤ 0 (`backend/app/services/pipeline_orchestrator.py:1796`).
   - The Firecrawl ceilings use `<= 0` to mean **unlimited** (`deerflow_bridge/cached_fetch.py:306`; `deerflow_bridge/search_tools.py:448`).
   - `RESEARCH_NEGATIVE_CACHE_TTL_SECONDS=0` disables suppression (`deerflow_bridge/research_budget.py:343-344`).

9. **Suspected: degraded telemetry is lossy and not sticky.**
   - `_emit_degraded` overwrites the whole telemetry file with a payload that has no counters, limits or `epoch` (`deerflow_bridge/research_budget.py:1497-1504`). The next successful `export_telemetry` writes `"degraded": False` back (`:1354`), erasing the marker.
   - While the degraded payload is current, the orchestrator's epoch-matched exhaustion guard returns None, because the `epoch` field is missing (`backend/app/services/pipeline_orchestrator.py:1781-1782`).

10. **Suspected: the telemetry epoch can differ from the guard's epoch on resume.** On explicit resume the orchestrator sets `RESEARCH_BUDGET_EPOCH` to the **prior** `resume_attempt_id` (`backend/app/services/pipeline_orchestrator.py:2388-2395`), but the activated ledger epoch is the new task id (`:1858`). The bridge writes `epoch` from env (`deerflow_bridge/research_budget.py:1351`), so later `_research_budget_exhaustion(…, budget_epoch)` checks against that telemetry would not match. This is unverified end to end; it is orchestrator-side.

11. **Suspected lease leak on asyncio cancellation.** `async_model_call_lease` and `async_subagent_call_lease` run the blocking `__enter__` in `asyncio.to_thread` (`deerflow_bridge/research_budget.py:1055`, `:1242`). If the awaiting task is cancelled while waiting, the worker thread still acquires the lease and starts a daemon heartbeat. `__exit__` is never called, so the lease stays heartbeated, and global capacity stays reduced, until the process exits. [verifier: refuted — when the worker thread's `__enter__` returns, it drops the last reference to the abandoned `_GeneratorContextManager`. CPython then finalizes the suspended generator, raising `GeneratorExit` at the `yield`, and the `finally` block stops the heartbeat and releases the lease (`deerflow_bridge/research_budget.py:1042-1047`, `:1229-1234`). A scratch-DB experiment (capacity 1, cancel the waiting task, then free capacity) gave `model_lease_acquisitions=2` but 0 rows in `model_leases` within 0.25 s. The only residue is a brief phantom acquisition that telemetry counts.]

12. **Telemetry write amplification and lease-DB contention.**
    - `clear_negative` **always** forces a full export (`deerflow_bridge/research_budget.py:427`), and it runs on every successful fetch and search.
    - Each forced `_snapshot` opens `BEGIN IMMEDIATE` on the tool DB **and** on the application-wide lease DB (`:1280-1286`), then fsyncs the JSON.
    - On a busy machine this competes with lease acquisitions from every pipeline.

13. **Duplicated logic.**
    - The cache read, write and LRU code is copy-pasted between the two tool modules (`deerflow_bridge/cached_fetch.py:611-689` versus `deerflow_bridge/search_tools.py:259-335`).
    - The domain denylist is implemented twice: `deerflow_bridge/cached_fetch.py:505-528` and `deerflow_bridge/deerflow_research.py:2070-2088`, with the same default list.
    - The Firecrawl over-ceiling check runs both in `_resilient_fetch` (`:439-443`) and inside `_firecrawl_fetch` (`:333-335`).
    - Each module keeps its own `_firecrawl_ceiling_warned` global.

14. **Dead or test-only code.** `get_firecrawl_call_counts()` in both modules ("for future budget telemetry export") is referenced only by `backend/tests/test_sessionb_firecrawl_guardrails.py:273-291` (`deerflow_bridge/cached_fetch.py:316-318`; `deerflow_bridge/search_tools.py:391-393`).

15. **Firecrawl ceilings are named "per-run" but are per process.** The error strings say "per-run" (`deerflow_bridge/cached_fetch.py:313`; `deerflow_bridge/search_tools.py:455`), but the counters are per-process globals. Each outer-track subprocess has its own 400/300 allowance, and the v3 engine runs everything in one process.

16. **The search provider has no transport failover or circuit.** Only an *import* failure falls back to DDG (`deerflow_bridge/search_tools.py:586-593`). A Serper outage returns error JSON on every call, and `provider_circuit_open` is never consulted for search.

17. **`max_results` is mostly cosmetic for search.** Serper, Tavily and DDG override it with the config stanza value of 10 (see `_call_delegate` notes), yet it is part of the cache and negative key (`deerflow_bridge/search_tools.py:155-158`, `:599`). Different `max_results` values therefore miss the cache for identical results. Only Firecrawl honours it, clamped to 5.

18. **Thread-safety gaps (suspected, minor).**
    - `_firecrawl_throttle` mutates the module-level `_firecrawl_window` without a lock (`deerflow_bridge/search_tools.py:414-432`), so concurrent sync tool threads can exceed the per-minute cap.
    - The cache temp name `<path>.<pid>.tmp` is not unique per thread or task (`deerflow_bridge/cached_fetch.py:647`; `deerflow_bridge/search_tools.py:296`). Concurrent same-URL writes in one process can collide; this happens when single-flight is off, i.e. when the budget is disabled. [verifier: imprecise — single-flight is also bypassed when `claim_request` fails open with an `uncontrolled:` token (`deerflow_bridge/research_budget.py:822-824`) or when `research_budget` is not importable (`deerflow_bridge/cached_fetch.py:48-51`). A second owner can also start when the first owner outlives the 120 s claim TTL, because claims have no heartbeat and expired claims are purged (`deerflow_bridge/research_budget.py:790-802`).] Orphaned `.tmp` files are never evicted because the cap only scans `*.json`.

19. **Direct-fallback edge cases (suspected).**
    - After 6 redirect hops the loop ends holding a 3xx response, which is then processed as content (`deerflow_bridge/cached_fetch.py:178-191`).
    - The size limit is checked only after the full body has been downloaded (`:196`).
    - DNS is resolved separately from httpx's own connection, which leaves a rebinding window.
    - The User-Agent still points at the archived `DeepAgentForecast` repository (`:165-169`).

20. **Content-failure markers can reject legitimate pages.** Any page whose first 1200 characters contain words like "captcha", "page not found" or "access denied" is treated as dead and negative-cached (`deerflow_bridge/cached_fetch.py:81-89`, `:596-598`).

21. **Small inconsistencies.**
    - The fetch disk-cache key uses the raw `url`, but budget keys use `url.strip()` (`deerflow_bridge/cached_fetch.py:702` versus `:713`).
    - The `_is_cacheable` length test uses the unstripped length (`:608`), while provenance uses the stripped length (`deerflow_bridge/research_budget.py:518`).
    - Lane default `track-1` (`deerflow_bridge/research_budget.py:89`) versus the orchestrator's `outer-track-1` (`backend/app/services/pipeline_orchestrator.py:2010`).
    - Single-flight claims last 120 s with no heartbeat, while followers wait only 45 s (`deerflow_bridge/research_budget.py:790-794`; `deerflow_bridge/cached_fetch.py:745-748`). The worst-case fetch chain of Firecrawl 25 s + Jina 10 s + Exa 15 s exceeds 45 s, so followers can time out while the owner is still working.

22. **The search cache stores raw queries in plaintext** (`deerflow_bridge/search_tools.py:289-292`), and the fetch cache stores raw URLs and bodies. The budget ledger, by contrast, deliberately hashes keys for privacy (`deerflow_bridge/research_budget.py:393-395`). This is not a bug, but the privacy posture differs between layers.

---

## Verification

Adversarial verification on 2026-10-11 against `main` as checked out on disk. Every cited anchor in the slice files was opened. The deployed copies under `deer-flow/` were re-checked with `cmp` and are still byte-identical, and the cache file counts (4 888 fetch, 10 026 search) still match. Two behaviours were also checked by running a scratch copy of `research_budget.py` against throwaway SQLite files outside the repo: probe gating and lease release on cancellation. No repo file other than this map was touched, and no network or provider was called.

### Verdict counts

30 statements checked: the 15 key claims, the 14 key surprises, and 1 extra body statement.

- **Confirmed:** 24
- **Imprecise:** 5
- **Refuted:** 1
- **Unverifiable:** 0

Spot-checks of Walkthrough and Control-flow statements found everything else accurate. Statements checked:
- deploy copy list (`backend/app/services/pipeline_orchestrator.py:1359-1362`, `:1530-1533`; `setup.sh:597`);
- lane ids (`:11179`, `:11502`, `:10948`);
- lease-DB default (`backend/app/config.py:1216-1219`, `UPLOAD_FOLDER` at `:1048`);
- `RESEARCH_BUDGET_ENABLED` and `RESEARCH_BUDGET_MAX_EPOCHS` (`backend/app/config.py:528-529`, `:543-544`);
- v3 `_bridge_lease` 300 s cap (`deerflow_bridge/linear_research.py:6141-6215`);
- telemetry summary and the 0.05 penalty (`backend/app/services/pipeline_orchestrator.py:10583-10605`, `:10676-10679`);
- `_source_title`, `_direct_http_fetch` limits, Exa limits, the Firecrawl 429 mapping, `_resilient_fetch` return precedence, the follower poll back-off, the search 429 back-off, the throttle cap, `_call_delegate` signature handling (`deer-flow/.../serper/tools.py:42-44`, `ddg_search/tools.py:144-151`, `tavily/tools.py:24-27`), and the Jina stanza timeout (`deer-flow/.../jina_ai/tools.py:56-61`);
- `.env.example:155` and `:337`.

### Non-confirmed items and corrections

1. **Key claim, imprecise: "hits and followers never use network allowance"** (`deerflow_bridge/cached_fetch.py:706-786`; `deerflow_bridge/search_tools.py:577-683`).
   - The part about `admit_attempt` running before the cache is correct.
   - Only followers satisfied from the disk cache skip `admit_network`.
   - A follower that wins the claim after the owner released it without a cache write re-checks the negative cache, consumes the one retry, and then reserves a network unit and fetches (`deerflow_bridge/cached_fetch.py:766-786`; `deerflow_bridge/search_tools.py:662-683`; `deerflow_bridge/research_budget.py:365-378`).
2. **Surprise, imprecise: doc drift incl. `.env.example`.**
   - Drift in DRF_ARCHITECTURE §5.5, ARCHITECTURE_MAP:1003-1004, and the config.yaml comments (`deerflow_bridge/config.yaml:718-724`, `:792-798`) is confirmed. So are the stale DRF anchors (`DRF_ARCHITECTURE.md:301`, `:487`, `:490`, `:492`), plus `config.yaml:726` at `DRF_ARCHITECTURE.md:484`.
   - However, `.env.example` is internally inconsistent rather than uniformly stale. `.env.example:402` correctly documents Firecrawl as the primary fetch provider and as the search backend when no Serper/Tavily key is set. Only `:399-400` and `:415` carry the old wording.
3. **Surprise, imprecise: DRF §5.6 "leases wait or raise instead of failing open".**
   - Leases do fail open on every non-contention ledger error (`deerflow_bridge/research_budget.py:996-1009`, `:1185-1197`).
   - Only busy/locked contention and saturation wait, then raise `TimeoutError` (`:1010-1014`).
   - `ValueError` is a caller weight check, not a ledger error (`:919-925`).
   - The other two sub-points are confirmed: compaction is off by default (`:434-437`), and the lease DB is separate and application-wide (`backend/app/services/pipeline_orchestrator.py:2404-2410`).
4. **Surprise, imprecise: "roughly one in-flight caller per 30 s".**
   - Gating below the threshold is confirmed: `failures > 0` is enough (`deerflow_bridge/research_budget.py:644-657`).
   - However, the slot is one in-flight probe at a time. A transport failure clears `probe_until` (`:708`), so the next caller probes immediately. The 30 s lease only expires a probe that ended with neither a success nor a transport failure. The scratch-DB run confirmed this: A closed, B open; after A's failure, C closed, D open.
5. **Surprise, refuted: lease leak on asyncio cancellation** (`deerflow_bridge/research_budget.py:1050-1064`, `:1237-1251`).
   - The abandoned generator is finalized by CPython once the worker thread drops its last reference. The `finally` block then stops the heartbeat and deletes the lease row (`:1042-1047`, `:1229-1234`).
   - Experiment: with capacity 1, a cancelled waiter's thread acquired the lease once capacity freed (`model_lease_acquisitions=2`), but `model_leases` held 0 rows within 0.25 s.
   - The real residue is a brief phantom acquisition counted in telemetry.
6. **Body statement, imprecise: "single-flight is off, i.e. when the budget is disabled"** (surprise 18).
   - Single-flight is also bypassed when a claim degrades to `uncontrolled:` (`deerflow_bridge/research_budget.py:822-824`) or when `research_budget` is absent (`deerflow_bridge/cached_fetch.py:48-51`).
   - A second owner can start when the first owner outlives the 120 s heartbeat-less claim (`deerflow_bridge/research_budget.py:790-802`).

### Confirmed with added detail

- **Resume epoch mismatch (surprise 10).** The code path is confirmed: `env["RESEARCH_BUDGET_EPOCH"] = resume_attempt_id` (`backend/app/services/pipeline_orchestrator.py:2388-2395`), versus the ledger `epoch = task_id` (`:1859`), versus the telemetry `epoch` from env (`deerflow_bridge/research_budget.py:1351`), versus the guard's epoch equality check (`backend/app/services/pipeline_orchestrator.py:1781-1782`). A concrete consequence the map did not name: synthesis recovery reuses the current epoch whenever `_research_budget_exhaustion(...) is None` (`:1951-1957`), so a mismatched epoch makes an exhausted ledger look reusable. The guard is also called at `:10877` and `:12038`, not only at `:11104`.
- **`clear_negative` forced export (surprise 11).** This happens on every successful *network* (cache-miss) result, not on cache hits (`deerflow_bridge/cached_fetch.py:799-800`; `deerflow_bridge/search_tools.py:701-702`).

### Omissions (significant behaviour the map does not cover)

1. **Blocking SQLite and fsync on the event loop.**
   - The async `cached_fetch` calls the synchronous ledger APIs directly on the event-loop thread: `admit_attempt`, `negative_suppressed`, `claim_request`, `admit_network`, `record_*`, and forced `export_telemetry`, which fsyncs. Each connection has a 10 s busy timeout. So do `_provider_circuit_open` and `_reserve_additional_physical_fetch` inside `_resilient_fetch`, and so does disk-cache I/O with fsync.
   - Ledger contention can therefore stall every coroutine in the research process (`deerflow_bridge/cached_fetch.py:706-813`, `:437-494`; `deerflow_bridge/research_budget.py:218-220`, `:1476-1483`).
2. **Probe gating × keyless setup compounds surprises 5 and 6.**
   - Setup: no Firecrawl or Exa key, and the direct fallback off (the default).
   - After one Jina transport failure, every concurrent caller without the probe gets `Error: no web-fetch provider was available`.
   - It has already spent a fetch network unit (`deerflow_bridge/cached_fetch.py:783`), and the healthy URL is negative-recorded (`:809-810`). See `deerflow_bridge/cached_fetch.py:453-502` and `deerflow_bridge/research_budget.py:644-657`.
3. **Serper empties are never negative-cached.**
   - DeerFlow's Serper tool, the top-precedence search backend, reports an empty result as `{"error":"No results found"}` (`deer-flow/backend/packages/harness/deerflow/community/serper/tools.py:77-79`).
   - `_is_search_no_result` returns False for any truthy `error` (`deerflow_bridge/search_tools.py:203-205`), so repeated empty Serper queries are never suppressed. Each one costs an attempt and a network unit (`:698-705`).
   - The v3 gateway separately maps the "No results" prefix to `MSG_NO_RESULTS` (`deerflow_bridge/research_gateway.py:3602`).
4. **The Firecrawl search ceiling still spends network units.** `admit_network("search")` runs before `_firecrawl_search` checks its per-process ceiling. After 300 calls, every search reserves a unit and returns error JSON without any request, and error JSON is never negative-cached (`deerflow_bridge/search_tools.py:679-688`, `:447-457`, `:699-705`).
5. **A Firecrawl probe lease can be taken without a request.**
   - `_resilient_fetch` evaluates `_provider_circuit_open("firecrawl")` before the ceiling check. When failures > 0, this takes the 30 s probe lease.
   - A ceiling hit then makes no request and records neither a success nor a failure. Firecrawl stays gated for other processes until the lease expires (`deerflow_bridge/cached_fetch.py:437-443`; `deerflow_bridge/research_budget.py:644-657`).
6. **In-code doc drift in `search_tools`.** The docstring and comment claim Firecrawl has no harness community module (`deerflow_bridge/search_tools.py:10`, `:343`). The vendored DeerFlow does ship one (`deer-flow/backend/packages/harness/deerflow/community/firecrawl/tools.py:18`, `:50`); DRF simply bypasses it with its own HTTP client.
