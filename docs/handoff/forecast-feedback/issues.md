# Issues

- FF-1 (in progress): Main broadly fulfills due promises for unrelated actions.
- FF-2 (in progress): Forecast/outcome/scoring/next-report join is incomplete.

- FF-3 (fixed, verification pending): Validated metadata removal left extra trailing newlines, so final lint rejected publication. Canonical whitespace joining now restores stable prose without weakening block validation.
- FF-4 (fixed, verification pending): Market settlement suppressed official-data resolution for dual-anchor questions. Official lane precedence now applies before native resolution selection.
- FF-5 (fixed, verification pending): Naive local completion timestamps were treated as UTC. New completion instants are timezone-aware; registration converts legacy local instants to UTC.
- FF-6 (worker fix, verification pending): Legacy official-data summaries admitted evaluation records. Eligibility and finite score checks now apply there too.
- FF-7 (fixed, verification pending): Saturated outcome queues starved interrupted-publication recovery. Recovery has an independent bounded scan with a durable fair cursor before the outcome queue.
- FF-8 (fixed, verification pending): Market response embedded identity could differ from requested key. Exact embedded identity and terminal label/price checks now precede native record construction.
- FF-9 (in progress): Validate durable frozen track-record provenance across report restart while later ledger events arrive.

- FF-10 (fixed, verification pending): Audit-time registration could outlive a failed visual replay rollback. Registration now occurs only at final save or explicit audited recovery.
- FF-11 (fixed, verification pending): Reopened forecast bytes could differ from checked publication. Registration now compares their SHA-256 to the checked seal.
- FF-12 (fixed, verification pending): Candidate conflicts were rendered despite ledger rejection. Public monitor outputs now use retained typed outcomes and preserve candidates separately.
- FF-13 (fixed, 11 compatibility cases pass): Visual replay modified canonical score metadata; exact verified block is now protected through stabilization.
- FF-14 (SDK worker): Module reload left an exception-class alias stale, turning conflict409 into500; live module lookup and ordered regression added.
- FF-15 (ledger worker): Support bounded rounding in issued scenario distributions without silently changing original probabilities.

## Final acceptance closure

FF-1 through FF-15 are resolved by implementation, focused regressions and the final accepted 812-case set. Remaining publication work is only the final reviewed commit/main fast-forward/push; this does not imply deployment or empirical calibration. No new unresolved application issue remains in the approved slice.

- DELIVERY-1 (blocked): GitHub rejected the authenticated push of reviewed local main with Invalid username or token. Source/acceptance are complete; restore credentials before retrying. No unchanged-credential retry occurred.

- DELIVERY-1 resolved on 2026-10-20T17:40:56.437076+00:00: replacement authentication was securely stored in macOS Keychain and the reviewed main push succeeded. The previous failure is retained above as history.
