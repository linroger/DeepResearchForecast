# Translation/PDF diagnostic findings

**Date:** 2026-10-26 (Asia/Shanghai). This is diagnosis, not implementation acceptance. No application/test files were modified, no live model was called, and no saved report was exported or changed.

## Recorded issues

| ID | Priority/status | Finding and evidence | Acceptance scenario |
|---|---|---|---|
| TR-01 | P1/open | model_translation.py:409–417 collapses distinct exceptions into generic ValueError. Exact examples exist in report_213f3e2bcc79 and report_8f0bea34ec96; saved-failure-evidence.json records hashes and receipt counts. | Typed safe stage/error codes preserve actionable cause without response bodies or secrets. |
| TR-02 | P1/open | model_translation.py:368–425 validates whole envelopes as all-or-nothing; missing review restarts translation. diagnostic-probes.json reproduces the call sequence. report_agent.py:11495 supplies no previous section receipts to translate_document. | Reuse valid sections; review-only retry does not retranslate; tampered/stale proofs never reuse. |
| TR-03 | P1/open | GraphPanel.vue:350 retains overlay but drops failure/partial status; overlayTranslation.js:75 does not retry failed/partial/interrupted unless forced. Auditor memory-only probes observed zero POSTs for those statuses. | Visible issue and explicit retry reaches one correct POST. |
| TR-04 | P1/open | GraphPanel.vue:356 admits late overlay regardless of graph generation; graph synchronization at:933 does not reset translation state. Auditor memory-only probe displayed graph A's translation in graph B. | Graph/revision/language/unmount changes invalidate stale requests and source-mismatched values. |
| TR-05 | P1/open | ForecastReport.vue:524 does not resume translation polling for existing source Markdown;:980 stops on GET failure while can_generate:false can hide recovery. reportLanguages.js:125 controls eligibility. | Mount during translation and recover after one transient GET failure without duplicate generation. |
| TR-06 | P2/open | WorldStatePanel.vue:68 renders provenance through d(), but:232 omits provenance from visible translation inventory. | A unique visible provenance string is submitted and rendered in Mandarin. |
| TR-07 | P2/open | artifact_translation.py:99 limits graph translation to200 nodes/400 edges; GraphPanel has no coverage disclosure. | Expanded graphs expose real pending coverage and bounded retries make progress; no silent complete status. |
| PDF-01 | P1/open | research.py:740 gets verified_markdown, then:757 rereads the file and renders without rechecking identity afterward. Source-established race, not observed production corruption. | Render the verified snapshot; detect changed source/audit/translation before serving output. |
| PDF-02 | P2/open | report_agent.py:18347 deletes dossier PDF before rendering at a shared destination; no equivalent of forecast per-language lock/cache. | Concurrent exports cannot overwrite each other; unchanged inputs reuse valid PDF; failed replacement preserves prior bytes without serving stale content. |
| PDF-03 | P2/open | DossierViewer.vue:32 uses a raw new-tab link without busy/error/PDF validation; research.py:762 returns generic500 for disabled/failed rendering. | Typed errors, inline message, busy reset and no downloaded JSON/HTML masquerading as PDF. |

## Control matrix

| Surface | Current translation path | Planned scope |
|---|---|---|
| Research dossier: body, actors/events/topics, brief, relationships, markets, official data, sources | DossierViewer; GET/POST /api/research/:id/dossier/translations/:lang | Preserve envelope/identity guards; regression all states and recovery; fix shared backend and PDF path. |
| Forecast body, dashboard, binary forecasts, scenarios, captions/data/context | ForecastReport; report translation task and language-specific data | Repair mount/transient-error polling; review-only and pending-section recovery; explicit PDF language. |
| Graph node summaries, edge/self-loop facts | GraphPanel; /api/graph/:id/translations/:lang | Retry/status, identity/revision, coverage and pending-tail fixes. |
| OASIS personas and social feeds/replies | SimulationView; selected visible strings and digest/context-bound cache | Regress shared backend retry and source/language/round isolation. |
| OASIS world-state panel | WorldStatePanel, own controls with parent language | Add visible provenance to inventory; retain context binding. |
| World-v1 state/actions/commitments/interactions/assumptions | WorldSimulationView; visibility-filtered projection | Regress bounded retry, source/context ownership and all supported visible views. |
| Source/news/market context | Inherits dossier/report controls | Include in parent scenarios; no redundant new button. |
| Simulation after-action record | No translation control, even though it is the completed-run default | Explicit adjacent scope gap; no new independent translation feature in this bounded plan. Existing requested controls are the acceptance boundary. |
| Ontology and logs/application chrome | No standalone ontology translation control; logs/chrome use locale | No invented translation endpoint or standalone tab. |

## PDF contract and render evidence

Interpret the requested language as the language of the report being viewed. The button will explicitly identify Mandarin or English. A reviewed Mandarin view exports Mandarin; the English view exports English. An English primary is addressed through the unsuffixed export path, not blindly through ?lang=en. Downloads use existing accepted artifacts and never initiate translation.

Read-only dependency audit found Pandoc3.8.2.1, XeLaTeX/TeX Live2025, Poppler25.10.0, xeCJK/fontspec/longtable/booktabs, DejaVu Sans/Mono and PingFang SC; backend PyMuPDF1.28.2. An in-memory Chinese renderer smoke retained its heading with zero replacement characters. This establishes dependency availability only. Application-export and visual layout proof remain to be produced after implementation. Existing renderer tests substantially stub rendering; real English/Mandarin multipage fixtures must cover tables, charts, citations, CJK and ≥ ≤ ± plus page raster inspection.

## Audit ownership and limits

Parent inspected saved audit/source hashes and executed the shared-engine no-network probes. Read-only subagent Banach audited translation controls and provided in-memory graph reproductions. Read-only subagent Godel audited PDF routes/render dependencies and reported source-established races. Their results identify regression targets, not completed fixes. Historical translation receipts remain historical; this task needs fresh exact-source acceptance.

## Scope update after user direction

The user subsequently requested a full translation-system redesign. architecture.md and PLANS.md supersede the initial patch proposal. In that redesign, the completed SimulationRecord is included under the shared Simulation language control, reversing the earlier bounded-plan exclusion above. Other findings remain evidence and acceptance cases for the unified architecture, not independent patch work.
