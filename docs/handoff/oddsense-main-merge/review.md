# Oddsense main merge independent review

**Reviewed at (UTC):** 2026-10-21T04:56:17.396220+00:00

**Scope:** Final frozen production reconciliation and matching focused acceptance.

**Static verdict:** No open blocking production findings. Previously reported merge defects are closed on the exact source below.

**Release verification:** Closed on the current frozen source: 1,889 passed, zero failures/errors and two existing harness skips across 44 modules. Ready for the coordinator's scoped merge commit. Git integration and delivery remain separate.

## Scope and method

The comparison bases are current main `15c8453b60bede17e3e9ecbbbee862f6cbe9e607` and incoming Oddsense `7c98895c98cc2bcaff4559b165f038975d3c0713`. Review took place in `/Users/rogerlin/.codex/worktrees/forecast-feedback/DeepResearchForecast` on `codex/merge-oddsense`. The coordinator owns conflict resolution, code/test edits, verification execution, Git integration and delivery. This reviewer performed source/diff inspection, stdlib-only AST/JSON/XML analysis and hashing. The reviewer ran no application imports or tests, installed nothing, made no Git mutations, and accessed no primary runtime uploads, credentials, providers or services. This is the only reviewer-created repository artifact.

The 12 entries in [final-freeze.json](final-freeze.json) match the reviewed worktree and the first broad mirror. The freeze JSON has SHA-256 `54b2e227998a35eb36711152f4cb29abcdfc807a687b573a30dc6b9fa787f963`. All **177** source entries in Gauss's [post-run source check](/private/tmp/drf-oddsense-merge-final-20261021-g/post-run-source-check.json) were independently rehashed against the current worktree with no mismatches. That full portable source map has SHA-256 `c621fcee4ed7a02d961fc7f8bc81dc3efd1b0df97a50516bb50a346ef87f0d13`. Focused completion source entries also match the current files. The later controlled test delta is recorded separately below; production remains frozen.

## Reviewed merge invariants and closed findings

| Boundary | Final disposition and evidence |
|---|---|
| Historical cutoff and context acquisition | Tool advertisement returns no context names for a backtest policy. Gateway dispatch refuses before cache/provider access. Engine initialization rejects retained current capture/ledger context and disables fresh context. `_context_text` returns before client or cached-snapshot reads. `_seal_context` cannot seal/bind a current capture and rejects an injected nonempty snapshot. Fresh/default, native prebound client, actual planner-input and direct no-read controls cover these boundaries. |
| Existing historical tools | `ResearchTools` retains keyword-only `backtest`, `archive_get` and `context_client`. Existing dated search/fetch and official-data/market cutoff behavior remains. `backtest_cutoff.py` is byte-identical to main. No production guard was relaxed. |
| Documented risks and hazards | Main's frame template, hazard regex/note/writer rule, probability normalization, risk extraction function and annotated prompt-template registry are AST-identical. The reference-class method skill is byte-identical to main. Scenario weights and probability ranges retain their prior exclusions; contextual quotes do not acquire forecast-anchor or settlement authority. |
| Binding through classic/world/world-seed preparation | All three generic binding-failure handlers inspect `_research_declares_news_context` and raise for declared context instead of silently degrading. `ResearchBindingConflict` propagates. Legacy official-only absence/degradation remains. The declaration helper checks visible presence, consumed fingerprints, contract manifest and persisted pipeline artifacts. |
| Official bridge loader | Main's generic `bridge_module(name)` and existing `data_api()` wrapper coexist with Oddsense's context-presence detector and optional generation fingerprints. |
| Context plus frozen history through finalization | Context is validated, detached and rendered from the sealed carrier. Main's exact bound history is verified and stripped into `audit_md`; context-aware final lint uses that stripped text. Official/context canonical rows receive metadata handling, while authored or modified rows receive no such waiver. Both history and context integrity failures remain hard failures. Stabilization retains the history detach/restore behavior and context's owned-boundary restoration. |
| Persisted visual replay | `_offline_report_agent(..., *, report_id=None)` restores validated report-local context into private JSON/digest/block/attached fields. Both primary and variant call sites pass `report_id`; the temporary assignment to a read-only property is gone. Actual reconstructed stabilization and audit preserve both companion byte sequences. Actual `backfill_one(apply=True)` reaches the controlled PDF failure after real audit, then restores the entire changed bundle and leaves the typed journal unchanged. |
| Publication and source digest | Main's feedback journal, ledger, presentation helper and SDK route are byte-identical. Registration remains at audited final save or explicit recovery, checks the reopened forecast bytes against the publication fingerprint, and does not occur in the final audit. The frozen-history companion remains exact and independently verifies its journal-prefix source digest. The focused next-report receipt retains source digest `8af86918886b864fd7f2d5026242ae00d91d8a5ad2bf014151fb95fa1c537d67`; context and history tampering withhold downloads. |
| Partial translation UI | The diff against main only adds the context component/import to `ForecastReport.vue`; main's partial-translation disclosure and retry behavior remain. EN/ZH backtest-context documentation is aligned. |
| Deployment module synchronization | Both setup and launch-time lists include `backtest_cutoff.py`, `news_signals.py`, `news_tools.py`, and `market_intelligence.py`. No required launch module is missing from setup. Setup's pre-existing extra `runtime_skill_sync.py` remains. No deployment was performed. |

## Independently inspected focused evidence

Counts below overlap with the broad matrix and must not be added to a unique release total.

| Gate | Observed result | Boundary and source check |
|---|---|---|
| `/private/tmp/drf-oddsense-merge-final-20261021-g` | **6 passed**, zero failures/errors/skips; exit 0, complete shutdown, preserved identity, no recorded source drift. | Current 177-file source map matches. Actual Engine/QA/ledger/promotion/binding/report/publication/API consumers, SDK settlement, next-report canonical history/context, repeat/reconstructed finalization, real replay transaction rollback, and actual historical planner messages are exercised with scripted external inputs. |
| `/private/tmp/drf-oddsense-merge-backtest-final-20261021-1` | **24 passed**, zero failures/errors/skips; parent and two children exit 0 with complete shutdown, preserved identity and no source drift. | Current fixture/guard/bridge hashes match. Both actual child bridge runs complete, preserving cutoff/audit/late-source and live ambient-policy assertions. |

Gauss's receipt records two denied subprocess font probes and eighteen denied external font-directory reads. They remained denied; this is not zero attempted activity. No network, credential or external-write attempts are recorded in that focused gate. The native backtest control records two actual model-input sequences, cutoff `2024-11-01`, no further scripted provider requests, and no historical output capture/binding. Its populated future evidence stays out of planning prompts.

Mencius's final parent PID is 22379; backtest/live child PIDs are 22440 and 22441. All three receipts were independently parsed. Aggregate events comprise the three storage redirects in each process and two admitted guarded-child launches, with no recorded blocked events. The backtest child resolves the real policy to `2024-11-01`, strict mode and the actual handoff audit path; native metadata records 12 dropped late search hits, 36 kept hits and four kept fetches. The live child reports no inherited backtest policy and the intended market flag `true`.

### Mencius adapter bounds

The final fixture uses the unchanged guard's named-script hash registration and delegates to the captured installed `Popen`. It captures the real runner-supplied parent environment. The child bootstrap overrides the market flag, so the fixture carries that actual synthetic value through `BACKTEST_FIXTURE_MARKETS_ENABLED` and restores it before bridge execution. **The final adapter does not transport policy through CLI arguments:** `DRF_BACKTEST_POLICY` is left untouched. A wrapper calls the original `_backtest_policy(env)`, records its actual return, and returns the same object; it does not manufacture policy, metadata, source output or audit counts.

All 13 original test-function ASTs are unchanged, preserving the original 24 parameterized cases and their cutoff/strictness/audit-path/market-arm/live-policy/late-source assertions. Parent environment equality, distinct PID, installed child guard and successful receipts add evidence. The market-flag alias proves the runner chose the intended value and the child consumer ran with that value; it does not prove that this flag survived unmodified through the guard bootstrap. Context is explicitly disabled only in these unrelated spawn/environment fixtures; separate real-context and historical-context controls cover that boundary.

### Receipt fingerprints

| Artifact | SHA-256 |
|---|---|
| Gauss `completed.json` | `4d2da793ca1aa3c6c3e22cbc4c25cd255cef4d7eda39dd7f37b2b9527043429a` |
| Gauss `junit.xml` | `e883ecfda21a7c7867a6418eb2f9e46876ab4d382b0ab9a76fbeda06ba74b84a` |
| Gauss `oddsense-workflow.json` | `b877b3ea4578c3d59b77e0897ccb9a08badc77a0ba4fa530b5d612e1eb2eb6a5` |
| Gauss `oddsense-backtest-native.json` | `1a7e5fd515618161af5be646773a45e77193f17da81b96c58463bcac70332d89` |
| Mencius `completed.json` | `c2c0a1963272eefc0b56620d249f943e3526b31889d65dda9acaad90cddfca68` |
| Mencius `junit.xml` | `3f13a0a0221486fe5a9b02224a5b27c1b5ffa4adc137d2272e063b760dad7db6` |
| Mencius `process-22440.json` | `f6a72802e46500638b4691fee43d657f87de492632c91554bc66e530dc6e2f31` |
| Mencius `process-22441.json` | `485b7ddbd24ae0a339fced4d8d6a357396771adf05e463c012b3d1b1ed32cf0e` |

## Retained red evidence and broad closure

The old `_context_text` no-read regression at `/private/tmp/drf-oddsense-merge-cutoff-red-20261021-1` contains one genuine failure: the old candidate read the injected snapshot. It has complete shutdown, preserved identity and no recorded drift. The current production early return and fresh focused native-planner proof close that finding; it is not an open production defect.

The first final 44-module gate at `/private/tmp/drf-oddsense-merge-final-20261021-1` contains **1,891 cases: 1,888 passed, one failed and two prior harness skips**, no collection errors, complete shutdown, preserved identity and no source drift. The only failure is `test_news_research::test_market_contract_reaches_real_gateway_kiq_synthesis_and_source_projection`: its `__new__` engine omitted `backtest`, which the real guard now reads. The coordinator's controlled correction adds only `engine.backtest = None` to that live-context fixture. An independent textual diff against the first broad mirror confirms this single added line; native quote, rule, gateway, synthesis and source assertions are unchanged. Current corrected fixture SHA-256 is `56f263be18adcedbf9ea8281c11b42ac20877b47308c8d2636ea0c1369c32d4c`. No production change accompanies it. This receipt remains historical; the fresh accepted matrix below closes its fixture failure.

The coordinator reports **261 frontend unit passes and a successful production build** in [frontend-verification.json](frontend-verification.json). All four frontend source hashes were independently checked and match. Raw frontend logs were not independently inspected in this review, so execution results are attributed to that coordinator record.

### Accepted final 44-module matrix

The fresh accepted gate is `/private/tmp/drf-oddsense-merge-accepted-20261021-1`, executed from `/private/tmp/drf-oddsense-merge-accepted-hgwdqiet`. [accepted-command.json](accepted-command.json) records the provisioned primary interpreter with `-I -S -B`, the unchanged guarded runner, explicit named-script registrations and all 44 test modules. No guard or production source changed for this rerun.

The independently parsed [JUnit](evidence/accepted-junit.xml) contains **1,891 unique cases: 1,889 passed, zero failures/errors, two skips**, in **104.874 seconds**. The skips are the two existing vendored-deer-flow-harness checks in `test_deerflow_bridge_sync_guard`; the vendor snapshot is absent. The matrix includes all seven `test_forecast_feedback_workflow` cases, the actual new report generation/restart consumers, the Oddsense workflow and combined replay, historical cutoff and hazard/risk coverage. These totals supersede the prior broad diagnostic and are not added to the overlapping six- and 24-case results.

The parent PID 26187 exited zero with complete shutdown, preserved identity and empty source drift. Its 33 admitted children have **31 zero exits**, **one intentional SIGTERM exit -15** (PID 26273), and **one intentional abrupt exit 23** (PID 26304). The 31 zero-exit children have completed receipts. The two deliberate interruptions retain started-only receipts with `shutdown_complete=false` and no child exit code; the parent's child table records their actual return codes. They must not be described as normal child shutdowns.

Both interrupted scripts are byte-identical to incoming `7c98895`. The market-intelligence control explicitly terminates the admitted child after observing a physical request, then verifies the reserved request and interrupted replay. The news-signals control explicitly expects exit 23, produced by `os._exit(23)` after two durable admissions, and verifies conservative spent allowance and replay. Their accepted JUnit cases, registered script identities, parent's return-code table and source assertions agree. These are expected provider crash controls, not unexplained child failures.

Aggregate process events contain 33 allowed guarded children, four denied subprocess attempts and eighteen denied external reads. The subprocess event records name `fc-list`, `system_profiler`, `uname` and one redacted `unregistered-executable`; all remained denied. Storage redirects occur in eight processes. No recorded network, credential or external-write attempt appears in these process receipts. This remains a CPython audit-hook boundary, not an OS sandbox.

All **36** copied parent/child/completion/JUnit artifacts were independently compared with the private originals and are byte-identical. All **36** entries in [accepted-source.json](accepted-source.json) match both current integration files and the accepted mirror. All **56** parent-receipt source hashes were independently rehashed against both mirror and current source with no drift. All **12** coordinator freeze entries and all **28** entries in this review's source table still match. The accepted source map itself records `source_drift=[]`. Main and integration HEAD were both still `15c8453b60bede17e3e9ecbbbee862f6cbe9e607` during the final read-only ref check; this review does not claim the merge has been committed or pushed.

| Accepted artifact | SHA-256 |
|---|---|
| [accepted-command.json](accepted-command.json) | `76db1851242e6ae7752c7b770c55ec6ad548f39ada67358da956898139180b9b` |
| [accepted-source.json](accepted-source.json) | `d88ccc8763936373e998cacf7cc26515c21720f74d17a04af45ff51e8415f9d6` |
| [accepted-completed.json](evidence/accepted-completed.json) | `90eaec841091edba2288a097c53277954f17d941a661f6f189ca080c05c408fc` |
| [accepted-junit.xml](evidence/accepted-junit.xml) | `d7833f1839911466dd004c51cf06bdd8c369fa865d2f02d61c8e5099ac9a7b78` |

### Primary checkout preservation correction

[preservation-after.json](preservation-after.json), SHA-256 `4deee55a7f633a7c6fef29d480ee99066e946a5220a3e18fff1f6a9487577ab0`, records nonempty primary-checkout drift in `backend/app/services/report_agent.py` and `ISSUES_LIST_ZCODE.md`, with `status_changed=true`. The coordinator reports concurrent external edits and confirms its own commands did not write those paths. This reviewer wrote no primary-checkout files. There is **no verified no-drift or unchanged-status claim** for that dirty checkout. Preserve those changes without resetting or reconciling them into this scoped merge. They do not alter the exact integration-source agreement established above.

## Exact reviewed hash manifest

The full 177-file tested source map is linked above. This table pins all 12 coordinator freeze entries, the controlled fixture correction, and the additional invariant/consumer surfaces explicitly reviewed here. Any later relevant production/test change requires an affected hash comparison and fresh acceptance as appropriate.

| File | SHA-256 |
|---|---|
| `backend/app/services/official_data.py` | `86a377d163580efc94499ff12ba17d314a389f3c3d14b4d323bba4d76fc92472` |
| `backend/app/services/pipeline_orchestrator.py` | `d8fb9ffeb1aae3f619de04f95393ffb1ed95b00fbbe59ec6e24d6275c56023e2` |
| `backend/app/services/report_agent.py` | `25c719d81af6633e8be64a9aa7482b84aad6ffa8888211b184cf0978b6b703dd` |
| `deerflow_bridge/research_gateway.py` | `f8e04046bad50ec7228fa0c27d4dfaa73811d503bd89d6cc9d515153928523b5` |
| `deerflow_bridge/linear_research.py` | `f14bb1fcc831c233859a02b4cb045af2203b381a557e5669383d15f840f68986` |
| `backend/scripts/backfill_report_visuals.py` | `e8850ae44a04d5461f2e638fbd7a21c9ab9b3808830747a2ef73e571fdae5e2d` |
| `backend/tests/test_oddsense_workflow.py` | `68fe72f133d4aea5822bb7d70dbe433fae12b81ba756c7b8097472fd297589f0` |
| `backend/tests/test_oddsense_feedback_merge.py` | `974a9e59f1a666d9eef6c7c09ff81e6269e026d60823f819c88dfecdfaf80aea` |
| `backend/tests/test_oddsense_merge_guards.py` | `3571b0af08c9e8e0bc72dc57d7c65490ec6d797538f49d7f0de5bbd6da9de0af` |
| `backend/tests/test_backtest_pipeline.py` | `8417ea8ae2a1ab9492da37d6b6133ac1289e35907627bd1dd726d4379498dd78` |
| `backend/tests/test_news_context_pipeline.py` | `da59415fd4c305c83541012d1e46f3fd1404b366341f81469b5130cab25b69c4` |
| `backend/tests/test_official_data_consumers.py` | `231c0ca9e506cc178fcc14cc0264e52be6adc279cfad949347621f5f9d0e9584` |
| `backend/scripts/main_offline_pytest.py` | `8c8bb8f6c0e4e5decee8f167603a4eb47711ec562e028d19f9d3d6bee1741815` |
| `backend/tests/test_news_research.py` | `56f263be18adcedbf9ea8281c11b42ac20877b47308c8d2636ea0c1369c32d4c` |
| `backend/app/services/news_market_context.py` | `b52a36170ef81c7760cb14ea46fd762d27144052c91dbc6649e0a5153ab2e136` |
| `backend/app/services/forecast_feedback.py` | `5e4f4eb48adff25bbb25bf0c7df661531b8f1584fdabda6da73c0a82bd5a3209` |
| `backend/app/services/forecast_ledger.py` | `2576a04a669586c7ebe94550d5d5ef1a8754c51bf65b42809e068e7164c0edc5` |
| `backend/app/services/forecast_track_record.py` | `6cd977828939223b239cd83ebb72c39f05c6a76714ad9ada3f9be5b73d9610b1` |
| `backend/app/api/sdk.py` | `37ab645649b8e3f97c0bfb1a79c2f90335fc7e0d4e9d455612f30034fb56cf40` |
| `deerflow_bridge/backtest_cutoff.py` | `c8d9d7550d465c9b144e18f31df97f04c12ac3fc0e7c977477b4a44db0aad7f0` |
| `deerflow_bridge/skills/reference-class-forecasting/SKILL.md` | `d05be01794f41bdbb15dbf7906ccdb6bafcf91fc3de5f3d7810cb8d66854b79a` |
| `setup.sh` | `c3bbafba17bd301c5537c2e2e7e360a8ac285d706243cb6512e5855db3dc2863` |
| `README.md` | `47285eab36ccf02aec9403bffd91cb1bd3eb6b819ea962ae3639a4623049a390` |
| `README.zh-CN.md` | `b5d0bd6dc94bf5a42f0e8916534e5ecf1e957ef04f0b72f8bfd809323566d0db` |
| `frontend/src/components/research/ForecastReport.vue` | `781407fc1e62d4cea158c25f1073d9409cbf414d0aa12a61570514e2442e7a0c` |
| `frontend/src/components/research/DossierViewer.vue` | `2c604110825f9c7974bd2ad193bed80594d3a6d8e4cf2fb2e63f9f874869041e` |
| `frontend/src/components/research/SourceContextPanel.vue` | `44be3a9bfeccae31821326b57c7e2276bcb88c7d2a1efab6cb94c46c6998613d` |
| `frontend/src/utils/sourceContext.js` | `f58d0eb37263c288e5145ab586d8d63f8692ab1446f5eeaaaeb49cba69f06563` |

## Remaining acceptance and limits

No open blocking production or acceptance finding remains in the reviewed scope. The accepted final matrix, expected interrupted children, durable copies and current source agreement have been independently inspected. The frozen integration source is ready for the coordinator's scoped merge commit. Git ancestry publication and delivery remain the coordinator's responsibility; preserve the separately observed primary-checkout edits.

The focused next report uses actual assembly/finalization/publication consumers with scripted authored sections. Full fresh `generate_report` behavior and fresh-process feedback restart are covered separately by the accepted broad workflow module and are not inferred from the six-case gate. Demo export covers copying audited report/dossier Markdown through the actual helpers, not the complete strict `export_run` graph/simulation gate. The replay test intentionally fails external PDF export and proves rollback; it does not prove native PDF rendering. All evidence is offline contract/mechanics evidence, not live provider compatibility, empirical forecast accuracy, deployment or publication proof. The unchanged CPython audit hook is not an OS sandbox.

## Updates

- 2026-10-21T04:56:17.396220+00:00: Created the final independent static review after the coordinator's production freeze; reconciled focused receipts, source maps, original fixture assertions and retained red evidence. Broad full-matrix rerun is pending after the controlled one-line fixture correction.
- 2026-10-21: Closed final acceptance after independently parsing the accepted 44-module receipt/JUnit and every child receipt, checking the two explicit provider interruption controls, reconciling all durable copies and rehashing accepted/frozen/reviewed source. Corrected preservation language to retain the observed primary-checkout drift. No open blocking finding remains; ready for the coordinator's scoped commit.
