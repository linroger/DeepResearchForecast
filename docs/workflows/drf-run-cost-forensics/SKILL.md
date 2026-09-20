---
name: drf-run-cost-forensics
description: Reconcile DeepResearchForecast saved-run token usage, elapsed time, retries, ensemble costs, and telemetry gaps. Use for questions about expensive or slow runs and source-backed workflow cost audits; it does not execute pipeline recovery.
---

# DeepResearchForecast run cost forensics

Produce a reproducible cost/time reconciliation from saved artifacts and current source. Distinguish historical behavior from the implementation that exists now. This complements architecture research and recovery audits; it is not a general optimization checklist.

## Establish the accounting scope

Use the user's repository and requested run/date range. Read current `handoff.md`, Git status/history, and relevant runtime configuration definitions for context, unless the user requests an independent calculation from raw artifacts; in that case establish the numbers before consulting prior conclusions. Preserve unrelated dirty files. Locate the current authority rather than assuming a redesign is live: the historical implementation uses `PipelineOrchestrator` and `pipeline_state.json`; verify this against source.

State whether the denominator is one attempt, all attempts of a pipeline, or that pipeline plus scenario forks/ensemble children. Identify IDs and artifact lineage before summing anything. Enumerate run creation dates so old measurements cannot be mistaken for a current benchmark.

This playbook is read-only with respect to runtime: do not launch/resume/cancel a pipeline, probe a paid provider, alter settings, or delete artifacts to obtain measurements. If a requested conclusion requires a live run, finish the saved-artifact analysis and label that remaining measurement explicitly. Do not inspect credentials or include prompts, private report text, or raw provider payloads in evidence exports.

## Find and reconcile the records

Typical locations, to verify rather than treat as fixed schemas:

- `backend/uploads/pipelines/<id>/pipeline_state.json`: stage timestamps, options, child IDs, handoff/artifact references.
- Sibling `run_telemetry.json`: meter totals, per-stage/model records, previous/cumulative attempts, child summaries.
- Sibling `telemetry.json`: compact stage tokens and wall time.
- `handoff/ensemble_forecast.json` or an ensemble checkpoint: extra simulation/report lineage.
- `backend/uploads/reports/<id>/telemetry.json`: report-local accounting; sections may be absent or incomplete under concurrency.
- Simulation `sim_llm_telemetry.json`, `llm_health.json`, checkpoints, and run summaries: token snapshots versus call/error counters.

Read selected aggregate keys rather than dumping these files. Preserve source path, JSON key path, file hash, timestamp, units, and accounting scope for each number used.

Apply these rules:

1. A synthetic research aggregate may already be included in the parent total. Do not add `options.research_telemetry` to that total again.
2. A report-local total can overlap the parent's REPORT stage. Reconcile differences; do not add both. Extra report IDs may be additive only after verifying distinct lineage and whether a parent cumulative total already includes them.
3. Do not sum `total`, `previous_attempt`, and `cumulative_total` indiscriminately. Read the producer's current merge semantics. Repeated snapshots of one attempt are not separate spending.
4. Same-request cumulative snapshots can grow. Count positive deltas once, not every full snapshot and not only the first occurrence. Record gaps where the saved data cannot support exact reconciliation.
5. Zero recorded tokens with nonzero calls is a telemetry gap. Use “reconciled recorded coverage” when request-level history cannot rule out upstream double counting. Missing measurements and aggregate overcount can coexist; label an actual-usage lower bound only when the evidence supports that claim. Missing data is not zero cost.
6. Token volume, cache-read/cache-write volume, estimated API cost, actual charges, and subscription capacity are distinct. Do not assume a provider's API pricing describes an OAuth/subscription route. A saved `cost_estimated: false` flag is not proof of actual billing.
7. Compute wall time from applicable start/end timestamps. Separate main-stage intervals from ensemble/recovery/other intervals. Request-latency sums and concurrent timeouts are not automatically critical-path time. Missing timezone or inconsistent timestamp semantics must be called out rather than silently repaired.
8. Provider/model/call-site coverage changes over time. When recommendations are requested, verify failed-attempt capture, thread context propagation, subprocess imports, and budget gates in current source before recommending that an old missing feature be implemented. A simple accounting question does not require a broad implementation audit.

## Deliver the useful result

Return a compact stage table, the reconciled recorded coverage or evidence-supported actual-usage bound, unclassified usage/time, the exact non-overlap reasoning for child costs, and the current-source status of each historical bottleneck. Recommend only changes supported by a current mechanism or an explicitly stated measurement hypothesis.

For each recommendation, give a source anchor, expected cost mechanism, constraint that must survive, and a falsifiable acceptance check. Examples of constraints include actor/source provenance, exact artifact seals, uninterrupted-versus-resumed simulation equivalence, and no duplicate launch intent. Do not promise speedup percentages without comparative measurements.

When an artifact is requested, save a small sanitized evidence JSON containing selected aggregates and hashes alongside the report. Verify arithmetic independently and check that cited source paths and line numbers exist. Keep the requested report as the primary deliverable.

Stop when the requested accounting scope is reconciled as far as the saved evidence permits, remaining uncertainty is explicit, current fixes have been separated from open work, and the requested artifact is validated. Missing historical counters are an honest result, not a reason to launch a replacement run.
