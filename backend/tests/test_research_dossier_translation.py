"""Research-dossier translation: section order, funding rounds, integrity retries.

Every Chinese translation of the quantum-2040 dossier (pipe_6c4190b31f0b) was
withheld, deterministically:

* A dossier carries a Visual Annex after its References.  Lint-before-audit
  re-appended References at the end, so the heading sequence never matched.
* Chinese lint deleted every sentence containing 轮次 as simulation-round
  leakage — including 融资轮次 ("funding rounds") — so the translation lost
  those sentences' numbers and citations and failed number/citation parity.
"""

from __future__ import annotations

import re
import json

from model_translation_fakes import model_protocol

from app.services import report_lint
from app.services.report_agent import ReportAgent
from test_translation_dates import GlmLikeTranslator, _glm_like

_DOSSIER = (
    "# Quantum computing outlook\n\n"
    "## Private investment\n\n"
    "Venture funding reached a record in 2025 [S63]. "
    "Chinese rounds grew larger again in 2024–2026 after a post-2022 lull [S70].\n\n"
    "## References\n\n"
    "1. [S63] QED-C State of the Industry — qed-c.org, 2026, https://qed-c.org/report\n"
    "2. [S70] China funding tracker — example.com, 2026, https://example.com/china\n\n"
    "## Visual Annex\n\n"
    "### Event Timeline\n\n"
    "Milestones are plotted on the timeline below.\n"
)


def _worker(llm):
    worker = ReportAgent.__new__(ReportAgent)
    worker.llm = llm
    worker.output_language = "English"
    worker._forecast_spine = None
    return worker


def _headings(markdown: str) -> list:
    return re.findall(r"(?m)^(#{1,6}) ", markdown)


class RealRoundsTranslator(GlmLikeTranslator):
    """Renders "rounds" as the real Chinese word, like GLM does (融资轮次)."""

    def _render(self, value):
        return super()._render(value).replace(_glm_like("rounds"), "融资轮次")


def test_references_keep_their_place_when_a_visual_annex_follows_them():
    result = _worker(GlmLikeTranslator()).translate_research_markdown(_DOSSIER)
    assert result["available"] is True, result["audit"]["issues"]
    translated = result["translated_md"]
    assert _headings(translated) == _headings(_DOSSIER)
    assert translated.index("## 参考来源") < translated.index("### ")


def test_model_led_default_avoids_legacy_reference_reattachment(monkeypatch):
    """Parsed whole blocks retain References position without editorial reattachment."""
    monkeypatch.setattr(
        ReportAgent,
        "_reattach_translation_references",
        classmethod(
            lambda _cls, _document, body, refs: body.rstrip() + "\n\n" + refs.rstrip() + "\n"
        ),
    )
    result = _worker(GlmLikeTranslator()).translate_research_markdown(_DOSSIER)
    assert result["available"] is True, result["audit"]["issues"]
    assert result["audit"]["fact_fidelity"]["passed"] is True
    assert _headings(result["translated_md"]) == _headings(_DOSSIER)
    assert result["translated_md"].index("## 参考来源") < result["translated_md"].index("### ")


def test_reattach_appends_when_the_trailing_section_is_gone():
    document = "# T\n\n## A\n\nbody\n\n## References\n\n1. [S1] x\n\n## Annex\n\nannex\n"
    body, refs, _heading = ReportAgent._translation_reference_parts(document)
    assert ReportAgent._reattach_translation_references(document, body, refs) == document
    # Lint dropped the annex: nothing to anchor on, so References go last.
    rebuilt = ReportAgent._reattach_translation_references(
        document, "# T\n\n## A\n\nbody\n", refs
    )
    assert rebuilt.rstrip().endswith("1. [S1] x")


def test_a_funding_rounds_sentence_survives_the_chinese_translation():
    result = _worker(RealRoundsTranslator()).translate_research_markdown(_DOSSIER)
    assert result["available"] is True, result["audit"]["issues"]
    assert "融资轮次" in result["translated_md"]
    assert "[S70]" in result["translated_md"]


def test_model_led_default_avoids_legacy_rounds_lint_rewrites(monkeypatch):
    """The model-led publication audit does not run the old destructive prose lint."""
    patterns = [
        (name, re.compile(r"轮次") if name == "sim_mechanics_zh" else pattern)
        for name, pattern in report_lint.LEAKAGE_PATTERNS
    ]
    monkeypatch.setattr(report_lint, "LEAKAGE_PATTERNS", patterns)
    result = _worker(RealRoundsTranslator()).translate_research_markdown(_DOSSIER)
    assert result["available"] is True, result["audit"]["issues"]
    assert "融资轮次" in result["translated_md"]
    assert "2024–2026" in result["translated_md"] and "[S70]" in result["translated_md"]
    assert result["audit"]["fact_fidelity"]["passed"] is True


def test_chinese_lint_keeps_real_world_rounds_and_removes_simulation_rounds():
    def kept(sentence: str) -> bool:
        markdown = "# 标题\n\n## 部分\n\n前一句保持不变 [S1]。" + sentence + "\n"
        out, _report = report_lint.lint_report(markdown, "Chinese", mode="final")
        return sentence[:8] in out

    assert kept("中国的融资轮次在 2024–2026 年间再度扩大 [S70]。")
    assert kept("双方已进行三个谈判轮次，仍未达成协议 [S2]。")
    assert not kept("模拟中，第 3 轮产生 48 次动作。")
    assert not kept("在推演的后期轮次中，各方立场趋同。")
    assert not kept("第 5 轮次的共识明显增强。")
    assert not kept("智能体逐轮调整报价。")


def test_dossier_sections_get_one_targeted_model_repair_after_rejected_source_echo():
    """A rejected section gets one source-aware model repair, never a prose-slot cascade."""
    class RefusesUntilTold(GlmLikeTranslator):
        def __init__(self):
            super().__init__()
            self.repair_payloads = []

        def chat(self, messages=None, temperature=0.0, max_tokens=4096, tier="strong", **kw):
            payload = json.loads(messages[-1]["content"])
            if payload.get("repair"):
                self.repair_payloads.append(payload)
            def generate(source):
                return source if "Venture" in source and not payload.get("repair") else self._render(source)
            return model_protocol(messages, generate, expected_fn=self._render)

    llm = RefusesUntilTold()
    result = _worker(llm).translate_research_markdown(_DOSSIER)
    assert len(llm.repair_payloads) == 1
    retry = llm.repair_payloads[0]
    assert len(retry["entries"]) == 1 and "Venture" in next(iter(retry["entries"].values()))
    assert retry["issues"] and retry["previous"]
    assert result["available"] is True, result["audit"]["issues"]
    assert "Venture" not in result["translated_md"]
    assert result["audit"]["model_translation"]["calls_used"] == 4
