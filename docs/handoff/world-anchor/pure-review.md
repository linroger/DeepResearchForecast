# Independent pure World Anchor review

Last updated: 2026-10-30. Branch: `codex/world-anchor`. Base: `9916b3be`.

Status: Bounded pure review closed at projection freeze `c85ce260…`, with dedicated tests `2de1211c…`. The research-note projection follow-up is closed by the exact-source rereview below. PR1–PR3, the retained-currency remainder, and the parent-side selected-budget join remain closed; their implementation is untouched. Historical source pins and earlier closures below remain dated evidence, superseded by this new projection pin where applicable.

## Projection follow-up and closure, 2026-10-30

On module `1b90d45e42dbc2cf52b9d0b83dbb001f9aff13c5ccb78e0fccab7037f6d87df6`, `engine_projection` selects requirements by engine alone at lines 4421–4425, then adds their dependencies without checking the `research_note` role at lines 4427–4432. Bound research-only requirements can consequently enter the privileged engine projection when another requirement makes that engine ready. Mechanism, hazard, indicator, identity, and calendar descriptor selection also needs a consistent boundary so a later dependency or descriptor path cannot restore non-executable research notes.

Pauli preserved two failing actual publication/runtime regression cases and Maxwell made the narrow pure-source repair. The reviewer subsequently inspected those unchanged tests and their durable red/green evidence, without importing or rerunning the application paths. The earlier research-inventory checks covered a wholly blocked no-contract pack; they did not establish note exclusion from a mixed ready pack. That coverage gap explains why the prior pure closure missed this behavior.

The rereview checked direct selection, transitive dependencies, descriptor references, and preservation of valid executable evidence against these exact pins:

| File | Projection closure SHA-256 |
|---|---|
| `deerflow_bridge/world_anchor.py` | `c85ce260bb8309019c86efdcdf5ffdffcd1c7ca580cb0c250a56b7fd4a6ae231` |
| `backend/tests/test_world_anchor.py` | `2de1211c263ffb6136354bf19cb04bf2d1f28718b3239a65a559b8d7e5060086` |
| `backend/tests/test_world_anchor_target.py` | `45ef8aaebeb45db4dcdc6159be807a710ba09400b5a7fca1dc92c8786d6c0c2b` |
| `deerflow_bridge/world_anchor_case.py` | `ddaba728b5243a51a3e3a205c319eececa0c0053045282a7e0937903f2a96aac` |

The reviewer independently compared the retained `1b90d45e…` source with the frozen candidate. Only `engine_projection` changes by AST; all other module statements and function signatures are unchanged. This independently confirms the retained [scope check](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-note-freeze-28-envelope/scope-check.json), so PR1–PR3 and the renderer/private-inventory code do not require reopening.

Direct engine selection now excludes `research_note` consumers. Dependency traversal stops at research-only requirements and does not inherit otherwise unrelated evidence through them. Mechanisms require an allowed consumer and projected parameter, lag, and applicability origins. Identities require both a retained mechanism and projected basis; calendar, hazard, and indicator descriptors similarly require their relevant projected origins and permitted consumers. Bound observations and source references are derived only from the resulting binding set. Research notes remain in the immutable analyst pack, while independently required executable dependencies remain available.

The reviewer inspected these durable envelopes, their output/JUnit/completion receipts, and their four retained core/test/adapter source copies:

- [Actual-path red25](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-note-red-25-envelope/verification.json): two behavioral failures on unchanged Pauli cases, for `actor_free=False` and `actor_free=True`.
- [Pure red26](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-note-pure-red-26-envelope/verification.json): nine behavioral failures across the three engines for direct/dependency exclusion and descriptor exclusion.
- [Frozen green28](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-note-freeze-28-envelope/verification.json) and [JUnit](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-note-freeze-28/junit.xml): 32 passes, 189 deselected, no failures/errors/skips; 7.877 seconds of JUnit runtime and 8.129 seconds of process wall time. The actual-path cases publish, reload through the host, and execute the existing runtime while preserving notes in the private pack, excluding note authority/actor observations, and retaining the expected target result.

All three envelopes contain 128 matching before/after source pins and report no source drift. They retain four source copies each, not copies of all 128 pinned files; the reviewer verified every retained copy against its pin. All 128 green28 pins also matched the live checkout at the closing rehash. Pauli's full target test file and adapter hashes are unchanged across red25 and green28. The pure negative test functions are AST-identical from red26 to green28; their shared fixture only gains an opt-in `executable_dependency=False` argument and branch for the additional positive control. The final gate includes valid dependency/descriptor controls and existing research-inventory, target privacy, native actor authority, and intermediate-identity controls.

The reviewer also executed twelve narrowly selected pure fixture controls entirely in memory: direct exclusion, dependency exclusion, independently required dependency preservation, and descriptor exclusion for each of `oasis-legacy`, `world-v1`, and `target-first-v1`. All passed. Fixture writes were redirected to the existing in-memory path map; no application imports, provider calls, filesystem test writes, or duplicate application gate occurred. Core/test pre/post hashes matched the frozen candidate.

**Disposition:** The projection follow-up is closed for the four exact pins above after the closing rehash. The earlier independent pure and parent budget closures remain valid within their documented scopes. Only `docs/handoff/world-anchor/pure-review.md` was edited by this reviewer.

## Prior closure and source pins

The reviewed checkout remains `codex/world-anchor` at base `9916b3beff6753cd07f2407f36428ca2030127fd`, with concurrent implementation changes preserved. Closure covers the pure evidence/admission/rendering boundary and the specifically reviewed parent budget join. It does not establish complete application integration, live model/provider qualification, private child-process execution, deployment, or forecast accuracy.

| Final reviewed file | SHA-256 |
|---|---|
| `deerflow_bridge/world_anchor.py` | `1b90d45e42dbc2cf52b9d0b83dbb001f9aff13c5ccb78e0fccab7037f6d87df6` |
| `backend/tests/test_world_anchor.py` | `51dd3e8c2b4905b367ea8265b45757ca41b74e30d1602ccf4d15ec1cd2486f31` |

The final independent rehash matches these exact pins and the private harness's before/after pins. Publication and host files also retain the parent closure hashes listed below. Any later relevant source change requires a bounded rereview of that change; this approval does not float to new bytes.

PR1 now reconciles immutable authority/limits, monotone retained vectors, transport floors, and all five retained budget components. The selected raw budget must cover the retained currency maximum as well as the attempt/token counters. The parent separately authenticates the selected budget's canonical identity against the real ledger exit. PR2 enforces accepted evidence classes from authenticated source/native-claim provenance. PR3 authenticates retained prior basis/hash/pointer/value/library projection and enforces the required value type and permission for assumptions. Independent probes, current retained negative controls, and relevant positive controls support closure.

The reviewer inspected the final 114-case candidate gate and the separate two-case private gate. These are two owner-executed guarded runs, not a newly executed 116-case composed gate. The candidate gate reports 114 passes; the private gate reports two passes with no failures/errors/skips and 2.363 seconds of JUnit runtime (2.614 seconds of process wall time). The private [completion receipt](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-private-freeze-24/completed.json), [JUnit](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-private-freeze-24/junit.xml), and [verification envelope](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-private-freeze-24-envelope/verification.json) retain the exact invocation, guard boundary, source/input pins, stdin identity, and timing. The guard records completed shutdown, no source drift, and only the existing config/logger redirects.

The durable [private runner](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-private-harness-20261030/run_private_gate.py) hashes to `76449b425a5183b9001b5184a472b495a41bf5bb562bf75fca67912cea1621ab`. The reviewer read it and executed only its read-only verification/payload functions, without launching the gate. All 108 manifest members, all 109 package members, and the complete 95 raw files match the original envelope before/after map. The original manifest remains `9dfa2f0861a6133d174d06fd76d850e3ef4404c0775572721db04f81569c3f27`; the package seal remains `2ce833dadd4edbbaaad6692bfe2258aa2954383ff03193e6d71a47891b35ef39`. Reconstructed stdin was exactly 796,348 bytes with SHA-256 `030c042cf7e60634e6579d8c46d5acfd109c38b6c7b665dddad94c83a32e0c82`, matching the retained invocation.

The retained private outputs were also inspected directly. The full corpus inventories 212 rows (116 KIQ facts, 52 quantitative rows, 24 timeline rows, and 20 actor rows), 201 sources, 34 fetched pages, and 167 snippet-only sources. Without a typed contract it has zero observations/variables/requirements and all three engines blocked. S107's separately reviewed scripted fixture preserves 247.5 as a 2026 third-party forecast, with unknown publication and the original capture time as known-by. A distinct no-contract pack retains all five 2026 forecast revisions—239.8, 244.2, 246.2, 248.2, and 247.5—with zero variables/requirements and all engines blocked. None becomes observed state or a five-period growth history. The scripted review receipts establish offline boundary behavior, not live semantic qualification.

Only this review document was edited by the reviewer. No production/test edits, application imports, provider calls, broad tests, duplicate parent gate, commits, or further delegation were performed.

## Scope and method

This is a bounded independent review of `deerflow_bridge/world_anchor.py`, its retained dedicated tests, and the receipt/publication callers needed to understand the pure boundary. The reviewer may edit only this document. No production or test files, provider calls, application imports, broad test runs, commits, or other agents are part of this review.

The review follows `PLANS.md`, `contracts.md`, and `handoff.md`. It checks source/track/SID identity, exact UTF-8 passages, independent review authentication, typed support, availability and actor visibility, qualitative collections, research-only output, retained spending evidence, human provenance, and immutable emission/replay. The initial pass began while the renderer and specimen gates were still in progress. Their final implementation and evidence were subsequently reviewed before the closure recorded above.

The first reviewed source SHA-256 is `05005a0f6bdb41f3c160e52a52689c0ecf509cc71910a3793d1dc84e88c1e151`; the dedicated test SHA-256 is `83005fc7f0b789fa3a0fa91f53639240bd6b7a379b1a17d183bf7510497a863e`. These are interim pins, not a final freeze.

The closing rehash for the initial interim pass matched both complete hashes above. The runnable appendix also reproduced PR1–PR3 with identical module/test hashes before and after execution. Those original findings apply to that earlier source. The final disposition above supersedes the interim hold after the repairs, renderer, and private evidence were reviewed.

## Findings and original reproductions

### PR1. Retained accounting can select an older, smaller receipt

Priority: P1. At the interim source, `attach_producer_receipts` validates each budget separately and only reconciles the budget scope. `_metering` at lines 2228–2253 validates all receipts but compares pack totals only with the summary whose artifact ID and hash the caller selects. It does not require that selected summary to cover other attached retained budget counters.

The reviewer reproduced this using the current `make_fixture` and `budget_receipts_fixture` helpers with all fixture filesystem operations replaced by an in-memory byte map. Two externally pinned, same-scope receipt handles retained `(model attempts, tokens, catalog attempts, follow-up attempts)` of `(1, 1000, 0, 0)` and `(3, 3000, 2, 1)`. Both attached successfully, and `admit_bindings` accepted the older meter, emitting `(1, 1000, 0, 0)` while retaining the newer receipt too. No application or provider was imported or called, and the probe wrote no files.

This understates retained costs on the pure replay/attachment interface. The current binder normally emits one final bundle, which narrows its immediate production reach but does not repair the public multi-bundle contract. A bounded remedy is to reconcile immutable budget identity/limits across all attached receipts and require the selected final summary to cover the cumulative retained counters. A regression should also reject conflicting lower caps and preserve identical/idempotent attachments.

**Parent implication, checked at the coordinator's request:** A pure retained floor alone cannot detect a publication containing only an older budget bundle. `backend/app/services/run_spending.py:391–414` authenticates the whole completion object against the ledger exit proof but persists only `completion.artifact_manifest_sha256`. `backend/app/services/world_anchor.py:135–150` then accepts the completion manifest without joining the selected pack budget to `completion.budget_receipt_sha256`. The spending core's `finish_anchor_scope` at `deerflow_bridge/run_spending.py:1531–1540` authenticates the latter against the current ledger seal; it does not inspect the publication's selected budget artifact.

The parent should resolve the exact producer summary selected by `pack.metering.receipt_artifact_id` and `receipt_hash`, resolve and hash-check that summary's `budget_receipt_artifact_id` and `budget_receipt_hash`, and require the decoded budget's canonical spending hash to equal the ledger-authenticated `completion.budget_receipt_sha256`. The raw artifact hash and canonical ledger hash are separate checks if noncanonical JSON is allowed. Require matching pipeline/scope/session identity and metered mode even for a zero-call bound scope. Perform this validation before promoting the lifecycle to ready, and retain the authenticated expected budget pin if acceptance happens after handoff adoption. Do not select a receipt by filename alone or accept an unrelated bundle merely because it contains the expected hash.

A focused parent regression can publish a valid pack containing only an older budget receipt, finish the ledger scope with the actual current seal and that publication's manifest hash, then attempt adoption/acceptance. It must fail the selected-budget join. A second regression should include both old and current receipts but select the old one. This is a static cross-boundary finding plus the independently reproduced pure rollback; no application or ledger operation was executed by this reviewer.

The coordinator accepted ownership of that parent correction on 2026-10-30. The implementation plan below was subsequently verified by the narrow parent-side rereview recorded in its own section. That closure does not close the separate pure retained-currency remainder.

### PR2. Accepted evidence classes do not constrain binding

Priority: P2. `_mismatch` at lines 2068–2091 checks identity, value kind, and value type but never checks `Requirement.accepted_evidence`. No subsequent binding check enforces that field.

The reviewer changed only the fixture's baseline contract to `accepted_evidence=["official_row"]`, regenerated its authority bytes, manifest, requirements, and source index, then ran the fixture's usual independently authenticated scripted page review. `admit_bindings` returned a bound baseline backed by `retention=fetched_page`, although no official observation existed. All three readiness rows remained ready. This probe also used only an in-memory fixture filesystem.

A bounded remedy is to derive evidence classes from authenticated supporting source/artifact types and enforce the requirement's admitted classes during candidate matching and binding. Keep rejected candidates visible with an explicit reason. Add a negative page-versus-official case and positive controls for the allowed classes; a model nomination cannot override the contract restriction.

### PR3. A prior can bind the wrong value type with an absent basis

Priority: P2. The assumption branch of `admit_bindings` at lines 2328–2360 checks the policy ID, allowed requirement origin, parameter kind, and identity. It does not compare the prior's value type with the requirement or resolve its claimed basis artifact/hash/pointer.

Starting with the current `anchor_sheet_fixture`, the reviewer replaced the coefficient prior in the pinned policy with `value={"kind":"text","value":"not a coefficient"}`, `artifact_id="unretained-prior"`, a syntactically valid absent basis hash, and `pointer="/does-not-exist"`. After rebuilding the authenticated index under that policy, an `assume` proposal returned `status=bound` for the requirement with `value_type=number`. The result preserved the absent artifact as its asserted basis. This was another in-memory, stdlib-only probe with no filesystem writes.

The policy hash authenticates the declaration but does not authenticate the referenced artifact or make a text value a numeric parameter. A bounded remedy is to resolve the prior basis against retained bytes, verify its hash/pointer and declared value/library projection, and require its value type and assumed epistemic class to satisfy the requirement. Retained negative controls should cover absent/tampered bases and mismatched value types. The current binder ordinarily proposes `bind` or `gap`; this finding concerns the public assumption admission path, not an observed live producer invocation.

All three findings were sent to Maxwell and Poincare immediately with source locations, reproduction details, and bounded remedies. Their closure requires retained regression evidence and rereview of the final bytes.

## Interim remedy review, 2026-10-30

The owner supplied a red/green bracket with module hash `2f19d99dcdd9a020d1e9b862330caea176b619ea649bfc14af1e8f88a7773a00` and test hash `a16e15fe63fd0375b16dee27d41ba355bb28dff45704e0364b3fa3569645b5dd`. The reviewer inspected [red JUnit](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-review-red-17/junit.xml) and [green JUnit](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-review-green-18/junit.xml), together with their completion files. Red records four behavioral failures; green records fourteen passing controls with no failures/errors/skips. Both completed shutdown with no recorded source drift and only the normal config/logger redirects. The automatic source maps pin the supplied test hash but do not pin the pure module, so the module hash is owner-reported for that bracket.

By the time of this rereview, ongoing renderer work had changed the module to `56eb8301f3e13c466d596ce603b9cb4ba6f7acc638b47161543ed84c4a9f155f` and tests to `a592848d7ad2914e0a14168ca01d4a02cf1c1b894f6a75de82973f839adee37f`. The reviewer inspected the repaired budget, evidence-class, and prior paths and reran the in-memory appendix against these current bytes. PR1 was rejected with `E_BUDGET_RECEIPT: stale_metering`; PR2 and the combined PR3 probe returned gaps without bindings. Both current hashes matched before and after that probe. This establishes the observed behavior of those specific cases, not final closure or validation of the renderer. The retained missing-prior regression independently exercises the absent basis without relying on the combined probe's type mismatch.

**PR1 remainder:** The new `_retained_budget_maxima` includes all five retained fields, including `reserved_max_microusd`, but `_metering` at lines 2302–2305 compares only the four fields present in the summary. A further in-memory probe attached two same-authority, same-scope budgets with identical `(1, 1000, 0, 0)` attempt/token counters and `reserved_max_microusd` values of 0 and 100. Selecting the older summary still succeeded. The current module/test hashes above matched before and after this probe too. The bounded remedy is to resolve the selected summary's already hash-verified budget payload and require its retained currency component to cover the attached maximum as well. No additional public metering field is necessary. This remainder was sent to Maxwell immediately; the parent's exact canonical-seal join remains independently necessary for old-only publications.

PR2 now derives classes from authenticated sources and native case origins, and rejects disallowed classes during matching/admission with an explicit gap. PR3 now checks basis bytes/hash/pointer and value/library projection, plus the requirement's value type and acceptance of the assumed class. Further prior controls, final source pins, renderer review, and the parent join remain pending. No final closure is claimed.

## PR1 parent-side closure, 2026-10-30

The reviewer inspected `publication.validate_budget_completion`, host `_bound_scope_completion`/`load_research_anchor`/`accept_completion`/`require_completed`, and `_adopt_research_scope_handoff`, without importing the application or rerunning the gate. Adoption authenticates the complete completion object against the durable ledger transition before saving a detached copy under `world_anchor_scope_completion`; the lifecycle remains pending. Bound v2 acceptance requires that metadata. Both initial acceptance and ready-state revalidation pass it into the publication validator before returning a context or promoting readiness.

The publication loader now returns its authenticated producer handles as a public tuple. The validator follows the selected metering artifact ID and raw hash, checks that summary's selected budget artifact and raw hash, and then compares the decoded budget's canonical hash to the ledger-authenticated completion. It also checks publication identity, pipeline, scope, session, and metered mode. Retaining a matching budget elsewhere is insufficient. The checks therefore implement the exact join requested in PR1.

The reviewer read the unchanged [ledger regression](/Users/rogerlin/.codex/worktrees/world-anchor/DeepResearchForecast/backend/tests/test_world_anchor_budget_completion.py), [stable red receipt](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-budget-completion-20261030-01/verification.json), and [final green receipt](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-budget-completion-20261030-03/verification.json). Red01 records the two actual unexpected acceptances: both bundles with equal counters but the old session selected, and an old-only publication omitting the current retained dispatch. Green03 records one passing composite test in 2.612 seconds, with zero failures/errors/skips. The test also accepts a real current zero-call seal, verifies rejected states stay pending, and exercises the pure increasing-counter floor plus its current-summary positive control.

Both runs use the same test SHA-256, `dce4a033deb488bfc4ee4e8d62d2ec4c2e2ed5d1be2abec3d0e87f128b688608`. Their fourteen external source pins match before and after each run. At rereview, all fourteen green03 pins also matched the live checkout. The reviewer verified each archive's copy-manifest hash and all 59 retained files against their recorded byte counts and hashes. Green02 is superseded because of unrelated host drift and is not used for closure.

The principal reviewed green03 hashes are:

| File | SHA-256 |
|---|---|
| `deerflow_bridge/world_anchor_publication.py` | `4f2835590adadae26e76b79fa6c11570ac87beb34e804ecc099f878baa2734e6` |
| `backend/app/services/world_anchor.py` | `a26021efb3556bae4e86ffa4f8f5c956db537ba76d2e3888e4517084684ea880` |
| `backend/app/services/run_spending.py` | `cbda9bef53c2a99339a066ced9253ea37a57afdbd9a33ceb77204d052c3fb770` |
| `deerflow_bridge/run_spending.py` | `d7691253c4f842b0355113f39930ec0ace4671ae35ed608b533daddbcd6322df` |

**Disposition:** The parent-side PR1 join is closed for this exact source bracket. This is real local ledger/adoption evidence with a parked worker and one fake model dispatch. It establishes neither a provider call nor an actual private child-process proof. At this parent-only checkpoint, the pure currency comparison and renderer/prior work were still open; the final pure disposition above supersedes that interim status. The reviewer changed only this document throughout the temporary source/test hold.

## Candidate final review, 2026-10-30

The live candidate matches the supplied pure module SHA-256 `1b90d45e42dbc2cf52b9d0b83dbb001f9aff13c5ccb78e0fccab7037f6d87df6` and dedicated test SHA-256 `51dd3e8c2b4905b367ea8265b45757ca41b74e30d1602ccf4d15ec1cd2486f31`. AST comparison against the previously reviewed retained snapshot identifies the final substantive changes as source-tier uncertainty handling, the fifth retained-budget component, and the human renderer; other reviewed admission functions are unchanged apart from formatting. The reviewer inspected all final changed code and the current dedicated regressions.

The candidate checks the selected summary's verified raw budget currency against the full retained maximum. The independent in-memory currency reproduction now raises `E_BUDGET_RECEIPT: stale_metering`, while selecting the current currency receipt succeeds. The original PR1 probe rejects stale metering, and PR2/PR3 return explicit unbound gaps. The retained prior controls separately exercise absent/tampered hashes and pointers, value/library projection mismatches, wrong value types, and missing permission for the assumed class.

The completed private sheet has 22 sections covering scope, variables, mechanisms and parameter bases, actor items, calendar, hazards, indicators, reference classes, identities, evidence inventory, research items, sources, requirements, gaps, coverage/readiness, omissions, candidate selection, resolution attempts, and metering. It derives labels and registry classes from authenticated in-memory artifact bytes, uses track-qualified source IDs, emits per-member qualitative rows, preserves unknowns and assumptions, and labels declared authority and non-executable research notes honestly. Rendering does not evaluate identity residuals or infer base rates. Conflicting/unknown/overflowed source metadata remains tier `unknown` instead of falling back to a legacy primary tier.

The reviewer independently reconstructed the synthetic sheet's source index, producer receipts, and semantic review entirely in memory. All four rendered outputs were byte-identical after reconstruction; the sheet was 12,578 bytes with 22 section headings. Pack hash and actor projection were unchanged, the private analyst statement remained absent from actor output, injected markup remained escaped, and missing registry metadata remained explicit. These are bounded pure probes, not filesystem or application test runs. Both candidate source hashes matched before and after every probe.

The retained [currency red20](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-currency-red-20/junit.xml) records the original failure. [Renderer/review green21](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-render-review-green-21/junit.xml) records 15 passing controls. The [candidate23 JUnit](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-core-candidate-23/junit.xml) records 114 passing cases with no failures/errors/skips; the two private stdin cases were deselected, not executed. Its [completion receipt](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-core-candidate-23/completed.json) pins the exact candidate test hash, exit code zero, completed shutdown, and only config/logger redirects. These automatic maps still omit the pure module; final closure therefore also requires the private harness's external module pre/post pins and the reviewer's closing rehash.

No additional concrete pure blocker was found in the candidate pass. The final disposition above adds the subsequently received and independently checked full-95-file/S107/five-vintage private evidence and closing source pins.

## Current observations and limits

The target KIQ correction now dispatches provenance by row origin: KIQ facts use positive integer ledger SIDs, while case rows use explicit target-source crosswalks. The retained tests cover string, prefixed, boolean, zero, negative, and float KIQ IDs. Exact source references bind scope, track, source key, artifact hash, and retained locator. Text spans are checked against exact UTF-8 bytes, and nested support selectors remain inside the declared span/subtree.

Semantic review requires distinct extraction/review attempt identities, pinned profile/prompt identities, authenticated raw response bytes, and matching producer transport receipts. This establishes the documented bounded support judgment, not general natural-language truth or live model qualification. Known-by is derived from authenticated capture evidence; actor projection separately checks cutoff, requested time, visibility, audience, producer class, and value kind.

The reviewed collection code requires `cardinality=many` to be textual, uses reviewed requirement nominations for qualitative matching, retains scalar numeric conflict checks, and rejects collection parameters. Research-inventory contracts keep `missing_contract` blocking gaps, forbid settlement/mechanism authority, and emit non-executable research items. The reviewer read their current dedicated tests and inspected current retained evidence rather than accepting historical case counts as closure.

Deliberate limits remain explicit: retained official rows are inventoried without an automatic semantic admission adapter; unknown publication dates remain unknown even when capture establishes known-by; missing cadence is not synthesized; six ranked candidates per requirement do not claim complete remote extraction; and a research-only inventory does not establish a settlement contract or simulation readiness. Runtime adapter capability and provider/model qualification require their separate owner checks. These limits are distinct from the original PR1–PR3 defects, which are addressed in the final reviewed source.

The publication loader attaches all externally pinned producer bundles before replaying semantic reviews. Its later `read_pack` call validates the pack against the rebuilt authenticated index. Emission uses fixed filenames, no-overwrite publication, file/directory fsync, and deterministic companion regeneration. The final renderer/provenance review and final source rehash are recorded in the closure above.

## Retained evidence inspected

The reviewer read the current dedicated test source and the following existing JUnit/completion files; the reviewer did not run those gates. The attachment gate records 9 passing cases, the inventory/budget gate records 17, and the SID-origin gate records 9. Each reports zero failures/errors/skips, exit code zero, completed shutdown, no recorded source drift, and only the guard's app-config/logger redirects. These are owner-executed offline receipts, not live-provider evidence or a new composed review gate.

- [Attachment completion](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-attach-13/completed.json) and [JUnit](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-attach-13/junit.xml).
- [Inventory/budget completion](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-inventory-budget-15/completed.json) and [JUnit](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-inventory-budget-15/junit.xml).
- [SID-origin completion](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-sid-origin-16/completed.json) and [JUnit](/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-sid-origin-16/junit.xml).

At the initial review checkpoint, only the SID-origin completion pinned its dedicated test hash (`83005fc7…`); the earlier two receipts covered earlier test bytes. These initial completion files omit the pure module from their automatic source maps. Their historical counts are not closure evidence for later changes. The final private envelope supplies the needed external module pre/post pins, supplemented by the reviewer's final rehash.

## Remaining work and continuation boundary

No work remains in this bounded pure review at the latest projection pins above. Existing PR1–PR3 closures remain in force because their implementation is unchanged. The coordinator retains ownership of composed application/integration acceptance and delivery. The existing parent budget regression must run in a fresh guarded process if a later change requires it; it must not be combined with other authorization fixtures or reset core authority.

Continuation prompt: Check the final source hashes in this review before relying on its closure. If relevant files changed, inspect the bounded diff and current retained evidence, editing only `docs/handoff/world-anchor/pure-review.md` unless the user expands ownership. Preserve other work. Do not call providers, import the application, run broad tests, or delegate. A new completion claim requires another matching final rehash.

## Reproduction appendix

The following reviewer probe loads only the stdlib pure module and selected function definitions from the retained tests. Its fixture path object and `_read` substitution keep every fixture write in memory. It does not test the filesystem implementation, import pytest/application code, or run a pytest gate. Run it with `python3 -I -S -B`; any source change between loading and exit rejects the receipt. A `reproduced` result demonstrates the corresponding defect. A rejection or non-bound result requires inspection of the reason and positive controls before declaring a remedy correct.

<!-- pure-review-probe:start -->
```python
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

root = Path('/Users/rogerlin/.codex/worktrees/world-anchor/DeepResearchForecast')
module_path = root / 'deerflow_bridge/world_anchor.py'
tests_path = root / 'backend/tests/test_world_anchor.py'
before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in (module_path, tests_path)}
spec = importlib.util.spec_from_file_location('pure_review_module', module_path)
wa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wa)
files = {}

class MemPath:
    def __init__(self, value):
        self.value = value
    def __truediv__(self, other):
        return MemPath(self.value + '/' + str(other))
    @property
    def parent(self):
        return MemPath(self.value.rsplit('/', 1)[0])
    def mkdir(self, **kwargs):
        pass
    def write_bytes(self, raw):
        files[self.value] = raw
        return len(raw)
    def read_bytes(self):
        return files[self.value]
    def write_text(self, text):
        return self.write_bytes(text.encode())
    def read_text(self):
        return self.read_bytes().decode()

wa._read = lambda directory, relative, limit: files[(directory / relative).value]
names = {'dump', 'digest', 'unknown', 'unit', 'identity', 'scope', 'consumer',
         'make_fixture', 'review_fixture', 'receipt_fixture', 'enrich',
         'build_pack', 'args', 'budget_receipts_fixture', 'anchor_sheet_fixture'}
nodes = [n for n in ast.parse(tests_path.read_text()).body
         if isinstance(n, ast.FunctionDef) and n.name in names]
for node in nodes:
    node.decorator_list = []
helpers = {'wa': wa, 'copy': copy, 'hashlib': hashlib, 'json': json}
exec(compile(ast.Module(body=nodes, type_ignores=[]), '<retained-helpers>', 'exec'), helpers)

def reindex(f):
    f['index'] = wa.index_snapshot(
        f['root'], f['manifest'], expected_manifest_hash=wa.anchor_hash(f['manifest']),
        expected_scope=f['scope'], requirements=f['requirements'], policy=f['policy'])

def pr1():
    f = helpers['make_fixture'](MemPath('accounting'), with_contract=False)
    old, meter = helpers['budget_receipts_fixture'](f, (1, 1000, 0, 0))
    new, _ = helpers['budget_receipts_fixture'](f, (3, 3000, 2, 1))
    f['index'] = wa.attach_producer_receipts(f['index'], receipts=[old, new])
    candidates = wa.candidates_for_requirements(f['requirements'], f['index'])
    proposal = {'schema_version': 'world-anchor-proposal/v1',
        'requirements_hash': wa.anchor_hash(f['requirements']),
        'input_hash': f['index'].snapshot()['input_hash'],
        'candidate_hash': wa.anchor_hash(candidates), 'rows': []}
    pack = wa.admit_bindings(f['requirements'], f['index'], candidates, proposal,
        policy=f['policy'], attempts=[], metering=meter)
    return pack['metering']

def pr2():
    f = helpers['make_fixture'](MemPath('evidence'))
    contract = f['requirements']['contract']
    contract['terms'][1]['accepted_evidence'] = ['official_row']
    raw = helpers['dump']({'settlement': helpers['identity'](2027), 'terms': contract['terms']})
    (f['root'] / 'contract.json').write_bytes(raw)
    contract['authority_artifact_hash'] = helpers['digest'](raw)
    next(a for a in f['manifest']['artifacts'] if a['artifact_id'] == 'contract').update(
        sha256=helpers['digest'](raw), bytes=len(raw))
    f['requirements'] = wa.requirements_from_contract(contract, scope=f['scope'])
    reindex(f)
    pack = helpers['build_pack'](helpers['enrich'](f))
    rid = next(r['requirement_id'] for r in pack['requirements'] if r['kind'] == 'baseline')
    return next(b for b in pack['bindings'] if b['requirement_id'] == rid)

def pr3():
    f, _, _ = helpers['anchor_sheet_fixture'](MemPath('prior'))
    f['policy']['prior_rules'][0].update(artifact_id='unretained-prior',
        artifact_hash='f' * 64, pointer='/does-not-exist',
        value={'kind': 'text', 'value': 'not a coefficient'})
    reindex(f)
    f = helpers['enrich'](f)
    pack = helpers['build_pack'](f)
    rid = next(r['requirement_id'] for r in pack['requirements']
               if r['assumption_policy_id'] == 'prior-coefficient')
    for row in pack['proposal']['rows']:
        if row['requirement_id'] == rid:
            row.update(decision='assume', candidate_ids=[], prior_policy_id='prior-coefficient')
    pack = wa.admit_bindings(f['requirements'], f['index'], pack['candidates'], pack['proposal'],
        policy=f['policy'], attempts=[], metering=pack['metering'])
    return next(b for b in pack['bindings'] if b['requirement_id'] == rid)

for name, probe in [('PR1', pr1), ('PR2', pr2), ('PR3', pr3)]:
    try:
        result = probe()
    except wa.AnchorError as exc:
        print(name, 'rejected', exc.code, exc.path)
    else:
        status = 'reproduced' if name == 'PR1' or result.get('status') == 'bound' else 'not_bound'
        print(name, status, json.dumps(result, sort_keys=True))
after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in (module_path, tests_path)}
assert before == after, 'Source changed during the probe.'
print('matching_source_pins', json.dumps(after, sort_keys=True))
```
<!-- pure-review-probe:end -->
