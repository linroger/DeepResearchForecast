"""DELIV-1 执行交付物（exec brief + digest）的离线测试。

覆盖（全部无 LLM / 无网络 / 无真实 pandoc——pandoc 路径 mock）：
  * ExecBriefBuilder.build —— 合成报告目录（sections + forecast.json，形状对齐真实
    uploads/reports/report_90f1f75991f2/forecast.json）确定性产出 exec_brief.md + digest.md：
    问题 / 3 句论点 / TOP 二元预测表 / 情景概率 / 图引用 / 观察指标 / 诚实声明；
  * 二元预测表 ≤8 行、按承重度（|p-0.5|）降序；
  * 概率 ±ensemble.spread、市场锚 Δ 单元格；
  * 缺工件（无 forecast.json）degrade——不崩、给占位；
  * 双语——meta.translations[] + full_report.zh.md → exec_brief.zh.md（中文小节标签）；
  * mtime 缓存——源更新才重建；
  * build_pdf —— pandoc(no-toc) mock + PyMuPDF 回退 mock，mtime 缓存；
  * 端点 —— /exec-brief、/exec-brief.pdf、/digest 的 200/404、mtime 复用、REPORT_EXEC_BRIEF 关闭。
"""

import hashlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.services.exec_brief import (  # noqa: E402
    ExecBriefBuilder,
    _detect_lang,
    _extract_date,
    _extract_thesis,
    _first_sentences,
)
from app.services.report_agent import (  # noqa: E402
    Report,
    ReportManager,
    ReportStatus,
)


# ─────────────────────────── fixtures ───────────────────────────

# 一份英文成稿：H1 + 「## Framework Overview」执行摘要段（论点来源）+ 情景章节。
_FULL_MD_EN = """# Future Forecast Report: 2026 US Midterms

## Part 1 — Binary Forecasts

| # | Forecast | Prob. |
|---|---|---|
| F1 | Democrats win the House. | 82% |

## Part 2 — Framework & Synthesis

### Framework Overview

The 2026 midterm forecast is built on a four-scenario spine. A structurally unfavorable
environment for the incumbent party is the base condition. The cycle's resolution is dominated
by discrete shocks between August and November.

## Scenario A — Modest Wave

Body text for scenario A.
"""

# forecast.json 形状对齐真实 report_90f1f75991f2/forecast.json：headline / scenarios(含 p_low/p_high)
# / binary_forecasts(含 market_anchor / ensemble.spread / criteria_sharp / resolution_criteria 日期)
# / quality / binary_quality / citation_audit。
def _forecast_fixture(n_binaries=10):
    scenarios = [
        {"name": "Modest Democratic wave", "probability": 0.46, "p_low": 0.42, "p_high": 0.50,
         "summary": "soft tilt"},
        {"name": "Clean Democratic wave", "probability": 0.24, "summary": "tail"},
        {"name": "Narrow Republican hold", "probability": 0.18, "summary": "counter"},
        {"name": "Mixed split", "probability": 0.12, "summary": "asymmetric"},
    ]
    binaries = []
    # 造 n 条二元预测，概率从 0.82 递减到接近 0.5，保证承重度排序可判定；给几条市场锚 + ensemble。
    probs = [0.82, 0.78, 0.25, 0.72, 0.68, 0.32, 0.36, 0.62, 0.55, 0.45, 0.51, 0.49]
    for i in range(n_binaries):
        p = probs[i % len(probs)]
        b = {
            "id": f"F{i+1}",
            "statement": f"Forecast statement number {i+1} resolves on November 3, 2026.",
            "probability": p,
            "resolution_criteria": "AP race call by November 3, 2026 shows the outcome.",
            "resolution_source": "AP race calls",
            "horizon_year": 2026,
            "criteria_sharp": (i % 2 == 0),
        }
        if i == 0:  # 头号预测带 ensemble 离散
            b["ensemble"] = {"models": ["m1", "m2"], "probs": [0.80, 0.84],
                             "pooled": 0.82, "spread": 0.04}
        if i == 9:  # 一条带市场锚（低承重，落在 digest 的最大分歧里）
            b["market_anchor"] = {"market_id": "MKT-1", "implied_yes_prob": 0.52,
                                  "divergence": -0.07}
        binaries.append(b)
    return {
        "headline": "Democrats net 1-3 Senate seats; credible clean-wave tail.",
        "horizon": "2026-11-03",
        "scenarios": scenarios,
        "binary_forecasts": binaries,
        "key_uncertainties": ["Trump approval trajectory through October 2026."],
        "confidence": "low",
        "quality": {"passed": False, "citation_coverage": 0.24, "issues": ["coverage low"]},
        "binary_quality": {"count": n_binaries, "passed": False},
        "citation_audit": {"coverage": 0.24},
    }


@pytest.fixture
def reports_tmp(tmp_path, monkeypatch):
    """把 ReportManager.REPORTS_DIR 钉进 tmp，隔离磁盘副作用。"""
    d = tmp_path / "reports"
    d.mkdir()
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(d))
    return str(d)


def _make_report_dir(reports_tmp, rid="report_test", full_md=_FULL_MD_EN,
                     forecast=None, translations=None, requirement="Forecast the 2026 US midterms."):
    """构造一个合成报告目录：meta.json（via save_report）+ full_report.md + forecast.json。"""
    report = Report(report_id=rid, simulation_id="sim_x", graph_id="g",
                    simulation_requirement=requirement,
                    status=ReportStatus.COMPLETED, markdown_content=full_md)
    if translations is not None:
        report.translations = translations
    ReportManager.save_report(report)
    folder = ReportManager._get_report_folder(rid)
    with open(os.path.join(folder, "full_report.md"), "w", encoding="utf-8") as f:
        f.write(full_md)
    if forecast is not None:
        with open(os.path.join(folder, "forecast.json"), "w", encoding="utf-8") as f:
            json.dump(forecast, f, ensure_ascii=False)
    _write_passing_audit(rid, full_md)
    return rid, folder


def _write_passing_audit(rid, markdown, lang=None):
    markdown_sha = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    primary = ReportManager.publication_status(rid) if lang else None
    source_lang = str((primary or {}).get("language") or "en")
    source_sha = str((primary or {}).get("markdown_sha256") or "")
    with open(
        ReportManager._get_report_final_audit_path(rid, lang),
        "w",
        encoding="utf-8",
    ) as handle:
        audit = {
            "policy_version": 3,
            "hard_passed": True,
            "hard_issues": [],
            "markdown_sha256": markdown_sha,
            "publish_gate": {"enabled": True, "passed": True},
            "structured_forecast": {"required": False, "valid": True},
            "citation_artifacts": {"required": False, "passed": True},
        }
        if lang:
            audit.update({
                "report_id": rid,
                "language": lang,
                "source_language": source_lang,
                "source_markdown_sha256": source_sha,
            })
        json.dump(audit, handle)
    if lang:
        with open(
            ReportManager._get_report_citations_path(rid, lang),
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump({
                "report_id": rid,
                "language": lang,
                "source_language": source_lang,
                "source_markdown_sha256": source_sha,
                "markdown_sha256": markdown_sha,
                "markers": [],
            }, handle)
        ReportManager._persist_translation_metadata(rid, [{
            "report_id": rid,
            "lang": lang,
            "source_lang": source_lang,
            "source_markdown_sha256": source_sha,
            "markdown_sha256": markdown_sha,
            "path": f"full_report.{lang}.md",
            "available": True,
        }])


# ─────────────────────────── 纯函数 ───────────────────────────

def test_detect_lang():
    assert _detect_lang("Hello world, this is English.") == "en"
    assert _detect_lang("这是一份中文预测报告，覆盖多个情景。") == "zh"
    assert _detect_lang("") == "en"


def test_extract_date_prefers_full_then_iso_then_month_year():
    assert _extract_date("AP call by November 3, 2026.")[1] == "November 3, 2026"
    assert _extract_date("resolves 2026-11-03 per clerk")[1] == "2026-11-03"
    assert _extract_date("reading for December 2026 reports")[1] == "December 2026"
    assert _extract_date("no date here") is None


def test_first_sentences_strips_markup_and_caps():
    txt = "**First** sentence [S1-a]. Second one [依据: X]. Third [link](u). Fourth."
    out = _first_sentences(txt, 3)
    assert out.count(".") == 3
    assert "S1-a" not in out and "依据" not in out and "**" not in out


def test_extract_thesis_from_framework_overview():
    thesis = _extract_thesis(_FULL_MD_EN, outline_summary="", lang="en", n=3)
    assert "four-scenario spine" in thesis
    # 3 句
    assert thesis.count(".") <= 3


def test_extract_thesis_falls_back_to_outline_summary():
    md_no_summary = "# Title\n\n## Random Section\n\nSome body prose without summary heading.\n"
    thesis = _extract_thesis(md_no_summary, outline_summary="The clean summary sentence.", lang="en")
    assert "clean summary" in thesis


# ─────────────────────────── build: 产物 & 内容 ───────────────────────────

def test_build_produces_brief_and_digest(reports_tmp):
    rid, folder = _make_report_dir(reports_tmp, forecast=_forecast_fixture())
    out = ExecBriefBuilder.build(rid, folder, force=True)
    assert "exec_brief" in out and "digest" in out
    brief = open(out["exec_brief"], encoding="utf-8").read()
    digest = open(out["digest"], encoding="utf-8").read()
    # 问题 + 论点 + 表头 + 情景 + 观察 + 诚实声明
    assert "Forecast question" in brief
    assert "four-scenario spine" in brief  # 论点
    assert "Top binary forecasts" in brief
    assert "Modest Democratic wave" in brief
    assert "What to watch" in brief
    assert "Honesty note" in brief and "quality gate not passed" in brief
    # digest：标题 + 情景要点 + 头号预测 + 最大市场分歧 + 链接
    assert "Digest:" in digest
    assert "Top forecast" in digest
    assert "Biggest market divergence" in digest and "-7pt" in digest
    assert f"/api/report/{rid}/exec-brief" in digest


def test_forecast_table_caps_at_8_and_sorted_by_conviction(reports_tmp):
    rid, folder = _make_report_dir(reports_tmp, forecast=_forecast_fixture(n_binaries=12))
    out = ExecBriefBuilder.build(rid, folder, force=True)
    brief = open(out["exec_brief"], encoding="utf-8").read()
    # 抽出预测表数据行（以 '| Forecast statement' 开头）
    rows = [ln for ln in brief.splitlines() if ln.startswith("| Forecast statement")]
    assert len(rows) == 8  # 上限 8
    # 第一行应是承重度最高（p=0.82 → |p-0.5|=0.32）
    assert "82%" in rows[0]
    assert "±4%" in rows[0]  # ensemble spread 渲染


def test_missing_forecast_degrades(reports_tmp):
    """无 forecast.json：仍产出简报（论点来自成稿），表格/情景/观察为占位，绝不崩。"""
    rid, folder = _make_report_dir(reports_tmp, forecast=None)
    out = ExecBriefBuilder.build(rid, folder, force=True)
    assert "exec_brief" in out
    brief = open(out["exec_brief"], encoding="utf-8").read()
    assert "four-scenario spine" in brief  # 论点仍抽到
    assert "No structured forecast available" in brief  # 表格占位


def test_missing_full_report_uses_meta_markdown(reports_tmp):
    """无 full_report.md：回退 meta.markdown_content，不崩。"""
    rid, folder = _make_report_dir(reports_tmp, forecast=_forecast_fixture())
    os.remove(os.path.join(folder, "full_report.md"))
    out = ExecBriefBuilder.build(rid, folder, force=True)
    assert "exec_brief" in out
    brief = open(out["exec_brief"], encoding="utf-8").read()
    assert "four-scenario spine" in brief


# ─────────────────────────── 双语 ───────────────────────────

def test_bilingual_emits_translation_brief(reports_tmp):
    """meta.translations[] + full_report.zh.md → exec_brief.zh.md（中文小节标签、论点从中文成稿抽取）。"""
    rid, folder = _make_report_dir(
        reports_tmp, forecast=_forecast_fixture(),
        translations=[{"lang": "zh", "path": "full_report.zh.md"}],
    )
    zh_md = ("# 未来预测报告：2026 美国中期选举\n\n## 执行摘要\n\n"
             "本预测建立在四情景骨架之上。对执政党结构性不利是基准条件。"
             "选举结果由八月至十一月的离散冲击主导。\n\n## 情景 A\n\n正文。\n")
    with open(os.path.join(folder, "full_report.zh.md"), "w", encoding="utf-8") as f:
        f.write(zh_md)
    out = ExecBriefBuilder.build(rid, folder, force=True)
    assert "exec_brief.zh" in out
    zh_brief = open(out["exec_brief.zh"], encoding="utf-8").read()
    assert "高管简报" in zh_brief  # 中文标签
    assert "核心论点" in zh_brief
    assert "四情景骨架" in zh_brief  # 论点来自中文成稿
    assert "头部二元预测" in zh_brief


# ─────────────────────────── mtime 缓存 ───────────────────────────

def test_mtime_cache_no_rebuild_then_rebuild(reports_tmp):
    rid, folder = _make_report_dir(reports_tmp, forecast=_forecast_fixture())
    out = ExecBriefBuilder.build(rid, folder)
    brief_path = out["exec_brief"]
    m1 = os.path.getmtime(brief_path)
    # 源未变 → 不重建（mtime 不变）
    ExecBriefBuilder.build(rid, folder)
    assert os.path.getmtime(brief_path) == m1
    # 令 full_report.md 变新 → 触发重建
    os.utime(os.path.join(folder, "full_report.md"), (m1 + 10, m1 + 10))
    ExecBriefBuilder.build(rid, folder)
    assert os.path.getmtime(brief_path) >= m1 + 10 or os.path.getmtime(brief_path) > m1


def test_disabled_flag_returns_empty(reports_tmp, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_EXEC_BRIEF", False, raising=False)
    rid, folder = _make_report_dir(reports_tmp, forecast=_forecast_fixture())
    assert ExecBriefBuilder.build(rid, folder) == {}
    assert not os.path.exists(ExecBriefBuilder.brief_path(folder))


# ─────────────────────────── PDF（pandoc mock + PyMuPDF 回退 mock）───────────────────────────

def test_build_pdf_via_pandoc_mock(reports_tmp, monkeypatch):
    rid, folder = _make_report_dir(reports_tmp, forecast=_forecast_fixture())
    ExecBriefBuilder.build(rid, folder, force=True)

    seen = {}

    def _fake_pandoc(cls, report_id, md, folder_, pdf_path):
        seen["md"] = md
        seen["pdf_path"] = pdf_path
        with open(pdf_path, "wb") as fh:
            fh.write(b"%PDF-1.4 exec-brief")
        return True

    monkeypatch.setattr(Config, "REPORT_PDF_EXPORT", True, raising=False)
    monkeypatch.setattr(ExecBriefBuilder, "_export_pdf_pandoc_no_toc", classmethod(_fake_pandoc))
    # This test isolates renderer selection/cache behavior with synthetic bytes.
    monkeypatch.setattr(ReportManager, "_validate_pdf_content", lambda *a: (True, {}))

    pdf = ExecBriefBuilder.build_pdf(rid, folder)
    assert pdf and pdf.endswith("exec_brief.pdf")
    assert os.path.exists(pdf)
    # mtime 缓存：源未变 → 第二次命中不重建（pandoc 不再被调）
    seen.clear()
    pdf2 = ExecBriefBuilder.build_pdf(rid, folder)
    assert pdf2 == pdf and "md" not in seen


def test_build_pdf_falls_back_to_pymupdf(reports_tmp, monkeypatch):
    rid, folder = _make_report_dir(reports_tmp, forecast=_forecast_fixture())
    ExecBriefBuilder.build(rid, folder, force=True)

    monkeypatch.setattr(Config, "REPORT_PDF_EXPORT", True, raising=False)
    # pandoc 路径失败
    monkeypatch.setattr(ExecBriefBuilder, "_export_pdf_pandoc_no_toc",
                        classmethod(lambda cls, *a, **k: False))

    def _fake_pymupdf(cls, md, folder_, pdf_path):
        with open(pdf_path, "wb") as fh:
            fh.write(b"%PDF-1.4 pymupdf")
        return True

    monkeypatch.setattr(ReportManager, "_export_pdf_pymupdf", classmethod(_fake_pymupdf))
    # This renderer is synthetic; real content validation has separate coverage.
    monkeypatch.setattr(ReportManager, "_validate_pdf_content", lambda *a: (True, {}))
    pdf = ExecBriefBuilder.build_pdf(rid, folder)
    assert pdf and os.path.exists(pdf)


def test_build_pdf_disabled_returns_none(reports_tmp, monkeypatch):
    rid, folder = _make_report_dir(reports_tmp, forecast=_forecast_fixture())
    ExecBriefBuilder.build(rid, folder, force=True)
    monkeypatch.setattr(Config, "REPORT_EXEC_BRIEF", False, raising=False)
    assert ExecBriefBuilder.build_pdf(rid, folder) is None


# ─────────────────────────── 端点 ───────────────────────────

@pytest.fixture
def client(reports_tmp, monkeypatch):
    from app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_api_exec_brief_and_digest(client, reports_tmp):
    rid, folder = _make_report_dir(reports_tmp, forecast=_forecast_fixture())
    r = client.get(f"/api/report/{rid}/exec-brief")
    assert r.status_code == 200
    assert "Top binary forecasts" in r.get_data(as_text=True)

    d = client.get(f"/api/report/{rid}/digest")
    assert d.status_code == 200
    assert "Digest:" in d.get_data(as_text=True)

    # 未知报告 → 404
    assert client.get("/api/report/report_missing/exec-brief").status_code == 404


def test_api_exec_brief_lang_param(client, reports_tmp):
    rid, folder = _make_report_dir(
        reports_tmp, forecast=_forecast_fixture(),
        translations=[{"lang": "zh", "path": "full_report.zh.md"}],
    )
    zh_md = "# 中文报告\n\n## 执行摘要\n\n中文论点第一句。第二句。第三句。\n"
    with open(os.path.join(folder, "full_report.zh.md"), "w", encoding="utf-8") as f:
        f.write(zh_md)
    _write_passing_audit(rid, zh_md, "zh")
    r = client.get(f"/api/report/{rid}/exec-brief?lang=zh")
    assert r.status_code == 200
    assert "高管简报" in r.get_data(as_text=True)
    # 非法 lang → 主语言（英文）200
    r2 = client.get(f"/api/report/{rid}/exec-brief?lang=fr")
    assert r2.status_code == 200
    assert "Executive Brief" in r2.get_data(as_text=True)


def test_api_exec_brief_disabled_404(client, reports_tmp, monkeypatch):
    monkeypatch.setattr(Config, "REPORT_EXEC_BRIEF", False, raising=False)
    rid, folder = _make_report_dir(reports_tmp, forecast=_forecast_fixture())
    assert client.get(f"/api/report/{rid}/exec-brief").status_code == 404
    assert client.get(f"/api/report/{rid}/digest").status_code == 404


def test_api_exec_brief_pdf_mock(client, reports_tmp, monkeypatch):
    rid, folder = _make_report_dir(reports_tmp, forecast=_forecast_fixture())
    zh_md = "# 中文报告\n\n## 执行摘要\n\n中文正文。\n"
    with open(os.path.join(folder, "full_report.zh.md"), "w", encoding="utf-8") as f:
        f.write(zh_md)
    _write_passing_audit(rid, zh_md, "zh")

    captured = {}

    def _fake_build_pdf(cls, report_id, report_dir, lang=None, force=False):
        captured["lang"] = lang
        p = ExecBriefBuilder.pdf_path(report_dir, lang)
        with open(p, "wb") as fh:
            fh.write(b"%PDF-1.4 fake")
        return p

    monkeypatch.setattr(ExecBriefBuilder, "build_pdf", classmethod(_fake_build_pdf))
    r = client.get(f"/api/report/{rid}/exec-brief.pdf")
    assert r.status_code == 200
    assert r.data.startswith(b"%PDF")
    assert captured["lang"] is None
    # ?lang=zh 透传
    client.get(f"/api/report/{rid}/exec-brief.pdf?lang=zh")
    assert captured["lang"] == "zh"


def test_api_exec_brief_mtime_cache_reuse(client, reports_tmp, monkeypatch):
    """端点惰性构建 + 复用：源不变时不重复重写简报（mtime 稳定）。"""
    rid, folder = _make_report_dir(reports_tmp, forecast=_forecast_fixture())
    r1 = client.get(f"/api/report/{rid}/exec-brief")
    assert r1.status_code == 200
    m1 = os.path.getmtime(ExecBriefBuilder.brief_path(folder))
    r2 = client.get(f"/api/report/{rid}/exec-brief")
    assert r2.status_code == 200
    assert os.path.getmtime(ExecBriefBuilder.brief_path(folder)) == m1
