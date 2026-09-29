"""REPORT-2 (P08 stage 1a): deterministic narrative sync after probability moves.

Offline: pure-module cases plus the three call sites (red-team critique, pre-mortem,
K>1 spine pooling) driven by FakeLLMClient.  The archived headlines below are the
real ``forecast.json`` headlines of report_ffe1ea6bf50d / 47c6b71e2d91 /
d428e43a179d / b283f119e40e / 92b01e08460b; their final probabilities are the
archived values, and the pre-move rows are reconstructed from the numbers each
headline states (the archive keeps only the final forecast).
"""

import copy
import json
import os

import pytest

from app.config import Config
from app.services import forecast_extractor as FE
from app.services import narrative_sync as NS
from app.services.narrative_sync import (
    NARRATIVE_SYNC_LOG_CAP,
    sync_probability_numbers,
    synchronize_forecast_narratives,
)
from tests.conftest import FakeLLMClient


def _rows(*pairs):
    return [{"name": name, "probability": probability} for name, probability in pairs]


FFE1_BEFORE = _rows(("A：基准扩张", 0.40), ("B：电力受限", 0.30), ("C：财务紧缩", 0.20),
                    ("D：超预期上行", 0.10))
FFE1_AFTER = _rows(("A：基准扩张", 0.35), ("B：电力受限", 0.30), ("C：财务紧缩", 0.20),
                   ("D：超预期上行", 0.05), ("E：其它/混合路径", 0.10))
FFE1_HEADLINE = (
    "基准情景（40%）下2030年全球IT装机容量达190–210 GW、单年capex $2.5–3.2T，但电力硬约束"
    "（30%）与融资紧缩（20%）构成合计50%的下行尾部，仅10%概率超预期上行。"
)
B283_HEADLINE = (
    "Global EV adoption through 2035 will bifurcate regionally into a probability distribution "
    "across Base (~52% share, 55%), Accelerated (~65–75%, 25%), and Plateau (~30–35%, 20%) "
    "scenarios, resolved by EU trilogue, US ACC II litigation, 2028 US election, and "
    "solid-state battery commercialization."
)


@pytest.fixture(autouse=True)
def _sync_on(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_NARRATIVE_SYNC", True, raising=False)


def _criteria(rows):
    for row in rows:
        row.setdefault("resolution_criteria", f"{row['name']} resolves by 2030")
    return rows


# ------------------------------------------------------------------ pure module
def test_ffe1_headline():
    out = {"headline": "基准情景（40%）… 仅10%概率超预期上行",
           "scenarios": copy.deepcopy(FFE1_AFTER)}

    synchronize_forecast_narratives(out, headline_before=FFE1_BEFORE)

    assert out["headline"] == "基准情景（35%）… 仅5%概率超预期上行"
    assert out["headline_detail"] == "基准情景（40%）… 仅10%概率超预期上行"
    edits = out["quality"]["narrative_sync"]
    assert [(e["field"], e["from"], e["to"]) for e in edits] == [
        ("headline", "40%", "35%"), ("headline", "10%", "5%")]
    assert all(len(e["excerpt"]) <= 180 for e in edits)


def test_ffe1_full_archived_headline_keeps_the_sum_statement():
    """The published ffe1 headline: A 40→35 and D 10→5 are synced, while B (30%) and
    C (20%) stay because they are the addends of the unchanged '合计50%'."""
    out = {"headline": FFE1_HEADLINE, "scenarios": copy.deepcopy(FFE1_AFTER)}

    synchronize_forecast_narratives(out, headline_before=FFE1_BEFORE)

    assert out["headline"] == (
        "基准情景（35%）下2030年全球IT装机容量达190–210 GW、单年capex $2.5–3.2T，但电力硬约束"
        "（30%）与融资紧缩（20%）构成合计50%的下行尾部，仅5%概率超预期上行。"
    )
    assert out["headline_detail"] == FFE1_HEADLINE
    assert len(out["quality"]["narrative_sync"]) == 2


@pytest.mark.parametrize("headline, final_a, expected", [
    (  # report_47c6b71e2d91: '2027+' means 'from 2027 on', not an addition.
        "基准情景（概率0.40）下，2030年底全球IT装机容量达190–210 GW、单年capex $2.5–3.2T，"
        "但电力物理约束（2026–28）与融资脆弱性（2027+）构成主要下行分岔，管道兑现基率仅13%意味着"
        "公告数字需大幅打折。",
        0.35, "基准情景（概率0.35）下，",
    ),
    (  # report_d428e43a179d
        "基准情景（概率约0.40）下，2030年底全球累计IT装机容量达190–210 GW、单年capex $2.5–3.2T；"
        "电力硬约束与融资脆弱性是情景分岔的两大决定变量，管道兑现率按历史基率13%大幅打折后仍有"
        "充足上行绝对量。",
        0.34, "基准情景（概率约0.34）下，",
    ),
], ids=["report_47c6", "report_d428"])
@pytest.mark.parametrize("d_before", [0.10, 0.13], ids=["D_at_10", "D_at_13"])
def test_archived_decimal_headlines_are_synced(headline, final_a, expected, d_before):
    """D's pre-move value is not in the archive (final D=0.08).  Reconstructed at 0.13
    it equals the cited base rate, and '基率仅13%' / '历史基率13%' must stay untouched."""
    before = _rows(("A. 基准", 0.40), ("B. 电力受限", 0.30),
                   ("C. 财务紧缩", round(0.30 - d_before, 2)), ("D. 上行", d_before))
    after = _rows(("A. 基准", final_a), ("B. 电力受限", 0.28), ("C. 财务紧缩", 0.17),
                  ("D. 上行", 0.08), ("E. 兜底", 0.12))

    new_text, edits, skipped = sync_probability_numbers(headline, before, after)

    assert new_text == headline.replace("0.40", f"{final_a:.2f}", 1)
    assert new_text.startswith(expected)
    assert [(e["from"], e["to"]) for e in edits] == [("0.40", f"{final_a:.2f}")]
    assert skipped == ({"quantity": 1} if d_before == 0.13 else {})


# "Bear" holds 13%: a label slot ("Bear case at 13%") needs the label to name the
# scenario whose old value the number is.
_QUANTITY_BEFORE = _rows(("A", 0.40), ("Bear", 0.13), ("C", 0.47))
_QUANTITY_AFTER = _rows(("A", 0.35), ("Bear", 0.08), ("C", 0.57))


@pytest.mark.parametrize("text", [
    # rates and base rates (report_47c6 / d428 headlines and the 47c6 rationale)
    "管道兑现基率仅13%意味着公告数字需大幅打折。", "管道兑现率按历史基率13%大幅打折",
    "LBNL 13%兑现率 vs 公告管线", "利润率13%", "失业率13%", "EV渗透率超过40%",
    "the base rate is 13%.", "13% base rate", "the 13% hurdle rate", "CAGR约13%", "13% CAGR",
    "13% IRR", "IRR ~13%", "margin of about 13%", "通胀约13%",
    # thresholds and comparators
    "EV share above 40% by 2030", "≥40%的装机", "over 40%", "低于13%", "逾40%", "不足13%",
    "40%或以上", "40% or more", "市场份额40%以上", "at least 40% of capex",
    # shares, tariffs, 'of' quantities and changes
    "a 40% tariff on imports", "a 40% import tariff", "40% of respondents", "占全球装机的40%",
    "分别占约40%", "比例为40%", "增速放缓至40%", "涨幅达40%", "prices rose by 40%",
    "shares up 13%",
    # CJK change verbs (a change amount, not a level: "降至" / "降为" stay probabilities)
    "成本降低40%", "价格下降40%", "价格下降约40%", "成本下降了40%", "效率提高40%", "需求上升40%",
    "电价下滑40%", "预算削减40%", "成本缩减40%", "股价暴跌40%", "股价下跌达40%", "价格涨40%",
    "capex跌40%", "PUE下降40%", "产能翻番、成本下探40%",
    # English change and comparative words after the number
    "a 40% decline in capex", "a 40% drop in prices", "a 40% increase in demand",
    "a 40% reduction in emissions", "costs 40% lower by 2030", "40% higher power prices",
    "40% cheaper batteries", "40% faster build-out", "doubling, then 40% more",
    # English change verbs before the number
    "capex cut 40%", "capex cut by 40%", "emissions reduced 40%", "prices slashed 40%",
    # CJK "X%的<noun>" shares
    "40%的降幅", "40%的涨幅", "40%的增量", "约40%的装机", "40%的电力需求", "40%的数据中心",
    "40%的电价涨幅",
    # tariffs
    "关税40%", "40%关税", "上调关税至40%", "tariff of 40%",
    # metrics
    "WACC 13%", "WACC of 13%", "ROE 40%", "毛利40%", "净利润40%", "EBITDA margin 40%",
    "40% EBITDA margin", "13% inflation", "13% unemployment", "unemployment at 13%",
    "13% interest", "13% vacancy", "40% utilization", "40% utilisation", "40% efficiency",
    "40% capacity factor", "capacity factor of 40%", "40% load factor", "40%利用率", "40%负荷率",
    "yields of 13%", "discount rate 13%", "40% YoY", "40% of capex",
    "roughly 40% of global capacity",
])
def test_quantity_figures_are_never_rewritten(text):
    new_text, edits, skipped = sync_probability_numbers(text, _QUANTITY_BEFORE, _QUANTITY_AFTER)

    assert (new_text, edits, skipped) == (text, [], {"quantity": 1})


@pytest.mark.parametrize("text, expected", [
    ("基准情景占主导（40%）", "基准情景占主导（35%）"),        # 占 not adjacent to the number
    ("高通胀情景（40%）", "高通胀情景（35%）"),                # quantity word inside a name
    ("仅13%概率超预期上行", "仅8%概率超预期上行"),            # 概率 is not a rate noun
    ("40%的概率", "35%的概率"),
    ("几率40%", "几率35%"),
    ("基准情景（概率0.40）", "基准情景（概率0.35）"),
    ("Base holds 40% of the probability mass", "Base holds 35% of the probability mass"),
    ("a 40% chance of the base case", "a 35% chance of the base case"),
    ("Soft landing (40%) — rate cuts follow", "Soft landing (35%) — rate cuts follow"),
    ("Escalation (40%): tariffs rise", "Escalation (35%): tariffs rise"),
    ("Bear case at 13%", "Bear case at 8%"),
    ("Bear (40%) over Bull (47%)", "Bear (35%) over Bull (57%)"),
    # a new level after a move verb is a probability, not a change amount
    ("Bear is cut to 13%", "Bear is cut to 8%"),
    ("A raised to 40% on grid evidence", "A raised to 35% on grid evidence"),
    ("基准情景概率降至40%", "基准情景概率降至35%"),
    ("基准情景概率降为40%", "基准情景概率降为35%"),
    ("40%的可能性", "35%的可能性"),
    ("以40%的发生概率领先", "以35%的发生概率领先"),
    ("有40%的把握", "有35%的把握"),
    ("a 40% likelihood of the soft-landing scenario", "a 35% likelihood of the soft-landing scenario"),
])
def test_probabilities_next_to_quantity_words_are_still_synced(text, expected):
    assert sync_probability_numbers(text, _QUANTITY_BEFORE, _QUANTITY_AFTER)[0] == expected


def test_non_ascii_digits_are_never_tokens():
    before = _rows(("A", 0.40), ("Z", 0.0), ("C", 0.60))
    after = _rows(("A", 0.35), ("Z", 0.05), ("C", 0.60))
    text = "基准（４０％）、尾部（４0%）、阿拉伯数字（٤٠%）、下行（40%）"

    new_text, edits, skipped = sync_probability_numbers(text, before, after)

    assert new_text == text.replace("下行（40%）", "下行（35%）")
    assert [(e["from"], e["to"]) for e in edits] == [("40%", "35%")]
    assert skipped == {}


def test_b283_quantity_and_range_guards():
    before = _rows(("Base Case", 0.55), ("Accelerated Case", 0.25), ("Plateau Case", 0.20))
    after = _rows(("Base Case", 0.50), ("Accelerated Case", 0.22), ("Plateau Case", 0.18),
                  ("Other / Status Quo", 0.10))

    new_text, edits, _ = sync_probability_numbers(B283_HEADLINE, before, after)

    assert "Base (~52% share, 50%)" in new_text
    assert "Accelerated (~65–75%, 22%)" in new_text
    assert "Plateau (~30–35%, 18%)" in new_text
    assert new_text == (B283_HEADLINE.replace("share, 55%", "share, 50%")
                        .replace("75%, 25%", "75%, 22%").replace("35%, 20%", "35%, 18%"))
    assert [(e["from"], e["to"]) for e in edits] == [("55%", "50%"), ("25%", "22%"), ("20%", "18%")]


def test_range_and_quantity_guards_skip_mapped_values():
    before = _rows(("Base", 0.55), ("Bear", 0.20), ("Bull", 0.25))
    after = _rows(("Base", 0.50), ("Bear", 0.18), ("Bull", 0.32))
    text = ("Bear (~15–20%, 20%); reduced from 55% to 50%; EV share 55% by 2035; "
            "55% growth; 同比增长20%，美国与中国分别占约25%增量。")

    new_text, edits, skipped = sync_probability_numbers(text, before, after)

    assert new_text == text.replace("15–20%, 20%", "15–20%, 18%")
    assert [(e["from"], e["to"]) for e in edits] == [("20%", "18%")]
    assert skipped == {"range": 2, "quantity": 4}


def test_signed_changes_are_quantities():
    before = _rows(("A", 0.40), ("D", 0.10), ("C", 0.50))
    after = _rows(("A", 0.35), ("D", 0.05), ("C", 0.60))
    text = "AI capex (+10%), power −10%, ±10% band, ＋10%, -10%; D (10%)."

    new_text, edits, skipped = sync_probability_numbers(text, before, after)

    assert new_text == text.replace("D (10%)", "D (5%)")
    assert [(e["from"], e["to"]) for e in edits] == [("10%", "5%")]
    assert skipped == {"quantity": 5}


def test_stated_moves_are_left_alone():
    """A before→after pair ("由40%下调至35%", "from 40% to 35%", "40% → 35%") is
    history plus a critic target, never one scenario's current value."""
    before = _rows(("A", 0.40), ("B", 0.35), ("C", 0.25))
    after = _rows(("A", 0.35), ("B", 0.41), ("C", 0.24))
    for text in ("A由40%下调至35%，B由35%上调为41%。", "A cut from 40% to 35%.",
                 "A 40% → 35%; A 40% down to 35%.", "概率从0.40降到0.35", "A (down from 40%)"):
        new_text, edits, skipped = sync_probability_numbers(text, before, after)
        assert (new_text, edits) == (text, [])
        assert set(skipped) == {"range"}

    new_text, edits, _ = sync_probability_numbers("A 概率升至40%，B（35%）", before, after)
    assert new_text == "A 概率升至35%，B（41%）"
    assert len(edits) == 2


def test_no_cascade_and_ambiguity():
    new_text, edits, _ = sync_probability_numbers(
        "A（40%）B（35%）",
        _rows(("A", 0.40), ("B", 0.35), ("C", 0.25)),
        _rows(("A", 0.35), ("B", 0.30), ("C", 0.35)),
    )
    assert new_text == "A（35%）B（30%）"
    assert len(edits) == 2

    # Two BEFORE rows at 30%: '30%' cannot be attributed to one scenario.
    new_text, edits, skipped = sync_probability_numbers(
        "B（30%）与C（30%）；A（40%）",
        _rows(("A", 0.40), ("B", 0.30), ("C", 0.30)),
        _rows(("A", 0.35), ("B", 0.35), ("C", 0.30)),
    )
    assert new_text == "B（30%）与C（30%）；A（35%）"
    assert skipped["ambiguous"] >= 1
    assert [(e["from"], e["to"]) for e in edits] == [("40%", "35%")]

    # '合计50%' whose addends cannot be identified shields its whole clause.
    new_text, _, skipped = sync_probability_numbers(
        "A（50%）领先；B与C合计50%。",
        _rows(("A", 0.50), ("B", 0.30), ("C", 0.20)),
        _rows(("A", 0.45), ("B", 0.30), ("C", 0.20), ("Other", 0.05)),
    )
    assert new_text == "A（45%）领先；B与C合计50%。"
    assert skipped == {"sum": 1}


def test_sum_guard_arithmetic_and_listed_totals():
    before = _rows(("A", 0.40), ("B", 0.35), ("C", 0.25))
    after = _rows(("A", 0.35), ("B", 0.30), ("C", 0.25), ("Other", 0.10))
    for text in ("A 40% + B 35% = 75% of the mass.",
                 "基准40%，下行35%，上行25%，合计100%。",
                 "Base 40% and Bear 35% together make up 75%."):
        new_text, edits, skipped = sync_probability_numbers(text, before, after)
        assert new_text == text
        assert edits == []
        assert skipped == {"sum": 2}


def test_decimal_context():
    before = _rows(("A", 0.40), ("B", 0.60))
    after = _rows(("A", 0.35), ("B", 0.65))

    assert sync_probability_numbers("基准情景（概率0.40）", before, after)[0] == "基准情景（概率0.35）"
    assert sync_probability_numbers("A at probability .40", before, after)[0] == "A at probability .35"
    assert sync_probability_numbers("A (p=0.40)", before, after)[0] == "A (p=0.35)"
    assert sync_probability_numbers("A (p = 0.40)", before, after)[0] == "A (p = 0.35)"
    assert (sync_probability_numbers("概率约0.40。成本0.40美元", before, after)[0]
            == "概率约0.35。成本0.40美元")
    for untouched in ("costs 0.40 USD", "概率。成本0.40", "概率0.40%", "概率10.40", "概率0.405",
                      # an English sentence stop ends the trigger's reach
                      "The probability. Unit cost 0.40", "probability. unit cost 0.40",
                      # money next to the number
                      "probability 0.40 USD", "概率约0.40美元", "概率约0.40元", "probability $0.40",
                      # probability-weighted figures
                      "概率加权成本0.40", "probability-weighted 0.40",
                      # statistical p-values
                      "(p=0.40) significant", "p=0.40，差异不显著", "p = .40 (p-value)"):
        assert sync_probability_numbers(untouched, before, after) == (untouched, [], {})


def test_consistent_headline_stays_byte_identical():
    """report_92b01e08460b: the headline already states A's final 40%."""
    headline = ("基准情景（40%）下2030年底全球IT装机容量达190–210 GW、单年capex $2.5–3.2T，"
                "但电力硬约束与债务化融资使下行尾部（合计50%）不可忽视。")
    final = _rows(("A 基准扩张", 0.4), ("B 电力受限", 0.3273), ("C 财务紧缩", 0.1636),
                  ("D 上行超预期", 0.1091))
    moved = _rows(("A 基准扩张", 0.4), ("B 电力受限", 0.30), ("C 财务紧缩", 0.20),
                  ("D 上行超预期", 0.10))
    for before in (final, moved):
        out = {"headline": headline, "scenarios": copy.deepcopy(final)}
        snapshot = json.dumps(out, ensure_ascii=False, sort_keys=True)
        synchronize_forecast_narratives(out, headline_before=before, rationale_before=before,
                                        summary_before_by_name=before)
        assert json.dumps(out, ensure_ascii=False, sort_keys=True) == snapshot


def test_summary_syncs_only_its_own_scenario_and_keeps_details():
    before = _rows(("A", 0.40), ("B", 0.30), ("Other", 0.20), ("D", 0.10))
    after = [
        {"name": "A", "probability": 0.35, "summary": "Base path (40%); B was 30%."},
        {"name": "B", "probability": 0.35, "summary": "Grid-limited path (30%)."},
        {"name": "Other", "probability": 0.20, "summary": "Residual."},
        {"name": "D", "probability": 0.10, "summary": "Upside 10%."},
    ]
    quality = {"lint": {"ok": True}}
    out = {"headline": "A 40%, B 30%.", "confidence_rationale": "Stable view.",
           "scenarios": after, "quality": quality}

    synchronize_forecast_narratives(out, headline_before=before, rationale_before=before,
                                    summary_before_by_name=before)

    assert out["headline"] == "A 35%, B 35%."
    assert after[0]["summary"] == "Base path (35%); B was 30%."
    assert after[0]["summary_detail"] == "Base path (40%); B was 30%."
    assert after[1]["summary"] == "Grid-limited path (35%)."
    assert "summary_detail" not in after[2] and "summary_detail" not in after[3]
    assert "confidence_rationale_detail" not in out
    assert [e["field"] for e in out["quality"]["narrative_sync"]] == [
        "headline", "headline", "scenario[0].summary", "scenario[1].summary"]
    assert out["quality"]["lint"] == {"ok": True}
    assert quality == {"lint": {"ok": True}}          # shared quality dict never mutated


def test_details_keep_first_original_and_log_is_capped():
    out = {"headline": "A 40%.", "scenarios": _rows(("A", 0.35), ("B", 0.65)),
           "quality": {"narrative_sync": [{"field": "x"}] * (NARRATIVE_SYNC_LOG_CAP - 1),
                       "narrative_sync_skipped": {"range": 2}}}
    synchronize_forecast_narratives(out, headline_before=_rows(("A", 0.40), ("B", 0.60)))
    assert out["headline"] == "A 35%."
    assert len(out["quality"]["narrative_sync"]) == NARRATIVE_SYNC_LOG_CAP
    assert "narrative_sync_dropped" not in out["quality"]

    out["scenarios"] = _rows(("A", 0.30), ("B", 0.70))
    out["headline"] = "A 35%; A (35%) and 65%-70%."
    synchronize_forecast_narratives(out, headline_before=_rows(("A", 0.35), ("B", 0.65)))
    assert out["headline"] == "A 30%; A (30%) and 65%-70%."
    assert out["headline_detail"] == "A 40%."                  # first original wins
    assert len(out["quality"]["narrative_sync"]) == NARRATIVE_SYNC_LOG_CAP
    assert out["quality"]["narrative_sync_dropped"] == 2      # the cap never drops silently
    assert out["quality"]["narrative_sync_skipped"] == {"range": 3}

    out["scenarios"] = _rows(("A", 0.25), ("B", 0.75))
    synchronize_forecast_narratives(out, headline_before=_rows(("A", 0.30), ("B", 0.70)))
    assert out["headline"] == "A 25%; A (25%) and 65%-70%."
    assert out["quality"]["narrative_sync_dropped"] == 4


def test_nothing_to_sync_leaves_forecast_untouched():
    for out, kwargs in [
        ({"headline": "A 40%.", "scenarios": _rows(("A", 0.40), ("B", 0.60))},
         {"headline_before": _rows(("A", 0.40), ("B", 0.60))}),
        ({"headline": "A 40%.", "scenarios": _rows(("A", 0.35), ("B", 0.65))}, {}),
        ({"headline": "A 40%.", "scenarios": []}, {"headline_before": _rows(("A", 0.40))}),
        ({"headline": None, "scenarios": _rows(("A", 0.35), ("B", 0.65))},
         {"headline_before": _rows(("A", 0.40), ("B", 0.60))}),
        ({"headline": "A 40%.", "scenarios": _rows(("A", 0.35), ("B", 0.65)), "quality": "x"},
         {"headline_before": _rows(("A", 0.40), ("B", 0.60))}),
    ]:
        snapshot = copy.deepcopy(out)
        synchronize_forecast_narratives(out, **kwargs)
        assert out == snapshot


def test_unpairable_rows_never_map():
    # Duplicate names, missing or non-numeric probabilities never produce a mapping.
    before = [{"name": "A", "probability": 0.40}, {"name": "A", "probability": 0.20},
              {"name": "B", "probability": None}, {"name": "C", "probability": "0.30"},
              {"name": "D", "probability": True}]
    after = _rows(("A", 0.35), ("B", 0.45), ("C", 0.20))
    text = "A 40%, A 20%, B 30%, C 30%, D 100%"
    assert sync_probability_numbers(text, before, after) == (text, [], {"unpaired": 2})


def _step(out, before, after):
    """One probability move: ``out`` now carries ``after``; sync against ``before``."""
    out["scenarios"] = copy.deepcopy(after)
    synchronize_forecast_narratives(out, headline_before=before, rationale_before=before,
                                    summary_before_by_name=before)


def test_ambiguous_value_stays_blocked_in_later_passes():
    """Pass 1 cannot tell Base's 40% from Bear's; pass 2 must not map both onto Base's move."""
    step0 = _rows(("Base", 0.40), ("Bear", 0.40), ("Other", 0.20))
    step1 = _rows(("Base", 0.40), ("Bear", 0.35), ("Other", 0.25))
    step2 = _rows(("Base", 0.30), ("Bear", 0.35), ("Other", 0.35))
    out = {"headline": "Base (40%) vs Bear (40%); Other 20%."}

    _step(out, step0, step1)
    assert out["headline"] == "Base (40%) vs Bear (40%); Other 25%."
    assert out["quality"]["narrative_sync_blocked"] == {"headline": [40]}
    unblocked = copy.deepcopy(out)
    del unblocked["quality"]["narrative_sync_blocked"]

    _step(out, step1, step2)
    assert out["headline"] == "Base (40%) vs Bear (40%); Other 35%."
    assert out["quality"]["narrative_sync_skipped"] == {"ambiguous": 4}
    assert out["quality"]["narrative_sync_blocked"] == {"headline": [40]}
    assert out["headline_detail"] == "Base (40%) vs Bear (40%); Other 20%."

    _step(unblocked, step1, step2)                             # the record is what guards it
    assert unblocked["headline"] == "Base (30%) vs Bear (30%); Other 35%."


def test_unpaired_value_stays_blocked_in_later_passes():
    """A renamed scenario's stale 40% must not take the next move of whoever now holds 40%."""
    step0 = _rows(("X", 0.40), ("Y", 0.35), ("Z", 0.25))
    step1 = _rows(("X (revised)", 0.25), ("Y", 0.40), ("Z", 0.35))
    step2 = _rows(("X (revised)", 0.25), ("Y", 0.30), ("Z", 0.45))
    out = {"headline": "X (40%), Y (35%), Z (25%)."}

    _step(out, step0, step1)
    assert out["headline"] == "X (40%), Y (40%), Z (35%)."
    assert out["quality"]["narrative_sync_skipped"] == {"unpaired": 1}
    assert out["quality"]["narrative_sync_blocked"] == {"headline": [40]}
    unblocked = copy.deepcopy(out)
    del unblocked["quality"]["narrative_sync_blocked"]

    _step(out, step1, step2)
    assert out["headline"] == "X (40%), Y (40%), Z (45%)."
    assert out["quality"]["narrative_sync_skipped"] == {"unpaired": 1, "ambiguous": 2}

    _step(unblocked, step1, step2)
    assert unblocked["headline"] == "X (30%), Y (30%), Z (45%)."


def test_summary_blocks_are_keyed_by_scenario_name():
    step0 = [{"name": "Bear", "probability": 0.40, "summary": "Bear (40%) ties Base (40%)."},
             {"name": "Base", "probability": 0.40, "summary": "Base path."},
             {"name": "Other", "probability": 0.20, "summary": "Other paths."}]
    step1 = _rows(("Bear", 0.35), ("Base", 0.45), ("Other", 0.20))
    step2 = _rows(("Bear", 0.40), ("Base", 0.45), ("Other", 0.15))
    step3 = _rows(("Bear", 0.30), ("Base", 0.45), ("Other", 0.25))

    def move(out, before, after):
        for row, new in zip(out["scenarios"], after, strict=True):
            row["probability"] = new["probability"]
        synchronize_forecast_narratives(out, summary_before_by_name=before)

    out = {"headline": "Outlook.", "scenarios": copy.deepcopy(step0)}
    move(out, step0, step1)                  # Bear 40→35 while Base also held 40
    assert out["quality"]["narrative_sync_blocked"] == {"summary:bear": [40]}
    move(out, step1, step2)
    unblocked = copy.deepcopy(out)
    del unblocked["quality"]["narrative_sync_blocked"]

    move(out, step2, step3)                  # Bear 40→30; 40 is Bear's alone by now
    assert out["scenarios"][0]["summary"] == "Bear (40%) ties Base (40%)."
    # Step 2 (Bear 35→40) also saw both stale 40% tokens as foreign: Bear's new value,
    # which Bear did not hold before that move.
    assert out["quality"]["narrative_sync_skipped"] == {"ambiguous": 4, "foreign": 2}
    assert "narrative_sync" not in out["quality"]

    move(unblocked, step2, step3)
    assert unblocked["scenarios"][0]["summary"] == "Bear (30%) ties Base (30%)."


def test_foreign_value_in_a_probability_slot_stays_blocked():
    """'an early cut (25%)' was written against no scenario.  Once a move makes 25%
    Bear's value, the next move must not treat that token as Bear's: a bracket is a
    slot whatever its label, so only the record keeps it apart."""
    step0 = _rows(("Base", 0.40), ("Bear", 0.30), ("Bull", 0.20), ("Other", 0.10))
    step1 = _rows(("Base", 0.40), ("Bear", 0.25), ("Bull", 0.20), ("Other", 0.15))
    step2 = _rows(("Base", 0.40), ("Bear", 0.20), ("Bull", 0.20), ("Other", 0.20))
    out = {"headline": "Bear (30%); an early cut (25%); capex fell 25%."}

    _step(out, step0, step1)
    assert out["headline"] == "Bear (25%); an early cut (25%); capex fell 25%."
    assert out["quality"]["narrative_sync_skipped"] == {"foreign": 1}   # the quantity is guarded
    assert out["quality"]["narrative_sync_blocked"] == {"headline": [25]}
    unblocked = copy.deepcopy(out)
    del unblocked["quality"]["narrative_sync_blocked"]

    _step(out, step1, step2)                 # Bear 25→20: every 25% is left alone
    assert out["headline"] == "Bear (25%); an early cut (25%); capex fell 25%."
    assert out["quality"]["narrative_sync_skipped"] == {"foreign": 1, "ambiguous": 3}

    _step(unblocked, step1, step2)                             # the record is what guards it
    assert unblocked["headline"] == "Bear (20%); an early cut (20%); capex fell 25%."


def test_a_market_cited_foreign_value_is_never_rewritten_nor_recorded():
    """A market citation is skipped by the words next to it at every step, so it needs
    no record and does not block Bear's own number at the next step."""
    step0 = _rows(("Base", 0.40), ("Bear", 0.30), ("Bull", 0.20), ("Other", 0.10))
    step1 = _rows(("Base", 0.40), ("Bear", 0.25), ("Bull", 0.20), ("Other", 0.15))
    step2 = _rows(("Base", 0.40), ("Bear", 0.20), ("Bull", 0.20), ("Other", 0.20))
    out = {"headline": "Bear (30%); markets price a 25% chance of a cut."}

    _step(out, step0, step1)
    assert out["headline"] == "Bear (25%); markets price a 25% chance of a cut."
    assert set(out["quality"]) == {"narrative_sync"}          # nothing skipped or blocked

    _step(out, step1, step2)
    assert out["headline"] == "Bear (20%); markets price a 25% chance of a cut."
    assert out["quality"]["narrative_sync_skipped"] == {"market": 1}


def test_a_guarded_foreign_quantity_is_not_recorded():
    """A foreign number a range or quantity guard skips is skipped again at every later
    step, so it never blocks the scenario that now holds its value."""
    step0 = _rows(("Base", 0.40), ("Bear", 0.30), ("Bull", 0.20), ("Other", 0.10))
    step1 = _rows(("Base", 0.40), ("Bear", 0.25), ("Bull", 0.20), ("Other", 0.15))
    step2 = _rows(("Base", 0.40), ("Bear", 0.20), ("Bull", 0.20), ("Other", 0.20))
    out = {"headline": "Bear (30%); capex fell 25%; EV share 15–25%."}

    _step(out, step0, step1)
    assert out["headline"] == "Bear (25%); capex fell 25%; EV share 15–25%."
    assert set(out["quality"]) == {"narrative_sync"}          # nothing skipped or blocked

    _step(out, step1, step2)
    assert out["headline"] == "Bear (20%); capex fell 25%; EV share 15–25%."
    assert "narrative_sync_blocked" not in out["quality"]
    assert out["quality"]["narrative_sync_skipped"] == {"quantity": 1, "range": 1}


def test_context_rows_block_values_another_scenario_held():
    """A critic's text written against its own rows may cite the input it saw: a value
    the input gave another scenario is ambiguous; one the input never held is synced.
    Context rows equal to the BEFORE rows add nothing."""
    input_rows = _rows(("Base", 0.40), ("Bear", 0.30), ("Bull", 0.20), ("Other", 0.10))
    critic_rows = _rows(("Base", 0.35), ("Bear", 0.20), ("Bull", 0.30), ("Other", 0.10))
    final_rows = _rows(("Base", 0.3684), ("Bear", 0.2105), ("Bull", 0.3158), ("Other", 0.1053))
    text = "Bear (30%) ignored grid relief: Bear cut to 20%, Bull raised to 30%, Base to 35%."

    out = {"confidence_rationale": text, "scenarios": copy.deepcopy(final_rows)}
    synchronize_forecast_narratives(out, rationale_before=critic_rows, context_rows=input_rows)
    assert out["confidence_rationale"] == text.replace("Base to 35%", "Base to 37%")
    assert out["quality"]["narrative_sync_skipped"] == {"ambiguous": 3}
    assert out["quality"]["narrative_sync_blocked"] == {"confidence_rationale": [20, 30]}

    unguarded = {"confidence_rationale": text, "scenarios": copy.deepcopy(final_rows)}
    synchronize_forecast_narratives(unguarded, rationale_before=critic_rows)
    assert unguarded["confidence_rationale"] == (      # what the input context prevents
        "Bear (32%) ignored grid relief: Bear cut to 21%, Bull raised to 32%, Base to 37%.")
    # A label slot names its scenario: "Bear's 30%" is no slot for Bull's old 30%.
    labelled = {"confidence_rationale": text.replace("Bear (30%)", "Bear's 30%"),
                "scenarios": copy.deepcopy(final_rows)}
    synchronize_forecast_narratives(labelled, rationale_before=critic_rows)
    assert labelled["confidence_rationale"] == (
        "Bear's 30% ignored grid relief: Bear cut to 21%, Bull raised to 32%, Base to 37%.")
    assert labelled["quality"]["narrative_sync_skipped"] == {"no_slot": 1}

    for before, after, headline in (
            (FFE1_BEFORE, FFE1_AFTER, FFE1_HEADLINE),
            (input_rows, final_rows, "Base (40%) leads; Bear 30%, Bull 20%, Other 10%.")):
        plain = {"headline": headline, "scenarios": copy.deepcopy(after)}
        with_context = copy.deepcopy(plain)
        synchronize_forecast_narratives(plain, headline_before=before)
        synchronize_forecast_narratives(with_context, headline_before=before, context_rows=before)
        assert with_context == plain
        assert plain["headline"] != headline


def test_many_sentences_resolve_each_token_to_its_own_sentence():
    before = _rows(("A", 0.40), ("B", 0.30), ("C", 0.20), ("D", 0.10))
    after = _rows(("A", 0.35), ("B", 0.25), ("C", 0.25), ("D", 0.15))
    unit = "A（40%）。B（30%）与C（20%）合计50%。"

    new_text, edits, skipped = sync_probability_numbers(unit * 2000, before, after)

    assert new_text == "A（35%）。B（30%）与C（20%）合计50%。" * 2000
    assert len(edits) == 2000
    assert skipped == {"sum": 4000}


# ------------------------------------------------------------------ call sites
def _critique_case():
    forecast = {
        "headline": "Path A leads at 45%, Path B trails at 35%, residual 20%.",
        "horizon": "2030",
        "confidence": "medium",
        "confidence_rationale": "Spine view before critique.",
        "scenarios": _criteria([
            {"name": "Path A", "probability": 0.45, "summary": "A path (45%)."},
            {"name": "Path B", "probability": 0.35, "summary": "B path (35%)."},
            {"name": "Other / Status Quo", "probability": 0.20, "summary": "Mixed outcomes."},
        ]),
    }
    critique = {
        "confidence": "medium",
        "confidence_rationale": "Raised Path B to 60% on new grid evidence.",
        "scenarios": _criteria([
            {"name": "Path A", "probability": 0.25, "summary": "A path fades (25%).",
             "critique_note": "Evidence shifted toward B."},
            {"name": "Path B", "probability": 0.60, "summary": "B now most likely at 60%.",
             "critique_note": "Grid evidence favours B."},
            {"name": "Other / Status Quo", "probability": 0.15, "summary": "Mixed outcomes.",
             "critique_note": "Residual kept."},
        ]),
    }
    return forecast, critique


# The pre-REPORT-2 output of self_critique_forecast for _critique_case(), captured by
# running the base branch (feat/finharness-transplants @ 57d0e65) — the flag-off path
# must reproduce it exactly.
_LEGACY_CRITIQUE_OUTPUT = {
    "headline": "Path A leads at 45%, Path B trails at 35%, residual 20%.",
    "horizon": "2030",
    "confidence": "medium",
    "confidence_rationale": "Raised Path B to 60% on new grid evidence.",
    "scenarios": [
        {"name": "Path A", "probability": 0.3438, "summary": "A path fades (25%).",
         "key_drivers": [], "resolution_criteria": "Path A resolves by 2030",
         "critique_note": "Evidence shifted toward B."},
        {"name": "Path B", "probability": 0.45, "summary": "B now most likely at 60%.",
         "key_drivers": [], "resolution_criteria": "Path B resolves by 2030",
         "critique_note": "Grid evidence favours B."},
        {"name": "Other / Status Quo", "probability": 0.2062, "summary": "Mixed outcomes.",
         "key_drivers": [], "resolution_criteria": "Other / Status Quo resolves by 2030",
         "critique_note": "Residual kept."},
    ],
    "critiqued": True,
}


def test_critique_integration(monkeypatch):
    forecast, critique = _critique_case()
    snapshot = copy.deepcopy(forecast)

    out = FE.self_critique_forecast(forecast, FakeLLMClient(json_responses=[critique]))

    assert out["critiqued"] is True
    probabilities = {row["name"]: row["probability"] for row in out["scenarios"]}
    peak = max(probabilities.values())
    assert probabilities["Path B"] == peak == 0.45           # critic's 60% clamped to 45%
    # "residual 20%" names no scenario ("Other / Status Quo"), so it is no slot and
    # stays (the rule fails closed); the two labelled numbers are synced.
    assert out["headline"] == "Path A leads at 34%, Path B trails at 45%, residual 20%."
    assert "60%" not in out["headline"]
    assert out["headline_detail"] == snapshot["headline"]
    assert out["confidence_rationale"] == "Raised Path B to 45% on new grid evidence."
    assert out["confidence_rationale_detail"] == critique["confidence_rationale"]
    rows = {row["name"]: row for row in out["scenarios"]}
    assert rows["Path A"]["summary"] == "A path fades (34%)."
    assert rows["Path B"]["summary"] == "B now most likely at 45%."
    assert rows["Path B"]["summary_detail"] == "B now most likely at 60%."
    assert "summary_detail" not in rows["Other / Status Quo"]
    assert len(out["quality"]["narrative_sync"]) == 5
    assert out["quality"]["narrative_sync_skipped"] == {"no_slot": 1}
    assert FE.audit_scenario_contract(out)["valid"] is True
    assert forecast == snapshot                               # input never mutated

    monkeypatch.setattr(Config, "REPORT_NARRATIVE_SYNC", False, raising=False)
    off = FE.self_critique_forecast(forecast, FakeLLMClient(json_responses=[critique]))
    assert off["headline"] == snapshot["headline"]            # byte-identical to the input


def _critique_json():
    forecast, critique = _critique_case()
    out = FE.self_critique_forecast(forecast, FakeLLMClient(json_responses=[critique]))
    return json.dumps(out, ensure_ascii=False, sort_keys=True)


def test_critique_flag_off_is_byte_identical(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_NARRATIVE_SYNC", False, raising=False)
    flag_off = _critique_json()
    monkeypatch.setattr(FE, "_sync_forecast_narratives", lambda *_args, **_kwargs: None)

    assert flag_off == _critique_json()                       # == no sync call at all
    assert flag_off == json.dumps(_LEGACY_CRITIQUE_OUTPUT, ensure_ascii=False, sort_keys=True)


def test_critique_flag_on_touches_only_narrative_fields(monkeypatch):
    out = json.loads(_critique_json())
    monkeypatch.setattr(FE, "_sync_forecast_narratives", lambda *_args, **_kwargs: None)
    unsynced = json.loads(_critique_json())

    for target, field in [(out, "headline"), (out, "confidence_rationale"),
                          *[(row, "summary") for row in out["scenarios"]]]:
        if f"{field}_detail" in target:
            target[field] = target.pop(f"{field}_detail")
    out.pop("quality")
    assert out == unsynced


def test_critique_residual_template_rationale_is_not_synced():
    forecast = {
        "headline": "Path A 80%, Path B 20%.",
        "horizon": "2030",
        "confidence": "medium",
        "confidence_rationale": "Path A 80%.",
        "scenarios": _criteria(_rows(("Path A", 0.80), ("Path B", 0.20))),
    }
    critique = {"confidence_rationale": "Path A cut to 55%.",
                "scenarios": _criteria(_rows(("Path A", 0.55), ("Path B", 0.45)))}

    out = FE.self_critique_forecast(forecast, FakeLLMClient(json_responses=[critique]))

    assert out["residual_scenario_added"] is True
    assert "complete 100% partition" in out["confidence_rationale"]
    assert out["confidence_rationale_detail"] == "Path A cut to 55%."
    probabilities = {row["name"]: row["probability"] for row in out["scenarios"]}
    assert out["headline"] == (f"Path A {round(probabilities['Path A'] * 100)}%, "
                               f"Path B {round(probabilities['Path B'] * 100)}%.")
    assert out["headline_detail"] == "Path A 80%, Path B 20%."
    assert FE.audit_scenario_contract(out)["valid"] is True


def test_critique_survives_a_sync_failure(monkeypatch, caplog):
    forecast, critique = _critique_case()

    def boom(*_args, **_kwargs):
        raise RuntimeError("sync exploded")

    monkeypatch.setattr(FE, "synchronize_forecast_narratives", boom)
    out = FE.self_critique_forecast(forecast, FakeLLMClient(json_responses=[critique]))

    assert out["critiqued"] is True                           # critique kept, not discarded
    assert out["headline"] == forecast["headline"]
    assert "quality" not in out
    assert "sync exploded" in caplog.text


def test_rewrite_failure_leaves_out_untouched(monkeypatch):
    out = {"headline": "A 40%.", "confidence_rationale": "A 40%.",
           "scenarios": _rows(("A", 0.35), ("B", 0.65))}
    snapshot = copy.deepcopy(out)
    calls = []
    real_rewrite = NS._rewrite

    def flaky(*args):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("second field fails")
        return real_rewrite(*args)

    monkeypatch.setattr(NS, "_rewrite", flaky)
    with pytest.raises(RuntimeError):
        synchronize_forecast_narratives(out, headline_before=_rows(("A", 0.40), ("B", 0.60)),
                                        rationale_before=_rows(("A", 0.40), ("B", 0.60)))
    assert out == snapshot                                    # compute-then-apply


def _premortem_case():
    return {
        "headline": "Base case (60%) vs downside (25%); other 15%.",
        "confidence_rationale": "Base 60% reflects the pipeline.",
        "scenarios": _criteria([
            {"name": "Base", "probability": 0.60, "summary": "Base at 60%."},
            {"name": "Downside", "probability": 0.25, "summary": "Downside at 25%."},
            {"name": "Other", "probability": 0.15, "summary": "Other paths."},
        ]),
    }


_PREMORTEM_REPLY = {"underweighted_scenario": "Downside", "missed_signals": ["grid delays"],
                    "overconfident_scenario": "Base"}


def _pooling_draws():
    draw0 = {"headline": "基准情景（60%）领先，下行情景（30%）次之，兜底10%。", "horizon": "2030",
             "confidence": "medium", "confidence_rationale": "基准概率0.60。",
             "scenarios": _criteria([
                 {"name": "基准", "probability": 0.6, "summary": "基准（60%）。"},
                 {"name": "下行", "probability": 0.3, "summary": "下行（30%）。"},
                 {"name": "其它", "probability": 0.1, "summary": "兜底。"}])}
    draw1 = copy.deepcopy(draw0)
    draw1["scenarios"][0]["probability"] = 0.4
    draw1["scenarios"][1]["probability"] = 0.5
    return [draw0, draw1]


def test_premortem_and_pooling(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_PREMORTEM", True, raising=False)
    forecast = _premortem_case()
    out = FE.premortem_forecast(forecast, FakeLLMClient(json_responses=[_PREMORTEM_REPLY]))
    probabilities = {row["name"]: row["probability"] for row in out["scenarios"]}
    assert probabilities == {"Base": 0.55, "Downside": 0.30, "Other": 0.15}
    assert out["headline"] == "Base case (55%) vs downside (30%); other 15%."
    assert out["headline_detail"] == forecast["headline"]
    assert out["confidence_rationale"] == "Base 55% reflects the pipeline."
    assert [row["summary"] for row in out["scenarios"]] == [
        "Base at 55%.", "Downside at 30%.", "Other paths."]
    assert forecast["headline"] == "Base case (60%) vs downside (25%); other 15%."

    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 2, raising=False)
    draws = _pooling_draws()
    spine = FE.derive_forecast_spine(FakeLLMClient(json_responses=draws), central_question="q")
    pooled = {row["name"]: row["probability"] for row in spine["scenarios"]}
    assert spine["self_consistency_k"] == 2
    assert pooled == {"基准": 0.5, "下行": 0.4, "其它": 0.1}
    assert spine["headline"] == "基准情景（50%）领先，下行情景（40%）次之，兜底10%。"
    assert spine["headline_detail"] == draws[0]["headline"]
    assert spine["confidence_rationale"] == "基准概率0.50。"
    assert [row["summary"] for row in spine["scenarios"]] == ["基准（50%）。", "下行（40%）。", "兜底。"]
    assert len(spine["quality"]["narrative_sync"]) == 5


def test_pooling_then_critique_keeps_an_ambiguous_value_blocked(monkeypatch):
    """K=2 pooling leaves the shared '40%' stale; the critique that follows must not map
    both onto Base's move (Bear would be shown with Base's new 30%)."""
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 2, raising=False)
    draw0 = {"headline": "Base (40%) vs Bear (40%); Other 20%.", "horizon": "2030",
             "confidence": "medium", "confidence_rationale": "Spine view.",
             "scenarios": _criteria(_rows(("Base", 0.40), ("Bear", 0.40),
                                          ("Other / Status Quo", 0.20)))}
    draw1 = copy.deepcopy(draw0)
    draw1["scenarios"][1]["probability"] = 0.30
    draw1["scenarios"][2]["probability"] = 0.30
    spine = FE.derive_forecast_spine(FakeLLMClient(json_responses=[draw0, draw1]),
                                     central_question="q")
    assert {row["name"]: row["probability"] for row in spine["scenarios"]} == {
        "Base": 0.40, "Bear": 0.35, "Other / Status Quo": 0.25}
    assert spine["headline"] == "Base (40%) vs Bear (40%); Other 25%."
    assert spine["quality"]["narrative_sync_blocked"] == {"headline": [40]}

    critique = {"confidence": "medium", "scenarios": _criteria(_rows(
        ("Base", 0.30), ("Bear", 0.35), ("Other / Status Quo", 0.35)))}
    out = FE.self_critique_forecast(spine, FakeLLMClient(json_responses=[critique]))

    assert out["critiqued"] is True
    assert {row["name"]: row["probability"] for row in out["scenarios"]} == {
        "Base": 0.30, "Bear": 0.35, "Other / Status Quo": 0.35}
    assert out["headline"] == "Base (40%) vs Bear (40%); Other 35%."
    assert out["headline_detail"] == "Base (40%) vs Bear (40%); Other 20%."
    assert out["quality"]["narrative_sync_skipped"] == {"ambiguous": 4}


def test_critic_rationale_citing_input_values_is_not_rewritten():
    """A critic swaps Bear and Bull and writes 'Bear's 30%' about the INPUT Bear while
    its own Bull is 30%.  Normalisation moves every value (the rows sum to 0.95), so
    without the input rows as context the sync would print 'Bear's 32%', a value Bear
    never had.  A value the input gave another scenario is ambiguous in every
    critic-written field (acceptance 2); a value the input never held is still synced."""
    forecast = {
        "headline": "Base (40%) leads; Bear 30%, Bull 20%, Other 10%.",
        "horizon": "2030",
        "confidence": "medium",
        "confidence_rationale": "Spine view.",
        "scenarios": _criteria(_rows(("Base", 0.40), ("Bear", 0.30), ("Bull", 0.20),
                                     ("Other / Status Quo", 0.10))),
    }
    rationale = ("Bear's 30% ignored grid relief, so Bear is cut to 20% and Bull raised to 30%; "
                 "Base trimmed to 35%.")
    critique = {
        "confidence": "medium",
        "confidence_rationale": rationale,
        "scenarios": _criteria([
            {"name": "Base", "probability": 0.35, "summary": "Base trimmed to 35%."},
            {"name": "Bear", "probability": 0.20, "summary": "Bear cut to 20%."},
            {"name": "Bull", "probability": 0.30, "summary": "Bull (30%) takes Bear's former 30%."},
            {"name": "Other / Status Quo", "probability": 0.10, "summary": "Residual paths (10%)."},
        ]),
    }

    out = FE.self_critique_forecast(forecast, FakeLLMClient(json_responses=[critique]))

    assert out["critiqued"] is True
    assert {row["name"]: row["probability"] for row in out["scenarios"]} == {
        "Base": 0.3684, "Bear": 0.2105, "Bull": 0.3158, "Other / Status Quo": 0.1053}
    # The headline was written against the input rows: every value is attributable.
    assert out["headline"] == "Base (37%) leads; Bear 21%, Bull 32%, Other 11%."
    # 30% (input Bear, critic Bull) and 20% (input Bull, critic Bear) stay; 35% is synced.
    assert out["confidence_rationale"] == rationale.replace("trimmed to 35%", "trimmed to 37%")
    assert "Bear's 30%" in out["confidence_rationale"]
    assert out["confidence_rationale_detail"] == rationale
    assert [row["summary"] for row in out["scenarios"]] == [
        "Base trimmed to 37%.",
        "Bear cut to 20%.",                  # precision first: the input Bull also held 20%
        "Bull (30%) takes Bear's former 30%.",
        "Residual paths (11%).",             # the input held 10% under the same name
    ]
    quality = out["quality"]
    assert quality["narrative_sync_skipped"] == {"ambiguous": 6}
    assert quality["narrative_sync_blocked"] == {
        "confidence_rationale": [20, 30], "summary:bear": [20], "summary:bull": [30]}
    assert [edit["field"] for edit in quality["narrative_sync"]] == [
        "headline"] * 4 + ["confidence_rationale", "scenario[0].summary", "scenario[3].summary"]


def test_pooling_then_critique_keeps_a_foreign_value_blocked(monkeypatch):
    """Pooling makes Bear 25%, the value of an unrelated 'early rate cut (25%)' in
    draws[0]'s headline; the critique that then moves Bear 25→20 must not rewrite
    that outside probability."""
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 2, raising=False)
    draw0 = {"headline": "Base (40%) leads; an early rate cut (25%) would lift Bull.",
             "horizon": "2030", "confidence": "medium", "confidence_rationale": "Spine view.",
             "scenarios": _criteria(_rows(("Base", 0.40), ("Bear", 0.30), ("Bull", 0.20),
                                          ("Other / Status Quo", 0.10)))}
    draw1 = copy.deepcopy(draw0)
    for row, probability in zip(draw1["scenarios"], (0.40, 0.20, 0.20, 0.20), strict=True):
        row["probability"] = probability

    spine = FE.derive_forecast_spine(FakeLLMClient(json_responses=[draw0, draw1]),
                                     central_question="q")
    assert {row["name"]: row["probability"] for row in spine["scenarios"]} == {
        "Base": 0.40, "Bear": 0.25, "Bull": 0.20, "Other / Status Quo": 0.15}
    assert spine["headline"] == draw0["headline"]
    assert spine["quality"]["narrative_sync_skipped"] == {"foreign": 1}
    assert spine["quality"]["narrative_sync_blocked"] == {"headline": [25]}
    unblocked = copy.deepcopy(spine)
    del unblocked["quality"]["narrative_sync_blocked"]

    critique = {"confidence": "medium", "scenarios": _criteria(_rows(
        ("Base", 0.40), ("Bear", 0.20), ("Bull", 0.20), ("Other / Status Quo", 0.20)))}
    out = FE.self_critique_forecast(spine, FakeLLMClient(json_responses=[copy.deepcopy(critique)]))

    assert out["critiqued"] is True
    assert out["scenarios"][1]["probability"] == 0.20
    assert out["headline"] == draw0["headline"]
    assert out["quality"]["narrative_sync_skipped"] == {"foreign": 1, "ambiguous": 1}

    rewritten = FE.self_critique_forecast(unblocked, FakeLLMClient(json_responses=[critique]))
    assert "an early rate cut (20%)" in rewritten["headline"]   # what the record stops


def _pooled_critique():
    return {"confidence": "medium", "scenarios": _criteria([
        {"name": "基准", "probability": 0.45, "summary": "基准（45%）。"},
        {"name": "下行", "probability": 0.40, "summary": "下行（40%）。"},
        {"name": "其它", "probability": 0.10, "summary": "兜底。"}])}


_POOLED_PREMORTEM_REPLY = {"underweighted_scenario": "下行", "missed_signals": ["并网延迟"],
                           "overconfident_scenario": "基准"}


def _pooled_prompts():
    """K=2 pooling → critique → pre-mortem; returns (critique prompt, pre-mortem prompt, out)."""
    spine = FE.derive_forecast_spine(FakeLLMClient(json_responses=_pooling_draws()),
                                     central_question="q")
    critic = FakeLLMClient(json_responses=[_pooled_critique()])
    critiqued = FE.self_critique_forecast(spine, critic)
    premortem = FakeLLMClient(json_responses=[dict(_POOLED_PREMORTEM_REPLY)])
    out = FE.premortem_forecast(critiqued, premortem)
    return critic.calls[0]["messages"][0]["content"], premortem.calls[0]["messages"][0]["content"], out


def test_critique_and_premortem_prompts_omit_sync_bookkeeping(monkeypatch):
    """The originals and the edit log the sync keeps never reach the LLM: they would
    hand the critic the stale numbers the sync just removed, and cost prompt tokens."""
    monkeypatch.setattr(Config, "REPORT_PREMORTEM", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 2, raising=False)

    critique_prompt, premortem_prompt, out = _pooled_prompts()

    assert out["headline_detail"] == _pooling_draws()[0]["headline"]
    assert out["critiqued"] is True and "premortem" in out
    assert len(out["quality"]["narrative_sync"]) > 5          # pooling and critique both synced
    for prompt in (critique_prompt, premortem_prompt):
        assert "_detail" not in prompt
        assert "narrative_sync" not in prompt
        assert "60%" not in prompt and "0.60" not in prompt   # draws[0]'s stale values
        payload = json.loads(prompt.split("[预测对象]\n", 1)[1])
        assert "quality" not in payload
        assert payload["headline"].startswith("基准情景（")
    assert json.loads(critique_prompt.split("[预测对象]\n", 1)[1])["headline"] == (
        "基准情景（50%）领先，下行情景（40%）次之，兜底10%。")


def test_premortem_prompt_keeps_the_legacy_residual_rationale_detail(monkeypatch):
    """confidence_rationale_detail written by the residual path (flag on or off) is legacy
    prompt content and stays; only the sync's own bookkeeping is dropped."""
    monkeypatch.setattr(Config, "REPORT_PREMORTEM", True, raising=False)
    forecast = {
        "headline": "Path A 80%, Path B 20%.",
        "horizon": "2030",
        "confidence": "medium",
        "confidence_rationale": "Path A 80%.",
        "scenarios": _criteria(_rows(("Path A", 0.80), ("Path B", 0.20))),
    }
    critique = {"confidence_rationale": "Path A cut to 55%.",
                "scenarios": _criteria(_rows(("Path A", 0.55), ("Path B", 0.45)))}
    reply = {"underweighted_scenario": "Path B", "missed_signals": ["x"],
             "overconfident_scenario": "Path A"}
    for flag in (True, False):
        monkeypatch.setattr(Config, "REPORT_NARRATIVE_SYNC", flag, raising=False)
        critiqued = FE.self_critique_forecast(copy.deepcopy(forecast),
                                              FakeLLMClient(json_responses=[critique]))
        assert critiqued["residual_scenario_added"] is True
        assert ("headline_detail" in critiqued) is flag
        premortem = FakeLLMClient(json_responses=[dict(reply)])
        FE.premortem_forecast(critiqued, premortem)
        prompt = premortem.calls[0]["messages"][0]["content"]
        assert '"confidence_rationale_detail": "Path A cut to 55%."' in prompt
        assert "headline_detail" not in prompt


def test_prompts_are_byte_identical_with_the_sync_off(monkeypatch):
    """Flag off: the critique and pre-mortem prompts equal the pre-REPORT-2 construction
    (json.dumps of the forecast itself)."""
    monkeypatch.setattr(Config, "REPORT_NARRATIVE_SYNC", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_PREMORTEM", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 2, raising=False)
    flag_off = _pooled_prompts()
    monkeypatch.setattr(FE, "_llm_forecast_view", lambda forecast: forecast)
    legacy = _pooled_prompts()

    assert flag_off[:2] == legacy[:2]
    assert json.dumps(flag_off[2], ensure_ascii=False) == json.dumps(legacy[2], ensure_ascii=False)


def test_premortem_and_pooling_flag_off_match_the_unsynced_path(monkeypatch):
    """Flag off == the code path with no sync call at all (the pre-REPORT-2 bytes)."""
    monkeypatch.setattr(Config, "REPORT_PREMORTEM", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 2, raising=False)

    def run():
        premortem = FE.premortem_forecast(_premortem_case(),
                                          FakeLLMClient(json_responses=[_PREMORTEM_REPLY]))
        spine = FE.derive_forecast_spine(FakeLLMClient(json_responses=_pooling_draws()),
                                         central_question="q")
        return json.dumps([premortem, spine], ensure_ascii=False, sort_keys=True)

    monkeypatch.setattr(Config, "REPORT_NARRATIVE_SYNC", False, raising=False)
    flag_off = run()
    monkeypatch.setattr(Config, "REPORT_NARRATIVE_SYNC", True, raising=False)
    synced = run()
    monkeypatch.setattr(FE, "_sync_forecast_narratives", lambda *_args, **_kwargs: None)
    unsynced = run()
    assert flag_off == unsynced
    assert synced != unsynced


def test_premortem_and_pooling_flag_off_are_unchanged(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_NARRATIVE_SYNC", False, raising=False)
    monkeypatch.setattr(Config, "REPORT_PREMORTEM", True, raising=False)
    forecast = _premortem_case()
    out = FE.premortem_forecast(forecast, FakeLLMClient(json_responses=[_PREMORTEM_REPLY]))
    assert out["scenarios"][0]["probability"] == 0.55
    assert out["headline"] == forecast["headline"]
    assert out["confidence_rationale"] == forecast["confidence_rationale"]
    assert [row["summary"] for row in out["scenarios"]] == [
        row["summary"] for row in forecast["scenarios"]]
    assert "quality" not in out and "headline_detail" not in out

    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 2, raising=False)
    draws = _pooling_draws()
    spine = FE.derive_forecast_spine(FakeLLMClient(json_responses=draws), central_question="q")
    assert spine["scenarios"][0]["probability"] == 0.5
    assert spine["headline"] == draws[0]["headline"]
    assert spine["scenarios"][0]["summary"] == "基准（60%）。"
    assert "quality" not in spine and "headline_detail" not in spine


def test_single_spine_draw_is_not_synced(monkeypatch):
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 1, raising=False)
    draw = _pooling_draws()[0]
    spine = FE.derive_forecast_spine(FakeLLMClient(json_responses=[draw]), central_question="q")
    assert spine["headline"] == draw["headline"]
    assert "quality" not in spine


# ------------------------------------------------------------------ round-3 review probes
# Round 3 found that a deny-list quantity guard fails open: 262 of the reviewer's 458
# should-stay phrasings and 3 of 7 distinct archive-replay edits were rewritten.  The
# rule is now a fail-closed slot allowlist (see the module docstring).  Below are the
# reviewer's probes (report2_round3_review.md; probe scripts p1–p7 and final_probes),
# the archived false edits and the phrasings the new label slot must reject.  Every
# reviewer probe moves A 40→35 with C 20→22 and D 15→18.
_PROBE_BEFORE = _rows(("A", 0.40), ("B", 0.25), ("C", 0.20), ("D", 0.15))
_PROBE_AFTER = _rows(("A", 0.35), ("B", 0.25), ("C", 0.22), ("D", 0.18))

_REVIEW_KEEP_PROBES = (
    # p1: quantities, shares, rates, thresholds and metrics
    '成本下降40%，基准情景仍占主导', '价格涨40%', '价格上涨了40%', 'a 40% decline in costs',
    'costs 40% cheaper', '40% more capacity', 'capex cut 40%', 'capex was cut by 40%',
    '约40%的装机来自中国', '关税40%', '40%的关税', 'WACC 40%', 'ROE of 40%', '毛利40%',
    'inflation at 40%', '40% inflation', '40% of respondents said yes', '40% of GDP', '占GDP的40%',
    'p=0.40, significant', '(p = 0.40) not significant', '(p=0.40; statistically significant)',
    '概率加权成本0.40', 'market odds imply 40%', '2030年达到40%', '30–40%', '30-40%',
    'from 40% to 35%', '由40%下调至35%', '40%以上', 'EV share above 40%', '占比40%', '40%份额',
    '增长40%', '同比40%', '市占率40%', '渗透率达40%', '渗透率约40%', 'the utilization rate is 40%',
    'a 40% tariff', '40% import tariffs', 'unemployment of 40%', 'load factor 40%',
    '40% capacity factor', 'efficiency gains of 40%', 'prices rose 40%', 'prices rose by 40%',
    'prices are up 40%', 'prices fell nearly 40%', 'prices dropped roughly 40% year on year',
    'a drop of 40%', 'a decline of about 40%', 'a 40 % drop', '40% lower costs',
    'a 40%-lower cost', 'costs are 40% below 2020 levels', 'costs are 40% above 2020 levels',
    '40% higher than', '40% less expensive', 'shrinks by 40%', 'shrank 40%', 'grew 40%',
    'expanded 40%', 'a 40% expansion', 'a 40% contraction', 'a 40% discount', '40% premium',
    'a 40% stake', '40% owned by', '40% of the market', 'roughly 40% of new builds',
    'about 40% of capex', '40% of total', '工程完成40%', '降幅40%', '下滑40%', '萎缩40%',
    '缩水40%', '减少了约40%', '提升40%', '增加40%', '翻了40%', '年化40%', '收益率40%', '回报40%',
    '毛利率40%', '净利率达到40%', '负债率高达40%', '折旧40%', '40%的受访者', '40%的企业',
    '40%的GDP', '40%的人口', 'GDP的40%', '全球40%的产能', '占全球产能的约40%', '市场份额约为40%',
    '有40%的企业', '近40%的数据中心', '超过40%', '不到40%', '低于40%', '高于40%', '将近40%',
    '40% yield', 'a yield of 40%', '40% returns', '40% interest', '40% vacancy', '40% cut',
    '40% haircut', '40% markdown', '40% rebound', '40% slump', '40% plunge', '40% crash',
    '40% selloff', '40% rally', '40% improvement', '40% reduction', '40% savings', '40% saving',
    '40% smaller', '40% larger', '40% bigger', '40% fewer', '40% faster', '40% slower',
    '40% of the time', '40% chance-weighted cost', '40% utilization', '40% occupancy',
    '40% uptime', '40% efficient', '40% complete', '40% done', '40% renewable', '40% renewables',
    '40% electrified', '40% adoption', 'adoption of 40%', 'adoption reaches 40%',
    'adoption hits 40%', 'coverage of 40%', '40% coverage', '40% mix', 'the mix is 40%',
    '40% probability-weighted', 'by 2030, 40% of cars are EVs', 'EVs reach 40% of sales',
    'EVs reach 40% by 2030', 'EVs account for 40%', 'EVs make up 40%', 'EVs comprise 40%',
    'EVs represent 40%', 'EVs represent roughly 40%', 'EV penetration hits 40%',
    'EV sales share of 40%', '40% attach rate', 'attach rate 40%', 'hit rate 40%',
    'win rate of 40%', 'success rate of 40%', 'failure rate 40%', 'default rate 40%',
    '40% default rate', 'a 40% hurdle', '40% threshold', 'threshold of 40%', '40% cap',
    'capped at 40%', 'a floor of 40%', '40% ceiling', '40% limit', '40% quota', 'a 40% quota',
    '40% local content', '40% LTV', 'LTV 40%', '40% leverage', '40% payout', 'payout ratio 40%',
    '40% tax', 'tax of 40%', 'a tax rate of 40%', '40% duty', '40% levy', '40% subsidy',
    '40% rebate', '40% down payment', '40% deposit', '40% equity', '40% debt', '40% volatility',
    'vol of 40%', '40% implied vol', '40% drawdown', '40% IRR', '40% ROI', '40% EBITDA margin',
    '40% gross margin', 'margin of 40%', '40% utilisation',
    # p2: round-2 CJK change verbs and English comparatives / change verbs
    '成本下降40%', '成本下降了40%', '成本下降了约40%', '成本减少40%', '成本减少了40%',
    '成本减少了约40%', '价格上涨了约40%', '装机增加了40%', '削减了40%', '削减了近40%', '缩减了40%',
    '压缩40%', '扩大40%', '腰斩40%', '下跌了40%', '下跌约40%', '跌了40%', '跌去40%', '跌掉40%',
    '回撤40%', '回撤了40%', '提升了40%', '提高了40%', '降低了40%', '降低了近40%', '下调40%',
    '上调40%', '收窄40%', '扩张40%', '翻倍后再涨40%', '价格较2020年低40%', '比2020年高40%',
    '较基准低40%', '便宜40%', '贵40%', '多40%', '少40%', '快40%', '慢40%', 'costs fell 40%',
    'costs have fallen 40%', 'costs have fallen by roughly 40%', 'costs decreased 40%',
    'a decrease of 40%', 'down about 40%', '40% below', '40% above', '40% under', '40% over',
    '40% higher', '40% greater', '40% worse', '40% better', '40% cheaper than', '40% costlier',
    'grow 40%', 'grows 40%', 'grew by 40%', 'shrinks 40%', 'contracted 40%', 'plunged 40%',
    'soared 40%', 'climbed 40%', 'tumbled 40%', 'slumped 40%', 'rebounded 40%', 'declined 40%',
    'slid 40%', 'sank 40%', 'lost 40%', 'added 40%', 'gained 40%', 'fell 40%', 'rose 40%',
    'increased 40%', 'doubled then rose 40%', 'sales jumped 40%', 'sales were up 40%',
    'sales were down 40%', 'cost is 40% lower', '40% year-over-year', '40% y/y', '40% YoY',
    '40% QoQ', '40% MoM', '40% annually', '40% a year', '40% per year', '40% p.a.',
    # p4: decimals that are not scenario probabilities
    'p=0.40 (n.s.)', 'p = 0.40; not statistically meaningful', 'regression p=0.40', 'R²=0.40',
    'r=0.40', 'beta 0.40', 'Brier 0.40', 'a Brier score of 0.40', 'log-loss 0.40',
    'probability calibration slope 0.40', 'probability-weighted 0.40',
    'probability weighted mean 0.40', 'probability. 0.40 of revenue',
    'Probability anchors matter. .40 of revenue comes from...', 'probability, e.g. 0.40',
    '概率加权后0.40', '概率区间0.40', '概率区间0.30-0.40', '概率0.30至0.40', '概率从0.40降到0.35',
    'probability $0.40', 'probability 0.40 USD', 'probability 0.40美元', '概率约0.40元',
    '概率约0.40亿', 'probability 0.40x', 'probability 0.40 GW', 'probability; 0.40',
    'Brier/probability 0.40', 'probability score 0.40', 'probability threshold 0.40',
    'probability cutoff of 0.40', 'probability floor 0.40', '概率阈值0.40', '概率下限0.40',
    'posterior probability ratio 0.40', 'the 0.40 probability', 'probability 0.40–0.45',
    'probability ~0.40 to 0.45', 'P=0.40 for H0', 'p=.40 (t-test)', 'p=0.40, CI 0.2-0.6',
    'Kelly probability 0.40 odds', 'market probability 0.40', 'Polymarket probability 0.40',
    'Polymarket prices it at 0.40',
    # p5: market and outside probabilities
    'Polymarket prices this at 40%', 'Polymarket 40%',
    "Polymarket's 40% US-China deal probability", "Kalshi's 40% on OH-Senate",
    'markets imply a 40% chance of a rate cut', 'the market-implied probability is 40%',
    '（Polymarket 40%）', '(Optimus-2026 at 40%)', 'Polymarket 对 2026 发布的 40% 概率',
    '市场隐含概率40%', '盘口40%', '赔率隐含40%', 'Metaculus community forecast 40%',
    'Metaculus: 40%', 'AI bubble 40%', 'the Fed cut odds are 40%',
    'a 40% chance of an early rate cut', '~40% residual R-trifecta paths', 'base rate 40%',
    'historical base rate of 40%', 'reference-class frequency 40%', '40% of comparable cases',
    'in 40% of past cycles', '40% hit rate for analogues', 'superforecasters put it at 40%',
    'experts give 40%', 'IEA puts the odds at 40%', 'BNEF 40% base case',
    # p7: round-2 leftovers (decimals after a comma, dash minus, <=, far quantity words)
    '该情景概率较高，EPS 0.40', '概率上升，股价跌0.40', 'probability up, EPS 0.40',
    'probability high, Sharpe 0.40', '概率不变，系数0.40', '概率下降，弹性0.40', '概率高：β=0.40',
    '概率高（β 0.40）', '概率与0.40的相关系数', 'probability vs. 0.40 correlation', 'gains of 40%',
    'a gain of 40%', 'rose sharply, 40%', 'SOX correction of –40% to –55%',
    'drawdown deepens to –40%', 'exceeds –40%', '—40% YoY', 'declines of —40%',
    'EU weakens CO2 target to <=40%', '目标削弱至 <=40%', '=<40%', '≦40%', '≧40%', '≥ 40%',
    '> 40%', '→40%', 'roughly 40% domestic EV penetration', '40% global EV share',
    '40% domestic penetration', '40% of new capacity', 'account for roughly 40%',
    'the US and China account for roughly 40% and 15–20% of the incremental capacity', '占约40%',
    '美国与中国分别占约40%与15–20%增量', '美国与中国分别约40%与15–20%增量',
    '美国约40%、中国15–20%的增量', '2027年AI收入不及$2T门槛的40%', '不及40%', '未及40%', '不足40%',
    '逾40%', '近四成', '40%上下', '40%左右的份额', 'post-SCOTUS ~40% ETR', '(40% H20 model)',
    'tariffs ratchet back toward the ~40% Liberation-Day peak',
    'IEA GEVO 2026 40% 2026 trajectory', 'China 40%, US 5.8%', 'softened 40% CO₂ rule',
    '(40%海外C端+AGI叙事优先)', 'BNEF 40% base case vs Plateau Thesis ~30%',
    # final probes (the review's issue list)
    'global IT installed capacity in 2030 reaches 190–210 GW, of which the US and China account for roughly 40% and 15–20% of the incremental capacity',
    'Polymarket provides one external calibration anchor (Optimus-2026 at 40%)',
    "Kalshi's 40% on OH-Senate-going-D aligns with the base case", '40% below 2020 levels',
    'China reaches ~40% domestic EV penetration', 'BNEF 40% global EV share by 2035',
    '概率较高，EPS 0.40',
)


_REVIEW_REWRITE_PROBES = [
    pytest.param('基准情景（40%）下装机达200GW',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 '基准情景（35%）下装机达200GW',
                 id='zh paren'),
    pytest.param('基准情景（40 %）',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 '基准情景（35 %）',
                 id='zh paren spaced'),
    pytest.param('Under the base case (40%), capacity grows',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 'Under the base case (35%), capacity grows',
                 id='en paren'),
    pytest.param('基准情景概率40%',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 '基准情景概率35%',
                 id='zh 概率'),
    pytest.param('基准情景的概率为40%',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 '基准情景的概率为35%',
                 id='zh 概率为'),
    pytest.param('基准情景概率约40%',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 '基准情景概率约35%',
                 id='zh 概率约'),
    pytest.param('基准情景概率降至40%',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 '基准情景概率降至35%',
                 id='zh 概率降至'),
    pytest.param('有40%的概率维持基准',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 '有35%的概率维持基准',
                 id='zh 40%的概率'),
    pytest.param('仅40%概率超预期上行',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 '仅35%概率超预期上行',
                 id='zh 40%概率'),
    pytest.param('40%的可能性',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 '35%的可能性',
                 id='zh 40%的可能'),
    pytest.param('a 40% probability of the base case',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 'a 35% probability of the base case',
                 id='en prob'),
    pytest.param('a 40% chance of the base case',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 'a 35% chance of the base case',
                 id='en chance'),
    pytest.param('40% likelihood',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 '35% likelihood',
                 id='en likelihood'),
    pytest.param('the base case carries 40% of the probability mass',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 'the base case carries 35% of the probability mass',
                 id='en of the probability mass'),
    pytest.param('Base holds 40% of probability',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 'Base holds 35% of probability',
                 id='en of the probability mass2'),
    pytest.param('基准情景（概率0.40）',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 '基准情景（概率0.35）',
                 id='decimal'),
    pytest.param('Base (p=0.40)',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 'Base (p=0.35)',
                 id='decimal p='),
    pytest.param('Base (P = .40)',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 'Base (P = .35)',
                 id='decimal P ='),
    pytest.param('probability of 0.40',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 'probability of 0.35',
                 id='decimal probability of'),
    pytest.param('prob. 0.40',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 'prob. 0.35',
                 id='decimal prob.'),
    pytest.param('Base (~52% share, 55%), Accelerated (~65–75%, 25%), and Plateau (~30–35%, 20%)',
                 _rows(('Base', 0.55), ('Acc', 0.25), ('Pla', 0.2)),
                 _rows(('Base', 0.5), ('Acc', 0.22), ('Pla', 0.18), ('Other', 0.1)),
                 'Base (~52% share, 50%), Accelerated (~65–75%, 22%), and Plateau (~30–35%, 18%)',
                 id='zh b283'),
    pytest.param('A（40%）B（25%）',
                 _rows(('A', 0.4), ('B', 0.25), ('C', 0.35)),
                 _rows(('A', 0.25), ('B', 0.2), ('C', 0.55)),
                 'A（25%）B（20%）',
                 id='no cascade'),
    pytest.param('基准情景（40％）',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 '基准情景（35％）',
                 id='fullwidth pct'),
    pytest.param('基准情景（~40%）',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 '基准情景（~35%）',
                 id='tilde hedge'),
    pytest.param('基准情景（约40%）',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 '基准情景（约35%）',
                 id='约 hedge'),
    pytest.param('基准情景[40%]',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 '基准情景[35%]',
                 id='in bracket'),
    pytest.param('The base case is 40% likely',
                 _PROBE_BEFORE, _PROBE_AFTER,
                 'The base case is 35% likely',
                 id="en 'is 40%'"),
]


@pytest.mark.parametrize("text", _REVIEW_KEEP_PROBES)
def test_review_probes_that_must_stay_untouched(text):
    new_text, edits, _ = sync_probability_numbers(text, _PROBE_BEFORE, _PROBE_AFTER)

    assert (new_text, edits) == (text, [])


@pytest.mark.xfail(strict=True, reason=(
    "Known residual: a bracket is a probability slot whatever its label ('Soft landing "
    "(40%)', '下行（40%）' must sync), so an outside probability in brackets whose value "
    "equals a scenario's old value is still rewritten."))
def test_bracketed_outside_probability_is_the_known_residual():
    assert sync_probability_numbers("AI bubble (40%)", _PROBE_BEFORE, _PROBE_AFTER)[0] == (
        "AI bubble (40%)")


@pytest.mark.parametrize("text, before, after, expected", _REVIEW_REWRITE_PROBES + [
    pytest.param(FFE1_HEADLINE.replace("、单年capex $2.5–3.2T", ""), FFE1_BEFORE, FFE1_AFTER,
                 FFE1_HEADLINE.replace("、单年capex $2.5–3.2T", "").replace("（40%）", "（35%）", 1)
                 .replace("仅10%概率", "仅5%概率"),
                 id="ffe1 zh"),
])
def test_review_probes_that_must_still_sync(text, before, after, expected):
    assert sync_probability_numbers(text, before, after)[0] == expected


@pytest.mark.parametrize("text, expected, no_slot", [
    ("Base: 40%; Bear: 20%", "Base: 35%; Bear: 22%", 2),
    ("Base 40%, Bear 20%, Bull 15%", "Base 35%, Bear 22%, Bull 18%", 3),
])
def test_label_lists_sync_only_when_the_label_names_the_scenario(text, expected, no_slot):
    before = _rows(("Base", 0.40), ("B", 0.25), ("Bear", 0.20), ("Bull", 0.15))
    after = _rows(("Base", 0.35), ("B", 0.25), ("Bear", 0.22), ("Bull", 0.18))

    assert sync_probability_numbers(text, before, after)[0] == expected
    # With the reviewer's A–D rows no label names a scenario: nothing is rewritten
    # (the accepted recall loss of failing closed).
    assert sync_probability_numbers(text, _PROBE_BEFORE, _PROBE_AFTER) == (
        text, [], {"no_slot": no_slot})


@pytest.mark.parametrize("text, skipped", [
    # the review's unexpectation probes: left alone (recall loss, never a false edit)
    ("基准情景占40%概率", {"quantity": 1}),
    ("the base case at 40%", {"no_slot": 1}),
    ("the base case, weighted at 40%", {"no_slot": 1}),
    ("Base holds 40%", {"no_slot": 1}),
    ("We assign the base case 40%", {"no_slot": 1}),
    ("基准情景权重40%", {"quantity": 1}),
    ("odds of 40% for Base", {"no_slot": 1}),
])
def test_review_recall_losses_are_left_alone(text, skipped):
    assert sync_probability_numbers(text, _PROBE_BEFORE, _PROBE_AFTER) == (text, [], skipped)


_E5C9E8_ROWS = _rows(
    ("D House + D Senate (clean Dem sweep)", 0.1876), ("D House + R Senate (split Congress)", 0.4371),
    ("D House + 50–50 Senate (VP Vance tiebreaker)", 0.1251), ("R trifecta preserved (status quo)", 0.1042),
    ("R House + D Senate (upset Democratic Senate, GOP House hold)", 0.0625),
    ("Other / ambiguous / contingent (election contested, delayed certification, or other "
     "non-standard outcome)", 0.0834))
_A53841_ROWS = _rows(
    ("China-led hardware ramp (base case)", 0.4771), ("Bull breakthrough — software + hardware compound", 0.1634),
    ("Bear plateau — hardware bottleneck bites", 0.2179), ("Other / Status Quo", 0.1416))
_A53841_ZH_ROWS = _rows(
    ("中国主导的硬件爬坡（基准情形）", 0.4771), ("牛市突破 — 软件 + 硬件复合", 0.1634),
    ("熊市平台期 — 硬件瓶颈显现", 0.2179), ("其他 / 维持现状", 0.1416))
_AA88CC_ROWS = _rows(
    ("Oscillating Bipolar Equilibrium (Chokepoint Reflexivity, base case)", 0.38),
    ("Accelerated Two-Bloc Bifurcation (Managed Decoupling)", 0.23),
    ("Escalation to Systemic Breakdown / Crisis", 0.14),
    ("Détente / Grand Bargain (Durable De-escalation)", 0.09),
    ("Status Quo / Other (Catch-all Fallback)", 0.16))


def _moved(rows, name, delta):
    return [{**row, "probability": round(row["probability"] + delta, 4)} if row["name"] == name else row
            for row in rows]


@pytest.mark.parametrize("text, before, moved_name, delta", [
    pytest.param(  # report_1b70ace5c9e8 confidence_rationale
        "Cannot be high because Polymarket resolution cluster still shows 16% residual R House and "
        "~10% residual R-trifecta paths.", _E5C9E8_ROWS, "R trifecta preserved (status quo)", -0.03,
        id="e5c9e8 residual paths"),
    pytest.param(  # report_970e5aa53841 confidence_rationale_detail
        "(4) Polymarket provides one external calibration anchor (Optimus-2026 at 14%) but limited "
        "coverage of the broader question.", _A53841_ROWS, "Other / Status Quo", -0.03, id="a53841 en"),
    pytest.param(
        "(4) Polymarket 提供了一个外部校准锚点（Optimus-2026 为 14%），但对更广泛问题的覆盖有限。",
        _A53841_ZH_ROWS, "其他 / 维持现状", -0.03, id="a53841 zh"),
    pytest.param(  # report_4c90deaa88cc: a true edit the fail-closed rule gives up
        "the four-scenario overconfidence was reduced, and the residual bucket was fattened to ~16% "
        "to carry model-specification and unknown-unknown risk.", _AA88CC_ROWS,
        "Status Quo / Other (Catch-all Fallback)", -0.03, id="aa88cc recall loss"),
    pytest.param(  # report_319207d17c9a scenario A summary: a rate compared in brackets
        "装机区间上限从原210 GW下调，因管道兑现率口径分歧大（13% vs 40-60%），中位预期应向保守端回归。",
        _QUANTITY_BEFORE, "Bear", -0.05, id="d17c9a rate comparison"),
])
def test_archived_false_edits_stay_untouched(text, before, moved_name, delta):
    """The review's archive replay (each scenario moved −3 points) rewrote the first
    three: market odds and a residual count, not the scenario's own probability.  The
    ffe1 English summary's "roughly 40%" is covered below."""
    after = _moved(before, moved_name, delta)

    new_text, edits, skipped = sync_probability_numbers(text, before, after)

    assert (new_text, edits) == (text, [])
    assert skipped and set(skipped) <= {"market", "no_slot"}


FFE1_EN_BEFORE = _rows(
    ("A: Base-case expansion (steady delivery after pipeline haircuts)", 0.40),
    ("B: Power-constrained (physical/regulatory constraints compress delivery)", 0.30),
    ("C: Financial tightening/credit contraction (AI revenue validation failure triggers "
     "renegotiation)", 0.20),
    ("D: Upside surprise (revenue explosion + rapid resolution of supply bottlenecks)", 0.10))
FFE1_EN_HEADLINE = (
    "Under the base case (40%), global IT installed capacity reaches 2030 at 190–210 GW, with "
    "single-year capex of $2.5–3.2T, but power hard constraints (30%) and financing tightening "
    "(20%) create a combined 50% downside tail, with only a 10% probability of upside surprise.")
FFE1_EN_SUMMARY = (
    "global IT installed capacity in 2030 reaches 190–210 GW, with single-year capex of "
    "$2.5–3.2T, of which the US and China account for roughly 40% and 15–20% of the "
    "incremental capacity")


def test_ffe1_english_run_syncs_the_headline_but_not_the_capacity_share():
    after = copy.deepcopy(FFE1_EN_BEFORE)
    for row, probability in zip(after, (0.35, 0.30, 0.20, 0.05), strict=True):
        row["probability"] = probability
    after.append({"name": "E: Other/hybrid paths (including inertia-driven status quo)",
                  "probability": 0.10})
    after[0]["summary"] = FFE1_EN_SUMMARY
    out = {"headline": FFE1_EN_HEADLINE, "scenarios": after}

    synchronize_forecast_narratives(out, headline_before=FFE1_EN_BEFORE,
                                    summary_before_by_name=FFE1_EN_BEFORE, context_rows=FFE1_EN_BEFORE)

    assert out["headline"] == (FFE1_EN_HEADLINE.replace("(40%)", "(35%)")
                               .replace("a 10% probability", "a 5% probability"))
    assert out["scenarios"][0]["summary"] == FFE1_EN_SUMMARY          # "roughly 40%" is a share
    assert out["quality"]["narrative_sync_skipped"] == {"no_slot": 1}


def test_an_outside_event_chance_never_takes_a_scenario_move():
    """p6: 'a 30% chance of an early rate cut' named no scenario, so Bear 30→35 must not
    rewrite it; a chance whose object is the scenario (or a scenario noun) is synced."""
    before = _rows(("Base", 0.50), ("Bear", 0.30), ("Bull", 0.20))
    after = _rows(("Base", 0.45), ("Bear", 0.35), ("Bull", 0.20))
    for text, expected in (
            ("Base (50%); a 30% chance of an early rate cut.", "Base (45%); a 30% chance of an early rate cut."),
            ("a 30% chance of Bear.", "a 35% chance of Bear."),
            ("a 30% chance of the bear case.", "a 35% chance of the bear case."),
            ("a 30% probability that the downside scenario plays out.",
             "a 35% probability that the downside scenario plays out."),
            ("Bear is 30% likely to materialise.", "Bear is 35% likely to materialise."),
            ("a 30% chance.", "a 35% chance."),
            ("30% likely to be delayed by permitting.", "30% likely to be delayed by permitting.")):
        assert sync_probability_numbers(text, before, after)[0] == expected

    # A one-word label must match its first letter ("Other" is the residual scenario,
    # "other central banks" is not); a multi-word label ignores case.
    before = _rows(("Base", 0.50), ("Other / Status Quo", 0.25), ("Bull", 0.20))
    after = _rows(("Base", 0.45), ("Other / Status Quo", 0.30), ("Bull", 0.25))
    for text, expected in (
            ("a 25% chance of other central banks cutting.", "a 25% chance of other central banks cutting."),
            ("a 25% chance of Other.", "a 30% chance of Other."),
            ("a 25% chance of the status quo.", "a 30% chance of the status quo.")):
        assert sync_probability_numbers(text, before, after)[0] == expected


def test_market_words_block_every_slot():
    before = _rows(("Base", 0.40), ("Bear", 0.25), ("Bull", 0.20), ("Other", 0.15))
    after = _rows(("Base", 0.35), ("Bear", 0.25), ("Bull", 0.22), ("Other", 0.18))
    for text in ("Polymarket prices Base at 40%.", "Kalshi's 40% on Base.", "Base (Polymarket 40%)",
                 "市场隐含基准情景概率40%", "Polymarket probability 0.40", "Base 40% on Kalshi.",
                 "Base (40%, per Metaculus)", "盘口：基准40%", "Polymarket 对基准情景给出 40% 概率",
                 "consensus puts Base at 40%.", "Fed funds futures imply a 40% chance of Base."):
        new_text, edits, skipped = sync_probability_numbers(text, before, after)
        assert (new_text, edits, skipped) == (text, [], {"market": 1}), text


@pytest.mark.parametrize("text", [
    "（成本减少了约40%）", "（装机增加了40%）", "（回撤40%）", "（价格较2020年低40%）", "（不及40%）",
    "（未及40%）", "(costs have fallen 40%)", "(grew 40%)", "(efficiency gains of 40%)", "(–40%)",
    "(<=40%)", "(>=40%)", "(≦40%)", "(≧40%)", "Base: 40% smaller", "Base: 40% larger",
    "Base: 40% greater", "Base: 40% fewer", "Base: 40% below", "Base: 40% above", "Base falls 40%.",
])
def test_quantity_guards_still_apply_inside_a_slot(text):
    before = _rows(("Base", 0.40), ("Bear", 0.60))
    after = _rows(("Base", 0.35), ("Bear", 0.65))

    assert sync_probability_numbers(text, before, after) == (text, [], {"quantity": 1})


@pytest.mark.parametrize("text", [
    "p=0.40 (n.s.)", "regression p=0.40", "(p=0.40, n.s.)", "(p = 0.40; t-test)", "概率较高，EPS 0.40",
    "probability threshold 0.40", "probability floor 0.40", "概率阈值0.40", "概率下限0.40",
    "概率区间0.40", "Brier/probability 0.40", "probability 0.40 GW", "Kelly probability 0.40 odds",
])
def test_decimals_outside_the_probability_slot_are_not_tokens(text):
    before = _rows(("Base", 0.40), ("Bear", 0.60))
    after = _rows(("Base", 0.35), ("Bear", 0.65))

    assert sync_probability_numbers(text, before, after) == (text, [], {})


# The label slot (d) is new: a label must name the scenario whose old value the number
# is, LINK words must end on a state word or "to", and the number must close its clause.
_LABEL_BEFORE = _rows(("Base", 0.40), ("Bear", 0.25), ("Bull", 0.20), ("基准情景", 0.15))
_LABEL_AFTER = _rows(("Base", 0.35), ("Bear", 0.25), ("Bull", 0.22), ("基准情景", 0.18))


@pytest.mark.parametrize("text", [
    "Base: 40% renewables by 2030", "In Base, 40% of capacity is gas", "Base assumes 40%.",
    "Base grows at 40%.", "Base case: 40% EV share", "Base: capex falls 40%.", "Base 40% tariff",
    "Base at 40% utilization", "Base hits 40%.", "Base reaches 40%.", "Base: 40%-45% range", "Bear's 40%",
    "Base, with 40%", "base 40%.", "Baseline 40%.", "Database 40%.", "Base grew 40%.", "Base falls 40%.",
    "Base is 40% higher.", "Base is 40% of demand.", "Base: EV share 40%.", "Bull at 40%.",
    "Base stands at 40% penetration.", "基准情景的装机40%。", "基准情景占15%。", "基准情景增长15%。",
    "基准情景较2020年高15%。", "the probability of reaching 40%.", "probability of 40% adoption",
    "probability that EV share exceeds 40%.", "chance of a 40% drawdown.", "the likelihood EVs reach 40%.",
    "概率较高的40%渗透率", "概率：EV渗透率40%。", "Probability-weighted capex 40%.",
    "probability mass: 40% of paths", "Base (EV share 40%)", "(Base: 40% share)", "Base [40% of load]",
    "a 40% probability of an EU ban", "40% likely to be delayed by 2030 permitting.",
    "Base, per Polymarket, at 40%.", "Base 40% on Kalshi.", "Base (40%, per Metaculus)",
    "基准情景（市场隐含40%）", "Base holds 40% of the market.", "Base carries 40% margin.", "Base: –40%.",
    "Base at <=40%.", "Base drops 40%.", "Base down 40%.", "Base rose 40%,", "Base cut 40%.",
    "兑现率口径分歧大（40% vs 40-60%）", "a 40% chance of recession",
])
def test_label_slot_rejects(text):
    new_text, edits, _ = sync_probability_numbers(text, _LABEL_BEFORE, _LABEL_AFTER)

    assert (new_text, edits) == (text, [])


@pytest.mark.parametrize("text, expected", [
    ("Base: 40%;", "Base: 35%;"), ("Base 40%, Bull 20%.", "Base 35%, Bull 22%."),
    ("Base at 40%.", "Base at 35%."), ("Base is 40%.", "Base is 35%."),
    ("Base case at 40%.", "Base case at 35%."),
    ("Base now 40% given grid relief.", "Base now 35% given grid relief."),
    ("Base's 40% reflects demand.", "Base's 35% reflects demand."),
    ("Bull raised to 20%, Base trimmed to 40%.", "Bull raised to 22%, Base trimmed to 35%."),
    ("基准情景15%，", "基准情景18%，"), ("基准15%，", "基准18%，"), ("基准情景为15%。", "基准情景为18%。"),
    ("基准情景降至15%。", "基准情景降至18%。"), ("probability of 40%.", "probability of 35%."),
    ("Base probability is now 40%.", "Base probability is now 35%."),
    ("a 40% probability of the Base scenario", "a 35% probability of the Base scenario"),
    ("a 40% chance of Base", "a 35% chance of Base"), ("Base (40%) leads", "Base (35%) leads"),
    ("(40% vs 20%)", "(35% vs 22%)"),
    ("Base is 40% likely to materialise.", "Base is 35% likely to materialise."),
    ("Base is cut to 40%.", "Base is cut to 35%."), ("Base falls to 40%.", "Base falls to 35%."),
    ("Base leads at 40%,", "Base leads at 35%,"),
])
def test_label_slot_accepts(text, expected):
    assert sync_probability_numbers(text, _LABEL_BEFORE, _LABEL_AFTER)[0] == expected


# ------------------------------------------------------------------ knob
def test_knob_defaults_on_and_is_documented():
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(backend, "app", "config.py"), encoding="utf-8") as handle:
        assert ("REPORT_NARRATIVE_SYNC = os.environ.get('REPORT_NARRATIVE_SYNC', 'true')"
                ".strip().lower() == 'true'") in handle.read()
    with open(os.path.join(os.path.dirname(backend), ".env.example"), encoding="utf-8") as handle:
        assert "# REPORT_NARRATIVE_SYNC=true " in handle.read()
