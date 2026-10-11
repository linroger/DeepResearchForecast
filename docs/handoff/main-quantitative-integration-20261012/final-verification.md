# Final quantitative integration verification

Status: Functional acceptance and all scoped independent reviews complete on main; scoped Git delivery is being closed. No live provider/model/deployment result is claimed.

## Current acceptance

| Boundary | Result | Evidence |
|---|---:|---|
| Combined actor, provider API, v3/legacy, promotion, report, downstream and configuration regression gate | 2,025 passed; 15 explicitly separated | `/private/tmp/drf-main-integration-final-20261012-01` |
| Real stdio MCP → agent tool/source ledger → dataset persistence → promoted research → real charts → publication audit → Flask/detail/download/assets → report and dossier exports | 1 passed, no publication bypass | `/private/tmp/drf-main-official-e2e-no-bypass-final-20261012-01` |
| Original MCP transport cases | 23 distinct cases: 10 guarded and 13 OS-sandboxed | `transport-verification.md` and `deployment-acceptance.md` |
| Absolute deadline regressions plus provider API | 19 deadline + 144 API cases, also included in the combined gate | `/private/tmp/drf-transport-replacement-guarded-20261012-01` |
| Deployment and app-native cases separated from the main guard | 9 deployment + 4 native workflow cases | Final B012 sidecar roots below |
| Frontend | 92 tests; isolated production build passed | `/private/tmp/drf-main-frontend-build-5srizy4z/build.log` and current-turn test output |
| Fixture lint refinements | 43 passed; actor producer/consumer/parent suite separately 169 passed | `/private/tmp/drf-main-fixture-lint-green-20261012-01`; `/private/tmp/drf-main-actor-attribution-20261012-01` |
| Sidecar exception-path controls | 5 meaningful failures before repair, then 5 passed | `/private/tmp/drf-sidecar-b012-red-20261012-01`; `/private/tmp/drf-sidecar-b012-green-20261012-01` |

The combined gate binds 99 source/test files with identical before/after SHA-256 values in `integration-source-freeze.json`. Production bytes remain unchanged after that gate. Two test fixtures subsequently received explicit fixture-export aliases and a strict zip assertion; the focused 43-case gate and 169-case actor replay cover those current bytes. The end-to-end receipt independently binds 21 files, two successful guarded children, actual final audit/publication status, ten normalized binary forecasts, two surviving S1 attributions, HTTP response bytes and exported image/caption hashes.

The final sidecar is `c329cba3672d7ec23d3c8620a3667ba86de77e2c1e19485e3c53a57863079f37`. Its only change from the reviewed predecessor is worker control flow: exceptions cannot be hidden by a return from finally or a stale success record. Its three fresh complete gates are `/private/tmp/drf-sidecar-b012-deployment-final-20261012-01` (9), `/private/tmp/drf-sidecar-b012-transport-final-20261012-01` (13), and `/private/tmp/drf-sidecar-b012-integration-final-20261012-01` (4). Each requires nine boundary controls, preserved identities, cleanup/reaping, and no source drift. Original assertion bodies and native signal behavior remain intact; SIGTERM 143 is an expected scenario, not an all-child-zero claim.

## Explicit separation and baseline

Of the 15 cases separated from the combined pytest run, nine deployment and four native parent/signal scenarios passed in the reviewed macOS sandbox sidecar. The other two are existing demo-corpus checks: `test_published_ev_markdown_assets_resolve_and_match_manifest_hashes` and `test_every_published_demo_bundle_matches_its_manifest`. They fail because the baseline already deletes demo research logs and PNGs. The initial 1,955-pass/16-failure discovery receipt documents those exact failures; all 64 unrelated deletions remain absent. No test assertion was weakened or asset restored to hide this baseline.

The original 23 transport cases are partitioned 10+13 with no overlap. Repeated receipts for the same cases are not additional distinct tests. The MCP-to-publication test is separate from the broad run; its final form removes the earlier admission-only bypass entirely. The initial bypass receipt remains historical API/export isolation, not publication proof.

## Guard observations and practical limits

The main runner remains SHA-256 `53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa`. It is a CPython audit boundary for trusted tests, not an OS sandbox. The combined run completed shutdown, preserved HOME/home/CODEX_HOME/USERPROFILE, reaped all 15 registered children, and reported no source drift. One fake-server closed-stream exit 1 and the intentional no-Matplotlib exit 3 are retained in receipts; the other registered children exited zero.

Nonzero blocked attempts are explicit: four subprocess probes, twenty external reads, one socket-construction probe, ten killpg cleanup attempts and three os.kill calls. A diagnostic actor replay called the same guard record method before appending stack attribution, without altering allow/deny behavior. It passed all 169 actor cases and attributed the extra reads to Torch `/proc/self/maps` and igraph `.igraphrc`, the socket construction to urllib3 IPv6 capability detection, and the two non-font subprocess probes to CAMEL/platform `uname` and `file` discovery. The other two subprocess probes and eighteen reads are font discovery. These were denied attempts, not successful network/provider access or zero-probe evidence. Process cleanup/probe denials remain recorded. Attribution is in `/private/tmp/drf-main-actor-attribution-20261012-01/attribution.jsonl`.

The macOS sidecar uses a separately reviewed OS boundary and exact scratch copies. A fixed read-only parent broker executes `ps -o stat= -p <registered fixture PID>` because native setuid ps cannot run inside Seatbelt. That broker is outside the OS sandbox; sentinel exclusion and same-sandbox signal controls are verified. Application imports use the frozen storage redirects with inert recording and dotenv disabled before imports. This is separate evidence from CPython enforcement and does not establish live provider compatibility, forecast accuracy or production deployment.

## Static checks and preservation

Current scoped Ruff over 50 Python files has zero introduced findings. Its 71 remaining findings are byte/source-line-matched preexisting report_visualizer style warnings (66 C408 and five B905); `/private/tmp/drf-main-static-delivery-071rz5x8` stores raw findings and the empty introduced-findings list. Python AST parsing and scoped whitespace checks pass. The environment-documentation check has no missing Config knobs. Both data-source/data-visual skills pass the installed skill-creator validator; their guidance and chart-pattern reference preserve canonical statuses, fiscal labels, source identity and disable controls.

`owned-paths.json` is the explicit delivery list. The six vendor trees retain their license files and unmodified sources; ignored builds, caches, runtime/session files and credentials are excluded. A source scan of 707 newly adopted paths found no known private-key/OpenAI/GitHub token patterns. Root handoff, .zcodeignore, prior handoff/study trees and all 64 baseline deletions are preserved. Remote publication is unverified: the approved plan records rejected GitHub authentication and prohibits retrying unchanged credentials.

## Reproduction and closure

Use the exact command stored in the combined receipt, with a new nonexistent evidence directory. The end-to-end and sidecar reports record their commands and explicit script allowlists. No installs, service restarts, saved-run resumes, global identity changes or live model/provider calls are part of these gates. All substantive actor, envelope, provider/status/fiscal, promotion, resolver, generation-binding, actor-denial and publication findings have red/green evidence and independent scoped closure. Final commit identities and sidecar rereview closure will be appended here and to the authoritative handoff.

- 2026-10-11T19:50:18.391621+00:00: Euler independently closed c329 sidecar failure paths and all fresh9/13/4 receipts. The new5case fault control also passed independently. No app/provider/runner code changed after final functional acceptance. Actor/dossier fixes are committed as d48552c/6372005.

Vendor preservation check: all705 staged vendor blobs (including the original dangling .npmrc symlink) exactly match supplied working-tree bytes. Git reports 927 existing vendor whitespace/line-ending warnings; vendor sources were intentionally not reformatted. Scoped staged whitespace checks excluding datamcps pass after cleaning five owned documentation whitespace-only issues. No deletion is staged.
