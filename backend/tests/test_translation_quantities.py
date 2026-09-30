"""Amounts in report translation: "$3.7 billion" must become "37亿美元", not "3.7亿美元".

Numbers are protected byte-for-byte, so before amounts were atomic tokens the
model chose the magnitude word around a frozen numeral and wrote billion as 亿
(ten times too small) and million as 万 (a hundred times too small).  Every
numeral survived, so no integrity guard could see it; the published Chinese
quantum-2040 report said "3 亿美元" for "$3 billion".
"""

from __future__ import annotations

import re

import pytest

from app.services import translation_quantities as tq
from app.services.report_agent import ReportAgent
from test_translation_dates import GlmLikeTranslator


def _render(text: str, lang: str) -> list:
    return [tq.render_quantity(q, lang) for q in tq.find_quantities(text)]


@pytest.mark.parametrize(
    "source, rendered",
    [
        ("roughly $3.7 billion", ["37亿美元"]),
        ("about $255 million", ["2.55亿美元"]),
        ("only about $150–165 million", ["1.5–1.65亿美元"]),
        ("$0.1–0.7 billion per year", ["1–7亿美元"]),
        ("the USD 150 billion figure", ["1500亿美元"]),
        ("€900 million", ["9亿欧元"]),
        ("£2bn", ["20亿英镑"]),
        ("a $125M agreement", ["1.25亿美元"]),
        ("$2.7 trillion", ["2.7万亿美元"]),
        ("RMB 250 billion", ["2500亿元"]),
        ("1.4 billion people", ["14亿"]),
        ("2 million EVs", ["200万"]),
        ("a 3 billion-dollar deal", ["30亿"]),
    ],
)
def test_english_amounts_render_in_chinese_units(source, rendered):
    assert _render(source, "zh") == rendered


@pytest.mark.parametrize(
    "source, rendered",
    [
        ("37亿美元", ["$3.7 billion"]),
        ("8,200亿美元", ["$820 billion"]),
        ("1.5–1.65亿美元", ["$150–165 million"]),
        ("3.2万亿", ["3.2 trillion"]),
        ("250亿元投资", ["RMB 25 billion"]),
        ("60万颗", ["600,000"]),
        ("7.2 十亿", ["7.2 billion"]),
    ],
)
def test_chinese_amounts_render_in_english_units(source, rendered):
    assert _render(source, "en") == rendered


@pytest.mark.parametrize(
    "text",
    ["the 3M company", "Nvidia H100 million-unit", "5 thousand", "Series B", "8,200 jobs",
     "2030年", "A 10 km route", "截至 2025 万科销售额"],
)
def test_non_amounts_are_left_alone(text):
    assert tq.find_quantities(text) == []


def test_a_year_never_opens_an_amount_range():
    """Datacenter-2030 (中文→English) was withheld: "from $237 billion in 2024 to $200
    billion in 2025" was read as the range 2024–200 billion."""
    english = "FCF fell from $237 billion in 2024 to $200 billion in 2025."
    assert _render(english, "zh") == ["2370亿美元", "2000亿美元"]
    chinese = "自由现金流已从2024年的2,370亿美元降至2025年的2,000亿美元"
    assert ReportAgent._translation_fact_multiset(english) == (
        ReportAgent._translation_fact_multiset(chinese)
    )
    assert _render("from $1 to $2 billion", "zh") == ["10–20亿美元"]


def test_facts_compare_values_not_numerals():
    facts = ReportAgent._translation_fact_multiset
    assert facts("funding of $3.7 billion") == facts("资金为37亿美元")
    assert facts("funding of $3.7 billion") != facts("资金为3.7亿美元")
    assert facts("about $255 million") == facts("约2.55亿美元")
    assert facts("about $255 million") != facts("约255万美元")
    assert facts("出货 60万颗") == facts("shipped 600,000 units")
    assert ReportAgent._folded_fact_multiset("出货 60万颗") == (
        ReportAgent._folded_fact_multiset("shipped 600000 units")
    )


def test_pre_fix_facts_could_not_see_a_wrong_magnitude(monkeypatch):
    """Guard the guard: without amount facts the tenfold error looked identical."""
    monkeypatch.setattr(tq, "mask_quantities", lambda text: (text, []))
    facts = ReportAgent._translation_fact_multiset
    assert facts("funding of $3.7 billion") == facts("资金为3.7亿美元")


def test_amounts_are_protected_as_one_rendered_token():
    protected, mapping = ReportAgent._protect_translation_tokens(
        "Origin raised $150–165 million in 2025 [S65].", date_target="zh"
    )
    tokens = dict(mapping)
    amount = next(key for key in tokens if key.startswith("⟦Q"))
    assert tokens[amount] == "1.5–1.65亿美元"
    assert "million" not in protected and "$" not in protected


def test_restore_drops_a_magnitude_or_currency_the_model_repeated():
    restored, issues = ReportAgent._restore_translation_tokens(
        "筹集了⟦QA⟧亿美元。", [("⟦QA⟧", "37亿美元")]
    )
    assert restored == "筹集了37亿美元。" and issues == []
    restored, _ = ReportAgent._restore_translation_tokens(
        "raised $⟦QA⟧ billion.", [("⟦QA⟧", "$3.7 billion")]
    )
    assert restored == "raised $3.7 billion."
    # A currency the rendering does not carry is the model's own addition.
    restored, _ = ReportAgent._restore_translation_tokens(
        "投资⟦QA⟧美元。", [("⟦QA⟧", "30亿")]
    )
    assert restored == "投资30亿美元。"


def _worker(llm):
    worker = ReportAgent.__new__(ReportAgent)
    worker.llm = llm
    worker.output_language = "English"
    worker._forecast_spine = None
    return worker


def test_english_report_translates_amounts_with_the_right_magnitude():
    source = (
        "# Quantum 2040\n\n## Funding\n\n"
        "SCSP puts cumulative US private funding at roughly $3.7 billion against about "
        "$255 million for China [S69]. Origin Quantum has raised $150–165 million [S65].\n"
    )
    result = _worker(GlmLikeTranslator()).translate_research_markdown(source)
    assert result["available"] is True, result["audit"]["issues"]
    translated = result["translated_md"]
    for amount in ("37亿美元", "2.55亿美元", "1.5–1.65亿美元"):
        assert amount in translated
    assert "billion" not in translated and "million" not in translated


class _ChineseToEnglish:
    """Speaks the translation protocols for Chinese → English (pseudo-English words)."""

    model = "zh-en-stub"
    provider = "fake"

    @staticmethod
    def _englishify(value: str) -> str:
        def _word(char: str) -> str:
            return "".join(chr(97 + (ord(char) >> shift) % 26) for shift in (0, 3, 6))

        english = re.sub(
            r"[一-鿿]+",
            lambda match: " " + " ".join(_word(char) for char in match.group(0)) + " ",
            value,
        ).replace("，", ",").replace("。", ".")
        return "\n".join(re.sub(r"(?<=\S) {2,}| +$", " ", line).rstrip()
                         for line in english.split("\n")).replace("#  ", "# ")

    def chat(self, messages=None, temperature=0.0, max_tokens=4096, tier="strong", **_kw):
        system, user = messages[0]["content"], messages[-1]["content"]
        if "same alphabetic keys" in system:
            import json

            return json.dumps(
                {key: self._englishify(core) for key, core in json.loads(user).items()}
            )
        return self._englishify(user)

    def chat_json(self, messages=None, temperature=0.0, max_tokens=4096, tier="fast", **_kw):
        return {}


def test_chinese_report_translates_amounts_into_english_scale_words():
    source = (
        "# 数据中心市场\n\n## 市场规模\n\n"
        "全球数据中心投资将达到 8,200亿美元，其中芯片出货 60万颗，"
        "中国市场规模为 250亿元 [S1]。\n"
    )
    result = _worker(_ChineseToEnglish()).translate_research_markdown(source)
    assert result["available"] is True, result["audit"]["issues"]
    translated = result["translated_md"]
    for amount in ("$820 billion", "600,000", "RMB 25 billion"):
        assert amount in translated
