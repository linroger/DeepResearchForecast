"""REPORT-3 (P08 stage 1b): alias-aware probability-slot audit — the pure module.

Offline, no LLM.  The FFE1 rows are report_ffe1ea6bf50d's archived final scenarios; its
summary blockquote said "基准情景（40%）" while forecast.json held A：基准扩张 = 0.35,
and S11 (anchored on the first occurrence of the full scenario name) passed it.
"""

import logging

import pytest

from app.services import forecast_extractor as FE
from app.services import logic_number as LN
from app.services import narrative_sync as NS
from app.services.forecast_extractor import (
    BINARY_FORECAST_END_MARKER,
    BINARY_FORECAST_START_MARKER,
)


def _rows(*pairs):
    return [{"name": name, "probability": probability} for name, probability in pairs]


FFE1_ROWS = _rows(("A：基准扩张（管道打折后稳步兑现）", 0.35), ("B：电力受限", 0.30),
                  ("C：财务紧缩", 0.20), ("D：超预期上行", 0.05), ("E：其它/混合路径", 0.10))
FFE1_SUMMARY = (
    "基准情景（40%）下2030年全球IT装机容量达190–210 GW，但电力硬约束（30%）与融资紧缩（20%）"
    "构成合计50%的下行尾部。"
)


def _statuses(findings):
    return [(f["alias"], f["claimed"], f["expected_pct"], f["status"]) for f in findings]


# ------------------------------------------------------------------ aliases
def test_alias_derivation():
    aliases, stats = LN.derive_scenario_aliases(FFE1_ROWS)
    for alias in ("情景A", "A情景", "Scenario A", "scenario A", "基准扩张",
                  "基准扩张（管道打折后稳步兑现）", "A：基准扩张（管道打折后稳步兑现）"):
        assert aliases[alias] == 0, alias
    # The residual classifier counts 基准 as residual, so it would never resolve this role;
    # the role table resolves 基准情景 to the one scenario whose name holds 基准.
    assert FE._is_residual_scenario_name(FFE1_ROWS[0]["name"]) is True
    assert FE._is_residual_scenario_name("基准情景") is True
    assert aliases["基准情景"] == 0 and aliases["base case"] == 0 and aliases["baseline"] == 0
    assert aliases["上行情景"] == 3 and aliases["超预期上行"] == 3
    assert aliases["维持现状"] == 4 and aliases["其它/混合路径"] == 4
    # A residual word alone names no scenario ("Other (20%)" rows are everywhere).
    assert "其它" not in aliases
    assert stats == {"scenarios": 5, "aliases": len(aliases), "ambiguous_alias": 0}

    shared, shared_stats = LN.derive_scenario_aliases(_rows(
        ("A: Soft landing (tariffs)", 0.4), ("B: Soft landing (no tariffs)", 0.3),
        ("C: Recession", 0.3)))
    assert "Soft landing" not in shared                       # would name A and B
    assert shared["Soft landing (tariffs)"] == 0 and shared["Recession"] == 2
    assert shared_stats["ambiguous_alias"] == 1


def test_role_alias_needs_a_unique_holder():
    aliases, stats = LN.derive_scenario_aliases(_rows(
        ("A：基准扩张", 0.4), ("B：基准偏弱", 0.3), ("C：其它", 0.3)))
    assert "基准情景" not in aliases and "基准" not in aliases
    assert aliases["基准扩张"] == 0 and aliases["基准偏弱"] == 1
    assert stats["ambiguous_alias"] == 6                      # the six base-role words
    assert LN.find_probability_slots("基准情景（40%）", _rows(
        ("A：基准扩张", 0.35), ("B：基准偏弱", 0.3), ("C：其它", 0.35))) == []


def test_enumerator_forms():
    aliases, _ = LN.derive_scenario_aliases(_rows(
        ("Scenario B: Recession", 0.25), ("III. Collapse", 0.1), ("情景C：温和复苏", 0.65)))
    assert aliases["B情景"] == 0 and aliases["Recession"] == 0
    assert aliases["Scenario III"] == 1 and aliases["Collapse"] == 1
    assert aliases["情景C"] == 2 and aliases["温和复苏"] == 2


# ------------------------------------------------------------------ slots
def test_ffe1_slot():
    findings = LN.find_probability_slots(FFE1_SUMMARY, FFE1_ROWS)
    assert _statuses(findings) == [("基准情景", 40, 35, "fixable")]
    finding = findings[0]
    assert finding["code"] == "stale_probability_number"
    assert finding["scenario"] == FFE1_ROWS[0]["name"]
    assert FFE1_SUMMARY[finding["start"]:finding["end"]] == "40"
    assert len(finding["excerpt"]) <= 180 and "基准情景（40%）" in finding["excerpt"]
    fixed, applied = LN.substitute_probability_slots(FFE1_SUMMARY, findings)
    assert fixed.startswith("基准情景（35%）下2030年")
    assert fixed == FFE1_SUMMARY.replace("基准情景（40%）", "基准情景（35%）")
    assert applied == [{"scenario": FFE1_ROWS[0]["name"], "alias": "基准情景",
                        "from": "40%", "to": "35%"}]
    # "电力硬约束" / "融资紧缩" are no alias of any scenario: no finding for them.
    assert LN.find_probability_slots("电力硬约束（30%）", FFE1_ROWS) == []
    assert LN.find_probability_slots("电力硬约束（30%）与融资紧缩（20%）", FFE1_ROWS) == []
    # The number-first slot of the archived headline ("仅10%概率超预期上行", D = 0.05); the
    # sum statement's total and addends (30% + 20% = 50%) stay shielded.
    headline = FFE1_SUMMARY[:-1] + "，仅10%概率超预期上行。"
    findings = LN.find_probability_slots(headline, FFE1_ROWS)
    assert _statuses(findings) == [("基准情景", 40, 35, "fixable"), ("超预期上行", 10, 5, "fixable")]
    assert LN.substitute_probability_slots(headline, findings)[0] == headline.replace(
        "基准情景（40%）", "基准情景（35%）").replace("仅10%", "仅5%")
    # Cut off from its addends, a sum total shields its whole sentence.
    tail = "构成合计50%的下行尾部，仅10%概率超预期上行。"
    assert [(f["status"], f["guard"]) for f in LN.find_probability_slots(tail, FFE1_ROWS)] == [
        ("unresolved", "sum")]


def test_guards_and_decimal():
    rows = _rows(("A：基准扩张", 0.35), ("B：电力受限", 0.25), ("C：融资紧缩", 0.15),
                 ("E：其它", 0.25))
    for text in ("Base Case 52% target", "Base Case (52% target)", "A情景渗透率（35%）",
                 "A情景渗透率（40%）", "基准情景（30–40%）", "(30–40%)", "基准扩张：40%"):
        assert [f for f in LN.find_probability_slots(text, rows) if f["status"] == "fixable"] == [], text

    summed = "电力受限（30%）与融资紧缩（20%）合计50%"
    findings = LN.find_probability_slots(summed, rows)
    assert [(f["scenario"], f["status"], f["guard"]) for f in findings] == [
        ("B：电力受限", "unresolved", "sum"), ("C：融资紧缩", "unresolved", "sum")]
    assert all("replacement" not in f for f in findings)
    assert LN.substitute_probability_slots(summed, findings) == (summed, [])

    decimal = LN.find_probability_slots("基准情景（概率0.40）", rows)
    assert _statuses(decimal) == [("基准情景", 40, 35, "fixable")]
    assert type(decimal[0]["claimed"]) is int                 # 0.40 reads as exactly 40
    assert LN.substitute_probability_slots("基准情景（概率0.40）", decimal)[0] == "基准情景（概率0.35）"
    bare = LN.find_probability_slots("基准情景（probability .40）", rows)
    assert LN.substitute_probability_slots("基准情景（probability .40）", bare)[0] == \
        "基准情景（probability .35）"
    # A quantity word right after a colon slot is a quantity: reported, never rewritten.
    quantity = LN.find_probability_slots("基准扩张：40%概率份额", rows)
    assert [(f["status"], f["guard"]) for f in quantity] == [("unresolved", "quantity")]
    signed = LN.find_probability_slots("有+40%的概率基准扩张", rows)
    assert [(f["status"], f["guard"]) for f in signed] == [("unresolved", "quantity")]


@pytest.mark.parametrize("text, fixed", [
    ("**基准情景**（约40%）", "**基准情景**（约35%）"),
    ("基准情景 (~40%)", "基准情景 (~35%)"),
    ("基准情景（概率约 40%）", "基准情景（概率约 35%）"),
    ("Scenario A (probability ≈40%)", "Scenario A (probability ≈35%)"),
    ("Baseline (about 40%)", "Baseline (about 35%)"),
    ("A情景（40％）", "A情景（35％）"),
    ("基准扩张：40% 概率", "基准扩张：35% 概率"),
    ("基准扩张: 40.0% probability", "基准扩张: 35.0% probability"),
    ("有40%的可能性维持基准扩张", "有35%的可能性维持基准扩张"),
    ("40%的概率 **基准情景**", "35%的概率 **基准情景**"),
    ("The base case at 40% probability.", "The base case at 35% probability."),
])
def test_strict_slot_forms(text, fixed):
    rows = _rows(("A：基准扩张", 0.35), ("B：Recession", 0.40), ("C：其它", 0.25))
    findings = LN.find_probability_slots(text, rows)
    assert [f["status"] for f in findings] == ["fixable"], text
    assert LN.substitute_probability_slots(text, findings)[0] == fixed


@pytest.mark.parametrize("text", [
    "基准情景有40%的可能性",          # no strict slot: 有 between alias and number
    "Base: 40%",                      # a colon without a probability word
    "a recession (25%)",              # a name part keeps its first letter exact
    "非基准情景（60%）",               # 非 negates the alias
    "non-baseline (60%)",
    "Other (20%)",                    # a residual word alone is no alias
    "基准情景（40%，高于共识）",        # the bracket holds more than the number
    "基准情景（35%）",                  # matches the forecast
    "基准情景（36%）",                  # within the 1-point tolerance
    "基准情景（140%）",                 # not a probability
])
def test_non_slots_and_matches_give_no_finding(text):
    rows = _rows(("A：基准扩张", 0.35), ("B：Recession", 0.40), ("C：其它", 0.25))
    assert LN.find_probability_slots(text, rows) == []


@pytest.mark.parametrize("text, fixed", [
    ("价格上行（10%）", None),                  # a price move, not the upside scenario
    ("需求下行（25%）", None),
    ("高于基准（40%）", None),                  # a benchmark
    ("EPS upside (10%)", None),
    ("2030上行（10%）", None),
    ("上行（10%）情形下", "上行（5%）情形下"),
    ("在基准（40%）下", "在基准（35%）下"),
    ("The upside (10%) is thin.", "The upside (5%) is thin."),
    ("仅10%概率上行", "仅5%概率上行"),           # right after a probability word
    ("**下行**：25%的概率", "**下行**：30%的概率"),
])
def test_weak_aliases_count_only_when_free_standing(text, fixed):
    rows = _rows(("A：基准扩张", 0.35), ("B：下行", 0.30), ("D：超预期上行", 0.05),
                 ("E：其它", 0.30))
    findings = LN.find_probability_slots(text, rows)
    if fixed is None:
        assert findings == [], text
    else:
        assert [f["status"] for f in findings] == ["fixable"], text
        assert LN.substitute_probability_slots(text, findings)[0] == fixed


@pytest.mark.parametrize("text", [
    "此前基准情景（40%）偏高。",
    "基准情景（40%）已下调至35%。",
    "Originally Scenario A (40%) led.",
    "Scenario A (40%) was cut to 35%.",
])
def test_history_context_is_reported_not_rewritten(text):
    findings = LN.find_probability_slots(text, FFE1_ROWS)
    assert [(f["status"], f["guard"]) for f in findings] == [("unresolved", "history")]
    assert LN.substitute_probability_slots(text, findings) == (text, [])


def test_conflicting_slot_and_bad_inputs():
    rows = _rows(("A：基准扩张", 0.35), ("D：超预期上行", 0.05), ("E：其它", 0.60))
    # One number read as A's (colon slot) and as D's (number-first slot): left alone.
    audit = LN.audit_markdown("基准扩张：40%的概率超预期上行", rows)
    assert audit["count"] == 0 and audit["skipped"]["ambiguous_slot"] == 1
    assert LN.find_probability_slots(None, rows) == []
    assert LN.find_probability_slots("基准情景（40%）", None) == []
    assert LN.find_probability_slots("基准情景（40%）", ["not a row", {"name": 3}]) == []
    null = _rows(("A：基准扩张", None), ("E：其它", 0.6))
    assert LN.find_probability_slots("基准情景（40%）", null) == []
    assert LN.substitute_probability_slots(None, [{"status": "fixable"}]) == (None, [])


def test_substitution_skips_stale_or_overlapping_spans():
    text = "基准情景（40%），A情景（40%）"
    findings = LN.find_probability_slots(text, FFE1_ROWS)
    assert [f["status"] for f in findings] == ["fixable", "fixable"]
    moved = "X" + text
    assert LN.substitute_probability_slots(moved, findings) == (moved, [])
    overlapping = [findings[0], dict(findings[0], replacement="99")]
    fixed, applied = LN.substitute_probability_slots(text, overlapping)
    assert fixed == "基准情景（35%），A情景（40%）" and len(applied) == 1


def test_public_guards_match_the_sync():
    text = "电力受限（30%）与融资紧缩（20%）合计50%，基准情景（40%），由40%下调至35%，份额40%"
    for match in NS._INT_PERCENT_RE.finditer(text):
        start, end = match.span()
        assert NS.range_guarded(text, start, end) is NS._is_range(text, start, end)
        assert NS.quantity_guarded(text, start, end) is NS._is_quantity(text, start, end)
    spans = [m.span() for m in NS._INT_PERCENT_RE.finditer(text)]
    assert [NS.sum_guarded(text, *span) for span in spans] == [True, True, True, False, False,
                                                               False, False]
    assert NS.quantity_guarded("我们给基准扩张40%的概率", 7, 10) is True
    assert NS.quantity_guarded("我们给基准扩张40%的概率", 7, 10, ("A：基准扩张",)) is False


# ------------------------------------------------------------------ markdown
def _report(summary="> 基准情景（40%）下装机稳步兑现。"):
    return "\n".join([
        "# 2030 全球数据中心展望",
        "",
        BINARY_FORECAST_START_MARKER,
        "## 第一部分 · 二元预测",
        "| F1 | 基准情景（40%） |",
        "> 基准情景（40%）市场对照",
        BINARY_FORECAST_END_MARKER,
        "",
        summary,
        "",
        "---",
        "",
        "## 第二部分 · 框架与综合",
        "",
        "正文里A情景（40%）仍是主路径。",
        "",
        "> 基准情景（40%）——某分析师原话",
        "",
        "```text",
        "基准情景（40%）",
        "```",
        "",
        "## References",
        "",
        "1. 基准情景（40%）报告 https://example.org",
        "### 附注",
        "基准情景（40%）",
        "## 附录",
        "情景A（40%）",
    ])


def test_markdown_scope():
    md = _report()
    audit = LN.audit_markdown(md, FFE1_ROWS)
    assert [(f["alias"], md[f["start"]:f["end"]]) for f in audit["findings"]] == [
        ("基准情景", "40"), ("A情景", "40"), ("情景A", "40")]
    assert md[audit["findings"][0]["start"] - 7:audit["findings"][0]["start"]] == "> 基准情景（"
    assert (audit["count"], audit["fixable"], audit["unresolved"]) == (3, 3, 0)
    assert audit["skipped"] == {"binary_block": 5, "blockquote": 1, "fenced": 3,
                                "references": 5}

    skipped = LN.audit_markdown(md, FFE1_ROWS, skip_summary_blockquote=True)
    assert [f["alias"] for f in skipped["findings"]] == ["A情景", "情景A"]
    assert skipped["skipped"]["summary_blockquote"] == 1

    # A blockquote that is not right after the H1 (prose in between) is never the summary.
    late = md.replace("> 基准情景（40%）下装机稳步兑现。", "引言。\n> 基准情景（40%）下装机稳步兑现。")
    assert [f["alias"] for f in LN.audit_markdown(late, FFE1_ROWS)["findings"]] == ["A情景", "情景A"]
    # No H1: every blockquote is skipped.
    assert LN.audit_markdown("> 基准情景（40%）", FFE1_ROWS)["count"] == 0
    # An unterminated Part-1 marker opens nothing.
    open_marker = "# T\n\n" + BINARY_FORECAST_START_MARKER + "\n基准情景（40%）"
    assert LN.audit_markdown(open_marker, FFE1_ROWS)["fixable"] == 1


def test_audit_caps_findings_and_repair_takes_all():
    md = "# T\n\n" + "\n".join(f"第{i}段：A情景（40%）。" for i in range(30))
    capped = LN.audit_markdown(md, FFE1_ROWS)
    assert len(capped["findings"]) == LN.LOGIC_NUMBER_FINDINGS_CAP
    assert capped["count"] == capped["fixable"] == 30
    full = LN.audit_markdown(md, FFE1_ROWS, max_findings=None)
    fixed, applied = LN.substitute_probability_slots(md, full["findings"])
    assert len(applied) == 30 and "40%" not in fixed
    assert LN.audit_markdown(fixed, FFE1_ROWS)["count"] == 0


def test_s11_mismatch_strings():
    md = "# T\n\n> 基准情景（40%）\n\n正文：A情景（40%），电力受限（30%）与财务紧缩（20%）合计50%。"
    rows = _rows(("A：基准扩张", 0.35), ("B：电力受限", 0.25), ("C：财务紧缩", 0.25),
                 ("E：其它", 0.15))
    assert LN.s11_mismatches(md, rows, reference="forecast.json") == [
        "scenario 'A：基准扩张': prose 40% vs forecast.json 35%",
        "scenario 'B：电力受限': prose 30% vs forecast.json 25%",
        "scenario 'C：财务紧缩': prose 20% vs forecast.json 25%",
    ]
    long_name = "A：基准扩张（管道打折后稳步兑现，电力约束在2028年后逐步缓解）"
    assert LN.s11_mismatches("# T\n\n基准情景（40%）", _rows((long_name, 0.35), ("E：其它", 0.65)),
                             reference="spine") == [
        f"scenario '{long_name[:28]}': prose 40% vs spine 35%"]


def test_resolve_gate(caplog):
    assert [LN.resolve_gate(value) for value in ("off", " Observe ", "NUMERIC")] == \
        ["off", "observe", "numeric"]
    with caplog.at_level(logging.WARNING, logger=LN.__name__):
        assert LN.resolve_gate("report3-strict-typo") == "observe"
        assert LN.resolve_gate("report3-strict-typo") == "observe"
    warnings = [r for r in caplog.records if "report3-strict-typo" in r.getMessage()]
    assert len(warnings) == 1
