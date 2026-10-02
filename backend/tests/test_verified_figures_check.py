"""REPORT-9 (C11 phase 2, detection only): the report's figures against the REPORT-8
verified-figures block (verified_facts.check_verified_figures), recorded in
forecast.quality.verified_figures and final_audit.json, and figure_provenance.json.
Shadow: never changes markdown bytes, never adds a hard or epistemic issue.  Offline."""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import date
from types import SimpleNamespace

import pytest

from app.config import Config
from app.config_audit import RANGE_RULES
from app.services import verified_facts as vf
from app.services.forecast_extractor import BINARY_FORECAST_END_MARKER, BINARY_FORECAST_START_MARKER
from app.services.report_agent import ReportAgent, ReportManager, ReportOutline, ReportSection, ReportStatus
from app.utils.numeric_guards import scan_quantities, threshold_comparators, threshold_spans
from tests.conftest import FakeLLMClient

AS_OF = date(2026, 6, 30)
SHARE = {"metric": "Data-centre electricity share", "value": "24.6", "unit": "%", "when": "2025", "tag": "S1"}
CAPEX = {"metric": "Global data centre capex spending", "value": "1,200", "unit": "USD billion",
         "when": "2025", "tag": "S2"}


def _check(md, rows=(SHARE, CAPEX), **kwargs):
    return vf.check_verified_figures(md, list(rows), **kwargs)


def _counts(md, rows=(SHARE, CAPEX), **kwargs):
    return {k: v for k, v in _check(md, rows, **kwargs)["counts"].items() if v}


# ------------------------------------------------------------------ pure check
@pytest.mark.parametrize("line", [
    "The data-centre electricity share was 24.6% in 2025 [S1].",          # exact
    "The data-centre electricity share reached about 25% in 2025 [S1].",   # rounding to the claim
    "Global data centre capex spending hit $1.2 trillion in 2025 [S2].",   # scale
    "Global data centre capex spending hit $1,200 billion in 2025.",
])
def test_match_cases(line):
    result = _check(f"# T\n\n{line}\n")
    assert result["counts"]["matched"] == 1 and sum(result["counts"].values()) == 1
    (index,) = result["matched_rows"]
    assert result["matched_rows"][index] == [{"line": 3, "excerpt": line}]


def test_conflict_and_guards():
    conflict = _check("# T\n\nThe data-centre electricity share was 31% in 2025 [S3].\n")
    assert conflict["counts"]["conflict"] == 1
    assert conflict["examples"][0]["kind"] == "conflict" and conflict["examples"][0]["row_index"] == 0
    assert conflict["examples"][0]["cited"] == "S3"
    # Two candidate rows with different values: ambiguous, never a conflict.
    other = dict(SHARE, value="30", tag="S4")
    assert _counts("# T\n\nThe data-centre electricity share was 27% in 2025.\n", rows=(SHARE, other)) \
        == {"ambiguous": 1}
    # A year mismatch, a unit-class mismatch or a 10x ratio is no conflict.
    assert _counts("# T\n\nThe data-centre electricity share was 31% in 2019.\n") == {"unmatched": 1}
    assert _counts("# T\n\nThe data-centre electricity share was $31 billion in 2025.\n") == {"unmatched": 1}
    assert _counts("# T\n\nThe data-centre electricity share was 0.5% in 2025.\n") == {"unmatched": 1}
    # Within rel_tol is no conflict either.
    assert _counts("# T\n\nThe data-centre electricity share was 24.9% in 2025.\n", rel_tol=0.05) \
        == {"unmatched": 1}
    # No anchor: unmatched, whatever the number.
    assert _counts("# T\n\nShipments rose 31% in 2025.\n") == {"unmatched": 1}


def test_table_cells_take_their_row_or_column_year():
    year_column = "# T\n\n| Metric | Year | Value |\n|---|---|---|\n| Data-centre electricity share | {year} | 31% |\n"
    # The year sits in another cell of the row: a 2030 row is no conflict with the 2025 figure.
    assert _counts(year_column.format(year=2030)) == {"unmatched": 1}
    assert _counts(year_column.format(year=2025)) == {"conflict": 1}
    # The year is the column header: each cell is read with its own column's year.
    by_column = ("# T\n\n| Metric | 2025 | 2030E |\n|---|---|---|\n"
                 "| Data-centre electricity share | 24.6% | 31% |\n")
    result = _check(by_column)
    assert {k: v for k, v in result["counts"].items() if v} == {"matched": 1, "unmatched": 1}
    # A cell's excerpt is its whole row: the cell alone ("24.6%") names no metric.
    assert result["matched_rows"] == {0: [{"line": 5, "excerpt": "| Data-centre electricity share | 24.6% | 31% |"}]}
    # A cell's own year beats its column's.
    assert _counts("# T\n\n| Metric | 2030E |\n|---|---|\n| Data-centre electricity share | 31% (2025) |\n") \
        == {"conflict": 1}
    # A line outside the table ends it: a later headerless row takes no stale column year.
    assert _counts(by_column + "\nSee the table.\n\n| Data-centre electricity share | n/a | 31% |\n") \
        == {"matched": 1, "unmatched": 1, "conflict": 1}


def test_thresholds_and_probabilities_are_counted_apart():
    # Neither the probability nor the threshold states the metric's level.
    assert _counts("# T\n\nWe assign a 40% probability that the data-centre electricity share will exceed 30%.\n") \
        == {"threshold_or_probability": 2}
    assert _counts("# T\n\nThe odds are 35% that the data-centre electricity share stays below 20% in 2025.\n") \
        == {"threshold_or_probability": 2}
    zh_row = {"metric": "数据中心电力占比", "value": "24.6", "unit": "%", "when": "2025", "tag": "S1"}
    assert _counts("# T\n\n2025年数据中心电力占比超过30%的概率为40%。\n", rows=[zh_row]) \
        == {"threshold_or_probability": 2}
    assert _counts("# T\n\n2025年数据中心电力占比为31%。\n", rows=[zh_row]) == {"conflict": 1}
    # The level beside them is still checked.
    assert _counts("# T\n\nThe data-centre electricity share was 31% in 2025, with a 40% chance of exceeding "
                   "35% by 2030.\n") == {"conflict": 1, "threshold_or_probability": 2}


@pytest.mark.parametrize("line", [
    "We judge it 70% likely that the data-centre electricity share rises in 2025.",
    "The data-centre electricity share is 70% likely to rise in 2025.",
    "With 70% confidence, the data-centre electricity share rises in 2025.",
    "We are 70% confident the data-centre electricity share rises in 2025.",
    "The data-centre electricity share scenario carries a 55% weight in 2025.",
    "Base case (data-centre electricity share rises in 2025): 55% probability.",
    "Scenario A (the data-centre electricity share surges in 2025): 55%.",
    "**Scenario B** (55%): the data-centre electricity share plateaus in 2025.",
    "We put the data-centre electricity share surge scenario at 40% for 2025.",
])
def test_forecast_phrasings_are_probabilities(line):
    assert _counts(f"# T\n\n{line}\n") == {"threshold_or_probability": 1}


@pytest.mark.parametrize("line", [
    "情景A（数据中心电力占比上升）：55%。",
    "1. 情景B（2025年数据中心电力占比回落）：25%",
    "数据中心电力占比在2025年上升，置信度70%。",
    "2025年数据中心电力占比上升的可能性约70%。",
])
def test_chinese_forecast_phrasings_are_probabilities(line):
    zh_row = {"metric": "数据中心电力占比", "value": "24.6", "unit": "%", "when": "2025", "tag": "S1"}
    assert _counts(f"# T\n\n{line}\n", rows=[zh_row]) == {"threshold_or_probability": 1}


def test_probability_words_never_hide_a_level():
    # Words after the label, or "likely" without a clause, leave the figure a level.
    for line in ("Scenario A: the data-centre electricity share reaches 31% in 2025.",
                 "The data-centre electricity share was 31% in 2025, likely because of AI demand.",
                 "The data-centre electricity share was 31% in 2025, with a heavy weighting to the US."):
        assert _counts(f"# T\n\n{line}\n") == {"conflict": 1}, line


def test_weight_and_confidence_words_that_name_the_metric_state_its_level():
    weight = {"metric": "Technology sector index weight", "value": "31", "unit": "%", "when": "2025", "tag": "S1"}
    rows = (SHARE, weight)
    assert _counts("# T\n\nThe technology sector index weight was 31% in 2025.\n", rows=rows) == {"matched": 1}
    assert _counts("# T\n\nThe technology sector index weight was 35% in 2025.\n", rows=rows) == {"conflict": 1}
    assert _counts("# T\n\n| Metric | 2025 |\n|---|---|\n| Technology sector index weight | 31% |\n", rows=rows) \
        == {"matched": 1}
    zh_weight = {"metric": "科技板块指数权重", "value": "31", "unit": "%", "when": "2025", "tag": "S1"}
    assert _counts("# T\n\n2025年科技板块指数权重为31%。\n", rows=[zh_weight]) == {"matched": 1}
    # A confidence grade in a row label grades the figure: the level is still checked.
    graded = "# T\n\n| Metric | 2025 |\n|---|---|\n| Data-centre electricity share (high confidence) | {v} |\n"
    assert _counts(graded.format(v="24.6%"), rows=rows) == {"matched": 1}
    assert _counts(graded.format(v="31%"), rows=rows) == {"conflict": 1}
    # The word stays a probability when no candidate's metric names it, and a column headed
    # by it is a probability column whatever its rows name.
    for md in ("The data-centre electricity share scenario carries a 55% weight in 2025.",
               "| Item | Confidence |\n|---|---|\n| Data-centre electricity share rises in 2025 | 70% |",
               "| Scenario | Weight |\n|---|---|\n| Technology sector index weight rises in 2025 | 40% |"):
        assert _counts(f"# T\n\n{md}\n", rows=rows) == {"threshold_or_probability": 1}, md


@pytest.mark.parametrize("md", [
    "The key threshold for the data-centre electricity share is 30% in 2025.",
    "The data-centre electricity share trigger level of 30% in 2025 matters.",
    "The 30% threshold for the data-centre electricity share was not crossed in 2025.",
    "Trigger: the data-centre electricity share at 30% in 2025.",
    "- **Signpost**: data-centre electricity share at 30% in 2025.",
    "| Metric | Threshold |\n|---|---|\n| Data-centre electricity share (2025) | 30% |",
    "| Item | 2025 |\n|---|---|\n| Trigger level for the data-centre electricity share | 30% |",
])
def test_threshold_nouns_and_labels_are_thresholds(md):
    assert _counts(f"# T\n\n{md}\n") == {"threshold_or_probability": 1}


def test_threshold_nouns_leave_the_level_beside_them():
    assert _counts("# T\n\nThe data-centre electricity share was 31% in 2025; the threshold is 35%.\n") \
        == {"conflict": 1, "threshold_or_probability": 1}
    # A verb "triggers" and a word ending a label are no threshold nouns.
    for line in ("AI demand triggers a data-centre electricity share of 31% in 2025.",
                 "Shares: the data-centre electricity share was 31% in 2025."):
        assert _counts(f"# T\n\n{line}\n") == {"conflict": 1}, line
    zh_row = {"metric": "数据中心电力占比", "value": "24.6", "unit": "%", "when": "2025", "tag": "S1"}
    for line in ("2025年数据中心电力占比的阈值为30%。", "阈值：2025年数据中心电力占比30%。", "2025年数据中心电力占比30%的阈值未被突破。",
                 "| 指标 | 阈值 |\n|---|---|\n| 2025年数据中心电力占比 | 30% |"):
        assert _counts(f"# T\n\n{line}\n", rows=[zh_row]) == {"threshold_or_probability": 1}, line


def test_threshold_spans_marks_only_comparator_governed_figures():
    text = "The share was 24.6% and may exceed 30%, or reach 5% or more; it sits between 28% and 38%."
    spans = threshold_spans(text)
    assert [hit["raw"] for hit in scan_quantities(text) if any(lo <= hit["start"] < hi for lo, hi in spans)] \
        == ["30%", "5%", "28%", "38%"]
    for unreadable in (None, {"a": 1}, True, ""):
        assert threshold_spans(unreadable) == [] and threshold_comparators(unreadable) == []
    # The same spans with their comparators (a negated event's inverted one).
    assert [comparator for _start, _end, comparator in threshold_comparators(text)] == [">", ">=", "between"]
    assert threshold_comparators("It does not exceed 30%.") == [(19, 22, "<=")]


def test_bounded_rows_are_read_as_bounds():
    """A verified value that is a bound (">3" trillion) states the figures on its side, and
    no figure conflicts with it (nor, when its [S#] supports the claim, is a discrepancy)."""
    bound = {"metric": "Global data centre capex forecast", "value": ">3", "unit": "USD trillion",
             "when": "2030", "tag": "S1"}
    line = "# T\n\nGlobal data centre capex forecast is ${v} trillion for 2030 [S1].\n"
    for value, expected in (("3.5", "matched"), ("3", "matched"), ("1.2", "unmatched"), ("40", "unmatched")):
        result = _check(line.format(v=value), rows=[bound], support_fn=lambda unit, tag: True)
        assert {k: v for k, v in result["counts"].items() if v} == {expected: 1}, value
        assert result["source_discrepancies"] == [], value
    capacity = "# T\n\nThe data-centre electricity capacity share was {v} in 2025.\n"
    for value, unit, inside, outside in (("<12", "%", "10%", "15%"), ("≥25", "%", "31%", "20%"),
                                         ("at least 5", "GW", "6 GW", "4 GW"), ("超过30", "GW", "35 GW", "20 GW"),
                                         ("5 or more", "GW", "6 GW", "4 GW"), ("20+", "GW", "25 GW", "12 GW"),
                                         ("$153M+", "", "$160 million", "$100 million"),
                                         ("up to 40", "GW", "35 GW", "50 GW")):
        row = {"metric": "Data-centre electricity capacity share", "value": value, "unit": unit, "when": "2025"}
        assert _counts(capacity.format(v=inside), rows=[row]) == {"matched": 1}, value
        assert _counts(capacity.format(v=outside), rows=[row]) == {"unmatched": 1}, value
    # "between 28% and 38%" is read as its first end only: the row states no figure.
    between = {"metric": "Data-centre electricity capacity share", "value": "between 28% and 38%", "when": "2025"}
    assert _counts(capacity.format(v="50%"), rows=[between]) == {"unmatched": 1}
    # A plain value is still a point.
    point = dict(between, value="30", unit="%")
    assert _counts(capacity.format(v="35%"), rows=[point]) == {"conflict": 1}


def test_source_discrepancies_need_the_cited_source_to_support_the_claim():
    md = "# T\n\nThe data-centre electricity share was 31% in 2025 [S3].\n"
    assert _check(md, support_fn=lambda unit, tag: True)["source_discrepancies"] == [{
        "line": 3, "excerpt": md.splitlines()[2], "tag": "S3", "row_index": 0, "claim": "31%",
        "row_value": "24.6"}]
    for verdict in (False, None):
        assert _check(md, support_fn=lambda unit, tag, v=verdict: v)["source_discrepancies"] == []

    def boom(unit, tag):
        raise RuntimeError("support check failed")

    assert _check(md, support_fn=boom)["source_discrepancies"] == []
    uncited = "# T\n\nThe data-centre electricity share was 31% in 2025.\n"
    assert _check(uncited, support_fn=lambda unit, tag: True)["source_discrepancies"] == []


def test_citation_tags_follow_the_report_grammar():
    # Every tag of the unit is tried; the first that supports the claim is recorded,
    # normalised as forecast_extractor._norm_citation_tag does.
    md = "# T\n\nThe data-centre electricity share was 31% in 2025 [s3]【S1-A】.\n"
    seen = []

    def support(unit, tag):
        seen.append(tag)
        return tag == "S1-a"

    result = _check(md, support_fn=support)
    assert seen == ["S3", "S1-a"]
    assert [(d["tag"], d["claim"]) for d in result["source_discrepancies"]] == [("S1-a", "31%")]
    assert result["examples"][0]["cited"] == "S3"
    # A legacy tiered tag cites the unit: its restatement is the writer's own sourcing.
    unverified = {"metric": "Grid connection queue length", "value": "40", "unit": "months",
                  "verification": "unverified"}
    assert _counts("# T\n\nThe grid connection queue length reached 40 months [S5-b].\n",
                   excluded_rows=[unverified]) == {"unmatched": 1}


def test_scope():
    stated = "The data-centre electricity share was 31% in 2025."
    md = "\n".join([
        "# The data-centre electricity share was 31% in 2025", "",
        "## Data-centre electricity share 31% in 2025", "",
        BINARY_FORECAST_START_MARKER, f"- F1: {stated} (70%)", BINARY_FORECAST_END_MARKER, "",
        "```", stated, "```", "",
        "## References", "", f"- {stated} [S1]", "",
    ])
    assert sum(_check(md)["counts"].values()) == 0
    # The same sentence in the body counts, and a section after References is read again.
    after = md + "\n## Outlook\n\n" + stated + "\n"
    assert _counts(after) == {"conflict": 1}
    # A table cell is read with its whole row as the anchor.
    table = "# T\n\n| Metric | 2025 |\n|---|---|\n| Data-centre electricity share | 31% |\n"
    assert _counts(table) == {"conflict": 1}


def test_states_unverified_and_market():
    unverified = {"metric": "Grid connection queue length", "value": "40", "unit": "months",
                  "verification": "unverified"}
    md = "# T\n\nThe grid connection queue length reached 40 months.\n"
    assert _counts(md, excluded_rows=[unverified]) == {"states_unverified": 1}
    # Cited, the restatement is the writer's own sourcing: not flagged.
    assert _counts(md.replace("months.", "months [S5]."), excluded_rows=[unverified]) == {"unmatched": 1}
    market = {"market_id": "m1", "question": "Will the AI liability directive be adopted by June 2026?",
              "implied_yes_prob": 0.30, "price_at_research": 0.25}
    wrong = "# T\n\nPolymarket implies a 45% chance the AI liability directive is adopted.\n"
    right = "# T\n\nPolymarket implies a 30% chance the AI liability directive is adopted.\n"
    research_price = "# T\n\nPolymarket implied 25% for the AI liability directive at research time.\n"
    assert _counts(wrong, market_rows=[market]) == {"market_conflict": 1}
    assert _counts(right, market_rows=[market]) == {"unmatched": 1}
    assert _counts(research_price, market_rows=[market]) == {"unmatched": 1}
    # No anchored market: nothing to compare against (and "45% chance" is a probability).
    assert _counts(wrong, market_rows=[dict(market, question="Will oil exceed $100?")]) \
        == {"threshold_or_probability": 1}
    assert _counts(wrong) == {"threshold_or_probability": 1}


def test_market_percentages_are_read_against_the_markets_only():
    # The market's question and the block's metric share their anchor words.
    market = {"market_id": "m2", "question": "Will the data-centre electricity share exceed 30% in 2030?",
              "implied_yes_prob": 0.45, "price_at_research": 0.40}
    price = "# T\n\nPolymarket implies a {p}% chance the data-centre electricity share exceeds 30%.\n"
    # The market's own price is no conflict with the block's 24.6%, nor is the threshold.
    assert _counts(price.format(p=45), market_rows=[market]) == {"threshold_or_probability": 1, "unmatched": 1}
    assert _counts(price.format(p=40), market_rows=[market]) == {"threshold_or_probability": 1, "unmatched": 1}
    assert _counts(price.format(p=60), market_rows=[market]) == {"threshold_or_probability": 1, "market_conflict": 1}
    # A level quoted beside the market: the block's value matches, any other is a market conflict.
    level = "# T\n\nPolymarket prices a 45% chance although the data-centre electricity share was {v}% in 2025.\n"
    assert _counts(level.format(v=24.6), market_rows=[market]) == {"matched": 1, "unmatched": 1}
    assert _counts(level.format(v=31), market_rows=[market]) == {"market_conflict": 1, "unmatched": 1}
    assert _counts(level.format(v=31)) == {"threshold_or_probability": 1, "unmatched": 1}
    # "manifold" and a bare "implied" are ordinary words: no market context.
    for line in ("A manifold rise took the data-centre electricity share to 31% in 2025.",
                 "The implied data-centre electricity share was 31% in 2025."):
        assert _counts(f"# T\n\n{line}\n", market_rows=[market]) == {"conflict": 1}
    assert _counts("# T\n\nThe implied probability of 60% puts the data-centre electricity share above 30%.\n",
                   market_rows=[market]) == {"market_conflict": 1, "threshold_or_probability": 1}


_MARKET_TABLE = ("# T\n\n| Polymarket market | Implied probability | At research |\n|---|---|---|\n"
                 "| Will the data-centre electricity share exceed 30% in 2025? | {now}% | {then}% |\n")
_SHARE_MARKET = {"market_id": "m3", "question": "Will the data-centre electricity share exceed 30% in 2025?",
                 "implied_yes_prob": 0.45, "price_at_research": 0.40}


def test_market_tables_are_read_against_the_markets_only():
    # The market words sit in the header, the prices in their own cells: the cells that state
    # the anchored market's prices are no conflict with the block's 24.6% (the 30% is a threshold).
    same = _MARKET_TABLE.format(now=45, then=40)
    assert _counts(same, market_rows=[_SHARE_MARKET]) == {"threshold_or_probability": 1, "unmatched": 2}
    moved = _check(_MARKET_TABLE.format(now=60, then=40), market_rows=[_SHARE_MARKET])
    assert {k: v for k, v in moved["counts"].items() if v} == {
        "threshold_or_probability": 1, "market_conflict": 1, "unmatched": 1}
    (example,) = moved["examples"]
    # The excerpt is the whole row and the example names the column, for the manual review.
    assert (example["kind"], example["figure"], example["column"]) == ("market_conflict", "60%",
                                                                       "Implied probability")
    assert example["excerpt"] == "| Will the data-centre electricity share exceed 30% in 2025? | 60% | 40% |"
    # A market named only by its column header.
    by_column = ("# T\n\n| Question | Polymarket price |\n|---|---|\n"
                 "| Will the data-centre electricity share exceed 30% in 2025? | {p}% |\n")
    assert _counts(by_column.format(p=45), market_rows=[_SHARE_MARKET]) \
        == {"threshold_or_probability": 1, "unmatched": 1}
    assert _counts(by_column.format(p=60), market_rows=[_SHARE_MARKET]) \
        == {"threshold_or_probability": 1, "market_conflict": 1}


def test_scenario_probability_tables_are_counted_apart():
    table = ("# T\n\n## Scenario analysis\n\n| Scenario | Probability | Key driver |\n|---|---|---|\n"
             "| A: Data-centre electricity share surges | 40% | AI build-out |\n"
             "| B: Data-centre electricity share plateaus | 35% | Efficiency gains |\n"
             "| C: Other / status quo | 25% | — |\n")
    assert _counts(table) == {"threshold_or_probability": 3}
    zh_row = {"metric": "数据中心电力占比", "value": "24.6", "unit": "%", "when": "2025", "tag": "S1"}
    zh_table = "# T\n\n## 情景分析\n\n| 情景 | 概率 |\n|---|---|\n| 情景A：数据中心电力占比快速上升 | 40% |\n"
    assert _counts(zh_table, rows=[zh_row]) == {"threshold_or_probability": 1}
    # A row labelled as a probability, and a column headed by a bare "P".
    assert _counts("# T\n\n| Item | 2025 |\n|---|---|\n| Probability the data-centre electricity share "
                   "rises | 40% |\n") == {"threshold_or_probability": 1}
    assert _counts("# T\n\n| Scenario | P |\n|---|---|\n| Data-centre electricity share surges | 40% |\n") \
        == {"threshold_or_probability": 1}
    # A "P" inside a label ("S&P", "p.a.") makes no probability: the level is still checked.
    assert _counts("# T\n\n| Metric | Level (% p.a.) |\n|---|---|\n"
                   "| S&P data-centre electricity share | 31% (2025) |\n") == {"conflict": 1}


def test_reported_rows_are_read_by_the_period_they_describe():
    """A reported row is dated by its source's publication (as_of_date 2026-01-01) but
    describes 2025 (period_end): the check reads the period, the block still renders the date."""
    row = {"metric": "Global humanoid robot shipments", "value": "13,317", "unit": "units",
           "as_of_date": "2026-01-01", "period_end": "2025-12-31", "value_type": "actual", "tier": "S2",
           "source": "Omdia", "source_ref": "S1", "verification": "verified"}

    def block_for(*rows):
        return vf.build_verified_figures_block(list(rows), tag_for=lambda r: r.get("source_ref"), lang="en",
                                               as_of=AS_OF)

    block = block_for(row)
    (public,) = block["rows"]
    assert (public["when"], public["period"]) == ("2026-01-01", "2025-12-31")
    assert "2026-01-01" in block["rendered"] and "2025-12-31" not in block["rendered"]
    rows = block["rows"] + block["projections"]
    restated = vf.check_verified_figures(
        "# T\n\nGlobal humanoid robot shipments reached 13,317 units in 2025 [S1].\n", rows)
    assert restated["counts"]["matched"] == 1 and restated["matched_rows"] == {0: [{
        "line": 3, "excerpt": "Global humanoid robot shipments reached 13,317 units in 2025 [S1]."}]}
    forecast = "# T\n\nGlobal humanoid robot shipments are expected to reach 30,000 units in 2026.\n"
    assert {k: v for k, v in vf.check_verified_figures(forecast, rows)["counts"].items() if v} == {"unmatched": 1}
    # The metric's own year still counts; the publication year never does.
    named = block_for(dict(row, metric="2025 global humanoid shipments"))
    assert {k: v for k, v in vf.check_verified_figures(
        forecast.replace("robot ", ""), named["rows"])["counts"].items() if v} == {"unmatched": 1}
    # An excluded research row is read by its reference period too.
    unverified = dict(row, verification="unverified", value="9,000")
    stated = "# T\n\nGlobal humanoid robot shipments reached 9,000 units in {year}.\n"
    assert _counts(stated.format(year=2025), rows=(), excluded_rows=[unverified]) == {"states_unverified": 1}
    assert _counts(stated.format(year=2026), rows=(), excluded_rows=[unverified]) == {"unmatched": 1}


def test_unrendered_fields_never_change_the_block_and_never_depend_on_input_order():
    base = {"metric": "Data-centre electricity share", "value": "24.6", "unit": "%", "as_of_date": "2026-01-01",
            "value_type": "actual", "tier": "S1", "source": "Energy agency", "source_ref": "S1",
            "verification": "verified"}
    annotated = dict(base, period_end="2025-12-31", definition="Share of national electricity use by data "
                     "centres", series="IEA electricity tracker")

    def block_for(*rows):
        return vf.build_verified_figures_block(list(rows), tag_for=lambda r: r.get("source_ref"), lang="en",
                                               as_of=AS_OF)

    plain, rich = block_for(base), block_for(annotated)
    assert (plain["rendered"], plain["sha256"]) == (rich["rendered"], rich["sha256"])
    (row,) = rich["rows"]
    assert (row["period"], row["definition"], row["series"]) == (
        "2025-12-31", "Share of national electricity use by data centres", "IEA electricity tracker")
    # Two rows with the same cells: the kept one is the same whichever comes first.
    other = dict(annotated, period_end="2025-06-30", definition="Another definition")
    assert block_for(annotated, other)["rows"] == block_for(other, annotated)["rows"]


def test_definition_and_series_anchor_a_block_row():
    row = {"metric": "Share", "value": "24.6", "unit": "%", "when": "2025", "tag": "S1"}
    line = "# T\n\nThe data-centre electricity share was 31% in 2025.\n"
    assert _counts(line, rows=[row]) == {"unmatched": 1}
    assert _counts(line, rows=[dict(row, definition="Data-centre share of electricity use")]) == {"conflict": 1}
    assert _counts(line, rows=[dict(row, series="Data-centre electricity tracker")]) == {"conflict": 1}


def test_far_candidates_labels_and_fiscal_years_add_no_noise():
    makers = {"metric": "Number of humanoid robot makers", "value": "20", "unit": "", "when": "2025", "tag": "S1"}
    shipments = dict(makers, value="15,000")
    # A candidate beyond the 10x ratio neither conflicts nor makes the figure ambiguous.
    assert _counts("# T\n\nThe number of humanoid robot makers reached 18 in 2025.\n",
                   rows=(makers, shipments)) == {"conflict": 1}
    assert _counts("# T\n\nThe number of humanoid robot makers reached 21 in 2025.\n",
                   rows=(makers, dict(makers, value="25"))) == {"ambiguous": 1}
    # Label numbers, fiscal-year suffixes and year spans are no figures.
    for line in ("The number of humanoid robot makers grew in 2025 (see Figure 12 and Section 301).",
                 "The number of humanoid robot makers grew in 2025/26.",
                 "The number of humanoid robot makers grew over 2025–26.",
                 "如图12所示，2025年人形机器人厂商数量增长。"):
        assert sum(_check(f"# T\n\n{line}\n", rows=(makers, shipments))["counts"].values()) == 0, line
    assert _counts("# T\n\nThe data-centre electricity share was 31% in 2025/26.\n") == {"conflict": 1}
    # A figure with a unit mark is never a label or a fiscal-year suffix.
    zh_row = {"metric": "数据中心电力占比", "value": "24.6", "unit": "%", "when": "2025", "tag": "S1"}
    assert _counts("# T\n\n2025年数据中心电力占比代表31%。\n", rows=[zh_row]) == {"conflict": 1}
    assert _counts("# T\n\nIn 2025 – 31% was the data-centre electricity share.\n") == {"conflict": 1}


@pytest.mark.parametrize("figure", ["~10⁻⁶", "10^-6", "3×10⁸", "10<sup>-6</sup>", "3.5×10⁸", "3x10^8",
                                    "10^12", "10<sup>12</sup>"])
def test_bare_small_numbers_years_and_scientific_notation_are_no_figures(figure):
    assert sum(_check("# T\n\nThree of the 3 scenarios start in 2025 and end in 2030.\n")["counts"].values()) == 0
    # Neither the base, the mantissa nor the exponent of scientific notation is a figure.
    qubits = {"metric": "Logical qubit error rate", "value": "48", "unit": "", "when": "2025"}
    line = f"# T\n\nThe logical qubit error rate was {figure} in 2025.\n"
    assert sum(_check(line, rows=[qubits])["counts"].values()) == 0
    assert _counts("# T\n\nThe logical qubit error rate was 52 in 2025.\n", rows=[qubits]) == {"conflict": 1}


@pytest.mark.parametrize("run", ["_" * 50_000, "*" * 50_000, "*_" * 25_000, "- " + "_" * 50_000])
def test_long_emphasis_runs_are_read_in_linear_time(run):
    # The scenario-slot reading runs on the text before every figure: a long run of "*"
    # or "_" (which the old pattern backtracked over quadratically, ~15 s here) is linear.
    started = time.perf_counter()
    result = _check(f"# T\n\n{run} 31%\n")
    assert time.perf_counter() - started < 0.5
    assert {k: v for k, v in result["counts"].items() if v} == {"unmatched": 1}


def test_examples_and_matched_lines_are_capped():
    md = "# T\n\n" + "\n\n".join(["The data-centre electricity share was 31% in 2025."] * 30
                                 + ["The data-centre electricity share was 24.6% in 2025."] * 15) + "\n"
    result = _check(md)
    assert result["counts"]["conflict"] == 30 and len(result["examples"]) == vf.CHECK_EXAMPLES_MAX
    assert len(result["matched_rows"][0]) == vf.MATCHED_LINES_PER_ROW
    # The cap is visible: every use of the row is counted.
    assert result["matched_counts"] == {0: 15}


# ------------------------------------------------------------------ report agent (shadow)
_SOURCE = {"title": "Energy agency annual review", "url": "https://agency.example/review", "tier": "S1",
           "content": "The data-centre electricity share was 24.6% in 2025."}
_OTHER = {"title": "Trade body survey", "url": "https://trade.example/survey", "tier": "S3",
          "content": "The trade body puts the data-centre electricity share at 31% in 2025."}
_MARKETS = [{"market_id": "m1", "question": "Will the share exceed 30% in 2026?", "implied_yes_prob": 0.2,
             "price_at_research": 0.25, "quoted_at": "2026-06-29T10:00:00+00:00",
             "snapshot_as_of": "2026-06-29T09:00:00+00:00", "volume": 1000}]
_QUANT = [{"metric": "Data-centre electricity share", "value": "24.6", "unit": "%", "as_of_date": "2025-12-31",
           "value_type": "actual", "tier": "S1", "source": "Energy agency annual review", "source_ref": "S1",
           "source_url": "https://agency.example/review", "verification": "verified", "verified": True},
          {"metric": "Grid connection queue length", "value": "40", "unit": "months", "as_of_date": "2026-03-01",
           "value_type": "actual", "tier": "S3", "source": "Wire story", "verification": "unverified"}]
MD = ("# Forecast\n\n"
      "The data-centre electricity share was 24.6% in 2025 [S1].\n\n"
      "The trade body puts the data-centre electricity share at 31% in 2025 [S2].\n\n"
      "The grid connection queue length reached 40 months.\n")


def _forecast():
    return {"headline": "Base case leads", "confidence": "high", "confidence_rationale": "Broad evidence.",
            "scenarios": [{"name": "Base case", "probability": 0.6, "resolution_criteria": "Filing records it."},
                          {"name": "Other / status quo", "probability": 0.4,
                           "resolution_criteria": "Any other outcome."}],
            "binary_forecasts": [{"id": "F1", "statement": "Share exceeds 30% by 2030.", "probability": 0.3,
                                  "resolution_criteria": "The agency reports above 30%."}],
            "quality": {}}


def _agent(*, labelled=True, quantitative=_QUANT):
    agent = ReportAgent.__new__(ReportAgent)
    agent.output_language = "English"
    agent.research_report = ""
    agent._outline_summary = ""
    agent.sources = [_SOURCE, _OTHER]
    agent._citation_index = {"S1": _SOURCE, "S2": _OTHER}
    agent._forecast_spine = None
    agent._prediction_markets = [dict(m) for m in _MARKETS]
    agent.quantitative = [dict(r) for r in quantitative]
    agent._verified_figures = vf.build_verified_figures_block(
        agent.quantitative if labelled else [], tag_for=lambda row: row.get("source_ref"), lang="en", as_of=AS_OF)
    return agent


def _prepare(tmp_path, monkeypatch, report_id, md=MD, forecast=None):
    reports = tmp_path / "reports"
    folder = reports / report_id
    folder.mkdir(parents=True)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports), raising=False)
    (folder / "full_report.md").write_text(md, encoding="utf-8")
    (folder / "meta.json").write_text(json.dumps({"report_id": report_id, "status": "completed",
                                                  "failed_sections": [], "partial": False}), encoding="utf-8")
    (folder / "forecast.json").write_text(json.dumps(forecast or _forecast()), encoding="utf-8")
    return folder


def _audit(tmp_path, monkeypatch, report_id, *, knob, labelled=True, forecast=None, quantitative=_QUANT,
           stale_sidecar=False):
    monkeypatch.setattr(Config, "REPORT_VERIFIED_FIGURES_CHECK", knob, raising=False)
    folder = _prepare(tmp_path, monkeypatch, report_id, forecast=forecast)
    if stale_sidecar:
        (folder / "figure_provenance.json").write_text(
            json.dumps({"schema": "drf.figure_provenance/v1", "block_sha256": "old"}), encoding="utf-8")
    agent = _agent(labelled=labelled, quantitative=quantitative)
    md_sha = hashlib.sha256((folder / "full_report.md").read_bytes()).hexdigest()
    report = SimpleNamespace(markdown_content=MD)
    audit = agent._audit_final_published_markdown(report_id, report)
    agent._write_figure_provenance(report_id, report)
    # Read-only: neither the audit nor the sidecar touches the published markdown.
    assert report.markdown_content == MD
    assert hashlib.sha256((folder / "full_report.md").read_bytes()).hexdigest() == md_sha
    forecast = json.loads((folder / "forecast.json").read_text(encoding="utf-8"))
    return folder, agent, report, audit, forecast


def test_shadow_only(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True, raising=False)
    on_folder, on_agent, on_report, on, on_forecast = _audit(tmp_path, monkeypatch, "r_on", knob=True)
    off_folder, _, off_report, off, off_forecast = _audit(tmp_path, monkeypatch, "r_off", knob=False)

    # Markdown bytes, hard issues and the gate are what the knob-off run gives.
    assert on_report.markdown_content == off_report.markdown_content == MD
    assert (on_folder / "full_report.md").read_bytes() == (off_folder / "full_report.md").read_bytes()
    assert on["hard_issues"] == off["hard_issues"] and on["hard_passed"] == off["hard_passed"]
    assert on["publish_gate"]["issues"] == off["publish_gate"]["issues"]
    assert on_agent._final_audit_integrity_issues(on) == off["hard_issues"]
    # Apart from the new record (and the run's own id, time and forecast seal) the audit is the knob-off one.
    volatile = {"verified_figures", "report_id", "audited_at", "forecast_sha256"}
    assert {k: v for k, v in on.items() if k not in volatile} == {k: v for k, v in off.items() if k not in volatile}

    # The counts and the block fingerprint, in final_audit.json and forecast.json (kept by the gate).
    summary = on["verified_figures"]
    assert summary["counts"] == {"matched": 1, "conflict": 1, "ambiguous": 0, "states_unverified": 1,
                                 "market_conflict": 0, "threshold_or_probability": 0, "unmatched": 0}
    assert summary["block_sha256"] == on_agent._verified_figures["sha256"] and summary["source_discrepancies"] == 1
    assert on_forecast["quality"]["verified_figures"] == summary
    assert json.loads((on_folder / "final_audit.json").read_text())["verified_figures"] == summary
    assert "verified_figures" not in off and "verified_figures" not in off_forecast["quality"]

    # figure_provenance.json: each block row, its source and the lines that use it; market stamps.
    provenance = json.loads((on_folder / "figure_provenance.json").read_text(encoding="utf-8"))
    assert provenance["schema"] == "drf.figure_provenance/v1"
    assert provenance["block_sha256"] == summary["block_sha256"]
    assert provenance["markdown_sha256"] == hashlib.sha256(MD.encode("utf-8")).hexdigest()
    (row,) = provenance["rows"]
    assert (row["row_index"], row["metric"], row["value"], row["unit"], row["source_ref"], row["source_title"],
            row["source_url"], row["verification"]) == (
        0, "Data-centre electricity share", "24.6", "%", "S1", "Energy agency annual review",
        "https://agency.example/review", "verified")
    assert row["used_in"] == [{"line": 3, "excerpt": "The data-centre electricity share was 24.6% in 2025 [S1]."}]
    assert (row["used_in_count"], row["as_of"], row["period"]) == (1, "2025-12-31", "2025-12-31")
    assert provenance["market_rows"] == [{"market_id": "m1", "implied_yes_prob": 0.2,
                                          "quoted_at": "2026-06-29T10:00:00+00:00", "price_at_research": 0.25,
                                          "snapshot_as_of": "2026-06-29T09:00:00+00:00",
                                          "price_time": "2026-06-29T10:00:00+00:00", "price_time_basis": "requote"}]
    assert [(d["tag"], d["claim"], d["row_value"]) for d in provenance["source_discrepancies"]] == [
        ("S2", "31%", "24.6")]
    assert provenance["unmatched_numeric_claims"] == 0
    # The per-figure examples, for the manual precision review that would gate any enforcement.
    assert provenance["counts"] == summary["counts"]
    assert [(e["kind"], e["line"], e["figure"], e["cited"], e["row_index"]) for e in provenance["examples"]] == [
        ("conflict", 5, "31%", "S2", 0), ("states_unverified", 7, "40 months", None, None)]
    assert not (off_folder / "figure_provenance.json").exists()


def test_market_price_time_follows_its_knob_and_the_row(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "MARKET_ANCHOR_PRICE_TIME", False, raising=False)
    folder, *_ = _audit(tmp_path, monkeypatch, "r_no_price_time", knob=True)
    (market,) = json.loads((folder / "figure_provenance.json").read_text(encoding="utf-8"))["market_rows"]
    assert (market["quoted_at"], market["price_time"], market["price_time_basis"]) == (
        "2026-06-29T10:00:00+00:00", None, None)
    monkeypatch.setattr(Config, "MARKET_ANCHOR_PRICE_TIME", True, raising=False)
    agent = _agent()
    agent._prediction_markets = [{"market_id": "m9", "snapshot_as_of": "2026-06-29T09:00:00+00:00"}, "junk"]
    agent._write_figure_provenance("r_no_price_time", SimpleNamespace(markdown_content=MD))
    (market,) = json.loads((folder / "figure_provenance.json").read_text(encoding="utf-8"))["market_rows"]
    assert market == {"market_id": "m9", "implied_yes_prob": None, "quoted_at": None, "price_at_research": None,
                      "snapshot_as_of": "2026-06-29T09:00:00+00:00", "price_time": "2026-06-29T09:00:00+00:00",
                      "price_time_basis": "snapshot"}


def test_untagged_row_keeps_its_source_title_and_url(tmp_path, monkeypatch):
    untagged = [dict(_QUANT[0], source_ref=None), _QUANT[1]]
    folder, agent, *_ = _audit(tmp_path, monkeypatch, "r_untagged", knob=True, quantitative=untagged)
    (row,) = json.loads((folder / "figure_provenance.json").read_text(encoding="utf-8"))["rows"]
    assert (row["source_ref"], row["source_title"], row["source_url"]) == (
        None, "Energy agency annual review", "https://agency.example/review")
    # The rendered block is unchanged by the unrendered provenance fields.
    assert "source_url" not in agent._verified_figures["rendered"]
    assert agent._verified_figures["rows"][0]["source"] == "Energy agency annual review"


def test_empty_block_writes_nothing(tmp_path, monkeypatch):
    folder, _, _, audit, forecast = _audit(tmp_path, monkeypatch, "r_legacy", knob=True, labelled=False)
    assert "verified_figures" not in audit and "verified_figures" not in forecast["quality"]
    assert not (folder / "figure_provenance.json").exists()


@pytest.mark.parametrize("why", ["empty_block", "knob_off", "check_raises"])
def test_unmeasured_final_audit_drops_stale_draft_values_and_sidecar(tmp_path, monkeypatch, why):
    """A final audit that measured nothing must not re-seal the draft's counts, nor leave a
    figure_provenance.json describing other bytes."""
    if why == "check_raises":
        def boom(self, md):
            raise RuntimeError("check failed")

        monkeypatch.setattr(ReportAgent, "_verified_figures_check", boom)
    stale = {"counts": {"conflict": 99}, "block_sha256": "old", "source_discrepancies": 0}
    seeded = dict(_forecast(), quality={"verified_figures": stale})
    folder, _, _, audit, forecast = _audit(
        tmp_path, monkeypatch, f"r_stale_{why}", knob=why != "knob_off", labelled=why != "empty_block",
        forecast=seeded, stale_sidecar=True)
    assert "verified_figures" not in audit and "verified_figures" not in forecast["quality"]
    assert "verified_figures" not in json.loads((folder / "final_audit.json").read_text(encoding="utf-8"))
    assert not (folder / "figure_provenance.json").exists()


def test_failures_degrade_to_nothing(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("checker failed")

    monkeypatch.setattr(vf, "check_verified_figures", boom)
    folder, _, report, audit, forecast = _audit(tmp_path, monkeypatch, "r_boom", knob=True)
    assert report.markdown_content == MD and "verified_figures" not in audit
    assert not (folder / "figure_provenance.json").exists()


def _finalize(tmp_path, monkeypatch, report_id, *, knob):
    """forecast.json as _finalize_structured_forecast writes it for MD (offline: the spine is
    pinned, so nothing is extracted, critiqued or drawn)."""
    monkeypatch.setattr(Config, "REPORT_VERIFIED_FIGURES_CHECK", knob, raising=False)
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "FORECAST_LEDGER_DIR", str(tmp_path / "ledger"), raising=False)
    for name in ("REPORT_REPAIR_PASSES", "REPORT_FORECAST_SELF_CRITIQUE", "FORECAST_EMIT_BINARY",
                 "PREDICTION_MARKETS_ENABLED"):
        monkeypatch.setattr(Config, name, False, raising=False)
    agent = _agent()
    for key, value in {
        "graph_id": "g1", "simulation_id": "sim1", "llm": FakeLLMClient(),
        "simulation_requirement": "Will the data-centre electricity share exceed 30% by 2030?",
        "situation_brief": "", "actors": None, "scenario_label": "", "base_simulation_id": None,
        "_background_block": "", "_sources_index": "", "_signal_pack": "", "_market_pack": "",
        "_forecast_spine": _forecast(), "_forecast_spine_block": "", "_retrieval_query": None,
        "_outline_degraded": False, "_section_tool_calls": 0, "report_logger": None, "console_logger": None,
        "tools": {},
    }.items():
        setattr(agent, key, value)
    agent._finalize_structured_forecast(report_id, MD)
    path = tmp_path / "reports" / report_id / "forecast.json"
    return agent, json.loads(path.read_text(encoding="utf-8"))


def test_finalize_records_the_draft_counts_and_changes_nothing_else(tmp_path, monkeypatch):
    agent, on = _finalize(tmp_path, monkeypatch, "r_final_on", knob=True)
    expected = ReportAgent._verified_figures_summary(agent._verified_figures_check(MD))
    _, off = _finalize(tmp_path, monkeypatch, "r_final_off", knob=False)
    summary = on["quality"].pop("verified_figures")
    assert summary == expected
    assert summary["counts"]["conflict"] == 1 and summary["block_sha256"] == agent._verified_figures["sha256"]
    # Knob off: no key, and everything else is what the knob-on run wrote.
    assert "verified_figures" not in off["quality"]
    assert json.dumps(on, sort_keys=True) == json.dumps(off, sort_keys=True)


def test_finalize_survives_a_failing_check(tmp_path, monkeypatch):
    def boom(self, md):
        raise RuntimeError("check failed")

    monkeypatch.setattr(ReportAgent, "_verified_figures_check", boom)
    _, forecast = _finalize(tmp_path, monkeypatch, "r_final_boom", knob=True)
    assert forecast["scenarios"] and "verified_figures" not in forecast["quality"]


@pytest.mark.parametrize("knob", [True, False])
def test_generate_writes_the_sidecar_between_the_final_audit_and_the_translation(tmp_path, monkeypatch, knob):
    """generate_report itself: the sidecar is absent when the final audit runs, present (and
    describing the final bytes) when the translation starts, and never written with the knob off."""
    for name, value in (("REPORT_SECTION_CONCURRENCY", 1), ("REPORT_SECTION_RETRY_MAX", 0),
                        ("REPORT_STRUCTURED_FORECAST", False), ("REPORT_SIGNAL_PACK", False),
                        ("LLM_TELEMETRY_ENABLED", False), ("REPORT_EDITORIAL_LINT", False),
                        ("REPORT_CITATION_FINALIZER", False), ("REPORT_BILINGUAL", True),
                        ("REPORT_FINAL_READ_ONLY_AUDIT", True), ("REPORT_FORECAST_LEDGER", False),
                        ("REPORT_VERIFIED_FIGURES_CHECK", knob)):
        monkeypatch.setattr(Config, name, value, raising=False)
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    agent = _agent()
    for key, value in {
        "graph_id": "g1", "simulation_id": "sim_1", "simulation_requirement": "Data-centre electricity share?",
        "situation_brief": "", "actors": {"as_of_date": "2026-06-30"}, "scenario_label": "",
        "base_simulation_id": None, "_background_block": "", "_sources_index": "", "_signal_pack": "",
        "_forecast_spine_block": "", "_retrieval_query": None, "_outline_degraded": False,
        "_section_tool_calls": 0, "report_logger": None, "console_logger": None, "tools": {},
    }.items():
        setattr(agent, key, value)
    outline = ReportOutline(title="Forecast", summary="Summary", sections=[ReportSection(title="Analysis")])
    agent.plan_outline = lambda progress_callback=None, forecast_spine_block="", \
        require_forecast_structure=False: outline
    body = "The data-centre electricity share was 24.6% in 2025 [S1]. " + "A long enough analytical body. " * 20
    agent._generate_section = lambda section, outline, previous_sections, progress_callback=None, \
        section_index=0: body
    sidecar = tmp_path / "reports" / "r_generate" / "figure_provenance.json"
    calls = []

    def final_audit(report_id, report):
        calls.append(("final_audit", sidecar.exists()))
        return {}

    def bilingual(report_id, report):
        calls.append(("bilingual", sidecar.exists()))
        if sidecar.exists():
            provenance = json.loads(sidecar.read_text(encoding="utf-8"))
            calls.append(("describes_final_bytes", provenance["markdown_sha256"] == hashlib.sha256(
                report.markdown_content.encode("utf-8")).hexdigest()))
            calls.append(("used_in_count", provenance["rows"][0]["used_in_count"]))

    agent._enforce_final_publish_audit = final_audit
    agent._generate_bilingual_report = bilingual
    report = agent.generate_report(report_id="r_generate")
    assert report.status == ReportStatus.COMPLETED
    if knob:
        assert calls == [("final_audit", False), ("bilingual", True), ("describes_final_bytes", True),
                         ("used_in_count", 1)]
    else:
        assert calls == [("final_audit", False), ("bilingual", False)]


def test_knob_defaults_range_and_documentation():
    assert Config.REPORT_VERIFIED_FIGURES_CHECK is True
    assert Config.REPORT_VERIFIED_FIGURE_REL_TOL == pytest.approx(0.02)
    assert "REPORT_VERIFIED_FIGURE_REL_TOL" in RANGE_RULES
    env = open(os.path.join(os.path.dirname(__file__), "..", "..", ".env.example"), encoding="utf-8").read()
    assert "# REPORT_VERIFIED_FIGURES_CHECK=true" in env and "# REPORT_VERIFIED_FIGURE_REL_TOL=0.02" in env


def test_block_sha_matches_rendered_block():
    agent = _agent()
    assert agent._verified_figures["sha256"] == hashlib.sha256(
        agent._verified_figures["rendered"].encode("utf-8")).hexdigest()
