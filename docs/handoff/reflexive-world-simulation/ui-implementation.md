# World simulation UI implementation

**Status:** Complete for this UI implementation slice; local verification and independent review passed. Coordinator component/browser verification is recorded in browser-evidence/receipt.json; a full live research-page pipeline browser run is not claimed. **Started:** 2026-10-16 UTC. **Updated:** 2026-10-16T16:03:00Z.

## Request and ownership

Implement the approved M4 world-v1 reader in the existing research simulation view. Own only SimulationView.vue, the new WorldSimulationView.vue, simulation.js, the new worldSimulationView.js helper, world-simulation*.test.mjs tests, and this record. Other workers own the backend and shared contracts. No commits, dependency installs, lock changes, default-engine promotion, or edits to other routes. The existing PLANS.md and implementation-approval.json authorize this slice.

## Requirements and acceptance

| Requirement | Scenario and evidence |
| --- | --- |
| Saved engine routing | Real SimulationView setup selects world-v1 only from saved state; missing historical pin selects legacy; failures/unknown pins never fall back. |
| World presentation | Real compiled template renders metrics/accounts/rules/relations, exact quantities/units, unknowns/status, decisions and causal references, commitments/interactions, assumptions and labeled private modeled states. |
| Async identity | Deferred API calls exercise simulation and view A→B→A, generation/round changes, stale success/error envelopes, rejection, refresh and disposal. |
| Revision binding | Validate response simulation/generation/view/actor/round and revision; cursor conflicts require explicit refresh without an unbounded retry loop. |
| Accessibility/localization | Render EN/ZH, semantic labeled controls, keyboard tab navigation and escaped generated content. |
| Integration | Reuse original checkout dependencies in an isolated temporary copy; run real Vue component tests and production build. Coordinator performs browser verification later. |

## Plan and progress

1. Read results.py, the world endpoint and saved lifecycle pins; inspect existing UI and tests. Done.
2. Add a bounded request epoch and projection helper, a world API GET, and an engine-aware parent branch. Done.
3. Implement the localized world view and focused regression/component tests. Done; all 24 focused checks passed after review fixes.
4. Run targeted tests/build, request independent review, and record outcomes and integration limits. Done. Final build passed; initial independent review findings fixed with red/green evidence, and the reviewer confirmed both fixes with no remaining concrete defects.

## Findings and decisions

- The API returns `{success,data}` where data uses `world-result/v1` and `engine: world-v1`. Each response binds one head revision and one selected-round revision. Actor decisions are private; public responses intentionally omit them.
- Public results contain no complete actor roster. The actor view will accept an explicit actor ID and suggest only IDs already visible in the selected projection; it will not fetch analyst data to populate a public selector.
- SimulationView has one caller, ResearchView.vue. The active router redirects removed legacy simulation URLs to research. Direct world routes would require a coordinator decision outside this ownership scope.
- There are existing unrelated backend and documentation edits. They remain owned by other workers.
- The worktree has no frontend/node_modules. The original checkout has existing Vue/Vite dependencies; validation will reuse them without changing repository dependency files.
- Each load owns one AbortController. Starting another load cancels its predecessor; only the current ticket may write success, error, or loading state. Synchronous Vue watchers invalidate same-tick A→B→A transitions. Unmount cancels the last ticket. All requests from this parent and world reader have a 20-second transport timeout. There is no automatic world polling or conflict retry loop; explicit refresh reads the latest head and clears the revision cursor.
- The world reader verifies simulation, generation, engine, schema, view, actor, head revision and selected round before displaying data. A generation first learned from a response remains pinned until the input identity changes. Selected state is never reconstructed from trajectory data.
- No backend/API/result schema changed. Added `getWorldSimulation(simulationId, query, options)` mapping actorId to actor_id, preserving round zero and omitting irrelevant actor parameters. Existing read helpers accept an optional final request-options argument without changing old call forms.
- The old social template and styles are retained. Social requests run only after saved state admits oasis-legacy; an absent historical pin is legacy, but unknown/empty pins, saved-state errors, or conflicting runner pins fail closed.
- Claim evidence refs are structured objects in compiler.py, whereas scenario/event refs are strings. The UI renders actor/claim references and report spans explicitly, without displaying hashes or object coercions. Assumptions have their own declared identity/description and do not require a fabricated basis.

## Issues and recovery

Independent review found two P2 issues: actor suggestions retained later-round identifiers during an earlier-round request, and causal joins scanned all cumulative events/resolutions for every intent. Both were reproduced before fixing in `review-red.log` (two failing tests, including 4,000,000 event-reference reads for 2,000 intents). Suggestions now clear with every invalidated result, including failed round loads. Causal joins use per-response indexes, with an operation-count regression budget instead of a timing-dependent test; suggestions reuse the computed projection. Browser verification is explicitly assigned to the coordinator. Rules and relations do not declare units in the frozen contract, so they display “Not applicable”; missing metric/account units display “Unknown”.

## Verification and remaining work

Final focused check: `node --test tests/world-simulation.test.mjs` passed **24/24**, zero failed/skipped, on Node 22.22.3. These execute the actual compiled script setup and templates with Vue reactivity and SSR, inject API transport and lifecycle hooks, and stub the world child in parent routing tests. They are not browser/DOM acceptance. Cases cover exact decimal/zero/false/unknown projection; claim/span references; public/actor isolation; run/generation/view/actor/round/revision validation; run/view/actor/round A→B→A success, failure envelopes and rejection; current HTTP409 and timeout; explicit cursor refresh; cancellation/unmount/empty identity; legacy engine/platform preservation; semantic EN/ZH rendering, escaped content and keyboard-handler state; stale round suggestions; and linear cumulative causal joins.

Final production check: `npm run build` passed with Vite 7.2.7, **703 transformed modules**, in 2.47s. Entry JS is 427.42 kB / 153.35 kB gzip. `git diff --check` passed for tracked owned changes. No application dependency or lock files were changed, no packages were installed, and no commits were made.

Validation runs in `/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/world-ui-validation-qgmzhbvs/frontend`, an isolated frontend copy with node_modules symlinked to `/Users/rogerlin/Downloads/DeepResearchForecast/frontend/node_modules`. Evidence in its parent directory: `world-tests.log` (final 24-pass TAP), `review-red.log` (both review findings reproduced), `build.log`, and `source-hashes.json`. Current worktree source hashes were compared against the tested/built copy and matched:

| Owned source | SHA-256 |
| --- | --- |
| frontend/src/components/research/SimulationView.vue | `6cfc7141aba01767e89d8129b1c392671e90cea7e98128cd544beb19f70fa68d` |
| frontend/src/components/research/WorldSimulationView.vue | `e95be7d1ba19bcffbe3e2f61e0e9f319d50bfae9d1aa8c979a14081e81cd469a` |
| frontend/src/api/simulation.js | `c4fcb83e120f0817c59b89a9642c6ff5019587a25452008a30ac5b7a746ba6c7` |
| frontend/src/utils/worldSimulationView.js | `7cb145b4c008f85e7d1323a32beda6604f353c6cb696bf4bff86bebd848e3435` |
| frontend/tests/world-simulation.test.mjs | `ce64b1055b11c3db9aba52d67d03ae932cbfaa4e2f9a07aa810aafeb22c2ce03` |

### Coordinator handoff and remaining checks

Independent reviewer Carson (`01a1456c-a845-7c13-927c-a7ddd385afe6`) performed read-only review, inspected red/green logs, and compared reviewed component/helper/test hashes with the validation copy. Final assessment: both P2 findings resolved; no remaining concrete defects in the reviewed changes. The reviewer did not independently rerun builds/tests or perform browser/backend execution.

Browser verification remains coordinator-owned: open a saved world run through ResearchView's Simulation tab and compare the rendered selected round to the endpoint's same committed revision. Exercise public→actor→analyst visibility, changing round while requests are delayed/rejected, explicit refresh after HTTP409, parent run switching while the world child is pending, actual focus movement via arrows/Home/End and causal links, hidden-panel tab order, narrow-screen table scrolling, and a saved legacy run's unchanged social feed. Verify any stopped/failed world lifecycle status in the surrounding research flow separately; this reader labels committed progress and does not infer runner liveness.

There is no dedicated active simulation route: `frontend/src/router/index.js` redirects removed legacy routes, and `frontend/src/views/ResearchView.vue:218` is the only SimulationView caller. Direct world links or new-route navigation need an explicit integration decision outside this slice. Public results do not expose a full actor roster, so actor IDs are entered explicitly with suggestions restricted to the accepted projection. No analyst request is made to populate public choices. M5 default-engine promotion remains outside this work.

**Resume prompt:** “Read ui-implementation.md and the shared handoff, verify the recorded source hashes, run coordinator browser acceptance against a saved world-v1 run and a saved oasis-legacy run, and record DOM/focus/API fidelity evidence. Preserve other workers' changes, the frozen world result/API contracts, and the existing default-engine admission. Do not infer browser acceptance from the 24 local SSR/reactivity checks.”

## Updates

- 2026-10-16 UTC: Created this bounded continuity record after reading the approved contracts and repository handoff.
- 2026-10-16 UTC: Implemented the world reader, saved-engine dispatch, bounded request invalidation and first 18 passing component/projection/API checks. Initial production build passed. Added structured evidence-reference and legacy cancellation refinements during self-review; independent reviewer is checking the final boundaries.
- 2026-10-16 UTC: Expanded suite passed 22 checks. Independent reviewer then identified stale round suggestions and quadratic causal joins. Added two failing regression scenarios before applying fixes; final checks and review confirmation follow.
- 2026-10-16T16:01:18Z: Final 24 checks and production build passed after both fixes. Recorded source hashes, isolated validation evidence and coordinator browser/integration handoff.
- 2026-10-16T16:03:00Z: Independent reviewer confirmed both fixes and the matching tested sources; closed this implementation slice with browser acceptance explicitly assigned to the coordinator.

- 2026-10-16T18:19:35.711671+00:00: Coordinator source hashes still match all five accepted UI files. Browser fixture acceptance is complete with scope/limits in browser-evidence/receipt.json. The broader historical suggested browser checklist remains a possible production follow-up, not a claim that every item was executed.
