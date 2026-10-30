# Saved-world replay owner

Status: P2 raw-prestate repair implemented and source-frozen; ready for independent reviewer closure. Historical acceptance remains partial. This owner is limited to `backend/scripts/replay_saved_world.py`, `backend/tests/test_saved_world_replay.py`, and this record. The parent owns the private snapshot and shared handoff. No commits, pushes, provider calls, production writes, or runtime architecture changes are authorized.

## Design sent before implementation

The existing dossier replay prepares new worlds with scripted model responses; it cannot establish historical action or raw-response equivalence. Add a narrow, import-safe CLI that consumes an explicit frozen simulation directory, writes an explicit new aggregate JSON output, and runs only under the unchanged main offline guard. Its stopping condition is one finite pass over the supplied records. It must use real WorldModel and validation/commitment helpers, with no provider construction.

Inventory precedes replay. Both specimens lack `arbiter_raw.jsonl` and per-round full state. Their history `arbiter` objects contain application counts and summaries, not raw responses. Keep raw validation unavailable unless a capture and appropriate state actually exist. Controlled raw inputs are separate test evidence.

Recorded-action checks reconstruct only the local prerequisites justified by retained commitment creation fields, interaction terms, action rows and period records. Deadline and grace comparisons are conditional on those inputs, never a historical full-world trajectory. Legacy deadline/grace rules are explicit scalar classifications anchored to the prior acceptance map; no second world kernel is implemented. Current action and breach behavior is exercised by the production helpers.

## Acceptance and evidence

| Requirement | Check | Evidence |
|---|---|---|
| Preserve originals | Hash all consumed frozen fixture bytes before/after success and failure | Aggregate receipt and tests |
| Honest raw coverage | Both missing captures remain explicit; summary cannot substitute | Saved specimen coverage |
| Real consumers | Deadline resolution, delivery admission and batch lapse use real WorldModel | Source hashes and controlled semantics |
| Valid raw control | Captured-style raw fixture reaches real field validation/application | Focused guarded test |
| Malformed inputs | Reject bad JSON/schema with sanitized diagnostics | Focused guarded tests |
| Private data stays private | Output only counts, status codes, file hashes and source anchors | Output schema assertions and review |

## Inventory findings

- `sim_2a4f7d0e73de`: 14 history rows, 138 structured action rows, 134 scenario-only decision rows. History reports 10 applied and four invalid arbiter rounds.
- `sim_1838cf014c0b`: nine history rows, 61 structured action rows, 61 scenario-only decision rows. History reports nine applied arbiter rounds.
- Neither history retains `snapshot_before`, `arbiter_raw` or full per-round state. Even a current `snapshot_before` would be compact and insufficient for restoring commitments or actor state.
- A final `world_state.json` and prepared `simulation_config.json` exist in both frozen specimens. Their private values are not copied into this document.

## Progress and remaining work

- Inventory and existing-tool assessment complete.
- Scoped input/coverage contract and real-helper checks complete.
- Controlled and specimen acceptance complete through fresh canonical `/private/tmp` evidence roots; final guard receipts and preservation hashes verified.
- Source review complete for the three owned files. No new runtime kernel blocker was reproduced. Independent external review was not dispatched under this task's no-model-call boundary.
- The parent can consolidate these aggregate results, preserve the private evidence directory durably, and decide the next separately authorized acceptance step. No additional source edits are needed for this owner's bounded scope.

## Updates

- 2026-10-28: Read the shared handoff, plan, receipt and first-ten acceptance map. Sent the concrete design before edits. Created this owner record; preserved the parent-owned dirty handoff.
- 2026-10-28: First guarded run `/private/tmp/drf-saved-world-replay-20261028-r1` passed 18 checks. The unchanged runner reported exit 0, shutdown complete, no source drift, no blocked operations, and only three expected storage redirects. Both fixture inputs were hash-preserved. Its source receipt remains historical after subsequent coverage changes.
- 2026-10-28: Initial results exercised 58/138 and 6/61 recorded actions locally. All 53 recorded deliveries were admitted without being marked fulfilled. Current acceptance handling yielded five acceptances, five counteroffers and one rejection across the specimens. These are conditional checks on retained inputs, not complete historical-state replay.
- 2026-10-28: Exact retained commitment-event matching identified eight historical lapse events per specimen, each one round after its recorded deadline. Added a real-helper check of those event-bound obligations under current grace, with ambiguous descriptions explicitly unbound. Added malformed raw-state/duplicate-interaction checks and fixed-code rejection classification.
- 2026-10-28: Expanded regression run `r2` passed 130 checks in 16.40 seconds, including the existing commitment and world-update suites. It also recorded one blocked socket construction, four blocked process launches, and 23 blocked external reads. This is contained attempted activity, not zero probes. Process names were uname, an unregistered executable, fc-list, and system_profiler; reads included native/font/config discovery and three attempts to read the external staging launcher's source. The broader integration imports are excluded from the final focused receipt; guards were not relaxed. Production code was unchanged throughout.
- 2026-10-28: Final `r3` passed 23 focused checks in 3.67 seconds with no skips. Added a preserved-input runtime-error control and exact expired-offer classification. `completed.json` records exit 0, completed shutdown, preserved identity, no drift and only the three expected app storage redirects. Frozen manifest plus all 100 frozen file hashes match, as do tested source hashes.
- 2026-10-28: A final workspace check caught concurrent parent edits to `world_model_seed.py` after r3. Preserved those edits and reran the unchanged 23 focused checks as `r4`, passing in 1.96 seconds with no skips or blocked operations. Results are unchanged; r4 is now the current receipt. Seed hash is `58933d83ef6b11347e3b82bcce36574ef5710bb55e05930bce4c3513a9b21db4`. All 100 frozen input hashes and all r4 tested sources matched at closing verification. Parent changes to simulation configuration and agency classification remain outside this owner's review.
- 2026-10-28: Independent review found P2: raw prestates with duplicate registry identities reach permissive `WorldModel.from_dict`, which silently overwrites them before replay credit is awarded. Prior source-review completion was therefore insufficient for this boundary. Added controlled malformed registry/reference regression cases before changing the script. Repair design: reuse final-state actor/commitment identity checks, reject duplicate/missing actor, variable, interaction and directed relationship identities plus invalid required references before model construction, and retain legitimate shared names/aliases. The world kernel is outside scope. The independent reviewer owns closure.
- 2026-10-28: Guarded red gate `/private/tmp/drf-replay-prestate-20261028-red` produced 16 expected malformed-input assertion failures while both valid raw controls passed. Duplicate actor/variable/interaction/relationship cases incorrectly exited 0; a dangling agreement incorrectly reached runtime exit 3. Green controlled gate passed 38 cases with the two private-specimen tests deliberately deselected. Final frozen gate `/private/tmp/drf-replay-prestate-20261028-final` passed all 40 cases in 2.11 seconds with no skips. All three gates had only the three expected storage redirects and no blocked operations. The source freeze and updated private specimen receipts below supersede r4 for the repaired code; Arendt owns independent closure.

## Guarded fixture staging

The main runner requires a nonexistent evidence directory and installs its guard immediately after creating it. The standard-library-only launcher `/private/tmp/drf-saved-replay-stage-20261028.py` intercepts **only that exact directory creation**, immediately restores `Path.mkdir`, copies eight files from the receipt's frozen snapshot into `fixtures/<simulation>/`, verifies copy hashes, and then resumes the unchanged runner. All copies exist before its audit-hook installation and any app import. No guard code, read roots, protections, environment policy, or import redirections change. The launcher verifies the frozen manifest hash and retains itself and a sanitized staging receipt in each evidence directory. Original uploads are never accessed.

The final launcher additionally checks every staged source hash against the frozen manifest, rather than merely comparing a fresh source hash to its copy. This strengthens provenance without reading original saved uploads.

## Final scenario results

| Aggregate | sim_2a4f7d0e73de | sim_1838cf014c0b |
|---|---:|---:|
| Retained history rounds | 14 | 9 |
| Retained structured actions | 138 | 61 |
| Conditional local action checks | 58 | 6 |
| Actions outside those checks | 80 | 55 |
| Recorded delivery actions admitted by current helpers | 53 | 0 |
| Delivery actions automatically marked fulfilled | 0 | 0 |
| Recorded acceptance actions checked | 5 | 6 |
| Current accepted / countered / rejected | 3 / 1 / 1 | 2 / 4 / 0 |
| Accepted obligation pairs with retained deadlines | 3 | 2 |
| Those deadlines changed from legacy lag-only rule | 0 | 0 |
| Exact historical lapse events bound to retained obligations | 8 | 8 |
| Those lapse events preserved by current grace helper | 8 | 8 |
| Raw historical responses replayed | 0 | 0 |

The 53 delivery checks all fall within the original recorded due windows. They do **not** supply historical grace-window delivery evidence; controlled due/grace/expired cases cover that boundary. All 16 observed lapse events occurred at recorded due-round + 1. With the explicitly assumed still-open promise, the actual current helper leaves it open during grace. This establishes the conditional classification change, not a replay of later historical outcomes.

For the five currently accepted pairs, the real helper keeps both obligations open at due + 1 and breaches both at due + 2 if neither delivers: ten breach events and zero released obligations across these independent probes. No recorded deadline shift was found in those five pairs. A controlled three-period term verifies the deadline-parser change separately. Legacy comparisons are the old scalar `round + max(1, lag)` deadline and `due < round` lapse rule, anchored in the existing first-ten acceptance map and `test_world_commitment_fulfilment.py`, `test_world_update.py`, and `test_world_model.py` regression narratives; no historical engine is reimplemented.

Five historical accept actions become counteroffers when their supplied terms change the offer. The single rejected action in sim_2a4f7d0e73de is after the retained offer expiry and reaches the real `invalid offer response binding` guard. These are observed differences under stated local prerequisites, not newly discovered kernel failures. No private terms, actor names, action text, rationale or transcripts appear in the receipts or this document.

The valid controlled raw capture changes one real state variable under both policies. With an additional malformed events field, field repair changes the valid variable while round rejection changes none. Both tests load an explicitly supplied full pre-arbiter WorldModel state. The fixture-only `pre_arbiter_world` field is not claimed to be a field retained by production. Production `arbiter-raw/v1` currently stores response/attempts but no full pre-arbiter state; captures alone therefore would not prove full stateful replay.

## Prior r4 reproduction and source state (before P2 repair)

Final private evidence root: `/private/tmp/drf-saved-world-replay-20261028-r4`. The root contains private staged copies; only its aggregate receipts, hashes and source references are suitable for publication.

Reproduce with a **new**, nonexistent canonical evidence directory. The launcher executes the existing `backend/scripts/main_offline_pytest.py` entrypoint unchanged, with the arguments below and the same isolated interpreter flags:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B \
  /private/tmp/drf-saved-world-replay-20261028-r4/staging-launcher.py \
  --evidence-dir /private/tmp/drf-saved-world-replay-20261028-NEXT \
  -q --tb=short backend/tests/test_saved_world_replay.py
```

Run from `/Users/rogerlin/.codex/worktrees/first-ten-remedies/DeepResearchForecast`. Ordinary guarded unit execution can invoke `main_offline_pytest.py` directly; the two private-specimen tests explicitly skip if their frozen fixtures were not staged. The final acceptance above had no skips. The replay CLI requires `--input` and a new `--output`, refuses unguarded execution, requires both paths inside the evidence read/write boundary, forbids output inside input, reads a fixed five-file inventory with a per-file size limit, and stops after a finite pass. Exit 0 means diagnostics produced, not full historical equivalence; malformed input exits 2 and runtime failures exit 3 with sanitized type-only diagnostics.

| Artifact | SHA-256 |
|---|---|
| backend/scripts/replay_saved_world.py | ef5ac51bca0c0dc83dc91a1e69ab79bdd65b98609f2f9c32ef11420712dd3c6a |
| backend/tests/test_saved_world_replay.py | 404c7773a888aa6c7a50506b07d1c06d91626384fd17c455c11650b4f8ce6ad4 |
| Unchanged main_offline_pytest.py | 5046cf820fa468d8e8ffb2e3fdade1d20fca2f0bd56ee15eabdff51c223c02be |
| sim_2a4f7d0e73de-replay.json | 23e52f2c17be863dc7312efdca844d25cf514dc82ff4500f09d78790653e9a50 |
| sim_1838cf014c0b-replay.json | 4b67f71e085631a464bd681366923e12a8d96c98289f8b9988e6aafafaee2fec |
| completed.json | b0d57b1cf2407be8d84da295de0a7b6b4e34d1c7aa8fc9127a04571f1fc9dac0 |
| junit.xml | ef87418c88af32a97c5f158d474e215852e2c08a44ab1094c1de629ed79fe866 |
| preservation.json | 8d98ff956d10722765872851f6a7adda17bda71b52db7bbf4ed79109405fd39c |
| staging.json | f95da3b08f0e593577fd6d4b5394bb80e9fefc985456a036ac412b439b73ecdc |
| staging-launcher.py | 8767e98cb6de8bcd347f1e901e00b94b2d77ffae520e1d559d04bb33f6556360 |

The aggregate per-simulation receipts also record hashes of the actual WorldModel, world-update, seed, decision and text-budget code. Input hashes are compared before/after successful CLI calls, and success/malformed/runtime-failure tests independently verify fixture preservation. Original frozen files were independently rehashed against all 100 manifest entries after the final run. No source drift was detected. Syntax checks passed; source review found no remaining actionable issue in this bounded tool.

## Parent handoff and remaining evidence limits

Suggested continuation prompt: “Read the P2 source freeze below and relay its exact script/test hashes to Arendt for closure. Compose the parent's frozen affected gate using those bytes, then consolidate the conditional 64/199 action checks and 16 event-bound lapse checks from the updated final receipts. Preserve the final evidence and source freeze privately before temporary storage is cleaned. Do not label missing raw history as replayed or infer a full historical trajectory.”

All three owned files remain uncommitted as requested. Parent-owned handoff, snapshot and case/cast/projection work are preserved. No provider calls, intentional network probes, scheduler changes, deployment, commits or pushes were made. The expanded regression receipt's blocked native/import probes remain explicitly disclosed above.

## P2 repair source freeze — ready for Arendt

The raw-prestate boundary now validates identity registries and required references **before** constructing `WorldModel`. Shared final-state checks reject duplicate/coerced/missing actor IDs, duplicate commitment IDs and invalid interaction identities. Raw-only checks add unique explicit variable IDs, canonical interaction keys, unique directed relationship pairs, cast endpoints, reciprocal agreement/obligation/counterparty references, and explicit effect/event variable references. Missing registry references are rejected rather than fabricated. Shared names and aliases remain legal, and reciprocal directed edges remain distinct. No world-kernel source was changed.

Every malformed regression asserts CLI exit 2, a sanitized fixed-code `invalid_input` result, zero calls to `WorldModel.from_dict`, no valid-structural/replayed credit and unchanged input hashes. The valid raw fixture still exercises the real field/round repair paths. Missing raw files in the actual specimens remain missing; their conditional coverage and all other aggregate semantics exactly match r4.

Final evidence directory: `/private/tmp/drf-replay-prestate-20261028-final`.
Source copies captured before the final gate: `/private/tmp/drf-replay-prestate-20261028-sourcefreeze`.
The eight-file source-freeze receipt is also copied into the final evidence directory. Closing comparison found no source-freeze drift, no replay-source drift, and no differences across the frozen snapshot's 100 manifest entries. No tests beyond the focused replay suite were added to the final gate; the parent owns the combined affected gate.

| Current artifact | SHA-256 |
|---|---|
| backend/scripts/replay_saved_world.py | d29c4b0c244fe4bc15cc87b604a49e69ce8b391a30671da2a5123e1739438947 |
| backend/tests/test_saved_world_replay.py | 1d474ccbe029e1924ad4b5e17d3dac56b7a5b07e474b3ad2efe70d088611ade5 |
| Unchanged world_model.py | 805c5f67e26176de9ac722145aa4662627b8c9d58a8d522fa6c1a3997752067a |
| Unchanged main_offline_pytest.py | 5046cf820fa468d8e8ffb2e3fdade1d20fca2f0bd56ee15eabdff51c223c02be |
| source-freeze.json | a952d6d377bb10371631f072c6a301b53cc81beb872181e3939f403e17dff02e |
| sim_2a4f7d0e73de-replay.json | 700562bbc24f3a9870041709170e9fd6ea1c2175cb5c99e8d9a55c975003eb2a |
| sim_1838cf014c0b-replay.json | 772eae82710cb87be07f377181c3e61d6979117c1b76cb9f714b415847a5f6fa |
| completed.json | e001571ca001ac42a4e5f9216d3586ad776ac013ae2251989951ec56af43050e |
| junit.xml | d14ba3f5416631bc7ef2c81e1bc25590bd8a6dbae969945854a4d1784b20b095 |
| preservation.json | 3e1f095cc3822ed8a663d3cbf7492f0b045a4c568fa0638ba611d41ae89c25bc |

Reproduce the final specimen gate with the same isolated interpreter and the retained standard-library staging launcher, substituting a new evidence root:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B \
  /private/tmp/drf-replay-prestate-20261028-final/staging-launcher.py \
  --evidence-dir /private/tmp/drf-replay-prestate-20261028-NEXT \
  -q --tb=short backend/tests/test_saved_world_replay.py
```

For the controlled regression only, invoke the unchanged `backend/scripts/main_offline_pytest.py` directly with a new evidence root and `-k 'raw_prestate or controlled_raw_capture'`. The independent review's old characterization assertions intentionally describe the pre-fix bug; the reviewer should verify rejection against these frozen bytes before closing P2. The replay owner will make no further script/test edits unless a new finding requires them.
