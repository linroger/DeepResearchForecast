import hashlib
import json
from pathlib import Path

import pytest

from scripts.backfill_report_visuals import (
    _PROVENANCE_ISSUE_RE,
    _SCORE_ISSUE_RES,
    _WITHHELD_ISSUE_RE,
    _provenance_issue,
    backfill_one,
    carry_binary_quality,
    drop_irreparable_language_lines,
    ensure_baseline_scenario_label,
    localized_manifest,
    strip_circular_binary_rows,
    strip_generated_visuals,
    synchronize_market_comparison,
)
from app.config import Config
from app.services.forecast_extractor import (
    _binary_quality,
    _binary_withheld_issue,
    extract_binary_forecasts,
)
from app.services.report_agent import ReportAgent, ReportManager
from app.services.report_visualizer import ReportVisualizer

from tests.conftest import FakeLLMClient


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
    assert not (charts / "new.png").exists()
    assert not (report_dir / "viz_manifest.json").exists()
    backups = list(report_dir.glob(".codex-backup-*"))
    assert len(backups) == 1
    failure = json.loads((backups[0] / "replay_failure.json").read_text(encoding="utf-8"))
    assert failure["restored"] is True and failure["error"] == "quality gate failed"


# --------------------------------------------- FU-1: binary_quality keys survive a re-run

def _binaries(n, *, downgraded=()):
    rows = []
    for i in range(n):
        row = {"id": f"F{i + 1}", "statement": f"Grid storage installs exceed {10 + i} GW in 2030",
               "resolution_criteria": "IEA report 2030-12-31", "probability": 0.2 + 0.05 * i,
               "theme": "grid", "criteria_sharp": True}
        if i in downgraded:
            row["source"], row["source_claimed"] = "research-prior", "world-state outcome shares"
        rows.append(row)
    return rows


# A forecast of a market quote rather than of its event: the backfill drops the row.
_CIRCULAR = {"statement": "Polymarket contract price will exceed 50 cents by 2030-12-31",
             "resolution_criteria": "market settles"}
PROVENANCE_2 = ("2 forecast(s) claimed a simulation signal that was never injected into the prompt "
                "— source downgraded to research-prior (see source_claimed)")
ENSEMBLE_LINE = "1 forecast(s) show cross-model disagreement (spread > 0.15): F2"
_EXTRACTOR_ONLY_KEYS = ("world_state_outcome", "needs_review_count", "needs_review_reasons",
                        "needs_review_secondary_count", "market_window_ended_excluded",
                        "llm_truncation_market_trimmed")


def _eval10_quality(binaries):
    """A binary_quality as ReportAgent writes it after EVAL-10: the rebuilt scorecard,
    then the extractor-only keys and lines (withheld line first)."""
    quality = _binary_quality(binaries, min_count=10)
    quality["proposition_consistency"] = {"status": "ok"}
    quality.update({
        "ensemble": {"enabled_models": ["glm"], "low_agreement": ["F2"]},
        "world_state_outcome": {"scenario_shares": {"A": 0.6, "B": 0.4}},
        "needs_review_count": 2, "needs_review_reasons": {"unreadable": 2},
        "needs_review_secondary_count": 1, "market_window_ended_excluded": 1,
        "provenance_downgrades": 2, "llm_truncation_market_trimmed": {"divergence": 1},
    })
    quality["issues"] = (["2 binary probabilities unreadable — withheld, not clamped"]
                         + quality["issues"] + [PROVENANCE_2, ENSEMBLE_LINE])
    return quality


def _replay_harness(tmp_path, monkeypatch, tag, forecast):
    """Stage a primary-only report whose forecast.json holds ``forecast`` and stub the
    chart, citation, audit and PDF steps as the quarantine test above does; returns
    (pipeline_id, report_id, report_dir)."""
    pipelines = tmp_path / tag / "pipelines"
    reports = tmp_path / tag / "reports"
    pipeline_id, report_id = f"pipe_{tag}", f"report_{tag}"
    handoff = pipelines / pipeline_id / "handoff"
    report_dir = reports / report_id
    handoff.mkdir(parents=True)
    report_dir.mkdir(parents=True)
    (pipelines / pipeline_id / "pipeline_state.json").write_text(json.dumps({
        "report_id": report_id, "simulation_id": f"sim_{tag}", "handoff_dir": str(handoff),
    }), encoding="utf-8")
    (report_dir / "full_report.md").write_text(
        "# Forecast\n\n## Outcome\n\nClean primary outcome.\n", encoding="utf-8")
    (report_dir / "meta.json").write_text(json.dumps({"report_id": report_id}), encoding="utf-8")
    (report_dir / "forecast.json").write_text(json.dumps(forecast), encoding="utf-8")

    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(pipelines), raising=False)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports))
    monkeypatch.setattr(ReportVisualizer, "build_all", lambda self, *args: [])
    monkeypatch.setattr(ReportAgent, "_repair_quote_grounding", lambda self, md: (md, 0))
    monkeypatch.setattr(
        ReportAgent, "_finalize_citations_for_publish", lambda self, *args: None)

    def _audit(self, rid, report):
        sha = hashlib.sha256(report.markdown_content.encode("utf-8")).hexdigest()
        return {"hard_passed": True, "markdown_sha256": sha, "publish_gate": {"passed": True}}

    def _export_pdf(cls, rid, force=False, lang=None):
        path = Path(cls._get_report_pdf_path(rid))
        path.write_bytes(b"%PDF-1.4 primary")
        return str(path)

    monkeypatch.setattr(ReportAgent, "_enforce_final_publish_audit", _audit)
    monkeypatch.setattr(ReportManager, "export_pdf", classmethod(_export_pdf))
    return pipeline_id, report_id, report_dir


def test_backfill_keeps_eval10_binary_quality_keys_and_recounts_provenance():
    stored = _binaries(4, downgraded=(0, 3))
    old = _eval10_quality(stored)
    retained = stored[:3]            # F4 (downgraded) dropped as a circular market forecast
    rebuilt = _binary_quality(retained, min_count=10)
    quality = carry_binary_quality(
        old, dict(json.loads(json.dumps(rebuilt)), proposition_consistency={"status": "ok"}), retained)
    for key in _EXTRACTOR_ONLY_KEYS:
        assert quality[key] == old[key], key
    assert quality["count"] == 3 and quality["provenance_downgrades"] == 1
    assert quality["issues"] == (
        ["2 binary probabilities unreadable — withheld, not clamped"] + rebuilt["issues"]
        + [PROVENANCE_2.replace("2 forecast(s)", "1 forecast(s)"), ENSEMBLE_LINE])


def test_backfill_drops_the_provenance_line_when_no_downgraded_row_remains():
    stored = _binaries(4, downgraded=(3,))
    old = _eval10_quality(stored)
    old["provenance_downgrades"] = 1
    old["issues"] = [line.replace("2 forecast(s) claimed", "1 forecast(s) claimed") for line in old["issues"]]
    quality = carry_binary_quality(old, _binary_quality(stored[:3], min_count=10), stored[:3])
    assert quality["provenance_downgrades"] == 0
    assert not any("claimed a simulation signal" in line for line in quality["issues"])
    assert ENSEMBLE_LINE in quality["issues"]


def test_backfill_writes_a_missing_provenance_line_where_the_extractor_puts_it():
    """A non-zero recount always has its line (the extractor writes one whenever the
    count is above zero): after the scorecard lines, before the ensemble line."""
    stored = _binaries(4, downgraded=(0,))
    old = _eval10_quality(stored)
    old["issues"] = [line for line in old["issues"] if line != PROVENANCE_2]
    rebuilt = _binary_quality(stored[:3], min_count=10)
    quality = carry_binary_quality(old, json.loads(json.dumps(rebuilt)), stored[:3])
    assert quality["provenance_downgrades"] == 1
    assert quality["issues"] == (
        [_binary_withheld_issue(2)] + rebuilt["issues"] + [_provenance_issue(1), ENSEMBLE_LINE])


def test_backfill_ignores_malformed_stored_issues_and_ensemble():
    """Only a list of stored issue lines is read (a string is not split into
    characters), and carry_binary_quality never writes ``ensemble``: the caller keeps a
    dict ensemble, so a malformed one stays dropped as before FU-1."""
    rows = _binaries(3)
    rebuilt = _binary_quality(rows, min_count=10)
    quality = carry_binary_quality(
        {"issues": "abc", "ensemble": None}, json.loads(json.dumps(rebuilt)), rows)
    assert quality == rebuilt


def test_backfill_of_a_pre_eval10_binary_quality_is_unchanged():
    """A stored block holding only what the rebuild writes plus proposition_consistency
    and ensemble (both already set by the caller) gives exactly the old result."""
    stored = _binaries(12)
    old = _binary_quality(stored, min_count=10)
    old["proposition_consistency"] = {"status": "stale"}
    old["ensemble"] = {"enabled_models": ["glm"], "low_agreement": []}
    old["issues"] = list(old["issues"]) + ["only 9 binaries (< 10)"]   # a stale scorecard line
    retained = stored[:9]
    expected = _binary_quality(retained, min_count=10)
    expected["proposition_consistency"] = {"status": "fresh"}
    expected["ensemble"] = old["ensemble"]
    got = carry_binary_quality(old, json.loads(json.dumps(expected)), retained)
    assert json.dumps(got) == json.dumps(expected)


def test_carried_line_templates_match_the_extractor_wording():
    """Drift guard: the backfill recognises the extractor's issue lines by copies of
    its f-strings (forecast_extractor has no importable helper for them)."""
    hedged = [{"id": f"F{i}", "probability": 0.5, "theme": "grid", "criteria_sharp": False}
              for i in range(1, 5)]
    lines = _binary_quality(hedged, min_count=10)["issues"]
    assert len(lines) == len(_SCORE_ISSUE_RES) == 6
    for line, pattern in zip(lines, _SCORE_ISSUE_RES, strict=True):
        assert pattern.fullmatch(line), line
    assert _WITHHELD_ISSUE_RE.fullmatch(_binary_withheld_issue(3))
    assert _PROVENANCE_ISSUE_RE.match(_provenance_issue(7)).group(1) == "7"

    # The provenance line as the extractor itself writes it: F1 names a simulation
    # signal that was never injected and is downgraded to research-prior.
    def _reply():
        return {"binary_forecasts": [
            {"id": f"F{i}", "statement": f"Statement {i} resolves by 2027", "probability": p,
             "resolution_criteria": f"metric {i} > 1 by 2027 per BLS", "theme": "t", "source": source}
            for i, (p, source) in enumerate(
                ((0.2, "world-state outcome shares"), (0.7, "research-prior")), 1)]}

    out = extract_binary_forecasts(
        "dossier", FakeLLMClient(json_responses=[_reply() for _ in range(4)]),
        min_count=2, language="English")
    quality = out["binary_quality"]
    assert quality["provenance_downgrades"] == 1
    assert _provenance_issue(1) in quality["issues"]
    for line in quality["issues"]:
        assert line == _provenance_issue(1) or any(r.fullmatch(line) for r in _SCORE_ISSUE_RES), line


def test_replay_of_an_eval10_forecast_json_keeps_its_keys_and_recounts_the_dropped_row(
        tmp_path, monkeypatch):
    """End to end through backfill_one: the circular F4 (which also carried a provenance
    downgrade) is dropped, every extractor-only key survives, the row-dependent counts
    follow the retained rows and the issue lines are rebuilt in the extractor's order."""
    stored = _binaries(4, downgraded=(0, 3))
    stored[3].update(_CIRCULAR)
    old = _eval10_quality(stored)
    pipeline_id, report_id, report_dir = _replay_harness(
        tmp_path, monkeypatch, "eval10",
        {"binary_forecasts": stored, "binary_quality": old, "scenarios": []})

    result = backfill_one(pipeline_id, report_id, apply=True)

    forecast = json.loads((report_dir / "forecast.json").read_text(encoding="utf-8"))
    retained = forecast["binary_forecasts"]
    quality = forecast["binary_quality"]
    assert [row["id"] for row in retained] == ["F1", "F2", "F3"]
    for key in ("ensemble",) + _EXTRACTOR_ONLY_KEYS:
        assert quality[key] == old[key], key
    assert quality["count"] == 3 and quality["provenance_downgrades"] == 1
    assert "only 4 binaries (< 10)" in old["issues"]
    assert quality["issues"] == (
        [_binary_withheld_issue(2)] + _binary_quality(retained, min_count=10)["issues"]
        + [_provenance_issue(1), ENSEMBLE_LINE])

    # A second replay of the backfilled report is stable. _backup names its directory
    # to the second, so the first run's backup is moved aside first.
    Path(result["backup"]).rename(report_dir / "first-replay-backup")
    backfill_one(pipeline_id, report_id, apply=True)
    again = json.loads((report_dir / "forecast.json").read_text(encoding="utf-8"))
    assert again["binary_forecasts"] == retained and again["binary_quality"] == quality


@pytest.mark.parametrize("ensemble", [{"enabled_models": ["glm"], "low_agreement": []}, None])
def test_replay_of_a_pre_eval10_forecast_json_writes_the_same_bytes(tmp_path, monkeypatch, ensemble):
    """A forecast.json finalized before EVAL-10 (the rebuild's keys, proposition_consistency
    and ensemble) replays to the same bytes as the pre-FU-1 path, in which the rebuilt
    block was written as is; a malformed null ensemble is still dropped."""
    import scripts.backfill_report_visuals as module

    rows = _binaries(4)
    rows[3].update(_CIRCULAR)
    quality = _binary_quality(rows, min_count=10)
    quality.update(proposition_consistency={"status": "stale"}, ensemble=ensemble)
    forecast = {"binary_forecasts": rows, "binary_quality": quality, "scenarios": []}

    def _replay(tag):
        pipeline_id, report_id, report_dir = _replay_harness(tmp_path, monkeypatch, tag, forecast)
        backfill_one(pipeline_id, report_id, apply=True)
        return (report_dir / "forecast.json").read_bytes()

    current = _replay("current")
    monkeypatch.setattr(module, "carry_binary_quality", lambda old, rebuilt, retained: rebuilt)
    assert _replay("pre_fu1") == current
    replayed = json.loads(current)["binary_quality"]
    assert replayed["count"] == 3 and ("ensemble" in replayed) == (ensemble is not None)
