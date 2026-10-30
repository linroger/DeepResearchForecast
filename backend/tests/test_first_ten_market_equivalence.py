"""A model-declared market ID is not evidence of an exact settlement match."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from app.services import forecast_extractor as fe
from app.services.forecast_tournament import run_forecast_tournament
from app.services.target_report import build_target_report, audit_target_report


@pytest.fixture
def market_case():
    case = json.loads((Path(__file__).parent / "fixtures/target_case.json").read_text())
    case["binaries"][0]["resolution_contract"] = {
        "kind": "polymarket", "market_id": "M1", "equivalence": "exact"}
    return case


@pytest.fixture
def market():
    # Retained provider text, explicitly synthetic. No helper manufactures the
    # asserted source evidence, and no semantic-review marker is supplied.
    return {"market_id": "M1", "implied_yes_prob": 0.73,
            "question": "Will 2027 spending be at least USD 280 billion?",
            "description": (
                'This market will resolve to "Yes" if worldwide security spending for the calendar year 2027 '
                'is at least USD 280 billion, as reported in the first annual release by '
                'Synthetic official statistics (https://example.test/spending). '
                'It will otherwise resolve to "No". The resolution deadline is March 30, 2028.'),
            "url": "https://example.test/market/M1", "endDate": "2028-03-30",
            "retrieved_at": datetime.now(timezone.utc).isoformat()}


def test_retained_exact_terms_reach_audit_and_method_lane(market_case, market):
    bundle = build_target_report(market_case, markets=[market])
    row = bundle["forecast"]["binary_forecasts"][0]
    assert row["probability"] == 0.6
    assert row["market_anchor"]["match_method"] == "deterministic-tree-settlement-v1"
    assert row["market_anchor"]["description"] == market["description"]
    assert row["resolution_date"] == "2028-03-30"
    assert fe.audit_market_anchor_integrity(bundle["forecast"])["passed"]
    assert audit_target_report(market_case, None, bundle["forecast"], bundle["record"], markets=[market])["valid"]
    tournament = run_forecast_tournament(bundle["forecast"], case=market_case, markets=[market], enabled=True)
    lane = next(x for x in tournament["estimators"] if x["source"] == "market_implied")
    assert lane["status"] == "ok" and lane["binaries"] == [{"id": "B1", "p": 0.73}]


@pytest.mark.parametrize("mutation", ["threshold", "year", "entity", "source", "url", "deadline", "comparator",
                                    "title_only", "wrong_title", "unsupported", "driver", "duplicate_id", "no_snapshot"])
def test_unproven_market_preserves_named_source_authority(market_case, market, mutation):
    if mutation == "threshold":
        market["description"] = market["description"].replace("280 billion", "999 billion")
    elif mutation == "year":
        market["description"] = market["description"].replace("2027", "2028")
    elif mutation == "entity":
        market["description"] = market["description"].replace("worldwide security", "US healthcare")
    elif mutation == "source":
        market["description"] = market["description"].replace("Synthetic official statistics", "Another publisher")
    elif mutation == "url":
        market["description"] = market["description"].replace("example.test/spending", "other.test/spending")
    elif mutation == "deadline":
        market["endDate"] = "2027-12-31"
    elif mutation == "comparator":
        market["description"] = market["description"].replace("at least", "more than")
    elif mutation == "title_only":
        market.pop("description")
    elif mutation == "wrong_title":
        market["question"] = market["question"].replace("280", "999")
    elif mutation == "unsupported":
        market["description"] += " Otherwise a committee may choose another source."
    elif mutation == "driver":
        market_case["binaries"][0]["predicate"]["nodeId"] = "trend"
    markets = None if mutation == "no_snapshot" else [market, deepcopy(market)] if mutation == "duplicate_id" else [market]
    if mutation == "driver":
        with pytest.raises(ValueError, match="exact tree market"):
            build_target_report(market_case, markets=markets)
        return
    bundle = build_target_report(market_case, markets=markets)
    row = bundle["forecast"]["binary_forecasts"][0]
    assert "market_anchor" not in row
    assert row["probability"] == 0.6
    assert row["resolution_contract"]["kind"] == "named_source_event"
    assert row["resolution_contract"]["publisher"] == market_case["resolution"]["settlementSource"]["name"]
    assert row["market_equivalence"]["reason"]
    assert row["market_equivalence"]["status"] == ("unavailable" if mutation in {
        "title_only", "unsupported", "duplicate_id", "no_snapshot"} else "rejected")
    result = run_forecast_tournament(bundle["forecast"], case=market_case, markets=markets, enabled=True)
    assert next(x for x in result["estimators"] if x["source"] == "market_implied")["status"] == "unavailable"


def test_declared_contract_cannot_bypass_admitted_anchor(market_case, market):
    case = deepcopy(market_case)
    case["binaries"][0].pop("resolution_contract")
    forecast = build_target_report(case)["forecast"]
    forecast["binary_forecasts"][0]["resolution_contract"] = market_case["binaries"][0]["resolution_contract"]
    out = run_forecast_tournament(forecast, case=case, markets=[market], enabled=True)
    lane = next(x for x in out["estimators"] if x["source"] == "market_implied")
    assert lane["status"] == "unavailable" and not lane["binaries"]


@pytest.mark.parametrize("field", ["question", "description", "endDate"])
def test_changed_snapshot_cannot_reuse_exact_proof(market_case, market, field):
    forecast = build_target_report(market_case, markets=[market])["forecast"]
    changed = deepcopy(market)
    changed[field] += " changed"
    out = run_forecast_tournament(forecast, case=market_case, markets=[changed], enabled=True)
    assert next(x for x in out["estimators"] if x["source"] == "market_implied")["status"] == "unavailable"


def test_historical_wrong_event_cannot_score(market_case, tmp_path):
    from app.services import forecast_ledger as ledger
    wrong = {"market_id": "M1", "question": "Will 2028 spending be at least USD 999 billion?",
             "description": "YES only if 2028 spending exceeds USD 999 billion.",
             "endDate": "2028-12-31", "url": "https://example.test/wrong-market", "implied_yes_prob": 0.3}
    forecast = build_target_report(market_case, markets=[wrong])["forecast"]
    binary = forecast["binary_forecasts"][0]
    assert "market_anchor" not in binary and binary["market_equivalence"]["reason"]
    ledger.record_published_forecast(forecast, report_id="wrong-market-fallback",
                                   created_at="2026-10-28T00:00:00Z", d=tmp_path)
    row = {"report_id": "wrong-market-fallback", "forecast_id": "B1", "model_p": 0.6,
           "market_id": "M1", "market_anchor": wrong, "resolved_at": "2029-01-02T00:00:00Z",
           "resolved_outcome": "Yes", "resolved_yes_price": 1.0}
    assert ledger.reconcile_published_resolutions("wrong-market-fallback", market_rows=[row], data_rows=[], d=tmp_path)["accepted"] == 0


def test_exact_source_contract_reaches_sealed_publication(market_case, market, tmp_path, monkeypatch):
    from app.services.report_agent import ReportAgent, ReportManager, ReportStatus
    from app.services.forecast_ledger import read_published_forecast
    from app.services.official_data import bridge_module
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    evidence = {"schemaVersion": "target-evidence/v1",
                "caseHash": bridge_module("forecast_case").case_hash(market_case),
                "official_data": None, "markets": [market], "news_market_context": None}
    agent = ReportAgent("graph_exact", "sim_exact", market_case["question"],
                        forecast_case=market_case, target_evidence=evidence)
    report = agent.generate_report(report_id="report_exact")
    assert report.status == ReportStatus.COMPLETED, report.error
    assert ReportManager.publication_status(report.report_id)["publishable"]
    issued = read_published_forecast(report.report_id)["forecast"]
    binary = issued["binary_forecasts"][0]
    assert binary["market_anchor"]["description"] == market["description"]
    assert binary["probability"] == 0.6
    assert fe.audit_market_anchor_integrity(issued)["passed"]


def test_native_gamma_snapshot_retains_natural_source_terms(market_case, market, monkeypatch, tmp_path):
    from deerflow_bridge import deerflow_research as collector
    from app.config import Config
    from app.services.report_agent import ReportAgent, ReportManager, ReportStatus
    from app.services.forecast_ledger import read_published_forecast
    from app.services.official_data import bridge_module
    raw = {"id": "M1", "question": market["question"], "description": "\n " + market["description"] + "\n",
           "endDate": market["endDate"], "outcomes": '["Yes","No"]',
           "outcomePrices": '["0.73","0.27"]', "volume": 1000, "closed": False}
    original = deepcopy(raw)
    calls = []
    def transport(path, params, **kwargs):
        calls.append((path, params))
        return {"events": [{"title": "Security spending", "slug": "spending-2027", "markets": [deepcopy(raw)]}]}
    monkeypatch.setattr(collector, "_polymarket_get", transport)
    monkeypatch.setattr(collector, "_pm_backtest_policy", lambda: None)
    diagnostics = {}
    rows = collector._pm_snapshot(["security spending 2027"], diagnostics=diagnostics)
    assert len(calls) == 1 and diagnostics["successful_query_count"] == 1
    assert rows[0]["description"] == original["description"]
    assert raw == original
    payload = {"markets": rows, "as_of": datetime.now(timezone.utc).isoformat(), "status": {"state": "fresh"}}
    bundle = build_target_report(market_case, markets=payload)
    row = bundle["forecast"]["binary_forecasts"][0]
    assert row["market_anchor"]["description"] == original["description"]
    assert row["market_anchor"]["match_method"] == "deterministic-tree-settlement-v1"
    assert audit_target_report(market_case, None, bundle["forecast"], bundle["record"], markets=payload)["valid"]
    result = run_forecast_tournament(bundle["forecast"], case=market_case, markets=payload, enabled=True)
    assert next(x for x in result["estimators"] if x["source"] == "market_implied")["status"] == "ok"
    # Continue the actual collector output through sealed publication and the
    # immutable journal; no post-normalization settlement fields are injected.
    monkeypatch.setattr(Config, "REPORT_TOURNAMENT", True)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    evidence = {"schemaVersion": "target-evidence/v1",
                "caseHash": bridge_module("forecast_case").case_hash(market_case),
                "official_data": None, "markets": payload, "news_market_context": None}
    report = ReportAgent("graph_native", "sim_native", market_case["question"],
                         forecast_case=market_case, target_evidence=evidence).generate_report(report_id="report_native_exact")
    assert report.status == ReportStatus.COMPLETED, report.error
    assert ReportManager.publication_status(report.report_id)["publishable"]
    issued = read_published_forecast(report.report_id)["forecast"]
    assert issued["binary_forecasts"][0]["market_anchor"]["description"] == original["description"]
    assert issued["binary_forecasts"][0]["probability"] == 0.6
    lane = next(x for x in issued["estimators"] if x["source"] == "market_implied")
    assert lane["status"] == "ok" and lane["binaries"] == [{"id": "B1", "p": 0.73}]


@pytest.mark.parametrize("description", [None, "", " \n\t", 17, {"text": "not provider text"}])
def test_native_normalizer_never_synthesizes_missing_source_description(description):
    from deerflow_bridge import deerflow_research as collector
    raw = {"id": "M1", "question": "Will spending grow?", "description": description,
           "outcomes": '["Yes","No"]', "outcomePrices": '["0.73","0.27"]', "volume": 1000}
    before = deepcopy(raw)
    row = collector._pm_normalize_market(raw, "spending", 0)
    assert row is not None and "description" not in row
    assert raw == before
