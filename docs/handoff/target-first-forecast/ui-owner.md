# Target-first API and UI owner

Status: Complete for scoped implementation. Independent rereview closed all four original findings and found no blockers within that bounded review. Scope was authorized on 2026-10-27. This owner edits only graph.py, simulation.py, ResearchView.vue, TargetSimulationView.vue, uniquely named tests, and this note. Other owners' edits are preserved. No providers, deployment, application backend, commits or pushes were used. The first full frontend suite did start ephemeral loopback test listeners; this boundary mistake and corrected no-server gate are recorded below.

## Request and acceptance

Provide an explicit target-first-v1 selector without changing legacy defaults. Send forecast_authority and target_simulation paths/periods/seed to research/run. Saved pipeline options select the result renderer; target simulations show numerical distributions, trajectories and unresolved assumptions with zero forecast weight. Reports retain ordinary report IDs.

Read-only graph and simulation APIs must bind artifacts to a matching pipeline owner, validate identifiers and known paths, and reject case/hash mismatches. Target graph reads must never construct Graphiti; target simulations must not route into OASIS APIs.

| Requirement | Scenario evidence planned |
| --- | --- |
| Explicit opt-in and unchanged defaults | SFC harness captures legacy and target launch payloads and saved-run renderer selection. |
| Target diagnostics | SFC harness verifies distribution, path and assumption display, zero weight, loading failures and stale-request isolation. |
| Owner-bound reads | Guarded Flask tests exercise matching artifacts, mismatched owners/case hashes, malformed IDs, traversal and symlink rejection. |
| Provider isolation and compatibility | Guarded backend receipt plus related existing frontend tests. |

## Plan and progress

1. Done: read the frozen contract/request, existing API/UI flow and current core/coordinator source.
2. Done: implement owner-bound read-only target artifact routes and legacy misroute prevention.
3. Done: add mode selection and a lazily loaded target-only result component.
4. Done: run guarded backend tests, focused and full frontend suites and production build. Independent review found four issues; all were fixed with regressions and rereview closed all four. The reviewer confirmed all six frozen source/test hashes.

## Decisions and assumptions

The frozen case APIs are pure and loaded through the existing fixed-namespace bridge loader so a cold backend does not depend on the repository root being in sys.path. The graph projection wire and target-input/v1 wire were confirmed against the current core/coordinator source. The coordinator owns research admission, preflight and pipeline persistence; this owner consumes those contracts without editing them.

## Issues, verification and remaining work

GET `/api/simulation/<simulation_id>/target?pipeline_id=<pipeline_id>` is the dedicated read-only endpoint. It returns pipelineId, simulationId, forecastAuthority, caseId, caseHash, resolution, nodes, mechanisms and simulation. Inputs match the coordinator's `target-input/v1` wire exactly, including pinned settings, pipelineId, simulation projection and decisionBudget. Simulation result seed/path count/replay periods and seed/dense trajectory periods/terminal target are checked against those settings. The exact frozen target_case_binding (including authority, question hash and policy) is mandatory.

GET `/api/graph/data/target_graph_<pipeline_id>` and the existing `/node/<uuid>`, `/edge/<uuid>` and `/neighbors/<uuid>` variants serve the core projection locally. The reader checks fixed owner-local paths, same-read SHA-256 against handoff/manifest.json, case identity and exact recomputed projection. It never constructs Graphiti. Missing/unsealed artifacts return 404; malformed identifiers return 400; identity/hash/path conflicts return 409. Target graphs are read-only, and old simulation consumers reject target artifacts with 409 rather than constructing legacy managers. Ordinary graph IDs continue through the existing builder.

Coordinator integration resolved: per coordinator steering, the selector calls GET `/api/research/preflight?mode=...&simulation_engine=target-first-v1` through the existing adapter and requires the returned simulation_engine to match. POST still sends forecast_authority plus target_simulation without world_spec or legacy engine fields.

The first related frontend run exposed missing new-component stubs in the existing ResearchView harness. Resolved within ownership by lazily importing the target-only component with Vue defineAsyncComponent; existing legacy tests do not need an additional import stub. The dedicated target tests render the real component separately and verify the parent selection.

The independent reviewer identified cold-start import failure, missing frozen-case binding checks, missing result settings checks, and omitted parameter-level assumptions. These are fixed and each has a regression. Parameter bases now remain visible even when their parent mechanism is observed; optional decision-budget request/cache statistics and a bilingual exhausted-budget limitation are displayed.

Final guarded gate: 61 passed in 5.16 seconds, consisting of 59 target API checks and two existing graph research-boundary checks. Evidence is `/private/tmp/target-ui-api-20261027-e/{completed.json,junit.xml}`. The completed receipt has exit_code 0, shutdown_complete true, identity_preserved true, no source drift, no child processes and no blocked provider/network attempts; its only events are the three configured application storage redirects. This is a CPython audit boundary, not an OS sandbox. The final Ruff gate `ruff check --no-cache --select F,E9 backend/app/api/graph.py backend/app/api/simulation.py backend/tests/test_target_ui_api.py` passed.

Focused frontend gate: 70 passed. The initial full frontend gate passed 330 tests at `/private/tmp/target-first-ui-node-20261027/full-tests.log`, but it included the existing devServer.test.mjs listener test. That test starts and closes temporary loopback Vite/stub-backend listeners, despite this task's no-server constraint. This was discovered by inspecting the unexpected primary `.vite-temp` directory mtime change. No browser opened, no actual Flask service was started, and no provider endpoint was contacted. The test's finally block closed both temporary servers and deleted its temporary dependency cache. The corrected gate passed 329 tests with the one listener case explicitly excluded by `--test-skip-pattern='^running dev server answers on localhost and 127.0.0.1 and on no other interface$'` and is recorded at `/private/tmp/target-first-ui-node-20261027/full-tests-no-server.log`. Node omits that excluded test from its count. The shared .vite-temp mtime did not change during this corrected run. Do not describe the initial 330-test result as a no-server run.

Production Vite build passed at `/private/tmp/target-first-ui-node-20261027/build.log`; output is in the adjacent `dist/`. Build warnings are the 508.53 kB main chunk and an existing mixed static/dynamic import of overlayTranslation.js. TargetSimulationView is its own lazy chunk (9.34 kB JS, 1.35 kB CSS). The build starts no server.

Dependency reuse is an ignored-only `frontend/node_modules` symlink to the primary checkout, as subsequently authorized. Vite uses `configLoader: native`, an explicit `/private/tmp/.../vite-cache` cache directory, and `/private/tmp/.../dist` output. No package installation or primary source changes were made. Full tests used `node --test tests/*.test.mjs`; the exact external build driver is `/private/tmp/target-first-ui-node-20261027/build.mjs`. Earlier focused tests used the existing sfcHarness with a temporary Node loader resolving missing dependencies from the primary checkout before the symlink was available.

Cache observation: the primary `.vite` directory mtime was unchanged, but the shared primary `.vite-temp` directory mtime changed and the directory is empty. The existing devServer.test.mjs test uses Vite's default bundled-config loader; it can write/remove its temporary config bundle in that shared directory. The production build uses native loading and bypasses that path. No cache was deleted or modified to conceal the observation. The no-server rerun excludes the responsible listener test; future full suites must account for side effects in existing tests before executing them.

Backend reproduction:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/NEW-target-ui-evidence -q backend/tests/test_target_ui_api.py backend/tests/test_graph_research_boundary.py
```

## Frozen paths and hashes

The source/test snapshot is also saved at `/private/tmp/target-first-ui-node-20261027/frozen.sha256`. Coordinator integration may change unrelated files; no further edits to these owned files are planned unless rereview finds a concrete defect.

```text
517a103ef61d5ff5cfe813b8c2f8d4ef62e7d7ee9581047ab50740c69de3c183  backend/app/api/graph.py
31df1e5ed4569a9825a154884742ca83639fccbebec49fe66d961c7fe1b116c1  backend/app/api/simulation.py
183b88e2abe9b75f361434f925e67fb8394a19c13ebec4815cc3a1df30bb67ac  frontend/src/views/ResearchView.vue
619afb6a07353719bb5fe70b92a66c6c9a033cf267d894f26e71bb18ed90deca  frontend/src/components/research/TargetSimulationView.vue
df85a030813b68caf6b24ffece8a57e08ae6cd8c5a5f4d23a38f3c09337e8105  backend/tests/test_target_ui_api.py
9c1f751f15ae93831fbb2bf83a23814277fd419dd1c2e29a45be2455fd969654  frontend/tests/targetFirstUi.test.mjs
```

## Remaining work and next-session prompt

Coordinator owns final whole-system integration and delivery. Scoped implementation has no remaining feature work; independent rereview closed all four original findings and confirmed the additional decision-budget consistency fix. Optional result maximumRequests must equal the sealed input max_calls; a same-case 64-versus-128 cap regression now returns 409. Offline checks do not establish live-provider realism, prospective forecast lift or deployed behavior.

Next-session prompt: Read this note and contracts.md; verify the frozen source hashes, then integrate the target read-only endpoint with the coordinator's sealed pipeline fixture. Keep the explicitly selected authority, unchanged defaults, zero simulation forecast weight, and fixed owner/path/hash rules. Reuse the current tests; do not start providers, servers, deployment, commits or pushes under this owner's authorization.

## Updates

- 2026-10-27: Created initial scope, acceptance scenarios, plan and ownership record after reading the root handoff and target contract/request.
- 2026-10-27: Added owner-bound graph/target routes, legacy misroute guards, forecast selector and diagnostics component. Confirmed core graph wire and coordinator input wire from source. Recorded preflight and existing-test-harness integration dependencies.
- 2026-10-27: Closed the harness compatibility issue with a lazy component; completed the 50-case guarded/69-case focused gates, then obtained independent review. Corrected all four review findings and incorporated the coordinator's decisionBudget input contract and exhaustion diagnostic. Final gates passed 60 backend, 70 focused frontend and 330 full frontend checks plus production build. Recorded exact frozen source hashes and isolated build/evidence paths.
- 2026-10-27: Inspected full-suite side effects and disclosed the ephemeral listener/cache-write boundary mistake. Repeated the frontend gate with exactly the listener test excluded: 329 passed and shared cache mtime unchanged. Independent reviewer closed the four original findings and confirmed the six frozen source/test hashes. No source files changed after the freeze.
- 2026-10-27: Reopened only simulation.py and its scoped test to reject result/input budget-cap mismatch; independent reviewer confirmed closure. Applied coordinator-requested harmless Ruff cleanup (unused RunnerStatus import alias, config_file local, local os import and unnecessary f-string prefixes), preserving module imports/side effects. Refreshed those two hashes, passed the 61-case guarded gate and Ruff F,E9 gate. The four other frozen source/test hashes and frontend build inputs remain unchanged.
