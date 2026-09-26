# Ling-Fin-Event-Trading-System — Enhancement & Optimization Proposal

> **Date:** 2026-09-27  
> **Status:** Analysis Complete — Ready for Implementation Planning  
> **Scope:** DeepResearchForecast (DeepAgentForecast / MiroFish) codebase transformation into an event-based AI quant trading system  
> **Methodology:** 5 parallel agent teams mapped architecture, event patterns, performance, simulation models, and external integrations  

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Architecture Map](#2-current-architecture-map)
3. [What Already Works as a Trading System](#3-what-already-works-as-a-trading-system)
4. [Gap Analysis: Current State → Production Trading](#4-gap-analysis)
5. [Proposed Enhancements — Layer by Layer](#5-proposed-enhancements)
6. [Performance Optimization Targets](#6-performance-optimization-targets)
7. [Event-Driven Architecture Upgrades](#7-event-driven-architecture-upgrades)
8. [Quant Trading Model Additions](#8-quant-trading-model-additions)
9. [Data & Integration Enhancements](#9-data--integration-enhancements)
10. [Risk Management & Compliance Layer](#10-risk-management--compliance-layer)
11. [Implementation Roadmap](#11-implementation-roadmap)
12. [Success Metrics & Validation](#12-success-metrics--validation)

---

## 1. Executive Summary

DeepResearchForecast is fundamentally an **event-based AI prediction engine**. It takes a natural-language question, researches it across multiple angles, builds a temporal knowledge graph of real-world actors, simulates those actors on social platforms, and produces probabilistic forecasts with Polymarket calibration anchors. The system already implements many components that map directly to quantitative trading infrastructure:

- **Binary forecast generation** = digital options pricing
- **Scenario probability derivation** = multi-scenario risk modeling
- **Brier score backtesting** = model calibration verification
- **Polymarket integration** = market data feed + calibration
- **Ensemble extremized log-odds pooling** = multi-strategy portfolio aggregation
- **WorldState with EWMA convergence** = stochastic price model
- **Decision Channel** = multi-agent market microstructure
- **SHA-256 sealed provenance chain** = regulatory audit trail

**The core insight:** The system is a quantitative *research* platform that needs an *execution bridge* to become a trading system. The analytical infrastructure (calibration, backtesting, ensemble methods, uncertainty quantification, market anchoring, data integrity) is production-grade. What's missing is the execution layer: order management, position sizing, risk limits, real-time market connectivity, and the feedback loop from trading outcomes back into model calibration.

**Key metrics from the reference run (`pipe_f23527f7d903`):**
- Total wall-clock: **13h 57m**
- Total tokens: **~150M** (true lower bound ~83M main run)
- GRAPH stage: **8h 37m** (62% of total) — the #1 optimization target
- RESEARCH stage: **~2h 38m** (18%)
- Report rework rate: **8/13 runs** produced placeholder content
- Per-run cost: **~$26+** in LLM tokens

---

## 2. Current Architecture Map

### 2.1 System Topology

The system runs as a **Flask web application** orchestrating multiple long-running subprocesses:

| Process | Role | Launch | Communication |
|---------|------|--------|---------------|
| **Flask backend** | API + orchestrator + all pipeline services | `backend/run.py` → `create_app()`, threaded on `:5001` | HTTP (polled by frontend) |
| **Vite/Vue frontend** | SPA dashboard | `npm run frontend`, port 3000 | HTTP polling (no WebSockets) |
| **DeerFlow research** | Deep research per track | `subprocess.Popen(start_new_session=True)` | stdout line stream + `handoff/` files + SQLite budget ledger |
| **OASIS simulation** | Dual-platform social sim | `subprocess.Popen(start_new_session=True)` | `actions.jsonl` tail + `run_state.json` + file-mailbox IPC |
| **Graphiti runtime** | Local temporal KG | In-process singleton with background asyncio loop | Direct calls behind Zep-shaped facade |
| **MCP servers** | `drf-kg`, `drf-simulation` | `python -m app.mcp.kg_server` | stdio FastMCP |

### 2.2 Pipeline Stages (6-Stage)

```
one prompt → [1 RESEARCH] → [2 ONTOLOGY] → [3 GRAPH] → [4 PREPARE] → [5 RUN] → [6 REPORT] → forecast
              DeerFlow        LLM derives    local KG     personas +     OASIS     ReportAgent
              (subprocess)    entity/edge    ingest +     sim config     dual-     (spine-first,
                             types)         extract      (env agent)      platform  publish-gated)
                    │                │            │            │            │            │
                    └── local Graphiti temporal KG (GraphRAG, embedded FalkorDB) ──┘
```

**Progress bands:** Research 0–30%, Ontology 30–40%, Graph 40–60%, Prepare 60–72%, Run 72–92%, Report 92–100%.

### 2.3 Key Services (~30 modules)

| Category | Services |
|----------|----------|
| **Pipeline** | `pipeline_orchestrator.py` (7,618 lines), `simulation_manager.py`, `simulation_runner.py`, `simulation_ipc.py` |
| **Research** | `research_progress.py`, `deerflow_research.py` (8,905 lines), `search_tools.py`, `market_tools.py`, `research_budget.py` |
| **Graph** | `graph_builder.py`, `graph_pruner.py`, `graphiti_client/` (runtime, client, llm_adapter, compat), `zep_entity_reader.py`, `zep_entity_resolver.py`, `zep_graph_memory_updater.py` |
| **Forecast** | `forecast_extractor.py`, `forecast_ledger.py`, `backtest.py`, `ensemble.py`, `decision_channel.py`, `worldstate.py`, `world_delta.py`, `agent_dynamics.py`, `exec_brief.py`, `requirement_spec.py`, `resolution_autorun.py` |
| **Simulation** | `oasis_profile_generator.py`, `simulation_config_generator.py`, `actor_role_prompt.py`, `actor_context.py` |
| **Report** | `report_agent.py`, `report_lint.py`, `report_visualizer.py` |
| **Infrastructure** | `llm_client.py`, `oasis_llm.py`, `telemetry.py`, `token_budget.py`, `security.py`, `prediction_markets.py`, `atomic.py`, `actors.py`, `dates.py` |

### 2.4 Persistence & Data Stores

| Store | Technology | Purpose |
|-------|-----------|---------|
| Temporal KG | Graphiti + embedded FalkorDB (`falkordblite`) | Bi-temporal knowledge graph with entity/edge/episode model |
| Simulation DBs | SQLite (`<platform>_simulation.db`) | Per-platform action logs, posts, comments |
| Budget Ledger | SQLite (`research_budget.py`) | Cross-process budget enforcement, model leases |
| Forecast Ledger | JSONL (`_forecast_ledger/`) | Trade blotter + settlement ledger + P&L reconciliation |
| Pipeline State | JSON file (`pipeline_state.json`) | Atomic writes with fsync, per-pipeline threading lock |
| Action Logs | JSONL (`actions.jsonl`) | Immutable event stream per platform |
| File-based IPC | Commands/responses in `ipc_commands/` + `ipc_responses/` | Backend ↔ OASIS subprocess communication |

### 2.5 Concurrency Model

- **Flask:** Threaded, no asyncio in the main app
- **Slow jobs:** Daemon threads + in-memory `Task` objects
- **Profile generation:** `ThreadPoolExecutor` (parallelism 16 for HTTP, 3 for CLI)
- **Graphiti async:** Dedicated background asyncio event loop with sync→async bridge
- **OASIS:** Detached subprocesses with their own asyncio loops
- **Graph build:** `GRAPH_BUILD_CONCURRENCY=4`, `GRAPHITI_MAX_COROUTINES=16`, `GRAPH_LLM_EXECUTOR_WORKERS=64`
- **Lock patterns:** Per-graph `asyncio.Lock`, per-pipeline `threading.Lock`, HMAC auth gate, file-based IPC mailboxes

---

## 3. What Already Works as a Trading System

### 3.1 Binary Forecast Engine = Digital Options Pricing

The `forecast_extractor.py` generates independent YES/NO forecasts with:
- `probability` = implied probability (like implied odds in betting markets)
- `resolution_criteria` = settlement conditions (exactly what determines payout)
- `market_anchor` = Polymarket reference price for basis comparison
- `base_rate_anchor` + `adjustment_rationale` = anchor-and-adjust fundamental analysis
- Contrarian framing (~40-50% priced below 0.5) = mean-reversion signal generation

**Trading mapping:** Each binary forecast is a **binary option** (digital call/put) with a defined strike (resolution criteria), implied probability (model fair value), and market reference (Polymarket price).

### 3.2 WorldState = Stochastic Price Model

`worldstate.py` implements:
- **Probability distribution** over scenarios that evolves via resource-weighted commitments
- **EWMA delta tracking** = volatility estimation
- **Inertia parameter** (0.7 default) = mean reversion speed
- **Calendar entropy floor** = prevents distribution lock-in (analogous to prior reversion)
- **Convergence state machine** = regime detection (`converged`/`inconclusive`/`active`)
- **Typed round statuses** = position state tracking

**Trading mapping:** This is a **mean-reverting stochastic process** — exactly like models used in algorithmic trading for pairs trading, mean-reversion strategies, and regime detection.

### 3.3 Decision Channel = Market Microstructure Model

`decision_channel.py` implements:
- **Outcome-power-weighted commitments** (weight = `outcome_power × confidence`) ≠ influence-weight
- **Two-phase elicit → replay** with `ThreadPoolExecutor`
- **Abstention handling** (`ABSTAIN_TOKEN`) = no-position state
- **Convergence detection** with windowed EWMA
- **Calendar-temporal inertia** scaling

**Trading mapping:** Each agent is a **market participant**. `outcome_power` = capital/balance sheet capacity. `influence_weight` = market visibility. The power-weighted commitment = **order sizing based on capital, not visibility**. Abstention = flat position.

### 3.4 Backtesting & Calibration = Model Validation

`backtest.py` implements:
- **Multi-class Brier score** + log-loss
- **Murphy decomposition**: Brier = Reliability − Resolution + Uncertainty (exact analog of Brinson-Fachler portfolio attribution)
- **Jeffreys Beta(0.5,0.5) smoothing** with credible intervals (Bayesian shrinkage)
- **Platt-scaling recalibrator** via gradient descent on log-loss (implied volatility calibration)
- **5-bin hit rate analysis** with calibration error tracking

**Trading mapping:** This is a **complete model risk management system** — the mathematical infrastructure for validating that probability forecasts are honest, calibrated, and actionable.

### 3.5 Ensemble Methods = Multi-Strategy Portfolio

`ensemble.py` implements:
- **Semantic scenario alignment** via Jaccard token overlap (`ENSEMBLE_ALIGN_MIN_OVERLAP=0.34`)
- **Extremizing log-odds pooling** with parameter `a` (conviction scaling)
- **`p_low`/`p_high` confidence intervals** from ensemble stdev
- **TV-distance agreement** with support penalty
- **Low-agreement flags** when `spread > 0.15`

**Trading mapping:** Ensemble aggregation is a **multi-strategy fund** where each model is a trading strategy. The extremizing parameter = conviction-weighted allocation. The spread = divergence signal (volatility expansion). The agreement metric = correlation analysis between strategies.

### 3.6 Polymarket Integration = Market Data Feed

`prediction_markets.py` provides:
- **Keyless Polymarket Gamma API** client with 10s timeout
- **`search_events()`** — full-text search of active markets
- **`snapshot_for_queries()`** — market snapshot with volume filtering (min ≥200)
- **`requote_markets()`** — price delta calculation (research-time vs. current)
- **`fetch_price_history()`** — CLOB historical prices (1h/6h/1d/1w/1m intervals)
- **`fetch_resolutions()`** — MON-1 terminal state queries
- **CLOB token tracking** with `clob_token_ids`, `clob_yes_token_id`
- **Market microstructure data:** `best_bid`, `best_ask`, `volume`, `liquidity`, `oneDayPriceChange`

**Trading mapping:** This is a **complete market data infrastructure** with bid-ask spread, volume, liquidity, daily returns, and historical price series — the raw inputs for any algorithmic trading system.

### 3.7 Resolution Monitoring = Position Settlement

`forecast_ledger.py` + `resolution_autorun.py` provides:
- **Idempotent settlement writes** (`append_market_resolution()`) with `threading.Lock` + `fcntl.flock`
- **Brier score tracking** per market-anchored forecast
- **Due-for-resolution detection** (position expiry alerts)
- **Periodic daemon polling** (`resolution_autorun.py`) with `threading.Event` stop signaling
- **Golden result system** for backtesting against known outcomes
- **Evaluation/production ledger separation** (segregated accounts)

**Trading mapping:** This is a **trade blotter + settlement ledger + P&L reconciliation system** with double-settlement prevention and regulatory separation of concerns.

### 3.8 Source Tiering (S1-S4) = Evidence-Weighted Signal

```python
_TIER_RANK = {"S1": 0, "S2": 1, "S3": 2, "S4": 3}
_TIER_WEIGHT = {"S1": 3.0, "S2": 2.0, "S3": 1.0, "S4": 0.5}
```

**Trading mapping:** S1 = primary exchange data (highest conviction → larger position), S4 = unverified social media (lowest conviction → smaller or no position). The tier weight = **position sizing factor based on data quality**.

### 3.9 Actor Intelligence = Counterparty Risk Profiles

The 17-dimension actor profiles with SHA-256 sealing map to:
- **Counterparty credit profiles** (position, risk tolerance, mandate, constraints)
- **Visibility tiers** = information access levels
- **Evidence gap audit** = due diligence gaps
- **Decision incentives** (`gains_if`/`loses_if`) = payoff structure
- **Canonical sealing** = KYC/AML compliance

---

## 4. Gap Analysis: Current State → Production Trading

| Category | What Exists | Trading-Ready? | Key Gap |
|----------|------------|----------------|---------|
| **Event Architecture** | Action logs, resolution autorun, decision channel, world state | **Partially** | Social actions ≠ trade events; no order execution |
| **Prediction/Forecasting** | Binary forecasts, scenario extraction, calibration, backtesting, ensemble | **Mostly** | Probabilities LLM-derived, not market-derived |
| **Market Integration** | Polymarket client, price history, resolution monitoring | **Partially** | Read-only; no trade execution, no position management |
| **Agent Behavior** | Affective dynamics, decision channel, 17-dimension profiles | **Prototype** | Gated behind `SIM_DECISION_CHANNEL` (default OFF) |
| **Temporal Simulation** | Calendar timeline, round-based sim, bi-temporal KG | **Working** | No market timing, no execution timing |
| **Risk & Uncertainty** | Confidence scoring, scenario analysis, sensitivity, calibration | **Working** | No P&L translation, no risk limits |
| **Data Quality** | SHA-256 sealing, S1-S4 tiering, evidence gap audit | **Production-grade** | Excellent but not connected to trading decisions |
| **Execution Layer** | **NONE** | ❌ | No order management, no position sizing, no risk limits |
| **Market Connectivity** | Polymarket read-only | ❌ | No exchange APIs, no WebSocket market data |
| **Portfolio State** | **NONE** | ❌ | No position tracking, no P&L, no balance management |
| **Alerting/Monitoring** | Basic heartbeat + status | ❌ | No trading alerts, no anomaly detection |

---

## 5. Proposed Enhancements — Layer by Layer

### Layer 1: Event Bus & Execution Infrastructure

**Problem:** The system uses file-based polling (`actions.jsonl` tail every 2s) and has no WebSocket/SSE support. For a trading system, events must propagate in real-time.

**Enhancements:**

1. **Replace polling with WebSocket/SSE**
   - Add a WebSocket layer to Flask (or migrate to FastAPI) for real-time event streaming
   - Replace `setInterval` polling in the frontend with WebSocket subscriptions
   - Event types: `action:created`, `round:ended`, `market:resolved`, `position:updated`, `alert:triggered`

2. **Event Store**
   - Replace ad-hoc `actions.jsonl` with a proper event store
   - Each event: `{event_id, timestamp, type, payload, metadata, source}`
   - Support event sourcing pattern for full audit trail
   - Enable replay for backtesting and debugging

3. **Message Queue**
   - Add Redis or NATS as a message bus between pipeline stages
   - Replace file-based IPC with message queues for simulation ↔ backend communication
   - Enable event-driven triggers: market data update → recalibration → forecast revision

4. **Order Management System (OMS)**
   ```python
   class Order:
       order_id: str
       strategy_id: str
       instrument: str  # ticker, contract, prediction market ID
       side: str        # buy/sell/long/short
       quantity: float
       limit_price: Optional[float]
       stop_price: Optional[float]
       status: str      # pending, filled, partial, cancelled, rejected
       timestamp: datetime
       fill_price: Optional[float]
       pnl: Optional[float]
   ```

### Layer 2: Market Data Integration

**Problem:** Currently only Polymarket (prediction markets) with read-only access. No real-time exchange data, no order book depth.

**Enhancements:**

1. **WebSocket Market Data Feed**
   - Connect to exchange WebSocket APIs (Coinbase, Binance, or Polymarket CLOB WebSocket)
   - Real-time OHLCV, order book depth, trade ticks
   - Normalize all feeds to a common schema

2. **Market Data Adapter**
   ```python
   class MarketDataAdapter:
       """Unified interface for all market data sources."""
       def subscribe(self, instrument: str, channels: list[str]) -> Subscription
       def get_order_book(self, instrument: str, depth: int) -> OrderBook
       def get_trades(self, instrument: str, since: datetime) -> list[Trade]
       def get_candles(self, instrument: str, timeframe: str) -> list[Candle]
   ```

3. **Historical Data Pipeline**
   - Store historical data in a time-series database (QuestDB, TimescaleDB, or InfluxDB)
   - Enable backtesting against real historical data
   - Support feature engineering (moving averages, RSI, MACD, Bollinger Bands)

4. **Prediction Market → Exchange Bridge**
   - Use Polymarket probabilities as a signal source for traditional markets
   - Map prediction market events to tradeable instruments
   - Example: "Will the Fed cut rates by June?" → trade SOFR futures or 2-year Treasury notes

### Layer 3: Position Management & Portfolio State

**Problem:** The system has no concept of positions, balances, or P&L. `WorldState` tracks scenario probabilities but not financial state.

**Enhancements:**

1. **Portfolio State Machine**
   ```python
   class Portfolio:
       cash: float
       positions: dict[instrument, Position]
       unrealized_pnl: float
       realized_pnl: float
       margin_used: float
       margin_available: float
       risk_metrics: RiskMetrics  # VaR, Sharpe, max_drawdown
   
   class Position:
       instrument: str
       side: str
       quantity: float
       entry_price: float
       current_price: float
       unrealized_pnl: float
       stop_loss: Optional[float]
       take_profit: Optional[float]
   ```

2. **Position Sizing Engine**
   - Kelly Criterion sizing based on forecast probability and edge
   - Volatility-adjusted sizing (lower vol → larger position)
   - Portfolio concentration limits (max % per instrument, max % per strategy)
   - Correlation-aware sizing (reduce exposure when strategies are correlated)

3. **P&L Ledger**
   - Extend `forecast_ledger.py` to track trade-level P&L
   - Realized P&L per trade, per strategy, per day
   - Drawdown tracking and recovery metrics
   - Tax-lot accounting support

### Layer 4: Execution Engine

**Problem:** The system generates forecasts but has no mechanism to execute trades based on them. The Decision Channel elicits agent commitments but doesn't translate them to orders.

**Enhancements:**

1. **Strategy-to-Order Translation**
   ```python
   class Strategy:
       """Maps a forecast signal to trading orders."""
       def generate_signal(self, forecast: BinaryForecast) -> Signal
       def size_position(self, signal: Signal, portfolio: Portfolio) -> Order
       def manage_risk(self, position: Position, market: MarketData) -> Optional[Order]
   
   class Signal:
       instrument: str
       direction: str          # long/short/flat
       conviction: float       # 0.0-1.0 (derived from probability divergence)
       horizon: timedelta      # time to resolution
       edge: float             # model_prob - market_prob
       rationale: str
   ```

2. **Execution Algorithms**
   - **VWAP/TWAP** for large orders to minimize market impact
   - **Spread-aware execution** — use `best_bid`/`best_ask` from Polymarket to determine timing
   - **Liquidity-sensitive sizing** — smaller orders in thin markets
   - **Slippage model** — estimate execution cost based on order size vs. volume

3. **Order Router**
   - Connect to exchange APIs (REST for orders, WebSocket for status)
   - Support multiple venues (Polymarket for prediction markets, exchanges for crypto/equities)
   - Order confirmation and reconciliation

### Layer 5: Risk Management Layer

**Problem:** The system has `forecast_ledger.py` with Brier scoring and calibration, but no real-time risk management. No position limits, no stop-loss enforcement, no margin monitoring.

**Enhancements:**

1. **Real-Time Risk Engine**
   ```python
   class RiskEngine:
       def check_position_limits(self, order: Order, portfolio: Portfolio) -> RiskDecision
       def check_margin_requirements(self, portfolio: Portfolio) -> MarginStatus
       def check_concentration_limits(self, portfolio: Portfolio) -> ConcentrationStatus
       def check_correlation_risk(self, portfolio: Portfolio) -> CorrelationRisk
       def calculate_var(self, portfolio: Portfolio, confidence: float) -> float
       def calculate_max_drawdown(self, portfolio: Portfolio) -> float
   ```

2. **Risk Controls**
   - **Position limits:** Max $X per instrument, max Y% of portfolio
   - **Daily loss limit:** Stop trading if daily P&L < -Z%
   - **Margin monitoring:** Auto-liquidate if margin < maintenance requirement
   - **Concentration limits:** Max exposure to correlated instruments
   - **Circuit breaker:** Halt all trading if volatility exceeds threshold

3. **Risk Metrics Dashboard**
   - Real-time VaR, Sharpe ratio, Sortino ratio, max drawdown
   - Per-strategy P&L attribution
   - Risk budget utilization
   - Live margin status

### Layer 6: Feedback Loop — Trading Outcomes → Model Calibration

**Problem:** The system has `forecast_ledger.py` with `calibration_summary()` and `fit_recalibrator()`, but the loop from trading outcomes back to model improvement is not automated.

**Enhancements:**

1. **Automated Calibration Pipeline**
   ```
   Trade executed → Outcome observed → P&L recorded → Forecast accuracy measured 
   → Recalibrator updated → New forecasts adjusted → New trades generated
   ```

2. **Post-Trade Analysis**
   - Compare forecast probability to actual outcome for every trade
   - Update Murphy decomposition components (Reliability, Resolution, Uncertainty)
   - Identify systematic biases (e.g., consistently overconfident on certain event types)
   - Trigger model retraining when calibration drift exceeds threshold

3. **Strategy Selection**
   - Multi-armed bandit approach to strategy selection
   - Allocate more capital to strategies with better recent performance
   - Reduce or disable strategies that are consistently losing

### Layer 7: Real-Time Simulation & Scenario Analysis

**Problem:** The OASIS simulation runs as a detached batch process (30-45 minutes). For a trading system, scenario analysis must be near-instantaneous.

**Enhancements:**

1. **Real-Time Simulation Engine**
   - Convert OASIS from batch to streaming mode
   - Process market events in real-time and update agent beliefs
   - Use `world_delta.py` patterns to generate live market narratives
   - Emit scenario probabilities updated continuously

2. **Event-Driven Agent Updates**
   - When market data arrives, trigger agent belief updates
   - `agent_dynamics.py` mood/energy/opinion state updates on each market event
   - `decision_channel.py` re-elicits commitments when significant news arrives
   - `worldstate.py` steps on each significant market event

3. **Live Scenario Dashboard**
   - Show real-time scenario probabilities updating as market events occur
   - Highlight divergences between model and market
   - Alert when scenario probabilities shift significantly

---

## 6. Performance Optimization Targets

### 6.1 Critical: GRAPH Stage (62% of runtime)

**Current:** 8h 37m for GRAPH stage. Root cause is the **per-graph `asyncio.Lock`** at `runtime.py` lines 493 and 1123 that serializes all episode writes.

**The 64-worker pool (`GRAPH_LLM_EXECUTOR_WORKERS=64`) provides idle headroom** — it's ready but blocked by the lock.

**Fix options (in priority order):**

| Option | Description | Est. Savings | Risk |
|--------|-------------|-------------|------|
| **A: Entity-level locking** | Lock per entity name instead of per graph_id | GRAPH: 8h37m → 2-3h | Low (documented concern) |
| **B: Post-build dedup** | Allow concurrent writes, run `GRAPH_RESOLVE_ENTITIES=true` after | GRAPH: 8h37m → 2-4h | Low |
| **C: Parallel graphs** | Accept serialization, run multiple graphs via `GRAPH_BUILD_CONCURRENCY` | Throughput ×N | Low |
| **D: Cast pre-filter + early exit** | Skip chunks with 0 cast mentions before any LLM call | GRAPH: 8h37m → 6-7h | Minimal |

**Recommended:** Combine A + D — entity-level locking with cast pre-filter early exit. This targets **GRAPH: ~2.5h** (savings: ~6h).

### 6.2 Metering Blind Spots (FOG-TEL-1)

**Problem:** `ThreadPoolExecutor` workers don't inherit `contextvars`. Graph stage shows 0 tokens/0 calls in telemetry despite 100+ minutes of continuous extraction.

**Fix:** Propagate `contextvars.copy_context()` into `ThreadPoolExecutor` tasks at `llm_adapter.py` job submission points.

**Impact:** Enables accurate per-stage token attribution → enables budget enforcement → critical for cost control in production trading.

### 6.3 Research Thread Re-Send Optimization

**Problem:** 78M tokens in RESEARCH stage, dominated by thread re-send. Single agentic turns reach 22M input tokens. No prompt caching.

**Fixes:**
1. **Prompt caching** — `DEERFLOW_CLAUDE_PROMPT_CACHE` tri-state kill-switch already exists; was force-disabled on OAuth path. Re-enable via `_apply_prompt_caching` at `_get_request_payload` choke point (≤4 breakpoints, 5-min TTL). **Verified fix in prior loop.**
2. **Inter-phase compaction** — compress prior notes before passing to next phase (60,000-char cap already exists)
3. **Track topology** — evaluate if 3 parallel tracks are optimal vs. fewer deeper tracks
4. **Lower recursion limits** — for non-deep modes

**Estimated savings:** 30-50M tokens (40-60% reduction in RESEARCH).

### 6.4 Provider Outage Halt

**Problem:** 2026-07-08: 231 errors/minute × 26 hours = 10,584 ERROR lines. No run-level halt mechanism.

**Fix:** `ProviderOutageHalt` (already implemented in prior loop) + `LLM_OUTAGE_HALT_CONSECUTIVE=10` knob.

**Impact:** Prevents 26-hour grinds. Instead of burning $10+ per failed run, abort in <10 minutes. **Already deployed.**

### 6.5 Report Rework Elimination

**Problem:** 8/13 runs showed `status=completed` with placeholder content.

**Fixes:**
1. `REPORT_FORECAST_SPINE_FIRST` — forces prediction spine derivation before chapter writing
2. `REPORT_PUBLISH_GATE_MIN_COVERAGE=0.75` — blocks low-coverage reports
3. `REPORT_PURITY_ESCALATION_MAX=12` — bounds language-purity repair
4. Section concurrency — already default 6 (not 1 as previously assumed)

**Estimated savings:** Eliminate 8/13 wasted runs = ~60% compute savings on report stage.

### 6.6 Graph Chunk Attempt Budget

**Problem:** 60% of 466 chunks burned full retry ladder before being skipped.

**Fix:** Reduce `GRAPH_CHUNK_MAX_ATTEMPTS` from 2 to 1 for non-schema errors; add early-exit for chunks with 0 cast mentions.

**Estimated savings:** ~30-45 minutes in GRAPH stage. **Already implemented in prior loop.**

### 6.7 Polymarket Ledger Contention

**Problem:** SQLite WAL contention under high concurrency causes `OperationalError: database is locked`. Budget enforcement is bypassed (fail-open) during contention.

**Fix:** Increase `busy_timeout` beyond 10000ms, or switch to Redis for the budget ledger.

**Estimated savings:** Prevent 3-hour hangs when model capacity is saturated. **Priority: HIGH for production trading.**

### 6.8 Performance Summary Table

| Bottleneck | Current | After Fix | Savings | Status |
|-----------|---------|-----------|---------|--------|
| GRAPH lock | 8h 37m | ~2.5h | ~6h | 🔴 Needs fix |
| Metering blind spots | N/A | Accurate | Cost control | 🟡 Partially done |
| Research caching | 78M tokens | ~35M tokens | ~43M tokens | 🟡 Fix identified |
| Provider outage | 26h grinds | <10min abort | ~26h | ✅ Deployed |
| Report rework | 8/13 wasted | ~2/13 | ~60% | 🟡 Partial |
| Chart Plotly inline | 4.86MB/charts | 8.4KB/charts | ~48MB/report | ✅ Deployed |
| Polymarket ledger | 3h hangs | Normal | ~3h/run | 🔴 Needs fix |
| Chunk attempts | 2 (60% skip) | 1 + early exit | ~45min | ✅ Deployed |

**Projected total runtime after all fixes:** ~4-5h (down from 14h), with ~50M tokens saved.

---

## 7. Event-Driven Architecture Upgrades

### 7.1 Event Classification for Trading

Map the existing event types to trading events:

| Current Event | Trading Equivalent |
|---------------|-------------------|
| `CREATE_POST` | `LIMIT_ORDER` placed |
| `REPOST` | `ORDER_MODIFIED` |
| `LIKE_POST` | `QUOTE_CONFIRMED` |
| `FOLLOW` | `RELATIONSHIP_ESTABLISHED` |
| `round_end` | `BAR_CLOSE` (candlestick) |
| `simulation_end` | `SESSION_END` |
| `market_resolved` | `CONTRACT_EXPIRY` |
| `decision_channel` | `ORDER_ROUTED` |
| `world_state.step` | `PRICE_UPDATE` |

### 7.2 Event Stream Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│ Market Data │────▶│  Event Bus   │────▶│  Strategies │
│  (WebSocket)│     │  (Redis/NATS)│     │  (agents)   │
└─────────────┘     └──────────────┘     └──────┬──────┘
                                                │
                                                ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   OASIS     │────▶│  Event Store │◀────│  Risk Engine│
│  Simulation │     │  (SQLite)    │     │  (limits)   │
└─────────────┘     └──────────────┘     └──────┬──────┘
                                                │
                                                ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│ Forecast    │────▶│  Execution   │────▶│  Exchange   │
│   Engine    │     │  Manager     │     │  APIs       │
└─────────────┘     └──────────────┘     └─────────────┘
```

### 7.3 Real-Time Triggers

Replace the current 2-second polling interval with event-driven triggers:

1. **Market data event** → trigger agent belief update → re-derive forecast → generate signal → create order
2. **Resolution event** → trigger settlement → update P&L → recalibrate model → adjust strategies
3. **Risk event** → trigger position reduction → create stop order → alert operator
4. **Calendar event** → trigger scenario injection → update world state → adjust probabilities

### 7.4 State Machine for Event Processing

```python
class EventState(Enum):
    RECEIVED = "received"
    PROCESSED = "processed"
    ACTIONED = "actioned"
    SETTLED = "settled"
    ARCHIVED = "archived"

class EventProcessor:
    """Process market events through the pipeline."""
    def on_market_data(self, event: MarketDataEvent) -> list[Action]
    def on_resolution(self, event: ResolutionEvent) -> list[Action]
    def on_risk_trigger(self, event: RiskEvent) -> list[Action]
    def on_calendar_event(self, event: CalendarEvent) -> list[Action]
```

---

## 8. Quant Trading Model Additions

### 8.1 Order Book Simulation

The current simulation models social media posts, not orders. Add an order book layer:

```python
class OrderBook:
    """Limit order book for a simulated market."""
    bids: list[Order]    # sorted by price descending
    asks: list[Order]    # sorted by price ascending
    
    def add_order(self, order: Order) -> FillResult
    def cancel_order(self, order_id: str) -> bool
    def get_spread(self) -> float
    def get_depth(self, level: int) -> float
    def match_orders(self) -> list[Fill]
```

**Integration:** Agent decisions from `decision_channel.py` generate orders instead of posts. The order book processes them, generates fills, and updates the `WorldState`.

### 8.2 Market Microstructure Features

Add these to the existing `prediction_markets.py` integration:

1. **Implied volatility surface** — from Polymarket prices across different expirations
2. **Volume-weighted mid-price** — for better execution pricing
3. **Order flow toxicity** — detect informed vs. uninformed order flow
4. **Adverse selection model** — estimate probability of trading against informed agents
5. **Market impact model** — estimate price impact of a given order size

### 8.3 Multi-Asset Support

Currently tied to Polymarket prediction markets. Add:

1. **Instrument abstraction layer**
   ```python
   class Instrument:
       id: str
       type: str          # "prediction_market", "crypto_pair", "equity", "futures", "option"
       ticker: str
       exchange: str
       contract_spec: ContractSpec
       data_feed: DataFeed
       order_router: OrderRouter
   ```

2. **Cross-asset correlation** — use the existing graph structure to model correlations between events and instruments
3. **Portfolio-level optimization** — mean-variance optimization or risk-parity across strategies

### 8.4 Execution Algorithms

Replace the current "fire-and-forget" approach with proper execution:

| Algorithm | When to Use | Description |
|-----------|------------|-------------|
| **Immediate-or-cancel** | High conviction, liquid markets | Fill immediately or cancel |
| **VWAP** | Large orders, liquid markets | Spread over time to match volume profile |
| **TWAP** | Large orders, thin markets | Evenly spread over time |
| **Iceberg** | Large orders, hidden intent | Show only a fraction of total size |
| **Stop-loss** | Risk management | Auto-sell when price drops below threshold |
| **Take-profit** | Profit management | Auto-sell when price reaches target |

### 8.5 Signal Generation Framework

Convert the existing binary forecast system into a formal signal generation framework:

```python
class Signal:
    """A trading signal derived from a forecast."""
    instrument: str
    direction: float          # +1.0 (long) to -1.0 (short)
    strength: float           # 0.0 to 1.0
    horizon: timedelta
    confidence: float         # calibrated probability
    edge: float               # model_prob - market_prob
    rationale: str
    source: str               # S1-S4 tier
    expiry: datetime
    
    def to_order(self, portfolio: Portfolio) -> Optional[Order]:
        """Convert signal to order with position sizing."""
        if abs(self.edge) < MIN_EDGE_THRESHOLD:
            return None  # No edge, no trade
        size = self._kelly_size(portfolio)
        return Order(
            instrument=self.instrument,
            side="buy" if self.direction > 0 else "sell",
            quantity=size,
            ...
        )
```

### 8.6 Kelly Criterion Position Sizing

```python
def kelly_fraction(p: float, b: float) -> float:
    """
    Kelly Criterion: f* = (bp - q) / b
    where p = probability of win, q = probability of loss (1-p), b = win/loss ratio
    """
    q = 1 - p
    return (b * p - q) / b

def half_kelly(fraction: float) -> float:
    """Use half-Kelly for risk management."""
    return fraction * 0.5
```

Use the forecast probability `p` and the market-implied odds `b` to compute the optimal fraction of portfolio to allocate. Apply the half-Kelly rule to reduce risk.

### 8.7 Portfolio Optimization

```python
class PortfolioOptimizer:
    """Optimize portfolio allocation across strategies."""
    def mean_variance_optimization(self, returns: DataFrame) -> dict[str, float]
    def risk_parity_allocation(self, risk_contributions: dict[str, float]) -> dict[str, float]
    def black_litterman(self, views: list[View], market_equilibrium: dict) -> dict[str, float]
    def risk_budgeting(self, risk_limits: RiskBudget) -> dict[str, float]
```

---

## 9. Data & Integration Enhancements

### 9.1 Time-Series Database

Add a dedicated time-series database for market data:

| Option | Pros | Cons |
|--------|------|------|
| **QuestDB** | SQL + SQL-like queries, extremely fast ingestion | New infrastructure |
| **TimescaleDB** | PostgreSQL extension, familiar SQL | Additional dependency |
| **InfluxDB** | Purpose-built for time series, good ecosystem | Additional dependency |
| **DuckDB** | Embedded, no server, fast analytical queries | Less mature for time series |

**Recommendation:** Use **DuckDB** for embedded analytical queries (already Python-native) + **SQLite** for operational data. This avoids new infrastructure.

### 9.2 Feature Store

Add a feature store for reproducible ML features:

```python
class FeatureStore:
    """Store and retrieve ML features for model training and inference."""
    def get_features(self, instrument: str, start: datetime, end: datetime) -> DataFrame
    def store_features(self, instrument: str, features: DataFrame, version: str) -> None
    def get_feature_history(self, instrument: str, feature_names: list[str]) -> DataFrame
```

**Features to compute:**
- Technical indicators (MA, EMA, RSI, MACD, Bollinger Bands, ATR)
- Statistical features (volatility, skewness, kurtosis, autocorrelation)
- Microstructure features (spread, depth, order flow imbalance)
- Prediction market features (implied probability, volume, liquidity, spread)

### 9.3 Data Lineage & Audit

The existing SHA-256 sealing system (`canonical_json_sha256()`, `_validated_canonical_context_pack()`) is production-grade. Extend it:

1. **Trade data lineage** — every input to a trading decision must have a cryptographic hash
2. **Model version tracking** — every forecast model version is hashed and stored
3. **Reproducibility** — given a hash, reproduce exact trading decisions
4. **Regulatory compliance** — MiFID II, SEC Rule 17a-4 compatible audit trail

### 9.4 External Data Sources

Add these to the existing DeerFlow research infrastructure:

| Source | Purpose | Integration Method |
|--------|---------|-------------------|
| **Exchange APIs** | Real-time prices, order books | REST + WebSocket |
| **News APIs** | Sentiment, event detection | REST |
| **Economic Data** | Macro indicators (FRED, Census) | REST |
| **Alternative Data** | Satellite, credit card, web traffic | REST + file |
| **On-Chain Data** | Blockchain analytics | RPC + APIs |
| **SEC EDGAR** | Financial filings | REST |
| **Financial Modeling Prep** | Fundamental data | REST |

---

## 10. Risk Management & Compliance Layer

### 10.1 Risk Framework

```python
class RiskFramework:
    """Complete risk management system."""
    
    # Position Risk
    def check_position_limits(self, order: Order, portfolio: Portfolio) -> RiskDecision
    def check_concentration_risk(self, portfolio: Portfolio) -> RiskDecision
    def check_correlation_risk(self, portfolio: Portfolio) -> RiskDecision
    
    # Portfolio Risk
    def calculate_var(self, portfolio: Portfolio, confidence: float = 0.95) -> float
    def calculate_cvar(self, portfolio: Portfolio, confidence: float = 0.95) -> float
    def calculate_max_drawdown(self, portfolio: Portfolio) -> float
    def calculate_sharpe_ratio(self, portfolio: Portfolio) -> float
    def calculate_sortino_ratio(self, portfolio: Portfolio) -> float
    def calculate_calmar_ratio(self, portfolio: Portfolio) -> float
    
    # Market Risk
    def check_market_hours(self, instrument: str) -> RiskDecision
    def check_liquidity(self, instrument: str, quantity: float) -> RiskDecision
    def check_volatility(self, instrument: str) -> RiskDecision
    
    # Operational Risk
    def check_daily_loss_limit(self, portfolio: Portfolio) -> RiskDecision
    def check_margin_requirement(self, portfolio: Portfolio) -> RiskDecision
    def check_circuit_breaker(self, market: MarketData) -> RiskDecision
```

### 10.2 Compliance Controls

1. **Pre-trade validation**
   - Position limits
   - Margin requirements
   - Concentration limits
   - Trading hours
   - Restricted instruments

2. **Post-trade reconciliation**
   - Order confirmation vs. execution
   - P&L verification
   - Position balance verification
   - Cash balance verification

3. **Audit trail**
   - Every decision logged with hash
   - Every action signed
   - Immutable ledger
   - Regulatory report generation

### 10.3 Circuit Breakers

```python
class CircuitBreaker:
    """Market and system circuit breakers."""
    
    # Market Circuit Breakers
    def check_price_spike(self, instrument: str, threshold: float) -> bool
    def check_volume_anomaly(self, instrument: str, threshold: float) -> bool
    def check_spread_widening(self, instrument: str, threshold: float) -> bool
    
    # System Circuit Breakers
    def check_error_rate(self, threshold: float, window: timedelta) -> bool
    def check_latency_spike(self, threshold: float) -> bool
    def check_budget_exhausted(self, budget: Budget) -> bool
    def check_provider_outage(self) -> bool
    
    # Trading Circuit Breakers
    def check_daily_loss_limit(self, limit: float) -> bool
    def check_position_limit(self, limit: float) -> bool
    def check_concentration_limit(self, limit: float) -> bool
```

### 10.4 Stress Testing

Extend the existing `backtest.py` with stress testing:

1. **Historical stress tests** — replay 2008, 2020, 2022 market events
2. **Monte Carlo simulation** — random market scenarios
3. **Scenario analysis** — what if correlation goes to 1? What if volatility doubles?
4. **Liquidity stress** — what if market depth drops 90%?
5. **Flash crash simulation** — 10% drop in 1 minute

---

## 11. Implementation Roadmap

### Phase 1: Foundation (Weeks 1-4)
**Goal:** Establish the event-driven infrastructure and execution bridge.

| Task | Description | Dependencies |
|------|-------------|-------------|
| 1.1 | Add WebSocket/SSE layer to Flask | None |
| 1.2 | Replace polling with event-driven architecture | 1.1 |
| 1.3 | Add Redis/NATS message bus | 1.1 |
| 1.4 | Extend `forecast_ledger.py` with trade-level P&L | None |
| 1.5 | Add Portfolio state machine | 1.4 |
| 1.6 | Fix GRAPH per-graph asyncio.Lock | None |
| 1.7 | Enable prompt caching in DeerFlow | None |
| 1.8 | Fix Polymarket SQLite contention → Redis | None |

### Phase 2: Market Data & Orders (Weeks 5-8)
**Goal:** Connect to real market data and enable order execution.

| Task | Description | Dependencies |
|------|-------------|-------------|
| 2.1 | Add exchange WebSocket market data feeds | 1.3 |
| 2.2 | Build MarketDataAdapter (unified interface) | 2.1 |
| 2.3 | Add historical data pipeline | 2.2 |
| 2.4 | Build Order Management System (OMS) | 1.5 |
| 2.5 | Connect to exchange REST APIs for orders | 2.4 |
| 2.6 | Add order confirmation and reconciliation | 2.5 |
| 2.7 | Build Signal generation framework | 1.5, 2.2 |

### Phase 3: Risk & Portfolio (Weeks 9-12)
**Goal:** Add risk management and portfolio optimization.

| Task | Description | Dependencies |
|------|-------------|-------------|
| 3.1 | Build RiskEngine with position limits | 1.5 |
| 3.2 | Add Kelly Criterion position sizing | 3.1 |
| 3.3 | Build PortfolioOptimizer | 3.1 |
| 3.4 | Add circuit breakers | 3.1 |
| 3.5 | Add daily loss limits and margin monitoring | 3.1 |
| 3.6 | Build stress testing framework | 3.3 |
| 3.7 | Add compliance audit trail | 3.4 |

### Phase 4: Real-Time Simulation (Weeks 13-16)
**Goal:** Convert OASIS to real-time mode and add order book simulation.

| Task | Description | Dependencies |
|------|-------------|-------------|
| 4.1 | Convert OASIS to streaming mode | 1.3 |
| 4.2 | Build OrderBook simulation engine | 4.1 |
| 4.3 | Map agent decisions to orders | 4.2 |
| 4.4 | Add market microstructure features | 4.2 |
| 4.5 | Build real-time scenario dashboard | 4.3 |
| 4.6 | Add event-driven agent belief updates | 4.1 |

### Phase 5: Intelligence & Optimization (Weeks 17-20)
**Goal:** Add ML-based signal generation and adaptive strategies.

| Task | Description | Dependencies |
|------|-------------|-------------|
| 5.1 | Build feature store with technical indicators | 2.2 |
| 5.2 | Add ML-based forecast model (beyond LLM) | 5.1 |
| 5.3 | Add reinforcement learning for strategy selection | 5.2 |
| 5.4 | Build automated calibration pipeline | 5.2 |
| 5.5 | Add multi-armed bandit strategy selection | 5.3 |
| 5.6 | Add cross-asset correlation modeling | 5.1 |

### Phase 6: Production Hardening (Weeks 21-24)
**Goal:** Deploy, monitor, and validate.

| Task | Description | Dependencies |
|------|-------------|-------------|
| 6.1 | Add comprehensive logging and monitoring | All |
| 6.2 | Add alerting system | All |
| 6.3 | Add latency and throughput benchmarks | All |
| 6.4 | Controlled backtest validation | 5.4 |
| 6.5 | Paper trading validation | 6.4 |
| 6.6 | Live trading with small capital | 6.5 |
| 6.7 | Full production deployment | 6.6 |

---

## 12. Success Metrics & Validation

### 12.1 Performance Metrics

| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Pipeline runtime | 14h | 4-5h | `pipeline_state.json` |
| Total tokens/run | ~150M | ~50M | `telemetry.json` |
| GRAPH stage time | 8h 37m | 2-3h | `pipeline_state.json` |
| Report waste rate | 8/13 (62%) | <10% | `pipeline_state.json` |
| Provider outage recovery | 26h | <10min | `llm_health.json` |

### 12.2 Trading Performance Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Forecast calibration (Brier) | <0.15 | `forecast_ledger.py` |
| Sharpe ratio | >1.5 | Portfolio metrics |
| Max drawdown | <10% | Portfolio metrics |
| Win rate | >55% | Trade blotter |
| Average edge per trade | >2% | Signal vs. market |
| Calibration error | <0.05 | `calibration_summary()` |
| Model decay detection | <24h | Recalibration pipeline |

### 12.3 Validation Approach

1. **Backtesting** — Use `backtest.py` (Murphy decomposition, Brier score, log-loss) to validate against historical data
2. **Paper trading** — Run strategies with simulated capital for 1-3 months
3. **A/B testing** — Run old vs. new strategies in parallel
4. **Shadow mode** — Generate signals without executing, compare to actual market outcomes
5. **Controlled live trading** — Start with minimum capital, gradually increase

### 12.4 Quality Gates

Extend the existing `PIPELINE_HEALTH_GATE` to include trading-specific checks:

```python
TRADING_QUALITY_GATES = {
    "min_calibration_score": 0.95,      # Brier score threshold
    "max_daily_loss": 0.02,             # 2% daily loss limit
    "min_ensemble_agreement": 0.7,      # TV-distance threshold
    "max_position_concentration": 0.10, # 10% per instrument
    "min_market_liquidity": 200,        # Minimum Polymarket volume
    "max_spread": 0.05,                 # Maximum bid-ask spread
}
```

---

## Appendix: Key File References

### Core Pipeline
| File | Lines | Purpose |
|------|-------|---------|
| `backend/app/services/pipeline_orchestrator.py` | 1-7618 | Pipeline spine (6 stages) |
| `backend/app/config.py` | 1-1502 | All configuration knobs |
| `backend/app/models/task.py` | — | Task state management |
| `backend/app/models/project.py` | — | Project persistence |

### Forecast & Trading Models
| File | Lines | Purpose |
|------|-------|---------|
| `backend/app/services/forecast_extractor.py` | — | Binary forecast generation |
| `backend/app/services/forecast_ledger.py` | — | Trade blotter + settlement |
| `backend/app/services/backtest.py` | — | Brier score, Murphy decomposition |
| `backend/app/services/ensemble.py` | — | Multi-seed aggregation |
| `backend/app/services/decision_channel.py` | — | Multi-agent market microstructure |
| `backend/app/services/worldstate.py` | — | Stochastic price model |
| `backend/app/services/world_delta.py` | — | Catalyst notifications |
| `backend/app/services/agent_dynamics.py` | — | Agent behavioral model |
| `backend/app/services/exec_brief.py` | — | Execution summaries |
| `backend/app/services/requirement_spec.py` | — | Prediction task specification |
| `backend/app/services/resolution_autorun.py` | — | Settlement daemon |

### Simulation
| File | Lines | Purpose |
|------|-------|---------|
| `backend/app/services/simulation_runner.py` | 1-1700+ | OASIS simulation engine |
| `backend/app/services/simulation_manager.py` | — | Simulation lifecycle |
| `backend/app/services/oasis_profile_generator.py` | — | Agent persona generation |
| `backend/app/services/simulation_config_generator.py` | — | Temporal configuration |
| `backend/app/services/actor_context.py` | — | Agent intelligence packs |
| `backend/app/services/actor_role_prompt.py` | — | Role contracts |

### Market Integration
| File | Lines | Purpose |
|------|-------|---------|
| `backend/app/utils/prediction_markets.py` | — | Polymarket client |
| `deerflow_bridge/market_tools.py` | — | Research market tools |
| `deerflow_bridge/research_budget.py` | — | Budget ledger |
| `deerflow_bridge/deerflow_research.py` | — | Research driver (8905 lines) |

### Graph
| File | Lines | Purpose |
|------|-------|---------|
| `backend/app/services/graphiti_client/runtime.py` | — | Graph runtime + async bridge |
| `backend/app/services/graphiti_client/client.py` | — | Zep-shaped facade |
| `backend/app/services/graphiti_client/llm_adapter.py` | — | LLM adapter + I/O pool |
| `backend/app/services/graph_builder.py` | — | Graph construction |
| `backend/app/services/graph_pruner.py` | — | 400-node cap pruning |

### Performance
| File | Lines | Purpose |
|------|-------|---------|
| `backend/app/utils/telemetry.py` | — | Token metering |
| `backend/app/utils/token_budget.py` | — | Context budgeting |
| `backend/app/utils/llm_client.py` | — | LLM client + circuit breakers |
| `backend/app/utils/oasis_llm.py` | — | OASIS LLM bridge |

### Frontend
| File | Lines | Purpose |
|------|-------|---------|
| `frontend/src/views/` | — | Vue 3 SPA views |
| `frontend/src/api/` | — | API client modules |
| `frontend/src/components/` | — | UI components |

---

## Document Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-09-27 | Multi-Agent Analysis | Initial comprehensive analysis |
| — | | | |

---

*This document was produced by 5 parallel AI agent teams analyzing the DeepResearchForecast codebase. All findings are grounded in actual source code with `file:line` references where applicable. The architecture maps, performance analyses, and simulation deep-dives are available as companion documents in the repository.*
