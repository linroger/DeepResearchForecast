# Model-led translation workflow acceptance

Status: owned acceptance sidecar complete and frozen; thirteen guarded scenarios pass on the recorded snapshot. The coordinator's later dependency edits still need the final combined-byte gate.

## Owned scope and request

This worker owns only `backend/tests/test_model_translation_workflow.py` and this document. The coordinator owns the shared model-translation core, ReportAgent migration and dependencies; the artifact owner owns translation adapters and cache/projection changes. This worker will not change those implementations, publication gates, existing tests, Git state, running services, saved runs, or provider configuration.

The user approved translating original readable Markdown and human prose with the model, preserving parsed structure and canonical typed facts, then reviewing fidelity with a separate bounded model call. Existing publication, source identity, polling and read-only cache contracts remain in force. The separate review is a second scripted model invocation in these tests, not evidence of an independent model or live semantic quality.

## Requirements and planned evidence

| Requirement | Acceptance scenario | Required evidence |
|---|---|---|
| Raw readable translation is the default | Real ReportManager generation and research worker; legacy protection/repair methods raise if entered | Actual model messages, native audit and published sidecars |
| Equivalent localized quantities and dates are accepted | Source `$3.7 billion` and `October 22, 2026` become `37亿美元` and `2026年10月22日` with an affirmative semantic review | Exact source/target receipt and real reader availability |
| Factual drift remains rejected | Scripted wrong unit/negation receives negative semantic verdict on original plus one repair | Bounded call trace, rejected result, no available sidecar |
| Structure is preserved without rewriting | First candidate drops a heading/table; repair restores it | Actual repair messages and final Markdown |
| Canonical JSON stays unchanged | Research dataset codes, scientific numeric strings, dates, probabilities, IDs and units pass through structured display | Before/after native files and API payloads |
| Consumers verify persisted proof without providers | Actual report GET/download plus research and simulation readers after module reload | Forbidden provider constructor on reads; equality with persisted bytes |
| Source and output mutation fail closed | Change source during generation; tamper persisted translated Markdown/cache | Actual public reader denial and retained original proofs |

## Plan and progress

1. Inspect native ReportManager/publication, research and simulation cache entry points and the current guarded runner. Done.
2. Write a strict transport-only scripted model using the agreed `translations` and `reviews` envelopes. Done.
3. Exercise the new core and actual consumers with all legacy production gates active. Done on the recorded thirteen-case snapshot.
4. Run fresh guarded mirrors, inspect receipts and source hashes, and record failures for the appropriate owner. Done; historical migration and fixture failures are retained below.
5. Freeze the owned tests and record exact acceptance and explicit limits. Done. Later coordinator source changes require the combined gate; they do not alter the owned test freeze.

## Initial findings and assumptions

The current ReportManager `generate_translation_variant` entry point already owns the publication lease, reads the real saved report, generates a sidecar, refuses changed source bytes and merges only translation metadata. The accepted production report fixture in `test_forecast_feedback_sdk.py` uses real stabilization, final audit, ReportManager save and immutable forecast-ledger registration; it can provide a real publication boundary without fabricating passing audits.

The simulation public endpoint supports visible-only texts and exact request/context binding. Research translation POST starts the real worker, and its GET exposes body and structured coverage. The test will keep those consumers real. Private mirrors and the existing guarded runner must contain imports and writes before application collection. Only the existing two child admissions may be used; a new unregistered child entrypoint will not be introduced.

## Verification and limits

No application imports, pytest, services, providers or saved-run operations have been performed by this worker in the shared checkout. Application imports and tests occur only inside fresh guarded private mirrors.

### First guarded snapshot

Root: `/private/tmp/drf-model-workflow-first-51zxrogh`. Completion receipt: `evidence/completed.json`; JUnit: `evidence/junit.xml`; all Python source hashes: `source-hashes.json`. Result: **4 passed, 4 failed in 4.68 seconds**, with no setup errors or deselections. Exit1, shutdown complete, identity preserved, source drift empty. The only guard events were the three declared storage redirects; no child was reached in this phase.

The four passing cases prove the shared core accepts the explicitly scripted equivalent amounts/dates with source/target/language-bound document receipts, rejects wrong units and negation after exactly one repair, and repairs only a structurally failing entry while retaining a good entry. They do not prove a live model can perform those judgements accurately.

The four consumer failures precede the owners' migrations: actual ReportManager generation enters `_protect_translation_tokens`; research fails before the new transport and cannot acquire a matching structured display; the source-race control has no model trace because it fails before acquisition; the simulation pair adapter enters the old protocol and rejects the strict new transport. These remain historical migration reds. The tests do not bypass the legacy guard or modify production in response.

The tested owned test SHA was `0480c0013faa4620f5295c30319e84a7a575c9362855047d5301e8e0ff9b6289`. Subsequent owned assertions also require native forecast-dashboard completeness and unchanged typed probabilities, horizon and binary ID; these need a fresh acceptance run.

### Migrated ReportManager snapshot

Root: `/private/tmp/drf-model-workflow-second-8sslhzr9`. The five core/report nodes passed in **3.40 seconds**; the three research/simulation nodes were deliberately unselected because the artifact adapters were still being written at snapshot time. This is an affected gate, not a whole-workflow verdict. Native ReportManager generation, audited sidecar publication, localized forecast reader, exact Markdown serving, separately loaded persisted manager, source-proof preservation and tamper409 all completed with legacy protection/repair methods forbidden. The next owned test delta also exercises the available-body POST's real asynchronous structured-display job and the actual report metadata/forecast API readers, retaining the accepted body/audit bytes.

### Joint migration and owned fixture correction

Root: `/private/tmp/drf-model-workflow-third-2n4yx08e`; result **6 passed, 2 failed in4.85 seconds**. The actual migrated report/display, source-race and simulation restart/tamper consumers passed. Both failures were the same owned fixture expectation: the strict scripted reviewer rejected an unchanged standalone English `## References` heading. A separate diagnostic root `/private/tmp/drf-model-workflow-diagnostic-s6nelygv` retained the exact section and verdict in `document-review-proof.json`; its one selected case failed, seven were deliberately unselected. That diagnostic omitted pyproject metadata and therefore also produced one unknown-marker warning; it is not a passing gate.

The fixture now translates that heading to the documented canonical Mandarin `## 参考来源`. The reviewer remains strict; unknown unchanged English prose is not relabelled complete. No production change was requested for this fixture error. Two new native research-API negatives also prove deliberately corrupted units and negation remain unavailable after one bounded repair, with no translated body file and a real PDF409. These controls expand the owned suite from eight to ten cases.

### Accepted owned snapshot and reader controls

The ten-case workflow first passed in4.41 seconds at `/private/tmp/drf-model-workflow-fourth-uheo83n3`, then passed in4.49 seconds against the newer core at `/private/tmp/drf-model-workflow-final-2i_r02e4`. The second snapshot's core matched after shutdown, but ReportAgent had advanced; those receipts remain tied to their tested bytes.

The coordinator then requested explicit forecast-reader controls. Three additional cases generate a real reviewed localized forecast and subsequently forge `complete=true` with a null receipt, an unchanged unreviewed source fallback, or a missing engine stamp. The actual forecast API must report incomplete localization without provider acquisition, retain canonical scenarios/probabilities/binary IDs/horizon, and continue serving the already audited Mandarin body. The unchanged fallback is allowed as a partial view; it cannot assert reviewed completeness.

**Final owned result:13 passed in5.00 seconds,0 failures,0 errors,0 skips,0 deselections.** Root: `/private/tmp/drf-model-workflow-reader-final-415u8jt8`. Receipt: `evidence/completed.json`; JUnit: `evidence/junit.xml`; reconciled manifest: `verification.json`; complete Python snapshot: `source-hashes.json`. Parent and child52373 each completed with exit0, shutdown complete, identity preserved and no source drift. Parent events are exactly three declared storage redirects plus one allowed guarded child. Child events are only the three declared storage redirects. There are no recorded blocked operations, external probes, socket or CLI dispatch attempts in this gate. The unchanged guard is a CPython audit-hook boundary, not an OS sandbox.

Receipt SHA256: `7e75a82df3f55de13ca715a3aa05bc2686e687be3046746398110ac0027aff00`.

JUnit SHA256: `5dc8d8a680834df846d05b2ea3986a13b385400962f4829b537a856ed7a240ba`.

The exact tested files below define this result. At post-shutdown reconciliation, the owned test and twelve other listed files still matched current bytes. `model_translation.py` and `report_agent.py` had advanced in the shared checkout, so this receipt is **not** assigned to those later bytes. The coordinator must include this unchanged owned test in final combined acceptance. No production finding is asserted solely from that expected concurrent delta.

| File | Tested SHA256 |
|---|---|
| `backend/tests/test_model_translation_workflow.py` | `d902ca8aaac1f31a91f87f10698e64a1afd234286d941f0cd2023bf78e9811f7` |
| `backend/app/services/model_translation.py` | `d9da39d7e35c3d0e6de8f9cf4577d7da979ec1f96065d4413d94556102d1336f` |
| `backend/app/services/report_agent.py` | `53c92e1f0f03b4d1b174ed3b1458f4f090b43cf8a8fe8bf00d3ff49a90ee864a` |
| `backend/app/services/translation_tools.py` | `9c607c0002f847031d6187c9353d4a0b51ab7e1ef37e49a5020856852f8a700f` |
| `backend/app/services/artifact_translation.py` | `cb3a960bbc65e7c3f03390d9b3b14100803c4206435003e3b416e269f0934d88` |
| `backend/app/api/report.py` | `3ab1ce237e1ccad4d094275a6b6b9492cd848c5853114d9047f1f1cd5105bca9` |
| `backend/app/api/research.py` | `58b65a7a6f64f47bbe1a1732620a83e3d364e97900c0312ae2409723745d57a3` |
| `backend/app/api/simulation.py` | `80e6376993f6aafd351aa7ad54f49526b28271fdedb01e25b99b1f2bc9bc8b8b` |
| `backend/scripts/main_offline_pytest.py` | `53fc29d5ec7657f31ade5265183e032dcfe54c8cea88d2e339ec905da14af2fa` |
| `backend/tests/test_forecast_feedback_sdk.py` | `65feee980bfa286d52836c37a57b2f75b7f2e6db25a03a554139038c47527fec` |
| `backend/tests/test_artifact_translation_restart.py` | `5320a95b415608fa94d4e05c791860450aa334372b740b1003dffa8a89e39b4c` |
| `backend/tests/fixtures/orphan_owner.py` | `72845575e4867695ae14247982e34c06e4730020f48b64a20ef8b8ce4761beaa` |
| `backend/pyproject.toml` | `e4122a0b20fa0842ee7abecaebf2272435015a4769b17362f59b159860b175dc` |
| `backend/requirements.txt` | `d6f9dae330f7716002a27282c9027ce4223bd1981ff48eef3af90a9d8599d091` |
| `backend/uv.lock` | `cd0148b549b0224e4450e570ab8c0126c156e049de10c62073d3be2acc0cd083` |

Command, from the recorded mirror's `repo` directory:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B \
  backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-model-workflow-reader-final-415u8jt8/evidence \
  --allow-python-script backend/tests/fixtures/orphan_owner.py \
  --allow-python-script backend/tests/test_artifact_translation_restart.py \
  -q backend/tests/test_model_translation_workflow.py
```

That evidence directory is immutable historical output; reproduction must use a new directory. The test reuses the existing admitted simulation restart script. It does not introduce a new child entrypoint or require any guard change. The first admitted orphan-owner script is not dispatched by this owned suite.

## Verdict, limits and integration handoff

The owned sidecar proves the exercised new default reaches actual managers, audits, publication barriers, source-bound caches and public Flask consumers without entering the old protection or repair helpers. It covers translated forecast fields and structured dossier fields with canonical typed JSON preserved; rejected meaning, changed source and tampered output remain unavailable or explicitly incomplete. Read-only report/research/simulation consumers do not acquire models. Simulation persistence is read in a real separate interpreter; report persistence is read by a separately loaded manager module, not a separate OS process. Both limitations are intentional and explicit.

This does not establish live model judgement accuracy, billing, latency, provider reliability, all Markdown extensions, browser rendering or whole-repository acceptance. The model transport and semantic verdicts are scripted, with exact fixture translations and deliberate refusal controls; semantic review remains a separate call to the same configured model. The coordinator's combined gate, independent review, frontend acceptance and any separately authorized live checks remain outside this owned worker's scope.

Only the two assigned new files were changed. No application/peer/guard/existing-test/Git/service/provider/saved-data mutation was performed. The coordinator may integrate these owned paths and include the new test in the final combined gate. No further owned edits are planned absent a concrete review finding.

## Updates

- 2026-10-23: Created this owned acceptance record before test implementation. Read the current guarded-verification and code-review skills and inspected existing native consumer fixtures. The shared checkout has unrelated peer edits; those remain outside ownership.
- 2026-10-23: Wrote eight cases in the new owned test file and ran the first frozen mirror. Preserved all four migration reds and the four core passes. Added explicit real localized-forecast reader assertions before the next snapshot. The transport supports both `.chat_json` and `.chat`, returning the same exact new envelopes; semantic review is explicitly a separate call on the same scripted model.
- 2026-10-23: Captured five green migrated core/report nodes in a second fresh mirror. Strengthened the scripted reviewer so unknown unchanged English prose is refused rather than silently labelled translated. Added native structured-display POST/poll and metadata GET assertions before the joint consumer run.
- 2026-10-23: Preserved the third joint result and the exact owned untranslated-heading diagnostic. Corrected only the fixture's heading and added two real research publication negatives. A fresh ten-case mirror is running with the existing two exact child admissions and unchanged guard.
- 2026-10-23: Ten scenarios passed in two fresh mirrors; retained dependency deltas explicitly rather than reassigning old receipts. Added the coordinator-requested null-receipt/forged-completeness/missing-engine actual API controls. Final owned thirteen-case gate passed in5.00 seconds; reconciled parent/child receipts and exact tested hashes, froze the owned test, and recorded the two later coordinator dependency deltas for final combined acceptance.

## Additional bounded corpus assignment

The coordinator accepted the frozen thirteen-case sidecar pending joint acceptance, then separately assigned only `test_report_bilingual_filter_safe.py`, `test_sessionb_translation_structure.py` and `test_sessionb_translation_reallm.py`. The assignment is test-only: migrate default-generation scenarios to the approved raw-model/review protocol while preserving meaningful structure, facts, code, PDF and historical direct-helper controls. The frozen thirteen-case test remains exactly `d902ca8aaac1f31a91f87f10698e64a1afd234286d941f0cd2023bf78e9811f7` and was not edited.

Baseline root `/private/tmp/drf-model-corpus-before-4isnykvw` retained **29 passes and6 failures in2.34 seconds**, with no setup errors. The failures were the obsolete default filter-partial publication/directive retry, old FRED masked transport, and two default slot/lint fixtures. Three other tests still reproduced a manually assembled obsolete auto sequence; they were green but did not exercise the new default and were migrated too.

The new default scenarios now require:

- Content-filter and ordinary provider exceptions produce explicit failed availability after a single raw call. They never publish a source-language partial or invoke the old directive ladder; the old filter knob cannot re-enable that ladder.
- Whole readable translations receive a separate fixture-known review. Raw FRED `25000 Millions of Dollars`, `20,000 millions of dollars` and month/year values reach the model intact and become the asserted equivalent `250亿美元`/`200亿美元` and Mandarin dates. Code/IDs/source data remain intact.
- Actual native report/research entry points retain parsed headings/tables/code/links/citations and exact accepted output. Old skeleton, protection, contamination and editorial-lint methods raise if the default tries to enter them.
- Dropped structure and echoed source prose receive exactly one repair of only the failing sections. A persistently introduced0.4 claim receives a negative semantic review and cannot acquire a receipt or available result.

The historical helper tests remain explicitly labelled compatibility coverage. AST comparison against the retained baseline proves **26 prior test functions are unchanged**:17 filter/helper/audit tests,7 structure/parser/PDF controls and2 direct impurity/protection controls. The existing shared PDF and rich-document fail-closed boundaries remain exercised. Fixture semantic review uses the separately supplied faithful renderer via `model_translation_fakes.model_protocol`, not the corrupt generation renderer as its oracle.

**Final relevant three-suite gate:36 passed in2.13 seconds,0 failures/errors/skips/deselections.** Root `/private/tmp/drf-model-corpus-green-5gqre1l_`; evidence at `evidence/`, complete hashes and AST preservation in `verification.json`. Parent exit0, shutdown complete, identity preserved, source drift empty. Events are only the three declared storage redirects; there are no child processes, blocked operations, external probes, sockets or CLI attempts recorded by this gate. Both existing exact child scripts were admitted but neither was dispatched.

All13 selected test/dependency/guard/fixture hashes matched current bytes after shutdown. Receipt SHA256: `fb3c1b186f448039a99193bdca352d64f71df96dede52e78f13696a87890d262`. JUnit SHA256: `c05c1eb10c60d184a4f4724b0d3396232d567c00b2e464a6ff129e0464677c4d`.

| Assigned test | Final SHA256 |
|---|---|
| `backend/tests/test_report_bilingual_filter_safe.py` | `11c3c79f41e258c1e34537bc02ee92064b4380ce93b7b668829eef1219cce534` |
| `backend/tests/test_sessionb_translation_structure.py` | `527544ecf58f1bbee9c355e4e120edaf3d6afb3fb01281faaafa3aa1fc09a32e` |
| `backend/tests/test_sessionb_translation_reallm.py` | `148f62c66ea94f0de268695ebcfa2164a88e6227607bf1baca90858b28ce1258` |

Tested production core `c637732bb7637e1ce83c9a0953c4d85148e1d03662b48868cc65c5cacdea2092`, ReportAgent `d92102817264963236f630ebde11e3999863a24b1bd3918412ad0af2e13fc5f7`, adapter `df75a4fedf2253bca20cebea96cbfe5d77fcf6704de12e08f56ec0d629dd0221` and shared fixture `0a7d922199236841af8aaff1acaf017ce5e26d56a7019a5ee7e263bd12fa637b` are listed in full alongside the other matched dependencies in the verification record. Later changes require the affected or final combined gate.

Run from a fresh mirror using the existing interpreter and unchanged guard, with the same two exact child admissions shown above, followed by these three paths and no `-k`, `--deselect`, skip or exclusion:

```sh
-q backend/tests/test_report_bilingual_filter_safe.py \
   backend/tests/test_sessionb_translation_structure.py \
   backend/tests/test_sessionb_translation_reallm.py
```

No application, peer fixture/helper, guard, Git, service, provider or saved-data files were edited. This does not expand the earlier offline/live quality limits or establish a whole-repository verdict. The three assigned suites are frozen and ready for the coordinator's final joint acceptance and independent review.

- 2026-10-23: Completed the bounded additional corpus assignment, preserved the original6-failure baseline and all26 direct historical controls, and reconciled the unexcluded36-case green gate against all13 current hashes. The previous frozen thirteen-case consumer test remains unchanged.
