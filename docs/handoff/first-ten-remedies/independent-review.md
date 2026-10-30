> Final status note: The final receipt-policy, prior-publication and deterministic accounting closures below supersede the earlier open review entries.

# Independent bounded review

Status: Bounded rereview complete; both reproduced P2 findings are closed by fresh independent evidence. No open P1/P2 remains within this review scope. Review baseline: `5b9b92157b8a5699c6e702cd8e3e3766eaadf02a`.

The review covers the coordinator's receipt-aware HTTP resume, continue, and seed-fork preflight, plus estimator display and deterministic report publication/audit. The acceptance boundary is actual HTTP/report consumers, frozen authority/probabilities, legacy and tournament-off compatibility, provider readiness for new LLM paths, tamper rejection, diagnostic-fence containment, and deterministic publication/replay.

Only this document is owned by the reviewer. Market/prior, mechanisms, and health changes belong to other workers and are excluded from this pass. No application or test source edits, live/network calls, scheduler activation, saved-run access, primary-checkout writes, or commits are authorized by this review.

## Evidence plan

Read the topic handoff, plan, issues, changed source and relevant consumers. Run the three requested test modules through the approved isolated offline runner with a new `/private/tmp` evidence directory. Record exact reviewed source hashes and inspect completion receipts, guard events and drift. Report only concrete P1/P2 defects, with bounded reproductions or precise source-supported triggers. A later composed review is required if reviewed source changes after this pass.

## Findings

Closed: unknown model-admission policy bypassed receipt matching and removed its diagnostics from a publishable report. Closed: interrupted seed-fork HTTP resume incorrectly required research credentials. No P1 was identified within this bounded review. Detailed evidence and the historical sequence follow below; the final receipt-repair closure supersedes earlier open statuses.

## Verification

Latest independent closure gate: HTTP14 + estimator5 + model-consumer11 + report37 + one actual ReportAgent acceptance doctest passed 68/68 in 8.69 seconds. Reviewed production and test hashes were unchanged across the run. Both reproduced findings are closed for these exact source bytes; broader owner work and later source edits are outside this verdict.

## Updates

- 2026-10-28: Initialized the review record after reading the active handoff, plan and issues. Working tree contains concurrent owner edits.

## Confirmed P2: interrupted seed-fork resume still requires the research provider

Location: `backend/app/services/target_pipeline.py:247-249` (`preflight_saved_target` early return), consumed by `backend/app/api/research.py:63-69`.

A newly admitted target seed fork deliberately starts all local stages as pending while retaining `target_case_binding` and the verified `target_fork_source` parent receipts. If execution is interrupted before child research resealing, HTTP resume delegates to fresh-research preflight and returns 400 for the missing DeerFlow directory/key. The runtime can instead validate/copy the admitted parent snapshot and finish with no new research call. This leaves the user unable to recover an already admitted fork precisely when the completed research provider is unavailable.

Bounded observation under the approved runner: parent completed, HTTP seed fork returned 200, child research remained pending with both bindings present, simulated interruption saved only fixture state, HTTP resume returned 400 with missing-research prerequisites and did not dispatch. Direct `PipelineOrchestrator.resume` plus `_run` then completed the child without another research producer invocation. Fix the pending fork recovery branch by read-only validation of its parent proof before skipping research readiness; retain decision-provider preflight for new LLM paths and reject altered parent inputs.

The first interactive probe used `pytest --trace` to exercise an extra scenario without editing source. Its terminal submission truncated one evidence command and its subsequent continuation reused a stale local child object, causing an unrelated final assertion failure. That run is retained at `/private/tmp/first-ten-independent-review-20261028-02` and is not claimed as a clean regression result. A clean evidence capture is in progress.

## Initial gate result

`/private/tmp/first-ten-independent-review-20261028-01`: the three requested modules passed **54 tests in 6.64 seconds**, exit 0. Completion receipt records shutdown complete, identity preserved, no children, no blocked events, and no recorded source drift. Separate before/after SHA-256 checks confirm all eight assigned production/test files were unchanged during the gate. These green tests do not cover the interrupted-fork defect above.

## Confirmed P2: unknown model-admission policy silently removes its receipt from the report

Location: `backend/app/services/target_report.py:189-191` and `241-242`. These checks run only when the supplied receipt itself claims `policy == "known-contradictions/v1"`.

Starting from the real pipeline's `unmeasured` receipt, changing its policy to `changed-policy/v1` and its status to `passed` permits an actual `ReportAgent` to create a completed, publishable report. The altered simulation companion is sealed, but `target_report.json` has no `modelValidation`, and the Markdown omits its Model validation section. Thus the report can silently downgrade a present invalid receipt into the legacy compatibility path and hide the unmeasured seed finding. `admit_model(case)` still rejects actual model contradictions; this finding concerns receipt integrity and visibility, not a claim that contradiction checks are bypassed.

Evidence: `/private/tmp/first-ten-independent-review-20261028-06/receipt-downgrade-probe.json`, with the generated report under that run's `pytest-tmp` directory. Reject unknown or malformed policy-bearing receipts, validate the recognized receipt against recomputation, and separately preserve genuinely legacy receipt-free/diagnostic inputs. Do not require a successful validation status for unsupported or unmeasured cases.

## Scope addition and composed gate

The parent added model-admission integration to this review: pipeline admission before binding, `run_paths(model_validation="admission")`, report recomputation and matching, and visible evidence gaps. The mechanism implementation itself remains with its owner.

Fresh run `/private/tmp/first-ten-independent-review-20261028-05` produced **50 passed, 9 failed in 7.44 seconds** across the original three modules plus `test_first_ten_model_consumers.py`. Five failures are the old linear-report fixture's inconsistent declared output seed: its formula changed to `2 * base` while its seed remained the growth fixture value. Four are market-health fixtures missing the newly required exact-settlement terms. The relevant owners should repair those fixtures while preserving both stricter production guards. These failures supersede the earlier 54-pass statement for the composed source, and are not additional runtime findings.

The bridge/isolation/bilingual gate `/private/tmp/first-ten-independent-review-20261028-04` produced **34 passed, 1 skipped in 6.44 seconds**. The skip is the pre-existing model-review translator integration test. Its receipt recorded two blocked native discovery subprocesses (`fc-list`, `system_profiler`) and 18 blocked font-directory reads. No child or network operation was admitted.

The clean interrupted-fork probe is `/private/tmp/first-ten-independent-review-20261028-03/interrupted-fork-probe.json`: HTTP 400 rather than 200, no dispatch/state mutation, direct resume completed, exactly one research call including the parent, and child publication true. The underlying existing test completed normally (1 passed); the supplemental HTTP expectation failed as explicitly recorded in the JSON. Debugger startup attempted to read `~/.pdbrc`; the guard denied it. A supplementary debugger hash command had a comprehension-scope NameError; it did not affect the captured behavior. The original eight-file before/after hashes remain the source evidence for that pre-integration pass.

## Interrupted-fork repair received

The coordinator now handles a pending child with `target_fork_source` by loading its parent, comparing `capture_fork_source(parent)` to the pinned proof and comparing parent/child case bindings before reading the verified parent's case. The runner retains the copying responsibility. Source inspection confirms this path still reaches decision-provider readiness when LLM actors need new paths; the only earlier successful return requires a verified completed run. The added actual Flask test covers valid interrupted recovery and changed parent research. Independent rerun of exactly HTTP14 + estimator5 + model-consumer5 is in progress in `/private/tmp/first-ten-independent-review-20261028-08`.

The model-receipt probe also confirms the intended controls: keeping the recognized policy but falsifying its status raises `model admission receipt differs from frozen case`; unsupported units remain accepted with status `unsupported` and visible report diagnostics. The unknown-policy bypass is therefore isolated to the conditional receipt dispatch, not the mechanism algorithm.

## Final bounded verdict and source state

At the close of this review, the interrupted-fork finding is **closed**. `/private/tmp/first-ten-independent-review-20261028-08/{completed.json,junit.xml}` records **24 passed in 7.55 seconds**, exit 0, shutdown complete, identity preserved, no blocked operations, no child processes, and no source drift among runner-recorded files. This is the exact requested HTTP14 + estimator5 + model-consumer5 gate, run with the approved interpreter and `-I -S -B backend/scripts/main_offline_pytest.py`.

The receipt-policy downgrade finding remains **open, P2**. Its actual publication reproduction and positive/negative controls are captured in `/private/tmp/first-ten-independent-review-20261028-06/receipt-downgrade-probe.json`. That run completed normally and recorded one denied debugger startup read of `~/.pdbrc`; no network, provider or child process was admitted. The known-policy altered status is rejected, and unsupported units retain their visible `unsupported` result. No additional P1/P2 was found in the estimator display, fence containment, authority/probability preservation or exact report replay paths examined.

After the coordinator repaired the linear fixtures, the intermediate broader rerun `/private/tmp/first-ten-independent-review-20261028-07` recorded **57 passed, 4 failed in 8.95 seconds**. Only the four market-health fixtures failed; these remain the reporting/market owner's reconciliation work. Do not relax exact-settlement admission to restore those tests.

Production SHA-256 values checked at the final requested gate:

| File | SHA-256 |
|---|---|
| `backend/app/api/research.py` | `bb6f066b30cf30f4c7a8fc397bb3a02c54f665c260fab2b16c3e90c9e6c7dfbe` |
| `backend/app/services/target_pipeline.py` | `8a864d49f30be3eb6ee5c8be11212662b5f1a86db50403be36d657b4be29e00e` |
| `backend/app/services/target_report.py` | `658abb2634bddd6357e2ac458c64b6d0504786a16fc64a07da254c67d64a67da` |
| `backend/app/services/report_agent.py` | `fd67276d791aed22a46ea9d4aeba7faf96c07662cabce7fdf44ce26591391a08` |
| `backend/app/services/forecast_estimator_table.py` | `5d7f534b8ffee74b325e4d44f6074bae8c9ebab7f6282f9bd7e03df774a2aa76` |
| `backend/app/services/target_mechanisms.py` | `fba619848e9698f458bdabf5d82d44ddd55a1d68baa2d0dcd43ec5768c36bd59` |
| `backend/app/services/target_simulation.py` | `6b8623edf4f87d0891a452a0a53fd3406ffae55321541319b9e6dd679895689a` |

The final gate's recorded test hashes are HTTP `3c37fec4212254d9e039c30f53c93ea64be1c5160c9112ce5ffcf5d1818dbf58`, estimator `ffd91b2426b27140ea8dbd16154cd9361ba5d8ef8e031b18629f986b88d2781d`, and model-consumer `cdbd0f57a8166abf10bd0c3c400c209487f63f2aa527c23f2f279e85bd228d56`. After that gate finished, the coordinator added a zero-decision-budget case to the model-consumer test module (observed hash `060c8eb2a4ef3f0707589ca6d85e124abdc70980777154234de37aeb14f5791d`). That additional case is not covered by the 24-pass receipt. A subsequent composed review must use fresh evidence for any later receipt-validation or other source edits.

Only this review document was written in the worktree by this reviewer. All runtime writes were contained in new offline evidence roots; no source/test edits, live/network/scheduler runs, production saved-data access, primary-checkout writes, or commits were performed.

Next bounded handoff: repair the report's handling of unknown/malformed policy-bearing model receipts, preserve legacy compatibility and unsupported/unmeasured visibility, and rerun its actual-publication regression plus the affected report consumers on frozen source. The coordinator owns the fix and remaining composed gate.

- 2026-10-28: Finalized this bounded pass with one closed P2, one open P2, fresh 24-case evidence, exact source hashes, and explicit limits for concurrent later test edits.

## Receipt repair rereview: actual ReportAgent acceptance scenario

The coordinator repaired receipt admission and added zero-budget publication coverage. The following executable documentation uses the existing case fixture and production `ReportAgent`; it writes only inside the fresh guarded evidence root. It checks the original unknown-policy failure at the constructor/publication boundary, valid unmeasured publication and deterministic replay, honest legacy unsupported diagnostics, and receipt-free compatibility. Run this document through the approved runner with pytest's `--doctest-glob=independent-review.md`, alongside a backend test module so its conftest binds the repository's `tests` package.

```pycon
>>> import copy, hashlib, json, logging, sys
>>> from pathlib import Path
>>> import pytest
>>> from app.config import Config
>>> from app.services import report_agent as ra
>>> from app.services.target_simulation import run_paths
>>> from tests import test_target_pipeline as existing_cases
>>> root = sys.modules["main_offline_guard"].root
>>> patch = pytest.MonkeyPatch()
>>> patch.setattr(ra.ReportManager, "REPORTS_DIR", str(root / "review-reports"))
>>> patch.setattr(Config, "REPORT_FORECAST_LEDGER", False)
>>> prior_logging_disable = logging.root.manager.disable
>>> logging.disable(logging.CRITICAL)
>>> case = existing_cases.case.__wrapped__()
>>> next(row for row in case["nodes"] if row["nodeId"] == "spending")["value"] = None
>>> simulation = run_paths(case, paths=1, periods=1, model_validation="admission")
>>> assert simulation["modelValidation"]["status"] == "unmeasured"
>>> bad = copy.deepcopy(simulation)
>>> bad["modelValidation"].update(policy="changed-policy/v1", status="passed")
>>> with pytest.raises(ValueError, match="model admission receipt"):
...     ra.ReportAgent("g", "sim_review_invalid", case["question"], forecast_case=case, target_simulation=bad).generate_report(report_id="report_review_invalid")
>>> assert not Path(ra.ReportManager._get_report_folder("report_review_invalid")).exists()
>>> agent = ra.ReportAgent("g", "sim_review_valid", case["question"], forecast_case=case, target_simulation=simulation)
>>> report = agent.generate_report(report_id="report_review_valid")
>>> assert report.status == ra.ReportStatus.COMPLETED, report.error
>>> assert ra.ReportManager.publication_status(report.report_id)["publishable"]
>>> folder = Path(ra.ReportManager._get_report_folder(report.report_id))
>>> record = json.loads((folder / "target_report.json").read_text())
>>> assert record["modelValidation"] == simulation["modelValidation"]
>>> assert "### Model validation" in report.markdown_content and "unmeasured" in report.markdown_content
>>> before = {name: (folder / name).read_bytes() for name in ("forecast.json", "full_report.md", "target_report.json", "final_audit.json")}
>>> replay = agent.generate_report(report_id=report.report_id)
>>> assert replay.status == ra.ReportStatus.COMPLETED
>>> assert all((folder / name).read_bytes() == data for name, data in before.items())
>>> forecast = json.loads((folder / "forecast.json").read_text())
>>> assert [row["probability"] for row in forecast["scenarios"]] == [0.4, 0.6]
>>> legacy_case = existing_cases.case.__wrapped__()
>>> next(row for row in legacy_case["nodes"] if row["nodeId"] == "base")["units"] = "unmodeled-unit"
>>> legacy_simulation = run_paths(legacy_case, paths=1, periods=1, model_validation="diagnostic")
>>> legacy_report = ra.ReportAgent("g", "sim_review_legacy", legacy_case["question"], forecast_case=legacy_case, target_simulation=legacy_simulation).generate_report(report_id="report_review_legacy")
>>> assert legacy_report.status == ra.ReportStatus.COMPLETED, legacy_report.error
>>> legacy_folder = Path(ra.ReportManager._get_report_folder(legacy_report.report_id))
>>> assert json.loads((legacy_folder / "target_report.json").read_text())["modelValidation"]["status"] == "unsupported"
>>> assert "### Model validation" in legacy_report.markdown_content and "unsupported" in legacy_report.markdown_content
>>> assert ra.ReportManager.publication_status(legacy_report.report_id)["publishable"]
>>> old_case = existing_cases.case.__wrapped__()
>>> old_simulation = run_paths(old_case, paths=1, periods=1)
>>> assert "modelValidation" not in old_simulation
>>> old_report = ra.ReportAgent("g", "sim_review_old", old_case["question"], forecast_case=old_case, target_simulation=old_simulation).generate_report(report_id="report_review_old")
>>> assert old_report.status == ra.ReportStatus.COMPLETED, old_report.error
>>> assert "### Model validation" not in old_report.markdown_content
>>> assert ra.ReportManager.publication_status(old_report.report_id)["publishable"]
>>> result = {"unknown_policy_rejected_before_report_write": True, "unmeasured_publishable": True, "legacy_unsupported_visible_and_publishable": True, "receipt_free_legacy_shape_preserved": True, "deterministic_replay": True, "probabilities_unchanged": True}
>>> _ = (root / "actual-report-agent-closure.json").write_text(json.dumps(result, indent=2))
>>> paths = ["backend/app/api/research.py", "backend/app/services/target_pipeline.py", "backend/app/services/target_report.py", "backend/app/services/report_agent.py", "backend/app/services/forecast_estimator_table.py", "backend/app/services/target_mechanisms.py", "backend/app/services/target_simulation.py"]
>>> hashes = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in paths}
>>> _ = (root / "reviewed-source-sha256.json").write_text(json.dumps(hashes, indent=2))
>>> patch.undo()
>>> logging.disable(prior_logging_disable)

```

## Final receipt-repair closure — supersedes the prior open verdict

**Verdict: CLOSED.** `target_report.py:189-200` now treats any present `modelValidation` as a receipt that requires verification. A policy-bearing receipt must equal the recomputed admission receipt, so unknown policies, false statuses and altered fields cannot choose a compatibility bypass. A policy-free receipt must exactly equal the genuine legacy diagnostic validator result. Every accepted present receipt is rendered using the recomputed admission status, retaining unsupported/unmeasured gaps. Receipt-free legacy projections retain their shape. The zero-budget report validator now agrees with admission and permits zero requests without a provider call.

Fresh independent results:

| Evidence directory | Scope | Result |
|---|---|---|
| `/private/tmp/first-ten-independent-review-20261028-09` | HTTP14 + estimator5 + model-consumer11 | 30 passed in 7.91 seconds |
| `/private/tmp/first-ten-independent-review-20261028-11` | HTTP14 + estimator5 + model-consumer11 + full target report37 + actual ReportAgent doctest above | **68 passed in 8.69 seconds** |

The actual consumer scenario rejected the original unknown-policy/false-status payload at `ReportAgent` construction, before any report directory was created. Its positive controls published an unmeasured receipt with the matching visible record, published genuine legacy unsupported diagnostics with honest status, and retained the receipt-free legacy shape. Repeated report generation preserved the exact `forecast.json`, `full_report.md`, `target_report.json` and `final_audit.json` bytes. Research probabilities remained exactly `[0.4, 0.6]`. The separate zero-budget regression completed a publishable pipeline with zero actor-model calls.

Evidence files in run11 are `actual-report-agent-closure.json`, `reviewed-source-sha256.json`, `completed.json`, and `junit.xml`. Completion shows exit 0, shutdown complete, identity preserved, no admitted child processes, no recorded source drift and no network/provider attempts. Pytest's doctest debugger initialization attempted one read of `~/.pdbrc`; the guard denied it. No interactive debugging or `--trace` was used in this rereview. The earlier run10 doc-only attempt failed because an installed `tests` package shadowed the repository namespace; collecting the actual backend modules loaded the repository conftest binding. This was a harness import failure before the scenario, not an application defect, and its evidence was retained.

All ten production files and four test files listed below were independently hashed before and after run11 and matched. The source receipt stores the seven directly reviewed production paths; the runner completion receipt stores the four test hashes. The additional market/health dependencies below establish the exact composed consumer state without duplicating their owners' implementation review.

| Path | Final SHA-256 |
|---|---|
| `backend/app/api/research.py` | `bb6f066b30cf30f4c7a8fc397bb3a02c54f665c260fab2b16c3e90c9e6c7dfbe` |
| `backend/app/services/target_pipeline.py` | `8a864d49f30be3eb6ee5c8be11212662b5f1a86db50403be36d657b4be29e00e` |
| `backend/app/services/target_report.py` | `4766b651b03931ad2f78a3d1a878aa74bf8607b50918da81fe88c87c2f43959b` |
| `backend/app/services/report_agent.py` | `fd67276d791aed22a46ea9d4aeba7faf96c07662cabce7fdf44ce26591391a08` |
| `backend/app/services/forecast_estimator_table.py` | `5d7f534b8ffee74b325e4d44f6074bae8c9ebab7f6282f9bd7e03df774a2aa76` |
| `backend/app/services/target_mechanisms.py` | `fba619848e9698f458bdabf5d82d44ddd55a1d68baa2d0dcd43ec5768c36bd59` |
| `backend/app/services/target_simulation.py` | `6b8623edf4f87d0891a452a0a53fd3406ffae55321541319b9e6dd679895689a` |
| `backend/app/services/forecast_extractor.py` | `1f9290509ec590050acfeb753d23115a5b25871723e6756016645cdb80d8a123` |
| `backend/app/services/forecast_tournament.py` | `99730b9245c23714f149fa359987efb0c97de48baa9418c7887f6015dccb5c0c` |
| `backend/app/services/forecast_inputs_health.py` | `48c73f949b474557a90e29d516d4c9587c7af14ebeb86419dc80d370d236fa89` |
| `backend/tests/test_target_reuse_preflight.py` | `3c37fec4212254d9e039c30f53c93ea64be1c5160c9112ce5ffcf5d1818dbf58` |
| `backend/tests/test_first_ten_estimator_table.py` | `ffd91b2426b27140ea8dbd16154cd9361ba5d8ef8e031b18629f986b88d2781d` |
| `backend/tests/test_first_ten_model_consumers.py` | `55e997f8e438318d14d991f403eb7a639962bb5e46eba66a5ed7c3d4c016f3a4` |
| `backend/tests/test_target_report.py` | `221ffabcffccbe629990c2178a8a94ff9aeedc9d094cdf3c602c8641dedbdecc` |

No open P1/P2 remains in the assigned HTTP reuse, estimator display/audit, or bounded model-consumer integration review. The wider first-ten-remedies acceptance remains the coordinator's work after other owners freeze. Only this owned review document was edited; no application or test files were written by the reviewer.

- 2026-10-28: Closed the receipt-policy P2 with actual ReportAgent rejection and publication/replay controls; independently passed the finalized 67-case suite plus one consumer doctest; recorded final hashes and guard activity.

## Final bounded addition: prior-ledger publication hooks

**Verdict: reviewed; no new P1/P2 found.** The coordinator added three small hooks to `report_agent.py` after the 68-case receipt closure. At lines5984-5986, prior/posterior validation runs after critique and before assigning the spine, rendering its prompt block or early persistence. Invalid prior-bearing spines therefore cannot become pinned inputs; the existing enclosing fallback clears the optional spine instead. This is not a claim that the pre-pin path aborts the whole report.

At lines12442-12454, the final artifact audit validates a deep copy and compares it to the original forecast. A stale ledger or metadata that the validator would canonicalize/complete is recorded as invalid, without silently repairing the published ledger. The validator detaches the supplied prior and update rows, so passing those original arguments does not mutate them. At lines12092-12094, an invalid prior audit contributes a hard integrity issue independently of whether structured forecasts are required; grade-mode uncertainty disclosures cannot downgrade that defect. Legacy forecasts carrying neither prior field preserve the previous audit path.

Fresh independent execution of only the requested `backend/tests/test_first_ten_prior_publication.py` passed **2/2 in 1.68 seconds**, using `/private/tmp/first-ten-independent-review-20261028-12`. The valid and tampered cases exercise the real final audit in grade mode: the valid ledger passes its prior audit; the stale posterior fails `hard_passed`; both retain their stored ledger without repair. `completed.json` records exit0, shutdown complete, identity preserved, no blocked operations, no child processes, and no recorded source drift.

Reviewed hashes matched before/after this run:

| File | SHA-256 |
|---|---|
| `backend/app/services/report_agent.py` | `97502eff845b6f7acb597059ab393b7bd5b169ca3f109b73fe42c7e96cc27fb1` |
| `backend/app/services/forecast_extractor.py` | `1f9290509ec590050acfeb753d23115a5b25871723e6756016645cdb80d8a123` |
| `backend/tests/test_first_ten_prior_publication.py` | `7ed13c804b0a90cff71020f18683ad64722f5405016da4ccfc836f72db025c51` |

The report-agent hash above supersedes its earlier source-table entry. The earlier 68-case run applies to the earlier source state; this addition has independent source review and the requested two-case execution, not a claimed repeat of the coordinator's reported41-case gate. Both previously reproduced P2 findings remain closed. Only this review document was edited.

- 2026-10-28: Reviewed the final pre-pin and read-only prior-ledger validation hooks, independently passed2publication regressions, and recorded the updated report-agent hash with no new P1/P2.

## Bounded broad-gate diagnosis: world-evaluation terminal classification

**Concrete cause confirmed; pre-existing source, no code changes.** The broad failure in `test_unknown_concurrent_attempts_remain_reserved_and_stopped_in_denominator` is the scheduling-sensitive choice of terminal error, not lost reservations or denominator corruption.

Original evidence root: `/private/tmp/drf-first-ten-broad-final-20261028-01/pytest-tmp/test_unknown_concurrent_attemp0`. Exactly one case, `m5-investment-v2-s0-external-feedback-ablation`, has `status="failed"`, `errorCode="required_decision_failed"`, and sanitized details `lastErrorCode="policy_decision_failed"`, `lastErrorMessage="The previous decision was unavailable."` The test deliberately makes every local policy call raise `RuntimeError("scripted ambiguous dispatch")`; no provider is involved.

The original SQLite database was inspected read-only with SQLite URI `immutable=1`, which avoids sidecar creation. Its actual attempts in insertion order are:

| rowid | Slot | Ordinal | Status | Reserved / unknown cost |
|---|---|---|---|---|
| 1 | `1:proposal:authority` | 1 | unknown | 0.2 |
| 2 | `1:proposal:authority` | 2 | unknown | 0.2 |
| 3 | `1:proposal:buyer` | 1 | unknown | 0.2 |

The case permits two attempts per slot, four concurrent calls, and a cost ceiling of `0.694444444444`. In `controller.py:147-189`, each actor independently retries; authority can therefore consume its two attempts and raise `required_decision_failed` before other actors finish their first attempts. `store.py:621-627` separately rejects reservations that would exceed the shared budget. After three unknown0.2 reservations, another0.2 request fails with `run_budget_exhausted`. The controller collects these distinct exceptions through `as_completed()` and raises `errors[0]` (`controller.py:196-205`). This selection follows whichever future is yielded first, not a stable semantic priority. `evaluation.py:627-630` maps `run_budget_exhausted` to `budget_stopped` but maps `required_decision_failed` to `failed`. That exact error reached the original stored receipt.

The complete broad-run report still contains108attempts, reserved/unknown exposure21.6, actual0, both evaluation gates incomplete, and each domain has12incomplete cases,0earned points and96denominator points. Therefore every accounting/denominator invariant following the first status assertion already held in the original artifacts. The assertion that every case must specifically be `budget_stopped` assumes a scheduling order the controller does not guarantee.

### Bounded reproduction and baseline comparison

Only the exact requested test was run, once in each checkout, under the approved isolated runner:

- Current checkout: `/private/tmp/first-ten-world-eval-current-20261028-01`, **1 passed in3.36s**.
- Clean source snapshot `/private/tmp/drf-first-ten-baseline-ejnaf5wj`: `/private/tmp/first-ten-world-eval-baseline-20261028-01`, **1 passed in3.39s**.

Both receipts record exit0, shutdown complete, identity preserved, no blocked operations, no children and no recorded source drift. In both fresh runs the same case had one attempt each for authority, buyer and financier, followed by `run_budget_exhausted`; the original failure had authority twice then buyer. These reruns expose the alternate valid scheduling outcome; they do not invalidate the original failure. No repetitions or full suite were launched after the user's diagnostic checkpoint request.

The failed scheduling case is directly reconstructable from the original attempts table. A deterministic focused regression can control scheduling so authority exhausts both local attempts before peer reservations and its failed future is yielded first; the opposite control can ensure three different actors reserve before any retry. Those schedules should retain identical global reservation/unknown totals while demonstrating the current terminal-status difference. No new test code or scheduling monkeypatch was introduced by this reviewer. Avoid treating repeated green reruns as a repair.

All relevant current files match the clean baseline byte-for-byte and have no diff from5b9b9215; the original preregistration source hashes also match the production modules:

| File | SHA-256 in current and baseline |
|---|---|
| `backend/tests/test_world_evaluation.py` | `a975091594f3fca5e88d32e8c42ea2f9bf8cc8243f47347451ad5f81aee11e98` |
| `backend/app/services/world_simulation/controller.py` | `8e4799825aa5f59892617d598f57e1b658f43c0baeececa612b5d7e1a2baf553` |
| `backend/app/services/world_simulation/store.py` | `84992896b3919ace0ce0729be83b8bc6fdce16ad6cc275a2ea8b3fc140dec01e` |
| `backend/app/services/world_simulation/evaluation.py` | `f31c5467ba58da1c2aa00918910c4e288be807203517b16636386492ed27e657` |
| `backend/app/services/world_simulation/contracts.py` | `9bc5cf2389af40f8358963a09ae63f850313c4909e19e95a71d643e928ce943d` |
| `backend/scripts/main_offline_pytest.py` | `5046cf820fa468d8e8ffb2e3fdade1d20fca2f0bd56ee15eabdff51c223c02be` |

The baseline directory is an exported source snapshot without `.git`; its provenance is established here by byte comparison rather than an invented baseline HEAD. An initial ordinary SQLite read-only open could not open its WAL database; the immutable read-only URI succeeded without modifying original evidence. The source/artifact diagnosis is complete. Any fix must deliberately choose either stable error precedence in the controller or a scheduling-aware test assertion with exact allowed error codes and unchanged budget/denominator assertions; that implementation is not part of this read-only assignment. The other three broad failures remain with their assigned owners.

- 2026-10-28: Diagnosed the original world-evaluation failure from its error receipt and SQLite attempt ordering, compared unchanged baseline source, and ran only the one requested test once per checkout. No source/test edits or full-suite reruns.
