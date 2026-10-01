"""NEXTSTEPS P2-4: forecast ledger (append / read / calibration / due) — offline."""

import json
import math
import os
import threading
import time
from datetime import datetime, timezone

from app.config import Config
from app.services import forecast_ledger, ledger_commit
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
    cs = calibration_summary(d)
    assert cs["n_resolved"] == 2 and cs["mean_brier"] is not None


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


# ----------------- REPORT-11: objective_signals.probability_shape + shape_summary
def _shape(guard, entropy, max_p, *, delta=None, midband=0.2, extreme=0.0):
    scenarios = {"n": 3, "normalized_entropy": entropy, "max_probability": max_p,
                 "tv_from_uniform": 0.1}
    if delta is not None:
        scenarios["critique_delta"] = {"max_probability": -0.05, "normalized_entropy": delta}
    policy = {} if guard is None else {"binary_symmetric_guard": guard}
    return {"version": "prob-shape/v1", "policy": policy, "scenarios": scenarios,
            "binaries": {"n": 10, "midband_share": midband, "extreme_share": extreme}}


def _commit_row(d, report_id, *, as_of="2026-09-01", signals=None, record_class="production",
                characterization_only=False):
    kwargs = {} if signals is None else {"objective_signals": signals}
    return forecast_ledger.commit_published_forecast(
        {"horizon": "2030", "confidence": "medium",
         "scenarios": [{"name": "A", "probability": 0.6}, {"name": "B", "probability": 0.4}]},
        report_id=report_id, question="Will A happen by 2030?", language="English",
        as_of_date=as_of, as_of_source="validated",
        publication={"forecast_sha256": report_id.ljust(64, "0")},
        record_class=record_class, d=d, committed_at="2026-09-29T12:00:00+00:00",
        characterization_only=characterization_only, **kwargs)


def test_commit_stores_objective_signals_copy(tmp_path):
    d = str(tmp_path)
    signals = {"probability_shape": _shape(False, 0.9, 0.5)}
    status, row = _commit_row(d, "r_sig", signals=signals)
    assert status == "committed" and row["objective_signals"] == signals
    signals["probability_shape"]["policy"]["binary_symmetric_guard"] = True  # caller mutates later
    (stored,) = read_ledger(d)
    assert stored["objective_signals"]["probability_shape"]["policy"] == {
        "binary_symmetric_guard": False}
    # no signals (the default) → the row shape is unchanged
    status, plain = _commit_row(d, "r_plain", as_of="2026-09-02")
    assert status == "committed" and "objective_signals" not in plain
    assert set(plain) == set(row) - {"objective_signals"}
    # non-JSON telemetry never blocks the scored row
    status, nan_row = _commit_row(d, "r_nan", as_of="2026-09-03",
                                  signals={"probability_shape": {"x": float("nan")}})
    assert status == "committed" and "objective_signals" not in nan_row
    assert nan_row["objective_signals_dropped"] is True


def test_commit_report_carries_the_sealed_shape(monkeypatch):
    shape = _shape(True, 0.8, 0.45)

    def commit(report_id, forecast, as_of):
        return ledger_commit.commit_report(
            report_id=report_id, report_status="completed", error=None,
            question="Will A happen by 2030?", language="English", actors=None,
            scenario_label="", ledger_context={"as_of_date": as_of},
            publication_status_fn=lambda rid: {"publishable": True,
                                               "forecast_sha256": report_id.ljust(64, "0")},
            load_forecast_fn=lambda rid: forecast,
            now=datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc))

    base = {"horizon": "2030", "scenarios": [{"name": "A", "probability": 0.6},
                                             {"name": "B", "probability": 0.4}]}
    monkeypatch.setattr(Config, "FORECAST_PROBABILITY_SHAPE", True, raising=False)
    assert commit("r_shape", {**base, "quality": {"probability_shape": shape}},
                  "2026-09-01")["status"] == "committed"
    assert commit("r_bare", dict(base), "2026-09-02")["status"] == "committed"
    monkeypatch.setattr(Config, "FORECAST_PROBABILITY_SHAPE", False, raising=False)
    assert commit("r_off", {**base, "quality": {"probability_shape": shape}},
                  "2026-09-03")["status"] == "committed"
    rows = {r["report_id"]: r for r in read_ledger()}
    assert rows["r_shape"]["objective_signals"] == {"probability_shape": shape}
    assert "objective_signals" not in rows["r_bare"]
    assert "objective_signals" not in rows["r_off"]


def test_shape_summary_groups_by_policy_flag(tmp_path):
    d = str(tmp_path)
    for i, (guard, entropy, max_p, delta) in enumerate(
            ((False, 0.8, 0.5, 0.02), (False, 0.6, 0.7, None), (True, 0.9, 0.4, 0.04))):
        _commit_row(d, f"r{i}", as_of=f"2026-09-0{i + 1}",
                    signals={"probability_shape": _shape(guard, entropy, max_p, delta=delta)})
    _commit_row(d, "r_nopolicy", as_of="2026-08-01",
                signals={"probability_shape": _shape(None, 0.5, 0.8)})
    _commit_row(d, "r_plain", as_of="2026-08-02")                      # no objective_signals
    append_forecast({"horizon": "2030", "scenarios": [{"name": "A", "probability": 1.0}]},
                    report_id="r_legacy", d=d)                         # legacy mode row
    # excluded by default: a revision, an unpublished terminal, golden and evaluation rows
    _commit_row(d, "r_rev", as_of="2026-09-01",
                signals={"probability_shape": _shape(False, 0.1, 0.99)})
    forecast_ledger.record_unpublished_terminal(
        report_id="r_unpub", question_sha256="q", record_class="production", run_ref="p",
        reasons=["x"], d=d)
    extra = [
        {"golden": True, "report_id": "g1", "scenarios": [],
         "objective_signals": {"probability_shape": _shape(False, 0.1, 0.99)}},
        {"record_class": "evaluation", "row_type": "commit", "calibration_role": "primary",
         "report_id": "e1", "characterization_only": True,
         "objective_signals": {"probability_shape": _shape(True, 0.2, 0.9)}},
    ]
    entries = read_ledger(d) + extra
    assert any(r.get("calibration_role") == "revision" for r in entries)

    summary = forecast_ledger.shape_summary(entries=entries)
    assert summary["version"] == "prob-shape-summary/v1"
    assert (summary["n_rows"], summary["n_with_shape"]) == (6, 4)
    by_flag = {g["binary_symmetric_guard"]: g for g in summary["groups"]}
    assert [g["binary_symmetric_guard"] for g in summary["groups"]] == [False, True, None]
    off, on, unknown = by_flag[False], by_flag[True], by_flag[None]
    assert (off["n"], off["n_with_shape"]) == (2, 2)
    assert off["metrics"]["scenarios.normalized_entropy"] == {"n": 2, "mean": 0.7, "median": 0.7}
    assert off["metrics"]["scenarios.max_probability"] == {"n": 2, "mean": 0.6, "median": 0.6}
    assert off["metrics"]["scenarios.critique_delta.normalized_entropy"] == {
        "n": 1, "mean": 0.02, "median": 0.02}
    assert off["metrics"]["binaries.midband_share"]["n"] == 2
    assert off["metrics"]["binaries.extreme_share"] == {"n": 2, "mean": 0.0, "median": 0.0}
    assert (on["n"], on["metrics"]["scenarios.normalized_entropy"]["mean"]) == (1, 0.9)
    # rows without objective_signals (plain + legacy) and a shape without the flag
    assert (unknown["n"], unknown["n_with_shape"]) == (3, 1)
    assert unknown["metrics"]["scenarios.max_probability"] == {
        "n": 1, "mean": 0.8, "median": 0.8}
    json.dumps(summary, allow_nan=False)

    # read from disk: the same selection (the extra rows were never written)
    assert forecast_ledger.shape_summary(d)["n_rows"] == 6

    # the evaluation lane relaxes only the record-class rule
    lane = forecast_ledger.shape_summary(entries=entries, include_evaluation=True)
    assert lane["include_evaluation"] is True and lane["n_rows"] == 8
    lane_flags = {g["binary_symmetric_guard"]: g["n"] for g in lane["groups"]}
    assert lane_flags == {False: 3, True: 2, None: 3}


def test_shape_summary_empty_and_malformed_rows(tmp_path):
    assert forecast_ledger.shape_summary(str(tmp_path)) == {
        "version": "prob-shape-summary/v1", "include_evaluation": False,
        "n_rows": 0, "n_with_shape": 0, "groups": []}
    weird = [None, "row", {"report_id": "x", "objective_signals": "bad"},
             {"report_id": "y", "objective_signals": {"probability_shape": {
                 "policy": {"binary_symmetric_guard": "yes"},
                 "scenarios": {"normalized_entropy": float("nan"), "max_probability": True}}}},
             # a hand-edited row: an int too large for a float is skipped, not fatal
             {"report_id": "z", "objective_signals": {"probability_shape": {
                 "scenarios": {"normalized_entropy": 10 ** 400, "max_probability": -10 ** 400},
                 "binaries": {"midband_share": 10 ** 400}}}}]
    summary = forecast_ledger.shape_summary(entries=weird)
    (group,) = summary["groups"]
    assert group["binary_symmetric_guard"] is None and (group["n"], group["n_with_shape"]) == (3, 2)
    assert all(m == {"n": 0, "mean": None, "median": None} for m in group["metrics"].values())


def test_shape_summary_never_prints_negative_zero():
    # mean -0.0000333 and a -0.0 median round to 0.0, not "-0.0"
    rows = [{"report_id": f"r{i}", "objective_signals": {"probability_shape": {
        "policy": {"binary_symmetric_guard": False},
        "scenarios": {"critique_delta": {"normalized_entropy": delta}}}}}
        for i, delta in enumerate((-0.0001, -0.0, -0.0))]
    summary = forecast_ledger.shape_summary(entries=rows)
    (group,) = summary["groups"]
    metric = group["metrics"]["scenarios.critique_delta.normalized_entropy"]
    assert metric == {"n": 3, "mean": 0.0, "median": 0.0}
    assert math.copysign(1, metric["mean"]) == math.copysign(1, metric["median"]) == 1
    assert "-0.0" not in json.dumps(summary)
