# Report, dossier and PDF integration handoff

**Status:** Complete and frozen, including the executive-brief extension and native-PDF corrections. **Owner:** report adapter worker. **Started:** 2026-10-26.

**Current authority:** the final live-copper PDF correction below is frozen at report-agent `64a9ec…`, with55 focused tests and actual copied-input native acceptance complete. Earlier401-case production and25-case test-migration gates remain historical evidence for their exact bytes. Native rendering and bounded independent review are complete; no worker code change or blocker remains. Parent owns full-combined validation, delivery, activation and any live HTTP recheck.

**Reopened live-copper PDF investigation:** the parent reports that the actual copper body recovered with21 valid imported sections and only one translation/review pair, while both primary and Mandarin PDF API exports return503 despite native renderer rc0. Original saved artifacts remain outside this worker's write scope. The native verifier owns diagnosis using private copied inputs under `/Users/rogerlin/Documents/Codex/evidence/translation-redesign-2026-10-26/live-copper/pdf-repro`; this worker owns a production PDF correction only after a reproduced root cause and regression, plus bounded content-free audit-rejection logging. No translation/body regeneration, provider action or service restart is authorized here. Earlier401/native fixture acceptance remains historical evidence, not proof of the current real-report export.

The native verifier reproduced two distinct roots. The eight-column official-indicators table has a real2.0224pt glyph-box overlap between adjacent numeric/date cells, confirmed visually in both languages and reproduced with invented data in a one-row eight-column fixture. Separately, an English visible URL identifier wraps between digits; the complete exact URI remains in PDF annotations, so treating that identifier as a missing operating number is a false rejection. Root evidence is `/private/tmp/drf-copper-native-20261026-01/diagnosis.json`, `table-overlap-proof.json`, `url-identity-proof.json`, and the minimal-red fixture under `/private/tmp/drf-copper-minimal-native-20261026-01/`. Private report prose was not printed or copied into tests.

The bounded production correction uses the existing Pandoc/XeLaTeX pipeline with a trusted render-only Lua filter: tables of at least7 columns get landscape, small table text and3pt cell padding; narrower tables retain their layout, and longtable pagination/source contents stay intact. Visible URL labels are treated as URI carriers only when the exact PDF link destination is verified; their layout-wrapped identifiers leave quantity comparison, while ordinary/linked numerical claims retain the strict token-count gate. A rejection now logs fixed issue codes, bounded counts and source SHA rather than source text, labels, paths or token values. Red logging/URI tests were preserved before the fix. The52-case focused PDF/artifact gate passed at `/private/tmp/drf-pdf-copper-fix-focused-20261026/`, including changed numeric claims, merged numeric cells and changed-URI negatives.

Current candidate freeze for native verification: `report_agent.py` SHA `93f33c646b17c75d273c644ab30d7d640e088334c1c4613fdfd02a950e02ef32`; artifacts remains `b2fd31…`. Trusted filter constant is `ReportManager._PDF_WIDE_TABLE_FILTER`, UTF-8 SHA `3957cd5af880f481a4682f70f967b5af665bc5422f701f49f2f87948d95ec8a6`, emitted as `.pdf-wide-table-*.lua` with one `--lua-filter=<absolute path>` argument. Native minimal/dense multipage/actual copied-report/four-column regression runs and bounded independent review are in progress. No source-body regeneration or provider work occurred.

The first native minimal rerun admitted both languages with zero content issues and cache reuse. Geometric separation improved from−2.0224pt overlap to+34.0919pt, with the dense table on landscape page2. A harness-only rejection-control classification was corrected by the native owner; no production renderer defect was found in that step. Independent source review found a URL-label mismatch hole, which was reproduced by a negative fixture: unchanged annotation, changed displayed URL and an omitted operating number matching another URL segment could otherwise pass. Missing complete visible-label matches now reject the PDF independently. The focused gate passed53 tests at `/private/tmp/drf-pdf-copper-fixed-final-20261026/`; current frozen report-agent SHA is `ded605854262639ace22ad76dc01168c8749857cd9adea8f72ced3ef28a09bf0`. The trusted filter and its hash are unchanged. Native copied/stress/baseline runs are released on this updated hash.

The native owner verified the same+34.0919pt gap in actual copied reports and all120 stress rows; dense tables span seven landscape pages with no row loss. Four-column baseline PNGs remained byte-identical. Actual exports then failed only one visible-label check: Pandoc's SMART reader had changed a URL's double ASCII hyphen into an en dash in its AST while retaining the original href. A bounded native AST/LaTeX probe proved `--from=markdown-smart` preserves the label; that exact-content input mode is now used without relaxing label admission. A parent-requested prefix-URL regression also reproduced that removing a short URL first damaged a longer label; unique labels are now removed longest-first, with positive and missing-operating-number controls.

**Current PDF owner freeze:** report-agent SHA `64a9ec3b8b8bae889395f30f3dc79116e2cfe6a34826d105e796c599a9014011`; test file `test_report_viz_and_pdf.py` SHA `fcd7b83c3ee86e13da625d877582a5215bd6042efbe7018f88a92d6d3d48a816`. The55-case guarded gate passed in4.23s at `/private/tmp/drf-pdf-copper-owner-freeze-20261026/`. The wide-table filter hash remains `3957cd5af880f481a4682f70f967b5af665bc5422f701f49f2f87948d95ec8a6`; the native command adds exact `--from=markdown-smart`. Strict merged/changed numeric and changed href/label negatives remain green. Actual copied-report final rerender and bounded review closure are pending on these bytes; no more production edits are planned absent a reproduced defect.

### Live-copper PDF correction — final accepted handoff

The focused gate is55 passed with no failures/errors/skips, no tracked drift, preserved identity and complete shutdown. Its only denials are the established2 font-discovery subprocess probes and18 font-directory reads; no provider/network/saved-data event occurred. Receipt and exact frozen hashes: `/private/tmp/drf-pdf-copper-owner-freeze-20261026/{completed.json,junit.xml,frozen-hashes.json}`. Red logging, wrapped-URL, combined changed-label/missing-number, and prefix-URL receipts remain preserved as regression evidence. Scoped diff checks pass. The bounded independent reviewer closed the known URL findings and found no material issue in trusted filter binding or safe rejection logging.

**Actual copied inputs now pass on the same `64a9ec…` bytes:** `/private/tmp/drf-copper-v9-actual-20261026-01/acceptance-summary.json` is the compact final proof; `native-pdf-receipt.json`, `final-visual-proof.json`, and `geometry-verification.json` retain full evidence. English35 pages and Mandarin28 pages both pass actual export and cache reuse. Numeric, glyph, heading, citation, image, all33 visible URL-label and exact URI-target checks pass. Table separation is+34.0919pt in both languages, with final table PNGs identical to the inspected repaired layout. Fresh URL crops show exact double ASCII hyphens. All70 source/input hashes remained unchanged;61 native process groups closed; safety controls passed.

The current-CLI narrow-table baseline also passes at `/private/tmp/drf-copper-v9-baseline-20261026-01/`; all7 PNGs are byte-identical to the original accepted baseline. The dense120-row, seven-table-page stress evidence uses the same unchanged filter on the earlier `ded605…` source, with all120 same-baseline pairs and positive gaps; it is explicitly distinguished from the final actual-input source rather than relabeled as a fresh full run. The native owner's section12 in `worker-native-pdf.md` is the current native authority.

Only `backend/app/services/report_agent.py` and `backend/tests/test_report_viz_and_pdf.py` were changed by this worker for the PDF runtime correction, plus this record. Original saved reports were not written or regenerated. No translation/provider action, service restart, Git action, or live HTTP verification was performed. The parent retains full-combined/delivery and separately authorized activation/export recheck. This correction is complete and frozen with no remaining worker blocker.

**2026-10-26 reopened test-only migration:** the parent's44-suite gate exposed additional legacy assumptions in `test_artifact_translation_routes.py` (report/research portions), `test_artifact_translation_structured_job.py`, and `test_translation_robustness.py`. This worker now owns their migration, preserving semantic/tamper/source-drift/no-body-regeneration/one-writer/partial-retry scenarios. The simulation case in the mixed route file remains parent-owned and unchanged. Production files remain frozen unless a genuine implementation defect is reproduced. Two robustness child failures require the existing explicit `orphan_owner.py` runner admission, not a code or guard relaxation.

The structured-job fixture now models an admitted historical body without a completed dashboard job. Previously it translated the entire forecast first and then damaged only the sidecar; the new durable engine correctly reuses that accepted work without entering a held/refusing provider, so the old fixture no longer exercised its claimed scenario. Registered handler dispatch now uses real SQLite ownership and epoch context. All original test cases remain, including duplicate start, pending GET, partial/refusal retry, source mutation, former-inline caller joining the same operation, and constructor failure clearing activity. Robustness assertions use typed `provider_failure`, the generation resolver, and legacy-PID-to-interrupted route semantics. The19-case guarded run passed at `/private/tmp/drf-report-test-migrations-20261026-1/`, including both admitted orphan-owner child cases. Mixed-route migration and final three-file freeze remain pending; no production edit was made.

**Test-only migration completed:** the final three-file gate passed **25 tests in7.96s**, with zero exclusions/failures/errors/skips. Evidence: `/private/tmp/drf-report-migrations-final-20261026/{completed.json,junit.xml,source-hashes-before.json,source-hashes-after.json}`. All15 captured production/core/test hashes stayed unchanged during execution. There were no network attempts or blocked operations; two explicitly admitted `orphan_owner.py` children and two liveness checks are recorded. Identity environment was preserved and shutdown completed. The simulation test inside the mixed route file is unchanged.

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-report-migrations-final-20261026 \
  --allow-python-script backend/tests/fixtures/orphan_owner.py -q \
  backend/tests/test_artifact_translation_routes.py \
  backend/tests/test_artifact_translation_structured_job.py \
  backend/tests/test_translation_robustness.py
```

Use a fresh evidence directory when rerunning. The only code edits in this follow-up are these three test files; the parent retains ladder-simulation fixture and broader command-admission ownership. No scenario was deselected. Actual current-generation tampering, failed-refresh preservation, durable restart recovery, changed-source refusal, no-body-regeneration, duplicate/one-writer ownership, partial retry and provider-free reads remain asserted. All five owned production hashes still match the401-case freeze; no production defect reproduced.

```text
backend/tests/test_artifact_translation_routes.py
fdb16fd916137e6c0bd609327a2a8734e073e3771a616559c559fcf5828acec7
backend/tests/test_artifact_translation_structured_job.py
aeb796ac26ce4d414951e05d4f2426abab8a0dc65f539ea44675ac93af65994d
backend/tests/test_translation_robustness.py
de99eeb36d54a11363b065f6903f62189968b7846abda87232eec168ac992d29
```

- 2026-10-26: Closed the parent's additional test-migration assignment with25 guarded passes, no exclusions and stable source hashes. Preserved the failed parent44-suite receipt as historical evidence; the parent-wide rerun is still the parent's gate, not implied by this scoped result.

## Request and accepted boundaries

Implement the approved full design using the parent's durable translation and scheduler APIs. Preserve the extensive baseline dirty tree. Owned production files are `report_agent.py`, `api/report.py`, `api/research.py`, and new `translation/artifacts.py`. Core modules and app registration belong to the parent. No providers, saved production data, service restart, package installation or commits are authorized for this worker.

## Requirements and checks

| Requirement | Scenario evidence |
|---|---|
| Resume accepted sections and fields | Failed v1 proof passed as previous_proof; matching field receipts supplied as seed; guarded deterministic fixtures count provider calls. |
| One durable route authority | Named registered scheduler operations; duplicate start and interrupted/restart status tests through public routes. |
| Preserve accepted content | Failed refresh leaves accepted generation and legacy artifacts unchanged; immutable manifest and pointer crash-window checks. |
| Exact export language and snapshot | Resolver bytes feed renderer; source/publication drift and concurrent exports return typed409; read/export makes no provider call. |
| Atomic PDF cache | Unique temporary output, content validation, dependency recheck, atomic replace; failed build retains prior cache. |

## Plan and ownership

The report worker implements artifact publication, report-agent durable calls and shared PDF rendering. Dewey owns only `api/report.py` and new report route tests. Chandrasekhar owns only `api/research.py` and new research route tests. Existing dirty changes are the starting point, not changes to revert. The existing root handoff and approved architecture/plan/contract were read before implementation.

## Findings and decisions

The current guarded runner is `backend/scripts/main_offline_pytest.py`, not the older Finharness runner. Use the installed `backend/.venv/bin/python -I -S -B` entrypoint before any app imports. The runner prohibits native renderer subprocesses; real fixture rendering requires either a safe supported in-process renderer or a documented parent command. Legacy sidecars remain readable under their existing audit contract; new publications use immutable directories and one atomic pointer.

## Progress and errors

- [x] Read approved contract, current ownership and dirty state.
- [x] Split disjoint API adapter ownership.
- [x] Implement artifacts, body/forecast migration and PDF caching.
- [x] Integrate routes and guarded scenario tests.
- [x] Review current bytes and record verification receipt.

Initial historical-runner lookup found no Finharness runner in this checkout; source discovery located the main runner before any app import.

## Verification and remaining work

The current focused acceptance run passed **94 tests**: `/private/tmp/drf-reports-gate-20261026-4/{completed.json,junit.xml}`. This includes the real report manager's failed-v1 22-section scenarios (20 or21 accepted sections; exactly2 provider-fixture calls for the remaining2 or1 sections), failed refresh preservation, read-only generation resolution without SQLite, publication interruption, drift and concurrent PDF conflicts. API lifecycle/publication compatibility scenarios are receiving a second bounded gate. Parent retains final cross-package review, app activation, live acceptance and delivery.

The real installed PyMuPDF path rendered English and Mandarin multipage fixtures with figures, ≥ ≤ ± symbols and citation markers. First-page PNGs were visually inspected under `/private/tmp/drf-reports-pdf-real-20261026-2/pytest-tmp/`. An initial render exposed missing figures despite passing text checks: absolute Pandoc image paths were not resolvable by the PyMuPDF archive. The fallback now rebases contained local assets and the test asserts embedded images. Content admission now also checks source raster figure presence. These are real simple-document fallback renders; rich-table/footnote Pandoc/XeLaTeX validation remains a separate parent gate because the existing guard denies native renderer subprocesses.

The94-test receipt records zero network or saved-data events. It records2 denied native library probes (`fc-list`, `system_profiler`) and18 denied font-directory reads; these are contained discovery attempts, not zero attempts. The receipt reports shutdown complete and no tracked source drift. The initial runner invocation used symlinked `/tmp` and was rejected before imports; canonical `/private/tmp` is used thereafter. Earlier implementation failures (missing tempfile import and a misplaced generation-status insertion) were fixed before this acceptance.

Independent review identified three P2 defects. First-time Mermaid rendering wrote derived files into canonical `charts/`, causing its own fingerprint to drift; those files now live in unique temporary export staging. Publication lacked figure identity; manifests now seal `figures.json`, readers compare exact referenced local image hashes, and body adapters capture that inventory before translation. Explicit forecast refresh failed to propagate; it now bypasses ordinary reuse only when requested, passes the durable refresh identity, and preserves accepted bytes while raising a safe incomplete error for a failed replacement. The targeted review-fix run passed108 tests at `/private/tmp/drf-reports-review-fixes-20261026-1/`. Review closure and final combined freeze remain pending.

All three P2 findings were independently closed. A follow-up image-reference issue was fixed by using the existing Markdown AST, including reference-style images and optional titles; missing or changed published figures return409. The reviewer's independent3-case image-closure run passed at `/private/tmp/drf-reviewer-image-closure-20261026-759a6447/`.

The parent's final scoped-import contract is integrated: document audits must match report/pipeline ID, source hash, target/source language and context before a legacy proof receives the Python `trusted_import` capability. Foreign bound proof or section scopes are rejected before wrapping. Forecast seeds pass the source-bound typed-payload reader and scope filtering. New receipts preserve their native scope binding. Five report import-negative cases, legacy partial-forecast reuse, foreign forecast-reader rejection and matching research scenarios cover this boundary. Independent source review found no remaining P1/P2 defect in these adapter checks.

Automatic report completion now queues through `ReportManager.enqueue_translation_variant()` and `api.report.enqueue_report_translation()` after saving the completed primary, using the same named scheduler operation as POST. The existing `DRF_TEST_PROCESS` lifecycle boundary suppresses implicit background work in fixtures; explicit queue/POST tests exercise the real scheduler interfaces. Automatic/manual attachment deduplicates and automatic attachment does not retry failed operations.

An intermediate combined run passed313 tests at `/private/tmp/drf-reports-final-20261026-freeze/`; its tracked test inputs did not drift during execution. Later generic-authorizer work changed API source bytes, so this is historical acceptance, not the final freeze. `register_translation_handler()` now also registers real report/research generic retry/cancel authorizers, recomputing identity from minimal resource selections and rejecting client-provided identity assertions. Final affected verification is in progress.

### Integration surface

Both resource modules expose `register_translation_handler()` for explicit Flask lifecycle registration. `ReportManager.resolve_translation()` and `read_translation_markdown()` consume a generation with historical fallback only when no generation pointer exists. `refresh_translation_assets()` seals structured-display repair around the unchanged admitted body. Artifact pointer activation uses the parent's `scheduler.publication_guard()` and an immediate source recheck while holding the artifact lock. PDF exports return immutable cache paths; facade filenames remain language-specific. The PDF manifest location remains the existing `<requested PDF path>.manifest.json` convention.

### Native rich PDF gate prepared for the parent (ownership transferred)

`backend/tests/render_translation_pdf_fixture.py` is an explicit opt-in runner. It copies only application source into a new external fixture directory before imports, sets test-process mode, relocates mutable roots, disables fallback, and renders English/Mandarin documents with repeated tables, figure, citation footnotes, ≥ ≤ ± symbols and multipage output. It verifies the actual content gate and cache reuse, and saves first/middle/last-page PNGs for parent visual review. It has **not been executed by this worker**, because native subprocesses are outside the authorized CPython guarded execution boundary.

From the checkout, the parent command is:

```sh
backend/.venv/bin/python -I -B backend/tests/render_translation_pdf_fixture.py --execute-native --output /private/tmp/drf-native-rich-pdf-20261026-parent
```

Use a fresh absent output path. The receipt is `native-pdf-receipt.json` in that directory. The parent explicitly requested this prepared outside-guard isolated-source-copy gate; it is not a claim of native rendering success.

The parent subsequently assigned a dedicated native verifier. An initial plan named a parallel fixture; the report worker removed the then-unused helper to avoid duplicate entrypoints. Immediately afterward, explicit user direction required preserving and strengthening the existing helper instead. It was restored byte-for-byte (`449f4eeb…`), and ownership of `backend/tests/render_translation_pdf_fixture.py` transferred to the native verifier. The report worker will not edit or remove it again. The native owner adds narrow admissions before imports and native child containment; use that worker's final command and receipt. This records the sequencing mistake and recovery rather than concealing it.

### Saved-evidence correction from the parent

The synthetic22-section tests demonstrate exact20/22 and21/22 reuse. The parent's subsequent read-only saved-artifact investigation establishes that the **current** semiconductor audit contains19 receipts and failed sections5,12,13, after a pre-implementation02:58Z replacement. There is no invalid present receipt or new structure-cache regression. Actual recovery must resume the19 current receipts, not force a historical20-count. Copper currently has21. This worker did not inspect or mutate live saved artifacts.

## Updates

- 2026-10-26: Created initial brief, ownership, acceptance matrix and guard boundary.
- 2026-10-26: Added durable body/forecast identity and proof import, sealed generation publication and readers, atomic immutable PDF caching, typed conflicts and actual in-process PDF rendering. Recorded94-case guarded acceptance and the figure-rendering correction. Continued from current working bytes after stream interruption.
- 2026-10-26: Migrated actual model-workflow consumers to generation paths while retaining forged-receipt, semantic rejection, canonical immutability and tamper checks. Integrated the overlay owner's authoritative world-v1 fixture and real restart-reader path. Workflow gate passed13 tests; compatibility/publication gate passed83. Native rich renderer command prepared for the parent; saved receipt-count correction recorded separately from synthetic evidence.
- 2026-10-26: Fixed all three independent P2 findings with targeted first-export, figure-drift and refresh-preservation scenarios;108-case guarded gate passed. Removed obsolete local dashboard thread coordination from the active report wrapper.
- 2026-10-26: Closed independent review, added resource-scoped trusted legacy import and public read checks, migrated automatic completion to the shared scheduler, and integrated real generic retry/cancel authorizers.313-case intermediate combined acceptance passed; final authorizer freeze pending.

## Final frozen acceptance — 2026-10-26

**343 passed in31.31s, zero failures, errors, skips or deselections.** Evidence is `/private/tmp/drf-reports-actions-final-20261026/`: `completed.json`, `junit.xml`, `source-hashes-before.json`, and `source-hashes-after.json`. All26 manually frozen production/core/test hashes match before/after; the runner also reports no tracked source drift, exit0, complete shutdown and preserved identity environment. One explicitly admitted guarded child verifies the simulation restart-reader consumer. No network or saved-data events occurred. Two blocked library subprocess probes (`fc-list`, `system_profiler`) and18 blocked font-directory reads remain honestly recorded.

| Test file under `backend/tests/` | Passed |
|---|---:|
| `test_translation_artifact_generations.py` | 13 |
| `test_report_durable_publication.py` | 12 |
| `test_report_durable_routes.py` | 62 |
| `test_research_durable_routes.py` | 79 |
| `test_report_forecast_localization.py` | 8 |
| `test_report_viz_and_pdf.py` | 25 |
| `test_report_bilingual.py` | 41 |
| `test_research_dossier_translation.py` | 7 |
| `test_report_bilingual_filter_safe.py` | 22 |
| `test_sessionb_translation_structure.py` | 9 |
| `test_report_publication_barrier.py` | 10 |
| `test_report_data_publication.py` | 14 |
| `test_report_draft_exposure.py` | 28 |
| `test_model_translation_workflow.py` | 13 |

The command used the installed interpreter with `-I -S -B`, `backend/scripts/main_offline_pytest.py`, a fresh `--evidence-dir`, `--allow-python-script backend/tests/test_artifact_translation_restart.py`, `-q`, and exactly the14 files above. Scoped diff checks and AST syntax checks passed. No baseline path-migration test failure remains in this gate.

Frozen owned production SHA-256:

```text
backend/app/services/report_agent.py
aff53be281fc2ecd0f1ea2596a2072c8a7cd9cb3fab2dd700397551f515c8336
backend/app/services/translation/artifacts.py
b2fd31f8e3b69f43173b34253730c5f3c36efd6d7176fdad75e6cfd9bd8d3e36
backend/app/api/report.py
b3fb4bc2510838c3cd5b2827b1ff22f530d5153513035f0323cb7fa675a00c25
backend/app/api/research.py
fd0cc80edac0bd93c14f9dc3c868f45a5777aa8c3b1270d6523668d9e3c34a38
```

### Parent integration and next-session prompt

No assigned implementation defect remains. Parent owns native Pandoc longtable/chart/citation acceptance, final full-system activation/recovery and delivery. Independent source review closed all reported P2 findings and found no material scoped-import defect. A downstream reader outside this worker's ownership remains at `backend/app/services/exec_brief.py:819`: it reads the historical `full_report.<lang>.md` literal. If translated executive briefs are part of the full integration gate, migrate that reader through `ReportManager`'s resolver; do not restore an independent mutable sidecar writer to satisfy it. Existing legacy variants remain supported.

> Continue the translation-hardening-pdf parent integration from this frozen343-case report/dossier/PDF slice. Read the final receipt and hash manifests, then the dedicated native-PDF worker record. Preserve all baseline dirty work and1878 saved report artifacts. Do not rerun providers or restart services merely to validate source. Resolve the out-of-ownership executive-brief reader if included in final scope, run the parent combined gate on frozen bytes, then perform only separately authorized activation/live recovery/delivery.

### Additional affected-reader acceptance requested by the parent

The seven additional suites exercised175 cases. `/private/tmp/drf-report-readers-final-20261026/` recorded174 passes and one blocked restart-child launch: the invocation omitted the exact `--allow-python-script backend/tests/test_forecast_feedback_sdk.py` admission. This was a harness invocation error, not a reader implementation failure; the guard remained enforced. The single affected scenario was rerun with that explicit admission at `/private/tmp/drf-reader-restart-final-20261026/` and passed in4.11s. Do not misreport the original run as green. No source drift occurred.

| Additional file under `backend/tests/` | Verified cases |
|---|---:|
| `test_exec_brief.py` | 20 |
| `test_exec_brief_sim_disclosure.py` | 7 |
| `test_forecast_feedback_sdk.py` | 38 (37 initial +1 admitted-child rerun) |
| `test_sdk_publication_barrier.py` | 2 |
| `test_report_official_data.py` | 69 |
| `test_report_official_publication_real.py` | 32 |
| `test_report_viz_manifest_api.py` | 7 |

These legacy executive-brief tests do not establish that the literal sidecar reader supports newly generated translations. That source-established consumer gap remains explicitly handed to the parent. All four owned production files still match the343-case freeze. No additional production code was changed for this expanded gate.

### Native renderer finding and correction

The native verifier demonstrated an actual Pandoc/XeLaTeX rc0 English PDF rejected solely because it contained a short Chinese marker. At `/private/tmp/drf-native-pdf-20261026-04/`, `raw-en.pdf` has4 pages,1 raster image, all protected symbols/numbers/citation markers/headings, Latin coverage0.9969 and all6 Han characters; the old short-Han branch nevertheless required the entire normalized report to appear contiguously, which tables/footnotes/TOC extraction cannot guarantee.

The report owner corrected both symmetric short-script branches: short Han requires its character counts; short Latin requires all its word counts. Existing heading, numeric, citation, protected-symbol, long-script coverage and figure gates remain. Four real-PDF positive/negative regressions cover reordered English-plus-short-Han and Chinese-plus-short-Latin content, including missing-fragment rejection. The42-case guarded PDF/artifact gate passed at `/private/tmp/drf-pdf-mixed-script-fix-20261026/`. Renderer version is now v6, invalidating old caches. `report_agent.py` is frozen at `13d908597e7e4b2b598d47e94e4c27c9840ec5104f47cb12754f914bfa62110c`; the other three owned production hashes are unchanged.

**Current final combined gate:347 passed in29.38s**, with no failures/errors/skips/deselections, at `/private/tmp/drf-reports-nativefix-final-20261026/`. The14-file test list is unchanged from the343-case table; `test_report_viz_and_pdf.py` now has29 cases, accounting for the4 new regressions. All26 captured production/core/test hashes match in `source-hashes-before.json` and `source-hashes-after.json`; the runner reports no source drift and complete shutdown. Guard events remain2 blocked discovery subprocess probes,18 blocked font scans and1 explicitly admitted restart child, with no network or saved-data events. This gate supersedes343 for the current renderer. Native rerender/visual inspection is still being completed by its owner.

The independent reviewer closed the narrow native-validator correction with no material P1/P2 finding. The native owner then reported that run06 on `13d908…` produced admitted PDFs/manifests in both English and Mandarin through actual Pandoc/XeLaTeX rc0. English content/cache/four-page raster checks passed. Mandarin legitimately used3 pages, exposing an overly specific4-page assertion in the harness; the owner corrected the harness to require at least3 pages while still requiring the longtable itself to span3 pages. Final run07 remains the native owner's evidence authority; no further production defect was reported.

**Correction to that intermediate native report:** the native owner clarified that only English export was accepted; Mandarin's renderer returned rc0 but its artifact had been inspected through diagnostic continuation after production-gate rejection. Run07 isolated a second real defect: `_markdown_visible_text` counted the non-rendered `audit` identifier in `[^audit]` references/definitions as visible Latin prose. The owner preserved `raw-zh.pdf` and `rejected-zh-content-audit.json`; all table rows, symbols, headings, Chinese content, image and actual footnote body were present. Do not count rc0 alone as publication acceptance.

The report owner replaced regex-only visible-text extraction with the existing Markdown AST's rendered text/code traversal. It skips footnote-reference identifiers, includes footnote-body children, and retains literal code and unresolved references. The short-Latin content gate is unchanged. Three new regressions prove syntax exclusion and actual footnote-body presence/loss. The45-case PDF/artifact gate passed at `/private/tmp/drf-pdf-footnotes-fix-20261026/`; renderer version is v7 and current report-agent hash is `13fd157ed2c7661a2099dad3b927f4173a6f8fcb9abeb242ec21b14e25588583`. Native rerender is pending on that exact correction.

**Native export acceptance subsequently passed** on `13fd157…` / artifacts `b2fd31…`: `/private/tmp/drf-native-pdf-20261026-09/native-pdf-receipt.json` reports export and safety passed, zero source drift, preserved identity and complete shutdown after atexit. Actual English export is4 pages and Mandarin3 pages; both cache hits require no further Pandoc call. Independent extraction checks cover120 row/value pairs per language across3 longtable pages, raster chart, footnotes, citations, Chinese text, ≥ ≤ ± and clickable links. Native OS network/external-write/private/credential-read and Python saved-data/network/identity/process negative controls passed. The native owner retains the final seven-page raster inspection and exact harness command/hash record in `worker-native-pdf.md`.

**Final native acceptance is complete:** `/private/tmp/drf-native-pdf-20261026-10/` contains `native-pdf-receipt.json`, `completed.json`, `visual-inspection.json`, `review-closure.json` and `native-commands.json`. Both actual exporter results and cache hits pass; all7 final PNG hashes match individually inspected pages; independent review is closed. The native owner rehashed47 source files with no drift and closed all64 tracked native process groups. The one strengthened existing harness is `backend/tests/render_translation_pdf_fixture.py`, hash `c17b9504c51fb33727731d3efdf67a153bc6e619792c13615498a5ae51b8fc41`; production hashes remain report `13fd157…` and artifacts `b2fd31…`. Use `worker-native-pdf.md` for the full exact command, controls and scoped limitations. No duplicate harness remains.

### Newly assigned executive-brief scope

The parent explicitly expanded this worker's ownership to `backend/app/services/exec_brief.py` and corresponding tests, so the previously out-of-ownership gap is now an active required fix, not a future task. The bounded worker is replacing literal translation reads with admitted generation snapshots and binding deterministic brief caches to source/generation identity, retaining legacy compatibility. Acceptance must exercise an actual newly generated variant through public brief reads, plus stale/deletion/failed-refresh cases, with no provider work from reads. The earlier scoped Complete status is superseded until this extension and the native corrections finish.

The initial executive-brief extension passed37 tests (27 existing and10 new), then integration/independent review found four bounded P2 corrections before acceptance: pass the report directory as the fallback image archive while keeping output staged; enforce current publication policy on snapshot capture; make digest delivery honor successful returned artifacts and verify source/output identity; and run the existing PDF content validator before brief-cache publication instead of checking only `%PDF-`. Those corrections and their regression cases are in progress within the newly assigned brief module/routes/tests. The full-report native renderer remains frozen and accepted.

## Final delivery freeze — authoritative current result

**401 passed in36.90s; zero failures, errors, skips or deselections.** The current receipt is `/private/tmp/drf-reports-complete-final-20261026/completed.json`, with `junit.xml` and `source-hashes-before.json` / `source-hashes-after.json` beside it. All30 captured production/core/test hashes match across the run. The guard reports exit0, no source drift, preserved identity environment and complete shutdown. Events include one admitted restart-reader child, two blocked font-discovery subprocess probes and18 blocked font-directory reads; no network or saved-data event occurred.

| Test file under `backend/tests/` | Passed |
|---|---:|
| `test_translation_artifact_generations.py` | 13 |
| `test_report_durable_publication.py` | 12 |
| `test_report_durable_routes.py` | 64 |
| `test_research_durable_routes.py` | 79 |
| `test_report_forecast_localization.py` | 8 |
| `test_report_viz_and_pdf.py` | 32 |
| `test_report_bilingual.py` | 41 |
| `test_research_dossier_translation.py` | 7 |
| `test_report_bilingual_filter_safe.py` | 22 |
| `test_sessionb_translation_structure.py` | 9 |
| `test_report_publication_barrier.py` | 10 |
| `test_report_data_publication.py` | 14 |
| `test_report_draft_exposure.py` | 28 |
| `test_model_translation_workflow.py` | 13 |
| `test_exec_brief.py` | 20 |
| `test_exec_brief_sim_disclosure.py` | 7 |
| `test_exec_brief_generations.py` | 22 |

The final invocation used `backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py`, a fresh `--evidence-dir /private/tmp/drf-reports-complete-final-20261026`, `--allow-python-script backend/tests/test_artifact_translation_restart.py`, `-q`, and exactly the17 files above. The separate175-case SDK/official/chart/legacy-reader verification and its one explicit-child rerun remain recorded above; relevant brief cases are now rerun within401 on current bytes.

All known executive-brief findings are closed: admitted generation Markdown and forecast assets feed the brief; question/title uses admitted translated display or target H1; derived caches bind source/generation/content/figures; snapshot policy revocation is rejected; the fallback uses the correct image archive; brief PDFs pass the existing content gate before publication; failed replacements preserve prior files; brief/digest delivery returns verified bytes rather than reopening mutable paths. Normal and forced primary-language structured repair are also verified without translating the canonical body or demanding a nonexistent same-language variant. Independent review closed all four P2 findings and the verified-byte delivery race. No baseline path-migration failure remains.

The native final evidence remains `/private/tmp/drf-native-pdf-20261026-10/`, with its exact command and limits in `worker-native-pdf.md`: actual English4-page and Mandarin3-page exports, cache reuse,120 row/value pairs each across3 longtable pages, figure, footnotes, citations, Chinese/symbol/link checks and all7 visually inspected PNGs pass. Both native and Python isolation controls pass, with independent review closure. Native acceptance used the same final report-agent/artifact hashes below.

```text
backend/app/services/report_agent.py
13fd157ed2c7661a2099dad3b927f4173a6f8fcb9abeb242ec21b14e25588583
backend/app/services/translation/artifacts.py
b2fd31f8e3b69f43173b34253730c5f3c36efd6d7176fdad75e6cfd9bd8d3e36
backend/app/api/report.py
78f3237531717aed25683640c07f0bfa7de3317e22b91f902525b8d2bb40bc7e
backend/app/api/research.py
fd0cc80edac0bd93c14f9dc3c868f45a5777aa8c3b1270d6523668d9e3c34a38
backend/app/services/exec_brief.py
9a8ac9a1f6d792f936005da1e393aa994cd53ba33c08ca9b2aa95d7e2add67f1
```

### Final handoff prompt

> Integrate the frozen401-case report/dossier/PDF/brief slice with the parent core, overlay and frontend work. Verify the five production hashes above and the final native receipt before the parent-wide gate. The former executive-brief literal-sidecar gap is fixed and reviewed. Preserve the baseline dirty tree and saved reports. This worker performed no live provider call, production saved-data mutation, service restart or commit; activation, observed live recovery and source delivery remain the parent's separately authorized steps. No additional worker implementation or verification task is pending.

- 2026-10-26: Completed the executive-brief extension and all known review corrections; final combined401-case gate passed on stable30-file hashes. Final native bilingual/visual acceptance passed on the same renderer. Marked assigned scope complete and frozen for parent integration/delivery.

- 2026-10-26: Marked scoped adapter work complete after343-case frozen acceptance. Recorded every suite/count, guard events, source hashes, review closure and parent-only remaining gates. The native helper's brief removal was immediately reversed per the latest user direction and its ownership handed to the native verifier. No commit, provider call, production saved-data mutation or service restart was performed. Additional parent-requested executive-brief/SDK/official-data/chart-reader compatibility gate is running.
- 2026-10-26: Completed the additional175-case affected-reader coverage across the174-pass initial run and1-pass explicit-child rerun. Recorded the invocation mistake and preserved the failed receipt. Production hashes remain frozen; native harness ownership belongs to the dedicated verifier.
- 2026-10-26: Native validation found the short-script contiguous-body defect; corrected it with positive/negative real-PDF tests and42-case focused acceptance, bumped the renderer cache version and sent the new frozen hash to the native verifier.
- 2026-10-26: Full combined suite passed347 on the corrected frozen renderer, all26 pre/post hashes unchanged; current acceptance supersedes the historical343-case result.
- 2026-10-26: Independent narrow review closed the validator change. Native owner confirmed actual en/zh exports both admitted on the corrected hash; final native harness rerun/visual result remains with its owner.
