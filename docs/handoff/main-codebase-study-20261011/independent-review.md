# Independent review of the synthesized main study

**Verdict:** Material documentation corrections are required. The broad lifecycle and engine-selection spine is supported, but the study overstates research sealing and completion guarantees, omits a separate publication boundary, and needs an explicit current-v1 producer-to-PREPARE compatibility qualification.

**Reviewed:** `STUDY.md`, 96 lines, SHA-256 `a90b28e1dcfcdcb3286b8f620c2bf7725c8469c6dee5340ab150984a0f2ae6b4`.
**Source authority:** Commit `c20ec60909fa1aa15154bb6fdb3fdb71c421e10e`, frozen at `/tmp/drf-main-study-c20ec60-20261011/source`.
**Scope:** Only the synthesized spine, its source claims, and its 37 source-anchor occurrences. Findings below concern the accuracy of the study, not implementation quality or proposed changes.

All source paths and line ranges below refer to that frozen tree. For compact references, **P** means [backend/app/services/pipeline_orchestrator.py](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/pipeline_orchestrator.py). Study line numbers refer to the reviewed hash above.

## Findings and exact corrections

### 1. [P1] The default v3 research handoff is not the universally sealed generation shown in the spine

**Study:** Lines 21, 74–76 describe a “Sealed research handoff” and say RESEARCH completes “only after handoff finalization and applicable actor reception.” The default-v3 paragraph does not explain that a new v3 admission explicitly makes the sealed actor plane optional.

**Frozen evidence:**

- [P:832–851](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/pipeline_orchestrator.py:832) sets `required=dual_track and engine == RESEARCH_ENGINE_LEGACY`. A v3 admission records `required=False` and `research_engine_v3_emits_unsealed_actor_plane`.
- [linear_research.py:5526–5568](/tmp/drf-main-study-c20ec60-20261011/source/deerflow_bridge/linear_research.py:5526) writes the v3 outputs directly. [Its structured-output writer:5756–5771](/tmp/drf-main-study-c20ec60-20261011/source/deerflow_bridge/linear_research.py:5756) removes `actor_intelligence_contract` and per-actor `intelligence` before writing `actors.json`.
- [P:3628–3636](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/pipeline_orchestrator.py:3628) makes `_finalize_research_contract` return without sealing when `research_contract_manifest.json` is absent. The single-lane branch calls the research runner directly at P:12047–12075; the lint condition at P:12087–12099 treats a missing contract as audit-only.
- [P:5678–5707](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/pipeline_orchestrator.py:5678) accepts pre-policy runs and a valid policy with `required=False` without validating a sealed actor plane. P:12274–12286 skips actor reception entirely for research-only mode.

**Exact correction:** Change the diagram label to **“Research handoff; contract-sealed on applicable paths.”** Add after the engine-selection paragraph:

> New v3 admissions pin the sealed actor-plane requirement to false and disclose why; v3 produces unsealed report-grounded actor rows. A saved run whose pinned policy requires the sealed plane selects legacy. Runs without that requirement follow the configured engine.

Replace the first sentence at line 76 with:

> Before marking RESEARCH complete, the orchestrator calls handoff finalization, which validates and seals sanctioned changes only when a research contract manifest already exists. Full runs also apply the pinned actor reception policy; research-only runs skip actor reception. The default single-lane v3 path does not acquire the legacy sealed actor-plane contract through this call.

Keep the producer research contract distinct from the generic `handoff/manifest.json` used for artifact registration/reuse.

### 2. [P1] The final health check does not precede every persisted 100% value or guarantee healthy completion

**Study:** Line 90 says, “Pipeline completion runs the deliverable health gate before storing completed/100%.”

**Frozen evidence:**

- REPORT calls `_complete_stage` at [P:13241–13244](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/pipeline_orchestrator.py:13241) on reuse and P:13325–13328 on generation, before the health check at P:13345.
- [_complete_stage, P:9026–9047](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/pipeline_orchestrator.py:9026) sets the stage to completed, computes global progress using REPORT's upper bound of 100, and saves state. A running pipeline can therefore already persist `global_progress=100` before the final health check.
- [P:9445–9497](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/pipeline_orchestrator.py:9445) returns immediately when `PIPELINE_HEALTH_GATE` is disabled, allows degraded health, and catches assessment exceptions and continues. Only collected hard report issues raise. P:13345–13348 subsequently records overall `status=completed`.

**Exact correction:**

> After REPORT stage completion, the orchestrator invokes the configurable pipeline health check before saving the overall pipeline status as completed. REPORT completion can already have persisted global progress at 100%. With the health check enabled, collected hard report defects fail the pipeline; degraded health is recorded without preventing completion, and assessment exceptions are logged and ignored. Disabling the check bypasses it.

This is a correction to the completion claim, not a claim that the check was exercised.

### 3. [P1] Customer publication is a separate consumer check, not an automatic consequence of pipeline completion

**Study:** Diagram lines 29–30 and the report-delivery section imply a single final check leading to UI delivery, language variants, and exports. No cited orchestrator anchor establishes the actual publication consumer contract.

**Frozen evidence:**

- [P:9237–9245](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/pipeline_orchestrator.py:9237) and P:9303–9349 distinguish hard publication issues from epistemic findings. The latter can yield degraded health while overall pipeline completion proceeds.
- [ReportManager.publication_status, report_agent.py:12435–12533](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/report_agent.py:12435) separately checks completed report metadata, failed/partial sections, the final audit, current policy version, exact Markdown/forecast fingerprints, and—when enabled—the professional gate's `passed` value. A gate failure can withhold publication even when it generated only degraded pipeline health.
- [report.py:45–83](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/api/report.py:45) strips the report body/outline drafts from an unpublishable report payload and supplies a 409 publication rejection. The Markdown-download guard is at report.py:725–726, and the PDF guard is at report.py:1069–1077.
- [report_agent.py:11577–11588](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/report_agent.py:11577) performs the configured final audit and attempts optional bilingual generation within `generate_report`. Translation failure does not fail the main report. Language publication additionally checks primary/source identity, isolated citation artifacts, and translation metadata at report_agent.py:12465–12469 and 12533–12594.

**Exact correction:** Split the diagram's final boundary into **pipeline health/overall terminal status** and **ReportManager publication checks at consumer access**. Add:

> Pipeline completion and customer publication are separate decisions. Report APIs revalidate the exact audited deliverable before exposing the body or exports and can withhold a completed report. Bilingual generation is an optional, failure-tolerant operation inside report generation; each language variant must also satisfy its own publication checks and source-identity bindings.

The optional ensemble-sidecar claim is supported: P:8723–8743 writes independent sidecars and options, without rewriting the primary audited forecast. The stale comment at P:13330–13332 is not evidence that ensemble confidence is written back.

### 4. [P2] RUN's actual evidence predicate is weaker and more specific than “simulation_end plus valid summary”

**Study:** Line 84 states that completion requires enabled-platform `simulation_end` evidence and a “valid published `run_summary.json`.”

**Frozen evidence:**

- [P:9942–9974](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/pipeline_orchestrator.py:9942) accepts either a truthy platform `*_completed` bit from run state or a `simulation_end` event in that platform's actions-file tail. It does not require reopening the event file when the bit is already set. If both enabled flags are false, it infers enabled platforms from actions-file existence; no platform evidence fails.
- The normal producer sets those bits when parsing `simulation_end` at [simulation_runner.py:1187–1205](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/simulation_runner.py:1187), but it also reloads them from saved JSON at simulation_runner.py:365–366. The consumer trusts the persisted projection.
- [P:10086–10122](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/pipeline_orchestrator.py:10086) checks that the summary exists, is nonempty, and passes `_probe_artifact_schema`. For `run_summary.json`, [P:7433–7445](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/pipeline_orchestrator.py:7433) merely requires parseable JSON whose top level is a dict or list. This is not a summary-specific semantic validation of identity, agents, or rounds.
- P:13123–13136 records telemetry and applies this evidence predicate before P:13170–13175 marks RUN complete.

**Exact correction:**

> RUN completion requires evidence for each enabled platform, accepting its persisted completion bit or a simulation_end event in its actions-file tail, plus publication of a nonempty summary that passes the generic JSON object/list probe. Legacy enabled-platform inference falls back to actions-file presence. A process exit or overall completed status alone is insufficient; these checks do not amount to a full semantic validation of run_summary.json.

This preserves the supported rejection of process-exit-only completion while accurately describing producer/consumer trust.

### 5. [P2] Several named files and enrichments are optional or best effort, not unconditional stage outputs

**Study:** Lines 60, 80, 82, 88 and 90 describe outputs without distinguishing required artifacts from conditional/observational ones.

**Frozen evidence and exact qualifications:**

- **Run metadata and generic manifest:** `run.json` is configurable through `RECORD_RUN_MANIFEST` and write failures are ignored (P:10374–10391). Generic `handoff/manifest.json` records existing nonempty candidates when `PIPELINE_VALIDATE_ARTIFACTS` is enabled; write failures are tolerated (P:9703–9755). Reuse skips absent entries, permits a missing manifest, and can bypass validation entirely (P:9798–9831, 9887–9907). Replace “contains” at line 60 with **“uses pipeline_state.json and handoff/; it may also contain run.json, telemetry, and handoff/manifest.json, subject to their flags and successful writes.”** The manifest path at P:1108–1110 uses the pipeline's local handoff path; it is distinct from the contained, stored research-handoff reference resolved at P:888–912.
- **Ontology and graph enrichment:** The project ontology is saved, but writing `handoff/ontology.json` is a warning-only attempt (P:12375–12387); ontology reuse reads the project, not a mandatory handoff copy (P:12311–12314). Community detection, entity resolution, pruning and graph-prior persistence have flag/exception/no-data paths (P:12574–12637, 12687–12725). Non-v1 actor seeding may be skipped; sealed-v1 seeding/readback has stricter requirements (P:7199–7207, 7098–7099). Replace “stores … and a handoff copy” with **“stores the project ontology and attempts a handoff copy.”** Describe configured graph enrichments as **attempted, with failures generally logged and tolerated; sealed-v1 seed readback is enforced when that contract is present.**
- **Actor context and roles:** [simulation_manager.py:982–1013](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/simulation_manager.py:982) builds context artifacts only when `selected_actor_rows` is nonempty, otherwise clears their state fields. Role manifests are conditional on a nonzero role count at simulation_manager.py:1242–1276. New preparation does require the executable-config seal at simulation_manager.py:1278–1298; legacy unsealed PREPARE reuse remains readable through simulation_manager.py:1352–1361 and 1442–1451. Qualify line 82 as **“New PREPARE writes the cast and executable-config seal; selected dossier actors additionally produce context/role artifacts. Legacy reuse has compatibility allowances.”** Overlay/seed injection at P:12855–12917 is conditional and failure-tolerant; resealing is required after a mutation actually succeeds (P:12924–12927).
- **Report extras and telemetry:** Structured research files are read optionally at P:13301–13315, and the constructor accepts them as optional inputs (report_agent.py:1533–1552). Chart generation can be disabled, return no manifest, or log and skip a failure (report_agent.py:8893–8915). Telemetry writes are best effort (P:7575–7614, 13435–13485). The normal `telemetry.md` sidecar is separate from prose, as the study says; `REPORT_TELEMETRY_APPENDIX=True` can additionally append it to `full_report.md` (P:13464–13480). Use **“passes available structured artifacts and attempts configured report-owned visualizations; telemetry finalization attempts persistence on all handled terminal paths.”**

These qualifications distinguish an intended artifact layout from evidence required for a stage to complete.

### 6. [P1] Current-v1 producer-to-PREPARE compatibility is not established by the presence of checks

**Study:** The handoff → graph → contexts/personas/sealed-config spine (lines 21–25), together with lines 76, 80 and 82, needs an explicit boundary qualification. Validation functions exist, but that is not proof that an admitted current-v1 producer bundle can pass PREPARE.

**Independently verified frozen evidence:**

- The producer constructs an actor-ID multiplicity map and hashes its compact, sorted-key JSON at [deerflow_research.py:3813–3821](/tmp/drf-main-study-c20ec60-20261011/source/deerflow_bridge/deerflow_research.py:3813). It assigns this digest to both `actor_ids_sha256` and `actor_ids_multiset_sha256` at [deerflow_research.py:3895–3899](/tmp/drf-main-study-c20ec60-20261011/source/deerflow_bridge/deerflow_research.py:3895); ordered IDs have a separate field.
- The parent computes the same multiplicity-map digest through [P:4708–4715](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/pipeline_orchestrator.py:4708) and compares `contract["actor_ids_sha256"]` to it at [P:5404–5413](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/pipeline_orchestrator.py:5404).
- The PREPARE consumer's incoming-contract validator instead computes SHA-256 of the **sorted IDs joined with newlines** and compares that to the same `actor_ids_sha256` field, raising `actor intelligence actor roster fingerprint mismatch` on inequality: [actor_context.py:1267–1279](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/actor_context.py:1267).
- This is on the selected-actor context path: [simulation_manager.py:985–992](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/simulation_manager.py:985) calls `build_actor_context_artifacts`; [actor_context.py:1443–1448](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/actor_context.py:1443) calls `build_actor_context_pack`, which invokes the incoming-contract validator at [actor_context.py:1320–1323](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/actor_context.py:1320). Parent cast reconciliation preserves a sealed-v1 object rather than translating its roster digest (P:3933–3942).
- Do not confuse that incoming producer-contract field with the actor-context manifest's own `actor_ids_sha256`: the latter hashes a canonical JSON list at actor_context.py:1474–1486 and is checked against that representation at :1583–1588. That separate manifest check does not reconcile the incoming-contract algorithms.

**Exact qualification to add after line 82:**

> The source contains parent actor reception, graph seed readback, context/role validation, and executable-config sealing checks. Their existence does not establish that a current-v1 producer bundle can pass PREPARE: the producer and parent define actor_ids_sha256 as a digest of the actor-ID multiplicity map, while actor_context's incoming-contract validator expects the digest of sorted newline-joined IDs. These definitions disagree at a reachable selected-actor boundary. Current-v1 producer-to-PREPARE compatibility remains unverified in this source-only study.

The algorithm definitions and call edge above are directly established from frozen source. This qualification does **not** claim that a particular bundle reached the check, that a runtime failure was reproduced, or that all current-v1 runs fail. No bundle was synthesized, imported or executed, and no runtime diagnosis or fix is proposed. The area reader's note was a discovery pointer only; the area report was not used as verdict evidence.


### 7. [P2] Several anchors are blank, partial, insufficiently targeted, or point at stale comments

All 37 source-anchor occurrences were checked. The ledger below accounts for each occurrence, including both endpoints of the two cited ranges. “Supported” means the cited definition/block is the relevant source entry point; it does not waive the qualifications above.

| Study line | Original anchor(s), using P shorthand | Anchor review / exact replacement |
|---|---|---|
| 36 | P:87, :8894, :8904; research_progress.py:147 | P:87 declares a stage name, not its percentage band. Cite **P:95–106** for full/research-only bands. :8894 and :8904 are correct function starts; read the executable weighting at **P:8916–8947**, which also rescales PREPARE despite the stale “prepare stays static” docstring at :8913. ResearchProgressEstimator starts at :147 and is the relevant estimator. |
| 58 | P:660, :683, :860, :7920; models/task.py:54 | Correct declaration/definition starts. Admission policy details are at **P:832–851 and 7962–7967**; atomic state persistence at **P:945–956**; process-local task storage at **task.py:63–71**. |
| 60 | P:888, :915, :1108 | Correct definitions for contained handoff resolution, run-manifest path and generic artifact-manifest path. Add **P:10374–10391 and 9703–9755** for creation conditions; path declarations alone do not prove required file existence. |
| 70 | P:7982, :8043, :8107, :8214, :8280 | All five are correct public method starts and support the lifecycle table. Fork copies the actor policy at **P:8321–8326**; other options are not copied wholesale. |
| 74 | P:5906, :5937, :5955 | All correct resolver/topology function starts. Add **P:832–851** for new-v3 admission policy and **P:5895–5901** for the literal alias sets. |
| 76 | P:3492, :3607, :11883, :12274, :12294 | Correct function/control-flow starts, but :11883 is the whole 1,610-line runner, and :3492 is promotion rather than lint-byte preservation. Cite **P:12084–12143** for lint, **11919–11959** for contract/recovery selection, **3628–3636** for the no-contract branch, and **12267–12305** for completion/reception/early exit. |
| 80 | P:12306 through :12732 | Both endpoints are blank. Use **P:12307–12731** for the whole region, or **12346–12360, 12375–12387, 12462–12545, 12574–12651, 12687–12725** for the distinct producers and qualifications. |
| 82 | P:12733 through :12965 | :12733 correctly starts PREPARE, but :12965 is already a RUN-reuse assignment. Use **P:12733–12938** for PREPARE; add the simulation-manager producer anchors in finding 5 for cast/context/role/seal assertions. |
| 84 | P:12969, :13118, :10059 | :12969 is a closing parenthesis; :13118 is blank. :10059 correctly starts the evidence gate. Replace with **P:12974–13070** for execution/cancellation/cost-on-failure, **13101–13136** for summary/cost/evidence ordering, **9942–9974** for the evidence predicate, and **10086–10122 plus 7433–7445** for summary publication/probing. |
| 88 | P:13193, :13291 | :13193 is a continuation of a reuse comment; :13291 supplies only `actors`. Cite **P:13195–13244** for reuse, **13285–13315** for report inputs, and **report_agent.py:8882–8915** for chart ownership/execution. The constructor at report_agent.py:1533–1552 actually supports the additional artifacts; the “not yet supported” fallback comment at P:13297–13300 is not proof of a missing consumer. |
| 90 | P:13332, :13342, :13400 | :13332 is a stale comment saying ensemble confidence rewrites `forecast.json`; cite **P:13333–13340 and 8723–8743** for the supported sidecar behavior. :13342 is the DONE heading; use **13345–13348 plus 9445–9497** for the actual completion check. :13400 begins a telemetry metadata dict; use **13393–13485**, especially **13429–13434 and 13464–13480**, for finalization and sidecar/prose behavior. |

## Independently confirmed claims

- The frozen Python path set matches the commit and inventory: **326 total, 146 outside backend/tests, 180 within backend/tests**. I compared all 326 files to their Git blobs and inventory SHA-256 values and parsed all 326 with the standard-library AST parser; there were no mismatches or parse failures.
- The 146 count explicitly includes six bridge patch-test/conftest files and six operational `test_*.py` scripts. The study already qualifies this; no count correction is warranted.
- Static stage bands, v3/linear and legacy/deerflow/agentic aliases, default-v3 normalization, required-actor-policy selection of legacy, and one outer v3 lane are supported. The v3 implementation shares a ledger/tool instance at linear_research.py:3978–3989, gathers pending key questions through gather_kiqs at :4425–4426 and fan-out at :4485–4499, and deduplicates search requests through research_gateway.py:3553–3566.
- Background thread admission, process-local TaskManager state, file-backed PipelineManager state, contained handoff resolution, lifecycle method descriptions, ordered PREPARE mutations/resealing, and ensemble sidecar separation are supported with the qualifications above.
- The UI/API spine is supported by frontend/src/api/research.js:28–35, frontend/src/views/ResearchView.vue:600–659, backend/app/api/research.py:109–125 and :306–331. No browser behavior was exercised.

## Review limits and continuity

This review did not use any other area report or coverage receipt as evidence for its verdict. The inventory and source-validation metadata were used only to check the spine's inventory/integrity claims; their results were independently reproduced. Reading-map completeness, pending links, and aggregate reader coverage are not approved by this review while area work remains in progress. The exclusions stated in the spine are consistent with the frozen tracked-Python scope; no third-party internals, untracked data-MCP additions, external branches or saved runs were used.

No application module was imported or executed. No providers, app processes, tests or installs were invoked; no external branches or saved runs were inspected. Test files were hashed and syntax-parsed only, not executed or used as behavioral evidence. Standard-library source parsing, hashing, text searches and read-only Git-object inspection are the entire validation basis. Source order and predicates establish the corrections and compatibility qualification, not runtime success or a reproduced implementation failure.

Only `docs/handoff/main-codebase-study-20261011/independent-review.md` was written. Source, STUDY, other reports, existing handoffs, tracked changes and untracked work were preserved. No commit, push, issue creation, subagent or asset packaging was performed because the requested output was this review file only.

**Next action for the study owner:** Apply the seven documentation corrections and qualifications above, then reconcile the remaining area reports and coverage separately. In particular, keep the current-v1 PREPARE digest boundary explicitly unverified rather than describing the checks as proof of compatible passage. No implementation change is requested by this review.

---

## Rereview closure — revised synthesis, 2026-10-12 Asia/Shanghai

**Current verdict:** The substantive corrections from the initial review have been incorporated. Two bounded factual qualifications remain in added text, listed below. The revised study still correctly leaves current-v1 producer-to-PREPARE passage unverified; this is a documented source-contract uncertainty, not a reproduced runtime failure.

**Revised STUDY reviewed:** 112 lines, SHA-256 `e3c0b31577da5996b80af7b1896befec8491645b8d105ba9db505f550292ce8e`, against the same main commit `c20ec60909fa1aa15154bb6fdb3fdb71c421e10e`.

**History preserved:** The initial reviewed STUDY hash remains `a90b28e1dcfcdcb3286b8f620c2bf7725c8469c6dee5340ab150984a0f2ae6b4`. The entire pre-append review, including its seven findings, remains unchanged; its SHA-256 was `6d7cfca8d1f051887a357f4825eeebe5fe280026afc111a45d5ae29d385fabe9`. The initial verdict and next-action paragraph above describe the earlier revision; this appended verdict applies to the revised hash.

### Closure of the initial findings

| Initial finding | Revised STUDY evidence | Rereview disposition |
|---|---|---|
| 1. Universal research sealing | Lines 21, 76–78 distinguish path-specific contracts, new-v3 actor policy, no-contract finalization and research-only reception. | Closed as a documentation correction. |
| 2. Health check versus persisted 100% | Line 98 distinguishes REPORT progress, overall completed status, disabled checks, degradation and ignored assessment exceptions. | Closed as a documentation correction. |
| 3. Pipeline status versus publication | Diagram lines 29–32 and line 100 separate terminal state from publication and explain optional bilingual generation and variant bindings. | Closed as a documentation correction. |
| 4. RUN evidence and summary probe | Line 90 states persisted-bit/event alternatives, legacy platform inference and the generic JSON object/list probe. | Closed as a documentation correction. |
| 5. Optional artifacts/enrichments | Lines 62, 84, 88, 96 and 102 qualify manifests, ontology copies, graph enrichment, context/role production, charts and telemetry. | Closed as a documentation correction. |
| 6. Actor-roster digest boundary | Line 106 explicitly distinguishes the producer/parent multiplicity-map recipe from the context consumer's sorted-newline recipe and withholds a successful-passage claim. | Closed as a documentation correction; compatibility remains unverified. The fixture recipe is confirmed by text at test_actor_context_runtime.py:175–177 and :220, not by running a test. |
| 7. Original inaccurate anchors | Prior blank, closing-parenthesis, misplaced range-end and stale-comment targets have been replaced with relevant source locations. | The original anchor defects are addressed. Some added anchors would benefit from the precision notes below; they do not reopen the corrected lifecycle claims. |

### Remaining factual corrections in the additions

**R1 [P2] — “the backend explicitly passes v3” overstates engine selection (STUDY line 80).**

The direct bridge CLI's unset/empty-engine default is correctly identified as legacy at deerflow_research.py:16381–16400. The backend explicitly supplies the **selected canonical engine**, which can be legacy: P:5937–5952 selects legacy for a required actor plane; P:11983 and :12074 pass that selection to the runner; [P:2295–2301](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/pipeline_orchestrator.py:2295) also forces legacy for evidence-only or synthesis-manifest invocations before setting the child environment.

Replace the relevant clause with:

> The direct bridge CLI has a different unset-engine default—legacy—while the backend explicitly passes its selected canonical engine, v3 by default; required sealed-actor runs and legacy-only lane contracts select legacy.

This preserves the default distinction without contradicting line 76 or excluding supported legacy backend invocations.

**R2 [P2] — “otherwise Kuzu” omits the terminal availability condition (STUDY line 86).**

[graphiti_client/runtime.py:290–302](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/graphiti_client/runtime.py:290) selects FalkorDB when `FALKORDB_HOST` is set, otherwise probes `redislite.async_falkordb_client`, then probes `kuzu`. If neither import probe succeeds, it raises `RuntimeError` with “No local graph backend available”; it does not unconditionally select Kuzu. The study correctly says this is configuration/import selection rather than connection-failure retry.

Replace the selection sentence with:

> GRAPH_BACKEND=auto selects FalkorDB when FALKORDB_HOST is set, otherwise import-discoverable FalkorDBLite, otherwise import-discoverable Kuzu; if none is available it raises a no-backend error. This is configuration/import selection, not a connection-failure retry cascade.

### Added-claim and anchor check

All **85 source-anchor occurrences** in the revised study were resolved against the frozen files during this rereview. This included the additions; no other area report was used as verdict evidence. The phase sequence, shared evidence/tools, local Graphiti facade, lazy local embeddings, checkpoint/reuse distinction, diagnostic/no-update labeling and fixture recipe are supported by the source already read. The added module-index count also matches the source/inventory: **146 files and 151,957 lines**, with all 146 index rows matching their inventory paths/counts.

Several anchors are relevant but broad or point at a constant/comment rather than the exact behavior. These are precision improvements, separate from R1/R2:

- **Line 80:** Add linear_research.py:2674–2729 for numerical/fetched-page note verification, :4485–4499 for investigator fan-out, :4808–4828 for section writers and :5166–5192 for persisted QA. The existing :4186–4196 supports the phase order. Add P:2295–2301 for the corrected backend-engine wording.
- **Line 86:** embedder.py:43 defines the default model only. Use [embedder.py:205–251](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/graphiti_client/embedder.py:205) for lazy model/cache construction and :284–339 for cache use. client.py:349–357 and runtime.py:283–305 are appropriate for the facade and selector.
- **Line 88:** P:12931 is a continuation of the fingerprint comment; :12933–12938 directly anchors PREPARE completion after resealing. The behavior is correctly described.
- **Line 92:** run_parallel_simulation.py:3737 is a separator before an older checkpoint comment. Prefer :3752–3757 and :3802–3849 for checkpoint flags/storage, :4792–4807 and :4838–4851 for resume, :4692/:5228 for platform functions and :5920–5936 for the dual-platform dispatch. decision_channel.py:631 concerns elicitation fan-out; [decision_channel.py:733–764](/tmp/drf-main-study-c20ec60-20261011/source/backend/app/services/decision_channel.py:733) directly supports validity, forecast-effect policy and `elicited_model_projection`. The study does not adopt the old comment's checkpoint-default claim or claim uninterrupted-run equivalence.
- **Line 106:** The existing entry points are relevant. For the exact comparisons, P:5407–5413, actor_context.py:1275–1279 and test_actor_context_runtime.py:175–177/:220 are more precise.

### Rereview limits and preservation

This was the continuation of the already-requested rereview, not a new audit. The source checks completed before interruption remain the evidence receipts. After the mirror was removed and restored, those receipts and the exact-commit Git blobs remained the authority; completed reading was not repeated. The restored mirror is a convenience copy, not a new source version.

No application imports, execution, tests, provider calls, installs, source edits, saved-run inspection, external branches or subagents were used. The fixture was read only as source to verify the newly added fixture-description claim. Coverage receipts, completed area reports and implementation quality remain outside this verdict.

Only this appendix to `independent-review.md` was written. No earlier finding or hash was removed or rewritten, and `STUDY.md` was not edited. The remaining study-owner action is the two wording corrections above; no runtime change is requested.



---

## Final closure — R1/R2, 2026-10-12 Asia/Shanghai

**Final verdict:** R1 and R2 are closed as documentation corrections. No material factual correction remains open from this review of the synthesized spine at the final reviewed hash.

**Final STUDY reviewed:** 116 lines, SHA-256 `82f7db7e813ce9ab839b7f2d670086fe8c7dd548967bf7d274619708bad89d56`, against main commit `c20ec60909fa1aa15154bb6fdb3fdb71c421e10e`.

- **R1 closed:** The direct-CLI/backend sentence now says the backend explicitly passes its selected canonical engine, v3 by default, and identifies required sealed-actor runs and legacy-only lane contracts as legacy selections. This matches the already-read P:5937–5952, :11983/:12074 and :2295–2301, together with deerflow_research.py:16381–16400.
- **R2 closed:** The graph-selection sentence now conditions Kuzu on import discovery and states the no-backend error. This matches the already-read graphiti_client/runtime.py:283–302; the sentence retains the correct distinction between selection and connection-failure retry.
- **Anchor precision incorporated:** The revised references now identify numerical note verification, investigator fan-out, section writing/QA, explicit child-engine selection, lazy embedding/cache behavior, PREPARE completion, checkpoint/resume/dispatch and decision-channel policy at the previously identified blocks. The actor-digest qualification remains supported and does not claim successful producer-to-PREPARE passage.

**Coverage paragraph check:** The final paragraph accurately reports the parent `coverage-validation.json`: source commit c20ec60, nine receipt hashes, 146/146 scoped files, 151,957 scoped source lines, 180 backend tests indexed, 12 full test reads, 15 partial test reads, and empty missing-file/error arrays. The distinction between reported read scope and runtime acceptance is explicit. This closure verifies correspondence to that parent receipt; it does not claim this independent reviewer personally read every scoped file or reran the parent's coverage-validation process. No area report was used to replace source evidence for a behavioral claim.

**History and limits:** This pass checked only the requested wording, anchor refinements and coverage statement against completed source-reading receipts and the parent coverage summary. It did not repeat the broad study, diagnose runtime, import the app, run tests/providers/installations, inspect saved runs or external branches, or change source/STUDY. The actor-roster digest discrepancy remains an explicitly documented compatibility uncertainty.

The complete review before this appendix is retained byte-for-byte: 33,320 bytes, SHA-256 `ef49175f8d5b7e4917f40d14fddc5d9d2c32f164a3066f39e89655f486447311`. Earlier findings, reviewed hashes and intermediate verdicts remain historical records; this final closure supersedes their remaining-action statements for the final STUDY hash. Only this appendix to `independent-review.md` was written.
