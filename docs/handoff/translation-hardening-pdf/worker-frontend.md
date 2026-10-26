# Frontend translation redesign handoff

**Status:** Complete for frontend implementation and installed-dependency verification; frozen for parent browser E2E. **Date:** 2026-10-26. **Owner:** frontend worker.

## Request and boundaries
Implement the approved full translation frontend redesign. Ownership is frontend/src, frontend/tests and this file. The dirty working tree is the accepted baseline. No backend edits, commits, provider calls, service restarts or saved-artifact mutations are authorized for this worker.

## Acceptance and plan
All dossier, forecast, graph, OASIS, world-state, world-v1 and completed-record controls must share one observer for selection identity, reconnect, bounded polling/backoff and explicit actions. Resource adapters retain existing routes and prefer attached translation_job summaries. Retry preserves accepted work and never requests force. Visible source inventories include provenance and tail content. Late responses must not contaminate new resources, source revisions, languages or views. Both PDF controls export the admitted displayed language, validate PDF bytes and show busy/error states.

The local critical path is the shared observer and overlay adapters. Disjoint delegated workers own ForecastReport and DossierViewer with their component tests. The frontend owner integrates graph, simulation record and simulation inventory changes, then executes installed frontend tests and production build. An independent review checks the final changes.

## Progress and evidence
- Initial inspection confirmed existing independent dossier, forecast, graph and simulation translation controllers, and an untranslated completed record.
- Read architecture.md, PLANS.md, integration-contract.md and findings.md. Existing root handoff was read and left untouched.
- Shared contract uses normalized snapshots in resource adapters and one composable; all read/reconnect paths are provider-free.

## Remaining work
Implement, integrate, verify actual control scenarios, run unit tests/build and record exact outcomes and changed files here.

## Updates
- 2026-10-26: Created worker continuity record; preserved existing dirty files and established disjoint frontend write sets.

## 2026-10-26 implementation checkpoint
The shared useTranslationJob observer now owns all translation observation, cancellation, reconnect/backoff and explicit actions. Transport compatibility normalizes attached v2 job summaries separately from admitted artifact availability. Graph and simulation page continuations require the server's continuation.available flag and measurable progress, are bounded to 20 pages, and issue ordinary force:false POSTs only within an explicit generation/refresh action. Progress includes accepted entries increasing or refresh_pending decreasing. Reload and status GET never generate work.

The overlay worker confirmed the stable selection digest algorithm and strengthened source_fingerprint to the full backend permitted projection. The frontend computes only the exact request digest, pins the returned fingerprint within an observation, and treats a missing selected cache as 404. Record requests use surface=record and the audited record revision; public/world/actor visibility remains in the context. Graph display binds each returned translation to its exact current source string, including selected detail/self-loop and full graph inventories.

Focused observer and graph scenarios passed 9/9. The first broad integration run passed 419/443 and exposed mostly stale test harness imports and retired lifecycle assertions. Subsequent focused runs passed 107/109; the two failures were a temporary start scheduling change and an async fixture timing issue, both corrected. Final tests/build and independent review are still pending; these counts are checkpoints, not completion evidence.

## Independent review and corrections
Independent frontend review identified six concrete findings: missing source-byte binding for dossier admission/export; a forecast metadata/Markdown publication race; page coverage overriding aggregate forecast coverage; untranslated `coverage.translated` counts; duplicate graph prose losing field-specific translations; and the parent whole-simulation action failing to start the visible child world-state translation. These are being fixed before the frontend is frozen. Targeted regressions cover each scenario; no backend or saved-data changes are part of these frontend corrections.

Browser E2E recommendation for the coordinating parent: use a disposable upload directory and controlled fake provider on a dedicated backend port, with the built frontend on a separate origin/port and configured API proxy. Report metadata/display states are inline in forecastTranslationObserver.test.mjs and dossierTranslationObserver.test.mjs (there is no fixtures/report/translation-*.json directory). Reuse fixtures/sim/simulation_record.en.json and simulation_record.zh.json, fixtures/world/world_state.reflexive.json, and graphTranslationObserver.test.mjs's deterministic >216-entry graph. Exercise a failed GET/reconnect, delayed old-source response, source/target toggles, all five 216-entry pages of a 1001-field inventory, public/actor visibility, completed record selection, and primary/variant PDF downloads. Parent owns isolated real-browser/provider-fixture execution; this worker does not start services.

## Final frontend freeze — 2026-10-26T04:00:43.078134+00:00

All seven translation surfaces use the same observer and shared status component. Explicit Retry keeps force=false; only explicit Refresh forces a replacement. GET-only reconnect, transient backoff, unmount/resource/source/language cancellation, monotonic job revision admission and timeout bounds are shared. Automatic continuation preserves a failing sibling without POSTing it again; only eligible batches advance. Full artifact coverage takes precedence over page job counters, including translated-count aliases and refresh_pending progress.

Dossier admission and both PDF exports are bound to the displayed source SHA-256. Forecast translated Markdown is pinned to the admitted generation and verified byte-for-byte against its expected digest before caching. Export controls identify the admitted displayed language, preserve unsuffixed primary URLs, validate MIME and PDF magic, report typed errors and reject late completions. The record uses the audited selected-period/overall projection with an opaque source seal; the existing parent language action covers either the record or visible live feed plus world-state panel.

### Verification

- `npm run test:unit` in frontend: **486 passed, 0 failed, 0 skipped**, exit 0; final run duration 2551.469375 ms. Full log: `/tmp/drf-frontend-translation-tests.log` (SHA-256 `17b17c7c72fd521341496bd9effa88e974e916648a470253f3a96b1617d8f737`).
- `npm run build` in frontend: **passed**, exit 0, 3.19 seconds. Log: `/tmp/drf-frontend-translation-build.log` (SHA-256 `fef85c7fa11dfeb7e0d8eb77d7687bf71d81f88aa7fb6fa7b726a612419e1d84`). Vite reports its >500 kB chunk warning (542.26 kB main JS; 193.14 kB gzip), with no build error. No bundle refactor was added to the translation scope.
- `git diff --check -- frontend/src frontend/tests`: passed.
- Actual mounted/compiled component regressions cover dossier/forecast controls and exports, graph summary/self-loop and full-tail paging, OASIS personas/feed, world-state provenance, world-v1 private/public scopes, completed record and parent/child action forwarding. Deferred transport scenarios prove late-response rejection, source/generation conflicts, reconnect and disposal. These are frontend transport-controlled scenarios; parent owns real browser plus isolated fake-provider backend execution.
- Independent read-only review identified six original findings, then sibling continuation and stale-revision bounds. All have source corrections and targeted regressions; the final scoped core-observer/pagination review reports no remaining blocking findings.

### Changed files owned by this worker

Production files (existing dirty contents retained as the baseline):
- `frontend/src/api/research.js`
- `frontend/src/api/report.js`
- `frontend/src/components/GraphPanel.vue`
- `frontend/src/components/TranslationJobStatus.vue`
- `frontend/src/components/research/DossierViewer.vue`
- `frontend/src/components/research/ForecastReport.vue`
- `frontend/src/components/research/SimulationRecordView.vue`
- `frontend/src/components/research/SimulationView.vue`
- `frontend/src/components/research/WorldStatePanel.vue`
- `frontend/src/components/research/WorldSimulationView.vue`
- `frontend/src/composables/useTranslationJob.js`
- `frontend/src/utils/dossierTranslationAdapter.js`
- `frontend/src/utils/forecastTranslationAdapter.js`
- `frontend/src/utils/overlayTranslation.js`
- `frontend/src/utils/pdfDownload.js`
- `frontend/src/utils/simulationRecordTranslation.js`
- `frontend/src/utils/translationJobAdapter.js`

Regression tests and harness adaptations:
- `frontend/tests/dossierOfficialData.test.mjs`
- `frontend/tests/dossierTranslationEnvelope.test.mjs`
- `frontend/tests/dossierTranslationObserver.test.mjs`
- `frontend/tests/forecastReportOfficialData.test.mjs`
- `frontend/tests/forecastReportPartialTranslation.test.mjs`
- `frontend/tests/forecastReportProvenance.test.mjs`
- `frontend/tests/forecastTranslationObserver.test.mjs`
- `frontend/tests/graphTranslationObserver.test.mjs`
- `frontend/tests/reportMandarinConsumers.test.mjs`
- `frontend/tests/researchWorldAdmission.test.mjs`
- `frontend/tests/sfcHarness.mjs`
- `frontend/tests/simulationMandarinTranslation.test.mjs`
- `frontend/tests/simulationRecordTranslation.test.mjs`
- `frontend/tests/simulationRecordView.test.mjs`
- `frontend/tests/simulationTranslationHarness.mjs`
- `frontend/tests/sourceContextPanel.test.mjs`
- `frontend/tests/world-simulation.test.mjs`
- `frontend/tests/worldStatePanel.test.mjs`
- `frontend/tests/translationJobObserver.test.mjs`

### Frozen-byte receipt

The 36 files listed above have aggregate SHA-256 `d9c6ba40c4cd6d4a05dacf6838d3958e93721b9f1aba247fa2cf84fcb0b8ef7e`. Reproduce by sorting their repository-relative paths, concatenating each path, a NUL byte, its file SHA-256 hex digest, and a newline; hash the resulting UTF-8 bytes. This receipt covers worker-owned production/test changes, not unrelated pre-existing dirty paths or the independently changing backend.

No frontend code work remains for this worker. Parent's next step is isolated browser E2E and coordinated backend/frontend acceptance. No commits, service restarts, live-provider calls or saved-artifact mutations were performed by this worker. The checkout intentionally retains all pre-existing and concurrent dirty changes.

### Next-session prompt

> Continue from the frozen frontend receipt in worker-frontend.md. Verify the 36-file aggregate hash before browser E2E. Use a disposable backend upload root and controlled provider, and route the frontend API to that isolated backend rather than the default Vite proxy on5001. Exercise all translation controls, selected record/live views, full inventory continuation, source/generation conflicts, reconnect and actual primary/translated PDF downloads. Keep backend and saved-artifact ownership boundaries intact. The frontend unit gate is486/486 and the production build passes; report live/browser outcomes separately from these transport-controlled regressions.

### Closing updates
- 2026-10-26T04:00:43.078134+00:00: Recorded final486-test/build gate, independent review corrections, exact changed paths, frozen-byte receipt and parent browser-test handoff. Source and test files are frozen.

## Authorized real-browser defect closure — 2026-10-26T04:55:12.133317+00:00

The user authorized unfreezing the Forecast adapter and its actual-component regression after real browser E2E proved that a visible Retry could be rejected by a body-only preflight. `frontend/src/utils/forecastTranslationAdapter.js` now performs the same full resource/status/display read before mutation. It preserves source/generation guards, rejects freshly revoked metadata or status permissions, and reconnects read-only after preflight transport failures. `frontend/tests/forecastTranslationObserver.test.mjs` adds the real missing-body/partial-structured response shape and late/revoked/failing preflight checks. No control is bypassed by the browser harness.

The full frontend gate now passes **495 tests, 0 failures** (2247.487125 ms), and `npm run build` passes (2.00 seconds), retaining only Vite's chunk-size warning. Logs: `/tmp/drf-browser-fix-frontend-tests.log` and `/tmp/drf-browser-fix-frontend-build.log`. The actual Forecast browser scenario passes its offered Retry, interrupted GET, source/target restoration and both PDF downloads; evidence is in `worker-browser.md`.

The refreshed aggregate SHA-256 for the same36 owned frontend files is **`3d1e716a446763e1b90f4036fbebf3a3dc04e8f33e50a2d5d7c6cae2eb11b681`**, using the existing path-NUL-filehash-newline algorithm. This supersedes the earlier frozen receipt for current integration. Production frontend files are frozen again. New browser fixture files and backend source-version receipts are recorded separately in `worker-browser.md`.

## Test-only admission scheduling stabilization — 2026-10-26T05:07:32.165827+00:00

A concurrent parent run exposed a fixed-event-loop-tick assumption in the three mismatched-job-identity tests. Only `frontend/tests/forecastTranslationObserver.test.mjs` was changed to await actual admitted-language/snapshot/loading state and the corresponding render tick. The negative zero-reconnect/zero-paid-work assertions remain. Full frontend suite495/495 and48/48 focused cases across16 runs/four concurrent processes pass. All52 production frontend source files exactly match the successful seven-surface real-browser build (`e9d62cc6fe638621cf2f0d20afa5ea8a9da2ca0fe2210ea8501232cc9f4da417`); no production code changed and browser rerun was unnecessary.

The latest aggregate for the same36 owned frontend files is **`e732fcd55b661f7a2a6a1a0c71cec6574a464f9384ad55e8bb28475456de8728`**, superseding the prior test-inclusive receipt. Detailed evidence and the real-browser seven-of-seven acceptance are in worker-browser.md and `/private/tmp/drf-translation-browser-e2e-20261026/verification.json`.
