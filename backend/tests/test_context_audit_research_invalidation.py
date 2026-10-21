"""Research-generation invalidation through the real parent lifecycle.

Reuse the existing prepare/run resume harness. Research and graph acquisition,
persona storage and simulator responses are scripted; real research contracts,
ontology generation, simulation-config generation/model prompts, stage dispatch,
reuse checks, config sealing and research bindings remain production code.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import test_orchestrator_research_wiring as wiring
from app.models.project import Project, ProjectStatus
from app.models.task import TaskManager
from app.services import pipeline_orchestrator as po
from app.services import simulation_config_generator as config_module
from app.services.official_data import bind_simulation_research, capture_research_generation
from app.services.ontology_generator import OntologyGenerator
from app.services.report_agent import Report
from app.services.simulation_manager import build_simulation_config_seal
from app.services.zep_entity_reader import EntityNode


def _record_source_hashes():
    guard = sys.modules.get("main_offline_guard")
    if guard is None:
        return
    root = Path(__file__).resolve().parents[2]
    for relative in (
        "backend/app/services/pipeline_orchestrator.py",
        "backend/app/services/ontology_generator.py",
        "backend/app/services/simulation_config_generator.py",
        "backend/app/services/simulation_manager.py",
        "backend/app/services/official_data.py",
        "backend/app/models/project.py",
        "backend/tests/test_orchestrator_research_wiring.py",
    ):
        path = root / relative
        guard.source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()


_record_source_hashes()


def _report(generation):
    return f"RESEARCH-{generation}: permit capacity is {45 if generation == 'G1' else 95} MW. " * 30


def _actors(generation):
    return {"as_of_date": "2026-07-12", "central_question": "Forecast EV permits through 2035",
            "situation_brief": {"current_situation": f"RESEARCH-{generation} permit conditions.",
                                "fault_lines": [f"RESEARCH-{generation} capacity"]},
            "actors": [{"name": "EV OEM", "type": "Company", "memory": f"RESEARCH-{generation}"}],
            "relationships": []}


def _drive(monkeypatch, tmp_path, *, damage=None, reset_derived_control=False):
    real_run = po.PipelineOrchestrator._run
    real_finalize = po._finalize_research_contract
    real_get_project = po.ProjectManager.get_project
    real_generator = config_module.SimulationConfigGenerator
    observed = {"research": [], "ontology": [], "prepare": [], "graph": [], "report": []}
    proof = {}

    def enter(cls, state):
        # The established fixture has now prepared valid old PREPARE/RUN
        # artifacts. Extend its setup at the one entry into the real _run.
        handoff = Path(state.handoff_dir)
        manager = po.SimulationManager()
        monkeypatch.setattr(po, "_finalize_research_contract", real_finalize)
        monkeypatch.setattr(po.ProjectManager, "get_project", real_get_project)
        monkeypatch.setattr(po.ProjectManager, "PROJECTS_DIR", str(tmp_path / "projects"))
        for key, value in {"RESEARCH_ENGINE": "v3", "RESEARCH_PARALLEL_TRACKS": 1,
                           "GRAPH_SEED_FROM_ACTORS": False, "GRAPH_BUILD_CONCURRENCY": 1,
                           "SIM_AUDIENCE_AGENTS": 0, "SIM_AUDIENCE_SIZE": 0,
                           "SIM_ECHO_CHAMBER_ENABLED": False, "PIPELINE_VALIDATE_ARTIFACTS": True,
                           "SIM_MARKET_PRIORS": False}.items():
            monkeypatch.setattr(po.Config, key, value, raising=False)

        def publish(generation):
            (handoff / "research_report.md").write_text(_report(generation))
            (handoff / "actors.json").write_text(json.dumps(_actors(generation)))
            (handoff / "sources.json").write_text("[]")
            (handoff / "meta.json").write_text(json.dumps({"status": "completed", "depth": "standard",
                                                         "question": state.prompt, "generation": generation}))
            po._promote_research_contract(str(handoff), str(handoff))
            return po._load_research_handoff(str(handoff))

        class OntologyModel:
            def chat_json(self, messages, **kwargs):
                observed["ontology"].append(messages)
                marker = "G2" if "RESEARCH-G2" in messages[-1]["content"] else "G1"
                return {"entity_types": [{"name": "Company", "description": "Decision-maker",
                                           "attributes": []}], "edge_types": [],
                        "analysis_summary": f"RESEARCH-{marker}"}

        class ConfigModel:
            def __init__(self, **kwargs):
                self.provider, self.model = "scripted", "config-probe"

            def chat(self, messages, **kwargs):
                observed["prepare"].append(messages)
                marker = "G2" if "RESEARCH-G2" in messages[-1]["content"] else "G1"
                return json.dumps({"hot_topics": [f"RESEARCH-{marker}"],
                                   "initial_posts": [{"content": f"RESEARCH-{marker} permit conditions",
                                                      "poster_agent_id": 0}],
                                   "agent_configs": [{"agent_id": 0, "name": "EV OEM"}]})

        monkeypatch.setattr(po, "OntologyGenerator", lambda: OntologyGenerator(llm_client=OntologyModel()))
        monkeypatch.setattr(config_module, "LLMClient", ConfigModel)
        entity = EntityNode(uuid="actor-oem", name="EV OEM", labels=["Company"],
                            summary="Permit decision-maker", attributes={})

        def native_config(simulation_id, report, actors, graph_id):
            params = real_generator(provider="scripted").generate_config(
                simulation_id=simulation_id, project_id="proj", graph_id=graph_id,
                simulation_requirement=state.prompt, document_text=report, entities=[entity],
                actors=actors, max_rounds=9, research_language="English")
            return params.to_dict()

        publish("G1")
        project = Project(project_id="proj", name="Permit project", status=ProjectStatus.GRAPH_COMPLETED,
                          created_at="2026-07-12T00:00:00Z", updated_at="2026-07-12T00:00:00Z",
                          ontology=po.OntologyGenerator().generate([_report("G1")], state.prompt,
                                                                  actors=_actors("G1")), graph_id="graph")
        Path(po.ProjectManager.PROJECTS_DIR, "proj").mkdir(parents=True)
        po.ProjectManager.save_project(project)
        po.ProjectManager.save_extracted_text(project.project_id, _report("G1"))
        (handoff / "ontology.json").write_text(json.dumps(project.ontology))
        old_config_path = tmp_path / "simulations/sim_old/simulation_config.json"
        old_config_path.write_text(json.dumps(native_config("sim_old", _report("G1"), _actors("G1"), "graph")))
        old_sim = manager.get_simulation("sim_old")
        old_sim.simulation_config_sha256, old_sim.simulation_config_manifest_sha256 = build_simulation_config_seal(
            str(old_config_path.parent), simulation_id="sim_old", actor_cast_manifest_sha256=None,
            actor_context_manifest_sha256=None, actor_role_manifest_sha256={})
        bind_simulation_research("sim_old", str(handoff), pipeline_id=state.pipeline_id,
                                 expected_generation=capture_research_generation(str(handoff)))
        manifest = po.PipelineManager.load_artifact_manifest(state.pipeline_id)
        for stage in (po.STAGE_RESEARCH, po.STAGE_ONTOLOGY, po.STAGE_PREPARE):
            for name, path in po.PipelineOrchestrator._stage_artifact_specs(state, stage):
                if Path(path).is_file():
                    entry = po._manifest_entry_for(name, path, stage)
                    if entry is not None:
                        manifest[name] = entry
        po.PipelineManager.write_artifact_manifest(state.pipeline_id, manifest)
        state.task_id = TaskManager().create_task("research-invalidation-G1")
        _, _, old_epoch = po._activate_research_budget_epoch(state, str(handoff))
        state.task_id = TaskManager().create_task("research-invalidation-resume")
        proof.update(old_epoch=old_epoch, old_graph=state.graph_id, old_simulation=state.simulation_id,
                     old_config_sha256=hashlib.sha256(old_config_path.read_bytes()).hexdigest(),
                     old_generation=capture_research_generation(str(handoff)))
        # Baseline artifacts came from the real consumer methods above. Observe
        # only new calls during the resume, not fixture construction calls.
        observed["ontology"].clear()
        observed["prepare"].clear()

        def research_producer(prompt, handoff_dir, **kwargs):
            observed["research"].append({"epoch": kwargs["budget_epoch"], "prompt": prompt})
            result = publish("G2")
            result["research_telemetry"] = {}
            return result

        monkeypatch.setattr(po.DeerFlowResearchRunner, "run", staticmethod(research_producer))

        class GraphResponses:
            last_ingest_stats = None

            def set_ontology(self, graph_id, ontology):
                pass

            def create_graph(self, name):
                return "graph_G2"

            def add_text_batches(self, graph_id, chunks, **kwargs):
                observed["graph"].append({"graph_id": graph_id, "chunks": chunks})
                return ["episode-G2"]

            def _wait_for_episodes(self, uuids, progress_callback):
                pass

            def _get_graph_info(self, graph_id):
                return SimpleNamespace(node_count=1, edge_count=0, components=1, centrality={})

        monkeypatch.setattr(po, "GraphBuilderService", lambda **kwargs: GraphResponses())
        report_root = tmp_path / "reports"
        monkeypatch.setattr(po.ReportManager, "REPORTS_DIR", str(report_root))
        monkeypatch.setattr(po.ReportManager, "_get_report_folder", classmethod(
            lambda cls, report_id: str(report_root / report_id)))

        class ReportProducer:
            """External report generation only; parent adoption/gates stay real."""

            def __init__(self, **kwargs):
                self.inputs = kwargs
                observed["report"].append({"constructor": kwargs, "report_id": None})

            def generate_report(self, *, report_id, progress_callback=None):
                observed["report"][-1]["report_id"] = report_id
                if progress_callback:
                    progress_callback("writing", 95, "Scripted completed publication")
                return Report(
                    report_id=report_id,
                    simulation_id=self.inputs["simulation_id"],
                    graph_id=self.inputs["graph_id"],
                    simulation_requirement=self.inputs["simulation_requirement"],
                    status=po.ReportStatus.COMPLETED,
                    markdown_content="## Permit forecast\n\n" + self.inputs["research_report"],
                )

        monkeypatch.setattr(po, "ReportAgent", ReportProducer)
        fixture_prepare = manager.prepare_simulation

        def prepare_consumer(simulation_id, **kwargs):
            config = native_config(simulation_id, kwargs["document_text"], kwargs["actors"], state.graph_id)
            fixture_prepare(simulation_id, **kwargs)
            path = tmp_path / "simulations" / simulation_id / "simulation_config.json"
            path.write_text(json.dumps(config))
            manager.reseal_simulation_config(simulation_id)
            return manager.get_simulation(simulation_id)

        monkeypatch.setattr(manager, "prepare_simulation", prepare_consumer)
        if damage == "report_changed":
            (handoff / "research_report.md").write_text(_report("G1") + "Changed outside the current contract.")
        elif damage == "report_missing":
            (handoff / "research_report.md").unlink()
        elif damage == "contract_and_report_missing":
            Path(po._research_contract_path(str(handoff))).unlink()
            (handoff / "research_report.md").unlink()
        elif damage == "contract_changed":
            contract_path = Path(po._research_contract_path(str(handoff)))
            contract = json.loads(contract_path.read_text())
            contract["files"]["research_report.md"]["sha256"] = "0" * 64
            contract_path.write_text(json.dumps(contract))
        if reset_derived_control:
            # Positive mechanism control only: demonstrate that these real
            # consumers see G2 when the derived attempts are explicitly reset.
            project.ontology = None
            project.graph_id = None
            po.ProjectManager.save_project(project)
            state.graph_id = None
            state.simulation_id = None
            for stage in (po.STAGE_ONTOLOGY, po.STAGE_GRAPH, po.STAGE_PREPARE, po.STAGE_RUN):
                po._reset_stage_attempt(state.stages[stage])
        real_run(state)
        proof.update(status=state.status, error=state.error,
                     epoch=state.options.get("research_budget_epoch", {}).get("epoch"),
                     project_id=state.project_id, graph_id=state.graph_id,
                     simulation_id=state.simulation_id, report_id=state.report_id,
                     report_generation="G2" if "RESEARCH-G2" in (handoff / "research_report.md").read_text() else "G1",
                     ontology_summary=po.ProjectManager.get_project(state.project_id).ontology.get("analysis_summary"),
                     prepared_config=json.loads((tmp_path / "simulations" / state.simulation_id / "simulation_config.json").read_text()),
                     old_config_unchanged=hashlib.sha256(old_config_path.read_bytes()).hexdigest() == proof["old_config_sha256"],
                     calls=observed)
        (tmp_path / "research-invalidation-observed.json").write_text(json.dumps(proof, indent=2, ensure_ascii=False))

    monkeypatch.setattr(po.PipelineOrchestrator, "_run", classmethod(enter))
    wiring._exercise_prepare_run_resume(monkeypatch, tmp_path, rebuild_prepare=False)
    return proof


def test_matching_research_generation_reuses_derived_consumers_read_only(monkeypatch, tmp_path):
    proof = _drive(monkeypatch, tmp_path)
    assert proof["status"] == "completed", proof["error"]
    assert proof["calls"] == {"research": [], "ontology": [], "prepare": [], "graph": [], "report": []}
    assert proof["epoch"] == proof["old_epoch"]
    assert proof["graph_id"] == proof["old_graph"] and proof["simulation_id"] == proof["old_simulation"]
    assert proof["old_config_unchanged"]
    assert proof["report_id"] == "report_existing"


@pytest.mark.parametrize("damage", ["report_changed", "report_missing", "contract_changed", "contract_and_report_missing"])
@pytest.mark.parametrize("reset_derived_control", [False, True])
def test_reconstructed_research_reaches_new_ontology_graph_and_prepare_attempts(
        monkeypatch, tmp_path, damage, reset_derived_control):
    proof = _drive(monkeypatch, tmp_path, damage=damage, reset_derived_control=reset_derived_control)
    assert proof["status"] == "completed", proof["error"]
    assert proof["report_generation"] == "G2" and len(proof["calls"]["research"]) == 1
    failures = []
    if not proof["calls"]["ontology"] or not all("RESEARCH-G2" in call[-1]["content"] for call in proof["calls"]["ontology"]):
        failures.append("ontology consumer did not receive G2")
    if not proof["calls"]["prepare"] or not any("RESEARCH-G2" in call[-1]["content"] for call in proof["calls"]["prepare"]):
        failures.append("prepare config model did not receive G2")
    if not proof["calls"]["graph"] or "RESEARCH-G2" not in json.dumps(proof["calls"]["graph"]):
        failures.append("graph ingestion did not receive G2")
    if proof["epoch"] == proof["old_epoch"]:
        failures.append("research epoch did not change")
    if proof["graph_id"] == proof["old_graph"] or proof["simulation_id"] == proof["old_simulation"]:
        failures.append("graph/simulation attempt identity was reused")
    if "RESEARCH-G2" not in json.dumps(proof["prepared_config"]):
        failures.append("persisted simulation config still consumes G1")
    report_calls = proof["calls"]["report"]
    if len(report_calls) != 1:
        failures.append("replacement report producer was not invoked exactly once")
    else:
        inputs = report_calls[0]["constructor"]
        if ("RESEARCH-G2" not in inputs["research_report"]
                or "RESEARCH-G2" not in json.dumps(inputs["actors"])
                or inputs["graph_id"] != proof["graph_id"]
                or inputs["simulation_id"] != proof["simulation_id"]):
            failures.append("replacement report constructor did not consume G2 identities/context")
        if (report_calls[0]["report_id"] != proof["report_id"]
                or not proof["report_id"].startswith("report_")
                or proof["report_id"] == "report_existing"):
            failures.append("replacement report identity was not newly allocated/adopted")
    if proof["project_id"] == "proj":
        failures.append("reconstructed research retained the G1 project identity")
    assert not failures, json.dumps({"failures": failures, "status": proof["status"],
                                   "graph": proof["graph_id"], "simulation": proof["simulation_id"],
                                   "ontology": proof["ontology_summary"]}, indent=2)
