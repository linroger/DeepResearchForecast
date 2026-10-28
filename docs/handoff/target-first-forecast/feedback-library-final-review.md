# Feedback and library final independent review

**Started (UTC):** 2026-10-28 03:52:04
**Last updated (UTC):** 2026-10-28 04:15:34
**Status:** FBL-1 repaired and independently verified; accepted production/test freeze intact. Coordinator confirms Issue 10 is synced; no unresolved tracker action remains.

The original review and its ownership/verdict below are retained as historical evidence. The final section, **Assigned FBL-1 repair**, records the subsequent authorization, current three-file ownership, implementation, and repair verification.

## Review brief and ownership

Review `forecast_feedback.py`, `forecast_inputs_health.py`, `forecast_library.py`, the production calibration change in `forecast_ledger.py`, `resolution_autorun.py`, and the coordinator's manual SDK endpoint. Check actual evidence, identity, temporal ordering, prospective eligibility, and compatibility with historical publication journals. The coordinator additionally requested a valid-case library export check where source retrieval follows `case.asOf` even though the source vintage precedes that cutoff.

This document is the reviewer's only owned repository file and its continuity record. Production code, shared handoffs, tests, and other owners' reports remain unchanged. Code fixes require a specific coordinator assignment. No providers, live probes, services, scheduler activation, commits, or pushes are authorized. The primary checkout is read only; its existing interpreter runs the worktree's guarded runner.

## Acceptance checks and plan

| Requirement | Check | Evidence |
|---|---|---|
| Review exact source bytes | Capture source hashes before verification and compare afterward | External manifests and final hashes below |
| Existing contracts remain exercised | Run library, extension, input-health, ledger, feedback, SDK, and resolution suites through `main_offline_pytest.py` | Fresh completed receipt, JUnit, and guard events |
| Real-case export compatibility | Validate a case with earlier vintage and later retrieval; call the real publisher and inspect its receipt without backdating | Guarded reproduction and source references |
| Findings are reproducible | Trace any suspicious behavior through production producers and consumers and use bounded temporary probes when necessary | Exact scenario, observed result, impact, and proposed narrow repair |
| Offline limits stay explicit | Inspect child receipts, blocked operations, source drift, and preserved identity | Separate guard-attempt accounting and verdict |

Read the supplied handoff, plan, frozen interfaces, request documents, and feedback/library owner reports. Freeze sources, run the selected existing suites, investigate uncovered boundary cases, and record a source-bound verdict here. Runtime or forecasting-quality acceptance is outside this review.

## Progress and decisions

- 2026-10-28 03:52:04 UTC: Confirmed the worktree is `codex/target-first-forecast` at `6ab52f7746bf7ec55e9f9921c71ba4ab08e33c01` with extensive existing multi-owner changes. Read the owner reports; their earlier green receipts do not close this review.
- 2026-10-28 03:52:04 UTC: Current `publish_case_mechanisms` catches entry-validation failures and records skips. The requested cutoff case must therefore distinguish an existing nonfatal `entry_cutoff` skip from a propagated forecast failure and from the requested descriptive `available_after_case_cutoff` reason.
- 2026-10-28: Captured 561 Python/fixture hashes in `/private/tmp/drf-feedback-library-review-20261028-0352/source-before.json` (manifest SHA-256 `15e70718c1dcb0738d6a8abc169af056e263b2013152eaafe46e94daa74ac8da`). All six scoped Python files passed `/Users/rogerlin/.pyenv/shims/ruff check --select F,E9`.
- 2026-10-28: The existing-suite aggregate finished **278 passed, 1 failed** in 18.14 seconds, with no deselections. Evidence: `/private/tmp/drf-feedback-library-review-20261028-0352-suites/{completed.json,junit.xml}`. The additional Oddsense backtest fixture failed at `backend/tests/test_oddsense_feedback_merge.py:83` before its backtest assertion. A separate single-test run reproduced the same setup failure in 1.60 seconds. Its fixture generates article dates from wall-clock yesterday, while its client cutoff is fixed at 2026-10-21; on this review date the client correctly discards those articles. This is distinct from a feedback/library regression and remains visible as an unmodified compatibility-test failure.
- 2026-10-28: A first temporary diagnostic plugin asked pytest to collect an absolute evidence-root path; pytest attempted to list an ancestor outside the guard, which was blocked. That receipt is preserved in `/private/tmp/drf-feedback-library-review-20261028-0352-probes`. The revised plugin collects the specific evidence-root module directly and leaves the guard unchanged. Diagnostic fixture files are external to the repository; no production/test source ownership was expanded.

## Findings and verification

### Critical issues

No critical defect was reproduced in the reviewed scope.

### Important issue FBL-1: an unrelated actor claim inherits journal-outcome provenance

**Location:** `backend/app/services/forecast_library.py:287-321`, particularly the URL-only claim join at lines 304-311 and the content binding that applies only to reference classes at lines 312-321. **Status:** Open; coordinator assignment required before any code edit.

The real journal reader validates the outcome and its hashes, but an actor entry's identity and asserted behavioural record are never compared with that outcome. A fetched source with the same URL is enough for both `record_entry` and `select_entries` to accept the actor row with `provenance.basis="journal_outcome"`. Reference-class rows have an additional content-to-observation check; actor rows do not.

**Reproduction:** Register the existing named-source fixture about an Agency issuing its final rule, then settle it with the real manual-resolution API and its dated evidence. Construct an actor library entry using the genuine journal event hash and publication hash, retaining the exact genuine source URL and passage, but set `content.name="Unrelated actor"`, `content.actorClass="company"`, and `content.record="This unrelated actor honoured all of its real-world commitments."`. The write succeeds, and the actual later-case selector returns that unrelated claim. No journal bytes, event hash, URL, or passage were falsified. The claim itself is unsupported by the authenticated event.

**Evidence:** `/private/tmp/drf-feedback-library-review-20261028-0352-probes03/actor-proof-observed.json` contains the complete genuine outcome and accepted entry. Its stored ID is `fl1-14c133dcd7c97dee59cb7ef2ae1820bcd766907b31f5a027c0ebfe6105022d2a`. The diagnostic rejection assertion fails at `test_feedback_library_review_probes.py:85`; the same run's valid export, temporal-admission, nonfatal-skip, and frozen-prefix controls pass. The existing valid journal-backed actor fixture also passes in the 277-test suite.

**Impact and limits:** This is a reproduced proof-to-claim binding gap in the public actor-library write/read path. It does not show that the current mechanisms-only case exporter writes actor rows or that any runtime probability or actor policy was promoted. It must be closed before describing journal-backed actor records as authenticated real-world behavioural learning.

**Narrow proposed repair:** Refuse `journal_outcome` actor records unless the actor identity and behavioural claim are explicitly bound by the frozen outcome evidence. Requiring the retained record to be the journal's actual evidence text closes this reproduced invented-record case, but actor identity still needs an explicit binding. Until that contract exists, reject this use of `journal_outcome` rather than treating an arbitrary actor claim as verified. Preserve ordinary source-aware contextual records and inherited assumptions. Apply the same principle before supporting learned mechanism parameters from outcome proofs; a journal hash alone cannot validate a new coefficient. No broader learning feature is requested by this review.

### Additional compatibility-test issue: the Oddsense fixture has drifted with wall time

`backend/tests/test_oddsense_feedback_merge.py:77-83` supplies a fixed client cutoff of `2026-10-21`, while its imported `_articles()` fixture at `backend/tests/test_oddsense_workflow.py:76-81` generates publication timestamps from wall-clock yesterday. On 2026-10-28 those articles are dated 2026-10-27, and `deerflow_bridge/news_signals.py:898` correctly discards them as after the cutoff. The first aggregate and a separate isolated run both fail before the asserted backtest protection is exercised. This is an existing time-dependent fixture failure, not evidence that the new feedback code violates the backtest cutoff.

The coordinator can freeze the source fixture's dates within its declared capture window in a separate test-only assignment. The original red receipts remain intact; the 277-test scoped gate excludes this additional two-test module explicitly, not through a hidden deselection or test edit.

### Requested library-cutoff investigation

The proposed valid-case `entry_cutoff` forecast failure is **not reproduced for the current canonical contract**. `forecast_case._date` normalizes timezone-aware timestamps to UTC dates (`deerflow_bridge/forecast_case.py:98-108`), and `validate_case` rejects a source whose retrieval date is after `case.asOf` (`:320-334`). The publisher invokes this validator before storage (`forecast_library.py:415-419`). Two negative controls exercise both next-day UTC retrieval and a local-date timestamp whose offset moves retrieval to the next UTC day; both are rejected at canonical admission before any library directory is created.

The unchanged accepted fixture exports one public mechanism and skips its private-node mechanism. Its original retrieval time survives in the selected library row. A second valid case with a date-only publication and a retrieval timestamp on the same UTC day demonstrates the library's stricter date precision: date-only publication means end of that UTC day in the library, so it yields a nonfatal `publication_after_retrieval` skip. The publisher returns the receipt without creating an entry or raising. These controls are captured as `valid-cutoff-observed.json`, `next-day-admission-utc.json`, `next-day-admission-offset.json`, and `same-day-precision-skip.json` in the final diagnostic evidence root.

The existing `_validate(entry)` catch at `forecast_library.py:493-497` already converts ineligible entries into explicit skips; genuine filesystem and immutable-store integrity failures still propagate from `record_entry`. If canonical admission is later changed to permit source retrieval after the case cutoff, the coordinator's requested `available_after_case_cutoff` skip is an appropriate explicit reason immediately after computing availability at lines 477-478. Preserve the real timestamps and do not backdate availability. That future policy change is not required or implemented to resolve a forecast failure here.

### Positive notes and reviewed boundaries

- Manual resolution binds the forecast ID, immutable binary contract hash, exact publisher, strict boolean outcome, and ordered publication/deadline/source/retrieval/resolution times. The new SDK endpoint's success, wrong-hash, conflict, and missing-report paths reach the real journal in existing tests.
- Near-market settlement requires frozen and reobserved source terms and a terminal source state. It remains separate from exact-market scores, and disabling new admissions does not invalidate historical replay.
- Legacy publication retries and frozen prefix summaries remain readable under the existing version-1 semantics. New admission validation is kept out of the original digest/replay path (`forecast_feedback.py:250-268`). An additional diagnostic verifies an old frozen prefix after a later named-source settlement.
- Production `calibration_summary` reads the publication journal, while explicit legacy entries remain available to historical-math callers. No fresh forecasting skill or prospective lift is inferred from those scores.
- The health helper remains a pure consumer of stored status evidence. Existing cases cover missing dates, future times, failed transport, cached official series, partial requotes, and the news search-cutoff/retrieval-time distinction. Scheduler tests exercise substituted triggers and a fake clock; no production monitor or service was activated.
- Mechanism export preserves the input mechanism/parameter bases and explicit gaps. Its receipt and content IDs establish provenance and integrity, not earned confidence, a validated kernel, or permission to change estimator weights.

## Exact verification record

The final existing-suite command was:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B \
  backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-feedback-library-review-20261028-0352-scoped-final \
  --allow-python-script backend/tests/test_forecast_feedback_sdk.py -q \
  backend/tests/test_forecast_library.py \
  backend/tests/test_target_feedback_extensions.py \
  backend/tests/test_target_inputs_health_probe.py \
  backend/tests/test_forecast_ledger.py \
  backend/tests/test_forecast_feedback_ledger.py \
  backend/tests/test_forecast_feedback_workflow.py \
  backend/tests/test_forecast_feedback_sdk.py \
  backend/tests/test_resolution_autorun.py \
  backend/tests/test_resolution_monitor.py
```

**Result: 277 passed in 17.50 seconds, exit 0.** The respective module counts are 48, 42, 32, 9, 82, 7, 38, 6, and 13. The explicitly registered SDK fixture SHA-256 is `65feee980bfa286d52836c37a57b2f75b7f2e6db25a03a554139038c47527fec`. The unchanged runner SHA-256 is `5046cf820fa468d8e8ffb2e3fdade1d20fca2f0bd56ee15eabdff51c223c02be`.

| Run suffix after `/private/tmp/drf-feedback-library-review-20261028-0352-` | Result | Meaning |
|---|---|---|
| `suites` | 278 passed, 1 failed, 18.14 s, exit 1 | Requested suites plus two additional Oddsense compatibility cases; dated-fixture failure preserved |
| `oddsense-isolated` | 1 failed, 1.60 s, exit 1 | Same fixture failure independently reproduced |
| `probes` | Collection error, exit 4 | Reviewer harness attempted an ancestor directory listing; guard denied it |
| `probes02` | 4 passed, 1 failed, 1.53 s, exit 1 | Corrected collection; reviewer assumption that offset timestamps bypass UTC-date admission was disproved |
| `probes03` | 6 passed, 1 intentional rejection regression failed, 1.40 s, exit 1 | FBL-1 reproduced; includes one existing invalid-case control and six temporary diagnostic cases |
| `scoped-final` | 277 passed, 17.50 s, exit 0 | Complete requested feedback/library/health/ledger/SDK/resolution scope after supporting owner changes |

The temporary diagnostic driver is `/private/tmp/drf-feedback-library-review-20261028-0352/run_review_probes.py`; reproduce it with the same isolated interpreter and a new canonical evidence-directory argument. It invokes the unchanged runner through its `main`, supplies a pytest plugin, writes exact fixture and driver copies inside that runner's evidence root, and records both copies in the runner's source hashes. It does not alter any guard check, read root, allowed network operation, or repository test. The plugin's preimported-module assertion-rewriting warning is visible in the diagnostic receipts. These synthetic probes establish the exercised behavior, not live source truth.

**Guard accounting:** Inspecting every parent and child process receipt, the final suite has six completed processes: one parent and five registered guarded children, all exit 0 with shutdown complete, preserved identity, and no recorded source drift. Across those processes there are six redirects each for `app.config`, `app.utils.logger`, and `app.services.simulation_manager`, plus five `allowed:guarded_child` events. There are no recorded blocked operations, network events, or contained font/platform-discovery probes in the final suite or final diagnostic run. The first diagnostic collection attempt has exactly one **blocked external-read directory-listing attempt**, preserved in its event stream; it is not zero attempts and was not a network or provider probe. No guard was relaxed to make collection pass. This is the trusted-test CPython audit boundary, not an OS sandbox or proof of arbitrary native-code isolation.

**Receipt hashes:**

| Artifact | SHA-256 |
|---|---|
| `scoped-final/completed.json` | `4eba42ea41162efda38014adaab9b17dca4cc45a2e46dd9acb2d04aa3eb439bc` |
| `scoped-final/junit.xml` | `370624ff975e47d96091571262f62eb7738fce4ac6cc72e067ac110db206db8e` |
| `probes03/completed.json` | `f8d318a8a0c0ea081907933762045a3d4a276d6d3453e8b06ca9283a9e489ca4` |
| `probes03/junit.xml` | `2eae0fee9a9cb76772476b599dc02a2d4d236cadf16054c86f21b4d9a152169c` |

## Source-freeze verdict

The following six files are byte-identical between the initial 561-file capture and final inspection at 2026-10-28 04:01:11 UTC. They are the exact reviewed source state, including the open FBL-1 defect.

| Reviewed path | SHA-256 |
|---|---|
| `backend/app/services/forecast_feedback.py` | `7e05f2a86de3f0d09b11455c3aca663b692937acc19ae32883cf207cdd1f345c` |
| `backend/app/services/forecast_inputs_health.py` | `85504123eebc7ad9249d2081d240638463ab31277b78d83f44426ebb1ec872e7` |
| `backend/app/services/forecast_library.py` | `f2c7ba6073a9fc16e251035034677ef8153f489ff9bdbc6d08a99c227b8cb6ca` |
| `backend/app/services/forecast_ledger.py` | `5069f5ef07691b68b15648722da07f1b3bfdfef31320ae43398aa03fe3f936c1` |
| `backend/app/services/resolution_autorun.py` | `ecf34ef6b5e3cc310b558ea1d46708f5df252a825844d699f5ac498b13dcffdb` |
| `backend/app/api/sdk.py` | `5e6b61b5c4721ba96d7af6f3da3907b28fb1e089fabcc860023ac2b6a91259d3` |

Full before/after manifests, all test and supporting-source hashes, and process/event comparisons are in `/private/tmp/drf-feedback-library-review-20261028-0352/{source-before.json,source-before-final-suite.json,source-after.json,verification-summary.json}`. The broad worktree was **not frozen**: ten other files changed between the first and last capture, including report/API/pipeline/tournament/monitor sources and unselected target tests. A fresh capture preceded the final suite; only the unselected `backend/tests/test_target_report_api.py` changed after that capture. The six scoped files and all production files in that capture remained unchanged through the final inspection. Other owners' changes were neither reverted nor attributed to this reviewer. A coordinator-wide integration verdict still requires its own frozen state.

Ruff `--select F,E9` passed for the six reviewed files; no formatter or autofix was run. No notebook gates apply to this review.

## Remaining work and resumption prompt

The bounded review is complete. **Full library review closure is withheld for FBL-1**, despite the passing existing suites. The coordinator should assign a narrow proof-to-claim repair, preserve the recorded red, add the actor rejection regression to the owned suite with its valid control, and request a hash-bound rereview. The dated Oddsense fixture remains a separate test-maintenance follow-up. There is no reproduced admitted-case `entry_cutoff` forecast failure to fix in this source state.

Reviewer edits are limited to this document. All diagnostic scripts, captures, manifests, and pytest outputs are under `/private/tmp`; there are no reviewer production/test code edits, provider calls, live probes, production scheduler/service activations, commits, or pushes. Primary-checkout source and saved data were not modified.

**Next-session prompt:** Read `feedback-library-final-review.md` and the feedback/library owner reports. Verify the six listed source hashes. Reproduce FBL-1 with the preserved guarded diagnostic, then implement only the coordinator-assigned claim-binding repair. Rerun the 277 scoped cases and the new rejection/validity controls under a fresh evidence root, inspect every guard receipt, and obtain independent review for the new bytes. Keep mechanism/kernel outputs and cross-case assumptions separate from earned confidence or prospective lift.

## Closing update

- 2026-10-28 04:01:11 UTC: Finalized the six-file source-bound verdict, FBL-1 reproduction and proposed bounded repair, canonical cutoff controls, dated-fixture compatibility failure, complete guarded-run accounting, exact commands, and source/receipt hashes. Review activity is complete; FBL-1 remains open for coordinator assignment.

## Assigned FBL-1 repair — 2026-10-28

The user explicitly assigned `forecast_library.py`, `test_forecast_library.py`, and this document for the demonstrated repair. The earlier review and six-file hashes above describe the pre-repair source state. Other ownership and all offline/no-activation/no-commit restrictions remain in force.

**Brief and plan:** Reject journal-derived actor learning and mechanism/template parameter validation because the current journal does not independently admit the required identity-to-claim bindings. Apply this rejection during entry validation so both writes and selection of old unbound rows fail closed. Cover nested mechanism parameter bases as well as entry-level provenance; retain inherited observed/estimated/assumed bases. Keep exact journal-bound reference-class observations and manually source-backed observed actor records working. Add the reproduced negative and positive controls first, obtain guarded red evidence, apply the minimal validation repair, then run the affected suites and an independent peer review of the final source bytes.

| Acceptance criterion | Scenario evidence planned |
|---|---|
| Unsupported actor claims cannot borrow journal proof | Genuine named-source and official outcomes with unrelated actor claims reject on write and selection; even verbatim event text supplies no typed actor binding |
| Unsupported mechanism parameters cannot borrow journal proof | Genuine outcomes reject entry-level mechanism learning and nested `journal_outcome` parameter bases |
| Supported source-aware paths survive | Exact journal-bound reference-class observation and manually observed actor record round-trip; mechanism exporter preserves original bases and gaps |
| Repair remains narrow and auditable | Only the two assigned code/test files and this report change; preserve red receipts, final hashes, guard accounting, and peer verdict |

- 2026-10-28 04:06:52 UTC: Captured the three assigned files before edits in `/private/tmp/drf-fbl1-repair-20261028/source-before.json`, with byte copies beside the manifest. The library and suite still match the original review hashes.
- 2026-10-28: Added regressions before changing production code. `/private/tmp/drf-fbl1-repair-20261028-red` records **13 failed, 49 passed in 2.40 seconds**. Every failure is a missing expected rejection: eight actor/mechanism write/read joins across genuine named-source and official outcomes, one verbatim-text actor claim, and four direct/nested mechanism-parameter claims. The manual-source actor and exact reference-class journal controls already pass. No setup/import failure is used as behavioural red evidence.
- 2026-10-28: Applied the bounded repair in shared validation. Journal-derived actor and mechanism entries now reject with `unsupported_journal_actor_proof` and `unsupported_journal_mechanism_proof`; individual mechanism parameters cannot assert journal-derived validation either. The current journal has no typed binding that could authorize those claims, so publisher or evidence text is never used to infer one. Unsupported old library rows fail on selection without changing the publication journal. Verification and independent peer review are next.
- 2026-10-28: The affected library suite now passes **62/62 in 1.92 seconds** at `/private/tmp/drf-fbl1-repair-20261028-green`; Ruff `--select F,E9` also passes for the two edited Python files. The 13 regression failures became passes with the same test bytes. A composed feedback/library compatibility gate is running under a fresh source manifest. Read-only peer reviewer Lagrange (`01a180b2-6471-7693-8522-b89a478a44d3`) is inspecting the exact repair against the saved pre-edit bytes; it has no write ownership.

### Final repair verdict and source freeze

**FBL-1 is closed for the source hashes below.** The repair rejects unsupported journal-derived actor records, mechanism templates/parameters, and direct or nested parameter-level `journal_outcome` assertions. Shared validation enforces the same boundary on new writes and old stored rows. Errors are explicit: `unsupported_journal_actor_proof` and `unsupported_journal_mechanism_proof`. No actor calibration is inferred from a publisher name, copied evidence text, or arbitrary self-rating.

The current supported journal-learning path remains an exact single official observation joined to a reference class, including series, units, comparator, counts, window, evidence, and availability. Source-backed manually observed actor records still round-trip as `basis="observed"` without journal proof. Mechanism exports retain their inherited observed/estimated/assumed bases, original parameters, uncertainty, and gaps. They gain no learned validation, earned confidence, runtime policy change, or nonzero estimator weight from this repair.

**Production and test source freeze announced 2026-10-28 04:11 UTC. No further feature additions or code changes follow this freeze.**

| Frozen file | SHA-256 |
|---|---|
| `backend/app/services/forecast_library.py` | `4e75eed517e4ffc80951159162f6edf249a018e8bfaf60d4176326dbff0a4ffc` |
| `backend/tests/test_forecast_library.py` | `c684b6c104961d8a716843f1e18fb202c1802994e09ce3132ab7bd4a19c65493` |
| Unchanged `backend/scripts/main_offline_pytest.py` | `5046cf820fa468d8e8ffb2e3fdade1d20fca2f0bd56ee15eabdff51c223c02be` |

These code/test hashes match those sent to the peer reviewer and used by the composed affected gate. The 561-file manifest captured before that gate had no Python/fixture drift through final comparison at 04:10:31 UTC. The coordinator's broader 149-module gate and final combined freeze remain separate evidence; this local repair does not claim that gate's result.

### Repair verification and independent peer review

| Gate | Result | Evidence root |
|---|---|---|
| Regressions against original implementation | 13 missing-rejection failures, 49 passes, 2.40 s; exit 1 | `/private/tmp/drf-fbl1-repair-20261028-red` |
| Same test bytes after repair | 62 passed, 1.92 s; exit 0 | `/private/tmp/drf-fbl1-repair-20261028-green` |
| Affected feedback/library/SDK/resolution compatibility | 291 passed, 17.34 s; exit 0 | `/private/tmp/drf-fbl1-repair-20261028-composed` |
| Independent peer focused verification | 62 passed, 1.91 s; exit 0; no review findings | `/private/tmp/drf-fbl1-peer-review-20261028-cedar` |

The new library-suite controls cover genuine named-source and official journal outcomes with actor/mechanism substitutions, both writing and selecting old wire rows, verbatim event text without a typed actor binding, nested mechanism-parameter basis assertions, a manually source-backed actor record, and a valid exact journal reference observation. Existing producer/selection tests additionally verify that inherited mechanism assumptions, parameters, gaps, and explicit lack of outcome validation survive export. The former permissive named-source actor test is now a helper feeding rejection controls; the change deliberately removes its unsupported learning expectation.

The red and green runs both record the exact test hash `c684b6c104961d8a716843f1e18fb202c1802994e09ce3132ab7bd4a19c65493`. There were no collection errors or hidden skips in those runs. Ruff `--select F,E9` passed for both edited Python files; no autofix, formatter, or unrelated code cleanup was applied.

The composed command was:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B \
  backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-fbl1-repair-20261028-composed \
  --allow-python-script backend/tests/test_forecast_feedback_sdk.py -q \
  backend/tests/test_forecast_library.py \
  backend/tests/test_target_feedback_extensions.py \
  backend/tests/test_target_inputs_health_probe.py \
  backend/tests/test_forecast_ledger.py \
  backend/tests/test_forecast_feedback_ledger.py \
  backend/tests/test_forecast_feedback_workflow.py \
  backend/tests/test_forecast_feedback_sdk.py \
  backend/tests/test_resolution_autorun.py \
  backend/tests/test_resolution_monitor.py
```

The focused gates use the same interpreter/runner with their fresh evidence roots and only `backend/tests/test_forecast_library.py`. Across all repair and peer receipts, shutdown completed, identity was preserved, and no recorded blocked operations, network events, contained platform/font probes, or runner-recorded source drift occurred. The composed gate has one parent plus five registered guarded child processes, all exit 0; its aggregated events are six redirects each for `app.config`, `app.utils.logger`, and `app.services.simulation_manager`, plus five `allowed:guarded_child`. The red, focused-green, and independent peer gates each have one process and the three storage redirects. These are CPython audit receipts for trusted offline fixtures, not an OS sandbox or live-provider verification.

Read-only peer reviewer Lagrange (`01a180b2-6471-7693-8522-b89a478a44d3`) compared both files with the pre-edit byte copies and reported **no bypass, read/write inconsistency, supported-path regression, or unnecessary scope expansion**. Its independently verified hashes are exactly those in the freeze table. The reviewer changed no repository files and has been closed after returning its result.

| Repair receipt | SHA-256 |
|---|---|
| `red/completed.json` | `0a8867c181370d91422555a386294b1130a749aee55b671377954d6b6ab0bc8a` |
| `green/completed.json` | `70af6404dc8b467da81aac9d6c2211badc565b8a1c5ec0c9e55d12ce5781fd7a` |
| `composed/completed.json` | `ec9e7a6e2b4af49d4f25698696a5d7d01bc7b943423aee4923e2f8145c4f752f` |
| `composed/junit.xml` | `fa5fac9931f850f21c78b176f0d811f4441f127c79222ac7d9663fe9a6191abf` |
| Peer `completed.json` | `18cc9cdd17401190af4ba07f4aa55c93d412487544ecbaa7cc71b17e6be57eff` |

Full per-process comparisons and receipt hashes are in `/private/tmp/drf-fbl1-repair-20261028/verification-summary.json`. The exact owned source/test delta against the preserved original byte copies is `/private/tmp/drf-fbl1-repair-20261028/repair.patch`. Only the assigned library, its suite, and this review document were edited by this repair; other owners' work remains intact. No forecast providers, live probes, production scheduler/service activation, commits, or pushes were used.

### Issue 10 — schema limitation and tracker-sync note

**The current journal schema independently admits neither actor identity plus behavioural claim nor a mechanism template/parameter plus validation claim.** Its named-source and official-data outcome evidence cannot authorize either kind of learned record. Accordingly, this repair explicitly rejects `journal_outcome` actor/mechanism entries and mechanism-parameter assertions, including old unbound library rows on read. Publisher names, matching URLs, verbatim text, and self-ratings do not substitute for those bindings. Future support requires a separately designed and independently admitted typed binding; none is invented or added here. Manually source-backed observed actor context, inherited mechanism assumptions, and exact official reference observations remain supported. This is a schema limitation, not completed actor/mechanism calibration or proof of prospective skill.

**Coordinator-synced correction, 2026-10-28 04:15:34 UTC:** The configured legacy tracker is [linroger/DeepResearchForecast issue 10](https://github.com/linroger/DeepResearchForecast/issues/10). The coordinator confirms it was already created successfully through the coordinator's connected GitHub session and includes the schema-binding limitation above. **No unresolved tracker action remains.** This synchronization status is recorded from the coordinator's explicit confirmation; no new tracker query or mutation was performed.

The earlier access attempts mistakenly inferred the tracker from the archived checkout origin, `linroger/DeepAgentForecast`. That was the wrong tracker. Its connected-tool **404** and the CLI's **401 Bad credentials** are retained as historical attempt evidence, not as an outstanding blocker for the actual legacy tracker. No authentication retry, credential change, or tracker write accompanies this correction.

### Repair completion and next handoff

Implementation, the demonstrated negative/valid controls, affected compatibility checks, independent peer review, and the two-file source freeze are complete. FBL-1 has no remaining local code work, and the coordinator has accepted the production file freeze. Issue 10 includes the schema limitation through the coordinator's completed synchronization; no tracker action remains. The coordinator's final broad gate is running, and its result remains separate from this repair's evidence. Any later source change needs fresh affected evidence. The earlier unrelated Oddsense wall-clock fixture issue remains outside this repair.

- 2026-10-28 04:12:44 UTC: Closed FBL-1 for the frozen production/test hashes after 62 focused, 291 composed, and 62 independent peer passes. Recorded the journal schema limitation for Issue 10, tracker access failures, exact receipt hashes, no-drift evidence, and the no-further-code-change boundary.
- 2026-10-28 04:15:34 UTC: Corrected the tracker identity to `linroger/DeepResearchForecast/issues/10` from the coordinator's explicit confirmation, recorded completed synchronization of the schema limitation, and removed the unresolved tracker action. Only this document changed; no authentication retry or tracker access occurred, and the accepted production/test source freeze remains intact.
