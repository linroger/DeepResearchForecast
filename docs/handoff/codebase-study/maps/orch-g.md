# orch-g — Orchestrator part G: parallel research tracks and embedder warm-up

Slice: `backend/app/services/pipeline_orchestrator.py` lines 11060-11882 (branch `main`, on-disk checkout, read 2026-10-11).
It holds two `PipelineOrchestrator` methods: `_run_parallel_research_tracks` (11060-11828) and `_maybe_warm_embedder` (11832-11878). Lines 11879-11882 are the section banner and the decorator of `_run` (another slice).
All anchors are `path:line` relative to the repo root. Lines with no path are in `backend/app/services/pipeline_orchestrator.py`.

## Purpose & position in the pipeline

- `_run_parallel_research_tracks` is Stage 0 (RESEARCH) when there is more than one outer research lane. `_run` calls it only when `research_outer_track_count(...) > 1` (11983-11991). That function returns 1 for engine v3 and returns `RESEARCH_PARALLEL_TRACKS` only for the legacy engine (5955-5981). So **with the default `RESEARCH_ENGINE=v3` (backend/app/config.py:1187) this slice is dormant.** It runs only when:
  - the engine resolves to legacy (`legacy|deerflow|agentic`, 5895-5901), or
  - the run's pinned `actor_intelligence_policy_v1.required is True` forces legacy (5937-5952).
- It launches K angle-specialized DeerFlow research subprocesses (one `DeerFlowResearchRunner.run` each) in a thread pool. Each lane writes `handoff/track_<k>/`. The method then does one of two things:
  - **Default ("LOOP-010") architecture** (`RESEARCH_GLOBAL_SYNTHESIS=true`, n>1): the lanes are `--evidence-only`. The method seals their evidence packs plus the single baseline actor dossier into `handoff/evidence_synthesis_manifest.json` (version 3). It runs **one** global-synthesis subprocess (up to 2 attempts) in a private temp dir, then promotes that generation into `handoff/` with a checksum contract (11279-11634).
  - **Legacy concatenation architecture** (`RESEARCH_GLOBAL_SYNTHESIS=false`): each lane writes a full report. The orchestrator merges reports, sources, actors, timeline, markets and meta into `handoff/` itself, optionally with one LLM reconcile call (11636-11828).
- Either way it returns the same dict shape as `DeerFlowResearchRunner.run`: `report, report_path, actor_dossier, actors, sources, timeline, exit_code, research_telemetry` (11623-11634, 11819-11828, compare 2685-2695). Downstream stages consume it unchanged.
- `_maybe_warm_embedder` runs once per research-stage completion, including the reuse path (12208, after the reuse/run branches converge). It is default-OFF. When enabled it starts a daemon thread that loads a SentenceTransformer and pre-encodes actor names and aliases into the shared embedding disk cache, ahead of the graph stage (11832-11878).

## Walkthrough (source order)

### `_run_parallel_research_tracks(self, state, handoff_dir, upd, n_tracks) -> dict` (11060-11828)

**Inputs**
- `state: PipelineState`. Fields read: `prompt`, `options[depth|research_language|research_model]`, `pipeline_id`, `graph_id`, `task_id` (through the budget helper), `research_pid`.
- `handoff_dir`: the pipeline handoff root.
- `upd(pct, msg)`: the stage updater from `_make_stage_updater` (8949-9006). It raises `PipelineCancelled` when the cancel event is set (8961-8963) and `ProviderOutageHalt` when the run-level breaker has tripped (8967-8969). It also saves state and updates the task (8994-9005).
- `n_tracks`: the outer lane count from the caller.

**Docstring (11064-11072).** It claims "wall-clock ≈ 1 track", "any lane may fail as long as ≥1 survives", and "all fail → RuntimeError". These claims hold only for the legacy concatenation path; see Surprises S1 and S2. [verifier: only the "≥1 survivor" claim is path-specific; "wall-clock ≈ 1 track" fails in both paths whenever outer_workers < n (5842, 11243-11244), and the global path adds a serial synthesis (11473-11520)]

#### 1. Setup and envelope sizing (11073-11122)
- 11073-11074: imports `ThreadPoolExecutor` and `as_completed` locally, plus `write_json_atomic` and `write_text_atomic` (backend/app/utils/atomic.py:20, 53; temp file + `os.replace`, fsync by default).
- 11077-11078: `angles = _RESEARCH_TRACK_ANGLES[:max(1, n_tracks)]` and `n = len(angles)`. `_RESEARCH_TRACK_ANGLES` (5812-5818) holds exactly 3 `(short_key, H1 title, prompt_prefix)` tuples, so **n is silently clamped to ≤3**:
  1. `("base-evidence", "基线证据扫描 (Base Evidence Sweep)", "")`: empty prefix, so the lane prompt is the raw brief.
  2. `("base-rates", …, _TRACK2_PREFIX)` (5796-5802): Chinese-language instruction for reference-class forecasting, base rates and historical analogs.
  3. `("incentives-contrarian", …, _TRACK3_PREFIX)` (5803-5809): actor incentives, contrarian case and market pricing.
- 11080: `research_engine = research_engine_for_run(state.options)` (5937-5952). This value is passed to full-research lanes only; evidence lanes and synthesis are forced to legacy inside the runner (2295-2301). [verifier: it is passed to every lane (11232) and only overridden by the runner for evidence lanes; the synthesis call omits it (11491-11512). Because this method runs only when the engine is not v3 (11983-11991, 5972-5973), the value is in practice always "legacy" here]
- 11081-11082: `global_synthesis = n > 1 and Config.RESEARCH_GLOBAL_SYNTHESIS` (default true, backend/app/config.py:1200-1201).
- 11083-11084: `global_subagent_cap = Config.RESEARCH_GLOBAL_SUBAGENT_CAP` (default 9, config.py:1205-1206) and `configured_model_cap = Config.RESEARCH_GLOBAL_MODEL_CONCURRENCY` (default 0, config.py:1212-1213).
- 11085-11086: `outer_workers = research_outer_track_workers(n, cap, model_cap)`, which is `max(1, min(n, cap, model_cap if >0 else n))` (5833-5842). This is the thread-pool size: how many lanes run **at once**. The remaining lanes queue.
- 11087-11091: `model_concurrency = research_model_concurrency_cap(outer_workers, cap, configured)`. It returns the configured value if >0, else `outer_workers + global_subagent_cap` (5845-5854).
- 11092-11097: `subagent_cap = research_lane_subagent_cap(outer_workers, cap, RESEARCH_SUBAGENTS_PER_TRACK_MAX (default 5, clamped 1..8, config.py:1207-1208), model_concurrency)` (5857-5873). It computes `model_room = model_concurrency // outer_workers - 1`; if that is ≤0 it returns 0, else `min(model_room, max(1, min(per_track_max≤8, cap // workers)))` (5821-5830).
  - Defaults (n=3, cap=9, model=0) give outer_workers=3, model_concurrency=12 and subagent_cap=min(3, min(5, 9//3)) = **3 per lane**.
- 11098-11099: `harness_subagents = Config.DEERFLOW_SUBAGENTS (default true, config.py:1168) and subagent_cap > 0`.
- 11100: `os.makedirs(handoff_dir, exist_ok=True)`.
- 11101-11103: `_activate_research_budget_epoch(state, handoff_dir)` (1815-1922) returns `(budget_db_path, budget_telemetry_path, budget_epoch)`:
  - The epoch is keyed by `state.task_id`, or `initial-<pipeline_id>` if there is none (1831-1833).
  - Re-entry under the same task reuses the epoch row (1840-1849).
  - Otherwise it creates `handoff/research_budget_epochs/epoch-NNN-<slug>/research_budget.sqlite3` and resets `handoff/research_budget.json` (1858-1923). [verifier: the parent only creates the epoch directory and computes the `.sqlite3` path (1860-1862, 1881); the DB file is created by the child ledger. It also archives the previous snapshot into the prior epoch dir, raising RuntimeError if the copy fails (1864-1879)]
  - It raises `RuntimeError` once `len(history) >= RESEARCH_BUDGET_MAX_EPOCHS` (default 3, 1851-1856; config.py:543-544).
  - It appends to `state.options["research_budget_epochs"]`, sets `state.options["research_budget_epoch"]`, and saves state (1891-1922).
  - **All lanes and both synthesis attempts share this one SQLite ledger** (docstring 1819-1824; lanes pass `budget_db_path` at 11206, synthesis at 11501). [verifier: only while `RESEARCH_BUDGET_ENABLED` is true (default, config.py:528-529). When it is false, `_configure_research_budget_env` strips every budget env key from the child (2002-2005), so no ledger is shared, although the parent still allocates epochs]
- 11104-11111: pre-launch guard. `_research_budget_exhaustion(telemetry_path, epoch)` (1764-1803) reads the `research_budget.json` snapshot. It ignores a snapshot from another epoch. It returns the first saturated global cap among `attempts_global` (default 1800), `search_global` (900) and `fetch_global` (450) (1907-1918; config.py:530-537). A hit raises `RuntimeError("research_budget_exhausted before track launch (epoch=…, budget=…); explicit pipeline resume is required…")`. [verifier: the counters it compares are `global.attempts`, `global.search_network` and `global.fetch_network` against the snapshot's own `limits` (1783-1797). A newly created epoch rewrites the snapshot with `global: {}` (1899-1921), so the guard can only trip when the same task id re-enters an epoch that is already in use (1840-1849)]
- 11116: `_sync_deerflow_bridge_if_stale(Config.DEERFLOW_DIR)` (1441ff) runs once before any lane. It copies changed `deerflow_bridge/` files into `deer-flow/`. A required skill-sync or safety-overlay failure re-raises (1736-1738) and aborts the stage before spend. Every runner call repeats the sync under the same lock (2211); comment 11112-11115.
- 11117-11122: `upd(2, "并行研究：排队 {n} 条…（同时 {outer_workers} 条；每轨最多 {subagent_cap or 0} 个 harness 子代理；全局模型流 {model_concurrency}）…")`.

#### 2. Progress aggregation state (11124-11135)
- `prog_lock` and `publish_lock` (threading.Lock). `track_local = [2]*n` holds each lane's local percent. `failed_tracks: set[int]`. `last_published = 2`. `last_publish_at = 0.0`. `pids_lock`.
- The comment at 11124-11128 explains why: each lane is capped at 95 so the merge can own 95→100, aggregation is monotonic, and publishing is serialized and throttled.

#### 3. `_make_cb(idx)` → `_cb(local, msg)` (11137-11160): per-lane progress callback
- 11140-11142: if `cls._cancel_events[pipeline_id]` is set, it raises `PipelineCancelled("并行研究期间被取消")`. This runs on the lane thread inside the runner's stdout loop, so the runner's `finally` kills that lane's process group (2566-2575).
- 11143-11144: `track_local[idx] = max(old, min(95, int(local)))`, so each lane is monotonic and capped at 95. The runner's final `on_progress(100, …)` (2681-2684) is clamped to 95.
- 11145-11152: under `publish_lock`, then `prog_lock`: `agg = aggregate_parallel_progress(track_local, previous=last_published, ceiling=95, excluded_indices=failed_tracks)`. That function returns the integer arithmetic mean of non-excluded lanes, clamped to the ceiling and floored at `previous` (backend/app/services/research_progress.py:371-392).
- 11153-11156: **throttle**. It returns without publishing if `agg <= last_published` **and** less than 15.0 s have passed since the last publish. So it publishes on every increase, or as a ≥15 s keep-alive.
- 11157-11159: updates `last_published` and `last_publish_at`, then calls `upd(agg, f"[轨{idx+1}] {_tail(detail)}")`. `_tail` strips a `"] "`-delimited prefix and caps at 160 chars (2739-2744). `upd` can raise `PipelineCancelled` or `ProviderOutageHalt`, which propagates into that lane's runner.

#### 4. `_make_spawn(idx)` → `_spawn(pid)` (11162-11173): PID persistence
- Under `pids_lock`: appends `int(pid)` to `state.options["research_track_pids"]` without duplicates. Sets `state.research_pid` to the first PID only if it is `None` (back-compat field).
- Then calls `PipelineManager.save(state)` outside `pids_lock` (11172). `save` takes the per-pipeline state lock (945-956).
- Consumers: boot-time orphan reconcile (7703-7704, 7724-7725) and pipeline delete (8077-8078) kill every PID in `research_track_pids`. [verifier: delete kills them only when the persisted status is `"running"` (8071-8078). The kill is a SIGTERM to the process group (7864)] `_kill_orphan_research` first checks that the cmdline contains `deerflow_research.py` and the pipeline id (7843-7865).
- The caller clears `research_pid` and pops `research_track_pids` after the stage returns successfully (12076-12078).

#### 5. `_run_track(idx, angle_title, prefix) -> (idx, angle_title, track_dir, res)` (11175-11239): one lane, run on a pool thread
- 11176-11177: `track_dir = handoff/track_{idx+1}` (1-based), created.
- 11178: `track_prompt = prefix + state.prompt` if there is a prefix, else `state.prompt`.
- 11179: `track_lane_id = "outer-track-{idx+1}"`. This is both the budget lane id and the checkpoint lane id.
- 11182-11194: **per-lane resume (ITEM-3).** `_validated_research_checkpoint_lineage(track_dir, prompt=track_prompt, depth=str(options.depth or Config.DEERFLOW_RESEARCH_DEPTH), run_id=pipeline_id, lane_id=track_lane_id, expected_attempt_ids=_research_budget_attempt_ids(state))` (2974-3039) reads `track_dir/research_checkpoint.json`.
  - It accepts only a `version == 2` checkpoint whose question hash, depth, run, lane and attempt (one of `state.options.research_budget_epochs[*].epoch`, 1806-1812) all match, with a well-formed pass list and an intact `checkpoint_id` (sha256 projection, 2956-2971).
  - On success it returns `{attempt_id, checkpoint_id, thread_id}`, and `_resume_track = bool(attempt_id)`. Otherwise the lane starts clean.
- 11195-11233: `DeerFlowResearchRunner.run(track_prompt, track_dir, …)` with:
  - `on_progress=_make_cb(idx)` and `on_spawn=_make_spawn(idx)`.
  - `depth`, `language` and `model` from `state.options` (`depth`, `research_language`, `research_model`).
  - `cancel_event=cls._cancel_events.get(pipeline_id)`.
  - `resume=_resume_track`, `resume_attempt_id`, `resume_checkpoint_id`.
  - `kg_graph_id=state.graph_id`: KG MCP is wired only when a graph already exists (fork, continue, resume-with-graph). On a first run it is `None`, so this is a no-op (2414-2423).
  - `budget_db_path`, `budget_lane_id=track_lane_id`, `budget_telemetry_path`, `budget_run_id=pipeline_id`, `budget_epoch`.
  - `subagents=harness_subagents`, `max_concurrent_subagents=max(1, subagent_cap)`, `model_concurrency_global=model_concurrency`.
  - `dual_track=research_dual_track_for_outer_lane(idx, Config.DEERFLOW_DUAL_TRACK)`. This is True **only for idx 0**, so only the baseline lane produces the Track-B actor dossier (5876-5882; comment 11218-11223).
  - `shared_actor_track=False` (11230).
  - `evidence_only=global_synthesis` (11231).
  - `research_engine=research_engine` (11232).
- No explicit `timeout`, so each lane gets the runner's own watchdog: `.env` `DEERFLOW_RESEARCH_TIMEOUT` if set, else `Config.deerflow_depth_budget(depth)`, which is ×1.5 when dual-track, subagents or fan-out is on (2277-2283; config.py:1559-1578). The watchdog starts when that lane's subprocess starts (2446-2458), so queued lanes are not penalized.
- 11234-11238: defense-in-depth. A non-zero `res["exit_code"]` raises `RuntimeError("research lane {k} returned non-zero exit …")`. The runner already raises on non-zero exit unless it salvaged a timeout (2618-2619).

#### 6. Launch, monitor, fail and cancel (11241-11268)
- 11243-11245: `ThreadPoolExecutor(max_workers=outer_workers, thread_name_prefix="research-track")` submits all n lanes. Lanes beyond `outer_workers` wait for a free worker.
- 11246-11264: `as_completed` loop:
  - On success: `results[idx] = (angle_title, track_dir, res)`.
  - On `PipelineCancelled`: stores it in `cancelled` and keeps draining. The other lanes die quickly because the runner's cancel watcher polls the event every 1 s and kills the group (2461-2472).
  - On any other `Exception`: logs a warning, calls `_note_provider_stage_failure(pipeline_id, te)` (580-592; a best-effort +1 on the run-level outage breaker) [verifier: +1 only when a breaker is registered for the run and `_classify_provider_outage` classifies the error as provider-level; any other lane error is not counted (490-495, 586-590)], adds the lane to `failed_tracks` under `prog_lock`, and calls `_make_cb(i)(95, "研究轨失败…")` inside a `try/except Exception: pass` to republish an aggregate that excludes the failed lane.
  - **No per-lane retry happens at this layer.** A failed lane is skipped. Retries live inside the bridge subprocess, and on a later pipeline attempt through per-lane checkpoints.
- 11265-11266: after all futures finish, re-raises the stored `PipelineCancelled`.
- 11267-11268: `results` empty → `RuntimeError("所有并行研究轨均失败，研究阶段失败")`.

#### 7. Common merge prelude (11270-11277)
- `survived = len(results)` and `degraded = survived < n` (11270-11271). Then `upd(96, "合并 {survived}/{n} 条研究轨…")` (11272).
- `ordered = [results[i] for i in sorted(results)]`: lane order is deterministic (11275).
- `track_sources = [res["sources"] …]` (11276). `merged_sources = merge_sources_union(track_sources)` (11277) uses 6281-6310:
  - Union by normalized URL (strip, drop trailing `/`, lowercase; 5993-5997).
  - On a duplicate, keeps the first-seen row, upgrades `tier` to the best (S1 > … > S4 > unknown; 5984-5990), and backfills empty fields.
  - Rows without a URL are kept as-is. First-seen order is preserved.

#### 8a. Global-synthesis branch (`if global_synthesis:`, 11279-11634)
- **Baseline ownership gate (11285-11306).**
  - `0 not in results` → `RuntimeError("broad baseline evidence lane failed; required shared actor intelligence is unavailable")`.
  - Empty `results[0]["actor_dossier"]` → `RuntimeError("…returned no fresh shared actor dossier")`. In evidence-only mode the runner fills that field from `_load_fresh_evidence_lane_actor_dossier`. That loader raises if `meta.json` lacks current-attempt provenance (`status=completed`, `workflow_mode=evidence_only`, `question==prompt`, `actor_dossier_generated`/`required` true) or if the dossier is degraded (2650-2657, 2826-2866).
  - Any non-baseline lane that returned a non-empty `actor_dossier` → `RuntimeError("non-baseline evidence lanes produced actor dossiers: …")`.
- **Lane rows (11308-11353).** `manifest_path = handoff/evidence_synthesis_manifest.json`. For each surviving lane in order:
  - Requires `track_k/evidence_pack.md` and `track_k/sources.json` to exist with size > 0, else `RuntimeError("surviving research lane has empty/missing …")`.
  - Reads both as bytes. `sources.json` must parse as UTF-8 JSON, else `RuntimeError("…invalid source ledger")`.
  - Requires **≥1 verified row**: a dict whose `url` starts with `http://` or `https://` and whose `reachable` is not `False`. Otherwise `RuntimeError("…no verified fetched sources")`.
  - Appends `{title, path (relative to handoff), bytes, sha256, sources_path, sources_bytes, sources_sha256}`.
- **`_sealed_actor_artifact(path, label) -> (bytes, relpath)` (11355-11369).** Rejects a missing path, a non-file, a **symlink**, or an empty file with `RuntimeError("baseline actor dossier has missing/empty {label}: …")`.
- **Actor descriptor (11371-11405).**
  - Seals `track_1/actor_dossier.md`, `track_1/actor_dossier_coverage.json` and `track_1/sources.json`.
  - `dossier_bytes.decode().strip()` must equal the runner's `shared_dossier`, else `RuntimeError("baseline runner dossier differs from sealed actor_dossier.md")` (11385-11388).
  - Builds the descriptor `{lane_index: 1, lane_title, path, bytes, sha256, coverage_path, coverage_bytes, coverage_sha256, sources_path, sources_bytes, sources_sha256}`.
- **Judge binding (11406-11424).** If `track_1/meta.json["actor_dossier_judge_sha256"]` is non-empty, `track_1/actor_dossier_judge.json` must exist and hash to that value, else `RuntimeError("baseline actor judge does not match current-attempt metadata")`. The descriptor then also gets `judge_path`, `judge_bytes` and `judge_sha256`.
- **Manifest v3 (11425-11440).** `{version: 3, pipeline_id, lanes, sources: merged_sources, sources_count, sources_sha256, actor_dossier}`.
  - `sources_sha256` is the sha256 of `json.dumps(merged_sources, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`.
  - Written with `write_json_atomic` (indent 2).
  - The bridge accepts manifest versions 1, 2 and 3 (deerflow_bridge/deerflow_research.py:7337-7345) and loads the dossier through `load_manifest_actor_dossier` (deerflow_bridge/deerflow_research.py:17000-17004).
- **Market candidates carry-over (11441-11461).** Concatenates every lane's `track_k/prediction_market_candidates.jsonl`. Lines are stripped, de-duplicated by exact text and kept in first-seen order. Unreadable files are skipped (`OSError` → continue). Each synthesis attempt dir gets a copy (11477-11484). Rationale comment at 11441-11446: a lost market previously caused about 17 minutes of repeated catalog calls.
- **`_global_progress(percent, message)` (11462-11464)** maps synthesis progress to `min(99, 96 + max(0, p)*3//100)`, i.e. 96-99, and calls `upd(…, "[全局综合] …")` directly. It does not throttle and does not carry a monotonic guard across attempts.
- **Synthesis attempt loop (11466-11548).** `for attempt in range(1, 3)`, so **at most 2 attempts**. Comment 11470-11472: a synthesis outage must never trigger another full evidence run. Each attempt:
  - Creates `synthesis_dir = tempfile.mkdtemp(prefix=".global-synthesis-{attempt}-", dir=handoff_dir)` (11475-11476).
  - Copies in the market JSONL (11477-11484) and calls `upd(96, "全局综合 {survived} 条证据轨（…尝试 {attempt}/2）…")` (11485-11489).
  - Calls `DeerFlowResearchRunner.run(state.prompt, synthesis_dir, on_progress=_global_progress, …)` with the raw brief and no angle prefix (11491-11512):
    - `depth`, `language`, `model` and `cancel_event` as for the lanes.
    - `on_spawn=_make_spawn(0)`, so the synthesis PID is also appended to `research_track_pids`.
    - `kg_graph_id=state.graph_id`.
    - Budget args with `budget_lane_id="global-synthesis"`.
    - `subagents=False`, `max_concurrent_subagents=1`, `model_concurrency_global=model_concurrency`, `dual_track=False`, `shared_actor_track=False`, `synthesis_manifest_path=manifest_path`.
    - **No `resume` and no `research_engine`.** The runner forces legacy because `synthesis_manifest_path` is set (2295-2301) and adds `--synthesis-manifest <path>` (2268-2269).
  - A non-zero `exit_code` → `RuntimeError` (11513-11517). On success: `final_res`, `synthesis_source_dir = synthesis_dir`, `break`.
  - `PipelineCancelled` (11521-11530): `_preserve_research_attempt_progress(…, outcome="cancelled")`, `rmtree(synthesis_dir)`, re-raise.
  - Any `Exception` (11531-11548): `_preserve_research_attempt_progress(…, outcome="failed", detail="Type: msg")` (3078-3137). That copies `synthesis_dir/research_progress.log` to `handoff/research_attempts/global_synthesis_{attempt}_{outcome}_{uuid12}.log`, appends a status line, and copies the sidecars [verifier: all of this is skipped, sidecars included, when the staging dir has no regular `research_progress.log` (3094-3096), for example a child that died before writing its log; an `OSError` during the copy only logs a warning (3133-3137)] `research_report.md`, `research_report_judge.json`, the refinement and failure candidates and their judges, and `meta.json` as `<stem>.<name>`. The handler then records the error string, `rmtree`s the dir, logs a warning and calls `_note_provider_stage_failure`.
- **Double failure (11550-11568).**
  - `failure_meta = {requested: n, survived, architecture: "parallel_evidence_single_global_synthesis", evidence_manifest, evidence_lanes_consumed: survived, global_synthesis_failed: True, global_synthesis_attempts, errors, degraded: True}`.
  - Written to both `state.options["parallel_research"]` and `state.options["global_synthesis_failure"]`, then the state is saved.
  - Raises `RuntimeError("全局证据综合连续两次失败；已保留全部 evidence packs，拒绝回退到全量研究重跑或发布未综合证据")`.
  - The lane dirs and the manifest stay on disk. On the next pipeline attempt the caller sees the manifest without a root report and routes to `_run_research_synthesis_recovery` (11955-11959, 11970-11976; method at 10841) instead of re-running lanes.
- **Success (11570-11590).**
  - `parallel_meta = {requested, survived, angles: [short_key of surviving lanes], architecture, evidence_manifest, evidence_lanes_consumed, global_synthesis_failed: False, global_synthesis_attempts, degraded}`.
  - `_promote_research_contract(synthesis_dir, handoff_dir, meta_patch={"parallel_research": parallel_meta})` (3492-3600). It stages the whitelisted contract files (`_RESEARCH_CONTRACT_FILES`, 3141-3149) plus `charts/`. It patches `meta.json`, requires a staged report of ≥400 chars, and moves the old root files into a rollback dir. It then installs the new files, writes `research_contract_manifest.json` **last**, and validates. Any exception rolls back.
  - Afterwards: `rmtree(synthesis_dir)`, `state.options["parallel_research"] = parallel_meta`, pop `global_synthesis_failure` and `global_synthesis_fallback`, save.
- **Telemetry (11592-11621).**
  - Sums `tokens_in`, `tokens_out`, `tokens_total` (falls back to in+out), `tokens_cached`, `tool_calls` and `results` over every lane plus the **successful** synthesis attempt. [verifier: over every *surviving* lane only. `lane_tels` iterates `ordered`, which holds only successful lanes (11275, 11592-11595). Failed lanes' spend reaches the meter only through the runner wrapper's exception flush (2134-2140)]
  - `wall_s = round(max(lane wall_s) + synthesis wall_s, 1)`.
  - `model = synthesis model or Config.DEERFLOW_MODEL`, `depth = synthesis depth`, `parallel_tracks = survived`, `global_synthesis_runs = synthesis_attempts`.
  - Failed-attempt tokens are not in this dict. The runner's exception wrapper flushes them separately to the meter (2130-2140).
- **Return (11622-11634).** Reads the promoted root files: `research_report.md`, `actor_dossier.md`, `actors.json`, `sources.json` (falls back to `merged_sources` if unreadable) and `timeline.json`. `exit_code: 0`.

#### 8b. Legacy concatenation branch (11636-11828; reached only when `RESEARCH_GLOBAL_SYNTHESIS=false`)
- **Citation remap (11636-11643).** For each lane, `normalize_track_report_citations(res["report"], lane_sources, merged_sources)` (6318-6385):
  - Recovers each local `[S#]` URL from the lane's References section, falling back to the positional lane source.
  - Maps the marker to its 1-based index in `merged_sources` and drops the lane References section.
  - Strips any unresolvable marker and leaves fenced code untouched.
  - Returns `(text, {markers, remapped, stripped})`.
- **Merges (11644-11650).** `labeled_dossiers = [(title, res.actor_dossier)]`. `merged_report = merge_track_reports(labeled_reports)` and `raw_merged_dossier = merge_track_reports(labeled_dossiers)`: `# Track N: <title>` H1 per non-empty body, with N renumbered over the non-empty ones (6000-6014). `merged_actors, _ = merge_actors_objs([...])` (6433-6466) unions the `actors`, `relationships` and `key_events` lists, takes scalar keys from the first lane, then calls `utils.actors.reconcile_cast`; on exception it falls back to the raw union.
- **Dossier compaction (11651-11688).**
  - Enabled by `RESEARCH_COMPACT_MERGED_DOSSIER` (default true, config.py:551-552). The cap is `max(1000, ACTOR_DOSSIER_MAX_CHARS)` (default 80000, config.py:553-554); a bad value means 80000.
  - If `merged_actors` is a dict, calls `actor_dossier_compactor.render_compact_actor_dossier(merged_actors, max_chars=cap, max_actors=ACTOR_CAST_MAX (default 20))` (backend/app/services/actor_dossier_compactor.py:151). On exception it records `fallback_reason`.
  - If the compact output is ≥800 chars after strip, it becomes the merged dossier. Otherwise the fallback is the **single longest** surviving dossier, truncated at the cap on a line boundary.
  - Audit: `{enabled, raw_chars, …compactor meta, compact_chars, reduction_ratio}`. If compaction is disabled, the K-way raw concatenation is kept.
- **Lists, quality and markets (11689-11707).**
  - `merge_list_dedup` (6413-6430; canonical-JSON identity, first-seen) is applied to the lanes' `timeline` (from runner results) and to `track_k/quantitative.json` and `track_k/contested.json`.
  - `track_metas` comes from `track_k/meta.json`. `merge_research_quality` (6469-6492) takes the **minimum-score** lane's `research_quality` block and adds `per_track` and `merged_from_tracks`.
  - `merge_market_snapshots(track_k/prediction_markets.json…, max_total=PREDICTION_MARKETS_MAX (20), max_per_event=PREDICTION_MARKETS_MAX_PER_EVENT (3))` (6549ff) is a relevance-gated union by `market_id`.
  - `merge_market_price_histories(track_k/market_price_history.json…, selected_market_ids)` (6715-6741) keeps only selected markets, one point per timestamp, with `0 ≤ p ≤ 1`.
- **Degraded (11709-11712).** Sets `merged_rq["degraded"] = True` and appends `"parallel-tracks {survived}/{n} survived"` to `merged_rq["degradation"]`.
- **merged_meta (11716-11739).**
  - Starts from a copy of the first non-empty lane `meta.json`.
  - Overrides `research_quality`, `source_tiers` (recomputed with `_source_tier_histogram` from the merged sources, 6495ff), `sources_count`, `actors_count` and `relationships_count`.
  - Adds `parallel_research = {requested, survived, angles, citation_remap: {markers, remapped, stripped} summed}` and `actor_dossier_compaction`.
  - Adds `prediction_markets_count`, `prediction_markets_as_of` and `prediction_market_status`, plus `prediction_market_price_history_count`.
- **Reconcile (11744-11763).** Runs only if `survived >= 2`:
  - If `RESEARCH_TRACK_RECONCILE` (default true, config.py:525): `upd(97, …)`, then `reconcile_track_reports(merged_report, labeled_reports)` (6195-6278). This makes **one LLM call** via `LLMClient().chat(temperature=0.2, max_tokens=4000)` over the lanes' executive summaries, capped at about 30K chars. The output is validated for structure, error markers and the citation audit. On any rejection it returns the deterministic dedup/demoted report, never a raw concatenation. [verifier: one exception: when fewer than 2 lane reports are non-empty, it returns the raw `merged_report` unchanged with reason `"tracks<2"` and makes no LLM call (6208, 6217-6219). The call count is therefore "at most one", not "exactly one"]
  - Otherwise: `_deterministic_track_report(labeled_reports)` (6121ff), with audit `{applied: False, reason: "llm reconciliation disabled", fallback: "deterministic"}`.
  - The audit goes to `state.options["research_track_reconcile"]`. It logs info when not applied.
- **References (11768).** `append_merged_references(merged_report, merged_sources)` (6388-6405) appends one `## References` listing `- [S#] title — url` for every cited in-range marker.
- **Writes (11771-11792), all atomic to the `handoff/` root.**
  - Always: `research_report.md` and `meta.json`.
  - `actor_dossier.md` if non-blank. `actors.json` if a dict. `sources.json`, `timeline.json`, `quantitative.json` and `contested.json` if non-empty. `prediction_markets.json` if a dict. `market_price_history.json` if non-empty.
  - **No `research_contract_manifest.json` is written in this branch.**
- **Telemetry (11795-11811).** Sums as above. `wall_s = max(lane wall_s)` (lanes overlap). `model` and `depth` come from the first surviving lane. `parallel_tracks = survived`.
- **State (11813-11817).** `state.options["parallel_research"] = merged_meta["parallel_research"]` and `state.options["actor_dossier_compaction"] = dossier_audit`. Logs a warning when degraded, then saves.
- **Return (11819-11828).** Returns the in-memory merged values; `actor_dossier` is `""` when blank.

### `_maybe_warm_embedder(self, state, actors) -> None` (11832-11878)
- 11840-11841: returns immediately unless `Config.EMBED_WARM_AT_RESEARCH` (default **false**, backend/app/config.py:476).
- 11842-11848: `rows = utils.actors.extract_actor_rows(actors)`, i.e. the dict rows with a truthy `name` from `actors["actors"]` (backend/app/utils/actors.py:180-187). Any exception gives `[]`. No rows → return.
- 11849-11861: builds `texts` from each row's `name` plus every entry of `aliases` when that is a list. Values are `str().strip()`ed, empties dropped, exact-string de-duplicated and kept in first-seen order. It stops consuming rows once `len(texts) >= 600`; the check runs after a whole row, so the list can slightly exceed 600. No texts → return.
- 11862: `pid = state.pipeline_id`.
- 11864-11873: `_warm()` builds a **new** `graphiti_client.embedder.LocalSentenceTransformerEmbedder()` (model `GRAPHITI_EMBED_MODEL`, default `paraphrase-multilingual-MiniLM-L12-v2`, dim 384; backend/app/services/graphiti_client/embedder.py:43-46). It calls the private `emb._encode(texts[i:i+128])` in batches of 128. `_encode` checks the in-memory LRU, then the disk cache, computes the misses and writes through to the sqlite disk cache keyed by sha256(model ⧺ "\0" ⧺ normalized text) (embedder.py:253-342). Success logs info. Any exception logs **debug** only.
- 11875-11878: `threading.Thread(target=_warm, name=f"embed-warm-{pid[:8]}", daemon=True).start()`. Failure to start is swallowed. The caller never joins the thread.

## Control flow

1. `PipelineOrchestrator._run` (11882ff) → Stage 0. It decides between reuse, synthesis recovery and fresh research (11904-11964):
   - A manifest without a root report, or a contract that fails the quality gate, goes to `_run_research_synthesis_recovery` (11927-11928, 11942-11944, 11955-11959; call at 11970-11976).
   - Otherwise it computes `_research_engine = research_engine_for_run(options)` and `_n_tracks = research_outer_track_count(Config.RESEARCH_PARALLEL_TRACKS (default 3, config.py:1196), engine)` (11983-11988).
   - `_n_tracks > 1` → `self._run_parallel_research_tracks(state, handoff_dir, upd, _n_tracks)` (11989-11991). Else the single-lane path (11992-12075).
2. Inside the method:
   - Sizing → budget epoch → exhaustion guard → bridge sync → `upd(2)` (11077-11122).
   - Thread-pool fan-out of `_run_track` (11243-11245). Each lane runs a `DeerFlowResearchRunner.run` subprocess. Progress flows through `_cb` → `aggregate_parallel_progress` → `upd`, and PIDs through `_spawn` → state.
   - `as_completed` drain → cancel re-raise → all-failed check → `upd(96)` → `merge_sources_union`.
   - Either (a) seal manifest → ≤2 synthesis subprocesses → `_promote_research_contract` → return, or (b) deterministic merge → optional LLM reconcile (`upd(97)`) → atomic writes → return.
3. Back in `_run`:
   - `state.research_pid = None` and pop `research_track_pids` (12076-12078).
   - Research lint (12079ff). Lint is audit-only when no contract manifest exists (12097-12099), which is always the case for branch 8b. [verifier: not always. 8b never writes or removes `research_contract_manifest.json` (11771-11792), so a stale manifest from an earlier generation can still exist (Surprise S12). In that case `_lint_audit_only` is false unless the report is judge-bound (12097-12099)]
   - Cast reconcile (12152-12203), then `_record_research_telemetry` (12205).
   - `_maybe_warm_embedder(state, actors)` (12208), then `_surface_research_quality` (12210).

## Data & artifacts

| Path | Writer (anchor) | Format and key fields |
|---|---|---|
| `handoff/track_<k>/` (k=1..n) | `_run_track` makedirs (11176-11177); contents written by the bridge subprocess | Lane working dir. Evidence mode: `evidence_pack.md`, `sources.json` (list of `{url, title, tier, reachable, excerpt…}`), `meta.json`, `research_checkpoint.json` (v2 identity), `research_progress.log`, `prediction_market_candidates.jsonl` (via `DEERFLOW_RUN_ARTIFACT_DIR`, 2378). Lane 1 also has `actor_dossier.md`, `actor_dossier_coverage.json` and optionally `actor_dossier_judge.json`. Full mode adds `research_report.md`, `actors.json`, `timeline.json`, `quantitative.json`, `contested.json`, `prediction_markets.json` and `market_price_history.json`. |
| `handoff/track_<k>/.prompt-*.txt` | runner (2244-2250) | The lane prompt, mode 0600, deleted in `finally` (2572-2575). [verifier: the `try/finally` starts only at 2491. If the pre-spawn `on_progress(2, …)` at 2426 raises (`_cb` cancel check, or `upd` → `ProviderOutageHalt`), or `Popen` fails, the prompt file (the research question) stays on disk] |
| `handoff/research_budget_epochs/epoch-NNN-<task>/research_budget.sqlite3` and `handoff/research_budget.json` | `_activate_research_budget_epoch` (1858-1923) | Shared per-task tool-budget ledger and snapshot `{schema_version: 1, run_id, epoch, limits{attempts_global, search_global, search_lane, fetch_global, fetch_lane}, global{}, lanes{}}`. |
| `handoff/evidence_synthesis_manifest.json` | 11308-11309, 11440 | v3 manifest (see 8a). Paths are relative to `handoff/`. Persists after success and after failure (it is the recovery seed). |
| `handoff/.global-synthesis-<attempt>-XXXX/` | 11475-11476 | Private staging dir for one synthesis attempt. Removed on success (11586), failure (11542) and cancel (11529). [verifier: it is NOT removed in three cases. (1) `_promote_research_contract` raises: the rmtree at 11586 runs only after promotion succeeds. (2) The pre-`try` `upd(96, …)` at 11485-11489 raises `PipelineCancelled` or `ProviderOutageHalt`. (3) `ProviderOutageHalt` escapes the `try` (Surprise S9). No code elsewhere cleans `.global-synthesis-*` (grep)] |
| `handoff/research_attempts/global_synthesis_<a>_<failed|cancelled>_<uuid12>.log` plus `<stem>.<artifact>` sidecars | `_preserve_research_attempt_progress` (3078-3137) | Forensic copy of the failed synthesis progress log and candidate report, judge and meta. Read by the progress endpoint (research_progress.py:448-466). |
| `handoff/{research_report.md, actor_dossier.md, actor_dossier_coverage.json, actor_dossier_judge.json, actors.json, sources.json, timeline.json, quantitative.json, contested.json, prediction_markets.json, market_price_history.json, research_report_judge.json, research_progress.log, meta.json, charts.json, charts/}` plus `research_contract_manifest.json` | 8a: `_promote_research_contract` (3492-3600) | Promoted generation. `meta.json.parallel_research = parallel_meta`. The checksum manifest is written last. |
| `handoff/{research_report.md, actor_dossier.md, actors.json, sources.json, timeline.json, quantitative.json, contested.json, prediction_markets.json, market_price_history.json, meta.json}` | 8b: 11771-11792 | Merged files written directly. `meta.json` carries `parallel_research` with `citation_remap` and `actor_dossier_compaction`. |
| `EMBED_DISK_CACHE_PATH` (default `<GRAPHITI_DATA_DIR>/embed_cache.sqlite`, config.py:1253-1256) | `_warm` via `_encode` (embedder.py:338-339) | Embedding vectors keyed by model + normalized text. |

**`state.options` keys written:**
- `research_track_pids` (11167-11169) and `research_pid` (11170-11171).
- `parallel_research`: 11562, 11587 or 11813.
- `global_synthesis_failure`: set at 11563, popped at 11588. `global_synthesis_fallback` is popped at 11589 and never set here.
- `research_track_reconcile` (11759) and `actor_dossier_compaction` (11814).
- Through the budget helper: `research_budget_epochs`, `research_budget_epoch`, `legacy_research_budget_*` (1836-1895).

**In-memory structures:**
- `results: dict[int, (title, track_dir, res)]` (11241).
- `track_local: list[int]` and `failed_tracks: set[int]` (11131-11132).
- `merged_sources: list[dict]`, whose 1-based position is the global `[S#]` id (11277; 6330-6334).

## Config / env knobs

| Knob | Default | Effect | Anchor |
|---|---|---|---|
| `RESEARCH_ENGINE` | `v3` | v3 → 1 outer lane, so this method is never called; legacy/deerflow/agentic → K lanes | config.py:1187; 5955-5981 |
| `RESEARCH_PARALLEL_TRACKS` | 3 (≥1) | K requested by the caller; clamped to 3 by the angle list | config.py:1196; 11077 |
| `RESEARCH_GLOBAL_SYNTHESIS` | true | n>1 and true → evidence-only lanes plus one global synthesis; false → full-report lanes plus deterministic merge | config.py:1200-1201; 11081-11082 |
| `RESEARCH_GLOBAL_SUBAGENT_CAP` | 9 | Bounds concurrent outer lanes and the per-lane subagent split; forwarded to the child env | config.py:1205-1206; 11083; 2372-2373 |
| `RESEARCH_SUBAGENTS_PER_TRACK_MAX` | 5 (1..8) | Per-lane harness subagent ceiling | config.py:1207-1208; 11095 |
| `RESEARCH_GLOBAL_MODEL_CONCURRENCY` | 0 (derive) | >0 caps simultaneous lanes and total model streams; small values disable harness subagents | config.py:1212-1213; 11084 |
| `DEERFLOW_SUBAGENTS` | true | Harness subagents on when `subagent_cap > 0` | config.py:1168; 11098-11099 |
| `DEERFLOW_DUAL_TRACK` | true | Lane 0 owns the Track-B actor dossier; false makes the global path fail closed (Surprise S3) | config.py:1228; 11224-11225 |
| `DEERFLOW_RESEARCH_DEPTH` | `deep` | Depth fallback for the checkpoint-lineage check (and the runner) | config.py:1159; 11185-11188 |
| `DEERFLOW_DIR` | `<repo>/deer-flow` | Target of the pre-launch bridge sync | config.py:1148-1151; 11116 |
| `DEERFLOW_MODEL` | `claude` | Telemetry `model` fallback | config.py:1156; 11603, 11801 |
| `RESEARCH_BUDGET_MAX_EPOCHS` | 3 | Hard cap on budget epochs (one per explicit task/resume) | config.py:543-544; 1851-1856 |
| `RESEARCH_BUDGET_{ATTEMPTS,SEARCH,FETCH}_GLOBAL` | 1800 / 900 / 450 | Pre-launch exhaustion guard thresholds (recorded in the snapshot) | config.py:530-537; 1907-1918; 1785-1802 |
| `RESEARCH_COMPACT_MERGED_DOSSIER` | true | 8b: compact canonical cast dossier instead of a K-way concatenation | config.py:551-552; 11652 |
| `ACTOR_DOSSIER_MAX_CHARS` | 80000 (min 1000) | 8b: dossier char cap | config.py:553-554; 11657-11660 |
| `ACTOR_CAST_MAX` | 20 | 8b: compactor `max_actors` | config.py:1362; 11669 |
| `PREDICTION_MARKETS_MAX` / `_MAX_PER_EVENT` | 20 / 3 | 8b: market union caps | config.py:1425-1431; 11694-11698 |
| `RESEARCH_TRACK_RECONCILE` | true | 8b with ≥2 survivors: one LLM opening reconcile, else deterministic | config.py:525; 11745 |
| `EMBED_WARM_AT_RESEARCH` | false | Enables `_maybe_warm_embedder` | config.py:476; 11840 |
| `EMBED_DISK_CACHE_PATH` | `GRAPHITI_DATA_DIR/embed_cache.sqlite` | Disk cache the warm-up populates | config.py:1253-1256; embedder.py:185-202 |
| `GRAPHITI_EMBED_MODEL` / `GRAPHITI_EMBED_DIM` | `paraphrase-multilingual-MiniLM-L12-v2` / 384 | Warm-up model | embedder.py:43-46 |
| Hard-coded | — | progress ceiling 95 (11144, 11150); publish keep-alive 15.0 s (11155); merge 96, reconcile 97, synthesis band 96-99 (11272, 11746, 11463); synthesis attempts 2 (11473); dossier fallback threshold 800 chars (11673); warm cap about 600 texts, batch 128 (11858, 11869) | as listed |

## External calls

- **Subprocesses.** One per lane, through `DeerFlowResearchRunner.run` (11195), and one per synthesis attempt (11491). Each spawns `deer-flow` python `deerflow_research.py --prompt-file … --out-dir … --model … --depth …` plus `--subagents/--resume/--evidence-only/--synthesis-manifest`, in its own process group (2251-2269, 2428-2437). All provider, web-search and fetch traffic happens inside these children.
- **LLM in-process.** 8b only: one `LLMClient.chat` call in `reconcile_track_reports` (6240-6244), when `survived >= 2` and `RESEARCH_TRACK_RECONCILE` is on.
- **SQLite.**
  - The budget ledger path is created by `_activate_research_budget_epoch` and used by the children.
  - The model-lease DB `RESEARCH_MODEL_LEASE_DB` is passed to the children (2408-2410).
  - The warm-up writes the embed disk cache (embedder.py:244-251, 338-339).
- **Model download.** `SentenceTransformer(model_name)` may download from the Hugging Face hub on first use (embedder.py:226-242).
- **Bridge sync.** File copies from `deerflow_bridge/` to `deer-flow/` (11116 → 1441ff).
- **No direct HTTP or network calls in the slice itself.**

## Cross-module edges

**Callers (grep `_run_parallel_research_tracks|_maybe_warm_embedder`):**
- `pipeline_orchestrator.py:11990` (the `_run` research stage) and `:12208` (warm-up).
- Tests: `backend/tests/test_loop010_global_synthesis.py:483,561,617` call it directly. `backend/tests/test_research_round3_parent.py:107,132` and `backend/tests/test_orchestrator_research_wiring.py:1051,1642,1674` stub one or both methods.

**Outbound, same module:**
- `_RESEARCH_TRACK_ANGLES` (5812), `research_engine_for_run` (5937), `research_outer_track_workers` (5833), `research_model_concurrency_cap` (5845), `research_lane_subagent_cap` (5857), `research_dual_track_for_outer_lane` (5876).
- `_activate_research_budget_epoch` (1815), `_research_budget_exhaustion` (1764), `_research_budget_attempt_ids` (1806), `_sync_deerflow_bridge_if_stale` (1441), `_validated_research_checkpoint_lineage` (2974).
- `DeerFlowResearchRunner.run` (2113), `_note_provider_stage_failure` (580), `_tail` (2739), `_read_text` (2925), `_read_json` (2933), `_preserve_research_attempt_progress` (3078), `_promote_research_contract` (3492).
- `merge_sources_union` (6281), `normalize_track_report_citations` (6318), `merge_track_reports` (6000), `merge_actors_objs` (6433), `merge_list_dedup` (6413), `merge_research_quality` (6469), `merge_market_snapshots` (6549), `merge_market_price_histories` (6715), `_source_tier_histogram` (6495), `reconcile_track_reports` (6195), `_deterministic_track_report` (6121), `append_merged_references` (6388).
- `PipelineManager.save` (945), `PipelineCancelled` (248).

**Outbound, other modules:**
- `research_progress.aggregate_parallel_progress` (backend/app/services/research_progress.py:371).
- `utils.atomic.write_json_atomic` / `write_text_atomic` (backend/app/utils/atomic.py:20, 53).
- `actor_dossier_compactor.render_compact_actor_dossier` (backend/app/services/actor_dossier_compactor.py:151).
- `utils.actors.extract_actor_rows` (backend/app/utils/actors.py:180) and `reconcile_cast` (via 6462).
- `graphiti_client.embedder.LocalSentenceTransformerEmbedder` (backend/app/services/graphiti_client/embedder.py:205).

**Downstream readers of the slice's artifacts:**
- The progress endpoint reads `track_N/research_progress.log` and `research_attempts/*.log` (research_progress.py:418-467).
- Boot orphan reconcile (7703, 7724) and pipeline delete (8077) read `research_track_pids`.
- Synthesis recovery reads `evidence_synthesis_manifest.json` and `track_*/prediction_market_candidates.jsonl` (11916-11959, 10897).
- Actor-lineage validation accepts only lane ids `outer-track-1`, `global-synthesis` and `global-synthesis-recovery` (5089-5092).

## Invariants, gates, validation

- **Lane count.** 1 ≤ n ≤ 3, because the angle list has length 3 (11077, 5812-5818).
- **Concurrency.**
  - Simultaneous lanes = `min(n, RESEARCH_GLOBAL_SUBAGENT_CAP, model_cap or n)` (5842).
  - Per-lane subagents ≤ `model_concurrency // outer_workers - 1` (5866-5873).
  - The child receives `DEER_FLOW_MAX_CONCURRENT_SUBAGENTS` clamped to 1..8 and `RESEARCH_MODEL_CONCURRENCY_GLOBAL` (2366-2371).
- **Progress.** Never regresses within the lane phase (floor `previous`, research_progress.py:392). Lanes cannot exceed 95 (11144). Failed lanes are excluded from the mean (11260, 11151).
- **Budget.** One epoch per task, shared by all lanes and the synthesis (1815-1824). Launch is refused when a global cap is saturated (11104-11111). [verifier: the ledger is shared only while `RESEARCH_BUDGET_ENABLED` is true (2002-2005). The saturation guard can only fire on re-entry into an epoch already in use, because a new epoch resets the snapshot counts (1899-1921). The epoch is allocated before the guard and before the bridge sync (11101-11116), so a failure there still uses up one of the `RESEARCH_BUDGET_MAX_EPOCHS` slots on the next explicit resume (1851-1856)] At most `RESEARCH_BUDGET_MAX_EPOCHS` epochs (1851-1856).
- **Bridge deployment.** Verified before any lane starts (11116).
- **Global path, fail-closed gates:**
  - The baseline lane must survive and own a fresh dossier; no other lane may emit a dossier (11285-11306).
  - Every surviving lane needs a non-empty evidence pack and source ledger and ≥1 verified http(s) source (11318-11344).
  - Actor artifacts must be non-symlink, non-empty and byte-consistent with the runner (11355-11388). The judge hash must match the meta (11411-11419).
  - The synthesis must exit 0 (11513-11517), and promotion requires a ≥400-char report and post-install validation (3536-3538, 3570-3576).
- **Cancellation.** `PipelineCancelled` (a BaseException, 248) is never treated as a skippable lane failure (11251-11252). It is re-raised after the drain (11265-11266) and from the synthesis loop (11521-11530).

## Failure modes & recovery

| Failure | Behavior | Anchor |
|---|---|---|
| Budget epoch cap reached / global caps saturated | `RuntimeError` before any lane launch; explicit resume needed | 1851-1856; 11104-11111 |
| Bridge skill sync / safety overlay invalid | Exception propagates; stage fails before spend | 11116; 1736-1738 |
| One lane raises (subprocess failure, timeout without salvage, short/error report, bad baseline dossier provenance) | Logged, counted on the outage breaker, excluded from progress; other lanes continue. No lane retry [verifier: counted only when the error classifies as provider-level and a breaker is registered (490-495, 586-590)] | 11253-11264 |
| All lanes fail | `RuntimeError("所有并行研究轨均失败…")` | 11267-11268 |
| User cancel | Runner cancel watcher kills each group (≤1 s poll); `_cb` raises pre-spawn for queued lanes; `PipelineCancelled` re-raised after the drain | 11140-11142; 2461-2472; 11265-11266 |
| Outage breaker tripped mid-run | `upd` raises `ProviderOutageHalt` (BaseException) from `_cb` or `_global_progress`. Not caught by `except Exception`, so it unwinds through the drain. The pool's `__exit__` waits for the remaining lanes, which die on their next published progress callback [verifier: `__exit__` is `shutdown(wait=True)`, which does not cancel pending futures. Queued lanes (n > outer_workers) still start, and usually spawn a subprocess: their first `_cb(2)` is normally throttled and so does not reach `upd`, until the next published callback (11153-11159, 2426-2437)] | 8967-8969; 11253 |
| Global path: baseline lost / dossier mismatch / unverified lane sources | `RuntimeError`, even though the other lanes succeeded (all lane spend already paid) | 11285-11306; 11340-11344 |
| Global synthesis attempt fails | Progress log and candidates preserved, staging dir removed, retried once in a fresh dir [verifier: nothing is preserved when the staging dir has no `research_progress.log` (3094-3096). A promotion failure after a successful synthesis is not retried and leaves the staging dir behind (11581-11586)] | 11531-11548 |
| Both synthesis attempts fail | `global_synthesis_failure` recorded, lanes and manifest preserved, `RuntimeError`. The next pipeline attempt routes to `_run_research_synthesis_recovery` without re-running lanes | 11550-11568; 11955-11959 |
| Promotion fails | `_promote_research_contract` restores the prior root generation and re-raises | 3578-3600 |
| Crash or backend restart mid-lane | Lane PIDs persisted (11167-11172) and killed by orphan reconcile (7724-7725). Each lane resumes from its own `track_k/research_checkpoint.json` on the next attempt (11182-11194) | |
| Warm-up failure | Swallowed at debug level; the pipeline is never affected | 11845-11846; 11872-11873; 11877-11878 |

## Surprises

1. **S1 (doc drift, docstring).** The docstring says "某轨失败仅跳过（存活 ≥1 即继续）" (11067-11068). In the default global-synthesis path, **lane 1 (baseline) is mandatory** (11285-11289). Also, any surviving lane that lacks a verified source aborts the whole stage instead of being dropped (11340-11344). The "survive ≥1" guarantee holds only for branch 8b. README.md:572 correctly says lane 1 is mandatory.
2. **S2 (doc drift).** "wall-clock ≈ 1 轨" (11067) is false when `outer_workers < n`, e.g. `RESEARCH_GLOBAL_MODEL_CONCURRENCY=2` gives 2 concurrent lanes for n=3 (5842, 11243-11244). The lanes then run in roughly two waves, followed by a serial synthesis.
3. **S3 (suspected bug).** With the legacy engine, `RESEARCH_PARALLEL_TRACKS>1`, `RESEARCH_GLOBAL_SYNTHESIS=true` and `DEERFLOW_DUAL_TRACK=false`:
   - Lane 0 gets `dual_track=False` (5876-5882, 11224-11225).
   - The evidence-only runner therefore returns `actor_dossier=""` (2650-2657).
   - The stage then always raises "broad baseline evidence lane returned no fresh shared actor dossier" (11293-11296), but only **after** all lanes have spent their budget.
   - No config validation couples these knobs (grep of `DEERFLOW_DUAL_TRACK` in backend/app finds no guard).
4. **S4 (doc drift).** `.env.example:377` says that on global-synthesis failure the system "从基线轨 checkpoint 恢复一次单轨综合". The code refuses any fallback and fails closed (11565-11568). The leftover `state.options.pop("global_synthesis_fallback")` (11589) is the only trace of the removed fallback.
5. **S5 (doc drift).** Comments say a reconcile failure "回退纯拼接（与今日逐字节一致）" (11741-11743; config.py:522-524; `.env.example:659`). `reconcile_track_reports` actually falls back to the deterministic dedup/demoted report (6209-6214, 6277-6278). Similarly, the config comment says markets "取最新" (config.py:1189-1195), but `merge_market_snapshots` is now a relevance-gated union (6549-6557).
6. **S6 (doc drift, line refs).** ARCHITECTURE_MAP.md:46,147 and DRF_ARCHITECTURE.md:403-409 cite `_run_parallel_research_tracks` at `:5806-6391` and the executor at `:5962-5964`. The actual location is 11060-11828 and 11243-11244. DRF_ARCHITECTURE.md:408-409 also says synthesis is "retried twice"; the code makes 2 attempts total, i.e. one retry (11473).
7. **S7 (suspected, docstring vs behavior).** `_maybe_warm_embedder` claims the graph stage "meets a warm model" (11836-11837). The warm thread creates its own `LocalSentenceTransformerEmbedder` instance (11866-11867). The graph runtime lazily creates a separate one (backend/app/services/graphiti_client/runtime.py:363), and models are per-instance (`self._model`, embedder.py:226-242). So the in-process model is loaded twice: the benefit is only the shared sqlite disk cache plus the HF/OS file cache, and memory use doubles. [verifier: "memory use doubles" is overstated. `emb` is a local of `_warm` (11867) and becomes unreachable when the thread ends, so two models coexist only if the graph stage loads its model while the warm thread is still running. The core point is confirmed: the graph stage does not get a warm in-process model] The warm-up also calls the private `_encode` (11870). It is also called *after* research finishes (12208), not "during research" as the docstring says (11833). [verifier: the docstring says "during research/ontology". The thread starts at the end of the research stage (12208), so it overlaps the ontology stage. Only the "research" half is wrong]
8. **S8 (suspected, minor).** `_cb`'s failure-branch republish is wrapped in `except Exception` (11261-11264). `PipelineCancelled` and `ProviderOutageHalt` are BaseExceptions (248, 258), so a cancel or breaker trip at that moment escapes the drain loop immediately. That masks the lane error, and the pool `__exit__` then blocks until the other lanes die.
9. **S9 (suspected leak).** In the synthesis loop, only `PipelineCancelled` and `Exception` clean up the staging dir (11521-11548). A `ProviderOutageHalt` raised through `_global_progress` → `upd` (8967-8969) skips both handlers. It leaves `handoff/.global-synthesis-N-*` on disk without a preserved log. [verifier: confirmed, and there are two more leak paths. The `upd(96, …)` at 11485-11489 runs after `mkdtemp` but outside the `try`, so a `PipelineCancelled` or `ProviderOutageHalt` from it also leaks the dir. A `_promote_research_contract` failure leaks the successful synthesis dir, because the rmtree at 11586 runs only after promotion]
10. **S10 (observation).** The live global-synthesis progress log is in `handoff/.global-synthesis-*/research_progress.log`, which `_progress_sources` does not scan: it reads the root, `track_N` and `research_attempts` only (research_progress.py:418-467). The detailed event stream for synthesis is therefore invisible until promotion or preservation. Only the coarse `[全局综合]` status messages show.
11. **S11 (observation).** Progress can regress on synthesis retry: attempt 2 calls `upd(96, …)` after attempt 1 may have published up to 99 (11463, 11485-11489). [verifier: a *failed* attempt can reach at most 98. The estimator caps at 99 (research_progress.py:182-183), which maps to 96+99*3//100 = 98. 99 needs `on_progress(100)`, which the runner emits only immediately before a successful return (2681-2695). The regression is therefore ≤98 → 96] `upd` itself has no monotonic guard (8975).
12. **S12 (suspected, 8b only).** The legacy concatenation branch writes root files without removing stale ones. Optional files are written only when non-empty (11773-11791), and no contract manifest is written or cleared. A leftover `timeline.json`, `contested.json` etc. from a prior generation, or an older `research_contract_manifest.json`, can survive next to the new report. With a single survivor, the report also keeps its `# Track 1: …` H1 scaffold, because reconcile and demotion run only for `survived >= 2` (11744).
13. **S13 (minor inconsistency).** Per-track numbering differs between outputs:
    - `merge_research_quality.per_track[].track` counts surviving lanes 1..m (6484).
    - `merge_track_reports` renumbers `# Track N` over non-empty bodies (6008-6013).
    - `parallel_research.angles` uses original short keys (11726).
    
    If lane 2 failed, "track 2" means lane 3 in the first two and nothing in the third.
14. **S14 (minor inconsistency).** Evidence-lane artifact checks use `os.path.isfile` and size, which follow symlinks (11318). The actor artifacts explicitly reject symlinks (11357).
15. **S15 (observation).** Lanes 2 and 3 always get a Chinese-language angle prefix ending in "原始预测问题：" (5796-5809), even for English briefs. The output language is governed separately by `research_language` (11200).
16. **S16 (observation, possible race).** `_spawn` mutates `state.options` (`setdefault` of a new key, 11167) under `pids_lock`, not under the state-file lock that `PipelineManager.save` holds while running `asdict(state)` (955-956, 721). A concurrent save from another lane, heartbeat or `upd` could in principle see the dict change size mid-iteration. The window is tiny: the first spawn only.

## Verification

Adversarial pass, 2026-10-11, on the `main` checkout as it is on disk. Every cited anchor was re-opened. Inline `[verifier: …]` notes mark the statements that are wrong or imprecise.

**Verdict counts**
- Key claims (15): 10 confirmed, 5 imprecise, 0 refuted.
- Surprises submitted (13): 11 confirmed, 2 imprecise, 0 refuted.
- Extra spot-checks of Walkthrough, Control-flow, Data, Invariant and Failure-mode statements (22): 12 confirmed, 10 imprecise.

**Non-confirmed key claims, with corrections**
1. *Shared budget ledger and exhaustion guard* (imprecise).
   - Sharing holds only while `RESEARCH_BUDGET_ENABLED` is true. When it is false, `_configure_research_budget_env` pops every budget env key (2002-2005).
   - The pre-launch guard compares `global.attempts`, `search_network` and `fetch_network` against the snapshot's own limits (1783-1797).
   - A newly created epoch resets the snapshot counts (1899-1921), so the guard can only fire when the same task re-enters an epoch already in use (1840-1849).
2. *Lane failure handling* (imprecise).
   - `_note_provider_stage_failure` adds +1 only when a breaker is registered and the error classifies as provider-level (490-495, 586-590).
   - The failure-branch republish can raise `PipelineCancelled` or `ProviderOutageHalt` past `except Exception` (11261-11264). That exits the drain early instead of "collect and re-raise after drain".
3. *Synthesis attempts and preservation* (imprecise).
   - `_preserve_research_attempt_progress` does nothing, sidecars included, when the staging dir has no `research_progress.log` (3094-3096).
   - Preservation runs only on the `PipelineCancelled` and `Exception` handlers. It does not run on `ProviderOutageHalt` (11521-11548), on a raise from the pre-`try` `upd(96)` (11485-11489), or on a promotion failure (11581-11586).
4. *Promotion and merged telemetry* (imprecise).
   - The sum covers surviving lanes only (`ordered`, 11275, 11592-11597), not "all lanes".
   - Failed lanes' and failed attempts' tokens are flushed only by the runner wrapper (2134-2140).
   - The 8b telemetry likewise covers survivors only (11795).
5. *8b writes and reconcile* (imprecise).
   - `actors.json` and `prediction_markets.json` are written whenever the merged value is a dict, possibly an empty one (11775-11776, 11785-11786), not "only when non-empty".
   - `reconcile_track_reports` makes **at most** one `LLMClient.chat` call. With fewer than 2 non-empty lane reports it returns the raw merged report (`"tracks<2"`) with no call and no deterministic fallback (6208, 6217-6219).

**Non-confirmed surprises, with corrections**
1. *Warm-up overclaim (S7)* (imprecise).
   - "Memory use doubles" is overstated. `emb` is local to the daemon thread (11867), so two models coexist only if the graph stage loads its model before the warm thread ends.
   - The docstring says "during research/ontology", and the thread does overlap ontology (12208).
   - Confirmed: the graph runtime builds its own instance (graphiti_client/runtime.py:363), so there is no warm in-process model, and `_encode` is private.
2. *Progress regression on synthesis retry (S11)* (imprecise). A failed attempt can publish at most 98, not 99. The estimator ceiling is 99 (research_progress.py:182-183), which maps to 96+2. 99 needs `on_progress(100)`, which is emitted only right before a successful return (2681-2695).

**Non-confirmed spot-checks, with corrections**
1. `research_engine` "passed to full-research lanes only". It is passed to every lane (11232) and overridden for evidence lanes (2295-2301). The synthesis call omits it. It is always `legacy` here (11983-11991).
2. The epoch helper "creates … research_budget.sqlite3". It only creates the epoch directory and computes the path (1860-1862, 1881); the child creates the DB.
3. "Pipeline delete kills every PID". It does so only when the persisted status is `running` (8071-8078).
4. "Telemetry over every lane". Surviving lanes only (11592-11595).
5. "Reconcile never returns a raw concatenation". It does in the `tracks<2` case (6217-6219).
6. "Lint is always audit-only for 8b". Not when a stale `research_contract_manifest.json` survives (11771-11792 never clears it; 12097-12099).
7. "`.prompt-*.txt` deleted in finally". The `try/finally` starts at 2491. A raise from the pre-spawn `on_progress(2)` at 2426, or a `Popen` failure, leaves the prompt file behind.
8. "Staging dir removed on success/failure/cancel". It leaks on promotion failure (11581-11586), on a raise from the pre-`try` `upd(96)` (11485-11489), and on `ProviderOutageHalt`.
9. "Docstring claims hold only for the legacy path". The wall-clock claim fails in both paths when `outer_workers < n` (5842).
10. Failure-mode row "remaining lanes die on next published callback". `shutdown(wait=True)` does not cancel pending futures, so queued lanes still start and normally spawn a subprocess first (11243-11264, 11153-11159, 2426-2437).

**Confirmed spot-checks (sample)**
- The warm-up runs on the reuse path too (12208 sits after the reuse/run branches converge).
- A lane's final `on_progress(100)` is clamped to 95 (11144, 2681-2684).
- The watchdog starts at subprocess start (2446-2458).
- The cancel watcher polls every 1 s (2464-2468).
- Baseline dossier provenance conditions (2840-2865).
- The bridge accepts manifest versions 1-3 (deerflow_bridge/deerflow_research.py:7341) and loads the dossier via `load_manifest_actor_dossier` (17004).
- Market-candidate carry-over and dedup (11447-11484).
- The compaction fallback threshold is 800 chars (11673-11684).
- The warm-up cap of about 600 texts is checked after each whole row (11858).
- `_encode` checks the LRU, then the disk cache, then computes, keyed by sha256(model\0text) (embedder.py:253-339).
- Checkpoint lineage requires v2 plus a matching hash, depth, run, lane, attempt and identity (2994-3039).
- `_cb` raises before spawn for queued lanes after a cancel (11140-11142, 2426).

**Omissions (significant behavior the map did not cover)**
1. **Synthesis staging-dir leak paths beyond S9.**
   - If promotion fails after a successful synthesis, `.global-synthesis-*` is never removed (rmtree at 11586 runs only after `_promote_research_contract`, 11581-11585). In that case no `parallel_research` or `global_synthesis_failure` metadata is recorded either.
   - The pre-`try` `upd(96, …)` (11485-11489) runs after `mkdtemp` (11475-11476), so a cancel or breaker trip there also leaks the dir.
   - Nothing else cleans `.global-synthesis-*` (grep).
2. **The research question can be left on disk on a pre-spawn cancel.** A queued lane that starts after a cancel raises from `_cb` (11140-11142) inside the runner's `on_progress(2, …)` (2426). That call comes after the `.prompt-*.txt` is written (2244-2250) but before the `try/finally` that deletes it (2491-2575).
3. **Epoch slots are spent before any spend can happen.**
   - `_activate_research_budget_epoch` runs before the exhaustion guard and the bridge sync (11101-11116).
   - A sync failure therefore still records an epoch for that task, and every explicit resume gets a new task id and a new epoch.
   - Repeated pre-spend failures can exhaust `RESEARCH_BUDGET_MAX_EPOCHS` (1851-1856) with no research spend.
4. **The budget guard is mostly inert.**
   - A fresh epoch resets the snapshot (1899-1921), so the guard only matters on same-task re-entry (1840-1849).
   - `RESEARCH_BUDGET_ENABLED=false` (config.py:528-529) strips the ledger env from every child (2002-2005).
5. **Queued lanes still launch after a `BaseException` escape.**
   - A `ProviderOutageHalt` from a lane or from the republish leaves the `with ThreadPoolExecutor` block through `shutdown(wait=True)`, which does not cancel pending futures (11243-11264).
   - Queued lanes then start and normally spawn a subprocess: their first `_cb(2)` is throttled and does not reach `upd`. They die at the next published callback (11153-11159).
6. **Global-path degradation is not surfaced downstream.**
   - When a non-baseline lane is lost, the global path sets only `parallel_research.degraded` (11579, 11584). It does not touch `research_quality`, unlike 8b (11709-11712).
   - `_surface_research_quality` reads `research_quality` and the budget snapshot only (10564ff, about 10582-10605).
   - `parallel_research` has no reader in backend/app or frontend/src (grep), so a degraded global synthesis looks non-degraded to later stages.
