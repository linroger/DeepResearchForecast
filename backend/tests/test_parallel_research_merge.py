"""Offline unit tests for PAR-2 parallel-research-track merge helpers.

These are pure functions (no network / LLM / disk) that deterministically fold K
angle-specialized research tracks back into one handoff/. Covers the four
load-bearing merge rules called out in the PAR-2 spec:

  * source union with highest-tier-wins dedup by URL
  * research_report concat under '# Track N' H1 headers
  * quantitative/contested/timeline concat-with-dedup
  * research_quality = min score across tracks (with per-track detail)
  * prediction_markets = freshest snapshot by as_of

plus actors merge routed through the existing reconcile_cast machinery.
"""

from app.services.pipeline_orchestrator import (
    merge_track_reports,
    merge_sources_union,
    merge_list_dedup,
    merge_actors_objs,
    merge_research_quality,
    pick_freshest_markets,
    merge_market_snapshots,
    merge_market_price_histories,
    _source_tier_histogram,
    _track_tier_rank,
    _track_norm_url,
    _RESEARCH_TRACK_ANGLES,
    research_subagent_cap_per_track,
    research_outer_track_workers,
    research_model_concurrency_cap,
    research_lane_subagent_cap,
    research_dual_track_for_outer_lane,
    append_merged_references,
    normalize_track_report_citations,
)


# ── tier rank / url normalization ───────────────────────────────────────────

def test_tier_rank_orders_s1_highest_unknown_lowest():
    assert _track_tier_rank("S1") == 1
    assert _track_tier_rank("s3") == 3
    assert _track_tier_rank("S4") == 4
    assert _track_tier_rank(None) == 9
    assert _track_tier_rank("garbage") == 9


def test_norm_url_strips_trailing_slash_and_case():
    assert _track_norm_url("https://A.com/x/") == "https://a.com/x"
    assert _track_norm_url("  https://a.com/x  ") == "https://a.com/x"
    assert _track_norm_url(None) == ""


# ── source union: highest tier wins on URL dedup ────────────────────────────

def test_source_union_dedups_by_url_keeping_highest_tier():
    t1 = [{"url": "https://a.gov/x", "tier": "S3", "title": "A"}]
    t2 = [{"url": "https://a.gov/x/", "tier": "S1", "date": "2026-01-01"}]  # same URL, better tier
    t3 = [{"url": "https://b.com/y", "tier": "S2", "title": "B"}]
    out = merge_sources_union([t1, t2, t3])
    # a.gov collapsed to one row, tier upgraded to S1, missing fields backfilled
    urls = [s["url"] for s in out]
    assert urls == ["https://a.gov/x", "https://b.com/y"]
    a = out[0]
    assert a["tier"] == "S1"          # highest tier kept
    assert a["title"] == "A"          # kept from first-seen
    assert a["date"] == "2026-01-01"  # backfilled from the higher-tier row


def test_source_union_keeps_urlless_rows_and_is_deterministic():
    t1 = [{"title": "no-url row"}]
    t2 = [{"url": "https://a.com", "tier": "S2"}]
    out = merge_sources_union([t1, t2])
    assert len(out) == 2
    assert out[0]["title"] == "no-url row"
    # rerun → identical order/content (determinism)
    assert merge_sources_union([t1, t2]) == out


def test_source_union_ignores_non_list_and_non_dict():
    assert merge_sources_union([None, "bad", [123, {"url": "u", "tier": "S1"}]]) == [
        {"url": "u", "tier": "S1"}
    ]


def test_track_citations_are_remapped_to_one_global_source_namespace():
    merged_sources = [
        {"title": "A", "url": "https://a.test/source"},
        {"title": "B", "url": "https://b.test/source"},
    ]
    track_report = (
        "# Analysis\n\nClaim A [S1]. Claim B [S2]. Unknown [S9].\n\n"
        "## References\n\n"
        "- [S1] B source — https://b.test/source\n"
        "- [S2] A source — https://a.test/source\n"
    )
    normalized, audit = normalize_track_report_citations(
        track_report,
        [{"url": "https://wrong.test/fallback"}, {"url": "https://wrong2.test"}],
        merged_sources,
    )

    assert "Claim A [S2]. Claim B [S1]. Unknown." in normalized
    assert "## References" not in normalized
    assert audit == {"markers": 3, "remapped": 2, "stripped": 1}

    merged = append_merged_references(normalized, merged_sources)
    assert merged.count("## References") == 1
    assert "- [S1] A — https://a.test/source" in merged
    assert "- [S2] B — https://b.test/source" in merged


def test_track_citation_remap_falls_back_to_track_source_positions():
    report = "Metric reached 42% [S1]."
    sources = [{"title": "Data", "url": "https://data.test/value"}]
    normalized, audit = normalize_track_report_citations(report, sources, sources)
    assert normalized == report
    assert audit["remapped"] == 1 and audit["stripped"] == 0


# ── report concat under '# Track N' headers ─────────────────────────────────

def test_merge_track_reports_concats_under_h1_headers():
    out = merge_track_reports([("Angle A", "body-a"), ("Angle B", "body-b")])
    assert out == "# Track 1: Angle A\n\nbody-a\n\n# Track 2: Angle B\n\nbody-b"


def test_merge_track_reports_skips_empty_and_renumbers_contiguously():
    out = merge_track_reports([("A", "body-a"), ("B", "   "), ("C", "body-c")])
    # empty middle track dropped; numbering stays contiguous 1,2
    assert "# Track 1: A" in out
    assert "# Track 2: C" in out
    assert "Track 3" not in out
    assert "B" not in out.split("body-a")[0] or "# Track" in out  # B header absent


# ── quantitative/contested/timeline concat + dedup ──────────────────────────

def test_merge_list_dedup_concats_and_dedups_by_identity():
    t1 = [{"metric": "gdp", "value": 1}, {"metric": "cpi", "value": 2}]
    t2 = [{"value": 1, "metric": "gdp"}, {"metric": "unemp", "value": 3}]  # first is dup (key order irrelevant)
    out = merge_list_dedup([t1, t2])
    assert out == [
        {"metric": "gdp", "value": 1},
        {"metric": "cpi", "value": 2},
        {"metric": "unemp", "value": 3},
    ]


def test_merge_list_dedup_tolerates_non_list_inputs():
    assert merge_list_dedup([None, [{"a": 1}], "bad", [{"a": 1}]]) == [{"a": 1}]


# ── research_quality = min across tracks ────────────────────────────────────

def test_merge_research_quality_takes_min_score_with_per_track_detail():
    m1 = {"research_quality": {"score": 0.80, "components": {"x": 1}}}
    m2 = {"research_quality": {"score": 0.55, "components": {"y": 2}}}
    m3 = {"research_quality": {"score": 0.70}}
    merged = merge_research_quality([m1, m2, m3])
    assert merged["score"] == 0.55                     # conservative min
    assert merged["components"] == {"y": 2}            # base is the min-score track
    assert merged["merged_from_tracks"] == 3
    scores = [p.get("score") for p in merged["per_track"]]
    assert scores == [0.80, 0.55, 0.70]


def test_merge_research_quality_handles_missing_scores():
    merged = merge_research_quality([{}, {"research_quality": {"no_score": True}}])
    assert "score" not in merged
    assert merged["merged_from_tracks"] == 2
    assert merged["per_track"][0] == {"track": 1, "research_quality": None}


# ── source tier histogram recompute ─────────────────────────────────────────

def test_source_tier_histogram_counts_by_tier():
    sources = [
        {"tier": "S1"}, {"tier": "S1"}, {"tier": "S3"}, {"tier": None}, {"no": "tier"}
    ]
    hist = _source_tier_histogram(sources)
    assert hist == {"s1_count": 2, "s2_count": 0, "s3_count": 1, "s4_count": 0, "s_unknown": 2}


# ── freshest prediction-markets snapshot ────────────────────────────────────

def test_pick_freshest_markets_by_as_of():
    a = {"as_of": "2026-01-01T00:00:00Z", "markets": [{"q": 1}]}
    b = {"as_of": "2026-03-01T00:00:00Z", "markets": [{"q": 2}]}
    assert pick_freshest_markets([a, b]) is b
    assert pick_freshest_markets([b, a]) is b


def test_pick_freshest_markets_prefers_nonempty_then_falls_back():
    empty = {"as_of": "2026-05-01", "markets": []}
    nonempty = {"as_of": "2026-01-01", "markets": [{"q": 1}]}
    assert pick_freshest_markets([empty, nonempty]) is nonempty
    # all empty → returns first dict (fallback)
    only_empty = {"as_of": "x", "markets": []}
    assert pick_freshest_markets([only_empty]) is only_empty
    assert pick_freshest_markets([None, "bad"]) is None


def test_market_snapshot_merge_unions_tracks_and_keeps_freshest_quote():
    first = {
        "as_of": "2026-07-10T00:00:00Z", "queries": ["AI bubble"],
        "markets": [
            {"market_id": "a", "question": "A?", "implied_yes_prob": 0.2,
             "volume": 1000, "event_title": "A"},
            {"market_id": "b", "question": "B?", "implied_yes_prob": 0.3,
             "volume": 500, "event_title": "B"},
        ],
    }
    second = {
        "as_of": "2026-07-11T00:00:00Z", "queries": ["AI bubble", "US recession"],
        "markets": [
            {"market_id": "a", "question": "A?", "implied_yes_prob": 0.25,
             "volume": 1500, "event_title": "A"},
            {"market_id": "c", "question": "C?", "implied_yes_prob": 0.4,
             "volume": 800, "event_title": "C"},
        ],
    }

    merged = merge_market_snapshots([first, {"as_of": "later", "markets": []}, second])

    by_id = {row["market_id"]: row for row in merged["markets"]}
    assert set(by_id) == {"a", "b", "c"}
    assert by_id["a"]["implied_yes_prob"] == 0.25
    assert len(by_id["a"]["track_provenance"]) == 2
    assert merged["queries"] == ["AI bubble", "US recession"]
    assert merged["status"]["selected_count"] == 3
    assert "end_date_passed_count" not in merged["status"]  # no track ran the TIME-3 gate


def test_market_snapshot_merge_recounts_end_date_passed_rows_that_survive_selection():
    """TIME-3: tracks that ran the endDate gate carry status.end_date_passed_count; the merge
    recounts the window_ended rows it actually selected, so the telemetry survives."""
    def row(mid, volume, ended):
        out = {"market_id": mid, "question": f"{mid}?", "implied_yes_prob": 0.3,
               "volume": volume, "event_title": mid}
        if ended:
            out.update(window_ended=True, window_ended_at="2026-09-30T12:00:00+00:00")
        return out

    first = {"as_of": "2026-10-01T00:00:00Z", "status": {"end_date_passed_count": 1},
             "markets": [row("a", 1000, True), row("b", 500, False)]}
    second = {"as_of": "2026-10-02T00:00:00Z", "status": {"end_date_passed_count": 2},
              "markets": [row("a", 1500, True), row("c", 100, True)]}
    gate_off_track = {"as_of": "2026-10-02T00:00:00Z", "markets": [row("d", 50, False)]}

    merged = merge_market_snapshots([first, second, gate_off_track])
    assert merged["status"]["end_date_passed_count"] == 2  # a and c; the row stays stamped
    assert {r["market_id"] for r in merged["markets"] if r.get("window_ended")} == {"a", "c"}
    capped = merge_market_snapshots([first, second], max_total=2)  # c falls to the cap
    assert [r["market_id"] for r in capped["markets"]] == ["a", "b"]
    assert capped["status"]["end_date_passed_count"] == 1


def test_market_price_history_merge_filters_selected_and_deduplicates_timestamps():
    histories = [
        {"a": [{"t": 1, "p": 0.2}, {"t": 2, "p": 0.3}],
         "discard": [{"t": 1, "p": 0.9}]},
        {"a": [{"t": 2, "p": 0.35}, {"t": 3, "p": 0.4}],
         "b": [{"t": 1, "p": 0.6}]},
    ]
    assert merge_market_price_histories(histories, {"a", "b"}) == {
        "a": [{"t": 1, "p": 0.2}, {"t": 2, "p": 0.35}, {"t": 3, "p": 0.4}],
        "b": [{"t": 1, "p": 0.6}],
    }


def test_market_snapshot_merge_preserves_transport_failure_status():
    merged = merge_market_snapshots([{
        "as_of": "2026-07-11T00:00:00Z", "markets": [],
        "status": {
            "query_count": 4, "successful_query_count": 0,
            "transport_failure_count": 4, "tool_observation_count": 0,
        },
    }])
    assert merged["status"]["empty_reason"] == "transport_failure"
    assert merged["status"]["transport_failure_count"] == 4


def test_market_snapshot_merge_preserves_raw_candidates_and_empty_reasons():
    merged = merge_market_snapshots([
        {
            "as_of": "2026-07-10T00:00:00Z", "markets": [],
            "status": {
                "attempted_query_count": 2, "query_count": 2,
                "successful_query_count": 2, "transport_failure_count": 0,
                "candidate_count": 5, "empty_reason": "all_candidates_irrelevant",
            },
        },
        {
            "as_of": "2026-07-11T00:00:00Z", "markets": [],
            "status": {
                "query_count": 1, "successful_query_count": 1,
                "transport_failure_count": 0, "candidate_count": 3,
                "empty_reason": "all_candidates_irrelevant",
            },
        },
    ])

    assert merged["status"]["candidate_count"] == 8
    assert merged["status"]["raw_candidate_count"] == 8
    assert merged["status"]["selected_input_count"] == 0
    assert merged["status"]["query_count"] == 3  # no double count of alias fields
    assert merged["status"]["attempted_query_count"] == 3
    assert merged["status"]["empty_reason"] == "all_candidates_irrelevant"
    assert merged["status"]["state"] == "all_candidates_irrelevant"
    assert merged["status"]["empty_reason_counts"] == {"all_candidates_irrelevant": 2}


def test_market_snapshot_merge_transport_requires_every_attempt_to_fail():
    merged = merge_market_snapshots([
        {
            "markets": [],
            "status": {
                "query_count": 4, "successful_query_count": 0,
                "transport_failure_count": 4, "candidate_count": 0,
                "empty_reason": "transport_failure",
            },
        },
        {
            "markets": [],
            "status": {
                "query_count": 2, "successful_query_count": 2,
                "transport_failure_count": 0, "candidate_count": 0,
                "empty_reason": "no_equivalent_market",
            },
        },
    ])

    assert merged["status"]["query_count"] == 6
    assert merged["status"]["successful_query_count"] == 2
    assert merged["status"]["transport_failure_count"] == 4
    # RESEARCH-3: a partial outage with no candidate is labelled, never folded
    # into the generic 'no_equivalent_market'.
    assert merged["status"]["empty_reason"] == "partial_transport_failure"
    assert merged["status"]["state"] == "partial_transport_failure"
    assert merged["status"]["empty_reason_counts"] == {
        "transport_failure": 1, "no_equivalent_market": 1,
    }


def test_market_snapshot_merge_exposes_inflight_timeout_without_calling_it_outage():
    merged = merge_market_snapshots([{
        "markets": [],
        "status": {
            "attempted_query_count": 2, "successful_query_count": 0,
            "transport_failure_count": 0, "inflight_timeout_count": 2,
            "candidate_count": 0, "empty_reason": "inflight_timeout",
        },
    }])

    assert merged["status"]["empty_reason"] == "no_equivalent_market"
    assert merged["status"]["state"] == "inflight_timeout"
    assert merged["status"]["inflight_timeout_count"] == 2
    assert merged["status"]["empty_reason_counts"] == {"inflight_timeout": 1}


def test_market_snapshot_merge_raw_candidates_take_empty_reason_precedence():
    merged = merge_market_snapshots([{
        "markets": [],
        "status": {
            "query_count": 2, "successful_query_count": 0,
            "transport_failure_count": 2, "candidate_count": 4,
            "empty_reason": "transport_failure",
        },
    }])

    assert merged["status"]["candidate_count"] == 4
    assert merged["status"]["empty_reason"] == "all_candidates_irrelevant"
    assert merged["status"]["state"] == "all_candidates_irrelevant"


# ── actors merge via reconcile_cast machinery ───────────────────────────────

def test_merge_actors_unions_rows_and_reconciles_duplicates():
    t1 = {
        "central_question": "Q1",
        "as_of_date": "2026-05-01",
        "actors": [{"name": "Nvidia", "role": "chipmaker", "influence": "high"}],
        "relationships": [{"source": "Nvidia", "target": "TSMC", "label": "buys_from"}],
    }
    t2 = {
        "central_question": "Q2",  # scalar taken from first non-empty track (t1)
        "actors": [
            {"name": "NVIDIA Corp", "aliases": ["Nvidia"]},   # duplicate of t1's Nvidia
            {"name": "AMD", "role": "chipmaker"},
        ],
    }
    merged, audit = merge_actors_objs([t1, t2])
    assert merged is not None
    names = {a.get("name") for a in merged.get("actors", [])}
    # Nvidia + NVIDIA Corp reconciled to a single canonical row; AMD distinct
    assert len(merged["actors"]) == 2
    assert "AMD" in names
    assert merged["central_question"] == "Q1"   # scalar from first non-empty track
    assert audit.get("n_before") == 3
    assert audit.get("n_after") == 2


def test_merge_actors_all_empty_returns_none():
    merged, audit = merge_actors_objs([None, "bad", {}])
    # {} is a dict → becomes base with empty actors; reconcile of <2 rows is a no-op
    assert merged == {"actors": []}
    merged2, _ = merge_actors_objs([None, "bad"])
    assert merged2 is None


# ── angle table sanity ──────────────────────────────────────────────────────

def test_track_angles_track1_has_no_prefix():
    # Track 1 must be the verbatim base evidence sweep (empty prefix → byte-identical prompt).
    assert _RESEARCH_TRACK_ANGLES[0][2] == ""
    # tracks 2/3 carry angle-specialization prefixes
    assert _RESEARCH_TRACK_ANGLES[1][2].strip() != ""
    assert _RESEARCH_TRACK_ANGLES[2][2].strip() != ""


def test_global_subagent_envelope_is_shared_across_outer_tracks():
    assert research_subagent_cap_per_track(3, 9, 5) == 3
    assert research_subagent_cap_per_track(2, 9, 5) == 4
    assert research_subagent_cap_per_track(1, 9, 5) == 5
    assert research_subagent_cap_per_track(3, 2, 5) == 1
    assert len(_RESEARCH_TRACK_ANGLES) == 3


def test_outer_tracks_and_model_streams_share_one_global_envelope():
    assert research_outer_track_workers(3, 9) == 3
    assert research_outer_track_workers(3, 2) == 2
    assert research_outer_track_workers(3, 1) == 1
    assert research_outer_track_workers(3, 9, 2) == 2
    assert research_model_concurrency_cap(3, 9, 0) == 12
    assert research_model_concurrency_cap(2, 2, 0) == 4
    assert research_model_concurrency_cap(3, 9, 7) == 7
    assert research_lane_subagent_cap(3, 9, 5, 12) == 3
    assert research_lane_subagent_cap(2, 9, 5, 4) == 1
    assert research_lane_subagent_cap(2, 9, 5, 2) == 0


def test_actor_ontology_track_runs_once_across_outer_angles():
    assert [
        research_dual_track_for_outer_lane(index, True)
        for index in range(3)
    ] == [True, False, False]
    assert not research_dual_track_for_outer_lane(0, False)
