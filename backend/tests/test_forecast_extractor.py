"""Golden tests for structured forecast extraction + citation audit (EXECPLAN2 I-3-0/I-3-1)."""

import json
from datetime import datetime, timezone

import pytest

from app.services.forecast_extractor import (
    _binary_quality,
    _normalize_binaries,
    anchor_binaries_to_markets,
    apply_horizon_consistency,
    audit_citation_grounding,
    audit_market_anchor_integrity,
    audit_proposition_consistency,
    audit_scenario_contract,
    build_market_comparison,
    derive_forecast_spine,
    enforce_market_divergence,
    extract_binary_forecasts,
    extract_structured_forecast,
    parse_requirement_years,
    reconcile_forecast_contract,
    render_binary_forecasts_block,
    render_forecast_spine_block,
    render_resolution_block,
    self_critique_forecast,
    slice_head_tail,
    validate_citation_markers,
)
from app.services.ensemble import pool_binary_forecasts
from app.utils import prediction_markets
from tests.conftest import FakeLLMClient


def _scenario_issue_codes(audit):
    return {example["code"] for example in audit["examples"]}


def test_audit_citation_grounding_counts_and_coverage():
    md = (
        "# 标题\n"
        "市场份额将达到 45% [S1]。\n"          # cited quantitative
        "营收增长 30%。\n"                      # uncited quantitative
        "到 2030年 格局重塑【S3】。\n"          # cited (CJK marker + year)
        "这是一句没有数字的话。\n"             # not quantitative
    )
    a = audit_citation_grounding(md)
    assert a["quantitative_claims"] == 3
    assert a["cited"] == 2
    assert a["coverage"] == round(2 / 3, 3)
    assert any("营收增长 30%" in s for s in a["unsupported_samples"])


def test_audit_empty_is_full_coverage():
    assert audit_citation_grounding("no numbers here")["coverage"] == 1.0


def test_citation_audit_separates_authored_forecast_contract_from_source_claims():
    md = (
        "# Forecast\n\n"
        "## Part 1 — Binary Forecasts\n\n"
        "| F1 | Authored outcome | 72% | Resolve above 40% by 2030 |\n\n"
        "## Analysis\n\n"
        "Official adoption reached 55.6% in 2025 [S1].\n\n"
        "Unsupported market share reached 99% in 2027.\n\n"
        "## How to Verify This Forecast (Resolution Criteria & Indicators)\n\n"
        "Resolve the authored scenario at a 90% threshold by 2035.\n"
    )
    audit = audit_citation_grounding(
        md,
        index_map={"S1": {"title": "Official adoption"}},
        exclude_authored_forecasts=True,
    )

    assert audit["quantitative_claims"] == 2
    assert audit["resolved_cited"] == 1
    assert audit["resolved_coverage"] == 0.5
    assert audit["excluded_authored_forecast_claims"] == 3


def test_citation_audit_counts_each_sentence_and_table_cell_independently():
    md = (
        "# Evidence\n\n"
        "Official adoption reached 55.6% in 2025. [S1] "
        "Unsupported lunar adoption reached 99% in 2027.\n\n"
        "| Metric | 2025 actual | 2026 forecast |\n"
        "|---|---:|---:|\n"
        "| Official adoption | 55.6%. [S1] | 99% |\n"
    )

    audit = audit_citation_grounding(md, index_map={"S1": {"title": "Official"}})

    # Numeric table headers are labels, not factual claim units. The two prose
    # sentences and two data cells are each audited independently.
    assert audit["quantitative_claims"] == 4
    assert audit["resolved_cited"] == 2
    assert audit["resolved_coverage"] == 0.5
    assert sum("99%" in sample for sample in audit["unsupported_samples"]) == 2


def test_citation_audit_uses_exact_authored_boundaries_not_arbitrary_part_one():
    md = (
        "# Forecast\n\n"
        "## Part 1 — Market Evidence\n\n"
        "Unsupported market evidence reached 99% in 2027.\n\n"
        "<!-- binary-forecast-block:start -->\n"
        "## Part 1 — Binary Forecasts\n\n"
        "| F1 | Authored outcome | 72% | Resolve above 40% by 2030 |\n"
        "<!-- binary-forecast-block:end -->\n\n"
        "## Analysis\n\n"
        "Official adoption reached 55.6% in 2025 [S1].\n"
    )

    audit = audit_citation_grounding(
        md,
        index_map={"S1": {"title": "Official"}},
        exclude_authored_forecasts=True,
    )

    assert audit["quantitative_claims"] == 2
    assert audit["resolved_cited"] == 1
    assert audit["resolved_coverage"] == 0.5
    assert audit["excluded_authored_forecast_claims"] == 2


def test_citation_scanners_require_matching_fence_delimiters():
    md = (
        "```text\n"
        "Inside code reached 99% [S9].\n"
        "~~~\n"
        "Still inside code reached 88% [S8].\n"
        "```\n"
        "Outside evidence reached 77% [S1].\n"
    )

    audit = audit_citation_grounding(md, index_map={"S1": {"title": "Official"}})
    markers = validate_citation_markers(md, {"S1": {"title": "Official"}})

    assert audit["quantitative_claims"] == 1
    assert audit["resolved_cited"] == 1
    assert audit["ignored_fenced_quantitative_lines"] == 2
    assert markers["order"] == ["S1"]
    assert markers["dangling"] == []


def test_claim_splitter_keeps_dotted_initialism_with_its_sentence():
    md = (
        "U.S. EV adoption reached 55.6%. [S1] "
        "Unsupported lunar adoption reached 99%."
    )

    audit = audit_citation_grounding(md, index_map={"S1": {"title": "Official"}})

    assert audit["quantitative_claims"] == 2
    assert audit["resolved_cited"] == 1
    assert audit["resolved_coverage"] == 0.5


@pytest.mark.parametrize(
    "tail",
    [
        "Unsupported lunar adoption reached 99%.",
        "“Unsupported lunar adoption reached 99%.“",
        "(Unsupported lunar adoption reached 99%.)",
        "2027 lunar adoption reached 99%.",
        "[Unsupported lunar adoption](https://example.org) reached 99%.",
        "unsupported lunar adoption reached 99%.",
    ],
)
def test_post_punctuation_citation_never_covers_wrapped_next_claim(tail):
    md = f"Official adoption reached 55.6%. [S12] {tail}"

    audit = audit_citation_grounding(md, index_map={"S12": {"title": "Official"}})

    assert audit["quantitative_claims"] == 2
    assert audit["resolved_cited"] == 1
    assert audit["resolved_coverage"] == 0.5


def test_semicolon_separates_citation_ownership():
    md = "Official adoption reached 55.6% [S1]; Unsupported adoption reached 99%."

    audit = audit_citation_grounding(md, index_map={"S1": {"title": "Official"}})

    assert audit["quantitative_claims"] == 2
    assert audit["resolved_cited"] == 1
    assert audit["resolved_coverage"] == 0.5


def test_unclosed_authored_marker_disables_marker_based_exclusion():
    md = (
        "<!-- binary-forecast-block:start -->\n"
        "## Part 1 — Binary Forecasts\n\n"
        "| F1 | Authored outcome | 72% | Resolve above 40% by 2030 |\n\n"
        "## Analysis\n\n"
        "Unsupported market evidence reached 99% in 2027.\n"
    )

    audit = audit_citation_grounding(
        md,
        index_map={},
        exclude_authored_forecasts=True,
    )

    assert audit["authored_forecast_markers_valid"] is False
    assert audit["quantitative_claims"] == 1
    assert audit["resolved_cited"] == 0
    assert audit["resolved_coverage"] == 0.0


def test_fenced_literal_end_marker_cannot_balance_unclosed_authored_block():
    md = (
        "<!-- binary-forecast-block:start -->\n"
        "## Part 1 — Binary Forecasts\n\n"
        "| F1 | Authored outcome | 72% | Resolve above 40% by 2030 |\n\n"
        "```text\n"
        "<!-- binary-forecast-block:end -->\n"
        "```\n"
        "## Analysis\n\n"
        "Unsupported market evidence reached 99% in 2027.\n"
    )

    audit = audit_citation_grounding(
        md,
        index_map={},
        exclude_authored_forecasts=True,
    )

    assert audit["authored_forecast_markers_valid"] is False
    assert audit["quantitative_claims"] == 1
    assert audit["resolved_coverage"] == 0.0


def test_scenario_contract_accepts_absent_or_valid_conservative_partition():
    assert audit_scenario_contract({}) == {
        "valid": True,
        "issue_count": 0,
        "issues": [],
        "examples": [],
    }

    audit = audit_scenario_contract({
        "scenarios": [
            {
                "name": "Lower band",
                "probability": 0.30,
                "resolution_criteria": (
                    "Global revenue between $1.0T and $1.2T by 2030"
                ),
                "summary": (
                    "Scenario probability is 30%. Product mix is 40% + 30%."
                ),
                "critique_note": "Adjusted probability to 30% after review.",
            },
            {
                "name": "Upper band",
                "probability": 0.50,
                "resolution_criteria": "Global revenue: $1.3T-$1.5T by 2030",
                "summary": (
                    "Probability of the joint event is computed as 40% + 30% = 70%."
                ),
            },
            {
                "name": "All else",
                "probability": 0.20,
                "resolution_criteria": "All other measurable outcomes by 2030",
            },
        ],
    })
    assert audit["valid"] is True
    assert audit["issue_count"] == 0


def test_scenario_contract_rejects_non_list_and_empty_scenarios():
    not_list = audit_scenario_contract({"scenarios": {"name": "Other"}})
    empty = audit_scenario_contract({"scenarios": []})

    assert not_list["valid"] is False
    assert _scenario_issue_codes(not_list) == {"scenarios_not_list"}
    assert empty["valid"] is False
    assert _scenario_issue_codes(empty) == {"scenarios_empty"}


def test_scenario_contract_rejects_row_schema_and_probability_defects():
    audit = audit_scenario_contract({
        "scenarios": [
            {
                "name": "Base case",
                "probability": 0.40,
                "resolution_criteria": "Revenue is at least $1.0T by 2030",
            },
            {
                "name": " base CASE ",
                "probability": "0.30",
                "resolution_criteria": "Revenue is below $1.0T by 2030",
            },
            {
                "name": "Other",
                "probability": 10 ** 400,
                "resolution_criteria": "",
            },
        ],
    })

    assert audit["valid"] is False
    assert _scenario_issue_codes(audit) >= {
        "duplicate_scenario_name",
        "probability_not_numeric",
        "probability_out_of_range",
        "resolution_criteria_missing",
    }


def test_scenario_contract_rejects_bad_sum_and_missing_residual_bin():
    audit = audit_scenario_contract({
        "scenarios": [
            {
                "name": "Mother company expansion",
                "probability": 0.40,
                "resolution_criteria": "Revenue exceeds $1.2T by 2030",
            },
            {
                "name": "Contested election",
                "probability": 0.40,
                "resolution_criteria": "Revenue remains below $1.0T by 2030",
            },
        ],
    })

    assert _scenario_issue_codes(audit) >= {
        "probability_sum",
        "residual_scenario_missing",
    }


def test_named_base_case_is_not_a_residual_bin():
    audit = audit_scenario_contract({
        "scenarios": [
            {
                "name": "Three-bloc Fragmentation (Base Case)",
                "probability": 0.60,
                "resolution_criteria": "Fragmentation criteria are met by 2035",
            },
            {
                "name": "Accelerated convergence",
                "probability": 0.40,
                "resolution_criteria": "Convergence criteria are met by 2035",
            },
        ],
    })

    assert "residual_scenario_missing" in _scenario_issue_codes(audit)


def test_self_critique_preserves_unallocated_mass_as_residual_scenario():
    forecast = {
        "headline": "Global EV pathways",
        "horizon": "2035-12-31",
        "confidence": "medium",
        "confidence_rationale": "Initial rationale.",
        "scenarios": [
            {"name": "Fragmentation", "probability": 0.50,
             "resolution_criteria": "Fragmentation criteria are met by 2035"},
            {"name": "Convergence", "probability": 0.30,
             "resolution_criteria": "Convergence criteria are met by 2035"},
            {"name": "Industrial retreat", "probability": 0.20,
             "resolution_criteria": "Retreat criteria are met by 2035"},
        ],
    }
    critique = {
        "confidence": "medium",
        "confidence_rationale": "Four substantive scenarios sum to 95%.",
        "scenarios": [
            {"name": "Fragmentation", "probability": 0.42,
             "resolution_criteria": "Fragmentation criteria are met by 2035",
             "critique_note": "Probability reduced from 0.50 to 0.42."},
            {"name": "Convergence", "probability": 0.12,
             "resolution_criteria": "Convergence criteria are met by 2035",
             "critique_note": "Probability reduced from 0.30 to 0.12."},
            {"name": "Industrial retreat", "probability": 0.15,
             "resolution_criteria": "Retreat criteria are met by 2035",
             "critique_note": "Probability reduced from 0.20 to 0.15."},
        ],
    }

    out = self_critique_forecast(
        forecast, FakeLLMClient(json_responses=[critique]),
    )
    probabilities = {row["name"]: row["probability"] for row in out["scenarios"]}

    assert probabilities == {
        "Fragmentation": 0.42,
        "Convergence": 0.12,
        "Industrial retreat": 0.15,
        "Other / Status Quo": 0.31,
    }
    assert out["residual_scenario_added"] is True
    assert "complete 100% partition" in out["confidence_rationale"]
    assert out["confidence_rationale_detail"] == "Four substantive scenarios sum to 95%."
    assert audit_scenario_contract(out)["valid"] is True


def test_self_critique_reserves_residual_and_synchronizes_scaled_notes():
    forecast = {
        "headline": "Two named paths",
        "horizon": "2030",
        "confidence": "medium",
        "scenarios": [
            {"name": "Path A", "probability": 0.80,
             "resolution_criteria": "Path A resolves by 2030"},
            {"name": "Path B", "probability": 0.20,
             "resolution_criteria": "Path B resolves by 2030"},
        ],
    }
    critique = {
        "scenarios": [
            {"name": "Path A", "probability": 0.55,
             "resolution_criteria": "Path A resolves by 2030",
             "critique_note": "Probability reduced to 0.55."},
            {"name": "Path B", "probability": 0.45,
             "resolution_criteria": "Path B resolves by 2030",
             "critique_note": "Probability increased to 0.45."},
        ],
    }

    out = self_critique_forecast(
        forecast, FakeLLMClient(json_responses=[critique]),
    )
    residual = next(row for row in out["scenarios"] if row["name"] == "Other / Status Quo")

    assert residual["probability"] == 0.03
    assert abs(sum(row["probability"] for row in out["scenarios"]) - 1.0) < 1e-6
    path_a = next(row for row in out["scenarios"] if row["name"] == "Path A")
    path_b = next(row for row in out["scenarios"] if row["name"] == "Path B")
    assert "critique_note_detail" in path_a  # 1.65pp move exceeds contract tolerance
    assert "critique_note_detail" not in path_b  # 1.35pp move is within tolerance
    assert audit_scenario_contract(out)["valid"] is True


@pytest.mark.parametrize("malformed_scenarios", [
    "not-a-list",
    [
        {"name": "Path A", "probability": 0.50,
         "resolution_criteria": "Path A resolves by 2030"},
        "not-an-object",
    ],
    [
        {"name": "Path A", "probability": "0.50",
         "resolution_criteria": "Path A resolves by 2030"},
        {"name": "Path B", "probability": 0.50,
         "resolution_criteria": "Path B resolves by 2030"},
    ],
    [
        {"name": "Path A", "probability": float("nan"),
         "resolution_criteria": "Path A resolves by 2030"},
        {"name": "Path B", "probability": 0.50,
         "resolution_criteria": "Path B resolves by 2030"},
    ],
    [
        {"name": "Path A", "probability": float("inf"),
         "resolution_criteria": "Path A resolves by 2030"},
        {"name": "Path B", "probability": 0.50,
         "resolution_criteria": "Path B resolves by 2030"},
    ],
    [
        {"name": "Path A", "probability": 0.80,
         "resolution_criteria": "Path A resolves by 2030"},
        {"name": "Path B", "probability": 0.70,
         "resolution_criteria": "Path B resolves by 2030"},
    ],
    [
        {"name": "Path A", "probability": True,
         "resolution_criteria": "Path A resolves by 2030"},
        {"name": "Other / Status Quo", "probability": 0.50,
         "resolution_criteria": "All other outcomes by 2030"},
    ],
    [
        {"name": "Path A", "probability": 0.50,
         "resolution_criteria": ""},
        {"name": "Path B", "probability": 0.50,
         "resolution_criteria": "Path B resolves by 2030"},
    ],
])
def test_self_critique_rejects_malformed_scenario_payloads(malformed_scenarios):
    forecast = {
        "headline": "Original forecast",
        "horizon": "2030",
        "confidence": "medium",
        "scenarios": [
            {"name": "Original A", "probability": 0.60,
             "resolution_criteria": "Original A resolves by 2030"},
            {"name": "Original B", "probability": 0.40,
             "resolution_criteria": "Original B resolves by 2030"},
        ],
    }

    out = self_critique_forecast(
        forecast,
        FakeLLMClient(json_responses=[{"scenarios": malformed_scenarios}]),
    )

    assert out is forecast
    assert "critiqued" not in out


def test_humility_rebalance_closes_probability_rounding_on_residual():
    forecast = {
        "headline": "Five paths",
        "horizon": "2030",
        "confidence": "medium",
        "scenarios": [
            {"name": "A", "probability": 0.63,
             "resolution_criteria": "A resolves by 2030"},
            {"name": "B", "probability": 0.12,
             "resolution_criteria": "B resolves by 2030"},
            {"name": "C", "probability": 0.10,
             "resolution_criteria": "C resolves by 2030"},
            {"name": "D", "probability": 0.08,
             "resolution_criteria": "D resolves by 2030"},
            {"name": "Other / Status Quo", "probability": 0.07,
             "resolution_criteria": "All other outcomes by 2030"},
        ],
    }
    critique = {
        "scenarios": [
            {"name": "A", "probability": 0.91,
             "resolution_criteria": "A resolves by 2030"},
            {"name": "B", "probability": 0.031,
             "resolution_criteria": "B resolves by 2030"},
            {"name": "C", "probability": 0.024,
             "resolution_criteria": "C resolves by 2030"},
            {"name": "D", "probability": 0.019,
             "resolution_criteria": "D resolves by 2030"},
            {"name": "Other / Status Quo", "probability": 0.016,
             "resolution_criteria": "All other outcomes by 2030"},
        ],
    }

    out = self_critique_forecast(
        forecast, FakeLLMClient(json_responses=[critique]),
    )

    assert max(row["probability"] for row in out["scenarios"]) == 0.63
    assert round(sum(row["probability"] for row in out["scenarios"]), 4) == 1.0
    assert audit_scenario_contract(out)["valid"] is True


def test_scenario_contract_rejects_stale_critique_and_bad_percentage_total():
    audit = audit_scenario_contract({
        "headline": (
            "The scenario weights are 40%, 30%, and 20%, totaling 90%."
        ),
        "confidence_rationale": "Scenario probabilities sum to 90%.",
        "scenarios": [
            {
                "name": "Primary",
                "probability": 0.50,
                "resolution_criteria": "Revenue exceeds $1.2T by 2030",
                "critique_note": (
                    "The probability was reduced from 50% to 27%. "
                    "Scenario probability allocation: 40% + 30% + 20% = 90%."
                ),
            },
            {
                "name": "Other / status quo",
                "probability": 0.50,
                "resolution_criteria": "All other measurable outcomes by 2030",
                "summary": "情景概率为40%、30%、20%，合计90%。",
            },
        ],
    })

    assert _scenario_issue_codes(audit) >= {
        "stale_critique_probability",
        "percentage_allocation_arithmetic",
    }
    percentage_findings = [
        example for example in audit["examples"]
        if example["code"] == "percentage_allocation_arithmetic"
    ]
    assert {finding["kind"] for finding in percentage_findings} >= {
        "stated_total",
        "allocation_total",
    }
    assert any("scenario weights" in finding["excerpt"].lower()
               for finding in percentage_findings)
    assert any("情景概率" in finding["excerpt"] for finding in percentage_findings)

    direct_note = audit_scenario_contract({
        "scenarios": [
            {
                "name": "Primary",
                "probability": 0.50,
                "resolution_criteria": "Revenue exceeds $1.2T by 2030",
                "critique_note": "Probability: 27% after review.",
            },
            {
                "name": "Other",
                "probability": 0.50,
                "resolution_criteria": "All other outcomes by 2030",
                "critique_note": (
                    "Base probability: 20%. 更新为2家公司进入决赛。"
                ),
            },
        ],
    })
    stale = [
        example for example in direct_note["examples"]
        if example["code"] == "stale_critique_probability"
    ]
    assert len(stale) == 1
    assert stale[0]["scenario"] == "Primary"


def test_scenario_contract_range_overlap_requires_same_metric_and_positive_width():
    overlap = audit_scenario_contract({
        "scenarios": [
            {
                "name": "Revenue lower",
                "probability": 0.30,
                "resolution_criteria": "Global revenue: $1.0T-$1.3T by 2030",
            },
            {
                "name": "Revenue upper",
                "probability": 0.30,
                "resolution_criteria": "Global revenue: $1.2T-$1.5T by 2030",
            },
            {
                "name": "Margin band",
                "probability": 0.20,
                "resolution_criteria": "Operating margin: $1.2T-$1.5T by 2030",
            },
            {
                "name": "Other",
                "probability": 0.20,
                "resolution_criteria": "All other measurable outcomes by 2030",
            },
        ],
    })
    overlap_examples = [
        example for example in overlap["examples"]
        if example["code"] == "overlapping_numeric_ranges"
    ]
    assert len(overlap_examples) == 1
    assert overlap_examples[0]["metric"] == "global revenue"

    touching = audit_scenario_contract({
        "scenarios": [
            {
                "name": "Lower",
                "probability": 0.40,
                "resolution_criteria": "Global revenue: $1.0T-$1.2T by 2030",
            },
            {
                "name": "Upper",
                "probability": 0.40,
                "resolution_criteria": "Global revenue: $1.2T-$1.4T by 2030",
            },
            {
                "name": "Other",
                "probability": 0.20,
                "resolution_criteria": "All other measurable outcomes by 2030",
            },
        ],
    })
    assert touching["valid"] is True

    scoped = audit_scenario_contract({
        "scenarios": [
            {
                "name": "Product A band",
                "probability": 0.40,
                "resolution_criteria": "Revenue: $1.0T-$1.3T for Product A by 2030",
            },
            {
                "name": "Product B band",
                "probability": 0.40,
                "resolution_criteria": "Revenue: $1.2T-$1.5T for Product B by 2030",
            },
            {
                "name": "Other",
                "probability": 0.20,
                "resolution_criteria": "All other outcomes by 2030",
            },
        ],
    })
    assert scoped["valid"] is True

    leading_date = audit_scenario_contract({
        "scenarios": [
            {
                "name": "Lower",
                "probability": 0.40,
                "resolution_criteria": (
                    "By 2030, global revenue between $1.0T and $1.3T"
                ),
            },
            {
                "name": "Upper",
                "probability": 0.40,
                "resolution_criteria": (
                    "By 2030, global revenue between $1.2T and $1.5T"
                ),
            },
            {
                "name": "Other",
                "probability": 0.20,
                "resolution_criteria": "All other outcomes by 2030",
            },
        ],
    })
    assert "overlapping_numeric_ranges" in _scenario_issue_codes(leading_date)

    chinese = audit_scenario_contract({
        "scenarios": [
            {
                "name": "低位",
                "probability": 0.40,
                "resolution_criteria": "到2030年，全球营收：$1.0T-$1.3T",
            },
            {
                "name": "高位",
                "probability": 0.40,
                "resolution_criteria": "到2030年，全球营收：$1.2T-$1.5T",
            },
            {
                "name": "其他",
                "probability": 0.20,
                "resolution_criteria": "到2030年的所有其他结果",
            },
        ],
    })
    chinese_overlaps = [
        example for example in chinese["examples"]
        if example["code"] == "overlapping_numeric_ranges"
    ]
    assert len(chinese_overlaps) == 1
    assert chinese_overlaps[0]["metric"] == "全球营收"


def test_scenario_contract_audit_is_strict_json_serializable():
    audit = audit_scenario_contract({
        "scenarios": [
            {
                "name": "Unbounded lower",
                "probability": float("nan"),
                "resolution_criteria": "Global revenue above $1.0T by 2030",
            },
            {
                "name": "Unbounded upper",
                "probability": 0.40,
                "resolution_criteria": "Global revenue above $1.2T by 2030",
            },
            {
                "name": "Other",
                "probability": 0.60,
                "resolution_criteria": "All other outcomes by 2030",
            },
        ],
    })

    assert _scenario_issue_codes(audit) >= {
        "probability_not_numeric",
        "overlapping_numeric_ranges",
    }
    overlap = next(
        example for example in audit["examples"]
        if example["code"] == "overlapping_numeric_ranges"
    )
    assert overlap["overlap"] == [1.2, None]
    assert json.loads(json.dumps(audit, allow_nan=False))["valid"] is False


def test_scenario_contract_probability_sum_tolerance_includes_boundary():
    at_boundary = audit_scenario_contract({
        "scenarios": [
            {
                "name": "Primary",
                "probability": 0.500,
                "resolution_criteria": "Primary outcome is recorded by 2030",
            },
            {
                "name": "Other",
                "probability": 0.485,
                "resolution_criteria": "All other outcomes by 2030",
            },
        ],
    })
    outside = audit_scenario_contract({
        "scenarios": [
            {
                "name": "Primary",
                "probability": 0.500,
                "resolution_criteria": "Primary outcome is recorded by 2030",
            },
            {
                "name": "Other",
                "probability": 0.484,
                "resolution_criteria": "All other outcomes by 2030",
            },
        ],
    })

    assert at_boundary["valid"] is True
    assert "probability_sum" in _scenario_issue_codes(outside)


def test_scenario_contract_enforces_two_to_five_rows_and_nested_json_safety():
    six_rows = [
        {
            "name": f"Case {index}" if index < 5 else "Other",
            "probability": 1 / 6,
            "resolution_criteria": f"Outcome bucket {index} is observed.",
        }
        for index in range(6)
    ]
    too_many = audit_scenario_contract({"scenarios": six_rows})
    nested_nonfinite = audit_scenario_contract({
        "scenarios": [
            {
                "name": "Primary",
                "probability": [float("nan")],
                "resolution_criteria": "Primary outcome is observed.",
            },
            {
                "name": "Other",
                "probability": 1.0,
                "resolution_criteria": "All other outcomes are observed.",
            },
        ]
    })

    assert "scenario_count" in _scenario_issue_codes(too_many)
    assert too_many["valid"] is False
    assert json.loads(json.dumps(nested_nonfinite, allow_nan=False))["valid"] is False
    assert nested_nonfinite["examples"][0]["value"] == ["nan"]


def test_extract_structured_forecast_normalizes_probabilities():
    fake = FakeLLMClient(json_responses=[{
        "headline": "存储芯片三强争霸",
        "horizon": "2030",
        "scenarios": [
            {"name": "三星领先", "probability": 3, "summary": "...", "key_drivers": ["HBM"],
             "resolution_criteria": "2030 年三星 DRAM 份额>40%"},
            {"name": "格局僵持", "probability": 1, "summary": "...", "key_drivers": [],
             "resolution_criteria": "无单一厂商>40%"},
        ],
        "key_uncertainties": ["出口管制"],
        "confidence": "medium",
    }])
    out = extract_structured_forecast("some report markdown", fake)
    probs = [s["probability"] for s in out["scenarios"]]
    assert abs(sum(probs) - 1.0) < 1e-6      # normalized to sum 1
    assert probs[0] == 0.75 and probs[1] == 0.25
    assert out["schema_version"] == 1
    assert out["confidence"] == "medium"
    assert fake.calls and fake.calls[0]["kind"] == "chat_json"


def test_extract_handles_garbage_reply():
    fake = FakeLLMClient(json_responses=[{"nonsense": True}])
    out = extract_structured_forecast("x", fake)
    assert out["scenarios"] == []
    assert out["confidence"] == "medium"  # safe default


# ----------------------------------------------- NEXTSTEPS P0-1: forecast spine
def test_derive_forecast_spine_from_signals_not_prose():
    fake = FakeLLMClient(json_responses=[{
        "headline": "X",
        "horizon": "2030",
        "scenarios": [
            {"name": "情景A", "probability": 2, "resolution_criteria": "到2030 A>50%"},
            {"name": "维持现状", "probability": 2, "resolution_criteria": "无变化"},
        ],
        "confidence": "high",
    }])
    out = derive_forecast_spine(
        fake, central_question="谁会赢", horizon="2030",
        situation_brief="某态势简报",
        forecast_inputs="参考类基率: 历史延续率 70%", signal_pack="Top actor: NVIDIA",
    )
    assert out["derived_from"] == "spine"
    probs = [s["probability"] for s in out["scenarios"]]
    assert abs(sum(probs) - 1.0) < 1e-6 and probs == [0.5, 0.5]
    # the spine prompt is seeded by SIGNALS (inputs + question), not finished prose
    msg = fake.calls[0]["messages"][0]["content"]
    assert "参考类基率" in msg and "Top actor" in msg and "谁会赢" in msg


def test_render_forecast_spine_block_empty_when_no_scenarios():
    assert render_forecast_spine_block(None) == ""
    assert render_forecast_spine_block({"scenarios": []}) == ""


def test_render_forecast_spine_block_lists_scenarios_with_pct():
    block = render_forecast_spine_block({
        "headline": "核心结论X", "horizon": "2030", "confidence": "medium",
        "scenarios": [
            {"name": "情景A", "probability": 0.6, "resolution_criteria": "A>50%"},
            {"name": "维持现状", "probability": 0.4, "resolution_criteria": "无变化"},
        ],
    })
    assert "预测骨架" in block
    assert "60%" in block and "情景A" in block
    assert "40%" in block and "维持现状" in block
    assert "判定" in block


# ------------------------------------------ NEXTSTEPS P2-2: resolution section
def test_render_resolution_block_lists_criteria_and_indicators():
    fc = {"scenarios": [
        {"name": "情景A", "probability": 0.6, "resolution_criteria": "2030 A 份额>50%"},
        {"name": "维持现状", "probability": 0.4, "resolution_criteria": "无重大变化"},
    ]}
    inds = [{"indicator": "DRAM 份额", "date_or_trigger": "2030Q4", "discriminates": "情景A"}]
    block = render_resolution_block(fc, inds)
    assert "如何验证本预测" in block
    assert "情景A" in block and "2030 A 份额>50%" in block
    assert "DRAM 份额" in block and "2030Q4" in block          # indicator table


def test_render_resolution_block_empty_without_scenarios():
    assert render_resolution_block(None) == ""
    assert render_resolution_block({"scenarios": []}) == ""


# ---------------------------------------- RQ-6: requirement-horizon consistency
def _binaries(*years):
    return [{"id": f"F{i}", "statement": f"Event {i} happens by {y}",
             "probability": 0.7, "horizon_year": y}
            for i, y in enumerate(years, start=1)]


def test_parse_requirement_years_filters_historical_context():
    txt = "Since the 2008 crisis tariffs rose. Forecast the November 2026 US midterm elections."
    assert parse_requirement_years(txt, now_year=2026) == [2026]   # 2008 = context, not a target
    assert parse_requirement_years("no target date given", now_year=2026) == []
    assert parse_requirement_years(None, now_year=2026) == []


def test_horizon_mismatch_flag_merges_into_quality():
    fc = {"binary_forecasts": _binaries(2028, 2028),
          "quality": {"vague_criteria": ["X"]}}
    out = apply_horizon_consistency(fc, "Forecast the 2026 US midterm elections.", now_year=2026)
    hm = out["quality"]["horizon_mismatch"]
    assert hm["requirement_years"] == [2026]
    assert hm["binary_years"] == [2028]
    assert "no overlap" in hm["detail"]
    assert out["quality"]["vague_criteria"] == ["X"]   # merged, never overwritten


def test_horizon_year_read_from_statement_when_field_missing():
    fc = {"binary_forecasts": [{"id": "F1", "statement": "Tariffs exceed 10% by 2028",
                                "probability": 0.6, "horizon_year": None}]}
    out = apply_horizon_consistency(fc, "the 2026 midterms", now_year=2026)
    assert out["quality"]["horizon_mismatch"]["binary_years"] == [2028]


def test_horizon_overlap_or_unparseable_adds_no_flag():
    # any overlap between brief years and binary resolution years → consistent, untouched
    out = apply_horizon_consistency({"binary_forecasts": _binaries(2026, 2028)},
                                    "the 2026 midterms", now_year=2026)
    assert "quality" not in out
    # brief without a parseable target year → no flag (degrade-safe)
    assert "quality" not in apply_horizon_consistency(
        {"binary_forecasts": _binaries(2028)}, "no target date given", now_year=2026)
    # no binaries / no binary-side years → no flag
    assert "quality" not in apply_horizon_consistency(
        {"binary_forecasts": []}, "by 2026", now_year=2026)


def test_horizon_check_disabled_by_flag(monkeypatch):
    from app.config import Config
    monkeypatch.setattr(Config, "FORECAST_HORIZON_CHECK", False, raising=False)
    fc = {"binary_forecasts": _binaries(2028)}
    assert "quality" not in apply_horizon_consistency(fc, "the 2026 midterms", now_year=2026)


# ---------------------------------------------------- RQ-2: slice_head_tail math
def test_slice_head_tail_keeps_head_and_tail():
    text = "A" * 100 + "B" * 100                      # 200 chars, head=A tail=B
    out = slice_head_tail(text, budget=100, head_ratio=0.6)
    assert out.startswith("A" * 60)                    # head 60% of budget
    assert out.endswith("B" * 40)                      # tail 40% of budget
    assert "…(中段略)…" in out                          # elision marker between segments


def test_slice_head_tail_noop_when_within_budget():
    assert slice_head_tail("short", budget=1000) == "short"
    assert slice_head_tail("abc", budget=0) == "abc"   # non-positive budget → unchanged
    assert slice_head_tail("", budget=10) == ""


# ------------------------------------------------- RQ-2: theme cardinality flag
def test_binary_quality_flags_single_theme():
    single = [{"probability": 0.8, "theme": "ai", "criteria_sharp": True},
              {"probability": 0.2, "theme": "ai", "criteria_sharp": True}]
    q1 = _binary_quality(single, min_count=2)
    assert q1["theme_cardinality"] == 1
    assert any("single theme" in s for s in q1["issues"])
    multi = [{"probability": 0.8, "theme": "ai", "criteria_sharp": True},
             {"probability": 0.2, "theme": "trade", "criteria_sharp": True}]
    q2 = _binary_quality(multi, min_count=2)
    assert q2["theme_cardinality"] == 2
    assert not any("single theme" in s for s in q2["issues"])


# ----------------------------------------- PM-2: deterministic market anchoring
_ANCHOR_MARKETS = [
    {"market_id": "mkt-1", "question": "Tariffs > 10%?", "implied_yes_prob": 0.30,
     "url": "https://polymarket.com/event/tariffs", "end_date": "2028-12-31"},
]


def test_anchor_binaries_to_markets_backfills_rich_anchor():
    binaries = [
        {"id": "F1", "statement": "US tariff rate averages over 10% 2026-2028",
         "probability": 0.25, "adjustment_rationale": "base rate"},
        {"id": "F2", "statement": "AI capex exceeds $500B in 2027",
         "probability": 0.80, "adjustment_rationale": ""},
    ]
    fake = FakeLLMClient(json_responses=[{"matches": [
        {"forecast_id": "F1", "market_id": "mkt-1", "resolution_equivalence": "exact", "confidence": 0.9},
        {"forecast_id": "F2", "market_id": None, "resolution_equivalence": "loose", "confidence": 0.2},
    ]}])
    n = anchor_binaries_to_markets(binaries, _ANCHOR_MARKETS, fake)
    assert n == 1
    a = binaries[0]["market_anchor"]
    assert a["market_id"] == "mkt-1" and a["question"] == "Tariffs > 10%?"
    # implied 以我们的快照价为准；price_at_research 同源；divergence 本地计算。
    assert a["implied_yes_prob"] == 0.30 and a["price_at_research"] == 0.30
    assert a["divergence"] == round(0.25 - 0.30, 4)
    assert a["url"].endswith("/tariffs") and a["endDate"] == "2028-12-31"
    assert a["resolution_equivalence"] == "exact" and a["match_confidence"] == 0.9
    assert "market_anchor" not in binaries[1]           # null market_id → no anchor


def test_anchor_skips_loose_match_below_min_equivalence():
    binaries = [{"id": "F1", "statement": "X happens", "probability": 0.5}]
    fake = FakeLLMClient(json_responses=[{"matches": [
        {"forecast_id": "F1", "market_id": "mkt-1", "resolution_equivalence": "loose", "confidence": 0.9}]}])
    assert anchor_binaries_to_markets(binaries, _ANCHOR_MARKETS, fake) == 0
    assert "market_anchor" not in binaries[0]           # loose < default 'near' → dropped


def test_anchor_no_markets_or_bad_json_leaves_no_anchor():
    binaries = [{"id": "F1", "statement": "X happens", "probability": 0.5}]
    # no markets → no LLM call, no anchor
    assert anchor_binaries_to_markets(binaries, [], FakeLLMClient()) == 0
    # malformed reply → today's behavior (no anchors)
    assert anchor_binaries_to_markets(
        binaries, _ANCHOR_MARKETS, FakeLLMClient(json_responses=[{"nope": 1}])) == 0
    assert "market_anchor" not in binaries[0]


def test_anchor_disabled_by_flag(monkeypatch):
    from app.config import Config
    monkeypatch.setattr(Config, "FORECAST_MARKET_ANCHORING", False, raising=False)
    binaries = [{"id": "F1", "statement": "X happens", "probability": 0.5}]
    fake = FakeLLMClient(json_responses=[{"matches": [
        {"forecast_id": "F1", "market_id": "mkt-1", "resolution_equivalence": "exact", "confidence": 1.0}]}])
    assert anchor_binaries_to_markets(binaries, _ANCHOR_MARKETS, fake) == 0
    assert fake.calls == []                              # flag off → no LLM call at all


# --------------------------------------------------- PM-2: 10pp divergence rule
def _divergent_binary():
    # LOOP-017 P0：分歧重述的资格现在要求 match_confidence >= 门槛（默认 0.6）——
    # 本组测试针对「重述采纳」机制本身，故锚点带一枚高置信匹配；置信门槛本身的
    # 红线在 test_market_influence_boundary.py。
    return {"id": "F1", "statement": "X happens", "probability": 0.20,
            "adjustment_rationale": "base rate says low",
            "market_anchor": {"market_id": "m", "implied_yes_prob": 0.55,
                              "match_confidence": 0.9,
                              "divergence": round(0.20 - 0.55, 4)}}


def test_enforce_market_divergence_revises_when_rationale_cites_market():
    b = _divergent_binary()
    fake = FakeLLMClient(json_responses=[{"revisions": [
        {"id": "F1", "probability": 0.35,
         "adjustment_rationale": "The market implies 55%; I move up but it overweights the base case."}]}])
    assert enforce_market_divergence([b], fake) == 1
    assert b["probability"] == 0.35
    assert b["market_anchor"]["divergence"] == round(0.35 - 0.55, 4)   # recomputed


def test_enforce_market_divergence_rejects_silent_move():
    b = _divergent_binary()
    # revision moves the probability but never mentions the market → rejected, prob untouched
    fake = FakeLLMClient(json_responses=[{"revisions": [
        {"id": "F1", "probability": 0.55, "adjustment_rationale": "just moved it higher"}]}])
    assert enforce_market_divergence([b], fake) == 0
    assert b["probability"] == 0.20                     # never silently moved


def test_enforce_market_divergence_skips_when_already_cited():
    b = _divergent_binary()
    b["adjustment_rationale"] = "market prices 55% but I disagree because of the tail risk"
    fake = FakeLLMClient()                              # no responses queued
    assert enforce_market_divergence([b], fake) == 0
    assert fake.calls == []                             # already explained → no revision call


def test_enforce_market_divergence_ignores_within_10pp():
    b = _divergent_binary()
    b["probability"] = 0.50
    b["market_anchor"]["divergence"] = round(0.50 - 0.55, 4)   # |−0.05| <= 0.10
    fake = FakeLLMClient()
    assert enforce_market_divergence([b], fake) == 0
    assert fake.calls == []


def test_build_market_comparison_flags_10pp_breaches():
    binaries = [
        {"id": "F1", "statement": "X", "probability": 0.20,
         "adjustment_rationale": "the market prices 55%",
         "market_anchor": {"market_id": "m", "question": "Q", "implied_yes_prob": 0.55,
                           "price_at_research": 0.55, "divergence": -0.35}},
        {"id": "F2", "statement": "Y", "probability": 0.5},          # no anchor
    ]
    mc = build_market_comparison(binaries)
    assert mc["anchored_count"] == 1
    row = mc["comparisons"][0]
    assert row["forecast_id"] == "F1" and row["exceeds_10pp"] is True
    assert row["abs_divergence"] == 0.35 and row["rationale_cites_market"] is True


def test_reconcile_forecast_contract_uses_scenario_partition_and_moves_market_anchor():
    forecast = {
        "scenarios": [
            {"name": "D House + D Senate (clean Dem sweep)", "probability": 0.19},
            {"name": "D House + R Senate (split Congress)", "probability": 0.44},
            {"name": "D House + 50-50 Senate (GOP VP tiebreaker)", "probability": 0.13},
            {"name": "R trifecta preserved", "probability": 0.10},
            {"name": "R House + D Senate", "probability": 0.06},
            {"name": "Other / ambiguous / contested", "probability": 0.08},
        ],
        "binary_forecasts": [
            {"id": "F2", "statement": "Democrats win a 218+ House majority.",
             "resolution_criteria": "Democratic control of the House", "probability": 0.53},
            {"id": "F3", "statement": "Republicans retain effective control of the Senate.",
             "resolution_criteria": "51+ Republicans or 50/50 with a GOP VP tiebreaker",
             "probability": 0.84},
            {"id": "F4", "statement": "A divided result gives Democrats the House and Republicans the Senate.",
             "resolution_criteria": "D House and R Senate, including 50/50 with GOP VP",
             "probability": 0.46,
             "market_anchor": {"market_id": "m-sweep", "question": "2026 Balance of Power: D Senate, D House",
                               "implied_yes_prob": 0.44, "price_at_research": 0.44,
                               "url": "https://polymarket.com/event/balance", "endDate": "2026-11-03",
                               "resolution_equivalence": "near", "match_confidence": 0.95}},
            {"id": "F10", "statement": "Republicans retain a 218+ House majority.",
             "resolution_criteria": "Republicans control 218+ House seats", "probability": 0.18},
            {"id": "F11", "statement": "Democrats win a sweep of both the House and Senate.",
             "resolution_criteria": "Democratic House and Democratic Senate control",
             "probability": 0.10,
             "market_anchor": {"market_id": "m-sweep", "implied_yes_prob": 0.44}},
        ],
    }

    result = reconcile_forecast_contract(forecast)
    by_id = {row["id"]: row for row in forecast["binary_forecasts"]}

    assert by_id["F2"]["probability"] == 0.76
    assert by_id["F3"]["probability"] == 0.67
    assert by_id["F4"]["probability"] == 0.57
    assert by_id["F10"]["probability"] == 0.16
    assert by_id["F11"]["probability"] == 0.19
    assert "market_anchor" not in by_id["F4"]
    assert by_id["F11"]["market_anchor"]["question"].startswith("2026 Balance")
    assert by_id["F11"]["market_anchor"]["resolution_equivalence"] == "near"
    assert forecast["market_comparison"]["anchored_count"] == 1
    assert result["corrected_count"] == 5 and result["passed"] is True
    assert audit_proposition_consistency(forecast)["passed"] is True
    assert audit_market_anchor_integrity(forecast)["passed"] is True


def test_membership_rejects_non_boolean_derivable_without_reconciling():
    binaries = _normalize_binaries([{
        "id": "F1",
        "statement": "The event occurs by 2027.",
        "probability": 0.20,
        "resolution_criteria": "The named metric exceeds 1 by 2027.",
        "scenario_membership": {
            "derivable": "false",
            "yes_scenarios": ["Event occurs"],
        },
    }])
    forecast = {
        "scenarios": [
            {"name": "Event occurs", "probability": 0.40},
            {"name": "Event does not occur", "probability": 0.60},
        ],
        "binary_forecasts": binaries,
    }

    result = reconcile_forecast_contract(forecast)
    audit = audit_proposition_consistency(forecast)

    assert binaries[0]["scenario_membership"]["derivable"] is None
    assert "derivable must be a JSON boolean" in (
        binaries[0]["scenario_membership"]["validation_errors"]
    )
    assert binaries[0]["probability"] == 0.20
    assert result["corrected_count"] == 0
    assert audit["passed"] is False
    assert "JSON boolean" in audit["mismatches"][0]["reason"]


def test_membership_canonicalizes_non_derivable_scenario_suggestions():
    raw = [
        {
            "id": forecast_id,
            "statement": statement,
            "probability": probability,
            "resolution_criteria": criteria,
            "scenario_membership": {
                "derivable": False,
                "yes_scenarios": ["China Triumphant — Global Bifurcation Hardens"],
            },
        }
        for forecast_id, statement, probability, criteria in (
            (
                "F4",
                "China domestic EV penetration exceeds 65% by 2030.",
                0.68,
                "CAAM reports penetration above 65% by December 2030.",
            ),
            (
                "F7",
                "CATL and BYD control more than 50% of battery capacity by 2030.",
                0.73,
                "SNE reports combined capacity above 50% by December 2030.",
            ),
            (
                "F11",
                "Chinese vehicles exceed 15% of European EV registrations by 2028.",
                0.72,
                "ACEA reports a share above 15% by December 2028.",
            ),
        )
    ]
    binaries = _normalize_binaries(raw)
    forecast = {
        "scenarios": [
            {
                "name": "China Triumphant — Global Bifurcation Hardens",
                "probability": 0.488,
            },
            {"name": "Solid-State Disruption", "probability": 0.122},
            {"name": "Other / Status Quo", "probability": 0.39},
        ],
        "binary_forecasts": binaries,
    }

    result = reconcile_forecast_contract(forecast)
    audit = audit_proposition_consistency(forecast)

    assert [row["probability"] for row in binaries] == [0.68, 0.73, 0.72]
    assert all(
        row["scenario_membership"]["derivable"] is False
        and row["scenario_membership"]["yes_scenarios"] == []
        and row["scenario_membership"]["discarded_yes_scenarios"]
        == ["China Triumphant — Global Bifurcation Hardens"]
        for row in binaries
    )
    assert result["corrected_count"] == 0
    assert result["passed"] is True
    assert audit["checked"] == 0
    assert audit["mismatch_count"] == 0
    assert audit["passed"] is True


def test_membership_rejects_duplicate_yes_scenarios_without_double_counting():
    binaries = _normalize_binaries([{
        "id": "F1",
        "statement": "The event occurs by 2027.",
        "probability": 0.20,
        "resolution_criteria": "The named metric exceeds 1 by 2027.",
        "scenario_membership": {
            "derivable": True,
            "yes_scenarios": ["Event occurs", "Event occurs"],
        },
    }])
    forecast = {
        "scenarios": [
            {"name": "Event occurs", "probability": 0.40},
            {"name": "Event does not occur", "probability": 0.60},
        ],
        "binary_forecasts": binaries,
    }

    result = reconcile_forecast_contract(forecast)
    audit = audit_proposition_consistency(forecast)

    assert binaries[0]["probability"] == 0.20
    assert result["corrected_count"] == 0
    assert audit["passed"] is False
    assert "duplicates" in audit["mismatches"][0]["reason"]


def test_net_seat_gain_statement_conflicts_with_house_control_criterion():
    forecast = {
        "scenarios": [
            {"name": "R House", "probability": 0.20},
            {"name": "D House", "probability": 0.80},
        ],
        "binary_forecasts": [{
            "id": "F10",
            "statement": "Republicans gain a net of zero or more House seats.",
            "resolution_criteria": "Republicans control 218+ House seats.",
            "probability": 0.18,
        }],
    }

    result = reconcile_forecast_contract(forecast)
    audit = audit_proposition_consistency(forecast)

    assert forecast["binary_forecasts"][0]["probability"] == 0.18
    assert result["corrected_count"] == 0
    assert audit["passed"] is False
    assert "different events" in audit["mismatches"][0]["reason"]


def test_general_scenario_membership_and_unbound_market_equivalence_fail_closed():
    forecast = {
        "scenarios": [
            {"name": "Launch succeeds", "probability": 0.65},
            {"name": "Launch slips", "probability": 0.25},
            {"name": "Program cancelled", "probability": 0.10},
        ],
        "binary_forecasts": [{
            "id": "F1",
            "proposition_id": "program-operational-by-2030",
            "statement": "The program is operational by 2030.",
            "resolution_criteria": "The regulator certifies operations by 2030.",
            "probability": 0.40,
            "scenario_membership": {
                "derivable": True,
                "yes_scenarios": ["Launch succeeds"],
            },
            "market_anchor": {
                "market_id": "unrelated-1",
                "question": "Will a different company merge by 2029?",
                "implied_yes_prob": 0.5,
                "url": "https://polymarket.com/event/unrelated",
                "endDate": "2029-12-31",
                "resolution_equivalence": "near",
                "match_confidence": 0.9,
            },
        }],
    }

    before = audit_proposition_consistency(forecast)
    market_before = audit_market_anchor_integrity(forecast)
    result = reconcile_forecast_contract(forecast)

    assert before["mismatch_count"] == 1
    assert market_before["passed"] is False
    assert forecast["binary_forecasts"][0]["probability"] == 0.65
    assert "market_anchor" not in forecast["binary_forecasts"][0]
    assert result["passed"] is True


def test_extract_binary_forecasts_anchors_and_emits_comparison(monkeypatch):
    # TIME-3: pin the endDate clock so the 2028-12-31 market never ages out of anchoring.
    monkeypatch.setattr(prediction_markets, "market_clock_now",
                        lambda: datetime(2026, 10, 1, tzinfo=timezone.utc))
    markets = [{"market_id": "mkt-1", "question": "Tariffs > 10%?", "implied_yes_prob": 0.30,
                "url": "https://polymarket.com/event/t", "end_date": "2028-12-31"}]
    fake = FakeLLMClient(json_responses=[
        {"binary_forecasts": [
            {"id": "F1", "statement": "US tariff averages over 10% 2026-2028", "probability": 0.25,
             "resolution_criteria": "USITC > 10% by 2028", "theme": "trade", "horizon_year": 2028,
             "adjustment_rationale": "base rate"},
            {"id": "F2", "statement": "AI capex exceeds $500B in 2027", "probability": 0.80,
             "resolution_criteria": "capex > $500B in 2027", "theme": "ai", "horizon_year": 2027,
             "adjustment_rationale": "trend"},
        ]},
        {"matches": [                                    # deterministic anchoring call
            {"forecast_id": "F1", "market_id": "mkt-1", "resolution_equivalence": "exact", "confidence": 0.9}]},
    ])
    out = extract_binary_forecasts("dossier", fake, min_count=2, language="English",
                                   market_pack="table", markets=markets)
    f1 = next(b for b in out["binary_forecasts"] if b["id"] == "F1")
    assert f1["market_anchor"]["market_id"] == "mkt-1"
    assert f1["market_anchor"]["implied_yes_prob"] == 0.30          # our snapshot price
    assert "market_comparison" in out and out["market_comparison"]["anchored_count"] == 1
    # F1 divergence 0.25-0.30 = -0.05 (<=10pp) → no revision call was needed
    assert "market_anchor" not in next(b for b in out["binary_forecasts"] if b["id"] == "F2")


# ------------------------------------------------- ITEM 12: multi-model ensemble
def _ensemble_config(monkeypatch, *, models="modelb", extremize=None, threshold=0.15):
    """Configure the multi-model ensemble deterministically for a test.

    ``extremize=None`` → arithmetic-mean pooling (predictable math); contrarian /
    sim-sensitivity top-ups disabled so the primary makes exactly one draw call."""
    from app.config import Config
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_MODELS", models, raising=False)
    monkeypatch.setattr(Config, "ENSEMBLE_EXTREMIZE_A", extremize, raising=False)
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_SPREAD_THRESHOLD", threshold, raising=False)
    monkeypatch.setattr(Config, "FORECAST_BINARY_CONTRARIAN", False, raising=False)
    monkeypatch.setattr(Config, "FORECAST_SIM_SENSITIVITY", False, raising=False)


def _binary(bid, stmt, prob, theme="t1"):
    return {"id": bid, "statement": stmt, "probability": prob,
            "resolution_criteria": f"metric > 10% by 2027 ({bid})", "theme": theme,
            "horizon_year": 2027}


def test_ensemble_pools_across_models_and_flags_spread(monkeypatch):
    _ensemble_config(monkeypatch)
    primary = FakeLLMClient(provider="primary", json_responses=[
        {"binary_forecasts": [_binary("F1", "Alpha exceeds 10% by 2027", 0.20),
                              _binary("F2", "Beta exceeds 500 by 2027", 0.80, theme="t2")]}])
    secondary = FakeLLMClient(provider="modelb", json_responses=[
        {"binary_forecasts": [_binary("F1", "Alpha exceeds 10% by 2027", 0.60),
                              _binary("F2", "Beta exceeds 500 by 2027", 0.82, theme="t2")]}])
    out = extract_binary_forecasts(
        "dossier", primary, min_count=2, language="English",
        ensemble_client_factory=lambda name: {"modelb": secondary}.get(name))
    f1 = next(b for b in out["binary_forecasts"] if b["id"] == "F1")
    f2 = next(b for b in out["binary_forecasts"] if b["id"] == "F2")
    # statement-keyed match; arithmetic-mean pooling overrides the published probability
    assert f1["ensemble"]["models"] == ["primary", "modelb"]
    assert f1["ensemble"]["probs"] == [0.2, 0.6]
    assert f1["ensemble"]["pooled"] == 0.4
    assert f1["probability"] == 0.4
    assert f1["ensemble"]["spread"] > 0.15          # stdev([0.2,0.6]) ≈ 0.2828 → disagreement
    assert f2["ensemble"]["spread"] < 0.15          # stdev([0.8,0.82]) ≈ 0.0141 → agreement
    assert f2["probability"] == 0.81
    ens = out["binary_quality"]["ensemble"]
    assert ens["pooled_models"] == ["modelb"]
    assert ens["low_agreement"] == ["F1"]
    assert ens["skipped"] == []
    assert any("cross-model disagreement" in s for s in out["binary_quality"].get("issues", []))
    # the secondary client was invoked exactly once (one draw)
    assert sum(1 for c in secondary.calls if c["kind"] == "chat_json") == 1


def test_ensemble_id_matching_when_statements_differ(monkeypatch):
    _ensemble_config(monkeypatch, models="mb")
    primary = FakeLLMClient(provider="primary", json_responses=[
        {"binary_forecasts": [_binary("F1", "Alpha exceeds 10% by 2027", 0.30)]}])
    # different wording → statement key won't match, but id "F1" does (id fallback)
    secondary = FakeLLMClient(provider="mb", json_responses=[
        {"binary_forecasts": [_binary("F1", "Paraphrased alpha clause over ten percent", 0.50)]}])
    out = extract_binary_forecasts(
        "d", primary, min_count=1, language="English",
        ensemble_client_factory=lambda name: secondary if name == "mb" else None)
    f1 = out["binary_forecasts"][0]
    assert f1["ensemble"]["models"] == ["primary", "mb"]
    assert f1["ensemble"]["probs"] == [0.3, 0.5]
    assert f1["probability"] == 0.4


def test_ensemble_off_by_default_is_byte_identical(monkeypatch):
    # FORECAST_ENSEMBLE_MODELS empty → the entire ensemble path is skipped.
    from app.config import Config
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_MODELS", "", raising=False)
    monkeypatch.setattr(Config, "FORECAST_BINARY_CONTRARIAN", False, raising=False)
    monkeypatch.setattr(Config, "FORECAST_SIM_SENSITIVITY", False, raising=False)
    primary = FakeLLMClient(provider="primary", json_responses=[
        {"binary_forecasts": [_binary("F1", "Alpha exceeds 10% by 2027", 0.30)]}])
    out = extract_binary_forecasts("d", primary, min_count=1, language="English")
    assert all("ensemble" not in b for b in out["binary_forecasts"])
    assert "ensemble" not in out["binary_quality"]
    assert out["binary_forecasts"][0]["probability"] == 0.3   # untouched primary


def test_ensemble_secondary_failure_is_skipped_never_blocks(monkeypatch):
    _ensemble_config(monkeypatch, models="badmodel")

    def _factory(name):
        raise RuntimeError(f"cannot build client for {name}")

    primary = FakeLLMClient(provider="primary", json_responses=[
        {"binary_forecasts": [_binary("F1", "Alpha exceeds 10% by 2027", 0.30)]}])
    out = extract_binary_forecasts("d", primary, min_count=1, language="English",
                                   ensemble_client_factory=_factory)
    f1 = out["binary_forecasts"][0]
    assert "ensemble" not in f1                      # nothing pooled
    assert f1["probability"] == 0.3                  # primary preserved
    ens = out["binary_quality"]["ensemble"]
    assert ens["skipped"] == ["badmodel"]
    assert ens["pooled_models"] == [] and ens["low_agreement"] == []


def test_pool_binary_unmatched_keeps_primary():
    primary = [{"id": "F1", "statement": "alpha", "probability": 0.30},
               {"id": "F2", "statement": "beta", "probability": 0.70}]
    secondary = {"mb": [{"id": "F1", "statement": "alpha", "probability": 0.50}]}  # only F1
    low = pool_binary_forecasts(primary, secondary, primary_model="primary",
                                extremize_a=None, spread_threshold=0.05)
    assert primary[0]["ensemble"]["probs"] == [0.3, 0.5]
    assert primary[0]["probability"] == 0.4
    assert "ensemble" not in primary[1]              # F2 had no secondary → keep primary
    assert primary[1]["probability"] == 0.70
    assert low == ["F1"]                             # stdev([0.3,0.5]) ≈ 0.1414 > 0.05


def test_render_binary_block_shows_pm_spread_and_low_agreement():
    forecast = {
        "binary_forecasts": [
            {"id": "F1", "statement": "Alpha", "probability": 0.40, "resolution_criteria": "x",
             "theme": "t1", "ensemble": {"models": ["a", "b"], "probs": [0.2, 0.6],
                                         "pooled": 0.4, "spread": 0.2828}},
            {"id": "F2", "statement": "Beta", "probability": 0.81, "resolution_criteria": "y",
             "theme": "t2", "ensemble": {"models": ["a", "b"], "probs": [0.8, 0.82],
                                         "pooled": 0.81, "spread": 0.0141}},
        ],
        "binary_quality": {"count": 2, "conviction_count": 1, "sharp_criteria_count": 0,
                           "ensemble": {"pooled_models": ["b"], "low_agreement": ["F1"],
                                        "spread_threshold": 0.15}},
    }
    md = render_binary_forecasts_block(forecast, language="English")
    assert "±28%" in md            # F1 spread rendered
    assert "⚠" in md               # F1 exceeds threshold → low-agreement marker
    assert "±1%" in md             # F2 spread rendered (tight)
    assert "cross-model disagreement" in md
    # a plain (non-ensemble) forecast is byte-unchanged (no ± column noise)
    plain = {"binary_forecasts": [{"id": "F1", "statement": "X", "probability": 0.5,
                                   "resolution_criteria": "z", "theme": "t"}]}
    assert "±" not in render_binary_forecasts_block(plain, language="English")
