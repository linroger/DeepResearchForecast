# Handoff.md — Simulation After-Action Record and Report Bridge

**Last Updated (UTC):** 2026-10-23T05:05:20.577872+00:00
**Status:** Implementation verified; source delivery in progress. Historical S0–S4 notes below are retained as history.
**Current Focus:** Commit and reconcile the verified feature with the preserved Mandarin work; verify remote delivery and managed local readiness.

The key words MUST, SHOULD and MAY are to be interpreted as described in RFC 2119.

## 1) Request & Context

- **User's request (paraphrased):** The forecast report is meant to be factual and evidence-based while the simulation is speculative. Should the report incorporate the simulation, or should a separate summary at the end of Stage 5 describe the dynamics, the per-period evolution and how the world state responds to agent actions? After the analysis the owner asked for an ADR and a design document with the concrete change list and tests.
- **Operational constraints / environment:** Analysis only on 2026-10-22; no code changed. Main checkout carries unrelated uncommitted work (Mandarin translation repair); nothing from this topic is committed. `diagnostic_only` is the production policy and MUST stay so (I-21).
- **Guidelines honored:** ADR format follows `docs/adr/0001` and `0002`. Every `file:line` anchor in design.md was verified against the tree on 2026-10-22. Invariants I-11, I-16, I-21 come from `EXECPLAN_FOGLAMP.md` (git `92e53486`, not in the main tree).
- **Scope boundaries:** No probability-path changes; no realism work; no demo regeneration beyond badging; world-v1 pathway appendix untouched in version 1.
- **Changes since start:** 2026-10-22 — question answered in chat; owner requested documents; documents drafted. 2026-10-22 ~15:40 UTC — owner approved S0 and then asked to "fully implement this plan" (the whole ADR 0003 architecture, S1–S4) and for improvement ideas on the reflexive simulation and the deep-research phase.

## 2) Requirements → Acceptance Checks (traceable)

| Requirement | Acceptance check | Expected outcome | Evidence to capture |
|---|---|---|---|
| R1 Reader sees what the simulation did, per period and overall | Open the Simulation tab after a completed run | Record view with banner, health, period strip, per-period section | Screenshot; `simulation_record.json` + audit |
| R2 Probabilities provably research-only on the default engine | T1, T2 (design.md §6) | Byte-identical prompts and `forecast.json` across two simulations | Test output |
| R3 Simulation-derived text labelled wherever it appears; lint never relabels as evidence | T3, T13 | Outside-fence hit = hard issue; inside-fence attribution allowed | Test output; lint report |
| R4 Record gated on fidelity | T4, T14, T15 | Negatives rejected; deterministic bytes; input contract enforced | `simulation_record_audit.json` |
| R5 Hollow/invalid runs never narrated | T5 | Stub record, zero LLM calls | Test output |
| R6 One vocabulary, one constants module | T7, T9 | Chart retitled; no literal copies | Test output |
| R7 Bridge present once under `diagnostic_only`, absent under `no_update` | T6, T13 | Count and byte checks in final audit | `final_audit.json`, `forecast.json.simulation_bridge` |
| R8 Bilingual bridge with numeric parity | T10 | ZH rendering byte-stable; parity holds | Test output |
| R9 Documentation records the decision | ADR 0003 exists; design.md has change list and tests | Owner can accept or amend | This folder |

## 3) Plan & Decomposition (with rationale)

- **Execution model for S1–S4 (decided 2026-10-22):** the main checkout is shared with another topic's uncommitted edits and a concurrent editor, so implementation runs in isolated git worktrees branched from `claude/sim-provenance-s0` (S1 backend and S2 frontend in parallel via a Workflow with `isolation: 'worktree'`; S3 after the S0 review lands), each agent committing on its own branch. Integration happens on a new branch `claude/sim-provenance-impl` checked out in the clean worktree `scratchpad/wt_head` (the same branch cannot be checked out twice, and `git merge` in the dirty main checkout would refuse on `report_agent.py`). The main checkout stays on `claude/sim-provenance-s0`. Shared anchors committed first: `sim_provenance.py` (strings) and `simulation_record_contract.py` (record shape, loaders, `is_published`). Frontend tests in the worktree use a symlinked `node_modules`; backend tests use the main checkout's `.venv` python from the worktree's `backend/` directory.

- **Critical path narrative:** S0 first because it removes the laundering rewrites and the misleading chart title with no new artifact and the smallest blast radius. S1 next because the record is the raw material for everything reader-facing. S3 (bridge + prompt isolation) depends on S1 and is the only slice that changes report bytes, so T1 lands with it. S2 and S4 are presentation and documentation and can run in parallel with S3.
- **Slices:** S0 containment → S1 record + gate + API → S2 dashboard → S3 bridge + prompt isolation + section-aware lint → S4 docs, demo, ADR acceptance. Full list in design.md §5.
- **Decision log:** ADR 0003 (Proposed). Open decisions D1–D6 in design.md §7.

## 4) To-Do & Progress Ledger

- [x] Map all six stages and the simulation→report data flow — **done**; evidence: workflow run `wf_35fd19f8-591` (5 reader maps, 3 design perspectives), chat analysis 2026-10-22.
- [x] Verify code anchors cited in the documents — **done**; grep output 2026-10-22 (function names and lines in design.md).
- [x] Draft ADR 0003 — **done**; `docs/adr/0003-simulation-after-action-record-and-report-bridge.md`.
- [x] Draft design.md with change list and tests — **done**; `docs/handoff/simulation-after-action-record/design.md`.
- [x] S0 adversarial review (3 lenses, 57 agents): 25 confirmed / 2 refuted findings — **fixed** in 3f969fb9 (labels + state-variables chart survive the lint; F1), df5f7026 (Tier-2 `_rl` blocker + all-or-nothing guard; F2), 7dd3d0d0 (pattern precision; F3), F4 (pack header/section prompt/tool hints on one rule, placement keywords, legacy-label audit check, brief policy from the pinned run policy, extractor default/docstring), F5 (docs). Deferred to S3 on purpose: canonical label as leakage pattern outside the fence; `interview_agents` removal from the default tool list.
- [ ] Owner decides D1–D6 and accepts or amends ADR 0003.
- [x] S0 containment — **done** on `claude/sim-provenance-s0` (branched from main 589d5d92): docs cf450ccf · S0.1 33177198 · S0.2 c656cd1b · S0.3 885df8b9 · S0.4 59a4512b · S0.5 d88e3b2a · S0.6 273284b7 · S0.7 dbba3428 · S0.8 8ac209ee · T9 fc523420. Evidence: T3 `test_report_lint_provenance.py`, T7 `test_report_visualizer_titles.py` + `test_exec_brief_sim_disclosure.py`, T9 `test_sim_provenance_constants.py`, S0.6 `test_outcome_header_alignment.py`; re-pinned `test_wave9_report_focus.py`, `test_smoke_realrun_residue.py`, `test_loop006_static_viz_fallbacks.py`, `test_report_visualizer.py`, `test_audit_fixes_infra.py`. Targeted suites green (visualizer, exec brief, lint-related 21 files, foglamp, sessionb, extractor, audit fixes, backtest report stage, wave9 integration/focus, repair/reflection, sim reconciliation). False-positive probe: 0 newly flagged sentences across 6,407 sentences of six simulation-free demo reports (EN+ZH).
- [x] Record shape contract `simulation_record_contract.py` + test — **done** 02de15d7 on s0.
- [ ] S1 record + gate + API — **in progress** (worktree agent, Workflow wf_92affb56-682); planned evidence: T4, T5, T11, T14, T15.
- [ ] S2 dashboard — **in progress** (worktree agent, same Workflow); planned evidence: T12 + frontend build.
- [ ] S3 bridge + prompt isolation — planned evidence: T1, T2, T6, T8, T10, T13, T16.
- [ ] S4 docs/demo; ADR status → Accepted — planned evidence: live default-engine run with one bridge block; live `no_update` run with none.

## 5) Findings, Decisions, Assumptions

- **Finding:** The stated contract (README 1036/1249/1292) and the code disagree. Under `diagnostic_only` the signal pack is pinned into every section prompt and the lint rewrites simulation attribution into evidence wording (`report_lint.py:927, 999, 1009, 1026-1027`). Implication: the current default launders by construction.
- **Finding:** Pre-July demo reports quote fabricated statements attributed to real people and cite action counts; post-WP1 demos contain no simulation content; the only remaining footprint is a chart titled "Forecast Outcome-Share Trajectory".
- **Finding:** The per-period narrative already exists in `world_state_history.jsonl` and is UI-only. No end-of-run synthesis exists on any engine.
- **Finding:** Byte-level probability isolation is proven only for world-v1 (RW-11). The default engine has no such test.
- **Finding:** Zero resolved forecasts, no ablation run, world-v1 realism gate withheld. The simulation has earned no probability authority.
- **Decision:** Separate gated record + one deterministic fenced bridge + prompt isolation + lint flip + RW-11 extension (ADR 0003). Alternatives and reasons for rejection are in the ADR.
- **Decision:** Version 1 bridge is deterministic only (no LLM-written sentence about the simulation in the report). Prose commentary deferred to D2.
- **Assumption:** The arbiter narrative and deterministic lists in `world_state_history.jsonl` are sufficient raw material for a readable per-period account. Falsification: render the record for `sim_3ec25e64209e` (local, 8 committed rounds) and read it. If it reads as a log rather than an account, enable the bounded synthesis (D1) for a per-period smoothing pass under the same gate. Not yet run.
- **Assumption:** Removing the signal pack from section prompts thins mechanism prose but does not break section generation. Falsification: run the demo-corpus rubric before and after S3 (D3). Not yet run.
- **Assumption:** Roughly 1,500 tests pin current lint behaviour. Falsification: `grep -l "leakage\|simulation" backend/tests | wc -l` before S0. Not yet run.

## 6) Issues, Mistakes, Recoveries

- **S0.5 blocker (review).** The Tier-2 numeric guard referenced `report_lint` as `_rl`, bound only by local imports in other methods; on a live run the swallowed NameError dropped the whole simulation-leakage repair pass. Root cause: the repair tests build the agent without an LLM, so Tier-2 never ran in the suite. Fix df5f7026 + `test_simleak_tier2_guard.py` (stub LLM). Guardrail: any change to an LLM-gated branch needs a stub-LLM test.
- **S0.8 label eaten by S0.4 lint (review).** 模拟推演产物 matched `sim_agent_zh`; the what-if table would have published unlabelled. The world-variables chart title "Simulated World …" had been deleted from every published report by the pre-existing `simulated world` pattern. Fix 3f969fb9; guardrail: T9 lints every reader-facing string and requires it back byte-identical.
- **First pattern cut over-matched real-world prose (review).** Re-anchored in 7dd3d0d0; probe over 15 demo reports: 37 newly flagged, all simulation content, 0 in clean reports.
- **Chained edit-then-test commands hid a failed edit (twice).** Guardrail now followed: edit scripts run in the foreground and print per file; tests launch in a separate background call.

- **Dirty shared checkout.** `report_agent.py` and root `handoff.md` carry another topic's uncommitted edits (Mandarin translation repair), and files kept changing during the session (a concurrent process is editing this checkout). Guardrail: each S0 change to a dirty file was staged from a before/after snapshot pair with `scratchpad/stage_hunks.py` (HEAD bytes + this session's hunks only), verified by `git diff -- report_agent.py` containing none of this session's strings. Final verification runs in a clean worktree at the branch tip, not in the dirty checkout.
- **Two `test_context_audit_report.py` localized-brief tests fail in the dirty checkout but pass in the clean worktree at the S0.3 commit and at S0.1.** Cause is the other topic's uncommitted files, not this slice. Recorded so the next session does not chase it here.
- **Script aborted silently inside a background chain** (forecast_extractor edit asserted on an import line that did not exist; the test run that followed reported the old regex). Guardrail: run editing scripts in the foreground and check their output before launching tests.
- **Design assumptions corrected during S0.** `_find_scenario_chart` read only the legacy list-shaped manifest, so its exclusion guard would have been dead code; it now reads the WAVE9 schema-v2 `{items: […]}` shape too. The Tier-2 numeric guard had to change from "every input number survives" to "numbers in non-leaking sentences survive, no new numbers, paragraph may only shrink", otherwise a delete-oriented rewrite could never pass. Both are recorded in the commit messages and belong in design.md §3.4 / §5. Historical: the `【预测结果分布` / `【推演结果分布` marker drift (`forecast_extractor.py:1187, 1266` vs `report_agent.py:4283`) shows why a constants module is required (S0.1, T9). The 2026-06 hollow-run narration incident ("94 agents in round 10", see `pipeline-quality-architecture` memory) is why G7 and T5 exist.

## 7) Scenario-Focused Resolution Tests

Not applicable yet; no change applied. The acceptance scenarios for the implementation are T1–T16 in design.md §6 plus the two live runs named under §4.

## 8) Verification Summary

- **Fast checks run:** anchor verification by `grep -n` for every function, constant and line cited in design.md (2026-10-22). All resolved.
- **Acceptance runs:** none; design only.
- **Evidence vault:** workflow run `wf_35fd19f8-591` journal under the session's `subagents/workflows/` directory; demo report excerpts quoted in design.md §1; local run `sim_3ec25e64209e` `world_state_history.jsonl` row 1 used as the per-period sample.

## 9) Remaining Work & Next Steps

- **Blockers:** owner decisions D1–D6; ADR acceptance.
- **Risks:** listed in design.md §8; the two that most affect ordering are the lint re-pin volume (S0.4) and thinner prose after S3.3 (D3).
- **Next working interval:** implement S0.1–S0.3 (constants module, chart retitle, exec-brief line) with T7 and T9; then S0.4–S0.5 with T3 and the WAVE9 re-pin. Each change in its own commit.

## 10) Updates to This File (append-only)

- 2026-10-22T14:40:00+00:00: created with the analysis findings, the requirement table, the slice plan and open decisions; ADR 0003 and design.md drafted in the same session.
- 2026-10-22T15:20:00+00:00: slice S0 implemented and committed on `claude/sim-provenance-s0` (one commit per change, nothing pushed); ledger, issues and evidence updated; full-suite run in a clean worktree and an adversarial review of the diff in progress.
- 2026-10-23T16:35:00+00:00: S0 review fixes F1–F5 committed; ideas document `docs/handoff/pipeline-improvement-ideas/ideas.md` (448245dd); record contract 02de15d7; S1/S2 agents running in worktrees.
- 2026-10-22T15:50:00+00:00: full suite at the S0 tip in a clean worktree: 7,707 passed / 9 failed / 19 errors / 1,668 skipped; every failure reproduces at the base commit 589d5d92 except the Kaleido exit test, which was a real regression (relative import broke standalone loading) fixed in 77a9f65e; two follow-ups (frontend caption table 73905af4, env example 0567ef18). Owner expanded scope to S1–S4 plus an ideas write-up; record contract committed (02de15d7); S1/S2 agents launched in worktrees.


## 2026-10-23T03:45:43.414648+00:00 — Codex completion continuation

The user asked to finish and validate the existing approved design. The active checkout is still at S0 and contains extensive unrelated Mandarin edits. The integration branch survives at `579c1acf` although its temporary worktree no longer exists. A managed worktree at `/Users/rogerlin/.codex/worktrees/simulation-report-boundary/DeepResearchForecast` on `codex/simulation-report-boundary` recovers the integration source. This continuation follows [PLANS.md](PLANS.md). Historical completion counts above are not fresh verification.

Current status: in progress. The immediate critical path is closing the documented outline-prompt leak, checking record fidelity and real consumer wiring, then guarded acceptance and independent review. Existing decisions D1–D6 use the documented version-1 recommendations within the user's completion authorization. No new probability authority is granted to simulation.

### 2026-10-23T03:53:16.248022+00:00 — Boundary defects reproduced

The old T1 test stub returned empty simulation-tool outputs, masking the documented outline leak. Replacing those outputs with distinct stored trajectories and adding direct-tool/what-if checks produced five behavioral failures (report-red/junit.xml). The writer also advertised simulation_outcomes, coalition_map, opinion_shift and scenario_diff, and faction_brief could fall back to simulation behavior. The fix removes these tools under every non-legacy policy, blocks direct dispatch, prevents the community fallback, and isolates the outline. The report's deterministic bridge retains simulation access.

The main offline runner initially refused the managed checkout because its absolute path includes `.codex`. The guard now checks credential components relative to the explicitly admitted checkout, independently checking resolved targets. Its 25 actual-operation controls pass, including source-read, credential/sibling/symlink denials and child propagation (guard-control-v3). Initial failures from missing evidence parent, an unapplied combined patch, and an over-eager symlink control were corrected; no protected reads succeeded. The report suite exposed reused test directories under guarded execution, fixed with per-test roots. Evidence root: `/Users/rogerlin/.local/share/DeepResearchForecast/verification/simulation-report-boundary/`.

Bounded workers: record compiler/gate/API (Popper), frontend consumers (Kant), read-only stage lifecycle audit (Averroes); parent owns report isolation, guard, integration and continuity.

### 2026-10-23T04:07:03.392609+00:00 — Real trajectory and lifecycle findings

The full saved run `sim_3ec25e64209e` was copied read-only (11 allowlisted inputs) into a private replay snapshot, with source hashes retained. Its nine committed periods compile into 106 public moves and 51 state changes; deterministic compilation, gate, and verified reload pass with zero warnings and no provider calls (`saved-replay-v1/junit.xml`). This proves fidelity to saved artifacts, not their real-world truth or forecasting calibration. The actual saved run was not modified.

Independent lifecycle tracing found missing world-v1/standalone finalization, a generic research artifact endpoint bypass, overly strict RUN reuse dependence on the derivative record, existence-only reuse of stale audits, and post-completion state writes invalidating full-file seals. Averroes is implementing the bounded producer/consumer fixes. Parent report checks now use the real record compiler and gate instead of fabricated audit JSON. A 202-case affected run had 200 passes, one intended fixture re-pin and one explicit skip; it is intermediate evidence, not final acceptance.

Hollow bridges now show health only; no_update omits record links and simulated charts; unmatched bridge markers fail byte/count validation. Structured red-line ranking uses the recorded crosser (`by`) rather than the first actor name in a dict string.

### 2026-10-23T04:47:51.569004+00:00 — Delivery cursor and combined translation validation

The pure feature is in `/Users/rogerlin/.codex/worktrees/simulation-report-boundary/DeepResearchForecast` on `codex/simulation-report-boundary`; no continuation commit or push yet. Primary is still untouched on `claude/sim-provenance-s0` at `aad41e90`, with 69 dirty tracked-file hashes recorded in `primary-preservation-snapshot.json`; subsequent checks show no drift. The complete combined candidate is under the private evidence root's `combined-checkout/`. It contains preserved primary translation changes, the feature, and reviewed manual conflict resolutions. Do not rerun the first-pass `resolve_combined.py` over the updated candidate: later reviewer/harness edits must be retained.

Pure integrated-v1 exercised 38 suites: 870 passed, 11 expected failures, one git-based historical comparison skipped, and one real orphan-owner child fixture blocked because its CLI allowance was omitted. With the exact inspected `backend/tests/fixtures/orphan_owner.py` allowlisted, that case passed (`orphan-control`). Source drift was zero. A later common translation-provenance helper and clarified JSON-hash label still need the final affected/broad gate.

Combined translation validation: 141 passed (`combined-report-v2`) with the named translation restart child allowed. The newer semantic translator receives bridge-free prose; the bridge is reinserted deterministically. Model receipts stay bound to the exact translated body, and full publication envelopes bind the full source/target documents. The publication reader independently checks both. Additional bridge-tamper tests are in `combined-provenance-review`. Frontend combination initially had 18 test-harness import gaps (360 passed); Kant is fixing only the composed harness and the Live-only translation-button scope in the candidate, with no primary writes.

Lifecycle cross-review identified three final edges: verify native world export seals, avoid losing a new world monitor behind an exiting old monitor, and suppress repeated synthesis when only old Markdown survives. Averroes is fixing these; Popper is adding the native result-manifest input seal. After freeze, sync their changed production/test files into the candidate, using three-way merges for primary-dirty paths, then run final guarded gates and build. Halley is reviewing the combined report translation adapter.

Browser proof is saved as `record-ui-en.png` and `record-ui-zh-period9.png` in the evidence root. The actual compiled record component displays the nine-period saved replay and preserves period selection when language labels switch; source narratives remain verbatim. The preview server is loopback-only on 53741 (session 52609). Local production health was ok and `/api/research/list` reported no active pipelines at the last read-only check. Recheck immediately before any managed restart.

Final delivery must preserve primary translation edits and staged news work. Commit only the owned feature files, never the temporary full-run input copy or peer translation code. The candidate's small compatibility adjustments must remain reviewable with the preserved peer work. Save final source hashes, exact tests, independent reviews, source delivery and any operational acceptance limits before marking this topic complete.

### 2026-10-23T05:05:20.577872+00:00 — Final acceptance

The feature branch passes 883 backend tests (2 explicit skips, 11 expected failures), 58 rechecked context tests after fixture corrections, and 321 frontend tests/build. The composed active-source candidate passes 981 backend tests (1 Git-history skip, 11 expected failures), 379 frontend tests/build, the model-receipt/bridge negative matrix and independent review. See [completion.md](completion.md), [verification.json](verification.json) and [issues.md](issues.md). Production hashes are frozen; the remaining action is source delivery and local readiness.
