"""Real report consumers with scripted external responses; guarded runner only."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.test_forecast_feedback_sdk import published

from app.config import Config
from app.services.report_agent import ReportAgent, ReportManager, ReportOutline, ReportSection, ReportStatus
from app.services import news_market_context


BODY = "The forecast remains conditional on executed capacity and delivery constraints. " * 35
SCENARIO = "EXPORT_RESTRICTION_FIXTURE"
BRIEF = "Admitted research generation: CAPACITY_BRIEF_FIXTURE."
DRIVER = "STRUCTURED_DRIVER_FIXTURE"


class ScriptedModel:
    def __init__(self):
        self.calls = []
        self.native_calls = 0
        self.exhaust_native = False

    def chat(self, messages, **kwargs):
        self.calls.append(copy.deepcopy(messages))
        return BODY

    def chat_json(self, messages, **kwargs):
        self.calls.append(copy.deepcopy(messages))
        return {"title": "Capacity outlook", "summary": "A bounded outlook.",
                "horizon": "2029-12-31", "confidence": "medium",
                "scenarios": [{"name": "Constrained", "probability": 1.0,
                               "resolution_criteria": "Capacity remains below target."}],
                "sections": [{"title": f"Outlook {i}", "description": "Drivers"} for i in range(4)]}

    def chat_with_tools(self, messages, schemas, **kwargs):
        self.calls.append(copy.deepcopy(messages))
        self.native_calls += 1
        if self.exhaust_native:
            if self.native_calls == 1:
                return {"tool_calls": [{"id": "call_fixture", "name": "quick_search",
                                        "arguments": {"query": "capacity"}}]}
            return {"content": ""}
        return {"content": BODY}


class Graph:
    def __init__(self):
        self.diff_calls = []

    def get_simulation_context(self, **kw):
        return {"graph_statistics": {}, "related_facts": ["GRAPH_FACT_FIXTURE"]}

    def insight_forge(self, **kw):
        return ""

    def simulation_outcomes(self, *args, **kw):
        return ""

    def quick_search(self, **kw):
        return SimpleNamespace(to_text=lambda: "RETRIEVED_TOOL_EVIDENCE_FIXTURE")

    def scenario_diff(self, baseline, scenario):
        self.diff_calls.append((baseline, scenario))
        return "BASELINE_COMPARISON_FIXTURE: capacity differs under the admitted condition."


@pytest.fixture
def make_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(Config, "RESEARCH_FORECAST_INPUTS", True, raising=False)
    monkeypatch.setattr(Config, "REPORT_EVIDENCE_BLOCKS", True, raising=False)
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", False)
    monkeypatch.setattr(Config, "REPORT_FORECAST_SELF_CRITIQUE", False)
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 1, raising=False)
    monkeypatch.setenv("REPORT_OUTPUT_LANGUAGE", "English")

    def make(**overrides):
        args = dict(graph_id="graph_fixture", simulation_id="sim_fixture",
                    simulation_requirement="QUESTION_FIXTURE: assess capacity by 2029-12-31",
                    situation_brief=BRIEF, scenario_label=SCENARIO,
                    actors={"as_of_date": "2026-10-20", "forecast_inputs": {
                        "drivers": [{"variable": DRIVER, "why_it_matters": "A binding capacity constraint"}]}},
                    sources=[{"title": "Stored capacity evidence", "url": "https://example.org/capacity",
                              "content": "CAPACITY_SOURCE_FIXTURE: capacity is 47 units in 2026."}],
                    llm_client=ScriptedModel(), zep_tools=Graph())
        args.update(overrides)
        return ReportAgent(**args)
    return make


def prompt(agent):
    return "\n".join(str(message.get("content") or "") for message in agent.llm.calls[-1])


@pytest.mark.parametrize("brief", [BRIEF, ""])
@pytest.mark.parametrize("consumer", ["outline", "native", "react"])
def test_actual_writers_keep_scenario_and_structured_context(make_agent, brief, consumer):
    agent = make_agent(situation_brief=brief)
    sec = ReportSection(title="Capacity", description="Drivers", padded=True)
    outline = ReportOutline(title="Capacity", summary="Outlook", sections=[sec])
    if consumer == "outline":
        agent.plan_outline()
    else:
        getattr(agent, f"_generate_section_{consumer}")(sec, outline, [])
    assert SCENARIO in prompt(agent)
    assert DRIVER in prompt(agent)
    if brief:
        assert BRIEF in prompt(agent)


@pytest.mark.parametrize("consumer", ["critique", "revise", "continue", "synthesis"])
def test_repair_and_synthesis_keep_admitted_scope(make_agent, consumer):
    agent = make_agent()
    sec = ReportSection(title="Risk and uncertainty", description="Capacity")
    outline = ReportOutline(title="Capacity", summary="Outlook", sections=[sec])
    agent._forecast_spine_block = "SPINE_FIXTURE: Constrained: 100%; resolves 2029-12-31."
    agent._contested_table_block = "CONTESTED_FIXTURE: delivery estimates disagree."
    if consumer == "critique":
        agent._critique_section_draft(sec, BODY, [])
    elif consumer == "revise":
        agent._revise_section_draft(sec, outline, BODY, "Clarify the binding condition.")
    elif consumer == "continue":
        agent._continue_section_draft(sec, BODY)
    else:
        agent._build_part2_synthesis("## Drivers\n" + BODY)
    assert SCENARIO in prompt(agent)
    assert "QUESTION_FIXTURE" in prompt(agent)
    assert BRIEF in prompt(agent)
    if consumer != "synthesis":
        assert "CONTESTED_FIXTURE" in prompt(agent)


def test_native_forced_final_keeps_actual_tool_observation(make_agent):
    agent = make_agent()
    agent.llm.exhaust_native = True
    section = ReportSection(title="Capacity", padded=True)
    outline = ReportOutline(title="Capacity", summary="Outlook", sections=[section])
    agent._generate_section_native(section, outline, [])
    assert agent.llm.native_calls == 14
    assert "RETRIEVED_TOOL_EVIDENCE_FIXTURE" in prompt(agent)
    assert any(m["role"] == "tool" for m in agent.llm.calls[-1])


def test_scenario_reaches_real_spine_model_prompt(make_agent):
    agent = make_agent()
    ReportManager._ensure_report_folder("report_fixture")
    agent._derive_and_pin_forecast_spine("report_fixture")
    assert agent.llm.calls, "the real extractor must reach the scripted model"
    assert SCENARIO in prompt(agent)
    assert "2029" in prompt(agent)
    assert DRIVER in prompt(agent)


def sealed_context(count=1):
    envelope = {"schema_version": 1, "generation_id": "capture_fixture",
                "question_sha256": hashlib.sha256(b"question").hexdigest(),
                "language": "English", "as_of": "2026-10-20", "created_at": "2026-10-20T00:00:00Z",
                "sealed": True, "providers": {}, "queries": [], "items": []}
    for i in range(count):
        envelope["items"].append({"id": f"newsapi:{i}", "provider": "newsapi", "kind": "news_snippet",
                                  "title": f"Capacity source {i}", "url": "https://example.org/news",
                                  "snippet": "NEWS_SNIPPET_FIXTURE: deliveries were delayed.",
                                  "published_at": "2026-10-19", "retrieved_at": "2026-10-20",
                                  "eligibility": {"context_only": True, "anchor": False, "resolution": False}})
    envelope["sha256"] = hashlib.sha256(json.dumps(envelope, ensure_ascii=False, sort_keys=True,
                                                  separators=(",", ":")).encode()).hexdigest()
    return envelope


def test_news_snippet_reaches_actual_writer_and_omissions_are_disclosed(make_agent):
    agent = make_agent(news_market_context=sealed_context(13))
    agent.plan_outline()
    assert "NEWS_SNIPPET_FIXTURE" in prompt(agent)
    assert "1 additional" in prompt(agent)
    assert "not probability anchors" in prompt(agent)
    assert agent.news_market_context == sealed_context(13)


def test_news_rejects_foreign_digest_without_constructing_model(make_agent):
    context = sealed_context()
    context["items"][0]["snippet"] = "changed"
    with pytest.raises(ValueError, match="digest"):
        make_agent(news_market_context=context)


def test_seed_scenario_identity_reaches_actual_spine_prompt_without_parent_probability(make_agent):
    agent = make_agent(scenario_spine=[{"name": "PARENT_SCENARIO_FIXTURE",
                                     "resolution_criteria": "PARENT_RULE_FIXTURE by 2029-12-31",
                                     "probability": 0.123456789}])
    ReportManager._ensure_report_folder("report_seed")
    agent._derive_and_pin_forecast_spine("report_seed")
    assert "PARENT_SCENARIO_FIXTURE" in prompt(agent)
    assert "PARENT_RULE_FIXTURE" in prompt(agent)
    assert "0.123456789" not in prompt(agent)


def test_chat_keeps_news_and_conditional_scope_without_report(make_agent):
    agent = make_agent(news_market_context=sealed_context())
    agent.chat("Explain the captured delivery delay.")
    assert SCENARIO in prompt(agent)
    assert "NEWS_SNIPPET_FIXTURE" in prompt(agent)
    assert "not probability anchors" in prompt(agent)


def test_localized_exec_brief_uses_sealed_variant_and_rebuilds_on_variant_update(tmp_path, monkeypatch):
    from app.services.exec_brief import ExecBriefBuilder
    from tests.test_exec_brief import _make_report_dir, _forecast_fixture
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    rid, folder = _make_report_dir(str(tmp_path / "reports"), forecast=_forecast_fixture(),
                                   translations=[{"lang": "zh"}])
    folder = Path(folder)
    (folder / "full_report.zh.md").write_text("# 预测报告\n\n## 核心论点\n\n这是依据执行约束作出的条件预测。\n")
    raw = (folder / "forecast.json").read_bytes()
    audit = json.loads((folder / "final_audit.json").read_text())
    audit.update(forecast_sha256=hashlib.sha256(raw).hexdigest(),
                 structured_forecast={"required": False, "present": True, "valid": True})
    (folder / "final_audit.json").write_text(json.dumps(audit))
    localized = json.loads(raw)
    localized["binary_forecasts"][0]["statement"] = "本地化预测甲"
    localized["localization"] = {"lang": "zh", "source_forecast_sha256": audit["forecast_sha256"], "complete": True}
    variant = folder / "forecast.zh.json"
    variant.write_text(json.dumps(localized, ensure_ascii=False))
    result = ExecBriefBuilder.build(rid, str(folder), force=True)
    out = Path(result["exec_brief.zh"])
    assert "本地化预测甲" in out.read_text()
    localized["binary_forecasts"][0]["statement"] = "本地化预测乙"
    variant.write_text(json.dumps(localized, ensure_ascii=False))
    import os
    old = out.stat().st_mtime
    os.utime(variant, (old + 10, old + 10))
    ExecBriefBuilder.build(rid, str(folder))
    assert "本地化预测乙" in out.read_text()
    localized["localization"]["source_forecast_sha256"] = "0" * 64
    variant.write_text(json.dumps(localized, ensure_ascii=False))
    ExecBriefBuilder.build(rid, str(folder), force=True)
    assert "本地化预测乙" not in out.read_text()


def test_admitted_draw_count_survives_ambient_change(make_agent, monkeypatch):
    from app.services.pipeline_orchestrator import capture_safety_policy_v1
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 1)
    policy = capture_safety_policy_v1("admission")
    agent = make_agent(report_policy=policy)
    monkeypatch.setattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 3)
    ReportManager._ensure_report_folder("report_policy")
    agent._derive_and_pin_forecast_spine("report_policy")
    assert len(agent.llm.calls) == policy["report_spine_selfconsistency_k"]


def test_admitted_ensemble_factor_survives_ambient_change(monkeypatch):
    from app.services.ensemble import aggregate_forecasts
    from app.services.pipeline_orchestrator import capture_safety_policy_v1
    runs = [{"scenarios": [{"name": "A", "probability": 0.8}, {"name": "B", "probability": 0.2}]}] * 2
    monkeypatch.setattr(Config, "ENSEMBLE_EXTREMIZE_A", 1.0)
    policy = capture_safety_policy_v1("admission")
    admitted = aggregate_forecasts(runs, report_policy=policy)
    monkeypatch.setattr(Config, "ENSEMBLE_EXTREMIZE_A", 2.0)
    resumed = aggregate_forecasts(runs, report_policy=policy)
    assert resumed["extremize_a"] == policy["ensemble_extremize_a"]
    assert resumed["scenarios"] == admitted["scenarios"]


def test_admitted_simulation_effect_survives_ambient_change(make_agent, monkeypatch):
    from app.services.pipeline_orchestrator import capture_safety_policy_v1
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "diagnostic_only")
    policy = capture_safety_policy_v1("admission")
    agent = make_agent(report_policy=policy)
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "legacy_prompt")
    assert agent._simulation_forecast_effect() == policy["simulation_forecast_effect"]


def policy_fixture(**changes):
    return {"report_spine_selfconsistency_k": 1, "ensemble_extremize_a": 1.0,
            "simulation_forecast_effect": "diagnostic_only", **changes}


@pytest.mark.parametrize("admitted_effect", ["legacy_prompt", "diagnostic_only"])
def test_merged_simulation_anchor_obeys_saved_policy_at_actual_report_caller(
        make_agent, monkeypatch, tmp_path, admitted_effect):
    """The new legacy anchor cannot turn diagnostic projections into forecast evidence."""
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT",
                        "diagnostic_only" if admitted_effect == "legacy_prompt" else "legacy_prompt")
    monkeypatch.setattr(Config, "REPORT_SPINE_ANCHOR_WORLDSTATE", True)
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path / "simulations"))
    agent = make_agent(report_policy=policy_fixture(simulation_forecast_effect=admitted_effect))
    folder = tmp_path / "simulations" / agent.simulation_id
    folder.mkdir(parents=True)
    shares = {"SIM_ANCHOR_MARKER": 1.0}
    (folder / "world_state_trajectory.json").write_text(json.dumps({
        "validity": "valid", "outcome": {"shares": shares}}))
    (folder / "simulation_config.json").write_text(json.dumps({"temporal_config": {
        "as_of_date": "2026-10-22", "horizon_date": "2029-12-31"}}))
    report_id = "report_merged_anchor_" + admitted_effect
    ReportManager._ensure_report_folder(report_id)
    agent._derive_and_pin_forecast_spine(report_id)
    assert agent._forecast_spine and agent.llm.calls
    stored = json.loads((Path(ReportManager._get_report_folder(report_id)) / "forecast.json").read_text())
    consumed = "SIM_ANCHOR_MARKER" in json.dumps(agent.llm.calls)
    if admitted_effect == "legacy_prompt":
        assert consumed
        assert stored["base_distribution"] == shares
        assert stored["simulation_anchor"]["mode"] == "band"
    else:
        assert not consumed
        assert "base_distribution" not in stored and "simulation_anchor" not in stored


def test_policy_is_detached_and_missing_or_invalid_controls_fail_closed(make_agent, monkeypatch):
    policy = policy_fixture()
    agent = make_agent(report_policy=policy)
    policy["simulation_forecast_effect"] = "legacy_prompt"
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "legacy_prompt")
    assert agent._simulation_forecast_effect() == "diagnostic_only"
    assert agent._backtest_extraction_kwargs()["simulation_effect"] == "diagnostic_only"
    with pytest.raises(TypeError):
        agent._report_policy["simulation_forecast_effect"] = "legacy_prompt"
    for bad in ({}, policy_fixture(report_spine_selfconsistency_k=True),
                policy_fixture(ensemble_extremize_a=float("nan")),
                policy_fixture(simulation_forecast_effect="unknown")):
        with pytest.raises(ValueError):
            make_agent(report_policy=bad)


def test_binary_extractor_uses_pinned_effect_but_explicit_arm_retains_precedence(monkeypatch):
    from app.services.forecast_extractor import extract_binary_forecasts
    from tests.conftest import FakeLLMClient
    from tests.test_forecast_extractor import _binary
    monkeypatch.setattr(Config, "FORECAST_SIM_SENSITIVITY", True)
    monkeypatch.setattr(Config, "FORECAST_BINARY_CONTRARIAN", False)
    monkeypatch.setattr(Config, "FORECAST_ENSEMBLE_MODELS", "")
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "legacy_prompt")
    for override, expected in ((None, False), ("legacy_prompt", True)):
        model = FakeLLMClient(json_responses=[{"binary_forecasts": [_binary("F1", "Capacity exceeds target", .4)]}])
        extract_binary_forecasts("Evidence", model, min_count=1, signal_pack="DIAGNOSTIC_SIGNAL_FIXTURE",
                                 simulation_effect=override, report_policy=policy_fixture())
        assert ("DIAGNOSTIC_SIGNAL_FIXTURE" in json.dumps(model.calls)) is expected


def test_binary_ensemble_uses_pinned_extremization(monkeypatch):
    from app.services.forecast_extractor import extract_binary_forecasts
    from tests.conftest import FakeLLMClient
    from tests.test_forecast_extractor import _binary, _ensemble_config
    _ensemble_config(monkeypatch, extremize=2.0)
    primary = FakeLLMClient(provider="primary", json_responses=[
        {"binary_forecasts": [_binary("F1", "Capacity exceeds target", .2)]}])
    secondary = FakeLLMClient(provider="modelb", json_responses=[
        {"binary_forecasts": [_binary("F1", "Capacity exceeds target", .6)]}])
    out = extract_binary_forecasts("Evidence", primary, min_count=1, report_policy=policy_fixture(),
                                   ensemble_client_factory=lambda name: secondary)
    from app.services.ensemble import _extremized_logodds
    row = out["binary_forecasts"][0]
    assert row["ensemble"]["pooled"] == round(_extremized_logodds([.2, .6], 1.0), 4)
    assert row["ensemble"]["pooled"] != round(_extremized_logodds([.2, .6], 2.0), 4)


def test_timeline_chart_keeps_constructor_generation_over_new_pipeline_handoff(make_agent, tmp_path, monkeypatch):
    from app.services.pipeline_orchestrator import PipelineManager, PipelineState
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))
    handoff = tmp_path / "new-handoff"
    handoff.mkdir()
    (handoff / "timeline.json").write_text(json.dumps([{"date": "2031-01-01", "event": "FOREIGN_TIMELINE"}]))
    PipelineManager.save(PipelineState(pipeline_id="pipe_foreign", prompt="Capacity", simulation_id="sim_fixture",
                                        handoff_dir=str(handoff)))
    pinned = [{"date": "2028-10-20", "event": "CONSUMED_TIMELINE"}]
    agent = make_agent(timeline_events=pinned)
    ReportManager._ensure_report_folder("report_timeline")
    artifacts = agent._collect_viz_artifacts("report_timeline", ReportManager._get_report_folder("report_timeline"))
    assert artifacts["timeline"] == pinned


def test_handoff_discovery_uses_consumed_binding_and_invalid_proof_cannot_fallback(make_agent, tmp_path, monkeypatch):
    from app.services import official_data
    from app.services.simulation_manager import SimulationManager
    from app.services.pipeline_orchestrator import PipelineManager, PipelineState
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))
    simulations = tmp_path / "simulations"
    (simulations / "sim_fixture").mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(simulations))
    bound, foreign = tmp_path / "bound", tmp_path / "foreign"
    for folder, label in ((bound, "BOUND"), (foreign, "FOREIGN")):
        folder.mkdir()
        (folder / "research_report.md").write_text(label)
        (folder / "actors.json").write_text('{}')
        (folder / "sources.json").write_text('[]')
        (folder / "timeline.json").write_text(json.dumps([{"date": "2028-01-01", "event": label}]))
    official_data.bind_simulation_research("sim_fixture", bound, pipeline_id="pipe_original")
    PipelineManager.save(PipelineState(pipeline_id="pipe_foreign", prompt="Capacity", simulation_id="sim_fixture",
                                        handoff_dir=str(foreign)))
    agent = make_agent()
    assert agent._locate_handoff_dir() == str(bound)
    assert agent._locate_timeline()[0]["event"] == "BOUND"
    (bound / "research_report.md").write_text("changed generation")
    assert agent._locate_handoff_dir() is None
    assert agent._locate_timeline() is None


@pytest.mark.parametrize("sidecar", ["quantitative.json", "contested.json", "timeline.json"])
@pytest.mark.parametrize("change", ["edit", "remove", "late_addition"])
def test_research_sidecars_are_generation_bound(tmp_path, monkeypatch, sidecar, change):
    from app.services import official_data
    from app.services.simulation_manager import SimulationManager
    simulations = tmp_path / "simulations"
    (simulations / "sim_sidecars").mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(simulations))
    handoff = tmp_path / "research"
    handoff.mkdir()
    for name, body in (("research_report.md", "Research"), ("actors.json", "{}"), ("sources.json", "[]")):
        (handoff / name).write_text(body)
    path = handoff / sidecar
    if change != "late_addition":
        path.write_text('[{"fixture":"consumed"}]')
    generation = official_data.capture_research_generation(handoff)
    official_data.bind_simulation_research("sim_sidecars", handoff, pipeline_id="pipe_sidecars",
                                           expected_generation=generation)
    proof = official_data.simulation_research_binding("sim_sidecars")
    assert proof["status"] == "valid"
    if change != "late_addition":
        assert proof["files"].get(sidecar) == hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        assert sidecar not in proof["files"]
    if change == "remove":
        path.unlink()
    else:
        path.write_text('[{"fixture":"later"}]')
    assert official_data.simulation_research_binding("sim_sidecars")["status"] == "invalid"
    with pytest.raises(ValueError, match="generation changed"):
        official_data.bind_simulation_research("sim_sidecars", handoff, pipeline_id="pipe_sidecars",
                                               expected_generation=generation)


def test_old_absent_sidecars_and_later_graph_priors_remain_compatible(tmp_path, monkeypatch):
    from app.services import official_data
    from app.services.simulation_manager import SimulationManager
    simulations = tmp_path / "simulations"
    (simulations / "sim_old").mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(simulations))
    handoff = tmp_path / "research"
    handoff.mkdir()
    (handoff / "research_report.md").write_text("Legacy/off research")
    generation = official_data.capture_research_generation(handoff)
    assert set(generation["files"]) == set(official_data._GENERATION_FILES)
    official_data.bind_simulation_research("sim_old", handoff, pipeline_id="pipe_old")
    before = official_data.simulation_research_binding("sim_old")
    for name in ("graph_priors.json", "graph_priors_structural.json"):
        (handoff / name).write_text('{"later_graph_output":true}')
    after = official_data.simulation_research_binding("sim_old")
    assert after == before and after["status"] == "valid"


@pytest.mark.parametrize("changed", ["data/datasets.json", "research_report.md", "actors.json", "sources.json", "actor_dossier.md"])
def test_verified_core_retains_only_unchanged_consumed_prose(tmp_path, monkeypatch, changed):
    from app.services import official_data
    from app.services.simulation_manager import SimulationManager
    root = tmp_path / "simulations"
    (root / "sim_core").mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(root))
    handoff = tmp_path / "research"
    (handoff / "data").mkdir(parents=True)
    bodies = {"research_report.md": "G1 report", "actors.json": '{"actors":[],"generation":"G1"}',
              "sources.json": '[{"title":"G1"}]', "actor_dossier.md": "G1 dossier", "data/datasets.json": "[]"}
    for name, body in bodies.items():
        (handoff / name).write_text(body)
    official_data.bind_simulation_research("sim_core", handoff, pipeline_id="pipe_core")
    initial = official_data.read_bound_research_core("sim_core")
    assert initial["status"] == "valid" and initial["research_report"] == "G1 report"
    (handoff / changed).write_text(bodies[changed].replace("G1", "G2") if changed != "data/datasets.json" else '[{"later":true}]')
    assert official_data.simulation_research_binding("sim_core")["status"] == "invalid"
    core = official_data.read_bound_research_core("sim_core")
    if changed == "data/datasets.json":
        assert core == initial  # Core proof is deliberately narrower than optional data proof.
    else:
        assert core == {"status": "invalid"}
    assert official_data.read_bound_research_core("sim_unbound") == {"status": "missing"}


def test_verified_core_rejects_changed_binding_during_read(tmp_path, monkeypatch):
    from app.services import official_data
    from app.services.simulation_manager import SimulationManager
    root = tmp_path / "simulations"
    (root / "sim_core").mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(root))
    handoff = tmp_path / "research"
    handoff.mkdir()
    (handoff / "research_report.md").write_text("G1 report")
    official_data.bind_simulation_research("sim_core", handoff, pipeline_id="pipe_core")
    original = official_data._contained_bytes
    count = 0
    def racing_read(directory, relative, **kw):
        nonlocal count
        data = original(directory, relative, **kw)
        if relative == "research_report.md":
            count += 1
            if count == 1:
                binding_path = root / "sim_core" / official_data._BINDING_FILE
                binding = json.loads(binding_path.read_text())
                binding["pipeline_id"] = "pipe_changed"
                binding_path.write_text(json.dumps(binding))
        return data
    monkeypatch.setattr(official_data, "_contained_bytes", racing_read)
    assert official_data.read_bound_research_core("sim_core") == {"status": "invalid"}


def test_primary_brief_rebuilds_after_localization_deletion(tmp_path, monkeypatch):
    from app.services.exec_brief import ExecBriefBuilder
    from tests.test_exec_brief import _make_report_dir, _forecast_fixture
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    rid, folder = _make_report_dir(str(tmp_path / "reports"), forecast=_forecast_fixture())
    folder = Path(folder)
    raw = (folder / "forecast.json").read_bytes()
    audit = json.loads((folder / "final_audit.json").read_text())
    audit.update(forecast_sha256=hashlib.sha256(raw).hexdigest(),
                 structured_forecast={"required": False, "present": True, "valid": True})
    (folder / "final_audit.json").write_text(json.dumps(audit))
    localized = json.loads(raw)
    marker = "REMOVED_PRIMARY_LOCALIZATION_FIXTURE"
    localized["binary_forecasts"][0]["statement"] = marker
    localized["localization"] = {"lang": "en", "source_forecast_sha256": audit["forecast_sha256"], "complete": True}
    variant = folder / "forecast.en.json"
    variant.write_text(json.dumps(localized))
    out = ExecBriefBuilder.build(rid, str(folder), force=True)
    brief, digest = Path(out["exec_brief"]), Path(out["digest"])
    assert marker in brief.read_text()
    variant.unlink()
    assert ReportManager.load_localized_forecast(rid, "en")[1]["localized"] is False
    ExecBriefBuilder.build(rid, str(folder))
    assert marker not in brief.read_text()
    assert marker not in digest.read_text()


@pytest.mark.parametrize("changed", [False, True])
def test_manual_dossier_cannot_feed_changed_bound_actor_context_to_outline(make_agent, tmp_path, monkeypatch, changed):
    from app.services import official_data, pipeline_orchestrator as po
    from app.services.simulation_manager import SimulationManager
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))
    simulations = tmp_path / "simulations"
    (simulations / "sim_manual").mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(simulations))
    handoff = tmp_path / "handoff"
    handoff.mkdir()
    actors = {"central_question": "Capacity by 2029?", "as_of_date": "2026-10-20", "actors": [],
              "hot_topics": ["G1_CONSUMED capacity 40 MW"]}
    (handoff / "actors.json").write_text(json.dumps(actors))
    (handoff / "research_report.md").write_text("G1_CONSUMED research")
    (handoff / "sources.json").write_text('[]')
    po.PipelineManager.save(po.PipelineState(pipeline_id="pipe_manual", prompt="Capacity by 2029?",
                                             simulation_id="sim_manual", handoff_dir=str(handoff)))
    official_data.bind_simulation_research("sim_manual", handoff, pipeline_id="pipe_manual")
    if changed:
        actors["hot_topics"] = ["G2_REPLACEMENT capacity 99 MW"]
        (handoff / "actors.json").write_text(json.dumps(actors))
    try:
        dossier = po.load_research_dossier_for_simulation("sim_manual")
    except ValueError:
        assert changed  # A fail-closed loader is also an acceptable boundary.
        return
    agent = make_agent(simulation_id="sim_manual", scenario_label=None, situation_brief=dossier["situation_brief"],
                       actors=dossier["actors"], research_report=dossier["research_report"], sources=dossier["sources"],
                       official_data=dossier["official_data"], news_market_context=dossier["news_market_context"])
    agent.plan_outline()
    assert "G2_REPLACEMENT" not in prompt(agent)
    if not changed:
        assert "G1_CONSUMED" in prompt(agent)


@pytest.mark.parametrize("consumer", ["outline", "native", "react"])
def test_baseline_identity_reaches_comparison_and_actual_writer_prompt(make_agent, consumer):
    agent = make_agent(base_simulation_id="sim_baseline_fixture")
    section = ReportSection(title="Scenario comparison", padded=True)
    outline = ReportOutline(title="Capacity", summary="Outlook", sections=[section])
    if consumer == "outline":
        agent.plan_outline()
        assert agent.zep_tools.diff_calls == [("sim_baseline_fixture", "sim_fixture")]
    else:
        getattr(agent, f"_generate_section_{consumer}")(section, outline, [])
    assert "sim_baseline_fixture" in prompt(agent)
    assert SCENARIO in prompt(agent)


@pytest.mark.parametrize("foreign_exists", [False, True])
def test_legacy_market_snapshot_prompt_uses_consumed_owner_not_later_pipeline(make_agent, tmp_path, monkeypatch, foreign_exists):
    from app.services import official_data, pipeline_orchestrator as po
    from app.services.simulation_manager import SimulationManager
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"))
    monkeypatch.setattr(Config, "PREDICTION_MARKETS_REQUOTE", False)
    simulations = tmp_path / "simulations"
    (simulations / "sim_fixture").mkdir(parents=True)
    monkeypatch.setattr(SimulationManager, "SIMULATION_DATA_DIR", str(simulations))
    for label, date in (("G1_MARKET", "2026-10-19"), ("G2_FOREIGN_MARKET", "2026-10-20")):
        if label.startswith("G2") and not foreign_exists:
            continue
        handoff = tmp_path / label
        handoff.mkdir()
        (handoff / "research_report.md").write_text("Consumed research" if label.startswith("G1") else "Other research")
        (handoff / "prediction_markets.json").write_text(json.dumps({"markets": [{
            "market_id": label, "question": label + " capacity by 2029?", "implied_yes_prob": .4,
            "volume": 100000, "liquidity": 10000}]}))
        pid = "pipe_" + label
        po.PipelineManager.save(po.PipelineState(pipeline_id=pid, prompt="Capacity", simulation_id="sim_fixture",
                                                 handoff_dir=str(handoff), created_at=date, options={}))
        if label.startswith("G1"):
            official_data.bind_simulation_research("sim_fixture", handoff, pipeline_id=pid)
    agent = make_agent()
    markets = agent._load_prediction_markets()
    agent._market_pack = agent._render_market_pack(markets)
    agent.plan_outline()
    assert "G1_MARKET" in prompt(agent)
    assert "G2_FOREIGN_MARKET" not in prompt(agent)
    # Optional data drift must not turn a report's failed proof into a new
    # capture or a replacement snapshot from the later sibling pipeline.
    owner = tmp_path / "G1_MARKET"
    (owner / "data").mkdir()
    (owner / "data/datasets.json").write_text('[]')
    assert official_data.simulation_research_binding("sim_fixture")["status"] == "invalid"
    assert make_agent()._load_prediction_markets() == []


@pytest.mark.parametrize("marker", ["malformed", "broken_symlink", "directory"])
def test_retirement_marker_excludes_index_scan_and_cached_lookup_only(published, marker):
    report, folder = published["report"], published["folder"]
    from tests.test_forecast_feedback_sdk import NoExternalCalls
    agent = ReportAgent(report.graph_id, report.simulation_id, report.simulation_requirement,
                        llm_client=NoExternalCalls(), zep_tools=NoExternalCalls())
    assert agent._resolve_report_cached().report_id == report.report_id
    audit = (folder / "final_audit.json").read_bytes()
    path = folder / "current_simulation_retirement.json"
    if marker == "malformed":
        path.write_text("not valid JSON")
    elif marker == "directory":
        path.mkdir()
    else:
        path.symlink_to(folder / "absent-retirement-record")
    assert ReportManager.get_report_by_simulation(report.simulation_id) is None
    assert agent._resolve_report_cached() is None
    Path(ReportManager._get_sim_index_path()).unlink()
    assert ReportManager.get_report_by_simulation(report.simulation_id) is None
    assert ReportManager.get_report(report.report_id).report_id == report.report_id
    assert ReportManager.publication_status(report.report_id)["publishable"]
    assert (folder / "final_audit.json").read_bytes() == audit


def test_retire_reports_preserves_history_ledger_scoring_and_sibling_ownership(published):
    from dataclasses import replace
    from app.services import forecast_ledger
    from tests.test_forecast_feedback_sdk import NoExternalCalls
    report, folder = published["report"], published["folder"]
    agent = ReportAgent(report.graph_id, report.simulation_id, report.simulation_requirement,
                        llm_client=NoExternalCalls(), zep_tools=NoExternalCalls())
    assert agent._resolve_report_cached().report_id == report.report_id
    journal = published["ledger"] / "published_forecasts.jsonl"
    preserved = {name: (folder / name).read_bytes() for name in
                 ("meta.json", "forecast.json", "full_report.md", "final_audit.json")}
    ledger_before = journal.read_bytes()
    sibling = replace(report, report_id="report_sibling_retirement", simulation_id="sim_sibling_retirement",
                      status=ReportStatus.PENDING)
    ReportManager.save_report(sibling)
    # Remove the index so retirement must discover every persisted matching owner.
    Path(ReportManager._get_sim_index_path()).unlink()
    assert ReportManager.retire_reports_for_simulation(report.simulation_id) == [report.report_id]
    marker = folder / "current_simulation_retirement.json"
    first = marker.read_bytes()
    assert json.loads(first)["simulation_id"] == report.simulation_id
    assert ReportManager.retire_reports_for_simulation(report.simulation_id) == [report.report_id]
    assert marker.read_bytes() == first
    assert not ReportManager.is_report_retired(sibling.report_id)
    assert ReportManager.get_report_by_simulation(sibling.simulation_id).report_id == sibling.report_id
    assert ReportManager.get_report_by_simulation(report.simulation_id) is None
    # A cached agent can select a newly generated current report after retirement.
    current = replace(sibling, report_id="report_after_retirement", simulation_id=report.simulation_id,
                      created_at="2026-10-21T00:00:00Z")
    ReportManager.save_report(current)
    assert agent._resolve_report_cached().report_id == current.report_id
    assert {name: (folder / name).read_bytes() for name in preserved} == preserved
    assert journal.read_bytes() == ledger_before
    assert forecast_ledger.read_published_forecast(report.report_id) == published["snapshot"]
    response = published["client"].post("/api/v1/resolve/" + report.report_id, json={"outcome": "Base case"})
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["data"]["scoring"]["brier"] == pytest.approx(.18)
    assert ReportManager.publication_status(report.report_id)["publishable"]
    # Successful adjudication may append its own event; retirement must not
    # replace the original publication prefix or immutable forecast snapshot.
    assert journal.read_bytes().startswith(ledger_before)
    assert forecast_ledger.read_published_forecast(report.report_id) == published["snapshot"]
    assert (folder / "final_audit.json").read_bytes() == preserved["final_audit.json"]


def test_atomic_retirement_write_failure_propagates_without_mutating_publication(published, monkeypatch):
    import os
    report, folder = published["report"], published["folder"]
    before = {name: (folder / name).read_bytes() for name in
              ("meta.json", "forecast.json", "full_report.md", "final_audit.json")}
    journal = published["ledger"] / "published_forecasts.jsonl"
    ledger_before = journal.read_bytes()
    original = os.replace
    def fail_marker_commit(source, destination):
        if Path(destination).name == "current_simulation_retirement.json":
            raise OSError("fixture atomic marker commit failure")
        return original(source, destination)
    monkeypatch.setattr(os, "replace", fail_marker_commit)
    with pytest.raises(OSError, match="marker commit"):
        ReportManager.retire_reports_for_simulation(report.simulation_id)
    assert not ReportManager.is_report_retired(report.report_id)
    assert ReportManager.get_report_by_simulation(report.simulation_id).report_id == report.report_id
    assert {name: (folder / name).read_bytes() for name in before} == before
    assert journal.read_bytes() == ledger_before
    assert not list(folder.glob(".tmp-*"))


@pytest.mark.parametrize("artifact", ["full_report.md", "forecast.json"])
def test_retired_history_still_rejects_tampered_publication(published, artifact):
    report, folder = published["report"], published["folder"]
    journal = published["ledger"] / "published_forecasts.jsonl"
    before = journal.read_bytes()
    ReportManager.retire_reports_for_simulation(report.simulation_id)
    (folder / artifact).write_text("Tampered after historical publication")
    assert not ReportManager.publication_status(report.report_id)["publishable"]
    response = published["client"].post("/api/v1/resolve/" + report.report_id, json={"outcome": "Base case"})
    assert response.status_code == 409, response.get_json()
    assert journal.read_bytes() == before
