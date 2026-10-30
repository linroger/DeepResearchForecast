# Independent final core rereview

**Status:** Complete — no open P1/P2 findings in the reviewed core scope. **Signed:** Independent Codex core reviewer, 2026-10-28T04:12:51Z.

**Final verdict:** CORE-1 through CORE-5 and the additional CORE-6 through CORE-12 findings are closed against the frozen source manifest below. The immutable production gate passed **8/8** scenarios; the original core/research/report/API/estimator suites passed **248/248** tests; Ruff F/E9 passed on 20 reviewed production files. All 154 registered source/test files stayed unchanged across the final runs. This is scoped offline core acceptance; the separate library actor/journal review and broader release gates remain outside this verdict.

This review rechecks CORE-1 through CORE-5 from `review-core.md` against current source and traces upstream estimator/evidence production, forks, cohort registration, and reuse pins. Only this report is owned. Other owners' source and reports are read-only; there are no provider calls, live probes, service activation, commits, or pushes.

Acceptance requires fresh guarded production-path reproductions, source hashes and guard receipts, with explicit limits on what helper tests establish. Historical receipts are not reused as current proof. The former `/private/tmp/review-core-0d7jp2ya` evidence tree is absent in this session.

The review sequence is to inspect the repaired producer and consumers, run a fresh focused baseline, investigate concrete integrity or lifecycle defects with bounded guarded probes, report repair requests, and recheck repaired bytes. Findings remain open until their original scenarios and relevant controls pass.

## Progress and evidence

- Read the scoped handoff, plan, contracts, supplied requests, relevant owner reports and prior core findings. Preserved all other owners' files.
- Independently reproduced defects, sent repair requests promptly, and reran unchanged reviewer assertions after owner fixes.
- Completed fresh production-path verification, guard-receipt review, source-manifest comparison and Ruff. Historical failures and intermediate source states are retained below.

### 2026-10-28 initial guarded evidence

Evidence root: `/private/tmp/review-core-final-20261028-u4M5pt`. `before.json` records 154 source/test hashes. The ordinary guarded baseline ran `test_target_pipeline.py`, `test_target_research.py`, `test_target_report.py` and `test_target_estimators_owner.py`: **136 passed / 18 failed in 7.36 seconds**. All 18 failures hit the research fixture's fixed `asOf=2026-10-27` against real 2026-10-28 ledger retrieval timestamps. This is a fixture clock issue, not evidence to weaken the production cutoff. The coordinator assigned its repair to Harvey.

The production pipeline publication/retry/continuation, return-boundary cancellation, rule-only success and missing-provider LLM-actor controls pass in this baseline. CORE-1's adversarial planner rejection passes; authenticated continuation and CORE-2's parameter-to-report proof remain unverified until the clock repair removes the earlier failure.

Four additional desired-behavior regressions deliberately fail against current production source. `/private/tmp/review-core-final-20261028-u4M5pt/run_probes.py` installs the existing `Guard` before application/pytest imports, redirects storage through the same runner, records all reviewed application/bridge/test source hashes, and materializes its tests inside its new evidence root. Run `probes-01` completed with **4 failed in 4.10 seconds**, zero registered source drift, normal shutdown, preserved identity variables, and only the three expected storage redirects; there were no network/denied-operation events. Its failures are the defects below, not an acceptance pass.

## Historical findings sent to the coordinator and repaired

### CORE-6 [P1] — Valid target fork completes but cannot use graph/simulation consumers

The real `PipelineOrchestrator.fork` and `_run` complete the child. `_isolate_fork_handoff` in `pipeline_orchestrator.py` places child research at `consumed-handoff-*`; `api/graph.py:_target_pipeline` insists on `<pipeline_id>/handoff`. The simulation API shares that same rejecting helper. Fresh `probes-01/fork-api.json` records parent graph/simulation **200/200**, child **409/409**, and unchanged parent responses afterward. Both child errors are `Target handoff does not belong to this pipeline`.

The coordinator should align the producer's child-owned handoff with the API's known owner-local path contract while retaining traversal/symlink rejection. Recheck real fork → run → GET graph and simulation routes, plus parent preservation.

### CORE-7 [P2] — A target fork reseals a parent research generation whose receipt fails

`PipelineOrchestrator.fork` checks graph presence but does not validate the parent's completed research receipt. The child target branch resets stages to pending. Snapshot copying compares bytes only to its own copy-time hashes; `run_target_pipeline` inherits the case binding and reseals the copied report without requiring the parent manifest to validate.

Fresh `probes-01/fork-tamper.json`: after appending only a sentinel to the parent's `research_report.md`, parent research validation is **false**. The child nevertheless **completes**, its research stage is **completed**, its research receipt validates **true**, and `copied_corruption=true`. Require the parent's sealed generation before a fork and bind copied bytes to it, or regenerate derivatives from authenticated authority. A valid fork is the paired positive control.

### CORE-8 [P2] — Ambient tournament flag changes a frozen run's estimator output on report retry

`forecast_tournament.py:run_forecast_tournament` still resolves `enabled` from current `Config.REPORT_TOURNAMENT` even when consuming `saved_estimators`; `report_agent.py:_forecast_diagnostics` does not pass the pipeline's pinned enable flag. Fresh `probes-01/estimator-flag-pin.json` records a completed initial report with research, reference_class, trend, adversarial, market_implied, structural and simulation lanes. After changing only the ambient flag to false and retrying report, the run completes with **research only**. `target_tournament_enabled` remains true and the saved estimator envelope bytes are unchanged.

Consume the frozen generation under the admitted setting. A current process setting must not silently erase a previously saved estimator generation. Add production report retry with the ambient flag flipped and verify all saved lanes and authority remain unchanged with zero new method calls.

### CORE-9 [P2] — Manual report consumer rejects the production target-input shape

`api/report.py:_target_report_inputs` compares `target_input.json` with an exact dict lacking `decisionBudget`, whereas `target_pipeline.py` always emits that field and the simulation consumer validates it. Fresh `probes-01/manual-report-inputs.json` uses a successfully completed pipeline and records `Target report input integrity verification failed: Target inputs differ from the frozen case or settings`. This is an actual producer/consumer mismatch, missed by isolated hand-built fixtures. Align the exact comparison with the pinned decision budget; retain failure on altered budgets and settings. The report owner is validating this consumer.

All four findings and evidence paths were sent through native collaboration messaging to coordinator `01a17ca5-401c-7e63-bb7e-3564780d1c2d`. An attempted app-thread message was rejected because this is a native ancestor; native `multi_agent_v1.send_input` succeeded. No repair code was written by this reviewer.

### 2026-10-28 repair rerecheck — CORE-6 through CORE-9

The coordinator added `capture_fork_source` and `isolate_target_fork`, froze parent research/ontology/graph manifests at fork admission, checked them again at copying, and installed target child research at the canonical local handoff. The generic OASIS copy route remains separate. The estimator owner made omitted enablement follow the saved estimator generation; the report owner added the pinned decision budget to manual input comparison.

The **same four reviewer production regressions now pass**, without altering their assertions: `probes-02/junit.xml`, **4 passed in 3.96 seconds**. Its completed receipt records zero registered source drift, normal shutdown, preserved identity variables, and only storage redirects. Child graph and simulation endpoints return **200/200** and parent endpoints stay **200/200**. Tampered parent prose is rejected at fork admission. A report retry with the ambient tournament flag false retains all seven lanes and the exact saved envelope bytes. Manual report inputs accept the actual pipeline output.

CORE-6, CORE-7, CORE-8 and CORE-9 are **closed for these tested bytes and scenarios**. Later changes still require the combined final gate. Coordinator-owned after-admission tamper/recovery controls, research fixture repair and additional upstream evidence checks remain in progress.

### CORE-10 [P2] — Native market-envelope health is discarded before estimator freezing

`target_pipeline.py` extracts `market_rows` from the stored envelope and supplies only that list to `freeze_target_estimators`; `forecast_tournament.py:_market_lane` reconstructs health solely from individual rows. Native collector status/cache metadata lives on the envelope. A dated row from a cache can therefore be classified as fresh even when the authenticated envelope explicitly says stale.

Production research-only repro `probes-03/market-envelope-health.json` preserves the native `{markets, as_of, status:{state:stale,cache_hit:true,stale:true}, cache:{hit:true,stale:true}}` payload exactly in `target_evidence.json`, yet seals the market estimator with `status=ok`, `p=0.73`, and rationale `Fresh stored exact-equivalence market snapshots.` This falsely admits unhealthy input into the stored shadow estimator generation. Published research authority still has zero market weight; that does not make a mislabeled independent estimator acceptable. Pass the full health envelope to the producer, preserve its status, and test stale/failure/undated plus fresh controls.

### CORE-11 [P2] — A native market payload breaks target report publication

`ReportAgent._init_target_report` passes `evidence["markets"]` directly to `build_target_report`; for the native collector shape this is a dict. `forecast_extractor.py:derive_binaries_from_tree` iterates `markets` as a list of market objects at line 4613. With an explicit polymarket binary contract, it instead iterates string keys and raises `AttributeError: 'str' object has no attribute 'get'`.

Production full-pipeline repro `probes-03/market-payload-publication.json` completes research and freezes upstream estimators, then fails report publication with exactly that error. The paired fixture is a standard dict envelope containing one complete exact-contract market snapshot. Normalize native dict/list carriers consistently for tree anchoring while retaining full status for input health and estimator admission. Recheck pipeline → publication → manual reconstruction with a real stored market payload.

The reviewer added only temporary probes in `run_probes_v2.py`. `probes-03` has **4 passed / 2 failed in 4.03 seconds**, normal shutdown and only storage redirects. The receipt records concurrent drift in `test_target_report_api.py`, which these probes do not import; all registered production source stayed unchanged. These two new findings were sent immediately to the coordinator.

### Research repair and combined producer → publication proof

`research-recheck/junit.xml` records **65 passed in 6.93 seconds** after the fixture-only clock repair. The original CORE-1 forged-planner regression and authenticated genuine-excerpt rotation both pass. CORE-2 binds coefficient 2.0 from admitted fetched primary passages and persists its proof.

The reviewer additionally connected the actual `_Engine`/gateway/tools producer to `PipelineOrchestrator._run` through a scripted transport adapter, then used real mechanisms, real report generation, final audit and publication. `probes-05/engine-to-pipeline-publication.json` records **completed**, coefficient **[2.0]**, all three target paths **352.0**, published probabilities **[0.3, 0.7]**, every stage receipt valid, and `publication.publishable=true`. This closes CORE-2 through the final consumer, not only through the helper projection. It also verifies the repaired publication fixed point with actual producer output. The scripted model made 16 local fixture calls; no provider/network transport ran.

### CORE-12 [P2] — Report retry unnecessarily requires the decision provider for already sealed LLM paths

Before the latest repair, provider readiness ran unconditionally before preparation, including report-only retries with valid completed simulation. `probes-05/saved-llm-path-provider-retry.json` records a successful first run with scripted LLM actor decisions, then a failed report retry after provider readiness became unavailable; the run stage stayed completed and simulation bytes stayed unchanged. The coordinator moved readiness behind validation of the existing completed run receipt. Fresh retesting is pending.

The first attempt to probe this scenario (`probes-04`) used an incomplete decision-provider stub that omitted the production usage counters and failed before reaching the intended boundary. That setup failure is not application evidence. `run_probes_v3.py` corrects it by retaining the real decision callback and substituting only the JSON transport client; `probes-05` establishes the actual readiness defect.

`probes-06` still failed both native-market scenarios during the brief interval after upstream whole-envelope forwarding and before report normalization landed. It is an intermediate integration failure, not a new finding or a closed gate. Final combined verification is held until the reporter and coordinator freeze the source.

### Native markets and saved-path readiness rerechecks

`probes-07` reruns the unchanged native-market regressions after whole-envelope health preservation and report normalization: **6 passed in 4.79 seconds**. The stale payload now seals an unavailable market lane with no probabilities; a complete fresh native payload reaches full published report. `probes-08` reruns the corrected saved-provider and actual-engine scenarios: **6 passed in 5.90 seconds**. The report retry completes after credentials become unavailable and retains exact simulation bytes. The actual engine → pipeline → publication proof remains green. Both receipts have zero registered source drift, normal shutdown, preserved identity variables and only the three storage redirects. CORE-10, CORE-11 and CORE-12 are closed for these tested scenarios pending the final combined frozen-source gate.

The requested `ruff check --no-cache --select F,E9` passes on 20 reviewed production files (target core/actors/mechanics/report, pipeline, estimator/health, related APIs and research bridge). Its exact command/output is recorded at the evidence root. No formatter, source fixer or repository code write was run.

## Final findings and disposition

There are **no open critical/P1 or important/P2 findings in this core review**. Earlier pending statements describe their historical source generation; this table is the final disposition.

| Finding | Disposition and current evidence |
|---|---|
| CORE-1: planner passage laundering | **Closed.** Original real-engine forged-planner rejection and authenticated genuine-passage rotation pass in `final-core-suite`. Fresh planning evidence is rejected in `target_research.py:595`; checkpoint continuation requires retained fragments in pinned original pages. |
| CORE-2: missing parameter producer | **Closed.** Real post-gather binding at `target_research.py:689` produces coefficient 2.0. `final-probes/engine-to-pipeline-publication.json` records actual engine → persisted case → all three target paths 352.0 → published report probabilities [0.3, 0.7], with every stage receipt valid. |
| CORE-3: cancellation becomes completion | **Closed.** The original return-boundary cancellation test and normal completion controls pass on final bytes; cancellation is checked after producer return and before terminal success. |
| CORE-4: final rendering not at a fixed point | **Closed.** Actual full publication, report retry, research-only continuation, and the combined real-engine publication scenario pass. Final audit remains enforced and records no linter mutation. |
| CORE-5: LLM/rule provider readiness | **Closed.** Rule-only case succeeds without provider credentials; a new LLM-actor run fails before simulation when its provider is unavailable. Sealed-run report retry is separately covered under CORE-12. |
| CORE-6: fork API path mismatch | **Closed.** `target_pipeline.py:158` installs canonical child inputs. `final-probes/fork-api.json` records completed child graph/simulation 200/200 and preserved parent 200/200 responses. |
| CORE-7: tampered-parent resealing | **Closed.** `target_pipeline.py:138` validates and freezes parent receipts. Final reviewer probe rejects altered prose at fork admission; original regression additionally rejects parent changes after admission before copying into the child. |
| CORE-8: ambient flag erases saved lanes | **Closed.** Saved envelope drives omitted enablement in `forecast_tournament.py`. Final report retry retains all seven original lanes and identical envelope bytes after the ambient flag is disabled. |
| CORE-9: manual input schema mismatch | **Closed.** `api/report.py:466` includes the pinned decision budget. Actual pipeline → manual reconstruction and the full API suite pass; altered input/seal controls remain enforced. |
| CORE-10: native stale envelope laundered as fresh | **Closed.** The pipeline forwards the full stored payload; `forecast_tournament.py:64` checks envelope and row health. The final stale-envelope probe retains an unavailable market lane with no probabilities. |
| CORE-11: native market dict breaks publication | **Closed.** `target_report.py:204` normalizes row extraction for binary anchoring while preserving the envelope elsewhere. Final fresh native-market pipeline completes publication; native cached data stays stale. |
| CORE-12: report retry needs a provider despite saved paths | **Closed.** `target_pipeline.py:434` validates the completed run before skipping provider readiness. Final saved-LLM-path retry completes without the provider and preserves simulation bytes. |

The existing prospective registration and fork-cohort controls also pass: same-case retries retain enrollment; changed case/seed/policy and retrospective enrollment fail; diagnostic forks are excluded from production cohort authority. These controls establish local contract behavior, not prospective forecast lift.

## Final verification and reproducibility

Evidence root: `/private/tmp/review-core-final-20261028-u4M5pt`. Exact invocations and bootstrap details are in `commands.md`.

| Final gate | Outcome | Evidence |
|---|---|---|
| Eight unchanged reviewer production scenarios | **8 passed in 6.27 seconds** | `final-probes/{junit.xml,completed.json,test_review_probes.py}` and scenario JSON files |
| Original target pipeline/research/report/report API/estimator regressions | **248 passed in 25.64 seconds**, zero skips/errors/failures | `final-core-suite/{junit.xml,completed.json}` and `final-core-suite-output.txt` |
| Ruff on 20 reviewed production files | **Passed**, `--no-cache --select F,E9` | `final-ruff-output.txt`; exact file list in `commands.md` |
| 154 source/test hashes before and after both final runs | **Zero drift**, including the library file during this interval | `final-before.json`, `final-source-hashes.json`, `final-summary.json` |

Both completed receipts record exit code zero, completed shutdown, preserved identity variables, no child processes and only the three expected storage redirects. No network, credential, subprocess or blocked-operation events were recorded. The guard remains a CPython audit boundary, not an OS sandbox. Library source happened to remain unchanged during these runs; its separately assigned FBL1 actor/journal issue is not accepted by these core scenarios or the library hash alone.

The immutable final bootstrap SHA-256 is `b1715e20779b4e95fec2e0f2e4b3c2f854c8b8f4d92a15ab7c652c0ba17b0c1d`. The full 154-file final source manifest SHA-256 is **`afc740def0967d66a0c8ebf6b4faf01c3516f9b8d1a65ab8d0f20eab583edeb9`**. Key entries from that manifest:

```text
f5653615b1ac7211b7ea7232243cfa3798ff551f021a46a58dca3786ddd2cfbe  deerflow_bridge/forecast_case.py
e65b6f0db0fd9edb118f3b2f004a2269cbe8dee74ebd1e188b31c025f7a0f98f  deerflow_bridge/target_research.py
a65a525d8196f5cc929e05da382cbcff84e2526c693247ac012649ca34e99141  backend/app/services/target_pipeline.py
baf626562232c8956b147047c2b66628a27e5500972496d88128473b2289d21d  backend/app/services/pipeline_orchestrator.py
2c2e6a159d5fb972d6bb71e0eabcd10c80984527947f6d27edc0bd5421f3dec5  backend/app/services/target_report.py
d5db366d2ba61cdbde0e5c07fd23dd9bb99b7f7d4e893961acb55a0d2554e681  backend/app/services/report_agent.py
7ca8bf92f91d7d87e430cfa8c63b382c14f6c54dd0a3c4eea7b6d11eeda3720b  backend/app/services/forecast_tournament.py
74d362a17e2ecc7c82e50d354c181269c2b2c26fbf0f0e4a811aeffb2f4cd05e  backend/app/services/forecast_inputs_health.py
eeae32dda33f012d6b3a87db00b8371409a2ed9cf58671c804b8d1ca80231831  backend/app/api/report.py
517a103ef61d5ff5cfe813b8c2f8d4ef62e7d7ee9581047ab50740c69de3c183  backend/app/api/graph.py
31df1e5ed4569a9825a154884742ca83639fccbebec49fe66d961c7fe1b116c1  backend/app/api/simulation.py
4e75eed517e4ffc80951159162f6edf249a018e8bfaf60d4176326dbff0a4ffc  backend/app/services/forecast_library.py
```

## Exact edits, positive controls and limits

The reviewer's **only repository edit** is `docs/handoff/target-first-forecast/review-core-final.md`. Reproducer scripts, generated tests, receipts, logs and manifests are confined to the new private temporary evidence tree. Repair source and permanent regression edits were made by their assigned owners. No shared handoff, primary checkout, service, scheduler, provider, issue tracker, commit or push was changed by this reviewer.

The strongest controls are frozen numeric research authority, post-gather parameter proof through final publication, sealed upstream estimator/evidence replay, explicit fork ownership and receipt verification, and zero simulation probability weight. No cosmetic or speculative suggestions are added to this review.

This signed verdict applies to the manifest above and the reviewed contracts. It does not establish live provider/schema behavior, live market availability, real evidence semantics, production deployment, prospective calibration/lift, or completion of the separate library actor/journal review. Any later core/report/estimator code change requires a refreshed affected gate and source receipt before reusing this signoff. Coordinator can continue broader integration and library acceptance from this evidence without repeating the now-closed core investigation.
