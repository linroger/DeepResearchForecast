# Actor roster incoming hash fix

**Last updated (UTC):** 2026-10-11T17:13:42Z
**Status:** Complete for the bounded actor-roster incoming hash fix.
**Current focus:** Deliver fresh actor-only acceptance under lead's frozen runner; actor source and tests remain unchanged.

## 1. Request and scope

Fix only the incoming actor-roster digest mismatch on main. Owned paths are
`backend/app/services/actor_context.py`, `backend/tests/test_actor_context_runtime.py`,
the new `backend/tests/test_actor_roster_producer_consumer.py`, and this report.
Other edits, producer/parent/orchestrator code, saved data, other tests and handoffs
are outside ownership. No feature branch, commit, dependency installation, live
provider execution or saved-upload access is authorized.

## 2. Requirements and acceptance checks

| Requirement | Scenario and expected result | Evidence |
|---|---|---|
| Real producer compatibility | Persist and promote a synthetic production handoff; parent accepts it and context compilation seals every selected actor | Focused regression, red then green |
| Identity and tamper protection | Missing/duplicate/changed identities, altered hashes and a changed selected row still fail closed | Focused negative controls |
| Distinct digest contracts | Incoming full-roster multiplicity map remains distinct from the selected context manifest's ordered JSON list | Subset/order/manifest tamper checks |
| Existing behavior | Relevant context, producer and parent tests pass with mocked external dependencies | Guarded pytest receipts |
| Preservation | Only owned source/report paths are edited; branch remains main and no commits are made | Scoped diff and final status |

## 3. Plan

1. Read current producer, parent, incoming consumer, shared fixtures and dependency declarations.
2. Add regressions built with production normalization/finalization and parent reception helpers; execute before the production patch.
3. Change only the incoming roster digest recipe and align the existing runtime fixture.
4. Run focused and relevant existing checks under an existing guarded runner, review the diff and record exact evidence.

## 4. Progress ledger

- [x] Confirm main and inspect the unrelated dirty working tree; owned existing source/test files initially have no diff.
- [x] Read `handoff.md`, the integration handoff, `backend/tests/conftest.py`, `backend/pyproject.toml`, and import/path dependencies.
- [x] Trace producer canonical multiplicity-map JSON and parent `_actor_multiset_sha256` validation.
- [x] Add and capture meaningful behavioral red evidence: 7 failed, 9 passed, 0 collection/setup errors under unchanged production.
- [x] Apply the narrow production patch and obtain green evidence: all 169 selected tests pass against matching before/after source hashes.
- [x] Complete independent review with no actionable findings and record remaining evidence limitations.

## 5. Findings and decisions

The producer `normalize_actor_intelligence_contract` seals `actor_ids_sha256`
with UTF-8 JSON of ID occurrence counts, `ensure_ascii=False`, `sort_keys=True`
and compact separators. The parent independently uses that same recipe.
Incoming actor-context validation currently hashes sorted newline-joined IDs.
The context artifact manifest separately hashes an ordered selected-ID JSON list;
its build/validation recipe must remain unchanged. Existing identity, report,
count, dimensional coverage and selected-row checks must remain intact.

## 6. Issues and recovery

Main contains unrelated work that must be
preserved. Lead explicitly instructed this worker to hold test execution until
a main-scoped safe runner is provided, and excluded all Finharness source,
including its runner. That instruction supersedes the initially proposed runner.
The previous runner review is historical preparation only: it was never executed
for this task, will not be reused, and must not be treated as verification evidence.
Lead subsequently provided `backend/scripts/main_offline_pytest.py` after its
controls passed. It was reviewed and used with `-I -S -B`. The execution hold is
lifted. Its isolation preserves identity, redirects storage before imports,
denies saved-data reads/writes, excludes forbidden worktree sources, and denies
all subprocess and network operations in this initial CLI.

## 7. Scenario-focused verification

`backend/tests/test_actor_roster_producer_consumer.py` constructs synthetic local
evidence using the existing parent's source/claim/dossier fixture inputs, then
invokes real `persist_final_actor_intelligence_contract`, dossier coverage audit,
handoff promotion and full parent reception. It exercises both producer roster
orders, all selected contexts, subset/reversed selection, identity/hash/report/
count tampering and the separate manifest digest. Both owned test modules
explicitly mock LLM and HTTP/DNS/connection entry points to reject external calls.
All generated output uses pytest temporary paths. No research engine, server,
provider, graph service or saved run is launched.

## 8. Safe execution and evidence

**Historical proposal:** The commands below were prepared during the execution
hold; the actual approved main-runner commands and outcomes follow them.

```sh
DRF_TEST_PROCESS=1 /Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -B "$MAIN_SAFE_RUNNER" \
  --evidence-dir /tmp/drf-actor-roster-red-20261012 \
  -q backend/tests/test_actor_roster_producer_consumer.py

# Only after the behavioral red is recorded and incoming validation is patched:
DRF_TEST_PROCESS=1 /Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -B "$MAIN_SAFE_RUNNER" \
  --evidence-dir /tmp/drf-actor-roster-green-20261012 \
  -q backend/tests/test_actor_roster_producer_consumer.py \
  backend/tests/test_actor_context_runtime.py \
  backend/tests/test_actor_intelligence_producer.py \
  backend/tests/test_pipeline_actor_contract.py
```

Required boundary: isolated temp application/log/cache/pytest roots before app
imports; no ambient dotenv/provider configuration, network, services or saved
uploads; no dependency resolution. Preserve HOME/home/CODEX_HOME/USERPROFILE.
Existing runtime OASIS construction may attempt optional tokenizer vocabulary
downloads; this dependency must use a main-scoped local fixture or an explicitly
documented exclusion before that test runs. This is not related to roster digest
semantics and must not be mistaken for behavioral red evidence.

### Actual red evidence

Executed from the main repository root before the production patch:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-main-actor-red-20261012-01 \
  -q backend/tests/test_actor_roster_producer_consumer.py
```

Exit 1; JUnit reports **16 tests, 7 failures, 9 passes, 0 errors, 0 skips** in
1.06 seconds. Both real producer roster orders pass full parent reception and
then fail at incoming context validation with `actor intelligence actor roster
fingerprint mismatch`. Both selected-manifest cases fail at that same premature
check. The legacy newline digest case incorrectly raises no exception. The
selected-actor/count controls are preempted by the bad incoming digest. This is
behavioral red, not fixture setup or collection failure.

Receipts: [completed.json](/private/tmp/drf-main-actor-red-20261012-01/completed.json),
[JUnit](/private/tmp/drf-main-actor-red-20261012-01/junit.xml), and
[events](/private/tmp/drf-main-actor-red-20261012-01/events-46232.jsonl).
Identity preservation is true. There were **32 blocked file-descriptor path
operations**, separately from the test failures, and no recorded network,
subprocess, saved-data, credential or external-write attempts. The initial guard
rejects descriptor-relative traversal; production promotion uses two best-effort
`shutil.rmtree(..., ignore_errors=True)` cleanup calls per synthetic bundle.
The 32-count matches those two cleanup calls across 16 cases; exact attribution
is still pending a trace or an improved runner receipt. No guard was relaxed.

Frozen red SHA-256 values:

| Source | SHA-256 |
|---|---|
| actor_context.py | ff9dd29047c139edca8b46bbda74eecdfe2dc2329e425ad9822d6023e188e024 |
| test_actor_context_runtime.py | bdb2570a9803554ed7180a0e78f975573ac4ae4a0bc35072b0a92557090b354d |
| test_actor_roster_producer_consumer.py | a1fcfe5c5b7f21ba7a21f2d43214294c2175bd01a5ae51057e67a10fb5c4fca2 |
| pipeline_orchestrator.py | bdc1c33e31320e1cf2a870663bcb1981f9f707fc967371d306ffbd3a5058a7a9 |
| deerflow_research.py | abef7d74ca76ae28b68f5b69dd9fe526191c1e8113e37176da635b77865f2674 |
| conftest.py | 1fcc05fc9b39ae8bddd8beed78c92f49ea9eded8794b6fa13a9126017512cfba |
| main_offline_pytest.py | c3f14266188fcb7a8a460e378889af7063555c261f6ee4ca84bf29630eb38ace |

After inspecting red, changed only the incoming digest recipe to
`canonical_json_sha256({actor_id: actor_ids.count(actor_id) for actor_id in actor_ids})`.
All preceding identity/duplicate checks and subsequent count/report/coverage
checks remain unchanged. Manifest list hashing and artifact validation are unchanged.

### Initial green results and fixture correction

Focused run, same command with evidence root
`/private/tmp/drf-main-actor-green-focused-20261012-01`: **16 passed** in 1.06s,
exit 0. Completion/events/JUnit were inspected; identity preserved; **32 blocked
file-descriptor path operations**, with no recorded network/process/saved-data/
credential/external-write attempts. All producer-to-context and negative controls
are now green under the narrow production patch.

Existing suites were then run with:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-main-actor-green-existing-20261012-01 \
  -q backend/tests/test_actor_context_runtime.py \
  backend/tests/test_actor_intelligence_producer.py \
  backend/tests/test_pipeline_actor_contract.py
```

Result: **152 passed, 1 failed**, exit 1, 7.16s. The OASIS system-message fixture
imports a dependency that creates `./log/social.twitter-*.log`; the guard blocked
that repository write before agent construction. This is a test-fixture isolation
defect, not a roster regression. Changed only that owned test to chdir into its
pytest temporary directory before OASIS imports. Added an in-memory byte tokenizer
to keep real OASIS agent construction offline; actual tokenizer-vocabulary quality
is outside this scenario, whose assertions concern real system-message content.
No production dependency or guard was changed. The raw failed-run receipt and
JUnit remain preserved at the evidence root; final acceptance awaits rerun.

### Final green acceptance

Executed from `/Users/rogerlin/Downloads/DeepResearchForecast`:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-main-actor-green-final-20261012-02 \
  -q backend/tests/test_actor_roster_producer_consumer.py \
  backend/tests/test_actor_context_runtime.py \
  backend/tests/test_actor_intelligence_producer.py \
  backend/tests/test_pipeline_actor_contract.py
```

**Exit 0; 169 passed in 10.76s; 0 failures, 0 errors, 0 skips.** JUnit counts:

| Module | Passed |
|---|---:|
| test_actor_roster_producer_consumer.py | 16 |
| test_actor_context_runtime.py | 27 |
| test_actor_intelligence_producer.py | 63 |
| test_pipeline_actor_contract.py | 63 |

Inspected [completion receipt](/private/tmp/drf-main-actor-green-final-20261012-02/completed.json),
[JUnit](/private/tmp/drf-main-actor-green-final-20261012-02/junit.xml), and
[raw events](/private/tmp/drf-main-actor-green-final-20261012-02/events-53560.jsonl).
Raw event totals exactly match the completion receipt. `identity_preserved` is
true and the child-script allowlist is empty.

Blocked attempts are separate from the passing test result:

| Guard event | Count | Observed detail |
|---|---:|---|
| External read | 20 | `/proc/self/maps`, optional font lookup directories, and `.igraphrc` |
| Socket creation | 1 | `socket.__new__` denied before a transport was created; individual caller not traced |
| Subprocess | 4 | `uname`, one `unregistered-executable`, `fc-list`, `system_profiler`; all denied |
| Saved data / credentials / external writes / descriptor cleanup | 0 | No such events in final raw logs or receipt |

These denied import/discovery operations are not successful provider calls or a
zero-attempt claim. The tests explicitly mock LLM/HTTP/DNS/connection entry points;
no live provider, saved upload or permitted child process is exercised. Exact
call-site attribution for the socket constructor and unnamed executable remains
outside this fix. The byte-only tokenizer verifies real role-prompt propagation
and provenance, not production BPE vocabulary or token-budget accuracy.

Eleven relevant source/test/runner files were hashed immediately before and after
the final run. The [before snapshot](/private/tmp/drf-main-actor-final-20261012-02.before.sha256)
and [after snapshot](/private/tmp/drf-main-actor-final-20261012-02.after.sha256)
match exactly (`diff -u` exit 0). Final actor-owned hashes:

| Source | SHA-256 |
|---|---|
| actor_context.py | 17f12e5ba2b8f02309ab3ba65a08ee14afe93383217e5707ccf941efea1a0dbf |
| test_actor_context_runtime.py | df194583e8e645dc29767fac8a6feddaeb0aab08c8863f8896f0da6e839da756 |
| test_actor_roster_producer_consumer.py | 33ca61e1ee935ad37696fdd29bc03767ca4fbd7fa8f6075b8d7a9e1de66d11f2 |

Other authorized workers changed producer, parent and runner bytes during earlier
runs; those edits were preserved. The first full run (`green-all-...-01`) passed
169 tests in 7.75s. A subsequent run (`green-final-...-01`) passed 169 in 10.39s,
but its parent-source before/after hash changed. Both are historical supporting
evidence only; `green-final-...-02` is the stable-source acceptance run. Its runner
hash is `862b5279d3d096b980b850a0b5d9e89c30e7acfb7fdca494cea923e60de04e2f`,
parent hash is `84a667504f64d4067a1eef1e3dd4efab9442a26245d35c001e5eec6ef6b404c3`,
and producer hash is `8a339e3e988508a30eb35febef8d3525e90aeebbb1b647a7e009a6782f44f131`.

### Review and preservation

Independent read-only reviewer Kant (`01a12be7-0a98-7601-b8e1-d78f283bc69d`)
returned **no actionable findings**. It confirmed producer/parent JSON parity,
unchanged missing/duplicate/report/count/schema/coverage/selected-row checks,
separate selected-list manifest hashing, and preserved real OASIS prompt and
provenance assertions with the offline fixture. The reviewer inspected current
main references after concurrent producer edits; no forbidden worktree or runner
was used. The reviewer made no edits or executions.

Only the four owned paths were edited by this worker. No producer, parent,
orchestrator, shared fixture, saved-data or other handoff changes were made by
this worker. Main remains the active branch; nothing was staged or committed.

## 9. Remaining work and next-session prompt

No actor-roster implementation work remains. The required ordering was satisfied:
meaningful red preceded the production patch, and final green covers stable
reviewed actor-owned bytes. Guard-call attribution and production tokenizer/live
provider behavior are explicit evidence limits, not unimplemented roster work.

**Historical execution hold (2026-10-11T17:11:09Z):** Lead instructed all workers to
hold new guarded runs while the runner owner repairs syntax and freezes validated
bytes. Existing completed receipts remain historical evidence for their recorded
source hashes; they do not establish the current runner's state. Lead's report2
pre-import test block is not an executed test failure and is not added to this
fix's failure counts. This worker launched no new test/app process during the
hold. Read-only self-review reconfirmed the incoming-only diff, unchanged identity
checks and distinct manifest list hashing; tracked whitespace checks remain clean.
No actor code or regression changes were needed. Lead lifted this hold with the
validated frozen runner described below.

### Latest acceptance with lead's frozen runner

Lead provided runner SHA-256
`53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa`
after 15/15 controls. Verified that exact local hash before launching only the
four implemented actor suites; no partial data-source client APIs were tested.

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-main-actor-frozen-green-20261012-01 \
  -q backend/tests/test_actor_roster_producer_consumer.py \
  backend/tests/test_actor_context_runtime.py \
  backend/tests/test_actor_intelligence_producer.py \
  backend/tests/test_pipeline_actor_contract.py
```

**169 passed in 12.59s; exit 0; zero failures, errors or skips.** Module counts
remain 16 focused + 27 context runtime + 63 producer + 63 parent. No dependency
setup errors occurred. Inspected [completed.json](/private/tmp/drf-main-actor-frozen-green-20261012-01/completed.json),
[JUnit](/private/tmp/drf-main-actor-frozen-green-20261012-01/junit.xml) and
[raw events](/private/tmp/drf-main-actor-frozen-green-20261012-01/events-62131.jsonl).
`source_drift=[]`, `identity_preserved=true`, `shutdown_complete=true`, no child
scripts registered, and no children launched. Raw events exactly match receipt
totals: 20 blocked external reads (18 explicitly classified font-discovery probes,
plus `/proc/self/maps` and `.igraphrc`), one blocked socket constructor, four
blocked subprocesses (`uname`, unregistered executable, `fc-list`,
`system_profiler`). These are denied attempts, not successful network/process
activity or a zero-probe claim. No saved-data/credential/external-write blocks
were recorded. Existing attribution/tokenizer limits above still apply.

All eleven [before hashes](/private/tmp/drf-main-actor-frozen-20261012-01.before.sha256)
and [after hashes](/private/tmp/drf-main-actor-frozen-20261012-01.after.sha256)
match (`diff -u` exit 0). Actor-owned code/test hashes are unchanged from the
reviewed table above. The current producer hash for this run is
`3e90cf2fa0b272bf0be34b9586ed6a1f26c540e29bb94613797b1e0ff44b08a2`;
the full snapshots bind the parent and remaining test/import dependencies too.
This is the latest acceptance receipt; earlier completed runs remain historical.

Continuation prompt: "Read actor-fix.md and retain the scoped incoming JSON
multiplicity-map digest fix. Its 169-test stable-source receipt is
/private/tmp/drf-main-actor-green-final-20261012-02. Preserve other owners' changes;
do not merge this acceptance claim with the broader data integration. No actor
fix commit or branch was created."

## 10. Updates

- 2026-10-11T16:41:49Z: Created the owned continuity report with contract findings, acceptance checks and reviewed execution boundary before writing tests or production code.
- 2026-10-12 Asia/Shanghai: Lead explicitly excluded Finharness source and instructed a test-execution hold pending a main-scoped runner. Authored producer-to-parent-to-context regressions and aligned the existing runtime fixture to the real JSON multiplicity-map contract. Added explicit external-call mocks in both owned test modules. No tests or production patches have been executed/applied.
- 2026-10-11T16:56 UTC: Lead provided the main-scoped runner. Captured meaningful 7-failure/9-pass red under unchanged production, inspected completion/events/JUnit, recorded blocked operations separately, and applied the incoming-only multiplicity-map digest patch.
- 2026-10-11T16:59 UTC: Focused 16-test suite passed. Existing suites yielded 152 passes and one OASIS relative-log isolation failure. Corrected only the owned test's working directory and tokenizer dependency before a full rerun; no guard weakening or production scope expansion.
- 2026-10-11T17:03:08Z: Final 169-test run passed with all eleven before/after hashes identical, exact raw/receipt event reconciliation, preserved system identity and separately reported blocked probes. Recorded independent no-findings review and marked only this bounded bug fix complete.
- 2026-10-11T17:11:09Z: Recorded lead's new runner-repair execution hold. Continued read-only code/assertion review, retained the actor patch unchanged, and labeled prior receipts historical; report2's pre-import block is not counted as an executed failure.
- 2026-10-11T17:13:42Z: Verified lead's frozen runner hash 53a2cd41..., then reran only implemented actor suites: 169 passed, no setup errors, source_drift empty, shutdown and identity true, all eleven before/after hashes equal. Updated current receipt and blocked-attempt evidence without changing actor code/tests.
