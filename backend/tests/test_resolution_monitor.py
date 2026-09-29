"""MON-1 解析追踪 / 持续预测监测的离线测试。

覆盖：Gamma 判定终态解析（fixture payload，全 mock httpx）、市场判定账本幂等追加、
per-report price_track 追加、指标「需人工判定」检测、Brier 回算、以及 --dry-run 纯净性
（不写任何盘）。全部离线，绝不发真实网络请求。
"""

import json

import httpx
import pytest

from app.utils import prediction_markets as pm
from app.utils.prediction_markets import PolymarketClient, _parse_resolution
from app.services import forecast_ledger as ledger
import scripts.resolution_monitor as mon


# ---------------------------------------------------------------- helpers

class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}",
                                        request=None, response=None)

    def json(self):
        return self._payload


@pytest.fixture
def enabled(monkeypatch):
    from app.config import Config
    monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "true")
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)


def _resolved_raw(mid, yes_price, closed=True, uma="resolved"):
    """一条已判定的 Gamma /markets 行：outcomePrices 收敛到 ~0/1（字符串价，镜像真实 API）。"""
    return {
        "id": mid, "question": f"Will {mid} happen?",
        "outcomes": '["Yes","No"]',
        "outcomePrices": json.dumps([f"{yes_price:.4f}", f"{1 - yes_price:.4f}"]),
        "closed": closed, "active": True, "umaResolutionStatus": uma,
    }


def _anchored_forecast():
    """一份带两个锚定二元预测的 forecast.json（一个会判定 Yes，一个尚未判定）。"""
    return {
        "binary_forecasts": [
            {"id": "F1", "statement": "Event A occurs", "probability": 0.30,
             "horizon_year": 2025, "resolution_criteria": "resolves by 2025-12-31",
             "market_anchor": {"market_id": "mA", "question": "Will A?",
                               "implied_yes_prob": 0.44, "price_at_research": 0.40,
                               "divergence": -0.10}},
            {"id": "F2", "statement": "Event B occurs", "probability": 0.70,
             "horizon_year": 2099,
             "market_anchor": {"market_id": "mB", "question": "Will B?",
                               "implied_yes_prob": 0.55, "price_at_research": 0.55,
                               "divergence": 0.15}},
            # 无锚点、已过期 → 应进「需人工判定」。
            {"id": "F3", "statement": "Event C occurs by 2025-01-01", "probability": 0.5,
             "resolution_criteria": "by 2025-01-01"},
        ]
    }


# ---------------------------------------------------------- resolution parse

def test_parse_resolution_yes_and_no_and_unknown():
    # Yes 胜出（价 ~1）：resolved=True，outcome="Yes"，yes 价 ~1。
    r = _parse_resolution(_resolved_raw("mA", 1.0))
    assert r["resolved"] is True and r["resolved_outcome"] == "Yes"
    assert r["resolved_yes_price"] == 1.0 and r["uma_status"] == "resolved"
    # No 胜出（yes 价 ~0）：resolved=True，outcome="No"，yes 价 ~0。
    r2 = _parse_resolution(_resolved_raw("mB", 0.0))
    assert r2["resolved"] is True and r2["resolved_outcome"] == "No"
    assert r2["resolved_yes_price"] == 0.0
    # 未关闭 / 价未收敛 → unknown（resolved=False，但 closed 透传）。
    r3 = _parse_resolution({"id": "mC", "closed": False,
                            "outcomes": '["Yes","No"]', "outcomePrices": '["0.5","0.5"]'})
    assert r3["resolved"] is False and r3["resolved_outcome"] is None
    assert r3["closed"] is False
    # 已关闭但价仍中段（争议中）→ 仍 unknown（不硬造标签）。
    r4 = _parse_resolution({"id": "mD", "closed": True,
                            "outcomes": '["Yes","No"]', "outcomePrices": '["0.6","0.4"]'})
    assert r4["closed"] is True and r4["resolved"] is False
    # 非 dict → None。
    assert _parse_resolution("nope") is None


def test_fetch_resolutions_batches_and_degrades(enabled, monkeypatch):
    seen = {}

    def fake_get(url, params=None, timeout=None, headers=None):
        seen.update(url=url, params=params)
        return FakeResponse([_resolved_raw("mA", 1.0), _resolved_raw("mB", 0.0)])

    monkeypatch.setattr(pm.httpx, "get", fake_get)
    out = PolymarketClient().fetch_resolutions(["mA", "mB", "mA"])  # 去重
    assert seen["url"].endswith("/markets")
    assert seen["params"] == {"id": ["mA", "mB"], "limit": 2}  # EVAL-2: explicit page size
    assert out["mA"]["resolved_outcome"] == "Yes"
    assert out["mB"]["resolved_outcome"] == "No"

    # 网络失败 → {}（degrade-safe）。
    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(pm.httpx, "get", boom)
    assert PolymarketClient().fetch_resolutions(["mA"]) == {}


def test_fetch_resolutions_disabled_makes_no_call(monkeypatch):
    calls = []
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: calls.append(1))
    # conftest 默认关闭 PREDICTION_MARKETS_ENABLED。
    assert PolymarketClient().fetch_resolutions(["mA"]) == {}
    assert PolymarketClient().fetch_resolutions([]) == {}
    assert calls == []


# ------------------------------------------------------- ledger idempotency

def test_append_market_resolution_idempotent(tmp_path):
    d = str(tmp_path)
    e1 = ledger.append_market_resolution(
        report_id="r1", forecast_id="F1", market_id="mA", resolved_outcome="Yes",
        model_p=0.30, market_p_at_research=0.40, brier_contribution=0.49,
        resolved_at="2026-01-01T00:00:00", resolved_yes_price=1.0, d=d)
    assert e1 is not None
    # 同 (report, forecast, market) 再记 → None，不重复入账。
    e2 = ledger.append_market_resolution(
        report_id="r1", forecast_id="F1", market_id="mA", resolved_outcome="Yes",
        model_p=0.30, market_p_at_research=0.40, brier_contribution=0.49,
        resolved_at="2026-02-02T00:00:00", resolved_yes_price=1.0, d=d)
    assert e2 is None
    recs = ledger.read_market_resolutions(d)
    assert len(recs) == 1 and recs[0]["forecast_id"] == "F1"
    # 缺 id → None。
    assert ledger.append_market_resolution(
        report_id="", forecast_id="F", market_id="m", resolved_outcome=None,
        model_p=None, market_p_at_research=None, brier_contribution=None,
        resolved_at="t", d=d) is None
    # 不同市场 → 入账。
    assert ledger.append_market_resolution(
        report_id="r1", forecast_id="F2", market_id="mB", resolved_outcome="No",
        model_p=0.70, market_p_at_research=0.55, brier_contribution=0.49,
        resolved_at="2026-01-01T00:00:00", resolved_yes_price=0.0, d=d) is not None
    assert len(ledger.read_market_resolutions(d)) == 2


def test_market_brier_summary(tmp_path):
    d = str(tmp_path)
    assert ledger.market_brier_summary(d) == {"n_resolved": 0, "mean_brier": None}
    ledger.append_market_resolution(
        report_id="r", forecast_id="F1", market_id="m1", resolved_outcome="Yes",
        model_p=0.3, market_p_at_research=0.4, brier_contribution=0.49,
        resolved_at="t", d=d)
    ledger.append_market_resolution(
        report_id="r", forecast_id="F2", market_id="m2", resolved_outcome="No",
        model_p=0.2, market_p_at_research=0.3, brier_contribution=0.04,
        resolved_at="t", d=d)
    s = ledger.market_brier_summary(d)
    assert s["n_resolved"] == 2 and s["mean_brier"] == round((0.49 + 0.04) / 2, 4)


# --------------------------------------------------------- pure monitor logic

def test_build_resolution_records_brier():
    fc = _anchored_forecast()
    anchored = mon.anchored_forecasts(fc)
    resolutions = {
        "mA": {"market_id": "mA", "resolved": True, "resolved_outcome": "Yes",
               "resolved_yes_price": 1.0},
        "mB": {"market_id": "mB", "resolved": False, "resolved_outcome": None,
               "resolved_yes_price": None},
    }
    recs = mon.build_resolution_records(anchored, resolutions,
                                        report_id="r1", resolved_at="2026-07-07T00:00:00")
    assert len(recs) == 1  # 只有 mA 判定
    r = recs[0]
    assert r["forecast_id"] == "F1" and r["market_id"] == "mA"
    assert r["model_p"] == 0.30 and r["market_p_at_research"] == 0.40
    # y=1（Yes），brier=(0.30-1)^2=0.49。
    assert r["brier_contribution"] == 0.49


def test_detect_needs_manual():
    fc = _anchored_forecast()
    binaries = fc["binary_forecasts"]
    # mA 已判定 → F1 不催；mB 未判定但 horizon 2099 未到期 → F2 不催；
    # F3 无锚点、2025-01-01 已过 → 需人工。
    needs = mon.detect_needs_manual(binaries, resolved_market_ids={"mA"},
                                    as_of="2026-07-07")
    ids = {n["forecast_id"] for n in needs}
    assert ids == {"F3"}
    assert needs[0]["has_anchor"] is False
    # 若 mA 未判定 → F1 也需人工（已过 2025-12-31）。
    needs2 = mon.detect_needs_manual(binaries, resolved_market_ids=set(),
                                     as_of="2026-07-07")
    assert {n["forecast_id"] for n in needs2} == {"F1", "F3"}


def test_compute_movers_sorted_and_thresholded():
    requoted = [
        {"market_id": "m1", "statement": "A", "price_at_research": 0.34,
         "implied_yes_prob": 0.50, "price_delta": 0.16},
        {"market_id": "m2", "statement": "B", "price_at_research": 0.40,
         "implied_yes_prob": 0.42, "price_delta": 0.02},   # < threshold
        {"market_id": "m3", "statement": "C", "price_at_research": 0.60,
         "implied_yes_prob": 0.30, "price_delta": -0.30},
        {"market_id": "m4", "requote_failed": True},         # 失败行跳过
    ]
    movers = mon.compute_movers(requoted, threshold=0.05)
    assert [m["market_id"] for m in movers] == ["m3", "m1"]  # |Δ| 降序
    assert movers[0]["delta"] == -0.30


def test_binary_resolution_date():
    assert mon.binary_resolution_date(
        {"resolution_criteria": "by 2026-11-03"}) == "2026-11-03"
    assert mon.binary_resolution_date({"horizon_year": 2027}) == "2027-12-31"
    assert mon.binary_resolution_date({}) is None


# ---------------------------------------------------------- price track I/O

def test_price_track_append_and_read(tmp_path):
    folder = str(tmp_path)
    snap = {"at": "2026-07-07T00:00:00", "report_id": "r1",
            "markets": [{"market_id": "mA", "implied_yes_prob": 0.5}]}
    assert mon.append_price_snapshot(folder, snap) is True
    mon.append_price_snapshot(folder, {"at": "2026-07-08T00:00:00", "markets": []})
    rows = mon.read_price_track(folder)
    assert len(rows) == 2 and rows[0]["report_id"] == "r1"


# ---------------------------------------------------------- orchestrator

class FakeClient:
    """离线替身：requote 把研究期价搬去现价并算 Δ；fetch_resolutions 返回预置终态。"""

    def __init__(self, resolutions=None, current=None):
        self._resolutions = resolutions or {}
        self._current = current or {}

    def requote_markets(self, rows):
        out = []
        for m in rows:
            m2 = dict(m)
            research = m.get("price_at_research")
            if research is not None:
                m2["price_at_research"] = round(float(research), 4)
            cur = self._current.get(m.get("market_id"))
            if cur is None:
                m2["requote_failed"] = True
            else:
                m2["implied_yes_prob"] = round(cur, 4)
                if research is not None:
                    m2["price_delta"] = round(cur - float(research), 4)
            out.append(m2)
        return out

    def fetch_resolutions(self, ids):
        return {mid: self._resolutions[mid] for mid in ids
                if mid in self._resolutions}


def test_run_monitor_writes_and_scores(tmp_path):
    folder = str(tmp_path / "report")
    led = str(tmp_path / "ledger")
    fc = _anchored_forecast()
    client = FakeClient(
        resolutions={"mA": {"market_id": "mA", "resolved": True,
                            "resolved_outcome": "Yes", "resolved_yes_price": 1.0}},
        current={"mA": 0.62, "mB": 0.55})
    res = mon.run_monitor("r1", forecast=fc, report_folder=folder, client=client,
                          ledger_dir=led, dry_run=False, as_of="2026-07-07T00:00:00",
                          threshold=0.05, publishable_fn=lambda rid: True)
    # mA 判定 → 一条记录入账；mB 现价==研究期价（无 Δ）→ 非 mover；
    # mA 研究期 0.40 → 现 0.62 = +0.22 → mover。
    assert res["resolved_count"] == 1 and res["newly_recorded_count"] == 1
    assert [m["market_id"] for m in res["movers"]] == ["mA"]
    # F3 无锚点、已过期 → 需人工。
    assert res["needs_manual_count"] == 1
    # 落盘：price_track / monitor_report.md / 账本各就位。
    assert len(mon.read_price_track(folder)) == 1
    assert res["monitor_report_path"] and res["monitor_report_path"].endswith("monitor_report.md")
    assert ledger.market_brier_summary(led)["n_resolved"] == 1
    # 二次运行幂等：账本不重复入账。
    res2 = mon.run_monitor("r1", forecast=fc, report_folder=folder, client=client,
                           ledger_dir=led, dry_run=False, as_of="2026-07-08T00:00:00",
                           publishable_fn=lambda rid: True)
    assert res2["newly_recorded_count"] == 0
    assert ledger.market_brier_summary(led)["n_resolved"] == 1


def test_run_monitor_dry_run_writes_nothing(tmp_path):
    import os
    folder = str(tmp_path / "report")
    led = str(tmp_path / "ledger")
    fc = _anchored_forecast()
    client = FakeClient(
        resolutions={"mA": {"market_id": "mA", "resolved": True,
                            "resolved_outcome": "Yes", "resolved_yes_price": 1.0}},
        current={"mA": 0.62})
    res = mon.run_monitor("r1", forecast=fc, report_folder=folder, client=client,
                          ledger_dir=led, dry_run=True, as_of="2026-07-07T00:00:00",
                          publishable_fn=lambda rid: True)
    # 仍计算出判定/mover/需人工，但绝不写盘。
    assert res["resolved_count"] == 1 and res["dry_run"] is True
    assert not os.path.exists(mon.price_track_path(folder))
    assert not os.path.exists(os.path.join(folder, "monitor_report.md"))
    assert ledger.read_market_resolutions(led) == []


def test_run_monitor_degrades_when_market_access_fails(tmp_path):
    folder = str(tmp_path / "report")
    led = str(tmp_path / "ledger")
    fc = _anchored_forecast()

    class DownClient:
        def requote_markets(self, rows):
            raise httpx.ConnectError("down")

        def fetch_resolutions(self, ids):
            raise httpx.ConnectError("down")

    res = mon.run_monitor("r1", forecast=fc, report_folder=folder, client=DownClient(),
                          ledger_dir=led, dry_run=True, as_of="2026-07-07T00:00:00",
                          publishable_fn=lambda rid: True)
    assert res["degraded"] is True and res["resolved_count"] == 0
    # 指标检查仍在（不依赖网络）：F3（+可能 F1）需人工。
    assert res["needs_manual_count"] >= 1
