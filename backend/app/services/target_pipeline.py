"""Target-first pipeline orchestration over a frozen typed research case.

The existing PipelineManager owns lifecycle/status. This module supplies the six
stage producers for the explicitly admitted authority, without prose extraction,
external graph inference, scenario votes or simulation probability promotion.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import uuid

from ..config import Config
from ..utils.atomic import write_json_atomic
from .official_data import bridge_module

AUTHORITY = "target-first-v1"


class TargetPipelineError(ValueError):
    """An admitted target case or one of its bound artifacts is invalid."""


def normalize_target_options(authority=None, simulation=None):
    if authority in (None, "legacy"):
        if simulation is not None:
            raise TargetPipelineError("target_simulation requires target-first-v1 authority")
        return {}
    if authority != AUTHORITY:
        raise TargetPipelineError("forecast_authority must be legacy or target-first-v1")
    if simulation is None:
        simulation = {}
    if not isinstance(simulation, dict) or set(simulation) - {"paths", "periods", "seed"}:
        raise TargetPipelineError("target_simulation accepts paths, periods and seed only")
    limits = {"paths": (32, 1, 256), "periods": (12, 1, 120), "seed": (0, 0, 2**31 - 1)}
    normalized = {}
    for key, (default, low, high) in limits.items():
        value = simulation.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise TargetPipelineError(f"target_simulation.{key} must be an integer in [{low}, {high}]")
        normalized[key] = value
    return {"forecast_authority": AUTHORITY, "simulation_engine": AUTHORITY,
            "target_simulation": normalized, "target_policy_version": 1}


def is_target(state):
    return state.options.get("forecast_authority") == AUTHORITY


def _digest(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                     separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64_000_000:
        raise TargetPipelineError(f"Required regular target artifact missing or oversized: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
    except (ValueError, UnicodeError) as exc:
        raise TargetPipelineError(f"Invalid target artifact: {path.name}") from exc


def stage_specs(state, stage):
    from .pipeline_orchestrator import PipelineManager, ReportManager
    handoff = Path(state.handoff_dir or PipelineManager.handoff_dir(state.pipeline_id))
    simulation = Path(Config.OASIS_SIMULATION_DATA_DIR) / (state.simulation_id or "unprepared")
    mapping = {
        "research": [("forecast_case", handoff / "forecast_case.json"),
                     ("target_estimators", handoff / "target_estimators.json"),
                     ("target_evidence", handoff / "target_evidence.json"),
                     ("target_library", handoff / "target_library.json"),
                     ("target_library_publication", handoff / "target_library_publication.json"),
                     ("report", handoff / "research_report.md")],
        "ontology": [("ontology", handoff / "ontology.json")],
        "graph": [("target_graph", handoff / "target_graph.json")],
        "prepare": [("target_case", simulation / "target_case.json"),
                    ("target_input", simulation / "target_input.json")],
        "run": [("target_simulation", simulation / "target_simulation.json")],
    }
    if "world_anchor" in state.options:
        from .world_anchor import enabled
        enabled(state.options)
        mapping["research"].extend(("world_anchor_" + key, handoff / filename) for key, filename in (
            ("manifest", "world_anchor_manifest.json"), ("pack", "world_anchor.json"),
            ("sheet", "world_anchor.md"), ("gaps", "world_anchor_gaps.json"),
            ("coverage", "world_anchor_coverage.json"), ("inputs", "world_anchor_inputs.json"),
            ("contract", "world_anchor_contract.json"), ("policy", "world_anchor_policy.json")))
    if stage == "report" and state.report_id:
        folder = Path(ReportManager._get_report_folder(state.report_id))
        return [("target_forecast", str(folder / "forecast.json")),
                ("target_report", str(folder / "full_report.md")),
                ("target_report_audit", str(folder / "final_audit.json")),
                ("target_comparison", str(simulation / "target_comparison.json"))]
    return [(name, str(path)) for name, path in mapping.get(stage, [])]


def validate_stage(state, stage):
    from .pipeline_orchestrator import PipelineManager
    entries = PipelineManager.load_artifact_manifest(state.pipeline_id)
    specs = stage_specs(state, stage)
    if not specs:
        return False
    for name, filename in specs:
        entry = entries.get(name)
        path = Path(filename)
        if (not isinstance(entry, dict) or entry.get("path") != filename
                or not entry.get("sha256") or path.is_symlink() or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]):
            return False
    return True


def record_stage(state, stage):
    from .pipeline_orchestrator import PipelineManager, _manifest_entry_for
    manifest = PipelineManager.load_artifact_manifest(state.pipeline_id)
    for name, filename in stage_specs(state, stage):
        path = Path(filename)
        if path.is_symlink() or not path.is_file():
            raise TargetPipelineError(f"Missing target {stage} artifact: {name}")
        entry = _manifest_entry_for(name, filename, stage)
        if not entry or not entry.get("sha256"):
            raise TargetPipelineError(f"Cannot seal target {stage} artifact: {name}")
        manifest[name] = entry
        state.artifacts[name] = filename
    PipelineManager.write_artifact_manifest(state.pipeline_id, manifest)


def _complete(owner, state, stage, message, *, reused=False):
    # Unlike optional historical artifacts, every typed stage receipt is required.
    owner._complete_stage(state, stage, message, reused=reused)


def _already_complete(state, stage):
    previous = state.stages.get(stage)
    if previous is not None and previous.status == "completed":
        if not validate_stage(state, stage):
            raise TargetPipelineError(f"Completed target {stage} artifacts changed; refusing mixed-generation reuse")
        return True
    return False


def capture_fork_source(state):
    """Freeze parent stage receipts before a target fork can reset stage flags."""
    from .pipeline_orchestrator import PipelineManager
    directory = Path(state.handoff_dir or PipelineManager.handoff_dir(state.pipeline_id)).resolve()
    manifest = PipelineManager.load_artifact_manifest(state.pipeline_id)
    files = {}
    for stage in ("research", "ontology", "graph"):
        saved = state.stages.get(stage)
        if saved is None or saved.status != "completed" or not validate_stage(state, stage):
            raise TargetPipelineError(f"Target fork parent {stage} receipts are invalid")
        for name, filename in stage_specs(state, stage):
            try:
                relative = Path(filename).relative_to(directory).as_posix()
            except ValueError as exc:
                raise TargetPipelineError("Target fork input is outside its parent handoff") from exc
            files[relative] = manifest[name]["sha256"]
    return {"schemaVersion": "target-fork-source/v1", "pipelineId": state.pipeline_id,
            "caseBinding": state.options.get("target_case_binding"), "files": files}


def isolate_target_fork(state):
    """Install receipt-verified inputs at the child's canonical local handoff."""
    from .pipeline_orchestrator import PipelineManager, PipelineState, _research_data_read
    import os
    import shutil
    import tempfile
    destination = Path(PipelineManager.handoff_dir(state.pipeline_id))
    if Path(state.handoff_dir or destination).absolute() == destination.absolute():
        return
    proof = state.options.get("target_fork_source")
    parent_id = state.options.get("base_pipeline_id")
    if (not isinstance(proof, dict) or proof.get("schemaVersion") != "target-fork-source/v1"
            or proof.get("pipelineId") != parent_id):
        raise TargetPipelineError("Target fork has no admitted parent input receipts")
    parent_data = PipelineManager.load(parent_id)
    if not isinstance(parent_data, dict):
        raise TargetPipelineError("Target fork parent is unavailable")
    parent = PipelineState.from_dict(parent_data)
    if capture_fork_source(parent) != proof:
        raise TargetPipelineError("Target fork parent generation changed after admission")
    source = Path(parent.handoff_dir or PipelineManager.handoff_dir(parent_id))
    if Path(state.handoff_dir).resolve() != source.resolve():
        raise TargetPipelineError("Target fork handoff differs from the admitted parent")
    temporary = Path(tempfile.mkdtemp(prefix=".target-handoff-", dir=destination.parent))
    try:
        for relative, digest in proof["files"].items():
            raw = _research_data_read(str(source), relative, 64_000_000)
            if hashlib.sha256(raw).hexdigest() != digest:
                raise TargetPipelineError("Target fork source changed: " + relative)
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        if capture_fork_source(parent) != proof:
            raise TargetPipelineError("Target fork parent changed during snapshot")
        if destination.is_symlink():
            raise TargetPipelineError("Target fork destination must be a regular directory")
        existing = list(destination.iterdir()) if destination.exists() else []
        if existing:
            files = {f.relative_to(destination).as_posix(): f for f in destination.rglob("*") if f.is_file()}
            if any(f.is_symlink() for f in destination.rglob("*")) or set(files) - {"manifest.json"} != set(proof["files"]):
                raise TargetPipelineError("Target fork destination already contains another generation")
            if any(hashlib.sha256(files[name].read_bytes()).hexdigest() != digest
                   for name, digest in proof["files"].items()):
                raise TargetPipelineError("Target fork recovery inputs differ from admitted receipts")
        else:
            os.replace(temporary, destination)
        state.handoff_dir = str(destination)
        PipelineManager.save(state)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _check_cancel(state):
    from .run_spending import check_state
    check_state(state)
    from .pipeline_orchestrator import PipelineOrchestrator, PipelineCancelled
    event = PipelineOrchestrator._cancel_events.get(state.pipeline_id)
    if event is not None and event.is_set():
        raise PipelineCancelled("Target pipeline cancelled")


def decision_provider_readiness():
    """Inspect configured provider requirements without constructing or calling it."""
    import shutil
    provider = getattr(Config, "LLM_PROVIDER", "")
    meta = getattr(Config, "PROVIDER_META", {}).get(provider)
    if not isinstance(meta, dict):
        return ["Configured target decision provider is unsupported"]
    if meta.get("needs_key") and not getattr(Config, "LLM_API_KEY", ""):
        return [f"Target decision provider {provider} requires its configured API key"]
    command = {"claude-cli": "claude", "codex-cli": "codex"}.get(provider)
    if command and shutil.which(command) is None:
        return [f"Target decision provider requires the {command} executable"]
    return []


def preflight_saved_target(data, *, operation="resume"):
    """Check only work remaining after receipt-verified research reuse.

    None delegates fresh research and legacy runs to their normal preflight.
    This is read-only: the runner still rechecks every receipt before reuse.
    """
    from .pipeline_orchestrator import PipelineState, PipelineManager

    if operation not in {"resume", "continue", "scenario"}:
        raise ValueError("Unsupported target reuse operation")
    if (data.get("options") or {}).get("forecast_authority") != AUTHORITY:
        return None
    state = PipelineState.from_dict(data)
    research = state.stages.get("research")
    completed_research = research is not None and research.status == "completed"
    fork_proof = state.options.get("target_fork_source")
    if not completed_research and not fork_proof:
        return None
    try:
        if state.options.get("simulation_engine") != AUTHORITY:
            raise TargetPipelineError("Target authority and engine pins differ")
        research_owner = state
        if not completed_research:
            # A fork interrupted before resealing already owns admitted parent
            # inputs. Verify them read-only; copying remains the runner's job.
            parent = PipelineManager.load(state.options.get("base_pipeline_id"))
            if not isinstance(parent, dict):
                raise TargetPipelineError("Target fork parent is unavailable")
            research_owner = PipelineState.from_dict(parent)
            if (capture_fork_source(research_owner) != fork_proof
                    or research_owner.options.get("target_case_binding") != state.options.get("target_case_binding")):
                raise TargetPipelineError("Target fork parent generation changed")
        if not validate_stage(research_owner, "research"):
            raise TargetPipelineError("Completed target research artifacts changed; cannot reuse them")
        binding = state.options.get("target_case_binding")
        if not isinstance(binding, dict) or not binding.get("caseHash"):
            raise TargetPipelineError("Completed target research has no case binding")
        handoff = Path(research_owner.handoff_dir or PipelineManager.handoff_dir(research_owner.pipeline_id))
        case = bridge_module("forecast_case").read_case(
            handoff / "forecast_case.json", expected_hash=binding["caseHash"])
        if case["question"].strip() != state.prompt.strip():
            raise TargetPipelineError("Case question does not match admitted pipeline")
        if operation == "resume" and state.mode == "research_only":
            return []
        # A seed fork always runs new paths even when its parent has completed.
        if operation != "scenario" and _already_complete(state, "run"):
            return []
        if any(actor["decisionRule"]["kind"] == "llm" for actor in case["actors"]):
            return decision_provider_readiness()
        return []
    except (ValueError, OSError, KeyError, TypeError):
        return ["Saved target artifacts or authority are invalid; restore the admitted generation before reuse"]


def _method_gateway():
    if decision_provider_readiness():
        return None
    from ..utils.llm_client import LLMClient
    return LLMClient()


def _decision_provider(owner, state):
    """Only safe actor observations cross the model boundary; no assessment input."""
    client = None
    cache = {}
    maximum = (state.options.get("target_decision_budget_v1") or {}).get("max_calls", 128)
    stats = {"maximumRequests": maximum, "requests": 0, "cacheHits": 0, "exhausted": False}
    state.options["target_decision_usage"] = stats

    def decide(observation):
        nonlocal client
        _check_cancel(state)
        key = _digest(observation)
        if key not in cache:
            if stats["requests"] >= maximum:
                stats["exhausted"] = True
                return {"actions": []}
            stats["requests"] += 1
            if client is None:
                from ..utils.llm_client import LLMClient
                client = LLMClient()
            cache[key] = client.chat_json([
                {"role": "system", "content": (
                    "Choose feasible institutional lever settings from the supplied observation. "
                    "Return a JSON object with actions. A lever action is {kind:'lever',actorId,leverId,value}; "
                    "a future plan is {kind:'commitment',actorId,leverId,value,duePeriod,condition}; "
                    "independent consent is {kind:'consent',actorId,forActorId,leverId,value}; "
                    "a signal is {kind:'signal',actorId,nodeId,value,recipients,duePeriod}. "
                    "Use only the opaque IDs, visible beliefs, preliminary lookahead options and decision rights supplied. "
                    "Consent must be your own decision, never a claim to consent on another actor's behalf. "
                    "Do not invent variables, consent, scenario probabilities or evidence. "
                    "An empty actions array is a valid decision to hold the current plan.")},
                {"role": "user", "content": json.dumps(observation, ensure_ascii=False, allow_nan=False)},
            ], max_tokens=1800, tier="strong")
        else:
            stats["cacheHits"] += 1
        return json.loads(json.dumps(cache[key]))
    return decide


def run_target_pipeline(owner, state):
    """Execute real research, projections, closed-loop paths and typed publication."""
    from . import pipeline_orchestrator as pipeline
    from .target_report import register_comparison
    from .target_simulation import run_paths
    fc = bridge_module("forecast_case")
    options = normalize_target_options(state.options.get("forecast_authority"),
                                       state.options.get("target_simulation"))
    if not options or state.options.get("simulation_engine") != AUTHORITY:
        raise TargetPipelineError("Target authority and engine pins differ")
    handoff = Path(state.handoff_dir or pipeline.PipelineManager.handoff_dir(state.pipeline_id))
    handoff.mkdir(parents=True, exist_ok=True)
    case_path = handoff / "forecast_case.json"
    library_path = handoff / "target_library.json"
    library_binding = state.options.get("target_library_binding")
    if library_binding is not None:
        if _digest(_read(library_path)) != library_binding:
            raise TargetPipelineError("Pinned cross-case library input changed")
    elif not state.options.get("target_case_binding"):
        from datetime import datetime, timezone
        import re
        from .forecast_library import select_entries
        words = re.findall(r"[\w-]+", state.prompt.casefold())
        terms = sorted(set(words + [" ".join(words[i:i + width])
                       for width in (2, 3) for i in range(len(words) - width + 1)]))
        selected = select_entries(Path(Config.UPLOAD_FOLDER) / "_library",
                                  as_of=datetime.now(timezone.utc).isoformat(), node_terms=terms)
        context = {"schemaVersion": "target-library-context/v1", "entries": selected,
                   "authority": "prior_context_only"}
        write_json_atomic(str(library_path), context)
        state.options["target_library_binding"] = _digest(context)
        pipeline.PipelineManager.save(state)

    # A frozen generation is never silently replaced on resume. Interrupted
    # research can resume through its own child checkpoint before this pin exists.
    reused = _already_complete(state, "research")
    update = owner._make_stage_updater(state, "research")
    update(5, "Build target resolution tree and source-backed case")
    if not reused and not state.options.get("target_case_binding"):
        def on_spawn(pid):
            state.research_pid = pid
            pipeline.PipelineManager.save(state)
        research = pipeline.DeerFlowResearchRunner.run(
            state.prompt, str(handoff), model=state.options.get("research_model"),
            depth=state.options.get("depth"), language=state.options.get("research_language"),
            on_progress=update, cancel_event=pipeline.PipelineOrchestrator._cancel_events.get(state.pipeline_id),
            on_spawn=on_spawn, resume=bool(state.options.get("resume")),
            research_engine="v3", forecast_authority=AUTHORITY, dual_track=False,
            budget_run_id=state.pipeline_id,
        )
        owner._record_research_telemetry(state, research.get("research_telemetry"))
        state.research_pid = None
        _check_cancel(state)
    case = fc.read_case(case_path)
    anchor_context = None
    if "world_anchor" in state.options:
        from . import world_anchor as anchors
        if state.options[anchors.LIFECYCLE_KEY]["status"] == "ready":
            anchor_context = anchors.require_completed(state)
        else:
            receipt_hash = state.options[anchors.LIFECYCLE_KEY].get("completion_manifest_sha256")
            anchor_context = anchors.accept_completion(state, expected_manifest_sha256=receipt_hash)
        anchors.validate_anchor_context(anchor_context, engine=AUTHORITY)
        bridge_module("world_anchor_case").validate_anchored_case(case,
            pack=anchor_context.pack, requirements=anchor_context.requirements,
            index=anchor_context.index, policy=anchor_context.policy)
    from .target_mechanisms import admit_model
    # The schema validates shape; production admission must also consume the
    # dimensional and seed-identity checks before any case is published/reused.
    admit_model(case)
    if case["question"].strip() != state.prompt.strip():
        raise TargetPipelineError("Case question does not match admitted pipeline")
    case_digest = fc.case_hash(case)
    binding = {"authority": AUTHORITY, "caseId": case["caseId"], "caseHash": case_digest,
               "questionHash": _digest(state.prompt), "policyVersion": 1}
    saved = state.options.get("target_case_binding")
    if saved is not None and saved != binding:
        raise TargetPipelineError("Frozen target case changed after research admission")
    state.options["target_case_binding"] = binding
    pipeline.PipelineManager.save(state)
    library_receipt_path = handoff / "target_library_publication.json"
    library_receipt_digest = state.options.get("target_library_publication_binding")
    if library_receipt_digest is not None:
        library_receipt = _read(library_receipt_path)
        if (_digest(library_receipt) != library_receipt_digest
                or library_receipt.get("caseHash") != case_digest):
            raise TargetPipelineError("Cross-case mechanism publication receipt changed")
    else:
        from .forecast_library import publish_case_mechanisms
        library_receipt = publish_case_mechanisms(Path(Config.UPLOAD_FOLDER) / "_library", case)
        write_json_atomic(str(library_receipt_path), library_receipt)
        state.options["target_library_publication_binding"] = _digest(library_receipt)
        pipeline.PipelineManager.save(state)
    from .target_report import build_target_report
    from .forecast_tournament import freeze_target_estimators, run_forecast_tournament
    evidence_path = handoff / "target_evidence.json"
    evidence_digest = state.options.get("target_evidence_binding")
    if evidence_digest is not None:
        target_evidence = _read(evidence_path)
        if _digest(target_evidence) != evidence_digest or target_evidence.get("caseHash") != case_digest:
            raise TargetPipelineError("Frozen official/market evidence changed")
    else:
        from .official_data import load_official_data
        markets_path = handoff / "prediction_markets.json"
        target_evidence = {"schemaVersion": "target-evidence/v1", "caseHash": case_digest,
            "official_data": load_official_data(str(handoff)),
            "markets": _read(markets_path) if markets_path.exists() else None,
            "news_market_context": pipeline._load_news_context(str(handoff))}
        write_json_atomic(str(evidence_path), target_evidence)
        state.options["target_evidence_binding"] = _digest(target_evidence)
        pipeline.PipelineManager.save(state)
    market_payload = target_evidence.get("markets")
    estimators_path = handoff / "target_estimators.json"
    estimator_digest = state.options.get("target_estimators_binding")
    policy = state.options.get("aggregation_policy_v1")
    typed_forecast = build_target_report(case, None, official_data=target_evidence.get("official_data"),
                                         markets=market_payload)["forecast"]
    if estimator_digest is not None:
        saved_estimators = _read(estimators_path)
        if _digest(saved_estimators) != estimator_digest:
            raise TargetPipelineError("Frozen target estimator evidence changed")
        run_forecast_tournament(typed_forecast, case=case, policy=policy,
                               saved_estimators=saved_estimators)
    else:
        enabled = state.options.get("target_tournament_enabled", False)
        saved_estimators = freeze_target_estimators(
            case, typed_forecast, policy, llm=_method_gateway() if enabled else None,
            markets=market_payload, enabled=enabled)
        _check_cancel(state)
        write_json_atomic(str(estimators_path), saved_estimators)
        state.options["target_estimators_binding"] = _digest(saved_estimators)
        pipeline.PipelineManager.save(state)
    _complete(owner, state, "research", "Typed research case and independent estimators frozen", reused=reused)
    if state.mode == "research_only":
        _finish(state, pipeline)
        return

    graph = fc.graph_projection(case)
    reused = _already_complete(state, "ontology")
    update = owner._make_stage_updater(state, "ontology")
    update(20, "Project resolution terms and actor decision rights")
    if not reused:
        ontology = {"schemaVersion": "target-ontology/v1", "caseHash": case_digest,
                    "entity_types": [{"name": "ResolutionNode"}, {"name": "Actor"}],
                    "edge_types": [{"name": "Determines"}, {"name": "Controls"}],
                    "analysis_summary": "Deterministic projection of the frozen resolution tree."}
        write_json_atomic(str(handoff / "ontology.json"), ontology)
    _complete(owner, state, "ontology", "Typed ontology projected", reused=reused)

    reused = _already_complete(state, "graph")
    update = owner._make_stage_updater(state, "graph")
    update(20, "Build deterministic case graph")
    if not reused:
        state.graph_id = f"target_graph_{state.pipeline_id}"
        graph.update({"graph_id": state.graph_id, "caseHash": case_digest})
        write_json_atomic(str(handoff / "target_graph.json"), graph)
    if not state.project_id:
        project = pipeline.ProjectManager.create_project(
            name=state.options.get("project_name") or case["question"])
        project.graph_id = state.graph_id
        project.ontology = _read(handoff / "ontology.json")
        project.simulation_requirement = state.prompt
        pipeline.ProjectManager.save_extracted_text(project.project_id,
            (handoff / "research_report.md").read_text(encoding="utf-8"))
        pipeline.ProjectManager.save_project(project)
        state.project_id = project.project_id
    _complete(owner, state, "graph", "Case graph projected", reused=reused)

    reused = _already_complete(state, "prepare")
    update = owner._make_stage_updater(state, "prepare")
    update(20, "Bind mechanism inputs and private actor observations")
    completed_run = _already_complete(state, "run")
    if not completed_run and any(actor["decisionRule"]["kind"] == "llm" for actor in case["actors"]):
        errors = decision_provider_readiness()
        if errors:
            raise TargetPipelineError("; ".join(errors))
    if not state.simulation_id:
        state.simulation_id = f"sim_{uuid.uuid4().hex[:12]}"
        pipeline.PipelineManager.save(state)
    directory = Path(Config.OASIS_SIMULATION_DATA_DIR) / state.simulation_id
    directory.mkdir(parents=True, exist_ok=True)
    inputs = {"schemaVersion": "target-input/v1", "pipelineId": state.pipeline_id,
              "caseHash": case_digest, "simulation": options["target_simulation"],
              "structure": fc.simulation_projection(case), "simulationWeight": 0.0,
              "decisionBudget": state.options.get("target_decision_budget_v1", {"max_calls": 128})}
    if anchor_context is not None:
        from .world_anchor import anchor_config_pin
        inputs["worldAnchor"] = anchor_config_pin(anchor_context, require_join=False)
    if reused:
        if _read(directory / "target_input.json") != inputs:
            raise TargetPipelineError("Prepared target inputs or pinned settings changed")
        fc.read_case(directory / "target_case.json", expected_hash=case_digest)
    else:
        fc.write_case(directory / "target_case.json", case)
        write_json_atomic(str(directory / "target_input.json"), inputs)
    _complete(owner, state, "prepare", "Mechanism inputs bound", reused=reused)

    reused = _already_complete(state, "run")
    update = owner._make_stage_updater(state, "run")
    update(10, "Run independent closed-loop target paths")
    if reused:
        result = _read(directory / "target_simulation.json")
        if result.get("caseHash") != case_digest or result.get("caseId") != case["caseId"]:
            raise TargetPipelineError("Target result case binding differs")
    else:
        result = run_paths(case, **options["target_simulation"],
                           decision_provider=_decision_provider(owner, state), cancel_check=lambda: _check_cancel(state),
                           model_validation="admission",
                           **({"anchor_context": anchor_context} if anchor_context is not None else {}))
        _check_cancel(state)
        result["decisionBudget"] = dict(state.options.get("target_decision_usage") or {})
        write_json_atomic(str(directory / "target_simulation.json"), result)
    _complete(owner, state, "run", "Target paths complete; simulation weight remains zero", reused=reused)

    reused = _already_complete(state, "report")
    update = owner._make_stage_updater(state, "report")
    update(10, "Render frozen research estimates and structural diagnostics")
    # Enrollment is recorded before publication and before the target resolves.
    # An expired target cannot become a purported prospective comparison.
    if not reused:
        from datetime import datetime, timezone
        if state.options.get("base_pipeline_id"):
            receipt = {"schemaVersion": "target-comparison/v1", "status": "diagnostic_fork",
                       "caseId": case["caseId"], "caseHash": case_digest,
                       "basePipelineId": state.options["base_pipeline_id"],
                       "simulationHash": _digest(result), "productionEligible": False}
        else:
            registry = Path(Config.PIPELINE_DATA_DIR) / "_target_comparisons"
            receipt = register_comparison(registry / (_digest(case["caseId"]) + ".json"), case, result,
                                          enrolled_at=datetime.now(timezone.utc).isoformat())
        write_json_atomic(str(directory / "target_comparison.json"), receipt)
        state.report_id = f"report_{uuid.uuid4().hex[:12]}"
        pipeline.PipelineManager.save(state)
        report = pipeline.ReportAgent(
            graph_id=state.graph_id, simulation_id=state.simulation_id,
            simulation_requirement=state.prompt, forecast_case=case,
            target_simulation=result, aggregation_policy=state.options.get("aggregation_policy_v1"),
            saved_estimators=saved_estimators, target_evidence=target_evidence,
            **({"anchor_context": anchor_context} if anchor_context is not None else {}),
            **owner._report_scenario_context(state),
        ).generate_report(progress_callback=lambda stage, progress, message: update(progress, message),
                          report_id=state.report_id)
        if report.status == pipeline.ReportStatus.FAILED:
            raise TargetPipelineError(report.error or "Typed report generation failed")
    publication = pipeline.ReportManager.publication_status(state.report_id)
    if not publication.get("publishable"):
        raise TargetPipelineError("Typed report publication failed: " + "; ".join(publication.get("reasons", [])))
    _complete(owner, state, "report", "Typed report published", reused=reused)
    state.options["pipeline_health"] = {"status": "ok", "authority": AUTHORITY,
        "simulationWeight": 0.0, "prospectiveLift": "unmeasured"}
    _finish(state, pipeline)


def _finish(state, pipeline):
    _check_cancel(state)
    from .run_spending import complete_target
    complete_target(state)
    state.status, state.global_progress = "completed", 100
    pipeline.PipelineManager.save(state)
    if state.task_id:
        pipeline.TaskManager().complete_task(state.task_id, result={
            "pipeline_id": state.pipeline_id, "project_id": state.project_id,
            "graph_id": state.graph_id, "simulation_id": state.simulation_id,
            "report_id": state.report_id})
