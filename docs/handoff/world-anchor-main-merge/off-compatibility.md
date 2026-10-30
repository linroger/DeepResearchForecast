# Off-mode compatibility during the main merge

Updated: 2026-10-30T08:11:28.286423+00:00. Branch: `codex/world-anchor-main-merge`. Status: bounded off comparison and reflexive gate 10 accepted; production and test source remain frozen for the running 107-module composed gate.

## Request and acceptance

Preserve the retained `9916b3beff6753cd07f2407f36428ca2030127fd` payload and its historical `960d2466fff5be6edc329df3972728dbbac5600280252479999b22e91e478e92` pin. Compare a coherent archived main `f773f61bee4eed6e2c3be23e546d114ff2a786e8` application and bridge with the merged source through the existing offline guard. Review every config, request and state delta; retain RNG and no-extra-anchor-call guarantees. Edit only the historical snapshot function, the new off test and prefixed fixtures, and this note.

The user explicitly requested the main merge. Index stage 2 is main; stage 3 is feature `43efe06defc78de9bedda73d1708ba4c750a6150`; their common ancestor is `6ab52f7746bf7ec55e9f9921c71ba4ab08e33c01`. The historical receipt is a third, retained reference, not the merge base.

## Completed work

The existing snapshot test now checks the complete merged payload against two independent reconstructions: archived main plus five exact C11 deltas, and the retained historical payload plus twelve exact main deltas. Each replacement asserts the old value before applying the new value; additions require an absent key. No fields, prompts, values, unknown keys or RNG state are ignored. Both reconstructions must agree before comparison with the runtime payload. All baseline and merged digests are recomputed.

The existing module's bytes outside `test_off_mode_config_prompt_state_and_rng_snapshot` match the opening copy exactly. This includes the parent's `arbiter_repair="field"` selection in the mixed primitive/derived consequence test. No other assertion changed. The parent released the first shared-module hold before this edit; the entire module is now frozen again. Readiness and exact source hashes were sent directly to Kuhn (`01a18b9e-773b-7922-b539-384cd30d1a47`) for gate 10.

Owned deliverables:

- [Historical snapshot test](../../../backend/tests/test_world_anchor_reflexive.py).
- [Main-merge comparison and two task-validation controls](../../../backend/tests/test_world_anchor_main_merge_off.py).
- [Portable synthetic probe](../../../backend/tests/fixtures/world_anchor_off_probe.py).
- [Retained historical payload](../../../backend/tests/fixtures/world_anchor_off_historical.json), [actual archived-main payload and model requests](../../../backend/tests/fixtures/world_anchor_off_main.json), and [reviewed exact deltas with parent source hashes](../../../backend/tests/fixtures/world_anchor_off_reviewed_delta.json).

Only synthetic Acme data, requests and reviewed deltas are in these fixtures. The archived source corpus remains ignored under `.pytest_cache/private-artifacts/world_anchor_off/main-f773`.

## Baseline provenance

The original receipt came from `/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-reflexive-review-20261030-01/off-mode-snapshot.json`. Its complete payload recomputes to the retained `960d…` hash. This task did not rerun `9916`; it validated that supplied receipt and executed actual main.

A stdlib-only `git archive f773 -- backend/app deerflow_bridge backend/scripts/main_offline_pytest.py backend/tests/conftest.py backend/tests/forecast_task_fakes.py` produced the coherent main tree. The archive SHA256 is `5302de46b1ded3963e699549b4523f743da98bb1868901e855fdb64350b70dad`. All 228 archived files were hashed and rechecked unchanged before acceptance. Main's guard was not modified. The portable probe was also executed in that archived tree to verify that the committed helper reproduces the original independent probe's payload and all generator requests exactly.

All application imports used `/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B` through the selected tree's `backend/scripts/main_offline_pytest.py`. Outside the guard, scripts used only stdlib for archive, copy, hashing, AST inspection and receipt analysis. The guard redirects storage and disables ambient dotenv/plugins. The fixture substitutes only the synthetic model, optional official-data loading and the manager-owned backtest-pressure lookup, matching the original producer fixture. Real generator, typed-task validation, calendar, seed, world model, prompt and decision parsing run.

| Payload | SHA256 |
|---|---|
| Retained `9916` | `960d2466fff5be6edc329df3972728dbbac5600280252479999b22e91e478e92` |
| Executed `f773` main | `25980415f90f4a80a4d4a69af5b250f8e144aed105b254940a670127f305bd41` |
| Executed merged tree | `5613af9445171bc6db845569596eef8ed70374a7df3592de61c637dca48c99d6` |

## Intentional main changes relative to the historical receipt

These are all twelve exact changed paths; the JSON fixture retains complete values, including strings and full arrays.

| Payload paths | Change and source |
|---|---|
| `config/agent_configs/0/actor_id`, `config/agent_configs/0/preparation_audience` | Add stable `actor_822b33ad87c148a0` and `actor`. Main `simulation_config_generator.py`, `_generate_agent_configs_batch`, lines 3650–3654. |
| `config/forecast_task_v1` | Add typed task inputs, source quote, independent semantic review, input/task hashes and explicit round limit 3. Main `simulation_config_generator.py`, `admit_forecast_task`, lines 514–586; `forecast_task.py` binds and validates the task. |
| `config/temporal_config/horizon_source`, `n_rounds`, `round_cap_coarsened`, `round_dates`, `unit`, `warnings` | Source becomes `llm`; fourteen weekly periods become two quarterly periods under the explicit cap of three. The endpoint remains exactly 2027-01-31. Main `admit_forecast_task` applies the cap; `app/utils/sim_timeline.py`, `build_timeline`, lines 541–606, coarsens coverage without truncating it. |
| `config/time_config/total_simulation_hours` | Calendar compatibility shim follows the admitted count, changing 14 to 2. |
| `config/generation_reasoning` | Reports the admitted quarterly timeline, two rounds and model-based task resolution. |
| `calls/0/messages/1/content` | The JSON contract retains main's support for integer actor IDs on persisted fulfillment targets. This is the sole historical-to-merged message difference; the rest of the user prompt and the entire system prompt are unchanged. Source: main `agent_decision.py`, `build_decision_prompt`. |

The actor identity and preparation-audience fields are the main preparation changes visible in this small unsealed producer fixture. There is no sealed `preparation_context`, parsed research variable, action execution or arbiter transaction here. The exact world settings remain `arbiter_enabled=true`, `max_change_ratio=0.5`, and `barrier_timeout_s=1800.0`. Main's atomic default and explicit `affordable-menu-v2` behavior are covered by the coordinator/reflexive controls; this receipt does not claim to execute those branches.

## Intentional C11 changes relative to executed main

These are all five changed paths. No unexplained difference was found.

| Payload path | Reviewed change |
|---|---|
| `config/world_model/actors/0/capacity_per_round` | Firm capacity increases from 2 to 3. Feature `agent_decision.default_capacity` permits every canonical class action; the real seed uses it. |
| `world/actors/0/capacity_per_round` | Runtime preserves that same capacity, 3. |
| `world/actors/0/action_rejections` | Adds the empty durable typed rejection list from feature `ActorState`. |
| `calls/0/messages/0/content` | Uses C11's dedicated JSON decision system with actor state, capacity and instruction/data separation. |
| `calls/0/messages/1/content` | Moves the fenced role evidence into user data; renders capacity 3, fixed action costs, available custom kinds and separate zero-cost deliveries. Main's integer-target contract remains. |

The reviewed delta fixture pins the exact parent source hashes and symbols for all six source references. Each reference was checked against `git show <full-parent>:<path>` and parsed to confirm its named symbols exist. C11 source is `43efe` `agent_decision.py` and `world_model.py`; the principal current consumers are `default_capacity`, `build_decision_system_prompt`, `_decision_dossier`, `build_decision_prompt`, `elicit_decision`, and `ActorState` serialization.

The complete merged world state equals the historical world state. The seeded RNG representation is identical before and after round start, shocks and decision elicitation, and identical across historical, main and merge payloads. Main and merge make the same four complete generator requests: task extraction, independent review, event configuration and actor configuration. There is one generator instance and one actor decision request. The comparison test also traps any call to anchor runtime or actor-payload projection. Neither is invoked.

## Verification and exact source bracket

Accepted final checks:

- Archived-main replay: **1 passed**, zero failures/skips, in 1.89 seconds. [Completion receipt](/private/tmp/world-anchor-main-merge-off-main-20261030-02/completed.json), [JUnit](/private/tmp/world-anchor-main-merge-off-main-20261030-02/junit.xml).
- Merged snapshot, full comparison and both source-validation controls: **4 passed**, zero failures/skips, in 2.33 seconds. [Completion receipt](/private/tmp/world-anchor-main-merge-off-final-20261030-03/completed.json), [JUnit](/private/tmp/world-anchor-main-merge-off-final-20261030-03/junit.xml), [full comparison payload](/private/tmp/world-anchor-main-merge-off-final-20261030-03/off-mode-main-comparison.json).
- Unsupported task-source quotes still raise `ForecastTaskError`; failed independent semantic reviews still raise it. The task validator and source checks were not patched.
- Scoped Ruff F821/F811/F822/F823 and `git diff --check` passed. AST and exact-byte comparison confirm all unrelated existing-module content is preserved.

Both accepted guards exited 0 after shutdown, preserved identity, and recorded only three storage redirects. They recorded **zero blocked attempts**, zero registered source drift and no child processes. This is CPython audit-hook evidence, not an OS sandbox or provider-health test.

The final source bracket covers 189 files, including every app/bridge Python source, the guard, both tests, original producer helper, task fake and four new prefixed fixtures. It opens at `2026-10-30T08:03:52.510255+00:00` and closes at `2026-10-30T08:07:45.355673+00:00` with no drift. [Source before](../../../.pytest_cache/private-artifacts/world_anchor_off/acceptance-source-before.json), [source after](../../../.pytest_cache/private-artifacts/world_anchor_off/acceptance-source-after.json), [verification summary](../../../.pytest_cache/private-artifacts/world_anchor_off/verification.json).

| File | SHA256 in the accepted bracket |
|---|---|
| `backend/app/services/simulation_config_generator.py` | `cc7a5403c9c17486a6a66f1011b8a827af11eaf02db8e5b06ffec7b5047eb50b` |
| `backend/app/services/agent_decision.py` | `8e209cbf4cf975146600aac313ffaf3377502d14240de7ae9d3efe2b78658bc3` |
| `backend/app/services/world_model.py` | `2f93c4e7b42892946570272116c29e2c22c4b1560e9296ad8784182becbf08d3` |
| `backend/app/services/world_model_seed.py` | `f0fb32b0f301c01198d8b0c9faa56379878197d08649c05f1e3a003e88aba545` |
| `backend/app/services/world_update.py` | `a1dba607d557c191258e4d4e122f2c55fa85d6a792eaf3c38278cf5ad944a895` |
| `backend/tests/test_world_anchor_reflexive.py` | `c7efaf05c597e0d68737d4aa276c312fd6836ae797318551d0a5e2018d2ab3e6` |
| `backend/tests/test_world_anchor_main_merge_off.py` | `6953941f4c290899944687ae2dddde20329e65e038627cc08de332a6c7fa5d96` |
| `backend/tests/fixtures/world_anchor_off_probe.py` | `bd023f48e4789721424c199cb5ad71bf9c7b2271871cabffc56a62120d289abb` |

The first merged diagnostic probe preceded the other owner's immutable-anchor transactional-copy fix. Between the first probe and final acceptance, `world_update.py` changed from `083d365b8522098f1c11c18939ca1019c9ab3897e7aa83bdfc8bf22016b74128` to `a1dba607d557c191258e4d4e122f2c55fa85d6a792eaf3c38278cf5ad944a895`. This is documented between-run drift, not drift within either accepted run. The off payload remains `5613…`. The intermediate four-case gate `off-final-20261030-02` passed before a source-reference symbol was corrected from `_generate_agent_configs` to `_generate_agent_configs_batch`; final gate 03 verifies the corrected fixture bytes.

Reproduction from the integration worktree:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B \
  backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/world-anchor-main-merge-off-NEW \
  -q backend/tests/test_world_anchor_reflexive.py::test_off_mode_config_prompt_state_and_rng_snapshot \
  backend/tests/test_world_anchor_main_merge_off.py
```

Use a new evidence directory. To replay archived main, run its unchanged guard from `.pytest_cache/private-artifacts/world_anchor_off/main-f773` with `-q backend/tests/world_anchor_off_archive_probe.py` and another new evidence directory.

## Reflexive gate 10 confirmation

The source owner reported gate 10 green. Read-only inspection of its [completion receipt](/private/tmp/world-anchor-main-merge-reflexive-20261030-10/completed.json) and [JUnit results](/private/tmp/world-anchor-main-merge-reflexive-20261030-10/junit.xml) confirms **606 tests, zero failures, zero errors and zero skips**, in 122.17 seconds. The JUnit names include the historical snapshot, complete off comparison and both task-validation controls. The owner reports zero deselections. The completed guard exited 0 after shutdown, preserved identity and recorded no source drift. Both supplied test-module hashes match the receipt and current files exactly.

This confirms the focused off result within the broader reflexive suite. The separate 107-module composed gate at `/private/tmp/world-anchor-main-merge-composed-20261030-01` remains running as reported by the coordinator. Its broader production/test hold remains in force. This update changed only this handoff note; no production, test or fixture source changed.

## Remaining work and handoff

No bounded off-comparison implementation or acceptance item remains. Reflexive gate 10 has passed; the coordinator owns the still-running 107-module composed gate and merge delivery. This slice made no production edits and performed no Git staging, commit or push. No provider was invoked. Private archives and evidence are ignored; the new synthetic fixtures and test are intentionally unstaged for the coordinator.

Ready-to-use continuation: “Read `off-compatibility.md`. Include the historical off snapshot and the complete `test_world_anchor_main_merge_off.py` in the composed gate. Preserve its source-backed historical/main fixtures and exact reviewed deltas. Keep the parent's explicit field-mode mixed-consequence call. If production changes, rebracket and rerun the four focused cases; investigate any new path difference before changing fixtures.”
