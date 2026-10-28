# First ten remedies: implementation reconciliation

Status: The user requests implementation of the supplied design. Reuse the delivered implementation at 5b9b9215; verify it against the supplied first-ten acceptance criteria and repair concrete missing behavior. The previous implementation plan and acceptance records are under ../target-first-forecast/. The new plan records reconciliation, not a second architecture.

1. Preserve the deployment checkout and saved runs; use this managed isolated branch based on the delivered implementation. The supplied main f773f61 is stale relative to the existing provenance and target-first implementation; rebuilding from it would discard those dependencies.
2. Map all ten requested slices to their actual producers, persistent artifacts, consumers, rollback controls and tests. Delegate disjoint reporting, research/mechanism, and feedback/input reviews. Confirm completed work before making changes.
3. Repair reproduced discrepancies within each owner's bounded scope; each repair needs a failing scenario, passing corrected scenario, rollback controls and independent review. Do not change phase-2 architecture without its separately required approval.
4. Run guarded offline producer-to-publication and applicable compatibility checks on frozen source. Reuse existing guarded runner; no provider/network probes, scheduler activation, deployment or saved-run mutation. Paid and empirical gates remain explicit.
5. Record the ten-slice matrix, residual issues, exact test evidence and preservation check. Commit and push only this branch's changes to the existing active remote; do not advance main or deploy without tested integration.

Success is a source-backed disposition of every requested slice, closure of any reproduced implementation defects, and durable evidence distinguishing delivered source from live validation. Existing target-first mode remains opt-in; simulation/structural weights stay zero.
