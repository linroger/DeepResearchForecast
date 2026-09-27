"""Robustness regressions of the deep-research engine v3 (review findings).

F1 deadline-limited transient errors degrade instead of failing the run, F2 a
sticky fallback model retries transient blips, F3 an outage-time template plan
is re-planned on resume, F12 agents cite only sources they were shown, F18
agents keep time for their final notes, F21 KIQs cut short by the deadline are
re-researched on resume, F22 ``--config`` reaches the v3 model factory.

Offline and deterministic: the fakes, fixtures and ``run_engine`` harness of
``test_research_engine_v3`` (scripted model, injected search/fetch, the real
bridge module with prediction markets and charts stubbed), no sleeps.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

import test_research_engine_v3 as v3

# The shared fixtures (hermetic env, real bridge with network steps stubbed).
_hermetic_env = v3._hermetic_env
bridge = v3.bridge
lr = v3.lr
rg = v3.rg


class APIConnectionError(Exception):
    """Same class name as openai.APIConnectionError (classified transient)."""


class APITimeoutError(Exception):
    """Same class name as openai.APITimeoutError (classified transient)."""


def _agent_kiq(call: dict) -> str:
    return call["messages"][2][1].split("Investigate ", 1)[1].split(":", 1)[0]


# =============================================================== F1

def test_single_blip_with_the_synthesis_deadline_nearly_spent_still_publishes(tmp_path, bridge, monkeypatch):
    """One connection reset on the executive summary with ~30 s of synthesis
    left used to become ProviderUnavailable → exit 2 after all the research."""
    monkeypatch.setattr(lr, "PHASE_TIME_SHARE", dict(lr.PHASE_TIME_SHARE, synthesize=30 / 2690))
    blips = {"n": 0}

    def one_blip(call, role):
        if role == "EXECUTIVE SUMMARY TASK" and blips["n"] == 0:
            blips["n"] += 1
            return APIConnectionError("Connection error.")
        return None

    rc, meta, plog, model, out = v3.run_engine(tmp_path, bridge, v3.World(fail=one_blip))
    assert rc == 0, meta.get("error")
    assert meta["status"] == "completed" and "error" not in meta
    assert meta["executive_summary_origin"] == "fallback"
    assert len(v3.calls_of(model, "EXECUTIVE SUMMARY TASK")) == 1
    assert (out / "research_report.md").is_file()
    assert "deadline leaves no room to retry" in plog.text()


def test_agent_timeouts_at_the_gather_deadline_degrade_to_deterministic_notes(tmp_path, bridge, monkeypatch):
    """Agent calls whose timeout was clipped to the gather deadline used to abort
    gathering as a provider outage (exit 2 with no evidence)."""
    monkeypatch.setenv("RESEARCH_LINEAR_TIME_BUDGET_S", "100")
    monkeypatch.setattr(lr, "PHASE_TIME_SHARE", dict(lr.PHASE_TIME_SHARE, gather=0.3))

    def timeout_agents(call, role):
        return APITimeoutError("Request timed out.") if role == "agent" else None

    rc, meta, plog, model, out = v3.run_engine(tmp_path, bridge, v3.World(fail=timeout_agents), depth="quick")
    assert rc == 0, meta.get("error")
    state = json.loads((out / "v3" / "state.json").read_text(encoding="utf-8"))
    assert {entry["fallback"] for entry in state["kiqs"].values()} == {"deadline"}
    assert (out / "research_report.md").is_file()


# =============================================================== F2

def test_sticky_fallback_blip_after_primary_quota_does_not_fail_the_run(tmp_path, bridge):
    def quota(call, role):
        return Exception("Error code: 429 - {'error': {'code': '2056', 'message': '已达到 Token Plan 用量上限'}}")

    blipped = {"done": False}

    def one_writer_blip(call, role):
        if role == "SECTION WRITING TASK" and not blipped["done"]:
            blipped["done"] = True
            return APIConnectionError("Connection error.")
        return None

    primary = v3.ScriptedModel(v3.World(fail=quota))
    fallback = v3.ScriptedModel(v3.World(fail=one_writer_blip))
    fallback.model_name = "fallback-model"
    out = tmp_path / "out"
    out.mkdir()
    plog = v3.FakePlog()
    meta = {"status": "running"}

    def gateway_factory(args, plog_arg, bridge_arg, preset):
        return rg.ModelGateway(primary, plog_arg, fallback_model=fallback, max_concurrency=preset.workers,
                               budget_units=preset.budget_units, reserve_share=lr.RESERVE_SHARE,
                               sleep=lambda seconds: None)

    def tools_factory(ledger, pages_dir, bridge_arg, plog_arg, limits):
        return rg.ResearchTools(ledger, pages_dir, search_fn=v3.fake_search, fetch_fn=v3.page_text,
                                bridge=bridge_arg, plog=plog_arg, limits=limits)

    rc = lr.run("Will global data-centre capacity exceed 250 GW by the end of 2027?", out, v3.make_args(),
                meta, plog, lambda: None, bridge=bridge, gateway_factory=gateway_factory,
                tools_factory=tools_factory)
    assert rc == 0, meta.get("error")
    assert blipped["done"] and len(primary.calls) == 1
    assert (out / "research_report.md").is_file()


# =============================================================== F3

def test_outage_template_plan_is_replanned_on_resume(tmp_path, bridge):
    out = tmp_path / "out"

    def all_down(call, role):
        return APIConnectionError("Connection error.")

    rc, meta, _, _, _ = v3.run_engine(tmp_path, bridge, v3.World(fail=all_down), out_dir=out)
    assert rc == 2 and meta["error"].startswith("provider_unavailable: gather failed")
    assert lr.PLAN_OUTAGE_KEY in meta["plan_fallback"]
    stale_plan = json.loads((out / "v3" / "plan.json").read_text(encoding="utf-8"))
    assert stale_plan["fallback"][lr.PLAN_OUTAGE_KEY] is True

    rc, meta, plog, model, _ = v3.run_engine(tmp_path, bridge, v3.World(), out_dir=out)
    assert rc == 0, meta.get("error")
    assert len(v3.calls_of(model, "SCOPE TASK")) == 1 and len(v3.calls_of(model, "PLANNING TASK")) == 1
    assert meta["plan_fallback"] == []
    plan = json.loads((out / "v3" / "plan.json").read_text(encoding="utf-8"))
    assert [k["question"] for k in plan["kiqs"]][0] == "What is installed capacity today?"
    assert "planning again" in plog.text()


def test_outage_plan_is_kept_once_evidence_was_gathered_for_it(tmp_path, bridge):
    out = tmp_path / "out"

    def planning_down(call, role):
        return APIConnectionError("Connection error.") if role in ("SCOPE TASK", "PLANNING TASK") else None

    rc, meta, _, _, _ = v3.run_engine(tmp_path, bridge, v3.World(fail=planning_down), out_dir=out)
    assert rc == 0 and lr.PLAN_OUTAGE_KEY in meta["plan_fallback"]
    state_path = out / "v3" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["phases"] = {k: v for k, v in state["phases"].items() if k in ("plan", "gather", "gap")}
    state_path.write_text(json.dumps(state), encoding="utf-8")

    rc, meta, _, model, _ = v3.run_engine(tmp_path, bridge, v3.World(), out_dir=out)
    assert rc == 0 and not v3.calls_of(model, "PLANNING TASK") and not v3.calls_of(model, "agent")
    assert lr.PLAN_OUTAGE_KEY in meta["plan_fallback"]


def test_unusable_plan_answer_is_not_treated_as_an_outage(tmp_path, bridge):
    rc, meta, _, _, _ = v3.run_engine(tmp_path, bridge, v3.JunkWorld(), depth="quick")
    assert rc == 0 and "plan" in meta["plan_fallback"]
    assert lr.PLAN_OUTAGE_KEY not in meta["plan_fallback"]


# =============================================================== F12 (agents)

class ScoutCitingWorld(v3.World):
    """Every KIQ's notes cite [S1], a scout result only the planner was shown."""

    def notes(self, tool_results) -> str:
        return super().notes(tool_results).replace(
            "## Conflicts", "- A scout-only figure of 777 GW [S1] (REPORTED)\n## Conflicts", 1)


def test_agents_cannot_cite_sources_they_were_never_shown(tmp_path, bridge):
    rc, meta, _, _, out = v3.run_engine(tmp_path, bridge, ScoutCitingWorld())
    assert rc == 0, meta.get("error")
    ledger = json.loads((out / "v3" / "sources_ledger.json").read_text(encoding="utf-8"))
    assert ledger[0]["sid"] == 1 and ledger[0]["first_seen_by"] == "planner"
    for kid in ("K1", "K2", "K3", "K4"):
        record = json.loads((out / "v3" / "kiq" / f"{kid}.json").read_text(encoding="utf-8"))
        # The guessed marker is dropped; a finding left without any source is
        # not a fact (round 2: it never reaches the digest).
        assert not [f for f in record["facts"] if "777 GW" in f["text"]]
        assert [u for u in record["unsourced"] if "777 GW" in u and "[S1]" not in u]
        assert all(1 not in fact["sids"] for fact in record["facts"])
    assert "777 GW" not in (out / "v3" / "digest.md").read_text(encoding="utf-8")


# =============================================================== F18

class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _agent_engine(model, clock, work: Path):
    ledger = rg.SourceLedger(work / "ledger.json")
    tools = rg.ResearchTools(ledger, work / "pages",
                             search_fn=lambda q, n: json.dumps({"results": [
                                 {"title": "Agency", "url": "https://agency.gov/r", "content": "176 GW in 2023"}]}),
                             fetch_fn=v3.page_text)
    gateway = rg.ModelGateway(model, None, sleep=lambda s: None, clock=clock)
    return types.SimpleNamespace(
        gateway=gateway, tools=tools, ledger=ledger, brief="RUN BRIEF\nquestion", language="English",
        preset=types.SimpleNamespace(agent_max_steps=7, workers=4),
        log=lambda kind, msg: None, units=lambda tokens: float(tokens))


def test_agent_stops_researching_while_the_final_notes_call_still_has_time(tmp_path):
    """F18: the agent only forced its notes after the deadline had expired, so
    the notes call itself failed and deterministic notes replaced them."""
    clock = _Clock()

    def responder(call):
        last_kind, last = call["messages"][-1]
        if last_kind == "human" and last.startswith("STOP"):
            return v3.ai("## Findings\n- Installed capacity reached 176 GW in 2023 [S1] (VERIFIED)\n"
                         "## Conflicts\n## Open questions\n## Discovered")
        clock.now += 250  # a slow research step: 400 s -> 150 s left, inside the 240 s grace
        return v3.ai(tool_calls=[{"name": "web_fetch", "args": {"url": "https://agency.gov/r", "focus": "capacity"},
                                  "id": f"c{len(call['messages'])}"}])

    model = v3.ScriptedModel(responder)
    engine = _agent_engine(model, clock, tmp_path)
    kiq = lr.Kiq(id="K1", question="What is installed capacity?", queries=[], kind="data")
    deadline = rg.Deadline(400, clock, label="gather")
    agent = lr.KiqAgent(engine, kiq, "KIQ INVESTIGATION TASK\nInvestigate K1: capacity", [], deadline,
                        grace=240)
    outcome = agent.run()
    assert outcome.fallback is None and outcome.forced == "deadline"
    assert len(model.calls) == 2 and "176 GW" in outcome.notes and outcome.fetched == [1]


def test_final_notes_grace_is_the_call_timeout_capped_by_the_slice():
    engine = types.SimpleNamespace(gateway=types.SimpleNamespace(
        profile=types.SimpleNamespace(timeout_by_call_kind={"agent": 240.0})))
    clock = _Clock()
    assert lr._Engine._final_notes_grace(engine, rg.Deadline(1400, clock)) == 240.0
    assert lr._Engine._final_notes_grace(engine, rg.Deadline(200, clock)) == pytest.approx(50.0)


# =============================================================== F21

def test_kiqs_cut_short_by_the_deadline_are_researched_again_on_resume(tmp_path, bridge, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("RESEARCH_LINEAR_TIME_BUDGET_S", "100")
    monkeypatch.setattr(lr, "PHASE_TIME_SHARE", dict(lr.PHASE_TIME_SHARE, gather=0.35))

    def k2_blip(call, role):
        if role == "agent" and _agent_kiq(call) == "K2":
            return APIConnectionError("Connection error.")  # with < 38 s left: deadline-limited
        return None

    rc, meta, _, _, _ = v3.run_engine(tmp_path, bridge, v3.World(fail=k2_blip), out_dir=out)
    assert rc == 0, meta.get("error")
    state_path = out / "v3" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["kiqs"]["K2"]["fallback"] == "deadline"
    assert {state["kiqs"][k]["fallback"] for k in ("K1", "K3", "K4")} == {None}

    # The attempt stops before synthesis (e.g. killed); the next one resumes.
    state["phases"] = {k: v for k, v in state["phases"].items() if k in ("plan", "gather", "gap")}
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.delenv("RESEARCH_LINEAR_TIME_BUDGET_S")
    monkeypatch.setattr(lr, "PHASE_TIME_SHARE", dict(lr.PHASE_TIME_SHARE, gather=0.55))
    rc, meta, plog, model, _ = v3.run_engine(tmp_path, bridge, v3.World(), out_dir=out)
    assert rc == 0, meta.get("error")
    assert {_agent_kiq(c) for c in v3.calls_of(model, "agent")} == {"K2"}
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["kiqs"]["K2"]["fallback"] is None and state["kiqs"]["K2"]["facts"] >= 2
    assert "researching K2 again" in plog.text()

    # Once a report was synthesized from the stub, a later resume keeps it.
    rc, _, _, model, _ = v3.run_engine(tmp_path, bridge, v3.World(), out_dir=out)
    assert rc == 0 and not v3.calls_of(model, "agent")


# =============================================================== F22

def test_default_gateway_factory_builds_models_from_the_config_file(tmp_path, monkeypatch):
    """F22: ``--config`` was ignored; the v3 factory must load that file and
    build the primary and fallback models from it."""
    loaded: list[str] = []
    installed: list[object] = []
    created: list[tuple] = []

    class AppConfig:
        @classmethod
        def from_file(cls, path):
            loaded.append(path)
            config = cls()
            config.path = path
            return config

    def set_app_config(config):
        installed.append(config)

    class FakeModel:
        model_name = "fake-model"

    def create_chat_model(name=None, thinking_enabled=False, *, app_config=None, **kwargs):
        created.append((name, thinking_enabled, app_config))
        return FakeModel()

    package = types.ModuleType("deerflow")
    models = types.ModuleType("deerflow.models")
    models.create_chat_model = create_chat_model
    config_pkg = types.ModuleType("deerflow.config")
    app_config = types.ModuleType("deerflow.config.app_config")
    app_config.AppConfig = AppConfig
    app_config.set_app_config = set_app_config
    for name, module in {"deerflow": package, "deerflow.models": models, "deerflow.config": config_pkg,
                         "deerflow.config.app_config": app_config}.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv("DEERFLOW_FALLBACK_MODEL", "backup-model")
    preset = lr.resolve_preset("quick", {})
    config_file = str(tmp_path / "custom-config.yaml")

    gateway = lr._default_gateway_factory(v3.make_args(config=config_file), None, None, preset)
    assert isinstance(gateway, rg.ModelGateway)
    assert loaded == [config_file] and len(installed) == 1
    assert created == [("fake-model", False, installed[0]), ("backup-model", False, installed[0])]

    loaded.clear()
    created.clear()
    lr._default_gateway_factory(v3.make_args(config=None), None, None, preset)
    assert loaded == [] and created == [("fake-model", False, None), ("backup-model", False, None)]
