# Dossier translation envelope fix

**Last updated (UTC):** 2026-10-11T16:49:15Z
**Status:** Complete.

## Request and boundaries

Fix only the dossier translation response-envelope mismatch in the existing main checkout. The shared Axios response interceptor already returns the backend JSON body, and the research translation endpoints return `{ success, data: { status, available, report, ... } }`. At intake, the component read `res.data.data` for both GET and POST. All other concurrent changes must be preserved. The owned files are `DossierViewer.vue`, `researchTranslation.js`, `researchTranslation.test.mjs`, a focused `dossierTranslationEnvelope.test.mjs`, and this report. No Git operations, shared API/backend/data edits, external network, live translation requests, or dependency installation are authorized.

## Acceptance checks and plan

| Requirement | Behavioral check | Expected evidence |
| --- | --- | --- |
| Reproduce before patch | Exercise actual component translation methods with the endpoint envelope and stubbed API calls. | Failing Node regression output before any production edit. |
| Available translation | Load a verified translation and switch between source and cached target. | Correct report bytes, status, PDF availability, no redundant request. |
| Generation and polling | Submit generation and run controlled timer callbacks through component loading. | Pending source fallback, one 4000 ms poll, eventual available translation, stopped polling. |
| Failure and interruption | Return terminal statuses and reject requests. | Source fallback, retry feedback, no continuing terminal polls. |
| Report identity | Change pipeline or source while a request/poll is outstanding. | Old responses cannot populate the new report cache or overwrite its state. |
| Preserve frontend health | Run focused tests, the frontend unit suite, and an isolated build using installed dependencies. | Commands, exit codes, counts, and material warnings recorded here. |

The critical path is to compile the actual Vue script for a local behavioral harness, demonstrate the envelope failure, apply the smallest component correction, and verify cache/poll/identity behavior. Changes will be made with targeted patches so existing prediction-market and other concurrent component work remains intact. This owned report serves as the continuity record; other handoffs remain untouched.

## Findings and baseline

- `.git/HEAD` identifies `refs/heads/main`; it was read without running Git or changing repository state.
- The existing root `handoff.md` was read and describes an unrelated September research task. It will not be edited.
- `frontend/src/api/index.js` returns `response.data`; `frontend/src/api/research.js` directly returns its GET/POST promises. Backend endpoint definitions in `backend/app/api/research.py` confirm the single `data` layer.
- The component has an existing version guard for GET and poll callbacks, and clears cache/state on pipeline or source-report changes. POST currently lacks that version guard; the identity acceptance checks will establish whether a narrow matching guard is needed.
- Installed Vue compiler and Vite dependencies are available. Tests will execute production component methods with injected API/timer boundaries; they will not assert source strings or reproduce translation logic in fixtures.

Baseline SHA-256:

```text
17d8ba90036838e5e7471cf552975f6dc8f88826fa45095691f2c0c42cb24b99  frontend/src/components/research/DossierViewer.vue
789419e1d6f75a09bb492c8fc357092b9510aa2630f243daf2c54d4f8fbdf225  frontend/src/utils/researchTranslation.js
b169a0c0e109db05f17a988db5256c33175559c7eb03ac199930c7b557e14704  frontend/tests/researchTranslation.test.mjs
```

## Progress and verification

- Completed: inspected the current translation consumer and local client/backend contract; reproduced the bug with actual compiled component methods before production edits.
- Completed: changed both response reads to `res.data`, and bound POST completion/error/cleanup to the current report version using the existing GET guard pattern.
- Completed: focused red/green checks, full frontend unit suite, and isolated frontend production build.
- Completed: verified that reversing only the intended hunks in memory exactly reproduces the pre-fix component hash; all other component bytes and the existing helper/test files are preserved.
- Completed: independent read-only review found no actionable concerns in the scoped fix. The final source/test hashes still match the snapshot tested by the parent session.

All commands below ran from `/Users/rogerlin/Downloads/DeepResearchForecast/frontend` using installed dependencies.

| Stage | Command | Result |
| --- | --- | --- |
| Red, before production patch | `node --test --test-reporter=spec tests/researchTranslation.test.mjs tests/dossierTranslationEnvelope.test.mjs` | Exit 1; 21 tests, 6 passed, 15 failed, 0 skipped. |
| Green, identical regression | `node --test --test-reporter=spec tests/researchTranslation.test.mjs tests/dossierTranslationEnvelope.test.mjs` | Exit 0; 21 passed, 0 failed/skipped. |
| Full frontend unit suite | `npm run test:unit` | Exit 0; 92 passed, 0 failed/skipped. |
| Isolated production build | `npm run build -- --outDir /tmp/drf-dossier-build.3JZJEO --emptyOutDir --logLevel warn` | Exit 0; nonempty `index.html` verified, no warnings emitted. Existing `frontend/dist` was not used as output. |

Changed paths are `frontend/src/components/research/DossierViewer.vue`, the new `frontend/tests/dossierTranslationEnvelope.test.mjs`, and this report. `researchTranslation.js` and `researchTranslation.test.mjs` are unchanged. No shared API/backend/data module, other component, other handoff, or Git state was edited.

Post-fix SHA-256:

```text
057ae7b9aaf83101202c534ec853ab2ed44d52d75f5d9130a8e7ee90c581505f  frontend/src/components/research/DossierViewer.vue
0b62174d8d8867c9cc8de9db79192414951f75e4864f31131dd8b17f41ca8894  frontend/tests/dossierTranslationEnvelope.test.mjs
```

## Review concerns and practical limits

Independent reviewer `01a12bdc-4a25-7720-b4c8-522327c4034d` found no actionable correctness concerns under the supplied response contract. The reviewer confirmed the single-layer envelope, cache/source fallback, unchanged polling interval, POST success/catch/finally guards, and the behavioral harness's execution of actual production methods. The reviewer performed code inspection only; the parent session ran all recorded tests and the build.

The test executes production setup/method logic, including the actual poll callback and identity watcher; it does not mount browser DOM or invoke a real Axios transport/backend/provider. API responses use the inspected endpoint contract, and controlled timers verify the existing 4000 ms interval and poll cancellation. No external browser/network/provider, live translation request, or dependency install was used. The full unit suite's existing local dev-server smoke check is separate from translation requests. Suite/build results describe the current shared checkout and do not establish acceptance of other workers' integration changes.

Review coverage limits: direct terminal POST payloads (the inspected endpoint returns generating/available on success), stale GET rejection, and an identity change during POST's follow-up GET are not separate scenarios. The existing guarded GET catch/finally and newly guarded POST finally cover those paths on inspection. No broader status-policy or lifecycle changes were introduced.

## Remaining work and next-session prompt

No remaining work for the scoped envelope fix. Suggested integration-session prompt: "Review the dossier envelope correction in `DossierViewer.vue`, its new behavioral regression test, and this owned report. Preserve concurrent changes, rerun the recorded focused tests and frontend checks if source changes, and handle Git/integration actions under your own ownership." No commit, staging, branch, push, or issue-tracker action was taken in this task.

## Updates

- 2026-10-11T16:40:26Z: Created the owned continuity report with request, boundaries, acceptance scenarios, inspected contract evidence, and initial plan.
- 2026-10-11T16:45:47Z: Resumed under explicit user approval. The component hash still matches the baseline. Before production edits, `cd frontend && node --test --test-reporter=spec tests/researchTranslation.test.mjs tests/dossierTranslationEnvelope.test.mjs` exited 1: 21 tests, 6 passed, 15 failed, no skips. Available GET returned component status `unavailable`; available POST did not fetch its report; generating GET did not poll; late POST success/failure overwrote the new identity's state. The earlier TAP run reproduced the same 6/15 result. The new test compiles and executes the actual SFC setup with real Vue refs, computed values, watchers, renderer, i18n, and translation helper. Only API calls and timers are injected. This proves the consumer mismatch rather than testing a copied fixture implementation.
- 2026-10-11T16:46Z: Patched only the component's GET/POST envelope reads and added the existing version-guard pattern to POST success, failure, and busy cleanup. Re-ran the identical focused command: exit 0, 21 passed, 0 failed/skipped. Coverage verifies available GET display and cached switches, unavailable source fallback, pending POST deduplication, generating GET/POST polling at 4000 ms, available POST immediate GET, interrupted/failed terminal responses with issues and retry feedback, API rejections, late GET/POST results across pipeline/source changes, and canceled/dequeued old polls. The helper and its existing tests need no edits. Full suite, isolated build, and read-only review are next.
- 2026-10-11T16:47Z: `cd frontend && npm run test:unit` exited 0: 92 tests passed, 0 failed/skipped. The existing dev-server test uses temporary local stub servers and local-interface checks; no external service or translation request was used. A read-only reconstruction check reversed only the intended envelope/version-guard hunks in memory and reproduced the exact original component hash `17d8ba90036838e5e7471cf552975f6dc8f88826fa45095691f2c0c42cb24b99`, confirming every other component byte is preserved. The helper and existing helper tests still match their baseline hashes. Dispatched an independent reviewer with read-only ownership and the same network/Git restrictions. Isolated Vite build is underway.
- 2026-10-11T16:47:34Z: Isolated Vite production build exited 0 and produced a nonempty index at `/tmp/drf-dossier-build.3JZJEO/index.html`. No build warnings were emitted. Added the consolidated command/results table, exact changed paths and output hashes, and practical validation limits; independent review remains pending.
- 2026-10-11T16:49:15Z: Independent review completed without actionable findings. Recorded its inspection scope and coverage limits, verified current source/test hashes against the tested snapshot, closed the read-only reviewer, and marked this scoped fix complete. No ownership expansion occurred.
