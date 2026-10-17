# V3 response-shape clarification

Status: the approved prompt-only [plan](PLANS.md) is implemented and frozen; the supplied 486-case guarded closure receipt has been independently verified. The coordinator reports exact-source review closed and phase16 active under a source freeze. No phase16 outcome is claimed.

Ownership is limited to `_REVIEW_SYSTEM_V3` and `_REVIEW_ERROR_SYSTEM` in `backend/app/services/world_simulation/policy.py`, at most two appended SDK wire cases in `backend/tests/test_world_consistency_v3_policy.py`, and this new note. The accepted parent-folder policy note remains untouched. The source baseline is policy SHA-256 `934fcf3a2d30371d2d465302b615c1c256c2cb4a2bc6a1edc74c7f6d6e702683` and test SHA-256 `19f7320fb8b36a9053d89c41d63b9e7417c3b7ffd6f02469fe348eaca092f32e`.

The change adds a neutral schematic outer/check layout with explicitly non-output metavariables, an exact key/type/array audit independent of semantic verdicts, and an instruction placing assessment reasoning in each check's bounded explanation string. It explicitly preserves permitted decision rationale and state updates. The repair suffix repeats the complete decision/assessment envelope and forbids echoing the error context. No action or verdict is supplied as a default.

The parent reported phase15 closed with eight qualitative passes and four known schema rejections, exposure US$0.103072, and US$20.146455044336 remaining under the approved total US$40. Offending output keys were not retained; this change addresses observed prompt usability gaps without asserting their causal role in those failures. Historical results and gates remain unchanged.

Two actual-SDK/mock-HTTP wire cases were appended, one for a valid candidate and one for error-context review. They assert the schematic layout, exact key/type/array guidance, bounded explanation placement, continued allowance of decision rationale/state updates, and the repair envelope/no-echo instruction. They also verify the exact original observation and review input, complete byte reservation, one dispatch per call, known usage and unchanged unknown/inconsistent verdicts. The fixture responses do not prove that a live model will follow the prompt. These cases are authored but not executed by this worker; the parent owns execution. Existing malformed-schema, legacy-wire, controller and store checks remain unchanged.

Static verification passed: both Python files parse with `ast.parse`; the test file has 39 statically counted cases (37 existing plus two appended), with no duplicate test names or imported-fixture parameter shadowing; scoped whitespace checks are clean. Removing the two allowed prompt-constant regions from baseline and current source produces exactly equal remaining bytes. The original 37 test cases remain byte-for-byte intact. The accepted `../policy.md` hash remains `04346adc2c8e3d991a00c5f6e5fc262c18815390327a4b2e88245903312a8434`; that file was not edited.

Frozen SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `backend/app/services/world_simulation/policy.py` | `4ab43abf110ad9cf70aed77a0b627bf8950c7c12f4fc41c967e4c44ea0af5030` |
| `backend/tests/test_world_consistency_v3_policy.py` | `69debc3b7d9541945a0799e0dc9713f9dacf0c3da4ab988dc01ca2480b08a2de` |

The parent was notified of this freeze for guarded runtime verification and exact-source rereview. No application imports, test execution, provider calls, commits or delegation were performed by this worker. Earlier gates apply to their recorded historical hashes, not this prompt change. Full behavior acceptance and default promotion remain outside this slice.

## Guarded runtime closure

Independently inspected the supplied artifacts under `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-v3-shape-clarification-20261017T162023Z-ec9k_jy6/evidence`. The [JUnit receipt](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-v3-shape-clarification-20261017T162023Z-ec9k_jy6/evidence/junit.xml) records 486 tests with zero failures, errors or skips; the console reports 486 passed in 7.31 seconds. Coverage includes all 39 v3 SDK cases (including the two new shape cases), 216 original policy cases, prior v1/v2 review checks, consistency controller/store checks, and current candidate-repair controller/store and v3 checks.

The [verification summary](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-v3-shape-clarification-20261017T162023Z-ec9k_jy6/verification-summary.json) reports exit code zero and no source drift across 545 files. Both owned Python files match their source-manifest entries, frozen copies and current hashes listed above. `completed.json` confirms successful shutdown; guard counters record three storage redirects and two blocked subprocess attempts. Its stated boundary is CPython audit hooks, not an OS sandbox.

This verifies the bounded prompt change against the current affected scopes. The coordinator's earlier 1399-pass broad gate remains separate historical evidence; these run counts are not summed or represented as a fresh broad rerun. No source/test correction was needed, and this receipt update changes only this note. Exact-source independent review was pending at that receipt update; the subsequent coordinator-reported closure is recorded below. No live behavior improvement, full-study success or default promotion is claimed.

## Exact-source review closure and phase16 freeze

The coordinator subsequently reported exact-source review closed and launched phase16 in session `41294`, with output at `/private/tmp/drf-world-consistency-v3-shape-20261017` and manifest SHA-256 `2d8b56a742a7fed14a43743ce8faf84b7fe88380c8f0113c81f8b183f232e7a5`. The launch notice reports 459 prior artifacts and 545 source files verified. These launch/review statements are attributed to the coordinator; this worker did not inspect in-flight artifacts. A local read-only hash check confirms that the policy and test files still match the frozen values above.

Phase16 is limited to 12 fixed calls and at most US$1.25 within the approved total US$40, with US$20.146455044336 remaining at launch as reported by the coordinator. Source, tests and pricing remain frozen until closure. The independent qualitative review must wait for completion. This worker performs no provider calls, runtime tests or in-flight outcome inspection; only this scoped note was updated.

The separately tested full36 manifest and its US$18 cap do not authorize that run. No phase16 result, full-study success or default-promotion claim is made here. Await the parent's phase closure and reconciled receipt before further work.

Updates:

- 2026-10-18: Read the approved plan, captured frozen policy/test baselines, and implemented only the two permitted prompt-constant additions.
- 2026-10-18: Appended exactly two SDK wire cases, verified static source isolation and preservation of prior tests/history, and sent the frozen policy/test hashes to the parent. Stopped for the guarded gate and independent rereview.
- 2026-10-18: Verified the 486-pass/7.31-second guarded receipt, zero failures/errors/skips, no source drift across 545 files and matching current/frozen policy/test hashes. Updated only this note; exact-source independent rereview remains pending before phase16.
- 2026-10-18: Recorded the coordinator-reported exact-source review closure and phase16 launch/freeze, including the fixed-call budget and manifest identity. Reconfirmed local policy/test hashes unchanged; did not inspect live artifacts or claim an outcome.
