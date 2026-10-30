# Parent budget completion regression

Last updated: 2026-10-30. Branch: `codex/world-anchor`, base `9916b3be`. Status: Complete for the assigned regression. Stable behavioral red and final green are retained; production remediation belongs to the parent.

## Request and acceptance criteria

Own only `backend/tests/test_world_anchor_budget_completion.py` and this note. Reproduce PR1 at the parent completion boundary using real spending authorization, pipeline admission, database scope transitions, retained dispatch accounting, sealed budget receipts, authenticated producer handles, immutable publication, and host handoff adoption. A valid current zero-call completion must succeed before checking rollback rejection. Record a both-bundles case at the pure boundary if its retained floor rejects it there, and cover any older selected bundle that the pure layer still permits.

Production changes belong to the parent. Do not change existing tests, reset spending core state, weaken the offline guard, call providers, commit, or delegate. Application imports and execution use only `backend/scripts/main_offline_pytest.py`.

## Plan and progress

The test reuses the existing admission `prepared` context, which holds the real run lock, and the existing `runtime` fixture, which parks the worker thread. It does not import the optional spending reset fixture. It builds a no-contract source snapshot with the actual pipeline ID before rebuilding its requirements and evidence index. Each authenticated producer handle wraps the unmodified ledger budget seal and a summary derived from its exact counters.

Real entry and exit packets are the sole expected-completion source. The production parent adapter adopts them while the pipeline lifecycle remains pending. Acceptance controls load actual saved host state, so accepting the valid control does not reset the working pending state. The initial behavioral failure was reported to the parent before host enforcement was applied. The final test is unchanged from that red run.

One test deliberately exercises all scenarios under one authorization and one real pipeline start. Run this test in its own fresh guarded process: it never resets the core's process-wide authorization, sticky-required flag, context, or admission state. The copied context represents an independent producer descriptor for the same process and ledger. This test does not establish actual child-process handoff behavior.

## Findings and decisions

The pure layer rejects a selected older summary when another attached receipt retains larger counters. It still admits older receipts with the same counters, because session identity is a separate parent completion condition. The initial parent `accept_completion` implementation did not join its selected budget to the ledger-authenticated exit seal. The first run reached its final assertion and reported both prohibited acceptances, after the valid current zero-call control had already succeeded.

The parent subsequently wired its publication validation helper into host completion and persisted the exact authenticated completion in `options.world_anchor_scope_completion` during adoption. The lifecycle schema stayed unchanged. No production code was edited by this owner.

| Scenario | Exercised boundary and observed final result |
|---|---|
| Current zero-call scope, exact budget and publication | Real scope entry, seal, publication, exit, adoption and saved-state reload; host accepts and marks the loaded state ready. |
| Both bundles retain zero counters, but the pack selects the older session | Pure admission and publication succeed. The current session exits with its actual budget hash; host rejects with `anchor_artifact_invalid` and leaves the loaded state pending. |
| Both bundles retain different counters after one fake dispatch | Pure `admit_bindings` rejects the older selected meter with `E_BUDGET_RECEIPT` at `stale_metering`, before publication. Selecting the current meter succeeds at that same pure boundary. |
| Old-only publication after one retained fake dispatch | The ledger exits successfully using its current budget seal and the old publication manifest. Parent adoption authenticates those real transitions; host rejects the selected old budget with `anchor_artifact_invalid` and stays pending. |

The dispatch callback observes its already-retained debit before returning its fake response. The final ledger has exactly one attempt. Budget values, limits, session identity and hashes come from `seal_anchor_budget`; the test does not invent those values or write completion authority directly into options.

## Verification

The owned test SHA-256 is `dce4a033deb488bfc4ee4e8d62d2ec4c2e2ed5d1be2abec3d0e87f128b688608` in all three runs. Each evidence directory includes stdout, the original runner completion and JUnit files, closed-run SQLite/fixture evidence, exact pre-run copies of 14 direct source/test/runner dependencies, before/after hashes, the command receipt, and a verified copy manifest. All 59 regular runner files were copied and compared byte for byte. Two internal pytest convenience symlinks were omitted and recorded; their real target files were copied. The source and temporary evidence trees were preserved.

| Run | Result and source bracket | Durable receipt |
|---|---|---|
| Red01, before host enforcement | One behavioral failure in 2.40 seconds, at the final stale-budget assertion; no setup or collection error. All 14 external pins matched. | [Red verification](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-budget-completion-20261030-01/verification.json), [stdout](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-budget-completion-20261030-01/stdout.txt), [JUnit](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-budget-completion-20261030-01/runner/junit.xml). |
| Green02, historical only | One pass in 2.37 seconds. The external bracket detected a concurrent host source change; this run is superseded for final acceptance. | [Historical verification](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-budget-completion-20261030-02/verification.json). |
| Green03, final source hold | One pass in 2.61 seconds. All 14 external pins matched; the runner also reported no tracked-source drift. | [Final verification](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-budget-completion-20261030-03/verification.json), [JUnit](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-budget-completion-20261030-03/runner/junit.xml), [completion](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-budget-completion-20261030-03/runner/completed.json), [copy manifest](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-budget-completion-20261030-03/copy-manifest.json). |

The final copy-manifest SHA-256 is `a8843e325ae07c1b9db42e5d50d7d9ce0ad94d2fe0c75002b7de15cf5a6d9e11`. Both stable runs completed shutdown and recorded only the three expected configuration/logger/simulation-storage redirects, with no blocked attempts recorded. The CPython audit runner is not an operating-system sandbox. This is offline behavioral evidence, not provider, billing, complete research, deployment, or actual child-process evidence.

Final command, executed from this worktree:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B \
  backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/world-anchor-budget-completion-20261030-03 \
  -q --tb=short backend/tests/test_world_anchor_budget_completion.py
```

Use a new evidence directory for another run. Copied authorization and SQLite files preserve the completed experiment; they are not relocated authority to resume. `ruff check backend/tests/test_world_anchor_budget_completion.py` passes. The first attempted Ruff executable path was absent; the installed `ruff` command succeeded. The final diff review is restricted to the two owned files.

The first copy attempt correctly refused pytest's symlinks before copying any runner file. The corrected bounded copy recorded and omitted those aliases after confirming that their targets stayed inside the original evidence root. A premature no-drift message for Green02 was corrected immediately when the closing bracket returned its mismatch. The parent held shared source for Green03; the final result was reported only after every external pin matched.

## Remaining work

No work remains in this owner's two-file scope. The parent owns production review, broader composed verification, integration, and delivery. No commit, provider call, guard change, core reset, or delegation was performed.

Continuation prompt: If the parent changes the budget-completion path, rerun only this test in a fresh `main_offline_pytest.py` process with new before/after source pins and a new evidence directory. Preserve Red01 and final Green03. Read PR1 in `pure-review.md`, preserve active owners' files, and never reset spending core state or fabricate expected completion authority. Keep any unrelated pure admission rejection attributed to its actual boundary.
