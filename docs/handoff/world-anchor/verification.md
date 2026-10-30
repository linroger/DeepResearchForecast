# World Anchor offline acceptance

Accepted on 2026-10-30 in `codex/world-anchor`, based on `9916b3beff6753cd07f2407f36428ca2030127fd`. Git delivery is recorded separately in the handoff. The machine-readable verdict is [final-verification.json](evidence/final-verification.json), with [703 source/fixture pins](evidence/source-hashes.json) and [distinct passing case IDs](evidence/passed-case-ids.json).

## What passed

The final coverage set contains **3,707 distinct backend cases**. This combines the frozen broad run, full affected-module closure, the final reflexive fixture cleanup, and four separately isolated cases. It is not a claim that the first broad command exited successfully.

| Gate | Result | Interpretation |
|---|---:|---|
| Initial ordered 77-module run | 3,690 passed; 12 failed; no skips | All 703 pins matched. Four performance children lacked explicit invocation registration; eight launcher cases encountered `TOKENIZERS_PARALLELISM` introduced during broad collection. |
| Full affected-module closure under the same collection | 286 passed | Complete v1/v2 launcher and record modules, plus all four performance cases. Production was unchanged. The fixture isolates the library hint, and a new negative still requires the unchanged launcher to refuse it. |
| Current reflexive test module | 61 passed | Fixture import aliases and unused-import cleanup only; all assertions remain unchanged. |
| Selected-budget completion, fresh process | 1 passed | Real ledger transitions reject an old selected budget and accept the current zero-call seal without resetting authority. |
| Archived target off comparison, fresh process | 1 passed | Eight combinations compare actual `9916b3be` actor/runtime output, callbacks and RNG consumption. |
| Private retained specimen, fresh process | 2 passed | All 95 raw files and original sealed inputs verified; no private skip. |

The closing case-ID reconciliation replaces all original failures, covers every affected module case, and adds the new environment-refusal control. No unresolved failure remains. Ruff `F,E9` passes on all 60 changed/new Python files; scoped whitespace and `setup.sh` syntax checks pass. The original red receipts remain preserved. The standalone budget test also declares the existing guard-only pytest marker; its unchanged case passed again in a fresh guarded process, and normal unguarded CI collection skips it through the established policy.

The compiled-world off control uses the exact archived `9916b3be` world package with disclosed current shared parent dependencies. The reflexive control retains its historical config/request/state/RNG golden. The source bracket pins those shared dependencies; no baseline is inferred merely from omitted versus `None` arguments.

## Actual private processes

The copied CPython, installed SDK, frozen launcher, upstream CLI, omitted-control factory, full linear research engine, default source tools, producer, publication and actual parent adoption APIs executed with HTTP responses mocked. No provider connection was admitted.

| Control | Outcome | Wall time | HTTP/ledger joins | Anchor scope |
|---|---|---:|---:|---|
| Documented fresh actor | Child exit 0; ready; ledger closed | 254.04 s | 41 | 7 extraction + 7 independent review calls; 140,000 retained token-envelope units |
| Missing actor authority | Expected child exit 2; blocked before assessment; ledger closed | 245.54 s | 40 | The same 14 scoped calls and 140,000 retained units |

Both controls verify all nine actor controls, the authority outcome, captured proposal/review/observation joins, primary claim incidence, trusted completion metadata, and the selected budget's exact link to the committed ledger seal. Each retained 168,000 **synthetic** microUSD in the anchor scope, with no catalog or follow-up attempt. Whole-run retained amounts were 1,146,032 and 1,106,032 synthetic microUSD respectively. These numbers validate accounting behavior, not live tariffs.

All 172 staged repository files and 424 runtime pins per control match their executed bytes. Four later test-only changes were neither staged nor imported; the global release reference is explicitly 699/703, while every used application/bootstrap file remains exact. Production `os._exit` remains intact: the child records `shutdown_complete=false`, and the parent verifies the exit by waiting. Each child records two blocked socket probes and two blocked process probes. These are denied capability probes, not zero attempts or successful provider access.

The independent final receipt is [final-verification.json](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-v2-process-final-20261030-01/final-verification.json), SHA-256 `4dc0b9285d380091fdb807306107e8770e447cf2d5821871cde990fcff4dd8e3`. Both controls meet the separate 300-second scripted-process target. The final private specimen replay took about 2.7 seconds; neither result promises live model latency.

## Evidence and review boundaries

The [pure review](pure-review.md), [coordinator review](implementation-review.md), [reflexive review](reflexive-review.md), and [record review](record-review.md) close their reproduced findings against named source and receipts. Producer, native-world, target and launcher owner records retain their bounded independent closures. Final integration covers the shared source after those owner gates.

Raw evidence remains outside Git under `~/.local/share/DeepResearchForecast/evaluations/`. The final gate archives are indexed in [archive-index.json](evidence/archive-index.json). Every regular archived payload was checked against its original bytes; pytest aliases and one special negative-test fixture are separately inventoried rather than followed or extracted. Archive copying is not relocated execution.

The original broad guard recorded 46 authorized children, one blocked socket construction, nine blocked process attempts and twenty blocked external reads. Four process refusals were the missing performance registrations; the closing invocation registered that exact existing script and its hash. The remaining dependency probes and intentional negative controls stayed denied. The guard uses CPython audit hooks, not an OS sandbox.

The saved specimen has no typed forecast contract and no official series. Its source supports 247.5 as a **2026 third-party forecast**, plus four earlier same-year forecast vintages. The tests preserve those distinctions and emit a missing-contract result; they do not create a 2027 observation, growth history, cadence or missing mechanism coefficient.

## Reproduction

Use the provisioned Python and unchanged guard, a new canonical evidence directory, and the module list in [test-plan.json](evidence/test-plan.json). Register every listed child, including `backend/tests/fixtures/gateway_performance.py`. The three stdin cases must run separately from the broad selector, and `test_world_anchor_budget_completion.py` must use its own fresh process. The exact executed argv and stdout are retained in the three final private envelopes.

The world package baseline is staged with `git archive 9916b3be backend/app/services/world_simulation/` at the documented ignored archive path; the fixture requires SHA-256 `e2e61da08d1e04068541833acaa31660a57a775a9c155b5e9238241213f6648e`. The separate SDK proof archive requires `7ceb09fc03243140d3745c7008dab4aa04abd7dc22ce1b3707bd746f08b8e6cf`. No dependency installation or guard relaxation is part of reproduction.

## Operational scope

The feature is opt-in. The initial launcher profile admits full target-first runs; other engine adapters require separate launch-profile qualification. The 64 KiB packet bound is not model-native token counting: physical calls reserve the verified full route input ceiling plus inclusive output, and a provider oversize rejection retains that debit and stops without an unmetered retry. Unsupported required mappings remain typed gaps or preparation refusals. Partial target-v3 child resume remains unsupported.

No live provider run, billing qualification, production deployment, scheduler activation or empirical forecast-quality promotion occurred. Simulation remains diagnostic with zero forecast weight.
