# Fresh simulation selection and readiness — frontend handoff

**Last updated (UTC):** 2026-10-17T15:02:31Z
**Status:** Frontend SFC/API, production build, and bounded source-review gates closed on frozen sources. Browser validation has not been executed and remains parent-owned.
**Scope:** Only `frontend/src/views/ResearchView.vue`, `frontend/src/api/research.js`, `frontend/tests/researchWorldAdmission.test.mjs`, and this file are owned by this slice.

## Request and contract

Implement the authorized fresh-admission UI against [default-api-contract.md](default-api-contract.md). The server default remains legacy until the parent completes the release gates. Existing pipeline viewing continues to use saved simulation data. No backend changes, test/build/browser/provider execution, commits, or delegation are authorized in this slice. This scoped file serves as the working handoff because the shared handoff and other files are outside ownership.

## Plan and acceptance evidence

| Requirement | Implementation and authored acceptance check |
| --- | --- |
| Server default, world, and social legacy choices | Render the real ResearchView SFC with all three options; verify the effective engine comes from preflight. |
| Backward-compatible preflight API | Capture actual API adapter calls for no arguments, mode-only calls, and optional model/engine parameters. |
| Recheck mode, model, engine, and provider changes | Exercise actual setup watchers and settings callback with deferred API responses. |
| Prevent stale A–B–A readiness | Resolve/reject earlier requests after later selections and verify they cannot update readiness, effective engine, errors, or loading. |
| Block unknown/failed readiness with retry | Verify the real template's disabled launch button, checking/error states, and retry handler. |
| Keep legacy round controls and omit world rounds | Verify actual template visibility and captured launch payloads for both effective engines, including server default and research-only. |
| Send engine only when explicitly selected | Capture launch payloads and verify absence of the engine property for server default. |
| Bilingual generic simulation copy | Render English and Chinese setup text without universal OASIS wording. |

The implementation order is API compatibility, request identity and effective-engine state, template/payload wiring, then actual-SFC harness scenarios. Static parsing and diff inspection are allowed; parent execution is required before any runtime success claim.

## Findings, decisions, and API questions

- The existing view marks failed preflight fetches ready and allows launch before the first check finishes. Both paths must become blocked.
- Existing readiness only watches mode; provider changes are currently ignored. Identity must invalidate synchronously to cover same-tick A–B–A changes.
- The API contract supplies effective `simulation_engine`, `mode`, `ready`, and `errors`; no blocking API question was found during intake. The UI must not infer a missing effective engine as legacy.
- Other agents already have backend and shared-handoff changes. Those files are outside this slice and will be preserved.
- At intake, `backend/app/api/research.py` still returned only `mode`, `ready`, and `errors` in its short response. Parent integration must supply the contract's effective engine before this frontend can become ready; this is an integration dependency, not permission to infer legacy locally.
- Readiness uses monotonic request identity and synchronous watchers. Entering a saved pipeline invalidates fresh admission state without requesting preflight; returning to fresh setup checks again. Provider settings changes use the same path.
- Failed or malformed responses clear readiness and effective engine and expose a bilingual retry action. The legacy round value remains in local state when hidden, but is included only for a full run whose latest preflight confirms legacy.

## Progress and remaining work

- [x] Read the contract, current frontend flow, existing SFC harness, and shared handoff.
- [x] Implement the owned UI/API changes and review the scoped diff against the shared contract.
- [x] Author actual-SFC and API payload tests using `sfcHarness.mjs`; execution was performed by the coordinator, not this worker.
- [x] Complete static checks and record frozen source hashes below.
- [x] Parent: pass 54/54 SFC/API tests (30 new readiness scenarios plus 24 existing world UI scenarios), pass the production build, and obtain Parfit's bounded source review with no P1/P2 findings. Evidence is linked below.
- [ ] Parent: execute browser validation and complete remaining integration/release gates; decide default promotion separately.

## Verification and frozen source

The 30 authored scenarios use the existing `compileSfc` helper, real Vue reactivity, the real compiled ResearchView template, and the actual research API adapter with an injected transport. Retry and provider-event tests obtain handlers from the real rendered VNodes. API requests, storage, polling timers, and child components are isolated. No test scenarios have been executed by this worker. The coordinator's final isolated run passed all 30 corrected scenarios and 24 existing world UI scenarios; its retained receipts are linked below.

Static evidence captured at freeze:

- Vue SFC/template structure and script setup parsed without errors. `babelParse` also accepted the API and test module. Because this worktree has no frontend dependency installation, parsing used the already installed compiler at `/Users/rogerlin/Downloads/DeepResearchForecast/frontend/node_modules/@vue/compiler-sfc/dist/compiler-sfc.cjs.js` (version 3.5.25). This was parsing only, without compilation or application execution.
- `node --check frontend/src/api/research.js` and `node --check frontend/tests/researchWorldAdmission.test.mjs` exited 0 without executing either module.
- Scoped `git diff --check` exited 0 for the tracked source changes. A read-only scan found no trailing whitespace in any of the four owned files, including the new files.
- Only the four explicitly owned paths were written during implementation; this closure updates only `frontend.md`. Other agents' dirty files were left untouched. This worker installed no dependencies, ran no tests/build/browser/providers, made no commits, and delegated no agents.

| Frozen file | SHA-256 |
| --- | --- |
| `frontend/src/views/ResearchView.vue` | `0b6f4108d954147f3f9eda3f479ea7c9789b3824da202dd4390c3dfa125624c3` |
| `frontend/src/api/research.js` | `e65941c6fdefa87cbb8d3e12f60103acd5dee3df99e39959cc58cf89a56b5e57` |
| `frontend/tests/researchWorldAdmission.test.mjs` | `1eec75380407a690d216fa3736d33dac39ae8b691b611d8caacba6f458b8efda` |

This document is the fourth owned file; its final hash is reported separately to avoid self-referential hashing.

## Parent receipt and narrow correction

The coordinator's [first SFC/API receipt](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-default-ui-xd3yogqp/tests.log) records 29 passed, 1 failed, 30 total, in 498.018417 ms. The failure is the initial-readiness test's English default-option assertion: SSR emitted valid `<option value>Server default</option>`, while the assertion required `value=""`. The original test hash was `758a603e31c9e68547907bc16a33e8b169b83ecc1b6c0ea8e8d1991fe490cbe2`.

The correction changes only this test and this note. English and Chinese assertions now accept both empty-value spellings while requiring an attribute boundary, so nonempty engine values still cannot satisfy the server-default assertion. No scenarios were removed; the suite remains 30 tests. This records the lesson from the failure: assertions should validate the attribute's meaning without prescribing one valid SSR spelling.

At the correction freeze, the test passed `node --check` and `babelParse` without execution, and the two production SHA-256 values remained identical to the accepted freeze. The coordinator's subsequent rerun and build are now closed by the final receipts below; the original failed receipt remains historical evidence.

## Verified coordinator runtime and source closure

The final isolated run was `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-default-ui-final-trhhwui5`. The coordinator copied the evidence into this release-readiness directory. This worker read the retained receipts and rehashed the three owned source/test files without executing application code.

| Gate | Verified result | Retained evidence |
| --- | --- | --- |
| Actual SFC/reactivity/SSR and API adapter | 54 passed, 0 failed, 0 skipped; 30 fresh-readiness tests plus 24 existing world UI tests. TAP duration: 241.398417 ms. | [tests.log](frontend-evidence/tests.log) |
| Production frontend build | Vite 7.2.7 build passed in 1.22 seconds; 703 modules transformed. | [build.log](frontend-evidence/build.log) |
| Frozen source identity | Receipt records no source drift; all three owned source/test hashes above match the manifest and current files. | [source-hashes.json](frontend-evidence/source-hashes.json), [receipt.json](frontend-evidence/receipt.json) |
| Independent bounded source review | Parfit reported no P1/P2 findings in the bounded UI/API change. | [receipt.json](frontend-evidence/receipt.json) |

The coordinator reused existing primary-checkout `node_modules` without installing dependencies. These results close the frontend SFC/API, build, and bounded source-review gates for the frozen source. **Browser validation has not yet been executed.** It remains owned by the parent, together with backend integration, remaining release gates, and any default-promotion decision. SSR and injected-transport evidence do not establish browser interaction or live-provider behavior.

## Parent continuation

> Preserve the frozen source/test hashes and retained 54/54, build, and bounded-review receipts. Complete parent-owned backend integration and browser validation, including both effective defaults, explicit legacy/world choices, retry after failed readiness, and readiness changes on mode/model/engine/provider updates. Record browser evidence separately from the completed SSR/API gates. Any release/default promotion remains a separate parent decision after all gates; this frontend slice does not activate a default.

## Updates

- 2026-10-17: Created the scoped handoff before implementation; recorded ownership, contract, observed failure paths, acceptance scenarios, and execution restrictions.
- 2026-10-17: Implemented backward-compatible optional preflight arguments, selection/effective-engine display, fail-closed readiness, identity invalidation, generic bilingual copy, and engine-aware launch payloads. Recorded the current backend integration dependency. No runtime checks executed.
- 2026-10-17: Authored real-SFC/API scenarios for both server defaults, explicit choices, mode/model/provider changes, A–B–A races, malformed/refused responses, retry, saved-run transitions, and unmount. Static review corrected test cleanup ordering so polling cleanup occurs before restoring the document stub. The first AST parse attempt could not resolve `@vue/compiler-sfc` in this worktree; no dependencies were installed and no tests ran.
- 2026-10-17T14:48:34Z: Finished static parsing, JavaScript syntax checks, whitespace checks, and scoped source review. Recorded exact source hashes and parent continuation instructions; froze this slice with runtime verification explicitly outstanding.
- 2026-10-17T14:52:19Z: Read the coordinator's 29-pass/1-failure receipt, corrected only the default-option serialization assertion with EN/ZH coverage, and updated the test hash. AST and syntax checks passed without test execution. Refroze the test and note with both production hashes unchanged; parent rerun pending.
- 2026-10-17T15:02:31Z: Updated only this note after reading the retained final receipts: 54/54 SFC/API tests passed, production build passed in 1.22 seconds, and Parfit found no P1/P2 issues in the bounded source review. Reverified all three owned source/test hashes against the retained manifest. Frontend runtime/source closure is recorded; browser validation remains explicitly unexecuted and parent-owned. No runtime/provider execution or commit by this worker.
