# world-v1 on real research dossiers — offline replay (2026-10-18)

This folder is the evidence for the 2026-10-18 follow-up recorded in [../handoff.md](../handoff.md) (§2 R6–R11, §4b, §5, §7–§9):
world-v1's automatic modeling, replayed read-only over the 12 newest completed research dossiers of the
deployment checkout (plus 4 older dossiers whose actor names contain fullwidth parentheses), before and
after the change.

## What ran

- **Inputs.** A read-only copy of each pipeline's `research_report.md`, `actors.json`, `meta.json`,
  `pipeline_state.json` (prompt) and project ontology, taken at 08:21 +08 from
  `/Users/rogerlin/Downloads/DeepResearchForecast/backend/uploads` (deployment checkout; only read).
  Selection and SHA-256 of every copied file: [snapshot_manifest.json](snapshot_manifest.json).
- **Code.** *Before* = a frozen copy of `main` 01b1d78. *After* = a frozen copy of this branch's tree.
- **Path.** The real preparation path, `WorldSimulationService.prepare_model` → `generate_candidate` →
  `build_compiler_messages` → strict modeler transport (`StrictHTTPModeler`, real OpenAI SDK) →
  `compile_world_spec` → input seal. Only the provider is replaced: an `httpx.MockTransport` whose scripted
  model builds a deterministic candidate from the request it receives (its own actors, their exact claims,
  one report excerpt cited by quote, declared assumptions for numbers). No network (an audit hook refuses
  sockets and processes), no reads under the deployment except its interpreter, no writes outside the work
  folders.
- **Policy profiles** ([profiles.json](profiles.json)), derived from Codex's last pinned live GLM policy
  (`behavior-rerun/.../lossless-review-fields/live-policy.json`): *before* = that policy as pinned
  (`maxInputTokens` 60,000, 120 s, 8,192 output, `reasoningEffort: high`); *after* = the same with
  `thinking: "disabled"` instead of `reasoningEffort` and
  `modeler: {maxInputTokens: 400000, maxOutputTokens: 32768, timeoutSeconds: 900}`, total budget
  3,000,000 tokens / USD 25; *after_unpinned* = *after* without `modeler`.
- **Scenarios.** `compliant` (the scripted model follows the prompt), `repair` (its first proposal rewords one
  sourced objective, a typical slip; the second request carries the compiler's feedback), `content_filter`
  (HTTP 400, Zhipu code 1301), `truncate` (`finish_reason: length`) and `sensitive`
  (`finish_reason: sensitive`); the last three also resume once to show nothing is resent.
- **Round smoke (`--round`).** Each world compiled in the `compliant` and `repair` runs also commits round 1
  through the real controller (`run_round`), store and strict actor transport (`StrictHTTPPolicy`, real SDK)
  under the pinned `actor-consistency-v4` review with candidate repair. The scripted actors wait and every
  review returns four consistent checks, so this shows the worlds run and their observations fit the actor
  envelope, not how a real model decides.
- **Tool.** [`backend/scripts/world_dossier_replay.py`](../../../../backend/scripts/world_dossier_replay.py)
  (`snapshot`, `profiles`, `replay`, `compare`). Outputs: [before.json](before.json), [after.json](after.json).

## Result per dossier

The first 12 rows are the 12 newest dossiers; the last 4 are the CJK supplement. "Actors" is research actors
→ compiled actors (the prompt now states `maxActors` = 20). Request bytes are what the strict transport counts
(one token per serialized byte) before its 1,024-token framing overhead.

| Dossier | Actors | Before (pinned policy, main 01b1d78) | After: compliant model | After: one model slip | After: no `policy.modeler` | 1301 (HTTP 400) | `length` | `sensitive` |
|---|---|---|---|---|---|---|---|---|
| `pipe_1c1255cee2e4` | 15 → 15 | `policy_context_limit` before any request | valid (1 req), 231 claims, 183888 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_1ee2fae33f8c` | 18 → 18 | `policy_context_limit` before any request | valid (1 req), 118 claims, 213800 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_22b62e7b8346` | 12 → 12 | `policy_context_limit` before any request | valid (1 req), 201 claims, 175818 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_261de6107490` | 15 → 15 | `policy_context_limit` before any request | valid (1 req), 226 claims, 162767 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_3dcd66754cdc` | 12 → 12 | `policy_context_limit` before any request | valid (1 req), 202 claims, 176968 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_41c155a33733` | 20 → 20 | `policy_context_limit` before any request | valid (1 req), 284 claims, 197788 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_4eb5ce9557ff` | 19 → 19 | `policy_context_limit` before any request | valid (1 req), 320 claims, 219608 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_69a26e4c37df` | 9 → 9 | `policy_context_limit` before any request | valid (1 req), 144 claims, 163342 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_6c4190b31f0b` | 19 → 19 | `policy_context_limit` before any request | valid (1 req), 320 claims, 255510 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_baddcd338811` | 15 → 15 | `policy_context_limit` before any request | valid (1 req), 220 claims, 142311 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_d569f211eb14` | 11 → 11 | `policy_context_limit` before any request | valid (1 req), 200 claims, 176543 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_fd2799f3ad41` | 15 → 15 | `policy_context_limit` before any request | valid (1 req), 235 claims, 185313 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_41522d5d9790` | 18 → 18 | `unsafe_model_text` before any request | valid (1 req), 54 claims, 91113 B | valid (succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_7ef597666938` | 14 → 14 | `unsafe_model_text` before any request | valid (1 req), 390 claims, 151519 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_a90b338fdfa0` | 33 → 20 | `unsafe_model_text` before any request | valid (1 req), 99 claims, 141491 B | valid (succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_e2egold02` | 21 → 20 | `unsafe_model_text` before any request | valid (1 req), 63 claims, 78223 B | valid (succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |

Denied (analyst-only) dossier text found in any actor observation of the 16 compiled worlds: 0. Every modeler request carried thinking={"type": "disabled"} and max_tokens=[32768].

Reading the table:

- **Before**, every dossier stops before any request is sent: the 12 newest at `policy_context_limit`
  (requests of 123,229–229,526 bytes against the pinned 60,000; the review measured 124K–231K) and the 4 CJK
  dossiers already while building the request, at `unsafe_model_text` (fullwidth （） in actor names). The
  request carried no citable claims (`claims: []`), so even with a larger bound only scenario assumptions
  could have compiled, and a compile error would have been permanent.
- **After**, all 16 compile to a valid, sealed world in one request: 54–390 derived claims per dossier, actor
  profiles filled from each actor's own claims, a report excerpt resolved from its quote, 0 analyst-only
  texts in any actor observation. With one model slip the second request repairs it (13 of 16; the other 3 have
  no objective claims to reword, so the first proposal is already valid). Without `policy.modeler` the typed
  stop is still `policy_context_limit`. A content filter (input or output side) or a truncated reply stops at
  its typed code after one request, and a resume sends nothing.
- **Round 1** commits in all 32 compiled worlds (16 `compliant`, 16 `repair`): 18–40 actor requests per world,
  exactly one candidate and one v4 review per actor; the largest actor request is 17,029 bytes against the
  pinned 60,000-token actor bound; every actor request carried `thinking: {"type": "disabled"}`.

## Live run 1 (2026-10-18 20:15 +08, owner-approved, modeling only)

One paid modeling run on `pipe_fd2799f3ad41` (OPEC+) with the *after* profile and the branch head a99c20b
(script: [live-2026-10-18/live_modeling.py](live-2026-10-18/live_modeling.py); DNS only to the pinned provider
host, deployment reads limited to its interpreter and `.env`, nothing printed from it). No-dispatch preflight
first: configured provider `glm`, endpoint equal to the pinned coding endpoint, admission `ready`; no other
pipeline was running.

- **Outcome:** typed `modeling_attempts_exhausted` after 197 s, `attemptCodes`
  [`unresolved_source`, `actor_basis_mismatch`]; no crash. Reserved 217,035 then 257,904 tokens (byte
  ceilings); metered 61,126 + 70,122 tokens, USD 0.180520 + 0.189184 at the pinned ceiling tariff.
  Ledger and both proposals: [live-2026-10-18/live-run-1-receipts.json](live-2026-10-18/live-run-1-receipts.json).
- **Attempt 1:** every actor's identity basis was a report quote of the research actor's own name; the 8
  names with a parenthetical qualifier (`Saudi Arabia (energy ministry)`, …) never occur verbatim in the
  report. **Attempt 2 (repair):** all 12 quotes were real report sentences, but to make each span contain the
  name it shortened 8 names (`Saudi Arabia`), which the identity check refuses. The prompt had pushed the model
  into that corner ("identity basis … the excerpt must contain the exact actor name").
- **Offline, free:** with the names and a `role` claim basis restored, GLM's proposal fails next at
  `invalid_state` — its `initialState` sections, template `inputs`, scheduled events (`date`, `recurrence`)
  and flows do not follow the spec's shapes, which the prompt named but never stated. Its substance was
  sound: 20 declared assumptions, decimal-string numbers, every profile item citing an allowed claim.
- **Change made:** the prompt now states the exact shape of every section (keyed objects, `inputs` object,
  one occurrence per scheduled event, contiguous per-round periods), tells the model to copy each research
  actor's id and name and to use one of its own claims (its `role`) as identity basis, and to quote report
  sentences, never names. Whether glm-5.3 then compiles needs a second paid run.

## Live run 2 (2026-10-18 20:37 +08, owner-approved, modeling only)

Same dossier, profile and script, on 4326304 (the revised prompt). Preflight passed and no other process
was using the key. **Outcome:** typed `modeling_attempts_exhausted` after 1.6 s with two
`policy_transport_failed` rows (`status: unknown`, no usage): GLM answered both requests with an HTTP error
before generating anything (the host was reachable; an unauthenticated call returns 401), so the revised
prompt was not exercised. The ledger kept only the code, not the HTTP status, so 429 (quota or rate limit)
cannot be told from another refusal after the fact; attempt rows now also keep the transport's closed
status message (`errorMessage`, e.g. "…failed with status 429…"). Files:
[live-2026-10-18/live-run-2-receipts.json](live-2026-10-18/live-run-2-receipts.json).

## Live run 3 and the refusal's cause (2026-10-18 20:45–20:47 +08)

Run 3 (owner: "Try again"; e7eff90, rows now keep the status): both requests refused in 1.3 s with
**HTTP 400** ([live-run-3-receipts.json](live-2026-10-18/live-run-3-receipts.json)). The exact request,
resent once with the plain SDK to read GLM's error body ([diagnose_400.py](live-2026-10-18/diagnose_400.py),
[diagnose-400.json](live-2026-10-18/diagnose-400.json)), answered **code 1210**, "该模型始终思考，不支持关闭思考；
请使用 low、high 或 max" (the model always thinks; disabling thinking is not supported; use low, high or max).
Run 1 sent the same `thinking: {"type": "disabled"}` at 20:15 and was accepted, so glm-5.3 changed between
20:15 and 20:37. Changes: the modeler stops after one deterministic 4xx refusal (`provider_request_rejected`)
instead of resending it, and `profiles` adds `after_effort_low` (the *after* profile with
`reasoningEffort: "low"` instead of `thinking`), which passes admission without a request. Neither run 2 nor
run 3 reached the model, so the revised prompt is still untested live.

## What this does not show

- The scripted model is not GLM. Live run 1 showed glm-5.3 did not follow the earlier prompt's implicit
  shapes; runs 2 and 3 were refused before generation (GLM 1210, see above), so whether glm-5.3 compiles
  under the revised prompt is still open.
- Actor decisions ran only with scripted waiting actors for one round. Real decision quality, multi-round
  behaviour and the engine's known limits (429/1302, unresolved v4 verdicts, reboot liveness; ../handoff.md
  §9) are outside this replay.

## Regeneration (19:56 +08)

The session scratchpad was cleared after the first run. The snapshot was retaken by pipeline id with
`snapshot --ids …` and matched every SHA-256 in [snapshot_manifest.json](snapshot_manifest.json); the *before*
tree was recreated with `git archive 01b1d78`; the profiles regenerated byte-identical. The *before* outcomes
and every *after* outcome (status, code, claims, request bytes) matched the first run exactly; the outputs here
are the regenerated ones, from the tree that includes the review fixes (handoff §6) and with `--round`.

## Reproduce

```bash
PY=/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python
DEPLOY=/Users/rogerlin/Downloads/DeepResearchForecast
TOOL=backend/scripts/world_dossier_replay.py
$PY -I -B $TOOL snapshot --pipelines $DEPLOY/backend/uploads/pipelines --projects $DEPLOY/backend/uploads/projects --newest 12 --to SNAP
$PY -I -B $TOOL profiles --live-policy docs/handoff/reflexive-world-simulation/behavior-rerun/semantic-consistency/release-readiness/check-verdicts/lossless-review-fields/live-policy.json --out profiles.json
$PY -I -B $TOOL replay --src FROZEN_TREE --dossiers SNAP --work NEW_WORK_DIR --out after.json --profiles profiles.json --runs after:compliant,after:repair --deny $DEPLOY --allow-read $DEPLOY/backend/.venv --round
$PY -I -B $TOOL compare --before before.json --after after.json
```

`FROZEN_TREE` is an rsync copy of a tree (`--exclude .git --exclude node_modules --exclude backend/uploads
--exclude .venv`); a snapshot taken later selects whichever 12 pipelines are newest then.
