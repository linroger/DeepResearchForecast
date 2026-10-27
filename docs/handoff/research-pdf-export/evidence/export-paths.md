# MAIN export, UI, and source trace

Status: complete, source inspection only. Inspected checkout: `/Users/rogerlin/.codex/worktrees/research-pdf-export/DeepResearchForecast`, branch `codex/research-pdf-export`, HEAD `033e191fe78fcd7cf81dfc117e3264f3dc02f133`. Date: 2026-10-26.

Scope: trace existing dossier and forecast PDF buttons, API clients, persisted source readers, report/language identity, chart/citation scope, and relevant test definitions. This evidence document is the only owned write. No application code, providers, services, tests, or other worktrees are executed or modified. Renderer internals and agent/job feasibility belong to the parent investigation.

Source references below are repository-relative `path:line` anchors at the frozen HEAD. They identify inspected code, not executed behavior. The parent owns the implementation plan and the separate resource-scoped asynchronous start/status/download routes; this trace supplies their existing consumers and source boundaries.

## 1. Exact buttons, selectors, and API clients

| Surface | Selector and visibility | Existing action | Client and route |
|---|---|---|---|
| Research dossier | `.dossier-language-bar a.edit-btn`; rendered when `hasReport && !editing && pipelineId`. `hasReport` requires `dossier.has_report` plus nonblank `dossier.report`. | Anchor `:href="researchPdfHref"`, `target="_blank"`, `@click="onPdfClick"`. Handler only calls `preventDefault()` if the selected language has no cached body. | `researchPdfUrl(pipelineId, activeReportLang || undefined)` → `GET /api/research/<pipeline_id>/dossier/pdf[?lang=en|zh]`. |
| Forecast report | `.forecast-report .pdf-btn`; inside the report layout after loading/error/generating/empty branches. | Button `@click="downloadArtifact('pdf')"`; disabled by `Boolean(exportBusy) || langLoading`; busy label and `exportError` alert. | `reportPdfUrl(reportId, activeLang || undefined)` → `fetch(GET /api/report/<report_id>/pdf[?lang=en|zh])`. |

Anchors: `frontend/src/components/research/DossierViewer.vue:3`, `:32`, `:563`, `:645`; `frontend/src/components/research/ForecastReport.vue:3`, `:52`, `:133`, `:1070`; `frontend/src/api/research.js:213`; `frontend/src/api/report.js:124`.

Both URL helpers use `apiUrl`: same-origin by default, or `VITE_API_BASE_URL` prefix. The existing downloads bypass Axios. Ordinary JSON API calls use the shared interceptor, which returns the backend body itself, so callers read `res.data`, never `res.data.data`. Its five-minute timeout does not apply to the direct anchor or forecast's native `fetch`. Anchors: `frontend/src/api/index.js:4`, `:25`, `:65`.

## 2. Producer → artifact → UI → current export

### Research dossier

```text
Research producer finalization
  → resolved handoff/research_report.md + sources.json + other structured files
  → GET /api/research/<pipeline_id>/dossier
  → getDossier(pipelineId) → ResearchView.dossier → DossierViewer.dossier
  → source body, or admitted research_report.<lang>.md in researchLangCache
  → researchPdfHref → GET /api/research/<pipeline_id>/dossier/pdf[?lang=...]
  → read selected Markdown from resolved handoff
  → ReportManager.export_document_pdf(md, handoff, out_pdf, label=...)
  → handoff/research_report[.<lang>].pdf → attachment research_report[.<lang>].pdf
```

- V3 `phase_finalize` writes citation-ordered `sources.json` before `research_report.md`, writes structured artifacts, then invokes research chart generation. Chart embedding can append a Visual Annex to the saved report. References: `deerflow_bridge/linear_research.py:8431`, `:8442`, `:8458`; `deerflow_bridge/deerflow_research.py:17718`. The multi-track merge also writes its finalized merged report and source ledger into the same handoff filenames: `backend/app/services/pipeline_orchestrator.py:13357`, `:13370`.
- Default root is `Config.PIPELINE_DATA_DIR/<pipeline_id>/handoff`, normally `backend/uploads/pipelines/<pipeline_id>/handoff`. **Use `PipelineManager.resolve_handoff_dir`, not only the constructed local path:** fork state can point to its base handoff, subject to containment under the pipeline root. References: `backend/app/config.py:1816`; `backend/app/services/pipeline_orchestrator.py:896`, `:905`, `:910`.
- Dossier GET reads `research_report.md`, `actors.json`, `sources.json`, `timeline.json`, `quantitative.json`, `contested.json`, `prediction_markets.json`, `charts.json`, and news context. `has_report` means the text file was readable; `sealed` is a separate edit-state signal. References: `backend/app/api/research.py:413`, `:431`, `:456`.
- `ResearchView` supplies pipeline ID, dossier, and artifact names; it fetches the dossier after observing research completion and retries at terminal pipeline state if no dossier was loaded. References: `frontend/src/views/ResearchView.vue:222`, `:784`, `:808`; `frontend/src/api/research.js:164`.
- The PDF route selects and rereads one body, supplies its containing handoff as the asset root, and uses labels `research::<pipeline_id>` or `research::<pipeline_id>::<lang>`. References: `backend/app/api/research.py:724`, `:737`, `:756`.

### Forecast report

```text
PipelineOrchestrator creates report_id and calls ReportAgent.generate_report
  → reports/<report_id>/meta.json + full_report.md + audited companions
  → GET /api/report/<report_id> → getReport(reportId)
  → ForecastReport.md + metadata, with publication withholding
  → primary body, or admitted GET full_report.<lang>.md in langMdCache
  → downloadArtifact('pdf') → GET /api/report/<report_id>/pdf[?lang=...]
  → publication admission → ReportManager.export_pdf(report_id, lang)
  → reports/<report_id>/full_report[.<lang>].pdf
  → attachment <report_id>[.<lang>].pdf → validated browser Blob download
```

- A new report attempt has a distinct `report_id` persisted into pipeline state before generation. The report agent receives the research body and structured inputs; its visual assets belong to its own report directory. References: `backend/app/services/pipeline_orchestrator.py:14882`, `:14892`, `:14913`, `:14941`.
- Report root is `Config.UPLOAD_FOLDER/reports/<report_id>`, normally `backend/uploads/reports/<report_id>`. `save_report` writes `meta.json` and `full_report.md`; translation finalization writes `citations.<lang>.json`, `final_audit.<lang>.json`, then `full_report.<lang>.md`, and records exact identities in translation metadata. References: `backend/app/services/report_agent.py:16311`, `:16338`, `:16355`, `:19039`, `:11560`, `:11593`.
- UI identity comes from pipeline status `report_id`, not from its `pipeline_id` or `simulation_id`: `frontend/src/views/ResearchView.vue:247`, `:784`. `ForecastReport.load` reads `data.markdown_content`: `frontend/src/components/research/ForecastReport.vue:482`, `:518`.
- **The UI metadata body is not a sufficient export input.** `ReportManager.get_report` prefers `meta.json.markdown_content` and only reads `full_report.md` if that field is empty; existing export reads the actual selected Markdown file and rechecks admission. References: `backend/app/services/report_agent.py:19123`, `:18150`, `:18159`, `:18165`.

## 3. Language identity and source admission

| Boundary | Current exact contract | Implication for the parent's source reader |
|---|---|---|
| Source selection | `activeReportLang === null` / `activeLang === null` omits `lang` and selects the primary saved body. | Primary can already be Mandarin; do not equate omitted language with English, or demand a same-language translation file. |
| Research language selector | `detectTranslationTarget` counts CJK versus Latin characters and offers the opposite of the source; source UI labels can follow app locale. | Treat the UI selector as selection intent, not proof of the selected bytes' language. |
| Research translated body | `_research_variant` requires current source SHA, schema 2, matching `target_lang`, exact variant/audit hashes, `hard_passed == True`, and a valid model review receipt when applicable. While regeneration runs/fails, an exact prior proof can remain usable. | Reuse this admission logic against the resolved handoff; never admit merely because `research_report.zh.md` exists. |
| Research primary body | Existing dossier/PDF readers require readable source; the PDF route does **not** explicitly apply the research contract seal/judge gate. | This is a source-observed admission asymmetry, not proof of an accepted/sealed source. The parent must specify the accepted-source rule if stricter admission is required. Do not call report publication checks with a pipeline ID. |
| Forecast primary/variant | `publication_status` requires completed metadata, no failed/partial report sections, current-policy hard audit matching the Markdown, and required companion integrity checks. A variant additionally requires publishable primary plus exact report/language/source fingerprints in audit, citation ledger, and translation metadata. | Preserve these gates before work and before serving completed bytes. Missing/stale/rebound variants cannot silently fall back to primary. |
| Forecast language controls | Toggles come only from matching backend-verified translation rows; source is read from `translation_status.source_lang`. Variant load must succeed before `activeLang` changes. | Preserve selected-language identity through async completion and download. |
| Partial translation versus partial report | An audited translation may disclose retained source-language passages. Structured card translation can also be incomplete while body remains available. Report sections marked failed/partial are a separate publication rejection. | Availability does not prove complete translation of prose/cards/chart labels; retain disclosures and let the plan define stricter export completion if required. |

References: `frontend/src/utils/researchTranslation.js:14`; `frontend/src/components/research/DossierViewer.vue:376`, `:571`, `:608`, `:645`; `backend/app/api/research.py:485`, `:548`, `:693`, `:740`; `backend/app/services/report_agent.py:17041`, `:17164`, `:17189`, `:17219`; `frontend/src/utils/reportLanguages.js:29`, `:53`, `:81`; `frontend/src/components/research/ForecastReport.vue:745`, `:844`.

The research translation worker writes only `research_report.<lang>.md`, `research_report.final_audit.<lang>.json`, and `research_report.translation.<lang>.json` for body publication; status commits last with file hashes. It rechecks source identity before publishing. Structured display uses a separate projection. References: `backend/app/api/research.py:520`, `:539`, `:583`, `:618`, `:639`.

## 4. Chart, reference, and footnote scope

| Surface | Content/asset scope | Citation/footnote scope |
|---|---|---|
| Dossier body | Complete `research_report[.<lang>].md`, including saved chart embeds/Visual Annex. `embed_chart_refs` avoids duplicate embeds, skips diagnostic charts, uses PNG plus optional HTML link, or an HTML-only link. Relative `charts/<basename>` resolves through `/api/research/<pipeline_id>/artifact/chart_<encoded basename>`; registered, provisional, and fork-shared paths are checked at serving. | V3 `[S#]` positions correspond to `sources.json` order. UI tooltip titles come from its source list; references remain in Markdown. `export_document_pdf` does **not** load a citations ledger or run the forecast `[S#]`→footnote conversion. Existing explicit Markdown footnotes still belong to the body passed to its renderer. |
| Forecast body | Complete `full_report[.<lang>].md` with report-owned visual embeds. `_inject_visualizations` builds `charts/` plus `viz_manifest.json`, places visuals into Markdown, and persists the body. Relative assets resolve through `/api/report/<report_id>/charts/<filename>`, with publication/containment checks. | UI derives citation tooltips from the active Markdown's References section. `export_pdf` loads `citations.json` for primary or **only** `citations.<lang>.json` for a variant and applies citation-footnote preprocessing when `REPORT_PDF_CITATION_FOOTNOTES` is enabled. The translated citation namespace must not fall back to primary. |

Anchors: `deerflow_bridge/linear_research.py:8443`; `deerflow_bridge/deerflow_research.py:17122`; `frontend/src/api/research.js:12`; `backend/app/api/research.py:885`, `:915`; `frontend/src/components/research/DossierViewer.vue:554`, `:577`; `backend/app/services/report_agent.py:12905`, `:16601`, `:18178`, `:18265`; `frontend/src/api/report.js:167`; `backend/app/api/report.py:1662`; `frontend/src/components/research/ForecastReport.vue:643`.

**UI-only additions are not automatically part of either existing PDF body.** Dossier actors/timeline/market/source/dataset tabs and forecast cards, binary table, source context, and fallback chart gallery are separate consumers. The forecast gallery normalizes the manifest and excludes figures already embedded in Markdown, so a manifest-only figure may be visible in UI without belonging to the saved body. Preserve the complete saved body and its references/figures; do not claim screenshot-equivalent inclusion of every tab/card. References: `backend/app/api/research.py:431`; `frontend/src/components/research/ForecastReport.vue:298`, `:1137`; `backend/app/api/report.py:889`, `:1753`.

Both languages currently resolve the same body-referenced chart paths; neither chart URL helper has a language parameter. Localized captions/structured display metadata do not establish that rasterized chart labels are translated. Likewise UI `[S#]` links/tooltips are not page footnotes: the shared Markdown renderer links superscripts only when it detects a References section. References: `frontend/src/api/research.js:12`; `frontend/src/api/report.js:167`; `frontend/src/components/research/ForecastReport.vue:1139`; `frontend/src/utils/markdown.js:81`, `:152`.

Keep saved simulation provenance markers and disclosures intact: forecast UI separately interprets bridge markers, hides a bridge under `no_update`, and withholds malformed bridges. Export must use the admitted saved body rather than the DOM's `displayMd` projection. This is a preservation boundary, not a request to change simulation or translation behavior. Reference: `frontend/src/components/research/ForecastReport.vue:685`.

## 5. Existing synchronous, polling, and error states

| Flow | Current behavior |
|---|---|
| Dossier PDF | Synchronous GET→render→attachment. No UI export busy/error/progress state or export-job polling. Repeated clicks can open repeated requests. Selected-language body absence disables the link; a cached body remains usable while structured translation is partial. |
| Forecast PDF | Synchronous GET→render→attachment. One `exportBusy` covers both Markdown and PDF. Native fetch checks HTTP status, parses JSON `error` when present, checks `%PDF-`, honors/sanitizes `Content-Disposition`, creates a Blob link, then revokes it. Request identity is report ID + selected language + latest-request token. Switching language/report or unmounting aborts the request and invalidates completion/cleanup. There is no explicit export deadline or job polling. |
| Dossier PDF errors | Unsupported nonblank language → 400; missing handoff/body → 404; unadmitted translation → 409; read/build failure → 500; unexpected renderer exception → 500 with `code=pdf_internal_error`. Disabled renderer currently becomes generic PDF failure 500 through this wrapper. |
| Forecast PDF errors | Missing report → 404; unsupported nonblank language → 400; publication rejection → 409 with `publication_issues`; disabled service → 503 `pdf_export_disabled`; rejected/absent build → 503 `pdf_build_failed`; internal error → 500 `pdf_internal_error`. Successful response is `application/pdf` attachment. |
| Dossier translation, not export | POST `/api/research/<pipeline_id>/dossier/translations/<lang>` starts/deduplicates translation; GET same path returns availability/body/projection. Polls every 4 seconds, maximum 30 scheduled reads, with visible timeout and retry. Pipeline or dossier-object content changes synchronously clear caches and invalidate pending responses; unmount also invalidates. |
| Forecast translation, not export | POST `/api/report/<report_id>/translations/<lang>` and GET `.../status?task_id=...`. Task/report/language mismatch is rejected. UI polls recognized active task states every 1.5 seconds, stops on terminal/error, and refreshes metadata before activating completion. Structured display separately polls `/forecast?lang=...` every 4 seconds with a 30-read bound. |
| Report generation, not export | Forecast `/sections-partial` plus detail polling runs every 3 seconds when loading an unfinished report; missing partial endpoint falls back to detail polling. The main `ResearchView` pipeline poll is independently adaptive, 2.5–12 seconds, and assigns report/dossier identity. None is an export-job status channel. |

References: `frontend/src/components/research/DossierViewer.vue:645`, `:660`, `:712`, `:778`; `frontend/src/components/research/ForecastReport.vue:816`, `:844`, `:959`, `:1080`, `:1375`, `:1554`; `frontend/src/utils/reportLanguages.js:385`, `:440`, `:455`; `backend/app/api/research.py:656`, `:724`; `backend/app/api/report.py:334`, `:1360`, `:1420`; `frontend/src/views/ResearchView.vue:464`.

## 6. Minimal integration seams for the parent's resource-scoped async plan

1. **Dossier consumer:** replace only the PDF anchor/click behavior at `DossierViewer.vue:32/:656` with the resource-scoped start/status/download consumer. Bind it to `pipelineId`, selected source/variant, and source generation. Retain the current unavailable-variant disable rule; add explicit busy/error handling because this surface lacks it.
2. **Forecast consumer:** adapt the PDF branch of `downloadArtifact` at `ForecastReport.vue:1080`; keep Markdown download behavior. Reuse the latest-request gate, filename handling, and PDF-signature check across start, polling, and final byte download. UI cancellation alone is not proof that a backend agent job stopped.
3. **Server source adapters:** retain research handoff resolution plus `_research_variant`, and forecast report-directory resolution plus publication checks. Capture exact selected Markdown and required asset/citation/audit identities server-side; revalidate before completed bytes can be served. Never take the other surface's ID/body or accept client-rendered HTML as authoritative input.
4. **Transport:** add narrowly scoped API helpers beside `researchPdfUrl` and `reportPdfUrl`; preserve `apiUrl` deployment behavior and the one-level JSON envelope. Existing translation/generation polling cannot substitute for the new export job's status. Job route names, persistence, renderer execution, and skill packaging remain the parent's scope.

No translation branch merge, canonical body rewrite, new research run, or source-system refactor is proposed.

## 7. Eight specific acceptance cases for implementation

These are proposed checks, **not executed results**. Existing tests listed below were inspected as source or located by exact definitions; several use fake renderers/transports and cannot establish real PDF layout or live-agent success.

| # | Scenario and required observation | Existing test anchors to reuse/extend |
|---|---|---|
| 1 | Click each original PDF control on a pipeline containing both surfaces. Each starts only its own resource's job, using its own complete saved body; forecast Markdown download stays unchanged. Preserve headings, paragraphs, tables, reference ledger, inline charts, and provenance blocks through the resulting PDF. | `frontend/tests/dossierTranslationEnvelope.test.mjs:99`; `backend/tests/test_report_viz_and_pdf.py:502`; no current source-located test executes the new async button→job→download path. |
| 2 | Export English primary→Mandarin variant, and Mandarin primary→English variant. Primary selection omits `lang`; no same-language variant is required. Variant bytes, attachment filename, and job status retain the requested report/language identity. | `frontend/tests/researchTranslation.test.mjs:13`; `frontend/tests/reportLanguages.test.mjs:65`; `backend/tests/test_report_bilingual.py:707`, `:848`, `:1253`. |
| 3 | Missing/stale/tampered translation, or a variant copied from another report, is refused before starting paid work and again at download; the old cached PDF cannot bypass admission. Also mutate the source after job start and require refusal rather than a stale success. | `backend/tests/test_artifact_translation_routes.py:99`; `backend/tests/test_report_bilingual.py:894`, `:909`; `backend/tests/test_model_translation_workflow.py:453`; `backend/tests/test_report_publication_barrier.py:125`. |
| 4 | Export a forked pipeline with an empty local handoff. It reads the contained state-resolved parent handoff and its charts, preserves the requested resource identity, and rejects escaping/symlink-swapped assets. | `backend/tests/test_research_fork_handoff.py:51`, `:66`, `:87`, `:117`, `:136`; `backend/tests/test_report_viz_manifest_api.py:161`. |
| 5 | Export a body containing inline figures, Visual Annex, static/HTML twins, source captions, repeated `[S#]`, explicit footnotes, and fenced examples. Preserve body exhibits and references without duplicating UI-gallery figures; use the forecast variant's isolated citation ledger. Explicitly account for dossier's current lack of automatic citation-footnote conversion and HTML-only figures. | `backend/tests/test_report_viz_and_pdf.py:85`, `:129`, `:255`; `backend/tests/test_wave9_citations.py:642`, `:665`, `:674`; `frontend/tests/markdown.test.mjs:43`, `:64`. |
| 6 | Double-click PDF while work is pending, then switch report/language or unmount before late start/status/download responses. Deduplicate the resource request, prevent stale downloads and stale cleanup, and distinguish stopping UI observation from cancelling the backend job. | `frontend/tests/reportLanguages.test.mjs:256`; `frontend/tests/dossierTranslationEnvelope.test.mjs:125`; `frontend/tests/reportMandarinConsumers.test.mjs:244`, `:479`, `:499`. |
| 7 | Exercise queued/running/completed, failed/interrupted, timeout, publication 409, service 503, network failure, and a successful HTTP response containing HTML rather than PDF. Status handling must terminate or expose retry truthfully; download only the current successful job's valid PDF and retain the server filename. | `frontend/tests/reportLanguages.test.mjs:167`, `:209`, `:276`; `backend/tests/test_report_bilingual.py:1301`, `:1311`. Translation state tests are patterns, not export-job coverage. |
| 8 | Export an admitted body while structured translation is incomplete, and a variant with disclosed retained source-language passages. Preserve the accepted body and disclosures without starting translation regeneration. Do not advertise full chart/card translation merely because the body was admitted; apply the parent's explicit skill completion policy honestly. | `frontend/tests/reportMandarinConsumers.test.mjs:329`, `:365`, `:544`, `:568`; `frontend/tests/reportLanguages.test.mjs:358`; `backend/tests/test_model_translation_workflow.py:274`. |

## 8. Evidence boundary and receipt

No test, app, provider, service, browser, or renderer was run. No other worktree was inspected. Only this evidence file was written; parent handoff and source files were left to their owners. Source statements above were checked against this branch, with memory used only as a locator for the Axios/identity boundary and then verified in current source.

Core inspected source SHA-256 values:

| File | SHA-256 |
|---|---|
| `frontend/src/components/research/DossierViewer.vue` | `2158b31c20a38a51eb8b560125ad1175f96569b1c3c616aa2c48e4895e1d566b` |
| `frontend/src/components/research/ForecastReport.vue` | `0b56b0638f42b7bbdf7caca3c6111fe7175f87879fa9005c910bae983d94b586` |
| `frontend/src/api/research.js` | `d9a61eb8fe385c2d163ec9e4eea9cb341cd850f5237478f29a6f6e0be960b1eb` |
| `frontend/src/api/report.js` | `c145d06edd84551135c995dbedbb4c2b416d5dce81762ecb7b79da8f8a7c3cfd` |
| `backend/app/api/research.py` | `4029e93bb8b5428d48cec27b54a6c34b70238521112c213bd7b358bd60b92d24` |
| `backend/app/api/report.py` | `37b7b9d01dc7fb7a66b5193a4de8f4c1fb8ec69e86a2946393d6ae6efe5cc988` |

Updates: 2026-10-26 — created the owned evidence document; completed the bounded selectors/routes/source/chart/citation trace and eight proposed acceptance cases. The parent's later scope clarification fixes the integration direction as separate resource-scoped start/status/download routes; implementation remains unperformed. Static document verification checked 71 explicit file/line anchors and the six source hashes; it caught and corrected one transcribed hash. No application tests were executed.
