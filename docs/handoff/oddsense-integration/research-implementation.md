# Research consumer implementation

Date: 2026-10-18. Status: owned implementation verified; released to coordinator for final integration review. Ownership is limited to research_gateway.py, linear_research.py, deerflow_research.py, config.yaml, test_news_research.py and this record. The coordinator's handoff.md remains authoritative for the complete integration.

The approved OS-1/2/3 task requires actual topic prefetch and tool dispatch in both engines, source-aware snippet versus fetched evidence, bounded agent/run admission, stable schemas, reuse without silent retrieval, and sealing before QA/citation finalization. Provider acquisition and the context store belong to news_signals.py; market acquisition belongs to market_intelligence.py.

| Requirement | Scenario and evidence |
| --- | --- |
| Actual research use | A scripted model calls context tools, reads a publisher page through the existing fetch owner and cites its exact ledger source in the completed report. |
| Stable tools and bounded admission | The same run-level schema object is used throughout agent calls; deadline, cancellation, run and agent caps refuse additional work. |
| Durable provenance | Ledger save/load and sources.json retain provider, publication, retrieval and evidence-type metadata without marking snippets fetched. |
| Resume integrity | Sealed stored context is reused without new acquisition; changed/tampered inputs fail closed. |
| Legacy availability | Trusted runtime registry and scoped allowlists expose context tools even when user YAML predates the change. |

Implementation plan: extend the gateway ledger and static schemas, integrate v3 prefetch/planning/gather/synthesis/sealing, integrate the legacy registry and lanes in parallel, then capture guarded controlled-engine and compatibility evidence from new exact-source mirrors. The source-mirror helper and canonical /private/tmp evidence directories preserve the existing offline guard.

## Progress and decisions

- 2026-10-18: Read the approved plan, frozen contract and shared handoff before source edits. Source inspection confirms fixed v3 dispatch and metadata-dropping sources projection. Delegated only deerflow_research.py/config.yaml to a legacy worker; other workers' files remain untouched.
- 2026-10-18: Provider feature-flag names are not part of the frozen API; research enablement must agree with the provider owner instead of inventing conflicting settings. The provider modules were not present at initial inspection. This is coordination state, not behavioral red evidence.

## Verification

At intake, no application imports or pytest collection had run. Every subsequent check below used a new exact-source mirror and canonical /private/tmp evidence directory, with the original provisioned Python interpreter and -I -S -B. No guard was weakened. The dated entries retain red evidence, corrections and later passing checks.

## Remaining work

The owned implementation and controlled scenarios are complete. The coordinator retains final joint acceptance and independent rereview against final hashes. The latest broader joint run reached research QA, source projection, promotion and consumed-generation binding; its remaining failure was backend report quantitative stabilization. No Git mutations, services, saved runs, credential access, package installation, vendor execution or live models were performed by this worker.

## Dated implementation and verification ledger


- 2026-10-18: Meaningful red captured at `/private/tmp/oddsense-research-red-20261018a/junit.xml`: the real KiqAgent dispatcher returned UNKNOWN_TOOL for a news_search call despite an available consumer callback (one assertion failure, successful imports).
- 2026-10-18: Implemented gateway context schemas/dispatch, shared search admission, snippet provenance, v3 topic news prefetch, planning/gather/synthesis context, resume acquisition freeze, pre-QA sealing and final source metadata. Citation mapping concern was reported: a pre-QA immutable envelope cannot embed a final namespace determined by later QA repairs; the current consumer preserves ledger refs and stores final canonical-URL refs in QA metadata.

- 2026-10-18: The failed legacy child was closed after its transport/DNS error; ownership of its existing deerflow_research.py/config.yaml patch returned to this worker. Its implementation was inspected and completed without spawning another agent.
- 2026-10-18: The initial broad compatibility receipt `/private/tmp/oddsense-research-green-dispatch-20261018a/junit.xml` records 537 passes and four unchanged subprocess-based regex timing cases blocked by the existing process guard. No guard relaxation or test result reclassification occurred.
- 2026-10-18: The gateway control receipt `/private/tmp/oddsense-research-ledger-controls-20261018a/junit.xml` records five passes. A short fixture page was initially refused by the existing fetch validator; the fixture was corrected to a representative body rather than bypassing validation. A real-store run exposed an external-root read in the provider's directory walk; that issue was reported to its owner, who corrected provider-side traversal while preserving the guard.
- 2026-10-18: Citation resolution is now explicit: research calls seal() without source_refs. Capture URLs remain authoritative. V3 presents current ledger markers only inside the report before QA, then QA renumbers them against cited-only sources.json and persists the canonical-URL map as news_market_context_citations. The regression inserts an uncited earlier ledger row so source IDs differ and checks the final map. The extra context section is included in deterministic expected QA heading order; no QA check is disabled.
- 2026-10-18: `/private/tmp/oddsense-research-engines-20261018a/junit.xml` records eight passing consumer scenarios, including full v3 execute with qa.passed=true, actual ContextClient store/seal, planning/gather/synthesis use, actual publisher fetching and final citations, reordered/cited-only sources, sealed resume without acquisition, tamper refusal, and real legacy streamed-turn accounting plus registration/prefetch/pre-judge sealing. Acquisition, model responses and the legacy external judge are scripted; provider/store/engine/citation paths remain production implementations.

- 2026-10-18: The broader receipt `/private/tmp/oddsense-research-regression-20261018a/junit.xml` records 312 passes, 14 failures and 19 setup errors. Failures include former web/data-only schema/outline assumptions, expected changed-question artifact reuse, existing guarded chart subprocesses, unrelated skill-size/content checks and data cases. The 19 setup errors concern absent vendored schema files in the source mirror; they are not behavioral red evidence. No vendored file was copied or executed. The newly actionable empty-unattempted-context outline issue was fixed by omitting empty context presentation.
- 2026-10-18: `/private/tmp/oddsense-research-owned-final-20261018a/junit.xml` records 115 passes across the owned consumer suite, gateway official-data suite and v3 hardening/residual suites. A later joint receipt `/private/tmp/oddsense-research-final-20261018a/junit.xml` records 118 passes and one backend publication-audit failure after successful research execution, source projection and promotion. The failure was reported to the coordinator/backend owner without editing backend-owned files.
- 2026-10-18: Read the coordinator's formal contract amendments. Research validates the internal parent NEWS_CONTEXT_QUESTION_SHA256 when present and otherwise uses the actual direct-run question. A valid multitrack test has been added; it awaits the provider owner honoring that same amended identity. Existing foreign question/cutoff checks remain strict, and legacy synthesis consumes already merged sealed context without acquisition.
- 2026-10-18: Addressed independent review PR-2 in the owned consumer paths. Bounded context_metadata/context_evidence_sha256 now retain supplied literal outcome, numeric values including zero, null timestamps, bid/ask/last, bases/units, count volume, rules/horizon/threshold and original outcome/price arrays. Actual tool messages and writer/executive-summary input retain these details with context-only labels. The real ContextClient.market_compare → ResearchTools.context_query → KIQ → synthesis/source-projection regression uses No-first Polymarket prices and distinct Kalshi dollar/count/rules/unknown-time fields. `/private/tmp/oddsense-research-market-evidence-20261018a/junit.xml` records ten passes with only the pending canonical-parent scenario deselected; the provider's API amendment was not yet implemented in those bytes.

- 2026-10-18: V3 now writes its sealed generation/digest into its existing state.json before synthesis, so a restart cannot accept a valid-checksum rollback or deletion of already bound proof. Capture validation happens before acquisition, using the formal canonical-parent digest rule. Context cancellation closes admission without waiting for a thread holding the acquisition lock.

- 2026-10-18: `/private/tmp/oddsense-research-amended-api-20261018a/junit.xml` records 120 passes and one backend stabilization failure. The canonical-parent two-angle merge and synthesis replay test passed with the implemented provider amendment. The real market test now preserves the production HTTP transport/admission path and replaces only HTTPSConnection responses; it verifies three physical fixture requests exactly match the durable store's market reservation count. The joint acceptance confirmed native 0.41/0.40/0.44 quotes, bases/units/rules/unknown-time in actual tool messages, writers, research Markdown and source metadata before failing the backend quantitative publication gate (quant_passed=false, coverage=0.0).

## Final owned-source release

The final owned gate is `/private/tmp/oddsense-research-release-20261018a/junit.xml`: **117 passed** (11 research-consumer scenarios plus gateway official-data and v3 hardening/residual suites), exit 0. Its exact mirror is `/private/tmp/drf-oddsense-research-release-01wqy4jm`; `oddsense-source-manifest.json` contains the full source receipt. Completion confirms preserved identity, no source drift and no blocked audit events. The only recorded guard events are the three standard app storage redirects. All five implementation/test/config files below were rehashed after the run and exactly match that mirror. This evidence document was then updated with the result; its final text is coordinator handoff material, not executable test input.

| Owned implementation file | SHA-256 |
| --- | --- |
| `deerflow_bridge/research_gateway.py` | `f99839713cd2d50bed1580acaa843cc049ed7fe187219372b253e4b9e13b2003` |
| `deerflow_bridge/linear_research.py` | `aba8869dbf8386d3afd118f43ab685c4f204b7a590a2036aeb0e2aa4bc2c901b` |
| `deerflow_bridge/deerflow_research.py` | `f7ff138fdbaa0cf84625bd92212a13ee8fa914c374c42fe57d7318d0b6214d87` |
| `deerflow_bridge/config.yaml` | `ffdb3bebaec91745aa549a93cc2f994dd7db9ae5bc3963f8fd8eccf66e37a23d` |
| `backend/tests/test_news_research.py` | `827b4b2edf8363234b852312a046818e96176d92ec5dd79c8c4f88b0b620e3d5` |

The exact owned file set is the five table entries plus this research-implementation.md. The failed child was closed before taking over its legacy/config write set. Other workers' paths were not modified. No commits or other Git mutations were performed.

Remaining coordinator actions are final independent PR-2 rereview on these hashes and the joint backend publication/stabilization gate. The 120-pass/one-failure joint receipt is historical evidence for earlier backend bytes; it is not a claim that the complete OS-3 publication path passed. The next bounded rerun is test_news_research.py plus test_oddsense_workflow.py from a new mirror after the backend fix, preserving the final quote assertions and audit gates.

## Final joint-freeze confirmation

The coordinator requested a final check of provider counter migration and the shared integration gate. No production or test files were changed after the owned-source release above. The new frozen mirror is `/private/tmp/drf-oddsense-research-joint-freeze-eb8c2y98`; its `oddsense-source-manifest.json` records the complete source identity. The command used the original provisioned Python with `-I -S -B` and the unchanged `main_offline_pytest.py`, selecting test_news_signals.py, test_market_intelligence.py, test_news_research.py, test_oddsense_workflow.py, test_news_context_pipeline.py and test_news_context_reports.py.

Result: **214 passed in 10.89 seconds**, exit 0. Evidence is `/private/tmp/oddsense-research-joint-freeze-20261018a/{junit.xml,completed.json}` with process receipts in the same directory. This includes migration using the maximum of each capture's legacy network count and durable reservation count, preservation of the existing shared counter high-water mark, cross-process/interrupted capture cases, all 11 owned research scenarios, and the four end-to-end scenarios. The later passing report tests supersede the earlier backend stabilization failures only for these frozen tested bytes. This remains controlled offline evidence, not live-provider or deployed-runtime proof.

After completion, all ten implementation/test paths below were rehashed and exactly match the mirror. Owned production/test files remain frozen and ready for the coordinator's final broad gate and independent rereview; no research-side implementation item remains open. This append is the only post-gate evidence-document change.

| Final joint input | SHA-256 |
| --- | --- |
| `deerflow_bridge/research_gateway.py` | `f99839713cd2d50bed1580acaa843cc049ed7fe187219372b253e4b9e13b2003` |
| `deerflow_bridge/linear_research.py` | `aba8869dbf8386d3afd118f43ab685c4f204b7a590a2036aeb0e2aa4bc2c901b` |
| `deerflow_bridge/deerflow_research.py` | `f7ff138fdbaa0cf84625bd92212a13ee8fa914c374c42fe57d7318d0b6214d87` |
| `deerflow_bridge/config.yaml` | `ffdb3bebaec91745aa549a93cc2f994dd7db9ae5bc3963f8fd8eccf66e37a23d` |
| `backend/tests/test_news_research.py` | `827b4b2edf8363234b852312a046818e96176d92ec5dd79c8c4f88b0b620e3d5` |
| `deerflow_bridge/news_signals.py` | `ffc7a2d720bf3943116d4a3ff0636ce77b1134b743b82c361a9af4e8f88e0d45` |
| `deerflow_bridge/news_tools.py` | `a0ee232160113bd88c7418637cb7bd50db40951edcad5c2e4e38e78af6af592c` |
| `deerflow_bridge/market_intelligence.py` | `e5f5525f0c34d651417808c5fd16453df00e0061cb3e02cf6ca4f31c2c796cae` |
| `backend/tests/test_news_signals.py` | `75eec3560cc7e8ae6be93bd64ff53e1453253a276113cd496891b048a68c9fc6` |
| `backend/tests/test_market_intelligence.py` | `4c97eb3e76958b54ec517baf85d6b7884cc9848a2153490dfc68ff502a709298` |

Guard summary: {"blocked_events": {}, "exit_code": 0, "identity_preserved": true, "process_receipts": 23, "source_drift": []}.

## Changed-question final-gate correction

The coordinator's final broad gate found three historical web-only fixture assumptions and one real changed-question defect. test_research_engine_v3.py is now explicitly authorized for bounded fixture isolation: its autouse fixture sets NEWS_CONTEXT_ENABLED=false, retaining the original exact schema-object and section-order assertions. Context-ON acceptance remains in test_news_research.py and the independent end-to-end suite.

A new context-ON regression completes one question, reuses the same output directory for a different question, and requires byte-preserving capture/state archival, a fresh bound generation, new acquisition, and rejection of the retired old client. The red attempt is recorded at `/private/tmp/oddsense-research-inputchange-red-20261018a`. The provider public archive/cache-retirement contract was proposed to the coordinator before implementation; cache internals will not be accessed or current-generation guards bypassed.

The coordinator approved amendment 5 with the proposed archive_context signature. The engine now invokes that public owner only on a genuinely different identity with valid old state/binding, verifies the old sealed generation/digest first, stages the unchanged capture beside its old state, and then renames that directory to v3.stale-*. Missing/corrupt/foreign proof cannot use retirement. `/private/tmp/oddsense-research-baseline-isolation-20261018a/junit.xml` separately records the four unchanged historical web-only scenarios passing with the explicit OFF fixture; it is not ON-fix acceptance.

## Final changed-question handoff on current provider lock ordering

The context-ON red was fixed through the formally approved archive_context owner. The selected ON/archive gate `/private/tmp/oddsense-research-inputchange-green-20261018a/junit.xml` passed 12 cases (103 unrelated cases deselected). The complete baseline module independently passed 51 cases at `/private/tmp/oddsense-research-baseline-module-20261018a/junit.xml`.

The final correction gate is `/private/tmp/oddsense-research-last-freeze-20261018a/junit.xml`: **76 passed in 7.20 seconds**, covering the 12 context-ON research-consumer cases, 51 explicitly OFF historical baseline cases, provider archival checks and the new parameterized cache-lock regression. Its new exact-source mirror is `/private/tmp/drf-oddsense-research-last-freeze-1_mqkgfo`. This rerun includes the coordinator's later root-to-cache lock-order correction and the provider's subsequently added lock regression. The earlier 74-pass inputchange/cacheorder receipts remain historical for their respective dependency test bytes.

The ON changed-question case proves the old sealed capture bytes and old state are preserved together under v3.stale-*, the next question in the same output directory acquires a genuinely new generation, the new state binds the new digest, and the old client reference is rejected. Same-identity reuse, missing/tampered proof and all existing controlled source/citation behavior remain checked by the consumer suite. The four originally failing baseline assertions remain exact and pass with explicit NEWS_CONTEXT_ENABLED=false; the ON test is separate.

All production/test bytes below were rehashed after the current gate and exactly match its mirror. The authorized research write set is now the previous six files plus backend/tests/test_research_engine_v3.py (only its baseline isolation fixture changed). The last two table entries are provider-owned dependency inputs, not edits by this worker. No further production/test changes are pending; these bytes are frozen for the parent's final broad gate and independent rereview. Only this factual evidence append follows testing.

| Current frozen input | SHA-256 |
| --- | --- |
| `deerflow_bridge/research_gateway.py` | `f99839713cd2d50bed1580acaa843cc049ed7fe187219372b253e4b9e13b2003` |
| `deerflow_bridge/linear_research.py` | `d34299e79d751848052c25ab999782cb94068a98d82d0daead97444052b68cd1` |
| `deerflow_bridge/deerflow_research.py` | `f7ff138fdbaa0cf84625bd92212a13ee8fa914c374c42fe57d7318d0b6214d87` |
| `deerflow_bridge/config.yaml` | `ffdb3bebaec91745aa549a93cc2f994dd7db9ae5bc3963f8fd8eccf66e37a23d` |
| `backend/tests/test_news_research.py` | `7fbaa25a3ac3f3a7ebb1ad05dd0a0a342a228c84bba77e9fd639515e40533b2d` |
| `backend/tests/test_research_engine_v3.py` | `3a47699a7677f4a5f33c987ee3112aa79d6765df5a87af8369d23f3da81c3d87` |
| `deerflow_bridge/news_signals.py` | `dc0dca47e0dc1c2d07878eb1a851c0c37a9b0c968a80b009e6fcbc97002f287b` |
| `backend/tests/test_news_signals.py` | `fc1dd9a5e69cfed2cc5408a9933a61eb32d54e3286e1ab83f1e2cfe71c25185e` |

Completion receipt: {"events": {"redirect:app.config": 1, "redirect:app.services.simulation_manager": 1, "redirect:app.utils.logger": 1}, "exit_code": 0, "identity_preserved": true, "shutdown_complete": true, "source_drift": [], "status": "completed"}.

## Coordinator final integration disposition

The final accepted source and receipt matrix is authoritative in final-verification.md/json. Historical worker freezes and remaining-work statements above apply to their dates only. All approved OS-1/OS-2/OS-3 implementation and concrete independent review findings are now closed; subsequent coordinator report/language/UI deltas have their own recorded affected tests/review. The complete matrix has1397pass/2existing skips, the final affected92 and bilingual61 pass, and the final UI187/build/visual gate passes. Remaining external limits are explicit provider access, deployment/live-model evaluation and Git authentication—not missing approved code. No historical receipt hash was reassigned.
