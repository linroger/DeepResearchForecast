"""TIME-7: hindcast admission (validated as_of, fail-closed gating, pinned policy).

A run request may carry ``as_of`` (a past-or-today date the question is answered
as of). ``/api/research/run``, ``/api/v1/run`` and ``PipelineOrchestrator.start``
admit it only when HINDCAST_ENABLED is on, the date is canonical and not in the
future, and the run's research engine is v3; anything else is refused before a
pipeline directory or task exists, never run live. An admitted hindcast pins
``hindcast_policy_v1`` and runs as an evaluation run (EVAL-13); without as_of
every path is unchanged.

Offline: Flask test client, the background run is a no-op, per-test data dirs.
"""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask

from app.api import research as research_api
from app.api import research_bp, sdk_bp
from app.api import sdk as sdk_api
from app.config import Config
from app.services import hindcast_policy as hp
from app.services import pipeline_orchestrator as po
from app.services.report_agent import ReportAgent

QUESTION = "Will the ECB cut its deposit rate below 3% by the end of 2024?"
AS_OF = "2024-06-01"
ROUTES = ("/api/research/run", "/api/v1/run")


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"), raising=False)
    monkeypatch.setattr(Config, "HINDCAST_ENABLED", True, raising=False)
    monkeypatch.setattr(Config, "RESEARCH_ENGINE", "v3", raising=False)
    monkeypatch.setattr(Config, "DEERFLOW_DUAL_TRACK", True, raising=False)
    # Admission is what matters; the background run is a no-op and preflight passes.
    monkeypatch.setattr(po.PipelineOrchestrator, "_run", classmethod(lambda cls, state: None))
    monkeypatch.setattr(research_api, "preflight_pipeline", lambda **kwargs: [])
    monkeypatch.setattr(sdk_api, "preflight_pipeline", lambda **kwargs: [])
    return tmp_path


@pytest.fixture
def client(env):
    app = Flask(__name__)
    app.register_blueprint(research_bp, url_prefix="/api/research")
    app.register_blueprint(sdk_bp, url_prefix="/api/v1")
    return app.test_client()


@pytest.fixture
def no_tasks(monkeypatch):
    class _NoTasks:
        def __init__(self):
            pytest.fail("a task was created for a refused hindcast")

    monkeypatch.setattr(po, "TaskManager", _NoTasks)


@pytest.fixture
def start_calls(monkeypatch):
    """Record every PipelineOrchestrator.start call's kwargs, then run the real start."""
    calls = []
    real = po.PipelineOrchestrator.start

    def spy(cls, *args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(po.PipelineOrchestrator, "start", classmethod(spy))
    return calls


def _settle(pipeline_id):
    thread = po.PipelineOrchestrator._threads.pop(pipeline_id, None)
    if thread is not None:
        thread.join(timeout=5)
    po.PipelineOrchestrator._cancel_events.pop(pipeline_id, None)


def _start(**kwargs):
    state = po.PipelineOrchestrator.start(QUESTION, mode="full", **kwargs)
    _settle(state.pipeline_id)
    return state


def _future():
    return (datetime.now(timezone.utc).date() + timedelta(days=2)).isoformat()


def _post(client, route, **fields):
    return client.post(route, data=json.dumps({"prompt": QUESTION, **fields}),
                       content_type="application/json")


def _without_volatile(options, pipeline_id):
    """Options with the pipeline id and admission timestamps neutralised."""
    data = json.loads(json.dumps(options, sort_keys=True).replace(pipeline_id, "<pid>"))

    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k != "pinned_at"}
        return node
    return strip(data)


# ───────────────────────────── API: fail closed ─────────────────────────────
@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("setup, as_of, error", [
    ({"HINDCAST_ENABLED": False}, AS_OF, "as_of requires HINDCAST_ENABLED=true"),
    # The switch is checked first: a malformed date with the switch off names the switch.
    ({"HINDCAST_ENABLED": False}, "2024-6-1", "as_of requires HINDCAST_ENABLED=true"),
    ({}, "2024-6-1", "as_of must be a canonical YYYY-MM-DD date"),
    ({}, "2024-06-01 00:00", "as_of must be a canonical YYYY-MM-DD date"),
    ({}, 20240601, "as_of must be a canonical YYYY-MM-DD date"),
    ({}, "", "as_of must be a canonical YYYY-MM-DD date"),
    ({}, "FUTURE", "as_of cannot be in the future"),
    ({"RESEARCH_ENGINE": "legacy"}, AS_OF, "hindcast runs require the v3 research engine"),
])
def test_route_refuses_an_inadmissible_as_of_before_anything_exists(
        client, monkeypatch, no_tasks, start_calls, route, setup, as_of, error):
    for name, value in setup.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    if as_of == "FUTURE":
        as_of = _future()

    response = _post(client, route, as_of=as_of)

    assert response.status_code == 400
    assert response.get_json() == {"success": False, "error": error}
    assert start_calls == []
    assert not os.path.exists(Config.PIPELINE_DATA_DIR)


@pytest.mark.parametrize("route", ROUTES)
def test_route_admits_a_valid_as_of_and_start_pins_it(client, start_calls, route):
    response = _post(client, route, as_of=AS_OF, mode="research_only")

    assert response.status_code == 200, response.get_json()
    body = response.get_json()["data"]
    _settle(body["pipeline_id"])
    assert [call.get("as_of") for call in start_calls] == [AS_OF]
    persisted = po.PipelineManager.load(body["pipeline_id"])
    pin = persisted["options"][hp.HINDCAST_POLICY_OPTION]
    assert pin["as_of"] == AS_OF and pin["hindcast"] is True and pin["research_engine"] == "v3"
    assert persisted["options"][po.EVALUATION_RUN_OPTION]["eval_run_id"] == "hindcast_20240601"


@pytest.mark.parametrize("route", ROUTES)
def test_route_without_as_of_is_unchanged(client, start_calls, route):
    response = _post(client, route)

    assert response.status_code == 200
    pipeline_id = response.get_json()["data"]["pipeline_id"]
    _settle(pipeline_id)
    assert [call.get("as_of") for call in start_calls] == [None]
    options = po.PipelineManager.load(pipeline_id)["options"]
    assert hp.HINDCAST_POLICY_OPTION not in options and po.EVALUATION_RUN_OPTION not in options


@pytest.mark.parametrize("route", ROUTES)
def test_route_maps_only_an_admission_refusal_from_start_to_400(client, monkeypatch, route):
    raised = {}

    def start(cls, *args, **kwargs):
        raise raised["error"]

    monkeypatch.setattr(po.PipelineOrchestrator, "start", classmethod(start))

    raised["error"] = po.RunAdmissionError("refused at admission")
    hindcast = _post(client, route, as_of=AS_OF)
    assert hindcast.status_code == 400
    assert hindcast.get_json() == {"success": False, "error": "refused at admission"}
    # Any other ValueError from start() is an internal fault: today's 500, with or
    # without as_of.
    raised["error"] = ValueError("internal fault")
    for fields in ({"as_of": AS_OF}, {}):
        response = _post(client, route, **fields)
        assert response.status_code == 500 and response.get_json()["error"] == "internal fault"


@pytest.mark.parametrize("route", ROUTES)
def test_route_reports_a_fault_after_admission_as_500(client, monkeypatch, route):
    """A ValueError raised once start() is creating the pipeline (here: the safety-policy
    snapshot) is not a client error, even for a request carrying as_of."""
    def broken_snapshot(origin):
        raise ValueError("safety snapshot unavailable")

    monkeypatch.setattr(po, "capture_safety_policy_v1", broken_snapshot)

    response = _post(client, route, as_of=AS_OF)

    assert response.status_code == 500
    assert response.get_json()["error"] == "safety snapshot unavailable"


# ───────────────────────────── start(): the single constructor ──────────────
@pytest.mark.parametrize("setup, as_of, error", [
    ({"HINDCAST_ENABLED": False}, AS_OF, "HINDCAST_ENABLED"),
    ({}, "2024-6-1", "canonical"),
    ({}, "FUTURE", "in the future"),
    ({"RESEARCH_ENGINE": "legacy"}, AS_OF, "v3 research engine"),
])
def test_start_refuses_before_any_dir_task_or_thread(env, monkeypatch, no_tasks, setup, as_of, error):
    for name, value in setup.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    if as_of == "FUTURE":
        as_of = _future()
    threads_before = dict(po.PipelineOrchestrator._threads)

    with pytest.raises(po.RunAdmissionError, match=error):
        po.PipelineOrchestrator.start(QUESTION, as_of=as_of)

    assert not os.path.exists(Config.PIPELINE_DATA_DIR)
    assert po.PipelineOrchestrator._threads == threads_before


def test_start_pins_the_hindcast_and_an_evaluation_run(env):
    state = _start(as_of=AS_OF)

    persisted = po.PipelineManager.load(state.pipeline_id)
    pin = persisted["options"][hp.HINDCAST_POLICY_OPTION]
    assert pin == state.options[hp.HINDCAST_POLICY_OPTION]
    assert {key: pin[key] for key in ("version", "origin", "as_of", "hindcast", "research_engine",
                                      "markets", "fetch", "search")} == {
        "version": hp.HINDCAST_POLICY_VERSION, "origin": "admission", "as_of": AS_OF,
        "hindcast": True, "research_engine": "v3", "markets": "withheld", "fetch": "label",
        "search": "unbounded"}
    assert hp.hindcast_policy(persisted["options"]) == pin
    # The actor policy the engine check used is the one pinned (v3: not required).
    actor_policy = persisted["options"]["actor_intelligence_policy_v1"]
    assert actor_policy["research_engine"] == "v3" and actor_policy["required"] is False
    # EVAL-13's single admission path: option pin plus the handoff marker.
    evaluation = persisted["options"][po.EVALUATION_RUN_OPTION]
    assert evaluation["eval_run_id"] == "hindcast_20240601"
    assert evaluation["record_class"] == "evaluation" and evaluation["characterization_only"] is True
    marker = os.path.join(po.PipelineManager.handoff_dir(state.pipeline_id), po.EVALUATION_RUN_MARKER)
    with open(marker, encoding="utf-8") as fh:
        assert json.load(fh) == dict(evaluation, pipeline_id=state.pipeline_id)


def test_start_keeps_the_callers_evaluation_context(env):
    state = _start(as_of=AS_OF, evaluation={"eval_run_id": "golden-sweep", "cell_id": "c1"})
    options = po.PipelineManager.load(state.pipeline_id)["options"]
    assert options[po.EVALUATION_RUN_OPTION]["eval_run_id"] == "golden-sweep"
    assert options[po.EVALUATION_RUN_OPTION]["cell_id"] == "c1"
    assert options[hp.HINDCAST_POLICY_OPTION]["as_of"] == AS_OF


def test_start_refuses_an_invalid_evaluation_with_a_valid_as_of(env, no_tasks):
    with pytest.raises(po.RunAdmissionError):
        po.PipelineOrchestrator.start(QUESTION, as_of=AS_OF, evaluation={"eval_run_id": "../x"})
    assert not os.path.exists(Config.PIPELINE_DATA_DIR)


def test_admission_refusals_are_value_errors(monkeypatch):
    """Callers that catch ValueError (scripts, EVAL-13 users) keep working."""
    monkeypatch.setattr(Config, "HINDCAST_ENABLED", False, raising=False)
    assert issubclass(po.RunAdmissionError, ValueError)
    with pytest.raises(po.RunAdmissionError, match="HINDCAST_ENABLED"):
        po.admit_hindcast_as_of(AS_OF)


def test_as_of_today_is_admitted_but_pinned_live(env):
    today = datetime.now(timezone.utc).date().isoformat()
    state = _start(as_of=today)
    options = po.PipelineManager.load(state.pipeline_id)["options"]
    assert options[hp.HINDCAST_POLICY_OPTION]["hindcast"] is False
    assert hp.hindcast_policy(options) is None


def test_start_without_as_of_is_identical_to_today(env, monkeypatch):
    omitted = _start()
    explicit = _start(as_of=None)
    for state in (omitted, explicit):
        options = po.PipelineManager.load(state.pipeline_id)["options"]
        assert hp.HINDCAST_POLICY_OPTION not in options and po.EVALUATION_RUN_OPTION not in options
        assert os.listdir(po.PipelineManager.handoff_dir(state.pipeline_id)) == []
    assert (_without_volatile(po.PipelineManager.load(omitted.pipeline_id)["options"],
                              omitted.pipeline_id)
            == _without_volatile(po.PipelineManager.load(explicit.pipeline_id)["options"],
                                 explicit.pipeline_id))
    # With the switch off (its default), a live start does not even consult it.
    monkeypatch.setattr(Config, "HINDCAST_ENABLED", False)
    live = _start()
    assert hp.HINDCAST_POLICY_OPTION not in po.PipelineManager.load(live.pipeline_id)["options"]


def test_resume_keeps_both_pins(env):
    state = _start(as_of=AS_OF)
    before = po.PipelineManager.load(state.pipeline_id)["options"]
    po.PipelineManager.mark_failed(state.pipeline_id, "research failed")

    resumed = po.PipelineOrchestrator.resume(state.pipeline_id)
    _settle(resumed.pipeline_id)

    after = po.PipelineManager.load(state.pipeline_id)["options"]
    assert after[hp.HINDCAST_POLICY_OPTION] == before[hp.HINDCAST_POLICY_OPTION]
    assert after[po.EVALUATION_RUN_OPTION] == before[po.EVALUATION_RUN_OPTION]
    assert after["resume_count"] == 1


def test_fork_of_an_admitted_hindcast_carries_both_pins(env):
    state = _start(as_of=AS_OF)
    base = po.PipelineState.from_dict(po.PipelineManager.load(state.pipeline_id))
    base.graph_id = "graph_1"
    po.PipelineManager.save(base)
    before = po.PipelineManager.load(state.pipeline_id)["options"]

    fork = po.PipelineOrchestrator.fork(state.pipeline_id, {"label": "Surprise hike"})
    _settle(fork.pipeline_id)

    after = po.PipelineManager.load(fork.pipeline_id)["options"]
    assert after[hp.HINDCAST_POLICY_OPTION] == before[hp.HINDCAST_POLICY_OPTION]
    assert after[po.EVALUATION_RUN_OPTION]["eval_run_id"] == "hindcast_20240601"
    assert after[po.EVALUATION_RUN_OPTION]["record_class"] == "evaluation"


def test_api_regenerate_of_a_hindcast_report_resolves_both_pins(env):
    """/api/report/generate builds a ReportAgent without orchestrator context: it
    finds the evaluation run and the hindcast pin through the simulation's owner."""
    state = _start(as_of=AS_OF)
    persisted = po.PipelineState.from_dict(po.PipelineManager.load(state.pipeline_id))
    persisted.simulation_id = "sim_hindcast"
    po.PipelineManager.save(persisted)
    options = po.PipelineManager.load(state.pipeline_id)["options"]

    context = po.evaluation_context_for_simulation("sim_hindcast")
    assert context == options[po.EVALUATION_RUN_OPTION]
    assert context["eval_run_id"] == "hindcast_20240601"
    assert po.hindcast_pin_for_simulation("sim_hindcast") == options[hp.HINDCAST_POLICY_OPTION]

    agent = ReportAgent.__new__(ReportAgent)
    agent.simulation_id = "sim_hindcast"
    assert agent._resolve_evaluation_context() == context
    assert agent._hindcast_pin() == options[hp.HINDCAST_POLICY_OPTION]


def test_config_default_and_env_example():
    assert Config.HINDCAST_ENABLED is False
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    with open(os.path.join(root, ".env.example"), encoding="utf-8") as fh:
        assert "# HINDCAST_ENABLED=false " in fh.read()
