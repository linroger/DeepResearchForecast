# Fresh-run world default readiness audit

**Recorded:** 2026-10-17T14:22:30Z
**Source baseline:** `120c44cd39972feb884dc648573a80e1ecf469ce`
**Status:** Bounded helper/fresh-launch findings closed against the coordinator's current guarded integration receipt. Source/tests remain frozen. Section 11 is current; broader regression, frontend/browser and live/full-behavior acceptance remain pending.
**Scope:** Research request/UI → pipeline admission/options → world modeling/policy → PREPARE/RUN, including compatibility at shared callers.

Only this document is authorized for writing in this audit. The coordinator owns the withheld-response diagnostic, phase13 execution, budgets, source freeze and release decision. No application import, test, provider request, credential read, delegation or code change was performed. The relevant runtime files cited below had no working-tree diff when checked. Concurrent edits to `consistency_evaluation.py`, the parent handoff and diagnostic artifacts belong to the coordinator and were not altered or assessed here. These findings are not permission to promote before the gates in [PLANS.md](PLANS.md) pass.

The terms MUST, SHOULD and MAY in the proposed contract below are normative requirements for a future implementation, as defined by RFC 2119; they do not describe implemented behavior.

## 1. Finding and release boundary

Changing an engine literal alone will not produce a usable world default. Ordinary UI launches provide neither a raw world model nor a modeling policy. Current launch preflight cannot detect that omission, so a world-selected request can complete research, ontology and graph work before failing at PREPARE. A safe fresh default needs one shared admission resolver, explicit operator/request policy, consistent readiness and preserved saved-run semantics.

The proposed approach is appropriate with three qualifications:

1. `StrictHTTPModeler` construction and closure validate local transport configuration, not complete world admission. Total budgets, safe forecast effect, review policy and calendar constraints require separate checks.
2. A period cap does not establish a target horizon. The requested endpoints must be independently resolved and bound before model dispatch, then compared with the candidate before sealing.
3. The new-run default must be distinct from every saved-state fallback. Existing missing pins mean legacy, including after release.

The initial resolver implementation MUST keep the fresh engine default `oasis-legacy`. The coordinator can change that one fresh-admission default to `world-v1` only after the release gates pass. No tariff, spending allowance, provider capability assertion or behavioral pass is supplied by this document.

## 2. Current source trace

| Boundary | Observed behavior and source | Consequence |
|---|---|---|
| UI submission | [ResearchView.vue:460](../../../../../../frontend/src/views/ResearchView.vue#L460) sends prompt, mode, depth, max rounds, research language and research model. [research.js:28](../../../../../../frontend/src/api/research.js#L28) forwards the body once. | There is no engine/policy selection or world profile in the ordinary request. The research `model` field is not the world policy model. |
| Research POST | [research.py:100](../../../../../../backend/app/api/research.py#L100) resolves missing engine to legacy but forwards world arguments only when a world-related key exists. | Changing only the API fallback does not change a prompt-only request. A policy/spec without an engine currently still selects legacy. |
| Pipeline creation | [pipeline_orchestrator.py:8560](../../../../../../backend/app/services/pipeline_orchestrator.py#L8560) independently defaults to legacy, creates directories and a task, saves options/actor/safety policies and starts a thread. | The resolver must run before these side effects and serve direct callers as well as HTTP. |
| Readiness | [pipeline_orchestrator.py:7266](../../../../../../backend/app/services/pipeline_orchestrator.py#L7266) accepts only mode and research model. [research.py:366](../../../../../../backend/app/api/research.py#L366) exposes GET readiness; [preflight.py:105](../../../../../../backend/scripts/preflight.py#L105) reuses the same check. | These checks do not validate world policy, prices, review mode or budgets. |
| World branch | [pipeline_orchestrator.py:13645](../../../../../../backend/app/services/pipeline_orchestrator.py#L13645) selects world stages after GRAPH. [pipeline_orchestrator.py:8457](../../../../../../backend/app/services/pipeline_orchestrator.py#L8457) chooses raw spec, saved handoff candidate, then modeling policy; none produces `world_model_not_ready`. | A fresh admission must not rely on a candidate that does not yet exist. |
| Model production | [modeler.py:22](../../../../../../backend/app/services/world_simulation/modeler.py#L22) requires positive total budgets, journals at most two requests and binds messages/policy. It copies caller policy and subtracts preparation charges from execution budgets at line 99. | No inferred policy, renewed allowance or independent unaccounted modeling budget is needed. Preserve this accounting. |
| Compilation/seal | [service.py:74](../../../../../../backend/app/services/world_simulation/service.py#L74) models only when raw spec is absent, compiles, pins the new queue policy and seals. [compiler.py:495](../../../../../../backend/app/services/world_simulation/compiler.py#L495) rejects modeling gaps and validates source-backed records. | A supplied raw spec bypasses the modeler; its own policy is authoritative. Separate `world_policy_spec` is not merged into it today. |
| Execution | [simulation_manager.py:919](../../../../../../backend/app/services/simulation_manager.py#L919) saves generation/manifest/spec pins. [simulation_runner.py:520](../../../../../../backend/app/services/simulation_runner.py#L520) dispatches world from the saved engine. [service.py:160](../../../../../../backend/app/services/world_simulation/service.py#L160) validates inputs and policy before the child. | Preserve these execution guards and the committed-horizon completion requirement. |

## 3. Configuration and input blockers

### 3.1 Explicit provider and pricing authority

The source default for `Config.LLM_PROVIDER` is `claude-cli` ([config.py:750](../../../../../../backend/app/config.py#L750)). This is a source default, not a finding about the active machine configuration. World policy rejects CLI transports and requires a catalogued OpenAI-compatible HTTP provider ([policy.py:259](../../../../../../backend/app/services/world_simulation/policy.py#L259)). Production construction also requires the configured provider and resolved endpoint to match the pinned policy and authentication to be available. A successful research-provider preflight therefore does not establish world readiness.

The policy requires provider/model/base URL, timeout of 1–120 seconds, positive input and output bounds, and pricing bound to the same identity. Pricing must include a dated source reference, positive conservative input/output rates, context size, maximum output, framing overhead, an allowed output-token parameter and `maxOutputIncludesReasoning=true`. The adapter validates declarations; it does not verify vendor documentation or prove those guarantees. Provider/rate evidence remains an operator/release responsibility.

There is no current `WORLD_POLICY_SPEC_PATH` setting or automatic default profile loader. Existing settings select a general provider, not this complete sourced policy. Missing/unsupported configuration must produce an actionable local readiness failure, without a silent CLI or legacy fallback.

### 3.2 Budgets, forecast effect and consistency mode

`StrictHTTPModeler` inherits the transport constructor and needs only policy metadata plus `limits.maxOutputTokens` ([policy.py:679](../../../../../../backend/app/services/world_simulation/policy.py#L679)). It does not validate a positive total `maxTokens`/`maxCostUsd`, all actor limits, safe forecast effect or the required review pin. Those cannot be inferred from successful construction.

The schema default cost ceiling is zero ([contracts.py:24](../../../../../../backend/app/services/world_simulation/contracts.py#L24)); it is not a paid-run default. World allows only `diagnostic_only` and `no_update`, while configuration accepts additional forecast-effect strings ([config.py:1527](../../../../../../backend/app/config.py#L1527), [contracts.py:192](../../../../../../backend/app/services/world_simulation/contracts.py#L192)). The effective pipeline safety snapshot and world effect must agree before admission.

Missing `policy.decisionReview` currently means no consistency revision. Both v1 and v2 are understood, and review requires the two-call slot allowance ([review.py:16](../../../../../../backend/app/services/world_simulation/review.py#L16)). Fresh release-mode world admission must explicitly select the mode covered by the release receipt; the current proposed candidate is `actor-consistency-v2`, conditional on the coordinator's gates. Do not silently upgrade old absent/v1 pins. Unresolved revisions must remain failures with no replacement allowance ([controller.py:51](../../../../../../backend/app/services/world_simulation/controller.py#L51)).

### 3.3 Calendar and source-dependent checks

The UI advertises a cap that coarsens time rather than truncating the horizon ([ResearchView.vue:93](../../../../../../frontend/src/views/ResearchView.vue#L93)). The world preparation path currently does not consume `options.max_rounds`; runtime overrides are rejected against the sealed world ([simulation_runner.py:523](../../../../../../backend/app/services/simulation_runner.py#L523)).

The calendar validator checks 1–1000 contiguous periods and then derives `asOf` and `horizon` from the first/last periods ([contracts.py:224](../../../../../../backend/app/services/world_simulation/contracts.py#L224)). It cannot prove that a generated candidate retained an independently requested horizon. The modeler prompt has no explicit period-cap input ([compiler.py:627](../../../../../../backend/app/services/world_simulation/compiler.py#L627)).

Research-dependent evidence, actor roster, numerical provenance, model gaps and exact request size cannot all be checked before research exists. Keep their compiler/preparation failures explicit. In particular, the compiler's 240,000-byte prompt limit and transport input/context bounds must still be checked against the actual generated messages. Admission must not claim a future candidate is executable merely because its transport is configured.

## 4. Proposed minimal fresh-admission contract

### 4.1 Ownership and function boundary

Add one small `backend/app/services/world_simulation/admission.py` module with `resolve_fresh_simulation_request`. It accepts the request's mode, optional engine, raw world spec, world policy, max rounds and optional modeling constraints, together with a captured configuration/safety snapshot. It returns detached normalized pipeline options or a structured, sanitized validation failure.

The function MUST distinguish an omitted engine from explicitly null, empty or unknown values. Omission uses one module-owned `FRESH_SIMULATION_ENGINE_DEFAULT`, initially `oasis-legacy`; explicit invalid values are errors. An explicit engine wins over the fresh default. World-only fields with an effective legacy engine SHOULD be rejected as contradictory rather than silently discarded or used to infer a different engine.

`PipelineOrchestrator.start()` MUST resolve before `ensure_dirs`, task creation, state persistence, event/thread registration or dispatch. Readiness and HTTP handlers MUST use the same rules. The resolver may read the declared non-secret profile and construct/close a local SDK client; it is not a pure function, but MUST NOT issue network requests, create pipeline/modeling artifacts or mutate application configuration. Do not call the general provider connectivity probe.

Keep existing `options.simulation_engine`, `options.world_spec` and `options.world_policy_spec`. Add only `options.world_modeling_constraints` and a small `options.simulation_admission_v1` record containing version, origin (`request_policy`, `operator_profile`, `raw_spec` or `legacy`), configuration status and the normalized profile digest where applicable. Persist detached profile content, not a promise to reload its path at PREPARE. Do not place credentials or raw profile paths in public responses. Later ambient configuration changes may cause a clear identity/readiness failure; they must never replace pinned policy silently.

### 4.2 Profile and precedence

Introduce only `Config.WORLD_POLICY_SPEC_PATH` for this slice, defaulting to unset. It names a local UTF-8 JSON operator profile; no URL fetching, shell expansion or executable configuration. Read a bounded regular file, reject duplicate keys/nonfinite numbers and unexpected fields, and sanitize errors. A proposed 64 KiB bound is sufficient for transport metadata and explicit limits; this is an input-size guard, not a spending allowance. The profile contains only:

- `policy`: the existing strict HTTP policy/pricing fields, including the explicit release review pin;
- `limits`: existing world limit fields, with explicitly supplied positive total token/USD ceilings and output bound;
- `forecastEffect`: one of the two supported safe values;
- `modelingConstraints`: the automatic-modeling period cap and, when explicitly provided, calendar endpoints.

`modelingConstraints` is new admission metadata and MUST be separated from the existing modeler's policy/limits payload. Reuse the existing policy field allowlist; no credentials, arbitrary headers or query defaults are admitted. Do not fill missing rates, capability assertions, budgets or provider identities from guessed model defaults.

For automatic world admission, an explicitly supplied complete request policy wins; otherwise read the configured profile. Do not field-merge two partial policies. An invalid explicit policy must fail, not fall back. If neither exists, return a structured configuration-required error before research starts. For a raw spec, validate its own explicit policy/limits/effect and calendar; reject simultaneous raw spec plus modeling policy as ambiguous. Do not read or inject the operator profile into a supplied raw spec.

### 4.3 Validation order and readiness meaning

For a full world request, perform these checks before pipeline side effects:

1. Validate mode/engine and request shape, including exact positive integer fields rather than coercing booleans/floats.
2. Resolve one policy authority and detach it; reject secret/unknown fields before persistence or SDK construction.
3. Validate every declared limit against the world bounds. Require positive total `maxTokens`, decimal-string `maxCostUsd` and `maxOutputTokens`. Check that an individual declared request envelope is compatible with the context and total allowance. Positive totals alone are not a guarantee of enough budget for a complete trajectory.
4. Validate `forecastEffect` and reconcile it with the captured pipeline safety policy. A mismatch is an error, not a late overwrite. If the request omits the effect, pin the effective safe snapshot explicitly; reject unsafe snapshots for world admission.
5. Require and validate the fresh release review pin using `review_mode` with the actual limits, including `maxAttemptsPerSlot=2`. The constructor alone is insufficient. Preserve existing schema defaults only for nonmonetary limits and record the resolved values.
6. Validate the applicable calendar constraints described below.
7. Construct `StrictHTTPModeler` with the effective policy/limits, then close the successfully constructed instance in `finally`. Never call `decide`, provider tests or research execution. This confirms local supported-provider/endpoint/authentication availability and SDK configuration only, not live credential validity, provider reachability or pricing correctness.

Readiness SHOULD expose engine, ready/blocked/deferred state and sanitized reason codes/remediation, without policy secrets or claiming that research-dependent compilation already passed. Proposed failures include missing/invalid profile, unsupported HTTP configuration, policy identity mismatch, invalid budget/effect/review and calendar conflict. Preserve existing low-level error codes where they already express the reason. HTTP launch can consistently return 400 for invalid request shape and 409 for unavailable/incompatible world configuration, with no state change in either case.

GET preflight must use the selected engine/model and configured profile; arbitrary per-request policies need validation through the same resolver when POSTed. GET readiness cannot claim to validate a request body it has not received. POST must revalidate at admission. The current frontend marks failed preflight fetches ready; the revised UI should show readiness unknown and rely on the authoritative POST check, not display “Configuration ready” for that failure.

### 4.4 Research-only and continuation

A new `research_only` request MUST be able to start without a world profile, supported simulation provider or simulation budget. Resolve and pin its engine selection, validate explicitly supplied data's local shape, and mark missing simulation admission as deferred. Do not open an ambient profile or construct a transport solely to run research. Preserve a detached explicitly supplied policy for later full validation.

`continue_to_full()` MUST validate before changing mode, resetting stages, creating tasks or saving state. Today the first state change is at [pipeline_orchestrator.py:8900](../../../../../../backend/app/services/pipeline_orchestrator.py#L8900). Use the saved engine, with historical absence still meaning legacy. For a saved world selection, use its pinned policy; when simulation policy was explicitly deferred, resolve the configured profile at this first full admission, validate it and pin its origin/content then. An unavailable profile leaves the research-only run unchanged and reports how to configure it. The continuation path must not call the fresh engine-default resolver in a way that reclassifies old runs.

### 4.5 Period cap and horizon guarantee

For a raw spec, `max_rounds` means an upper bound, not an exact required count. Reject a nonpositive/noninteger cap or a spec whose period count exceeds it; accept fewer periods without rewriting them. If separate endpoints are supplied, reject disagreement with the raw calendar. Never truncate, resample or silently rewrite a supplied spec.

For automatic modeling, require a positive declared `modelingConstraints.maxPeriods` bounded by the existing 1000-period contract. When a request also supplies `max_rounds`, a lower value tightens the cap; a value exceeding the operator/request-policy ceiling is a clear conflict, not a silent clamp. Missing both caps is a configuration error, not an invented default. Keep this cap distinct from token/USD budgets: period count alone does not bound actors, responses or request sizes.

Calendar endpoints MUST be fixed independently of the candidate before model dispatch. Accept explicit validated `asOf`/`horizon` constraints, or derive them deterministically from the consumed research cutoff and requested horizon, recording their origin. Existing date parsing and [sim_timeline.extract_horizon](../../../../../../backend/app/utils/sim_timeline.py#L266) are reusable primitives. Do not reuse an ambient-today/default-month/LLM fallback as an undisclosed source of authority. If the cutoff or target horizon cannot be resolved, stop with a specific modeling-readiness error before the model request and require explicit dates; do not fabricate a complete model. This is a PREPARE-time limitation when the missing anchor depends on research, not something admission can promise away.

Pass the resolved endpoints and maxPeriods as explicit bounded data into `build_compiler_messages`; bind them into the durable modeler identity so resume cannot change them or renew requests. A compiler/service check MUST enforce contiguous periods, count at most the cap, first start equal to the pinned cutoff and final end equal to the pinned horizon **before sealing**. Coarser periods are allowed; shortened coverage is not. Recheck after compilation because the current validator derives the endpoint fields from periods. Preserve receipt/charge accounting on invalid candidates; do not add a third request or automatic budget renewal. The resulting guarantee is “an accepted model covers the pinned horizon,” not “every model response succeeds.”

## 5. Historical compatibility and shared callers

Historical missing engine pins remain legacy in [pipeline_orchestrator.py:8408](../../../../../../backend/app/services/pipeline_orchestrator.py#L8408), [simulation_manager.py:808](../../../../../../backend/app/services/simulation_manager.py#L808), [simulation_runner.py:314](../../../../../../backend/app/services/simulation_runner.py#L314) and [worldSimulationView.js:10](../../../../../../frontend/src/utils/worldSimulationView.js#L10). World artifacts without matching pins must continue failing closed. Do not turn these readers into consumers of the fresh default.

Preserve explicit legacy launch behavior. Do not globally change `SimulationManager.create_simulation()`'s legacy default: the legacy pipeline branch calls it without an explicit engine at [pipeline_orchestrator.py:13693](../../../../../../backend/app/services/pipeline_orchestrator.py#L13693). Standalone `/simulation/create` has a separate default at [simulation.py:218](../../../../../../backend/app/api/simulation.py#L218); it is outside the smallest research-launch promotion slice and must not be silently changed.

World scenario forks inherit their parent's sealed world and accept label/seed only ([pipeline_orchestrator.py:8937](../../../../../../backend/app/services/pipeline_orchestrator.py#L8937), [service.py:230](../../../../../../backend/app/services/world_simulation/service.py#L230)). Resume/fork/reuse must not reload the operator profile, add a missing review pin, reset modeling charges or reconstruct damaged world artifacts. Readiness for existing worlds must validate their pins rather than fresh defaults.

The research actor policy is independent: new v3 admissions intentionally do not require a sealed legacy actor plane ([pipeline_orchestrator.py:832](../../../../../../backend/app/services/pipeline_orchestrator.py#L832)). World supports unsealed v3 and sealed legacy evidence, with different provenance checks ([compiler.py:93](../../../../../../backend/app/services/world_simulation/compiler.py#L93)). Do not force sealed legacy actor requirements when promoting the simulation engine.

Before changing the shared `start()` default, account for these callers:

- [sdk.py:127](../../../../../../backend/app/api/sdk.py#L127): currently has no world argument forwarding; give it the same request resolution/override contract.
- [scheduled_rerun.py:693](../../../../../../backend/scripts/scheduled_rerun.py#L693): currently forwards no engine/policy. For the smallest compatibility slice, pass explicit legacy for existing unpinned schedules; new world scheduling requires explicit persisted support and separate acceptance.
- [batch_runs.py:444](../../../../../../backend/scripts/batch_runs.py#L444): anchor uses shared start, but children at [line 300](../../../../../../backend/scripts/batch_runs.py#L300) omit engine/policy pins, and shared children retain the base simulation ID. A world anchor would conflict with an inferred-legacy child. Keep unsupported batch creation explicitly legacy and reject world-parent batch reuse before child side effects until its pins/contracts are implemented. This is an explicit compatibility boundary, not a fallback from a failed world request.

## 6. Small proposed implementation and test scope

No files in this section were changed or tests executed. The scope is proposed for after the diagnostic source freeze is released.

| Slice | Implementation files | Required evidence |
|---|---|---|
| Shared admission/profile | New `backend/app/services/world_simulation/admission.py`; `backend/app/config.py`; `world_simulation/policy.py` / `compiler.py` only as needed to share narrow metadata validation | New `backend/tests/test_world_default_admission.py`: valid profile and explicit request policy; precedence; detached snapshot; malformed/unknown/secret fields; no profile; CLI/unsupported provider; identity mismatch; zero/invalid budgets; unsafe effect; missing/wrong review pin; constructor closed without dispatch. |
| Launch and readiness | `backend/app/services/pipeline_orchestrator.py`, `backend/app/api/research.py`, `backend/scripts/preflight.py` | Actual prompt-only POST and direct start before side effects; initial legacy default and explicit world; release-default seam exercised with a fixture; null/unknown engine; explicit legacy; common readiness outcomes; research-only without profile; failed continuation leaves saved bytes/tasks/stages unchanged; historical continuation stays legacy. |
| Calendar propagation | `world_simulation/modeler.py`, `compiler.py`, `service.py`; `simulation_manager.py` for parameter plumbing if needed | Extend `test_world_modeler.py`, `test_world_compiler.py`, `test_world_lifecycle.py`: raw cap conflict; automatic cap in actual messages; endpoint equality; complete coarse horizon; shorter/shifted/noncontiguous candidate rejection before seal; changed constraints rejected on resume without allowance renewal. |
| Research UI | `frontend/src/views/ResearchView.vue`, `frontend/src/api/research.js` | New `frontend/tests/researchDefaultReadiness.test.mjs` using `sfcHarness.mjs`: selected engine and overrides, configured/unconfigured world readiness, deferred research-only, failed preflight fetch, round-cap semantics and ordinary launch payload. Then actual browser acceptance of the configured prompt-only path. |
| Shared callers/compatibility | `backend/app/api/sdk.py`, `backend/scripts/scheduled_rerun.py`, `backend/scripts/batch_runs.py` | SDK explicit override; existing unpinned schedules stay legacy; batch cannot create an unpinned child referencing a world parent. Extend `test_world_engine_admission.py` and `test_world_lifecycle.py` for historical absent pins, mismatches, immutable forks and zero-write completed reuse. |
| Documentation | `.env.example`, `README.md`, `README.zh-CN.md`, parent-owned release/handoff record | Matching configuration/error/override instructions; no sample guessed paid policy and no secrets. No settings editor or provider-routing redesign is required for this operator-profile slice. |

Existing tests are useful starting points, not proof of the new path: [test_world_lifecycle.py:615](../../../../../../backend/tests/test_world_lifecycle.py#L615) starts directly at `_run_world_stages` with a supplied policy; [test_world_policy.py:349](../../../../../../backend/tests/test_world_policy.py#L349) covers metadata rejection at the transport; [test_world_consistency_v2.py:122](../../../../../../backend/tests/test_world_consistency_v2.py#L122) preserves review-mode compatibility. Add a composed admission-to-modeling-to-compile-to-run scenario with bounded fake boundaries; do not count a manually constructed state as prompt-only launch coverage.

## 7. Acceptance boundaries and remaining decisions

The coordinator must supply the sourced operator policy, budget authority and accepted review-mode identity. This audit does not choose live prices or spend. Positive budgets and a period cap establish explicit bounds; they do not prove that the eventual actor roster and complete reviewed trajectory fit the allowance. Modeling and actual actor-request reservations must continue enforcing the same durable ledger.

The smallest implementation can ship the resolver with legacy still default, explicit-world support and accurate blocked/deferred readiness. Promotion is a later change to the fresh default plus its release receipt after the prescribed full behavior, source, recovery and consumer gates pass. Operator setup must be concrete and usable: no profile or no supported provider means a visible blocked full-world request, not silent fallback or a late surprise after research spending.

No diagnostic outcome, phase13 status, root cause or budget change is inferred here. No live-world or browser success is claimed. This document is the only output of this writing task.

## 8. Narrow implementation checkpoint and coordinator freeze — 2026-10-17

The subsequent implementation authorization supersedes the broader proposal in section 4 for this slice. Only new `backend/app/services/world_simulation/admission.py`, new `backend/tests/test_world_default_admission.py` and this document are owned here. Config, transport, pipeline, UI, scheduling and batch integration remain coordinator-owned. The original audit and proposal above are retained as history, not a statement that those broader changes have been implemented.

The draft exposes the requested keyword-only `resolve_fresh_simulation_request` API with an `UNSET` engine sentinel and an initial `default_engine="oasis-legacy"`. It returns only `simulation_engine`, `world_spec`, `world_policy_spec` and `simulation_admission_v1`. It distinguishes omission from invalid explicit engines, rejects nonnull world inputs under legacy, detaches explicit research-only inputs while deferring profile/auth readiness, and resolves full-world raw/request/operator policy authority without merging profiles. Full-world admission rejects every nonnull `max_rounds` with `world_calendar_override`; no modelingConstraints or new calendar API is implemented in this slice.

The draft checks closed metadata using the compiler helper, explicit positive paid limits, supported nonmonetary bounds, safe forecast-effect equality and the v2 review pin. Its profile reader is bounded to 64 KiB and refuses nonregular files and symlinks in all path components. The transport path constructs and closes `StrictHTTPModeler` without calling `decide`. Admission records contain version/source/status and a normalized policy digest, not a profile path. These are implementation observations from source review, not executed behavior claims.

The test draft contains 28 test functions with parameterized scenarios, including real SDK construction with HTTP replaced by MockTransport, configuration/auth identity checks, missing/invalid policies, malicious profiles, exact file-size bounds, no-symlink reads, detached inputs, legacy/null-engine behavior, deferred research-only requests, review/effect/limit rejection and rejection of every full-world round override. None has been executed by this worker.

The coordinator requested a whole-runtime freeze while running the transport diagnostic. Both Python files were already saved and passed `ast.parse` without importing application code. Source and test editing is paused until an explicit release. No tests, provider requests, runtime imports, commits or delegation were performed.

| Frozen file | SHA-256 | Static checkpoint |
|---|---|---|
| `backend/app/services/world_simulation/admission.py` | `dc3b0eab1e38fd9d71df07b218036c9f852ffdfddc90b326d80b183a12b17eaa` | 10,401 bytes; 217 lines; AST valid |
| `backend/tests/test_world_default_admission.py` | `e5c72f0c23363667f91da910cb915f64df7780f2d5f332c9ba169c9818e2358d` | 19,176 bytes; 418 lines; AST valid; 28 test functions |

Remaining work after release: finish source-level review against the frozen API, address any concrete review findings in owned files, reconcile with the coordinator's transport fixes, and submit the exact files to the coordinator's guarded execution. The new helper is not yet integrated, tests have not passed, no fresh default has been promoted, and this checkpoint is not acceptance. The earlier proposal's continuation/calendar integration remains outside this worker's authorized code ownership.

## 9. Released static completion: v3 policy and single-request budget — 2026-10-17

After the coordinator reported phase14 closed, the coordinator explicitly released this worker for static completion with a revised fresh-admission policy. Only the same three owned files were changed. The earlier v2 checkpoint and broad calendar proposal are historical; neither defines the current fresh-admission contract.

The completed source changes are:

- Import the shared `MODE_V3` from `review.py` and require it for full fresh-world admission. Require an explicit `policy.responseFormat="json_object"`; do not infer it. Reuse the parent-updated compiler metadata allowlist. Existing saved v1/v2 runs must continue bypassing the fresh helper; the saved reader was not modified here.
- Require complete full-world profiles to contain `policy` and `limits`, with `forecastEffect` optional. An omitted effect is filled from the supplied safe snapshot before hashing or transport construction. Explicit null, unsafe effects and snapshot conflicts remain errors. The rule applies to request policies, raw-spec policies and operator files. Input dictionaries and file bytes are not rewritten.
- After constructing `StrictHTTPModeler`, require `max_input + max_output <= limits.maxTokens` and the adapter's conservative `_cost(max_input, max_output) <= limits.maxCostUsd`. The constructed transport is closed in `finally`, including when either budget check rejects. This proves only that one declared envelope fits the supplied ceiling; it does not establish whole-modeling or whole-trajectory funding. No request is dispatched by admission.
- Keep the exact keyword-only API and four return keys. The function default remains `default_engine="oasis-legacy"`; no fresh default promotion, Config change or integration was made by this worker. Research-only requests still defer profile/auth readiness while checking and detaching explicit metadata. Every full-world `max_rounds` override remains rejected; there is no new calendar API.

The authored test file now has 34 test functions with parameterized scenarios. New cases cover missing/invalid JSON-format pins, rejection of fresh v1/v2 review pins, historical review-reader compatibility, omitted effects under both safe snapshots from each policy source, unchanged explicit conflicts, digest binding to the resolved effect, and token/USD envelope failures. The exact-boundary fixture accepts 30,512 tokens and USD0.064608 for its synthetic 30,000-input/512-output envelope; cases one token or USD0.000000000001 below the corresponding bound reject. These numbers are test fixtures, not a live pricing recommendation. Client closure and zero MockTransport dispatch are asserted in both accepted and rejected envelope cases.

Static verification performed on the frozen Python bytes:

1. Both files passed `ast.parse` and compilation of the AST to an in-memory code object. The code objects were not executed, and no application or test module was imported.
2. `ruff check --no-cache --select F,E9` reported all checks passed for exactly these two files.
3. AST inspection confirmed the agreed keyword-only signature and the legacy default, and found no calls to `decide`, `request`, `send` or `reserve_attempt` in the helper. This is source evidence, not a runtime network-isolation proof.
4. Source review checked policy precedence, immutable input copies, full/deferred branches, rejection before transport construction for invalid metadata, cleanup after envelope failures, and sanitized error surfaces.

| Frozen file | SHA-256 | Static checkpoint |
|---|---|---|
| `backend/app/services/world_simulation/admission.py` | `246fc70737d112b6d0da4b80d6559715ab75ac4e39b8b9d448824f8f814f01b0` | 11,544 bytes; 231 lines; AST/compile valid; Ruff F/E9 passed |
| `backend/tests/test_world_default_admission.py` | `a80ef587fc5c899f9927d050df41298527a02125a3861c186673052cb998bce7` | 24,183 bytes; 516 lines; 34 test functions; AST/compile valid; Ruff F/E9 passed |

The helper depends on the parent-owned shared v3 review constant, compiler `responseFormat` allowlist and strict transport implementation. Constructor-only tests do not prove the wire response-format parameter; that belongs to the parent's transport tests. The parent owns the guarded helper run and fresh API/UI integration, including admission-before-side-effects and bypass of historical runs. No pytest collection/execution, runtime invocation, provider work, commit or delegation was performed here. Source/test edits are frozen again at these hashes pending coordinator feedback; this is ready for guarded verification, not admission or promotion acceptance.

## 10. Required fresh candidate-repair pin — 2026-10-17T16:03:37Z

The coordinator approved [candidate-repair-contract.md](check-verdicts/candidate-repair-contract.md) and requested only a narrow helper/test/note delta. Full fresh-world admission now also requires `policy.candidateRepair="known-output-error-v1"`, alongside shared `MODE_V3`, explicit `responseFormat="json_object"` and the existing two-attempt limit. The helper calls the shared `candidate_repair_enabled(profile)` predicate; it does not add the pin, implement repair, change metering or grant another call. The compiler metadata boundary and shared review validator enforce the pin's exact value and v3-only applicability before transport construction.

The existing fresh-admission API, four return keys, legacy default, safe-effect inheritance, request-envelope checks and secure no-symlink profile reader are unchanged. Research-only still permits incomplete explicit metadata while deferring full admission, but a supplied invalid repair pin is rejected. Saved v1/v2 and previously sealed v3 generations without the pin continue bypassing fresh admission; no saved-state reader or runtime repair implementation was edited here.

The profile fixture now uses the shared `CANDIDATE_REPAIR_MODE` constant. Three additional test functions cover missing/invalid repair pins for request/raw/file sources, successful preservation and digest binding of the exact pin with zero dispatch, and rejection of invalid explicitly supplied pins in research-only requests. The historical-reader check now also includes v3 without the repair pin and asserts repair is disabled. The test draft has 37 test functions with parameterized scenarios; none was executed by this worker.

Both owned Python files passed AST parsing, non-executing AST compilation and `ruff check --no-cache --select F,E9`. Static signature inspection confirmed the unchanged API and `default_engine="oasis-legacy"`; no `decide`, `request`, `send` or `reserve_attempt` call sites were found in the helper. These checks establish source/syntax properties, not a guarded runtime pass. No runtime/application imports, pytest collection/execution, provider requests, commits or delegation occurred.

| Frozen file | SHA-256 | Static checkpoint |
|---|---|---|
| `backend/app/services/world_simulation/admission.py` | `290c2d1f3df9215d80ee039bd6554dfcb5d4904e166eeb30dc87c441d6d204c4` | 11,787 bytes; 234 lines; AST/compile valid; Ruff F/E9 passed |
| `backend/tests/test_world_default_admission.py` | `05739086a38d44beb66ad3f09097ef881c278260e3077eb17d36f75bc72c883f` | 27,089 bytes; 571 lines; 37 test functions; AST/compile valid; Ruff F/E9 passed |

The coordinator owns guarded execution, descriptor-traversal guard support, integration and promotion. The earlier reported filesystem guard failures did not authorize weakening the production reader, which remains unchanged. The new repair-pin requirement means other fresh-policy fixtures/operator profiles owned by the parent must include the approved pin; historical saved policies must not be silently upgraded. Source/test edits are frozen at this checkpoint pending coordinator receipt.

## 11. Bounded findings closed against guarded integration receipt — 2026-10-18 Asia/Singapore

The coordinator reported a green combined integration gate and authorized note-only updates. This worker read the existing receipt, JUnit report, console summary and source manifest; no tests or providers were launched and no source/test bytes were edited.

Evidence root: `/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-candidate-repair-integration-first-20261017T160659Z-6nouqkvj/evidence`. Its sibling `verification-summary.json` records exitCode 0, `sourceDrift=[]` and 545 files; sibling `source-manifest.json` contains 545 entries. `console.log` records **668 passed in 8.24s**. `evidence/junit.xml` records 668 cases, zero failures/errors/skips and suite time 8.233 seconds. The console and JUnit elapsed values are preserved as reported rather than treated as distinct runs.

The manifest hashes, copied frozen-source bytes and current worktree bytes all match for the two owned Python files:

- `admission.py`: `290c2d1f3df9215d80ee039bd6554dfcb5d4904e166eeb30dc87c441d6d204c4`.
- `test_world_default_admission.py`: `05739086a38d44beb66ad3f09097ef881c278260e3077eb17d36f75bc72c883f`.

The JUnit breakdown is 189 default-admission cases, 46 fresh-launch cases, 21 candidate-repair controller cases, 68 candidate-repair store cases, 37 v3 policy cases, 25 existing consistency-controller cases, 41 existing consistency-store cases, 216 existing policy cases and 25 v3 consistency cases. These counts sum to the single 668-case run; the helper's 189 parameterized cases come from its 37 test functions and are not additional runs or acceptance counts.

| Bounded finding | Closure evidence in this receipt | Scope of closure |
|---|---|---|
| Missing or unsupported world configuration could fail after pipeline side effects | `test_bad_admission_before_any_pipeline_side_effect` covers direct start and both POST routes for missing/bad profiles, null engines, round overrides and CLI configurations; configured prompt-only and post-readiness revalidation cases pass. | Closed for these guarded fresh-admission scenarios. This does not establish that any live provider is configured or reachable. |
| Fresh policy authority/effect/budget requirements were incomplete | All 189 helper cases pass, including v3/JSON/repair pins, inherited safe effect, explicit conflicts, detached profile/digest, paid limit validation and single-request envelope bounds. Fresh handoff-candidate authority replacement rejection cases also pass. | Closed for the pinned fresh-admission contract. Whole-trajectory funding and model truth are not inferred. |
| Missing historical pins or continuation could acquire current defaults | Historical missing-engine continuation, deferred/saved policy continuation, invalid saved policy versus valid ambient profile, saved schedules and explicit legacy/default cases pass; failed continuation retains saved state/tasks/threads. | Closed for the exercised compatibility boundaries. Saved-run semantics remain separate from fresh admission. |
| World round overrides were silently unsuitable | Full-world round-override rejection passes at helper, direct launch and POST boundaries. Raw-spec detachment/period-preservation cases pass. | Closed by explicit rejection in this slice. No automatic calendar-cap or horizon-modeling API was added. |
| File-profile cases were previously blocked by ancestor traversal in the offline guard | The current run passes all helper file-profile cases with the unchanged production reader, including nonregular/symlink rejection and size/JSON checks. | The helper's blocked test evidence is resolved by this fresh receipt. This note does not substitute for independent review of the parent-owned guard/negative controls. |

The completed guard receipt reports 464 allowed directory-traversal events, three storage/logger redirects and two blocked subprocess events. It records no network event category, preserves identity and reports shutdown complete. These are CPython audit-hook observations, not an OS sandbox guarantee or proof of zero attempted process probes. The earlier failed gate and its blocked file reads remain historical; they are not reclassified as passing.

There are no remaining open findings in this worker's bounded helper/default-admission slice on the verified hashes. The coordinator still owns the broad all-world/affected-legacy gate, frontend/browser acceptance, the fresh full behavioral study and release/promotion decision. No live/full-behavior success, production readiness or default promotion is claimed here. Source and tests remain frozen; this update changes only the audit note.
