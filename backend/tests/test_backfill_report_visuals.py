import hashlib
import json
from pathlib import Path

import pytest

from scripts.backfill_report_visuals import (
    backfill_one,
    drop_irreparable_language_lines,
    ensure_baseline_scenario_label,
    localized_manifest,
    strip_circular_binary_rows,
    strip_generated_visuals,
    synchronize_market_comparison,
)
from app.config import Config
from app.services.report_agent import ReportAgent, ReportManager
from app.services.report_visualizer import ReportVisualizer


def test_offline_language_repair_drops_mixed_prose_but_keeps_refs_and_assets():
    md = (
        "# Forecast\n\n"
        "Clean English outcome.\n\n"
        "研究证据显示 this sentence is broken.\n\n"
        "| Metric | Value |\n|---|---|\n| 市场规模 | $1T |\n\n"
        "![中文图题](charts/scenario.png)\n\n"
        "## References\n- [S1] 中文原始标题 — https://example.com\n"
    )

    out, removed = drop_irreparable_language_lines(md, "English")

    assert removed == 3
    assert "研究证据显示" not in out
    assert "| — | $1T |" in out
    assert "![Visualization](charts/scenario.png)" in out
    assert "中文原始标题" in out  # citation metadata is intentionally preserved


def test_baseline_label_uses_existing_modal_scenario_without_probability_change():
    forecast = {"scenarios": [
        {"name": "Structural Supercycle (Modal)", "probability": 0.6},
        {"name": "Deep bear", "probability": 0.4},
    ]}

    change = ensure_baseline_scenario_label(forecast)

    assert change == (
        "Structural Supercycle (Modal)",
        "Baseline / Status Quo — Structural Supercycle (Modal)",
    )
    assert [row["probability"] for row in forecast["scenarios"]] == [0.6, 0.4]
    assert ensure_baseline_scenario_label(forecast) is None


def test_strip_generated_visuals_removes_annex_and_inline_legacy_blocks():
    md = """# Report

## Actors

Intro.

<!-- viz:charts/actor_network.mmd -->
**Actor Network**

```mermaid
graph TD
A-->B
```

Actor analysis continues.

## Visual Annex

_Generated figures._

<!-- viz:charts/timeline.mmd -->
**Timeline**

```mermaid
timeline
```

<!-- viz:charts/scenario.png -->
![Scenario](charts/scenario.png)

*Scenario*

## Conclusion

Outcome.
"""

    out = strip_generated_visuals(md)

    assert "viz:" not in out and "```mermaid" not in out
    assert "Visual Annex" not in out and "charts/scenario.png" not in out
    assert "Intro." in out and "Actor analysis continues." in out and "Outcome." in out


def test_strip_generated_visuals_is_idempotent_without_visuals():
    md = "# Report\n\n## Outcome\n\nText.\n"
    assert strip_generated_visuals(md) == md


def test_strip_circular_binary_rows_removes_only_selected_id_and_refreshes_summary():
    md = (
        "| # | Forecast | Prob. | Criteria | Theme |\n"
        "|---|---|---|---|---|\n"
        "| F1 | Real outcome | 80% | metric by 2028 | real |\n"
        "| F2 | Market contract resolves YES | 16% | market settles | circular |\n\n"
        "_2 forecasts; 2 high-conviction (≥70% or ≤30%); 2 with objective criteria._\n"
    )
    out, removed = strip_circular_binary_rows(md, ["F2"])
    assert removed == 1
    assert "| F2 |" not in out and "| F1 |" in out
    assert "_1 forecasts; 1 high-conviction" in out


def test_strip_circular_binary_rows_refreshes_bilingual_summary_from_quality():
    md = (
        "| # | 预测 | 概率 | 标准 | 主题 |\n"
        "|---|---|---|---|---|\n"
        "| F1 | 真实结果 | 80% | 指标 | real |\n\n"
        "_共 13 项预测；其中 7 项为高确信度预测（≥70% 或 ≤30%）；"
        "12 项具备客观判定标准。_\n"
    )
    quality = {"count": 1, "conviction_count": 1, "sharp_criteria_count": 0}

    out, removed = strip_circular_binary_rows(md, [], quality=quality)

    assert removed == 0
    assert "_共 1 项预测；其中 1 项为高确信度预测" in out
    assert "0 项具备客观判定标准" in out


def test_summary_refresh_does_not_consume_later_same_line_emphasis():
    md = (
        "| F1 | Real outcome | 80% | metric | real |\n"
        "_2 forecasts; 2 high-conviction; 2 with objective criteria._ _keep me_\n"
    )

    out, _ = strip_circular_binary_rows(
        md, [], quality={"count": 1, "conviction_count": 1, "sharp_criteria_count": 1})

    assert "_keep me_" in out


def test_synchronize_market_comparison_rebuilds_embedded_and_standalone(tmp_path):
    forecast = {
        "binary_forecasts": [
            {
                "id": "F1", "statement": "Real outcome", "probability": 0.7,
                "adjustment_rationale": "Market price is 50%, with weaker base rates.",
                "market_anchor": {
                    "market_id": "m1", "question": "Will the real event occur?",
                    "implied_yes_prob": 0.5, "price_at_research": 0.5,
                    "divergence": -0.4,
                },
            },
        ],
        "market_comparison": {
            "anchored_count": 2,
            "comparisons": [{"forecast_id": "F1"}, {"forecast_id": "F2"}],
        },
    }
    (tmp_path / "market_comparison.json").write_text(
        json.dumps(forecast["market_comparison"]), encoding="utf-8")

    comparison = synchronize_market_comparison(tmp_path, forecast)

    assert comparison is not None and comparison["anchored_count"] == 1
    assert [row["forecast_id"] for row in comparison["comparisons"]] == ["F1"]
    assert comparison["comparisons"][0]["divergence"] == 0.2
    assert forecast["binary_forecasts"][0]["market_anchor"]["divergence"] == 0.2
    assert forecast["market_comparison"] == comparison
    persisted = json.loads((tmp_path / "market_comparison.json").read_text(encoding="utf-8"))
    assert persisted == comparison


def test_synchronize_market_comparison_removes_stale_copies_without_anchors(tmp_path):
    forecast = {
        "binary_forecasts": [{"id": "F1", "statement": "Real outcome", "probability": 0.7}],
        "market_comparison": {
            "anchored_count": 1,
            "comparisons": [{"forecast_id": "REMOVED"}],
        },
    }
    standalone = tmp_path / "market_comparison.json"
    standalone.write_text(json.dumps(forecast["market_comparison"]), encoding="utf-8")

    comparison = synchronize_market_comparison(tmp_path, forecast)

    assert comparison is None
    assert "market_comparison" not in forecast
    assert not standalone.exists()


def test_synchronize_market_comparison_derives_missing_divergence(tmp_path):
    forecast = {
        "binary_forecasts": [{
            "id": "F1", "statement": "Real outcome", "probability": 0.31,
            "market_anchor": {
                "market_id": "m1", "question": "Will it happen?",
                "implied_yes_prob": 0.18,
            },
        }],
    }

    comparison = synchronize_market_comparison(tmp_path, forecast)

    assert comparison["comparisons"][0]["divergence"] == 0.13
    assert comparison["comparisons"][0]["exceeds_10pp"] is True
    assert forecast["binary_forecasts"][0]["market_anchor"]["divergence"] == 0.13


def test_localized_manifest_translates_reader_caption_without_mutating_input():
    manifest = [{
        "id": "actor_network", "title": "Actor Relationship Network",
        "caption": "Actor Relationship Network", "path": "charts/a.html",
    }]

    localized = localized_manifest(manifest, "Chinese")

    assert localized[0]["caption"] == "关键行为者关系网络"
    assert manifest[0]["caption"] == "Actor Relationship Network"


def test_backfill_quarantines_invalid_legacy_translation_without_deleting_backup_prose(
        tmp_path, monkeypatch):
    import scripts.backfill_report_visuals as module

    pipelines = tmp_path / "pipelines"
    reports = tmp_path / "reports"
    pipeline_id = "pipe_translation_guard"
    report_id = "report_translation_guard"
    pipeline_dir = pipelines / pipeline_id
    report_dir = reports / report_id
    handoff = pipeline_dir / "handoff"
    handoff.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    (pipeline_dir / "pipeline_state.json").write_text(json.dumps({
        "report_id": report_id,
        "simulation_id": "sim_translation_guard",
        "handoff_dir": str(handoff),
    }), encoding="utf-8")
    primary = "# Forecast\n\n## Outcome\n\nClean primary outcome.\n"
    legacy = (
        "# 预测\n\n## 结果\n\n这是不可删除的旧译文正文。 [S99]\n\n"
        "**来源标签**\n\n- [S99] 内部推演记号\n"
    )
    (report_dir / "full_report.md").write_text(primary, encoding="utf-8")
    (report_dir / "full_report.zh.md").write_text(legacy, encoding="utf-8")
    (report_dir / "full_report.zh.pdf").write_bytes(b"%PDF-1.4 stale")
    stale_provenance = '{"schema": "drf.figure_provenance/v1", "block_sha256": "old"}'
    (report_dir / "figure_provenance.json").write_text(stale_provenance, encoding="utf-8")
    (report_dir / "meta.json").write_text(json.dumps({
        "report_id": report_id,
        "translations": [{
            "lang": "zh", "source_lang": "en", "path": "full_report.zh.md",
            "chars": len(legacy), "translation_quality": "ok",
        }],
    }), encoding="utf-8")

    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(pipelines), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports))
    monkeypatch.setattr(ReportVisualizer, "build_all", lambda self, *args: [])
    monkeypatch.setattr(
        ReportAgent, "_repair_quote_grounding", lambda self, md: (md, 0))
    monkeypatch.setattr(
        ReportAgent, "_finalize_citations_for_publish", lambda self, *args: None)

    def _primary_audit(self, rid, report):
        sha = hashlib.sha256(report.markdown_content.encode("utf-8")).hexdigest()
        return {
            "hard_passed": True, "markdown_sha256": sha,
            "publish_gate": {"passed": True},
        }

    def _variant_audit(self, rid, source_md, variant_md, *args):
        assert legacy.strip() in variant_md
        sha = hashlib.sha256(variant_md.encode("utf-8")).hexdigest()
        return ({
            "report_id": rid, "language": "zh", "audited_at": "now",
            "markdown_sha256": sha, "hard_passed": False,
            "issues": ["legacy citation namespace does not match primary"],
        }, {})

    monkeypatch.setattr(ReportAgent, "_enforce_final_publish_audit", _primary_audit)
    monkeypatch.setattr(ReportAgent, "_audit_translation_variant", _variant_audit)

    calls = []
    original_drop = module.drop_irreparable_language_lines

    def _count_drop(md, language):
        calls.append((md, language))
        return original_drop(md, language)

    monkeypatch.setattr(module, "drop_irreparable_language_lines", _count_drop)

    def _export_pdf(cls, rid, force=False, lang=None):
        assert lang is None  # invalid translation never reaches PDF export
        path = Path(cls._get_report_pdf_path(rid))
        path.write_bytes(b"%PDF-1.4 primary")
        return str(path)

    monkeypatch.setattr(ReportManager, "export_pdf", classmethod(_export_pdf))

    result = backfill_one(pipeline_id, report_id, apply=True)

    backup = Path(result["backup"])
    assert (backup / "full_report.zh.md").read_text(encoding="utf-8") == legacy
    assert (backup / "full_report.zh.pdf").read_bytes() == b"%PDF-1.4 stale"
    # REPORT-9: the re-audit measured no verified-figures block, so the old sidecar,
    # which describes the pre-replay bytes, is gone (and kept in the backup).
    assert (backup / "figure_provenance.json").read_text(encoding="utf-8") == stale_provenance
    assert not (report_dir / "figure_provenance.json").exists()
    assert not (report_dir / "full_report.zh.md").exists()
    assert not (report_dir / "full_report.zh.pdf").exists()
    assert len(calls) == 1 and calls[0][1] == "English"  # primary only
    meta = json.loads((report_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["translations"] == []
    unavailable = meta["unavailable_translations"][0]
    assert unavailable["lang"] == "zh" and unavailable["available"] is False
    assert unavailable["backup_path"].endswith("full_report.zh.md")
    assert [row["language"] for row in result["pdf_exports"]] == ["primary"]


def test_backfill_failure_restores_entire_pre_replay_bundle(tmp_path, monkeypatch):
    pipelines = tmp_path / "pipelines"
    reports = tmp_path / "reports"
    pipeline_id = "pipe_replay_rollback"
    report_id = "report_replay_rollback"
    pipeline_dir = pipelines / pipeline_id
    report_dir = reports / report_id
    handoff = pipeline_dir / "handoff"
    charts = report_dir / "charts"
    handoff.mkdir(parents=True)
    charts.mkdir(parents=True)
    (pipeline_dir / "pipeline_state.json").write_text(json.dumps({
        "report_id": report_id,
        "simulation_id": "sim_replay_rollback",
        "handoff_dir": str(handoff),
    }), encoding="utf-8")
    original_md = "# Forecast\n\nOriginal publish candidate.\n"
    original_meta = {"report_id": report_id, "status": "completed", "sentinel": "original"}
    (report_dir / "full_report.md").write_text(original_md, encoding="utf-8")
    (report_dir / "meta.json").write_text(json.dumps(original_meta), encoding="utf-8")
    (charts / "original.png").write_bytes(b"original-chart")
    original_provenance = '{"schema": "drf.figure_provenance/v1", "block_sha256": "original"}'
    (report_dir / "figure_provenance.json").write_text(original_provenance, encoding="utf-8")

    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(pipelines), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports))

    def _build_all(self, rid, folder, artifacts):
        target = Path(folder) / "charts"
        (target / "new.png").write_bytes(b"new-chart")
        (Path(folder) / "viz_manifest.json").write_text("[]", encoding="utf-8")
        return []

    def _stabilize(self, rid, report):
        report.markdown_content = "# Forecast\n\nMutated replay bytes.\n"
        return {"stable": True, "lint": {"changed": False, "leakage_flags": 0}}

    monkeypatch.setattr(ReportVisualizer, "build_all", _build_all)
    monkeypatch.setattr(ReportAgent, "_repair_quote_grounding", lambda self, md: (md, 0))
    monkeypatch.setattr(ReportAgent, "_stabilize_publish_markdown", _stabilize)
    monkeypatch.setattr(
        ReportAgent,
        "_enforce_final_publish_audit",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("quality gate failed")),
    )

    with pytest.raises(RuntimeError, match="quality gate failed"):
        backfill_one(pipeline_id, report_id, apply=True)

    assert (report_dir / "full_report.md").read_text(encoding="utf-8") == original_md
    assert json.loads((report_dir / "meta.json").read_text(encoding="utf-8")) == original_meta
    assert (charts / "original.png").read_bytes() == b"original-chart"
    assert (report_dir / "figure_provenance.json").read_text(encoding="utf-8") == original_provenance
    assert not (charts / "new.png").exists()
    assert not (report_dir / "viz_manifest.json").exists()
    backups = list(report_dir.glob(".codex-backup-*"))
    assert len(backups) == 1
    failure = json.loads((backups[0] / "replay_failure.json").read_text(encoding="utf-8"))
    assert failure["restored"] is True and failure["error"] == "quality gate failed"
