# Overlay backend handoff

**Status:** Complete — scoped backend implementation and guarded acceptance; parent owns full-system acceptance and delivery. **Date:** 2026-10-26. This worker owns `artifact_translation.py`, `translation_tools.py`, graph/simulation translation routes, and overlay backend regressions. The approved architecture and integration contract govern this work. The existing dirty checkout is the baseline; no commits, saved-data edits, service restarts, or live providers were performed.

## Request and acceptance

Move actual overlay and structured-display calls to durable source/scope identities. Replace overlay-local threads and inflight state with the parent scheduler. GET remains read-only. Graph coverage includes the full source inventory and advances bounded pages. Simulation work is bound to its permitted visible projection, including the audited completed record; canonical facts and provenance remain unchanged.

| Requirement | Acceptance evidence planned |
|---|---|
| Durable identity and scheduler | Real scheduler start/poll/retry and restarted reader tests, no independent overlay worker |
| Complete graph coverage | More than 200 nodes / 400 edges, bounded progress, stable source digest and changed-revision rejection |
| Simulation privacy | Public/actor/analyst isolation, explicit projection membership, no generic hidden record scan |
| Completed record | Both engines submit visible record prose through simulation selection, preserve source bytes and typed provenance |
| Read-only consumers | GET/status/display cannot construct provider, submit, retry, or write |

## Plan and progress

1. Read design, guard, source adapters and consumers; preserve initial dirty state. Done.
2. Implement complete inventories and source/scope-bound durable pair calls. Done, including OASIS, native world-v1 and audited completed records.
3. Replace translation threads with registered shared operation handler and compatibility routes. Done; parent registers the handler at application startup.
4. Add source/revision/privacy/restart/large-inventory regressions and run the existing guarded runner. Done; final 80-case source-bound gate passed.
5. Review changed files and record exact evidence and integration limits here. Done; independent review findings closed by source inspection and targeted runtime regressions.

## Findings and decisions

The baseline truncates graph inventory at 200 nodes / 400 edges, tracks workers in `_INFLIGHT`, and caches reused visible text without a visibility-scoped pool. The new adapter must not inherit those ownership weaknesses. Existing report/dossier display call signatures stay compatible; their owning worker controls scheduling around `display_document(generate=True)`.

The guard must install before app imports: `backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir <fresh /private/tmp path> ...`. No app import has occurred outside it.

## Issues and verification

The first guarded gate passed all 10 tests in 34.06 seconds: `/private/tmp/drf-overlay-v2-first-20261026/completed.json` and `junit.xml`. It exercises the actual shared durable engine and scheduler with a scripted provider, including a 1,001-field graph in five bounded pages, no duplicate accepted-unit generation, changed graph revision/typed context, scoped simulation selectors, review-only retry, exhausted-call-budget recovery, refresh retention, cancellation, explicit size rejection, and read-only GET. The simulation projection in the privacy-selector test is a controlled source reader; real engine/record gates are still being added.

Parent supplied `publication_guard`, and overlay cache writes now share its cancellation lock. Parent also fixed explicit resume to grant an additional bounded call window while retaining lifetime attempts; the exhausted-page regression confirms 40 entries advance 18 → 36 → 40 without regenerating accepted prefixes.

Further gates: 34 compatibility cases passed (`/private/tmp/drf-overlay-compat-second-20261026`); 18 integrated cases passed in 20.70 seconds (`/private/tmp/drf-overlay-v2-integrated2-20261026`), including real native world public/actor/analyst projection, both engines' audited completed records, and two new guarded interpreters for accepted read and review-only resume; 17 selected review regressions passed (`/private/tmp/drf-overlay-review-regressions-20261026`). These are offline scripted-provider proofs only.

After parent's canonical feed URI fix, the combined gate passed **71 tests, 9 deselected, 35.45 seconds**, with no denied operations/network attempts and two allowed guarded children: `/private/tmp/drf-overlay-owned-final2-20261026`. The additional legacy simulation POST/poll/growth route case passed independently in 3.02 seconds: `/private/tmp/drf-overlay-route-final-20261026`. That test uses a declared synthetic visibility reader to isolate route/scheduler behavior; native source authority remains covered separately by the real world/OASIS/record tests.

Independent review then identified three concrete missing cases. Duplicate POST previously waited for the worker's cache lock across provider work; a separate short admission lock now checks the persisted active operation before the long worker lock. Native no-text simulation requests now persist their native-key manifest mode so the returned digest reconnects correctly. A queued refresh now records pending keys and refresh generation at POST admission, so cancellation before execution preserves a resumable intent and the old accepted text. Six focused cases pass in 2.73 seconds at `/private/tmp/drf-overlay-reviewfix-20261026`, including these fixes, existing selection growth/refresh retention, and foreign-scope receipt rejection. The earlier 71-case receipt predates these fixes; a final combined rerun is required.

The parent is adding receipt `resource_scope_sha256`. The overlay reader now rejects any present foreign binding against its exact durable resource scope. A legacy receipt without a binding can seed only through the in-process `trusted_import` capability after this adapter validates its full canonical source/visibility cache identity and exact semantic receipt. A foreign bound receipt is never rebound. Pools are separate per artifact, target, engine, adapter, source fingerprint and full context; there is no language-wide cross-view pool.

The independent reviewer also identified inherited per-entry refresh publication as incompatible with the approved preservation rule. `refresh_entries` now stages a complete replacement independently of published `entries`; ordinary resume retains those accepted candidates. Until all refresh keys pass, readers and the scoped pool retain the entire old generation. Final activation replaces the whole map atomically. The old 20-entry regression was strengthened accordingly, and a 220-entry/two-page scenario checks old-map/pool retention followed by complete activation with no duplicate refresh calls. The combined gate then passed 77 tests in 49.36 seconds at `/private/tmp/drf-overlay-owned-final3-20261026`, with zero network/denied events, two clean guarded children and no production-source drift.

A final completion-window review case required scheduled execution to consume the refresh generation persisted at admission, rather than replay a `force=True` payload. After publication succeeds but operation completion fails, explicit Retry now reconciles the accepted generation with zero extra provider calls. A superseded generation cannot overwrite a newer one. Generic job retry/cancel is registered through the parent's resource-authorizer interface: it re-resolves `_inventory`, requires the current source/view cache and current linked operation, and returns only the server-derived identity. Cross-view, forged identity and changed typed-source control requests are denied. Four focused cases pass at `/private/tmp/drf-overlay-control-reviewfix2-20261026` (5.07 seconds). The first run safely rejected a valid refresh because the new generation check preceded POST's final cache write; checking under the worker/cache lock closes that ordering race. The subsequent combined gate passed 79 cases in 50.30 seconds at `/private/tmp/drf-overlay-owned-final4-20261026` with no production-source drift.

The paired explicit-new-refresh case after that completion failure now submits a new operation when the admission generation differs from the previous terminal operation. It does not retry an old-generation payload. Both branches pass at `/private/tmp/drf-overlay-generation-reviewfix-20261026`: generic Retry makes zero additional calls and preserves the generation; explicit new Refresh performs one translation/review pair under the next generation.

## Final acceptance and source freeze

**80 passed, 9 deselected, 54.68 seconds.** Final receipt: `/private/tmp/drf-overlay-owned-final5-20261026/completed.json`; scenario results: `junit.xml` in that directory. The parent and both guarded child interpreters exited zero. Events contain only the three storage redirects and two explicitly allowed guarded child starts; no denied operations or network attempts were recorded. The 12 production/dependency hashes in `/private/tmp/drf-overlay-final5-before-hashes-20261026.json` match after the gate with no drift. Owned production source is frozen. Poincare's independent static review confirms closure of all its reported findings; its final conditional closure is backed by the passing two-branch runtime scenario.

Reproduction command:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-overlay-NEW-UNUSED-DIRECTORY \
  --allow-python-script backend/tests/test_artifact_translation_restart.py -q \
  backend/tests/test_overlay_durable_redesign.py \
  backend/tests/test_artifact_translation_restart.py \
  backend/tests/test_artifact_translation_services.py \
  backend/tests/test_artifact_translation_model.py \
  backend/tests/test_artifact_translation_review_regressions.py \
  backend/tests/test_translation_pairs_integrity.py \
  backend/tests/test_translation_pairs_admission.py \
  backend/tests/test_artifact_translation_routes.py::test_simulation_actual_post_poll_contexts_and_incremental_growth \
  -k 'not research and not forecast_api'
```

The decisive scenarios include 1,001 graph fields completed in five pages with no repeated accepted-unit generation; exact-source and visibility isolation; native and visible selection reload; immutable typed facts/provenance; real public OASIS feed/personas/world-state and native world-v1 views; audited completed records for both engines; real-process accepted reads and review-only recovery; duplicate POST during held provider work; budget exhaustion, source change, corruption repair, cancellation and queued-refresh recovery; staged 220-field refresh activation; publication-completion replay; and generic control resource authorization. The nine deselections are mixed report/research cases owned by the other adapter worker.

## Changed paths and integration contract

Production changes are confined to `backend/app/services/artifact_translation.py`, `backend/app/services/translation_tools.py`, `backend/app/api/graph.py`, and `backend/app/api/simulation.py`. Parent owns all core, generic API/app-registration and `feed_rounds.py` changes; none were edited by this worker.

Owned tests added or updated: `test_overlay_durable_redesign.py`, `test_artifact_translation_restart.py`, `test_artifact_translation_services.py`, `test_artifact_translation_model.py`, `test_artifact_translation_review_regressions.py`, `test_translation_pairs_integrity.py`, and only the first simulation scenario in `test_artifact_translation_routes.py`. `test_translation_pairs_admission.py` is exercised unchanged. Mixed report/research scenarios are intentionally outside this worker's gate.

The startup hook is `register_translation_handler()`, which registers both the scheduler handler and resource-control authorizer. Generic retry/cancel uses `{job_revision, resource: {kind, ref_id, lang, request_digest, context}}`; the supplied selection is re-resolved, never trusted as a job identity. Existing resource POST remains ordinary resume. Graph source discovery requests `slim=False` with no top-k cutoff and rejects any upstream truncated inventory explicitly.

Supported input bounds are 20,000 requested fields, 12,000,000 source characters total and 24,000 characters per atomic field. Page limits are 216 entries or 96,000 characters. Exceeding bounds is an explicit admission error; no smaller denominator is reported as complete. Browser continuation is bounded by the frontend controller and can be resumed explicitly. Offline evidence does not establish live provider quality, latency, billing, production activation, or the parent's full-system acceptance.

Scoped `git diff --check` and Python AST checks pass. Ruff passes the changed artifact adapter, graph routes and new/restart tests; whole-file lint additionally reports three pre-existing untouched warnings: simulation.py F541 at lines 1327/1635 and translation_tools.py B905 at line 312. These are recorded, not attributed to this redesign. The installed linter is `/Users/rogerlin/.pyenv/versions/3.12.6/bin/ruff`, version 0.13.3, reached through `/Users/rogerlin/.pyenv/shims/ruff`; no installation was performed.

The first combined frozen-source gate produced 70 passed / 1 failed / 9 deselected. Its new real OASIS feed case reached a denied noncanonical SQLite URI in the pre-existing `feed_rounds.load_platform_rows`, which uses `file:` plus a raw absolute path. The new owned helper already uses `Path.as_uri()`. Parent was asked to make the same narrowly scoped canonical URI fix in that unowned helper; no guard relaxation is appropriate. The retained receipt is `/private/tmp/drf-overlay-owned-final-20261026/completed.json`, with exactly one blocked SQLite URI attempt and two allowed guarded children. It is not a green acceptance receipt.

Earlier integrated red results are retained: a 12-second test polling deadline expired after 864 accepted graph entries, and a restart fixture reused an identical resource in a shared test database. The scenario bound was raised to 45 seconds with less frequent polling; restart cases now pass an isolated upload/store path into the child. Neither failure was hidden by changing production admission.

Frontend contract: simulation request digests keep the existing canonical `[kind, ref_id, lang, context, text-hash-sorted-pairs]` formula. A separate immutable selection manifest enables reload GET; output files additionally bind the full backend-visible source fingerprint, including typed facts. Misses return 404. Graph and simulation results attach `translation_job` for the bounded operation and retain top-level artifact truth. `continuation.available` is true only after a complete page with pending tail; it is false for failures, active work, and cancellation. Page bounds are 216 entries / 96,000 source characters. Record selection uses `context.surface='record'` or `view='record'` and the audited record projection.

## Remaining work and next session prompt

No scoped backend implementation work remains. Parent should preserve the final receipt/hash manifest in its durable integration evidence, run its broader cross-surface acceptance on the final coordinated bytes, and handle activation/publication separately. Any subsequent production change invalidates only the affected source-bound proof and requires the relevant regressions again. No live quality, provider availability, app restart, saved-run recovery, commit or remote-delivery claim is made by this worker.

## Updates

- 2026-10-26: Created the worker continuity record after source/contract inspection.
- 2026-10-26: Implemented durable pair/scheduler migration; coordinated source digests, record surface and continuation fields with frontend; initial 10-case guarded gate passed. Delegated the owned simulation reader extraction to Hume and independent read-only review to Poincare.
- 2026-10-26: Migrated older fixtures to explicit source authority; retained forged-text and receipt-tamper negatives. Added source-scoped reuse pools, real source-projection and process restart evidence, and final gate outcomes including the existing feed URI blocker.
- 2026-10-26: Closed independent refresh/ownership/reconnect/admission findings, integrated the parent's generic resource authorizer and receipt scope binding, passed the final 80-case gate without drift, and froze the owned production source for parent integration.
