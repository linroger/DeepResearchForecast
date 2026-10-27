# Research PDF export acceptance

Verified 27 October 2026 on `codex/research-pdf-export`, created from main at `033e191fe78fcd7cf81dfc117e3264f3dc02f133`. The implementation is isolated in the attached worktree. The primary checkout, its services, accepted report bytes and provider configuration were preserved.

## User-visible behavior
Both original PDF buttons start a resource-scoped background agent, display its phase and download the reviewed PDF on completion. The agent loads the actual packaged skill and reviews the complete selected source. It preserves values, qualifiers, tables, citations, footnotes, chart associations and the chosen language; it does not regenerate research or another translation. Required unsupported content or unsuccessful review produces a visible error without a legacy-renderer fallback.

The skill ships inside the backend wheel. Formatting is source-preserving and selected-language; the original standalone paired-language workflow is retained in the vendored package. Agent reviews use a new automated-review contract and do not fabricate manual approval flags.

## Final evidence
| Check | Outcome | Evidence |
|---|---|---|
| New and related backend scenarios | 266 passed | `/private/tmp/research-pdf-delivery-gate-20261027` |
| Frontend unit tests | 445 passed | Durable `acceptance-20261027/frontend.log` |
| Production frontend build | Passed; Vite reports the 533 kB bundle-size warning | Same log |
| Browser harness boundary tests | 31 passed | `frontend/tests/browser/research-pdf-export.guard.test.mjs` |
| Actual Vue buttons → real API/jobs/agent/native renderer | 8 browser cases passed, four correct-language PDFs, duplicate clicks and stale observers covered | Durable `acceptance-20261027/browser-final-ui/receipt.json` |
| Live provider | English dossier and Mandarin forecast each passed in four calls; one page each | `live-final-20261027/live-summary.json` |
| Full saved-source native rendering | 38-page forecast with 363 components and 30-page dossier with 212 components passed | `native-results/final-20261027/receipt.json` |
| Visual preservation on final renderer | All 68 final page images identical to the previously inspected generation | Same native receipt and `native-acceptance.final.json` |
| Complete-source review budget | Actual examples fit the 96-call default: 83 and 68 calls including page coverage | `native-results/current-budget-check-20261027.json` |
| Static/package gates | Scoped Ruff and CI F/E9 passed; environment drift and uv lock passed; wheel contains all runtime/skill files | `evidence/verification.json`, local wheel validation |
| Independent review | Six reproduced job-core defects closed; final integration review found no new blocker | `evidence/review-jobs.md`, `evidence/final-integration-review.md` |

Private evidence paths above are below `/Users/rogerlin/Documents/Codex/evidence/research-pdf-export-20261026/` unless an absolute path is shown. Raw backend/browser receipts are archived there under `acceptance-20261027/`; full source reports, PDFs, page images and model journals stay private. The committed `evidence/verification.json` records paths and SHA-256 values. `evidence/final-source-manifest.json` freezes 54 source/harness files. Final browser/live runs and native rerenders match this freeze; no source drift was observed.

The real provider run used the existing GLM route and credentials, with `glm-5.3` planning and the documented `glm-5.3-flash` reviewer. Its random pixel probe and actual page reviews passed. Two bounded smoke runs used sixteen requests in total; the final run had a four-call ceiling for each of its two cases and used exactly eight requests. No automatic retry occurred. This is real provider evidence for small fixtures, not a long-report latency or financial-quality benchmark.

## Isolation and guard interpretation
The backend gate installed the existing guard before application imports. It admits one exact read-only restart test child through `--allow-python-script backend/tests/test_artifact_translation_restart.py`; the earlier run without that admission was rejected and was not counted as a green gate. The final run had no source drift and completed child/process shutdown.

Blocked operations remain recorded rather than relabeled as zero attempts: ReportLab attempted optional home configuration reads; old PDF/font discovery attempted `fc-list`, `system_profiler` and font-directory reads. These were denied. The browser server admitted only its exact loopback listener, deliberately exercised seven negative controls, and shut down cleanly. The live harness admitted only DNS for the configured official provider and TCP connections to its resolved HTTPS addresses. Its eight final requests are recorded separately from offline checks. SDK platform-header discovery attempted `uname` and an unregistered executable; source inspection identifies the corresponding Python `platform.platform()`/`architecture()` `file` probe. Both were denied; neither guard rules nor HOME were weakened.

## Corrections and remaining limits
Review-driven fixes cover unknown-dispatch barriers surviving cancellation/status polling, mandatory input/review bindings, malformed agent receipts, ownership lock release and snapshot-race recovery. Exact text/cell/image/link checks remain in place. The actual dossier's local interactive chart link is bound to its captured PNG and represented as a static PDF link with the original destination retained; no HTML executes. Large reference lists use their exact parsed child nodes for reconciliation, with the complete raw-source pass and node hashes preserved, instead of resending the entire reference list for every item.

Final lint changes made iterator strictness and asynchronous closure captures explicit; the final 266-test gate and the refreshed browser/live/native runs cover the resulting bytes. CI now installs the native test fonts, runs the guarded PDF suite explicitly, and uses the project's declared Python 3.12 lint target. Five pre-existing undocumented Config defaults were documented to close the environment-drift gate without changing runtime values.

No required feature work remains after source delivery. Other browser/font environments and arbitrary unsupported Markdown require their own acceptance. No main merge or shared-service deployment is part of this branch request. The PDF review is automated, not human certification or verification of the source research's factual conclusions.
