> Final status note: The final native producer and fixture closures below supersede the earlier pending dependency; all owned production source is frozen.

# Reporting remedy audit

Status: Owned implementation complete and frozen; native-source acceptance is now passing. Initial scope was read-only review of slices 1 (F1), 2 (A2/A3 spine side), 7 (F6), and 8 (A1/F7), based on delivered commit `5b9b9215`. After confirmed findings, the coordinator assigned `forecast_extractor.py`, `forecast_tournament.py`, `test_first_ten_prior_updates.py`, `test_first_ten_market_equivalence.py`, and the narrow market fixtures in `test_target_pipeline.py` / `test_target_report_api.py`. The final scope extension authorized only `_pm_normalize_market` in `deerflow_bridge/deerflow_research.py`, to preserve native settlement descriptions. The coordinator retains report rendering, final publication guards, and `test_target_report.py`. The coordinator verified that all 537 initial delivered source files matched their manifest.

The review traces ordinary defaults and explicit target-first admission through production, persistence, report/brief/journal/API/UI consumption, rollback, and simulation separation. Existing test definitions and historical receipts are distinguished from fresh bounded execution. No deployment files, saved runs, provider transports, services, scheduler, main reference, or feedback resolver internals are changed or exercised.

## Plan and acceptance

1. Reconcile the supplied first-ten requirements with the admitted target-first contracts and current sources.
2. Locate real producer and final-consumer paths, including pinned policies and integrity controls.
3. Characterize only uncovered concrete edge cases with the existing guarded runner; do not repeat the coordinator's baseline suite.
4. Record a disposition and exact source/test references for each slice, concrete reproduction if any, and remaining empirical gates.

## Findings

**RPT-1, P1, confirmed: the default pre-prose critique invalidates A2's frozen prior/posterior ledger.** `report_agent.py:5956-5980` calls `self_critique_forecast` after the new prior-aware spine returns. `forecast_extractor.py:5923-5929` replaces the scenarios with normalized critique rows but leaves the top-level `scenario_updates` untouched; normalization also drops each scenario's `prior`. The real `_derive_and_pin_forecast_spine` call in the executable characterization persists 50/50 probabilities with a stale 60/40 ledger and no per-scenario priors. Re-running its own `validate_prior_posterior_updates` rejects that persisted result. These controls are default-on (`config.py:174,181,664`). A2 is therefore partial on the ordinary active route, despite helper-level prior tests passing. The target-first renderer avoids this critique path and retains its assessment ledger. Recommended bounded fix: keep prior-aware updates consistent through every post-spine probability mutation, with scenario-identity preservation or rejection of unaccounted changes, and validate before pinning/persistence. Do not synthesize an evidence rationale from nothing.

**RPT-2, P2, source-confirmed: no requested estimator table reaches the report/bridge renderer.** `forecast_tournament.py:105-174` creates lanes, `report_agent.py:3174-3177,3195,6287` attaches them to forecast JSON, and the API returns that JSON. However, `target_report.py:304-326` renders only scenario divergence, target summaries, sensitivity, signposts and decision budget. No report/brief/frontend renderer reads `estimators`; searching those consumers finds only producer/persistence/audit references. The default report can pay for the three shadow calls yet readers cannot see the lane results in the requested table. This is a concrete missing consumer, not a request for a new architecture.

**Coordinator repair review:** The new `api/research.py:_preflight_existing_pipeline` and `target_pipeline.py:preflight_saved_target` check completed research receipts before skipping obsolete research prerequisites, retain normal preflight for incomplete research/legacy runs, preserve decision-provider readiness for fresh LLM paths, and reuse sealed completed paths without re-opening a provider. Source review found no actionable defect. Independent guarded execution passed all 12 `test_target_reuse_preflight.py` cases, including the real HTTP resume/continue/fork consumers, no-dispatch tampering controls, incomplete research, LLM readiness and exact legacy arguments.

## Evidence and remaining work

The supplied request, both first-ten continuity files, and the target-first architecture, plan, contracts, acceptance, and verification documents were read. The source defaults retain legacy admission unless `forecast_authority=target-first-v1` is explicitly selected. Target-specific behavior must therefore be described separately from ordinary default behavior.

Fresh bounded evidence: `/private/tmp/drf-first-ten-report-audit-20261028-03/junit.xml` records **13 passes** in 4.75 seconds: 12 independent API preflight repair checks plus the report's real-flow defect characterization. Runs `01` and `02` stopped at doctest log-output matching; they were harness-formatting failures, not application failures. Run `03` suppresses only the logger's informational output and confirms the actual persisted values and validation error. No broad baseline suite was repeated.

## Slice dispositions and end-to-end mapping

| Slice | Disposition | Actual flow, rollback, and acceptance boundary |
|---|---|---|
| 1 / F1 | Implemented backend and rendered-document behavior | `report_agent._apply_publish_gate` classifies low coverage/spread as disclosures and leaves quote/probability/byte integrity hard. `_require_final_publish_audit` enforces the distinction. The final `forecast.json`, `final_audit.json`, signed Quality notes, `publication_status`, and immutable journal `publication` carry grade/disclosures. `exec_brief._quality_annotations`, `_honesty_line`, `_render_brief`, and `_render_digest` consume them. The report API withholds unpublishable artifacts; `ForecastReport.vue` renders the audited Markdown containing Quality notes. The demo exporter exports that audited Markdown, although its compact `_publication_summary` does not itself repeat grade. `REPORT_PUBLISH_GATE_MODE=fail` restores strict epistemic refusal. Exact acceptance: `test_publish_gate_grades.py::test_low_coverage_and_spread_publish_with_disclosures_and_journal`, `::test_nonverbatim_citation_remains_hard_in_grade_mode`, `::test_grade_quantitative_retention_cannot_bypass_final_integrity`; bilingual/legacy byte fixtures are in `test_exec_brief_quality.py`. These were inspected, not redundantly re-executed by this owner. |
| 2 / A2, spine side of A3 | A2 was partial; RPT-1 repair implemented and focused checks passing. Typed route is equivalent. | Ordinary `actors.forecast_inputs_block` / `research_prior_from_actors` feed the prior into the real `_derive_and_pin_forecast_spine` call; `derive_forecast_spine` validates the update ledger and persists per-scenario priors. The default critique used to invalidate it. New prior-aware critique and pre-mortem preserve scenario/settlement identity, require model-supplied reasons for new moves, preserve precision, and rebind the ledger. `REPORT_SPINE_RESEARCH_PRIOR=false` generates no new prior contract and keeps the prior-free critique path; an already admitted contract is not silently discarded. Target-first uses the frozen `forecast_case.assessments` and renders its update ledger directly, without a report probability model. A3's world seed is another owner's scope; reviewed documentation and `test_world_state_seed_prior.py` provide its mapping, not fresh execution here. |
| 7 / F6 | Equivalent typed-case architecture, with G3-EXACT admission repair | `target_pipeline` persists/seals the typed case and evidence; `target_report.build_target_report` calls `derive_binaries_from_tree`, preserves declared probabilities, derives partition masses only when provable, requires driver-specific settlement, and skips legacy quota/contrarian rules. Existing `test_target_estimators_owner.py` covers six predicates, explicit partition membership, precision, official anchors and unsupported driver inheritance. The ordinary route remains prose extraction; explicit target-first authority uses the typed renderer regardless of ambient prose rollback flags, preserving immutable run authority. `FORECAST_BINARIES_SOURCE=prose` governs the optional generic extractor hook; switching an admitted typed run into prose is deliberately not a rollback. `forecast_authority` is the route rollback for new runs. G3-EXACT previously trusted a market ID; the repair now admits only supported natural retained source terms, records unsupported/rejected equivalence, and uses the case's valid named-source target settlement without a market anchor. |
| 8 / A1+F7 | Core estimator/policy behavior implemented; consumer gaps owned by coordinator/feedback owner | Admission pins `aggregation_policy_v1` in pipeline options. Default identity weights are authority 1, all shadows 0; report constructors reject non-identity promotion. `target_pipeline` freezes `target_evidence.json` and `target_estimators.json` before simulation, binds digests, and replay verifies case/policy/proposition joins. Tournament calls are bounded to three injected gateway calls, with explicit unavailable/error lanes; `REPORT_TOURNAMENT=false` creates authority only. Saved admitted lanes survive later flag drift. The report JSON/API and journal retain lanes; raw model-declared market contracts can no longer bypass admitted tree anchors. The requested renderer table was absent (RPT-2, coordinator fixing). No `estimators` consumer was found in `forward_cohort.py`, `forecast_track_record.py`, or `forecast_feedback.py`; per-lane scoring needs confirmation by its owner, and is not claimed implemented here. |

RW-11: the ordinary route excludes simulation from spine probability prompts; target-first renders frozen case rows and attaches zero-weight diagnostics. `test_target_estimators_owner.py::test_tournament_bounded_diverse_injected_gateway_and_shadow_invariance` proves authority numbers and non-simulation lanes unchanged. The earlier `test_target_report.py::test_decision_budget_exhaustion_is_visible_without_probability_effect` checked only scenario/binary equality and explicitly allowed simulation budget state to alter forecast quality; this is weaker than the requested whole-forecast exception set. The coordinator is repairing this reporting boundary. No claim is made that unchanged probabilities alone establish strict RW-11.

## Repair decisions and current evidence

RPT-1: `_prior_critique_rows` refuses implicit floors/rounding, altered settlement, changed scenario sets, incomplete distributions, and increased peak confidence. `_rebind_prior_updates` validates the input ledger, requires new supplied reasons for every changed probability, retains prior reasons as history, and validates the revised ledger. Invalid model revisions leave the original forecast unchanged. Optional pre-mortem also requires actual string reasons. Final publication should separately validate the admitted ledger to reject stale or independently altered saved artifacts; the coordinator owns that hook.

G3-EXACT: the first attempted repair required a custom canonical description. The coordinator correctly rejected that as an impractical producer requirement. It was replaced with a bounded natural-language parser for annual monetary thresholds with explicit first-release publisher/URL and deadline. The parser must consume the entire retained source description; unsupported exceptions or missing terms never establish exactness. Known parsed contradictions produce `market_equivalence.status=rejected`; missing/unsupported proof produces `unavailable`. Both paths remove market authority and use the already valid target named-source contract. Driver nodes without their own settlement cannot inherit the target source. Supported source terms preserve the source description verbatim in the anchor and use `deterministic-tree-settlement-v1`, never a fabricated semantic-review marker. The tournament requires that admitted anchor and matching snapshot terms, never a raw declared contract.

Evidence sequence:

- `/private/tmp/drf-first-ten-prior-red-20261028-01/junit.xml`: 8 failed, 2 passed before repair; the real default persistence path lost priors and retained stale posteriors.
- `/private/tmp/drf-first-ten-prior-green-20261028-01/junit.xml`: 10 passed after the initial prior repair.
- `/private/tmp/drf-first-ten-market-red-20261028-01/junit.xml`: 14 failed, 4 passed before market admission repair.
- `/private/tmp/drf-first-ten-extractor-regression-20261028-01/junit.xml`: 147 passed, one old title-only exact-positive fixture failed as expected; fixture migration is coordinator-owned.
- `/private/tmp/drf-first-ten-owned-final-20261028-01/junit.xml`: 32 passes on the initial strict repair, including actual exact-anchor report publication and the journal. Superseded for market fallback semantics by the next run.
- `/private/tmp/drf-first-ten-native-exact-20261028-01/junit.xml`: 32 passes and one genuine producer failure on the revised natural-source/fallback behavior. Actual `_pm_snapshot` invokes the real normalizer, which discards `description`; the test fails before admission. A successful native-source check requires producer retention, not injecting a fabricated description after normalization. The coordinator was notified; those producer files are outside this owner's scope.
- Ruff F/E9 passed the owned implementation/tests before the final source-retention integration. Repeat the focused static check after final edits; no broad suite is required.

Empirical boundaries: these are controlled synthetic source fixtures, not live Polymarket availability or semantic coverage of arbitrary market prose. Provider realism, complete natural-language settlement coverage, live transport, scheduler activation, paid studies and prospective calibration remain separate. Unsupported optional markets leave forecast authority with its named source rather than inventing exactness.

## Final owned-source freeze

`/private/tmp/drf-first-ten-report-freeze-20261028-01/junit.xml` records **43 passes, 1 failure, 5.49 seconds**. It includes this report's repaired real-flow doctest, all owned prior/market tests, the two pipeline market cases, four API replay cases, and the parent's four natural-market health cases. The sole failure is `test_native_gamma_snapshot_retains_natural_source_terms`: real `_pm_snapshot` invokes `_pm_normalize_market`, which drops the raw provider description. The remaining acceptance is a producer dependency, not a reason to loosen the equivalence matcher. The coordinator was notified with the exact correction: retain nonempty string `raw['description']` verbatim, without synthesis, in the bridge and backend market normalizers, then rerun that single test before the composed gate. No producer edit was made outside the assigned scope.

The completed guard receipt reports shutdown complete, preserved identity variables, no source drift among recorded inputs, no children, one blocked external read and no recorded socket/process attempts. Ruff F/E9 and `git diff --check` pass for all six owned implementation/test files. No broad suite, live provider, service, scheduler, deployment, main mutation, commit or push was performed by this worker; the coordinator owns integration and delivery.

| Frozen file | SHA-256 |
|---|---|
| `backend/app/services/forecast_extractor.py` | `1f9290509ec590050acfeb753d23115a5b25871723e6756016645cdb80d8a123` |
| `backend/app/services/forecast_tournament.py` | `99730b9245c23714f149fa359987efb0c97de48baa9418c7887f6015dccb5c0c` |
| `backend/tests/test_first_ten_prior_updates.py` | `538faf9dfcc16bc025b842785e38cd6b87815971b3a85b63c596992a131ee579` |
| `backend/tests/test_first_ten_market_equivalence.py` | `319c4f5683584d3c08f8e179778e98d8a625668ce38a4320c396e7bc9a8b2176` |
| `backend/tests/test_target_pipeline.py` | `56f69ca2268656471e59d7b7a362639af6a0883fbaa649e1e44a60e9133330b4` |
| `backend/tests/test_target_report_api.py` | `74abd9335b9dbed120176df7771c95fba186452572bd89f683fdf96879f34acc` |

The owned fixture edits preserve transport health and replay assertions, while title-only markets now explicitly remain unanchored with a valid named-source fallback. Full exact-source fixtures use retained natural settlement prose rather than a helper-manufactured provider description.

### Native producer closure and superseding freeze

The coordinator authorized the five-line bridge normalization change. `_pm_normalize_market` now retains an actual nonempty string `raw['description']` verbatim, including surrounding whitespace. Missing, blank and non-string values are omitted, never converted or synthesized. No backend normalizer or other producer was edited by this worker.

`/private/tmp/drf-first-ten-native-closure-20261028-01/junit.xml` records **38 passed, 0 failed, 2.26 seconds** on the owned prior/market modules. The native test uses a Gamma-shaped synthetic transport response containing natural settlement prose. Actual `_pm_snapshot` calls the real normalizer; its output then passes the typed report audit, deterministic exact admission, report publication seal, immutable journal and market estimator. The description is compared byte-for-byte at the collector, anchor and journal; no description is added after normalization. This closes the one failure in the preceding 43-pass gate. Five negative normalization cases establish that missing/invalid provider descriptions remain absent.

The final guard completed with exit 0, shutdown complete, preserved identity variables, no recorded source drift, no children, and no recorded blocked/socket/process events. These are controlled transport fixtures, not live network or provider confirmation. Ruff F/E9 and diff checks pass on all seven owned implementation/test files.

The prior-publication hook was source-reviewed independently: pre-pin validation calls the existing contract validator; final audit validates a detached copy, rejects any mutation needed to restore missing metadata, and routes invalid ledgers through the unconditional hard-integrity issue list. It therefore cannot repair the publication while auditing it and does not depend on grade/fail mode. No missing hook or actionable source finding remains.

Independent hook execution also passed: `/private/tmp/drf-first-ten-prior-publication-review-20261028-01/junit.xml` records **2 passed in 1.71 seconds** on the coordinator's valid/stale publication cases. Reviewed `report_agent.py` SHA-256: `97502eff845b6f7acb597059ab393b7bd5b169ca3f109b73fe42c7e96cc27fb1`; test SHA-256: `7ed13c804b0a90cff71020f18683ad64722f5405016da4ccfc836f72db025c51`.

Two hashes supersede the preceding freeze; all other owned hashes are unchanged:

| File | Final SHA-256 |
|---|---|
| `deerflow_bridge/deerflow_research.py` | `844ac35d58d4fe43b5f00c0947c20b7373dc25217b175a0989a4b3b97136bdb8` |
| `backend/tests/test_first_ten_market_equivalence.py` | `4e7d369c0b00df6986203dde4bf6678e0076836adc0f326cb8d29d457daf4d8f` |

### Final broad-gate fixture reconciliation

The coordinator's 159-module frozen gate reported 5,300 passes, four failures and two skips. Two failures were assigned here: the exact-market positive fixtures in `test_target_estimators_owner.py::test_tree_exact_market_adapts_stored_snapshot_without_changing_p` and `test_target_feedback_extensions.py::test_typed_market_producer_anchor_reaches_real_journal_and_score`. Their old title-only snapshots correctly no longer establish exactness. Only these two functions were edited: explicit synthetic natural source descriptions now supply entity, annual period, comparator, threshold, units, first-release publisher/URL and the March 30, 2028 deadline. The journal outcome date now follows that deadline. Existing exact-anchor, unchanged-probability, accepted-outcome and Brier-score assertions remain, with additional source-byte round-trip assertions. The absent-snapshot assertion now verifies explicit unavailable equivalence and named-source fallback, matching the approved optional-market behavior.

`/private/tmp/drf-first-ten-market-fixtures-final-20261028-01/junit.xml` records **88 passed in 2.42 seconds** across both full focused modules. Ruff F/E9 and diff checks pass. Application source remains frozen: the extractor, tournament and bridge SHA-256 values still exactly match the final source freeze above. The other two broad-gate failures remain with the coordinator; this worker makes no claim about their closure.

| Migrated test file | Final SHA-256 |
|---|---|
| `backend/tests/test_target_estimators_owner.py` | `16c4cb6a17eef208926296b83898c981e8d4d7e9bca8b45915e158642158cf59` |
| `backend/tests/test_target_feedback_extensions.py` | `9755ffd7e26a74d473190b00e9da71648c6726cdd4382a2af794dcbad39f8456` |

## Updates

- 2026-10-28: Created the bounded audit record before any execution or implementation. The coordinator owns implementation assignments after findings.
- 2026-10-28: Reproduced the real default critique ledger defect, reviewed the API preflight repair (12 independent passes), and mapped all assigned slices to producers and final consumers.
- 2026-10-28: Implemented authorized prior and market admission repairs; rejected an initially over-restrictive custom source template, added natural retained-source parsing with explicit no-authority fallback, and retained the native producer failure rather than bypassing it.
- 2026-10-28: Froze six owned code/test files after 43 focused passes and the one documented producer dependency; recorded hashes, guard receipt, static checks and exact remaining acceptance.
- 2026-10-28: After explicit producer ownership extension, preserved native description bytes, proved the real source-to-journal and estimator path, and passed all 38 owned checks. Source-reviewed the coordinator's prior-publication guard and recorded the final seven-file freeze.
- 2026-10-28: Migrated the two specifically assigned exact-market positive fixtures after broad-gate failure review. Both focused modules pass all 88 cases; application source hashes remain unchanged.

## Executable bounded characterization

This doctest uses the real prior producer, spine generation, default critique ordering, and persisted early forecast. Only model replies and peripheral stored-context access are controlled. Explicitly set controls equal their source defaults. It writes exclusively into the guarded runner's temporary directory. Originally this yielded 50/50 with stale 60/40 updates and no priors. After RPT-1, the unreasoned critique is refused and the original 60/40 contract remains intact.

    >>> import json
    >>> from copy import deepcopy
    >>> from pathlib import Path
    >>> from app.config import Config
    >>> from app.services.report_agent import ReportAgent, ReportManager
    >>> from app.services import forecast_extractor as fe
    >>> patch = getfixture('monkeypatch')
    >>> temp = getfixture('tmp_path')
    >>> for key, value in {'REPORT_SPINE_RESEARCH_PRIOR': True, 'REPORT_FORECAST_SELF_CRITIQUE': True, 'REPORT_CRITIQUE_BEFORE_PROSE': True, 'REPORT_PREMORTEM': False, 'REPORT_SPINE_SELFCONSISTENCY_K': 1}.items():
    ...     patch.setattr(Config, key, value)
    >>> patch.setattr(ReportManager, 'REPORTS_DIR', str(temp / 'reports'))
    >>> rows = [{'name': 'Expansion', 'probability': 0.6, 'resolution_criteria': 'Revenue > 100 in 2027.'}, {'name': 'Other / status quo', 'probability': 0.4, 'resolution_criteria': 'Revenue <= 100 in 2027.'}]
    >>> updates = [{'name': r['name'], 'prior': r['probability'], 'posterior': r['probability'], 'reason': ''} for r in rows]
    >>> class Replies:
    ...     def __init__(self):
    ...         self.calls = []
    ...     def chat_json(self, **kwargs):
    ...         self.calls.append(kwargs)
    ...         if len(self.calls) == 1:
    ...             return {'headline': 'Revenue?', 'horizon': '2027-12-31', 'scenarios': deepcopy(rows), 'scenario_updates': deepcopy(updates)}
    ...         changed = deepcopy(rows)
    ...         changed[0]['probability'], changed[1]['probability'] = 0.5, 0.5
    ...         return {'scenarios': changed, 'confidence': 'medium'}
    >>> a = ReportAgent.__new__(ReportAgent)
    >>> a.actors = {'as_of_date': '2026-10-27', 'forecast_inputs': {'scenarios': deepcopy(rows)}}
    >>> a.simulation_requirement, a.output_language, a.situation_brief = 'Revenue?', 'English', ''
    >>> a.llm, a._market_pack, a._data_pack = Replies(), 'No stored markets.', ''
    >>> a._forecast_situation_brief = lambda: ''
    >>> a._temporal_horizon_date = lambda: '2027-12-31'
    >>> a._simulation_forecast_effect = lambda: 'diagnostic_only'
    >>> a._official_pack_kwargs = lambda: {}
    >>> folder = Path(ReportManager._get_report_folder('report_prior_audit'))
    >>> folder.mkdir(parents=True, exist_ok=True)
    >>> from app.services import report_agent as ra
    >>> patch.setattr(ra.logger, 'info', lambda *args, **kwargs: None)
    >>> a._derive_and_pin_forecast_spine('report_prior_audit')
    >>> issued = json.loads((folder / 'forecast.json').read_text())
    >>> (len(a.llm.calls), issued.get('critiqued', False), [r['probability'] for r in issued['scenarios']], [r['posterior'] for r in issued['scenario_updates']], [r.get('prior') for r in issued['scenarios']])
    (2, False, [0.6, 0.4], [0.6, 0.4], [0.6, 0.4])
    >>> fe.validate_prior_posterior_updates(deepcopy(issued), issued['research_prior'], issued['scenario_updates']) == issued
    True
