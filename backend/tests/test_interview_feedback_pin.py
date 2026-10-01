"""FU-8 (INFRA-9 open issue): the run's pinned safety policy governs interview graph feedback.

``capture_safety_policy_v1`` pins ``sim_interview_graph_feedback`` at admission (forks
inherit the pin). End-of-simulation interview answers reach the observed graph only
through ``ZepToolsService.interview_agents`` -> ``ZepGraphMemoryUpdater.write_interview_fact``,
and both follow the run's pin rather than the ambient ``Config.SIM_INTERVIEW_GRAPH_FEEDBACK``:

- the orchestrator's main and seed reports get the resolved gate as the
  ``interview_graph_feedback`` ReportAgent kwarg (a seed's simulation has no persisted
  owner while its report runs, so a by-simulation lookup would read the ambient value);
- report entry points without orchestrator context (``/api/report`` regenerate and chat)
  look the pin up by simulation id, following a shared-simulation child to its base;
- no pin -> the ambient value (unpinned runs unchanged); a failed lookup or a damaged
  pin -> no feedback, with a warning.

Offline: temp pipeline states, stubbed services, no network, no LLM.
"""

import sys

import pytest

from app.config import Config
from app.services import pipeline_orchestrator as po
from app.services import zep_graph_memory_updater as zgmu
from app.services import zep_tools
from app.services.report_agent import ReportAgent, ReportManager
from app.services.simulation_runner import SimulationRunner
from tests.conftest import FakeLLMClient

INTERVIEW_ANSWER = "终局反思陈述，供测试使用的足够长的一句话内容。"


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"), raising=False)
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"), raising=False)
    monkeypatch.setattr(po.PipelineOrchestrator, "_run", classmethod(lambda cls, state: None))
    return tmp_path


def _ambient(monkeypatch, value):
    monkeypatch.setattr(Config, "SIM_INTERVIEW_GRAPH_FEEDBACK", value, raising=False)


def _policy(**fields):
    return {"version": po.SAFETY_POLICY_VERSION, "origin": "admission", **fields}


def _recorded(monkeypatch, logger, level):
    """Messages ``logger.<level>`` receives (project loggers do not propagate to caplog)."""
    messages = []
    monkeypatch.setattr(logger, level,
                        lambda msg, *args, **kwargs: messages.append(msg % args if args else msg))
    return messages


def _save_pipeline(pipeline_id, simulation_id, *, created_at, **options):
    state = po.PipelineState(pipeline_id=pipeline_id, prompt="q")
    state.simulation_id = simulation_id
    state.created_at = created_at
    state.options.update(options)
    po.PipelineManager.save(state)
    return state


def _interview_service(monkeypatch, written):
    """A ZepToolsService whose OASIS batch, persona and LLM helpers are stubbed; the graph
    writer records ``(agent, feedback_allowed)`` for every fact it is asked to write."""

    class _Updater:
        def __init__(self, graph_id):
            self.graph_id = graph_id

        def write_interview_fact(self, name, statement, valid_at=None, *, feedback_allowed=None):
            written.append((name, feedback_allowed))
            return True

    monkeypatch.setattr(zgmu, "ZepGraphMemoryUpdater", _Updater)
    monkeypatch.setattr(SimulationRunner, "interview_agents_batch", classmethod(
        lambda cls, **kw: {"success": True, "interviews_count": 1, "result": {"results": {
            "twitter_0": {"response": INTERVIEW_ANSWER}}}}))
    service = zep_tools.ZepToolsService.__new__(zep_tools.ZepToolsService)
    profile = {"realname": "ActorA", "profession": "p", "bio": "b"}
    service._load_agent_profiles = lambda sid: [profile]
    service._select_agents_for_interview = lambda **kw: ([profile], [0], "only one")
    service._generate_interview_questions = lambda **kw: ["How did it end?"]
    service._generate_interview_summary = lambda **kw: "summary"
    service.invalidate_search_cache = lambda graph_id=None: None
    return service


# ─────────────────────────────── the graph writer ───────────────────────────────
def test_writer_follows_the_callers_resolved_gate(monkeypatch):
    """An explicit feedback_allowed (the run's pinned gate) overrides the ambient Config
    both ways and only a real True allows; None keeps the ambient gate. The refusal log
    names the source that refused."""

    class _FakeGraph:
        def __init__(self):
            self.triplets = []

        def add_triplet(self, *a, **k):
            self.triplets.append((a, k))

    stub = zgmu.ZepGraphMemoryUpdater.__new__(zgmu.ZepGraphMemoryUpdater)
    stub.graph_id = "g_test"
    stub.client = type("_C", (), {"graph": _FakeGraph()})()
    debug = _recorded(monkeypatch, zgmu.logger, "debug")

    _ambient(monkeypatch, True)
    assert stub.write_interview_fact("ActorA", "x", feedback_allowed=False) is False
    assert stub.write_interview_fact("ActorA", "x", feedback_allowed="true") is False
    assert stub.client.graph.triplets == []
    assert len(debug) == 2
    assert all("钉住的安全政策" in m and "SIM_INTERVIEW_GRAPH_FEEDBACK" not in m for m in debug)
    assert "feedback_allowed=False" in debug[0] and "feedback_allowed='true'" in debug[1]

    _ambient(monkeypatch, False)
    assert stub.write_interview_fact("ActorA", "x", feedback_allowed=True) is True
    assert len(stub.client.graph.triplets) == 1
    del debug[:]
    assert stub.write_interview_fact("ActorA", "x") is False      # None: the ambient gate
    assert debug == ["采访事实写入被 SIM_INTERVIEW_GRAPH_FEEDBACK=false 拒绝（Foglamp 1A/I-11）"]


# ──────────────────────────── the by-simulation lookup ──────────────────────────
def test_lookup_pin_beats_ambient_and_no_pin_reads_ambient(monkeypatch):
    owners = {}
    monkeypatch.setattr(po, "_ledger_owner_of_simulation", lambda sid: owners.get(sid))

    def owned(options):
        return ("pipe_x", {"simulation_id": "other", "options": options}, False, None)

    owners.update({
        "sim_off": owned({"safety_policy_v1": _policy(sim_interview_graph_feedback=False)}),
        "sim_on": owned({"safety_policy_v1": _policy(sim_interview_graph_feedback=True)}),
        "sim_legacy": owned({"safety_policy_v1": _policy(sim_graph_feedback=False)}),
        "sim_bare": owned({}),
    })
    _ambient(monkeypatch, True)
    assert po.interview_graph_feedback_for_simulation("sim_off") is False
    assert po.interview_graph_feedback_for_simulation("sim_legacy") is True   # no key -> ambient
    assert po.interview_graph_feedback_for_simulation("sim_bare") is True     # no pin -> ambient
    assert po.interview_graph_feedback_for_simulation("sim_unknown") is True  # no owner -> ambient
    _ambient(monkeypatch, False)
    assert po.interview_graph_feedback_for_simulation("sim_on") is True
    for unpinned in ("sim_legacy", "sim_bare", "sim_unknown", None, ""):
        assert po.interview_graph_feedback_for_simulation(unpinned) is False


def test_lookup_failure_and_damaged_pins_fail_closed_with_a_warning(monkeypatch):
    warnings = _recorded(monkeypatch, po.logger, "warning")
    _ambient(monkeypatch, True)

    def boom(sid):
        raise OSError("pipeline dir unreadable")

    monkeypatch.setattr(po, "_ledger_owner_of_simulation", boom)
    assert po.interview_graph_feedback_for_simulation("sim_on") is False
    assert len(warnings) == 1 and "sim_on" in warnings[0] and "pipeline dir unreadable" in warnings[0]

    # A hand-edited or corrupted pin never enables graph writes (bool('false') would).
    owners = {
        "sim_str": {"safety_policy_v1": _policy(sim_interview_graph_feedback="false")},
        "sim_int": {"safety_policy_v1": _policy(sim_interview_graph_feedback=1)},
        "sim_list_policy": {"safety_policy_v1": ["sim_interview_graph_feedback", True]},
    }
    monkeypatch.setattr(po, "_ledger_owner_of_simulation", lambda sid: (
        "pipe_x", {"simulation_id": sid, "options": owners[sid]}, False, None))
    for simulation_id in owners:
        del warnings[:]
        assert po.interview_graph_feedback_for_simulation(simulation_id) is False, simulation_id
        assert len(warnings) == 1 and "失败关闭" in warnings[0], (simulation_id, warnings)


def test_lookup_reads_persisted_states_and_follows_a_shared_simulation(env, monkeypatch):
    """Against real pipeline_state.json files: a seed member's simulation follows its
    pipeline's pin once the member map is persisted; a newer shared-simulation child
    without a pinned value defers to the base it borrowed the simulation from (so a
    regeneration of the pinned base's report keeps the base's semantics); a child with
    its own pinned value keeps it; a base that re-ran its simulation no longer answers;
    an origin that cannot be read fails closed."""
    warnings = _recorded(monkeypatch, po.logger, "warning")
    _save_pipeline("pipe_off", "sim_off", created_at="2026-09-30T10:00:00+00:00",
                   safety_policy_v1=_policy(sim_interview_graph_feedback=False),
                   ensemble_member_simulations={"sim_off_seed": 7})
    _save_pipeline("pipe_on", "sim_on", created_at="2026-09-30T10:00:01+00:00",
                   safety_policy_v1=_policy(sim_interview_graph_feedback=True))
    _save_pipeline("pipe_rerun", "sim_rerun_new", created_at="2026-09-30T10:00:02+00:00",
                   safety_policy_v1=_policy(sim_interview_graph_feedback=False))
    # Newer shared-simulation batch children (FORK_INHERIT_SAFETY_POLICY=false: no pin).
    _save_pipeline("pipe_off_child", "sim_off", created_at="2026-09-30T11:00:00+00:00",
                   shared_simulation=True, shared_simulation_from="pipe_off")
    _save_pipeline("pipe_on_child", "sim_on", created_at="2026-09-30T11:00:01+00:00",
                   shared_simulation=True, shared_simulation_from="pipe_on",
                   safety_policy_v1=_policy(origin="fork_admission",
                                            sim_interview_graph_feedback=False))
    _save_pipeline("pipe_rerun_child", "sim_rerun_old", created_at="2026-09-30T11:00:02+00:00",
                   shared_simulation=True, shared_simulation_from="pipe_rerun")
    _save_pipeline("pipe_orphan", "sim_orphan", created_at="2026-09-30T11:00:03+00:00",
                   shared_simulation=True, shared_simulation_from="pipe_deleted")

    _ambient(monkeypatch, True)
    assert po.interview_graph_feedback_for_simulation("sim_off") is False        # the base's pin
    assert po.interview_graph_feedback_for_simulation("sim_off_seed") is False   # member map
    assert po.interview_graph_feedback_for_simulation("sim_on") is False         # child's own pin
    assert po.interview_graph_feedback_for_simulation("sim_rerun_old") is True   # no pin -> ambient
    assert warnings == []
    assert po.interview_graph_feedback_for_simulation("sim_orphan") is False     # fail closed
    assert len(warnings) == 1 and "pipe_deleted" in warnings[0]
    _ambient(monkeypatch, False)
    assert po.interview_graph_feedback_for_simulation("sim_rerun_old") is False
    assert po.interview_graph_feedback_for_simulation("sim_unknown") is False


# ─────────────────────────────── zep_tools wiring ───────────────────────────────
def test_zep_tools_gate_uses_the_real_lookup_and_the_explicit_value_wins(monkeypatch):
    """The unpatched zep_tools helper reaches the orchestrator lookup (pin True beats
    ambient False); an explicit feedback_allowed wins over the lookup and only a real
    True allows."""
    asked = []

    def owner(sid):
        asked.append(sid)
        return ("pipe_x", {"simulation_id": sid, "options": {
            "safety_policy_v1": _policy(sim_interview_graph_feedback=True)}}, False, None)

    monkeypatch.setattr(po, "_ledger_owner_of_simulation", owner)
    _ambient(monkeypatch, False)
    assert zep_tools._interview_feedback_allowed("sim_42") is True
    assert asked == ["sim_42"]
    assert zep_tools._interview_feedback_allowed("sim_42", False) is False
    assert zep_tools._interview_feedback_allowed("sim_42", "true") is False
    _ambient(monkeypatch, True)
    monkeypatch.setattr(po, "_ledger_owner_of_simulation", lambda sid: None)
    assert zep_tools._interview_feedback_allowed("sim_42", False) is False
    assert zep_tools._interview_feedback_allowed("sim_42", True) is True
    assert asked == ["sim_42"]   # an explicit value never triggers the lookup


def test_zep_tools_gate_fails_closed_when_the_orchestrator_cannot_be_imported(monkeypatch):
    warnings = _recorded(monkeypatch, zep_tools.logger, "warning")
    _ambient(monkeypatch, True)
    monkeypatch.setitem(sys.modules, "app.services.pipeline_orchestrator", None)
    assert zep_tools._interview_feedback_allowed("sim_42") is False
    assert len(warnings) == 1 and "失败关闭" in warnings[0]


def test_interview_agents_writes_facts_only_when_the_pin_allows(env, monkeypatch):
    """interview_agents with no explicit gate asks the run's pin by simulation id; with
    one (an orchestrator report) it uses it, whatever the lookup or the ambient Config
    would say."""
    written = []
    service = _interview_service(monkeypatch, written)
    _save_pipeline("pipe_off", "sim_off", created_at="2026-09-30T10:00:00+00:00",
                   safety_policy_v1=_policy(sim_interview_graph_feedback=False))
    _save_pipeline("pipe_on", "sim_on", created_at="2026-09-30T10:00:01+00:00",
                   safety_policy_v1=_policy(sim_interview_graph_feedback=True))
    cases = [
        ("sim_off", True, None, []),                       # pin False beats ambient True
        ("sim_on", False, None, [("ActorA", True)]),       # pin True beats ambient False
        ("sim_free", True, None, [("ActorA", True)]),      # no owner -> ambient
        ("sim_free", False, None, []),
        ("sim_free", True, False, []),                     # explicit gate beats the lookup
        ("sim_free", False, True, [("ActorA", True)]),
    ]
    for simulation_id, ambient, gate, expected in cases:
        del written[:]
        _ambient(monkeypatch, ambient)
        result = service.interview_agents(simulation_id, "topic", graph_id="g_1",
                                          feedback_allowed=gate)
        assert result.interviewed_count == 1
        assert written == expected, (simulation_id, ambient, gate)
    del written[:]
    _ambient(monkeypatch, True)
    service.interview_agents("sim_on", "topic", graph_id=None)
    assert written == []   # no graph, nothing to write


# ─────────────────────────── ReportAgent and orchestrator ───────────────────────────
def test_report_agent_stores_and_forwards_the_gate(env, monkeypatch):
    """The constructor keeps None (look up) or a strict bool; the interview tool hands it
    to interview_agents, so a seed report whose member map is not on disk yet (the lookup
    reads ambient True) still writes nothing under a False pin."""
    for given, stored in ((None, None), (True, True), (False, False), ("true", False)):
        agent = ReportAgent(graph_id="g1", simulation_id="sim_ctor", simulation_requirement="Q?",
                            llm_client=FakeLLMClient(), zep_tools=object(),
                            interview_graph_feedback=given)
        assert agent.interview_graph_feedback is stored, given

    written = []
    service = _interview_service(monkeypatch, written)
    _ambient(monkeypatch, True)
    assert po.interview_graph_feedback_for_simulation("sim_seed") is True   # no persisted owner

    def agent_with(**attrs):
        agent = ReportAgent.__new__(ReportAgent)
        agent.graph_id, agent.simulation_id, agent.simulation_requirement = "g1", "sim_seed", "Q?"
        agent.zep_tools = service
        agent.tools = {"interview_agents": {"name": "interview_agents"}}
        for name, value in attrs.items():
            setattr(agent, name, value)
        return agent

    assert "ActorA" in agent_with(interview_graph_feedback=False)._execute_tool(
        "interview_agents", {"interview_topic": "t"})
    assert written == []
    agent_with()._execute_tool("interview_agents", {"interview_topic": "t"})  # no gate: lookup
    assert written == [("ActorA", True)]
    del written[:]
    _ambient(monkeypatch, False)
    agent_with(interview_graph_feedback=True)._execute_tool(
        "interview_agents", {"interview_topic": "t"})
    assert written == [("ActorA", True)]


def test_seed_reports_get_the_pinned_gate(env, monkeypatch):
    """_run_one_seed hands its ReportAgent the run's pinned gate: the seed simulation's
    owner is only in the in-memory member map while the report runs."""
    constructed = []

    class _Sim:
        simulation_id = "sim_seed"

    class _SimManager:
        def create_simulation(self, *a, **k):
            return _Sim()

        def prepare_simulation(self, **k):
            return None

    class _RunState:
        current_round = 1
        runner_status = po.RunnerStatus.COMPLETED

    class _Runner:
        start_simulation = staticmethod(lambda **k: None)
        get_run_state = staticmethod(lambda sim_id: _RunState())
        write_run_summary = staticmethod(lambda sim_id: None)

    class _FakeAgent:
        def __init__(self, **kwargs):
            constructed.append(kwargs)
            self.ledger_context = None
            self.evaluation_context = None

        def generate_report(self, report_id=None, **kw):
            return None

    monkeypatch.setattr(Config, "SIM_GRAPH_FEEDBACK", False, raising=False)
    monkeypatch.setattr(po, "SimulationManager", _SimManager)
    monkeypatch.setattr(po, "SimulationRunner", _Runner)
    monkeypatch.setattr(po, "ReportAgent", _FakeAgent)
    cases = [
        (_policy(sim_interview_graph_feedback=False), True, False),
        (_policy(sim_interview_graph_feedback=True), False, True),
        (_policy(sim_interview_graph_feedback="false"), True, False),   # damaged: fail closed
        (_policy(), True, True),                                         # no key -> ambient
        (None, False, False),                                            # no pin -> ambient
    ]
    for policy, ambient, expected in cases:
        _ambient(monkeypatch, ambient)
        state = po.PipelineState(pipeline_id="pipe_ens", prompt="q")
        if policy is not None:
            state.options["safety_policy_v1"] = policy
        po.PipelineOrchestrator()._run_one_seed(
            state, type("P", (), {"project_id": "proj"})(), "graph_1", None, {}, "report md",
            seed=11, max_rounds=None)
        assert constructed[-1]["interview_graph_feedback"] is expected, (policy, ambient)
        assert state.options["ensemble_member_simulations"] == {"sim_seed": 11}
        assert po.PipelineManager.load("pipe_ens") is None   # the member map is not on disk


def test_main_report_gets_the_pinned_gate(monkeypatch, tmp_path):
    """The real _run state machine (every service faked) builds the main report agent with
    the run's pinned gate even when the ambient Config says otherwise."""
    from tests.test_orchestrator_research_wiring import _exercise_prepare_run_resume

    created = []

    class _Recording(po.ReportAgent):
        def __new__(cls, *args, **kwargs):
            agent = super().__new__(cls)
            created.append(agent)
            return agent

    monkeypatch.setattr(po, "ReportAgent", _Recording)
    _ambient(monkeypatch, True)
    policy = dict(po.capture_safety_policy_v1("admission"), sim_interview_graph_feedback=False)
    result = _exercise_prepare_run_resume(
        monkeypatch, tmp_path, rebuild_prepare=True, real_run_manifest=True,
        extra_options={"safety_policy_v1": policy})
    assert result.report_generations, "the stage must build a fresh report"
    assert created[-1].kwargs["interview_graph_feedback"] is False
