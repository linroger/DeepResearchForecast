"""Offline unit tests for orchestrator research-stage wiring.

Covers the pure helpers landed for R2-RES-7 (as_of anchor validation) and
R2-RES-3 (advisory forecast-confidence penalty). No network / LLM / disk.
"""

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.pipeline_orchestrator import (
    PipelineOrchestrator,
    _preserve_research_attempt_progress,
)


def test_failed_global_synthesis_progress_is_preserved_outside_disposable_stage(tmp_path):
    stage = tmp_path / ".global-synthesis-1-temp"
    handoff = tmp_path / "handoff"
    stage.mkdir()
    handoff.mkdir()
    (stage / "research_progress.log").write_text(
        "2026-01-01T00:00:00+00:00 [stage] synthesis started\n",
        encoding="utf-8",
    )

    preserved = _preserve_research_attempt_progress(
        str(stage),
        str(handoff),
        attempt=1,
        outcome="failed",
        detail="RuntimeError: provider timeout",
    )

    assert preserved is not None
    preserved_path = handoff / "research_attempts" / Path(preserved).name
    lines = preserved_path.read_text(encoding="utf-8").splitlines()
    assert lines[0].endswith("[stage] synthesis started")
    assert lines[-1].endswith(
        "[error] global synthesis attempt 1 failed: RuntimeError: provider timeout"
    )


# ── R2-RES-7: as_of anchor validation ───────────────────────────────────────

def _src(date_str):
    return {"title": "x", "url": "u", "tier": "S1", "date": date_str}


def test_as_of_valid_within_bounds_is_kept():
    actors = {"as_of_date": "2026-05-01"}
    sources = [_src("2026-01-01"), _src("2026-04-15")]
    dt, note = PipelineOrchestrator._validate_as_of_date(actors, sources)
    assert note is None
    assert dt is not None and dt.date().isoformat() == "2026-05-01"


def test_as_of_future_falls_back_to_max_source():
    future = (datetime.now(timezone.utc) + timedelta(days=400)).date().isoformat()
    actors = {"as_of_date": future}
    sources = [_src("2026-02-01"), _src("2026-03-20")]
    dt, note = PipelineOrchestrator._validate_as_of_date(actors, sources)
    assert note is not None and "晚于运行日" in note
    assert dt is not None and dt.date().isoformat() == "2026-03-20"


def test_as_of_predates_evidence_falls_back():
    actors = {"as_of_date": "2024-01-01"}
    sources = [_src("2026-02-01"), _src("2026-03-20")]
    dt, note = PipelineOrchestrator._validate_as_of_date(actors, sources)
    assert note is not None and "早于最新来源日" in note
    assert dt is not None and dt.date().isoformat() == "2026-03-20"


def test_as_of_unparseable_with_sources_falls_back():
    actors = {"as_of_date": "sometime last spring"}
    sources = [_src("2026-02-01")]
    dt, note = PipelineOrchestrator._validate_as_of_date(actors, sources)
    assert note is not None and "无法解析" in note
    assert dt is not None and dt.date().isoformat() == "2026-02-01"


def test_as_of_absent_no_sources_preserves_none():
    # degrade-safe: no anchor available → byte-identical to today's None behavior.
    dt, note = PipelineOrchestrator._validate_as_of_date({}, None)
    assert dt is None and note is None
    dt2, note2 = PipelineOrchestrator._validate_as_of_date(None, [])
    assert dt2 is None and note2 is None


def test_as_of_future_no_sources_uses_run_date():
    future = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
    dt, note = PipelineOrchestrator._validate_as_of_date({"as_of_date": future}, None)
    assert note is not None
    assert dt is not None and dt.date() == datetime.now(timezone.utc).date()


def test_as_of_garbage_inputs_never_raise():
    # tolerate any shape of dirty data
    for actors, sources in [(123, "nope"), ([], {}), ("x", [{"date": None}, 5])]:
        dt, note = PipelineOrchestrator._validate_as_of_date(actors, sources)
        assert dt is None or hasattr(dt, "date")


def test_as_of_ignores_a_source_dated_after_the_run():
    """TIME-2 (defensive): a misdated source after the run date is not the
    newest evidence, so it cannot push a valid as_of_date off."""
    run_date = datetime.now(timezone.utc).date()
    future = (run_date + timedelta(days=3)).isoformat()
    actors = {"as_of_date": "2026-05-01"}
    dt, note = PipelineOrchestrator._validate_as_of_date(actors, [_src("2026-04-15"), _src(future)])
    assert note is None and dt.date().isoformat() == "2026-05-01"
    # The newest past source still bounds the as-of from below.
    dt, note = PipelineOrchestrator._validate_as_of_date({"as_of_date": "2026-01-01"},
                                                         [_src("2026-04-15"), _src(future)])
    assert "早于最新来源日 2026-04-15" in note and dt.date().isoformat() == "2026-04-15"
    # Only future sources: no source bound; an absent as-of stays "no anchor".
    assert PipelineOrchestrator._validate_as_of_date({}, [_src(future)]) == (None, None)
    dt, note = PipelineOrchestrator._validate_as_of_date({"as_of_date": "garbage"}, [_src(future)])
    assert dt.date() == run_date and "无法解析" in note


# ── R2-RES-3: advisory forecast-confidence penalty ──────────────────────────

def test_penalty_zero_when_no_signals():
    pen, comp = PipelineOrchestrator._compute_forecast_confidence_penalty(None, None)
    assert pen == 0.0 and comp == {}


def test_penalty_from_low_research_quality():
    # Config.RESEARCH_QUALITY_FLOOR default 0.45; score 0.30 → 0.15 (capped).
    meta = {"research_quality": {"score": 0.30}}
    pen, comp = PipelineOrchestrator._compute_forecast_confidence_penalty(meta, None)
    assert comp.get("research_quality") == 0.15
    assert pen >= 0.15


def test_penalty_from_low_tier_sources():
    meta = {"source_tiers": {"S3": 4}}  # all low tier (weight 0.4) → (1-0.4)*0.1=0.06
    pen, comp = PipelineOrchestrator._compute_forecast_confidence_penalty(meta, None)
    assert comp.get("source_tier_mix") == 0.06
    # high-tier sources should yield no penalty
    pen2, comp2 = PipelineOrchestrator._compute_forecast_confidence_penalty(
        {"source_tiers": {"S1": 5}}, None)
    assert "source_tier_mix" not in comp2 and pen2 == 0.0


def _producer_tiers(**counts):
    """meta.source_tiers exactly as every producer emits it (bridge
    source_tier_histogram / orchestrator _source_tier_histogram)."""
    hist = {"s1_count": 0, "s2_count": 0, "s3_count": 0, "s4_count": 0, "s_unknown": 0}
    hist.update(counts)
    return hist


def test_penalty_reads_producer_source_tier_shape():
    """IF-10: the producer keys ('s1_count'…'s_unknown') used to miss the weight
    table, so ANY run with sources paid a constant 0.08 tier penalty."""
    pen, comp = PipelineOrchestrator._compute_forecast_confidence_penalty(
        {"source_tiers": _producer_tiers(s1_count=5)}, None)
    assert "source_tier_mix" not in comp and pen == 0.0

    _, comp = PipelineOrchestrator._compute_forecast_confidence_penalty(
        {"source_tiers": _producer_tiers(s3_count=4)}, None)
    assert comp["source_tier_mix"] == 0.06          # (1-0.4)*0.1, as for {"S3": 4}

    _, comp = PipelineOrchestrator._compute_forecast_confidence_penalty(
        {"source_tiers": _producer_tiers(s1_count=3, s3_count=3)}, None)
    assert comp["source_tier_mix"] == 0.03          # mean weight (1.0+0.4)/2 = 0.7


def test_penalty_producer_shape_matches_legacy_shape():
    for legacy, producer in (
        ({"S1": 3, "S2": 2}, _producer_tiers(s1_count=3, s2_count=2)),
        ({"s3": 4}, _producer_tiers(s3_count=4)),
        ({"S1": 1, "S3": 3}, {"S1_count": 1, "s3_count": 3}),
    ):
        assert (PipelineOrchestrator._compute_forecast_confidence_penalty(
            {"source_tiers": legacy}, None)
            == PipelineOrchestrator._compute_forecast_confidence_penalty(
                {"source_tiers": producer}, None))


def test_penalty_reject_tier_and_unknown_sources_keep_fallback_weight():
    # S4 (reject tier) and untiered sources keep the historical 0.2 weight.
    for tiers in (_producer_tiers(s4_count=4), _producer_tiers(s_unknown=4),
                  {"mystery": 4}):
        _, comp = PipelineOrchestrator._compute_forecast_confidence_penalty(
            {"source_tiers": tiers}, None)
        assert comp["source_tier_mix"] == 0.08, tiers
    # Non-numeric / non-positive counts are ignored, never raise.
    pen, comp = PipelineOrchestrator._compute_forecast_confidence_penalty(
        {"source_tiers": {"s1_count": "x", "s3_count": -2, "s_unknown": None}}, None)
    assert pen == 0.0 and comp == {}


def test_penalty_from_weak_dossier_coverage():
    cov = {"n_actors": 5, "pct_actors_with_incentives": 0.1,
           "n_relationships": 3, "pct_edges_valenced": 0.0}
    pen, comp = PipelineOrchestrator._compute_forecast_confidence_penalty(None, cov)
    assert comp.get("dossier_coverage") == 0.1  # two weak signals × 0.05
    assert pen == 0.1


def test_penalty_capped_at_0_3():
    meta = {"research_quality": {"score": 0.0}, "source_tiers": {"S3": 10}}
    cov = {"n_actors": 5, "pct_actors_with_incentives": 0.0,
           "n_relationships": 0}
    pen, _ = PipelineOrchestrator._compute_forecast_confidence_penalty(meta, cov)
    assert pen <= 0.3


def test_penalty_includes_research_budget_exhaustion():
    pen, components = PipelineOrchestrator._compute_forecast_confidence_penalty(
        {"research_budget": {"denials": 3, "degraded": False}}, None)
    assert pen == 0.05
    assert components == {"research_budget": 0.05}


# ── ORCH-1(2): report-health placeholder detection (figure exemption) ───────

def _write_health_fixture(tmp_path, sections):
    """Write forecast.json + numbered section files; return the folder path."""
    import json as _json
    forecast_text = _json.dumps({"scenarios": [
        {
            "name": "A",
            "probability": 0.7,
            "resolution_criteria": "Outcome A is observed.",
        },
        {
            "name": "Other",
            "probability": 0.3,
            "resolution_criteria": "Any other outcome is observed.",
        },
    ]})
    (tmp_path / "forecast.json").write_text(forecast_text, encoding="utf-8")
    (tmp_path / "final_audit.json").write_text(
        _json.dumps({
            "policy_version": 3,
            "read_only": True,
            "markdown_sha256": "fixture",
            "forecast_sha256": hashlib.sha256(forecast_text.encode("utf-8")).hexdigest(),
            "disk_matches_memory": True,
            "hard_issues": [],
            "hard_passed": True,
            "structured_forecast": {"required": True, "present": True, "valid": True},
            "scenario_contract": {"valid": True, "issue_count": 0},
            "publish_gate": {
                "enabled": True,
                "passed": True,
                "hard_issues": [],
                "epistemic_issues": [],
                "hard_passed": True,
            },
        }),
        encoding="utf-8",
    )
    for i, body in enumerate(sections, start=1):
        (tmp_path / f"section_{i:02d}.md").write_text(body, encoding="utf-8")
    return str(tmp_path)


def test_report_health_short_figure_section_is_not_placeholder(monkeypatch, tmp_path):
    from app.services import pipeline_orchestrator as po
    folder = _write_health_fixture(tmp_path, [
        # <200 chars but carries figure markup → exempt from the placeholder rule
        "```mermaid\ngraph TD; A-->B;\n```\n图1：情景分支",
        "![对比图](data:image/png;base64,AAAA)",
        # <200 chars, plain prose, no figure → still a placeholder
        "太短。",
        # the exact report_agent failure template → placeholder
        "（本章节生成失败：LLM 返回空响应，请稍后重试）",
        # long prose that merely *mentions* 本章节/失败 → must NOT be a placeholder
        "本章节回顾了三次谈判失败的原因。" + "分析正文。" * 60,
    ])
    monkeypatch.setattr(po.ReportManager, "_get_report_folder", lambda rid: folder)
    health, issues, meta = po.PipelineOrchestrator._assess_report_health(None, "rid-1")
    assert meta["placeholder_sections"] == 2
    assert meta["sections"] == 5
    assert health == "degraded"  # partial placeholders → degraded, not failed
    assert any("2/5" in i for i in issues)


def test_report_health_surfaces_residual_simulation_mechanics(monkeypatch, tmp_path):
    from app.services import pipeline_orchestrator as po
    folder = _write_health_fixture(tmp_path, ["Analysis body. " * 40])
    forecast = json.loads((tmp_path / "forecast.json").read_text(encoding="utf-8"))
    forecast["quality"] = {
        "lint": {"leakage_flags": 2, "outcome_focus_ok": False}
    }
    forecast_text = json.dumps(forecast)
    (tmp_path / "forecast.json").write_text(forecast_text, encoding="utf-8")
    audit_path = tmp_path / "final_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["forecast_sha256"] = hashlib.sha256(
        forecast_text.encode("utf-8")
    ).hexdigest()
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    monkeypatch.setattr(po.ReportManager, "_get_report_folder", lambda rid: folder)

    health, issues, meta = po.PipelineOrchestrator._assess_report_health(None, "rid-1")

    assert health == "degraded"
    assert any("simulation-mechanics" in issue for issue in issues)
    assert any("simulation-mechanics" in issue for issue in meta["quality_issues"])


def test_report_health_hard_fails_final_publish_integrity_issue(monkeypatch, tmp_path):
    from app.services import pipeline_orchestrator as po

    folder = _write_health_fixture(tmp_path, ["Analysis body. " * 40])
    (tmp_path / "final_audit.json").write_text(json.dumps({
        "policy_version": 3,
        "read_only": True,
        "markdown_sha256": "dirty",
        "disk_matches_memory": True,
        "hard_issues": ["最终 Markdown 含 1 个悬空引用记号"],
        "hard_passed": False,
        "publish_gate": {
            "enabled": True,
            "passed": False,
            "hard_issues": ["最终 Markdown 含 1 个悬空引用记号"],
            "epistemic_issues": ["定量声明引用覆盖率 0.20 < 阈值 0.50"],
            "hard_passed": False,
        },
    }), encoding="utf-8")
    monkeypatch.setattr(po.ReportManager, "_get_report_folder", lambda rid: folder)

    health, issues, meta = po.PipelineOrchestrator._assess_report_health(None, "rid-1")

    assert health == "failed"
    assert any("悬空引用" in issue for issue in issues)
    assert any("覆盖率" in issue for issue in issues)
    assert any("悬空引用" in issue for issue in meta["hard_quality_issues"])


def test_report_health_rejects_stale_final_audit_fingerprint(monkeypatch, tmp_path):
    from app.services import pipeline_orchestrator as po

    folder = _write_health_fixture(tmp_path, ["Analysis body. " * 40])
    report_md = "# Forecast\n\n" + ("Substantive outcome analysis. " * 100)
    (tmp_path / "full_report.md").write_text(report_md, encoding="utf-8")
    audit_path = tmp_path / "final_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["markdown_sha256"] = "0" * 64
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    monkeypatch.setattr(po.ReportManager, "_get_report_folder", lambda rid: folder)

    health, issues, _meta = po.PipelineOrchestrator._assess_report_health(None, "rid-1")

    assert health == "failed"
    assert any("fingerprint" in issue for issue in issues)


def test_report_health_hard_fails_when_final_audit_missing(monkeypatch, tmp_path):
    from app.services import pipeline_orchestrator as po

    folder = _write_health_fixture(tmp_path, ["Analysis body. " * 40])
    (tmp_path / "final_audit.json").unlink()
    monkeypatch.setattr(po.ReportManager, "_get_report_folder", lambda rid: folder)

    health, issues, _meta = po.PipelineOrchestrator._assess_report_health(None, "rid-1")

    assert health == "failed"
    assert any("not audited" in issue for issue in issues)


# ── VIZ-2: charts/datasets 可视化产物通道 specs & 临时产物发现 ──────────────────
# 覆盖 _viz_artifact_specs / _stage_artifact_specs / _discover_partial_artifacts 的
# 纯离线行为：索引锚点登记、开关门控、缺文件降级、原始 png|svg|csv 逐个透出。No disk-writes
# 到 uploads（仅 tmp_path handoff 目录）。

import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import threading  # noqa: E402

from app.services import pipeline_orchestrator as _po  # noqa: E402


def _viz_state(tmp_path):
    return _po.PipelineState(pipeline_id="viz-pipe-1", prompt="x", handoff_dir=str(tmp_path))


def test_viz_specs_present_for_research_and_report(monkeypatch, tmp_path):
    monkeypatch.setattr(_po.Config, "PIPELINE_VIZ_ARTIFACTS", True, raising=False)
    st = _viz_state(tmp_path)
    specs = dict(_po.PipelineOrchestrator._stage_artifact_specs(st, _po.STAGE_RESEARCH))
    assert "charts" in specs and "datasets" in specs
    assert specs["charts"] == os.path.join(str(tmp_path), "charts.json")
    assert specs["datasets"].endswith(os.path.join("data", "datasets.json"))


def test_report_viz_specs_point_to_report_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(_po.Config, "PIPELINE_VIZ_ARTIFACTS", True, raising=False)
    report_dir = tmp_path / "report"
    monkeypatch.setattr(_po.ReportManager, "_get_report_folder",
                        classmethod(lambda cls, rid: str(report_dir)))
    st = _viz_state(tmp_path / "handoff")
    st.report_id = "rid"
    specs = dict(_po.PipelineOrchestrator._stage_artifact_specs(st, _po.STAGE_REPORT))
    assert specs == {"report_viz_manifest": str(report_dir / "viz_manifest.json")}


def test_viz_specs_accept_legacy_nested_chart_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(_po.Config, "PIPELINE_VIZ_ARTIFACTS", True, raising=False)
    legacy = tmp_path / "charts" / "charts.json"
    legacy.parent.mkdir()
    legacy.write_text("[]", encoding="utf-8")
    specs = dict(_po.PipelineOrchestrator._stage_artifact_specs(
        _viz_state(tmp_path), _po.STAGE_RESEARCH))
    assert specs["charts"] == str(legacy)


def test_dynamic_chart_specs_include_static_and_interactive_assets(tmp_path):
    charts = tmp_path / "charts"
    charts.mkdir()
    for name in ("actor.png", "timeline.svg", "actor.html", "ignore.json"):
        (charts / name).write_text("x", encoding="utf-8")
    specs = dict(_po.PipelineOrchestrator._viz_dynamic_artifact_specs(str(tmp_path)))
    assert set(specs) == {"chart_actor.png", "chart_timeline.svg", "chart_actor.html"}


def test_viz_specs_absent_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(_po.Config, "PIPELINE_VIZ_ARTIFACTS", False, raising=False)
    st = _viz_state(tmp_path)
    names = {n for n, _ in _po.PipelineOrchestrator._stage_artifact_specs(st, _po.STAGE_RESEARCH)}
    assert "charts" not in names and "datasets" not in names


def test_viz_absent_files_are_not_discovered(monkeypatch, tmp_path):
    # 旧跑：无 charts/ data/ 目录 → 索引锚点与原始文件都不出现，且不抛错（degrade-safe）。
    monkeypatch.setattr(_po.Config, "PIPELINE_VIZ_ARTIFACTS", True, raising=False)
    st = _viz_state(tmp_path)
    partials = _po.PipelineOrchestrator._discover_partial_artifacts(st, _po.STAGE_RESEARCH)
    for p in partials:
        assert p["name"] not in ("charts", "datasets")
        assert not str(p["name"]).startswith(("chart_", "dataset_"))


def test_viz_present_files_surface_as_partials(monkeypatch, tmp_path):
    monkeypatch.setattr(_po.Config, "PIPELINE_VIZ_ARTIFACTS", True, raising=False)
    (tmp_path / "charts").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "charts" / "fig1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "charts" / "fig1.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "charts" / "charts.json").write_text(
        '[{"title": "t", "caption": "c", "source_data": "data/fig1.csv"}]', encoding="utf-8")
    (tmp_path / "data" / "fig1.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    st = _viz_state(tmp_path)
    # report_id 为空 → section_*.md 扫描分支自然跳过；不触碰 ReportManager。
    names = {p["name"] for p in _po.PipelineOrchestrator._discover_partial_artifacts(st, _po.STAGE_RESEARCH)}
    assert "charts" in names                # charts.json 经 specs 枚举登记为索引锚点
    assert "chart_fig1.png" in names        # 原始 png 经目录扫描逐个透出
    assert "chart_fig1.html" in names       # 交互式 HTML 同样可深链
    assert "dataset_fig1.csv" in names      # 原始 csv 经目录扫描逐个透出


def test_report_partial_scan_uses_report_owned_charts(monkeypatch, tmp_path):
    monkeypatch.setattr(_po.Config, "PIPELINE_VIZ_ARTIFACTS", True, raising=False)
    handoff = tmp_path / "handoff"
    report_dir = tmp_path / "report"
    (report_dir / "charts").mkdir(parents=True)
    (report_dir / "charts" / "timeline.html").write_text("<html></html>", encoding="utf-8")
    (report_dir / "viz_manifest.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(_po.ReportManager, "_get_report_folder",
                        classmethod(lambda cls, rid: str(report_dir)))
    st = _viz_state(handoff)
    st.report_id = "rid"

    names = {p["name"] for p in _po.PipelineOrchestrator._discover_partial_artifacts(
        st, _po.STAGE_REPORT)}

    assert "report_viz_manifest" in names
    assert "report_chart_timeline.html" in names


def test_research_completion_registers_chart_assets_without_partial_suffix(
        monkeypatch, tmp_path):
    monkeypatch.setattr(_po.Config, "PIPELINE_VIZ_ARTIFACTS", True, raising=False)
    monkeypatch.setattr(_po.Config, "PIPELINE_VALIDATE_ARTIFACTS", False, raising=False)
    charts = tmp_path / "charts"
    charts.mkdir()
    (tmp_path / "charts.json").write_text("[]", encoding="utf-8")
    (charts / "actor.png").write_bytes(b"png")
    (charts / "actor.html").write_text("<html></html>", encoding="utf-8")
    st = _viz_state(tmp_path)
    st.artifacts["chart_actor.png_partial"] = str(charts / "actor.png")
    st.artifacts["chart_actor.html_partial"] = str(charts / "actor.html")
    orch = _po.PipelineOrchestrator.__new__(_po.PipelineOrchestrator)

    orch._record_stage_artifacts(st, _po.STAGE_RESEARCH)

    assert st.artifacts["chart_actor.png"] == str(charts / "actor.png")
    assert st.artifacts["chart_actor.html"] == str(charts / "actor.html")
    assert "chart_actor.png_partial" not in st.artifacts
    assert "chart_actor.html_partial" not in st.artifacts


def test_report_viz_reuse_validation_checks_every_declared_asset(tmp_path):
    report_dir = tmp_path / "report"
    charts = report_dir / "charts"
    charts.mkdir(parents=True)
    (charts / "timeline.html").write_text("<html></html>", encoding="utf-8")
    (charts / "timeline.png").write_bytes(b"png")
    (report_dir / "viz_manifest.json").write_text(json.dumps({
        "schema_version": 2,
        "items": [{
            "id": "timeline",
            "type": "html",
            "path": "charts/timeline.html",
            "png_path": "charts/timeline.png",
        }],
        "skipped": [],
    }), encoding="utf-8")

    assert _po.PipelineOrchestrator._validate_report_viz_references(str(report_dir)) is True
    (charts / "timeline.png").unlink()
    assert _po.PipelineOrchestrator._validate_report_viz_references(str(report_dir)) is False


def test_report_viz_reuse_validation_rejects_symlink(tmp_path):
    report_dir = tmp_path / "report"
    charts = report_dir / "charts"
    charts.mkdir(parents=True)
    outside = tmp_path / "outside.html"
    outside.write_text("<html></html>", encoding="utf-8")
    os.symlink(outside, charts / "timeline.html")
    (report_dir / "viz_manifest.json").write_text(json.dumps({
        "schema_version": 2,
        "items": [{"type": "html", "path": "charts/timeline.html"}],
    }), encoding="utf-8")

    assert _po.PipelineOrchestrator._validate_report_viz_references(str(report_dir)) is False


def test_new_report_attempt_clears_formal_partial_and_integrity_rows(monkeypatch, tmp_path):
    st = _viz_state(tmp_path)
    st.artifacts = {
        "report_viz_manifest": "/old/viz_manifest.json",
        "report_chart_timeline.html": "/old/charts/timeline.html",
        "section_01_partial": "/old/section_01.md",
        "report": "/handoff/research_report.md",
    }
    written = {}
    monkeypatch.setattr(
        _po.PipelineManager,
        "load_artifact_manifest",
        classmethod(lambda cls, pid: {
            "report_viz_manifest": {"path": "/old/viz_manifest.json"},
            "report_chart_timeline.html": {"path": "/old/charts/timeline.html"},
            "report": {"path": "/handoff/research_report.md"},
        }),
    )
    monkeypatch.setattr(
        _po.PipelineManager,
        "write_artifact_manifest",
        classmethod(lambda cls, pid, value: written.update(value)),
    )

    _po.PipelineOrchestrator._clear_report_attempt_artifacts(st)

    assert st.artifacts == {"report": "/handoff/research_report.md"}
    assert written == {"report": {"path": "/handoff/research_report.md"}}


def test_run_reuse_rejects_manifest_artifact_from_previous_simulation(
        monkeypatch, tmp_path):
    """A valid old run must not satisfy the manifest contract for a new PREPARE attempt."""
    run_root = tmp_path / "run-state"
    old_summary = run_root / "sim_old" / "run_summary.json"
    old_summary.parent.mkdir(parents=True)
    old_summary.write_text(json.dumps({
        "simulation_id": "sim_old",
        "rounds_executed": 19,
        "simulation_health": "ok",
    }), encoding="utf-8")
    entry = _po._manifest_entry_for("run_summary", str(old_summary), _po.STAGE_RUN)
    monkeypatch.setattr(_po.SimulationRunner, "RUN_STATE_DIR", str(run_root), raising=False)
    monkeypatch.setattr(
        _po.PipelineManager,
        "load_artifact_manifest",
        classmethod(lambda cls, pid: {"run_summary": entry}),
    )
    st = _po.PipelineState(
        pipeline_id="pipe_identity", prompt="q", mode="full", status="running")
    st.simulation_id = "sim_new"

    assert _po.PipelineOrchestrator()._validate_reuse(st, _po.STAGE_RUN) is False


def test_reuse_validation_exception_fails_closed(monkeypatch):
    orch = _po.PipelineOrchestrator()
    monkeypatch.setattr(
        orch,
        "_validate_reuse",
        lambda state, stage: (_ for _ in ()).throw(OSError("manifest read race")),
    )
    st = _po.PipelineState(
        pipeline_id="pipe_fail_closed", prompt="q", mode="full", status="running")

    assert orch._reuse_ok(st, _po.STAGE_RUN) is False


def test_prepare_reuse_accepts_the_recorded_persona_alternative(monkeypatch, tmp_path):
    """Duplicate persona candidates are one logical artifact, not two required files."""
    sim_root = tmp_path / "simulations"
    reddit_profiles = sim_root / "sim_one" / "reddit_profiles.json"
    reddit_profiles.parent.mkdir(parents=True)
    reddit_profiles.write_text('[{"name": "agent"}]', encoding="utf-8")
    entry = _po._manifest_entry_for("personas", str(reddit_profiles), _po.STAGE_PREPARE)
    monkeypatch.setattr(
        _po.Config, "OASIS_SIMULATION_DATA_DIR", str(sim_root), raising=False)
    monkeypatch.setattr(
        _po.PipelineManager,
        "load_artifact_manifest",
        classmethod(lambda cls, pid: {"personas": entry}),
    )
    st = _po.PipelineState(
        pipeline_id="pipe_persona", prompt="q", mode="full", status="running")
    st.simulation_id = "sim_one"

    assert _po.PipelineOrchestrator()._validate_reuse(st, _po.STAGE_PREPARE) is True


def test_run_reuse_requires_the_current_simulation_to_be_completed(monkeypatch, tmp_path):
    run_root = tmp_path / "run-state"
    summary = run_root / "sim_current" / "run_summary.json"
    summary.parent.mkdir(parents=True)
    summary.write_text(json.dumps({
        "simulation_id": "sim_current",
        "rounds_executed": 19,
        "simulation_health": "ok",
    }), encoding="utf-8")
    monkeypatch.setattr(_po.SimulationRunner, "RUN_STATE_DIR", str(run_root), raising=False)
    st = _po.PipelineState(
        pipeline_id="pipe_status", prompt="q", mode="full", status="running")
    st.simulation_id = "sim_current"

    ready = SimpleNamespace(simulation_id="sim_current", status=_po.SimulationStatus.READY)
    completed = SimpleNamespace(
        simulation_id="sim_current", status=_po.SimulationStatus.COMPLETED)
    wrong = SimpleNamespace(simulation_id="sim_previous", status=_po.SimulationStatus.COMPLETED)

    assert _po.PipelineOrchestrator._run_reuse_ready(st, ready) is False
    assert _po.PipelineOrchestrator._run_reuse_ready(st, wrong) is False
    assert _po.PipelineOrchestrator._run_reuse_ready(st, completed) is True


def test_reused_run_summary_is_registered_without_rewriting(monkeypatch, tmp_path):
    run_root = tmp_path / "run-state"
    summary = run_root / "sim_current" / "run_summary.json"
    summary.parent.mkdir(parents=True)
    original = b'{"simulation_id":"sim_current","rounds_executed":19}\n'
    summary.write_bytes(original)
    monkeypatch.setattr(_po.SimulationRunner, "RUN_STATE_DIR", str(run_root), raising=False)
    writes = []
    monkeypatch.setattr(
        _po.SimulationRunner,
        "write_run_summary",
        classmethod(lambda cls, *args, **kwargs: writes.append((args, kwargs))),
    )
    monkeypatch.setattr(
        _po.PipelineManager, "save", classmethod(lambda cls, state: None))
    monkeypatch.setattr(
        _po.PipelineManager, "load_artifact_manifest", classmethod(lambda cls, pid: {}))
    recorded = {}
    monkeypatch.setattr(
        _po.PipelineManager,
        "write_artifact_manifest",
        classmethod(lambda cls, pid, value: recorded.update(value)),
    )
    st = _po.PipelineState(
        pipeline_id="pipe_preserve", prompt="q", mode="full", status="running")
    st.simulation_id = "sim_current"

    _po.PipelineOrchestrator()._publish_run_summary(
        st, "sim_current", communities=None, regenerate=False)

    assert writes == []
    assert summary.read_bytes() == original
    assert st.artifacts["run_summary"] == str(summary)
    assert recorded["run_summary"]["path"] == str(summary)


def test_missing_legacy_run_summary_is_backfilled_once(monkeypatch, tmp_path):
    run_root = tmp_path / "run-state"
    summary = run_root / "sim_legacy" / "run_summary.json"
    monkeypatch.setattr(_po.SimulationRunner, "RUN_STATE_DIR", str(run_root), raising=False)
    writes = []

    def write_summary(cls, simulation_id, communities=None):
        writes.append(simulation_id)
        summary.parent.mkdir(parents=True, exist_ok=True)
        summary.write_text(json.dumps({
            "simulation_id": simulation_id,
            "rounds_executed": 7,
            "simulation_health": "ok",
        }), encoding="utf-8")

    monkeypatch.setattr(
        _po.SimulationRunner, "write_run_summary", classmethod(write_summary))
    monkeypatch.setattr(
        _po.PipelineManager, "save", classmethod(lambda cls, state: None))
    manifest = {}
    monkeypatch.setattr(
        _po.PipelineManager,
        "load_artifact_manifest",
        classmethod(lambda cls, pid: dict(manifest)),
    )
    monkeypatch.setattr(
        _po.PipelineManager,
        "write_artifact_manifest",
        classmethod(lambda cls, pid, value: manifest.update(value)),
    )
    st = _po.PipelineState(
        pipeline_id="pipe_legacy", prompt="q", mode="full", status="running")
    st.simulation_id = "sim_legacy"
    completed = SimpleNamespace(
        simulation_id="sim_legacy", status=_po.SimulationStatus.COMPLETED)

    assert _po.PipelineOrchestrator._run_reuse_ready(st, completed) is True
    orch = _po.PipelineOrchestrator()
    assert orch._publish_run_summary(
        st, "sim_legacy", communities=None, regenerate=False) is True
    assert orch._publish_run_summary(
        st, "sim_legacy", communities=None, regenerate=False) is True

    assert writes == ["sim_legacy"]
    assert st.artifacts["run_summary"] == str(summary)
    assert manifest["run_summary"]["path"] == str(summary)


def _exercise_prepare_run_resume(
        monkeypatch, tmp_path, *, rebuild_prepare, corrupt_run=False,
        corrupt_prepare_seal=False, report_simulation_id=None, lineage_flags=True,
        report_preflight_failures=0, real_run_manifest=False, extra_options=None,
        prior_run_manifest=None, report_interrupt=None):
    """Run the real orchestrator state machine with every external service faked.

    The persisted report was generated for ``report_simulation_id`` (default:
    the old simulation).  A regenerated report is recorded in
    ``report_generations`` (the simulation id it was generated for) instead
    of running the real ReportAgent.  ``lineage_flags`` sets both INFRA-7
    knobs (RUN_SHAPE_PIN, RESUME_LINEAGE_GUARDS).  The first
    ``report_preflight_failures`` REPORT preflight probes raise (a provider
    outage).  ``real_run_manifest`` keeps the real run.json writers, and
    ``run_manifest_at_start`` then holds run.json's simulation block as RUN
    starts each simulation; ``prior_run_manifest`` is an earlier attempt's
    run.json.  ``report_interrupt`` ends the first report generation early,
    once: ``"cancel_before_meta"`` cancels the pipeline right after the new
    report_id is minted (the report never reaches disk);
    ``"cancel_after_publish"`` publishes the report and then cancels from its
    final progress callback; ``"complete_stage_crash"`` publishes it and
    crashes in ``_complete_stage(REPORT)``.  With it set, the report store is
    keyed by id and the simulation lookup returns the newest report of the
    simulation.  The returned ``pid`` can be resumed for a second attempt while
    the fakes stay installed.
    """
    pipeline_root = tmp_path / "pipelines"
    simulation_root = tmp_path / "simulations"
    report_root = tmp_path / "reports" / "report_existing"
    report_root.mkdir(parents=True)
    monkeypatch.setattr(_po.Config, "PIPELINE_DATA_DIR", str(pipeline_root), raising=False)
    monkeypatch.setattr(
        _po.Config, "OASIS_SIMULATION_DATA_DIR", str(simulation_root), raising=False)
    monkeypatch.setattr(_po.SimulationRunner, "RUN_STATE_DIR", str(simulation_root), raising=False)
    for name, value in {
        "REPORT_LINT": False,
        "CAST_RECONCILE": False,
        "EMBED_WARM_AT_RESEARCH": False,
        "PIPELINE_VIZ_ARTIFACTS": False,
        "GRAPH_BUILD_COMMUNITIES": False,
        "GRAPH_RESOLVE_ENTITIES": False,
        "GRAPH_PRUNE_ENABLED": False,
        "SIM_GRAPH_FEEDBACK": False,
        "PIPELINE_RUN_STALL_S": 0,
        "REPORT_LLM_PREFLIGHT": False,
        "REPORT_TELEMETRY_APPENDIX": False,
        "SIM_TEMPORAL_MODE": "calendar",
        "SIM_DECISION_CHANNEL": True,
        "N_FORECAST_SEEDS": 1,
        "RUN_SHAPE_PIN": lineage_flags,
        "RESUME_LINEAGE_GUARDS": lineage_flags,
    }.items():
        monkeypatch.setattr(_po.Config, name, value, raising=False)
    if report_preflight_failures:
        import app.utils.llm_client as llm_client_module

        preflight = {"calls": 0}

        class FlakyPreflightClient:
            def chat(self, messages, **kwargs):
                preflight["calls"] += 1
                if preflight["calls"] <= report_preflight_failures:
                    raise RuntimeError("provider outage")
                return "pong"

        monkeypatch.setattr(_po.Config, "REPORT_LLM_PREFLIGHT", True, raising=False)
        monkeypatch.setattr(llm_client_module, "LLMClient", FlakyPreflightClient)

    pid = "pipe_state_machine"
    _po.PipelineManager.ensure_dirs(pid)
    handoff = _po.PipelineManager.handoff_dir(pid)
    os.makedirs(handoff, exist_ok=True)
    with open(os.path.join(handoff, "research_report.md"), "w", encoding="utf-8") as f:
        f.write("Evidence-backed EV research. " * 30)
    with open(os.path.join(handoff, "actors.json"), "w", encoding="utf-8") as f:
        json.dump({
            "as_of_date": "2026-07-12",
            "actors": [{"name": "EV OEM", "type": "Company"}],
            "relationships": [],
        }, f)
    with open(os.path.join(handoff, "sources.json"), "w", encoding="utf-8") as f:
        json.dump([], f)

    old_id = "sim_old"
    new_id = "sim_new"
    old_dir = simulation_root / old_id
    old_dir.mkdir(parents=True)
    old_config = old_dir / "simulation_config.json"
    old_config_payload = {
        "temporal_config": {
            "mode": "calendar",
            "unit": "year",
            "n_rounds": 9,
            "horizon_date": "2035-12-31",
            "horizon_source": "bare_year",
            "horizon_defaulted": False,
        },
        "world_state_seed": {
            "as_of_date": "2026-07-12",
            "horizon_date": "2035-12-31",
        },
    }
    if corrupt_run:
        # Model an already-overlaid PREPARE artifact whose RUN summary later
        # becomes invalid. Reapplying the same overlay must not duplicate it.
        old_config_payload["event_config"] = {
            "scheduled_events": [{
                "round": 0,
                "content": "Policy shock",
                "date": None,
                "poster_agent_id": 0,
                "poster_name": "",
                "is_scenario_injection": True,
            }],
        }
    old_config.write_text(
        json.dumps(old_config_payload, indent=2), encoding="utf-8"
    )
    (old_dir / "twitter_profiles.csv").write_text("name\nEV OEM\n", encoding="utf-8")
    old_summary = old_dir / "run_summary.json"
    original_summary = json.dumps({
        "simulation_id": old_id,
        "rounds_executed": 9,
        "simulation_health": "ok",
    }, indent=2).encode()
    old_summary.write_bytes(original_summary)
    from app.services.simulation_manager import (
        build_simulation_config_seal,
        validate_simulation_config_seal,
    )
    old_config_sha, old_config_manifest_sha = build_simulation_config_seal(
        str(old_dir),
        simulation_id=old_id,
        actor_cast_manifest_sha256=None,
        actor_context_manifest_sha256=None,
        actor_role_manifest_sha256={},
    )
    old_config_manifest = old_dir / "simulation_config_manifest.json"
    old_config_manifest_bytes = old_config_manifest.read_bytes()
    if corrupt_prepare_seal:
        stale_manifest = json.loads(old_config_manifest.read_text(encoding="utf-8"))
        stale_manifest["simulation_config_sha256"] = "0" * 64
        old_config_manifest.write_text(
            json.dumps(stale_manifest, indent=2), encoding="utf-8"
        )
    manifest = {
        "initial_posts": _po._manifest_entry_for(
            "initial_posts", str(old_config), _po.STAGE_PREPARE),
        "personas": _po._manifest_entry_for(
            "personas", str(old_dir / "twitter_profiles.csv"), _po.STAGE_PREPARE),
        "run_summary": _po._manifest_entry_for(
            "run_summary", str(old_summary), _po.STAGE_RUN),
    }
    _po.PipelineManager.write_artifact_manifest(pid, manifest)
    if rebuild_prepare:
        # Same path, different bytes: force the production manifest guard to
        # create a new PREPARE attempt while the old RUN bit remains completed.
        old_config.write_text(old_config.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    if corrupt_run:
        old_summary.write_bytes(original_summary + b"\n")

    states = {
        old_id: SimpleNamespace(
            simulation_id=old_id,
            project_id="proj",
            graph_id="graph",
            status=_po.SimulationStatus.COMPLETED,
            actor_cast_manifest_sha256=None,
            actor_context_manifest_sha256=None,
            actor_role_manifest_sha256={},
            actor_context_count=0,
            simulation_config_sha256=old_config_sha,
            simulation_config_manifest_sha256=old_config_manifest_sha,
        ),
    }
    manager_calls = {"create": 0, "prepare": 0, "reseal": 0, "validate": 0}

    class FakeSimulationManager:
        def get_simulation(self, simulation_id):
            return states.get(simulation_id)

        def create_simulation(self, project_id, graph_id, **kwargs):
            manager_calls["create"] += 1
            states[new_id] = SimpleNamespace(
                simulation_id=new_id,
                project_id=project_id,
                graph_id=graph_id,
                status=_po.SimulationStatus.CREATED,
                actor_cast_manifest_sha256=None,
                actor_context_manifest_sha256=None,
                actor_role_manifest_sha256={},
                actor_context_count=0,
                simulation_config_sha256=None,
                simulation_config_manifest_sha256=None,
            )
            return states[new_id]

        def prepare_simulation(self, simulation_id, **kwargs):
            manager_calls["prepare"] += 1
            sim_dir = simulation_root / simulation_id
            sim_dir.mkdir(parents=True, exist_ok=True)
            (sim_dir / "simulation_config.json").write_text(json.dumps({
                "temporal_config": {
                    "mode": "calendar",
                    "unit": "year",
                    "n_rounds": 9,
                    "horizon_date": "2035-12-31",
                    "horizon_source": "bare_year",
                    "horizon_defaulted": False,
                },
            }, indent=2), encoding="utf-8")
            (sim_dir / "twitter_profiles.csv").write_text(
                "name\nEV OEM\n", encoding="utf-8")
            config_sha, config_manifest_sha = build_simulation_config_seal(
                str(sim_dir),
                simulation_id=simulation_id,
                actor_cast_manifest_sha256=None,
                actor_context_manifest_sha256=None,
                actor_role_manifest_sha256={},
            )
            states[simulation_id].simulation_config_sha256 = config_sha
            states[simulation_id].simulation_config_manifest_sha256 = (
                config_manifest_sha
            )
            states[simulation_id].status = _po.SimulationStatus.READY
            return states[simulation_id]

        def reseal_simulation_config(self, simulation_id):
            manager_calls["reseal"] += 1
            sim_dir = simulation_root / simulation_id
            state = states[simulation_id]
            config_sha, manifest_sha = build_simulation_config_seal(
                str(sim_dir),
                simulation_id=simulation_id,
                actor_cast_manifest_sha256=state.actor_cast_manifest_sha256,
                actor_context_manifest_sha256=state.actor_context_manifest_sha256,
                actor_role_manifest_sha256=state.actor_role_manifest_sha256,
            )
            state.simulation_config_sha256 = config_sha
            state.simulation_config_manifest_sha256 = manifest_sha
            validate_simulation_config_seal(
                str(sim_dir),
                expected_manifest_sha256=manifest_sha,
                expected_config_sha256=config_sha,
                expected_simulation_id=simulation_id,
                require=True,
            )
            self._save_simulation_state(state)
            return state

        def validate_prepared_simulation_config(self, simulation_id):
            manager_calls["validate"] += 1
            state = states[simulation_id]
            return validate_simulation_config_seal(
                str(simulation_root / simulation_id),
                expected_manifest_sha256=(
                    state.simulation_config_manifest_sha256
                ),
                expected_config_sha256=state.simulation_config_sha256,
                expected_simulation_id=simulation_id,
                require=bool(
                    state.actor_context_count
                    or state.simulation_config_manifest_sha256
                    or state.simulation_config_sha256
                ),
            )

        def _save_simulation_state(self, state):
            states[state.simulation_id] = state
            sim_dir = simulation_root / state.simulation_id
            sim_dir.mkdir(parents=True, exist_ok=True)
            (sim_dir / "state.json").write_text(json.dumps({
                "simulation_id": state.simulation_id,
                "actor_context_count": state.actor_context_count,
                "simulation_config_sha256": state.simulation_config_sha256,
                "simulation_config_manifest_sha256": (
                    state.simulation_config_manifest_sha256
                ),
            }, indent=2), encoding="utf-8")

    fake_manager = FakeSimulationManager()
    monkeypatch.setattr(_po, "SimulationManager", lambda: fake_manager)
    project = SimpleNamespace(
        project_id="proj",
        name="EV project",
        ontology={"entity_types": [{"name": "Company"}]},
        graph_id="graph",
    )
    monkeypatch.setattr(
        _po.ProjectManager, "get_project", classmethod(lambda cls, project_id: project))

    import app.services.zep_entity_reader as zep_reader

    class FakeEntityReader:
        def filter_defined_entities(self, graph_id, enrich_with_edges=False):
            return SimpleNamespace(entities=[{"uuid": "one"}])

    monkeypatch.setattr(zep_reader, "ZepEntityReader", FakeEntityReader)
    monkeypatch.setattr(
        _po,
        "GraphBuilderService",
        lambda **kwargs: SimpleNamespace(set_ontology=lambda graph_id, ontology: None),
    )

    start_calls = []
    summary_writes = []
    run_manifest_at_start = []

    def start_simulation(cls, simulation_id, **kwargs):
        start_calls.append(simulation_id)
        if real_run_manifest:
            with open(_po.PipelineManager.manifest_path(pid), encoding="utf-8") as fh:
                run_manifest_at_start.append(json.load(fh)["resolved"]["simulation"])
        states[simulation_id].status = _po.SimulationStatus.RUNNING

    def get_run_state(cls, simulation_id):
        # DEFECT-2: a real COMPLETED runner state always carries the enabled +
        # simulation_end completion flags (the monitor only publishes COMPLETED
        # after every enabled platform emitted its marker). The completion-
        # evidence gate at the RUN boundary now demands that authority, so the
        # fake must model it faithfully.
        return SimpleNamespace(
            total_rounds=9,
            current_round=9,
            runner_status=_po.RunnerStatus.COMPLETED,
            twitter_enabled=True,
            reddit_enabled=True,
            twitter_completed=True,
            reddit_completed=True,
        )

    def write_summary(cls, simulation_id, communities=None):
        summary_writes.append(simulation_id)
        path = simulation_root / simulation_id / "run_summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "simulation_id": simulation_id,
            "rounds_executed": 9,
            "simulation_health": "ok",
        }), encoding="utf-8")

    monkeypatch.setattr(
        _po.SimulationRunner, "start_simulation", classmethod(start_simulation))
    monkeypatch.setattr(
        _po.SimulationRunner, "get_run_state", classmethod(get_run_state))
    monkeypatch.setattr(
        _po.SimulationRunner, "write_run_summary", classmethod(write_summary))

    existing_report = SimpleNamespace(
        report_id="report_existing", status=_po.ReportStatus.COMPLETED,
        simulation_id=report_simulation_id or old_id)
    published_reports = {"report_existing": existing_report}
    if report_interrupt is None:
        def get_report(cls, report_id):
            return existing_report

        def get_report_by_simulation(cls, simulation_id):
            return None
    else:
        def get_report(cls, report_id):
            return published_reports.get(report_id)

        def get_report_by_simulation(cls, simulation_id):
            matches = [report for report in published_reports.values()
                       if report.simulation_id == simulation_id]
            return matches[-1] if matches else None
    monkeypatch.setattr(_po.ReportManager, "get_report", classmethod(get_report))
    monkeypatch.setattr(
        _po.ReportManager, "get_report_by_simulation", classmethod(get_report_by_simulation))
    monkeypatch.setattr(
        _po.ReportManager,
        "_get_report_folder",
        classmethod(lambda cls, report_id: str(report_root)),
    )

    report_generations = []
    interrupts = {"pending": report_interrupt}

    def take_interrupt(kind):
        if interrupts["pending"] != kind:
            return False
        interrupts["pending"] = None
        return True

    def cancel_pipeline():
        event = threading.Event()
        event.set()
        monkeypatch.setitem(_po.PipelineOrchestrator._cancel_events, pid, event)

    def generate_stage_report(self, state, agent, simulation_id, *, report_id,
                              progress_callback):
        report_generations.append(simulation_id)
        report = SimpleNamespace(report_id=report_id, status=_po.ReportStatus.COMPLETED,
                                 simulation_id=simulation_id)
        published_reports[report_id] = report
        if take_interrupt("cancel_after_publish"):
            # ReportAgent.generate_report saves the completed report, then calls
            # progress_callback('completed', 100, ...): the stage updater raises
            # PipelineCancelled there on a user cancel.
            cancel_pipeline()
            progress_callback("completed", 100, "report generated")
        return report

    real_clear_report_attempt = _po.PipelineOrchestrator._clear_report_attempt_artifacts

    def clear_report_attempt(state):
        real_clear_report_attempt(state)
        if take_interrupt("cancel_before_meta"):
            cancel_pipeline()  # the next stage update, right after the mint, raises

    # Keep this transition test focused on durable stage contracts, not provider,
    # telemetry, or final-report quality systems.
    monkeypatch.setattr(_po, "_finalize_research_contract", lambda *args, **kwargs: None)
    stubs = {
        "_start_heartbeat": lambda self, state: None,
        "_init_telemetry_flush": lambda self, state: None,
        "_write_run_manifest": lambda self, state: None,
        "_update_manifest": lambda self, state, stage, **kwargs: None,
        "_record_research_telemetry": lambda self, state, value: None,
        "_maybe_warm_embedder": lambda self, state, actors: None,
        "_surface_research_quality": lambda self, state, handoff_dir: {},
        "_surface_forecast_confidence_penalty": lambda self, state, handoff_dir: None,
        "_flush_run_telemetry": lambda self, state, **kwargs: None,
        "_maybe_run_seed_ensemble": lambda self, *args, **kwargs: None,
        "_enforce_pipeline_health": lambda self, state: None,
        "_assess_report_health": lambda self, report_id: ("ok", [], {}),
        "_generate_stage_report": generate_stage_report,
    }
    if real_run_manifest:
        monkeypatch.setattr(_po, "_repo_git_sha", lambda: "gitsha")
        monkeypatch.setattr(_po, "_deerflow_ref", lambda: None)
        del stubs["_write_run_manifest"], stubs["_update_manifest"]
    for name, replacement in stubs.items():
        monkeypatch.setattr(_po.PipelineOrchestrator, name, replacement)
    monkeypatch.setattr(_po.PipelineOrchestrator, "_clear_report_attempt_artifacts",
                        staticmethod(clear_report_attempt))
    real_complete_stage = _po.PipelineOrchestrator._complete_stage

    def complete_stage(self, state, stage, message="完成", *, reused=False):
        if stage == _po.STAGE_REPORT and not reused and take_interrupt("complete_stage_crash"):
            raise RuntimeError("backend restarted before the REPORT stage completed")
        return real_complete_stage(self, state, stage, message, reused=reused)

    monkeypatch.setattr(_po.PipelineOrchestrator, "_complete_stage", complete_stage)

    class FakeReportAgent(_po.ReportAgent):
        # Keeps the class-level helpers (the reuse-path ledger repair calls
        # them) while skipping the real agent's service construction.
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(_po, "ReportAgent", FakeReportAgent)
    monkeypatch.setattr(
        _po.ReportManager, "save_report", classmethod(lambda cls, report: None))

    state = _po.PipelineState(
        pipeline_id=pid,
        prompt="Forecast EV development through 2035",
        mode="full",
        status="running",
    )
    state.handoff_dir = handoff
    state.project_id = "proj"
    state.graph_id = "graph"
    state.simulation_id = old_id
    state.report_id = "report_existing"
    state.options["research_language"] = "English"
    state.options.update(extra_options or {})
    if prior_run_manifest is not None:
        with open(_po.PipelineManager.manifest_path(pid), "w", encoding="utf-8") as fh:
            json.dump(prior_run_manifest, fh)
    if corrupt_run:
        state.options["scenario_overlay"] = {
            "injected_events": [{"content": "Policy shock", "round": 0}],
        }
    state.stages = {
        name: _po.StageState(name=name, status="completed", progress=100)
        for name in (
            _po.STAGE_RESEARCH,
            _po.STAGE_ONTOLOGY,
            _po.STAGE_GRAPH,
            _po.STAGE_PREPARE,
            _po.STAGE_RUN,
            _po.STAGE_REPORT,
        )
    }

    _po.PipelineOrchestrator._run(state)
    return SimpleNamespace(
        pid=pid,
        state=state,
        old_id=old_id,
        new_id=new_id,
        simulation_root=simulation_root,
        original_summary=original_summary,
        start_calls=start_calls,
        summary_writes=summary_writes,
        manager_calls=manager_calls,
        report_generations=report_generations,
        run_manifest_at_start=run_manifest_at_start,
        manifest=_po.PipelineManager.load_artifact_manifest(pid),
        old_config_sha=old_config_sha,
        old_config_manifest_sha=old_config_manifest_sha,
        old_config_manifest_bytes=old_config_manifest_bytes,
    )


def _assert_legacy_report_reuse(result):
    """INFRA-7 flags off: the persisted report is reused whatever changed upstream."""
    assert result.report_generations == []
    assert result.state.report_id == "report_existing"
    for key in ("stage_notes", "lineage_invalidated", "stage_reuse_v1"):
        assert key not in result.state.options


@pytest.mark.parametrize("lineage_flags", [True, False])
def test_prepare_rebuild_invalidates_and_executes_run_end_to_end(
        monkeypatch, tmp_path, lineage_flags):
    result = _exercise_prepare_run_resume(
        monkeypatch, tmp_path, rebuild_prepare=True, lineage_flags=lineage_flags)

    assert result.state.status == "completed"
    assert result.state.simulation_id == result.new_id
    assert result.manager_calls == {
        "create": 1, "prepare": 1, "reseal": 1, "validate": 0,
    }
    assert result.start_calls == [result.new_id]
    assert result.summary_writes == [result.new_id]
    config_path = result.simulation_root / result.new_id / "simulation_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["world_state_seed"]["horizon_date"] == "2035-12-31"
    entry = result.manifest["initial_posts"]
    assert os.path.realpath(entry["path"]) == os.path.realpath(config_path)
    assert entry["sha256"] == _po._sha256_file(str(config_path))
    prepared_state = json.loads(
        (result.simulation_root / result.new_id / "state.json").read_text(
            encoding="utf-8"
        )
    )
    assert prepared_state["simulation_config_sha256"] == (
        _po._sha256_file(str(config_path))
    )
    from scripts.run_parallel_simulation import validate_direct_child_config_seal
    child_manifest = validate_direct_child_config_seal(
        str(config_path), prepared_state["simulation_config_manifest_sha256"]
    )
    assert child_manifest["manifest_sha256"] == (
        prepared_state["simulation_config_manifest_sha256"]
    )
    assert result.manifest["run_summary"]["path"].endswith(
        f"{result.new_id}/run_summary.json")
    assert result.state.stages[_po.STAGE_RUN].message == "模拟完成"
    if not lineage_flags:
        _assert_legacy_report_reuse(result)
        return
    # INFRA-7: the old report was written for the replaced simulation.
    assert result.report_generations == [result.new_id]
    assert result.state.report_id != "report_existing"
    assert result.state.options["stage_notes"][_po.STAGE_REPORT] == [
        "reuse_refused: simulation_id_mismatch"]
    # Every stale stage was rebuilt, so nothing stays invalidated.
    assert "lineage_invalidated" not in result.state.options


@pytest.mark.parametrize("lineage_flags", [True, False])
def test_prepare_and_run_reuse_is_read_only_end_to_end(monkeypatch, tmp_path, lineage_flags):
    result = _exercise_prepare_run_resume(
        monkeypatch, tmp_path, rebuild_prepare=False, lineage_flags=lineage_flags)

    assert result.state.status == "completed"
    assert result.state.simulation_id == result.old_id
    assert result.manager_calls == {
        "create": 0, "prepare": 0, "reseal": 0, "validate": 1,
    }
    assert result.start_calls == []
    assert result.summary_writes == []
    summary = result.simulation_root / result.old_id / "run_summary.json"
    assert summary.read_bytes() == result.original_summary
    config_path = result.simulation_root / result.old_id / "simulation_config.json"
    assert _po._sha256_file(str(config_path)) == result.old_config_sha
    config_manifest = (
        result.simulation_root / result.old_id / "simulation_config_manifest.json"
    )
    assert config_manifest.read_bytes() == result.old_config_manifest_bytes
    assert _po._sha256_file(str(config_manifest)) == result.old_config_manifest_sha
    assert result.state.stages[_po.STAGE_RUN].message == "模拟已恢复"
    if not lineage_flags:
        _assert_legacy_report_reuse(result)
        return
    assert result.report_generations == []
    assert result.state.report_id == "report_existing"
    assert "stage_notes" not in result.state.options
    assert "lineage_invalidated" not in result.state.options


@pytest.mark.parametrize("lineage_flags", [True, False])
def test_invalid_run_manifest_applies_overlay_before_rerun(monkeypatch, tmp_path, lineage_flags):
    result = _exercise_prepare_run_resume(
        monkeypatch, tmp_path, rebuild_prepare=False, corrupt_run=True,
        lineage_flags=lineage_flags)

    assert result.state.status == "completed"
    assert result.state.simulation_id == result.old_id
    assert result.manager_calls == {
        "create": 0, "prepare": 0, "reseal": 1, "validate": 1,
    }
    assert result.start_calls == [result.old_id]
    assert result.summary_writes == [result.old_id]
    config_path = result.simulation_root / result.old_id / "simulation_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    scenario_events = config["event_config"]["scheduled_events"]
    assert len(scenario_events) == 1
    assert scenario_events[0]["content"] == "Policy shock"
    assert result.state.stages[_po.STAGE_RUN].message == "模拟完成"
    if not lineage_flags:
        _assert_legacy_report_reuse(result)
        return
    # INFRA-7: RUN re-executed this attempt, so the old report is stale.
    assert result.report_generations == [result.old_id]
    assert result.state.options["stage_notes"][_po.STAGE_REPORT] == [
        "reuse_refused: run_recomputed"]
    assert "lineage_invalidated" not in result.state.options


def test_scenario_overlay_replay_preserves_requested_duplicate_multiplicity():
    config = {
        "agent_configs": [{
            "agent_id": 7,
            "entity_name": "Policy actor",
            "influence_weight": 2.0,
        }],
    }
    event = {
        "content": "Two deliberately distinct announcements",
        "round": 3,
        "poster_name": "Policy actor",
    }
    overlay = {"injected_events": [dict(event), dict(event)]}

    _po.PipelineOrchestrator.apply_scenario_overlay_to_config(config, overlay)
    _po.PipelineOrchestrator.apply_scenario_overlay_to_config(config, overlay)

    scheduled = config["event_config"]["scheduled_events"]
    assert len(scheduled) == 2
    assert all(row["poster_agent_id"] == 7 for row in scheduled)
    assert all(row["is_scenario_injection"] is True for row in scheduled)


@pytest.mark.parametrize("lineage_flags", [True, False])
def test_prepare_reuse_rebuilds_when_state_bound_config_seal_is_tampered(
    monkeypatch, tmp_path, lineage_flags
):
    result = _exercise_prepare_run_resume(
        monkeypatch,
        tmp_path,
        rebuild_prepare=False,
        corrupt_prepare_seal=True,
        lineage_flags=lineage_flags,
    )

    assert result.state.status == "completed"
    assert result.state.simulation_id == result.new_id
    assert result.manager_calls == {
        "create": 1, "prepare": 1, "reseal": 1, "validate": 1,
    }
    assert result.state.options["resumed_stage_validation"] == (
        "run_rebuilt_prepare_identity_changed"
    )
    assert result.state.options["artifact_validation_error"]["artifact"] == (
        "simulation_config_manifest"
    )
    assert "fingerprint mismatch" in result.state.options[
        "artifact_validation_error"
    ]["error"]
    assert result.start_calls == [result.new_id]
    if not lineage_flags:
        _assert_legacy_report_reuse(result)
        return
    assert result.report_generations == [result.new_id]


def test_research_html_artifact_is_raw_served_in_opaque_sandbox(monkeypatch, tmp_path):
    charts = tmp_path / "charts"
    charts.mkdir()
    chart = charts / "actor.html"
    chart.write_text("<html><script>window.ok=1</script></html>", encoding="utf-8")
    monkeypatch.setattr(
        _po.PipelineManager,
        "handoff_dir",
        classmethod(lambda cls, pid: str(tmp_path)),
    )
    monkeypatch.setattr(
        _po.PipelineManager,
        "load",
        classmethod(lambda cls, pid: {
            "artifacts": {"chart_actor.html_partial": str(chart)},
        }),
    )
    from app import create_app
    client = create_app().test_client()

    resp = client.get("/api/research/pipe/artifact/chart_actor.html")

    assert resp.status_code == 200
    assert resp.mimetype == "text/html"
    assert resp.data.startswith(b"<html>")
    assert "sandbox allow-scripts" in resp.headers["Content-Security-Policy"]
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_research_svg_artifact_disables_scripts(monkeypatch, tmp_path):
    charts = tmp_path / "charts"
    charts.mkdir()
    chart = charts / "active.svg"
    chart.write_text("<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
                     encoding="utf-8")
    monkeypatch.setattr(_po.PipelineManager, "handoff_dir",
                        classmethod(lambda cls, pid: str(tmp_path)))
    monkeypatch.setattr(_po.PipelineManager, "load", classmethod(lambda cls, pid: {
        "artifacts": {"chart_active.svg": str(chart)},
    }))
    from app import create_app
    resp = create_app().test_client().get("/api/research/pipe/artifact/chart_active.svg")

    assert resp.status_code == 200
    assert "sandbox;" in resp.headers["Content-Security-Policy"]
    assert "script-src 'none'" in resp.headers["Content-Security-Policy"]
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_research_chart_rejects_post_registration_symlink_swap(monkeypatch, tmp_path):
    charts = tmp_path / "charts"
    charts.mkdir()
    outside = tmp_path / "outside.html"
    outside.write_text("<script>window.stolen=1</script>", encoding="utf-8")
    swapped = charts / "actor.html"
    os.symlink(outside, swapped)
    monkeypatch.setattr(_po.PipelineManager, "handoff_dir",
                        classmethod(lambda cls, pid: str(tmp_path)))
    monkeypatch.setattr(_po.PipelineManager, "load", classmethod(lambda cls, pid: {
        "artifacts": {"chart_actor.html_partial": str(swapped)},
    }))
    from app import create_app
    resp = create_app().test_client().get("/api/research/pipe/artifact/chart_actor.html")

    assert resp.status_code == 404


# ── ITEM-18: 阶段级墙钟提取 ──────────────────────────────────────────────────

def test_stage_walls_computes_seconds_and_skips_incomplete():
    # 各阶段 started_at→finished_at 差值（秒）；缺一端/未结束的阶段跳过（degrade-safe）。
    st = _po.PipelineState(pipeline_id="pipe-walls-1", prompt="x")
    st.stages = {
        "research": _po.StageState(
            name="research", started_at="2026-05-01T00:00:00+00:00",
            finished_at="2026-05-01T00:00:42+00:00"),
        "graph": _po.StageState(
            name="graph", started_at="2026-05-01T00:01:00+00:00",
            finished_at="2026-05-01T00:01:05.500000+00:00"),
        "run": _po.StageState(name="run", started_at="2026-05-01T00:02:00+00:00"),  # 未结束
        "report": _po.StageState(name="report"),  # 未开始
    }
    walls = _po._stage_walls(st)
    assert walls == {"research": 42.0, "graph": 5.5}
    assert "run" not in walls and "report" not in walls


def test_stage_walls_empty_state_is_empty():
    st = _po.PipelineState(pipeline_id="pipe-walls-2", prompt="x")
    assert _po._stage_walls(st) == {}


def test_reused_stage_completion_preserves_original_wall_clock(monkeypatch):
    """A resume bookkeeping pass MUST not turn idle downtime into stage runtime."""
    state = _po.PipelineState(pipeline_id="pipe-walls-reuse", prompt="x")
    state.stages["research"] = _po.StageState(
        name="research",
        status="running",
        started_at="2026-05-01T00:00:00+00:00",
        finished_at="2026-05-01T00:00:42+00:00",
    )
    orchestrator = PipelineOrchestrator()
    monkeypatch.setattr(orchestrator, "_record_stage_artifacts", lambda *_args: None)
    monkeypatch.setattr(orchestrator, "_flush_run_telemetry", lambda *_args: None)
    monkeypatch.setattr(_po.PipelineManager, "save", classmethod(lambda cls, _state: None))
    monkeypatch.setattr(_po, "_utcnow", lambda: "2026-05-01T08:00:00+00:00")

    orchestrator._complete_stage(
        state, "research", "研究报告已恢复", reused=True,
    )

    assert state.stages["research"].finished_at == "2026-05-01T00:00:42+00:00"
    assert _po._stage_walls(state)["research"] == 42.0


@pytest.mark.parametrize(
    ("started_at", "finished_at", "expected"),
    [
        ("2026-05-01T00:00:00+00:00", None, "2026-05-01T00:00:00+00:00"),
        (None, "2026-05-01T00:00:42+00:00", "2026-05-01T00:00:42+00:00"),
    ],
)
def test_reused_stage_completion_collapses_one_sided_legacy_timing(
    monkeypatch, started_at, finished_at, expected,
):
    """A missing legacy endpoint MUST not turn resume idle time into runtime."""
    state = _po.PipelineState(pipeline_id="pipe-walls-one-sided", prompt="x")
    state.stages["research"] = _po.StageState(
        name="research",
        status="running",
        started_at=started_at,
        finished_at=finished_at,
    )
    orchestrator = PipelineOrchestrator()
    monkeypatch.setattr(orchestrator, "_record_stage_artifacts", lambda *_args: None)
    monkeypatch.setattr(orchestrator, "_flush_run_telemetry", lambda *_args: None)
    monkeypatch.setattr(_po.PipelineManager, "save", classmethod(lambda cls, _state: None))
    monkeypatch.setattr(_po, "_utcnow", lambda: "2026-05-01T08:00:00+00:00")

    orchestrator._complete_stage(state, "research", "研究报告已恢复", reused=True)

    stage = state.stages["research"]
    assert stage.started_at == expected
    assert stage.finished_at == expected
    assert _po._stage_walls(state)["research"] == 0.0


def test_retry_stage_reset_starts_a_fresh_timing_window():
    stage = _po.StageState(
        name="report",
        status="failed",
        progress=96,
        message="old failed attempt",
        error="quality gate failed",
        started_at="2026-05-01T00:00:00+00:00",
        finished_at="2026-05-01T00:30:00+00:00",
    )

    _po._reset_stage_attempt(stage)

    assert stage.status == "pending"
    assert stage.progress == 0
    assert stage.message == ""
    assert stage.error is None
    assert stage.started_at is None
    assert stage.finished_at is None


def test_reconcile_completed_simulation_state_copies_authoritative_run_progress():
    simulation = SimpleNamespace(
        status=_po.SimulationStatus.RUNNING,
        enable_twitter=True,
        enable_reddit=True,
        current_round=0,
        twitter_status="not_started",
        reddit_status="not_started",
        error="stale",
    )
    run_state = SimpleNamespace(
        current_round=19,
        twitter_enabled=True,
        reddit_enabled=True,
        twitter_completed=True,
        reddit_completed=True,
        error=None,
    )

    PipelineOrchestrator._reconcile_completed_simulation_state(simulation, run_state)

    assert simulation.status == _po.SimulationStatus.COMPLETED
    assert simulation.current_round == 19
    assert simulation.twitter_status == "completed"
    assert simulation.reddit_status == "completed"
    assert simulation.error is None


def test_reconcile_completed_simulation_state_keeps_legacy_platforms_unknown():
    simulation = SimpleNamespace(
        status=_po.SimulationStatus.COMPLETED,
        enable_twitter=True,
        enable_reddit=True,
        current_round=0,
        twitter_status="not_started",
        reddit_status="not_started",
        error=None,
    )

    PipelineOrchestrator._reconcile_completed_simulation_state(
        simulation,
        run_state=None,
        run_summary={"rounds_executed": 19},
    )

    assert simulation.current_round == 19
    assert simulation.twitter_status == "unknown"
    assert simulation.reddit_status == "unknown"


def test_reconcile_loaded_legacy_run_state_uses_simulation_enable_flags(
    tmp_path, monkeypatch
):
    from app.services.simulation_runner import SimulationRunner

    simulation_id = "sim_legacy_enabled_flags"
    run_dir = tmp_path / simulation_id
    run_dir.mkdir()
    (run_dir / "run_state.json").write_text(
        json.dumps({
            "simulation_id": simulation_id,
            "runner_status": "completed",
            "current_round": 19,
            "twitter_completed": True,
            "reddit_completed": False,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(SimulationRunner, "RUN_STATE_DIR", str(tmp_path))

    loaded = SimulationRunner._load_run_state(simulation_id)
    assert loaded is not None
    assert loaded.twitter_enabled is None
    assert loaded.reddit_enabled is None

    simulation = SimpleNamespace(
        status=_po.SimulationStatus.RUNNING,
        enable_twitter=True,
        enable_reddit=False,
        current_round=0,
        twitter_status="not_started",
        reddit_status="not_started",
        error=None,
    )
    PipelineOrchestrator._reconcile_completed_simulation_state(
        simulation,
        run_state=loaded,
        run_summary={"rounds_executed": 19},
    )

    assert simulation.twitter_status == "completed"
    assert simulation.reddit_status == "disabled"


def test_report_agent_accepts_charts_manifest_kwarg():
    # 附加 kwarg：仅存储、默认 None、不改变旧构造行为。
    from app.services.report_agent import ReportAgent
    manifest = [{"title": "t", "caption": "c", "source_data": "d"}]
    agent = ReportAgent.__new__(ReportAgent)  # 免全量构造（无需 LLM/图谱）
    # 直接断言签名接受该 kwarg 且默认 None 语义：用 __init__ 参数内省。
    import inspect
    sig = inspect.signature(ReportAgent.__init__)
    assert "charts_manifest" in sig.parameters
    assert sig.parameters["charts_manifest"].default is None
    del agent, manifest


# ── Engine v3: engine selection, outer-lane topology, child env ─────────────

class _RecordingLogger:
    """Stand-in for the orchestrator's non-propagating logger (caplog cannot
    see ``mirofish.*`` records); keeps (level, rendered message) pairs."""

    def __init__(self):
        self.records = []

    def _log(self, level, msg, *args, **_kwargs):
        self.records.append((level, msg % args if args else msg))

    def debug(self, msg, *args, **kwargs):
        self._log("debug", msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self._log("info", msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._log("warning", msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._log("error", msg, *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        self._log("error", msg, *args, **kwargs)

    def of(self, level):
        return [text for lvl, text in self.records if lvl == level]


@pytest.mark.parametrize("raw, expected", [
    ("v3", "v3"),
    (" V3 ", "v3"),
    ("linear", "v3"),        # historical .env spelling → v3 alias
    ("LINEAR", "v3"),
    ("legacy", "legacy"),
    ("Legacy\n", "legacy"),
    ("deerflow", "legacy"),  # bridge-side legacy aliases resolve identically
    ("agentic", "legacy"),
    ("", "v3"),              # empty = unset → default
])
def test_resolve_research_engine_normalizes_aliases(raw, expected):
    assert _po.resolve_research_engine(raw) == expected


def test_engine_aliases_select_the_same_engine_in_parent_and_bridge(monkeypatch):
    """The parent passes its normalized value to the child, but operators and
    direct CLI runs set RESEARCH_ENGINE themselves: every spelling the parent
    accepts must mean the same engine to the bridge's own resolver."""
    import importlib
    import sys

    bridge_dir = str(Path(__file__).resolve().parents[2] / "deerflow_bridge")
    if bridge_dir not in sys.path:
        sys.path.insert(0, bridge_dir)
    bridge = importlib.import_module("deerflow_research")
    for spelling, engine in _po._RESEARCH_ENGINE_ALIASES.items():
        monkeypatch.setenv("RESEARCH_ENGINE", spelling)
        assert bridge._resolve_research_engine(None) == engine, spelling
        assert _po.resolve_research_engine(spelling) == engine, spelling


def test_resolve_research_engine_reads_config_by_default(monkeypatch):
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "linear", raising=False)
    assert _po.resolve_research_engine() == "v3"
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "legacy", raising=False)
    assert _po.resolve_research_engine() == "legacy"


def test_unknown_research_engine_falls_back_to_v3_with_one_warning(monkeypatch):
    log = _RecordingLogger()
    monkeypatch.setattr(_po, "logger", log)
    monkeypatch.setattr(_po, "_UNKNOWN_RESEARCH_ENGINES_WARNED", set())

    assert _po.resolve_research_engine("langgraph-v9") == "v3"
    assert _po.resolve_research_engine("LangGraph-V9") == "v3"   # same value, normalized
    assert _po.resolve_research_engine("other") == "v3"

    warnings = log.of("warning")
    assert len(warnings) == 2
    assert "langgraph-v9" in warnings[0] and "other" in warnings[1]


@pytest.mark.parametrize("configured, expected", [
    (3, 3), (2, 2), (1, 1), (0, 3), (None, 3), ("x", 3), ("2", 2),
])
def test_legacy_engine_keeps_todays_outer_track_rule(configured, expected):
    assert _po.research_outer_track_count(configured, "legacy") == expected


def test_v3_engine_forces_single_outer_track_and_logs_once(monkeypatch):
    log = _RecordingLogger()
    monkeypatch.setattr(_po, "logger", log)

    assert _po.research_outer_track_count(3, "v3", pipeline_id="pipe_v3") == 1
    infos = log.of("info")
    assert len(infos) == 1
    assert "pipe_v3" in infos[0] and "RESEARCH_PARALLEL_TRACKS=3" in infos[0]

    # Nothing to disable → no override log.
    assert _po.research_outer_track_count(1, "v3") == 1
    assert len(log.of("info")) == 1
    # Unset/garbage means the legacy default of 3 lanes, which v3 also overrides.
    assert _po.research_outer_track_count(None, "v3") == 1
    assert len(log.of("info")) == 2


def _drive_research_only_stage(monkeypatch, tmp_path, *, engine, tracks, options=None,
                               runner_kwargs=None, expect_status="completed",
                               handoff_files=None):
    """Run the real ``_run`` state machine for a fresh research-only pipeline
    with the research subprocess layer faked; return which topology ran (and,
    for a single lane, the engine the stage asked the runner for).
    ``runner_kwargs`` (a list) collects each single-lane runner call's kwargs;
    ``handoff_files`` ({name: text}) are written to the handoff dir before the run."""
    monkeypatch.setattr(_po.Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"),
                        raising=False)
    monkeypatch.setattr(_po.Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"),
                        raising=False)
    for name, value in {
        "RESEARCH_ENGINE": engine,
        "RESEARCH_PARALLEL_TRACKS": tracks,
        "REPORT_LINT": False,
        "CAST_RECONCILE": False,
        "EMBED_WARM_AT_RESEARCH": False,
        "PIPELINE_VIZ_ARTIFACTS": False,
    }.items():
        monkeypatch.setattr(_po.Config, name, value, raising=False)
    for name, replacement in {
        "_start_heartbeat": lambda self, state: None,
        "_init_telemetry_flush": lambda self, state: None,
        "_write_run_manifest": lambda self, state: None,
        "_update_manifest": lambda self, state, stage, **kwargs: None,
        "_record_research_telemetry": lambda self, state, value: None,
        "_maybe_warm_embedder": lambda self, state, actors: None,
        "_surface_research_quality": lambda self, state, handoff_dir: {},
        "_surface_forecast_confidence_penalty": lambda self, state, handoff_dir: None,
        "_flush_run_telemetry": lambda self, state, **kwargs: None,
    }.items():
        monkeypatch.setattr(_po.PipelineOrchestrator, name, replacement)
    monkeypatch.setattr(_po, "_finalize_research_contract", lambda *a, **k: None)

    calls = []
    engines = []
    report = "Evidence-backed research report with citations [S1]. " * 20

    def research_result(handoff_dir):
        with open(os.path.join(handoff_dir, "research_report.md"), "w",
                  encoding="utf-8") as fh:
            fh.write(report)
        return {
            "report": report,
            "report_path": os.path.join(handoff_dir, "research_report.md"),
            "evidence_pack": None, "actor_dossier": "", "actors": None,
            "sources": None, "timeline": None, "exit_code": 0,
            "research_telemetry": {"tokens_in": 0, "tokens_out": 0},
        }

    def fake_single(prompt, handoff_dir, **kwargs):
        calls.append(("single", kwargs.get("budget_lane_id")))
        engines.append(kwargs.get("research_engine"))
        if runner_kwargs is not None:
            runner_kwargs.append(kwargs)
        return research_result(handoff_dir)

    def fake_parallel(self, state, handoff_dir, upd, n_tracks):
        calls.append(("parallel", n_tracks))
        return fake_single(state.prompt, handoff_dir)

    def fake_synthesis_recovery(self, state, handoff_dir, upd, manifest_path):
        calls.append(("synthesis_recovery", os.path.basename(manifest_path)))
        return research_result(handoff_dir)

    monkeypatch.setattr(_po.DeerFlowResearchRunner, "run", staticmethod(fake_single))
    monkeypatch.setattr(
        _po.PipelineOrchestrator, "_run_parallel_research_tracks", fake_parallel)
    monkeypatch.setattr(
        _po.PipelineOrchestrator, "_run_research_synthesis_recovery", fake_synthesis_recovery)

    pid = f"pipe_topology_{engine}_{tracks}"
    _po.PipelineManager.ensure_dirs(pid)
    state = _po.PipelineState(
        pipeline_id=pid, prompt="Will X happen by 2030?",
        mode="research_only", status="running", options=dict(options or {}),
    )
    state.handoff_dir = _po.PipelineManager.handoff_dir(pid)
    os.makedirs(state.handoff_dir, exist_ok=True)
    for name, text in (handoff_files or {}).items():
        with open(os.path.join(state.handoff_dir, name), "w", encoding="utf-8") as fh:
            fh.write(text)
    _po.PipelineOrchestrator._run(state)
    assert state.status == expect_status, state.error
    if options is not None:
        return calls, engines
    return calls


def test_research_stage_runs_one_outer_lane_for_v3_even_with_parallel_tracks(
        monkeypatch, tmp_path):
    calls = _drive_research_only_stage(monkeypatch, tmp_path, engine="v3", tracks=3)
    assert calls == [("single", "outer-track-1")]


def test_research_stage_keeps_parallel_lanes_for_legacy_engine(monkeypatch, tmp_path):
    calls = _drive_research_only_stage(monkeypatch, tmp_path, engine="legacy", tracks=3)
    assert calls[0] == ("parallel", 3)


class _FakeResearchProc:
    def __init__(self):
        self.pid = 4242
        self.stdout = ["2026-09-27T00:00:00+00:00 [done] research complete\n"]

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def _launch_capturing_child(monkeypatch, tmp_path, *, actors=None, **run_kwargs):
    """Launch the real runner against a fake Popen; return the child cmd/env
    (and the runner's result under ``"result"``).  ``actors``, when given, is the
    handoff actors.json the child left behind."""
    deerflow_dir = tmp_path / "deer-flow"
    deerflow_dir.mkdir()
    (deerflow_dir / "deerflow_research.py").write_text("# entry\n", encoding="utf-8")
    handoff = tmp_path / "handoff"
    handoff.mkdir()
    artifact = "evidence_pack.md" if run_kwargs.get("evidence_only") else "research_report.md"
    (handoff / artifact).write_text(
        "Evidence: the regulator published the 2026 capacity figures [S1]. " * 12,
        encoding="utf-8")
    if actors is not None:
        (handoff / "actors.json").write_text(json.dumps(actors), encoding="utf-8")
    monkeypatch.setattr(_po.Config, "DEERFLOW_DIR", str(deerflow_dir))
    monkeypatch.setattr(_po.Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    monkeypatch.setattr(_po, "_sync_deerflow_bridge_if_stale", lambda _p: None)
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["env"] = dict(kwargs["env"])
        return _FakeResearchProc()

    monkeypatch.setattr(_po.subprocess, "Popen", fake_popen)
    captured["result"] = _po.DeerFlowResearchRunner.run(
        "Will X happen?", str(handoff), on_progress=lambda _p, _m: None, **run_kwargs)
    return captured


def test_runner_passes_v3_engine_and_watchdog_budget_explicitly(monkeypatch, tmp_path):
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    # Ambient env must never decide the child's engine: the parent is authoritative.
    monkeypatch.setenv("RESEARCH_ENGINE", "legacy")
    monkeypatch.setenv("DEERFLOW_RESEARCH_TIMEOUT", "14400")

    child = _launch_capturing_child(monkeypatch, tmp_path, timeout=900)

    assert child["env"]["RESEARCH_ENGINE"] == "v3"
    # v3 plans against the watchdog that will actually kill it (explicit timeout).
    assert child["env"]["DEERFLOW_RESEARCH_TIMEOUT"] == "900"


def test_runner_hands_v3_the_depth_tier_watchdog_budget(monkeypatch, tmp_path):
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "linear", raising=False)
    monkeypatch.delenv("DEERFLOW_RESEARCH_TIMEOUT", raising=False)

    child = _launch_capturing_child(monkeypatch, tmp_path, depth="quick")

    assert child["env"]["RESEARCH_ENGINE"] == "v3"
    assert child["env"]["DEERFLOW_RESEARCH_TIMEOUT"] == str(
        int(_po.Config.deerflow_depth_budget("quick")))


def test_runner_passes_legacy_engine_without_touching_its_env(monkeypatch, tmp_path):
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "legacy", raising=False)
    monkeypatch.delenv("DEERFLOW_RESEARCH_TIMEOUT", raising=False)

    child = _launch_capturing_child(monkeypatch, tmp_path, timeout=900)

    assert child["env"]["RESEARCH_ENGINE"] == "legacy"
    assert "DEERFLOW_RESEARCH_TIMEOUT" not in child["env"]


def test_runner_unknown_engine_launches_v3(monkeypatch, tmp_path):
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "gpt-researcher", raising=False)
    monkeypatch.setattr(_po, "logger", _RecordingLogger())

    child = _launch_capturing_child(monkeypatch, tmp_path, timeout=900)

    assert child["env"]["RESEARCH_ENGINE"] == "v3"


@pytest.mark.parametrize("lane_kwargs, flag", [
    ({"evidence_only": True}, "--evidence-only"),
    ({"synthesis_manifest_path": "/tmp/evidence_synthesis_manifest.json"},
     "--synthesis-manifest"),
])
def test_lane_contract_invocations_always_declare_legacy_engine(
        monkeypatch, tmp_path, lane_kwargs, flag):
    """Evidence lanes / global synthesis are legacy-only contracts (IF-1): even
    with RESEARCH_ENGINE=v3 the child is told to run the engine that honours them."""
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    monkeypatch.delenv("DEERFLOW_RESEARCH_TIMEOUT", raising=False)

    child = _launch_capturing_child(monkeypatch, tmp_path, timeout=900, **lane_kwargs)

    assert flag in child["cmd"]
    assert child["env"]["RESEARCH_ENGINE"] == "legacy"
    assert "DEERFLOW_RESEARCH_TIMEOUT" not in child["env"]


@pytest.mark.parametrize("engine, dual_track, required, reason", [
    ("v3", True, False, _po.ACTOR_PLANE_UNSUPPORTED_BY_V3),
    ("linear", True, False, _po.ACTOR_PLANE_UNSUPPORTED_BY_V3),
    ("legacy", True, True, None),
    ("v3", False, False, None),
    ("legacy", False, False, None),
])
def test_admission_actor_policy_follows_research_engine(
        monkeypatch, engine, dual_track, required, reason):
    """IF-2: v3 never produces the sealed actor-intelligence/v1 plane, so a
    dual-track admission must not pin it as required (reception would fail every
    full run after the research spend); legacy admissions are unchanged."""
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", engine, raising=False)
    monkeypatch.setattr(_po.Config, "DEERFLOW_DUAL_TRACK", dual_track, raising=False)

    policy = _po.admission_actor_intelligence_policy_v1()

    assert policy["origin"] == "admission"
    assert policy["required"] is required
    assert policy["research_engine"] == _po.resolve_research_engine(engine)
    assert policy.get("not_required_reason") == reason
    assert policy["version"] == _po.ACTOR_INTELLIGENCE_POLICY_VERSION
    assert policy["schema_version"] == _po.ACTOR_INTELLIGENCE_SCHEMA_VERSION


def test_pipeline_start_pins_engine_aware_actor_policy(monkeypatch, tmp_path):
    monkeypatch.setattr(_po.Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"),
                        raising=False)
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    monkeypatch.setattr(_po.Config, "DEERFLOW_DUAL_TRACK", True, raising=False)
    # The admission record is what matters; the background run is a no-op.
    monkeypatch.setattr(_po.PipelineOrchestrator, "_run", classmethod(lambda cls, state: None))

    state = _po.PipelineOrchestrator.start("Will X happen by 2030?", mode="full")
    try:
        _po.PipelineOrchestrator._threads[state.pipeline_id].join(timeout=5)
        persisted = _po.PipelineManager.load(state.pipeline_id)
        policy = persisted["options"]["actor_intelligence_policy_v1"]
        assert policy["required"] is False
        assert policy["research_engine"] == "v3"
        assert policy["not_required_reason"] == _po.ACTOR_PLANE_UNSUPPORTED_BY_V3
    finally:
        _po.PipelineOrchestrator._threads.pop(state.pipeline_id, None)
        _po.PipelineOrchestrator._cancel_events.pop(state.pipeline_id, None)


def test_v3_pinned_policy_admits_unsealed_actors_with_disclosed_reason(monkeypatch):
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    monkeypatch.setattr(_po.Config, "DEERFLOW_DUAL_TRACK", True, raising=False)
    state = _po.PipelineState(
        pipeline_id="pipe_v3_reception", prompt="forecast",
        options={"actor_intelligence_policy_v1":
                 _po.admission_actor_intelligence_policy_v1()},
    )
    unsealed = {"actors": [{"name": "Regulator", "type": "Government"}]}

    _po._enforce_actor_intelligence_reception(
        state, unsealed, report="report", dossier="", sources=[])

    assert state.options["actor_intelligence_reception"] == {
        "required": False,
        "passed": True,
        "reason": _po.ACTOR_PLANE_UNSUPPORTED_BY_V3,
    }


# ── F20: a pipeline admitted before v3 keeps the engine its pinned policy needs ──

def _pre_upgrade_policy(monkeypatch):
    """What admission pinned before the v3 change: dual-track on (the default),
    so ``required=True`` and no ``research_engine`` key."""
    monkeypatch.setattr(_po.Config, "DEERFLOW_DUAL_TRACK", True, raising=False)
    policy = _po.capture_actor_intelligence_policy_v1("admission")
    assert policy["required"] is True and "research_engine" not in policy
    return policy


def test_research_engine_for_run_honours_a_policy_that_requires_the_sealed_plane(monkeypatch):
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    pre_upgrade = _pre_upgrade_policy(monkeypatch)
    assert _po.research_engine_for_run({"actor_intelligence_policy_v1": pre_upgrade}) == "legacy"
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "legacy", raising=False)
    legacy_admission = _po.admission_actor_intelligence_policy_v1()
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    assert legacy_admission["required"] is True
    assert _po.research_engine_for_run({"actor_intelligence_policy_v1": legacy_admission}) == "legacy"
    v3_admission = _po.admission_actor_intelligence_policy_v1()
    assert _po.research_engine_for_run({"actor_intelligence_policy_v1": v3_admission}) == "v3"
    assert _po.research_engine_for_run({}) == "v3"          # pre-policy run: configured engine
    assert _po.research_engine_for_run(None) == "v3"
    disabled = _po.capture_actor_intelligence_policy_v1("admission", required=False)
    assert _po.research_engine_for_run({"actor_intelligence_policy_v1": disabled}) == "v3"


def test_pre_upgrade_pipeline_resumes_on_the_legacy_engine(monkeypatch, tmp_path):
    """F20: the stage used Config (v3) for such a run, which then wrote unsealed
    actors and failed reception after the whole research spend."""
    policy = _pre_upgrade_policy(monkeypatch)
    calls, engines = _drive_research_only_stage(
        monkeypatch, tmp_path, engine="v3", tracks=1,
        options={"actor_intelligence_policy_v1": policy})
    assert calls == [("single", "outer-track-1")] and engines == ["legacy"]


def test_pre_upgrade_pipeline_keeps_legacy_parallel_lanes(monkeypatch, tmp_path):
    policy = _pre_upgrade_policy(monkeypatch)
    calls, _ = _drive_research_only_stage(
        monkeypatch, tmp_path, engine="v3", tracks=3,
        options={"actor_intelligence_policy_v1": policy})
    assert calls[0] == ("parallel", 3)


def test_v3_admitted_pipeline_still_runs_v3(monkeypatch, tmp_path):
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    monkeypatch.setattr(_po.Config, "DEERFLOW_DUAL_TRACK", True, raising=False)
    policy = _po.admission_actor_intelligence_policy_v1()
    calls, engines = _drive_research_only_stage(
        monkeypatch, tmp_path, engine="v3", tracks=3,
        options={"actor_intelligence_policy_v1": policy})
    assert calls == [("single", "outer-track-1")] and engines == ["v3"]


def test_runner_launches_the_engine_the_stage_selected(monkeypatch, tmp_path):
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    monkeypatch.delenv("DEERFLOW_RESEARCH_TIMEOUT", raising=False)

    child = _launch_capturing_child(monkeypatch, tmp_path, timeout=900, research_engine="legacy")

    assert child["env"]["RESEARCH_ENGINE"] == "legacy"
    assert "DEERFLOW_RESEARCH_TIMEOUT" not in child["env"]


# ------------------------------------------------ research-child knob registry

def test_runner_forwards_the_as_of_pin_from_config_to_v3_only(monkeypatch, tmp_path):
    """TIME-1: Config decides RESEARCH_AS_OF_PIN for the v3 child, never ambient env."""
    for name in ("default", "off", "ambient", "legacy"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    monkeypatch.delenv("RESEARCH_AS_OF_PIN", raising=False)
    # The hermetic Config default (the ambient env is scrubbed before import).
    assert _po.Config.RESEARCH_AS_OF_PIN is True
    child = _launch_capturing_child(monkeypatch, tmp_path / "default", timeout=900)
    assert child["env"]["RESEARCH_AS_OF_PIN"] == "true"

    monkeypatch.setattr(_po.Config, "RESEARCH_AS_OF_PIN", False)
    child = _launch_capturing_child(monkeypatch, tmp_path / "off", timeout=900)
    assert child["env"]["RESEARCH_AS_OF_PIN"] == "false"

    monkeypatch.setattr(_po.Config, "RESEARCH_AS_OF_PIN", True)
    monkeypatch.setenv("RESEARCH_AS_OF_PIN", "false")
    child = _launch_capturing_child(monkeypatch, tmp_path / "ambient", timeout=900)
    assert child["env"]["RESEARCH_AS_OF_PIN"] == "true"

    # The legacy engine has its own as-of clamp: the v3-only knob is not forwarded.
    monkeypatch.delenv("RESEARCH_AS_OF_PIN")
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "legacy", raising=False)
    child = _launch_capturing_child(monkeypatch, tmp_path / "legacy", timeout=900)
    assert "RESEARCH_AS_OF_PIN" not in child["env"]


def test_runner_forwards_the_source_date_knobs_from_config_to_v3_only(monkeypatch, tmp_path):
    """TIME-2: Config decides RESEARCH_SOURCE_DATES and
    RESEARCH_SOURCE_DATE_TEXT_FALLBACK for the v3 child, never ambient env."""
    names = ("RESEARCH_SOURCE_DATES", "RESEARCH_SOURCE_DATE_TEXT_FALLBACK")
    for name in ("default", "flipped", "legacy"):
        (tmp_path / name).mkdir()
    assert ("RESEARCH_SOURCE_DATES", "bool") in _po.RESEARCH_CHILD_V3_KNOBS
    assert ("RESEARCH_SOURCE_DATE_TEXT_FALLBACK", "bool") in _po.RESEARCH_CHILD_V3_KNOBS
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    for name in names:
        monkeypatch.delenv(name, raising=False)
    # The hermetic Config defaults: dates off, text fallback on.
    assert (_po.Config.RESEARCH_SOURCE_DATES, _po.Config.RESEARCH_SOURCE_DATE_TEXT_FALLBACK) == (False, True)
    child = _launch_capturing_child(monkeypatch, tmp_path / "default", timeout=900)
    assert [child["env"][name] for name in names] == ["false", "true"]

    monkeypatch.setattr(_po.Config, "RESEARCH_SOURCE_DATES", True)
    monkeypatch.setattr(_po.Config, "RESEARCH_SOURCE_DATE_TEXT_FALLBACK", False)
    monkeypatch.setenv("RESEARCH_SOURCE_DATES", "false")
    monkeypatch.setenv("RESEARCH_SOURCE_DATE_TEXT_FALLBACK", "true")
    child = _launch_capturing_child(monkeypatch, tmp_path / "flipped", timeout=900)
    assert [child["env"][name] for name in names] == ["true", "false"]

    for name in names:
        monkeypatch.delenv(name)
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "legacy", raising=False)
    child = _launch_capturing_child(monkeypatch, tmp_path / "legacy", timeout=900)
    assert not any(name in child["env"] for name in names)


_SOURCE_DATE_CONFIG_CHILD = r"""
import importlib, json, os, sys
import dotenv
dotenv.load_dotenv = lambda *a, **k: False  # the repo .env must not decide
import app.config as config_module
out = []
for raw in json.loads(sys.argv[1]):
    for name in ("RESEARCH_SOURCE_DATES", "RESEARCH_SOURCE_DATE_TEXT_FALLBACK"):
        if raw is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = raw
    config = importlib.reload(config_module).Config
    out.append([config.RESEARCH_SOURCE_DATES, config.RESEARCH_SOURCE_DATE_TEXT_FALLBACK])
print("<<<JSON>>>" + json.dumps(out))
"""


def test_source_date_config_parsing():
    """RESEARCH_SOURCE_DATES follows the default-off 'true' pattern; the default-on
    text fallback is disabled only by an explicit falsy word (as the child reads
    it).  A clean child process: app.config loads the repo .env at import."""
    import subprocess
    import sys

    cases = [(None, False, True), ("true", True, True), ("TRUE ", True, True), ("1", False, True),
             ("false", False, False), ("0", False, False), ("off", False, False), ("maybe", False, True)]
    backend = Path(__file__).resolve().parents[1]
    proc = subprocess.run([sys.executable, "-c", _SOURCE_DATE_CONFIG_CHILD, json.dumps([c[0] for c in cases])],
                          cwd=str(backend), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    line = [ln for ln in proc.stdout.splitlines() if ln.startswith("<<<JSON>>>")][-1]
    assert json.loads(line[len("<<<JSON>>>"):]) == [[dates, fallback] for _raw, dates, fallback in cases]


def test_runner_forwards_the_end_date_gate_knobs_from_config_to_every_engine(
        monkeypatch, tmp_path):
    """TIME-3: Config decides the Polymarket endDate gate and its grace hours for the
    research child of every engine (all engines collect prediction markets)."""
    for name in ("default", "flipped", "legacy"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    # The hermetic Config defaults: gate on, no grace.
    assert _po.Config.PREDICTION_MARKETS_END_DATE_GATE is True
    assert _po.Config.PREDICTION_MARKETS_END_DATE_GRACE_HOURS == 0.0
    child = _launch_capturing_child(monkeypatch, tmp_path / "default", timeout=900)
    assert child["env"]["PREDICTION_MARKETS_END_DATE_GATE"] == "true"
    assert child["env"]["PREDICTION_MARKETS_END_DATE_GRACE_HOURS"] == "0.0"

    monkeypatch.setattr(_po.Config, "PREDICTION_MARKETS_END_DATE_GATE", False)
    monkeypatch.setattr(_po.Config, "PREDICTION_MARKETS_END_DATE_GRACE_HOURS", 6.5)
    # An ambient value never decides: the parent's Config is authoritative.
    monkeypatch.setenv("PREDICTION_MARKETS_END_DATE_GATE", "true")
    monkeypatch.setenv("PREDICTION_MARKETS_END_DATE_GRACE_HOURS", "99")
    child = _launch_capturing_child(monkeypatch, tmp_path / "flipped", timeout=900)
    assert child["env"]["PREDICTION_MARKETS_END_DATE_GATE"] == "false"
    assert child["env"]["PREDICTION_MARKETS_END_DATE_GRACE_HOURS"] == "6.5"

    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "legacy", raising=False)
    child = _launch_capturing_child(monkeypatch, tmp_path / "legacy", timeout=900)
    assert child["env"]["PREDICTION_MARKETS_END_DATE_GATE"] == "false"
    assert child["env"]["PREDICTION_MARKETS_END_DATE_GRACE_HOURS"] == "6.5"


def test_runner_forwards_quant_reconcile_from_config_to_every_engine(monkeypatch, tmp_path):
    """TIME-4: Config decides RESEARCH_QUANT_RECONCILE for the research child of
    every engine (both engines and the extract-only salvage read it); an
    ambient value never decides."""
    assert ("RESEARCH_QUANT_RECONCILE", "bool") in _po.RESEARCH_CHILD_KNOBS
    for name in ("default", "v3", "legacy"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    assert _po.Config.RESEARCH_QUANT_RECONCILE is True   # the hermetic default
    child = _launch_capturing_child(monkeypatch, tmp_path / "default", timeout=900)
    assert child["env"]["RESEARCH_QUANT_RECONCILE"] == "true"

    monkeypatch.setattr(_po.Config, "RESEARCH_QUANT_RECONCILE", False)
    monkeypatch.setenv("RESEARCH_QUANT_RECONCILE", "true")
    child = _launch_capturing_child(monkeypatch, tmp_path / "v3", timeout=900)
    assert child["env"]["RESEARCH_QUANT_RECONCILE"] == "false"

    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "legacy", raising=False)
    child = _launch_capturing_child(monkeypatch, tmp_path / "legacy", timeout=900)
    assert child["env"]["RESEARCH_QUANT_RECONCILE"] == "false"


def _registry_entries():
    return [*_po.RESEARCH_CHILD_KNOBS, *_po.RESEARCH_CHILD_V3_KNOBS]


def test_research_child_registry_names_exist_on_config_and_are_documented():
    env_example = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\s*#?\s*([A-Z][A-Z0-9_]+)=", env_example, re.M))
    entries = _registry_entries()
    assert ("RESEARCH_AS_OF_PIN", "bool") in _po.RESEARCH_CHILD_V3_KNOBS
    for name, kind in entries:
        assert hasattr(_po.Config, name), name
        assert name in documented, f"{name} is not documented in .env.example"
        assert kind in _po._RESEARCH_KNOB_FORMATTERS, (name, kind)
    names = [name for name, _kind in entries]
    assert len(names) == len(set(names)), "a knob is registered twice"
    for table in (_po.RESEARCH_CHILD_KNOBS, _po.RESEARCH_CHILD_V3_KNOBS):
        assert [name for name, _kind in table] == sorted(name for name, _kind in table)


def test_registry_forwarder_formats_each_kind(monkeypatch):
    monkeypatch.setattr(_po.Config, "_TIME1_ON", True, raising=False)
    monkeypatch.setattr(_po.Config, "_TIME1_OFF", 0, raising=False)
    monkeypatch.setattr(_po.Config, "_TIME1_INT", 7.9, raising=False)
    monkeypatch.setattr(_po.Config, "_TIME1_FLOAT", 5, raising=False)
    monkeypatch.setattr(_po.Config, "_TIME1_STR", "dossier_only", raising=False)
    env = {"_TIME1_ON": "0", "UNRELATED": "kept"}
    _po._forward_research_knobs(env, (("_TIME1_ON", "bool"), ("_TIME1_OFF", "bool"), ("_TIME1_INT", "int"),
                                      ("_TIME1_FLOAT", "float"), ("_TIME1_STR", "str")))
    # Bools are 'true'/'false' (never '1'/'0') and overwrite any inherited value.
    assert env == {"_TIME1_ON": "true", "_TIME1_OFF": "false", "_TIME1_INT": "7",
                   "_TIME1_FLOAT": "5.0", "_TIME1_STR": "dossier_only", "UNRELATED": "kept"}


def test_registry_forwarder_fails_loudly_on_a_broken_entry(monkeypatch):
    monkeypatch.setattr(_po.Config, "_TIME1_ON", True, raising=False)
    with pytest.raises(ValueError, match="unknown kind"):
        _po._forward_research_knobs({}, (("_TIME1_ON", "boolean"),))
    with pytest.raises(AttributeError):
        _po._forward_research_knobs({}, (("_TIME1_NOT_ON_CONFIG", "bool"),))


def test_every_registry_knob_is_forwarded_from_config(monkeypatch, tmp_path):
    """Each registered knob reaches its child with the Config value; the v3
    table only reaches a v3 child."""
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    (tmp_path / "v3").mkdir()
    (tmp_path / "legacy").mkdir()
    child = _launch_capturing_child(monkeypatch, tmp_path / "v3", timeout=900)
    for name, kind in _registry_entries():
        assert child["env"][name] == _po._RESEARCH_KNOB_FORMATTERS[kind](getattr(_po.Config, name)), name

    for name, _kind in _po.RESEARCH_CHILD_V3_KNOBS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "legacy", raising=False)
    child = _launch_capturing_child(monkeypatch, tmp_path / "legacy", timeout=900)
    for name, _kind in _po.RESEARCH_CHILD_V3_KNOBS:
        assert name not in child["env"], name
    for name, kind in _po.RESEARCH_CHILD_KNOBS:
        assert child["env"][name] == _po._RESEARCH_KNOB_FORMATTERS[kind](getattr(_po.Config, name)), name


def test_judge_bound_probe_is_false_without_a_contract_manifest(tmp_path):
    """Single-lane runs publish no research contract manifest; the probe must
    answer False instead of raising (the AttributeError skipped research lint)."""
    assert _po._research_report_is_judge_bound(str(tmp_path)) is False


# ── TIME-7: a pinned hindcast's as-of reaches only a v3 child; graph anchor = pin ──

from datetime import date  # noqa: E402

from app.services import hindcast_policy as _hp  # noqa: E402

HINDCAST_AS_OF = "2024-06-01"


def _hindcast_pin(as_of=HINDCAST_AS_OF):
    return _hp.capture_hindcast_policy_v1(as_of, research_engine="v3", today_utc=date(2026, 9, 30))


def test_runner_hands_a_pinned_as_of_to_the_v3_child(monkeypatch, tmp_path):
    """The hindcast values are written after every Config forward, so they win
    (markets on and the as-of pin off in Config), and an ambient value never decides."""
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    monkeypatch.setattr(_po.Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)
    monkeypatch.setattr(_po.Config, "RESEARCH_AS_OF_PIN", False, raising=False)
    monkeypatch.setenv("RESEARCH_AS_OF", "2020-01-01")

    child = _launch_capturing_child(monkeypatch, tmp_path, timeout=900, as_of=HINDCAST_AS_OF,
                                    actors={"as_of_date": HINDCAST_AS_OF, "actors": []})

    env = child["env"]
    assert env["RESEARCH_ENGINE"] == "v3"
    assert env["RESEARCH_AS_OF"] == HINDCAST_AS_OF
    assert env["PREDICTION_MARKETS_ENABLED"] == "false"
    assert env["RESEARCH_AS_OF_PIN"] == "true"
    assert HINDCAST_AS_OF not in " ".join(child["cmd"])  # env contract only, no new CLI flag
    assert child["result"]["actors"]["as_of_date"] == HINDCAST_AS_OF


@pytest.mark.parametrize("actors", [None, {"as_of_date": "2026-09-30", "actors": []},
                                    {"actors": []}, ["not", "an", "object"]])
def test_pinned_child_must_date_actors_to_the_pin(monkeypatch, tmp_path, actors):
    """actors.json as_of_date anchors the simulation calendar: a hindcast whose child
    left no actors.json, or dated it otherwise, fails closed (resumable)."""
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    with pytest.raises(RuntimeError, match="hindcast_as_of_mismatch"):
        _launch_capturing_child(monkeypatch, tmp_path, timeout=900, as_of=HINDCAST_AS_OF,
                                actors=actors)


def test_live_child_keeps_the_model_dated_actors(monkeypatch, tmp_path):
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    child = _launch_capturing_child(monkeypatch, tmp_path, timeout=900,
                                    actors={"as_of_date": "2026-09-30", "actors": []})
    assert child["result"]["actors"]["as_of_date"] == "2026-09-30"


class _ManualWatchdog:
    """``threading.Timer`` stand-in: the fake child fires the research watchdog itself."""

    armed = []

    def __init__(self, interval, function):
        self.function = function
        self.daemon = False
        _ManualWatchdog.armed.append(self)

    def start(self):
        return None

    def cancel(self):
        return None


class _KilledDuringFinalizeProc:
    """A child the watchdog kills after it wrote research_report.md (v3 writes the report,
    then makes its structured-extraction calls), optionally after actors.json as well."""

    pid = 4243

    def __init__(self, handoff, actors):
        self.handoff = handoff
        self.actors = actors
        self.killed = False

    @property
    def stdout(self):
        yield "2026-09-30T00:00:00+00:00 [stage] research:v3:finalize start\n"
        (self.handoff / "research_report.md").write_text(
            "Evidence: the regulator published the capacity figures [S1]. " * 12,
            encoding="utf-8")
        if self.actors is not None:
            (self.handoff / "actors.json").write_text(json.dumps(self.actors), encoding="utf-8")
        _ManualWatchdog.armed[-1].function()
        yield "2026-09-30T00:00:01+00:00 [stage] extracting\n"

    def poll(self):
        return -9 if self.killed else None

    def wait(self, timeout=None):
        return -9


def _run_killed_during_finalize(monkeypatch, tmp_path, *, actors=None, **run_kwargs):
    """Run the real runner over a child the watchdog kills during finalize; return the
    result (or the raised exception) and the ITEM-14 salvage calls."""
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    monkeypatch.delenv("RESEARCH_EXTRACT_ONLY_SALVAGE", raising=False)
    deerflow_dir = tmp_path / "deer-flow"
    deerflow_dir.mkdir()
    (deerflow_dir / "deerflow_research.py").write_text("# entry\n", encoding="utf-8")
    handoff = tmp_path / "handoff"
    handoff.mkdir()
    monkeypatch.setattr(_po.Config, "DEERFLOW_DIR", str(deerflow_dir))
    monkeypatch.setattr(_po.Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    monkeypatch.setattr(_po, "_sync_deerflow_bridge_if_stale", lambda _p: None)
    monkeypatch.setattr(_po, "_kill_process_group",
                        lambda proc, *a, **k: setattr(proc, "killed", True))
    monkeypatch.setattr(_ManualWatchdog, "armed", [])
    monkeypatch.setattr(_po.threading, "Timer", _ManualWatchdog)
    monkeypatch.setattr(_po.subprocess, "Popen",
                        lambda cmd, **kwargs: _KilledDuringFinalizeProc(handoff, actors))
    salvages = []

    def fake_salvage(deerflow_dir, handoff_dir, prompt, model, depth, language, env, on_progress):
        salvages.append(dict(env))
        return True

    monkeypatch.setattr(_po, "_run_extract_only_salvage", fake_salvage)
    try:
        outcome = _po.DeerFlowResearchRunner.run(
            "Will X happen?", str(handoff), on_progress=lambda _p, _m: None, timeout=900,
            **run_kwargs)
    except RuntimeError as exc:
        outcome = exc
    return outcome, salvages


def test_timed_out_live_child_still_gets_the_extract_only_salvage(monkeypatch, tmp_path):
    """Control: the fake really reaches ITEM-14 (live runs are unchanged)."""
    outcome, salvages = _run_killed_during_finalize(monkeypatch, tmp_path)
    assert isinstance(outcome, dict) and outcome["exit_code"] == 0
    assert len(salvages) == 1 and "RESEARCH_AS_OF" not in salvages[0]


def test_timed_out_hindcast_never_launches_the_legacy_salvage(monkeypatch, tmp_path):
    """--extract-only runs the legacy engine, which ignores RESEARCH_AS_OF: a pinned
    hindcast fails closed instead (a resume lets v3 finish finalize)."""
    outcome, salvages = _run_killed_during_finalize(monkeypatch, tmp_path, as_of=HINDCAST_AS_OF)
    assert isinstance(outcome, RuntimeError)
    assert str(outcome).startswith("hindcast_salvage_refused:")
    assert HINDCAST_AS_OF in str(outcome)
    assert salvages == []


def test_hindcast_killed_after_its_actors_were_written_continues(monkeypatch, tmp_path):
    """Killed after v3 wrote actors.json dated to the pin: nothing to salvage, the
    report and the pinned actors are kept."""
    outcome, salvages = _run_killed_during_finalize(
        monkeypatch, tmp_path, as_of=HINDCAST_AS_OF,
        actors={"as_of_date": HINDCAST_AS_OF, "actors": []})
    assert isinstance(outcome, dict) and outcome["actors"]["as_of_date"] == HINDCAST_AS_OF
    assert salvages == []


@pytest.mark.parametrize("engine", ["v3", "legacy"])
def test_ambient_research_as_of_never_reaches_a_live_child(monkeypatch, tmp_path, engine):
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", engine, raising=False)
    monkeypatch.setattr(_po.Config, "PREDICTION_MARKETS_ENABLED", True, raising=False)
    monkeypatch.setenv("RESEARCH_AS_OF", HINDCAST_AS_OF)

    child = _launch_capturing_child(monkeypatch, tmp_path, timeout=900)

    assert "RESEARCH_AS_OF" not in child["env"]
    assert child["env"]["PREDICTION_MARKETS_ENABLED"] == "true"


def test_live_child_env_is_identical_with_or_without_the_as_of_argument(monkeypatch, tmp_path):
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    envs = []
    for name, extra in (("omitted", {}), ("explicit", {"as_of": None}), ("empty", {"as_of": ""})):
        root = tmp_path / name
        root.mkdir()
        env = _launch_capturing_child(monkeypatch, root, timeout=900, **extra)["env"]
        envs.append({key: value.replace(os.path.realpath(root), "<root>").replace(str(root), "<root>")
                     for key, value in env.items()})
    assert envs[0] == envs[1] == envs[2]
    assert "RESEARCH_AS_OF" not in envs[0]


@pytest.mark.parametrize("config_engine, kwargs", [
    ("v3", {"research_engine": "legacy"}),
    ("legacy", {}),
    ("v3", {"evidence_only": True}),
    ("v3", {"synthesis_manifest_path": "/tmp/evidence_synthesis_manifest.json"}),
])
def test_pinned_as_of_on_a_non_v3_child_fails_before_launch(monkeypatch, tmp_path, config_engine, kwargs):
    """Only v3 honours a pinned as-of: any other child is refused before Popen (a
    launched child would make the fake runner return normally) and before the
    prompt file exists."""
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", config_engine, raising=False)

    with pytest.raises(RuntimeError, match="hindcast_engine_mismatch"):
        _launch_capturing_child(monkeypatch, tmp_path, timeout=900, as_of=HINDCAST_AS_OF, **kwargs)

    assert not list((tmp_path / "handoff").glob(".prompt-*"))


def test_research_stage_passes_the_pinned_as_of_to_the_runner(monkeypatch, tmp_path):
    seen = []
    calls, engines = _drive_research_only_stage(
        monkeypatch, tmp_path, engine="v3", tracks=3,
        options={_hp.HINDCAST_POLICY_OPTION: _hindcast_pin()}, runner_kwargs=seen)
    assert calls == [("single", "outer-track-1")] and engines == ["v3"]
    assert [kwargs["as_of"] for kwargs in seen] == [HINDCAST_AS_OF]


@pytest.mark.parametrize("options", [
    {},
    # An as-of equal to today is pinned but live (TIME-6): no as-of reaches research.
    {_hp.HINDCAST_POLICY_OPTION: _hp.capture_hindcast_policy_v1(
        "2026-09-30", research_engine="v3", today_utc=date(2026, 9, 30))},
])
def test_research_stage_without_a_hindcast_pin_passes_no_as_of(monkeypatch, tmp_path, options):
    seen = []
    _drive_research_only_stage(monkeypatch, tmp_path, engine="v3", tracks=1,
                               options=options, runner_kwargs=seen)
    assert [kwargs["as_of"] for kwargs in seen] == [None]


def test_research_stage_refuses_a_pinned_hindcast_on_the_legacy_engine(monkeypatch, tmp_path):
    """Config drift after admission (or on resume) selects legacy: the stage fails
    closed before any lane runs, with a resumable, named error."""
    seen = []
    calls, engines = _drive_research_only_stage(
        monkeypatch, tmp_path, engine="legacy", tracks=3,
        options={_hp.HINDCAST_POLICY_OPTION: _hindcast_pin()}, runner_kwargs=seen,
        expect_status="failed")
    assert calls == [] and engines == [] and seen == []
    persisted = _po.PipelineManager.load("pipe_topology_legacy_3")
    assert "hindcast_engine_mismatch" in persisted["error"]
    assert persisted["stages"][_po.STAGE_RESEARCH]["status"] == "failed"


def test_research_stage_refuses_a_pinned_hindcast_synthesis_recovery(monkeypatch, tmp_path):
    """A global-synthesis manifest (written only by legacy parallel lanes) in a pinned
    hindcast's handoff dir never reaches the legacy synthesis child, which runs without
    the as-of: the stage fails closed before any spend, with a named, resumable error."""
    manifest = {"evidence_synthesis_manifest.json": "{}"}
    calls, engines = _drive_research_only_stage(
        monkeypatch, tmp_path, engine="v3", tracks=1,
        options={_hp.HINDCAST_POLICY_OPTION: _hindcast_pin()}, handoff_files=manifest,
        expect_status="failed")
    assert calls == [] and engines == []
    persisted = _po.PipelineManager.load("pipe_topology_v3_1")
    assert "hindcast_synthesis_refused" in persisted["error"]
    assert HINDCAST_AS_OF in persisted["error"]
    assert persisted["stages"][_po.STAGE_RESEARCH]["status"] == "failed"

    # Control: the same handoff dir without a pin takes the recovery branch.
    calls, _engines = _drive_research_only_stage(
        monkeypatch, tmp_path / "live", engine="v3", tracks=1, options={},
        handoff_files=manifest)
    assert calls == [("synthesis_recovery", "evidence_synthesis_manifest.json")]


def _anchor_state(**options):
    return _po.PipelineState(pipeline_id="pipe_hindcast_anchor", prompt="Will X happen?",
                             options=dict(options))


def _dated(url, date_str):
    return {"title": "t", "url": url, "tier": "S1", "date": date_str}


def test_hindcast_graph_anchor_is_the_pin_and_records_later_sources():
    pin = _hindcast_pin()
    state = _anchor_state(**{_hp.HINDCAST_POLICY_OPTION: pin})
    sources = [
        _dated("https://early.example/a", "2024-05-20"),
        _dated("https://late.example/a", "2025-03-01"),
        _dated("https://same-day.example/a", HINDCAST_AS_OF),     # not after the as-of
        _dated("https://late.example/a", "2025-03-01"),            # recorded once
        {"title": "undated", "url": "https://undated.example/a"},
        _dated("", "2026-01-01"),                                  # nothing to record
        "not a source",
        _dated("https://month.example/a", "2024-07"),              # a later month counts
    ]

    anchor = _po.PipelineOrchestrator._pin_hindcast_graph_anchor(state, pin, sources)

    assert anchor == datetime(2024, 6, 1, tzinfo=timezone.utc)
    assert state.options["hindcast_violations"] == ["https://late.example/a",
                                                    "https://month.example/a"]
    # The check's coverage is explicit: source rows, the URL-less one included.
    assert state.options["hindcast_source_dates"] == {"dated": 6, "undated": 1, "after_as_of": 4,
                                                     "ambiguous": 0}
    # EVAL-1: the pinned date is the ledger pre-registration anchor.
    assert state.options["as_of_date_validated"] == HINDCAST_AS_OF
    # Without the pin, the R2-RES-7 validator would have rolled the anchor forward.
    rolled, note = _po.PipelineOrchestrator._validate_as_of_date(
        {"as_of_date": HINDCAST_AS_OF}, sources)
    assert rolled.date().isoformat() == "2026-01-01" and "早于最新来源日" in note


def test_hindcast_graph_anchor_rebuild_drops_stale_violations_and_caps_them():
    pin = _hindcast_pin()
    state = _anchor_state(hindcast_violations=["https://stale.example"],
                          as_of_date_validated="2026-01-01")
    _po.PipelineOrchestrator._pin_hindcast_graph_anchor(
        state, pin, [_dated("https://early.example/a", "2024-01-01")])
    assert "hindcast_violations" not in state.options
    assert state.options["as_of_date_validated"] == HINDCAST_AS_OF

    many = [_dated(f"https://late.example/{i}", "2025-01-01") for i in range(80)]
    _po.PipelineOrchestrator._pin_hindcast_graph_anchor(state, pin, many)
    assert state.options["hindcast_violations"] == [
        f"https://late.example/{i}" for i in range(_po.HINDCAST_VIOLATIONS_MAX)]
    assert _po.HINDCAST_VIOLATIONS_MAX == 50
    # The URL list is capped; the count of later-dated rows is not.
    assert state.options["hindcast_source_dates"] == {"dated": 80, "undated": 0, "after_as_of": 80,
                                                     "ambiguous": 0}


def test_hindcast_graph_anchor_records_that_undated_sources_were_not_checked():
    """RESEARCH_SOURCE_DATES is off by default, so v3 sources.json rows carry no date:
    no violations then means "not checked", and the coverage record says so."""
    pin = _hindcast_pin()
    state = _anchor_state()
    undated = [{"title": "t", "url": f"https://undated.example/{i}", "tier": "S1"} for i in range(3)]
    _po.PipelineOrchestrator._pin_hindcast_graph_anchor(state, pin, undated)
    assert "hindcast_violations" not in state.options
    assert state.options["hindcast_source_dates"] == {"dated": 0, "undated": 3, "after_as_of": 0,
                                                     "ambiguous": 0}
    _po.PipelineOrchestrator._pin_hindcast_graph_anchor(state, pin, None)
    assert state.options["hindcast_source_dates"] == {"dated": 0, "undated": 0, "after_as_of": 0,
                                                     "ambiguous": 0}


def test_hindcast_graph_anchor_reads_coarse_source_dates_at_their_precision():
    """A year or month is not its first day: one that starts on or before the pin but
    ends after it is ambiguous (neither cleared nor a violation), one that ends by the
    pin is cleared, and one that starts after it is a violation."""
    pin = _hindcast_pin()
    state = _anchor_state()
    sources = [
        _dated("https://year.example/a", "2024"),                   # 2024: spans the pin
        _dated("https://month.example/a", "2024-06"),               # June 2024: spans it
        _dated("https://cjk-month.example/a", "2024年6月"),          # June 2024: spans it
        _dated("https://may.example/a", "2024-05"),                 # ends before the pin
        _dated("https://last-year.example/a", "2023"),              # ends before the pin
        _dated("https://next-month.example/a", "2024-07"),          # starts after the pin
        # A declared precision widens a date, never narrows it (v3 date_precision).
        dict(_dated("https://declared-month.example/a", "2024-06-01"), date_precision="month"),
        dict(_dated("https://declared-day.example/a", "2024"), date_precision="day"),
        dict(_dated("https://bad-precision.example/a", "2024-05-31"), date_precision="decade"),
    ]

    anchor = _po.PipelineOrchestrator._pin_hindcast_graph_anchor(state, pin, sources)

    assert anchor == datetime(2024, 6, 1, tzinfo=timezone.utc)
    assert state.options["hindcast_violations"] == ["https://next-month.example/a"]
    assert state.options["hindcast_source_dates"] == {"dated": 9, "undated": 0, "after_as_of": 1,
                                                     "ambiguous": 5}
    assert state.options["as_of_date_validated"] == HINDCAST_AS_OF

    # A month or year that ends on the pin is cleared, not ambiguous.
    end_of_june = _hindcast_pin("2024-06-30")
    _po.PipelineOrchestrator._pin_hindcast_graph_anchor(
        state, end_of_june, [_dated("https://month.example/a", "2024-06")])
    assert state.options["hindcast_source_dates"] == {"dated": 1, "undated": 0, "after_as_of": 0,
                                                     "ambiguous": 0}
    new_years_eve = _hindcast_pin("2024-12-31")
    _po.PipelineOrchestrator._pin_hindcast_graph_anchor(
        state, new_years_eve, [_dated("https://year.example/a", "2024")])
    assert state.options["hindcast_source_dates"] == {"dated": 1, "undated": 0, "after_as_of": 0,
                                                     "ambiguous": 0}
    assert "hindcast_violations" not in state.options


@pytest.mark.parametrize("bad_as_of", ["2024-6-1", None, "2999-01-01"])
def test_hindcast_graph_anchor_fails_closed_on_a_bad_pin(bad_as_of):
    pin = dict(_hindcast_pin(), as_of=bad_as_of)
    state = _anchor_state(as_of_date_validated="2024-06-01")
    with pytest.raises(ValueError):
        _po.PipelineOrchestrator._pin_hindcast_graph_anchor(state, pin, [])


class _StopAtIngest(RuntimeError):
    pass


def _drive_graph_stage(monkeypatch, tmp_path, *, options, actors, sources):
    """Run the real ``_run`` over a fresh full pipeline (research and ontology faked)
    up to the graph stage's text ingest, where a sentinel stops the attempt.  Return
    the state and what the graph layer received."""
    monkeypatch.setattr(_po.Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"),
                        raising=False)
    monkeypatch.setattr(_po.Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"), raising=False)
    for name, value in {
        "RESEARCH_ENGINE": "v3",
        "RESEARCH_PARALLEL_TRACKS": 1,
        "REPORT_LINT": False,
        "CAST_RECONCILE": False,
        "EMBED_WARM_AT_RESEARCH": False,
        "PIPELINE_VIZ_ARTIFACTS": False,
        "VALIDATE_AS_OF_DATE": True,
    }.items():
        monkeypatch.setattr(_po.Config, name, value, raising=False)
    for name, replacement in {
        "_start_heartbeat": lambda self, state: None,
        "_init_telemetry_flush": lambda self, state: None,
        "_write_run_manifest": lambda self, state: None,
        "_update_manifest": lambda self, state, stage, **kwargs: None,
        "_record_research_telemetry": lambda self, state, value: None,
        "_maybe_warm_embedder": lambda self, state, actors: None,
        "_surface_research_quality": lambda self, state, handoff_dir: {},
        "_surface_forecast_confidence_penalty": lambda self, state, handoff_dir: None,
        "_flush_run_telemetry": lambda self, state, **kwargs: None,
    }.items():
        monkeypatch.setattr(_po.PipelineOrchestrator, name, replacement)
    monkeypatch.setattr(_po, "_finalize_research_contract", lambda *a, **k: None)
    report = "Evidence-backed research report with citations [S1]. " * 20

    def fake_research(prompt, handoff_dir, **kwargs):
        path = os.path.join(handoff_dir, "research_report.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(report)
        return {"report": report, "report_path": path, "evidence_pack": None,
                "actor_dossier": "", "actors": actors, "sources": sources, "timeline": None,
                "exit_code": 0, "research_telemetry": {}}

    monkeypatch.setattr(_po.DeerFlowResearchRunner, "run", staticmethod(fake_research))
    project = SimpleNamespace(project_id="proj_hindcast", name="Hindcast", files=[],
                              ontology=None, analysis_summary="", status=None,
                              graph_id=None, simulation_requirement="", total_text_length=0)
    monkeypatch.setattr(_po.ProjectManager, "create_project",
                        classmethod(lambda cls, name: project))
    monkeypatch.setattr(_po.ProjectManager, "get_project", classmethod(lambda cls, pid: project))
    monkeypatch.setattr(_po.ProjectManager, "save_project", classmethod(lambda cls, p: None))
    monkeypatch.setattr(_po.ProjectManager, "save_extracted_text",
                        classmethod(lambda cls, pid, text: None))

    class FakeOntologyGenerator:
        def generate(self, **kwargs):
            return {"entity_types": [{"name": "Organization"}], "edge_types": [],
                    "analysis_summary": ""}

    monkeypatch.setattr(_po, "OntologyGenerator", FakeOntologyGenerator)
    seen = {"validator_calls": 0}

    def fake_seed(builder, graph_id, seed_actors, valid_at=None):
        seen["valid_at"] = valid_at
        return 0

    monkeypatch.setattr(_po, "_seed_research_actors", fake_seed)
    monkeypatch.setattr(_po, "_validate_actor_graph_seed_contract", lambda *a, **k: None)
    real_validator = _po.PipelineOrchestrator._validate_as_of_date

    def spy_validator(actors_arg, sources_arg):
        seen["validator_calls"] += 1
        return real_validator(actors_arg, sources_arg)

    monkeypatch.setattr(_po.PipelineOrchestrator, "_validate_as_of_date",
                        staticmethod(spy_validator))

    class FakeGraphBuilder:
        def __init__(self, **kwargs):
            pass

        def create_graph(self, name):
            return "graph_hindcast"

        def set_ontology(self, graph_id, ontology):
            return None

        def add_text_batches(self, graph_id, chunks, batch_size=10, progress_callback=None,
                             reference_time=None):
            seen["reference_time"] = reference_time
            raise _StopAtIngest("STOP_AT_INGEST")

    monkeypatch.setattr(_po, "GraphBuilderService", FakeGraphBuilder)
    pid = "pipe_hindcast_graph"
    _po.PipelineManager.ensure_dirs(pid)
    state = _po.PipelineState(pipeline_id=pid, prompt="Will the ECB cut by the end of 2024?",
                              mode="full", status="running", options=dict(options))
    state.handoff_dir = _po.PipelineManager.handoff_dir(pid)
    _po.PipelineOrchestrator._run(state)
    assert state.status == "failed" and "STOP_AT_INGEST" in (state.error or ""), state.error
    return state, seen


_GRAPH_ACTORS = {"as_of_date": HINDCAST_AS_OF, "central_question": "Will the ECB cut?",
                 "actors": [{"name": "ECB", "type": "Organization"}], "relationships": []}
_GRAPH_SOURCES = [_dated("https://early.example/a", "2024-05-20"),
                  _dated("https://late.example/a", "2025-03-01")]


def test_graph_stage_anchors_a_pinned_hindcast_at_its_as_of(monkeypatch, tmp_path):
    """The real graph stage: the actor seeds and every research chunk are anchored at the
    pin, the later-dated source is recorded (never adopted) and the roll-forward
    validator is not consulted."""
    state, seen = _drive_graph_stage(
        monkeypatch, tmp_path, options={_hp.HINDCAST_POLICY_OPTION: _hindcast_pin()},
        actors=_GRAPH_ACTORS, sources=_GRAPH_SOURCES)

    pinned = datetime(2024, 6, 1, tzinfo=timezone.utc)
    assert seen["valid_at"] == pinned
    assert seen["reference_time"] == pinned
    assert seen["validator_calls"] == 0
    assert state.options["hindcast_violations"] == ["https://late.example/a"]
    assert state.options["hindcast_source_dates"] == {"dated": 2, "undated": 0, "after_as_of": 1,
                                                     "ambiguous": 0}
    assert state.options["as_of_date_validated"] == HINDCAST_AS_OF
    assert "as_of_date_correction" not in state.options


def test_graph_stage_without_a_pin_keeps_the_roll_forward_validator(monkeypatch, tmp_path):
    """Control (R2-RES-7 unchanged): the same inputs without a pin roll the anchor forward
    to the newest source date and record no hindcast fields."""
    state, seen = _drive_graph_stage(monkeypatch, tmp_path, options={},
                                     actors=_GRAPH_ACTORS, sources=_GRAPH_SOURCES)

    rolled = datetime(2025, 3, 1, tzinfo=timezone.utc)
    assert seen["validator_calls"] == 1
    assert seen["valid_at"] == rolled and seen["reference_time"] == rolled
    assert state.options["as_of_date_validated"] == "2025-03-01"
    assert "as_of_date_correction" in state.options
    assert "hindcast_violations" not in state.options
    assert "hindcast_source_dates" not in state.options


# ── TIME-8: the admission pin's point-in-time gates reach only a pinned v3 child ──

_PIT_CONFIG = {"PIT_GATES": True, "PIT_SAME_DAY_POLICY": "include", "PIT_UNDATED_POLICY": "flag",
               "PIT_PROVIDER_DATE_BOUNDS": False, "PIT_SEARCH_OVERFETCH": 3}
_PIT_CHILD_ENV = {"RESEARCH_PIT_GATES": "true", "RESEARCH_PIT_SAME_DAY": "include",
                  "RESEARCH_PIT_UNDATED": "flag", "RESEARCH_PIT_PROVIDER_BOUNDS": "false",
                  "RESEARCH_PIT_OVERFETCH": "3"}


def _set_pit_config(monkeypatch, **values):
    for name, value in values.items():
        monkeypatch.setattr(_po.Config, name, value, raising=False)


def _pit_keys(env):
    return {key: value for key, value in env.items() if key.startswith("RESEARCH_PIT_")}


def test_capture_pins_configs_pit_gates_normalized(monkeypatch):
    _set_pit_config(monkeypatch, **_PIT_CONFIG)
    assert _hindcast_pin()["pit"] == {"gates": True, "same_day": "include", "undated": "flag",
                                      "provider_bounds": False, "overfetch": 3}
    _set_pit_config(monkeypatch, PIT_GATES=False, PIT_SAME_DAY_POLICY="maybe", PIT_UNDATED_POLICY="",
                    PIT_PROVIDER_DATE_BOUNDS=True, PIT_SEARCH_OVERFETCH=9)
    assert _hindcast_pin()["pit"] == {"gates": False, "same_day": "exclude", "undated": "drop",
                                      "provider_bounds": True, "overfetch": 4}


@pytest.mark.parametrize("pit, expected", [
    (None, {}),
    ({}, {}),
    ({"gates": False, "same_day": "include"}, {}),
    ({"gates": "true"}, {}),  # only a real True turns the gates on
    # A pin missing a key reads it as its admission default (provider bounds on).
    ({"gates": True}, {"RESEARCH_PIT_GATES": "true", "RESEARCH_PIT_SAME_DAY": "exclude",
                       "RESEARCH_PIT_UNDATED": "drop", "RESEARCH_PIT_PROVIDER_BOUNDS": "true",
                       "RESEARCH_PIT_OVERFETCH": "1", "RESEARCH_SOURCE_DATES": "true"}),
    ({"gates": True, "provider_bounds": None}, {"RESEARCH_PIT_GATES": "true", "RESEARCH_PIT_SAME_DAY": "exclude",
                                                "RESEARCH_PIT_UNDATED": "drop", "RESEARCH_PIT_PROVIDER_BOUNDS": "true",
                                                "RESEARCH_PIT_OVERFETCH": "1", "RESEARCH_SOURCE_DATES": "true"}),
    # Only a real False turns the provider bound off.
    ({"gates": True, "provider_bounds": "false"}, {"RESEARCH_PIT_GATES": "true", "RESEARCH_PIT_SAME_DAY": "exclude",
                                                   "RESEARCH_PIT_UNDATED": "drop",
                                                   "RESEARCH_PIT_PROVIDER_BOUNDS": "true",
                                                   "RESEARCH_PIT_OVERFETCH": "1", "RESEARCH_SOURCE_DATES": "true"}),
    ({"gates": True, "provider_bounds": False}, {"RESEARCH_PIT_GATES": "true", "RESEARCH_PIT_SAME_DAY": "exclude",
                                                 "RESEARCH_PIT_UNDATED": "drop", "RESEARCH_PIT_PROVIDER_BOUNDS": "false",
                                                 "RESEARCH_PIT_OVERFETCH": "1", "RESEARCH_SOURCE_DATES": "true"}),
    ({"gates": True, "same_day": "include", "undated": "flag", "provider_bounds": False, "overfetch": 3},
     {**_PIT_CHILD_ENV, "RESEARCH_SOURCE_DATES": "true"}),
    ({"gates": True, "same_day": "INCLUDE", "undated": "keep", "provider_bounds": True, "overfetch": "x"},
     {"RESEARCH_PIT_GATES": "true", "RESEARCH_PIT_SAME_DAY": "exclude", "RESEARCH_PIT_UNDATED": "drop",
      "RESEARCH_PIT_PROVIDER_BOUNDS": "true", "RESEARCH_PIT_OVERFETCH": "1", "RESEARCH_SOURCE_DATES": "true"}),
])
def test_pit_research_env_reads_the_pin_strictly(pit, expected):
    assert _hp.pit_research_env(pit) == expected


def test_runner_hands_the_pinned_pit_gates_to_the_v3_child(monkeypatch, tmp_path):
    """The child gets the gates admitted into the pin, not today's Config (changed after
    admission here), and RESEARCH_SOURCE_DATES is forced on over the registry forward."""
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    _set_pit_config(monkeypatch, **_PIT_CONFIG)
    pin = _hindcast_pin()
    _set_pit_config(monkeypatch, PIT_GATES=False, PIT_SAME_DAY_POLICY="exclude", PIT_UNDATED_POLICY="drop",
                    PIT_PROVIDER_DATE_BOUNDS=True, PIT_SEARCH_OVERFETCH=1)
    monkeypatch.setattr(_po.Config, "RESEARCH_SOURCE_DATES", False, raising=False)
    monkeypatch.setenv("RESEARCH_PIT_UNDATED", "drop")
    monkeypatch.setenv("RESEARCH_PIT_STRAY", "x")

    child = _launch_capturing_child(monkeypatch, tmp_path, timeout=900, as_of=HINDCAST_AS_OF, pit=pin["pit"],
                                    actors={"as_of_date": HINDCAST_AS_OF, "actors": []})

    env = child["env"]
    assert _pit_keys(env) == _PIT_CHILD_ENV
    assert env["RESEARCH_SOURCE_DATES"] == "true"
    assert env["RESEARCH_AS_OF"] == HINDCAST_AS_OF


@pytest.mark.parametrize("engine", ["v3", "legacy"])
def test_ambient_pit_env_never_reaches_a_live_child(monkeypatch, tmp_path, engine):
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", engine, raising=False)
    monkeypatch.setattr(_po.Config, "RESEARCH_SOURCE_DATES", False, raising=False)
    for name, value in {**_PIT_CHILD_ENV, "RESEARCH_PIT_STRAY": "x"}.items():
        monkeypatch.setenv(name, value)

    child = _launch_capturing_child(monkeypatch, tmp_path, timeout=900, pit={"gates": True})

    assert _pit_keys(child["env"]) == {}
    if engine == "v3":
        assert child["env"]["RESEARCH_SOURCE_DATES"] == "false"


@pytest.mark.parametrize("pit", [None, {"gates": False, "same_day": "include"}])
def test_a_pin_without_active_gates_sends_no_pit_env(monkeypatch, tmp_path, pit):
    """A pin admitted before TIME-8 (no 'pit') or with the gates off: the hindcast runs
    exactly as TIME-7 left it, whatever the ambient env says."""
    monkeypatch.setattr(_po.Config, "RESEARCH_ENGINE", "v3", raising=False)
    monkeypatch.setattr(_po.Config, "RESEARCH_SOURCE_DATES", False, raising=False)
    monkeypatch.setenv("RESEARCH_PIT_GATES", "true")

    child = _launch_capturing_child(monkeypatch, tmp_path, timeout=900, as_of=HINDCAST_AS_OF, pit=pit,
                                    actors={"as_of_date": HINDCAST_AS_OF, "actors": []})

    assert _pit_keys(child["env"]) == {}
    assert child["env"]["RESEARCH_SOURCE_DATES"] == "false"
    assert child["env"]["RESEARCH_AS_OF"] == HINDCAST_AS_OF


def test_research_stage_passes_the_admission_pins_pit_block(monkeypatch, tmp_path):
    _set_pit_config(monkeypatch, **_PIT_CONFIG)
    pin = _hindcast_pin()
    # Config drift after admission never reaches the launch: the pin decides.
    _set_pit_config(monkeypatch, PIT_GATES=False, PIT_SEARCH_OVERFETCH=1)
    seen = []
    _drive_research_only_stage(monkeypatch, tmp_path, engine="v3", tracks=1,
                               options={_hp.HINDCAST_POLICY_OPTION: pin}, runner_kwargs=seen)
    assert [(kwargs["as_of"], kwargs["pit"]) for kwargs in seen] == [(HINDCAST_AS_OF, pin["pit"])]
    assert seen[0]["pit"]["gates"] is True and seen[0]["pit"]["overfetch"] == 3


@pytest.mark.parametrize("options", [
    {},
    # A pin admitted before TIME-8 carries no 'pit' block: no gates.
    {_hp.HINDCAST_POLICY_OPTION: {key: value for key, value in _hindcast_pin().items() if key != "pit"}},
])
def test_research_stage_without_a_pit_block_passes_no_gates(monkeypatch, tmp_path, options):
    seen = []
    _drive_research_only_stage(monkeypatch, tmp_path, engine="v3", tracks=1, options=options,
                               runner_kwargs=seen)
    assert [kwargs["pit"] for kwargs in seen] == [None]


def test_pit_config_defaults_and_env_example():
    """Defaults: gates on, strict same-day and undated policies, provider bounds on,
    no over-fetch; every knob is documented in .env.example with that default."""
    assert (_po.Config.PIT_GATES, _po.Config.PIT_SAME_DAY_POLICY, _po.Config.PIT_UNDATED_POLICY,
            _po.Config.PIT_PROVIDER_DATE_BOUNDS, _po.Config.PIT_SEARCH_OVERFETCH) == (
        True, "exclude", "drop", True, 1)
    env_example = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    for line in ("# PIT_GATES=true ", "# PIT_SAME_DAY_POLICY=exclude ", "# PIT_UNDATED_POLICY=drop ",
                 "# PIT_PROVIDER_DATE_BOUNDS=true ", "# PIT_SEARCH_OVERFETCH=1 "):
        assert line in env_example, line
