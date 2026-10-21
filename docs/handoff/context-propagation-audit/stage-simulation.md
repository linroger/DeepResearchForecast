# Default OASIS / reflexive simulation context audit

**Status:** Bounded implementation and scenario verification complete; frozen for parent final review. **Scope:** default OASIS and reflexive-world coordinator; world-v1 is owned separately. **Base:** `3cd421a3b89f475d54db66421eaa6a1684c3e86f`, branch `codex/context-propagation-audit`.

## Brief and acceptance

Trace config/role/persona and evidence access through real actor prompts, calendar/period, world observations and expectations, relationships, commitments, outcomes and memories, barriers/restarts, and committed artifacts through feed/summary/report projections. Necessary bounded context repairs are authorized. Preserve exact promise confirmation behavior, feature gates and concurrent work. No Git mutations, primary-checkout writes, runtime uploads, secrets, live services or installations.

| Contract | Acceptance evidence planned |
|---|---|
| Actor identity/access | Real actor prompt capture with distinct actor markers and denied/private controls. |
| Reflexive context | Real coordinator round 1 -> committed world -> actor round 2 prompt; observations, expectations, relationships, commitments and outcome controls. |
| Ordering/restart | Platform barrier and saved-state reload with committed-round and config identity checks. |
| Downstream projection | Real committed world/action artifacts and existing summary/feed/report consumers where within read scope. |
| Verification | Unchanged guarded runner in fresh `/private/tmp` mirror/evidence roots, meaningful red/green receipts, exact source hashes and read ranges. |

## Plan and ledger

1. Read stage contracts, owned source and relevant tests; map producers, artifacts, actual consumers and omission/access controls.
2. Add narrowly targeted production-path probes; preserve behavioral red evidence for confirmed defects.
3. Repair only owned paths, run targeted guarded suites, and record exact hashes, explained guard activity and limits.
4. Hand frozen stage bytes and findings to the parent's final reviewer.

- [x] Confirm branch/base and read parent PLANS.md/handoff.md and offline-verification skill.
- [x] Complete source/consumer map and coverage ledger.
- [x] Verify real prompts, barriers, restart and artifact projections.
- [x] Resolve reproduced defects and preserve red/green evidence.
- [x] Record final source state and remaining limits.

## Findings, decisions and issues

The parent handoff is authoritative for the whole audit. This stage note is the owned continuity record. Existing tests are evidence candidates; helper-only assertions cannot establish the complete simulation contract. Historical world-v1 ordering work is outside this stage and does not establish default OASIS behavior.

## Evidence and read coverage

Coverage ranges and SHA-256 hashes will be recorded after reads; all app imports/tests must use the existing unchanged `backend/scripts/main_offline_pytest.py`, provisioned interpreter `-I -S -B`, fresh source mirror and fresh evidence directory. No app imports have been performed at initialization.

## Remaining work and next-session prompt

Continue the bounded default simulation audit in the assigned owned paths. Re-read this note and the parent handoff. Preserve peer edits and all historical evidence. Resolve only behaviorally demonstrated propagation failures, retain promise-confirmation semantics and feature gates, and hand exact tested hashes to the parent's reviewer.

## Updates

- 2026-10-21: Created before code edits after checking the exact requested branch/base and parent plan.

## Early boundary findings and first behavioral receipts

Three source candidates are now behavioral reproductions. The real round loop accepted the changed configuration, rejected its platform checkpoint, and nevertheless resumed the old world at committed round 3, making no new decisions. A separately older finalization trajectory rolled the newer per-round world's scenario share from `A=0.797478` back to `A=0.680631`. A real coordinator delivery containing an actual public comment was never present in the next actual model prompt.

- Red: `/private/tmp/drf-simulation-audit-red-u6wjli3h/evidence/{completed.json,junit.xml}`; **4 failed**, all requirement assertions after successful model/coordinator execution (not collection/setup errors). Exact red bytes: sibling `source-hashes.json`.
- First repair gate: `/private/tmp/drf-simulation-audit-green1-qwjrv9wa/evidence/{completed.json,junit.xml}`; **136 passed**, including all 4 repro cases, actual loop/barriers, sibling paths, and exact promise-fulfilment controls. Exact bytes: sibling `source-hashes.json`. This is an intermediate source state, not the final acceptance claim.
- Receipts preserve identity and show no tracked-source drift, but show one denied socket creation, four denied process attempts and twenty denied external reads during dependency import. These are attempts, not zero activity; attribution is still under inspection.

The repairs keep fresh/config-invalidated DB and world state together, bind newly saved worlds to config/simulation identity, recover latest shares from the atomic checkpoint and historical projections from round history, and relay bounded, explicitly unverified public action text to the next decision. Public relay selects only public CREATE_POST/CREATE_COMMENT/QUOTE_POST content for exact cast IDs and never serializes arbitrary action metadata.

| Context field | Producing method | Persisted artifact | Actual consumer | Truncation / access / reuse rule | Executed evidence or current limit |
|---|---|---|---|---|---|
| Role/persona and admitted evidence | preparation role compiler; runtime `_world_decision_step._lookup` | platform profiles and role manifest | `elicit_decision` system message -> `LLMClient.chat_json` | Runtime uses the actual actor system text, not config JSON alone; canonical Reddit composition is attested | New reaction probe captures `ROLE_ACCESS_SENTINEL` in the model system turn; canonical pack-to-prompt control pending |
| Calendar and current period | temporal config / coordinator `_run_decisions` | sealed `simulation_config.json`; world period labels | `build_decision_prompt` -> actual decision model user turn; `_inject_period_context` -> OASIS USER memory | Zero-based loop -> one-based world round; deadline and remaining periods explicit | Existing real-loop suite green1; actual dependency memory selection remains a declared separate limit |
| Committed facts, outcomes, relationships and commitments | `run_world_round` / `WorldModel` kernel | world state/history/digest/actions | next `_run_decisions` public/private brief; platform WORLD CLOCK; report projection | Public brief excludes scenario shares; private brief is actor-specific; bounded sections | green1 real round-loop and promise controls; detailed bounds and downstream receipt pending |
| Public organic replies / fallback posts | DB `fetch_new_actions_from_db`; coordinator `deliver` | newly saved world public-discourse projection | `build_decision_prompt(recent_discourse=...)` -> captured model call | Last committed period only; exact actor ID; public content whitelist; 12 rows, 240 chars/text and omission disclosure | red reaction assertion -> green1 prompt capture, denied/private/foreign-name marker controls |
| World/config identity | platform checkpoint/config seal; coordinator state writer | checkpoint `config_hash`; new world `config_hash` and simulation ID | platform resume admission and coordinator loader | Fresh invalidation clears only derived world files once; mismatched saved identity must fail closed | two red cases -> green1; explicit foreign-state rejection pending |
| Latest scenario shares / time | coordinator round step and atomic world writer | world state vs finalization-only trajectory | coordinator reload -> `WorldState` -> subsequent stepping/finalize/report artifacts | Atomic checkpoint owns latest shares/date; stale trajectory cannot override it | red stale-trajectory assertion -> green1; convergence-history exactness is under an additional focused probe |


## Frozen verdict and issue ledger

The final gate is **307 passed, 0 failed, 0 errors, 0 skipped** across 13 selected files, including 21 cases in the new stage test file. This establishes the exercised default-simulation contracts below, not universal context completeness or live forecasting quality. The parent owns final independent review and integration. Production and test scope is now frozen.

Changed production paths are only `backend/scripts/run_parallel_simulation.py` and `backend/app/services/world_model_seed.py`. The four other owned production modules remain unchanged. Added tests are only `backend/tests/test_context_audit_simulation.py`. This document is the only stage-note edit. No Git mutations, primary-checkout changes, live services, live provider calls, uploads, secret reads, installations or new agents were performed.

| Issue | Behavioral red | Bounded repair | Final green / negative control |
|---|---|---|---|
| SIM-CTX-01 Fresh/config-invalidated platform adopted old completed world | R0: both fresh and changed-config-resume made no new decisions | Pass accepted resume status to shared world creation; reset only derived world artifacts for a fresh run | `test_new_config_cannot_consume_old_committed_world` (2 cases), G |
| SIM-CTX-02 Older trajectory rolled back newer checkpoint shares/date | R0: A share regressed 0.797478 -> 0.680631 | Atomic world head owns latest shares/date; recover committed historical rows from round history and committed decision rows from actions | `test_stale_final_trajectory_cannot_roll_back_newer_world_checkpoint`, G |
| SIM-CTX-03 Organic public observations discarded before next decision | R0: delivered public comment absent from actual next model request | Whitelist exact cast-ID public text, bound/disclose omissions, persist last committed public projection, pass existing `recent_discourse` input | `test_public_reactions_reach_next_decision_without_private_payload`; reload/budget control, G |
| SIM-CTX-04 Structured calls bypassed publisher's own private move memory | R2: continuous and restarted next model calls lacked own rationale | Project only that actor's last committed validated decision through existing `decision_memory_note`; reconstruct from committed actor rows on reload; no new public/private payload duplication | `test_own_decision_memory_reaches_the_next_structured_prompt` (2 cases); peer/arbiter negative controls, G |
| SIM-CTX-05 Restart reset convergence evidence | R2: EWMA reset 0.22806 -> 1.0 | Save/restore bounded convergence fields with committed round; conservative legacy reconstruction from known adjacent history | `test_restart_restores_convergence_evidence_not_just_shares`, G |
| SIM-CTX-06 Denied canonical claim bypassed role into world option menu | G2 failure: `qualifiers.actor_knows=false` marker absent from role but present in actual actor user prompt | Seed consumer enforces both direct and nested explicit actor denial | `test_canonical_pack_role_seed_reaches_only_the_correct_actor_prompt`; admitted own-plan and other-actor controls, G |
| SIM-CTX-07 Future-dated research fact admitted at initial cutoff | R3 actual model call showed `FUTURE_FACT_SENTINEL ... as of 2026-09-01` despite dossier cutoff 2026-07-11 | Exclude research fact whose explicit as-of/as_of_date exceeds dossier cutoff, alongside existing period/value-type filters | `test_future_dated_research_fact_cannot_enter_initial_actor_context`, G |
| SIM-CTX-08 Dynamics USER-message object stored with SYSTEM backend role was dropped | R4: actual installed CAMEL selector removed the note | Write dynamics as USER backend memory without replacing original sealed SYSTEM or clearing accumulated memory | `test_dynamics_note_survives_actual_camel_context_selection`, G |
| SIM-CTX-09 Mixed platform resume admission could reset shared world beside old sibling DB | R5: missing/mismatched Reddit checkpoint, Twitter-first and Reddit-first all reached bad behavior; missing-first rebuilt shared world | Check shared resume admission before either platform constructs a model, resets a DB or clears the world; fail closed on mixed valid/invalid checkpoints | `test_mixed_platform_resume_rejected_before_either_start_order_mutates_state` (4 cases), G; all protected artifact SHA-256 values unchanged after rejection |

### Mixed two-platform resume acceptance, precisely

R5 drives the real two-platform loops to produce the original state, checkpoints and SQLite DBs. It then removes or invalidates only the Reddit checkpoint and launches the real first platform with `resume=True, semaphore_platforms=2`, once with Twitter first and once with Reddit first. Before the admission repair, all four expected-rejection assertions failed; missing-first actually rebuilt the shared world while the sibling DB remained from the earlier run. These are behavioral results, not the original reviewer's source-only suspicion.

G exercises those same four cases after repair and proves rejection before any recorded DB/world/history/actions/trajectory/checkpoint hash changes or model dispatch. The tests deliberately stop at rejected admission; they do not claim to run a bad mixed simulation after rejection.

Positive full-fresh control is `test_two_platforms_share_decisions_and_respect_barrier` (both platform loops start fresh, decide once per actor/round and commit in lockstep), also used as the initial producer in the new mixed cases. Positive full-resume control is `test_two_platform_full_resume_keeps_committed_world_and_skips_new_decisions` (both matching checkpoints/DBs preserved, no new decisions, shares and variables unchanged). Both pass in G. A live active coordinator permits its already-admitted sibling to join after the first platform has advanced a checkpoint; this avoids reclassifying a normal ongoing fresh launch as mixed.

## Final field-to-consumer contract table

`G` is the final receipt linked below. Test names refer to the new stage test file unless an existing file is named. These rows describe actual consumption or explicitly mark a source-only/adjacent-owner limit.

| Context field | Producing method | Persisted artifact | Actual consuming prompt / runtime / render method | Truncation / access / reuse rule | Executed case / receipt or explicit limit |
|---|---|---|---|---|---|
| Forecast question/shared situation, run language | prepare's `world_brief`; `_inject_world_brief`, `_sim_output_language` | sealed simulation config and platform role/profile files | `_world_decision_step._lookup` -> `elicit_decision` actual SYSTEM turn; language rule in `build_decision_prompt` USER turn | Shared-brief gate retained; canonical Reddit sealed composition attested; statement script mismatch remains typed rejection | `test_question_language_and_world_clock_reach_actual_decision_calls`; existing wrong-language real-loop test, G |
| Actor ID/persona and own admitted evidence | real actor-context pack + role compiler; seed `_pack_claims` | actor-context/role/profile manifests; config `world_model.actors` | actual SYSTEM role text and actor's `build_option_menu`/decision USER prompt | Exact cast ID at lookup; own plans/goals/red lines; direct or qualifier denial wins; canonical flat compatibility field cannot bypass pack | canonical pack-to-actual-prompt test, G; upstream manifest closure is preparation owner's responsibility |
| Goals, incentives, capabilities and red lines | world seed; `WorldModel.from_seed` | world actor row plus sealed role text | `build_decision_prompt`, `render_private_brief`, `build_option_menu`; arbiter red-lines-at-stake | Seed plans <=4, goals <=3, red lines <=3; menu <=10; private rendered red lines <=3; richer capabilities remain in own role | canonical actual prompt test and existing agent-decision/seed tests, G |
| Research/official observation value, unit, as-of, source | `state_variables_from_research`, `WorldModel.add_variable` | config seed; world's variables/history | `render_public_brief` -> actual decision prompt; `build_arbiter_prompt` -> actual arbiter call | Actual/estimate only; forecast/target excluded; fact period/as-of beyond dossier cutoff excluded; official carrier validates retrieval/date/status; up to 24 seed variables/10 official series | future-dated fact actual prompt negative and current-fact positive; existing official eligibility tests, G; alignment of dossier vs independently supplied timeline cutoff remains upstream |
| Calendar unit, round/date, horizon, remaining periods | temporal config; coordinator `_run_decisions`; `_inject_period_context` | config `round_dates`; world period/labels; action log period fields | actual decision clock and OASIS WorldClock USER memory; period-indexed summary/feed projection | Loop round 0 -> world round 1; exact dates; no calendar runtime `max_rounds` truncation; hours path unchanged | question/language/clock actual prompt test; existing calendar and round-loop tests, G |
| Confirmed scheduled events | `_scheduled_events_due`, `fire_scheduled_events`; `register_scheduled_events` | config event schedule, platform actions, world events/history | current decision CONFIRMED EVENTS; next public brief/clock; deterministic update and arbiter | Same zero-based schedule match; duplicate platform schedule deliveries deduplicated by date/content | existing calendar/real world-loop cases, G; event-post publication failure does not invalidate the predeclared research schedule |
| Public organic posts, comments and quotes | real DB trace projection -> coordinator `deliver` -> `_public_discourse` | platform actions; bounded world `public_discourse` and committed-round stamp | next `build_decision_prompt(recent_discourse=...)` actual USER request | Public content keys only; exact cast IDs supply display names; no private messages, raw metadata or share dictionary; <=12 rows x 240 chars plus omission markers; last committed period only | actual next-prompt and restart/budget cases, G; observations explicitly unverified, never mechanical numeric changes |
| Actor's own private rationale/last move memory | parsed `AgentDecision`; existing `decision_memory_note`; coordinator committed-row map | existing private audit `world_actions.jsonl`; organic in-process USER memory | `_previous_decision_note` in that actor's next structured USER prompt | Only matching actor ID/name, accepted config and committed round; <=1800 chars plus disclosure; never copied to world brief, arbiter or report block | own-memory continuous/restart cases and peer/arbiter/public-state negative controls, G; complete OASIS conversational memory is still process-local |
| Expectations and expected-vs-observed responses | parser expected reactions -> `register_decisions` / `_record_expectations` -> `expectation_checks` | actor expectations and world events in world checkpoint | actor's actual `render_private_brief` inside decision call; arbiter expectations-in-play; responsiveness counters | Up to 4 new/8 stored expectations, 160 chars; compare expectation in r-1 with observed action in r, visible in next decision; no peer private-brief sharing | `test_expectation_and_response_comparison_reaches_only_its_actor_prompt`, G; existing reflexivity test checks mechanics |
| Relationship/alliance changes, offers, consent | parsed move -> `register_decisions`, `resolve_interaction`, validated arbiter update | world relationships/interactions/events/history | next private/public briefs and option menus; arbiter offers/agreements block; feed/summary/report diagnostics | Cast-restricted targets; explicit recipient response required; materially changed acceptance remains counter-offer; bounded displayed neighbors/offers | real two-platform/world loop plus existing interaction and promise scenarios, G; no new consent/realism policy |
| Pending commitments and exact promise confirmation | `register_decisions`, `delivery_commitment`, `delivery_resolution_target`, `apply_arbiter_update` | actor commitments, fulfillment attempt/evidence, world events/history | due `fulfill:<exact id>` option; arbiter specific-attempt prompt; next actor outcome/private note | Exact promise ID, owner/counterparty, current action round and concrete arbiter success rationale required; announcements/partial/other actions do not fulfill | complete selected `test_world_commitment_fulfilment.py` suite plus real-loop controls, G; protected production methods unchanged |
| Action outcomes, changed facts, track records, delayed effects | deterministic update -> `run_arbiter` -> validated kernel -> `commit_round` | world state/history/digest and variable/event histories | actual next decision public/private briefs; OASIS clock; arbiter variable path/track record; report diagnostic render | Typed failed/invalid/language mismatch; unknown cast/variables rejected; arbiter changes clamped unless matching own announcement; seeded due effects; histories capped | existing real-loop arbiter-failure/reflexivity/model/update tests, G; no live model realism claim |
| Dynamics and accumulated memory | real `AgentDynamicsTracker.state_line`; `_inject_agent_dynamics` | process-local CAMEL memory; separate dynamics summary | actual installed `ChatHistoryMemory.get_context` / `ScoreBasedContextCreator.create_context` | USER backend role preserves original SYSTEM and prior conversation; feature-off remains no-op | real dependency selection test with deterministic character costing only, G; no actual provider tokenizer/window-quality claim |
| Cross-platform causal barrier / single shared decision | `begin_round`, shared decision future, `deliver`, `_try_commit`, `_commit_round` | world/history/actions plus both platform update rows | next platform round begins only after previous shared commit; one decision set reused across platforms | Per-round event barrier/watermarks; timeout/stalled-platform degradation retained; platform event deduplication | existing two-platform order/uniqueness test, G; no claim of scheduler-invariant ordering for every simultaneous action combination |
| Fresh vs resume / simulation-config identity | direct config seal; platform checkpoint; `_validate_shared_world_resume`; coordinator loader | config manifest; per-platform checkpoint; new world/actions/history/trajectory config fingerprints | actual platform launch before model/DB mutation; `_get_world_coordinator` and constructor reload | New saved worlds reject foreign simulation/config; mixed two-platform checkpoint admission rejects both start orders; fresh cleanup limited to derived world filenames | fresh/changed-config, foreign-state, mixed admission, full-fresh and full-resume controls, G; old artifacts without fingerprints retain legacy compatibility, not newly invented proof |
| Latest scenario shares, round validity, convergence and time | scenario commitments + outcome power + applied world pressure -> `WorldState.step`; atomic world writer | per-round world/history/digest; final trajectory/decisions; convergence checkpoint | actual coordinator reload -> next `WorldState` stepping/outcome and final artifacts | Shares never rendered by public/private briefs; projection epistemic label retained; latest atomic world head beats stale trajectory; missing historical rounds disclosed and not valid transitions | stale-final-trajectory and exact convergence restore cases; existing worldstate/calendar/path tests, G; no scenario-share polling/herding feature added |
| Feed/update headings and run summary | coordinator world headline + `PlatformActionLogger.log_world_update`; `_write_world_state` | both actions logs, world state and `run_summary.json` | real `SimulationRunner._read_action_log` -> run-state options; real `write_run_summary`; API world-state projection | Newest committed round selected; bounded headline; selected-period API rows bounded; absent world omitted | actual committed-artifact summary test plus existing action-log/API consumer tests, G; browser selected-period interaction remains outside this stage |
| Summary/world history -> report diagnostic | actual committed world + history/trajectory | same simulation artifacts; report signal pack/viz inputs | real `ReportAgent._world_evolution_block`; source trace `_build_signal_pack` -> chapter grounding/prompt consumers | Explicit elicited model projection; bounded variables/moves/red lines; diagnostic-only/no_update gates retained; private rationale/share probability absent from evolution block | actual coordinator -> committed artifacts -> real report render and existing downstream tests, G; final chapter/model/publication consumption belongs to report owner |
| World-model off / hours / legacy in-band fallback | `_world_model_enabled`, calendar gate, `_InbandWorldEvolution` | legacy trajectory/digest only when gated active | ordinary OASIS actions and legacy `decision_channel.elicit_round` branch | Existing feature gates unchanged; legacy in-band restart rebuilds seed and covers only resumed slice, explicitly documented in source | existing world-off/hours/calendar cases, G; those legacy loop tests substitute the legacy elicitation call, so do not prove its complete live prompt contract |

## Evidence receipts, exact command and guard interpretation

Every invocation used the existing interpreter with `-I -S -B`, the unchanged `backend/scripts/main_offline_pytest.py`, a fresh private source mirror and a fresh evidence directory. Mirrors contain source and test fixtures, exclude `.git`, `.venv`, uploads/logs/data, credentials and DBs, and final mirrors include the real `deerflow_bridge` package needed by official-data consumers. External model/platform responses are scripted. Real producer/consumer code, parsers, coordinator, kernel, atomic writers, SQLite trace projection and tested render/runtime consumers remain real.

| Receipt | Root under `/private/tmp/` | Result and meaning |
|---|---|---|
| R0 | `drf-simulation-audit-red-u6wjli3h` | 4 behavioral failures: fresh/changed config, stale trajectory, missing public observation |
| Intermediate first repair | `drf-simulation-audit-green1-qwjrv9wa` | 136 passed; historical intermediate bytes only |
| R2 | `drf-simulation-audit-red2-awrq14f9` | 3 behavioral failures, 4 deliberately unselected cases: own memory (2), convergence |
| G2 diagnostic expansion | `drf-simulation-audit-green2-48d7uf09` | 231 passed / 2 failed: qualifier-denial behavioral red, and incomplete-mirror official-data fixture failure |
| R3 | `drf-simulation-audit-red3-iz24xnsp` | 1 passed / 2 failed / 11 unselected: future-fact behavioral red; dynamics fixture initially called nonexistent BaseMessage factory (not behavioral red) |
| R4 | `drf-simulation-audit-red4-rcoipf8t` | 1 behavioral failure / 13 unselected: corrected fixture proves installed CAMEL drops SYSTEM dynamics record |
| R5 | `drf-simulation-audit-red5-k5q_787t` | 4 mixed-admission behavioral failures / 4 passed / 11 unselected; both orders and missing/mismatched checkpoint |
| Narrowing check | `drf-simulation-audit-green3-8ncfgsqt` | 304 passed / 1 failed: an unneeded timeline-cutoff override changed a legacy v3 fixture; removed that broader policy, retained only reproduced explicit research fact cutoff fix |
| Pre-freeze gate | `drf-simulation-audit-green4-hhfsfsca` | 305 passed; before the final two actual-consumer coverage cases |
| **G final** | **`drf-simulation-audit-final-x6et87zy`** | **307 passed / 0 failed / 0 errors / 0 skipped**; frozen production/test bytes |

Each root has `evidence/completed.json` and `evidence/junit.xml`; source-state manifests are sibling `source-hashes.json`. R0 and G carry full owned-source hashes; later narrow red phases carry exact changed production/test/runner hashes. Raw receipts are preserved. Diagnostic setup failures are not relabeled as propagation bugs.

The final invocation, from the final root's `source` directory, was:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B \
  backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-simulation-audit-final-x6et87zy/evidence -q \
  backend/tests/test_context_audit_simulation.py \
  backend/tests/test_world_model_loop.py backend/tests/test_world_model_downstream.py \
  backend/tests/test_world_model_seed.py backend/tests/test_agent_decision.py \
  backend/tests/test_world_reflexivity.py backend/tests/test_world_paths.py \
  backend/tests/test_world_commitment_fulfilment.py backend/tests/test_calendar_round_loop.py \
  backend/tests/test_world_model.py backend/tests/test_world_update.py \
  backend/tests/test_worldstate.py backend/tests/test_worldstate_calendar.py
```

G records `status=completed`, `exit_code=0`, `shutdown_complete=true`, preserved identity, no tracked-source drift and no allowed spawned children. Its denied operations are **one socket construction, five process attempts, twenty external reads**. These are nonzero attempts, not successful external effects or zero activity. No guard was weakened and no credential/saved-data/external-write attempt is recorded.

Supporting attribution trace: `/private/tmp/drf-simulation-audit-guard-attribution-_yiws27q/evidence/denial-attribution.txt`. The runner remained unchanged; only a temporary mirror's test conftest added call-stack observation. This diagnostic is not the final acceptance run. CAMEL `get_system_information` invokes `platform.processor` (`uname`) and `platform.platform` -> `architecture` -> `_syscmd_file` (`file`, recorded as unregistered executable). Matplotlib font manager attempts `fc-list`, `system_profiler`, and font-directory reads. The two non-font denied read paths are `/proc/self/maps` and the identity-local `.igraphrc`; both remain blocked. A fifth process attempt in G has no program detail in the guard event; one socket-construction caller has not yet been precisely attributed. They are disclosed as attribution limits, not declared expected or successful. Supplemental attribution may be appended without changing frozen production/test bytes.

## Read coverage and source identity

The coverage is targeted semantic review, not a claim to have read every line in the repository. Numeric spans and method hashes below correspond to the frozen final mirror. `read-coverage.json` beside its `source-hashes.json` contains each selected span's SHA-256; whole-file hashes identify exact bytes without implying complete line coverage. Non-owned source referenced for adjacent boundaries is read-only, and its final tested hash is also in the manifest for parent reconciliation.

| Owned source | Targeted reviewed ranges in final snapshot | Whole-file SHA-256 |
|---|---|---|
| `backend/scripts/run_parallel_simulation.py` | 1280-1292, 1295-1355, 1405-1494, 1911-1936, 1951-2035, 2590-2603, 4020-4112, 4114-4133, 4135-4165, 4269-4298, 4300-4327, 4329-4395, 4397-4425, 4509-4532, 4534-4712, 4792-4856, 4858-4876, 4879-4912, 4940-4976, 4979-5037, 5066-5075, 5104-5137, 5140-5152, 5155-5183 | `c668acf811ded2738c5483adb4b904dcf7b055b3bbaa0d9da631a440e8348c82` |
| `backend/app/services/agent_decision.py` | 369-479, 482-509, 532-587, 707-820, 823-849, 852-870 | `dc1920bed119ba23b969ba9ff6209079dbb1afba8cddcaa047886a3b95146c7e` |
| `backend/app/services/world_model.py` | 943-1017, 1262-1426, 1629-1650, 1736-1886, 2078-2166, 2168-2245, 2248-2273, 2275-2314, 2339-2351 | `0b0a2e5534137bf2a06a86ac2d719ae46caac02cc0c1d8fff91b28af950f1080` |
| `backend/app/services/world_update.py` | 69-99, 106-236, 540-570, 577-619, 688-737 | `2f7dfe133b3f08280bbac40a0cb751d28b10893fba2704c1c4c853471ceed37a` |
| `backend/app/services/worldstate.py` | 81-119, 145-165, 205-278, 280-299, 301-319, 329-350 | `c4588cc83571aa784ee495ef650a6ed20158b8a8da7e0ee44f3617c753e91c8e` |
| `backend/app/services/world_model_seed.py` | 133-158, 253-269, 272-283, 328-454, 1037-1215 | `b9988ee035fe33a0c8597e1324059e9a96daa08105a21f6039e767f6b0ee34ea` |

| Other frozen evidence bytes | SHA-256 |
|---|---|
| `backend/scripts/main_offline_pytest.py` | `8c8bb8f6c0e4e5decee8f167603a4eb47711ec562e028d19f9d3d6bee1741815` |
| `backend/tests/test_context_audit_simulation.py` | `bb9e1092683b4d7a3f733ea97465d413c8cf0edb0f7b88e05b7378b3e4455005` |

Additional inspected boundaries include canonical Reddit runtime composition and attestation, both platform startup/round loops, period/event propagation, legacy in-band source docstring and wiring, `actor_context`/role compiler access checks, `SimulationRunner` action-log and summary consumers, `PlatformActionLogger.log_world_update`, and `ReportAgent` world diagnostic/signal-pack assembly. Those cross-owner files are identified in the final hash manifest, not claimed as wholly reviewed here. The calendar/risk parsing middle of world seed and all possible option/catalog combinations were not given exhaustive line-by-line review.

## Causal authority, limits and parent handoff

- Research/official seed facts carry their source/as-of/units. Deterministic consequences are produced by the real kernel. The arbiter's validated/clamped changes remain simulated consequences; an actor's own announced setting is action-owned only when the kernel matches its actor/current move/number. Public discourse remains unverified observation and cannot itself fulfill a promise or set a variable.
- The scenario distribution remains an elicited model projection, separated from actor-facing public/private briefs. Private rationale is retained only in its existing actor audit rows and that actor's structured prompt; it does not enter the shared world state, report evolution block, or arbiter prompt in the exercised controls.
- Promise mechanics and world-v1 implementation were not edited. The existing exact ID/owner/counterparty/current-round/rationale confirmation controls all ran in G. World-v1 causal-ordering/history is a separate owner's responsibility.
- Existing `render_public_brief` (3200 chars), `render_private_brief` (1300 chars), digest (1100 chars), histories (48 per variable/relationship), events (400) and expectation bounds are intentional context selection. Existing `_bound_lines` truncates at a line boundary without a general omission marker; the new public-observation/private-move projections explicitly disclose omissions. No claim is made that every persisted datum fits every prompt or that narrow helper bounds establish sufficient semantics under all budgets.
- New fingerprinted worlds reject explicit foreign simulation/config state. Old saved worlds and old checkpoints without fingerprints retain existing compatibility; this is a declared legacy proof limit. Corrupt/missing saved-world fallback and multi-artifact I/O crash windows were not exhaustively fault-injected here. The preserved timeout/stalled-platform degradation and async decision completion order are not proven invariant for every possible simultaneous-action ordering.
- The real CAMEL memory test substitutes deterministic character counting only. It verifies the installed selection algorithm and retained original role/prior memory; it does not validate a provider tokenizer, full live OASIS action prompt, all token-window settings, or lossless restoration of the entire OASIS conversation (already documented as process-local/reset on restart).
- Parent must reconcile preparation's admitted actor/config manifests and cutoff identity, lifecycle resume/fork/ensemble constructors, report chapter/model/publication consumers, API/UI selected-period behavior, and global source freeze. This stage verifies specific committed artifacts through actual summary/report render consumers; it does not certify live providers, browser behavior, forecast calibration, report publication or the complete pipeline.
- Self-review and scoped `git diff --check` passed. Final source/test hashes were checked against the active owned paths after G. Parent's final reviewer remains the independent acceptance authority; no new reviewer agent was spawned. Delivery/commit/push is intentionally left to the parent under the explicit no-Git-mutation boundary.

**Next-session / parent prompt:** Re-read parent PLANS.md/handoff.md and this frozen stage note. Review only these owned changes, using final manifest and G receipts. Reconcile the field table with prepare/actor and report/lifecycle owners. Preserve all raw red receipts and peers. Run the parent's combined gate against its final frozen bytes before global completion; do not treat this stage's bounded green as universal correctness.

## Final updates

- 2026-10-21T11:46:42.446203+00:00: Recorded nine behaviorally established defects and bounded repairs, both-order mixed admission rejection with full-fresh/full-resume controls, final 307-case receipt, precise tested hashes, method coverage, guard-attempt attribution/limits, and parent review handoff. Production/test scope frozen.


### Final denied-attempt attribution detail

| G denied event | Count | Attribution established / exact limit |
|---|---:|---|
| `network:socket.__new__` | 1 | Blocked construction, no connect/send success recorded. Exact caller remains unattributed; neither a temporary Python socket wrapper nor Python call tracing captured it. It is not relabeled zero attempts or expected provider activity. |
| `process:subprocess.Popen`, `program=uname` | 1 | CAMEL prompt import -> `get_system_information` -> `platform.processor` -> `_Processor.from_subprocess`. Exact stack in attribution trace. |
| `process:subprocess.Popen`, `program=unregistered-executable` | 1 | CAMEL prompt import -> `platform.platform` -> `architecture` -> `_syscmd_file` attempting `file`. Exact stack in attribution trace; the guard deliberately omits arbitrary argv. |
| `process:subprocess.Popen`, `program=fc-list` | 1 | Matplotlib import -> `FontManager` -> `findSystemFonts` -> `_get_fontconfig_fonts`. Exact stack in attribution trace. |
| `process:subprocess.Popen`, `program=system_profiler` | 1 | Matplotlib import -> `FontManager` -> `_get_macos_fonts`. Exact stack in attribution trace. |
| `process:subprocess.Popen`, no program detail | 1 | G's append-only event records a generic denied launch. No exact caller attribution was obtained; do not infer a successful child or classify it as one of the above four. |
| `external_read`, font-discovery category | 18 | Matplotlib system font discovery paths; all denied by unchanged boundary. |
| `external_read`, `/proc/self/maps` | 1 | Exact denied path known; caller not precisely attributed by the diagnostic. |
| `external_read`, identity-local `.igraphrc` | 1 | Exact denied initialization/config path known; file was not read. Filename is consistent with igraph startup, but that caller identification is an inference. |

The final-source diagnostic reran the same 307 cases with only temporary test-conftest call tracing: `/private/tmp/drf-simulation-audit-final-attribution-i3miro20/evidence/{completed.json,junit.xml,denial-attribution.txt}`; **307 passed**, with production source/runner unchanged. This did not expand the behavioral scope or replace G. Additional socket-wrapper diagnostic is `/private/tmp/drf-simulation-audit-socket-attribution-j6wp9fby/evidence/`; it did not identify the socket caller. Attribution limits remain explicit. The authoritative final acceptance receipt and exact production/test hashes remain G.

- 2026-10-21T11:50:12.637346+00:00: Completed denied-attempt accounting and supporting diagnostic attribution; no production/test edits after frozen G. Parent review retains the explicit unmatched socket/generic-process/native-read caller limitations.

## 2026-10-22 bounded joint-fixture follow-up (in progress)

The coordinator's candidate3 joint receipt `/private/tmp/drf-context-joint-accepted-npw99tgw/evidence` has one assertion failure, 4532 passes and 21 explicitly deselected cases on the same frozen production bytes. The sole failure is the fixture's unconditional `Actor1 holds position` assertion. The expected-reaction marker did reach Actor0's actual round-3 prompt.

Read-only artifact inspection confirms `world_actions.jsonl` contains actors 0/2/3 in rounds 1 and 2; Actor1 first appears in round 3. No Actor1 round-2 event exists. The native `expectation_checks` contract therefore correctly reports `made no recorded move`. The scripted `_WorldLLM` returns `hold_position` whenever an actor other than Actor0 is actually asked, so the missing record is not an unexpected model choice.

Source diagnosis: `_calendar_config` makes Actor0 principal and Actor1 sampled, with three sampled candidates at activity 1 and a two-actor sampled cap. `get_active_agents_for_round` still samples only two of those three, and `_world_decision_step` restricts the deciding roster to actual active IDs. `_patch_world` does not reset the process-local sampling RNG. The fixture incorrectly assumed activation and a hold record were guaranteed. No runtime defect or production edit is justified by this evidence.

Authorized follow-up is limited to this one expectation fixture and this stage note. The fixture will mark only Actor1 principal through real config, assert its real round-2 `world_actions` row is a hold, then retain the existing exact owner-feedback and peer-visibility assertions. A bounded seed comparison and the existing 307-case affected gate will be recorded before refreezing. No Git, guard, provider, primary-checkout or shared-helper changes are authorized.


### 2026-10-22 fixture-only follow-up completed and refrozen

**Classification:** the candidate3 sole joint failure is a stochastic fixture precondition, not a production context-propagation bug. Its unchanged actual world correctly distinguished an unrecorded action from an explicit hold. No production change was made or is proposed for this failure.

The repair changes only `test_expectation_and_response_comparison_reaches_only_its_actor_prompt` in `backend/tests/test_context_audit_simulation.py`. It marks **only Actor1** `cadence="principal"` in that case's real configuration; Actor0 was already principal. Before reading Actor0's round-3 prompt, it asserts exactly one real Actor1 round-2 `world_actions.jsonl` record exists and its option is `hold_position`. The three original assertions are all preserved exactly in the AST: the owner receives its expected-reaction marker, the owner sees the exact `Actor1 holds position` comparison, and other actors never receive that private expectation. The added two assertions make the intended hold premise observable. No global helper, scheduler, model-default, guard or activation logic changed.

| Sampling seed | Original sampled fixture | Native prior-period comparison | Owner marker / peer privacy | Fixed principal fixture |
|---|---|---|---|---|
| 0 | passed; Actor1 recorded in round 2 | `Actor1 holds position` | both controls pass | passes; round-2 hold recorded |
| 1 | original hold assertion fails; Actor1 not sampled in round 2 | `made no recorded move` | both controls pass | passes; round-2 hold recorded |
| 2 | passed; Actor1 recorded in round 2 | `Actor1 holds position` | both controls pass | passes; round-2 hold recorded |
| 3 | original hold assertion fails; Actor1 not sampled in round 2 | `made no recorded move` | both controls pass | passes; round-2 hold recorded |
| 7 | passed; Actor1 recorded in round 2 | `Actor1 holds position` | both controls pass | passes; round-2 hold recorded |
| 42 | original hold assertion fails; Actor1 not sampled in round 2 | `made no recorded move` | both controls pass | passes; round-2 hold recorded |

The seed diagnostic uses real `_build_sampling_rng`, the real activation sampler, loop/coordinator/parser/kernel/artifact writer, and actual scripted-model prompt captures. Only a temporary diagnostic test selects `SIM_SEED` and reinstantiates the process-local RNG for each bounded trial; none of that seed-control code is added to repository fixtures. Each trial calls the exact expectation fixture, inspects the committed native world/actions, verifies native `expectation_checks(0, 2)`, and verifies actual owner/peer prompts. The diagnostic intentionally catches the original assertion to classify active and inactive trials, then requires the native result to match the actual action record; its six passing diagnostic tests do **not** mean the original fixture passed all six seeds. Seeds 1, 3 and 42 faithfully reproduce the original assertion failure while proving the runtime's inactive-actor comparison and owner privacy are correct. This explains why identical production/test bytes passed earlier joint runs but failed candidate3.

| Receipt | Result | Meaning |
|---|---|---|
| `/private/tmp/drf-context-joint-accepted-npw99tgw/evidence/{completed.json,junit.xml}` | historical candidate3: 1 failure / 4532 passes / 21 explicit deselections | Original single joint-fixture red retained unchanged. `pytest-tmp/test_expectation_and_response_0/world_actions.jsonl` has Actor1 absent in rounds 1/2 and present in round 3. |
| `/private/tmp/drf-simulation-expectation-seeds-before-5vful169/evidence/{completed.json,junit.xml}` | 6 diagnostic controls passed | `seed-0.json`, `seed-1.json`, `seed-2.json`, `seed-3.json`, `seed-7.json`, `seed-42.json` preserve the three original fixture failures and three active positive controls. |
| `/private/tmp/drf-simulation-expectation-seeds-after-fideegu5/evidence/{completed.json,junit.xml}` | 6 passed | Same six seed trials, with all original owner-feedback/privacy assertions and new committed-hold premise passing after only the local case-config repair. |
| `/private/tmp/drf-simulation-expectation-affected-w5vqziz_/evidence/{completed.json,junit.xml}` | **307 passed / 0 failed / 0 errors / 0 skipped** | Fresh affected gate, exactly the existing 13-file simulation/world/promise selection; no production changes. |

Each new root has `source-hashes.json`. The after-seed and affected roots additionally contain `candidate3-delta.json`: comparison of every copied existing Python file to candidate3 identifies only `backend/tests/test_context_audit_simulation.py` as changed. The final affected mirror has no diagnostic test file; the temporary seed-probe file exists only in its separate scratch mirrors. All source paths required by the affected gate use candidate3 bytes except the approved fixture delta.

The fixture SHA-256 changes from historical `bb9e1092683b4d7a3f733ea97465d413c8cf0edb0f7b88e05b7378b3e4455005` to **`bece688b84263501877e2d90e916136b53b8cd25d7272e7ec563accd3f221bc7`**. The unchanged runner remains `8c8bb8f6c0e4e5decee8f167603a4eb47711ec562e028d19f9d3d6bee1741815`; simulation production remains the hashes in the original frozen table above. The earlier 307-case production gate is retained as historical evidence for its original fixture bytes; the new affected receipt binds the fixed fixture, while parent candidate4 must establish the final joint result.

All three new guarded runs completed normally with `exit_code=0`, `shutdown_complete=true`, `identity_preserved=true` and `source_drift=[]`. Both seed diagnostics record one blocked socket construction, four blocked process attempts and twenty blocked external reads; the 307 affected gate records one blocked socket construction, five blocked process attempts and twenty blocked external reads. Existing attribution/limits above still apply. No credential, saved-data or external-write denial is recorded; blocked attempts are not relabeled zero attempts. All runs used the unchanged guarded runner, existing interpreter with `-I -S -B`, and fresh source/evidence roots.

Setup note: the first broad scratch-source copy failed on a dangling unrelated `.npmrc` path in a nested third-party tree (`/private/tmp/drf-simulation-expectation-seeds-before-fxigf5_h`). It performed no app imports or tests and produced no behavioral receipt. The actual diagnostic/affected mirrors copy only the required backend and real `deerflow_bridge` source/fixtures, exclude runtime/secret/cache/package directories, and never traverse that unrelated package configuration. No source or package repair was attempted.

**Current completion state:** fixture-only delta and stage note complete and frozen. The exact original hold/owner-feedback/private-visibility assertions remain enforced. No production/Git/primary/provider/installation/guard changes or new broad review. Parent should incorporate this one fixture delta into candidate4's source manifest and perform the final joint replay; candidate3's historical failure is not silently relabeled green.

- 2026-10-21T17:18:44.636995+00:00: Closed bounded stochastic expectation-fixture diagnosis with six before/after seed controls, controlled inactive comparisons, unchanged exact feedback/privacy assertions, 307-case affected green, and new fixture hash. Refrozen for parent candidate4; production untouched.
