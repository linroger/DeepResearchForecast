# world-v1 review: Core engine (kernel, contracts, observations, controller)

- **Reviewed:** `codex/reflexive-world-simulation` at a6fbbc0 (read-only, 2026-10-18 +08), one of four parallel reviews.
- **Line numbers** refer to a6fbbc0 in the Codex worktree unless marked otherwise; the merged tree differs.
- **What was done with each finding** is recorded in [../handoff.md](../handoff.md) §5–§9.

---

I found two blockers, five majors and seven minors. Every blocker and major was reproduced with a probe script. The two blockers are the main thing: each can stop a run permanently, and resuming does not help because the same failure replays from saved decisions.

**How I checked.** I read the four core files, `examples.py`, the four test modules and the design docs at tip a6fbbc0; the tip did not move while I worked. I ran small stdlib-only probe scripts against the kernel without importing the app and without writing anything to the worktree. Two caveats: a probe ran a real round through `WorldStore` once, and other code it touches (`policy.py`, `compiler.py`, `service.py`) was only spot-read. To rerun: `python3 -I run.py pN_*.py` in `/private/tmp/claude-501/-Users-rogerlin-Downloads-DeepResearchForecast/8488656d-00c7-4477-b942-5011cbd7a86c/scratchpad/probes/`.

All file references below are in `/Users/rogerlin/.codex/worktrees/reflexive-world-simulation/DeepResearchForecast/backend/app/services/world_simulation/` unless shown with a fuller path.

## 1. Defects

### Blockers

**B1. One badly formed `bundleId` from an actor stops the run for good.**
- **Where:** `validate_decision` allows the field but never checks its format (`contracts.py:326-339`). The HTTP policy's input check doesn't either (`policy.py:806-849`). `_decisions` then checks it with `identifier()` outside the per-group rollback (`kernel.py:777-778`), so both `stage_interactions` and `resolve_round` raise `invalid_identity`.
- **Failure:** the bad decision is already saved, and resume reuses it.
- **Probe p1b:** a policy that emits `"bundleId": "buy and expand"` makes `run_round` fail. Reopening the store with a clean policy fails the same way, and the head stays at round 0. The value `7`, an empty string, and anything over 128 characters all do the same.
- **Fix:** check the format in `validate_decision`. It then becomes an ordinary `invalid_intent` that the actor can repair (that code is already in `CANDIDATE_OUTPUT_ERRORS`). Ideally `_decisions` would also reject only that group instead of the whole round.

**B2. Any effect that fails at a time boundary kills the round.**
- **Where:** `_advance` (`kernel.py:701-712`) applies scheduled events and settlements with no rollback. `_effect` can raise `insufficient_resources` (via `_transfer`, lines 357-359) or `negative_quantity` (line 414). `validate_mechanisms` (lines 80-95 and 149) accepts scheduled transfers out of actor-owned accounts and deltas of either sign.
- **Probe p2, three cases:**
  - A scheduled tax of 5 is drawn from `a_cash` at day 1.5. Actor `a` legally transfers 8 in round 1, so round 2 fails.
  - An investment with delta −3 on capacity 4 is executed twice in round 1, and both are accepted. Settlement in round 2 fails.
  - A scheduled −10 shock on capacity 4 passes validation, and round 2 fails with no actor involved.
- **Why it matters:** all three are deterministic, so resume can't get past them. They also break the kernel's own stated rule that actor failures roll back their own intent. Nothing in the modeler prompt (`compiler.py:650-690`) steers the model away from writing these specs.
- **Fix:** record boundary failures instead of raising (a `*_failed` event, the commitment marked failed, holds released). At minimum, only allow scheduled transfers from external accounts and reject stock or rate deltas whose worst case goes negative.

### Major

**M1. Derived records take the template's audience, not the parties' or the affected records'.** This is both a privacy leak and a functional gap. Probe p3:
- **Commitments:** `_commitment` (`kernel.py:429`) uses the template's visibility, while `_offer` (lines 476-478) narrows offers to the participants.
  - With an order template visible only to `c`, the b→a deal's transfers (7 and 5) show up in `c`'s view of commitments.
  - Neither `a` nor `b` sees the commitment or its settlement event.
  - The recipient never learns the commitment id it would need to breach.
  - With the default analyst-only visibility, parties never see their own obligations.
- **Hidden metrics:** a public investment that targets an analyst-only metric exposes that metric's id and delta through the commitment record (projected at `observations.py:66-68`). The compiler's `_effect_visibility` only checks rule and relation writes.
- **Messages:** a message template visible only to `a` and `b` but with no `recipientIds` is sent to every actor (`kernel.py:599-600`). In the probe, `c` received "private to b".
- **Fix:**
  - Agreement commitments and their events should inherit the offer's audience.
  - Effects should only be shown to actors who can see the records they change.
  - Message recipients should default to the template's audience.

**M2. Actor observations grow without limit and eventually hit a hard context limit.**
- **What grows:**
  - `ownOffers` holds every interaction the actor ever proposed, in every status, including all its sent messages (`observations.py:69-70`).
  - Every commitment stays in the world view forever.
  - `priorityChanges` is appended with no de-duplication (`kernel.py:853-854`).
- **Probes:**
  - With short messages (p5b), one actor's observation grows from 25 KB in round 1 to 84 KB in round 30, linearly.
  - With maximum-length messages plus a repeated priority change (p4), it reaches 163 KB by round 10 and 399 KB by round 30.
- **Why it matters:** the HTTP policy reserves one token per byte and raises `policy_context_limit` before sending (`policy.py:570-583`). Once an observation crosses the limit, the world can never advance, and cost climbs steadily before that.
- **Fix:**
  - Show only pending or recent own offers, with a cap.
  - Drop messages that already appear under `messages`.
  - Prune closed commitments from the view.
  - De-duplicate priority changes by rule id.

**M3. The order of simultaneous events depends on the random generation id.**
- **Where:** effects that land at the same instant are sorted by `stable_id(generationId, …)`, mixed with raw scheduled event ids (`kernel.py:703`). Intents with equal priority are ordered by intent-id hash (lines 789 and 796).
- **Probe p6:** two one-day-lead policies, one closing a permit and one reopening it, are issued in the same round. With identical decisions, the final permit is `False` under 6 of 8 generation ids and `True` under 2.
- **Why it matters:** forks get a fresh random generation id (`service.py:234`), so this is unrecorded randomness. It contradicts §4 of `contracts.md`, which says tie-breaking is pinned and draws are recorded.
- **Fix:** break ties on meaningful keys (kind, phase, actorId, priority, position in the decision), or reject conflicting writes at the same instant.

**M4. Kernel cost grows quadratically with run length.**
- **Where:**
  - Every intent group deep-copies the whole snapshot (`kernel.py:802`).
  - `_state_check` re-serializes the full snapshot plus a hash of the spec for every group (`kernel.py:809`, via `contracts.py:304` and `312`), and rebuilds the template map once per commitment (`kernel.py:724`).
  - `appliedEvents` is a list, so each lookup scans it (lines 390, 682 and 750).
  - Interactions and commitments are never pruned.
  - The spec and mechanism validation, including the flow-precision grid, reruns on every `_prepare`, three times per round under `presented-v1`.
- **Probes p5b/p9 (20 actors × 3 messages per round):** stage plus resolve takes 0.12 s at round 1, 2.0 s at round 10, 3.5 s at round 20 and 5.2 s at round 30. A profile puts about 99% of the time in deep copying and JSON serialization.
- **Fix:**
  - Use an undo log or copy only the sections a group touches.
  - Check invariants once per round.
  - Make `appliedEvents` a set.
  - Validate the spec once per process.

**M5. Hitting the per-round event limit kills the round, and actors can drive it there.**
- **Where:** `_run_intents` re-raises `event_limit` instead of rejecting the group (`kernel.py:812-813`). Zero-amount flow receipts also count toward the limit (line 673).
- **Admission gap:** nothing checks that actors × intents per phase × about 3 events, plus flows × boundaries, fits under `maxEventsPerRound`. For example, 100 actors × 10 intents is accepted against the default limit of 1000.
- **Probe p7:** with the limit set to 5, three actors sending two messages each fail the round.
- **Fix:** reject only the group that overflows, or enforce the bound at admission and skip zero receipts.

### Minor
- **m1. Breach works on any pending commitment the actor is part of,** including its own investment or policy (`kernel.py:630-632`). In p7, `a` cancelled its own capital project and the trust relation became "damaged". The penalty recipient and the relation are fixed in the template, unrelated to the actual counterparty.
- **m2. Admission gaps (p8):**
  - A fixed `amount` parameter silently overrides an `amount` input the actor can see in its menu (`kernel.py:579` against line 141). The actor asked to move 1 and 9 moved.
  - An actor whose id is literally `external` owns every external source and sink (`contracts.py:247`). In the probe it spent the external `raw` account.
  - Priority-rule triggers on analyst-only records are accepted and appear in the actor's prompt (`kernel.py:246-251`).
  - Enum element types are not checked.
  - An offer can expire before it is delivered.
  - Message length and inbox size can be set as high as 10 million.
- **m3. Kernel bugs are reported as actor rejections.** Invariant failures such as `duplicate_effect`, `negative_quantity` or `invalid_json` get this treatment because they're missing from the fatal set at `kernel.py:812`.
- **m4. Rejection codes reveal hidden state.** A failed acceptance tells the acceptor whether a hidden rule blocked it (`rule_ineligible`) or funds did. The existing staging test doesn't cover these receipts.
- **m5. Traps for weaker models:**
  - Proposal-phase observations show the inbox but offer no response operations (`observations.py:45`). Two attempts to accept there use up the slot.
  - A partial acceptance can't be withdrawn (`kernel.py:513`).
  - One recipient's counteroffer cancels a multi-party offer for everyone.
  - Under review modes v1/v2, a single invalid candidate ends the run.
- **m6. Controller:**
  - When several actors fail, the error raised is whichever finished first (`controller.py:170-176`), so the reported cause varies.
  - A non-`WorldError` from a non-HTTP policy, such as a list where `templateId` or `status` should be (`contracts.py:331` and `370`), gets generic feedback and is never eligible for repair (`controller.py:72-75`).
  - Object items in `stateUpdates` have no size limit (`contracts.py:343-365`).
- **m7. Scheduled events run from the snapshot, not the pinned spec.** The kernel uses the snapshot's copy of `scheduledEvents` (`kernel.py:680`), and nothing checks it still matches the hash-pinned spec.

## 2. Keep unchanged
- **Exact decimal quantities:** decimal-string handling (no floats, at most 12 places, bounded size), 80-digit precision at every kernel entry point, and refusing flow grids that can't be represented exactly instead of rounding them.
- **Resource accounting:** gross-debit aggregation in `_transfer`, so circular transfers can't create funds; separate reserve and release paths; the check after every group that reserved amounts equal the sum of pending holds.
- **Atomicity and consent:** all-or-nothing intent groups and bundles. Staging handles only communication and ignores hidden feasibility. Recipients see exact obligations before consenting. Consent requires every recipient on the exact interaction. Withdrawals are processed before responses.
- **Time handling:** flows integrated between effect boundaries, each round covering (t, t_next], opening effects settled before the first observation, settlement that includes the horizon, and later obligations left pending.
- **Observations:** an allowlisted view with a digest-bound observation id, mechanism parameters never in the menu, delivery-gated feedback, and per-period flow summaries in place of raw receipts.
- **Purity and tests:** a pure core that never mutates its inputs, with no I/O, clock or module state. The 74-case kernel suite is thorough and worth keeping.

## 3. Hazards for sharing the repo with the other engine
- **Error base class:** `WorldError` subclasses `ValueError` (`contracts.py:33`). Any broad `except ValueError` in shared pipeline or API code will swallow world-v1's fatal errors. Give it its own base class or audit those handlers.
- **Overlapping names:** these names overlap the other engine's world vocabulary:
  - world-v1's: the schema ids (`world-snapshot/v1`, `world-result/v1`, `simulation-world-spec/v1`, `actor-world-observation/v1`), the `world_simulation` package and the `/world` route.
  - the other engine's: `world_model*.py`, `world-model-state/v1`, the `/world-state` route and the `SIM_WORLD_*` flags, which only apply to OASIS.
  - **Don't rename the schema constants:** they are baked into spec hashes, revision digests and the fixture hash in `/Users/rogerlin/.codex/worktrees/reflexive-world-simulation/DeepResearchForecast/backend/tests/test_world_public_grammar.py:22`. Separate the two engines through the engine pin, UI labels and config docs instead.
- **Different conventions:** decimal strings and lowerCamelCase here, floats and snake_case in the other engine. Shared report and chart code will need an adapter per engine.
- **Decimal context:** outside the kernel entry points, the contract helpers use whatever decimal context is current (`abs()` in `decimal()`, the multiplication in `add_days`). Another module changing the global context could change world-v1 admission results.
- **Tests skip in the normal gate:** all four core test modules are marked `guarded_runner`, so they skip unless `MAIN_OFFLINE_EVIDENCE` is set (`/Users/rogerlin/.codex/worktrees/reflexive-world-simulation/DeepResearchForecast/backend/tests/conftest.py`). The kernel and grammar tests are pure and can safely run unguarded. Otherwise regressions from the merge won't show up.
- **Safe to share a process:** there is no mutable module state, `__init__` imports only `contracts`, and the lazy imports stay inside the package.

Something else wrote untracked files into the Codex worktree at 02:44 today, under `docs/handoff/reflexive-world-simulation/behavior-rerun/semantic-consistency/release-readiness/evidence-recovery/`. I did not write them; the branch tip is unchanged.
