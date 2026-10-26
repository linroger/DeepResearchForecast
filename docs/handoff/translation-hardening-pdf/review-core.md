# Independent durable translation core review

## Current bounded approval — 2026-10-26T04:48:54Z

**Approved for the reviewed code/comment preservation delta and export-consumer
integration on this captured snapshot.** All three additional findings below are
closed: the comment matcher no longer consumes visible text between comments,
the misplaced test assertion is now in the oversized-prose fixture, and the
reports-only dossier preflight forwards its pipeline ID.

Fresh independent guarded gates:

- `/private/tmp/drf-carrier-fixed-review-20261026/`: **130 passed in 5.52 seconds**.
  This includes 114 repository tests and 16 independent carrier controls, including
  matched-hash forged-preservation negatives and actual zero-budget execution of
  visible text/HTML between comments. Code/comment-only positives remain exact,
  make no model calls, have no semantic-review claim, and count preserved units as
  a subset of accepted units. Plain prose, mixed prose/code, visible HTML and text
  between comments cannot enter the preserved path in these exercised cases.
- `/private/tmp/drf-export-fixed-review-20261026/`: **58 passed, 2 deselected in
  2.58 seconds**. Ten independent controls include the formerly failing preflight
  case without an existing dossier language map, generation-only export forwarding,
  and corrupt/stale/tampered/changed-pointer rejection with otherwise eligible
  legacy sidecars. The two unchanged demo-asset availability checks remain the
  explicit exclusions documented below; they are not claimed as passing.
- Ruff check passed across the scoped core, exporter and reviewed test files.

All **18 captured source/test/dependency hashes matched before and after** these
gates. Exact bytes and `before.json` are retained under
`tmp/review-translation-core-20261026/carrier-export-fix-review/`; its
`verification.json` records per-suite counts, zero failures, guard receipts and
the empty drift list. Both permitted child-process controls exited 0. Guard
shutdown completed, system identity was preserved, and no blocked operations
occurred. No live provider, saved-data access or real static-site publication was
performed. Temporary exporter output existed only inside the guarded fixtures.

The original 108-case core receipt and source snapshot are preserved unchanged.
This new approval covers the stated carrier and consumer additions; it does not
reopen or approve the remaining report-worker, PDF, frontend/browser, deployment
or saved-artifact acceptance. No production or repository test files were edited
by this reviewer. Any later source/test changes need affected-case revalidation.
The blocked findings and receipts below are superseded for this snapshot and
retained as evidence history.

## Additional bounded reviews — 2026-10-26

The prior 108-case core approval and exact snapshot remain preserved below. The
user subsequently requested a separate read-only export-consumer review and a
separate review of the new code/comment preservation delta. Neither is silently
covered by the earlier freeze approval. No production or repository test files
were edited during these reviews; extra probes are private synthetic fixtures.

### Export consumers: resolver precedence passes; one adjacent preflight omission

Reviewed only `published_report_variants`, `published_dossier_variants`, the
`export_dossier` pipeline-ID forwarding change, and their immediate call sites
needed to establish consumption. The older RUNS additions were excluded.

`/private/tmp/drf-export-consumer-independent-20261026/` recorded **57 passed,
2 deselected in 2.88 seconds**: 9 independent pointer/forwarding probes, 2 new
consumer tests and 46 existing exporter cases. The two unchanged, pre-existing
demo-bundle availability checks were explicitly deselected:
`test_published_ev_markdown_assets_resolve_and_match_manifest_hashes` and
`test_every_published_demo_bundle_matches_its_manifest`. They were not altered or
counted as passing. Consumer, test and resolver dependency hashes did not drift;
the three reviewed helper AST hashes also remained stable. No blocked guard
events occurred. See `tmp/review-translation-core-20261026/export-consumer-review/`
for hashes, private probes and verification.

Both report and dossier consumers reject corrupt pointer JSON, stale source,
tampered generation bytes and pointers invalidated after initial resolution.
Each negative had an otherwise exportable legacy sidecar; temporarily removing
the v2 pointer proved that legacy fallback would genuinely succeed, then restoring
the invalid pointer proved it is blocked. The dossier forwarding probe used the
real admitted generation and captured the final writer; no real static site was
published. Model/scheduler acquisition was replaced with a failing sentinel after
fixture construction. The report publication-policy decision was controlled,
while generation/hash/source resolution remained real.

**Export P2:** `refresh_demo_reports` at
`backend/scripts/export_demo_site_data.py:895` still calls the now generation-aware
helper without `pipeline_id`. For a valid generation-only dossier with no legacy
sidecar and no existing `metadata.dossier_languages`, this preflight returns empty
and never calls `export_dossier`; therefore the correct forwarding inside
`export_dossier` is never reached. The same fixture does reach export if a previous
dossier language map exists, establishing a valid control.

Minimal owner fix: pass `pipeline_id=pipeline_id` in that preflight helper call.
No code was changed here. This is an adjacent caller integration defect, not a
failure of the three changed helpers' generation precedence. The reproduction
is `test_reports_refresh_discovers_generation_only_dossier_without_old_language_map`
in the private export probes. `/private/tmp/drf-export-preflight-review2-20261026/`
records **1 failed, 11 passed in 1.88 seconds**. Its first attempted standalone
probe invocation had a test-import collection error because the backend conftest
was not selected; the corrected run includes the new consumer test file. That
earlier collection failure is not behavioral evidence.

### Carrier delta: visible prose can still be classified as comment-only

The original unrestricted HTML-block preservation was narrowed by the parent to
code blocks and HTML comments, and the independent controls were updated to
require visible HTML to take semantic review. The current matcher in
`model_translation._immutable_carrier` uses
`(?:\s*<!--[\s\S]*?-->\s*)+`. Lazy repetition can still backtrack across the first
closing delimiter when later text prevents the full match.

**Carrier P1:** `<!-- first -->Ordinary visible English prose.<!-- second -->`
and `<!-- first --><div>Ordinary visible English prose.</div><!-- second -->`
are admitted by that regex as comment-only. Mistune retains the same-line content
in the HTML block; visible text between the two actual comments is consequently
eligible for a preserved receipt. Independent negative receipts use matching
source/target/context/structure hashes and a valid control review, so failure
reaches the carrier predicate rather than stopping at a hash mismatch.

The comment parser must stop each comment at its first legal closing delimiter
and require the remainder to consist solely of whitespace or further comments;
it must not backtrack across a closing delimiter to absorb visible prose.
Ordinary prose, mixed code/prose, standalone visible HTML, actual comments and
code-only positive controls remain in the private probe suite.

Direct execution confirms this is not limited to forged-receipt admission:
`translate_entries(NoCalls(), [("visible", source)], "zh", max_calls=0)` returns
the English source accepted with `coverage.preserved=1` and `accepted=1` for both
comment-surrounded visible-text examples. No translator or reviewer is called.
`/private/tmp/drf-carrier-visible-text-review-20261026/` records **2 failures,
38 deselected in 1.20 seconds**, no blocked guard events and completed shutdown.
The focused test is
`test_visible_text_between_comments_is_not_automatically_preserved` in the private
carrier probes. The reviewed 12 official source/test hashes still match.

`/private/tmp/drf-carrier-comments-review-20261026/` recorded **122 passed,
3 failed in 6.56 seconds**, with no drift in the 12 captured source/test files:
two matched-hash carrier-bypass negatives plus one parent test error. The parent
test `test_visible_html_prose_cannot_bypass_language_review_as_carrier` ends with
`valid_document_receipt(source, target, "zh", proof)` although `target` and `proof`
are undefined there. Remove or relocate that trailing assertion into the intended
document fixture; its NameError is a test failure separate from the production
carrier bypass. The preceding variant's misplaced assertion also rejected an
actually valid unchanged code document; historical receipts are retained.

No carrier source fixes were made by this reviewer. The exact comment-delta
manifest, private matched-hash/zero-call controls and verification are under
`tmp/review-translation-core-20261026/carrier-review/`. The original 108-case
snapshot remains unchanged. Resolve the carrier matcher and test error, then
rerun the full bounded suite; resolve the exporter preflight separately and rerun
the pointer/forwarding and refresh controls. No report/PDF/browser/overlay scope
has been reopened.

The parent-requested single trailing space on the historical engine.py:72 source
reference was removed during review finalization. No production bytes changed.

## Current freeze approval — 2026-10-26T04:22:25Z

**Approved for the bounded durable-core freeze on the captured snapshot. All eight
original findings are closed for the exercised core scenarios.** The last I3
boundary defect is resolved: `_chat` now uses compact JSON separators,
`ensure_ascii=False` and `allow_nan=False`, matching the admission estimator's
serialized character content. Preserving insertion order does not change this
additive estimator. The exact transmitted-payload regression passes unchanged;
its assertion and 16000 hard ceiling were not relaxed.

Fresh independent guarded acceptance at
`/private/tmp/drf-core-serialization-freeze-20261026/`: **108 passed in 5.39
seconds**, exit 0. Breakdown: original core 21, durable jobs 21, parent recovery
integrity 14, action admission 37, independent core review regressions 15. Both
guarded child processes exited 0. Ruff check passed on all scoped production
files and the five reviewed test files. No blocked guard events occurred;
shutdown completed and system identity variables were preserved.

All **12 scoped source/test file hashes match before and after** the run.
`tmp/review-translation-core-20261026/serialization-freeze-snapshot/manifest.json`
is the exact freeze manifest; that directory also preserves the reviewed source
bytes and `verification.json`. The guard completion and JUnit receipts are in
the evidence directory above. Subsequent edits require affected-case revalidation.

This closes C1 reference/footnote admission and ordinary repair; C2 scoped and
trusted legacy seed admission; C3 atomic candidate/review batch persistence; C4
transactional action CAS; I1 repair-count recovery; I2 unknown remote outcome
accounting; I3 first-entry/review/repair/exact-serialization input bounds; and I4
resource-admitted generic mutations. Unregistered generic operation kinds still
fail closed by design, and existing resource-specific admitted callers preserve
their explicit latest-state semantics.

No production edits were made in this final rereview. It does not approve or
reopen report/overlay workers, frontend/browser behavior, PDFs, live providers,
saved-artifact acceptance or deployment. The previous blocked verdicts below
are superseded for this exact core snapshot and retained as evidence history.

## Latest verdict — 2026-10-26T04:16:42Z

**Core freeze remains blocked only by I3's serialization mismatch.** Reviewed the
final adjacent-zip `strict=False`, equal-length receipt-zip `strict=True`, and
request-phase default binding. They introduce no new finding. The earlier empty
reference normalization is now included in acceptance, including its positive
citation-at-start control.

Fresh current-byte gate: `/private/tmp/drf-core-lint-final-rereview-20261026/`:
**107 passed, 1 failed in 7.93 seconds**. Original core 21/21, durable jobs 21/21,
parent recovery integrity 14/14, action admission 37/37, independent core review
regressions 14/15. The only failure remains
`test_hard_budget_counts_exact_serialization_at_boundary` at compact estimate
16000 versus actual transmitted-string estimate 16002. `engine.py:202/205` still
uses `canonical(payload)` while `model_translation.py:279` still uses spaced
`json.dumps(payload, ensure_ascii=False)`. Use the same serialization in both.

All 12 scoped source/test hashes matched before and after this run. Manifest,
exact source snapshot and verification summary are under
`tmp/review-translation-core-20261026/lint-final-rereview-snapshot/`. The guard
receipt records completed shutdown, preserved identity, no blocked operations,
and two permitted guarded child processes. Ruff check passed on the entire
scoped core and five reviewed test files. No production edits were made in this
rereview, and no overlay/frontend/report/browser/saved-artifact work was expanded.
Original C1/C2/C3/C4/I1/I2/I4 closure remains valid for the exercised core scenarios.
This latest entry supersedes the previous run's drift qualification and counts;
the underlying evidence history below is retained.

## 2026-10-26 bounded implementation: action admission

The user explicitly approved implementation of C4 and I4 only. Ownership is
`api/translations.py`, `scheduler.retry/cancel`, `Store.retry_task` and new
`Store.cancel_task`, new `tests/test_translation_action_admission.py`, and this
record. The parent concurrently owns all other core fixes. No other production
methods, adapters, saved data, services or Git state will be changed here.

Plan: first capture failing action tests; implement revision compare-and-swap
inside each mutation transaction and share the publication lock for retry/cancel;
require generic mutation requests to supply a positive integer revision and a
resource/view selection admitted by a registered resource resolver; then run the
guarded focused and existing durable suites. Success means stale interleavings
return 409 without changing the new task, invalid/missing authority never mutates
or dispatches, valid admitted actions work, and resource-specific callers retain
latest-state semantics when they intentionally omit `expected_revision`.

Integration interface: `api.translations.register_resource_authorizer(kind,
resolver)` registers `resolver(selection, action) -> server_identity | None`.
Resolvers MUST use their actual resource/visibility readers and current source
identity, rather than echoing client identity or reading the job ID as authority.
Generic action JSON is `{job_revision, resource: selection}`. The returned identity
must exactly match the task's stored identity. Unregistered kinds fail closed.
Existing redacted GET observation remains unchanged. Existing resource endpoints
already validating identity can use scheduler retry/cancel without a revision;
the transaction then intentionally acts on latest state. Adapter-owner registration
is the explicit integration point and is not silently inferred by this API.

Status: C4 and I4 action mutations are implemented and independently exercised by
37 passing guarded scenarios. Parent-core rereview has one remaining I3
serialization-boundary failure; see the latest evidence below. Historical
review/evidence follows unchanged.

### Action implementation result and interface

`Store.retry_task/cancel_task(task_id, *, expected_revision=None)` select and
compare revision under `BEGIN IMMEDIATE`, condition the update on that revision,
and return the transaction's resulting snapshot. A mismatch raises `stale_job`;
the generic API returns 409. Retry and cancel both acquire the same per-task
publication lock before the DB transaction. Internal validated resource callers
can intentionally omit the revision to act on latest state. Completed actions
are no-ops and do not launch the scheduler. Generic actions require positive
integer revision plus resolver-admitted resource selection; booleans, omitted
revisions, mismatched view/language/source, forged client identity, and unregistered
kinds do not mutate or dispatch. A genuinely admitted private view remains usable.

To enable generic actions for a real operation kind, its adapter owner registers
`register_resource_authorizer(kind, resolver)` during existing handler registration.
The resolver calls the actual resource/visibility reader, validates current source
and returns the exact server-derived task identity. No production adapters were
modified in this bounded change; unregistered generic kinds intentionally return
403, while existing validated resource-specific endpoints remain compatible.

Evidence: `/private/tmp/drf-action-admission-final-20261026/` records **37 passed in
1.95 seconds**, exit 0, completed shutdown, preserved identity, and no blocked
guard events. `tmp/review-translation-core-20261026/action-verification-final.json`
records owned file hashes and owned method AST hashes. Shared Store changes by
the parent to checkpoint, finish_attempt, and summary are explicitly excluded
from my write ownership. AST comparison confirms only retry/cancel changed in
the scheduler. Scoped `uv run --offline --no-sync --project backend ruff check`
passed on API/scheduler/store/action tests; format check passed on the wholly
owned API and test files. Shared files were not reformatted.

The original negative admission run at
`/private/tmp/drf-action-admission-red-20261026/` had **2 failures** because both
unregistered actions returned 200. After implementation, those cases return 403;
the valid controls exercise real store mutation. Threaded lock/CAS cases prove
one winner for two equal-revision requests, and prove revision is rechecked after
waiting for publication. No provider, real service, saved data or Git mutation ran.

### Parent-core rereview and durable regression transfer

The user authorized independent assessment of the parent fixes and durable test
transfer. Added `backend/tests/test_translation_core_review_regressions.py` rather
than depending on tmp probes. The new tests cover translation and review batch
crashes, repair-count/feedback preservation, unknown timeout consumption, resource
and visibility-bound seed admission, explicit legacy-reader imports, link and
footnote recovery with source fallback, 9,000-CJK no-call rejection, 4,000-CJK review
rejection, repair candidate cost, and legal long English sections.

Rereview `/private/tmp/drf-core-scoped-rereview1-20261026/` produced **93 passed,
1 failed in 6.04 seconds** across the new core regressions, 37 action scenarios,
existing durable tests and original core tests. The three intermediate old
durable-fixture failures from green1/green2 are no longer present after the parent
updated the seed/recovery contracts and fixtures. The new C1 test correctly
requires incomplete source fallback, retained references, rejection by the
publication receipt validator, and successful ordinary retry of only section 0.
Both link and footnote controls pass; it no longer expects a broken fallback.

**Remaining I3 blocker:** `engine.py` measures compact `canonical(payload)` but
`model_translation._chat` transmits `json.dumps(payload, ensure_ascii=False)` with
spaces. The new `test_hard_budget_counts_exact_serialization_at_boundary` finds
an input admitted at/below 16,000 by the compact estimate but dispatched above
16,000 using the actual captured system/user strings. The 6,500 soft batching
target is accepted as the declared policy; this is a separate mismatch at the
hard ceiling. Parent must use the same serialization for admission and transport.
The regression deliberately remains red. No engine/facade edits were made here.

Next bounded gate: fix serialization under parent ownership, then rerun
`test_translation_core_review_regressions.py`,
`test_translation_action_admission.py`, `test_translation_job_v2.py`, and
`test_model_translation_core.py` through the existing guarded runner with a fresh
evidence directory. This is core acceptance only, not adapter/PDF/live acceptance.

### 2026-10-26 final scoped rereview verdict

**Do not freeze yet: only I3's exact-serialization boundary remains open among the
original eight findings.** The independent combined run at
`/private/tmp/drf-core-final-rereview-20261026/` recorded **106 passed, 1 failed in
5.55 seconds**: 14 independent core regression cases passed, 13 parent recovery
cases passed, all 37 action cases passed, and both existing 21-case suites passed.
The single failing case is
`test_hard_budget_counts_exact_serialization_at_boundary`: **compact admission =
16000; actual captured request estimate = 16002; declared hard limit = 16000**.
These are the engine's own estimator units, not measured provider tokenizer usage.
Use identical serialization in the budget guard and `_chat`; do not relax the
ceiling or change the negative assertion to accept the overrun.

The passed controls close the exercised C1 link/footnote rejection plus ordinary
retry cases, C2 scoped/legacy admission, C3 candidate/review batch persistence,
C4 admitted-action CAS, I1 repair preservation, I2 uncertain-outcome accounting,
and I4 mutation authority. The 6500 soft target and 16000 hard input policy are
explicitly distinguished; first-entry, full-context, review-pair and repair-input
overruns are otherwise rejected. Source fallback remains valid and is not falsely
described as a broken target. Closure is limited to the scoped core scenarios;
worker publication, immutable-code/long-table additions, PDF, saved-artifact and
live-provider acceptance are not claimed here.

`tmp/review-translation-core-20261026/final-rereview-snapshot/` preserves the 12
source/test files and manifest before this run, plus `verification.json` with test
counts, failures, guard receipt and post-run comparison. The parent subsequently
changed only `_local_definitions` empty-result normalization and added the
citation-at-start regression in the facade/recovery test file. That delta was
inspected; it does not change either serialization path responsible for the
remaining failure. It is not covered by the 107-case run. Thus no frozen-current-
bytes or global integration acceptance is claimed. Both guarded child controls
exited 0; no blocked guard events, real providers or saved-data reads were used.

The earlier focused boundary receipt is
`/private/tmp/drf-core-budget-boundary-20261026/` (one failure, 14 deselected), which
also records the exact 16000/16002 mismatch. The parent's 92-pass receipt covers
its recovery controls but not this newly durable exact-serialization boundary.

Status: Review complete; eight unresolved findings on the R4 source snapshot.
This is the reviewer's continuity record; the parent-owned handoff and production
sources are untouched. This is not a cutover or adapter-integration acceptance.

## Scope and acceptance

Review the current bytes of `translation/{contracts,store,engine,service,scheduler}.py`,
`model_translation.py`, `api/translations.py`, and `test_translation_job_v2.py`
against approved `architecture.md` and `PLANS.md`. Report actionable correctness,
crash, ownership, source/visibility, privacy, budget, and retry defects with
source-based offline reproductions and valid controls. Adapter workers and their
unfinished implementation are excluded. No providers, saved data, service
restarts, source edits, or Git mutations are authorized.

## Procedure and evidence

1. Read design, ownership contract, scoped sources and existing tests.
2. Capture reviewed source hashes and add private, synthetic probes under
   `tmp/review-translation-core-20261026/`.
3. Execute through `backend/scripts/main_offline_pytest.py` with a fresh canonical
   `/private/tmp` evidence root. Only model transport and explicit fault injection
   are substituted; persistence, executor, parser and route code stay real.
4. Compare source hashes after the run, inspect guard/JUnit receipts and distinguish
   observed failures from static architectural gaps.
5. Record unresolved findings and the next bounded validation steps here.

Initial source manifest: `tmp/review-translation-core-20261026/source-before.json`.
Base commit: `6ab52f7746bf7ec55e9f9921c71ba4ab08e33c01`; branch:
`claude/sim-provenance-s0`. The scoped source files are untracked parent-owned work,
so a Git diff cannot represent their new bytes. The manifest binds this review.

## Progress and decisions

- Read the approved architecture, plan and integration contract, plus all scoped
  sources and tests. Read the root handoff without modifying it.
- The store separates core execution jobs from scheduler tasks. Review probes will
  check actual API observation as well as internal helper behavior.
- Suspected crash/repair and imported-receipt defects require negative/valid
  controls before becoming findings.

## Updates

- 2026-10-26: Started bounded independent review and recorded its write boundary.

## Verdict and exact evidence

The current core is not ready for the approved durability/source-scope contract.
The final guarded run reproduced eight findings with nine failing scenarios and
eight passing review controls. Existing tests passed: 21 in
`test_model_translation_core.py` and 21 in the current `test_translation_job_v2.py`.
Total: **9 failed, 50 passed in 3.62 seconds**, with no collection/setup failures.
The two actual child processes from the existing duplicate-submit test exited 0.

Evidence root: `/private/tmp/drf-core-review-20261026-r4/`.

- `completed.json` and `junit.xml` contain the final guard and test receipts.
- `reviewed-source/` preserves all eight scoped source/test files at collection.
- `tmp/review-translation-core-20261026/verification-r4.json` records the hashes,
  counts, and the additional post-run comparison with current working-tree bytes.
- `tmp/review-translation-core-20261026/test_core_review_probes.py` is the private
  reproducible probe suite. The failing assertions state the intended contract;
  they deliberately remain red. It does not change production behavior.

The guard recorded only three application storage redirects and two allowed
guarded-child launches, with no blocked events, no source drift, completed shutdown,
and preserved system identity variables. It is a CPython audit boundary, not an OS
sandbox. Model transport is synthetic; no live provider or saved data was used.

Reproduce with a **new** evidence directory:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-core-review-20261026-rerun-UNUSED \
  -q --tb=short \
  tmp/review-translation-core-20261026/test_core_review_probes.py \
  backend/tests/test_model_translation_core.py \
  backend/tests/test_translation_job_v2.py
```

The line references below apply to the R4 snapshot. Concurrent later edits require
the corresponding probes to be rerun; earlier green gates do not close these reds.

## Critical issues / P1

### C1. Whole-document structural failure is marked complete and becomes unrecoverable by ordinary Retry

**Source:** `backend/app/services/model_translation.py:336`, `:352`, `:355`, `:388`;
`backend/app/services/translation/engine.py:67`.

`translate_document` validates independent sections but sets `complete` solely
from the number of accepted sections. Reference definitions outside a section are
absent from that section's parser environment. A dropped reference-style link can
therefore look like an ordinary prose change locally, while the assembled document
loses a real link. The final whole-document check exists only in
`valid_document_receipt`, after the core has accepted every unit.

**Reproduction:** Use `## Outlook\n\nSee [policy][p].\n\n## References\n\n[p]: https://example.test/policy\n`.
The controlled translator turns the first prose line into `参见政策。`, preserving
headings and the later definition, and the reviewer returns positive verdicts.
All sections are accepted, `proof.complete` is true, but
`valid_document_receipt(source, target, "zh", proof)` is false. Ordinary retry makes
**zero calls** and returns the same invalid whole-document result. This reproduces
a permanent core retry dead end even if downstream publication correctly rejects it.

**Negative:** `test_document_must_not_mark_globally_broken_references_complete`.
**Valid control:** `test_control_intact_reference_scope_is_valid` passes with the
same two-section source when the reference use is retained.

**Required change:** Carry document reference/footnote scope into unit validation
and validate assembly before declaring the document complete. Persist actionable
repair state for affected units when assembly fails, so ordinary retry can repair
the defect without regenerating unrelated admitted sections. Architecture §§3, 5,
and 9 require this.

### C2. Seed admission ignores artifact ownership and visibility scope

**Source:** `backend/app/services/translation/engine.py:72`;
`backend/app/services/model_translation.py:302`, `:309`, `:340`.

Seed reuse checks source text, language, engine, structural signature and textual
context. Neither the receipt nor the seed admission binds the original resource or
visibility identity. Creating a different destination job hash does not validate
the imported receipt's origin. The new whole-source/language/engine checks for
document proofs do not add that missing origin binding.

**Reproduction:** Obtain two valid receipts under resource A with actor visibility.
Pass those receipts as `seed` into either resource B or public visibility with
identical source text and context. Both new jobs report `reused=2` and make **zero
model calls**. This proves cross-scope admission, not an observed disclosure of
real private data; all probe text is synthetic.

**Negatives:** `test_seed_must_bind_original_resource_and_visibility[resource]`
and `[scope]`. **Valid controls:** matching seed import into an empty store succeeds;
changed textual context rejects the seed and makes two calls. Existing direct-job
identity tests also pass, showing the defect is specifically the seed bypass.

**Required change:** Bind new receipts/import envelopes to resource, scope and
validation-policy identity and compare them on admission. Legacy v1 imports need
explicit provenance from a trusted matching-resource reader rather than treating
an unscoped receipt as proof of matching origin. Preserve the approved matching
20/22 and 21/22 imports. Architecture §§2, 3 and 8 require scoped reuse.

### C3. A crash after one candidate checkpoint loses the rest of an already returned batch

**Source:** `backend/app/services/translation/engine.py:154`, `:166`, `:182`;
`backend/app/services/translation/store.py:169`.

The attempt becomes `returned` before its results are persisted. Candidates are
then saved one at a time, interleaved with parsing. A crash after the first saved
candidate leaves other already-returned entries pending, with no durable response
from which to recover them. Restart cannot recover those entries or classify this
as a still-started unknown attempt.

**Reproduction:** One fake response contains translations for a and b. Raise a
`BaseException` immediately after the real `Store.checkpoint` commits a's
`validate` state. Resume through the real public service entrypoint. It reviews a,
then retranslates **b**, which was already returned in the original response.

**Negative:** `test_crash_after_first_candidate_must_retain_whole_returned_batch`.
**Controls:** ordinary replay makes zero calls; the existing single-candidate
restart test and the positive candidate-review path pass.

**Required change:** Persist all unambiguously returned candidates and their
attempt outcome in one fenced transaction before parsing/advancing any individual
unit, or persist a replayable bounded response envelope first. Do the analogous
checkpointing for review verdicts. Architecture §§2, 4, 5 and 9 require this.

### C4. Revision admission and action mutation are not atomic

**Source:** `backend/app/api/translations.py:38`–`:46`;
`backend/app/services/translation/scheduler.py:163`;
`backend/app/services/translation/store.py:246`.

The route reads/checks a revision, then invokes a mutation that does not receive
that expected revision. Another request can cancel and retry the task between
these operations. The stale first cancellation then cancels the newly queued
attempt, even though it supplied a now-obsolete revision. The publication lock
does not protect the earlier revision read.

**Reproduction:** Read running revision 2 for request A; inject real cancellation
and `retry_task` before returning that read, advancing the task to queued revision
4; continue A's cancellation with expected revision 2. The route returns **200**
and leaves the new attempt cancelled. This is a deterministic interleaving, not
a probabilistic stress test.

**Negative:** `test_cancel_revision_check_must_be_atomic_with_mutation`.
**Valid control:** an already stale revision at the initial read returns 409 and
leaves the running task intact.

**Required change:** Pass expected revision into retry/cancel and compare it in
the same transaction as the conditional state update. For cancellation, take the
publication lock before the compare-and-mutate transaction; return typed 409 on
revision mismatch. Architecture §§2 and 6 require stale actions to be fenced.

## Important issues / P2

### I1. Crash recovery bypasses the one-content-repair counter and feedback

**Source:** `backend/app/services/translation/service.py:36`–`:39`;
`backend/app/services/translation/engine.py:112`–`:118`.

Normal validation rejection uses `repair()`, which consumes the single repair and
prepares feedback. Recovery of persisted `validate` instead changes an invalid
candidate directly to `pending`, preserving `repair_count=0`. It repeats an initial
translation without repair feedback, and then grants the normal repair again.

**Reproduction:** Source contains `[S1]`; every synthetic translation drops it.
Normal execution makes two translations. Crash immediately after the first
candidate commit and resume: total translation count becomes **three**, and the
first resumed payload lacks `repair` and previous-candidate feedback.
**Negative:** `test_crash_validation_must_not_grant_extra_content_repair`.
**Control:** `test_control_invalid_structure_gets_only_one_content_repair` passes.

**Required change:** Resume validation through the same persisted validation/error/
repair transition as uninterrupted execution, preserving already consumed repair
allowances. This is separate from the approved explicit new call-budget window;
the defect changes content-repair semantics solely because a crash occurred.

### I2. Timeout attempts lose explicit remote-outcome uncertainty

**Source:** `backend/app/services/translation/engine.py:155`–`:157`;
`backend/app/services/translation/store.py:169`–`:173`;
`backend/app/services/translation/contracts.py` (`safe_error`).

All caught exceptions finalize the attempt as `failed`. A timeout after possible
dispatch therefore has no explicit unknown remote outcome, and restart only turns
`started` rows into `unknown`. The attempt is correctly counted against budget;
the missing part is the durable uncertainty classification, not cost forgiveness.

**Reproduction:** The controlled transport records its call and raises
`TimeoutError`. The stored attempt is `failed` with code `provider_timeout`, not
an explicitly unknown remote outcome; calls used remains 1.
**Negative:** `test_timeout_attempt_must_remain_remote_outcome_unknown`.
**Controls:** existing abandoned-started-attempt and safe-error retention tests pass.

**Required change:** Separate local stage outcome from remote execution/usage
certainty, or persist an explicit `unknown` state for post-dispatch timeout and
transport ambiguity while retaining call-budget consumption. Architecture §2.8.

### I3. The token ceiling is bypassed for the first entry and does not bound repair payloads

**Source:** `backend/app/services/translation/engine.py:15`–`:31`, `:139`–`:142`.

`_batch` applies its 6500-token threshold only when `keys` is nonempty, so the first
entry is always dispatched. The separate 24000-character limit does not enforce
the estimator's token limit. Repair batching additionally omits previous candidate
and feedback size from its estimate, and the API call always uses a fixed output
limit rather than an estimated source/target budget.

**Reproduction:** A 4000-character CJK entry is admitted. The core's own estimator
measures dispatched translation/review inputs at **8000 and 16000** tokens against
the 6500 ceiling. **Negative:** `test_batch_input_estimate_respects_declared_ceiling[oversized-cjk]`.
**Valid control:** `[bounded-english]` stays within the limit.

**Required change:** Account for context, both sides of review/repair, framing and
output allowance. Split supported source blocks or reject unsupported atomic size
before admission/provider work; do not unconditionally bypass the limit for an
empty batch. Architecture §§3 and 5 require explicit token ceilings.

### I4. Generic retry/cancel bypass resource and visibility admission

**Source:** `backend/app/api/translations.py:18`–`:21`, `:38`–`:46`.

The action path resolves solely by opaque task ID and never runs a resource/scope
reader or compares caller selection/authority to stored identity. Hiding identity
and result from GET prevents direct text disclosure but does not authorize a
retry that spends budget or a cancellation that stops another view's job.

**Reproduction:** Create a failed task with actor-private scope. The bare blueprint
accepts POST retry with only its ID and `{}`, returns **200**, and requeues the task.
Dispatcher startup is stubbed for this probe; the actual storage mutation is real.
**Negative:** `test_job_id_alone_must_not_authorize_private_retry`.
**Control:** the public status does omit identity/result/private payload text.

**Qualification:** The full application has an outer loopback/API-token gate
(`backend/app/__init__.py:154`), which was checked as surrounding context. This is
not a claim of unauthenticated Internet access or observed private-text leakage.
It is the missing resource/view check explicitly required by architecture §6 and
the integration contract; that outer deployment-level gate does not perform it.

**Required change:** Resolve each task's resource through its registered scoped
access reader before GET/actions, or move mutations behind the existing scoped
resource endpoints. A job ID alone must not be the resource-authorization proof.

## Controls, refinements, and limits

- Accepted replay, exact matching seed import, mismatched textual-context rejection,
  intact whole-document references, bounded English batching, stale-at-read 409,
  private result redaction, and current task progress propagation all pass.
- The added epoch check and progress snapshot were incorporated. An earlier probe
  set only task ID and therefore failed before its intended assertion; it was fixed
  to use the real current epoch. That failure is not a finding.
- An earlier matching-seed control used `force=True`. The owner intentionally made
  refresh ignore seeds, so the control was corrected to import into an empty store
  with the same resource/scope and `force=False`. That failure is not a finding.
- The source/language/engine document-seed gate, explicit additional call-budget
  window, cumulative accounting, force behavior, cancellation/publication guard,
  progress snapshot and typed storage-unavailable handling were reviewed as
  current behavior, not reported as absent.
- This bounded review does not claim adapter publication, PDF, frontend, provider
  semantics, real process-kill crash coverage, or power-loss durability. The crash
  probes inject a terminating BaseException at actual persistence boundaries.
- No production edits, saved-data access, service restart, or Git mutations were
  made. No new quality-gate/lint changes are required from this read-only review.

## Remaining work and next-session prompt

Owner action: address C1–C4 first, then I1–I4; rerun the corresponding private
negative and valid controls through a fresh guarded evidence directory. Add stable
regressions to the owned durable suite after agreeing each contract. The review
remains blocking against the declared architecture until the negative cases pass
or an explicit design change resolves the stated requirement.

> Read `review-core.md`, the approved architecture and integration contract. Review
> the R4 source snapshots and failing probes before changing parent-owned core
> files. Preserve adapter workers and saved artifacts. Fix one contract defect at
> a time, retain valid controls, and record exact new source hashes and guarded
> receipts. Do not infer integration or live-provider acceptance from core tests.

## Closing updates

- 2026-10-26: R1/R2 retained as exploratory evidence. Concurrent parent changes
  required a fresh source capture and corrected controls; neither obsolete probe
  setup failure is included among the findings.
- 2026-10-26: R4 completed with 9 failing scenarios covering eight findings,
  8 passing review controls, and 42 passing existing tests. All scoped hashes
  matched through the acceptance run. A later facade prompt-only edit is recorded below.

- 2026-10-26: A final facade edit introduced immutable cached Markdown signatures after R3. R4 reran all 59 cases on that revision and reproduced the same nine failures with 50 passes in 3.62 seconds. No source drift was recorded during R4. At the final working-tree comparison, the facade changed again: five lines were added only to the reviewer system prompt, distinguishing warnings from material issues. That delta was inspected and changes none of the reproduced control-flow/admission defects, but it was not rerun; live semantic effects are unverified. The source references above remain bound to the preserved R4 snapshot. R1-R3 remain historical evidence.
