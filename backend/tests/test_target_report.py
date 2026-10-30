"""Typed report public consumer and prospective comparison regressions; no startup."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest

from app.services import target_report as tr


@pytest.fixture
def case():
    return json.loads((Path(__file__).parent / "fixtures/target_case.json").read_text())


def simulation(case):
    return {"schemaVersion": "target-simulation/v1", "caseId": case["caseId"],
            "caseHash": tr._case_api().case_hash(case), "seed": 7,
            "paths": [{"pathId": "p0", "parameters": {},
                       "trajectory": [{"period": 1, "values": {"spending": 290}}],
                       "decisions": [], "targetValue": 290}],
            "scenarioShares": {"below": 0.0, "above": 1.0, "other": 0.0},
            "targetSummary": {"mean": 290.0}, "sensitivity": [{"nodeId": "trend", "slope": 250.0}],
            "signposts": [{"nodeId": "trend", "threshold": 0.12}], "simulationWeight": 0.0}


def test_projection_retains_exact_typed_authority_and_diagnostics(case):
    before = deepcopy(case)
    result = tr.build_target_report(case, simulation(case))
    forecast = result["forecast"]
    assert [r["probability"] for r in forecast["scenarios"]] == [0.4, 0.6]
    assert forecast["binary_forecasts"][0]["probability"] == 0.6
    assert result["record"]["assessmentLedger"] == case["assessments"]
    assert result["record"]["divergence"][0]["difference"] == -0.4
    assert "No published shock frequency" in result["markdown"]
    assert "[S1]" in result["markdown"]
    assert "ZERO forecast weight" in result["markdown"]
    assert "### Sensitivity" in result["markdown"] and "### Signposts" in result["markdown"]
    assert case == before
    result["record"]["assessment"]["scenarioWeights"]["below"] = 0.9
    assert case == before


def test_simulation_changes_cannot_change_research_probabilities(case):
    first = simulation(case)
    second = deepcopy(first)
    second["scenarioShares"] = {"below": 1.0, "above": 0.0, "other": 0.0}
    second["paths"][0]["targetValue"] = 270.0
    second["paths"][0]["trajectory"][-1]["values"]["spending"] = 270.0
    a, b = tr.build_target_report(case, first), tr.build_target_report(case, second)
    assert a["forecast"] == b["forecast"]
    assert a["record"] != b["record"]


@pytest.mark.parametrize("field,value", [("simulationWeight", 0.1), ("caseHash", "wrong"),
                                         ("caseId", "another"), ("simulationWeight", False)])
def test_invalid_simulation_cannot_enter_report(case, field, value):
    sim = simulation(case)
    sim[field] = value
    with pytest.raises(ValueError):
        tr.build_target_report(case, sim)


def test_prospective_registration_is_immutable_and_retry_keeps_enrollment(case, tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "_utcnow", lambda: datetime(2026, 10, 27, 12, tzinfo=timezone.utc))
    sim = simulation(case)
    path = tmp_path / "pair.json"
    first = tr.register_comparison(path, case, sim, enrolled_at="2026-10-27T10:00:00Z")
    raw = path.read_bytes()
    assert tr.register_comparison(path, case, sim, enrolled_at="2026-10-27T11:00:00Z") == first
    assert path.read_bytes() == raw
    assert first["policy"]["simulationWeight"] == 0 and not first["policy"]["promotionAllowed"]
    assert first["researchArm"]["above"] == 0.6 and first["structuralArm"]["above"] == 1.0
    changed = deepcopy(sim)
    changed["seed"] = 8
    for destination in (path, tmp_path / "renamed.json"):
        with pytest.raises(ValueError, match="immutable"):
            tr.register_comparison(destination, case, changed, enrolled_at="2026-10-27T11:00:00Z")
    assert path.read_bytes() == raw


@pytest.mark.parametrize("enrolled_at", ["2026-10-26T12:00:00Z", "2026-10-28T12:00:00Z", "2026-10-27T12:00:00"])
def test_enrollment_rejects_backdating_future_and_naive(case, tmp_path, monkeypatch, enrolled_at):
    monkeypatch.setattr(tr, "_utcnow", lambda: datetime(2026, 10, 27, 12, tzinfo=timezone.utc))
    with pytest.raises(ValueError):
        tr.register_comparison(tmp_path / "pair.json", case, simulation(case), enrolled_at=enrolled_at)
    assert not list(tmp_path.iterdir())


def test_enrollment_requires_future_horizon_and_no_outcomes(case, tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "_utcnow", lambda: datetime(2028, 1, 1, 12, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="future resolution"):
        tr.register_comparison(tmp_path / "pair.json", case, simulation(case), enrolled_at="2028-01-01T12:00:00Z")
    monkeypatch.setattr(tr, "_utcnow", lambda: datetime(2026, 10, 27, 12, tzinfo=timezone.utc))
    sim = simulation(case)
    sim["resolvedOutcome"] = "above"
    with pytest.raises(ValueError, match="outcome-bearing"):
        tr.register_comparison(tmp_path / "pair.json", case, sim, enrolled_at="2026-10-27T12:00:00Z")
    assert not list(tmp_path.iterdir())


def test_backend_only_import_does_not_depend_on_test_root(case, monkeypatch):
    root = str(Path(__file__).resolve().parents[2])
    monkeypatch.setattr(sys, "path", [entry for entry in sys.path if entry not in (root, "")])
    for name in list(sys.modules):
        if name == "deerflow_bridge" or name.startswith("deerflow_bridge."):
            monkeypatch.delitem(sys.modules, name)
    assert tr.build_target_report(case)["forecast"]["authority"] == "target-first-v1"
    assert root not in sys.path


def test_direct_production_generation_zero_provider_calls_and_publishable(case, tmp_path, monkeypatch):
    from app.config import Config
    from app.services import report_agent as ra
    from tests.conftest import FakeLLMClient
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("forbidden")
        raise AssertionError("typed report attempted legacy provider/state path")

    monkeypatch.setattr(ra, "LLMClient", forbidden)
    monkeypatch.setattr(ra, "ZepToolsService", forbidden)
    monkeypatch.setattr(ra, "load_simulation_world", forbidden)
    for name in ("_derive_and_pin_forecast_spine", "_finalize_structured_forecast", "plan_outline",
                 "_generate_bilingual_report", "_build_market_pack", "_sim_dir"):
        monkeypatch.setattr(ra.ReportAgent, name, forbidden)
    monkeypatch.setattr(ra.ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True)
    monkeypatch.setattr(Config, "REPORT_BILINGUAL", True)
    fake = FakeLLMClient()
    sim = simulation(case)
    agent = ra.ReportAgent("target_graph_fixture", "sim_fixture", case["question"],
                           forecast_case=case, target_simulation=sim, llm_client=fake)
    # The constructor owns an immutable snapshot, not the caller's mutable dict.
    case["binaries"][0]["probability"] = 0.9
    sim["scenarioShares"]["above"] = 0.0
    report = agent.generate_report(report_id="report_target_fixture")
    assert report.status == ra.ReportStatus.COMPLETED, report.error
    status = ra.ReportManager.publication_status(report.report_id)
    assert status["publishable"] is True, status
    assert calls == [] and fake.calls == []
    folder = tmp_path / "reports" / report.report_id
    forecast = json.loads((folder / "forecast.json").read_text())
    assert forecast["binary_forecasts"][0]["probability"] == 0.6
    assert [row["probability"] for row in forecast["scenarios"]] == [0.4, 0.6]
    audit = json.loads((folder / "final_audit.json").read_text())
    assert audit["target_report"]["valid"] and audit["simulation_bridge"]["bytes_match"]
    assert audit["hard_passed"]
    assert agent.generate_report(report_id=report.report_id).forecast_authority == "target-first-v1"
    # Every typed companion is sealed by the same publication barrier.
    for name in ("forecast_case.json", "target_simulation.json", "target_report.json"):
        path = folder / name
        saved = path.read_bytes()
        path.write_text("{}")
        assert not ra.ReportManager.publication_status(report.report_id)["publishable"]
        path.write_bytes(saved)
    assert ra.ReportManager.publication_status(report.report_id)["publishable"]


def test_explicit_invalid_mode_fails_before_legacy_clients(monkeypatch):
    from app.services import report_agent as ra
    monkeypatch.setattr(ra, "LLMClient", lambda *a, **k: pytest.fail("LLM constructor"))
    monkeypatch.setattr(ra, "load_simulation_world", lambda *a: pytest.fail("world loader"))
    with pytest.raises(ValueError):
        ra.ReportAgent("g", "s", "q", forecast_case={})
    with pytest.raises(ValueError, match="requires"):
        ra.ReportAgent("g", "s", "q", target_simulation={})


def test_precise_extreme_probabilities_and_sparse_source_ids(case, tmp_path, monkeypatch):
    from app.config import Config
    from app.services.report_agent import ReportAgent, ReportManager, ReportStatus
    case["binaries"][0]["probability"] = 0.1234567890123456
    case["binaries"][0]["predicate"] = {"nodeId": "spending", "operator": "gte", "value": 300.0}
    case["binaries"][0]["question"] = "Will spending reach USD 300 billion?"
    case["binaries"] += [{**deepcopy(case["binaries"][0]), "binaryId": "zero", "probability": 0},
                         {**deepcopy(case["binaries"][0]), "binaryId": "one", "probability": 1}]
    case["binaries"][1]["predicate"] = {"nodeId": "spending", "operator": "lt", "value": 0.0}
    case["binaries"][1]["question"] = "Will spending be negative?"
    case["binaries"][2]["predicate"] = {"nodeId": "spending", "operator": "gte", "value": 0.0}
    case["binaries"][2]["question"] = "Will spending be nonnegative?"
    def retag(value):
        if isinstance(value, dict):
            return {k: retag(v) for k, v in value.items()}
        if isinstance(value, list):
            return [retag(v) for v in value]
        return "S17" if value == "S1" else value
    case = retag(case)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(Config, "REPORT_FORECAST_LEDGER", False)
    agent = ReportAgent("g", "s", case["question"], forecast_case=case)
    report = agent.generate_report(report_id="report_sparse")
    assert report.status == ReportStatus.COMPLETED, report.error
    folder = tmp_path / "reports" / report.report_id
    forecast = json.loads((folder / "forecast.json").read_text())
    assert [r["probability"] for r in forecast["binary_forecasts"][:3]] == [0.1234567890123456, 0, 1]
    assert "[S17]" in report.markdown_content and "[S1]" not in report.markdown_content
    assert ReportManager.publication_status(report.report_id)["publishable"]
    # Re-auditing edited prose may not seal a changed typed forecast narrative.
    report.markdown_content = report.markdown_content.replace("250 billion", "999 billion")
    (folder / "full_report.md").write_text(report.markdown_content)
    audit = agent._audit_final_published_markdown(report.report_id, report)
    assert not audit["target_report"]["valid"]
    assert not audit["hard_passed"]


@pytest.mark.parametrize("kind", ["growth", "linear"])
def test_real_structural_paths_reach_publication(case, tmp_path, monkeypatch, kind):
    from app.services.target_simulation import run_paths
    from app.services import report_agent as ra, target_pipeline as tp
    from app.utils import llm_client
    from types import SimpleNamespace
    ReportAgent, ReportManager, ReportStatus = ra.ReportAgent, ra.ReportManager, ra.ReportStatus
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    if kind == "linear":
        case["mechanisms"][-1].update(kind="linear", inputNodeIds=["base"],
                                    parameters={"coefficients": [2.0], "intercept": 0.0})
        # A derived target has no observed period-zero value in this alternate
        # model; preserve the parameter-envelope regression without a false seed.
        next(n for n in case["nodes"] if n["nodeId"] == "spending")["value"] = None
    for actor in case["actors"]:
        actor["decisionRule"]["kind"] = "llm"
    observations = []
    class Decisions:
        def chat_json(self, messages, **kwargs):
            observation = json.loads(messages[-1]["content"])
            observations.append(observation)
            lever = observation["levers"][0]
            return {"actions": [{"kind": "lever", "actorId": observation["actorId"],
                                 "leverId": lever["leverId"], "value": lever["maximum"]}]}
    monkeypatch.setattr(llm_client, "LLMClient", Decisions)
    state = SimpleNamespace(pipeline_id="pipe_report_runtime", options={"target_decision_budget_v1": {"max_calls": 1}})
    sim = run_paths(case, paths=3, periods=3, seed=13, lookahead=True,
                    decision_provider=tp._decision_provider(None, state),
                    interventions=[{"interventionId": "mandate", "settings": [
                        {"actorId": "regulator", "leverId": "mandate", "value": 0.02}]}],
                    conditions=[{"conditionId": "upper", "predicate": case["scenarios"][1]["predicate"]}],
                    model_validation="diagnostic")
    sim["decisionBudget"] = deepcopy(state.options["target_decision_usage"])
    assert len(observations) == 1 and observations[0]["options"]
    assert observations[0]["actorId"] not in {actor["actorId"] for actor in case["actors"]}
    assert sim["replay"]["identityMode"] == "opaque" and sim["replay"]["lookahead"]
    assert sim["interventionTables"][0]["kind"] == "intervention"
    assert sim["conditionalTables"][0]["kind"] == "observational_conditioning"
    assert sim["decisionBudget"]["requests"] == 1 and sim["decisionBudget"]["exhausted"]
    if kind == "linear":
        assert sim["paths"][0]["parameters"]["spending-growth"] == {"coefficient:base": 2.0, "intercept": 0.0}
    monkeypatch.setattr(tr, "_utcnow", lambda: datetime(2026, 10, 27, 12, tzinfo=timezone.utc))
    receipt = tr.register_comparison(tmp_path / "pair.json", case, sim, enrolled_at="2026-10-27T12:00:00Z")
    assert receipt["structuralArm"] == sim["scenarioShares"] and receipt["policy"]["simulationWeight"] == 0
    agent = ReportAgent("target_graph_actual", "sim_actual_" + kind, case["question"], forecast_case=case, target_simulation=sim)
    report = agent.generate_report(report_id="report_actual_" + kind)
    assert report.status == ReportStatus.COMPLETED, report.error
    assert ReportManager.publication_status(report.report_id)["publishable"]
    folder = tmp_path / "reports" / report.report_id
    forecast = json.loads((folder / "forecast.json").read_text())
    assert forecast["binary_forecasts"][0]["probability"] == case["binaries"][0]["probability"]
    assert [row["probability"] for row in forecast["scenarios"]] == [0.4, 0.6]
    assert json.loads((folder / "target_simulation.json").read_text()) == sim
    markdown = (folder / "full_report.md").read_bytes()
    block = tr.diagnostic_markdown(json.loads((folder / "target_report.json").read_text()), forecast=forecast)
    for _ in range(2):
        audit = agent._enforce_final_publish_audit(report.report_id, report)
        assert audit["hard_passed"] and not audit["lint"]["changed"]
        assert audit["simulation_bridge"]["bytes_match"] and audit["quality_notes"]["passed"]
        assert ra._sim_bridge_blocks(report.markdown_content) == [block]
        assert ra._insert_sim_bridge(report.markdown_content, block) == report.markdown_content
        assert (folder / "full_report.md").read_bytes() == markdown
    assert agent.generate_report(report_id=report.report_id).status == ReportStatus.COMPLETED
    assert len(observations) == 1
    # Fences remain exact authority boundaries even after canonical reinsertion.
    original = report.markdown_content
    for altered in (original.replace(block, ""), original.replace(block, block + "\n\n" + block),
                    original.replace("ZERO forecast weight", "POSITIVE forecast weight")):
        report.markdown_content = altered
        (folder / "full_report.md").write_text(altered)
        audit = agent._audit_final_published_markdown(report.report_id, report)
        assert not audit["simulation_bridge"]["bytes_match"] and not audit["hard_passed"]
        assert not ReportManager.publication_status(report.report_id)["publishable"]


@pytest.mark.parametrize("parameters", [{"coefficients": [2.0], "intercept": 0.0},
                                       {"coefficient:base": 2.0},
                                       {"coefficient:other": 2.0, "intercept": 0.0},
                                       {"coefficient:base": True, "intercept": 0.0}])
def test_flattened_runtime_parameters_remain_strict(case, parameters):
    from app.services.target_simulation import run_paths
    case["mechanisms"][-1].update(kind="linear", inputNodeIds=["base"],
                                parameters={"coefficients": [2.0], "intercept": 0.0})
    # Leave this alternate model's seed unmeasured so the negative case reaches
    # its intended malformed runtime-parameter boundary.
    next(n for n in case["nodes"] if n["nodeId"] == "spending")["value"] = None
    sim = run_paths(case, paths=1, periods=1)
    sim["paths"][0]["parameters"]["spending-growth"] = parameters
    with pytest.raises(ValueError, match="parameter fields"):
        tr.build_target_report(case, sim)


def test_structural_scoring_rejects_fabricated_paths_and_nested_outcomes(case):
    sim = simulation(case)
    sim["scenarioShares"] = {"below": 1.0, "above": 0.0, "other": 0.0}
    with pytest.raises(ValueError, match="terminal paths"):
        tr.build_target_report(case, sim)
    for path in ({}, {**simulation(case)["paths"][0], "resolved": True},
                 {**simulation(case)["paths"][0], "result": "above"}):
        sim = simulation(case)
        sim["paths"] = [path]
        with pytest.raises(ValueError, match="path fields"):
            tr.build_target_report(case, sim)


def test_enrollment_recovers_original_on_later_day_after_horizon_and_new_copy(case, tmp_path, monkeypatch):
    sim = simulation(case)
    monkeypatch.setattr(tr, "_utcnow", lambda: datetime(2026, 10, 27, 12, tzinfo=timezone.utc))
    registry = tmp_path / "registry"
    path = tmp_path / "original" / "pair.json"
    first = tr.register_comparison(path, case, sim, enrolled_at="2026-10-27T10:00:00Z", registry_dir=registry)
    for now in (datetime(2026, 10, 28, 12, tzinfo=timezone.utc), datetime(2028, 1, 1, 12, tzinfo=timezone.utc)):
        monkeypatch.setattr(tr, "_utcnow", lambda: now)
        assert tr.register_comparison(path, case, sim, enrolled_at="2026-10-27T10:00:00Z", registry_dir=registry) == first
    recovered = tmp_path / "retry" / "pair.json"
    assert tr.register_comparison(recovered, case, sim, enrolled_at="2028-01-01T10:00:00Z", registry_dir=registry) == first
    assert recovered.read_bytes() == path.read_bytes()
    changed = deepcopy(sim)
    changed["seed"] += 1
    with pytest.raises(ValueError, match="immutable"):
        tr.register_comparison(tmp_path / "fork" / "pair.json", case, changed,
                               enrolled_at="2028-01-01T10:00:00Z", registry_dir=registry)


def test_typed_constructor_independent_and_partial_write_retry(case, tmp_path, monkeypatch):
    from app.services import report_agent as ra
    monkeypatch.setattr(ra._backtest, "pipeline_for_simulation", lambda *args: pytest.fail("typed constructor owner lookup"))
    monkeypatch.setattr(ra.ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    agent = ra.ReportAgent("g", "sim_retry", case["question"], forecast_case=case)
    real_write = ra.write_json_atomic
    failed = []
    def fail_once(path, *args, **kwargs):
        if str(path).endswith("target_report.json") and not failed:
            failed.append(path)
            raise OSError("injected interrupted companion write")
        return real_write(path, *args, **kwargs)
    monkeypatch.setattr(ra, "write_json_atomic", fail_once)
    first = agent.generate_report(report_id="report_partial")
    assert first.status == ra.ReportStatus.FAILED
    second = agent.generate_report(report_id="report_partial")
    assert second.status == ra.ReportStatus.COMPLETED, second.error
    assert ra.ReportManager.publication_status(second.report_id)["publishable"]


def test_fork_has_exact_numbers_but_is_excluded_from_production_cohort(case, tmp_path, monkeypatch):
    from app.services.report_agent import ReportAgent, ReportManager, ReportStatus
    from app.services.forecast_ledger import read_published_forecast
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    report = ReportAgent("g", "sim_fork", case["question"], forecast_case=case,
        target_simulation=simulation(case), scenario_label="Intervention arm", base_simulation_id="sim_primary").generate_report(report_id="report_fork")
    assert report.status == ReportStatus.COMPLETED, report.error
    forecast = json.loads((tmp_path / "reports" / report.report_id / "forecast.json").read_text())
    assert forecast["characterization_only"] is True and forecast["record_class"] == "evaluation"
    assert [s["probability"] for s in forecast["scenarios"]] == [0.4, 0.6]
    assert forecast["binary_forecasts"][0]["probability"] == 0.6
    assert "Diagnostic fork" in report.markdown_content
    assert read_published_forecast(report.report_id) is None
    assert ReportManager.publication_status(report.report_id)["publishable"]


def test_market_health_retains_consumed_transport_receipt(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.config import Config
    from app.services import report_agent as ra
    from app.utils import prediction_markets
    agent = ra.ReportAgent.__new__(ra.ReportAgent)
    agent.simulation_id = None
    agent.llm = None
    agent._news_market_context_json = None
    agent.set_backtest_policy(None)
    payload = {"as_of": "2026-10-27T00:00:00Z", "markets": [],
               "status": {"empty_reason": "transport_failure"}}
    (tmp_path / "prediction_markets.json").write_text(json.dumps(payload))
    monkeypatch.setattr(agent, "_locate_handoff_dir", lambda: str(tmp_path))
    monkeypatch.setattr(prediction_markets, "PolymarketClient", lambda: SimpleNamespace(enabled=False))
    monkeypatch.setattr(Config, "REPORT_TOURNAMENT", False, raising=False)
    agent._prediction_markets = agent._load_prediction_markets()
    assert agent._prediction_markets_health_payload == payload
    fc = {"scenarios": [{"name": "Base", "probability": 0.6}, {"name": "Other", "probability": 0.4}],
          "binary_forecasts": []}
    result = agent._forecast_diagnostics(fc)
    assert result["inputs_health"]["markets"]["status"] == "offline"
    assert result["inputs_health"]["markets"]["as_of"] == payload["as_of"]
    assert result["inputs_health"]["provider"]["status"] == "unknown"


def test_saved_aggregation_is_used_by_legacy_manual_constructor_and_copied(monkeypatch):
    from app.services import report_agent as ra
    from app.services.forecast_aggregator import default_aggregation_policy
    policy = default_aggregation_policy()
    policy["floor"] = 0.07
    monkeypatch.setattr(ra._backtest, "pipeline_for_simulation", lambda _: {"options": {"aggregation_policy_v1": policy}})
    pinned = ra.ReportAgent._pin_aggregation_policy(None, "sim_saved", "spine")
    assert pinned == policy
    policy["floor"] = 0.12
    assert pinned["floor"] == 0.07
    invalid = default_aggregation_policy()
    invalid["weights"]["simulation"] = 0.1
    with pytest.raises(ValueError):
        ra.ReportAgent._pin_aggregation_policy(invalid, "sim_saved", "spine")


@pytest.mark.parametrize("typed", [True, False])
@pytest.mark.parametrize("stale", [True, False])
def test_report_tournament_retains_native_market_health(case, monkeypatch, typed, stale):
    from app.config import Config
    from app.services import report_agent as ra
    from app.services.forecast_aggregator import default_aggregation_policy
    monkeypatch.setattr(Config, "REPORT_TOURNAMENT", True)
    case["binaries"][0]["resolution_contract"] = {"kind": "polymarket", "market_id": "M1", "equivalence": "exact"}
    stamp = datetime.now(timezone.utc).isoformat()
    market = {"market_id": "M1", "implied_yes_prob": 0.73, "question": case["binaries"][0]["question"],
              # Explicit synthetic retained source terms make this a genuine
              # exact positive; matching only its ID/title was insufficient.
              "description": 'This market will resolve to "Yes" if worldwide security spending for the calendar year 2027 is at least USD 280 billion, as reported in the first annual release by Synthetic official statistics (https://example.test/spending). It will otherwise resolve to "No". The resolution deadline is March 30, 2028.',
              "url": "https://example.test/market", "endDate": "2028-03-30", "retrieved_at": stamp}
    payload = {"markets": [market], "as_of": stamp, "status": {"state": "stale" if stale else "fresh"},
               "cache": {"hit": stale, "stale": stale}}
    before = deepcopy(payload)
    forecast = tr.build_target_report(case, markets=payload)["forecast"]
    if typed:
        agent = ra.ReportAgent("g", "sim_health", case["question"], forecast_case=case,
            target_evidence={"schemaVersion": "target-evidence/v1", "caseHash": tr._case_api().case_hash(case),
                             "official_data": None, "markets": payload, "news_market_context": None})
    else:
        agent = ra.ReportAgent.__new__(ra.ReportAgent)
        agent._prediction_markets = [market]
        agent._prediction_markets_health_payload = payload
        agent._news_market_context_json = None
        agent._aggregation_policy = default_aggregation_policy("spine")
        forecast.pop("authority")
    result = agent._forecast_diagnostics(forecast, case=case if typed else None)
    lane = next(row for row in result["estimators"] if row["source"] == "market_implied")
    assert lane["status"] == ("unavailable" if stale else "ok")
    assert lane["binaries"] == ([] if stale else [{"id": "B1", "p": 0.73}])
    assert result["inputs_health"]["markets"]["status"] == ("stale" if stale else "fresh")
    assert result["binary_forecasts"][0]["probability"] == 0.6
    assert payload == before


@pytest.mark.parametrize("markets", [{}, {"status": "fresh"}, {"markets": None},
                                    {"markets": ["M1"]}, "M1"])
def test_invalid_market_carrier_cannot_fabricate_snapshot_rows(case, markets):
    with pytest.raises(ValueError, match="market"):
        tr.build_target_report(case, markets=markets)


def test_decision_budget_exhaustion_is_visible_without_probability_effect(case):
    from app.services.report_agent import ReportAgent
    sim = simulation(case)
    baseline = tr.build_target_report(case, sim)
    sim["decisionBudget"] = {"maximumRequests": 2, "requests": 2, "cacheHits": 3, "exhausted": True}
    result = tr.build_target_report(case, sim)
    assert result["forecast"]["scenarios"] == baseline["forecast"]["scenarios"]
    assert result["forecast"]["binary_forecasts"] == baseline["forecast"]["binary_forecasts"]
    assert result["record"]["decisionBudget"] == sim["decisionBudget"]
    assert "budget was exhausted" in result["markdown"]
    graded = ReportAgent._apply_publish_gate(result["forecast"])
    assert any("budget" in line and "zero forecast weight" in line for line in graded["quality"]["disclosures"])
    sim["decisionBudget"]["requests"] = 3
    with pytest.raises(ValueError, match="budget"):
        tr.build_target_report(case, sim)
