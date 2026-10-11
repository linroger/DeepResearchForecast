# MCP hub absolute deadline fix

**Last updated (UTC):** 2026-10-11T19:00:16Z
**Status:** Complete for the bounded hub fix, independent review and refreshed guarded/native transport acceptance.
**Current focus:** Deliver the unchanged review-approved replacement hub0b65ca3e... with final acceptance receipts.

## 1. Request and ownership

Fix the global deadline hole between DataSources prewarm/status checks and a hub
restart/tool dispatch. This task owns only `deerflow_bridge/data_mcp.py`, NEW
`backend/tests/test_data_mcp_deadline.py`, and this report. Existing
`backend/tests/test_data_mcp.py`, frozen runner, providers, API implementation,
other modules/handoffs and saved runs are not writable. Stay on main without Git
mutations, installations, live providers or network access. Preserve other work.

## 2. Frozen coordination contract and acceptance

API owner `01a12bdd-9095-7d81-9c13-917029de4fda` and lead froze:

```python
McpHub.call(name, tool, args, *, timeout=None, deadline: float | None = None)
```

`deadline` is an absolute `time.monotonic()` instant shared across DataSources
preflight, startup/restart, semaphore and tool admission. `None` preserves direct
call behavior. Expired work returns a failure `CallResult` before launching or
dispatching. Every request wait is capped to the remaining original budget and
checks are repeated under admission/at invocation; no relative budget reset.
API owner alone updates its `_call` callsite to pass the thread-local deadline
for bounded workers, retaining its existing `hub.start(names, wait=remaining)`
prewarm/status gate. This worker confirmed the keyword contract directly.

| Requirement | Acceptance scenario | Evidence |
|---|---|---|
| Cold startup consumes global budget | Startup exceeds caller budget; call fails promptly and never invokes tool | Before/after regression |
| Ready-to-failed restart race | Ready observed before failure; restart must not reset caller budget or dispatch late | Deterministic race regression |
| Expired admission | Deadline expires before launch, during startup, while queued, or before tool invocation | Launch/dispatch recorder and negative controls |
| Independent concurrent callers | Expired caller neither poisons shared hub nor cancels another valid call | Concurrent short/long deadline scenario |
| Default compatibility | No absolute deadline retains existing direct-call timeout semantics | Existing transport acceptance and explicit control |
| Safe lifetime | Request futures cancel on timeout and shared sessions remain lifecycle bounded; no post-deadline provider tool call | Cancellation/late-dispatch assertions and receipts |

## 3. Plan

1. Read hub lifecycle, API callsite and existing transport fixtures; coordinate contract.
2. Author focused tests with real hub admission/invocation and synthetic sessions,
   plus fixed fake-MCP transport acceptance when useful. Capture baseline behavior
   using the current relative-timeout call shape rather than counting missing-keyword
   TypeErrors as meaningful red.
3. Add optional absolute deadline checks and remaining-budget waits across the
   existing hub path. Preserve shared owner lifetime and independent callers.
4. Capture guarded green under frozen runner, coordinate landing/hash with API and
   transport owners, obtain independent review and transport acceptance.

## 4. Progress ledger

- [x] Read main hub/API/fixtures and confirm frozen runner hash `53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa`.
- [x] Confirm exact optional keyword contract with API owner by direct message.
- [x] Capture meaningful baseline red before hub patch: eight actual late-dispatch failures, three passing controls.
- [x] Implement and verify bounded admission and writer handoff: 16/16 guarded green, including actual SDK in-flight cancellation/session reuse.
- [x] Notify API/transport owners of frozen hash/selectors directly; independent original10 + new16 transport gate passed.
- [x] Obtain independent review approval with no actionable findings on replacement hub0b65ca3e... and source-bound 19-case transport/deadline gate.

## 5. Findings and design constraints

Current `_call` waits the full startup timeout plus grace, then submits `_invoke`
with a fresh relative call limit and waits limit plus result grace. `_invoke`
also clamps exhausted tool budget upward to 1ms. Thus a startup/restart race can
dispatch after the original DataSources deadline even with `timeout=remaining`.
Existing ready/failed transitions are protected by a shared RLock; deadline
checks must be made under that admission lock and again on the hub loop.

A transport owner is running ten existing transport cases independently and will
wait for this worker's hub freeze before its final rerun. No changes to the
existing transport test file are part of this task. Shared startup may serve
multiple callers; expiry of one caller must not cancel unrelated valid work.

## 6. Issues and recovery

Baseline used a temporary feature-detection adapter that dropped the new keyword
on the original hub while preserving `timeout=remaining`. It exposed real late
dispatch rather than missing-keyword TypeErrors. That adapter was removed after
red; final tests call the new absolute keyword directly.

Baseline `/private/tmp/drf-main-mcp-deadline-red-20261012-01` reports **8 failed,
3 passed** in 2.41s, exit 1. Original hub SHA was
`56c5679b20749f7bd1313cd263191fc2fd1477bafa00fdfb8dda1265b1c5fde6`.
Expired requests returned success; cold/restart calls dispatched after ~0.18s
against 0.04s budgets; ready-event, loop queue and semaphore gaps likewise sent
expired calls. Parent/child receipts preserve identity/shutdown and have no source
drift. One fake child exited 0. Two denied process-group cleanup probes were
recorded separately; no provider/network requests occurred.

Initial implementation passed 11 cases. Self-review added queued-owner adoption,
prewarm adoption, final process-start admission and bounded lock/bookkeeping,
then 14 cases passed. Independent reviewer James identified an additional P1:
the shared stdin writer can already own a message when the caller expires.
Captured separate meaningful review red at
`/private/tmp/drf-main-mcp-writer-review-red-20261012-01`: real SDK/fake-process
recording showed `stdin.send` receiving the expired `never sent` tool request,
while its caller had returned deadline failure. The test also preserved a valid
sibling. This one-failure receipt is not a setup or unsupported-keyword error.

The fix now captures a per-request deadline/cancellation token at SDK outbound
handoff, rechecks it before and after serialization, and admits no new write for
an expired tools/call. Per-write cancellation is scoped to that message; it does
not cancel the shared writer. Bytes already admitted before a deadline cannot be
recalled from OS buffers; the guarantee is no fresh launch/tool/write admission
after expiry, not retroactive cancellation of an already dispatched provider request.
Shared startup remains bounded by its existing owner/start timeout once launched,
and independently valid callers can adopt queued startup. Expired unlaunched
owners restore idle/failed state without consuming the once-only restart quota.

## 7. Scenario-focused checks

Use recording async sessions and controlled owner startup to exercise real hub
locks, `_admit`, `_launch`, ready events, `_invoke`, semaphore and Future handling.
No mock may fabricate the hub's deadline decision. Real transport controls use
only the existing fixed fake MCP child with synthetic tool responses and temp
roots; no node/vendor server or provider HTTP operation is authorized.

## 8. Execution and evidence

Use existing `backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py`
with fresh canonical `/private/tmp` evidence directories and explicit selectors.
Only fixed Python fixtures are registered with `--allow-python-script` when
needed. Inspect parent/child completion, JUnit, events, identity, shutdown and
source drift. Preserve HOME/home/CODEX_HOME/USERPROFILE. No frozen runner edits.

Current gate:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-main-mcp-deadline-green-20261012-03 \
  --allow-python-script backend/tests/fixtures/fake_mcp_server.py \
  -q backend/tests/test_data_mcp_deadline.py
```

**15 passed in 3.69s, exit 0.** Completion/JUnit and events inspected. Parent
identity/shutdown true, source_drift empty; two allowed fake children exit 0.
Four denied `os.killpg` fallback cleanup probes are separate from success; the
children had graceful termination and no provider/network/credential/saved-run
activity was permitted. The frozen runner remains SHA53a2cd41....

Current candidate hub SHA:
`010c1c0841a9173bf4d418050453fad4d5033f56a02994cb9de93f5222925765`.
New test SHA:
`8cdf71b47440b52e3ffa243983cf7f50b11d716783970732ba7959313132c7ff`.
API callsite SHA419663c3... and existing transport-test SHA9f41f730... were read
and verified without edits. API owner received candidate landing/hash/selectors;
the candidate was subsequently frozen as authorized by lead while rereview continues.

### Frozen implementation and final transport evidence

Hub is **FROZEN** at
`010c1c0841a9173bf4d418050453fad4d5033f56a02994cb9de93f5222925765`.
Full new test file SHA is
`78112376b7a9168dcb959f73d27daf81d528b20f8f9786c22aa671d0e1eceacd`.
API owner and Boyle (`01a12bdd-91be-7ab3-89dd-b1f7d6c11c7d`) / Euler
(`01a12bdd-9315-7001-a2ca-81a445ed71aa`) received the freeze/hash/selectors by
direct coordination message. No code/test changes have occurred since freeze.

Latest owned run:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-main-mcp-deadline-green-final-20261012-01 \
  --allow-python-script backend/tests/fixtures/fake_mcp_server.py \
  -q backend/tests/test_data_mcp_deadline.py
```

**16 passed in 4.66s; exit 0; no test failures/errors/skips.** The extra real SDK
scenario confirms a bounded in-flight tool task is cancelled while a concurrently
valid echo and subsequent direct echo remain successful. All eight
[before hashes](/private/tmp/drf-main-mcp-deadline-final-20261012-01.before.sha256)
and [after hashes](/private/tmp/drf-main-mcp-deadline-final-20261012-01.after.sha256)
match. Parent [completion](/private/tmp/drf-main-mcp-deadline-green-final-20261012-01/completed.json)
and [JUnit](/private/tmp/drf-main-mcp-deadline-green-final-20261012-01/junit.xml)
preserve identity/shutdown and have source_drift empty. Three registered fake
children were reaped; six denied `os.killpg` fallback cleanup attempts remain
explicit. Two child exits are 0; the in-flight cancellation fixture child exits 1
after EOF because its already-admitted remote sleep later responds to a closed
MCP stream (`ClosedResourceError`). Its receipt still confirms complete shutdown,
identity and no drift/blocked child activity. This is separately disclosed, not
silently counted as a clean child exit or a failed caller assertion.

Static check passes:
`ruff check --isolated --no-cache --target-version py312 --select F,E9 deerflow_bridge/data_mcp.py backend/tests/test_data_mcp_deadline.py`.
An initial isolated lint invocation without `--target-version py312` incorrectly
flagged the pre-existing Python 3.11+ `BaseExceptionGroup` builtin; correcting the
lint target (the existing interpreter is Python 3.12) required no source change.

Transport acceptance owner independently reports **26/26 passed in 8.97s** for
the original ten immutable transport cases plus the full sixteen new deadline
cases at `/private/tmp/drf-transport-frozen-guarded-final-20261012-01`.
Its `explicit-source-hashes.json` covers seven pre/post files including this hub,
with no drift; runner remains unchanged. Five registered fake children were
reaped and ten denied process-group cleanup attempts are explicitly reported.
This establishes relevant guarded transport acceptance against the frozen hub.
Boyle's separate native13 sidecar gate remains coordinator-owned and is not
represented as completed by this task.

### Combined API + transport acceptance and teardown classification

**Historical snapshot only:** Results in this section apply to hub010c1c... and
predate three later reproduced review findings. They are not current acceptance
for replacement hub0b65ca3e.... Raw receipts and teardown classifications remain
preserved.

API/transport coordinator subsequently ran
`/private/tmp/drf-data-api-transport-final-20261012-01`: **170/170 passed in
10.08s**, consisting of the original guarded10, full new16 and API144. This
worker inspected its [completion](/private/tmp/drf-data-api-transport-final-20261012-01/completed.json),
[JUnit](/private/tmp/drf-data-api-transport-final-20261012-01/junit.xml), per-process
receipts and the in-flight fixture's stderr. Parent exit 0, no test errors,
failures or skips, identity/shutdown true, source_drift empty. The coordinator
reports exact pre/post stability of hub010c1c..., API419663..., original tests
9f41f730..., new tests781123..., and runner53a2cd41...; completion also records
those frozen hashes. Only the exact fixed fake child was allowed. No network,
credentials or saved-data operations were recorded.

Parent reaped five fake children with exit codes **[-15, 7, 0, 0, 1]** and records
**ten denied `os.killpg` fallback cleanup attempts**. Classify these separately:

- `41579`, exit -15: configured slow-start timeout/termination control. Its child
  receipt is **started-only**, with `shutdown_complete=false` and no final exit
  recorded there; parent reaping confirms process termination. Do not manufacture
  a completed child receipt or assert clean child shutdown hooks ran.
- `41600`, exit 7: the configured startup-exit failure control, with completed
  child receipt and shutdown true. This expected child exit is not a failed pytest
  assertion or a live-provider failure.
- `41605` and `41626`, exit 0: completed fake transport children, shutdown true.
- `41629`, exit 1: real in-flight cancellation scenario passed its behavioral
  assertions (bounded request cancellation, valid sibling and session reuse),
  then the already-admitted fake server sleep responded after EOF/stream closure.
  Its [stderr](/private/tmp/drf-data-api-transport-final-20261012-01/pytest-tmp/test_real_inflight_deadline_ca0/logs/fake.stderr.log)
  ends in `anyio.ClosedResourceError` while sending that response. Child receipt
  is completed with shutdown true, empty events and no source drift. It is
  post-assertion server-fixture teardown behavior, not a new request dispatched
  after its deadline, and is **not** counted as child exit 0.

Thus the 170-test pass establishes the exercised request/transport/API behavior
and parent-managed child reaping; it does not establish all child exits being
zero or native13 sidecar/process-group acceptance. Native13 remains separately
owned by Boyle. No production, fixture or runner bytes were changed in response
to this teardown observation.

### Review residuals, announced unfreeze and replacement freeze

Independent rereview accepted closure of the first four findings but identified
three residuals in 010c1c.... Announced UNFREEZE/HOLD directly to lead/API/Boyle/
Euler before edits. Reproduced all three at
`/private/tmp/drf-main-mcp-review-residuals-red-20261012-01`: **3 failed in 1.75s**,
with no setup errors. The expired final branch still entered `stdin.send`; a
valid caller lost startup adoption and returned `server not ready (idle)`; generic
exception accounting waited ~0.305s against its 0.04s deadline.

Corrections stay within owned hub/newtests:

1. Encode outbound bytes before the final deadline guard, and `continue` rather
   than merely cancelling a scope when expired. No send coroutine is entered.
2. Retire rejected startup while still holding the same admission RLock. A later
   valid caller sees idle/failed state and launches a new owner; rejected-owner
   exception cleanup cannot overwrite the new owner/generation.
3. Keep the validated absolute deadline in a separate local and pass it through
   both timeout and generic-exception failure accounting, preserving the bounded
   return path even under concurrent lock contention.

Replacement gate:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-main-mcp-deadline-replacement-final-20261012-01 \
  --allow-python-script backend/tests/fixtures/fake_mcp_server.py \
  -q backend/tests/test_data_mcp_deadline.py
```

**19 passed in 5.88s; exit 0.** All eight
[before hashes](/private/tmp/drf-main-mcp-deadline-replacement-20261012-01.before.sha256)
and [after hashes](/private/tmp/drf-main-mcp-deadline-replacement-20261012-01.after.sha256)
match. Ruff Python3.12 F/E9 passes. Published replacement READY/FROZEN directly
to API owner, Boyle and Euler, while independent rereview continues against exact
bytes as lead explicitly authorized. No further edits are planned absent an
announced hold. Parent completion has identity/shutdown true and empty drift.
Five allowed fake children were reaped, with exit codes [0,0,1,0,0]; the same
post-assertion in-flight server EOF response explains exit 1. Ten denied
`os.killpg` fallback cleanup attempts are recorded separately. No live provider,
network, credential or saved-data operation was permitted.

- **Current hub:** `0b65ca3e0ef012261faf994b00107c9b0b517a121fc8e583be05bfb6c58934a9`
- **Current new tests:** `6fc84115bc210d8efd1dcce0b77b65cb364cf2bc1c44bd4fcbf291c6755c0066`
- **Unchanged API:** `419663c3bbd0d1a790212ed229023b6f5b171e9e74adecff16adc4b04f001511`
- **Unchanged original transport tests:** `9f41f7308efd8825b87bd9f8a51b05ed547ecd146815dd8b33b0a34e48c51b48`
- **Unchanged frozen runner:** `53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa`

Coordinated original10 + replacement19 + API144 acceptance is expected to contain
173 cases. That rerun remains pending; historical 170/26-case green is not
substituted for it.

### Independent review closure on replacement bytes

Reviewer James (`01a12c3b-a8e3-7e90-8887-c2e77a219f73`) independently verified hub
SHA0b65ca3e... and test SHA6fc84115..., inspected final completion/JUnit, and returned
**"Replacement READY for freeze. No actionable findings; all three residual
findings are closed."** Source review confirmed encoding precedes final guards,
expired send is skipped, startup retirement is atomic under the RLock, old-owner
cleanup cannot overwrite a successor, and both outer exception paths carry the
validated absolute deadline. The reviewer made no edits and ran no tests/app or
providers. It also confirmed the 19-case receipt's clean parent shutdown,
preserved identity and empty source drift; the known fake-server EOF caveat is
not an additional production finding.

Sent review-approved replacement READY directly to API owner, Boyle and Euler.
No source/test changes occurred after the replacement freeze or its review.

### Final replacement combined and native acceptance

Inspected the replacement combined
[completion](/private/tmp/drf-data-api-transport-replacement-final-20261012-01/completed.json)
and [JUnit](/private/tmp/drf-data-api-transport-replacement-final-20261012-01/junit.xml):
**173/173 passed in 11.23s**, original guarded10 + new19 + API144, with zero
errors/failures/skips. Frozen hub0b65ca3e..., API419663..., original tests9f41f730...,
new tests6fc84115... and runner53a2cd41... match recorded hashes. Coordinator
verified unchanged pre/post bytes; completion has source_drift empty and parent
identity/shutdown true. Only the exact fixed fake child was allowed.

Seven registered children were reaped, exit codes **[-15,7,0,0,1,0,0]**; fourteen
denied `os.killpg` cleanup probes remain explicit. `48530` is the configured
slow-start SIGTERM control with a started-only child receipt, parent-reaped.
`48570` is the configured exit-7 startup control. `48577` is the real SDK
in-flight cancellation case's post-assertion EOF/closed-stream server response,
exit 1 with completed child receipt. The remaining four children exit 0. The
previous detailed classifications apply; this does not imply all child exits 0
or that denied group signals established native process-group cleanup. No
network, credential or saved-data activity was recorded.

Separate native acceptance also passed at
[/private/tmp/drf-data-api-native-replacement-final-20261012-01](/private/tmp/drf-data-api-native-replacement-final-20261012-01/completed.json):
**13/13 native cases**, elapsed **13.766s**, with **9/9 OS isolation controls**.
This worker inspected its parent completion and `work/worker-result.json`:
parent/worker exit 0 and identity preserved, source_drift empty, child cleanup
complete, worker and sentinel reaped, and broker stopped. The boundary is macOS
sandbox-exec, distinct from the CPython guard; source includes frozen hub0b65ca3e....
Coordinator verified copied bodies/assertions and nine helper ASTs against the
frozen original tests. This worker additionally checked the exact disjoint union
of guarded10 and native13 against all 23 original `test_data_mcp.py` test-function
names: no overlap or omission. No sidecar/runner/test source was edited by this
worker or in response to these results.

Current combined/native evidence supersedes historical 010c1c.../170/26-case
acceptance for this fix. There is no remaining owned implementation, review or
transport acceptance gap. These offline synthetic fixtures do not claim live
provider availability, upstream response-time guarantees, or recall of bytes
already admitted before a deadline.

## 9. Remaining work and continuation

No hub implementation, owned-test, independent-review or transport acceptance
findings remain open. Current 19-case owned gate, combined173 and separate
native13 + OS9 controls all apply to review-approved hub0b65ca3e.... Preserve
these exact bytes and historical red/review evidence when assembling the broader
integration gate; no actor/compatibility/data-integration completion claim is
inferred from this bounded hub fix.
Continuation prompt: "Read
mcp-deadline-fix.md. Finish only the optional absolute-monotonic hub deadline
contract across cold startup/restart/semaphore/tool dispatch in the three owned
paths. Keep default calls compatible, preserve independently valid callers,
coordinate API callsite/transport freeze, and never edit the frozen runner or
existing test_data_mcp.py."

## 10. Updates

- 2026-10-11T18:14:26Z: Created this owned continuity report and confirmed the frozen optional deadline keyword with the API owner before production edits.
- 2026-10-11T18:38:49Z: Recorded baseline eight-failure behavioral red, 11/14-case intermediate greens, independent writer-handoff P1/red/fix, and current 15-case guarded green. Notified API owner of candidate landing/hash while independent rereview continues.
- 2026-10-11T18:42 UTC: Published verified hub freeze010c1c... directly to Boyle, Euler and API owner after 16-case source-bound green. Recorded SDK child EOF/ClosedResourceError separately and preserved frozen bytes.
- 2026-10-11T18:44 UTC: Independent transport owner reported original10 + new16 all passing against the frozen hub with seven-file no-drift proof and reaped children; awaiting only narrow independent rereview for this fix.
- 2026-10-11T18:45:45Z: Inspected combined 170-case API/transport acceptance and explicitly classified child exits [-15,7,0,0,1], started-only SIGTERM receipt and post-assertion closed-stream server response. Retained all frozen bytes and separated native13 proof from this green result.
- 2026-10-11T18:54:00Z: Re-review found three residuals; announced unfreeze before edits, captured three behavioral reds, corrected the narrow branches, obtained 19-case source-bound green and published replacement hub0b65ca3e.../newtests6fc84115... freeze for coordinated reruns and ongoing independent review.
- 2026-10-11T18:55 UTC: Independent reviewer approved exact replacement bytes with no actionable findings and closed all residuals. Notified API/Boyle/Euler that replacement READY is now review-approved; refreshed combined receipt remains pending.
- 2026-10-11T18:58 UTC: Reconciled current parent/child events and receipts, verified nineteen-case JUnit and frozen hashes again, and closed only the owned hub/deadline/source-review work. Combined/native receipts remain coordinator-owned pending evidence; no code/test bytes changed.
- 2026-10-11T19:00:16Z: Inspected refreshed combined173 and native13/OS9 receipts on exact replacement bytes; classified all child exits, confirmed cleanup/identity/no drift and exact guarded/native union of all 23 original transport tests. Closed bounded transport acceptance without any further source/test/runner edits.
