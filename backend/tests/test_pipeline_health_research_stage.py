"""RESEARCH-2: pipeline_health.stages.research (PIPELINE_HEALTH_RESEARCH_STAGE, default off).

A degraded research_quality becomes a degraded (never failed) research stage,
and the executive brief's honesty note names it.  Offline: the report
assessment is stubbed and the brief reads a pipeline_state.json on disk.
"""

from __future__ import annotations

import json

from app.config import Config
from app.services import exec_brief as eb
from app.services import pipeline_orchestrator as po

_ISSUES = [f"issue {i}: " + "x" * 300 for i in range(10)]


def _enforce(monkeypatch, *, flag: bool, research_quality=None) -> dict:
    orch = po.PipelineOrchestrator()
    state = po.PipelineState(pipeline_id="pipe_research", prompt="q", mode="full", status="running")
    if research_quality is not None:
        state.options["research_quality"] = research_quality
    monkeypatch.setattr(po.PipelineOrchestrator, "_assess_report_health", lambda self, rid: ("ok", [], {}))
    monkeypatch.setattr(Config, "PIPELINE_HEALTH_GATE", True, raising=False)
    monkeypatch.setattr(Config, "PIPELINE_HEALTH_RESEARCH_STAGE", flag, raising=False)
    orch._enforce_pipeline_health(state)
    return state.options["pipeline_health"]


def test_degraded_research_quality_is_a_degraded_research_stage(monkeypatch):
    health = _enforce(monkeypatch, flag=True,
                      research_quality={"score": 0.41, "degraded": True, "degradation": _ISSUES})
    stage = health["stages"]["research"]
    assert stage["health"] == "degraded" and stage["score"] == 0.41
    assert stage["issues"] == [issue[:200] for issue in _ISSUES[:8]]
    assert health["status"] == "degraded" and health["stages"]["report"]["health"] == "ok"


def test_research_stage_never_fails_the_pipeline(monkeypatch):
    # Every degradation a run can carry stays degrade-only: no hard issue, no raise.
    health = _enforce(monkeypatch, flag=True,
                      research_quality={"score": 0.0, "degraded": True,
                                        "degradation": "evidence_unavailable: no sourced evidence"})
    assert health["status"] == "degraded"
    assert health["stages"]["research"] == {"health": "degraded", "score": 0.0,
                                            "issues": ["evidence_unavailable: no sourced evidence"]}


def test_flag_off_or_healthy_research_adds_no_stage(monkeypatch):
    degraded = {"score": 0.41, "degraded": True, "degradation": ["a"]}
    assert "research" not in _enforce(monkeypatch, flag=False, research_quality=degraded)["stages"]
    assert _enforce(monkeypatch, flag=False, research_quality=degraded)["status"] == "ok"
    assert "research" not in _enforce(monkeypatch, flag=True, research_quality={"score": 0.9})["stages"]
    assert "research" not in _enforce(monkeypatch, flag=True)["stages"]


def test_research_health_stage_is_pure_and_tolerant():
    assert po._research_health_stage(None) is None
    assert po._research_health_stage({"degraded": False, "degradation": ["a"]}) is None
    assert po._research_health_stage({"degraded": True}) == {"health": "degraded", "issues": [], "score": None}
    assert po._research_health_stage({"degraded": True, "degradation": ["", "  ", 7]})["issues"] == ["7"]


def _report_dir(tmp_path, pipeline_health: dict):
    uploads = tmp_path / "uploads"
    report_dir = uploads / "reports" / "report_1"
    report_dir.mkdir(parents=True)
    (report_dir / "telemetry.json").write_text(json.dumps({"totals": {"run_id": "pipe_1"}}), encoding="utf-8")
    state_dir = uploads / "pipelines" / "pipe_1"
    state_dir.mkdir(parents=True)
    (state_dir / "pipeline_state.json").write_text(
        json.dumps({"options": {"pipeline_health": pipeline_health}}), encoding="utf-8")
    return str(report_dir)


def test_honesty_note_names_the_research_degradation(tmp_path):
    first = "3 of 10 searches failed " + "y" * 200
    report_dir = _report_dir(tmp_path, {"status": "degraded", "stages": {
        "report": {"health": "ok", "issues": []},
        "research": {"health": "degraded", "issues": [first, "b", "c"], "score": 0.4}}})
    en = eb._build_honesty_note(None, report_dir, eb._LABELS["en"])
    assert en == f"pipeline health degraded; research degraded ({first[:120]} +2)"
    assert "research degraded (" in en
    zh = eb._build_honesty_note(None, report_dir, eb._LABELS["zh"])
    assert "研究阶段降级" in zh and zh.startswith("管线健康 degraded；研究阶段降级 (")


def test_honesty_note_research_stage_without_issues_and_without_stage(tmp_path):
    bare = _report_dir(tmp_path / "bare", {"status": "degraded", "stages": {
        "research": {"health": "degraded", "issues": [], "score": None}}})
    assert eb._build_honesty_note(None, bare, eb._LABELS["en"]) == "pipeline health degraded; research degraded"
    single = _report_dir(tmp_path / "single", {"status": "degraded", "stages": {
        "research": {"health": "degraded", "issues": ["only one"]}}})
    assert eb._build_honesty_note(None, single, eb._LABELS["en"]).endswith("research degraded (only one)")
    none = _report_dir(tmp_path / "none", {"status": "ok", "stages": {"report": {"health": "ok"}}})
    assert eb._build_honesty_note(None, none, eb._LABELS["en"]) == "pipeline health ok"


def test_label_tables_stay_parallel():
    assert eb._LABELS["en"]["research_degraded"] == "research degraded"
    assert eb._LABELS["zh"]["research_degraded"] == "研究阶段降级"
    assert set(eb._LABELS["en"]) == set(eb._LABELS["zh"])
