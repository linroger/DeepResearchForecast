# V3 official data integration

Status: Complete for the owned V3 slice, with guarded offline acceptance and independent review closure. This is the owned continuity record for the approved plan. Main working bytes and integration-contract.md are authoritative.

## Scope and acceptance

Only research_gateway.py, linear_research.py and backend/tests/test_v3_official_data.py are implementation-owned. Shared data_sources.py and legacy chart helpers are supplied by their owners. No provider/model calls, saved-run inspection, installs, restarts or Git mutations are permitted.

Acceptance follows a deterministic question through optional data planning, bounded fetch, durable page and ledger registration, KIQ evidence, digest, citation remapping and dossier exhibits. Disabled inputs must preserve existing prompt/tool behavior. Replays consume stored evidence; sealed QA artifacts must not gain new data. Tests must exercise the actual shared API before final acceptance.

## Progress and decisions

- Read approved plan, integration contract and prior design. Existing unrelated dirt and root handoff are preserved.
- Implement guarded tool admission and persistence before adding engine phases, then verify consumer scenarios with the main offline runner once available.
- The earlier design's blanket deterministic VERIFIED facts are superseded by the integration contract: only observation-derived quantitative statements can enter the existing verification machinery; projections retain their labels.

## Evidence and remaining work

Initial behavior red: three stdlib-only tests failed before production edits (planner drops data needs, data_get header not counted as fetched, data dispatch never invokes the API). Command: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 backend/.venv/bin/python -B -m pytest --noconftest -p no:cacheprovider -q backend/tests/test_v3_official_data.py`. Those three cases subsequently passed. This initial run did not import the app and predates the guarded runner.

Guarded red: `/private/tmp/drf-main-v3-red-20261012-01/completed.json` and `junit.xml` record one failing cancellation-admission regression and three passing tests. The failure reached `engine.cancel()` and showed that inflight data admission remained open. Receipt: exit 1, identity preserved, zero blocked attempts; only app config/logger path redirects. Production cancellation now freezes data admission. Full shared-module acceptance and independent review are pending while data_sources.py is being supplied by its owner.

Guarded compatibility pass attempt: `/private/tmp/drf-main-v3-regression-20261012-01` ran the original gateway and core V3 suites plus the first four new tests: 539 passed, four existing subprocess performance tests failed under the guard. Receipt records six blocked subprocess attempts and eighteen blocked file-descriptor-path operations, with identity preserved. These are blocked attempts, not successful provider work and not a zero-attempt result. The four performance checks remain unverified under the original all-subprocess-denied runner; no guard was weakened.

Guarded core green: `/private/tmp/drf-main-v3-green-core-20261012-01` contains five passing tests (four original regressions plus KIQ deadline/reserve propagation), with fourteen shared-module cases intentionally not selected until the real module exists. Completed receipt and JUnit were inspected; no blocked events, identity preserved.

Independent read-only review identified eight issues. Changes close invalid-dataset access through web fetch and citation reuse, preserve KIQ deadline/reserve, validate single-digit dataset claims, retain origin query selectors, omit stale excerpt markers, count official evidence in grounding, resolve catalog imports in both module modes, and refresh failure telemetry before degradation analysis. Focused shared-module regressions cover those boundaries. Re-review is in progress.

Dependency-stage attempt `/private/tmp/drf-main-v3-actual-api-20261012-01`: fourteen tests passed against the real shared model/render/persistence core. Two tests and six fixture setups could not run because the owner had published only the core, without DataSources/get_data_sources. This is a dependency limitation, not behavioral red evidence. No blocked attempts appeared in that receipt.

Frozen-runner core acceptance `/private/tmp/drf-main-v3-core-20261012-02`: fourteen passed, eight client-dependent cases not selected. Runner SHA-256 was verified as `53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa` before launching.

Compatibility rerun `/private/tmp/drf-main-v3-compat-20261012-02`: 535 passed, four subprocess performance cases explicitly not selected, one existing teardown error. That fixture calls `os.environ.clear()`, so the runner blocked an identity-environment mutation. Receipt also records two subprocess attempts from library activity. The source was not modified to bypass this protection. This is not a clean broad-suite pass.

Current runtime decisions: the plan-phase batch now reserves each series before calling the real `DataSources.get_many`; agents use budgeted `get` calls. Durable V3 manifests retain ledger IDs; published root manifests retain only the current run generation, carry positional IDs and KIQ routing, and are bound along with dataset JSON/CSV and embedded PNGs in QA proof. Replays reject changed sealed artifacts, never repair them after sealing. A fresh changed identity retires only explicitly V3-owned old manifests/chart rows and retains the original data/image files.

Current integrated test attempt `/private/tmp/drf-main-v3-green-20261012-02`: 23 passed and one client-adapter case returned DATA_UNAVAILABLE. Source inspection established that the newly present DataSources.get dispatches to `_fetch_fred`, but provider adapter methods had not yet been published; this remains dependency-stage evidence. All engine/data persistence/QA/resume cases and the actual legacy chart-helper/render subprocess case passed. Parent receipt: identity and shutdown preserved, one allowed guarded child, no blocked parent operations. Renderer child `process-65630.json`: exit zero, identity/shutdown preserved; two blocked subprocess probes (fc-list and system_profiler) and eighteen blocked font-directory reads, classified as contained library probes. These are explicitly nonzero attempted operations, with zero permitted network/provider activity. The generated PNG was visually inspected: correct percent units, a missing-data gap without interpolation, distinct observed and publisher-projection points, and source/retrieval annotation.

## Final acceptance

Independent reviewer approved closure on the exact gateway and linear-research hashes below, verified the JUnit/completion/source-hash receipts, and reported no remaining actionable findings. This closes the owned slice; it does not assert completion of the other integration owners' work.

- Independent review regressions: `/private/tmp/drf-main-v3-review-red-20261012-01` has four behavioral failures: source-export page corruption, sign reversal, lost successful batch siblings at deadline, and chart-lock retirement recovery. All four now pass. Their fixes revalidate pages before source publication, preserve numeric signs, reserve provider-batch completion time, and make manifest retirement recoverable under the chart lock.
- Full owned tests: `/private/tmp/drf-main-v3-green-20261012-03` has 28/28 passing, using actual DataSources/FRED adapter code with synthetic native MCP results and real persistence/chart helpers. Later shared source changes made this an intermediate receipt.
- Final combined acceptance: `/private/tmp/drf-main-v3-acceptance-20261012-01` has **749 passed, five explicitly deselected, zero failures** in 9.72 seconds. `completed.json`, `junit.xml`, child `process-71659.json`, event logs and `v3-source-hashes.json` were inspected. Before/after hashes match for all seven recorded producer/consumer/test/renderer files; runner receipt also reports no source drift. Parent and child both preserve identity variables and finish shutdown.
- Guard activity is not zero: parent blocked two subprocess attempts, named `uname` and `unregistered-executable` in its receipt. The allowed renderer child blocked fc-list and system_profiler plus eighteen font-directory reads. All were denied; no network/credential/saved-run operation was recorded. The renderer completed successfully using available fonts.
- The five exclusions are the four existing gateway regex-performance tests that launch Python `-c` and `test_main_dispatches_research_engine_v3_end_to_end`, whose old teardown calls `os.environ.clear()`. Their earlier denied attempts remain recorded above. No unowned test or guard was changed to bypass those restrictions. The owned end-to-end test calls the actual V3 engine with a scripted model and tests durable replay independently.
- Broad compatibility exposed three direct-call test doubles without `agent_tools`. `_ask` now uses the web-only constant as its compatibility fallback; real initialized agents retain the same per-run schema on regular, wider-retry and forced-final turns. All three regressions pass in the final combined run.

Tested SHA-256 values:

| Source | SHA-256 |
|---|---|
| `deerflow_bridge/research_gateway.py` | `4a93b8f0ae2faab42863c37c7e34fcc11c46bbf5d01f6dfbfe50c019c90f8ddf` |
| `deerflow_bridge/linear_research.py` | `3f6791573d3fb580a5881024f7cd054c407be4b15f7ca47ecee3a58a4012a284` |
| `backend/tests/test_v3_official_data.py` | `dabd9cdf13478c736c733a8918097f82f0518ad79145d3d59a0f22a458228137` |
| Actual shared `deerflow_bridge/data_sources.py` | `417ca9130ecbbd1ae118fd9fe27992e1ea151d9d02bfabbaa08e18eeaef6c8e5` |

After review closure, the shared API owner published newer bytes. Focused acceptance was refreshed in `/private/tmp/drf-main-v3-current-api-20261012-01`: **28/28 passed** in 2.90 seconds against shared API SHA-256 `20c9babf0dc83925ae9ecc22fefa4bb8fb891f0ce0a94beae8547ca9b673114b`. All owned hashes remain those above. Its source-hash receipt records unchanged before/after bytes for all seven files; a final read matched the current shared API hash. Parent receipt has zero blocked attempts and one successful allowed renderer child. Child `process-72709.json` records the same two denied metadata/font subprocess probes and eighteen denied font-directory reads. Identity/shutdown are preserved in both receipts. This is the latest producer/consumer acceptance, supplementing the larger compatibility gate.

## Contracts, limitations and continuation

Changed paths are exactly the three owned implementation/test paths above and this report. No other source, global skill, legacy helper, dependency, saved run, service, or Git state was changed by this worker. Provider transport/adapter breadth, report/forecast integration and publication across other slices remain their owners' responsibility. This evidence uses synthetic observations and a scripted model; it makes no live-provider availability, paid-model quality, full six-provider transport or deployment claim.

The first successful series/transform window remains immutable for the run; subsequent calls show its stored coverage. Data search is metadata only. All flagged values remain explicitly flagged; publisher projections/estimates are not promoted to VERIFIED historical observations. Corrupt durable data or changed sealed artifacts fail replay instead of triggering a fresh provider fetch or post-seal repair. Renderer failure falls back to a genuine stored-value table without broken image links.

Next coordinator prompt: Reuse the exact source hashes and receipts above when assembling the all-slice gate. If shared producers or helpers change, rerun `backend/tests/test_v3_official_data.py` through the frozen main runner with the exact data-renderer script allowed. Keep the five pre-existing guard-incompatible cases separate unless their owner replaces their forbidden operations with equivalent bounded controls. No provider runs, saved-run resumes, installs, service restarts or commits were authorized for this slice.
