# Independent integration-core review

Status: Focused re-review complete; all six reproduced defects are closed for the fixed source hashes recorded in the closure section below. The original red evidence is retained as history. Scope is the parent-owned contracts, sources, jobs, API, registration/configuration diff, and job tests at the approved research-pdf-export worktree. Agent, model, renderer, and UI internals are excluded. This evidence file is the review continuity record; the shared handoff remains parent-owned.

## Review brief and checks

The review checks actual source/translation admission, resource and snapshot identity, durable lifecycle/retry/cancel behavior, duplicate ownership, and completion/download evidence. Findings require a concrete source path and a guarded private-fixture reproduction, paired with a passing valid control. No application source fixes, shared saved data, provider calls, service operations, or global configuration changes are authorized.

Use the existing private backend interpreter and `backend/scripts/main_offline_pytest.py` with `-I -S -B` and a fresh canonical `/private/tmp` evidence directory. Add regressions only to `backend/tests/test_research_pdf_job_review.py`, with a bounded child fixture only if necessary. Capture exact reviewed source hashes and runner receipts. Passing synthetic transport tests establish lifecycle behavior only, not PDF quality or provider acceptance.

## Initial observations

- The branch is `codex/research-pdf-export`; the in-progress source files are untracked, so the registration/configuration changes appear in `git diff` and the new modules require direct reads.
- The supplied 11-test suite replaces `sources._locate`; its controls do not exercise actual forecast publication or dossier translation admission.
- The current contract and approved plan require unchanged sources, current admission on download, process-safe duplicate suppression, and no silent replay of ambiguous dispatch outcomes.

## Progress

- Read the scoped files, integration contract, approved plan, existing handoff, and guarded runner boundaries.
- First guarded run completed: **5 failed, 17 passed in 3.48s**. All original 11 tests passed. No collection/setup failures occurred. The six new passing controls include actual forecast publication and forked dossier translation admission/revocation, without replacing `_locate`.

## Findings reported early

1. **P1 — cancellation loses a nonretryable unknown-dispatch outcome.** `jobs.py:365` persists a worker exception only while the saved state is active. `cancel()` first changes it to cancelled with `retryable=True` (`jobs.py:396`). If the still-inflight worker subsequently returns `dispatch_unknown/retryable=False`, its result is discarded. An explicit retry enters the worker a second time. The unchanged, uncancelled control enters it once. This proves a job-layer retry barrier failure; actual provider replay is not claimed because agent/model internals are outside scope.
2. **P1 — a status read overwrites the same durable retry barrier.** `jobs.py:382-383` replaces a terminal nonretryable failure with retryable `source_changed`. Changing the private source, polling once, restoring the original bytes, and requesting retry enters the worker twice. Without the source-change poll it runs once. Source/admission freshness and attempt replay eligibility need separate persistent fields.
3. **P1 — missing input binding is accepted as a completed review.** `jobs.py:175-178` compares `.get()` values without requiring the input digest. Removing `input_sha256` from both the result and review makes `None == None` pass, resulting in `completed` and a download URL. The unchanged control completes. Required bindings must be present and valid before equality checks.
4. **P2 — agent receipt contents are never validated.** `jobs.py:173` verifies the supplied file hash and discards the bytes. A non-JSON text file with a matching supplied hash is accepted as an agent receipt and the job completes. Validate the agreed receipt schema and required job/source/policy/evidence bindings, coordinated with its owner. The test is a boundary-corruption case, not an assertion that the excluded agent currently emits this malformed file.
5. **P2 — a failed interrupted-state write leaks live ownership.** `jobs.py:238-241` acquires `.owner.lock` and calls `_finish_error()` outside a releasing `finally`. A fixture-induced `OSError` from the atomic state write leaves that lock held; an immediate independent nonblocking acquire returns `None`. The no-failure control releases it. Use exception-safe ownership until the descriptor transfers to the worker.
6. **P2 — a rejected capture strands the original source identity.** `jobs.py:268-270` first publishes `source/snapshot.json` under the job ID computed from the initial source read, then checks that the capture has that digest. A source revision between the initial read and capture returns retryable `source_changed` but retains the new snapshot under the old ID without a job record. Restoring the original report bytes and retrying always loads that incompatible snapshot at `jobs.py:264-267` and returns `export_snapshot_invalid`. The unchanged-source control queues successfully. Make capture and identity admission transactional, or remove/quarantine only the newly owned mismatched snapshot before retry; preserve established exports.

## First-run evidence

Command:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/research-pdf-job-review-20261026-a -q \
  backend/tests/test_research_pdf_jobs.py \
  backend/tests/test_research_pdf_job_review.py
```

Receipts: `/private/tmp/research-pdf-job-review-20261026-a/{completed.json,junit.xml,events-15666.jsonl}`. The completed receipt reports exit 1, completed shutdown, zero source drift, unchanged system identity, no children, and only three storage-import redirects. No audited network, credential, saved-data, or blocked operations occurred. This is a CPython audit boundary, not an OS sandbox.

Reviewed SHA-256 values (full receipt also hashes runner/tests and supporting redirected modules):

| Scoped file | SHA-256 |
|---|---|
| `contracts.py` | `a7c1da0a56536bb4a0140e375c444bf2a6aaa151dea45c5fb9d40060c44a9b14` |
| `sources.py` | `61e4eb0c1df403e447581bdd72d5458930a100c8a831725f4ee592c4861e4ae3` |
| `jobs.py` | `38e8796cb5025ae57a4f605f9db1f30e7ea75d489223d61542b042aefb87e857` |
| `api/research_pdf.py` | `9d499637e50375b8407d7f4673bde340f82c823e786d986475ec4f279ea9fbf9` |
| `app/__init__.py` | `db753519859286be365a9f9f239307f82faa5416020bc6b4a14f7f64ebde7958` |
| `app/config.py` | `e9f4ad84c124a6c90eede69eb414d7e4c70fb8541a52257a7b5bf22d8af1a2f2` |

At the original red gate, all failures were open and parent-owned. No fix or all-green regression gate was claimed at that point; the later closure below supersedes that status.

## Final reproduction and control matrix

The final test file has 14 review cases: six behavioral reds and eight passing controls. Together with all 11 original passing tests, the final guarded run reports **6 failed, 19 passed in 3.72 seconds**, with **zero setup/collection errors and zero skips**. These reds are intentionally unmarked assertions of required behavior, so the parent can use them directly while fixing production code.

| Regression suffix in `test_research_pdf_job_review.py` | Red case | Passing control / observed boundary |
|---|---|---|
| `test_unknown_dispatch_remains_nonretryable_after_cancel` | `[True]`: worker invoked twice | `[False]`: nonretryable error prevents second invocation |
| `test_source_poll_cannot_erase_unknown_dispatch_barrier` | `[True]`: changed-source GET permits later replay | `[False]`: original barrier retained |
| `test_result_requires_parseable_receipt_and_bound_input` | `[non_json_receipt]`, `[missing_input_digest]`: completion **and download** succeed | `[none]`: unchanged synthetic integration fixture completes and downloads |
| `test_failed_interrupted_state_write_releases_owner` | `[True]`: failed write retains live owner lock | `[False]`: owner lock is available after start returns |
| `test_changed_capture_does_not_poison_original_identity` | `[True]`: restored-source retry is stranded | `[False]`: original identity remains usable |
| `test_real_forecast_admission_and_revocation` | No defect observed | Actual `ReportManager.publication_status` admits current private Markdown/audit; changed Markdown is refused |
| `test_real_fork_dossier_and_translation_revocation` | No defect observed | Actual fork resolution and `_research_variant` admit the isolated existing translation; removal of its proof is refused |
| `test_separate_managers_share_duplicate_ownership_and_concurrency` | No defect observed | Independent managers share the same job/slot locks, duplicate work is suppressed, and a queued cancellation never enters its worker |

The lifecycle/receipt tests reuse the existing explicitly synthetic worker fixture and replace `_locate`; they make no semantic/visual-review claims. The two real-source controls retain `_locate` and the actual admission functions, changing only manager storage roots to private directories. The translation fixture exercises the existing legacy byte-bound admission path; it is not model-led translation acceptance. The two-manager control is in-process and does not establish process-crash behavior. No bounded child fixture was necessary.

Final command is the first-run command above with `--tb=no` and a fresh evidence directory, `/private/tmp/research-pdf-job-review-20261026-final`. Final receipts are:

- `/private/tmp/research-pdf-job-review-20261026-final/completed.json`
- `/private/tmp/research-pdf-job-review-20261026-final/junit.xml`
- `/private/tmp/research-pdf-job-review-20261026-final/events-40292.jsonl`

The final receipt has completed shutdown, exit 1 for the six assertions, unchanged system identity, no children, zero source drift, and exactly the three storage-import redirects. There were **zero audited network attempts, credential accesses, saved-data accesses, or blocked operations**. A separate post-run hash comparison matched every receipt source hash to disk. The production hashes remain the values listed above. Final review-test SHA-256 is `09ac36688ed8e55c49ec9d323a99743076f3e8bb8ad46bbc647ce76d9eb21b0c`.

Only the permitted review test and this evidence document were created by the reviewer. Production changes, commits, pushes, issue posting, shared handoff edits, global configuration changes, service operations, and other workers' internals remain outside this review. The existing in-progress worktree changes were preserved.

## Static verification and review limits

The private backend environment has no Ruff executable. The existing installed Ruff was invoked without project synchronization or network access:

```sh
uv run --no-project --offline ruff check --no-cache backend/tests/test_research_pdf_job_review.py
uv run --no-project --offline ruff format --check --no-cache --line-length 100 backend/tests/test_research_pdf_job_review.py
```

Both pass. The initial lint pass identified an imported-fixture name collision in the new test file; an explicit fixture alias resolved it, and Ruff formatted only that permitted file. The final guarded run above was taken after those edits. No dependencies were installed or application source files formatted. Contributor-wide `make check` / `make fix` were not run because this is a bounded review with concurrent owners and deliberately failing regression cases.

No additional concrete defect was established in the contract/error wrapper, API/registration/configuration diff, or the exercised source admission controls. This does not certify excluded agent/model/renderer/UI behavior, full translated-forecast coverage, native PDF quality, live provider replay, or cross-process crash recovery.

## Parent follow-up

Preserve nonretryable attempt outcomes independently of cancel/source-freshness state; require complete review bindings and an agreed agent-receipt schema; release owner locks on every failed persistence path; and recover safely from a capture whose digest differs from the selected identity. Apply source fixes in the parent-owned files, then rerun the two suites with a new guarded evidence directory and retain the current red receipts. The suite should turn green without weakening assertions or changing the valid control scenarios. Review the resulting source hashes before closing these findings.

## Updates

- 2026-10-26: Started the independent scoped review. Parent-owned production files and other workers' files are preserved.
- 2026-10-26: Recorded first guarded behavioral reds and passing controls; reported the lifecycle, receipt, and ownership defects immediately.
- 2026-10-26: Added and reproduced the source-capture identity race, confirmed actual malformed-receipt downloads, and added the independent-manager ownership/concurrency/queued-cancellation control.
- 2026-10-26: Completed scoped review after lint/format cleanup and a fresh 25-case gate: six red assertions, nineteen passes, zero source drift or audited external activity. Source fixes remain parent-owned.
- 2026-10-26: Applied the requested 100-character format to the owned test, then reran the unchanged scenarios in `research-pdf-job-review-20261026-final`: six failures and nineteen passes in 3.72s. The earlier `-b` and `-c` receipts remain preserved; `-c` took 3.77s before this formatting-only edit.

## Focused fix closure — 2026-10-26

The parent accepted all six findings, applied source fixes, and requested rechecking only those cases plus their existing valid controls. No broader scan was performed. The parent's named gate was confirmed ready before this re-review: `/private/tmp/research-pdf-job-review-fixes-20261026/completed.json` reports exit 0, completed shutdown, zero drift, and 25 tests passing in 3.714 seconds according to its JUnit receipt. This is inspected parent-run evidence, distinct from the independent run below.

The independent reviewer read only the affected job admission, persistence, worker-error, status/cancel, and snapshot-recovery paths plus the revised synthetic helper. The parent updated that helper to carry a 64-hex input digest, matching QA input binding, review policy and page verdict, and the agreed JSON agent receipt. It remains explicitly synthetic and supplies no native rendering or real model-review proof.

Independent command:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/research-pdf-job-review-independent-green-20261026 \
  -q backend/tests/test_research_pdf_job_review.py
```

Result: **14 passed in 3.32 seconds; zero failures, errors, or skips**. These are the exact six formerly failing cases and eight existing valid controls. The review test file was not edited or weakened: its SHA-256 remains `09ac36688ed8e55c49ec9d323a99743076f3e8bb8ad46bbc647ce76d9eb21b0c`, identical to the final red gate.

| Finding | Fixed behavior reviewed | Independent regression outcome |
|---|---|---|
| 1. Cancellation erased a late nonretryable outcome | The current attempt's worker error persists even when state is inactive; `replay_barrier` independently controls retry. | Cancelled and uncancelled unknown-dispatch cases each enter the worker exactly once. Closed. |
| 2. Source polling erased replay eligibility | Status freshness changes leave the separate barrier intact, and start checks it before retry. | Change/poll/restore no longer re-enters the worker; unchanged-source control remains valid. Closed. |
| 3. Missing input digest was admitted | Required result source/input/PDF digests must be 64-hex before equality checks; review acceptance uses `is True`. | Missing input binding fails and cannot download; compliant synthetic control completes and downloads. Closed. |
| 4. Non-JSON agent receipt was admitted | Receipt bytes are parsed and checked against the agreed schema, source, PDF, review, policy, skill and calls fields. | Non-JSON receipt fails and cannot download; compliant control passes. Closed. |
| 5. Interrupted-state persistence leaked the owner FD | Failure while persisting interruption explicitly releases the acquired owner descriptor. | The independent nonblocking lock probe succeeds after both injected write failure and the successful-write control. Closed. |
| 6. Rejected capture poisoned the original identity | New mismatched captures are quarantined under the owned job directory; orphan snapshot recovery is confined to the no-`job.json` branch. | Original-source restoration queues successfully after the capture race; unchanged-source control remains valid. Closed. |

The real forecast and forked dossier admission/revocation controls and the independent-manager duplicate/concurrency/queued-cancellation control also pass unchanged. Inspection confirmed the additional strict policy/page/agent binding checks described by the parent, but this bounded rerun does not claim a new exhaustive negative matrix for every field.

Independent receipts:

- `/private/tmp/research-pdf-job-review-independent-green-20261026/completed.json`
- `/private/tmp/research-pdf-job-review-independent-green-20261026/junit.xml`
- `/private/tmp/research-pdf-job-review-independent-green-20261026/events-80733.jsonl`

The completed receipt reports exit 0, completed shutdown, zero source drift, preserved system identity, no children, and exactly three storage-import redirects. There were zero audited network attempts, credential accesses, saved-data accesses, or blocked operations. A separate post-run hash comparison matched every receipt source hash to disk, and every shared recorded hash matched the parent gate.

Updated fixed-state hashes:

| File | SHA-256 |
|---|---|
| `backend/app/services/research_pdf/jobs.py` | `9d3cec839db27c0981a6e5bda47497c96f129b48c3fea13ae0e8f5be891389a8` |
| `backend/tests/test_research_pdf_jobs.py` | `4ddd5f3566b99e82043ec609362ffa66817ef177bb9bc04e5794f86ae8882f78` |
| `backend/tests/test_research_pdf_job_review.py` | `09ac36688ed8e55c49ec9d323a99743076f3e8bb8ad46bbc647ce76d9eb21b0c` |

The other scoped production hashes remain as listed in the original red evidence. This re-review changed only this evidence file. It closes the six reproduced job-core findings for these bytes, with no remaining finding from the requested focused recheck. Broader integration acceptance, live-provider behavior, native PDF quality, process-crash recovery, and other owners' internals remain outside this verdict.

- 2026-10-26: Confirmed the parent gate was complete, independently reran the unchanged 14-case review suite, verified hash equality and guard receipts, and closed all six reproduced findings for the fixed source state above.
