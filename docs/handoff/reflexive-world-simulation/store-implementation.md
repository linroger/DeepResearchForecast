# WorldStore implementation handoff

**Last updated (UTC):** 2026-10-16T15:03:01Z
**Status:** All 43 prior store scenarios passed under the coordinator guard. A small accounting fix and stricter assertions are ready for the next frozen run (44 scenarios).

## Request and ownership

Implement the approved durable SQLite WorldStore. This worker owns only `backend/app/services/world_simulation/store.py`, `backend/tests/test_world_store.py`, and this document. The approved `implementation-contract.md`, `contracts.py`, and `contracts.md` are the interface authority. Shared contracts and other workers' edits remain coordinator-owned. No commits, provider calls, graph calls, or unguarded application imports are permitted.

## Requirements and acceptance checks

| Requirement | Scenario and expected evidence |
| --- | --- |
| Durable atomic closure | Reopen after commit and compare snapshot, events, resolutions, decisions, and semantic revision; reject stale head without partial writes. |
| Writer fencing | Reject live-owner takeover and stale-fence writes; allow explicit takeover after confirmed process death. |
| Receipt identities and phase membership | Freeze proposal and response rosters; reject wrong-slot observations, substituted decisions, missing receipts, and duplicate events. |
| Conservation and closure | Reject account creation, unit/owner changes, resource creation, and missing actor/pending/sampling sections; preserve valid balanced transfers and reservations. |
| Durable call budgets | Persist unknown dispatch exposure, enforce attempts across reopen, and serialize simultaneous reservations against run-wide token/cost limits. |
| Read-only and detached readers | Reopen read-only without repair; reject writes and prove returned JSON cannot mutate authoritative state. |

## Plan and progress

1. Read the approved contracts and inspect consumer conventions. Done.
2. Implement versioned SQLite transactions, fencing, and detached readers. Done in source.
3. Implement phase/receipt persistence and reservation accounting. Done in source.
4. Implement complete round closure and targeted regression scenarios. Done in source: 24 test functions expand to 44 scenarios after the final accounting-bound regression.
5. Review source and syntax without importing the application, request independent source review, and hand off the test file for guarded execution. AST and Ruff passed. Independent rereview found no further store blocker. The second coordinator run passed all 43 then-current store scenarios; the coordinator owns the canonicalization fix and final rerun.

## Findings, assumptions, and decisions

SQLite `BEGIN IMMEDIATE` will serialize every mutation; head and fence comparisons occur inside the same transaction as the write. Semantic revisions include only canonical snapshot, prior revision, and ordered round evidence. Reservations are persisted before a dispatch; unfinished/unknown attempts retain their full exposure across restarts. The store does not dispatch any external work.

The controller shares its store with policy threads. A connection-level reentrant lock protects connection use, while SQLite `BEGIN IMMEDIATE` protects budget reservation across separate connections. Known finished usage frees unused allowance; an unknown result retains the full reservation. `budget_summary()` returns `reserved` (lifetime allowance, including later reconciled reservations), `actual` (known finished usage), `unknown` (full outstanding/unknown allowance), `exposure` (`actual + unknown`, the amount checked against the run ceiling), and the durable attempt records. These categories must not all be added together.

The result-reader convention is frozen as `rounds() -> [{round, revision, snapshot, events, resolutions, decisions}]`, excluding round zero. `head()` and `history()` snapshots include `revision`; history includes round zero. `read_bundle()` returns `{spec, head, rounds, history, budget}` within a single explicit SQLite read transaction, including for `mode=ro` readers. Tentative receipts never appear in committed events/resolutions/rounds. Initial scheduled events are committed in the initial snapshot and event ledger through `kernel.initialize_world(spec)`.

Round commit replays the bounded pure `kernel.resolve_round` against the stored prior snapshot and exact persisted decisions and compares canonical snapshot/events/resolutions. This deliberately adds a second pure calculation to commit validation so pending obligations, actor state, scheduled effects, sampling, and event provenance cannot diverge from the mechanism implementation. There are no external effects during replay. No shared contracts were edited. Reopen validates the entire contiguous semantic revision chain and its event index before exposing historical rows.

Writer liveness is conservative: a known current PID is alive without a probe; another PID requires a signal-zero check. Permission/OS uncertainty is treated as alive, and PID reuse cannot make a live process stealable. Explicit takeover requires a confirmed absent PID. The process-death regression simulates loss and liveness deterministically; it is not a host-process kill test.

## Issues and recoveries

Independent source review identified missing pending-record continuity, insufficient nested shared snapshot validation, unchecked historical commit content, and weak event causal/provenance checks. Store-owned recovery fixes and full pure transition replay address the persistence boundary. The shared `contracts.validate_snapshot` nested-schema gap was reported to the coordinator; that file remains coordinator-owned.

Rereview identified one integration issue in coordinator-owned `controller.py`: after `save_decision()`, the worker returns its original dictionary, while store persistence applies NFC canonicalization. With a text enum containing composed `é` and a raw decomposed `e` plus combining acute accent, first execution can reject while canonical replay accepts. Required coordinator fix: return `store.decision(slot)` after persistence (or normalize the shared validator's return), then verify first execution and recovery consume identical decision bytes without another attempt. The strict store replay comparison should remain. Reviewer confirmed no additional constructor/replay blocker at the recorded store hash; review was source-only.

The original guarded runner rejected every `file:` SQLite URI and nonowned signal-zero liveness probe. The first coordinator run therefore blocked store/controller construction on `sqlite_uri`; this is not evidence that store behavior passed or failed. The coordinator subsequently implemented narrowly bounded URI admission and negative controls; the second run passed the store scenarios. Production read-only mode remains `mode=ro`. Writable connections use ordinary paths. Three Ruff loop-variable warnings in immediate test lambdas were fixed by explicitly binding their loop arguments.

Final source review found an accounting-bound edge case: with a supported maximum reservation of `1e30`, finishing one attempt at known zero usage permits a second full reservation, making lifetime reserved allowance `2e30` while current exposure stays `1e30`. Passing that cumulative audit total through the scalar input validator made `budget_summary()` fail. The store now formats the exact cumulative Decimal directly; per-attempt input validation and run exposure limits are unchanged. A focused regression covers this case. Replay-substitution tests now assert the exact expected error codes, as recommended by independent review.

## Verification

This worker has run no application imports or runtime tests. AST parsing of the two owned Python files passed. `ruff check --no-cache backend/app/services/world_simulation/store.py backend/tests/test_world_store.py --output-format concise` passed. Focused diff whitespace checks passed.

The coordinator's first frozen guarded run reported 49 failed and 99 passed, with store/controller failures blocked by `sqlite_uri` (console inspected). Evidence: `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-world-first-20261016T145815Z-fc5a1m88/evidence`; console is its sibling `console.log`. The coordinator reported no source drift for that frozen run. This run predates the latest ordinary-path writable connection change.

The second frozen guarded run reported **218 passed, 1 failed**, with `sourceDrift: []`. This worker inspected its console, verification summary, source manifest, and JUnit XML. All **43 store cases passed with zero failures/errors**, and the then-current owned Python hashes exactly matched the frozen manifest. The only combined-suite failure was `test_world_policy.py:309`, where a test called `.as_dict()` on SDK timeout integer `17`; that file is outside this worker's ownership. Evidence: `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-world-second-20261016T150115Z-iamdldpa/evidence`.

Source hashes at 2026-10-16T14:59 UTC:

- `store.py`: `7e44b05fa4b8c7c39176e64e3dac7c541310b8ef18fefb11790341f09b2adcde`.
- `test_world_store.py`: `da916e15a950b41c4b872cc7345b31a1d63ec09b0febc343d4fcf0aa698671c3`.

The following source hashes include the subsequent cumulative-audit formatting fix and strict error assertions. AST and Ruff pass; guarded execution of this delta remains coordinator-owned:

- `store.py`: `845930020ac3e487ba6c53185a22e9b193d48f3b39de1cf6976ae0ba8b08657c`.
- `test_world_store.py`: `4499bc43a3eebc116842092a25c62549c64b1c220189803078fff1d4f9a18686`.

## Remaining work and next-session prompt

The owned files are stable. The coordinator should freeze and rerun the now-44 store scenarios with the controller canonical-decision return and policy-test correction. Check both test outcomes and guard receipts. This worker will address store-owned failures without editing shared contracts or the runner. No commits were created.

## Updates

- 2026-10-16T14:46:36Z: Created scoped continuity record after reading the three authoritative contract sources and existing root/project handoffs.
- 2026-10-16T14:59:03Z: Recorded implementation, exact reader/budget conventions, 43 test scenarios, initial independent review and fixes, AST/Ruff evidence, initial blocked guarded run, and the coordinator-owned harness follow-up.
- 2026-10-16T15:01:00Z: Independent source rereview completed. Recorded its controller canonicalization finding and requested the coordinator-owned fix; the owned source files remain stable at the recorded hashes.
- 2026-10-16T15:03:01Z: Verified second-run source bindings and JUnit evidence (43 store scenarios passed), added cumulative-reservation audit-bound regression and fix, tightened review-test error assertions, and recorded stable updated hashes for coordinator rerun.
