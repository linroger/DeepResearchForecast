# Spending boundary implementation contracts

Approved scope is PLANS.md. This API sketch coordinates disjoint owners; owners may propose a small correction before callers are wired. It is not a new spending authorization. All real provider execution remains prohibited during implementation.

## Authority and costs

One stdlib module `deerflow_bridge/run_spending.py` is shared. Backend callers MUST load it through `official_data.bridge_module("run_spending")`, so a process has one stop exception/context identity. Child runtime uses its deployed sibling consistently. Integer micro-USD are the ledger arithmetic; manifest amounts/rates are decimal strings. Every maximum remains retained forever. No telemetry decrement, refund, epoch reset, timeout release or resume renewal.

Routes are closed: one qualified external OpenAI-compatible model route and priced Firecrawl search/scrape. Input quote uses a verified enforceable model input ceiling, not text-length heuristics; output quote uses the final wire maximum including reasoning. Tool quote uses the actual bounded payload units. Unknown billing classes, subscription/CLI routes, hidden retries or unpriced dimensions are unsupported. Rates and bounds carry explicit basis and hashes. Usage observations are not invoices and never reduce balance.

## Required core interface (store owner freezes details first)

- `SpendingStop(code)` is a fixed-code exception with no raw payload/credential text. `is_spending_stop(exc)` supports guarded rethrow where needed.
- `create_authorization(manifest_path, *, registry_dir)` atomically validates an approved private manifest and creates its fixed DB/root binding plus an outside-runtime consumed-authorization record. Only launcher/tests call this; transport adapters never create state.
- `open_existing(binding)` opens only the existing, regular, matching DB and manifest; missing/corrupt/symlinked/moved state denies, never initializes.
- `bind_pipeline(binding, pipeline_id, request)` is a once-only immutable normalized-request binding before any child/thread dispatch; repeat/new mismatches deny. Returns a complete generation-bound descriptor.
- `activate_binding(binding)` and `binding_from_environment()` provide a required process context, with a latch that cannot be disabled by later environment changes. No binding means legacy mode; a present invalid binding never means legacy.
- `operation(stage, logical_key)` is a context manager for out-of-band operation identity. No billing IDs are appended to actor-visible prompts/observations.
- `dispatch(route_id, request, send, *, usage=None)` obtains the current binding and operation, validates actual endpoint/model/wire limits, allocates a fresh physical attempt and commits its retained quote before invoking `send`. It captures allowlisted raw usage before parsing; exceptions/ambiguous outcomes latch a typed halt. A model JSON/empty-response repair with a successful prior response is a distinct attempt; a transport-unknown retry is denied. A local cache hit has no dispatch/debit.
- `halt(binding, reason)`, `check_active(binding=None)`, `close_run(binding)`, `summary(binding)`, `resume_existing(binding, proof)` implement cancellation, terminal guard, conservative recovery and aggregate evidence. Cancellation/exhaustion/unknown/completed states cannot reopen dispatch; clean recoverable resume changes generation only after exclusive ownership/verified participant exit, never cap.
- Child binding/environment export and participant/fence APIs must be explicit and hash-bound; they are not controlled by RESEARCH_BUDGET_ENABLED or telemetry settings.

The store owner must publish exact manifest and request/usage shapes plus public function signatures before adapters finalize. No placeholder implementation or permissive default quote is allowed.

## Ownership

1. Store owner: shared stdlib module, core/fake-process tests and exact API/schema documentation.
2. Parent-transport owner: `backend/app/utils/llm_client.py` and its focused tests; raw completions/SDK retries/route admission/stop propagation.
3. Child/tool owner: `deerflow_bridge/research_gateway.py`, `search_tools.py`, `cached_fetch.py`, `linear_research.py` plus focused tests; final raw invoke/POST attempts, context propagation, retry/fallback/stop paths.
4. Coordinator: pipeline admission/cancel/resume/fork/continue/delete, target estimator/actor operation identities, launcher, setup/bridge synchronization, composed tests and shared handoff.
5. Independent reviewer: read-only actual dispatch/accounting/identity/recovery review, not a substitute for executed producer-consumer tests.

No owner edits another's files. The completed C5/acceptance source, production checkout, saved runs and world-v1 store remain unchanged. Fix duplicate module exception identity through one import path, not fragile exception-name checks. The new overhaul domain store/query contract remains a separate draft.

## Frozen store API (store owner, 2026-10-29)

All carriers below are ordinary JSON dictionaries; functions return detached dictionaries. `hash_payload(value)` is SHA-256 of UTF-8 sorted compact JSON (no NaN). Currency/rates are decimal **strings**; counts are strict nonnegative integers, never bool/float. All hashes are lowercase SHA-256. `source_sha256 = hash_payload(source_files)` and `routes_sha256 = hash_payload(routes)`. No missing/empty source map is admitted; every relative source file is verified below root on opens.

### Manifest (exact keys; synthetic example values, no paid approval)

```
{
 "schema":"target-run-spending/v1", "authorization_id":"synthetic-auth",
 "root":"/absolute/private/runtime", "currency":"USD", "cap_usd":"1.00",
 "request_sha256":"<hash_payload(normalized complete pipeline request)>",
 "source_files":{"app/source.py":"<sha256 of bytes>"},
 "source_sha256":"<hash_payload(source_files)>",
 "routes_sha256":"<hash_payload(routes)>",
 "resume_policy":"explicit_clean_only", "routes":{
   "model-main":{
     "kind":"openai_chat", "endpoint":"https://synthetic.invalid/v1",
     "model":"synthetic-model", "account_sha256":"<SHA-256 of exact UTF-8 credential; private reviewed binding>",
     "billing_class":"external_model", "basis_sha256":"<tariff/bounds evidence hash>",
     "input_bound":"enforced_context_ceiling", "input_ceiling":1000,
     "max_output_tokens":1000, "max_tool_units":0,
     "pricing":{"input_usd_per_million":"1", "output_usd_per_million":"2",
       "tool_usd_per_unit":"0", "fixed_usd":"0", "surcharge_usd":"0"},
     "coverage":"all_billable_dimensions"
   }
 }
}
```

For tool routes `kind` is `firecrawl_search` or `firecrawl_scrape`, `endpoint` is the exact POST URL, `model` is `""`, `billing_class` is `external_tool`, `input_bound` is `not_applicable`, input/output ceilings and token rates are zero, and positive `max_tool_units` bounds the *complete* payload. Tool tariff unit valuation includes prepaid credit usage. At most one `openai_chat`, one search and one scrape route are supported; no subscription/CLI/zero/unverified route. Nonzero USD quote is mandatory. Pinned rates/basis assert a reviewed conservative envelope covering caches, reasoning and surcharges; the store cannot independently verify a real provider tariff. Synthetic tests supply synthetic evidence only.

### Construction and raw dispatch

- `required() -> bool`: process latch OR environment marker. A present invalid/removed binding after latch raises; never silently legacy. `binding_from_environment() -> dict | None` validates `DRF_RUN_SPENDING_REQUIRED="1"`, `DRF_RUN_SPENDING_BINDING=<canonical JSON binding>`, `DRF_RUN_SPENDING_MODULE_SHA256=<sha256 current module bytes>`. `export_environment(binding) -> dict[str,str]` produces those three keys. No credentials are included.
- `activate_binding(binding) -> dict`: **permanent process latch**, installs a detached binding in the caller's ContextVar; not a context manager. Once required, missing context in a new thread is a hard stop. Use `contextvars.copy_context().run(...)` for workers. No API to deactivate. Different authorization cannot replace a latched binding. A newer generation of the same authorization requires valid takeover proof first. Tests may monkeypatch internal latch/context for isolation only.
- `current_binding() -> dict | None`, `check_active(binding=None, *, require_operation=False) -> dict | None`; `check_context() -> dict | None` means `check_active(require_operation=True)`.
- `qualify_route(kind, endpoint, model="", *, account_sha256=None) -> str | None`: require active binding and operation in bound mode, match exact pinned kind/endpoint/model, the account fingerprint is mandatory in bound mode and must match. Return manifest route ID (no invented adapter ID); return None only for legacy. Endpoint normalization allows a single trailing `/` to differ. `get_route(route_id, binding=None) -> dict` returns pinned route. Adapters MUST validate actual client endpoint/model/account config and zero SDK retries/no redirects both before construction and before dispatch; this generic store cannot inspect an opaque client.
- `deny(code)`: persist a terminal halt when possible and raise fixed-code `SpendingStop`. Public codes: `invalid_manifest`, `invalid_binding`, `missing_context`, `invalid_request`, `unsupported_route`, `billing_class_unverified`, `source_drift`, `storage_unavailable`, `authorization_consumed`, `binding_conflict`, `attempt_reused`, `stale_generation`, `participant_unverified`, `lock_unavailable`, `resume_denied`, `budget_exhausted`, `unknown_outcome`, `usage_integrity`, `observation_conflict`, `halted_cancelled`, `halted_error`, `closed`. Unknown exception text is replaced by `invalid_request`; never echoed.
- `operation(stage, logical_key)` is a ContextVar context manager; both arguments are bounded opaque strings. Nested operations are permitted but callers MUST first `check_context()` before deriving a child operation. Ledger stores their hashes; no actor/prompt bodies.
- `dispatch(route_id, request, send, *, usage=None)` and `async dispatch_async(route_id, request, send, *, usage=None)` return the raw result. Sync/async `send` is a zero-argument callable; `usage(raw_result)` is a synchronous pure extractor. They reserve+commit before invoking/awaiting send, then record observation before returning. Exceptions from send or extractor latch unknown, retaining the maximum. No auto retry. Actual HTTP >=400 must be explicitly classified unknown by adapter or raised. A deliberately recognized HTTP 400 reasoning-parameter refusal can return a private sentinel with extractor returning missing usage and `outcome="response_observed"`; it is a fully retained known response and a resend is a fresh physical attempt. RuntimeError lookalikes, ambiguous errors/429/5xx/timeouts remain unknown.

Exact request dictionary (no extra keys):
```
{"endpoint":"https://synthetic.invalid/v1", "model":"synthetic-model",
 "input_tokens":1000, "max_output_tokens":64, "tool_units":0,
 "payload_sha256":"<hash_payload(exact final wire JSON)>"}
```
Model `input_tokens` MUST equal pinned enforceable full `input_ceiling`, not a tokenizer/character heuristic. `max_output_tokens` is the final effective wire limit after all overrides and reasoning headroom. Tool input/output are zero; `tool_units` is positive and bounded. Adapters reject tools/n/stream, limit overrides, redirect/fallback/retry/extra query/header/payload dimensions unless proven part of the closed bound contract. Ledger stores only the hash and aggregate dimensions, never the actual wire body. `quote_request(route_id, request, binding=None) -> dict` returns `reserved_max_microusd` and validated dimensions without admission.

Exact usage extractor output: `None` means missing; otherwise a subset of:
```
{"kind":"provider_reported", "input_tokens":12, "output_tokens":20,
 "tool_units":0, "provider_request_id":"opaque private provider ID",
 "outcome":"response_observed"}
```
`kind` is `provider_reported`, `estimated`, or `missing`; default outcome is `response_observed`, alternatively `unknown`. Counts may be absent, never default absent raw usage to zero; missing kind forbids counts. Tool response may report `tool_units` only. Provider ID is hashed immediately. Unknown fields (including invoice/verified_billed fields) are rejected. Counts beyond the reservation record `usage_integrity` and halt; estimated counts remain explicitly estimates. Missing usage is unknown **usage**, distinct from unknown transport outcome. A returned empty response with missing usage is observed and keeps its full quote.

### Authority, claims and lifecycle

- `validate_manifest(manifest) -> dict`, `create_authorization(manifest_path, *, registry_dir) -> binding`, `open_existing(binding) -> binding`, `bind_pipeline(binding, pipeline_id, request) -> binding`.
- Binding exact fields: `schema="target-run-spending-binding/v1"`, `root`, `manifest_path`, `db_path`, `registry_dir`, `authorization_id`, `manifest_sha256`, `source_sha256`, `routes_sha256`, `pipeline_id` (empty before bind), `generation` (starts 1), `participant_id` (`parent` initially). Manifest must be at `root/spend/authorization.json`, ledger `root/spend/run.sqlite3`; registry must be outside root. Existing-only regular/no-symlink path and source checks apply. Registry consumption precedes DB publication; DB/root inode receipts prevent replacement/move. A partial creation remains consumed and stopped.
- `run_lock(binding)` context manager yields binding and holds exclusive OS flock; required for pipeline binding, participant registration, dispatch and takeover. Parent owns it for the full run. Lock absence denies even with a copied descriptor. `register_participant(binding, participant_id, *, spawn_receipt_sha256) -> binding` occurs before launch. `participant_started(binding) -> binding` claims current PID once; called by child activation. `participant_exited(binding, participant_id, *, exit_receipt_sha256)` is called by coordinator only after its owned process join/exit verification; unproven children deny takeover.
- `reserve_and_claim(binding, route_id, request, *, stage, logical_key, attempt_id=None) -> claim`: fresh attempt ID allocated if absent; an existing attempt ALWAYS refuses, never regrants send permission. Unknown row and retained max commit before return. `claim` contains `binding`, `attempt_id`, `ordinal`, `reserved_max_microusd`. `record_observation(claim, usage=None) -> dict`: immutable/idempotent exact observation; conflicting observation halts. Generation fencing applies, including late responses after takeover. Late same-generation response after halt may add evidence but cannot reopen.
- `halt(binding, reason)` terminal reasons map to durable states; `close_run(binding)` requires no unresolved attempts. `mark_recoverable(binding)` pauses after a non-spending failure, only with no unknown attempts; it does not authorize resume.
- `resume_existing(binding, proof) -> binding`: under `run_lock`, requires state `paused_recoverable`, no unknown attempts, all children exited, and exact proof fields `approval_sha256`, `request_sha256`, `source_sha256`, `routes_sha256`, `participants_sha256` (`hash_payload(summary(binding)["participants"])`). Explicit new approval evidence and verified owned-child exit are coordinator responsibilities. Generation increments; same pipeline/cap/reservations retained. Terminal unknown/cancel/exhaustion/closed cannot resume.
- `summary(binding) -> dict`: sanitized hashes, integer cap/reserved/remaining, attempt counts/states, state/generation/pipeline, route totals, participant receipts, provider usage vs estimates/missing. No raw provider IDs, prompts, paths, exception text or invoice claims.

### One module identity

The core registers both `run_spending` and `deerflow_bridge.run_spending` in `sys.modules` as the SAME module, only after comparing canonical `__file__` if either already exists. A different-source collision fails closed. Backend MUST still use `official_data.bridge_module("run_spending")`; deployed sibling imports may use `import run_spending`. Both spellings share the same exception class, ContextVars and permanent latch. Child environment pins the module bytes before model factory construction.

Frozen clarification: `account_sha256` is the SHA-256 fingerprint of the exact UTF-8 credential used by the adapter; it pins credential selection, not an independent billing-account lookup. Reviewed billing class/tariff still belongs to basis evidence. Child local function tools may use only the pinned AGENT_TOOLS_SCHEMA with the full input ceiling; tools reserve full route max units per POST.

Child operation carrier: `register_participant(..., operation_context=None)` additionally accepts an explicit `{stage,logical_key}` dictionary; otherwise it captures the **existing** current operation (missing denies). Its hash is persisted beside the spawn receipt. `export_environment(binding, *, operation_context=None)` returns a fourth key `DRF_RUN_SPENDING_OPERATION` containing that supplied/current operation, requiring its hash to match the participant receipt. `binding_from_environment` validates this child carrier and installs it; `activate_binding` also validates/installs it when present. It never invents an operation. Parent binding export may omit the fourth key when there is no operation. Child factory therefore runs under the coordinator-supplied, spawn-bound operation, with model/tool suboperations nested only after check_context.

Test isolation only: monkeypatch module `_REQUIRED` to False, `_ACTIVE_AUTH` to None, `_ENV_PIN` to None, `_LOCAL_STOPS` to a new `{}`, `_binding` to `contextvars.ContextVar("test_binding", default=None)`, and `_operation` similarly. These are implementation internals, not a runtime reset API. `run_lock` context exits must still execute for cleanup. All aliases refer to the same module and the same variables.

Post-review tightening (2026-10-29): In bound mode `qualify_route` REQUIRES the `account_sha256` argument even though the signature default permits legacy callers; missing fingerprints deny `billing_class_unverified`. The agreed value is exactly `hashlib.sha256(api_key.encode("utf-8")).hexdigest()`; nonempty organization/project overrides are unsupported. Imported child environment carriers are pinned for the process lifetime and removal/mutation denies even with a retained ContextVar. `operation` now hashes parent ancestry into nested logical keys; `current_operation()` returns a detached current carrier after context validation. A child exit with unresolved attempts immediately latches unknown. Usage beyond admitted bounds is retained as a sanitized `integrity_breach` observation with its original reservation and a terminal stop. The optional SQLite sidecars may disappear during last-connection close, but observed symlinks/nonregular files are refused. Fork-inherited workers are unsupported: an after-fork hook closes inherited parent-lock descriptors without unlocking the parent's copy; child processes must use spawn/exec.

Lifecycle carrier clarification: `bind_pipeline` and `resume_existing` now adopt a committed parent descriptor into `DRF_RUN_SPENDING_BINDING` and the caller's existing binding ContextVar under the module lock. Adoption validates the old pin, same immutable authorization/root/source/route identity and actual DB transition. It is limited to empty→bound pipeline and explicitly approved generation advance. Callers MUST NOT reset environment pins or mutate the descriptor independently. Export remains a detached carrier producer. The coordinator should register a participant inside the same research operation it exports (or explicitly pass the same operation_context to both calls).

Test isolation additionally MUST monkeypatch `_ENV_PIN` to None. Production activation never clears a previously imported environment pin, including the interval between binding_from_environment and first activate_binding. Both implicit and explicit binding admission enforce that pin. Test denied-send spies must assert their markers outside dispatch so its exception normalization cannot hide an invoked transport.

Parent root-operation regression (2026-10-29): The lock-owning parent may enter `operation(stage, logical_key)` while its authorization is still `prepared` and pipeline ID is empty, solely to scope the initial bind. This does not activate dispatch: `check_context`, route qualification, claims and sends still require the committed active pipeline binding. After `bind_pipeline`, the root operation remains in its ContextVar and an initially absent parent `DRF_RUN_SPENDING_OPERATION` remains absent. `export_environment(child, operation_context=registered_root)` produces a detached child carrier; callers apply it only to that child's environment copy. No coordinator export/update back into the parent environment is needed or allowed.

Immutable request validation addition (2026-10-29): `validate_bound_request(binding, request) -> str` validates the current generation, source/manifest/registry/ledger identity, a nonempty matching bound pipeline ID, and `hash_payload(request)` against the immutable manifest `request_sha256`. It returns that approved hash on success and changes no pipeline binding, generation, cap, reservations or state. It works for active and paused authorities; successful validation is not dispatch or resume permission. A different or noncanonical request raises fixed `binding_conflict` and persists the terminal stop through the existing immediate transaction. A stale generation remains `stale_generation` and cannot poison the new generation. Coordinator calls it on the actual normalized state request before provider execution and before resume generation advance; comparison with a mutable saved request copy is insufficient.
