# Shared backend Mandarin display translations

**Status:** Structured forecast/display repair and inline status boundaries passed focused current-source acceptance. Owned source is frozen for combined acceptance/rereview; coordinator owns activation and delivery.
**Scope:** `artifact_translation.py`, `translation_tools.py`, translation/display routes in simulation/research/report APIs, the research POST force flag, four new backend test modules, and the explicitly granted `_dead_pid` fixture helper. No lifecycle, canonical report producer, SDK, environment, service, Git or provider operations were performed by this owner.

## Request and acceptance

The user needs predominantly Mandarin content throughout Simulation and Research Report tabs and reliable retries instead of repeated numeric errors. The report translation engine's numeric parity is separately owned by the coordinator. This slice protects structured/overlay facts and completes the backend display contract.

| Requirement | Exercised consumer and check |
|---|---|
| Visible simulation prose, including actors/feed/decisions/private scoped view | Real Flask POST/poll of exact caller text inventory, identity echo, source-content hashes, context mismatch denial and default-cache privacy negative |
| Incremental simulation updates | Existing validated source strings are reused internally; a new visible inventory receives a new digest and only new strings reach the controlled translator |
| Preserve facts and appropriate English | Protected numbers, units, dates, quantities, ranges, currency symbols, citation IDs, URLs, machine IDs, leading decimal, scientific notation and Unicode minus; proper names allowed; copied English sentences rejected |
| Retry malformed/partial output | Missing/extra/duplicate JSON keys, nonstring values, changed tokens, refusal/English echo; only validated entries cached, pending entries retriable |
| Complete structured dossier display | Actor roles/stances/memory, situation brief, relationships/hot topics/events, timelines/source titles, market questions/rules and dataset labels; IDs/numbers/units/raw URLs retained |
| Complete forecast display | Separate title/news-context/viz-caption/failed-section projection, admitted only after actual language publication when a body task requests acquisition |
| Restart and publication separation | Real separate guarded interpreter reads exact saved overlay with no provider constructor; existing dead/live PID assertions retained; report canonical bytes/download/SDK resolution remain valid |
| Source/audit invalidation | Changed source during generation rejects publication; tampered variant refused by JSON/PDF readers; failed forced regeneration retains previous good Markdown/audit bytes |

## Caller contract

Simulation POST remains `/api/simulation/<id>/translations/<lang>`, with JSON `{texts:[...], context:{engine,platform,round,generation_id,revision,view,actor_id}}`. Poll the same GET with `request_digest` and `context=JSON.stringify(context)`. The response echoes identity/context and returns `request_digest`, `source_fingerprint`, `target_lang`, `simulation_id`, `translations:[{source,text,source_sha256}]`, legacy `overlay`, `status`, `pending`, `failed_keys`, `partial`, `retryable`, `issues`, counts and update time. Default GET never enumerates a private/analyst visible-text cache. World-v1 native fallback uses the actual public result reader, not raw private artifacts.

Research translation GET returns audited `report` plus separate `dossier` display copy and `structured_translation:{status,complete,coverage,partial,pending,retryable,issues,source_fingerprint,target_lang}`. The original dossier GET accepts `?lang=` and adds this same separate display copy while retaining canonical fields. The display includes `data/datasets.json`. POST `?force=1` is honored. Markdown availability is separate from structured completeness. Previously successful variant bytes survive failed forced attempts; exact source/variant/audit hashes admit a readable variant.

Forecast GET `/api/report/<id>/forecast?lang=` keeps the manager's existing localized forecast and adds `display:{title,news_market_context,viz_manifest,failed_sections,translation_status}` plus identical `translation_status` and `structured_translation` coverage objects. Existing translation POST starts/deduplicates missing display work. An already audited Markdown retains the existing HTTP200/available contract, with display progress in `structured_translation.status`. GET does not translate. Real body-task status is never overwritten by display progress. Chart paths obey the existing report-owned `charts/` policy. Source/canonical reports, forecast values, prices, units, source identities and publication/ledger proof are not rewritten.

## Implementation and limits

The pair translator protects whole date/quantity spans and fact-bearing tokens before model transport, restores them deterministically and validates every returned value. It chunks long strings without truncation, limits batches and total logical client calls, saves incremental validated progress, and never accepts an extra provider key. Persisted entries are validated again on read. Temporary files are unique/atomic; acquisition/cache writes serialize by file lease. Visible inventories are limited to 1200 strings, 32000 characters per value and 240000 characters total; the frontend splits larger rendered pages into bounded requests. Source-keyed validated strings are reused internally, but a response only returns its exact admitted request inventory and context.

The structured projection traverses named human-text fields/containers and deliberately keeps machine metadata, numeric values, units, quote/basis/citation contracts and raw URLs. Canonical image/HTML chart artifacts themselves are not regenerated; the view translates prose/captions, with chart-native technical labels retained. The native graph collector retains its existing bounded graph selection. Complete live simulation coverage uses the current frontend's visible-text inventory rather than an unbounded scan of profiles, feed databases or private world state.

Offline model transports are scripted; this does not claim live provider availability, semantic translation quality or a completed live UI/provider test. The coordinator's combined current-source gate and independent review remain required.

## Evidence and retained history

- First mirror `/private/tmp/drf-artifact-translation-first-apa7ne_5`: 30 passed, one old fixture exposed incorrectly selecting machine `cause=seed`; collector selection fixed, assertion retained.
- Second mirror `/private/tmp/drf-artifact-translation-second-5k427bvb`: 76 passed, one existing Markdown-availability contract failed; preserved the existing HTTP200 availability and separated display status, with original assertion retained.
- Third mirror `/private/tmp/drf-artifact-translation-third-her2xnrg`: 152 passed, two old tests were blocked launching inline Python. No exclusions or guard weakening; the explicitly granted helper now launches the repository's exact named `orphan_owner.py --mode exit`, retaining all original live/dead PID assertions.
- Freeze1 `/private/tmp/drf-artifact-translation-final-013czjcw`: 155 passed, four actual guarded children, no source drift, identity/shutdown preserved.
- Freeze2 `/private/tmp/drf-artifact-translation-freeze2-gpq0eo2j`: 157 passed in59.92s, no skipped/deselected cases, four actual guarded children all completed/exit0/shutdown/identity/no drift. Receipt SHA256 `03600f8e929967dd18d1e63d759716563f0763bec1c24f9d638d49592fb63ece`; JUnit SHA256 `079596959958eef6bb0f3c90300d1d3b4ce1059637b54e2e533d5260d95d4cfb`.
- Those older receipts explicitly contain eight denied Popen attempts and18 denied font reads. Two programs were `fc-list`/`system_profiler`. A fresh guarded diagnostic copy `/private/tmp/drf-translation-pdf-probe-xavwz5uy` attributed the other six to `claude` fallback from a legacy test that mocked an available result without publishing a variant. The diagnostic wrapper called the original guard and recorded only program basename/stack, never command arguments. No command was dispatched. A production publication check now prevents further display acquisition on such a stale/unverified result; a provider-constructor-forbidden regression covers it. These historical attempts are not relabeled as zero attempts.
- Current final candidate `/private/tmp/drf-artifact-translation-freeze3-sn42hue7`: source hashes in `source-hashes.json`; 158 passed in48.88s with no failures/errors/skips/deselections. All four children completed/exit0/shutdown/identity/no drift. Parent receipt also completed/exit0/shutdown/identity/no drift. Final observed attempts are only two denied font-discovery commands (`fc-list`, `system_profiler`) and18 denied font-path reads; the six prior CLI attempts are absent. Receipt SHA256 `bdcc53d41d41511213506bb5ff6f7cef3e3651d82a942f893d5834ec7ca261f1`; JUnit SHA256 `0a9edb47b5bb31f222eebde97bfbb895729da1901f97da8f5ac48733cde3edc0`. All13 owned/guard/fixture source hashes matched the tested mirror at handoff; the coordinator concurrently changed the14th dependency `report_agent.py`, so its new bytes require the combined gate; detailed reconciliation is `verification.json`. Exact runner admissions are only `backend/tests/fixtures/orphan_owner.py` and `backend/tests/test_artifact_translation_restart.py`; no guard source change.

## Remaining work

The last receipt, all four child receipts and13 unchanged current owned/guard/fixture source hashes have been reconciled. The separately owned `report_agent.py` changed during the run and is explicitly outside this receipt's current-byte claim. Obtain the coordinator's independent review and combined gate, then let the coordinator activate and deliver. This owner performs no service/provider or Git operations.

## Updates

- 2026-10-22: Recorded source/consumer contract, scope, retained reds, previous green receipts and the publication-admission improvement before final handoff.

- 2026-10-22: Freeze3 scoped acceptance closed at158 passes with no exclusions, four clean guarded children, current source reconciliation and complete attempt attribution.

- 2026-10-22: Corrected final reconciliation:13 owned/guard/fixture files still match; the coordinator's concurrently edited report_agent.py dependency differs and requires the combined current-source run. The scoped receipt remains tied to its frozen dependency bytes.

## Independent review corrections, 2026-10-22

The retained independent review found four owned boundaries despite the earlier green suites. They were lifted into `backend/tests/test_artifact_translation_review_regressions.py` and reproduced on current source before correction: `/private/tmp/drf-artifact-review-red-doijbqvp/evidence` has six intended assertion failures, no setup errors, and the actual thousand-string service-to-Flask retry remained at136 pending. No review assertion or guard was weakened.

The forecast API now preserves the actual manager's full localization verdict instead of recomputing completeness from whether a variant file was selected. Pair restoration inserts only whitespace proven between the exact same adjacent source placeholders; real fused identifiers and changed values remain rejected. Mandarin quality validation removes boilerplate translation labels, checks ordinary English clauses across sentence punctuation and shares that same admission check with the already-target fast path/cache reader. Proper-name/technical positives and all numeric/unit/citation guards remain.

A partial artifact retry repairs missing/invalid entries before optional refresh. Explicit force on a complete valid inventory retains the good texts, tracks unfinished refresh keys separately, discloses partial refresh and resumes only its tail on the next bounded request. Thus force no longer deterministically reprocesses the same864-good prefix while starving136 missing strings. A separate bounded complete-inventory refresh control checks retained good entries and failed-refresh disclosure.

The focused candidate `/private/tmp/drf-artifact-review-green1-rsz0ewog` runs the actual reviewer-derived cases plus prior owned pair/service/API/restart/bilingual controls. Acceptance is pending at this update; do not assign the old158-case receipt to these corrected bytes. The coordinator separately owns localized-forecast protected-atom admission and frontend initial-read unmount findings.

- 2026-10-22: Resumed the four explicitly assigned review corrections, retained the real6-failure red and started focused current-source acceptance before a new freeze.

### Current focused correction acceptance

`/private/tmp/drf-artifact-review-final-m_sg1m8o/evidence` passed218 cases in17.27s, no failures/errors/skips/deselections. All18 listed current source/dependency/guard/fixture hashes matched the frozen mirror after shutdown. All four child receipts completed/exit0/shutdown/identity/no drift; parent likewise. Observed attempts remain explicit: two denied library font commands (`fc-list`, `system_profiler`) and18 denied font-path reads; no model/CLI/socket acquisition. The real large-page correction progresses136 pending to0 on the forced API retry using only8 additional logical translator calls; no good-prefix keys are requeued.

The reusable `translation_tools.FACT_UNIT_PATTERN` now recognizes common SI power/energy tokens with raw case preserved: W/kW/MW/GW/TW/mW/uW/µW/μW and corresponding Wh forms, longest first. Its scoped case-sensitive branch overrides outer ignore-case flags; boundaries avoid ordinary words/identifiers while allowing numeric attachment. The actual pair producer protects the unit in transit, and an actual cache-reader test rejects25 kW→25 W even if the tampered text checksum was recomputed. Signed-quantity grammar and report-helper fixes were made by the coordinator, not this owner, and their current bytes/tests were included in this acceptance.

A preceding expanded candidate had217 passes and one newly added tiny-negative quantity parity failure on the then-frozen coordinator dependency; the coordinator independently fixed that boundary before the final snapshot. That historical receipt remains at `/private/tmp/drf-artifact-review-green2-7slrzgif`. The earlier four-boundary baseline6-failure receipt and the independent original reds remain retained.

Final hash and child reconciliation: `verification.json` in the current candidate. Receipt SHA256 `599126adef97c3c20b9f4922a71a8b3838ce3bda7c1c799aa9a47e9a0180846d`; JUnit SHA256 `11960229f0a70b786d5a8f0236fd295a32b07750ed9057acac54821ef8c43499`. The coordinator must still run the planned combined current-source gate and request independent rereview; this focused receipt is not universal live/semantic translation proof.

- 2026-10-22: Closed the four owned review corrections plus the explicitly requested SI-unit gap, with218 focused current-source passes and18/18 source hash reconciliation. Owned source is frozen pending combined acceptance/rereview; no Git, runtime services, providers, environments or production saved data were mutated by this owner.

## Shared translation provider admission

A later live observation reported simultaneous simulation inventories and report translation workers exhausting the shared GLM concurrency limit. This owner did not perform that live acquisition. The approved extension is `translation_tools.translation_client(llm)`, an idempotent attribute-forwarding proxy with one shared per-process FIFO admission queue for actual `chat`/`chat_json` calls. `DRF_TRANSLATION_MAX_CONCURRENCY` defaults to1, invalid values use1 and integer values clamp to1..4. Slots cover the complete underlying call, including its own retries, and release in `finally` after success or error. This is a translation-only process limit, not a cross-process or provider-account quota. Generic `LLMClient`, guard code and environment files are untouched.

Pair calls use this proxy inside their existing bounded client. The coordinator separately wraps public report/research/localized-forecast translation scopes and restores original client identity after joined work. Other client attributes and methods remain delegated. `chat`/`chat_json` are resolved dynamically so missing capabilities remain absent for `hasattr` protocol selection; a real method's internal exceptions are never converted into a missing-capability fallback. The initial always-defined-method proxy was actually reproduced red at `/private/tmp/drf-translation-admission-6uchuxop/capability-red-evidence` (one intended assertion failure in1.30s), then corrected without changing its assertion.

New `test_translation_pairs_admission.py` uses real threads with held controlled clients to verify default1, different client objects, both call protocols, configurable2 and clamp4/1, preserved arguments/attributes/idempotence, release after both failure paths, real pair/report shared admission and missing-method/internal-error boundaries. A fresh guarded mirror includes the coordinator's current report wrapper, new concurrency/cooldown tests and error classification. No owner provider/service/Git/credential operations are performed; this does not claim that a provider can never rate-limit an application for other reasons.

- 2026-10-22: Added approved shared translation admission and capability preservation, retained the capability red, and started fresh focused acceptance before replacing any readiness claim.

### Provider-admission focused acceptance

The first expanded admission run had233 passes and one legacy configurable-parallel fixture failure at `/private/tmp/drf-translation-admission-green-euuuxd4v`: the new default1 correctly prevented its two fake retry calls from overlapping. The coordinator explicitly authorized exactly one fixture line setting `DRF_TRANSLATION_MAX_CONCURRENCY=2` in that test. Its original barrier and all overlap assertions remain unchanged; separate new controls retain the default1 assertion.

Final `/private/tmp/drf-translation-admission-final-ruydkq8t/evidence` passed234 cases in16.35s with no failures/errors/skips/deselections. It includes all ten new actual-thread/capability cases, the coordinator's real report-plus-pair maximum1 and pure cooldown/publication-negative controls, the prior owned review/service/API/cache/restart tests, signed quantities and existing error classification. All16 listed current source/dependency/guard/fixture hashes matched the mirror after shutdown. Parent and all four child receipts completed/exit0/shutdown/identity/no drift. Observed attempts remain two denied font-discovery commands and18 denied font-path reads; no CLI/provider/socket acquisition.

`verification.json` retains exact hashes, counts, attempts and child reconciliation. Receipt SHA256 `c49b1c724ad45669ed0b5a953d168dfc6d98f1bea2ac53c0b0a9e1de772c96a2`; JUnit SHA256 `e1a4dca561745ca55b5ef1fa3816b7e31b15698386909edfaf51087a11451b16`. Generic LLMClient, guard code and environment files were not edited. This establishes the exercised per-process translation admission and failure/capability contracts, not a live provider/account-wide throughput guarantee. The coordinator's combined current-source rerun and independent rereview still apply.

- 2026-10-22: Closed shared translation admission with234 focused passes, ten new threaded controls,16/16 current hash reconciliation, and the explicitly approved parallel-fixture setting. Owned code is frozen; no further edits are planned absent a new finding.

## Audited-body structured forecast repair

A new consumer finding showed that plain POST for an already-audited body repaired only display metadata and skipped an incomplete forecast. The owner lifted it into `test_artifact_translation_structured_job.py`: two actual primary/translated publication fixtures, native incomplete forecast readers (including stale `complete:true` metadata), and already-complete display caches reproduced the old API's missing-job behavior. Both baseline cases failed at the intended queued-job assertion, with no setup failure, at `/private/tmp/drf-structured-job-red-576qzg95/evidence`.

The shared job now invokes the existing source-bound forecast-localization producer followed by the display producer, under a separate advisory lease and cache-bypass context. It validates the language publication before work and again after forecast work. It never regenerates Markdown or rewrites canonical forecasts, audit files, citation artifacts or report publication metadata. `_report_structured` only reads the two projections and reports their joint completeness, coverage, pending fields, forecast source hash and source fingerprint. Its generating status lasts for the entire job; after completion/refusal the reader reports available/partial and retryability. The native manager's forecast localization verdict is preserved. GET performs no acquisition. Existing Markdown remains HTTP200/available during optional structured repair.

Four native Flask cases cover both incomplete metadata forms, request deduplication, GET/no-acquisition while a controlled forecast call is held, real producer/reader completion, canonical/translated Markdown/audit/citation/meta byte preservation, failure/partial/retry, no body-generation calls, and a source mutation that remains unsealed and yields real forecast-reader/API rejection409. The coordinator separately added strict current-reader completeness before reuse and cache bypass inside the existing forecast producer; this owner did not edit ReportAgent.

An initial focused run had all four new cases passing, with58 total passes and one setup-boundary failure because the invocation omitted the existing named orphan-process fixture admission. The fixture/guard were not changed. The replacement run uses the same exact two allowed child scripts as prior acceptance and a fresh source mirror.

- 2026-10-22: Opened and implemented the scoped plain-POST forecast repair finding, retained the two actual-consumer reds, and started current guarded replacement acceptance. No service/provider actions or waiting for the ongoing live run are part of this owner task.

### Inline activity correction and current readiness

The first whole scoped replacement passed253 cases at `/private/tmp/drf-structured-job-final-etfjfetc`. Independent source review then identified that the body-task path calls the repair helper inline without the background driver's active marker. Two additional actual inline held-call tests reproduced `partial` instead of `generating`, including a held constructor failure, at `/private/tmp/drf-structured-inline-red-5pc1djrx/evidence` (two intended failures in5.36s). The helper now owns activity registration/cleanup for direct inline work. Its default path joins an already-active repair without acquiring more work. The pre-registered background driver passes an internal flag and retains its existing outer cleanup. No new asynchronous job or duplicate provider acquisition was introduced.

Current `/private/tmp/drf-structured-inline-final-6_ddjqad/evidence` passed255 cases in18.83s with no failures/errors/skips/deselections, including all six structured-job cases plus prior service/API/forecast/body/admission/restart controls. All17 listed current source/dependency/guard/fixture hashes matched the frozen mirror after shutdown. Parent and all four child receipts completed/exit0/shutdown/identity/no drift. The only denied attempts were the known two library font-discovery commands and18 font-path reads; no provider/CLI/socket acquisition.

`verification.json` retains exact source hashes, counts, attempt and child reconciliation, and retained-red pointers. Receipt SHA256 `3b5701e0f43aa1c1d4303a450bbecc64ffd1c1bea8400a041ca2515de57eb0f2`; JUnit SHA256 `94f7ca4deb9008998ecac08666e3dbd276b116be87fcae4cd0458d03e246fa31`. The API and new test module hashes are in that manifest. Body availability/main body-task status remain separate from the joint structured status; GET is read-only, and canonical/translated Markdown, audits, citations and metadata remain byte-identical in the positive/failure controls. The source-mutation control remains unsealed and is rejected by the real reader/API409. The coordinator's final combined run and independent rereview remain required; no live-run waiting, service refresh or provider request was performed by this owner.

- 2026-10-22: Closed plain-POST structured forecast repair and direct-inline activity with255 current focused passes;17/17 source reconciliation and four clean guarded children. Owned source is frozen pending combined acceptance.


## Approved model-led migration (2026-10-23, in progress)

The coordinator approved the new shared `model-translation/v1` engine and owns its implementation and ReportAgent migration. This owner adapts raw pair production, typed display selection, schema4 receipt caches and the explicitly granted research variant reader. Numbers and dates now reach translation and its separate semantic review as readable source. The active adapters no longer use the historical token protection/restoration or exact numeric token bag. Parsed Markdown/code/link/citation checks and source/target/language/context-bound review receipts admit cache entries. Arbitrary untyped prose facts depend on the reviewer's judgement; this is not a deterministic proof of semantic truth. Typed factual fields and identifiers remain canonical and outside the structured prose selection.

Full request contexts still identify privacy/cache requests; stable artifact-kind context identifies reusable text review receipts. Default GET cannot enumerate private visible-text pools, and GET never acquires a translator. A new engine/version prevents legacy unreviewed cache adoption. Explicit force preserves good entries and missing-first progress, with translation plus review calls counted toward the shared budget. Research readers validate new document receipts read-only while retaining the historical legacy audit/hash contract.

Only the two granted pair/cache fixtures in `test_translation_ladder.py` are adapted to raw JSON and review call counts. Euler owns shared long-form/forecast transport fixtures and the common model-protocol helper. Prior255-pass evidence above is retained as historical old-engine acceptance and is not assigned to these changed bytes. A fresh guarded focused gate, receipt/cache corruption controls, native API/restart scenarios and final coordinator combined gate are required. No Git, services, providers or saved production data are touched.


### Model-led adapter scoped acceptance and freeze

The first raw-model affected run at `/private/tmp/drf-model-artifacts-5r8bz6z3/evidence` passed80 cases and exposed one actual shared-parser false negative: ``The `Q12027` forecast remains unchanged.`` translated faithfully as “`Q12027`的预测保持不变。” was rejected because dropping the English article removed a plain-text AST prefix. The coordinator fixed the shared parser to ignore prose text leaves while retaining ordered structural/immutable carriers, and added a native code-leading regression with a changed-ID negative. The owner's exact failing case was rerun unchanged; no artificial target prefix was added.

The replacement `/private/tmp/drf-model-artifacts-final-isn34jr8/evidence` passed110 cases in25.53s with no failures/errors/skips/deselections. It includes all81 owned affected cases plus current shared-core and13 workflow acceptance cases. The exercised paths cover actual raw translate/review adapters, explicit equivalent currency/date formats, code-leading Mandarin, one failing-entry repair, call-budget accounting, shared admission/failure/capability behavior, schema4/cache/pool admission,1000-entry forced tail progress, retained-good force refresh, typed canonical facts, source/context/version/language changes, actual Flask simulation/research/report readers/jobs, immutable publication/SDK controls and actual separate interpreter restart. The research proof reader requires new engine receipts and preserves the historical audited legacy contract.

`verification.json` stores the27 exact frozen input hashes, JUnit summary, all child receipt paths/hashes, retained red and scope limits. Parent and all three registered children completed/exit0/shutdown/identity-preserved/no drift. Parent events contain only the three storage redirects, three admitted guarded children and the named reaped-child liveness check; child events contain only redirects or no events. No denied attempts/library probes were recorded in this bounded run. This is controlled transport/reviewer-oracle evidence, not live-provider translation quality or a proof that model semantic judgement cannot err. Receipts are integrity records, not signatures.

All owned production/test bytes and shared production dependencies matched the frozen mirror after shutdown. Two **peer-owned fixture dependencies** changed while the run executed: `test_report_bilingual.py` from44bc17ad… to f1bc9f15… and `test_translation_dates.py` from955ba787… to64c9e24d…. The110-pass receipt is explicitly bound to its frozen fixture versions and is not assigned to those later peer bytes. The coordinator's replacement combined gate must use current peer fixtures and supersedes this narrow dependency limit. No own source/test edit is planned after this freeze absent a new finding. No Git/service/provider or saved-production-data operation was performed.

Receipt SHA256: `4d87884e77b9894a8eb48491d41659ecfaf80385d6ae8c9886e29effbe501c41`. JUnit SHA256: `e7a5fce43cc10048adf50429e6a9be376d357812956c38742209bfd5c34e6386`.

| Owned input | Frozen SHA256 |
|---|---|
| `backend/app/services/artifact_translation.py` | `cb3a960bbc65e7c3f03390d9b3b14100803c4206435003e3b416e269f0934d88` |
| `backend/app/services/translation_tools.py` | `df75a4fedf2253bca20cebea96cbfe5d77fcf6704de12e08f56ec0d629dd0221` |
| `backend/app/api/research.py` | `58b65a7a6f64f47bbe1a1732620a83e3d364e97900c0312ae2409723745d57a3` |
| `backend/tests/test_translation_ladder.py` | `69fee1969db7c98b82e39221ef783c836de1858e3563dabe83c166570cdef31a` |
| `backend/tests/test_translation_pairs_integrity.py` | `25048608018c3caa8ae3e07b9653a59e6d2e2d87e745ec467a2f1446b0b34876` |
| `backend/tests/test_translation_pairs_admission.py` | `9b598e0dfa5c6c01bfb2330f08f89ae4f5038bfe69f10aa611157aace0dbbeaa` |
| `backend/tests/test_artifact_translation_model.py` | `582b61b388e779919eca69bfcf046e832957ccff78b351a350f66a9bbe3d4045` |
| `backend/tests/test_artifact_translation_restart.py` | `5320a95b415608fa94d4e05c791860450aa334372b740b1003dffa8a89e39b4c` |
| `backend/tests/test_artifact_translation_review_regressions.py` | `fb20286f87d5d857e655dc58b90582ad92fbef536ae5d07387f980236d04a515` |
| `backend/tests/test_artifact_translation_routes.py` | `821b36281284dd3cd94eb189e62e1a0060ba4560d6f3dade2f950aa594245ef9` |
| `backend/tests/test_artifact_translation_services.py` | `192abb900b62b35dc7e98fda65e6d0ab6238d6c9d9b3ea59851a9862cadb8d37` |
| `backend/tests/test_artifact_translation_structured_job.py` | `790ba98a0a8de32eb131ab753a125491082f2c28e92d0d2f1326293e33f4114a` |

- 2026-10-23: Closed the owned model-led adapter/projection/cache/proof-reader affected gate with110 passes, three clean guarded children, exact source receipts and the explicit two-peer-fixture delta above. Scope is ready for coordinator combined acceptance; prior old-engine receipts remain historical.


### Independent target-review relationship correction (2026-10-23)

The final independent target review reproduced two schema errors: global human `source` selection translated relationship endpoint `A1`, and globally preserved `basis` omitted the dossier's scalar relationship explanation while claiming full projection coverage. The correction changes only `artifact_translation.py` and `test_artifact_translation_model.py`. Relationship source/target endpoints now remain canonical, including name-shaped endpoints; source-credit labels are selected only in known dataset/chart schemas. Scalar relationship basis prose is selected, while structured basis objects and their references/provenance stay canonical. No translation/model validator was weakened.

Three lifted controls were actually red against the prior source at `/private/tmp/drf-model-relation-review-qeoq8b4o/red-evidence`:3 failures/13 explicit unselected existing nodes, no setup errors. Native actual research-worker/API cases cover typedA1 and nameNVIDIA endpoints, reviewed basis/type translation, immutable actors bytes, read-only GET and an explicit no-endpoint-submission assertion. The display control covers structured basis preservation, canonical untyped source references and positive dataset/chart credit translation.

Fresh current `/private/tmp/drf-model-relation-green-38n_j7zc/evidence` passed40 cases in12.90s (0 failures/errors/skips/deselections), including these regressions, owned cache/services/routes/restart and current model workflow acceptance. Parent and all registered guarded children completed/exit0/shutdown/identity/no drift; only expected redirects/admitted children/liveness events were recorded. `verification.json` records exact hashes, all child receipts and proof limits. This remains controlled transport/reviewer evidence; the coordinator's replacement full target gate is required. No Git/service/provider actions were taken.

- Frozen artifact source SHA256: `c62285688e8cdd4a07aa051540aa351e6461c2bf276723fe62be7fbcd5e0352e`.
- Frozen owned model-test SHA256: `041a81513592fe7ee235e8e2e07c98eed230665b6ecaa9a94e2764e7b4f7f755`.
- Receipt SHA256: `d9d4cb7628c373a65f7f32e9581310a4b1a8501e37e389ac1103ab96113411a1`; JUnit SHA256: `c5acdb116960c4eebd47c932602396335fc11bb799710094ded83dc08dc47a18`.
- 2026-10-23: The two corrected source/test files are frozen for coordinator target acceptance; earlier110-case receipt remains bound to its earlier source and is not reassigned to these bytes.
