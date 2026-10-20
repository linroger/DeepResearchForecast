# Handoff — reflexive world-state model: realism, reflexivity and robustness (iteration 2026-10-20)

**Last Updated (UTC):** 2026-10-20T14:48Z
**Status:** Complete for this iteration — merged into `main` as acf9b09 on 2026-10-20 at 22:47 +08 and pushed to legacy (8bf156d..main) at 23:02 +08, both on the owner's request; a live run awaits the owner's approval
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
- **Not done in this iteration (candidates):** the World State panel does not yet show track records or the expectation counts (the API returns them); the report's world-evolution block does not list red-line crossings or track records; exogenous shocks from researched risks with base rates (the seed has no such field yet); private negotiations (offers are public today); commitment fulfilment stays mechanical (any non-hold move except a withdrawal honours a due commitment).

## 10) Updates to This File (append-only)
- 2026-10-20T13:30Z: created with the brief, the eight gaps, acceptance checks and the plan.
- 2026-10-20T14:05Z: increments 1–8 done (52a9b37, f599827, 63aa8c7 + docs); findings F1–F4, decisions D1–D6, before/after evidence (§7); suites pending (§8).
- 2026-10-20T14:10Z: final plain and guarded suites recorded (§8); status Complete for this iteration.
- 2026-10-20T14:48Z: merged `claude/agitated-albattani-b57618` (b8cc994) into `main` as acf9b09 (`--no-ff`; `main` had no other commits, so the merged tree a5f59fe… is the tested tree). Pushed to legacy at 23:02 +08 (fast-forward from 8bf156d; secret scan of the 6 commits clean).
