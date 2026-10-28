# Final implementation verification — 2026-10-28

The code is verified on the isolated `codex/target-first-forecast` branch from base `6ab52f77`. The original application checkout's staged/unstaged work and saved runs were not incorporated or reset. This record establishes controlled implementation behavior, not deployment or forecast skill.

## Gates

| Gate | Final result | Durable evidence |
|---|---|---|
| Relevant backend regression and actual-consumer scenarios | **5,199 passed, 0 failed, 2 skipped**, 149 modules, 466.27 seconds | `evidence/backend-final-junit.xml.gz`, `backend-final-receipt.json` |
| Fixed source | **537 backend/source/test/fixture files unchanged** throughout the broad run | `evidence/backend-final-source-before.json`, `backend-final-source-after.json` |
| Independent actual production scenarios | **8 passed**; includes real engine → case → paths → final publication | `evidence/independent-core-probes-junit.xml.gz` |
| Independent core/API/estimator regression | **248 passed**, no open CORE-1 through CORE-12 P1/P2 findings | `review-core-final.md`, `evidence/independent-core-summary.json` |
| Journal-learning repair | **62 focused, 291 composed, 62 independent peer passes**; FBL-1 closed | `feedback-library-final-review.md`, `evidence/library-verification-summary.json` |
| Frontend release | **329 passed**, no failures; one unchanged listener scenario intentionally excluded | `evidence/frontend-release-tests.log.gz`, `frontend-release-summary.json` |
| Production frontend build | **Passed** with 95 unchanged source/test/fixture inputs and unchanged shared cache mtime | `evidence/frontend-release-build.log.gz`, `frontend-release-source-hashes.json` |
| Static checks | Changed Python files pass Ruff F/E9; application/bridge/scripts parse; setup.sh passes shell syntax; environment drift has zero missing controls | `evidence/environment-drift.json`, `verification.json` |

Python 3.12.6 and Node 22.22.3 were the existing provisioned runtimes; no dependency installation was performed. The build retains the existing Vite main-chunk-size and mixed static/dynamic overlay import warnings. It starts no server and writes its output/cache only to the recorded temporary build directory.

## Skips and boundaries

The two backend skips are the vendored DeerFlow overlay observability and model-inheritance-drift tests in `test_deerflow_bridge_sync_guard.py`; their required vendored harness snapshot is absent from this checkout. The rest of the deployment sync tests ran. The excluded frontend scenario is exactly `running dev server answers on localhost and 127.0.0.1 and on no other interface`; it exercises unchanged dev-server exposure and starts loopback listeners. The selected tests use real components and API consumers with controlled transports.

The broad guard completed shutdown and preserved identity variables with **15 registered children**:14 exited0, and the real SIGTERM fixture intentionally exited143 with a completed shutdown receipt. It recorded **one blocked socket creation,11 blocked process attempts and20 blocked external reads**, including contained font/platform discovery. Those are nonzero blocked attempts, not proof of zero attempted networking or an OS sandbox. No successful live forecast provider, source probe, production service, paid cohort or production scheduler activation is claimed.

After the broad gate, the monitor cadence comment was corrected to match its already-tested24-hour source default. Its Python AST is byte-for-byte equivalent under normalized AST comparison;39 affected scheduler/lifecycle tests pass on the delivered bytes. `evidence/config-comment-proof.json` records both hashes, and `delivery-source-hashes.json` records all537 delivered source/test/fixture hashes. This is the sole post-gate source edit; no executable behavior changed.

## Red-to-green history

The first broad149 run had 5,163 passes, 17 failures and 2 skips. Eleven tests asserted the old strict quantitative-grounding policy; they now explicitly test `REPORT_PUBLISH_GATE_MODE=fail` with every original assertion retained, while grade tests exercise coverage disclosure and hard cited/probability contradictions. Two signal fixtures used an unwritable cwd and self-signals denied by the existing guard; exact generated-child registration plus real parent-delivered SIGINT/SIGTERM now preserve the queued-work and terminal-state assertions. Four reader failures used obsolete synthesized action metadata; the fixture now uses legal response menu rows and a reviewed actual API export. Five frontend literals were aligned to that canonical snapshot, preserving all 256 assertions. These are repaired compatibility cases, not deferred failures or unexplained exclusions. Historical red JUnit and receipts are retained under `evidence/broad-initial-*`.

Independent review also reproduced and closed evidence laundering, missing post-gather parameter binding, late cancellation, publication canonicalization, readiness and report-only reuse, fork consumer ownership and parent receipt validation, frozen estimator replay, manual budget reconstruction, native market payload/health and unbound journal-learning defects. Their reproductions and closure are in the two final review files. The source-aware library retains assumptions; a real journal event alone cannot validate an unrelated actor claim or mechanism parameter.

## Reproduction

`evidence/backend-final-command.json` is the exact argv used from the repository root. Use the same compatible interpreter and unchanged `backend/scripts/main_offline_pytest.py`; replace only the value after `--evidence-dir` with a **new nonexistent canonical** `/private/tmp/...` directory. The two explicitly registered static Python fixtures are the gateway performance and feedback SDK helpers. `evidence/backend-test-modules.txt` records all 149 selected modules. Dynamic signal children are registered by their own exact script hashes inside the test; no guard policy is relaxed.

JUnit files are gzip-compressed without modification. `evidence/index.json` hashes every stored receipt/report and its original uncompressed bytes. Full generated pipelines remain in their guarded evidence directories; no historical application pipeline was resumed or rewritten.

## Separate empirical acceptance

[Issue10](https://github.com/linroger/DeepResearchForecast/issues/10) tracks authorized live transport/provider confirmation, monitor activation, documented realized historical episodes and outcome-blind prospective scoring. The implementation does not manufacture these results. Simulation and structural estimator weights remain zero. Source cadence defaults do not prove runtime activation, and publisher-vintage arithmetic does not establish realized forecasting accuracy.
