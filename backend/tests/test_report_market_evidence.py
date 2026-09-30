"""市场证据集回归 — 「真实市场价被当作 fabrication」事故的两条在库机制（LOOP-017 P0 尾巴）。

历史事故：一个直接相关的 Polymarket 市场价（Tesla Optimus P=0.125）被研究捕获后，
报告侧把真价改写/删除成「捏造数字」。i7 取证钉出两条机制：
1) `_critique_section_draft` 的材料集缺 `self._market_pack` —— 章节撰写提示里注入了
   市场表，质检员却看不到它，于是按规则 2 把无 [S#] 的市场价判为未接地并下修订指令；
2) `_repair_final_quantitative_grounding` → `_quantitative_semantic_decision` 的允许
   证据只有 admissible `self.sources` —— 机器抓取的市场快照永远不在其中，低覆盖率报告
   里未标注的真实市场价被确定性删除。
本套件固定修复语义：市场语境 + 快照价精确命中 ⇒ `market_supported`（保留原句、不发明
[S#]、独立计数）；质检材料含市场表 + 明示市场价为合法机器证据；无市场语境的裸数字仍走
原有 unsupported/unverifiable 判定。
"""

from __future__ import annotations

from app.services.report_agent import ReportAgent, ReportSection


def _agent(**over):
    a = ReportAgent.__new__(ReportAgent)
    a.sources = []
    a.research_report = ""
    a.situation_brief = ""
    a._background_block = ""
    a._outline_summary = ""
    a.output_language = "English"
    for k, v in over.items():
        setattr(a, k, v)
    return a


class _RecLLM:
    """记录每次 chat 调用并按序返回脚本响应（最后一条循环使用）。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages=None, **kw):
        self.calls.append({"messages": messages, **kw})
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


# ------------------------------------------------- 机制 1：反思质检的市场材料
def test_critique_material_includes_market_pack_and_rule():
    llm = _RecLLM(["PASS"])
    a = _agent(llm=llm,
               _market_pack="| Optimus milestone by 2026 | implied YES 12.5% |",
               _signal_pack="")
    sec = ReportSection(title="Body 1", description="")
    out = a._critique_section_draft(sec, "x" * 100, [])
    assert out is None
    sys_p = llm.calls[0]["messages"][0]["content"]
    usr_p = llm.calls[0]["messages"][1]["content"]
    assert "Optimus milestone" in usr_p, "市场表必须进入质检材料"
    assert "预测市场表" in sys_p, "规则须明示市场表数字是合法机器抓取证据"


def test_critique_without_market_pack_says_none(monkeypatch):
    """REPORT_ABSENCE_MARKERS=False pins the legacy '（无）' slot."""
    from app.config import Config

    monkeypatch.setattr(Config, "REPORT_ABSENCE_MARKERS", False, raising=False)
    llm = _RecLLM(["PASS"])
    a = _agent(llm=llm, _market_pack="", _signal_pack="")
    sec = ReportSection(title="Body 1", description="")
    a._critique_section_draft(sec, "x" * 100, [])
    assert "（无）" in llm.calls[0]["messages"][1]["content"]


def test_critique_without_market_pack_marks_absence():
    """REPORT-4 default: a typed marker replaces '（无）' and the rule keeps the [S#] carve-out."""
    llm = _RecLLM(["PASS"])
    a = _agent(llm=llm, _market_pack="", _signal_pack="")
    sec = ReportSection(title="Body 1", description="")
    a._critique_section_draft(sec, "x" * 100, [])
    sys_p = llm.calls[0]["messages"][0]["content"]
    usr_p = llm.calls[0]["messages"][1]["content"]
    assert "（无）" not in usr_p
    assert "【预测市场表】\n（预测市场表：本次运行未启用该步骤——不是空结果" in usr_p
    assert "未带 [S#] 的预测市场价格/隐含概率没有机器证据" in sys_p
    assert "带 [S#] 的研究材料数字不受影响" in sys_p


# --------------------------------------- 机制 2：最终定量接地修复的市场证据
def test_final_grounding_preserves_market_corroborated_price():
    a = _agent(_prediction_markets=[{
        "market_id": "m1",
        "question": "Will Tesla ship the Optimus milestone by 2026?",
        "implied_yes_prob": 0.125,
    }])
    md = ("## Analysis\n"
          "Polymarket implied probability for the Optimus milestone is 12.5%.\n"
          "Total capex reached $42.5B according to unnamed filings.\n")
    out, stats = a._repair_final_quantitative_grounding(md)
    assert "12.5%" in out, "与快照一致的市场价必须保留"
    assert "42.5" not in out, "无来源的普通硬数字仍应删除"
    assert stats["market_claims_preserved"] == 1
    assert stats["sentences_removed"] >= 1


def test_price_without_market_context_still_removed():
    """快照里有 0.125，但句子没有市场语境 → 不豁免（防止裸数字碰巧撞价）。"""
    a = _agent(_prediction_markets=[{
        "market_id": "m1", "question": "q", "implied_yes_prob": 0.125,
    }])
    md = "## Analysis\nFleet adoption reached 12.5% across operators.\n"
    out, stats = a._repair_final_quantitative_grounding(md)
    assert "12.5" not in out
    assert stats["market_claims_preserved"] == 0


def test_decision_market_supported_status_and_miss():
    a = _agent(_prediction_markets=[{
        "market_id": "m", "question": "q",
        "implied_yes_prob": 0.34, "price_at_research": 0.31,
    }])
    # 现价命中
    tag, status = a._quantitative_semantic_decision(
        "The Polymarket market currently prices this outcome at 34%.")
    assert (tag, status) == ("", "market_supported")
    # 研究期价命中（price_at_research 也是快照证据）
    tag2, status2 = a._quantitative_semantic_decision(
        "At research time the prediction market implied 31%.")
    assert (tag2, status2) == ("", "market_supported")
    # 市场语境但数字不在快照 → 不豁免
    _tag3, status3 = a._quantitative_semantic_decision(
        "The market prices this outcome at 55%.")
    assert status3 in ("unsupported", "unverifiable")


def test_decision_spine_market_anchor_counts_as_snapshot():
    """market_comparison / market_anchor 里的价（快照同源）同样可豁免。"""
    a = _agent(
        _prediction_markets=None,
        _forecast_spine={
            "binary_forecasts": [{
                "id": "F1", "statement": "s", "probability": 0.2,
                "market_anchor": {"market_id": "m1", "implied_yes_prob": 0.125},
            }],
        },
    )
    tag, status = a._quantitative_semantic_decision(
        "The matched Polymarket market implies 12.5% for this proposition.")
    assert (tag, status) == ("", "market_supported")
