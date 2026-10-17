# M0 public simulation engine admission regression

**Started (UTC):** 2026-10-16T14:32:34Z.
**Last updated (UTC):** 2026-10-16T14:35:19Z.
**Status:** Complete for the assigned M0 regression; application behavior remains failing.

This sidecar owns only `backend/tests/test_world_engine_admission.py` and this
record. The supplied checkout is
`/Users/rogerlin/.codex/worktrees/reflexive-world-simulation/DeepResearchForecast`,
branch `codex/reflexive-world-simulation`, supplied revision `4b64c27`. No Git
operation is used to verify that revision. The approved [plan](PLANS.md),
[contracts](contracts.md) sections 3 and 8, and
[acceptance matrix](acceptance-scenarios.md) RW-10/RW-15 supply the compatibility
requirements. The user's current instruction narrows the task to M0 red evidence.

## Scenario and acceptance

Use Flask's real registered `POST /api/simulation/start` route with the existing
`SimulationState` in `READY`, with no world engine metadata. Fake only service
lookup, persistence, and runner launch, following the blueprint/client pattern in
`test_official_data_consumers.py` and state/service monkeypatches in
`test_simulation_config_seal.py`. The real handler, state classes, and response
serialization remain in use. No simulation process is started.

| Check | Expected outcome | Evidence |
|---|---|---|
| A legacy request omits engine selection. | HTTP 200, one fake legacy dispatch, and a saved RUNNING state. | Passing control and runner JUnit. |
| The same prepared legacy state is requested as `world-v1`. | HTTP 409 with an explicit mismatch identifying `world-v1` and `oasis-legacy`; no dispatch or state persistence; state stays READY. | Failing regression, response and captured dispatch in assertion, runner receipts. |
| Execution stays within the existing offline guard. | No provider/network/child execution, saved-run access, installs or guard changes; explain every blocked operation. | Guard event stream and completion receipt. |

The current handler reads platform, rounds, graph-memory and force options but
does not inspect `simulation_engine`; it dispatches to `SimulationRunner` and
saves RUNNING. The regression must reach that behavior, not fail on a future
module, fixture error, or missing import. It will remain an ordinary failing
assertion, without `xfail`.

## Execution plan and constraints

Create the two focused tests, run them with the original checkout's existing
Python using `-I -S -B` and `backend/scripts/main_offline_pytest.py`, then inspect
JUnit, exit status, source hashes and guard receipts. Use a fresh evidence root
under `/private/tmp`, the canonical target of `/tmp` on this Mac. Do not modify
application code, the runner, other agents' files, or the shared handoff.

## Progress and next step

- 2026-10-16T14:32:34Z: Read the approved documents, current public handler,
  `SimulationState`/`SimulationRunState`, shared conftest, nearby route/service
  fixtures, and runner source. Recorded baseline source hashes before testing.
- Next: create the regression and legacy control, capture guarded execution,
  and record the exact reproducible command and failure evidence here.

## Guard setup failure and bounded recovery

The first invocation used the requested worktree directly:

```sh
cd /Users/rogerlin/.codex/worktrees/reflexive-world-simulation/DeepResearchForecast
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B \
  backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-m0-engine-admission-worktree-20261016T143234Z \
  -q backend/tests/test_world_engine_admission.py \
  > /private/tmp/drf-m0-engine-admission-worktree-20261016T143234Z.console.log 2>&1
```

It exited 1 before pytest collection at runner line 476, while reading its own
source for hashing: `GuardViolation: main offline guard blocked credential_path`.
`protected_reason()` treats any `.codex` path component as a credential path,
including this worktree. The completed receipt records 16
`blocked:credential_path` events (including exception-source rendering attempts),
no registered children, no source hashes, and preserved identity. This is a setup
failure, not the required behavioral red. Raw evidence is
`/private/tmp/drf-m0-engine-admission-worktree-20261016T143234Z/`, with console output
at the sibling `.console.log` path above.

Recovery keeps the guard unchanged: copy only ordinary Python application source,
the existing runner, shared conftest, and the owned test into a new source snapshot
under canonical `/private/tmp`. Reject symlinks; do not copy Git metadata,
credentials, saved runs, caches, environments, or other `.codex` contents. Bind all
copied bytes to the worktree with SHA-256 before and after the run. Execute that
snapshot using the specified original-checkout interpreter and a separate fresh
evidence directory. The snapshot is disposable verification evidence, not another
implementation checkout or a change to application code.

- 2026-10-16T14:34:10Z: The first source snapshot (79 Python files) reached the
  intended route behavior: one legacy control passed and the mismatch regression
  failed with `assert 200 == 409`, a captured legacy launch, and saved RUNNING.
  Evidence: `/private/tmp/drf-m0-engine-admission-red-20261016T143234Z/` and its
  sibling `.console.log`. The guard recorded only its three storage redirects,
  with no blocked events, children, or source drift. The snapshot omitted
  `backend/pyproject.toml`, producing one `PytestUnknownMarkWarning` for the
  existing `guarded_runner` marker. Preserve that attempt and include the
  unchanged existing configuration in a fresh final snapshot and evidence run.

## Final exact command and result

The final source snapshot contains 80 unchanged files, selected as above plus the
existing `backend/pyproject.toml`. Its
[source manifest](/private/tmp/drf-m0-engine-admission-source-final-20261016T143234Z/source-manifest.json)
records every relative path and SHA-256. All 80 files matched both the original
worktree and snapshot after the run. No application module was imported while
copying or hashing; application imports occurred only inside the guarded pytest
process. The existing runner's three standard storage redirects were retained.

Exact command executed (the evidence directory did not exist beforehand):

```sh
cd /private/tmp/drf-m0-engine-admission-source-final-20261016T143234Z
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B \
  backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-m0-engine-admission-red-final-20261016T143234Z \
  -q backend/tests/test_world_engine_admission.py \
  > /private/tmp/drf-m0-engine-admission-red-final-20261016T143234Z.console.log 2>&1
```

For another run, keep this frozen snapshot and choose a different, nonexistent
evidence directory under `/private/tmp`; the runner deliberately rejects reuse.

The command exited **1**, with **1 failed, 1 passed in 1.63s**, no warnings,
collection/setup errors, skips or expected failures. The failure is at
`backend/tests/test_world_engine_admission.py:104`:

```text
AssertionError: world-v1 requested for legacy preparation must return HTTP 409 engine mismatch before launch; got HTTP 200, success=True, legacy_launches=[{'simulation_id': 'sim_m0_legacy_prepared', 'platform': 'parallel', 'max_rounds': None, 'enable_graph_memory_update': False, 'graph_id': None}], saved_statuses=['running']
assert 200 == 409
```

The legacy control proves the same fixture and public route can dispatch an
ordinary legacy request successfully. The regression requests only a different
engine and demonstrates that the real handler silently dispatches the legacy
runner and persists RUNNING. The fake records that dispatch and returns the
existing `SimulationRunState`; it never starts OASIS, a provider, or a child
application. The later regression assertions require an explicit error naming
both engines, zero launches, zero state saves, and unchanged READY state once the
application admission check is implemented. They do not prescribe an unapproved
future error-code schema.

## Evidence and source identity

- [Full pytest output](/private/tmp/drf-m0-engine-admission-red-final-20261016T143234Z.console.log).
- [JUnit result](/private/tmp/drf-m0-engine-admission-red-final-20261016T143234Z/junit.xml).
- [Completed guard receipt](/private/tmp/drf-m0-engine-admission-red-final-20261016T143234Z/completed.json).
- [Append-only guard events](/private/tmp/drf-m0-engine-admission-red-final-20261016T143234Z/events-85789.jsonl).
- [Post-run source and result verification](/private/tmp/drf-m0-engine-admission-red-final-20261016T143234Z/verification-summary.json).

The final receipt has `shutdown_complete=true`, `identity_preserved=true`,
`source_drift=[]`, `allowed_scripts={}` and `children={}`. Its only events are one
each of `redirect:app.config`, `redirect:app.utils.logger` and
`redirect:app.services.simulation_manager`. There are zero recorded blocked
operations and zero recorded network or child-process attempts in this final
run. The initial direct-worktree guard failure remains separate evidence above;
it is not relabeled as zero attempts. This is the runner's CPython audit boundary,
not an OS sandbox or proof of live engine execution.

| Bound file | SHA-256 |
|---|---|
| `backend/tests/test_world_engine_admission.py` | `eb770ea64b3535fc3abc330d8cc53de4125b4cfd7443b4701c8735981050dfb7` |
| `backend/app/api/simulation.py` | `dc68ad1f6802bf28afb5c6858aa28a1c1c676f4289df0c9c1322b9452e03f212` |
| `backend/app/services/simulation_manager.py` | `f0ba8c46f915dc204e5975133eeb51d8a07525829d8ceec5c36e765d0f4f0f59` |
| `backend/app/services/simulation_runner.py` | `8d97257a95252a9aca269386a9796d9decf97923c7cbb12ac15979b4179dea37` |
| `backend/tests/conftest.py` | `a1ac08fe607544807d64042b308673179c1b4f402bc2993cf58e9c98004d8f59` |
| `backend/scripts/main_offline_pytest.py` | `53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa` |

Self-review confirmed the test imports only existing modules, uses the registered
Flask route, and replaces only the relevant service methods. A stdlib AST parse
and trailing-whitespace check passed. No guard/source change, installation,
provider call, saved-run operation, Git operation or subagent was used. The only
project writes were the two assigned files; temporary source/evidence files are
under `/private/tmp`.

## Handoff and remaining application work

The assigned regression/evidence task is complete. The application defect remains
open: admission must reject an explicit `world-v1` request against a legacy
prepared simulation before dispatch or state persistence. That implementation
belongs to the application owner, outside this sidecar's scope. This evidence
does not claim M1/M3 completion, runner internals, or live-provider acceptance.

```text
Use backend/tests/test_world_engine_admission.py as the M0 red baseline. Preserve
the missing-engine legacy control. Implement engine mismatch admission in the
authorized application slice, returning explicit HTTP 409 before process work or
state mutation. Re-run both tests under the unchanged main offline guard using a
fresh evidence root. Bind current source hashes; the snapshots linked here prove
only the recorded source version. Keep other workers' changes intact.
```

- 2026-10-16T14:35:19Z: Final run reached the intended assertion with one passing
  control and one behavioral failure, no warnings or blocked guard events.
  Rehashed all 80 source files against the frozen snapshot with no drift;
  verified JUnit counts, failure text, shutdown/identity receipts and no children.
  Marked this assigned M0 sidecar complete, retaining the application defect as red.
