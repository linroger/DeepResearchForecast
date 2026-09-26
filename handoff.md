# Handoff.md — DeepResearchForecast Analysis Suite

**Last Updated (UTC):** 2026-09-27T05:00:00Z
**Status:** Complete — All analyses delivered and verified
**Current Focus:** Critical verification finding: per-graph asyncio.Lock is the ACTUAL bottleneck (not thread pool size)

## 1) Request & Context
- **Original request:** Analyze DeepResearchForecast codebase to identify ALL performance bottlenecks for high-throughput event-based AI quant trading system
- **Secondary request:** Map ALL external integrations, data flow boundaries, MCP servers, and cross-system communication patterns relevant to building an event-based AI quant trading system
- **Operational constraints:** Reference run `pipe_f23527f7d903` took 13h57m with GRAPH occupying 8h37m (62%), ~150M tokens per run
- **Guidelines:** Quantitative analysis with exact metrics, file/line references, estimated savings, risk/trade-off assessment
- **Scope boundaries:** Analysis documents only (no code changes unless requested). Covers 6-stage pipeline: RESEARCH → ONTOLOGY → GRAPH → PREPARE → RUN → REPORT

## 2) Requirements → Acceptance Checks
| Requirement | Acceptance Check | Expected Outcome | Evidence |
|---|---|---|---|
| R1-R11: Performance bottlenecks | Extract from source files | 11 bottleneck categories with metrics | `PERFORMANCE_BOTTLENECKS.md` §3-11 |
| R12-R30: External integrations map | Read all 8 integration areas (DeerFlow, MCP, API, LLM, Frontend, DB, Config, Security) | Complete integration map with protocols, auth, failure modes | `EXTERNAL_INTEGRATIONS_MAP.md` §1-16 |
| Live trading gap analysis | Identify all missing components | 10 critical gaps documented | `EXTERNAL_INTEGRATIONS_MAP.md` §16 |

## 3) Plan & Decomposition
- **Approach:** Exhaustive source code reading across all integration boundaries, compile comprehensive mapping documents
- **Deliverables:** 
  - `PERFORMANCE_BOTTLENECKS.md` — 11 bottleneck categories with quantitative metrics
  - `EXTERNAL_INTEGRATIONS_MAP.md` — 16 sections covering all external systems, protocols, and live trading gaps

## 4) To-Do & Progress Ledger
- [x] Read all performance source files (telemetry.py, llm_client.py, graph_builder.py, runtime.py, pipeline_orchestrator.py, etc.)
- [x] Extract token/time distribution data → PERFORMANCE_BOTTLENECKS.md
- [x] Read all integration source files (deerflow_bridge, MCP servers, API layer, LLM infra, frontend, DB, config)
- [x] Search for WebSocket/SSE, Polymarket, Firecrawl, Graphiti/FalkorDB, Zep references across entire codebase
- [x] Produce EXTERNAL_INTEGRATIONS_MAP.md (16 sections)
- [x] Identify 10 critical gaps for live trading
- [x] Update handoff.md

## 5) Findings, Decisions, Assumptions
### Performance Analysis Key Findings
- **GRAPH stage is 62% of pipeline time** (8h37m/14h). Largest optimization: fixing per-graph asyncio.Lock serialization that defeats `GRAPH_BUILD_CONCURRENCY=4`
- **Metering blind spots (FOG-TEL-1)** mean ~unknown fraction of 150M tokens are unaccounted for
- **Provider outage grind**: 231 errors/min × 26h during outages

### External Integrations Key Findings
- **System is completely poll-based** — no WebSockets, no SSE, no streaming anywhere
- **Polymarket integration is keyless read-only** — no write/order execution capability
- **9 LLM providers** supported via dual CLI + SDK paths
- **4 search providers** (Serper, Tavily, Firecrawl, DDG) selected dynamically by env key availability
- **4 fetch providers** with graceful fallback chain (Firecrawl → Jina → Exa → Direct HTTP)
- **SQLite** for budget ledgers, **embedded falkordblite** for graph storage, **file system** for everything else
- **2 stdio MCP servers** (kg_server, sim_server) lazily initialized, never hang the protocol
- **10 critical gaps** for live trading: no real-time data, no write exchange API, no WebSocket, no message queue, no risk management, no alerting, no time-series DB, no wallet layer, no compliance/audit, no monitoring dashboard

## 6) Issues, Mistakes, Recoveries
- **Performance analysis**: Initial handoff.md was a project template. All data extracted from source code comments, config, and forensic audit references.
- **Integration mapping**: System architecture is heavily file-based with no streaming infrastructure — major refactor needed for live trading.

## 7) Scenario-Focused Resolution Tests
- **Graph stage 8h37m → target 2-3h:** Per-graph `asyncio.Lock` at `runtime.py` lines 493, 1123 is the ACTUAL bottleneck (verified). The 64-worker pool (`GRAPH_LLM_EXECUTOR_WORKERS=64`) is confirmed wired but doesn't help without relaxing the lock. Fix: entity-level locking or accept single-graph serialization + parallelize multiple graphs.
- **GRAPH_LLM_EXECUTOR_WORKERS=64 verification:** VERIFIED wired through (`llm_adapter.py` lines 59-78, 150; `config.py` line 1192; `contextvars.copy_context()` at lines 168-171). Pool provides headroom but per-graph lock serializes all episodes on the same graph.
- **Provider outage 26h → <10min:** Implement `LLM_OUTAGE_HALT_CONSECUTIVE=10` circuit breaker + `_cb_tripped` fast-fail
- **Report rework 8/13 → <1:** Enable `PIPELINE_HEALTH_GATE=true` + `REPORT_FORECAST_SPINE_FIRST=true` + `REPORT_PUBLISH_GATE=true`
- **Live trading → production:** Requires full infrastructure rebuild: WebSocket/SSE, exchange API, wallet layer, risk management, message queue, time-series DB

## 8) Verification Summary
- **Performance files read:** 17+ source files, ~15,000+ lines
- **Integration files read:** 30+ source files across 8 areas
- **Performance bottlenecks:** 11 major categories, 50+ quantitative data points
- **Integration sections:** 16 comprehensive sections covering all external boundaries
- **Live trading gaps:** 10 critical gaps with specific remediation paths
- **GRAPH_LLM_EXECUTOR_WORKERS=64:** VERIFIED wired through (`llm_adapter.py` lines 59-78, 150; `config.py` line 1192; `runtime.py` line 396). NOT the bottleneck — the per-graph `asyncio.Lock` at `runtime.py` lines 493, 1123 is.
- **Per-graph asyncio.Lock:** Confirmed as the single largest concurrency limiter. `add_episodes_concurrent` holds the lock across the entire fan-out. Code explicitly warns to keep `GRAPH_BUILD_CONCURRENCY=1` unless duplicates acceptable (line 1087-1088).

## 9) Remaining Work & Next Steps
### Immediate (code changes)
- [VERIFIED] `GRAPH_LLM_EXECUTOR_WORKERS=64` is confirmed wired through to graphiti runtime (`llm_adapter.py` lines 59-78, 150; `config.py` line 1192; `contextvars.copy_context()` at lines 168-171). The pool provides headroom but does NOT solve the bottleneck.
- [KEY FINDING] The per-graph `asyncio.Lock` at `runtime.py` lines 493 and 1123 is the ACTUAL remaining bottleneck — it serializes all episodes on the same graph regardless of thread pool size. `add_episodes_concurrent` holds the lock across the entire `asyncio.gather` fan-out.
- Relax the per-graph lock to allow concurrent writes for non-conflicting entity names, or implement fine-grained locking at the entity-name level instead of the graph level
- Implement cross-process LLM caching (disk-based) for recurring event patterns
- Replace SQLite budget ledger with Redis for high-concurrency scenarios
- Implement pipeline pipelining (overlap RESEARCH→ONTOLOGY→GRAPH stages)
- Add warm-started graph pre-computation for recurring entities

### For Live Trading (major infrastructure)
1. **Phase 1**: Add WebSocket/SSE infrastructure (Flask → FastAPI migration or Flask-SocketIO)
2. **Phase 2**: Add exchange API integrations (ccxt library) with signed order submission
3. **Phase 3**: Add wallet/identity layer (EIP-712 signing for Polymarket CLOB)
4. **Phase 4**: Add risk management (position sizing, stop-loss, drawdown circuit breakers)
5. **Phase 5**: Add alerting/monitoring (Slack/email/Telegram, real-time PnL dashboard)
6. **Phase 6**: Replace SQLite with time-series DB (InfluxDB/TimescaleDB), add message queue (Redis/Kafka)

## 10) Deliverables Summary
| Document | Path | Sections | Status |
|---|---|---|---|
| Performance Bottlenecks | `PERFORMANCE_BOTTLENECKS.md` | 11 areas | Complete |
| External Integrations Map | `EXTERNAL_INTEGRATIONS_MAP.md` | 16 sections | Complete |

## 11) Updates to This File
- 2026-09-27: Updated — Added external integrations mapping analysis (EXTERNAL_INTEGRATIONS_MAP.md, 16 sections, 10 critical live trading gaps)
- 2026-09-27: Created — Exhaustive performance analysis of DeepResearchForecast codebase. All 11 requirement areas addressed with quantitative metrics.
- 2026-09-27: Verified — `GRAPH_LLM_EXECUTOR_WORKERS=64` confirmed wired through (`llm_adapter.py` lines 59-78, 150; `config.py` line 1192; `contextvars.copy_context()` at lines 168-171). Per-graph `asyncio.Lock` at `runtime.py` lines 493, 1123 confirmed as the ACTUAL remaining bottleneck. Updated `PERFORMANCE_BOTTLENECKS.md` Root Cause #1 and section 12c with verified findings.
