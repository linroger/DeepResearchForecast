# Slice 4 feedback and input audit

Date: 2026-10-28. Initial audit scope was this report only; the coordinator subsequently assigned G1-STATUS and G1-PROBE repair as recorded below. Reviewed baseline: `5b9b9215`; the coordinator separately verified all 537 delivery-manifest files. Deployment, saved runs, services, issue 10 and scheduling remain untouched.

## Baseline findings (retained audit history)

1. **G3-EXACT (P1): typed market contracts can label an unrelated market exact.** `derive_binaries_from_tree` selects the supplied market ID and calls `_build_market_anchor(... equivalence="exact", match_confidence=1.0, binary=row)` without comparing its settlement proposition to the typed predicate. `_build_market_anchor` generates a semantic-review marker and independent hashes itself. For an unclassified spending proposition, `audit_market_anchor_integrity` accepts those hashes; `audit_target_report` regenerates the same anchor and accepts it. The journal then accepts a terminal outcome from that market. This misses G3's exact re-match requirement at publication, and can assign another event's outcome to the forecast's Brier score. See `backend/app/services/forecast_extractor.py:4617`, `:3449`, `:4073`, `backend/app/services/target_report.py:327`, and `backend/app/services/forecast_feedback.py:529`. The controlled reproduction below deliberately substitutes a different spending threshold, year and market settlement description while retaining its declared ID. This is an admission defect, not an argument for live re-fetching or nonzero simulation weighting.

2. **G1-STATUS (P2): native collector disabled and successful-empty results lose their known state in input health.** The collector emits `status.empty_reason="disabled"` and then `_pm_publish_collection` sets `status.state="unavailable"`, `as_of=None` for zero rows. The health consumer only recognizes the label `disabled` or top-level `enabled=False`. Successful-empty responses similarly retain `successful_query_count` and `attempted_at`, but `build_inputs_health` returns early for missing snapshot time before checking verified emptiness. Both therefore render as unknown/missing_snapshot_time despite known input availability. See `deerflow_bridge/deerflow_research.py:16803`, `:16868`, and `backend/app/services/forecast_inputs_health.py:76`. Keep `as_of=None` when no price snapshot exists; record the attempt/status time separately rather than fabricating freshness.

3. **G1-PROBE (P2, source-demonstrated requirement gap): the probe does not exercise the research collector's transport.** `backend/scripts/probe_markets.py:26` uses `app.utils.prediction_markets.PolymarketClient` / `httpx`; the production research collector calls `_polymarket_get` / `urllib.request.urlopen` at `deerflow_bridge/deerflow_research.py:15961`. The two share endpoint overrides and browser user agent, but differ in HTTP implementation, proxy/TLS behavior, retry and timeout configuration. The existing probe test explicitly patches `pm.httpx.get`. Thus it establishes the backend client's path, not G1's requested exact collector path. A collector probe mode or shared transport adapter needs a controlled bridge-path regression before a later authorized live probe can answer the original failure. No assertion about current network availability is made.

## Slice disposition

| Requested behavior | Current implementation and evidence | Disposition |
|---|---|---|
| Real collector last-good cache | `deerflow_bridge/deerflow_research.py:16666-16855`; real collector tests `backend/tests/test_target_research.py:520-580` | Implemented. Query key binds full question, topics/actors, query/cap/relevance settings, model and transport. Backtests and opt-out bypass cache. Only fresh nonempty transport successes are saved. |
| Cache ownership, time and evidence | `_pm_read_cache` requires request key in envelope and payload, schema, fresh status, payload hash, bounded file size, non-symlink file, valid prices, aware nonfuture as_of and fetched_at no older than seven days. Failed refresh preserves original snapshot age and bytes. | Implemented; coordinator owns fresh baseline acceptance. A cache hash proves local integrity, not external truth. |
| Input health into forecast and brief/card | `ReportAgent._forecast_diagnostics` (`backend/app/services/report_agent.py:3158-3187`) retains native market envelope and uses stored news/official inputs; `exec_brief._inputs_health_display` (`:486-513`) and both detail/card render paths consume only forecast fields. Tests `test_target_inputs_health_probe.py`, `test_exec_brief_quality.py:274-354`. | Implemented connection; G1-STATUS remains. Provider is explicitly unknown without a receipt, rather than inferred healthy from configuration. |
| Frozen snapshot ownership | `target_pipeline.py:399-413` pins evidence digest and case hash; `api/report.py:469-482` checks owner-bound artifact, saved digest, exact carrier keys and case; `ReportAgent._init_target_report` at `:3088-3095` rejects mismatched supplied official/news inputs. Existing mutation cases `test_target_report_api.py:478-546`. | Implemented. The coordinator owns fresh pipeline/API acceptance. A valid frozen carrier does not itself prove exact market proposition equivalence. |
| Exact anchors at publication | Tree contract selects matching market ID; typed audit recomputes from sealed input. | G3-EXACT remains: input integrity and exact semantic equivalence are different checks. |
| Near resolution in its own lane | `forecast_feedback.py:308-394`, `:529-560`; monitor obtains fresh provider settlement terms at `resolution_monitor.py:829-848`; tests `test_target_feedback_extensions.py:162-231`, `:255-275`. | Implemented conservatively. Requires matching frozen/source settlement hashes, verbatim proposition and criteria, equal deadline, terminal closed/resolved state, matching probability and publication identity. True approximate proxies stay outstanding. Rollback prevents new admissions but preserves replay. |
| Named-source manual API | `forecast_feedback.py:324-452`, `backend/app/api/sdk.py` resolve-binary route; tests `test_target_feedback_extensions.py:46-146`, `:332-357`. | Implemented with exact frozen contract hash, strict boolean, publisher match, evidence URL/text/adjudicator, publication < deadline <= source publication <= retrieval <= resolution, wall-clock future check, idempotency and conflict rejection. This is explicitly human adjudication, not automated truth verification. |
| Journal/scoring authority | `forecast_feedback._binary_record`, immutable publication join, `forecast_ledger.py:251-272`, monitor committed-result readback `resolution_monitor.py:925-1000`. | Implemented. Default production calibration uses the journal. Explicit legacy/evaluation callers retain legacy scoring. Near/manual lanes remain separate. |
| Daily monitor | `config.py:299`; `resolution_autorun.py:99-147`; explicit production entrypoint `backend/run.py:41-42`; fake-clock test `test_target_inputs_health_probe.py:78-90`. | Source default is 24 hours; initial production delay is 60 seconds, then daily. Import/create_app does not activate it. Production activation remains unperformed and belongs to issue 10. |
| Frozen cohort dry-run | `backend/scripts/forward_cohort.py:18-79`; `test_forward_cohort_proposal.py:30-73`. | Implemented. Six validated fixture questions, no LLM/enrollment, frozen hash, duplicate/outcome/date rejection; actual release calendars and paid cohort remain separate gates. |

## Controlled reproductions

These historical doctests ran on the pre-repair baseline under the existing guarded runner. They assert observed faulty behavior, so a passing baseline audit probe is not a claim that the behavior is correct. They are not current regression tests: use the new test modules below after repair. Temporary collector and journal writes were confined to the runner's evidence root. The status probe uses the actual collector with a fixed clock, deterministic query list and substituted empty snapshot response; the exact-anchor probe uses actual report/audit/journal components with a synthetic stored market. No live network, model, scheduler, service, deployment or saved-run access is required.

### G1-STATUS: actual collector producer to health consumer

    >>> import json, tempfile
    >>> from pathlib import Path
    >>> from types import SimpleNamespace
    >>> import pytest
    >>> from deerflow_bridge import deerflow_research as collector
    >>> from app.services.forecast_inputs_health import build_inputs_health
    >>> clock = "2026-10-28T05:00:00+00:00"
    >>> scratch = tempfile.TemporaryDirectory(prefix="feedback-audit-")
    >>> root = Path(scratch.name)
    >>> log = SimpleNamespace(write=lambda *args, **kwargs: None)
    >>> with pytest.MonkeyPatch.context() as mp:
    ...     mp.setenv("PREDICTION_MARKETS_ENABLED", "false")
    ...     mp.setattr(collector, "_utcnow", lambda: clock)
    ...     collector._collect_prediction_markets(root, "Spending in 2027?", "# Research\n", {}, log)
    >>> disabled = json.loads((root / collector.PREDICTION_MARKETS_FILENAME).read_text())
    >>> (disabled["status"]["empty_reason"], build_inputs_health(markets=disabled, as_of=clock)["markets"])
    ('disabled', {'status': 'unknown', 'as_of': None, 'rows': 0, 'reason': 'missing_snapshot_time'})
    >>> def empty_snapshot(queries, **kwargs):
    ...     kwargs["diagnostics"].update(successful_query_count=len(queries), transport_failure_count=0)
    ...     return []
    >>> with pytest.MonkeyPatch.context() as mp:
    ...     mp.setenv("PREDICTION_MARKETS_ENABLED", "true")
    ...     mp.setenv("PREDICTION_MARKETS_CACHE", "off")
    ...     mp.setenv("PREDICTION_MARKETS_HORIZON_RETRY", "false")
    ...     mp.setattr(collector, "_utcnow", lambda: clock)
    ...     mp.setattr(collector, "_pm_backtest_policy", lambda: None)
    ...     mp.setattr(collector, "_PM_TRANSPORT_UNAVAILABLE", False)
    ...     mp.setattr(collector, "_pm_resolve_queries", lambda *args: ["spending 2027"])
    ...     mp.setattr(collector, "_pm_snapshot", empty_snapshot)
    ...     collector._collect_prediction_markets(root, "Spending in 2027?", "# Research\n", {}, log)
    >>> empty = json.loads((root / collector.PREDICTION_MARKETS_FILENAME).read_text())
    >>> (empty["status"]["successful_query_count"], empty["status"]["empty_reason"], build_inputs_health(markets=empty, as_of=clock)["markets"])
    (1, 'no_equivalent_market', {'status': 'unknown', 'as_of': None, 'rows': 0, 'reason': 'missing_snapshot_time'})

### G3-EXACT: wrong market passes both audits and reaches score

    >>> from app.services.target_report import build_target_report, audit_target_report
    >>> from app.services.forecast_extractor import audit_market_anchor_integrity
    >>> from app.services import forecast_ledger as ledger
    >>> case = json.loads(Path("backend/tests/fixtures/target_case.json").read_text())
    >>> case["binaries"][0]["resolution_contract"] = {"kind": "polymarket", "market_id": "wrong-market", "equivalence": "exact"}
    >>> markets = [{"market_id": "wrong-market", "question": "Will 2028 spending be at least USD 999 billion?", "description": "YES only if 2028 spending exceeds USD 999 billion.", "endDate": "2028-12-31", "url": "https://example.test/wrong-market", "implied_yes_prob": 0.3}]
    >>> bundle = build_target_report(case, markets=markets)
    >>> binary = next(row for row in bundle["forecast"]["binary_forecasts"] if row["id"] == "B1")
    >>> (binary["statement"], binary["market_anchor"]["question"], binary["market_anchor"]["resolution_equivalence"])
    ('Will 2027 spending be at least USD 280 billion?', 'Will 2028 spending be at least USD 999 billion?', 'exact')
    >>> audit_market_anchor_integrity(bundle["forecast"])["passed"]
    True
    >>> audit_target_report(case, None, bundle["forecast"], bundle["record"], markets=markets)["valid"]
    True
    >>> journal = root / "journal"
    >>> publication = ledger.record_published_forecast(bundle["forecast"], report_id="audit-wrong-market", created_at=clock, d=journal)
    >>> outcome = {"report_id": "audit-wrong-market", "forecast_id": "B1", "model_p": binary["probability"], "market_id": "wrong-market", "market_anchor": binary["market_anchor"], "resolved_at": "2029-01-02T00:00:00Z", "resolved_outcome": "Yes", "resolved_yes_price": 1.0}
    >>> ledger.reconcile_published_resolutions("audit-wrong-market", market_rows=[outcome], data_rows=[], d=journal)["accepted"]
    1
    >>> ledger.production_track_record(d=journal)["tracks"]["market_binary"]["mean_brier"]
    0.16
    >>> scratch.cleanup()

## Verification and boundaries

**Fresh bounded result: 80 passed in 2.35 seconds**, consisting of this document's reproducible defect checks and the feedback-extension, input-health/probe/cadence, and frozen-cohort modules. The doctest confirmed both G1-STATUS outputs and G3-EXACT's wrong-event anchor, passing component audits, accepted journal event, and 0.16 exact-market Brier score. This establishes a broken admission path; it does not claim execution of a full live pipeline or prove legitimate settlement of the synthetic future event.

Exact command, from the isolated worktree root:

```sh
/Users/rogerlin/Downloads/DeepResearchForecast/backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-g1g3-audit-20261028-a --doctest-glob=feedback-review.md docs/handoff/first-ten-remedies/feedback-review.md backend/tests/test_target_feedback_extensions.py backend/tests/test_target_inputs_health_probe.py backend/tests/test_forward_cohort_proposal.py
```

Evidence: `/private/tmp/drf-g1g3-audit-20261028-a/junit.xml`, `completed.json`, and `events-66376.jsonl`. The completed receipt records exit 0, shutdown complete, no drift among its recorded source hashes, preserved identity variables, no child processes, and one blocked external `.pdbrc` read. It records no socket/process attempts. The guard is a CPython audit boundary, not an OS sandbox. The full 537-file baseline verification remains the coordinator's separate evidence, not this receipt's claim.

The coordinator-owned `test_target_pipeline`, `test_target_report_api`, `test_target_research` and `test_world_report_consumers` modules were not rerun. Other workers changed unrelated source during this audit; those edits were preserved. No implementation file was written by this owner.

All live transport/provider confirmation, production monitor activation and paid/prospective cohort evidence remain under existing [issue 10](https://github.com/linroger/DeepResearchForecast/issues/10). No new issue or remote mutation was performed. G3-EXACT remains owned by the reporting agent; this owner does not edit extractor, report authority or feedback/journal code.

## G1 implementation and focused acceptance

G1-STATUS now consumes native `empty_reason=disabled` and recognizes dated successful-empty checks without inventing a price timestamp. The optional additive `attempted_at` output preserves the collector's status-check time separately from `as_of`. Malformed/future attempt times cannot establish empty availability, attempts cannot freshen undated prices, old empty checks become stale, and cached prices keep their original snapshot time. Inputs are not mutated. The actual collector output reaches the brief/card rendering helper with disabled, empty or offline labels.

G1-PROBE now calls the existing collector `_polymarket_get` directly for Gamma and CLOB and reuses its normalization/history parser. No bridge source extraction or edit was necessary. The CLI still accepts query, `--token-id`, `--timeout`, `--limit` and emits `market-probe/v1`; explicit timeout overrides both calls. Omitting timeout follows the research collector's Gamma environment/default and CLOB history's 15-second default. `urllib.request.urlopen`, browser user agent, endpoint overrides, retry classification, and the default proxy/TLS path are shared with production collection. Missing token remains unknown, failures remain offline and no-price health keeps `as_of=None`.

Focused evidence:

- `/private/tmp/drf-g1-remedies-red-20261028-b`: **13 failed, 5 passed** on the pre-repair code with corrected fixtures. The transport tests forbid backend `httpx` and substitute only `urllib.request.urlopen`.
- `/private/tmp/drf-g1-remedies-green-20261028-a`: **87 passed in 2.58s**, comprising both new test modules and existing `test_exec_brief_quality.py`.
- `/private/tmp/drf-g1-compatibility-20261028-a`: **30 passed, 2 deselected**, existing input-health/cadence tests. The two existing probe cases mock the former backend transport and require coordinator-owned migration: `test_probe_cli_uses_real_configured_gamma_and_clob_transport` and `test_probe_disabled_and_missing_clob_token_do_not_claim_success` in `test_target_inputs_health_probe.py`. They were not edited or counted as passing.

Every test run used the unchanged provisioned interpreter with `-I -S -B backend/scripts/main_offline_pytest.py --evidence-dir NEW`, writing only guarded evidence. Independent read-only review was requested and is closed in the final record below. No live probe was executed.

### Final G1 acceptance and frozen source

**G1-STATUS and G1-PROBE are implemented; final focused acceptance is 120 passed, zero failed/skipped/deselected, in 2.09 seconds.** Evidence directory: `/private/tmp/drf-g1-final-20261028-a` (`junit.xml`, `completed.json`). The command selected exactly `test_first_ten_market_health.py`, `test_first_ten_collector_probe.py`, `test_target_inputs_health_probe.py`, and `test_exec_brief_quality.py` through the same guarded runner/interpreter described above. Ruff `check --no-cache --select F,E9` passed on all five changed Python files; scoped `git diff --check` passed.

The coordinator explicitly extended ownership to the two former backend-client probe tests in `test_target_inputs_health_probe.py`. Only those two functions were migrated. Positive Gamma/CLOB normalization, timeout/user-agent checks, disabled no-transport behavior and endpoint redaction assertions are retained; missing-token behavior is now exercised explicitly. Both tests patch `urllib.request.urlopen` and reject use of backend `httpx`. The earlier 2-case deselection is closed by the final complete module run.

Independent reviewer Lorentz identified one additional concrete P2: a native mixed-query result (one successful empty query and one transport failure) was classified empty. Positive `transport_failure_count` now takes precedence, with a real collector fixture confirming `offline`, `as_of=None`, and preserved `attempted_at`. **Read-only closure review is complete: the P2 is resolved and no concrete in-scope findings remain.** The reviewer independently confirmed all five frozen hashes, unchanged bridge/runner source and the120-pass final JUnit. No files or tests were changed by that reviewer.

Frozen SHA-256 values (no further source/test edits after this record):

| Changed file | SHA-256 |
|---|---|
| `backend/app/services/forecast_inputs_health.py` | `48c73f949b474557a90e29d516d4c9587c7af14ebeb86419dc80d370d236fa89` |
| `backend/scripts/probe_markets.py` | `f4cc49167613d3d0f7e3e7000f0297154186b855d3e10d2461ada0aebe2f5465` |
| `backend/tests/test_first_ten_market_health.py` | `be0fbb401b3084cfa6520b7e2393de960087baeb95a74395eeb652ed3723791a` |
| `backend/tests/test_first_ten_collector_probe.py` | `b0b5391510008de3f5086d27afaf2e483b5ca558a302f9766e0f5893bd89cd07` |
| `backend/tests/test_target_inputs_health_probe.py` | `a80bd75a619c0598b6ba45ed5343f2154e6aaaeed55f7395a478dfe487d0c535` |

`deerflow_bridge/deerflow_research.py` was not changed: its existing transport helper is reused. The only other owned modification is this review document. The final guard receipt records completed shutdown, exit 0, preserved identity, no source drift among its recorded files, no children, and no blocked socket/process/external-read events. This is focused offline implementation evidence; no network probe, paid run, active scheduler, service, deployment, saved-upload mutation or issue-10 change occurred. Integration/commit remains coordinator-owned.

## Updates

- 2026-10-28: Read supplied slice-4 acceptance, current first-ten handoff, delivered architecture/contracts/verification, and relevant producers/consumers/tests. Wrote source findings and bounded executable reproductions in this owned report only.
- 2026-10-28: Completed guarded 80-case check and inspected its shutdown receipt. Confirmed two runtime defects; retained the transport-probe mismatch as a source-demonstrated offline acceptance gap. Added owner/case/digest snapshot checks and distinguished source coverage from the coordinator's broader acceptance.
- 2026-10-28: Coordinator assigned implementation of G1-STATUS/G1-PROBE in `forecast_inputs_health.py`, `probe_markets.py`, two new focused test files and this report. G3-EXACT is owned by the reporting agent. Planned interface: additive optional `attempted_at` status-check time, no-price `as_of=None`; collector `_polymarket_get` reused directly for both probe endpoints without bridge source edits. Existing CLI flags/result envelope stay stable; omitted timeout follows collector defaults (Gamma environment setting, CLOB history 15 seconds), and explicit `--timeout` overrides both. Source-aware no-price states, stale snapshot time and future/invalid attempt times get focused tests. First red run: 13 failures/5 passes; corrected two fixture details before repeating (missing attempted-query count and the actual brief label); the old probe tests' backend Config enablement is also made explicit in the new regression fixture so the old path cannot hide behind disabled state.
- 2026-10-28: Initial repair passed87 checks plus30 compatibility checks with2 old probe cases excluded. Coordinator authorized those2 test-function migrations; reviewer identified the partial-failure status gap, which was repaired. Final120 checks and Ruff F/E9 pass, all compatibility exclusions closed, five source/test hashes frozen above. A guessed venv Ruff path was absent; no installation occurred, and the existing PATH Ruff binary completed the check. No production bridge file or out-of-scope worker file was edited.
- 2026-10-28: Independent source review closed on frozen hashes with no remaining concrete G1 findings. This owner is ready for coordinator integration; all implementation writes are complete.
