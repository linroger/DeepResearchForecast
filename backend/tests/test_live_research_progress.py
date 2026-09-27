"""Focused regression coverage for LOOP-008 live research observability."""

from __future__ import annotations

import json

import pytest
from flask import Flask

from app.api import research_bp
from app.services.pipeline_orchestrator import PipelineManager
from app.services.research_progress import (
    ResearchProgressEstimator,
    aggregate_parallel_progress,
    merged_research_progress_full,
    merged_research_progress_tail,
)


def test_phase_bounded_progress_does_not_jump_to_ninety_during_opening_tools():
    estimator = ResearchProgressEstimator()
    observed = [estimator.observe("2026-01-01T00:00:00+00:00 [init] client ready")]
    observed.append(estimator.observe(
        "2026-01-01T00:00:01+00:00 [stage] deep: starting multi-pass research protocol"))
    observed.append(estimator.observe(
        "2026-01-01T00:00:02+00:00 [stage] research:deep-opening: starting agent turn"))
    for i in range(300):
        kind = "tool" if i % 2 == 0 else "result"
        observed.append(estimator.observe(f"2026-01-01T00:00:03+00:00 [{kind}] event {i}"))

    # Hundreds of opening events remain inside the opening phase's 8..16 band.
    assert observed == sorted(observed)
    assert estimator.progress < 16
    opening_progress = estimator.progress
    assert estimator.observe(
        "2026-01-01T00:05:00+00:00 [stage] actor-ontology synthesize: produced 70000 chars"
    ) == opening_progress
    assert estimator.observe(
        "2026-01-01T00:05:01+00:00 [result] article says research complete; "
        "wrote research_report.md"
    ) < 16
    assert estimator.observe(
        "2026-01-01T00:05:02+00:00 [result] docs literally say [done] research complete"
    ) < 16
    assert estimator.observe(
        '2026-01-01T00:05:03+00:00 [tool] web_search(query="[stage] wrote sources.json")'
    ) < 16

    assert estimator.observe(
        "2026-01-01T00:10:00+00:00 [stage] deep fan-out: 8 scoped workers") == 18
    for i in range(500):
        estimator.observe(f"2026-01-01T00:10:01+00:00 [tool] fanout {i}")
    assert estimator.progress < 32

    assert estimator.observe(
        "2026-01-01T01:00:00+00:00 [stage] deep: running 3 middle phases in parallel") == 42
    assert estimator.observe(
        "2026-01-01T02:00:00+00:00 [stage] synthesize/multipart: requesting section outline") == 78
    assert estimator.observe(
        "2026-01-01T03:00:00+00:00 [done] research complete") == 99
    # Late/out-of-order stdout cannot regress the UI.
    assert estimator.observe("2026-01-01T00:00:00+00:00 [init] client ready") == 99


def test_parallel_progress_is_equal_weight_monotonic_and_reserves_merge_band():
    assert aggregate_parallel_progress([20, 40, 60], previous=2) == 40
    assert aggregate_parallel_progress([100, 100, 100], previous=40) == 95
    assert aggregate_parallel_progress([10, 10, 10], previous=41) == 41
    assert aggregate_parallel_progress([], previous=7) == 7
    # Once a failed lane is terminal and excluded, surviving lanes can reach the
    # reserved merge boundary instead of jumping from ~64 straight to 96.
    assert aggregate_parallel_progress(
        [95, 95, 2], previous=64, excluded_indices={2}) == 95


def test_report_refinement_does_not_impersonate_late_triangulation():
    estimator = ResearchProgressEstimator()
    assert estimator.observe(
        "2026-01-01T00:00:00+00:00 [stage] research-report refine round 1: addressing 3 gaps"
    ) == 88
    assert estimator.observe(
        "2026-01-01T00:10:00+00:00 [ok] research-report refine round 1: "
        "adopted re-synthesized report (100000 chars)"
    ) == 88
    assert estimator.observe(
        "2026-01-01T00:20:00+00:00 [stage] triangulation top-up: verifying 5 claims"
    ) == 95


def test_deep_coverage_topups_advance_in_bounded_slots_before_synthesis():
    estimator = ResearchProgressEstimator()
    assert estimator.observe(
        "2026-01-01T00:00:00+00:00 [stage] research:deep-5-forecast-implications: "
        "turn complete (80 tool calls, 2000 chars)"
    ) == 68
    observed = []
    for number in range(1, 5):
        observed.append(estimator.observe(
            f"2026-01-01T00:0{number}:00+00:00 [stage] "
            f"research:deep-coverage-topup-{number}: starting agent turn"))
        for i in range(80):
            estimator.observe(
                f"2026-01-01T00:0{number}:01+00:00 "
                f"[tool] coverage round {number} event {i}")
        observed.append(estimator.observe(
            f"2026-01-01T00:0{number}:59+00:00 [stage] "
            f"research:deep-coverage-topup-{number}: turn complete"))

    assert observed == sorted(observed)
    assert observed[0] == 69
    assert observed[-1] == 76
    assert max(observed) < 78
    assert estimator.observe(
        "2026-01-01T00:10:00+00:00 [stage] synthesize/multipart: requesting section outline"
    ) == 78


_TS = "2026-09-27T00:00:00+00:00"


def _feed(estimator, line):
    return estimator.observe(f"{_TS} {line}")


def test_v3_lifecycle_follows_spec_bands_end_to_end():
    """Engine v3 (V3_SPEC §3.3): each phase line lands in its band and the run
    stays monotonic from the plan through the shared finalize milestones."""
    estimator = ResearchProgressEstimator()
    expected = [
        ("[init] client ready", 4),
        ("[stage] research:v3:plan start", 6),
        ("[ok] research:v3:plan done (7 KIQs, 10 sections)", 9),
        ("[stage] research:v3:gather start (7 KIQs, workers=4)", 10),
        ("[stage] research:v3:gap round 1", 60),
        ("[stage] research:v3:gap round 2", 64),
        ("[stage] research:v3:synthesize start (8 groups)", 70),
        ("[ok] research:v3:synthesize done", 86),
        ("[stage] research:v3:qa start", 88),
        ("[ok] research:v3:qa passed=True failures=0 repaired=1", 89),
        ("[stage] research:v3:finalize start", 90),
        ("[ok] wrote research_report.md (61234 chars)", 91),
        # v3 publishes sources.json before extraction → below actors.json.
        ("[ok] wrote sources.json (42 sources)", 92),
        ("[ok] wrote actors.json (12 actors)", 93),
        ("[ok] wrote timeline.json (9 events)", 94),
        ("[ok] wrote quantitative.json (20 facts)", 94),
        ("[ok] wrote charts.json (4 charts) + charts/ files", 98),
        ("[done] research complete (v3: 7 KIQs, 42 sources)", 99),
    ]
    observed = [_feed(estimator, line) for line, _ in expected]
    assert observed == [value for _, value in expected]


def test_v3_gather_tool_activity_moves_inside_band_but_never_crosses_it():
    estimator = ResearchProgressEstimator()
    assert _feed(estimator, "[stage] research:v3:gather start (10 KIQs, workers=4)") == 10
    observed = []
    for i in range(1500):
        kind = "tool" if i % 2 == 0 else "result"
        observed.append(_feed(estimator, f"[{kind}] web_search query {i}"))
    assert observed == sorted(observed)
    assert 30 < observed[-1] < 60
    assert _feed(estimator, "[stage] research:v3:gap round 1") == 60


def test_v3_kiq_completions_advance_proportionally_deduped_with_reserve():
    estimator = ResearchProgressEstimator()
    _feed(estimator, "[stage] research:v3:gather start (5 KIQs, workers=4)")
    # 49 usable points (one reserved) / 5 KIQs.
    assert _feed(estimator, "[ok] research:v3:gather K1 facts=6 verified=4 sources=5") == 19
    # A re-emitted completion of the same KIQ is not a new unit.
    assert _feed(estimator, "[ok] research:v3:gather K1 facts=7 verified=4 sources=5") == 19
    # Warnings, untrusted results and usage lines are never unit completions.
    assert _feed(estimator, "[warn] research:v3:gather K2 content filtered; fallback notes") == 19
    assert _feed(estimator, "[result] research:v3:gather K3 facts=9") == 19
    assert _feed(estimator, "[usage] tokens in=10 out=5 total=15 phase=gather:K2 cached=0") == 19
    for kiq in ("K2", "K3", "K4", "K5"):
        _feed(estimator, f"[ok] research:v3:gather {kiq} facts=3 verified=1 sources=2")
    # All units done → floor + span - 1: the gap/synthesize boundary stays explicit.
    assert estimator.progress == 59


def test_v3_follow_up_gathering_inside_gap_neither_regresses_nor_rearms():
    estimator = ResearchProgressEstimator()
    _feed(estimator, "[stage] research:v3:gather start (4 KIQs, workers=4)")
    assert _feed(estimator, "[stage] research:v3:gap round 1") == 60
    # Gap follow-ups reuse the gather machinery; a repeated gather start must not
    # pull the band back to 10, and its completions belong to no armed ledger.
    assert _feed(estimator, "[stage] research:v3:gather start (3 KIQs, workers=4)") == 60
    assert _feed(estimator, "[ok] research:v3:gather G1F1 facts=2 verified=1 sources=2") == 60
    assert _feed(estimator, "[ok] research:v3:gather G1F2 facts=2 verified=1 sources=2") == 60
    # Rounds beyond the preset maximum share the last gap slot.
    assert _feed(estimator, "[stage] research:v3:gap round 5") == 64
    assert _feed(estimator, "[stage] research:v3:synthesize start (6 groups)") == 70


def test_v3_lines_never_fall_through_to_legacy_milestones():
    """A v3 line is classified only by the v3 vocabulary: unknown v3 phases or
    shapes are inert even when they contain legacy milestone substrings."""
    for line in (
        "[ok] research:v3:synthesize: produced 90000 chars",   # legacy 87
        "[stage] research:v3:extract: starting agent turn",   # legacy 92
        "[stage] research:v3:brief research: starting agent turn",  # legacy 10
        "[ok] research:v3:plan scout digest (6 queries)",      # not 'done'
        "[init] research:v3:gather start (7 KIQs)",           # init never enters
    ):
        estimator = ResearchProgressEstimator()
        assert _feed(estimator, line) == 2, line


def test_legacy_streams_are_untouched_by_v3_rules():
    """Legacy lines never contain ``research:v3:``; their bands (including the
    late sources.json slot) are unchanged, and untrusted previews that merely
    mention v3 lines cannot cross boundaries."""
    for line, expected in (
        ("[stage] research:deep-opening: starting agent turn", 8),
        ("[stage] synthesize/multipart: requesting section outline", 78),
        ("[ok] wrote research_report.md (1000 chars)", 91),
        ("[ok] wrote sources.json (30 sources; tiers={})", 95),
        ("[ok] research_quality=0.71 (components={})", 95),
        ("[stage] research: starting agent turn", 10),
    ):
        assert _feed(ResearchProgressEstimator(), line) == expected, line

    estimator = ResearchProgressEstimator()
    _feed(estimator, "[stage] research: starting agent turn")
    assert _feed(estimator, "[result] page says [ok] research:v3:synthesize done") < 62
    assert _feed(estimator, "[tool] web_search research:v3:qa start") < 62


def test_merged_tail_reads_active_tracks_orders_deduplicates_and_bounds(tmp_path):
    track1 = tmp_path / "track_1"
    track2 = tmp_path / "track_2"
    ignored = tmp_path / "track_bad"
    track1.mkdir()
    track2.mkdir()
    ignored.mkdir()
    first = "2026-01-01T00:00:01+00:00 [tool] first"
    (track1 / "research_progress.log").write_text(
        first + "\n" + first + "\n2026-01-01T00:00:04+00:00 [result] fourth\n",
        encoding="utf-8",
    )
    (track2 / "research_progress.log").write_text(
        "2026-01-01T00:00:02+00:00 [stage] second\n"
        "2026-01-01T00:00:03+00:00 [ok] third\n",
        encoding="utf-8",
    )
    (ignored / "research_progress.log").write_text(
        "2026-01-01T00:00:05+00:00 [error] must not leak\n", encoding="utf-8")

    tail = merged_research_progress_tail(str(tmp_path), limit=3)

    assert tail.source_count == 2
    assert tail.truncated is True
    assert tail.lines == [
        "2026-01-01T00:00:02+00:00 [track:2] [stage] second",
        "2026-01-01T00:00:03+00:00 [track:2] [ok] third",
        "2026-01-01T00:00:04+00:00 [track:1] [result] fourth",
    ]
    assert all("must not leak" not in line for line in tail.lines)


def test_multiline_continuation_keeps_source_order_instead_of_masking_live_tail(tmp_path):
    track = tmp_path / "track_1"
    track.mkdir()
    (track / "research_progress.log").write_text(
        "2026-01-01T00:00:01+00:00 [result] first line\n"
        "continuation of first line\n"
        "2026-01-01T00:00:02+00:00 [tool] genuinely newest\n",
        encoding="utf-8",
    )

    tail = merged_research_progress_tail(str(tmp_path), limit=10)

    assert tail.lines == [
        "2026-01-01T00:00:01+00:00 [track:1] [result] first line",
        "[track:1] continuation of first line",
        "2026-01-01T00:00:02+00:00 [track:1] [tool] genuinely newest",
    ]


def test_full_progress_snapshot_preserves_early_rows_duplicates_and_exact_total(tmp_path):
    root = tmp_path / "research_progress.log"
    track = tmp_path / "track_1"
    track.mkdir()
    root.write_text(
        "2026-01-01T00:00:03+00:00 [done] root summary\n",
        encoding="utf-8",
    )
    repeated = "2026-01-01T00:00:01+00:00 [tool] repeated"
    (track / "research_progress.log").write_text(
        repeated + "\n" + repeated + "\n"
        "2026-01-01T00:00:02+00:00 [result] later\n",
        encoding="utf-8",
    )

    snapshot = merged_research_progress_full(str(tmp_path))

    assert snapshot.source_count == 2
    assert snapshot.truncated is False
    assert len(snapshot.lines) == 4
    assert snapshot.lines[:2] == [
        "2026-01-01T00:00:01+00:00 [track:1] [tool] repeated",
        "2026-01-01T00:00:01+00:00 [track:1] [tool] repeated",
    ]
    assert snapshot.lines[-1].endswith("[done] root summary")


def test_full_progress_snapshot_includes_preserved_failed_attempt_logs(tmp_path):
    attempts = tmp_path / "research_attempts"
    attempts.mkdir()
    (attempts / "global_synthesis_1_failed_abc123.log").write_text(
        "2026-01-01T00:00:00+00:00 [error] first synthesis failed\n",
        encoding="utf-8",
    )
    (tmp_path / "research_progress.log").write_text(
        "2026-01-01T00:00:01+00:00 [done] retry succeeded\n",
        encoding="utf-8",
    )

    snapshot = merged_research_progress_full(str(tmp_path))

    assert snapshot.source_count == 2
    assert snapshot.lines[0].endswith(
        "[attempt:global_synthesis_1_failed_abc123] [error] first synthesis failed"
    )
    assert snapshot.lines[-1].endswith("[done] retry succeeded")


def test_full_progress_snapshot_fails_explicitly_instead_of_silently_truncating(tmp_path):
    (tmp_path / "research_progress.log").write_text("0123456789\n", encoding="utf-8")

    with pytest.raises(ValueError, match="exceeds the full-history safety limit"):
        merged_research_progress_full(str(tmp_path), max_total_bytes=4)


def test_progress_endpoint_serves_track_logs_before_root_merge(tmp_path, monkeypatch):
    track = tmp_path / "track_3"
    track.mkdir()
    (track / "research_progress.log").write_text(
        "2026-01-01T00:00:00+00:00 [init] client ready\n"
        "2026-01-01T00:00:01+00:00 [tool] web_search(query=x)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(PipelineManager, "handoff_dir", lambda _pipeline_id: str(tmp_path))
    monkeypatch.setattr(PipelineManager, "load", lambda _pipeline_id: {"status": "running"})

    app = Flask(__name__)
    app.register_blueprint(research_bp, url_prefix="/api/research")
    response = app.test_client().get("/api/research/pipe_live/progress?lines=20")

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["source_count"] == 1
    assert payload["returned"] == 2
    assert payload["total"] is None
    assert payload["total_exact"] is False
    assert payload["lines"][-1].endswith("[track:3] [tool] web_search(query=x)")
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    assert response.headers["Pragma"] == "no-cache"


def test_progress_endpoint_serves_exact_full_history_on_explicit_scope(tmp_path, monkeypatch):
    track = tmp_path / "track_2"
    track.mkdir()
    (tmp_path / "research_progress.log").write_text(
        "2026-01-01T00:00:02+00:00 [done] root\n",
        encoding="utf-8",
    )
    (track / "research_progress.log").write_text(
        "2026-01-01T00:00:00+00:00 [init] first\n"
        "2026-01-01T00:00:01+00:00 [tool] second\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(PipelineManager, "handoff_dir", lambda _pipeline_id: str(tmp_path))
    monkeypatch.setattr(PipelineManager, "load", lambda _pipeline_id: {"status": "completed"})

    app = Flask(__name__)
    app.register_blueprint(research_bp, url_prefix="/api/research")
    response = app.test_client().get("/api/research/pipe_live/progress?scope=full")

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["scope"] == "full"
    assert payload["returned"] == payload["total"] == 3
    assert payload["total_exact"] is True
    assert payload["snapshot_exact"] is True
    assert payload["event_fidelity"] == "summarized_progress_events"
    assert payload["truncated"] is False
    assert payload["lines"][0].endswith("[track:2] [init] first")
    assert payload["lines"][-1].endswith("[done] root")


def test_progress_endpoint_returns_not_found_for_unknown_pipeline():
    app = Flask(__name__)
    app.register_blueprint(research_bp, url_prefix="/api/research")

    response = app.test_client().get(
        "/api/research/pipe_definitely_missing_loop013/progress?scope=full"
    )

    assert response.status_code == 404
    assert response.get_json()["success"] is False


def test_status_endpoint_is_never_cached(monkeypatch):
    monkeypatch.setattr(PipelineManager, "load", lambda _pipeline_id: {
        "pipeline_id": "pipe_live", "status": "running", "global_progress": 17,
    })
    app = Flask(__name__)
    app.register_blueprint(research_bp, url_prefix="/api/research")

    response = app.test_client().get("/api/research/status/pipe_live")

    assert response.status_code == 200
    assert response.get_json()["data"]["global_progress"] == 17
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    assert response.headers["Pragma"] == "no-cache"


def test_dossier_endpoint_surfaces_market_signals_status_and_charts(tmp_path, monkeypatch):
    (tmp_path / "research_report.md").write_text("# Report", encoding="utf-8")
    market_payload = {
        "as_of": "2026-07-11T00:00:00Z",
        "markets": [{"market_id": "691340", "implied_yes_prob": 0.1545}],
        "status": {"attempted": True, "selected_count": 1, "empty_reason": None},
    }
    (tmp_path / "prediction_markets.json").write_text(
        json.dumps(market_payload), encoding="utf-8")
    (tmp_path / "charts.json").write_text(
        json.dumps([{"id": "market_probabilities", "path": "charts/market.png"}]),
        encoding="utf-8")
    monkeypatch.setattr(PipelineManager, "handoff_dir", lambda _pipeline_id: str(tmp_path))

    app = Flask(__name__)
    app.register_blueprint(research_bp, url_prefix="/api/research")
    response = app.test_client().get("/api/research/pipe_live/dossier")

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["prediction_markets"] == market_payload
    assert data["charts"][0]["id"] == "market_probabilities"
