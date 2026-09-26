# DeepResearchForecast Codebase — Comprehensive Simulation Engine & Quantitative Modeling Analysis

**Last Updated**: 2026-09-27  
**Status**: Complete Analysis  
**Scope**: 18+ files across simulation engine, agent dynamics, forecast extraction, backtesting, ensembles, and graphiti_client

---

## 1. EXECUTIVE SUMMARY

This codebase implements an **OASIS/CAMEL multi-agent social simulation** system that models discourse dynamics on Twitter and Reddit platforms. Agents are LLM-powered personas that post, comment, like, follow, and repost in simulated social environments. The system produces structured forecasts, runs backtests, and aggregates ensembles — but is fundamentally a **social simulation**, not a market simulation. Production quant trading adaptation would require significant architectural additions.

**Key architectural fact**: Simulation runs as a subprocess, orchestrated via file-based IPC. The backend orchestrator launches Python scripts, monitors their progress, reads JSONL action logs, and manages lifecycle (start/stop/resume).

---

## 2. OASIS/CAMEL MULTI-AGENT SOCIAL SIMULATION MECHANICS

### 2.1 Current Mechanism

The system uses the **OASIS** framework (Open Agent Social Simulation) with the **CAMEL** agent communication pattern. Key mechanics:

- **Agent Pool Selection** (`simulation_manager.py` → `select_agent_pool`): Agents are selected from a graph based on relevance to simulation entities. The selection uses Zep graph search to find nodes matching entity names, then filters by entity type and relevance scores.

- **OASIS Profile Generation** (`oasis_profile_generator.py`): Generates LLM-based personas for each entity. The flow is:
  1. Resolve entity in Zep graph (uuid lookup)
  2. Retrieve ego network (relation edges)
  3. Build entity context (attributes, edges, related nodes, Zep search results)
  4. Call LLM to generate persona JSON (bio, persona, demographic fields, values, beliefs, incentives)
  5. Optional: persona_design block (structured design fields: identity, views, incentives, objectives, relations, constraints, decision_style, rhetoric)
  6. Optional: Market priors injection for analyst/media roles (prediction_markets.json relevance-gated)

- **Activity Configuration** (`simulation_config_generator.py`): Generates per-agent activity configs:
  - `AgentActivityConfig` with fields: `entity_name`, `entity_type`, `influence_weight`, `stance`, `sentiment_bias`, `interested_topics`, `posting_frequency`, `engagement_pattern`
  - Echo chamber follows: deterministic clustering by (stance_bucket, topic) with cross-role bridges
  - Scheduled events from research key_events mapped to rounds
  - Temporal mode: calendar (round_dates → periods) or hours-based

### 2.2 Key Data Structures

**AgentAction** (`simulation_runner.py`):
```python
@dataclass
class AgentAction:
    round_num: int
    timestamp: str
    platform: str  # "twitter" or "reddit"
    agent_id: int
    agent_name: str
    action_type: str  # CREATE_POST, CREATE_COMMENT, QUOTE_POST, LIKE_POST, FOLLOW, MUTE, REPOST
    action_args: dict  # content, followee_id, etc.
    result: Optional[dict]
    success: bool
```

**SimulationRunState** (`simulation_runner.py`):
```python
@dataclass
class SimulationRunState:
    simulation_id: str
    runner_status: RunnerStatus  # STARTING, RUNNING, STOPPING, STOPPED, COMPLETED, FAILED, PAUSED
    current_round: int
    twitter_current_round: int
    reddit_current_round: int
    twitter_enabled: bool
    reddit_enabled: bool
    twitter_completed: bool
    reddit_completed: bool
    twitter_running: bool
    reddit_running: bool
    process_pid: int
    process_pgid: int
    error: Optional[str]
    created_at: str
    completed_at: Optional[str]
    _lock: threading.RLock  # All state mutations are lock-protected
```

**SimulationState** (`simulation_manager.py`):
```python
@dataclass
class SimulationState:
    simulation_id: str
    project_id: str
    graph_id: str
    status: SimulationStatus  # PENDING, READY, RUNNING, STOPPED, COMPLETED, FAILED
    profiles_count: int
    entities_count: int
    config_generated: bool
    actor_role_count: int
    actor_context_count: int
    simulation_config_sha256: str
    actor_cast_manifest_sha256: str
    # ... plus seals/validation hashes
```

### 2.3 Trading System Mapping

**Social actions → Trading analogs**:
| Social Action | Trading Analog | Fidelity |
|---|---|---|
| CREATE_POST | Place Order | Low — no price, size, side |
| QUOTE_POST / REPOST | Repost / Signal Propagation | Medium — information flow |
| CREATE_COMMENT | Commentary / Analysis | Low — no commitment |
| LIKE_POST | Vote / Signal Strength | Very Low — weak signal |
| FOLLOW | Follow / Subscribe to Signal | Low — relationship only |
| MUTE | Block / Ignore Signal | Very Low |

**Critical Gap**: The system has NO concepts of: order books, bid/ask spreads, slippage, liquidity depth, market impact, position sizing, margin, leverage, or portfolio construction. Agents do not trade; they communicate.

### 2.4 Enhancements Needed for Production Trading

1. **Agent → Trader Mapping**: Each agent needs a `Trader` overlay with: `portfolio`, `cash_balance`, `positions`, `risk_limits`, `execution_capabilities`
2. **Market Microstructure Layer**: Replace social feed with limit order book (LOB). Each agent submits orders (market/limit) with size, price, side.
3. **Price Discovery**: Mid-price evolves from order flow imbalance (OFI). Use the existing `sentiment_bias` → `sentiment_score` as a directional signal component.
4. **Execution Simulation**: Model slippage as function of order_size / liquidity_depth. Market impact via square-root model (Almgren-Chriss).
5. **State Evolution**: WorldState already has `scenarios`, `base_rates`, `shares`, `sentiment_bias` — these map directly to market state (scenario = regime, shares = probabilities, sentiment = order flow bias).

---

## 3. WORLD STATE EVOLUTION

### 3.1 Current Mechanism

**WorldState** (`worldstate.py`):
- Initialized with `scenarios` (list of scenario names), `base_rates` (prior probabilities), and `inertia` parameter
- **EWMA convergence**: `shares` evolve via exponentially weighted moving average:
  ```
  new_shares[s] = (1 - inertia) * observed[s] + inertia * old_shares[s]
  ```
- **Entropy mixing**: `WORLDSTATE_ENTROPY_MIX` flag adds noise to prevent premature convergence
- **Convergence detection**: `convergence_eps` (default 0.02) — when share changes fall below threshold for `SIM_CONVERGENCE_WINDOW` rounds, `converged_at` is set
- State is serialized to `world_state_trajectory.json` (schema v3)

**WorldDelta** (`world_delta.py`):
- Inter-round digest summarizing changes: `previous_leader`, `new_leader`, `leader_share`, `significant_shifts` (scenario → delta_share)
- Used to feed the WORLD CLOCK header in each round

**Decision Channel** (`decision_channel.py`):
- Post-simulation WorldState evolution via agent commitments
- `SIM_DECISION_CHANNEL` flag controls activation (default OFF)
- `SIM_DECISION_CHANNEL_INBAND` flag controls calendar-mode in-band evolution (default ON)
- Process: agent actions → active roster → commitment elicitation → WorldState.step() → qualitative summary
- `_activation_weight_map`, `_outcome_power_map`, `_agent_meta_map` weight each agent's influence
- Agent `outcome_power` (resource/structural leverage) × `influence_weight` (activation/visibility) determines voting power

**In-Band Evolution** (`run_parallel_simulation.py` → `_InbandWorldEvolution`):
- Calendar mode: per-round commitments elicited from agents, WorldState stepped each round
- Dual-platform shared single WorldState instance
- Dead-round heartbeat mechanism prevents platform-pair deadlock
- Trajectory written to `world_state_trajectory.json` with schema v3

### 3.2 Key Data Structures

**WorldState**:
```python
class WorldState:
    scenarios: List[str]
    base_rates: Dict[str, float]  # Prior probabilities
    shares: Dict[str, float]       # Current probabilities (sum to 1)
    inertia: float                 # EWMA smoothing (default 0.7)
    convergence_eps: float         # Convergence threshold (default 0.02)
    converged_at: Optional[int]    # Round at which convergence detected
    
    def step(self, observations: Dict[str, float]) -> Dict[str, float]:
        """Update shares via EWMA with entropy mixing"""
    
    def outcome(self) -> Dict[str, Any]:
        """Return current leader, shares, and metadata"""
```

### 3.3 Trading System Mapping

**WorldState → Market State**:
- `scenarios` = market regimes (bull, bear, sideways, crash)
- `shares` = regime probability distribution (directly usable as belief state)
- `base_rates` = prior probabilities (market priors from prediction markets)
- `inertia` = mean-reversion strength in belief updates
- `converged_at` = market consensus formation point
- `leader` = dominant narrative/thesis

**Decision Channel → Market Clearing**:
- Agent commitments = market orders (weighted by `outcome_power` × `influence_weight`)
- WorldState step = price/clearing mechanism
- EWMA convergence = market approaching equilibrium
- Entropy mixing = market noise/uncertainty

### 3.4 Enhancements Needed

1. **Explicit Price Variable**: Add `mid_price` and `order_book` to WorldState — current shares are regime probabilities, not prices
2. **Liquidity Modeling**: Track depth at each price level; agents submit limit orders
3. **Volume Modeling**: Action volume (posts/comments) maps to trading volume; add `volume` tracking per round
4. **Volatility Surface**: `polarization_index` could map to implied volatility
5. **Time Decay**: Add theta-like decay for scenarios far from resolution

---

## 4. AGENT DECISION MODELS

### 4.1 Current Mechanism

**Agent Dynamics** (`agent_dynamics.py`):
- Per-agent **affective state**: `mood`, `energy`, `opinion`, `fatigue`
- **Received-interaction signals**: Each agent maintains a queue of incoming interactions (mentions, replies, likes)
- **State evolution**: Mood follows sentiment of received content; energy depletes with activity and recovers with rest; fatigue accumulates
- **Activation gates**: Agent only acts when `energy > activation_threshold` and `mood > mood_threshold`

**Agent Activity Config** (`simulation_config_generator.py`):
- `AgentActivityConfig` fields:
  - `influence_weight`: Determines visibility in feed (higher = more likely seen)
  - `stance`: Supportive/opposing/neutral/observer
  - `sentiment_bias`: Directional tilt in posting
  - `interested_topics`: Topic tags
  - `posting_frequency`: How often the agent posts
  - `engagement_pattern`: Like/comment/repost ratios

**Decision Channel Activation** (`decision_channel.py`):
- **Activation weight**: Based on `influence_weight` × current engagement state
- **Outcome power**: Structural leverage (e.g., verified accounts, institutional actors have higher power)
- **Active roster**: Each round, top-N agents by activation weight are "called upon" to make commitments
- **Elicitation**: Called agents produce commitments (probability estimates for each scenario), weighted by `outcome_power`

### 4.2 Key Data Structures

**AffectiveState** (`agent_dynamics.py`):
```python
@dataclass
class AffectiveState:
    mood: float          # [-1, 1] — sentiment state
    energy: float        # [0, 1] — available activity budget
    opinion: float       # [-1, 1] — stance direction
    fatigue: float       # [0, 1] — accumulated tiredness
    received_signals: List[InteractionSignal]
```

**AgentActivityConfig** (`simulation_config_generator.py`):
```python
@dataclass
class AgentActivityConfig:
    agent_id: int
    entity_name: str
    entity_type: str
    influence_weight: float    # Visibility/activation priority
    stance: str               # supportive/opposing/neutral/observer
    sentiment_bias: float     # [-1, 1] directional tilt
    interested_topics: List[str]
    posting_frequency: float  # Posts per round
    engagement_pattern: Dict[str, float]  # Like/comment/repost ratios
    outcome_power: float      # Structural leverage
```

### 4.3 Trading System Mapping

**Agent Decision → Trading Decision**:
- `outcome_power` = capital allocation / position size
- `influence_weight` = signal strength / credibility
- `stance` = directional bias (long/short/neutral)
- `sentiment_bias` = alpha signal (directional conviction)
- `activation_threshold` = opportunity cost threshold (only trade when expected edge > threshold)
- `fatigue` = risk aversion (tired agents trade less)
- `mood` = market sentiment (affects risk appetite)

**Commitment Elicitation → Forecast/Order**:
- Agent commitments = probability estimates (forecasts) OR order submissions
- Weighted by `outcome_power` → weighted average = consensus forecast / clearing price
- The `influence_weight` × `outcome_power` product mirrors **Kelly criterion** sizing

### 4.4 Enhancements Needed

1. **Risk Management Layer**: Add `risk_tolerance`, `max_position`, `stop_loss` parameters per agent
2. **Portfolio State**: Each agent needs `positions`, `pnl`, `exposure` tracking
3. **Execution Strategy**: Agents choose between market/limit orders, timing strategies
4. **Information Asymmetry**: Some agents could have private information (insider modeling)
5. **Learning/Adaptation**: Agents update strategies based on past performance (reinforcement learning)
6. **Correlation Awareness**: Agents aware of other agents' positions (herding detection)

---

## 5. FORECAST EXTRACTION

### 5.1 Current Mechanism

**Forecast Extractor** (`forecast_extractor.py` — 2193+ lines, the largest service):
Multi-pass LLM structured forecast extraction with the following pipeline:

1. **Binary Forecast Generation**: For each scenario, produce binary yes/no forecasts with confidence
   - `market_anchor` with `implied_yes_prob` — the closest concept to market pricing
   - `divergence` between model's estimate and market anchor
   
2. **Citation Grounding**: Every forecast claim must cite specific evidence from research documents
   - References to source documents with page/section
   - Verifiability scoring based on source quality

3. **Market Anchoring**: Prediction market data (`prediction_markets.json`) used as calibration anchor
   - `implied_yes_prob` from Polymarket-style markets
   - Forecasts can be compared against market prices
   - `divergence` field captures gap between model and market

4. **Scenario Extraction**: Multi-scenario forecasts with probabilities:
   - Base case, bull case, bear case, tail events
   - Each with probability, key drivers, and evidence citations

5. **Temporal Forecasts**: Time-bound predictions (when will X happen)
   - Uses temporal_config.round_dates for calendar alignment

6. **Structured Output**: JSON schema with fields: `forecast_id`, `scenario`, `probability`, `confidence`, `evidence`, `market_anchor`, `divergence`

### 5.2 Key Data Structures

**BinaryForecast** (`forecast_extractor.py`):
```python
@dataclass
class BinaryForecast:
    forecast_id: str
    scenario: str
    probability: float           # Model's estimate
    market_anchor: Optional[Dict]  # {implied_yes_prob, source}
    divergence: Optional[float]   # model_prob - implied_yes_prob
    confidence: float             # Self-assessed confidence
    evidence: List[str]           # Citation references
    reasoning: str
```

**StructuredForecast** (`forecast_extractor.py`):
```python
@dataclass
class StructuredForecast:
    forecast_id: str
    question: str
    scenarios: List[ScenarioForecast]  # {name, probability, drivers, evidence}
    binary_forecasts: List[BinaryForecast]
    temporal_predictions: List[TemporalPrediction]
    calibration_notes: str
    market_comparison: Optional[MarketComparison]
```

**ForecastLedger** (`forecast_ledger.py`):
- Persistent ledger of all forecasts with calibration tracking
- `resolutions.jsonl` — market resolution tracking
- Calibration loop: compares forecast probability vs actual outcome
- Market resolution data feeds back for recalibration

### 5.3 Trading System Mapping

**Forecast → Trading Signal**:
- `probability` = edge estimate (P(upside) vs market implied P)
- `divergence` = alpha signal (positive divergence = model more bullish than market)
- `confidence` = position sizing input (higher confidence → larger position)
- `evidence` = research backing (qualitative conviction)
- `market_anchor` = current market price/belief (the baseline to beat)
- Calibration quality = strategy reliability metric

**Forecast Ledger → Trade Journal**:
- Every forecast = a trade idea with entry thesis
- `resolutions.jsonl` = trade outcomes (win/loss)
- Calibration loop = strategy performance attribution
- Murphy decomposition (from backtest.py) = alpha vs luck decomposition

### 5.4 Enhancements Needed

1. **Real-Time Scoring**: Forecasts need continuous updating as market conditions change
2. **Cross-Asset Correlations**: Forecasts should account for correlated instruments
3. **Volatility Forecasts**: Not just directional, but implied vol forecasts
4. **Regime-Conditional Forecasts**: Different models for different market regimes
5. **Backtested Forecast Accuracy**: Track Brier score, log-loss over time as strategy KPI
6. **Ensemble of Forecasts**: Multiple models producing consensus (see Section 7)

---

## 6. BACKTESTING

### 6.1 Current Mechanism

**Backtest** (`backtest.py` — 237 lines):
The backtesting module implements probabilistic forecast evaluation:

1. **Brier Score**: 
   ```
   BS = (1/N) Σ (p_i - o_i)²
   ```
   Where p_i = forecast probability, o_i = actual outcome (0/1). Lower = better calibration.

2. **Log-Loss (Cross-Entropy)**:
   ```
   LL = -(1/N) Σ [o_i * log(p_i) + (1-o_i) * log(1-p_i)]
   ```
   Penalizes overconfident wrong predictions severely.

3. **Calibration Report**:
   - Reliability diagram data (binning probabilities, comparing avg forecast vs avg outcome)
   - Expected calibration error (ECE)
   - Maximum calibration error

4. **Murphy Decomposition**:
   - Decomposes score into: **reliability** (calibration), **resolution** (discrimination), **uncertainty** (base rate)
   - `score = reliability + resolution + uncertainty`
   - This identifies whether a forecaster adds value through calibration or discrimination

5. **fit_recalibrator**: 1-param logit-scale recalibrator (Platt scaling)
   - Fits `σ(α * logit(p) + β)` to minimize CRPS
   - This is analogous to trading strategy calibration

### 6.2 Key Data Structures

```python
@dataclass
class CalibrationReport:
    brier_score: float
    log_loss: float
    reliability: float        # Murphy decomposition component
    resolution: float         # Murphy decomposition component
    uncertainty: float        # Murphy decomposition component
    ece: float                # Expected Calibration Error
    recalibrated_score: float # After Platt scaling
    n_observations: int
```

### 6.3 Trading System Mapping

**Backtest Metrics → Trading KPIs**:
| Backtest Metric | Trading Analog | Notes |
|---|---|---|
| Brier Score | Sharpe-like calibration score | Lower BS = better calibrated signals |
| Log-Loss | Information coefficient (IC) | Penalizes bad confidence estimates |
| Murphy Reliability | Strategy calibration quality | Is the model well-calibrated? |
| Murphy Resolution | Alpha generation | Does the model discriminate winners from losers? |
| fit_recalibrator | Strategy calibration/normalization | Adjust raw signals to market prices |
| Calibration Error | Slippage estimate | Gap between expected and realized |

**Critical Gap**: No PnL backtesting. Current system evaluates **forecast quality**, not **trading performance**. Missing: returns, drawdown, Sharpe ratio, Sortino ratio, max drawdown, win rate, profit factor.

### 6.4 Enhancements Needed

1. **PnL Simulation**: Convert forecasts → simulated trades → PnL time series
2. **Risk-Adjusted Metrics**: Sharpe, Sortino, Calmar ratios
3. **Drawdown Analysis**: Peak-to-trough analysis, recovery time
4. **Strategy Comparison**: Side-by-side comparison of different forecasting strategies
5. **Transaction Cost Model**: Include estimated costs in backtest
6. **Walk-Forward Analysis**: Rolling window backtest to avoid look-ahead bias
7. **Monte Carlo Permutation**: Shuffle forecast/outcome pairs to establish significance

---

## 7. ENSEMBLE METHODS

### 7.1 Current Mechanism

**Ensemble** (`ensemble.py` — 419 lines):
Multi-run forecast aggregation with the following approach:

1. **Multi-Seed Runs**: Execute multiple simulation runs with different random seeds
2. **Extremized Log-Odds Pooling**:
   ```python
   def _extremized_logodds(probabilities, extremizing_factor_a):
       """Convert probabilities to log-odds, scale by extremizing factor, convert back"""
       log_odds = log(p / (1 - p))
       extremized = a * log_odds
       return sigmoid(extremized)
   ```
   - `a > 1`: Sharpens consensus (pushes toward 0 or 1) — used when confident in signal
   - `a < 1`: Softens consensus (pushes toward 0.5) — used when uncertain
   - `a = 1`: Linear pooling (no extremizing)

3. **Semantic Alignment**: Ensures ensemble members are semantically diverse (not redundant)
4. **Weighted Aggregation**: Agents/runs weighted by `outcome_power` × historical accuracy

### 7.2 Key Data Structures

**EnsembleConfig**:
```python
@dataclass
class EnsembleConfig:
    num_runs: int               # Number of seeds
    extremizing_factor: float   # a parameter for log-odds pooling
    aggregation_method: str     # "extremized_logodds", "linear", "weighted"
    semantic_diversity_weight: float
    run_weights: Optional[List[float]]
```

**EnsembleResult**:
```python
@dataclass
class EnsembleResult:
    individual_runs: List[Forecast]
    aggregated_forecast: Forecast
    consensus_probability: float
    dispersion: float           # How much agents disagree
    extremizing_factor: float
    quality_score: float        # Ensemble confidence metric
```

### 7.3 Trading System Mapping

**Ensemble → Trading System**:
- **Multi-model ensemble** = Portfolio of alpha signals
- **Extremized log-odds** = Conviction scaling (high conviction → larger position)
- **Dispersion** = Uncertainty measure (high dispersion → reduce position size)
- **Semantic diversity** = Correlation matrix of signals (diversification benefit)
- **Weighted aggregation** = Risk-parity or alpha-weighted portfolio construction

**The extremizing factor `a` is DIRECTLY analogous to conviction sizing**:
- `a >> 1`: All-in conviction trades
- `a ≈ 1`: Normal-sized positions
- `a << 1`: Small/exploratory positions

### 7.4 Enhancements Needed

1. **Dynamic Extremizing**: `a` should adapt based on recent ensemble performance
2. **Stacking/Blending**: Meta-model that learns optimal weights for combining ensemble members
3. **Bayesian Model Averaging**: Proper uncertainty quantification via posterior model probabilities
4. **Drawdown-Constrained Ensemble**: Drop underperforming ensemble members during drawdowns
5. **Real-Time Ensemble Monitoring**: Track each member's decay and add/remove dynamically
6. **Cross-Validation for Weights**: Out-of-sample weight optimization

---

## 8. DECISION CHANNELS & EXECUTIVE BRIEFS

### 8.1 Decision Channel Mechanics

**Decision Channel** (`decision_channel.py` — 775 lines):
Post-simulation WorldState evolution via agent commitments.

**Flow**:
1. `run_decision_channel()` activated (SIM_DECISION_CHANNEL flag)
2. Build active roster: agents ranked by `activation_weight` (influence_weight × engagement)
3. Elicit commitments: Top-N agents produce probability estimates for each scenario
4. WorldState.step(): Apply commitments as weighted observations → EWMA update
5. Generate qualitative summary via LLM (world_delta.build_world_delta)
6. Write world_digest.jsonl (quantitative audit trail)

**In-Band Mode** (SIM_DECISION_CHANNEL_INBAND, calendar mode only):
- Every round: deliver platform actions → build roster → elicit → step → summary
- Dual-platform synchronization: both platforms' actions processed before stepping
- Trajectory written to `world_state_trajectory.json` (schema v3)

**Post-Hoc Mode** (default): After simulation completes, replay all actions through decision channel

### 8.2 Executive Briefs

**Exec Brief** (`exec_brief.py` — 927 lines):
Builds executive deliverables from simulation results:

1. **Report Generation**: Aggregates run_summary, emergent_metrics, world_state_trajectory
2. **Narrative Construction**: LLM generates narrative from quantitative data
3. **Key Findings Extraction**: Top insights, leader changes, polarization events
4. **Timeline of Events**: Chronological summary of critical moments
5. **Forecast Summary**: Consensus forecasts with confidence intervals
6. **Actionable Intelligence**: Recommendations derived from simulation outcomes

### 8.3 Trading System Mapping

**Decision Channel → Order Management**:
- Active roster = universe of tradable instruments/strategies
- Commitment elicitation = signal generation (each agent = a strategy)
- WorldState.step = portfolio rebalancing signal
- Qualitative summary = narrative overlay (sentiment analysis)

**Exec Brief → Trading Report**:
- Report = daily/quarterly performance report
- Key findings = alpha attribution
- Timeline = trade blotter
- Forecast summary = forward-looking views
- Actionable intelligence = trade recommendations

### 8.4 Enhancements Needed

1. **Real-Time Decision Channel**: Currently post-simulation; needs streaming/real-time mode
2. **Order Execution Integration**: Commitments → actual orders via broker API
3. **Risk Checkpoints**: Pre-trade risk checks before WorldState updates
4. **Slippage Modeling**: Decision quality degraded by execution friction
5. **Multi-Asset Support**: Multiple independent decision channels for different instruments
6. **Automated Execution**: Brief → order without human intervention

---

## 9. REQUIREMENT SPECS & SIMULATION TIMELINE

### 9.1 Requirement Spec

**Requirement Spec** (`requirement_spec.py` — 105 lines):
Parses forecast brief specifications:
- Structured input: forecast question, entities, timeline constraints
- Output: Parsed requirement with entities, time horizon, confidence thresholds
- Maps research documents → simulation parameters

### 9.2 Simulation Timeline

**Two Temporal Modes** (`simulation_config_generator.py`):

**Hours Mode** (legacy):
- `total_simulation_hours` × 60 / `minutes_per_round` = total rounds
- Linear time mapping (each round = fixed time increment)
- Round → time via linear interpolation

**Calendar Mode** (`temporal_config`):
- `round_dates`: Array of {round, period_start, period_end} mappings
- Each round maps to a real calendar period
- `as_of_date`: Simulation start date
- `horizon_date`: Prediction horizon end date
- Events dated in research → mapped to specific rounds via `events_to_calendar_rounds()`
- `n_rounds`: Hard cap (default ≤48 for calendar mode)

**Timeline in `run_parallel_simulation.py`**:
- `_resolve_total_rounds()`: Unique round count calculation
- Calendar mode: `temporal_config.n_rounds` is authoritative
- Hours mode: `total_simulation_hours * 60 / minutes_per_round` truncated by `max_rounds`
- `_build_round_to_date()`: Round → ISO date mapping (exact for calendar, linear for hours)

### 9.3 Trading System Mapping

**Timeline → Trading Calendar**:
- `as_of_date` = trade entry date
- `horizon_date` = position expiration/roll date
- `round_dates` = rebalancing schedule
- `n_rounds` = holding period
- Calendar events = scheduled market events (earnings, FOMC, economic data releases)

**Simulation Rounds → Trading Periods**:
- Each round = a trading period (day, week, month)
- Agent actions within a round = intraday activity
- Round-end = end-of-day portfolio valuation

### 9.4 Enhancements Needed

1. **Trading Calendar Integration**: Use actual market trading calendars (NYSE, etc.)
2. **Event Scheduling**: Earnings, FOMC, economic releases as scheduled events
3. **Rolling Windows**: Adaptive horizon that extends based on performance
4. **Multi-Horizon Forecasts**: Simultaneous short/medium/long-term predictions
5. **Real-Time Clock**: Live market clock integration for real-time simulation

---

## 10. GRAPHTI_CLIENT ARCHITECTURE

### 10.1 Overview

The `graphiti_client/` directory implements a **drop-in Zep replacement** backed by a local Graphiti knowledge graph (FalkorDB/Kuzu). This replaces the original Zep Cloud API with a fully local, no-external-service knowledge graph.

### 10.2 Component Map

| File | Purpose | Key Classes |
|---|---|---|
| `client.py` | Zep-compatible facade | `_ZepNode`, `_ZepEdge`, `_ZepEpisode`, `_SearchResult` |
| `runtime.py` | Async↔sync bridge + graph DB lifecycle | `GraphitiRuntime`, async event loop on bg thread |
| `llm_adapter.py` | Provider-agnostic LLM for graph extraction | `AppGraphitiLLMClient`, dedicated I/O thread pool |
| `embedder.py` | Local sentence-transformers embeddings | Embedding generation for graph nodes |
| `cross_encoder.py` | Cross-encoder for relevance scoring | Query-document relevance scoring |
| `falkor_driver.py` | FalkorDB (Redis-compatible) driver | Graph persistence layer |
| `ontology.py` | Custom graph ontology schema | Node/edge type definitions |
| `compat.py` | Compatibility utilities | Type conversions, adapter functions |
| `__init__.py` | Module exports | Public API surface |

### 10.3 Graph Knowledge Model

**Nodes**: Entities (people, organizations, events) with attributes, embeddings, summaries
**Edges**: Relationships with causal attributes (sign, strength, lag, polarity, valence)
**Episodes**: Observation contexts (documents, events) that trigger knowledge extraction

**Causal Edge Attributes** (`runtime.py`):
- `sign`: +1/-1 (positive/negative relationship)
- `strength`: High/medium/low
- `lag`: Temporal delay (e.g., "2w" = 2 weeks)
- `polarity`: Float [-1, 1]
- `valence`: Positive/negative sentiment

These are folded into edge `fact` text: `"…（sign=-，strength=high，lag=2w，polarity=-0.80）"` and parsed back for multi-hop causal reasoning.

### 10.4 Trading System Mapping

**Knowledge Graph → Market Intelligence**:
- **Nodes** = tradable assets, companies, economic indicators
- **Edges with polarity/strength** = correlation/causation between assets
- **Causal lag** = lead-lag relationships (e.g., interest rates → equity prices with 2-week lag)
- **Episodes** = market events that update beliefs
- **Graph search** = alternative data query (find relevant entities/relationships)
- **Multi-hop reasoning** = complex signal chains (e.g., Fed rate → bond yield → bank stocks → sector rotation)

### 10.5 Trading Enhancements

1. **Real-Time Graph Updates**: Stream market data into graph as new episodes
2. **Temporal Reasoning**: Use causal lag attributes for predictive signal chains
3. **Risk Graph**: Map counterparty risk, supply chain risk through graph
4. **Signal Extraction**: Graph queries to generate alpha signals (e.g., "find all companies affected by X")
5. **Portfolio Construction**: Use graph community detection for sector diversification

---

## 11. CROSS-CUTTING CONCERNS

### 11.1 Simulation IPC (`simulation_ipc.py` — 732 lines)

File-based command/response protocol:
- **Commands**: `start`, `stop`, `pause`, `resume`, `status`, `interview`, `health`
- **Responses**: JSON with `status`, `data`, `error` fields
- **File-based**: Commands written to `command.json`, responses read from `response.json`
- **Environment status**: `env_status.json` tracks platform availability
- **Telemetry**: `ipc_telemetry.jsonl` for latency monitoring

**Trading Implication**: This IPC pattern could be adapted for order management (send order command → receive execution report).

### 11.2 Action Logger (`action_logger.py` — 323 lines)

**PlatformActionLogger**: Structured logging of all agent actions
- Logs to JSONL files per platform
- Tracks: round, agent_id, agent_name, action_type, action_args, result, timestamp
- **SimulationLogManager**: Aggregates and manages log lifecycle

**Trading Implication**: Direct analog to trade blotter/audit trail.

### 11.3 Configuration Management

**Key configs** (`Config` class, accessed via `getattr(Config, KEY, default)`):
- `SIM_ACTIVITY_PROFILE`: `china_social` / `us_business` / `global_market`
- `SIM_DECISION_CHANNEL`: ON/OFF for post-sim WorldState evolution
- `SIM_MARKET_PRIORS`: ON/OFF for prediction market injection
- `SIM_WORLD_BRIEF`: ON/OFF for shared world context
- `WORLDSTATE_ENTROPY_MIX`: ON/OFF for entropy noise
- `SIM_CONVERGENCE_EPS`: Convergence threshold (default 0.02)
- `SIM_DECISION_INERTIA`: EWMA smoothing (default 0.7)
- `SIM_EMERGENT_METRICS`: ON/OFF for structural metrics
- `SIM_PERSONA_DESIGN`: ON/OFF for structured persona design
- `SIM_VALENCED_RELATIONS`: ON/OFF for relationship polarity
- `PERSONA_BEHAVIORAL_DNA`: ON/OFF for behavioral attributes

### 11.4 Graphiti Client Integration

**Current usage**: Persona generation uses Zep graph search to retrieve entity context. The `graphiti_client` replaces Zep entirely with local Graphiti.

**Flow**:
1. `OasisProfileGenerator` creates `ZepGraphMemoryManager` (or graphiti client)
2. Graph search for entity → ego network → context building
3. LLM generates persona with this context
4. Graph memory updated with simulation activities (via `add_activity_from_dict`)

---

## 12. PRODUCTION TRADING SIMULATION — ARCHITECTURE ROADMAP

### 12.1 Current State Assessment

| Component | Current State | Trading Readiness |
|---|---|---|
| Agent Communication | Full social simulation | ❌ Needs market action layer |
| World State | Probabilistic (regime) | ⚠️ Needs price/LOB overlay |
| Forecast Extraction | Binary/scenario with market anchors | ⚠️ Needs real-time pricing |
| Backtesting | Forecast quality (Brier, log-loss) | ❌ Needs PnL-based metrics |
| Ensembles | Extremized log-odds pooling | ✅ Close to trading ensemble |
| Decision Channel | Post-sim commitments | ❌ Needs real-time execution |
| Knowledge Graph | Entity/relationship graph | ✅ Directly usable |
| Action Logging | JSONL audit trail | ✅ Analog to trade blotter |
| Temporal Engine | Calendar/hours mode | ✅ With trading calendar swap |
| IPC | File-based command/response | ✅ Analog to order gateway |

### 12.2 Recommended Build Order

**Phase 1: Market Microstructure Layer** (Highest priority)
- Add LimitOrderBook to WorldState
- Agent actions → order submissions (buy/sell/limit/market)
- Price discovery via order flow imbalance
- Basic slippage model

**Phase 2: Agent → Trader Transformation**
- Add `Trader` state to each agent (portfolio, positions, cash)
- Map `outcome_power` → capital, `influence_weight` → signal quality
- Execution strategies (market/limit)
- Risk limits per agent

**Phase 3: PnL-Based Backtesting**
- Extend `backtest.py` with trade-level PnL
- Sharpe, drawdown, win rate metrics
- Transaction cost model
- Walk-forward validation

**Phase 4: Real-Time Decision Channel**
- Streaming commitment → order pipeline
- Pre-trade risk checks
- Order management integration
- Slippage-aware execution

**Phase 5: Advanced Features**
- Volatility forecasting
- Cross-asset correlation
- Regime detection
- Reinforcement learning adaptation

### 12.3 Key Gaps Summary

1. **NO order books** — social feed ≠ limit order book
2. **NO price discovery** — no mechanism for prices to emerge from supply/demand
3. **NO portfolio state** — agents have no positions, cash, or PnL
4. **NO transaction costs** — no slippage, fees, or market impact
5. **NO PnL metrics** — backtesting evaluates forecast quality, not trading returns
6. **NO execution model** — commitments are not orders
7. **NO real-time mode** — all simulations are batch/offline
8. **NO risk management** — no position limits, stop-losses, or margin
9. **NO leverage/margin** — all-or-nothing commitment model
10. **NO correlation modeling** — agents don't model cross-asset dependencies

### 12.4 Existing Strengths to Build Upon

1. ✅ **EWMA convergence** — already a belief-update mechanism
2. ✅ **Entropy mixing** — already models market uncertainty/noise
3. ✅ **Extremized log-odds** — already a conviction-scaling mechanism
4. ✅ **Murphy decomposition** — already separates reliability from resolution
5. ✅ **Prediction market anchors** — already uses market prices as calibration
6. ✅ **Agent influence/outcome power** — already maps to capital/signal quality
7. ✅ **Stance polarization metrics** — already measures herding behavior
8. ✅ **Knowledge graph with causal attributes** — already has lead-lag modeling
9. ✅ **Calendar-temporal mode** — already has time-mapped simulation
10. ✅ **Structured forecast extraction** — already produces tradeable signals

---

## 13. FILE INVENTORY (18+ FILES)

| File | Lines | Primary Purpose |
|---|---|---|
| `simulation_runner.py` | ~2090+ | OASIS simulation execution, agent actions, run state management |
| `simulation_manager.py` | ~1544 | Simulation lifecycle, state management, config preparation |
| `simulation_ipc.py` | 732 | IPC command/response protocol between backend and subprocess |
| `agent_dynamics.py` | 405 | Per-agent affective state, interaction signals |
| `decision_channel.py` | 775 | Post-sim WorldState evolution via agent commitments |
| `worldstate.py` | 304 | WorldState class, EWMA convergence, scenario distributions |
| `world_delta.py` | 80 | Inter-round world delta digest |
| `forecast_extractor.py` | 2193+ | Structured forecast extraction, binary/scenario forecasts |
| `forecast_ledger.py` | 436 | Forecast ledger, calibration loop, market resolutions |
| `backtest.py` | 237 | Brier score, calibration, Murphy decomposition |
| `ensemble.py` | 419 | Multi-run forecast aggregation, extremized log-odds |
| `exec_brief.py` | 927 | Executive deliverables builder |
| `requirement_spec.py` | 105 | Forecast brief parser |
| `oasis_profile_generator.py` | 2145+ | Agent profile/persona generation |
| `simulation_config_generator.py` | 2120+ | LLM-driven simulation config generation |
| `run_parallel_simulation.py` | 3490+ | Main simulation loop, agent activation, calendar-temporal |
| `action_logger.py` | 323 | PlatformActionLogger, SimulationLogManager |
| `graphiti_client/` | 8 files | Local Graphiti knowledge graph (Zep replacement) |

---

## 14. CONCLUSION

The DeepResearchForecast codebase is a sophisticated multi-agent social simulation system with strong foundations for quantitative analysis. The core mechanisms — EWMA convergence, extremized log-odds pooling, Murphy decomposition, prediction market anchoring, and knowledge graph reasoning — are directly transferable to a production quant trading system.

The fundamental architectural gap is that this is a **social simulation** (agents communicate on social media) rather than a **market simulation** (agents trade financial instruments). The bridge between these domains is well-defined: replace social actions with market orders, add price discovery and portfolio state, and adapt the existing probabilistic forecasting infrastructure to evaluate trading performance rather than forecast accuracy.

The system is modular enough that the transition can happen incrementally, starting with the market microstructure layer and building up through PnL-based backtesting to real-time execution.

---

*This analysis was produced by systematically reading all 18+ specified files and extracting trading-relevant patterns, mechanisms, data structures, and architectural mappings.*
