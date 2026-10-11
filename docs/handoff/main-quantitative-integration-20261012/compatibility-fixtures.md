# V3 compatibility fixtures

**Last updated (UTC):** 2026-10-11T18:10:12Z
**Status:** Complete for the five bounded compatibility fixtures.
**Current focus:** Deliver the reviewed fixture-only changes and full existing-suite acceptance to lead.

## 1. Request and ownership

Resolve only the five previously excluded existing V3 cases described in
`v3-implementation.md`. Owned paths are `backend/tests/test_research_gateway.py`,
`backend/tests/test_research_engine_v3.py`, the new
`backend/tests/fixtures/gateway_performance.py`, and this report. No production,
runner, module, provider, saved-run or other handoff edits are authorized. Preserve
all other workers' changes and remain on main without commits or staging.

## 2. Requirements and acceptance

| Requirement | Acceptance check | Evidence |
|---|---|---|
| Preserve four regex-performance scenarios | Each named case runs the exact original workloads against actual production gateway functions, with unchanged time assertions and subprocess timeout | Original guard red, focused green, exact helper comparison |
| Bounded child execution | Use one fixed fixture path and explicit `--case` choices through frozen runner's exact script registration | Parent/child receipts, script hashes, no unregistered test child |
| Preserve dispatch scenario | Actual mocked V3 dispatch and existing output/log assertions pass, with nonidentity environment changes restored | Focused/full-suite green and teardown receipt |
| Preserve identity and isolation | Never clear or modify HOME/home/CODEX_HOME/USERPROFILE during restoration; no live model/network/saved data | Identity/shutdown/source-drift and guard event inspection |
| Preserve ownership and quality | Only owned fixtures/tests/report change; independent review closes actionable findings | Scoped diff, source hashes and review verdict |

## 3. Plan

1. Read `v3-implementation.md`, identify exact tests and confirm frozen main runner.
2. Execute the five original cases unchanged to record current guard incompatibility.
3. Move the original timing helper into one bounded script with an explicit case CLI;
   retain subprocess timeout and parent test assertions. Replace environment clearing
   with restoration of changed nonidentity keys only.
4. Run the five cases, then relevant existing gateway/V3 suites under the same frozen
   runner with only the exact fixture script registered. Inspect parent/child evidence.
5. Obtain independent review and record exact source state, outcomes and limitations.

## 4. Progress ledger

- [x] Read current V3 continuity report and notify lead of the four exact owned paths.
- [x] Confirm the existing tests are initially unmodified and runner SHA-256 is
  `53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa`.
- [x] Capture original current guard incompatibility before fixture edits.
- [x] Adapt fixtures without production or guard edits; moved timing helper is source-identical to the archived original.
- [x] Obtain focused five-case and full 539-case existing-suite green evidence, with zero exclusions.
- [x] Complete independent review with no actionable findings; source/assertion/whitespace and parent/child event reconciliation checks pass.

## 5. Findings and decisions

Four gateway tests call `_r3_isolated`, whose `python -c` imports this test module
to invoke `_r3_timing_probe`. The runner intentionally refuses arbitrary inline
code. The original helper has exactly four cases: whitespace, tools, boilerplate
and quantity. It measures real production regex/tool calls with fixed input sizes
and scripted fetch/search responses. Move that helper verbatim into the registered
fixture rather than reimplementing the production behavior.

The fifth case is
`backend/tests/test_research_engine_v3.py::test_main_dispatches_research_engine_v3_end_to_end`.
Its sole `restore_environ` fixture user currently tears down with
`os.environ.clear()` and `os.environ.update(saved)`. Replace that bulk operation
with key-by-key restoration excluding the four identity names. Keep the actual
dispatch, scripted model/tools and all original assertions unchanged.

## 6. Issues and recoveries

The earlier V3 receipts report four subprocess denials and one teardown identity
mutation. These are compatibility evidence, not production behavioral defects.
This worker will reproduce the current incompatibilities before edits. No fixture
setup or pre-import error will be mislabeled a behavioral red.

Original current run `/private/tmp/drf-main-compat-fixtures-red-20261012-01`
selected exactly the five cases named below. Result: **4 failed, 1 test body
passed, 1 teardown error** in 1.40s; exit 1. The four failures reach the forbidden
`subprocess.run([sys.executable, "-c", ...])`; dispatch reaches real V3 completion
and passes all original assertions, then its bulk environment clear is denied.
This is guard-compatibility red, not a production behavior or dependency-setup
failure. [Completed receipt](/private/tmp/drf-main-compat-fixtures-red-20261012-01/completed.json),
[JUnit](/private/tmp/drf-main-compat-fixtures-red-20261012-01/junit.xml), and
[events](/private/tmp/drf-main-compat-fixtures-red-20261012-01/events-303.jsonl)
were inspected: four blocked subprocess attempts, one blocked identity mutation,
identity/shutdown true, source_drift empty, no children launched.

Archived the [original timing helper](/private/tmp/drf-main-compat-fixtures-red-20261012-01/original-gateway-timing-probe.py)
before edits. An AST-located source-segment comparison confirms the moved
`_r3_timing_probe` is text-identical. The new script adds only imports, production
gateway path binding, and argparse `--case` with four fixed choices. Parent
timeout, exception handling, return-code checking, JSON parsing and all timing
and dispatch assertions are unchanged. Environment teardown now removes newly
introduced nonidentity keys and restores only changed saved nonidentity values;
it never assigns/deletes any identity key.

## 7. Scenario-focused verification

Original cases:

- `test_r3_neutralize_is_linear_on_whitespace_runs`
- `test_r3_fetch_and_search_of_whitespace_padded_text_stay_fast`
- `test_r3_passage_and_reasoning_regexes_are_linear`
- `test_r3_quantity_detection_is_linear_on_long_digit_runs`
- `test_main_dispatches_research_engine_v3_end_to_end`

The first four retain real subprocess isolation because pathological regexes can
hold the GIL. Existing thresholds remain 0.05s / 0.1s as written; parent timeout
remains 60 seconds. No guard relaxation or in-process timing substitution is allowed.

## 8. Execution and evidence

Use the existing `backend/.venv/bin/python -I -S -B` and
`backend/scripts/main_offline_pytest.py`, with a fresh canonical `/private/tmp`
evidence root per run. Green explicitly registers only
`--allow-python-script backend/tests/fixtures/gateway_performance.py`.
Review completed receipts, append-only events, JUnit, every child receipt,
shutdown/identity preservation and source hashes. No dependency resolution,
installation, live provider/network, saved-upload access or other branch runner.

Focused green used the same five explicit node IDs as red, with evidence root
`/private/tmp/drf-main-compat-fixtures-green-focused-20261012-01` and
`--allow-python-script backend/tests/fixtures/gateway_performance.py`.
**5 passed in 1.92s; exit 0; no failures/errors/skips.** Parent
[completed receipt](/private/tmp/drf-main-compat-fixtures-green-focused-20261012-01/completed.json)
records four allowed children and zero blocked operations. All four child
receipts (`process-2881.json`, `process-2885.json`, `process-2889.json`,
`process-2890.json`) have exit 0, empty events, empty source drift and preserved
identity/shutdown. Parent also preserves identity/shutdown and has empty source
drift. Each child records the fixture hash
`ea81aeb522a76a9fbb8e87e7f0d37616858cf3e221774feb288453ab0a611881`.

The four parent assertions still check <0.05s for whitespace and <0.1s for
tools/boilerplate/quantity; the actual workload source and best-of-three repeat
counts are unchanged. Dispatch's output, metadata, log and usage assertions are
unchanged and now complete teardown without an identity-environment denial.

### Full existing-suite acceptance

Executed from `/Users/rogerlin/Downloads/DeepResearchForecast`:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-main-compat-fixtures-green-all-20261012-01 \
  --allow-python-script backend/tests/fixtures/gateway_performance.py \
  -q backend/tests/test_research_gateway.py backend/tests/test_research_engine_v3.py
```

**539 passed in 6.01s; exit 0; zero failures, errors, skips or deselections.**
JUnit counts 489 gateway cases and 50 V3 engine cases, including all five former
exclusions. Inspected [completion](/private/tmp/drf-main-compat-fixtures-green-all-20261012-01/completed.json),
[JUnit](/private/tmp/drf-main-compat-fixtures-green-all-20261012-01/junit.xml),
[parent events](/private/tmp/drf-main-compat-fixtures-green-all-20261012-01/events-4750.jsonl)
and all four child receipts (`process-4773.json` through `process-4776.json`).
Parent and every child have `identity_preserved=true`, `shutdown_complete=true`
and `source_drift=[]`. All four allowed children exited 0 with empty event maps.
No network/provider/saved-data/credential/identity/external-write denials occurred.
The parent separately records **two blocked subprocess discovery attempts**:
`uname` and `unregistered-executable`. They remain denied; this is not a
zero-attempt claim or authorization to run those commands.

The [before hashes](/private/tmp/drf-main-compat-fixtures-20261012-01.before.sha256)
and [after hashes](/private/tmp/drf-main-compat-fixtures-20261012-01.after.sha256)
match for all nine recorded test/fixture/runner/production/import files (`diff -u`
exit 0). Exact owned and production reference hashes:

| File | SHA-256 |
|---|---|
| test_research_gateway.py | a2e10cce43cb0297b969fde7dd988336f6c19cbc0f9b8a31087a1d1e19bb4424 |
| test_research_engine_v3.py | 129ae923d9ea53b5d956c8f27eadc881d972a0a0e44b14b346ed7de1acc85610 |
| fixtures/gateway_performance.py | ea81aeb522a76a9fbb8e87e7f0d37616858cf3e221774feb288453ab0a611881 |
| main_offline_pytest.py (unchanged) | 53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa |
| research_gateway.py (unchanged) | 4a93b8f0ae2faab42863c37c7e34fcc11c46bbf5d01f6dfbfe50c019c90f8ddf |
| linear_research.py (unchanged) | 3f6791573d3fb580a5881024f7cd054c407be4b15f7ca47ecee3a58a4012a284 |

A static AST comparison against the initially unmodified main HEAD verifies all
156 gateway test functions and all 38 engine test functions remain identical;
only helpers/fixtures changed. Parametrization accounts for the larger executed
case counts. The timing helper also remains source-text identical to the archived
original. This provides direct preservation evidence beyond a green aggregate.

### Independent review and final preservation

Reviewer Bernoulli (`01a12c25-9fc7-73e3-9d80-17ec5770c966`) approved the bounded
changes with **no actionable findings**. Independent static review confirmed
timeout/error handling, fixed production import resolution, four bounded CLI
choices, exact workload preservation, unchanged assertions and sound environment
restoration/teardown ordering. The reviewer explicitly relied on this worker's
execution receipts for the 539-case gate and did not claim to rerun tests or
independently inspect those receipts. No further code changes were requested.

This worker reconciled every raw per-process event map with its corresponding
receipt, including all four child processes; all matched. Scoped tracked
`git diff --check` passes, and the new fixture/report have no trailing whitespace.
Only the four owned paths were edited during this compatibility task. Production,
frozen runner, other tests/modules, providers, saved runs and other handoffs remain
untouched by this task. All unrelated working-tree changes are preserved. Main
remains active; no staging, commits, branch creation, dependency installation or
service operations occurred.

## 9. Remaining work and continuation

No compatibility-fixture work remains. The five formerly excluded cases now run
under the frozen guard, and both complete existing suites pass without exclusions.
The evidence is offline and source-bound; it does not establish live provider
availability or completion of other data-integration slices. The parent discovery
probe named only `unregistered-executable` remains unattributed beyond that denied
category. No fix requires weakening the guard or changing production.

Next coordinator prompt: "Read compatibility-fixtures.md. Include all five restored
cases in the combined gate and register only
`--allow-python-script backend/tests/fixtures/gateway_performance.py` for these
timing workloads. The complete two-suite receipt is
/private/tmp/drf-main-compat-fixtures-green-all-20261012-01. Preserve the frozen
runner and all other owners' changes; no fixture commit or branch was created."

## 10. Updates

- 2026-10-11T18:03:09Z: Created this owned continuity record before tests or edits; exact paths were identified and notified to lead.
- 2026-10-11T18:04 UTC: Reproduced four inline-subprocess denials and one teardown identity denial, archived the original helper, moved it verbatim into the bounded CLI, and changed only nonidentity restoration before green execution.
- 2026-10-11T18:06 UTC: Focused five-case green passed with four successful guarded children, no blocked operations and intact identity/shutdown/source hashes; requested independent read-only review before broad acceptance.
- 2026-10-11T18:08:36Z: Full 539-case existing-suite gate passed with no exclusions and matching nine-file before/after hashes. Recorded separate blocked discovery probes and static preservation of all original test functions/assertions; independent review is pending.
- 2026-10-11T18:10:12Z: Independent review approved with no actionable findings. Reconciled parent and all child raw events with receipts, verified static preservation/whitespace checks, and marked this bounded compatibility task complete without production or runner edits.
