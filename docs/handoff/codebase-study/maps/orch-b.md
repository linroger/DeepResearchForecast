# orch-b — Orchestrator part B: DeerFlowResearchRunner, research checkpoints, research contract/judge/sealing, extract-only salvage

Slice: `backend/app/services/pipeline_orchestrator.py` lines 2099-3856 (main branch, on-disk checkout as of 2026-10-11). All anchors are `path:line` relative to the repo root. Unless another path is given, a bare `:NNNN` means `backend/app/services/pipeline_orchestrator.py:NNNN`.

---

## Purpose & position in the pipeline

This slice is the parent-process side of **Stage 0 / RESEARCH**. It has five jobs:

1. **Run one research subprocess.** `DeerFlowResearchRunner` (`:2099`) launches the deployed DeerFlow bridge script `$DEERFLOW_DIR/deerflow_research.py` as a child process in its own session/process group. It forwards a large, parent-owned env block. It streams and parses the child's stdout into progress and token telemetry. It enforces a depth-scaled watchdog and user cancellation, salvages timed-out runs whose artifact is already on disk, and returns a handoff dict (`report`, `actors`, `sources`, `timeline`, `actor_dossier`, `research_telemetry`, …) (`:2685-2695`).
2. **Validate checkpoint lineage for resume.** It checks `research_checkpoint.json` (version 2) and computes the exact `(attempt_id, checkpoint_id, thread_id)` lineage that the strict bridge must receive (`:2974-3039`). Callers turn this into `--resume` plus `RESEARCH_BUDGET_EPOCH`/`RESEARCH_CHECKPOINT_ID` (`:2388-2403`).
3. **Check the research judge.** It validates the persisted 7-dimension research-report judge scorecard (`:3151-3213`). It binds that judge to the exact LLM-prose prefix of `research_report.md` using `_judged_prose`/`_judge_input` and the `meta.json` summary (`:3231-3309`).
4. **Manage the research contract.** It promotes a staged research generation into `handoff/` with rollback and writes `research_contract_manifest.json` last (`:3492-3604`). It also finalizes sanctioned post-processing (lint/cast reconciliation/source union) into a new sealed generation (`:3607-3726`). Validation, quality, and "sealed" predicates live here as well (`:3353-3489`).
5. **Run extract-only salvage.** After a watchdog timeout that left a report but no `actors.json`, it runs a bounded `--extract-only` child to recover the structured files (`:3729-3808`).

The slice also contains small shared helpers that later stages use: `_read_text`/`_read_json` (`:2925-2940`), `_LLM_ERROR_MARKERS` (`:2748`), `_is_degraded_dossier` (`:2814`), `_stage_walls` (telemetry, `:3811`) and `_reset_stage_attempt` (resume, `:3839`).

The orchestration of lanes, retries, budget epochs, and reuse decisions lives outside this slice, in `_run_parallel_research_tracks` (~`:11060-11630`), synthesis-only recovery (~`:10900-11050`), and the Stage-0 block of `_run` (~`:11900-12270`). This slice provides the primitives those blocks call.

---

## Walkthrough (source order)

### `class DeerFlowResearchRunner` (`:2099`)

- **`_live_procs`** (`:2103`): class-level `set[subprocess.Popen]` of in-flight research children. A proc is added right after `Popen` (`:2438`) and discarded in the read loop's `finally` (`:2570`). There is no lock; the code relies on the GIL, and `cleanup_all` iterates over a `list(...)` copy.
- **`cleanup_all()`** (classmethod, `:2105-2111`): for every live proc still running (`poll() is None`), it sends **SIGTERM** to the whole process group through `_kill_process_group(proc, signal.SIGTERM)` (`:1248`), then discards the proc. It is registered with `atexit` (`:7888`) and called from the chained SIGINT/SIGTERM/SIGHUP handler (`:7899`). In Flask debug mode it is registered only in the reloader child process (`:7880-7885`).

#### `run(prompt, handoff_dir, *, model=None, budget_run_id=None, **kwargs)` (staticmethod, `:2113-2140`) — DEFECT-2 spend-flush wrapper

- It builds a per-attempt `spend` tally (`:2124-2129`) with these fields: `tokens_in/out/total/cached=0`, `t_start=time.time()`, `model=model or Config.DEERFLOW_MODEL`, `flushed=False`.
- It calls `_run_attempt(prompt, handoff_dir, model=..., budget_run_id=..., _spend=spend, **kwargs)` (`:2131-2133`).
- `except PipelineCancelled` → `_flush_failed_research_attempt_spend(spend, "cancelled", run_id=budget_run_id)`, then re-raise (`:2134-2136`).
- `except BaseException` → flush with status `f"failed({type(exc).__name__})"`, then re-raise (`:2137-2140`). This also catches `ProviderOutageHalt` (a `BaseException`, `:258`), `KeyboardInterrupt` and `SystemExit`.
- On a successful return, nothing is flushed here. The caller meters success through `_record_research_telemetry` (`:10432`). [verifier: the only call site is `:12205`, reached only after the whole Stage 0 succeeds (lanes, global synthesis, promotion, lint, cast reconciliation). Successful attempts whose stage later fails, for example lanes before a twice-failed global synthesis (`:11565-11568`), are never metered. The def line is `:10430` (`backend/app/services/pipeline_orchestrator.py:10430`, `:12205`)]
- The flush helper (outside the slice, `:2035-2096`) is idempotent through `spend["flushed"]`. It returns early when there are no tokens or when `LLM_TELEMETRY_ENABLED` is off. Otherwise it writes one `LLMMeter.record(stage=STAGE_RESEARCH, provider="claude-cli" if model in ("claude","codex") else model, prompt_tokens, completion_tokens, latency_ms)` and logs a warning.

#### `_run_attempt(...)` (staticmethod, `:2142-2695`) — the actual launcher

Keyword parameters (`:2143-2172`):

| Parameter | Effect |
|---|---|
| `on_progress` (required) | Progress callback |
| `depth`, `model`, `language`, `subagents` | Override the corresponding Config values |
| `timeout` | Explicit watchdog budget |
| `cancel_event` | User cancellation |
| `on_spawn(pid)` | Called after the child starts |
| `resume` | Adds `--resume` |
| `kg_graph_id` | Enables the KG MCP wiring |
| `budget_db_path`, `budget_lane_id`, `budget_telemetry_path`, `budget_run_id`, `budget_epoch` | LOOP-007 ledger |
| `resume_attempt_id`, `resume_checkpoint_id` | Checkpoint lineage validated by the parent |
| `max_concurrent_subagents`, `model_concurrency_global` | Concurrency caps |
| `dual_track`, `shared_actor_track` | Track-B ownership |
| `evidence_only` | Writes `evidence_pack.md` |
| `synthesis_manifest_path` | Global synthesis |
| `research_engine` | Engine choice |
| `_spend` | DEFECT-2 tally |

Step by step:

1. **Preflight** (`:2205-2211`).
   - `deerflow_dir = Config.DEERFLOW_DIR` (default `<repo>/deer-flow`, `backend/app/config.py:1148-1151`) and `script = deerflow_dir/deerflow_research.py`.
   - If the directory is missing, it raises `RuntimeError("DeerFlow 目录不存在…")`. If the script is missing, it raises `RuntimeError("未找到 deerflow_research.py…")`.
   - It then calls `_sync_deerflow_bridge_if_stale(deerflow_dir)` (`:1441`). That helper re-syncs the tracked `deerflow_bridge/` source into the deployed copy and returns a `skill_sync_result` dict. It raises `_DeerFlowSkillSyncError`/`_DeerFlowSafetyOverlayError` (both `RuntimeError` subclasses, `:1341`/`:1345`) to **fail closed** before any child is spawned (`:1736-1738`).
2. **Expected artifact and freshness** (`:2213-2240`).
   - It runs `os.makedirs(handoff_dir, exist_ok=True)`.
   - The expected artifact is `evidence_pack.md` if `evidence_only`, else `research_report.md` (`:2214-2217`).
   - `_artifact_fingerprint(path)` returns `(size, sha256)` or `None` (`:2219-2225`, using `_sha256_file` `:7401`). `artifact_before` is captured **before launch** (`:2227`).
   - `_fresh_expected_artifact()` (`:2229-2240`) is true only when four things hold:
     - the current fingerprint exists,
     - it differs from `artifact_before`,
     - the stripped text is at least **400** characters (hard-coded),
     - for evidence lanes, the pack is not control-failure-only (`_evidence_pack_is_control_failure_only`).
   - So a stale artifact left by a previous attempt can never be "salvaged".
3. **Prompt file** (`:2244-2250`).
   - `tempfile.mkstemp(prefix=".prompt-", suffix=".txt", dir=handoff_dir)` creates the file and writes the prompt as UTF-8, then applies `chmod 0600` (best-effort).
   - The prompt is passed with `--prompt-file`, so it never appears on argv (`ps`).
   - The file is deleted in the read loop's `finally` (`:2571-2575`).
4. **Command line** (`:2251-2269`): `_detect_deerflow_python(deerflow_dir)` (`:1229`, which tries, in order, `Config.DEERFLOW_PYTHON`, `deer-flow/backend/.venv/bin/python`, `deer-flow/.venv/bin/python`, then `uv run --project deer-flow/backend python`) followed by:
   ```
   deerflow_research.py --prompt-file <tmp> --out-dir <handoff_dir>
     --model <model or Config.DEERFLOW_MODEL> --depth <depth or Config.DEERFLOW_RESEARCH_DEPTH>
     [--target-language <language or Config.DEERFLOW_RESEARCH_LANGUAGE>]   # only if truthy
     [--subagents]          # subagents if not None else Config.DEERFLOW_SUBAGENTS
     [--resume]             # if resume
     [--evidence-only]      # if evidence_only
     [--synthesis-manifest <path>]
   ```
   The bridge's argparse is at `deerflow_bridge/deerflow_research.py:16573-16595`.
5. **Watchdog budget** (`:2277-2283`).
   - `effective_depth = (depth or Config.DEERFLOW_RESEARCH_DEPTH or "standard").lower()`.
   - Precedence:
     1. a truthy `timeout` argument;
     2. if `os.environ["DEERFLOW_RESEARCH_TIMEOUT"]` is non-blank, `Config.DEERFLOW_RESEARCH_TIMEOUT` (default 10800, `config.py:1165`);
     3. otherwise `Config.deerflow_depth_budget(effective_depth)` (`config.py:1559-1578`).
   - The depth tiers are `{'quick': 900, 'standard': 7200, 'deep': 21600}` (`config.py:1553`), multiplied by **1.5** when any of `DEERFLOW_DUAL_TRACK`/`DEERFLOW_SUBAGENTS`/`RESEARCH_DEEP_FANOUT` is on (all three default on). The effective defaults are therefore 1350 / 10800 / 32400 s. An unknown depth falls back to `DEERFLOW_RESEARCH_TIMEOUT` × 1.5.
   - None of the four production callers passes `timeout` (`:10937`, `:11195`, `:11491`, `:12047`).
6. **Child env** (`:2285-2423`). The child receives `dict(os.environ)` plus the following:
   - `PYTHONUNBUFFERED=1` (setdefault, `:2286`). `RESEARCH_CHECKPOINT_ID` is **popped** (`:2289`), so the backend's ambient value never leaks into the child.
   - `RESEARCH_ENGINE` (`:2295-2301`): forced to `"legacy"` if `evidence_only` or `synthesis_manifest_path`. Otherwise it is `resolve_research_engine(research_engine)` when an engine argument was given, else `resolve_research_engine()` (`:5906`; `Config.RESEARCH_ENGINE` default `v3`, `config.py:1187`).
   - For v3 only, `DEERFLOW_RESEARCH_TIMEOUT=str(max(1,int(budget)))` (`:2302-2307`), so v3 can plan within 0.85 × the watchdog.
   - When the sync result is a dict, `DRF_RUNTIME_SKILL_SYNC_REQUIRED=1` and `DRF_RUNTIME_SKILL_SYNC=<compact sorted JSON>` (`:2308-2319`).
   - `DEERFLOW_DEEP_OPENING_RECURSION_LIMIT` (`:2322`; Config default **400**, `config.py:1556`).
   - `DEERFLOW_DUAL_TRACK` (`:2327-2337`) is `"true"`/`"false"`: an explicit `dual_track` wins; otherwise evidence lanes get `False`; otherwise `Config.DEERFLOW_DUAL_TRACK` (default True, `config.py:1228`). `RESEARCH_SHARED_ACTOR_TRACK` uses the explicit argument, else `"false"` (`:2338-2344`).
   - `RESEARCH_DEEP_FANOUT`, `RESEARCH_FANOUT_WIDTH` (default 8), `ACTOR_CAST_MAX` (20), `ACTOR_EXCLUDE_MEDIA` (true) (`:2348-2354`).
   - `PREDICTION_MARKETS_ENABLED/MAX/MIN_VOLUME/MAX_PER_EVENT/PER_QUERY/MIN_RELEVANCE` (`:2358-2365`). `PREDICTION_MARKETS_REQUOTE` and `PREDICTION_MARKETS_HORIZON_RETRY` (`config.py:1443/1449`) are **not** forwarded; the child only inherits them from `os.environ`.
   - `DEER_FLOW_MAX_CONCURRENT_SUBAGENTS = clamp(max_concurrent_subagents, 1, 8)` if given (`:2366-2368`). `RESEARCH_MODEL_CONCURRENCY_GLOBAL = max(1, n)` if given (`:2369-2371`). `RESEARCH_GLOBAL_SUBAGENT_CAP = max(1, Config…)` (default 9) (`:2372-2373`).
   - `DEERFLOW_RUN_ARTIFACT_DIR = realpath(handoff_dir)` (`:2378`), the trusted root for the prediction-market provenance ledger.
   - `_configure_research_budget_env(...)` (`:2379-2387` → `:1986-2032`):
     - If `RESEARCH_BUDGET_ENABLED` is off, it pops every `RESEARCH_BUDGET_*` key. [verifier: it pops the 12 names in `_RESEARCH_BUDGET_ENV_KEYS`, which also include `RESEARCH_NEGATIVE_CACHE_TTL_SECONDS` and `RESEARCH_NEGATIVE_CACHE_RETRIES`. These do not have the `RESEARCH_BUDGET_` prefix (`backend/app/services/pipeline_orchestrator.py:1748-1761`, `:2002-2005`)]
     - Otherwise it sets `RESEARCH_BUDGET_DB` (default `handoff_dir/research_budget.sqlite3`), `RESEARCH_BUDGET_TELEMETRY_PATH` (default `handoff_dir/research_budget.json`) and `RESEARCH_BUDGET_LANE_ID` (default `outer-track-1`).
     - It sets `RESEARCH_BUDGET_RUN_ID` and `RESEARCH_BUDGET_EPOCH`, or pops them when no value is given.
     - It sets these caps: `ATTEMPTS_GLOBAL` 1800, `SEARCH_GLOBAL` 900, `SEARCH_LANE` 360, `FETCH_GLOBAL` 450, `FETCH_LANE` 180, negative-cache TTL 600 s, and negative-cache retries 1.
   - **Resume lineage override** (`:2388-2403`): if `resume` is set and `resume_attempt_id` is non-blank, it **overwrites** `RESEARCH_BUDGET_RUN_ID`, `RESEARCH_BUDGET_LANE_ID`, and `RESEARCH_BUDGET_EPOCH = resume_attempt_id`. This replaces the caller's new `budget_epoch`. If `resume_checkpoint_id` is non-blank, it also sets `RESEARCH_CHECKPOINT_ID`. The bridge reads its checkpoint lineage from exactly these env vars (`deerflow_bridge/deerflow_research.py:916-928`, `:16747-16760`).
   - `RESEARCH_MODEL_LEASE_DB = realpath(Config.RESEARCH_MODEL_LEASE_DB or UPLOAD_FOLDER/research_model_leases.sqlite3)` (`:2408-2410`). This is always set, even when budget is disabled, because model leases are a concurrency correctness boundary.
   - KG MCP (`:2414-2423`): if `kg_graph_id` is set and `Config.RESEARCH_MCP_KG` (default true, `config.py:521`) is on, and `deer-flow/extensions_config.json` exists, the code sets `DEER_FLOW_EXTENSIONS_CONFIG_PATH` and `DRF_MCP_KG_GRAPH_ID`. If the file is missing it only logs a warning.
7. **Spawn** (`:2425-2443`).
   - It logs the command, then calls `on_progress(2, "启动深度研究子进程…")`. This call is **outside** the try/finally (see Surprises).
   - `subprocess.Popen(cmd, cwd=deerflow_dir, env=env, stdout=PIPE, stderr=STDOUT, text=True, bufsize=1, start_new_session=True)` (`:2428-2437`). Because of `start_new_session`, `os.killpg` can reach grandchildren (MCP stdio servers, sandbox shells).
   - The proc is added to `_live_procs`, then `on_spawn(proc.pid)` is called; exceptions from `on_spawn` are swallowed with a warning (`:2439-2443`).
8. **Watchdog and cancel threads** (`:2446-2472`).
   - `deadline = time.time() + budget`.
   - A `threading.Timer(budget, _watchdog)` daemon sets `timed_out["hit"]` and SIGKILLs the process group if the child is still alive.
   - If a `cancel_event` was given, a daemon thread loops `cancel_event.wait(1.0)` while the child is alive. When the event fires it sets `cancelled["hit"]` and SIGKILLs the group.
9. **Stdout read loop** (`:2477-2533`).
   - It creates a `ResearchProgressEstimator()` (`backend/app/services/research_progress.py:147`). Every non-empty line goes through `estimator.observe(line)`, which returns monotonic, phase-banded progress.
   - The line is then dispatched by substring, first match wins:
     - `[tool]`: `tool_events += 1`, call `on_progress`.
     - `[result]`: `_result_events += 1`, call `on_progress`.
     - `[stage]`: call `on_progress`.
     - `[usage]`: parse tokens with `_parse_usage_line` and `_parse_usage_cached_tokens`, and accumulate `_tok_in/_tok_out/_tok_total/_tok_cached` (total falls back to in+out when it is 0). The values are mirrored into `_spend` (`:2511-2525`). There is **no** progress callback for this branch.
     - `[ok]` or `[done]`: call `on_progress`.
     - `[error]`: call `on_progress`.
     - `[init]`: call `on_progress(max(local,4), …)`.
   - Messages are trimmed with `_tail()`.
   - The loop breaks if `timed_out["hit"]` or `time.time() > deadline` (`:2532-2533`).
   - `_spend["t_start"]` is reset to the start of the read loop (`:2489-2490`).
10. **Reap and the W9-4 slow-teardown path** (`:2534-2565`).
    - It calls `proc.wait(timeout=30)`.
    - On `TimeoutExpired` (stdout reached EOF but the process group has not exited within 30 s), it SIGKILLs the group and waits another 10 s (`returncode=-9` if that also times out).
    - It then accepts the lane as alive (`returncode=0`, `timeout_salvaged`, `on_progress(95, …)`) only in these cases:
      - evidence lane: `_fresh_expected_artifact()`;
      - non-evidence: fresh report **and** `_track_artifacts_survived(handoff_dir)`.
    - Otherwise it raises `RuntimeError("研究子进程收尾超时（30s）且产物不完整…")`.
11. **`finally`** (`:2566-2575`): cancels the watchdog, SIGKILLs the group if the child is still alive, discards the proc from `_live_procs`, and unlinks the prompt file.
12. **Post-exit decision ladder** (`:2577-2644`). Checks run in this order:
    1. `cancelled` → raise `PipelineCancelled("深度研究已取消")` (`:2577-2578`).
    2. `timed_out` (`:2583-2617`):
       - If the artifact is fresh, it logs a warning, calls `on_progress(95, …)`, and sets `returncode=0` / `timeout_salvaged`. Then, only for non-evidence lanes where `RESEARCH_EXTRACT_ONLY_SALVAGE` is not in {0,false,no} (env-only, default true, `:2602-2603`) and `handoff_dir/actors.json` does **not** exist, it calls `_run_extract_only_salvage(...)` with the same `env`. Any `Exception` is swallowed with a warning (`:2604-2612`).
       - Otherwise it raises `RuntimeError("DeerFlow 研究超时（>{budget}s，depth=…）…")`.
    3. `returncode != 0` and not salvaged → `RuntimeError("DeerFlow 研究子进程失败 (exit=N)：<last stdout line>")` (`:2618-2619`).
    4. Artifact missing → `RuntimeError("DeerFlow 研究未产出 <artifact>")` (`:2620-2621`). Empty after strip → `RuntimeError("<artifact> 为空")` (`:2623-2625`).
    5. Degraded-text guard (`:2631-2639`): raise if `Config.RESEARCH_MIN_REPORT_CHARS` (default 400, 0 disables) is set and the stripped length is below it, **or** if the length is under 400 (hard-coded) and any `_LLM_ERROR_MARKERS` substring is present.
    6. Evidence lane that is control-failure-only → `RuntimeError(... "refusing synthesis admission")` (`:2640-2644`).
13. **Actor dossier admission** (`:2650-2665`).
    - Evidence lane: if dual-track is enabled, call `_load_fresh_evidence_lane_actor_dossier(handoff_dir, prompt=prompt)`, which **raises** on any provenance defect and so fails the lane. Otherwise use `""`.
    - Normal run: read `actor_dossier.md` directly.
    - Either way, if the dossier is non-empty but `_is_degraded_dossier` or control-failure-only, replace it with `""` and log a warning.
14. **Structured reads** (`:2666-2668`): `actors.json`, `sources.json`, `timeline.json` through `_read_json`, which returns `None` on missing or unparsable files.
15. **Telemetry and return** (`:2670-2695`).
    - `research_telemetry = {model, depth, tokens_in, tokens_out, tokens_total (or in+out), tokens_cached, tool_calls, results, wall_s}`.
    - It calls `on_progress(100, "研究完成（报告|证据包 N 字）")`.
    - It returns `{report, report_path, evidence_pack (report if evidence_only else None), actor_dossier, actors, sources, timeline, exit_code, research_telemetry}`.

### Usage-line parsing (`:2698-2736`)

- **`_USAGE_RE`** (`:2701-2703`): `tokens in=(\d+|None)\s+out=(\d+|None)\s+total=(\d+|None)`. The bridge emits this from `deerflow_bridge/deerflow_research.py:6349`, `:10181` and `deerflow_bridge/research_gateway.py:1859`.
- **`_parse_usage_line(line)`** (`:2706-2715`): returns `(in, out, total)` with `None` mapped to 0, or `None` when the regex does not match.
- **`_USAGE_CACHED_RE`** (`:2722`): `(?:^|\s)cached=(\d+)(?!\S)`. **`_parse_usage_cached_tokens(line)`** (`:2725-2736`) searches only **after** the `tokens in=… total=…` triple, so `cache_write=` and `prompt_cached=` never match. It returns 0 when the field is absent (legacy engine).

### Small helpers

- **`_tail(s, limit=160)`** (`:2739-2744`): strips the line, drops everything up to the first `"] "` (timestamp/level prefix), and truncates to 160 characters plus `…`. It is also used by the parallel-track aggregator (`:11159`).
- **`_LLM_ERROR_MARKERS`** (`:2748-2754`): `"The configured LLM provider"`, `"LLM request failed"`, `"unprocessable_entity"`, `"new_sensitive"`, `"Error code: 4"`, `"Error code: 5"`. Other users of this tuple: `:6246` (a separate short-output guard), `_is_degraded_dossier`, and `_control_failure_block`.
- **`_EVIDENCE_BLOCK_RE`** (`:2757-2758`): a line consisting only of `<!-- evidence-block:N -->`.
- **`_control_failure_block(text)`** (`:2761-2791`): returns True when any of the following holds:
  - the block is empty;
  - its first line starts with `SUBAGENT_OUTCOME: BLOCKED`;
  - it parses as a JSON dict whose `error` is `research_budget_exhausted` or `llm_provider_unavailable`;
  - it contains any LLM error marker;
  - it contains `research_budget_exhausted` (case-insensitive) together with one of the status phrases `status: blocked`, `no admissible evidence`, `cannot fetch`, `research halted`, and similar.
- **`_evidence_pack_is_control_failure_only(text)`** (`:2794-2811`): "mirror the bridge gate".
  - If evidence-block markers exist, the text is split into per-marker blocks; trailing `\n\n---` separators are trimmed except on the last block, and empty blocks are dropped.
  - If there are no markers and the text starts with `# Internal Evidence Lane Pack`, the pack counts as zero blocks (header only means failure).
  - Otherwise the whole text is one block.
  - Returns True when there are no blocks or every block is a control failure.
- **`_is_degraded_dossier(text)`** (`:2814-2823`): an empty dossier returns False (empty means missing, not degraded). A dossier shorter than `RESEARCH_MIN_REPORT_CHARS` (when that is non-zero) returns True, as does one containing any `_LLM_ERROR_MARKERS` substring, **at any length**.

### `_load_fresh_evidence_lane_actor_dossier(handoff_dir, *, prompt)` (`:2826-2922`)

This admits only the Track-B dossier produced by **this** evidence-lane attempt, because track directories are reused across resumes and mtime is not trustworthy. Every failure raises `RuntimeError`: [verifier: almost every failure. `int(coverage.get("tier_1_2_actor_count") or 0)` is outside any try, so a non-numeric string raises `ValueError` and a list or dict raises `TypeError`, not `RuntimeError`. Both still fail the lane (`backend/app/services/pipeline_orchestrator.py:2887`)]

1. `meta.json` must be a dict with `status=="completed"`, `workflow_mode=="evidence_only"`, `question==prompt` (exact string), `actor_dossier_generated is True`, and `actor_dossier_required is True` (`:2840-2854`).
2. `actor_dossier.md` must be non-empty, not degraded, and not control-failure-only. Its `sha256(utf-8)` must equal `meta.actor_dossier_sha256` (`:2856-2870`).
3. `actor_dossier_coverage.json` must read as bytes and parse as a dict with `accountable is True`, `schema_version=="actor-intelligence/v1"`, and a non-zero `tier_1_2_actor_count`. It must equal `meta.actor_dossier_coverage`, and `sha256(raw bytes)` must equal `meta.actor_dossier_coverage_sha256` (`:2872-2894`).
4. If `meta.actor_dossier_judge_sha256` is non-blank, `actor_dossier_judge.json` bytes must hash to it and its verdict must not be `FAIL` (`:2900-2921`). An absent hash is accepted, meaning a degraded judge.

On success it returns the dossier text.

### File readers (`:2925-2940`)

- `_read_text(path)` returns `""` on **any** exception. It opens in text mode, so universal-newline translation applies.
- `_read_json(path)` returns `None` if the file is missing or on any exception.

### Checkpoints (`:2943-3075`)

- **`_has_research_checkpoint(handoff_dir)`** (`:2947-2953`): true when `research_checkpoint.json` exists with size > 0. Only tests call it (`backend/tests/test_research_checkpoint.py:322-329`); production resume uses lineage validation instead (see Surprises).
- **`_research_checkpoint_identity(checkpoint)`** (`:2956-2971`): `"checkpoint_" + sha256(json.dumps({version, thread_id, question_hash, depth, run_id, attempt_id, lane_id, completed_passes, fetched_source_count, gaps}, ensure_ascii=False, sort_keys=True, separators=(",",":")))[:24]`. This mirrors the bridge's `_checkpoint_identity` (`deerflow_bridge/deerflow_research.py:931-950`). It is also used by actor-lineage reception (`:5117`).
- **`_validated_research_checkpoint_lineage(handoff_dir, *, prompt, depth, run_id, lane_id, expected_attempt_ids=None)`** (`:2974-3039`) returns `{}` (a fresh start) unless all of the following hold:
  - `research_checkpoint.json` is a dict with `version == 2`;
  - `thread_id` and `attempt_id` are non-blank;
  - `question_hash == _actor_question_hash(prompt)`, which is the first 16 hex characters of the sha256 of the whitespace-collapsed, lowercased question (`:5016-5018`);
  - `depth`, `run_id` and `lane_id` match as strings;
  - when `expected_attempt_ids` is not None, `attempt_id` is in the non-blank allowlist (an empty set rejects everything);
  - `completed_passes` is a list of non-blank strings, `gaps` is a list of strings, and `fetched_source_count` is a non-bool int ≥ 0;
  - the stored `checkpoint_id` equals the recomputed identity.

  On success it returns `{"attempt_id", "checkpoint_id", "thread_id"}`. Callers pass `expected_attempt_ids=_research_budget_attempt_ids(state)`, the set of `state.options["research_budget_epochs"][*].epoch` (`:1806-1812`).
- **`_validated_research_checkpoint_attempt_id(...)`** (`:3042-3059`): a compatibility projection that returns only `attempt_id`. **No callers** anywhere.
- **`_track_artifacts_survived(handoff_dir)`** (`:3062-3075`): requires `research_report.md` to be at least 400 characters after stripping. It then returns True if `actors.json` exists, or if the checkpoint has a truthy `completed_passes`. It is used only by W9-4 (`:2551`).

### `_preserve_research_attempt_progress(source_dir, handoff_dir, *, attempt, outcome, detail="")` (`:3078-3137`)

This keeps forensic evidence from a failed or cancelled global-synthesis staging directory before the caller deletes it.

- If `source_dir/research_progress.log` is missing or is a symlink, it returns None.
- Otherwise it copies the log to `handoff_dir/research_attempts/global_synthesis_<max(1,attempt)>_<outcome sanitized to [A-Za-z0-9_-]>_<uuid12>.log`. It then appends the line `"<utc> [error|warn] global synthesis attempt N <outcome>: <detail≤1000 chars>"`, using `error` when the outcome is `failed`.
- It copies these sibling sidecars as `<stem>.<name>` when they are regular files: `research_report.md`, `research_report_judge.json`, `research_report_refinement_candidate.md`, its `_judge.json`, `research_report_failure_candidate.md`, its `_judge.json`, and `meta.json`.
- It returns the destination path. An `OSError` produces a warning and None.
- Callers: `:10968`, `:10983` (synthesis-only recovery) and `:11522`, `:11532` (global synthesis).

### Contract constants (`:3140-3172`)

- `_RESEARCH_CONTRACT_FILENAME = "research_contract_manifest.json"`.
- `_RESEARCH_CONTRACT_FILES` (16 root files): `research_report.md`, `actor_dossier.md`, `actor_dossier_coverage.json`, `actor_dossier_judge.json`, `actors.json`, `sources.json`, `actor_intelligence_lineage.json` (`ACTOR_INTELLIGENCE_LINEAGE_FILENAME`, `:109`), `timeline.json`, `quantitative.json`, `contested.json`, `prediction_markets.json`, `market_price_history.json`, `research_report_judge.json`, `research_progress.log`, `meta.json`, `charts.json`. The `charts/` tree is handled separately.
- `_RESEARCH_JUDGE_DIMS` (7): `thesis_specificity`, `base_rate_usage`, `mechanism_chains`, `quantitative_density`, `contrarian_coverage`, `length_vs_target`, `citation_coverage`.
- `_RESEARCH_JUDGE_CRITICAL` (4): `thesis_specificity`, `mechanism_chains`, `contrarian_coverage`, `citation_coverage`.
- `_RESEARCH_JUDGE_FATAL_GAP_RE`: matches truncat\*, "mid-sentence", "cut off", "not/never delivered|provided|included|completed", "no (renderable) actual/source-data table(s)", "chart/visualization ideas/specifications alone|only|without", "incomplete … citation|marker|table|section|list|forecast|scenario|milestone|deliverable", and the Chinese 截断/未写完/未完成/只有…规格|图表想法/没有…真实数据表|来源数据表. It is case-insensitive.

### Judge validators

- **`_research_judge_scores(scorecard)`** (`:3175-3193`) returns the 7-tuple of floats, or None when the schema is invalid. It requires a dict whose verdict is `PASS` or `FAIL` (case-insensitive) and whose `scores` dict has keys **exactly** equal to the 7 dimensions. Each value must be an int or float (not bool), finite, and within `[0, 5]`.
- **`_research_judge_passes(scorecard)`** (`:3196-3213`) returns True only when all of these hold:
  - the schema is valid and the verdict is `PASS`;
  - no `gaps[]` entry matches the fatal regex;
  - if env `RESEARCH_REPORT_JUDGE_STRICT` is in {1,true,yes,on}, `min ≥ 4`;
  - `min ≥ 3`;
  - every critical dimension is ≥ 4;
  - the mean is ≥ 4.0.
- **`_research_contract_quality_errors(handoff_dir, *, require_judge=False)`** (`:3216-3228`) returns one of:
  - `[]`;
  - `["research_report_judge_missing"]` (only when `require_judge`);
  - `["research_report_judge_malformed"]`;
  - `["research_report_judge_failed"]`.

  This is the **publication-quality** gate, separate from integrity. Its only caller is Stage-0 reuse (`:11930`), with `require_judge = isfile(evidence_synthesis_manifest.json)`.
- **`_research_judge_contract_errors(root, entries, report)`** (`:3231-3309`) is the judge-to-prose **binding** check.
  - The judge is required when any of these holds: `meta.depth == "deep"`, `research_report_judge.json` is in the manifest entries, `meta.research_report_judge` is a dict, or `meta.global_synthesis_judge` is a dict.
  - If required, it checks in this order, stopping at the first fatal error:
    1. Both `research_report_judge.json` and `meta.json` must be manifest entries, or it returns `judge_required_artifact_missing:<list>`.
    2. The scorecard schema must be valid, or it returns `judge_scorecard_schema_invalid`.
    3. `_judged_prose` and `_judge_input` must be dicts, or it returns `judge_input_identity_missing`.
    4. `chars = int(_judged_prose.chars)` must parse, or it returns `judge_prose_chars_invalid`.
    5. `0 < chars ≤ len(report)` and `scope == "llm-prose"` must hold, or it returns `judge_prose_boundary_invalid:…`.
  - The remaining checks accumulate:
    - `sha256(report[:chars].encode())` must equal `_judged_prose.sha256`, else `judge_prose_hash_mismatch:…`.
    - `_judge_input` must equal exactly `{"report_chars":chars,"input_chars":chars,"input_sha256":prose_sha,"truncated":False}`, else `judge_input_identity_mismatch`.
    - `meta.research_report_judge` must exist, else `judge_meta_summary_missing`. Its `verdict`, `scores`, `passed` (`is` the value recomputed by `_research_judge_passes`), `judged_prose_sha256`, `judged_prose_chars` and `judge_scope=="llm-prose"` must all match, else `judge_meta_summary_mismatch`.
    - If `meta.global_synthesis_judge` is present, it must equal the summary, else `global_judge_summary_mismatch`.
  - `chars` counts Python characters (code points), not bytes. This lets deterministic annexes (markets/charts) follow the judged prose without breaking the binding.
- **`_validate_research_judge_contract`** (`:3312-3318`): a bool wrapper. **No callers.**

### Contract integrity

- **`_research_contract_path(handoff_dir)`** (`:3321-3322`) returns `handoff_dir/research_contract_manifest.json`.
- **`_research_contract_entries(root)`** (`:3325-3350`) returns `{relpath: {"bytes", "sha256"}}`. It covers each of `_RESEARCH_CONTRACT_FILES` that exists as a file (`isfile`, which follows symlinks) plus every regular, non-symlink file under `charts/` (`os.walk`, symlinked subdirectories pruned, sorted). It raises `RuntimeError("cannot fingerprint research artifact: …")` if a hash fails.
- **`_research_contract_validation_errors(handoff_dir)`** (`:3353-3415`) returns a list of error codes.
  - The manifest must be a dict with `version == 1`, else `manifest_missing_or_version_invalid`.
  - `files` must be a dict containing `research_report.md`, else `manifest_files_invalid_or_report_missing`.
  - For each entry, it records one of these problems and moves to the next entry:
    - `manifest_entry_invalid` for a non-string key, a non-dict value, or an absolute path;
    - `artifact_path_escape` when the realpath leaves the root;
    - `artifact_missing`;
    - `artifact_size_mismatch`;
    - `artifact_sha256_mismatch`.
  - `research_report.md` shorter than 400 characters after stripping → `report_incomplete`. Otherwise it appends the judge binding errors.
  - Any `_RESEARCH_CONTRACT_FILES` member present on disk but absent from the manifest → `unmanifested_optional_artifact:<name>`.
  - If `charts/` exists, the set of actual chart files must equal the manifested set, else `chart_artifact_set_mismatch:missing=…,extra=…`.
  - `OSError`, `ValueError` and `TypeError` become `validation_exception:…`.
- **`_validate_research_contract(handoff_dir)`** (`:3418-3420`) returns `not errors`. Callers: `:5047` (actor reception), `:11921` (Stage-0 reuse), and `_finalize_research_contract`.

### Sealing and the legacy manifest

- **`research_dossier_is_sealed(handoff_dir)`** (`:3423-3441`) returns True if any of these is true:
  - the contract manifest **exists** (validity is not checked);
  - `actor_intelligence_lineage.json` exists;
  - `actors.json` is a dict carrying a dict `actor_intelligence_contract`.

  The API uses it to set `sealed` in GET (`backend/app/api/research.py:439`) and to refuse `PUT /dossier` with 409 (`backend/app/api/research.py:720-733`).
- **`refresh_research_artifact_manifest(pipeline_id, handoff_dir, filenames)`** (`:3444-3474`) handles legacy, unsealed edits.
  - It loads `handoff/manifest.json` through `PipelineManager.load_artifact_manifest` (`:1113`). If the manifest is empty or missing it returns `[]`.
  - It builds a probe `PipelineState(pipeline_id, prompt="", handoff_dir=…)`. For each `(name, path)` in `PipelineOrchestrator._stage_artifact_specs(probe, STAGE_RESEARCH)` (`:9500-9520`, names such as `report` and `dossier`=actors.json) whose realpath was edited, it rebuilds the entry with `_manifest_entry_for` (`:7452`), keeps the previous `produced_at`, adds `human_edited_at=_utcnow()`, and stores it.
  - It writes the manifest atomically when anything changed (`:1129`) and returns the refreshed **spec names**, not filenames.
  - Caller: `backend/app/api/research.py:767`.
- **`_research_report_is_judge_bound(handoff_dir)`** (`:3477-3489`): the manifest must be a dict with `version==1`, and `files` must be a dict containing `research_report_judge.json`. A non-dict manifest (single-lane/v3, which have no contract) returns False. The comment says this used to raise `AttributeError`. Caller: lint gating (`:12087`).

### `_promote_research_contract(source_dir, handoff_dir, *, meta_patch=None)` (`:3492-3604`)

1. It realpaths both directories and creates `root`. It sets `generation = uuid4().hex`, makes `stage = mkdtemp(".research-stage-<gen>-", dir=root)` and `rollback = mkdtemp(".research-rollback-<gen>-", dir=root)`, and initializes the trackers `moved_old`, `installed_new`, `charts_installed`, `old_charts_moved` and `old_contract_moved` (`:3505-3516`).
2. **Stage** (`:3518-3544`).
   - It copies each existing `_RESEARCH_CONTRACT_FILES` file from the source with `shutil.copy2`, and `charts/` with `copytree`.
   - If `meta_patch` is given, it applies `staged_meta.update(meta_patch)` (an empty dict when meta is missing or invalid) and writes it with `write_json_atomic`.
   - If the staged report is shorter than 400 characters after stripping, it raises `RuntimeError("staged research contract has no complete report")`.
   - It computes the entries and builds `manifest = {version:1, generation, created_at:_utcnow(), files:entries}`.
3. **Move the old generation out** (`:3546-3557`): it moves the existing contract manifest, every existing root contract file, and `charts` (`lexists`) into `rollback/` with `os.replace`.
4. **Install** (`:3559-3567`): it moves the staged files into the root with `os.replace`, then the staged `charts`.
5. **Manifest last** (`:3569-3576`): it writes `research_contract_manifest.json` atomically, then re-runs `_research_contract_validation_errors(root)`. Any error raises `RuntimeError("promoted research contract validation failed: …")`, listing the first 8 errors.
6. On success it returns the manifest.
7. On **any** `Exception` (`:3578-3601`):
   - It unlinks `contract_path` **unconditionally** (see Surprises) and unlinks the installed new files.
   - It removes `charts` if they were installed, restores `moved_old`, `charts` and the old contract from `rollback/`, then removes stage and rollback (inner finally) and re-raises.
8. The outer `finally` also removes `stage` and `rollback`.

Callers: global synthesis (`:11581`, `meta_patch={"parallel_research": …}`), synthesis-only recovery (`:11040`, `meta_patch` with `parallel_research` and `synthesis_recovery`), and `_finalize_research_contract` (`:3724`).

### `_finalize_research_contract(handoff_dir, research)` (`:3607-3726`)

This seals sanctioned post-processing (report lint, cast reconciliation, effective source union, meta) as a new generation without ever mutating the producer generation in place.

- If there is no contract manifest, it returns **None** (legacy and single-lane paths: no-op) (`:3630-3631`).
- If the root contract is currently invalid, it raises `"research contract changed before sanctioned finalization"` (`:3633-3636`).
- `research["report"]` must be a string of at least 400 characters after stripping (`:3638-3642`).
- If the contract is judge-bound and `report != root research_report.md`, it raises `"post-judge research report mutation rejected…"` (`:3643-3649`).
- Type gates (`:3650-3667`): `actors` must be a dict or None, `sources` a list or None, `meta` a dict or None. Otherwise it raises.
- **No-op fast path** (`:3672-3678`): if the root report text equals `report` and actors, sources and meta are each None or JSON-equal to the root, it returns the existing manifest.
- Otherwise it copies the root contract files plus `charts/` into `final_source = mkdtemp(".research-final-", dir=root)`. It atomically rewrites only the changed `research_report.md` (`write_text_atomic`), `actors.json`, `sources.json` and `meta.json` (`write_json_atomic`) (`:3680-3708`).
- If the new entries equal `existing_manifest.files` byte-for-byte, it returns the existing manifest (`:3710-3715`).
- It re-validates the root and raises `"research contract changed during sanctioned finalization"` if anything changed (`:3720-3723`). It then calls `_promote_research_contract(final_source, root)` without a `meta_patch` (`:3724`).
- `final_source` is always removed in the `finally` (`:3725-3726`).
- Caller: Stage-0 finalization (`:12267`), after lint and `forecast_inputs` injection.

### `_run_extract_only_salvage(deerflow_dir, handoff_dir, prompt, model, depth, language, env, on_progress) -> bool` (`:3729-3808`)

- If `deerflow_research.py` is missing, it returns False (`:3744-3746`).
- The timeout is `max(1, int(env RESEARCH_EXTRACT_ONLY_TIMEOUT or "600"))`, falling back to 600 on `ValueError` (`:3747-3750`). This knob is env-only and not in Config.
- **Prompt source** (`:3754-3766`): it prefers `handoff_dir/prediction_requirement.txt` (written by the bridge) when that file is non-empty. Otherwise it writes the prompt to a 0600 `.extract-prompt-*.txt` temp file in `handoff_dir`.
- `cmd = <python> deerflow_research.py --extract-only --prompt-file <f> --out-dir <handoff_dir> --model <model> --depth <depth> [--target-language <lang>]` (`:3768-3778`). There is no `--subagents`, `--resume` or `--evidence-only`.
- It calls `on_progress(96, "超时打捞：补跑结构化抽取…")`, swallowing `Exception` only (`:3781-3784`).
- It then calls `subprocess.run(cmd, cwd=deerflow_dir, env=env, stdout=PIPE, stderr=STDOUT, text=True, timeout=_timeout, start_new_session=True)` (`:3786-3790`). Output is captured but **discarded**.
  - Exit 0 → info log and True.
  - Non-zero → warning and False.
  - `TimeoutExpired` or `OSError`/`SubprocessError` → warning and False.
  - The temp prompt is deleted in the `finally` (`:3803-3808`).
- The bridge forces the legacy engine for `--extract-only` regardless of the inherited `RESEARCH_ENGINE=v3` (`deerflow_bridge/deerflow_research.py:16403-16415`). It also requires an existing report of at least `RESEARCH_EXTRACT_ONLY_MIN_CHARS` (`deerflow_bridge/deerflow_research.py:16847-16852`).
- The caller ignores the returned bool (`:2607-2610`).

### `_stage_walls(state) -> dict[str, float]` (`:3811-3836`)

- For each `state.stages` item whose `started_at` and `finished_at` both parse (`_parse_iso`, `:303`) with dt ≥ 0, it stores `walls[name] = seconds`.
- It also adds `walls["ensemble"]` from `state.options["ensemble_wall"]` (`started_at`, `finished_at`), wrapped in try/except.
- Caller: `build_stage_telemetry(state.pipeline_id, _stage_walls(state))` (`:13443`).

### `_reset_stage_attempt(stage)` (`:3839-3854`)

Sets `status="pending"`, `progress=0`, `message=""`, `error=None`, `started_at=None`, `finished_at=None`. Clearing both timestamps keeps a retried stage's wall clock to the final attempt only. Callers: the resume path (`:8163`, force-report reset; `:8171`, the failed or cancelled current stage) and the continue-to-full path (`:8253`, every non-research stage).

---

## Control flow

**One research lane, as run by the single-track caller `:12047`:**

```
Stage-0 (_run, ~:11900)
  ├─ reuse check: _research_contract_path exists? → _validate_research_contract (:11921)   [verifier: the contract branch is entered only after the _report_candidate gate passes (root research_report.md at least 400 stripped chars, hard-coded, :11906-11909); with no candidate report it goes to synthesis recovery if evidence_synthesis_manifest.json exists (:11955-11959)]
  │      → _research_contract_quality_errors(require_judge=evidence manifest exists) (:11930)
  ├─ _validated_research_checkpoint_lineage(handoff_dir, prompt, depth, run_id, lane "outer-track-1",
  │      expected_attempt_ids=_research_budget_attempt_ids(state))           (:11996)
  ├─ _activate_research_budget_epoch → (db, telemetry, epoch)                (:12037)
  └─ DeerFlowResearchRunner.run(... resume=bool(attempt_id), resume_attempt_id, resume_checkpoint_id ...)
        └─ _run_attempt
             preflight → _sync_deerflow_bridge_if_stale (fail closed)        (:2211)
             fingerprint expected artifact (before)                         (:2227)
             write .prompt-*.txt (0600)                                     (:2244)
             build cmd + budget + env (+ budget env, resume lineage, KG MCP) (:2251-2423)
             on_progress(2) → Popen(start_new_session)                       (:2426-2437)
             Timer watchdog + cancel watcher                                 (:2456, :2471)
             read stdout → estimator/on_progress/usage tally                 (:2493-2533)
             wait(30) [W9-4 teardown salvage]                                (:2534-2565)
             finally: kill group if alive, unlink prompt                     (:2566-2575)
             cancelled? → PipelineCancelled
             timed_out? → fresh artifact? salvage (+ _run_extract_only_salvage) : RuntimeError
             rc/empty/short/error-marker/control-failure gates               (:2618-2644)
             dossier admission, JSON reads, telemetry, return dict           (:2650-2695)
  └─ (post) lint (:12087 _research_report_is_judge_bound) → _finalize_research_contract (:12267)
```

**Multi-lane (legacy global-synthesis) path:**

- `_run_track` (`:11175-11240`) calls the lineage check per `track_<k>/` directory with lane `outer-track-<k>`, then `DeerFlowResearchRunner.run(..., evidence_only=global_synthesis, dual_track=research_dual_track_for_outer_lane(idx, …))`. Only the broad baseline lane owns Track B.
- Global synthesis then runs at most **2 attempts** (`for attempt in range(1, 3)` at `:11473`; log text "尝试 %d/2"). Each attempt uses a fresh `synthesis_dir` mkdtemp and `DeerFlowResearchRunner.run(..., synthesis_manifest_path=manifest_path)`, which forces legacy.
  - On failure or cancellation: `_preserve_research_attempt_progress(...)` then `rmtree(synthesis_dir)` (`:11520-11545`).
  - On success: `_promote_research_contract(synthesis_source_dir, handoff_dir, meta_patch=…)` (`:11581`).
- Synthesis-only recovery runs at most **2 attempts** (`:10922`). It reuses validated evidence lanes and promotes at `:11040`.

**Retries:** `DeerFlowResearchRunner` itself **never** retries the main research. The only extra subprocess it launches is the one extract-only salvage. Bounded retries live in the callers listed above. Crash/timeout retries come from pipeline resume, which calls `_reset_stage_attempt` (`:8171`) and then re-enters Stage 0, where checkpoint lineage decides between `--resume` and a clean start.

**Cancellation:**

- `cancel_event` comes from `PipelineOrchestrator._cancel_events[pipeline_id]`. The cancel watcher kills the process group, and the runner raises `PipelineCancelled`.
- In addition, `on_progress` (the stage updater `:8958-8969`) itself raises `PipelineCancelled`/`ProviderOutageHalt` whenever the event is set or the outage breaker trips. Any progress callback can therefore abort the attempt; inside the read loop, the `finally` cleans up.

---

## Data & artifacts

| Path (relative to `handoff_dir` unless noted) | R/W | Who | Notes |
|---|---|---|---|
| `.prompt-*.txt` | W/del | `_run_attempt` `:2244-2250`, `:2571-2575` | 0600; prompt kept off argv |
| `research_report.md` / `evidence_pack.md` | R | `_run_attempt` `:2214-2240`, `:2623` | Freshness = (size, sha256) differs from pre-launch; ≥400 chars |
| `actor_dossier.md` | R | `:2659-2660`, `:2856` | Track-B dossier; degraded → `""` |
| `meta.json` | R | `:2840`, `:3242` | Evidence-lane provenance; judge summary (`research_report_judge`, `global_synthesis_judge`, `depth`) |
| `actor_dossier_coverage.json` | R (bytes) | `:2872-2894` | `schema_version=="actor-intelligence/v1"`, `accountable`, `tier_1_2_actor_count` |
| `actor_dossier_judge.json` | R (bytes) | `:2900-2921` | sha must match `meta.actor_dossier_judge_sha256`; verdict ≠ FAIL |
| `actors.json`, `sources.json`, `timeline.json` | R | `:2666-2668` | Returned as parsed JSON or None |
| `research_checkpoint.json` | R | `:2947`, `:2994`, `:3074` | v2 keys: `version, thread_id, question_hash, depth, run_id, attempt_id, lane_id, completed_passes[], fetched_source_count, gaps[], checkpoint_id` |
| `prediction_requirement.txt` | R | `:3755` | Preferred prompt file for extract-only salvage |
| `.extract-prompt-*.txt` | W/del | `:3759-3766`, `:3803-3808` | Fallback salvage prompt |
| `research_attempts/global_synthesis_<n>_<outcome>_<uuid12>.log` (+ `.<sidecar>` copies) | W | `:3098-3131` | Forensic copies from a synthesis staging dir |
| `research_contract_manifest.json` | R/W | `:3355`, `:3570` | `{version:1, generation:<uuid hex>, created_at, files:{relpath:{bytes, sha256}}}`, written **last** |
| `.research-stage-<gen>-*`, `.research-rollback-<gen>-*`, `.research-final-*` | temp dirs | `:3509-3510`, `:3680` | Always removed in `finally` |
| `charts/**` | R/W | `:3333-3341`, `:3522-3524`, `:3564-3567` | Regular non-symlink files fingerprinted |
| `handoff/manifest.json` (legacy I-4-3 artifact manifest) | R/W | `:3454`, `:3473` | Entries `{path, sha256, bytes, produced_by_stage, produced_at, schema_ok, human_edited_at}` |
| `deer-flow/extensions_config.json` | R (exists) | `:2415-2417` | KG MCP wiring |
| `research_budget.sqlite3`, `research_budget.json` | path only | `_configure_research_budget_env` `:2006-2009` | Default ledger paths when the caller passes none |
| `uploads/research_model_leases.sqlite3` | path only | `:2408-2410` | Cross-process model lease DB |

**In-memory structures:**

- `spend` dict (`:2124`).
- `timed_out`/`timeout_salvaged`/`cancelled` single-key dicts used as cross-thread flags (`:2448-2462`).
- `research_telemetry` (`:2670-2680`).
- Return dict (`:2685-2695`).
- `_live_procs` class set (`:2103`).

---

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `DEERFLOW_DIR` | `<repo>/deer-flow` | Child cwd and script location | `backend/app/config.py:1148`; used `:2205` |
| `DEERFLOW_PYTHON` | unset → autodetect `.venv`, then `uv run` | Interpreter prefix | `config.py:1153`; `:1229-1245` |
| `DEERFLOW_MODEL` | `claude` | `--model` and telemetry model | `config.py:1156`; `:2255`, `:2127` |
| `DEERFLOW_RESEARCH_DEPTH` | `deep` | `--depth` and budget tier | `config.py:1159`; `:2256`, `:2277` |
| `DEERFLOW_RESEARCH_LANGUAGE` | unset (None) | `--target-language` only when truthy | `config.py:1163`; `:2258-2260` |
| `DEERFLOW_RESEARCH_TIMEOUT` | 10800 | Used as the budget **only if present in `os.environ`**; also forwarded to v3 as the effective budget | `config.py:1165`; `:2280-2281`, `:2307` |
| `DEERFLOW_DEPTH_BUDGETS` (code constant) | quick 900 / standard 7200 / deep 21600, ×1.5 when dual-track, subagents or fanout is on | Watchdog | `config.py:1553`, `:1559-1578` |
| `DEERFLOW_SUBAGENTS` | true | `--subagents` | `config.py:1168`; `:2261` |
| `DEERFLOW_DUAL_TRACK` | true | Child `DEERFLOW_DUAL_TRACK` (evidence lanes default false) | `config.py:1228`; `:2327-2337` |
| `DEERFLOW_DEEP_OPENING_RECURSION_LIMIT` | 400 | Forwarded | `config.py:1556`; `:2322` |
| `RESEARCH_ENGINE` | `v3` | Engine; lane contracts are forced to legacy | `config.py:1187`; `:2295-2301` |
| `RESEARCH_DEEP_FANOUT` / `RESEARCH_FANOUT_WIDTH` | true / 8 | Forwarded | `config.py:1172/1174`; `:2348-2350` |
| `ACTOR_CAST_MAX` / `ACTOR_EXCLUDE_MEDIA` | 20 / true | Forwarded | `config.py:1362/1368`; `:2353-2354` |
| `PREDICTION_MARKETS_ENABLED/MAX/MIN_VOLUME/MAX_PER_EVENT/PER_QUERY/MIN_RELEVANCE` | true/20/200/3/15/5 | Forwarded | `config.py:1423-1438`; `:2358-2365` |
| `RESEARCH_GLOBAL_SUBAGENT_CAP` | 9 | Forwarded (≥1) | `config.py:1205`; `:2372` |
| `RESEARCH_MODEL_LEASE_DB` | `uploads/research_model_leases.sqlite3` | Forwarded as realpath | `config.py:1216`; `:2408` |
| `RESEARCH_MCP_KG` | true | KG MCP env when `kg_graph_id` is set | `config.py:521`; `:2414` |
| `RESEARCH_BUDGET_ENABLED` (+ `RESEARCH_BUDGET_*` caps) | true | Ledger env injection, or removal when off | `config.py:528`; `:1986-2032` |
| `RESEARCH_MIN_REPORT_CHARS` | 400 (0 disables the length gate only) | Report and dossier degraded gate | `config.py:511`; `:2631`, `:2820` |
| `RESEARCH_EXTRACT_ONLY_SALVAGE` | true (env-only) | Enables ITEM-14 salvage | `:2602-2603`; `.env.example:552` |
| `RESEARCH_EXTRACT_ONLY_TIMEOUT` | 600 s (env-only) | Salvage wall clock | `:3748`; `.env.example:553` |
| `RESEARCH_REPORT_JUDGE_STRICT` | off (env-only) | Judge PASS requires all 7 dimensions ≥ 4 | `:3206`; `.env.example:137` |
| `LLM_TELEMETRY_ENABLED` | true | Failed-attempt spend flush | `config.py:58`; `:2061` |

**Child env written by the parent** (output contract):

- `RESEARCH_ENGINE`
- `DEERFLOW_RESEARCH_TIMEOUT` (v3 only)
- `DRF_RUNTIME_SKILL_SYNC_REQUIRED`, `DRF_RUNTIME_SKILL_SYNC`
- `DEERFLOW_DEEP_OPENING_RECURSION_LIMIT`
- `DEERFLOW_DUAL_TRACK`, `RESEARCH_SHARED_ACTOR_TRACK`
- `RESEARCH_DEEP_FANOUT`, `RESEARCH_FANOUT_WIDTH`
- `ACTOR_CAST_MAX`, `ACTOR_EXCLUDE_MEDIA`
- `PREDICTION_MARKETS_*` (6)
- `DEER_FLOW_MAX_CONCURRENT_SUBAGENTS`, `RESEARCH_MODEL_CONCURRENCY_GLOBAL`, `RESEARCH_GLOBAL_SUBAGENT_CAP`
- `DEERFLOW_RUN_ARTIFACT_DIR`
- `RESEARCH_BUDGET_*`
- `RESEARCH_CHECKPOINT_ID` (popped, then optionally set)
- `RESEARCH_MODEL_LEASE_DB`
- `DEER_FLOW_EXTENSIONS_CONFIG_PATH`, `DRF_MCP_KG_GRAPH_ID`
- `PYTHONUNBUFFERED`

---

## External calls

| Target | Kind | Anchor | Notes |
|---|---|---|---|
| `$DEERFLOW_DIR/deerflow_research.py` (deployed copy of `deerflow_bridge/deerflow_research.py`) | subprocess `Popen` | `:2428-2437` | `start_new_session=True`, stdout+stderr merged, line-buffered text. The child makes all LLM, search and fetch calls; the parent makes none. |
| Same script with `--extract-only` | subprocess `run` | `:3786-3790` | Bounded by `RESEARCH_EXTRACT_ONLY_TIMEOUT` |
| `os.killpg(getpgid(pid), sig)` | signals | `:1248-1262` via `:2110`, `:2454`, `:2468`, `:2542`, `:2569` | SIGKILL (default) for watchdog, cancel and teardown; SIGTERM for `cleanup_all` |
| `LLMMeter.record(stage="research")` | telemetry | `:2079-2087` via `:2135`, `:2138` | Only on failed or cancelled attempts |
| `_sync_deerflow_bridge_if_stale` | filesystem sync + lock | `:2211` → `:1441` | Can fail closed |
| SQLite budget and lease DBs | indirect (paths only) | `:2379-2387`, `:2408` | Opened by the child |
| KG MCP servers | indirect (child) | `:2414-2418` | Through `extensions_config.json` |
| `PipelineManager.load/write_artifact_manifest` | filesystem JSON | `:3454`, `:3473` | `uploads/pipelines/<id>/handoff/manifest.json` (`:1108-1133`) |

The parent makes no HTTP or LLM calls anywhere in this slice.

---

## Cross-module edges

**Inbound (who calls into this slice):**

- `DeerFlowResearchRunner.run`: synthesis-only recovery `:10937`; parallel lanes `_run_track` `:11195`; global synthesis `:11491`; single-track Stage 0 `:12047`.
- `DeerFlowResearchRunner.cleanup_all`: `atexit` at `:7888`; signal handler at `:7899`.
- `_validated_research_checkpoint_lineage`: `:11182` (per track), `:11996` (single track).
- `_research_checkpoint_identity`: `:3032`, `:5117` (actor-lineage reception).
- `_preserve_research_attempt_progress`: `:10968`, `:10983`, `:11522`, `:11532`.
- `_promote_research_contract`: `:11040`, `:11581`, `:3724`.
- `_finalize_research_contract`: `:12267`.
- `_validate_research_contract`: `:5047`, `:11921`, `:3633`, `:3720`.
- `_research_contract_quality_errors`: `:11930`.
- `_research_contract_path`: `:5040`, `:10616`, `:11911`, `:12098`, `:12170`.
- `_research_report_is_judge_bound`: `:12087`.
- `research_dossier_is_sealed`: `backend/app/api/research.py:439`, `:720`.
- `refresh_research_artifact_manifest`: `backend/app/api/research.py:767`.
- `_is_degraded_dossier`: `:3873` (`_load_research_handoff`).
- `_LLM_ERROR_MARKERS`: `:6246`.
- `_read_text`/`_read_json`: dozens of sites across the module (for example `:3866`, `:5040-5151`, `:11624-11705`).
- `_tail`: `:11159`.
- `_stage_walls`: `:13443`.
- `_reset_stage_attempt`: `:8163`, `:8171`, `:8253`.

**Outbound (what this slice calls):**

| Callee | Anchor |
|---|---|
| `Config` | `backend/app/config.py` |
| `_sync_deerflow_bridge_if_stale` | `:1441` |
| `_detect_deerflow_python` | `:1229` |
| `_kill_process_group` | `:1248` |
| `_configure_research_budget_env` | `:1986` |
| `_flush_failed_research_attempt_spend` | `:2035` |
| `resolve_research_engine`, `RESEARCH_ENGINE_V3/LEGACY` | `:5888-5934` |
| `ResearchProgressEstimator` | `backend/app/services/research_progress.py:147` |
| `_sha256_file` | `:7401` |
| `_actor_question_hash` | `:5016` |
| `_manifest_entry_for` | `:7452` |
| `PipelineOrchestrator._stage_artifact_specs` | `:9500` |
| `PipelineManager` | `:1113`, `:1129` |
| `write_json_atomic`, `write_text_atomic` | `backend/app/utils/atomic.py:53`, `:20` |
| `_utcnow` | `:293` |
| `_parse_iso` | `:303` |
| `PipelineCancelled` | `:248` |

**Tests touching this slice:**

- `backend/tests/test_research_checkpoint.py`
- `test_research_contract_finalization.py`
- `test_loop010_global_synthesis.py`
- `test_orchestrator_research_wiring.py`
- `test_pipeline_actor_contract.py`
- `test_research_engine_v3.py`
- `test_research_gateway.py`
- `test_research_round3_parent.py`
- `test_research_spend_flush.py`
- `test_wave9_orchestrator.py`
- `test_sessionb_judge_normalization.py`

---

## Invariants, gates, validation

1. **Fail closed before spawn.** A bridge, skill or safety-overlay sync failure raises before any child exists (`:2211`, `:1736-1738`).
2. **Prompt never on argv.** The prompt goes through a 0600 temp file (`:2244-2253`). Salvage prefers `prediction_requirement.txt` (`:3755-3757`).
3. **Parent owns checkpoint identity.** `RESEARCH_CHECKPOINT_ID` is always popped from the inherited env (`:2289`) and is set only from a parent-validated lineage (`:2396-2403`).
4. **Lane contracts run legacy.** `evidence_only` or `synthesis_manifest_path` forces `RESEARCH_ENGINE=legacy` (`:2295-2297`). The bridge independently forces legacy for `--extract-only`.
5. **Exactly one Track-B owner.** Evidence lanes default `DEERFLOW_DUAL_TRACK=false` (`:2331`). Only an explicitly dual-track evidence lane may return a dossier, and only after meta/sha/coverage/judge provenance checks (`:2650-2657`, `:2826-2922`).
6. **Salvage only fresh output.** Both timeout salvages require the expected artifact's (size, sha256) to differ from its pre-launch fingerprint, at least 400 characters, and, for evidence lanes, a pack that is not control-failure-only (`:2229-2240`). W9-4 additionally requires `_track_artifacts_survived` for report lanes (`:2549-2552`).
7. **Report admission gates** (`:2620-2644`): the file exists and is non-empty; it is at least `RESEARCH_MIN_REPORT_CHARS`; it is not a short (<400) error-marker string; and an evidence pack is not control-failure-only.
8. **Checkpoint resume requires all of:** v2, non-blank thread/attempt, question-hash/depth/run/lane equality, an allowlisted attempt, well-typed pass/gap/count fields, and a recomputed identity equal to the stored one (`:2997-3034`).
9. **Judge PASS policy:** verdict PASS, no fatal gap, min ≥ 3 (≥ 4 in strict), all 4 critical dimensions ≥ 4, mean ≥ 4.0 (`:3196-3213`).
10. **Judge-to-prose binding:** `sha256(report[:chars])` equals the judged sha; `_judge_input` exactly matches untruncated identity; the meta summary mirrors the scorecard and the recomputed pass (`:3276-3308`).
11. **Manifest-last contract.** The manifest is written only after all files are installed, then fully re-validated; any failure rolls back (`:3569-3601`). [verifier: rollback is not complete. (a) A staging-phase failure unlinks the previous valid manifest, which is never restored (`:3580-3581` vs `:3546-3548`; Surprise 6). (b) If a restore `os.replace` raises, the inner `finally` deletes `rollback/` (`:3598-3600`). (c) Only `Exception` is caught (`:3578`). A `BaseException` mid-swap skips the restore, and the outer `finally` deletes `rollback/`, which holds the prior generation (`backend/app/services/pipeline_orchestrator.py:3602-3604`)] Validation rejects missing, size- or sha-mismatched, path-escaping and unmanifested contract files, and mismatched chart sets (`:3353-3415`).
12. **No post-judge prose mutation.** Finalization refuses to change a judge-bound report (`:3644-3649`). Lint is audit-only for judge-bound and single-lane reports (`:12087-12100`).
13. **Sealed dossiers are not editable.** `PUT /dossier` returns 409 when the manifest exists, the lineage file exists, or `actors.json` has an `actor_intelligence_contract` (`:3435-3441`; `backend/app/api/research.py:720`).
14. **Spend is metered exactly once.** Success is metered by the caller; failure and cancel are metered by the `run` wrapper, made idempotent by `spend["flushed"]` (`:2134-2140`, `:2054-2056`). [verifier: overstated. Failed or cancelled attempts are metered at most once, and only when tokens > 0 and `LLM_TELEMETRY_ENABLED` is on (`:2059-2062`). Successful attempts are metered only at `:12205`, after all of Stage 0 completes. Successful lanes or synthesis attempts in a stage that later raises (for example `:11565-11568`, a promotion failure, or `_finalize_research_contract` raising) are metered zero times. Extract-only salvage tokens are never metered (`backend/app/services/pipeline_orchestrator.py:3786-3790`)]

---

## Failure modes & recovery

| Failure | Detection | Result |
|---|---|---|
| `DEERFLOW_DIR` or script missing | `:2207-2210` | `RuntimeError`; spend flush is a no-op (0 tokens) |
| Bridge/skill sync unverifiable | `:2211` | `_DeerFlowSkillSyncError`/`_DeerFlowSafetyOverlayError` (RuntimeError) |
| User cancel | cancel watcher `:2464-2469` or `on_progress` raising (`:8962-8963`) | Process group SIGKILLed → `PipelineCancelled` (`:2578`); spend flushed as `cancelled` |
| Provider-outage breaker | `on_progress` raises `ProviderOutageHalt` (`:8968-8969`) | Propagates as a BaseException; spend flushed as `failed(ProviderOutageHalt)` |
| Watchdog expiry with no fresh artifact | `:2613-2617` | `RuntimeError("DeerFlow 研究超时…可降低研究深度，或…DEERFLOW_RESEARCH_TIMEOUT")` |
| Watchdog expiry with fresh artifact | `:2586-2612` | Treated as success (exit_code 0); optional extract-only salvage; any salvage failure only logs |
| stdout EOF but process group lingers >30 s | `:2536-2565` | Kill; artifacts complete → lane survives, else `RuntimeError` |
| Non-zero exit | `:2618-2619` | `RuntimeError` containing the last stdout line |
| Missing, empty, short or LLM-error report | `:2620-2639` | `RuntimeError` |
| Evidence lane holds only control failures (budget exhausted, provider down, BLOCKED) | `:2640-2644` | `RuntimeError` ("refusing synthesis admission") |
| Baseline evidence lane dossier has stale or invalid provenance | `:2840-2921` | `RuntimeError` → lane fails |
| Non-evidence dossier degraded | `:2661-2665` | Dossier dropped to `""` (warning only) |
| Checkpoint drift (other run, question, lane or attempt, tampering) | `:2997-3034` | `{}` → clean restart (no `--resume`) |
| Promotion error at any phase | `:3578-3601` | Rollback restores the moved old files/charts/contract; re-raise [verifier: not for every phase. A staging-phase `Exception` deletes the previous manifest without restoring it (`:3580-3581`). A failed restore deletes `rollback/` (`:3598-3600`). A `BaseException` skips the restore entirely, and the outer `finally` deletes `rollback/` (`backend/app/services/pipeline_orchestrator.py:3578`, `:3602-3604`)] |
| Contract mutated before or during finalization | `:3633-3636`, `:3720-3723` | `RuntimeError` |
| Global-synthesis attempt failure | caller `:11531-11545` | Forensic logs/sidecars kept by `_preserve_research_attempt_progress`; staging dir removed; retried up to 2/2 |
| Extract-only salvage timeout or failure | `:3797-3802` | Returns False; the research continues with whatever structured files exist |

---

## Surprises

1. **Docs drift: watchdog budgets.** `ARCHITECTURE_MAP.md:157` says "Quick: 900s / Standard: 2400s / Deep: 10800s". `DRF_ARCHITECTURE.md:388` says "quick 900s / standard 2400s / deep 10800s". The code tiers are 900/7200/21600 × 1.5 = 1350/10800/32400 s by default (`backend/app/config.py:1553`, `:1559-1578`). `README.md:1801` ("quick ≈ 23 min, standard 3 h, deep 9 h") matches the code.
2. **Docs drift: stale line anchors.** `ARCHITECTURE_MAP.md:820` places the salvage at `pipeline_orchestrator.py:1290-1324`, and `DRF_ARCHITECTURE.md:385-391` cites `:1136`, `:1153-1164`, `:1170-1177`, `:1183-1191` for Popen, budget, watchdog and cancel. Those now live at `:2428`, `:2277-2283`, `:2451-2458` and `:2462-2472`.
3. **Code-comment drift.** `:2321` says the Config recursion-limit default is 220. Config's default is 400 (`backend/app/config.py:1556`).
4. **Stale comment / production-dead helper.** The ITEM-3 block comment at `:2943-2946` says retries add `--resume` whenever a non-empty `research_checkpoint.json` exists. Production now requires full lineage validation (`:2974`), and `_has_research_checkpoint` (`:2947`) is called only from `backend/tests/test_research_checkpoint.py:324-329`.
5. **Dead code.** `_validated_research_checkpoint_attempt_id` (`:3042`) and `_validate_research_judge_contract` (`:3312`) have no callers in `backend/` (app, scripts or tests).
6. **Suspected: a staging-phase promotion failure deletes the previous valid contract manifest.** The `except` branch runs `os.unlink(contract_path)` whenever it exists (`:3580-3581`), but the old manifest is moved into `rollback/` only at `:3546-3548`. An exception during staging leaves `old_contract_moved=False`, so the prior manifest is deleted and never restored. Staging failures include a copy error, a meta_patch write error, a staged report under 400 characters (`:3537`), and a fingerprint `RuntimeError`. This leaves the root unsealed and contradicts `_finalize_research_contract`'s docstring ("A failure therefore leaves the prior valid contract reusable", `:3623-3625`).
7. **Suspected: data loss if rollback restore fails.** If an `os.replace` during restore raises (`:3588-3597`), the inner `finally` still calls `shutil.rmtree(rollback)` (`:3598-3600`), deleting the old generation's only copy.
8. **Non-atomic window during promotion.** Between moving the old files out (`:3549-3557`) and installing the new ones (`:3559-3567`), `handoff/` briefly holds no `research_report.md`. Concurrent API readers can observe this; only the manifest is written last.
9. **Suspected: prompt-file leak.** `.prompt-*.txt` is created at `:2244` but the try/finally that deletes it starts at `:2491`. If `Popen` raises (for example `uv` missing or a bad interpreter path) or `on_progress(2, …)` at `:2426` raises `PipelineCancelled`/`ProviderOutageHalt` (the stage updater does, `:8962-8969`), the prompt file stays on disk. Salvage has the same issue: `on_progress(96)` at `:3782` is guarded only by `except Exception`, so a BaseException there leaks `.extract-prompt-*.txt`.
10. **Suspected: extract-only salvage is not fully supervised.**
    - It uses `subprocess.run(..., timeout, start_new_session=True)` (`:3786-3790`). On timeout, `subprocess.run` kills only the direct child, not its process group, so grandchildren can survive.
    - The child is not added to `_live_procs`, so backend shutdown's `cleanup_all` will not reach it.
    - It ignores `cancel_event`, so a cancel can wait up to 600 s.
    - Its stdout is discarded, so its `[usage]` tokens are never metered.
11. **Resume overwrites the budget epoch.** With `resume` set and a `resume_attempt_id`, the code sets `RESEARCH_BUDGET_EPOCH=resume_attempt_id` (`:2395`) after `_configure_research_budget_env` (`:2379`), so the caller's new `budget_epoch` is discarded for the child. This is intentional, because the bridge reads `attempt_id` from `RESEARCH_BUDGET_EPOCH` (`deerflow_bridge/deerflow_research.py:922-924`), but the variable name is confusing. The same block also re-adds three `RESEARCH_BUDGET_*` vars when `RESEARCH_BUDGET_ENABLED=false` had removed them (`:2002-2005` vs `:2393-2395`).
12. **Suspected: false-positive dossier degradation.** `_is_degraded_dossier` treats a dossier of **any length** that contains `"Error code: 4"`/`"Error code: 5"`/`"LLM request failed"` as degraded (`:2823`). The report guard limits marker matching to texts under 400 characters (`:2634`). A long, legitimate actor dossier that quotes an HTTP error string would be silently dropped (`:2661-2665`), and in evidence lanes it would fail the lane (`:2860-2865`). [verifier: confirmed, and the problem is broader. `_control_failure_block` also treats any block that contains a marker as a control failure, at any length (`:2776`). An evidence pack without `evidence-block` markers counts as one block (`:2809-2810`). Such a pack that quotes "Error code: 5" is therefore refused at `:2640-2644`, and it can never count as fresh for timeout salvage (`backend/app/services/pipeline_orchestrator.py:2236-2239`)]
13. **Hard-coded 400 thresholds coexist with `RESEARCH_MIN_REPORT_CHARS`.** `_fresh_expected_artifact` (`:2235`), `_track_artifacts_survived` (`:3070`), the contract validator (`:3389`), promotion (`:3536`) and finalization (`:3639`) all use a literal 400. Setting the knob therefore does not move these gates.
14. **Judge strictness is evaluated at validation time from env.** `_research_judge_contract_errors` compares `meta.research_report_judge.passed` with `_research_judge_passes(scorecard)`, which reads `RESEARCH_REPORT_JUDGE_STRICT` from `os.environ` at call time (`:3206`, `:3295-3305`). Changing the env after a contract was sealed can flip `expected_pass` and make a previously valid contract fail with `judge_meta_summary_mismatch`, rejecting reuse.
15. **Suspected: `_validate_research_contract` can raise.** `_research_contract_validation_errors` catches only `OSError/ValueError/TypeError` (`:3414`). It calls `_research_contract_entries(root)` (`:3400`), which raises `RuntimeError` when a chart file cannot be hashed (`:3344-3345`), so the "bool" validator can raise instead of returning False. [verifier: confirmed, with a wider trigger. Whenever `charts/` exists, `_research_contract_entries` re-hashes all 16 root contract files as well as the charts, so any unreadable contract file raises. A judge `_judged_prose.chars` that parses to a JSON float infinity raises `OverflowError` at `int(...)`, which neither `:3269` nor `:3414` catches (`backend/app/services/pipeline_orchestrator.py:3329-3345`, `:3268`)]
16. **Integrity validation does not enforce judge PASS.** The binding check accepts a correctly bound FAIL verdict. Promotion and finalization only run integrity validation (`:3571`, `:3633`). The PASS requirement is applied only at reuse time by `_research_contract_quality_errors` (`:11930`).
17. **`refresh_research_artifact_manifest` returns spec names** (`report`, `dossier`), not the filenames passed in (`:3463-3471`). Its manifest path comes from `PipelineManager.handoff_dir(pipeline_id)` (`:1110`), while the probe uses the caller's `handoff_dir`. The two could diverge if `resolve_handoff_dir` returns a different directory.
18. **The success path does not check report freshness.** A child that exits 0 without rewriting `research_report.md` would have the stale on-disk report admitted (`:2618-2623`). Freshness is enforced only on the timeout paths.
19. **Explicit `timeout` is unused in production.** No caller passes it; the branch at `:2278-2279` is reachable only from tests. `depth` passed to argv is not lowercased (`:2256`) even though budgeting lowercases it (`:2277`). A caller-supplied "Deep" would budget correctly but fail the bridge's argparse `choices` (`deerflow_bridge/deerflow_research.py:16577`). [verifier: this is latent. The HTTP entry points lowercase `depth` before it reaches `state.options` (`backend/app/api/research.py:71`, `backend/app/api/sdk.py:102`), and `Config.DEERFLOW_RESEARCH_DEPTH` is lowercased at load (`backend/app/config.py:1159`)]
20. **The `_spend["t_start"]` reset is redundant.** It is set in `run` (`:2126`) and overwritten at the start of the read loop (`:2490`), so the failed-attempt `latency_ms` excludes the sync and spawn overhead, as the comment intends. [verifier: neither assignment is redundant. The `run()` value is the only one in effect for failures before the read loop: a bridge-sync error at `:2211`, a `Popen` error, or `on_progress(2)` raising at `:2426`. The reset then narrows the window for later failures, but it only matters when tokens > 0 (`backend/app/services/pipeline_orchestrator.py:2126`, `:2489-2490`, `:2059-2060`)]
21. **Low-confidence: stdout decoding uses the locale codec.** `Popen(..., text=True)` has no explicit `encoding` (`:2428-2435`), and the bridge prints Chinese progress lines. Under a non-UTF-8 locale this could raise `UnicodeDecodeError` in the read loop. Modern Python's C-locale coercion usually avoids it.

---

## Verification

An adversarial verifier re-read the code on 2026-10-11 (branch `main`, on-disk checkout). Every key claim and surprise was checked against `backend/app/services/pipeline_orchestrator.py`, and 20 more Walkthrough and Control-flow statements were spot-checked. Bare `:NNNN` anchors mean `backend/app/services/pipeline_orchestrator.py`.

**Verdict counts (50 checked):** 40 confirmed, 10 imprecise, 0 refuted, 0 unverifiable.

- Key claims (15): 13 confirmed, 2 imprecise.
- Surprises (15): 15 confirmed. Three of them turn out broader than stated.
- Extra spot checks (20): 12 confirmed, 8 imprecise.

The map is accurate overall. Line anchors were correct to within a line or two everywhere they were checked.

### Non-confirmed statements and corrections

1. **Key claim, W9-4 teardown survival** (imprecise). The claim says the lane survives only if the report is fresh and either `actors.json` exists or the checkpoint has non-empty `completed_passes`. That rule applies only to non-evidence lanes. An evidence lane survives when its `evidence_pack.md` is fresh, with no `_track_artifacts_survived` check (`:2547-2552`). The Walkthrough (step 10) already states this correctly.
2. **Key claim, `_promote_research_contract` "restores the old generation on any exception"** (imprecise). Three gaps:
   - Only `Exception` is caught (`:3578`). A `BaseException` skips the restore, and the outer `finally` deletes `rollback/` (`:3602-3604`).
   - A staging-phase failure unlinks the previous manifest and never restores it (`:3580-3581` vs `:3546-3548`).
   - A restore failure deletes `rollback/` (`:3598-3600`).
   The same correction applies to Invariant 11 and to the "Promotion error at any phase" row of the failure table (both annotated inline).
3. **Walkthrough, `run` wrapper "the caller meters success"** and **Invariant 14, "Spend is metered exactly once"** (imprecise).
   - Failed or cancelled attempts are metered at most once, and only when tokens > 0 and `LLM_TELEMETRY_ENABLED` is on (`:2059-2062`).
   - Successful attempts are metered only at `:12205`, after the whole Stage 0 succeeds. Successful lanes or attempts in a stage that later raises (for example `:11565-11568`, a promotion error, or a finalization error) are metered zero times.
   - Extract-only salvage tokens are never metered.
4. **Walkthrough, "`_configure_research_budget_env` pops every `RESEARCH_BUDGET_*` key"** (imprecise). It pops the 12 names in `_RESEARCH_BUDGET_ENV_KEYS`, which include `RESEARCH_NEGATIVE_CACHE_TTL_SECONDS` and `RESEARCH_NEGATIVE_CACHE_RETRIES` (`:1748-1761`).
5. **Walkthrough, `_load_fresh_evidence_lane_actor_dossier` "Every failure raises `RuntimeError`"** (imprecise). `int(coverage.get("tier_1_2_actor_count") or 0)` is unguarded, so it can raise `ValueError` or `TypeError` (`:2887`). The lane still fails.
6. **Control flow, "reuse check: contract exists → validate"** (imprecise). The contract branch requires `_report_candidate` first: the root report must be at least 400 stripped characters, a hard-coded threshold (`:11906-11909`). With no candidate report, Stage 0 goes to synthesis recovery when `evidence_synthesis_manifest.json` exists (`:11955-11959`).
7. **Surprise 19, the depth half** (imprecise: the risk is overstated). The runner really does pass `depth` to argv without lowercasing it (`:2256`). In practice the HTTP entry points lowercase depth first (`backend/app/api/research.py:71`, `backend/app/api/sdk.py:102`), and Config lowercases its default (`backend/app/config.py:1159`), so a "Deep" value is latent.
8. **Surprise 20, "the `_spend["t_start"]` reset is redundant"** (imprecise). Neither assignment is redundant. The `run()` value (`:2126`) is the only one in effect for failures before the read loop (`:2211`, `Popen`, `on_progress(2)` at `:2426`). The reset at `:2489-2490` narrows the window afterwards.

### Confirmed surprises with broader scope than stated

- **Surprise 12 (false-positive degradation)** also covers evidence packs and dossiers that go through `_control_failure_block`. A marker anywhere in a block counts as a control failure (`:2776`). A pack without `evidence-block` markers is a single block (`:2809-2810`), so a pack that quotes "Error code: 5" is refused at `:2640-2644` and can never count as fresh for salvage (`:2236-2239`).
- **Surprise 15 (validator can raise)** has a wider trigger. When `charts/` exists, `_research_contract_entries` re-hashes all 16 root files, so any unreadable contract file raises `RuntimeError` (`:3329-3345`). Separately, a JSON float infinity in `_judged_prose.chars` raises `OverflowError`, which neither handler catches (`:3268`, `:3414`).
- **Surprise 17 (`refresh_research_artifact_manifest` path split)** is reachable in practice. The only caller passes `PipelineManager.resolve_handoff_dir(pipeline_id)` (`backend/app/api/research.py:717`), which for a fork is the base run's handoff (`:888-912`). The manifest is still loaded from the fork's static `handoff/manifest.json` (`:1110`, `:1113-1127`). The caller also ignores the return value (`backend/app/api/research.py:767`).

### Omissions (significant behavior the map does not state)

1. **Extract-only salvage never runs on the W9-4 teardown path.** A non-evidence lane can survive teardown salvage on the strength of a checkpoint's `completed_passes` alone, with no `actors.json` (`:3072-3075`). The ITEM-14 salvage then never runs, because it is wired only into the watchdog branch (`:2583-2612` vs `:2534-2565`). Such a lane proceeds with `actors`/`sources`/`timeline` set to None.
2. **The ×1.5 budget multiplier follows global Config flags, not the per-call arguments.** `Config.deerflow_depth_budget` checks the class attributes `DEERFLOW_DUAL_TRACK`/`DEERFLOW_SUBAGENTS`/`RESEARCH_DEEP_FANOUT` (`backend/app/config.py:1572-1575`). Global synthesis (`:11491-11510`) and synthesis-only recovery (`:10937-10956`) pass `subagents=False, dual_track=False` and still get the ×1.5 budget. A non-blank env `DEERFLOW_RESEARCH_TIMEOUT` bypasses both depth scaling and the multiplier (`:2280-2281`).
3. **The success path meters nothing when Stage 0 later fails.** See correction 3: the single success meter is at `:12205`.
4. **A `BaseException` during promotion destroys the prior generation.** `_promote_research_contract` catches only `Exception` (`:3578`), and its outer `finally` unconditionally deletes `rollback/` (`:3602-3604`).
5. **More docs drift than Surprise 2 lists.**
   - `ARCHITECTURE_MAP.md:485` and `ARCHITECTURE_MAP.md:816` still say `--resume` is passed whenever `research_checkpoint.json` exists. Resume is now gated by `_validated_research_checkpoint_lineage` (`:2974-3039`, callers `:11182`, `:11996`).
   - `ARCHITECTURE_MAP.md:822` and `DRF_ARCHITECTURE.md:250`/`DRF_ARCHITECTURE.md:255` cite the stale anchors `:1290-1324` and `:1243-1272`. The code is now at `:2583-2612` and `:2534-2565`.
