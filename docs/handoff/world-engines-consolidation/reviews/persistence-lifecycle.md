# world-v1 review: Persistence and lifecycle (store, service, results, runner, manager)

- **Reviewed:** `codex/reflexive-world-simulation` at a6fbbc0 (read-only, 2026-10-18 +08), one of four parallel reviews.
- **Line numbers** refer to a6fbbc0 in the Codex worktree unless marked otherwise; the merged tree differs.
- **What was done with each finding** is recorded in [../handoff.md](../handoff.md) §5–§9.

---

I found three blockers: two can permanently stall a world-v1 run after a crash or reboot, and one breaks the simulation list for every engine. All three need fixing before the merge. Line numbers refer to the Codex worktree at a6fbbc0. I modified no repository files; the only things I wrote are a probe script and `git merge-tree` output in my scratchpad.

## 1. Defects

### Blockers

**B1. A dead writer is detected by its PID, which macOS reuses quickly.** `store.py:68-83, 308`; `service.py:21-30, 136-139`
- **Scenario:** reboot mid-run.
  - The child has no SIGTERM handler, so it dies without running its cleanup. The writer row keeps `owner`, `pid=P`, and `world_run.json` stays `running`.
  - macOS hands out PIDs sequentially (there is no `kern.randompid`). On this Mac, booted at 01:38 today, 874 of 1,082 live PIDs are ≤5000 and the counter has already reached 99,599, so P is quickly reused. A permission error from a root daemon also counts as "alive".
- **Result:**
  - `status()` reports `running` forever.
  - Every `start()` spawns a child that fails `writer_active` before acquiring a fence. `run_child` then discards the error: nothing is recorded or logged (`service.py:286-291`).
  - The pipeline only gives up after its 30-minute stall timer. There is no way for an operator to release the writer.
- **Fix:** every write already re-checks the fence, so wrongly declaring a writer dead is harmless. That means the launch flock, which the kernel releases on death and on reboot, can decide liveness:
  - In `run_child`, confirm the inherited fd holds the lock (`flock(fd, LOCK_EX|LOCK_NB)`), then take over without calling `_alive`.
  - In `status()`, treat `_launch_active()` as authoritative.
  - Log failures that happen before the fence is acquired.
  - Turn SIGTERM into cancel-and-release.

**B2. World database creation is not atomic.** `store.py:105-129`, called from `service.py:272`
- **Mechanism:** `sqlite3.connect` creates a 0-byte file immediately. Until the init transaction commits, any read-only reader sees `application_id=0` and raises `unsupported_store`. A rolled-back init leaves the file in that state. A scratch SQLite probe reproduced all three states.
- **Scenario a:** the pipeline polls `get_run_state` every second (`pipeline_orchestrator.py:8649`). A poll that lands during the first launch's init raises; `_wait_world_simulation` catches it, stops the healthy world and fails the stage.
- **Scenario b:** any init failure (kernel error, disk full, kill) leaves that file behind. From then on `status()` and `start()` (`service.py:179`, which runs before spawning) raise a misleading `unsupported_store` forever. Recovery needs manual file deletion, and B3 turns it into an outage for all engines.
- **Fix:** initialize in a temp file with `journal_mode=DELETE`, fsync, `os.replace`, then switch to WAL. Alternatively, have readers treat "no tables and `application_id` 0" as uninitialized round 0.

**B3 (affects OASIS users). One bad directory fails `/history` and `/list` for every engine.** `simulation_manager.py:796-813, 1570-1584`
- **Mechanism:**
  - `_load_simulation_state` now applies the world identifier regex, symlink refusal and the artifact-pin check to every directory, before checking that `state.json` exists.
  - `list_simulations` has no per-entry guard.
  - `_project_world_status` propagates any `status()` error.
- **Scenario:** a Finder duplicate named `sim_x copy`, a symlinked simulation directory, or one B2-broken world makes `GET /api/simulation/history` (unfiltered) fail for everyone.
- **Fix:** wrap each entry in try/except, log it, and return a stub with `status=failed` and the error code. Fail loudly only on single-simulation reads.

### Major

**M1 (affects OASIS users). The world stop loop in `cleanup_all_simulations` is unguarded.** `simulation_runner.py:2467-2469`
- It runs inside the signal handler, before OASIS teardown.
- If any `stop()` raises (B2 window, corrupt or deleted directory), OASIS children are never terminated and the original signal handling is skipped.
- **Fix:** try/except per world, and run the loop after OASIS teardown.

**M2. Resuming after a crash uses up retry attempts that can never be restored.**
- `maxAttemptsPerSlot` is hard-capped at 2 (`contracts.py:201`), and attempts left `unknown` by a dead writer count toward it (`store.py:485-486`).
- Without review: a reboot costs every in-flight slot (up to 4) one attempt. After that, a single invalid model output kills the world.
- With `decisionReview` pinned: an `unknown` or transport-failed stage is terminal (`controller.py:93-100`), raising `consistency_candidate_unavailable` or `consistency_revision_exhausted`.
- Provider quota errors are indistinguishable from model failures. The only remedy is forking from round 0.
- **Fix:**
  - Mark attempts from a superseded fence as `abandoned`: keep their budget exposure, exclude them from the per-slot count, and allow the stage to be re-dispatched.
  - Give transport failures a separate small retry allowance.

**M3. Exported results are bound to the exact renderer output and spec normalization.**
- `load_frozen_result` compares the saved result with a fresh render (`results.py:129-133`). `validate_recoverable_export` refuses to overwrite a file that doesn't match (`results.py:97-103`).
- So any edit to `_project` or `_render_bundle` — even translating the `interpretation` string for the bilingual UI — flips every completed world to `failed: result_binding_mismatch`, with no repair path.
- `validate_spec` merges `DEFAULT_LIMITS` into each spec (`contracts.py:196`). Adding a new default changes `specHash`, and every existing world then fails with `input_binding_mismatch` or `corrupt_store`.
- **Fix:**
  - Put a renderer version in the result manifest.
  - Re-export when the manifest's revision matches the committed head but the version differs.
  - Version the spec normalization.

**M4. Size bounds are inconsistent, and `/world` responses are unbounded.**
- `export_result` writes with no size limit, but every reader, including recovery, uses `read_json`'s 16 MiB cap (`artifacts.py:55`). A long-horizon world can commit successfully in SQLite and then be permanently `failed: artifact_too_large`; the trajectory repeats every section for every round.
- `GET /world` (`api/simulation.py:2935-2962`) returns the full trajectory and all events, plus the whole attempt ledger in the analyst view. The UI re-fetches it every 10 s. Our `/world-state` caps rows at 200 and bounds bytes.
- **Fix:** check size at export time, and paginate or bound `/world` with a `rows=` parameter.

### Minor
- **m1. Decision save gap (non-review mode):** recording the attempt result and saving the decision are separate transactions (`controller.py:156-157`). A kill between them throws away a paid decision and burns an attempt. Merge them into one transaction.
- **m2. Stop and cancel:** `stop()` (`service.py:217-223`) never persists `stopping`, so the next poll shows `running` again. The cancel file is keyed to the generation, not the launch, so a stop aimed at launch A can cancel launch B.
- **m3. Spurious start rejection:** the `_launch_active` probe briefly takes the exclusive lock (`service.py:33-45`), so a concurrent `start()` can get a false `world_running`.
- **m4. File descriptors and symlinks:** `start()` opens the launch lock without `O_NOFOLLOW` (`service.py:173`), and `world_child.log` follows symlinks. The child leaves the inherited fd inheritable and only checks device/inode (`service.py:264-267`), never that it actually holds the lock.
- **m5. Poll cost:** each `get_run_state` performs at least two full integrity loads (quick_check, whole revision chain, review journal), plus a full re-render once the world is complete. That happens every second from the pipeline, and again per world on list calls.
- **m6. OASIS hot path:** `get_run_state` now reads `state.json` and validates the path before checking the in-memory cache. `to_dict` adds `simulation_engine` to every OASIS `run_state.json`, contrary to the "hours-mode bytes unchanged" comment. The existing test still passes because it only bans specific keys.
- **m7. macOS durability:** neither `synchronous=FULL` nor `atomic_json`'s `os.fsync` issues `F_FULLFSYNC`, so a forced power-off can lose acknowledged commits or leave an export newer than the database.
- **m8. Windows:** `fcntl`, `pass_fds` and directory fsync are POSIX-only. Worse, `os.kill(pid, 0)` terminates the target process on Windows, and `status()` calls `_alive` eagerly (`service.py:136`). Gate world-v1 to POSIX at admission.
- **m9. Preparation crash:** a crash between `seal_inputs` and `_pin_world_preparation` leaves `generation_exists` forever. Adopting the valid sealed manifest would recover it.
- **m10. API errors:** `GET /world` before the first launch returns `missing_world` as a 400, and `sqlite3.OperationalError` is uncaught (500).

## 2. Solid — keep unchanged
- One database per world; `BEGIN IMMEDIATE` with fence and head checks inside the transaction; schema identity pragmas; full revision-chain and event-index verification on open.
- `commit_round` replays the pure kernel against the persisted decisions.
- Reservations are durable before dispatch; budget exposure is actual plus unknown, and it holds across separate connections.
- Observation and decision IDs are content-derived, so resume is idempotent.
- Fences make two simultaneous writers harmless at the database level, and takeover itself is serialized.
- Cancellation is checked before each reservation and before commit, so a stop never orphans an attempt.
- `read_bundle` reads one snapshot; GET never repairs; the final-round recovery handles a crash between writing the result and its manifest.
- Launch exclusivity via an inherited flock; `atomic_json`; `read_json` refuses symlinks and duplicate keys.
- Simulation-ID path containment (identifier regex plus resolved-parent check) is sound.
- The manifest pin chain and launch-ID check, and the engine admission guards.

## 3. Integration risks with our reflexive world model
1. **Frontend conflict with a semantic trap:** `getSimulationPosts` and `getSimulationComments` both use the 5th positional parameter, but ours is `round` and Codex's is an `options` object. Resolving the conflict to one side either sends `round=[object Object]` (400) or silently drops the round filter. Use `{round, ...options}`. `SimulationView.vue` also conflicts.
2. **Silent merges:** `simulation_runner.py` and `api/simulation.py` merge textually clean, and `simulation_manager.py` isn't touched on `main`, so B3, M1 and m6 land with no conflict to flag them.
3. **Two "world" vocabularies in one directory:** no filenames collide today. Keep `_STALE_DERIVED_ARTIFACTS` an explicit list — a `world_*` glob would delete world-v1's authoritative files. `/world-state`, `/feed-rounds` and the `round=` filters return 404 or empty for world-v1; return `unsupported_capability` as interviews do, and pick the UI panel by `simulation_engine`.
4. **No run state or run summary:** world-v1 never writes `run_state.json` and never enters the run-state cache or the monitor thread, so our `world_update` → `options.world_model` and `run_summary.world_model` never apply. Its `write_run_summary` branch (`simulation_runner.py:2100-2103`) raises when incomplete, returns a world-result dict and writes no `run_summary.json`. Our pipeline treats that file as completion evidence (around lines 10637-10675 and 13741-13764), so those gates must check the engine first.
5. **Calendar mode:** `_world_run_state` sets `temporal_mode="calendar"`, so our calendar UI and summary code will treat world-v1 as an OASIS calendar run.
6. **Shared provider quota:** world children share no concurrency limiter with OASIS (`get_oasis_semaphore` is per process). Concurrent runs can exhaust provider quota, which M2 makes terminal for world-v1.
7. **Merge-time edits:** because of M3, unifying vocabulary or translating strings in `results.py` during the merge would break every existing world-v1 result.

Files reviewed are under `/Users/rogerlin/.codex/worktrees/reflexive-world-simulation/DeepResearchForecast/backend/`: `app/services/world_simulation/{store,service,results,artifacts,controller,contracts}.py`, `scripts/run_world_simulation.py`, `app/services/simulation_{manager,runner}.py`, `app/api/simulation.py`. The SQLite probe is at `/private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/8488656d-00c7-4477-b942-5011cbd7a86c/scratchpad/sqlite_init_probe.py`.
