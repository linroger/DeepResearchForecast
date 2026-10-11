# Transport foundation verification

Status: COMPLETE — DOCUMENT FROZEN FOR DELIVERY, 2026-10-12.
Replacement transport acceptance is complete on reviewed hub 0b65ca3e.
The new guarded gate passed 173 cases (10 original transport, 19 deadline, 144
Data API); Boyle's replacement native gate passed the other 13 original cases
and was independently reviewed without duplicate execution. All 23 original
transport cases are covered on the replacement freeze. Earlier 010c1c/170-era
results remain historical only. The separate four-case integration adapter has
now passed execution and independent boundary/assertion-preservation review;
its receipt remains separate from the transport gates. The latest sidecar is the
independently accepted B012 repair
`c329cba3672d7ec23d3c8620a3667ba86de77e2c1e19485e3c53a57863079f37`,
with five passing failure controls and fresh deployment 9/9, transport 13/13 and
integration 4/4 receipts. The full exact-byte closure is at the end of this report.
No active HOLD, pending review or remaining execution applies to this owner's
scope. Earlier proposed/pending/hold statements are retained as chronological
history and superseded by the later closure sections. No further review or
exploration is planned. Source, tests, the frozen runner and Boyle's sidecar
remain unedited by this owner.

Scope: all 23 original tests in `backend/tests/test_data_mcp.py`, preserving
their assertions and identity environment. Reuse the frozen main runner where
its semantics fit, and coordinate reuse of
`backend/scripts/verify_deployment_fixtures.py` with Boyle for the other cases.
Do not create another harness or weaken original assertions to accept guard
errors as expected transport errors.

Partition: 10 main-guard cases, 6 pure shell/specification fixtures, and 7 native
lifecycle/launch cases. All 23 original assertion bodies must be accounted for;
no assertion replacement, transport mocking, skipped case or silent deselection
counts as full foundation acceptance.

The runner remains SHA-256
`53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa`.

Updates: 2026-10-12 — inspected all 23 test bodies and both verification
mechanisms; requested Boyle's reuse/interface assessment without authorizing
new implementation or test execution.

## A. Ten exact selectors for the frozen main guard

These preserve the real client, stdio transport and unchanged fake server. The
tests require no dynamic executable, `python -c`, `ps`, or direct PID-gone probe.

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-transport-guarded-ten-20261012-01 \
  --allow-python-script backend/tests/fixtures/fake_mcp_server.py \
  -q backend/tests/test_data_mcp.py::test_start_list_and_call \
  backend/tests/test_data_mcp.py::test_concurrent_calls_from_eight_threads \
  backend/tests/test_data_mcp.py::test_call_timeout_then_server_still_usable \
  backend/tests/test_data_mcp.py::test_tool_error_and_input_errors \
  backend/tests/test_data_mcp.py::test_redaction_of_secrets_and_bls_key_echo \
  backend/tests/test_data_mcp.py::test_child_env_is_allowlisted \
  backend/tests/test_data_mcp.py::test_cwd_and_errlog \
  backend/tests/test_data_mcp.py::test_exit_during_startup_reports_exit_code_and_stderr \
  backend/tests/test_data_mcp.py::test_unavailable_and_unsafe_specs_fail_instantly \
  backend/tests/test_data_mcp.py::test_get_hub_singleton_and_reset
```

Authorized execution: **10 passed in 5.12s** at the evidence path above. Use a
different fresh path for subsequent runs. The parent receipt has no recorded
source drift and preserves identity. Two exact fake-server children were reaped:
the shared server exited SIGTERM (-15) during teardown and has a started guard
receipt without atexit completion; the deliberately failing startup exited 7
with a completed receipt. Four rejected `os.killpg` cleanup attempts remain in
the event counts. This is not zero-probe evidence or proof of all seven native
lifecycle scenarios below.

This is an interim run. Cicero owns the optional-deadline hub repair and new test;
the final gate must bind the hub's announced frozen bytes. The main runner hashes
selected tests and registered fixtures, but not every imported bridge module;
capture explicit pre/post hashes for `data_mcp.py` in that final gate.

## B. Six pure specification/shell fixtures for Boyle's sidecar

Exact original selectors, all from `backend/tests/test_data_mcp.py`:

| Selector | Native operation that must remain real |
|---|---|
| `test_default_specs_resolve_all_six` | Fixture shell `node --version`; verify all six executable/args/env/timeout specifications. |
| `test_default_specs_defaults_from_env` | Same node version probe; scratch CWD/cache default and repo-root fallback. |
| `test_default_specs_missing_builds` | Same probe plus real scratch missing files, stale shebang and executable-bit checks. |
| `test_node_resolution_and_version_gating` | Fixture node versions 22/20/16, malformed version output, missing executable and controlled fallback search. |
| `test_node_version_checked_once` | Exact shell counter append and assertion that three lookups invoke the node fixture once. |
| `test_data_sources_allowlist` | Exact node probe plus disabled-provider and Python-only specification selection. |

Smallest reuse: extend Boyle's existing source-copy/AST-selected-case registry.
Copy byte-identical `data_mcp.py` into the scratch repo layout; select the original
test bodies and helpers `make_executable`, `fake_node`, `build_datamcps`, and
`tree`, stripping decorators only to supply fixtures explicitly. Retain body
hashes and the exact counter/script contents. No real MCP server, node/npm/uv
installation, pytest/application import or service launch is needed for these six.
Provide reversible module monkeypatching for the original fixtures, and reset
the module singleton/node-version cache between cases as the original conftest
does. Each case receives its own temporary tree.

The original `tree` helper's `env['HOME']=<tmp>/home` is **argument data** used by
`default_server_specs` to test fallback selection. Preserve that input. It must
not replace process identity: actual `os.environ` and launched child environment
must retain HOME/home/CODEX_HOME/USERPROFILE. `_node_version` inherits actual HOME
from `os.environ`; the shell fixtures do not need to read its contents.

## C. Seven native transport/lifecycle cases for the same sidecar

| Exact selector | Why the frozen guard changes the tested operation |
|---|---|
| `test_crash_restarts_once_then_circuit_opens` | `pid_gone` must observe real process absence after crash/restart; the guard rejects `os.kill(pid,0)` once the child is reaped. |
| `test_spawn_failure_returns_quickly` | Requires real `FileNotFoundError` for `/nonexistent/drf-node`; the guard emits `GuardViolation` before kernel launch. |
| `test_start_timeout_kills_the_child` | Requires native termination plus the original `pid_gone`/`ps` liveness assertion. |
| `test_close_kills_children_and_is_idempotent` | Real shutdown of ready and startup-delayed children, in-flight RPC cancellation, PID probes and loop-thread exit. |
| `test_interpreter_exits_promptly_and_leaves_no_orphans` | Executes the original bounded Python `-c` script, generated shell launcher and fake MCP; verifies process atexit and no orphan. |
| `test_default_specs_drive_the_hub_end_to_end` | Executes the generated venv shell launcher; checks IMF initialization and the expected WB argument/exit-code failure. |
| `test_terminate_groups_kills_a_survivor` | Launches the exact `python -c` sleeper in a new session and proves real SIGTERM/SIGKILL termination. |

Retain `FakeClock`, `fake_spec`, `wait_for`, `pid_gone`, `_run_python`, the shell
helpers and fake MCP source. Do not replace `pid_gone` with a stub returning True,
mock `_terminate_groups`, rewrite the asserted exception/exit code, or execute
this group with the guard disabled outside the OS sandbox.

Use the **same** sidecar's explicit transport case registry and scratch copy
mechanism. Its transport extension must preserve caller cwd, explicit env,
start_new_session, stdio pipes, timeouts and original executable argument shapes
where those are under assertion. Native `ps` inspection is limited to PIDs
created by this invocation; signals are limited to its child/session groups.
Prefer an OS-supported child-target signal restriction and prove it with an
owned outside-group sentinel. If native policy cannot express that bound, record
the limitation and obtain a reviewed tracked-child enforcement design; a blanket
signal grant is not proof of process-target isolation.

## Reuse compatibility constraints (no second harness)

Boyle alone edits `verify_deployment_fixtures.py`. This owner supplied the above
13 exact selectors and required helpers; both agents were instructed to preserve
the frozen runner and original `test_data_mcp.py`. The inspected deployment
sidecar currently targets nine deployment assertions; it is not yet an executable
transport command. A new transport mode/registry must be supplied by its owner
before claiming readiness. No invented CLI flag is presented as available here.

Concrete differences that its extension must handle:

1. Deployment's `fake_executable` accepts node `-v`; transport deliberately uses
   `--version`, several versions, malformed output and a persistent invocation
   counter. Keep transport's original fake-node bodies.
2. The current process wrapper forces cwd/env and supports only bash, git and
   Python. Transport needs exact fixture paths, original explicit environments,
   the controlled `/bin/sh` launchers, and owned-PID `ps` probes. The current
   unqualified `(allow signal)` requires narrowing or an explicit limitation
   before native lifecycle acceptance.
3. Resolving Python to its base binary and injecting `-S` does not by itself make
   existing backend-venv `mcp`/`anyio` dependencies available. Use the already
   provisioned runtime with an explicit read-only dependency/bootstrap plan;
   preserve the original Python `-c` payload and fake-server body. Do not install
   dependencies, inherit arbitrary PYTHONPATH, or substitute a real provider.
4. Prove anonymous pipes/asyncio's local wakeup mechanism work while Internet
   sockets stay denied. The deployment sidecar's shell-only controls do not
   establish that MCP dependency imports and stdio initialization work.
5. Missing-executable assertions require actual ENOENT, not OS policy EPERM.
   If the narrow profile masks that distinction, keep the case blocked and
   adjust the approved isolation policy; do not relabel the altered exception
   as successful foundation verification.

Before the thirteen run, the reused OS boundary must demonstrate scratch
read/write success, outside synthetic read/write denial, network denial,
unapproved executable denial, identity preservation and bounded cleanup. For
native lifecycle cases add child-PID signal/probe positive controls and an owned
outside-group negative control. Refuse execution if these fail; no unguarded
fallback. Record every selected original body hash, copied source hash,
policy/command/env-key inventory, timeout, exit code and child cleanup result.
Do not merge the OS-sandbox receipt with CPython evidence or claim native
isolation from Python hooks.

## Source identity and next actions

Inspected source hashes:

| Artifact | SHA-256 |
|---|---|
| Original 23 tests | `9f41f7308efd8825b87bd9f8a51b05ed547ecd146815dd8b33b0a34e48c51b48` |
| Hub before Cicero repair | `56c5679b20749f7bd1313cd263191fc2fd1477bafa00fdfb8dda1265b1c5fde6` |
| Fake MCP server | `f4116f777087ceb77a151006d9a9e3b7d7dd5e8c972c48fdb9913e1f4ea118bc` |

1. Boyle confirms ownership/reuse and publishes the bounded transport extension,
   its supported invocation and controls. His deployment implementation is
   actively changing; its inspected hash is not a freeze or transport approval.
2. Cicero publishes the hub freeze hash and optional-deadline regression selector.
3. Validate the sidecar controls, then run its exact six pure plus seven native
   cases. Preserve failures as failures; coordinate narrowly if a production
   defect appears.
4. Rerun the ten guarded cases against the final hub freeze, include the new
   deadline regression as separately identified coverage, and reconcile all 23
   original tests across the two evidence mechanisms.

Coordination identities: Boyle `01a12bdd-91be-7ab3-89dd-b1f7d6c11c7d`;
Cicero `01a12bd5-8e0f-7081-a1ae-22cea6e2a4b8`. No new harness or runner change is
authorized by this document. The lead explicitly authorized the ten-case run and
reuse of Boyle's extension for the thirteen after his confirmation.

- 2026-10-12: Lead authorized concrete verification; ten guarded cases passed.
  Preserved the four denied cleanup attempts and incomplete SIGTERM child receipt
  distinction. Requested Boyle's extension confirmation and Cicero's freeze.
- 2026-10-12: Boyle explicitly confirmed the same-sidecar extension with the exact
  13-case allowlist, original helper bodies and case-specific process handling.
  He remains the sole editor. His deployment worker had startup-policy issues
  under diagnosis; transport execution waits for published controls and readiness.
  Cicero acknowledged the freeze coordination and is implementing the optional
  absolute-deadline repair with a separate new test file. No duplicate edits or
  unguarded transport execution were performed.
- 2026-10-12: Inspected `test_data_mcp_deadline.py` for final-run compatibility.
  It uses real hub admission with recording sessions and one fixed fake-MCP
  transport scenario, so it can accompany group A after the hub freeze. The
  existing deadline red receipt contains eight behavioral failures, including
  actual expired/late dispatches; they are not missing-keyword errors. No extra
  baseline rerun is needed. Final execution still awaits the owner freeze.

## Final frozen-hub acceptance — 2026-10-12

The lead announced and this owner verified hub SHA-256
`010c1c0841a9173bf4d418050453fad4d5033f56a02994cb9de93f5222925765`.
The original test file remains `9f41f730...`; the complete deadline test file is
`78112376b7a9168dcb959f73d27daf81d528b20f8f9786c22aa671d0e1eceacd`.
The main runner remains `53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa`.

### Guarded gate

`/private/tmp/drf-transport-frozen-guarded-final-20261012-01` passed **26/26 in
8.97s**: the ten exact original selectors listed above plus the complete
`backend/tests/test_data_mcp_deadline.py` (sixteen cases). The command is retained
in `explicit-source-hashes.json`, together with pre/post hashes for the hub,
original and new tests, fixture, runner, conftest and Config. All seven hashes
match. Parent identity is preserved and shutdown completes.

Five registered fake children were reaped. Exit codes were -15, 7, 0, 0 and 1
for the exercised normal/error/termination controls. Ten rejected `os.killpg`
cleanup attempts remain explicit; there were no network, credential or external
write events. A signal-terminated child may have only its guard-start receipt;
the parent's reaped exit result is not relabeled as child atexit completion.

### Native sidecar gate and independent review

Boyle ran the single reused sidecar once:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/verify_deployment_fixtures.py \
  --suite transport \
  --evidence-dir /private/tmp/drf-main-transport-sidecar-20261012-01
```

Its parent `completed.json` and `work/worker-result.json` record **13/13 passed**,
15.011 seconds overall, no source drift, parent/worker identity preserved,
children and outside sentinel reaped, cleanup complete and the PS broker stopped.
All nine boundary controls passed: scratch read/write, outside read/write denial,
INET bind denial, unapproved executable denial, outside-sentinel signal denial,
anonymous AF_UNIX pair communication, owned-PID native status/signal access and
outside-PID status-request denial.

This owner independently verified, without rerunning the thirteen:

- Every scratch copy matches its manifest hash, including the exact frozen hub.
- All thirteen original assertion bodies and nine helper/class bodies match AST
  hashes recomputed from the untouched original test file.
- Native thirteen and guarded ten selectors have no overlap and their union is
  exactly the original 23 tests. All sixteen deadline cases are additional.
- The sandbox profile matches its recorded hash. It denies network operations,
  restricts writable paths to scratch and /dev/null, and limits signals and
  process information to same-sandbox targets.
- All 30 brokered native status queries use exactly `/bin/ps -o stat= -p <pid>`
  with a registered fixture PID; none target the outside sentinel.
- Normal bootstrap child exit performs no harness cleanup that could manufacture
  the original no-orphan assertion. Root cleanup happens after assertion execution.

Sidecar SHA-256:
`f568fcc1e1b8f9449356fc697326f840a1ae3a87ce90177b106d155bf9a524aa`.
SBPL profile SHA-256:
`905fc15ffee221f99cd7fe9b3d5f9d595053659e848c22fa6bba4a4d95f90b0b`.

The native `ps` command is a documented exception: macOS's binary cannot execute
inside this Seatbelt setup, so a parent broker outside the sandbox performs only
the fixed read-only status query. The worker first validates a registered PID and
the OS same-sandbox signal gate; the broker also restricts requests to registered
fixture PIDs and excludes the outside sentinel. This is a trusted-fixture broker,
not proof that arbitrary hostile scratch code cannot forge its journal. The
CPython and macOS sandbox receipts retain distinct assurance claims. Identity
and source preservation are verified for the exercised scenarios, not live
provider, deployment or service acceptance.

No remaining transport foundation case is untested for this freeze. No source,
original test, deadline test, frozen runner or sidecar edit was made by this owner.

- 2026-10-12 final update: received the verified hub freeze, ran the final 26-case
  guarded gate, independently reviewed Boyle's thirteen-case native receipt and
  boundary, and reconciled all 23 original plus 16 additional cases. New proposed
  integration coverage remains separate and awaits pre-execution boundary review.

## Superseding hold — 2026-10-12

The lead unfreezed hub 010c1c after independent review found three deadline
defects: an expired-send branch cancels its scope but can still enter send; a
startup rejection/restoration race can overwrite valid adoption; and generic
public-exception failure accounting omits the deadline. Those findings are
owned by the hub/deadline worker and do not authorize edits by this reviewer.

The 26-case guarded and 13-case native receipts above remain exact historical
scenario evidence. They do **not** close the newly reproduced defects. Previous
“complete for this freeze” statements must be read subject to this superseding
hold. Boyle was directly notified not to launch additional final transport or
integration gates until the replacement READY announcement. Read-only boundary
and generation-binding review may continue without provider/hub requests.

Next execution requires the replacement hub/test hashes, regression results and
an explicit READY release. The main runner, API and original transport tests
remain outside this owner's write scope and unchanged.

## Replacement READY and final coordinated acceptance — 2026-10-12

The lead published the replacement freeze and subsequently confirmed independent
reviewer James closed all three residual findings on the exact bytes with no
actionable finding. This supersedes the execution hold above for these frozen
transport gates only.

| Frozen artifact | SHA-256 |
|---|---|
| Hub | `0b65ca3e0ef012261faf994b00107c9b0b517a121fc8e583be05bfb6c58934a9` |
| Deadline tests | `6fc84115bc210d8efd1dcce0b77b65cb364cf2bc1c44bd4fcbf291c6755c0066` |
| Data API | `419663c3bbd0d1a790212ed229023b6f5b171e9e74adecff16adc4b04f001511` |
| API tests | `102bd5ccb17799da0b1691ced4b78155ca74ab97a7676855477c2542179baa61` |
| Original transport tests | `9f41f7308efd8825b87bd9f8a51b05ed547ecd146815dd8b33b0a34e48c51b48` |
| Main runner | `53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa` |

### Independently executed guarded gate

`/private/tmp/drf-transport-replacement-guarded-20261012-01` passed **173/173 in
11.12s**: exactly 10 original transport cases, 19 deadline cases and 144 API
cases, with no failures/errors/skips. The command is the ten exact selectors
in section A plus the full deadline and API test files; the only registered
child target is the unchanged `backend/tests/fixtures/fake_mcp_server.py`.
`explicit-source-hashes.json` retains the exact command and eleven pre/post
source/fixture/config hashes. Every tracked hash matches; parent identity and
shutdown are true and both receipts report no source drift.

Child results are deliberately separate from pytest success:

| Child PID | Parent-observed exit | Child receipt |
|---|---|---|
| 48734 | -15 (SIGTERM teardown) | Started only; no atexit completion is claimed. |
| 48752 | 7 (configured startup failure) | Completed, exit 7, shutdown true. |
| 48754 | 0 | Completed, shutdown true. |
| 48756 | 0 | Completed, shutdown true. |
| 48779 | 1 (known EOF-path scenario) | Completed, exit 1, shutdown true. |
| 48780 | 0 | Completed, shutdown true. |
| 48782 | 0 | Completed, shutdown true. |

All seven are reaped in the parent receipt. **Fourteen blocked `os.killpg`
cleanup attempts** are retained as attempted operations, not zero probes. Parent
and child event streams record no network, credential or external-write attempts.
The passing guard gate does not establish native isolation or all-zero child exits.

### Independently reviewed replacement native gate

Boyle executed the single authorized replacement run at
`/private/tmp/drf-main-transport-sidecar-replacement-20261012-01`: **13/13 original
cases passed in 15.391s**. This owner reviewed the parent and worker receipts
without executing a duplicate run. Hub/original-test hashes match the same freeze
as the guarded gate. All scratch copies and all thirteen assertion plus nine
helper/class body hashes were independently recomputed and matched. The thirteen
native selectors and ten guarded originals are disjoint and cover exactly 23
original tests; no case is omitted or counted twice.

All nine OS/ownership controls passed. Parent/worker identity is preserved,
source drift is empty, fixture cleanup is complete, worker and separately owned
sentinel are reaped, and the PS broker stopped. All **28** broker queries were
independently checked as the fixed `/bin/ps -o stat= -p <registered fixture PID>`
operation, excluding the outside sentinel. The count 30 in the earlier section
belongs only to the historical 010c1c run.

Replacement sidecar SHA:
`ede36f1ce30726635bbc03bd6b02fc0293fc2b65d2e01b7d8b20c9b7d926de4e`.
Profile SHA:
`2fe23714b0655017aedc10ee8a86da6ac809e70119bd48d49b36a586177f3d62`.
The native-PS parent-broker exception and trusted-fixture limits documented above
still apply. The added integration branch in this sidecar did not execute during
the transport run; that branch requires its own pre-execution boundary approval.

The coordinated result is **173 guarded plus 13 native**, not a fabricated
single-boundary 186-test run. No source, test, runner or sidecar code was changed
by this owner. The lead and hub owner received the exact receipt paths and
nonzero child/cleanup classifications.

- 2026-10-12 replacement update: verified replacement READY hashes, independently
  executed the 173-case guarded gate and independently reviewed the native 13-case
  rerun. Preserved all historical receipts and assurance distinctions; transport
  acceptance is complete for the replacement freeze only.

## Separate four-case integration boundary approval — 2026-10-12

The lead authorized this proposal subject to pre-execution review. This owner
reviewed frozen sidecar `ede36f1ce30726635bbc03bd6b02fc0293fc2b65d2e01b7d8b20c9b7d926de4e`
and `/private/tmp/drf-main-integration-sidecar-prepared-20261012-02` without
executing any integration case. Preparation records 110 exact source copies,
no worker started, no application imports and preserved identity. Every copied
hash and the four selected original assertion-body hashes were independently
verified. No uploads, logs, .env, credential or excluded-branch paths occur in the
copy manifest. The frozen runner copy matches 53a2cd; prepared profile hash is
`431f0f7425e91f58f7d03b578e32c95ce861e13d6656daff5741a896f84d6067`.

Only these cases are approved:

- `test_research_engine_v3_round2::test_r2_parent_pipeline_accepts_a_v3_research_run[clean]`
- `test_research_engine_v3_round2::test_r2_parent_pipeline_accepts_a_v3_research_run[cut]`
- `test_research_engine_v3_round3_robust::test_r3_sigint_during_a_fan_out_starts_no_queued_kiq_and_no_new_call`
- `test_research_engine_v3_round3_robust::test_r3_sigterm_leaves_a_terminal_status_and_a_closed_progress_log`

The copied test modules and dynamic child strings remain unchanged. Parent and
child bootstrap install offline/test flags, dotenv stubs and the unmodified
frozen storage transformer before app imports. The inert recorder supplies only
scratch root, source hashes and event recording; it does not install the CPython
guard policy that would alter native signal assertions. OS file/network/process
restrictions and the bounded read-only PS broker remain the enforcement boundary.
The adapter invokes the existing hermetic fixture before each case and calls the
original functions directly, with only their declared parameters supplied.

No actionable boundary defect was identified for these trusted fixtures. The
review is **permission to execute the four cases under the already-authorized
proposal, not a passing test result**. The nine boundary controls must pass before
any case runs; identities, child cleanup, app-import/source receipts, socket
observations and failures remain explicit. Only `report_agent.py` had changed
since the prepared copy inventory, so Boyle was instructed to create a fresh
bundle and capture all current before/after source hashes for execution. This
does not authorize adding cases, changing production code or weakening assertions.

- 2026-10-12 integration-boundary update: completed read-only source, manifest,
  assertion and SBPL review; notified Boyle and the lead that the exact four cases
  may execute once under the reviewed frozen sidecar with fresh source copies.

## Four-case integration receipt closure — 2026-10-12

The user requested receipt/boundary review only, without duplicate execution or
new independent exploration. This owner independently reviewed
`/private/tmp/drf-main-integration-sidecar-20261012-01/completed.json`,
`work/worker-result.json`, `work/manifest.json`, the SBPL profile, process journal,
PS broker journal and all five app-import receipts.

**Verdict: the four declared cases passed; no actionable boundary or original-
assertion-preservation finding remains in this bounded review.** Runtime was
5.899 seconds. Parent and worker exit codes are zero, source drift is empty,
identities are preserved, worker cleanup completed, worker and outside sentinel
were reaped, and the broker stopped. All nine OS/ownership controls passed before
the case loop.

| Original case | Recorded result |
|---|---|
| Parent pipeline accepts v3 research, clean world | Passed; real research-only child output accepted and subsequent reuse checked. |
| Parent pipeline accepts v3 research, cut world | Passed with the original cut-output assertions. |
| SIGINT during fan-out | Passed; original assertion requires child exit 0 after expected KeyboardInterrupt, restored handler and no queued/new work. |
| SIGTERM terminal state/progress-log closure | Passed; original assertion requires child exit `128 + SIGTERM = 143`, terminated metadata and closed log. |

Preservation checks performed independently:

- Rehashed all **110 scratch copies** against the launch manifest.
- Recomputed every selected original assertion-body hash and the three declared
  helper bodies (`_hermetic_env`, `_positional_citations_ok`, `_child`).
- Verified the full three test modules are byte-identical to their frozen source
  hashes, preserving their original dynamic string literals.
- Reconstructed the two parent/child scripts and both signal scripts directly
  from those original literals, using the same scratch-path substitutions, and
  compared the generated files byte-for-byte. All four matched.
- Verified the unchanged frozen runner copy and sidecar, and rehashed the actual
  executed SBPL profile.
- Checked the single brokered native `ps` query: fixed status-only argv, a
  registered fixture PID, and not the outside sentinel.
- Inspected all five `app-imports-<pid>.json` receipts (worker plus four case
  children). Each records exactly one Config, logger and simulation-manager
  redirect, corresponding source hashes, preserved identity and
  `audit_policy_installed=false`. Each observed Python socket-event map is empty.

Generated script SHA-256 values:

| Script | SHA-256 |
|---|---|
| Clean and cut research entrypoints (same code, different selected world env) | `3130c0ab02cab5699cc79271889cec841ee8e361d8d9b78aaa32fc842416d043` |
| SIGINT entrypoint | `e964f10515886f17bf1b3a62cc6fb69e298d6f6b5e95cacf6fe5d8726d6b0aca` |
| SIGTERM entrypoint | `4058bcd2d1ff42131d6fca814c6798ace92d641cf400c1275b157ad5fafc30d7` |

Executed sidecar SHA:
`ede36f1ce30726635bbc03bd6b02fc0293fc2b65d2e01b7d8b20c9b7d926de4e`.
Executed profile SHA:
`ad996de97e88e96b9461c74e977799231c2efa3ffc3fa42e418391ffb777ba5b`.
The copied main runner remains
`53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa`.

This is native-fixture acceptance under the reviewed macOS OS boundary, with
the already documented trusted-fixture, read-only parent `ps` broker exception.
Empty Python socket-observation maps are not a complete native syscall audit;
the mandatory denial controls intentionally attempted prohibited operations.
The SIGTERM result is established by the preserved original assertion, not by a
blanket all-child-exit-zero claim or a newly fabricated per-child exit receipt.
The CPython guard's native-signal restrictions were not installed or represented
as OS enforcement; only its unchanged pre-import storage transformer was reused.

Closure applies to the 110-file launch generation recorded in this receipt. It
does not replace the future final combined gate after the report owner's freeze,
and it establishes no live-provider, saved-run, deployment or publication result.
No fixture was rerun, and no source/test/runner/sidecar code was edited here.

- 2026-10-12 integration closure: completed independent receipt, source/body/hash,
  generated-script, import-isolation, signal-assertion and cleanup review; returned
  the bounded four-case closure to Boyle and the lead. Only this report changed.

## B012 harness-only repair: independent exact-byte closure — 2026-10-12

The lead unfreezed only the sidecar after Ruff identified the `worker()` return
inside `finally`: an owned-route exception could be suppressed while stale
`output['exit_code']=0` was returned. Production, hub, API, original assertions
and the main runner remained outside this repair. This review checked the
failure path first, then the three requested fresh suite receipts; it did not
reopen production or publication analysis.

**Accepted sidecar SHA-256:**
`c329cba3672d7ec23d3c8620a3667ba86de77e2c1e19485e3c53a57863079f37`.
**Negative-control test SHA-256:**
`bd570464b2898f927cc6e056716725ae901015bb8c15229799ffcb4f17a98440`.

An independent full-module AST comparison with the verified `ede36f1c…` copy
found exactly one changed top-level node: `worker`. Profiles, case registries,
bootstraps, broker, original assertion handling and all other functions are
unchanged. The corrected ordinary-exception path sets exit code one and replaces
the stale owned receipt. The finalizer no longer returns: it skips duplicate
outer cleanup for an already-owned result and otherwise performs the outer
cleanup/write path. `SystemExit(23)` therefore propagates instead of becoming
success.

The supplied red JUnit at `/private/tmp/drf-sidecar-b012-red-20261012-01` contains
five meaningful failures: stale zero returns for both owned routes, acceptance
of those zeros by the actual parent-supervisor control flow, and suppressed
SystemExit. They are not setup/import failures. The owner's green contains five
passes. This reviewer independently ran the unchanged new test file under the
frozen main guard:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-sidecar-b012-independent-20261012-01 \
  -q backend/tests/test_deployment_sidecar_control_flow.py
```

Result: **5 passed in 0.91s**, matching before/after helper/test/runner hashes,
identity preserved, complete shutdown and redirects only. `children={}`: these
controls execute real worker/main control flow while substituting native dispatch
and OS controls; they do not pretend to establish the native boundary. Exact AST
and source checks are retained in `independent-source-check.json` in that root.

### Three fresh suites, reviewed without duplicate execution

| Suite | Result | Evidence root |
|---|---|---|
| Deployment | 9/9 passed, 4.826s | `/private/tmp/drf-sidecar-b012-deployment-final-20261012-01` |
| Transport | 13/13 passed, 14.738s | `/private/tmp/drf-sidecar-b012-transport-final-20261012-01` |
| Integration | 4/4 passed, 5.707s | `/private/tmp/drf-sidecar-b012-integration-final-20261012-01` |

For every suite, parent and worker exit zero; all nine boundary controls pass;
source drift is empty; identities are preserved; child cleanup completes; the
worker and outside sentinel are reaped; and the PS broker stops. All three
receipts and scratch copies bind the exact c329cba candidate.

Independent preservation checks recomputed every copied hash (19 deployment,
19 transport, 110 integration), every recorded selected assertion/helper AST hash
(32, 32 and 38 respectively), and all three executed profile hashes. The listed
original sources also still matched their recorded hashes at review close. The
transport broker made 29 fixed owned-PID status queries; integration made one.
All were checked against the registered-PID journal and excluded the outside
sentinel. This is the same documented read-only parent-broker exception, not a
new general native command surface.

The integration rerun again has five pre-app redirect receipts, with unchanged
Config/logger/simulation-manager source identities, preserved environment
identity, `audit_policy_installed=false`, and empty observed Python socket-event
maps. All four generated scripts were reconstructed from the original literal
expansions and matched exactly. Original SIGINT exit-zero and SIGTERM exit-143
assertions remain intact; no blanket all-child-exit-zero claim is made.

Executed profile SHA-256 values:

- Deployment: `7de969326b2d99e2c6ff98ae1c920bdce904563754c2621a1fa99433aaaf6526`.
- Transport: `74874c64e9d6809cdeabcb63d63b34250cfe61744bcfe5f3a99c71b0f3f2a540`.
- Integration: `a2d193a8bcf6a72b47ef90725e651c52f43c2279b3d27a5bc863aff3b38d5e82`.

**Independent verdict: no actionable finding remains in this bounded B012
control-flow repair, and the three fresh-suite receipts are accepted for the
recorded bytes.** Earlier normal-case receipts remain historical evidence; the
c329cba receipts establish the repaired supervisor behavior. The five controlled
negative tests and 9/13/4 native suites are distinct evidence, not one invented
combined run. The existing OS/CPython/trusted-fixture assurance limits still apply.

Only this review report was changed by this owner. No harness, original test,
application, hub, API or frozen-runner code was edited, and no native suite was
duplicated. Broader production and true-publication results were not rerun or
reassessed in this harness-only follow-up.

- 2026-10-12 B012 closure: verified exact worker-only AST change, independently
  passed all five failure controls, reviewed the three fresh suite receipts and
  preservation proofs, and returned the bounded closure to Boyle and the lead.

- 2026-10-12 delivery freeze: clarified current acceptance and the final c329cba
  sidecar at the top, explicitly superseded historical holds/pending states, and
  froze this document for delivery. No new execution or independent exploration.
