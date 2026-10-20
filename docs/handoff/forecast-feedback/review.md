# Forecast feedback independent review

**Reviewed at (UTC):** 2026-10-20T17:26:44Z  
**Reviewer:** Bacon  
**Coordinator-supplied base:** `303e5a88aa4fa097441b8b2161bc0209b3c42130`  
**Static verdict:** No remaining blocking findings in the scoped frozen source below.  
**Final review verdict:** Closed; no remaining blocking findings. The frozen source is ready for the coordinator's scoped commit and integration, supported by the independently inspected 500-case regression, seven-case end-to-end gate, and two fresh world continuation cases. This is an offline implementation/review verdict, not a deployment or empirical forecast-quality verdict.

## Scope and method

The review covers published forecast admission, native market/official-data resolution, exact SDK scenario adjudication, durable scoring and restart, next-report history, public publication checks, and visual replay compatibility. The already accepted world integration is outside the feedback diff; its evidence was checked without changing or reimplementing it.

The reviewer inspected the production boundaries and changed tests, generated file-content diffs for existing feedback files, and reviewed new modules as additions. No Git commands were executed, in accordance with the review restriction. The comparison used `/private/tmp/drf-forecast-commitment-in9y9u3h/source-accepted`: its accepted evidence pins non-world source to `ac488913`, and the coordinator identified `303e5a8` as the world-only integration commit. All eight accepted world source/test hashes were independently checked against the worktree and matched. This establishes the applicable feedback-file comparison; Git ancestry and ref publication remain the coordinator's responsibility.

The reviewer ran no application imports, pytest processes, provider calls, network operations, or production accesses. Receipt inspection and hashing used isolated, stdlib-only Python. The only reviewer-created repository artifact is this file.

## Closed findings

Closure below means the final source addresses the concrete finding. Runtime evidence is identified separately rather than inferred from static inspection.

| Finding | Final disposition and review basis |
|---|---|
| Draft admission and publication/ledger crash window | Draft finalization no longer appends the production forecast. Final save persists the required tracking marker, and public reads withhold missing, corrupt, or mismatched original snapshots. Explicit recovery allows only an otherwise audit-passed unchanged publication before acquisition. SDK settlement never backfills an absent original. |
| Dual anchors suppressed official-data resolution | Market candidates for data-anchored binaries are removed before constructing the already-resolved exclusion list. The ledger uses the official-data lane; no binary outcome selects a scenario winner. |
| Naive local publication timestamps | New report completion uses aware UTC. Registration converts legacy local timestamps to UTC instead of relabeling local wall time as UTC. The SDK retains aware UTC adjudication timestamps. |
| Evaluation contamination through legacy official summaries | The legacy official-data summary filters root and dataset evaluation classifications, boolean/nonfinite/out-of-range scores, and computes its count from eligible scores. The typed journal independently rejects evaluation publication/evidence. |
| Saturated outstanding queue starved publication recovery | An independent bounded registration-recovery pass precedes outcome queue selection and persists a rotating cursor. Invalid metadata/cursor JSON shapes are checked before field access. |
| Provider response identity and terminal-state ambiguity | Market construction requires the embedded market ID to match the requested anchor and requires a consistent terminal Yes/No price. The typed join additionally validates exact equivalence, original probability, and original contract identity. |
| Frozen history trusted existing model metadata or changed after restart | First capture is derived from durable facts and saved in `forecast_track_record.json`. Subsequent preparation verifies the journal prefix. The read-only audit and public reads compare the companion exactly with the sealed embedded summary and independently verify typed history. Later valid journal events do not refresh that history. |
| Canonical block mutation and whitespace instability | Only an exact rendered, bound block receives the metadata treatment. Missing, altered, duplicate, or unbound blocks fail. Stabilization verifies, detaches, and restores the exact block; stripping restores canonical prose whitespace. Full report and forecast fingerprints remain authoritative. |
| Audit-time registration survived failed replay rollback | `_enforce_final_publish_audit` performs no journal registration. Registration is confined to final save or explicit audited recovery. |
| Registration reopened different forecast bytes after validation | Registration hashes the actual reopened bytes against `publication_status.forecast_sha256` and parses those same checked bytes before admission. |
| Conflicting/rejected candidates appeared as authoritative monitor outcomes | Registered-report presentation reads detached committed typed outcomes. It uses the retained score/probability and keeps native candidates separately. Conflicting retries preserve the first outcome and evidence. |
| Monitor aggregates bypassed typed admission | Registered-report scenario/market/data aggregates come from typed tracks. The new-record count uses admitted outcomes. `native_records_appended` is a separate diagnostic; rejected near-match outcomes cannot change authoritative rendered aggregates. |
| Backfill discarded audit-time Markdown changes | Backfill retains the enforced report object and propagates its final Markdown into metadata and subsequent translation source fingerprints. |
| Backfill rollback omitted the new companion | Backup and restore include `forecast_track_record.json`. The added failure case verifies restoration of its original absence and of the original four sealed artifact byte sequences, with no leaked journal admission. |
| SDK conflict became HTTP 500 after helper reload | The route catches the live helper module's `ForecastFeedbackError`, avoiding a stale re-exported class. Publication checks, exact unique scenario matching, conflict rejection, and journal-first mirror repair remain intact. |
| Issued four-decimal probabilities failed strict unit-sum admission | The ledger allows bounded `0.0005` total rounding error, while retaining each issued probability in the snapshot, digest, and score. The tests preserve exact `0.3333` thirds and reject distributions beyond that bound. |

The ledger implementation also retains mandatory file/process locking, flush/fsync on append and idempotent retries, checksummed journal validation, exact outcome binding, independent score-family denominators, and no mutable authoritative score cache. The prefix verifier validates the full journal, including facts after the retained prefix. Mutable legacy scenario summaries remain outside the typed history proof and are not rendered as that proof.

## Exact reviewed source

These are the current bytes reviewed after the coordinator requested the release freeze. A change to any relevant entry requires affected checks and rereview.

| File | SHA-256 |
|---|---|
| `backend/app/api/sdk.py` | `41537171afdf65b179718e38c39f3834709a58a567cafc5b8cbbed845c7f3ba9` |
| `backend/app/services/forecast_feedback.py` | `5e4f4eb48adff25bbb25bf0c7df661531b8f1584fdabda6da73c0a82bd5a3209` |
| `backend/app/services/forecast_ledger.py` | `2576a04a669586c7ebe94550d5d5ef1a8754c51bf65b42809e068e7164c0edc5` |
| `backend/app/services/forecast_track_record.py` | `6cd977828939223b239cd83ebb72c39f05c6a76714ad9ada3f9be5b73d9610b1` |
| `backend/app/services/report_agent.py` | `880615f54c85e2f43a1d2a50f1c7bdd8949baf4f41ae46b75ed0c48886e4e46a` |
| `backend/scripts/backfill_report_visuals.py` | `c8f36446dc8c72affb46b2458096878dd773154b7efaa66296be090404ff62bf` |
| `backend/scripts/resolution_monitor.py` | `b76349d721fb306f086b1284591255dae0d67dd562f9bdd8be4d68f3f16eb15c` |
| `backend/tests/test_forecast_feedback_ledger.py` | `34e7f4f852fc9c93efa7dacb3abf556bf34cda5e93601e065ecd8f2aa9eb52ed` |
| `backend/tests/test_forecast_feedback_sdk.py` | `65feee980bfa286d52836c37a57b2f75b7f2e6db25a03a554139038c47527fec` |
| `backend/tests/test_forecast_feedback_workflow.py` | `b49be9a22dc19e49f72acd8a457635ac1f706c927078727852ce4bd0aa959362` |
| `backend/tests/test_forecast_track_record.py` | `b10619ed839a53d3b3ddeff5929f25428c89c7a3487daa3cbb7c1ccbb5963caf` |
| `backend/tests/test_report_official_publication_real.py` | `208c6cd7919151d586e136e9db7168e0ccf350d17dd2123809e1658671fba8a6` |

Supporting files checked:

| File | SHA-256 |
|---|---|
| `backend/scripts/main_offline_pytest.py` | `8c8bb8f6c0e4e5decee8f167603a4eb47711ec562e028d19f9d3d6bee1741815` |
| `README.md` | `d3d0e5d4030e4e6b222e977b5bacf955aaa870b931cfd62f874f9d60aa02be08` |
| `README.zh-CN.md` | `49307fe17271b30b48ae00f322c91f33d2f3fdda7c1ec6ffea9f385c93560559` |

The English and Chinese feedback documentation describes the same immutable publication journal, exact typed scoring, separate official-data lane, bounded recovery, and descriptive next-report history. Neither claims empirical calibration from these fixtures.

## Independently inspected evidence

The reviewer parsed each completion receipt and JUnit file below, inspected child receipts where present, and compared the relevant tested source files with the worktree. There were no source mismatches in the stated comparisons. Counts overlap across suites and must not be summed into a unique release-test total.

| Gate | Observed result | Source comparison and limits |
|---|---|---|
| `/private/tmp/drf-ledger-rounding-6q77ed85/evidence` | 199 tests, no failures/errors/skips. Parent and three children exited 0 with complete shutdown, identity preserved, no tracked drift, and no blocked-operation events. | Current helper, ledger export module, and ledger test file match the tested mirror. |
| `/private/tmp/drf-feedback-acceptance-candidate-mgs4p0sr-evidence` | 7 tests, no failures/errors/skips. Parent and restart child exited 0 with complete shutdown, preserved identity, no tracked drift, and no blocked-operation events. | Current SDK, report producer, helper, ledger export, presentation, monitor, and end-to-end test match the mirror. Exercises real report generation, publication/API consumers, native resolutions, conflict handling, restart, next report, dual anchors, recovery, companion tampering, and rejected-candidate aggregate separation with synthetic external responses. |
| `/private/tmp/drf-feedback-replay-20261021-1` | 3 tests, no failures/errors/skips. Exit 0, complete shutdown, preserved identity, no tracked drift. Two subprocess attempts and 18 external-read attempts were blocked. | Current report agent, backfill script, presentation helper, and official-publication test match the mirror. Includes successful first companion capture and downstream PDF-failure rollback. PDF export is a controlled fixture; this is not PDF-engine or live-provider evidence. |
| `/private/tmp/drf-feedback-compat-20261021-1` | 11 tests, no failures/errors/skips. Exit 0, complete shutdown, preserved identity, no tracked drift. Two subprocess attempts and 18 external-read attempts were blocked. | Historical selected compatibility evidence; the later frozen combined gate remains required. |

Receipt fingerprints:

| Gate | `completed.json` SHA-256 | `junit.xml` SHA-256 |
|---|---|---|
| Ledger rounding | `268d3ce607260adbb13ec6c9b0733cbcd67bb2f0468cb0dd94a5f8f0c4a6279a` | `ddd5662a4762cdf5985397c87367e6f03b10ecb1c77c0b475fd9676848116982` |
| Seven-scenario acceptance | `076264f32c3d98308891eb87d4516a4291b1fa96847f0539b909532a73653ecc` | `fea3cf16d542a42a0998c015607bc935daf90e90b7828d42fd2186ce154b1c7d` |
| Replay | `d08691a44a18df7cc05b2c678a68918a19027918a41343fbef334158eeeebb3f` | `c140888031761f001b301538ce453ac440893aa2be44848a3add246b8f561c1b` |

The SDK module-order evidence was subsequently supplied and independently inspected. `/private/tmp/drf-feedback-sdk-p035l8i1/reload-final-{forward,reverse}-evidence` each contains 122 passing cases, no failures/errors/skips, and a normal parent plus four normal guarded child receipts. Both tested SDK source/test pairs match the reviewed hashes. These suites overlap with other gates and are not added to the unique final total. The independent SDK review at `/private/tmp/drf-feedback-sdk-p035l8i1/reload-final-review.json` closes the stale exception-class finding on the same two owned hashes.

The separate world record `/private/tmp/drf-forecast-commitment-in9y9u3h/verification-accepted.json` was independently checked: all eight owned source/test hashes match, all five receipt/JUnit hashes match, and the XML contains 305 unique passing cases with zero failures/errors/skips. The accepted world gates record blocked socket/process/external-read attempts as documented in `commitment-integration.md`; they are not zero-activity or live-provider evidence. The world slice is not reopened by this feedback review.

## Final combined receipt closure

The following final runs were independently inspected after the coordinator declared the source freeze. JUnit testcase identities across these four commands are disjoint: **509 unique passing cases**, with zero failures, errors, or skips. The preceding 199-case ledger, 122-case module-order, three-case replay, and earlier world suites are overlapping supporting evidence, not additional unique release counts.

| Final gate | Result | Receipt and guard interpretation |
|---|---|---|
| `/private/tmp/drf-feedback-final-20261021-1` | 500 passed | Parent and guarded children 5958, 5959, 5960, and 6120 all exited 0 with complete shutdown, preserved identities, and no tracked drift. Parent events record two blocked subprocess attempts and 18 blocked external reads, attributed to `fc-list`, `system_profiler`, and font-directory discovery. Four guarded child launches were allowed. |
| `/private/tmp/drf-feedback-acceptance-final-_y02obqb-evidence` | 7 passed | Parent 13728 and restart child 13731 exited 0 with complete shutdown, preserved identities, and no tracked drift. Storage redirects and one allowed guarded child were recorded; no blocked-operation events were recorded. |
| `/private/tmp/drf-feedback-world-continuous-20261021-1` | 1 passed | Uses the same joint mirror as the 500-case gate. Exit 0, complete shutdown, preserved identity, no tracked drift. Records one blocked socket creation, four blocked subprocess attempts, 20 blocked external reads, and OASIS import quarantine. |
| `/private/tmp/drf-feedback-world-resume-20261021-1` | 1 passed | Uses the same joint mirror as the 500-case gate. Exit 0, complete shutdown, preserved identity, no tracked drift. Records the same categories/counts of blocked probes as continuous execution. |

The blocked probes remained denied. These receipts describe a CPython audit-hook boundary, not an OS sandbox, and do not imply zero attempted operations.

Final receipt fingerprints:

| Gate | `completed.json` SHA-256 | `junit.xml` SHA-256 |
|---|---|---|
| Combined regression | `725fe118ce6127a6a92b8be2f43b02953f1cd45f9376454cf447266510a81320` | `2ed8d3fa9242ad819c86bc34ac0b3cb1b17cff96f5bf96f5cc7a6db09871b70e` |
| Final end-to-end | `b0e206210bb6d61dddc2d33876fd8ea93dd76e61e86c31d27d34c21d447a5777` | `98a0732d803897b4345d1fcab434b11ada9ce8227cc87819a519dd907310ceb1` |
| Joint world continuous | `90d45d5bad67dbbc15a4423dd448c175123f010f55417dea4581018defd9e1fe` | `0111cb2a15e13a34750d66d6ac51c6f955ac536668b637bbdc24f2abc1999e49` |
| Joint world restart | `1790fe28a9ef0760ed9129b58ae964881672dda1c8ed392d748f02dc32248128` | `5a675d0b82119019f5e6de6f26756387adf093ec3b8b95375dd2702e942b80eb` |
| SDK forward order | `66340df963e138d4e5d078d86fd7eb030ee737ff206c4b7c20aefc65d6ed419d` | `bf2e32caa6274287a2a19a275e5b6f217c074de27f60505ed788abee31dc9d22` |
| SDK reverse order | `524fb10a812fe411c989c14c3e30d410b450f8f73448b8879a3e17231c5b9acd` | `777b9d013713178161a0502948ec89df1cf9d62f9536deb7da118445ba9570e5` |

The final end-to-end child receipt SHA-256 is `936d53308c9f483065d92bd265b9e3112cbb5b036d1ae9a842f0799c9a32c5d9`. Its workflow receipt at `pytest-tmp/test_published_forecast_native0/acceptance-receipt.json` has SHA-256 `3ad67d6b2e929b6887c6e776e96b9bd0ddefa5a579a2c7141ea1bebd8668fce4`.

### Source and artifact reconciliation

The reviewer rehashed all **16 entries** in [final-source-freeze.json](final-source-freeze.json) against both the worktree and `/private/tmp/drf-feedback-final-EE0asH`: no mismatches. The freeze manifest SHA-256 is `5e31ab9cfac97162e905d4a4e2625c1faaeab68f47f59fe5243668a9514fabce`. All entries already recorded in the review source table also still match.

The additional already accepted world files in that joint freeze are:

| File | SHA-256 |
|---|---|
| `backend/app/services/agent_decision.py` | `695f29f4558f78f5fecc98cd8dfe79dab247f414fe669fe83ad6f5dee12c655f` |
| `backend/app/services/world_model.py` | `2673149b82e606abd008f62c31a4ea5019358ee31f8b376314052711730fea43` |
| `backend/app/services/world_update.py` | `91116f0a92fce1a6b65a312f29b6b9cfe24094ffdb97da0b6cadbf1d1cf38f56` |
| `backend/tests/test_world_commitment_fulfilment.py` | `c404da182ed40a36fcb42a025e3958885259528ce60d0d423389a050dc534873` |

The final end-to-end manifest `/private/tmp/drf-feedback-acceptance-final-_y02obqb/source-freeze.json` has SHA-256 `ae01e13c5fa7158ecc006cecb637cf33ba4ee13a8cbc6f2beb40b6443198b368`. All **14 declared boundary files** match both its mirror and the current worktree. Its recorded full mirror/worktree drift lists are empty. This includes the workflow test, publication APIs, official-data resolver and bridge, and unchanged guarded runner in addition to the changed production modules.

The reviewer directly rehashed the original and next generated reports and confirmed that both final audits hard-pass and bind the actual Markdown and forecast bytes:

| Artifact | SHA-256 |
|---|---|
| Original `full_report.md` | `9d60ce7b9e699f70a13e8fd0e056ff18b7cd50fb1d00e83207403132e69fee43` |
| Original `forecast.json` | `7056cea8c8e7447897f34f893947456f6202afe9cf03051f54e8495fda192567` |
| Original `final_audit.json` | `2d0b6da9ff4ee5539201fc17d593207ee6b758e87f225ee48c137ac2a7342c97` |
| Next `full_report.md` | `e0d226ca9a16c31976fcf17f3282640df29d3e64bc9915c3bd0c7ebd9369e579` |
| Next `forecast.json` | `ec9214faa5223d7f74364f21c584bae09ccc78b7bde38086077edc323e3886e6` |
| Next `final_audit.json` | `aab56ad295273e23aed8da9c507e984f06b61f4a1a3946027241efd58cb14b92` |

Durable copies of the broad regression, replay, and joint-world parent/JUnit receipts under [evidence/feedback](evidence/feedback/) were byte-compared with their private evidence originals and matched. The coordinator's primary-checkout preservation claim remains coordinator-owned; this reviewer did not access deployment state.

## Final disposition

All blocking findings from this scoped review are closed on the listed bytes. Final combined, restart, next-report, replay, and module-order receipts have been inspected, with source and generated-artifact hashes reconciled as described above. The feedback slice is ready for the coordinator's scoped commit and integration. No further reviewer application changes or test runs are required for this frozen state. Subsequent substantive source changes invalidate the corresponding closure until affected checks and review are refreshed.

This review and the inspected tests establish the exercised offline contracts. They do not establish live provider availability, forecast accuracy, production operation, remote publication, or deployment.

## Updates

- 2026-10-20T17:21:52Z: Created the scoped final static review, recorded exact hashes and finding closures, and independently inspected ledger, acceptance, replay, compatibility, and separate world evidence. Final combined release receipts remain pending.
- 2026-10-20T17:26:44Z: Inspected the 500-case final regression, both 122-case SDK module orders, seven-case final end-to-end gate, and two joint-mirror world continuation cases. Reconciled all 16 joint-freeze and 14 end-to-end boundary hashes, generated report seals, child shutdown receipts, and durable evidence copies. Closed the review with 509 unique final-gate cases and no remaining blocking findings.
