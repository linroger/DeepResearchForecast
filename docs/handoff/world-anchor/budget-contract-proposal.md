# World Anchor budget v2 — implementation contract

**Status:** Owned core implementation complete; APIs below are frozen for coordinator integration. Final owned verification and independent review passed. No live provider, deployment or scheduler authorization.
**Worktree:** `/Users/rogerlin/.codex/worktrees/world-anchor/DeepResearchForecast`, branch `codex/world-anchor`, based on spending delivery9916b3be/c2736d36.
**Owner files:** `deerflow_bridge/run_spending.py`, `backend/tests/test_world_anchor_spending.py`, `backend/tests/fixtures/world_anchor_spending_child.py`, and this document. Existing v1 tests, callers, gateway, launcher and other owners' files are not edited.

The original documentation-only proposal was accepted with one refinement: retain eight catalog attempts and add a separate maximum of **12 registered search/scrape attempts**, including retries, under the same one follow-up identity. This current contract supersedes the draft's blanket Firecrawl denial. The old worktree/core remains untouched. Frozen v1 baseline was `b54cac7c001c5f46106e3593e7a5ad4f66a6711488bd5679fee0f35ec889f9d5`.

## 1. Invariants and compatibility

One existing SQLite ledger atomically retains every attempt's whole-run integer microUSD maximum and, when scoped, its stage dimensions. Stage membership is explicit and durable; it is never inferred from `stage_hash`, nested stage names, PID, epoch text, task IDs or research-generation labels.

For the sole authorization-lifetime anchor scope:

- Model physical attempts <=20.
- Retained enforceable input-plus-inclusive-output token envelopes <=150000.
- Catalog physical attempts <=8.
- Registered search/scrape physical attempts <=12, combined across both routes.
- One admitted follow-up identity/set across catalog and research collection; at most one logical catalog query per stable admitted gap.
- Every attempt also satisfies the immutable whole-run USD cap. All dimensions commit together before raw send, or none does. Usage, errors, cancelled/killed workers, late receipts and new research revisions never refund capacity.

Lower immutable limits are supported, never higher than these hard maxima. All count fields are strict integers, not bool/float. Existing v1 decimal rates and integer microUSD arithmetic remain unchanged. Captured local data, local cache hits and complete pack replay create no physical attempt/debit. Future model-based embeddings would consume model attempts/tokens but are unsupported in this initial route set.

v1 opens/writes keep the existing manifest, request, binding, SQLite schema, summaries and observed-missing-usage behavior. No v1 DB migration, retrofit of anchor mode, stage reconstruction, cap renewal or approval upgrade occurs. v2 is created only for a new manifest/authorization. Old code refuses its schema/version. Off/unpinned requests retain their existing seven fields and behavior; enablement cannot fall back to unbound provider dispatch if v2 authority is absent.

## 2. Exact v2 authority shapes

A v2 manifest has all existing v1 fields, changes `schema` to `target-run-spending/v2`, and adds exactly `anchor_budget`:

```json
{
  "schema": "anchor-budget/v1",
  "scope_id": "anchor-opaque-id",
  "policy_version": "world-anchor-budget/v1",
  "source_policy_sha256": "<64 lowercase hex>",
  "model_attempt_limit": 20,
  "token_envelope_limit": 150000,
  "catalog_attempt_limit": 8,
  "followup_attempt_limit": 12,
  "catalog_lookups_per_gap": 1,
  "followup_round_limit": 1,
  "model_profile": {"route_id": "model-main", "max_output_tokens": 2000},
  "catalog_route_ids": [],
  "followup_route_ids": [],
  "usage_policy": "provider_reported_required"
}
```

Each route list is an exact immutable allowlist, initially empty when only captured data is admitted. Adding a ceiling does not authorize a route. The model attempt/token limits are positive; tool limits may be zero. `model_profile.max_output_tokens` is a positive inclusive wire ceiling <=2000 and <=the pinned route ceiling. No silent reasoning-headroom/widening exemption.

The normalized private request retains the existing seven fields and adds exactly:

```json
{
  "world_anchor": {
    "mode": "v1",
    "anchor_budget_scope_id": "anchor-opaque-id",
    "policy_version": "world-anchor-budget/v1",
    "source_policy_sha256": "<64 lowercase hex>",
    "model_attempt_limit": 20,
    "token_envelope_limit": 150000,
    "catalog_attempt_limit": 8,
    "followup_attempt_limit": 12,
    "catalog_lookups_per_gap": 1,
    "followup_round_limit": 1
  }
}
```

Coordinator normalization injects those reviewed private fields; a public caller may select only `world_anchor={"mode":"v1"}`, not supply budget IDs/limits. The entire expanded request is hashed. `bind_pipeline` and `validate_bound_request` require exact agreement between the object and manifest. Existing top-level request normalization remains coordinator ownership.

A v2 binding retains the exact v1 fields, changes `schema` to `target-run-spending-binding/v2`, and adds `admission_epoch: int` and `active_scope_id: str|null`. Initial values are0/null. `generation` fences process-tree ownership; `admission_epoch` fences phase handoffs. Neither is an allowance. No scope selector is added to prompts or mutable environment flags.

The model/Firecrawl route shapes are unchanged. A v2-only `kind="catalog_lookup"` route uses the existing external-tool fields plus exact `catalog_contract` keys: `provider_id`, `operation_id`, `catalog_sha256`, `request_schema_sha256`, `response_bound_sha256`, `retry_policy_sha256`. Endpoint, credential fingerprint, every charge dimension and bounded units must be qualified. No zero-priced, unknown-billing or subscription route is inferred. The current implementation supports synthetic catalog HTTP controls; a real catalog adapter/qualification is separate owner work.

## 3. Phase/participant lifecycle

The first profile allows one provider-producing phase at a time. Concurrent batches/descendants within anchor share its scope; unrelated unscoped sends are fenced during that phase. Scope entry/exit increments the run-wide admission epoch. A pre-entry or post-exit late worker cannot be silently reclassified as unscoped.

The parent may enter the stage. A registered research root may enter only after the parent explicitly grants `scope_entry_ids=[scope_id]` in its registration. Stage-entry authority is not automatically delegated. All descendants inherit the scope and epoch from their registrar; they cannot clear or replace them. Copied ContextVars carry the full binding into threads/async work. Missing context denies.

The existing lock, source, manifest, registry, immutable request and generation checks still apply. Entry and budget sealing require no unresolved attempts, all non-ancestor registered workers exited, and explicit owned-worker join evidence. An idle coordinating ancestor is permitted. A PID timeout/lease expiry is not an exit receipt. v2 registrars may record an actual joined direct child's exit in the same generation; they cannot attest siblings. Unresolved child attempts still halt unknown.

Only trusted committed transitions adopt the new descriptor into the current context/environment under the existing RLock. Parent `DRF_RUN_SPENDING_OPERATION` absence stays absent. A child receives its registered operation only in its environment copy. Old admission descriptors are never auto-refreshed during dispatch.

## 4. Available stage APIs and closed carriers

All carriers are detached JSON dictionaries; hashes are lowercase SHA256 and IDs are bounded opaque strings. The following functions are implemented, not placeholders:

| Function | Exact arguments/result |
|---|---|
| `preflight_anchor_profile(binding)` | Returns `{schema:"anchor-profile/v1", scope_id, policy_sha256, route_id, routes_sha256, input_upper_bound, max_output_tokens, token_envelope_units}`. Success changes no reservation. Oversized qualification persists `stage_profile_oversize`; no client/send follows. |
| `begin_anchor_scope(binding, *, session)` | Session keys: `session_id`, `research_generation_id`, `input_manifest_sha256`, `requirement_registry_sha256`, `workers_quiesced_sha256`, `restart_of_session_id` (nullable). Returns `{binding, transition_receipt}`; the returned v2 binding is already adopted in the calling process. The exact current open session is idempotent; a different session cannot overlap. |
| `seal_anchor_budget(binding, *, seal)` | Seal keys: `session_id`, `participants_exited_sha256`, `workers_joined_sha256`. Freezes scoped admission in state `sealing`; returns the immutable budget receipt below. It requires an active, quiescent scope and a completed registered follow-up, if one exists. |
| `finish_anchor_scope(binding, *, completion)` | Completion keys: `session_id`, `artifact_manifest_sha256`, `budget_receipt_sha256`, `result` (`sealed` or `non_ready`). Requires the sealed budget receipt, then returns `{binding, transition_receipt}` with a new unscoped epoch. Never use as an unconditional finally/reset. |
| `adopt_scope_handoff(binding, receipts)` | Parent-controller-only, under its held run lock. `receipts` is one/two contiguous stored transition receipts from its old epoch through the current epoch. Returns/adopts its updated binding. It cannot manufacture a transition or refresh an ordinary worker. |
| `scope_summary(binding)` | Read-only inspection, including historical binding generations. Its exact public fields are listed below. It grants no dispatch permission. |

Transition receipt fields are exactly `schema="scope-transition/v1"`, `authorization_id`, `pipeline_id`, `generation`, `session_id`, `owner_participant_id`, `kind=enter|exit`, `from_epoch`, `to_epoch`, `from_scope_id`, `to_scope_id`, `proof_sha256`. They are stored append-only in the same DB. Do not authenticate a caller-generated receipt without checking it against the stored transition.

`scope_summary` returns `schema="anchor-budget-summary/v1"`, `scope_id`, `policy_sha256`, `generation`, `admission_epoch`, `active_scope_id`, `active_session_id`, `active_session_state`, `pending_restart_session_id`, run `state`, `stop_code`, `limits`, `retained`, `remaining`, `sessions`, and `followup`.

- `limits` has the four `*_limit` fields: model attempts, token envelope, catalog attempts, follow-up attempts.
- `retained` has `model_attempts`, `token_envelope_units`, `catalog_attempts`, `followup_attempts`, `reserved_max_microusd`.
- `remaining` has the four count/token fields, excluding USD; whole-run USD remains in the existing run summary.
- Each session view has `session_id`, `owner_generation`, `owner_participant_id`, `enter_epoch`, `exit_epoch`, `state`.
- `followup` is null or `{followup_id, gap_manifest_sha256, state, result_sha256}`.

**Binder entry check:** `check_context()` → `preflight_anchor_profile(binding)` → require matching `binding.active_scope_id == profile.scope_id`, non-null `scope_summary.active_session_id`, `active_session_state == "open"`, run `state == "active"`. Use the existing gateway with an inclusive final output cap <=profile cap. Do not make a second reservation or infer scope from the gateway's changing stage label.

The sealed budget receipt has `schema="anchor-budget-receipt/v1"`, `authorization_sha256`, `pipeline_id`, `scope_id`, `session_id`, `generation`, `policy_sha256`, `source_sha256`, `routes_sha256`, `retained`, `limits`, `barrier_sha256`. Hash this receipt canonically before putting its hash in completion. It contains no future pack hash, so publication can seal the pack using this receipt without a circular hash. A terminal spending failure cannot use the active sealing/finish APIs to reopen; its diagnostic gap/error can include a read-only scope summary and must propagate the stop.

## 5. Restart without renewal

For v2 only, `resume_existing` keeps all exact v1 proof fields and additionally requires:

- `scope_state_sha256 = hash_payload(scope_summary(binding))`.
- `anchor_recovery = null` when no stage session is open, otherwise exactly `{kind:"restart_from_inputs", previous_session_id, research_generation_id, input_manifest_sha256, requirement_registry_sha256}`.

A clean resume retains the same DB/authorization/scope and all rows, increments writer generation and admission epoch, and requires the existing exclusive-lock/owned-exit proof. Unknown/cancel/exhausted/closed states cannot resume.

For unfinished anchor work, the explicit recovery marks the previous session `interrupted` and leaves a pending restart marker. No raw send is allowed until a new authorized root calls `begin_anchor_scope` with a new session ID, `restart_of_session_id` naming the interrupted one, and the same research/input/requirement identities. The new session gets a generation-qualified owner; prior model/token/tool debits and follow-up identity remain. This is bounded restart from frozen inputs, not target-v3 checkpoint continuation. A later changed-input research revision enters a new normal session only after the prior one closed, against the same lifetime limits. Completed pack replay makes zero calls.

## 6. Registered W4 operations

`register_anchor_gaps(binding, *, gap_manifest_sha256, gaps)` registers the **one** admitted follow-up set and returns `{scope_id, followup_id, gap_manifest_sha256, state}`. Each gap has exactly `gap_key`, `requirement_id`, `constraint_identity_sha256`; sort by gap_key before hashing the list. `gap_manifest_sha256` must equal that canonical list hash.

The deterministic producer derives a stable semantic constraint identity from its authenticated kind/identity/actor/consumer references. Generation-sensitive anchor contract/requirement/gap IDs are trace references, not budget keys. Core checks:

`gap_key = hash_payload({"schema":"anchor-gap-budget-key/v1", "request_sha256": immutable_manifest_request_sha256, "constraint_identity_sha256": ...})`.

Source policy must supply that stable semantic identity; uncertainty denies external lookup rather than inventing a key. No changed research generation creates another follow-up set. Same set registration is idempotent and may return its already-completed state.

| Function | Exact use |
|---|---|
| `open_catalog_lookup(binding, *, followup_id, gap_key, catalog_route_id, query_sha256)` | One immutable catalog query per stable gap. Different query/route conflicts. |
| `open_followup_operation(binding, *, followup_id, gap_key, route_id, query_sha256)` | Registered allowed Firecrawl search/scrape query for that same gap/follow-up. Each distinct wire operation is registered; all physical attempts share the12 ceiling. |
| `complete_tool_operation(binding, operation_id, *, result_sha256, outcome="complete")` | Stage owner seals a known returned result; `outcome="abandoned"` explicitly closes an unsent/known retry-ready/known returned operation without refunds. Never abandons an unknown/in-flight call. |
| `complete_catalog_lookup(binding, lookup_id, *, result_sha256)` | Convenience delegation to complete_tool_operation; existing proposed caller spelling remains available. |
| `complete_anchor_followup(binding, followup_id, *, result_sha256)` | Stage owner seals the round once every registered operation is complete/failed. It cannot be reopened in a later research session. Required before budget sealing if a round was registered. |

Both open methods return exactly `{scope_id, followup_id, gap_key, operation_id, route_id, query_sha256, state}`. Registration creates no physical debit. Only the current stage owner registers/seals operations; descendants execute the registered IDs.

The catalog adapter freezes a canonical `{method, endpoint, query, body}` request, with secret credentials checked separately through the pinned credential fingerprint. `query_sha256` must equal the physical envelope's `payload_sha256`. Search/scrape use the existing final validated JSON body hash. A registered query A cannot authorize a query B send. Actual endpoint/method/payload/credential validation remains the transport owner's responsibility; no arbitrary URL/method or fallback is admitted.

Use additive `catalog_lookup_id=operation_id` OR `followup_operation_id=operation_id` on `dispatch`, `dispatch_async`, or `reserve_and_claim`. Both absent for model/unscoped routes; exactly the applicable one for scoped tools. Route kind and allowlist determine which counter increments, never the caller's diagnostic label.

Operations transition `ready|retry_ready` → `in_flight` atomically with the attempt insertion. A competing claim cannot reuse that lookup. Scoped tool observations may add `tool_result=complete|retryable_known|terminal_known` (default complete); this must come from the pinned transport response classification, never model prose. After verifiable observed usage these map to `awaiting_admission`, `retry_ready`, or `failed`. The stage owner then seals deterministic results as `complete`. Unknown outcomes halt; missing usage never makes an ambiguous429/5xx retryable. The catalog retry-policy hash and existing route basis bind the actual adapter's classification. No hidden library retry is admitted.

## 7. Atomic debit and usage semantics

The existing BEGIN IMMEDIATE transaction validates source/manifest/registry, generation, lock, participant, admission epoch and current scope, then computes the final conservative quote. It checks remaining run USD and stage counters, validates the registered operation's scope/route/hash/state, inserts one immutable unknown attempt with **all** applicable debit fields, marks its tool operation in-flight if any, and commits before send. No transaction spans HTTP. On any failed predicate there is no attempt/partial counter increment and no send; a fixed denial/halt is persisted when storage permits.

v2 attempt additions are `scope_id`, `scope_session_id`, `admission_epoch`, `model_attempt_units`, `token_envelope_units`, `catalog_attempt_units`, `followup_attempt_units`, `tool_operation_id`. They are immutable alongside USD. Totals derive from attempt rows across every session/generation; there is no separate mutable quota cache or TTL refund.

v2 tables extend the same DB: `budget_scopes` (immutable policy), `scope_sessions`, append-only `scope_transitions`, immutable-identity `anchor_followups`, and `scope_tool_operations`. Participants gain parent/scope/epoch/entry-capability fields. No existing DB is migrated. v1 physical rows/receipt schema remain unchanged.

The approved plan's scoped usage rule is stricter than v1. Anchor models require provider-reported input AND output counts; scoped tools require provider-reported units. Missing/estimated-only/unverifiable usage persists `stage_usage_unverifiable`, retaining all maxima and halting unknown. Over-bound usage preserves its breach observation and halts integrity. v1 and unscoped v2 missing-usage responses retain existing semantics. In particular, the v1 reasoning-refusal sentinel with missing usage cannot silently authorize an anchor resend.

Input uses the qualified enforceable full route ceiling, covering actual serialized framing/schema/tool inputs. Inclusive output includes reasoning. A200000-input/2000-output profile is rejected against150000; never use min(context,cap), optimistic text heuristics or returned usage. A qualified128000+2000 profile can fund at most one call;8000+2000 at most15;1000+2000 hits the20-attempt ceiling first. This promises no minimum call count. Batches must shrink to fit both actual serialized input and complete structured output; no reply truncation becomes a valid binding.

New fixed codes: `budget_scope_missing`, `budget_scope_conflict`, `stale_admission_epoch`, `stage_model_attempts_exhausted`, `stage_tokens_exhausted`, `stage_tool_attempts_exhausted`, `stage_followup_attempts_exhausted`, `catalog_lookup_conflict`, `tool_operation_conflict`, `stage_profile_oversize`, `stage_usage_unverifiable`, `transport_receipt_missing`. Exhaustions map to terminal exhausted; unverifiable usage to terminal unknown; integrity/qualification failures to terminal error. Stale epochs reject the old worker without poisoning the current owner. No provider text or raw private paths are in these codes.

## 8. Confirmed producer provenance seam

The budget store does not invent provider response evidence. New optional `response_fingerprint` on `dispatch`/`dispatch_async` is a **transport-owned callable**, evaluated on the raw send result before returning to parsing/admission. It returns exactly `{basis,sha256}` where basis is `provider_json/v1` (canonical provider JSON) or `http_bytes/v1` (exact response bytes). The fingerprint becomes part of the immutable usage observation/hash on the actual claimed attempt. It is accepted only for active v2-scoped attempts; pass None for v1/unscoped calls.

```python
with spending.capture_dispatch_receipts() as capture:
    result = gateway.invoke(...)
opaque = capture.receipt()             # after leaving capture and joining work
facts = spending.inspect_dispatch_receipt(opaque)
```

`capture_dispatch_receipts(binding=None)` captures actual committed IDs across copied thread/async contexts. Nested captures may observe the same physical attempt; they do not double debit. `capture.receipt()` issues an opaque `DispatchReceipt`, not a caller-constructible JSON credential. `inspect_dispatch_receipt` accepts that issuer-bound object only, rechecks exact ledger facts and returns a detached manifest. Missing response fingerprints or unobserved attempts refuse authentication. An empty capture proves zero physical calls only; it cannot authenticate a newly generated proposal. A cache reuse needs its earlier authenticated receipt/artifact.

Manifest fields: `schema="anchor-dispatch-receipt/v1"`, `authorization_sha256`, `manifest_sha256`, `source_sha256`, `routes_sha256`, `pipeline_id`, `scope_id`, `generation`, `admission_epoch`, `attempts`. Each attempt contains `attempt_id`, `logical_hash`, `ordinal`, `participant_id`, `route_id`, `scope_session_id`, `request_sha256`, `response_fingerprint`, `observation_sha256`, `reserved_max_microusd`, and the four stage debit-unit fields. It contains no raw prompt/provider body/credential.

**Required gateway-owner edit, outside this owner's files:** `_BoundRawCompletion.create` already obtains `raw.http_response.json()` before LangChain choice parsing. Capture immutable canonical UTF-8 bytes for both `_model_wire_body(kwargs)` and that provider JSON at this seam. Verify the request hash against the existing admitted envelope; persist the provider bytes through the assigned producer callback; compute the fingerprint from those bytes, not from normalized AIMessage/text. Store it in the call-local `observed` carrier and pass `response_fingerprint=lambda _: observed["response_fingerprint"]` from `_provider_call` only when the binding is v2 with non-null scope. v1 observation bytes remain unchanged. Callback/storage failure stops rather than inventing evidence.

The producer joins captured request/provider bytes to the inspected attempt facts by their hashes, verifies that parsed `response_artifact` (`references/rows` or `decisions`) was decoded from that actual provider JSON, and only then issues the separate authenticated producer manifest. Core receipts alone do not prove source entailment or approve arbitrary self-stamped response artifacts. The pure contract owner/coordinator must also include `physical_followup_attempts` in shared Metering so the separate12 allowance remains visible; this owner does not edit that shared contract.

## 9. Coordinator/caller integration boundaries

- Launcher/normalizer: issue the sole scope ID and complete v2 request/policy, validate exact route/source/import hashes, and reject unqualified profiles before provider construction. No migration of existing authorizations.
- Research-root lifecycle: begin scope before binder construction; register/join descendants with inherited context; explicitly close the one follow-up; seal budget receipt before pack emission; finish only after the artifact manifest is durable. Complete reuse is zero-call.
- Binder: use existing ModelGateway and final wire caps; consume the opaque capture and trusted raw-body callback, not normalized output hashes. The existing dispatch owns every reservation.
- Catalog/search/scrape: register source-policy-approved operations under the admitted gap set, pass the applicable operation ID at each actual raw send, capture raw usage before parsing and preserve typed stops. No unregistered fallback.
- Resume: validate immutable actual request before generation advance, verify owned process exits, preserve the scope/round/counts, and use only the explicit same-input restart proof.
- Parent/child namespace: continue one canonical `run_spending` module identity and source-bound deployed copy. Stage IDs/provenance stay out of actor/model-visible metadata except the actual requested source content.

## 10. Verification ledger and remaining work

The initial new tests failed because frozen v1 correctly rejected the v2 manifest; `/private/tmp/world-anchor-budget-red-20261029-01` records that feature-absence red. The first implementation passed96cases (3new+93unchanged v1). Expanded source proof passed114cases, then `/private/tmp/world-anchor-budget-process-20261029-04` passed122cases (29new+93v1) in27.85s, including independent-process final model/token/catalog/follow-up slot races, three crash windows and a fresh-PID retained-scope restart. These are intermediate receipts; subsequent follow-up sealing/provenance/edge additions require the final gate below before any completion claim.

Current owned tests also cover fake HTTP search/scrape against the same ledger, exact wire operation matching, no partial stage debit on run-USD denial, scope/carrier tamper rejection, parent/child epoch adoption, one follow-up across revisions, strict missing/estimated usage, async cancellation, immutable captures and v1 compatibility. Actual gateway/raw-response sink integration is a separate owner assignment; this core gate is not that producer-to-publication proof.

Pending: finish the expanded guarded gate, close bounded independent review findings, reconcile final hashes and this owner record, then hand exact stable bytes/API to coordinator. No broad app tests, provider calls, package installation, production writes, commit or push are performed by this owner.

## Updates

- 2026-10-29: Drafted stage scope/epoch/same-ledger proposal; static review identified and resolved explicit owner transfer, descendant exit, wire-hash matching, serialized lookup retry and profile-failure semantics.
- 2026-10-29: Spending delivered; moved the owned proposal to codex/world-anchor. User released core/new-test implementation, adding the separate12-attempt registered research-follow-up requirement.
- 2026-10-29: Implemented v2 opt-in storage, atomic counters, phase fencing/restart, complete registered W4 tool lifecycle and opaque dispatch receipt capture; retained all existing v1 test sources unchanged. Current API text replaces the obsolete proposal-only table.


## Final owned acceptance and handoff

2026-10-29: `/private/tmp/world-anchor-budget-final-20261029-13` passed **147 tests in35.23s**, with zero failures/errors/skips and completed shutdown. This is54 new/extended checks plus all93 unchanged v1 store tests. Existing v1 test and child-fixture source files have no diff. Ruff and scoped whitespace checks passed. Independent reviewer Beauvoir inspected the exact final core and receipts and reported no outstanding findings in the reviewed core/phase/restart/provenance repairs.

| Final file | SHA-256 |
|---|---|
| `deerflow_bridge/run_spending.py` | `d7691253c4f842b0355113f39930ec0ace4671ae35ed608b533daddbcd6322df` |
| `backend/tests/test_world_anchor_spending.py` | `d946f828c34de26398b91982f270b1532d463a2ed67236332b5b20d1f9574d53` |
| `backend/tests/fixtures/world_anchor_spending_child.py` | `b5589e20dbc4b973c654b7154214390d6cd3860d80027368512b0fd3be91da39` |

Preserved failures: review-red06 reproduced pending-restart recovery, stale exited-worker phase poisoning, and mutable issued-receipt truncation; all are fixed. Context-red08 proved that a parent-local missing-context stop did not reach an alive scoped child; v2 now persists denial using a last-validated control descriptor that can never grant admission. Sidecar-red11 reproduced optional zero-link metadata during unlink; one bounded restat accepts confirmed absence while still checking any replacement. Capture-red12 proved pre-issuance capture-list truncation; capture claims and issued receipts now retain immutable canonical snapshots.

The intermediate reviewed07 gate recorded139passes/one failure in the unchanged v1 concurrency case (`invalid_binding` from both children). Its original cause remains unproven; do not retrospectively attribute it to a specific line. The unchanged focused v1 rerun passed, the controlled sidecar defect was separately repaired, and final13 includes all original v1 tests plus four extra independent-root executions of that unchanged race. The failed receipt is preserved rather than relabeled green.

Remaining work is owned by coordinator/callers: wire v2 request/launcher/source copying, producer stage hooks, registered W4 operation IDs, and the gateway's real provider-JSON capture callback; re-run their actual composed raw-transport/publication checks on frozen new bytes. The pure Metering contract needs its separate physical follow-up count. This core receipt does not claim those integrations, live provider qualification, invoice correctness or a completed World Anchor feature. No other owners' source was edited; no provider/network connection, install, production mutation, commit or push was performed by this owner. The old spending worktree remains untouched.

Final next-step prompt: integrate the exact APIs in sections4/6/8 on codex/world-anchor; preserve the final core hash unless a concrete defect is reproduced; keep v1/off behavior and strict source/runtime pinning; use the current guard with exact child registrations and fresh evidence roots. Do not derive response fingerprints from normalized model text or use an unregistered W4 fallback.

### Interface distribution
2026-10-29: Reverified core hash `d7691253c4f842b0355113f39930ec0ace4671ae35ed608b533daddbcd6322df` and sent Carver the exact v2 manifest/request/binding/profile fields and limits for his separately owned launcher adapter. Sent a concrete relay packet for Poincare covering the actual scope-entry worker barrier, entry/seal/finish carriers, adopted descriptors, and opaque capture/fingerprint/parsed-response verification seam. No broad-gate wait or source edit was needed. The shared APIs remain stable; gateway raw-body capture remains an explicit separate owner assignment.

### Urgent coordinator → pure/publication owner interface
2026-10-29: Binder's zero-model/catalog-only and bound zero-call cases require a pure receipt attachment edge. Route to Maxwell and the publication owner (coordination remains through the coordinator as recorded in binder-owner.md):

`attach_producer_receipts(index, *, receipts: Sequence[ProducerReceipts]) -> EvidenceIndex` should accept only already authenticated externally pinned handles, validate each handle's scope and policy against the immutable index, deduplicate by manifest hash with collision checks, and return a new opaque index retaining the same observations/files/reviews. It must not fabricate a semantic review or edit `_review_pins` to obtain a receipt handle. All attached producer hashes must be included in the publication inventory. `load_completion` must reconstruct/authenticate and attach every bundle before pack validation, even when there are no reviews.

Metered scope and exact retained counters may come from the authenticated sealed `anchor-budget-receipt/v1`, including zero model attempts with positive catalog/follow-up attempts, retained earlier scope usage, or a bound zero-call stage. A normalized metering summary must be hash-linked to that selected sealed budget artifact and match its scope/counters; arbitrary counter JSON is not authority. Model transport rows, when present, must agree with scope and provide a retained floor, not be the sole source of scope identity. Preserve `physical_followup_attempts` and its12 ceiling. The source-support/observation gate remains independent.

One additional ordering constraint is visible in current pure source: `_evidence_digest` includes `producer_manifest_hashes`. An accounting-only attachment after model decisions must not silently invalidate their already authenticated semantic input/candidate hashes. Separate auxiliary receipt inventory from the semantic evidence digest (or freeze an equivalent explicit lineage rule). Do not rerun paid work after budget sealing merely to refresh a hash, and do not rewrite model-authenticated hash fields. Publication still seals the complete producer inventory.

The current core already supports zero-model enter/seal/finish and returns scope plus exact retained counters in its sealed budget receipt. No core API/source change is requested for this pure-module edge. Core remains frozen at `d7691253c4f842b0355113f39930ec0ace4671ae35ed608b533daddbcd6322df`.

### Coordinator → pure inventory owner: target KIQ provenance join
2026-10-29: Read-only source inspection confirms the binder-reported edge in `world_anchor.index_snapshot`'s local `inventory` function: every row under a target-case/v1 track takes the target_source_id crosswalk branch, including origin=kiq_fact. Actual raw KIQ `sids` are positive ledger integers such as1, whereas target external IDs such asS1 are a different namespace.

Maxwell should dispatch by row origin: target-track kiq_fact joins its validated integer ledger SID within the same track/snapshot; case_claim/case_node continue to require the explicit authenticated target-source crosswalk and whole-row pointer. Preserve original KIQ bytes and hashes; do not prefix/rewrite SIDs in the binder or use a blanket string-coercion join. Regression: one target track containing both facts.sids=[1] and case sourceIds=["S1"] joins each through its correct path; identical SID1 in another track cannot cross-bind; missing/invalid crosswalk still denies case claims; malformed/nonpositive/bool KIQ SIDs cannot acquire provenance. A source-key join does not waive page/hash/semantic admission.

This is outside spending ownership and changes no core API. Core remains frozen d7691253c4f842b0355113f39930ec0ace4671ae35ed608b533daddbcd6322df.

### Coordinator → Maxwell: bounded qualitative collection proposal
2026-10-29: The native producer requires nonempty, source-supported actor/time/indicator/reference-class research output without inventing executable authority or a target contract. This belongs to the pure contract owner, not the spending core.

Recommended minimum: preserve `requirements_from_contract` and add an explicitly tagged `authority_kind="research_inventory"` contract alternative with `settlement=null`. Admit only text requirements whose consumers all use `role="research_note"`; no numeric target/baseline/mechanism/identity fields or executable specs can be supplied through this alternative. It must always emit a blocking `missing_contract` gap for all simulation engines, even though qualitative requirements may bind. A non-null hash of a research inventory is not a settlement contract. Existing `requirements_from_contract(None)` behavior remains unchanged; the native adapter explicitly supplies the inventory alternative from authenticated retained artifacts.

Allow optional `collection=true` only for these text/non-executable research-note requirements. Absence preserves existing scalar admission. Each selected observation still requires independent supported provenance and existing cutoff/known_by checks. Collect independent supported statements/events by observation identity; differing independent text is not automatically a scalar conflict. Contradictory statements stay explicitly attributed/contested. Numeric conflict detection, conversions, identity constraints and executable authority gates remain unchanged. Never enable collection for a numeric or executable consumer.

Derive `research_items` from admitted collection bindings, not model notes or unverified candidate rows. Proposed minimum fields are `research_item_id`, `requirement_id`, `observation_id`, `kind`, nullable `actor_ref`, exact supported `quote`, `value_kind`, `producer_class`, `audience`, `known_by`, `effective_at`, `visible_at`, `ref_ids`, and fixed `executable=false`. Reuse existing Time/Audience types and unknown semantics; no inferred schedule/cadence or fabricated date. Preserve raw quote bytes/spans. These items render meaningful private sheet/dossier/timeline sections; they are excluded from engine execution projections. Human research output is not an actor visibility grant: actual actor payloads retain the existing actor-known/owner/audience/time/privacy gates and must not inherit analyst inference merely because an item is non-executable.

Required controls: multiple valid actor statements and announced events survive; reference-class/indicator notes reach rendered output; an unrelated or wrong-actor source is denied; numeric collection is rejected and existing numeric conflicts still fail; research_inventory yields nonempty qualitative items while missing_contract blocks every engine; no collection text becomes a scheduled effect, lever, target or first-party probability. Avoid hard-coded empty sections and fake target identities.

The independent budget-only ProducerReceipts attachment remains necessary: attach authenticated handles without invented model reviews, support metered zero-model/catalog-only/retained-usage scopes, and attach every bundle on publication reload. Qualitative collection does not justify dummy calls or self-authenticated counters. These are proposed pure-module interface changes awaiting coordinator/Maxwell freeze; no pure source or spending source was edited by this owner.
