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


_QUANTITY_BEFORE = _rows(("A", 0.40), ("D", 0.13), ("C", 0.47))
_QUANTITY_AFTER = _rows(("A", 0.35), ("D", 0.08), ("C", 0.57))


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
    ("a 40% chance of recession", "a 35% chance of recession"),
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
    ("a 40% likelihood of a soft landing", "a 35% likelihood of a soft landing"),
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
        {"name": "B", "probability": 0.35, "summary": "Grid-limited path at 30%."},
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
    assert after[1]["summary"] == "Grid-limited path at 35%."
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
    out["headline"] = "A 35% but 35% and 65%-70%."
    synchronize_forecast_narratives(out, headline_before=_rows(("A", 0.35), ("B", 0.65)))
    assert out["headline"] == "A 30% but 30% and 65%-70%."
    assert out["headline_detail"] == "A 40%."                  # first original wins
    assert len(out["quality"]["narrative_sync"]) == NARRATIVE_SYNC_LOG_CAP
    assert out["quality"]["narrative_sync_dropped"] == 2      # the cap never drops silently
    assert out["quality"]["narrative_sync_skipped"] == {"range": 3}

    out["scenarios"] = _rows(("A", 0.25), ("B", 0.75))
    synchronize_forecast_narratives(out, headline_before=_rows(("A", 0.30), ("B", 0.70)))
    assert out["headline"] == "A 25% but 25% and 65%-70%."
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
    """'a 25% chance of a cut' was written against no scenario.  Once a move makes 25%
    Bear's value, the next move must not treat that token as Bear's."""
    step0 = _rows(("Base", 0.40), ("Bear", 0.30), ("Bull", 0.20), ("Other", 0.10))
    step1 = _rows(("Base", 0.40), ("Bear", 0.25), ("Bull", 0.20), ("Other", 0.15))
    step2 = _rows(("Base", 0.40), ("Bear", 0.20), ("Bull", 0.20), ("Other", 0.20))
    out = {"headline": "Bear (30%); markets price a 25% chance of a cut; capex fell 25%."}

    _step(out, step0, step1)
    assert out["headline"] == "Bear (25%); markets price a 25% chance of a cut; capex fell 25%."
    assert out["quality"]["narrative_sync_skipped"] == {"foreign": 1}   # the quantity is guarded
    assert out["quality"]["narrative_sync_blocked"] == {"headline": [25]}
    unblocked = copy.deepcopy(out)
    del unblocked["quality"]["narrative_sync_blocked"]

    _step(out, step1, step2)                 # Bear 25→20: every 25% is left alone
    assert out["headline"] == "Bear (25%); markets price a 25% chance of a cut; capex fell 25%."
    assert out["quality"]["narrative_sync_skipped"] == {"foreign": 1, "ambiguous": 3}

    _step(unblocked, step1, step2)                             # the record is what guards it
    assert unblocked["headline"] == (
        "Bear (20%); markets price a 20% chance of a cut; capex fell 25%.")


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
    text = "Bear's 30% ignored grid relief: Bear cut to 20%, Bull raised to 30%, Base to 35%."

    out = {"confidence_rationale": text, "scenarios": copy.deepcopy(final_rows)}
    synchronize_forecast_narratives(out, rationale_before=critic_rows, context_rows=input_rows)
    assert out["confidence_rationale"] == text.replace("Base to 35%", "Base to 37%")
    assert out["quality"]["narrative_sync_skipped"] == {"ambiguous": 3}
    assert out["quality"]["narrative_sync_blocked"] == {"confidence_rationale": [20, 30]}

    unguarded = {"confidence_rationale": text, "scenarios": copy.deepcopy(final_rows)}
    synchronize_forecast_narratives(unguarded, rationale_before=critic_rows)
    assert unguarded["confidence_rationale"] == (      # what the input context prevents
        "Bear's 32% ignored grid relief: Bear cut to 21%, Bull raised to 32%, Base to 37%.")

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
    assert out["headline"] == "Path A leads at 34%, Path B trails at 45%, residual 21%."
    assert "60%" not in out["headline"]
    assert out["headline_detail"] == snapshot["headline"]
    assert out["confidence_rationale"] == "Raised Path B to 45% on new grid evidence."
    assert out["confidence_rationale_detail"] == critique["confidence_rationale"]
    rows = {row["name"]: row for row in out["scenarios"]}
    assert rows["Path A"]["summary"] == "A path fades (34%)."
    assert rows["Path B"]["summary"] == "B now most likely at 45%."
    assert rows["Path B"]["summary_detail"] == "B now most likely at 60%."
    assert "summary_detail" not in rows["Other / Status Quo"]
    assert len(out["quality"]["narrative_sync"]) == 6
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
    # INFRA-2's critique_attempted stamp is a separate knob; the legacy golden predates it.
    monkeypatch.setattr(Config, "REPORT_CRITIQUE_SINGLE_PASS", False, raising=False)
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
    """Pooling makes Bear 25%, the value of an unrelated '25% chance of an early rate
    cut' in draws[0]'s headline; the critique that then moves Bear 25→20 must not
    rewrite that market-implied probability."""
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 2, raising=False)
    draw0 = {"headline": "Base (40%) leads; markets price a 25% chance of an early rate cut.",
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
    assert "a 20% chance of an early rate cut" in rewritten["headline"]   # what the record stops


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
    # INFRA-2's critique_attempted stamp is a separate knob (its own prompt test lives in
    # test_critique_single_pass.py); the identity view below would echo it into the prompt.
    monkeypatch.setattr(Config, "REPORT_CRITIQUE_SINGLE_PASS", False, raising=False)
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


# ------------------------------------------------------------------ knob
def test_knob_defaults_on_and_is_documented():
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(backend, "app", "config.py"), encoding="utf-8") as handle:
        assert ("REPORT_NARRATIVE_SYNC = os.environ.get('REPORT_NARRATIVE_SYNC', 'true')"
                ".strip().lower() == 'true'") in handle.read()
    with open(os.path.join(os.path.dirname(backend), ".env.example"), encoding="utf-8") as handle:
        assert "# REPORT_NARRATIVE_SYNC=true " in handle.read()
