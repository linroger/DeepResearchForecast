"""PM-2 / PM-3 / VIZ-2 报告半侧的离线测试。

覆盖：
  * render_market_comparison_block —— 纯渲染（预测 vs 市场对照表按 |Δ| 降序、>10pp 判定、
    未匹配市场清单、市场链接、双语、market_anchor 回退、空输入降级）；
  * _prepend_binary_forecasts_section —— 紧随 Part-1 二元表插入「### Market Cross-Check」（幂等）；
  * _requote_snapshot / _refresh_market_prices_for_extraction —— handoff-PLUS-refresh 实时重报价
    与 degrade-safe 时效性标注；
  * _available_charts / _build_charts_block —— VIZ-2 图表清单规整与章节可引用块。
全部无网络：预测市场客户端离线化（conftest autouse），需要 client 行为的用例显式打开旗标并 mock httpx。
"""

import json

import httpx
import pytest

from app.config import Config
from app.utils import prediction_markets as pm
from app.services.report_agent import (
    ReportAgent,
    ReportManager,
    render_market_comparison_block,
    _MARKET_XCHECK_MARKERS,
)
from app.services.forecast_extractor import _normalize_binaries


# ---------------------------------------------------------------- fixtures

def _agent(**attrs):
    """__new__ 构造（与既有 report 测试同模式），只挂被测方法所需属性。"""
    a = ReportAgent.__new__(ReportAgent)
    a.output_language = attrs.pop("output_language", "English")
    a._prediction_markets = attrs.pop("_prediction_markets", [])
    a._market_pack = attrs.pop("_market_pack", "")
    a._markets_stale = attrs.pop("_markets_stale", False)
    a.charts_manifest = attrs.pop("charts_manifest", None)
    for k, v in attrs.items():
        setattr(a, k, v)
    return a


class _ReportStub:
    def __init__(self, md):
        self.markdown_content = md


@pytest.fixture
def report_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(ReportManager, "_get_report_folder",
                        classmethod(lambda cls, rid: str(tmp_path)))
    return tmp_path


@pytest.fixture
def enabled(monkeypatch):
    """打开 PREDICTION_MARKETS_ENABLED（覆盖 conftest autouse 关闭）。"""
    monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "true")
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)


class _FakeResp:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self):
        return self._payload


def _fresh(mid, yes):
    """一条 Gamma /markets 行（重报价响应用），字符串价镜像真实 API。"""
    return {"id": mid, "question": f"Q{mid}", "closed": False,
            "outcomes": '["Yes","No"]',
            "outcomePrices": json.dumps([f"{yes:.4f}", f"{1 - yes:.4f}"])}


def test_binary_normalization_drops_circular_market_contract_forecasts():
    rows = _normalize_binaries([
        {"statement": "Polymarket 'AI bubble' contract resolves YES by end-2026.",
         "probability": 0.16, "resolution_criteria": "Polymarket resolves YES by 2026-12-31"},
        {"statement": "NVIDIA revenue exceeds $400B by FY2028.",
         "probability": 0.45, "resolution_criteria": "FY2028 10-K revenue >= $400B"},
    ])
    assert [row["statement"] for row in rows] == ["NVIDIA revenue exceeds $400B by FY2028."]


@pytest.mark.parametrize("statement", [
    "Polymarket probability will rise above 60% by 2027.",
    "The prediction-market price will reach 72c before year-end.",
    "Prediction market odds for recession will fall to 20% by Q4.",
    "The event contract is expected to close at 0.65 in December.",
    "预测市场概率将在年底前升至 60%。",
    "市场合约价格预计降至 0.25。",
    "预测市场将在 2027 年结算为是。",
    "The probability on Polymarket will rise to 60% by year-end.",
    "Polymarket's YES shares reach 60 cents before Q4.",
    "YES shares will trade above 60 cents on Polymarket by 2027.",
    "Polymarket's AI-bubble contract will resolve in the affirmative by 2027.",
    "The event contract will settle against the proposition by year-end.",
    "Prediction-market odds will double by year-end.",
    "到年底，该事件在Polymarket上的概率为60%。",
])
def test_binary_normalization_drops_future_market_quote_forecasts(statement):
    rows = _normalize_binaries([
        {"statement": statement, "probability": 0.6,
         "resolution_criteria": "Observe the quoted market level."},
    ])
    assert rows == []


def test_binary_normalization_drops_circular_resolution_criteria_only():
    rows = _normalize_binaries([
        {"statement": "A recession occurs by 2027.", "probability": 0.3,
         "resolution_criteria": "The Polymarket contract settles YES by 2027-12-31."},
    ])
    assert rows == []


def test_binary_normalization_keeps_real_event_with_current_market_evidence():
    statement = (
        "A recession occurs by 2027; Polymarket currently prices the event at 15%."
    )
    rows = _normalize_binaries([
        {"statement": statement, "probability": 0.3,
         "resolution_criteria": "NBER dates a recession beginning by 2027-12-31."},
    ])
    assert [row["statement"] for row in rows] == [statement]


@pytest.mark.parametrize("statement", [
    "The labor market contracts as energy prices rise above $100 by 2027.",
    "The housing market contracts and home prices fall below 2025 levels.",
    "A recession occurs by 2027; Polymarket currently prices the event at 15%.",
    "A recession occurs by 2027; Polymarket currently prices a recession by 2027 at 15%.",
    "A recession occurs by 2027; Polymarket currently prices the event at 15%, below our forecast of 30%.",
    "A recession occurs by 2027; the market-implied probability is 15%, below our forecast of 30%.",
    "A recession occurs by 2027; Polymarket currently prices it at 15%, while our model will be at 30%.",
    "A recession occurs by 2027; Polymarket currently prices it at 15%, while our model is projected to be at 30%.",
    "衰退将在2027年前发生；Polymarket目前的概率为15%。",
    "衰退将在2027年前发生；Polymarket目前概率为15%，低于我们的预计30%。",
    "衰退将在2027年前发生；Polymarket目前概率为15%，而我们的模型预计为30%。",
])
def test_binary_normalization_keeps_real_outcomes_and_current_market_evidence(statement):
    rows = _normalize_binaries([
        {"statement": statement, "probability": 0.3,
         "resolution_criteria": "Use an external real-world series by 2027-12-31."},
    ])
    assert [row["statement"] for row in rows] == [statement]


# 对照负载（PM-2 抽取器 build_market_comparison 的确定性 schema）。
_MC = {
    "anchored_count": 2,
    "comparisons": [
        {"forecast_id": "F1", "statement": "A resolves yes", "model_probability": 0.75,
         "market_id": "m1", "market_question": "Will A?", "market_implied_yes_prob": 0.50,
         "divergence": 0.25, "exceeds_10pp": True, "rationale_cites_market": False,
         "url": "https://polymarket.com/event/a"},
        {"forecast_id": "F2", "statement": "B resolves yes", "model_probability": 0.52,
         "market_id": "m2", "market_question": "Will B?", "market_implied_yes_prob": 0.48,
         "divergence": 0.04, "exceeds_10pp": False, "rationale_cites_market": True,
         "url": "https://polymarket.com/event/b"},
    ],
}

_SNAPSHOT = [
    {"market_id": "m1", "exchange": "polymarket", "question": "Will A?",
     "implied_yes_prob": 0.50, "volume": 9000, "url": "https://polymarket.com/event/a"},
    {"market_id": "m2", "exchange": "polymarket", "question": "Will B?",
     "implied_yes_prob": 0.48, "volume": 5000, "url": "https://polymarket.com/event/b"},
    {"market_id": "m3", "exchange": "polymarket", "question": "Will C (unmatched)?",
     "implied_yes_prob": 0.30, "volume": 1200, "url": "https://polymarket.com/event/c"},
]


# ---------------------------------------------- render_market_comparison_block

def test_crosscheck_render_sorts_by_abs_divergence_and_flags_verdicts():
    fc = {"binary_forecasts": _MC["comparisons"], "market_comparison": _MC}
    block = render_market_comparison_block(fc, markets=_SNAPSHOT, lang="en")
    assert "### Market Cross-Check" in block
    # 按 |Δ| 降序：F1（|0.25|）在 F2（|0.04|）之前。
    assert block.index("| F1 |") < block.index("| F2 |")
    # Δ 列（分歧，pp，带号）。
    assert "+25pt" in block and "+4pt" in block
    # >10pp 判定：F1 超阈且理由未引用市场 → 需解释；F2 带内 → within band。
    assert "⚠ explain" in block
    assert "within band" in block
    # 市场链接渲染为可点链接。
    assert "[Will A?](https://polymarket.com/event/a)" in block
    # 未匹配市场：m3 出现在清单，m1/m2 不再重复列为未匹配。
    assert "Unmatched markets" in block
    assert "Will C (unmatched)?" in block
    assert "implied P(yes) 30%" in block


def test_crosscheck_render_explained_and_review_verdicts():
    """已引用市场的超阈行 → explained；rationale_cites_market 未知（None）→ review。"""
    comps = [
        {"forecast_id": "F1", "statement": "big gap explained", "model_probability": 0.80,
         "market_id": "m1", "market_question": "Q1", "market_implied_yes_prob": 0.50,
         "divergence": 0.30, "exceeds_10pp": True, "rationale_cites_market": True},
        {"forecast_id": "F2", "statement": "gap unknown citation", "model_probability": 0.70,
         "market_id": "m2", "market_question": "Q2", "market_implied_yes_prob": 0.50,
         "divergence": 0.20, "exceeds_10pp": True, "rationale_cites_market": None},
    ]
    fc = {"market_comparison": {"comparisons": comps}}
    block = render_market_comparison_block(fc, markets=[], lang="en")
    assert "explained" in block
    assert "⚠ review" in block


def test_crosscheck_render_falls_back_to_market_anchor():
    """无 market_comparison 负载时从 binary_forecasts[].market_anchor 现场推导。"""
    fc = {"binary_forecasts": [
        {"id": "F1", "statement": "anchored one", "probability": 0.70,
         "market_anchor": {"market_id": "m1", "question": "Will A?",
                           "implied_yes_prob": 0.50, "divergence": 0.20,
                           "url": "https://polymarket.com/event/a"}},
        {"id": "F2", "statement": "no anchor", "probability": 0.40},  # 无锚 → 不入表
    ]}
    block = render_market_comparison_block(fc, markets=_SNAPSHOT, lang="en")
    assert "### Market Cross-Check" in block
    assert "| F1 |" in block and "| F2 |" not in block
    assert "+20pt" in block
    # 现场推导无法判定理由是否引用市场（None）→ review。
    assert "⚠ review" in block


def test_crosscheck_render_chinese_headers():
    fc = {"market_comparison": _MC}
    block = render_market_comparison_block(fc, markets=_SNAPSHOT, lang="Chinese")
    assert "### 市场交叉核对" in block
    assert "需解释" in block
    assert "未匹配市场" in block
    # 标记与幂等门常量一致。
    assert any(m in block for m in _MARKET_XCHECK_MARKERS)


def test_crosscheck_render_empty_degrades_to_blank():
    assert render_market_comparison_block(None) == ""
    assert render_market_comparison_block({}) == ""
    # 无锚定预测且无快照 → 无表无未匹配 → ""。
    assert render_market_comparison_block(
        {"binary_forecasts": [{"id": "F1", "statement": "x", "probability": 0.4}]},
        markets=[]) == ""


def test_crosscheck_render_only_unmatched_when_no_anchors():
    """无锚定预测但有快照 → 只渲染未匹配市场清单（无对照表）。"""
    block = render_market_comparison_block({}, markets=_SNAPSHOT, lang="en")
    assert "### Market Cross-Check" in block
    assert "Unmatched markets" in block
    assert "Model P" not in block          # 无对照表头


def test_crosscheck_labels_window_ended_unmatched_markets(monkeypatch):
    """FU-5 (TIME-3 open issue): an expired-but-open market in the snapshot is labelled,
    never listed as a live candidate cross-check; open rows and gate-off output are
    unchanged, and the caller's snapshot is not mutated."""
    from datetime import datetime, timezone
    now = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(pm, "market_clock_now", lambda: now)
    snapshot = [
        {"market_id": "m-ended", "question": "Will X happen by August?", "implied_yes_prob": 0.03,
         "volume": 9000, "end_date": "2026-08-31T00:00:00Z"},
        {"market_id": "m-open", "question": "Will Y happen by December?", "implied_yes_prob": 0.4,
         "volume": 100, "end_date": "2026-12-31T00:00:00Z"},
    ]
    before = json.dumps(snapshot, sort_keys=True)
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GATE", True, raising=False)
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GRACE_HOURS", 0.0, raising=False)
    en = render_market_comparison_block({}, markets=snapshot, lang="en")
    zh = render_market_comparison_block({}, markets=snapshot, lang="zh")
    assert "- Will X happen by August? — implied P(yes) 3% — window ended 2026-08-31, awaiting settlement" in en
    assert "- Will Y happen by December? — implied P(yes) 40%\n" in en + "\n"
    assert "已过截止日 2026-08-31，待结算" in zh and zh.count("待结算") == 1
    assert json.dumps(snapshot, sort_keys=True) == before
    # Within the grace period the market is still open.
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GRACE_HOURS", 48.0, raising=False)
    assert "awaiting settlement" not in render_market_comparison_block({}, markets=snapshot, lang="en")
    # The pinned market clock decides expiry, never the wall clock: before the end date the
    # row is open even though the wall clock (after 2026-08-31) would call it ended.
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GRACE_HOURS", 0.0, raising=False)
    monkeypatch.setattr(pm, "market_clock_now", lambda: datetime(2026, 8, 30, tzinfo=timezone.utc))
    assert "awaiting settlement" not in render_market_comparison_block({}, markets=snapshot, lang="en")
    assert "待结算" not in render_market_comparison_block({}, markets=snapshot, lang="zh")
    monkeypatch.setattr(pm, "market_clock_now", lambda: now)
    # Gate off: the pre-FU-5 bytes, even for a row the research snapshot already stamped.
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GATE", False, raising=False)
    stamped = [dict(snapshot[0], window_ended=True, window_ended_at="2026-08-31T00:00:00+00:00"), snapshot[1]]
    off = render_market_comparison_block({}, markets=stamped, lang="en")
    assert off == "\n".join([
        "### Market Cross-Check", "", _LEGACY_CAPTION_EN, "", "",
        "**Unmatched markets (in snapshot, not anchored by any forecast — candidate cross-checks):**",
        "- Will X happen by August? — implied P(yes) 3%",
        "- Will Y happen by December? — implied P(yes) 40%",
    ])
    assert off == render_market_comparison_block({}, markets=snapshot, lang="en")
    off_zh = render_market_comparison_block({}, markets=stamped, lang="zh")
    assert off_zh == "\n".join([
        "### 市场交叉核对", "", _LEGACY_CAPTION_ZH, "", "",
        "**未匹配市场（快照中未被任何预测锚定，可补充对照）：**",
        "- Will X happen by August? — 隐含 P(yes) 3%",
        "- Will Y happen by December? — 隐含 P(yes) 40%",
    ])


def test_crosscheck_labels_window_ended_matched_rows(monkeypatch):
    """FU-5 review round 1: TIME-3 keeps window-ended markets out of anchoring when the
    binaries are extracted, but the cross-check is rendered later, so a market open at
    extraction can have ended by render time. Such a matched row is labelled in its Market
    cell (from the comparison row's endDate, the fallback market_anchor's endDate, or the
    snapshot row for the same market when the comparison row has no end date). Open matched
    rows and gate-off rows keep their bytes; the caller's forecast is not mutated."""
    from datetime import datetime, timezone
    extracted_at = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    rendered_at = datetime(2026, 9, 1, 13, tzinfo=timezone.utc)
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GATE", True, raising=False)
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GRACE_HOURS", 0.0, raising=False)
    monkeypatch.setattr(pm, "market_clock_now", lambda: rendered_at)
    comps = [
        {"forecast_id": "F1", "statement": "Z happens", "model_probability": 0.30,
         "market_id": "m-z", "market_question": "Will Z by Sep 1?", "market_implied_yes_prob": 0.04,
         "divergence": 0.26, "exceeds_10pp": True, "rationale_cites_market": False,
         "url": "https://polymarket.com/event/z", "endDate": "2026-09-01T12:30:00Z"},
        {"forecast_id": "F2", "statement": "W happens", "model_probability": 0.50,
         "market_id": "m-w", "market_question": "Will W by December?", "market_implied_yes_prob": 0.48,
         "divergence": 0.02, "exceeds_10pp": False, "rationale_cites_market": False,
         "url": "https://polymarket.com/event/w", "endDate": "2026-12-31T00:00:00Z"},
    ]
    fc = {"market_comparison": {"comparisons": comps}}
    before = json.dumps(fc, sort_keys=True)
    row_z = "| F1 | Z happens | 30% | 4% | +26pt | ⚠ explain | [Will Z by Sep 1?](https://polymarket.com/event/z)"
    row_w = ("| F2 | W happens | 50% | 48% | +2pt | within band | "
             "[Will W by December?](https://polymarket.com/event/w) |")
    en = render_market_comparison_block(fc, markets=[], lang="en")
    zh = render_market_comparison_block(fc, markets=[], lang="zh")
    assert row_z + " — window ended 2026-09-01, awaiting settlement |" in en.split("\n")
    assert row_w in en.split("\n")
    assert ("[Will Z by Sep 1?](https://polymarket.com/event/z) — 已过截止日 2026-09-01，待结算 |"
            in zh and zh.count("待结算") == 1)
    assert json.dumps(fc, sort_keys=True) == before
    # Fallback rows derived from binary_forecasts[].market_anchor carry the anchor's endDate.
    fallback = {"binary_forecasts": [
        {"id": "F1", "statement": "Z happens", "probability": 0.30,
         "market_anchor": {"market_id": "m-z", "question": "Will Z by Sep 1?",
                           "implied_yes_prob": 0.04, "divergence": 0.26,
                           "url": "https://polymarket.com/event/z",
                           "endDate": "2026-09-01T12:30:00Z"}}]}
    assert ("(https://polymarket.com/event/z) — window ended 2026-09-01, awaiting settlement |"
            in render_market_comparison_block(fallback, markets=[], lang="en"))
    # Without an end date on the comparison row the snapshot row for the same market decides,
    # whether it ended at the market clock or the research snapshot already stamped it.
    no_end = {"market_comparison": {"comparisons": [dict(comps[0], endDate=None)]}}
    assert "awaiting settlement" not in render_market_comparison_block(no_end, markets=[], lang="en")
    snap_open_end = [{"market_id": "m-z", "question": "Will Z by Sep 1?", "implied_yes_prob": 0.04,
                      "end_date": "2026-09-01T12:30:00Z"}]
    research_stamped = [{"market_id": "m-z", "question": "Will Z by Sep 1?", "implied_yes_prob": 0.04,
                         "window_ended": True, "window_ended_at": "2026-09-01T12:30:00+00:00"}]
    for snap in (snap_open_end, research_stamped):
        block = render_market_comparison_block(no_end, markets=snap, lang="en")
        assert row_z + " — window ended 2026-09-01, awaiting settlement |" in block.split("\n")
        assert "Unmatched markets" not in block
    # At extraction time the market was still open: the pinned clock decides (the wall clock,
    # after 2026-09-01, would call it ended), and the row keeps its pre-FU-5 bytes.
    monkeypatch.setattr(pm, "market_clock_now", lambda: extracted_at)
    open_en = render_market_comparison_block(fc, markets=[], lang="en")
    assert row_z + " |" in open_en.split("\n") and "awaiting settlement" not in open_en
    # Gate off: byte-identical to the open rendering, even with a research-stamped snapshot row.
    monkeypatch.setattr(pm, "market_clock_now", lambda: rendered_at)
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GATE", False, raising=False)
    off = render_market_comparison_block(fc, markets=research_stamped, lang="en")
    assert off == open_en
    assert row_z + " |" in off.split("\n") and row_w in off.split("\n")
    off_zh = render_market_comparison_block(fc, markets=research_stamped, lang="zh")
    assert "待结算" not in off_zh
    assert ("| F1 | Z happens | 30% | 4% | +26pt | ⚠ 需解释 | "
            "[Will Z by Sep 1?](https://polymarket.com/event/z) |") in off_zh.split("\n")


def test_crosscheck_now_pins_the_stamp_instant_and_restamp_off_keeps_only_saved_stamps(monkeypatch):
    """FU-5 review round 2: an injected ``now`` decides expiry instead of market_clock_now()
    (omitted, the live path renders exactly as before); ``restamp=False`` consults no clock
    at all and labels only rows whose window_ended stamp was saved with the artifacts."""
    from datetime import datetime, timezone
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GATE", True, raising=False)
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GRACE_HOURS", 0.0, raising=False)
    snapshot = [
        {"market_id": "m-ended", "question": "Will X by August?", "implied_yes_prob": 0.03,
         "volume": 900, "end_date": "2026-08-31T00:00:00Z"},
        {"market_id": "m-saved", "question": "Will S by July?", "implied_yes_prob": 0.02,
         "volume": 500, "end_date": "2026-07-15T00:00:00Z",
         "window_ended": True, "window_ended_at": "2026-07-15T00:00:00+00:00"},
        {"market_id": "m-open", "question": "Will Y by December?", "implied_yes_prob": 0.4,
         "volume": 100, "end_date": "2026-12-31T00:00:00Z"},
    ]
    comps = [
        {"forecast_id": "F1", "statement": "Z happens", "model_probability": 0.30,
         "market_id": "m-z", "market_question": "Will Z by Sep 1?", "market_implied_yes_prob": 0.04,
         "divergence": 0.26, "exceeds_10pp": True, "rationale_cites_market": False,
         "url": "https://polymarket.com/event/z", "endDate": "2026-09-01T12:30:00Z"},
        {"forecast_id": "F2", "statement": "Q happens", "model_probability": 0.20,
         "market_id": "m-q", "market_question": "Will Q by June?", "market_implied_yes_prob": 0.05,
         "divergence": 0.15, "exceeds_10pp": True, "rationale_cites_market": True,
         "url": "https://polymarket.com/event/q", "endDate": "2026-06-30T00:00:00Z"},
    ]
    # The research snapshot saved a stamp for the matched market m-q.
    snap = snapshot + [{"market_id": "m-q", "question": "Will Q by June?", "implied_yes_prob": 0.05,
                        "end_date": "2026-06-30T00:00:00Z", "window_ended": True,
                        "window_ended_at": "2026-06-30T00:00:00+00:00"}]
    fc = {"market_comparison": {"comparisons": comps}}
    before = json.dumps([fc, snap], sort_keys=True)
    report_time = datetime(2026, 9, 2, tzinfo=timezone.utc)
    ended_x = "- Will X by August? — implied P(yes) 3% — window ended 2026-08-31, awaiting settlement"
    saved_s = "- Will S by July? — implied P(yes) 2% — window ended 2026-07-15, awaiting settlement"
    open_y = "- Will Y by December? — implied P(yes) 40%"
    row_z = "| F1 | Z happens | 30% | 4% | +26pt | ⚠ explain | [Will Z by Sep 1?](https://polymarket.com/event/z)"
    row_q = "| F2 | Q happens | 20% | 5% | +15pt | explained | [Will Q by June?](https://polymarket.com/event/q)"

    # Omitted ``now`` reads market_clock_now(); an explicit ``now`` gives the same bytes and
    # outranks a market clock that disagrees.
    monkeypatch.setattr(pm, "market_clock_now", lambda: report_time)
    live = render_market_comparison_block(fc, markets=snap, lang="en")
    monkeypatch.setattr(pm, "market_clock_now", lambda: datetime(2100, 1, 1, tzinfo=timezone.utc))
    assert render_market_comparison_block(fc, markets=snap, lang="en", now=report_time) == live
    lines = live.split("\n")
    assert {ended_x, saved_s, open_y} <= set(lines)
    assert row_z + " — window ended 2026-09-01, awaiting settlement |" in lines
    assert row_q + " — window ended 2026-06-30, awaiting settlement |" in lines
    before_end = render_market_comparison_block(
        fc, markets=snap, lang="en", now=datetime(2026, 8, 1, tzinfo=timezone.utc))
    assert ("- Will X by August? — implied P(yes) 3%" in before_end.split("\n")
            and row_z + " |" in before_end.split("\n") and saved_s in before_end.split("\n"))

    # restamp=False: no clock is read; only saved stamps label (the unmatched m-saved row and,
    # through the snapshot, the matched m-q row whose own endDate cannot be judged without a
    # clock). m-ended and m-z ended at any plausible clock but carry no saved stamp.
    def _no_clock():
        raise AssertionError("restamp=False must not read the market clock")
    monkeypatch.setattr(pm, "market_clock_now", _no_clock)
    kept = render_market_comparison_block(fc, markets=snap, lang="en", restamp=False)
    assert kept == render_market_comparison_block(
        fc, markets=snap, lang="en", restamp=False, now=datetime(2100, 1, 1, tzinfo=timezone.utc))
    kept_lines = kept.split("\n")
    assert saved_s in kept_lines and open_y in kept_lines
    assert "- Will X by August? — implied P(yes) 3%" in kept_lines
    assert row_z + " |" in kept_lines
    assert row_q + " — window ended 2026-06-30, awaiting settlement |" in kept_lines
    kept_zh = render_market_comparison_block(fc, markets=snap, lang="zh", restamp=False)
    assert kept_zh.count("待结算") == 2 and "已过截止日 2026-07-15，待结算" in kept_zh
    assert json.dumps([fc, snap], sort_keys=True) == before

    # Gate off: neither keyword changes a byte.
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GATE", False, raising=False)
    off = render_market_comparison_block(fc, markets=snap, lang="en")
    assert "awaiting settlement" not in off
    assert render_market_comparison_block(fc, markets=snap, lang="en", now=report_time) == off
    assert render_market_comparison_block(fc, markets=snap, lang="en", restamp=False) == off


def test_crosscheck_window_ended_label_replaces_the_placeholder_market_cell(monkeypatch):
    """FU-5 review round 2: a matched row with neither a market question nor a URL shows
    "—"; once it is labelled the cell carries the market id (or only the label when there is
    blank id), never "— — window ended …". Unlabelled placeholder cells keep their bytes."""
    from datetime import datetime, timezone
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GATE", True, raising=False)
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GRACE_HOURS", 0.0, raising=False)
    monkeypatch.setattr(pm, "market_clock_now", lambda: datetime(2026, 9, 2, tzinfo=timezone.utc))
    base = {"statement": "Z happens", "model_probability": 0.30, "market_implied_yes_prob": 0.04,
            "divergence": 0.26, "exceeds_10pp": True, "rationale_cites_market": False}
    comps = [
        dict(base, forecast_id="F1", market_id="m-z|1", endDate="2026-09-01T12:30:00Z"),
        dict(base, forecast_id="F2", market_id="  ", url="https://polymarket.com/event/n",
             endDate="2026-09-01T12:30:00Z"),
        dict(base, forecast_id="F3", market_id="m-open", endDate="2026-12-31T00:00:00Z"),
        dict(base, forecast_id="F4", market_id="m-q", market_question="Will Q?",
             endDate="2026-09-01T12:30:00Z"),
    ]
    fc = {"market_comparison": {"comparisons": comps}}
    prefix = "| {} | Z happens | 30% | 4% | +26pt | ⚠ explain | "
    en = render_market_comparison_block(fc, markets=[], lang="en").split("\n")
    assert prefix.format("F1") + "m-z／1 — window ended 2026-09-01, awaiting settlement |" in en
    assert prefix.format("F2") + "window ended 2026-09-01, awaiting settlement |" in en
    assert prefix.format("F3") + "— |" in en
    assert prefix.format("F4") + "Will Q? — window ended 2026-09-01, awaiting settlement |" in en
    zh = render_market_comparison_block(fc, markets=[], lang="zh")
    assert "| m-z／1 — 已过截止日 2026-09-01，待结算 |" in zh
    assert "| ⚠ 需解释 | 已过截止日 2026-09-01，待结算 |" in zh
    assert "— —" not in "\n".join(en) and "— —" not in zh
    # The label strings are TIME-3's, imported under their public names.
    assert pm.window_ended_label(
        {"window_ended": True, "window_ended_at": "2026-09-01T12:30:00+00:00"}, False) == (
        " — window ended 2026-09-01, awaiting settlement")
    assert pm.row_market_end({"endDate": "2026-09-01T12:30:00Z"}) == datetime(
        2026, 9, 1, 12, 30, tzinfo=timezone.utc)


# ---------------------------------- _prepend_binary_forecasts_section (PM-2)

_H1_MD = "# Grand Forecast\n\n> Executive summary\n\n## Section A\n\nBody.\n"


def test_prepend_inserts_crosscheck_after_binary_table(report_folder):
    a = _agent(_forecast_spine={"binary_forecasts": _MC["comparisons"],
                                "market_comparison": _MC},
               _prediction_markets=_SNAPSHOT)
    rep = _ReportStub(_H1_MD)
    a._prepend_binary_forecasts_section("rid-1", rep)
    md = rep.markdown_content
    i_p1 = md.find("## Part 1 — Binary Forecasts")
    i_xc = md.find("### Market Cross-Check")
    i_sa = md.find("## Section A")
    assert -1 < i_p1 < i_xc < i_sa            # 交叉核对夹在二元表与详细章节之间
    # full_report.md 同步重写。
    assert (report_folder / "full_report.md").read_text(encoding="utf-8") == md


def test_prepend_crosscheck_is_idempotent(report_folder):
    a = _agent(_forecast_spine={"binary_forecasts": _MC["comparisons"],
                                "market_comparison": _MC},
               _prediction_markets=_SNAPSHOT)
    rep = _ReportStub(_H1_MD)
    a._prepend_binary_forecasts_section("rid-1", rep)
    once = rep.markdown_content
    a._prepend_binary_forecasts_section("rid-1", rep)   # 重入
    assert rep.markdown_content == once                  # 幂等：不二次插入
    assert once.count("### Market Cross-Check") == 1


# ----------------------------------- REPORT-10: anchoring disclosure in the caption

_DISCLOSURE_ZH = "预测在起草时已参考上述市场价格，故 Δ 是锚定之后的差值，并非独立于市场的估计。"
_DISCLOSURE_EN = ("Forecasts were drafted with these market prices in view, so Δ is measured "
                  "after anchoring, not against a market-independent estimate.")
_LEGACY_CAPTION_ZH = ("_预测概率与真实预测市场隐含概率的确定性对照。市场是校准锚点，非真值；"
                      "分歧超 10 个百分点且理由未引用市场者标注「需解释」。_")
_LEGACY_CAPTION_EN = ("_Deterministic cross-check of forecast probabilities against live "
                      "prediction-market implied probabilities. Markets are calibration anchors, "
                      "not ground truth; divergences over 10 percentage points whose rationale "
                      "does not cite the market are flagged for explanation._")


@pytest.mark.parametrize("lang, legacy, disclosure", [
    ("zh", _LEGACY_CAPTION_ZH, _DISCLOSURE_ZH),
    ("en", _LEGACY_CAPTION_EN, _DISCLOSURE_EN),
])
def test_crosscheck_disclose_anchoring_appends_caption_sentence(lang, legacy, disclosure):
    fc = {"market_comparison": _MC}
    default = render_market_comparison_block(fc, markets=_SNAPSHOT, lang=lang)
    disclosed = render_market_comparison_block(fc, markets=_SNAPSHOT, lang=lang,
                                               disclose_anchoring=True)
    # default call byte-identical to the pre-REPORT-10 caption; kwarg False == default
    assert default.split("\n")[2] == legacy
    assert render_market_comparison_block(fc, markets=_SNAPSHOT, lang=lang,
                                          disclose_anchoring=False) == default
    assert disclosure not in default
    # the disclosure joins the italic intro caption; nothing else changes
    sep = "" if lang == "zh" else " "
    assert disclosed.split("\n")[2] == legacy[:-1] + sep + disclosure + "_"
    assert disclosed.replace(sep + disclosure, "", 1) == default


@pytest.mark.parametrize("knob", [True, False])
def test_prepend_crosscheck_discloses_per_knob(report_folder, monkeypatch, knob):
    monkeypatch.setattr(Config, "REPORT_MARKET_XCHECK_DISCLOSURE", knob, raising=False)
    a = _agent(_forecast_spine={"binary_forecasts": _MC["comparisons"],
                                "market_comparison": _MC},
               _prediction_markets=_SNAPSHOT)
    rep = _ReportStub(_H1_MD)
    a._prepend_binary_forecasts_section("rid-1", rep)
    assert (_DISCLOSURE_EN in rep.markdown_content) is knob
    assert (_LEGACY_CAPTION_EN in rep.markdown_content) is (not knob)


def test_market_xcheck_disclosure_defaults_on():
    assert Config.REPORT_MARKET_XCHECK_DISCLOSURE is True


# ------------------------------------------------- PM-3: requote snapshot

def test_requote_snapshot_disabled_flag_marks_stale(monkeypatch):
    """PREDICTION_MARKETS_REQUOTE=False → 不发请求、保留研究期价、置 _markets_stale=True。"""
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_REQUOTE", False, raising=False)
    calls = []
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: calls.append(1))
    a = _agent()
    rows = [{"market_id": "m1", "implied_yes_prob": 0.34, "volume": 9000}]
    out = a._requote_snapshot(rows)
    assert out == rows                       # 原样
    assert a._markets_stale is True
    assert calls == []                       # 关闭 → 绝不发请求


def test_requote_snapshot_client_disabled_marks_stale(monkeypatch):
    """PREDICTION_MARKETS_ENABLED=False（conftest 默认）→ client 不可用 → stale，不发请求。"""
    calls = []
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: calls.append(1))
    a = _agent()
    out = a._requote_snapshot([{"market_id": "m1", "implied_yes_prob": 0.34}])
    assert a._markets_stale is True
    assert calls == []
    assert out[0]["implied_yes_prob"] == 0.34


def test_requote_snapshot_merges_fresh_prices(enabled, monkeypatch):
    """启用 + mock httpx → 现价覆盖 implied_yes_prob、保留 price_at_research、算 Δ、非陈旧。"""
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_REQUOTE", True, raising=False)
    monkeypatch.setattr(pm.httpx, "get",
                        lambda *a, **k: _FakeResp([_fresh("m1", 0.41)]))
    a = _agent()
    out = a._requote_snapshot([{"market_id": "m1", "implied_yes_prob": 0.34, "volume": 9000}])
    assert out[0]["implied_yes_prob"] == 0.41
    assert out[0]["price_at_research"] == 0.34
    assert out[0]["price_delta"] == round(0.41 - 0.34, 4)
    assert a._markets_stale is False


def test_requote_snapshot_all_failed_marks_stale(enabled, monkeypatch):
    """全部行重报价失败（网络整体故障）→ 保留旧价并 stale=True，绝不抛。"""
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_REQUOTE", True, raising=False)
    monkeypatch.setattr(pm.httpx, "get",
                        lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")))
    a = _agent()
    out = a._requote_snapshot([{"market_id": "m1", "implied_yes_prob": 0.34}])
    assert out[0]["implied_yes_prob"] == 0.34
    assert a._markets_stale is True


def test_report_market_fallback_is_relevance_scored_fail_closed(
    enabled, monkeypatch, report_folder,
):
    from app.services.pipeline_orchestrator import PipelineManager

    monkeypatch.setattr(PipelineManager, "list_pipelines", classmethod(lambda cls: []))
    monkeypatch.setattr(pm, "derive_market_queries_llm",
                        lambda *_args, **_kwargs: ["AI bubble 2026"])
    candidates = [
        {"market_id": "good", "question": "AI bubble burst in 2026?",
         "implied_yes_prob": 0.15, "volume": 2000},
        {"market_id": "junk", "question": "Celebrity movie market?",
         "implied_yes_prob": 0.60, "volume": 5000},
    ]
    monkeypatch.setattr(pm.PolymarketClient, "snapshot_for_queries",
                        lambda *_args, **_kwargs: candidates)
    monkeypatch.setattr(pm, "score_market_relevance", lambda *_args, **_kwargs: [
        {**candidates[0], "relevance_score": 9.0},
    ])

    class LLM:
        def chat(self, **_kwargs):
            return "[]"

    agent = _agent(simulation_requirement="Will the AI investment boom unwind?")
    agent.llm = LLM()
    agent.actors = {}
    agent._active_report_id = "report_test"
    rows = agent._load_prediction_markets()

    assert [row["market_id"] for row in rows] == ["good"]
    recovered = json.loads((report_folder / "prediction_markets_recovered.json").read_text())
    assert recovered["status"]["candidate_count"] == 2
    assert recovered["status"]["selected_count"] == 1


def test_report_market_fallback_drops_unscored_candidates(enabled, monkeypatch):
    from app.services.pipeline_orchestrator import PipelineManager

    monkeypatch.setattr(PipelineManager, "list_pipelines", classmethod(lambda cls: []))
    monkeypatch.setattr(pm, "derive_market_queries_llm", lambda *_args, **_kwargs: ["broad"])
    candidate = {"market_id": "junk", "question": "Unrelated?",
                 "implied_yes_prob": 0.5, "volume": 9999}
    monkeypatch.setattr(pm.PolymarketClient, "snapshot_for_queries",
                        lambda *_args, **_kwargs: [candidate])
    monkeypatch.setattr(pm, "score_market_relevance",
                        lambda *_args, **_kwargs: [candidate])

    class LLM:
        def chat(self, **_kwargs):
            raise RuntimeError("classifier unavailable")

    agent = _agent(simulation_requirement="Forecast X")
    agent.llm = LLM()
    agent.actors = {}
    assert agent._load_prediction_markets() == []


def test_refresh_market_prices_updates_pack_and_snapshot(enabled, monkeypatch):
    """抽取前刷新：就地更新 _prediction_markets（现价）与 _market_pack（渲染表）。"""
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_REQUOTE", True, raising=False)
    monkeypatch.setattr(pm.httpx, "get",
                        lambda *a, **k: _FakeResp([_fresh("m1", 0.41)]))
    a = _agent(_prediction_markets=[{"market_id": "m1", "exchange": "polymarket",
                                     "question": "Will A?", "implied_yes_prob": 0.34,
                                     "volume": 9000}])
    a._refresh_market_prices_for_extraction()
    assert a._prediction_markets[0]["implied_yes_prob"] == 0.41
    assert a._prediction_markets[0]["price_at_research"] == 0.34
    assert "预测市场信号" in a._market_pack          # 市场包重渲染
    assert "34%→41%" in a._market_pack               # Δ 列反映移动


def test_render_market_pack_stale_note(monkeypatch):
    """_markets_stale=True → 包头附时效性说明；行数上限 20（PM-2）。"""
    a = _agent(_markets_stale=True)
    rows = [{"market_id": f"m{i}", "exchange": "polymarket", "question": f"Q{i}",
             "implied_yes_prob": 0.4, "volume": 1000} for i in range(25)]
    pack = a._render_market_pack(rows)
    assert "实时重报价未生效" in pack
    # 只渲染前 20 行（表体 20 条数据行）。
    assert pack.count("polymarket") == 20


# ------------------------------------------------------ VIZ-2: charts manifest

def test_available_charts_normalizes_entries():
    manifest = [
        {"title": "Fig 1", "caption": "trend", "source_data": "data/fig1.csv"},
        {"title": "", "caption": "", "path": "charts/fig2.png"},   # 仅路径也保留
        {"title": "Interactive", "path": "charts/fig3.html"},
        {"title": "Unsafe", "path": "../secret.png"},
        {"title": "", "caption": "", "source_data": ""},           # 三者全空 → 丢弃
        "not a dict",                                              # 非字典 → 跳过
    ]
    a = _agent(charts_manifest=manifest)
    charts = a._available_charts()
    assert len(charts) == 2
    assert charts[0]["path"] == "charts/fig2.png"
    assert charts[1]["path"] == "charts/fig3.html"


def test_available_charts_tolerates_dict_wrapper_and_missing():
    assert _agent(charts_manifest=None)._available_charts() == []
    assert _agent(charts_manifest="bad")._available_charts() == []
    wrapped = {"charts": [{"title": "T", "caption": "C", "path": "charts/t.png"}]}
    charts = _agent(charts_manifest=wrapped)._available_charts()
    assert charts and charts[0]["title"] == "T"


def test_build_charts_block_references_figures():
    manifest = [
        {"title": "Scenario fan", "caption": "P bands", "path": "charts/fan.png"},
        {"title": "Actor network", "path": "charts/actors.html"},
    ]
    a = _agent(charts_manifest=manifest)
    block = a._build_charts_block()
    assert "Available research figures" in block
    assert "Scenario fan" in block
    assert "![P bands](charts/fan.png)" in block          # 标准 markdown 图片语法
    assert "[interactive](charts/actors.html)" in block
    # 空清单 → 空串（注入自动跳过）。
    assert _agent(charts_manifest=[])._build_charts_block() == ""
