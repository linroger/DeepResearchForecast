# Handoff — reflexive world-state model: realism, reflexivity and robustness (iteration 2026-10-20)

**Last Updated (UTC):** 2026-10-20T17:35Z
**Status:** Complete for this iteration — merged into `main` as acf9b09 on 2026-10-20 at 22:47 +08 and pushed to legacy (8bf156d..main) at 23:02 +08, both on the owner's request; the reader iteration (§11) is on `claude/brave-stonebraker-d2b98b`, not merged or pushed; a live run awaits the owner's approval
**Current Focus:** none; next candidates in §9.

The words MUST, SHOULD and MAY are used as in RFC 2119.

## 1) Request & Context
- **Owner's request (2026-10-20, verbatim):** "keep on iterating and improving and enhancing the world state model and make it more realistic and robust and reflective of realworld dynamics, including reflexivity".
- **What "the world state model" is:** the default engine's reflexive world-state model (OASIS social simulation + `backend/app/services/world_model.py` kernel, `agent_decision.py`, `world_update.py`, coordinator `_ReflexiveWorldCoordinator` in `backend/scripts/run_parallel_simulation.py`; design in `docs/handoff/reflexive-world-state/design.md`). The opt-in world-v1 engine (`world_simulation/`) is out of scope for this iteration.
- **Constraints carried over:** never modify the deployment checkout `/Users/rogerlin/Downloads/DeepResearchForecast` or its uploads (it serves live pipelines on 5001/5013); use its venv; run suites on frozen rsync copies without `backend/uploads`; guarded modules only under `backend/scripts/main_offline_pytest.py` with a new evidence dir; no paid live runs and no pushes without the owner's approval; `git`/`gh` with `env -u GH_TOKEN`; hours mode and `SIM_WORLD_MODEL=false` stay byte-identical (design §2.1); the herding guard I-1 (agents never see scenario shares) holds.
- **Branch:** `claude/agitated-albattani-b57618` (worktree `.claude/worktrees/agitated-albattani-b57618`), fast-forwarded to `main` 8bf156d before this work.

## 2) Gaps found (evidence from the code at 8bf156d)
| # | Gap | Evidence | Kind |
|---|---|---|---|
| G1 | Every GLM call is refused since 2026-10-18 ~20:37 +08: `Config.reasoning_extra_body('glm')` sends `thinking: disabled`, glm-5.3 answers HTTP 400 / code 1210 ("always thinks; use low, high or max"). The world model's decisions and arbiter go through `LLMClient`, so a live run would degrade to every actor holding (`failed`) and every arbiter round `failed`. | `config.py:835-861`, `llm_client.py:927-991`; `docs/handoff/world-engines-consolidation/real-dossier-replay/live-2026-10-18/diagnose-400.json`; that handoff §9 calls it urgent | robustness |
| G2 | Delayed effects bypass the per-round change clamp: `fire_due_effects` calls `set_value` without `max_change_ratio`, so an arbiter-scheduled effect can move a fact without bound (and flip its sign) a period later. | `world_model.py:1337-1376` | robustness |
| G3 | The clamp also blocks real policy jumps: an announced instrument setting (a tariff raised from 20% to 145% in one month, a policy rate cut by 50 bp from 0.25%) can only move 50% of its magnitude per period, so the world lags the actors' own announcements by several rounds. | `StateVariable.set_value`, `apply_arbiter_update` | realism |
| G4 | Reputation is dead state: changed by breaches and arbiter resolutions but never shown to any actor, never given to the arbiter and never used. Real counterparties discount the threats and promises of actors who broke commitments. | `world_model.py` (`reputation` only written), briefs and arbiter prompt never read it | reflexivity |
| G5 | Expectations are elicited and thrown away: each decision returns `expected_reactions` (what the actor expects others to do), but nothing stores them, compares them with what happened, or lets announcements and shared expectations move the world before measures take effect. The perception → fundamentals → perception loop (reflexivity proper) is missing. | `agent_decision.parse_decision` keeps them only in `world_actions.jsonl` | reflexivity |
| G6 | Red lines are shown only to their owner; the arbiter never sees them and nothing detects a move that crosses one, so escalation after a red line is crossed depends on luck. | `render_private_brief` only; `build_arbiter_prompt` omits them | realism |
| G7 | The arbiter sees each fact's current value only (no trajectory), and the public brief shows only last period's change, so momentum and multi-period trends are invisible to both. | `build_arbiter_prompt`, `render_public_brief` | realism |
| G8 | The world never reaches the outcome distribution: scenario shares are stepped only from the actors' self-declared `scenario_commitment`s; the arbiter's world-grounded `scenario_pressure` is recorded and ignored. A signed deal or a collapsed tariff does not move the outcome unless actors say so. | `_commit_round` in `run_parallel_simulation.py:4333-4393`; `record["scenario_pressure"]` unused | realism |

## 3) Requirements → Acceptance Checks
| Req | Acceptance check | Expected | Evidence |
|---|---|---|---|
| R1 (G1) | A GLM call whose provider answers 400 / 1210 "thinking cannot be disabled" is resent once with thinking enabled at a low reasoning effort; later calls of the same provider/model go straight to the accepted setting; other 400s are not resent; non-GLM providers unchanged. | One extra request only on the 1210 refusal; process-wide memory; max_tokens headroom for the reasoning | new `tests/test_llm_thinking_refusal.py`; existing llm_client tests green |
| R2 (G2) | A delayed numeric effect is clamped like an arbiter change. | effect moves at most `max_change_ratio` × magnitude | kernel test |
| R3 (G3) | An arbiter change attributed (`caused_by`) to an actor whose move this period announced that exact figure applies in full (no clamp) but never crosses zero; unattributed or unannounced changes stay clamped. | 20 → 145 in one round when announced; 20 → 30 otherwise | kernel + validation tests |
| R4 (G4) | Each actor carries a deterministic track record (commitments kept / lapsed / breached, agreements honoured / broken, blocked moves); the public brief shows it for actors with a record, the arbiter weighs moves by it, the actor sees its own. | brief lines and arbiter prompt lines present; no scenario shares | kernel + prompt tests |
| R5 (G5) | Expected reactions are stored per actor; the next private brief shows "you expected X to …; X actually …"; the arbiter sees the expectations in play and is told that announcements and shared expectations move markets and counterparties before measures take effect, weighted by credibility. | private brief and arbiter prompt carry them; bounded | tests |
| R6 (G6) | The arbiter receives the red lines of the actors a move touched and may report `red_line_crossings`; validated ones become `red_line` events aimed at the aggrieved actor, push the relationship apart, appear in the public brief, and give the aggrieved actor response options next period. | event, nudge, brief line, menu options | tests |
| R7 (G7) | The arbiter prompt shows each fact's recent path; the public brief marks multi-period trends. | "(was a → b → c)" / "rising for N periods" | tests |
| R8 (G8) | When the arbiter applied, its `scenario_pressure` enters the share step as a bounded world channel (`SIM_WORLD_PRESSURE_WEIGHT`, default 0.35 of the actors' committed weight; 0 disables), recorded per round in the trajectory/history; failed arbiter rounds add nothing; invalid rounds still freeze. | shares move toward "up" scenarios even when actors abstain; channel weights recorded | pure helper tests + loop test |
| R9 | Reflexive loop end to end (offline, scripted LLM): an announced measure lands, crosses a red line, the target responds, a breach shows in the breacher's public track record, expectations are compared, and the world channel moves the shares. | one scenario test covering the chain | `tests/test_world_reflexivity.py` |
| R10 | No regressions: plain suite 0 failures apart from the 19 known `test_legacy_official_data.py` errors; guarded runner only the 3 known guard failures; frontend unit + build green. | as stated | frozen-copy runs, evidence dirs recorded in §8 |

## 4) Plan (increments, in order)
1. **G1** LLM client: classify the 1210 thinking refusal; resend once with `thinking: enabled` + `reasoning_effort` (`LLM_THINKING_REFUSED_EFFORT`, default `low`) and token headroom; remember per (provider, model). Highest risk to live runs, independent of the kernel → first.
2. **G2 + G3** kernel bounds: clamp delayed effects; announced-figure instrument jumps with a zero-crossing guard; `last_action` keeps the bounded statement/terms the check needs.
3. **G4** track record: computed from commitments and interactions (no new stored state beyond what exists); briefs, arbiter prompt, API actor rows.
4. **G5** expectations: stored on the actor, compared in the private brief, listed for the arbiter with the announcement-effect instruction.
5. **G6** red lines in the arbiter contract, `red_line` events, menu responses.
6. **G7** trends in the arbiter prompt and the public brief.
7. **G8** world channel into the share step (coordinator + pure helper).
8. Reflexive-loop scenario test, docs (design §2.11, README EN/ZH line-aligned), suites, commit.
- **Order rationale:** G1 blocks any live use; G2/G3 change numbers the later features rely on; G4/G5 feed the arbiter prompt that G6/G7 extend; G8 consumes the arbiter's output last.
- **Rollback:** each increment is its own commit; G8 is switchable off with `SIM_WORLD_PRESSURE_WEIGHT=0`.

## 5) To-Do & Progress Ledger
- [x] Increment 1 (G1) — 52a9b37; `tests/test_llm_thinking_refusal.py` (16).
- [x] Increment 2 (G2, G3) — f599827; `tests/test_world_announced_settings.py` (10).
- [x] Increments 3–6 (G4–G8) — 63aa8c7; `test_world_track_records.py` (7), `test_world_red_lines.py` (5), `test_world_pressure_channel.py` (12); two existing tests that pin the behaviour dict exactly gained the two new keys (`test_world_update.py`, `test_world_model_loop.py`).
- [x] Increment 8 — `tests/test_world_reflexivity.py` (the chain end to end), README EN/ZH (still 2,007 lines each), design §2.11, this record, `agent-progress.txt`.

## 6) Findings, Decisions, Assumptions
- **Finding F1 (G1 was wider than the world model):** the OASIS agents' model (`oasis_llm.py`), the settings connectivity test and `preflight.py` sent the same refused payload as `LLMClient`; on GLM every agent post would have failed, not only the world-model calls. All four now take the shared rule.
- **Finding F2 (kernel defect found by the new tests):** a `break_alliance` in the period an agreement obligation fell due first marked that obligation `fulfilled` (the mechanical "any non-hold move honours a due commitment" rule), so the breaker kept a clean record. A withdrawal no longer honours the obligations it breaks.
- **Finding F3:** red-line matching by plain containment let a bare keyword ("warships") match a whole red line; a contained fragment must now cover 60% of it, or half its content tokens must be repeated.
- **Finding F4:** a move that crossed a red line produced two response sets on the target's menu (one for the move, one for the crossing); the crossing now replaces the plain response.
- **Assumption A1 (open):** glm-5.3 accepts `thinking: enabled` + `reasoning_effort: low` on chat completions. Evidence for: the 1210 message itself and the default research engine's GLM ladder, which sends exactly this. Falsified only by a live call (needs the owner's approval).
- **Decision D1 (G1):** a static rule for `glm-5*` plus runtime learning, instead of flipping `LLM_DISABLE_THINKING`: other GLM models and gateways may still accept the disable switch, and a refusal costs one resend per model per process.
- **Decision D2 (G3):** an unclamped change needs three things — attribution to an actor, that actor's own move this period of an instrument-setting kind, and the figure (new value or size of change) in its statement or terms; it may not cross zero. Commentary (communication kind) never sets a figure. Coincidental figure matches remain possible; the arbiter still chose the value.
- **Decision D3 (G4):** the track record is computed from recorded state only (the 24 newest commitments, arbiter outcome counts); `released` obligations are not the actor's failure. No reputation score is shown (it mixes sources); counts are.
- **Decision D4 (G5):** expectations are juxtaposed with what happened, not judged: the next-period move is shown verbatim and `reacted` only means the named actor made a non-hold move. An LLM verdict on "met / not met" would add a call and an unverifiable judgement.
- **Decision D5 (G8):** world weight 0.35 of the actors' committed weight and tilt 0.25: in a committed round the world is about a quarter of the target; in an abstained round it alone sets the target, and the calendar inertia (0.7) still damps it to a few points per period. Round statuses stay the actors' (Foglamp semantics unchanged); `0` restores the old behaviour.
- **Decision D6:** brief budgets raised from 2,400 / 900 to 3,200 / 1,300 characters for the new sections (≈ +200 tokens per decision prompt).

## 7) Scenario-Focused Resolution Tests
- **Before/after demonstration** (`before_after.py`, APIs both trees share; outputs `before_after_main.json` / `before_after_branch.json` in `/Users/rogerlin/Downloads/drf-guarded-runs/20261020-215513-realism-before-8bf156d/`):

  | Scenario | `main` 8bf156d | this branch |
  |---|---|---|
  | glm-5.3 chat call (gateway refuses `thinking: disabled` with 400 / 1210) | raises `BadRequestError`; payload `thinking: disabled` | succeeds; payload `thinking: enabled`, `reasoning_effort: low` |
  | US move "Tariffs rise to 145%", arbiter sets 145 `caused_by` US | 30 (clamped) | 145 |
  | Arbiter reports the crossing of China's red line | ignored; prompt never lists red lines | `red_line` event; prompt lists them |
  | Expected reactions of the US move | not stored | stored |
  | Delayed effect −3,900 on 4,000 (ratio 0.5) | 100 (unbounded) | 2,000 |
  | Accept, then withdraw when the obligation falls due | US obligation `fulfilled` | `breached` |
  | Public brief carries track records | no | yes |
- **New tests on `main`** (same evidence dir, `pytest2.log`): 13 failed, 3 modules error at import (names that do not exist there); every new behaviour fails before. Verdict: resolved.

## 8) Verification Summary
All on 2026-10-20 (+08:00) against the working tree at 63aa8c7 plus the docs and `test_world_reflexivity.py`, each on a new frozen rsync copy without `backend/uploads`, with the deployment venv.
- **Plain suite** (`/Users/rogerlin/Downloads/drf-guarded-runs/20261020-215807-realism-plain/`): JUnit `tests=8089 errors=19 failures=0 skipped=1352` = 6,718 passed, 1,341 skipped, 11 xfailed, 19 errors, 0 failed. The 19 errors are the known `test_legacy_official_data.py` cases (untracked deer-flow checkout). 8,089 = the 8,038 of the `main` integration run (`20261018-205943-final2-plain`) + the 51 new tests.
- **Guarded runner** (`20261020-220509-realism-guarded/`, module list in `modules.txt`): 55 modules (every `guarded_runner` module plus every unguarded world module except the world-model / update / delta ones the plain suite runs), 1,611 tests: 1,608 passed, 3 failed — the known guard failures (`test_deployment_sidecar_control_flow.py` ×2, `test_official_data_end_to_end.py::test_guarded_mcp_to_promoted_research_and_report_png`). Receipt: no source drift, identity preserved.
- **Targeted during development:** world-model suites (`test_world_model*`, `test_world_update`, `test_world_interactions`, `test_agent_decision`, `test_world_delta`, `test_feed_rounds`, the new modules) 196 + 31 loop tests green after each increment; reasoning-option suites (every module touching `extra_body`, `llm_errors`, the OASIS guard, settings and preflight) 944 passed.
- **Gates:** `uvx ruff@0.17.1 check --select F,E9 --ignore F401,F841,F541 backend/app backend/scripts deerflow_bridge` and `--select F,E9` on the new modules pass; `check_env_drift.py --strict` exit 0 (three new `LLM_*` variables documented in `.env.example`); `compileall` OK.
- **Not run:** frontend tests (no frontend file changed); no paid live run (owner's approval needed); nothing pushed.

## 9) Remaining Work & Next Steps
- **Live run (owner's approval):** the only way to see the new mechanics on real artifacts and to falsify A1. Watch: `glm` calls succeed with `reasoning_effort: low`; `world_state.json` actors' `track_record`; `red_line` events; `expectations_checked/reacted` in `summary.behaviour`; trajectory `channels`.
- **Deployment:** the deployment checkout still serves `claude-reflexive-world-state-model` with another process's edits; nothing here reaches it until it runs `main` after this branch is merged.
- **Not done in this iteration (candidates):** the World State panel does not yet show track records or the expectation counts (the API returns them); the report's world-evolution block does not list red-line crossings or track records (*both done in the reader iteration, §11*); exogenous shocks from researched risks with base rates (the seed has no such field yet); private negotiations (offers are public today); commitment fulfilment stays mechanical (any non-hold move except a withdrawal honours a due commitment).

## 10) Updates to This File (append-only)
- 2026-10-20T13:30Z: created with the brief, the eight gaps, acceptance checks and the plan.
- 2026-10-20T14:05Z: increments 1–8 done (52a9b37, f599827, 63aa8c7 + docs); findings F1–F4, decisions D1–D6, before/after evidence (§7); suites pending (§8).
- 2026-10-20T14:10Z: final plain and guarded suites recorded (§8); status Complete for this iteration.
- 2026-10-20T14:48Z: merged `claude/agitated-albattani-b57618` (b8cc994) into `main` as acf9b09 (`--no-ff`; `main` had no other commits, so the merged tree a5f59fe… is the tested tree). Pushed to legacy at 23:02 +08 (fast-forward from 8bf156d; secret scan of the 6 commits clean).
- 2026-10-20T15:25Z: reader iteration recorded (§11): panel and report lines for track records, red lines and expectation counts; §9 candidates annotated.
- 2026-10-20T17:35Z: `main` (303e5a8) merged into the reader branch (2070d30); F5 fixed (headline counts red-line crossings); suites on the merged tree recorded (§11.6).

## 11) Reader iteration — the panel and the report show the new signals (2026-10-20, +08:00 22:46–23:30)
- **Request (from the session that ran §1–§10):** surface the reflexive world model's new signals to readers. World State panel: each actor's `track_record` (kept, lapsed, broken, released, open, resolved, reliability, outcomes), breakers first; `red_line` events with a readable label in both languages; the run summary's `behaviour.expectations_checked` / `expectations_reacted` beside the responsive-moves badge. Report (`ReportAgent._world_evolution_block`): bounded lines for red-line crossings and for actors with broken or lapsed commitments, still labelled an elicited model projection, hours mode and legacy runs byte-identical. Tests, README EN/ZH (line-aligned), this entry; commit on an own branch, nothing pushed. Constraints as §1 (deployment checkout untouched, frozen rsync copies, herding guard, no paid runs, `env -u GH_TOKEN`).
- **Branch:** `claude/brave-stonebraker-d2b98b` (worktree `.claude/worktrees/brave-stonebraker-d2b98b`), fast-forwarded from `main` 8bf156d to b8cc994 (this record's four commits) before the work.

### 11.1 Requirements → acceptance checks
| Req | Acceptance check | Evidence |
|---|---|---|
| R11 panel track records | Latest view only (like open commitments), on runs whose API actors carry `track_record`: one line per actor with a resolved, released or open commitment or a resolved move; order broken + lapsed, then broken, resolved, name; "kept k of n (p%) · b broken · l lapsed · r released · o open · moves: …", zero buckets left out; never the reputation score (D3); the actor name red for a breaker, amber for lapses only; empty-state line when nothing is resolved; card absent on older runs | `frontend/tests/worldState.test.mjs` (`trackRecordRows`, `trackRecordSummary`, view model), `worldStatePanel.test.mjs` (EN and ZH markup, classes, no `reputation`) |
| R12 red-line label | `red_line` consequences read "red line crossed" / 「越过红线」, lead their period's list, red tag; a past period outside the API's 40-event window takes them from the history row's `red_lines_crossed` | same modules; screenshot `en-past-2026-04-red-line.jpg` |
| R13 expectation badge | "expected reactions followed r/c" / 「预期反应获跟进 r/c」 beside the responsive-moves badge, tooltip saying a match is not judged (D4); shown whenever `expectations_checked` > 0, also when the move score is null; reacted capped at checked; absent on older runs | same modules |
| R14 report lines | after the alliance shifts and before the closing caveat: 「红线越界（推演仲裁认定，共 N 次[，列最近 4 次]）：」 + the newest 4 `red_line` event descriptions (period label, 220 chars), then 「承诺履约（推演内记录，非现实信誉评估）：」 + up to 6 actors with broken or lapsed commitments, same order as the panel (「兑现 k/n，违约 b，失效 l」) | `backend/tests/test_world_reader_signals.py` |
| R15 byte-identical | the block for the downstream fixture equals the text b8cc994 rendered (`LEGACY_BLOCK`, SHA-256 df3d715f… from both trees); clean or junk track records and blank red-line events add nothing; hours mode has no `world_state.json` → "" as before | same module; `block_head.txt` = `block_new.txt` |
| R16 API | `/world-state` history rows carry `red_lines_crossed` (≤ 4 entries, `actor`/`by`/`red_line` only, 160 chars each) only when the row's `arbiter` summary has crossings; the response of an older run is unchanged | same module |
| R17 contract | `frontend/tests/fixtures/world/world_state.reflexive.json` (the panel tests' payload) equals the API's answer for the reflexivity scenario (`tests/test_world_reflexivity.py`, periods 1–4) run through the real kernel; regenerate with `DRF_WRITE_FIXTURES=1` | same module, `test_the_panel_fixture_is_what_the_api_returns` |
| R18 no regressions | frontend unit + build green; plain suite 0 failures apart from the 19 known errors; guarded runner only the 3 known guard failures | §11.4 |

### 11.2 Decisions
- **D7 (API, small addition):** each history row already stores the period's crossings (`arbiter.red_lines_crossed`), but the API passes no `arbiter` field, so a past period older than the 40-event window lost its red lines. The row now carries `red_lines_crossed`, only when non-empty. Alternative (widen the event window) rejected: it grows every poll.
- **D8 (order):** breakers first by broken + lapsed, the agents' public-brief key, then broken (an actor who broke a commitment ranks ahead of one who only let one lapse), then resolved, then name. The report uses the same order (its third key, kept, ranks identically once the first two tie).
- **D9 (wording):** reliability shows as the percentage after "kept k of n"; "released" counts are listed (not the actor's failure) and explained in the card's tooltip with the other terms. Chinese uses 违约 for broken, as the existing offers line does.
- **D10:** track records describe the latest world only; a past period would need per-round snapshots the API does not keep.
- **D11:** the report block stays Chinese like the rest of the signal pack; each new heading repeats that it is the model's own record (推演仲裁认定 / 推演内记录，非现实信誉评估), and the block keeps its projection label and closing caveat. No shares or probabilities appear in the new lines.

### 11.3 Issues, mistakes, recoveries
- **I1 (deployment folder touched; cache only):** a throwaway Vite preview of the panel, run from this worktree whose `frontend/node_modules` is a symlink to the deployment checkout's, re-optimised its dependency cache into `/Users/rogerlin/Downloads/DeepResearchForecast/frontend/node_modules/.vite/deps` at 23:04:06 +08 (axios and vue; it replaced the cache that was there). No deployment Vite process was running; Vite rebuilds that cache by itself on its next start because the config hash differs. It was not restored (the old content is gone, and deleting the folder would be one more write). **Guardrail:** a Vite dev server started from a worktree with linked `node_modules` MUST set `cacheDir` outside `node_modules` (the preview config was changed to the scratchpad, and the timestamp stayed 23:04:06 afterwards). `npm run build` and `node --test` do not write there.
- **I2:** the desktop app's preview launcher left that Vite process asleep without a port; a background shell job served it and the browser pane opened the URL.
- **I3 (test):** a first panel assertion forgot that the consequence count includes relationship rows; fixed in the test.
- **F5 (found, not changed):** the round headline's "N events" counts only the arbiter's emergent events, so a period whose only event is a red-line crossing reads "0 events" (seen in the preview for 2026-04).

### 11.4 Verification (2026-10-20, +08:00)
- **Before/after:** the new tests on an archive of b8cc994 (`/Users/rogerlin/Downloads/drf-guarded-runs/20261020-reader-signals-evidence/before_*.log`): frontend — `worldState.test.mjs` fails at import (the new helpers do not exist), 2 of the 3 new panel tests fail (the "older runs render no new lines" test passes, as it must); backend — 6 of 7 fail, the byte-identical test passes (it is the guarantee). On this branch all pass.
- **Frontend:** `npm run test:unit` 228 passed / 0 failed (218 + 10 new; the empty-state case was added after the suites below, frontend only); `npm run build` OK.
- **Plain suite** (`/Users/rogerlin/Downloads/drf-guarded-runs/20261020-230100-reader-signals-plain/`, frozen rsync copy without `backend/uploads`, deployment venv): JUnit `tests=8096 errors=19 failures=0 skipped=1352` = 6,725 passed, 1,341 skipped, 11 xfailed, 19 errors (all `test_legacy_official_data.py`), 0 failed; 8,096 = 8,089 (§8) + 7 new. The copy predates only a frontend label change (the Chinese colon after 行动); its `backend/` equals the final one apart from caches.
- **Guarded runner** (`/Users/rogerlin/Downloads/drf-guarded-runs/20261020-231007-reader-signals-guarded/`): the §8 module list plus `test_world_reader_signals.py` (56 modules, `modules.txt`): 1,618 tests, 1,615 passed, 3 failed — the known guard failures (`test_deployment_sidecar_control_flow.py` ×2, `test_official_data_end_to_end.py::test_guarded_mcp_to_promoted_research_and_report_png`); 1,618 = 1,611 (§8) + 7 new. Receipt: no source drift, identity preserved.
- **Gates:** `uvx ruff@0.17.1 check --select F,E9 --ignore F401,F841,F541` on the two changed app modules and `--select F,E9` on the new test module pass; `py_compile` OK; no invisible characters in the changed files; README EN/ZH still 2,007 lines each.
- **Visual check** (throwaway Vite page with the real component and the fixture, no backend; screenshots and SHA-256 sums in the evidence folder): latest view (expectation badge beside the responsive-moves badge, US first in red with "kept 0 of 1 (0%) · 1 broken · moves: 1 succeeded", China "1 released · moves: 1 partly succeeded"), the 2026-04 period ("red line crossed" in red at the head of the list, no track-record card), Chinese, and 375 px width (no horizontal scroll). Light theme only; dark-theme colours reuse the panel's existing red/amber hues.

### 11.5 Remaining
- A live run (owner's approval) shows the lines on real artifacts; nothing here needs one to be correct.
- F5 (headline event count); the candidates in §9. *(F5 fixed 2026-10-21, §11.6.)*

### 11.6 Follow-up 2026-10-21 (+08:00 01:14–01:40): `main` merged in, F5 fixed
- **Why:** `main` had moved to 303e5a8 (confirmed commitment delivery: a due commitment counts as kept only after an explicit delivery attempt that the arbiter confirms; `docs/handoff/forecast-feedback/commitment-integration.md`). Track records feed every new reader line, so the branch had to be checked against it.
- **Merge:** local `main` merged as 2070d30 (`--no-ff`). The app's sync tool was not used: it fetches `origin`, which here is the archived DeepAgentForecast repository (`origin/main` = ec29ab1); this project's `main` exists locally and on `legacy` (`legacy/main` = ac48891, behind local `main`). One conflict, in this file (status line and update log); both sides kept, in time order. On the merged code the reader, reflexivity, track-record, red-line and downstream modules pass (33), and the fixture contract still holds: the stricter delivery rule does not change this scenario (the US withdrawal is a breach either way; China's obligation is released).
- **F5 fix:** `world_update_headline` adds "N red line(s) crossed" before `arbiter=` when the arbiter's apply summary has crossings; other headlines are unchanged byte for byte, and the panel's `headlineSummary` keeps the segment (it cuts after `arbiter=`). The fixture changes in exactly one line (round 1's headline). Before the fix, the new headline test and the fixture contract fail and the other 6 reader tests pass (`before_f5.log` in the evidence folder).
- **Verification (frozen copy `/Users/rogerlin/Downloads/drf-guarded-runs/20261021-011722-reader-signals-merged/`):** frontend 228 passed, build OK; plain suite (JUnit `plain-junit.xml`) 8,191 tests: 6,820 passed, 1,341 skipped, 11 xfailed, 19 errors (all `test_legacy_official_data.py`), 0 failed — 8,191 = 8,096 (§11.4) + 1 new headline test + 94 tests `main` brought in; guarded runner (§11.4's 56 modules plus `test_world_commitment_fulfilment.py`, `modules.txt`) 1,713 tests: 1,710 passed, 3 failed — the same known guard failures; receipt: no source drift, identity preserved; ruff (same selection) and `git diff --check` clean.
