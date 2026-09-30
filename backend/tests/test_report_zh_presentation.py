"""Chinese report variants: chart titles and PDF labels read in Chinese.

Chart images keep the builder's English title as Markdown alt text, which pandoc
prints as the figure caption ("Figure 1: Binary Forecasts — P(yes)"), and the
LaTeX template labels ("Contents", "Figure", "Table") are English by default.
"""

from __future__ import annotations

import os
import re

from app.services import report_visualizer as rv
from app.services.report_agent import ReportManager

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(_BACKEND)


def test_chart_alt_text_is_localized_for_chinese_variants_only():
    md = (
        "![Scenario Probabilities](charts/scenario_probabilities.png)\n\n"
        "*情景概率*\n\n"
        "![A custom figure](charts/custom.png)\n\n"
        "```\n![Event Timeline](charts/timeline_lanes.png)\n```\n"
    )
    zh = rv.localize_chart_alt_text(md, "zh")
    assert "![情景概率](charts/scenario_probabilities.png)" in zh
    assert "![A custom figure](charts/custom.png)" in zh
    assert "```\n![Event Timeline](charts/timeline_lanes.png)\n```" in zh
    assert rv.localize_chart_alt_text(md, "en") == md


def _builder_titles() -> set:
    source = open(rv.__file__, encoding="utf-8").read()
    titles = set(re.findall(
        r'(?:_attempt|_fallback)\(\s*"[a-z_]+",\s*"[a-z_]+",\s*"([^"]+)"', source
    ))
    titles |= set(re.findall(r'"title": "([^"{]+)"', source))
    return titles


def test_every_builder_title_has_a_chinese_title():
    titles = _builder_titles()
    assert "Scenario Probabilities" in titles and "Model vs Market" in titles
    assert titles <= set(rv.CHART_TITLES_ZH), titles - set(rv.CHART_TITLES_ZH)


def test_frontend_gallery_captions_match_the_backend_table():
    js = open(os.path.join(_REPO, "frontend", "src", "utils", "vizManifest.js"),
              encoding="utf-8").read()
    block = js[js.index("ZH_CHART_CAPTIONS"):js.index("})", js.index("ZH_CHART_CAPTIONS"))]
    frontend = dict(re.findall(r"'([^']+)':\s*'([^']+)'", block))
    assert frontend == rv.CHART_TITLES_ZH


def _pandoc_command(monkeypatch, tmp_path, markdown: str) -> list:
    import subprocess

    captured = {}

    def _run(cmd, **_kwargs):
        captured["cmd"] = cmd
        with open(cmd[cmd.index("-o") + 1], "wb") as handle:
            handle.write(b"%PDF-1.4\n")

        class _Done:
            returncode = 0
            stderr = b""
        return _Done()

    monkeypatch.setattr(ReportManager, "_resolve_pandoc", classmethod(lambda cls: ("pandoc", "xelatex")))
    monkeypatch.setattr(ReportManager, "_resolve_pdf_fonts", classmethod(lambda cls: {
        "main": {"family": "Main"}, "cjk": {"family": "CJK"}, "mono": None,
    }))
    monkeypatch.setattr(subprocess, "run", _run)
    ok = ReportManager._export_pdf_pandoc(
        "report_zh_labels", markdown, str(tmp_path), str(tmp_path / "out.pdf")
    )
    assert ok is True
    return captured["cmd"]


def test_chinese_pdf_uses_chinese_latex_labels(monkeypatch, tmp_path):
    zh = _pandoc_command(monkeypatch, tmp_path, "# 量子计算\n\n中文正文，图表与目录。\n")
    assert "toc-title=目录" in zh
    assert any("\\renewcommand{\\figurename}{图}" in arg for arg in zh)
    en = _pandoc_command(monkeypatch, tmp_path, "# Quantum\n\nEnglish body text.\n")
    assert not any("toc-title" in arg or "figurename" in arg for arg in en)


def test_bilingual_variant_gets_chinese_chart_titles(tmp_path, monkeypatch):
    import json

    from app.services.report_agent import Report, ReportAgent, ReportStatus

    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))

    def _to_zh(text: str) -> str:
        # Leave image lines alone (as GLM did), translate prose word by word.
        return "\n".join(
            line if line.lstrip().startswith("![") else re.sub(
                r"(?<![A-Za-z0-9⟦])[A-Za-z][A-Za-z'-]*", "译", line
            )
            for line in text.split("\n")
        )

    class Translator:
        model = "fake"
        provider = "fake"

        def chat(self, messages=None, temperature=0.0, max_tokens=4096, tier="strong", **_kw):
            system, user = messages[0]["content"], messages[-1]["content"]
            if "same alphabetic keys" in system:
                return json.dumps({k: _to_zh(v) for k, v in json.loads(user).items()},
                                  ensure_ascii=False)
            return _to_zh(user)

        def chat_json(self, messages=None, **_kw):
            return {}

    rid = "report_zh_chart_titles"
    md = (
        "# Outlook\n\n## Charts\n\n"
        "![Scenario Probabilities](charts/scenario_probabilities.png)\n\n"
        "The base case holds at 60% overall.\n"
    )
    report = Report(report_id=rid, simulation_id="sim", graph_id="graph",
                    simulation_requirement="req", status=ReportStatus.COMPLETED,
                    markdown_content=md)
    ReportManager.save_report(report)
    agent = ReportAgent.__new__(ReportAgent)
    agent.llm = Translator()
    agent.output_language = "English"
    agent._forecast_spine = None
    agent._generate_bilingual_report(rid, report)
    with open(ReportManager._get_report_translation_path(rid, "zh"), encoding="utf-8") as handle:
        variant = handle.read()
    assert "![情景概率](charts/scenario_probabilities.png)" in variant
