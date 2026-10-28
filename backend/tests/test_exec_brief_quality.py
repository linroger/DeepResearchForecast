"""F1: direct, offline grade/disclosure rendering and byte-exact legacy output.

Only unrelated official-indicator readers are stubbed. Renderers, forecast JSON
reads and pipeline-health reads use production code; no app is started.
"""
from copy import deepcopy
import json

import pytest

from app.services import exec_brief as eb


_MD = "# Fixture\n\n## Executive summary\n\nA measured forecast.\n"
_DISCLOSURES = [
    "Citation coverage is 70%, below the publication target.",
    "Binary forecasts cluster near 50%; sharpness is limited.",
]
_LEGACY_BRIEFS = {
    "en": """# Executive Brief — Fixture

**Forecast question:** Fixture

## Thesis

A measured forecast.

## Top binary forecasts

_No structured forecast available._

## Key scenario probabilities

- **Base** — 60%
- **Residual** — 40%

## What to watch

_No structured forecast available._

{honesty}_Deterministically extracted from the full report — no model generation._
""",
    "zh": """# 高管简报 — Fixture

**预测问题:** Fixture

## 核心论点

A measured forecast.

## 头部二元预测

_暂无结构化预测数据。_

## 关键情景概率

- **Base** — 60%
- **Residual** — 40%

## 观察指标

_暂无结构化预测数据。_

{honesty}_全部从成稿确定性抽取——无模型生成。_
""",
}
_LEGACY_DIGEST = """# {title}: Fixture

- Base — **60%**
- Residual — **40%**

**{links}:** [brief](/api/report/report_quality/exec-brief) · [brief.pdf](/api/report/report_quality/exec-brief.pdf) · [digest](/api/report/report_quality/digest) · [full report](/api/report/report_quality/download) · [report.pdf](/api/report/report_quality/pdf)
"""
_TEXT = {
    "en": {
        "grade": "Forecast quality grade", "notes": "Quality notes",
        "honesty": "Honesty note", "pass": "forecast quality gate passed",
        "fail": "forecast quality gate not passed (citation coverage 70%)",
        "digest": "Digest", "links": "Links",
    },
    "zh": {
        "grade": "预测质量等级", "notes": "质量说明", "honesty": "诚实声明",
        "pass": "预测质量门通过", "fail": "预测质量门未通过 (引用覆盖率 70%)",
        "digest": "速览", "links": "链接",
    },
}


@pytest.fixture
def report_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(eb, "_official_summaries", lambda *args: [])
    monkeypatch.setattr(eb, "_official_rows", lambda *args: {})
    folder = tmp_path / "reports" / "report_quality"
    folder.mkdir(parents=True)
    return folder


def _forecast():
    return {
        "headline": "Fixture",
        "scenarios": [
            {"name": "Base", "probability": 0.6},
            {"name": "Residual", "probability": 0.4},
        ],
    }


def _render(forecast, report_dir, lang):
    return (
        eb.ExecBriefBuilder._render_brief(
            "report_quality", str(report_dir), _MD, forecast, {}, lang, ""),
        eb.ExecBriefBuilder._render_digest(
            "report_quality", _MD, forecast, {}, lang, report_dir=str(report_dir)),
    )


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("state", ["missing", "empty", "passed", "failed", "binary_failed"])
def test_legacy_output_is_byte_identical_without_additive_fields(report_dir, lang, state):
    forecast = _forecast()
    expected_note = ""
    if state == "empty":
        forecast.update(quality={}, binary_quality={})
    elif state in {"passed", "failed", "binary_failed"}:
        forecast["quality"] = {"passed": state != "failed", "citation_coverage": 0.7}
        forecast["binary_quality"] = {"passed": state == "passed"}
        expected_note = _TEXT[lang]["pass" if state == "passed" else "fail"]
    honesty = f"> **{_TEXT[lang]['honesty']}:** {expected_note}\n\n" if expected_note else ""
    brief, digest = _render(forecast, report_dir, lang)
    assert brief.encode("utf-8") == _LEGACY_BRIEFS[lang].format(honesty=honesty).encode("utf-8")
    assert digest.encode("utf-8") == _LEGACY_DIGEST.format(
        title=_TEXT[lang]["digest"], links=_TEXT[lang]["links"]).encode("utf-8")


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("grade", ["A", "B", "C"])
@pytest.mark.parametrize("binary_quality", [None, {"passed": False}, {"sharpness": {"stdev": 0.02}}])
def test_persisted_grade_and_disclosures_render_deterministically(
        report_dir, lang, grade, binary_quality):
    forecast = _forecast()
    forecast["quality"] = {
        "grade": grade, "disclosures": _DISCLOSURES,
        "passed": True, "citation_coverage": 0.7,
    }
    if binary_quality is not None:
        forecast["binary_quality"] = binary_quality
    path = report_dir / "forecast.json"
    path.write_text(json.dumps(forecast, ensure_ascii=False), encoding="utf-8")
    persisted = path.read_bytes()
    loaded = eb._read_json(str(path))
    before = deepcopy(loaded)
    brief, digest = _render(loaded, report_dir, lang)
    assert _render(loaded, report_dir, lang) == (brief, digest)
    assert loaded == before
    assert path.read_bytes() == persisted
    honesty = next(line for line in brief.splitlines() if line.startswith("> **"))
    assert f"{_TEXT[lang]['grade']}: {grade}" in honesty
    assert _TEXT[lang]["pass"] in honesty
    assert _TEXT[lang]["fail"].split(" (")[0] not in honesty
    assert f"**{_TEXT[lang]['grade']}:** {grade}" in digest
    expected_notes = f"## {_TEXT[lang]['notes']}\n\n" + "\n".join(
        f"- {disclosure}" for disclosure in _DISCLOSURES)
    for output in (brief, digest):
        assert expected_notes in output
        assert all(output.count(disclosure) == 1 for disclosure in _DISCLOSURES)
    assert digest.index(expected_notes) < digest.index(f"**{_TEXT[lang]['links']}:**")


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_grade_only_does_not_invent_a_gate_result_or_notes(report_dir, lang):
    forecast = _forecast()
    forecast["quality"] = {"grade": "A", "disclosures": []}
    brief, digest = _render(forecast, report_dir, lang)
    assert f"> **{_TEXT[lang]['honesty']}:** {_TEXT[lang]['grade']}: A\n" in brief
    assert f"**{_TEXT[lang]['grade']}:** A" in digest
    assert all(_TEXT[lang]["notes"] not in output for output in (brief, digest))


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_disclosures_without_grade_are_complete_ordered_single_lines(report_dir, lang):
    long_note = "A source limitation requires explicit disclosure. " * 8 + "END."
    forecast = _forecast()
    forecast["quality"] = {"disclosures": [
        "  引用覆盖率不足。\n请谨慎解读。  ", None, "", " \t", 7, {}, long_note,
    ]}
    brief, digest = _render(forecast, report_dir, lang)
    for output in (brief, digest):
        assert f"## {_TEXT[lang]['notes']}\n\n- 引用覆盖率不足。 请谨慎解读。\n- {long_note}\n" in output
        assert _TEXT[lang]["grade"] not in output
        assert _TEXT[lang]["fail"].split(" (")[0] not in output


@pytest.mark.parametrize("grade,disclosures", [
    (None, None), ("D", "not a list"), ([], {}), ({}, [None, 1, False, " "]),
])
def test_malformed_additive_fields_do_not_change_legacy_output(report_dir, grade, disclosures):
    forecast = _forecast()
    forecast.update(quality={"passed": True}, binary_quality={"passed": True})
    before = _render(forecast, report_dir, "en")
    forecast["quality"].update(grade=grade, disclosures=disclosures)
    assert _render(forecast, report_dir, "en") == before


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_grade_preserves_explicit_gate_failure_and_pipeline_health(report_dir, lang):
    (report_dir / "telemetry.json").write_text(
        json.dumps({"totals": {"run_id": "pipe_quality"}}), encoding="utf-8")
    pipeline = report_dir.parent.parent / "pipelines" / "pipe_quality"
    pipeline.mkdir(parents=True)
    (pipeline / "pipeline_state.json").write_text(json.dumps({"options": {
        "pipeline_health": {"status": "degraded", "stages": {
            "run": {"health": "hollow", "organic_actions": 0}}},
        "safety_policy_v1": {"simulation_forecast_effect": "diagnostic_only"},
    }}), encoding="utf-8")
    forecast = _forecast()
    forecast["quality"] = {"grade": "C", "passed": False, "citation_coverage": 0.7}
    forecast["binary_quality"] = {"passed": True}
    note = eb._build_honesty_note(forecast, str(report_dir), eb._LABELS[lang])
    assert _TEXT[lang]["fail"] in note
    assert f"{_TEXT[lang]['grade']}: C" in note
    assert "diagnostic_only" in note and "hollow" in note
    assert ("pipeline health degraded" if lang == "en" else "管线健康 degraded") in note


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("fallback_key", ["publication", "publication_quality"])
def test_publication_is_a_fallback_without_overriding_quality(report_dir, lang, fallback_key):
    forecast = _forecast()
    forecast[fallback_key] = {"grade": "C", "disclosures": _DISCLOSURES}
    if fallback_key == "publication":
        forecast["publication_quality"] = {"grade": "B", "disclosures": ["Obsolete alias note."]}
    brief, digest = _render(forecast, report_dir, lang)
    assert f"{_TEXT[lang]['grade']}: C" in brief
    assert f"**{_TEXT[lang]['grade']}:** C" in digest
    assert all(_DISCLOSURES[0] in output for output in (brief, digest))
    assert all("Obsolete alias note." not in output for output in (brief, digest))
    forecast["quality"] = {"grade": "A", "disclosures": [], "passed": True}
    brief, digest = _render(forecast, report_dir, lang)
    assert f"{_TEXT[lang]['grade']}: A" in brief
    assert f"**{_TEXT[lang]['grade']}:** A" in digest
    assert all(_TEXT[lang]["notes"] not in output for output in (brief, digest))


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_clean_publication_does_not_revive_older_alias_disclosures(report_dir, lang):
    forecast = _forecast()
    forecast["publication"] = {"grade": "A", "disclosures": []}
    forecast["publication_quality"] = {"grade": "C", "disclosures": _DISCLOSURES}
    brief, digest = _render(forecast, report_dir, lang)
    assert f"{_TEXT[lang]['grade']}: A" in brief
    assert f"**{_TEXT[lang]['grade']}:** A" in digest
    assert all(_TEXT[lang]["notes"] not in output for output in (brief, digest))


_HEALTH_TEXT = {
    "en": {
        "heading": "Input health", "markets": "Prediction markets", "news": "News",
        "official_data": "Official data", "provider": "Provider", "unknown": "unknown",
        "stale": "stale", "fresh": "fresh", "offline": "offline",
        "empty": "empty", "disabled": "disabled",
        "as_of": "As of", "rows": "Rows", "reason": "Reason",
    },
    "zh": {
        "heading": "输入健康", "markets": "预测市场", "news": "新闻",
        "official_data": "官方数据", "provider": "提供方", "unknown": "未知",
        "stale": "过期", "fresh": "新鲜", "offline": "离线",
        "empty": "无数据", "disabled": "已禁用",
        "as_of": "截至", "rows": "行数", "reason": "原因",
    },
}


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_inputs_health_uses_only_the_consumed_snapshot(report_dir, lang):
    forecast = _forecast()
    forecast["quality"] = {"grade": "C", "passed": True, "disclosures": _DISCLOSURES}
    # Intentionally old dates: the display must not recompute health at render time.
    forecast["inputs_health"] = {
        "markets": {"status": "stale", "as_of": "2026-10-01T00:00:00Z", "rows": 2,
                    "reason": "Consumed last-good snapshot; live lookup failed."},
        "news": {"status": "offline", "as_of": "2026-10-02T00:00:00Z", "rows": 0,
                 "reason": "No news entered the forecast."},
        "official_data": {"status": "fresh", "as_of": "2026-10-03T00:00:00Z", "rows": 9,
                          "reason": "已使用官方数据。"},
        # Provider is missing, even though unrelated report data looks healthy.
    }
    (report_dir / "inputs_health.json").write_text(json.dumps({
        "provider": {"status": "fresh", "rows": 999, "reason": "UNCONSUMED"},
    }), encoding="utf-8")
    (report_dir / "forecast.json").write_text(json.dumps(forecast), encoding="utf-8")
    consumed = eb._read_json(str(report_dir / "forecast.json"))
    original = deepcopy(consumed)
    brief, digest = _render(consumed, report_dir, lang)
    words = _HEALTH_TEXT[lang]
    for output in (brief, digest):
        assert f"## {words['heading']}\n" in output
        for source in ("markets", "news", "official_data"):
            entry = forecast["inputs_health"][source]
            assert f"- **{words[source]}:** {words[entry['status']]}" in output
            assert f"**{words['as_of']}:** {entry['as_of']}" in output
            assert f"**{words['rows']}:** {entry['rows']}" in output
            assert entry["reason"] in output
        assert f"- **{words['provider']}:** {words['unknown']}" in output
        assert "UNCONSUMED" not in output and "999" not in output
    honesty = next(line for line in brief.splitlines() if line.startswith("> **"))
    assert f"{words['heading']}:" in honesty
    assert f"{words['markets']} {words['stale']}" in honesty
    assert f"{words['provider']} {words['unknown']}" in honesty
    assert _TEXT[lang]["pass"] in honesty
    assert consumed == original
    assert _render(consumed, report_dir, lang) == (brief, digest)


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("snapshot", [None, {}, [], "healthy", {"markets": {"rows": 12}}])
def test_missing_inputs_are_explicitly_unknown(report_dir, lang, snapshot):
    forecast = _forecast()
    forecast["inputs_health"] = snapshot
    words = _HEALTH_TEXT[lang]
    for output in _render(forecast, report_dir, lang):
        for source in ("markets", "news", "official_data", "provider"):
            assert f"- **{words[source]}:** {words['unknown']}" in output
        assert words["fresh"] not in output


def test_malformed_health_details_do_not_become_health_or_row_counts(report_dir):
    forecast = _forecast()
    forecast["inputs_health"] = {
        "markets": {"status": True, "as_of": [], "rows": True, "reason": {}},
        "news": {"status": "unexpected", "rows": -1},
        "official_data": {"status": [], "rows": 1.5},
        "provider": "healthy",
    }
    for output in _render(forecast, report_dir, "en"):
        assert output.count("**Rows:** unknown") == 4
        assert output.count("**As of:** unknown") == 4
        assert "healthy" not in output and "unexpected" not in output


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("status", ["fresh", "stale", "offline", "unknown", "empty", "disabled"])
def test_all_snapshot_statuses_are_localized_without_reclassification(report_dir, lang, status):
    forecast = _forecast()
    forecast["inputs_health"] = {
        "markets": {"status": status, "as_of": "2026-01-01T00:00:00Z", "rows": 0,
                    "reason": "frozen_status_receipt"},
    }
    words = _HEALTH_TEXT[lang]
    for output in _render(forecast, report_dir, lang):
        assert f"- **{words['markets']}:** {words[status]}" in output
        assert "frozen_status_receipt" in output
