# Oddsense and forecast feedback seam acceptance

**Status:** Complete for this worker's focused acceptance. Latest candidate G passes all six selected cases, and independent exact-byte review is closed with no remaining actionable finding. Production merge/delivery and broad regressions remain with the coordinator.

## Scope and acceptance brief

This worker owns `backend/tests/test_oddsense_workflow.py`, optional `backend/tests/test_oddsense_feedback_merge.py`, and this document. The coordinator owns production conflict resolution, the working handoff, broad regressions, Git mutations, and delivery. Preserve peer edits, primary-checkout dirt, uploads, credentials, and service state.

The existing real Engine → QA/SourceLedger → promotion and simulation binding → ReportManager finalization/publication → Flask report/download and demo export acceptance remains the baseline. Extend that scenario to prove that audited publication registers the original immutable forecast and that a subsequent actual report carries the typed journal track record alongside exact canonical Oddsense news metadata. Script only external transport, model responses, publisher fetches, and unrelated intelligence; never replace the report/ledger/publication consumers or weaken admission gates.

| Requirement | Observable check | Evidence |
|---|---|---|
| Native Oddsense context survives all consumers | Existing full workflow checks quote/rule metadata, QA, sealed sources, promotion, binding, final report, API, download, export, replay, and tamper denial. | `oddsense-workflow.json` plus guarded completion/JUnit. |
| Original forecast is registered at publication | Real audited save produces the typed original snapshot; draft does not register. | Stored original digest/forecast and publication verdict in workflow receipt. |
| Context and typed history coexist | Resolve the original through a production consumer, construct/finalize/save a later report, and validate both canonical blocks, companion JSON, audited download/export. | Typed history, exact block checks, API/export hashes in receipt. |
| Gates remain fail closed | News capture and typed history tamper reject publication/download after successful positive controls. | Denial statuses and unchanged original snapshots. |
| Tested bytes and guard boundary are known | Fresh private source mirror, unchanged guarded runner, isolated provisioned interpreter, completion/source drift/identity/event inspection. | Source manifest, before/after hashes, completed receipt, JUnit, process exit. |

## Freeze needs

Before any application import, resolve conflict markers in `backend/app/services/{official_data,pipeline_orchestrator,report_agent}.py` and `deerflow_bridge/research_gateway.py`. Freeze all `backend/app/**/*.py`, `deerflow_bridge/**/*.py`, `backend/scripts/{main_offline_pytest,export_demo_site_data}.py`, the selected tests, and their shared fixtures for one mirror capture. The source mirror manifest will record the entire copied source, and the workflow receipt will enumerate the directly exercised seams. Coordinator edits after mirror capture require an affected-path hash comparison and another fresh mirror if tested bytes changed.

Invoke only `/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir <fresh-private-tmp-dir> <selected-tests>` from the frozen mirror. No dependencies, live providers/models, runtime recovery, or service operations are authorized. The CPython audit hook is not an OS sandbox.

## Progress and decisions

- 2026-10-21: Read the merge plan/handoff, source Oddsense final verification, current main feedback handoff, guarded runner and required skills. Verified branch `codex/merge-oddsense` and initial HEAD `15c8453b60bede17e3e9ecbbbee862f6cbe9e607` with unresolved production conflicts. Historical 1455-case Oddsense and 812-case feedback evidence is context only.
- 2026-10-21: Began static tracing of the publication and typed history consumers. No Git mutation, production edit, app import, or test run performed.
- 2026-10-21: Updated the owned workflow test to retain draft status until final audit, isolate its typed journal, enable the real SDK route, verify original registration and immutable SDK adjudication, and publish a later actual assembled report with canonical context and typed history. Positive download/export checks precede history-companion tamper denial. No production method or gate is replaced. Test execution is still pending.
- 2026-10-21: First fresh mirror `/private/tmp/drf-oddsense-merge-acceptance-20261021-a-0o291vw3` passed static parsing of 484 selected Python files with no capture drift. Guarded run `/private/tmp/drf-oddsense-merge-acceptance-20261021-a` produced 3 passes/1 failure: the added test compared a stale local forecast object after a second real audit refreshed diagnostic quality fields. Both reports, publication, SDK settlement, exact canonical blocks and repeat stabilization had succeeded. Corrected the test to reread current forecast bytes and separately assert unchanged frozen history. The retained red receipt is fixture evidence, not a production defect.
- 2026-10-21: Fresh candidate mirror `/private/tmp/drf-oddsense-merge-acceptance-20261021-b-1vps9qw8`, guarded evidence `/private/tmp/drf-oddsense-merge-acceptance-20261021-b`: all four Oddsense cases pass, including added SDK original/settlement/next-report coexistence. Read-only control preparation found `_offline_report_agent` assigning the read-only `ReportAgent.news_market_context` property; reported the production reconstruction defect to the coordinator immediately. New owned `test_oddsense_feedback_merge.py` exercises real cached/uncached tool denial, Engine backtest context behavior, and report-local reconstruction with/without context.
- 2026-10-21: Coordinator repaired reconstruction. Control run `.../drf-oddsense-merge-controls-20261021-c` passed both reconstruction cases and all three tool-denial cases; its Engine test's injected rejecting client exposed `_seal_context` calling a client despite the disabled backtest branch. Replaced that fixture with a native client and a separate default-client positive control to distinguish actual contract failure from fixture setup.
- 2026-10-21: Combined mirror `/private/tmp/drf-oddsense-merge-controls-20261021-d-qw15o98x`, evidence `/private/tmp/drf-oddsense-merge-controls-20261021-d`: ten passed, one genuine production failure. The full workflow now also reconstructs through `backfill_report_visuals._offline_report_agent` and invokes the real stabilizer/final audit with both canonical blocks; this passes. Native prebound-client control fails because `_seal_context` writes a present-day sealed capture under a 2024 policy, changing `disabled_backtest` to `sealed`. Reported immediately; coordinator owns repair. The default fresh-backtest control and stored-current-capture refusal pass.
- 2026-10-21: Dispatched one required concrete read-only review of the two owned test files and their actual consumer claims. It cannot edit source, run app imports, mutate Git, or spawn further agents.
- 2026-10-21: Independent reviewer confirmed the native prebound-client case as a real forbidden persistence/binding regression, with no claim of provider acquisition. Coordinator added a backtest `_seal_context` guard. Removed overlapping direct-tool/schema and standalone reconstruction cases after the parent added its own five-case gate. Retained only distinct default/stored and native prebound/invalid-snapshot Engine controls.
- 2026-10-21: Addressed the review's immutable-byte gaps: assert no SDK resolution mirror for invalid outcomes; successful append preserves the original journal prefix; duplicate/conflicting settlement preserves exact mirror bytes/timestamp/evidence; freeze history/context bytes immediately after first publication and compare after both finalization/reconstruction paths; compare export/download/source Markdown bytes directly. Scope the existing export helper accurately instead of claiming strict `export_run` acceptance.
- 2026-10-21: Candidate E adds actual `backfill_one(apply=True)` replay. Real visualizer/repair/final audit reach a scripted external PDF write failure. The actual transaction restores every prior report artifact byte and removes new chart/manifest artifacts while preserving typed journal bytes. The restored report remains publishable. Only PNG renderer selection and the failing external PDF write are controlled; no report repair, final audit, publication admission, visualizer builder, backup, or rollback implementation is replaced.
- 2026-10-21: Fresh mirror `/private/tmp/drf-oddsense-merge-recovery-20261021-e-d4vkcy84`, evidence `/private/tmp/drf-oddsense-merge-recovery-20261021-e`: six passed, zero failures/errors/skips in 4.72 seconds; workflow reaches `complete`. Guard completes normal shutdown, preserves identity and reports no source drift. Compared all 148 selected production/consumer/test/fixture source files against the active worktree: no drift. Submitted final frozen tests to the same independent reviewer for a bounded recheck.
- 2026-10-21: Candidate F addressed both final review gaps: full initial SDK source/evidence/digest/timestamp retention, and delegated real replay call observations plus required pre-failure artifact mutations. All six cases passed on F. Those receipts remain historical after the coordinator's later prompt-reader source repair.
- 2026-10-21: Candidate G adds actual planning messages with populated future native evidence, on the coordinator's latest prompt-reader/seal guards. All six cases pass in 4.41 seconds. Independent review confirms the exact G test hashes and closes both earlier findings; no remaining actionable test finding. The reviewer performed no edits/imports/tests/Git mutations and is now closed.
- 2026-10-21: Final handoff to coordinator: focused acceptance is complete, current production/test bytes match candidate G, and post-run source hashes are retained in `/private/tmp/drf-oddsense-merge-final-20261021-g/post-run-source-check.json`. Run the parent's broad final matrix with both owned modules; keep this source frozen unless a blocking defect requires a new mirror/retest. No Git mutation or production edit was made by this worker.

## Latest candidate G result and exact evidence

The latest executed command used fresh mirror `/private/tmp/drf-oddsense-merge-final-20261021-g-ttitgwi9`:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-oddsense-merge-final-20261021-g -q backend/tests/test_oddsense_workflow.py backend/tests/test_oddsense_feedback_merge.py
```

**Result:** Six passed, zero failures/errors/skips, 4.41 seconds, completed normally with exit zero. This includes the original four-case Oddsense acceptance and two distinct Engine controls. The latest production candidate includes both the coordinator's seal guard and subsequent `_context_text` reader guard. A populated native-shaped future NewsAPI capture with two items is injected from a sibling root, then the real `Engine.phase_plan` and `ModelGateway` record two actual model input sequences. No future item title, URL or context block reaches either input. The historical cutoff remains `2024-11-01`, the native fixture performs no additional acquisition, and no context capture/binding enters the historical output. The explicitly nonempty in-memory snapshot is also refused at sealing.

Review-driven SDK checks retain the full submitted source/evidence, original publication digest and matching resolution timestamp in both typed journal and report mirror. The transactional replay observes calls delegated to the real stabilizer and final audit before the scripted PDF failure. It observes nine changed artifact paths (including chart HTML, citations, audit, forecast, Markdown, metadata and manifest) before proving byte-exact bundle rollback, journal preservation and continuing publication admission. Both source context and frozen history companions survive repeated and reconstructed finalization byte for byte.

| Latest G artifact | SHA-256 |
|---|---|
| `/private/tmp/drf-oddsense-merge-final-20261021-g/completed.json` | `4d2da793ca1aa3c6c3e22cbc4c25cd255cef4d7eda39dd7f37b2b9527043429a` |
| `/private/tmp/drf-oddsense-merge-final-20261021-g/junit.xml` | `e883ecfda21a7c7867a6418eb2f9e46876ab4d382b0ab9a76fbeda06ba74b84a` |
| `/private/tmp/drf-oddsense-merge-final-20261021-g/oddsense-workflow.json` | `b877b3ea4578c3d59b77e0897ccb9a08badc77a0ba4fa530b5d612e1eb2eb6a5` |
| `/private/tmp/drf-oddsense-merge-final-20261021-g/oddsense-backtest-native.json` | `1a7e5fd515618161af5be646773a45e77193f17da81b96c58463bcac70332d89` |
| `/private/tmp/drf-oddsense-merge-final-20261021-g-ttitgwi9/oddsense-source-manifest.json` | `73d3e42b14a82626af73bb61985d33e655bc6db08d0467f3ddad3689388fd1fd` |
| `/private/tmp/drf-oddsense-merge-final-20261021-g/post-run-source-check.json` | `c621fcee4ed7a02d961fc7f8bc81dc3efd1b0df97a50516bb50a346ef87f0d13` |

Latest G's 23 directly exercised boundary hashes match the historical D table below except `linear_research.py` and the workflow test. The additional selected control/conftest hashes are recorded in the mirror/completion manifest. The exact current deltas are:

```text
deerflow_bridge/linear_research.py f14bb1fcc831c233859a02b4cb045af2203b381a557e5669383d15f840f68986
backend/tests/test_oddsense_workflow.py 68fe72f133d4aea5822bb7d70dbe433fae12b81ba756c7b8097472fd297589f0
backend/tests/test_oddsense_feedback_merge.py 974a9e59f1a666d9eef6c7c09ff81e6269e026d60823f819c88dfecdfaf80aea
backend/tests/conftest.py dc42f8f27bb68e012654ba15b96578b8bae7c8605861b6e181c6e02c93d4df0d
```

The latest completion records the same three storage redirects, two denied subprocess font probes and eighteen denied font-directory reads as E. No recorded network, credential or external-write attempts, no source drift, preserved identity, and normal shutdown. A post-run worktree comparison checks all 148 relevant production/consumer/test/fixture files with no drift. Source-scoped `git diff --check` passes. Controlled inputs, helper-only export, native PDF, full generation, restart, broad regression and delivery limitations below continue to apply.

At `2026-10-21T04:47:14.503615+00:00`, the final source-freeze comparison additionally covered all mirrored backend scripts, for 177 Python production/consumer/test/fixture files total; every current hash matches the tested mirror. The post-run source-check receipt above contains that complete portable path-to-hash map. This is the worker's final source freeze; subsequent documentation updates do not change tested code.

## Historical candidate E result and exact evidence

The unchanged guarded command, executed from `/private/tmp/drf-oddsense-merge-recovery-20261021-e-d4vkcy84`, was:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-oddsense-merge-recovery-20261021-e -q backend/tests/test_oddsense_workflow.py backend/tests/test_oddsense_feedback_merge.py
```

All four original Oddsense cases and both distinct native Engine cutoff cases pass. The full workflow proves original forecast registration at audited publication, immutable SDK adjudication (`Brier=0.32`), next-report typed history alongside canonical Oddsense context, two exact-block replay paths, positive Flask/download/copied-Markdown consumers, report-local/history tamper denial, and actual visual replay transaction rollback. Its history contains one resolved scenario, ten outstanding unanchored binaries, and zero market/official-data anchored binaries; context quotes do not become scored forecast anchors.

| Final E artifact | SHA-256 |
|---|---|
| `/private/tmp/drf-oddsense-merge-recovery-20261021-e/completed.json` | `0f7796afc823b549f44f4c9ff4bcfb35854b5d165ed20c2d28c582c1ef45b6f4` |
| `/private/tmp/drf-oddsense-merge-recovery-20261021-e/junit.xml` | `d3453d8db6ad9c6ef1433ca19a0171b61e21a301203b26e2f888bcce5553b67f` |
| `/private/tmp/drf-oddsense-merge-recovery-20261021-e/oddsense-workflow.json` | `2ccad57b08032a6f7fa82840e2cdbd93bd30cdcb2b6229bdfa51077d430fda5d` |
| `/private/tmp/drf-oddsense-merge-recovery-20261021-e-d4vkcy84/oddsense-source-manifest.json` | `1bf05e7df2d8988420f66c4c8ff4c6630dc6683c05bdb00cc08f9d97d5bbf731` |

Final E's 23 directly exercised boundary hashes match the historical D table below except `linear_research.py` and the workflow test. Final E additionally records the selected control test and shared conftest in its mirror/completion manifest. Exact final values for those deltas are:

```text
deerflow_bridge/linear_research.py 8a0be15b869a175bf885ff1c96a8e77809bdb4c06426edcd0a3b9914750cf739
backend/tests/test_oddsense_workflow.py a43dafdd2b1468dd9e7e3bd4008c81ae4eed382897667d4e91246f1978ca1327
backend/tests/test_oddsense_feedback_merge.py fe4cf0fdb9ff51996f98b0f2eecf606e0c30e8b11e586691c1320c2080710bae
backend/tests/conftest.py dc42f8f27bb68e012654ba15b96578b8bae7c8605861b6e181c6e02c93d4df0d
```

The final completion receipt reports three storage redirects, two denied subprocess probes (`fc-list`, `system_profiler`), eighteen denied font-directory reads, exit zero, normal shutdown, preserved identity, and empty source drift. No network, credential, or external-write attempts are recorded. The process remains a CPython audit boundary, not an OS sandbox. The replay test intentionally fails the external PDF write; successful native PDF rendering is not claimed. Demo export evidence exercises `export_report`/`export_dossier` copying already audited content, not the full strict `export_run(require_publishable=True)` graph/simulation export gate. Full new report generation, process restart and broad regressions remain with the parent. No Git mutation, production edit, dependency install, primary runtime access, credential/service operation, or live provider/model call was performed by this worker.

## Historical results and limits

The four original Oddsense cases pass on candidate B. The current combined candidate D passes ten of eleven cases; acceptance remains incomplete until the prebound-client backtest issue is repaired and the affected cases rerun on fresh frozen bytes. Parent owns broad regressions and independent production review. Controlled fixtures prove only the exercised workflow contracts; they do not prove live source compatibility, forecast calibration, provider performance, deployment, or Git delivery. The next report is assembled through actual ReportManager consumers from scripted authored sections; a new full `generate_report` invocation and fresh-process restart remain delegated to the parent's regression matrix. The red cutoff case demonstrates invalid present-day capture sealing at a supported injected-client boundary; it does not demonstrate a live acquisition or published forecast contaminated through the default factory.

Candidate D's final workflow receipt reaches `stage=complete` with unchanged source hashes. Its overall completion exits 1 solely for the explicit prebound-client regression. Normal shutdown completes, identity is preserved, and source drift is empty. The blocked events are exactly two native font-discovery subprocess attempts (`fc-list`, `system_profiler`) and eighteen external font-directory reads caused by importing the actual replay/visualization consumer. All remain denied. There are no recorded network, credential, or external-write attempts; this is scoped audit-hook evidence, not a native OS sandbox claim.

| Candidate D artifact | SHA-256 |
|---|---|
| `/private/tmp/drf-oddsense-merge-controls-20261021-d/completed.json` | `f7bfa1f9e135c06f48133bf10b18d22fd6b379a4cfea206194866d838e1a0acd` |
| `/private/tmp/drf-oddsense-merge-controls-20261021-d/junit.xml` | `c9a1fb8fa3910d789ac7eb5f26ea51942a5a4c4f6a5e37d656f4dc1d102265e3` |
| `/private/tmp/drf-oddsense-merge-controls-20261021-d/oddsense-workflow.json` | `15943cf1abe838c73ffc187f477b997fdf17b09bd654023b4c2863353071d174` |
| `/private/tmp/drf-oddsense-merge-controls-20261021-d-qw15o98x/oddsense-source-manifest.json` | `4f8723b9795b923b8649583e3067426b1196e04a7c5fab8136f4a9093c9e3b6d` |

The workflow receipt enumerates all 23 directly exercised boundary hashes, and the full mirror manifest enumerates 2438 copied files. A live-worktree comparison immediately after D found no selected Python drift. The unchanged guarded runner is `8c8bb8f6c0e4e5decee8f167603a4eb47711ec562e028d19f9d3d6bee1741815`; candidate D's `linear_research.py` is `fe9ac58da80dfb947085ed72c00c1017ffea6ba8157d6e25da581e5986b4aacb`. These are historical candidate hashes, not final delivery claims.

### Candidate D directly tested SHA-256 values

```text
deerflow_bridge/news_signals.py 58390a6286e4366cf478c9fdb21536a2fff87821f70c1c6a8045fd399e4c5b70
deerflow_bridge/news_tools.py a0ee232160113bd88c7418637cb7bd50db40951edcad5c2e4e38e78af6af592c
deerflow_bridge/market_intelligence.py 1017766daf27b35533f03d3089b00713a5e72130c1945e00d251c0be50f7b67f
deerflow_bridge/research_gateway.py f8e04046bad50ec7228fa0c27d4dfaa73811d503bd89d6cc9d515153928523b5
deerflow_bridge/linear_research.py fe9ac58da80dfb947085ed72c00c1017ffea6ba8157d6e25da581e5986b4aacb
deerflow_bridge/deerflow_research.py 2abe7e1f0a5a97a626737fef67177c226b17b464ab517701861d05f7f5203755
deerflow_bridge/research_budget.py bf698af519aefd686994fddc7224e47775157597de3a77b691e267cd8c7ba636
backend/app/services/pipeline_orchestrator.py d8fb9ffeb1aae3f619de04f95393ffb1ed95b00fbbe59ec6e24d6275c56023e2
backend/app/services/news_market_context.py b52a36170ef81c7760cb14ea46fd762d27144052c91dbc6649e0a5153ab2e136
backend/app/services/official_data.py 86a377d163580efc94499ff12ba17d314a389f3c3d14b4d323bba4d76fc92472
backend/app/services/report_agent.py 25c719d81af6633e8be64a9aa7482b84aad6ffa8888211b184cf0978b6b703dd
backend/app/services/forecast_extractor.py 4171cd38a7ed11975c71f57a9eedc555c2aade1bf44f853ee80989b1926d013c
backend/app/services/report_lint.py 67e91a0805f95c7b073cd21d6e2d2979fff6b47bebd474715b9d13cf04d59899
backend/app/api/research.py 6e0acc4aaa712093f7d9bd3f66107f6830dfa25eee26878f7137683a1b278bb0
backend/app/api/report.py 964d8b2549a24440f36e57f4fc6915f34d3d0869f10f462c896fe433be60b7ac
backend/scripts/export_demo_site_data.py 1d8d334cbf72a96940399f041472a7a094b3f2be426442e783a905a5cd47602b
backend/scripts/main_offline_pytest.py 8c8bb8f6c0e4e5decee8f167603a4eb47711ec562e028d19f9d3d6bee1741815
backend/tests/test_oddsense_workflow.py 2433d255fb1d2d5f0e39ed14fbed944fe080f377e547dde7326c866905b413ff
backend/app/services/forecast_feedback.py 5e4f4eb48adff25bbb25bf0c7df661531b8f1584fdabda6da73c0a82bd5a3209
backend/app/services/forecast_ledger.py 2576a04a669586c7ebe94550d5d5ef1a8754c51bf65b42809e068e7164c0edc5
backend/app/services/forecast_track_record.py 6cd977828939223b239cd83ebb72c39f05c6a76714ad9ada3f9be5b73d9610b1
backend/app/api/sdk.py 37ab645649b8e3f97c0bfb1a79c2f90335fc7e0d4e9d455612f30034fb56cf40
backend/scripts/backfill_report_visuals.py e8850ae44a04d5461f2e638fbd7a21c9ab9b3808830747a2ef73e571fdae5e2d
backend/tests/test_oddsense_feedback_merge.py a91450141730c5e993e5090b18eb3497cfd83f2b5dc40077ba8a0ff35ac6e08a
```
