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

    def chat(self, messages=None, temperature=0.0, max_tokens=4096, tier="strong", **_kw):
        out = super().chat(messages, temperature, max_tokens, tier)
        return out.replace(_glm_like("rounds"), "融资轮次")


def test_references_keep_their_place_when_a_visual_annex_follows_them():
    result = _worker(GlmLikeTranslator()).translate_research_markdown(_DOSSIER)
    assert result["available"] is True, result["audit"]["issues"]
    translated = result["translated_md"]
    assert _headings(translated) == _headings(_DOSSIER)
    assert translated.index("## 参考来源") < translated.index("### ")


def test_pre_fix_reference_placement_reproduces_the_heading_failure(monkeypatch):
    """Guard the guard: re-appending References at the end fails the same dossier."""
    monkeypatch.setattr(
        ReportAgent,
        "_reattach_translation_references",
        classmethod(
            lambda _cls, _document, body, refs: body.rstrip() + "\n\n" + refs.rstrip() + "\n"
        ),
    )
    result = _worker(GlmLikeTranslator()).translate_research_markdown(_DOSSIER)
    assert result["available"] is False
    assert "translation heading-level sequence differs from primary" in (
        result["audit"]["issues"]
    )


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


def test_pre_fix_rounds_rule_reproduces_the_lost_sentence(monkeypatch):
    """Guard the guard: the old bare-轮次 rule deletes the sentence and its facts."""
    patterns = [
        (name, re.compile(r"轮次") if name == "sim_mechanics_zh" else pattern)
        for name, pattern in report_lint.LEAKAGE_PATTERNS
    ]
    monkeypatch.setattr(report_lint, "LEAKAGE_PATTERNS", patterns)
    result = _worker(RealRoundsTranslator()).translate_research_markdown(_DOSSIER)
    assert result["available"] is False
    assert "translation citation-token multiset differs from primary" in (
        result["audit"]["issues"]
    )


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


def test_dossier_sections_get_the_targeted_integrity_retry():
    """The dossier path shares the report engine: a section that stays English gets
    one retry carrying the INTEGRITY RETRY rules (it used to get a plain one)."""

    class RefusesUntilTold(GlmLikeTranslator):
        def __init__(self):
            super().__init__()
            self.retry_prompts = []

        def chat(self, messages=None, temperature=0.0, max_tokens=4096, tier="strong", **_kw):
            system, user = messages[0]["content"], messages[-1]["content"]
            if "INTEGRITY RETRY" in system:
                self.retry_prompts.append(system)
                return super().chat(messages, temperature, max_tokens, tier)
            if "Venture" in user:
                return user  # the whole-block call echoes English
            return super().chat(messages, temperature, max_tokens, tier)

        def chat_json(self, messages=None, temperature=0.0, max_tokens=4096, tier="fast", **_kw):
            return {}  # purity repair declines, so only the integrity retry can fix it

    llm = RefusesUntilTold()
    result = _worker(llm).translate_research_markdown(_DOSSIER)
    assert llm.retry_prompts, "the English section never got an integrity retry"
    assert result["available"] is True, result["audit"]["issues"]
    assert "Venture" not in result["translated_md"]
