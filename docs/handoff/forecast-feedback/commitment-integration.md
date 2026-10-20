# Commitment integration into forecast feedback

**Status:** Complete for the owned world integration; ready for coordinator commit and combined review.
**Base:** `codex/forecast-feedback`, main `ac488913e78a8f87179830088f85452b3a8454f5`.
**Repair source:** `faae88f248dc7e54baf14bd18b930f107c264aaa`.

## Request and boundary

Integrate only the stricter default-world commitment repair into current main, preserving newer track records, expectation comparisons, red lines, announced settings and world pressure. Owned production files are `world_model.py`, `agent_decision.py` and `world_update.py`; affected world tests and this record are the only additional writable repository paths. The coordinator owns the parent handoff. No shared Git state, commits, cherry-picks, primary deployment files, secrets, network/provider calls, services or installations are authorized.

The approved parent [plan](PLANS.md) and [handoff](handoff.md) remain authoritative for the larger feedback effort. This document is the bounded integration working record.

## Acceptance and plan

| Requirement | Check | Evidence |
|---|---|---|
| Unrelated actions and new consent do not discharge old obligations | Port repair regression module and exercise current-main behavior before repair | Fresh guarded red receipt |
| Delivery requires exact owned promise, counterparty, round and explicit successful arbiter attestation | Port narrowly scoped repair hunks and adversarial cases | Fresh guarded core receipt |
| Main realism behavior survives | Retain track record, expectations, red lines, announcement and pressure tests; update only obsolete commitment fixtures | Core and coordinator regression receipts |
| Consequences reach actual next actor prompt and durable restart | Real calendar coordinator with synthetic external responses, uninterrupted and checkpoint continuation | Separate guarded continuous/restart receipts and saved artifacts |
| Exact reviewed bytes are green | Independent review, followup regression runs, hashes before/after | Source manifest, completion receipts and review findings |

Read existing code and old repair evidence first; bring in the repair test module; capture the behavioral regression in an isolated mirror; apply only matching repair hunks and reconcile overlap with newer main logic; run focused checks; issue the requested contract summary before broad testing; run relevant core and separate real coordinator/restart gates; resolve independent review findings and record the exact accepted bytes.

All application imports and tests use the existing guarded `backend/scripts/main_offline_pytest.py`, the provisioned `/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B`, a fresh `/private/tmp` source mirror and fresh evidence directories. Guard code stays unchanged. Static source inspection and stdlib-only artifact management do not import the app.

## Progress and findings

- Initial checkout verification found HEAD exactly at `ac488913` and only the coordinator's untracked forecast-feedback handoff directory. Ownership is preserved.
- Prior repair evidence establishes useful scenarios and invocation boundaries, but its 235 green tests do not establish acceptance on current main.
- Main still fulfils due promises on unrelated non-hold moves except explicit withdrawals. The repair replaces that rule with an explicit attempt and confirmation contract.
- Main's additional expectation recording, action outcome counters, track records, red-line and announcement paths must remain in place around the imported repair.

## Issues, verification and remaining work

Evidence root: `/private/tmp/drf-forecast-commitment-in9y9u3h`. Each source mirror has a SHA-256 manifest beside it; each run has a separate unchanged-runner evidence directory.

- `red`: Both original regressions fail on main because unrelated notices and second-offer acceptances fulfil old promises. These are behavioral failures, not setup failures.
- `focused-v1`: 63 passed, one failed, two calendar cases deselected for separate execution. The failed assertion pinned the old 900-character private-brief default; main deliberately increased it to 1300. The ported test now checks the current budget while retaining the complete breach/credibility feedback checks.
- `main-fixtures-v1`: Four passed and three failed because the track-record fixture still treated another announcement as delivery. The fixture now confirms a real delivery through menu/parser/validator/application, retaining the expected one kept and one lapsed commitment plus the newly real successful-outcome count.
- Exact-match repair hunks were applied only to owned paths. Overlapping hunks were reconciled manually around main's stored announcements, expectation recording, red-line processing and outcome counts. No old whole production file was substituted.
- Independent reviewer Kepler is checking the scoped diff without editing files or importing the app.

- `focused-v2`: 71 passed, two calendar cases reserved for their isolated runs.
- `core-v2`: 256 passed and one failed because the first mirror omitted the repository's unchanged `deerflow_bridge` sources. This was a mirror construction error, not a product defect. `source-v3` adds those 92 tracked files; `core-v3` then passes all 257 cases. No fixture, production logic or guard was changed for that recovery.
- `continuous-v2`, `resume-v2`, `world-loop-v2`, `calendar-loop-v2`: 1, 1, 11 and 7 passed respectively. All accepted runs exited normally with complete shutdown, identity preserved and no runner-reported source drift. Manual manifests verify every owned production/test file against both mirrors and worktree.
- Initial accepted candidate totals 277 unique cases, but independent review found P2: general substring matching admits `Actor10` as `Actor1` and `Actor00` as `Actor0`, including stringified malformed targets and shared aliases. This defect was inherited from the repair. `review-red` reproduces 13 behavioral failures with eight passing controls against the preserved candidate.
- Review followup adds exact candidate matching for delivery targets, direct delivery registration and arbiter identity claims. Ambiguous aliases implicate every matching actor during duplicate detection; numeric IDs stay numeric if display-name canonicalization would introduce ambiguity. Ordinary descriptive matching remains available through the unchanged default resolver behavior. New controls cover valid IDs, names and unique aliases.

- `review-green`: 84 commitment cases passed after the exact-identity repair. The `source-v4` candidate then passed 297 unique cases across all gates.
- Rereview closed guessed identity but found a new P2: the parser converted a valid numeric counterparty ID to an ambiguous display name before registration. Three counterpart-collision cases reproduced that loss; five ID-tampering controls also failed before the added metadata boundary. All eight failures are retained in `counterparty-red`.
- The menu now supplies `option.commitment_target_ids` from the stored obligation. The parser preserves those IDs alongside display names. Registration checks typed IDs against the current agreement, stores them on the current action, and resolution rechecks them. Canonical display names remain presentation data; guessed names still fail. Historical rows without this added metadata retain the previous compatibility path.
- `counterparty-green`: 92 commitment cases passed, with the two coordinator cases reserved for separate acceptance. `source-v5` and its full source manifest are the current freeze. The coordinator owns aligned README edits and subsequent Git operations; this worker has not modified Git state.

## Accepted freeze and independent review

Kepler independently reviewed the eight owned production/test files and closed both P2 findings with no remaining actionable defects. The [review receipt](/private/tmp/drf-forecast-commitment-in9y9u3h/review-accepted.json) records the finding history, closure and reviewed SHA-256 hashes. Source-v5 owned bytes are unchanged in the final `source-accepted` mirror and the working tree.

The final source audit detected one early peer `report_agent.py` snapshot in the earlier mirrors. The final mirror restores that dependency to the base commit, without changing any worktree file. Every non-owned file in `source-accepted` was checked against the Git blob at `ac488913`. The entire mirror was rehashed after acceptance. This proves the owned world integration against main; the coordinator still owns combined forecast-feedback acceptance.

| Accepted gate | Passed | Receipt |
|---|---:|---|
| Core, including all main realism suites | 285 | [completed](/private/tmp/drf-forecast-commitment-in9y9u3h/core-base-accepted/completed.json) |
| Real calendar coordinator, continuous | 1 | [completed](/private/tmp/drf-forecast-commitment-in9y9u3h/continuous-base-accepted/completed.json) |
| Real calendar coordinator, restart after delivery | 1 | [completed](/private/tmp/drf-forecast-commitment-in9y9u3h/resume-base-accepted/completed.json) |
| Existing world coordinator regressions | 11 | [completed](/private/tmp/drf-forecast-commitment-in9y9u3h/world-loop-base-accepted/completed.json) |
| Existing calendar-loop regressions | 7 | [completed](/private/tmp/drf-forecast-commitment-in9y9u3h/calendar-loop-base-accepted/completed.json) |

There are **305 unique passing cases**, zero failures/errors/skips in the accepted gates. The two new calendar cases are deselected only from the core gate and each executed separately. Every accepted process exited 0 normally, completed shutdown, preserved identity and reported no source drift. The immutable receipts, JUnit paths/hashes, exact argv and cwd, source manifest, consequence comparisons and review closure are indexed in [verification-accepted.json](/private/tmp/drf-forecast-commitment-in9y9u3h/verification-accepted.json). Its SHA-256 is `cc54c5f899ad9f7e077bf73f0dd7d1939de09f0879ea1d2573c54c6a4963f89b`.

The accepted runtime gates each record one blocked socket creation, four blocked subprocess attempts and 20 blocked external reads, alongside three storage redirects and OASIS import quarantine. Recorded native probes include `fc-list`, `system_profiler` and 18 font-directory scans. These are blocked attempts, not zero activity or live-provider evidence. The unchanged runner SHA-256 is `8c8bb8f6c0e4e5decee8f167603a4eb47711ec562e028d19f9d3d6bee1741815`; its CPython audit boundary is not an OS sandbox. No guards were weakened. Static AST parsing of all eight owned Python files and scoped `git diff --check` also pass.

### Owned source hashes

Full snapshot: [source-accepted-sha256.json](/private/tmp/drf-forecast-commitment-in9y9u3h/source-accepted-sha256.json), SHA-256 `96242481f08a9a2e943e133d4c1eb03874314eb59646a8cfbe959170a7ae7341`.

```text
2673149b82e606abd008f62c31a4ea5019358ee31f8b376314052711730fea43  backend/app/services/world_model.py
695f29f4558f78f5fecc98cd8dfe79dab247f414fe669fe83ad6f5dee12c655f  backend/app/services/agent_decision.py
91116f0a92fce1a6b65a312f29b6b9cfe24094ffdb97da0b6cadbf1d1cf38f56  backend/app/services/world_update.py
c404da182ed40a36fcb42a025e3958885259528ce60d0d423389a050dc534873  backend/tests/test_world_commitment_fulfilment.py
73372a548871a03705eace3744e98d272fb4b86382532d8dfb7318af94dc1099  backend/tests/test_world_model.py
9bcc23d1b1bbabc7340683e3ef4f583671cf60601785fca07dafa5ae17c5328b  backend/tests/test_world_interactions.py
642ea9afbb4c015f99c20bb0f9e1b0bd73f0c86c4f63d1289e4ed6b138648a6b  backend/tests/test_world_model_loop.py
cfeaeb8dc14dc5cbc5a79b6d9b817c3fb1afe70bb7caa19b79f798ba831a53c6  backend/tests/test_world_track_records.py
```

This record is the ninth owned file. The coordinator's README and feedback implementation files were not modified by this worker. No Git index, branch, commit or remote state was changed.

### Concrete behavior and limits

Unrelated actions and new consent leave prior promises open. A specific delivery attempt spends one unit and requires the owned promise, current round and correct stored counterparty. Successful arbiter confirmation must identify that exact current attempt and supply a nonempty rationale. Partial/failed/pending outcomes, stale or malformed identities, ambiguous aliases, duplicate/conflicting attestations and replay cannot grant fulfilment or duplicate delivery outcome credit. Numeric counterparty binding survives decision serialization and saved-world reload. Main's announcements, track records, expectation comparisons, red lines and world pressure remain exercised by the accepted gates.

The real coordinator scenarios create and accept an agreement in R1/R2, confirm Actor0's delivery in R3, leave Actor1's unrelated picnic announcement due, apply one breach in R4, and feed the actual breach into the R5 actor prompt and posted response. The external model replies and platform environment are synthetic; the menu, parser, coordinator, state transitions, arbiter validation/application, persistence and restart are production code.

[Consequence traces](/private/tmp/drf-forecast-commitment-in9y9u3h/consequence-traces-accepted.json) retain both runs' artifact hashes and exact comparison. Principal commitment evidence, track records, reputations, commitment events, relationship polarity and history agree after restart. Existing four-decimal relationship-strength serialization leaves 0.3783 versus 0.3782, so whole-world equality is not asserted.

This establishes mechanics and feedback with synthetic external responses, not live-provider quality, empirical realism or forecast accuracy. Arbiter-off/failure leaves delivery unconfirmed under existing deadlines. Historical closed records remain preserved rather than retroactively rescored. No deployment, service start, installation or default-engine promotion occurred.

## Coordinator handoff

No owned implementation or review followup remains. The coordinator can commit exactly these eight source/test files plus this record, then let Bacon review the combined feedback implementation. Preserve peer edits and the dirty primary checkout. The accepted command list is in [commands-accepted.txt](/private/tmp/drf-forecast-commitment-in9y9u3h/commands-accepted.txt); any rerun must choose fresh evidence directories.

Next-session prompt: “Continue forecast-feedback from main ac488913. The commitment integration is reviewed and passes 305 unique guarded cases; verify the owned hashes in commitment-integration.md and verification-accepted.json before the scoped world commit. Complete the separately owned feedback ledger/report acceptance and combined review without treating this world-only acceptance as proof of the entire feedback release.”

## Updates

- 2026-10-20: Created before production edits, after reading the approved plan, scoped handoff, prior repair verification and offline-verification/code-review skills.
- 2026-10-20: Captured main behavioral red evidence, integrated owned repair hunks, preserved newer main paths and recorded the two obsolete fixture assumptions with their red receipts.
- 2026-10-20: Recorded initial green gates, corrected the incomplete mirror, retained independent review's 13 red identity cases and implemented the exact-identity followup.
- 2026-10-20: Recorded the second review finding, preserved eight counterparty-boundary red cases, added durable target IDs and froze source-v5 after 92 focused cases passed.
- 2026-10-20: Independent review closed both P2 findings. All non-owned final mirror files were pinned to ac488913, all 305 accepted cases reran green, exact hashes and consequence/restart evidence were recorded, and owned integration was handed back for coordinator Git operations and combined review.
