# world-v1 review: Model-facing paths (strict HTTP transport, compiler, modeler, review modes)

- **Reviewed:** `codex/reflexive-world-simulation` at a6fbbc0 (read-only, 2026-10-18 +08), one of four parallel reviews.
- **Line numbers** refer to a6fbbc0 in the Codex worktree unless marked otherwise; the merged tree differs.
- **What was done with each finding** is recorded in [../handoff.md](../handoff.md) §5–§9.

---

## Code review: world-v1 strict transport, compiler and modeler on `codex/reflexive-world-simulation` (a6fbbc0)

Nothing in this part of the code breaks the default oasis-legacy engine. But world-v1 can't currently produce a world from a real research dossier on this deployment, and any one 429 kills a run for good. I only read code and git history, and ran offline, read-only scans of the 36 dossiers under `backend/uploads`. I made no edits, ran no tests or app, and made no network calls.

**Your direct question:** yes, a real dossier will almost certainly fail, and most fail before reaching `modeling_gap`. With the pinned GLM policy, every real dossier stops before any request is sent. If you raise the input limit, the output size or the 120 s timeout stops it. If a candidate does parse, one compile error is permanent, because no attempt is ever used to repair a compile failure.

### 1. Defects

#### Blockers (world-v1 unusable here)

**B1. The modeler and compiler can't turn a real dossier into a world.**
- **The default research engine gives the compiler no evidence to cite.**
  - The v3 engine deletes per-actor `intelligence` and `actor_intelligence_contract` from actors.json (`linear_research.py:7681-7685`). The pipeline then passes that file to the compiler unchanged (`pipeline_orchestrator.py:8576`).
  - None of the 36 on-disk dossiers has `claims` or `actor_id`, so source-claim references can never resolve.
  - Report excerpts need offsets plus a SHA-256 that the model must compute itself (`compiler.py:662-664`). An LLM can't do that.
  - Sourced numbers need the cited quote to parse as JSON (`compiler.py:306-321`), which never happens with prose.
  - That leaves scenario assumptions as the only basis that compiles. The prompt still tells the model to return `gaps` when evidence is missing (`compiler.py:687-688`), and compile rejects any gap outright (`compiler.py:521-523`).
- **Size limits rule out real dossiers.**
  - The input bound counts one token per byte (`policy.py:570-583`). On the 12 newest handoffs the modeler request comes to 124K–231K. The pinned `maxInputTokens` is 60,000, so it fails with `policy_context_limit` before dispatch.
  - The modeler shares the actor output cap (4096/8192; `modeler.py:102-104`, `policy.py:463`) and the ≤120 s non-streaming timeout (`policy.py:452`). My estimate is 8–15K tokens of JSON plus reasoning for a 15-actor spec, so it truncates or times out.
  - `maxActors` defaults to 20 (`contracts.py:25`) and isn't mentioned in the prompt; 8 of the 36 dossiers have more than 20 actors.
- **There is no repair path.**
  - The first parseable candidate is saved (`modeler.py:94-96`) and recompiled on every retry (`service.py:80-89`).
  - Changing any input gives `modeling_binding_mismatch` (`modeler.py:56-57`).
  - Failed attempt rows store no error code (`modeler.py:87-93`), so `modeling_attempts_exhausted` can't be diagnosed.
- **This path has never run on real input.** Compiler tests use a made-up `claims[].report_ref` schema that nothing produces (`test_world_compiler.py:31-41`). Every live study used the hand-built `example_spec` worlds (`evaluation.py:63`).
- **Fix:**
  - Have the compiler turn dossier fields into claims itself, with exact text and spans it computes for verbatim matches. At minimum, tell the prompt "claims=[] → scenario assumptions only, no spans, selectors or gaps".
  - Accept report spans cited by quote and let the compiler compute offsets and hash.
  - Allow one repair with the compile error as feedback, inside the existing two-attempt budget.
  - Give the modeler its own limits (input ≥256K, output ≥32K, timeout ≥600 s or streaming with a byte cap).
  - Store error codes in ledger rows.

**B2. Any 429/1302 ends the world permanently.**
- `_dispatch` maps every SDK exception to `policy_transport_failed` with no usage recorded (`policy.py:647-654`).
- Fresh admission forces review mode v4 plus candidate repair (`admission.py:139-145`). In v4, a candidate failure with unknown usage can't be repaired (`controller.py:71-75`). It raises `required_decision_failed` (87-88), and resume then refuses with `consistency_candidate_unavailable` (94-95).
- Without review mode, the retry fires immediately (126-158). The modeler does two attempts back to back, then is exhausted permanently.
- Each world runs up to 4 concurrent calls (`contracts.py:28`, `controller.py:167`), outside the research `model_call_lease` permits.
- Their own "validated-withheld-review-diagnostics" phase lost all 12 calls exactly this way (`live-budget.json`).
- **Fix:**
  - Classify 429/1302 with `llm_errors.error_status`/`error_code`, which read structured fields, not body text.
  - Don't charge the wait against the slot's or the modeler's allowance.
  - Back off, honouring Retry-After (≤30 s, at most 3 waits).
  - Wrap dispatch in `research_budget.model_call_lease(1)`.
  - If the waits run out, stop in a resumable state instead of burning the slot.

#### Major

- **M1. Mandatory v4 review makes any verdict other than `consistent` terminal.**
  - An `unknown` or `inconsistent` self-verdict ends the run (`controller.py:64-68` → 87-88; resume blocked at 99-100).
  - In the directed phases about 1 in 12 slots came back unresolved, and v3 had 4–7 of 12 structural rejections. V4 only absorbs the "extra member" kind.
  - A real world needs roughly 60–120 revisions, so the chance of completing is near zero.
  - V4 with its planned high-effort/8192 profile has never run live (`lossless-review-fields/profile-proposal.json`).
  - Fix: stop requiring v4 at admission until a full study passes. Make `consistency_unresolved` non-terminal: commit the decision flagged unresolved (or a wait) and keep the withheld receipt.
- **M2. Content filter (1301).**
  - An HTTP 400 is either retried identically or terminal.
  - Output-side `finish_reason:'sensitive'` becomes `policy_invalid_response`, so candidate repair resends the same content.
  - The modeler sends the whole report, so both attempts get filtered.
  - Fix: map `is_content_filter_error` to a `provider_content_filtered` code, never send the identical request twice, and surface the code.
- **M3. Output truncation (`length`).**
  - A truncated response counts as repairable (`policy.py:676-686`). The repair request is about 10 KB longer and must return a decision plus 4 checks under the same cap, so it likely truncates again and ends the run.
  - The transport can't send the app's GLM `thinking:{type:disabled}`: the request options are fixed (`policy.py:642-646`) and the policy whitelist has no such key (`compiler.py:445-446`).
  - Fix: add a `policy_output_truncated` code that is not repair-eligible (or repair with a larger pinned cap). Add an optional closed `thinking:"disabled"` pin sent as `extra_body`. Enforce a minimum `maxOutputTokens` for v4 at admission.
- **M4. Chinese dossiers fail before any call.**
  - `_text` requires the sanitizer to leave text unchanged, including NFKC (`compiler.py:72-78`), and runs on research actor names while messages are built (`compiler.py:123`, `634`).
  - Fullwidth （） in a name gives `unsafe_model_text`. That hits 5 of the 36 dossiers, i.e. every one with CJK names in parentheses. Any model-written Chinese text with "，" also fails compile.
  - English is barely affected: 3 of 3,842 strings (CO₂).
  - Fix: NFKC-normalize first, then check, and compare normalized forms.

#### Minor

- **m1. Prompt versions aren't pinned.** bfbc311 and 7d72c95 rewrote `_REVIEW_SYSTEM_V2` in place after v2 had been used live. No prompt hash is stored in specs or attempts, so a resumed world silently switches prompts. Pin a prompt hash per mode.
- **m2. A model mismatch throws away known usage.** The identity check runs before usage parsing (`policy.py:661-668`), so a mismatch charges the full reservation. Parse usage first, then fail closed.
- **m3. Fragile SDK internals.** `policy.py:510-539` reads private httpx/OpenAI attributes. They work on openai 1.109.1 / httpx 0.28.1 / httpcore 1.0.9, identical in both lockfiles. An upgrade silently disables world-v1 with `invalid_policy_client`; add a guard test.
- **m4. Copied validator messages.** a6fbbc0 copies the v4 validator messages as string literals into `consistency_evaluation.py:34-52`. If review.py changes, diagnostics silently fall back to the generic text.

### 2. Incompatibilities with the provider facts

| Fact | Current behaviour | Minimal change |
|---|---|---|
| Reasoning tokens use up `max_tokens` | No `thinking` control; planned profile is `reasoningEffort: high`, 8192 cap, 120 s timeout | M3 |
| 429/1302 under concurrency | Terminal, with full reservation charged | B2 |
| 1301 content filter | Retried blindly or terminal | M2 |
| Model identity check | Compatible: `glm-5.3` echoed on all 690 live calls | m2 |
| Pinned pricing/endpoint | Compatible with `LLM_PROVIDER=glm` and the coding endpoint. Switching provider in Settings makes saved worlds unresumable (fails closed, acceptable). The USD tariff is a synthetic ceiling; request-count quota isn't modeled | None needed |
| No fallback provider | Consistent with the design, but it also bypasses LLMClient's 429 backoff and circuit breaker | B2 |
| Byte-per-token input bound | Safe, but overestimates 3–4× (worse for CJK); this is why modeler requests reach 124K–231K | Separate modeler limit (B1) |

### 3. Newest 9 commits
- **aab6dd5:** the two-stage revision journal is sound; the semantic gate is the problem (M1).
- **d184eb5:** binding the review scope on the server and dropping model-chosen indices is sound.
- **bfbc311, 7d72c95:** prompt-only, edited v2 in place (m1).
- **e4eacdd:** the per-check server-derived aggregate (v3), lossless v4 member packing and origin-proven candidate repair are all sound. Status-code-only transport diagnostics are sound for privacy, but stop short of classifying 429/1301. Making fresh admission require the unvalidated v4 is M1.
- **1a83008, a6fbbc0:** evaluation-only (m4).
- **d59cb43, 120c44c:** docs only.

`evaluation.py` is a sound harness for preregistration and accounting, but it only covers the synthetic example worlds and says nothing about compiler or modeler behaviour on research input.

### 4. Solid — keep unchanged
- **Strict transport:** one dispatch, no SDK or connection retries, no redirects, auth flows, hooks or environment proxies, and the credential is bound to the exact provider and endpoint (`policy.py:439-559`). Add classified waiting around it, not inside it.
- **Exposure accounting:** integer metering read from the raw response before SDK coercion, inclusive usage checks, no cache discounts, ceiling rounding (`policy.py:585-632`). The reservation is written durably before dispatch, unknown exposure is kept, and the attempt journal can't be renewed.
- **Error hygiene:** closed error vocabulary, `from None`, and log filtering scoped to the calling thread (`policy.py:256-275`, `400-425`).
- **Execution identity and projection:** actor and observation IDs are bound from the serialized request (`policy.py:858-876`), and the exact observation projection is checked (`policy.py:708-751`).
- **Strict JSON** for decisions: no duplicate or NFC-colliding keys, no floats (`policy.py:376-397`).
- **Public-grammar preflight** against the captured observation, with no clamping or guessed IDs; the kernel keeps feasibility (`policy.py:806-849`).
- **Compiler privacy partition** (`compiler.py:146-251`): denied text can't be laundered through assumptions, and report spans never grant actor knowledge. Model output can't set its own policy or budget (`modeler.py:99-106`).
- **Candidate repair** is limited to failures the code itself proved and metered (`policy.py:322-347`).
