# Independent report and native-world merge review

Updated: 2026-10-30T16:44:36+08:00. Initial review: 2026-10-30T16:13:11+08:00.
Branch: `codex/world-anchor-main-merge`.
Status: Initial review retained; focused target-FMP report/native consumer review closed for the exact candidate hashes below. No actionable finding in this affected scope. Full C1 reuse/fork closure remains with Hubble.

## Request and acceptance criteria

Review the current merge of main `f773f61bee4eed6e2c3be23e546d114ff2a786e8` and World Anchor feature `43efe06defc78de9bedda73d1708ba4c750a6150` in `/Users/rogerlin/.codex/worktrees/world-anchor-main-merge/DeepResearchForecast`. Preserve main's preparation, model-reviewed translation and parsed structural checks together with World Anchor and typed frozen forecast authority. Follow producer-to-consumer paths through report/API publication and private audit separation.

This review is source-only. No application imports, application execution, tests, provider calls, service operations, delegation, staging, commits or other Git mutations were performed. The only file written by this reviewer is this document. The concurrent bounded reflexive work is outside this review. The active merge index still contains unresolved entries; this conclusion concerns the current working-file bytes, not a staged or committed merge.

## Findings

- **Critical issues:** None identified in the reviewed merge changes.
- **Important issues:** None identified in the reviewed merge changes.
- **Suggestions:** No additional source change is requested from this review. Final combined-tree runtime acceptance remains the coordinator's responsibility.

The finding threshold was a concrete regression introduced by combining the two parents. Function retention alone was not treated as proof of behavioral compatibility. Existing limitations or hypothetical malformed inputs were not promoted into merge findings without an affected caller and a changed behavior.

## Source traces and positive notes

### Report preparation, extraction and final publication

`backend/app/services/report_agent.py:2917` retains main's frozen binary-quality-policy validation before client creation and feature typed initialization. The typed branch admits the case, simulation, frozen evidence and aggregation policy before ordinary legacy initialization. Both keyword families survive in `forecast_extractor.extract_binary_forecasts` at line 4812. The tree branch returns the case-derived result before acquiring an extraction model; the ordinary branch retains main's evidence-quality policy and its ban on distribution-shaping draws under that policy.

`report_agent.py:6076` is main's structured forecast finalizer with the feature diagnostic call retained at the end; it forwards the pinned binary quality policy. The typed publisher at line 3215 uses its separate frozen projection and audits exact case, simulation, evidence, estimator and policy companions. Simulation retains zero probability authority. `forecast_extractor.py` retains the feature's typed settlement/equivalence checks and exact tree-probability refusal alongside main's versioned evidence scorecard.

`report_agent.py:6797` retains main's parsed Markdown block/inline handling, independent citation scope checks and exact carrier preservation. The only changes to that main function are the feature grade-mode branch and its coverage result. There is no restored coverage-based early return. The shared final publication method at line 12665 combines main's forecast-task snapshot recheck with the feature's bounded insertion and re-audit of quality disclosures. The gate at line 13698 retains the canonical residual-label tuple from main and the feature's validated typed-partition exception and grade disclosures; artifact-integrity defects remain hard issues.

### Translation and report/API reads

Main's model-reviewed bilingual generator is retained at `report_agent.py:11698`, with its source-bound semantic receipt and deterministic envelope reconstruction in `_audit_model_translation_variant` at line 10023. The merge does not substitute the feature parent's older translation pipeline. Main's structured display/forecast projection and explicit repair routes remain in `backend/app/api/report.py:166`; passive reads do not acquire translation work.

The common publication reader at `report_agent.py:17531` combines both parents' validations. A language variant recursively requires the primary report to remain publishable, then checks current source/target bytes and main's model translation receipt. The primary typed report checks all six exact companion hashes and invokes feature external anchor revalidation. Report metadata, forecast reads and SDK forecast reads use the shared publication boundary. The target API admission at `backend/app/api/report.py:582` validates saved stages, manifest entries, case, evidence, estimators, aggregation policy and enrollment before cache reuse or dispatch; forced regeneration retains the producer-owned original report.

### Native preparation, compiler, seal, reload and fork

`backend/app/services/world_simulation/compiler.py:535` combines main's verified ResearchPreparation/source fingerprints, official observations and actor-audience denial checks with the feature's authenticated anchor adapter. Official quantities remain exact native-unit initial metric baselines. They cannot replace a required anchor consumer or become unsupported account, action or flow parameter authority. The adapter retains independent structural provenance and rejects unimplemented required mechanism/hazard consumers.

The public compiler at line 1337 preserves an optional preparation context inside the opaque anchor preparation input envelope. That is necessary for an exact recompilation of the combined source inputs. `validate_world_anchor` at line 1377 reauthenticates the candidate and compares the recomputed spec after removing only the two documented host additions. Reload restores the opaque preparation only after its manifest/hash checks; fork at line 1406 recompiles with the same preparation and fresh native identity.

`world_simulation/modeler.py:110` forwards both contexts into the model messages, so the existing durable message/policy binding covers both. Modeler budgeting, reservation, bounded repair and candidate reuse remain intact. `service.py:108` forwards both contexts to compile, model and seal; `service.py:283` reloads the saved preparation before forking. `artifacts.py:163` requires exact preparation presence and fingerprints before sealing; `artifacts.py:202` requires both preparation proofs on reload before restoring the anchored spec. `contracts.py:175` permits official-observation provenance only for metrics while preserving the exact anchor reference schema.

At `world_simulation/observations.py:114`, the feature's final enabled-anchor filter still runs after the main research/official projection and after the evaluation mask. It replaces legacy actor context with admitted anchor evidence and filters initial values and options. Main's ordinary preparation and official-baseline metadata behavior remains available when anchoring is absent. This ordering prevents the new preparation channel from bypassing enabled-anchor audience admission.

### Public projections and private audit separation

`backend/app/services/target_report.py`, `simulation_record_contract.py`, and `deerflow_bridge/world_anchor_publication.py` are byte-identical to the feature parent. The typed report continues to render the authorized public diagnostic projection instead of raw simulation paths, private plans or decision counters. The report diagnostic method at `report_agent.py:3179` suppresses the raw simulation estimator lane for anchored targets.

`report_agent.py:12975` preserves exact companion hashes in private `final_audit.json` and removes `target_report.files` from the public forecast audit. `_validate_target_anchor_publication` at line 17501 revalidates the external generation, the public projection, the absence of the raw simulation estimator and the absence of privileged companion hashes on every primary typed publication read. Language publication inherits that primary gate. `simulation_record_contract.py:820` retains record-byte/Markdown seals and external anchor revalidation. Main's new discovery-question artifact in `simulation_record.write_record` remains separate from the record schema, report bridge and probability inputs.

## Review method and verification

Read `handoff.md`, the merge handoff and the report, native, preparation, research and off-mode owner notes. Confirmed the requested HEAD and MERGE_HEAD and inspected recent main history. Compared working sources to both exact Git parents with `git diff` and `git show`, then traced the shared functions and their callers. AST inventories found no removed functions/methods from either parent in the scoped report, extractor, API, native compiler/modeler/service/artifact/contracts/observations and record modules. The shared methods that differ from both parents were inspected individually. The API report functions each match a parent implementation; their newly combined call paths were inspected separately.

Read-only AST parsing of the 15 source files in the hash table completed successfully. Scoped `git diff --check` passed. All 15 files still matched their opening review hashes at document creation. Main's `model_translation.py`, `artifact_translation.py`, `research_preparation.py` and translation directory have no working-tree difference from main; the three public-projection modules named above have no working-tree difference from the feature parent.

Existing execution evidence was inspected, not rerun:

| Owner evidence | Observed result | Limit |
| --- | --- | --- |
| `/private/tmp/world-anchor-main-merge-report-20261030-01/completed.json` and `junit.xml` | 317 tests, zero failures/errors/skips; exit 0; shutdown complete; identity preserved | Receipt records `simulation_manager.py` source drift. It is not final combined-tree acceptance. |
| `/private/tmp/world-anchor-main-merge-native-20261030-02/completed.json` and `junit.xml` | 226 tests, zero failures/errors/skips; exit 0; shutdown complete; identity preserved; no recorded source drift | Evidence for that owner's exercised snapshot. |
| `/private/tmp/world-anchor-main-merge-preparation-20261030-06/completed.json` and `junit.xml` | 23 tests, zero failures/errors/skips; exit 0; shutdown complete; identity preserved; no recorded source drift | Focused correction evidence for the manager ordering and combined native/preparation cases. |

No new runtime, build, lint-tool or provider claim is made by this review. The existing receipts' blocked attempts and audit-boundary limits remain as documented by their owners.

## Initial reviewed source hashes (historical snapshot)

These are the initial review bytes. The target-FMP addendum below supersedes only the `target_pipeline.py` entry and the aggregate digest, and adds `target_research.py`. The other fourteen entries were rehashed and remain current.

SHA-256 of the exact initial working-file bytes. The compact, sorted JSON mapping of the following paths to SHA-256 values has SHA-256 `ebcc2a9c723d8f7c11b0f9618fdd44e08a3724a9e631b6fcefb698d143b71e5a` (UTF-8, `json.dumps(mapping, sort_keys=True, separators=(",", ":"))`, no newline).

| Source path | SHA-256 |
| --- | --- |
| `backend/app/services/report_agent.py` | `96274257339550fe05bbd586ffd00dc2b0121e02bdb45839c03e7ca1682ab6cd` |
| `backend/app/services/forecast_extractor.py` | `a7e4e544532685c8b517e3c73c80f3f42277759740460f43742eeb8b02801e9a` |
| `backend/app/services/world_simulation/compiler.py` | `87a41b12c285f0bd3f545c3238dc425c38e20096b9013994ac37ce000b97de27` |
| `backend/app/services/world_simulation/modeler.py` | `fccb299f1248fbdb22860c5fe7ec2f29f1a7afafbc28f0d0d063e65102733569` |
| `backend/app/services/world_simulation/service.py` | `9629436bb28c7fe6fcc9fb7f86e0f631e187c9750da1959148305f411b0ceb8d` |
| `backend/app/services/world_simulation/artifacts.py` | `4481ce8804d9ea710d3eba6ab0fa5d8c5941fbab2e810f39eb1466ed170fac7a` |
| `backend/app/services/world_simulation/contracts.py` | `5f48ff4d31e3480c48a277dc8f3f5341c1c6d029514853d75651c046f3739a1d` |
| `backend/app/services/world_simulation/observations.py` | `9874778baa6198c022a871688e7730a4c89f51ebfab9399a06e813eea6736574` |
| `backend/app/api/report.py` | `12f5c1291dc1d9f12d43fead7f6520e987829bae98d0476bd8d344966684350a` |
| `backend/app/services/simulation_record.py` | `190731799175f6529e6dc93d2da3c653c728a0a18e01ef70485ecfc41b4999b0` |
| `backend/app/services/simulation_record_contract.py` | `9dbff85d2ca8999b4fbc601659b3a3ffee2fe4ddcc474fc8783c58938e53fd5d` |
| `backend/app/services/target_report.py` | `f0154c6e59c57e14339b4ddf62d0b3511da49391fba92f6eeaa36b89292b2357` |
| `backend/app/services/target_pipeline.py` | `256600a8369bd1b99b2b49440b17603c7f6d6e3b4086995e8fd85c5953fa647e` |
| `backend/app/services/world_anchor.py` | `a26021efb3556bae4e86ffa4f8f5c956db537ba76d2e3888e4517084684ea880` |
| `deerflow_bridge/world_anchor_publication.py` | `4f2835590adadae26e76b79fa6c11570ac87beb34e804ecc099f878baa2734e6` |

## Remaining work

No repair is requested from this review. The coordinator still owns final acceptance of the combined frozen tree and merge completion. Any change to the reviewed files invalidates this source snapshot and requires an affected review. The independent review does not approve production adoption or the out-of-scope reflexive changes.

Continuation prompt: Read this review and the current merge owner notes, compare the full source hashes, and revisit only changed or newly failing paths. Preserve both parent authorities. Run any required execution checks under the existing coordinator-approved offline guard; this review itself authorized no application execution or Git mutation.


## Target-FMP report/native consumer closure

Updated: 2026-10-30T16:44:36+08:00.
Disposition: **No actionable report/native publication regression found in the frozen target-FMP candidate.** This closes only the requested affected-consumer review. Hubble owns full FMP reuse/fork authority; the remaining affected producer verification and whole-merge acceptance are not closed by this note.

### Scope and exact-source continuity

Confirmed the requested worktree, branch and unchanged merge parents. Compared the two changed files with feature parent `43efe06defc78de9bedda73d1708ba4c750a6150`; the original reviewed `target_pipeline.py` was byte-identical to that parent, so this diff isolates the new candidate from the retained review. Rehashed all fifteen original source pins: only `target_pipeline.py` changed. The other fourteen report, API, record, anchor and native-world source files still match the historical table above. No repeated whole review was performed.

| Candidate source | SHA-256 |
| --- | --- |
| `backend/app/services/target_pipeline.py` | `4585a688ebf20fb74dff13814229fd239c20a5dff458768e1243f3c5da44acf4` |
| `deerflow_bridge/target_research.py` | `0666fc8fb6baf55f2e62c420515d112b4229b002165f482110165738e229f420` |

The current 16-file source inventory is the original table with its `target_pipeline.py` hash replaced by the candidate above, plus `deerflow_bridge/target_research.py`. Its compact sorted JSON mapping SHA-256 is `82aa696d434a7b67ed3d25e87e728e5bf0113aff2d0f268b64fe02753b09595b`, using the same encoding recipe documented for the original inventory. The old aggregate `ebcc2a9c723d8f7c11b0f9618fdd44e08a3724a9e631b6fcefb698d143b71e5a` is historical and does not identify this candidate.

### Affected consumer traces

1. **The report evidence contract remains closed.** `target_pipeline.py:581` still constructs exactly `schemaVersion`, `caseHash`, `official_data`, `markets` and `news_market_context`. The optional proof is written separately at line 520 and bound by `target_fmp_evidence_binding`; it is not added to `target_evidence`. The report dispatch at line 710 passes the unchanged evidence carrier. This agrees with both strict consumers, `report_agent.py:3101` and `api/report.py:654`, and with the existing six report companions at `report_agent.py:3222` and `17607`.

2. **Manual report admission reaches the new proof validation.** `api/report.py:619` calls `validate_stage` for research, prepare and run before cache reuse or worker dispatch. `target_pipeline.py:193` now validates the FMP state binding, reconstructed evidence and exact research receipt set. The new carrier is attached only to research stage specifications at line 174; report-stage output specifications remain unchanged. Ordinary pipeline report generation follows the new capture admission at line 520 and research completion before dispatch at line 710. This is a source trace of affected report admission, not a substitute for Hubble's full reuse/fork review.

3. **Vendor proof stays outside typed/public projections.** `target_research.py:455` exports vendor capture metadata to handoff `sources.json` while preserving the case source fields. The final case is frozen separately at line 857 before the enriched source export at line 872. The report still builds its citation index from `case["sources"]` at `report_agent.py:3134`; it does not consume the extra capture metadata as forecast authority. The optional file/binding proof is not passed into `ReportAgent`, copied into its six report companions, or added to the public forecast audit. Existing removal of private companion hashes at `report_agent.py:12979` and external anchor publication revalidation at line 17501 remain unchanged.

4. **Native and translation behavior is preserved within this delta.** None of the held native compiler, modeler, service, artifacts, contracts or observations modules changed. The new sidecar is confined to target research admission and receipts; the report contract still supplies the same case, simulation, evidence and optional authenticated anchor context. No new consumer path feeds the sidecar into native actor observations, report prose, translation inputs or simulation probability authority. Existing frozen-report reads remain sealed report consumers; this addendum does not claim that every historical report read now reopens the upstream FMP capture store.

### Verification and limits

Read-only AST parsing of both candidates and scoped `git diff --check` passed. Both frozen hashes and all fourteen held hashes matched at the beginning and end of this follow-up. No application imports, tests, provider calls, delegation, Git mutation or writes outside this review document were performed.

Inspected the existing [37-case completion receipt](/private/tmp/world-anchor-main-merge-target-fmp-fix-20261030-03/completed.json) and [JUnit](/private/tmp/world-anchor-main-merge-target-fmp-fix-20261030-03/junit.xml). They record 37 passes, zero failures/errors/skips, exit 0, completed shutdown, preserved identity and no in-run source drift, in 12.642 seconds. The receipt pins both exact candidate hashes above. The gate consists of 21 target-FMP cases and 16 research-merge cases; it is not a new full report/native execution gate. The target-FMP module includes the closed five-key/no-optional-carrier control and producer provenance assertions, which were read without executing them.

- Completion receipt SHA-256: `826f8adc56e7adc40cad9be12fa0bfd631a9852d417334ad9f0a592fb8a50ebe`.
- JUnit SHA-256: `a0d9e73aa26dd5f7ec71e72a0b9ba56060f04ec9000d9aa539805a5e15d53520`.
- Target-FMP test source pin in that receipt: `2dc19ba4149ec09e0297cf58b1ce79e9a5a84674fe763e0a163e4b251c63b07f`.

The earlier 107-module composed result remains historical for this later candidate. Its one `storage_unavailable` failure, optional historical skips and the narrower scalar rerun are not converted into a combined acceptance claim here. No additional report/native correction is requested on these bytes. Reopen this affected review if either candidate or one of the fourteen held sources changes.
