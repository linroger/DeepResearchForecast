# Fresh actor HTTP public-input grammar

**Status:** Complete — guarded runtime acceptance and independent source review closed; phase-seven behavior remains unassessed here. **Base:** `37b4316`. **Date:** 2026-10-17 Asia/Singapore.

## Request, authority and ownership

The user released the completed V2 source freeze and approved [PLANS.md](PLANS.md) and [the prior proposal](../followup-proposal.md). This worker owns only `backend/app/services/world_simulation/policy.py`, `backend/tests/test_world_policy.py` and this note. The coordinator owns the shared kernel helper, runtime gates and live work; the replay worker owns captured old-trace compatibility fixtures. No provider calls, application/test execution, commits or extra agents are authorized for this worker.

The coordinator reports conservative cumulative exposure US$13.714174955664 and US$11.285825044336 remaining under the original authorization. This task creates no budget and does not reset exhausted allowances. Original study sources, failed contrasts and qualitative reviews remain preserved. World-v1 stays opt-in.

## Implementation boundary

Check only fresh actor HTTP replies after the existing dispatch has returned trustworthy usage, using the detached observation parsed from the exact serialized RPC before dispatch. Reuse parent-owned `kernel._input_values(option, detached_intent, None, max_chars)`; its None mode skips only private actor-roster membership, while ordinary dictionary callers retain all previous checks and errors. Validate the captured visible menu, declared inputs, and exact inbox/ownOffers references. Never inspect hidden mechanisms, balances, global actor membership or economic feasibility; never clamp, fabricate IDs, drop an invalid intent or partially accept a response.

On any public-grammar failure, raise `PolicyFailure` retaining the known usage so the existing controller can charge the failed dispatch and use only its already allowed second attempt with safe feedback. An unexpected validation failure must likewise retain known usage behind a fixed generic message. No new retry or SDK call exists inside the adapter.

Keep `validate_decision`, store admission/replay, cached decisions and modeler behavior untouched. Previously committed rejected intents must remain valid historical records. Keep the request-bound outer identity, prices, metering and attempt ceilings unchanged.

The prompt additionally defines the half-open current period `[simulatedAt, periodEnd)`, distinguishes historical records and future plans from current completion, distinguishes choosing to wait from a genuinely unavailable action, and asks for claims consistent with supplied facts and submitted intents. Prose arithmetic and economic correctness are not mechanically verified by this grammar gate.

## Acceptance plan

- Real SDK/mock HTTP scalar grammar cases cover all declared types, required/unknown fields, bounds, enum, global text safety and actor inputs without hidden roster lookup.
- Reference cases cover exact consent/counter/withdraw, empty consent parameters, wrong/missing/mixed IDs and versions, visible delivery/expiry/recipient checks, and pending undelivered own-offer withdrawal.
- Real controller/store scenarios cover known-usage invalid→valid repair, invalid twice and exhausted reopen, unchanged observations and quote growth, and preservation of all attempted charges.
- Mutation/concurrency cases prove the grammar reads the immutable dispatched observation rather than caller changes or another actor's data.
- Modeler and kernel feasibility controls demonstrate the boundary does not become a hidden economic check. Replay fixtures remain separately owned.

Only static source inspection is performed here. The coordinator owns runtime acceptance and source review; no behavioral improvement or current runtime pass is claimed before those receipts exist.

## Progress

- 2026-10-17: Read the approved plans and confirmed the coordinator's explicit `actors: dict | None` helper is already present. The public-grammar directory is nested under `behavior-rerun`; no alternate directory was created. Started the bounded policy/test implementation.
- 2026-10-17: Implemented the actor-only visible grammar check after known dispatch usage. Shared `_input_values` validates parameters with None roster mode; exact references are checked only in the captured public inbox/own offers, including the existing allowance for undelivered pending own-offer withdrawal. Known failures and unexpected local validation failures retain usage; a valid subset is never returned for a response containing an invalid intent. Public Response IDs remain bound to the captured RPC. Added only the approved general period/choice/claim prompt wording.
- Updated the affected fresh-HTTP negative expectations to the new earlier metered failure while retaining direct validator/kernel rejection controls. Added 55 focused cases for declared types/required/unknown/min/max/enum, empty consent and references, unexpected-error sanitization, actual controller/store repair and exhausted reopen, caller mutation, concurrent actors, modeler preservation, unaffordable-but-valid grammar, and no partial drops. The static expected policy collection is 216 cases; the coordinator's runner is authoritative for the actual count.
- Static syntax and whitespace checks passed. AST comparison against `37b4316` confirms `_StrictHTTPTransport` and `StrictHTTPModeler` are unchanged. No application imports or runtime tests were run by this worker. The existing shared validator/store/cached paths were not edited; old-trace replay fixtures remain owned by the separate replay worker.
- Frozen policy SHA-256: `d408d53ae56700976aa101dfde38817699b839c5056b7dcd515a2d732f782e68`.
- Frozen test SHA-256: `b20f285710701fd096ba2f517db70b94c08dcb735d47f3e533a5ee7887267046`.
- Next: coordinator runs the focused guarded policy/controller/store/replay controls and source review. Preserve originals and current budget accounting; this implementation has no live acceptance claim and starts no provider work.

## Final runtime and source closure

The coordinator's full public-grammar gate passed **537 tests in 58.84 seconds**, including **216 policy tests**, with zero failures, errors or skips. The run summary records exit 0 and no drift across **523 frozen files**. This worker independently inspected the summary, JUnit, completion receipt and current owned source hashes; they exactly match the first frozen implementation:

| Owned source | Accepted SHA-256 |
|---|---|
| `backend/app/services/world_simulation/policy.py` | `d408d53ae56700976aa101dfde38817699b839c5056b7dcd515a2d732f782e68` |
| `backend/tests/test_world_policy.py` | `b20f285710701fd096ba2f517db70b94c08dcb735d47f3e533a5ee7887267046` |

Evidence: [frozen-run summary](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-public-grammar-first-20261016T193911Z-6at6fp8z/verification-summary.json), [JUnit results](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-public-grammar-first-20261016T193911Z-6at6fp8z/evidence/junit.xml), [guard completion](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-public-grammar-first-20261016T193911Z-6at6fp8z/evidence/completed.json), and [console output](/private/var/folders/sh/z3hsvy7526b8xcjjphdq8hs00000gn/T/drf-public-grammar-first-20261016T193911Z-6at6fp8z/console.log). The guard records three storage redirects and two blocked subprocess attempts, no recorded network attempts, completed shutdown and preserved identity. These counters do not mean zero attempted operations or an OS sandbox.

The coordinator confirmed Epicurus's independent source closure with no findings. JUnit confirms passing replay cases for the three captured historical rejection traces (`v2-quantity`, `original-wrong-id`, `original-altered-accept-terms`) and the cached rejected-decision recovery case. Shared-helper controls also pass for normal, empty and None actor maps; None skips only membership while preserving all declared grammar and consent checks. No policy-owned finding remains open.

## Accounting and interpretation boundary

| Outcome | Accounting and record meaning |
|---|---|
| Fresh HTTP response fails public grammar after known metering | A **failed generation attempt** retains its known usage and consumed attempt allowance. It does not become a persisted successful decision or a committed kernel-rejection resolution. Only the existing remaining second attempt may repair it. |
| A grammar-valid admitted decision is later rejected by the kernel | A **committed intent rejection** remains an explicit world-resolution outcome, including hidden economic or institutional infeasibility. The new public check does not replace these checks, force a wait or erase their history. |
| A second attempt repairs the first | The repaired decision may proceed, but the first failed generation and its charge remain recorded. Improved committed feasibility must not be reported as first-attempt model perfection. |

Unknown provider exposure retains its prior conservative reservation handling. Two failed attempts still exhaust the durable slot, and cached/replayed historical decisions receive no fresh HTTP preflight. Future reports must keep generation failures, repair attempts and committed rejections distinguishable rather than silently changing denominators or regrading earlier studies.

## Handoff and live freeze

The coordinator reports a separately launched phase seven, identified here only by the reported manifest prefix `6c5be0e1`, with cap **US$11.285825044336** allocated from the reconciled remainder of the original authorization. This is not a new budget or a statement of the still-unspent balance after launch. Current runtime source is frozen. Phase-seven calls, traces, qualitative review and any behavioral-gate decision are coordinator-owned; no live-behavior improvement is claimed in this closure. World-v1 remains opt-in, and prior studies remain preserved.

Only this note was updated for closure. No code/test changes, new test execution, providers, commits or agents were used. Stop this worker's scope; reopen only for an explicitly authorized change or concrete regression after respecting the live-source freeze.

- 2026-10-17: Verified the 537-pass receipt and exact owned source bindings, recorded coordinator-confirmed Epicurus approval and historical replay/cache success, and closed the slice. Preserved the failed-generation versus committed-rejection distinction and the phase-seven source freeze.
