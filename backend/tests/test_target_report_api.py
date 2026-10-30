"""Target report HTTP consumers over sealed fixtures; never call create_app."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app.api import report as api
from app.config import Config
from app.services import pipeline_orchestrator as po, report_agent as ra
from app.services import target_pipeline as tp, target_report as tr
from app.services import forecast_tournament as ft
from app.services.forecast_aggregator import default_aggregation_policy
from app.services.forecast_library import publish_case_mechanisms
from app.services.official_data import bridge_module
from app.services.target_simulation import run_paths
from tests.test_news_context_reports import _context
from tests import test_target_pipeline as pipeline_tests


pytestmark = pytest.mark.guarded_runner

# Reuse the actual coordinator fixtures without a second orchestration harness.
case = pipeline_tests.case
execution = pipeline_tests.execution
runtime = pipeline_tests.runtime


@pytest.fixture(scope="module", autouse=True)
def record_consumer_source_hashes():
    guard = sys.modules.get("main_offline_guard")
    if guard is not None:
        for module in (api, ra, tp, tr, ft, bridge_module("forecast_case")):
            path = Path(module.__file__)
            guard.source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()


def forbidden(*args, **kwargs):
    pytest.fail("Target report API must not acquire a legacy state, client, or new enrollment")


@pytest.fixture
def target_api(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path / "simulations"))
    monkeypatch.setattr(ra.ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(Config, "REPORT_PUBLISH_GATE", True)
    fc = bridge_module("forecast_case")
    case = fc.validate_case(json.loads((Path(__file__).parent / "fixtures/target_case.json").read_text()))
    digest = fc.case_hash(case)
    state = po.PipelineState(pipeline_id="pipe_report_api", prompt=case["question"],
                             simulation_id="sim_report_api", graph_id="target_graph_pipe_report_api")
    state.handoff_dir = po.PipelineManager.handoff_dir(state.pipeline_id)
    state.options = tp.normalize_target_options(tp.AUTHORITY, {"paths": 2, "periods": 2, "seed": 7})
    state.options["target_case_binding"] = {"authority": tp.AUTHORITY, "caseId": case["caseId"],
        "caseHash": digest, "questionHash": tp._digest(state.prompt), "policyVersion": 1}
    policy = default_aggregation_policy("research")
    policy["floor"] = 0.07  # A saved non-default value must survive regeneration.
    state.options["aggregation_policy_v1"] = policy
    state.options["target_decision_budget_v1"] = {"max_calls": 128}
    state.options["safety_policy_v1"] = {"report_spine_selfconsistency_k": 1,
        "ensemble_extremize_a": 1.0, "simulation_forecast_effect": "diagnostic_only"}
    po.PipelineManager.save(state)
    handoff = Path(state.handoff_dir)
    directory = Path(Config.OASIS_SIMULATION_DATA_DIR) / state.simulation_id
    directory.mkdir(parents=True)
    fc.write_case(handoff / "forecast_case.json", case)
    (handoff / "research_report.md").write_text("Frozen fixture research")
    fc.write_case(directory / "target_case.json", case)
    library = {"schemaVersion": "target-library-context/v1", "entries": [],
               "authority": "prior_context_only"}
    publication = publish_case_mechanisms(tmp_path / "library", case)
    for name, value in (("target_library", library), ("target_library_publication", publication)):
        (handoff / (name + ".json")).write_text(json.dumps(value, allow_nan=False))
        state.options[name + "_binding"] = tp._digest(value)
    evidence = {"schemaVersion": "target-evidence/v1", "caseHash": digest,
                "official_data": {"datasets": []}, "markets": {"markets": [], "status": "offline"},
                "news_market_context": _context()}
    state.options["target_evidence_binding"] = tp._digest(evidence)
    (handoff / "target_evidence.json").write_text(json.dumps(evidence, allow_nan=False))
    typed = tr.build_target_report(case, official_data=evidence["official_data"], markets=evidence["markets"])["forecast"]
    estimators = ft.freeze_target_estimators(case, typed, policy, enabled=True)
    adversarial = next(row for row in estimators["estimators"] if row["source"] == "adversarial")
    adversarial.update(status="ok", scenario_distribution={"below": 0.2, "above": 0.8},
                       rationale="Frozen independent assessment", cruxes=["Frozen evidence crux"])
    state.options["target_estimators_binding"] = tp._digest(estimators)
    (handoff / "target_estimators.json").write_text(json.dumps(estimators, allow_nan=False))
    result = run_paths(case, **state.options["target_simulation"])

    def write(path, value):
        Path(path).write_text(json.dumps(value, allow_nan=False), encoding="utf-8")

    inputs = {"schemaVersion": "target-input/v1", "pipelineId": state.pipeline_id,
        "caseHash": digest, "simulation": state.options["target_simulation"],
        "structure": fc.simulation_projection(case), "simulationWeight": 0.0,
        "decisionBudget": state.options["target_decision_budget_v1"]}
    write(directory / "target_input.json", inputs)
    write(directory / "target_simulation.json", result)
    for stage in ("research", "prepare", "run"):
        state.stages[stage] = po.StageState(name=stage, status="completed")
        tp.record_stage(state, stage)
    monkeypatch.setattr(tr, "_utcnow", lambda: datetime(2026, 10, 27, 12, tzinfo=timezone.utc))
    registry = Path(Config.PIPELINE_DATA_DIR) / "_target_comparisons"
    registry_path = registry / (tp._digest(case["caseId"]) + ".json")
    receipt = tr.register_comparison(registry_path, case, result, enrolled_at="2026-10-27T10:00:00Z")

    def seal(name, path, value):
        write(path, value)
        manifest = po.PipelineManager.load_artifact_manifest(state.pipeline_id)
        manifest[name] = {"path": str(path), "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
        po.PipelineManager.write_artifact_manifest(state.pipeline_id, manifest)

    seal("target_comparison", directory / "target_comparison.json", receipt)
    po.PipelineManager.save(state)
    calls, completed, failures, created, pending = [], [], [], [], []
    tasks = SimpleNamespace(
        create_task=lambda **kw: created.append(kw) or "task_report_api",
        update_task=lambda *a, **kw: None,
        complete_task=lambda *a, **kw: completed.append((a, kw)),
        fail_task=lambda *a, **kw: failures.append((a, kw)),
    )
    monkeypatch.setattr(api, "TaskManager", lambda: tasks)
    class InlineThread:
        def __init__(self, target, **kwargs):
            self.target = target
        def start(self):
            self.target()
    monkeypatch.setattr(api, "threading", SimpleNamespace(Thread=InlineThread))
    real_agent = ra.ReportAgent
    def capture(**kwargs):
        calls.append(deepcopy(kwargs))
        return real_agent(**kwargs)
    monkeypatch.setattr(api, "ReportAgent", capture)
    monkeypatch.setattr(api, "SimulationManager", forbidden)
    monkeypatch.setattr(api.ProjectManager, "get_project", forbidden)
    monkeypatch.setattr(api, "load_research_dossier_for_simulation", forbidden)
    monkeypatch.setattr(api, "load_simulation_world", forbidden)
    monkeypatch.setattr(ra, "load_simulation_world", forbidden)
    monkeypatch.setattr(ra, "LLMClient", forbidden)
    monkeypatch.setattr(ra, "ZepToolsService", forbidden)
    monkeypatch.setattr(tr, "register_comparison", forbidden)
    monkeypatch.setattr(ft, "_method_lane", forbidden)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(api.report_bp, url_prefix="/api/report")
    return SimpleNamespace(client=app.test_client(), state=state, root=tmp_path, directory=directory,
        handoff=handoff, case=case, result=result, inputs=inputs, policy=policy, receipt=receipt,
        estimators=estimators, evidence=evidence,
        registry_path=registry_path, write=write, seal=seal, calls=calls, completed=completed,
        failures=failures, created=created, pending=pending)


def post(a, endpoint="generate", **extra):
    return a.client.post("/api/report/" + endpoint,
                         json={"simulation_id": a.state.simulation_id, "message": "Explain", **extra})


def snapshot(a):
    return {str(p): p.read_bytes() for root in (a.handoff, a.directory, a.registry_path.parent)
            for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("native_market", [False, True])
def test_actual_pipeline_then_manual_replay_preserves_saved_inputs_and_lanes(execution, monkeypatch, enabled, native_market):
    monkeypatch.setattr(Config, "REPORT_TOURNAMENT", enabled)
    payload = None
    if native_market:
        execution.case["binaries"][0]["resolution_contract"] = {
            "kind": "polymarket", "market_id": "M1", "equivalence": "exact"}
        stamp = datetime.now(timezone.utc).isoformat()
        payload = {"markets": [{"market_id": "M1", "implied_yes_prob": 0.73,
            "question": execution.case["binaries"][0]["question"], "url": "https://example.test/market",
            "endDate": "2027-12-31", "retrieved_at": stamp}],
            "as_of": stamp, "status": {"state": "fresh", "cache_hit": False, "stale": False, "as_of": stamp},
            "cache": {"hit": False, "stale": False, "age_seconds": 0}}
        original_research = execution.po.DeerFlowResearchRunner.run
        def research(*args, **kwargs):
            response = original_research(*args, **kwargs)
            (Path(args[1]) / "prediction_markets.json").write_text(json.dumps(payload))
            return response
        monkeypatch.setattr(execution.po.DeerFlowResearchRunner, "run", research)
    state = pipeline_tests._execute(execution)
    assert state.status == "completed", state.error
    assert state.options["target_tournament_enabled"] is enabled
    folder = Path(ra.ReportManager._get_report_folder(state.report_id))
    original = json.loads((folder / "forecast.json").read_text())
    if native_market:
        assert original["binary_forecasts"][0]["probability"] == 0.6
        assert "market_anchor" not in original["binary_forecasts"][0]
        assert original["binary_forecasts"][0]["resolution_contract"]["kind"] == "named_source_event"
        assert original["binary_forecasts"][0]["market_equivalence"]["status"] == "unavailable"
        assert json.loads((folder / "target_evidence.json").read_text())["markets"] == payload
        assert original["inputs_health"]["markets"]["status"] == "fresh"
        assert original["inputs_health"]["markets"]["as_of"] == payload["as_of"]
    inputs_path = Path(Config.OASIS_SIMULATION_DATA_DIR) / state.simulation_id / "target_input.json"
    inputs = json.loads(inputs_path.read_text())
    assert inputs["decisionBudget"] == state.options["target_decision_budget_v1"]
    before = {str(p): p.read_bytes() for root in
              (Path(state.handoff_dir), inputs_path.parent, Path(Config.PIPELINE_DATA_DIR) / "_target_comparisons")
              for p in root.rglob("*") if p.is_file()}
    owner = po.PipelineManager.load(state.pipeline_id)
    completed, failures = [], []
    tasks = SimpleNamespace(create_task=lambda **kw: "task_manual_pipeline",
        update_task=lambda *a, **kw: None,
        complete_task=lambda *a, **kw: completed.append((a, kw)),
        fail_task=lambda *a, **kw: failures.append((a, kw)))
    monkeypatch.setattr(api, "TaskManager", lambda: tasks)
    class InlineThread:
        def __init__(self, target, **kwargs):
            self.target = target
        def start(self):
            self.target()
    monkeypatch.setattr(api, "threading", SimpleNamespace(Thread=InlineThread))
    for name in ("SimulationManager", "load_research_dossier_for_simulation", "load_simulation_world"):
        monkeypatch.setattr(api, name, forbidden)
    for name in ("LLMClient", "ZepToolsService", "load_simulation_world"):
        monkeypatch.setattr(ra, name, forbidden)
    monkeypatch.setattr(ft, "_method_lane", forbidden)
    monkeypatch.setattr(tr, "register_comparison", forbidden)
    monkeypatch.setattr(Config, "REPORT_TOURNAMENT", not enabled)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(api.report_bp, url_prefix="/api/report")
    client = app.test_client()
    cached = client.post("/api/report/generate", json={"simulation_id": state.simulation_id})
    assert cached.status_code == 200, cached.json
    assert cached.json["data"]["report_id"] == state.report_id
    forced = client.post("/api/report/generate", json={"simulation_id": state.simulation_id, "force_regenerate": True})
    assert forced.status_code == 200, forced.json
    assert len(completed) == 1 and not failures, failures
    new_id = forced.json["data"]["report_id"]
    assert new_id != state.report_id and ra.ReportManager.publication_status(new_id)["publishable"]
    regenerated = json.loads((Path(ra.ReportManager._get_report_folder(new_id)) / "forecast.json").read_text())
    for key in ("scenarios", "binary_forecasts", "estimators", "aggregation"):
        assert regenerated[key] == original[key], key
    if native_market:
        assert json.loads((Path(ra.ReportManager._get_report_folder(new_id)) / "target_evidence.json").read_text())["markets"] == payload
    assert po.PipelineManager.load(state.pipeline_id) == owner
    assert all(Path(path).read_bytes() == raw for path, raw in before.items())


def test_normal_generate_then_cache_then_force_regenerate_preserves_frozen_producers(target_api):
    a = target_api
    before = snapshot(a)
    first = post(a)
    assert first.status_code == 200, first.json
    old_id = first.json["data"]["report_id"]
    assert len(a.completed) == 1 and not a.failures, a.failures
    assert ra.ReportManager.publication_status(old_id)["publishable"]
    assert not (a.directory / "state.json").exists()
    assert a.calls[0]["forecast_case"] == a.case
    assert a.calls[0]["target_simulation"] == a.result
    assert a.calls[0]["aggregation_policy"] == a.policy
    assert a.calls[0]["saved_estimators"] == a.estimators
    assert a.calls[0]["target_evidence"] == a.evidence
    assert a.calls[0]["report_policy"] == a.state.options["safety_policy_v1"]
    cached = post(a)
    assert cached.status_code == 200 and cached.json["data"]["already_generated"] is True
    assert cached.json["data"]["report_id"] == old_id and len(a.calls) == 1
    # A primary report remains referenced by the pipeline's immutable stage receipt.
    a.state.report_id = old_id
    tp.record_stage(a.state, "report")
    po.PipelineManager.save(a.state)
    before = snapshot(a)
    forced = post(a, force_regenerate=True, aggregation_policy={"method": "weighted_log_odds"})
    assert forced.status_code == 200, forced.json
    new_id = forced.json["data"]["report_id"]
    assert new_id != old_id and len(a.completed) == 2 and not a.failures
    assert (Path(ra.ReportManager.REPORTS_DIR) / old_id).exists()
    assert tp.validate_stage(a.state, "report")
    forecast = json.loads((Path(ra.ReportManager.REPORTS_DIR) / new_id / "forecast.json").read_text())
    assert forecast["authority"] == "target-first-v1"
    assert [row["probability"] for row in forecast["scenarios"]] == [0.4, 0.6]
    assert forecast["aggregation"]["policy"] == a.policy
    assert [row for row in forecast["estimators"] if row["source"] != "simulation"] == a.estimators["estimators"]
    assert json.loads((Path(ra.ReportManager.REPORTS_DIR) / new_id / "target_estimators.json").read_text()) == a.estimators
    assert json.loads((Path(ra.ReportManager.REPORTS_DIR) / new_id / "target_evidence.json").read_text()) == a.evidence
    assert snapshot(a) == before


def test_chat_returns_structured_unsupported_without_legacy_state(target_api):
    a = target_api
    before = snapshot(a)
    response = post(a, "chat")
    assert response.status_code == 409
    assert response.json["code"] == "target_report_chat_unsupported"
    assert response.json["forecast_authority"] == tp.AUTHORITY
    assert not a.calls and not a.created and snapshot(a) == before


def test_failed_first_report_reuses_enrollment_before_report_stage_seal(target_api):
    a = target_api
    manifest = po.PipelineManager.load_artifact_manifest(a.state.pipeline_id)
    del manifest["target_comparison"]
    po.PipelineManager.write_artifact_manifest(a.state.pipeline_id, manifest)
    a.state.stages["report"] = po.StageState(name="report", status="failed")
    po.PipelineManager.save(a.state)
    before = snapshot(a)
    response = post(a, force_regenerate=True)
    assert response.status_code == 200, response.json
    assert len(a.completed) == 1 and not a.failures, a.failures
    assert ra.ReportManager.publication_status(response.json["data"]["report_id"])["publishable"]
    assert snapshot(a) == before  # No fresh enrollment, timestamp, or producer seal.


def test_existing_comparison_seal_cannot_be_bypassed_on_failed_retry(target_api):
    a = target_api
    manifest = po.PipelineManager.load_artifact_manifest(a.state.pipeline_id)
    manifest["target_comparison"]["sha256"] = "0" * 64
    po.PipelineManager.write_artifact_manifest(a.state.pipeline_id, manifest)
    a.state.stages["report"] = po.StageState(name="report", status="failed")
    po.PipelineManager.save(a.state)
    response = post(a, force_regenerate=True)
    assert response.status_code == 409 and response.json["code"] == "target_report_integrity"
    assert not a.calls and not a.created


@pytest.mark.parametrize("endpoint", ["generate", "chat"])
@pytest.mark.parametrize("stage", ["research", "prepare", "run"])
def test_stage_manifest_required_before_any_target_consumer(target_api, endpoint, stage):
    a = target_api
    name, path = tp.stage_specs(a.state, stage)[0]
    Path(path).write_text(Path(path).read_text() + "\n")
    response = post(a, endpoint)
    assert response.status_code == 409 and response.json["code"] == "target_report_integrity"
    assert not a.calls and not a.created


@pytest.mark.parametrize("mutation", ["missing-hash", "wrong-hash", "missing-policy", "null-policy",
    "wrong-policy", "weighted-policy", "missing-manifest", "pending-run", "missing-owner",
    "missing-authority", "wrong-engine", "wrong-question", "wrong-graph", "wrong-handoff",
    "missing-comparison", "comparison-hash", "registry-changed", "missing-registry", "missing-settings"])
def test_damaged_target_cannot_fall_back_or_dispatch(target_api, mutation):
    a = target_api
    if mutation == "missing-hash":
        del a.state.options["target_case_binding"]["caseHash"]
    elif mutation == "wrong-hash":
        a.state.options["target_case_binding"]["caseHash"] = "0" * 64
    elif mutation == "missing-policy":
        del a.state.options["aggregation_policy_v1"]
    elif mutation == "null-policy":
        a.state.options["aggregation_policy_v1"] = None
    elif mutation == "wrong-policy":
        a.state.options["aggregation_policy_v1"] = default_aggregation_policy("spine")
    elif mutation == "weighted-policy":
        a.state.options["aggregation_policy_v1"]["method"] = "weighted_log_odds"
    elif mutation == "pending-run":
        a.state.stages["run"].status = "pending"
    elif mutation == "missing-authority":
        del a.state.options["forecast_authority"]
    elif mutation == "wrong-engine":
        a.state.options["simulation_engine"] = "oasis-legacy"
    elif mutation == "missing-settings":
        del a.state.options["target_simulation"]["seed"]
    elif mutation == "wrong-question":
        a.state.prompt = "Different question"
    elif mutation == "wrong-graph":
        a.state.graph_id = "graph_legacy"
    elif mutation == "wrong-handoff":
        a.state.handoff_dir = str(a.root / "other")
    elif mutation == "missing-comparison":
        (a.directory / "target_comparison.json").unlink()
    elif mutation == "comparison-hash":
        a.receipt["simulationHash"] = "0" * 64
        a.seal("target_comparison", a.directory / "target_comparison.json", a.receipt)
    elif mutation == "registry-changed":
        a.write(a.registry_path, {**a.receipt, "enrolledAt": "2026-10-26T10:00:00Z"})
    elif mutation == "missing-registry":
        a.registry_path.unlink()
    po.PipelineManager.save(a.state)
    if mutation == "missing-manifest":
        Path(po.PipelineManager.artifact_manifest_path(a.state.pipeline_id)).unlink()
    elif mutation == "missing-owner":
        Path(po.PipelineManager.state_path(a.state.pipeline_id)).unlink()
    response = post(a, force_regenerate=True)
    assert response.status_code == 409, response.json
    assert response.json["code"] == "target_report_integrity"
    assert not a.calls and not a.created


@pytest.mark.parametrize("mutation", ["case", "result-case", "result-hash", "result-weight", "input",
                                     "input-budget-missing", "input-budget-mismatch"])
def test_resealed_mismatched_inputs_are_rejected(target_api, mutation):
    a = target_api
    if mutation == "case":
        a.case["question"] += " altered"
        a.seal("target_case", a.directory / "target_case.json", a.case)
    elif mutation.startswith("input"):
        if mutation == "input-budget-missing":
            del a.inputs["decisionBudget"]
        elif mutation == "input-budget-mismatch":
            a.inputs["decisionBudget"]["max_calls"] = 1
        else:
            a.inputs["pipelineId"] = "pipe_other"
        a.seal("target_input", a.directory / "target_input.json", a.inputs)
    else:
        a.result[{"result-case": "caseId", "result-hash": "caseHash", "result-weight": "simulationWeight"}[mutation]] = (
            0.1 if mutation == "result-weight" else "wrong")
        a.seal("target_simulation", a.directory / "target_simulation.json", a.result)
    response = post(a)
    assert response.status_code == 409 and response.json["code"] == "target_report_integrity"
    assert not a.calls and not a.created


def test_cached_report_does_not_bypass_required_input_validation(target_api, monkeypatch):
    a = target_api
    monkeypatch.setattr(api.ReportManager, "get_report_by_simulation", forbidden)
    del a.state.options["target_case_binding"]["caseHash"]
    po.PipelineManager.save(a.state)
    assert post(a).status_code == 409


def test_worker_uses_detached_inputs_and_policy(target_api, monkeypatch):
    a = target_api
    class ParkedThread:
        def __init__(self, target, **kwargs):
            a.pending.append(target)
        def start(self):
            pass
    monkeypatch.setattr(api, "threading", SimpleNamespace(Thread=ParkedThread))
    response = post(a)
    assert response.status_code == 200 and len(a.pending) == 1
    a.state.options["aggregation_policy_v1"]["floor"] = 0.4
    po.PipelineManager.save(a.state)
    a.case["binaries"][0]["probability"] = 0.9
    a.write(a.directory / "target_case.json", a.case)
    a.write(a.handoff / "target_estimators.json", {})
    a.write(a.handoff / "target_evidence.json", {})
    a.pending[0]()
    assert not a.failures and len(a.completed) == 1
    assert a.calls[0]["aggregation_policy"]["floor"] == 0.07
    assert a.calls[0]["forecast_case"]["binaries"][0]["probability"] == 0.6
    assert a.calls[0]["saved_estimators"] == a.estimators
    assert a.calls[0]["target_evidence"] == a.evidence


def test_target_fork_forwards_original_scenario_and_base_simulation(target_api):
    a = target_api
    base = po.PipelineState(pipeline_id="pipe_baseline", prompt=a.case["question"], simulation_id="sim_baseline")
    po.PipelineManager.save(base)
    a.state.options.update(base_pipeline_id=base.pipeline_id, scenario_label="Capacity stress")
    receipt = {"schemaVersion": "target-comparison/v1", "status": "diagnostic_fork",
        "caseId": a.case["caseId"], "caseHash": bridge_module("forecast_case").case_hash(a.case),
        "basePipelineId": base.pipeline_id, "simulationHash": tp._digest(a.result), "productionEligible": False}
    a.seal("target_comparison", a.directory / "target_comparison.json", receipt)
    po.PipelineManager.save(a.state)
    before = snapshot(a)
    response = post(a)
    assert response.status_code == 200 and len(a.calls) == 1 and not a.failures
    assert a.calls[0]["scenario_label"] == "Capacity stress"
    assert a.calls[0]["base_simulation_id"] == "sim_baseline"
    assert a.calls[0]["aggregation_policy"] == a.policy
    assert a.calls[0]["saved_estimators"] == a.estimators
    assert a.calls[0]["target_evidence"] == a.evidence
    report_id = response.json["data"]["report_id"]
    assert ra.ReportManager.publication_status(report_id)["publishable"]
    forecast = json.loads((Path(ra.ReportManager.REPORTS_DIR) / report_id / "forecast.json").read_text())
    assert forecast["characterization_only"] is True and forecast["record_class"] == "evaluation"
    assert snapshot(a) == before


@pytest.mark.parametrize("name", ["target_case", "target_simulation", "target_comparison"])
def test_target_artifact_symlink_is_rejected(target_api, name):
    a = target_api
    path = a.directory / (name + ".json")
    original = a.directory / (name + "-original.json")
    path.rename(original)
    path.symlink_to(original)
    response = post(a)
    assert response.status_code == 409 and response.json["code"] == "target_report_integrity"
    assert not a.calls and not a.created


@pytest.mark.parametrize("mutation", ["missing", "missing-binding", "binding", "unsealed", "tampered",
    "case", "policy", "authority", "proposition", "symlink"])
def test_saved_estimators_require_bytes_binding_and_consumer_identity(target_api, mutation):
    a = target_api
    path = a.handoff / "target_estimators.json"
    if mutation == "missing":
        path.unlink()
    elif mutation == "missing-binding":
        del a.state.options["target_estimators_binding"]
    elif mutation == "binding":
        a.state.options["target_estimators_binding"] = "0" * 64
    elif mutation == "unsealed":
        manifest = po.PipelineManager.load_artifact_manifest(a.state.pipeline_id)
        del manifest["target_estimators"]
        po.PipelineManager.write_artifact_manifest(a.state.pipeline_id, manifest)
    elif mutation == "tampered":
        path.write_text(path.read_text() + "\n")
    elif mutation == "symlink":
        original = a.handoff / "estimators-original.json"
        path.rename(original)
        path.symlink_to(original)
    else:
        if mutation in {"case", "policy"}:
            a.estimators[mutation + "_hash"] = "0" * 64
        elif mutation == "authority":
            a.estimators["estimators"][0]["scenario_distribution"] = {"below": 0.1, "above": 0.9}
        else:
            shadow = next(row for row in a.estimators["estimators"] if row["source"] == "adversarial")
            shadow["binaries"] = [{"id": "unknown_binary", "p": 0.5}]
        a.seal("target_estimators", path, a.estimators)
        a.state.options["target_estimators_binding"] = tp._digest(a.estimators)
    po.PipelineManager.save(a.state)
    response = post(a)
    assert response.status_code == 409 and response.json["code"] == "target_report_integrity"
    if mutation == "proposition":
        assert "proposition identities mismatch" in response.json["error"]
    assert not a.calls and not a.created


@pytest.mark.parametrize("mutation", ["missing", "missing-binding", "binding", "unsealed", "tampered",
                                     "case", "schema", "news", "symlink"])
def test_target_evidence_requires_manifest_hash_and_case_binding(target_api, mutation):
    a = target_api
    path = a.handoff / "target_evidence.json"
    if mutation == "missing":
        path.unlink()
    elif mutation == "missing-binding":
        del a.state.options["target_evidence_binding"]
    elif mutation == "binding":
        a.state.options["target_evidence_binding"] = "0" * 64
    elif mutation == "unsealed":
        manifest = po.PipelineManager.load_artifact_manifest(a.state.pipeline_id)
        del manifest["target_evidence"]
        po.PipelineManager.write_artifact_manifest(a.state.pipeline_id, manifest)
    elif mutation == "tampered":
        path.write_text(path.read_text() + "\n")
    elif mutation == "symlink":
        original = a.handoff / "evidence-original.json"
        path.rename(original)
        path.symlink_to(original)
    else:
        if mutation == "case":
            a.evidence["caseHash"] = "0" * 64
        elif mutation == "schema":
            a.evidence["schemaVersion"] = "target-evidence/v0"
        else:
            a.evidence["news_market_context"]["sha256"] = "0" * 64
        a.seal("target_evidence", path, a.evidence)
        a.state.options["target_evidence_binding"] = tp._digest(a.evidence)
    po.PipelineManager.save(a.state)
    response = post(a)
    assert response.status_code == 409 and response.json["code"] == "target_report_integrity"
    assert not a.calls and not a.created


@pytest.mark.parametrize("endpoint", ["generate", "chat"])
def test_legacy_calls_preserve_dossier_and_owner_context(tmp_path, monkeypatch, endpoint):
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path))
    owner = {"prompt": "Owner question", "options": {"scenario_label": "Legacy scenario"}}
    monkeypatch.setattr(api, "pipeline_for_simulation", lambda sid: owner)
    monkeypatch.setattr(api, "load_simulation_world", lambda sid: None)
    monkeypatch.setattr(api, "SimulationManager", lambda: SimpleNamespace(
        get_simulation=lambda sid: SimpleNamespace(project_id="project_legacy", graph_id="graph_legacy")))
    monkeypatch.setattr(api.ProjectManager, "get_project", lambda pid: SimpleNamespace(
        graph_id="graph_project", simulation_requirement="Project question"))
    monkeypatch.setattr(api, "load_research_dossier_for_simulation", lambda sid: {
        "research_report": "Legacy research", "report_artifacts": {"quantitative": [{"value": 3}]}})
    calls = []
    def capture(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(chat=lambda **kw: {"response": "Legacy answer"})
    monkeypatch.setattr(api, "ReportAgent", capture)
    if endpoint == "generate":
        monkeypatch.setattr(api.ReportManager, "get_report_by_simulation", lambda sid: SimpleNamespace(
            status=ra.ReportStatus.COMPLETED, report_id="report_legacy"))
        monkeypatch.setattr(api.ReportManager, "is_publishable", lambda rid: True)
    app = Flask(__name__)
    app.register_blueprint(api.report_bp, url_prefix="/api/report")
    response = app.test_client().post("/api/report/" + endpoint,
        json={"simulation_id": "sim_legacy", "message": "Explain"})
    assert response.status_code == 200, response.json
    if endpoint == "chat":
        assert response.json["data"]["response"] == "Legacy answer"
        assert calls[0]["simulation_requirement"] == "Owner question"
        assert calls[0]["research_report"] == "Legacy research"
        assert calls[0]["quantitative"] == [{"value": 3}]
        assert calls[0]["scenario_label"] == "Legacy scenario"
        assert "forecast_case" not in calls[0]
    else:
        assert response.json["data"]["already_generated"] is True and not calls
