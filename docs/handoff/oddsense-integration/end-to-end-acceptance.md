# Oddsense end-to-end acceptance

**Status:** Complete for the assigned controlled end-to-end acceptance scope; final joint mirror passed 4/4. **Owner:** independent acceptance worker. **Scope:** only `backend/tests/test_oddsense_workflow.py` and this document.

**Final accepted evidence:** `/private/tmp/drf-os-final-e2e-20261018-1` from the coordinator's exact joint mirror `/private/tmp/drf-oddsense-final-joint-vksogbeu`; **4 passed in 2.89 seconds**. The owned test SHA-256 is `d298dad0628c4e4f74eaf8eefb6091e9d991bb2792b9dadce5b2be3abf98be8f`. The final section below supersedes the earlier pending-freeze entries while preserving their history. These are controlled scripted responses with real QA/publication/API/export checks, not live provider/model evidence.

## Request and acceptance boundary

Implement the approved OS-1/OS-2/OS-3 consumer scenario in the shared Oddsense worktree. Use the existing official-data end-to-end test as a pattern, the production research engine and tools, native-shaped scripted provider/model/fetch boundaries, parent research promotion, real report publication checks, and Flask dossier/report/Markdown consumers. No live network, model, credentials, services, installation, saved runs, Git mutations, root handoff changes, or edits to other owners' files are permitted.

The controlled pipeline must actually invoke the new tools, retain NewsAPI and Kalshi native identities and citations through stored research and final report, preserve context-only exclusion from anchors/resolution, and demonstrate immutable generation/tamper/off controls. Optional Reddit evidence is a separate controlled scenario, with denial and unknown values distinguished from emptiness. Scripted acceptance cannot establish live-provider compatibility or forecast quality.

## Requirements and checks

| Requirement | Scenario and expected evidence |
|---|---|
| Real producer through consumer | Execute `_Engine` with `ResearchTools`/`SourceLedger`, inject only external response boundaries, capture actual tool and transport traces, then consume the resulting files. |
| Stored and cited native identities | Inspect sealed snapshot, sources and pages, research dossier, promoted files, report-local snapshot, final citations, Flask JSON and Markdown download. |
| Real admission/publication | Keep research QA and final publication/audit checks active. Require `ReportManager.publication_status` to return publishable and API download bytes to match audited Markdown. |
| Context-only semantics | Assert all new provider rows remain in the context carrier and out of automatic market/official-data anchors and resolution inputs. |
| Immutable/replay/tamper/off controls | Consume sealed bytes without acquisition; reject changed evidence; disabled mode performs no new acquisition or artifact write. |
| Guarded execution | Freeze with `scripts/oddsense_source_mirror.py --label e2e-...`; run provisioned Python with `-I -S -B` and the existing guarded runner against a fresh canonical `/private/tmp` evidence root. Record hashes and guard counters. |

## Plan and progress

1. Read the approved contract and plan and the complete official-data acceptance pattern. Done.
2. Inspect the current public engine/provider/backend seams and identify API gaps before implementing. Done; discovered gaps and owner corrections are recorded below.
3. Implement a few focused scenarios in the owned test file, without alternate orchestration or publication bypasses. Done: three test functions produce four focused scenarios.
4. Run the exact-source mirror under the existing offline guards; resolve owned test issues and report application gaps to their owners.
5. Record executed call trace, artifact identities/citations, publication/API/export evidence, limitations and exact run receipts here.

## Findings and decisions

- The shared integration contract records implementation approval; no renewed approval is required.
- At initial inspection `news_signals.py` and `news_tools.py` are absent. Research and backend seams are partially present. Build against the frozen API and execute after provider implementation lands.
- The task-specific root handoff contains historical pre-approval prose plus an appended approved shift. The frozen integration contract and latest user instruction govern this assignment.
- Existing unrelated work remains outside this worker's write set. There is no child agent to resume or stop.

## Verification ledger

Initial checkpoint: no runtime acceptance had run at document creation. Source reads alone were not behavioral evidence; the dated run ledger below records subsequent execution.

## Remaining work and next-session prompt

Complete the owned test, run guarded scenarios on a frozen source mirror, and record a verdict with precise limitations. Resume by reading this file and the shared integration contract; do not edit application files or weaken guards to make acceptance pass.

## Updates

- 2026-10-18: Created the scoped continuity record after reading the approved contract and complete official-data pattern. Recorded absent provider implementation as the immediate execution dependency.

### First controlled run: meaningful red evidence

The first mirror is `/private/tmp/drf-oddsense-e2e-first-b2gawhfr`. The unchanged runner executed the four owned scenarios under `/private/tmp/oddsense-e2e-first-20261018-1318`: **2 passed, 2 failed**. `junit.xml`, `completed.json`, per-process guard receipts and `oddsense-workflow.json` retain the original failures and actual call trace.

The full real engine completed its phases and wrote a dossier, but its real QA failed only `sections_in_order`: the produced context heading was absent from the expected heading list. The remaining eight checks passed (citation density 100%, canonical scenario frame, section lengths, no dropped/stale/error/truncated content). This is an application finding assigned to the research owner, not bypassed in acceptance. The second failure was an acceptance expectation error: unknown Reddit publication time correctly produces `partial`; the owned expectation was corrected from `ok` to `partial`.

The actual first-run provider boundary calls were two NewsAPI `/v2/everything` calls, one existing Polymarket public-search response, one Kalshi catalog response and one Kalshi detail response. The first trace also exposed `language=english` on the native NewsAPI request; the provider owner was notified and the test now requires `language=en`. Every response is scripted. No provider compatibility claim follows from these traces.

The test calls `_append_news_market_context` as well as the real citation/lint/stabilization/audit publication entrypoints. No `_require_publishable` or publication-status function is replaced.

### Second controlled run: strengthened native language assertion

Mirror `/private/tmp/drf-oddsense-e2e-second-vjldu7nx`, evidence `/private/tmp/oddsense-e2e-second-20261018-1320`: **3 passed, 1 failed**. Research QA now passed after its owner's section-order correction. This frozen mirror preceded the provider language correction, so the stricter transport assertion rejected `language=english`; the actual tool reported `unavailable`, no publisher body was fetched, and the integration correctly failed the required fetch trace. The original receipt remains intact. Both Reddit controls and the off control passed.

A third run uses a fresh mirror after provider canonicalization landed. The immutable-generation control now reconstructs a new real `_Engine`, `ContextClient` and `SourceLedger` over the stored generation, rather than merely invoking the same in-memory engine again. It also checks changed-cutoff rejection without acquisition. Report-local storage is compared by validated envelope equality and its own immutable bytes; identical JSON formatting between independently owned writers is not required by the carrier contract.

### Third and fourth runs: capture provenance and real publication failure

Third mirror `/private/tmp/drf-oddsense-e2e-third-eko9kq71`, evidence `/private/tmp/oddsense-e2e-third-20261018-1323`: **3 passed, 1 failed**. Native language, publisher fetches and real engine QA passed. A repeated article can have more than one retained query capture; comparing the first-cited ledger timestamp only with the last aggregate item was an overconstraint in the owned test. The corrected assertion now requires the cited native ID, URL, publication and retrieval times to match an exact retained query capture, and records its capture ID and evidence digest.

Fourth mirror `/private/tmp/drf-oddsense-e2e-fourth-6qjduq8w`, evidence `/private/tmp/oddsense-e2e-fourth-20261018-1326`: **3 passed, 1 failed**. Real engine QA, source/page hashes, parent promotion and simulation consumed-generation binding passed. Actual report stabilization then removed metadata timestamps and part of the Kalshi source cell as unsupported numeric content. The authoritative final audit rejected publication with `news context artifact or audited Markdown differs from consumed generation`: carrier validity was true, but canonical context Markdown presence was false. This is a backend integration defect reported with its actual audit, unchanged guards, and a warning that pre-QA lane-local source numbers cannot be trusted as the final report namespace.

Acceptance now also checks every final deterministic context row's URL/publication/retrieval values against its stored item, checks any row's inline citation points to that same URL, and exercises report-local tamper rejection through the real publication status and Markdown-download route. These checks preserve the requested source/publication boundary.

### Fifth run and current critical path

Fifth mirror `/private/tmp/drf-oddsense-e2e-fifth-4goth9co`, evidence `/private/tmp/oddsense-e2e-fifth-20261018-1330`: **3 passed, 1 failed**, at the same authoritative context-Markdown publication check. This run includes the stronger final metadata/citation/API/report-tamper assertions, but those downstream assertions have not yet been reached. They must not be reported as passing until the backend fix lands and a fresh exact mirror reaches them.

The current critical path is the backend owner's canonical metadata stabilization fix, followed by a fresh full owned-suite run. No broad tests, additional agents, provider probes or application edits are needed from this worker. The NewsAPI fixture now dates its articles relative to the real run date so the required current-day market capture does not make this test expire after the provider's lookback window.

### Review-driven quote-presentation acceptance

The parent relayed an independent review finding that native quotes/rules/units must survive actual v3 presentation, beyond source existence and timestamps. The owned test now requires the real `market_compare` tool output, actual section-writer input messages, research Markdown, final published Markdown, and both exported Markdown files to contain the supplied Kalshi last/bid/ask values, quote/probability basis, USD-per-contract unit, literal Yes outcome, native primary rule and explicitly unknown/null quote time. The scripted writer copies only quote lines it actually receives; it does not inject missing quote metadata from fixtures. Executive-summary input remains the engine's normal bounded section leads; no new summary-orchestration path was introduced.

The provider owner separately owns multiprocess pre-I/O reservation/crash-cap controls. This end-to-end assignment verifies final consumers and does not claim that another worker's concurrency checks passed.

### Quote-focused run

Mirror `/private/tmp/drf-oddsense-e2e-quote-guxkxg9t`, evidence `/private/tmp/oddsense-e2e-quote-20261018-1341`: **3 passed, 1 failed**. The stronger actual `market_compare` outputs, actual writer-input messages, real engine QA/dossier, ledger/source metadata and evidence hashes, and promotion/binding checks passed. Publication was rejected at quantitative stabilization, before final admission. All guards remained unchanged.

The scripted model had additionally dumped raw metadata lines into authored prose; this created artificial uncited narrative claims and was removed from the owned fixture. The real supplied writer-input metadata remains recorded and asserted. Complete quote metadata must still survive the engine's real deterministic context section, report consumer and both exports. This change isolates the actual consumer contract instead of requiring the production writer to copy a raw field dictionary into prose. The report agent now receives the exact bound simulation ID as well as the validated carrier.

### Ready-source run: normal report assembly correction

Mirror `/private/tmp/drf-oddsense-e2e-ready-rd8kxks_`, evidence `/private/tmp/oddsense-e2e-ready-20261018-1353`: **3 passed, 1 failed**. All stronger producer/quote/source/promotion checks passed. The new unique-section restoration guard rejected two identical context H3 headings: the fixture had reused the complete dossier as report narrative and then appended the report's own metadata block. Normal report generation consumes the dossier as background and assembles its own authored sections, so that fixture duplicated the metadata owner.

The owned test now passes the already produced, QA-cited narrative sections through real `ReportManager.save_outline`, `save_section` and `assemble_full_report`, and then invokes the real context appender exactly once. The dossier remains intact for dossier/API/export comparisons. No existing context is silently deleted by the application, no ambiguity guard is disabled, and no alternative orchestration is implemented. This fixture correction was reported to the coordinator before editing.

### Assembled-report run: exact final audit preserved

Mirror `/private/tmp/drf-oddsense-e2e-assembled-q50iezly`, evidence `/private/tmp/oddsense-e2e-assembled-20261018-1356`: **3 passed, 1 failed**. This run was dispatched immediately before the coordinator's later instruction to wait for digest-bound ownership markers. Real report assembly passed. Stabilization converged in one pass, and the final context audit recorded `present=true`, `valid=true`, `markdown_present=true`. The sole remaining hard issue was one suspected truncated table cell in the final Markdown. The exact long native contract metadata cell and the full audit remain in the receipt directory; the coordinator was notified. No table audit, grounding, quote, citation or publication switch was disabled.

Next execution waits for the coordinator's digest-marker readiness signal. Production ownership is being strengthened so authored same-heading content can coexist with a uniquely owned, digest-bound metadata block. Missing or duplicate owned markers must still fail; only the owned block may be restored.

### Digest-marker run: complete controlled pipeline passed

Mirror `/private/tmp/drf-oddsense-e2e-markers-knnnk70l`, evidence `/private/tmp/oddsense-e2e-markers-20261018-1401`: **4 passed in 3.15 seconds**, runner exit 0. The complete producer-to-final-consumer scenario reached publication, Flask endpoints, real Markdown exports, reconstructed-engine replay and tamper rejection. Research QA, final hard audit, professional publication gate and citation artifacts all passed. The source hashes before/after and the checked current worktree bytes matched.

The audit receipt contains only three expected root redirects (`app.config`, logger and simulation manager), with no blocked operations, native probes, source drift or child processes, and preserved process identity. This is a CPython audit-hook boundary, not an OS sandbox or live-provider proof.

This mirror already contains the new durable `ContextClient.capture_market` callback API. The production market transport reserved one Polymarket request and two Kalshi requests before its three scripted HTTPS dispatches; Metaculus remained unsupported with zero network requests and `attempted=false`. A narrow final assertion now compares those stored admission counts with the actual native transport trace. Provider concurrency and crash-cap acceptance remains with its owner. A final rerun against the owner's finalized callback bytes remains pending the coordinator's readiness notice.

## Passing-run evidence detail (historical marker freeze)

The completed marker receipt is `/private/tmp/oddsense-e2e-markers-20261018-1401/oddsense-workflow.json`. Its SHA-256 is `916f9239e45abb166bf176afb304f33a55d3a8d97743693fcc5152aaa7fab81c`. The full mirror inventory is `/private/tmp/drf-oddsense-e2e-markers-knnnk70l/oddsense-source-manifest.json`; the focused receipt also records all 18 relevant source/test hashes before and after execution.

The actually executed context-tool trace was:

| Order | Production caller | Tool | Query |
|---|---|---|---|
| 1 | context-prefetch | news_search | semiconductor capacity grow end 2027 |
| 2 | K1 | news_search | capacity |
| 3 | K1 | market_compare | capacity |
| 4 | K2 | news_search | capacity |
| 5 | K2 | market_compare | capacity |

The trace contains two native-shaped NewsAPI `GET /v2/everything` responses with `language=en`, a scripted Polymarket public-search response, and scripted Kalshi catalog/detail responses. The repeated K2 requests replayed stored data. Existing web-fetch ownership stored exactly the two publisher pages and the Kalshi contract page, with content hashes checked against the ledger/source projection. Fourteen scripted model responses went through the real ModelGateway: scope, plan, seven agent/prime calls, one additional warm-up, two section-writing calls, summary and fact extraction. Both real section-writing inputs carried the actual supplied quote metadata. No external report model or graph intelligence call occurred.

The immutable capture generation was `ffe7f84a5eb544c49b056532669a6e9f`, language `en`, cutoff `2026-10-18`, question digest `a7dbfd92b8bf3ac842174f600827f873e55fa6439169168e7c856dcb58a1eda1`. Its envelope digest was `506b69f314cba21a34c2ef7f9ef75e56433711d6088b8ac212ddf2131654d0f4`; the promoted serialized-file hash was `6f2f49438007e074d77d9a6754da6d2fa7b8faedd463b20e0b6a2d04799f7290`. These are distinct identities: the envelope digest excludes its own digest field; the file hash binds the exact serialized bytes.

| Final research citation | Native source identity | Retained capture evidence digest |
|---|---|---|
| S1 | kalshi:CAPACITY-27-GROW | e891e6d13797bde44c2e9fd7460dfe85e7426aff75e5ae2ea65f127124081d5f |
| S2 | newsapi:ac3f2335c0f8bb669aa405b76dbe9d3724a4d7542cdec98a8b22055e42f6cd8a | 93798a2cbd44e97c3cd4db9b1038b20782240b3e072607126c2a47801e303e3a |
| S3 | newsapi:92c9afec5e338286fa50a3165dafb9632a95b09bd44e3e90672e92c242cddea5 | 5cb76f9de815a4207d61cfd2ae13197b0ea0fad435a33e591a4d1b769b556790 |

Kalshi retained `yes_bid=0.4`, `yes_ask=0.44`, `last_price=0.41`, `probability=0.41`, `price_unit=USD_per_contract`, the documented quote/probability bases, literal `outcome=Yes`, exact primary/secondary synthetic rules and `quote_at=null`. Both news articles retained publisher, publication time and their first-cited retrieval capture; repeated-query captures remain separately available. All new items remained context-only, anchor-ineligible and resolution-ineligible. The scenario produced no official quantitative facts or canonical market registry rows, and the report's market/data packs and final forecast anchors remained empty.

| Final consumer | Observed result |
|---|---|
| Real publication status and final audit | publishable=true, hard_passed=true; no hard issues; professional publication gate passed; context carrier valid and present in final Markdown. |
| `/api/research/pipe_oddsense/dossier` | HTTP 200; exact promoted report/sources and immutable carrier returned; sealed=true. |
| `/api/report/report_oddsense` | HTTP 200; publishable=true; exact carrier and final Markdown returned. |
| `/api/report/report_oddsense/download` | HTTP 200; exact audited Markdown bytes. |
| Actual demo report export | Exact same Markdown bytes; hash `7819fb050a7184dca5b015b92dda66dd19357ca2ca8294b19f4562331f8a20d1`. |
| Actual demo dossier export | Exact produced dossier bytes; hash `27a4e11c3b04a3b88ff377057abea8da84bdccb5b553a54f3659d9f4209f9720`. |
| Reconstructed engine and client | Same sealed bytes and passing stored QA; zero new model/provider/fetch calls. |
| Changed cutoff | ContextClient rejected the changed identity without acquisition. |
| Promoted-capture tamper | Carrier/binding/parent contract failed closed; dossier API HTTP 409. |
| Report-local capture tamper | Publication failed closed; Markdown download HTTP 409; restored original bytes regained publication eligibility. |
| Optional Reddit 403 | forbidden, attempted=true, no items; no raw provider body or verified-empty claim. |
| Optional Reddit unknown time | partial, unknown publication-date count 1; null publication time and no synthetic probability. |
| Disabled context | No provider/model call and no context artifact write. |

The final report, API download and report export all hashed to `7819fb050a7184dca5b015b92dda66dd19357ca2ca8294b19f4562331f8a20d1`. The structured forecast hash was `43ed5ed6ee64c9d08337ce7065d19c49ad5d99707026335524fb7dc34a6e964b`. The exact native quote values, rules, units, explicit unknown trade time, source URLs and stored publication/retrieval times survived the final APIs and Markdown exports.

## Scope limits and final-freeze dependency

This worker changed only the assigned test and this acceptance document, preserved all earlier red receipts, and made no application or Git edits. The scenario uses scripted provider/model/search/fetch responses and synthetic forecast inputs. It keeps real research QA, citation sealing, report assembly, forecast normalization/quality checks, publication stabilization/audit/status, Flask routing and demo export. It does not run OASIS, actors, paid models, services, saved runs, live providers, frontend UI or provider compatibility probes. Legacy registry acquisition and unrelated chart rendering are disabled explicitly; this is a focused contextual-source acceptance scenario rather than exhaustive legacy-path acceptance. The coordinator owns broader release acceptance and independent reviews.

The sole pending source freeze is the provider owner's migration reconciliation for the earlier `network_requests` counter. The current passing receipt remains valid for its exact historical source hashes. After the coordinator reports final callback/migration bytes ready, rerun the same owned four-case suite from a new exact mirror with the new stored-admission-to-transport equality assertion, then record the final source state and verdict here. No further implementation expansion is required from this worker.


## Final joint source acceptance

**Recorded UTC:** 2026-10-18T13:22:20.554762+00:00. **Verdict:** Complete for this worker's assigned acceptance scope. There is no remaining owned implementation or verification task.

The final run used the coordinator's exact `/private/tmp/drf-oddsense-final-joint-vksogbeu` mirror, after comparing the owned test hash and all 18 focused source files against the shared worktree. No file differed. The provisioned interpreter and unchanged guard executed:

```sh
cd /private/tmp/drf-oddsense-final-joint-vksogbeu
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-os-final-e2e-20261018-1 -q backend/tests/test_oddsense_workflow.py
```

**Result:** 4 passed in 2.89 seconds; JUnit and runner exit 0. Evidence is `/private/tmp/drf-os-final-e2e-20261018-1/{junit.xml,completed.json,oddsense-workflow.json,oddsense-reddit-403.json,oddsense-reddit-200.json}`. The exact whole-mirror inventory remains `/private/tmp/drf-oddsense-final-joint-vksogbeu/oddsense-source-manifest.json`.

The final detailed receipt hash is `80c86de1cad08699b6f9a140f43242c53f380f690ea02e53bfe16e4ae82f72c6`. All 18 source hashes stayed unchanged during the run and still matched the worktree when this completion record was written. The guard retained process identity and recorded only its three expected root redirects; it recorded no blocked operations, contained native probes, child processes or source drift. This remains an audit-hook guarantee, not an OS sandbox claim.

### Final executed call trace

| Order | Actual production caller | Tool | Query |
|---|---|---|---|
| 1 | context-prefetch | news_search | semiconductor capacity grow end 2027 |
| 2 | K1 | news_search | capacity |
| 3 | K1 | market_compare | capacity |
| 4 | K2 | news_search | capacity |
| 5 | K2 | market_compare | capacity |

The real production callback persisted network admissions `{"kalshi": 2, "metaculus": 0, "polymarket": 1}`; their sum equals the three actually dispatched native market HTTP responses. Those dispatches were:

- `GET https://gamma-api.polymarket.com/public-search?q=capacity&limit_per_type=8&events_status=active`.
- `GET https://external-api.kalshi.com/trade-api/v2/markets?status=open&limit=100&mve_filter=exclude`.
- `GET https://external-api.kalshi.com/trade-api/v2/markets/CAPACITY-27-GROW`.

Two NewsAPI `/v2/everything` responses used the run's topic query and `capacity`, `language=en`, one page of at most 20 articles, and header authentication with a synthetic sentinel. The same three publisher/contract page fetches and fourteen scripted model calls described in the historical passing trace executed again. K2 replay, direct client replay and full engine reconstruction added no provider/model/fetch calls. The market adapter's real callback path remained in place; only HTTPS responses were scripted.

### Final artifact identity and citation proof

Capture generation `6a73766045a24fbe9c0bc3588d35f988` has envelope digest `1f83a3fb295052e4396dfdf906ba3b1741e4fbf13dfad2d31a37039c8df28e50`, language `en` and cutoff `2026-10-18`. The exact promoted capture-file hash is `a68d0f61e6501ab5d9c7a8f17efdb4df0ea02f070dbc9155c32026aad83666ea`. Parent promotion, consumed simulation binding, report-local storage, both Flask JSON consumers and the final audit all consumed this same validated envelope.

| Final citation | Provider/native identity | Publication time | Cited retrieval time | Evidence digest |
|---|---|---|---|---|
| S1 | kalshi:CAPACITY-27-GROW | 2026-10-16T00:00:00Z | 2026-10-18T13:20:48.361777Z | 31a7966f0872986ae5cc07055a70447ac5ebc5d98bc39f47b4a800510a84c5b3 |
| S2 | newsapi:ac3f2335c0f8bb669aa405b76dbe9d3724a4d7542cdec98a8b22055e42f6cd8a | 2026-10-17T09:00:00Z | 2026-10-18T13:20:48.310137Z | 32672204159b97de770a112348db1127d47e290efdfb1f8868b759ab5c9c9022 |
| S3 | newsapi:92c9afec5e338286fa50a3165dafb9632a95b09bd44e3e90672e92c242cddea5 | 2026-10-17T09:00:00Z | 2026-10-18T13:20:48.310137Z | 70521aed62f9735e93e7af0afd3a4cf2e7fc61a84f0a3acdb51edcaa7454b35e |

The exact native Yes outcome, last/bid/ask values, units, quote/probability bases, both settlement rules and null quote time passed at the tool response, actual section-writer input, SourceLedger reload, final sources projection, research dossier, final published report, both JSON carriers and both Markdown exports. Every final context row retained its own URL and publication/retrieval values; any inline source marker resolved to that same URL. The canonical metadata block remained digest-bound through real publication stabilization and the final read-only audit.

### Final consumer and negative controls

| Consumer/check | Result |
|---|---|
| Research QA | passed=true; full production engine completed all seven phases. |
| Report assembly | Real save_outline/save_section/assemble_full_report consumed produced QA-cited narrative sections. |
| Publication | hard_passed=true, publishable=true, professional publish gate passed; no hard issues or dangling citations. |
| Dossier API | HTTP 200; exact report/sources and capture, sealed=true. |
| Report API | HTTP 200; publishable=true, exact capture and audited Markdown. |
| Markdown download | HTTP 200; exact audited bytes. |
| Demo exports | Actual exporter retained exact report/dossier bytes and all supplied context metadata. |
| Reconstructed engine/client | Stored generation/QA replayed with no new acquisition or model/fetch call. |
| Changed cutoff | Rejected before acquisition. |
| Promoted capture tamper | Carrier/binding/parent proof rejected; dossier API HTTP 409. |
| Report-local tamper | Real publication status rejected; download HTTP 409; restoring original bytes restored eligibility. |
| Reddit denial/unknown time | forbidden with no items versus partial with null time and no probability; separate receipts. |
| Off | No context acquisition or context artifact; no model call. |

Final report, download and exported report Markdown share SHA-256 `0ec8039d3fa2bd581c3ce5ebc3e6cc3b55c00aedf60bc59eaa513bb3941b9b09`. Exported dossier SHA-256 is `a42f476b29d148c546e06d37bd3de3ff713868a089c47dc117448a836a539de4`. The structured forecast SHA-256 is `c03bf776c7ff684f4935043ef9fe0c64cdd39a94bb7f9567efb4d6c8c0779b58`. All final files live below `/private/tmp/drf-os-final-e2e-20261018-1/pytest-tmp/test_scripted_engine_to_publis0/` in `research/`, `pipelines/pipe_oddsense/handoff/`, `reports/report_oddsense/` and `demo/`.

### Final 18 focused source hashes

| File | SHA-256 |
|---|---|
| deerflow_bridge/news_signals.py | ffc7a2d720bf3943116d4a3ff0636ce77b1134b743b82c361a9af4e8f88e0d45 |
| deerflow_bridge/news_tools.py | a0ee232160113bd88c7418637cb7bd50db40951edcad5c2e4e38e78af6af592c |
| deerflow_bridge/market_intelligence.py | e5f5525f0c34d651417808c5fd16453df00e0061cb3e02cf6ca4f31c2c796cae |
| deerflow_bridge/research_gateway.py | f99839713cd2d50bed1580acaa843cc049ed7fe187219372b253e4b9e13b2003 |
| deerflow_bridge/linear_research.py | aba8869dbf8386d3afd118f43ab685c4f204b7a590a2036aeb0e2aa4bc2c901b |
| deerflow_bridge/deerflow_research.py | f7ff138fdbaa0cf84625bd92212a13ee8fa914c374c42fe57d7318d0b6214d87 |
| deerflow_bridge/research_budget.py | bf698af519aefd686994fddc7224e47775157597de3a77b691e267cd8c7ba636 |
| backend/app/services/pipeline_orchestrator.py | a15e36fda51101added494a829d1f1f578b3d3fab53ed259aa5cc540fa8fc894 |
| backend/app/services/news_market_context.py | b52a36170ef81c7760cb14ea46fd762d27144052c91dbc6649e0a5153ab2e136 |
| backend/app/services/official_data.py | 43498ff019b2dac0f5b3cb0ee6a680579dcfe4805116f4214f29e45a764e6963 |
| backend/app/services/report_agent.py | 77475afcac5fd1fac7e65bf22469970b477ee117afa73a4117942be1fbc6750e |
| backend/app/services/forecast_extractor.py | 07080e1866ddff300412ef94842938f6a9ec071a8a890602434f7312d25ae3af |
| backend/app/services/report_lint.py | 4d6e5ae17354b6ba21a7f5f8a0767d42794289877d3413c38838b59311bddd83 |
| backend/app/api/research.py | 6d0c1ab9fab189540ab2da9bee602510a6b33aa662f9addcc652e993dead2a37 |
| backend/app/api/report.py | e5e394f7c9cbbb46a413228e6829a7a6f5cb11d40cc9d566eba80fd728334cea |
| backend/scripts/export_demo_site_data.py | 1d8d334cbf72a96940399f041472a7a094b3f2be426442e783a905a5cd47602b |
| backend/scripts/main_offline_pytest.py | 53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa |
| backend/tests/test_oddsense_workflow.py | d298dad0628c4e4f74eaf8eefb6091e9d991bb2792b9dadce5b2be3abf98be8f |

### Closing ownership and handoff

Only `backend/tests/test_oddsense_workflow.py` and this document were edited by this worker. No application module, peer test, root handoff or Git state was edited. Earlier red and green receipts were retained. No new agent was spawned and no child write set was taken over. Provider migration/concurrency controls, coordinator report-ownership regressions, deployment checks, live probes and broader release acceptance remain their owners' responsibilities; this document does not reclassify them as this worker's proof.

The assigned controlled acceptance is complete. If the coordinator changes any of the 18 tested files, repeat this same four-case suite against the next shared frozen mirror using a new canonical evidence root; retain the preceding receipts. No implementation expansion, guard relaxation, provider access or saved-run recovery is needed to reproduce this acceptance.

- 2026-10-18T13:22:20.554762+00:00: Recorded final shared-mirror 4/4 acceptance, actual callback-count equality, all 18 exact hashes, final native citation/capture identity, API/export hashes and completed ownership handoff.

## Coordinator final integration disposition

The final accepted source and receipt matrix is authoritative in final-verification.md/json. Historical worker freezes and remaining-work statements above apply to their dates only. All approved OS-1/OS-2/OS-3 implementation and concrete independent review findings are now closed; subsequent coordinator report/language/UI deltas have their own recorded affected tests/review. The complete matrix has1397pass/2existing skips, the final affected92 and bilingual61 pass, and the final UI187/build/visual gate passes. Remaining external limits are explicit provider access, deployment/live-model evaluation and Git authentication—not missing approved code. No historical receipt hash was reassigned.
