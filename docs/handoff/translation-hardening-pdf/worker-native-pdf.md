# Native PDF verification worker

**Last Updated (UTC):** 2026-10-26T06:07:10Z
**Status:** Complete: final copied-input native export acceptance passed.
**Current Focus:** Parent may integrate the verified owner source and perform its separately authorized live HTTP check.

Current authority is section12 and `/private/tmp/drf-copper-v9-actual-20261026-01/native-pdf-receipt.json`. Earlier synthetic passes and real-input failures below are retained as historical evidence.

## 1. Request and context
The approved translation redesign requires actual English and Mandarin PDFs through `ReportManager.export_document_pdf`, Pandoc and XeLaTeX. Following the user's explicit filename correction, this worker owns only this note and the strengthened existing `backend/tests/render_translation_pdf_fixture.py`; no duplicate fixture was created. Production files belong to the parent/report worker. Preserve all existing dirty work and all 1,878 saved reports. No provider calls, services, dependency installation, saved-data access, commits or identity-HOME changes. Runtime outputs belong only in a new `/private/tmp` directory.

## 2. Requirements and acceptance checks
| Requirement | Scenario and evidence |
|---|---|
| Actual native export | Import current production code after installing the existing main offline isolation; call the public export method; require manifest renderer `pandoc-xelatex` and successful native process evidence. |
| Rich bilingual fidelity | Export a table spanning pages, chart, citation and explicit footnote, Chinese text and ≥ ≤ ±; inspect extracted content, embedded images and page count. |
| Visual acceptance | Render PNGs with Poppler and inspect pages, including table continuations, figure, notes and final rows. |
| Narrow isolation | Exact executable/argument/path admissions in a fixture-only guard subclass; retain saved-write, network and identity controls; exercise negative controls. |
| Reproducibility | Save invocation, source/tool hashes, full native commands, stderr/stdout, PDF/PNG hashes and pass/fail receipts. |

## 3. Plan and decomposition
Read the production exporter and main guard; implement only the isolated harness; prove negative controls before importing the app; run both fixtures; inspect PNGs; report production findings to report worker `01a17634-0c45-7061-ad6d-03c5ef1a9c70`; record exact evidence and limitations. The approved redesign plan is `PLANS.md` in this directory; no separate production design is introduced.

## 4. Progress ledger
- [x] Read root handoff, approved plan, report-worker note, current exporter and offline runner.
- [x] Record ownership and extensive concurrent dirty baseline without changing it.
- [x] Implement fixture-specific guard and negative controls; final run10 passes both Python and native checks.
- [x] Execute real English and Mandarin exports and cache checks; both actual exporter results accepted independently.
- [x] Inspect all seven rendered pages and communicate the two production defects and final passing result to the report worker.
- [x] Complete independent harness review; reviewer Hilbert found no remaining material blocker after finalizer I/O failure was repaired and tested.

## 5. Findings, decisions and assumptions
The existing runner redirects storage before imports and preserves identity variables. Its native subprocess denial is deliberate. The harness subclasses it without editing the production guard, imports the actual application source and calls the actual public exporter. It does not copy/extract/replace renderer functions or mock rendering. Installed Pandoc3.8.2.1, XeTeX/TeXLive2025 and Poppler25.10.0 performed the native work; actual PDFs identify their producer as `xdvipdfmx (20250205)`.

Direct native launches require hashed trusted executables, exact arguments, an approved fixture working directory, and, for the production Pandoc command, exact generated Markdown bytes. They run under an inherited macOS sandbox: no network, writes only below the fresh evidence directory or `/dev/null`, explicit system-resource reads, credential exclusions, and no repository/saved-report content reads. TeX uses `openin_any=p`, `openout_any=p`, and disabled shell escape. TeX/font/temp caches are explicitly relocated; identity variables are retained. Pandoc's XeLaTeX/helper descendants inherit this sandbox and are contained and reaped as an owned process group. The direct launch arguments are captured; descendants are not individually traced as separate Python launches.

## 6. Issues, mistakes and recovery
Two production validator defects were reproduced and repaired by the production owner, without production edits by this worker. First, a rich English PDF containing six Han characters was incorrectly subjected to whole-document contiguous-text comparison. Second, a valid Mandarin PDF's explicit footnote identifier was counted as visible Latin prose. The owner fixed fragment checks and then Markdown AST visible-text extraction while retaining missing-content checks. Red PDFs and rejection audits remain under run04 and run07. Run10 is green on the owner's final frozen bytes.

Harness-only mistakes and recoveries are retained chronologically below: initial native startup read denial, whitespace normalization in an assertion, arbitrary page minimum, a sandbox-regex escaping defect caught using synthetic credentials, and finalizer safety/evidence paths identified by independent review. An initial rc0/publication conflation in a progress message was corrected; final receipts explicitly separate export and safety verdicts.

## 7. Scenario-focused resolution tests
The final command exited0 and the authoritative post-shutdown receipt reports `status=passed`, `export_status=passed`, and `safety_status=passed`. Both language manifests report `pandoc-xelatex`; both returned immutable cache paths; a second export returned the same path without another Pandoc invocation.

| Scenario | English | Mandarin |
|---|---|---|
| Pages | 4 | 3 |
| One continuous table | 120 unique row/value pairs across pages1–3; headers repeated | 120 unique row/value pairs across pages1–3; headers repeated |
| Embedded chart | One raster image on page1 | One raster image on page1 |
| Text | Headings, final marker, Chinese marker and ≥≤± present | Chinese headings/body/final marker and ≥≤± present |
| References | Citation footnote, explicit footnote body and clickable source link present | Citation footnote, explicit footnote body and clickable source link present |
| Production content gate | No issues; Latin token and unique coverage1.0 | No issues; Latin coverage1.0; Han bigram coverage0.9889 |
| Visual review | All4pages inspected, no clipping/overlap/missing glyphs | All3pages inspected, localized TOC/figure label, no clipping/overlap/missing glyphs |

All seven run09 PNGs were viewed individually. The final run10 PNG hashes exactly match those seven inspected images; the final files were rehashed. This equivalence is recorded in `visual-inspection.json`, separate from the machine-only native receipt.

## 8. Verification summary
Final evidence root: [`/private/tmp/drf-native-pdf-20261026-10`](/private/tmp/drf-native-pdf-20261026-10).

Exact executed command (from the checkout):

```sh
backend/.venv/bin/python -I -S -B backend/tests/render_translation_pdf_fixture.py --execute-native --output /private/tmp/drf-native-pdf-20261026-10
```

For a repeat run, choose a new absent direct child of `/private/tmp`. The harness deliberately pins the owner's renderer/artifact source hashes; update those only after an authorized owner supplies new frozen bytes.

| Evidence | Location in final evidence root |
|---|---|
| Post-shutdown acceptance and separate safety/export verdicts | `native-pdf-receipt.json`, `completed.json` |
| Actual argv and interpreter flags | `invocation.json` |
| All64direct native commands, working directories, exit codes and output logs | `native-commands.json`, `command-*-stdout.txt`, `command-*-stderr.txt` |
| Exact native executables and SHA256s | `native-tools.json`; version outputs are first3commands |
| Source hashes and guard events | `completed.json`, `events-*.jsonl` |
| Python controls and native OS controls | `negative-controls.json`, `native-negative-controls.json`, `native.sb` |
| Real fixture input and actually submitted rewritten Markdown | `en/en.md`, `zh/zh.md`, `submitted-en.md`, `submitted-zh.md` |
| Poppler text, rendered PNGs, immutable PDFs/manifests | `en/`, `zh/`; exact PDF paths in `native-pdf-results.json` |
| Visual proof and hashes | `visual-inspection.json` |
| Finalizer I/O failure exits1 | `finalizer-io-negative-control.json` (stdlib-only failure injection, no app import) |

| File/artifact | Verified SHA256 |
|---|---|
| Existing guard `backend/scripts/main_offline_pytest.py` | `5046cf820fa468d8e8ffb2e3fdade1d20fca2f0bd56ee15eabdff51c223c02be` |
| Owned `backend/tests/render_translation_pdf_fixture.py` | `c17b9504c51fb33727731d3efdf67a153bc6e619792c13615498a5ae51b8fc41` |
| Owner `backend/app/services/report_agent.py` | `13fd157ed2c7661a2099dad3b927f4173a6f8fcb9abeb242ec21b14e25588583` |
| Owner `backend/app/services/translation/artifacts.py` | `b2fd31f8e3b69f43173b34253730c5f3c36efd6d7176fdad75e6cfd9bd8d3e36` |
| Final English PDF | `92c4fcd2846590598e9228bac68e5d460fdb8ebb50af62e37b50729c0ab04085` |
| Final Mandarin PDF | `25bc873d7c0f9c9f488d861f5a3c204ac59273cd40fde13592547908ace5fc81` |

There are47tracked source hashes with no run-time drift. All64native process groups closed. The11Python negative controls passed; the native controls demonstrated an exact loopback `connect` OS permission denial, out-of-root Pandoc write denial, synthetic private/credential read denial, and TeX paranoid-write rejection, paired with a successful fixture-local Pandoc read/write. Expected blocked Python controls count two networking attempts, three saved-data operations (including a symlink attempt), one external write, one credential read, one identity change and three unregistered-command attempts. App imports additionally attempted two denied font-discovery processes and18denied font-directory reads; these are explicitly classified and never described as zero attempts. No unexpected provider/network/saved-write events were accepted. Ruff and AST validation passed; `-O` is rejected before output creation.

Independent reviewer `01a1766b-e0e9-77d0-9f75-fb2d6fe33909` closed all material harness findings after inspecting source and the targeted finalizer-failure evidence. The reviewer did not claim independent visual/native rerun execution; the worker performed those checks.

## 9. Remaining work and next steps
No work remains for this bounded worker. Parent retains broader integration, any later source changes, service activation and delivery. This worker neither committed nor modified production files, the existing guard, or saved report content. The1,878report count is supplied by the parent and was not independently recounted or rehashed; preservation evidence here is the pre-import guard, native sandbox, redirected roots and passing no-escape controls. Runtime artifacts remain disposable under `/private/tmp`; preserve them elsewhere only through the parent's separately authorized evidence workflow.

Next-session prompt: “Read worker-native-pdf.md and run10/native-pdf-receipt.json plus visual-inspection.json. Verify the listed source hashes against the intended integration state. Keep the existing harness as the sole native PDF verifier; preserve parent/report-worker ownership. Only rerun if relevant source changed, using a fresh `/private/tmp` output root and an explicitly updated owner freeze.”

## 10. Updates
- 2026-10-26T05:23Z: Scope expanded by the user to read only supplied private copies under `/Users/rogerlin/Documents/Codex/evidence/translation-redesign-2026-10-26/live-copper/pdf-repro` and HTTP outcome evidence `pdf-downloads.json`. Reuse existing native harness through an isolated driver; write reproducible private outputs only under fresh `/private/tmp`; preserve raw PDFs/content audits and identify minimal synthetic causes. Original saved reports, providers, services, production edits and Git remain outside authorization. Success is a source-backed diagnosis plus owner handoff, distinguishing rendered text loss from validator false positives; previous synthetic acceptance does not establish real artifact acceptance.
- 2026-10-26: Created the worker brief, ownership boundary and acceptance matrix before harness implementation.
- 2026-10-26: User directed reuse and strengthening of existing `backend/tests/render_translation_pdf_fixture.py` instead of creating the initially assigned duplicate. This supersedes the initial harness filename above. Report worker was asked to preserve that file. Frozen owner hashes are report_agent.py `aff53be281fc2ecd0f1ea2596a2072c8a7cd9cb3fab2dd700397551f515c8336` and translation/artifacts.py `b2fd31f8e3b69f43173b34253730c5f3c36efd6d7176fdad75e6cfd9bd8d3e36`.
- 2026-10-26T04:17Z: Python negative controls passed, including saved read/write, external write, credentials, network, identity and arbitrary-process rejection. Native Pandoc loopback access produced an OS permission denial; XeLaTeX rejected an out-of-root write. The first two sandbox profiles aborted Pandoc at startup because opening `/` was denied; a literal-root read allowance resolved this without allowing user-data reads. Evidence roots `drf-native-pdf-20261026-01` through `-03` retain diagnostics.
- 2026-10-26T04:18Z: Actual Pandoc+XeLaTeX returned zero and produced a four-page English PDF, but production content validation rejected it. `/private/tmp/drf-native-pdf-20261026-04/raw-en.pdf` and `rejected-en-content-audit.json` preserve the defect: one raster, all protected symbols/numbers/headings/citation markers, all six source Han characters, 99.69% Latin token coverage; sole issue is the short-Han branch requiring the entire document to be contiguous. Owner acknowledged and is fixing production plus positive/negative regression tests. Harness does not change production. Run `-05` preserved another raw PDF and exposed a harness assertion that compared spaced heading text against whitespace-normalized extraction; corrected the assertion. Further production execution awaits the owner's updated hash.
- 2026-10-26T04:23Z: Owner supplied renderer hash `13d908597e7e4b2b598d47e94e4c27c9840ec5104f47cb12754f914bfa62110c`. The English export now passes production audit and cache reuse. Run `-06` showed the Mandarin fixture occupies three pages, so the arbitrary four-page minimum was corrected to three while retaining three-page-table coverage. Run `-07` completed independent content checks and PNG rendering for both languages, but Mandarin production publication remains rejected: explicit `[^audit]` reference/definition IDs appear to be counted as visible Latin prose. Sole issue is visible Latin content loss, with all120 table row/value pairs, Chinese text, image, citations and note body independently present. Reported to owner; `/private/tmp/drf-native-pdf-20261026-07/raw-zh.pdf` and `rejected-zh-content-audit.json` preserve evidence. An earlier progress message incorrectly equated native rc0 with publication success; corrected immediately when the completed receipt exposed the rejection.
- 2026-10-26T04:23Z: Visually inspected all four English pages from run `-05` and all three Mandarin pages from run `-07`: table headers repeat, final rows survive, figures/footnotes and symbols are legible, no clipping or missing glyph boxes. Automated final acceptance still awaits the owner's second validator fix. Independent harness review led to `-O` rejection, actual argv recording, precise native negative-control diagnostics, native process-group cleanup, accurate native child receipt pointers, explicit credential exclusions, row/value association checks, PNG count checks and rejection of unexpected post-control guard denials. Ruff passes; `-O` exits before creating an output directory.
- 2026-10-26T04:31:11Z: Owner's Markdown-AST footnote fix is frozen at13fd157ed2c7661a2099dad3b927f4173a6f8fcb9abeb242ec21b14e25588583. The new native synthetic credential control caught a regex-escaping error in run08 before app imports; literal-character classes repaired it. Run09 passed both actual exporters and safety checks; seven PNGs were individually inspected. Independent review's final evidence-I/O false-success finding was fixed with an outer failure guard and an actual stdlib-only child exit1 check. Final run10 passed on the current harness,47source hashes remained unchanged, all64native groups closed and final seven PNG hashes matched inspected pages. The worker is complete with production defects fixed by their owner and no production/saved-data/commit actions by this worker.
- 2026-10-26T05:33Z: Actual copied copper input reproduced both public-export rejections on the same13fd157 renderer; safe diagnosis and evidence handed to report worker. English34pages and Mandarin27pages each rendered successfully, but the sole content-gate issue was missing numeric tokens. Visual/glyph-coordinate inspection proves a real2.0224pt overlap between numeric cells in the eight-column official-indicator table. A separate English reference URL identifier is intact but line-wrapped and mis-tokenized. A one-row synthetic fixture with invented numbers, no citations and no footnotes reproduces the table failure in both languages. Prior synthetic green remains historical and does not establish actual-copper acceptance. No production fix or live endpoint retry was performed by this worker.

## 11. Actual copper diagnosis (supersedes synthetic-only acceptance for the live artifact)

Safe complete handoff: [`diagnosis.json`](/private/tmp/drf-copper-native-20261026-01/diagnosis.json). Runtime evidence lives in `/private/tmp/drf-copper-native-20261026-01`; the private input copies were rehashed unchanged after the run. The existing repository harness was reused unchanged through `/private/tmp/drf-copper-native-driver-20261026.py`. Only that driver, disposable outputs and this worker note changed during the follow-up.

| Language | Native render | Actual exporter | Sole audit issue | Missing token counts |
|---|---|---|---|---|
| English | Success;34pages;6rasters | Rejected | Visible numeric tokens | `14473.0559`: expected2/actual1; `60727111`: expected1/actual0 |
| Mandarin | Success;27pages;6rasters | Rejected | Visible numeric tokens | `14473.0559`: expected2/actual1 |

Both audits report zero replacement glyphs, all23headings present, and no missing protected symbols or citation markers. This is a focused diagnosis, not an all34/27page visual acceptance. Exact raw PDFs are `raw-en.pdf` and `raw-zh.pdf`; full private audits are `content-audit-en.json` and `content-audit-zh.json`. They were preserved before production cleanup. `native-pdf-receipt.json` records export failure separately from passing safety, no source drift across70tracked source/input files, preserved identity and complete shutdown.

**Root1: real table-layout failure.** Englishpage8 and Mandarinpage7 contain an eight-column table with equal Markdown delimiter widths. The last digit of `14473.0559` has x-range241.099–247.435pt; the next cell's first date digit starts at245.413pt on the same baseline. The2.0224pt overlap is visible in both rendered pages. Extracted text becomes `14473.05592026-09`. Other long numeric cells also collide. This is not a superscript/footnote fusion and should not be hidden by accepting arbitrary number substrings. Evidence: `table-overlap-proof.json`, `numeric-location-diagnostics.json`, `en/diagnostic-page-8.png`, `zh/diagnostic-page-7.png`. The owner should fix dense-table rendering while retaining genuine changed/missing-number negative checks.

**Root2: exact URL-carrier line-wrap false positive.** Englishpage33 visibly splits the identifier as `6` then `0727111` on the next line. All digits are rendered and the full hyperlink URI remains intact in both wrapped annotation rectangles; the URI SHA256 is `ad063aa506e22eea2ac5514fa208ef50512d9320b127e4693861af8151896be0`. Mandarin keeps the identifier contiguous on page26. Evidence: `url-identity-proof.json` and `en/diagnostic-page-33.png`. The owner should handle verified URL-carrier layout without indiscriminately joining numeric text, dropping digits, or relaxing operating-number validation.

**Minimal native regression.** `/private/tmp/drf-copper-minimal-input-20261026/{full_report.md,full_report.zh.md}` contains only a title, the eight-column header and one invented row. It uses `12345.6789`, date `2026-09`, a signed change and a numeric range. There are no citations or footnotes. Actual native rendering succeeds into a one-page PDF in both languages, but the unchanged production gate rejects missing `12345.6789` and `2026`. Evidence: `/private/tmp/drf-copper-minimal-native-20261026-01`, including raw PDFs, extraction, audits, screenshots and passing safety receipt. This isolates the layout cause from report prose, translation, footnotes and providers.

Exact commands, from the checkout:

```sh
backend/.venv/bin/python -I -S -B /private/tmp/drf-copper-native-driver-20261026.py /private/tmp/drf-copper-native-20261026-01
backend/.venv/bin/python -I -S -B /private/tmp/drf-copper-minimal-driver-20261026.py /private/tmp/drf-copper-minimal-native-20261026-01
```

The three targeted actual-PDF PNGs were rendered under the same native sandbox and visually inspected. `diagnosis.json` records their hashes. Report worker received the initial counts, both root causes, exact evidence paths, geometric proof and synthetic regression. Remaining critical path: owner fixes production layout and URI validation with negative controls, supplies frozen bytes, then actual-copy export acceptance is rerun before any live-service acceptance claim. Original saved reports, model calls, services and Git remain untouched by this worker.

### Owner-fix acceptance preparation

The owner is implementing a render-only Lua filter for tables with at least7columns, using landscape layout and smaller table typography while preserving content, width specifications and multipage longtable behavior. The four-column baseline should remain unchanged. URL quantity treatment will change only when the exact href is independently checked against PDF link annotations. The follow-up driver will admit only the frozen generated filter bytes at their declared temporary path plus the exact expected header arguments; arbitrary Lua files remain denied. Prepared `/private/tmp/drf-copper-filter-driver-20261026.py` fails closed until those owner bindings are supplied. `/private/tmp/drf-copper-pdf-geometry-20261026.py` compares numeric/date glyph rectangles along the actual text direction, including rotated pages, without importing the app. Acceptance requires positive separation on the corrected table, actual exporter acceptance in both languages, intact URL targets, unchanged copied input hashes and baseline regression checks.

On owner source93f33c646b17c75d273c644ab30d7d640e088334c1c4613fdfd02a950e02ef32 and exact LuaSHA3957cd5af880f481a4682f70f967b5af665bc5422f701f49f2f87948d95ec8a6, the minimal native export accepted both languages with zero content issues and cache reuse. The inspected landscape pages show34.0919pt positive numeric/date separation, replacing the original2.0224pt overlap. This first run is deliberately not final acceptance: its old `--version --lua-filter=/tmp/no` negative control was classified as a forbidden read by the new admission subclass, so safety failed. Early source-argument validation now rejects it before reading any path. Read-only admission review found no material flaws. Evidence is `/private/tmp/drf-copper-filter-minimal-20261026-01/visual-layout-only.json`. The owner then identified a visible-URL-label/annotation mismatch case and requested final actual/stress runs wait for a further frozen source; those runs have not started.

### Candidate ded605 results and last URL-label defect

After owner freeze `ded605854262639ace22ad76dc01168c8749857cd9adea8f72ced3ef28a09bf0`, four isolated runs completed under `/private/tmp/drf-copper-final-{minimal,stress,actual,baseline}-20261026-01`. Minimal,120row dense stress and four-column baseline passed both export and safety, including cache reuse. The120dense rows survived across seven landscape table pages in each language; all120numeric/date pairs had34.0919pt positive separation and zero overlap. All seven four-column PNGs were byte-identical to the original accepted baseline. Targeted dense/actual table PNGs were visually inspected and showed clean numeric columns, repeated headers, retained final rows and footnotes.

Actual English35pages and Mandarin28pages had no remaining numeric, protected-glyph, heading, citation or image deficits. Both nevertheless correctly failed the new visible-label gate for one URL: Pandoc smart parsing changes the source's double ASCII hyphen into an en dash in the visible link label while leaving the href intact. Label SHA256 is `fbed75cde88f0e6845bb59ee9c494b37470c2914e14eac9881793fe82398f234`. A tiny synthetic native JSON/LaTeX probe in the actual evidence root proves this occurs in Pandoc's AST, before PDF extraction. `--from=markdown-smart` preserves the exact label and emits safe literal-hyphen/URL LaTeX. No gate was relaxed by this worker. The owner selected that exact reader option, retained strict label/href/numeric negatives, and requested only actual-copy exports be repeated on the next frozen hash; no new broad probes are planned. The versioned `/private/tmp/drf-copper-v9-driver-20261026.py` admits only that exact extra argument and preserves earlier driver/evidence bytes.

## 12. Final actual-input acceptance on v9

**Final source:** `backend/app/services/report_agent.py` SHA256 `64a9ec3b8b8bae889395f30f3dc79116e2cfe6a34826d105e796c599a9014011`. The owner preserved strict URL-label, URL-target and operating-number gates, added longest-first exact URL removal to avoid prefix interference, and supplied a55-case guarded regression result. This worker independently executed the real public export against the unchanged provided copies; it did not rerun or claim authorship of those55 owner tests.

**Final actual evidence:** [`/private/tmp/drf-copper-v9-actual-20261026-01`](/private/tmp/drf-copper-v9-actual-20261026-01). `native-pdf-receipt.json` and `completed.json` were written after shutdown and both export/safety verdicts passed. `real-copper-results.json`, per-language content audits, raw PDFs, immutable caches, all native commands/output logs, original submitted Markdown and exact Lua bytes are retained. `filter-binding.json` binds the generated Lua to the trusted class constant; `filter-negative-control.json` confirms altered Lua rejection.

| Acceptance criterion | English | Mandarin |
|---|---|---|
| Actual public exporter | Accepted immutable PDF | Accepted immutable PDF |
| Pages / raster images | 35 / 6 | 28 / 6 |
| Repeat export | Same immutable path; no second Pandoc render | Same immutable path; no second Pandoc render |
| Content audit | No issues; no missing numeric tokens, protected glyphs, headings or citations | No issues; no missing numeric tokens, protected glyphs, headings or citations |
| Exact URL labels and targets | All33carriers accepted | All33carriers accepted |
| Corrected numeric/date separation | +34.0919pt on landscape page9 | +34.0919pt on landscape page8 |
| Formerly smartened URL label | Exact two ASCII hyphens visible on page35; href exact | Exact two ASCII hyphens visible on page28; href exact |

The source/report/chart copies were read-only inputs. All70tracked source/input hashes remained unchanged through shutdown and were rehashed again after visual checks. All61direct native process groups closed; identity was preserved; no unexpected saved/network operations occurred. The input manifests retain the exact original-copy SHA256s. The unconditioned Poppler numeric-token diagnostic still sees one English URL-ID line-wrap; it is explicitly separate from the now-passing exact-label/exact-href quantity audit, not suppressed by treating arbitrary number fragments as equivalent.

**Visual evidence:** `geometry-verification.json` proves positive separation along rotated text baselines. `final-visual-proof.json` records final table PNG hashes, their equality to the already visually inspected corrected tables, and independently rendered/inspected crops of the exact URL labels. The new URL crops were viewed individually. This is targeted real-report defect verification, not a claim to have visually inspected every page of both long reports.

**Baseline:** `/private/tmp/drf-copper-v9-baseline-20261026-01` passed the current final CLI in both languages, including cache reuse. All seven four-column PNGs were byte-identical to the original accepted run10, which had been individually inspected; see `four-column-visual-comparison.json`.

**Dense multipage stress:** As explicitly accepted by the owner, the unchanged Lua filter's prior `ded605...` evidence remains authoritative for this slice: `/private/tmp/drf-copper-final-stress-20261026-01`. Both languages rendered120unique rows across seven landscape table pages (eight total pages including the title/TOC), with repeated headers, all120numeric/date pairs separated by34.0919pt, zero overlap, clean audits and cache reuse. `longtable-pagination-proof.json` and `geometry-verification.json` record all rows/pages. Middle and tail PNGs were visually inspected. This stress source hash is distinguished from the final v9 actual/baseline hash; no redundant stress rerun was performed after the owner limited the final gate.

Exact final commands, from the checkout:

```sh
backend/.venv/bin/python -I -S -B /private/tmp/drf-copper-v9-driver-20261026.py /private/tmp/drf-copper-v9-actual-20261026-01 64a9ec3b8b8bae889395f30f3dc79116e2cfe6a34826d105e796c599a9014011 actual
backend/.venv/bin/python -I -S -B /private/tmp/drf-copper-v9-driver-20261026.py /private/tmp/drf-copper-v9-baseline-20261026-01 64a9ec3b8b8bae889395f30f3dc79116e2cfe6a34826d105e796c599a9014011 baseline
```

| Frozen item | SHA256 |
|---|---|
| Report renderer, final v9 | `64a9ec3b8b8bae889395f30f3dc79116e2cfe6a34826d105e796c599a9014011` |
| Artifacts module, unchanged | `b2fd31f8e3b69f43173b34253730c5f3c36efd6d7176fdad75e6cfd9bd8d3e36` |
| Trusted dense-table Lua, unchanged | `3957cd5af880f481a4682f70f967b5af665bc5422f701f49f2f87948d95ec8a6` |
| Existing repository native harness, unchanged | `c17b9504c51fb33727731d3efdf67a153bc6e619792c13615498a5ae51b8fc41` |
| Isolated v9 driver | `0f8e590a7010873920c6be80e76ef2fb5fe5b7f42f928852f78854737688ef44` |
| Accepted English PDF | `ca817046516a3ab2a95088903f28019b55ff6457b1df4d5d0d391485bf04820f` |
| Accepted Mandarin PDF | `c89e1a2a30d0bf2ec62ecf2c0c8628a5e93a3b0079f9280a40cd7170b42013b2` |

Read-only reviewer Hilbert found no material flaw in either the exact Lua admission or the final `--from=markdown-smart` admission delta. Ruff passed for the isolated driver. This worker modified no production source or original saved report, made no provider calls, restarted no service and created no commit. All corrections were made by the production owner. The final evidence and completion status were sent to that owner. Remaining parent action is any separately authorized service activation/live HTTP export check; this worker has not claimed that the previously observed live503responses have been rechecked.

**2026-10-26T06:07:10Z closing update:** Actual copied English/Mandarin exports and current four-column baseline pass final v9. Dense-layout, strict URL-label/target, cache, isolation and targeted visual evidence are reconciled above. The bounded native verification task is complete.
