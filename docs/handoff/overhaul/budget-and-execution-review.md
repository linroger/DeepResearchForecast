# Budget and execution review — draft for approval

Reviewed 2026-10-29 (Asia/Shanghai); attachment dated 2026-10-28. Planning only; no overhaul or spending code is authorized.
Authority: [new PLAN.md attachment](</Users/rogerlin/.codex/attachments/187dc6b8-4f4d-4ed7-9cfa-b804d117d726/Pasted text.txt>), 445 lines, SHA-256 `f7bd878e0530fb22a2724b92a1b0f6474cc967c2648fe4a95266ae7c02fa939a` (cited as **P:line** below).
Read with `../target-first-acceptance/spending-PLANS.md` and `live-readiness.md`; those remain historical proposals, not the execution roadmap. The new draft supersedes roadmap priorities, not already verified source or its evidence.
At inspection, HEAD was `e0b233779a08493603360ddd4b5f4ba12a0183bf` with concurrent parent changes. The parent is finalizing their verified delivery; neither the draft's `main f773f61` nor this dirty snapshot is the next implementation baseline. Freeze the parent's delivered source before assigning slices (P:4,32).

## Decision

**Retain the spending boundary as a small prerequisite to paid acceptance, aligned with A5 and B1—not a competing architecture.** Part VIII specifies attribution, per-phase RunSpec budgets and graceful stops but does not define immutable whole-run USD admission, physical-attempt pricing or durable restart behavior (P:292–294). A5 telemetry and B1 replay/storage alone do not enforce money limits (P:309,312).
There is **no numeric spending approval**. The old illustrative USD 5 proposal and its particular question/path settings are not approvals or defaults for the overhaul. O-10 explicitly requires separate C/F/G/cohort approvals (P:414).
The earlier free probe is already consumed: the sanitized `../target-first-acceptance/market-probe-receipt.json` records Gamma transport failure, zero rows/model calls/provider spend, and CLOB unattempted because no token ID. It authorizes no retry or new probe; it proves neither CLOB failure nor provider readiness. This task makes no network calls.

## Reconciliation with A5, B1 and Part VIII

| Requirement | Smallest adjustment to the prior spending plan |
|---|---|
| A5: usage folded into `by_stage`, across resumes | Reuse existing research/simulation aggregation; add stable `(run_id, phase, step_id, attempt_id)` joins and preserve actual-versus-estimated usage. Parent summaries reference child attempt IDs rather than charging them twice. Accounting remains distinct from admission (P:292,309). |
| B1: one world-model store and sealed exports | World-model records remain the forecast authority. Recommend a small **control-plane spending sidecar**, referenced by RunSpec and the B1 manifest, with read-only summaries available to the hub. World exports/replay/forks must never restore or recreate allowance. Physical colocation is an O-2 design decision, not assumed approval (P:51–54,312). |
| RunSpec budgets per phase | Define one immutable external-USD ceiling plus explicit phase ceilings in the admission binding; conservatively require their sum ≤ the whole-run ceiling. Each reservation passes both checks atomically. No silent phase transfers. RunSpec is named but its budget schema is absent from Appendix A; agree this small contract before adapters (P:292,418–441). |
| Phase/step attribution | “Phase” in RunSpec means workflow phases 0–7, and `step_id` means A-00/R-05/S-05/E-01/V-05 etc. Implementation milestones C/F/G are experiment scopes, not new balances. Bind admission A-00 and asynchronous R-00 spending before their first dispatch (P:74–103,300–355). |
| Caching and fallback | Local exact-cache hits make no new reservation; provider-side caches still require a priced maximum. Each repair, retry, reasoning resend and allowed provider fallback is a separate physical attempt. Part VIII's fallback-provider behavior requires priced admission of that route; otherwise deterministic fallback only (P:291,294). |
| Graceful halt | A money/authority denial is not an epistemic shortfall. Stop further paid dispatch with a typed budget reason, preserve partial records and render only available deterministic output. Do not call a paid writer to explain exhaustion or count a fallback as a successful judgment (P:22,292,294). |
| Broader overhaul coverage | The old one-model/Firecrawl closed profile is only a possible first experiment. C/F/G add verifier, prior, judge, effect, crux, writer, critic and translation calls; channels/embedding routes may also spend. Each enabled route must join the same boundary before its paid slice; disabled routes stay off. Do not build every future adapter now. |

## Existing mechanisms and precise missing seam

| Current source | Reuse or necessary change after approval |
|---|---|
| `backend/app/services/world_simulation/store.py:145,175,425,609,633` | Reuse FULL-durability SQLite transactions, fencing, pre-dispatch attempts and retained unknown exposure. Avoid importing world-state/private-observation schemas into a generic spending table. |
| `backend/app/services/world_simulation/policy.py:738,746,754` | Reuse bounded request quotation and upward rounding, with verified route/model tariff and actual output/reasoning envelope. |
| `deerflow_bridge/research_budget.py:211,291` | Reuse cross-process coordination patterns/tests; its fail-open tool counters, lease TTLs and `synchronous=NORMAL` cannot be the hard money boundary. |
| `backend/app/utils/telemetry.py:403`; `backend/app/utils/llm_client.py:568–582` | Current USD check is post-response and estimated. Keep telemetry; reserve before physical dispatch instead. |
| `pipeline_orchestrator.py:8912,9155,12052,12095,15177` under `backend/app/services/` | Bind once at `start`; validate the same ledger at `resume`; retain research/simulation summaries. `LLMMeter.reset` must not reset spending. Resolve function-name anchors again after the parent's commit. |
| `backend/app/utils/llm_client.py:332,987`; `deerflow_bridge/research_gateway.py:1622` | Wrap each raw completion/invoke after final parameters are chosen. Parent SDK retries currently turn off only in the custom-HTTP-client branch; required mode must suppress all hidden retries or reject that adapter. |
| `deerflow_bridge/search_tools.py:452,492`; `deerflow_bridge/cached_fetch.py:321,355` | Reserve each actual tool POST, not the outer search counter. Firecrawl retries and remote cache settings must not bypass charging. |
| `backend/app/services/forecast_tournament.py:33,59`; `backend/app/services/target_simulation.py:283` | Propagate spending stops through broad exception handlers; do not turn them into error lanes/actor holds followed by another paid call. New step wrappers must obey the same rule. |

Small proposed core: a stdlib `deerflow_bridge/run_spending.py` using the patterns above, with manifest binding, transactional reservation, stop/fence and sanitized receipt APIs; existing bridge sync/import mechanisms deliver identical bytes to the child. It does not exist yet. No billing platform, new research engine or rewrite of working world storage is needed.
The minimal dependency is: **parent verified delivery → approved budget contract → A5 stable attempt attribution + minimum B1 budget reference → strict shared dispatch gate and affected adapters → guarded fake-transport acceptance → separately approved priced experiment**. Full B1 can proceed offline in parallel; a full hub rewrite is not needed to establish the gate. Even earlier paid B2/B3 admission/prefetch needs it.

## Durable cap semantics to approve

- One authorization binds one run/request/source/route/tariff set. Store currency in fixed-point units; no floats. Whole-run and phase maxima are immutable for that authorization.
- Recommended first version keeps every committed maximum for the run's lifetime: `sum(reserved_max) ≤ approved_cap`, with the same invariant per phase. No recycling from estimated successful usage; more conservative than the current world evaluator, requiring explicit owner acceptance.
- A logical key identifies phase/step plus checkpoint, method, actor/path/period or tool context and input hash; each physical attempt gets a unique ID and ordinal. Commit before I/O; repeated receipt writes are idempotent, repeated dispatch requires a new reservation. Keep this metadata out of actor-visible prompts.
- Unknown/timeout/possibly-sent errors retain their full maximum and stop the initial experiment; no blind retry or zero-cost inference from 429. A late response adds evidence, never renews allowance. Missing/corrupt ledger or context fails closed.
- Clean explicitly authorized resume uses the same balance and a new owner fence only; task IDs, process restarts, research epochs and phase exports cannot refill it. Cancel/exhaustion/unknown outcomes do not reopen automatically. Already admitted in-flight calls remain fully reserved.
- External model fees and tool/prepaid-credit consumption are recorded separately from subscription request/token/quota usage. Unknown billing classes block. Never price a coding subscription by a public API tariff, call it resource-free, or label a usage estimate a bill. Invoices are separate evidence; no invoice service is needed for the first gate.
- Preserve the ledger outside deletable/replayable phase artifacts; freeze its binding in a private authorization registry. Rollback stops the bound run and preserves receipts; an older binary or disabled flag cannot resume it uncapped. No historical migration or reset from `run_telemetry.json`.

## Conditions before any paid milestone

Common gate: explicit implementation-slice approval; frozen reviewed source and isolated runtime; all enabled dispatch routes covered; pinned finite input/output/reasoning/tool bounds and pricing/billing class; passing guarded denial/race/retry/crash/resume tests; exact experiment manifest; **fresh numeric whole-run and phase ceilings plus run count authorized under O-10**. No configured key, token forecast, prior spend allowance or elapsed-time limit substitutes for this gate.

| Paid milestone | Additional concrete admission conditions |
|---|---|
| C confirmation | B1/B2 and the relevant C slices pass their offline contracts; freeze target/settlement/as-of, KIQs, actor/mechanism/claim-verifier limits and channel routes. Price repair/retry work, not just successful calls. Approve G0 for this first-ten run. The 80–120 research-call estimate does not bound ≤60 R-05 verifications, dossier repairs or new tool dispatches (P:77–118,317–323,370). |
| F confirmation | E2 review/checks and the selected F kernels/observation/decision paths pass scripted and replay gates; approve G1 and freeze cast, K, periods, triggers, plans, per-step ceilings and source hashes. Resolve whether O-8's 120 counts logical decisions or physical sends; recommend physical S-05 sends including repairs across paths. Resolve S-08's “sample twice / ≤40 calls” as ≤40 physical samples, not 40 occasions doubled silently; price custom judges and optional discourse separately (P:162–202,334–342,412). |
| G confirmation | Selected G dependencies, estimator identity/policy, leakage tests and tokenized writer audit pass offline. Freeze estimator/section counts, critic/rewrite/translation allowances and any retrieval routes; deterministic readers add no model allowance. Keep shadow/zero weights and block budget stops from being reported as successful judgments (P:208–240,344–349). |
| Forward cohort / H2 | Freeze eligible questions, settlement contracts, cutoff, estimator policy, score lanes and enrollment/failed-run denominator before outcomes. Separately approve cohort count and numeric total, per-run and per-arm allocations, including equal-budget ablations; child runs/resumes cannot each claim the whole cohort allocation. Reuse a frozen allocation manifest referencing one-run caps; no scheduler or general cohort service is needed for the first manually launched case. Later automated allocation needs its own acceptance (P:272,353,374–382). |

`backend/scripts/forward_cohort.py:18,52` only validates a dry proposal (`enrolled=false`, `paidRunsStarted=0`); it provides neither funding nor launch authorization. The promotion condition is prospective paired lift with CI excluding zero and n≥30 in the lane, not one successful C/F/G run (P:272). Monitor-on-24h text and O-9 do not authorize H1/M-02 recurring paid research; schedule, cadence, total allocation and stopping rules require a separate decision (P:244,284,308,413).
The claimed 2.5–3M-token standard-run total and comparison with today's 8–15M are **unverified planning estimates**, not a quote or measured savings; the draft itself labels research unrecorded (P:369–370). Count all physical repairs/samples/critics and cache-billing categories before presenting a priced envelope.

## Isolation, tests and owner decisions

Use a fresh canonical private `R/app` and `R/deer-flow`; all uploads, ledger/WAL, logs, caches and child homes resolve under owned private roots. Storage assignments are source-relative; an `UPLOAD_FOLDER` env value alone does not redirect them. Prevent `.env` and editable `.pth` paths from selecting deployment sources. Disable scheduler, model fallback and every unadmitted route; no production runtime synchronization. Retain private outputs and publish only aggregate diagnostics/hashes. The new `agent_io` requirement does not authorize publishing private rationale/transcripts (P:32,54,66).
Acceptance must cover: concurrent reservations; child→parent→step accounting without double debit; phase and whole-run exhaustion; JSON/reasoning/tool retries; missing usage and late replies; stop propagation through fallbacks; crash/cancel/resume/fork no-renewal; local-cache zero dispatch; unknown subscription classification; source/path isolation; byte-identical legacy mode. Reuse existing world-store, research-budget, gateway, provider and target-reuse tests.
All future app imports/tests use `/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir NEW_CANONICAL_PRIVATE_TMP_ROOT`, unchanged. Private fixtures, if needed, come only from the parent's frozen snapshot into the authorized evidence read root before imports. No tests were run here.

| Owner decision | Required approval / recommendation |
|---|---|
| O-1/O-2 | Approve hub/schema direction separately from implementation; decide the small spending control-plane reference and sidecar placement so B1 replay cannot rewind money. |
| O-7/O-8 | Approve first-ten G0/G1 gates and unambiguous physical-call counting, including S-08 double samples; these limits do not approve dollars. |
| O-9 | Reconcile already verified hotfixes instead of reimplementing them. Probe authorization is consumed; monitor activation/new probes remain separate. |
| O-10 | Separate numerical approvals for C, F, G and the cohort, with routes, scope, run counts and allocations; none exists now. |
| Proposed budget addendum to Part VIII/A5/B1 | Approve lifetime retained maxima, immutable whole-run plus phase limits, stop/resume semantics, accounting classes and the smallest dependency above before coding. These decisions are not supplied by O-8 alone. |

Disposition: draft ready for parent/owner review; no permission question or implementation request issued by this owner. Only this file was created; previous verified code, old plans and current handoff remain untouched. No app imports, provider/network calls, commits, pushes or scheduler actions were performed. Source anchors describe the inspected snapshot and must be refreshed after the parent's final commit.
