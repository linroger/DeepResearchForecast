# OS-1 provider implementation

Status: Provider implementation and scoped guarded verification complete, 2026-10-18. Integration acceptance remains coordinator-owned. Owner writes are limited to `news_signals.py`, `news_tools.py`, `test_news_signals.py`, and this record. The approved `integration-contract.md` is authoritative; the coordinator maintains the shared handoff.

The implementation preserves provider statuses, snippet provenance and context-only eligibility. A safe run-local store will bind query identities to immutable captures, share admission across threads/processes, and fail closed for malformed or tampered present generations. NewsAPI uses a header credential and a two-request generation cap; Reddit remains independently off by default. Optional tone is omitted.

Acceptance checks cover injected NewsAPI responses, bounded request/response behavior, replay/sealing, changed identity, tampering, safe paths, merge/render and legacy wrappers. Tests must run through `backend/scripts/main_offline_pytest.py` using the original provisioned interpreter, after `scripts/oddsense_source_mirror.py` prepares a fresh exact-source mirror. Evidence roots use canonical `/private/tmp`; the existing guard remains unchanged. No live provider, credential, saved-run, service, package or Git mutation is part of this work.

The test file is delegated with a disjoint write scope; no test/app import occurs outside the guarded mirror.

## Progress and evidence — 2026-10-18

The public implementation and legacy wrappers are present. The delegated worker left a 58-case provider suite before a transport/DNS failure. That child was stopped; ownership of its sole test path returned to this worker. The first guarded execution exposed an incompatible storage operation: opening `/` was blocked as an external read. The store now pins and verifies the closest existing trusted directory inode and uses no-follow relative operations for descendants. The guard was not changed. That first receipt (`/private/tmp/oddsense-providers-red-20261018-01`) has blocked attempts and is not accepted as clean or behavioral red.

The next exact-source run (`/private/tmp/drf-oddsense-providers-check2-ubmyop_f`, evidence `/private/tmp/oddsense-providers-check2-20261018-01`) reached all scenarios: 57 passed and one renderer attribution test failed because the kind string's underscore was escaped in raw Markdown. This is meaningful renderer red evidence. Thread and guarded child-process scenarios passed, covering exact-query singleflight and the shared two-request cap.

Coordinator feedback corrected full-question identity hashing (provider queries alone remain capped at 500 characters), fixed the lookback hard limit to 30 days, and preserved market request counts, quote units/basis, outcome labels, settlement rules, raw source-price fields and provider evidence hashes. A separate `normalized_sha256` hashes the final normalized row excluding itself and citation-only `source_ref`; `evidence_sha256` retains a supplied provider hash. Temporal limitations are explicit metadata and do not change the required context-only eligibility flags. Seven additional scenarios cover those seams, master-off no-write behavior, legacy wrappers and endpoint allowlisting.

The approved merge key includes item identity AND capture identity. The inherited test's item-only dedupe expectation was corrected to preserve distinct lane captures, as required by the frozen contract. Input captures and their local citation references remain unchanged; merged output strips lane-local references for final remapping. The research engine annotates a presentation copy with citation references, so rendering checks bounded schema while durable loading/sealing always verify the stored digest.

A subsequent guarded focused regression captured five behavioral failures for English/Chinese aliases (`/private/tmp/oddsense-providers-alias-red-20261018-01`). Requests and cached/reopened identities now share normalization to `en`/`zh`, including Chinese script labels and `zh-CN`. The renderer retains the validated enum name visibly without escaping its internal underscore. Locks now respect caller/configured deadlines; metadata-only directory traversal stays inside the existing guard. A client also remembers its bound generation: deletion or a generation replacement cannot cause that live client to reacquire silently. Master-off sealing returns existing proof without writing.

The 70-case focused gate passed on mirror `/private/tmp/drf-oddsense-providers-green1-f_86hqlw` in 2.61 seconds, evidence `/private/tmp/oddsense-providers-green1-20261018-01`. Its completed receipt records identity preserved, no source drift, no blocked events and eight allowed guarded children (all exit 0). This is fixture proof, not live provider compatibility.

The coordinator's first combined gate used exactly the same provider/test hashes but reproduced lock-file open failures in both process tests (`/private/tmp/drf-os-joint-first-20261018-1`): 148 passed, two failed. Failed child receipts have empty guard-event maps, so these failures were not blocked operations. The open path now retries only `BlockingIOError` within the same caller/configured deadline, retaining no-follow and regular-file checks; other OS failures fail closed with an errno code. Deterministic tests inject this transient open condition and deadline exhaustion. Additional checks cover deletion of a bound capture, master-off preservation of an existing unsealed file, and opted-in Reddit 403/429 replay. A combined fresh-source rerun is in progress.


## Final verification and handoff

The combined fresh-source gate passed **160 tests in 5.61 seconds**, including all 76 provider/store scenarios, actual research-engine consumer scenarios, OS-2 fixtures and downstream pipeline/report checks. Mirror: `/private/tmp/drf-oddsense-providers-joint-green3-hi02hr9a`. Evidence: `/private/tmp/oddsense-providers-joint-green3-20261018-01/{started.json,completed.json,junit.xml}`. The mirror's `oddsense-source-manifest.json` freezes all copied source hashes. The completed receipt records zero blocked events, eight explicitly allowed guarded children (all exit 0), no source drift and preserved system identity. This fixes and supersedes the earlier lock/deadline failures; the earlier receipts remain historical evidence.

The exact command, run with the mirror as the working directory, was:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/oddsense-providers-joint-green3-20261018-01 -q backend/tests/test_news_signals.py backend/tests/test_news_research.py backend/tests/test_market_intelligence.py backend/tests/test_news_context_pipeline.py backend/tests/test_news_context_reports.py
```

Final owned source hashes (also AST-parse clean):

| File | SHA-256 |
| --- | --- |
| `deerflow_bridge/news_signals.py` | `bcc801907a5735b3ad0771301cce5486edb3b0bb943d87347f978945c009c5de` |
| `deerflow_bridge/news_tools.py` | `a0ee232160113bd88c7418637cb7bd50db40951edcad5c2e4e38e78af6af592c` |
| `backend/tests/test_news_signals.py` | `ac68b48eeaacabc6365ccaaaa7db27c86cdb9952238537cca470a6d11e54b90b` |


`news_signals.py` implements every frozen public symbol. Constructor-only transport/control injection is additive; legacy wrappers expose only query text and obtain the trusted cached client. Both package and bare imports are supported. No required API amendment was needed. The child test worker was stopped after its transport failure; no new agent was spawned afterward. The provider's four owned files are ready for coordinator review, and no further source writes are planned.

No live provider operation, provider plan/access assertion, paid model execution, package installation, saved-run access, service restart, credential read by this session, or Git mutation occurred. Runtime credential consumption exists only in the implementation and was exercised with synthetic injected fixture values. Optional tone is deliberately omitted. Optional Reddit remains off unless explicitly enabled. Final integration acceptance, independent review, deployment/configuration and project-level documentation remain with their designated owners.

Next-session prompt: Read the approved integration contract and this evidence record, verify these three source hashes against the recorded mirror, then run coordinator-owned end-to-end and independent review gates. Preserve owned boundaries and retain the original failed receipts. Do not infer live provider compatibility or production readiness from these offline results.

## Additional integration finding — awaiting coordinator amendment

After the 160-case green gate, the coordinator identified that legacy track angles intentionally change lane question text. Strict merge correctly rejects unequal question digests, but those lanes need a trusted shared parent question identity. The proposed internal `NEWS_CONTEXT_QUESTION_SHA256` binding is awaiting the coordinator's frozen-contract amendment. No identity override or relaxation of merge validation has been implemented yet. Once approved, provider/cache identity can honor only a validated parent digest; absent override retains full direct-CLI question hashing. Research's explicit identity check and backend child propagation must change in their respective owned paths, and the resulting bytes need another guarded gate.

## Review amendments in progress

The coordinator formally amended `integration-contract.md` to authorize shared parent-question lineage, atomic `capture_market(provider, query, acquire, *, deadline=None)`, monotonic sealed proof, and full bounded quote-contract presentation. The provider implementation now follows that amendment; the exploratory method name `capture_external` was replaced before integration. The trusted callback receives `reserve_network() -> {allowed, state, reason}`. That callback owns existing research-network admission and writes each shared four-request market reservation before HTTP; adapters must not double-charge it. The store checks replay/seal/query limits before acquisition and retains interrupted pending results after abrupt process death. No second persistent state owner was introduced.

Before the repair, three meaningful review scenarios failed (`/private/tmp/oddsense-providers-review-red-20261018-01`): restoring a valid same-ID unsealed predecessor, replacing it with valid resealed same-ID evidence, and rendering stored market quote/contract fields. A warm client now pins the first observed sealed digest, while allowing legitimate concurrent changes while gathering. Shared rendering now includes explicit outcome, bid/ask/last, quote/probability basis, quote/volume units, known or unknown quote time, rules, horizon and thresholds. The backend has a separate validated renderer and owns matching its presentation.

New tests exercise validated parent identity across angle lanes and foreign-parent rejection, each durable pre-I/O reservation, replay, full-query/sealed rejection before callback, existing research-budget denial, real separate-process identical/distinct-query admission, and a deliberately abrupt guarded child exit after two physical fixture requests. The latter must retain both interrupted replay and spent allowance. A fresh provider review gate is running; earlier green hashes do not cover these new bytes.


## Final amendment verification — 2026-10-18

The final provider-only gate passed **95 tests in 4.13 seconds** on exact-source mirror `/private/tmp/drf-oddsense-providers-final-ym2n_ia6`, evidence `/private/tmp/oddsense-providers-final-20261018-01`. `completed.json` records exit 0, identity preserved, no source drift, and no blocked events. There are 17 explicitly allowed guarded children: 16 exit 0; the crash-recovery fixture deliberately exits 23 after two durable market reservations. This is an exercised failure/control and is not relabeled a successful child exit. Its interrupted capture replays without new I/O and its spent allowance remains charged. `junit.xml` identifies all 95 scenarios.

This gate supersedes the earlier three-file hashes for provider acceptance. All three source/test files AST-parse and match the final mirror byte-for-byte:

| File | Final SHA-256 |
| --- | --- |
| `deerflow_bridge/news_signals.py` | `db8e964fdd78d96a0b265bb245fcf83b86395a5db8079e859a8475d2f4607225` |
| `deerflow_bridge/news_tools.py` | `a0ee232160113bd88c7418637cb7bd50db40951edcad5c2e4e38e78af6af592c` |
| `backend/tests/test_news_signals.py` | `b922ae12409f6dc8ba2b012b7e3d0ea82418eeeeb88c67b1c911239cf7ba3a83` |


The wider current integration run (`/private/tmp/drf-oddsense-providers-review-green2-87cj7_5o`, evidence `/private/tmp/oddsense-providers-review-green2-20261018-01`) has **189 passes / 7 failures** on its own earlier freeze. All 93 then-current provider/store scenarios passed. Failures were five market adapter/fixture replay expectations, one downstream truncated-table check, and one full workflow quantitative-grounding/stabilization gate. Those paths remain with their assigned workers; this worker did not modify their files or relax those gates. The receipt records 22 allowed guarded children, no blocked events, no source drift and preserved identity. This is not a successful overall integration verdict. Coordinator should rerun the affected final consumers and obtain final independent review after those owners finish.

Provider scope is now implemented and independently reviewable under the formal contract amendments. Strict foreign identity/cutoff/language checks remain. A current or reopened client pins observed sealed digest, and even an early client that first replays another client's capture binds that generation before future deletion. No arbitrary `record_result` overwrite was added. `capture_market` is the shared pre-I/O owner; callback transport receives `{allowed, state, reason}` and must honor it once for every physical HTTP request. Provider `evidence_sha256` is retained separately from the normalized row digest. Publisher native identity, units, literal outcomes, rules, horizon, unknown quote time and context-only eligibility survive normalization and shared rendering.

The three source/test files are frozen at the hashes above for coordinator integration and reviewer recheck. This documentation file is the fourth and final owned file. No further provider source changes are planned without a concrete integration/review finding. Optional tone remains deliberately omitted. All previous scope boundaries remain in effect; no Git mutation, service restart, runtime/saved-run access, installation, live provider, paid model or actual credential access was performed.

## Concrete migration finding — provider freeze reopened

The market owner's 65-pass/one-failure gate found that old captures can retain `network_requests=3` without `request_count`. The shared migration previously summed only `request_count`, recovering spent allowance. The store now takes `max(valid request_count, valid network_requests)` separately for each market capture, sums those non-overlapping capture counts, then takes the maximum of that sum and the existing shared counter. It does not add old/new representations together. Valid counts are non-negative integers with booleans excluded; an invalid present shared counter fails closed instead of resetting. All pre-I/O reservation, replay, sealing, query and deadline behavior remains with the same owner.

The exact production migration regression was captured against a fresh pre-fix source mirror. Eight additional provider scenarios cover old/new count disagreement, equal representations without double charging, missing/invalid legacy counts and retention of an existing higher shared counter across restart. Targeted and full shared provider/market gates are in progress on a fresh post-fix mirror; the previous frozen provider hash is historical until the new receipts and hash are recorded.


## Migration closure and final source freeze — 2026-10-18

The exact legacy-network-count regression failed before the fix with two new physical fixture calls instead of one (`/private/tmp/oddsense-providers-migration-red-20261018-01`), then passed on the fixed bytes (`/private/tmp/oddsense-providers-migration-target-20261018-01`: one passed, 52 deselected). Full shared validation passed **214 tests in 11.12 seconds**, including all provider/store, market, research, pipeline, report and E2E suites. Mirror: `/private/tmp/drf-oddsense-providers-migration-green-egfg33up`; evidence: `/private/tmp/oddsense-providers-migration-shared-20261018-01` (`started.json`, `completed.json`, `junit.xml` and child receipts). The mirror manifest freezes all copied source identities.

The shared completed receipt confirms exit 0, no blocked events, no source drift and identity preserved. Guarded subprocess controls include deliberate crash exits; these are expected negative scenarios, not successful child exits. Individual child statuses remain in the unmodified receipt. No guard was weakened. The full six-suite command was:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/oddsense-providers-migration-shared-20261018-01 -q backend/tests/test_news_signals.py backend/tests/test_market_intelligence.py backend/tests/test_news_research.py backend/tests/test_news_context_pipeline.py backend/tests/test_news_context_reports.py backend/tests/test_oddsense_workflow.py
```

Final frozen owned source/test hashes, verified byte-for-byte against that mirror and AST-parse clean:

| File | SHA-256 |
| --- | --- |
| `deerflow_bridge/news_signals.py` | `ffc7a2d720bf3943116d4a3ff0636ce77b1134b743b82c361a9af4e8f88e0d45` |
| `deerflow_bridge/news_tools.py` | `a0ee232160113bd88c7418637cb7bd50db40951edcad5c2e4e38e78af6af592c` |
| `backend/tests/test_news_signals.py` | `75eec3560cc7e8ae6be93bd64ff53e1453253a276113cd496891b048a68c9fc6` |


This final receipt supersedes the previous provider freeze for the concrete migration fix. Provider implementation, amendment fixes and guarded shared verification are complete and ready for coordinator-owned final broad regression and independent rereview. Production/test bytes are frozen; no cosmetic rewrites, additional scenarios, Git changes or out-of-scope operations follow this handoff.

## Legitimate engine identity transition — API coordination

The final joint gate identified a distinct lifecycle case: v3 archives its old work directory after a validated input identity change but leaves the old root contextual capture and process-cached client. Strict provider identity then correctly refuses the new question, making a legitimate engine transition fail. This must not be fixed by weakening context identity, accepting corrupt/missing consumed proof, or resetting an existing bound client.

The proposed narrow API is `retire_context(artifact_dir, archive_dir, *, previous_identity, next_identity)`. It should validate the archived engine state and its old context binding, require a real validated identity change, preserve exact valid proof in that archive before removing the active root file, and evict the active cached client only after success. References to the retired client stay invalid. The coordinator/research owner must freeze the signature before implementation. Resume, unreadable/corrupt state, corrupt context, missing consumed proof, foreign identities, unsafe paths and archive conflicts remain fail-closed controls. Production/test bytes remain at the migration freeze while this API is coordinated.

The coordinator froze amendment 5 as `archive_context(artifact_dir, archive_dir, *, expected_generation_id, expected_sha256) -> dict`; this supersedes the earlier proposed signature. The trusted engine validates genuine identity change and its old state/binding before calling. The provider verifies the exact expected capture under the existing root lock, requires an existing archive directory strictly beneath that root, and uses descriptor-relative no-follow hard-link/unlink as a no-clobber move. The archive entry is fsynced before the active entry is retired. No existing destination is overwritten; failed pre-retirement moves remove only the newly created link and preserve the original regular proof and cache registration. Only successful archival evicts the old registration and marks that old cached object retired; no old identity or generation is reset. Old noncached objects retain their strict generation/identity binding.

Eleven focused scenarios cover exact old proof/state bytes, new client/generation and actual injected acquisition, old-reference rejection, wrong bindings, corrupt/missing source, destination conflicts/symlinks, invalid archive paths, and rollback after an injected source-unlink failure. The old proof is never accepted as a way to recover corrupt or unchanged resumed state. Research owns the context-ON engine transition and its negative controls.

## Archive API ownership handoff

During a final ownership rebalance the coordinator requested source ownership of `news_signals.py` while the already-authorized implementation write was becoming visible. That write completed before the freeze; there are no provider source writes in flight. The coordinator confirmed it will review/test the existing implementation as-is, without duplicating or reverting it. Provider source files are now coordinator-owned and frozen here; this worker retains only the provider test/evidence document for completion.

The visible `news_signals.py` SHA-256 is `3d17443bf7f7bceb710d0108fd247b79f46d856a64750a4c884e94afa06ed107`, with `archive_context` at line 387. `news_tools.py` remains `a0ee232160113bd88c7418637cb7bd50db40951edcad5c2e4e38e78af6af592c`. The focused archive gate passed **11 tests, 103 deselected**, in 1.37 seconds: mirror `/private/tmp/drf-oddsense-providers-archive-check-o3jb15_o`, evidence `/private/tmp/oddsense-providers-archive-check-20261018-01`. This worker will not edit either source file without an explicit coordinator finding/reassignment.

A fresh shared gate now includes the actual research context-ON changed-question scenario and all historical v3 checks alongside provider, market, pipeline, report and workflow suites. Its frozen mirror is `/private/tmp/drf-oddsense-providers-archive-shared-hh3hwepu`; evidence is `/private/tmp/oddsense-providers-archive-shared-20261018-01`. These receipts, rather than the earlier source freeze, establish the archive API's integrated behavior.


## Final archive and lock-order acceptance — 2026-10-18

The shared archive gate passed **277 tests in 14.84 seconds**, including the actual context-ON changed-question scenario and historical v3 suite: mirror `/private/tmp/drf-oddsense-providers-archive-shared-hh3hwepu`, evidence `/private/tmp/oddsense-providers-archive-shared-20261018-01`. Its receipt records no blocked events, no source drift and preserved identity. This receipt applies to the landed archive implementation before the coordinator's subsequent lock-order correction.

The coordinator then accepted the archive API and repaired a concrete lock-order inversion in `get_context_client`: obtain the per-root lock before brief cache access, and do not hold the global cache lock during snapshot/file I/O. This worker did not edit either source file after the ownership rebalance. Two focused concurrency tests now require another root's client lookup to finish while the first root performs context I/O, for both fresh and cached first-root clients. They directly guard the reported global-cache serialization/deadlock condition.

Final current-source acceptance passed **15 tests, 164 deselected, in 3.02 seconds**. The selection includes all eleven archive controls, both cache concurrency controls, the actual context-ON changed-question/new-acquisition/old-client-rejection scenario, and the historical v3 changed-question archive check. Mirror: `/private/tmp/drf-oddsense-providers-lockorder-acceptance-wviq2tp2`. Evidence: `/private/tmp/oddsense-providers-lockorder-acceptance-20261018-01/{started.json,completed.json,junit.xml}`. The completed receipt records exit 0, no blocked operations, no source drift and preserved identity. The command was:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/oddsense-providers-lockorder-acceptance-20261018-01 -q backend/tests/test_news_signals.py backend/tests/test_news_research.py backend/tests/test_research_engine_v3.py -k 'context_archive or changed_question or different_question or client_lookup_does_not_hold'
```

Current source/test hashes, matching that exact mirror:

| File | SHA-256 |
| --- | --- |
| `deerflow_bridge/news_signals.py` | `dc0dca47e0dc1c2d07878eb1a851c0c37a9b0c968a80b009e6fcbc97002f287b` |
| `deerflow_bridge/news_tools.py` | `a0ee232160113bd88c7418637cb7bd50db40951edcad5c2e4e38e78af6af592c` |
| `backend/tests/test_news_signals.py` | `fc1dd9a5e69cfed2cc5408a9933a61eb32d54e3286e1ab83f1e2cfe71c25185e` |


Provider source remains coordinator-owned. Provider tests are frozen at the hash above; this document is the only final working-record edit. No further code/test changes are planned without a coordinator finding. Final broad regression and independent acceptance remain coordinator-owned, and the earlier receipts remain historical rather than evidence for later bytes. No Git mutation, package installation, saved-run access, actual credential access, provider/model execution or service restart occurred.

## Coordinator final integration disposition

The final accepted source and receipt matrix is authoritative in final-verification.md/json. Historical worker freezes and remaining-work statements above apply to their dates only. All approved OS-1/OS-2/OS-3 implementation and concrete independent review findings are now closed; subsequent coordinator report/language/UI deltas have their own recorded affected tests/review. The complete matrix has1397pass/2existing skips, the final affected92 and bilingual61 pass, and the final UI187/build/visual gate passes. Remaining external limits are explicit provider access, deployment/live-model evaluation and Git authentication—not missing approved code. No historical receipt hash was reassigned.
