"""NEXTSTEPS P2-4: forecast ledger (append / read / calibration / due) — offline."""

import json
import os
import threading
import time

from app.services import forecast_ledger
from app.services.forecast_ledger import (
    _year_end,
    append_forecast,
    append_market_resolution,
    calibration_summary,
    due_for_resolution,
    read_ledger,
    read_market_resolutions,
)


def test_append_and_read(tmp_path):
    d = str(tmp_path)
    fc = {"horizon": "2030", "confidence": "high",
          "scenarios": [{"name": "A", "probability": 0.6, "resolution_criteria": "x"},
                        {"name": "B", "probability": 0.4}]}
    e = append_forecast(fc, report_id="r1", created_at="2026-01-01T00:00:00", d=d)
    assert e["report_id"] == "r1" and e["resolution_date"] == "2030-12-31"
    led = read_ledger(d)
    assert len(led) == 1 and led[0]["horizon"] == "2030" and led[0]["resolved"] is False


def test_append_skips_no_scenarios(tmp_path):
    assert append_forecast({"scenarios": []}, report_id="r", d=str(tmp_path)) is None
    assert append_forecast(None, report_id="r", d=str(tmp_path)) is None


def test_calibration_summary_over_resolved(tmp_path):
    d = str(tmp_path)
    append_forecast({"horizon": "2027", "scenarios": [{"name": "A", "probability": 0.7},
                                                      {"name": "B", "probability": 0.3}]},
                    report_id="r1", d=d)
    append_forecast({"horizon": "2027", "scenarios": [{"name": "A", "probability": 0.4},
                                                      {"name": "B", "probability": 0.6}]},
                    report_id="r2", d=d)
    led = read_ledger(d)
    led[0]["resolved"], led[0]["outcome"] = True, "A"
    led[1]["resolved"], led[1]["outcome"] = True, "B"
    with open(os.path.join(d, "ledger.jsonl"), "w", encoding="utf-8") as fh:
        for e in led:
            fh.write(json.dumps(e) + "\n")
    # Legacy arithmetic stays available explicitly; production reads the journal.
    cs = calibration_summary(d, entries=led)
    assert cs["n_resolved"] == 2 and cs["mean_brier"] is not None
    production = calibration_summary(d)
    assert production["n_resolved"] == 0
    assert production["source"] == "published_forecasts.jsonl"


def test_calibration_empty_when_unresolved(tmp_path):
    append_forecast({"scenarios": [{"name": "A", "probability": 1.0}]}, report_id="r", d=str(tmp_path))
    cs = calibration_summary(str(tmp_path))
    assert cs["n_resolved"] == 0 and cs["mean_brier"] is None


def test_due_for_resolution(tmp_path):
    d = str(tmp_path)
    append_forecast({"horizon": "2025", "scenarios": [{"name": "A", "probability": 1.0}]},
                    report_id="past", d=d)
    append_forecast({"horizon": "2099", "scenarios": [{"name": "A", "probability": 1.0}]},
                    report_id="future", d=d)
    due = due_for_resolution("2026-06-01", d=d)
    assert len(due) == 1 and due[0]["report_id"] == "past"


def test_year_end_helper():
    assert _year_end("2030") == "2030-12-31"
    assert _year_end("到2027年底") == "2027-12-31"
    assert _year_end(None) is None


# ----------------- LOOP-017 P1: 市场判定晋升的幂等 + 并发安全（resolutions.jsonl）
def _promote(d, *, resolved_at="2026-08-01T00:00:00Z", fid="F1", mid="m-1"):
    return append_market_resolution(
        report_id="r1", forecast_id=fid, market_id=mid,
        resolved_outcome="Yes", model_p=0.62, market_p_at_research=0.55,
        brier_contribution=round((0.62 - 1.0) ** 2, 4), resolved_at=resolved_at, d=d)


def test_market_resolution_double_promotion_is_noop(tmp_path):
    """同一 (report, forecast, market) 判定重复晋升 = no-op：不产生重复行、
    不覆盖首次入账的 resolved_at 时间戳（钉住证明）。"""
    d = str(tmp_path)
    first = _promote(d, resolved_at="2026-08-01T00:00:00Z")
    assert first is not None and first["resolved_at"] == "2026-08-01T00:00:00Z"
    # 第二次晋升带了不同时间戳——必须被幂等门挡下，绝不改写首行。
    assert _promote(d, resolved_at="2026-08-02T09:00:00Z") is None
    rows = read_market_resolutions(d)
    assert len(rows) == 1
    assert rows[0]["resolved_at"] == "2026-08-01T00:00:00Z"   # 时间戳未被覆盖
    assert rows[0]["brier_contribution"] == first["brier_contribution"]


def test_market_resolution_concurrent_same_key_writes_once(tmp_path, monkeypatch):
    """两线程同时晋升**同一**判定：账本必须恰有一行。

    确定性复现读-查-写竞态：包裹 read_market_resolutions，在读取返回后停留 150ms——
    无锁实现里两线程都会先读到空账本、再各写一行（重复入账污染 Brier）；
    正确实现须把「查重 + 追加」放进同一临界区。"""
    d = str(tmp_path)
    real_read = forecast_ledger.read_market_resolutions

    def slow_read(dd=None):
        rows = real_read(dd)
        time.sleep(0.15)                                  # 拉开读→写窗口，竞态必现
        return rows

    monkeypatch.setattr(forecast_ledger, "read_market_resolutions", slow_read)
    start = threading.Barrier(2)
    results = []

    def worker():
        start.wait(timeout=5)
        results.append(_promote(d))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not any(t.is_alive() for t in threads)
    rows = real_read(d)
    assert len(rows) == 1                                 # 恰一行——无重复入账
    assert sum(1 for r in results if r is not None) == 1  # 恰一个胜者
    assert sum(1 for r in results if r is None) == 1


def test_market_resolution_concurrent_mixed_keys_complete_and_consistent(tmp_path):
    """8 线程并发晋升：各自一条独有判定 + 全体争抢同一共享判定。
    终态账本 = 8 条独有 + 1 条共享，所有行可解析（无交错写坏行）。"""
    d = str(tmp_path)
    start = threading.Barrier(8)

    def worker(i):
        start.wait(timeout=5)
        _promote(d, fid=f"F{i}", mid=f"m-{i}")            # 独有键
        _promote(d, fid="F-shared", mid="m-shared")       # 共享键（7 次应被挡下）

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not any(t.is_alive() for t in threads)
    rows = read_market_resolutions(d)
    keys = [(r["forecast_id"], r["market_id"]) for r in rows]
    assert len(keys) == len(set(keys)) == 9               # 8 独有 + 1 共享，零重复
    # 底层文件逐行可解析（并发追加未产生半行/交错行）。
    raw = open(os.path.join(d, "resolutions.jsonl"), encoding="utf-8").read()
    parsed = [json.loads(line) for line in raw.splitlines() if line.strip()]
    assert len(parsed) == 9
