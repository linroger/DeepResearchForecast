# DeepResearchForecast — Comprehensive Architecture Map

> **Scope.** Complete, code-grounded architectural map of DeepResearchForecast (a.k.a. **DeepAgentForecast** / **MiroFish**) — an event-based AI quant forecasting platform transforming a single natural-language prediction question into an interactive forecast report through a six-stage pipeline: **RESEARCH → ONTOLOGY → GRAPH → PREPARE → RUN → REPORT**.
>
> Codebase state: commit `6746de3` (Wave 9), with `file:line` references throughout. All paths relative to repo root unless prefixed `backend/`.

---

## TABLE OF CONTENTS

1. [System Topology](#1-system-topology)
2. [Pipeline Stages Deep-Dive](#2-pipeline-stages-deep-dive)
3. [Data Flow](#3-data-flow)
4. [Inter-Stage Contracts](#4-inter-stage-contracts)
5. [Configuration Surface](#5-configuration-surface)
6. [Concurrency Model](#6-concurrency-model)
7. [Persistence Layer](#7-persistence-layer)
8. [External Integrations](#8-external-integrations)
9. [Resilience & Recovery](#9-resilience--recovery)
10. [LLM Provider Abstraction](#10-llm-provider-abstraction)
11. [Key File Map](#11-key-file-map)
12. [Event-Based Quant Trading Relevance](#12-event-based-quant-trading-relevance)

---

## 1. SYSTEM TOPOLOGY

### 1.1 Process Landscape

The system runs as a **Flask web application** that orchestrates multiple long-running subprocesses. Everything is request-driven from a single Flask process.

| Process | What | Launch Mechanism | Communication Channel |
|---------|------|-----------------|----------------------|
| **Flask backend** | API + orchestrator + all pipeline services | `backend/run.py` → `create_app()` (`backend/app/__init__.py:22`), threaded dev server on `FLASK_HOST:FLASK_PORT` (default `127.0.0.1:5001`) | HTTP (polled by frontend) |
| **Vite/Vue frontend** | SPA dashboard | `npm run frontend`, port 3000, proxies `/api` → 5001 | HTTP polling only — **no SSE, no WebSockets** |
| **DeerFlow research** | Deep research per track | `subprocess.Popen(start_new_session=True)` from orchestrator (`pipeline_orchestrator.py:1136`), own venv `deer-flow/backend/.venv` (Python 3.12) | stdout line stream + `handoff/` files + SQLite budget ledger |
| **OASIS simulation** | Dual-platform social sim | `subprocess.Popen(start_new_session=True)` from `SimulationRunner.start_simulation` (`simulation_runner.py:685-695`) | `actions.jsonl` tail + `run_state.json` + file-mailbox IPC |
| **Graphiti runtime** | Local temporal KG | in-process singleton with background asyncio event loop (`graphiti_client/runtime.py:180-201`) | direct calls behind Zep-shaped facade |
| **MCP servers** | `drf-kg`, `drf-simulation` | `python -m app.mcp.kg_server` / `app.mcp.sim_server`, stdio FastMCP | consumed by DeerFlow harness on scenario re-runs |

### 1.2 Thread Model

**Concurrency model: threads + subprocesses, no asyncio in the Flask app.**

- Each pipeline runs on one daemon `threading.Thread`
- Parallel research tracks use `ThreadPoolExecutor` (`pipeline_orchestrator.py:5962-5964`)
- Profile generation uses thread pools
- Graphiti's async API runs on its dedicated background loop
- OASIS subprocesses run their own asyncio loops
- Slow operations: async-job pattern — create in-memory `Task`, spawn daemon thread, return `task_id`, frontend polls `/status`
- Because `Task` objects are in-memory only, every status endpoint also resolves progress from on-disk artifacts so progress survives backend restart

### 1.3 Startup Lifecycle

(`backend/app/__init__.py:55-69`)

1. `SimulationRunner.register_cleanup()` + `reconcile_orphans()` — kill leftover sim processes
2. `PipelineOrchestrator.reconcile_orphans()` + `register_cleanup()` — mark orphaned `running` pipelines failed or salvage as completed if report artifact intact, kill stranded DeerFlow process groups

### 1.4 Security Architecture

(`backend/app/utils/security.py` + `__init__.py:77-121`)

- `before_request` auth gate: OPTIONS/`/health`/non-`/api/` pass; loopback remotes pass; otherwise `X-API-Token` compared with `hmac.compare_digest`, fail-closed 403
- `redact_secrets` masks key-named fields and inline tokens before any logging
- `validate_safe_url` guards SSRF: blocks link-local, multicast/reserved, optionally private/loopback, resolves all A records

### 1.5 Repository Layout

```
DeepResearchForecast/
├── package.json              # npm scripts: dev = concurrently(backend, frontend)
├── .env / .env.example       # the entire config surface (~87KB documented)
├── setup.sh                  # interactive installer
├── scripts/                  # start.sh, doctor.sh, smoke.sh, salvage_orphaned_pipelines.py
├── frontend/                 # Vue 3 + Vite SPA (port 3000)
│   └── src/{views,components,api,router,store,i18n.js}
├── backend/
│   ├── run.py                # Flask entry point
│   ├── scripts/              # OASIS subprocess runners
│   └── app/
│       ├── __init__.py       # app factory, blueprints, auth gate, orphan reconcile
│       ├── config.py         # 1,502-line env-driven Config class
│       ├── api/              # graph.py, simulation.py, report.py, research.py, settings.py, sdk.py
│       ├── models/           # Task (in-memory) + Project (file-backed)
│       ├── mcp/              # kg_server.py, sim_server.py (stdio FastMCP)
│       ├── services/         # the pipeline (orchestrator + ~25 modules)
│       │   └── graphiti_client/  # Zep-SDK-compatible facade → local Graphiti + FalkorDB
│       └── utils/            # llm_client, oasis_llm, actors, telemetry, token_budget, security
├── deerflow_bridge/          # git-tracked research engine overlay
│   ├── deerflow_research.py  # 8,905-line headless driver
│   ├── search_tools.py / cached_fetch.py / market_tools.py / research_budget.py
│   ├── config.yaml / patches/ / skills/
├── deer-flow-2.0.0/          # vendored pristine DeerFlow 2.0 engine
├── deer-flow/                # the ASSEMBLED runtime (gitignored)
└── drf2/                     # older/parallel driver lineage
```

### 1.6 Persistence Layout (all under `backend/uploads/`)

| Entity | Path | Contents |
|--------|------|----------|
| Pipeline | `pipelines/<pipe_id>/` | `pipeline_state.json`, `run.json`, `handoff/` |
| Project | `projects/<proj_id>/` | `project.json`, uploaded `files/`, `extracted_text.txt` |
| Simulation | `simulations/<sim_id>/` | `state.json`, `run_state.json`, `simulation_config.json`, `*_profiles.{csv,json}`, `{twitter,reddit}/actions.jsonl`, `<platform>_simulation.db`, `env_status.json`, `ipc_commands/`, `ipc_responses/`, `world_state_trajectory.json`, `decisions.jsonl`, `emergent_metrics.json`, `run_summary.json`, `llm_health.json` |
| Report | `reports/<rep_id>/` | `outline.json`, `section_NN.md`, `full_report.md`, `forecast.json`, `citations.json`, `final_audit.json`, `viz_manifest.json`, `charts/`, `market_comparison.json`, `agent_log.jsonl`, `console_log.txt`, `progress.json`, `meta.json`, `resolved.json` |
| Graph DB | `graphiti_db/falkor.db` | embedded FalkorDB (one tenant DB per `graph_id`) |
| Ledger | `_forecast_ledger/` | `ledger.jsonl`, `resolutions.jsonl` |

---

## 2. PIPELINE STAGES DEEP-DIVE

### 2.1 Stage Overview & Progress Bands

The orchestrator (`pipeline_orchestrator.py:74-101`) defines stage constants and global-progress bands:

| Stage | Band (full mode) | Band (research_only) |
|-------|-----------------|---------------------|
| `research` | 0–30 | 0–100 |
| `ontology` | 30–40 | — |
| `graph` | 40–60 | — |
| `prepare` | 60–72 | — |
| `run` | 72–92 | — |
| `report` | 92–100 | — |

Bands are dynamically re-derived from observed cost signals via `_recompute_dynamic_bands` (`:4411-4448`), stored in `state.options['dynamic_bands']`.

### 2.2 State Model & Persistence

**`PipelineState`** dataclass (`:210-284`): `pipeline_id, prompt, schema_version(=2), mode, status, global_progress, current_stage, task_id, project_id, graph_id, simulation_id, report_id, handoff_dir, research_pid, owner_pid, owner_boot_id, heartbeat_at, last_progress_at, error, created_at, updated_at, options(dict), stages(dict[str, StageState]), artifacts(dict[str,str])`

**`StageState`** (`:186-206`): `name, status(pending/running/completed/failed/skipped), progress, message, started_at, finished_at, error`

**`PipelineManager`** (`:292-626`) writes `uploads/pipelines/<id>/pipeline_state.json` via `write_json_atomic` (tmp + fsync + `os.replace`) under a per-pipeline `threading.Lock` (`:341-361`).

**Schema versioning**: `PIPELINE_SCHEMA_VERSION = 2`; `load` migrates older files; file newer than running code returns HTTP 409.

### 2.3 Stage 1 — RESEARCH (DeerFlow Bridge)

**Entry conditions**: `POST /api/research/run` validates `depth ∈ {quick,standard,deep}` and `model ∈ SUPPORTED_DEERFLOW_MODELS`.

**Exit conditions**: Research contract promoted atomically (13 files + `charts/` tree); manifest written last; all hashes verified.

**Key files**: `deerflow_bridge/deerflow_research.py` (8,905 lines); `backend/app/services/research_progress.py`

**Key methods**: `PipelineOrchestrator.start()`, `_run_parallel_research_tracks()` (`:5806-6391`), `_promote_research_contract()` (`:1569-1677`), `_finalize_research_contract()` (`:1680-1792`), `ResearchProgressEstimator`

**LLM calls made**:
- Three parallel Track-A evidence-only lanes (base evidence · base rates and analogs · incentives/contrarian/markets)
- One shared Track-B actor-intelligence plane (17 dimensions per actor)
- Global synthesis: outline → multi-part sections → merge (≤2 attempts)
- Report judge (7-dimension scorecard)
- Structured extraction (`actors.json`, `timeline.json`, `quantitative.json`, `contested.json`)
- Deep loop: 5 fixed phases (scope → primary-evidence → actors-and-incentives → contradictions-and-risks → forecast-implications)

**Cost characteristics**: Deepest and most expensive stage. Quick: 900s watchdog / Standard: 2400s / Deep: 10800s. Budget governed by cross-process SQLite ledger (`RESEARCH_MODEL_LEASE_DB`): `ATTEMPTS_GLOBAL=1800`, `SEARCH_GLOBAL=900 / SEARCH_LANE=360`, `FETCH_GLOBAL=450 / FETCH_LANE=180`. Model concurrency `MODEL_CONCURRENCY_GLOBAL=12`, `SUBAGENT_CONCURRENCY_GLOBAL=9`.

**State management**: DeerFlow subprocess writes to `--out-dir` (= `handoff/`). Resume state in `research_checkpoint.json`. Budget tracked in cross-process SQLite ledger injected via env vars. Progress estimated from streamed lifecycle log lines.

**Artifacts produced** (the research contract, `_RESEARCH_CONTRACT_FILES` at `:1484-1490`):

| File | Content |
|------|---------|
| `research_report.md` | Long-form cited dossier (15–25K words merged). `[S<n>]` citations finalized against References section |
| `actor_dossier.md` | Track-B actor-ontology dossier: ranked cast in depth |
| `actors.json` | **Keystone artifact**: actors, relationships, situation_brief, key_events, quantitative_facts, contested_claims, sources, as_of_date |
| `sources.json` | Citation ledger grounded in URLs actually fetched; S1–S4 tier histogram, staleness, jurisdiction diversity |
| `timeline.json` | Key events with dates |
| `quantitative.json` | Quantitative facts with ~1000× unit-scale reconciliation warnings |
| `contested.json` | Contested claims with positions |
| `prediction_markets.json` | Relevance-gated market snapshot |
| `market_price_history.json` | 90-day price series |
| `charts.json` + `charts/` | Research Visual Annex PNGs |
| `meta.json` | Status, model, depth, thread_id, phase budgets, research_quality, degradation flags |
| `research_progress.log` | Streamed lifecycle/tool/usage lines |
| `prediction_requirement.txt` | The verbatim brief |
| `research_checkpoint.json` | Resume state |
| `evidence_pack.md` | Per-lane output in `--evidence-only` mode |

### 2.4 Stage 2 — ONTOLOGY

**Entry conditions**: Research contract validated; `actors.json` and `research_report.md` exist with verified hashes.

**Exit conditions**: `ontology.json` written to `handoff/`; `Project.ontology` persisted.

**Key files**: `backend/app/services/ontology_generator.py`; orchestrated at `pipeline_orchestrator.py:6697-6777`

**Key classes/methods**: `OntologyGenerator().generate(...)` receives `document_texts=[actor_dossier_md, research_report_md]`, `central_question`, `actors` dict, auto-selected template. Prompt (`ontology_generator.py:31-120`) demands exactly 10 entity types + 6–10 edge types.

**LLM calls made**: Single LLM call deriving entity/edge type schema. With `ONTOLOGY_RICH_SCHEMA` on, each entity carries archetype + simulation tier; each edge carries family + valence.

**State management**: A `Project` is created and seeded with the research report as extracted text. Output persisted to `project.ontology` and `handoff/ontology.json`.

**Cost characteristics**: Cheap — one LLM call. Sub-10s typical.

### 2.5 Stage 3 — GRAPH (Local Graphiti Temporal KG)

**Entry conditions**: Ontology validated; `actors.json` available for deterministic seeding.

**Exit conditions**: Graph built, communities detected, entities resolved, graph pruned to ≤400 nodes, structural priors computed, `handoff/graph_priors.json` written.

**Key files**:
- `backend/app/services/graph_builder.py` — `GraphBuilderService`
- `backend/app/services/graphiti_client/` — drop-in Zep-SDK-compatible facade
- `backend/app/services/graphiti_client/runtime.py` — `GraphitiRuntime` singleton
- `backend/app/services/zep_entity_resolver.py` — entity resolution / dedup
- `backend/app/services/graph_pruner.py` — the 400-node cap
- Orchestrated at `pipeline_orchestrator.py:6779-7063`

**Build sequence**:

1. **Create** — `create_graph` mints `graph_id = f"mirofish_{uuid4().hex[:16]}"` (`graph_builder.py:687-697`)
2. **Ontology → dynamic Pydantic models** — `set_ontology` `type()`-creates `EntityModel`/`EdgeModel` subclasses from ontology JSON
3. **Actor seeding (pre-text)** — `seed_actors` writes research-confirmed actors/relationships as typed triplets anchored at validated `as_of` date before prose extraction
4. **Chunk + episode ingest** — dossier text → `TextProcessor.split_text` (500-char chunks, 50 overlap) → `add_text_batches` (`graph_builder.py:963-1065`)
5. **Community detection** — `build_communities` (Leiden + LLM summaries) → `handoff/communities.json`
6. **Entity resolution / dedup** — `resolve_entities` with cosine ≥ `GRAPH_RESOLVE_SIM_THRESHOLD` (0.88); dossier aliases bypass cosine gate as authoritative ground truth
7. **Pruning** — `plan_prune` / `prune_graph` to ≤400 nodes
8. **Structural priors** — degree centrality, optional betweenness + articulation points → `graph_priors.json`
9. **Concurrency sanity** — duplicate-name detection under concurrent builds (`GRAPH_BUILD_CONCURRENCY=1`)

**The Graphiti facade** (`graphiti_client/`):
- `client.py` — reproduces the exact `client.graph.*` surface; returns `_ZepNode`/`_ZepEdge`/`_ZepEpisode` wrappers mirroring Zep attribute names
- `runtime.py` — `GraphitiRuntime` singleton: persistent asyncio loop on background thread with per-op wall-clock timeout `GRAPHITI_OP_TIMEOUT_S`; one cached `Graphiti` instance per `graph_id`; per-graph write lock serializes search→resolve→write dedup
- Storage backends (`GRAPH_BACKEND`, default `auto`): `falkordblite` (embedded FalkorDB via `redislite.AsyncFalkorDB` — the default) → external FalkorDB server → `kuzu` (embedded file fallback). DB at `uploads/graphiti_db/falkor.db`
- LLM/embedder: `AppGraphitiLLMClient` wrapping the app's `LLMClient`; embedder = local sentence-transformers `paraphrase-multilingual-MiniLM-L12-v2` (384-dim); Reranker = `NoOpCrossEncoder` (RRF recipes do ranking) or BGE via `GRAPHITI_RERANKER=bge`
- **falkordblite bug workaround**: `WHERE` property predicates silently dropped under `ORDER BY+LIMIT`; compensated with zero-predicate full scans + Python-side dedup/pagination

**Simulation→graph feedback loop**: `zep_graph_memory_updater.py` (`GraphMemoryUpdater`): when `SIM_GRAPH_FEEDBACK` is on, each simulation agent action converts to a natural-language episode and fed back into the same graph via a worker queue with a dead-letter file (`_zep_dead_letter/<graph_id>.jsonl`). At RUN completion a "confluence barrier" joins the monitor thread and flushes `ZepGraphMemoryManager.stop_updater`.

**Cost characteristics**: Graphiti extraction uses the configured LLM provider per episode. Embeddings are local (no cost). `add_episode` is synchronous. Skip ratio > `GRAPH_MAX_SKIPPED_RATIO` (0.3) triggers `graph_ingest_degraded`.

### 2.6 Stage 4 — PREPARE (Cast, Personas, Sim Config)

**Entry conditions**: Graph built and pruned; `actors.json` available; ontology validated.

**Exit conditions**: All actor personas generated, simulation config produced, `simulation_config.json` written and SHA-256 sealed, `actor_cast_manifest.json` fingerprinted, state `READY`.

**Key files**: `backend/app/services/simulation_manager.py`, `oasis_profile_generator.py`, `simulation_config_generator.py`, `actor_role_prompt.py`; orchestrated at `pipeline_orchestrator.py:7065-7174`

**Cast selection** (`ACTOR-CAST discipline`):
- `ZepEntityReader.filter_defined_entities` reads graph nodes and keeps only ontology-defined, agent-eligible entities
- `ensure_dossier_actor_entities` (`simulation_manager.py:33`) guarantees a graph node or stand-in for every eligible `actors.json` row
- `select_agent_pool` (`:130`) enforces cast discipline (`ACTOR_CAST_MAX=20 < OASIS_MAX_AGENTS=80`): pool derives **only from the main cast** — entities matched to a research actor that pass tier-1/2 agency gate — ranked by `(matched, eligible, salience×tier_weight + 0.5·centrality_prior, influence, edge_count)`
- Media/observers demoted to tier 3 and excluded (`ACTOR_EXCLUDE_MEDIA`)
- Cheap filler audience agents generated procedurally with zero LLM cost (`SIM_AUDIENCE_AGENTS`, `generate_audience_profiles`, `:846-874`)
- Archetype/tier machinery in `utils/actors.py`: `entity_archetype`, `entity_simulation_tier`, `is_agent_eligible`, `salience_score`, `is_media_entity`, `match_actor`

**Deterministic role contracts** (no LLM):
- `build_actor_role_contract` (`:290`) assembles identity/objectives/incentives/constraints/resources/vulnerabilities/incident relationships/beliefs/red lines/uncertainty — labeling missing facts as *missing* rather than guessing
- `compile_actor_role_prompt` (`:464`) renders a ≤6,000-char "ROLE BRIEF" wrapped in `BEGIN/END UNTRUSTED DOSSIER DATA` delimiters
- **Prompt-injection defense**: `_UNSAFE_CONTROL_PATTERNS` (`:24`) strips instruction-like dossier text; `sanitize_untrusted_dossier` cleans recursively
- Every prompt SHA-256'd (`role_prompt_sha256`); coverage validated against cast manifest; runner refuses to launch if role prompts don't match manifest (fail-closed)

**Persona assembly** (`oasis_profile_generator.py`):
- `generate_profile_from_entity` (`:305`) builds an LLM base persona from entity's Zep ego-network context
- Enriched by `actor_briefing` / `behavioral_dna_block` / `roster_block`
- Appends the role contract
- `OasisAgentProfile` serializes to OASIS's exact formats: `to_twitter_format` → CSV (`user_id,name,username,user_char,description`), `to_reddit_format` → JSON keyed by `user_id`
- Generation is parallel (`ThreadPoolExecutor`; 16 for HTTP via `PARALLEL_PROFILE_COUNT`, 3 for CLI), order-preserving, incremental-saving, with rule-based fallback

**Simulation config generation** (`simulation_config_generator.py` `generate_config` (`:398`)):
- Stepwise (avoiding one fragile mega-call): `TimeSimulationConfig` → `EventConfig` → per-agent activity (batched 15 at a time) → initial post → agent assignment → platform weights
- Serialized to `simulation_config.json` (atomic write)

**Cost characteristics**: Moderate — one LLM call per actor for persona generation (parallelized) + one for simulation config. For 20 actors, ~21 LLM calls.

### 2.7 Stage 5 — RUN (OASIS Dual-Platform Simulation)

**Entry conditions**: All preparation artifacts validated and sealed; `simulation_config.json` integrity verified against `simulation-config-manifest/v1`.

**Exit conditions**: Both platforms complete (or `max_rounds` reached); `run_state.json` reflects completion; `env_status.json` = stopped.

**Key files**: `backend/app/services/simulation_runner.py` (~1700 lines); `backend/scripts/run_parallel_simulation.py`; `backend/scripts/action_logger.py`; `backend/app/services/simulation_ipc.py`; `backend/app/services/zep_graph_memory_updater.py`

**Launch chain**:
- `SimulationRunner.start_simulation()` computes `total_rounds = total_hours*60/minutes_per_round` (optionally capped by `max_rounds`)
- Picks a script (`run_parallel`/`run_twitter`/`run_reddit`) and launches via **`subprocess.Popen`** with `cwd=sim_dir`, UTF-8 env, stdout/stderr → `simulation.log`, `start_new_session=True`
- Spawns a **daemon monitor thread** that tails `actions.jsonl` every 2s, parsing each JSONL record into the live `SimulationRunState` (`run_state.json`)
- If graph-memory updating enabled, each parsed action forwarded to `ZepGraphMemoryUpdater`

**OASIS subprocess internals** (`run_parallel_simulation.py`):
1. Monkey-patches `open()` to default UTF-8, silences OASIS's verbose loggers, loads `.env`
2. Builds an **agent graph** per platform from profiles
3. `oasis.make(...)` creates the environment with a fresh SQLite DB and concurrency semaphore (3 for CLI, 30 for HTTP)
4. `env.reset()`, injects `initial_posts` as `ManualAction`s (round 0)
5. **Round loop**: computes simulated hour/day, picks active agents via `get_active_agents_for_round` (gated by `active_hours × activity_level`), issues `{agent: LLMAction()}`, `await env.step(actions)`
6. Twitter and Reddit run **concurrently** via `asyncio.gather`
7. When loop finishes the env is **not closed** — process enters **wait-for-commands mode**, polling IPC command dir

**Dual stall watchdogs**: An inline poll-loop check plus an independent disk-reading watchdog thread; both force-stop a wedged sim after `PIPELINE_RUN_STALL_S` (default 1800s).

**Calendar-temporal simulation**: Each round is one even calendar unit between the research as-of date and the horizon. `"by 2030"` → 18 quarterly rounds, `"by 2035"` → 19 half-year rounds. Dated events fire in their true rounds.

**Cost characteristics**: Dominated by per-round LLM calls across all agents. Each round = N agents × 2 platforms × 1 LLM call. Controlled by `OASIS_SEMAPHORE` (30 for HTTP, 8 for CLI).

### 2.8 Stage 6 — REPORT (Forecast Synthesis & Publication)

**Entry conditions**: Simulation complete (or research-only mode); `simulation_id` available.

**Exit conditions**: `full_report.md` + `forecast.json` + `citations.json` + `final_audit.json` produced; publication gate passed (SHA fingerprint verified); `TaskManager` terminal result set.

**Key files**: `backend/app/services/report_agent.py`, `forecast_extractor.py`, `forecast_ledger.py`, `backtest.py`, `ensemble.py`, `exec_brief.py`, `requirement_spec.py`, `agent_dynamics.py`, `worldstate.py`, `decision_channel.py`, `world_delta.py`

**Report generation** (`report_agent.py`):
- **Spine-first**: `plan_outline` produces a 2-5 section JSON outline
- For each section, `_generate_section_react` loops (≤5 iterations, **≥3 tool calls required**): the LLM emits either a tool call or a Final Answer; the agent executes one tool per turn, feeds observation back, only accepts a Final Answer once enough evidence is gathered
- **Contamination defence** (`_looks_contaminated`): rejects sections leaking Claude Code system-prompt text, leftover tool-call framing, interview-timeout strings
- `chat()` is a lightweight 2-iteration ReAct over the finished report
- Native function/tool calls on capable providers; ReAct text fallback elsewhere
- `insight_forge` path retrieves from graph + simulation diagnostics before writing

**Forecast finalization**:
- `forecast_extractor.py` turns prose into machine-readable structured forecast: scenarios with calibrated probabilities, key drivers, resolution criteria
- `ensemble.py` aggregates N seeds into frequency-derived scenario probabilities with spread and inter-run agreement
- `backtest.py` scores resolved forecasts (Brier score, log-loss, calibration report)
- `forecast_ledger.py` appends every forecast to a jsonl ledger keyed by horizon/resolution date
- `decision_channel.py` post-simulation: elicits agent commitments, weights by outcome power, steps the WorldState
- `worldstate.py` — base-rate-seeded distribution evolved by resource-weighted commitments with EWMA convergence tracking
- `world_delta.py` — qualitative inter-round digest (no numeric shares in agent-facing text)

**Publication gate**: Read-only, SHA-fingerprinted. Exact report/forecast/audit hashes must match. Editor lint → citations → hard audit → sealed.

**Cost characteristics**: The most variable stage. Each section requires ≥3 tool calls (graph retrieval) + 1 LLM generation. Report LLM preflight aborts in <60s if both providers down. Budget enforcement via `LLM_RUN_BUDGET_TOKENS`/`LLM_RUN_BUDGET_USD`.

**Post-report deliverables**:
- `exec_brief.py` — deterministic executive deliverables (no LLM): `exec_brief.md`, `exec_brief.pdf`, `digest.md`
- `requirement_spec.py` — parses the brief into machine-readable output contract (language, binary forecast count, page budget)

---

## 3. DATA FLOW

### 3.1 Every Artifact That Moves Between Stages

```
User prompt
    │
    ▼
┌─── Stage 1: RESEARCH ──────────────────────────────────────┐
│  Input: prediction_requirement.txt (verbatim brief)              │
│  Output: handoff/ (13+ files)                                   │
│    ├── research_report.md ──────────────────┐                  │
│    ├── actors.json ─────────────────────────┤── keystone       │
│    ├── sources.json ────────────────────────┤                  │
│    ├── timeline.json ───────────────────────┤                  │
│    ├── quantitative.json ───────────────────┤                  │
│    ├── contested.json ──────────────────────┤                  │
│    ├── prediction_markets.json ─────────────┤                  │
│    ├── actor_dossier.md ────────────────────┘                  │
│    ├── meta.json, charts.json + charts/, research_checkpoint.json│
│    ├── prediction_requirement.txt, research_progress.log        │
│    └── manifest.json (SHA-256 of all files)                     │
└────────────────────────────────────────────────────────────────┘
    │  handoff/manifest.json (SHA-256 verified)
    ▼
┌─── Stage 2: ONTOLOGY ──────────────────────────────────────┐
│  Input: actors.json + research_report.md                       │
│  Output: ontology.json                                            │
│    ├── entity_types[] (10 types, archetype + tier)            │
│    └── edge_types[] (6-10, family + valence)                │
└────────────────────────────────────────────────────────────────┘
    │  ontology.json → graph.set_ontology()
    ▼
┌─── Stage 3: GRAPH ─────────────────────────────────────────┐
│  Input: actors.json (seeding) + research_report.md (prose)   │
│  Output: graph_priors.json + communities.json + entity_merges.json │
│    ├── Local Graphiti DB (embedded FalkorDB)                     │
│    │   ├── actor nodes (seeded pre-text)                       │
│    │   ├── prose-extracted entity/edge nodes                   │
│    │   ├── community assignments                                │
│    │   └── structural priors (centrality)                       │
│    └── handoff/graph_priors.json                               │
└────────────────────────────────────────────────────────────────┘
    │  graph_id → simulation_manager
    ▼
┌─── Stage 4: PREPARE ───────────────────────────────────────┐
│  Input: graph nodes + actors.json + ontology                 │
│  Output: simulation_dir/                                         │
│    ├── twitter_profiles.csv (user_char = sealed role)        │
│    ├── reddit_profiles.json (persona = sealed role)          │
│    ├── simulation_config.json (atomic, SHA-sealed)          │
│    ├── actor_cast_manifest.json (SHA fingerprinted)         │
│    ├── actor_context_manifest.json (v1 context packs)        │
│    └── role_manifest_sha256 (per-profile)                    │
└────────────────────────────────────────────────────────────────┘
    │  simulation_id → SimulationRunner
    ▼
┌─── Stage 5: RUN ───────────────────────────────────────────┐
│  Input: simulation_dir/ (profiles + config)                    │
│  Output: simulation artifacts                                  │
│    ├── twitter/actions.jsonl + reddit/actions.jsonl          │
│    ├── twitter_simulation.db + reddit_simulation.db (SQLite) │
│    ├── run_state.json (round counter, simulated hours)       │
│    ├── world_state_trajectory.json                             │
│    ├── decisions.jsonl (if DECISION_CHANNEL)                 │
│    ├── emergent_metrics.json, llm_health.json, env_status.json│
└────────────────────────────────────────────────────────────────┘
    │  simulation_id → ReportAgent
    ▼
┌─── Stage 6: REPORT ────────────────────────────────────────┐
│  Input: graph (retrieval) + simulation (diagnostics) + research │
│  Output: reports/<rep_id>/                                     │
│    ├── outline.json, section_NN.md, full_report.md           │
│    ├── forecast.json (scenarios × probabilities)             │
│    ├── citations.json, final_audit.json                       │
│    ├── viz_manifest.json + charts/ (Plotly HTML + PNG)       │
│    ├── market_comparison.json, agent_log.jsonl              │
│    ├── progress.json, meta.json, resolved.json               │
│    ├── exec_brief.md / exec_brief.pdf / digest.md           │
│    └── ensemble_forecast.json (if N_FORECAST_SEEDS > 1)    │
└────────────────────────────────────────────────────────────────┘
```

### 3.2 Artifact Lifecycle & Format Summary

| Artifact | Format | Stage Produced | Stage Consumed | Lifetime |
|----------|--------|---------------|---------------|----------|
| `research_report.md` | Markdown | RESEARCH | ONTOLOGY, GRAPH, REPORT | Permanent |
| `actors.json` | JSON | RESEARCH | ONTOLOGY, GRAPH, PREPARE | Permanent |
| `sources.json` | JSON | RESEARCH | REPORT | Permanent |
| `ontology.json` | JSON | ONTOLOGY | GRAPH | Permanent |
| Graph DB (FalkorDB) | Binary | GRAPH | PREPARE, REPORT | Permanent |
| `graph_priors.json` | JSON | GRAPH | PREPARE | Permanent |
| `twitter_profiles.csv` | CSV | PREPARE | RUN | Permanent |
| `reddit_profiles.json` | JSON | PREPARE | RUN | Permanent |
| `simulation_config.json` | JSON | PREPARE | RUN | Permanent |
| `actions.jsonl` | JSONL | RUN | REPORT | Permanent |
| `*_simulation.db` | SQLite | RUN | REPORT | Permanent |
| `run_state.json` | JSON | RUN | REPORT | Permanent |
| `forecast.json` | JSON | REPORT | Forecast ledger, backtest, ensemble | Permanent |
| `full_report.md` | Markdown | REPORT | Publication, PDF, exec_brief | Permanent |

---

## 4. INTER-STAGE CONTRACTS

### 4.1 The Universal Handoff File Contract

Every pipeline directory has a `handoff/` subdirectory that serves as the **universal inter-stage interface**. Every artifact is checksummed into a `manifest.json`, which enables:
- **Resume** (reuse completed stages)
- **Salvage** (recover from failures)
- **Scenario forking** (branch at any stage)
- **Research-only → full continuation**

### 4.2 Manifest Schema

`handoff/manifest.json` contains SHA-256 hashes for every declared artifact:
- Every stage's outputs declared in `_stage_artifact_specs` (`pipeline_orchestrator.py:4920-4974`)
- Hashes computed by `_manifest_entry_for` (`:3127`)
- On resume, `_reuse_ok`/`_validate_reuse` (`:5180-5254`) re-verifies hashes
- A mismatch forces a rebuild and stamps `state.options['resumed_stage_validation']`
- GRAPH reuse has a **0-entity health probe** via `ZepEntityReader` (`:6792-6805`)
- REPORT reuse keyed on **the deliverable itself**, not stage status (`:7321-7377`)

### 4.3 Research Contract (Atomic Multi-File Promotion)

Because a partially-written handoff would poison every downstream stage, promotion is **transactional** (`pipeline_orchestrator.py:1569-1792`):

1. `_promote_research_contract` (`:1569-1677`): staged copy → rollback dir → per-file `os.replace` → manifest written **last** → validate; full rollback on any exception
2. `_finalize_research_contract` (`:1680-1792`): builds a private finalized copy so post-processing cannot invalidate already-published checksums
3. `_validate_research_contract` (`:1525-1566`): byte/SHA match, report ≥400 chars, no stray files, exact charts set; path-traversal guarded

### 4.4 Simulation Config Seal

`simulation_config.json` is sealed with `simulation-config-manifest/v1` (`simulation_manager.py:build_simulation_config_seal`):
- SHA-256 of exact bytes
- References `actor_cast_manifest.json`, `actor_context_manifest.json`, all `actor_role_manifests`
- Runner refuses to launch if seals don't match (fail-closed)
- Child re-validates seals and attests final bytes before first model action

### 4.5 Actor-Intelligence Seals (Current v1)

| Boundary | Authority |
|----------|-----------|
| Stage 1→2 | `actor-intelligence/v1` schema with claim receipts, 17 dimensions |
| Stage 2→3 | `actor-graph-seed-manifest/v1` — deterministic actor/type/alias/relationship UUIDs + attributes |
| Stage 3→4 | `actor-context/v1` pack per actor — epistemic split (public/documented/known/inferred/contested/unknown) + typed gap audit |
| Stage 4→5 | `actor-role/v2` — sole behavioral profile authority; Twitter `user_char`, Reddit `persona` |
| Stage 5→6 | `simulation-config-manifest/v1` — exact config bytes + all cast/context/role/profile bindings |

### 4.6 Research Intra-Stage Resume

If `research_checkpoint.json` exists, `--resume` is passed to DeerFlow. `ResearchCheckpointer` manages thread_id reuse when `question_hash` + depth match. Completed passes are skipped inside the run.

### 4.7 Report Reuse Keyed on Deliverable

REPORT reuse keyed on the deliverable itself, not stage status:
- Resolves existing report by `report_id` or `get_report_by_simulation`
- Rejects broken deliverables via `_assess_report_health` — preventing "reuse bad report → health gate fails → resume loops forever"

---

## 5. CONFIGURATION SURFACE

### 5.1 The Single Config Class

All configuration lives in `backend/app/config.py` — a **1,502-line env-driven `Config` class**. Everything reads from `.env` via `dotenv.load_dotenv()`.

### 5.2 Key Configuration Categories

#### LLM Provider Selection
| Config Key | Default | Description |
|-----------|---------|-------------|
| `LLM_PROVIDER` | `claude-cli` | `claude-cli`, `codex-cli`, `openai`, `kimi`, `minimax`, `deepseek`, `qwen`, `glm` |
| `LLM_API_KEY` | — | API key for OpenAI-compatible providers |
| `LLM_MODEL_NAME` | provider-specific | Model name |
| `LLM_BASE_URL` | provider-specific | Base URL override |
| `LLM_FAST_MODEL` | — | Fast tier model for structured decomposition |
| `LLM_STRONG_MODEL` | — | Strong tier model for synthesis |
| `LLM_TIERED_ROUTING` | `True` | Route mechanical calls to fast, synthesis to strong |

#### Context & Budget
| Config Key | Default | Description |
|-----------|---------|-------------|
| `LLM_RUN_BUDGET_TOKENS` | `0` (unlimited) | Per-run token budget |
| `LLM_RUN_BUDGET_USD` | `0` (unlimited) | Per-run cost budget |
| `LLM_OUTAGE_HALT_CONSECUTIVE` | `10` | Consecutive provider failures → halt pipeline |
| `LLM_COST_PER_MTOK` | — | Per-provider `$/Mtok` cost overrides |
| `ADAPTIVE_CONTEXT` | `True` | Dynamic context budgeting by provider window |
| `RESERVED_COMPLETION_TOKENS` | `8192` | Tokens reserved for output |
| `PROVIDER_CONTEXT_WINDOWS` | see config | Per-provider context windows (128K–1M) |
| `DEFAULT_CONTEXT_WINDOW` | `32000` | Fallback for unknown providers |

#### Graph / Knowledge Graph
| Config Key | Default | Description |
|-----------|---------|-------------|
| `GRAPH_BACKEND` | `auto` | `auto` \| `falkordblite` \| `kuzu` \| `falkordb` |
| `GRAPHITI_DATA_DIR` | `backend/uploads/graphiti_db` | Graph DB location |
| `GRAPHITI_EMBED_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | Embedding model |
| `GRAPHITI_EMBED_DIM` | `384` | Embedding dimensions |
| `GRAPHITI_RERANKER` | `rrf` | `rrf` \| `bge` |
| `FALKORDB_HOST` | — | External FalkorDB server |
| `FALKORDB_PORT` | `6379` | External FalkorDB port |
| `GRAPH_MAX_SKIPPED_RATIO` | `0.3` | Max chunk ingest skip ratio |
| `GRAPH_MAX_ENTITIES` | `400` | Pruning cap |
| `GRAPH_CORE_ACTOR_HOPS` | `2` | BFS depth from core actors |
| `GRAPH_RESOLVE_SIM_THRESHOLD` | `0.88` | Cosine similarity for entity dedup |

#### Research (DeerFlow)
| Config Key | Default | Description |
|-----------|---------|-------------|
| `DEERFLOW_RESEARCH_DEPTH` | `standard` | `quick` \| `standard` \| `deep` |
| `RESEARCH_PARALLEL_TRACKS` | `3` | Number of parallel evidence lanes |
| `RESEARCH_FANOUT_WIDTH` | `8` | Per-KIQ fan-out width |
| `ACTOR_CAST_MAX` | `20` | Max actors in cast (legacy cap) |
| `RESEARCH_SEARCH_CACHE_TTL_H` | `6` | Search cache TTL |
| `RESEARCH_SOURCE_CACHE_TTL_H` | `72` | Fetch cache TTL |

#### Simulation (OASIS)
| Config Key | Default | Description |
|-----------|---------|-------------|
| `OASIS_SEMAPHORE` | `30` | HTTP provider concurrency |
| `OASIS_CLI_SEMAPHORE` | `8` | CLI provider concurrency |
| `SIM_AUDIENCE_AGENTS` | — | Number of filler audience agents |
| `SIM_GRAPH_FEEDBACK` | — | Enable simulation→graph feedback |
| `SIM_DECISION_CHANNEL` | — | Enable post-simulation decision channel |
| `SIM_AGENT_DYNAMICS` | — | Enable per-agent affective-state dynamics |
| `PIPELINE_RUN_STALL_S` | `1800` | Max seconds before wedged sim killed |
| `SIM_TEMPORAL_MODE` | — | `calendar` (default) or `hours` |

#### Report & Forecast
| Config Key | Default | Description |
|-----------|---------|-------------|
| `N_FORECAST_SEEDS` | `1` | Number of ensemble seeds |
| `FORECAST_PROB_FLOOR` | `0.0` | Minimum probability per scenario |
| `REPORT_STRUCTURED_FORECAST` | — | Enable machine-readable forecast extraction |
| `REPORT_EXEC_BRIEF` | — | Enable executive deliverables generation |
| `ENSEMBLE_ALIGN_MIN_OVERLAP` | `0.34` | Scenario alignment Jaccard threshold |

#### Security & Ops
| Config Key | Default | Description |
|-----------|---------|-------------|
| `APP_API_TOKEN` | — | API token for non-loopback access |
| `APP_CORS_ORIGINS` | localhost:3000,5001 | CORS origin whitelist |
| `APP_BLOCK_PRIVATE_URLS` | `False` | Block private/loopback outbound URLs |
| `LLM_TELEMETRY_ENABLED` | `True` | Process-wide LLM meter |
| `LLM_CACHE_ENABLED` | `True` | Content-addressed LLM response cache |
| `FLASK_DEBUG` | `False` | Flask debug mode (dev only) |
| `FLASK_HOST` | `0.0.0.0` | Flask host |
| `FLASK_PORT` | `5001` | Flask port |

### 5.3 `.env.example` Structure

The `.env.example` (~87KB documented) covers all provider configurations. Key sections:
- **LLM Provider**: `claude-cli` (default, no key), `codex-cli` (no key), `openai`/`kimi`/`minimax`/`deepseek`/`qwen`/`glm` (API key required)
- **Knowledge Graph**: `GRAPH_BACKEND`, `GRAPHITI_DATA_DIR`, `GRAPHITI_EMBED_MODEL/DIM`, `GRAPHITI_RERANKER`, `FALKORDB_HOST/PORT`
- **Text Chunking**: `DEFAULT_CHUNK_SIZE=2500`, `DEFAULT_CHUNK_OVERLAP=250`
- **Flask**: `FLASK_DEBUG`, `FLASK_HOST`, `FLASK_PORT`
- **LLM Boost**: Optional dual-LLM acceleration for OpenAI
- **OASIS Concurrency**: `OASIS_SEMAPHORE`, `OASIS_CLI_SEMAPHORE`
- **DeerFlow**: `DEERFLOW_DIR`, `DEERFLOW_MODEL`, depth budget, parallel tracks
- **Research Budget**: Attempts, searches, fetches caps per scope

---

## 6. CONCURRENCY MODEL

### 6.1 Thread Pools

| Pool | Purpose | Configuration |
|------|---------|---------------|
| `ThreadPoolExecutor` (research tracks) | Parallel DeerFlow research lanes | `thread_name_prefix="research-track"`, bounded by `RESEARCH_PARALLEL_TRACKS` (default 3) |
| `ThreadPoolExecutor` (profile generation) | Parallel persona assembly | `PARALLEL_PROFILE_COUNT` = 16 for HTTP, 3 for CLI |
| `ThreadPoolExecutor` (decision channel) | Parallel round elicitation | Bounded, two-phase elicit→replay |
| `ThreadPoolExecutor` (graph LLM I/O) | Graphiti extraction I/O | `GRAPH_LLM_EXECUTOR_WORKERS=64` |
| `ThreadPoolExecutor` (sim interview) | Agent interviews | Bounded by `≤6 agents`, 600s timeout |

### 6.2 Subprocess Management

| Subprocess Type | Launch | Management |
|----------------|--------|------------|
| **DeerFlow research** | `subprocess.Popen(start_new_session=True)` | `cwd=deerflow_dir`, stdout=PIPE, stderr=STDOUT, depth-scaled watchdog, `threading.Timer`, `_cancel_watcher` thread, `os.killpg` for cancellation |
| **OASIS simulation** | `subprocess.Popen(start_new_session=True)` | `cwd=sim_dir`, stdout/stderr → `simulation.log`, `start_new_session=True`, daemon monitor thread, dual stall watchdogs |

### 6.3 Sync→Async Bridge

The Flask app is synchronous but Graphiti is async. The bridge lives in `graphiti_client/runtime.py:180-201`:
- A **persistent asyncio event loop** on a background thread
- Per-op wall-clock timeout `GRAPHITI_OP_TIMEOUT_S` that cancels wedged coroutines
- The per-graph write lock cannot deadlock because wedged ops are cancelled
- All Graphiti coroutines run through this bridge

### 6.4 Lock Patterns

| Lock | Scope | Purpose |
|------|-------|---------|
| `threading.Lock` (per-pipeline) | `PipelineManager` | Serializes `save`, heartbeat `touch_heartbeat`, terminal `mark_failed`/`mark_salvaged_completed` — lost-update prevention |
| Per-graph write lock | `GraphitiRuntime` | Serializes search→resolve→write dedup sequence |
| `_console_handler_lock` | `ReportAgent` | Serializes FileHandler add/remove/close (concurrency fix) |
| `_ACTIVE_LOCK` | `LLMMeter` | Thread-safe active run registration |

### 6.5 Context Management

- `contextvars` (`_current_run`, `_current_stage`) tag every LLM call with run/stage attribution
- **Critical caveat**: `ThreadPoolExecutor` does not inherit `contextvars`, so worker-thread calls leak into the `_global` bucket (warned at 20/100/500/2000 calls)
- `_ACTIVE_RUNS` registry compensates: when exactly one run is active, unattributed calls are attributed to it
- `set_run_context(run_id, stage)` must be called explicitly in each worker

### 6.6 OASIS Internal Concurrency

Inside the OASIS subprocess:
- Twitter and Reddit run concurrently via `asyncio.gather`
- Each platform has its own `PlatformActionLogger` writing to `actions.jsonl`
- Agent concurrency capped by semaphore (3 for CLI, 30 for HTTP)
- Each agent's `active_hours × activity_level` gates participation per round
- A **wait-for-commands mode** after simulation loop (IPC server)

---

## 7. PERSISTENCE LAYER

### 7.1 Graphiti / FalkorDB

**Primary storage**: Embedded FalkorDB via `redislite.AsyncFalkorDB` (`falkordblite` package).
- One tenant database per `graph_id`
- `graph_id` doubles as FalkorDB tenant name AND Graphiti `group_id`
- DB file at `backend/uploads/graphiti_db/falkor.db`
- **No Docker, no server, no API key**
- Same engine Zep Cloud was built on

**Graphiti features used**:
- Temporal knowledge graph with bi-temporal anchors (`valid_at`, `invalid_at`/`expired_at`/`created_at`)
- Episode-based ingestion (text chunks → episodes)
- Entity/edge extraction via LLM (provider-configured)
- Sentence-transformer embeddings (local)
- Hybrid search (RRF/MMR/cross-encoder + node_distance)
- Community detection (Leiden)
- Node/edge merge
- Causal path traversal (`causal_paths`, `n_hop_subgraph`)

**Storage backend selection** (`GRAPH_BACKEND`):
1. `falkordblite` (default) — embedded, no external dependency
2. External FalkorDB server (if `FALKORDB_HOST` set)
3. `kuzu` — embedded file fallback

**Known bugs/workarounds**:
- `WHERE` property predicates silently dropped under `ORDER BY+LIMIT` → compensated with zero-predicate full scans + Python-side dedup/pagination
- Graphiti datetimes normalize to ISO strings at boundary
- Episodes always report `processed=True` (synchronous ingest)

### 7.2 File-Based Storage

All durable state is file-based under `backend/uploads/`.

**Atomic writes**: `backend/app/utils/atomic.py` — `write_json_atomic` (tmp + fsync + `os.replace`), `write_text_atomic`.

**File-based IPC** (for OASIS communication):
- `SimulationIPCClient` (Flask side) writes `<command_id>.json` into `<sim>/ipc_commands/`
- Polls `<sim>/ipc_responses/` for matching reply
- `SimulationIPCServer` (script side) polls for commands, executes, writes responses
- Commands: `interview`, `batch_interview`, `close_env`
- `env_status.json` tracks `alive`/`stopped`

**SQLite databases**:
- `deerflow_bridge/research_budget.py` — cross-process budget ledger (atomic SQLite admission with per-scope caps)
- `<platform>_simulation.db` — per-platform OASIS SQLite
- `_forecast_ledger/ledger.jsonl` — jsonl (not SQLite, for append-only simplicity)

**In-memory models**:
- `Task` / `TaskManager` — in-memory singleton, thread-safe (`PENDING→PROCESSING→COMPLETED/FAILED`, progress 0-100). Lost on restart.
- `Project` / `ProjectManager` — file-backed under `uploads/projects/<id>/`

### 7.3 State Persistence Flow

```
PipelineState (dataclass)
    │
    ├── write_json_atomic(pipeline_state.json)  ← per-pipeline lock
    │
    ├── TaskManager (in-memory) → /status endpoint
    │   └── Fallback: resolves progress from on-disk artifacts
    │
    ├── PipelineManager (file-backed)
    │   ├── project.json
    │   ├── run.json
    │   └── handoff/manifest.json (SHA-256)
    │
    └── Heartbeat thread → heartbeat_at
        └── owner_pid + owner_boot_id → orphan reconciliation
```

---

## 8. EXTERNAL INTEGRATIONS

### 8.1 DeerFlow 2 (Stage 1 Research Engine)

**Architecture**: DeerFlow 2 is the complete Stage-1 research subsystem inside the workflow. It's a LangGraph/LangChain "super-agent harness" by ByteDance.

**Three layers**:
| Layer | Purpose | Status |
|-------|---------|--------|
| `deer-flow-2.0.0/` | Vendored pristine source drop | Ignored local reference |
| `deerflow_bridge/` → `deer-flow/` | Tracked research driver/config/tools/skills/patches | **Current live Stage-1 path** |
| `drf2/` | Custom agents and skills, KG/simulation MCP servers | Optional, gated, pre-cutover |

**Assembly**: `setup.sh` seeds `deer-flow/` from vendor dir, trims to runtime essentials, applies bridge overlay. Two patches applied as **idempotent narrow AST transforms** (not file copies).

**Sync guard**: `_sync_deerflow_bridge_if_stale` (`pipeline_orchestrator.py:703`) — SHA-256 compares tracked bridge files against deployed copies on every subprocess launch.

**Skills deployed**: `deep-research`, `actor-ontology-research`, `prediction-markets`, `forecast-visuals`

**MCP boundary**: When `state.graph_id` exists and `RESEARCH_MCP_KG=true`, the orchestrator exposes the existing backend KG to the Stage-1 DeerFlow 2 child over stdio MCP.

### 8.2 OASIS / CAMEL (Stage 5 Simulation)

**Architecture**: OASIS (Open Agent Social Interaction Simulations) by CAMEL-AI is the multi-agent social simulation engine.

**How it's integrated**:
- Launched as a detached subprocess (`run_parallel_simulation.py`)
- `oasis.make(...)` creates the environment with a fresh SQLite DB
- `env.reset()` + `ManualAction`s (initial posts) → round loop
- `env.step(actions)` advances the simulation

**LLM bridging**: `backend/app/utils/oasis_llm.py` bridges the 8 providers into the CAMEL `ChatCompletion` shape:
- CLI providers wrapped in `CLIModel` (fake `OpenAIModel` calling `LLMClient`)
- `get_oasis_semaphore` caps concurrency (3 CLI, 30 HTTP)
- Optional OpenAI "boost" dual-LLM path
- **Tool call emulation**: CLI/text fallback path uses JSON-block-in-prompt protocol (`SIM_CLI_TOOL_EMULATION`)
- Empty assistant message prevention (quality fix)

### 8.3 Polymarket (Prediction Markets)

**Two keyless paths** (Gamma API, `https://gamma-api.polymarket.com`):

1. **In-agent tool** — `prediction_market_search` (`market_tools.py`)
   - ≤6 short phrases → `/public-search` (`events_status=active`)
   - `normalize_market` drops closed/unpriced markets, requires implied P(yes) ∈ (0,1) and volume ≥ 200
   - Returns `market_id, question, implied_yes_prob, volume, liquidity, event_title, url, end_date, status.state`
   - Every candidate set appended as provenance JSONL to `prediction_market_candidates.jsonl`

2. **Bridge orchestration** — Pre-pass snapshot + post-report collection
   - `_pm_initial_snapshot` injects current market pricing into pass 0
   - `_collect_prediction_markets` derives queries (LLM or deterministic), snapshots, applies LLM relevance gate
   - Optionally pulls 90-day price history → `market_price_history.json`
   - Market prices framed as **calibration anchors, not ground truth**

### 8.4 MCP Servers

**`drf-kg`** (`backend/app/mcp/kg_server.py`):
- stdio FastMCP server exposing `ZepToolsService` functions
- Tools: `kg_search`, `kg_trace_cascade`, `kg_entity_summary`, `kg_get_entities`, `kg_centrality_priors`, `kg_graph_statistics`
- Lazy construction of `ZepToolsService` (first call only)
- Timeout bounded by `DRF_MCP_KG_TIMEOUT` (default 60s)
- Always starts cleanly even without a graph

**`drf-simulation`** (`backend/app/mcp/sim_server.py`):
- stdio FastMCP server exposing `SimulationRunner` functions
- Tools: `sim_status`, `sim_results`, `sim_interview_agents`
- Checks `SimulationIPCClient.check_env_alive()` before interviews
- All blocking calls wrapped in `asyncio.wait_for` with `DRF_MCP_SIM_TIMEOUT` (default 120s)

### 8.5 Frontend Integration

The Vue 3 + Vite SPA on port 3000 proxies `/api` → 5001. All communication is **HTTP polling** (no SSE, no WebSockets). The frontend has a sticky 6-stage timeline and tabs for each phase.

---

## 9. RESILIENCE & RECOVERY

### 9.1 Checkpointing & Resume-by-Artifact

The defining property: **a stage is skipped on resume only if its output bytes still verify**, not merely because its status says "completed".

Mechanisms:
- Every stage's outputs declared in `_stage_artifact_specs` and SHA-256'd into `handoff/manifest.json`
- On resume, `_reuse_ok`/`_validate_reuse` re-verifies hashes
- Mismatch forces rebuild + stamps `state.options['resumed_stage_validation']`
- GRAPH reuse has a **0-entity health probe** via `ZepEntityReader`
- REPORT reuse is keyed on the deliverable itself, validated via `_assess_report_health`

### 9.2 Research Intra-Stage Resume

If `research_checkpoint.json` exists, `--resume` is passed to DeerFlow. `ResearchCheckpointer` manages thread_id reuse when `question_hash` + depth match.

### 9.3 Salvage Paths

**Watchdog-timeout salvage** (`pipeline_orchestrator.py:1290-1324`): If the research report artifact is fresh after SIGKILL, the run is treated as `timeout_salvaged` success, followed by `_run_extract_only_salvage` — a bounded (600s) `--extract-only` subprocess that recovers actors/sources/timeline/quantitative from the salvaged report.

**Teardown-timeout salvage** (`:1243-1272`): Kill the group, keep the track if `_track_artifacts_survived` (report ≥400 chars AND actors.json or completed checkpoint passes).

**Orphan salvage** (`:429-480` + `scripts/salvage_orphaned_pipelines.py`): A pipeline wrongly marked failed whose report stage completed with a non-empty `full_report.md` and parseable `forecast.json` is flipped to `completed` + `pipeline_health=degraded` + `ensemble_skipped`.

**Graph degradation**: Skip ratio > `GRAPH_MAX_SKIPPED_RATIO` (0.3) → `graph_ingest_degraded`. Graph prune failures degrade (never break the build).

**LLM outage halt** (`LLM_OUTAGE_HALT_CONSECUTIVE`, default 10): Consecutive provider failures without any success → pipeline stops as a recoverable `failed` checkpoint state. `POST /api/research/<id>/resume` can continue.

### 9.4 Orphan Reconciliation

**Startup** (`backend/app/__init__.py:55-69`):
1. `SimulationRunner.register_cleanup()` + `reconcile_orphans()` — kill leftover sim processes
2. `PipelineOrchestrator.reconcile_orphans()` + `register_cleanup()` — mark orphaned `running` pipelines failed or salvage as completed if report artifact intact

**Heartbeat**: `_start_heartbeat` stamps `heartbeat_at` so the orphan reconciler distinguishes live from dead runs across restarts (`owner_pid` + `owner_boot_id`).

### 9.5 Circuit Breakers

| Circuit Breaker | Trigger | Action |
|----------------|---------|--------|
| Content filter CIRCUIT BREAKER | K consecutive 422s from a provider | Route to fallback, skip doomed primary |
| Degenerate tool loop break | `RESEARCH_DEGENERATE_TOOL_BREAK_AT` (16) consecutive rejected tool calls | Raise `_DegenerateToolLoopError` → salvage |
| Report LLM preflight | Both primary + fallback providers down in <60s | Abort immediately |
| Dual stall watchdog | `PIPELINE_RUN_STALL_S` (1800s) | Force-stop wedged sim |
| Output validation | `_LLM_ERROR_MARKERS` + `RESEARCH_MIN_REPORT_CHARS` | Reject LLM error strings masquerading as reports |
| Graph prune fail-closed | Core count = 0 or `core_actor_coverage < 0.8` | Skip destructive deletion entirely |
| Incompatible schema | File newer than running code | HTTP 409 |

### 9.6 Error Taxonomy

- **`PipelineCancelled`** (subclasses `BaseException`) — deliberately pierces defensive `except Exception` layers; caught at top of `_run` → status `cancelled`, completed stages preserved
- Generic exceptions → `_fail_stage` + `failed`
- `finally` block: stops heartbeat, flushes telemetry, deregisters thread

### 9.7 Fork / Scenario

`POST /api/research/<id>/scenario` forks at PREPARE with a `scenario_overlay` (what-if world-state injection) reusing the completed research/ontology/graph artifacts of a `base_pipeline_id`.

### 9.8 Continue

`POST /api/research/<id>/continue` upgrades a `research_only` run to `full`, reusing the validated research contract.

---

## 10. LLM PROVIDER ABSTRACTION

### 10.1 Three Transport Layers

The system has **three cooperating LLM transport layers**:

**Layer 1: `utils/llm_client.py` — `LLMClient`**
- Used by all pipeline generation (ontology, profiles, config, report)
- Uniform interface: `chat(...)` and `chat_json(...)`
- **CLI providers** (`claude-cli`, `codex-cli`): shell out via `subprocess.run(["claude","-p","--output-format","json", prompt], cwd="/tmp")`. Multi-turn flattened into one prompt. 3-try exponential backoff.
- **OpenAI-compatible** (`openai`, `kimi`, `minimax`, `deepseek`, `qwen`, `glm`): use the `openai` SDK. Kimi injects coding-agent `User-Agent` header, disables hidden thinking.
- Content-addressed cache (`LLM_CACHE_ENABLED`): process-in-memory, exact key, bounded LRU. Only deterministic attempt-0 calls hit.
- Cost model: `_COST_PER_1K` (env override `LLM_COST_PER_MTOK`)
- Content filter CIRCUIT BREAKER: after K consecutive 422s, route to fallback

**Layer 2: `utils/oasis_llm.py` — OASIS/CAMEL bridge**
- Bridges the 8 providers into CAMEL's `ChatCompletion` shape
- CLI providers → `CLIModel` (fake `OpenAIModel` calling `LLMClient`)
- `get_oasis_semaphore` caps concurrency (3 CLI, 30 HTTP)
- Optional OpenAI "boost" dual-LLM path
- Tool call emulation for CLI/text paths

**Layer 3: `graphiti_client/llm_adapter.py` — `AppGraphitiLLMClient`**
- Wraps `LLMClient` for Graphiti's entity/edge extraction
- Schema-echo detection + rising-temperature retry (0.0→0.4)
- Envelope unwrap + pydantic pre-validation
- Runs on `GRAPH_LLM_EXECUTOR_WORKERS=64` I/O pool

### 10.2 Provider Metadata

8 providers with data-driven `PROVIDER_META`:
- `claude-cli`, `codex-cli` — local CLI, no API key
- `openai`, `kimi`, `minimax`, `deepseek`, `qwen`, `glm` — OpenAI-compatible API, need `LLM_API_KEY`
- `kimi`/`minimax`/`deepseek`/`qwen`/`glm` have sensible default `BASE_URL`/`MODEL_NAME`

### 10.3 Tiered Routing (Optional)

`LLM_TIERED_ROUTING` (default `True`):
- **Fast tier**: mechanical structured calls (subquery decomposition, agent selection, JSON repair) → `LLM_FAST_MODEL`
- **Strong tier**: quality-sensitive synthesis (persona generation, report planning, section synthesis) → `LLM_STRONG_MODEL`
- Falls back gracefully if models not configured

---

## 11. KEY FILE MAP

### 11.1 Core Pipeline Services

| File | Lines | Purpose |
|------|-------|---------|
| `pipeline_orchestrator.py` | ~7,618 | The spine. `_run` walks 6 stages on a daemon thread |
| `config.py` | ~1,502 | Single env-driven Config class |
| `__init__.py` | ~120 | App factory, blueprints, auth gate, orphan reconcile, cleanup registration |

### 11.2 Stage Services

| File | Purpose |
|------|---------|
| `services/ontology_generator.py` | Stage 2: derive entity/edge types |
| `services/graph_builder.py` | Stage 3: build Graphiti graph, seed actors, ingest prose |
| `services/graphiti_client/__init__.py` | Zep-SDK-compatible facade → local Graphiti |
| `services/graphiti_client/runtime.py` | Sync→async bridge, GraphitiRuntime singleton |
| `services/graphiti_client/client.py` | Zep-shaped API surface over Graphiti |
| `services/zep_entity_reader.py` | Filter graph nodes to agent-eligible entities |
| `services/zep_entity_resolver.py` | Entity resolution / dedup |
| `services/graph_pruner.py` | 400-node pruning |
| `services/simulation_manager.py` | Stage 4: cast selection, persona assembly, config generation |
| `services/simulation_runner.py` | Stage 5: launch + monitor OASIS subprocess |
| `services/simulation_ipc.py` | File-based IPC to running simulation |
| `services/oasis_profile_generator.py` | Stage 4: generate actor personas |
| `services/simulation_config_generator.py` | Stage 4: generate simulation config |
| `services/actor_role_prompt.py` | Deterministic role contracts |
| `services/zep_graph_memory_updater.py` | Simulation→graph feedback loop |
| `services/report_agent.py` | Stage 6: ReAct report generation |
| `services/zep_tools.py` | Graph retrieval toolkit |
| `services/forecast_extractor.py` | Structured forecast extraction |
| `services/forecast_ledger.py` | Forecast ledger (jsonl) |
| `services/backtest.py` | Calibration scoring (Brier, log-loss) |
| `services/ensemble.py` | Multi-seed forecast aggregation |
| `services/exec_brief.py` | Executive deliverables (deterministic) |
| `services/requirement_spec.py` | Parse forecast brief into machine-readable contract |
| `services/agent_dynamics.py` | Per-agent affective-state dynamics |
| `services/worldstate.py` | Modeled outcome WorldState |
| `services/decision_channel.py` | Post-simulation decision channel |
| `services/world_delta.py` | Inter-round world-delta digest |
| `services/research_progress.py` | DeerFlow progress estimation |

### 11.3 Utilities

| File | Purpose |
|------|---------|
| `utils/llm_client.py` | `LLMClient` — provider-agnostic LLM interface |
| `utils/oasis_llm.py` | OASIS/CAMEL LLM bridge |
| `utils/telemetry.py` | Central LLM meter, run correlation, content-addressable cache, budget guard |
| `utils/token_budget.py` | Adaptive context budgeting |
| `utils/actors.py` | `actors.json` tools, archetype/tier machinery |
| `utils/prediction_markets.py` | Polymarket Gamma API client |
| `utils/security.py` | Secret redaction, SSRF validation |
| `utils/atomic.py` | Atomic file writes |
| `utils/zep_paging.py` | Cursor pagination for graph queries |
| `utils/zep_rate_limit.py` | Rate limit handling |
| `utils/chart_html.py` | Plotly chart generation |
| `utils/sim_timeline.py` | Calendar-temporal timeline |
| `utils/dates.py` | Date parsing |
| `utils/file_parser.py` | PDF/MD/TXT extraction |
| `utils/logger.py` | Logging setup |

### 11.4 API Routes

| File | Routes | Purpose |
|------|--------|---------|
| `api/research.py` | `POST /run`, `POST /<id>/cancel`, `POST /<id>/resume`, `DELETE /<id>`, `GET /status/<id>`, `GET /<id>/dossier`, `GET /<id>/progress` | Unified research→forecast pipeline API |
| `api/simulation.py` | Simulation management + control | OASIS simulation API |
| `api/report.py` | Report generation, streaming, interaction | Report + forecast API |
| `api/graph.py` | Graph build, query, visualization | Knowledge graph API |
| `api/settings.py` | Provider configuration | Settings + LLM test |
| `api/sdk.py` | Optional `/api/v1` SDK surface | SDK compatibility |

### 11.5 MCP Servers

| File | Purpose |
|------|---------|
| `mcp/kg_server.py` | `drf-kg` stdio MCP — graph search, trace, entity lookup |
| `mcp/sim_server.py` | `drf-simulation` stdio MCP — simulation status, interview |

### 11.6 Models

| File | Purpose |
|------|---------|
| `models/task.py` | `Task` (in-memory) + `TaskManager` — async job tracking |
| `models/project.py` | `Project` (file-backed) + `ProjectManager` |

### 11.7 DeerFlow Bridge

| File | Purpose |
|------|---------|
| `deerflow_bridge/deerflow_research.py` | 8,905-line headless driver |
| `deerflow_bridge/search_tools.py` | Web search (Serper > Tavily > DuckDuckGo) |
| `deerflow_bridge/cached_fetch.py` | Transparent cache wrapper over Jina AI reader |
| `deerflow_bridge/market_tools.py` | Polymarket prediction market search |
| `deerflow_bridge/research_budget.py` | Cross-process SQLite budget ledger |
| `deerflow_bridge/config.yaml` | DeerFlow harness + model-provider config |
| `deerflow_bridge/patches/` | Model providers + middleware patches |
| `deerflow_bridge/skills/` | 4 deployed skills |

---

## 12. EVENT-BASED QUANT TRADING RELEVANCE

### 12.1 Why This Architecture Maps to Event-Based Quant Trading

The system is fundamentally an **event prediction engine** with a complete research → simulate → forecast pipeline. Key architectural features that map directly to event-based quant trading:

**Structured Forecast Objects**: `forecast_extractor.py` produces machine-readable scenarios with calibrated probabilities, key drivers, and resolution criteria — this is exactly the structure needed for quantitative trading signals.

**Forecast Ledger + Backtesting**: `forecast_ledger.py` + `backtest.py` form a complete calibration loop: every forecast is appended to a ledger keyed by horizon/resolution date. Once outcomes resolve, Brier score, log-loss, and calibration reports surface into new forecasts' `confidence_rationale`. This is production-grade quant infrastructure.

**Ensemble Aggregation**: `ensemble.py` runs N simulation+report seeds and aggregates into frequency-derived scenario probabilities with spread and inter-run agreement — directly analogous to Monte Carlo option pricing or ensemble model voting.

**WorldState + Decision Channel**: The `worldstate.py`/`decision_channel.py` pair models the *outcome* the simulation converges on (not just what agents say). Resource-weighted commitments, EWMA convergence tracking, and base-rate-seeded distributions are the exact machinery needed for event probability modeling.

**Polymarket Calibration Anchors**: Live prediction market data is injected as calibration anchors at both research and report stages, with exact/near market matching and 10pp-divergence rationale rules. This provides market-implied probabilities as a reference class.

**Deterministic Artifact Chain**: Every stage produces SHA-256-sealed artifacts. This auditability is essential for quant trading where every decision must be traceable to data.

**Event-Driven Architecture Patterns**:
- `decision_channel.py` is pure post-simulation (after both platforms finish) — zero coupling to concurrent per-platform round loops
- Round elicitation is a pure function of the frozen action log — safe to fan rounds out in parallel under a bounded thread pool
- `world_delta.py` is pure, deterministic, no LLM, no I/O — suitable for real-time event processing
- `agent_dynamics.py` is pure — per-agent affective state evolves from received interactions

### 12.2 Gaps and Enhancement Opportunities for Quant Trading

1. **Missing**: Real-time market data feeds beyond Polymarket (need Bloomberg, Tiingo, Polygon, etc.)
2. **Missing**: Order execution layer (the system predicts but doesn't trade)
3. **Missing**: Portfolio-level risk management (position sizing, correlation matrices)
4. **Missing**: Historical backtesting framework with P&L attribution
5. **Missing**: Real-time streaming (the system is batch/poll-based; need WebSocket/event streaming for live trading)
6. **Missing**: Multi-horizon correlation modeling (how 1-week forecasts relate to 1-year forecasts)
7. **Extension**: `forecast_ledger.py` could be extended with P&L-weighted scoring
8. **Extension**: `ensemble.py` could accept market-implied probabilities as prior distributions
9. **Extension**: `decision_channel.py` could model market microstructure effects
10. **Extension**: `worldstate.py` could integrate order book dynamics

---

*Document generated from codebase analysis of DeepResearchForecast at commit `6746de3`.*