# Forecast feedback implementation plan

Approved by the user: integrate the commitment fix with main, then implement forecast-to-resolution-to-scoring including restart and the next report track record. This document makes that approved scope concrete; no further plan approval is needed.

1. Reconcile faae88f commitment semantics into main ac48891 while retaining new expectations, red lines, track records and pressure behavior. Re-run mechanical and real coordinator feedback/restart cases.
2. Preserve immutable published forecast probabilities and resolution contracts in a durable typed ledger. Join only identity-matched outcomes to their original forecasts. Keep market binaries, official-data binaries and scenario outcomes separate; never infer a scenario winner from one binary result. Duplicate/conflicting evidence must not overwrite the original score.
3. Extend existing resolution monitoring to outstanding ledger-backed forecasts. Persist outcomes and reconstruct scores from durable facts after restart. Exclude evaluation records from production track records.
4. Carry the durable score/coverage track record into the next actual report's forecast and rendered publication, with no unsupported claim of empirical calibration.
5. Independent acceptance: actual producer, native monitor, durable reload, duplicate resolution, changed report probabilities, invalid/conflicting evidence, and next-report consumer. Script only external responses; preserve publication/QA gates. Freeze source hashes, run guarded relevant regressions and independent review.
6. Update EN/ZH docs, handoff and feature/progress records. Commit owned paths, integrate with main after review, attempt authorized publication once if credentials permit. Preserve the dirty deployment checkout and do not restart services or run paid models.

Ownership: coordinator owns monitor/report consumers and docs; commitment worker owns three world production modules plus affected world tests; ledger worker owns forecast_ledger.py/new bounded feedback helper and unit tests; acceptance worker owns one new end-to-end module and scenario notes. No agent edits shared Git state.
