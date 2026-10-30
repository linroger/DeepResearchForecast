# Durable run spending handoff

**Last Updated (UTC):** 2026-10-29T06:03:40.503670+00:00
**Status:** Complete for approved offline implementation; source remotely delivered.
**Current Focus:** Preserve the accepted source/evidence baseline and deliver it before World Anchor implementation.

## 1) Request & Context
The user explicitly approved spending-PLANS.md implementation on2026-10-29, codeworkonly. The completed acceptance source is fadd9594 with718passing checks; this isolated worktree starts at0d46ccbfc10b109562179b7647c81c1b86f70407. A separate overhaul draft adds a world-model hub but remains unapproved. No new provider spend, public probe, scheduler, deployment or saved-run mutation is authorized.

## 2) Requirements → Acceptance Checks
| Requirement | Scenario | Evidence |
|---|---|---|
| Immutable whole-run cap | Concurrent parent/child reserves retain maxima within integer micro-USD ceiling | SB-01/SB-02/SB-06 |
| Every physical dispatch admitted | Model reasoning/JSON repair and tool retry raw sends join exact committed attempts | SB-03/SB-04/SB-07 |
| No degraded bypass or renewed allowance | Typed stop propagates; missing context/ledger and resume/fork cannot renew cap | SB-05/SB-08/SB-09/SB-10 |
| Correct cost language | External bounded quotes separate from usage estimates, credits and subscription | SB-11 |
| Private runtime and compatibility | Source/import/storage isolation before app import; legacy behavior unchanged | SB-12 |

## 3) Plan & Decomposition
Freeze the shared stdlib store/context/adapter contract. Implement store and ledger tests; integrate parent/child raw transports and lifecycle with disjoint ownership; stage private headless launcher; verify actual producers and adversarial restart paths under the existing guard; independent review and scoped delivery. Full approved design is PLANS.md.

## 4) To-Do & Progress Ledger
- [x] Owner approval recorded and fresh managed worktree created.
- [x] Record initial API/ownership contract; store owner must freeze exact shapes before adapters finalize.
- [x] Core store/authority/quote/fence owner acceptance:93guarded cases, frozenb54; integrated acceptance still required.
- [x] Parent/child/tool adapters implemented with owner gates; final composed process proof remains pending.
- [x] Lifecycle, launcher, actual parent/child transport composition and supported fresh-PID backend resume accepted.
- [x] Independent final review: no remaining technical gates for the frozen approved offline scope.
- [x] Scoped source commit c2736d3648f323d0fd2cc83b9ba53966f5484f3f pushed and matched on legacy/codex/target-run-spending.

## 5) Findings, Decisions, Assumptions
Retain every committed maximum for the authorization lifetime; usage never refunds balance. SQLite WAL/FULL and immediate transactions are control authority, while telemetry stays observational. One qualified external API route and priced Firecrawl search/scrape are the closed first profile. Unverified tariffs or hidden retries refuse dispatch. No code acceptance is a paid-run approval.

## 6) Issues, Mistakes, Recoveries
Issue11 tracks this implementation. Existing issue10 tracks later empirical acceptance. Preserve failed receipts and do not relabel estimates as actual bills.

## 7) Scenario-Focused Resolution Tests
SB-01throughSB-12 in PLANS.md are the criteria. Tests must reach actual raw transports with fakes; a green standalone counter is insufficient. Use existing main_offline_pytest.py with exact registered child fixtures and no relaxed guards.

## 8) Verification Summary
Final combined gate B:1201passed/0failed/0skipped. Current workflow05:8passed/0failed/0skipped, including actual SDK/HTTP-mocked parent+child authority and supported backend resume. Import-isolation regression:3passed. Launcher current-byte gate:86passed after AST-identical lint comments. Startup09 executes private CPython, actual app/linear admission and installed SDK/tools with a bounded exercise engine and MockTransport;8attempts/66112synthetic microUSD retained, closed. See evidence/final-verification.json and review.md. Recorded blocked dependency probes remain disclosed; none is relabeled zero-attempt. No real provider/account/tariff/billing qualification occurred.

## 9) Remaining Work & Next Steps
Deliver the reviewed spending source and verify remote parity. The owner subsequently approved the separate World Anchor plan for code/offline tests; its implementation starts from this delivered baseline in a separate worktree. The broad overhaul remains unapproved. Future live release needs verified pricing/billing class and explicit numeric authorization; partial target-v3 research resume remains unsupported.

## 10) Updates
- 2026-10-29T02:52:51.343639+00:00: Created before new feature source changes; preserved completed acceptance branch and user approval.

- 2026-10-29T03:45:04.368235+00:00: Shared exactmanifest/binding/dispatch API frozen in contracts.md. Store, parentrawtransport, child/tool, and private-launcher owners are implementing disjointfiles. Coordinator added optionalcommonadmission/lifecycle, strictHTTPfield check, operation scopes, childregistration, no-site childcommand, bridge-copy parity and typedstop handling. Initial source parses/Ruffpass; actualruntimechecks waitforcoreimplementation. Integration review caught env-binding advancement and registered-child-operation mismatch before acceptance: coreowner ismakingvalidated transitions atomic; parent now registers the exact childoperation used in its exportedcontract. No livecalls.

- 2026-10-29T04:12:24.098524+00:00: Parent lifecycle11cases pass on realsharedstore: SPA/SDK/direct immutable binding, extra/mismatchedrequest no dispatch, targetpublicationclosesledgerwithoutrefund, estimatordenialfailsratherthandegrades, cancellationhaltsbeforeevent, explicitcleanresume retains prior debits. Parentrawtransportowner123cases andchildgateway/toolowner698cases are reported withfaketransports; finalsharedcorehash rerecheckisrequiredafterintegrationhardening. Launcher65syntheticcases pass butactualprovisionedprivateprocessstartupisbeing completed, preservinggroupwritable-source refusal via privateinterpreter/dependencycopies. No realprovider/credential/probe/scheduler action.

- Coordinator gap closure plan: a new workflow-level fixture is assigned to parent-transport owner to prove child gateway/tool, parent method and actor sends share one ledger across actual processes; include fresh-process resume retaining prior debits if feasible. Childowner is qualifying installedLangChain via private hashed dependency copies andfakeHTTP. Launcherowner is preserving group-writable-binary rejection while staging a private verified interpreter copy for actual no-site process startup. These are remainingSB02/SB08/SB12 acceptance, not optional live follow-ups.

- 2026-10-29T04:48:29.189995+00:00: Integrationreview foundP1: mutable savedrequest copy couldbeeditedwithstate whileimmutableauthorizationhash stayedold, allowingchangedquestionSDKsendswithinbudget. Addedcorevalidate_bound_request andcalleditbefore_run andbeforeresumegenerationadvance. Lifecycle17casesnowpass withactualSDKpositivecontrols andquestion/path/period/seeddenial; core93casefinalgateb54 independentlyreviewed. Supportedcleanresume requiresreceipt-valid completedresearch; partial target-v3 research/auto-reuse is explicitlydenied beforechilddispatch until a real checkpointcontract exists. LauncheractualprivateStartup06 currentcorepassedapp+child+harness+actualLCSDK/tools undercopiedprivateCPython, HTTPonlymock. Final actualregisteredchild→parentmethods/actors andfreshPIDbackendresume proof is inprogress.

- 2026-10-29T05:03:26.316516+00:00: Currentcriticalpath: close childpromptfile/in-memoryquestion binding to immutable R/control/request.json, then refresh exactsource private startup and corrected SB02/SB08workflowproof. CommonstateP1 is closed on coordinator796/coreb54 with17lifecyclecases. Core93,parent123,child698+actualLCSDK8mockcalls,launcher78+actualStartup07 are historical exact-byte receipts; anynewchild/launcher question guard requires affectedrerun. Workflownegative was corrected to discriminate retention (cap2.00, prior0.60, actorquote1.90) and pair fundedcap5control; those are synthetictest amounts, NOT humanpaidapproval. No spending-ledger code is committedyet.

- 2026-10-29T06:03:40.503670+00:00: Final coordinator gates completed and independent review closed. Broad A preserved1200pass/1failure: a fresh-import test removed only one of the canonical spending aliases. Test-only cleanup now removes/restores both and asserts shared identity; production duplicate-instance denial remains unchanged. B passes1201, workflow05passes8oncurrent source, affected launcher86passes. Three intentional import locations received F401 comments using two replacement patterns; full test AST is identical to the Startup09 fixture. Current frozen17production/control hashes match.
- 2026-10-29T06:03:40.503670+00:00: Durable private evidence copied to /Users/rogerlin/.local/share/DeepResearchForecast/evaluations/run-spending-acceptance-20261029T060017Z. Complete regular-file hashes match and originals remain unchanged; internal convenience links were relocated within each copied tree. Copy integrity is not a relocated execution claim. Private source/runtime/closed ledgers stay outside Git; sanitized gate summary is committed.

- 2026-10-29T06:09:08.763110+00:00: Source commit c2736d3648f323d0fd2cc83b9ba53966f5484f3f remotely verified on legacy/codex/target-run-spending; issue11closed for offline scope. Exact committed source archived in the durable private evidence root. Issue10remains empirical; issue12records explicit WorldAnchor code/offline approval. No production source changed after the final accepted gates.
