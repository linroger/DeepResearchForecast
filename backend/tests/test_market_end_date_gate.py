"""TIME-3 — Polymarket endDate hygiene (PREDICTION_MARKETS_END_DATE_GATE).

A market past its endDate can stay open (closed=false) at a near-settled price while it
awaits UMA resolution. Under the gate such a market never anchors a binary forecast and
never seeds SIM priors; it still appears, labelled, in the market pack and the research
section. Every comparison takes an injected clock (market_clock_now / _pm_now), so none of
these tests depends on the wall clock. Offline: no network, no real LLM.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

from app.config import Config
from app.services import forecast_extractor as fe
from app.services.forecast_extractor import extract_binary_forecasts
from app.utils import prediction_markets as pm
from app.utils.prediction_markets import (
    PolymarketClient,
    end_date_gate_settings,
    exclude_window_ended,
    market_window_ended,
    parse_market_end,
    render_markets_block,
    stamp_window_ended,
)
from tests.conftest import FakeLLMClient

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BRIDGE_DIR = os.path.join(_REPO_ROOT, "deerflow_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

import deerflow_research as bridge  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def pinned_clock(monkeypatch):
    """Pin both clocks (backend and bridge) to NOW."""
    monkeypatch.setattr(pm, "market_clock_now", lambda: NOW)
    monkeypatch.setattr(bridge, "_pm_now", lambda: NOW)
    return NOW


@pytest.fixture
def gate(monkeypatch):
    """Set the backend gate knobs on Config; returns a setter for (enabled, grace)."""
    def _set(enabled=True, grace=0.0):
        monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GATE", enabled, raising=False)
        monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GRACE_HOURS", grace,
                            raising=False)
    _set()
    return _set


# ------------------------------------------------------------ parser vector table (parity)
PARSE_VECTORS = [
    ("2026-12-31T00:00:00Z", datetime(2026, 12, 31, 0, 0, tzinfo=UTC)),
    ("2026-12-31T00:00:00.123Z", datetime(2026, 12, 31, 0, 0, 0, 123000, tzinfo=UTC)),
    ("2026-12-31T05:00:00+05:00", datetime(2026, 12, 31, 0, 0, tzinfo=UTC)),
    ("2026-12-31", datetime(2026, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)),
    # A date-only value with a UTC designator is still date-only: end of that day, not
    # midnight at its start (which would count the market as ended almost a day early).
    ("2026-12-31Z", datetime(2026, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)),
    (" 2026-12-31z ", datetime(2026, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)),
    ("2026-02-30Z", None),
    ("2026-12-31T12:30:00", datetime(2026, 12, 31, 12, 30, tzinfo=UTC)),
    ("  2026-12-31T00:00:00z ", datetime(2026, 12, 31, 0, 0, tzinfo=UTC)),
    ("not-a-date", None),
    ("", None),
    ("2026-13-01", None),
    ("2026-02-30", None),
    ("20261231", None),
    ("2026-W01", None),
    ("9999-12-31T23:59:59-05:00", None),
    (None, None),
    (123, None),
    (True, None),
    (["2026-12-31"], None),
]


@pytest.mark.parametrize("value, expected", PARSE_VECTORS)
def test_parse_market_end_vectors_backend_and_bridge_agree(value, expected):
    got_backend = parse_market_end(value)
    got_bridge = bridge._pm_parse_market_end(value)
    assert got_backend == expected
    assert got_bridge == expected
    if expected is not None:
        assert got_backend.tzinfo is not None and got_backend.utcoffset() == timedelta(0)
        assert got_bridge.utcoffset() == timedelta(0)


WINDOW_VECTORS = [
    # (row, grace_hours, expected) at NOW = 2026-10-01T12:00Z
    ({"end_date": "2026-09-30T12:00:00Z"}, 0.0, True),
    ({"end_date": "2026-09-30T12:00:00Z"}, 23.0, True),
    ({"end_date": "2026-09-30T12:00:00Z"}, 24.0, False),    # end + grace == now → not ended
    ({"end_date": "2026-09-30T12:00:00Z"}, 1000.0, False),  # clamped to 168h
    ({"end_date": "2026-09-30T12:00:00Z"}, -5.0, True),     # negative grace → 0
    ({"end_date": "2026-09-30T12:00:00Z"}, float("nan"), True),
    ({"end_date": "2026-09-30T12:00:00Z"}, "junk", True),
    ({"end_date": "2026-10-01"}, 0.0, False),                # date-only = end of that day
    ({"end_date": "2026-09-30"}, 0.0, True),
    ({"end_date": "2026-10-01Z"}, 0.0, False),               # date-only + Z = end of that day
    ({"endDate": "2026-09-01T00:00:00Z"}, 0.0, True),         # raw key fallback
    ({"end_date": "2027-04-19T12:00:00Z"}, 0.0, False),
    ({"end_date": "garbage"}, 0.0, False),                   # unparseable → tolerated
    ({}, 0.0, False),                                        # missing → tolerated
    ("not-a-row", 0.0, False),
]


@pytest.mark.parametrize("row, grace, expected", WINDOW_VECTORS)
def test_market_window_ended_backend_and_bridge_agree(row, grace, expected):
    assert market_window_ended(row, now=NOW, grace_hours=grace) is expected
    assert bridge._pm_market_window_ended(row, NOW, grace) is expected


def test_market_window_ended_reads_naive_now_as_utc():
    row = {"end_date": "2026-09-30T12:00:00Z"}
    naive = datetime(2026, 10, 1, 12, 0)
    assert market_window_ended(row, now=naive) is True
    assert bridge._pm_market_window_ended(row, naive, 0.0) is True
    assert market_window_ended(row, now="2026-10-01") is False  # non-datetime now never raises


def test_end_date_gate_settings_defaults_and_clamp(monkeypatch):
    assert end_date_gate_settings() == (True, 0.0)  # Config defaults: gate on, no grace
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GRACE_HOURS", 500.0, raising=False)
    assert end_date_gate_settings() == (True, 168.0)
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GRACE_HOURS", -3.0, raising=False)
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_END_DATE_GATE", False, raising=False)
    assert end_date_gate_settings() == (False, 0.0)


@pytest.mark.parametrize("raw, expected", [
    (None, 0.0), ("", 0.0), ("6", 6.0), ("6.5", 6.5), ("1000", 168.0), ("-2", 0.0),
    ("nan", 0.0), ("inf", 0.0), ("abc", 0.0),
])
def test_bridge_grace_hours_env_is_finite_and_clamped(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("PREDICTION_MARKETS_END_DATE_GRACE_HOURS", raising=False)
    else:
        monkeypatch.setenv("PREDICTION_MARKETS_END_DATE_GRACE_HOURS", raw)
    assert bridge._pm_end_date_grace_hours() == expected


# ------------------------------------------------------------ stamping / exclusion
def _rows():
    return [
        {"market_id": "A", "question": "Fed cuts 3 times in 2026?", "implied_yes_prob": 0.03,
         "end_date": "2026-09-30T12:00:00Z", "exchange": "polymarket", "volume": 9000.0},
        {"market_id": "B", "question": "Fed cuts 4 times by April 2027?", "implied_yes_prob": 0.62,
         "end_date": "2027-04-19T12:00:00Z", "exchange": "polymarket", "volume": 8000.0},
        {"market_id": "C", "question": "No end date market?", "implied_yes_prob": 0.40,
         "exchange": "polymarket", "volume": 7000.0},
    ]


def test_stamp_window_ended_copies_and_counts():
    rows = _rows()
    stamped, n = stamp_window_ended(rows + ["junk"], now=NOW, grace_hours=0.0)
    assert n == 1
    assert [m["market_id"] for m in stamped] == ["A", "B", "C"]  # never drops dict rows
    assert stamped[0]["window_ended"] is True
    assert stamped[0]["window_ended_at"] == "2026-09-30T12:00:00+00:00"
    assert "window_ended" not in stamped[1] and "window_ended" not in stamped[2]
    assert "window_ended" not in rows[0]  # shallow copies: the input is never mutated
    assert stamped[0] is not rows[0]
    # the bridge stamp helper mirrors it
    b_stamped, b_n = bridge._pm_stamp_window_ended(rows, NOW, 0.0)
    assert b_n == 1 and b_stamped[0]["window_ended_at"] == stamped[0]["window_ended_at"]
    assert "window_ended" not in rows[0]


def test_exclude_window_ended_honours_existing_stamp():
    rows = _rows()
    rows[1]["window_ended"] = True  # stamped upstream (research snapshot) → excluded too
    kept, excluded = exclude_window_ended(rows, now=NOW, grace_hours=0.0)
    assert [m["market_id"] for m in kept] == ["C"]
    assert [m["market_id"] for m in excluded] == ["A", "B"]
    assert kept[0] is rows[2]  # same objects, no copies


# ------------------------------------------------------------ market pack rendering
_PLAIN_TABLE_EN = "\n".join([
    "### Prediction Market Signals (Polymarket)",
    "",
    "| # | Market question | Venue | Implied P(yes) | Volume |",
    "|---|---|---|---|---|",
    "| 1 | Fed cuts 3 times in 2026? (A) | polymarket | 3% | 9,000 |",
    "| 2 | Fed cuts 4 times by April 2027? (B) | polymarket | 62% | 8,000 |",
    "| 3 | No end date market? (C) | polymarket | 40% | 7,000 |",
    "",
    "_Machine-fetched snapshot of active markets; prices move continuously. "
    "Market-implied probabilities are calibration anchors, not ground truth — "
    "mind freshness before relying on them._",
])


def test_render_markets_block_labels_only_window_ended_rows(pinned_clock, gate):
    block = render_markets_block(_rows(), lang="en")
    assert ("| 1 | Fed cuts 3 times in 2026? (A) — window ended 2026-09-30, "
            "awaiting settlement | polymarket | 3% | 9,000 |") in block
    assert "| 2 | Fed cuts 4 times by April 2027? (B) | polymarket | 62% | 8,000 |" in block
    assert block.count("window ended") == 1
    zh = render_markets_block(_rows(), lang="zh")
    assert "(A) — 已过截止日 2026-09-30，待结算 |" in zh
    assert zh.count("已过截止日") == 1


def test_render_markets_block_gate_off_is_byte_identical(pinned_clock, gate):
    gate(enabled=False)
    assert render_markets_block(_rows(), lang="en") == _PLAIN_TABLE_EN
    # rows stamped by a gate-on research snapshot stay unlabelled with the gate off
    stamped, _n = stamp_window_ended(_rows(), now=NOW)
    assert stamped[0]["window_ended"] is True
    assert render_markets_block(stamped, lang="en") == _PLAIN_TABLE_EN
    # gate on but nothing ended yet → the same bytes (unstamped output unchanged)
    gate(enabled=True)
    live = [dict(m, end_date="2027-01-01T00:00:00Z") for m in _rows()]
    assert render_markets_block(live, lang="en") == _PLAIN_TABLE_EN


def test_render_markets_block_link_rows_and_upstream_stamp(pinned_clock, gate):
    rows = _rows()
    rows[0]["url"] = "https://polymarket.com/event/fed-cuts"
    block = render_markets_block(rows, lang="en")
    assert ("[Fed cuts 3 times in 2026?](https://polymarket.com/event/fed-cuts) (A) — window "
            "ended 2026-09-30, awaiting settlement |") in block
    # A stamp without any parseable date still labels the row (no fabricated date).
    odd = [{"market_id": "Z", "question": "Odd?", "implied_yes_prob": 0.5,
            "window_ended": True}]
    assert "(Z) — window ended, awaiting settlement |" in render_markets_block(odd)


def test_report_market_pack_keeps_expired_rows_labelled(pinned_clock, gate):
    """The report's market pack (unchanged caller) still shows the expired market, labelled."""
    from app.services.report_agent import ReportAgent
    agent = ReportAgent.__new__(ReportAgent)
    agent.output_language = "English"
    pack = agent._render_market_pack(_rows())
    assert ("| 1 | Fed cuts 3 times in 2026? (A) — window ended 2026-09-30, "
            "awaiting settlement | polymarket | 3% | 9,000 |") in pack
    gate(enabled=False)
    assert agent._render_market_pack(_rows()).endswith(_PLAIN_TABLE_EN)


# ------------------------------------------------------------ requote (monitor path)
class _FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_requote_markets_unchanged_for_expired_but_open_market(monkeypatch, pinned_clock, gate):
    """resolution_monitor requotes anchored markets through requote_markets: an expired but
    still-open market requotes exactly as before under either gate setting."""
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)
    raw = {"id": "A", "question": "Fed cuts 3 times in 2026?", "closed": False,
           "endDate": "2026-09-30T12:00:00Z",
           "outcomes": '["Yes","No"]', "outcomePrices": '["0.02","0.98"]'}
    monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: _FakeResponse([raw]))
    research_row = {"market_id": "A", "implied_yes_prob": 0.03,
                    "end_date": "2026-09-30T12:00:00Z"}
    expected = [{"market_id": "A", "implied_yes_prob": 0.02, "price_at_research": 0.03,
                 "price_delta": -0.01, "end_date": "2026-09-30T12:00:00Z"}]
    assert PolymarketClient().requote_markets([research_row]) == expected
    gate(enabled=False)
    assert PolymarketClient().requote_markets([research_row]) == expected


# ------------------------------------------------------------ binary extraction
_A = {"market_id": "A", "question": "Will the Fed cut rates 3 times in 2026?",
      "implied_yes_prob": 0.03, "event_title": "Fed rate cuts",
      "end_date": (NOW - timedelta(days=1)).isoformat().replace("+00:00", "Z")}
_B = {"market_id": "B", "question": "Will the Fed cut rates 4 times by April 2027?",
      "implied_yes_prob": 0.62, "event_title": "Fed rate cuts",
      "end_date": (NOW + timedelta(days=200)).isoformat().replace("+00:00", "Z")}

_DRAW = {"binary_forecasts": [
    {"id": "F1", "statement": "The Fed cuts rates three times during 2026.",
     "probability": 0.10, "resolution_criteria": "Three FOMC cuts announced in 2026",
     "theme": "rates", "horizon_year": 2026, "adjustment_rationale": "base rate",
     # a model-transcribed (opt-in) anchor to the expired market must not survive the gate
     "market_anchor": {"market_id": "A", "implied_yes_prob": 0.03}},
    {"id": "F2", "statement": "The Fed cuts rates four times by April 2027.",
     "probability": 0.66, "resolution_criteria": "Four FOMC cuts announced by 2027-04-30",
     "theme": "rates", "horizon_year": 2027, "adjustment_rationale": "futures curve"},
]}
_MATCHES = {"matches": [
    {"forecast_id": "F1", "market_id": "A", "resolution_equivalence": "exact", "confidence": 0.9},
    {"forecast_id": "F2", "market_id": "B", "resolution_equivalence": "exact", "confidence": 0.9},
]}


def _extract(monkeypatch, markets, **kwargs):
    monkeypatch.setattr(Config, "FORECAST_BINARY_CONTRARIAN", False, raising=False)
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_MODELS", "", raising=False)
    fake = FakeLLMClient(json_responses=[_DRAW, _MATCHES])
    out = extract_binary_forecasts("dossier", fake, min_count=2, language="English",
                                   market_pack="table", markets=markets, **kwargs)
    match_prompts = [c["messages"][0]["content"] for c in fake.calls
                     if "[MARKETS]" in c["messages"][0]["content"]]
    by_id = {b["id"]: b for b in out["binary_forecasts"]}
    return out, by_id, match_prompts


def _pre_change_match_prompt(markets):
    """The matcher prompt exactly as it was built before TIME-3 (characterization pin)."""
    flines = [f"[{b['id']}] {b['statement']}" for b in _DRAW["binary_forecasts"]]
    mlines = [f"[{m['market_id']}] {m['question']} "
              f"(implied YES {m['implied_yes_prob'] * 100:.0f}%, ends {m['end_date']})"
              for m in markets]
    return (fe._MARKET_MATCH_INSTRUCTIONS + "\n\nWrite any prose in English."
            + "\n\n[FORECASTS]\n" + "\n".join(flines)
            + "\n\n[MARKETS]\n" + "\n".join(mlines))


def test_extraction_gate_on_never_anchors_expired_ladder_child(monkeypatch, gate):
    out, by_id, prompts = _extract(monkeypatch, [_A, _B], now=NOW)
    assert "market_anchor" not in by_id["F1"]          # neither matcher nor opt-in anchor
    assert by_id["F2"]["market_anchor"]["market_id"] == "B"
    assert out["binary_quality"]["market_window_ended_excluded"] == 1
    assert len(prompts) == 1
    assert "Today (UTC): 2026-10-01." in prompts[0]
    assert prompts[0].startswith(_pre_change_match_prompt([_B]))  # only B is offered
    assert "[A]" not in prompts[0]
    assert out["market_comparison"]["anchored_count"] == 1


def test_extraction_gate_on_defaults_now_to_market_clock(monkeypatch, gate, pinned_clock):
    out, by_id, prompts = _extract(monkeypatch, [_A, _B])  # no explicit now
    assert "Today (UTC): 2026-10-01." in prompts[0]
    assert "market_anchor" not in by_id["F1"]
    assert out["binary_quality"]["market_window_ended_excluded"] == 1


def test_extraction_gate_on_excludes_rows_stamped_upstream(monkeypatch, gate):
    stamped_b = dict(_B, window_ended=True, window_ended_at="2026-09-30T00:00:00+00:00")
    out, by_id, prompts = _extract(monkeypatch, [_A, stamped_b], now=NOW)
    assert prompts == []  # nothing left to anchor → no matcher call
    assert "market_anchor" not in by_id["F1"] and "market_anchor" not in by_id["F2"]
    assert out["binary_quality"]["market_window_ended_excluded"] == 2
    assert "market_comparison" not in out


def test_extraction_gate_on_without_expired_markets_adds_no_count(monkeypatch, gate):
    out, by_id, _prompts = _extract(monkeypatch, [_B], now=NOW)
    assert "market_window_ended_excluded" not in out["binary_quality"]
    assert by_id["F2"]["market_anchor"]["market_id"] == "B"


def test_extraction_gate_off_is_the_pre_change_path(monkeypatch, gate):
    gate(enabled=False)
    out, by_id, prompts = _extract(monkeypatch, [_A, _B], now=NOW)
    assert by_id["F1"]["market_anchor"]["market_id"] == "A"   # both anchors attach
    assert by_id["F2"]["market_anchor"]["market_id"] == "B"
    assert "market_window_ended_excluded" not in out["binary_quality"]
    assert len(prompts) == 1
    assert "Today (UTC)" not in prompts[0]
    assert prompts[0] == _pre_change_match_prompt([_A, _B])
