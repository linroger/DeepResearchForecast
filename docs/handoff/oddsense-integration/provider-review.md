# Independent provider and research review

**LATEST CLOSURE — 2026-10-18T14:46:01Z: PR-4 and PR-5 CLOSED on `/private/tmp/drf-oddsense-delivery-reviewed-nv9hnl2h`. No remaining concrete P1/P2 or commit blocker in this bounded acquisition-time recheck.** All five scoped file hashes match the manifest, frozen mirror and current worktree. Directly inspected matching evidence records 1,455 passes, two existing harness skips, zero failures/errors and exit 0, including all seven new finding-specific cases. The earlier request-changes verdict below is superseded for these final bytes and preserved as history.

**LATEST VERDICT — 2026-10-18T14:41:35Z: REQUEST CHANGES for the acquisition-time candidate. Two concrete P2 findings, PR-4 and PR-5, remain open despite the passing delivery matrix.** The idle-gap fix is sound in direction, but the current news completion comparison and legacy counter-only migration need narrow corrections and regression evidence before commit. This verdict supersedes the earlier exact-freeze closure only for the newly reviewed timing change. See the final appended section; earlier evidence remains historical.

**FINAL DISPOSITION — 2026-10-18T13:35:10Z:** **PR-1, PR-2 and PR-3 CLOSED for `/private/tmp/drf-oddsense-final-accepted-ub26ztb5`; no remaining concrete P1/P2 in this focused provider/research review.** The second exact-freeze joint receipt records 1,397 passes, two existing harness skips, zero failures/errors and exit 0. Closure includes source inspection, manifest/frozen/worktree comparison and the passing context-ON changed-question archival case, not an inference from the earlier broader pass. Historical provisional/open dispositions below describe superseded snapshots and are retained verbatim.

**Latest disposition, 2026-10-18T13:23:35Z:** Final-freeze attempt 1 inspected. PR-1 and PR-2 are resolved on the exact freeze below, with source inspection and matching targeted receipt cases. A new **P2 PR-3** remains open for changed-question reuse of an output directory. The parent confirms its repair is in progress. **Final acceptance awaits a fresh freeze and the context-enabled changed-input regression.** The original review below is preserved as history.

Status: **Provisional initial review in progress, 2026-10-18**. Implementation workers remain active. This review owns only this document. No Git, application/vendor execution, tests, credentials, services, or new agents are used. Parent joint gate: `/private/tmp/drf-oddsense-joint-first-qdwaaq4i`; no success is assumed.

The review traces the frozen contract through provider normalization/storage, market comparison, both research engines, citation projection and test scenarios. Findings require concrete triggers, precise source anchors, positive controls, and a distinction between missing coverage and observed defects. Final acceptance requires the parent's final source freeze and a recheck.

## Initial source identity

SHA-256 values captured before detailed reading; these do not assert atomicity across concurrently edited files. End-of-read hashes will be compared and drift explicitly recorded.

| Path | SHA-256 |
|---|---|
| `docs/handoff/oddsense-integration/integration-contract.md` | `3322e02f6e617c72cd02df9e72448c628c86b8b95026d1af27358edf825c02b6` |
| `deerflow_bridge/news_signals.py` | `9643a06fd77b7a8ff6d6d54dcc4a10044c0ca7540db0511595b5309d46af0cf9` |
| `deerflow_bridge/news_tools.py` | `a0ee232160113bd88c7418637cb7bd50db40951edcad5c2e4e38e78af6af592c` |
| `deerflow_bridge/market_intelligence.py` | `6fb7dbb8622460e9be39dbedeb37bd647f8fb2b04e48ffe1b311695d65e2733a` |
| `deerflow_bridge/research_gateway.py` | `8bd8726470f3fa6ada915e7ecb7f03d60d477b7332c9fda5031cf693252093ae` |
| `deerflow_bridge/linear_research.py` | `e54e6d9f32a915114172889150b71e9e73d042b04408003b5e0ebe37a9a6eb41` |
| `deerflow_bridge/deerflow_research.py` | `6e6c2ca74e52c154f35a5bda429f27dde6603761e7380f915beefb4afdb730b2` |
| `backend/tests/test_news_signals.py` | `ff4b51e0ec9d74e4d9daafaf33031b9f3cb0583f58673dc14f8ec26d6409f833` |
| `backend/tests/test_news_research.py` | `838438110389f6abd99aa2841dd241beb6837351f0202ee4b1064ca591dd5583` |
| `backend/tests/test_market_intelligence.py` | `0f53767b7f2f6bacb10595ae86dd6351ca2c8550ba83c2036ba85ed747fa2b64` |
| `deerflow_bridge/market_tools.py` | `eed4d54cf31202a07c4ad88091b6f5cdb57292c0001f4b6e9f12c827ea2bc061` |
| `deerflow_bridge/research_budget.py` | `bf698af519aefd686994fddc7224e47775157597de3a77b691e267cd8c7ba636` |
| `deerflow_bridge/config.yaml` | `ffdb3bebaec91745aa549a93cc2f994dd7db9ae5bc3963f8fd8eccf66e37a23d` |

## Initial findings — actionable, source-observed

### P1 PR-1: Market comparison reserves its generation allowance after physical I/O

**Anchors:** `deerflow_bridge/market_intelligence.py:400-406`, `:409-418`, `:428-453`; `deerflow_bridge/news_signals.py:602-609` in the end-of-read provider revision (initial revision `:590-597`).

`_LOCK` is a module-local threading lock. Each process snapshots the store, independently derives `4 - prior_calls`, performs HTTP, and only then enters `record_result`'s filesystem lock. Two processes sharing one unsealed generation can both observe zero calls and each issue up to four requests. The existing shared research budget bounds overall search traffic; it does not enforce this market-specific four-request allowance. With an identical query, the second writer replays the first recorded result after already issuing its own requests, so even the durable count can underreport physical traffic. Distinct queries can persist a total above four. A process dying after HTTP but before `record_result` similarly loses its consumed allowance. Filling the store's query slots also lets acquisition precede a rejected persistence attempt.

**Impact:** The advertised generation cap and single-capture replay semantics are not reliable under the explicitly requested multiple-process/client/query cases. This is an integration defect in admission ordering, not a request for a new market system.

**Narrow fix:** Have the provider-owned store atomically admit/reserve comparison requests before HTTP, with bounded cross-process exclusion and an interrupted-capture record. Reuse the existing store/locking owner; ensure sealing and the query cap prevent acquisition before it begins. The NewsAPI path already demonstrates durable pre-I/O reservation at end-of-read `news_signals.py:681-684`.

**Required negative scenario:** Under a deliberately generous global research network budget, synchronize two separate processes with separate clients on one root before the first physical request. Exercise identical and distinct queries. Count transport calls independently of the envelope; their sum must be at most four and persisted accounting must retain all reservations. Interrupt an admitted comparison before its result write and reopen it: it must not recover the spent allowance or silently refetch that capture. Repeat with a full query table and assert zero new HTTP.

**Valid positive control:** One process/client may fetch a Polymarket response, Kalshi catalog and detail with three physical requests, then reopen and use at most the remaining one request for another query. Existing `backend/tests/test_market_intelligence.py:312-347` and `:362-374` cover successful storage/replay and sequential restart accounting, respectively. They do not establish cross-process reservation. The NewsAPI process fixture at `backend/tests/test_news_signals.py:624-660` covers a different acquisition owner.

**Plan/coverage:** Bounded concurrency and durable identity/replay are in OS-2 and the frozen contract. Sequential coverage exists; comparison cross-process/crash/query-table admission coverage is missing. The market worker's own document discloses the shared-API limitation, so this remains an open gate rather than a newly inferred redesign requirement.

### P2 PR-2: V3 discards the comparison facts before presenting the tool response

**Anchors:** `deerflow_bridge/research_gateway.py:3954-3964` and `:2519-2537`; `deerflow_bridge/linear_research.py:4831-4843` and `:7657-7665`; end-of-read `deerflow_bridge/news_signals.py:881-903` (initial revision `:869-891`).

`market_compare` produces normalized quote/rule fields, but `context_query` reduces every row to ledger title, URL, provider, kind, publication/retrieval times and `snippet`. Polymarket sets `snippet=None`; Kalshi uses only its subtitle. The model-visible v3 result consequently omits probability, outcome, bid/ask/last, price basis, quote/volume units, quote time, threshold and settlement rules. `register_context` and the final sources projection retain only basic provenance, while the shared Markdown renderer also omits every quote/rule field. `_context_text` therefore does not restore the missing information for subsequent synthesis. Correct values remaining in the JSON artifact do not make them available to the actual investigator tool consumer or the exported research comparison table.

**Impact:** A v3 investigator cannot compare the supplied market quotes or their contractual bases using the tool it just called. Fetching a publisher page is an appropriate control for news, but cannot be assumed to reconstruct a specific captured market quote. The legacy raw JSON wrapper retains these fields on its immediate tool response, so the current presentation behavior also differs between engines.

**Narrow fix:** Extend the bounded context presentation for market rows to include captured outcome/quote values with basis/units, known/unknown quote time, volume units, key rules/horizon/threshold and provider status. Retain the corresponding source evidence metadata (or a bounded structured context-evidence carrier) through ledger serialization and final projection. Preserve context-only eligibility and original URLs; do not turn these fields into canonical market anchors.

**Required negative scenario:** Send the real `ContextClient.market_compare` output through `ResearchTools.context_query` and a v3 KIQ. Use reversed Polymarket `[No, Yes]` prices and a Kalshi fixture with dollar-string last/bid/ask, contract-count volume, different settlement rules and null quote time. Assert the actual tool message and later synthesis/export retain those distinctions and show unknown as unknown. Assert no fabricated quote for missing prices.

**Valid positive control:** `backend/tests/test_market_intelligence.py:128-155` correctly checks literal Yes `.2` against No-first `.8`, provider-qualified IDs, and replay. `:330-340` checks actual-store units/rules retention. A real `news_search` result with a nonempty snippet still yields its existing attributed discovery text and must not become fetched evidence. Existing research tests at `backend/tests/test_news_research.py:42-63` and `:136-219` validate that news-specific path; they do not exercise a market comparison through the real gateway.

**Plan/coverage:** OS-2's concrete comparison behavior and OS-3's attributed evidence/comparison table are specified in `PLANS.md:58-76`. The frozen gateway schema promises times, rules and quote bases. Stored-market metadata checks exist; market-to-investigator-to-synthesis/final-sources presentation coverage is missing. This is missing implementation of an approved outcome, not a new scope request.

## Checked behavior and limits

| Concern | Source observation and valid control | Limit / remaining evidence |
|---|---|---|
| Missing/unknown versus zero | News malformed/missing-key responses are unavailable; a literal empty articles list is verified empty. Kalshi `_number` accepts `0`, rejects missing/nonfinite/out-of-range values, and never substitutes legacy cents. Tests distinguish those cases (`test_news_signals.py:218-255`; `test_market_intelligence.py:111-125`). | Reviewed source and test assertions only; no execution. Polymarket deliberately retains the existing liquidity/settled-price filter and discloses it, so filtered results do not establish global absence. |
| Full question and en/zh identity | `_question_hash` hashes the complete whitespace-normalized question independently of the 500-character query cap. `_language` normalizes English/Chinese labels and zh variants. Cached and reopened identities are checked. | Test scenarios exist at `test_news_signals.py:682-695` and `:786-803`. No independent runtime claim. |
| Safe storage, bytes and time | `_directory` inspects ancestor components and pins the opened directory inode; regular files, no-follow opens, one-link checks, bounded read, atomic replace and digest/schema validation are present. News transport has fixed endpoints, a bounded body and remaining-time socket settings. Lock wait uses the caller deadline. | Provider lock-open handling changed while reading. Fresh final-freeze process/timeout evidence is required; no guarantee is inferred from an earlier worker receipt. Market cross-process admission remains PR-1. |
| Sealing, replay, tamper, invalidation | News requests reserve before I/O; sealed store refuses uncaptured queries. Present digest changes and bound-generation deletion/replacement fail closed. V3 seals before synthesis/QA and compares reused proof/QA digest. Market sealed replay checks snapshot before dispatch. | Provider direct news calls intentionally invoke the existing attempt-budget owner before durable replay; `research_budget.py:260-265` explicitly counts cache-hit attempts. Exhausted-attempt behavior is therefore not filed as an accidental network-cap defect. Tests must distinguish attempt accounting from physical I/O. |
| Literal Yes and units/rules | Polymarket normalization looks up the literal Yes index; OS-2 additionally requires binary Yes/No before publishing probability and strips CLOB token identity. Kalshi stores dollars-per-contract and contracts, with null unknown quote time. | Actual shared-store retention is covered in tests; v3 presentation loses the same fields (PR-2). |
| Wrong-provider anchor dispatch | Comparison injects a fetch callback into `snapshot_for_queries`; it does not use `prediction_market_search_impl` or `_capture_market_candidates`, emits provider-qualified context rows, and never emits a canonical `markets` registry. `test_market_intelligence.py:395-400` places fail spies on both canonical capture entrypoints. | Test assertions that no canonical file exists support this path only. Existing backend Polymarket requote methods are provider-specific and are not newly guarded by this integration. A joint positive control should prove ordinary Polymarket requote still works and injected Kalshi/Metaculus context never reaches Gamma/CLOB/resolution. No new dispatch defect is established by inspected paths. |
| Both engines: registration and use | V3 stable schemas and KIQ dispatch are wired; `phase_context` actually queries NewsAPI before planning and uses normal publisher fetch. Legacy preserved-config registration checks conflicts/denies, updates scoped allowlists and constructs trusted wrappers; prefetch precedes research. | Controlled legacy test invokes the real wrapper inside a scripted stream; it is not proof that a deployed native runtime selected the reflected tool. Actual market/social dispatch through both engines is less covered than news. No live/deployed-runtime claim. |
| Pre-QA versus final citation namespace | V3 seals without positional refs, renders current ledger refs before QA, renumbers cited-only sources, and stores the final canonical-URL map in QA metadata. Legacy appends link-based context before citation finalization/judge. | The v3 regression deliberately inserts an uncited earlier row (`test_news_research.py:144-191`) and checks different final positions. Capture URLs, not optional lane-local S refs, remain authority. Final consumer mapping must be rechecked with the parent's freeze. |
| Source metadata retention | News provider/kind/publication/retrieval/publisher/native/language metadata survives ledger reload and final sources; successful fetch alone sets fetched/hash. Legacy attaches bounded `context_evidence` to actual fetched sources. | Full market evidence is not retained by v3 ledger/source projection (PR-2). Multiple captures sharing one canonical publisher URL also use one source-ledger identity; final context JSON remains capture authority. |

## Evidence boundary and source drift

No tests, application imports, vendor code, provider probes or services were executed by this reviewer. Worker documents are treated as reports, not independent passing evidence. The parent joint directory is a frozen source mirror, not itself a success receipt. Its manifest was located; no outcome was assumed or copied into acceptance claims.

End-of-read check at **2026-10-18T12:58:09Z** observed concurrent edits to three inputs:

| Path | End-of-read SHA-256 | Review effect |
|---|---|---|
| `deerflow_bridge/news_signals.py` | `214b975346551161ffabbd49ac0205a73cf433b19ea9f21046aacb78f16fe0a3` | Read the changed lock-open retry/deadline block at 314-356 and shifted admission/render ranges. Initial hash is historical; this is still provisional. |
| `backend/tests/test_news_signals.py` | `ac68b48eeaacabc6365ccaaaa7db27c86cdb9952238537cca470a6d11e54b90b` | Read added contention/deadline/deletion/master-off/Reddit checks at 808-869. These are assertions, not results. |
| `backend/tests/test_news_research.py` | `2768ba05d7162760d850c1402e0542102317c889bdab4103fb015fd1731bb92d` | Read the extended legacy streamed-use/pre-QA/resume scenario at 286-345. |

The other primary source/test hashes in the initial identity table remained unchanged at the end-of-read check. Additional supporting read identities:

| Path | SHA-256 | Reading scope |
|---|---|---|
| `docs/handoff/oddsense-integration/PLANS.md` | `157b8e5319c74250d6c1c7681769deecf50ef596ab810d304f2ca4ea03998331` | Requirements and positive/negative scenario clauses |
| `backend/app/utils/prediction_markets.py` | `39fabbe003ba1d5741ca3795939da27f4fb39b9b49ea508b743ce6d61c103081` | Provider/dispatch symbol scan; not full-file review |
| `backend/app/services/report_agent.py` | `a0081e4d6b46561b4592a25c58eea2c8a77328548d33ce8144ce4e63125d81b8` | Market/context/dispatch symbol scan; not full-file review |
| `backend/tests/test_news_context_pipeline.py` | `2b4da4738a329c70b6ab5db53d1cd96bc7193d0ceb57b064c4934e656ee79189` | Context/merge/provider assertion scan |
| `backend/tests/test_news_context_reports.py` | `752ecc0dc88ba82b7004a6a4e927428161c41a57334f9cd2bdea8883b8d2fe18` | Context/report-binding assertion scan |

## Final-freeze recheck required

Parent should supply the final frozen source identities and joint-gate receipts. Recheck PR-1 and PR-2 on those exact bytes, match every executed scenario to the manifest, verify final quote presentation/citation mapping, and explicitly close or retain each finding. A green sequential market suite alone cannot close PR-1; successful news end-to-end use alone cannot close PR-2. No broad redesign or unrelated cleanup is required by this review.

Initial review delivered with **one P1 and one P2 open**. Implementation acceptance remains provisional.

## Final-freeze attempt 1 recheck — 2026-10-18

### Freeze identity and comparison scope

Reviewed mirror: `/private/tmp/drf-oddsense-final-joint-vksogbeu`. Its `oddsense-source-manifest.json` SHA-256 is `9422d4a0fceead2fe87f3d9cabcf62b8637ea7ea40d355d47e7ee6cedf984c16`.

For each of the following **24 scoped files**, the manifest's expected SHA-256, the actual frozen-file SHA-256, and the current implementation worktree SHA-256 matched at the recorded check. There was **no drift in this checked scope**. This is not a claim to have independently hashed every unrelated file in the complete manifest. Application source was read, never imported or executed. Only this review document was edited.

| Path | Matching manifest / frozen / worktree SHA-256 |
|---|---|
| `deerflow_bridge/news_signals.py` | `ffc7a2d720bf3943116d4a3ff0636ce77b1134b743b82c361a9af4e8f88e0d45` |
| `deerflow_bridge/market_intelligence.py` | `e5f5525f0c34d651417808c5fd16453df00e0061cb3e02cf6ca4f31c2c796cae` |
| `deerflow_bridge/news_tools.py` | `a0ee232160113bd88c7418637cb7bd50db40951edcad5c2e4e38e78af6af592c` |
| `deerflow_bridge/research_gateway.py` | `f99839713cd2d50bed1580acaa843cc049ed7fe187219372b253e4b9e13b2003` |
| `deerflow_bridge/linear_research.py` | `aba8869dbf8386d3afd118f43ab685c4f204b7a590a2036aeb0e2aa4bc2c901b` |
| `deerflow_bridge/deerflow_research.py` | `f7ff138fdbaa0cf84625bd92212a13ee8fa914c374c42fe57d7318d0b6214d87` |
| `deerflow_bridge/market_tools.py` | `eed4d54cf31202a07c4ad88091b6f5cdb57292c0001f4b6e9f12c827ea2bc061` |
| `deerflow_bridge/research_budget.py` | `bf698af519aefd686994fddc7224e47775157597de3a77b691e267cd8c7ba636` |
| `backend/app/services/news_market_context.py` | `b52a36170ef81c7760cb14ea46fd762d27144052c91dbc6649e0a5153ab2e136` |
| `backend/app/services/report_agent.py` | `77475afcac5fd1fac7e65bf22469970b477ee117afa73a4117942be1fbc6750e` |
| `backend/tests/test_news_signals.py` | `75eec3560cc7e8ae6be93bd64ff53e1453253a276113cd496891b048a68c9fc6` |
| `backend/tests/test_market_intelligence.py` | `4c97eb3e76958b54ec517baf85d6b7884cc9848a2153490dfc68ff502a709298` |
| `backend/tests/test_news_research.py` | `827b4b2edf8363234b852312a046818e96176d92ec5dd79c8c4f88b0b620e3d5` |
| `backend/tests/test_news_context_pipeline.py` | `3dc2d555414e25d41054beb2b5c18a41d68a27c9584dd002b38ab800f00931a8` |
| `backend/tests/test_news_context_reports.py` | `3b2b49bc4396fd6a94db736a4275c3c417697bbd1e97009d9c7e4ace42949aff` |
| `backend/tests/test_news_report_metadata.py` | `da733e2cc6e36a97a24e04301adb145eed057defb1f7c6570282df246d7d750e` |
| `backend/tests/test_oddsense_workflow.py` | `d298dad0628c4e4f74eaf8eefb6091e9d991bb2792b9dadce5b2be3abf98be8f` |
| `backend/tests/test_research_engine_v3.py` | `d8070f98bbf97cc6a45694ea3cd572e539c2c01df5850f9491d78a5dacf577eb` |
| `frontend/src/utils/sourceContext.js` | `955aef5af13fbed2ebaa9ed9db0bbe9d4195b74ce386116e1bb70b78888424dd` |
| `frontend/src/components/research/SourceContextPanel.vue` | `cfbf6b47107b3c75c0860cf380256526bf19960611bdff579b66c2fccc58ac2e` |
| `frontend/tests/sourceContext.test.mjs` | `708c0b346b6394c909877c579e708b2a1780585119797cdc88d2de8b36d0fa33` |
| `frontend/tests/sourceContextPanel.test.mjs` | `f5bb79badfe4bfa965042e315943140048922bf689a3d48cd0a173b4202bacce` |
| `docs/handoff/oddsense-integration/integration-contract.md` | `0fb0fffdecea9c7195d678ce65e4422bf4af89f2cd61d01a8dba7c530ceabcb5` |
| `docs/handoff/oddsense-integration/PLANS.md` | `157b8e5319c74250d6c1c7681769deecf50ef596ab810d304f2ca4ea03998331` |

The contract differs from the initial review's historical hash because it now includes explicit coordinator amendments for canonical parent-question identity, atomic market capture, sealed-state monotonicity and actual comparison presentation. Those amendments were read and used in this recheck.

### PR-1 disposition: resolved on attempt-1 freeze; carry forward for fresh-freeze verification

`news_signals.py:827-926` now owns `capture_market`. Under the existing process/file lock it checks identity, replay, sealed state and the query cap before calling acquisition. It persists interrupted proof first, and its reservation callback updates the shared high-water counter, charges the existing research network budget and writes/fsyncs the reservation before returning permission. Migration uses the maximum of overlapping old/new per-query representations and the durable high-water count (`:858-872`). Interrupted requests retain their allowance. `market_intelligence.py:180-197` invokes the callback immediately before each HTTP dispatch; `:398-427` requires the atomic API and fails closed when it is unavailable. No second persistent store or competing lock was introduced.

This is supported by matching passed JUnit cases, not just the broader pass count:

- `test_two_processes_reserve_before_http_and_share_generation_allowance[True/False]` (`test_market_intelligence.py:475-508`) starts separate guarded processes with real clients, a generous research network budget, actual adapter/store code and scripted HTTPS. Independent physical logs, SQLite network accounting and the stored market counter must agree: three calls for identical queries and four for distinct queries.
- `test_interrupted_process_preserves_spent_allowance_and_never_refetches_capture` (`:511-542`) interrupts the child after its first physical call, checks durable interrupted proof, and limits subsequent captures to the remaining allowance. This includes a successful new-provider/new-query control rather than disabling all acquisition.
- `test_full_query_table_blocks_acquisition_before_physical_http` (`:545-556`) asserts zero requests and an unchanged snapshot for a full table.
- The provider suite's migration cases (`test_news_signals.py:1130-1172`) passed for old/new count combinations and an existing larger high-water counter.

The original PR-1 defect and its missing process/crash/full-query coverage are addressed on these exact bytes. Subsequent provider/engine changes still require comparison with the next freeze; this is not approval of future bytes.

### PR-2 disposition: resolved on attempt-1 freeze; carry forward for fresh-freeze verification

`research_gateway.py:2379-2440` now supplies bounded typed market metadata/text with explicit null and zero. `:2599-2603` stores it in the ledger; `:4023-4047` returns provider status plus captured contract text in the actual v3 tool answer. `linear_research.py:4849-4871` exposes the same captured fields to synthesis; `:7696-7706` retains them in final source rows and labels an unfetched quote `context_quote`. `news_signals.py:1012-1067` renders bounded quote/rule/units/horizon/unknown-time details.

The passed `test_market_contract_reaches_real_gateway_kiq_synthesis_and_source_projection` (`test_news_research.py:402-488`) exercises the actual adapter, store, gateway, KIQ dispatcher, synthesis digest and source projection. It asserts No-first Polymarket `.2` versus `.8`, Kalshi `.43`, dollar/contract units, primary/secondary rules, threshold/horizon, null quote time, replay without another request, ledger reload, final metadata equality and zero preservation. This directly covers the original consumer defect.

The report adapter preserves native yes bid/ask/last, aliases, quote/probability bases, outcome, null quote time, rules, horizon and participation units. In `report_agent.py:3588-3656`, only exact canonical validated metadata lines receive special handling; the owned block has unique SHA-bound start/end markers, validates the exact stored capture and restores before publication auditing. Missing/ambiguous markers and a different valid capture fail. `:9614-9632` restores around citation stabilization; `:13537-13570` puts context before the final read-only audit. Both new metadata tests passed, including preservation of an authored matching heading and refusal of a changed generation. The real report-sequence cases (`test_news_context_reports.py:137-216`) passed through promotion, simulation binding, report generation, final audit, API and Markdown export with native Kalshi fields retained. The full scripted workflow case also passed in this same freeze.

### New P2 PR-3: changed-question archival leaves the old root capture and cached client active

**Disposition: OPEN on attempt-1 freeze; parent acknowledges repair in progress.**

**Anchors:** `linear_research.py:1238-1260`, `:4704-4712`, `:4794-4819`; `news_signals.py:940-956`. Existing reproducer: `backend/tests/test_research_engine_v3.py:942-965`.

The existing v3 behavior deliberately archives `v3/` when the question/run identity changes and starts a new run in the same output directory. The new root-level `news_market_context.json` is outside that archive, and `get_context_client` retains its process-cached binding by root. `_configure_context` then loads the old capture and requests the new identity from that same root/client, producing an integrity error instead of a fresh, separately archived generation. This occurs even when the old capture only records provider unavailability and no key was used.

**Observed evidence:** The joint JUnit reproducer successfully completes the first question and its same-question no-model-call resume, then fails the changed-question assertion with return code 2. Its actual saved `pytest-tmp/test_resume_skips_done_phases_0/out/meta.json` records `news_context_evidence_corrupt: ContextIntegrityError`; SHA-256 `e4623e13b27523cea93e08bde016868b51add994b7e9b987d0b2b16c09d0ee63`. Source inspection confirms the old context/cache are not retired by `_open_work_dir`.

**Narrow fix:** Extend the existing proven different-identity archival transition to preserve and retire the old root context with its owning run, and explicitly retire its cached client before admitting the new generation. Keep same-identity replay and present-proof corruption/mismatch checks strict. Merely relaxing identity checks, ignoring the error, disabling the feature in this case, or deleting the old proof is not a valid resolution.

**Acceptance and positive controls:** With context explicitly ON, finish question A in one directory, resume A without new provider/model work, then run question B in the same directory and require success with a distinct correctly bound context generation. Preserve A's sealed bytes in the archive, verify B cannot see A's items, and reopen/resume B in both the current and a fresh client/process. Same-question tampering/deletion and foreign-parent identity must still fail closed. Existing same-identity resume is the successful positive control already observed immediately before the failure. Add the changed-input ON case independently of the old web-only fixture's feature-off setup.

**Plan/coverage:** This is a regression in an existing supported lifecycle, not an expansion of provider scope. The existing regression caught it, but the dedicated context-enabled archival case is missing in attempt 1. The parent's latest instruction explicitly requires that ON case and a fresh freeze, and confirms the research worker is implementing preservation/retirement rather than stale reuse or return code 2. That report is progress, not evidence of a completed fix.

### Receipt assessment and limits

Read `/private/tmp/drf-os-final-joint-20261018-1/completed.json` and `junit.xml` directly. The gate completed with **exit 1: 1,379 passed, four failed, two skipped, zero errors**, 1,385 total tests. Shutdown completed, identity was preserved and the receipt's recorded source-drift list is empty. Its audit still records **four denied subprocess attempts and 18 denied external reads**, plus 26 allowed guarded children; these are not zero attempts. The deliberately interrupted admission fixtures account for expected nonzero child exits and are distinguished from pytest failures by their passing test results.

All **216 test cases across the seven new provider/market/research/context/report/metadata/workflow modules** have passing testcase entries without failure/error/skip children. In particular, the parent actual `_run` deleted-declared-capture and PREPARE late-addition cases passed with old/off positive controls (`test_news_context_pipeline.py:326-379`). These results support the specific inspected behaviors; they do not make the full gate green.

The four failures are:

1. `test_e2e_happy_path_writes_every_artifact`: existing fixed heading count does not include the new context section.
2. `test_e2e_prefix_cache_invariants`: existing assertion requires the original web-only tool-schema object while the integration correctly exposes enabled tools in one stable extended object.
3. `test_e2e_section_order_survives_out_of_order_completion`: existing exact heading list does not include the context section.
4. `test_resume_skips_done_phases_and_archives_a_different_question`: legitimate lifecycle regression PR-3 above.

The two skips state that the vendored DeerFlow harness snapshot is absent. The parent's plan to explicitly feature-off-isolate old web-only fixture expectations is appropriate only while preserving the independent ON suite and PR-3's ON lifecycle check. No check is considered resolved merely by changing a broad expectation.

Receipt SHA-256 values: `completed.json` = `ff1702a7b291dfa869eb6857f09a7606513b925b9703d83d23430814473fb528`; `junit.xml` = `73e2a4403961ac25d6864d2ad0ba925f0e2bd7950ef023dff243353793015d99`. The earlier `/private/tmp/oddsense-e2e-markers-20261018-1401` receipt also records four passes and exit 0, but uses another source mirror and test-file hash; it is historical proof, not the final-freeze acceptance gate.

Frontend original-ledger-reference EN/ZH source and regression assertions were inspected (`frontend/tests/sourceContextPanel.test.mjs:301-332`): original S1/S87 are explicitly labeled as research-ledger identifiers with direct source links and cannot become report citation anchors. Frontend execution was not performed by this reviewer, and the reported frontend/lint/targeted-report totals from the parent were not substituted for the inspected guarded receipt.

### Next exact-freeze gate

The review remains **pending**, with PR-3 open and the two original findings resolved only for attempt-1 bytes. The next recheck must compare the new manifest, actual frozen files and current parent files, read the new ON changed-input archival case and its result, confirm old capture/cache retirement without weakening replay/tamper rules, and revisit provider reservation and quote/citation presentation wherever those bytes change. Final closure requires that concrete evidence; the attempt-1 broader pass count alone cannot close remaining work.

## Accepted final-freeze recheck — 2026-10-18T13:35:10Z

### Exact source identity and drift

Final mirror: `/private/tmp/drf-oddsense-final-accepted-ub26ztb5`. Complete source manifest SHA-256: `08aa62f5f0cd29c0daf6db17ee1f34ea1f8ff33e0b844678708a20a0a122bfdc`.

Repeated the three-way manifest / actual frozen file / current implementation worktree comparison for the **same 24 review-scoped paths**. All matched; no drift was found in that scope. Additionally compared all 18 `oddsense-workflow.json` `source_before` file hashes with the actual final mirror and current worktree: all matched. The workflow artifact's before/after maps are identical, and its `source_unchanged` is true. The receipt also reports no recorded source drift. These statements specify their scope; they do not claim independent inspection of every unrelated manifest file.

Seven scoped files differ from attempt 1. Their current hashes are:

| Path | Matching final manifest / mirror / worktree SHA-256 |
|---|---|
| `deerflow_bridge/news_signals.py` | `dc0dca47e0dc1c2d07878eb1a851c0c37a9b0c968a80b009e6fcbc97002f287b` |
| `deerflow_bridge/linear_research.py` | `d34299e79d751848052c25ab999782cb94068a98d82d0daead97444052b68cd1` |
| `backend/tests/test_news_signals.py` | `fc1dd9a5e69cfed2cc5408a9933a61eb32d54e3286e1ab83f1e2cfe71c25185e` |
| `backend/tests/test_news_research.py` | `7fbaa25a3ac3f3a7ebb1ad05dd0a0a342a228c84bba77e9fd639515e40533b2d` |
| `backend/tests/test_research_engine_v3.py` | `3a47699a7677f4a5f33c987ee3112aa79d6765df5a87af8369d23f3da81c3d87` |
| `backend/tests/test_news_report_metadata.py` | `ceb958f276e65ddf6fd7331baeb3ae053798592c4f0e8666e72e7d68b1b1f63a` |
| `docs/handoff/oddsense-integration/integration-contract.md` | `134a3440d4fede65f5cf2aae979087ee858da9e06fd9bb597c658bad00842761` |

The other 17 scoped files retain the hashes in the attempt-1 table and also match the new complete manifest. In particular, market adapter, research gateway, both report/context adapters, legacy research engine, market process tests, E2E test and frontend citation components/tests are unchanged. The report-metadata test change only explicitly re-exports the original fixture implementations; its assertions remain intact. The contract adds the narrow explicit new-run retirement API; this amendment was read.

### PR-3 closed: actual archive boundaries and new generation admission

Inspected the full new `archive_context` implementation (`news_signals.py:387-466`), the full changed `_open_work_dir` transition (`linear_research.py:1238-1289`), retired-client checks and the cache lookup ordering. The fix addresses the observed integration defect without relaxing ordinary identity validation:

1. Same valid run identity still returns the existing work/state before any archival logic. A different identity may retire context only when the previous state has a valid binding; missing/corrupt/undeclared proof fails rather than becoming an acquisition opportunity. The engine loads sealed proof and compares the exact old generation/digest before invoking the provider API (`linear_research.py:1261-1284`).
2. The provider revalidates that exact capture under its existing bounded root/process lock. The destination must be an existing descendant of the same root, with safe directory traversal and no existing destination file. Descriptor-relative no-follow operations, source inode/link checks and no-clobber link/unlink preserve the original bytes. The preserved archive directory entry is fsynced before the active entry is removed (`news_signals.py:395-444`). An unsuccessful retirement cleans up only its newly created matching archive link and preserves active proof/cache (`:445-459`).
3. Only after successful retirement does the provider remove the matching cached root registration and mark the old object retired (`:460-465`). Existing references fail closed; a new explicitly requested generation gets a new client. Research code does not mutate cache internals. The engine then renames the work directory containing unchanged old state and proof into the ordinary stale archive.
4. Cache lookup obtains the root lock before briefly accessing `_CACHE_LOCK`, and releases the global cache lock before constructor/snapshot I/O (`news_signals.py:1027-1053`). This agrees with archiver root-to-cache ordering. `_thread_lock` releases its short registry lock before waiting for a root lock; no reverse held-lock acquisition was introduced.

The **passing context-ON scenario** `test_news_research.py::test_context_on_changed_question_archives_capture_and_uses_new_generation` (`:491-525`) executes the real engine lifecycle for A and then B in the same output directory. It verifies byte-for-byte preserved A capture, unchanged archived A state, valid archive loading, B's distinct generation and full question hash, actual new acquisition, B's new state/digest binding, a different cached client, and refusal by the old client. Acquisition responses are scripted; engine, store, archival, ledger and state behavior are production implementations. This directly resolves the failing attempt-1 scenario.

Additional passed provider cases (`test_news_signals.py:1175-1298`) cover successful acquisition after retirement; old-client refusal; wrong generation/digest; corrupt/missing source; existing/linked destination; symlink/external/missing archive; injected unlink failure retaining proof/cache; and independent-root lookup while current-root constructor/snapshot I/O runs. Both cached and uncached lookup controls passed. The historical web-only v3 fixture now explicitly sets `NEWS_CONTEXT_ENABLED=false` (`test_research_engine_v3.py:48-56`) while retaining its strict schema/order checks; it does not replace the separate ON acceptance. Its formerly failing same-directory resume/changed-question test now passes too.

**PR-3 disposition: CLOSED on the final hashes above.** Old capture preservation, valid new admission, and refusal controls are all supported by source and scenario-specific receipt entries. No missing plan coverage remains for the reported changed-question defect. Exhaustive process-crash recovery of every archive filesystem instruction is outside the claimed scenario coverage; inspected interrupted states preserve proof and fail closed rather than silently reacquire.

### PR-1 and PR-2 reconfirmed on final bytes

The provider diff adds archival/retirement/cache-order behavior; the durable market reservation algorithm is unchanged except for shifted anchors (`news_signals.py:914-1013`). Root identity/replay checks remain before acquisition, old/new count migration remains a maximum rather than a sum, and each request still persists its reservation before HTTP. In this new gate the actual two-process same/distinct-query, interrupted-process and full-query-table market cases passed again. **PR-1 remains CLOSED.**

The gateway/market adapter/report adapters are hash-identical to attempt 1. The engine's added archive transition does not remove captured-contract presentation or final metadata projection. The provider renderer is unchanged except for shifted anchors (`news_signals.py:1109-1164`). The real market-to-gateway/KIQ/synthesis/source-projection case, native-quote report sequence, metadata ownership tests and the full scripted production-to-publication workflow all passed again in this new gate. **PR-2 remains CLOSED.**

Also checked passing receipt entries for deletion of bound proof, same-ID seal rollback/resealing, invalid/foreign parent question identity, actual parent deleted-declared-proof and PREPARE late-addition guards. These controls remain effective; new-run archival does not substitute for same-run tamper recovery. The prior source-backed observations for missing/unknown versus zero, literal Yes, EN/ZH identity, safe bounded acquisition, separate canonical-market ownership and citation namespaces still apply to the unchanged relevant code.

### Final receipt and evidence limits

Read `/private/tmp/drf-os-final-joint-20261018-2/completed.json`, `junit.xml` and the selected structured workflow evidence directly after completion:

- **1,399 cases: 1,397 passed, two skipped, zero failures, zero errors; exit 0.** Both skips are the same missing vendored-harness snapshot cases. All **230 cases** across the seven new integration modules passed. Shutdown completed and identity was preserved.
- The audit records four denied subprocess attempts, 18 denied external reads and 26 allowed guarded children, with contained fc-list/system_profiler/font-directory probes. These are retained as observed attempts, not reported as zero. Intentional crash/termination children remain distinct from testcase failures.
- The actual scripted workflow records `publication.publishable=true`, `replay_no_new_calls=true`, unchanged source identities and the expected frozen provider/engine/report hashes. Its explicit flags are `controlled_scripted=true` and `live_provider_proof=false`. This supports offline integration and publication behavior, not live provider availability, deployed native-runtime selection, forecast quality or a live deployment claim.
- This reviewer performed no source/vendor execution, tests, provider calls, credential access, Git operations, services or agent creation. Only `provider-review.md` was edited. Frontend runtime totals remain parent-provided rather than independently rerun; the unchanged EN/ZH original-ledger-reference source/regression was inspected in the preceding recheck.

| Evidence | SHA-256 |
|---|---|
| New complete source manifest | `08aa62f5f0cd29c0daf6db17ee1f34ea1f8ff33e0b844678708a20a0a122bfdc` |
| Second joint `completed.json` | `2f591bcde3d10fcee73643674cbd6b2678c74e33417c27053a0b0869d5dc2759` |
| Second joint `junit.xml` | `d5f2ec5838ab11ba2d699da4933dd5ab6ef8300b2ddbca8ce8b7efc36d3054a7` |
| Second joint `oddsense-workflow.json` | `2154e8d92131f279810a2ebd2a526138cf9cae4842b31d2551eed1a933d11f18` |

**Final review result:** PR-1, PR-2 and PR-3 are closed for this exact final freeze. No remaining concrete P1/P2 was found within the assigned provider/research review scope. No broader redesign is requested. Future source drift invalidates this exact-byte closure and requires a scoped recheck; historical findings and the failed first gate remain preserved above.

## Acquisition-time candidate review — 2026-10-18T14:41:35Z

**Verdict: REQUEST CHANGES. No new P1 found; P2 PR-4 and PR-5 are open.** The reviewed candidate fixes the originally reported idle-planning failure, but the two remaining source-observed cases are not covered by the green matrix. No source or test was edited or executed by this reviewer. This is the single final documentation update for this candidate review.

### Exact reviewed bytes and evidence

Candidate mirror: `/private/tmp/drf-oddsense-idle-budget-final-t8hxvw7r`; complete source manifest SHA-256 `10960dfc4c08418e0b4ff737604f95a235d095d40ebc883fb1ce6c18380e5c1f`. All five requested source/test files match the manifest, actual frozen files and current worktree at the last check:

| Path | SHA-256 |
|---|---|
| `deerflow_bridge/news_signals.py` | `e76454cf6b5e0de2870ff6b32c7bbbd8dc394748e0045853e5693917e3381c04` |
| `deerflow_bridge/market_intelligence.py` | `1017766daf27b35533f03d3089b00713a5e72130c1945e00d251c0be50f7b67f` |
| `backend/tests/test_news_signals.py` | `0692d703dcf68055a2e3424ab7db47e986438a031f1d2f738d04879a590091b0` |
| `backend/tests/test_market_intelligence.py` | `405a8e0af174c56a131c88fdca99fb4e37f7dd2ad5cc141e3a45ec97bb17a93e` |
| `backend/tests/test_oddsense_workflow.py` | `5d9799ca0efa09a386bf7255fa51840a28024dfa5a036042b87f6fdbf839891c` |

**Documentation drift, explicitly distinguished from source drift:** The frozen contract remains `134a3440d4fede65f5cf2aae979087ee858da9e06fd9bb597c658bad00842761`, while the current worktree contract is `8294ed04988eed9725baa41404d785719b3c0e746cf57d3fc9915d11b9d168f9`. The coordinator's new cumulative-acquisition amendment was read in the current document. It is newer documentation and is not claimed to be part of the already executed source freeze. README/env/plan edits were not included in this five-file behavioral review.

Directly inspected evidence:

- `/private/tmp/drf-os-idle-budget-red-20261018-1`: five failing cases, including both news and market calls blocked after a simulated 120-second planning gap. This is meaningful behavioral red for the prior implementation.
- First focused candidate: 188 passes and two failures. The empty market fixture's `verified_empty` status and conservative crash reservation explain those two expectation failures; the second candidate corrects the expectations without granting extra acquisition.
- `/private/tmp/drf-os-idle-budget-green-20261018-2`: **196 passed, zero failures/errors/skips, exit 0**, shutdown complete, identity preserved and no recorded source drift. Its workflow records `simulated_planning_gap_seconds=120`, `source_unchanged=true`, publication permitted and no new calls on replay. The full engine shifts source wall time inside the real planning phase; unit cases advance both wall and monotonic time. External transport/model responses remain scripted, and `live_provider_proof=false` remains explicit.
- `/private/tmp/drf-os-delivery-final-20261018-1`: **1,448 passed, two existing missing-vendored-harness skips, zero failures/errors, exit 0**; 1,450 cases in 31.407 seconds. Shutdown completed, identity was preserved and recorded source drift is empty. The audit retains four denied subprocess attempts, 18 denied external reads, three denied `os.kill` attempts and 26 allowed guarded children. These are observed attempts, not zeros.

| Receipt | SHA-256 |
|---|---|
| Focused green2 `completed.json` | `b8e7eae139915cb7f95142c49b8c9019f3f6cbda7bdf40148137491ac3d1adfd` |
| Focused green2 `junit.xml` | `9c8365bf1fc47b2742b734a46c4ba04cf43db68e0fecc6e7732f32b2329e45fa` |
| Focused green2 `oddsense-workflow.json` | `d8bb578d9cc130f3ef36b81ff2c08107259a6288508113498a96ca8013f5db0e` |
| Delivery matrix `completed.json` | `21754e9aedbd82fc49135baee60d87f01ba4616291b8a6d2aa62ec7a6c702eeb` |
| Delivery matrix `junit.xml` | `913e0a9ec6b9b254b5174d39bd16a0b720d95f71e3ded76dd2ae152a92433d4d` |

### P2 PR-4: News completion compares total elapsed with the reduced transport timeout

**Anchors:** current/frozen `news_signals.py:812-821`.

The timer starts before the pending write, as intended. After that write, `timeout` is narrowed by subtracting the elapsed pending-write time (`:815-816`). After acquisition, however, `time.monotonic() - started` still includes that same write and is compared against the reduced `timeout` (`:820`). This counts persistence time twice when deciding whether a successful response met its deadline.

**Concrete valid scenario:** Grant 1.0 second, advance monotonic time by 0.3 seconds in the pending reservation write, then let the transport return valid articles after 0.5 seconds. The native transport receives at most 0.7 seconds and completes in 0.5; total acquisition/persistence elapsed is 0.8, within the original 1.0-second absolute grant. The current check evaluates `0.8 > 0.7` and incorrectly replaces the successful result with `timeout/http_deadline`. Very small remaining budgets or slow fsync make this reachable without a provider timeout. It loses a valid article capture and durably consumes one of the two NewsAPI requests.

**Narrow fix:** Keep an absolute completion deadline based on the original grant/start and the caller's bound. Narrow only the transport's remaining timeout after persistence; compare completion against that absolute deadline, not against the residual duration measured from the earlier start. Do not move the timer after fsync or extend the deadline.

**Acceptance / positive controls:** Add a deterministic pending-write delay of 0.3 and valid transport elapsed of 0.5 under a 1.0 grant: expect success, transport timeout at most 0.7, one physical call and durable spent time about 0.8. A matching control exceeding 1.0 must remain timeout; a caller deadline exhausted during the write must perform no HTTP. Current tests model idle gaps and transport elapsed, but do not advance time in the pending write, so the green matrix does not cover this condition.

**Disposition:** OPEN, source-observed; reviewer did not execute a reproducer. This is a completion-classification defect, not a request to relax durable reservation or the aggregate cap.

### P2 PR-5: Legacy market captures with counts but no start marker regain an unknown allowance

**Anchor:** current/frozen `news_signals.py:754-758`.

For a legacy envelope without `acquisition_seconds`, `_spent_seconds` treats only a truthy `network_started_at` as proof of unknown prior acquisition. With no start marker it returns zero, even when provider/query `network_requests` or `request_count` proves prior physical admissions. A legacy unsealed market-only capture can therefore acquire another full ten-second allowance despite unknown earlier spent time. The four-request cap survives, but the cumulative acquisition-time cap can be exceeded across the upgrade.

This is an actual source-produced historical shape, not a hypothetical arbitrary envelope. In the initial frozen `/private/tmp/drf-oddsense-joint-first-qdwaaq4i`, `market_intelligence.py:409-453` performed HTTP, set each result's `network_requests`, and called `record_result`; that path never set `network_started_at`. The historical adapter hash is `6fb7dbb8622460e9be39dbedeb37bd647f8fb2b04e48ffe1b311695d65e2733a`, already part of the initial review. Its shared store hash is `9643a06fd77b7a8ff6d6d54dcc4a10044c0ca7540db0511595b5309d46af0cf9`; only its separate news acquisition path set the start marker.

**Narrow fix:** When the time counter is absent, recognize bounded positive legacy network/request counts as prior acquisition evidence as well as the start marker, and conservatively admit no additional unknown time. Retain ordinary replay and the existing count high-water reconciliation. A genuinely untouched generation with no prior-I/O evidence should still have its allowance; a sealed legacy capture should replay without mutation.

**Acceptance / positive controls:** Start from a valid legacy unsealed market envelope with one saved physical request, no `acquisition_seconds` and no `network_started_at`. Existing-query replay must succeed without I/O, but an uncaptured query must not invoke acquisition. Also test an untouched legacy envelope with zero calls admitting acquisition, and sealed legacy replay preserving bytes. The current added migration test always injects `network_started_at`; the older count-migration tests retain a new generation's explicit zero time counter, so neither reproduces this missing-counter/no-marker shape.

**Disposition:** OPEN, source-observed; no source/provider execution was performed. This extends the candidate's explicit conservative migration rule to its already supported historical market count representation, without a new store or redesign.

### Design portions accepted, and stopping condition

The finite, nonnegative counter validation rejects booleans and malformed values. New generations start at zero. Under the same cross-process root lock, news reserves its bounded timeout and markets reserve the residual callback allowance before acquisition; completed paths settle once to monotonic elapsed and a crash preserves its reservation. The active market callback correctly computes remaining time from pre-reservation spent time rather than treating its own debit as exhausted. Its trusted absolute deadline narrows native connection/body timing (`market_intelligence.py:180-213`). Existing two-news/four-market network admission is unchanged. Updated interruption, invalid-counter, native-timeout and 120-second idle-gap cases are appropriate positive and refusal controls.

The idle/model gap defect is therefore addressed in the candidate, but **commit approval is withheld for PR-4 and PR-5**. Two narrow fixes plus the specified targeted scenarios and matching frozen hashes are sufficient for recheck. A repeat broad green run without those scenarios cannot close either finding. Earlier PR-1/PR-2/PR-3 dispositions remain tied to their historical bytes and are not used as blanket approval of this new timing change.

## PR-4 / PR-5 exact-byte closure — 2026-10-18T14:46:01Z

**Final disposition: both findings CLOSED. No remaining concrete P1/P2 in the assigned narrow fixes, migration/crash/cross-process controls and receipt review.** This closes the acquisition-time review for the final bytes below. No further application/API change or broader audit is requested by this reviewer.

### Frozen identity and drift check

Mirror: `/private/tmp/drf-oddsense-delivery-reviewed-nv9hnl2h`. Its complete `oddsense-source-manifest.json` SHA-256 is `815646fc6c39736eef4f6b8bd3648e5cd006f33c37b52d24091eb11b6e4b7ff9`.

The manifest, actual mirror files and implementation worktree match for all five scoped source/test files. No source drift was found in those paths; the executed receipt also reports an empty recorded drift list. Only the provider module and its test file changed from the previously reviewed timing candidate; the other three retain their preceding candidate hashes.

| Path | Matching manifest / mirror / current worktree SHA-256 |
|---|---|
| `deerflow_bridge/news_signals.py` | `58390a6286e4366cf478c9fdb21536a2fff87821f70c1c6a8045fd399e4c5b70` |
| `deerflow_bridge/market_intelligence.py` | `1017766daf27b35533f03d3089b00713a5e72130c1945e00d251c0be50f7b67f` |
| `backend/tests/test_news_signals.py` | `a8433512d64d5b40630b4d11130f67c83509bbfcec04c9ada45ebbbd451949c0` |
| `backend/tests/test_market_intelligence.py` | `405a8e0af174c56a131c88fdca99fb4e37f7dd2ad5cc141e3a45ec97bb17a93e` |
| `backend/tests/test_oddsense_workflow.py` | `5d9799ca0efa09a386bf7255fa51840a28024dfa5a036042b87f6fdbf839891c` |

### PR-4: CLOSED by the original absolute grant and both timing controls

Read the final `_search` sequence at `news_signals.py:806-834`. The timer remains before the durable pending write, and the transport receives the reduced post-write timeout, also constrained by the caller's remaining deadline. The completion decision at `:826` now compares against `started + remaining`, the original absolute grant, instead of comparing total elapsed against the reduced transport duration. A pre-dispatch expired timeout follows the no-acquisition result path. Settlement still charges actual monotonic elapsed once.

The matching passed cases `test_pending_write_and_transport_share_one_absolute_deadline[0.5-ok]` and `[0.8-timeout]` (`test_news_signals.py:488-509`) advance the first durable write by 0.3 seconds under a 1.0-second grant. They assert a 0.7-second transport timeout, one physical call, success for 0.5 seconds of transport and timeout for 0.8, with actual durable elapsed respectively 0.8 and 1.1. Thus both the previously rejected valid response and the true-overrun control are covered.

### PR-5: CLOSED by all legacy prior-I/O representations and untouched/sealed controls

Read final `_spent_seconds` at `news_signals.py:754-764`. An explicit validated counter remains authoritative. If it is absent, the start marker or a positive valid integer in root network counters or per-query `request_count` / `network_requests` conservatively exhausts unknown prior acquisition time. Untouched legacy zero counters retain their allowance. Replays occur before new-acquisition admission, and sealed replay is not rewritten.

The news path computes prior `spent` at `:812` **before** incrementing its new network count at `:813`. This prevents the first request of an untouched legacy generation from being mistaken for earlier unknown I/O.

All five corresponding cases passed: the three `test_legacy_positive_market_counts_without_time_marker_cannot_regain_time[root/request_count/network_requests]` variants replay saved evidence while refusing fresh acquisition; `test_untouched_legacy_generation_still_has_acquisition_allowance` performs both permitted news requests across a client reopen with low actual spent time; and `test_sealed_legacy_counts_replay_preserves_exact_bytes` retains byte-identical sealed proof. These are the required positive and refusal controls, not a broad pass-count inference.

### Meaningful red, final green and retained boundaries

Directly inspected `/private/tmp/drf-os-timing-review-red-20261018-1`: seven cases, **four failures and three passes**, exit 1 with no recorded drift. Before the fixes, the valid pending-write/transport case failed and all three positive legacy-count representations incorrectly reached acquisition. The overrun, untouched and sealed controls already passed. This isolates the reported defects and preserves their failure evidence.

Directly inspected final `/private/tmp/drf-os-delivery-reviewed-20261018-1/completed.json`, `junit.xml` and selected `oddsense-workflow.json` fields:

- **1,457 total: 1,455 passed, two skipped, zero failures, zero errors; exit 0**, in 29.859 seconds. The two skips are the existing absent vendored-harness snapshot cases. Shutdown completed; identity was preserved; recorded source drift is empty.
- All seven new PR-4/PR-5 cases have passing testcase entries on the final frozen bytes. Passing entries also retain the 120-second model-idle news/market checks, cumulative actual-time/restart check, news and market interruption reservations, actual two-process same/distinct-query market cap cases and native store-deadline propagation.
- The production-path scripted E2E still advances source wall time by 120 seconds inside planning after prefetch and finishes research/QA/publication/API/export. Its evidence records `source_unchanged=true`, `publication.publishable=true`, `replay_no_new_calls=true`, `controlled_scripted=true` and `live_provider_proof=false`. The two-news/four-market caps and conservative interrupted reservations remain intact in the inspected design and controls.
- The audit retains four denied subprocess attempts, 18 denied external reads, three denied `os.kill` attempts and 26 allowed guarded children. These are reported as attempts; passing containment does not mean they were zero.

| Evidence | SHA-256 |
|---|---|
| Finding-specific red `completed.json` | `04f2280107632c2a53e0167f28e9713ebf4bb61d93a5de4149339b87f585cf3d` |
| Finding-specific red `junit.xml` | `9672b4d10d1de0ca9b742add460e05c611a982ba40aa4597829f504b77deabcf` |
| Final reviewed `completed.json` | `377cff51cea9e9507d56c9a98a12fe3baa354fbe365837af273d9aa84107e0d8` |
| Final reviewed `junit.xml` | `df5a4d8524025c454ed7d1b7cf214beb947a29d1dfdf73c7d0d39042ddccad21` |
| Final reviewed `oddsense-workflow.json` | `ffb8e1c5b7c57e556ba8bcd80eab9ee2112c9d6d25cf9adbdc8e62d06aef677f` |

This reviewer made no source/test edits, ran no source or vendor code, accessed no credentials, made no live/provider calls, created no agents and performed no Git or service operation. Only this review document was updated. Closure concerns the exact five behavioral files and controls above; the coordinator's wider delivery checks remain separate. **PR-4 and PR-5 no longer block commit of these reviewed bytes.**
