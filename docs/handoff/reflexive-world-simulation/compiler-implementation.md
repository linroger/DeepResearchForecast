# Compiler implementation handoff

**Status:** Complete for the bounded compiler slice; ready for coordinator integration. **Updated:** 2026-10-16 UTC.

## Request, scope and acceptance

Implement a bounded, deterministic world derivative from research and modeler proposals. Ownership is limited to `compiler.py`, `test_world_compiler.py` and this document. The coordinator owns contracts, model calls, integration and frozen guarded test execution. No providers, source mutation, resealing or commits are authorized for this slice.

Acceptance requires actual report/claim reference resolution, honest sealed legacy versus unsealed v3 grades, denial of modeler/private information in actor profiles, declared assumptions for invented quantities, explicit modeling gaps before launch, and a constrained JSON-only modeler prompt. Tests must also preserve source objects and exercise the actual observation consumer.

## API and plan

The coordinator confirmed `compile_world_spec(raw_spec, *, simulation_id, generation_id, research_report, research_generation_id, research_engine, actor_bundle=None)` and `build_compiler_messages(*, research_report, research_generation_id, research_engine, actor_bundle=None, ontology=None, simulation_requirement='')`. The compiler owns `sourceBindings` and ignores proposed bindings. Exact span references use Python Unicode character offsets `{start, end, sha256}`; claim references use `{actorId, claimId}`. Assumption references resolve named entries, including `synthetic-example/v1`.

1. Inspect existing seal and partition validators, preserving their serialization recipes.
2. Implement bounded source indexing, provenance resolution and separate actor derivation.
3. Reject missing mandatory mechanism parameters and undeclared quantitative assumptions.
4. Add focused positive/negative tests, then request the coordinator's frozen guarded run and independent review.

## Findings and decisions

The current checkout implements actor intelligence in `deerflow_bridge/deerflow_research.py`, context validation in `backend/app/services/actor_context.py`, and role compilation in `backend/app/services/actor_role_prompt.py`; there are no standalone `actor_intelligence.py` or `actor_roles.py` files. Existing actor context keeps modeler-only evidence separate but its bounded text is unsuitable as an actor-visible world profile. Report relevance alone cannot establish permission. New actor profile fields will require admitted actor evidence or declared behavioral assumptions.

## Progress and verification

- Source contracts and ownership inspected; approved scope confirmed.
- API proposal sent to the coordinator and confirmed.
- Compiler and regression suite are implemented and frozen for the coordinator's first guarded run. Application execution has not occurred in this worker session.
- Frozen compiler SHA256: `04ff1b8a66cd2dc96013d70060035c97777fb01f4e98c15c6f58eb6a4a5ff389`.
- Frozen test SHA256: `769e4faffe1d24a0703f42221ae3006fc750c13024cd6ea1d2f3ac51ebc4aad4`.
- Static diff whitespace inspection reported no errors. These new files are untracked, so that command alone does not establish their syntax or runtime correctness.

## Implemented source carrier and conservative mapping

V3 accepts a raw `actors.json` object. Legacy additionally requires `{actors: <actors.json>, sources: <sources.json list>, dossier: <exact text>}`. Existing context-seal validation is followed by the parent's pure source-receipt lookup and claim normalization routines. The compiler compares the exact source ledger, dossier, actor identity and claim roster hashes; it performs no resealing. Full on-disk research-generation/lineage admission remains the coordinator's boundary.

An unsealed structured claim must have `claim_id`, `claim`, and `report_ref` resolving the exact report substring containing that text. Knowledge permission is separately derived from explicit metadata. Flat legacy-style v3 behavior strings do not gain knowledge authority: the modeler can declare behavioral assumptions, or leave the profile unknown. Source profile entries must reproduce a permitted claim exactly; declarations and contested evidence retain their evidence type.

Quantitative source references additionally require `field` and `target`, for example `qualifiers.balance` and `balance`. The cited report span or source quote must itself contain a JSON object with the matching named quantity and unit. A number elsewhere in prose, or an invented numeric qualifier, cannot establish liquid cash or a causal coefficient. Ordinary prose-derived quantities therefore require a scenario assumption until a typed evidence adapter exists. This is intentionally conservative.

`descriptionBasis` can separately admit menu text for all initiators and recipients. Descriptions must use exact permitted source text or explicit scenario assumptions. Denied/modeler claim text is checked before visible projection, including attempts to relabel it as an assumption. The compiler invokes `kernel.validate_mechanisms` directly and surfaces invalid configuration or required unknown physical metrics as `WorldError` before launch.

Tests cover actual observation payloads, input immutability, v3/report-only evidence, denial precedence, exact references/typed units, explicit priors, missing required parameters, three synthetic examples, malformed inputs, bounded prompt generation, and the real legacy producer fixture with tamper controls. Coordinator guarded results and independent review are pending.

## Guarded results and independent review

The coordinator's second frozen run executed 219 tests: 218 passed and one unrelated policy SDK timeout assertion failed. All **39 compiler tests passed**, confirmed by reading JUnit. The wrapper and completion receipt report no source drift. Evidence: `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-world-second-20261016T150115Z-iamdldpa/evidence/`. Guard self-tests deliberately attempted forbidden operations; counters include blocked network, credential, process, filesystem and identity-environment controls, so this is not a claim of zero attempts or an OS sandbox. The run applies to the earlier hashes above.

Independent reviewer Darwin traced four issues despite that green compiler suite. Unsealed claims could inject unverified structured `source_support` quotes; private effect values could reach a public destination record; alternate evidence-type fields could bypass analyst exclusion; and scheduled deltas could target an unknown metric without a preparation gap. All four were corrected with focused regressions. V3 now consumes only its checked report span for typed values; evidence aliases are resolved conservatively; rule/relation outputs are checked against destination, commitment and participant visibility; and scheduled metric targets participate in readiness checks.

Additional self-review corrections inspect nested original strings before JSON escaping, constrain typed reference selectors, derive initial evidence/status labels rather than trusting proposal labels, and require typed support or assumptions for categorical/boolean mechanism parameters as well as quantities. The modeler prompt includes the raw actor candidate artifact in a modeler-only field; those candidate fields never confer actor knowledge.

The revised files pass syntax parsing without executing imports. New frozen compiler SHA256: `c8a6963d4a14fa3a5259e92555780304fd463e49048161ab7786bf6f9f90c78f`. New test SHA256: `c61ceeaffc886e047cc127ae4474821ed349f4a8c7a91ed5b20c8749070411b0`. Coordinator rerun and reviewer closure are requested and pending; earlier green evidence does not validate these later changes.

The third frozen gate subsequently passed **225 tests in 5.58 seconds**, including **53 compiler tests with zero failures/errors**, verified directly in JUnit. Evidence: `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-world-third-20261016T154853Z-cna0sinm/evidence/`. The adjacent `source-manifest.json` matches the revised compiler/test hashes above, and `verification-summary.json` reports zero drift across 507 copied files. `completed.json` confirms exit code 0, preserved identity environment and no source drift. Its two blocked subprocess attempts remain explicitly recorded; no provider calls were made by this worker. The third run excludes the guard self-test suite, which ran in the earlier gate. Reviewer closure remains pending; no unchanged-byte test rerun is necessary.

Rereview closed the original four triggering cases but identified four further cases outside that suite: agreement conditions exposed denied text through offer obligations; existing actor names could acquire fabricated IDs; unknown/contested cash stayed spendable; and nested `basis`/`reserved` keys bypassed value provenance traversal. These have now been fixed, with dedicated regressions and an explicit-assumption positive control. Conditions use participant/public visibility, actor IDs are bound in both directions, executable resources and mandatory mechanisms require resolved evidence, and selected value subtrees are traversed without metadata-name exceptions. Informational actor beliefs may still retain unknown/contested labels.

Two coordinator-requested integration corrections were added in the same revision. Explicit `raw_spec.policy` is preserved as detached, canonically identical metadata with a closed credential-free shape; provider, prices and full transport admission remain pinned caller inputs checked by `StrictHTTPPolicy` before launch. No policy/provider/pricing default is invented. `assumptions[].visibility` is optional, normalized with the shared visibility helper after actor identities exist, and defaults to analyst-only. Public or actor-visible assumption descriptions pass the same denied-text check. The modeler prompt documents visibility and instructs the model not to generate transport policy.

Current frozen compiler SHA256: `346d4489bc8aec9f126a9181880c6267e79d3841cdf86500e78887f21fc0428d`. Current tests SHA256: `5425c0860e2830a1c64dc86f98d180d76626b17af8f8f61f54d15b43d0ac9535`. Syntax parsing passed; updated guarded compiler/integration runs and focused reviewer closure are pending. The third green gate remains valid historical evidence, not acceptance of this later revision.

The subsequent compiler and real preparation/child/results gate passed **78 tests in 5.81 seconds**, including **69 compiler tests** and **9 service/results tests**. Evidence: `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-world-service3-20261016T155359Z-d6cjg_in/evidence/`. JUnit, the completion receipt and source manifest were read directly: zero failures/errors, exit 0, no drift across 509 copied files, and the current compiler/test hashes above match. The receipt records only the three configured application-root/log redirections, with no blocked-attempt events and the identity environment preserved. The coordinator reports actual preparation → child → controller → store → public/analyst result consumers across all three domains, plus tamper, cancellation and fork controls. This is guarded synthetic evidence, not live-provider or empirical forecast validation. Focused independent closure is the only remaining acceptance step for this worker slice.

Final independent rereview by Darwin (`01a1453a-b121-7063-b6a6-e01e5cd15e26`) verified the current frozen compiler and test hashes and returned **clean within the requested scope**, with no remaining actionable defect or review blocker. It closed agreement-condition disclosure, actor-name rebinding, unresolved executable evidence, nested metadata-name provenance bypass, pinned policy preservation and assumption visibility. The earlier four findings were already closed in the preceding pass. The reviewer performed source review only; this worker independently inspected the guarded receipts cited above. All required compiler-slice checks now have current runtime evidence and focused independent review.

## Issues and recoveries

No application code has been executed. File-name discovery initially assumed standalone actor modules; current interfaces were located in the producer, context and role modules above.

## Remaining work and next-session prompt

No compiler review findings remain. The coordinator can integrate these unchanged frozen files and owns full research-generation admission, model invocation, transport preflight, commits and broader release acceptance. No commits or provider calls were made by this worker. Next-session prompt: read this note, verify the current compiler/test hashes against the latest receipt, and integrate the three owned files without re-running unchanged checks or modifying other workers' work. Reopen this slice only for a concrete integration defect or changed source.

## Updates

- 2026-10-16 UTC: Created the slice handoff before code changes; recorded API, scope, checks and source-interface findings.
- 2026-10-16 UTC: Implemented compiler and focused tests; sent frozen hashes and requested coordinator guarded testing and independent review. Reported the investment fixture's flow-unit disagreement with the kernel to its owner rather than changing unowned files.
- 2026-10-16 UTC: Read the 39-pass compiler JUnit and no-drift guard receipts. Recorded independent findings, fixed all four, added regressions and froze revised files for another guarded run and review.
- 2026-10-16 UTC: After transient-disconnect resume, verified unchanged owned hashes. Read the third-run 225-pass/53-compiler-pass receipt and 507-file no-drift manifest; recorded fresh runtime evidence for the revised bytes and requested final reviewer closure.
- 2026-10-16 UTC: Closed four additional rereview cases and added caller-pinned policy plus private-by-default assumption visibility compatibility requested by lifecycle/results integration. Froze current hashes and notified the coordinator that its integration rerun can proceed.
- 2026-10-16 UTC: Verified the 78-pass integration receipt, including all 69 compiler tests and exact current hashes, and recorded 509-file no-drift evidence. No further test rerun is requested for unchanged source bytes.
- 2026-10-16 UTC: Final independent rereview returned clean on the tested hashes. Marked the bounded compiler slice complete and ready for coordinator integration; retained all historical findings and receipts.
