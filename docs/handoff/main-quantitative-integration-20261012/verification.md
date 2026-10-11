# Main offline verification runner

Status: COMPLETE — DOCUMENT FROZEN FOR DELIVERY, 2026-10-12.
The owned runner implementation and verification scope is closed; runtime remains
frozen. The coordinator owns the shared handoff. No further review, execution or
source changes are planned by this owner.

Final runner SHA-256:
`53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa`.
Later transport, native integration and repaired-sidecar acceptance are recorded
in `transport-verification.md`; coordinator findings and closures are recorded
in `coordinator-review.md`. Earlier progress states below are preserved history.

## Brief and acceptance

Implement a main-scoped CPython test boundary before pytest/application imports.
Use a fresh evidence directory, preserve identity environment variables, prevent
ambient credentials/dotenv and saved-run access, redirect application data/logs
and caches, and block network, external mutations and unapproved subprocesses.
Only explicitly registered Python fixture/render scripts may run as children;
they must enter the same guard before third-party imports. This is trusted-code
accident containment, not an OS sandbox or protection from arbitrary native code.

| Requirement | Acceptance evidence |
|---|---|
| Early guard | Application import scenario plus pre-pytest marker/receipt |
| Network/write/credential boundaries | Actual attempted operations using synthetic files, plus allowed temporary writes |
| Child propagation | Registered Python script receives isolation with an explicit replacement environment; shell and unrestricted Python rejected |
| Identity/source preservation | HOME/home/CODEX_HOME/USERPROFILE equality and source hashes |
| Reproducibility | Fresh directory rejection, parent/child receipts and exact test commands |

## Plan and findings

1. Inspect current main bytes and import side effects. Done: conftest sets
   DRF_TEST_PROCESS but pytest is already imported; logger opens a production
   file during module import. Config and SimulationManager contain hardcoded
   uploads paths. Existing fake MCP and render tests launch Python scripts;
   other MCP tests launch shell stubs and unrestricted Python and require
   separate fixture adaptation by their owner.
2. Write guarded runner and focused controls. Done; 19 focused controls pass.
3. Capture a safe behavioral red, repair isolation, then run negative controls
   and selected real fake-stdio/render scenarios. Done; combined gate 26/26.
4. Deliver a usable command promptly and record source hashes, review and limits.
   Done; coordinator notified on initial release, child support and final freeze.

## Constraints and decisions

Only backend/scripts/main_offline_pytest.py,
backend/tests/test_main_offline_runner.py, and this report are owned. Preserve
all unrelated main dirt. No provider/model calls, dependency installation,
saved-run access, service restarts or Git commits. No excluded branch source
has been opened or copied. Use the existing backend Python environment with
`-I -S -B` so neither site startup nor ambient PYTHONPATH runs before the guard.

## Verification and remaining work

**Frozen runner SHA-256:**
`53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa`.
Fresh isolated compile and 15 controls passed at
`/private/tmp/drf-main-frozen-controls-20261012-01`; before/after hash agrees,
`source_drift=[]`, `identity_preserved=true`, `shutdown_complete=true`.
Consumers were notified that they may resume. Runtime bytes remain unchanged
during consumer acceptance. Any future runtime correction MUST be staged in a
private temporary file, compile-checked, then atomically replaced after
coordination with the lead.

**Frozen acceptance:** `/private/tmp/drf-main-frozen-acceptance-20261012-01`:
26 passed in 4.12s: 19 guard controls, 3 real fake-stdio MCP tests, 3 real renderer
subprocess tests, and the exactly-audited report download. Parent and all seven
child receipts completed with no source drift. Identity checks passed. One
expected child exit 3 is the missing-matplotlib fixture. Runner SHA above remains
unchanged; the tested control file SHA-256 is
`6664ddd3f74f80faec65a3f97a8979f3031139987da61eca41776458e60233ae`.
Ruff passed for both owned Python files.

Exact frozen acceptance command:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-main-frozen-acceptance-20261012-01 \
  --allow-python-script backend/tests/fixtures/fake_mcp_server.py \
  --allow-python-script deerflow_bridge/skills/data-visuals/scripts/render_data.py \
  -q backend/tests/test_main_offline_runner.py \
  backend/tests/test_data_mcp.py::test_start_list_and_call \
  backend/tests/test_data_mcp.py::test_child_env_is_allowlisted \
  backend/tests/test_data_mcp.py::test_cwd_and_errlog \
  backend/tests/test_data_visuals_render.py::test_cli_subprocess_end_to_end \
  backend/tests/test_data_visuals_render.py::test_exit_3_subprocess_without_matplotlib \
  backend/tests/test_data_visuals_render.py::test_plotly_missing_omits_html_path \
  backend/tests/test_report_publication_barrier.py::test_exactly_audited_report_is_exposed_and_downloadable
```

Change the evidence path before repeating this command; populated roots are
rejected. The negative controls deliberately recorded 3 parent network attempts,
3 credential-path attempts, 8 external-write attempts, 3 blocked concurrent
launches at the cap, a changed-script rejection, a SQLite URI rejection and
identity/saved-data protections. Additional child controls attempted a socket,
credential read and two external writes (one at atexit); all were blocked. These
are attempted operations, not live access. The parent additionally recorded
`fc-list=1`, `system_profiler=1`, `font_directory_scan=18`, plus two denied
post-exit MCP cleanup signals. The event streams preserve these classifications.

Initial CLI released after 6/6 controls pass independently and through pytest:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-main-OWNER-PHASE-20261012-01 \
  -q backend/tests/test_actor_roster_producer_consumer.py
```

Use a NEW path for every invocation. `/private/tmp` is canonical on this Mac;
`/tmp` is a symlink and is intentionally rejected. Evidence includes JUnit XML,
`completed.json`, `process-<pid>.json` and `events-<pid>.jsonl`. Read the event
counters even when pytest passes. No claims of zero attempted network calls
should be inferred from a passing result.

| Phase | Evidence root | Result |
|---|---|---|
| Safe behavioral red | `/private/tmp/drf-main-runner-red-20261012-01` | 5 controls passed; app import failed on blocked production log open |
| Pre-import redirects | `/private/tmp/drf-main-runner-green-20261012-01` | 6/6 stdlib controls passed |
| Actual pytest path | `/private/tmp/drf-main-runner-pytest-20261012-01` | 6/6 passed, JUnit and receipts captured |

The first version blocked all subprocesses. The current version supports exact,
explicitly registered Python scripts using repeatable `--allow-python-script`:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-main-CHILD-PHASE-20261012-01 \
  --allow-python-script backend/tests/fixtures/fake_mcp_server.py \
  --allow-python-script deerflow_bridge/skills/data-visuals/scripts/render_data.py \
  -q backend/tests/test_main_offline_runner.py
```

Registration permits Python under backend/tests, synthetic scripts inside this
evidence directory, and `render*.py` in bridge skill script directories. Script
hashes are checked before spawning and again inside the child. Only the same
Python interpreter may run; `-I -S -B -u` enters this guard before script imports,
even with an explicit minimal child env. Shell, `-c`, `-m`, arbitrary executables,
preexec functions and passed FDs remain denied. At most 64 launches and 8 live
children are permitted per process. Temporary PYTHONPATH shims must live in the
evidence directory and are inserted only after guards are installed. The test
API `sys.modules['main_offline_guard'].allow_python_script(path)` supports an
explicitly registered generated fixture. Recursive arbitrary spawning is not
authorized by the parent's registration.

Additional evidence:

| Phase | Evidence root | Result |
|---|---|---|
| Guarded child controls | `/private/tmp/drf-main-runner-children-20261012-02` | 9/9 pass; child blocks actual network/write/credential attempts with minimal env |
| Existing fake MCP transport | `/private/tmp/drf-main-mcp-child-20261012-01` | 3 pass, 20 deselected: start/list/call, explicit env, cwd/errlog |
| Renderer probe attribution | `/private/tmp/drf-main-render-import-probes-20261012-01` | 1 failed, 2 passed: actual blocking timezone read identified |
| Renderer children repaired | `/private/tmp/drf-main-render-children-20261012-02` | 3 pass, 23 deselected: actual CLI, no-matplotlib, no-Plotly |
| Reviewer controls red | `/private/tmp/drf-main-review-red-20261012-01` | 3 fail, 9 pass: SQLite URI classification, lexical credential path, inherited future annotations |
| Reviewer controls green | `/private/tmp/drf-main-review-green-20261012-01` | 12/12 pass after corrections |
| Combined guard/children | `/private/tmp/drf-main-runner-final-20261012-01` | 19 pass: 13 controls + 3 MCP + 3 render subprocess scenarios |
| MIME download compatibility | `/private/tmp/drf-main-mime-guard-green-20261012-01` | 15 pass: 14 controls + exactly-audited report download |

The renderer probes are attributable: matplotlib attempted `fc-list` and
`system_profiler`, plus 18 font-directory scans outside the read roots. These
remain blocked; system/bundled-font fallbacks rendered successfully. A read-only
allowroot for macOS system timezone data fixed the real dateutil failure;
PLOTLY_DIR now points to evidence/cache/plotly. Home Plotly config is not read.
The fake MCP parent caught two rejected cleanup signals after the child had
already exited. That rejection is retained to avoid signaling a reused PID.

Coordinator's `/private/tmp/drf-report-compat-v1` reproduced a report-download
HTTP 500: Python mimetypes attempted `/private/etc/apache2/mime.types`. The
runner now allows that exact system MIME database for reads, never for writes
and without granting `/etc` as a tree. The exact download scenario passes, and
a control confirms both MIME classification and rejection of writes to that
file. Receipts now expose `contained_library_probes` and a note explicitly
distinguishing contained attempts from zero probes.

The synthetic controls intentionally attempt
blocked network, credential, saved-data and external-write operations; these
are negative controls, not successful access. No saved-run data was read.

## Review, mistakes and limits

Independent reviewer Hume found five concrete issues: SQLite `file:` URI
classification, loss of lexical protected names during canonicalization,
evidence destination checking after mkdir, inherited future annotations, and
dotenv submodule compatibility. All are corrected and controls are recorded;
the SQLite red emitted the exact audit event without letting native SQLite open
any outside file. The second static review produced the six findings below.

The second review identified directory-entry mutation through external symlinks,
non-atomic child admission, changed os.open symlink-flag semantics, child hash
versus execution rereads, cwd-relative argument resolution, and sibling imports.
The frozen runtime addresses all six. Exact child bytes are compiled/executed,
child admission is serialized, and open preserves the original path/flags/dir_fd
after checking it. Directory-entry and target containment are both required for
writes; /dev/null is special only for opening. Final static rereview confirmed
the exact frozen SHA before/after and found no remaining must-fix issue within
the reviewed scope. The reviewer did not execute tests; the 26/26 gate above is
this owner's separate execution evidence.

A live patch briefly put `child_snapshot` between a `try` and its `except`,
causing a SyntaxError before another owner's tests could execute. The error was
fixed immediately and compile plus controls passed. That blocked consumer
attempt is **not** test failure evidence or a performed acceptance run. The
runtime freeze and private-file/atomic-replacement rule above prevent recurrence.

Controls now additionally exercise external-entry mutation decisions using exact
audit events with synthetic symlink resolution (no external fixture creation),
real O_NOFOLLOW/O_EXCL behavior on temporary symlinks, simultaneous Python child
admission with one remaining launch slot, and cwd-relative child execution with
a real sibling import. Shutdown receipts refresh after subsequently registered
atexit callbacks; the control confirms a blocked atexit write is included. This
does not claim coverage of every later interpreter-finalization event.

One directory-FD control initially used two `..` segments, which remained inside
the evidence root; it was a test error, not an escape. Three segments correctly
exercise the boundary. Its failed run is preserved in
`/private/tmp/drf-main-runner-children-20261012-01`.

The guard is for trusted tests and Python-audited operations. Native library
I/O, unaudited system calls, malicious hook tampering and filesystem race attacks
are outside this mechanism; it must never be described as OS/native isolation.
Existing MCP shell-stub, arbitrary `-c`, node-discovery and process-inspection
tests remain incompatible until their owner adapts fixtures. No test is silently
deselected by the runner. Source hashes currently cover the runner, explicitly
selected test files, redirected modules and registered child scripts; they do
not constitute a frozen hash of every imported application dependency.

## Owned delivery and next handoff

Exactly three paths were created by this slice:

- `backend/scripts/main_offline_pytest.py`
- `backend/tests/test_main_offline_runner.py`
- `docs/handoff/main-quantitative-integration-20261012/verification.md`

No existing shared source or conftest was changed, no dependency was installed,
and no Git commit was made. Unrelated working-tree changes were preserved.
Consumers should continue with the frozen runtime and fresh evidence roots;
new failures must distinguish application behavior, denied library probes and
blocked-before-execution attempts. No additional runner implementation remains
open for this slice. Provider/model/live-service and complete integration
acceptance belong to the coordinator and are not established by these tests.

Next-session prompt: “Read this report and the integration contract. Confirm the
frozen runner SHA before using it. Run only the requested main consumer tests in
a new `/private/tmp` evidence root; opt into exact Python fixture/render scripts
where needed. Inspect JUnit, parent/child receipts, source drift and classified
guard events together. Do not edit the frozen runtime while other owners test;
coordinate and use private compile-checked atomic replacement for any repair.”

## Updates

- 2026-10-12: Created the owned brief, acceptance table and import-side-effect findings.
- 2026-10-12: Captured safe behavioral red and two green runs; released the initial CLI and notified the coordinator. No shared source/conftest edits.
- 2026-10-12: Added guarded-child propagation; validated real fake MCP and renderer subprocess scenarios; recorded library-probe attribution and independent review corrections.
- 2026-10-12: Added exact-file read permission for the system MIME database following the coordinator's captured HTTP 500; verified report download and blocked writes. Recorded contained probe classifications in receipts.
- 2026-10-12: Corrected second-review findings, repaired the transient syntax mistake, compile-checked and passed 15 controls, then froze runtime SHA and notified the lead. Further changes are limited to focused tests and this owned report during consumer acceptance.
- 2026-10-12: Added focused regressions without changing frozen runtime bytes. Combined acceptance passed 26/26, with complete parent/child receipts, unchanged source hashes, preserved identity and classified contained probes.
- 2026-10-12: Final independent static rereview signed off the exact frozen runtime with no remaining must-fix finding; closed this owned slice and recorded the next-session handoff.
- 2026-10-12 delivery freeze: confirmed this owner's work is closed, clarified
  the current top-level status and linked the later review/transport receipts.
  No additional tests or exploration were performed for this documentation update.
