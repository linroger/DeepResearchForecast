"""EVAL-6 — market price-time provenance on anchors (MARKET_ANCHOR_PRICE_TIME).

A requote stamps ``quoted_at`` on every row that received a fresh price, and a later failed
requote keeps it (the retained price is still that quote). Rows from the research handoff
snapshot carry the payload's ``as_of`` as ``snapshot_as_of``; rows from the report-time live
fetch carry the fetch time. ``_build_market_anchor`` turns these into ``price_time`` +
``price_time_basis`` ('requote' | 'snapshot'), and ``resolution_monitor`` carries them into
price_track. Flag off → market rows and forecast.json anchors keep the pre-change shape
byte for byte. Offline: httpx, PipelineManager and the matcher LLM are faked, and the
market clock is pinned.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from app.config import Config
from app.services import forecast_extractor as fe
from app.services.report_agent import ReportAgent, ReportManager
from app.utils import prediction_markets as pm
from app.utils.point_in_time import parse_stamp_strict
from app.utils.prediction_markets import PolymarketClient
from tests.conftest import FakeLLMClient
import scripts.resolution_monitor as rm

UTC = timezone.utc
T1 = datetime(2026, 9, 30, 9, 15, tzinfo=UTC)
T2 = T1 + timedelta(hours=2)
SNAPSHOT_AS_OF = "2026-09-28T06:00:00.123456+00:00"
END = "2026-12-31T00:00:00Z"
_PRICE_TIME_KEYS = ("price_time", "price_time_basis")


# ------------------------------------------------------------------ fixtures & fakes
class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _gamma(mid, yes, closed=False):
    """One Gamma /markets row (string prices, as the live API sends them)."""
    return {"id": mid, "question": f"Will {mid} happen?", "closed": closed,
            "outcomes": '["Yes","No"]',
            "outcomePrices": json.dumps([f"{yes:.4f}", f"{1 - yes:.4f}"])}


@pytest.fixture
def clock(monkeypatch):
    """Pinned market clock; ``clock["now"] = ...`` moves it."""
    state = {"now": T1}
    monkeypatch.setattr(pm, "market_clock_now", lambda: state["now"])
    return state


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "true")
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)
    monkeypatch.setattr(pm, "_backoff_sleep", lambda attempt: None)


@pytest.fixture
def flag(monkeypatch):
    """Setter for MARKET_ANCHOR_PRICE_TIME (the default, on, is set up front)."""
    def _set(on):
        monkeypatch.setattr(Config, "MARKET_ANCHOR_PRICE_TIME", on, raising=False)
    _set(True)
    return _set


@pytest.fixture
def gamma(monkeypatch):
    """Setter for the Gamma /markets rows every requote receives."""
    def _serve(rows):
        monkeypatch.setattr(pm.httpx, "get", lambda *a, **k: _FakeResponse(list(rows)))
    return _serve


@pytest.fixture
def handoff(tmp_path, monkeypatch):
    """A pipeline for sim1 whose handoff dir is tmp_path; returns a payload writer."""
    from app.services.pipeline_orchestrator import PipelineManager

    monkeypatch.setattr(PipelineManager, "list_pipelines",
                        classmethod(lambda cls: [{"pipeline_id": "p1"}]))
    monkeypatch.setattr(PipelineManager, "load", classmethod(
        lambda cls, pid: {"simulation_id": "sim1", "handoff_dir": str(tmp_path)}))

    def _write(payload):
        (tmp_path / "prediction_markets.json").write_text(json.dumps(payload),
                                                          encoding="utf-8")
    return _write


def _agent(**over):
    a = ReportAgent.__new__(ReportAgent)
    a.simulation_id = "sim1"
    a.simulation_requirement = "Will the Fed cut rates in 2026?"
    a.actors = {}
    a.output_language = "English"
    a.hindcast = None
    a._hindcast_pin_cache = None
    a._market_pack = ""
    a._prediction_markets = []
    a._markets_stale = False
    for k, v in over.items():
        setattr(a, k, v)
    return a


def _market(**over):
    row = {"market_id": "m1", "exchange": "polymarket",
           "question": "Will the Fed cut rates three times in 2026?",
           "implied_yes_prob": 0.34, "url": "https://polymarket.com/event/fed-cuts",
           "end_date": END, "volume": 9000}
    row.update(over)
    return row


def _binary(**over):
    row = {"id": "F1", "proposition_id": "P1",
           "statement": "The Fed cuts rates three times during 2026.",
           "resolution_criteria": "Three FOMC cuts announced in 2026",
           "probability": 0.40, "theme": "rates", "horizon_year": 2026,
           "adjustment_rationale": "base rate"}
    row.update(over)
    return row


def _anchor(market, binary=None):
    b = binary if binary is not None else _binary()
    return fe._build_market_anchor(b["probability"], market, equivalence="exact",
                                   match_confidence=0.9, binary=b)


def _pre_change_anchor(market, binary):
    """The rich market_anchor exactly as _build_market_anchor built it before EVAL-6."""
    ip = round(market["implied_yes_prob"], 4)
    contract = (binary["statement"].strip() + "\n" + binary["resolution_criteria"].strip())
    return {
        "market_id": market["market_id"],
        "question": market["question"],
        "implied_yes_prob": ip,
        "price_at_research": ip,
        "divergence": round(binary["probability"] - ip, 4),
        "url": market["url"],
        "endDate": market["end_date"],
        "resolution_equivalence": "exact",
        "match_confidence": 0.9,
        "forecast_proposition_id": binary["proposition_id"],
        "forecast_contract_sha256": hashlib.sha256(contract.encode("utf-8")).hexdigest(),
        "market_question_sha256": hashlib.sha256(
            market["question"].encode("utf-8")).hexdigest(),
        "match_method": "bounded-semantic-equivalence-review",
    }


def _without_price_time(value):
    """Deep copy with every price_time / price_time_basis key removed."""
    if isinstance(value, dict):
        return {k: _without_price_time(v) for k, v in value.items()
                if k not in _PRICE_TIME_KEYS}
    if isinstance(value, list):
        return [_without_price_time(v) for v in value]
    return value


# ------------------------------------------------------------------ requote_markets
def test_requote_stamps_quoted_at_only_on_success(enabled, clock, flag, gamma):
    """A fresh price gets the batch quote time; a failed row with no prior quote gets none."""
    gamma([_gamma("m1", 0.41), _gamma("m2", 0.20, closed=True)])
    out = PolymarketClient().requote_markets([
        {"market_id": "m1", "implied_yes_prob": 0.34},
        {"market_id": "m2", "implied_yes_prob": 0.55},     # closed → requote_failed
        {"market_id": "m3", "implied_yes_prob": 0.60},     # not returned → requote_failed
    ])
    by = {m["market_id"]: m for m in out}
    assert by["m1"]["quoted_at"] == T1.isoformat()
    assert by["m1"]["implied_yes_prob"] == 0.41
    for mid in ("m2", "m3"):
        assert by[mid]["requote_failed"] is True
        assert "quoted_at" not in by[mid]


def test_requote_failed_row_keeps_prior_quoted_at(enabled, clock, flag, gamma):
    """A failed requote keeps the earlier quoted_at: it still dates the retained price."""
    earlier = (T1 - timedelta(hours=1)).isoformat()
    gamma([_gamma("m1", 0.20, closed=True)])
    row = {"market_id": "m1", "implied_yes_prob": 0.41, "price_at_research": 0.34,
           "quoted_at": earlier}
    out = PolymarketClient().requote_markets([row])
    assert out[0]["requote_failed"] is True
    assert out[0]["quoted_at"] == earlier
    assert out[0]["implied_yes_prob"] == 0.41
    assert row == {"market_id": "m1", "implied_yes_prob": 0.41, "price_at_research": 0.34,
                   "quoted_at": earlier}                # caller's row never mutated


def test_requote_success_replaces_prior_quoted_at(enabled, clock, flag, gamma):
    gamma([_gamma("m1", 0.45)])
    clock["now"] = T2
    out = PolymarketClient().requote_markets([
        {"market_id": "m1", "implied_yes_prob": 0.41, "quoted_at": T1.isoformat()}])
    assert out[0]["quoted_at"] == T2.isoformat()
    assert out[0]["implied_yes_prob"] == 0.45


def test_requote_flag_off_output_is_pre_change_shape(enabled, clock, flag, gamma):
    flag(False)
    gamma([_gamma("m1", 0.41), _gamma("m2", 0.20, closed=True)])
    out = PolymarketClient().requote_markets([
        {"market_id": "m1", "implied_yes_prob": 0.34},
        {"market_id": "m2", "implied_yes_prob": 0.55}])
    assert json.dumps(out) == json.dumps([
        {"market_id": "m1", "implied_yes_prob": 0.41, "price_at_research": 0.34,
         "price_delta": 0.07},
        {"market_id": "m2", "implied_yes_prob": 0.55, "price_at_research": 0.55,
         "requote_failed": True},
    ])


# ------------------------------------------------------------------ _load_prediction_markets
def test_load_prediction_markets_copies_snapshot_as_of(flag, handoff):
    """The handoff payload's as_of lands on each row; a row's own snapshot_as_of wins.

    The client stays disabled (conftest), so the requote keeps the research prices."""
    own = "2026-09-27T00:00:00+00:00"
    handoff({"as_of": SNAPSHOT_AS_OF, "source": "polymarket",
             "markets": [_market(), _market(market_id="m2", snapshot_as_of=own)]})
    rows = _agent()._load_prediction_markets()
    assert [(r["market_id"], r["snapshot_as_of"]) for r in rows] == [
        ("m1", SNAPSHOT_AS_OF), ("m2", own)]
    assert all("quoted_at" not in r for r in rows)


def test_load_prediction_markets_without_payload_as_of_adds_nothing(flag, handoff):
    handoff({"markets": [_market()]})
    rows = _agent()._load_prediction_markets()
    assert "snapshot_as_of" not in rows[0]


def test_load_prediction_markets_flag_off_rows_unchanged(flag, handoff):
    flag(False)
    handoff({"as_of": SNAPSHOT_AS_OF, "markets": [_market()]})
    assert _agent()._load_prediction_markets() == [_market()]


def _live_fallback(monkeypatch, row):
    from app.services.pipeline_orchestrator import PipelineManager

    monkeypatch.setattr(PipelineManager, "list_pipelines", classmethod(lambda cls: []))
    monkeypatch.setattr(pm, "derive_market_queries_llm", lambda *_a, **_k: ["fed cuts"])
    monkeypatch.setattr(pm.PolymarketClient, "snapshot_for_queries",
                        lambda *_a, **_k: [dict(row)])
    monkeypatch.setattr(pm, "score_market_relevance",
                        lambda *_a, **_k: [{**row, "relevance_score": 8.0}])


def test_live_fallback_rows_carry_the_fetch_time(enabled, flag, monkeypatch, tmp_path):
    """The one fetch time is both the recovered artifact's as_of and each row's snapshot_as_of."""
    _live_fallback(monkeypatch, _market())
    monkeypatch.setattr(ReportManager, "_get_report_folder",
                        classmethod(lambda cls, rid: str(tmp_path)))
    rows = _agent(llm=object(), _active_report_id="r1")._load_prediction_markets()
    recovered = json.loads((tmp_path / "prediction_markets_recovered.json")
                           .read_text(encoding="utf-8"))
    assert [r["snapshot_as_of"] for r in rows] == [recovered["as_of"]]
    assert parse_stamp_strict(recovered["as_of"], allow_date=False) is not None
    assert "snapshot_as_of" not in recovered["markets"][0]   # artifact rows keep their shape


def test_live_fallback_without_report_id_still_stamps_rows(enabled, flag, monkeypatch):
    _live_fallback(monkeypatch, _market())
    before = datetime.now(UTC)
    rows = _agent(llm=object())._load_prediction_markets()
    stamp = parse_stamp_strict(rows[0]["snapshot_as_of"], allow_date=False)
    assert stamp is not None and before <= stamp <= datetime.now(UTC)


def test_live_fallback_fetch_time_precedes_relevance_scoring(enabled, flag, monkeypatch):
    """The fetch time is taken when the prices arrive, not after the relevance LLM call."""
    _live_fallback(monkeypatch, _market())
    seen = {}

    def _slow_scorer(*_a, **_k):
        seen["scoring_started"] = datetime.now(UTC)
        while datetime.now(UTC) <= seen["scoring_started"]:
            pass                                          # the LLM call takes time
        return [{**_market(), "relevance_score": 8.0}]

    monkeypatch.setattr(pm, "score_market_relevance", _slow_scorer)
    rows = _agent(llm=object())._load_prediction_markets()
    assert datetime.fromisoformat(rows[0]["snapshot_as_of"]) <= seen["scoring_started"]


def test_live_fallback_flag_off_rows_unchanged(enabled, flag, monkeypatch):
    flag(False)
    _live_fallback(monkeypatch, _market())
    rows = _agent(llm=object())._load_prediction_markets()
    assert rows == [{**_market(), "relevance_score": 8.0}]


# ------------------------------------------------------------------ _build_market_anchor
@pytest.mark.parametrize("extra,expected", [
    ({"quoted_at": T1.isoformat(), "snapshot_as_of": SNAPSHOT_AS_OF},
     (T1.isoformat(), "requote")),
    ({"snapshot_as_of": SNAPSHOT_AS_OF}, (SNAPSHOT_AS_OF, "snapshot")),
    ({"requote_failed": True, "snapshot_as_of": SNAPSHOT_AS_OF},
     (SNAPSHOT_AS_OF, "snapshot")),
    ({}, None),
    ({"snapshot_as_of": "2026-09-28"}, None),               # a bare date is not a moment
    ({"snapshot_as_of": "2026-09-28T06:00:00"}, None),      # naive: the zone is a guess
    # a requoted price with an unusable quote time is unknown, never the snapshot time
    ({"quoted_at": "yesterday", "snapshot_as_of": SNAPSHOT_AS_OF}, None),
])
def test_build_market_anchor_price_time_basis(flag, extra, expected):
    anchor = _anchor(_market(**extra))
    if expected is None:
        assert not any(k in anchor for k in _PRICE_TIME_KEYS)
    else:
        assert (anchor["price_time"], anchor["price_time_basis"]) == expected
    # the probability-bearing fields never depend on the price time
    assert _without_price_time(anchor) == _pre_change_anchor(_market(), _binary())


def test_flag_off_anchor_byte_identical(flag):
    flag(False)
    stamped = _market(quoted_at=T1.isoformat(), snapshot_as_of=SNAPSHOT_AS_OF)
    expected = json.dumps(_pre_change_anchor(_market(), _binary()), ensure_ascii=False)
    assert json.dumps(_anchor(stamped), ensure_ascii=False) == expected
    assert json.dumps(_anchor(_market()), ensure_ascii=False) == expected


def test_integrity_audit_tolerates_new_keys(flag):
    binary = _binary()
    binary["market_anchor"] = _anchor(_market(quoted_at=T1.isoformat()), binary)
    anchor = binary["market_anchor"]
    assert anchor["price_time_basis"] == "requote"
    assert fe._market_anchor_complete(anchor)
    assert fe._market_anchor_binding_valid(binary, anchor)
    audit = fe.audit_market_anchor_integrity({"binary_forecasts": [binary]})
    assert audit == {"anchored_count": 1, "issues": [], "issue_count": 0, "passed": True}
    diagnostics = fe.reconcile_forecast_contract({"binary_forecasts": [binary]})
    assert diagnostics["removed_market_anchors"] == []
    assert diagnostics["market_anchors"]["passed"] is True
    assert binary["market_anchor"]["price_time"] == T1.isoformat()


# ------------------------------------------------------------------ binary extraction path
_DRAW = {"binary_forecasts": [
    {"id": "F1", "statement": "The Fed cuts rates three times during 2026.",
     "probability": 0.40, "resolution_criteria": "Three FOMC cuts announced in 2026",
     "theme": "rates", "horizon_year": 2026, "adjustment_rationale": "base rate"},
    {"id": "F2", "statement": "US unemployment exceeds 5% by the end of 2026.",
     "probability": 0.25, "resolution_criteria": "BLS U-3 above 5.0% for December 2026",
     "theme": "labor", "horizon_year": 2026, "adjustment_rationale": "labor trend"},
]}
_MATCHES = {"matches": [
    {"forecast_id": "F1", "market_id": "m1", "resolution_equivalence": "exact",
     "confidence": 0.9},
    {"forecast_id": "F2", "market_id": "m2", "resolution_equivalence": "near",
     "confidence": 0.8},
]}
_REVISIONS = {"revisions": [
    {"id": "F2", "probability": 0.30,
     "adjustment_rationale": "The market's implied 55% overstates the labor slack."}]}


def _extract(monkeypatch, markets):
    monkeypatch.setattr(Config, "FORECAST_BINARY_CONTRARIAN", False, raising=False)
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_MODELS", "", raising=False)
    fake = FakeLLMClient(json_responses=[copy.deepcopy(_DRAW), copy.deepcopy(_MATCHES),
                                         copy.deepcopy(_REVISIONS)])
    out = fe.extract_binary_forecasts("dossier", fake, min_count=2, language="English",
                                      market_pack="table", markets=copy.deepcopy(markets))
    return out, {b["id"]: b for b in out["binary_forecasts"]}


def test_extraction_after_failed_second_requote_keeps_first_quote(
        enabled, clock, flag, gamma, handoff, monkeypatch):
    """First requote (report load) succeeds, the pre-extraction requote fails: the anchor is
    dated by the first quote with basis 'requote', never mislabelled as the snapshot."""
    handoff({"as_of": SNAPSHOT_AS_OF, "markets": [_market()]})
    agent = _agent()
    gamma([_gamma("m1", 0.41)])
    agent._prediction_markets = agent._load_prediction_markets()
    assert agent._prediction_markets[0]["quoted_at"] == T1.isoformat()
    clock["now"] = T2
    gamma([])                                            # market no longer returned
    agent._refresh_market_prices_for_extraction()
    row = agent._prediction_markets[0]
    assert row["requote_failed"] is True and row["implied_yes_prob"] == 0.41
    assert (row["quoted_at"], row["snapshot_as_of"]) == (T1.isoformat(), SNAPSHOT_AS_OF)
    _out, by_id = _extract(monkeypatch, agent._prediction_markets)
    anchor = by_id["F1"]["market_anchor"]
    assert (anchor["price_time"], anchor["price_time_basis"]) == (T1.isoformat(), "requote")
    assert anchor["price_at_research"] == anchor["implied_yes_prob"] == 0.41


def test_extraction_flag_changes_no_probability_or_anchoring_decision(
        clock, flag, monkeypatch):
    markets = [_market(quoted_at=T1.isoformat(), snapshot_as_of=SNAPSHOT_AS_OF),
               _market(market_id="m2", question="Will US unemployment exceed 5% in 2026?",
                       implied_yes_prob=0.55, snapshot_as_of=SNAPSHOT_AS_OF)]
    on, on_by_id = _extract(monkeypatch, markets)
    assert (on_by_id["F1"]["market_anchor"]["price_time_basis"],
            on_by_id["F2"]["market_anchor"]["price_time_basis"]) == ("requote", "snapshot")
    assert on_by_id["F2"]["probability"] == 0.30          # the 10pp revision still ran
    flag(False)
    off, _ = _extract(monkeypatch, markets)
    assert _without_price_time(on) == off                 # probabilities, anchors, gates
    legacy = [{k: v for k, v in m.items() if k not in ("quoted_at", "snapshot_as_of")}
              for m in markets]
    legacy_off, _ = _extract(monkeypatch, legacy)
    assert json.dumps(off, ensure_ascii=False, sort_keys=False) == json.dumps(
        legacy_off, ensure_ascii=False, sort_keys=False)  # flag off: byte-identical


# ------------------------------------------------------------------ resolution_monitor
def test_build_price_rows_carries_price_time_into_price_track():
    anchored = [
        {"id": "F1", "statement": "s1",
         "market_anchor": {"market_id": "m1", "question": "q1", "implied_yes_prob": 0.41,
                           "price_at_research": 0.41, "price_time": T1.isoformat(),
                           "price_time_basis": "requote"}},
        {"id": "F2", "statement": "s2",
         "market_anchor": {"market_id": "m2", "question": "q2", "implied_yes_prob": 0.2}},
    ]
    rows = rm.build_price_rows(anchored)
    assert (rows[0]["price_time"], rows[0]["price_time_basis"]) == (T1.isoformat(), "requote")
    assert rows[1] == {"market_id": "m2", "question": "q2", "implied_yes_prob": 0.2,
                       "price_at_research": 0.2, "forecast_id": "F2", "statement": "s2"}
    snapshot = rm._price_snapshot("r1", "2026-10-01", rows)
    assert snapshot["markets"][0]["price_time"] == T1.isoformat()
    assert snapshot["markets"][0]["price_time_basis"] == "requote"
    assert snapshot["markets"][1] == {"market_id": "m2", "price_at_research": 0.2,
                                      "implied_yes_prob": 0.2, "price_delta": None,
                                      "requote_failed": False}


@pytest.mark.parametrize("partial", [
    {"price_time_basis": "requote"},                          # a basis with no time
    {"price_time": T1.isoformat()},                           # a time with no basis
    {"price_time": "", "price_time_basis": "snapshot"},
    {"price_time": T1.isoformat(), "price_time_basis": None},
    {"price_time": 1727687700, "price_time_basis": "requote"},
])
def test_price_track_never_carries_half_a_price_time_pair(partial):
    anchored = [{"id": "F1", "statement": "s1",
                 "market_anchor": {"market_id": "m1", "question": "q1",
                                   "implied_yes_prob": 0.41, **partial}}]
    rows = rm.build_price_rows(anchored)
    assert rows == [{"market_id": "m1", "question": "q1", "implied_yes_prob": 0.41,
                     "price_at_research": 0.41, "forecast_id": "F1", "statement": "s1"}]
    snapshot = rm._price_snapshot("r1", "2026-10-01", [{**rows[0], **partial}])
    assert not any(k in snapshot["markets"][0] for k in _PRICE_TIME_KEYS)


# ------------------------------------------------------------------ helpers
def test_stamp_snapshot_as_of_rules(flag):
    rows = [{"market_id": "a"}, "junk", {"market_id": "b", "snapshot_as_of": "x"}]
    out = pm.stamp_snapshot_as_of(rows, SNAPSHOT_AS_OF)
    assert out == [{"market_id": "a", "snapshot_as_of": SNAPSHOT_AS_OF},
                   {"market_id": "b", "snapshot_as_of": "x"}]
    assert rows[0] == {"market_id": "a"}                  # copies, never in place
    assert pm.stamp_snapshot_as_of(rows, "  ") == [rows[0], rows[2]]
    assert pm.stamp_snapshot_as_of(rows, None) == [rows[0], rows[2]]
    assert pm.stamp_snapshot_as_of(None, SNAPSHOT_AS_OF) == []
    flag(False)
    assert pm.stamp_snapshot_as_of(rows, SNAPSHOT_AS_OF) == [rows[0], rows[2]]
    assert pm.market_price_time("not a row") is None


def test_price_time_knob_defaults_on_and_is_documented():
    assert Config.MARKET_ANCHOR_PRICE_TIME is True
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, ".env.example"), encoding="utf-8") as f:
        assert "# MARKET_ANCHOR_PRICE_TIME=true" in f.read()
