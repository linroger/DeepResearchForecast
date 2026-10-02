# DRF_ARCHITECTURE.md — DeepResearchForecast: Full System Architecture

> **Scope.** This document is the granular, code-grounded map of the entire
> DeepResearchForecast (a.k.a. **DeepAgentForecast** / **MiroFish**) system: every
> pipeline stage, every service, every inter-stage contract, and every
> cross-cutting mechanism, with `file:line` references into the codebase as of
> commit `6746de3` (Wave 9). It complements `README.md` (product-level walkthrough),
> `ARCHITECTURE.md` (simulation-engine internals, pre-dating the one-prompt flow),
> and `DEERFLOW_INTEGRATION.md` (research-engine assembly).

---

## Table of contents

1. [System overview](#1-system-overview)
2. [Runtime topology & process model](#2-runtime-topology--process-model)
3. [Repository layout](#3-repository-layout)
4. [The pipeline orchestrator](#4-the-pipeline-orchestrator)
5. [Stage 1 — RESEARCH (DeerFlow bridge)](#5-stage-1--research-deerflow-bridge)
6. [Stage 2 — ONTOLOGY](#6-stage-2--ontology)
7. [Stage 3 — GRAPH (local Graphiti temporal KG)](#7-stage-3--graph-local-graphiti-temporal-kg)
8. [Stage 4 — PREPARE (cast, personas, sim config)](#8-stage-4--prepare-cast-personas-sim-config)
9. [Stage 5 — RUN (OASIS multi-agent simulation)](#9-stage-5--run-oasis-multi-agent-simulation)
10. [Stage 6 — REPORT (forecast synthesis & publication)](#10-stage-6--report-forecast-synthesis--publication)
11. [Cross-stage seams — how every piece connects](#11-cross-stage-seams--how-every-piece-connects)
12. [LLM provider abstraction (three transports)](#12-llm-provider-abstraction-three-transports)
13. [MCP servers](#13-mcp-servers)
14. [HTTP API surface](#14-http-api-surface)
15. [Frontend](#15-frontend)
16. [Configuration surface](#16-configuration-surface)
17. [Ops scripts & developer workflow](#17-ops-scripts--developer-workflow)
18. [Design philosophy & resilience patterns](#18-design-philosophy--resilience-patterns)
19. [Key file map](#19-key-file-map)
20. [finharness transplants (branch `feat/finharness-transplants`)](#20-finharness-transplants-branch-featfinharness-transplants)

---

## 1. System overview

One natural-language forecasting question ("Who wins the US AI race by 2030?")
drives a six-stage pipeline:

```
one prompt ─▶ 1 RESEARCH ─▶ 2 ONTOLOGY ─▶ 3 GRAPH ─▶ 4 PREPARE ─▶ 5 RUN ─▶ 6 REPORT ─▶ forecast
              DeerFlow       LLM derives   local      personas +   OASIS     ReportAgent
              subprocess     entity/edge   Graphiti   sim config   dual-     (spine-first,
              → dossier +    types +       temporal   (role        platform  publish-gated,
              actors.json    archetypes    KG ingest  contracts)   sim       market-anchored)
                     │                        │           │           │            │
                     └────── local Graphiti temporal KG (GraphRAG, embedded FalkorDB) ──────┘
```

- **RESEARCH** — three parallel DeerFlow subprocess "tracks" research the open web
  at scale and merge deterministically into a 15–25K-word cited dossier plus a
  structured actor cast (`actors.json`), sources, timeline, quantitative facts,
  and live Polymarket calibration anchors.
- **ONTOLOGY** — an LLM derives 10 entity types + 6–10 edge types from the
  dossiers, tagging entities with archetype + simulation tier and edges with
  family + valence.
- **GRAPH** — both dossiers are chunked and ingested into a **local** Graphiti
  temporal knowledge graph on embedded FalkorDB; researched actors are seeded as
  typed triplets first; then community detection, entity resolution, pruning to
  a 400-node actor-centered core, and structural priors (centrality).
- **PREPARE** — the tier-1/2 dossier-matched cast (≤20 actors) becomes LLM agent
  personas, each carrying a deterministic, dossier-traceable **role contract**;
  an LLM "environment agent" generates the simulation config.
- **RUN** — OASIS steps a dual-platform (Twitter + Reddit) multi-agent social
  simulation for N rounds in a detached subprocess; actions stream back through
  the filesystem and optionally feed the knowledge graph.
- **REPORT** — a spine-first ReportAgent derives MECE scenario probabilities and
  ≥10 binary forecasts *before* writing prose, retrieves from graph + simulation
  via tools, and emits a three-part, lint-scrubbed, citation-audited,
  Polymarket-anchored, optionally bilingual report behind a read-only,
  SHA-fingerprinted publication gate.

The **`handoff/` file contract** under each pipeline directory is the universal
inter-stage interface; every artifact is checksummed into a manifest, which is
what makes resume, salvage, scenario forking, and research-only → full
continuation possible.

---

## 2. Runtime topology & process model

| Process | What | Launch | Comm channel |
|---|---|---|---|
| **Flask backend** | API + orchestrator + all pipeline services | `backend/run.py` → `create_app()` (`backend/app/__init__.py:22`), threaded dev server on `FLASK_HOST:FLASK_PORT` (default `127.0.0.1:5001`, `run.py:42-43`) | HTTP (polled by frontend) |
| **Vite/Vue frontend** | SPA dashboard | `npm run frontend`, port 3000, proxies `/api` → 5001 | HTTP polling only — **no SSE, no WebSockets** (the `/stream`-named endpoints at `api/report.py:1426,1508` return full JSON blobs) |
| **DeerFlow research** | Deep research per track | `subprocess.Popen(start_new_session=True)` from the orchestrator (`pipeline_orchestrator.py:1136`), own venv `deer-flow/backend/.venv` (Python 3.12) | stdout line stream (progress estimator) + `handoff/` files + SQLite budget ledger |
| **OASIS simulation** | Dual-platform social sim | `subprocess.Popen(start_new_session=True)` from `SimulationRunner.start_simulation` (`simulation_runner.py:685-695`) | `actions.jsonl` tail + `run_state.json` + file-mailbox IPC (`ipc_commands/`/`ipc_responses/`) |
| **Graphiti runtime** | Local temporal KG | in-process singleton with a **background asyncio event loop** (sync→async bridge, `graphiti_client/runtime.py:180-201`) | direct calls behind the Zep-shaped facade |
| **MCP servers** | `drf-kg`, `drf-simulation` | `python -m app.mcp.kg_server` / `app.mcp.sim_server`, stdio FastMCP | consumed by the DeerFlow harness on scenario re-runs |

**Concurrency model: threads + subprocesses, no asyncio in the Flask app.**
Each pipeline runs on one daemon `threading.Thread`; parallel research tracks
use a `ThreadPoolExecutor` (`pipeline_orchestrator.py:5962-5964`); profile
generation uses thread pools; Graphiti's async API runs on its dedicated
background loop; OASIS subprocesses run their own asyncio loops. Slow API
operations follow the async-job pattern: create an in-memory `Task`, spawn a
daemon thread, return a `task_id`, frontend polls `/status`. Because `Task`
objects are in-memory only, every status endpoint *also* resolves progress from
on-disk artifacts so progress survives a backend restart.

**Startup lifecycle** (`backend/app/__init__.py:55-69`): `SimulationRunner.register_cleanup()`
+ `reconcile_orphans()` (kill leftover sim processes / reclaim orphans), then
`PipelineOrchestrator.reconcile_orphans()` + `register_cleanup()` (mark orphaned
`running` pipelines failed **or salvage them as completed** if the report
artifact is intact, and kill stranded DeerFlow process groups).

**Security** (`backend/app/utils/security.py` + `__init__.py:77-121`):
- `before_request` auth gate: OPTIONS/`/health`/non-`/api/` pass; loopback
  remotes pass; otherwise `X-API-Token` compared with `hmac.compare_digest`,
  fail-closed 403 if no token configured.
- `redact_secrets` masks key-named fields and inline tokens (`sk-`, `AIza`,
  `ghp_`, …) before any request/response logging.
- `validate_safe_url` guards SSRF: blocks link-local (169.254.169.254),
  multicast/reserved, optionally private/loopback, and resolves all A records to
  defend against DNS rebinding. Used by the settings LLM-test endpoint and fetches.

---

## 3. Repository layout

```
DeepResearchForecast/
├── package.json                # npm scripts: dev = concurrently(backend, frontend); start/stop; doctor; smoke; test; lint
├── .env / .env.example         # the entire config surface (~87KB documented example)
├── setup.sh                    # interactive installer: provider picker, venvs, DeerFlow assembly
├── scripts/                    # start.sh, doctor.sh, smoke.sh, salvage_orphaned_pipelines.py
├── frontend/                   # Vue 3 + Vite SPA (port 3000)
│   └── src/{views,components,api,router,store,i18n.js}
├── backend/
│   ├── run.py                  # Flask entry point (validates Config first)
│   ├── scripts/                # OASIS subprocess runners (run_parallel/twitter/reddit_simulation.py, action_logger.py)
│   └── app/
│       ├── __init__.py         # app factory, blueprints, auth gate, orphan reconcile
│       ├── config.py           # 1,502-line env-driven Config class — the single config surface
│       ├── api/                # graph.py, simulation.py, report.py, research.py, settings.py, sdk.py
│       ├── models/             # Task (in-memory) + Project (file-backed)
│       ├── mcp/                # kg_server.py, sim_server.py (stdio FastMCP)
│       ├── services/           # the pipeline (orchestrator + ~25 modules)
│       │   └── graphiti_client/  # Zep-SDK-compatible facade → local Graphiti + FalkorDB
│       └── utils/              # llm_client, oasis_llm, actors, telemetry, token_budget, security, …
├── deerflow_bridge/            # git-tracked source of truth for the research engine overlay
│   ├── deerflow_research.py    # 8,905-line headless driver (the bridge entry point)
│   ├── search_tools.py / cached_fetch.py / market_tools.py / research_budget.py
│   ├── config.yaml             # DeerFlow harness + model-provider config
│   ├── patches/                # model providers + middleware patches (+ AST overlay appliers)
│   └── skills/                 # deep-research, actor-ontology-research, prediction-markets, forecast-visuals
├── deer-flow-2.0.0/            # vendored pristine DeerFlow 2.0 engine (seed source; gitignored)
├── deer-flow/                  # the ASSEMBLED runtime that actually executes (gitignored; built by setup.sh)
└── drf2/                       # older/parallel driver lineage (market_tools was adapted from here)
```

**Persistence layout** (all under `backend/uploads/`):

| Entity | Path | Contents |
|---|---|---|
| Pipeline | `pipelines/<pipe_id>/` | `pipeline_state.json`, `run.json`, `handoff/` (the inter-stage contract + `manifest.json`) |
| Project | `projects/<proj_id>/` | `project.json`, uploaded `files/`, `extracted_text.txt` |
| Simulation | `simulations/<sim_id>/` | `state.json`, `run_state.json`, `simulation_config.json`, `*_profiles.{csv,json}`, `{twitter,reddit}/actions.jsonl`, `<platform>_simulation.db` (SQLite), `env_status.json`, `ipc_commands/`, `ipc_responses/`, `world_state_trajectory.json`, `decisions.jsonl`, `emergent_metrics.json`, `run_summary.json`, `llm_health.json` |
| Report | `reports/<rep_id>/` | `outline.json`, `section_NN.md`, `full_report.md` (+ `full_report.<lang>.md`), `forecast.json`, `citations.json`, `final_audit.json`, `viz_manifest.json`, `charts/`, `market_comparison.json`, `agent_log.jsonl`, `console_log.txt`, `progress.json`, `meta.json`, `resolved.json` |
| Graph DB | `graphiti_db/falkor.db` | embedded FalkorDB file (one tenant DB per `graph_id`) |
| Ledger | `_forecast_ledger/` | `ledger.jsonl`, `resolutions.jsonl` |

---

## 4. The pipeline orchestrator

`backend/app/services/pipeline_orchestrator.py` (7,618 lines) is the spine.
`PipelineOrchestrator._run` (`:6446-7618`) is a classmethod executed on one
dedicated daemon thread per pipeline; it walks the six stages sequentially.

### 4.1 Stages and progress bands

Stage constants at `:74-79`; global-progress bands at `:82-92`:

| Stage | Band (full mode) | Band (research_only) |
|---|---|---|
| `research` | 0–30 | 0–100 |
| `ontology` | 30–40 | — |
| `graph` | 40–60 | — |
| `prepare` | 60–72 | — |
| `run` | 72–92 | — |
| `report` | 92–100 | — |

Bands are **dynamically re-derived** from observed cost signals (chunk count,
total rounds, section count) via `_recompute_dynamic_bands` (`:4411-4448`),
stored in `state.options['dynamic_bands']`, and consumed by
`_global_from_stage` (`:4402-4409`) — so a 40-round sim widens the RUN band
rather than appearing stuck.

### 4.2 State model & persistence

- **`PipelineState`** dataclass (`:210-284`): `pipeline_id, prompt, schema_version(=2),
  mode, status, global_progress, current_stage, task_id, project_id, graph_id,
  simulation_id, report_id, handoff_dir, research_pid, owner_pid, owner_boot_id,
  heartbeat_at, last_progress_at, error, created_at, updated_at, options(dict),
  stages(dict[str, StageState]), artifacts(dict[str,str])`.
- **`StageState`** (`:186-206`): `name, status(pending/running/completed/failed/skipped),
  progress, message, started_at, finished_at, error`.
- **`PipelineManager`** (`:292-626`) writes `uploads/pipelines/<id>/pipeline_state.json`
  via `write_json_atomic` (tmp + fsync + `os.replace`; `backend/app/utils/atomic.py`)
  under a per-pipeline `threading.Lock` (`:341-361`) — this serializes the main
  thread's `save`, the heartbeat's `touch_heartbeat`, and terminal
  `mark_failed`/`mark_salvaged_completed` so a slow writer can't roll back a
  terminal status (lost-update prevention).
- **Schema versioning**: `PIPELINE_SCHEMA_VERSION = 2` (`:97`); `load` migrates
  older files forward (`_migrate`, `:382-395`); a file *newer* than the running
  code returns an incompatible sentinel → the API maps it to HTTP 409
  (`IncompatiblePipelineSchema`, `:110`, sentinel handling `:557-568`).

### 4.3 Checkpointing, reuse & resume (resume-by-artifact)

The defining property: a stage is skipped on resume **only if its output bytes
still verify**, not merely because its status says "completed".

- Every stage's outputs are declared in `_stage_artifact_specs` (`:4920-4974`)
  and SHA-256'd into `handoff/manifest.json` (`_manifest_entry_for`, `:3127`).
- On resume, `_reuse_ok`/`_validate_reuse` (`:5180-5254`) re-verify the hashes;
  a mismatch forces a rebuild and stamps `state.options['resumed_stage_validation']`.
- GRAPH reuse additionally does a 0-entity health probe via `ZepEntityReader`
  (`:6792-6805`) so an empty graph can't be "reused".
- REPORT reuse is keyed on **the deliverable itself**, not stage status
  (`:7321-7377`): it resolves the existing report by `report_id` or
  `get_report_by_simulation` and rejects broken deliverables via
  `_assess_report_health` — preventing "reuse bad report → health gate fails →
  resume loops forever".
- RESEARCH supports **intra-stage** resume: if `research_checkpoint.json`
  exists, `--resume` is passed to the DeerFlow subprocess (`:6513-6538`,
  `:973-976`) and completed passes are skipped inside the run.

### 4.4 The research contract (atomic multi-file promotion)

Research produces 13 files + a `charts/` tree (`_RESEARCH_CONTRACT_FILES`,
`:1484-1490`). Because a partially-written handoff would poison every
downstream stage, promotion is transactional:

1. `_promote_research_contract` (`:1569-1677`): staged copy → rollback dir →
   per-file `os.replace` → manifest written **last** → validate; full rollback
   on any exception.
2. `_finalize_research_contract` (`:1680-1792`): builds a private finalized copy
   so post-processing (lint, cast reconciliation) cannot invalidate the
   already-published checksum manifest.
3. `_validate_research_contract` (`:1525-1566`): byte/SHA match, report ≥400
   chars, no stray files, exact charts set; path-traversal guarded via
   `os.path.commonpath`.

### 4.5 Salvage paths

- **Watchdog-timeout salvage** (`:1290-1324`): if the research report artifact
  is fresh after SIGKILL, the run is treated as `timeout_salvaged` success,
  followed by `_run_extract_only_salvage` (`:1795-1874`) — a bounded (600s)
  `--extract-only` subprocess that recovers `actors/sources/timeline/quantitative`
  from the salvaged report.
- **Teardown-timeout salvage** (`:1243-1272`): kill the group, keep the track if
  `_track_artifacts_survived` (`:1467-1480`: report ≥400 chars AND actors.json
  or completed checkpoint passes).
- **Orphan salvage** (`:429-480` + `scripts/salvage_orphaned_pipelines.py`):
  a pipeline wrongly marked failed whose report stage completed with a non-empty
  `full_report.md` and parseable `forecast.json` is flipped to
  `completed` + `pipeline_health=degraded` + `ensemble_skipped`.

### 4.6 Error handling & health gate

- **`PipelineCancelled(BaseException)`** (`:100`) deliberately subclasses
  `BaseException` so it pierces defensive `except Exception` layers; caught at
  the top of `_run` (`:7492-7509`) → status `cancelled`, completed stages
  preserved. Generic exceptions → `_fail_stage` + `failed` (`:7510-7521`).
  The `finally` block (`:7522-7618`) stops the heartbeat, flushes telemetry,
  and deregisters the thread.
- **Output-validation circuit breakers**: `_LLM_ERROR_MARKERS` (`:1415`) +
  `RESEARCH_MIN_REPORT_CHARS` reject LLM error/moderation strings masquerading
  as reports (`:1338-1346`); `_is_degraded_dossier` (`:1424`) drops bad Track-B
  dossiers.
- **Report LLM preflight** (`:7383-7394`): a ping before section generation
  aborts in <60s if both primary and fallback providers are down, instead of
  burning per-section costs discovering it.
- **Dual stall watchdogs** for the RUN stage: an inline poll-loop check
  (`:7246-7251`) plus an independent disk-reading watchdog thread
  (`_spawn_run_stall_watchdog`, `:4533-4579`); both force-stop a wedged sim
  after `PIPELINE_RUN_STALL_S` (default 1800s).
- **`_enforce_pipeline_health`** (`:4865-4917`, `PIPELINE_HEALTH_GATE` default
  on): aggregates per-stage health into `state.options['pipeline_health']`;
  hard-raises on an empty/placeholder report or missing `forecast.json`
  (`_assess_report_health` `:4581`, `_assess_run_health` `:4771`); records
  `degraded` for graph ingest skip-ratio > `GRAPH_MAX_SKIPPED_RATIO` (0.3) or
  failed prune postconditions.

### 4.7 Budget enforcement (three independent layers)

1. **LLM meter** (`backend/app/utils/telemetry.py`): process-wide, thread-safe
   `LLMMeter` (`:176-266`) keyed by run id via contextvars, with per-stage/model
   rollups and a cost model (`_COST_PER_1K` `:48-65`, env override
   `LLM_COST_PER_MTOK`). `check_budget` (`:309-326`) is called after every LLM
   call and raises `BudgetExceeded` past `LLM_RUN_BUDGET_TOKENS`/`_USD`
   (0 = unlimited). Caveat: `ThreadPoolExecutor` does not inherit contextvars,
   so worker-thread calls can leak into the `_global` bucket (warned at
   20/100/500/2000 calls, `telemetry.py:171-204`).
2. **Research tool-budget ledger** (`deerflow_bridge/research_budget.py`, §5.6):
   a cross-process SQLite ledger injected into the DeerFlow env by
   `_configure_research_budget_env` (`:887-928`).
3. **Context/token budgeting** (`backend/app/utils/token_budget.py`): pure,
   never-raising helpers (`slice_budget_chars`, `context_budget`,
   `fit_to_budget`, `clamp_chars`, `:69-174`; ≈4 chars/token) that size prompt
   slices to the active provider's context window (`ADAPTIVE_CONTEXT`).

### 4.8 Heartbeat, cancel, fork, continue

- A heartbeat thread (`_start_heartbeat`, `:5447`) stamps `heartbeat_at` so the
  orphan reconciler can distinguish live from dead runs across restarts
  (`owner_pid` + `owner_boot_id`).
- Cancel: `POST /api/research/<id>/cancel` sets the pipeline's cancel `Event`;
  the DeerFlow subprocess group is `os.killpg`'d (`_kill_process_group`, `:653`)
  and the OASIS sim is stopped — a cancelled run stops burning quota immediately.
- **Fork / scenario**: `POST /api/research/<id>/scenario` forks at PREPARE with
  a `scenario_overlay` (what-if world-state injection) reusing the completed
  research/ontology/graph artifacts of a `base_pipeline_id`.
- **Continue**: `POST /api/research/<id>/continue` upgrades a `research_only`
  run to `full`, reusing the validated research contract.

### 4.9 Progress estimation

`backend/app/services/research_progress.py`:
- `ResearchProgressEstimator` (`:42-206`) converts DeerFlow's streamed
  lifecycle log lines into a monotonic, phase-banded estimate; **only**
  `[init]/[stage]/[ok]/[done]/[resume]` line kinds may cross phase boundaries
  (`:80-96`) — tool output can never impersonate a lifecycle transition (the
  old `10 + tool_calls*4` heuristic hit 90% after 20 calls and froze).
- `aggregate_parallel_progress` (`:209-230`): equal-weight mean across tracks
  with a **95 ceiling reserved for the merge phase**; failed tracks stay in the
  denominator so survivors can still reach 95.
- `merged_research_progress_tail` (`:256-314`): bounded multi-track log tailing
  (256KB/file, 500 lines) that powers the live console
  (`GET /api/research/<id>/progress`).

---

## 5. Stage 1 — RESEARCH (DeerFlow bridge)

### 5.1 Assembly topology & the sync guard

Four directories participate:

- **`deerflow_bridge/`** — git-tracked source of truth: the entry driver
  `deerflow_research.py` (8,905 lines), config-reflected tools
  (`search_tools.py`, `cached_fetch.py`, `market_tools.py`), the budget ledger
  (`research_budget.py`), `config.yaml`, `patches/`, `skills/`.
- **`deer-flow-2.0.0/`** — the vendored pristine DeerFlow 2.0 engine
  (LangGraph/LangChain "super-agent harness" by ByteDance).
- **`deer-flow/`** — the assembled runtime. `setup.sh` seeds it from the vendor
  dir (falling back to a pinned upstream clone), trims it to runtime essentials,
  and applies the bridge overlay.
- **`drf2/`** — an older driver lineage (historical).

**Sync guard** — `_sync_deerflow_bridge_if_stale`
(`pipeline_orchestrator.py:703`). Before *every* subprocess launch, tracked
bridge files are SHA-256-compared against the deployed copies and re-copied on
drift. (Historical bug: a bridge edit silently ran stale deployed code; a
28-actor dossier escaped `ACTOR_CAST_MAX=20`.) Synced: the entry script
(`:731`), the three tool modules + `research_budget.py` (`:739`), middleware
patches (`:749`), `extensions_config.json` (`:763`), all `skills/*/SKILL.md` +
bundled scripts + lazy references (`:770-795`). Two patches are applied as
**idempotent narrow AST transforms** rather than file copies:
`patches/apply_lead_agent_overlays.py` (`:809`; forwards
`trim_tokens_to_summarize: null` so summarization doesn't fall back to
LangChain's 4K tail) and `patches/apply_subagent_overlays.py` (subagent
lifecycle lease). `config.yaml` is copied only if absent — never clobbered.

### 5.2 Launch chain

`POST /api/research/run` (`api/research.py`; validates
`depth ∈ {quick,standard,deep}` and `model ∈ SUPPORTED_DEERFLOW_MODELS`) →
`PipelineOrchestrator.start(...)` → the orchestrator builds

```
<deer-flow venv python> deerflow_research.py
    --prompt-file …            # brief kept off argv (not visible in ps)
    --out-dir <handoff>  --model …  --depth …
    [--target-language] [--subagents] [--resume]
    [--evidence-only] [--synthesis-manifest]
```

with a large tuned env block (recursion limits, dual-track, fanout width,
`ACTOR_CAST_MAX`, prediction-market knobs, budget/lease DB paths,
`DEERFLOW_RUN_ARTIFACT_DIR`), then `subprocess.Popen(cwd=deerflow_dir,
stdout=PIPE, stderr=STDOUT, start_new_session=True)` (`:1136`) under a
depth-scaled watchdog (`Config.deerflow_depth_budget`, ×1.5 for
dual-track/subagents, `:1153-1164`; defaults quick 900s / standard 2400s /
deep 10800s). A `threading.Timer` watchdog (`:1170-1177`) and a
`_cancel_watcher` thread (`:1183-1191`) guard the run; the stdout line-reader
drives the `ResearchProgressEstimator`.

`main()` (`deerflow_research.py:8070`) writes `prediction_requirement.txt` +
`meta.json` immediately, runs a **credential pre-flight** (`:8231`; claude →
OAuth token present/fresh, codex → `~/.codex/auth.json`, API models → the exact
`$KEY` env var; fail-fast exit 3 naming the missing variable), then constructs
`deerflow.client.DeerFlowClient` (`:8278`) with `thinking_enabled=True` and the
whitelisted skills `deep-research`, `actor-ontology-research`,
`prediction-markets`, `forecast-visuals`.

### 5.3 Parallel tracks & deterministic merge

With `Config.RESEARCH_PARALLEL_TRACKS > 1` (default 3),
`_run_parallel_research_tracks` (`pipeline_orchestrator.py:5806-6391`) fans out
K angle-specialized subprocesses via a `ThreadPoolExecutor`
(`thread_name_prefix="research-track"`, `:5962-5964`). Angles from
`_RESEARCH_TRACK_ANGLES` (`:1965`): **base-evidence · base-rates & analogs ·
incentives/contrarian/markets**. Architecture: parallel **evidence-only lanes**
(`--evidence-only`) → **one global synthesis** run (`:5995-6199`; retried twice
in clean dirs, then fails closed preserving evidence packs, `:6058-6134`).

Concurrency governance is computed by pure functions
(`research_outer_track_workers` / `research_model_concurrency_cap` /
`research_lane_subagent_cap` / `research_subagent_cap_per_track`,
`:1974-2026`) sharing a **global model-concurrency cap via a SQLite lease DB**
(`RESEARCH_MODEL_LEASE_DB`, `:1116-1118`) so three tracks × subagents can't
stampede the provider.

Merging is deterministic (no LLM): `merge_sources_union` (`:2335`; keep the
highest S-tier per URL, `_track_tier_rank` `:2038`), `merge_track_reports`,
`merge_actors_objs`, citation remap via `normalize_track_report_citations`
(`:2372`), freshest-markets wins; then cross-track **cast reconciliation** via
`utils.actors.reconcile_cast` (`:6607-6635`) → `cast_reconciliation.json`.

### 5.4 Depth presets & the deep loop

`DEPTH_PRESETS` (`deerflow_research.py:91`): **quick** = 1 turn,
`recursion_limit=100`; **standard** = 1 turn, limit 360, + optional KIQ-gap
top-up rounds; **deep** = the staged multi-pass protocol.

**Deep loop** (`run_research_stage`, `:5680`; one shared thread/checkpointer
across passes):

1. **`deep-opening`** (limit 300) — maps the source landscape, seeds the KIQ
   (key intelligence questions) ledger.
2. Optional **brief-drift correction** (`:5844`): a cheap tool-free year-drift
   check (`_detect_year_drift`); if opening notes center on the wrong year
   versus the brief, a plain corrective thread message is injected (no agent
   turn spent).
3. **Five fixed phases** (`DEEP_RESEARCH_PHASES`, `:215`): `scope`(330) →
   `primary-evidence`(540) → `actors-and-incentives`(450) →
   `contradictions-and-risks`(450) → `forecast-implications`(390); budgets
   scaled by `RESEARCH_PHASE_BUDGET_MULT` (`_phase_budget`, `:277`). Scope runs
   sequentially; the three middle phases run as **parallel scoped workers** on
   isolated thread_ids (`RESEARCH_PARALLEL_PHASES`, `:5972`), then their notes
   are absorbed back; forecast-implications runs last so it sees all evidence.
4. Optional per-KIQ / per-actor **fan-out** (`RESEARCH_DEEP_FANOUT`,
   `start_deep_fanout`, `:4899`, width `RESEARCH_FANOUT_WIDTH` default 8)
   overlapping the scope pass, plus harness **sub-agents**
   (`DEERFLOW_SUBAGENTS`).
5. **Tool-free synthesis** writes the final dossier from accumulated thread
   notes + fetched sources.

**Termination conditions:**

- *Per-turn step budget* — LangGraph `recursion_limit`; `GraphRecursionError`
  is caught in `run_streamed_turn` (`:4702`) and salvaged (partial text kept).
- *Gap/KIQ convergence* — every pass must emit a complete "Gaps" ledger of
  still-open KIQs; top-ups continue only while a named unresolved KIQ has a
  credible next evidence upgrade. Standard-depth gate (`:5734`): up to
  `RESEARCH_COVERAGE_GATE_MAX_ROUNDS` (2) targeted passes; stops when
  `_gaps_closed==0 && _source_delta==0` for two rounds or on plateau
  (`advance_gap_set_from_notes`). Deep uses a **convergence scheduler**
  (`planned_deep_phase_indices`, `RESEARCH_CONVERGENCE_SCHEDULER`) that skips
  redundant fixed phases. Source counts are diagnostics, never quotas.
- *Degenerate-loop break* — `run_streamed_turn` (`:4616`) counts consecutive
  rejected/malformed tool calls (empty `web_search` query, schemeless
  `web_fetch`); at `RESEARCH_DEGENERATE_TOOL_CORRECT_AT` (8) it injects one
  corrective message; at `RESEARCH_DEGENERATE_TOOL_BREAK_AT` (16) it raises
  `_DegenerateToolLoopError` → salvage (`:4583`, thresholds `:4598`).
- *Budget ledger caps* (§5.6).
- *Synthesis trigger / min-report gate* — a turn returning fewer than
  `_synthesis_trigger_chars` (deep 15,000 / else 4,000, `:8531`) triggers a
  clean tool-free `synthesize_from_thread` call (recovers over-research and
  structural provider errors, but **not** content-moderation blocks). Reports
  below `RESEARCH_MIN_REPORT_CHARS` (deep 2,000 / else 400, `:8544`) or matching
  `looks_like_llm_error` (`:8564`) → honest non-zero exit, no report written.
- *Resume* — `--resume` reuses the `research_checkpoint.json` thread_id and
  skips completed passes when `question_hash` + depth match
  (`ResearchCheckpointer`, `:643`).

### 5.5 Search, fetch, caching

- **`web_search`** (`search_tools.py`; registered in `config.yaml:726`):
  provider selected at call time by key precedence — **Serper**
  (`SERPER_API_KEY`) > **Tavily** (`TAVILY_API_KEY`) > **DuckDuckGo** (keyless)
  (`_select_search_provider`, `:315`); delegates to the harness's own community
  tool (byte-equivalent to configuring the provider directly); degrade-safe
  (unavailable backend → DDG → empty-result JSON, never raises into the agent
  loop). `_filter_denied_search_results` (`:188`) strips denylisted URLs.
- **`web_fetch`** (`cached_fetch.py`; `config.yaml` `timeout:30`): transparent
  cache wrapper over the harness's Jina AI reader (`_jina_delegate_fetch`, `:347`).
- **Disk caches** (both atomic temp+`os.replace`, TTL from stored `fetched_at`,
  mtime reserved for LRU eviction):
  - search: `RESEARCH_SEARCH_CACHE_TTL_H` (6h; 0=off), key
    `sha256(provider + normalized query + max_results)`, cap 200MB;
    only successful non-empty results cached.
  - fetch: `RESEARCH_SOURCE_CACHE_TTL_H` (72h), key `sha256(url)`, cap 500MB;
    never caches `"Error:"`-prefixed or <200-char dead fetches.

### 5.6 The cross-process budget ledger

`deerflow_bridge/research_budget.py` — active only when the orchestrator sets
`RESEARCH_BUDGET_DB` (one DB per stage, distinct `RESEARCH_BUDGET_LANE_ID` per
track). Atomic SQLite admission with per-scope caps (`:32`):
`ATTEMPTS_GLOBAL=1800`, `SEARCH_GLOBAL=900` / `SEARCH_LANE=360`,
`FETCH_GLOBAL=450` / `FETCH_LANE=180`. Plus:

- **Negative-result ledger** (600s TTL, 1 retry): known-empty queries are not
  re-searched.
- **Positive-repeat dedup**: an identical repeated call returns a compact
  artifact id instead of re-running.
- **Single-flight**: `claim_request`/`release_request` collapse identical
  in-flight calls (`RESEARCH_INFLIGHT_WAIT_SECONDS=45`).
- **Model/subagent leases**: `MODEL_CONCURRENCY_GLOBAL=12`,
  `SUBAGENT_CONCURRENCY_GLOBAL=9` — the same DB arbitrates LLM concurrency
  across all tracks and their subagents.
- **Fails open** on any ledger error, emitting degraded telemetry
  (`research_budget.json`).

### 5.7 Prediction markets in research

Two keyless Polymarket paths (Gamma API, `https://gamma-api.polymarket.com`):

- **In-agent tool** — `prediction_market_search` (`market_tools.py`;
  `config.yaml:761`). ≤6 short phrases → `/public-search`
  (`events_status=active`); `normalize_market` (`:170`) drops closed/unpriced
  markets, requires implied P(yes) strictly in (0,1) and volume ≥
  `PREDICTION_MARKETS_MIN_VOLUME` (200); ranks by volume, caps 3/event, 20
  total. Returns `market_id, question, implied_yes_prob, volume, liquidity,
  event_title, url, end_date` **plus a `status.state`**
  (`success/verified_empty/transport_failure/inflight_timeout`) so an empty
  list is never misread as "no market exists". Every candidate set is appended
  as provenance JSONL to `prediction_market_candidates.jsonl`. HTTP retry: one
  retry on transient {429, 5xx} (`_http_get`, `:142`).
- **Bridge orchestration** (`deerflow_research.py`): a **pre-pass snapshot**
  (`_pm_initial_snapshot`, `:7576`) injects current market pricing into pass 0
  and into structured extraction; a **post-report collection**
  (`_collect_prediction_markets`, `:7593`) derives queries (LLM or
  deterministic), snapshots, applies an LLM **relevance gate**
  (`score_market_relevance`, threshold `PREDICTION_MARKETS_MIN_RELEVANCE`),
  optionally pulls 90-day price history → `market_price_history.json`, writes
  `prediction_markets.json`, and appends a "Prediction Market Signals" section.
  Market prices are framed throughout as **calibration anchors, not ground
  truth**. All degrade-safe.

### 5.8 Research outputs (the handoff contract)

Written atomically to `--out-dir` (= `handoff/`); filename constants at
`deerflow_research.py:502+`:

| File | Content |
|---|---|
| `research_report.md` | The long-form cited dossier (deep target 8–12K words/track; 15–25K merged). `[S<n>]` citations finalized against a References section (`finalize_report_citations`, `:1846`); dangling markers stripped. |
| `actor_dossier.md` | Track-B actor-ontology dossier: the ranked cast in depth. |
| `actors.json` | **The keystone artifact**: `actors`, `relationships`, `situation_brief`, `key_events`, `quantitative_facts`, `contested_claims`, `sources`, `as_of_date` — produced by tool-free `extract_structured_tool_free` (`:3515`). |
| `sources.json` | Citation ledger **grounded in URLs actually fetched** (`merge_fetched_into_sources`, `:1220` — fabricated model entries dropped), with S1–S4 tier histogram, staleness, jurisdiction diversity. |
| `timeline.json` / `quantitative.json` / `contested.json` | Promoted first-class extracts (key events, quantitative facts with ~1000× unit-scale reconciliation warnings, contested claims). |
| `prediction_markets.json` / `market_price_history.json` | Relevance-gated market snapshot + 90-day series. |
| `charts.json` + `charts/` | Research Visual Annex PNGs (rendered by the `forecast-visuals` skill's `render.py`). |
| `meta.json` | Status, model, depth, thread_id, phase budgets, `research_quality` (grounding-based score vs `RESEARCH_QUALITY_FLOOR=0.45`), degradation flags, coverage gaps, triangulation audit, resume info. |
| `research_progress.log` | Streamed lifecycle/tool/usage lines (`ProgressLog`, `:1508`) — tailed by the backend for live progress. |
| `prediction_requirement.txt` | The verbatim brief. |
| `research_checkpoint.json` | Resume state. |
| `evidence_pack.md` | Per-lane output in `--evidence-only` mode. |

Post-write enrichment in `main()`: dual-track actor dossier, **triangulation
top-up** (deep only — re-verifies single-origin load-bearing claims), quant
reconciliation, recency annotation.

---

## 6. Stage 2 — ONTOLOGY

Orchestrated at `pipeline_orchestrator.py:6697-6777`; implemented by
`backend/app/services/ontology_generator.py`.

- A `Project` is created and seeded with the research report as its extracted
  text (`:6708-6716`); `OntologyGenerator().generate(...)` receives
  `document_texts=[actor_dossier_md, research_report_md]`, the
  `central_question`, the `actors` dict, and an auto-selected template
  (`:6736-6750`).
- The prompt (`ontology_generator.py:31-120`) demands **exactly 10 entity
  types** describing *real, social-media-capable actors* (not abstract topics),
  with the last two forced to `Person`/`Organization` fallbacks; 6–10 edge
  types; PascalCase entity names, UPPER_SNAKE_CASE edge names; attributes
  primitive (`Optional[str]` — FalkorDB stores scalars only) with reserved names
  (`uuid,name,group_id,name_embedding,summary,created_at`) sanitized (`:25`,
  mirrored `graph_builder.py:48`).
- With `ONTOLOGY_RICH_SCHEMA` on, each entity type carries an **archetype +
  simulation tier** (so reporters/outlets/abstract concepts become graph
  *context*, not agents) and each edge a **family + valence** (allies, rivals,
  suppliers, backers stay distinguishable).
- Output `{entity_types[], edge_types[], analysis_summary}` is validated,
  persisted to `project.ontology`, and written to `handoff/ontology.json`
  (`:6756-6776`).

---

## 7. Stage 3 — GRAPH (local Graphiti temporal KG)

Orchestrated at `pipeline_orchestrator.py:6779-7063`; core services:
`graph_builder.py`, `graphiti_client/`, `zep_entity_resolver.py`,
`graph_pruner.py`.

### 7.1 The Graphiti facade (Zep Cloud is gone)

`backend/app/services/graphiti_client/` is a **drop-in facade** replacing the
`zep_cloud` SDK with a locally-running Graphiti graph
(`graphiti_client/__init__.py:1-15`). `Zep(api_key=...)` is accepted for
signature compatibility but the key is ignored (`client.py:292-300`); the five
graph-touching services (`GraphBuilderService`, `ZepEntityReader`,
`ZepGraphMemoryUpdater`, `OasisProfileGenerator`, `ZepToolsService`) kept their
Zep-era names — only the import line changed.

- **`client.py`** — reproduces the exact `client.graph.*` surface
  (`create/set_ontology/delete/add_batch/add/add_triplet/build_communities/search`
  + `graph.node/edge/episode` namespaces), returning `_ZepNode`/`_ZepEdge`/
  `_ZepEpisode` wrappers mirroring Zep attribute names (`uuid_`, `fact`,
  `valid_at`, …). Graphiti datetimes normalize to ISO strings at the boundary
  (`_iso`, `:24-29`). Episodes always report `processed=True` because Graphiti
  ingests synchronously (`:73-81`) — the old Zep "poll episode.processed
  ≤600s" wait collapses to a no-op.
- **`runtime.py`** — `GraphitiRuntime` singleton (`get_runtime()`, `:1796`):
  - Persistent asyncio loop on a background thread (sync→async bridge) with a
    per-op wall-clock timeout `GRAPHITI_OP_TIMEOUT_S` that cancels wedged
    coroutines so the per-graph lock can't deadlock (`:180-201`).
  - One cached `Graphiti` instance per `graph_id`; a **per-graph write lock**
    serializes the search→resolve→write dedup sequence (`:449-457`).
  - Graph primitives: `add_episode` (episode-level schema-echo retry ladder +
    fallback-LLM swap, `:558-611`), `add_triplet` (dedups endpoints by
    name+embedding so prose enriches seeded nodes instead of duplicating,
    `:679-717`), `causal_paths` / `n_hop_subgraph` (variable-length Cypher over
    `RELATES_TO`; parses the folded causal attributes back out of fact text;
    computes net polarity + cumulative lag, `:875-1021`), `search`
    (recipe-based hybrid RRF/MMR/cross-encoder/node_distance + bi-temporal
    `SearchFilters` push-down, `:1185-1285`), `merge_nodes`,
    `delete_entity_nodes`, `list_graph_ids`, `list_communities` (`:812-845`).
  - **Storage backend** (`GRAPH_BACKEND`, default `auto`, `:239-261`):
    `falkordblite` (embedded FalkorDB via `redislite.AsyncFalkorDB` — the
    default; same engine Zep Cloud was built on) → external FalkorDB server (if
    `FALKORDB_HOST` set) → `kuzu` (embedded file fallback). DB at
    `uploads/graphiti_db/falkor.db` (`:276`). `graph_id` doubles as the
    FalkorDB tenant name **and** Graphiti `group_id` (`:17,281-299`).
  - **LLM/embedder** (`:314-331`): LLM = `AppGraphitiLLMClient`
    (`llm_adapter.py`) wrapping the app's provider-agnostic `LLMClient` (works
    with keyless CLI providers), with schema-echo detection + rising-temperature
    retry (0.0→0.4) + envelope unwrap + pydantic pre-validation (`:113-269`),
    on a dedicated I/O pool (`GRAPH_LLM_EXECUTOR_WORKERS=64`). Embedder = local
    sentence-transformers `paraphrase-multilingual-MiniLM-L12-v2` (384-dim,
    `embedder.py`; `EMBEDDING_DIM` frozen at import). Reranker =
    `NoOpCrossEncoder` (RRF recipes do the ranking) or BGE via
    `GRAPHITI_RERANKER=bge`.
  - **falkordblite bug workaround**: `WHERE` property predicates are silently
    dropped under `ORDER BY+LIMIT`; the runtime
    (`_list_uuids_ordered`/`_fetch_edges_unfiltered`/`_page_after_cursor`,
    `:1298-1414`) and `utils/zep_paging.py:142-231` compensate with
    zero-predicate full scans + Python-side dedup/pagination.
- **`compat.py`** re-exposes `EpisodeData`, `EntityEdgeSourceTarget`,
  `ApiError`, `InternalServerError`. `zep_rate_limit.py` is retained but
  effectively dead against a local DB.

### 7.2 Build sequence

1. **Create** — `create_graph` mints `graph_id = f"mirofish_{uuid4().hex[:16]}"`
   (`graph_builder.py:687-697`).
2. **Ontology → dynamic Pydantic models** — `set_ontology` (`:699-809`)
   `type()`-creates `EntityModel`/`EdgeModel` subclasses from the ontology
   JSON, per-item try/except isolated, builds `source_targets`
   (`EntityEdgeSourceTarget`). The shim caches the ontology and passes
   entity/edge types **per `add_episode`** (Graphiti takes schema at ingest
   time; `runtime.py:398-417`).
3. **Actor seeding (pre-text)** — `seed_actors` (`:811-961`) writes
   research-confirmed actors/relationships **before prose extraction** as typed
   triplets anchored at a validated `as_of` date (`_validate_as_of_date`,
   `pipeline_orchestrator.py:5760`; seeding call `:6877-6883`):
   - Relationships → typed edges (edge name via `REL_EDGE_NAME`; unknown types
     sanitized to a specific label or `RELATES_TO`, never dropped, `:839-888`).
   - Isolated actors → `IS_A` → type nodes (`:889-935`); aliases →
     `ALSO_KNOWN_AS` bridges (`:936-960`).
   - **Causal metadata is folded into fact text** — e.g.
     `（sign=-，strength=high，lag=2w，polarity=-0.80）` — and with
     `ONTOLOGY_RICH_SCHEMA`, valence/archetype/tier/salience too. This folded
     payload is what `causal_paths` parses back out for the report's causal
     skeleton.
4. **Chunk + episode ingest** — dossier text (source selectable
   `both`/`dossier_only`/`report_only` via `GRAPH_CHUNK_SOURCE`, default
   `dossier_only`; `pipeline_orchestrator.py:6837-6847`; data-URI images
   stripped first, `:679`) → `TextProcessor.split_text` (500-char chunks, 50
   overlap) → `add_text_batches` (`graph_builder.py:963-1065`; `EpisodeData`
   with `reference_time=as_of` — the **bi-temporal anchor**; batch_size 10).
   Per-episode failures are isolated and counted (`last_ingest_stats`:
   total/failed/succeeded/skip_ratio/skip_reasons, `:1036-1052`); if **all**
   chunks fail → hard raise (no silent empty graph, `:1056`); skip ratio >
   `GRAPH_MAX_SKIPPED_RATIO` (0.3) → `graph_ingest_degraded`
   (`pipeline_orchestrator.py:6897-6913`).
5. **Community detection** — `build_communities` (Leiden + LLM summaries,
   `runtime.py:790-806`) → `handoff/communities.json` (`:6922-6934`).
6. **Entity resolution / dedup** (`zep_entity_resolver.py`; orchestrated
   `:6940-6955`; default ON via `GRAPH_RESOLVE_ENTITIES`): `resolve_entities`
   (`:418`) lists all nodes, embeds names, plans merges (pure `plan_merges`
   `:179`, or O(N) `plan_merges_fast` `:311` above
   `GRAPH_RESOLVE_MAX_NODES=1200`), executes via `runtime.merge_nodes`.
   Merge predicate: same primary label (or one generic `Entity`) **AND**
   (name exact/containment OR explicit alias OR **dossier alias from
   `actors.json`**) **AND** cosine ≥ `GRAPH_RESOLVE_SIM_THRESHOLD` (0.88) —
   dossier aliases bypass the cosine gate as authoritative ground truth
   (`:258-262`). Over-merge guards: two distinct canonicals never merge;
   typed-label bridging blocked via union-find `typed_by_root` (`:222-233`).
   Survivor = canonical/typed/longest-name node. Audit →
   `handoff/entity_merges.json`.
7. **Pruning** (§7.3) — after resolution, before priors.
8. **Structural priors** — `_get_graph_info` (`graph_builder.py:1096-1235`)
   computes weakly-connected components (union-find), top hubs, and normalized
   **degree centrality** (`name→[0,1]`, `:1167-1174`), alias-folded
   (`fold_priors_with_aliases`, `:153`) → `handoff/graph_priors.json`;
   optionally (`GRAPH_CHOKEPOINT_PRIORS`, default off) **betweenness**
   (Brandes, `:57`) + **articulation points** (Tarjan, `:95`) capped at 1500
   nodes → `graph_priors_structural.json`
   (`pipeline_orchestrator.py:7021-7057`).
9. **Concurrency sanity** — duplicate-name detection under concurrent builds
   (`:6992-7017`; `GRAPH_BUILD_CONCURRENCY=1`, >1 flagged unsafe).

### 7.3 Graph pruning (the 400-node cap)

`graph_pruner.py`. Motivation (`:1-21`): unbounded per-chunk extraction
inflates ~25 curated actors into ~740 entity nodes (~30×), 66% with degree ≤2,
~145 fully isolated — diluting the UI, centrality priors, and agent selection.

- **`plan_prune`** (pure, `:94-240`): **core set** = graph nodes whose
  normalized name matches `actors.json` canonicals ∪ aliases; **N-hop BFS**
  from core (`GRAPH_CORE_ACTOR_HOPS=2`); keep-set = core (always retained,
  unbounded) ∪ candidates ranked by `(distance, importance = mentions + degree
  + 1000·is_core, name)` under `effective_cap = max(GRAPH_MAX_ENTITIES=400,
  len(core))` and a non-core per-type cap (`GRAPH_MAX_ENTITIES_PER_TYPE=150`).
  **Delete = exact complement** — high degree or a long path to core does
  *not* exempt a node (a weak bridge cannot keep a giant component alive,
  `:11-13,203-205`).
- **`prune_graph`** (side-effecting, `:244-428`): **fail-closed guards** — if
  core count is 0 or `core_actor_coverage < GRAPH_PRUNE_MIN_CORE_COVERAGE`
  (0.8), it skips destructive deletion entirely (`:288-312`). Deletes batched
  under the per-graph write lock; UI cache invalidated; the actual surviving
  graph is **re-read** and postconditions verified (`survivor_set_matches_plan`,
  `core_survived`, `cap_satisfied`), with one bounded retry of remaining excess
  (`:341-353`); layout recomputed. Audit → `handoff/graph_prune.json`. All
  failures degrade (never break the build).
- Distinct from the destructive prune: the **UI-side display cap**
  `GRAPH_UI_MAX_NODES=400` — a degree top-K applied in
  `filter_subgraph`/`get_graph_data` (`graph_builder.py:297,1327,1382`).

### 7.4 The simulation→graph feedback loop

`zep_graph_memory_updater.py` (`GraphMemoryUpdater`): when
`SIM_GRAPH_FEEDBACK` is on, each simulation agent action is converted to a
natural-language episode (`AgentActivity.to_episode_text`, `:24-45`) and fed
back into the same graph via a worker queue with a dead-letter file
(`_zep_dead_letter/<graph_id>.jsonl`, `pipeline_orchestrator.py:4835`) —
the knowledge graph keeps evolving while the simulation runs (this powers the
"GraphRAG memory updating" overlay in the UI). At RUN completion a
"confluence barrier" joins the monitor thread and flushes
`ZepGraphMemoryManager.stop_updater` (`:7275-7287`).

---

## 8. Stage 4 — PREPARE (cast, personas, sim config)

Orchestrated at `pipeline_orchestrator.py:7065-7174`; owner:
`simulation_manager.py` (`create_simulation` → `prepare_simulation`), with
lifecycle metadata `created→preparing→ready→running→…` under
`uploads/simulations/<sim_id>/`.

### 8.1 Cast selection (ACTOR-CAST discipline)

- `ZepEntityReader.filter_defined_entities` reads graph nodes and keeps only
  ontology-defined, agent-eligible entities, using explicit classification
  signals folded into node attributes (`zep_entity_reader.py`,
  `_explicit_classification` `:33`).
- `ensure_dossier_actor_entities` (`simulation_manager.py:33`) guarantees a
  graph node or **stand-in** for every eligible `actors.json` row (partial
  ingestion cannot erase a researched actor) and emits an audit
  `actor_cast_manifest.json`, SHA-256 fingerprinted.
- `select_agent_pool` (`:130`) enforces the cast discipline
  (`ACTOR_CAST_MAX=20 < OASIS_MAX_AGENTS=80`): the pool derives **only from the
  main cast** — entities matched to a research actor that pass the tier-1/2
  agency gate — ranked by `(matched, eligible, salience×tier_weight +
  0.5·centrality_prior, influence, edge_count)` (`_rank`, `:232`).
  Media/observers are demoted to tier 3 and excluded (`ACTOR_EXCLUDE_MEDIA`);
  alias surface-forms of one real actor dedup by canonical name (`:290`).
  Legacy T3.13 selection is the degrade-safe fallback.
- Cheap filler **audience agents** are generated procedurally with zero LLM
  cost (`SIM_AUDIENCE_AGENTS`, `generate_audience_profiles`, `:846-874`).
- Archetype/tier machinery lives in `utils/actors.py`: `entity_archetype`
  (`:515`), `entity_simulation_tier` (`:581`; 1=core decider … 4=abstract),
  `is_agent_eligible` (`:614`; tier∈{1,2}), `salience_score` (`:623`),
  `is_media_entity` (`:560`), and `match_actor` (`:172`) — NFKC-normalized
  exact/alias match, then guarded fuzzy containment that **fails closed on
  ambiguity**.

### 8.2 Deterministic role contracts (no LLM)

`actor_role_prompt.py` (`ROLE_CONTRACT_VERSION="actor-role/v1"`) compiles each
cast actor's runtime identity **directly from dossier bytes** so it is
traceable and reproducible:

- `build_actor_role_contract` (`:290`) assembles identity / objectives /
  incentives / constraints / resources / vulnerabilities / incident
  relationships / beliefs / red lines / uncertainty (as-of date, horizon,
  evidence grade) / source tags — labeling missing facts as *missing* rather
  than guessing.
- `compile_actor_role_prompt` (`:464`) renders a ≤6,000-char "ROLE BRIEF"
  wrapped in `BEGIN/END UNTRUSTED DOSSIER DATA` delimiters.
- **Prompt-injection defense**: `_UNSAFE_CONTROL_PATTERNS` (`:24`) strips
  instruction-like dossier text ("ignore instructions", tool invocations,
  system-prompt exfiltration); `sanitize_untrusted_dossier` cleans recursively.
- Every prompt is SHA-256'd (`role_prompt_sha256`) and coverage validated
  against the cast manifest (`validate_role_prompt_manifest`; enforced in
  `simulation_manager.py:747-756,895-917` and re-checked at start in
  `api/simulation.py:299-334`) — **the runner refuses to launch if role
  prompts don't match the manifest** (fail-closed).

### 8.3 Persona assembly

`oasis_profile_generator.py`: `generate_profile_from_entity` (`:305`) builds an
LLM base persona from the entity's Zep ego-network context
(`_retrieve_ego_network`, `_build_entity_context`, with a parallel secondary
graph search for recall), enriched by `actor_briefing` /
`behavioral_dna_block` / `roster_block` (worldview, incentives, relational
buckets from `utils/actors.py`), then **appends the role contract**
(`:405-422`). `OasisAgentProfile` (`:47`) serializes to OASIS's exact formats:
`to_twitter_format` → CSV (`user_id,name,username,user_char,description`;
`user_char` becomes the agent system prompt) and `to_reddit_format` → JSON
keyed by `user_id`. Generation is parallel (`ThreadPoolExecutor`; parallelism
16 for HTTP providers via `PARALLEL_PROFILE_COUNT`, 3 for CLI —
`pipeline_orchestrator.py:7101-7130`), order-preserving, incremental-saving,
with rule-based fallback per actor. Per-profile-file `role_manifest_sha256`
recorded.

### 8.4 Simulation config generation

`simulation_config_generator.py` `generate_config` (`:398`) produces
`simulation_config.json` (atomic write) **stepwise** (avoiding one fragile
mega-call):

1. `TimeSimulationConfig` — simulated hours, minutes/round, diurnal activity
   curves (peak 19–22h, off-peak 0–5h).
2. `EventConfig` — hot topics, `initial_posts` (each tagged `poster_type`),
   `scheduled_events` (from research `events_to_schedule`), and an
   `initial_follows` seed graph (`build_initial_follow_graph`).
3. Per-agent `AgentActivityConfig` (batched) — activity level, posts/comments
   per hour, active hours, stance, sentiment bias, influence weight,
   interested topics, and **`gains_if`/`loses_if`** incentive stakes derived
   from the dossier.
4. Initial-post → agent assignment by `poster_type`.
5. Platform weights — recency/popularity/relevance, viral threshold,
   echo-chamber strength (community structure from `communities.json`).

The orchestrator then applies an optional **scenario overlay**
(`apply_scenario_overlay_to_config`, `pipeline_orchestrator.py:7134-7151`) and
injects a `world_state_seed` into the config (`:7156-7174`) for what-if forks.

---

## 9. Stage 5 — RUN (OASIS multi-agent simulation)

Owner: `simulation_runner.py` (~1,700 lines, classmethods over class-level
registries). Orchestrated at `pipeline_orchestrator.py:7176-7316`.

### 9.1 Launch & monitoring

`SimulationRunner.start_simulation` (`simulation_runner.py:414`):

- `total_rounds = total_hours*60/minutes_per_round` (optionally capped by
  `max_rounds`; `:568-572`).
- Picks the script (`run_parallel_simulation.py` / `run_twitter_…` /
  `run_reddit_…`, `:619-634`) and launches
  `subprocess.Popen([sys.executable, script, "--config", config_path, …],
  cwd=sim_dir, start_new_session=True)` (`:685-695`) with `PYTHONUTF8`,
  `SIM_SEED` (seed injected only into the child env), `SIM_RESUME`;
  stdout/stderr → `simulation.log`.
- A daemon **monitor thread** (`_monitor_simulation`, `:712`) tails
  `twitter/actions.jsonl` + `reddit/actions.jsonl` every 2s, parsing JSONL
  records into the live `SimulationRunState` (`run_state.json`): `round_end`
  advances rounds/simulated hours; `simulation_end` marks platform completion;
  action records become `AgentAction`s. Process exit → COMPLETED/FAILED (log
  tail captured on failure). If graph feedback is enabled, each parsed action
  is forwarded to the `GraphMemoryUpdater` (§7.4).
- The orchestrator polls `get_run_state` every 5s (`:7215-7252`) under the dual
  stall watchdogs (§4.6), then at completion joins the monitor thread, flushes
  the graph updater, and calls `SimulationRunner.write_run_summary` →
  `run_summary.json` (`:7291-7316`).
- Process control is cross-platform (`taskkill`/`killpg`);
  `register_cleanup()` kills all child sim processes on backend shutdown.

### 9.2 The OASIS round loop

`backend/scripts/run_parallel_simulation.py` (independent process):

1. Monkey-patches `open()` to default UTF-8 (OASIS reads files without
   encodings), silences OASIS loggers, loads `.env`.
2. Builds per-platform **agent graphs** from the profiles
   (`generate_twitter_agent_graph` from CSV / `generate_reddit_agent_graph`
   from JSON, imports at `:190-197`), wiring each agent to the LLM model and
   the platform action whitelist. Twitter actions (`:209`): CREATE_POST,
   LIKE_POST, REPOST, FOLLOW, QUOTE_POST, CREATE_COMMENT, SEARCH_POSTS, TREND,
   DO_NOTHING; Reddit (`:222`) adds DISLIKE_POST/COMMENT, LIKE_COMMENT,
   SEARCH_USER, REFRESH, MUTE. INTERVIEW is excluded from autonomous actions
   (IPC-only). Action tools are role-clipped per agent.
3. `oasis.make(...)` creates each env with a fresh SQLite DB
   (`<platform>_simulation.db`) and the LLM concurrency semaphore (§9.5).
4. `env.reset()`, then `initial_posts` injected as `ManualAction`s (round 0),
   throttled by `throttle_seed_follows` (`agent_dynamics.py:310`).
5. **Round loop** (`for round_num in range(start_round, total_rounds)` at
   `:3190`/`:3597`): compute simulated hour/day; pick active agents
   (`get_active_agents_for_round` — gated by per-agent `active_hours` ×
   `activity_level`, scaled by peak/off-peak multipliers and a random target
   count); issue `{agent: LLMAction()}`; `await env.step(actions)`. New DB rows
   are read back and appended to `actions.jsonl` by `PlatformActionLogger`
   (`action_logger.py` defines the JSONL schema: round-start/round-end/action/
   simulation-end). Per-round `env.step` failures are isolated behind a
   consecutive-failure circuit breaker (default 3).
6. Twitter and Reddit run **concurrently** via `asyncio.gather`.
7. After the loop the env is **not closed** — the process enters
   wait-for-commands mode, polling the IPC dir so agents can be interviewed
   against the post-simulation world; `close_env` or SIGTERM tears it down.

### 9.3 Realism layers (`agent_dynamics.py` — pure, offline-testable, gated)

- `AgentDynamicsTracker` (`:86`): per-agent `{mood, energy, opinion_strength,
  fatigue}` updated each round from received interactions
  (`extract_round_signals`, `:39`) and injected into the agent prompt as a
  one-line state (`state_line`; gate `SIM_AGENT_DYNAMICS`).
- `sample_engagement_likes` (`:245`): WTA-weighted deterministic likes fixing
  broadcast-only feeds.
- `detect_organic_ratio_collapse` (`:335`): flags posts>0/engagement==0 runs —
  **honest degradation, never fabricated activity**.
- `simulated_hours_from_rounds` (`:390`) for honest run accounting.

### 9.4 File-mailbox IPC (interviews)

`simulation_ipc.py`: Flask ↔ live sim communicate through `ipc_commands/` and
`ipc_responses/` under the sim dir.

- `SimulationIPCClient.send_command` (`:209`) atomically writes
  `<uuid>.json`, polls for the response (0.5s interval), and on timeout writes
  a `.cancel` marker.
- `SimulationIPCServer.poll_commands` (`:599`) claims commands by renaming to
  `.processing` (TOCTOU-safe), honors `.cancel`, executes, writes responses,
  and maintains `env_status.json` (`check_env_alive`, `:424`).
- Command types (`:117`): `INTERVIEW`, `BATCH_INTERVIEW`, `CLOSE_ENV`
  (`platform=None` = both platforms). Stale files swept at ≥300s (`:87`).
  Optional round-trip telemetry → `ipc_telemetry.jsonl` (p50/p95, timeout
  rate). Interview prompts get a text-only prefix (`INTERVIEW_PROMPT_PREFIX`,
  `api/simulation.py:24`) so agents don't emit tool calls; batch interviews
  capped ≤6 agents / 600s (guards against the historical 180s IPC timeout).

### 9.5 LLM usage inside the sim (`utils/oasis_llm.py`)

- `create_oasis_model` (`:557`) resolves the provider (`_resolve_provider`,
  `:481`): CLI providers → `CLIModel` (`:379`, a fake CAMEL `OpenAIModel`
  proxying to `LLMClient` and synthesizing a `ChatCompletion`); API providers →
  CAMEL `ModelFactory` (`_create_openai_model`, `:490`) with optional boost
  dual-LLM (`LLM_BOOST_*`), Kimi coding-agent UA injection (`:535`), and
  reasoning disabled via `extra_body`.
- **Tool-call emulation** (`SIM_CLI_TOOL_EMULATION`, default on): OASIS actions
  are OpenAI `tool_calls`, but CLI/text backends lack native function calling —
  the tool schema is appended to the prompt as JSON and the model's
  `{"tool":…, "arguments":…}` reply parsed back into `tool_calls`
  (`_render_tool_prompt`/`_parse_tool_call_text`, `:101-146`). Without this,
  agents produce zero actions (a hollow sim).
- **Reliability**: `_sanitize_messages`/`_wrap_openai_empty_guard`
  (`:213-253`) prevent the empty-assistant-400 cascade;
  `_wrap_openai_fallback_guard` (`:348`, `SIM_LLM_FALLBACK` default on)
  reroutes content-filter (422 `new_sensitive`) / 429 / quota failures through
  `LLMClient` (which carries retry, circuit breakers, and
  `LLM_FALLBACK_PROVIDER` failover); fallback counts → `llm_fallback.jsonl` +
  `llm_health.json` (folded back into pipeline telemetry at
  `pipeline_orchestrator.py:7544-7552`).
- **Concurrency/cost**: `get_oasis_semaphore` (`:603`) caps in-flight LLM calls
  — CLI `OASIS_CLI_SEMAPHORE` (8), API `OASIS_SEMAPHORE` (30 config default /
  24 in `.env.example`) — **divided by platform count** so dual-platform runs
  don't double concurrency. Cast discipline (≤20 vs 80 agents) cuts per-round
  calls ~4×; audience personas are rule-generated (zero LLM); decision-channel
  elicitation is batched one call per unique roster.

### 9.6 Forecast signal extraction (two layers + honest accounting)

- **(a) Voice-share metrics** — `compute_emergent_metrics`
  (`run_parallel_simulation.py:2423`, gate `SIM_EMERGENT_METRICS`): reads the
  SQLite DBs + `actions.jsonl` and computes `polarization_index`,
  `cross_stance_interaction_ratio`, `stance_trajectory`, `follow_communities`,
  information `cascades`, and `final_stance_share` (last-round stance shares
  normalized to 1, `:2462-2466`) → `{platform}_emergent_metrics.json` +
  aggregate `emergent_metrics.json`. Explicitly the *"who talked most"* signal.
- **(b) Decision channel + WorldState** — the modeled-outcome primitive, run
  **post-simulation** over the frozen action log (gate `SIM_DECISION_CHANNEL`;
  wired at `run_parallel_simulation.py:3919-3952`):
  - `run_decision_channel` (`decision_channel.py:344`) groups actions into
    per-round rosters, ranks by activation/influence, caps at
    `DECISION_CHANNEL_MAX_ACTIVE` and collapses the tail into one weighted
    `__public__` block (`_build_active_roster`, `:216`); then **one batched
    structured LLM call per unique roster** elicits each active agent's
    commitment `{scenario, magnitude, confidence}` toward a mutually-exclusive
    forecast scenario (`_elicit_round_decisions`, `:125`; abstention token
    filtered to no-op). Phase 1 fans elicitations across a bounded thread pool
    with per-roster caching; Phase 2 serially steps a single shared WorldState.
    Outputs → `world_state_trajectory.json` + `decisions.jsonl`.
  - `WorldState` (`worldstate.py:74`): a scenario-probability distribution
    seeded from research base rates, evolved by **resource-weighted
    (outcome_power × confidence) commitments** (`commitments_from_decisions`,
    `:33`) blended with the prior by calendar-gap-scaled `inertia`, with
    EWMA-delta convergence tracking and early stop. Crucially distinguishes
    **outcome power** (structural leverage over the result) from
    **voice/activation influence** (`_outcome_power_map` vs
    `_activation_weight_map`, `:172-197`). `WorldState.outcome()` (`:147`)
    yields `{shares, leader, leader_share, rounds, ewma_delta, converged,
    converged_at, uniform_prior}`.
  - The seed comes from `world_state_seed_from_actors`
    (`utils/actors.py:1842`): scenarios + base rates extracted from research
    `forecast_inputs` (numeric prob keys → probability-band midpoints →
    base-rate frequencies), flagging `uniform_prior` when base rates are
    genuinely absent rather than silently assuming 50/50.
- **(c) Honest accounting** — `run_summary.json` records organic-vs-seed
  action counts, `simulation_health`, rounds executed, simulated hours,
  LLM-fallback counts, and the dynamics-active flag, so downstream stages can
  **downgrade hollow sims instead of narrating fabricated activity**.

### 9.7 Calendar-temporal forecast mode (`SIM_TEMPORAL_MODE=calendar`, default)

The default simulation mode replaces the legacy 72-simulated-hours news-cycle
model with a **calendar-time forecast simulation**: each round is exactly one
calendar unit between the research `as_of_date` and the forecast horizon.

- **Horizon → unit → rounds** — pure module `backend/app/utils/sim_timeline.py`:
  `extract_horizon` parses the brief deterministically (4 tiers: explicit
  dates; anchored periods like "end of 2030"/"Q3 2028"/"2030年底"; relative
  spans like "next 18 months"; bare years — CJK-safe regexes; LLM fallback in
  the config generator; 12-month flagged default). `select_calendar_unit`
  picks from {day, week, half-month, month, quarter, half-year} targeting
  ~16 rounds (`SIM_CALENDAR_TARGET_MAX_ROUNDS=36` soft /
  `SIM_CALENDAR_HARD_MAX_ROUNDS=48` hard; ultra-long horizons use a
  half-year stride instead of truncating). `build_round_periods` snaps
  boundaries to the natural calendar grid (ISO Mondays, month/quarter firsts)
  with stub-period merges. Pinned behavior: "by 2030" → 18 quarterly rounds,
  "by 2035" → 19 half-year rounds, "3 weeks" → 21 daily rounds — rounds grow
  with horizon and the unit always fits the question.
- **Presence-keyed dispatch** — the config generator writes a versioned
  `temporal_config` block into `simulation_config.json` (as_of/horizon/unit/
  `round_dates` with per-round `period_start`/`period_end`/`label`); the
  runner and subprocess switch on that block's presence, so every legacy
  config/checkpoint runs the hours path byte-identically. A compat shim
  (`total_simulation_hours = n_rounds`, `minutes_per_round = 60`) keeps all
  legacy re-derivation sites correct. An explicit `max_rounds` **coarsens the
  unit instead of truncating the horizon** (`round_cap_coarsened` audit).
- **Round semantics** — every active agent receives a per-round WORLD CLOCK
  system record ("2027-Q3 (2027-07-01 → 2027-09-30) | round 8/18 | one quarter
  per round | horizon 2030-12-31") framing its action as the most
  consequential move of that period (decision/announcement/alliance;
  FOLLOW = coalition, DO_NOTHING = strategic patience), plus a one-time
  action-vocabulary hint. Diurnal `active_hours` gating is bypassed;
  **principal-cadence** actors (top cast by influence) act every round while
  background agents stay sampled.
- **Events land in real rounds** — `utils/actors.events_to_calendar_rounds`
  buckets `key_events` by exact date containment (`round_for_date`);
  beyond-horizon events are preserved in `temporal_config.beyond_horizon_events`.
- **In-band world evolution** (`SIM_DECISION_CHANNEL_INBAND`) — each round the
  decision channel elicits period commitments and steps the WorldState with
  calendar-scaled inertia plus an **entropy floor**
  (`WORLDSTATE_ENTROPY_MIX`: `lam = min(0.05, 0.0005·period_days)` mixing
  toward the researched base-rate prior, so uncertainty grows with horizon).
  `backend/app/services/world_delta.py` builds a **qualitative-only** "what
  changed last period" digest for the next round's header — numeric
  probability shares are deliberately hidden from agents (herding guard) and
  live only in `world_digest.jsonl` + the dated
  `world_state_trajectory.json` (schema v3, per-row `period_start`/
  `period_end`/`label`). No convergence early-stop: the loop always runs to
  the horizon.
- **Downstream** — the forecast spine receives the true `horizon_date`
  (fixing a bug where it got `as_of_date`), the report's world-state block
  renders dated waypoints, world-state charts use calendar-date x-axes, and
  `run_state`/`run_summary` carry `calendar_unit`, `current_period_end`,
  `coverage_end`, and horizon provenance.
- **Tests** — `test_sim_timeline.py`, `test_world_delta.py`,
  `test_calendar_event_bucketing.py`, `test_worldstate_calendar.py`,
  `test_calendar_round_loop.py`, `test_temporal_mode_contract.py` (the
  contract suite pins both modes).

---

## 10. Stage 6 — REPORT (forecast synthesis & publication)

Owner: `report_agent.py` (the largest service) + `forecast_extractor.py` +
`report_lint.py` + `report_visualizer.py` + `ensemble.py` + `backtest.py` +
`forecast_ledger.py` + `exec_brief.py`. Orchestrated at
`pipeline_orchestrator.py:7318-7461`. Nearly every enhancement is behind a
`Config` flag with a byte-identical legacy fallback; every optional step is
degrade-safe.

### 10.1 Spine-first generation

`ReportAgent.generate_report` (`report_agent.py:8216`):

1. **Signal packs before prose** (`:8317-8356`): the deterministic simulation
   **signal pack** (`_build_signal_pack`, `:2319`) and **market pack**
   (`_build_market_pack`, `:2623`) are built first, then the **forecast spine**
   is derived and pinned (`_derive_and_pin_forecast_spine`, `:2705`) — MECE
   scenarios + probabilities + resolution criteria produced *before any
   narrative*. The spine block is injected into `plan_outline` (`:7020`) so
   sections are organized around falsifiable predictions rather than
   probabilities being reverse-engineered from prose.
   `require_forecast_structure` forces framework/per-scenario/calibration
   sections whenever a spine exists.
2. **Section loop** (`:8408-8554`): serial by default, optional
   `REPORT_SECTION_CONCURRENCY` → `_generate_sections_concurrent` (`:7237`);
   context mode `full` (O(N²) prior-section text) or `brief`
   (`_build_synthesis_brief`, `:7227`). Per section:
   `_generate_section_with_retry` (`:7311`) → native tool-calling
   (`_generate_section_native`, `:7669`) or ReAct (`_generate_section_react`,
   `:7816` — `<tool_call>{…}</tool_call>` prompt-based calling for CLI
   providers, ≥3 tool calls required before a Final Answer is accepted).
   Failures get `SECTION_FAILURE_PLACEHOLDER`; an **LLM-outage circuit
   breaker** aborts early if the outline degraded and the first two sections
   fail consecutively (`:8503`) or all sections fail (`:8560`) — raising to
   FAILED instead of publishing an empty "completed" report.
3. **Per-section reflection**: `_reflect_and_maybe_revise_section` (`:7358`) —
   one cheap critique (`_critique_section_draft`, `:7443`, returns `PASS` or a
   single revision instruction) → at most one revision. Guards: anti-shrink
   (reject revisions below max(60%, char floor), `:7391`), bare-"FAIL"
   treated as no instruction (`:7484`), truncation-continue
   (`_continue_section_draft`, `:7530`), `MAX_REFLECTION_ROUNDS=3` (`:1484`).
4. **Tools available to sections** (`ZepToolsService`, `zep_tools.py`,
   instantiated at `report_agent.py:1644`): `insight_forge` (LLM decomposes
   the question into sub-queries, searches each, pulls entity details, builds
   relationship chains — `zep_tools.py`), `panorama_search` (active vs
   historical/expired facts via temporal flags), `quick_search`,
   `trace_cascade` (`:2716` — directed causal paths / N-hop causal
   neighborhoods, used for the report's **causal skeleton**:
   `report_agent.py:2643-2689`), `faction_brief` (community structure via
   `runtime.list_communities`, `:6705-6817`), and `interview_agents` (real
   OASIS interviews via the IPC bridge). Contamination defense
   (`_looks_contaminated`) rejects sections leaking CLI system-prompt text.

### 10.2 The finalization chain (strict order, each step flag-gated)

`assemble_full_report` (`:10069`) → `_post_process_report` (`:10098`) → then
(`:8585-8667`):

1. `_finalize_structured_forecast` (`:2787`) → **`forecast.json`** (§10.3).
2. `_prepend_binary_forecasts_section` (`:5836`) — **Part 1 — Binary
   Forecasts**: a deterministic table rendered *straight from `forecast.json`*
   (no LLM; `forecast_extractor.render_binary_forecasts_block:2683`,
   `upsert_binary_forecasts_block:2789`) guaranteeing prose↔JSON probability
   parity, plus a **Market Cross-Check** block.
3. `_inject_visualizations` (`:6069`) (§10.5).
4. `_apply_three_part_skeleton` (`:6019`) — **Part 2 — Framework & Synthesis**
   (one bounded LLM synthesis call, ≤~2,800 words, tightened by the
   requirement-spec `page_budget`, `:5966-5974`; must *defend* the spine
   probabilities and may never mention simulations/agents/graphs,
   `:5995-6007`), then relabels existing sections as **Part 3 — Appendix:
   Detailed Analysis**. Idempotency via `_PART1_MARKERS`/`_PART2_MARKERS`
   (`:5884`).
5. `_append_resolution_section` (`:4014`) — deterministic "How to Verify This
   Forecast".
6. `_apply_language_purity` (`:4348`) — contamination scan + inline/section
   re-translation.
7. `_apply_report_lint` (`:4513`) → `report_lint.lint_report` (§10.4).
8. `_stabilize_publish_markdown` / `_finalize_citations` (`:5278`/`:5132`) —
   `[S12]` markers resolved into a single **References** appendix +
   `citations.json`.
9. `_enforce_final_publish_audit` (`:5620`) — the authoritative read-only gate
   (§10.6).
10. `_generate_bilingual_report` (`:4937`) (§10.7).

The orchestrator feeds the agent `situation_brief(actors)`, `sources`,
`research_report`, and the structured artifacts
(quantitative/contested/timeline/graph_priors)
(`pipeline_orchestrator.py:7418-7453`); `ReportManager.save_report` persists
(`:7455`), streaming `agent_log.jsonl` + `console_log.txt` for the live UI.

### 10.3 Forecast extraction & calibration (`forecast_extractor.py`)

- **Two producers, one canonical shape** (`_assemble_forecast`, `:851`):
  spine-first `derive_forecast_spine` (`:2514` — one LLM pass over research
  inputs + simulation signals + market block + S-tier quantitative facts, with
  **anchor-and-adjust**: `base_rate_anchor` → `adjustment_rationale` → final
  probability; prompt `_SPINE_INSTRUCTIONS:2404`) and post-hoc
  `extract_structured_forecast` (`:820` — over the finished report using
  head+tail slicing, `slice_head_tail:793`, 40K-char budget).
- **Self-consistency**: K spine draws pooled to mean + spread
  (`_pool_spine_draws:2443`, `REPORT_SPINE_SELFCONSISTENCY_K`, default 5);
  wide disagreement demotes confidence (`:2507-2510`).
- **Calibration**: probabilities normalized to sum 1 with floor
  `FORECAST_PROB_FLOOR` (0.03; `_normalize_scenarios:69-108`) — avoids
  catastrophic log-loss on "realized but predicted ≈0%". Red-team
  `self_critique_forecast` (`:2912`) is **humility-monotone** (the critique can
  only lower the peak, `_enforce_humility_monotone:2951`). Optional
  `premortem_forecast` (`:2986`) widens uncertainty. Ledger-fitted
  recalibration `apply_recalibration` (`backtest.py:230`; off by default).
- **Binary forecasts** — `extract_binary_forecasts` (`:2122`): ≥`min_count`
  (default 10) **independent** yes/no forecasts (not summing to 1), each with a
  statement embedding number+date, objective resolution criteria
  (metric+threshold+date+source), theme, `horizon_year`, anchor-and-adjust,
  `proposition_id`, `scenario_membership`. Rules: **contrarian framing**
  (~40–50% below 0.5, `_BINARY_CONTRARIAN_RULE:923`) with a bounded
  low-probability top-up if spread <0.12 or all >0.5 (`:2234-2245`);
  simulation-sensitivity (rationale must cite a specific signal moving it off
  the anchor, `:2178`); circular market-quote forecasts dropped
  (`_is_circular_market_forecast:1074`). **Quality scorecard**
  (`_binary_quality:1208`): `passed` requires n≥min, stdev≥0.12, midband
  share ≤0.40, ≥3 high-conviction calls, ≥80% sharp criteria.
  **Multi-model ensemble** (`FORECAST_ENSEMBLE_MODELS`): secondary providers
  re-draw the same prompt, pooled via extremized log-odds
  (`pool_binary_forecasts:2261`). **Contract reconciliation**
  (`reconcile_forecast_contract:1929`): scenario-partition-determined binaries
  forced to the canonical implied probability; proposition/market-anchor
  integrity audited (`audit_proposition_consistency:1809`,
  `audit_market_anchor_integrity:1896`).
- **Market anchoring (deterministic two-stage)**:
  1. `anchor_binaries_to_markets` (`:1379`): one batched LLM match of
     statements × relevance-gated markets yielding `{market_id|null,
     resolution_equivalence: exact|near|loose, confidence}`; only
     ≥`FORECAST_MARKET_ANCHOR_MIN_EQUIVALENCE` (near) accepted; the anchor
     backfills **our snapshot price** — never the model's transcribed number
     (`_build_market_anchor:1327`) — with divergence computed locally.
  2. `enforce_market_divergence` (`:1447`): when |model−market| > 0.10 and the
     rationale doesn't cite the market, one bounded re-statement: the model
     either moves toward the market or keeps the divergence **and explicitly
     cites the market's implied probability**
     (`_MARKET_DIVERGENCE_INSTRUCTIONS:1291`); a rewrite that doesn't cite the
     market is rejected (probability never silently moves).
  3. `build_market_comparison` (`:1517`) → `market_comparison.json` (model vs
     implied, `abs_divergence`, `exceeds_10pp`, `rationale_cites_market`).
- **Market data client** (`utils/prediction_markets.py`): `PolymarketClient`
  (`:197`) — keyless Gamma `public-search`/`markets` + CLOB `prices-history`;
  normalizes only non-closed markets with P(yes)∈(0,1), volume ≥200
  (`_normalize_market:467`); per-event cap (`_cap_per_event:175`); LLM
  relevance gate (`score_market_relevance:764`); dual-time **requote**
  (`requote_markets:304` — research-time vs now with Δ); resolution detection
  (`_parse_resolution:134`, price ≥0.99; `fetch_resolutions:430`).
- **Repair passes** (`_run_repair_passes`, `report_agent.py:3031`): when a gate
  dimension fails — targeted single-pass repairs (citation backfill `:3277`,
  quote grounding `:3306`, placeholder resolution `:3427`, semantic citations
  `:3632`, dangling-citation repair `:3740`, simulation-leakage repair
  `:3836`), re-running affected audits once; runs *before* the publish gate so
  confidence is demoted at most once.

### 10.4 Report lint (`report_lint.py` — pure, no LLM/IO, fence-aware)

Entry `lint_report` (`:1299`) → `(cleaned_md, report)`; all functions operate
under a code-fence mask (`_fence_mask:38`).

- **Deterministic rewrites**: `[citation:…](url)` residue (`:245`); graph-edge
  dumps `A --[REL]--> B` → natural language (`rewrite_edge_dumps:260`); legacy
  simulation-agent labels → expert-panel phrasing (`rewrite_sim_labels:312`);
  raw tool-name tokens (`:360`); dangling attributions (`:381`);
  pass-narration brackets (`:417`); citation-variant normalization
  `【S1】/[S1-a]` → `[S1]` (`:438`); duplicate-sentence dedup (`:573`);
  failure placeholders (`:987`); internal telemetry/basis/graph parentheticals
  (`:789/816/865`); relation-bullet blocks (`:951`); standalone citation lines
  (`:1001`); corrupted mixed-punctuation lines (`:1015`); empty
  tables/sections (`:1046/1081`); **simulation-mechanics scrub**
  (`scrub_simulation_mechanics:1184` — ~80 regex rewrites,
  `_SIMULATION_OUTCOME_REWRITES:667`, reframing "the simulation shows" →
  "the evidence indicates" while preserving numbers/citations);
  sentence-space repair (`:1262`).
- **Detection-only**: cross-language contamination (`:455`); table-cell
  truncation (`:493`); **scenario-probability↔spine mismatch**
  (`check_scenario_probabilities:607`, ±1pt vs the spine as truth source);
  Tier-2 **leakage flags** (`LEAKAGE_PATTERNS:112` — 40+ EN+ZH patterns:
  "Simulation Agent", agent/edge counts, ontology relations, action tokens;
  `leakage_hits:638`); `outcome_focus_ok = leakage_flags == 0` (`:1363`).
- **Citation audits** (in `forecast_extractor.py`): `audit_citation_grounding`
  (`:3051` — of numeric-claim lines, the grounded fraction; reports `coverage`,
  strict `source_coverage`, and `resolved_coverage` where only markers
  resolving to a real source index count, so dangling `[S246]` can't inflate);
  `validate_citation_markers` (`:3116` — fence-aware inventory: `order`,
  `counts`, `dangling`, `uncited`); `_audit_semantic_citations`
  (`report_agent.py:3685` — each cited claim clause semantically supported by
  its source). Lint results land in `forecast.json['quality']['lint']`.

### 10.5 Visualization & PDF

`ReportVisualizer.build_all` (`report_visualizer.py:2534`) — **Plotly-first**
with a three-family degrade chain:

- **(C) Plotly interactive HTML + kaleido PNG pairs** (primary): scenario
  error bars (consuming ensemble stdev/min-max), binary dotplot,
  model-vs-market dumbbell, timeline lanes, actor network (networkx spring,
  fixed seed), influence×salience bubble, source-mix sunburst,
  quantitative-claims dots, driver tornado, market price-history, contested
  dumbbell, world-state stacked area (registrations `:2611-2691`).
- **(B) matplotlib PNG** fallback (`_run_matplotlib_family:2717`) — fills
  missing PNGs and owns comparison bars + the calibration curve
  (`build_calibration_curve:1334`).
- **(A) Mermaid** — retained as pure library helpers but **no longer emitted**
  by `build_all` (frontend/PDF couldn't render them reliably).

Optional deps probed at module load (`:57-102`); kaleido has an in-process
runtime circuit breaker (`_KALEIDO_RUNTIME_OK:102`); CVD-safe palette + CJK
font fallback (`:132-158`). `_persist_manifest` (`:2848`) writes
`viz_manifest.json` = `{schema_version:2, items:[{id,path,type,title,caption,
source,placement_hint,png_path?}], skipped:[{builder,reason}]}` — **skips are
never silent**. Placement (`report_agent._inject_visualizations:6069`,
`_place_visualizations:6230`): `placement_hint` → heading-keyword match
(`_VIZ_PLACEMENT_KEYWORDS:5889`), unmatched → a "Visual Annex".

**PDF export**: `ReportManager.export_pdf` (`report_agent.py:9546`) — pandoc +
XeLaTeX (CJK-safe) with PyMuPDF fallback (`:9356`/`:9414`), pre-rendered
mermaid (`:9190`), absolutized chart paths (`:9152`), mtime-cached.
`exec_brief.py` reuses the machinery for a single-page executive brief
(`_export_pdf_pandoc_no_toc:869`).

### 10.6 Publication gates (two, layered)

1. **`_apply_publish_gate`** (`report_agent.py:6338`, static/pure): citation
   coverage (`resolved_coverage` preferred) vs
   `REPORT_PUBLISH_GATE_MIN_COVERAGE` (0.75); probability-sum coherence
   (|Σp−1|>0.05 → hard); a residual/status-quo scenario must exist (missing →
   hard); degenerate entropy; folds in binary-quality, quote-provenance,
   numeric-consistency, implausible-stats, and final-audit integrity.
   **Epistemic** issues demote `confidence` at most one level (baseline
   preserved once via `pre_publish_confidence` so re-audits never ratchet);
   **hard** issues populate `hard_issues` and block publication.
2. **`_audit_final_published_markdown`** (`:5634`) +
   `_require_final_publish_audit` (`:5602`): authoritative, **read-only on the
   exact published bytes**; SHA-256 fingerprint of the markdown (`:5666`);
   excludes the References appendix from claim-grounding; runs
   scenario-contract, proposition-consistency, market-anchor,
   citation-marker, semantic-citation, quote-provenance, and numeric audits;
   persists `final_audit.json`; hard failures raise → FAILED.
3. **API-side**: `publication_status` (`:9009`) requires status=completed, no
   failed/partial sections, `hard_passed==True`, policy version match
   (`REPORT_FINAL_AUDIT_POLICY_VERSION=3`), fingerprint match on **both** the
   markdown and `forecast.json`, and a passing publish gate; `is_publishable`
   (`:9113`) is what the download/PDF endpoints check (`api/report.py:34,444`).

### 10.7 Bilingual output

`_generate_bilingual_report` (`:4937`): detect translation target (`:4564`);
split by H2 (`:4589`); translate chunks concurrently
(`REPORT_TRANSLATION_CONCURRENCY`); per-chunk **citation-token multiset
parity** with one retry carrying an exact token inventory (`:4982-5025`); then
a five-way hard audit — heading/table/number/marker/language signatures
(`_audit_translation_variant:4693`). Only audit-passing translations are
written (`full_report.<lang>.md`, `citations.<lang>.json`,
`final_audit.<lang>.json`); the main report is never mutated; stale
same-language artifacts are deleted on failure. Output language is decided by
`requirement_spec.detect_output_language` (`requirement_spec.py:34-45`:
explicit in-brief directive wins, else CJK-ratio sniff, default English) or
forced via `REPORT_OUTPUT_LANGUAGE`.

### 10.8 Ensemble, backtest, ledger

- **Ensemble** (`ensemble.py`; run by `_maybe_run_seed_ensemble`,
  `pipeline_orchestrator.py:7466-7473`, `N_FORECAST_SEEDS` default 3,
  concurrency `ENSEMBLE_SEED_CONCURRENCY` ≤3): `aggregate_forecasts` (`:150`)
  matches scenarios by normalized name with **semantic alignment** fallback
  (resolution-criteria token-Jaccard, `align_scenario_buckets:55`,
  `ENSEMBLE_ALIGN_MIN_OVERLAP=0.34`, same-run guard); published probability =
  extremized log-odds geometric pool (`_extremized_logodds:118`,
  `ENSEMBLE_EXTREMIZE_A=2.0`) or arithmetic mean; renormalized;
  `[p_low,p_high]` band from stdev; `agreement` = 1 − mean pairwise
  total-variation distance × support penalty (`_ensemble_agreement:348`).
  `graph_priors` are passed into every seed run so agent selection stays
  consistent (`pipeline_orchestrator.py:4298-4311`).
- **Backtest** (`backtest.py`): `score_forecast` (`:41`) — multi-class Brier +
  realized-scenario probability + log-loss; `calibration_report` (`:73`) —
  probability bins with Jeffreys-smoothed rates + credible intervals (`:105`),
  count-weighted ECE, **Murphy decomposition** (Brier = Reliability −
  Resolution + Uncertainty, `:151`), `CAL_MIN_RESOLVED` thin-evidence flag;
  `fit_recalibrator` (`:188`) — 1-parameter logit-scale slope (identity when
  <10 points).
- **Ledger** (`forecast_ledger.py`; dir from `FORECAST_LEDGER_DIR` else
  `PIPELINE_DATA_DIR/_forecast_ledger`, `:22`): `append_forecast` (`:37`)
  writes one scoring-essential entry per `forecast.json` (scenario names +
  probabilities + resolution criteria, `confidence`, `resolved=False`, plus
  `objective_signals` so the ledger doubles as a pre-resolution eval log);
  `resolution_date` defaults to horizon year-end (`:148`).
  `calibration_summary` (`:179`) surfaces historical Brier/ECE into new
  forecasts' `confidence_rationale` (`report_agent.py:2995-3005`).
  **Golden eval**: `append_golden_result` (`:84`) writes already-resolved
  golden questions into the same ledger. **Resolution monitor**:
  `resolutions.jsonl` idempotently records
  `{report_id, forecast_id, market_id, resolved_outcome, model_p,
  market_p_at_research, brier_contribution}` (`append_market_resolution:288`);
  `market_brier_summary` (`:334`) = running Brier vs resolved market truth.
  Resolution happens via `POST /api/v1/resolve/<report_id>` (Brier/log-loss →
  atomic `resolved.json`) or the `forecast_tools backtest` CLI.

---

## 11. Cross-stage seams — how every piece connects

This is the connective tissue; each row is a concrete dependency edge.

### 11.1 The `handoff/` file contract (universal interface)

Every stage reads and writes checksummed files under
`uploads/pipelines/<id>/handoff/`, manifest-verified on reuse (§4.3–4.4):

| Artifact | Producer | Consumers |
|---|---|---|
| `research_report.md` | research | ontology (document text), graph (chunk source), report (`research_report` context), dossier editor UI |
| `actor_dossier.md` | research (Track B) | ontology, graph (chunk source option), actor compaction |
| `actors.json` | research | **ontology** (central_question, cast), **graph** (`seed_actors` triplets; resolver dossier-aliases; pruner core-set), **prepare** (cast selection, role contracts, `world_state_seed`), **report** (`situation_brief`), lint (leakage vocabulary) |
| `sources.json` | research | report citations (`[S<n>]` index), publish-gate coverage |
| `timeline.json` / `quantitative.json` / `contested.json` | research | report structured context; visualizer (timeline lanes, quant dots, contested dumbbell) |
| `prediction_markets.json` / `market_price_history.json` | research | forecast anchoring (§10.3), market cross-check, price-history chart |
| `ontology.json` | ontology | graph `set_ontology`; entity reader eligibility |
| `communities.json` | graph | sim config (echo-chamber structure); report `faction_brief` |
| `entity_merges.json` / `graph_prune.json` | graph | audit / health gate |
| `graph_priors.json` | graph | **prepare** (agent ranking weight), ensemble seeds, report |
| `graph_priors_structural.json` | graph | report/UI chokepoint references |
| `cast_reconciliation.json` | research merge | prepare audit |
| `simulation_config.json` (+ overlay/world_state_seed) | prepare | run |
| `run_summary.json` / `run_state.json` / `llm_health.json` | run | report signal pack; health gate; telemetry fold-back |
| `manifest.json` | orchestrator | resume validation of everything above |

### 11.2 `actors.json` — the keystone thread

The single artifact touching every stage: research produces it → ontology reads
`central_question` + cast → graph seeds it as typed triplets *before* prose,
uses its aliases as authoritative merge evidence, and pins pruning to its
canonical names → prepare selects the cast from actors matched to it, compiles
each role contract from its exact bytes (SHA-traceable), and seeds the
WorldState from its `forecast_inputs` base rates → the report builds
`situation_brief(actors)` from it. Its `as_of_date` is validated
(`_validate_as_of_date`, `pipeline_orchestrator.py:5760`;
`RESEARCH_ASOF_MAX_LAG_DAYS`) and anchors the graph's bi-temporal facts and
each role contract's uncertainty block.

### 11.3 The knowledge graph as shared memory

Research (via MCP on re-runs) ⇄ graph ⇄ simulation ⇄ report:

- research → graph: dossiers chunked into episodes; actors seeded as triplets.
- graph → prepare: filtered eligible entities + centrality priors select and
  rank agents; ego-network context feeds personas.
- run → graph: `GraphMemoryUpdater` streams agent actions back as episodes
  (`SIM_GRAPH_FEEDBACK`), so the report's retrieval sees the simulation's
  emergent history.
- graph → report: `insight_forge` / `trace_cascade` / `faction_brief` /
  `panorama_search` retrieval; the folded causal metadata seeded in stage 3 is
  parsed back out for the causal skeleton.
- graph → research (loop closure): on scenario forks/continuations the
  orchestrator exposes the existing graph to the DeerFlow harness through the
  `drf-kg` MCP server (`RESEARCH_MCP_KG`;
  `pipeline_orchestrator.py:1122-1131,5930,6083,6540`).

### 11.4 Brief → everything

`state.prompt` (the user's question) threads verbatim through every stage:
DeerFlow `--prompt-file` → `prediction_requirement.txt`;
`project.simulation_requirement`; ontology `simulation_requirement`;
`prepare_simulation(simulation_requirement=…)`;
`ReportAgent(simulation_requirement=…)`. `requirement_spec.parse_requirement_spec`
(`requirement_spec.py:85-105`) distills `{output_language, wants_binary,
binary_min_count, page_budget, themes}` for the report finalizers.

### 11.5 Simulation signals → forecast

`run_summary.json` + `world_state_trajectory.json` + `emergent_metrics.json` →
`_build_signal_pack` → the forecast spine's simulation-sensitivity requirement
(every binary rationale must cite a specific signal) and the world-state
stacked-area chart. Voice-share (`final_stance_share`) is deliberately
segregated from the modeled outcome (`WorldState.outcome().leader`) — report
integration consumes the latter.

### 11.6 Markets: three touchpoints, one source

Polymarket data enters (1) pre-research as calibration anchors injected into
pass 0, (2) post-research as the relevance-gated `prediction_markets.json`
snapshot + price history, (3) at report time as per-binary anchors with the
10pp divergence rule and dual-time requote — always using the locally-stored
snapshot price, never a model transcription. Resolved markets later feed the
resolution monitor → calibration ledger → future confidence rationales.

### 11.7 Consistency invariants enforced across seams

- Prose probabilities ↔ `forecast.json`: Part 1 rendered from JSON (no LLM);
  lint cross-checks scenario tables ±1pt against the spine.
- Role prompts ↔ cast manifest: SHA validation at prepare **and** re-checked
  at run start (fail-closed launch).
- Citations ↔ sources: markers must resolve to real fetched-URL indices;
  translation must preserve the exact citation-token multiset.
- Deployed bridge ↔ tracked bridge: SHA sync guard before every research launch.
- Published bytes ↔ audit: SHA-256 fingerprints on both markdown and
  `forecast.json` in `publication_status`.
- Ensemble seeds ↔ base run: same `graph_priors` injected, semantic scenario
  alignment on aggregation.

---

## 12. LLM provider abstraction (three transports)

One provider selection (`Config.LLM_PROVIDER`, runtime-switchable) drives three
cooperating transports:

### 12.1 `utils/llm_client.py` — `LLMClient` (pipeline generation)

- **Families** (`:29-34`): `CLI_PROVIDERS = ('claude-cli','codex-cli')`
  (subprocess to the local CLI — `claude -p --output-format json` run in `/tmp`
  so the CLI doesn't ingest the repo's CLAUDE.md; leak mitigation) and
  OpenAI-compatible APIs (`openai`, `kimi`, `minimax`, `deepseek`, `qwen`,
  `glm`) via the `openai` SDK.
- **Provider metadata** (`config.py:793-812` `PROVIDER_META`): label,
  needs_key, deerflow_model mapping, default base/model, key env. Kimi needs
  the coding-agent `User-Agent` gateway header (`LLM_USER_AGENT` default
  `claude-cli/1.0.0`); reasoning models default `thinking: disabled`
  (`_DISABLE_THINKING_EXTRA_BODY`, `config.py:754-760`) so reasoning tokens
  don't consume `max_tokens` and return empty content.
- **Tiered routing** (`config.py:82-93`, `_model_for_tier`
  `llm_client.py:273`): `LLM_TIERED_ROUTING` (default on) sends mechanical
  calls (decomposition, JSON repair, entity extraction) to `LLM_FAST_MODEL`
  and quality calls to `LLM_STRONG_MODEL`; optional separate fast provider.
- **Retry/limits**: `MAX_RETRIES=3` with exponential backoff (`chat` `:361`,
  `chat_with_tools` `:572`); retryable = 429/timeouts/connection/5xx
  (`:41-49`); `Retry-After` honored but capped at `RETRY_AFTER_CAP=30s`
  (`:39,160-168`). **Circuit breakers**: 422 content-filter breaker and a
  429/quota breaker (`_cb_record_429`; threshold `LLM_CB_429_THRESHOLD=8`,
  cooldown 120s, `:103-143`). **Failover**: `_try_fallback` (`:420`) retries
  once on `LLM_FALLBACK_PROVIDER`. HTTP/2 + large keepalive pool; the SDK's
  own retries disabled (backoff owned here).
- **Budget/caching**: `check_budget` after every call (`:333,417`);
  content-addressed `LLMCache` (`LLM_CACHE_ENABLED`, default on).
- **Runtime switch**: `Config.apply_provider()` (`config.py:830`) under a lock
  — updates the class, mirrors into `os.environ` (so DeerFlow subprocesses
  inherit), and upserts `.env`. `POST /api/settings/llm/test` does a
  non-persisting one-token probe with SSRF-guarded base URLs.

### 12.2 `utils/oasis_llm.py` (simulation transport)

Bridges the same providers into CAMEL's `ChatCompletion` shape for OASIS —
`CLIModel` for CLI providers, `ModelFactory` for APIs — with the tool-call
emulation, empty-guard, fallback-guard, and semaphores described in §9.5.

### 12.3 DeerFlow `config.yaml` (research transport)

Independent provider selection via `DEERFLOW_MODEL` (`claude` default → Claude
Code OAuth; `codex` → ChatGPT-plan auth; `kimi/minimax/deepseek/qwen/glm` →
per-provider keys mirrored as `KIMI_API_KEY`, `MINIMAX_API_KEY`, …).
Bridge-patched providers: `claude_provider.py` (OAuth-token preference over
ambient `ANTHROPIC_API_KEY`; `THINKING_BUDGET_RATIO=0.5`; `Retry-After` cap
120s → `RetryAfterCapExceededError` fail-fast on multi-day quota 429s),
`patched_minimax.py` (strips per-message `name` fields). Harness settings
tuned for headless runs: memory/injection disabled (no cross-run
contamination), summarization at 80K tokens with a 16K recent tail,
model/subagent concurrency enforced at the provider-call boundary via patched
middleware, per-run loop-detection reset.

---

## 13. MCP servers

Both are stdio FastMCP servers consumed by the DeerFlow harness (wired via
`DEER_FLOW_EXTENSIONS_CONFIG_PATH` + `DRF_MCP_*` env), designed to **never
hang the protocol**: lazy construction on first tool call, every blocking call
in a thread under `asyncio.wait_for`, structured `{ok, …}`/`{ok:false, error}`
returns.

**`drf-kg`** (`mcp/kg_server.py`, `python -m app.mcp.kg_server --graph-id <id>`;
guard `_guarded` `:115`, timeout `DRF_MCP_KG_TIMEOUT=60s`; specs `:257`):

| Tool | Backing |
|---|---|
| `kg_search` | `search_graph` / `as_of_search` (hybrid semantic+BM25, point-in-time) — `zep_tools.py:613,918` |
| `kg_trace_cascade` | `trace_cascade` (directed causal paths / N-hop causal neighborhood) — `zep_tools.py:2716` |
| `kg_entity_summary` | `get_entity_summary` — `zep_tools.py:1335` |
| `kg_get_entities` | `get_entities_by_type` / `get_all_nodes` — `zep_tools.py:1307,1142` |
| `kg_centrality_priors` | deterministic degree centrality (no LLM) — `kg_server.py:181-211` |
| `kg_graph_statistics` | `get_graph_statistics` — `zep_tools.py:1407` |

**`drf-simulation`** (`mcp/sim_server.py`, `--sim-id <id>` /
`DRF_MCP_SIM_ID`): `sim_status` (`:218` — run_state + env liveness +
`interview_ready`; pure file reads), `sim_results` (`:238` — run_state +
timeline + top-N agents + `run_summary.json`; `partial=true` when
non-terminal), `sim_interview_agents` (`:257` — batch/single/broadcast over
the file IPC; liveness probed first; outer watchdog = inner timeout + 30s).

---

## 14. HTTP API surface

All responses use the `{success, data}` / `{success, error}` envelope.

**`/api/research`** (`api/research.py`) — the pipeline surface:
`POST /run` (start; validates depth/model; preflights credentials before spend)
· `POST /<id>/cancel` · `POST /<id>/resume` · `POST /<id>/continue`
(research_only → full) · `POST /<id>/scenario` (what-if fork at PREPARE) ·
`DELETE /<id>` · `POST /clean` (purge failed/cancelled) · `GET /status/<id>`
(aggregated 6-stage progress) · `GET /list` · `GET /preflight` ·
`GET|PUT /<id>/dossier` (read/edit the research report; PUT enforces ≥400
chars) · `GET /<id>/artifact/<name>` · `GET /<id>/progress` (merged live
track-log tail).

**`/api/graph`** (`api/graph.py`) — project CRUD (`/project/*`), the legacy
standalone build path (`POST /ontology/generate` multipart upload → ontology;
`POST /build` background-thread build — note this path omits the
seeding/communities/resolution/pruning/priors steps the orchestrator adds),
task polling (`/task/<id>`, `/tasks`), and graph reads:
`GET /data/<graph_id>` (`top_k`, `min_degree`, `slim`, `full`;
returns totals + `truncated` + precomputed positions) ·
`GET /data/<graph_id>/neighbors/<node_uuid>` (BFS ≤3) · node/edge detail ·
`POST /gc` (stale-graph GC — retains referenced + newest
`GRAPH_RETAIN_COUNT=5`; skips if any active pipeline lacks a graph_id) ·
`DELETE /delete/<graph_id>`.

**`/api/simulation`** (`api/simulation.py`, 31 routes) — entity reads
(`/entities/<graph_id>…`), lifecycle (`/create`, `/prepare` [async, auto-skips
if prepared with valid cast/role-prompt SHAs], `/prepare/status`,
`/generate-profiles`, `/start` [re-validates the role manifest, fail-closed],
`/stop`), reads (`/<id>`, `/list`, `/history`, profiles/config
+ `/realtime` + `/download`, `/run-status` + `/detail`, `/actions`,
`/timeline`, `/agent-stats`, `/posts`, `/comments`), interviews
(`/interview`, `/interview/batch`, `/interview/all`, `/interview/history`,
`/env-status`, `/close-env`).

**`/api/report`** (`api/report.py`) — `POST /generate` + `/generate/status` ·
`GET /<id>` · `/by-simulation/<sim_id>` · `/list` · `/download` ·
`/full_report.<lang>.md` · `/pdf` · `/exec-brief` (+ `.pdf`, `/digest`) ·
`/charts/<path>` · `/viz-manifest` · `DELETE /<id>` · `POST /chat` (report
agent Q&A) · `/progress` · `/sections` (+ `-partial`, `/section/<idx>`) ·
`/check/<sim_id>` · `/agent-log` (+`/stream`) · `/console-log` (+`/stream`) ·
`POST /tools/search` · `POST /tools/statistics`. Download/PDF endpoints check
`is_publishable`.

**`/api/settings`** — `GET /llm` (current + supported), `POST /llm` (runtime
switch; persists to Config + env + `.env`), `POST /llm/test` (non-persisting
probe).

**`/api/v1`** (`api/sdk.py`, opt-in via `API_V1_ENABLED`) — `POST /run`,
`GET /status/<pipeline_id>`, `GET /list`, `GET /dossier/<pipeline_id>`,
`GET /forecast/<report_id>` (structured forecast; 409 unless publishable),
`POST /resolve/<report_id>` (Brier/log-loss scoring → atomic `resolved.json`).

`GET /health` → `{status: ok}` (`__init__.py:141-143`).

**Frontend retry policy**: `requestWithRetry` (exponential backoff) is applied
only to idempotent GETs; run/generate/chat/build POSTs are deliberately never
retried — a retried POST would double-spend LLM budget (`api/research.js:19-26`,
`report.js:5`, `graph.js:7`).

---

## 15. Frontend

Vue 3 (Composition API) + Vue Router 4 + Axios + D3 v7 + Vite 7; no
Vuex/Pinia (one tiny reactive store `store/pendingUpload.js`); custom
dependency-free i18n (`src/i18n.js`: `locale`, `L`, `setLocale`; EN/中文).

Routes (`router/index.js`): `/` Home (prompt + upload + history) ·
`/research` **ResearchView** (the primary one-prompt dashboard) ·
`/process/:projectId` MainView (legacy Step 1) ·
`/simulation/:simulationId` SimulationView (Step 2) ·
`/simulation/:simulationId/start` SimulationRunView (Step 3; refreshes the
graph every 30s) · `/report/:reportId` ReportView (Step 4) ·
`/interaction/:reportId` InteractionView (Step 5 — chat + interviews).

`ResearchView.vue` polls `GET /api/research/status/<id>` (tolerating 4
consecutive failures before warning) and renders the sticky 6-stage timeline
with tabs: live research console (merged track-log tail with bounded polling
and monotonic percentages — see the LOOP-008 design in `handoff.md`), the
rendered dossier (`DossierViewer`), the D3 knowledge graph (`GraphPanel`:
zoom/pan, curved multi-edges, type-colour legend, live "GraphRAG memory
updating" overlay), the simulated social feed, and the final forecast
(`ForecastReport`), plus `PipelineHistory` and `SettingsMenu` (provider switch
+ Test connection). Everything is `setInterval` polling; Step 4 pulls
`agent-log`/`console-log` incrementally via a `from_line` cursor to render the
agent's reasoning live.

---

## 16. Configuration surface

`backend/app/config.py` (1,502 lines) is the single env-driven surface;
`.env.example` (~87KB) documents every knob. Highest-leverage groups:

| Group | Key knobs (defaults) |
|---|---|
| Provider | `LLM_PROVIDER` (claude-cli), `LLM_API_KEY/BASE_URL/MODEL_NAME`, per-provider keys, `LLM_FALLBACK_PROVIDER`, `LLM_TIERED_ROUTING`/`LLM_FAST_MODEL`/`LLM_STRONG_MODEL` |
| Research | `DEERFLOW_MODEL` (claude), `DEERFLOW_RESEARCH_DEPTH` (deep), `RESEARCH_PARALLEL_TRACKS` (3), `RESEARCH_FANOUT_WIDTH` (8), `DEERFLOW_SUBAGENTS` (true), `RESEARCH_MULTIPART_SYNTHESIS`, `DEERFLOW_RESEARCH_TIMEOUT` (depth-aware), `RESEARCH_QUALITY_FLOOR` (0.45), `RESEARCH_MIN_REPORT_CHARS` (400), `RESEARCH_MCP_KG`, `GRAPH_CHUNK_SOURCE` (dossier_only), search/fetch cache TTLs |
| Markets | `PREDICTION_MARKETS_ENABLED` (true), `PREDICTION_MARKETS_MIN_VOLUME` (200), `PREDICTION_MARKETS_MIN_RELEVANCE`, `FORECAST_MARKET_ANCHORING` (true), `FORECAST_MARKET_ANCHOR_MIN_EQUIVALENCE` (near) |
| Graph | `GRAPH_BACKEND` (auto→falkordblite), `GRAPHITI_DATA_DIR/EMBED_MODEL/EMBED_DIM/RERANKER`, `GRAPH_SEED_FROM_ACTORS`, `GRAPH_RESOLVE_ENTITIES` (on, threshold 0.88, fast path >1200 nodes), `GRAPH_PRUNE_ENABLED`, `GRAPH_MAX_ENTITIES` (400), `GRAPH_MAX_ENTITIES_PER_TYPE` (150), `GRAPH_CORE_ACTOR_HOPS` (2), `GRAPH_PRUNE_MIN_CORE_COVERAGE` (0.8), `GRAPH_UI_MAX_NODES` (400), `GRAPH_MAX_SKIPPED_RATIO` (0.3), `GRAPH_BUILD_COMMUNITIES`, `GRAPH_CHOKEPOINT_PRIORS` (off), `GRAPHITI_OP_TIMEOUT_S`, `GRAPH_RETAIN_COUNT` (5) |
| Cast/sim | `ACTOR_CAST_MAX` (20), `OASIS_MAX_AGENTS` (80), `ACTOR_EXCLUDE_MEDIA`, `SIM_AUDIENCE_AGENTS`, `OASIS_SEMAPHORE` (24–30) / `OASIS_CLI_SEMAPHORE` (8), `SIM_SEED`, `SIM_AGENT_DYNAMICS`, `SIM_EMERGENT_METRICS`, `SIM_DECISION_CHANNEL` (off), `SIM_GRAPH_FEEDBACK`, `SIM_CLI_TOOL_EMULATION` (on), `SIM_LLM_FALLBACK` (on), `PARALLEL_PROFILE_COUNT` (16) |
| Report | `REPORT_STRUCTURED_FORECAST` (on), `REPORT_FORECAST_SPINE_FIRST`, `REPORT_SPINE_SELFCONSISTENCY_K` (5), `REPORT_FORECAST_SELF_CRITIQUE`, `REPORT_PREMORTEM`, `FORECAST_PROB_FLOOR` (0.03), `FORECAST_EMIT_BINARY` / `BINARY_FORECASTS_MIN_COUNT` (10), `FORECAST_ENSEMBLE_MODELS`, `REPORT_PUBLISH_GATE` (+ `_MIN_COVERAGE` 0.75), `REPORT_FINAL_READ_ONLY_AUDIT` (policy v3), `REPORT_VISUALIZER` (true), `REPORT_PDF_EXPORT` (true), `REPORT_EXEC_BRIEF`, `REPORT_OUTPUT_LANGUAGE` (auto), `REPORT_SECTION_CONCURRENCY`, `REPORT_TRANSLATION_CONCURRENCY`, `REPORT_RECALIBRATE_FROM_LEDGER` (off) |
| Ensemble | `N_FORECAST_SEEDS` (3), `ENSEMBLE_SEED_CONCURRENCY` (2, cap 3), `ENSEMBLE_EXTREMIZE_A` (2.0), `ENSEMBLE_SEMANTIC_ALIGN`, `ENSEMBLE_ALIGN_MIN_OVERLAP` (0.34) |
| Budgets | `LLM_RUN_BUDGET_TOKENS/USD` (0 = unlimited), `LLM_COST_PER_MTOK`, `ADAPTIVE_CONTEXT` (true), `PROVIDER_CONTEXT_WINDOWS`, research ledger caps (§5.6) |
| Robustness | `PIPELINE_HEALTH_GATE` (on), `PIPELINE_RUN_STALL_S` (1800), `PIPELINE_HEARTBEAT_*`, `PIPELINE_SALVAGE_COMPLETED_ORPHANS`, `LLM_CB_429_THRESHOLD/COOLDOWN_S` (8/120), `RETRY_AFTER_CAP` (30s app / 120s research) |
| Exposure | `APP_API_TOKEN`, `APP_CORS_ORIGINS`, `APP_BLOCK_PRIVATE_URLS`, `FLASK_HOST/PORT` |
| Feature flags (off) | `API_V1_ENABLED`, `MODEL_COMPARISON_ENABLED`, `SCHEDULER_ENABLED`, `EVAL_ENABLED` |

`Config.validate()` enforces a known provider before the server starts;
`check_env_drift.py --strict` (`npm run check:env`) keeps `.env.example` and
`config.py` in sync.

---

## 17. Ops scripts & developer workflow

- **`setup.sh`** — interactive provider picker (silent key input, live
  one-token key test), scaffolds `.env`, installs root+frontend npm deps,
  builds the backend venv (**pinned Python 3.12** — camel-oasis targets ≤3.12),
  assembles `deer-flow/` from the vendor build, applies the bridge overlay,
  builds DeerFlow's isolated venv. Idempotent; env overrides `DEERFLOW_DIR/
  REPO/REF`, `SETUP_NONINTERACTIVE=1`.
- **`npm run dev`** — `concurrently` backend (:5001) + frontend (:3000).
- **`scripts/start.sh` / `npm start|stop`** — detached launcher
  (`nohup` + `disown`, pid files, redirected I/O — survives process-group
  teardown), polls `/health` (60s) + frontend (30s), opens the browser;
  `--stop` kills via `.backend.pid`/`.frontend.pid`; logs to
  `logs/{backend,frontend}.out.log`.
- **`scripts/doctor.sh` / `npm run doctor`** — default offline/instant: tool
  versions, both venvs, DeerFlow overlay, credentials for the selected
  providers. `--deep` adds live 1-token completions (both `LLM_PROVIDER` and
  `DEERFLOW_MODEL`), the ~470MB embed-model cache check (`--pull` to
  download), and free-disk checks. Exit 0/1/2 = ready/blocking/warning.
- **`scripts/smoke.sh` / `npm run smoke`** — offline inter-stage contract test
  with a stub LLM (`SIM_SEED=1337` determinism): ontology shape → graph
  frontend shape → entity filtering → sim-config + profile CSV/JSON headers →
  report outline. `SMOKE_GRAPH=1` exercises real Graphiti; `SMOKE_FULL=1` runs
  an OASIS micro-sim.
- **`scripts/salvage_orphaned_pipelines.py`** — zero-backend-import repair of
  wrongly-failed pipelines (§4.5); **dry-run by default**, `--apply` to write,
  race-guarded against pipelines that flipped back to `running`.
- **Tests**: `npm test` → `uv run pytest` over `backend/tests/` (1,500+ tests
  across report/forecast/citation/visual, actor/prepare/runner/orchestrator/
  publication, research/bridge/finalization families). `npm run lint` →
  `ruff check app`.
- **Logging**: `TimedRotatingFileHandler` → `logs/mirofish.log` (midnight
  rotation, 30-day retention); console INFO+; UTF-8 forced on Windows.

---

## 18. Design philosophy & resilience patterns

Recurring patterns you will find in essentially every module:

1. **Degrade-safe for enhancements, fail-closed for honesty.** Optional
   features sit behind flags with byte-identical fallbacks and never break a
   run; but empty graphs, hollow sims, LLM error strings posing as reports,
   unverifiable citations, and probability incoherence *block or demote* —
   the system prefers "no report" over a wrong-looking-right report.
2. **Determinism wherever an LLM isn't required.** Role contracts, Part 1
   tables, market anchors (snapshot prices), track merges, lint, pruning
   plans, visualization, and progress estimation are pure/deterministic —
   auditable and unit-testable offline.
3. **Resume-by-artifact.** Statuses are hints; SHA-verified bytes are truth
   (stage manifests, research contract, role-prompt manifests, publication
   fingerprints, bridge sync guard).
4. **Everything atomic.** `write_json_atomic` (tmp + fsync + `os.replace`)
   for every state/artifact write; staged multi-file promotion with rollback
   for the research contract; rename-claiming for IPC commands.
5. **Subprocess isolation + group kill.** Heavy LLM work runs out-of-process
   with `start_new_session=True`; watchdogs + `killpg` guarantee reapability;
   salvage prefers recovering fresh artifacts over discarding work.
6. **Budget at every layer.** Token/USD meters, tool-call ledgers,
   concurrency leases, context budgeting, semaphores divided by platform
   count, cast caps — cost control is structural, not advisory.
7. **Honest telemetry.** Skipped charts are recorded, hollow sims flagged,
   failed tracks stay in the progress denominator, budget-ledger failures
   emit degraded telemetry, and no silent truncation anywhere.
8. **Known failure modes defended in code**: CLI system-prompt leakage
   (contamination rejection + `/tmp` cwd + hook isolation), reasoning-token
   starvation (thinking disabled), Kimi UA gateway, MiniMax `name`-field 400s,
   falkordblite predicate bug, multi-day `Retry-After` quota sleeps (capped →
   fail fast), LangChain 4K summarization-tail fallback (patched), stale
   deployed bridge code (sync guard), empty-assistant 400 cascades (guards),
   contextvars non-inheritance in thread pools (warned).

Current known open items (per `handoff.md`, 2026-07-11): three legacy report
bundles remain quarantined under the policy-v3 publication gate; the
full-suite pytest run has a teardown hang (`Py_FinalizeEx` with live
`kevent`/`os.read` threads) — bounded teardown isolation is the next loop
candidate; a controlled paid/live run for before/after performance measurement
remains unauthorized.

---

## 19. Key file map

| Area | Files |
|---|---|
| Orchestration | `services/pipeline_orchestrator.py`, `services/research_progress.py`, `services/requirement_spec.py`, `models/{project,task}.py`, `utils/{atomic,telemetry,token_budget}.py` |
| Research | `deerflow_bridge/{deerflow_research,search_tools,cached_fetch,market_tools,research_budget}.py`, `deerflow_bridge/{config.yaml,patches/,skills/}`, `deer-flow/` (assembled runtime) |
| Ontology | `services/ontology_generator.py` |
| Graph | `services/graph_builder.py`, `services/graphiti_client/{client,runtime,llm_adapter,embedder,compat,falkor_driver}.py`, `services/{zep_entity_resolver,graph_pruner,zep_entity_reader,zep_graph_memory_updater,zep_tools}.py`, `utils/{zep_paging,zep_rate_limit}.py`, `mcp/kg_server.py`, `api/graph.py` |
| Prepare | `services/{simulation_manager,oasis_profile_generator,actor_role_prompt,actor_dossier_compactor,simulation_config_generator}.py`, `utils/actors.py` |
| Run | `services/{simulation_runner,simulation_ipc,agent_dynamics,decision_channel,worldstate}.py`, `backend/scripts/{run_parallel_simulation,run_twitter_simulation,run_reddit_simulation,action_logger}.py`, `utils/oasis_llm.py`, `mcp/sim_server.py`, `api/simulation.py` |
| Report | `services/{report_agent,report_lint,report_visualizer,forecast_extractor,forecast_ledger,exec_brief,ensemble,backtest}.py`, `utils/prediction_markets.py`, `api/report.py` |
| Platform | `backend/run.py`, `app/__init__.py`, `app/config.py`, `utils/{llm_client,security,logger,file_parser,dates}.py`, `services/text_processor.py`, `api/{research,settings,sdk}.py` |
| Frontend | `frontend/src/{views,components,components/research,api,router,store,i18n.js}` |
| Ops | `setup.sh`, `scripts/{start,doctor,smoke}.sh`, `scripts/salvage_orphaned_pipelines.py`, `package.json` |
| finharness transplants (§20) | Time/PIT: `services/hindcast_policy.py`, `utils/{point_in_time,deadline_dates,numeric_guards}.py`, `deerflow_bridge/{source_dates,data_tools}.py`. Research: `deerflow_bridge/{evidence_spans,derived_numbers}.py`, `utils/{quant_typing,absence}.py`, `services/{question_spec,consensus_evidence,forecast_context_packer,citation_finalization_telemetry}.py`. Simulation: `services/{decision_validation,sim_schedule_audit,sim_event_provenance,sim_period_context,sim_prior_echo}.py`. Report: `utils/probability_parse.py`, `services/{narrative_sync,logic_number,verified_facts,probability_shape,report_tool_args,forecast_counter_case,binary_targets,quantity_scoring}.py`. Evaluation: `services/{ledger_commit,forecast_resolution,eval_stats,golden_set,backbone_sensitivity,stage_scorecard,eval_bundle,value_add_stats}.py`, `utils/cost_accounting.py`, `backend/scripts/{golden_curate,golden_probe,stage_scorecard,cost_card,eval_bundle,value_add_eval,context_pack_replay}.py`. Platform: `app/config_audit.py`, `services/run_shape.py`, `utils/{llm_text,llm_recovery,provider_overrides,model_provenance,ctxpool,env_loading,numeric,canonical_json}.py`. Frontend: `frontend/src/utils/marketStatus.js` |

## 20. finharness transplants (branch `feat/finharness-transplants`)

This branch implements the roadmap in
`docs/research/2026-09-29-finharness-essence.md`. That roadmap was distilled from three repos (FinanceHarness,
StockAgent, TradingAgents) and five papers (F²Agent, the FinanceHarness paper, Nexus, TIEM and the
StockAgent paper). The research document holds the evidence, the per-package specs, the
implementation record and the open follow-ups. This section shows where each mechanism lives in
the pipeline.

**Invariants every package follows.**

- New behaviour sits behind a `Config` knob, and every knob is documented in `.env.example`.
- At its default a knob keeps output byte-identical to before, unless the package's spec explicitly turns it on by default. Most of those default-on knobs are fail-closed honesty fixes, but some are enhancements, provenance or shadow diagnostics (for example `NUMERIC_GUARD_MODE=shadow`, `MARKET_ANCHOR_PRICE_TIME=true`, `SIM_PERIOD_CONTEXT_V2=true`, `SIM_DECISION_EVENTS=true`). Each one's `.env.example` entry gives its default and what turning it off restores.
- Honesty checks fail closed (block, demote or flag). Enhancements degrade safely (log and continue).
- Artifacts are written atomically (`utils/atomic.py`).
- New bridge modules are registered in both `setup.sh` and `_DEPLOYED_BRIDGE_MODULES`, and a parity test pins the two lists.
- LLM and HTTP egress imports are restricted to approved modules by an AST import fence (`backend/tests/test_import_fences.py`, INFRA-13).
- Tests are offline and hermetic (INFRA-12):
  - the ambient environment is scrubbed;
  - a no-egress guard is active;
  - global state is reset between tests;
  - `FakeLLMClient` stands in for every model call.

### 20.1 Time and evidence integrity (hindcasts, point-in-time)

**Hindcast admission and the pin.**

- `PipelineOrchestrator.start` (and the run API routes, through `admit_hindcast_as_of`) validates a requested `as_of` and fails closed for any research engine other than v3 (TIME-7, `HINDCAST_ENABLED=false`).
- On admission it pins `options['hindcast_policy_v1']` (`services/hindcast_policy.py`, TIME-6).
- Under the pin the research child runs with `PREDICTION_MARKETS_ENABLED=false`, so no live odds reach the research, the simulation priors or the report. Reports are routed to the evaluation ledger.
- Forks carry the pin and never re-capture it.

**Point-in-time evidence gates** (`deerflow_bridge/source_dates.py` availability/gate rule, applied to search and fetch in `deerflow_bridge/research_gateway.py` (`PitPolicy`); pinned at admission by `services/hindcast_policy.py`; TIME-8, `PIT_*` knobs).

- One availability rule decides whether a source is admissible. It applies to search and fetch results, to provider date bounds and to undated sources.
- TIME-9 adds a citation wall: only admissible `[S#]` markers stay citable.
- The audit artifact `point_in_time.json` drives the hindcast integrity verdict that `forecast.json['hindcast']` reports.

**Source dates and as-of pins.**

- v3 records source publication dates in `sources.json` and in the SOURCE INDEX (`deerflow_bridge/source_dates.py`, TIME-2, `RESEARCH_SOURCE_DATES`).
- `actors.json` `as_of_date` is pinned to the plan's as-of (TIME-1, `RESEARCH_AS_OF_PIN=true`). A different model value is only recorded, under `meta.as_of_model_disagreement`.

**Markets.**

- Expired Polymarket markets never anchor a binary or seed a simulation prior (TIME-3, `PREDICTION_MARKETS_END_DATE_GATE=true`).
- Market rows record when their price was taken (`quoted_at` on a requote, `observed_at` from the research bridge, `snapshot_as_of` as an upper bound), and each anchor records `price_time` plus `price_time_basis` (requote|observed|snapshot), so a scorer knows which price the forecast saw (EVAL-6, `MARKET_ANCHOR_PRICE_TIME=true`; per-row `observed_at` from FU-11).

**Official data, vintage-pinned** (`deerflow_bridge/data_tools.py`).

- FRED/ALFRED macro series are read as of a date (TIME-10).
- SEC EDGAR company facts are restricted to filings made on or before `as_of` (TIME-11).
- Research gateway plumbing provides schemas, budgets, ledger rows and counters (TIME-12).
- TIME-13 wires both tools into the v3 engine as `macro_series` and `company_filings` (`RESEARCH_DATA_TOOLS`, default off).
  - A tool is bound only with its credential (`FRED_API_KEY`; an `SEC_EDGAR_USER_AGENT` containing an e-mail address). The reason a tool stays unbound is recorded in `meta.data_tools.disabled`.
  - The run's vintage and as-of cutoff are fixed once in `v3/data_pins.json` and reused on resume. In a hindcast that excludes same-day sources, the cutoff is the day before `as_of`.
  - Results are cited like fetched pages. Their structured values open `quantitative.json` as verified rows, and a model row that contradicts a cited data source is dropped.
- Adapted TradingAgents code is attributed in `NOTICE`.

**Quantitative sanity.**

- v3 reconciles unit-scale disagreements and flags future-dated actuals (TIME-4, `RESEARCH_QUANT_RECONCILE=true`).
- A shadow numeric guard checks published binary thresholds against the latest actuals (`utils/numeric_guards.py`, TIME-5, `NUMERIC_GUARD_MODE=shadow`).

### 20.2 Research (stage 1)

**Fetch layer.**

- A fetch-layer classifier detects extraction shells, and a provenance wall stops a shell page from verifying a fact. Each fetch call has a hard time bound (RESEARCH-1).
- Source outcomes are typed. Failures are counted honestly, credential and quota refusals are latched, and infrastructure failures are kept apart from content failures (RESEARCH-2, `RESEARCH_SOURCE_TAXONOMY`).

**Evidence handling.**

- Absence of evidence is reported with discipline: no-result text is coverage-aware, absence rules apply, and market-coverage states are explicit (RESEARCH-3, `RESEARCH_ABSENCE_DISCIPLINE`; frontend `utils/marketStatus.js`).
- Quantitative rows are typed as reported or projected, with target-date repair (RESEARCH-4, `RESEARCH_QUANT_TYPING=false`), and are checked against the fetched page of their cited source (RESEARCH-4, `RESEARCH_VERIFIED_FACTS=true`). The report side reads the typing in `utils/quant_typing.py` (RESEARCH-5).
- Findings carry verbatim evidence spans (`deerflow_bridge/evidence_spans.py`, RESEARCH-7, audit-first).

**Forecaster attribution** (RESEARCH-6, shadow only).

- Extracted facts are attributed to the forecaster who made them.
- Cross-source dispersion diagnostics show how far those forecasters disagree (`services/consensus_evidence.py`).

**Citation telemetry.** Citation-surgery telemetry is recorded for the report finalizer and for v3 QA (`services/citation_finalization_telemetry.py`, RESEARCH-9).

**Question spec** (`drf.question_spec/v1`).

- RESEARCH-11 produces it: the operational definition, the resolution source, the horizon and the deadline (`RESEARCH_QUESTION_SPEC`).
- RESEARCH-12 consumes it: the simulation horizon rung, the spine block and the resolution-section disclosure (`services/question_spec.py`, `QUESTION_SPEC_DOWNSTREAM=true`).

**Packing for the forecast prompts.**

- Deterministic context packs feed the two probability prompts (`services/forecast_context_packer.py`, RESEARCH-13, `FORECAST_CONTEXT_PACK_*`). An offline replay runs over stored handoffs (`scripts/context_pack_replay.py`).
- Each key intelligence question gets an evidence-count header and a sufficiency label, and the digest is truncated fairly (RESEARCH-10).
- Derived findings are declarative and evaluated in Decimal (`deerflow_bridge/derived_numbers.py`, RESEARCH-8, `RESEARCH_DERIVED_FINDINGS`).

### 20.3 Simulation (stages 4–5)

**Decision channel.**

- A shared validity verdict holds in-band, with coverage-aware accounting (SIM-1, `REPORT_WORLDSTATE_HIDE_INVALID=true`).
- Each elicitation reply is validated against the roster and every outcome is reason-coded (`services/decision_validation.py`, SIM-2).

**Run artifacts and context.**

- Run artifacts are kept clean: a reachability audit of scheduled events, `world_digest` rotation, and engagement samples kept out of the organic counts (`services/sim_schedule_audit.py`, SIM-3).
- Injected events never pose as actor behaviour (`services/sim_event_provenance.py`, SIM-5).
- Each period gets truthful context (`services/sim_period_context.py`, SIM-6, `SIM_PERIOD_CONTEXT_V2=true`).
- The world clock tells apart first, quiet, unavailable and not-produced periods (REPORT-6).
- The decision elicitor sees the period's scheduled events as labelled exogenous items (SIM-8).

**Diagnostics and overrides.**

- A zero-LLM prior-echo diagnostic and a pinned derivation of the ensemble seed (`services/sim_prior_echo.py`, SIM-4, `SIM_PRIOR_ECHO_DIAGNOSTIC=true`).
- Scenario overlays may carry human-authored `outcome_power` overrides (SIM-7).

### 20.4 Report and forecast (stage 6)

**Probability parsing.** Probabilities are parsed honestly (`utils/probability_parse.py`, REPORT-1, `FORECAST_PROB_STRICT_PARSE=true`). An unreadable value becomes `needs_review`; it is never coerced to 0.0 or a uniform split.

**Prompt slots and narrative.**

- Prompt slots get typed absence markers (`utils/absence.py`, REPORT-4).
- When a probability moves, a deterministic sync refreshes the stale numbers in the narrative (`services/narrative_sync.py`, REPORT-2, `REPORT_NARRATIVE_SYNC=true`).
- An alias-aware probability-slot audit runs over the outline summary and the final prose (`services/logic_number.py`, REPORT-3, `REPORT_LOGIC_NUMBER_GATE=observe`). Its zero-token slot repair stays off because known cases remain where it would rewrite a percentage that is not the scenario's probability; the guards must be extended before it is turned on (`REPORT_LOGIC_NUMBER_REPAIR=false`; it also needs `REPORT_NARRATIVE_SYNC`).

**Gates and walls.**

- The signal pack fails closed on a hollow or errored simulation (REPORT-5, `REPORT_SIGNAL_PACK_HEALTH_GATE=true`).
- Information walls are pinned (REPORT-10).

**Verified figures.**

- Research-side verification labels are written to `verified_facts.json` (REPORT-7).
- A labelled verified-figures block replaces the key-metrics table (`services/verified_facts.py`, REPORT-8).
- A shadow check compares the published figures with the verified rows and writes the `figure_provenance.json` sidecar; it never changes the report (REPORT-9, `REPORT_VERIFIED_FIGURES_CHECK=true`).

**Probability shape and markets.**

- Probability-shape telemetry is recorded (`services/probability_shape.py`, REPORT-11). An optional symmetric binary guard is behind `FORECAST_BINARY_SYMMETRIC_GUARD=false`.
- When switched on, the market-blend arithmetic for the divergence restatement is computed deterministically (REPORT-12, `FORECAST_MARKET_BLEND_ARITHMETIC=false`).
- When switched on, an evidence-cited counter-case pass runs before the final draft (`services/forecast_counter_case.py`, REPORT-13, `REPORT_COUNTER_CASE=false`).

**Agent tool calls.** The report agent's tool-call boundary tolerates malformed arguments: they are parsed leniently and validated, and up to six rejected calls per section are not charged against the tool budget (`REPORT_TOOL_MAX_REJECTED_PER_SECTION=6`; unknown-tool rejections are never charged) (`services/report_tool_args.py`, INFRA-5).

### 20.5 Evaluation, ledger and settlement

**Ledger commits and settlement.**

- A ledger commit happens after publication. It is sealed, idempotent and self-contained (`services/ledger_commit.py`, EVAL-1, `FORECAST_LEDGER_COMMIT_MODE=published`).
- Market settlement events are deterministic (`services/forecast_resolution.py`, `utils/deadline_dates.py`, EVAL-2).
- A settlement fold and a single point-in-time `admissible()` gate apply to the resolution monitor's calibration, and to the report's historical calibration only when switched on (EVAL-3, `FORECAST_LEDGER_SETTLEMENT_FOLD=false`).
- There is a manual settlement path with supersede and retract (EVAL-4).

**Golden set and scoring.**

- Small-sample statistics for golden evaluation (`services/eval_stats.py`, EVAL-7).
- Golden headline tiering separates prospective rows from hindcast rows (EVAL-8).
- The golden-set v2 contract (`services/golden_set.py`, `scripts/golden_curate.py`, EVAL-9).
- Contamination probes test the golden set (`scripts/golden_probe.py`, EVAL-12, `GOLDEN_PROBE_ENABLED=false`).
- Binaries get structured numeric targets, and a threshold-ladder audit checks them (`services/binary_targets.py`, EVAL-14, `FORECAST_BINARY_STRUCTURED_TARGET=false`).

**Run honesty and backbones.**

- `LLMClient` instances are isolated from each other (EVAL-10).
- An opt-in shadow cross-backbone sensitivity check can run on the spine (`services/backbone_sensitivity.py`, EVAL-11, `BACKBONE_CHECK_ENABLED=false`).
- Evaluation runs are kept honest: an admission pin, ledger routing and exclusion from the resolution monitor (EVAL-13).

**Scorecards and metering.**

- A per-stage scorecard sidecar (`services/stage_scorecard.py`, `scripts/stage_scorecard.py`, EVAL-15).
- Counters for unknown and invalid tool calls, plus a cross-run aggregate (EVAL-16).
- Metering is faithful (EVAL-17).
- A slim cost card, a config fingerprint and a compute-matched norm (`utils/cost_accounting.py`, `scripts/cost_card.py`, EVAL-18).

**Evaluation studies.**

- A frozen evaluation bundle (`services/eval_bundle.py`, `scripts/eval_bundle.py`, EVAL-19).
- A label-free block-movement study with an A/A noise floor (`services/value_add_stats.py`, `scripts/value_add_eval.py`, EVAL-20, `VALUE_ADD_EVAL_ENABLED=false`).
- A market-relative skill scorer in the resolution monitor (`services/backtest.py`, `scripts/resolution_monitor.py`, EVAL-5, `FORECAST_SKILL_SCORING`).

### 20.6 Platform

**LLM transport** (`utils/llm_text.py`, `utils/llm_recovery.py`, INFRA-1–4).

- Finish reasons and empty replies are normalized, and think tags are stripped.
- A structured-output repair turn retries a failed JSON reply.
- `max_tokens` escalates on an empty reply that was cut by the length limit, and a truncated JSON reply fails closed.
- Non-finite numbers are guarded, and errors are classified by HTTP status first.
- A model reply's JSON never crashes a parser: an oversized integer or deep nesting is "does not parse" and takes the repair or retry path (FU-12).

**Providers and provenance.**

- Per-provider request overrides come from one helper (`utils/provider_overrides.py`, INFRA-6).
- Model provenance records the requested and the served model for each stage (`utils/model_provenance.py`, INFRA-8).

**Runs and actors.**

- A run-shape pin, drift detection and resume-lineage guards (`services/run_shape.py`, INFRA-7).
- ContextVars propagate into worker pools, and forks inherit the safety policy (`utils/ctxpool.py`, INFRA-9).
- Actor identity is stable for non-Latin names (INFRA-11).

**Security and configuration.**

- Identifiers are contained and the local API is hardened (INFRA-10).
- The configuration is audited strictly (`app/config_audit.py`, INFRA-14, `CONFIG_STRICT_VALIDATION=true`).
- `.env` loading is shared by the standalone scripts (`utils/env_loading.py`).

### 20.7 Follow-ups

Some fixes came from triaging the merged packages' open issues. They landed as integration commits and as the follow-up packages FU-1 to FU-12. Owner decisions, the live checks still owed, and defects that predate this program are listed in the research document under "Open issues after implementation".
