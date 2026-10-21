# Independent downstream and lifecycle review

Current status: **All downstream P1/P2 findings are closed on the accepted freeze plus the exact two-file mixed-metadata delta and four-file UI fidelity delta.** The accepted baseline has 1,397 passing tests with two skips; affected backend runs have 92 and 61 passing tests, and the final UI gate reports 187 passing tests with a successful production build log. These are separate execution scopes, not a claim that the entire broad suite was rerun on the deltas. See the latest appended closures for current hashes; earlier findings and dispositions are preserved as history.

Historical initial status: **Provisional — workers were active; final frozen-source recheck required.** The initial review and its source identities below are preserved as history; the appended final-freeze dispositions are current.

Review started 2026-10-18 at approximately 12:55 UTC. The reviewer owns only this document. No Git operations, application or test execution, credential access, service operations, or additional agents are permitted or performed. Source reads and SHA-256 checks are the evidence for this pass; proposed reproduction scenarios are not passing tests.

The frozen integration contract is the acceptance authority. Review traces optional-present proof through generation capture, promotion, merge, reuse, simulation binding, report-local storage, publication, APIs, Markdown, translation and actual frontend parent consumption. The initial pass is bounded to approximately eight minutes and will be followed by a focused recheck when the parent supplies the final freeze.

## Initial verdict and actionable findings

**Provisional: three P1 integrity findings and two P2 presentation findings.** These are source-traced behavior findings, not executed reproductions. Anchors below refer to the initially pinned backend/frontend bytes, and to the updated provider hash recorded below. Parent acceptance must exercise real publication, API and Markdown export paths without bypassing their guards.

### P1 — A warm client accepts a valid stale envelope with the same generation ID, including an unsealed predecessor

**Anchors:** `deerflow_bridge/news_signals.py:448-456`, `:471-483`, `:611-630`, updated SHA-256 `bcc801907a5735b3ad0771301cce5486edb3b0bb943d87347f978945c009c5de`.

`_current()` and `snapshot()` compare only question/language/cutoff and `_bound_generation`; the client does not pin the sealed digest or remember that sealing has occurred. `seal()` returns any currently sealed envelope with that generation ID. An internally valid replacement with the same ID but different items is therefore accepted. More concretely, restoring the earlier valid **unsealed** envelope for that generation makes `_store()` accept new results after this client's successful seal. This matters before orchestrator capture: later consumers can bind the replacement as though it were the originally sealed research evidence. The stronger report-local audit guard does not close this producer boundary.

**Focused fix:** Once a client observes or produces a sealed capture, pin its digest and sealed state for subsequent snapshot/replay/store/seal operations, while continuing to permit legitimate pre-seal gathering. A stale predecessor must not reopen acquisition. Preserve normal fresh-process loading of a valid already-sealed capture.

**Suggested reproduction:** Use the real ContextClient/store; save the unsealed JSON after one result, seal A, then replace the file with (a) a valid different sealed envelope retaining A's ID and (b) the saved unsealed predecessor. Assert `snapshot()`, repeated `seal()`, cached replay and `record_result()` reject the changed proof, with no transport or new writes. Existing deletion/changed-identity tests do not establish this same-ID, valid-digest case.

### P1 — Resume treats a missing previously declared capture as permission to recover or reacquire research

**Anchors:** `backend/app/services/pipeline_orchestrator.py:12629`, `:12645-12655`, `:12674-12676`, `:12691-12718`.

When the research contract manifest exists and its declared `news_market_context.json` has been deleted, `_load_news_context()` returns missing-compatible `{}`, and `_validate_research_contract()` fails. The strict error at line 12648 is conditioned on the file still existing, so deletion bypasses it. `_reuse_research` remains false and execution proceeds into synthesis recovery or fresh research. The registered-stage test calls `_validate_reuse()` directly; `_run()` takes the manifest branch first and never calls that guard in this case. Thus a modern declared capture that disappeared is handled like an old run that never had one, contrary to the no-silent-reacquisition proof boundary.

**Focused fix:** Consult the existing contract/stage declaration when distinguishing genuinely absent legacy context from missing required proof. Fail before recovery/research whenever the prior generation declares the capture and it is absent or invalid. Preserve absence compatibility for manifests that never declared it.

**Suggested reproduction:** Promote a complete single-lane generation containing context; mark research complete; remove only its context file; resume through the real `_run()` entrypoint with all research/recovery dispatches instrumented to fail if entered. Expect a provenance failure and zero acquisition/recovery calls. Repeat with an old context-free generation and confirm existing reuse behavior. Include the contract-present case; the current direct `_validate_reuse()` deletion test does not reach this branch.

### P1 — A capture added after consumption is downgraded to optional enrichment failure before PREPARE

**Anchors:** `backend/app/services/official_data.py:160-166`; `backend/app/services/pipeline_orchestrator.py:13531-13547`; `backend/app/services/news_market_context.py:163-164`.

Capture a context-free research generation, then add a valid sealed context before simulation binding. `bind_simulation_research(... expected_generation=...)` correctly rejects the different file set. Its caller rethrows only when the **old** consumed file map already contains `news_market_context.json`. For this late-addition case it records optional official-data degradation and continues without a binding. The report context loader subsequently sees `status=missing` and returns None. This silently omits a new present capture and loses the explicit consumed-generation failure; malformed late additions follow the same downgrade. The binding helper's direct rejection alone does not prove the orchestrator stops.

**Focused fix:** Treat context presence in either the consumed generation or the current handoff/declaration as requiring strict failure on binding errors. Preserve optional official-only degradation when context was and remains absent.

**Suggested reproduction:** Drive the ordinary pipeline PREPARE branch, insert a valid sealed capture after `capture_research_generation()` and before binding, and assert preparation/report dispatch is never reached. Repeat with malformed present context. Keep a control where context stays absent and the historical optional enrichment failure still degrades. Do not replace the production binding helper with a successful stub.

### P2 — The final Markdown table drops the actual quote values, units, outcome and quote timestamp

**Anchors:** `backend/app/services/news_market_context.py:141-154`; `backend/app/services/report_agent.py:3593-3600`, `:13480`; `frontend/src/utils/sourceContext.js:54-64`.

The final report renderer emits provider/type, title/link, publication/retrieval timestamps and a basis string only. Store normalization retains `price_unit`, quote aliases, literal-Yes prices, outcome, `quote_at` and forecaster counts, and the UI uses these fields, but none of them reach the report's deterministic source table. For the supplied Kalshi fixture the durable capture contains bid 0.40 / ask 0.44 / last 0.41 and USD_per_contract; exported Markdown contains only the basis label. A report consumer cannot inspect the actual comparison or its units, and retrieval time cannot replace the unknown quote age. The table is also the deterministic context injected into report prompts, so this information is lost there as well.

**Focused fix:** Render bounded explicit stored values, units, outcome and quote time, retaining null-as-unknown and context-only limitations. Keep source-reported probability distinct from quote price and do not infer either. Preserve the sealed envelope unchanged.

**Suggested reproduction:** Feed the actual market adapter result through `ContextClient.record_result()` → seal → promotion → simulation binding → ReportAgent → real final audit/publication → Flask report and Markdown download. Assert stored bid/ask/last, unit, outcome, and explicitly unknown quote age survive in both final Markdown and export. Include zero, missing prices, and a community-forecast count so it cannot be relabeled dollar volume. Current title/URL/basis assertions do not establish this output requirement.

### P2 — The shared UI displays research-local source_ref as if it were a report citation

**Anchors:** `frontend/src/utils/sourceContext.js:50`; `frontend/src/components/research/SourceContextPanel.vue:30`; actual report parent `frontend/src/components/research/ForecastReport.vue:266`.

The backend correctly preserves the original sealed `source_ref` and renders direct URLs without adopting its S namespace. The shared panel renders that same original value as an unqualified `[S87]`. In a final report whose cited-only references have been reordered, that label can be absent or point to an unrelated source. The report test explicitly preserves S87 while changing the report ledger, so this is an actual supported carrier shape. Vue escaping makes the text safe, but does not make its citation meaning correct.

**Focused fix:** Hide the raw research reference in the final report, or label it explicitly as an original research-ledger reference in both languages. Continue using the actual item URL; do not mutate/remap the immutable capture to fix presentation.

**Suggested reproduction:** Use the real ForecastReport parent with a report reference S1 pointing to another URL and context with original `source_ref=S1` (also test S87 absent from the final appendix). Assert the panel shows the correct direct link and no unqualified ambiguous citation token. Repeat in Chinese and verify the captured envelope digest stays unchanged.

## Coverage, positive notes and limits

- The official-data generation extension includes optional context bytes and validates a present envelope before hashing. Its direct expected-generation check rejects a valid different capture; absent legacy captures retain the historical file map. `load_for_simulation()` uses the verified handoff and rechecks the binding, without a graph-based context search.
- Research contract enumeration/promotion includes the capture; merge invokes the bridge owner, deduplicates provider/capture identity, removes lane-local references and keeps canonical `prediction_markets.json` separate. Fork shares the base handoff and re-enters normal research/reuse handling. The deletion issue above is therefore relevant to fork/resume, too.
- All production ReportAgent construction sites found under `backend/app` pass the carrier: ordinary pipeline, seed/ensemble through `_run_one_seed`, manual generate and manual chat. Legacy missing binding returns no context. Seed binding rejects an invalid parent proof before starting its simulation. This is static call-site coverage, not execution of each path.
- The actual store normalization in `news_signals.py` was inspected alongside `normalize_kalshi_market()` and `_polymarket()`: typed units, rules, Yes/No labels, explicit unknown quote age, literal-Yes prices and source-price metadata are allowlisted. `test_market_metadata_survives_real_store_and_raw_hash_is_preserved` targets real storage rather than a presentation-only dictionary. The metadata-loss finding is at Markdown consumption, not the current normalization allowlist.
- ReportAgent detaches constructor input; report-local storage refuses a different existing capture; the final audit compares consumed and stored captures, records generation/digest and verifies the deterministic block exists. Publication rechecks the local capture against the audit and rejects deletion or valid replacement. Translated publication recursively requires the primary publication check, so the primary context guard is also consulted for translations. Translation-specific runtime behavior was not exercised.
- Report API payloads withhold unaudited Markdown/section drafts. The report and dossier APIs read their explicit local carriers. SourceContextPanel is actually consumed by DossierViewer and ForecastReport; frontend tests render those parent SFCs through their existing carrier/load paths in both languages. Text interpolation and HTTP(S)-only, credential-free links prevent direct HTML/javascript insertion in the panel; report Markdown text/link escaping is also present.
- No new-provider injection into automatic market anchors, official datasets or numeric world-state facts was found in the inspected integration seams. This is a bounded source review, not an exhaustive repo-wide noninterference proof. Missing/off, malformed, symlink, oversized, resealed, source-order and report-local replacement scenarios are present in focused tests; none were run by this reviewer.
- `test_oddsense_workflow.py` uses real deterministic report finalization, publication, Flask routes, Markdown download and exporter output rather than stubbing publication admission. Its report-writing/model content is controlled; it does not establish live providers, ordinary orchestration of the entire simulation, every alternate entrypoint, or actual browser interaction. The independent review must not convert its source presence into a passing execution claim.

## Final focused recheck requested from parent

After ownership freezes, supply exact final hashes and execution receipts. Recheck the five findings against those bytes, the same-ID stale producer case, the two actual orchestrator exception/recovery branches, real-store-to-Markdown metadata, citation presentation in both parent views, and primary/translated publication after local valid replacement or deletion. Retain real publication/API/Markdown export admission in the parent E2E. No broad infrastructure work is requested.

Initial review document is the only reviewer write. The coordinator owns implementation fixes, issue tracking, handoff/Git delivery and executable verification.

## Initial source identities

SHA-256 captured during initial inspection at approximately 12:57 UTC. Concurrent writes can invalidate these identities; the final recheck must compare all reviewed files again.

| File | SHA-256 |
| --- | --- |
| docs/handoff/oddsense-integration/integration-contract.md | 3322e02f6e617c72cd02df9e72448c628c86b8b95026d1af27358edf825c02b6 |
| backend/app/services/pipeline_orchestrator.py | 4a9a97189e6299555757075709012ca2843334e326f6f1360d5bb6e52940e3ab |
| backend/app/services/official_data.py | f8e9f68fe8f51dfb95989d707b78cdcbe72fdc27ec059c1f8fd885aae18af959 |
| backend/app/services/news_market_context.py | 145a87a9abe4ceef5b74783594ac83b191ddf28e36684e2fc9b18387d2e1388e |
| backend/app/services/report_agent.py | a0081e4d6b46561b4592a25c58eea2c8a77328548d33ce8144ce4e63125d81b8 |
| backend/app/api/research.py | 6d0c1ab9fab189540ab2da9bee602510a6b33aa662f9addcc652e993dead2a37 |
| backend/app/api/report.py | e5e394f7c9cbbb46a413228e6829a7a6f5cb11d40cc9d566eba80fd728334cea |
| deerflow_bridge/news_signals.py | 9643a06fd77b7a8ff6d6d54dcc4a10044c0ca7540db0511595b5309d46af0cf9 |
| deerflow_bridge/market_intelligence.py | 6fb7dbb8622460e9be39dbedeb37bd647f8fb2b04e48ffe1b311695d65e2733a |
| frontend/src/utils/sourceContext.js | 955aef5af13fbed2ebaa9ed9db0bbe9d4195b74ce386116e1bb70b78888424dd |
| frontend/src/components/research/SourceContextPanel.vue | 590d03be229ecd53fca451fdd617ef249ffe436e825fb94c4e16626600a1f31d |
| frontend/src/components/research/DossierViewer.vue | 2c604110825f9c7974bd2ad193bed80594d3a6d8e4cf2fb2e63f9f874869041e |
| frontend/src/components/research/ForecastReport.vue | 8714d947e95bff1f0266251c87cf31c84783458f77efb070f532020cf347e3cc |
| backend/tests/test_news_context_pipeline.py | 3ae41abb1f9dd75bdfda55c11ac2365fe2431b3dd345fdb00edc9272f4c6bad2 |
| backend/tests/test_news_context_reports.py | 77bb8ff36425f7e0492809202432eeaf4a6fd0685f46d9f02bfc47258f06c4a5 |
| backend/tests/test_oddsense_workflow.py | 09ddf756751d2d21d18352a84ac19a73387fba12523e1d0da1ce8ac300e08ee4 |
| frontend/tests/sourceContext.test.mjs | 708c0b346b6394c909877c579e708b2a1780585119797cdc88d2de8b36d0fa33 |
| frontend/tests/sourceContextPanel.test.mjs | 13f0a83e377c427f14ec40e0470dfb1fbe81ab61083a72c1d99224a7cdc725c1 |

## During-review drift and additional source identities

At 12:58:26 UTC the contract and all initially pinned backend/frontend production files remained unchanged except `deerflow_bridge/news_signals.py`. Focused test files also changed while workers remained active. The provider stale-generation finding was checked against the newer bytes and exact anchors above; this is still not a final freeze.

| File | Updated / additional SHA-256 |
| --- | --- |
| deerflow_bridge/news_signals.py | bcc801907a5735b3ad0771301cce5486edb3b0bb943d87347f978945c009c5de |
| backend/tests/test_news_context_pipeline.py | 2b4da4738a329c70b6ab5db53d1cd96bc7193d0ceb57b064c4934e656ee79189 |
| backend/tests/test_news_context_reports.py | 752ecc0dc88ba82b7004a6a4e927428161c41a57334f9cd2bdea8883b8d2fe18 |
| backend/tests/test_oddsense_workflow.py | e7bafbe91fbd6624d2b3daf4732c02867d6408ee2b21b38031ddaaab7fa3701a |
| backend/tests/test_news_signals.py | ac68b48eeaacabc6365ccaaaa7db27c86cdb9952238537cca470a6d11e54b90b |
| backend/tests/test_market_intelligence.py | 0f53767b7f2f6bacb10595ae86dd6351ca2c8550ba83c2036ba85ed747fa2b64 |
| backend/app/api/sdk.py | 56ebd542e406b6399a94a2225afda48c3ee9e432f0610ac9fd1ee67ef530fcb1 |
| backend/scripts/export_demo_site_data.py | 1d8d334cbf72a96940399f041472a7a094b3f2be426442e783a905a5cd47602b |

## Final focused recheck — 2026-10-18, 13:21–13:25 UTC

The parent designated `/private/tmp/drf-oddsense-final-joint-vksogbeu` as the final source freeze. Its `oddsense-source-manifest.json` SHA-256 is `9422d4a0fceead2fe87f3d9cabcf62b8637ea7ea40d355d47e7ee6cedf984c16`. A standalone read-only hash comparison verified **all 1,691 listed frozen files** against their expected byte counts and SHA-256 values, with zero frozen-source mismatches. No application modules or tests were imported or executed by this reviewer.

The same manifest was compared against the active worktree. At the comparison time all manifested application/test files matched. Two handoff documents had drifted:

| Parent file | Frozen SHA-256 | Observed parent SHA-256 |
| --- | --- | --- |
| docs/handoff/oddsense-integration/market-implementation.md | eba2818c41073aa5d4897d41fff0c9c48b0cc901983154a94638e32d008c3215 | 7806114aa6e3c4b8f6aac0c7dd0647472a21e054545a341ca588fb071341ccdc |
| docs/handoff/oddsense-integration/providers-implementation.md | 0e2105bed888206585ca732cf89b12ad03737fc124cc16afab14a706543f5d07 | 14902d70a1baa082e54d47e39fec5a6538d014628d94f1df32f92f608d66d43d |

This reviewer subsequently appends only to this owned review document. Parent documentation drift does not change the reviewed frozen code identity, but the whole active tree must not be described as byte-identical to the freeze.

### Disposition of the five original findings

| Original finding | Final disposition on the exact freeze | Source and execution evidence |
| --- | --- | --- |
| P1: same-ID valid replacement or unsealed predecessor accepted by warm client | **Addressed.** The client now pins `_sealed_digest`, observes both sealed state and digest, rejects rollback/replacement, and observes loaded proof even in repeated seal. Fresh identical sealed replay remains supported. | `deerflow_bridge/news_signals.py:447-479`, `:497-506`, `:636-658`; joint JUnit passes both `test_observed_seal_rejects_same_id_rollback_or_resealed_modified_capture` cases and the reopened sealed replay test. |
| P1: declared capture deletion enters recovery/reacquisition | **Addressed.** `_research_declares_news_context()` consults present bytes, consumed files, research contract, stage manifest and state artifact declarations. Real `_run()` checks declaration against missing proof before recovery, independently of report existence. | `backend/app/services/pipeline_orchestrator.py:4413-4425`, `:12663-12665`, `:12684`; joint JUnit passes the real `_run()` deletion case and legacy-never-present control in `test_real_run_declared_deleted_capture_fails_before_recovery`. |
| P1: late context addition is swallowed as optional official enrichment failure | **Addressed.** PREPARE's exception branch consults current presence/declarations as well as consumed-generation files, so both valid and malformed late additions fail before prepare/report dispatch. | `backend/app/services/pipeline_orchestrator.py:13569-13583`; joint JUnit passes all three `test_real_prepare_rejects_late_context_addition` cases, including the old official-only degradation control. |
| P2: actual quote, unit, outcome and quote age absent from deterministic final Markdown | **Addressed for the reviewed context-only report path.** The adapter now renders stored native/alias prices, probability and its basis, units, outcome, explicit unknown quote age, rules and relevant horizon/threshold/count fields. It preserves zero/null distinctions and bounds whole rows. Exact metadata is restored before final audit using SHA-bound unique HTML boundaries and report-local capture equality. | `backend/app/services/news_market_context.py:159-204`; `backend/app/services/report_agent.py:3596-3656`, `:9616-9632`; real-store report-sequence tests pass both cases. The joint four-case workflow reaches real audit/publication/API/download/export and passes. A separate mixed official/context language-audit defect remains below. |
| P2: original research S reference looks like a final-report citation | **Addressed in source.** The shared panel labels it `Original research ledger reference` / `原始研究来源台账编号`, while retaining the actual direct URL. The sealed carrier is unchanged. | `frontend/src/components/research/SourceContextPanel.vue:30`; `frontend/tests/sourceContextPanel.test.mjs:301-330` renders the actual ForecastReport parent with conflicting S1 and absent S87 in both languages. This reviewer did not run frontend tests, and the Python joint receipt is not frontend execution proof. |

### Remaining P2 — Mixed official-data/context reports overwrite the metadata-aware language audit

**Exact anchor:** `backend/app/services/report_agent.py:10202-10209`, SHA-256 `77475afcac5fd1fac7e65bf22469970b477ee117afa73a4117942be1fbc6750e`. Related detector: `backend/app/services/report_lint.py:535-570`; hard publication failure: `backend/app/services/report_agent.py:9956-9959`.

The final audit first calls `_audit_context_metadata_lint()`, which correctly removes only exact validated context metadata before measuring language contamination. When `self.official_data` is also nonempty, the following branch **overwrites** that result with a second detector pass that excludes only `_official_canonical_line()`. Original-language context metadata is included again. For example, a Chinese report with a valid English settlement rule such as `Resolve from the official annual capacity release published at year end.` is flagged by `_LATIN_PROSE_RE`; an English report with a Chinese original title has the corresponding problem. The source context is appended before the final References section, so the detector's reference-title exclusion does not protect it. Any positive contamination count becomes a hard publication failure. This makes valid mixed-source reports fail despite the newly correct standalone context exemption.

**Narrow fix:** Apply one combined exact-metadata predicate to the final language audit, covering both validated official and validated context rows/markers. Preserve normal detection for authored or changed/forged rows; do not exempt by heading, arbitrary marker text, provider name, or an entire unvalidated table.

**Suggested reproduction (not executed by this reviewer):** Extend the actual report-sequence test with a real nonempty official-data carrier and a sealed context containing the long English rule above; generate a Chinese report through final audit/publication/API/Markdown export. Expect zero contamination attributable to canonical metadata and successful publication. Repeat with an English report and Chinese original context title. Add a noncanonical authored foreign-language row beside the protected block and verify it still fails. This is a direct control-flow finding on the freeze, not a general request for additional infrastructure.

### Joint execution receipt: complete, with four failures

The parent joint run has now produced `/private/tmp/drf-os-final-joint-20261018-1/completed.json`: `status=completed`, `exit_code=1`, `shutdown_complete=true`, `identity_preserved=true`, `source_drift=[]`. Its recorded source hashes match the reviewed freeze for the listed sources. JUnit reports **1,385 tests, four failures, two skips** (1,379 passed). The five focused backend suites inspected contain 103 news-signal cases, 28 context-pipeline cases, 15 context-report cases, two metadata-ownership cases and four Oddsense workflow cases; none of these has a JUnit failure.

The four failures are all in `backend/tests/test_research_engine_v3.py`:

- `test_e2e_happy_path_writes_every_artifact`, line 742: expected ten H2 headings, observed eleven.
- `test_e2e_prefix_cache_invariants`, line 884: expected `rg.AGENT_TOOLS_SCHEMA` object identity, but the context-enabled schema differs.
- `test_e2e_section_order_survives_out_of_order_completion`, line 922: observed the deterministic `News and market context` section before References, outside the old expected list.
- `test_resume_skips_done_phases_and_archives_a_different_question`, line 959: changed-question run returned 2 rather than 0; its saved meta records `news_context_evidence_corrupt: ContextIntegrityError`.

**P2 acceptance disposition:** The exact joint gate is red and requires reconciliation before release closure. Three failures concern pre-context schema/report-shape assumptions. The changed-question failure reaches a substantive identity/lifecycle boundary: `_open_work_dir()` archives `v3/`, while the root context proof persists and `_configure_context()` rejects a different question. The parent should explicitly reconcile the intended new-question behavior and baseline fixture feature switches with the frozen contract, then rerun. Do not weaken the sealed identity guard or declare these failures passing because the narrow integration suites passed. This review does not infer whether the intended resolution is fixture isolation, adjusted expectations, or a safe archival transition.

The joint `oddsense-workflow.json` is separately useful positive evidence: `stage=complete`, `controlled_scripted=true`, `live_provider_proof=false`, `source_unchanged=true`, `replay_no_new_calls=true`, and no unscripted external intelligence calls. All 18 `source_before` and `source_after` hashes match the manifest; the real publication result is publishable with no reasons, and its final audit hard-passes with the exact context digest recorded. Its four JUnit cases pass. That establishes the controlled production-to-publication slice on these bytes; it does not turn the entire joint gate green or cover the mixed official/context language case.

The earlier `/private/tmp/oddsense-e2e-markers-20261018-1401` receipt independently reports exit 0 and four passing tests, but its test source hash `baee3596124c01af083f044d30128e41ec49069588212448f7e2d27de87034b2` differs from this freeze's `d298dad0628c4e4f74eaf8eefb6091e9d991bb2792b9dadce5b2be3abf98be8f`. It remains historical supporting evidence, not a substitute for the exact joint result.

| Evidence file | SHA-256 |
| --- | --- |
| /private/tmp/drf-os-final-joint-20261018-1/completed.json | ff1702a7b291dfa869eb6857f09a7606513b925b9703d83d23430814473fb528 |
| /private/tmp/drf-os-final-joint-20261018-1/junit.xml | 73e2a4403961ac25d6864d2ad0ba925f0e2bd7950ef023dff243353793015d99 |
| /private/tmp/drf-os-final-joint-20261018-1/oddsense-workflow.json | 28144ad5331f3d20645e713a765a55e300fd66b87d178976f1698b81e93862f6 |

### Exact final-freeze source identities used for dispositions

All paths below are relative to `/private/tmp/drf-oddsense-final-joint-vksogbeu`. Unchanged backend APIs and frontend parent hashes are retained in the historical table above and were also validated in the 1,691-file comparison.

| File | Frozen SHA-256 |
| --- | --- |
| docs/handoff/oddsense-integration/integration-contract.md | 0fb0fffdecea9c7195d678ce65e4422bf4af89f2cd61d01a8dba7c530ceabcb5 |
| deerflow_bridge/news_signals.py | ffc7a2d720bf3943116d4a3ff0636ce77b1134b743b82c361a9af4e8f88e0d45 |
| deerflow_bridge/market_intelligence.py | e5f5525f0c34d651417808c5fd16453df00e0061cb3e02cf6ca4f31c2c796cae |
| deerflow_bridge/linear_research.py | aba8869dbf8386d3afd118f43ab685c4f204b7a590a2036aeb0e2aa4bc2c901b |
| deerflow_bridge/research_gateway.py | f99839713cd2d50bed1580acaa843cc049ed7fe187219372b253e4b9e13b2003 |
| backend/app/services/pipeline_orchestrator.py | a15e36fda51101added494a829d1f1f578b3d3fab53ed259aa5cc540fa8fc894 |
| backend/app/services/official_data.py | 43498ff019b2dac0f5b3cb0ee6a680579dcfe4805116f4214f29e45a764e6963 |
| backend/app/services/news_market_context.py | b52a36170ef81c7760cb14ea46fd762d27144052c91dbc6649e0a5153ab2e136 |
| backend/app/services/report_agent.py | 77475afcac5fd1fac7e65bf22469970b477ee117afa73a4117942be1fbc6750e |
| backend/app/services/report_lint.py | 4d6e5ae17354b6ba21a7f5f8a0767d42794289877d3413c38838b59311bddd83 |
| backend/tests/test_news_signals.py | 75eec3560cc7e8ae6be93bd64ff53e1453253a276113cd496891b048a68c9fc6 |
| backend/tests/test_market_intelligence.py | 4c97eb3e76958b54ec517baf85d6b7884cc9848a2153490dfc68ff502a709298 |
| backend/tests/test_news_context_pipeline.py | 3dc2d555414e25d41054beb2b5c18a41d68a27c9584dd002b38ab800f00931a8 |
| backend/tests/test_news_context_reports.py | 3b2b49bc4396fd6a94db736a4275c3c417697bbd1e97009d9c7e4ace42949aff |
| backend/tests/test_news_report_metadata.py | da733e2cc6e36a97a24e04301adb145eed057defb1f7c6570282df246d7d750e |
| backend/tests/test_oddsense_workflow.py | d298dad0628c4e4f74eaf8eefb6091e9d991bb2792b9dadce5b2be3abf98be8f |
| backend/tests/test_research_engine_v3.py | d8070f98bbf97cc6a45694ea3cd572e539c2c01df5850f9491d78a5dacf577eb |
| frontend/src/components/research/SourceContextPanel.vue | cfbf6b47107b3c75c0860cf380256526bf19960611bdff579b66c2fccc58ac2e |
| frontend/src/utils/sourceContext.js | 955aef5af13fbed2ebaa9ed9db0bbe9d4195b74ce386116e1bb70b78888424dd |
| frontend/tests/sourceContextPanel.test.mjs | f5bb79badfe4bfa965042e315943140048922bf689a3d48cd0a173b4202bacce |

**Closure boundary:** The independent focused review of this exact freeze is complete. The five original findings are addressed. Remaining work is the concrete mixed-carrier language-audit P2 and a green reconciled joint gate; any implementation repair changes the freeze and needs its own source identity and focused recheck. No app/test edits, source execution, credentials, services, Git operations or additional agents were used by this reviewer.

### Final comparison update — 13:25:01 UTC

A second complete manifest comparison still found zero changes in the frozen mirror. Application source in the active worktree continued to match. Workers had changed three test files and six other handoff documents after the initial comparison; this owned review document also differs by its authorized appended recheck. These newer parent bytes are **outside** the reviewed freeze and the joint receipt above. Their presence is not proof that the remaining finding or failed gate is resolved.

| Parent path now outside the freeze | Observed current SHA-256 |
| --- | --- |
| backend/tests/test_news_report_metadata.py | ceb958f276e65ddf6fd7331baeb3ae053798592c4f0e8666e72e7d68b1b1f63a |
| backend/tests/test_news_research.py | 7fbaa25a3ac3f3a7ebb1ad05dd0a0a342a228c84bba77e9fd639515e40533b2d |
| backend/tests/test_research_engine_v3.py | 3a47699a7677f4a5f33c987ee3112aa79d6765df5a87af8369d23f3da81c3d87 |
| docs/handoff/oddsense-integration/backend-implementation.md | c8e2af3ee97ec56b4e79cc439397ffc783678555fc39c00a7c818a81f17cf0eb |
| docs/handoff/oddsense-integration/end-to-end-acceptance.md | 5ea438840b7f214922c99e994b644735ca5971872a2d2a74246559d4e0a927e5 |
| docs/handoff/oddsense-integration/frontend-implementation.md | 4c609e92b29cb4e146ae6739e817c45b1f93c1a4753239f93e1de0ca113392ac |
| docs/handoff/oddsense-integration/market-implementation.md | 7806114aa6e3c4b8f6aac0c7dd0647472a21e054545a341ca588fb071341ccdc |
| docs/handoff/oddsense-integration/providers-implementation.md | c6e4603583aa10a8c42d1361790750daec80c64c084cf6dcb53319966a26018c |
| docs/handoff/oddsense-integration/research-implementation.md | ad7e5a6d55a56f9fc649ef11476ae54968f21cb4cb53ac3476851e34def985a1 |

## Second final freeze and archive-boundary recheck — 2026-10-18, 13:33–13:36 UTC

This section supersedes the first-freeze acceptance disposition only where the new bytes and receipt establish a change. The designated freeze is `/private/tmp/drf-oddsense-final-accepted-ub26ztb5`. Its complete `oddsense-source-manifest.json` SHA-256 is `08aa62f5f0cd29c0daf6db17ee1f34ea1f8ff33e0b844678708a20a0a122bfdc`. A fresh read-only comparison verified **all 1,692 manifested files** against their SHA-256 values, with no frozen mismatches. The active worktree also matched all manifest entries at the initial comparison, before this reviewer appended the authorized review update. This establishes current source identity rather than carrying forward attempt 1's drift assumptions.

### Archive and cache lifecycle: closed on these bytes

No additional P1/P2 was found in the new archive boundary inspected here:

- `deerflow_bridge/linear_research.py:1250-1289` returns the old state immediately for an unchanged valid identity. A context-bearing changed run must have a distinct previous identity, structured prior state, and an old generation/digest binding. The engine loads the old sealed context and compares both generation ID and digest before calling the provider API. Missing/corrupt/mismatched proof fails; it is not treated as permission to create a fresh capture. The unchanged capture is staged beside the old state, and then the old work directory is renamed to `v3.stale-*` before fresh state is created.
- `deerflow_bridge/news_signals.py:387-466` contains the provider-owned archive operation. It restricts the archive beneath the trusted output root, uses the existing root/file lock, validates the expected capture, rejects symlink/unsafe/existing destinations, and uses descriptor-relative no-clobber link/unlink. It verifies inode/link-count/size/mtime identity and fsyncs the preserved archive entry before retiring the active entry. Pre-retirement failure removes only its own newly created link and leaves the original capture/cache registration in place. The inspected behavior preserves evidence and fails closed on interrupted proof; no claim of transparent recovery from every crash interval is made.
- Cache retirement occurs only after successful movement, under the root lock. The old registered client's identity and digest are preserved and `_retired=True` is set; old references reject subsequent use. A fresh `get_context_client()` registration binds the new generation. `news_signals.py:1030-1054` acquires the root thread lock before cache access and releases the cache lock before constructor/snapshot I/O. `_thread_lock()` only briefly holds the cache lock to obtain the lock object; it does not wait for the root while holding that global lock. This removes the archive-versus-lookup inversion identified in the parent change description.
- The operation remains an internal trusted-engine API. The engine does not mutate provider cache internals, and the reviewed agent tool schema/dispatch does not expose archival as a tool.

The joint receipt passes `test_context_on_changed_question_archives_capture_and_uses_new_generation` (`backend/tests/test_news_research.py:491-525`). It exercises the real context-ON engine transition, verifies exact archived capture bytes and old state, a different sealed generation with the new question hash, actual additional fixture acquisition, a fresh cache registration, and failure from the old client reference. Provider archive tests also pass unchanged-byte preservation, nine invalid archive cases, a retirement-unlink failure, and both cached/uncached global-lock-I/O regressions (`backend/tests/test_news_signals.py:1173-1298`). The two-root lock test establishes its asserted locking property; it is not described as an exhaustive deadlock/stress proof.

### Attempt-1 gate failure: closed by the exact attempt-2 receipt

Historical web-only engine fixtures now explicitly set `NEWS_CONTEXT_ENABLED=false` (`backend/tests/test_research_engine_v3.py:49-58`), preserving their strict schema identity and report-order expectations. This is complemented by the separate real context-ON changed-question test above; disabling the historical fixtures is not being accepted as substitute evidence for the ON lifecycle.

`/private/tmp/drf-os-final-joint-20261018-2/completed.json` now reports `status=completed`, `exit_code=0`, `shutdown_complete=true`, `identity_preserved=true`, and `source_drift=[]`. All **33** source hashes recorded by the receipt match this new manifest. JUnit reports **1,399 tests, zero failures, zero errors, two skips: 1,397 passed**. All four formerly failing `test_research_engine_v3` cases now pass. Focused suite totals include 116 news-signal cases, 12 news-research cases, 51 historical engine cases, two metadata-ownership cases and four Oddsense workflow cases; none of those focused cases is skipped.

The joint workflow receipt again reports `stage=complete`, `controlled_scripted=true`, `live_provider_proof=false`, `source_unchanged=true`, and `replay_no_new_calls=true`. Its recorded `source_before` hashes match the new manifest and equal `source_after`. Its actual publication check is publishable with no rejection reasons. This is fresh controlled E2E evidence through real publication/API/Markdown export on the new source identity, not a presumption derived from the earlier green four-case run. The runner also records blocked process/library probes; those remain blocked attempts, not zero attempts or evidence of live-provider activity.

| Attempt-2 evidence | SHA-256 |
| --- | --- |
| /private/tmp/drf-os-final-joint-20261018-2/completed.json | 2f591bcde3d10fcee73643674cbd6b2678c74e33417c27053a0b0869d5dc2759 |
| /private/tmp/drf-os-final-joint-20261018-2/junit.xml | d5f2ec5838ab11ba2d699da4933dd5ab6ef8300b2ddbca8ce8b7efc36d3054a7 |
| /private/tmp/drf-os-final-joint-20261018-2/oddsense-workflow.json | 2154e8d92131f279810a2ebd2a526138cf9cae4842b31d2551eed1a933d11f18 |

### Remaining mixed-carrier language-audit P2: still open, unchanged production bytes

The new freeze changes the provider/engine/archive-related tests but **does not change** `backend/app/services/report_agent.py`, `news_market_context.py` or `report_lint.py` from attempt 1. The concrete overwrite at `report_agent.py:10202-10209` remains: the context-aware language result is overwritten when `official_data` is nonempty by a detector pass that excludes official canonical lines alone. The long original-language settlement-rule/title case described in the first-freeze finding therefore remains supported by the same source trace. The final hard audit still rejects positive language contamination.

The two metadata-ownership tests exercise restoration, unique markers and valid capture replacement; they do not combine official and context metadata in the language audit. The controlled E2E carrier path does not establish that mixed-language mixed-carrier scenario. Consequently the green attempt-2 gate closes the previous gate failure but cannot close this separate source finding. The narrow combined exact-metadata predicate and real mixed-carrier report/publication reproduction already specified remain the requested resolution. No new P1 is open in this downstream review.

### Source identities for this second freeze

Unchanged consumers retain the exact hashes in the first-freeze table. The following changed files and unchanged files relevant to the remaining finding are explicitly pinned to avoid extending acceptance to unreviewed repairs.

| File | Second-freeze SHA-256 |
| --- | --- |
| docs/handoff/oddsense-integration/integration-contract.md | 134a3440d4fede65f5cf2aae979087ee858da9e06fd9bb597c658bad00842761 |
| deerflow_bridge/linear_research.py | d34299e79d751848052c25ab999782cb94068a98d82d0daead97444052b68cd1 |
| deerflow_bridge/news_signals.py | dc0dca47e0dc1c2d07878eb1a851c0c37a9b0c968a80b009e6fcbc97002f287b |
| backend/tests/test_news_signals.py | fc1dd9a5e69cfed2cc5408a9933a61eb32d54e3286e1ab83f1e2cfe71c25185e |
| backend/tests/test_news_research.py | 7fbaa25a3ac3f3a7ebb1ad05dd0a0a342a228c84bba77e9fd639515e40533b2d |
| backend/tests/test_research_engine_v3.py | 3a47699a7677f4a5f33c987ee3112aa79d6765df5a87af8369d23f3da81c3d87 |
| backend/tests/test_news_report_metadata.py | ceb958f276e65ddf6fd7331baeb3ae053798592c4f0e8666e72e7d68b1b1f63a |
| backend/app/services/report_agent.py | 77475afcac5fd1fac7e65bf22469970b477ee117afa73a4117942be1fbc6750e |
| backend/app/services/news_market_context.py | b52a36170ef81c7760cb14ea46fd762d27144052c91dbc6649e0a5153ab2e136 |
| backend/app/services/report_lint.py | 4d6e5ae17354b6ba21a7f5f8a0767d42794289877d3413c38838b59311bddd83 |

**Current closure:** Five original findings closed; attempt-1 gate failure closed; archive/cache delta reviewed with no additional P1/P2; **one previously reported mixed-carrier language-audit P2 remains open on this freeze**. Only this review document was edited. No application/test edits or source execution, credential access, services, Git operations or new agents were performed by this reviewer.

### Second-freeze final drift check — 13:36:23 UTC

A final complete manifest comparison still verifies all 1,692 frozen entries. Parent application and test source remains identical to the new freeze. The parent differs only in this authorized review update and three concurrently updated evidence documents: `provider-review.md` (`d471cae6dc4bb266b996531cc9a05b086effb355e1326125a9131f241badfbd3`), `providers-implementation.md` (`ec30c0440fc740533267e42cb0e11d75d368a0f0b4b7dbc40213b1401d6ce543`), and `research-implementation.md` (`68af1d999840931b6bae46f66886049230b9f6d5622b864f6d0314f531903c2d`), all beneath `docs/handoff/oddsense-integration/`. These documentation deltas do not resolve or change the remaining production-code P2.

## Mixed-carrier P2 final closure — 2026-10-18, 13:45–13:47 UTC

**Disposition: closed. No downstream P1/P2 remains open in the reviewed scope.** This closes the last finding on the exact mixed-metadata mirror `/private/tmp/drf-oddsense-mixed-metadata-green-pw2mud3p`, rather than transferring the previous broad green result to changed code without checking it.

The mirror's `oddsense-source-manifest.json` SHA-256 is `56a3871a683545486b7c8820a42ca23b53632bf7e9d7b0287fa11446e6c027a6`. All **1,692 manifested files** were verified against byte count and digest without mismatches. Comparing the entire accepted baseline manifest with this mirror establishes that the application/test delta consists of exactly these two files:

| File | Accepted baseline SHA-256 | Reviewed mixed-metadata SHA-256 |
| --- | --- | --- |
| backend/app/services/report_agent.py | 77475afcac5fd1fac7e65bf22469970b477ee117afa73a4117942be1fbc6750e | 06f1ab0068d9de12c3e7a0246fabcc040bdbe07ba69c550cbe077a21b54e054c |
| backend/tests/test_news_report_metadata.py | ceb958f276e65ddf6fd7331baeb3ae053798592c4f0e8666e72e7d68b1b1f63a | 0f71333fdf23064fe3dba2d4efbc946deaee2ae1489aa1763d8122655cc8dec6 |

The other differences relative to the accepted snapshot are historical reviewer/worker evidence documents already identified above. At the initial comparison, the active worktree matched every file in this mixed-metadata mirror; this authorized appended review update is subsequent to that comparison. No other application/test change is silently included in this closure.

### Exact fix inspected

The production diff has three localized predicate changes:

- `report_agent.py:3613-3617`: the metadata lint projection excludes a line only when the existing exact validated context predicate **or** the existing exact official predicate recognizes it.
- `report_agent.py:8085-8091`: the translation audit applies the same combined predicate when either carrier is present.
- `report_agent.py:10204-10212`: the primary official-carrier branch now preserves the context exemption instead of overwriting it with an official-only result.

The predicates remain backed by the already inspected immutable context carrier and exact official metadata. The diff adds no exemption for a raw heading, an arbitrary table, an authored paragraph, an unvalidated provider string or an entire marked section. Context digest, report-local equality, marker ownership and the real final publication audit remain in place. No change to acquisition, source generation, market/world-fact eligibility or publication admission was introduced by this fix.

### Red-to-green scenario evidence

The red mirror `/private/tmp/drf-oddsense-mixed-metadata-red-ff1y6kbc` contains the old report-agent hash `77475af...` and the **same new test hash** `0f71333...` used in green. `/private/tmp/drf-os-mixed-metadata-red-20261018-1/completed.json` reports exit 1, preserved identity and no source drift; JUnit records exactly two failures. Both Chinese and English cases fail at the actual `generate_report()` completion assertion because the real final publication audit reports one line of target-language contamination. This confirms the previously static finding with scenario-level red evidence.

The green `/private/tmp/drf-os-mixed-metadata-green-20261018-1/completed.json` reports `status=completed`, `exit_code=0`, `shutdown_complete=true`, `identity_preserved=true`, and `source_drift=[]`. All **eight** source hashes named by that receipt match the reviewed green manifest. JUnit records **92 passed, zero failures, zero errors, zero skips**, comprising:

- Four `test_news_report_metadata` cases, including the same Chinese/English red reproductions.
- Fifteen `test_news_context_reports` cases.
- Four `test_oddsense_workflow` cases.
- Sixty-nine `test_report_official_data` cases.

`test_news_report_metadata.py:25-91` uses a real nonempty official carrier together with sealed context. It calls the actual ReportAgent constructor, `generate_report()`, final audit and publication status in both languages, while acquisition is forbidden. Chinese retains the English settlement rules; English retains the original Chinese title. It verifies zero metadata contamination, preserved source title/rules, zero bid and explicitly unknown quote time. It reads the real Flask report endpoint and exact context envelope, verifies download bytes equal generated Markdown, and checks the actual demo exporter output equals the same Markdown.

Each positive case then appends a noncanonical authored foreign-language paragraph to the document, writes the changed Markdown, and calls the **actual** `_enforce_final_publish_audit()`. Both cases require RuntimeError and a positive recorded language-contamination count. The bare detector is also asserted to recognize the original-language metadata without the exact carrier predicate. Thus passing is tied to validated metadata identity while ordinary authored foreign text remains rejected; the test does not simply disable language detection.

The green workflow receipt separately records `stage=complete`, controlled scripted execution, no live-provider claim, unchanged before/after source hashes matching the green manifest, and a publishable actual report with no rejection reasons. Its source-before mapping explicitly pins the new `report_agent.py` hash `06f1ab...`. This supplements the runner's narrower recorded source list with actual application-source identity for the E2E slice. Publication/API/download/export admission is not stubbed out.

| Evidence | SHA-256 |
| --- | --- |
| /private/tmp/drf-os-mixed-metadata-red-20261018-1/completed.json | c59e92a9a4acbe9c792ebb64dd4c4e5088a6f258dd7d89367b8ae097f2b77714 |
| /private/tmp/drf-os-mixed-metadata-red-20261018-1/junit.xml | 54d724b85cc978dbb3c653d218c309a60147077e9fd34ceee447ed7f18fbbc01 |
| /private/tmp/drf-os-mixed-metadata-green-20261018-1/completed.json | d8c4756235621414dac1c64f77cd3cc9a584e3e356ce536d57b15b4c34a6ca7c |
| /private/tmp/drf-os-mixed-metadata-green-20261018-1/junit.xml | 43b57a111e3a405763b530c8a82cb5777af6ab7fdd5ce1e43f267295c1ea9086 |
| /private/tmp/drf-os-mixed-metadata-green-20261018-1/oddsense-workflow.json | a0b208ef71e3fa20234df41b7a7952ed7aba61b43448669722af960c998e4fad |

The accepted 1,397-pass/two-skip broad result remains evidence for its frozen baseline; the new 92-pass result is affected-scope evidence for the two-file delta. This review does not claim a fresh full broad-suite result or live-provider proof. The additional `/private/tmp/drf-os-final-bilingual-20261018-1` run is tracked separately below when its completed receipt is available; its announced execution alone is not counted as success. Closing this concrete P2 is warranted by the exact fix and the completed red/green evidence above.

Only this owned review document was edited by this reviewer. No application/test source was executed or edited, and no credential access, services, Git operations or additional agents were used.

### Completed bilingual regression and final drift check — 13:48:58 UTC

The additional bilingual receipt is now available and independently inspected. `/private/tmp/drf-os-final-bilingual-20261018-1/completed.json` reports completed, exit 0, shutdown complete, preserved identity and no recorded source drift. All eight recorded source pins match the same reviewed mixed-metadata manifest. Its JUnit result is **61 passed, zero failures/errors/skips**: 38 `test_report_bilingual`, four `test_news_report_metadata`, 15 `test_news_context_reports`, and four `test_oddsense_workflow` cases. This is separate completed affected/bilingual regression evidence; overlapping cases are not added to the 92-pass run as unique coverage, and the historical broad suite remains a separately identified baseline result.

| Additional evidence | SHA-256 |
| --- | --- |
| /private/tmp/drf-os-final-bilingual-20261018-1/completed.json | 93ccae5133b75001859e54ece15d9601e09d0ce46e4ade97825c17f63e27c9ed |
| /private/tmp/drf-os-final-bilingual-20261018-1/junit.xml | 34385bef12765ca121ce27d64b44d51ddc82b3ce89413ab524921f4c9797e5ba |

A final full comparison still finds no frozen-manifest mismatches. Parent application/test source matches the reviewed mixed-metadata bytes. The only parent differences at this check are this authorized review update and the coordinator's `docs/handoff/oddsense-integration/handoff.md`, observed SHA-256 `dcf576bae2ce9b0e1371e7c6443c28c9fbcfb8e04bd073fec1f702a389e8ec33`. **Final review closure: no open P1/P2 findings in the assigned downstream/lifecycle scope on the recorded source identities.**

### Durable evidence confirmation and commit verdict — 13:50 UTC

**Verdict: APPROVE for commit from the assigned independent downstream/lifecycle review. The mixed-carrier P2 is closed; no open P1/P2 remains in this review.** The reviewed report-agent SHA-256 is `06f1ab0068d9de12c3e7a0246fabcc040bdbe07ba69c550cbe077a21b54e054c`; the regression-test SHA-256 is `0f71333fdf23064fe3dba2d4efbc946deaee2ae1489aa1763d8122655cc8dec6`.

The coordinator's durable [receipt index](evidence/receipt-index.json), SHA-256 `3cc0eb82d72becb3d8977c7368e8e147203822ae6e67846e4c76ddc1788bba1c`, was read and **all 13 indexed artifact hashes verified**, with no mismatch. The durable [92-case completion](evidence/mixed-metadata-final-completed.json) and [JUnit](evidence/mixed-metadata-final-junit.xml), [61-case bilingual completion](evidence/bilingual-final-completed.json) and [JUnit](evidence/bilingual-final-junit.xml), and [two-case red completion](evidence/mixed-metadata-red-completed.json) and [JUnit](evidence/mixed-metadata-red-junit.xml) preserve the previously inspected exit codes and counts. The durable [workflow receipt](evidence/oddsense-workflow.json), SHA-256 `5ec21be03c57f9ba4b6607100d535ce95f9958cf935c71f4556570bc58b3e75b`, reports complete controlled execution, unchanged before/after source pins, no live-provider claim, and the fixed report-agent hash above. It is a separately identified durable workflow receipt, not conflated with earlier run-specific workflow digests.

At the fresh comparison all 1,692 frozen-manifest entries still verified, and the parent's application/test source matched the reviewed mirror. The only manifested parent differences were this authorized review document and the already identified coordinator handoff update. Evidence archival adds documentation artifacts and does not change reviewed runtime source. The exact-predicate inspection, real two-language red/green scenarios, authored-foreign-text rejection, actual publication/API/download/export checks, and completed bilingual regression warrant this closure. The separate baseline/affected execution boundaries described above remain in force.

This verdict is a review result; the reviewer performed no Git operations and changed only this document.

## Final UI contract-fidelity review — 2026-10-18, 13:54–13:56 UTC

**Verdict: APPROVE. Amendment 4's explicit UI rule/basis/horizon presentation is closed on the four exact files below. No new P1/P2 was found, and the mixed-carrier/backend closure remains valid.** This is an additional narrow reviewed delta; the older mixed-metadata mirror itself has not been rewritten to imply that it contained these UI changes.

A full comparison against the mixed-metadata manifest found exactly four changed application/test files, all frontend files listed below. The other manifested differences were the authorized reviewer document and coordinator handoff. Backend source, including `report_agent.py` SHA-256 `06f1ab0068d9de12c3e7a0246fabcc040bdbe07ba69c550cbe077a21b54e054c` and the mixed-metadata test SHA-256 `0f71333fdf23064fe3dba2d4efbc946deaee2ae1489aa1763d8122655cc8dec6`, is unchanged. All four UI hashes were rechecked after inspection with no further drift.

| Reviewed UI delta | SHA-256 |
| --- | --- |
| frontend/src/utils/sourceContext.js | f58d0eb37263c288e5145ab586d8d63f8692ab1446f5eeaaaeb49cba69f06563 |
| frontend/src/components/research/SourceContextPanel.vue | 44be3a9bfeccae31821326b57c7e2276bcb88c7d2a1efab6cb94c46c6998613d |
| frontend/tests/sourceContext.test.mjs | 384d4ba6ab0dc8f9f4afa1c72474d2885432d32a9755c43aa91ce9cf032aa135 |
| frontend/tests/sourceContextPanel.test.mjs | a9ba3d5934f0cd1f30f053183e4ce2f70106d4594d5de5fe5d767128b39ef768 |

### Actual carrier-to-UI behavior inspected

`sourceContext.js:54-64` projects the stored probability/price-basis string, primary/secondary rules, end date, strike type and floor/cap thresholds. These fields already survive the actual adapter/store normalization inspected earlier (`market_intelligence.py:116-138`, `news_signals.py:668-677`); this change makes them inspectable without introducing a competing provider/carrier path. Rules remain bounded text, and the existing timestamp normalizer requires an explicit valid date/offset rather than inventing time semantics.

Thresholds use the existing finite-number formatter, so numeric zero becomes the truthy display string `"0"`, while null/nonfinite values become an absent display value. Existing literal-Yes quote handling still distinguishes explicit null from generic aliases. Basis fields are displayed as supplied strings; no probability, price, sentiment or arbitrage computation is added. The normalization returns a new presentation object and does not mutate the capture.

`SourceContextPanel.vue:40-58` renders the end timestamp, source price basis, and optional native nested `<details>` for settlement rules and thresholds, with English/Chinese labels. All rule/threshold/basis content uses Vue interpolation; no `v-html` or link construction is introduced. Native details/summary supplies the expandable UI control. Long rule text preserves whitespace and wraps within the panel. The existing dossier/report parent integrations remain unchanged and still consume this shared component through their original carriers.

### Focused verification evidence inspected

The new utility regression (`sourceContext.test.mjs:126-139`) checks both rules, zero floor, absent null cap, end timestamp, source basis and byte-for-byte JSON nonmutation. The real compiled panel-SFC regression (`sourceContextPanel.test.mjs:26-40`) renders both locales with a native Kalshi-shaped carrier, checks rule text, source basis, end date and visible zero threshold, verifies a script-shaped rule is escaped into text, and verifies the input JSON remains unchanged. Existing actual parent-SFC consumption and original-ledger-reference tests remain part of the full gate. These are utility/SFC rendering checks, not a claim of a new manual browser click-through.

The coordinator's `/private/tmp/drf-os-frontend-final-rules2-20261018.log` explicitly passes both new scenarios (TAP cases 142 and 143) and ends with **187 tests, 187 passed, zero failures/cancellations/skips**. Its SHA-256 is `42eca9bf08c567bc3896d98b5101bc649d4e95b01b5be89ae0d3c2f78263dcbd`. This is the new log; the durable earlier 185-case log is not presented as evidence for these added cases.

The production build log `/private/tmp/drf-os-frontend-build-final-rules-20261018.log`, SHA-256 `734fc0b8f612639c3ec47760f2f017d918ef9015976e9c49a9cded9f550c52b8`, records `vite build`, 708 transformed modules, generated SourceContextPanel assets, and ends `✓ built in 1.53s`. The unit log completed at approximately 13:53:02 UTC; the panel's final wrapping-style edit is timestamped 13:53:43, and the current production build log completed at approximately 13:53:45. Accordingly, the gate establishes the added behavior and the subsequent build establishes compilation after the final style update; these log observations are kept distinct from a source-hashed guarded backend receipt. The reviewer ran neither the Node tests nor the build.

The reviewed UI display now exposes the stored contract information alongside the already reviewed Markdown/report path. **No open downstream/lifecycle P1/P2 remains; approval for the coordinator's commit is maintained for these recorded backend and UI identities.** Only this owned review document was edited by the reviewer; no production/test source edits, source execution, credentials, services, Git operations or new agents were performed.
