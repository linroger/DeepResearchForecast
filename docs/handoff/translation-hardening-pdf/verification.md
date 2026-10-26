# Translation redesign verification

**Date:** 2026-10-26 (Asia/Shanghai)
**Status:** Complete. Code commit `ddb0ff5c0aeeb27f30a68dd751f232d9d5652bd0` is published on `legacy/codex/translation-redesign`.

## Implemented behavior

One durable SQLite service owns translation jobs and staged attempts. Accepted results bind the exact source, language, resource and visibility scope. Complete returned batches are saved atomically; translation and review resume independently. Ordinary retry reuses accepted work. Explicit refresh stages a replacement before changing the accepted publication.

Immutable generations supply report, dossier, structured display, brief/digest, static-export and PDF readers. One frontend observer handles seven surfaces, reconnects, source/language changes, pending pages and stale responses. Failures remain explicit and bounded; incomplete work is never presented as fully reviewed.

## Acceptance evidence

| Boundary | Verified result | Evidence |
|---|---|---|
| Current checkout, combined backend | **966 passed; 2 pre-existing asset checks excluded.** No failures. | `/private/tmp/drf-translation-combined-final2-20261026/{completed.json,junit.xml}` |
| Frontend in the isolated delivery checkout | **495 passed; production build passed.** | `/private/tmp/drf-translation-delivery-frontend-final.log`, `/private/tmp/drf-translation-delivery-build-final.log` |
| Real browser → Flask → durable store | **7/7 surfaces and 4 language-correct downloads.** Includes failure/retry/reconnect and a 1,001-entry graph. | Private vault `browser/suite.json`; model transport and browser PDF output are controlled fixtures. |
| Native Pandoc/XeLaTeX | Four-column baseline: 4 English/3 Mandarin pages, 120 rows. Dense stress table: 120 rows across 7 landscape table pages per language. Actual copper copy: **35 English/28 Mandarin pages**, 6 images each, 33 URL labels/targets, no content issues. | `/private/tmp/drf-copper-v9-actual-20261026-01/acceptance-summary.json`, `worker-native-pdf.md` |
| Actual live translation | `report_8f0bea34ec96`: **22/22 body sections accepted; 21 reused; 2 new body model calls.** All 34 display fields completed in 4 calls. No issues. | Private vault `live-copper/live-verification.json` |
| Actual live PDF endpoints | **HTTP 200**, PDF MIME/magic and correct English/`.zh` filenames. 35/28 pages, 6 images each, no replacement glyphs. Export made no additional translation calls. | Private vault `live-copper/pdf-downloads-fixed.json`, `final-live-acceptance.json` |
| Report preservation | All **1,878** baseline artifacts still exist; **1,877** are byte-identical. Only the recovered report's metadata gained its admitted Mandarin variant. Canonical Markdown, forecast, audit, citations and all other reports are unchanged. | Private vault preservation and live-acceptance receipts. |
| HEAD-based delivery composition | Initial run: 965 passed, with one missing required classifier dependency. The five-line ambiguous `422/429` cooldown guard was included; **67 affected classifier/filter cases passed**, including the original failure. | `/private/tmp/drf-translation-delivery-final-gate-20261026/`, `/private/tmp/drf-translation-delivery-classifier-20261026/`, `delivery-scope.md` |

Independent core review closed all original findings. Subsequent carrier/core and export reviews passed 130 and 58 cases respectively; these overlap the combined suite and must not be added to its total. The earlier 941-pass/15-failure run remains retained. Its old fixtures were migrated to the real scheduler and generation resolver without dropping tamper, source-change, retry, partial-coverage or no-body-regeneration assertions. Two orphan-owner controls required explicit child-script admission.

The frontend's earlier 494/495 result exposed a test timing assumption. The test now waits for actual source admission and rendering, preserving its zero-reconnect/zero-paid-work assertions. The full 495-case suite and 48 focused repetitions passed; production frontend bytes stayed identical to the successful browser build.

## PDF corrections demonstrated by real inputs

The eight-column table originally overlapped numeric/date glyphs by **2.0224 pt**. The bounded landscape layout now separates them by **34.0919 pt**, while narrow-table raster output remains unchanged. A wrapped URL identifier is checked as a complete visible label and exact hyperlink destination, separately from operating quantities. Ordinary numerical claims retain strict count checks. Longest-first matching handles prefix URLs; disabling Pandoc SMART input preserves double ASCII hyphens in visible labels.

Missing or changed numbers, incorrect URI targets, missing or changed URL labels and merged numeric cells remain negative controls. Rejected exports log bounded reason codes, counts and a source hash without document text or token values. These changes affected rendering only; the accepted report bodies were not regenerated.

## Isolation, evidence and limits

The backend guard is a CPython audit boundary, not an OS sandbox. The combined gate records two denied font-discovery subprocess attempts, 18 denied font-directory reads, eight explicitly allowed guarded children and two liveness probes. These are recorded attempts, not claims of zero probes. No external provider/network or saved-report writes were admitted by those tests. Native fixtures additionally use a narrow macOS sandbox and negative controls.

Browser fixtures allow only their isolated loopback origin and use synthetic source/model transport. They prove button, API, persistence and download behavior, not semantic quality. Live provider evidence is separately recorded for the copper recovery. Model review is not infallible; source-bound validation does not make a financial forecast certain.

The private evidence vault is `/Users/rogerlin/Documents/Codex/evidence/translation-redesign-2026-10-26`. Original report bodies and private full-document copies are not committed. Reproducible code and fixtures carry the public verification procedure; private PDFs, screenshots, receipts and logs are retained with hashes.

Two pre-existing demo-asset availability checks are explicitly excluded and never counted as passing. They reference missing log/PNG files and are tracked in [issue #9](https://github.com/linroger/DeepResearchForecast/issues/9). Vite retains its existing large-chunk advisory; compilation succeeds. No static site was deployed, no new research pipeline was started, and no provider configuration was changed.

## Delivery boundary

The managed worktree is `/Users/rogerlin/.codex/worktrees/translation-redesign/DeepResearchForecast`, branch `codex/translation-redesign`, based on `6ab52f7746bf7ec55e9f9921c71ba4ab08e33c01`. Its separate index preserves the primary checkout's staged `news_market_context.py` and unrelated changes. The delivery policy excludes unrelated forecast-task, grounding, provider, layout and demo changes while including required translation dependencies.

Configured `origin` (`DeepAgentForecast`) is archived. Configured `legacy` (`DeepResearchForecast`) is active, and its GitHub commit endpoint confirms the exact base commit. The feature branch was pushed there successfully, without changing remote configuration or merging `main`. The managed delivery worktree was clean after the code commit. Closing documentation is a separate documentation-only commit; production/test bytes remain unchanged.
