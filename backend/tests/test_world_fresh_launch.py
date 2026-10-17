"""Real fresh launch/continuation boundaries; coordinator guarded runner only.

Storage and admission are real. Thread dispatch, unrelated environment checks and
task bookkeeping are observed substitutes; HTTP uses the shared MockTransport.
No test here is evidence until the coordinator executes it under the guard.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from test_world_default_admission import offline_http, profile, write_profile  # noqa: F401
from test_world_lifecycle import boundary as lifecycle_boundary  # noqa: F401


pytestmark = pytest.mark.guarded_runner


@pytest.fixture
def launch(monkeypatch, tmp_path):
    from flask import Flask
    from app.api import research_bp
    from app.api import research, sdk
    from app.config import Config
    from app.services import pipeline_orchestrator as po
    from app.services.world_simulation.policy import StrictHTTPModeler, StrictHTTPPolicy
    from app.utils.llm_client import LLMClient

    root = tmp_path.resolve() / "pipelines"
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(root))
    monkeypatch.setattr(po.SimulationRunner, "RUN_STATE_DIR", str(tmp_path / "simulations"))
    monkeypatch.setattr(Config, "DEFAULT_SIMULATION_ENGINE", "oasis-legacy")
    monkeypatch.setattr(Config, "WORLD_POLICY_SPEC_PATH", None)
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "diagnostic_only")
    monkeypatch.setattr(Config, "RESEARCH_ENGINE", "v3")
    monkeypatch.setattr(po.PipelineOrchestrator, "_threads", {})
    monkeypatch.setattr(po.PipelineOrchestrator, "_cancel_events", {})
    monkeypatch.setattr(po.PipelineManager, "_state_locks", {})
    calls, model_calls, checked = [], [], []
    original_dirs, original_save = po.PipelineManager.ensure_dirs, po.PipelineManager.save

    def dirs(cls, pid):
        calls.append(("dirs", pid))
        return original_dirs(pid)

    def save(cls, state):
        calls.append(("save", state.pipeline_id))
        return original_save(state)

    def task(**kwargs):
        calls.append(("task", kwargs))
        return "task_fixture"

    class ParkedThread:
        def __init__(self, **kwargs):
            calls.append(("thread", kwargs))
            self.kwargs = kwargs

        def start(self):
            calls.append(("dispatch", self.kwargs["name"]))

        def is_alive(self):
            return False

    def forbidden(*args, **kwargs):
        model_calls.append((args, kwargs))
        raise AssertionError("Fresh admission must not invoke research/model/actor calls")

    def preflight(mode="full", model=None):
        checked.append((mode, model))
        return []

    monkeypatch.setattr(po.PipelineManager, "ensure_dirs", classmethod(dirs))
    monkeypatch.setattr(po.PipelineManager, "save", classmethod(save))
    monkeypatch.setattr(po, "TaskManager", lambda: SimpleNamespace(create_task=task))
    monkeypatch.setattr(po, "threading", SimpleNamespace(
        Thread=ParkedThread, Event=threading.Event, Lock=threading.Lock))
    monkeypatch.setattr(po.DeerFlowResearchRunner, "run", forbidden)
    monkeypatch.setattr(StrictHTTPModeler, "decide", forbidden)
    monkeypatch.setattr(StrictHTTPPolicy, "decide", forbidden)
    monkeypatch.setattr(LLMClient, "chat", forbidden)
    monkeypatch.setattr(LLMClient, "chat_json", forbidden)
    monkeypatch.setattr(research, "preflight_pipeline", preflight)
    monkeypatch.setattr(sdk, "preflight_pipeline", preflight)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import preflight as script
    monkeypatch.setattr(script, "preflight_pipeline", preflight)
    monkeypatch.setattr(script, "_append_placeholder_checks", lambda *args: None)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(research_bp, url_prefix="/api/research")
    app.register_blueprint(sdk.sdk_bp, url_prefix="/api/v1")
    yield SimpleNamespace(po=po, config=Config, root=root, calls=calls,
                          model_calls=model_calls, checked=checked, script=script,
                          client=app.test_client())
    assert model_calls == []


def assert_unstarted(b):
    assert b.calls == []
    assert not b.root.exists()
    assert b.po.PipelineOrchestrator._threads == {}
    assert b.po.PipelineOrchestrator._cancel_events == {}
    assert b.model_calls == []


def completed_research(b, **kwargs):
    state = b.po.PipelineOrchestrator.start("Fixture research", mode="research_only", **kwargs)
    Path(state.handoff_dir, "research_report.md").write_text("Completed fixture research.", encoding="utf-8")
    state.status = "completed"
    state.stages["research"].status = "completed"
    state.stages["research"].progress = 100
    b.po.PipelineManager.save(state)
    b.calls.clear()
    return state


@pytest.mark.parametrize("entry", ["direct", "/api/research/run", "/api/v1/run"])
@pytest.mark.parametrize("failure", ["missing", "bad_profile", "null", "rounds", "cli"])
def test_bad_admission_before_any_pipeline_side_effect(launch, monkeypatch, tmp_path, entry, failure):
    from app.services.world_simulation.contracts import WorldError
    b = launch
    monkeypatch.setattr(b.config, "DEFAULT_SIMULATION_ENGINE", "world-v1")
    request = {"prompt": "Fixture launch"}
    code, status = "world_configuration_required", 409
    if failure == "bad_profile":
        path = tmp_path.resolve() / "bad-profile.json"
        path.write_text('{"secret":"fixture-never-echo"}', encoding="utf-8")
        monkeypatch.setattr(b.config, "WORLD_POLICY_SPEC_PATH", str(path))
        code, status = "invalid_world_request", 400
    elif failure == "null":
        request["simulation_engine"] = None
        code, status = "unsupported_engine", 400
    elif failure == "rounds":
        request["max_rounds"] = 1
        code, status = "world_calendar_override", 400
    elif failure == "cli":
        value = profile()
        value["policy"]["provider"] = "claude-cli"
        request["world_policy_spec"] = value
        code, status = "unbounded_transport", 409
    if entry == "direct":
        with pytest.raises(WorldError) as error:
            b.po.PipelineOrchestrator.start(**request)
        assert error.value.code == code
    else:
        response = b.client.post(entry, json=request)
        assert response.status_code == status, response.json
        assert response.json["error_code"] == code
        assert "traceback" not in response.json
        assert "fixture-never-echo" not in response.get_data(as_text=True)
    assert_unstarted(b)


@pytest.mark.parametrize("entry", ["direct", "/api/research/run", "/api/v1/run"])
def test_prompt_only_configured_world_pins_detached_profile(launch, offline_http, monkeypatch, tmp_path, entry):  # noqa: F811
    b = launch
    path = write_profile(tmp_path)
    monkeypatch.setattr(b.config, "DEFAULT_SIMULATION_ENGINE", "world-v1")
    monkeypatch.setattr(b.config, "WORLD_POLICY_SPEC_PATH", str(path))
    if entry == "direct":
        state = b.po.PipelineOrchestrator.start("Fixture prompt")
        pid = state.pipeline_id
    else:
        response = b.client.post(entry, json={"prompt": "Fixture prompt"})
        assert response.status_code == 200, response.json
        pid = response.json["data"]["pipeline_id"]
    saved = b.po.PipelineManager.load(pid)
    assert saved["options"]["simulation_engine"] == "world-v1"
    assert saved["options"]["simulation_admission_v1"]["source"] == "operator_profile"
    assert saved["options"]["world_policy_spec"]["policy"] == profile()["policy"]
    assert saved["options"]["actor_intelligence_policy_v1"]["required"] is False
    before = Path(b.po.PipelineManager.state_path(pid)).read_bytes()
    path.write_text("{}", encoding="utf-8")
    assert Path(b.po.PipelineManager.state_path(pid)).read_bytes() == before
    assert str(path).encode() not in before
    assert offline_http.sent == []
    assert offline_http.clients and all(client.is_closed for client in offline_http.clients)


def test_explicit_policy_and_single_safety_snapshot(launch, offline_http, monkeypatch):  # noqa: F811
    b = launch
    request = profile()
    request.pop("forecastEffect")
    snapshots = []
    original = b.po.capture_safety_policy_v1

    def capture(origin):
        snapshot = original(origin)
        snapshot["simulation_forecast_effect"] = "no_update"
        snapshots.append(snapshot)
        return snapshot

    monkeypatch.setattr(b.po, "capture_safety_policy_v1", capture)
    monkeypatch.setattr(b.config, "WORLD_POLICY_SPEC_PATH", "/must-not-read")
    state = b.po.PipelineOrchestrator.start("Fixture", simulation_engine="world-v1", world_policy_spec=request)
    before = deepcopy(state.options)
    request["limits"]["maxTokens"] = 1
    assert state.options == before
    assert len(snapshots) == 1
    assert state.options["safety_policy_v1"] == snapshots[0]
    assert state.options["world_policy_spec"]["forecastEffect"] == "no_update"


@pytest.mark.parametrize("explicit", [False, True])
def test_legacy_default_and_explicit_override(launch, monkeypatch, explicit):
    b = launch
    request = {"prompt": "Legacy", "max_rounds": 4}
    if explicit:
        monkeypatch.setattr(b.config, "DEFAULT_SIMULATION_ENGINE", "world-v1")
        request["simulation_engine"] = "oasis-legacy"
    response = b.client.post("/api/research/run", json=request)
    assert response.status_code == 200, response.json
    saved = b.po.PipelineManager.load(response.json["data"]["pipeline_id"])
    assert saved["options"]["simulation_engine"] == "oasis-legacy"
    assert saved["options"]["max_rounds"] == 4


def test_research_only_defers_profile_and_auth(launch, monkeypatch):
    from app.services.world_simulation import admission
    b = launch
    monkeypatch.setattr(b.config, "DEFAULT_SIMULATION_ENGINE", "world-v1")
    monkeypatch.setattr(b.config, "LLM_API_KEY", None)
    monkeypatch.setattr(b.config, "WORLD_POLICY_SPEC_PATH", "/must-not-read")

    def forbidden(*args):
        pytest.fail("Research-only must not inspect simulation profile or transport")

    monkeypatch.setattr(admission, "_read_profile", forbidden)
    monkeypatch.setattr(admission, "_transport_ready", forbidden)
    response = b.client.post("/api/research/run", json={"prompt": "Research", "mode": "research_only"})
    assert response.status_code == 200, response.json
    saved = b.po.PipelineManager.load(response.json["data"]["pipeline_id"])
    assert saved["options"]["simulation_admission_v1"]["status"] == "deferred"
    assert saved["options"]["world_policy_spec"] is None


def test_readiness_short_full_and_script_share_selected_mode_model_engine(launch, monkeypatch):
    b = launch
    monkeypatch.setattr(b.config, "DEFAULT_SIMULATION_ENGINE", "world-v1")
    for mode, engine, ready in [("full", "world-v1", False), ("research_only", "world-v1", True),
                               ("full", "oasis-legacy", True)]:
        params = {"mode": mode, "model": "codex", "simulation_engine": engine}
        short = b.client.get("/api/research/preflight", query_string=params).json["data"]
        full = b.client.get("/api/research/preflight", query_string={**params, "format": "full"}).json["data"]
        script = b.script.environment_report(**params)
        assert short["ready"] is full["ready"] is script["ready"] is ready
        assert short["simulation_admission"] == full["simulation_admission"] == script["simulation_admission"]
        assert short["simulation_engine"] == full["simulation_engine"] == engine
        assert short["default_simulation_engine"] == "world-v1"
        assert {"provider", "deerflow_model", "graph_backend", "venv_python", "deerflow_dir",
                "data_dir", "embed_model", "mode", "ready", "exit_code", "checks"} <= full.keys()
        assert b.checked[-3:] == [(mode, "codex")] * 3
    assert_unstarted(b)


def test_post_revalidates_after_successful_readiness(launch, offline_http, monkeypatch, tmp_path):  # noqa: F811
    b = launch
    path = write_profile(tmp_path)
    monkeypatch.setattr(b.config, "DEFAULT_SIMULATION_ENGINE", "world-v1")
    monkeypatch.setattr(b.config, "WORLD_POLICY_SPEC_PATH", str(path))
    ready = b.client.get("/api/research/preflight").json["data"]
    assert ready["ready"] is True
    encoded = json.dumps(ready)
    assert str(path) not in encoded and "fixture-only-secret" not in encoded
    assert "baseUrl" not in encoded and "maxTokens" not in encoded
    path.write_text("{}", encoding="utf-8")
    response = b.client.post("/api/research/run", json={"prompt": "Revalidate"})
    assert response.status_code == 400
    assert_unstarted(b)


@pytest.mark.parametrize("via_api", [False, True])
def test_failed_continuation_leaves_saved_state_tasks_and_threads_unchanged(launch, via_api):
    from app.services.world_simulation.contracts import WorldError
    b = launch
    state = completed_research(b, simulation_engine="world-v1")
    path = Path(b.po.PipelineManager.state_path(state.pipeline_id))
    before = path.read_bytes()
    threads = dict(b.po.PipelineOrchestrator._threads)
    events = dict(b.po.PipelineOrchestrator._cancel_events)
    if via_api:
        response = b.client.post(f"/api/research/{state.pipeline_id}/continue")
        assert response.status_code == 409, response.json
        assert response.json["error_code"] == "world_configuration_required"
    else:
        with pytest.raises(WorldError, match="WORLD_POLICY_SPEC_PATH"):
            b.po.PipelineOrchestrator.continue_to_full(state.pipeline_id)
    assert path.read_bytes() == before and b.calls == []
    assert b.po.PipelineOrchestrator._threads == threads
    assert b.po.PipelineOrchestrator._cancel_events == events


@pytest.mark.parametrize("saved_policy", [False, True])
def test_continuation_pins_deferred_or_saved_policy(launch, offline_http, monkeypatch, tmp_path, saved_policy):  # noqa: F811
    b = launch
    kwargs = {"world_policy_spec": profile()} if saved_policy else {}
    state = completed_research(b, simulation_engine="world-v1", **kwargs)
    path = write_profile(tmp_path)
    if saved_policy:
        path.write_text("invalid ambient profile", encoding="utf-8")
    monkeypatch.setattr(b.config, "WORLD_POLICY_SPEC_PATH", str(path))
    monkeypatch.setattr(b.config, "SIMULATION_FORECAST_EFFECT", "no_update")
    result = b.po.PipelineOrchestrator.continue_to_full(state.pipeline_id)
    assert result.mode == "full" and result.status == "running"
    assert result.options["world_policy_spec"]["forecastEffect"] == "diagnostic_only"
    assert result.options["simulation_admission_v1"]["source"] == (
        "request_policy" if saved_policy else "operator_profile")
    assert result.options["simulation_admission_v1"]["status"] == "ready"


def test_invalid_saved_policy_never_uses_valid_ambient_profile(launch, offline_http, monkeypatch, tmp_path):  # noqa: F811
    from app.services.world_simulation.contracts import WorldError
    b = launch
    state = completed_research(b, simulation_engine="world-v1", world_policy_spec={})
    before = Path(b.po.PipelineManager.state_path(state.pipeline_id)).read_bytes()
    monkeypatch.setattr(b.config, "WORLD_POLICY_SPEC_PATH", str(write_profile(tmp_path)))
    with pytest.raises(WorldError):
        b.po.PipelineOrchestrator.continue_to_full(state.pipeline_id)
    assert Path(b.po.PipelineManager.state_path(state.pipeline_id)).read_bytes() == before
    assert b.calls == []


def test_historical_missing_engine_stays_legacy_on_continue(launch, monkeypatch):
    b = launch
    state = completed_research(b)
    for key in ("simulation_engine", "simulation_admission_v1"):
        state.options.pop(key)
    b.po.PipelineManager.save(state)
    monkeypatch.setattr(b.config, "DEFAULT_SIMULATION_ENGINE", "world-v1")
    monkeypatch.setattr(b.config, "WORLD_POLICY_SPEC_PATH", "/must-not-read")
    result = b.po.PipelineOrchestrator.continue_to_full(state.pipeline_id)
    assert result.mode == "full"
    assert b.po.PipelineOrchestrator._simulation_engine(result) == "oasis-legacy"
    assert "simulation_engine" not in result.options


def test_world_error_never_exposes_exception_or_provider_body(launch, monkeypatch):
    from app.services.world_simulation.contracts import WorldError

    def fail(**kwargs):
        raise WorldError("invalid_policy_client", "secret-provider-body /private/path", details={"key": "secret"})

    monkeypatch.setattr(launch.po, "resolve_fresh_simulation_request", fail)
    for endpoint in ("/api/research/run", "/api/v1/run"):
        response = launch.client.post(endpoint, json={"prompt": "Fixture"})
        assert response.status_code == 409
        assert set(response.json) == {"success", "error", "error_code"}
        assert "secret" not in response.get_data(as_text=True)
        assert "/private/path" not in response.get_data(as_text=True)
    assert_unstarted(launch)


def test_saved_schedule_retains_engine_and_policy(launch, monkeypatch):
    import scheduled_rerun as scheduler
    seen = []
    monkeypatch.setattr(launch.config, "DEFAULT_SIMULATION_ENGINE", "world-v1")
    monkeypatch.setattr(scheduler.ScheduleStore, "save", lambda record: None)

    def start(*args, **kwargs):
        seen.append(kwargs)
        return SimpleNamespace(pipeline_id="pipe_schedule_fixture")

    monkeypatch.setattr(launch.po.PipelineOrchestrator, "start", start)
    for options in ({}, {"simulation_engine": "world-v1", "world_policy_spec": profile()}):
        record = {"schedule_id": "sched_fixture", "prompt": "Fixture", "options": options}
        assert scheduler.Scheduler._launch(record, datetime.now(timezone.utc)) == "pipe_schedule_fixture"
        assert seen[-1]["simulation_engine"] == options.get("simulation_engine", "oasis-legacy")
        assert seen[-1]["world_policy_spec"] == options.get("world_policy_spec")
    before = len(seen)
    record = {"schedule_id": "sched_fixture", "prompt": "Fixture", "options": {"simulation_engine": "world-v1"}}
    assert scheduler.Scheduler._launch(record, datetime.now(timezone.utc)) is None
    assert len(seen) == before


@pytest.mark.parametrize("shared", [False, True])
def test_batch_rejects_world_parent_before_child_side_effects(launch, monkeypatch, shared):
    import batch_runs
    b = launch
    state = b.po.PipelineState(pipeline_id="pipe_world_parent", prompt="Fixture", graph_id="graph_fixture",
                               simulation_id="sim_fixture", options={"simulation_engine": "world-v1"})
    monkeypatch.setattr(b.po.PipelineManager, "load", lambda pid: state.to_dict())
    with pytest.raises(RuntimeError, match="oasis-legacy only"):
        batch_runs.fork_question(state.pipeline_id, "Child", shared_simulation=shared)
    assert_unstarted(b)


def test_batch_anchor_and_child_explicitly_pin_legacy(launch, monkeypatch):
    import batch_runs
    b = launch
    monkeypatch.setattr(b.config, "DEFAULT_SIMULATION_ENGINE", "world-v1")
    monkeypatch.setattr(batch_runs, "preflight_pipeline", lambda **kw: [])
    monkeypatch.setattr(batch_runs.BatchManager, "save", lambda record: None)
    monkeypatch.setattr(batch_runs, "_wait_for_graph", lambda pid, **kw: b.po.PipelineManager.load(pid))
    record = batch_runs.start_batch(["Fixture anchor"])
    state = b.po.PipelineManager.load(record["anchor_pipeline_id"])
    assert state["options"]["simulation_engine"] == "oasis-legacy"
    state["graph_id"] = "graph_fixture"
    b.po.PipelineManager.save(b.po.PipelineState.from_dict(state))
    # The batch function imports TaskManager locally; replace that same boundary.
    import app.models.task as tasks
    monkeypatch.setattr(tasks, "TaskManager", lambda: SimpleNamespace(create_task=lambda **kw: "task_child"))
    monkeypatch.setattr(batch_runs, "threading", b.po.threading)
    child = batch_runs.fork_question(state["pipeline_id"], "Fixture child")
    assert child.options["simulation_engine"] == "oasis-legacy"


def test_admitted_options_reach_existing_world_prepare_hook(lifecycle_boundary, monkeypatch, tmp_path):  # noqa: F811
    """Fresh admission -> modeler -> seal -> actual v4 child -> committed API result."""
    import httpx
    from openai import OpenAI
    from app.config import Config
    from app.services.world_simulation import policy
    from app.services.world_simulation.contracts import canonical_json, digest
    from app.services.world_simulation.review import MODE_V4, normalize_v4_assessment_output
    from app.services.world_simulation.store import WorldStore
    from test_world_compiler import proposal
    from test_world_consistency_v3_policy import _assessment
    b = lifecycle_boundary
    monkeypatch.setattr(Config, "DEFAULT_SIMULATION_ENGINE", "world-v1")
    monkeypatch.setattr(Config, "WORLD_POLICY_SPEC_PATH", str(write_profile(tmp_path)))
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "diagnostic_only")
    monkeypatch.setattr(b.po, "TaskManager", lambda: SimpleNamespace(
        create_task=lambda **kw: "task_fixture", update_task=lambda *args, **kw: None))
    monkeypatch.setattr(b.po, "threading", SimpleNamespace(
        Event=threading.Event, Lock=threading.Lock,
        Thread=lambda **kw: SimpleNamespace(start=lambda: None)))
    monkeypatch.setattr(b.po.PipelineOrchestrator, "_threads", {})
    monkeypatch.setattr(b.po.PipelineOrchestrator, "_cancel_events", {})
    # Observe the actual SDK wire for both transports. The lifecycle fixture's
    # modeler client/handler stays intact; only actor responses are specialized.
    wire, actor_clients, launched_inputs = [], [], []
    original_send = httpx.Client.send

    def observe_send(client, request, *args, **kwargs):
        wire.append(json.loads(request.content))
        return original_send(client, request, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", observe_send)

    def actor_dispatch(request):
        body = json.loads(request.content)
        observation = json.loads(body["messages"][-1]["content"])
        b.sent.append(observation)
        decision = {"actorId": observation["actorId"], "observationId": observation["observationId"],
                    "intents": [], "status": "wait"}
        revision = policy._REVIEW_CANDIDATE_PREFIX in body["messages"][0]["content"]
        content = {"decision": decision, "assessment": _assessment()} if revision else decision
        return httpx.Response(200, json={
            "id": "fixture-actor", "object": "chat.completion", "created": 0, "model": "fixture-model-v1",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": json.dumps(content)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
        })

    def actor_build_client(self, config):
        http = httpx.Client(transport=httpx.MockTransport(actor_dispatch), follow_redirects=False, trust_env=False)
        actor_clients.append(http)
        return OpenAI(api_key="synthetic-test-key", base_url=self.base_url, http_client=http, max_retries=0)

    monkeypatch.setattr(policy.StrictHTTPPolicy, "_build_client", actor_build_client)

    def on_launch(directory):
        assert len(wire) == len(b.sent) == 1  # modeling only; no actor call before the child
        launched_inputs.append(json.loads((directory / "world_spec.json").read_text()))
        assert launched_inputs[-1]["policy"]["decisionReview"] == MODE_V4
        assert launched_inputs[-1]["policy"]["responseFormat"] == "json_object"

    b.behavior.on_launch = on_launch
    state = b.po.PipelineOrchestrator.start("Synthetic lifecycle test")
    assert b.sent == [] and b.launches == [] and wire == []
    admitted = deepcopy(state.options)
    b.behavior.model_candidate = proposal()
    sim = b.po.PipelineOrchestrator()._run_world_stages(
        state, SimpleNamespace(project_id="project_fixture", ontology={"entity_types": []}),
        "graph_fixture", b.actors, b.report)
    assert state.stages["prepare"].status == state.stages["run"].status == "completed"
    assert len(b.sent) == len(wire) == 3 and len(b.launches) == 1  # modeler, candidate, revision
    assert b.sent[0]["requirement"] == state.prompt
    assert b.sent[1] == b.sent[2] and b.sent[1]["actorId"] == "a"
    directory = b.root / state.simulation_id
    sealed = json.loads((directory / "world_spec.json").read_text())
    assert sealed == launched_inputs[0]
    assert sealed["policy"] == admitted["world_policy_spec"]["policy"]
    assert state.options["world_policy_spec"] == admitted["world_policy_spec"]
    assert state.options["simulation_admission_v1"] == admitted["simulation_admission_v1"]
    assert sealed["forecastEffect"] == admitted["safety_policy_v1"]["simulation_forecast_effect"]
    assert sealed["limits"]["maxTokens"] == admitted["world_policy_spec"]["limits"]["maxTokens"] - 140
    assert actor_clients and all(client.is_closed for client in actor_clients)
    with WorldStore(directory / "world.sqlite3", read_only=True) as store:
        assert store.head()["round"] == len(sealed["periods"]) == 1
        receipt = store.consistency_receipt("1:proposal:a")
        assert receipt["mode"] == MODE_V4 and receipt["assessment"] == normalize_v4_assessment_output(_assessment())
        assert [(stage["stage"], stage["status"]) for stage in receipt["stages"]] == [
            ("candidate", "succeeded"), ("revision", "succeeded")]
        assert all(stage["usage"]["tokens"] == 140 for stage in receipt["stages"])
        assert store.decision("1:proposal:a")["decisionId"] == receipt["finalDecisionId"]

    for body in wire:
        assert set(body) == {"model", "messages", "n", "stream", "max_completion_tokens", "response_format"}
        assert body["model"] == sealed["policy"]["model"]
        assert body["response_format"] == {"type": "json_object"}
        assert body["n"] == 1 and body["stream"] is False and body["max_completion_tokens"] == 512
    assert json.loads(wire[0]["messages"][-1]["content"]) == b.sent[0]
    maximum = sealed["limits"]["maxIntentsPerPhase"]
    assert wire[1]["messages"] == [
        {"role": "system", "content": policy._SYSTEM + f"Use at most {maximum} intents."},
        {"role": "user", "content": canonical_json(b.sent[1])},
    ]
    assert wire[2]["messages"] == [
        {"role": "system", "content": policy._REVIEW_SYSTEM_V3
         + f"Use at most {maximum} intents in decision."
         + policy._REVIEW_CANDIDATE_PREFIX + canonical_json(receipt["candidate"])},
        {"role": "user", "content": canonical_json(b.sent[1])},
    ]
    result = b.service.WorldSimulationService.require_complete(sim.simulation_id)
    view = b.client.get(f"/api/simulation/{sim.simulation_id}/world")
    assert view.status_code == 200, view.json
    assert view.json["data"] == result
    manifest = json.loads((directory / "world_result_manifest.json").read_text())
    projection = json.loads((directory / "world_run.json").read_text())
    assert result["completed"] is True and result["committedRound"] == result["totalRounds"] == 1
    assert result["generationId"] == manifest["generationId"] == projection["generation_id"] == sealed["generationId"]
    assert sim.world_generation_id == result["generationId"]
    assert result["specHash"] == digest(sealed) and manifest["revision"] == result["revision"]
    assert b.runner.get_run_state(sim.simulation_id).runner_status.value == "completed"
    saved = b.po.PipelineManager.load(state.pipeline_id)
    assert saved["stages"]["run"]["status"] == "completed"
    assert len(b.sent) == len(wire) == 3 and len(b.launches) == 1  # reads cannot redispatch


def test_export_real_preflight_responses_for_browser(launch, offline_http, monkeypatch, tmp_path):  # noqa: F811
    """Write actual Flask GET envelopes only when the coordinator runs the guard."""
    import sys
    guard = sys.modules.get("main_offline_guard")
    assert guard is not None, "Browser fixtures require the coordinator's guarded runner"
    b = launch
    monkeypatch.setattr(b.config, "DEFAULT_SIMULATION_ENGINE", "world-v1")
    monkeypatch.setattr(b.config, "WORLD_POLICY_SPEC_PATH", str(write_profile(tmp_path)))
    fixture = {"schemaVersion": "research-preflight-browser-fixtures/v1", "responses": {}}
    for name, query, ready, engine in [
        ("configured_world", {"mode": "full", "model": "codex"}, True, "world-v1"),
        ("explicit_legacy", {"mode": "full", "model": "codex", "simulation_engine": "oasis-legacy"}, True, "oasis-legacy"),
        ("missing_profile", {"mode": "full", "model": "codex"}, False, "world-v1"),
    ]:
        if name == "missing_profile":
            monkeypatch.setattr(b.config, "WORLD_POLICY_SPEC_PATH", None)
        response = b.client.get("/api/research/preflight", query_string=query)
        body = response.get_json()
        assert response.status_code == 200 and body["success"] is True
        assert body["data"]["ready"] is ready and body["data"]["simulation_engine"] == engine
        assert body["data"]["default_simulation_engine"] == "world-v1"
        fixture["responses"][name] = {
            "method": "GET", "path": "/api/research/preflight", "query": query,
            "status": response.status_code, "body": body,
        }
    assert fixture["responses"]["missing_profile"]["body"]["data"]["simulation_admission"]["error_code"] == "world_configuration_required"
    encoded = json.dumps(fixture, ensure_ascii=False, indent=2) + "\n"
    assert str(tmp_path) not in encoded and "baseUrl" not in encoded and "fixture-only-secret" not in encoded
    path = guard.root / "research-preflight-browser-fixture.json"
    path.write_text(encoded, encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8")) == fixture
    assert_unstarted(b)
    assert offline_http.sent == []


@pytest.fixture
def admitted_handoff_candidate(lifecycle_boundary, monkeypatch, tmp_path):  # noqa: F811
    """Observe real fresh preparation; stop before the unrelated actor-run stage."""
    from app.config import Config
    from app.services.simulation_manager import SimulationManager
    from test_world_compiler import proposal
    b = lifecycle_boundary
    monkeypatch.setattr(Config, "DEFAULT_SIMULATION_ENGINE", "world-v1")
    monkeypatch.setattr(Config, "WORLD_POLICY_SPEC_PATH", str(write_profile(tmp_path)))
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "diagnostic_only")
    monkeypatch.setattr(b.po, "TaskManager", lambda: SimpleNamespace(
        create_task=lambda **kw: "task_fixture", update_task=lambda *args, **kw: None))
    monkeypatch.setattr(b.po, "threading", SimpleNamespace(
        Event=threading.Event, Lock=threading.Lock,
        Thread=lambda **kw: SimpleNamespace(start=lambda: None)))
    monkeypatch.setattr(b.po.PipelineOrchestrator, "_threads", {})
    monkeypatch.setattr(b.po.PipelineOrchestrator, "_cancel_events", {})
    state = b.po.PipelineOrchestrator.start("Fixture admitted handoff candidate")
    assert b.sent == [] and b.launches == [] and state.simulation_id is None
    admitted = deepcopy(state.options["world_policy_spec"])
    admission = deepcopy(state.options["simulation_admission_v1"])
    candidate = {**proposal(), **deepcopy(admitted)}
    effects = []
    original_create, original_seal = SimulationManager.create_simulation, b.service.seal_inputs

    def create(manager, *args, **kwargs):
        effects.append("create_simulation")
        return original_create(manager, *args, **kwargs)

    def seal(*args, **kwargs):
        effects.append("seal_inputs")
        return original_seal(*args, **kwargs)

    class PreparedBoundary(Exception):
        pass

    def stop_before_actors(*args, **kwargs):
        effects.append("actor_run_boundary")
        raise PreparedBoundary()

    monkeypatch.setattr(SimulationManager, "create_simulation", create)
    monkeypatch.setattr(b.service, "seal_inputs", seal)
    monkeypatch.setattr(b.po.PipelineOrchestrator, "_wait_world_simulation", stop_before_actors)

    def prepare():
        return b.po.PipelineOrchestrator()._run_world_stages(
            state, SimpleNamespace(project_id="project_fixture", ontology={"entity_types": []}),
            "graph_fixture", b.actors, b.report)

    return SimpleNamespace(b=b, state=state, admitted=admitted, admission=admission,
                           candidate=candidate, effects=effects, prepare=prepare,
                           stop=PreparedBoundary,
                           path=Path(state.handoff_dir) / "world_modeling_candidate.json")


@pytest.mark.parametrize("conflict", [
    "v2_review", "missing_json_format", "increased_tokens", "increased_usd", "unbound",
    "changed_effect", "missing_effect", "changed_policy_field",
])
def test_fresh_handoff_candidate_cannot_replace_admitted_authority(admitted_handoff_candidate, conflict):
    from app.services.world_simulation.contracts import WorldError
    case = admitted_handoff_candidate
    raw = case.candidate
    if conflict == "v2_review":
        raw["policy"]["decisionReview"] = "actor-consistency-v2"
    elif conflict == "missing_json_format":
        raw["policy"].pop("responseFormat")
    elif conflict == "increased_tokens":
        raw["limits"]["maxTokens"] += 1
    elif conflict == "increased_usd":
        raw["limits"]["maxCostUsd"] = "500"
    elif conflict == "changed_effect":
        raw["forecastEffect"] = "no_update"
    elif conflict == "missing_effect":
        raw.pop("forecastEffect")
    elif conflict == "changed_policy_field":
        raw["policy"]["reasoningEffort"] = "low" if raw["policy"].get("reasoningEffort") == "high" else "high"
    else:
        for key in ("policy", "limits", "forecastEffect"):
            raw.pop(key)
    case.path.write_text(json.dumps({"world_spec": raw}), encoding="utf-8")
    candidate_bytes = case.path.read_bytes()
    before = {str(path.relative_to(case.b.root)): path.read_bytes()
              for path in case.b.root.rglob("*") if path.is_file()}
    failure = None
    try:
        case.prepare()
    except WorldError as error:
        failure = error
    except case.stop:
        # The current defect reaches this point after creating/sealing the
        # conflicting candidate. Preserve that concrete RED boundary evidence.
        pass
    assert case.effects == [], f"{conflict} crossed world side-effect boundaries: {case.effects}"
    assert failure is not None, "Conflicting or unbound candidate must fail closed with WorldError"
    assert case.state.simulation_id is None
    assert case.b.sent == [] and case.b.launches == []
    assert {str(path.relative_to(case.b.root)): path.read_bytes()
            for path in case.b.root.rglob("*") if path.is_file()} == before
    assert case.path.read_bytes() == candidate_bytes
    assert case.state.options["world_policy_spec"] == case.admitted
    assert case.state.options["simulation_admission_v1"] == case.admission


def test_fresh_handoff_candidate_matching_admitted_authority_is_allowed(admitted_handoff_candidate):
    case = admitted_handoff_candidate
    case.path.write_text(json.dumps({"world_spec": case.candidate}), encoding="utf-8")
    candidate_bytes = case.path.read_bytes()
    with pytest.raises(case.stop):
        case.prepare()
    assert case.effects == ["create_simulation", "seal_inputs", "actor_run_boundary"]
    assert case.state.stages["prepare"].status == "completed"
    assert case.b.sent == [] and case.b.launches == []  # raw candidate bypasses the modeler
    sealed = json.loads((case.b.root / case.state.simulation_id / "world_spec.json").read_text())
    for key in ("policy", "limits", "forecastEffect"):
        assert sealed[key] == case.admitted[key]
    assert case.state.options["world_policy_spec"] == case.admitted
    assert case.state.options["simulation_admission_v1"] == case.admission
    assert case.path.read_bytes() == candidate_bytes
