"""report_lint citation safety: lint never deletes or invents [S#] markers.

Research reports reach ``lint_report(mode="research")`` after the bridge has
finalized their citations: ``[S#]`` markers index ``sources.json`` by position
and References must equal the cited set.  Review round 3 found three lint
rules that corrupted those citations:

* C41: the pass-narration stripper closed its match on a citation's ``]`` and
  deleted ordinary ``(... pass 12 ... [S3])`` parentheticals with the marker;
* C16/C42: cross-section sentence dedup ignored differing ``[S#]`` sets and let
  the Executive Summary keep the first copy, deleting a body section's lead
  sentence (and its only citation of a source);
* C44: the bare ``(S<n>)`` variant turned legacy tier labels ``(S1)``/``(S4)``
  into invented (and dangling) citations.

The same invariant also covers two neighbours found while fixing them: the
variant normalizer collapsed ``[S2/S3]`` to ``[S2]``, and research mode deleted
a cited line that ended with a colon.  A research-mode guard reverts any rule
that would still change the body's cited sources or their first-appearance
order.

Every regression test here fails on the pre-fix ``report_lint``; the
legitimate-cleanup checks (genuine pass narration is still stripped) pass on
both.  Pure functions, offline.
"""

from __future__ import annotations

import re

import pytest

from app.services import report_lint as rl
from app.services.report_lint import lint_report


def _body(md: str) -> str:
    return md.split("\n## References")[0].split("\n## 参考来源")[0]


def _markers(md: str) -> list[str]:
    return re.findall(r"\[S\d+\]", _body(md))


def _cited(md: str) -> list[int]:
    return sorted({int(n) for n in re.findall(r"\[S(\d+)\]", _body(md))})


# ───────────────────────── C41: pass-narration stripper ─────────────────────────

SHUTDOWN_REPORT = """# Will the US federal government shut down on 1 October 2026?

## Executive Summary

Shutdown risk is elevated (Congress must pass 12 appropriations bills by 30 September [S1]). A continuing resolution remains the modal path [S2].

## Legislative calendar

The House schedule leaves nine voting days [S2]. Leadership aims to pass 3 minibus packages first (the Senate needs 60 votes to pass 1 package [S3]).

## References

- [S1] Appropriations status table — https://crs.example.gov/a (tier 1; fetched)
- [S2] House floor schedule — https://house.example.gov/b (tier 1; fetched)
- [S3] Senate cloture rules — https://senate.example.gov/c (tier 1; fetched)
"""


def test_research_lint_keeps_cited_parentheticals_that_mention_pass_n():
    cleaned, rep = lint_report(SHUTDOWN_REPORT, "English", mode="research")

    assert cleaned == SHUTDOWN_REPORT
    assert rep["pass_narration"]["stripped"] == 0
    assert _markers(cleaned) == _markers(SHUTDOWN_REPORT)
    assert _cited(cleaned) == [1, 2, 3]
    assert "(Congress must pass 12 appropriations bills by 30 September [S1])" in cleaned
    assert "(the Senate needs 60 votes to pass 1 package [S3])" in cleaned


def test_pass_bracket_never_closes_on_a_citation_bracket():
    for line in (
        "Funding lapses unless the chamber acts (see Pass 3 notes [S12]) this week.",
        "Funding lapses unless the chamber acts (… pass 3 … [S12]) this week.",
        "Funding lapses unless the chamber acts （第 3 轮 Pass 3 结论 [S12]） this week.",
    ):
        out, stripped, _flagged = rl.strip_pass_narration(line)
        assert out == line and stripped == 0, line


def test_pass_bracket_keeps_a_bracket_that_carries_a_source_id():
    line = "The regulator approved the merger [S37 Pass 4] after a long review."
    out, stripped, flagged = rl.strip_pass_narration(line)
    assert out == line and stripped == 0
    assert flagged == 1  # still surfaced for the upstream rewrite pass


def test_pass_bracket_keeps_verb_usage_of_pass_n():
    line = "Passage is uncertain (the Senate needs 60 votes to pass 1 package) this term."
    out, stripped, _flagged = rl.strip_pass_narration(line)
    assert out == line and stripped == 0


def test_pass_bracket_still_strips_genuine_pass_narration():
    md = ("Big Fund III ¥344B [Pass 2 working notes] anchored the estimate.\n"
          "Maine polls tightened (WGME; Pass 4) in April.\n"
          "Turnout fell to 60% (per Pass 5 E1) in the primary.\n"
          "Bloomberg reported the deal (per the working notes) on Monday.\n"
          "Capacity estimates diverge (cited in pass 4 contradictions notes) by 20 GW.\n"
          "该估计已确认（经 Pass3 验证）。\n"
          "Pass 4 of the broader dossier documented the contradiction.\n")
    out, stripped, flagged = rl.strip_pass_narration(md)

    assert stripped == 6
    for gone in ("[Pass 2 working notes]", "(WGME; Pass 4)", "(per Pass 5 E1)",
                 "(per the working notes)", "(cited in pass 4 contradictions notes)",
                 "（经 Pass3 验证）"):
        assert gone not in out
    assert "Big Fund III ¥344B anchored the estimate." in out
    assert "Pass 4 of the broader dossier" in out  # prose mention: flagged only
    assert flagged == 1


# ───────────────────── C16/C42: cross-section sentence dedup ─────────────────────

_LEAD = ("Installed data-centre capacity reached 176 GW at the end of 2023 "
         "according to the operator census")


def test_dedup_never_strips_a_body_lead_restated_by_the_executive_summary():
    md = f"""# Q

## Executive Summary

{_LEAD} [S1]. Growth is expected to continue through 2027 on hyperscaler plans [S2].

## Market Baseline

{_LEAD} [S1]. Operators added 26 GW in 2023 alone, the largest annual increase [S2].

## References

- [S1] Operator census — https://census.example.org/a
- [S2] Grid operator note — https://grid.example.org/b
"""
    cleaned, rep = lint_report(md, "English", mode="research")

    assert rep["duplicate_sentences_removed"] == 0
    assert cleaned == md
    baseline = cleaned.split("## Market Baseline")[1]
    assert baseline.lstrip().startswith(_LEAD)


def test_dedup_keeps_restated_sentences_whose_citations_differ():
    md = f"""# Q

## Executive Summary

{_LEAD} [S1]. Demand growth is expected to continue through 2027 on capex plans [S1].

## Market Baseline

{_LEAD} [S2]. Grid connection queues now exceed 40 months in several regions [S1].

## Outlook

{_LEAD} [S3]. Regulators are reviewing interconnection rules this year [S1].

## References

- [S1] Agency survey — https://agency.example.org/survey
- [S2] Operator census — https://census.example.org/2023
- [S3] Utility filing — https://ferc.example.gov/c
"""
    cleaned, rep = lint_report(md, "English", mode="research")

    assert rep["duplicate_sentences_removed"] == 0
    assert cleaned == md
    assert _cited(cleaned) == [1, 2, 3]


def test_dedup_still_removes_identical_body_duplicates_with_identical_citations():
    dup = ("The equipment segment reproduces the same structural claim about its own "
           "architecture across the entire industry every cycle [S2][S1].")
    same_set = dup.replace("[S2][S1]", "[S1, S2]")
    md = (f"## Section A\n\n{dup} Unique tail one [S1].\n\n"
          f"## Section B\n\n{same_set} Unique tail two [S3].\n")
    out, removed = rl.dedup_duplicate_sentences(md)

    assert removed == 1
    assert out.count("equipment segment reproduces") == 1
    assert "Unique tail one [S1]." in out and "Unique tail two [S3]." in out
    assert rl._cited_sequence(out) == rl._cited_sequence(md)


def test_dedup_scopes_chinese_executive_summary_separately():
    lead = ("截至二零二三年底全球数据中心装机容量达到一百七十六吉瓦且仍在以每年两位数的速度"
            "持续增长扩张之中并将延续到二零二七年年底之前的整个预测窗口")
    assert len(rl._norm_sentence(f"{lead}[S1]。")) >= 60  # long enough to be deduped
    md = (f"## 执行摘要\n\n{lead}[S1]。\n\n"
          f"## 市场基线\n\n{lead}[S1]。运营商在二零二三年新增二十六吉瓦[S2]。\n\n"
          f"## 展望\n\n{lead}[S1]。监管机构正在审查并网规则[S3]。\n")
    out, removed = rl.dedup_duplicate_sentences(md)

    # The body keeps its lead despite the summary copy; the second body copy
    # (same text, same citation set) is still a removable duplicate.
    assert removed == 1
    assert out.split("## 市场基线")[1].split("## 展望")[0].count(lead) == 1
    assert out.split("## 展望")[1].count(lead) == 0
    assert "监管机构正在审查并网规则[S3]。" in out


def test_summary_heading_classifier_is_bounded():
    for title in ("Executive Summary", "1. Executive Summary", "**Key Takeaways**",
                  "TL;DR", "执行摘要", "一、执行摘要与核心判断", "摘要"):
        assert rl._is_summary_heading(title), title
    for title in ("Market Baseline", "Summary statistics of grid queues", "Outlook",
                  "Scenario probabilities", "市场基线"):
        assert not rl._is_summary_heading(title), title


# ───────────────────────── C44: (S<n>) tier labels ─────────────────────────

LEGACY_TIER_REPORT = """# Research report

## Evidence quality

The evidence base is dominated by primary (S1) filings; secondary (S2) press coverage and one low-tier (S4) blog were discounted. Capacity reached 176 GW in 2023 [S3].

## References

- [S1] Utility filing — https://ferc.example.gov/a
- [S2] Reuters story — https://news.example.com/b
- [S3] IEA capacity — https://iea.example.org/c
"""


def test_research_lint_does_not_turn_tier_labels_into_citations():
    cleaned, rep = lint_report(LEGACY_TIER_REPORT, "English", mode="research")

    assert rep["citation_variants"] == 0
    assert cleaned == LEGACY_TIER_REPORT
    assert _markers(cleaned) == ["[S3]"]
    assert "primary (S1) filings" in cleaned and "low-tier (S4) blog" in cleaned


def test_research_lint_still_normalizes_bracketed_citation_variants():
    md = "Backed by 【S3】 and [S2-d] and [S1 / fact 8]; tier (S1) sources dominate.\n"
    cleaned, rep = lint_report(md, "English", mode="research")

    assert rep["citation_variants"] == 3
    assert cleaned == "Backed by [S3] and [S2] and [S1]; tier (S1) sources dominate.\n"


def test_citation_variant_normalization_keeps_every_source_id():
    md = "Both agencies agree [S2/S3]; context [S68-context] and [S1 / GS2024 fact 8].\n"
    expected = "Both agencies agree [S2][S3]; context [S68] and [S1].\n"
    out, n = rl.normalize_citation_variants(md)
    assert n == 3 and out == expected
    for mode in ("research", "final"):
        cleaned, rep = lint_report(md, "English", mode=mode)
        assert rep["citation_variants"] == 3 and cleaned == expected, mode
    assert rep["citation_guard_rules"] == []
    assert rl._cited_sequence(expected) == rl._cited_sequence(md) == ["2", "3", "68", "1"]


def test_final_lint_keeps_normalizing_paren_citation_variant():
    out, n = rl.normalize_citation_variants("Demand doubled (S2) last year.\n")
    assert n == 1 and out == "Demand doubled [S2] last year.\n"
    out, n = rl.normalize_citation_variants("Demand doubled (S2) last year.\n",
                                            paren_labels=False)
    assert n == 0 and out == "Demand doubled (S2) last year.\n"


# ───────────────────── research-mode citation invariant ─────────────────────

def test_research_lint_keeps_a_cited_line_that_ends_with_a_colon():
    md = ("## Supply\n\nThe agency notes that demand will double by 2030 [S2]:\n\n"
          "## Next Section\n\nNormal prose continues here [S1].\n")
    cleaned, rep = lint_report(md, "English", mode="research")

    assert rep["dangling_attributions"] == 0
    assert "demand will double by 2030 [S2]:" in cleaned
    # The final report keeps its historical cleanup of dangling intros.
    final_out, n = rl.remove_dangling_attributions(md)
    assert n == 1 and "[S2]" not in final_out


def test_citation_guard_reverts_a_rule_that_would_drop_a_citation():
    md = ("## Drivers\n\nPricing power persists "
          "(According to：ASML Holding N.V. --[SUPPLIES]--> TSMC；[S2]) through 2027 [S1].\n")
    # The edge-dump rewrite on its own drops the "[S2]" piece of the payload.
    rewritten, converted, _dangling = rl.rewrite_edge_dumps(md, "English")
    assert converted == 1 and "[S2]" not in rewritten

    cleaned, rep = lint_report(md, "English", mode="research")

    assert rep["citation_guard_rules"] == ["edge_dumps"]
    assert rep["citation_guard_reverts"] == 1 and rep["edge_dumps"] == 0
    assert cleaned == md


def test_research_lint_preserves_the_cited_sequence_while_cleaning():
    md = f"""# Q

## Executive Summary

{_LEAD} [S1]. Shutdown risk is elevated (Congress must pass 12 appropriations bills by 30 September [S3]).

## Market Baseline

{_LEAD} [S2]. Tier-one (S1) filings dominate [citation:census](https://census.example.org/a) the evidence [Pass 2 working notes] base [S1].

## References

- [S1] Operator census — https://census.example.org/a
- [S2] Grid operator note — https://grid.example.org/b
- [S3] Budget office brief — https://budget.example.gov/c
"""
    cleaned, rep = lint_report(md, "English", mode="research")

    assert rep["citation_residue"] == 1 and rep["pass_narration"]["stripped"] == 1
    assert rep["citation_variants"] == 0 and rep["duplicate_sentences_removed"] == 0
    assert rep["citation_guard_rules"] == []
    assert "[citation:" not in cleaned and "[Pass 2 working notes]" not in cleaned
    assert _markers(cleaned) == _markers(md)
    assert rl._cited_sequence(cleaned) == ["1", "3", "2"]
    assert cleaned.count(_LEAD) == 2 and "appropriations" in cleaned
    assert "Tier-one (S1) filings dominate the evidence base [S1]." in cleaned


def test_final_mode_reports_an_empty_citation_guard():
    _out, rep = lint_report("Plain prose [S1].\n", "English", mode="final")
    assert rep["citation_guard_rules"] == [] and rep["citation_guard_reverts"] == 0


# ------------------------------------------------ follow-up review: residual citation losses

_SHARED = ("The broader grid-scale storage market grew by roughly forty percent in 2025 across every "
           "major region.")


def test_dedup_keeps_a_citation_written_after_a_space():
    """'claim. [S2] Next sentence.': the [S2] belongs to the claim, so removing
    a later duplicate of the next sentence must not take it away."""
    md = ("## Sodium\n\nCATL began volume shipments of second-generation sodium-ion cells in 2025. [S2] "
          + _SHARED + "\n\n## Flow\n\nVanadium flow projects remain sub-scale. [S2] " + _SHARED
          + "\n\n## References\n\n- [S2] b\n")
    out, rep = lint_report(md, "English", mode="research")
    assert "Vanadium flow projects remain sub-scale. [S2]" in out
    assert out.count("[S2]") == md.count("[S2]")


def test_guard_reverts_a_rule_that_drops_a_repeated_citation():
    md = ("## Findings\n\nStorage demand is rising [S3].\n\n"
          "The alliance holds (According to: CATL --[ALLIED_WITH]--> BYD; [S3]).\n\n"
          "## References\n\n- [S3] BNEF\n")
    out, rep = lint_report(md, "English", mode="research")
    assert out.count("[S3]") == md.count("[S3]")
    assert "edge_dumps" in rep["citation_guard_rules"]


def test_guard_counts_body_text_after_the_references_block():
    md = ("## Findings\n\nDemand rose [S1].\n\n## References\n\n- [S1] a\n\n"
          "## Watchable Indicators\n\nThe alliance holds (According to: CATL --[ALLIED_WITH]--> BYD; [S1]).\n")
    out, rep = lint_report(md, "English", mode="research")
    assert out.count("[S1]") == md.count("[S1]")


@pytest.mark.parametrize("marker, expected", [
    ("[S3-5]", "[S3][S4][S5]"), ("[S3-S5]", "[S3][S4][S5]"), ("【S3-5】", "[S3][S4][S5]"),
    ("[S3–S5]", "[S3][S4][S5]"), ("[S7-3]", "[S7][S3]"),
])
def test_citation_ranges_keep_every_source(marker, expected):
    out, _ = rl.normalize_citation_variants(f"Storage reached 112 GW in 2025 {marker}.", paren_labels=False)
    assert expected in out


def test_em_dash_citation_ranges_expand_too():
    out, _ = rl.normalize_citation_variants("Storage reached 112 GW in 2025 [S3—5].", paren_labels=False)
    assert "[S3][S4][S5]" in out
