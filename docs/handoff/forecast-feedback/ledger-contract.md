# Published forecast ledger contract

Status: owned ledger slice, committed-outcome getter and producer-rounding
compatibility correction implemented, independently reviewed and guarded-verified;
bytes ready for integration. Owner: ledger worker. Base: main ac48891.

## Callable interface (all exported by `app.services.forecast_ledger`)

```python
record_published_forecast(forecast, *, report_id, created_at, d=None) -> dict
read_published_forecast(report_id, *, d=None) -> dict | None
read_published_resolutions(report_id, d=None) -> list[dict]
list_published_report_ids(d=None) -> list[str]
forecast_publication_digest(forecast) -> str
verify_published_forecast(forecast, *, report_id, d=None) -> dict | None
list_outstanding_published_questions(*, as_of=None, limit=100, d=None) -> list[dict]
outstanding_published_report_ids(*, as_of=None, limit=20, d=None) -> list[str]
mark_published_report_checked(report_id, *, checked_at, selection_token=None, d=None) -> dict
reconcile_published_resolutions(report_id, *, market_rows=None, data_rows=None, d=None) -> dict
resolve_published_scenario(report_id, outcome, *, evidence=None, resolved_at, d=None) -> dict
production_track_record(*, d=None, exclude_report_id=None) -> dict
verify_production_track_record(summary, *, exclude_report_id=None, d=None) -> bool
```

Publication returns `{report_id, created_at, publication_sha256, forecast,
record_class: "production"}`; identical publication returns the first stored row.
The `forecast` is a detached immutable-by-storage snapshot, suitable for passing to
the native monitor. Publication identity excludes top-level mutable audit, quality,
and track-record metadata, and includes all scenario/binary fields and substantive
top-level fields. Retrying with another timestamp preserves the original timestamp.
Conflicts, invalid input and evaluation publications raise `ForecastFeedbackError`
(a `ValueError` subclass with a stable `.code`). Persistence failures raise `OSError`;
integrators MUST make failures observable and prevent a successful publication.
An absent report returns `None` from read; resolution never backfills a publication.
`publication_sha256` is the pure `forecast_publication_digest(forecast)` value.
`verify_published_forecast` is read-only: exact match returns the stored row, absent
returns None, mismatch raises `publication_conflict`. It never repairs or registers.

Scenario resolution accepts an exact, unique, case-sensitive stored scenario name
only. It returns `{report_id, forecast_id: null, kind: "scenario", outcome,
resolved_at, evidence, publication_sha256, score}`. `score` contains `brier`,
`realized_probability`, `log_loss`, `n_scenarios`,
`outcome_matched_a_scenario: true`. Identical outcome retry preserves original evidence;
conflicting outcome raises. No fuzzy name/index lookup and no binary-to-scenario join.
Scenario probabilities must be finite and each lie in [0, 1]. Their total may
deviate from 1 by at most 0.0005: this covers the producer's four-decimal rounding
of up to five scenarios (maximum accumulated rounding error 0.00025), without
adopting the broader publication gate's 0.015 tolerance. Issued probabilities are
never renormalized; the original values determine the digest and multiclass score.

Reconciliation returns `{accepted: int, duplicates: int, rejected: list[dict]}`.
Each rejection has `kind`, `forecast_id`, `reason` (stable error code).
`None` rows means read the existing native resolutions JSONL; `[]` means no rows
for that kind. Only rows for this exact report are considered. Native market
`"Yes"`/`"No"` are converted explicitly to strict boolean outcomes; other strings
and numeric truthiness are rejected. Market evidence requires a terminal price
consistent with its outcome and an original `resolution_equivalence: "exact"`
anchor. Official outcomes must be strict bool and reproduce from the hashed original
dataset snapshot under the original anchor and resolution cutoff. Both require
original forecast ID, original probability and exact anchor identity. Native
precomputed Brier contributions are ignored. All retained outcome evidence is
copied into the append-only journal.

`read_published_resolutions` returns only committed typed outcomes from the validated
journal, sorted by `(kind, forecast_id)`; scenarios have `forecast_id: null`.
Rows contain `{report_id, forecast_id, kind, outcome, resolved_at, evidence,
publication_sha256, score}` with original frozen evidence and the authoritative
derived score. Use outer `outcome`/`score` for monitor presentation; any precomputed
score inside retained native `evidence` is observational input only. Absent or
unresolved reports return `[]`; native candidates and rejected conflicts are never
returned. The result is detached, and reads neither create nor change files.
Full journal and binding validation fail closed even when a report has no outcomes.

## Track record schema

```json
{
  "schema_version": 1,
  "source": "published_forecasts.jsonl",
  "source_digest": "<sha256 of included publication and outcome facts>",
  "journal_length": 5,
  "journal_sha256": "<sha256 of the complete captured journal prefix>",
  "excluded_report_id": null,
  "n_reports": 2,
  "tracks": {
    "scenario": {"n_forecasts": 2, "n_resolved": 1, "n_outstanding": 1, "mean_brier": 0.18, "coverage": 0.5},
    "market_binary": {"n_forecasts": 1, "n_resolved": 1, "n_outstanding": 0, "mean_brier": 0.09, "coverage": 1.0},
    "official_data_binary": {"n_forecasts": 1, "n_resolved": 0, "n_outstanding": 1, "mean_brier": null, "coverage": 0.0},
    "unanchored_binary": {"n_forecasts": 0, "n_resolved": 0, "n_outstanding": 0, "mean_brier": null, "coverage": 0.0}
  },
  "legacy_scenario": {"source": "ledger.jsonl", "n_resolved": 0, "mean_brier": null},
  "scored_identities": [
    {"report_id": "r1", "forecast_id": "F1", "kind": "market_binary"},
    {"report_id": "r1", "forecast_id": null, "kind": "scenario"}
  ]
}
```

The example is illustrative. Scenario Brier is multiclass, binary Brier is `(p-y)^2`;
there is deliberately no pooled score across these denominators. Empty means null
Brier. One report contributes one scenario forecast and each binary contributes
exactly once. If both anchors exist, official-data is the authoritative scoring
lane; the market remains observational. Legacy scenario rows remain separately
labeled, exclude evaluation and already registered report IDs, and never claim
immutable publication provenance. `exclude_report_id` excludes that report from all
counts, scores, legacy rows and the source digest. Scores are descriptive track records,
not a claim of empirical calibration.

`verify_production_track_record` returns True for an exact canonical typed summary
recomputed from the captured journal prefix, or raises `track_record_mismatch` /
`track_record_prefix_mismatch`. It binds the caller's `exclude_report_id`, counts,
scores, scored identities and source digest. Later appended events do not refresh
or invalidate the captured history. The full current journal is still validated;
corruption after the prefix fails closed. `legacy_scenario` is outside the typed
digest and verification because its source is mutable; it must never be presented
as proven immutable publication history. The canonical report renderer only renders
the verified typed tracks. Report owners must capture their own summary rather than
accept a model-provided snapshot or silently replace a published snapshot on restart.

## Outstanding queue and durability

Question rows are `{report_id, forecast_id, kind, probability, resolution_date,
created_at, publication_sha256, binary, selection_token}`; `binary` is the original snapshot.
Only unresolved binaries appear. `as_of` filters future known due dates; unknown
dates remain eligible. Reports are ordered by least recently checked journal
sequence first, then earliest due date, creation instant and ID. Unchecked reports
precede checked reports. Call `mark_published_report_checked` after every attempted
report (including unavailable/manual outcomes) to rotate fairly across old due
reports and restart. Both lists enforce a nonnegative finite integer limit.
Visits also rotate each report's eligible question prefix so a question limit
cannot permanently hide later questions behind an unresolved/manual first item.
Limited question-batch consumers MUST pass the returned `selection_token` when
marking that report checked (once per report batch). This makes concurrent attempts
on the same selected generation advance only once; stale marks preserve the already
recorded visit. Whole-report monitors can continue omitting the token because they
process the report's complete question set.
Official due dates derive from the frozen canonical observation period and frequency,
including fiscal periods; unrecognized periods remain eligible for manual review.

One checksummed, append-only `published_forecasts.jsonl` holds publications,
outcomes and queue visits. The same mandatory process/file lock protects complete
read/check/append transactions. Flush/fsync precedes successful return. Torn tails,
bad JSON, checksum errors and inconsistent journal facts fail closed, with no
silent skip, repair or overwrite. Scores reconstruct from durable outcomes after
restart or interruption between persistence and rendering; no mutable score cache.

## Verification ledger

Current owned-byte gate: **199 passed in 9.25 seconds**, including the new ledger
module and existing forecast-ledger, resolution-monitor, and official-data-downstream
modules (including the exact G5 compatibility assertion). Evidence:

- `/private/tmp/drf-ledger-rounding-6q77ed85/evidence/completed.json`
- `/private/tmp/drf-ledger-rounding-6q77ed85/evidence/junit.xml`
- `/private/tmp/drf-ledger-rounding-6q77ed85/source-hashes.json`

The parent and all three guarded child receipts show exit 0, normal shutdown,
identity preserved, no source drift and no blocked events/network attempts. App
imports and tests ran only under the existing unchanged guarded runner and
provisioned interpreter in a fresh private mirror. Owned Python source hashes
were rechecked against the mirror after completion:

| Owned file | SHA-256 |
|---|---|
| `backend/app/services/forecast_feedback.py` | `5e4f4eb48adff25bbb25bf0c7df661531b8f1584fdabda6da73c0a82bd5a3209` |
| `backend/app/services/forecast_ledger.py` | `2576a04a669586c7ebe94550d5d5ef1a8754c51bf65b42809e068e7164c0edc5` |
| `backend/tests/test_forecast_feedback_ledger.py` | `34e7f4f852fc9c93efa7dacb3abf556bf34cda5e93601e065ecd8f2aa9eb52ed` |

Independent reviewer Tesla (`01a159ed-2ed0-7ba0-85da-3436cd7ef8dd`) closed every
finding on the prior helper hash `30eb926914aeab8bcb3214979f0006f56d0fc3524010c83602023c7f279c435b`: fsync retries, frozen official metadata,
official due periods, fiscal aliases, fair token-based question rotation, and
frozen prefix verification. The reviewer performed static review; the ledger
worker ran and inspected the guarded tests/receipts. AST parsing and scoped
whitespace checks passed. The reviewer also closed the additive read-only getter,
export and five regression cases with no findings on the getter gate's Python
hashes; this review covered read-only behavior, full-state validation, report
isolation, detached results and retention of committed outcomes after conflicts.
The final bounded rereview also closed the producer-rounding correction and its
three regressions on helper hash `5e4f4eb48adff25bbb25bf0c7df661531b8f1584fdabda6da73c0a82bd5a3209`.

Remaining boundary: coordinator-owned final publication, SDK, monitor scheduling,
next-report rendering and their complete acceptance remain separate work. Current
whole-report `_cmd_run` uses the compatible ID selector and tokenless mark; the
fiscal/report-order fixes apply there directly, and it processes the complete
original binary set. Only limited-question-batch callers need the new optional
selection token. No report/monitor/SDK files or shared Git state were changed by
the ledger worker. No provider, deployment, service, install or live calibration
claim is made.

Initial guarded gate: 60 passed (new focused ledger module plus existing
`test_forecast_ledger.py`), 4.46 seconds. Fresh mirror and receipts:
`/private/tmp/drf-ledger-guard-otsboy7e/`; `evidence/completed.json` reports exit 0,
normal shutdown, preserved identity, no source drift and no blocked events.
Three guarded child processes independently competed for the same publication;
exactly one durable row remained. Source hashes are in `source-hashes.json`.

Exercised immutable publication, exact native joins, interruption after durable
outcome write, reload, duplicate/conflict, queue fairness, evaluation exclusion,
thread/process concurrency and corrupt/torn rejection. External observations are
synthetic; producer/monitor/report integration belongs to coordinator acceptance.
Independent static review was pending at this historical gate; the final gate
above supersedes it. Existing legacy ledger APIs retain their compatibility contracts.

## Updates

- 2026-10-20: Frozen callable signatures and summary schema before implementation;
  added exact SDK scenario settlement and self-report exclusion.
- 2026-10-20: Added pure digest and read-only verification APIs; implemented all
  exported interfaces and recorded the first 60-test guarded gate.
- 2026-10-20: Broadened compatibility gate passed 175 tests. Review identified
  incoming-dataset frequency substitution and within-report question starvation;
  added frozen frequency/geography checks and durable visit-based prefix rotation.
  Fsync retries now reestablish durability; data due dates use observation periods.
  Added list_published_report_ids and production eligibility/finite-score filtering
  to the legacy official-data summary, retaining legitimate unregistered outcomes
  with legacy provenance documented in its API docstring. Updated-byte
  verification remains pending.
- 2026-10-20: The review gate at
  `/private/tmp/drf-ledger-review-gate-mmpgcgp0/` passed 177 tests and failed G5's exact
  legacy response-shape assertion. Removed the additive provenance field from the
  legacy response; eligibility and finite-score filtering remain. The failure
  receipt is preserved; a fresh corrected gate follows.
- 2026-10-20: Added journal-prefix proofs and read-only frozen track-record
  verification so report restart preserves the historical counts while later
  outcomes accrue. Mutable legacy scenarios are explicitly outside that proof.
- 2026-10-20: Prefix gate passed 189 tests. Independent review closed the fsync,
  frequency and frozen-summary findings, and found two residual queue edge cases:
  fiscal aliases and synchronized pollers. Canonical fiscal period precedence and
  idempotent selection-token advancement now address those cases; fresh gate pending.
- 2026-10-20: Final fresh gate passed 191 tests; all reviewer findings closed on
  the final helper bytes. Recorded exact hashes, parent/child receipt checks and
  coordinator integration boundaries. The ledger slice is ready.
- 2026-10-20: Added exported read_published_resolutions for authoritative monitor
  presentation after candidate conflicts. Added coverage for missing/native-only
  records, detached copies, restart, retained first evidence/score, torn tails and
  invalid bound scores. Previous hashes are historical until this new gate completes.
- 2026-10-20: Getter gate passed 196 tests. Parent and three child receipts confirm
  normal completion, no blocked events/network attempts and no source drift.
  Rehashed owned Python files against the frozen mirror and recorded current hashes.
- 2026-10-20: Independent getter rereview closed with no findings on the tested
  bytes. The updated owned ledger slice is ready for coordinator integration.
- 2026-10-21: Replaced the overly strict 0.000001 scenario-total tolerance with
  bounded 0.0005 producer-rounding tolerance, preserving each issued probability
  in the snapshot, digest and score. Added exact 0.3333-thirds and out-of-bound
  distribution regressions. The existing publication producer remains unchanged.
- 2026-10-21: Final rounding gate passed 199 tests; independent reviewer closed the
  tolerance choice and regressions. Parent/child receipts have normal shutdown,
  no blocked/network attempts and no source drift; owned Python hashes match the
  mirror. The preceding 196-test getter evidence remains preserved at
  `/private/tmp/drf-ledger-outcome-read-3fp43grh/`. Updated bytes are ready.
