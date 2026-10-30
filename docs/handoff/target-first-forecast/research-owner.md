# Research owner scoped report

Status: Source frozen for coordinator integration; one report-owned acceptance check remains failing. Date: 2026-10-27. Scope is the explicit target-first-v1 research producer in the isolated target-first-forecast worktree from 6ab52f77.

## Request, constraints and acceptance

Implement the approved contracts.md route after the existing planner. Resolution nodes and value of information drive bounded gathering, with a mandatory adversarial investigation. Persist source-bound findings, actual passages, date and independence metadata, immutable prior/posterior assessments and typed case-derived artifacts. The route must bypass prose re-extraction and legacy probability-locking QA. Preserve default v3/legacy behavior.

Only target_research.py, linear_research.py, research_gateway.py, deerflow_research.py, necessary bridge sync/setup lists, test_target_research.py and this report are owned. The coordinator owns orchestrator/report/handoff; another agent owns forecast_case.py. No commits, push, services, providers or primary source edits. Tests use the primary interpreter with -I -S -B and the worktree guarded runner, each with a fresh /tmp evidence directory.

| Requirement | Check and evidence |
|---|---|
| Actual producer | Controlled gateway and tools run through _Engine, producing forecast_case.json at handoff root and research_report.md >=400 characters. |
| Grounded findings | Reject invented source IDs/passages, preserve explicit absent dates and shared origins, prevent unsupported settled values. |
| Revisions and restart | Prior remains immutable; changed posterior weights survive; matching reload skips production and altered case/hash/authority fails or restarts appropriately. |
| Compatibility | Existing research engine and gateway tests continue passing under the guard. |

## Plan and progress

1. Inspect adapters, current planner/gather/finalize phases and guarded runner. Done: child runner uses v3 engine factories; parent CLI propagation belongs to coordinator.
2. Add a narrow helper for case planning, evidence admission, priority computation and deterministic rendering; insert an explicit branch after planning.
3. Delegate CLI/runtime sync to a disjoint worker. Huygens owns deerflow_research.py and necessary sync/setup lists only.
4. Exercise real producer and negative controls, review and record exact results.

## Decisions and findings

The existing legacy frame QA rewrites probabilities to the initial planner frame, so the new route must branch before legacy synthesis/QA/finalize. The existing gateway and tools remain budget authorities. The final case belongs at out_dir/forecast_case.json because out_dir is the parent handoff root. Parent bypasses legacy finalization and reads typed artifacts directly.

## Verification and remaining work

Only source inspection is complete. Implementation, guarded acceptance and independent review are pending. No provider realism, live forecast quality or production acceptance is claimed.

## Updates

- 2026-10-27: Created before edits with assigned ownership, explicit acceptance checks and runner correction (-I -S -B).

### Implementation and first verification delta

The target route is an additive helper invoked after the existing planner/replan phases. It replaces topic KIQs with node priorities and a mandatory adversarial KIQ, retains the real gateway/tools/budget managers, and checkpoints typed plan/gather/assessment cases. No legacy synthesis, QA frame repair, prose extraction, market acquisition or chart callback runs on this branch. Final projections and report are derived directly from the validated case.

The CLI worker changed only deerflow_research.py and setup.sh; standalone explicit authority forces v3 and rejects salvage/legacy-only modes. The primary orchestrator runtime sync list belongs to the coordinator. The gateway worker adds conservative publication/origin/tier metadata and bounded actual selected passages; missing metadata remains unknown, and legacy source tiers are not promoted into primary evidence.

Verification run 01 found a fixture/prompt contract mismatch: linear parameters use coefficients plus intercept, not slope. Corrected to the current core template. Run 02 passed 14 target tests using the actual engine/gateway/tools with controlled model/search/fetch functions. Evidence: /private/tmp/drf-target-research-20261027-02/{completed.json,junit.xml}. This includes prior immutability, a posterior weight revision, node/adversarial KIQs, bounded gap follow-up, no legacy extraction, exact final hash, zero-call resume, and tampered final/checkpoint failures.

Follow-up review identified and fixed completed assessments reopening optional gap budget and multi-source claims counting unrelated extra citations as independent support. New run 03 includes those regressions and existing v3 tests. Core schemas reject extra claim/assessment fields; numeric finding/vintage details remain in the persisted typed findings sidecar while core claims use exactly the frozen fields. Definition changes fail explicitly and require a distinct revision case under the current core contract; posterior weights are free to update with an evidence ledger.

### Independent review and compatibility correction

Run 03 passed 67 target plus original v3 tests. Run 04 expanded to gateway/official-data compatibility and found one actual default-contract regression (five new ledger keys), one test fixture import error, and four performance-fixture subprocesses denied because the invocation omitted their explicit script registration. These failures were not treated as passing controls. The new provenance fields now require SourceLedger(capture_evidence=True), selected only by explicit target mode; the legacy exact-key assertion is preserved unchanged. The known trusted timing fixture is registered using --allow-python-script backend/tests/fixtures/gateway_performance.py, retaining the existing guard.

Independent read-only review found partial-checkpoint provenance was not pinned early enough, official datasets lacked retained passages, and sanitized excerpts were being compared against raw page text. Corrections pin fetched source metadata plus content hashes before every consumer (new sources append, consumed sources remain immutable), capture actual pinned dataset bodies in _render_dataset, and compare deterministic sanitized page representations while retaining original-byte hash verification. Added partial-restart success/tamper and real official-data prefetch→case tests. The scoped gateway regression after its fixes passed 551 tests at /private/tmp/target-first-gateway-20261027-dataset-gate. Full combined verification run 05 is in progress.

### Authorized part2 G1 extension

The user approved request-part2.md and assigned inspection/additive last-good caching within _collect_prediction_markets after finishing the target producer. Current code already has Gamma/CLOB base overrides, browser-style user agent, bounded transport/retry/deadline diagnostics and distinct transport_failure versus no_equivalent_market. There is no evidence yet that these transports work on the user's network; no live probe is authorized or performed.

The requested cache will be query-identity-bound, at most seven days old, used only on transport failure, and explicitly stale with original fetched/as-of dates. It must not replace the last-good snapshot on failure or treat reachable empty results as outages. Input-health consumer changes belong to another worker. This extension does not add market acquisition to the target research path or restore prose re-extraction.

Core producer run 07 passed 597 tests in 16.96 seconds. A twelve-file production/test/runner hash manifest was captured immediately before and rechecked after the run with zero drift: /private/tmp/drf-target-research-20261027-final-source-hashes.json. Final review closure is pending. The guard recorded four registered performance child executions and two blocked subprocess attempts (uname and an unregistered executable); no network events occurred. Those blocked probes are not described as zero attempts.

### Review closure delta and transport inspection

The final focused review closed per-KIQ persistence pinning and the target prompt repair, then identified a remaining snapshot race: metadata and content hashes were read from separate ledger snapshots while siblings could append sources. The helper now derives both from one immutable snapshot, with a regression that forbids rereading the ledger after a late sibling source appears. This is a new source state after run 07 and requires renewed acceptance.

G1 static inspection confirms _polymarket_get already uses configured Gamma/CLOB bases, Accept JSON plus a browser user-agent, a configurable HTTP timeout (default 8 seconds), 1–5 bounded attempts (default 2), and typed error-class/HTTP-status diagnostics. _pm_snapshot applies concurrent workers, a run deadline and transport circuit. These facts establish insertion points for cache fallback; they do not diagnose this network's actual failure or establish live availability. The seven-day fallback will preserve the original snapshot time and expose the current failed attempt separately.

### Core review closed; G1 behavioral red

The independent reviewer closed the source-snapshot race after the single-snapshot fix; no outstanding findings remain in the focused core review. Current core-only acceptance passed 29 tests at /private/tmp/drf-target-research-20261027-core-08. This adds explicit source metadata tests: unproven publication dates and timezone-free timestamps remain unknown, arbitrary tier claims do not establish primary evidence, and different hosts do not imply independent origins.

The first controlled G1 acceptance test is behaviorally red against the current collector: the successful snapshot lacks status.state and no last-good generation is created. Receipt: /private/tmp/drf-target-market-cache-red-20261027. Ten cache scenarios are prepared in the owned test_target_research.py. They use scripted snapshots and a fake clock; no live transport or model is involved. The cache worker owns only the collector section of deerflow_research.py for this extension.

### G1 implementation and consumer contract

The collector now supports a seven-day last-good cache keyed by normalized full question, deterministic query inputs, actor/topic context, retrieval caps, model/relevance settings and transport identity. It reads only on a live transport failure, including the existing open-circuit path, and never overwrites a last-good generation with a failure, reachable empty result, mixed/tool-only selection or historical backtest. Cache entries carry a schema, request hash and content hash. Corrupt, oversized, recursively nested, nonfinite, expired, future-dated and mismatched entries are misses. Known future-dated tool observations are rejected before selection.

PREDICTION_MARKETS_CACHE=off disables the cache. PREDICTION_MARKETS_CACHE_DIR supplies an explicit root. A normal uploads/pipelines/<id>/handoff directory derives uploads/_markets_cache. An arbitrary standalone output directory without an explicit root does not discover or write another run's cache.

The prediction_markets.json consumer contract adds top-level as_of, fetched_at and query_key; status contains state (fresh, stale, unavailable, or historical), as_of, fetched_at, age_seconds, cache_hit, stale, attempted_at, undated and historical, while retaining transport diagnostics and empty_reason. cache carries age_seconds/stale/hit, and meta.prediction_markets_status mirrors status. Failed refreshes keep the last successful timestamps; stored-only/mixed rows preserve the oldest known capture time, unknown dates stay null, and their report sections are explicitly stale. A refreshed duplicate retains only captured_via/captured_at/tool_queries provenance from its older row, not obsolete quote fields.

The target producer still performs no market collection or prose extraction. These G1 helpers affect the existing collector; the separately assigned input-health owner consumes their status. No live preflight script or network diagnostic was run. Cache behavior is accepted only against controlled fixtures.

### Final review corrections

The first combined extension gate passed 691 tests. Independent review then identified three concrete cache defects: retaining optional old quote fields on duplicate refresh, publishing explicitly future-dated tool quotes as undated, and allowing RecursionError from corrupt cache JSON to escape. All three were fixed and added as regressions. The affected target/bridge/backtest/tool suite passed 133 tests at /private/tmp/drf-target-market-cache-20261027-review. A final combined run on refreshed hashes follows; earlier green receipts remain historical rather than claims for later bytes.

## Exact owned changed paths

- deerflow_bridge/target_research.py: additive case producer, provenance admission, node priorities, typed checkpoints and rendering.
- deerflow_bridge/linear_research.py: explicit target branch, authority reuse identity, target prompt core and per-KIQ source pinning.
- deerflow_bridge/research_gateway.py: opt-in source metadata and selected web/dataset passages; legacy ledger keys preserved.
- deerflow_bridge/deerflow_research.py: CLI authority/pinning and the authorized G1 collector cache/status extension.
- setup.sh: sync target_research.py and forecast_case.py into the deployed bridge.
- backend/tests/test_target_research.py: producer, evidence, restart, CLI, official-data and cache acceptance controls.
- docs/handoff/target-first-forecast/research-owner.md: this scoped continuity/evidence report.

No coordinator handoff, core case, orchestration, simulation, report or UI source was edited by this owner. Their concurrent changes remain untouched. No commits, pushes, service restarts, actual model/provider calls, live probes or saved-run mutations were performed.

## Remaining acceptance outside this owned slice

The implementation and tests establish the controlled research producer and collector/cache behavior. Real model schema-following, semantic evidence quality, live Gamma/CLOB reachability, live source publication metadata, production deployment, full parent integration, input-health consumers, statistically measured forecast lift and prospective outcomes are not established here. Scenario definitions are immutable within a case under the current core contract; a changed definition set requires a separate revision case. This producer allows evidence-led posterior weights and explicitly rejects silent definition rewriting.

Next integration prompt: Read this report and contracts.md, keep target-first-v1 explicit and preserve the case/hash at handoff/forecast_case.json. Consume typed projections without legacy extraction or probability-locking QA. Read market status.state and original fetched_at/as_of; do not infer freshness from rows being present. Preserve unknowns and the zero simulation weighting policy. Use the final reviewed receipt and hash manifest below, and obtain separate authorization/evidence for any live provider or transport acceptance.

### CORE-1 / CORE-2 urgent repair and identity/library scope

The independent integration review in review-core.md supersedes the earlier narrow worker review. CORE-1 reproduced a real producer corruption: raw planner passages were merged as though they came from a validated prior checkpoint. CORE-2 proved mechanism payloads were ignored, leaving scout parameters in downstream simulation. These findings were open despite the earlier worker test counts; those receipts do not close the integration defects.

The repair separates initial planning from authenticated continuation. Fresh plans cannot include sources, claims or settled node evidence, and build_case no longer merges passages from its input case. Only checkpoint-authenticated continuation may restore old excerpts, and each retained fragment must still occur in the pinned original fetched page. A new post-gather mechanism binding phase updates parameters with admitted primary claims, exact quoted numbers or allowlisted reproducible arithmetic; unresolved parameters remain finite bounded assumptions with explicit gaps. Unknown evidence payload fields now fail rather than being dropped.

The coordinator also requested producer-owned opaque case identity for the global comparison registry. The child now assigns case_<random UUID hex> once in targetResearch before target planning, supplies it in the planning prompt, overrides the model's ID and validates every checkpoint against the pin. Existing accepted generations without the new identity are rejected rather than relabelled.

The new target_library.json input is a parent-selected prior-context artifact. Its complete bytes are hashed on first use, including an explicit absent binding; later byte changes fail. Planning and mechanism prompts receive only entries whose availableAt and asOf are not after the plan cutoff, retaining original provenance/gaps. Library sources never enter the current evidence ledger, and they cannot support verified claims or observed/estimated parameters without a current lookup. Default absent-library prompts retain their previous content.

### Current urgent repair verification and cross-owner blocker

Runs core-fixes-01 and core-fixes-02 exercised the actual engine for the new controls. The second run has 56 passing tests and one failing integration test. The passing scenarios include rejection of the exact forged-planner pattern, authenticated excerpt rotation, random producer IDs/collision separation/restart preservation, identity retention after failed planning, future-filtered byte-pinned library context, unknown mechanism payload rejection, quoted parameter evidence and deterministic ratio calculation.

The remaining failure is not hidden or deselected: test_evidence_updates_mechanism_through_persistence_runtime_and_report persists an evidence-updated coefficient of 2.0, and real run_paths produces targetValue=352.0 on every path. build_target_report then fails in target_report.py:_validate_paths with "invalid path parameter fields" because runtime linear parameters use coefficient:base while the report validator compares them against the wire parameter keys coefficients/intercept. This report source belongs to another owner. The end-to-end acceptance test remains present and failing until that owner aligns validation with the mechanism compiler's flattened parameter shape. Evidence: /private/tmp/drf-target-core-fixes-20261027-02/junit.xml. This is distinct from the earlier report fence/publication CORE-4 finding.

Mechanism evidence raw bindings now have a checkpoint hash and are revalidated on resume. Library bytes are rechecked before each target checkpoint/model phase and finalization. Fresh planning rejects observed/estimated mechanisms and requires bounded assumptions, preventing library/scout entries from being promoted as current parameter evidence.

### Parameter-phase lifecycle corrections

Focused review found that the general builder's mechanism fields were also accepted in the assessment phase, and that an assessment retry could reopen gaps before restoring an older mechanism checkpoint. The producer now uses phase-specific response allowlists, compares the final mechanisms against the hashed mechanism proof, and freezes gathering as soon as mechanism binding completes. Assessment retry cannot overwrite bound parameters or silently drop newly gathered findings. Regression tests cover a 999-valued assessment overwrite attempt and a resumed attempt whose gap budget increased after mechanisms were already frozen.

Current target suite: 60 passed / 1 failed at /private/tmp/drf-target-core-fixes-20261027-03. The sole failure remains the cross-owner report flattened-coefficient validator, after successful production persistence and runtime propagation to 352. No relevant failure is deselected. A future-dated market observation followed by a successful fresh refresh also passes; the earlier walrus variable was renamed observed_time before this run.

### Requested high-signal quality gate

Ran /Users/rogerlin/.pyenv/shims/ruff check --select F,E9 on exactly the owned Python sources and test_target_research.py. Initial findings were the test module's imported pytest fixture aliases (F811); no owned production-source F/E9 findings were reported. Replaced those aliases with narrow local fixture wrappers that delegate to the original bridge, autouse hermetic environment and environment-restoration implementations. Isolation is retained. The repeated owned-file Ruff gate reports "All checks passed!". No peer file was changed.

The focused independent reviewer has closed CORE-1 trust-boundary repairs and both CORE-2 producer lifecycle findings by static inspection. The remaining acceptance is the separately owned target_report flattened linear parameter validation. Coordinator runs the combined gate/hash reconciliation once all owners freeze; earlier broad 707-pass evidence predates the urgent changes and is not the current acceptance claim.


## Current source-freeze result

The owned implementation is frozen for the coordinator. Fresh final owned test run: **60 passed, 1 failed in 7.65 seconds**, with no skips. The sole failure is the preserved real producer → persisted case → runtime → report regression at test_target_research.py::test_evidence_updates_mechanism_through_persistence_runtime_and_report. Producer, persistence and runtime assertions pass (coefficient 2.0, target 352.0); target_report._validate_paths rejects the compiler's coefficient:base parameter key. No report-owned source was modified to bypass that contract.

Evidence directory: /private/tmp/drf-target-research-owner-freeze-20261027. junit.xml records the exact failure; completed.json records completed guard shutdown. owned-source-hashes.json contains the six frozen owned source/test/setup hashes. The source helper hash e65b6f0db0fd9edb118f3b2f004a2269cbe8dee74ebd1e188b31c025f7a0f98f matches the independent review closure. The coordinator should fix the report validation contract and rerun this exact failing scenario before treating CORE-2's end-to-end acceptance as closed.

Command (from the assigned worktree):

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-target-research-owner-freeze-20261027 -q backend/tests/test_target_research.py
```

Use a NEW evidence directory when reproducing. Owned-source Ruff F/E9, setup.sh shell syntax, and scoped git diff whitespace checks pass. Prior 707-pass and 691-pass broad runs are historical, before the urgent CORE/identity/library changes. The coordinator's pending combined gate is the authority for the final integrated source.

- 2026-10-27T10:58:03.602030+00:00: Frozen owned source after CORE repairs, opaque identity/library controls, focused independent review and Ruff; retained cross-owner report failure without deselection.
