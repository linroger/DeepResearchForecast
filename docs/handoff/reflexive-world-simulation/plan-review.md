# Independent review of the reflexive world simulation plan

**Last reviewed (UTC):** 2026-10-16T14:14:19Z.
**Terminal verdict:** PASS — no remaining blocking plan defects within the reviewed scope. The proposal is ready for the user's required plan approval.
**Review status:** Complete. R1, R2, R3, and the associated M0/M5 clarification requests are closed at planning level.
**Scope:** Independent planning review of `PLANS.md`, `contracts.md`, and `acceptance-scenarios.md`, informed by all three completed design inputs. This final pass reviewed only the requested amendments and their consistency with the established design. It did not reopen implementation or unrelated architecture.
**Assigned worktree:** `/Users/rogerlin/.codex/worktrees/reflexive-world-simulation/DeepResearchForecast`.
**Assigned branch/base:** `codex/reflexive-world-simulation` / `8852ce123fa15a6b4f4c3e6e4e492435c0e3137b`, supplied by the task and not independently checked with Git.

The amended proposal supports concrete evolving world state, independent goal/belief/incentive/constraint-driven actors, consequential actions, and next-epoch responses across the three declared domains. Its remaining work is the already-planned M0–M5 implementation and validation after user approval. No further plan amendment is required by this review. This verdict is a design assessment, not runtime acceptance, implementation authorization on the user's behalf, or evidence of predictive accuracy.

## Current design and bounded limits

The evaluation control is an **external-feedback ablation**. It retains the same physical kernel, conservation and authority checks, own-account state, and mandatory offer/consent/action-receipt protocol. Only preregistered external observation fields/channels are withheld; the contrast is measured at the declared next decision epoch. Later learning through permitted interactions is allowed. The mask must not remove consent terms or reveal withheld information through menus, summaries, or retries. This is the current interpretation throughout this review, including its history.

The current cap is **three intents per actor per phase**, with **one initial decision slot and at most one response slot per actor/period**, each permitting **at most two actual external provider attempts** including retries, fallback, and model-assisted repair. Multiple intents fit within one response; they do not create additional model-call slots. The evaluation maximum remains 36 runs × 4 actors × 4 periods × 2 slots × 2 attempts = **2,304 actor attempts**, subject to earlier hard-budget termination. Separate compiler evaluation requires its own allowance. These limits agree between `PLANS.md:139–140`, `contracts.md:51,93–97`, and `acceptance-scenarios.md:69`.

The store remains a single-host SQLite world ledger with WAL and synchronous=FULL, canonical logical-record hashes, and a fenced writer. Semantic state hashes exclude wall-clock, attempt, and fence audit metadata while retaining causal/model identity. Recovery of recorded effects and accounting for uncertain external dispatches are distinct responsibilities.

## Critical issues — all findings closed

### R1 — immediate-effect timing and the commit barrier: CLOSED

**Current evidence:** [contracts.md:47](/Users/rogerlin/.codex/worktrees/reflexive-world-simulation/DeepResearchForecast/docs/handoff/reflexive-world-simulation/contracts.md:47), lines 47–55; [acceptance-scenarios.md:58](/Users/rogerlin/.codex/worktrees/reflexive-world-simulation/DeepResearchForecast/docs/handoff/reflexive-world-simulation/acceptance-scenarios.md:58).

The earlier defect was that immediate effects chosen after an opening observation had no coherent place in an interval whose opening-time effects were already committed. The current contract distinguishes pre-existing scheduled effects at opening time from newly selected effects ordered by `(simulatedTime, phase, sequence)`. Immediate effects belong to the resolution phase without rewriting the opening view; interval flows follow them. The terminal horizon settles due work without adding a decision epoch.

The explicit RW-04/RW-08 trace now covers opening budget 10, post-decision project debit 6, remaining budget 4 before interval flows, completion after two full periods, a half-period completion, boundary-effective rules, and crash replay. This resolves the requested semantics and records how implementation will prove them. The single next-state publication barrier remains intact.

### R2 — durable unfinished negotiations and eligible responders: CLOSED

**Current evidence:** [contracts.md:21](/Users/rogerlin/.codex/worktrees/reflexive-world-simulation/DeepResearchForecast/docs/handoff/reflexive-world-simulation/contracts.md:21), lines 21, 27, 30, 49–67, 83; `PLANS.md:88,120`; [acceptance-scenarios.md:52](/Users/rogerlin/.codex/worktrees/reflexive-world-simulation/DeepResearchForecast/docs/handoff/reflexive-world-simulation/acceptance-scenarios.md:52) (RW-17).

The earlier defect concerned unaccepted counteroffers, delayed messages, and inbox overflow that were promised to survive but had no explicit authoritative recovery state. The new `interaction-envelope/v1` names their identities, exact terms versions, recipients, delivery/expiry times, withdrawal/supersession, response state, and queue order. Envelopes and their queues are included in snapshot, round, and store closure, with exact reconstruction from committed events permitted. Unaccepted offers are explicitly distinct from obligations.

Later acceptance must revalidate current authority, terms/version, expiry/withdrawal, and joint resources. Preacceptance holds require a named hold mechanism. Positive delay excludes same-epoch response; overflow preserves order and expiry across restart. Proposal and response rosters freeze separately. The pinned `onDeliveredOffer` trigger can admit an authorized recipient who had no initial proposal slot, within the existing cap; a deferred or ineligible item is distinct from a failed required response. Tentative disclosure is bound to persisted round receipts, and failed rounds do not publish it as a committed event.

RW-17 now covers delayed counteroffers, initially inactive recipients, overflow, restart, expiry/withdrawal, stale consent, and preacceptance holds. RW-05–08 continue to require privacy, consent, failed-round, and duplicate-effect controls. Stateless transports over persisted actor memory prevent failed attempts from leaving undeclared conversation state. The amendment closes R2 without introducing a separate messaging service or wider negotiation scope.

### R3 — enforceable actual-attempt budgets across recovery: CLOSED

**Current evidence:** [contracts.md:83](/Users/rogerlin/.codex/worktrees/reflexive-world-simulation/DeepResearchForecast/docs/handoff/reflexive-world-simulation/contracts.md:83), lines 83, 91–97; `PLANS.md:88,139–140`; [acceptance-scenarios.md:51](/Users/rogerlin/.codex/worktrees/reflexive-world-simulation/DeepResearchForecast/docs/handoff/reflexive-world-simulation/acceptance-scenarios.md:51) (RW-16).

The earlier defect was enforceability, not the numerical cap. The prior source review identified nested retries, fallback, JSON repair, and CLI subprocess boundaries in `backend/app/utils/llm_client.py:459,581,613–619,1028–1033,1093–1098`. The amended plan no longer assumes that reusing that interface establishes an actual-request ceiling.

World-mode preflight now requires controllable request, retry/fallback, output, and context boundaries. Automatic SDK retries are disabled for the supported HTTP path; an opaque CLI transport cannot enter strict-budget mode until its capabilities are demonstrated. The same adapter governs repair and fallback dispatches.

Every external request consumes a durable allowance reserved under its stable slot identity and current fence before dispatch. Ambiguous dispatches remain conservatively spent and are not misrepresented as measured billing. Resume preserves spent allowances and successful peers; exhausted slots stay exhausted under the original specification. Replay/cache does not make a new external attempt. Hard budgets additionally reserve conservative in-flight input/output/pricing exposure and reject transports that cannot bound it. Tentative observation, decision, and attempt writes are fenced as well as world commits.

RW-16 now requires boundary-fake verification of retry/repair/fallback combinations, dispatch-before-receipt crashes, repeated resume, concurrent slots, unsupported-transport preflight, separated usage categories, and no partial world commit on exhaustion. This directly closes the two enforcement gaps. It is a world-engine capability rule, not a global provider migration.

## Important issues and suggestions — incorporated

No important plan issue remains open from this review. The following previously requested details now have explicit contract or acceptance coverage:

| Review request | Closure evidence and assessment |
|---|---|
| Stable goals and authorized revisions | `contracts.md:20` defines the update whitelist and forbids post-hoc goal/value/incentive/priority-rule rewrites without a declared rule and triggering evidence. RW-18 at `acceptance-scenarios.md:53` covers belief updates, rejected stable-model rewrites, authorized priority changes, and replay. |
| Private raw rationale and rollback-safe memory | `contracts.md:67` makes raw rationales/belief updates private by default, projects public explanations from authorized content, and requires stateless transport over persisted memory. Existing recipient/metadata/menu tests remain applicable. |
| Semantic replay hashes and fencing | `contracts.md:83` explicitly excludes wall-clock/attempt/fence audit metadata from semantic hashes, preserves causal/model identity, and fences tentative writes. M0 fixes membership in golden fixtures; RW-08 supplies later behavioral evidence. |
| Responsiveness independent of aggregate score | `acceptance-scenarios.md:60` requires preregistered, direction-specific contrasts at the declared epoch in every domain, in addition to the 80% behavior threshold. Missing or budget-stopped cases remain incomplete. Explanations or feasibility scores cannot substitute for responsiveness. |
| Valid evaluation control | `acceptance-scenarios.md:75` preserves own-account and consent/receipt information, withholds only the declared external feedback, and admits later learning from permitted interaction outcomes. It tests the specified information intervention without disabling physical rules. |
| Intent and provider-call caps | `contracts.md:51` and `PLANS.md:140` both say three intents per phase. The two-slot, two-attempt limit is unchanged, so the actor-call arithmetic at `acceptance-scenarios.md:69` remains valid. |

M0 schema/fixture freezing and M1–M5 execution remain ordinary delivery obligations already in the proposal. They are not new approval blockers or claims that those checks have passed.

## Positive notes and retained review coverage

| Area | Planning assessment |
|---|---|
| Consent, resource conflicts, delays | Exact terms, independent counterparty responses, current resource/authority validation, reservations, atomic bundles, declared conflict rules, delayed settlement, and explicit breach mechanisms are coherent with the new durable interaction state. |
| Privacy and metadata | Actor-local observations, hidden-state-independent menus, server-bound actor identities, private rationale defaults, and separately permitted analyst projections retain the intended information boundary. RW-05 addresses effective bytes rather than warning labels alone. |
| Uncertainty and research provenance | Sealed legacy and unsealed v3 research remain distinct input grades. Unknown values, scenario assumptions, actor beliefs, and sampled mechanism uncertainty are not promoted to sourced facts or calibrated probabilities. |
| Forecast isolation | `contracts.md:107` and RW-11 retain clean probability inputs under pinned safe policies, including no-spine, missing-research, and repair paths. Richer simulated narrative cannot re-enter probability extraction through fallback prose. |
| Engine admission and consumers | Engine identity, strict completion, independent fork/seed stores, legacy compatibility, and frozen API/UI/report/chat/chart/translation/export results remain required across M3/M4 and RW-09–15. |
| Scope and rollout | Three cross-domain packs share the same contracts and real consumers. Mechanical correctness, actor behavior, and any future predictive calibration remain separate. The staged new engine and retained legacy readers are proportionate; no universal causal solver or global workflow migration is required. |

## Review history and closure record

- **Initial review, 2026-10-16:** Identified R1 (opening-time versus immediate-effect ownership), R2 (pending negotiation persistence and responder eligibility), and R3 (transport and crash-safe attempt accounting). Also requested explicit stable-goal revision checks, semantic hash membership, private rationale treatment, and a separate responsiveness gate. These were design findings, not observed production failures.
- **Intermediate rereview, 2026-10-16:** Closed R1 after time/phase/sequence ordering was added, and closed the responder-roster portion of R2 after the phases received separate participant sets. Accepted the clarified external-feedback-ablation design. R2's durable interaction state and R3's enforceability remained open. Earlier baseline descriptions were superseded; the current and historical assessment in this document uses the final external-feedback-ablation semantics.
- **Final bounded rereview, 2026-10-16T14:14:19Z:** Checked the interaction envelope and closure bindings, response trigger/delay rules, stateless/private actor outputs, strict transport preflight, durable fenced reservations, cross-resume exhaustion, concurrent hard-budget exposure, semantic hash exclusions, stable-model whitelist, per-phase intent cap, RW-16–18, exact timing trace, and separate responsiveness gate. Closed R2, R3, and the associated clarification requests. **No remaining blocking plan defect was found in these amendments.**

The prior verdict applied to plan/contracts/acceptance hashes `eacf6070af5c4a1d311f18f3df86414894e9c3f271e3e76ca5f366826c203b20`, `36b11992d979469b1b332f64ade7145ed7e72985df2a955640321fcc7e6d6813`, and `30c7a38ff6d745fc95933e7d020001a1d592edc14cfb39920ec529ef96ab8005`, respectively. The current verdict applies to the final identities below.

## Final evidence receipt and approval boundary

Only `docs/handoff/reflexive-world-simulation/plan-review.md` was authored or updated by this reviewer. The final pass used document reads and hashing; it did not reread application source or introduce new source claims. The earlier review used targeted source reads and the code-review skill's evidence discipline. Prior memory supplied navigation only and did not establish acceptance for this branch.

No application changes, imports, tests, provider calls, saved-run operations, additional agents, or Git operations were performed. Source/design input documents were preserved. Final verification detected concurrent normalization of acceptance-row ordering; that document was reread, its references/hash updated, and no semantic change was found. The six reviewed document hashes were checked again after the review update and matched the identities below.

| Document | Final SHA-256 |
|---|---|
| `PLANS.md` | `b91befab4c36e425f95e45522c214fd58470081fcf2a56f49a97b691d6b1dc30` |
| `contracts.md` | `ef414419d1587ac50be4fcf9884c210daaae2ce1c7a9a1ebf9f68e82d3005074` |
| `acceptance-scenarios.md` | `b03208a71feddbb867dffd3d0f595a0ab0b411a858926536f678d43994083654` |
| `runtime-input.md` | `46376a328ffe282ad8f2b1c63a75b375b34b190af4198976c0df43c46fb0127b` |
| `actor-input.md` | `6bd30fc761008ca8b2c9c9684d32e1b00eeff822a38fd8b49752da6e1dfa5a3c` |
| `consumer-input.md` | `affc90ef2ead63198a700cd0fd66f375662947996411e2069209fbe912249424` |

**Next authorized step:** Present this reviewed plan for the user's required approval. This review is terminal and complete; implementation, live evaluation, and default-engine promotion remain subject to the proposal's existing approval and evidence gates.
