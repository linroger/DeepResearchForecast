# Agent-backed equity research PDF export

**Date:** 2026-10-26, Asia/Shanghai
**Status:** Approved by the user on 2026-10-26; implementation authorized.
**Branch:** `codex/research-pdf-export`
**Base:** main / freshly fetched legacy/main, `033e191fe78fcd7cf81dfc117e3264f3dc02f133`

## Outcome
Each existing Export PDF control starts a bounded background export agent. The agent loads the repository's versioned equity-research-pdf skill, formats that surface's complete saved report in the selected language, checks the resulting PDF, and returns a verified download. The deep-research dossier and forecast report remain separate outputs. Their original research, forecasts, citations, translations, and chart assets remain unchanged.

## Current source evidence
- `DossierViewer.vue` currently opens a synchronous PDF URL. Its source is `research_report.md` or an admitted language variant in `PipelineManager.resolve_handoff_dir(...)`, which can be shared by a forked pipeline.
- `ForecastReport.vue` currently downloads a synchronous PDF through `downloadArtifact('pdf')`. It already guards report/language switches, download errors, filenames and PDF signatures. Its authoritative body is the selected `full_report*.md` file, not the UI metadata/DOM projection.
- Both backend routes use ReportManager directly. No current PDF button runs a skill agent or observes a persistent export job.
- Main's TaskManager is memory-only. It cannot by itself provide restart-safe export identity or durable phase receipts.
- The standalone skill has a strict bilingual input model and manually completed review record. An application adapter must add a genuine selected-language/agent-review mode; copying one language into both keys or automatically setting review booleans is unacceptable.
- Main and the dirty application's current feature branch differ. This work will not merge the separate translation redesign or simulation changes by inference.

Detailed anchors: `evidence/export-paths.md` and `evidence/agent-skill-feasibility.md`.

## 1. Version the skill inside the application
Vendor the tested skill under a repository-owned package location such as `backend/app/skills/equity-research-pdf/`, with its upstream file hashes and clear integration changes. The export agent reads its SKILL.md and relevant schema/review instructions from that package at runtime. Deployment must not depend on `/Users/rogerlin/.codex`, a desktop Codex process, or any global skill installation.

Add the needed renderer dependencies to the backend's declared dependencies and lockfile. Resolve explicit embeddable Latin/CJK fonts using configuration and known local candidates; missing dependencies or glyph coverage produce an actionable export error. Do not change unrelated provider credentials or install into the shared live application's environment.

## 2. Capture one authoritative, immutable report snapshot
The server derives paths and metadata from the requested resource and current source-language selection. It captures selected Markdown, the appropriate citation ledger/source registry, referenced chart assets, translation/publication evidence, and source hashes into an export-owned generation directory.

Preserve existing admission rules: forecast exports retain publication checks; translated dossier/forecast exports retain their own source-bound variant checks. Main's primary dossier reader does not currently apply a separate seal/judge gate; do not invent a claim that it does. The adapter must bind the exact readable source and its current upstream status rather than silently changing research publication policy.

Inventory every visible source component using the existing Markdown parser infrastructure: headings, paragraphs, lists, tables, inline links/citations, footnotes, figures, code/formula/diagram representations and appendices. Add tests for the report structures actually produced by this repository. Unsupported required components fail explicitly; neither a paragraph-only converter nor a code-text replacement for a required diagram is a successful export. All needed rendering/conversion occurs in the isolated generation directory.

Source selection is not language inference: an omitted `lang` selects primary content, which can already be Mandarin. Export an existing admitted language version; do not regenerate the report or start translation of the other language merely to satisfy the standalone schema. All new page furniture and labels use the selected language. Figure-language limitations must be surfaced honestly and resolved using source-backed localized assets where available; an English image is not certified Mandarin because its caption was translated.

## 3. Run a bounded formatting and review agent
Implement a dedicated export agent/service, not a research-pipeline rerun and not a wrapper that only names the skill in logs.

The actual run sequence is:
1. Load the pinned skill and source inventory. Supply complete source sections in bounded batches, with stable component IDs and source/asset hashes.
2. Have the agent choose a constrained institutional layout and source-derived metadata/component treatments. Preserve source text, financial values, dates, probabilities, qualifiers, citation identities and asset associations. Source spans/IDs select content; agent prose cannot silently replace the report body.
3. Build the selected-language structured input and run the skill's actual rendering/validation helpers. The new application mode must keep the paired standalone mode and its tests intact.
4. Perform source/semantic reconciliation and rendered-page review, then at most a bounded layout repair. Persist the actual requests, stage outcomes, exact reviewed artifact hashes and safe diagnostics under the export job. Never fabricate manual/human review flags.
5. Publish only an output that passes exact component, table-cell, figure-position, hyperlink, glyph, embedded-font, page-number and layout checks plus its required agent reviews.

Use the project's configured model transport and accounting where compatible. Text planning/reconciliation and visual page review are separate capabilities. The implementation must preflight image-input support and preserve real image content through the transport; a text-only/CLI fallback cannot count as a page-image review. If the current model lacks that capability, use an explicitly configured compatible reviewer model or return a clear configuration/review error. No silent downgrade or invented visual approval. The runtime capability decision and any remaining configuration requirement will be recorded before acceptance.

Agent calls, output tokens, concurrent jobs, per-stage timeouts and repair attempts are bounded. Reads/polls/downloads never start model work. Prior reviewed generation reuse requires matching source, language, assets, skill, renderer and model-policy fingerprints.

## 4. Add persistent, resource-scoped export jobs
Add narrow start/status/download endpoints for each report surface, with shared implementation where appropriate:
- Deep research: under `/api/research/<pipeline_id>/dossier/pdf-export`.
- Forecast: under `/api/report/<report_id>/pdf-export`.

A POST starts or rejoins the matching job. Status GETs return an opaque job ID, resource/language identity, phase, state and actionable issues; they do not return private source bodies. Download GETs serve only completed, still-admitted bytes from that resource/job. Bind ownership so an ID from another report or language cannot be used to fetch a file.

Use atomic persisted state and process-safe ownership to prevent duplicate work on repeated clicks. Preserve completed phase results across interruptions. Explicit retry resumes only unfinished eligible work within a new bounded allowance; it does not blindly replay an ambiguous paid request. A failed attempt preserves prior valid exports, and a source change prevents stale completion/download. Record cancellation truthfully if provided: stopping UI observation is distinct from stopping an already dispatched model call.

Existing synchronous PDF endpoints remain compatibility readers unless a narrowly necessary change is documented; the updated buttons use the new agent workflow exclusively and do not silently fall back to the old renderer after agent failure. Markdown/JSON exports remain unchanged.

## 5. Wire both original buttons
Replace the dossier's direct PDF link behavior and the forecast PDF branch with one shared export-job consumer. Show clear phases such as Preparing report, Formatting, Checking pages and Ready, with error/retry behavior. Automatically download the selected verified PDF on successful completion. Preserve existing report/language invalidation and add it where missing. Prevent duplicate starts and stale downloads after switching reports/languages or unmounting.

Keep normal product text concise. Surface implementation details only as an actionable error or optional diagnostics. The standalone preview page remains useful as a generated artifact, but clicking the application's Export PDF button does not require users to operate a second application.

## 6. Verify and deliver
Acceptance must exercise both actual UI→API→agent→skill-renderer→download paths, with controlled model transport for deterministic tests and real PDF rendering for layout/content verification. Cover English primary, Mandarin primary, admitted variants, missing/stale variants, fork-shared dossier assets, repeated clicks, source changes, malformed agent responses, rejected reviews, missing images/glyphs, long/wide tables, links/footnotes, interrupted work, failed publication, and stale UI responses.

Reuse `backend/scripts/main_offline_pytest.py` and its existing isolation model; any required renderer-child admission must be narrow and tested. Run relevant existing frontend/backend regressions, the frontend production build, native PDF checks and browser downloads. Independent review must apply to the final source bytes. Historical standalone tests are supporting evidence, not application acceptance.

After deterministic acceptance, perform a small bounded live-agent smoke test only with an already configured compatible provider and isolated fixture copies; report it separately from offline evidence. Do not recover saved production runs, overwrite accepted reports or restart the shared application for this branch. If the configured provider cannot perform the required image review, state the exact missing capability/configuration rather than claiming live success.

Commit only owned files and push `codex/research-pdf-export` to the active configured remote (`legacy`) after checks pass. Do not merge into main or deploy the shared application. Update the topic handoff, feature record, progress log and bilingual user documentation with usage, dependency setup, observed tests, model/review limits and the exact branch delivery.

## Approval boundary
This plan is the concrete proposal required by the user's instruction: “If tasked with a complex feature, create a PLANS.md first describing the approach. Only proceed with coding after plan approval.” Branch creation, source investigation and these documents are complete; no application code or tests have been changed yet.
