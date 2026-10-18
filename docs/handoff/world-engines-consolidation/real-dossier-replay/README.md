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
| `pipe_1c1255cee2e4` | 15 → 15 | `policy_context_limit` before any request | valid (1 req), 231 claims, 181818 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_1ee2fae33f8c` | 18 → 18 | `policy_context_limit` before any request | valid (1 req), 118 claims, 211730 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_22b62e7b8346` | 12 → 12 | `policy_context_limit` before any request | valid (1 req), 201 claims, 173748 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_261de6107490` | 15 → 15 | `policy_context_limit` before any request | valid (1 req), 226 claims, 160697 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_3dcd66754cdc` | 12 → 12 | `policy_context_limit` before any request | valid (1 req), 202 claims, 174898 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_41c155a33733` | 20 → 20 | `policy_context_limit` before any request | valid (1 req), 284 claims, 195718 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_4eb5ce9557ff` | 19 → 19 | `policy_context_limit` before any request | valid (1 req), 320 claims, 217538 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_69a26e4c37df` | 9 → 9 | `policy_context_limit` before any request | valid (1 req), 144 claims, 161272 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_6c4190b31f0b` | 19 → 19 | `policy_context_limit` before any request | valid (1 req), 320 claims, 253440 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_baddcd338811` | 15 → 15 | `policy_context_limit` before any request | valid (1 req), 220 claims, 140241 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_d569f211eb14` | 11 → 11 | `policy_context_limit` before any request | valid (1 req), 200 claims, 174473 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_fd2799f3ad41` | 15 → 15 | `policy_context_limit` before any request | valid (1 req), 235 claims, 183243 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_41522d5d9790` | 18 → 18 | `unsafe_model_text` before any request | valid (1 req), 54 claims, 89043 B | valid (succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_7ef597666938` | 14 → 14 | `unsafe_model_text` before any request | valid (1 req), 390 claims, 149449 B | valid (rejected `unsupported_actor_derivation` → succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_a90b338fdfa0` | 33 → 20 | `unsafe_model_text` before any request | valid (1 req), 99 claims, 139421 B | valid (succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |
| `pipe_e2egold02` | 21 → 20 | `unsafe_model_text` before any request | valid (1 req), 63 claims, 76153 B | valid (succeeded) | `policy_context_limit` | `provider_content_filtered`; resume +0 req | `policy_output_truncated`; resume +0 req | `provider_content_filtered`; resume +0 req |

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

## What this does not show

- The scripted model is not GLM. Whether glm-5.3 follows the new prompt, how often it needs the repair, and
  its real token use and latency on a 140–250 KB request need one paid live modeling run, which needs the
  owner's approval.
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
