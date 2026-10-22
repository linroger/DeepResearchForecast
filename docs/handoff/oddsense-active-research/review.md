# Oddsense active-source post-install review

> **Final status — Complete, 2026-10-22 08:38 UTC:** The corrected exact-fixture registered gate passes **796 cases with zero failures/errors/skips**. All 39 frozen active/mirror hashes and all 26 child records are reconciled. No bounded implementation or acceptance blocker remains. The earlier **792 passed / four failed** result is retained below and in its original evidence directory. Deployment synchronization, idle checks, backend restart and live readiness remain separate parent-owned actions.

> **Prior follow-up, 2026-10-22 08:30 UTC:** The readiness helper and surgical preflight field have been independently reviewed with no production-code blocker found. The current 39-file active freeze matches the tested mirror. The current-source readiness and renderer/report/E2E cases pass, closing the earlier renderer evidence gap. The expanded ten-module run is **792 passed / four failed**, all four failures caused by existing gateway performance fixtures being denied guarded subprocess admission. It is not an all-green matrix. This follow-up supersedes the earlier current-status statements while retaining their history below.

**Reviewed at:** 2026-10-22 08:15 UTC.
**Scope:** Independent, bounded, read-only review of the actual installed implementation, private candidate, seven peer baselines, historical cleanup, and the parent's guarded acceptance evidence.
**Reviewer ownership:** Only this document, `/private/tmp/drf-oddsense-active-postreview.md`. No source/Git/runtime mutations, application imports, test execution, provider calls, environment-file reads, or credential inspection.

## Verdict

**No source-reconciliation defect found. All seven shared files preserve the captured peer edits.** The actual active allowlist has **37 paths**, not 39: **21 runtime/UI paths, 10 tests, and six support files**. Initially all 37 were byte-identical to both the private merged candidate and the parent's tested mirror.

There is **one current acceptance gap**: while review was underway, the parent forward-ported the snippet renderer into `backend/app/services/news_market_context.py`. This is exactly the previously recommended small main fix and presents no new API, binding or world dependency in the inspected diff. However, the available 250-test receipt still pins the older renderer. Consequently, this report accepts the preservation/reconciliation and the original tested combination, but does **not** claim fresh runtime acceptance of every current installed byte.

HEAD, branch and indexed content remain the original identities. The raw index checksum changed during this review despite its staged content remaining equal to HEAD; that preservation discrepancy is detailed below. A fast-forward, commit or index rewrite is unnecessary for this activation and was not performed by this reviewer.

## Evidence roots and exact scope

- Primary: `/Users/rogerlin/Downloads/DeepResearchForecast`.
- Candidate: [private candidate](/private/tmp/drf-oddsense-active-candidate-gpt23yh1/manifest.json), with regular `before/`, `base/`, `theirs/` and `merged/` trees.
- Installation authority: [install.json](/Users/rogerlin/Downloads/DeepResearchForecast/docs/handoff/oddsense-active-research/install.json), specifically `active_allowlist` and `installed_sha256`. Its `files` array retains all 97 original delta entries; that array's length is not the current installation count.
- Current extra change: [forward-port.json](/Users/rogerlin/Downloads/DeepResearchForecast/docs/handoff/oddsense-active-research/forward-port.json).
- Tested mirror/evidence root: `/private/tmp/drf-oddsense-active-verify-mopcvk3v/`.
- Test evidence: [completed.json](/private/tmp/drf-oddsense-active-verify-mopcvk3v/evidence/completed.json), [JUnit](/private/tmp/drf-oddsense-active-verify-mopcvk3v/evidence/junit.xml), [workflow receipt](/private/tmp/drf-oddsense-active-verify-mopcvk3v/evidence/oddsense-workflow.json), and [test log](/private/tmp/drf-oddsense-active-verify-mopcvk3v/pytest.log).

The 21 runtime paths are the same bounded allowlist in the preceding reconciliation review: seven backend API/config/service paths, nine bridge/config/method-skill paths, four frontend source paths, and `setup.sh`. The ten tests comprise eight backend and two frontend files. The six support files are `.env.example`, the English and Chinese READMEs, `docs/third-party/oddsense.md`, `feature_list.json`, and `scripts/oddsense_live_probe.py`. The template was fingerprinted as support; no actual `.env` file was read. The probe script was not run.

At initial fingerprinting, all 37 matched the candidate, tested mirror and recorded installed hashes. After the recorded forward port, **36/37 still match**, including **20/21 runtime paths** and **all ten tests/six support files**; the renderer is the only identified delta. Independently checking the union of completion/workflow source maps against active source covered 27 files and found only that same renderer delta.

## Seven peer files: mechanical and code-level reconciliation

I independently recomputed `git merge-file -p --diff3` using the saved **regular files**, without writing merge output or Git objects. For each shared path, the saved `base/` and `theirs/` blob IDs match Git's `495000e:path` and `7c98895:path`; the `before/` SHA-256 matches the corresponding original SHA in the candidate/install manifest.

Six recomputed merges exit zero and reproduce the installed bytes exactly. The orchestrator exits one with exactly this conflict: ours deletes the old history-registration row, base contains that row, and theirs contains history plus news-context rows. Replacing that one conflict with only the news-context row reproduces the installed orchestrator SHA-256 exactly. There are no additional unreviewed differences hidden in its resolution.

| Shared path | Preservation and inspected combination |
|---|---|
| `backend/app/api/report.py` | Exact clean three-way result. Peer translation worker changes remain; metadata loading and both manual ReportAgent entrypoints forward the new context argument. |
| `backend/app/api/research.py` | Exact clean three-way result. Translation changes remain; dossier returns the sealed carrier and rejects invalid context with 409. |
| `backend/app/config.py` | Exact clean three-way result. Prior peer configuration remains, with bounded context switches/limits added. No credential value was inspected. |
| `backend/app/services/pipeline_orchestrator.py` | Exact approved single-conflict resolution. `_RESEARCH_CONTRACT_FILES` retains the peer's history deletion and adds context. Artifact registration contains the new news row without restoring history. Deployment names, parent question digest, lane limits, immutable promotion/reuse checks, classic preparation binding and report/seed context forwarding coexist with peer heartbeat/recovery/concurrency/history-removal edits. |
| `backend/app/services/report_agent.py` | Exact clean three-way result. Peer translation/visual/report changes remain. Constructor detaches context before client construction, writer background receives its renderer output, report-local capture is create-only, canonical metadata restoration happens before citation finalization, and publication compares the stored generation with the final audit. |
| `deerflow_bridge/deerflow_research.py` | Exact clean three-way result. Peer CLOB history-acquisition removal remains. Legacy trusted registration, allowlist, prefetch, citation/seal/archive changes are present. |
| `frontend/src/components/research/ForecastReport.vue` | Exact clean three-way result. All three peer 1200px width changes remain; only context panel placement and async component import/definition are added relative to before. |

All seven installed file permission modes match their saved before files. This proves retention of the captured text/modes; it does not assert runtime behavior of every unrelated peer feature.

### Exact installed shared-file hashes

| Path | SHA-256 |
|---|---|
| `backend/app/api/report.py` | `e19198d0aa483e50c6707e0feb12288b5c8687e87e6276e6478b4246e397ff0c` |
| `backend/app/api/research.py` | `3ea56c403371bd12d7a57b91a6890113062ca1de5957c7212368ae348334c49b` |
| `backend/app/config.py` | `3cc536afc42bbc67205bda780e17d65e7b829dd62d11409815badb2a24977b9a` |
| `backend/app/services/pipeline_orchestrator.py` | `123233a6bc1b053858a2b497c80ced8166b5565a59faa211ee8f89a22aa4b210` |
| `backend/app/services/report_agent.py` | `0bd18338dfe0a45aa2fd8b5ed205d31bb88307f68c44c4e228ebb6c2b9a5724d` |
| `deerflow_bridge/deerflow_research.py` | `9ec11300abdc184b34443c6c4556c9321bc4f7e8cc5f10d03030ac336092447b` |
| `frontend/src/components/research/ForecastReport.vue` | `e8c41bd38786928e6cd0f7ec8cf48c7512f39e8c72b2d7a061263989adb1d672` |

The inspected API and ReportAgent signatures agree on `news_market_context`; no main-only `report_policy` argument, backtest owner loader or world-v1 interface was substituted. The source/config registration and `setup.sh` module list retain the three provider/context modules. Source reconciliation is distinct from deployment of those files into ignored `deer-flow/`.

## Acceptance evidence independently inspected

The parent's JUnit contains **250 cases, zero failures/errors/skips**, across exactly seven modules: news signals, market intelligence, news research, context pipeline, context reports, report metadata, and Oddsense workflow. The log reports 250 passed in 12.31 seconds. This does not include the older `test_research_engine_v3.py` module or either frontend test file, although those installed files match the mirror.

The parent completion receipt records `exit_code=0`, `shutdown_complete=true`, `identity_preserved=true` and `source_drift=[]`. Its guarded runner hash is `53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa` and matches active source. I inspected all 22 child receipts: **20 completed normally with exit 0**; one remains started-only after deliberate abrupt exit 23, and one remains started-only after deliberate termination -15. The corresponding provider fixture source explicitly expects these interruptions. These two children must not be described as normal shutdowns, but they are accounted-for crash/replay controls rather than unexplained failed tests. The receipt boundary is CPython audit hooks, not an OS sandbox.

The workflow receipt has `controlled_scripted=true`, `live_provider_proof=false`, `stage=complete`, successful research QA and publication, and unchanged recorded source during its run. Its tool trace includes initial news prefetch plus **K1 and K2 calls to both news_search and market_compare**. It records the selected publisher URLs being fetched, evidence identity/citation promotion, sealed capture and consumed generation, real report final audit, research/report API HTTP 200, Markdown download/export, no-new-call replay, and report/dossier tamper rejection at HTTP 409. This is a producer-to-consumer contract result, not merely schema advertisement.

The workflow source map contains 18 entries; completion contains additional guard/consumer entries. Their union's current mismatch is solely the post-run renderer change described below. The original 37-file candidate/mirror match independently ties the installation to the tested source at that earlier revision.

No fresh browser interaction, frontend build, native PDF rendering, live provider compatibility, paid-model behavior or running backend adoption is established by the inspected 250-test evidence. The parent reports private key configuration and an idle-safe pending restart; neither was independently inspected because environment/runtime access is outside this review.

## Current renderer delta and narrow remaining acceptance

**[P2, evidence closure] Re-establish acceptance after the renderer forward port.**

The tested/candidate renderer hash is:

`b52a36170ef81c7760cb14ea46fd762d27144052c91dbc6649e0a5153ab2e136`

The current installed renderer hash is:

`5465d580213e473baad5933139eee8b4dc408c3e05034f85d00d37baea9b7dd9`

The active blob ID is `5ebbbd0b27207141f429b685722366e2fe713df4`, identical to this file on inspected main `da1d3c4`. The diff from the private candidate is exactly the small 14-addition/one-deletion renderer fix: escaped/length-bounded snippet text, explicit truncation disclosure and omitted-item count. No constructor, API, binding or world interface changes are included. This closes the earlier static omission in the original implementation.

The source change is small, but it changes the canonical report context block and writer input. The existing 250-test receipt pins the old hash and cannot be relabeled as proof for the new one. Parent should freeze the actual current source and run the affected report metadata/context cases and scripted engine-to-publication/API/export/replay/tamper selector under the unchanged guard, plus a direct snippet/omission/writer-input assertion. Capture source hashes and completed/JUnit evidence for this exact new renderer. A current-source repeat of the same seven-module matrix is also a bounded way to close this. Refresh final installed-source metadata or explicitly use the old installed map plus `forward-port.json`; do not silently treat the original `installed_sha256` value as the latest renderer hash.

The two frontend selectors and an existing frontend production build remain separate parent-owned acceptance items if not already captured elsewhere. This reviewer did not run them.

## Historical cleanup and other peer work

The manifest now records **60 historical paths restored or removed**. I checked all of that cleanup:

- Three pre-existing files — root `agent-progress.txt`, original Oddsense `PLANS.md`, and original `issues.md` — match their saved original hashes.
- All 56 previously absent historical additions are absent again, including old receipts and the source-mirror helper. Only existence/type was checked for removed credential-check records; their contents were never read.
- The original tracked study handoff's body remains exact. Its only diff from before is a two-line activation pointer prepended at the top, pointing to the current activation handoff. It does not replace the historical study body with old delivery evidence.

Parent cleanup and the renderer forward port occurred while this review was reading; the initial status snapshot still showed the wider historical installation. The later snapshot shows the stated narrowing. These are observed parent changes, not reviewer mutations, so I do not claim status was unchanged throughout the review.

Against the supplied preservation map I fingerprinted 49 unowned peer files outside the shared seven. **47 still match; only `ISSUES_LIST_ZCODE.md` and `backend/tests/test_bridge_prediction_markets.py` differ**, exactly the concurrent drift named by the parent. They were not restored, staged or edited. Unrelated Vue/world/translation source and peer untracked dependencies covered by that map remain accounted for. This is not a recursive audit of every ignored runtime or untracked directory.

The later private `before/` snapshots govern the seven source merges; earlier preservation-map hashes can predate concurrent peer edits. Replacing their before snapshots with an older global baseline would discard such edits and is not warranted.

## Git state, ownership and stopping condition

Primary HEAD remains `495000ea98d6bcd20daa7eff1398ed5ad2663310`, branch `claude-reflexive-world-state-model`; inspected main remains `da1d3c4dbb581f15aaba43da776608708c5cd356`. Staged diff is empty; there are no unmerged entries or non-`H` index flags. No fast-forward is proposed.

**[P3, preservation record] Raw index identity changed during review.** Its opening SHA-256 was `3f0aa3b4fbc54b96da378154fe0d8d062fee04d1d78dc93291ab919c27c667da`, matching the earlier review. The closing SHA-256 is `7fa33b92d33d22324c07eb99785ef5a38c54458757084b29e4479b3f8f6f62b0`, confirmed twice. The reviewer used `GIT_OPTIONAL_LOCKS=0` for Git reads and did not write the index. I cannot attribute the other writer or prove the internal cause from this scope. I independently normalized HEAD's recursive tree listing into stage-0 index format and compared its hash with `git ls-files --stage`: both are `bc44a716aa37b75ac2b5c7c334c5de0b306b4f413a029a421424dec15b2f22c6`. Thus the indexed paths, modes and blob IDs still match HEAD exactly. This is compatible with a metadata refresh, but it is not proof of byte-preserved index state. Record the discrepancy; do not restore an old index merely to recover an old checksum.

The installed combination has no identified source-merging blocker. Current acceptance is explicitly limited by the new renderer hash; deployed-backend adoption remains parent-owned and pending. Continue only with the narrow fresh affected checks and the already-authorized safe activation procedure. Preserve the concurrent unrelated drift.

Closing read-only check at 2026-10-22 08:17 UTC: all 37 current allowlist hashes were recaptured; only the already-recorded renderer differs from the original candidate/tested source. The seven shared hashes above are unchanged. Status entries match the later narrowed snapshot, HEAD/branch/main are unchanged, indexed content equals HEAD, and the raw-index discrepancy above is retained honestly. No newer acceptance receipt for the renderer was present in the inspected verification location. The reviewer wrote only this Markdown document.

## 2026-10-22 08:30 UTC follow-up: readiness helper and fresh active-source evidence

### Narrow source verdict

No blocking source defect was found in `research_tool_status()` or its preflight integration. The inspected separate worktree is `/Users/rogerlin/.codex/worktrees/forecast-feedback/DeepResearchForecast`, on `codex/oddsense-active-research` based at `da1d3c4`. Its production diff contains only the new helper in `backend/app/services/news_market_context.py` and two added preflight lines; the readiness test module is new. This describes the actual uncommitted diff, not a claim that those edits are already committed or delivered to main.

The active primary remains on `claude-reflexive-world-state-model` at `495000e`. Its preflight diff against its own different HEAD adds exactly the import of `research_tool_status` and the `research_context` response field. It does not replace main's preflight body, add world admission interfaces, change existing blocker calculations, or alter the existing `ready`/`exit_code` computation. The adapter file, including the earlier snippet-rendering fix and new helper, is byte-identical in the primary, separate main-based worktree and both relevant tested mirrors.

The helper's behavior was checked directly in source:

- It uses `_news_context_subprocess_env()` for canonical parent switches and hard-bounded request limits, and `research_engine_for_run({})` for the default engine.
- It establishes the existing fixed bridge namespace and calls the actual `research_gateway.context_tool_names(controls)`. It does not maintain a duplicate tool-name list.
- Its explicit scope is `default_live_research`. It describes default registration/configuration, not the admitted policy of an arbitrary saved run, historical replay, custom lane or synthesis invocation.
- Credential output is only `credential_configured`, calculated from presence/non-placeholder status. The key string is neither returned nor logged. The reviewer did not inspect any environment file or actual credential value.
- The helper contains no ContextClient construction, provider acquisition, research start or report mutation. Imports establish access to existing modules; `availability_checked` is explicitly false. Registered tools remain distinguishable from provider authentication/availability.
- The new response field is informational. It does not turn missing credentials or a provider status into a new pipeline blocker, and the existing shallow/deep preflight behavior remains under the pre-existing controls.

### Exact readiness source identities

| File/surface | SHA-256 |
|---|---|
| Common active/main-based `backend/app/services/news_market_context.py` | `8d5f3e7885ab46e94a91abbd56152733ea38271d0633e14ce67427f6701f4038` |
| Primary `backend/scripts/preflight.py` | `18c7be1edb9789dcb4505a964417c07c049bdacd2717bde37668a2ef10c3643f` |
| Main-based `backend/scripts/preflight.py` | `181cbe5c739f55ded2d5fbcf345f71a4290f301773de428e29dd4392ebfc7a06` |
| Common `backend/tests/test_research_context_status.py` | `80009e0ca141a249f5d7a37f21f8004a3617f4e857282cdbd8014d4cb3b753bd` |

Different complete preflight hashes are expected because the baselines differ. Copying the whole main preflight file into primary would be the wrong reconciliation. The inspected active change is the two-line insertion only.

### Main-based readiness acceptance: 46 passes

Inspected [completed receipt](/private/tmp/drf-oddsense-readiness-main-d9k2_v43/evidence/completed.json), [JUnit](/private/tmp/drf-oddsense-readiness-main-d9k2_v43/evidence/junit.xml), source files and mirror hashes. The run contains **46 passing cases, zero failures/errors/skips**: six readiness cases, 12 news-research cases and 28 context-pipeline cases. The parent completed with exit 0, preserved identity, normal shutdown and no recorded source drift. It recorded no child processes or network events; this remains the existing CPython audit-hook boundary.

The six readiness cases cover actual gateway/parent-control parity, non-disclosure of a synthetic fixture value, missing/empty/placeholder credential handling, Reddit opt-in and master-off behavior, and the actual Flask full preflight route. The route test preserves real report assembly while stubbing existing blocker/placeholder inputs, and makes starting research fail the test. This is useful route/contract evidence, not a live environment or provider-availability check.

### Fresh primary acceptance: renderer gap closed; four fixture admissions remain

The [source freeze](/private/tmp/drf-oddsense-active-final-6x_2v01i/source-hashes.json) contains **39 entries**: the earlier 37 plus the surgical preflight file and readiness test module. I independently rehashed all 39 active files and all 39 mirror files, with no discrepancy against the freeze. The seven shared peer-file hashes already listed in this review remain unchanged. No whole-main source replacement was found.

The expanded [JUnit](/private/tmp/drf-oddsense-active-final-6x_2v01i/evidence/junit.xml) contains **796 cases in ten modules: 792 passed, four failed, zero errors/skips**. The [completion receipt](/private/tmp/drf-oddsense-active-final-6x_2v01i/evidence/completed.json) records exit 1, normal parent shutdown, preserved identity, no source drift, 22 admitted children, and six denied `subprocess.Popen` attempts. Do not replace exit 1 with a green result because the failures are fixture-related.

All six readiness cases pass on the active primary's own baseline. All 250 cases from the original seven-module Oddsense acceptance pass again, as do the added research-engine-v3 cases; the four failures are confined to the gateway module. The fresh [workflow receipt](/private/tmp/drf-oddsense-active-final-6x_2v01i/evidence/oddsense-workflow.json) pins the current adapter hash above, reports `stage=complete`, successful QA/publication, research/report API and download HTTP 200, no-new-call replay, and both tamper responses at 409. Its source remains unchanged during execution; its tool trace again contains K1/K2 news and market calls. It is explicitly controlled/scripted and not live-provider proof. **This closes the earlier P2 gap for the renderer and its affected report/E2E consumers.**

The four failures are:

1. `test_r3_neutralize_is_linear_on_whitespace_runs`
2. `test_r3_fetch_and_search_of_whitespace_padded_text_stay_fast`
3. `test_r3_passage_and_reasoning_regexes_are_linear`
4. `test_r3_quantity_detection_is_linear_on_long_digit_runs`

Each is in `backend/tests/test_research_gateway.py` and reaches `_r3_isolated()`, which invokes `backend/tests/fixtures/gateway_performance.py` through `subprocess.run`. The unchanged guard rejects this fixture before the performance result is measured: it is absent from the allowed-script table, which currently contains only the two provider fixture modules. Thus these results do not demonstrate a readiness regression or a measured performance failure. They also do not establish that the four performance requirements pass. There are six recorded denied attempts, not merely four attempts; the four-case failure count must not be confused with attempt counts.

**Remaining bounded acceptance item:** adapt/admit that exact performance fixture through the existing guarded-child protocol, preserving the guard and all four assertions, and rerun the affected cases/current matrix as appropriate. Do not bypass the audit boundary, weaken its deny rules, or mark these cases passing without execution. No production readiness change is indicated by the observed failures. This reviewer does not mutate the fixture or run tests.

### Activation and preservation limits

The readiness source is reviewed with no code blocker. The current-source helper and core Oddsense producer/consumer scenarios have passing evidence. The expanded matrix still has the four fixture-admission failures above; it is not an all-green activation receipt. Existing frontend/native-PDF/live-provider limits remain separate. Whether the backend is idle, uses the private configured key and has loaded the new source remains parent-owned runtime verification; this review performs no restart or live preflight call.

At follow-up intake and the 2026-10-22 08:31:19 UTC closing check, primary HEAD was still `495000e`, main remained `da1d3c4`, the staged diff was empty, and the real index retained the previously recorded later hash `7fa33b92d33d22324c07eb99785ef5a38c54458757084b29e4479b3f8f6f62b0`. The readiness adapter, primary preflight and readiness test hashes above also remained unchanged. The earlier raw-index discrepancy remains a historical observation; no additional index change was observed in this follow-up. The reviewer continues to write only this document.

## 2026-10-22 08:38 UTC final closure: exact-fixture registration accepted

**Bounded review status: Complete. No remaining implementation or scoped acceptance blocker.** This closes the four fixture-admission failures; it does not rewrite or discard their earlier evidence and does not claim deployment or live-provider success.

### Corrected gate and source agreement

Independently inspected the registered-run [completion receipt](/private/tmp/drf-oddsense-active-final-6x_2v01i/evidence-registered/completed.json), [JUnit](/private/tmp/drf-oddsense-active-final-6x_2v01i/evidence-registered/junit.xml), [log](/private/tmp/drf-oddsense-active-final-6x_2v01i/pytest-registered.log), event stream and every child receipt. JUnit contains **796 tests, zero failures, zero errors and zero skips** across the same ten modules and the **exact same selector set** as the original 792/4 run. The log reports **796 passed in 18.97 seconds**. Parent PID 12132 completed with exit 0, normal shutdown, preserved identity and `source_drift=[]`.

The original and registered completion receipts have identical `source_sha256` maps. I also independently rehashed all **39 files** in the unchanged [source freeze](/private/tmp/drf-oddsense-active-final-6x_2v01i/source-hashes.json) against both active primary and the tested mirror: **39/39 match in each location**. The adapter hash remains `8d5f3e7885ab46e94a91abbd56152733ea38271d0633e14ce67427f6701f4038`; preflight/readiness and all seven preserved peer-source hashes are unchanged.

The only additional allowed script is the exact existing `backend/tests/fixtures/gateway_performance.py`, hash `ea81aeb522a76a9fbb8e87e7f0d37616858cf3e221774feb288453ab0a611881`. Its active and mirror hashes agree. The unchanged guarded runner is still `53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa`. Neither the fixture, gateway test module nor guard has a primary diff against HEAD. The original failure was repaired through exact fixture admission; no guard relaxation, performance assertion removal or production source change is needed to explain the green gate.

### All 26 children accounted for

All 26 parent child-table entries have matching receipt files and matching PIDs. The event stream independently records 26 admitted guarded children. The disposition is **24 normal zero exits plus two intentional provider interruption controls**, not 26 zero exits:

| Child records | Parent-observed result | Receipt state and interpretation |
|---|---|---|
| PIDs 12198–12213 and 12215–12218: 20 provider fixture children | Exit 0 | Each has `status=completed`, `exit_code=0`, `shutdown_complete=true`, preserved identity and no source drift. |
| PID 12214 | Exit 23 | Deliberate provider crash control. Receipt correctly remains `status=started`, `exit_code=null`, `shutdown_complete=false`; the parent records the actual exit. The unchanged fixture explicitly expects abrupt exit 23 after durable admissions. |
| PID 12219 | Exit -15 | Deliberately terminated provider control. Receipt correctly remains started-only with no child completion code; the parent records termination. The unchanged provider fixture intentionally terminates this child and verifies conservative reservation/replay behavior. |
| PIDs 12223–12226: four gateway performance children | Exit 0 | Each completed normally with preserved identity and no source drift. All four admission events name the exact registered `gateway_performance.py` fixture. Their previously failing test cases now pass. |

The two interrupted children are expected acceptance controls; they are not normal shutdowns. Every child receipt reports preserved identity and an empty source-drift list. The parent retains **two denied subprocess attempts**, attributed as `uname` and a redacted `unregistered-executable`. They remained denied; this is not zero attempted subprocess activity. No network or credential event appears in the inspected event stream. The mechanism remains a CPython audit-hook boundary, not an OS sandbox.

### Current producer-to-consumer proof and retained red evidence

The registered-run [workflow receipt](/private/tmp/drf-oddsense-active-final-6x_2v01i/evidence-registered/oddsense-workflow.json) pins the same current adapter hash, records unchanged source, completes research QA and report publication, returns 200 for dossier/report/download, replays without new calls, and rejects both report and dossier tampering at 409. It remains explicitly controlled/scripted with `live_provider_proof=false`.

The prior [completion](/private/tmp/drf-oddsense-active-final-6x_2v01i/evidence/completed.json), [JUnit](/private/tmp/drf-oddsense-active-final-6x_2v01i/evidence/junit.xml) and `pytest.log` remain intact with **792 passed / four failed**, parent exit 1, and the original denied exact-fixture attempts. This red-to-green progression is retained as evidence of the admission correction rather than overwritten by the successful run.

| Evidence artifact | SHA-256 |
|---|---|
| `source-hashes.json` | `0a487d6a4a581bfcf3c63d131070d73d716e7141237f60bc7e1be76d459ffd83` |
| `evidence-registered/completed.json` | `261225616df64234acbfa73eca2b106fdcb9064e17367a319f82f14aad6eaab8` |
| `evidence-registered/junit.xml` | `821efd77abdef258a741c081a0101b3b1ecfe4f5a41744d04885c5679af19c28` |
| Original `evidence/completed.json` | `f10d4cf20c914d816a123043ddb2decebad967e28d71c38a583ee0598989643a` |
| Original `evidence/junit.xml` | `41dda28c28693377397fb0957ba8ab52b959b31f9cd59306365949337550c335` |

### Final disposition and ownership

Both earlier P2 acceptance items are closed on inspected evidence: the current renderer/readiness/report consumers pass, and the four performance selectors pass with their exact fixture registered. The earlier raw-index checksum change remains an accurately documented historical preservation discrepancy, with indexed contents equal to HEAD; it is not erased or converted into a byte-preservation claim.

At this closure, primary HEAD remains `495000ea98d6bcd20daa7eff1398ed5ad2663310`, branch `claude-reflexive-world-state-model`; main remains `da1d3c4dbb581f15aaba43da776608708c5cd356`. Staging is empty and the real index retains `7fa33b92d33d22324c07eb99785ef5a38c54458757084b29e4479b3f8f6f62b0`.

This finishes the independent source/acceptance review. Deployment overlay synchronization, confirmation of idle process ownership, restart and observation of the running backend are separate parent-owned work. None was performed or certified by this reviewer. Only this postreview document was edited; no `.env` read, application import, test execution, provider call, Git mutation, source edit or runtime action was performed.

