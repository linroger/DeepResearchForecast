# Context propagation issue ledger

At intake no finding was established. The following dated entries retain the original progression; later closure records supersede earlier pending labels. Stage-specific issue tables are in the corresponding stage notes.

- CTX-L1 (reproduced, fix applied; green pending): `/api/research/run` silently discarded backtest context, including admitting malformed cutoff as live. Real route→admission→disk red controls failed; SDK control passed. Forward the existing option and preserve typed admission errors.
- CTX-L2 (reproduced, fix applied; green pending): SDK dropped the supported internal research_language alias accepted by the SPA route. Actual stored state lost English. Align existing alias handling.
- CTX-L3 (reproduced, fix applied; green pending): Default scenario forks dropped language/model/depth/engine/round budget/safety pins, and their run manifest reflected ambient defaults. Deep-copy the finite admitted execution-context whitelist, keeping overlay precedence and old absent-pin compatibility. Parent saved state remains byte-identical.

Initial lifecycle red receipt: /private/tmp/drf-context-lifecycle-red-20261021-1 (10 failed,3 positive controls). These are actual route/state/fork/manifest behavior failures; external thread execution was parked and preflight was scripted.

- CTX-L4 (reproduced, fix applied): SDK fork dossier read an empty child handoff instead of the consumed shared source. Native SPA control passed; SDK returned has_report=false. Resolve through the existing confined handoff resolver.
- CTX-L5 (reproduced, fix applied): Canonical simulation dossier omitted rich report arguments, so manual/seed paths could not forward them. Add the finite report_artifacts family and forward seed/main saved report policy. Evidence /private/tmp/drf-context-handoff-red-20261021-1:2fail/1control. Generation proof extension is owned by report worker; current graph-derived priors remain separately produced.

- CTX-L6 (reproduced, repaired; combined80 green): invalid consumed proof could adopt a replacement current dossier into actual outline. Required core failure now raises; optional-only change uses verified G1 core without enrichments. Independentred/green paths recorded in handoff.
- CTX-L7 (reproduced, repaired; extended controls pending): ensemble checkpoint ignored owner/input/output identity and child wrote shared parent sidecars; schema2 proof and child-owned directory now enforced. Native red2:8fails/2controls; combined80green.
- CTX-L8 (reproduced, repaired): scenario seed reports omitted label/baseline already required in main path. Actual seed constructor/outline now sees both, combined80green.
- CTX-L9 (source-only until independent reproduction): restart cache retirement may revoke immutable historical publication and block forecast feedback; direct API owner and independent reviewer investigating temporary ledger.

## Parent closure before joint acceptance

CTX-L1–L8 pass the current affected native/route gates (162 lifecycle and154 API/report/SDK cases). Stage issues and selected limitations are detailed in coverage.md and eight stage notes. Added parent fixes cover private fork postprocessing, automatic research→derived-attempt invalidation, native produced_by_stage manifest retirement, scenario_overlay proof and saved report simulation identity. Historical report directories and immutable forecast ledger data remain available by exact report ID after cache retirement.

CTX-L9 is reproduced and repaired by the separate retirement marker contract; current actual SDK controls retain probability0.7/Brier0.18 and tamper409. Joint verification exposed RUNNING-stop-before-marker durability, now separately assigned and repaired by the API owner (affected receipt in stage-direct-api.md). The first joint result4491P/27F/34E remains red evidence: fixture isolation and known missing external-DeerFlow setup nodes must be reconciled before global acceptance. No gate/source proof was relaxed. Final replacement joint receipt/review is pending.

Final freeze4 verification closes all reproduced application defects and valid fixture regressions within the named contracts:4533passed/21explicit exclusions,0failures/errors. The21 exclusions and semantic/native/live limits are retained as coverage limits, not counted as passes or silently fixed. Final independent disposition and Gitdelivery remain pending.

Independent final review is Accepted on freeze4; no unresolved material finding in the exercised scope. Gitdelivery follows.

Delivery closed: source commit 29bf6be5b08990de58099120dbf3db9ab617b366 verified on remote main and audit branch. No unresolved material finding in exercised scope; declared unavailable/live/semantic limits remain.
