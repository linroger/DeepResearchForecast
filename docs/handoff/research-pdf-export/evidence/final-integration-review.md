# Final bounded integration review

**Reviewed:** 2026-10-27, completed at approximately 04:43 UTC.
**Verdict:** No new blocking or important integration findings in the reviewed frozen source.
**Worktree:** `/Users/rogerlin/.codex/worktrees/research-pdf-export/DeepResearchForecast`
**Branch:** `codex/research-pdf-export`
**HEAD:** `033e191fe78fcd7cf81dfc117e3264f3dc02f133`; implementation is the working-tree overlay, including untracked feature files, not HEAD alone.

## Scope and method

This is the requested final read-only producer/consumer review against the approved [PLANS.md](../PLANS.md) and [integration contract](../integration-contract.md). It covers `backend/app/services/research_pdf/`, the new API routes, shared frontend consumer, both API clients, and the two original Vue PDF controls. Registration/configuration and the actual vendored renderer boundary were read where needed to establish those contracts. The previous six parent-core findings were checked against their recorded closure in [review-jobs.md](review-jobs.md); they were not reopened as a new whole-repository audit.

The reviewer read the current source/diff, relevant tests, and existing acceptance receipts, then compared recorded hashes with disk. No tests, probes, builds, provider calls, application imports, service operations, or existing user report reads were performed by this review. No production source, test, configuration, shared handoff, issue tracker, Git index, or branch history was changed. This evidence document is the only reviewer-owned worktree write. Parent release documentation/delivery remains separate.

## Critical Issues

None found. There is no concrete blocking reproduction to report.

## Important Issues

None found within this bounded integration scope. This verdict does not assert that every possible report, deployment, crash timing, or model response has been exercised.

## Producer/consumer findings and positive notes

| Boundary | Current source evidence | Review conclusion |
|---|---|---|
| Original buttons → shared controller | `DossierViewer.vue:389`, `:661`, `:785`, `:805`; `ForecastReport.vue:450`, `:1082`, `:1089`, `:1564` | Both controls call the shared job consumer. Source/resource/language changes and unmount invalidate local observation. The forecast Markdown branch retains its separate direct download. No PDF failure falls back to the old exporter. |
| Shared controller → API routes | `researchPdfExport.js:51`, `:88`, `:107`, `:145`; `api/research.js:218`; `api/report.js:129`; `api/research_pdf.py:26` | Request bodies, envelopes, state vocabulary, resource kind/ID, requested language, and job IDs agree. The consumer validates response identity and source-digest continuity, deduplicates an active local click, and only explicit start/retry sends POST. |
| API → authoritative source | `sources.py:75`, `:170`, `:243`, `:271` | Forecast publication and dossier translated-variant admission are reused. Primary language is detected rather than assuming English or fabricating a translated path. Dossier fork resolution uses the existing handoff authority. Citation/chart metadata and captured local asset hashes enter the source identity. Capture verifies the source before committing its immutable copy. |
| Persistent jobs → agent ownership | `jobs.py:238`, `:345`, `:401`, `:423` | Persistent identity includes resource/language through the source descriptor plus policy. File locks serialize metadata, protect worker ownership, and bound active jobs. Reads do not launch model work. The separate replay barrier survives cancellation/freshness observations; failed capture quarantine and owner-descriptor cleanup retain the prior fixes. |
| Agent → actual skill and renderer | `agent.py:100`, `:116`, `:202`, `:411`, `:712`; `renderer.py:620`, `:682`, `:811` | The agent loads the repository skill and review references, prepares a selected-language inventory, reads complete raw-source batches, reconciles source-bound components, and calls the real vendored builder/checker. Source/asset/inventory checks are enforced across the handoff. Layout controls cannot replace report text. |
| Agent → model and image review | `model.py:127`, `:208`, `:273`; `agent.py:565`, `:646`, `:827` | Route identity is consistent between job policy and production model objects. Actual image parts are sent through the configured API without SDK retries or CLI fallback. The pixel probe precedes planning; every rendered page needs a passing source-bound verdict. At most one layout repair is available, with content errors refusing release. |
| Agent/renderer result → completion | `agent.py:880`; `renderer.py:839`; `jobs.py:168`, `:392` | Result fields and digest formats match the job verifier: source, language, normalized input, PDF, QA, review, agent receipt, skill/policy and page inventory. The verifier requires strict passing review/page records and required QA booleans. The earlier malformed-receipt and missing-input-binding holes remain closed. |
| Completion → verified download | `jobs.py:448`; `api/research_pdf.py:35`; `researchPdfExport.js:112` | Download checks current source/policy, reviewed artifact hashes, and source admission again before returning bytes. The UI uses its constructed resource/job URL, refuses redirects and mismatched advertised URLs, validates the PDF signature, uses a sanitized filename helper, and drops late responses after invalidation. Stopping UI observation does not claim to cancel a dispatched provider request. |

The dossier source mapping was also checked against the existing positional `[S#]` contract documented in `report_lint.py:873` and `:1624`. No citation-renumbering mismatch was established. Existing report bodies were not opened for this check.

## Existing verification evidence inspected

These are inspections of earlier executions, not fresh executions by this reviewer.

| Evidence | What the receipt actually establishes | Boundary |
|---|---|---|
| `/private/tmp/research-pdf-delivery-gate-20261027/{completed.json,junit.xml}` | 266 tests, zero failures/errors/skips; exit 0; completed shutdown; zero recorded source drift. All 23 recorded source hashes currently match disk. | The receipt does not directly list `renderer.py` or vendored renderer/skill files. The suite includes renderer/agent tests, but its source-hash list alone is not an exact-byte receipt for those files. |
| `/private/tmp/research-pdf-frontend-resume-20261027.log` | The log records 445 passing frontend tests, zero failures, and a completed Vite production build. | Inspected log, not a fresh build or complete frontend hash-bound receipt. |
| `/private/tmp/research-pdf-browser-ui-20261027/receipt.json` and companion server receipts | Eight browser cases passed: four real Vue/API/job/agent/native-renderer downloads (English/Mandarin primary content on each surface), plus resource-switch and unmount stale-response cases on both surfaces. Download and server PDF hashes agree in the recorded cases. | Model transport was controlled. These primary-language cases do not establish translated-variant admission or live provider behavior. |
| `/Users/rogerlin/Documents/Codex/evidence/research-pdf-export-20261026/live-20261027/live-summary.json` and the two automated review receipts | Two fictional one-page reports passed: English dossier and Mandarin forecast. Four calls each, eight total, using GLM-5.3 planning and GLM-5.3-Flash review, with completed probe/planning/content/page phases, no retry, and no outstanding request recorded. | The smoke script calls `agent.run_export` on explicit fixture snapshots. It does not exercise the real UI, API admission, job persistence, or download in that live-provider run. It proves neither long-report performance nor factual research quality. |
| [Previous job review and closure](review-jobs.md) | Six concrete prior findings have documented fixes and the original focused red/green evidence. The later delivery suite includes the current job-review cases. | Historical closure evidence remains distinct from this final static integration review. |

The backend delivery guard reports two blocked subprocess attempts, 20 blocked external reads, and one allowed guarded child. Its contained-library summary identifies font/system-discovery probes. These are blocked attempts, not “zero attempts”; the boundary is CPython audit hooks, not an operating-system sandbox. The browser server receipt separately records deliberate negative controls for network, saved-data, credential-path and external-write access, plus its permitted fixture listener. This review did not rerun or bypass either guard.

### Source timing limits

The browser server receipt was captured before the final changes to:

- `backend/app/services/research_pdf/{agent,jobs,renderer}.py`;
- `backend/app/skills/equity-research-pdf/scripts/{export_report,make_example}.py`;
- `backend/tests/test_research_pdf_agent.py`.

The live review policies likewise differ from current `agent.py`, `renderer.py`, and those two vendored script files; their `model.py` and `contracts.py` hashes match. Thus the eight browser cases and eight real calls must remain described as historical acceptance for their recorded bytes, not reruns on every final file. The latest 266-case receipt matches all of its own 23 recorded files. Current integration was independently read and frozen-hash checked here; no additional browser/live execution is claimed.

The earlier failing `research-pdf-existing-regressions-20261027` run is superseded for its included scenarios by the later 266-case delivery gate. This review uses the latter result and does not present the older red run as a newly discovered feature defect.

## Suggestions and remaining limitations

No speculative feature expansion is requested by this review. Retain these explicit limits in the parent release evidence:

- Automated source-preservation/page review is not human approval, research fact-checking, or a guarantee of model judgment. An admitted Mandarin edition may retain original English exhibit labels/quotations; the preservation receipt explicitly declines to certify complete translation.
- Required unsupported HTML, mathematical/diagram notation, unsupported image encodings, missing source assets, unresolvable links/citations, excessive table width, or exceeded review allowances fail explicitly. The implementation does not promise arbitrary document conversion or silently omit those components.
- Static local HTML-chart adaptation is constrained to captured source companions or an explicit chart manifest, records its changed link destination, and does not execute HTML.
- Ambiguous dispatched model outcomes deliberately prevent replay. Native operations may finish privately after the caller stops waiting; this is not proof of forceful cancellation or general crash recovery under all deployment topologies.
- No production service deployment, saved-report execution/preservation check, multiprocess crash/load experiment, or final-byte browser/live rerun was performed here. Private copied-report rendering evidence was not opened because existing report reads were excluded.
- The parent owns release documentation, commit/push, and any further acceptance decisions. This reviewer has no remaining reproduced blocker to hand back.

## Frozen source record

A 46-file set was hashed during review and compared again before completion with **zero changed, added, or removed entries**. It includes every `research_pdf/*.py` file, every regular vendored skill file excluding `__pycache__`, and the API/configuration/registration plus five frontend files listed below.

The aggregate SHA-256 of the UTF-8 JSON mapping `relative_path -> file_sha256`, serialized with sorted keys and separators `(",", ":")`, is:

`88c43111cc915b4990574d20c12d239dc31c01a654b2dadc2ba266db3e0d06f2`

| File | SHA-256 |
|---|---|
| `backend/app/services/research_pdf/contracts.py` | `a7c1da0a56536bb4a0140e375c444bf2a6aaa151dea45c5fb9d40060c44a9b14` |
| `backend/app/services/research_pdf/sources.py` | `e87db375958d9464955b13fd3a166f9cd9e8f66684d7d56faa8ee396098ce985` |
| `backend/app/services/research_pdf/jobs.py` | `071196a3a34f0ad1e8d7d0fb74ec362201bd1748b9f4c873df1322a4c57a67e4` |
| `backend/app/services/research_pdf/agent.py` | `b90c3e23924a50a7ba9544bde750bc5974ddede5cc0d7a1d37fd5931234c847b` |
| `backend/app/services/research_pdf/model.py` | `ccc18250e2b141a7964c5d46ca0333a1d5eb9c36a121f7eb767636a00114276e` |
| `backend/app/services/research_pdf/renderer.py` | `199cd40aa5baeab6f399c107c3c7ba6adfef97e48ee9076256ae7c1b8240eb04` |
| `backend/app/api/research_pdf.py` | `9d499637e50375b8407d7f4673bde340f82c823e786d986475ec4f279ea9fbf9` |
| `backend/app/config.py` | `c05f40fa8b242c30ef2767a6329f1fb7da954a0510a107a9190908233461eb6d` |
| `backend/app/__init__.py` | `db753519859286be365a9f9f239307f82faa5416020bc6b4a14f7f64ebde7958` |
| `backend/app/skills/equity-research-pdf/SKILL.md` | `33665ba7b31dcfd54964f2338d31ab49890e31512d1ae6dd1e00a992e2027247` |
| `backend/app/skills/equity-research-pdf/scripts/export_report.py` | `78bc7ed9ea661b428f735d80d12c12f8e2ad6eefd0c790b46ccdc2d618e528af` |
| `frontend/src/utils/researchPdfExport.js` | `6e778dce803697387b7cd13e11dca73402a1da329f1ce93b8dfdfe21ffd6e4fa` |
| `frontend/src/api/research.js` | `2a89dcd177c35347f2fe5dfc99bf353adeaa28c830f81692b5389d2a314a565d` |
| `frontend/src/api/report.js` | `76964f6ffcbb2f919bee828d8da58c017ca000782be4681e4ab57fdafb9aaa31` |
| `frontend/src/components/research/DossierViewer.vue` | `66fec94a0ba45eb446bc54101f93285dd1e66ce236408a8cae905341f9e4da65` |
| `frontend/src/components/research/ForecastReport.vue` | `b9a3953caf028e270402b2224d8c770fd407e2690a9d9e9abb31c968c6b467ec` |

The reviewed source remained frozen throughout this review. Parent documentation changes are outside this source set. No unresolved finding required a private probe or source edit.

Parent acceptance update (27 October 2026): the final browser and live-provider checks were refreshed after the bounded review, and the final native reports were rerendered. The 54-file final-source manifest stayed unchanged throughout; all 68 long-report page images match the previously inspected generation. See verification.md and evidence/verification.json. This is parent acceptance evidence, not an additional reviewer action.
