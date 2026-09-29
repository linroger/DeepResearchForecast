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
def test_archived_decimal_headlines_are_synced(headline, final_a, expected):
    before = _rows(("A. 基准", 0.40), ("B. 电力受限", 0.30), ("C. 财务紧缩", 0.20),
                   ("D. 上行", 0.10))
    after = _rows(("A. 基准", final_a), ("B. 电力受限", 0.28), ("C. 财务紧缩", 0.17),
                  ("D. 上行", 0.08), ("E. 兜底", 0.12))

    new_text, edits, _ = sync_probability_numbers(headline, before, after)

    assert new_text == headline.replace("0.40", f"{final_a:.2f}", 1)
    assert new_text.startswith(expected)
    assert [(e["from"], e["to"]) for e in edits] == [("0.40", f"{final_a:.2f}")]


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
    for untouched in ("costs 0.40 USD", "概率。成本0.40", "概率0.40%", "概率10.40", "概率0.405"):
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

    out["scenarios"] = _rows(("A", 0.30), ("B", 0.70))
    out["headline"] = "A 35% but 35% and 65%-70%."
    synchronize_forecast_narratives(out, headline_before=_rows(("A", 0.35), ("B", 0.65)))
    assert out["headline"] == "A 30% but 30% and 65%-70%."
    assert out["headline_detail"] == "A 40%."                  # first original wins
    assert len(out["quality"]["narrative_sync"]) == NARRATIVE_SYNC_LOG_CAP
    assert out["quality"]["narrative_sync_skipped"] == {"range": 3}


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
    assert sync_probability_numbers("A 40%, A 20%, B 30%, C 30%, D 100%", before, after)[1] == []


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
