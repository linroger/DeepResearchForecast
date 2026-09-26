# DeepResearchForecast — Complete External Integrations Map

> **Purpose**: Maps every external system boundary, data flow, protocol, auth mechanism, and failure mode relevant to building an event-based AI quant trading system.
>
> **Last Updated**: 2026-09-27
> **Scope**: Entire repo at `/Users/rogerlin/Downloads/DeepResearchForecast`

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [LLM Provider Integrations](#2-llm-provider-integrations)
3. [Web Search Providers](#3-web-search-providers)
4. [Web Fetch / Page Extraction](#4-web-fetch--page-extraction)
5. [Prediction Market Data (Polymarket)](#5-prediction-market-data-polymarket)
6. [Knowledge Graph (Graphiti/FalkorDB)](#6-knowledge-graph-graphitifalkordb)
7. [MCP Servers (stdio)](#7-mcp-servers-stdio)
8. [Simulation Engine (OASIS/CAMEL)](#8-simulation-engine-oasiscamel)
9. [Backend API Layer (Flask)](#9-backend-api-layer-flask)
10. [Frontend Integration](#10-frontend-integration)
11. [Database & Storage](#11-database--storage)
12. [Cross-Process Communication](#12-cross-process-communication)
13. [Budget, Rate Limiting & Circuit Breakers](#13-budget-rate-limiting--circuit-breakers)
14. [Telemetry & Observability](#14-telemetry--observability)
15. [Security & SSRF Protections](#15-security--ssrf-protections)
16. [What Needs to Change for Live Trading](#16-what-needs-to-change-for-live-trading)

---

## 1. Architecture Overview

The system is a **6-stage pipeline**: `research → ontology → graph → prepare → run → report`.

```
Frontend (Vue.js)
    │
    │ HTTP (axios, same-origin via Vite proxy)
    ▼
Backend (Flask) ──→ PipelineOrchestrator
    │                    │
    │          ┌─────────┼──────────┐
    │          ▼         ▼          ▼
    │    DeerFlow     Graphiti    OASIS
    │    (research)   (KG build)  (simulation)
    │          │         │          │
    │    ┌─────┼─────┐  │    ┌─────┼─────┐
    │    ▼     ▼     ▼  │    ▼     ▼     ▼
    │  Serper  Jina  Polymarket  CAMEL  LLM   File-based IPC
    │  Tavily  Firecraw  Gamma   agents  (claude/│
    │  DDG     httpx   CLOB     (subproc) codex) │
    │                          │              │
    │                          └── FalkorDB ◄─┘
    │                          (embedded)
    │
    └── MCP servers (kg_server, sim_server) via stdio
```

**Key design pattern**: Everything is **poll-based** (no WebSockets). The frontend polls `/api/research/<id>/status` for progress. Research runs as **detached subprocesses** with their own asyncio loops.

---

## 2. LLM Provider Integrations

### 2.1 Supported Providers

| Provider | Protocol | Auth | Config Key | Use Case |
|----------|----------|------|------------|----------|
| **claude-cli** | Subprocess (`claude -p`) | Claude Code OAuth (`~/.claude/.credentials.json`) | `LLM_PROVIDER=claude-cli` | Default research model |
| **codex-cli** | Subprocess (`codex -p`) | Codex OAuth | `LLM_PROVIDER=codex-cli` | Alternative CLI |
| **openai** | HTTPS (OpenAI SDK) | `LLM_API_KEY` | `LLM_PROVIDER=openai` | Fallback |
| **kimi** | HTTPS (OpenAI-compatible) | `LLM_API_KEY` | `LLM_PROVIDER=kimi` | Fast/cheap; needs coding-agent UA |
| **minimax** | HTTPS (OpenAI-compatible) | `LLM_API_KEY` | `LLM_PROVIDER=minimax` | High-capacity reasoning |
| **deepseek** | HTTPS (OpenAI-compatible) | `LLM_API_KEY` | `LLM_PROVIDER=deepseek` | 1M context |
| **qwen** | HTTPS (OpenAI-compatible) | `LLM_API_KEY` | `LLM_PROVIDER=qwen` | Alibaba DashScope |
| **glm** | HTTPS (OpenAI-compatible) | `LLM_API_KEY` | `LLM_PROVIDER=glm` | Zhipu GLM-4.6 |
| **antigravity** | HTTPS (Quotio local proxy) | `LLM_FALLBACK_API_KEY` | Env var | Fallback via local adapter |

### 2.2 Protocol Details

- **CLI providers**: `subprocess.Popen` with stdin piping. Command: `claude -p --output-format json`. Prompt fed via stdin (not argv, to avoid `E2BIG`). Model pinned via `--model` flag.
- **OpenAI-compatible providers**: `openai.OpenAI` SDK client with `chat.completions.create()`. HTTP/2 with keepalive pools when `LLM_HTTP2=true`.
- **Concurrency**: CLI providers bounded by `OASIS_CLI_SEMAPHORE` (default 8). OpenAI-compatible by `OASIS_SEMAPHORE` (default 30).

### 2.3 Failover Chain

```
Primary provider → Circuit breaker check → Retry (3x, exponential backoff)
  → Content-filter (422) circuit breaker → Quota (429) circuit breaker
    → Fallback provider (LLM_FALLBACK_PROVIDER) → Connection pool reuse
      → If all fail → raise RuntimeError
```

### 2.4 Key Config

- `Config.LLM_PROVIDER` — active provider
- `Config.LLM_MODEL_NAME` — model name
- `Config.LLM_API_KEY`, `Config.LLM_BASE_URL` — for API providers
- `Config.LLM_FALLBACK_PROVIDER`, `Config.LLM_FALLBACK_API_KEY`, `Config.LLM_FALLBACK_BASE_URL` — failover
- `Config.LLM_TIERED_ROUTING` — dual fast/strong model routing
- `Config.LLM_CB_422_THRESHOLD`, `Config.LLM_CB_429_THRESHOLD` — circuit breaker thresholds
- `Config.LLM_RUN_BUDGET_TOKENS`, `Config.LLM_RUN_BUDGET_USD` — per-run budget guard

### 2.5 Rate Limiting / Concurrency

- **Retry**: 3 attempts, exponential backoff (`2^attempt * 2s`, capped at 30s)
- **429 handling**: Respects `Retry-After` header; circuit breaker after 8 consecutive 429s (300s cooldown)
- **422 content-filter**: Circuit breaker after 5 consecutive (300s cooldown)
- **Model lease**: SQLite-based global concurrency cap (`RESEARCH_MODEL_CONCURRENCY_GLOBAL=12`), heartbeat-renewed leases
- **Subagent lease**: Global cap of 9 concurrent subagents

### 2.6 Failure Modes

- Empty content from reasoning models (`finish_reason=length`) → RuntimeError
- Deterministic auth errors (401) → No retry, immediate failover
- Deterministic invalid-request (400) → No retry, process-level cooldown
- Content-filter (422) → Circuit breaker, failover to fallback
- Quota exhaustion (429) → Circuit breaker, failover

---

## 3. Web Search Providers

### 3.1 Provider Selection Logic (`search_tools.py`)

```
SERPER_API_KEY set? → serper
TAVILY_API_KEY set? → tavily
FIRECRAWL_API_KEY set? → firecrawl (direct HTTP)
Otherwise → ddg (keyless community)
```

### 3.2 Integration Details

| Provider | API | Auth | Protocol | Notes |
|----------|-----|------|----------|-------|
| **Serper** | `deerflow.community.serper.tools:web_search_tool` | `SERPER_API_KEY` | HTTPS JSON | Via harness community module |
| **Tavily** | `deerflow.community.tavily.tools:web_search_tool` | `TAVILY_API_KEY` | HTTPS JSON | Via harness community module |
| **Firecrawl** | `https://api.firecrawl.dev/v2/search` | `FIRECRAWL_API_KEY` (Bearer) | HTTPS JSON (POST) | Direct `httpx` call, no SDK |
| **DuckDuckGo** | `deerflow.community.ddg_search.tools:web_search_tool` | None | HTTPS JSON | Zero-key community fallback |

### 3.3 Rate Limiting / Guards

- **Firecrawl**: Process-in-60s rolling window throttle (default 8 calls/min), 429 retry with `Retry-After` parsing (up to 4 retries), per-process call ceiling (default 300)
- **Search cache**: SHA256-based disk cache (`RESEARCH_SEARCH_CACHE_TTL_H=6h`, max 200MB), LRU eviction
- **Budget**: SQLite ledger (`RESEARCH_BUDGET_DB`) with global/lane counters for search attempts and network calls
- **Negative caching**: Empty results cached for 600s to prevent repeated useless queries

### 3.4 Firecrawl Direct Implementation (`_firecrawl_search`)

- Endpoint: `https://api.firecrawl.dev/v2/search` (configurable via `FIRECRAWL_SEARCH_API_URL`)
- Headers: `Authorization: Bearer {FIRECRAWL_API_KEY}`, `Content-Type: application/json`
- Body: `{query, limit, sources: ["web"]}`
- 429 handling: Parse "retry after Ns" from body, fallback to exponential backoff
- Call ceiling enforced before network request (prevents billing surprises)

---

## 4. Web Fetch / Page Extraction

### 4.1 Fetch Pipeline (`cached_fetch.py`)

```
URL → [Firecrawl /scrape] → [Jina web_fetch] → [Exa] → [Direct HTTP fallback]
       (when FIRECRAWL_API_KEY)    (primary)        (when EXA_API_KEY)  (opt-in)
```

### 4.2 Provider Details

| Provider | API | Auth | Protocol | Notes |
|----------|-----|------|----------|-------|
| **Firecrawl** | `https://api.firecrawl.dev/v2/scrape` | `FIRECRAWL_API_KEY` (Bearer) | HTTPS POST (httpx) | Managed JS rendering |
| **Jina** | `deerflow.community.jina_ai.tools:web_fetch_tool` | None (anonymous) | Async HTTP | Primary extractor |
| **Exa** | `exa_py` SDK | `EXA_API_KEY` | HTTPS | Fallback extractor |
| **Direct HTTP** | `httpx.AsyncClient` | None | HTTPS | Opt-in fallback, public-URL only |

### 4.3 Guards

- **Firecrawl**: Per-process call ceiling (default 400), per-call timeout (25s), `maxAge` parameter for cache-reuse (172800s=2 days)
- **Source policy**: Rejects `economicsummarizer.com`, `insights.triplegains.com` unless `RESEARCH_ALLOW_LOW_QUALITY_SOURCES=true`
- **Cache**: SHA256(url) → `.json` file, TTL 72h, max 500MB, LRU eviction
- **Content check**: Rejects `<200 chars`, `"Error:"` prefixed, content-failure markers
- **Direct fetch guard**: Rejects non-public URLs (private IP ranges, localhost)

### 4.4 Failure Modes

- Jina ConnectTimeout (observed 53% failure rate) → Falls back to Firecrawl
- Firecrawl 402 (payment required) → Error string, not cached
- All providers fail → Returns `"Error: no web-fetch provider was available"`

---

## 5. Prediction Market Data (Polymarket)

### 5.1 Data Sources

| Source | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| **Gamma API** | `https://gamma-api.polymarket.com/public-search` | None (keyless) | Event/market search |
| **Gamma API** | `https://gamma-api.polymarket.com/markets/{id}` | None | Market detail, requote |
| **CLOB** | `https://clob.polymarket.com/prices-history?market={clobTokenId}&interval=1d` | None | Historical price timeline |
| **CLOB** | `https://clob.polymarket.com` | None | CLOB token IDs, order book |

### 5.2 Integration Files

- `backend/app/utils/prediction_markets.py` — `PolymarketClient` class (production use)
- `deerflow_bridge/market_tools.py` — `prediction_market_search_tool` (harness tool, keyless)
- `drf2/config/market_tools.py` — Legacy bridge version

### 5.3 Protocol Details

- **HTTP GET** with `Accept: application/json` and browser-form User-Agent
- **Timeout**: 10-15s per request
- **Retry**: 1 retry on transient errors (429/500/502/503/504), exponential backoff with jitter
- **Rate limiting**: No explicit rate limit config; single-request timeout + one retry

### 5.4 Data Flow

```
Research stage → LLM generates market-shaped queries → PolymarketClient.search_events()
  → snapshot_for_queries() → normalize_market() → Filter (closed, price 0/1, volume < 200)
  → market_price_history.json (90-day CLOB timeline for anchored markets)
  → Injected as "calibration anchors" into research prompts and report sections
```

### 5.5 Key Guards

- `PREDICTION_MARKETS_ENABLED=true` (default) — master switch
- `PREDICTION_MARKETS_MIN_VOLUME=200` — filters low-liquidity markets
- `PREDICTION_MARKETS_MAX=20`, `PREDICTION_MARKETS_MAX_PER_EVENT=3` — result caps
- `PREDICTION_MARKETS_NEGATIVE_CACHE_TTL_SECONDS=30` — prevents repeated empty queries
- Single-flight cache: deduplicates concurrent identical queries
- `MON-1`: Resolution detection — `closed=true` + price ≥ 0.99 → resolved

### 5.6 Failure Modes

- Cloudflare blocking default Python User-Agent → Mitigated by browser-form UA
- Gamma returns empty → `verified_empty` state, not an error
- CLOB history unavailable → Degrade to empty, market still usable as anchor
- Network failure → One log line, then skip (degrade-safe)

### 5.7 For Live Trading

The Polymarket integration is **keyless read-only**. For live trading, you would need:
- **Write access**: Polymarket CLOB API with wallet signing (`CLOB_API_KEY`, `POLYMARKET_SDK`)
- **WebSocket subscriptions**: Real-time price/orderbook feeds
- **Order execution**: `POST /clob-api/v1/orders` with signed payloads
- **Portfolio/position tracking**: `/clob-api/v1/positions`
- **Authentication**: EIP-712 signed messages, nonce-based authentication

---

## 6. Knowledge Graph (Graphiti/FalkorDB)

### 6.1 Architecture

```
ZepToolsService (shim) → Graphiti engine → Embedded FalkorDB (falkordblite)
                                        ↕
                                   Sentence-transformers
                                   (local embedding model)
```

### 6.2 Key Files

- `backend/app/services/zep_tools.py` — `ZepToolsService` class (the actual graph API)
- `backend/app/services/graphiti_client/` — Graphiti shim layer
  - `client.py`, `runtime.py`, `llm_adapter.py`, `embedder.py`, `compat.py`, `falkor_driver.py`
- `backend/app/mcp/kg_server.py` — MCP server exposing `kg_*` tools via stdio

### 6.3 Graph Operations

| Tool | Underlying Method | Purpose |
|------|-------------------|---------|
| `kg_search` | `search_graph` / `as_of_search` | Hybrid semantic + BM25 search |
| `kg_trace_cascade` | `trace_cascade` | Multi-hop causal path tracing |
| `kg_entity_summary` | `get_entity_summary` | Entity profile lookup |
| `kg_get_entities` | `get_entities_by_type` / `get_all_nodes` | Node listing |
| `kg_centrality_priors` | Degree centrality on full graph | Structural influence priors |
| `kg_graph_statistics` | `get_graph_statistics` | Node/edge/type counts |

### 6.4 Storage Backend

- **Default**: Embedded `falkordblite` (no Docker, no server, no API key)
- **Alternatives**: `kuzu`, `falkordb` (external server)
- **Connection**: `FALKORDB_HOST` / `FALKORDB_PORT` (default localhost:6379)
- **Data dir**: `GRAPHITI_DATA_DIR` (default `backend/uploads/graphiti_db`)
- **Embeddings**: `paraphrase-multilingual-MiniLM-L12-v2` (~470MB, downloaded on first run)

### 6.5 Rate Limiting / Concurrency

- `GRAPHITI_OP_TIMEOUT_S=900` — per-operation wall clock cap
- `GRAPHITI_MAX_COROUTINES=16` — intra-episode concurrency
- `GRAPH_LLM_EXECUTOR_WORKERS=64` — dedicated thread pool for blocking LLM HTTP I/O
- Async Graphiti API → sync app via `asyncio.to_thread()` on dedicated event loop

### 6.6 Failure Modes

- Graphiti startup failure → `ZepToolsService` construction fails → MCP tool returns `{ok: False, error: ...}`
- FalkorDB unavailable → Structured error, never hangs (asyncio.wait_for timeout)
- Community detection (`GRAPH_BUILD_COMMUNITIES=false` by default) — can cause 100% CPU if enabled

---

## 7. MCP Servers (stdio)

### 7.1 Server Registry (`extensions_config.json`)

Two MCP servers registered as **stdio** type, launched as subprocesses:

| Server | Command | Protocol | Purpose |
|--------|---------|----------|---------|
| `drf-kg` | `python -m app.mcp.kg_server` | stdio (JSON-RPC) | Knowledge graph queries |
| `drf-simulation` | `python -m app.mcp.sim_server` | stdio (JSON-RPC) | OASIS simulation control |

### 7.2 Protocol Details

- **Transport**: stdio (stdin/stdout for JSON-RPC)
- **SDK**: Official `mcp` Python SDK (`mcp.server.fastmcp.FastMCP`)
- **Tool registration**: Decorator-based (`@server.tool(name=...)`)
- **Timeout**: `DRF_MCP_KG_TIMEOUT=60s`, `DRF_MCP_SIM_TIMEOUT=120s`

### 7.3 kg_server Tools (6 tools)

All wrap `ZepToolsService` with:
- Lazy service construction (first call only)
- `asyncio.wait_for(asyncio.to_thread(...))` timeout enforcement
- Structured error: `{ok: False, error: "..."}` never hangs the protocol

### 7.4 sim_server Tools (3 tools)

- `sim_status` — File-based state poll, no blocking
- `sim_results` — Timeline + agent stats + run_summary
- `sim_interview_agents` — Blocking interview via file-based IPC (`SimulationIPCClient`)

### 7.5 Failure Modes

- Server starts before graph/simulation exists → Tools return structured errors, never hang
- `SimulationIPCClient.check_env_alive()` → Immediate rejection if simulation process dead
- `asyncio.TimeoutError` → `{ok: False, error: "TimeoutError: ..."}`

---

## 8. Simulation Engine (OASIS/CAMEL)

### 8.1 Architecture

```
PipelineOrchestrator → SimulationRunner → OASIS agents (CAMEL framework)
                                              │
                                    ┌───────────┼───────────┐
                                    ▼           ▼           ▼
                              CLIModel    OpenAIModel   OpenAIModel
                            (claude-cli)  (kimi/etc)  (minimax/etc)
                                    │           │           │
                              subprocess  HTTP API    HTTP API
                                    │           │           │
                              twitter     reddit      twitter/reddit
                              platform    platform    platform
```

### 8.2 Integration Files

- `backend/app/utils/oasis_llm.py` — Model creation for OASIS simulation
- `backend/app/services/simulation_runner.py` — Core simulation engine
- `backend/app/services/simulation_manager.py` — Simulation lifecycle
- `backend/app/services/simulation_ipc.py` — File-based IPC

### 8.3 Agent Communication

- **Platform**: Twitter and/or Reddit (simulated social media)
- **IPC**: File-based (`SimulationRunner.RUN_STATE_DIR/{sim_id}/`)
- **Agent actions**: Expressed as OpenAI `tool_calls` format
- **Tool emulation**: When CLI providers lack native function calling, text is parsed back as tool calls (`_parse_tool_call_text`)

### 8.4 Concurrency Controls

- CLI semaphore: `OASIS_CLI_SEMAPHORE=8` (default)
- OpenAI semaphore: `OASIS_SEMAPHORE=30` (default)
- Per-platform division: `cap // platforms`
- Boost: `LLM_BOOST_API_KEY` / `LLM_BOOST_BASE_URL` for accelerated twin

### 8.5 Failure Modes

- Empty assistant content → 400 BadRequestError cascade (mitigated by `_sanitize_messages`)
- Content-filter 422 → LLMClient fallback chain
- Agent returns no tool_calls → "hollow" round (recorded in run_summary)
- Simulation process dies → `check_env_alive()` returns false → interview rejected

---

## 9. Backend API Layer (Flask)

### 9.1 API Blueprint Routes

| Blueprint | Routes | Purpose |
|-----------|--------|---------|
| `research_bp` | `/api/research/run`, `/<id>/cancel`, `/<id>/resume`, `/<id>/delete`, `/status/<id>`, `/list`, `/<id>/dossier`, `/<id>/progress` | Unified pipeline lifecycle |
| `simulation_bp` | `/api/simulation/entities/<graph_id>`, `/create`, `/status/<id>`, `/run/<id>` | OASIS simulation management |
| `graph_bp` | `/api/graph/project/<id>`, `/ontology/generate`, `/build`, `/<id>/reset` | Knowledge graph construction |
| `report_bp` | `/api/report/<id>`, `/<id>/pdf`, `/<id>/charts/<file>`, `/<id>/exec-brief` | Report generation & delivery |
| `settings_bp` | `/api/settings/llm` (GET/POST), `/api/settings/llm/test` | Provider configuration |
| `sdk_bp` | `/api/v1/run`, `/api/v1/status/<id>`, `/api/v1/list`, `/api/v1/dossier/<id>`, `/api/v1/forecast/<id>`, `/api/v1/resolve/<id>` | Stable programmatic API |

### 9.2 Protocol Details

- **HTTP**: Flask dev server or production WSGI
- **Auth**: `X-API-Token` header (constant-time comparison), `APP_API_TOKEN` config
- **CORS**: Configurable via `APP_CORS_ORIGINS` (default: localhost ports)
- **Rate limiting**: None built-in at API level (relies on LLM/model lease system)

### 9.3 Request/Response Format

```json
// Success
{"success": true, "data": {...}}

// Error
{"success": false, "error": "Human-readable message"}
```

### 9.4 SSRF Protections

- `APP_BLOCK_PRIVATE_URLS` — Reject private/loopback URLs for outbound requests
- `validate_safe_url()` in `backend/app/utils/security.py`
- LLM test endpoint rejects base_url pointing to cloud metadata/link-local

---

## 10. Frontend Integration

### 10.1 Technology Stack

- **Framework**: Vue.js 3 (Composition API, `<script setup>`)
- **HTTP client**: `axios` with interceptors
- **Router**: Vue Router (page-based SPA)
- **Build**: Vite with dev proxy (`/api` → backend)

### 10.2 API Client (`frontend/src/api/index.js`)

```javascript
const service = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/',
  timeout: 300000, // 5 minutes
});
```

- **Retry**: `requestWithRetry(fn, maxRetries=3, delay=1000)` with exponential backoff
- **Error handling**: Interceptor extracts `error` field from response envelope
- **File downloads**: `apiUrl(path)` helper for same-origin paths

### 10.3 Views

Key views (from `frontend/src/views/`):
- **ResearchView** — Pipeline execution, live log streaming, ETA/heartbeat/spend
- **GraphView** — Knowledge graph visualization
- **SimulationView** — Simulation console, agent actions in real time
- **ReportView** — Report display, charts, PDF export

### 10.4 Polling Pattern (No WebSockets)

```
Frontend polls /api/research/<id>/status every N seconds
    → Gets {status, progress, stages, llm_telemetry}
    → Updates UI progress bars

Live log: /api/research/<id>/progress (bounded tail / full snapshot)
```

---

## 11. Database & Storage

### 11.1 SQLite Ledgers

| Purpose | Path | Tables |
|---------|------|--------|
| Research budget | `RESEARCH_BUDGET_DB` env var | `counters`, `negative_results`, `positive_results`, `global_request_claims`, `fetched_sources`, `provider_health`, `model_leases`, `subagent_leases`, `metadata` |
| LLM cache | In-memory (`LLMCache._store`) | SHA256-keyed, LRU, 2048 entries |
| Embedding cache | `embed_cache.sqlite` | Per (model, text) embedding |

### 11.2 File-Based Storage

| Purpose | Location | Format |
|---------|----------|--------|
| Pipeline state | `backend/uploads/` | `pipeline_state.json`, `state.json` |
| Simulation runs | `OASIS_SIMULATION_DATA_DIR/{sim_id}/` | JSON/CSV files |
| Graph data | `GRAPHITI_DATA_DIR/` | FalkorDB data files |
| Research handoff | Per-pipeline directory | `research_report.md`, `actors.json`, `sources.json`, `timeline.json`, `meta.json` |
| Market data | `handoff/market_price_history.json` | JSON |
| Telemetry | `run_telemetry.json` | JSON |

### 11.3 PostgreSQL / Redis

**None configured by default.** The system uses:
- SQLite for budget ledgers
- Embedded `falkordblite` (RocksDB-based) for graph storage
- File system for all other state

External FalkorDB can be configured via `FALKORDB_HOST`/`FALKORDB_PORT`.

### 11.4 Actors System (`backend/app/utils/actors.py`)

The `actors.json` structure is the central data contract:
- `actors[]` — Named entities with type, role, stance, influence, simulation_tier
- `relationships[]` — Directed edges with type (28 types), valence, polarity, strength
- `intelligence{}` — Per-actor evidence across 17 dimensions (actor-intelligence/v1)
- `forecast_inputs{}` — Base rates, drivers, indicators, scenarios
- `quantitative_facts[]` — Metric/value/unit/as_of_date tuples
- `contested_claims[]` — Claims with positions and evidence status
- `sources[]` — S1-S4 tiered references with independence flags

---

## 12. Cross-Process Communication

### 12.1 Subprocess Architecture

| Component | Launch Method | Communication |
|-----------|--------------|---------------|
| **DeerFlow research** | `subprocess.Popen("python deerflow_research.py")` | `research_progress.log` (tail), file-based handoff |
| **OASIS simulation** | `SimulationRunner` as detached child | File-based IPC (`SimulationIPCClient`) |
| **MCP servers** | `subprocess.Popen("python -m app.mcp.*")` | stdio JSON-RPC |
| **Resolution monitor** | Background cron (`scripts/resolution_monitor.py`) | File-based (`price_track.jsonl`, `resolutions.jsonl`) |
| **Graph build** | `GraphBuilderService` in-process | In-process function calls |

### 12.2 File-Based IPC Details

- **Simulation IPC**: `SimulationIPCClient` reads/writes JSON files in simulation directory
- **Watchdog**: SIGKILLs research subprocess groups at depth budget
- **Heartbeat**: Model leases renew every `ttl/3` seconds via SQLite UPDATE
- **Progress streaming**: `research_progress.log` is append-only, tail-able

### 12.3 Single-Flight / Deduplication

- **Query cache**: `_QUERY_CACHE` (OrderedDict, max 128 entries) + `_QUERY_INFLIGHT` (threading.Event-based)
- **Claims**: `global_request_claims` table in SQLite for cross-process dedup
- **Wait**: `RESEARCH_INFLIGHT_WAIT_SECONDS=45s` default, exponential backoff poll

---

## 13. Budget, Rate Limiting & Circuit Breakers

### 13.1 Research Budget (`research_budget.py`)

| Counter | Global Default | Lane Default | Purpose |
|---------|---------------|--------------|---------|
| `attempts` | 1800 | — | Total tool calls per run |
| `search_network` | 900 | 360 | Web search calls |
| `fetch_network` | 450 | 180 | Page fetch calls |
| `model_leases` | 12 | — | Concurrent model calls |
| `subagent_leases` | 9 | — | Concurrent subagents |

### 13.2 Provider Circuit Breakers

- **Transport failure threshold**: 5 consecutive failures → circuit open for 120s
- **Probe lease**: 30s for exactly one caller to test recovery
- **Content-filter (422)**: 5 consecutive → 300s cooldown
- **Quota (429)**: 8 consecutive → 120s cooldown
- **Provider health table**: `provider_health` with `consecutive_transport_failures`, `opened_at`, `open_until`, `probe_until`

### 13.3 Model Concurrency

- **Global cap**: 12 concurrent model calls (`RESEARCH_MODEL_CONCURRENCY_GLOBAL`)
- **Lease weight**: 1 (default) or `1 + max_concurrent_subagents` for lead streams
- **Heartbeat**: Every `ttl/3` seconds, auto-cleanup of expired leases
- **Wait**: Up to 10800s (`RESEARCH_MODEL_LEASE_WAIT_SECONDS`), poll with `0.1 * 1.7^n` backoff

---

## 14. Telemetry & Observability

### 14.1 LLM Meter (`telemetry.py`)

- **Run context**: `contextvars.ContextVar` for `llm_run_id` and `llm_stage`
- **Active run registry**: Thread-safe dict for single-active-run fallback attribution
- **Per-run tracking**: `by_stage`, `by_model`, `by_provider` with token/latency/cost
- **Cost model**: Per-provider $/1K token table, env-overridable via `LLM_COST_PER_MTOK`
- **Budget guard**: `check_budget()` raises `BudgetExceeded` after each LLM call
- **Telemetry export**: `write_run_telemetry()` atomically writes `run_telemetry.json`

### 14.2 Telemetry Data Flow

```
LLM call → LLMMeter.record(provider, model, tokens, latency, run_id, stage)
  → Stored in process-wide _runs dict
  → On pipeline end: write_run_telemetry(path, run_id)
    → Merges with previous attempts (cumulative tracking)
    → Includes: total, by_stage, by_model, fallback_attributed, unattributed_process
```

### 14.3 Observability Gaps

- **No distributed tracing**: No OpenTelemetry/Jaeger integration
- **No metrics server**: No Prometheus endpoint
- **No log aggregation**: No ELK/Splunk/Loki integration
- **No alerting**: No PagerDuty/Slack/email alert integration
- **No dashboard**: No Grafana/observable dashboard

---

## 15. Security & SSRF Protections

### 15.1 Implemented Protections

| Mechanism | File | Purpose |
|-----------|------|---------|
| `APP_BLOCK_PRIVATE_URLS` | `config.py` | Block private/loopback outbound URLs |
| `validate_safe_url()` | `backend/app/utils/security.py` | URL validation for LLM test endpoint |
| Content sanitization | `deerflow_research.py` | Strip instruction-like controls from evidence |
| `_UNSAFE_EVIDENCE_CONTROL_PATTERNS` | `deerflow_research.py` | Regex patterns for prompt injection detection |
| Direct fetch guard | `cached_fetch.py` | Reject non-public URLs (IP check) |
| `APP_API_TOKEN` | `config.py` | API token gate for `/api/*` mutation endpoints |
| `LLM_CLI_USE_API_KEY` | `llm_client.py` | Explicit opt-in to use API keys with CLI |

### 15.2 Gaps for Live Trading

- **No API key rotation** mechanism
- **No request signing** for write operations
- **No wallet authentication** for Polymarket CLOB
- **No encryption at rest** for sensitive data
- **No audit trail** for configuration changes
- **No rate limiting** at API gateway level

---

## 16. What Needs to Change for Live Trading

### 16.1 Real-Time Data Feeds (MISSING)

| Requirement | Current State | Needed for Trading |
|-------------|--------------|-------------------|
| **Market data** | Polymarket keyless REST (poll-based) | WebSocket subscriptions to exchanges (Binance, Coinbase, etc.) |
| **Order book** | None | L2/L3 order book streams via WebSocket |
| **Trade execution** | None (read-only Polymarket) | Signed order submission via CLOB API |
| **Portfolio** | None | Position/account endpoints with wallet signing |
| **Tick data** | None | Per-tick price/volume via WebSocket |

### 16.2 Protocol Changes Required

1. **Replace polling with WebSocket/SSE**:
   - Frontend: Replace `axios` polling with `WebSocket` or `EventSource`
   - Backend: Add WebSocket endpoint in Flask (or migrate to FastAPI)
   - Research: Replace `research_progress.log` tail with SSE stream

2. **Add exchange API integrations**:
   ```
   Binance WebSocket → Market data → Signal generator → Exchange API → Order execution
   ```
   - Need: `ccxt` library or exchange-specific SDKs
   - Auth: API keys + signature verification
   - Protocol: REST for orders, WebSocket for streaming

3. **Add wallet/identity layer**:
   - EIP-712 message signing for Polymarket CLOB
   - Wallet management (private key storage, nonces)
   - Position tracking and PnL calculation

4. **Add risk management**:
   - Position sizing / max exposure limits
   - Stop-loss / take-profit automation
   - Drawdown circuit breakers
   - Margin monitoring

5. **Add compliance/audit**:
   - Trade logging with immutable storage
   - KYC/AML checks
   - Regulatory reporting
   - Transaction reconciliation

6. **Add alerting/monitoring**:
   - Real-time PnL dashboard
   - Alert on threshold breaches (Slack/email/Telegram)
   - Latency monitoring for order execution
   - System health checks with uptime tracking

7. **Infrastructure changes**:
   - **Replace SQLite** with a proper time-series database (InfluxDB, TimescaleDB) for market data
   - **Add message queue** (Redis Pub/Sub, RabbitMQ, Kafka) for event-driven architecture
   - **Add cache layer** (Redis) for hot market data
   - **Migrate from Flask** to FastAPI for native WebSocket support
   - **Add GPU/low-latency** compute for signal generation

### 16.3 Specific Code Changes

```python
# Current: poll-based research progress
GET /api/research/<id>/progress  → tail of research_progress.log

# Needed: SSE stream
GET /api/research/<id>/stream   → EventSource with real-time stages

# Current: file-based simulation IPC
SimulationIPCClient.check_env_alive() → reads files

# Needed: WebSocket-based simulation
ws.connect("/ws/simulation/<id>") → real-time agent actions

# Current: REST-only Polymarket
PolymarketClient.search_events() → HTTP GET

# Needed: WebSocket subscription
polymarket.ws.subscribe("markets", callback) → real-time price updates

# Current: subprocess-based research
subprocess.Popen(["python", "deerflow_research.py"])

# Needed: In-process or gRPC-based research engine
research_engine.run(prompt) → AsyncGenerator(stages)
```

### 16.4 Data Flow for Live Trading System

```
WebSocket Market Feed
    │
    ▼
Signal Engine (Python) ──→ Feature Store (Redis)
    │                         │
    │                         ▼
    ▼                  Model Serving (TensorRT/ONNX)
Order Manager          │
    │                  ▼
    ▼            Risk Manager
Exchange API ◄─────── Position Tracker
    │                  │
    ▼                  ▼
Fill Reports    Alert System (Slack/Telegram)
    │
    ▼
Audit Ledger (PostgreSQL/TimescaleDB)
    │
    ▼
Dashboard (React/Vue + WebSocket)
```

### 16.5 Summary of Critical Gaps

1. **No real-time data infrastructure** — everything is poll/file-based
2. **No write-capable exchange API** — Polymarket is read-only
3. **No WebSocket support** in the backend or frontend
4. **No message queue** for event-driven architecture
5. **No risk management** system
6. **No alerting** infrastructure
7. **No time-series database** for market data
8. **No wallet/crypto identity** layer
9. **No compliance/audit** trail
10. **No monitoring dashboard** for live operations

---

## Appendix: Complete Config Key Inventory

Key configuration categories from `.env.example`:

- **LLM**: `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME`, `LLM_FALLBACK_*`, `LLM_TIERED_ROUTING`, `LLM_FAST_MODEL`, `LLM_CB_*`
- **Research**: `DEERFLOW_RESEARCH_DEPTH`, `RESEARCH_BUDGET_*`, `RESEARCH_SEARCH_CACHE_*`, `RESEARCH_SOURCE_CACHE_*`
- **Search**: `SERPER_API_KEY`, `TAVILY_API_KEY`, `FIRECRAWL_API_KEY`, `FIRECRAWL_SEARCH_API_URL`
- **Markets**: `PREDICTION_MARKETS_ENABLED`, `PREDICTION_MARKETS_MIN_VOLUME`, `PREDICTION_MARKETS_MAX`
- **Graph**: `GRAPH_BACKEND`, `GRAPHITI_DATA_DIR`, `FALKORDB_HOST`, `FALKORDB_PORT`, `ZEP_API_KEY`
- **Simulation**: `OASIS_SIMULATION_DATA_DIR`, `SIM_SEED`, `N_FORECAST_SEEDS`, `OASIS_CLI_SEMAPHORE`
- **Report**: `REPORT_STRUCTURED_FORECAST`, `REPORT_VISUALIZER`, `REPORT_PDF_EXPORT`, `REPORT_EXEC_BRIEF`
- **Security**: `APP_API_TOKEN`, `APP_CORS_ORIGINS`, `APP_BLOCK_PRIVATE_URLS`
- **Telemetry**: `LLM_TELEMETRY_ENABLED`, `LLM_CACHE_ENABLED`, `LLM_RUN_BUDGET_TOKENS`, `LLM_RUN_BUDGET_USD`
- **Resolution Monitor**: `RESOLUTION_MONITOR_RECENT_N`, `RESOLUTION_MONITOR_LOOKBACK_DAYS`, `RESOLUTION_MONITOR_DRIFT_THRESHOLD`, `RESOLUTION_MONITOR_AUTORUN_HOURS`

---

*This document was generated by analyzing the complete codebase at `/Users/rogerlin/Downloads/DeepResearchForecast`. All findings are based on source code inspection.*
