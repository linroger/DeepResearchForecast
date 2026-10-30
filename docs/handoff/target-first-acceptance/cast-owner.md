# C5 source-metadata correction: cast owner

**Status:** Complete for the five-file owner slice. **Date:** 2026-10-28. This is the bounded owner handoff for the approved C5 correction; the parent handoff and plan remain authoritative.

## Request, scope and acceptance

Correct executable agency classes using declared source metadata, without inventing actor facts or name-specific rules. Own only `agency_classification.py`, `simulation_config_generator.py`, `world_model_seed.py`, `test_agency_classification.py`, and this document. Other owners control manager, pipeline, API and flags. No production writes, network/provider/paid calls, scheduler changes, commits or pushes.

Acceptance requires canonical dossier precedence, concrete ontology type precedence, exact unambiguous ontology example/alias matching ahead of generic Organization, explicit unresolved conflicts, invalid metadata rejection, deterministic UUID-bound provenance, and generator-to-seed-to-decision consistency. Omitted maps must preserve old behavior and serialized fields. Frozen specimen copies must reproduce the three confirmed corrections in guarded evidence without adding private data to the repository.

## Integration interface

`build_agency_classifications(entities, actors, ontology)` returns a dictionary keyed by `entity.uuid`. Each value is `{agency_class: canonical_string_or_None, basis: {...}}`. Basis records `source`, `type_names`, `ontology_sha256`, `match_method`, and `status`; unresolved conflicts carry no class override. The ontology digest is SHA256 of UTF-8 canonical JSON (`sort_keys=True`, `ensure_ascii=False`, compact separators, no NaN). Inputs are never mutated.

Both `SimulationConfigGenerator.generate_config` and `build_world_model_seed` accept optional keyword `agency_classifications`. The parent builds this map once before sealing `actor_cast_manifest`, records it in that manifest, and passes the same map into configuration generation. The generator applies validated resolved entries to named configs before downstream consumers and forwards the map into the seed builder. Both retain the declaration basis when present. Omission creates no new serialized fields. Saved-config loading is outside this slice and remains unchanged.

## Plan and progress

1. Inspected existing producer/consumer interfaces and frozen metadata. Complete.
2. Added a pure classification adapter and shared validation for map entries. Complete.
3. Applied the map to executable config before constructing the world seed. Complete.
4. Verified targeted cases and frozen copies with the existing guarded runner. All review regressions pass; independent rereview closed with no remaining critical or important findings.

## Evidence and remaining work

The branch is `codex/target-first-acceptance`. Existing dirty parent paths are preserved. No application imports have run outside the guard. Verification results and exact private evidence paths will be appended here. The parent's manager integration remains separate work.

## Final verification receipts

The final owner gate is `/private/tmp/c5-final-gate-20261028-b`: **65 passed, zero skipped** in 2.26 seconds. `completed.json` confirms normal completion, no blocked operations or discovery probes, no tracked source drift, and preserved identity environment. It is CPython audit-hook evidence, not an OS sandbox or live-provider claim.

Independent read-only review by agent `01a18206-5e99-7f70-bb75-784e03787183` closed all three findings and the historical byte-compatibility suggestion after inspecting the final source. The reviewer did not run tests; the executed evidence is the owner gate above. Parent manager/pipeline/API/flag integration is outside this closure.

- `c5-source-hashes.json` pins all four owned Python files before/after the gate and confirms equality.
- `c5-specimen-proof.json` records the three corrected classes and their exact ontology declarations, with successful generator, seed, world-state and decision-rights consumption.
- `snapshot-preservation.json` confirms unchanged original frozen actors, ontology, saved config and manifest bytes. The input copies live only under `c5-snapshot/` inside private evidence.
- `c5-legacy-bytes-proof.json` proves complete no-map config serialization is byte-identical to the pre-change generator/seed at `e0b233779a08493603360ddd4b5f4ba12a0183bf`, fixing only `generated_at` for comparison. This includes the real legacy seed. Baseline source copies and hashes are in `c5-baseline/` inside evidence.
- `junit.xml` records all scenario outcomes. The earlier review red/green receipts retain the two reproduced defects and their fixes.

Frozen owner SHA256 values:

| File | SHA256 |
|---|---|
| agency_classification.py | `9405c796d19d43fc0d52e0f272e5531d4d4667df9a6e6a7904fb87739242b4ba` |
| simulation_config_generator.py | `8de3804f77f7bfd49b7d4a514e508ffaece36ecce159e349f2ba654475d1c541` |
| world_model_seed.py | `30832cbf1f70afe49d74c225dbce3f25f0f77c531c51b0d15bd4425cff64d606` |
| test_agency_classification.py | `a95dc5409f399580240f205b98910830a944abca390bd39337d3b388f3ea73ec` |

The broader exploratory gate is not a green acceptance claim: `c5-classification-gate-20261028-b` had 104 passes, one unstaged-private skip and the untouched temporal pin failure. Its dependency imports also attempted one socket construction, four process launches and twenty external reads, all blocked by the guard; these included OASIS/platform/font discovery. The focused final owner gate has none of these attempts. Parent integration and resolution of that independent temporal pin remain parent-owned.

## Next-session prompt

> Read this owner receipt and the parent handoff. Keep the four Python hashes above frozen while verifying the parent's manager → sealed cast manifest → generator → seed integration and rollback control. Use a fresh guarded evidence directory. Preserve the snapshot and unrelated dirty work. Network/provider/paid execution, scheduling, production writes, commits and pushes are not authorized by this owner task.

## Portable private receipt package

For durable retention, copy the complete `/private/tmp/c5-private65-package-20261028` directory. It contains `original-evidence/` from the 65-case final gate, original stdout, the frozen private input and baseline-source copies, a stdlib-only `bootstrap.py`, a README and a complete file-hash manifest. The package is private evidence and must stay outside Git. The original evidence directory remains unchanged.

`package-manifest.json` SHA256 is `7dd41af9fc00963fe860fe99774c983df2a1d8e42fe4d8622650d774cf9c61b4`. After copying, run the bootstrap with `--verify-only` from its new location. To reproduce, provide `--repo`, the provisioned interpreter as `--python`, and a new `--evidence-dir` under `/private/tmp`; the README gives complete commands. The bootstrap loads staged private and historical source copies rather than depending on mutable HEAD or the original snapshot path, and rejects anything other than 65 passing cases with no skips or guard violations.

The bootstrap itself was exercised successfully at `/private/tmp/c5-private65-bootstrap-check-20261028-a`: 65 passed, zero skipped, zero blocked operations/probes, no source drift and preserved identity. `bootstrap-receipt.json` records the command, package manifest digest and source/package preservation; `completed.json` and `junit.xml` confirm the result. This second directory can be copied alongside the package as reproducibility-validation evidence. None of the four frozen repository source files changed.

## Updates

- 2026-10-28: Read the approved handoff, plan and snapshot receipt. Sent the parent the optional keyword/map contract before implementation. Existing code recomputes seed classes from incidental actor text even after configuration classification, so both boundaries require the same map.
- 2026-10-28: Implemented UUID-bound declaration resolution and validation, applied config overrides before initial-post assignment and other consumers, and forwarded the map into world seeding. Canonical class values are accepted literally; no free-text class inference occurs inside the new adapter. Basis contains `entity_uuid`, `source`, `type_names`, `ontology_sha256`, `match_method`, `status`, `reason`, and `declarations`.
- 2026-10-28: Initial guarded gate `/private/tmp/c5-classification-gate-20261028-a` produced 58 passes, one failure and one expected unstaged-private-data skip. The integration fixture lacked the manager-owned consumed-research seal required by the existing backtest-policy loader; it therefore omitted the world seed. The fixture now explicitly supplies no official snapshot/backtest policy while retaining the real generator, seed and decision consumers. A fresh affected gate is running; independent review is also in progress.
- 2026-10-28: Gate `c5-classification-gate-20261028-b` reached 104 passes and one expected private-data skip, with one unrelated temporal regression-pin failure: the untouched runner writes `options` on the hours path. The same existing test fails alone in `/private/tmp/c5-temporal-baseline-20261028-a`; reported to parent without editing unowned paths.
- 2026-10-28: Private proof `/private/tmp/c5-private-specimen-20261028-a` passed using hash-verified copies of the frozen actors, ontology and saved config. Entity UUID/name/type inputs were reconstructed from the saved config, whose three types are Organization. CrowdStrike changes individual_leader → firm, Anthropic regulator_agency → firm, and Munich Re research_institution → financial_institution. Real configuration generation, seed, WorldModel and decision-option feasibility consume the corrections. All copied inputs and original snapshot hashes remained unchanged; proof is in `c5-specimen-proof.json` and `snapshot-preservation.json` in that evidence directory. No raw private inputs are in repository files.
- 2026-10-28: Final source refinement makes a resolved seed map bypass old inference entirely, and keeps the new optional dataclass field last to preserve positional callers. A final affected gate and private-proof rerun will bind validation to these exact bytes.
- 2026-10-28: Independent review found a reverse dossier-alias collision, acceptance of unresolved entries missing `agency_class`, and a consumer test that could miss a dropped trailing seed actor. Guarded red proof in `/private/tmp/c5-review-red-20261028-a` reproduced both implementation defects. The resolver now requires a unique entity-to-dossier binding in both directions before importing dossier metadata; the validator requires the class key and JSON-safe metadata. Consumer checks assert full config/seed/world membership and use strict zip, with a negative truncated-seed control. The three focused regressions passed in `/private/tmp/c5-review-green-20261028-a`.
- 2026-10-28: The earlier `c5-final-gate-20261028-a` passed 61 cases including the private proof but predates the review corrections and is superseded. A pre-change byte-comparison test now loads hash-pinned HEAD source copies staged inside the guard, exercises both generators with the same fixture, fixes only the generated timestamp, and compares complete serialized bytes. The final gate will stage these source copies alongside the frozen specimen.
- 2026-10-28: Final owner gate `c5-final-gate-20261028-b` passed all 65 cases including staged private and baseline comparisons. Added the source hashes, exact evidence paths, historical failures, guard-event distinctions and parent continuation prompt. No owned Python changes occurred during or after that gate.
- 2026-10-28: Independent rereview closed without further source changes. Marked this owner slice complete and sent the parent the final interface, proof paths, guard outcomes and frozen hashes. The five owned paths remain uncommitted as instructed; no provider/network calls, scheduler changes or production writes were performed.
- 2026-10-28: Parent reports the unrelated temporal assertion was updated to admit exactly the pre-existing publication-owner fields (`record_owner='runner'` and the validated `terminal_artifacts_token`) while retaining 144 rounds and no calendar metadata; production runner unchanged. Parent reports 67 integration gates and 10 direct receipt checks passing. These are parent-reported outcomes, not rerun by this owner. Reconfirmed all four frozen C5 source hashes and prepared the portable private65 receipt/bootstrap package for durable copying.
- 2026-10-28T10:44:21Z: Executed the portable bootstrap against a new guard root; all 65 cases passed without skips, blocked operations, probes or drift. Verified the package inventory and digest again after the run. Sent parent both copyable directories and the manifest checksum.
