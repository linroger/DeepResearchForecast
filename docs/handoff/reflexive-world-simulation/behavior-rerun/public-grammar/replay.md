# Historical rejected-decision replay

**Status:** Complete — parent guarded acceptance passed for all 28 replay/helper cases; source remains frozen during parent phase 7 live work.
**Started (UTC):** 2026-10-16T19:27:40Z.
**Last updated (UTC):** 2026-10-16T19:46:52Z.
**Baseline:** `37b4316` in the shared `codex/reflexive-world-simulation` worktree.

## Request and scope

Preserve the actual closed v2 case `m5-e2-investment-v3-s0-external-feedback-ablation`, including its rejected round-four quantity of 12 against a maximum of 10. The fresh HTTP response grammar check must not change historical validation, cached decisions, or replay. This worker owns only this document, `backend/tests/test_world_public_grammar.py`, and `backend/tests/fixtures/world_rejected_replay_v2.json`. No source contracts/store edits, original evidence writes, SQLite opens, application imports, provider calls, test execution, agents, or commits are authorized for this worker.

The subsequent user instruction expands the same fixture to two additional actual closed cases from `/private/tmp/drf-world-live-evaluation-20261016-request-bound`: `m5-investment-v2-s0-reflexive` (wrong interaction ID) and `m5-investment-v1-s0-external-feedback-ablation` (acceptance with supplied terms). Each uses the exact spec from its own preregistration. Full replay covers all three cases; partial cached recovery remains only on the v2 quantity case. The fixture ceiling is now eight MiB. The previous one-case freeze is retained below as draft history, superseded by the expanded freeze section.

## Acceptance plan

1. Read bounded regular JSON source files with the standard library; copy the exact selected spec and complete trace into one fixture with source-byte and canonical-content hashes.
2. Author a scripted replay through the real controller/store. Match every generated observation to its captured slot, preserve normalized historical decisions after removing only derived fields for transport, compare all four committed rounds and the final semantic revision, and reopen the temporary store read-only.
3. Exercise the saved fourth-round rejected decision as a cached receipt without dispatch. Assert no HTTP calls in either path.
4. Author focused `_input_values` parity checks proving `actors=None` skips membership only, while normal and empty actor dictionaries still enforce membership. Cover grammar bounds, required/enum/type rules, consent, and decimal normalization.
5. Parse authored Python with AST only, verify JSON/source hashes with the standard library, and freeze for parent-run guarded acceptance.

## Current evidence and boundaries

The selected source directory contains `trace.json` (403409 bytes), `receipt.json` (6296 bytes), and a SQLite database. Only JSON is read. The trace contains 19 observation/decision records, five history snapshots, and four committed rounds. Round four contains one rejected buyer intent: `invalid_input`, `Input above declared maximum`.

## Fixture provenance

The initial draft fixture was 414369 bytes, below the original one-MiB bound. Its content is preserved as the first case inside the expanded fixture. Each case contains the exact selected preregistered spec, the entire canonical trace, selected completed-case receipt fields, original case metadata, archived application source hashes, and source-file hashes. The original specs, including policy and observation-mask configuration, are preserved so historical spec hashes and semantic revisions remain unchanged. Test execution uses an `external=False` scripted policy; archived HTTP configurations are never instantiated as providers. The following table records the initial draft provenance; final fixture/test hashes appear in the expanded freeze section.

| Artifact | SHA-256 |
| --- | --- |
| Original `preregistration.json` (302662 bytes) | `3e77de380d252d00b5df8774ad0ae01a6aaaa82335ebd5192e493169e7a8b332` |
| Original case `trace.json` (403409 bytes) | `4c3cf087093ba603c2b7ef8dc3ddd980144d670452c0b08e689eb6c4c8bd4f0e` |
| Original case `receipt.json` (6296 bytes) | `6698ad1c39505e625472c501942ab8b1e15d2186e1ddf376d477ec0364ccf07b` |
| Canonical selected spec | `e802473e96a2a1147cfb6db6b2b389994de7c7754ddb38918a8324859d5c8a25` |
| Canonical complete trace (matches original receipt `traceHash`) | `b5c256f86c4b75baab33a70df43bb3abbe64d57a36dd58982ab68fe93404872f` |
| Checked-in `world_rejected_replay_v2.json` | `53d82dcfc65232f78a38e8455c729e5a14522fe0100a561a819ca565042e6a98` |
| Authored `test_world_public_grammar.py` | `350de980e16f4a321f3bda3ffb5e55b5228b251e14d6159646915a00f1315742` |

The preserved final semantic head revision is `f09b1e3781287db33f9a6f72de70ce0d876f5db8314852db09113bb6a5575165`. The quantity-12 rejection belongs to intent `7bab2f8fe03e57e3a54f0ea79ad97b40` in slot `4:proposal:buyer`; its price remains 12 as well. No input has been clamped or repaired.

The extraction used standard-library JSON/Unicode/hash code, no-follow read-only file opens, regular-file and one-MiB size checks, and before/after source hashes. All three original JSON hashes remained unchanged. The original SQLite database was neither opened nor read. No original source file was written.

## Authored regressions

Six test functions now expand to 28 cases. Four exercise the historical captures: full replay of each of the three cases and saved fourth-round decision recovery for the v2 quantity case. The real controller produces observations that must equal all captured records (19, 20, and 20 respectively). The real store must commit exactly the captured rounds, history, head revisions, events, resolutions, observations, and normalized decisions, then preserve them on read-only reopen. The cached path seeds the fourth-round proposal receipts through public store APIs and requires zero new attempts on resume. HTTP send traps must remain unused. Zero simulated replay usage is checked separately from the historical provider billing evidence, which is not rewritten or represented as newly measured usage. Full budget ledgers, SDK data, provider calls, and unrelated case data are not copied into this fixture.

The helper cases compare `actors=None`, a populated dictionary, and an empty dictionary. They retain integer/boolean/string/decimal type checks, text limits, numeric bounds, enums, required inputs, unsupported-input rejection, exact consent input rules, and decimal/enum normalization. Actor fields also retain type/length/minimum/maximum/enum restrictions in None mode. Both a normal dictionary lacking an actor and an empty dictionary must still raise `invalid_input: Unknown actor input`; only explicit None skips that membership check.

These tests intentionally exercise `validate_decision`, store receipt validation, controller cached decisions, and deterministic commit replay without patching those boundaries. Moving the new HTTP grammar rejection into one of these paths should break the corresponding captured historical replay rather than silently change its outcome. `ScriptedReplayPolicy` strips only derived decision/intent identity fields before returning the captured normalized decision to the real controller.

## Expanded three-case freeze

The collection schema is `world-historical-replay-fixture/v2`, with exactly three case objects. Its size is **1319777 bytes**, below eight MiB. Each original trace remains complete and canonical; each original completed receipt's `traceHash` matches its embedded canonical trace. All eight unique original JSON files were rehashed unchanged after extraction. Original SQLite files were never opened or read.

| Case | Slots | Preserved rejection | Final semantic revision |
| --- | --- | --- | --- |
| `m5-e2-investment-v3-s0-external-feedback-ablation` | 19 | Round 4, quantity 12 exceeds 10; `invalid_input` | `f09b1e3781287db33f9a6f72de70ce0d876f5db8314852db09113bb6a5575165` |
| `m5-investment-v2-s0-reflexive` | 20 | Round 2, interaction `f8e02d723e0454b6134dc3b36dcb1b` absent from presented inbox; `unavailable_offer` | `d917eafbb90d103c03b441b63db84d8cf836ddf5aeb9c2b68943f72ff46d9a0b` |
| `m5-investment-v1-s0-external-feedback-ablation` | 20 | Round 2, acceptance carries quantity/price 2 instead of empty input; `invalid_input` | `1bef5cf14d1df1048c5f353033189e8c4e0d93a199842d6b1102c6ab9dab8eee` |

Additional original source hashes, all under `/private/tmp/drf-world-live-evaluation-20261016-request-bound`:

| Source | SHA-256 |
| --- | --- |
| `preregistration.json` | `8b395d04703541fc8f57c42bcc7091c5bc6742ad13e2a6f607c4e35b0c19a717` |
| Wrong-ID case `trace.json` | `face30ea200a167d5006699211aa30303a4cdd56360185f8d40614cdbb440132` |
| Wrong-ID case `receipt.json` | `3dce0171ae136a172645d9163b78d4bd1d0812fe70aa2ea3cc27e49fc5e728e1` |
| Supplied-terms case `trace.json` | `567b194c9ec8f9190dc7a6e76f19bc30b8478742e694dc55ea555a0ba83cf31f` |
| Supplied-terms case `receipt.json` | `bd350290d6e7719f359ffcc1d777800b43718acdc8adf9a424e76e7bf3cebcb4` |

Final owned-file hashes:

- `world_rejected_replay_v2.json`: `4244407a0f4cd312ff19c8e5dc65f17febebe7afde800779ea7b37237dc9db1b`.
- `test_world_public_grammar.py`: `885cd06b9cbd6f821532ccccf98d3ca9d7a1d0d70de09d80dac1e1bd55cb14eb`.

## Verification and handoff

AST parsing passed again without importing or executing the authored test module. Standard-library verification confirmed all three case identities, completed receipts, canonical spec/trace bindings, four rounds/five snapshots per case, 59 total captured slots, and the expanded fixture hash. No tests, linter, providers, agents, or application imports ran in this worker.

At authoring, `contracts.py`, `store.py`, `controller.py`, and `observations.py` hashes matched the archived v2 source hashes. The kernel differed as expected from parent-owned work and was observed at `bc8d936d8dbb27a7882bc140e13307c502efd38b7740a5a72f93e817f2ec114a`; this worker did not edit it. Shared `contracts.py` and `store.py` had no working-tree diff. The final parent frozen-source manifest is the acceptance authority.

### Parent guarded acceptance

The parent completed the frozen guarded run at `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-public-grammar-first-20261016T193911Z-6at6fp8z/evidence`. This worker read only its saved `junit.xml` and sibling `verification-summary.json` / `source-manifest.json` to record acceptance; it did not rerun anything.

- Full run: **537 passed**, **0 failures**, **0 errors**, **0 skipped**, **58.837 seconds** (58.84 seconds rounded).
- This test module: **28 passed**, **0 failures/errors/skips**, covering three actual full historical replays, the v2 cached rejected-decision recovery, and the helper parity cases.
- Verification summary: `exitCode: 0`, `files: 523`, `sourceDrift: []`.
- Frozen test and fixture SHA-256 values exactly match the final hashes recorded above.
- The parent reports that an independent reviewer compared all three original specs/traces and all 59 captured slots exactly. This is separate source-comparison evidence, in addition to the executed replay assertions.

The real controller/store replay preserved the captured observations, semantic heads, histories, events, resolutions, and rejected intents, including read-only reopen. The cached variant added no dispatch attempts. Scripted zero usage and unused HTTP traps passed as assertions; this remains semantic replay evidence, not historical provider-billing reconstruction or evidence about the new live run.

The bounded replay work is complete. Parent phase 7 live work is active and source is frozen. Per the parent's final instruction, this update changes only `public-grammar/replay.md`; no further source, runtime, provider, or commit actions will be performed by this worker.

## Updates

- 2026-10-16T19:27:40Z: Read the follow-up plan, controller, validation/helper boundaries, and bounded JSON source shape; created the scoped replay handoff. Parent-owned kernel and budget edits are present and will be preserved.
- 2026-10-16T19:30:31Z: Copied and hash-bound the complete selected case, authored the two real-controller/store replay paths plus focused helper parity cases, completed AST-only and standard-library integrity checks, and froze the owned files for parent guarded execution.
- 2026-10-16T19:33:38Z: Applied the queued scope expansion: copied the two exact original rejected cases and their own preregistered specs, parameterized full replay over all three cases while retaining only the v2 cached variant, verified all eight original source JSON hashes unchanged, and announced the new bounded three-case freeze.
- 2026-10-16T19:46:52Z: Recorded verified parent guarded acceptance (537 total tests, including all 28 replay/helper cases, zero failures/errors/skips, 523 frozen files with no drift), matching frozen hashes, and the parent-reported independent comparison of all three captures and 59 slots. Marked the bounded replay work complete and stopped under the phase 7 source freeze.
