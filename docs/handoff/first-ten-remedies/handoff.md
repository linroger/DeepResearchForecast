# First ten remedies handoff

**Last Updated (UTC):** 2026-10-28T05:27:14.533632+00:00
**Status:** Complete — implementation, offline acceptance and branch delivery
**Current Focus:** Preserve the verified delivery; use the recorded next-session prompt for a separately authorized follow-up.

## 1) Request & Context
The user supplied the 2026-10-27 design and first-ten-remedies plan and requested architecture familiarization and an orchestrated implementation team. This supersedes the generic workflow-packaging request. The deployment checkout has unrelated staged, unstaged and untracked work. The earlier chat Coordinate DRF architecture changes delivered code91cf47e9 and closing docs5b9b9215 this morning. This session starts from that exact clean commit, preserving the original worktree and deployment.

## 2) Requirements → Acceptance Checks
| Requirement | Scenario check | Evidence |
|---|---|---|
| All ten slices have an accurate disposition | Compare requested producer, contract, consumer and rollback to source/tests | acceptance-matrix.md and owner reports |
| No duplicate implementation | Verify delivery manifest and exact source | baseline.json and source-hash verification |
| Concrete implementation defects are fixed | Reproduce through actual runtime; regression and independent review | guarded receipts and diffs |
| Preserve authority and primary work | RW-11, typed publication, input binding and baseline hashes | focused acceptance and preservation receipt |
| Keep live evidence distinct | Record source-only, offline, live and prospective gates separately | issues.md and verification.json |

## 3) Plan & Decomposition
The existing implementation is the dependency baseline. Three independent specialists map reporting, research/mechanisms, and feedback inputs while the coordinator checks existing evidence and actual lifecycle. Concrete defects receive disjoint ownership and regression checks. See PLANS.md.

## 4) To-Do & Progress Ledger
- [x] Read supplied design and actual root handoff; inspect primary dirt and branches.
- [x] Locate delivered target-first implementation and create an isolated branch.
- [x] Map requested slices to implementation and evidence using specialists; acceptance-matrix.md.
- [x] Repair reproduced gaps and independently review changed bytes; all owner/independent reports close findings.
- [x] Freeze, verify, update evidence, commit and push scoped changes; code722866a5 is verified on the active remote.

## 5) Findings, Decisions, Assumptions
PipelineOrchestrator and pipeline_state.json own current lifecycle; drf2 is not the active route. Target-first-v1 is explicitly admitted and uses a typed case, deterministic graph/mechanisms, frozen research posterior and shadow estimator lanes. Existing acceptance reports5199 backend cases and329 frontend cases; these remain historical until file hashes and focused current checks confirm them. The request's deployment/main base is older than the delivered dependency branch, so this branch starts from5b9b9215. No primary dirt is copied.

## 6) Issues, Mistakes, Recoveries
The reproduced implementation findings and their closures are recorded in issues.md and the owner reviews. Original red receipts are retained, including invalid fixture setup and the pre-existing scheduling assumption found by the broad gate. Existing empirical follow-up is issue10; it was verified open and not duplicated.

## 7) Scenario-Focused Resolution Tests
Acceptance follows the real research producer through persisted case, mechanisms, report and public APIs, with rollback and tamper controls. Each reproduced finding has a failing baseline and passing corrected scenario. See acceptance.json and verification.json.

## 8) Verification Summary
The final frozen gate passed **5,306 tests, zero failures/errors and two known vendor-snapshot skips** across 159 modules. All 547 source/test hashes were unchanged. Independent review closed the reproduced findings; Ruff F/E9, diff checks and environment documentation pass. The 95 unchanged frontend input hashes match the earlier 329-test/build evidence; no fresh frontend build is claimed.

## 9) Remaining Work & Next Steps
Implementation, controlled offline acceptance and scoped branch delivery are complete. There are no open implementation or review findings in this reconciliation. Provider transport, paid model validation, monitor activation, original-specimen measurements and prospective calibration remain separate gates under issue10.

Next-session prompt:
```text
Read docs/handoff/first-ten-remedies/handoff.md, acceptance-matrix.md, verification.json and delivery.json, then docs/handoff/target-first-forecast/architecture.md. Verify the branch and tested hashes before editing. Preserve the dirty deployment checkout and saved runs. Choose a single bounded follow-up. For live acceptance, start from issue10 and obtain the separately required probe, per-run budget or scheduler authorization. Keep target-first opt-in and simulation/structural weights zero until prospective evidence permits promotion.
```

## 10) Updates to This File
- 2026-10-28T05:27:14.533632+00:00: Created before source edits; chose reuse of existing delivery after verifying source history and continuity records.

- 2026-10-28: Fresh baseline producer/lifecycle/API/RW-11 gate passed207 cases in65.06s. Identified a public-consumer coverage gap: the HTTP resume/continue/fork routes always preflight the research installation and credentials even when typed research is sealed. The direct pipeline retry checks do not exercise this route. Coordinator will reproduce through Flask and implement stage-aware readiness within api/research.py and target_pipeline.py if confirmed.

- 2026-10-28: HTTP reuse regression confirmed3/3 failures before the repair; the same3 scenarios now pass. Added read-only receipt-aware target readiness so saved research skips research credentials, new LLM paths still require their provider, and legacy readiness is unchanged. Additional tamper, incomplete-research and LLM reuse controls are under test; independent review requested.

- 2026-10-28: The first expanded-test command named nonexistent test_pipeline.py/test_research_api.py and stopped before collection. This is a command-selection error, not a test result. Replaced guessed names with repository-discovered modules; retained its failed-start directory.

- 2026-10-28: Independent source/consumer audits found RPT1 stale prior-update ledgers after critique, RPT2 missing rendered estimator table, G3-EXACT incorrect exact-market admission, G1-STATUS lost collector states, G1-PROBE different transport from the failing collector, MR1 unconsumed dimensional/identity checks, and MR2 scenario predicates allowed on unrelated nodes. Assigned disjoint fixes: reporting owner forecast_extractor and dedicated tests; feedback owner health/probe/collector and dedicated tests; mechanisms owner schema/model/runtime and dedicated tests; coordinator owns API reuse and estimator render integration. Previous blanket implementation-complete claims are superseded by this evidence until these findings close.

- 2026-10-28: Estimator rendering had2 actual consumer failures (default bridge and full target publication) while3 rendering controls passed. Added one deterministic renderer consumed inside both diagnostic fences; the final target bridge audit re-reads the stored forecast and checks identical table bytes. Rendering does not mutate forecast probabilities, and tournament-off/old reports retain their previous projection. Focused publication and replay checks are running.

- 2026-10-28: Actual pipeline/report model-admission reproductions showed5 failures before the consumer fix: mismatched units/currency, contradictory seed identity, report acceptance of an unvalidated bad model and absent gap disclosure. One first-run seed fixture500 exceeded its schema bounds; corrected to in-range290 and repeated all5 behavioral failures. Wired the pure admission check before pipeline binding and direct report creation; new paths seal known-contradictions/v1 diagnostics, which the report recomputes and renders. Unsupported/unmeasured checks remain gaps, and valid legacy record shapes remain available.

- 2026-10-28: Independent review reproduced an interrupted seed-fork resume reaching fresh-research preflight despite retained parent receipts. Added2HTTP regressions, both red initially. The preflight now verifies the parent snapshot and child case binding read-only before bypassing completed research prerequisites; copying remains the runner responsibility. Tampered parents still reject before dispatch.

- 2026-10-28: Reviewer found that an unknown model-validation policy could hide the receipt via the legacy branch. All present receipts now match their recomputed recognized policy or genuine policy-free legacy diagnostics; unsupported/unmeasured states remain visible. Added5focused controls and requested independent actual-publication rereview. Also fixed a directly reproduced consumer mismatch: admission allowed a zero decision budget, but report rejected it; the zero-call hold scenario now has an end-to-end regression.

- 2026-10-28: Final parent-focused integration gate passes67/67 with no exclusions:14HTTP reuse controls,5estimator rendering/actual-publication checks,11model consumer/receipt/budget scenarios and37existing report regressions. All four market-health fixtures now use explicit synthetic natural settlement terms, preserving their stale/fresh lane assertions. G1owner final120pass and MRowner74focused/286compatibility evidence are archived. Awaiting reporting-owner freeze and independent closure before the combined broad gate.

- 2026-10-28: Final owner/reviewer closures are complete, including38native market/prior checks,120health/probe checks,286model compatibility cases,68independent parent/report checks and2independent final prior-publication controls. Counts overlap and are not summed. Combined159module gate is running against547 frozen files. Primary preservation check retains the original HEAD/status and85of86 tracked-dirty hashes; .env.example changed during concurrent activity outside this task and is left intact. No production uploads were written.

- 2026-10-28: The frozen broad gate reported one failure in the existing world-evaluation module after passing earlier target/research/report checks. Source remains unchanged547/547. Letting the run finish to collect exact failures before classifying and repairing; focused green results do not override the broad failure.

- 2026-10-28: Initial combined159module gate completed5300passed/4failed/2knownvendor-skips in483.52s with547sourcefiles unchanged. Two old market fixtures lacked settlement descriptions; one alternate linear model fixture mixed known units. Assigned their narrow fixture migrations preserving behavior assertions. Independent reviewer is diagnosing the fourth concurrent-evaluation failure against unchanged baseline before any rerun/acceptance. Full original failure JUnit/receipt/log are archived.

- 2026-10-28: Independent read-only evidence analysis identified the world-evaluation failure as a pre-existing schedule-sensitive terminal error selection, not lost costs or denominator entries. One actor consumed2unknown attempts before peers; errors[0] reflected required_decision_failed rather than the competing run_budget_exhausted. Original108attempts,21.6unknown/reserved exposure,0actual, incompletegates and96points/domain all held. Current and baseline code hashes match, and one focused run each demonstrated the alternate scheduling outcome. Assigned a narrow deterministic/schedule-aware fixture correction with exact error allowlists and all original accounting/replay assertions retained; no production controller change.

- 2026-10-28: All4initialbroadfailures have focused closure:88marketfixture checks,128runtime checks and9deterministic accounting checks. The forcedslot-first schedule reproduced the original incorrect assertion before repair. Only4test files changed after the initial broadgate; production source remained identical. Final159module gate now runs on a fresh release snapshot with547hashed files and all cases included.

- 2026-10-28T06:32:12.896603+00:00: Final159module gate passed5306/0failed/2knownskips in473.90s;547hashes unchanged, guard shutdown complete, identity preserved. verification.json and acceptance.json now record scoped offline acceptance. Commit and push follow; no app bytes will change.

- 2026-10-28T06:37:42.719861+00:00: Code commit 722866a54f919623b2c8f579a53f2e0c4c1afbdc pushed and remote-verified on legacy/codex/first-ten-remedies. Worktree was clean after code commit and all547tested hashes still match. This documentation-only closure adds delivery.json; no tested source changed.
