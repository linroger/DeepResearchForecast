"""LOOP-017 P0：市场影响边界（market influence boundary）——离线红线测试。

取证事故链（Tesla Optimus，P=0.125）：低置信 LLM 匹配把发布概率拉向市场价，随后
对账（reconcile_forecast_contract）整个弹出 market_anchor——修订后的概率永久保留、
市场溯源全部消失。本套测试钉住四条不变量：

  1. 低置信匹配**绝不**获得移动概率的资格（FORECAST_MARKET_DIVERGENCE_MIN_CONFIDENCE
     门槛；缺失/None 一律不合格）；
  2. 分歧重述被采纳且移动了概率 → 二元预测被盖上独立的 ``market_influence`` 印章
     （任何后续 pass 都不得弹出该键）；
  3. 对账弹出「曾移动过概率」的锚点时 → 恢复 prior_probability、追加解释、把
     anchor_removed / probability_restored 记进影响记录与 pass 诊断；
  4. build_market_comparison / 报告「Market Cross-Check」块必须展示全部市场实际
     移动过的概率（含锚点已被移除的情形）。
"""

from datetime import datetime, timezone

from app.config import Config
from app.services.forecast_extractor import (
    build_market_comparison,
    enforce_market_divergence,
    reconcile_forecast_contract,
)
from app.services.report_agent import render_market_comparison_block
from app.utils import prediction_markets
from tests.conftest import FakeLLMClient


def _divergent(confidence=0.9, prob=0.20, implied=0.55):
    """一条与市场分歧 >10pp、理由未引用市场的二元预测（含富锚点）。"""
    anchor = {
        "market_id": "m-1", "question": "Will X happen by 2027?",
        "implied_yes_prob": implied, "price_at_research": implied,
        "divergence": round(prob - implied, 4),
        "url": "https://polymarket.com/event/x", "endDate": "2027-12-31",
        "resolution_equivalence": "near",
    }
    if confidence is not None:
        anchor["match_confidence"] = confidence
    return {"id": "F1", "statement": "X happens by 2027", "probability": prob,
            "adjustment_rationale": "base rate says low", "market_anchor": anchor}


def _accepting_llm(prob=0.35):
    return FakeLLMClient(json_responses=[{"revisions": [
        {"id": "F1", "probability": prob,
         "adjustment_rationale": "The market implies 55%; I defer partly to the market."}]}])


# ---------------------------------------------- invariant 1: confidence gate
def test_low_confidence_match_cannot_move_probability():
    b = _divergent(confidence=0.4)
    fake = _accepting_llm()
    assert enforce_market_divergence([b], fake) == 0
    assert b["probability"] == 0.20                      # 概率纹丝不动
    assert fake.calls == []                              # 无候选 → 连重述调用都不发
    assert "market_influence" not in b


def test_missing_confidence_is_not_eligible():
    b = _divergent(confidence=None)                      # 锚点根本没记置信度
    fake = _accepting_llm()
    assert enforce_market_divergence([b], fake) == 0
    assert b["probability"] == 0.20 and fake.calls == []


def test_confidence_at_threshold_is_eligible():
    b = _divergent(confidence=0.6)                       # 恰在默认门槛 0.6 上 → 合格
    assert enforce_market_divergence([b], _accepting_llm()) == 1
    assert b["probability"] == 0.35


def test_confidence_gate_reads_config_knob(monkeypatch):
    monkeypatch.setattr(Config, "FORECAST_MARKET_DIVERGENCE_MIN_CONFIDENCE", 0.95,
                        raising=False)
    b = _divergent(confidence=0.9)                       # 0.9 < 调高后的 0.95 → 不合格
    fake = _accepting_llm()
    assert enforce_market_divergence([b], fake) == 0
    assert b["probability"] == 0.20 and fake.calls == []


# ------------------------------------------- invariant 2: durable influence stamp
def test_accepted_move_stamps_durable_market_influence():
    b = _divergent(confidence=0.9)
    assert enforce_market_divergence([b], _accepting_llm(0.35)) == 1
    inf = b["market_influence"]
    assert inf["market_id"] == "m-1"
    assert inf["market_question"] == "Will X happen by 2027?"
    assert inf["price_at_revision"] == 0.55
    assert inf["prior_probability"] == 0.20
    assert inf["revised_probability"] == 0.35
    assert inf["match_confidence"] == 0.9
    assert inf["resolution_equivalence"] == "near"


def test_rationale_only_revision_stamps_no_influence():
    b = _divergent(confidence=0.9)
    fake = FakeLLMClient(json_responses=[{"revisions": [
        {"id": "F1",                                     # 保留分歧：只重写理由，无 probability
         "adjustment_rationale": "The market implies 55% but it underweights the tail risk."}]}])
    assert enforce_market_divergence([b], fake) == 1
    assert b["probability"] == 0.20
    assert "market_influence" not in b                   # 概率没动 → 不盖影响印章


def test_repeat_revision_preserves_original_prior():
    b = _divergent(confidence=0.9)
    assert enforce_market_divergence([b], _accepting_llm(0.35)) == 1
    # 第二轮重述再次移动概率（0.35 → 0.42）：prior 必须仍是最初的 0.20。
    b["adjustment_rationale"] = "base rate only"         # 重新变成候选（不含市场字眼）
    b["market_anchor"]["divergence"] = round(0.35 - 0.55, 4)
    assert enforce_market_divergence([b], _accepting_llm(0.42)) == 1
    assert b["market_influence"]["prior_probability"] == 0.20
    assert b["market_influence"]["revised_probability"] == 0.42


# --------------------------------- invariant 3: reconcile restores moved probability
def _influenced_forecast(current=0.30, revised=0.30, prior=0.55):
    """构造一个「影响后锚点会被对账移除」的 forecast：无情景分区、锚点缺 hash 绑定。"""
    return {
        "scenarios": [],
        "binary_forecasts": [{
            "id": "F1",
            "statement": "Tesla ships Optimus robots commercially by 2027",
            "resolution_criteria": "Commercial Optimus deliveries confirmed by 2027-12-31",
            "probability": current,
            "adjustment_rationale": "The market implies 12.5%; I defer partly to the market.",
            "market_anchor": {
                "market_id": "m-opt", "question": "Optimus commercially available in 2027?",
                "implied_yes_prob": 0.125, "price_at_research": 0.125,
                "url": "https://polymarket.com/event/optimus", "endDate": "2027-12-31",
                "resolution_equivalence": "near", "match_confidence": 0.9,
                # 故意缺 forecast_proposition_id / sha 绑定 → 对账判定为不可验证 → 弹出。
            },
            "market_influence": {
                "market_id": "m-opt", "market_question": "Optimus commercially available in 2027?",
                "price_at_revision": 0.125, "prior_probability": prior,
                "revised_probability": revised, "match_confidence": 0.9,
                "resolution_equivalence": "near",
            },
        }],
    }


def test_reconcile_restores_probability_when_influencing_anchor_removed():
    forecast = _influenced_forecast(current=0.30, revised=0.30, prior=0.55)
    diag = reconcile_forecast_contract(forecast)
    b = forecast["binary_forecasts"][0]
    assert "market_anchor" not in b                      # 锚点确实被弹出
    assert b["probability"] == 0.55                      # 市场移动过的概率被恢复
    inf = b["market_influence"]                          # 影响印章绝不随锚点消失
    assert inf["anchor_removed"] is True
    assert inf["probability_restored"] is True
    assert "m-opt" in str(b["adjustment_rationale"])     # 追加了可读解释
    assert "restor" in str(b["adjustment_rationale"]).lower()
    assert diag["restored_market_influences"] == ["F1"]  # pass 诊断计数


def test_reconcile_does_not_restore_superseded_probability():
    # 当前概率 (0.44) ≠ 影响记录的 revised (0.30) → 影响已被后续步骤取代，绝不回滚。
    forecast = _influenced_forecast(current=0.44, revised=0.30, prior=0.55)
    diag = reconcile_forecast_contract(forecast)
    b = forecast["binary_forecasts"][0]
    assert "market_anchor" not in b
    assert b["probability"] == 0.44                      # 保持现值，不得回滚
    inf = b["market_influence"]
    assert inf["anchor_removed"] is True
    assert inf["probability_restored"] is False
    assert diag["restored_market_influences"] == []


def test_reconcile_never_rolls_back_partition_governed_probability():
    """分区治理优先：概率已被互斥情景分区验证/改写（canonical）时，哪怕数值恰与影响
    印章的 revised 巧合相等，弹锚也绝不回滚——回滚会制造分区失配。"""
    forecast = {
        "scenarios": [
            {"name": "D House + D Senate (clean Dem sweep)", "probability": 0.19},
            {"name": "D House + R Senate (split Congress)", "probability": 0.44},
            {"name": "D House + 50-50 Senate (GOP VP tiebreaker)", "probability": 0.13},
            {"name": "R trifecta preserved", "probability": 0.10},
            {"name": "R House + D Senate", "probability": 0.06},
            {"name": "Other / ambiguous / contested", "probability": 0.08},
        ],
        "binary_forecasts": [{
            "id": "F2", "statement": "Democrats win a 218+ House majority.",
            "resolution_criteria": "Democratic control of the House", "probability": 0.53,
            # 锚点命题（d_sweep）≠ 二元命题（d_house）→ 对账会弹出该锚点。
            "market_anchor": {
                "market_id": "m-x", "question": "2026 Balance of Power: D Senate, D House",
                "implied_yes_prob": 0.44, "price_at_research": 0.44,
                "url": "https://polymarket.com/event/balance", "endDate": "2026-11-03",
                "resolution_equivalence": "near", "match_confidence": 0.95,
            },
            # 影响印章的 revised (0.76) 与分区推出的 canonical 值巧合相等。
            "market_influence": {
                "market_id": "m-x", "market_question": "2026 Balance of Power: D Senate, D House",
                "price_at_revision": 0.44, "prior_probability": 0.53,
                "revised_probability": 0.76, "match_confidence": 0.95,
                "resolution_equivalence": "near",
            },
        }],
    }
    diag = reconcile_forecast_contract(forecast)
    b = forecast["binary_forecasts"][0]
    assert "market_anchor" not in b
    assert b["probability"] == 0.76                      # 分区 canonical 值（0.19+0.44+0.13）
    assert b["market_influence"]["anchor_removed"] is True
    assert b["market_influence"]["probability_restored"] is False
    assert diag["restored_market_influences"] == []
    assert diag["after"]["passed"] is True               # 分区一致性完好


def test_reconcile_removal_without_influence_needs_no_restore():
    forecast = _influenced_forecast()
    del forecast["binary_forecasts"][0]["market_influence"]
    forecast["binary_forecasts"][0]["probability"] = 0.30
    diag = reconcile_forecast_contract(forecast)
    b = forecast["binary_forecasts"][0]
    assert "market_anchor" not in b and b["probability"] == 0.30
    assert diag["restored_market_influences"] == []


def test_reconcile_keeps_influence_when_anchor_survives():
    # 锚点未被移除（不含影响印章的键弹出路径）→ market_influence 原样保留、无 removed 标记。
    forecast = _influenced_forecast(current=0.30, revised=0.30, prior=0.55)
    anchor = forecast["binary_forecasts"][0]["market_anchor"]
    # 补上 byte-bound 匹配契约 → 对账放行该锚点。
    import hashlib
    b = forecast["binary_forecasts"][0]
    b["proposition_id"] = "prop-1"
    contract_text = b["statement"] + "\n" + b["resolution_criteria"]
    anchor.update({
        "forecast_proposition_id": "prop-1",
        "forecast_contract_sha256": hashlib.sha256(contract_text.encode("utf-8")).hexdigest(),
        "market_question_sha256": hashlib.sha256(
            anchor["question"].encode("utf-8")).hexdigest(),
        "match_method": "bounded-semantic-equivalence-review",
    })
    diag = reconcile_forecast_contract(forecast)
    assert "market_anchor" in forecast["binary_forecasts"][0]
    inf = forecast["binary_forecasts"][0]["market_influence"]
    assert "anchor_removed" not in inf and forecast["binary_forecasts"][0]["probability"] == 0.30
    assert diag["restored_market_influences"] == []


# ---------------------------- invariant 4: comparison payload + report block surface
def test_build_market_comparison_includes_influences():
    binaries = [
        {"id": "F1", "statement": "X", "probability": 0.35,
         "adjustment_rationale": "market implies 55%",
         "market_anchor": {"market_id": "m-1", "question": "Q1", "implied_yes_prob": 0.55},
         "market_influence": {"market_id": "m-1", "market_question": "Q1",
                              "price_at_revision": 0.55, "prior_probability": 0.20,
                              "revised_probability": 0.35, "match_confidence": 0.9,
                              "resolution_equivalence": "near"}},
        {"id": "F2", "statement": "Y", "probability": 0.55,
         # 锚点已被对账移除，但影响印章仍在（含恢复标记）。
         "market_influence": {"market_id": "m-2", "market_question": "Q2",
                              "price_at_revision": 0.125, "prior_probability": 0.55,
                              "revised_probability": 0.30, "match_confidence": 0.7,
                              "resolution_equivalence": "near",
                              "anchor_removed": True, "probability_restored": True}},
        {"id": "F3", "statement": "Z", "probability": 0.5},          # 无锚无影响
    ]
    mc = build_market_comparison(binaries)
    assert mc["anchored_count"] == 1
    assert mc["influence_count"] == 2
    rows = {r["forecast_id"]: r for r in mc["influences"]}
    assert rows["F1"]["prior_probability"] == 0.20
    assert rows["F1"]["revised_probability"] == 0.35
    assert rows["F1"]["anchor_removed"] is False
    assert rows["F2"]["anchor_removed"] is True
    assert rows["F2"]["probability_restored"] is True
    assert rows["F2"]["current_probability"] == 0.55     # 恢复后的现值可见


def test_build_market_comparison_without_influences_keeps_legacy_shape():
    mc = build_market_comparison([
        {"id": "F1", "statement": "X", "probability": 0.2,
         "market_anchor": {"market_id": "m", "question": "Q", "implied_yes_prob": 0.55}}])
    assert "influences" not in mc and "influence_count" not in mc


def test_render_market_comparison_block_surfaces_influences_en():
    forecast = {
        "binary_forecasts": [],
        "market_comparison": {
            "anchored_count": 0, "comparisons": [],
            "influences": [{
                "forecast_id": "F2", "market_id": "m-opt",
                "market_question": "Optimus commercially available in 2027?",
                "price_at_revision": 0.125, "prior_probability": 0.55,
                "revised_probability": 0.30, "current_probability": 0.55,
                "match_confidence": 0.9, "resolution_equivalence": "near",
                "anchor_removed": True, "probability_restored": True,
            }],
            "influence_count": 1,
        },
    }
    block = render_market_comparison_block(forecast, markets=None, lang="en")
    assert block                                          # 只有影响记录也必须出块
    assert "Market Cross-Check" in block
    assert "F2" in block and "m-opt" in block
    assert "55%" in block and "30%" in block              # prior → revised 可见
    assert "12%" in block                                 # 修订时市场价（0.125 → :.0f → 12%）
    assert "restored" in block.lower()                    # 移除+恢复情形明确可见


def test_render_market_comparison_block_surfaces_influences_zh():
    forecast = {
        "binary_forecasts": [{
            "id": "F1", "statement": "X", "probability": 0.35,
            "market_influence": {
                "market_id": "m-1", "market_question": "Q1",
                "price_at_revision": 0.55, "prior_probability": 0.20,
                "revised_probability": 0.35, "match_confidence": 0.9,
                "resolution_equivalence": "near",
            },
        }],
    }
    block = render_market_comparison_block(forecast, markets=None, lang="zh")
    assert "市场交叉核对" in block
    assert "市场影响" in block and "F1" in block
    assert "20%" in block and "35%" in block


def test_render_market_comparison_block_unchanged_without_influences():
    assert render_market_comparison_block({"binary_forecasts": []}, None, "en") == ""


# --------------------------- end-to-end: extraction chain stamps + surfaces influence
def test_extract_binary_forecasts_stamps_influence_end_to_end(monkeypatch):
    """场景验证：抽取 → 高置信锚定 → 分歧重述移动概率 → 输出负载同时带
    market_influence 印章与 market_comparison.influences 审计面。"""
    from app.services.forecast_extractor import extract_binary_forecasts
    # TIME-3: pin the endDate clock so the 2028-12-31 market never ages out of anchoring.
    monkeypatch.setattr(prediction_markets, "market_clock_now",
                        lambda: datetime(2026, 10, 1, tzinfo=timezone.utc))
    markets = [{"market_id": "mkt-1", "question": "Tariffs > 10%?", "implied_yes_prob": 0.55,
                "url": "https://polymarket.com/event/t", "end_date": "2028-12-31"}]
    fake = FakeLLMClient(json_responses=[
        {"binary_forecasts": [
            {"id": "F1", "statement": "US tariff averages over 10% 2026-2028", "probability": 0.20,
             "resolution_criteria": "USITC > 10% by 2028", "theme": "trade", "horizon_year": 2028,
             "adjustment_rationale": "base rate"},
            {"id": "F2", "statement": "AI capex exceeds $500B in 2027", "probability": 0.80,
             "resolution_criteria": "capex > $500B in 2027", "theme": "ai", "horizon_year": 2027,
             "adjustment_rationale": "trend"},
        ]},
        {"matches": [                                    # 确定性锚定：高置信 exact 匹配
            {"forecast_id": "F1", "market_id": "mkt-1", "resolution_equivalence": "exact",
             "confidence": 0.9}]},
        {"revisions": [                                  # 10pp 分歧重述：向市场移动
            {"id": "F1", "probability": 0.35,
             "adjustment_rationale": "The market implies 55%; I move toward it partially."}]},
    ])
    out = extract_binary_forecasts("dossier", fake, min_count=2, language="English",
                                   market_pack="table", markets=markets)
    f1 = next(b for b in out["binary_forecasts"] if b["id"] == "F1")
    assert f1["probability"] == 0.35
    assert f1["market_influence"]["market_id"] == "mkt-1"
    assert f1["market_influence"]["prior_probability"] == 0.20
    assert f1["market_influence"]["revised_probability"] == 0.35
    mc = out["market_comparison"]
    assert mc["influence_count"] == 1
    assert mc["influences"][0]["forecast_id"] == "F1"
