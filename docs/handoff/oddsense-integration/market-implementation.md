# OS-2 market adapter implementation

Date: 2026-10-18. Status: preparation under the approved frozen integration contract; release remains gated on OS-1 acceptance. This worker owns only `deerflow_bridge/market_intelligence.py`, `backend/tests/test_market_intelligence.py` and this document. The coordinator owns the main handoff and plan.

The objective is a bounded context-only comparison through `ContextClient.record_result`, using the existing Polymarket normalizer and documented Kalshi discovery/detail fields. No external row may enter canonical markets, anchors, refresh or resolution. Unknown values remain null. Community forecasts remain distinct and unsupported access remains explicit.

Acceptance checks will cover native-shaped current Kalshi fixtures, literal Yes mapping through existing Polymarket code, fixed-point units, bounded paging/detail/response/time budgets, sanitized failures, durable replay and historical-cutoff behavior. Fixture checks will use the original provisioned Python and unchanged guarded runner in a frozen source mirror. Separate read-only unauthenticated probes have a total ceiling of six, five-second timeouts and one-megabyte response limits. No application imports occur outside the guard.

Plan: establish current primary documentation and bounded public compatibility; implement the adapter against the frozen shared API; exercise scenario and negative fixtures through the guard; independently review the owned files; record exact source hashes and remaining release gates. Existing shared handoff, unrelated dirty work, credentials and Git state remain outside worker mutation scope.

## Progress and decisions

- 2026-10-18: Read the approved PLANS.md, integration-contract.md and shared handoff, existing market_tools and guarded runner. The shared handoff's older approval-pending prose is superseded by its approved implementation shift and the frozen contract. No peer-owned document was edited.
- 2026-10-18: Current Kalshi primary documentation uses `https://external-api.kalshi.com/trade-api/v2/markets`, cursor pagination, `*_dollars`, `*_fp`, and singular `market` detail responses. Generic topic discovery must disclose bounded recall, since the documented list endpoint has no free-text query parameter.
- 2026-10-18: The current official Metaculus OpenAPI is available in its maintained repository; the interactive API page is not text-readable. Access/schema investigation is ongoing. No usable access is assumed from historical vendor code.

## Evidence and remaining work

Implementation, fixtures, independent review and probe receipts are pending. This document will distinguish observed live compatibility, source-only documentation and guarded fixture proof.

## Compatibility evidence (separate from fixtures)

The following four public unauthenticated GET probes ran on 2026-10-18, with direct HTTPS, redirects disabled, a five-second timeout and a 1,000,000-byte ceiling. No application module, credential, saved run, vendor code or paid service was used. Error bodies and exception messages were not emitted or retained. Two of the six authorized probes remain unused.

| Probe | UTC capture start | HTTP/result | Bytes | Elapsed |
|---|---|---|---|---|
| Kalshi `/trade-api/v2/markets?status=open&limit=5&mve_filter=exclude` | 12:37:19.770523 | 200; `markets` list + nonempty cursor, 5 rows | 9,860 | 0.887 s |
| Kalshi `/trade-api/v2/markets/{returned ticker}` | 12:37:20.657961 | 200; singular `market`, binary type | 2,037 | 0.779 s |
| Kalshi same bounded list with returned cursor | 12:37:21.437444 | 200; 5 rows + cursor | 10,848 | 0.762 s |
| Metaculus `/api/posts/?limit=1` | 12:37:22.199462 | 403; sanitized `http_error` only | body not read | 1.027 s |

Observed Kalshi fields include `yes_bid_dollars`, `yes_ask_dollars`, `no_bid_dollars`, `no_ask_dollars`, `last_price_dollars`, `volume_fp`, `volume_24h_fp`, `open_interest_fp`, `notional_value_dollars`, primary/secondary rules and market/event tickers. The detail response returned the four inspected price/count fields as strings. These probes establish public endpoint/schema compatibility at capture time. They do not exercise the complete adapter, research pipeline, availability for every topic or any market-equivalence claim.

Primary sources read on 2026-10-18: [Kalshi list](https://docs.kalshi.com/api-reference/market/get-markets), [Kalshi detail](https://docs.kalshi.com/api-reference/market/get-market), [public market-data quickstart](https://docs.kalshi.com/getting_started/quick_start_market_data), and [Metaculus official OpenAPI](https://github.com/Metaculus/metaculus/blob/main/docs/openapi.yml). The Kalshi list documents cursor filters and no free-text topic search; the adapter scans at most two pages and discloses incomplete recall. Metadata `updated_time` is not a trade timestamp, so `quote_at` stays null.

The current Metaculus OpenAPI documents `Authorization: Token ...` authentication, gateway field filtering by account/project, and null community aggregates outside eligible access. No configured authenticated access was inspected or established within this worker's authorized boundary. Therefore Metaculus returns `unsupported` with `authenticated_community_forecast_access_not_established`, no invented community probability/count/volume and zero adapter HTTP calls. The observed public 403 corroborates the documented unauthenticated restriction; it does not establish authenticated behavior.

## Fixture evidence and decisions

- Initial source mirror `/private/tmp/drf-oddsense-os2-initial-llpf0tqx`, evidence `/private/tmp/drf-os2-initial-20261018-1250`: 32 tests passed in 1.50 s. `completed.json` records exit 0, shutdown complete, identity preserved, no source drift and only the two expected config/logger redirects. No blocked network, credential, saved-data or external-write attempts were recorded. These bytes predate the current-day cutoff and actual shared-store tests; this is historical fixture evidence.
- A delegated source reviewer confirmed that `snapshot_for_queries(fetch=...)` does not call canonical capture, while the legacy tool wrapper does. The wrapper is not used. The review exposed helper coercion and nonbinary-label risks, so OS-2 retains bounded raw Polymarket metadata, validates literal binary Yes/No, omits CLOB token identity and restores unknown fields to null.
- The test child failed with a transport/DNS error before creating its file. It was stopped and its sole owned test path was taken over locally. No new agent was spawned after the user's resume constraint.
- Coordinator review reproduced that a nonempty `as_of` check rejected normal v3 runs. It was corrected to permit today's UTC date while refusing older date-only cutoffs and earlier explicit instants unless a capture can be replayed. A fresh client's empty snapshot now falls back to its bound cutoff/language, preventing an initial historical-acquisition bypass.
- Shared-store inspection confirmed full provider results in `queries`; replay uses that carrier before network admission, and persisted `network_requests` supports generation-level request accounting. Quote aliases agree with the frontend (`bid`, `ask`, `last`, `quote_units`) and the existing store (`rules`, `units`, `volume_units`, `price_basis`). The provider owner is extending retention of the exact native metadata fields; actual-store fixture evidence remains necessary.
- Network defaults use the frozen knobs only. The existing research budget admits each provider attempt and every physical HTTP request. No retry, redirect or credential header is used. The aggregate request cap is four and the HTTP timeout is at most five seconds; two catalog pages, two details and eight candidate rows are narrower code constants. Queued adapter work shares a ten-second aggregate deadline.

Remaining acceptance work: finish current-byte shared-client fixtures and regression run, inspect guard receipts and source hashes, and close provider metadata/API gaps with the owning worker. OS-1 acceptance and coordinator end-to-end/report/UI acceptance remain separate release gates. No Git mutation or service operation was performed by this worker.

- Current-byte first store attempt: mirror `/private/tmp/drf-oddsense-os2-current-wvin4ly4`, evidence `/private/tmp/drf-os2-current-20261018-1304`, 50 passed and two failed (including existing Polymarket regression suite). Both failures occurred during `ContextClient` construction because its directory walker opens `/`; the unchanged guard correctly denied that external read before adapter acquisition. This is setup/integration red evidence, not a behavioral market test pass or a live provider failure. Provider owner/coordinator were notified; no guard or peer file was changed by this worker.
- Remaining shared API limitation identified early: the frozen `snapshot`/`record_result` pair permits replay and persisted count recovery but does not expose a public atomic pre-I/O reservation or cross-process market transaction. OS-2 currently serializes threads locally. Acceptance must not infer cross-process crash/reservation protection from that mutex; this requires an OS-1-owned reservation/transaction contract before enabling concurrent acquisition across processes.

## OS-2 guarded acceptance result

The run in `/private/tmp/drf-oddsense-os2-final-ctn6ar6o` with evidence `/private/tmp/drf-os2-final-20261018-1312` passed **56 tests in 1.68 seconds**: 43 OS-2 cases and 13 existing Polymarket tool regression cases. Its completed receipt records exit 0, completed shutdown, preserved identity and no source drift. The only audit events were the expected `app.config` and `app.utils.logger` redirects. It recorded zero blocked network, credential-path, saved-data, external-read or external-write attempts.

The actual shared `ContextClient.market_compare` was exercised with scripted HTTP payloads, real store normalization, seal and load. Assertions prove primary/secondary rules, native IDs, original price strings, aliases, fixed-point contract units, quote basis, null quote time, thresholds and source references survive sealing; unsealed restart preserves the four-request aggregate cap; sealed replay and uncaptured queries perform no acquisition; no canonical market/candidate file is created. Normal v3 UTC-today cutoff is preserved in this scenario. The previous external-root setup failure was resolved by the provider owner while keeping the guard unchanged.

Exact owned tested sources:

| File | SHA-256 |
|---|---|
| `deerflow_bridge/market_intelligence.py` | `6fb7dbb8622460e9be39dbedeb37bd647f8fb2b04e48ffe1b311695d65e2733a` |
| `backend/tests/test_market_intelligence.py` | `0f53767b7f2f6bacb10595ae86dd6351ca2c8550ba83c2036ba85ed747fa2b64` |

The tested existing Polymarket helper hash was `eed4d54cf31202a07c4ad88091b6f5cdb57292c0001f4b6e9f12c827ea2bc061`. The tested shared-store hash was `3e178cd8c50cad3c8a3f7472d289de5a68a3c46ba3c4cc9bc4a04ab7dfcf29cc`; the provider owner subsequently changed language aliasing/rendering, so a final fresh-mirror compatibility check follows. The mirror manifest is the full frozen-source inventory; runner receipts alone do not automatically hash every dynamically loaded module.

## Delivery state

Status: **OS-2 source and scoped fixture verification ready for coordinator integration; release pending shared gates.** Only the three assigned files were created/edited by this worker. No commit, index, branch, service, deployment, saved-run or credential mutation was performed.

The final delivery check used `/private/tmp/drf-oddsense-os2-delivery-jx385z72` and `/private/tmp/drf-os2-delivery-20261018-1318`: **56 passed in 1.67 seconds**, exit 0, shutdown complete, identity preserved, no source drift and only the two expected config/logger redirect events. The tested OS-2 source and test hashes above still match the worktree. This mirror's tested `news_signals.py` hash is `a46203b383ec64edc884264995ff08d20951592fd3dcb5830fb0704b313c005e`. The provider owner continued editing that file after this freeze; coordinator acceptance must test its final integrated bytes. This worker does not overwrite or freeze a peer's source without coordination.

The source-reader's bounded review and local implementation self-review were completed. A full independent review of final integrated OS-1/OS-2/OS-3 bytes remains coordinator-owned. The positive fixture path is real client/store/seal/reload with substituted HTTP payloads, not a paid-model research run, live adapter run, final report/UI proof, external publication or production acceptance.

Next coordinator action: complete OS-1 acceptance, settle its atomic pre-I/O market reservation/transaction API if concurrent process/crash protection is required, and run the normal v3/legacy/report/UI end-to-end scenarios against frozen final source. The approved plan continues to gate OS-2 release on OS-1 acceptance; no such release is claimed here. The explicit Metaculus unsupported reason remains until documented authenticated access and applicable field availability are established in an authorized future compatibility task.

## PR-1 reopened — 2026-10-18

The independent provider review formally retained P1 PR-1: the adapter's process-local mutex and post-HTTP `record_result` cannot enforce cross-process reservation, interrupted-capture accounting, or admission before a full query-table rejection. Prior sequential green receipts remain valid for their scope and do not close PR-1. Release is explicitly blocked on this finding.

The adapter owner proposed `ContextClient.capture_market(provider, query, acquire, *, deadline=None)` to the provider/coordinator. The store owner must hold its existing bounded cross-process lock, admit the query before I/O, persist interrupted capture state, and supply a per-request `reserve_network()` callback that durably charges the shared four-request allowance before dispatch. No competing lock or artifact owner will be added here. Guarded tests now synchronize actual separate clients/processes before first dispatch, independently count physical fake-HTTPS calls under a permissive research budget, interrupt an admitted process, and fill the query table before attempting acquisition. Meaningful pre-fix red evidence follows before adapter wiring.

PR-1 behavioral red receipt: `/private/tmp/drf-oddsense-os2-pr1-red-qy533e42`, evidence `/private/tmp/drf-os2-pr1-red-20261018-1328`, three targeted tests failed in 2.74 seconds. Two processes synchronized after constructing separate clients and before physical dispatch. Identical-query and distinct-query cases each made **six** independently logged fake-HTTPS requests (expected three and four respectively). The interrupted-process control logged its first physical request, terminated that admitted child, and found no persisted capture at all. This proves admission-ordering defects in the old adapter; no live HTTP occurred. Five children were admitted by the unchanged guard, with one deliberately terminated to test interruption.

The full-table pre-fix control also failed meaningfully: `/private/tmp/drf-oddsense-os2-pr1-table-red-v4s8oemz`, evidence `/private/tmp/drf-os2-pr1-table-red-20261018-1334`, one failed test in 1.21 seconds. With all 32 query slots already occupied, the old adapter dispatched two independently counted fake transport requests before persistence returned `query_limit` (expected zero).

The coordinator formally amended the contract with `capture_market`. The adapter now consumes only that atomic public API for acquiring providers; it no longer derives spent allowance from a snapshot, uses a process-local mutex as proof, or calls the research network budget separately. `_Transport` requires a reservation callback and checks its canonical admission result before every HTTP dispatch. Missing atomic API fails closed without acquisition. Unsupported Metaculus/historical metadata remain no-I/O `record_result` paths. The unit-only client explicitly implements a local test adapter; all cross-process/crash/table proof uses the actual provider-owned client/store.

First atomic-API gate: mirror `/private/tmp/drf-oddsense-os2-pr1-green-h27u1lu0`, evidence `/private/tmp/drf-os2-pr1-green-20261018-1347`, 58 passed / 6 failed in 3.46 seconds. All four new required process/crash/full-table cases passed with the actual store and real generous research-budget ledger. Five failures were stale assumptions in the explicit unit-only test adapter (its `record_result` lacked case-insensitive replay, and no-I/O paths correctly stopped constructing transports); those tests were corrected locally. The remaining substantive failure proved a migration defect: an existing result with three `network_requests` was ignored by the store's new `request_count` migration, allowing two further requests. Provider owner was notified; acceptance remains pending that fix and a current-byte green gate.

## PR-1 adapter handoff and remaining store blocker

Latest frozen gate: `/private/tmp/drf-oddsense-os2-pr1-final-3qfsh39b`; evidence `/private/tmp/drf-os2-pr1-final-20261018-1400`; **65 passed, 1 failed in 4.62 seconds**. The sole remaining failure is `test_legacy_network_count_is_not_reset_during_atomic_api_migration`, owned behavior in `news_signals.py` (current `capture_market` migration near line 861). A stored three-request result under the earlier `network_requests` field permits two further requests because only `request_count` is summed. The store owner must conservatively reconcile both counters without double-counting, then rerun this gate. The adapter does not add a second migration/counter owner to hide this defect.

All explicitly required PR-1 controls now pass through actual separate processes and the actual ContextClient store: identical queries make three physical requests total; distinct queries make four total; both the envelope's reserved count and real generous research-budget SQLite counter match independent dispatch logs; an intentionally terminated admitted child leaves its spent reservation and interrupted result durable; replay does not refetch that provider capture; and a full 32-entry query table admits zero HTTP. The positive three-request capture plus one remaining request after restart also passes. No test clears normal UTC-today `as_of`. Full-table, sealed, historical, disabled and denied-budget paths do not issue new HTTP.

The unchanged guard completed shutdown, preserved identity and recorded no source drift. Audit events were only config/logger redirects and five admitted guarded children. Four children exited 0; one exited -15 because the fixture deliberately terminated it after its first physical dispatch. This intentional crash is not a provider timeout or an unexplained failed process. No blocked network, credential, saved-data, external-read or external-write events were recorded.

Current frozen hashes (all matched the worktree after the run):

| File | SHA-256 |
|---|---|
| `deerflow_bridge/market_intelligence.py` | `e5f5525f0c34d651417808c5fd16453df00e0061cb3e02cf6ca4f31c2c796cae` |
| `backend/tests/test_market_intelligence.py` | `4c97eb3e76958b54ec517baf85d6b7884cc9848a2153490dfc68ff502a709298` |
| tested peer `deerflow_bridge/news_signals.py` | `db8e964fdd78d96a0b265bb245fcf83b86395a5db8079e859a8475d2f4607225` |

PR-1 remains **open at release gate** until the store migration regression passes and independent final-byte review closes it. PR-2 presentation remains assigned to the research/provider owners. This worker changed only its original three paths, created no new agents, used no further live provider probes (the earlier total remains four), and made no Git or service changes. The earlier delivery claims apply only to their recorded pre-review scope; this section is the current authoritative worker status.

## Final OS-2 source freeze — migration regression resolved

The provider owner changed reconciliation to the maximum valid nonnegative `request_count` / `network_requests` per capture, reconciled against the persisted shared high-water mark. No adapter or test bytes changed for this final verification; no new scenarios were added.

Fresh mirror: `/private/tmp/drf-oddsense-os2-pr1-release-xv3yph8f`. Guarded evidence: `/private/tmp/drf-os2-pr1-release-20261018-1422` (`completed.json`, `junit.xml`, child receipts and append-only events). **66 passed in 3.35 seconds: 53 OS-2 cases and 13 existing Polymarket regressions.** This includes the formerly failing legacy-count migration control, identical/distinct real-process reservation controls, interrupted capture, full query table, ordinary UTC-today cutoff, real store seal/reload, provenance retention and canonical-market separation.

The unchanged runner records exit 0, completed shutdown, preserved identity, no source drift and only expected config/logger redirects plus five admitted guarded children. Four children exited 0; one was deliberately terminated (-15) by the interruption scenario. No blocked network, credential-path, saved-data, external-read or external-write attempt was recorded. All five checked production/test files still matched their mirrored bytes after the run.

| Frozen file | SHA-256 |
|---|---|
| `deerflow_bridge/market_intelligence.py` | `e5f5525f0c34d651417808c5fd16453df00e0061cb3e02cf6ca4f31c2c796cae` |
| `backend/tests/test_market_intelligence.py` | `4c97eb3e76958b54ec517baf85d6b7884cc9848a2153490dfc68ff502a709298` |
| tested peer `deerflow_bridge/news_signals.py` | `ffc7a2d720bf3943116d4a3ff0636ce77b1134b743b82c361a9af4e8f88e0d45` |
| existing `deerflow_bridge/market_tools.py` | `eed4d54cf31202a07c4ad88091b6f5cdb57292c0001f4b6e9f12c827ea2bc061` |
| existing `backend/tests/test_bridge_market_tools.py` | `79d6e2e16cb71b721012eacff17879b2e2d8c9640068bd5489e086d23e6cd869` |

Status: **OS-2 owned implementation/tests frozen and ready for final joint regression and independent re-review.** The previously open migration regression is resolved by fresh fixture evidence. Formal PR-1 closure and overall OS-1/OS-2/OS-3 release acceptance remain coordinator/reviewer-owned. PR-2 presentation is outside this worker's write scope. No further source/test edits, agents or live probes are planned absent a concrete finding. The separate live compatibility evidence remains the four dated probes above; this gate does not constitute live adapter, paid-model, deployed report/UI or production proof.

## Coordinator final integration disposition

The final accepted source and receipt matrix is authoritative in final-verification.md/json. Historical worker freezes and remaining-work statements above apply to their dates only. All approved OS-1/OS-2/OS-3 implementation and concrete independent review findings are now closed; subsequent coordinator report/language/UI deltas have their own recorded affected tests/review. The complete matrix has1397pass/2existing skips, the final affected92 and bilingual61 pass, and the final UI187/build/visual gate passes. Remaining external limits are explicit provider access, deployment/live-model evaluation and Git authentication—not missing approved code. No historical receipt hash was reassigned.
