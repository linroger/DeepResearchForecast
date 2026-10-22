"""ADR 0003 slice S3 — the fenced scenario-simulation bridge on the default OASIS engine.

T1  byte-level information flow: two real default-engine runs that differ ONLY in their
    simulation artifacts produce byte-identical spine, binary, section, critique and repair
    prompts, an identical forecast.json apart from the bridge hash, and reports that differ
    only between the bridge markers.
T2  the prose handed to the no-spine fallback extractor carries no leakage hit and none of
    the fixture's unique simulation tokens.
T6  policy: no_update → no block, no link, no field; diagnostic_only → exactly one block whose
    bytes equal the renderer.
T8  the what-if table appears only inside the bridge; the decisive-move selection rule is
    pinned on a fixture.

Everything here is offline (scripted model, stub graph tools, fresh upload roots from the
autouse ``_no_checkout_uploads`` fixture) and runs in the plain suite.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.config import Config
from app.services import report_agent as ra
from app.services import report_lint as rl
from app.services import sim_provenance as sp
from app.services.report_agent import ReportAgent, ReportManager, ReportStatus
from tests.conftest import FakeLLMClient

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sim"
SCENARIOS = ("Expansion", "Status quo")
TOKENS = ("ZORBLAX_QUUX_A", "ZORBLAX_QUUX_B")   # unique simulation tokens, same length


# ── fixtures: two default-engine simulation directories differing only in sim artifacts ──

def _record_fixture(name: str) -> Dict[str, Any]:
    return json.loads((FIXTURES / f"simulation_record.{name}.json").read_text(encoding="utf-8"))


def write_sim(root: Path, sim_id: str, *, shares: Dict[str, float], token: str,
              record: bool = True, paths_k: int = 1) -> Path:
    """A reflexive-OASIS simulation directory: trajectory, world state, history, run summary
    and (optionally) a gate-passed after-action record.  ``token`` marks every text field that
    only the simulation knows, so a prompt or report body containing it proves a leak."""
    directory = root / sim_id
    directory.mkdir(parents=True)
    (directory / "run_summary.json").write_text(json.dumps({
        "simulation_id": sim_id, "simulation_health": "ok", "organic_action_count": 40,
        "total_rounds": 2, "rounds_executed": 2, "temporal_mode": "calendar", "calendar_unit": "week",
        "horizon_date": "2026-11-14",
        "world_model": {"rounds_committed": 2, "arbiter_failed_rounds": 0, "seed_gaps": 1},
    }), encoding="utf-8")
    (directory / "world_state_trajectory.json").write_text(json.dumps({
        "schema_version": 3, "mode": "calendar", "validity": "valid", "calendar_unit": "week",
        "horizon_date": "2026-11-14", "n_rounds": 2, "converged_at": None, "scenarios": list(SCENARIOS),
        "outcome": {"shares": shares, "rounds": 2, "epistemic_status": "elicited_model_projection"},
        "trajectory": [{"round": 0, "shares": {"Expansion": 0.5, "Status quo": 0.5}, "as_of": "2026-11-01"},
                       {"round": 1, "shares": shares}],
    }), encoding="utf-8")
    (directory / "world_state.json").write_text(json.dumps({
        "schema_version": 1, "simulation_id": sim_id, "committed_round": 2,
        "summary": {"variables": 1, "events": 2, "arbiter_failed_rounds": 0, "seed_gaps": 1},
        "world": {
            "as_of_date": "2026-11-01", "horizon_date": "2026-11-14", "scenarios": list(SCENARIOS),
            "scenario_shares": shares, "period_labels": {"1": "2026-W45", "2": "2026-W46"},
            "variables": [{"id": "tariff", "name": f"Tariff rate {token}", "value": 145.0, "unit": "%",
                           "history": [{"round": 0, "value": 10.0, "cause": "seed"},
                                       {"round": 1, "value": 145.0, "cause": f"Actor B order {token}"}]}],
            "actors": [{"agent_id": 0, "name": "Actor A", "red_lines": ["No tariff above 100%"], "commitments": []},
                       {"agent_id": 1, "name": "Actor B", "red_lines": [], "commitments": []}],
            "events": [], "interactions": [], "seed_gaps": [f"actor_without_plans: Actor B {token}"],
        },
    }), encoding="utf-8")
    rows = [
        {"round": 1, "period_label": "2026-W45", "arbiter_status": "applied",
         "narrative": f"Actor B raised its tariff {token}.",
         "deterministic": {"actions": [f"Raise tariff {token} → Actor A"], "commitments_lapsed": [],
                           "red_lines_crossed": [f"Actor B crossed Actor A's red line {token}"]},
         "shares": {"Expansion": 0.5, "Status quo": 0.5}},
        {"round": 2, "period_label": "2026-W46", "arbiter_status": "applied",
         "narrative": f"Talks resumed {token}.",
         "deterministic": {"actions": [], "commitments_lapsed": [f"Actor B: keep the tariff {token}"]},
         "shares": shares},
    ]
    (directory / "world_state_history.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    if paths_k > 1:
        (directory / "world_paths.json").write_text(json.dumps({
            "schema_version": "world-paths/v1", "k": paths_k,
            "shares": {name: {"mean": value, "sd": 0.05, "p10": max(0.0, value - 0.06), "p50": value,
                              "p90": min(1.0, value + 0.07)} for name, value in shares.items()},
        }), encoding="utf-8")
    if record:
        rec = _record_fixture("paths")
        rec["simulation_id"] = sim_id
        rec["setup"]["scenarios"] = list(SCENARIOS)
        rec["overall"]["shares"] = {"final": dict(shares), "converged_at": None,
                                    "paths": {"k": 1, "per_scenario": {}}}
        for period in rec["periods"]:
            if period["narrative"]:
                period["narrative"] += " " + token
            for move in period["moves"]:
                move["public_statement"] += " " + token
        (directory / "simulation_record.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        md_text = f"# Simulation After-Action Record {token}\n"
        (directory / "simulation_record.md").write_text(md_text, encoding="utf-8")
        (directory / "simulation_record_audit.json").write_text(json.dumps({
            "sha256": hashlib.sha256(md_text.encode("utf-8")).hexdigest(),
            "hard_issues": [], "warnings": [], "publication_status": "passed",
        }), encoding="utf-8")
    return directory


class StubZep:
    """Graph tools that return nothing: the report is driven by the research report alone."""

    def get_simulation_context(self, **kwargs):
        return {}

    def __getattr__(self, name):
        def _empty(*args, **kwargs):
            return ""
        return _empty


OUTLINE = {"title": "Supply outlook", "summary": "The external research supports cautious planning.",
           "sections": [{"title": "Supply and demand", "description": "Assess the observed constraints."}]}
FORECAST = {
    "headline": "Evidence outlook", "confidence": "low",
    "scenarios": [
        {"name": "Expansion", "probability": 0.6, "description": "External evidence",
         "resolution_criteria": "Expansion is recorded by the horizon."},
        {"name": "Status quo", "probability": 0.4, "description": "External evidence",
         "resolution_criteria": "Expansion is not recorded by the horizon."}],
    "binary_forecasts": [{"id": "F1", "statement": "Capacity exceeds the documented target by the horizon.",
                          "probability": 0.35, "theme": "capacity", "horizon_year": 2027,
                          "resolution_criteria": "The documented capacity figure exceeds the target at the horizon."}],
}
PROSE = " ".join(
    f"{word} depends on observed conditions and documented institutional constraints. "
    "A decision requires checking the underlying evidence and the scope of the relevant mandate."
    for word in ("Investment", "Supply", "Demand", "Competition", "Financing", "Planning",
                 "Production", "Distribution", "Procurement", "Trade", "Coordination", "Execution"))


class ScriptedModel(FakeLLMClient):
    """Records every prompt; answers the outline, every forecast draw and every section/critique
    deterministically, so two runs can only differ through what the pipeline injects."""

    def __init__(self, *, fail_spine: bool = False):
        super().__init__()
        self.fail_spine = fail_spine
        self.forecast_calls = 0

    def chat_json(self, messages, **kwargs):
        self.calls.append({"kind": "chat_json", "messages": messages})
        system = " ".join(str(m.get("content") or "") for m in messages if m.get("role") == "system")
        if "首席分析师" in system:          # plan_outline (PLAN_SYSTEM_PROMPT)
            return copy.deepcopy(OUTLINE)
        self.forecast_calls += 1
        if self.fail_spine and self.forecast_calls == 1:
            return {}                        # the pre-prose spine fails → post-hoc extraction from prose
        return copy.deepcopy(FORECAST)

    def chat(self, messages, **kwargs):
        self.calls.append({"kind": "chat", "messages": messages})
        system = str(messages[0].get("content") or "") if messages else ""
        if "质检员" in system:               # section critique
            return "PASS"
        return "Final Answer: " + PROSE


@pytest.fixture
def report_config(monkeypatch):
    for name in ("REPORT_BILINGUAL", "REPORT_FORECAST_LEDGER", "REPORT_VISUALIZATIONS",
                 "REPORT_PUBLISH_GATE", "REPORT_LANGUAGE_PURITY", "REPORT_THREE_PART_SKELETON",
                 "REPORT_SECTION_CONTINUE", "REPORT_TELEMETRY", "LLM_TELEMETRY_ENABLED",
                 "PREDICTION_MARKETS_ENABLED", "REPORT_FORECAST_SELF_CRITIQUE", "REPORT_CITATION_REPAIR",
                 "REPORT_COMPARISON_TABLE", "FORECAST_SIM_SENSITIVITY"):
        monkeypatch.setattr(Config, name, False, raising=False)
    for name in ("REPORT_STRUCTURED_FORECAST", "REPORT_CITATION_FINALIZER", "REPORT_EDITORIAL_LINT",
                 "REPORT_FINAL_READ_ONLY_AUDIT", "REPORT_SECTION_REFLECTION", "FORECAST_EMIT_BINARY",
                 "REPORT_REPAIR_PASSES", "REPORT_SIGNAL_PACK"):
        monkeypatch.setattr(Config, name, True, raising=False)   # SIGNAL_PACK on: it must still be empty
    monkeypatch.setattr(Config, "REPORT_SECTION_CONCURRENCY", 1, raising=False)
    monkeypatch.setattr(Config, "REPORT_SECTION_CONTEXT_MODE", "full", raising=False)
    monkeypatch.setattr(Config, "FORECAST_BINARY_MIN_COUNT", 1, raising=False)
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "diagnostic_only", raising=False)
    monkeypatch.setattr(ReportAgent, "MIN_TOOL_CALLS_PER_SECTION", 0)
    monkeypatch.setattr(ReportAgent, "OUTLINE_PAD_FLOOR_SECTIONS", 1)
    monkeypatch.setattr(ReportAgent, "_locate_timeline", lambda self: None)
    monkeypatch.setattr(ReportAgent, "_locate_handoff_dir", lambda self: None)


def make_agent(sim_id: str, model: FakeLLMClient, **kwargs) -> ReportAgent:
    return ReportAgent("graph_test", sim_id, "What happens to the tariff regime by 2027?",
                       llm_client=model, zep_tools=StubZep(),
                       research_report=kwargs.pop(
                           "research_report",
                           "EXTERNAL_EVIDENCE: documented capacity observations from the ministry."),
                       **kwargs)


def run_pair(*, fail_spine: bool = False, record: bool = True):
    """Two complete default-engine runs; the directories differ only in simulation artifacts."""
    root = Path(Config.OASIS_SIMULATION_DATA_DIR)
    runs = []
    for index, (token, shares) in enumerate(zip(TOKENS, ({"Expansion": 0.44, "Status quo": 0.56},
                                                         {"Expansion": 0.70, "Status quo": 0.30}))):
        sim_id = f"sim_bridge_pair_{index}"
        write_sim(root, sim_id, shares=shares, token=token, record=record)
        model = ScriptedModel(fail_spine=fail_spine)
        agent = make_agent(sim_id, model)
        report = agent.generate_report(report_id=f"report_bridge_pair_{index}")
        assert report.status == ReportStatus.COMPLETED, report.error
        runs.append((agent, report, model))
    return runs


def _forecast(report_id: str) -> Dict[str, Any]:
    path = Path(ReportManager._get_report_folder(report_id)) / "forecast.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _comparable_forecast(forecast: Dict[str, Any]) -> Dict[str, Any]:
    """forecast.json without the bridge hash and the per-report audit envelope (its timestamp,
    report id, markdown hashes and its own bridge record) — everything else must be identical."""
    data = copy.deepcopy(forecast)
    data.pop("simulation_bridge", None)
    quality = data.get("quality") if isinstance(data.get("quality"), dict) else {}
    quality.pop("final_audit", None)
    return data


def _prompt_text(calls: List[Dict[str, Any]]) -> str:
    return json.dumps([c["messages"] for c in calls], ensure_ascii=False)


# ── T1 ──────────────────────────────────────────────────────────────────────

def test_t1_two_simulations_yield_identical_prompts_forecast_and_body(report_config):
    runs = run_pair()
    (a0, r0, m0), (a1, r1, m1) = runs
    # every prompt the model saw — outline, spine, binary top-up, section, critique, repair —
    # is byte-identical across the two simulations
    assert [c["messages"] for c in m0.calls] == [c["messages"] for c in m1.calls]
    assert len(m0.calls) >= 4
    for token in TOKENS:
        assert token not in _prompt_text(m0.calls) and token not in _prompt_text(m1.calls)
    # the signal pack is empty on the default engine under diagnostic_only even with the flag on
    assert a0._signal_pack == "" and a0._build_signal_pack() == ""
    assert "interview_agents" not in a0.tools
    # forecast.json identical apart from the bridge hash (and the audit envelope naming the report)
    f0, f1 = _forecast(r0.report_id), _forecast(r1.report_id)
    assert f0["simulation_bridge"]["sha256"] != f1["simulation_bridge"]["sha256"]
    for forecast in (f0, f1):
        assert forecast["simulation_bridge"]["forecast_effect"] == "diagnostic_only"
        assert forecast["simulation_bridge"]["probabilityEvidence"] is False
        assert forecast["quality"]["final_audit"]["hard_passed"] is True
    assert _comparable_forecast(f0) == _comparable_forecast(f1)
    # the reports differ only between the bridge markers
    md0, md1 = r0.markdown_content, r1.markdown_content
    assert md0 != md1
    assert ra._sim_prose(md0) == ra._sim_prose(md1)
    for agent, report, token in ((a0, r0, TOKENS[0]), (a1, r1, TOKENS[1])):
        blocks = ra._sim_bridge_blocks(report.markdown_content)
        assert len(blocks) == 1
        assert blocks[0] == agent._render_sim_bridge_for_report(report.report_id, chinese=False)
        assert token in blocks[0] and token not in ra._sim_prose(report.markdown_content)
        assert sp.BRIDGE_TITLE_EN in blocks[0] and sp.SIM_BANNER_EN in blocks[0]
        assert rl.leakage_hits(ra._sim_prose(report.markdown_content)) == []
        # the record link carries the gate's seal
        audit = json.loads((Path(Config.OASIS_SIMULATION_DATA_DIR) / report.simulation_id
                            / "simulation_record_audit.json").read_text())
        assert audit["sha256"] in blocks[0]
        # the full published file equals memory and the final audit recorded the bridge
        disk = (Path(ReportManager._get_report_folder(report.report_id)) / "full_report.md").read_text()
        assert disk == report.markdown_content
        final_audit = json.loads((Path(ReportManager._get_report_folder(report.report_id))
                                  / "final_audit.json").read_text())
        assert final_audit["simulation_bridge"] == {
            "expected_count": 1, "count": 1, "bytes_match": True,
            "sha256": hashlib.sha256(blocks[0].encode("utf-8")).hexdigest(), "policy": "diagnostic_only"}


# ── T2 ──────────────────────────────────────────────────────────────────────

def test_t2_no_spine_fallback_prose_carries_no_simulation_bytes(report_config, monkeypatch):
    """With no pre-prose spine, forecast.json is extracted from the finished prose: that prose
    must carry no leakage hit and no simulation token (the bridge is inserted only after)."""
    from app.services import forecast_extractor as fe
    captured: List[str] = []
    original = fe.extract_structured_forecast

    def spy(report_markdown, llm, **kwargs):
        captured.append(report_markdown)
        return original(report_markdown, llm, **kwargs)

    monkeypatch.setattr(fe, "derive_forecast_spine", lambda llm, **kwargs: None)
    monkeypatch.setattr(fe, "extract_structured_forecast", spy)
    runs = run_pair()
    assert len(captured) == 2, "the post-hoc extractor must have run once per report"
    for prose in captured:
        assert prose.strip()
        assert rl.leakage_hits(prose) == []
        for token in TOKENS:
            assert token not in prose
        assert sp.BRIDGE_START not in prose and sp.SIM_LABEL_EN not in prose
    assert captured[0] == captured[1]
    for _agent, _report, model in runs:
        text = json.dumps([c["messages"] for c in model.calls if c["kind"] == "chat_json"], ensure_ascii=False)
        for token in TOKENS:
            assert token not in text
    assert [c["messages"] for c in runs[0][2].calls] == [c["messages"] for c in runs[1][2].calls]


# ── T6 ──────────────────────────────────────────────────────────────────────

def test_t6_no_update_has_no_block_no_link_no_field(report_config, monkeypatch):
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "no_update", raising=False)
    root = Path(Config.OASIS_SIMULATION_DATA_DIR)
    write_sim(root, "sim_bridge_nu", shares={"Expansion": 0.44, "Status quo": 0.56}, token=TOKENS[0])
    model = ScriptedModel()
    agent = make_agent("sim_bridge_nu", model)
    report = agent.generate_report(report_id="report_bridge_nu")
    assert report.status == ReportStatus.COMPLETED, report.error
    assert sp.BRIDGE_START not in report.markdown_content
    assert "simulation_record.md" not in report.markdown_content
    assert TOKENS[0] not in report.markdown_content
    assert "simulation_bridge" not in _forecast(report.report_id)
    final_audit = json.loads((Path(ReportManager._get_report_folder(report.report_id))
                              / "final_audit.json").read_text())
    assert final_audit["simulation_bridge"] == {
        "expected_count": 0, "count": 0, "bytes_match": True, "sha256": None, "policy": "no_update"}
    assert agent._build_signal_pack() == ""


def test_t6_diagnostic_only_exactly_one_block_equal_to_the_renderer(report_config):
    (agent, report, _model), = run_pair()[:1]
    blocks = ra._sim_bridge_blocks(report.markdown_content)
    assert len(blocks) == 1
    assert report.markdown_content.count(sp.BRIDGE_START) == 1
    assert report.markdown_content.count(sp.BRIDGE_END) == 1
    assert blocks[0] == agent._render_sim_bridge_for_report(report.report_id, chinese=False)
    # shares are called shares; the only probabilities named are the report's own
    text = ra._SIM_BRIDGE_TEXT["en"]
    assert "| Scenario | Final simulated share | Report probability |" in blocks[0]
    share_rows = [line for line in blocks[0].splitlines() if line.startswith("| Expansion |")]
    assert share_rows == ["| Expansion | 44.0% | 60% |"]
    assert text["unchanged"].format(policy="diagnostic_only") in blocks[0]
    # inserted before the References appendix, like the world-v1 appendix
    for heading in ra._REFS_HEADINGS:
        if heading in report.markdown_content:
            assert report.markdown_content.index(sp.BRIDGE_END) < report.markdown_content.index(heading)


def test_absent_record_uses_the_artifact_adapter_and_says_so(report_config):
    root = Path(Config.OASIS_SIMULATION_DATA_DIR)
    write_sim(root, "sim_bridge_norec", shares={"Expansion": 0.44, "Status quo": 0.56}, token=TOKENS[0],
              record=False, paths_k=4)
    model = ScriptedModel()
    agent = make_agent("sim_bridge_norec", model)
    report = agent.generate_report(report_id="report_bridge_norec")
    assert report.status == ReportStatus.COMPLETED, report.error
    blocks = ra._sim_bridge_blocks(report.markdown_content)
    assert len(blocks) == 1
    block = blocks[0]
    text = ra._SIM_BRIDGE_TEXT["en"]
    assert text["no_record"] in block and "simulation_record.md" not in block
    assert text["moves_none"] in block
    # final shares, K-path spread, red lines and lapsed commitments from the raw artifacts
    assert "| Expansion | 44.0% (p10–p90 38.0%–51.0%) | 60% |" in block
    assert "| Status quo | 56.0% (p10–p90 50.0%–63.0%) | 40% |" in block
    assert f"2026-W45: Actor B crossed Actor A's red line {TOKENS[0]}" in block
    assert f"2026-W46: Actor B: keep the tariff {TOKENS[0]}" in block
    assert "- Engine: oasis-reflexive" in block and "- Health: ok (validity: valid)" in block
    assert "- Periods committed: 2 of 2 planned" in block
    assert block == agent._render_sim_bridge_for_report(report.report_id, chinese=False)
    assert TOKENS[0] not in ra._sim_prose(report.markdown_content)


def test_no_simulation_artifacts_leaves_the_report_untouched(report_config):
    (Path(Config.OASIS_SIMULATION_DATA_DIR) / "sim_bridge_empty").mkdir(parents=True)
    model = ScriptedModel()
    agent = make_agent("sim_bridge_empty", model)
    report = agent.generate_report(report_id="report_bridge_empty")
    assert report.status == ReportStatus.COMPLETED, report.error
    assert sp.BRIDGE_START not in report.markdown_content
    assert "simulation_bridge" not in _forecast(report.report_id)
    final_audit = json.loads((Path(ReportManager._get_report_folder(report.report_id))
                              / "final_audit.json").read_text())
    assert final_audit["simulation_bridge"]["expected_count"] == 0
    assert final_audit["simulation_bridge"]["count"] == 0


# ── T8 ──────────────────────────────────────────────────────────────────────

def _bare_agent(**attrs) -> ReportAgent:
    agent = ReportAgent.__new__(ReportAgent)
    agent.output_language = "English"
    agent.simulation_id = attrs.pop("simulation_id", "sim_bridge_unit")
    agent._forecast_spine = None
    for key, value in attrs.items():
        setattr(agent, key, value)
    return agent


def test_t8_whatif_table_appears_only_inside_the_bridge(report_config, monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "REPORT_COMPARISON_TABLE", True, raising=False)
    monkeypatch.setattr(Config, "SIMULATION_FORECAST_EFFECT", "diagnostic_only", raising=False)
    root = Path(Config.OASIS_SIMULATION_DATA_DIR)
    write_sim(root, "sim_bridge_whatif", shares={"Expansion": 0.44, "Status quo": 0.56}, token=TOKENS[0])
    report_id = "report_bridge_whatif"
    folder = Path(ReportManager._ensure_report_folder(report_id))
    diff = {"base_simulation_id": "sim_base", "scenario_simulation_id": "sim_bridge_whatif",
            "scenario_label": "tariff shock",
            "dimensions": [{"name": "Expansion", "baseline": "50.0%", "scenario": "44.0%",
                            "delta": "-6.0 pp", "verdict": "更不可能"},
                           {"name": "Status quo", "baseline": "50.0%", "scenario": "56.0%",
                            "delta": "+6.0 pp", "verdict": "更可能"}]}
    (folder / "comparison.json").write_text(json.dumps(diff, ensure_ascii=False), encoding="utf-8")
    (folder / "forecast.json").write_text(json.dumps(FORECAST), encoding="utf-8")
    agent = _bare_agent(simulation_id="sim_bridge_whatif")
    table = ReportAgent._render_comparison_table(diff)
    assert sp.WHATIF_TABLE_TITLE_ZH in table and sp.WHATIF_TABLE_NOTE_ZH in table
    block = agent._render_sim_bridge_for_report(report_id, chinese=False)
    assert table in block
    body = "# Report\n\n## Supply and demand\n\nObserved prose.\n\n## References\n\n1. [S1] Source\n"
    md = ra._insert_sim_bridge(body, block)
    # the table lives in the bridge and nowhere in the prose; the body's lint sees no label
    assert md.count(sp.WHATIF_TABLE_TITLE_ZH) == 1
    assert sp.WHATIF_TABLE_TITLE_ZH not in ra._sim_prose(md)
    assert rl.leakage_hits(md) == []
    linted, rep = rl.lint_report(md, "English", mode="final")
    assert linted == md and rep["changed"] is False
    # the section loop no longer prepends it: a comparison section stays prose-only
    assert not any("section_content = table_md" in line
                   for line in Path(ra.__file__).read_text(encoding="utf-8").splitlines())


def test_t8_decisive_move_selection_rule_is_pinned():
    record = _record_fixture("paths")
    # two more periods: an accepted offer party and large/small relative variable changes
    record["periods"].append({
        "round": 3, "label": "2026-W47", "arbiter_status": "applied", "arbiter_problems": [],
        "narrative": "", "held_position": [], "events": [], "shocks_fired": [], "red_lines_crossed": [],
        "alliances": [], "behaviour": {}, "refs": [],
        "moves": [
            {"actor": "Actor C", "option": "Cut quota", "targets": ["Actor A"], "public_statement": "Quota halved."},
            {"actor": "Actor D", "option": "Issue statement", "targets": [], "public_statement": "x" * 200},
            {"actor": "Actor E", "option": "Accept talks", "targets": ["Actor A"], "public_statement": "We accept."},
        ],
        "facts_changed": [
            {"variable": "Quota", "from": 100, "to": 40, "unit": "t", "cause": "Actor C quota order"},
            {"variable": "Index", "from": 50, "to": 55, "unit": "", "cause": "Actor D statement"},
        ],
        "offers": [{"from": "Actor A", "to": "Actor E", "kind": "talks", "status": "accepted", "terms": "t"}],
    })
    rows = ra._bridge_select_decisive_moves(record["periods"])
    actors = [row[1] for row in rows]
    # red-line crosser first (Actor B, W45); then offer parties — Actor A (W45, accepted offer
    # party) before Actor E (W47); then the largest relative change (Actor C 60%) before the
    # smaller one (Actor D 10%)
    assert actors == ["Actor B", "Actor A", "Actor E", "Actor C", "Actor D"]
    assert rows[0][0] == "2026-W45" and rows[2][0] == "2026-W47"
    statement = rows[-1][4]
    assert len(statement) == ra._SIM_BRIDGE_STATEMENT_CHARS + 1 and statement.endswith("…")
    # at most eight rows
    many = copy.deepcopy(record["periods"][0])
    many["moves"] = [{"actor": f"Actor {i:02d}", "option": "o", "targets": [], "public_statement": "s"}
                     for i in range(12)]
    many["red_lines_crossed"] = []
    many["offers"] = []
    assert len(ra._bridge_select_decisive_moves([many])) == ra._SIM_BRIDGE_MAX_MOVES
    assert ra._bridge_select_decisive_moves([]) == []


def test_bridge_insertion_is_idempotent_and_relocates_placed_simulated_charts(tmp_path):
    record = _record_fixture("en")
    charts = [{"id": "worldstate_trajectory", "path": "charts/worldstate_trajectory.png",
               "image": "charts/worldstate_trajectory.png"}]
    block = ra.render_sim_bridge(record, chinese=False, spine=None, chart_rel_paths=charts,
                                 whatif_table_md="", record_sha256="deadbeef")
    body = ("# R\n\n## Evidence\n\nProse.\n\n<!-- viz:charts/worldstate_trajectory.png -->\n"
            "![Simulated outcome-share trajectory](charts/worldstate_trajectory.png)\n\n"
            "*Simulated outcome-share trajectory*\n\n## References\n\n1. [S1] x\n")
    once = ra._insert_sim_bridge(body, block)
    twice = ra._insert_sim_bridge(once, block)
    assert once == twice
    assert once.count(sp.BRIDGE_START) == 1 and once.count("<!-- viz:charts/worldstate_trajectory.png -->") == 2
    # _place_visualizations skips the simulated chart when the bridge is active
    agent = _bare_agent()
    agent._world_binding = None
    manifest = [{"id": "worldstate_trajectory", "type": "png", "path": "charts/worldstate_trajectory.png",
                 "caption": sp.CHART_OUTCOME_SHARES_EN, "placement_hint": "simulation"},
                {"id": "scenario_probabilities", "type": "png", "path": "charts/scenario_probabilities.png",
                 "caption": "Scenario Probabilities", "placement_hint": "scenarios"}]
    md = "# R\n\n## Scenario outlook\n\nProse.\n"
    placed = agent._place_visualizations(md, str(tmp_path), manifest)
    assert "charts/scenario_probabilities.png" in placed
    assert "charts/worldstate_trajectory.png" not in placed


def test_reconstructed_agent_resolves_the_simulation_from_the_report_meta(report_config):
    """The backfill and translation workers build agents without the constructor (no
    ``simulation_id``); the audit still renders the same bridge from the report's meta.json."""
    root = Path(Config.OASIS_SIMULATION_DATA_DIR)
    write_sim(root, "sim_bridge_meta", shares={"Expansion": 0.44, "Status quo": 0.56}, token=TOKENS[0])
    report_id = "report_bridge_meta"
    ReportManager.save_report(ra.Report(report_id=report_id, simulation_id="sim_bridge_meta", graph_id="g",
                                        simulation_requirement="x", status=ReportStatus.COMPLETED,
                                        markdown_content="# x"))
    (Path(ReportManager._get_report_folder(report_id)) / "forecast.json").write_text(json.dumps(FORECAST))
    full = _bare_agent(simulation_id="sim_bridge_meta")
    worker = ReportAgent.__new__(ReportAgent)
    worker.output_language = "English"
    worker._forecast_spine = None
    assert worker._sim_dir(report_id) == full._sim_dir()
    assert worker._sim_dir() == ""
    block = worker._render_sim_bridge_for_report(report_id, chinese=False)
    assert block and block == full._render_sim_bridge_for_report(report_id, chinese=False)
    audit = worker._audit_sim_bridge(report_id, "# x\n\n" + block + "\n")
    assert audit["expected_count"] == 1 and audit["count"] == 1 and audit["bytes_match"] is True


def test_hollow_record_renders_banner_health_and_no_moves():
    record = _record_fixture("hollow")
    block = ra.render_sim_bridge(record, chinese=False, spine=FORECAST, chart_rel_paths=None,
                                 whatif_table_md="", record_sha256="cafe")
    text = ra._SIM_BRIDGE_TEXT["en"]
    assert "- Health: hollow (validity: valid)" in block
    assert "- Periods committed: 0 of 9 planned" in block
    assert text["moves_none"] in block and text["none"] in block
    assert "| Expansion | — | 60% |" in block and "| Status quo | — | 40% |" in block
    assert text["record"].format(sha="cafe") in block
    assert rl.leakage_hits(block) == []
