# Independent target-first core integration review

Status: Review complete for the recorded source states; seven findings remain open. Active source is changing, so coordinator must request a final recheck after repairs. Read-only review except this file.

## Critical / P1 findings

### CORE-1 — Model-planned passages can be laundered into fetched evidence

`deerflow_bridge/target_research.py:107-118` treats `plan.forecastCase.sources` as trusted previously admitted evidence and appends its passages to the actual gateway source rows before `_supported` runs at lines 176-185. `plan_case` passes the raw model-authored case into this same merge at lines 404-410, without requiring initial sources/claims to be empty. A planner response containing a fake S1 quote can therefore make an invented value pass as a verified, settled primary fact.

Reproduction: `/private/tmp/review-core-0d7jp2ya/probe/results.json`, `fabricated_planner_passage`. Actual fetched source: “Installed capacity was 176 GW as of 2026-10-26.” A model-planned S1 passage saying 999 GW, with a matching settled node and claim, was accepted and retained alongside the real passage. No network/provider was involved. This violates the integrity-fail-closed requirement and contaminates the persisted case and every downstream consumer.

Required fix: separate fresh planning admission from continuation of authenticated checkpoints. Require empty source/claim/settled-evidence fields on initial planning, and restore retained passages only from a validated, pinned checkpoint whose fragments are tied to the retained original page. Add an actual engine planning-response adversarial regression plus a valid excerpt-rotation control.

## Important / P2 findings

### CORE-2 — Research never produces evidence-updated mechanism parameters

`deerflow_bridge/target_research.py:404-410` creates the mechanisms before node evidence is gathered. `gather_case` requests only findings at lines 439-450; `assess` requests assessment/binaries and optional actors at lines 478-489. `build_case` at lines 125-218 never consumes a `mechanisms` update. No compile/estimation step binds newly gathered evidence to mechanism parameters. The runtime therefore receives the original planner multiplier/rate/elasticity even when later evidence could identify it.

A focused probe supplied a changed multiplier in the evidence payload; the builder silently ignored it and returned the original assumed multiplier. This is a missing producer path established by static call tracing and a direct builder probe; the probe is not evidence that its replacement value is empirically correct. Required fix: introduce a bounded typed mechanism estimation/binding phase after gathering, with source/claim provenance for observed/estimated parameters and explicit bounded assumptions for unresolved edges; reject unknown payload fields instead of silently dropping requested structural updates. Exercise a changed parameter through persisted case, `run_paths`, and report diagnostics.

### CORE-3 — Late research cancellation becomes successful completion

`backend/app/services/target_pipeline.py:198-214` has no cancellation check after the research runner returns and before `_finish` on `research_only`. `_complete_stage` seals artifacts without checking the event. A deterministic wrapper set the passed `cancel_event` immediately after writing valid research artifacts; production `_run` finished with `status=completed`, research `completed`, and `error=null`.

Evidence: `/private/tmp/review-core-0d7jp2ya/probe/results.json`, `cancel_after_research`. Required fix: check cancellation after producers return and immediately before terminal success; preserve completed research artifacts while giving cancellation the expected terminal status. Add the return-boundary regression and a no-cancellation control.

## Observed integration failure requiring final-byte recheck

The first focused guard run had 157 passed / 3 failed in 5.53s. All three full-pipeline completion/retry/continue failures ended at `forecast_tournament.py:130`, `simulation scenario identities do not match authority`. Evidence: `/private/tmp/review-core-0d7jp2ya/baseline/junit.xml` and `baseline-output.txt`. The current aggregator now uses scenario IDs, indicating concurrent repair; this failure must be rerun against the final bytes before closure.

## Evidence and scope

Primary interpreter only: `/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B`. Existing `backend/scripts/main_offline_pytest.py` guarded the focused suites. The separate `/private/tmp/review-core-0d7jp2ya/probe.py` installed that same Guard before app/test imports. No code, shared handoff, service, provider, commit or deployment changes were made.

Evidence root: `/private/tmp/review-core-0d7jp2ya`. `before.json` and `midpoint.json` record exact hashes and intervening source drift. The initial guard receipt has only three storage redirects and no network/blocked-operation events. This is not an acceptance signoff. Static deployment/API review and the bounded final checks are now complete.

## Critical / P1 publication finding

### CORE-4 — Deterministic target publication fails after reinserting the diagnostics fence

At `backend/app/services/report_agent.py:3173-3177`, `_finalize_citations` completes its canonicalization and audit, then `_insert_sim_bridge` reinserts `diagnostic_markdown` and writes a new `full_report.md` immediately before the final audit. The current target fixture passes the first audit (`lint_would_change=False`) but fails the second (`lint_would_change=True`); `target_pipeline.py:298-299` therefore fails the entire run. This is an integration failure of the real target publication path, even though individual renderer/contract tests passed.

Evidence: `/private/tmp/review-core-0d7jp2ya/publication-recheck/junit.xml` (17 passed, 3 failed: full publication, report retry, research-only continuation) and `/private/tmp/review-core-0d7jp2ya/final-publication/junit.xml` (single full-publication regression still fails in 2.42s). The final receipt hashes loaded production sources and records no drift during that run. In `publication-recheck/pytest-tmp/test_actual_pipeline_runs_case0/reports/report_8ce1c9b827c2/final_audit.json`, disk matches memory, but `lint.changed=true` blocks publication. No provider is needed to reproduce.

Required fix: make final rendering/fence insertion and the audit's prose extraction agree on a deterministic fixed point before the final audit. Preserve both exact diagnostic-fence bytes and frozen research authority; do not weaken the integrity check. Rerun all three production pipeline scenarios, not only `build_target_report` tests.

## Important / P2 readiness finding

### CORE-5 — Full target admission skips actor-provider readiness

`backend/app/api/research.py:113-114` and `backend/app/api/sdk.py:136-137` force `preflight_pipeline(mode="research_only")` for all target requests, including full runs. This avoids unnecessary graph dependencies but also skips provider checks in `pipeline_orchestrator.py:7505-7513`. If research credentials are usable but the simulation provider lacks its key/CLI, a case with LLM actors is still admitted. `target_pipeline.py:151-154` then constructs that unavailable client; the missing-key path raises in `llm_client.py:335-336`, while `target_simulation.py:245-255` catches the exception and records blocked `decision_provider_error` actions instead of executing the requested actor decisions.

This finding is static producer/consumer tracing from the independent API/deployment sidecar; it was not validated with real credentials or calls. Required fix: separate graph readiness from actor-provider readiness, and validate the configured decision provider before running a case that contains LLM actors. Explicitly support rule-only cases without requiring an unnecessary provider. Add one rule-only success and one missing-provider LLM-actor rejection/degraded-status test.

## Full producer evidence for CORE-1

The actual `_Engine`/gateway/tool/checkpoint path was run with only the model/search/fetch transports scripted. The planner supplied a fake retained passage on S1 while nodes were still unknown; the real fixture fetch returned 176 GW. The findings model then asserted 999 GW. Production returned `engine_rc=0`, wrote the final case with value 999 and `status=verified`, and rendered the false quote in `research_report.md`. Reading that final case with its recorded hash succeeded.

- Results: `/private/tmp/review-core-0d7jp2ya/engine-probe/results.json`.
- Reproducer: `/private/tmp/review-core-0d7jp2ya/engine-probe.py` (use a new evidence root if rerunning; existing evidence is immutable).
- Completed receipt: `/private/tmp/review-core-0d7jp2ya/engine-probe/completed.json`.
- Produced case hash: `8e94d0088762341e9d81cabc35d25cf00daf8725edb5a28e891b03fa0a5b1cde`.

This proves producer → persisted case → rendered research consumer corruption, not merely permissive validation of a handcrafted final object. The published full report remains separately blocked by CORE-4.

## Suggestions and positive notes

No cosmetic suggestions are included; the findings above are the actionable review scope. Explicit target authority/engine agreement, strict completed-stage checksum receipts, source identity pins, immutable assessment delta replay, and allowlisted actor observations are useful controls. The new bridge modules appear in both the runtime sync list and `setup.sh`; no additional concrete deployment/import bug was established. Source review and scripted offline tests do not establish actual deployment, live provider behavior, forecast quality, or prospective lift.

## Verification and source-state limits

All five guarded executions completed shutdown and preserved identity environment variables. Their receipts recorded the three expected storage redirects and no network, subprocess, credential, or blocked-operation events. The guard is a CPython audit boundary, not an OS sandbox. The first three selected suites yielded 157 passed / 3 failed; later source changes repaired scenario identity handling, but the focused publication rechecks remained red for CORE-4. Do not describe this as a passing gate.

Only `docs/handoff/target-first-forecast/review-core.md` was written in the repository. Temporary scripts, controlled outputs, and receipts are confined to the fresh `/private/tmp/review-core-0d7jp2ya` evidence tree. No code/shared handoff changes, providers, services, commits, push, or deployment were performed.

Source changed between review phases; `before.json`, `midpoint.json`, and `final-source-hashes.json` preserve that distinction. Per-run receipts identify the hashes explicitly registered for each run. CORE-1's engine reproduction and the final publication reproduction have zero registered-source drift. The current snapshot below is for coordinator recheck selection, not a claim that every listed current byte passed all prior tests.

## Current source SHA-256

Captured at 2026-10-27T10:30:10.654496+00:00. Complete manifest: `/private/tmp/review-core-0d7jp2ya/final-source-hashes.json`.

```text
f5653615b1ac7211b7ea7232243cfa3798ff551f021a46a58dca3786ddd2cfbe  deerflow_bridge/forecast_case.py
b7f9037adccf4b0489f724ede2ba24954a7d10456f9a24c6843cc19130c6f922  deerflow_bridge/target_research.py
f400fbb788cb5c0ac47951a2b9933165ea1b3f457f188c90b58b1e759c35c3c2  deerflow_bridge/linear_research.py
ddc1700b328d4acca0235d308f4c6ff738b9988da5d3caabdce57f18801f44af  deerflow_bridge/research_gateway.py
c4e78eaeb0ca3a439941c18423be8eb6ea2df5e6cdd79e6c6046a259064eb76a  deerflow_bridge/deerflow_research.py
a7125102136c7b9dc36381725e194fd5451b40dcf74b02e1d813a78ea1025aed  backend/app/services/target_pipeline.py
b5d1136f665f600b25ba0093157d8e84f5558be2da61d75d8064fb0efa922b4b  backend/app/services/pipeline_orchestrator.py
8f42b6cf26e9f5b807272eb32cd01b4657f5732d88709ed0431e0ff48b08acfc  backend/app/api/research.py
5e6b61b5c4721ba96d7af6f3da3907b28fb1e089fabcc860023ac2b6a91259d3  backend/app/api/sdk.py
a8983e2cdb0f0db13d702614fc17a01e501d1955909fbbc15af30737b516c715  backend/app/services/target_report.py
45c91699e17c697973e25b5e78a5bdc88f5aff34a05905077c418da6e39fda40  backend/app/services/target_simulation.py
b1ffcfcf26a24cefd65025c48894a02007ab7d3c62ed599ab61ecfe06da2fbed  backend/app/services/target_mechanisms.py
4f4e2d5d08c0da4d345b4c3d9f18fd0fd08ef548d40c725c5a46d4e20b80a35e  backend/app/services/target_actors.py
117165afb565cb2fcc1596de6facfcd082bfe71c9e166a0d0e1b01183e6a90b8  backend/tests/test_forecast_case.py
c874b1b89907b3ea6ba0f93e53f18e7adb606409b90ed5ca1a8ee41760e83c88  backend/tests/test_target_research.py
3fd496cb63debe00d91287d5846480fdaf7dcab3377ca750e370e029024e0dc5  backend/tests/test_target_pipeline.py
a0ea7cbed63193ec35457158e40473a0b0b34929626bf8e7fe9e9d45d5ac1cb2  setup.sh
22ee02e56b3cf9b4d3b6bea869db77b72f10714788db1e3ffd4c02cfd7fcce8d  backend/app/services/forecast_tournament.py
7a10b57511f56a970f12d9ed82eb08fb91adaccd6954e27d28a204f75ebdd2da  backend/app/services/forecast_aggregator.py
703b29d32bdbaf91e71f1833a4052c8ee3720c996e48f89822d5d141aec05fa8  backend/app/services/forecast_inputs_health.py
44dc60d4956f03fa0ebad360715c34843b4423d8e87e3935f07543307d492d0d  backend/app/services/report_agent.py
5046cf820fa468d8e8ffb2e3fdade1d20fca2f0bd56ee15eabdff51c223c02be  backend/scripts/main_offline_pytest.py
c5859983f9424660efe7fc8a6a56952736654824b76fc78a02296e7586de4c01  backend/app/services/official_data.py
8a550fa0bb3d5dd72bc6752917d21de1b39f0fbfd4068dc8b1e35e9e750d50af  backend/app/utils/llm_client.py
```

## Coordinator checkpoint / next bounded action

Prioritize CORE-1 and CORE-4. Ask the research owner to preserve the supplied engine-level adversarial test, and the report owner to run the actual pipeline publication/retry/continue tests. Assign CORE-2's missing typed parameter producer, CORE-3's post-producer cancellation check, and CORE-5's provider admission branch. After all workers freeze their source, request independent recheck against new hashes and NEW evidence directories. Do not overwrite these failure receipts or mark the larger integration accepted from earlier green worker suites.


## Continued read-only review — coordinator repair delta

The coordinator reported CORE-1/CORE-2 assigned to the research owner, added CORE-3 checks after the research producer returns and before `_finish`, and added CORE-5 actor-provider readiness before simulation. Per coordinator instruction, all findings remain open until a fresh final-byte review. The first cancellation regression passed. The simultaneous fork ownership test did not reach its child assertions because parent report publication still failed. Receipt: `/private/tmp/review-core-0d7jp2ya/delta-cancel-fork/completed.json` (1 passed / 1 failed; no registered drift or denied/network events).

### CORE-6 [P1] — Valid target forks cannot load either graph or simulation APIs

The target fork path at `pipeline_orchestrator.py:9391-9401` resets stages, and `_isolate_fork_handoff` at `pipeline_orchestrator.py:9656-9676` creates a child-owned `consumed-handoff-*` directory. The target producer correctly seals its case/graph there through `target_pipeline.stage_specs`. However, `api/graph.py:101-107` insists that the child's handoff equal `<pipeline_id>/handoff`; `_target_case` and graph reads hardcode that same location at lines 114-116 and 137-138. `api/simulation.py:54-57` shares the rejecting helper.

Reproduced with real `PipelineOrchestrator.fork` and `_run` plus Flask test clients: parent graph and target simulation endpoints both return 200; child graph and simulation endpoints both return 409, `Target handoff does not belong to this pipeline`. This is independent of report publication: child research, graph, preparation and run artifacts were produced, but their public consumers cannot read them. Evidence: `/private/tmp/review-core-0d7jp2ya/fork-consumers/results.json` and its guarded receipt.

Required fix: use the canonical owner-local handoff path for target fork snapshots, or define an explicitly validated owner-local snapshot path contract shared by producer and API. Preserve symlink/traversal rejection and do not simply trust arbitrary persisted pointers. Extend the fork acceptance test to GET both the graph and target simulation routes, including parent/sibling preservation controls.

### CORE-7 [P2] — Target fork bypasses the parent's failed research receipt and reseals corrupt prose

`pipeline_orchestrator.py:9334-9341` admits a target fork based on engine/graph presence without validating the parent's completed research receipt. The target-specific branch then resets every child stage to pending at lines 9399-9401. `_isolate_fork_handoff` verifies only that copied files do not change during its copy, rather than comparing them with the parent sealed manifest. `target_pipeline.py:186-212` skips production because it inherited `target_case_binding`, checks only the case hash, and seals the copied research report as a new completed generation.

Reproduction: corrupt only the parent's `research_report.md`, leaving its typed case unchanged. `validate_stage(parent, "research")` correctly returns false. Fork it: the child reaches `research.status=completed`, its new research receipt validates true, and its report contains the corruption. The full run's later report failure is separate and does not prevent the corrupt research receipt/project text from being accepted. Evidence: `fork-consumers/results.json` fields `tampered_parent_research_valid=false` and `tampered_child={research_status:completed,research_receipt_valid:true,copied_corruption:true}`.

Required fix: validate the parent's research receipt before creating/forking a target child and verify the copied files against those pinned parent hashes, or regenerate all derivative prose deterministically from the authenticated case instead of copying/resealing it. Add a tampered-parent-report negative case paired with the valid fork control.

The `fork-consumers` run also encountered an intermediate report/simulation schema mismatch (`invalid simulation decision fields` for newly emitted effectivePeriod/cost/remainingCapacity). The current report source now allows those fields; this transient repair needs the final integrated gate, but is not counted as a separate unresolved finding here.


## Fresh repair controls (findings still open pending final freeze)

`/private/tmp/review-core-0d7jp2ya/delta-readiness` ran exactly the three production scenarios requested by the coordinator: `test_cancellation_at_research_return_boundary_cannot_complete`, `test_llm_actor_requires_provider_before_simulation`, and `test_rule_only_case_does_not_require_decision_provider`. Result: **3 passed in 2.37 seconds**. Its completed receipt records zero registered-source drift, normal shutdown, preserved identity variables, and only the three expected storage redirects. This verifies the CORE-3/CORE-5 repairs for those tested bytes. The rule-only control also reaches completed report publication on that source generation. CORE-4's full publication/retry/continue gate still needs the final combined run; no finding is closed by this interim result.

There is one additional producer/consumer boundary to include in that final gate: `forecast_tournament.freeze_target_estimators` and its sealed `saved_estimators` envelope now exist, but at this read the target pipeline has no call site and `ReportAgent._forecast_diagnostics` explicitly passes `llm=None` without saved estimators. Thus reference_class/trend/adversarial lanes are always unavailable on the target path. This is recorded as an in-flight integration checkpoint, not an eighth finding, because the coordinator is actively wiring known interfaces. Require evidence of actual upstream production → sealed envelope → report consumption (with a no-new-calls retry) before claiming the approved shadow tournament works on target mode. Likewise the structural lane requests `targetDistribution.scenarioDistribution`, which the case schema currently does not admit; resolve that contract or label it unavailable intentionally.

Latest source snapshot at 2026-10-27T10:54:45.465113+00:00: `/private/tmp/review-core-0d7jp2ya/repair-delta-source-hashes.json`. Earlier snapshots/receipts remain unchanged.

```text
f5653615b1ac7211b7ea7232243cfa3798ff551f021a46a58dca3786ddd2cfbe  deerflow_bridge/forecast_case.py
e65b6f0db0fd9edb118f3b2f004a2269cbe8dee74ebd1e188b31c025f7a0f98f  deerflow_bridge/target_research.py
f400fbb788cb5c0ac47951a2b9933165ea1b3f457f188c90b58b1e759c35c3c2  deerflow_bridge/linear_research.py
f0b8276ebba1e977ee46533ecce3f701423862007c4cdbae99cb32c3ae1b04ae  backend/app/services/target_pipeline.py
1635074e621cd41c3a34e74b32ee3729eced5e7fb7d2b9dacb683dd1b8734689  backend/app/services/pipeline_orchestrator.py
8f42b6cf26e9f5b807272eb32cd01b4657f5732d88709ed0431e0ff48b08acfc  backend/app/api/research.py
5e6b61b5c4721ba96d7af6f3da3907b28fb1e089fabcc860023ac2b6a91259d3  backend/app/api/sdk.py
517a103ef61d5ff5cfe813b8c2f8d4ef62e7d7ee9581047ab50740c69de3c183  backend/app/api/graph.py
ac14a1e691abc848cfdb05f182c673c49f60e60cbe238d31a0e43a96d7882875  backend/app/api/simulation.py
```
