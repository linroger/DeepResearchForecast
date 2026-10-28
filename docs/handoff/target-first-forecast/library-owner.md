# Cross-case library owner handoff

**Last Updated (UTC):** 2026-10-27
**Status:** In Progress
**Current Focus:** Implement and validate the narrow G6 library within the assigned three files.

## 1) Request & Context
The approved part2 G6 slice persists source-aware reference classes, mechanism templates and real-world actor records for reuse across cases. Ownership is exclusively `backend/app/services/forecast_library.py`, `backend/tests/test_forecast_library.py` and this document. The coordinator owns pipeline/research integration. This slice neither creates a forecast/outcome ledger nor changes probability policy. The existing topic PLANS.md and the user's extension approval authorize this implementation.

## 2) Requirements → Acceptance Checks
| Requirement | Scenario check | Evidence |
|---|---|---|
| Persistent cross-case reuse | Write a base rate and mechanism, then select both for a second case | Guarded pytest and stored JSON fixtures |
| Immutable, cross-kind content identity | Repeat an identical write, change content/kind, corrupt a saved row | Stable/distinct IDs and closed tamper rejection |
| Source and availability cutoffs | Select before and after source retrieval, publication and outcome dates | Boundary assertions |
| No simulation/outcome leakage | Reject simulation basis and unverified journal claims; validate real journal joins | Real journal fixture tests, no provider calls |
| Narrow integration | Document exact schema, storage root and caller obligations | This owner report and module docstrings |

## 3) Plan & Decomposition
Validate typed JSON and provenance first. Persist immutable content-addressed rows atomically. Select only relevant rows available at the requested cutoff, revalidating stored identity and outcome proof. Run targeted tests with the primary interpreter and worktree offline guard in fresh `/private/tmp` evidence directories. Review boundaries and provide the coordinator with exact interfaces.

## 4) To-Do & Progress Ledger
- [x] Read G6, frozen case contract and journal validation paths.
- [x] Implement library and scenario tests; initial guarded gate passed 42 cases.
- [ ] Run guarded tests, review findings and document integration.

## 5) Findings, Decisions, Assumptions
The existing `forecast_feedback.read_published_resolutions` validates the complete journal hash chain and recomputes publication/outcome bindings. Outcome-based learning must consume that authority rather than accepting a caller's verification boolean or a copied simulation score. Sources retain distinct evidence/publication/retrieval/availability dates. Hashes establish integrity, not external truth. Only the coordinator can establish that an input row was derived from the admitted case and actual sources.

## 6) Issues, Mistakes, Recoveries
The connection was interrupted after bounded source inspection, before code files existed. Resumed the same assignment without changing any other owner's files. Initial combined source output was too broad; subsequent inspection is targeted.

Independent read-only review found that a valid journal proof was insufficiently bound to reference-class counts, journal hashing inherited the small-entry size cap, and newly created parent directories lacked fsync. The implementation now binds journal-derived reference counts to one exact observation, including comparator, units and window; hashes large journal events without imposing the library entry cap; and fsyncs newly created parent entries. Regression tests cover contradictory counts and large snapshots. These constraints prevent a single event from authenticating an invented aggregate.

## 7) Scenario-Focused Resolution Tests
Planned checks cover second-case reuse, persistence/reload, content and journal tampering, cutoff enforcement, disjoint kind identity and rejection of synthetic outcome promotion.

## 8) Verification Summary
Initial targeted gate: **42 passed in 1.74s**. Evidence: `/private/tmp/drf-target-library-20261027-a/junit.xml` and `completed.json`. Exit code zero, shutdown complete, identity preserved, no source drift, and no blocked operations. Command used the primary `/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B`, the worktree's `backend/scripts/main_offline_pytest.py`, and the owned test module. This proves local synthetic-source producer/storage/selection behavior, not live evidence or forecasting skill.

## 9) Remaining Work & Next Steps
Complete owned implementation and tests, then give exact integration requirements to the coordinator. No pipeline, research, configuration, scheduler, provider or shared tracker edits are authorized for this worker. Delivery commits belong to the coordinator's combined change.

## 10) Updates to This File
- 2026-10-27: Created the owner continuity checkpoint before implementation; recorded scope, G6 constraints, acceptance checks and connection recovery.
- 2026-10-27: User added `publish_case_mechanisms`; implemented canonical case validation, source-aware metadata export, explicit skips, and immutable publication receipts without expanding file ownership. Added real second-case consumption tests and completed the initial 42-case guarded gate. Closed three independent review findings and requested follow-up review.

## Coordinator integration contract

Call `publish_case_mechanisms(library_root, accepted_case)` after research's canonical case has been accepted. Persist its returned receipt as `handoff/target_library_publication.json`. Its exact shape is `{schemaVersion: "forecast-library-publication/v1", caseId, caseHash, entries: [{mechanismId, entryId}], skips: [{mechanismId, reason}]}`. An invalid case raises before writing anything; individual entry writes are immutable and idempotent, so a failed batch can be retried safely. Storage failures and existing-file integrity errors propagate rather than becoming success receipts.

The producer retains original source objects, mechanism/parameter bases, parameter ranges, input/output identity, units and vintages. It copies no node values, scenario weights, actor performance, simulation scores, hindcast claims or outcome data. References come from mechanism or input-node sources; contextual input evidence is labelled as not validating the mechanism. Private inputs/outputs, unfetched or absent sources, and missing evidence dates yield explicit skips. No reference-class counts are invented. `nodeTerms` includes case-folded labels/IDs and Unicode word tokens for cross-case matches.

Before a later case's research, call `select_entries(library_root, as_of=case_as_of, node_terms=terms, kinds=None, limit=12)` and freeze that return in `handoff/target_library.json`. Selection matches exact case-insensitive terms; callers should provide full node labels/IDs and their word tokens where labels differ across cases. Returned rows include `entryId`, all metadata and source passages. Treat these as prior context with original case provenance; do not relabel them as freshly fetched evidence or promote probability policy. Limit is an integer in 0..100. A nonexistent library returns an empty list without creating directories.

`record_entry` is available for separately supported typed reference-class or real-world actor records, but this producer emits mechanisms only. Manual reference classes require explicit series, units, comparator, window and observed counts plus primary source provenance; producers remain responsible for verifying those observed counts. Journal-derived reference entries are deliberately limited to a single authenticated official observation. Outcome learning uses the configured existing production journal, independently of `library_root`; no arbitrary journal location or verification boolean is accepted in entry JSON. Event hashes use the journal's canonical event envelope. The journal reader revalidates hash chain and semantic bindings on write and read. Only official-data and named-source-event outcomes are admissible; scenario self-ratings and simulated results are excluded.
