# Translation redesign delivery ownership audit

**Status:** Ownership audit complete; parent freeze, isolated acceptance, commit and push pending.
**Capture:** 2026-10-26T04:14:49Z, `claude/sim-provenance-s0`, HEAD `6ab52f7746bf7ec55e9f9921c71ba4ab08e33c01`.

Only this document and private proposal files were written. No application source, saved report, Git metadata, index, ref, branch or managed worktree was modified by this audit. No network, provider, service, test suite, commit or push was run. The parent-owned topic handoff and worker records remain separate authorities for implementation and acceptance.

## Decision and evidence

Deliver from the **parent-created managed worktree rooted at the exact HEAD**, applying a reviewed HEAD-to-proposal patch. The parent has authorized app operation `3b553930-4a1f-478e-9199-130e69f39957` at `6ab52f77`. A managed worktree has its own index and HEAD while sharing Git objects/refs; that isolation satisfies the parent's delivery requirement. The earlier independent-clone recommendation is superseded, not an approval gate. A baseline-to-current patch alone is insufficient: the baseline already contains uncommitted translation infrastructure required by the redesign. Whole-file staging of mixed files would instead include unrelated work.

The private review bundle is `/private/tmp/drf-translation-delivery-audit-3kv6swgt/`:

- `manifest.json`: captured HEAD/current/baseline hashes, staged path, index digest and sanitized remote identities.
- `allowlist.txt` / `allowlist.nul`: the historical 102-path source/test/package proposal; repeated below. The parent additions section extends ownership, but these private lists and the patch have not yet been refreshed.
- `translation-scope.patch`: HEAD-to-proposal patch, SHA-256 `0ac2767353abf8ffb1255163e671f0b527cee670e2bf3eea54a5d4cc30ac7dd2`.
- `exclude-from-capture.patch`: exact inverse hunks to omit from the captured current files, **for inspection only; never apply to the shared checkout**.
- `exclusions.json`: 81 excluded symbols/layout edits with baseline/head/capture coordinates and CSS before/after text. `proposal-hashes.json` records the resulting file bytes.
- `compute_proposal.py`: deterministic, fail-closed computation from private `head/`, `current/`, the saved baseline and `manifest.json`. It writes private proposal artifacts only; it does not refresh the capture or modify Git.
- `proposal-checks.json` and `relative-module-check.json`: static verification. The patch passes `git apply --check` against the private captured HEAD files; all 56 Python files parse; added/current relative application and frontend module paths resolve against HEAD plus the allowlist. This does not establish runtime imports, signatures, test success or release readiness.

The capture is **not a coordinated source freeze**. Later comparison found concurrent changes in `model_translation.py`, `report_agent.py`, `translation/engine.py`, two browser backend fixtures, the native PDF fixture and `test_report_viz_and_pdf.py`. The parent must recapture after all workers finish, review any new paths and recompute the proposal before acceptance. Existing worker greens tested the combined dirty tree and cannot certify the extracted commit.

## Exact unrelated prior changes to exclude

### Report agent

Restore these nodes to HEAD **in the delivery proposal only**, deleting nodes absent from HEAD. The generator verifies each excluded node still equals the saved baseline before restoring it, so a later overlapping edit stops extraction. Decorators are included in the node spans. Ranges below refer to the fixed saved baseline, not shifting current line numbers.

| Symbol | HEAD lines | Saved baseline lines |
|---|---:|---:|
| `ReportAgent.__init__` | 2819–3021 | 2819–3022 |
| `ReportAgent._bound_forecast_task_snapshot` | absent | 5154–5189 |
| `ReportAgent._temporal_horizon_date` | 5153–5176 | 5191–5217 |
| `ReportAgent._simulation_anchor_inputs` | 5483–5534 | 5524–5582 |
| `ReportAgent._grounding_inline_signature` | absent | 6342–6356 |
| `ReportAgent._grounding_inline_units` | absent | 6358–6391 |
| `ReportAgent._grounding_flat_list_lines` | absent | 6393–6418 |
| `ReportAgent._grounding_markdown_blocks` | absent | 6420–6475 |
| `ReportAgent._repair_final_quantitative_grounding` | 6294–6542 | 6477–6827 |
| `ReportAgent._repair_overused_citations` | 7269–7369 | 7554–7704 |
| `ReportAgent._REGROUND_CANDIDATE_LIMIT` | absent | 7706–7706 |
| `ReportAgent._reground_citation_tag` | absent | 7708–7731 |
| `ReportAgent._audit_numeric_consistency` | 7886–7925 | 8248–8280 |
| `ReportAgent._enforce_final_publish_audit` | 11976–11989 | 12393–12407 |
| `ReportAgent._apply_publish_gate` | 12901–13062 | 13319–13483 |

This removes both `_bound_forecast_task_snapshot` and its constructor, temporal-horizon, simulation-anchor and final-publication call sites; all four new `_grounding_*` helpers and the rewritten quantitative-grounding method; citation re-grounding plus `_REGROUND_CANDIDATE_LIMIT`; the `scenario_claim_probabilities` dependency; and the `_SCENARIO_RESIDUAL_TERMS` local import/change in `_apply_publish_gate`. Keep the HEAD versions of existing behavior. Do not deliver `forecast_task.py`, `forecast_extractor.py` or `report_lint.py` to satisfy those excluded references.

**Imports/constants were checked as well as methods.** At this capture the sole changed module-level import is `import tempfile`, required by PDF staging. No extra unrelated module-level import was found. Retain translation constants `_FORECAST_FACT_ATOMS_RE`, `_TRANSLATOR_VERSION = "model-translation/v1"`, the translation fact/unit imports and related fact-preservation methods. Remove `_REGROUND_CANDIDATE_LIMIT` with its callers. Do not discard all uppercase constants or all local imports. Retain the new `generate_report` automatic shared-scheduler enqueue change; it is translation ownership.

### Actual-source PDF repair ownership (latest parent direction)

Include the report worker's `_PDF_WIDE_TABLE_FILTER` class constant as trusted Lua text, `_PDF_RENDERER_VERSION`, the filter hash in `_pdf_renderer_fingerprint`, `_pdf_visible_url_label`, `_pdf_visible_url_carriers`, related Markdown/content-validation helpers and PDF render/export changes. The `pdflscape` header and render-time temporary Lua file creation are owned. There is no additional repository Lua source file to add. Preserve the actual relevant imports; uppercase naming is not an exclusion criterion. The unrelated `_REGROUND_CANDIDATE_LIMIT` remains excluded by its exact identity only.

The policy now has an explicit `report_preserve_pdf_nodes` list of14 class members. The generator checks that these nodes and current module-level imports survive extraction unchanged. A private negative control deleting the PDF Lua constant is rejected. The targeted ownership check used current report source SHA-256 `ded605854262639ace22ad76dc01168c8749857cd9adea8f72ced3ef28a09bf0`; this is a moving candidate observation, not the final freeze or native acceptance. Receipt: `/private/tmp/drf-translation-delivery-audit-3kv6swgt/pdf-ownership-checks.json`.

Parent-reported status supersedes older freeze language in worker notes: copper recovered22/22 sections with21 reused and2 body calls, but both English and Mandarin PDF requests returned503 despite earlier native-fixture success. The diagnosed actual-content defects are eight-column overlap and false rejection of a wrapped URL identifier. The native verifier is retesting private actual source. Parent also reports25 passing migrated-test cases,11 passing ladder cases and495 passing delivery-worktree frontend cases. Its broad run reported941 passes and15 old-fixture failures, now corrected on source; a final rerun is pending. These counts are attributed to the parent and were not rerun or independently certified by this audit. Prior fixture/native success and earlier report-worker401-case acceptance do not prove the current real-source PDF fixes or final extracted tree.

The PDF gate was subsequently advanced by the parent: actual live English/Mandarin endpoints reportedly return200 with35/28 pages and source preserved. The remaining extracted-tree failure is the classifier dependency described below. A refreshed proposal may now include that correction; final acceptance still requires the parent's affected/classifier rerun and final verification record. Earlier PDF failures remain historical evidence, not current unresolved claims.

### Simulation API

Exclude the prior `WORLD_STATE_MAX_ARBITER_ATTEMPTS` constant (baseline 2150), `_safe_world_record_attempts` helper (baseline 2154–2217), and `arbiter_attempts` mapping (baseline 2424; captured current 2421). The last line moved into the new `_read_simulation_world_state` reader, so deleting only the old helper leaves a dangling call. The private proposal removes all three together. Keep `_WorldStateReadError`, `_read_simulation_world_state`, the thin GET wrapper, translation source/projection helpers and the POST/GET translation route changes. The HEAD world-state behavior is preserved apart from the translation-required reader extraction.

### Frontend layout

Exclude all changes in `ResearchView.vue` and `StageTimeline.vue`. In the allowlisted components, omit preexisting width/padding/grid/radius/font/shadow/table-layout changes from `BinaryForecastTable`, `DossierViewer`, `ForecastReport`, `SimulationRecordView`, `SimulationView`, `WorldSimulationView` and `WorldStatePanel`. The exact 63 CSS edits are in `exclusions.json` and the inverse patch. Keep language bindings, shared-observer migration, source admission, source inventories and translation-specific styles, including scenario-driver display styles. The generator retains all post-baseline CSS changes and fails if an excluded baseline edit overlaps a redesign edit.

### Whole-path exclusions

Keep these at HEAD in the delivery worktree: `actor_context.py`, `agent_decision.py`, `forecast_task.py` (absent at HEAD), `forecast_extractor.py`, `graphiti_client/embedder.py`, `news_market_context.py`, `ontology_generator.py`, `pipeline_orchestrator.py`, `report_lint.py`, `simulation_config_generator.py`, `simulation_manager.py`, `simulation_runner.py`, `world_update.py`, `utils/dates.py`, the modified simulation/demo scripts except the explicitly allowed export-reader hunks below, `test_calibration_rigor.py`, `test_forecast_extractor.py`, and `test_report_lint_citations.py`. Also omit `.env.example`, preexisting README changes outside the newly approved workflow paragraphs below, root `handoff.md`, unrelated entries in `feature_list.json` and `agent-progress.txt`, unrelated handoffs, demo/site assets, `newskills/`, saved reports, uploads, databases, build output and caches. The default for every path not expressly allowlisted is exclusion; do not clean or reset these files in the source checkout.

## Required preexisting dependencies to carry forward

| Dependency | Why it belongs |
|---|---|
| Entire current `model_translation.py` plus seven `services/translation/` modules and generic API/startup registration | The facade, parser, receipt validation, durable engine/store/service, scheduler, publication and authorized controls form one dependency chain. The facade did not exist in HEAD. |
| Translation portions of `report_agent.py`, report/research APIs, `artifact_translation.py`, `translation_tools.py`, graph/simulation APIs | Existing model-v1 audit/read contracts, exact-source admission, structured-field translation and shared client admission are foundations of v2. Include the related baseline work as reviewed dependencies, not only new v2 lines. |
| `translation_quantities.py` and translation numeric/date regression changes | Existing signed/mixed-unit quantity preservation supports retained report translation admission. `translation_dates.py` itself is already in HEAD; the unrelated `utils/dates.py` calendar work is excluded. |
| `backend/app/utils/llm_errors.py` only the five-line ambiguous rate-circuit guard/comment | Required by the extracted HEAD-only failure in `test_mandarin_numeric_integrity::test_rate_circuit_is_not_a_content_filter_or_a_publishable_translation`; preserve real moderation handling while rejecting ambiguous cooldown text as moderation evidence. |
| `feed_rounds.py` only its `Path` import and canonical read-only SQLite URI change | The actual OASIS translation projection consumes this reader; the worker evidence explicitly identifies this narrow fix as required for guarded acceptance. |
| `mistune>=3.3.4,<4` in pyproject/requirements and two root dependency edges in `uv.lock` | `model_translation.py` imports Mistune directly. These four added lines are already in the saved unstaged patch and are the entire current dependency diff. The Mistune package record already exists in the HEAD lock. |
| Frontend translation API envelope, language props in `BinaryForecastTable`/`SourceContextPanel`, all observer/adapters/status/export and record helpers | Required for the new consumers to compile and use the correct language and resource identity independently of the dirty baseline. |
| Existing translation fakes, new/updated translation tests and frontend test harness imports | Do not omit untracked baseline `model_translation_fakes.py`, model/pair/artifact tests, `reportMandarinConsumers`, `simulationMandarinTranslation`, or `simulationTranslationHarness` just because they predate v2. |

**h2/provider boundary:** `h2>=4.1.0` and its root lock edges are already in HEAD. There is no uncommitted h2 hunk in either saved dependency patch or this capture. Keep inherited HEAD content; do not stage other provider work or fabricate an h2 removal. **Correction from the extracted HEAD-only gate:** the five-line `utils/llm_errors.py::is_content_filter_error` guard for the ambiguous `422/429` plus `熔断冷却` message is a required related baseline dependency. The earlier exclusion was incorrect: static module-path closure did not establish semantic compatibility. The generator now reconstructs HEAD plus only that exact guard/comment and rejects any other file changes. All other unrelated provider changes remain excluded.

## Captured source/test/package allowlist (before parent additions)

Full file content may be used only for paths not identified above as mixed. For mixed paths, use the computed proposal bytes. Browser/native fixture files are provisional until their owners freeze; their presence here is scope approval, not acceptance.

```text
backend/app/__init__.py
backend/app/api/graph.py
backend/app/api/report.py
backend/app/api/research.py
backend/app/api/simulation.py
backend/app/api/translations.py
backend/app/services/artifact_translation.py
backend/app/services/feed_rounds.py
backend/app/services/model_translation.py
backend/app/services/report_agent.py
backend/app/services/translation/__init__.py
backend/app/services/translation/artifacts.py
backend/app/services/translation/contracts.py
backend/app/services/translation/engine.py
backend/app/services/translation/scheduler.py
backend/app/services/translation/service.py
backend/app/services/translation/store.py
backend/app/services/translation_quantities.py
backend/app/services/translation_tools.py
backend/pyproject.toml
backend/requirements.txt
backend/tests/fixtures/translation_browser_documents.py
backend/tests/fixtures/translation_browser_server.py
backend/tests/fixtures/translation_browser_simulations.py
backend/tests/fixtures/translation_job_v2_child.py
backend/tests/model_translation_fakes.py
backend/tests/render_translation_pdf_fixture.py
backend/tests/test_artifact_translation_model.py
backend/tests/test_artifact_translation_restart.py
backend/tests/test_artifact_translation_review_regressions.py
backend/tests/test_artifact_translation_routes.py
backend/tests/test_artifact_translation_services.py
backend/tests/test_artifact_translation_structured_job.py
backend/tests/test_mandarin_numeric_integrity.py
backend/tests/test_model_translation_core.py
backend/tests/test_model_translation_workflow.py
backend/tests/test_overlay_durable_redesign.py
backend/tests/test_report_bilingual.py
backend/tests/test_report_bilingual_filter_safe.py
backend/tests/test_report_durable_publication.py
backend/tests/test_report_durable_routes.py
backend/tests/test_report_forecast_localization.py
backend/tests/test_report_viz_and_pdf.py
backend/tests/test_research_dossier_translation.py
backend/tests/test_research_durable_routes.py
backend/tests/test_sessionb_translation_reallm.py
backend/tests/test_sessionb_translation_structure.py
backend/tests/test_translation_action_admission.py
backend/tests/test_translation_artifact_generations.py
backend/tests/test_translation_core_review_regressions.py
backend/tests/test_translation_dates.py
backend/tests/test_translation_job_v2.py
backend/tests/test_translation_ladder.py
backend/tests/test_translation_pairs_admission.py
backend/tests/test_translation_pairs_integrity.py
backend/tests/test_translation_quantities.py
backend/tests/test_translation_recovery_integrity.py
backend/tests/test_translation_robustness.py
backend/uv.lock
frontend/src/api/report.js
frontend/src/api/research.js
frontend/src/api/translations.js
frontend/src/components/GraphPanel.vue
frontend/src/components/TranslationJobStatus.vue
frontend/src/components/research/BinaryForecastTable.vue
frontend/src/components/research/DossierViewer.vue
frontend/src/components/research/ForecastReport.vue
frontend/src/components/research/SimulationRecordView.vue
frontend/src/components/research/SimulationView.vue
frontend/src/components/research/SourceContextPanel.vue
frontend/src/components/research/WorldSimulationView.vue
frontend/src/components/research/WorldStatePanel.vue
frontend/src/composables/useTranslationJob.js
frontend/src/utils/dossierTranslationAdapter.js
frontend/src/utils/forecastTranslationAdapter.js
frontend/src/utils/overlayTranslation.js
frontend/src/utils/pdfDownload.js
frontend/src/utils/simulationRecordTranslation.js
frontend/src/utils/translationJobAdapter.js
frontend/tests/browser/BrowserHarness.vue
frontend/tests/browser/build.mjs
frontend/tests/browser/index.html
frontend/tests/browser/main.js
frontend/tests/dossierOfficialData.test.mjs
frontend/tests/dossierTranslationEnvelope.test.mjs
frontend/tests/dossierTranslationObserver.test.mjs
frontend/tests/forecastReportOfficialData.test.mjs
frontend/tests/forecastReportPartialTranslation.test.mjs
frontend/tests/forecastReportProvenance.test.mjs
frontend/tests/forecastTranslationObserver.test.mjs
frontend/tests/graphTranslationObserver.test.mjs
frontend/tests/reportMandarinConsumers.test.mjs
frontend/tests/researchWorldAdmission.test.mjs
frontend/tests/sfcHarness.mjs
frontend/tests/simulationMandarinTranslation.test.mjs
frontend/tests/simulationRecordTranslation.test.mjs
frontend/tests/simulationRecordView.test.mjs
frontend/tests/simulationTranslationHarness.mjs
frontend/tests/sourceContextPanel.test.mjs
frontend/tests/translationJobObserver.test.mjs
frontend/tests/world-simulation.test.mjs
frontend/tests/worldStatePanel.test.mjs

```

Documentation is separately reviewed. Include only the newly approved README paragraphs described below. Suggested exact handoff additions are `docs/handoff/translation-hardening-pdf/{handoff.md,PLANS.md,architecture.md,integration-contract.md,worker-frontend.md,worker-reports.md,worker-overlays.md,delivery-scope.md}` plus the parent's final validation record once named and reviewed. Do not recursively add the handoff directory or private evidence. This audit patch intentionally contains no documentation.

## Parent additions to the final scope (refresh after freeze)

This addendum records the parent's subsequent ownership instruction. It extends the delivery scope and supersedes the earlier whole-path exclusions for the named export/README hunks and the executive-brief ownership limit. **The historical 102-path private allowlist, patch, hashes and static-check receipts remain unchanged.** They do not yet contain these additions. The historical `compute_proposal.py` omits the new production/documentation paths. The new `refresh_proposal.py` and explicit `delivery-policy.json` described below implement the expanded capture and splitting rules.

| Additional path | Exact allowed scope | Exclusions / freeze requirement |
|---|---|---|
| `backend/scripts/export_demo_site_data.py` | Immutable-generation reading in `published_report_variants`; `published_dossier_variants` with optional keyword-only `pipeline_id`; the `export_dossier` call forwarding `pipeline_id=RUNS.get(key)` and the `refresh_demo_reports` preflight call forwarding `pipeline_id=pipeline_id`; imports required inside the two reader helpers. Reconstruct both callers from HEAD with only their exact call replacements. | Preserve HEAD `RUNS`. Exclude the preexisting `copper-2027` / `bitcoin-2027` additions and their comment, plus any unrelated provenance/source, run-selection or demo publication changes. Never take this whole file. |
| `backend/tests/test_translation_export_consumers.py` | New static-export consumer regressions for admitted translated generations and stale-pointer rejection. | Capture the final parent-owned test file after freeze and run it against the extracted delivery tree. |
| `backend/tests/test_translation_export_integrity.py` | Reviewed durable regressions for invalid-pointer precedence, post-resolution invalidation, dossier forwarding, and generation-only refresh preflight discovery. | Explicitly allowlisted and required at final capture; run only through the parent-owned guarded delivery gate. |
| `backend/app/services/exec_brief.py` | Report-worker adaptation from literal translated sidecars to admitted immutable generations, with required source/generation cache binding and legacy compatibility. | Ownership is approved; implementation bytes and exact hunks are not frozen or certified by this note. Include only the translation-consumer/cache adaptation. |
| `backend/tests/test_exec_brief.py` | Report-worker regression cases and fixture changes needed for generation-backed translated brief reads, cache identity and stale/deleted/failed-refresh behavior. | Include only changed translation-related cases after worker freeze; existing unchanged cases remain inherited from HEAD. |
| `backend/tests/test_exec_brief_sim_disclosure.py` | Report-worker translation-consumer compatibility cases, if this existing test file is modified for the adaptation. | This is a bounded test-scope reservation, not a claim that new cases are already present. No unrelated simulation/provenance changes. Any differently named new test file requires an explicit recorded addition at freeze. |
| `README.md` | The two new paragraphs beginning `Translation jobs now share one durable service` and `Both report PDF controls name the admitted language` (observed lines 1742 and 1744). | Keep only these v2 workflow/PDF paragraphs. Exclude the preexisting concurrency configuration row and the two earlier model-v1/control paragraphs at this delivery boundary. |
| `README.zh-CN.md` | Matching two paragraphs beginning `研究档案、预测报告、图谱` and `两类报告的 PDF 按钮` (observed lines 1742 and 1744). | Same narrow paragraph boundary as English; exclude prior README additions. Use text anchors, not shifting line numbers. |

Read-only inspection confirms the current exporter diff contains the two reader migrations and both forwarding calls, while the saved baseline patch contains the unrelated three-line `RUNS` addition. Those baseline run entries are not prerequisites for generation resolution: the forwarding call uses the existing `RUNS` mapping. The user additionally identifies unrelated provenance/source work as excluded even if it appears in a later freeze. The current README diff combines old and new paragraphs in one Git hunk, so `git add -p` at whole-hunk granularity is insufficient; construct the README proposal from HEAD plus only the two anchored paragraphs per language.

For the exporter, construct the final candidate from HEAD plus the reviewed helper changes and the two exact forwarding calls; compare every other top-level function/assignment/import to HEAD and reject unrelated changes. Do not infer ownership of an entire function if later edits mix in provenance/source work. For the executive brief, compare both HEAD and the saved baseline before extracting the worker's final adaptation. Parent acceptance must cover the exporter with existing RUNS keys and generation-backed report/dossier outputs, and public brief reads with stale/deletion/failed-refresh negatives. This audit does not run the exporter or publish site data.

At freeze, generate the final exact changed-path allowlist from the historical scope plus these approved additions, omitting unchanged reserved tests. Recompute patch/hash/module/syntax checks, run the parent's isolated acceptance on the resulting tree, and only then proceed with the existing delivery recipe. That addendum initially changed only this note. The subsequent private refresh below includes these additions; no Git mutation or production edit is performed by the audit.

## Diagnostic documentation and private evidence boundary

The parent explicitly approved `docs/handoff/translation-hardening-pdf/diagnostic-probes.json` and `docs/handoff/translation-hardening-pdf/saved-failure-evidence.json` because the active plan/architecture link them. Both are exact policy entries and required capture inputs. The parent reports having inspected them as compact hashes/counts/structural signatures and generic diagnostics without source bodies or credentials; this audit checked that both parse as JSON without printing their contents.

`docs/handoff/translation-hardening-pdf/verification.md` has now been created and is an explicit required capture input. Its earlier optional reservation is closed; final capture fails if it is missing. The two approved JSONs remain exact required paths. No wildcard or recursive JSON inclusion is enabled.

The parent reports archiving full verification artifacts privately at `/Users/rogerlin/Documents/Codex/evidence/translation-redesign-2026-10-26`. The forthcoming verification Markdown may summarize counts/hashes and point to that vault; the vault itself, raw baseline, full reports, and the 1,878-artifact preservation inventory are outside the delivery allowlist. This audit neither copies nor inspects the vault.

## HEAD-only semantic dependency correction

The parent reports a final extracted-tree run with **965 passed and1 failed**, specifically `test_mandarin_numeric_integrity::test_rate_circuit_is_not_a_content_filter_or_a_publishable_translation`. That test directly checks the shared error classifier and then verifies an unavailable provider cannot produce a publishable translation. The working source's entire diff for `backend/app/utils/llm_errors.py` is the related five-line guard/comment; no unrelated provider edit is needed. The preceding broad successes and static import checks did not prove this semantic dependency was absent.

Include this exact insertion before the generic422 branch in `is_content_filter_error`:

```python
    # This shared circuit message covers quota/rate failures as well as moderation.
    # It gives no evidence that content was rejected; do not send every paragraph
    # through the content-filter retry ladder during a rate-limit cooldown.
    if "422/429" in low and "熔断冷却" in low:
        return False
```

The file is explicitly allowlisted and required at capture. The generator verifies its complete current content equals HEAD plus this insertion, preventing other provider changes from entering. The existing regression file is already included. The parent owns copying/applying the scoped change in the delivery worktree and rerunning the failing scenario plus error-classifier controls. This audit records the reported965/1 result as the red evidence; it does not claim a green rerun. Actual live PDF200/35-page English and200/28-page Mandarin results and source preservation are also parent-reported, not HTTP probes performed here.

## Final project metadata and remote destination

`feature_list.json` is narrowly included for `fix_full_mandarin_translation` only. The generator takes that exact source entry with `passes: true`, checks its non-status specification against the saved baseline, and either replaces the same ID in HEAD or appends it to the HEAD array if absent. Current HEAD lacks the entry, so this delivery appends it. Every other HEAD feature entry remains byte-identical and in its original order; unrelated current entries or flag changes are discarded from the proposal.

`agent-progress.txt` is narrowly included for the single new heading `### 2026-10-26T06:42:44.884884+00:00 — translation redesign (delivery branch codex/translation-redesign)` and its entry body. The generator checks that it is new relative to both baseline and HEAD, then appends it to the exact HEAD prefix. Earlier unrelated progress edits/appends are excluded. Selection is bound to the2026-10-26 translation-redesign heading and the owned feature ID, allowing the parent's final text under that entry to be copied verbatim. No other progress history is rewritten.

The parent has selected **the existing configured `legacy` remote, `github.com/linroger/DeepResearchForecast.git`, and a new delivery branch**. The parent reports that `origin` is archived and that GitHub API verification confirmed the exact base commit on the active repository. Do not alter remote configuration, push to origin, or treat this local audit as the remote verification. The two preexisting demo-asset gaps are parent-tracked at `https://github.com/linroger/DeepResearchForecast/issues/9`; no extra asset/demo edits or site publication belong in this delivery.

The parent reports all functional/current-test/live verification complete, including actual English/Mandarin PDFHTTP200 and only the intended target report metadata extension. The five-line classifier dependency, metadata selectors, final verification Markdown and two safe JSONs are now represented in the policy. This audit's final readiness check is extraction/static evidence only; the parent owns the final capture, hash/method-scope comparison, commit and push. Policy documentation is frozen after this entry unless the parent requests another scope change.

## Reproducible refresh and exclusion checks

The stable generator is `/private/tmp/drf-translation-delivery-audit-3kv6swgt/refresh_proposal.py`, with explicit sibling policy `delivery-policy.json`. It only reads the source checkout and writes a new private output directory outside every checkout. Its Git commands are read-only; `git apply --check` runs only against captured HEAD files under the private output. It never applies, stages, commits, creates a worktree, starts services or runs application tests.

The policy now names 136 explicit required/current input paths; `verification.md` now exists and is required: the historical 102, parent additions, all nine current browser harness files (including `run-all.mjs` and `run-isolated.mjs`), 14 existing topic Markdown documents, the two specifically approved diagnostic JSONs, the final verification summary, and the two narrowly extracted project-metadata files. It explicitly includes `backend/tests/render_translation_pdf_fixture.py`, `backend/tests/test_exec_brief_generations.py`, `backend/tests/test_translation_export_consumers.py`, `backend/tests/test_translation_export_integrity.py` and the three `translation_browser_*` backend fixtures. Unchanged reserved executive-brief tests produce no patch entries. Only `diagnostic-probes.json` and `saved-failure-evidence.json` are included as topic JSON. The 1,878-artifact `preservation-before.json` inventory, baseline-status/raw baseline files, private full reports and the evidence vault remain excluded. New files in translation/browser/executive-brief/topic ownership areas stop capture for explicit policy review rather than being silently omitted or broadly included.

`capture` verifies the exact base and records primary HEAD/branch/index/staged-diff identity, file bytes/modes and hashes before/after. `replay` uses only a saved bundle and its copied generator/policy; it must reproduce the same patch hash without rereading the live source. `verify-source` is read-only and exits unsuccessfully if captured files or primary Git identity changed. Every output path must be absent. Commands for the parent after coordinated freeze:

```sh
generator=/private/tmp/drf-translation-delivery-audit-3kv6swgt/refresh_proposal.py
proposal_dir=/private/tmp/drf-translation-delivery-latefreeze-01
python3 -B "$generator" capture   --source /Users/rogerlin/Downloads/DeepResearchForecast   --baseline /private/tmp/drf-translation-v2-baseline-p0z616cz   --output "$proposal_dir"
python3 -B "$proposal_dir/refresh_proposal.py" replay   --bundle "$proposal_dir"   --output /private/tmp/drf-translation-delivery-latefreeze-01-replay
python3 -B "$proposal_dir/refresh_proposal.py" verify-source --bundle "$proposal_dir"
```

Read `capture.json`, `allowlist.txt`, `proposal-hashes.json`, `exclusions.json`, `exclusion-checks.json` and `proposal-checks.json`. The exact delivered path list contains only files different from HEAD, including README/topic docs. `exclude-from-capture.patch` remains an inspection artifact and must never be applied in the primary checkout.

The generator restores the 15 excluded report nodes only if they still match the saved baseline, removes the simulation arbiter helper/constant/call together, and separates the prior CSS edits. Exporter output is reconstructed from HEAD with just the two reader functions and the two verified forwarding-call replacements in `export_dossier` and `refresh_demo_reports`; its other symbols, imports and RUNS remain HEAD bytes. README output is HEAD plus the two anchored paragraphs. Package output is HEAD plus only Mistune declarations/root lock edges, regardless of other peer dependency edits. `feed_rounds.py` is HEAD plus only the Path import and read-only URI correction. Executive-brief inclusion requires its saved baseline to equal HEAD and the generation adapter to be present. These predicates are recorded in `exclusion-checks.json`.

Fresh proposal snapshots are bounded ownership evidence, not a substitute for the parent declaring the source frozen. The capture/replay checkpoints under `/private/tmp/drf-translation-delivery-refresh-20261026-*` are provisional; use the final late-freeze bundle for application verification. The generator copies its own exact source and policy into each bundle so an old snapshot remains reproducible even after this stable generator evolves.

## Parent-only managed-worktree delivery recipe (not executed)

1. Wait for the report/browser/parent changes to finish and freeze the source. Run the capture, replay and source-verification commands above. If capture reports overlapping excluded edits, missing/new owned paths or changed HEAD, review the specific scope change and update the explicit policy/splitting rule; do not widen staging to entire directories. Preserve the completed frozen bundle and use its copied generator for replay.
2. Set `delivery` to the **workspace directory returned by the completed app operation** `3b553930-4a1f-478e-9199-130e69f39957`. This audit does not create or modify that worktree. Confirm its HEAD is `6ab52f7746bf7ec55e9f9921c71ba4ab08e33c01` and its index/worktree are initially clean before first application. A dedicated branch/commit in that worktree is the parent's responsibility. Do not switch or reset the primary checkout.
3. Apply the proposal only in the parent-selected worktree:

```sh
: "${delivery:?Set delivery to the managed workspace directory returned by the app}"
git -C "$delivery" rev-parse HEAD
git -C "$delivery" status --porcelain=v1
git -C "$delivery" apply --check "$proposal_dir/translation-scope.patch"
git -C "$delivery" apply --index "$proposal_dir/translation-scope.patch"
git -C "$delivery" diff --cached --check
git -C "$delivery" diff --cached --name-only
```

Compare the staged path list exactly to the bundle's `allowlist.txt` and all resulting bytes to `proposal-hashes.json`. README and topic Markdown are already included; do not recursively add the handoff folder. Do not run staging/reset/stash/checkout/commit operations in the primary checkout. The generator does not use a temporary source index or write Git objects.

4. Verify **HEAD plus this patch**, using the delivery worktree's manifests and isolated mutable/evidence roots. Do not borrow excluded dirty source or run fixtures through the primary application. The parent runs the guarded backend runner, frontend test/build, browser cases and native PDF fixture as applicable. `backend-test-paths.txt` inventories changed/new backend suites, but unchanged HEAD compatibility suites—including `test_exec_brief.py`, `test_exec_brief_sim_disclosure.py`, report publication/source-proof/read-only consumers—remain required where the parent's gate already specifies them. Current-dirty-tree acceptance does not transfer to HEAD-only extraction; missing dependency or compatibility failures must be resolved narrowly and the patch/receipts refreshed. This audit claims only static extraction checks.
5. After acceptance, the parent commits the prepared index in the delivery worktree and verifies its changed-path list and source hashes. A separate worktree index is sufficient for this chosen workflow. Shared Git object/ref updates are expected there and do not authorize changing the primary index or its branch. Never pass the primary index into a commit command.
6. After final capture/scope validation and commit, the parent pushes the new delivery branch explicitly to the existing `legacy` remote (`github.com/linroger/DeepResearchForecast.git`). The parent reports origin archived and the exact base commit verified through GitHub API. Make no remote-configuration change and do not push to origin. The primary branch had no configured upstream at audit capture; use the delivery branch/ref explicitly without force. This audit performs no network access or push.
7. Compare the primary HEAD/branch/index/staged-diff identity with `capture.json` after parent delivery; preserve its unrelated dirty/untracked work and saved reports. Verify the delivery worktree's own final state independently. A clean primary checkout is not a requirement and must not be manufactured by discarding others' work.

## Limits and next-session prompt

At the initial capture, the worker report flagged `exec_brief.py:819` as a literal historical translated-Markdown reader outside ownership. The parent has now assigned its immutable-generation adaptation and corresponding regressions to the report worker; the additions below supersede that earlier ownership limit. The report worker subsequently recorded its executive-brief closure, while the latest parent direction reopens the actual-source PDF renderer gate as described above. Final extracted-tree acceptance remains parent-owned. No wider consumer audit was performed here.

> Read this scope and the three worker records. Freeze the final source first, refresh the private capture and compute a HEAD-based proposal with the listed prior symbols/CSS excluded. Add only newly reviewed translation dependencies. Apply and validate in the parent-created managed worktree, preserve the primary index and all saved reports, then perform the parent's separately gated commit/push. Treat the static proposal checks as ownership evidence only.

## Updates

- 2026-10-26T04:14:49Z: Captured source/HEAD/hash evidence and sanitized local remotes; read all specified ownership contracts. Created this authorized audit document; the existing parent handoff was read without modification.
- 2026-10-26T04:22:27.856628+00:00: Completed symbol/import/constant/package and layout separation, generated the 102-path private proposal and exact exclusions, checked patch applicability/Python syntax/module-file closure, and recorded concurrent drift. Initial private generation stopped on changed indentation in the extracted simulation reader; corrected the private matcher to the captured 12-space mapping and revalidated. No production source was edited.

- 2026-10-26T04:28:01.237599+00:00: Recorded parent-owned static-export generation readers and tests, report-worker executive-brief adaptation/test scope, and the two new workflow/PDF paragraphs in each README. Narrowed the previous exclusions accordingly; preserved unrelated RUNS/provenance and prior README edits. Private proposal remains historical pending the coordinated freeze.

- 2026-10-26T04:40:03.377529+00:00: Accepted the parent-selected managed-worktree delivery method, added a read-only capture/replay/verify-source generator with an explicit 129-path policy, and included current executive-brief/native/browser/export/README/topic-doc scope. Historical patch remains intact. Application testing, Git application and commits remain parent-owned.

- 2026-10-26T04:41:53.788666+00:00: Refreshed private bundle `/private/tmp/drf-translation-delivery-refresh-20261026-b` contains127 changed paths from129 explicit inputs,60 parseable Python files and87 exclusion records. Patch applicability and static module closure pass; replay reproduces patch/allowlist/hashes/exclusions byte-for-byte. Tampered-input and existing-output refusal controls pass. The final source verifier correctly detected a later edit to `backend/tests/test_exec_brief_generations.py`; this audit-note update also postdates capture. Treat the bundle as provisional and rerun capture after parent freeze. Primary HEAD/branch/index/staged diff still match the original audit. No application test or worktree application was run.

- 2026-10-26T04:48:01.296117+00:00: Added the independently reviewed `refresh_demo_reports` preflight keyword `pipeline_id=pipeline_id` as an exact HEAD-based call replacement, alongside the two reader helpers and existing `export_dossier` forwarding call. The generator preserves the rest of both callers from HEAD even when current/baseline carry unrelated edits. Private extraction checks prove inclusion, exclusion of injected unrelated provenance comments, rejection of a missing pipeline keyword, and patch applicability. Added `test_translation_export_integrity.py` explicitly (policy130 input paths). Parent reports318 delivery-preflight scenarios:317 passed and1 test-only NameError, subsequently corrected by relocating a stray assertion; no extracted dependency issue was observed. This is parent-reported evidence, not an audit rerun or a claimed318-pass result. Current core carrier/comment/test edits are already covered by the explicit policy. Full final capture remains deferred until browser/frontend and executive-brief freeze. No primary index mutation.

- 2026-10-26T04:49:00.909783+00:00: The first private forwarding-template check caught a missing closing parenthesis in the generator's expected-call string before any full capture or application. Corrected that private template; the repeated positive/exclusion/missing-keyword checks and single-file patch check all pass. Receipt: `/private/tmp/drf-translation-delivery-audit-3kv6swgt/exporter-forwarding-checks.json`. Existing full bundles remain historical; final capture is still deferred.

- 2026-10-26T04:55:17.080054+00:00: Added only the two parent-approved compact diagnostic JSONs to the explicit/required policy. Reserved `verification.md` for exact inclusion once created, recording pending absence and detecting later appearance. Private policy checks confirm both lifecycle cases and the exclusion of preservation/raw baseline/private vault data. Policy133 exact entries; final capture and application remain deferred to parent freeze. Receipt: `/private/tmp/drf-translation-delivery-audit-3kv6swgt/diagnostic-document-policy-checks.json`.

- 2026-10-26T05:56:26.472125+00:00: Explicitly retained the new PDF Lua class constant, renderer fingerprint/hash, URI-validation helpers, pdflscape header and relevant imports. Added14 exact PDF-node preservation checks; targeted extraction, missing-constant negative control and single-file patch applicability pass. No extra Lua path, production edit, native run or full capture. Recorded the parent-reported live recovery/PDF503 findings and pending final rerun separately from historical worker acceptance.

- 2026-10-26T06:31:14.613271+00:00: Corrected the earlier semantic-dependency exclusion using parent-reported extracted-tree evidence (965 passed,1 classifier regression failed). Explicitly included only the five-line `llm_errors.py` ambiguous422/429 cooldown guard/comment, added an exact-current-versus-HEAD-plus-guard check and required policy path, and removed the incorrect unneeded claim. Policy134 entries. Parent owns affected/classifier reruns; live bilingual PDF success is recorded separately as parent-reported evidence.

- 2026-10-26T06:50:08.954897+00:00: FINAL POLICY/DOCUMENTATION FREEZE for parent capture:136 exact input paths, including the required five-line classifier guard, only the owned feature entry and new progress append, verification.md and two approved JSONs. Metadata extraction/application checks passed and preserve unrelated HEAD entries/history. Parent reports final functional/current/live acceptance and activelegacy base verification; issue9 tracks only the two prior asset gaps. Parent owns final capture/hash/method checks/commit/push without remote-config changes. This audit will make no further documentation edits unless instructed.
