# Bounded discovery questions — Part E

**Last Updated (UTC):** 2026-10-23
**Status:** Complete (bounded discovery slice only)
**Current Focus:** Parent integration of the verified, uncommitted write set.

## 1) Request & Context
Implement only the bounded simulation-derived investigation experiment from Part E of the parent plan. The user explicitly granted the additional narrow `simulation_record.py` producer integration after confirming that `simulation_diagnostics.py` does not yet exist. Parent owns adaptive runtime, reports, orchestrator, config and managers. Preserve concurrent edits; no primary-checkout writes, commits or live execution.

## 2) Requirements → Acceptance Checks
| Requirement | Scenario check | Expected evidence |
|---|---|---|
| Actual producer integration | Compile real fixture artifacts and call `write_record`, then load the question sidecar through the published-record consumer. | Persisted artifact and guarded scenario receipt. |
| Hypothetical source linkage | Follow every question's JSON pointer into the exact hashed record. | Source hashes match; labels explicitly deny evidence/probability admission. |
| Bounded deterministic selection | Repeat generation, duplicate candidates, exceed candidate/question caps and use empty/unusable runs. | Stable IDs/bytes, dedup counts, explicit terminal reasons and no automatic execution. |
| Safe reuse | Change record inputs; tamper/remove the sidecar; fail its atomic write. | Stale or incomplete generations are rejected; unrelated files survive. |
| Existing boundary preserved | Run record/gate/report consumer regressions. | Existing record schema, renderings and probability isolation remain intact. |

## 3) Plan & Decomposition
The approved parent PLANS.md and first-principles review section 7 govern this slice. Reuse the record's existing turning-point selection (crossed red lines, accepted/breached offers and large state changes) and modeling gaps. Implement the question compiler and verified reader in one narrow module, add the sidecar write in `write_record`, and exercise actual producer/consumer paths under the existing guarded runner. Obtain independent review before delivery.

## 4) To-Do & Progress Ledger
- [x] Read the parent plan, review, existing record contracts and offline runner.
- [x] Confirm ownership expansion with the user.
- [x] Implement bounded generation, persistence and verified loading.
- [x] Capture focused and existing-boundary guarded receipts: 170 existing-boundary cases and 23 final focused cases passed; 25 separate runner controls passed.
- [x] Resolve independent review and document final source hashes: Peirce reported no actionable correctness issues on the final source/test bytes.

## 5) Findings, Decisions, Assumptions
The existing `simulation-record/v1` schema rejects extra fields, so investigation questions live in `simulation_discovery_questions.json`, outside record prose and probability inputs. Source links refer to simulated origins, never external corroboration. The consumer requires the existing publication gate and reproduces the deterministic artifact before returning it, rejecting stale/tampered generations. This slice introduces no research executor or runtime setting.

`simulation_diagnostics.build_discovery_questions(record)` returns schema `simulation-discovery-questions/v1`. `simulation_record.write_record()` persists it atomically and returns its path as `discovery_json`. `simulation_diagnostics.load_discovery_questions(sim_dir)` returns the verified artifact or `None`. The policy alternates recorded turning points and seed gaps, scans at most 128 supplied candidates, emits at most six unique questions with two queries each, and enforces a 600-character topic bound before and after Unicode normalization. Every question has support/refutation suggestions, a stable ID, hypothetical status and a JSON pointer bound to the exact record SHA256. A separate selection-input hash excludes synthesis, scenario shares and timestamps. Counts distinguish invalid/duplicate/capped/unscanned inputs; explicit terminal reasons never automatically resume.

## 6) Issues, Mistakes, Recoveries
The assigned diagnostics module was absent, discovered before edits. User granted the existing record producer integration. No changes were made outside the declared write set. Self-review reproduced two defects before fixing them: duplicate queries across origin categories and NFKC expansion past the text bound. Both have targeted passing regressions. No runtime or provider evidence is implied by offline results.

## 7) Scenario-Focused Resolution Tests
The tests use existing reflexive and world-v1 fixtures, deterministic synthesis disabled, and mutations confined to fresh guarded temporary directories. Actual terminal publication now produces a verified queue with provider construction forbidden; a second publication preserves identical bytes. A red-line crossing inserted into fixture history reaches a source-linked question. Sidecar and source tampering, missing/unpublished/symlinked artifacts, and changed-input partial writes return `None` from the verified consumer. A successful rebuild retains an unrelated sibling file. Health stubs and thin/no-world runs produce empty queues with explicit reasons. The same-evidence native-world comparison publishes distinct question topics while captured effective forecast messages remain identical under `diagnostic_only`, research present and a successful forecast spine.

## 8) Verification Summary
All application imports and test execution used `/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py` with fresh evidence directories. The [delivery summary](/Users/rogerlin/.local/share/DeepResearchForecast/verification/research-grounded-prepare/discovery-delivery-20261023/verification-summary.json) links the receipts and [source manifest](/Users/rogerlin/.local/share/DeepResearchForecast/verification/research-grounded-prepare/discovery-delivery-20261023/source-manifest.json). It also preserves the generated question artifact, its exact input record, producer/consumer receipts and independent review.

- `discovery-final-20261023`: 170 passed, zero failures/errors/skips, 80.37 seconds. This covers final production bytes and the test file before the last isolation addition.
- `discovery-isolation-20261023`: all 23 final focused cases passed, zero failures/errors/skips, 5.53 seconds. Final production and test-file bytes are bound in the receipt.
- `discovery-controls-20261023`: 25 runner controls passed. These intentionally attempt forbidden operations.
- All successful completion receipts report clean shutdown, preserved identity and no recorded source drift. The final focused run recorded no blocked operations. Broad regressions recorded denied `fc-list`/`system_profiler` and 18 font-directory probes, plus one permitted guarded child. These are attempted probes, not zero attempts. No network calls occurred in acceptance runs. The guard is a CPython audit boundary, not an OS sandbox.
- Scoped `git diff --check` passed. Reviewer Peirce independently checked the final hashes, origin pointers and receipts and found no actionable correctness issues.

Reproduction: run the guarded command with a fresh `--evidence-dir`, `-q`, and `backend/tests/test_simulation_discovery.py`. For the existing-boundary gate, also include `test_simulation_record.py`, `test_simulation_record_gate.py`, `test_simulation_record_integrity.py`, `test_simulation_record_routes.py` and `test_world_report_consumers.py`, all under `backend/tests/`.

## 9) Remaining Work & Next Steps
No open implementation defects remain in this slice. The parent receives three uncommitted source/test paths: `backend/app/services/simulation_diagnostics.py`, `backend/app/services/simulation_record.py`, and `backend/tests/test_simulation_discovery.py`. This dedicated handoff is the fourth owned path; the existing `.gitignore:100` ignores `handoff.md`, so the parent must explicitly preserve it if committing documentation. No staging, commits, primary edits or live execution occurred.

Existing published records are not backfilled and may have no sidecar; the verified reader returns `None`. The queue is not yet exposed through an API/UI or wired to a research executor. Upstream turning-point selection already truncates candidates, so the new omission counts do not claim coverage of every underlying dynamic. Prospective comparison with a simpler gap selector, equal-total-cost research, and actual independent evidence admission remain separate parent experiments; this artifact cannot establish forecast lift.

Next-session prompt: “Read `docs/handoff/research-grounded-prepare/discovery/handoff.md` and its delivery source manifest. Integrate only the reviewed bounded-discovery write set into the parent work, preserving all other owners. Treat the queue as hypothetical investigation questions, never evidence/probability inputs. Keep research execution separately authorized and do not silently backfill saved published records.”

## 10) Updates (append-only)
- 2026-10-23: Created the scoped handoff after explicit ownership expansion; recorded requirements, design and guard boundary.
- 2026-10-23: Behavioral red receipt `discovery-red-20261023` confirms the original `write_record()` omitted the sidecar (one assertion failure, not an import/setup error). Implemented the separate compiler/reader and a 12-line producer integration. The focused `discovery-focused-20261023` gate passed 18 tests, covering real reflexive/world-v1 producers, source pointers, paired support/refutation queries, caps, dedup, health/thin stops, source changes, tampering and atomic-write failure. Existing-boundary regression and independent review remain pending.
- 2026-10-23: The existing-boundary gate passed 166 cases and the guard self-test passed 25 controls. Two additional actual-consumer cases (history constraint and terminal publisher) passed in the 20-case focused rerun. Self-review then reproduced cross-category duplicate queries and Unicode normalization expanding past the topic limit (two behavioral failures in `discovery-edge-red-20261023`); fixed global topic deduplication and checked the bound after normalization. Final affected regression and independent review are in progress. Broad-suite blocked operations were only font-directory/platform probes (`fc-list`, `system_profiler`), with one permitted guarded fixture child; these attempts remained denied.
- 2026-10-23: Final 170-case gate and 23-case focused gate passed. The last test proves forecast-request isolation with distinct, actually persisted discovery sidecars. Independent review closed with no actionable issues; exact reviewed hashes match final production/test receipts. Preserved delivery artifacts and documented saved-record/API/UI/evaluation limits. Marked this slice complete; parent runtime and larger Part E evaluation remain outside its verdict.
