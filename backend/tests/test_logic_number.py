"""REPORT-3 (P08 stage 1b): alias-aware probability-slot audit — the pure module.

Offline, no LLM.  The FFE1 rows are report_ffe1ea6bf50d's archived final scenarios; its
summary blockquote said "基准情景（40%）" while forecast.json held A：基准扩张 = 0.35,
and S11 (anchored on the first occurrence of the full scenario name) passed it.
"""

import logging
import time
from collections import Counter

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
EN_ROWS = _rows(("A: Base case", 0.45), ("B: Bull case", 0.20), ("C: Bear case", 0.35))
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


def test_role_keyword_must_be_a_tag():
    """A role keyword inside a description or after a comparison names no role (review
    round 2): "other" in a bull case's description, "低于基准的放缓"."""
    rows = _rows(("Soft landing", 0.5), ("Bull case: rates fall and other regions follow", 0.2),
                 ("Recession", 0.3))
    aliases, stats = LN.derive_scenario_aliases(rows)
    assert "status quo" not in aliases and aliases["bull case"] == 1
    assert stats["ambiguous_alias"] == 5                      # the five residual-role words
    assert LN.find_probability_slots("The status quo (50%) persists.", rows) == []
    for name in ("A：低于基准的放缓", "A：低于基准", "A: Below baseline"):
        comparative = _rows((name, 0.3), ("B：高增长", 0.7))
        assert "基准情景" not in LN.derive_scenario_aliases(comparative)[0], name
        assert LN.find_probability_slots("基准情景（50%）仍是主路径", comparative) == [], name
    # A description after a colon or a dash is no tag.
    described, _ = LN.derive_scenario_aliases(_rows(
        ("A: Base case — upside capped by power", 0.6), ("B: Recession: others follow", 0.4)))
    assert "upside" not in described and "status quo" not in described


@pytest.mark.parametrize("name, role_alias", [
    # Real names from archived forecasts: the tag opens the core (after a spaced or glued
    # enumerator), closes a part (a scenario word may follow) or opens a bracket / slash.
    ("A：基准扩张（管道打折后稳步兑现）", "基准情景"),
    ("A 基准情景：管道打折兑现，债务化扩张延续", "基准情景"),
    ("A基准扩张：管道部分兑现，债务化融资延续", "基准情景"),
    ("D超预期上行：AI收入爆发+电力瓶颈突破", "上行情景"),
    ("D 上行情景：AI收入超预期+芯片/电力约束双双解除", "上行情景"),
    ("情景A维持现状", "status quo"),
    ("E. 混合下行/其它：电力与融资约束叠加或维持现状", "兜底"),
    ("Managed Fragmentation (baseline equilibrium)", "base case"),
    ("Oscillating Bipolar Equilibrium (Chokepoint Reflexivity, base case)", "baseline"),
    ("Managed Interdependence / Muddle-Through (status-quo baseline)", "base case"),
    ("Managed Interdependence / Muddle-Through (status-quo baseline)", "status quo"),
    ("Actuator/Battery Chokepoint Bear Case", "bear case"),
    ("Credit-Market Tail — Deep-Bear / 2000-Magnitude ($0.8–1.2T)", "downside"),
    ("B: Mild downside", "bear case"),
    ("Other / Status Quo", "status quo"),
    ("S2 — AI泡沫局部破裂+成熟节点灾难性过剩（BEAR）", "下行情景"),
])
def test_role_tags_in_real_names(name, role_alias):
    aliases, stats = LN.derive_scenario_aliases(_rows((name, 0.6), ("Z：高增长", 0.4)))
    assert aliases.get(role_alias) == 0, name
    assert stats["ambiguous_alias"] == 0, name


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
    # A conditional opener whose condition is the slot's own scenario keeps the slot.
    ("若基准情景（40%）成立，则装机稳步兑现", "若基准情景（35%）成立，则装机稳步兑现"),
    ("如果进入基准情景（40%），电力约束缓解", "如果进入基准情景（35%），电力约束缓解"),
    ("If the base case (40%) holds, capex rises.", "If the base case (35%) holds, capex rises."),
    ("若干年后基准情景（40%）仍是主路径", "若干年后基准情景（35%）仍是主路径"),       # 若干 is no 若
    ("在基准扩张（40%）路径下装机稳步兑现", "在基准扩张（35%）路径下装机稳步兑现"),
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


WEAK = "weak_alias"                     # reported as unresolved, never rewritten


@pytest.mark.parametrize("text, fixed", [
    ("价格上行（10%）", None),                  # a price move, not the upside scenario
    ("需求下行（25%）", None),
    ("高于基准（40%）", None),                  # a benchmark
    ("EPS upside (10%)", None),
    ("2030上行（10%）", None),
    ("租金维持现状（70%）", None),               # a rent that stays put
    # Free-standing, but with no scenario signal: a level, a price move or a benchmark.
    ("在基准（40%）下", WEAK),
    ("The upside (10%) is thin.", WEAK),
    ("油价方面，上行（10%）空间有限", WEAK),
    ("相对基准（40%）的偏离", WEAK),
    ("与基准（40%）相比", WEAK),
    ("情景概率：**基准**（40%）；**上行**（10%）", [WEAK, WEAK]),
    # A scenario word right after the slot or the alias, a probability word in the slot,
    # or a label position names the scenario.
    ("上行（10%）情形下", "上行（5%）情形下"),
    ("维持现状（10%）情形下", "维持现状（30%）情形下"),
    ("在基准路径（40%）下", "在基准路径（35%）下"),
    ("the upside case (10%)", "the upside case (5%)"),
    ("油价方面，上行（概率10%）空间有限", "油价方面，上行（概率5%）空间有限"),
    ("**下行**：25%的概率", "**下行**：30%的概率"),
    ("- 上行（10%）：需求超预期", "- 上行（5%）：需求超预期"),
    ("2、上行（10%）：需求超预期", "2、上行（5%）：需求超预期"),
    ("## 上行（10%）", "## 上行（5%）"),
    ("| 下行（25%） | 融资收紧 |", "| 下行（30%） | 融资收紧 |"),
    ("> 上行（10%）：需求超预期", "> 上行（5%）：需求超预期"),
    ("情景拆分，**上行**（10%）：需求超预期", "情景拆分，**上行**（5%）：需求超预期"),
    ("前言。上行（10%）：需求超预期", WEAK),     # mid-line and not bold: no label
    # After "N%的概率" a weak alias needs a scenario word right after it.
    ("仅10%概率走向上行情景", "仅5%概率走向上行情景"),
    ("有40%的概率走向基准路径", "有35%的概率走向基准路径"),
    ("仅10%概率上行", None),
    ("油价有40%的概率上行", None),               # a price move
    ("电价在2027年有60%的可能性上行", None),
    ("需求有40%的概率下行", None),
    ("托管租金有70%的概率维持现状", None),
    ("有40%的概率维持基准水平", None),           # a level, not the base case
])
def test_weak_aliases_need_a_scenario_signal(text, fixed):
    rows = _rows(("A：基准扩张", 0.35), ("B：下行", 0.30), ("D：超预期上行", 0.05),
                 ("E：其它", 0.30))
    findings = LN.find_probability_slots(text, rows)
    if fixed is None:
        assert findings == [], text
    elif fixed == WEAK or isinstance(fixed, list):
        guards = fixed if isinstance(fixed, list) else [fixed]
        assert [(f["status"], f["guard"]) for f in findings] == [
            ("unresolved", guard) for guard in guards], text
        assert LN.substitute_probability_slots(text, findings) == (text, [])
    else:
        assert [f["status"] for f in findings] == ["fixable"], text
        assert LN.substitute_probability_slots(text, findings)[0] == fixed


@pytest.mark.parametrize("text", [
    "EV share rises from the baseline (18%) to 45% by 2035.",
    "Penetration is above the baseline (18%).",
    "We see the upside (12%) to our price target as limited.",
])
def test_weak_english_aliases_are_never_rewritten(text):
    """The review probes: 'baseline' / 'upside' stand free after a determiner but name
    a level or a price target; the default-on repair must not write the scenario's
    probability over them."""
    rows = _rows(("Base case: steady adoption", 0.45), ("Upside: policy acceleration", 0.25),
                 ("Downside: stall", 0.30))
    md = "# EV outlook\n\n" + text + "\n"
    audit = LN.audit_markdown(md, rows, skip_summary_blockquote=True, max_findings=None)
    assert (audit["fixable"], audit["unresolved"]) == (0, 1)
    assert audit["findings"][0]["guard"] == "weak_alias"
    assert LN.substitute_probability_slots(md, audit["findings"]) == (md, [])
    # The strong role words still name the scenarios.
    assert _statuses(LN.find_probability_slots("The base case (40%) holds.", rows)) == [
        ("base case", 40, 45, "fixable")]


def test_scenario_word_may_follow_an_alias():
    rows = _rows(("A：基准扩张", 0.35), ("B：Recession", 0.40), ("C：其它", 0.25))
    for text, fixed in (("基准扩张情景（40%）", "基准扩张情景（35%）"),
                        ("**Recession** scenario (30%)", "**Recession** scenario (40%)"),
                        ("Recession scenario at 30% probability",
                         "Recession scenario at 40% probability"),
                        ("基准扩张路径：40%概率", "基准扩张路径：35%概率")):
        findings = LN.find_probability_slots(text, rows)
        assert [f["status"] for f in findings] == ["fixable"], text
        assert LN.substitute_probability_slots(text, findings)[0] == fixed


@pytest.mark.parametrize("text, rows, guard", [
    ("此前基准情景（40%）偏高。", FFE1_ROWS, "history"),
    ("基准情景（40%）已下调至35%。", FFE1_ROWS, "history"),
    ("Originally Scenario A (40%) led.", FFE1_ROWS, "history"),
    ("Scenario A (40%) was cut to 35%.", FFE1_ROWS, "history"),
    ("基准情景（40%）→ 35%", FFE1_ROWS, "history"),
    ("基准情景（40%）较上一版下调5个百分点", FFE1_ROWS, "history"),
    ("上季度基准情景（40%）偏高。", FFE1_ROWS, "history"),
    ("Last quarter's base case (55%) was higher.", EN_ROWS, "history"),
    ("Base case (40%), down from 45%.", EN_ROWS, "history"),
    # Revision narratives (review round 2): an earlier draft, a move verb earlier in the
    # clause, or a "to N%" right after the slot.
    ("The pre-mortem trimmed the bull case (35%) to 30%.", EN_ROWS, "history"),
    ("The critique trimmed the bull case (35%) sharply.", EN_ROWS, "history"),
    ("相比初版报告中基准情景（40%）的判断，本版下调至35%。", FFE1_ROWS, "history"),
    ("原预测的基准情景（40%）偏乐观，红队批判后降至35%。", FFE1_ROWS, "history"),
    ("Before the red-team critique, the base case (40%) looked too high.", EN_ROWS, "history"),
    ("In the first draft, the base case (40%) looked too high.", EN_ROWS, "history"),
    ("批判前基准情景（40%）偏高。", FFE1_ROWS, "history"),
    ("我们将基准情景（40%）的概率下调。", FFE1_ROWS, "history"),
    ("Scenario A (40%) to 35% after the critique.", FFE1_ROWS, "history"),
    # Markets and outside forecasters: never the pipeline's own scenario numbers.
    ("高盛的基准情景（60%概率）", FFE1_ROWS, "market"),
    ("据IEA，基准情景（60%）", FFE1_ROWS, "market"),
    ("市场隐含的基准情景（60%）", FFE1_ROWS, "market"),
    ("基准情景（60%）（高盛）", FFE1_ROWS, "market"),
    ("Consensus base case (60%)", EN_ROWS, "market"),
    ("Polymarket prices the bull case at 30% probability", EN_ROWS, "market"),
    ("某分析师称“基准情景（60%）下装机放缓”", FFE1_ROWS, "market"),
    # Someone else's words are never edited.
    ("他写道：“基准情景（60%）下装机放缓”", FFE1_ROWS, "quote"),
    ("「基准情景（60%）」", FFE1_ROWS, "quote"),
    ('He wrote "the bear case (60%) is underpriced".', EN_ROWS, "quote"),
    # A conditional probability is not the scenario's own.
    ("若进入电力受限情景，则有40%的概率出现财务紧缩", FFE1_ROWS, "conditional"),
    ("在B情景下，有60%的概率进入财务紧缩", FFE1_ROWS, "conditional"),
    ("在B情景下有60%的概率进入财务紧缩", FFE1_ROWS, "conditional"),
    ("若电力受限，财务紧缩（60%概率）随之而来", FFE1_ROWS, "conditional"),
    ("If the bull case fails, the bear case (60%) takes over.", EN_ROWS, "conditional"),
    # Review round 3: a condition noun with a position but without 在, 情况, 当…时 and a
    # clause ending in 时 / 后 open a condition too; an opener that closes its condition
    # never names the slot after it.
    ("电力受限情景下，有40%的概率出现财务紧缩", FFE1_ROWS, "conditional"),
    ("在电力受限的情况下，有60%的可能性出现财务紧缩", FFE1_ROWS, "conditional"),
    ("电力受限的情况下有60%的可能性出现财务紧缩", FFE1_ROWS, "conditional"),
    ("B情景下，有40%的概率出现财务紧缩", FFE1_ROWS, "conditional"),
    ("电力受限情景中，有40%的概率出现财务紧缩", FFE1_ROWS, "conditional"),
    ("当电力受限时，有40%的概率出现财务紧缩", FFE1_ROWS, "conditional"),
    ("电力受限条件下，有40%的概率出现财务紧缩", FFE1_ROWS, "conditional"),
    ("B情景成真后，有40%的概率出现财务紧缩", FFE1_ROWS, "conditional"),
    ("电力受限时，有40%的概率出现财务紧缩", FFE1_ROWS, "conditional"),
    ("在这种情况下，有40%的概率出现财务紧缩", FFE1_ROWS, "conditional"),
    ("在高利率情景下，财务紧缩（60%）成为主导。", FFE1_ROWS, "conditional"),
    ("电力受限时，财务紧缩（60%）成为主导。", FFE1_ROWS, "conditional"),
    # A number-first slot after another scenario's bare mention; a set of scenarios still
    # conditions a number-first slot ("conditional on their union").
    ("B情景成真，有40%的概率出现财务紧缩", FFE1_ROWS, "conditional"),
    ("在两种情景下，有40%的概率出现财务紧缩", FFE1_ROWS, "conditional"),
    # Someone else's scenario, read from the structure, not from a list of forecasters.
    ("McKinsey's base case (60%)", EN_ROWS, "attributed"),
    ("the Fed's base case (60%)", EN_ROWS, "attributed"),
    ("Rystad's base case (60%)", EN_ROWS, "attributed"),
    ("Wood Mackenzie's base case (60%)", EN_ROWS, "attributed"),
    ("their base case (60%)", EN_ROWS, "attributed"),
    ("the study's base case (60%)", EN_ROWS, "attributed"),
    ("中金的基准情景（50%）偏乐观", FFE1_ROWS, "attributed"),
    ("麦肯锡基准情景（40%）", FFE1_ROWS, "attributed"),
    ("国网能源研究院的基准情景（40%）", FFE1_ROWS, "attributed"),
    ("国网能源研究院基准情景（40%）", FFE1_ROWS, "attributed"),
    ("McKinsey基准情景（40%）", FFE1_ROWS, "attributed"),
    ("概率最高的基准情景（40%）", FFE1_ROWS, "attributed"),
    # Chinese move verbs right before the alias, a year or 历史上 in the slot's clause.
    ("我们上调基准情景（40%）", FFE1_ROWS, "history"),
    ("上调基准情景（40%）的权重", FFE1_ROWS, "history"),
    ("2025年基准情景（40%）", FFE1_ROWS, "history"),
    ("2025年我们的基准情景（40%）", FFE1_ROWS, "history"),
    ("历史上基准情景（40%）", FFE1_ROWS, "history"),
    # A size word right after the slot.
    ("a bear case (25%) drawdown", EN_ROWS, "quantity"),
    ("Our bear case (25%) drawdown is shallow.", EN_ROWS, "quantity"),
])
def test_guarded_contexts_are_reported_not_rewritten(text, rows, guard):
    findings = LN.find_probability_slots(text, rows)
    assert [(f["status"], f["guard"]) for f in findings] == [("unresolved", guard)], text
    assert "replacement" not in findings[0]
    assert LN.substitute_probability_slots(text, findings) == (text, [])


def test_history_cues_stay_in_their_place():
    """A "to / 到 N%" counts only right after the slot, and 把 / 将 only with a move verb:
    the base case's own stale probability is still repaired."""
    for text in ("基准情景（40%）下电动车在2030年达到45%。", "基准情景（40%）下装机在2030年前回升到45%。",
                 "我们将基准情景（40%）作为主路径。", "The base case (40%) sees EVs rise to 45%."):
        rows = EN_ROWS if text.startswith("The") else FFE1_ROWS
        assert [f["status"] for f in LN.find_probability_slots(text, rows)] == ["fixable"], text


def test_the_reports_own_scenario_stays_fixable():
    """The attributed, conditional and history guards leave the report's own slots alone:
    first person, the report or a chapter as owner, a set of scenarios an enumeration
    ranks, a year outside the slot's clause, and 当 / 时 / 后 words that open nothing."""
    for text, rows in (
            ("our base case (40%)", EN_ROWS), ("Our base case (40%) holds.", EN_ROWS),
            ("this report's base case (40%)", EN_ROWS), ("our model's base case (40%)", EN_ROWS),
            ("today's base case (40%)", EN_ROWS),
            ("我们的基准情景（40%）", FFE1_ROWS), ("本报告的基准情景（40%）", FFE1_ROWS),
            ("预测骨架中的基准情景（40%）", FFE1_ROWS), ("第四章的基准情景（40%）", FFE1_ROWS),
            ("Q3的基准情景（40%）", FFE1_ROWS),
            ("在四个情景中，基准情景（40%）概率最高。", FFE1_ROWS),
            ("所有情景中，基准情景（40%）概率最高。", FFE1_ROWS),
            ("在三种情景下，基准情景（40%）概率最高。", FFE1_ROWS),
            ("到2030年，基准情景（40%）下装机达到200 GW。", FFE1_ROWS),
            ("相当于电力受限时的水平，基准情景（40%）仍占主导。", FFE1_ROWS),
            ("同时，基准情景（40%）仍占主导。", FFE1_ROWS),
            ("最后，基准情景（40%）仍占主导。", FFE1_ROWS),
            ("当前基准情景（40%）仍占主导。", FFE1_ROWS)):
        findings = LN.find_probability_slots(text, rows)
        assert [f["status"] for f in findings] == ["fixable"], text


def test_conditional_opener_governs_only_its_clause():
    """"在…情景下" heads its own clause; the next clause's number-first slot is D's own."""
    text = "在基准扩张（40%）路径下装机稳步兑现，仅10%概率超预期上行。"
    findings = LN.find_probability_slots(text, FFE1_ROWS)
    assert _statuses(findings) == [("基准扩张", 40, 35, "fixable"), ("超预期上行", 10, 5, "fixable")]
    # 若 governs the rest of its sentence.
    governed = "若电力受限，在基准路径下装机放缓，财务紧缩（60%概率）随之而来。"
    assert [(f["status"], f["guard"]) for f in LN.find_probability_slots(governed, FFE1_ROWS)] == [
        ("unresolved", "conditional")]
    # The next sentence is out of its reach.
    later = "若电力受限，装机放缓。财务紧缩（60%概率）。"
    assert [f["status"] for f in LN.find_probability_slots(later, FFE1_ROWS)] == ["fixable"]


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


def _sum_guarded_reference(text, start, end):
    """The sum guard as the sync reads it: the shield of the token's sentence."""
    for lo, hi in NS._sentence_bounds(text):
        if lo <= start < hi:
            shield = NS._sum_shield(text, lo, hi)
            return shield is None or (start, end) in shield
    return False


def test_public_guards_match_the_sync():
    text = "电力受限（30%）与融资紧缩（20%）合计50%，基准情景（40%），由40%下调至35%，份额40%"
    for match in NS._INT_PERCENT_RE.finditer(text):
        start, end = match.span()
        assert NS.range_guarded(text, start, end) is NS._is_range(text, start, end)
        assert NS.quantity_guarded(text, start, end) is NS._is_quantity(text, start, end)
    spans = [m.span() for m in NS._INT_PERCENT_RE.finditer(text)]
    assert [NS.sum_guarded(text, *span) for span in spans] == [True, True, True, False, False,
                                                               False, False]
    # The text-bound checkers answer exactly as the per-call guards and the sync do.
    cited = ("据高盛，基准情景（60%）偏高。电力受限（30%）与融资紧缩（20%）合计50%；基准情景（40%）"
             "1+2 3%。Polymarket prices B at 30%. 份额40%\n基准情景（35%）（彭博）")
    for sample in (text, cited, "40%", ""):
        sums, markets = NS.sum_guard_for(sample), NS.market_guard_for(sample)
        positions = [m.span() for m in NS._INT_PERCENT_RE.finditer(sample)]
        positions += [(0, 1), (len(sample), len(sample) + 1), (len(sample) + 5, len(sample) + 6)]
        for start, end in positions:
            assert sums(start, end) is NS.sum_guarded(sample, start, end) \
                is _sum_guarded_reference(sample, start, end), (sample, start)
            assert markets(start, end) is NS.market_guarded(sample, start, end) \
                is NS._MarketCitations(sample)(start, end), (sample, start)
    assert NS.market_guarded(cited, cited.index("60%"), cited.index("60%") + 3) is True
    assert NS.market_guarded(cited, cited.index("40%"), cited.index("40%") + 3) is False
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


def test_blockquote_lazy_continuation_belongs_to_it():
    """A summary with a newline is published as "> line 1\nline 2": the second line is
    the blockquote's lazy continuation, never body text (review round 2)."""
    md = "# T\n\n> 装机稳步兑现。\n基准情景（40%）下装机稳步兑现。\n\n正文里A情景（40%）。\n"
    scanned = LN.audit_markdown(md, FFE1_ROWS)
    assert [f["alias"] for f in scanned["findings"]] == ["基准情景", "A情景"]
    skipped = LN.audit_markdown(md, FFE1_ROWS, skip_summary_blockquote=True)
    assert [f["alias"] for f in skipped["findings"]] == ["A情景"]
    assert skipped["skipped"]["summary_blockquote"] == 2
    # A later quote's continuation is a quote too; a list item, a heading or a blank
    # line ends the blockquote.
    later = ("# T\n\n正文。\n\n> 某券商：\n基准情景（40%）偏高\n\n> 引语\n- A情景（40%）\n\n"
             "> 引语\n## A情景（40%）\n")
    audit = LN.audit_markdown(later, FFE1_ROWS)
    lines = [later[later.rfind("\n", 0, f["start"]) + 1:later.find("\n", f["start"])]
             for f in audit["findings"]]
    assert lines == ["- A情景（40%）", "## A情景（40%）"]
    assert audit["skipped"]["blockquote"] == 4


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


def test_s11_carries_every_unresolved_finding():
    """The numeric gate fails closed: the guards only decide that a rewrite is unsafe,
    so market, quote, conditional, history and weak-alias findings reach S11 too."""
    rows = _rows(("A：基准扩张", 0.35), ("B：电力受限", 0.25), ("C：财务紧缩", 0.25),
                 ("D：超预期上行", 0.05), ("E：其它", 0.10))
    md = ("# T\n\n高盛的基准情景（60%）偏乐观。\n\n他写道：“电力受限（50%）”。\n\n"
          "若进入电力受限情景，则有45%的概率出现财务紧缩。\n\n此前基准情景（55%）偏高。\n\n"
          "油价方面，上行（15%）空间有限。\n\n正文：A情景（40%）。")
    audit = LN.audit_markdown(md, rows)
    assert [(f["claimed"], f.get("guard")) for f in audit["findings"]] == [
        (60, "market"), (50, "quote"), (45, "conditional"), (55, "history"),
        (15, "weak_alias"), (40, None)]
    assert LN.s11_mismatches(md, rows, reference="forecast.json") == [
        "scenario 'A：基准扩张': prose 60% vs forecast.json 35%",
        "scenario 'B：电力受限': prose 50% vs forecast.json 25%",
        "scenario 'C：财务紧缩': prose 45% vs forecast.json 25%",
        "scenario 'A：基准扩张': prose 55% vs forecast.json 35%",
        "scenario 'D：超预期上行': prose 15% vs forecast.json 5%",
        "scenario 'A：基准扩张': prose 40% vs forecast.json 35%",
    ]


@pytest.mark.parametrize("text, rows", [
    ("For the data-center market, the base case (40%) remains the main path.",
     _rows(("A: Base case", 0.35), ("B: Bull case", 0.30), ("E: Other", 0.35))),
    ("在当前市场环境下，基准情景（40%）仍是主路径。",
     _rows(("A：基准扩张", 0.35), ("B：电力受限", 0.30), ("E：其它", 0.35))),
    ("数据中心市场的基准情景（40%）仍是主路径。",
     _rows(("A：基准扩张", 0.35), ("B：电力受限", 0.30), ("E：其它", 0.35))),
])
def test_s11_does_not_fail_open_on_a_generic_market_word(text, rows):
    """A market-forecast report says 市场 / market everywhere: the market guard keeps
    the repair away, but the stale own probability still reaches S11."""
    md = "# T\n\n" + text + "\n"
    audit = LN.audit_markdown(md, rows)
    assert [(f["status"], f["guard"]) for f in audit["findings"]] == [("unresolved", "market")]
    assert LN.s11_mismatches(md, rows, reference="spine") == [
        f"scenario '{rows[0]['name']}': prose 40% vs spine 35%"]


# ------------------------------------------------------------------ cost on model text
@pytest.mark.parametrize("md", [
    "# T\n\n基准情景（40%）" + " " * 20000 + "x",               # history tail after a slot
    "# T\n\n基准情景：" + " " * 20000 + "x",                     # colon slot
    "# T\n\n基准情景：40%" + " " * 20000 + "x",
    "# T\n\n基准情景（概率" + " " * 20000 + "x",                  # bracket slot
    "# T\n\n基准情景（40%" + " " * 20000 + "x",
    "# T\n\n基准情景" + "* " * 20000 + "x",
    "# T\n\n40%" + " " * 20000 + "的概率" + " " * 20000 + "x",     # number-first slot
    "# T\n\nbase case" + " " * 20000 + "at" + " " * 20000 + "x",
    "# a" + " " * 50000 + "b\n\n基准情景（40%）",                 # heading line
    "# T\n\n" + "“" * 20000 + "基准情景（40%）",                   # unclosed quotes
    "# T\n\n" + "若" * 20000 + "基准情景（40%）",
    "# T\n\n基准情景（40%）to 40." + "0" * 20000 + "x",           # trailing "to N%"
    "# T\n\n" + "trimmed " * 5000 + "基准情景（40%）",              # move verb before
    "# T\n\n" + "将" * 20000 + "基准情景（40%）" + "的" * 20000,
    "# T\n\n" + " " * 20000 + "上行（10%）" + "*" * 20000,           # label position
    "# T\n\n上行" + " " * 20000 + "情景" + " " * 20000 + "x",       # scenario word
    "# T\n\n> q\n" + "-" * 20000 + "x",                           # lazy continuation
    "# T\n\n" + "".join(f"> q{i}\n上行（10%）\n" for i in range(3000)),
    "# T\n\n" + "".join(f"{BINARY_FORECAST_START_MARKER}\n上行（10%）\n" for i in range(2000)),
], ids=lambda md: f"{len(md)}-chars")
def test_degenerate_model_text_stays_linear(md):
    started = time.perf_counter()
    LN.audit_markdown(md, FFE1_ROWS)
    assert time.perf_counter() - started < 1.0


def test_unterminated_binary_markers_are_scanned_once():
    """Each start marker finds its end marker by bisection (review round 3): 20 000
    unterminated start markers took seconds when each one rescanned the rest of the
    report.  An unterminated start marker stays plain text; a terminated block is skipped."""
    lines = [BINARY_FORECAST_START_MARKER] * 20000
    md = "# T\n\n" + "\n".join(lines) + "\n"
    skipped = Counter()
    started = time.perf_counter()
    spans = LN._scannable_spans(md, False, skipped)
    assert time.perf_counter() - started < 0.5
    assert len(spans) == 2 and not skipped                 # the H1 and one paragraph
    md = ("# T\n\n" + BINARY_FORECAST_START_MARKER + "\n\nA情景（40%）\n\n"
          + BINARY_FORECAST_START_MARKER + "\n基准情景（40%）\n" + BINARY_FORECAST_END_MARKER
          + "\n\n" + BINARY_FORECAST_START_MARKER + "\nA情景（40%）\n")
    audit = LN.audit_markdown(md, FFE1_ROWS)
    # The first start marker is closed by the later end marker: its 7 lines are the block;
    # the last, unterminated one is plain text, so the slot after it is read.
    assert audit["skipped"] == {"binary_block": 7}
    assert [(f["alias"], f["status"]) for f in audit["findings"]] == [("A情景", "fixable")]


def test_guards_are_built_once_per_paragraph(monkeypatch):
    bounds_calls, market_builds = [], []
    real_bounds, real_market = NS._sentence_bounds, NS._MarketCitations

    def counting_bounds(text):
        bounds_calls.append(len(text))
        return real_bounds(text)

    def counting_market(text):
        market_builds.append(len(text))
        return real_market(text)

    monkeypatch.setattr(NS, "_sentence_bounds", counting_bounds)
    monkeypatch.setattr(NS, "_MarketCitations", counting_market)
    md = "# T\n\n" + "".join(f"第{i}句A情景（40%）。" for i in range(300))
    audit = LN.audit_markdown(md, FFE1_ROWS)
    assert audit["count"] == audit["fixable"] == 300
    assert len(bounds_calls) == len(market_builds) == 1


def test_resolve_gate(caplog):
    assert [LN.resolve_gate(value) for value in ("off", " Observe ", "NUMERIC")] == \
        ["off", "observe", "numeric"]
    with caplog.at_level(logging.WARNING, logger=LN.__name__):
        assert LN.resolve_gate("report3-strict-typo") == "observe"
        assert LN.resolve_gate("report3-strict-typo") == "observe"
    warnings = [r for r in caplog.records if "report3-strict-typo" in r.getMessage()]
    assert len(warnings) == 1
