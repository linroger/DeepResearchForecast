"""Narrow control-plane adapter for the optional private run spending authority.

The shared stdlib store owns all debits. These functions bind the existing
pipeline lifecycle and never derive allowance from telemetry or stage state.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path

from .official_data import bridge_module

BINDING_KEY = "spending_policy_v1"
REQUEST_KEY = "spending_request_v1"
REQUEST_FIELDS = frozenset({"prompt", "mode", "depth", "language", "model", "forecast_authority", "target_simulation"})
_ANCHOR_BUDGET_FIELDS = (
    "policy_version", "source_policy_sha256", "model_attempt_limit", "token_envelope_limit",
    "catalog_attempt_limit", "followup_attempt_limit", "catalog_lookups_per_gap", "followup_round_limit",
)
_PIPELINE_STATE = ContextVar("spending_pipeline_state", default=None)


def _v2(binding):
    return isinstance(binding, dict) and binding.get("schema") == "target-run-spending-binding/v2"


def _request_fields(binding):
    return REQUEST_FIELDS | {"world_anchor"} if _v2(binding) else REQUEST_FIELDS


def api():
    return bridge_module("run_spending")


def state_binding(state):
    options = state.get("options", {}) if isinstance(state, dict) else state.options
    binding = options.get(BINDING_KEY)
    if BINDING_KEY in options and not isinstance(binding, dict):
        api().deny("invalid_binding")
    return binding


def validate_api_request(data):
    store = api()
    # HTTP selects a mode. Scope, policy and limits belong to private authority,
    # even when the caller happens to repeat their currently authorized values.
    if isinstance(data, dict) and "world_anchor" in data:
        value = data["world_anchor"]
        if type(value) is not dict or value != {"mode": "v1"}:
            store.deny("invalid_request")
    if not store.required():
        return
    binding = store.binding_from_environment()
    if not isinstance(data, dict) or set(data) != _request_fields(binding):
        store.deny("invalid_request")


def _authorized_anchor_option(binding):
    """Expand a public selector from the existing, authenticated v2 budget.

    Public core APIs validate source ownership and pins before this bounded
    read. The subsequent atomic bind revalidates them and the full request;
    reading a manifest here never grants authority or creates a second ledger.
    """
    from .official_data import _contained_bytes

    store = api()
    bound = store.open_existing(binding)
    if not _v2(bound):
        store.deny("invalid_binding")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                store.deny("invalid_manifest")
            value[key] = item
        return value

    def nonfinite(_):
        store.deny("invalid_manifest")

    try:
        raw = _contained_bytes(Path(bound["root"]), "spend/authorization.json", limit=4_000_000)
        manifest = store.validate_manifest(json.loads(
            raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite))
    except (OSError, ValueError, UnicodeError, RecursionError):
        store.deny("invalid_manifest")
    if (manifest["schema"] != "target-run-spending/v2"
            or store.hash_payload(manifest) != bound["manifest_sha256"]
            or any(manifest[key] != bound[key] for key in
                   ("root", "authorization_id", "source_sha256", "routes_sha256"))):
        store.deny("source_drift")
    budget = manifest["anchor_budget"]
    return {"mode": "v1", "anchor_budget_scope_id": budget["scope_id"],
            **{key: budget[key] for key in _ANCHOR_BUDGET_FIELDS}}


def normalized_request(prompt, *, mode, depth, language, model, forecast_authority, target_simulation,
                       world_anchor=None):
    from .target_pipeline import AUTHORITY, normalize_target_options
    store = api()
    if (not isinstance(prompt, str) or not prompt.strip() or mode != "full"
            or depth not in {"quick", "standard", "deep"}
            or language not in {"English", "Chinese", ""}
            or not isinstance(model, str) or not model.strip()
            or forecast_authority != AUTHORITY):
        store.deny("invalid_request")
    try:
        options = normalize_target_options(forecast_authority, target_simulation)
    except (ValueError, TypeError):
        store.deny("invalid_request")
    result = {"prompt": prompt.strip(), "mode": mode, "depth": depth, "language": language,
              "model": model.strip().lower(), "forecast_authority": AUTHORITY,
              "target_simulation": options["target_simulation"]}
    if world_anchor is not None:
        if type(world_anchor) is not dict or world_anchor.get("mode") != "v1":
            store.deny("invalid_request")
        store.hash_payload(world_anchor)
        result["world_anchor"] = json.loads(json.dumps(world_anchor, allow_nan=False))
    return result


def bind_start(pipeline_id, prompt, *, mode, depth, language, model, forecast_authority,
               target_simulation, project_name=None, max_rounds=None, world_anchor=None):
    store = api()
    binding = store.binding_from_environment()
    if binding is None:
        return {}
    if project_name is not None or max_rounds is not None:
        store.deny("invalid_request")
    if _v2(binding) and type(world_anchor) is dict and world_anchor == {"mode": "v1"}:
        world_anchor = _authorized_anchor_option(binding)
    request = normalized_request(prompt, mode=mode, depth=depth, language=language,
                                 model=model, forecast_authority=forecast_authority,
                                 target_simulation=target_simulation, world_anchor=world_anchor)
    if set(request) != _request_fields(binding):
        store.deny("invalid_request")
    bound = store.bind_pipeline(binding, pipeline_id, request)
    store.activate_binding(bound)
    if _v2(bound):
        store.preflight_anchor_profile(bound)
    return {BINDING_KEY: bound, REQUEST_KEY: request}


def _validate_state(state, binding):
    store = api()
    options = state.get("options", {}) if isinstance(state, dict) else state.options
    value = state.get if isinstance(state, dict) else lambda key: getattr(state, key)
    request = options.get(REQUEST_KEY)
    if not isinstance(request, dict) or set(request) != _request_fields(binding):
        store.deny("invalid_request")
    actual = normalized_request(value("prompt"), mode=value("mode"), depth=options.get("depth"),
        language=options.get("research_language"), model=options.get("research_model"),
        forecast_authority=options.get("forecast_authority"),
        target_simulation=options.get("target_simulation"), world_anchor=options.get("world_anchor"))
    if actual != request or binding.get("pipeline_id") != value("pipeline_id"):
        store.deny("binding_conflict")
    store.validate_bound_request(binding, actual)
    return request


def _private_paths(binding):
    from ..config import Config
    from ..models.project import ProjectManager
    from .report_agent import ReportManager
    root = Path(binding["root"]).resolve()
    paths = [Config.UPLOAD_FOLDER, Config.PIPELINE_DATA_DIR, Config.OASIS_SIMULATION_DATA_DIR,
             Config.DEERFLOW_DIR, ProjectManager.PROJECTS_DIR, ReportManager.REPORTS_DIR]
    for value in paths:
        path = Path(value).absolute()
        if (not path.resolve().is_relative_to(root)
                or any(part.is_symlink() for part in (path, *path.parents))):
            api().deny("invalid_binding")


@contextmanager
def pipeline_scope(state):
    store = api()
    binding = state_binding(state)
    if binding is None:
        if store.required():
            store.deny("missing_context")
        yield None
        return
    store.activate_binding(binding)
    _validate_state(state, binding)
    _private_paths(binding)
    token = _PIPELINE_STATE.set(state)
    try:
        with store.operation("pipeline", store.hash_payload(state.options[REQUEST_KEY])):
            store.check_active(binding)
            yield binding
    finally:
        _PIPELINE_STATE.reset(token)


def check_state(state):
    binding = state_binding(state)
    if binding is not None:
        api().check_active(binding)
    elif api().required():
        api().deny("missing_context")


@contextmanager
def model_operation(stage, identity):
    """Derive a child operation without exposing its identity to the model."""
    store = api()
    if not store.required():
        yield
        return
    store.check_context()
    with store.operation(stage, store.hash_payload(identity)):
        yield


def finish_pipeline(state):
    store = api()
    binding = state_binding(state)
    if binding is None:
        return
    status = store.summary(binding)["state"]
    if state.status == "completed":
        if status != "closed":
            store.close_run(binding)
    elif state.status == "cancelled":
        store.halt(binding, "halted_cancelled")
    elif status == "active":
        store.mark_recoverable(binding)
    state.options["spending_summary_v1"] = store.summary(binding)


def complete_target(state):
    binding = state_binding(state)
    if binding is not None:
        store = api()
        store.check_active(binding)
        store.close_run(binding)
        state.options["spending_summary_v1"] = store.summary(binding)


def reject_scope_change(data):
    if state_binding(data) is not None:
        api().deny("invalid_request")


def cancel_bound(data):
    binding = state_binding(data)
    if binding is not None:
        try:
            api().halt(binding, "halted_cancelled")
        except Exception as error:
            if not api().is_spending_stop(error):
                raise
            # Missing/corrupt authority already denies every future admission;
            # it must not prevent the caller from stopping the owned child.
            return error.code
    return None


def resume_bound(data):
    store = api()
    binding = state_binding(data)
    if binding is None:
        if store.required():
            store.deny("missing_context")
        return None
    _validate_state(data, binding)
    _private_paths(binding)
    # The target-v3 producer has no admitted partial checkpoint contract in this
    # closed profile. Only a sealed completed research generation can resume.
    from .pipeline_orchestrator import PipelineState
    from .target_pipeline import validate_stage
    state = PipelineState.from_dict(data)
    research = state.stages.get("research")
    if research is None or research.status != "completed" or not validate_stage(state, "research"):
        raise store.SpendingStop("resume_denied")
    # Only the private launcher supplies a new explicit approval proof. No
    # HTTP argument, task ID or telemetry reset is an authority to replenish.
    raw = os.environ.get("DRF_RUN_SPENDING_RESUME_PROOF")
    if not raw:
        store.deny("resume_denied")
    try:
        proof = json.loads(raw)
    except (ValueError, TypeError):
        store.deny("resume_denied")
    rebound = store.resume_existing(binding, proof)
    store.activate_binding(rebound)
    return rebound


def record_stop(state, error):
    store = api()
    if not store.is_spending_stop(error):
        raise error
    state.status = "cancelled" if error.code == "halted_cancelled" else "failed"
    state.error = "Run spending stopped: " + error.code
    state.options["spending_stop_v1"] = {"code": error.code}
    binding = state_binding(state)
    if binding is not None:
        try:
            state.options["spending_summary_v1"] = store.summary(binding)
        except Exception:
            pass  # Missing/corrupt authority remains a stop, never a new ledger.


@contextmanager
def research_child_scope(prompt, handoff_dir, *, model, budget_run_id, options):
    """Register one required child before launch; only a joined process may exit."""
    import uuid
    from ..config import Config
    store = api()
    if not store.required():
        yield None, None
        return
    binding = store.check_context()
    root = Path(binding["root"]).resolve()
    if (budget_run_id != binding["pipeline_id"] or options.get("forecast_authority") != "target-first-v1"
            or options.get("research_engine") != "v3" or options.get("dual_track") is not False
            or options.get("backtest") is not None or options.get("evidence_only")
            or options.get("synthesis_manifest_path") or options.get("kg_graph_id")):
        store.deny("invalid_request")
    for value in (handoff_dir, Config.DEERFLOW_DIR):
        path = Path(value).absolute()
        if (not path.resolve().is_relative_to(root)
                or any(part.is_symlink() for part in (path, *path.parents))):
            store.deny("invalid_binding")
    participant_id = "research-" + uuid.uuid4().hex
    spawn_hash = store.hash_payload({"pipeline": binding["pipeline_id"], "participant": participant_id,
                                    "prompt": store.hash_payload(prompt), "model": model})
    child_operation = {"stage": "research", "logical_key": store.hash_payload(
        {"pipeline": binding["pipeline_id"], "question": store.hash_payload(prompt)})}
    tracker = {"process": None}
    with store.operation(**child_operation):
        entry = {}
        if _v2(binding):
            entry["scope_entry_ids"] = (store.preflight_anchor_profile(binding)["scope_id"],)
        child = store.register_participant(binding, participant_id, spawn_receipt_sha256=spawn_hash,
                                           operation_context=store.current_operation(), **entry)
        try:
            yield child, tracker
            if not _v2(binding):
                store.check_active(binding)
        finally:
            process = tracker["process"]
            if _v2(binding) and (process is None or process.poll() is not None):
                binding = _adopt_research_scope_handoff(binding, handoff_dir)
            if process is None:
                proof = {"participant": participant_id, "spawn_failed_before_process": True}
            elif process.poll() is not None:
                proof = {"participant": participant_id, "pid": process.pid, "exit_code": process.returncode}
            else:
                store.halt(binding, "unknown_outcome")
                proof = None
            if proof is not None:
                store.participant_exited(binding, participant_id,
                    exit_receipt_sha256=store.hash_payload(proof))
                store.check_active(binding)


def _adopt_research_scope_handoff(binding, handoff_dir):
    """Adopt DB-authenticated phase transitions and update the active host state."""
    from .official_data import _contained_bytes
    store = api()
    try:
        raw = _contained_bytes(Path(handoff_dir), "world_anchor_scope_handoff.json", limit=128 * 1024)
    except FileNotFoundError:
        return binding

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                store.deny("invalid_binding")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs)
        if (type(value) is not dict or set(value) != {"schema_version", "receipts", "completion"}
                or value["schema_version"] != "world-anchor-scope-handoff/v1"
                or type(value["receipts"]) is not list or not 1 <= len(value["receipts"]) <= 2
                or not all(type(row) is dict for row in value["receipts"])):
            store.deny("invalid_binding")
    except (ValueError, TypeError):
        store.deny("invalid_binding")
    completion = value["completion"]
    if completion is not None:
        if (type(completion) is not dict
                or value["receipts"][-1].get("kind") != "exit"
                or store.hash_payload(completion) != value["receipts"][-1].get("proof_sha256")):
            store.deny("invalid_binding")
    elif value["receipts"][-1].get("kind") == "exit":
        store.deny("invalid_binding")
    rebound = store.adopt_scope_handoff(binding, value["receipts"])
    state = _PIPELINE_STATE.get()
    if state is not None:
        if state.pipeline_id != rebound["pipeline_id"]:
            store.deny("binding_conflict")
        state.options[BINDING_KEY] = rebound
        if completion is not None:
            from . import world_anchor as anchors
            if not anchors.enabled(state.options):
                store.deny("binding_conflict")
            pending = state.options[anchors.LIFECYCLE_KEY]
            if pending["status"] != "pending":
                store.deny("binding_conflict")
            # The exit proof was matched to the durable transition above. This
            # records produced bytes; the research controller owns ready/sealed.
            pending["completion_manifest_sha256"] = completion["artifact_manifest_sha256"]
            state.options[anchors.SCOPE_COMPLETION_KEY] = json.loads(json.dumps(completion, allow_nan=False))
        from .pipeline_orchestrator import PipelineManager
        PipelineManager.save(state)
    return rebound


def configure_child(binding, env, cmd, script):
    """Require the isolated no-site bootstrap and close all unpriced routes."""
    store = api()
    root = Path(binding["root"])
    launcher = root / "app/backend/scripts/target_acceptance_run.py"
    descriptor = root / "spend/runtime.json"
    if not launcher.is_file() or launcher.is_symlink() or not descriptor.is_file():
        store.deny("invalid_binding")
    env.update(store.export_environment(binding))
    disabled = ("DATA_SOURCES_ENABLED", "NEWS_CONTEXT_ENABLED", "MARKET_INTELLIGENCE_ENABLED",
                "PREDICTION_MARKETS_ENABLED", "REDDIT_SIGNALS_ENABLED", "RESEARCH_MCP_KG",
                "RESEARCH_FALLBACK_ON_EXHAUST", "RESEARCH_TIMEOUT_EXTRACT_SALVAGE")
    for key in disabled:
        env[key] = "false"
    for key in ("DEERFLOW_FALLBACK_MODEL", "LLM_FALLBACK_PROVIDER", "LLM_FALLBACK_MODEL_NAME"):
        env[key] = ""
    for key in ("SERPER_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY", "JINA_API_KEY",
                "DEER_FLOW_EXTENSIONS_CONFIG_PATH", "DRF_MCP_KG_GRAPH_ID"):
        env.pop(key, None)
    env["RESOLUTION_MONITOR_AUTORUN_HOURS"] = "0"
    env["DEER_FLOW_HOME"] = str(root / "deer-flow-home")
    env["RESEARCH_MODEL_LEASE_DB"] = str(root / "research-model-leases.sqlite3")
    env["TMPDIR"] = str(root / "tmp")
    # The existing detector may select uv or a shell wrapper; required mode
    # accepts only the launcher-verified interpreter from the private descriptor.
    runtime = json.loads(descriptor.read_text())
    python = runtime.get("python")
    if not isinstance(python, str) or not Path(python).is_file():
        store.deny("invalid_binding")
    try:
        script_index = cmd.index(script)
    except ValueError:
        store.deny("invalid_request")
    return [python, "-I", "-S", "-B", str(launcher), "_child", "--", *cmd[script_index:]]
