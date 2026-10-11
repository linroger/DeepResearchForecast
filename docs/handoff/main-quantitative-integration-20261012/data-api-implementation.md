# Data API implementation handoff

Status: Replacement hub READY received and coordinated reruns complete: 173/173 guarded cases and 13/13 native cases passed against hub `0b65ca3e…`; all 23 original transport cases are accounted for. API remains frozen at `419663…`. The earlier `010c1c…`/170-case run remains historical only. API/consumer acceptance records below remain preserved. Ownership is limited to `deerflow_bridge/data_sources.py`, `backend/tests/test_data_sources.py`, dedicated fixtures in `backend/tests/fixtures/data_sources/`, and this report; the coordinator additionally authorized the status/fiscal contract append. The approved integration contract and prior design are authoritative. Main working bytes are the baseline; unrelated changes remain untouched.

## Acceptance and plan

Implement the six-provider common API using the existing MCP hub and catalog, normalize finite observations and publisher metadata, preserve gaps and projection labels, provide bounded keyless FRED fallback, and persist hash-bound datasets for offline consumers. Shared anchor validation/resolution must use exact periods and canonical units/transforms and must never resolve projections or ambiguous metadata.

1. Read actual vendor handlers and incoming provider studies; capture their response contracts in dedicated synthetic fixtures.
2. Write focused public-contract tests before runtime implementation. Exercise provider arguments, errors, paging/batching, provenance, transformations, persistence corruption, and anchor resolution.
3. Implement only owned files, capture behavioral red/green evidence with the main offline runner, review current bytes, and record limitations.

No provider calls, paid models, saved-run access, service restarts, dependency installations, commits, hub/catalog/renderer edits, or other-owner mutations are authorized. Tests that import application conftest require the prepared main offline guard. Missing-module collection failures will not count as behavioral red evidence.

## Initial findings

Vendor handlers differ materially: IMF takes a nested `params` object and returns flat rows; Data360 pages at 100 and strips observation status; Treasury returns a columnar table and uses `filter` rather than catalog `filters`; SEC drops observation start dates; USAspending can convert missing values to zero. These losses need explicit provenance and conservative resolution behavior.

## Progress and evidence

- 2026-10-12: Read root handoff, contract, prior design, hub/catalog interfaces, and selected vendor handlers. Confirmed branch `main` and existing unrelated dirt. Implementation and tests pending.
- 2026-10-12: Published core model, formatting, persistence, anchors, client and native adapters. All three provider studies were consulted. Captured two behavioral anchor failures (approved `observation` field absent, annual/quarter syntax accepted for monthly series) in `/private/tmp/drf-main-data-api-red-20261012-01`; fixed them and captured 20 passing core cases in `/private/tmp/drf-main-data-api-core-green-20261012-01`.
- 2026-10-12: Initial full suite passed 37 cases in `/private/tmp/drf-main-data-api-full-20261012-01`. All three completed receipts have only app config/logger redirection events, no blocked operations, empty source-drift lists and preserved identity. These are offline synthetic response proofs, not live-provider acceptance. An independent reviewer is checking the core while provider-specific edge cases are expanded.
- 2026-10-12: Native-source regressions captured four failures in `/private/tmp/drf-main-data-api-provider-red-20261012-01` (Data360 enriched search shape, IMF citation URL, missing native source receipts, and contrary metadata frequency). Corrected all four; 43 passed in `/private/tmp/drf-main-data-api-provider-green-20261012-01`.
- 2026-10-12: Integrity regressions captured two failures plus two valid controls in `/private/tmp/drf-main-data-api-integrity-red-20261012-01` (list-shaped manifest and injected chart/slug paths). Corrected them; 58 passed in `/private/tmp/drf-main-data-api-integrity-green-20261012-01`; cache-copy and import-mode checks subsequently brought the suite to 60 passing cases.
- 2026-10-12: Independent static review identified failed-write generation invalidation, SDMX units/period precision, Treasury page completeness, and parent-path replacement risks. Cache aliasing and duplicate BLS dispatch findings applied to an older snapshot and had already been corrected. Added regressions: seven behavioral failures and two passing controls in `/private/tmp/drf-main-data-api-review-red-20261012-01`. Persistence now stages immutable content generations before atomic manifest publication; SDMX validates native period precision and reconciles recognized units/scale; Treasury reconciles page totals and rejects repeated/incomplete pages. File reads and writes now use pinned directory descriptors and no-follow opens with directory identity checks.
- 2026-10-12: All demonstrated review regressions passed in the 69-case `/private/tmp/drf-main-data-api-review-fixes-green-20261012-01` run. Added parent-directory swap tests for read and replacement and a valid PCT control. That control exposed a missing `Per cent per year` alias from the actual BIS catalog; `/private/tmp/drf-main-data-api-final-20261012-01` recorded 71 passing and one failing case. Corrected normalization while preserving annual-rate metadata. Final `/private/tmp/drf-main-data-api-final-20261012-02` passed all 72 cases in 1.10 seconds.
- 2026-10-12: Completed live-discovery dispatch coverage against synthetic actual-handler shapes for BIS `search_dataflows` and Treasury `treasury_search_datasets`. Both map only to exact curated keys/recipes, never arbitrary inferred coordinates. Final acceptance moved to `/private/tmp/drf-main-data-api-final-20261012-03`: 74 passed in 1.20 seconds, with unchanged clean guard receipt properties.
- 2026-10-12: Targeted rereview identified a matching unit label masking a contradictory recognized code and a transient ancestor symlink that could preserve the checked inode. Both were reproduced as behavioral failures in `/private/tmp/drf-main-data-api-rereview-red-20261012-01`. Native code and label are now checked independently. Darwin directory acquisition uses kernel `O_NOFOLLOW_ANY`; other POSIX hosts use component-by-component descriptor traversal. An intermediate mistake combined Darwin's mutually exclusive `O_NOFOLLOW` and `O_NOFOLLOW_ANY`, causing EINVAL in the isolated run `/private/tmp/drf-main-data-api-final-20261012-04` (25 failures, 51 passes). Corrected the flag combination without weakening symlink protection; `/private/tmp/drf-main-data-api-final-20261012-05` passed all 76 tests in 1.24 seconds. The non-Darwin fallback was statically reviewed, not runtime exercised on this Mac.

## Public consumer details

`series_stats` exposes `latest`, `previous_year`, `yoy_change`, `yoy_change_pct`, `five_year_min`, `five_year_max`, `cagr_10y`, `count`, `first`, `last`, `projection_count`. Points/extrema are `{date,value}` or null. `validate_data_anchor` accepts and preserves `observation`, supports `period` as a compatibility alias, adds normalized `period`, canonical units/transform and historical `latest_value`/`latest_date`, and rejects mismatched period syntax. Only a resolved result contains boolean `outcome`.

The six provider routes are implemented through the actual hub contracts. SEC's concept recipe returns an explicit unavailable `DataError` because its native handler drops the period duration/filing provenance needed for a trustworthy annual series. USAspending keeps fiscal starts and unknown flags, with automatic resolution disabled because the vendor coerces missing amounts to zero. WEO/GEP without per-point status remain unknown; no projection cutoff is inferred from retrieval time. BIS/IMF truncation returns an explicit error, requesting a narrower window. These are deliberate source limitations rather than stubbed adapters.

To preserve the last committed dataset during any failed update, new JSON/CSV paths are `data/<identity-slug>.<content-sha256-prefix>.json|csv`; the stable `slug` and `charts/data_<slug>.png` identities are unchanged. Consumers must use manifest `file`/`csv` fields, as the inspected renderer/tool consumers already do. The reader accepts prior hash-bound `data/<slug>.json|csv` artifacts for compatibility. Old immutable generations are retained; automatic garbage collection is outside this slice.

## Final acceptance evidence and limits

Command, from the repository root:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-main-data-api-final-20261012-05 -q backend/tests/test_data_sources.py
```

The final `completed.json`, `junit.xml`, and `events-81741.jsonl` record exit 0, 76 passes, empty source drift, complete shutdown, preserved HOME/home/CODEX_HOME/USERPROFILE identity, no child processes, and only two application storage redirections. There were zero blocked network, process, external-file or credential operations in this run. The guard is a trusted CPython audit boundary, not an OS sandbox. Synthetic provider payloads establish the adapters exercised here; they do not establish live availability, current values, server builds, or whole-application acceptance.

The runner automatically hashes the test and its explicitly intercepted app imports. The owned runtime and fixtures were additionally hashed after the run; exact final bytes are:

| File | SHA256 |
|---|---|
| `deerflow_bridge/data_sources.py` | `511e152c647a17c71f4972170a52082c8cb5b850d3a3786532ce342fc65aed4e` |
| `backend/tests/test_data_sources.py` | `95798955788d537cfa3fb3730eb3693f7516076b8bb21193ad889fff2d898c66` |
| `backend/tests/fixtures/data_sources/provider_responses.json` | `137db12893d0b1e8ded7b24537d32e14efbbaf78f057b497deb350b9b83787d4` |
| `backend/tests/fixtures/data_sources/README.md` | `a38f3688af31ab0e4c3ffbbda918d3b7ba7f9fe99a9b892d20be524ec072ce20` |

Unrecognized SDMX unit codes or scale contradictions are explicit unavailable results until a source-backed mapping is available. Annual WDI metadata remains unsuitable for automatic resolution when per-point status has been stripped. Keyless FRED has a fixed HTTPS origin, no ambient proxy or redirects, a 15-second socket/body budget, a 2 MiB body cap and 5,000-row cap; its CSV transport is covered with injected bytes, not a live request. BLS quota reservations are durable, bounded to 20/day without a key, and protected by a process lock. `get_many` returns at its deadline and checks the deadline before later cache writes; the MCP hub owns cancellation of already running remote calls.

No services were started/restarted, saved runs inspected, dependencies installed, providers called, commits created, or other-owner files edited. The implementation leaves prior dataset generations intact; lifecycle garbage collection is a separate decision. The coordinator owns shared contract clarification for manifest-authoritative content-addressed artifact paths and wider consumer integration acceptance.

## Remaining work

The independent reviewer closed the original P1 and all targeted P2 findings on runtime hash `511e152c647a17c71f4972170a52082c8cb5b850d3a3786532ce342fc65aed4e` and test hash `95798955788d537cfa3fb3730eb3693f7516076b8bb21193ad889fff2d898c66`. This was static source review; the 76-test run and receipt inspection were performed by the implementation owner, not independently rerun by the reviewer. No unresolved finding remains within that review scope.

No required work remains in the owned slice. The coordinator owns combined V3, legacy, report and downstream acceptance and shared-contract clarification of content-addressed filenames. Every public API has a concrete implementation; source-limited results fail explicitly rather than supplying placeholders.

Next-session prompt: Read this report and the integration contract; verify the recorded runtime/test hashes, then run the coordinator-owned combined consumer gates under a fresh main offline evidence directory. Preserve all concurrent changes, consume manifest `file`/`csv` paths, and retain the explicit source limitations. No provider calls, saved-run access, service restart, installation, or commits are authorized by this handoff.

## Coordinator follow-up: historical availability and completed periods

2026-10-12: The coordinator reproduced resolution using a January observation retrieved in March at a February cutoff, and resolution with unknown retrieval metadata. The helper also rejected timestamp cutoffs and did not require the whole monthly/quarterly/annual period to have ended. Added focused regressions before changing runtime. Preserve the positive case with a real retrieval timestamp. Treat date-only timestamps as inclusive UTC days and ISO timestamps as exact instants; unzoned ISO timestamps mean UTC. A retrieval before period completion cannot certify the full-period value merely because a later cutoff has passed. No current adapter provides verified historical-vintage availability proof, so arbitrary vintage/last_updated/available_at text must not bypass the canonical retrieval check.

Focused red: `/private/tmp/drf-main-data-api-availability-red-20261012-01`, 11 behavioral failures and 3 passing controls, 76 prior cases deselected. The former positive anchor fixture now supplies its actual retrieval timestamp rather than silently relying on an empty timestamp.

Green: `/private/tmp/drf-main-data-api-availability-green-20261012-01`, all 90 cases passed in 1.16 seconds. Both receipts have empty source drift, identity preserved, complete shutdown, no child processes, and only config/logger storage redirections; there are no blocked operations. Tests use only synthetic observations and the existing offline runner.

Frozen follow-up hashes:

| File | SHA256 |
|---|---|
| `deerflow_bridge/data_sources.py` | `8424ded36596d4e1a9a301d3d1b7b2d1f3eaf33e23d9af6ae48dc9920e4fe655` |
| `backend/tests/test_data_sources.py` | `7597085a6b16ddb02ebb69591ba15b8485159b32563c86b552566a602fdc56f5` |

Cutoff behavior: unknown or later retrieval yields `manual`; an unfinished observation period yields `pending`; neither includes `outcome`. A valid completed historical observation retains the existing resolved result shape and boolean outcome. Date-only retrieval evidence spans the UTC day, so it cannot establish availability at an earlier intraday cutoff. Calendar monthly/quarterly/annual intervals close at the end of their final UTC day; exact ISO timestamps preserve this boundary. The coordinator owns any future authenticated vintage-proof contract and consumer adjustments; this change adds no speculative proof field or provider calls.

Final frozen acceptance: `/private/tmp/drf-main-data-api-availability-frozen-20261012-01`, 90 passed in 1.18 seconds. The runner was given both the test path and bridge source path so its existing pre-import hash capture includes both exact frozen files in `completed.json`; source drift remains empty. This closes the reviewer's receipt-binding limitation without changing the runner or runtime. JUnit reports no failures, errors or skips; completion records zero blocked operations, preserved identity and complete shutdown.

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-main-data-api-availability-frozen-20261012-01 -q backend/tests/test_data_sources.py deerflow_bridge/data_sources.py
```

The narrow independent review covers only the resolver follow-up and the source hashes shown above. Provider-source expert reviews remain coordinator-owned; no provider implementation changes were made during this follow-up. Only the bridge module, its test file, and this report changed. These bytes are frozen for integration.

## Provider review follow-up — current work

2026-10-12: Read all three early provider reviews against current bytes. The already-accepted resolver availability/period fixes close BIS/IMF F1–F2 and WB/USgov R2 within this owner scope. Published the requested public `resolution_instant` wrapper immediately. The coordinator authorized an append to the integration contract for canonical status flags and keyed fiscal intervals; notified renderer owner McClintock and the coordinator. The research-renderer status loss and report fiscal captions remain outside this owner's write scope.

Captured behavioral red at `/private/tmp/drf-main-data-api-provider-review-red-20261012-01`: 33 failures, 4 controls passing, 90 previous cases deselected. Source/test hashes were bound before import, no source drift or blocked operations. Covered FRED page completeness/placeholders/end-only windows/weekly YoY/auth classification, BLS preliminary status and omitted chunks, WB metadata/units/paging/status, old-policy admission, fiscal identity/display, Treasury FX geography and deadline preflight/startup.

Implemented fixes retain explicit unknown status for every WB/USAspending observation through `Series.from_dict`, cache/artifact admission and resolution. SEC Series construction/admission is unavailable, including old carriers. BLS preliminary observations remain preliminary and keep raw footnotes by date. Historical-only shared statistics exclude uncertain statuses; publisher values remain visible in explicitly labeled observation tables. `normalization_policy_version=2` separates cache generations; old cache entries cannot bypass policy. Fiscal metadata follows the frozen `provenance.periods[date]` contract, including partial coverage, FY labels and transform refusal for incomplete aggregates. Daily partial-month aggregation now retains intersecting buckets and explicit partial metadata. Weekly YoY is explicitly unavailable pending an agreed alignment policy.

First broad check after fixes: `/private/tmp/drf-main-data-api-provider-review-green-20261012-01` had 125 passing cases and two outdated fixture expectations: the former raw BLS P flag and a WB fixture lacking the native identity/periodicity/page envelope now required. Updated these positive fixtures to the actual handler contract; production guards were retained.

Shared dependency: API deadlines now move disk preflight into workers, check remaining time after cache work, and prewarm cold hubs within the same caller budget before dispatch. A restart race wholly inside the hub can still spend its separate startup budget; the coordinator was notified that strict atomic no-dispatch-after-expiry requires the hub owner's absolute deadline propagation. No hub, renderer, report, or backend snapshot code was edited here.

2026-10-12: The hub owner and API owner agreed `McpHub.call(..., timeout=None, deadline=None)`, with deadline an absolute monotonic timestamp. API bounded workers now pass the original deadline plus remaining timeout; direct requests omit the optional deadline. The hub owner implements atomic startup/restart/semaphore/dispatch enforcement in separate owned files. The API's scripted cold-start and exact-deadline propagation controls pass; actual hub acceptance is recorded by that owner.

The 127-case green at `/private/tmp/drf-main-data-api-provider-review-green-20261012-02` was expanded with positive completeness/scale/admission controls to 136 passing cases at `/private/tmp/drf-main-data-api-provider-review-controls-20261012-01`. The user-requested scoped lint check found five E731/C408/B023 findings; replaced the lambda helper and dictionary constructors and bound loop captures without changing assertions. `ruff check --target-version py311 deerflow_bridge/data_sources.py backend/tests/test_data_sources.py` now passes.

Narrow source rereviews found one remaining FRED rejected-auth spelling and four admission/metadata/display gaps. Preserved new reds: `/private/tmp/drf-main-data-api-auth-review-red-20261012-01` (1 failed, 2 controls passing), and `/private/tmp/drf-main-data-api-admission-review-red-20261012-01` (5 failed: latest/vintage WEO variants plus three WB cases). Fixed the vendor-documented `api_key is not registered` response while retaining operational-error vetoes; WEO missing status now becomes unknown on every Series admission; every nonmissing WB row establishes its own unit scale; page units must agree with separate metadata; dataset projection statements require classified projections rather than an unauthenticated cutoff.

Current frozen-candidate gate: `/private/tmp/drf-main-data-api-provider-final-20261012-01`, **144 passed in 1.60 seconds**, no failures/errors/skips. `completed.json` captures the exact module/test bytes, no source drift, identity preserved, completed shutdown, and only config/logger redirections; zero blocked operations. Fixture content is synthetic. Public interfaces remain stable except for the explicitly requested new `resolution_instant` wrapper and the coordinator-approved additive status/fiscal provenance fields.

| Current file | SHA256 |
|---|---|
| `deerflow_bridge/data_sources.py` | `419663c3bbd0d1a790212ed229023b6f5b171e9e74adecff16adc4b04f001511` |
| `backend/tests/test_data_sources.py` | `102bd5ccb17799da0b1691ced4b78155ca74ab97a7676855477c2542179baa61` |
| `backend/tests/fixtures/data_sources/provider_responses.json` | `e6791e7db1e26f922a0b8559687fed13ad18840d0b37574ebbbaf59cb78f1725` |

Provider-review disposition in this owner scope:

| Review | Disposition / evidence |
|---|---|
| FRED/BLS R1–R7 | Implemented, regression-covered, and narrow rereview closed. Weekly YoY explicitly unavailable until a source-backed alignment policy is agreed. |
| BIS/IMF F1–F2 | Closed by earlier 90-case resolver gate and independent review; retained in current suite. |
| BIS/IMF F3 | Producer and carrier admission now preserve unknown WEO status; shared statistics exclude it. Research/report rendering belongs to the renderer owner. |
| BIS/IMF F4 | API return deadline includes cache work; exact absolute deadline passed to the hub. Hub's atomic enforcement belongs to Cicero. |
| WB/USgov R1–R3 | Current fidelity applies through Series.from_dict, cache policy v2, manifest reload, and resolution; stale SEC authority is refused. Snapshot/rendering consumers are separately owned. |
| WB/USgov R4 | Keyed fiscal identity, coverage, labels and completeness survive filtering/trim/persistence; partial/full growth is refused. Report fiscal caption scope was signaled to the coordinator. |
| WB/USgov R5–R7 | Row/page/metadata unit reconciliation, explicit terminal/paging checks and Treasury reference geography/curated provenance implemented; final targeted rereview closed. |

Final review closure: Popper closed FRED/BLS R1–R7 and the daily partial-window note; Lovelace closed the three follow-up WB gaps; Pasteur closed legacy WEO admission. Each reviewed/rehashed the applicable current bytes or explicitly carried forward unchanged owned paths, with final runtime hash `419663c3bbd0d1a790212ed229023b6f5b171e9e74adecff16adc4b04f001511` and test hash `102bd5ccb17799da0b1691ced4b78155ca74ab97a7676855477c2542179baa61`. Reviews were read-only static/receipt inspections, not separate executions of the test suite. No outstanding finding remains in their bounded API review scopes.

Freeze command:

```sh
ruff check --target-version py311 deerflow_bridge/data_sources.py backend/tests/test_data_sources.py
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-main-data-api-provider-final-20261012-01 -q backend/tests/test_data_sources.py deerflow_bridge/data_sources.py
```

Exactly five paths changed during this provider-review follow-up: the core module, its test file, `backend/tests/fixtures/data_sources/provider_responses.json`, the coordinator-authorized status/fiscal append to `integration-contract.md`, and this report. `resolution_instant(value, date_end=True)` is public and ready for the backend adapter. The renderer owner received the exact canonical status/fiscal contract and the final API hash; the coordinator was notified of snapshot fields and report-fiscal scope gaps.

Cross-owner limitation at freeze: the current API sends `deadline=` only in bounded workers, as agreed with Cicero. The full owned suite proves that keyword/budget with injected hubs; it does not claim the old hub implementation already accepts/enforces it. Cicero owns landing and validating the optional keyword in `data_mcp.py` and its dedicated tests. The coordinator/E2E owner must include that new hub revision before accepting actual bounded transport. No further API edits are planned unless a new concrete integration defect is reproduced.

## Consumer acceptance received after API freeze

2026-10-12: Renderer owner reported completed research/report status and fiscal consumption. Inspected `renderer-status-fix.md`, `/private/tmp/drf-renderer-status-final-v1/completed.json`, source-freeze receipt and JUnit. The run passed 120 tests with zero source drift, completed shutdown and preserved identity; the API remained hash `419663c3bbd0d1a790212ed229023b6f5b171e9e74adecff16adc4b04f001511`. Consumer coverage includes WB/USAspending unknown values on both sides of legacy cutoffs, BLS preliminary markers, ambiguous other P flags, missing-status WEO/vintage carriers, keyed FY labels/partial coverage and rejection of missing fiscal metadata. Its bounded independent static review is closed.

The consumer receipt contains two blocked font-discovery subprocess attempts and eighteen blocked font-directory reads, plus four explicitly allowed guarded renderer children. These were contained library probes, not zero attempts; no network, credential or saved-data attempt is recorded. One child exit three is the expected missing-Matplotlib compatibility case. This is separate consumer evidence from the API's 144-case gate. No API or test code was changed while recording this update. Later shared hub/contract revisions still require the coordinator-owned combined gate.

## Combined API and frozen hub gate

2026-10-12: Received the hub owner's verified freeze at SHA256 `010c1c0841a9173bf4d418050453fad4d5033f56a02994cb9de93f5222925765`, with the optional absolute `deadline` contract. Verified that hash, frozen API `419663…`, original transport tests `9f41f730…`, new deadline tests `78112376…`, exact fake fixture `f4116f77…`, and runner `53a2cd41…` before execution and again afterward. No source files were edited for this gate.

Executed the ten original selectors authorized under the main guard (section A of `transport-verification.md`), the full new `backend/tests/test_data_mcp_deadline.py` file, and the full owned `test_data_sources.py` file together. Registered only `backend/tests/fixtures/fake_mcp_server.py`; also supplied both bridge source paths to the runner for pre-import hash capture. Fresh evidence: `/private/tmp/drf-data-api-transport-final-20261012-01`.

**170 passed in 10.08 seconds:** 10 original transport cases, 16 deadline cases, and 144 API cases. JUnit has zero failures/errors/skips. The completed parent receipt binds the exact frozen hub/API/test hashes, records `source_drift=[]`, identity preserved and complete shutdown. The remaining thirteen original tests belong to the native sidecar partition and were not run or claimed by this main-guard gate.

Guard/process details remain explicit: five registered fake-server children were reaped with exits `-15, 7, 0, 0, 1`; ten `os.killpg` cleanup attempts were blocked. No network, credential, saved-data or other blocked operations are recorded. The shared server terminated by SIGTERM has a started-only child receipt; the parent records it reaped. The deliberately failing startup child exited 7. The real in-flight-cancellation child exited 1 with `anyio.ClosedResourceError` while responding on a closed SDK write stream during teardown, after its sibling-survival/reusability assertions passed. This is not an all-child-exit-zero claim. The exact log is `pytest-tmp/test_real_inflight_deadline_ca0/logs/fake.stderr.log` beneath the evidence directory; this diagnostic was sent to the hub owner without modifying their code or tests.

The earlier API-to-old-hub keyword dependency is now exercised against the announced frozen hub. Its later independent review status and the thirteen native lifecycle cases remain with their owners. API runtime/test hashes remain unchanged.

## Hub unfreeze and final-gate hold

2026-10-12: The coordinator withdrew hub `010c1c…` from final acceptance after independent rereview found three actionable paths: an expired-send inner branch cancels its scope but still enters send; startup rejection/restoration can overwrite valid adoption; and generic public exception failure accounting omits the absolute deadline. The hub owner will add focused regressions, repair only their hub/new-test/report paths, and announce a replacement freeze hash. The existing 170-case green is retained as historical scenario evidence, not closure of those findings.

No new final combined or native gates will launch until that replacement READY. API `419663…`, its tests, existing transport tests and the frozen runner remain untouched. This update changes only the owned continuity report.

## Replacement freeze acceptance — current transport evidence

2026-10-12: The coordinator announced replacement READY, then confirmed James's independent review closed all three residuals with no actionable findings on the exact frozen bytes. Verified hub `0b65ca3e0ef012261faf994b00107c9b0b517a121fc8e583be05bfb6c58934a9` and new deadline tests `6fc84115bc210d8efd1dcce0b77b65cb364cf2bc1c44bd4fcbf291c6755c0066`; API `419663…`, original transport tests `9f41f730…`, API tests `102bd5cc…`, runner `53a2cd41…` and exact fake fixture `f4116f77…` remain unchanged before/after execution.

Guarded gate: `/private/tmp/drf-data-api-transport-replacement-final-20261012-01`, **173 passed in 11.23 seconds**, zero failures/errors/skips. The selection is the same ten original guarded selectors documented in `transport-verification.md` section A, the full new deadline file (19 cases), and the full API file (144 cases). Only the exact fake MCP server script was registered; both bridge source paths were explicit runner arguments for pre-import hashing. The completed receipt has no source drift, preserved identity and completed parent shutdown.

Guarded process accounting: seven registered children were reaped with exits `-15, 7, 0, 0, 1, 0, 0`. Fourteen `os.killpg` cleanup attempts were denied. No network, credential, saved-data or other blocked operation is recorded. The signal-terminated shared server has a started-only child receipt, with reaping established by the parent. Exit 7 is the intentional startup-error case. The in-flight-cancellation child (48577) again exited 1 with `anyio.ClosedResourceError` on SDK shutdown after its behavior assertions passed; all six nonsignal child receipts completed. These details were sent to Cicero and are not relabeled as all-zero child exits or native process-proof.

Native gate: reused the existing, unedited sidecar SHA `ede36f1ce30726635bbc03bd6b02fc0293fc2b65d2e01b7d8b20c9b7d926de4e`:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/verify_deployment_fixtures.py --suite transport --evidence-dir /private/tmp/drf-data-api-native-replacement-final-20261012-01
```

**13/13 original native-sidecar cases passed**, 13.766 seconds overall, with nine of nine boundary controls passing. The parent/worker identities were preserved; source drift was empty; worker child cleanup completed; worker and outside sentinel were reaped; the PS broker stopped. Controls include scratch read/write, denied outside read/write, denied INET bind, denied unapproved execution, denied outside-sentinel signal/status, anonymous AF_UNIX communication and allowed owned-PID status/signals. This is macOS sandbox-exec evidence, separate from the CPython guard. The read-only parent PS broker remains the documented trusted-fixture exception outside that sandbox.

Independently checked every scratch-copy hash against the manifest/current originals, the exact hub hash, all thirteen original assertion-body and nine helper AST hashes, and the exact disjoint partition of guarded ten plus native thirteen into all 23 original tests. The native journal records 20 child spawns, 48 attempts and two expected spawn failures; the PS broker records 28 fixed native status queries. The native receipt reports cleanup, not a fabricated per-child all-zero exit list. Sidecar, source, tests, runner and API code were not edited. Only this owned report changed. Boyle and Cicero received the fresh evidence paths and process details.
