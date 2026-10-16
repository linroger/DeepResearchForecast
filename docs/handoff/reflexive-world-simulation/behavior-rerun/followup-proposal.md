# Proposed follow-up: period language and visible input grammar

**Status:** Design only; not applied. V2 live-source freeze remains in force. **Date:** 2026-10-17 Asia/Singapore.

This document is the only authorized write for this task. No backend, tests, launcher, pricing, original evidence, current study or runtime configuration is changed. No application imports, providers, test execution, commits or additional agents are used. Any later implementation requires review and coordinator approval after V2 ends; another live phase additionally requires reconciliation against the remaining original global budget. This proposal neither resumes an exhausted slot nor grants a new allowance.

## 1. Concrete observations and limits of the diagnosis

The coordinator reported three V2 issues while the study remains active:

1. In `m5-e2-trade-v1-s0-external-feedback-ablation`, a round-two explanation calls a settlement dated 2030-01-01 current-period even though the supplied decision interval starts at 2030-01-02 and ends at 2030-01-03. This motivates general temporal wording, not a case-specific action or a change to that case's score.
2. The completed investment qualitative review reports quantity 12 against a declared maximum 10 in two control runs at round four. This is a public input-schema violation that the current kernel rejects after decision admission; an HTTP-boundary check could expose it to the already permitted second attempt instead.
3. Another explanation asserts affordability equivalent to `4 >= 7`. A false arithmetic/affordability claim is **not** a public input-grammar violation. This proposal deliberately does not validate balances, force waits, change quantities or reinterpret hidden mechanisms to address it. Existing kernel feasibility checks and qualitative review remain responsible for their respective boundaries.

These are coordinator-reported diagnostics. This worker has not independently opened mutable live traces or regraded the study. The original study and current V2 outcomes remain authoritative for their own frozen sources.

## 2. Proposed general temporal instruction

Add the following compact wording to the actor system prompt in a future approved source phase:

> The current decision period is [simulatedAt, periodEnd): it includes simulatedAt and excludes periodEnd. Events or settlements dated before simulatedAt remain historical even when their records are still visible. Use the record's event/effective time when describing when something happened; message delivery time says when information arrived. A planned or due action is not a completed action. Do not label an earlier settlement as occurring in the current period.

The instruction uses only existing observation fields. It contains no domain name, calendar answer, evaluation arm, rubric target or prescribed action. An event exactly at periodEnd belongs outside this period; an event inside the interval is not automatically complete at the decision instant. Historical facts remain valid evidence and are not deleted or masked. No obligation to act again is inferred from a new period.

## 3. Proposed actor-only check and exact execution order

Keep `StrictHTTPPolicy`'s public API and feedback capability unchanged. Add a private, non-mutating check conceptually named `_validate_visible_input_grammar(decision, sent_observation)` only in its fresh HTTP response path:

1. `_request` validates the actor observation and serializes the actual system/user messages, including any existing sanitized repair feedback. Reservation still covers those exact messages and the complete output bound.
2. Before dispatch, parse the already-validated user-message text into the existing detached `sent_observation` local. Derive request-bound actorId/observationId from that same local, as today. Never reread a caller-owned object or current global state after HTTP.
3. `_dispatch` makes exactly one SDK call and applies its existing raw-envelope, model-identity, strict-JSON and trustworthy-usage checks. Existing missing/untrustworthy-usage handling is unchanged.
4. Bind only the top-level execution IDs, then apply the proposed visible grammar check against `sent_observation`. The private dispatch result may already carry usage internally, but no successful public `PolicyResponse` is returned to the controller until this check completes.
5. On a known grammar error, raise `PolicyFailure` with a fixed safe code/message and the **same known usage dictionary** returned by dispatch. This is a paid failed attempt, not unknown exposure and not a refund. Unexpected local validation failures also retain known usage behind a fixed generic error; raw exception text is not forwarded.
6. On success, return the existing decision and usage without rewriting its intent parameters, interaction IDs or terms versions. The controller still performs its normal decision, provenance and identity validation; the kernel remains final execution authority.

No repair loop is introduced in the policy. The existing controller reserves and records each attempt, supplies volatile code/message feedback to at most the second total attempt, and preserves exhaustion across resume. The evaluator wrapper continues forwarding the same kwargs and recording actual dispatches. No third request, fallback, extra model call, automatic clipping, fuzzy ID matching or invented parameter is permitted. `StrictHTTPModeler` is unchanged.

## 4. Exact information boundary

The check may read only the captured observation's visible `options`, `inbox`, `ownOffers`, actor/phase identity and simulated time, plus the existing declared protocol string-length safety bound. It must not inspect the full world specification, template mechanism parameters, global actor roster, hidden observations, counterpart balances, available funds, mandates, private capabilities or mutable state.

| Allowed check | Source and behavior |
|---|---|
| Select the declared grammar | Resolve the intent's templateId and operation against captured `options`; use the existing default operation semantics without mutating the submitted intent. Missing/unknown menu references fail with a fixed visible-menu error. |
| Parameter object and field names | Parameters must be an object containing only fields in that option's `inputs`. Omitted parameters use the existing empty-object interpretation. |
| Input types and required fields | Reuse the current scalar rules for decimal, integer, boolean, string and actor-typed inputs. Boolean is not an integer. Do not add a second implementation of these rules. |
| Bounds and enum | Apply only the declared min/max/enum and existing protocol string/decimal safety limits. Preserve the current decimal comparison semantics. Do not substitute a nearest legal quantity. |
| Empty consent parameters | Accept/reject/defer/withdraw must have no supplied parameters, even when proposal inputs are marked required. Counter/propose/execute use their declared input grammar. |
| Exact delivered references | Accept/reject/defer/counter must refer to one exact captured inbox item: interactionId, templateId and integer termsVersion must all identify the same item. Use only the presented, eligible record; do not query whether an omitted ID exists elsewhere. |
| Withdrawal references | Withdraw must match one pending captured ownOffers item and its exact templateId/version/proposer identity. Do not require recipient delivery: the existing kernel allows the sender to withdraw its own still-undelivered pending offer. Expiry/status checks may use only that captured record and simulatedAt. |

Shape/type guards needed for safe lookup must produce fixed `WorldError`/`PolicyFailure` messages rather than leaking KeyError values. Unknown top-level fields and nested provenance are not stripped or repaired; existing controller validation remains mandatory. Do not filter invalid intents out of a bundle or replace them with wait. A preflight pass establishes only public grammar, never affordability, consent, authority or successful execution.

For actor-typed parameters, a declared visible enum still applies. Hidden global membership cannot be queried at this boundary. Any value that satisfies the visible grammar but fails the kernel's full admitted-roster or authority checks must remain a possible kernel rejection.

## 5. Reuse the existing scalar grammar; parent-owned helper proposal

The narrowest candidate for review is a backwards-compatible extension of `kernel._input_values(template, intent, actors, max_chars)`: permit `actors=None` to skip **only** admitted-roster membership for actor-typed string parameters. The policy supplies a captured visible option as the input-schema carrier, a detached intent with the existing default operation filled only for validation, `actors=None`, and its already pinned public protocol text-length limit. The helper currently reads only `template['inputs']`, the operation/parameters, the actor roster for that single membership check, and the text bound; it does not require mechanism parameters or world state.

The proposed semantic change is limited to the membership guard:

```text
Existing: kind != 'actor' or value in actors
Proposed: kind != 'actor' or actors is None or value in actors
```

The parent owns any later kernel signature/type-annotation change and its review. Every normal kernel call must still pass its real actor dictionary; an empty dictionary must continue to reject every actor reference. The None mode must not skip string typing, text limits, required fields, min/max, enum, decimal rules or empty-consent semantics. All normal-dictionary behavior, normalized return values and existing kernel error codes/messages must remain identical. The policy uses the helper for validation and does **not** replace the submitted parameters with its normalized return value.

This avoids copying the scalar schema validator into policy. The small exact-inbox/own-offer reference check is separately owned by the actor adapter because it operates on the captured public projection, not the kernel's authoritative world. A lazy helper import can preserve the existing import boundary. Review must confirm that the existing pinned string bound is public protocol metadata; no new hidden or guessed input limit is introduced.

If that private-helper coupling is rejected in review, the parent may propose a pure shared grammar extraction with unchanged kernel callers. Do not implement a second independent schema validator as a shortcut. Neither candidate is applied by this document.

## 6. Historical replay and source-version invariants

**Do not add this check to `contracts.validate_decision`, `WorldStore.save_decision`, store receipt validation, kernel replay, or cached-decision recovery.** Those paths must continue to accept historical decision records containing intents that were properly rejected during resolution. Moving the grammar gate into them would turn a valid recorded rejection into an unreadable historical run.

The new check applies only to newly dispatched actor HTTP results under a later frozen source version. Cached successful decisions are reused without a new policy call. Normal kernel calls retain full roster membership and all prior execution checks, so replayed events, resolutions and state revisions are unchanged. Historical wrong-ID/terms/over-maximum outcomes and V1/V2 denominators remain intact.

Fresh behavior will intentionally differ: a visible grammar error can consume the existing repair attempt before decision persistence; if both attempts fail, the required slot stops rather than committing another kernel-rejected intent. That protocol-admission change must be disclosed in the next study's source binding and preregistration. It must not be retroactively applied to the active V2 run or used to improve its existing scores. Temporal wording is likewise a future prompt version, not a rewrite of prior explanations.

## 7. Proposed focused offline acceptance; no execution now

| Planned check | Required result |
|---|---|
| Exact SDK wire temporal wording | The system message states the half-open observation period without case dates or action answers; observations/IDs are unchanged. This verifies instruction delivery, not live reasoning quality. |
| Known-usage over-limit → valid repair | Real SDK/mock HTTP plus controller/store: first response violates a visible maximum, fails before decision persistence with known usage, second corrected response succeeds; exactly two dispatches and both charges retained. |
| Invalid twice and reopen | Two visible grammar failures retain their usage; required slot fails; ordinary resume makes no third request. |
| Quoted repair exposure | Second request uses only fixed safe error code/message, includes that feedback in its byte/cost reservation and retains the exact original observation. |
| Consent/reference matrix | Exact acceptance with empty parameters succeeds; copied/altered consent parameters, wrong item ID, mixed template/item identifiers and wrong version fail with known usage. An available counter accepts only declared new inputs. Pending undelivered own-offer withdrawal remains permitted. |
| Immutable per-call projection | Mutate the caller observation during mock HTTP and overlap two actors: grammar checks use each serialized request snapshot without cross-talk or newer global facts. |
| Scalar-helper parity | Compare real-actor-dictionary behavior before/after for valid and invalid types, required/min/max/enum, empty consent, text/decimal limits and actor membership. None skips only membership; empty dict still enforces it. |
| Historical rejected-decision replay | Reopen immutable copies of existing old-store fixtures/receipts containing wrong references, altered terms and over-limit rejected intents. Verify unchanged read/replay revisions, events and rejection records, with no provider calls. Originals remain read-only. |
| Visible grammar versus hidden feasibility | Two compatible worlds with identical captured options/protocol but different hidden balances produce the same grammar verdict. A syntactically valid unaffordable action remains a kernel rejection; no forced wait, repaired balance or fabricated authority. |
| Existing boundaries | Modeler path, unknown-usage exposure, nested provenance, request-bound outer IDs, controller/store wrong-slot/fence checks and SDK no-retry behavior remain unchanged. |

No new full-domain performance claim follows from these checks. Review should assess the helper boundary and replay compatibility before implementation; the coordinator chooses a focused guarded run, not an unnecessary unchanged full-matrix rerun.

## 8. Freeze, review and budget sequence

1. Finish and close the current V2 run under its existing frozen sources. Preserve originals, live receipts, qualitative reviews and unsuccessful results.
2. Reconcile known, unknown and interrupted exposure against the original authorized global ceiling; do not reuse a historical remaining balance or renew an exhausted slot.
3. Review this proposal, including the parent-owned optional-helper mode and historical replay invariants. Obtain explicit release from the source freeze before any runtime edits.
4. Implement only the approved delta on a new source state, run its focused guarded controls, and obtain source-bound review closure.
5. Only then may the coordinator preregister and launch a separate next phase within the actually remaining authorized budget. No next-phase launch or allocation is created here. The engine remains opt-in until the relevant behavioral gate passes.

## 9. Read-only source anchors at proposal time

| Module | Inspected boundary | SHA-256 |
|---|---|---|
| `policy.py` | `_dispatch`, actor `decide`, existing immutable serialized observation and known usage | `f44d2faab9c0d1471d76da7e038d28f74b7fa0f205ce48537f8b1bd95077ee67` |
| `kernel.py` | `_input_values`, normal roster enforcement and physical feasibility | `15eacdbdc81bdee09ac0a1a18e6289f8f3f03d7a2a4756d55b1cd9ee7946de74` |
| `contracts.py` | Existing decision-shape validation that historical receipts depend on | `781ecb0fb4f8a30f8f4bbe0fa72069cf31c56d464d30bd1d1660cedd87b61857` |
| `controller.py` | Known-usage failure recording, volatile feedback and durable attempt admission | `89022e1f7b0f1a8e18b8a5dfbae3177622db5342a9baab112a146628fa460413` |
| `observations.py` | Public menu, eligible inbox and own-offer projection | `80e87afcbfbf6d2a39c859e0061238e318df2bcb3e45b7ae9f3c4847b7381e39` |
| `store.py` | Existing receipt validation, cached decisions and replay authority | `0e140cee894f90b652105216d516341f79748723d992fed2f26b1edf42e02407` |

These hashes identify inspected code, not a new runtime test or live acceptance receipt. Only this proposal document was written.
