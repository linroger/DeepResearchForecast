"""REPORT-4: typed absence markers (app/utils/absence.py) and the market-status classifier."""

from __future__ import annotations

import dataclasses
import json
import re

import pytest

from app.utils import absence
from app.utils.absence import (
    MARKER_SENTINELS,
    SlotStatus,
    absence_marker,
    market_status,
)

_STATES = (absence.not_run("x_reason"), absence.empty("x_reason"), absence.unavailable("x_reason"))


def test_slot_status_is_frozen_and_serialises():
    st = SlotStatus("empty", "no_equivalent_market", "detail")
    assert st.to_dict() == {"state": "empty", "reason": "no_equivalent_market", "detail": "detail"}
    with pytest.raises(dataclasses.FrozenInstanceError):
        st.state = "present"  # type: ignore[misc]
    assert absence.present("r").state == absence.SLOT_PRESENT
    assert set(absence.SLOT_STATES) == {"present", "not_run", "empty", "unavailable"}


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_three_states_give_distinct_digit_free_markers(lang):
    markers = [absence_marker("slot", st, lang) for st in _STATES]
    assert len(set(markers)) == 3
    for m in markers:
        assert m and not re.search(r"\d", m)
        assert any(s in m for s in MARKER_SENTINELS), m


def test_zh_and_en_markers_differ_and_follow_lang():
    for st in _STATES:
        zh = absence_marker("预测市场表", st, "zh")
        en = absence_marker("market table", st, "English")
        assert zh != en
        assert zh.startswith("（预测市场表：") and en.startswith("(market table: ")
    assert "本次运行未启用该步骤" in absence_marker("信号包", absence.not_run("x"))
    assert "这是检索结果，不代表现实中不存在" in absence_marker("信号包", absence.empty("x"))
    assert "本次运行中不可用" in absence_marker("信号包", absence.unavailable("x"))
    assert "not part of this run" in absence_marker("s", absence.not_run("x"), "en")
    assert "not evidence of absence in the world" in absence_marker("s", absence.empty("x"), "en")
    assert "unavailable in this run" in absence_marker("s", absence.unavailable("x"), "en")


def test_reason_and_label_are_sanitised_to_no_digits():
    m = absence_marker("slot 2", absence.unavailable("HTTP-503 Timeout.v2"), "en")
    assert not re.search(r"\d", m)
    assert "(http_timeout_v)" in m
    assert "(unspecified)" in absence_marker("s", absence.empty("123"), "en")


def test_present_needs_no_marker_and_unknown_state_is_unavailable():
    assert absence_marker("s", absence.present("research_snapshot")) == ""
    weird = absence_marker("s", SlotStatus("bogus", "r"), "en")
    assert weird == absence_marker("s", absence.unavailable("r"), "en")
    assert absence_marker("s", None, "en") == absence_marker("s", absence.unavailable(""), "en")


# ------------------------------------------------------------ market_status classifier
def _st(payload, enabled=True):
    s = market_status(payload, enabled=enabled)
    return s.state, s.reason


def test_market_status_disabled_and_missing_payload():
    assert _st({"markets": [{"market_id": "m"}]}, enabled=False) == (
        "not_run", "prediction_markets_disabled")
    assert _st(None) == ("unavailable", "no_market_snapshot")
    assert _st([{"market_id": "m"}]) == ("unavailable", "no_market_snapshot")


def test_market_status_rows_present():
    assert _st({"markets": [{"market_id": "m"}], "status": {"state": "verified_empty"}}) == (
        "present", "research_snapshot")
    assert _st({"markets": ["junk"], "status": {"state": "verified_empty"}})[0] == "empty"


@pytest.mark.parametrize("state,expected", [
    ("markets_selected", ("present", "markets_selected")),
    ("partial_transport_failure", ("unavailable", "partial_transport_failure")),
    ("inflight_timeout", ("unavailable", "inflight_timeout")),
    ("transport_failure", ("unavailable", "transport_failure")),
    ("verified_empty", ("empty", "verified_empty")),
    ("all_candidates_irrelevant", ("empty", "all_candidates_irrelevant")),
])
def test_market_status_reads_merged_state_first(state, expected):
    # The multi-track merge folds partial outages into empty_reason=no_equivalent_market;
    # status.state carries the real label and must win.
    payload = {"markets": [], "status": {"state": state, "empty_reason": "no_equivalent_market"}}
    assert _st(payload) == expected


def test_market_status_empty_reason_transport_failure():
    payload = {"markets": [], "no_relevant_markets": True,
               "status": {"empty_reason": "transport_failure", "query_count": 0,
                          "successful_query_count": 0, "transport_failure_count": 1}}
    assert _st(payload) == ("unavailable", "transport_failure")


def test_folded_partial_outage_is_unavailable_not_empty():
    payload = {"markets": [], "no_relevant_markets": True,
               "status": {"empty_reason": "no_equivalent_market", "query_count": 3,
                          "successful_query_count": 1, "transport_failure_count": 2}}
    assert _st(payload) == ("unavailable", "partial_transport_failure")
    all_failed = {"markets": [], "status": {"empty_reason": "no_equivalent_market",
                                            "attempted_query_count": 2,
                                            "transport_failure_count": 2}}
    assert _st(all_failed) == ("unavailable", "partial_transport_failure")


@pytest.mark.parametrize("reason", [
    "no_equivalent_market", "all_candidates_irrelevant", "no_derivable_queries"])
def test_market_status_clean_empty_reasons(reason):
    payload = {"markets": [], "no_relevant_markets": True,
               "status": {"empty_reason": reason, "query_count": 3,
                          "successful_query_count": 3, "transport_failure_count": 0}}
    assert _st(payload) == ("empty", reason)


def test_market_status_legacy_marker_and_unknown():
    assert _st({"markets": [], "no_relevant_markets": True}) == ("empty", "no_relevant_markets")
    assert _st({"markets": []}) == ("unavailable", "unknown_status")
    assert _st({"markets": [], "status": "garbled"}) == ("unavailable", "unknown_status")
    bad_counts = {"markets": [], "status": {"empty_reason": "no_equivalent_market",
                                            "transport_failure_count": "n/a"}}
    assert _st(bad_counts) == ("empty", "no_equivalent_market")


@pytest.mark.parametrize("raw_counts", [
    '"transport_failure_count": Infinity, "query_count": 3',
    '"transport_failure_count": NaN, "query_count": 3',
    '"transport_failure_count": 1, "query_count": Infinity, "successful_query_count": 1',
    '"transport_failure_count": 1, "query_count": 3, "successful_query_count": -Infinity',
])
def test_non_finite_counts_never_raise(raw_counts):
    # json.load accepts Infinity / NaN; int(float('inf')) raises OverflowError.
    payload = json.loads('{"markets": [], "status": {"empty_reason": "no_equivalent_market", '
                         + raw_counts + "}}")
    state, reason = _st(payload)
    assert state in absence.SLOT_STATES and reason


def test_infinite_failure_count_reads_as_unreadable_not_as_a_crash():
    payload = json.loads('{"markets": [], "status": {"empty_reason": "no_equivalent_market", '
                         '"transport_failure_count": Infinity, "query_count": 3}}')
    assert _st(payload) == ("empty", "no_equivalent_market")


@pytest.mark.parametrize("counts", [
    {"query_count": None, "attempted_query_count": 3},
    {"attempted_query_count": 3},
])
def test_null_query_count_falls_back_to_attempted(counts):
    ok = {"markets": [], "status": {"empty_reason": "no_equivalent_market",
                                    "successful_query_count": 3,
                                    "transport_failure_count": 0, **counts}}
    assert _st(ok) == ("empty", "no_equivalent_market")
    partial = {"markets": [], "status": {"empty_reason": "no_equivalent_market",
                                         "successful_query_count": 2,
                                         "transport_failure_count": 1, **counts}}
    assert _st(partial) == ("unavailable", "partial_transport_failure")


@pytest.mark.parametrize("counts", [
    {"query_count": None},
    {},
    {"query_count": "n/a"},
])
def test_transport_failure_with_unknown_query_count_is_unavailable(counts):
    # Without a query count nothing proves every query succeeded, so the folded
    # no_equivalent_market label cannot be trusted as a clean empty search.
    payload = {"markets": [], "status": {"empty_reason": "no_equivalent_market",
                                         "successful_query_count": 2,
                                         "transport_failure_count": 1, **counts}}
    assert _st(payload) == ("unavailable", "partial_transport_failure")
