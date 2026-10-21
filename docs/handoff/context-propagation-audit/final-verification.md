# Context propagation audit: verification and delivery

Status: Final offline gate and independent review accepted; Git delivery pending.

The audit starts from main `3cd421a3b89f475d54db66421eaa6a1684c3e86f` and uses the isolated `codex/context-propagation-audit` branch. The primary checkout remains on its existing branch; its urgent GraphPanel import repair is separately recorded in `../frontend-overlay-repair/`.

## Source and run identity

- Current source freeze: [source-freeze.json](source-freeze.json), generation4, 502 Python files. All compile without execution and match the current worktree and mirrored source.
- Final candidate: `/private/tmp/drf-context-joint-fourth-2tetzaqp/`, with exact command in `invocation.json` and guarded results under `evidence/`.
- Selection: [verification-selection.json](verification-selection.json), 125 test modules, exact child scripts and named exclusions. Pytest node IDs are relative to backend; `--deselect=tests/...` was verified by a guarded one-node collection diagnostic.
- Unchanged runner SHA: `8c8bb8f6c0e4e5decee8f167603a4eb47711ec562e028d19f9d3d6bee1741815`.

## Retained phases and interpretation

Counts below overlap and must not be added into a unique total. Original receipts remain immutable.

| Phase | Result | Interpretation |
|---|---|---|
| **Final freeze4, 2tetzaqp** | **4533 passed,21 named deselections,0 failures/errors in331.35s** | Parent and17children exit0/shutdown/identity/no drift;502worktree/mirror source hashes match. [Machine-readable verification](verification.json). |
| First joint, ip8sensq | 4491 passed,27 failed,34 setup errors,2 signal deselections | Meaningful restart-order finding plus invalid/poorly isolated older fixtures and19 missing-vendor setup nodes; retained in joint-first-red.json. |
| Second joint, zrf9t4ap | 4533 passed,0 assertion failures,19 known-vendor setup errors,2 signal deselections | All exercised repair/fixture cases pass, but wrong node-prefix exclusion flags prevent an overall green verdict. |
| Third joint, npw99tgw | 4532 passed,1 fixture-precondition failure,21 named deselections | Actor1 was sampled out before the asserted hold; expectation marker reached owner. Native artifacts/reviewer support a deterministic fixture correction, with original assertion retained. |
| Feedback fixture correction | 307 affected cases plus six seed controls pass | Only target cadence/precondition changed; three original seeds reproduce missing activation, all six corrected seeds retain exact owner response/privacy assertions. Production unchanged. |
| Parent lifecycle | 162 passed | Actual reconstruction/fork/reload/rollback/seed/ensemble/retired and foreign-report controls. |
| Original Oddsense + feedback workflow | 11 passed | Actual source-shaped transport/engine/ledger/promotion/report audit/API/export, resolution/restart and next-report frozen track record. External intelligence is scripted. |
| API RUNNING/restart/SDK | 51 passed | Retirement is durable before stop/cleanup/spawn; retained historical audit/ledger can still resolve and score; tamper rejects. |
| Official publication fixtures | 46 passed | Valid canonical IDs, complete storage isolation, genuine missing-proof carrier controls and native owner state; original assertions retained. |
| Legacy interrupted pending owner | 8 passed | Declared fake dead-PID liveness scripted only at that OS boundary; current-PID control remains native. Baseline fails identically without fixture correction. |
| Independent final main/sidecar probe | 3 passed | Correctly bound/absent controls reach real outline; late sidecar rejects before model construction. No wrong-generation adoption reproduced and no production patch made. |

## Exclusions and limits

Exactly19 named native configuration cases require the absent optional `deer-flow` checkout; the whole legacy-official suite is not excluded. Exactly2 named child OS self-signal cases conflict with the unchanged guard. These21 cases are unavailable/unexecuted coverage, not passes. No vendor schema substitute, dependency installation or new guard permission was introduced.

The guard is CPython audit containment, not an OS sandbox. Native OASIS/platform/font imports can attempt denied socket construction, subprocess discovery and external reads. MCP cleanup can attempt denied process-group signals. Record these as attempts; do not claim zero attempts or successful provider access. All17registered child receipts are completed/exit0/shutdown/identity/no drift. Final parent denials are9Popen,20externalreads,1socket and2killpg; known font/platform discovery is attributed in stage notes, while exact native callers for every unmatched probe are not established. No zero-attempt claim is made.

The evidence proves the exercised deterministic field, provenance, access, restart and publication contracts. It does not measure live provider reliability, paid model behavior, forecast accuracy, semantic translation quality, native PDF binaries, deployment, selected-period dashboard behavior or universal context completeness. Bounded prompt windows/projections and their documented omissions remain. Fresh world-v1 causal pins preserve unpinned legacy behavior and do not promote that opt-in engine by default. Main may reject a late changed binding while a core-verified manual path degrades; this is fail-closed compatibility behavior, not a completed report or proved adoption.

## Review and continuity

[Coverage](coverage.md), [issues](issues.md), [independent review](review.md) and eight stage notes retain producer → artifact → actual consumer maps, exact read ranges, source hashes, reds/greens and residual limits. [Handoff](handoff.md) is the current continuity authority. [Preservation](preservation-final.json) records the primary exception and concurrent peer drift without attributing peer changes to this audit. [Workflow packaging](workflow-packaging.json) binds the two narrow existing-skill reference additions; no new top-level skill, permanent agent, automation or global-memory write occurred.

The completed freeze4 receipt is accepted. Independent final review is Accepted. Owned-path commit/push remain pending. Do not infer running-service deployment from a future Git delivery.
