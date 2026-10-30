"""Collector status reaches health/brief without inventing a price timestamp."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.services import exec_brief
from app.services.forecast_inputs_health import build_inputs_health
from deerflow_bridge import deerflow_research as collector

pytestmark = pytest.mark.guarded_runner
NOW = "2026-10-28T05:00:00+00:00"


@pytest.fixture
def collect(tmp_path, monkeypatch):
    monkeypatch.setenv("PREDICTION_MARKETS_CACHE", "off")
    monkeypatch.setenv("PREDICTION_MARKETS_HORIZON_RETRY", "false")
    monkeypatch.setattr(collector, "_utcnow", lambda: NOW)
    monkeypatch.setattr(collector, "_pm_backtest_policy", lambda: None)
    monkeypatch.setattr(collector, "_PM_TRANSPORT_UNAVAILABLE", False)
    monkeypatch.setattr(collector, "_pm_resolve_queries", lambda *args: ["spending 2027"])

    def run(state):
        monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "false" if state == "disabled" else "true")
        if state == "partial_failure":
            monkeypatch.setattr(collector, "_pm_resolve_queries", lambda *args: ["spending 2027", "capacity 2027"])

        def snapshot(queries, **kwargs):
            failed = state == "offline"
            kwargs["diagnostics"].update(attempted_query_count=len(queries), successful_query_count=0 if failed else 1,
                                         transport_failure_count=1 if failed or state == "partial_failure" else 0)
            return []

        monkeypatch.setattr(collector, "_pm_snapshot", snapshot)
        collector._collect_prediction_markets(tmp_path, "Spending in 2027?", "# Research\n", {},
                                             SimpleNamespace(write=lambda *args: None))
        return json.loads((tmp_path / collector.PREDICTION_MARKETS_FILENAME).read_text())

    return run


@pytest.mark.parametrize("state,expected", [("disabled", "disabled"), ("empty", "empty"),
                                            ("offline", "offline"), ("partial_failure", "offline")])
def test_actual_collector_no_price_status_preserves_attempt_time(collect, state, expected):
    payload = collect(state)
    before = deepcopy(payload)
    entry = build_inputs_health(markets=payload, as_of=NOW)["markets"]
    assert entry["status"] == expected
    assert entry["as_of"] is None and entry["rows"] == 0
    assert entry["attempted_at"] == NOW
    assert payload == before
    # The actual brief/card helper consumes exactly this health snapshot.
    summary, detail = exec_brief._inputs_health_display({"inputs_health": {"markets": entry}},
                                                       exec_brief._LABELS["en"])
    assert f"Prediction markets {expected}" in summary
    assert f"**Prediction markets:** {expected}" in detail


def test_native_stale_preserves_original_price_time_and_separate_attempt():
    original = "2026-10-26T05:00:00+00:00"
    payload = {"markets": [{"market_id": "m1"}], "as_of": original,
               "status": {"state": "stale", "attempted_at": NOW}, "cache": {"hit": True}}
    row = build_inputs_health(markets=payload, as_of=NOW)["markets"]
    assert (row["status"], row["as_of"], row["attempted_at"]) == ("stale", original, NOW)


@pytest.mark.parametrize("attempt,reason", [("2999-01-01T00:00:00Z", "future_attempt_time"),
                                            ("not a timestamp", "missing_snapshot_time"),
                                            (None, "missing_snapshot_time")])
def test_empty_requires_admissible_status_time(attempt, reason):
    payload = {"markets": [], "as_of": None,
               "status": {"state": "unavailable", "successful_query_count": 1, "attempted_at": attempt}}
    row = build_inputs_health(markets=payload, as_of=NOW)["markets"]
    assert row["status"] == "unknown" and row["reason"] == reason
    assert row["as_of"] is None and row.get("attempted_at") is None


def test_attempt_time_cannot_freshen_an_undated_price_or_an_unknown_empty_result():
    for rows in ([], [{"market_id": "m1"}]):
        payload = {"markets": rows, "status": {"state": "unavailable", "attempted_at": NOW}}
        row = build_inputs_health(markets=payload, as_of=NOW)["markets"]
        assert row["status"] == "unknown" and row["as_of"] is None


def test_old_successful_empty_check_is_stale_without_price_time():
    payload = {"markets": [], "status": {"successful_query_count": 1,
               "attempted_at": "2026-10-01T05:00:00+00:00"}}
    row = build_inputs_health(markets=payload, as_of=NOW)["markets"]
    assert row["status"] == "stale" and row["as_of"] is None


def test_failure_takes_precedence_over_partial_empty_success():
    payload = {"markets": [], "status": {"successful_query_count": 1,
               "empty_reason": "transport_failure", "attempted_at": NOW}}
    row = build_inputs_health(markets=payload, as_of=NOW)["markets"]
    assert row["status"] == "offline" and row["as_of"] is None
