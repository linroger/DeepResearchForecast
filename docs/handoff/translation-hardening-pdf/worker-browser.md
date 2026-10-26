# Isolated real-browser translation acceptance

**Status:** Complete. Final independent seven-surface browser acceptance passed on current verified sources. **Owner:** browser worker. **Date:** 2026-10-26.

## Scope and acceptance
Build and run actual Vue components in a browser against real Flask resource routes and durable SQLite translation persistence, with controlled source fixtures and a fake provider. Exercise dossier, forecast, graph, OASIS, world-state, world-v1 and completed record; language selection, retry, reconnect, bounded page continuation and admitted-language PDF downloads. PDF renderer fidelity is already tested separately; browser downloads may use deterministic admitted fixture PDFs and must disclose that limit.

Write ownership is only new frontend/tests/browser/*, backend/tests/fixtures/translation_browser_* scripts and this file. Frozen production files are read-only; report discovered defects before changing them. Existing services, saved data and real providers remain outside the fixture. All runtime outputs, screenshots and logs go under a new disposable evidence root.

## Plan and boundary
Install a subclass of the existing main_offline guard before app imports. Preserve filesystem/credential/subprocess/outbound-denial behavior; allow only the exact loopback fixture listener needed for HTTP serving. Run outbound and saved-write negative controls and capture guard receipts. Use installed browser tooling, isolated Chromium profile, exact fixture origin allowlisting and real HTTP routes. Record hashes of tested production and fixture source before/after.

## Progress
- Read the frozen frontend handoff and current API contract. Confirmed backend job actions now require resource authority; browser tests will use resource routes.
- Found provisioned Node/npx and Playwright packages under installed global tooling; investigating the executable browser and guard bootstrap.
- No production files have been changed for this task.

## Evidence and remaining work
Guarded server, source fixtures, browser harness/scenarios and receipts are pending. Current absence of browser evidence is not a failure verdict on the frozen frontend.

## Guard and tooling checkpoint
The fixture subclasses the unchanged main_offline_pytest.Guard and admits only TCP stream construction (needed for accepted sockets) and one bind to127.0.0.1:18761. Every outbound connection, DNS query, other bind, saved-data write, external write and credential read remains denied. Seven pre-import negative controls passed at /private/tmp/drf-translation-browser-guard-20261026/completed.json. This is a trusted-process CPython audit boundary, not an OS sandbox.

Provisioned Playwright at /opt/homebrew/lib/node_modules/mcp-jobs/node_modules/playwright successfully launched the installed Google Chrome156.0.8078.47 headlessly and closed it. No dependency was installed. The browser harness builds the actual production Vue components into disposable static assets; the fixture Flask app serves those assets and its real APIs from the same loopback origin. Dedicated fixture artifacts will live under /private/tmp/drf-translation-browser-e2e-20261026.

Disjoint fixture assignments: frontend harness/browser runner, document/publication seed fixtures, and simulation/world/record source fixtures. Main owns the guard/server and evidence. Every production file remains read-only for this task; the parent continues core repairs independently.

## Browser discovery: forecast first-action admission defect
On the fresh real-API fixture, `/api/report/report_browser/translations/zh/status` returns body status=missing, can_generate=true and structured_translation.complete=false. The actual frontend normalizer therefore exposes both start=true and retry=true and the control chooses Retry. Its mutation preflight normalizes the report's metadata alone, which lacks structured state, producing start=true but retry=false. The handler rejects the offered Retry before any POST. The observed and preflight snapshots are saved at /private/tmp/drf-translation-browser-e2e-20261026/forecast-action-admission-defect.json. This is a production frontend contract mismatch; it was reported to the parent and no frozen file was edited by this worker. The browser click/inline-error capture is being recorded separately. The earlier PDF-label failure was a harness case-sensitive assertion against CSS-uppercase `DOWNLOAD ENGLISH PDF` and has been corrected in the harness.

The first debug browser smoke opened all seven real components successfully. Dossier generation failure, explicit retry, one interrupted GET, translation and both PDF downloads passed using the actual routes. These debug observations do not replace final per-surface evidence on current frozen code.

## Confirmed browser defect and authorized closure
The actual enabled Forecast Retry button was clicked in a dedicated browser probe. It displayed the inline permission error, sent only one report-metadata GET, issued zero translation POSTs, left provider call count at5 and produced zero page errors. Evidence: /private/tmp/drf-translation-browser-e2e-20261026/forecast-admission-probe1/result.json and its screenshots/network captures. This isolates the permission mismatch from the earlier whole-run browser shutdown. The user explicitly authorized unfreezing only the relevant frontend adapter/controller and regression tests to close this production defect, then rerunning the full frontend gate and independent browser cases. The adapter worker owns that correction.

## Isolation review corrections
The fixture now validates protected evidence roots before mkdir, permits only127.0.0.1:18761, hashes the model fake and primary-publication helper before import, and verifies zero active HTTP requests/live scheduler threads before clean-shutdown evidence. CLI negative controls reject a saved-data evidence root and alternate port without creating directories (cli-negative-controls.json). Existing offline runner bytes are unchanged. The OASIS SQLite compatibility adapter only canonicalizes the equivalent read-only file URI under the fixture root and still delegates to the unchanged guard; two guarded reader/control tests passed, including seven URI escape denials and refused writes.

run-all.mjs creates a new guarded backend root and Chrome process for every surface, with independent timeouts and teardown verification. This prevents parent OASIS world-state translations from making the separate WorldStatePanel failure/retry scenario vacuous. No failed or unrun surface is waived.

## Browser execution and lifetime diagnosis
The authorized Forecast adapter correction passed the full frontend495-test gate and production build. Its independent real-browser flow then passed the actual offered Retry, provider failure recovery, interrupted GET/reconnect, source/target restoration and both PDF downloads. OASIS, world-state, world-v1 and completed record also passed in independent fresh processes. Dossier passed behavior but its first receipt was rejected for concurrent backend source drift; its fresh rerun passed. These receipts are under acceptance/ and acceptance-retry1/ within the disposable evidence root.

Graph reached translated content and automatic page advancement, but the installed Google Chrome process exited cleanly during two runs. macOS unified logs for Chrome PID26432 show loginwindow issuing a force-quit callback and Chrome handling a Quit AppleEvent at2026-10-26 12:43:18 Asia/Shanghai, immediately before Playwright records exit0 at04:43:19.032UTC. The requesting client is unidentified. There was no runner signal, expired budget, JavaScript page error or preceding Playwright graceful-close marker. The graph result remains failed, not waived.

To remove the external application-lifetime interference, the existing Playwright CLI provisioned its pinned Chromium headless shell143.0.7499.4, revision1200, solely under browser-binaries/ in the disposable evidence root (plus its pinned FFMPEG asset). No repository package or user Chrome installation changed. The runner accepts its explicit absolute executable path and preserves all guards and the complete1001-entry/five-page assertion. All screenshots, downloads, traces and receipts remain version-bound; final current-source acceptance is still pending.

## Final acceptance — 2026-10-26T05:07:32.165827+00:00

The final coherent run at `/private/tmp/drf-translation-browser-e2e-20261026/final-acceptance/suite.json` reports **passed=true, acceptance_ready=true, seven of seven surfaces passed**. Each case used a fresh real Flask process, its own durable SQLite/artifact storage, a fresh Chromium headless-shell profile and the actual production Vue/API modules. No response fulfillment or frontend module replacement was used. The final source comparison rehashed every guarded source file and every frontend build input against the current checkout, with no drift. All owned fixture servers and browsers are closed.

| Surface | Browser result | Covered outcomes |
|---|---|---|
| Dossier | Passed | Source/target body, injected provider failure, offered retry, GET failure/reconnect, source restoration, English and Mandarin fixture PDFs. |
| Forecast | Passed | Actual formerly blocked Retry now reaches POST; full-state preflight, failure/reconnect, admitted target, source restoration and both PDFs. |
| Graph | Passed | Actual D3 node control/detail, retry/reconnect, all1001 entries through exactly five successful page POSTs after the initial injected failure, source restoration. |
| OASIS | Passed | Actual feed/persona language control, provider failure, retry/reconnect and source restoration; the parent starts its embedded world-state observer as well. |
| World-state | Passed | Its independent control, visible provenance text, failure/retry/reconnect and source restoration. |
| World-v1 | Passed | Actual model-assumption prose, not merely bilingual status labels; admitted response content, retry/reconnect and source restoration. |
| Completed record | Passed | Existing parent Simulation language control drives the audited record; failure/retry/reconnect and canonical source restoration. |

All seven final browser cases have zero uncaught page errors and zero unexpected out-of-origin requests. The browser egress negative request is blocked intentionally, separately counted. Each backend has exit0, identity preservation, no source drift and a quiescent-shutdown receipt with zero active requests and zero live scheduler threads. Read-only SQLite queries after process exit confirm persisted task/unit state. The OASIS injected failure also affects the embedded world-state job; that case repairs/asserts the feed control while the independent world-state case repairs/asserts the child control. Thus the OASIS fixture deliberately retains one failed child task; no claim is made that the single feed Retry atomically retries every child job.

Four actual browser downloads passed content-type, filename, explicit source/target URL, source hash, PDF-magic, extracted English/CJK body and language-marker checks. All four final page PNGs were visually inspected; no clipping or replacement glyphs were seen. They use the admitted deterministic PyMuPDF fixture renderer, so these outcomes establish real publication/export/browser transport and language selection, not production Pandoc typography or live semantic translation quality.

### Current source and artifact receipts

- [Final suite](/private/tmp/drf-translation-browser-e2e-20261026/final-acceptance/suite.json).
- [Current verification](/private/tmp/drf-translation-browser-e2e-20261026/verification.json), including per-file hashes, persisted-state counts, PDF hashes and limits.
- Final production frontend source aggregate, **52 files**: `e9d62cc6fe638621cf2f0d20afa5ea8a9da2ca0fe2210ea8501232cc9f4da417`.
- Guarded server/fixture source aggregate, **188 files**: `0f5006a7db7b8a4a278ef05986dfe800d7971523e21ce54f5a65310d5c23a3cc`.
- Browser fixture source aggregate, **12 files**: `574409ab3ebcd2d0a9eaa99d5486fc8c5e7315fb026b1a2883e8f5f34d372b87`.
- Refreshed36-file frontend handoff receipt (includes the stabilized test): `e732fcd55b661f7a2a6a1a0c71cec6574a464f9384ad55e8bb28475456de8728`.
- Chromium headless shell143.0.7499.4, Playwright revision1200, executable SHA-256: `8d6921aef8cc4c7bc48b03d4e709f9b563f8d1fd1ed08bc7fd5fd9784ffc2545`.

The source aggregate algorithm is SHA-256 over sorted path + NUL + file SHA-256 hexadecimal + newline. Source mappings and exact browser/PDF artifact paths are in verification.json. Historical failed runs remain intact, including the forecast admission reproducer and OS Quit AppleEvent evidence in graph-external-quit.log.

### Final test-only stabilization

The parent's concurrent frontend run caught a test assumption that three event-loop turns implied completed SHA-256 admission. Only `frontend/tests/forecastTranslationObserver.test.mjs` changed: the three mismatched-identity cases now await actual admitted-language/snapshot/loading state through Vue watch, then await the render tick. The five-second native timer is a failure bound, not a sleep. Source rejection, zero reconnect timers and zero paid POST assertions are unchanged. No production behavior changed.

- Full frontend suite: **495 passed, 0 failed**, 3476.050416ms, exit0. Log: `/private/tmp/drf-translation-browser-e2e-20261026/frontend-tests-stabilized.log`.
- Focused security cases under concurrent full-suite load: **48 passed out of48**,16 repetitions with four parallel processes. Summary: `/private/tmp/drf-translation-browser-e2e-20261026/focused-load/summary.json`.
- Production frontend bytes match the successful browser build exactly; [hash comparison](/private/tmp/drf-translation-browser-e2e-20261026/production-hash-after-test-only-fix.json). Browser rerun was therefore unnecessary for this test-only correction.
- Production build remains passed on identical production source, with Vite's existing >500kB chunk warning. Log: `/tmp/drf-browser-fix-frontend-build.log`.
- Whitespace/syntax checks passed. Existing main_offline runner was not edited.

### Changed files for this bounded task

New browser assets: `frontend/tests/browser/BrowserHarness.vue`, `main.js`, `index.html`, `build.mjs`, `run.mjs`, `run-all.mjs`, `run-isolated.mjs`, `probe-forecast.mjs`, and `README.md`.

New guarded fixtures: `backend/tests/fixtures/translation_browser_server.py`, `translation_browser_documents.py`, and `translation_browser_simulations.py`.

Explicitly authorized production-defect closure: `frontend/src/utils/forecastTranslationAdapter.js` and `frontend/tests/forecastTranslationObserver.test.mjs`. The latter also contains the final test-only scheduling fix. Continuity documents: this file and the refreshed frozen receipt in `worker-frontend.md`.

No commits, real provider calls, production service restarts or saved-artifact mutations were performed. No fixture/browser process remains running. There are no remaining blockers for this worker's acceptance scope.

### Reproduction

Build the harness into a new disposable directory with `node frontend/tests/browser/build.mjs --out-dir <new>/www`. Run `node frontend/tests/browser/run-all.mjs --evidence-dir <new>/suite --static-dir <new>/www --case-budget-ms 180000 --browser-executable <isolated-headless-shell>`. Port18761 must be free. Use the installed pinned Playwright headless shell recorded above to avoid the host's unrelated Google Chrome Quit AppleEvents. Every run creates new roots and retains failures; it never reuses or deletes saved production data.

### Closing update
- 2026-10-26T05:07:32.165827+00:00: Final seven-surface acceptance, four PDF downloads, current-source hash audit, persisted-state checks, clean process teardown and the495-test/48-repeat stabilization recorded. Task complete.
