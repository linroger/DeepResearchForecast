# Feedback owner handoff

**Last Updated (UTC):** 2026-10-27
**Status:** In Progress
**Current Focus:** Implement the bounded G1/G3/G8 feedback and input-status contracts.

## Request and boundaries
The approved part2 extension requires conservative typed input health, evidence-backed named-source/manual resolution, a separately scored exact-contract near-market lane, an offline-tested configured-client probe CLI, and fake-clock monitor cadence checks. The existing publication journal remains the only feedback authority. No provider calls, scheduler activation, service restarts, commits or pushes are authorized. Other owners' changes must remain intact.

Owned paths are forecast_feedback.py, resolution_autorun.py, new forecast_inputs_health.py, the existing backend/scripts/resolution_monitor.py (the supplied scripts/resolution_monitor.py shorthand has no root-level file), backend/scripts/probe_markets.py, uniquely named tests, and this record. API/config/report wiring belongs to the coordinator and report owner.

2026-10-27 delta: the coordinator explicitly authorized updates to existing resolution-monitor/forecast-feedback workflow and SDK journal tests for changed semantics. Only test_forecast_feedback_workflow.py required an edit: near candidates no longer append to the legacy exact-market ledger; the terminal fixture now includes the provider's closed flag and reaches the source-settlement identity gate. Exact-market and official-data valid controls remain intact.

## Requirements and acceptance checks
| Requirement | Scenario check | Expected evidence |
|---|---|---|
| Explicit input health | Missing, offline, stale and dated fresh fixtures | Typed consumer output never invents publication dates or availability |
| Evidence-backed manual outcomes | Register publication, resolve valid and invalid evidence, read score | Immutable contract identity and forward time checked in the existing journal |
| Near-market lane | Matching and mismatched contracts with rollback on/off | Exact identity required; near results separate from exact-market scores |
| Monitor cadence | Fake clock and duplicate-flight scenarios | 24h configuration semantics without activating runtime |
| Configured-client probe | Script entrypoint with substituted transport | Actual configured client path, no live request |

## Plan and progress
1. Read frozen case interfaces and existing journal/monitor contracts. In progress.
2. Implement narrow additive helpers and journal validation while preserving legacy behavior.
3. Exercise actual record/resolve/score consumers with adversarial fixtures under the guarded runner.
4. Review owned changes and report exact API/config contracts to coordinator.

## Findings and decisions
The worktree has concurrent owned edits. No shared handoff or config files will be changed by this worker. Missing data and prospective outcomes remain unknown; offline checks cannot establish first40 scores or live connectivity.

## Issues and recoveries
Initial source discovery found the monitor at backend/scripts/resolution_monitor.py. No source mutation was made before reading the contracts.

Independent review found four material issues in the first implementation. A forecast self-hash was wrongly treated as settlement equivalence; near settlement now additionally requires source terms frozen at publication and reobserved verbatim through the configured Gamma client, plus byte-identical forecast statement/criteria and exactly equal deadlines. New admission validation was being applied to old journal records; it now runs only on first publication append, with raw pre-extension v1 wire fixtures proving read/retry/append compatibility. Official series cache provenance (`route=cache`) was missed; it now produces stale status. Unregistered near candidates could be displayed as resolved without a commit; they now remain candidates and stay in the manual queue.

Gate02 had 203 passes and two failures. The first exposed the intentional removal of near native-ledger writes (expectation updated with authorization); the second was an existing SDK subprocess fixture missing its guard allowlist entry. The unchanged runner's `--allow-python-script backend/tests/test_forecast_feedback_sdk.py` restores the guarded child test without weakening isolation. Gate03 had 216 passes and one old rejection-reason assertion; the fixture now supplies actual closed-state evidence and expects the missing source-term proof failure. All raw receipts are preserved.

## Verification
First guarded gate: 145 passed in 4.26s across the two new suites, existing forecast-feedback ledger and resolution monitor suites. Evidence is `/private/tmp/drf-target-feedback-20261027-01/completed.json` and junit.xml. The completed receipt reports exit 0, no blocked events, no contained library probes, no source drift, identity preservation and three successful guarded child processes. This establishes offline durable record/score behavior, not provider reachability or forecast accuracy. Two follow-up guards (future client resolution timestamp and malformed health count) were added after this receipt and require the next run.

## Remaining work
Final verification and independent review remain. Coordinator owns API route/config integration; Turing owns report/brief consumer integration. Next-session prompt: read this file and contracts.md, inspect owned diffs, run the scoped guarded acceptance cases, and preserve the explicit no-runtime-activation boundary.

## Integration interface
`forecast_feedback.resolve_published_binary(report_id, forecast_id, *, outcome, evidence, contract_sha256, resolved_at, d=None)` returns the detached durable journal outcome. `outcome` is a strict boolean. `evidence` requires text, url, publisher, published_at, retrieved_at and adjudicator. The service stamps adjudication=manual; source publication dates and source text remain supplied evidence, never inferred. Resolution must follow publication, the declared deadline, source publication and retrieval, and cannot be in the future. Manual review documents an adjudication, not an independently fetched/verified source assertion.

`binary_resolution_contract_sha256(binary)` hashes the frozen statement/criteria, identity and typed contract. Named events use `resolution_contract={kind: named_source_event, publisher, event, deadline}`. Unanchored legacy manual questions need explicit resolution_date (or a typed manual contract deadline). Missing dates cannot be recovered from model/prose guesses. Market and official-data anchors cannot be bypassed through manual resolution.

`ForecastFeedbackError.code` is stable. Suggested API mapping: unpublished_report/unknown_forecast=404; publication_conflict/outcome_conflict=409; other evidence/hash/time validation=422. Runtime rollback does not invalidate historical journal replay. `build_inputs_health(*, markets=None, news=None, official_data=None, provider=None, as_of=None, max_age_hours=168)` is pure and returns four typed status entries with status/as_of/rows/reason. Input as_of is snapshot/retrieval time and never replaces source publication dates.

Required config: FORECAST_MARKET_NEAR_RESOLUTION=true (false disables new near admissions); RESOLUTION_MONITOR_AUTORUN_HOURS=24 desired source default, with the deployment's existing .env=0 continuing to override it. No scheduler was activated. PREDICTION_MARKETS_API_BASE and PREDICTION_MARKETS_CLOB_BASE remain the production client's endpoint overrides; probe_markets.py reuses that client, browser user-agent and timeout/retry path. Last-good cache production is outside this bounded consumer ownership; cached receipts are handled as stale. Global forecast_ledger.calibration_summary migration is likewise outside the assigned write set; authoritative monitor paths use the journal tracks.

Near-market contract detail: the frozen market anchor must include source `question`, `description`, `endDate`, `market_id` and `market_contract_sha256`, calculated by `market_resolution_contract_sha256`. Those exact terms must also appear in the newly fetched Gamma row; the monitor obtains raw terms through the real client's `_fetch_fresh_markets` and parses the same row's outcome. Forecast statement/criteria must match question/description byte for byte, and explicit resolution_date must equal endDate. Publication must precede the deadline and settlement must follow it. Existing approximate near matches without that proof stay unresolved, regardless of the rollback flag. The source field requirement is intentionally conservative and is not a claim that legacy market producers already capture complete settlement text.

The new manual and near outcomes live only in published_forecasts.jsonl. Near scores are rendered in a separate monitor section and never enter exact-market aggregate scores. News status consumes existing providers/queries evidence and treats news-envelope as_of as a search cutoff, not a retrieval timestamp. A partial failed market requote and native official cache route remain stale. Missing source publication dates are never supplied by this helper.

## Updates
- 2026-10-27: Created scoped continuity record before implementation.
- 2026-10-27: Implemented journal/manual/near lanes, pure health helper, configured probe and injected-clock cadence. First 145-case gate passed. Coordinator accepted the SDK and helper interface. Read-only reviewer Pauli deployed for immutable-history, provenance and false-freshness risks.
- 2026-10-27: Applied all four independent review fixes, added source-identity/legacy-wire/cache/unregistered regressions, and sent the tightened near contract to the coordinator. Broader gate04 running with the existing guarded SDK child explicitly registered. Coordinator reports the SDK endpoint, source monitor default24 and production calibration-summary journal wiring integrated; no service or scheduler activation occurred.
