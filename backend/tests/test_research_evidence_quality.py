"""Offline unit tests for the deerflow-bridge evidence-quality analytics.

Covers the pure, deterministic post-extraction helpers added for the research bucket:
  R2-RES-1  compute_research_quality / research_quality scorecard
  R2-RES-4  annotate_recency_rows (staleness + freshness histogram)
  R2-RES-6  compute_coverage_gaps (completeness probe)
  R2-RES-10 audit_triangulation (single-origin load-bearing claims)
  R2-RES-11 reconcile_quantitative (numeric disagreement + ~1000x unit errors)
  R2-RES-12 source_diversity_histogram (single-region monoculture warning)
  R2-RES-8/9 + RESEARCH-4/5 prompt/plumbing helpers

deerflow_research.py imports the deerflow harness lazily, so these pure helpers
import and run fine under backend/.venv without the deerflow venv.
"""

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "deerflow_bridge"))

import deerflow_research as dr  # noqa: E402


# --- date / number parsing primitives --------------------------------------

def test_parse_date_full_ym_year_and_junk():
    assert dr._parse_date("2026-03-09") == dt.date(2026, 3, 9)
    assert dr._parse_date("2026-03") == dt.date(2026, 3, 1)
    assert dr._parse_date("2026") == dt.date(2026, 1, 1)
    assert dr._parse_date("") is None
    assert dr._parse_date("n/a") is None
    assert dr._parse_date("2026-13-40") is None  # invalid month/day


def test_first_number_handles_ranges_commas_signs():
    assert dr._first_number("52-56") == 52.0
    assert dr._first_number("1,234.5 USD") == 1234.5
    assert dr._first_number("-3%") == -3.0
    assert dr._first_number("none") is None
    assert dr._first_number(None) is None


# --- R2-RES-12 source diversity --------------------------------------------

def test_source_diversity_flags_single_region_monoculture():
    sources = [
        {"title": "a", "jurisdiction": "US", "lang": "en"},
        {"title": "b", "jurisdiction": "us", "lang": "en"},
        {"title": "c", "jurisdiction": "US"},
        {"title": "d", "jurisdiction": "China", "lang": "zh"},
    ]
    out = dr.source_diversity_histogram(sources)
    assert out["n_total"] == 4
    assert out["n_with_jurisdiction"] == 4
    assert out["dominant_jurisdiction"] == "us"
    assert out["dominant_share"] == 0.75
    assert out["single_region_warning"] is True
    assert out["by_language"] == {"en": 2, "zh": 1}


def test_source_diversity_balanced_no_warning_and_legacy_safe():
    out = dr.source_diversity_histogram([
        {"title": "a", "jurisdiction": "US"},
        {"title": "b", "jurisdiction": "EU"},
        {"title": "c"},  # legacy untagged source
    ])
    assert out["single_region_warning"] is False  # 50/50 split, and only 2 tagged
    assert dr.source_diversity_histogram("nope")["n_total"] == 0


# --- R2-RES-1 research quality ---------------------------------------------

def test_research_quality_combines_components():
    sources = [{"title": "x", "tier": "S1"}, {"title": "y", "tier": "S2"}]
    obj = {
        "actors": [
            {"name": "A", "influence": "high",
             "incentives": [{"driver": "d"}],
             "worldview": {"values": ["v"]}},
        ],
        "relationships": [{"source": "A", "target": "B", "valence": "adversarial"}],
    }
    judge = {"scores": {k: 4 for k in dr._JUDGE_DIMS}}
    rq = dr.compute_research_quality(sources, obj, judge)
    assert 0.0 <= rq["score"] <= 1.0
    assert rq["components"]["source_tier_mix"] == 0.85   # (1.0 + 0.7) / 2
    assert rq["components"]["judge_mean"] == 0.8         # 4/5
    assert rq["components"]["dossier_richness"] is not None


def test_research_quality_degrades_when_no_data():
    rq = dr.compute_research_quality(None, None, None)
    assert rq["score"] is None
    assert all(v is None for v in rq["components"].values())


# --- R2-RES-6 completeness probe -------------------------------------------

def test_coverage_gaps_flags_unmapped_entity_and_orphan_fault_line():
    obj = {
        "central_question": "Will TSMC outproduce Intel in 2027?",
        "actors": [{"name": "TSMC", "aliases": ["Taiwan Semiconductor"]}],
        "situation_brief": {
            "fault_lines": [
                "TSMC vs Intel foundry leadership",   # TSMC grounded → not orphan
                "Rivian battery supply disputes",     # neither in cast → orphan
            ],
        },
    }
    gaps = dr.compute_coverage_gaps(obj)
    assert "Intel" in gaps["missing_named_entities"]
    assert "TSMC" not in gaps["missing_named_entities"]
    assert any("Rivian" in fl for fl in gaps["orphan_fault_lines"])
    assert all("TSMC vs Intel" not in fl for fl in gaps["orphan_fault_lines"])


def test_coverage_gaps_empty_safe():
    assert dr.compute_coverage_gaps(None) == {"missing_named_entities": [], "orphan_fault_lines": []}


# --- R2-RES-10 triangulation audit -----------------------------------------

def test_triangulation_flags_single_origin_status():
    contested = [
        {"claim": "X will collapse", "status": "single-origin"},
        {"claim": "Y is contested", "status": "contested"},
    ]
    flagged = dr.audit_triangulation([], contested)
    claims = [f["claim"] for f in flagged]
    assert "X will collapse" in claims
    assert "Y is contested" not in claims


def test_triangulation_supports_guarded_by_independence_signal():
    # No source carries an explicit independent flag → support-map path stays silent.
    sources_no_signal = [{"title": "s1", "supports": ["claim A"]}]
    assert dr.audit_triangulation(sources_no_signal, []) == []
    # With an explicit independence signal, a <=1-independent claim is flagged.
    sources = [
        {"title": "s1", "supports": ["claim A"], "independent": True},
        {"title": "s2", "supports": ["claim B"], "independent": False},
    ]
    flagged = dr.audit_triangulation(sources, [])
    claims = [f["claim"] for f in flagged]
    assert "claim A" in claims and "claim B" in claims  # both rest on <=1 independent origin


# --- R2-RES-11 quantitative reconciliation ---------------------------------

def test_reconcile_quant_emits_contested_and_unit_error():
    quant = [
        {"metric": "TSMC 2026 capex", "value": "52", "unit": "USD billion", "source": "co"},
        {"metric": "tsmc 2026 capex", "value": "54000", "unit": "USD billion", "source": "blog"},
    ]
    extra, unit_errors = dr.reconcile_quantitative(quant)
    assert len(extra) == 1
    assert extra[0]["origin"] == "quant_reconcile"
    assert extra[0]["status"] == "contested"
    assert len(unit_errors) == 1                  # 54000/52 ~= 1038x → ~1000x band
    assert unit_errors[0]["ratio"] > 300


def test_reconcile_quant_agreement_is_noop():
    quant = [
        {"metric": "rate", "value": "5.0", "unit": "%"},
        {"metric": "rate", "value": "5.2", "unit": "%"},   # <10% spread
    ]
    extra, unit_errors = dr.reconcile_quantitative(quant)
    assert extra == [] and unit_errors == []
    assert dr.reconcile_quantitative(None) == ([], [])


def test_reconcile_quant_material_disagreement_without_unit_error():
    quant = [
        {"metric": "share", "value": "30", "unit": "%"},
        {"metric": "share", "value": "45", "unit": "%"},   # 1.5x → contested, not unit error
    ]
    extra, unit_errors = dr.reconcile_quantitative(quant)
    assert len(extra) == 1 and unit_errors == []


# --- R2-RES-4 recency annotation -------------------------------------------

def test_annotate_recency_mutates_rows_and_histograms():
    ref = dt.date(2026, 6, 1)
    rows = [
        {"title": "fresh", "date": "2026-05-01"},   # 31d
        {"title": "recent", "date": "2026-01-01"},  # ~151d
        {"title": "stale", "date": "2024-01-01"},   # >365d
        {"title": "undated"},
    ]
    hist = dr.annotate_recency_rows(rows, ref, 365, date_key="date")
    assert rows[0]["is_stale"] is False and rows[0]["staleness_days"] == 31
    assert rows[2]["is_stale"] is True
    assert "staleness_days" not in rows[3]          # undated rows untouched
    assert hist == {"fresh_le_90": 1, "recent_le_365": 1, "stale_gt_365": 1, "undated": 1, "n_stale": 1}


_LEGACY_RECENCY_KEYS = {"fresh_le_90", "recent_le_365", "stale_gt_365", "undated", "n_stale"}


def test_annotate_recency_legacy_keys_unchanged_without_future_bucket():
    ref = dt.date(2026, 6, 1)
    rows = [{"date": "2026-05-01"}, {"date": "2027-01-01"}, {"title": "undated"}]
    hist = dr.annotate_recency_rows(rows, ref, 365, date_key="date")
    assert set(hist) == _LEGACY_RECENCY_KEYS
    # Legacy semantics kept: a future-dated row has a negative age and counts as fresh.
    assert hist == {"fresh_le_90": 2, "recent_le_365": 0, "stale_gt_365": 0, "undated": 1, "n_stale": 0}
    assert rows[1] == {"date": "2027-01-01", "staleness_days": -214, "is_stale": False}
    assert dr.annotate_recency_rows(None, ref, 365) == dict.fromkeys(_LEGACY_RECENCY_KEYS, 0)


def test_annotate_recency_future_bucket_keeps_future_rows_out_of_fresh():
    ref = dt.date(2026, 6, 1)
    rows = [{"date": "2026-05-01"}, {"as_of_date": "2029-12-31"}, {"date": "2024-01-01"}, {"title": "undated"}]
    hist = dr.annotate_recency_rows(rows, ref, 365, date_key="date", future_bucket=True)
    assert hist == {"fresh_le_90": 1, "recent_le_365": 0, "stale_gt_365": 1, "undated": 1, "n_stale": 1,
                    "future_dated": 1}
    assert rows[1] == {"as_of_date": "2029-12-31", "staleness_days": None, "is_stale": False,
                       "is_future_dated": True}
    # Rows dated on or before the reference date are annotated exactly as before.
    assert rows[0] == {"date": "2026-05-01", "staleness_days": 31, "is_stale": False}
    same_day = [{"date": "2026-06-01"}]
    assert dr.annotate_recency_rows(same_day, ref, 365, future_bucket=True)["fresh_le_90"] == 1
    assert same_day[0] == {"date": "2026-06-01", "staleness_days": 0, "is_stale": False}
    assert dr.annotate_recency_rows(None, ref, 365, future_bucket=True)["future_dated"] == 0


def test_annotate_recency_future_bucket_counts_typed_target_dates():
    """A row typed as_of_is_target holds a target date in as_of_date, and one
    typed published_after_as_of states a publication date after as-of: both
    are future-dated even when that date reads as this year's start or not at
    all."""
    ref = dt.date(2026, 9, 28)
    target = ["as_of_is_target"]
    impossible = ["future_dated_reported", "published_after_as_of"]

    def rows():
        return [{"as_of_date": "2026-Q4", "epistemic_flags": target},    # reads as 2026-01-01
                {"as_of_date": "FY2027", "epistemic_flags": target},     # unreadable here
                {"as_of_date": "2026-Q4"},                                # untyped: legacy reading
                # an actual for the current month: not yet reported, but freshly published
                {"as_of_date": "2026-09", "epistemic_flags": ["future_dated_reported"]},
                # an "actual" dated after as-of: no observation, whatever its date reads as
                {"as_of_date": "2026-Q4", "epistemic_flags": impossible},
                {"as_of_date": "Q4 2026", "epistemic_flags": impossible}]

    typed = rows()
    hist = dr.annotate_recency_rows(typed, ref, 365, date_key="as_of_date", future_bucket=True)
    assert hist == {"fresh_le_90": 1, "recent_le_365": 1, "stale_gt_365": 0, "undated": 0, "n_stale": 0,
                    "future_dated": 4}
    assert [row.get("is_future_dated") for row in typed] == [True, True, None, None, True, True]
    assert typed[1] == {"as_of_date": "FY2027", "epistemic_flags": target, "staleness_days": None,
                        "is_stale": False, "is_future_dated": True}
    assert typed[4] == {"as_of_date": "2026-Q4", "epistemic_flags": impossible, "staleness_days": None,
                        "is_stale": False, "is_future_dated": True}
    # Without the keyword the flags are ignored: the legacy histogram and annotations.
    legacy = rows()
    assert dr.annotate_recency_rows(legacy, ref, 365, date_key="as_of_date") == {
        "fresh_le_90": 1, "recent_le_365": 3, "stale_gt_365": 0, "undated": 2, "n_stale": 0}
    assert "is_future_dated" not in legacy[0] and legacy[0]["staleness_days"] == 270
    assert legacy[4]["staleness_days"] == 270 and "is_future_dated" not in legacy[4]


# --- R2-RES-9 gap threading -------------------------------------------------

def test_parse_gaps_from_notes_lifts_gap_section_only():
    notes = (
        "## Evidence gathered\n- not a gap\n\n"
        "## Gaps to carry into the next pass\n"
        "- HBM yield data for 2027\n"
        "* Intel 18A defect density\n\n"
        "## Other\n- ignore me\n"
    )
    gaps = dr.parse_gaps_from_notes(notes)
    assert gaps == ["HBM yield data for 2027", "Intel 18A defect density"]
    assert dr.parse_gaps_from_notes("") == []


def test_deep_phase_prompt_threads_prior_gaps():
    phase = dr.DEEP_RESEARCH_PHASES[0]
    base = dr.build_deep_phase_prompt("Q?", phase, 1, 5, None)
    assert "UNRESOLVED GAPS" not in base
    threaded = dr.build_deep_phase_prompt("Q?", phase, 1, 5, None, prior_gaps=["close X", "close Y"])
    assert "UNRESOLVED GAPS" in threaded and "close X" in threaded


def test_merge_gaps_dedups_case_insensitive_and_caps():
    merged = dr._merge_gaps(["a", "b"], ["B", "c"], cap=3)
    assert merged == ["a", "b", "c"]


# --- RESEARCH-4 synthesis cap ----------------------------------------------

def test_synthesis_cap_reserves_profile_output_and_env_override(monkeypatch):
    monkeypatch.delenv("SYNTHESIS_MAX_CONTEXT_CHARS", raising=False)
    monkeypatch.setenv("SYNTHESIS_CONTEXT_WINDOW_TOKENS", "200000")
    monkeypatch.setenv("SYNTHESIS_OUTPUT_RESERVE_TOKENS", "64000")
    monkeypatch.setenv("SYNTHESIS_PROMPT_OVERHEAD_TOKENS", "8000")
    monkeypatch.setenv("SYNTHESIS_CHARS_PER_TOKEN", "3.2")
    assert dr._synthesis_context_cap("profile-name-is-not-a-heuristic") == 409600
    monkeypatch.setenv("SYNTHESIS_MAX_CONTEXT_CHARS", "123")
    assert dr._synthesis_context_cap("claude") == 123  # explicit override wins
    assert dr._synthesis_context_cap(
        "claude", extra_prompt_chars=23) == 100  # lazy contract is charged


# --- RESEARCH-5 extraction excerpt cap -------------------------------------

def test_extraction_report_excerpt_cap(monkeypatch):
    monkeypatch.delenv("EXTRACTION_REPORT_EXCERPT_CHARS", raising=False)
    big = "Z" * 1000
    assert dr._extraction_report_excerpt(big) == big       # 0 → no-op
    monkeypatch.setenv("EXTRACTION_REPORT_EXCERPT_CHARS", "100")
    capped = dr._extraction_report_excerpt(big)
    assert capped.startswith("Z" * 100) and "truncated for extraction" in capped


# --- R2-RES-12 / RESEARCH-5 extraction prompt schema -----------------------

def test_extraction_prompt_source_diversity_and_light(monkeypatch):
    monkeypatch.delenv("RESEARCH_SOURCE_DIVERSITY", raising=False)
    p_div = dr.build_extraction_prompt(None, source_diversity=True, evidence_grading=True, forecast_inputs=False)
    assert '"jurisdiction"' in p_div and '"lang"' in p_div
    p_off = dr.build_extraction_prompt(None, source_diversity=False, evidence_grading=False, forecast_inputs=False)
    assert '"jurisdiction"' not in p_off


# --- R2-RES-8 judge source signal ------------------------------------------

def test_dossier_source_signal_and_judge_prompt_injection():
    dossier = "Per S1 filings and S2 reporting, see https://x.com and https://y.gov"
    sig = dr._dossier_source_signal(dossier)
    assert "S1=1" in sig and "S2=1" in sig and "2 cited links" in sig
    p = dr.build_judge_prompt("Q", None, sig)
    assert sig in p
    # No signal → prompt unchanged vs the 2-arg form.
    assert dr.build_judge_prompt("Q", None) == dr.build_judge_prompt("Q", None, "")
