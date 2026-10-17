# Handoff.md — consolidating the two world engines (claude reflexive world model × Codex world-v1)

**Last Updated (UTC):** 2026-10-17T18:40Z
**Status:** In Progress
**Current Focus:** finish the reviews and suites on `claude/world-engines-consolidation`, fix what they find, document both engines, then merge into `main` once the OPEC+ run (`pipe_fd2799f3ad41`) has finished.

Interpret MUST/SHOULD/MAY per RFC 2119.

## 1) Request & Context
- **Owner's words (2026-10-18 02:21 +08):** first "Yes. After the OPEC+ run finishes, merge claude-reflexive-world-state-model and refs/heads/claude/zealous-fermi-496656, refs/heads/claude/epic-villani-949705, refs/heads/claude/dazzling-varahamihira-e0bba5 into main via a test worktree with the suites run, then push main.", then, interrupting: "actually, review the world-v1 from the codex world state branch, review it, and consolidate it with the current claude world state branch and combine them and then merge it into the main".
- **Reading adopted:** the follow-up approvals stand (nothing retracted them); the new instruction adds the Codex `world-v1` engine — reviewed and combined with the claude world model — to what goes into `main`. The merge waits for the OPEC+ run, as the first message asked.
- **The two engines:**
  - *claude reflexive world model* (default): runs inside the OASIS social simulation — `world_model.py`, `agent_decision.py`, `world_update.py`, `world_model_seed.py`, `_ReflexiveWorldCoordinator` in `run_parallel_simulation.py`, `/world-state`, `/feed-rounds`, World State panel and per-period feed; consent rule, modelling gaps and behaviour diagnostics already ported from world-v1 (merge round of 2026-10-17, `docs/handoff/world-state-merge/handoff.md`); live-validated twice.
  - *Codex world-v1* (opt-in, `simulation_engine: "world-v1"`): a separate engine that replaces the social simulation for a run — typed ledger world, compiler from research evidence, round controller with proposal/response phases, deterministic kernel, fenced SQLite store, strict budgeted HTTP policy, decision review/consistency modes, `/world` API, WorldSimulationView, conditional report appendix. Branch `codex/reflexive-world-simulation`, tip a6fbbc0 (15 commits on old main 8852ce1). Its delivery keeps it opt-in.
- **Constraints:** the deployment checkout (`/Users/rogerlin/Downloads/DeepResearchForecast`) serves running pipelines from its working tree and carries another process's uncommitted edits, so all work happens in the worktree `/Users/rogerlin/Downloads/drf-world-consolidation` (branch `claude/world-engines-consolidation`); OASIS stays the default engine (`DEFAULT_SIMULATION_ENGINE=oasis-legacy`); Codex's guarded tests run through `backend/scripts/main_offline_pytest.py` on a frozen copy.

## 2) Requirements → Acceptance Checks
| Requirement | Acceptance check | Evidence |
|---|---|---|
| R1 follow-ups merged | merge the three approved branches; world/translation suites | §8 |
| R2 world-v1 reviewed | four parallel read-only reviews (core engine; persistence and lifecycle; model-facing; integration and UI) with findings triaged | §5, §6 |
| R3 engines combined | both engines selectable in one tree; the simulation tab routes by the saved engine; report/API keep both paths; OASIS default unchanged | §7 |
| R4 suites | full plain backend suite, all guarded tests under the runner, frontend tests, build, ruff, env drift | §8 |
| R5 merged into main | after the OPEC+ run: merge into `main`, push `main` | §8, §10 |

## 3) Plan
1. Consolidation worktree from the branch tip (dcff768); merge the three follow-ups. **Done.**
2. Merge `codex/reflexive-world-simulation` (a6fbbc0); resolve conflicts. **Done** (ad1c0ee).
3. Reviews in parallel with the merge; triage; fix blockers/majors that affect the combined tree or OASIS runs.
4. Docs: README (EN/ZH, line-aligned) — two engines; design notes; feature list.
5. Suites as R4; dashboard check of both views.
6. After the OPEC+ run: merge into `main`, push.

## 4) To-Do & Progress Ledger
- [x] Worktree and follow-up merges — 06ae11b (zealous-fermi), e51d621 (epic-villani), ecf4cf3 (translation chain); record conflicts resolved in date order; world + translation suites 261 passed, frontend 163 passed.
- [x] Codex merge — ad1c0ee; text conflicts in 5 files only (SimulationView.vue, api/simulation.js, report_agent.py, feature_list.json, agent-progress.txt); Codex's frontend harness extended; frontend 217 passed, build OK.
- [ ] Reviews (4) and triage.
- [ ] Full plain suite; guarded suite.
- [ ] Fixes, docs.
- [ ] Merge into main after the OPEC+ run.

## 5) Findings, Decisions, Assumptions
- **Finding:** the Codex branch moved after the 2026-10-17 study (95ebd04 → a6fbbc0: decision review modes v2–v4, candidate repair, consistency controller, default/fresh admission, transport diagnostics); its worktree was clean at the merge.
- **Finding:** textually the two implementations barely overlap — the orchestrator, runner, manager and API merged without conflicts; the conflicts were the simulation tab and its API module.
- **Decision:** the simulation tab first resolves the saved engine (Codex's routing and request gate); world-v1 runs render WorldSimulationView, OASIS runs keep the World State panel and the per-period feed. The selected period travels as `options.round` so Codex's request-options argument and its tests stay as they were.
- **Decision:** OASIS remains the default (`Config.DEFAULT_SIMULATION_ENGINE` defaults to `oasis-legacy`).

## 6) Issues, Mistakes, Recoveries
- (filled from the reviews and suites)

## 7) Scenario-Focused Resolution Tests
- (filled per step)

## 8) Verification Summary
- Follow-up merges: world + translation suites 261 passed; frontend 163 passed.
- Codex merge: frontend 217 passed (incl. Codex's 24 simulation-tab tests with the extended harness); build OK.

## 9) Remaining Work & Next Steps
- Everything unchecked in §4.

## 10) Updates to This File (append-only)
- 2026-10-17T18:40Z: created after the follow-up and Codex merges; reviews and suites running.
