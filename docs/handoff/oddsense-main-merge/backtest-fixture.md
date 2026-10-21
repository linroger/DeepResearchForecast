# Backtest child fixture handoff

**Status:** Complete for this fixture slice; parent merge acceptance and delivery remain separate.
**Current focus:** Return the exact reviewed fixture bytes and guarded evidence to the parent.
**Latest acceptance:** Final mirror `drf-oddsense-merge-backtest-final-20261021-72geo903`, evidence `drf-oddsense-merge-backtest-final-20261021-1`: **24 passed in 4.57 seconds**, including the peer-updated bridge. Earlier candidate receipts below remain historical.

## Request and boundaries

The parent authorized a narrow repair of `backend/tests/test_backtest_pipeline.py` on `codex/merge-oddsense`, merging main `15c8453` and Oddsense `7c98895`. This note is the only other owned file. Preserve every other owner's work. Do not mutate Git, production application code, the guard, the primary checkout, deployment, credentials, or network configuration. Private source mirrors and verification receipts are authorized.

## Requirements and acceptance checks

| Requirement | Scenario and expected result | Evidence |
|---|---|---|
| Preserve actual child spawning | The real pipeline and research runner launch an explicitly registered named fixture script in a different guarded process. | Parent/child receipts and fixture outputs. |
| Preserve backtest policy | The original parent-owned environment and resolved policy reach the bridge; pinned cutoff, audit file, dropped late sources, and research-only market flag remain asserted. | Existing cutoff test, child environment, metadata, audit and sources. |
| Preserve live policy isolation | The live child does not inherit an ambient backtest policy and retains its intended market flag. | Existing live-child test and child environment. |
| Keep the guard unchanged | Run the full module under current `main_offline_pytest.py` in a new private mirror, with exact source hashes and no guard weakening or assertion bypass. | Source manifest, completion/JUnit and process receipts, before/after hashes. |

## Plan and progress

1. Read the merge handoff, offline verification skill, current guard API, named-script examples, and original failing evidence. This is complete.
2. Adapt only the fixture's named script and any necessary explicit test-input carrier. Keep production runner spawning and the bridge's original resolved policy. Complete.
3. Verify the full module through the unchanged guard in a fresh mirror; inspect shutdown, identity, child exits, guard events and source drift. Complete: 24 passed, zero failures/errors/skips.
4. Record exact ready bytes and receipts for the parent. Complete below. Leave integration, commits and broader acceptance with the parent.

## Findings and decisions

- The guard already exposes `sys.modules['main_offline_guard'].allow_python_script(path)` and hashes the exact named script before spawning it with isolated startup and a child audit boundary.
- The child bootstrap deliberately resets `PREDICTION_MARKETS_ENABLED` to `false`; registration alone cannot preserve the live-child environment assertion. Any fixture carrier must retain the actual runner-supplied value as a test input, without altering guard permissions or inventing a policy.
- The retained broad red evidence is `/private/tmp/drf-oddsense-merge-first-20261021-1`. Historical results do not establish acceptance of this repair.

## Verification and remaining work

The fresh baseline mirror `/private/tmp/drf-oddsense-merge-backtest-baseline-20261021-qc481s32` reproduced 22 passes and the two reported child failures under `/private/tmp/drf-oddsense-merge-backtest-red-20261021-1`. Both failures are unregistered-script admission, before the child writes its environment. No repaired-source test result is claimed yet.

The candidate registers the generated script through the existing API and delegates the real runner's unmodified command/process options to the captured installed Popen. A single explicit synthetic environment alias carries the runner's actual market flag past the guard's deliberate bootstrap default; it grants no permissions. The child leaves `DRF_BACKTEST_POLICY` untouched, calls the original policy resolver and returns its result unchanged. It records the observed environment, process identity and resolved policy; the parent verifies exact environment equality, a different PID, real guard installation and completed clean child receipts.

Per the user's steering, `Config.NEWS_CONTEXT_ENABLED=False` isolates these unrelated spawn/environment cases from the merged default's keyless live-market prefetch. The original cutoff, strictness, audit, late-source rejection and live-policy assertions remain in place. Parent-owned real-engine and live-context end-to-end cases cover context separately.

The candidate mirror is `/private/tmp/drf-oddsense-merge-backtest-candidate-20261021-oz8qbhnl`. Its manifest records 2,441 copied source files; rehashing found zero mirror drift. All 146 selected production/bridge/fixture/guard Python files also matched the live worktree after acceptance. An AST comparison confirms every one of the 13 original test functions (24 parameterized cases) is unchanged. The edited module and generated shim parse successfully. `ruff check --no-cache backend/tests/test_backtest_pipeline.py` also exits 0 with “All checks passed!”

### Exact acceptance command and outcome

Working directory: `/private/tmp/drf-oddsense-merge-backtest-candidate-20261021-oz8qbhnl`.

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B \
  backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-oddsense-merge-backtest-candidate-20261021-1 \
  -q backend/tests/test_backtest_pipeline.py
```

The process exited 0: **24 passed in 4.56 seconds**, with zero failures, errors or skips. Parent PID 17626 admitted exactly two hashed guarded scripts; child PIDs 17690 and 17692 exited 0. All three receipts record completed shutdown, preserved identity and zero source drift. Aggregating all three process receipts gives only three occurrences each of the existing config/logger/simulation storage redirects, plus two `allowed:guarded_child` events. There are **zero blocked events**, including zero recorded network, credential, external-read, external-write or denied-process attempts. This is CPython audit evidence, not an OS sandbox claim.

The backtest child records the actual resolved `backtest/v1` policy with cutoff `2024-11-01`, strict mode and the actual handoff audit path; the parent environment equals the child's observed environment. Its metadata records 12 dropped after-cutoff search hits, 36 kept before-cutoff hits and four kept fetches. The original nonempty sources/no-`late.example` assertion passes. The live child records a null resolved policy, no `DRF_BACKTEST_POLICY` and market flag `true`, despite the test's ambient backtest value. Both actual bridge runs complete and produce reports and sources.

Independent read-only review by Dirac found no actionable findings. It verified named-script registration, forwarding to guarded Popen, unchanged original policy return, retained assertions and explicit context disablement. The reviewer did static inspection only; runtime conclusions above come from the captured receipts.

### Ready bytes and artifact index

The owned test file is 17,797 bytes, SHA-256 `8417ea8ae2a1ab9492da37d6b6133ac1289e35907627bd1dd726d4379498dd78`. The tested mirror, live worktree and private ready copy are byte-identical. The unchanged guard SHA-256 is `8c8bb8f6c0e4e5decee8f167603a4eb47711ec562e028d19f9d3d6bee1741815`, matching baseline, candidate and worktree. The production pipeline orchestrator and bridge sources also match baseline; this fixture repair does not modify them.

Evidence directory: `/private/tmp/drf-oddsense-merge-backtest-candidate-20261021-1`.

| Artifact | SHA-256 |
|---|---|
| `completed.json` and `process-17626.json` | `5584f846776041f98593c8a5d88771f8b2e2fb4db2a9799a10432c2025d9adb5` |
| `process-17690.json` (backtest child) | `f0ca15f86a9e00ac620daed1d7a335593e82c2782668a5ece6b96e719d688d44` |
| `process-17692.json` (live child) | `0222291e78aac56b3d768ec8d66e8719b0aad445d95fafe6c5cae1060955731d` |
| `junit.xml` | `3f8742070415a65af09f3b23f9716a4e4fab1a9f3eeb5937a8d87f2351622aef` |
| `verification.json` (source comparisons, original-test preservation, aggregate events and child-output hashes) | `0b0c57f44ba7b7434208430c8fdbf0a4bcabe1848431a7443a2fb47ecc11e286` |
| Mirror `oddsense-source-manifest.json` | `08f9dc99486eef15090a273807a22456bdf4ae50f705341c02d5b778d1b688ed` |

`ready-test_backtest_pipeline.py` preserves the exact tested bytes, and `backtest-fixture.patch` contains the scoped diff against the retained baseline. Child-owned `child_env.json`, `child_process.json`, `meta.json`, `sources.json`, reports and the backtest audit remain under each corresponding `pytest-tmp/.../pipelines/pipe_{backtest,live}child/handoff` directory; their paths and hashes are in `verification.json`.

### Final acceptance after the peer bridge update

The same unchanged fixture and guard were verified again from fresh mirror `/private/tmp/drf-oddsense-merge-backtest-final-20261021-72geo903`, with `linear_research.py` SHA-256 `f14bb1fcc831c233859a02b4cb045af2203b381a557e5669383d15f840f68986`. Use the command above from this final mirror, replacing the evidence destination with `/private/tmp/drf-oddsense-merge-backtest-final-20261021-1`.

The final run exited 0 with **24 passed in 4.57 seconds**, zero failures/errors/skips. Parent PID 22379 admitted backtest child 22440 and live child 22441, both exiting 0. All three final receipts show completed shutdown, preserved identity and zero source drift. Aggregate events again contain only three occurrences each of the storage redirects and two admitted guarded children: zero recorded blocked or network attempts. The same cutoff/strict/audit and original environment assertions pass; the backtest again drops 12 late search hits. Both runs produce six final source records and nonempty reports. All 146 selected current Python sources matched the final mirror at receipt reconciliation, and its 2,441-file manifest rehashed without drift.

The final evidence directory contains a byte-identical `ready-test_backtest_pipeline.py`, a scoped `backtest-fixture.patch`, complete child outputs and the following receipts:

| Final artifact | SHA-256 |
|---|---|
| `completed.json` and `process-22379.json` | `c2c0a1963272eefc0b56620d249f943e3526b31889d65dda9acaad90cddfca68` |
| `process-22440.json` | `f6a72802e46500638b4691fee43d657f87de492632c91554bc66e530dc6e2f31` |
| `process-22441.json` | `485b7ddbd24ae0a339fced4d8d6a357396771adf05e463c012b3d1b1ed32cf0e` |
| `junit.xml` | `3f13a0a0221486fe5a9b02224a5b27c1b5ffa4adc137d2272e063b760dad7db6` |
| `verification.json` | `40982d07fb52ddb90beb4821b812c5d6edae999e273ecf84528967572b741b0c` |
| Final mirror `oddsense-source-manifest.json` | `5a8161d8b62f354eaa051d9ae1a2b99d60db36ee88ab687ad4258e0896bbb0f9` |

### Remaining work and next-session prompt

No fixture-slice blocker remains. The parent retains ownership of broad merged-code acceptance, independent production review and any Git delivery. No commit, push, runtime/deployment/provider action or other owner's edit was performed here. This focused result does not claim broader merge completion or live-context/provider behavior.

> Continue the approved Oddsense merge in `/Users/rogerlin/.codex/worktrees/forecast-feedback/DeepResearchForecast` on `codex/merge-oddsense`. Preserve peer work. The backtest fixture slice is ready at SHA-256 `8417ea8ae2a1ab9492da37d6b6133ac1289e35907627bd1dd726d4379498dd78`; its full module passed 24 cases through the unchanged guard with two successful child receipts and zero recorded denied or network attempts, including the peer bridge update. Read this note and `/private/tmp/drf-oddsense-merge-backtest-final-20261021-1/verification.json`, compare hashes, then include these bytes in the parent's fresh combined verification. Keep the separate real-engine backtest context and native-shaped live-context end-to-end coverage.

## Updates

- 2026-10-21: Created this scoped continuity record before changing the fixture. Read the current merge plan and handoff and confirmed branch and ownership boundaries.
- 2026-10-21: Captured the two-case baseline failure; implemented named-script registration, the explicit market-flag carrier, original-resolver observation and child receipts. Applied the user's context-off fixture constraint.
- 2026-10-21: Recorded fresh 24-case guarded acceptance, parent and two child receipts, zero recorded blocked events, exact source hashes and original-test AST preservation. Independent static review found no actionable findings. Prepared private ready bytes and a scoped patch for the parent; marked this fixture slice complete.
- 2026-10-21: A later final rehash detected another owner's `linear_research.py` changing from tested `8a0be15b869a175bf885ff1c96a8e77809bdb4c06426edcd0a3b9914750cf739` to `f14bb1fcc831c233859a02b4cb045af2203b381a557e5669383d15f840f68986`. The fixture, guard and candidate artifacts are unchanged; the 24-case result above remains valid for its frozen candidate only. Preparing a fresh mirror to verify the updated bridge without editing peer source.
- 2026-10-21: Final fresh mirror with the peer-updated bridge passed all 24 cases in 4.57 seconds. Recorded final parent/child receipts and hashes, rechecked all 146 selected current Python sources and 2,441 frozen files, and updated the parent's continuation prompt to the final evidence.
