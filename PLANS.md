> Active PDF export integration: [approved plan](docs/handoff/research-pdf-export/PLANS.md) and [current handoff](docs/handoff/research-pdf-export/handoff.md), on codex/research-pdf-export from main.

# Active proposal: reflexive world simulation

The current branch proposal is [docs/handoff/reflexive-world-simulation/PLANS.md](docs/handoff/reflexive-world-simulation/PLANS.md). It includes the actor/world contracts and cross-domain acceptance scenarios. Status: independent review passed; awaiting user plan approval before application implementation. The completed earlier main-branch plan is preserved below.

---

# Main-branch fixes and official quantitative-data integration

**Date:** 2026-10-12 Asia/Shanghai
**Status:** Complete on main. The user approved all slices on 2026-10-12 Asia/Shanghai; implementation, offline acceptance and scoped independent review are delivered. See the continuity and final-verification records for exact commits and limits.
**Source/workspace:** Current `main` at c20ec60 plus the recorded existing data-MCP foundation. Finharness branches are excluded.
**Continuity:** `docs/handoff/main-quantitative-integration-20261012/handoff.md`.

## Objective and acceptance

Fix the actor-roster digest and dossier-translation envelope mismatches with regressions. Continue the existing six-provider data-MCP foundation so official observations become quantitative evidence actually queried by research agents, persisted/cited through the workflow, and visualized in both research and forecast reports. Preserve unrelated local changes and existing saved runs.

The authoritative prior interface design is `docs/handoff/data-sources-mcp/design.md`. Existing MCP hub, catalog, setup and renderer code will be reused after inspection rather than duplicated. Provider source studies will refine native request/response mappings; any required interface change must be recorded before dependent implementation.

## Ordered delivery slices

1. **Two independent bug fixes.** Match actor-context's incoming roster digest to the real producer/parent recipe while retaining duplicate, identity and tamper checks. Consume the ordinary Axios/backend envelope once in dossier translation and preserve cache/version/poll behavior. Capture meaningful failing regressions before patches and passing relevant suites after them.
2. **Complete the official-data API over the six supplied MCPs.** Add the missing `deerflow_bridge/data_sources.py` normalization/persistence layer on the existing `data_mcp.py` hub and `data_catalog.py`. Cover FRED, BLS, BIS, IMF, World Bank Data360 and the curated US-government modules using their actual native tools. Keep the existing documented FRED CSV fallback explicit in provenance. Normalize dates, finite values/missing observations, units, frequency, geography, seasonal adjustment, source URL, retrieval/revision/vintage information and publisher-projection flags. Bound time windows, pages, payloads, concurrency, retries and caches. Missing keys/builds or failed sources produce explicit unavailable/partial results, without invented data or a failed unrelated research phase.
3. **Connect quantitative planning and retrieval to both research engines.** V3 plans data needs, prefetches a bounded relevant baseline, exposes `data_search`/`data_get` alongside web tools, and registers actual returned datasets in the source ledger. Preserve one stable tools object per enabled run and the old tool list when disabled. KIQ evidence, gap analysis, synthesis/digest and source finalization consume the stored data. Legacy gets bounded wrapper tools, tool/skill registration, and the same persisted/citation contract. Resume reuses the bound dataset generation instead of silently refetching/revising its evidence.
4. **Deliver data-backed report exhibits end to end.** Write `data/datasets.json` plus canonical series JSON/CSV before charting. Integrate the existing deterministic data renderer with dossier finalization before citation/quality sealing. Pass a bounded `official_data` pack through normal, manual and ensemble report entrypoints, then through ReportAgent and ReportVisualizer. Embed manifest-backed historical series/comparison charts and source captions beside the argument. Show gaps, actual units and historical/publisher-projection boundaries; add forecast thresholds only from validated structured anchors. Confirm assets survive report API/UI and demo export paths. Disabled/unavailable sources retain explicit degradation and use existing report behavior.
5. **Useful downstream quantitative context.** Make available public historical snapshots usable by ontology/graph and simulation context without granting actors denied/private information or turning publisher projections into observations. Permit structured `data_anchor` metadata only for a known stored series, exact period, transform, units and comparator. Add strictly eligible, idempotent data-based resolution to the existing monitor only where a published matching observation establishes the outcome; otherwise leave it pending/manual with a reason. Do not activate schedules, mutate existing runs, or automatically alter forecast probabilities from simulation/data availability.
6. **Skills, operations and documentation.** Complete the existing project `data-sources` skill entrypoint and update `data-visuals` only to describe implemented behavior. Ensure every bare-import bridge module and both skills are deployed by all supported setup/sync paths. Reuse existing source setup/config controls, document defaults/key requirements/degradation in English and Mandarin, and preserve the vendor licenses and unmodified source trees. No new overlapping global skill or automation is planned.

## Shared artifact/identity contract

- Series identities use the existing `<provider>:<native>` grammar and explicit transform identity. Stored values, not model-transcribed numerals, are authoritative for tables, charts and anchors.
- `data/datasets.json` is the versioned manifest described in the prior design. It binds each safe relative JSON/CSV path and its series/provenance/units/time metadata. New identity/hash fields needed for reuse must be frozen before consumers are implemented.
- The source ledger allocates positional `[S#]` references. Dataset pages are stored as fetched source material; returned query results alone are not fetched quantitative support. Citation remapping must keep dataset/table/chart references synchronized through finalization and translation.
- `official_data={schema_version:1,series:[...]}` is the bounded research-to-report carrier, containing at most twelve series and the newest two hundred forty normalized observations per series, with explicit units and projection status. Main REPORT, manual report API and seed reports must pass the same contract.
- Artifact publication is ordered: source/series persistence → manifest → data-backed report/chart assembly → existing citation/quality/audit sealing. No post-seal numeric/figure mutation or reread of changing external data is allowed as a shortcut.
- Official-data availability is not authorization to weaken actor-knowledge/visibility policy, publication gates, numeric integrity, or the diagnostic-only simulation policy.

## Verification gates

| Gate | Required evidence |
|---|---|
| Bug regressions | Red/green tests reaching actual producer/context and component/API consumption; valid controls plus tamper/stale/error cases |
| Provider adapters | Fake stdio MCP transport and real handler-shaped fixtures for every provider; malformed results, missing values, dates/units, pagination, projections and unavailable sources |
| Research consumer | A controlled question goes plan → data tool → stored source → KIQ/digest → cited dossier, including enabled, disabled, partial-failure and resumed cases |
| Report consumer | The same stored series reaches normal/manual/ensemble report construction, renders a genuine chart, appears in the manifest and survives report/API/export handling |
| Visualization | Render fixture history, gaps, comparisons and publisher projections; visually inspect PNG output and verify cited data/units/thresholds against canonical observations |
| Downstream | Exact-period anchor validation and idempotent resolution; ambiguous units/unpublished periods remain pending/manual; actor-denial policy remains intact |
| Final acceptance | Relevant backend/frontend suites, builds/static/config checks, reviewed source hashes, independent producer-to-consumer review, and owned-change/baseline reconciliation |

Application tests use the existing provisioned environments with explicit isolation before app imports. No live LLM runs, saved-run resume, credential changes, global identity-path changes, service restart or new scheduler activation is part of acceptance. Limited live public-data MCP probes may be used separately to verify actual transport/provider compatibility; their results will be distinguished from deterministic test proof, and unavailable keyed sources will remain explicitly unverified.

## Ownership, preservation and stopping condition

The two bug workers have disjoint source/test ownership. Data implementation ownership is assigned only after plan approval and shared interfaces are frozen. Existing unrelated deletions, root handoff, .zcodeignore, prior study artifacts and other unfinished work remain untouched. Modified pre-existing foundation hunks are preserved and changes are committed by explicit ownership, never by broad staging.

The task is complete when both fixes have regression proof and the approved quantitative-data path demonstrably reaches research and forecast deliverables, with genuine charts, citations/provenance, compatibility/degradation, relevant checks and independent review. Optional source credentials, live-model behavior and remote publication remain separate evidence limits. GitHub previously rejected configured authentication; no repeated push with unchanged credentials is planned.
