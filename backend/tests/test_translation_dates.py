"""Dates in report translation (English ⇄ Chinese) — regression for report_d79a064bf5cc.

The user pressed "Translate to 中文" and got "translation contains 1 target-language
contamination lines"; the whole Chinese report was withheld.  Root cause: GLM renders
"December 2024" as "2024年12月", adding the numeral 12 that the English source does not
contain, so every numeric-integrity guard rejected the sentence and it stayed English.

The fix protects each date expression as one atomic token rendered in the target
language, and compares numbers across languages with a date-aware fact multiset.
"""

from __future__ import annotations

import json
import re

import pytest

from app.services import translation_dates as td
from app.services.report_agent import ReportAgent


# ─────────────────────────────── recognizer ───────────────────────────────
@pytest.mark.parametrize(
    "text, span, fact, zh, en",
    [
        ("in December 2024 it", "December 2024", "date:2024-12", "2024年12月", "December 2024"),
        ("By December 31, 2033, a", "December 31, 2033", "date:2033-12-31",
         "2033年12月31日", "December 31, 2033"),
        ("effective 6 November 2025 adding", "6 November 2025", "date:2025-11-06",
         "2025年11月6日", "November 6, 2025"),
        ("the 14th of March 2026", "14th of March 2026", "date:2026-03-14",
         "2026年3月14日", "March 14, 2026"),
        ("Dec. 5th 2025 and", "Dec. 5th 2025", "date:2025-12-05", "2025年12月5日",
         "December 5, 2025"),
        ("Sept 2025 update", "Sept 2025", "date:2025-09", "2025年9月", "September 2025"),
        ("announced 9 October controls", "9 October", "date:--10-09", "10月9日", "October 9"),
        ("on March 5 the", "March 5", "date:--03-05", "3月5日", "March 5"),
        ("2024年12月，谷歌", "2024年12月", "date:2024-12", "2024年12月", "December 2024"),
        ("2033年12月31日前", "2033年12月31日", "date:2033-12-31", "2033年12月31日",
         "December 31, 2033"),
        ("到 2024年 12月", "2024年 12月", "date:2024-12", "2024年12月", "December 2024"),
        ("12月31日", "12月31日", "date:--12-31", "12月31日", "December 31"),
    ],
)
def test_dated_expressions_are_recognized_rendered_and_canonical(text, span, fact, zh, en):
    [found] = td.find_dates(text)
    assert text[found.start:found.end] == span
    assert td.canonical_date_fact(found) == fact
    assert td.render_date(found, "zh") == zh
    assert td.render_date(found, "en") == en


def test_bare_months_are_protected_only_after_temporal_words_and_carry_no_fact():
    text = "in May; since March; mid-October; the March–June 2025 window; 去年3月"
    found = [(text[d.start:d.end], td.canonical_date_fact(d)) for d in td.find_dates(text)]
    assert found == [
        ("May", None), ("March", None), ("October", None),
        ("March", None), ("June 2025", "date:2025-06"), ("3月", None),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "regulators may act; Theresa May spoke",       # modal verb / surname
        "Long March 5 launched; Long March 2F too",     # rocket names
        "in March Congress acted",                      # proper-noun context
        "3 months, 5,000 qubits, 12个月, March 5.5% growth",
        "by March, 2026 targets were set",              # clause break, not a date
    ],
)
def test_non_dates_are_left_alone(text):
    assert td.find_dates(text) == [] or all(
        td.canonical_date_fact(d) is None for d in td.find_dates(text)
    )
    masked, facts = td.mask_dates(text)
    assert facts == []
    # Loose numbers survive masking untouched.
    for number in re.findall(r"\d+(?:[.,]\d+)?", text):
        assert number in masked


def test_mask_dates_keeps_loose_numbers_and_adds_one_fact_per_date():
    masked, facts = td.mask_dates("In December 2024, 31 firms and 2033 targets; 12月31日")
    assert facts == ["date:2024-12", "date:--12-31"]
    assert "31 firms" in masked and "2033 targets" in masked


def test_target_code_for_language_labels():
    assert td.target_code_for_language("简体中文（Simplified Chinese）") == "zh"
    assert td.target_code_for_language("professional analyst-grade English") == "en"
    assert td.target_code_for_language("Chinese") == "zh"
    assert td.target_code_for_language("English") == "en"
    assert td.target_code_for_language("French") is None


# ──────────────────────── token protection & restore ────────────────────────
_LINE = (
    "Google's Willow demonstrated below-threshold surface-code error correction in "
    "December 2024 and claimed the first verifiable quantum advantage in October 2025 "
    "[S1][S2]; DARPA's Quantum Benchmarking Initiative will test utility-scale "
    "operation by 2033 [S11]."
)


def test_dates_become_atomic_tokens_rendered_in_the_target_language():
    hidden, mapping = ReportAgent._protect_translation_tokens(_LINE, date_target="zh")
    dates = [raw for placeholder, raw in mapping if placeholder.startswith("⟦D")]
    assert dates == ["2024年12月", "2025年10月"]
    assert "December" not in hidden and "October" not in hidden
    # Loose numbers and citations keep their historical self-describing tokens.
    loose = {raw: placeholder for placeholder, raw in mapping if not placeholder.startswith("⟦D")}
    assert loose["2033"].startswith("⟦P")
    assert sorted(raw for raw in loose if raw.startswith("[S")) == ["[S11]", "[S1]", "[S2]"]


def test_protection_without_date_target_is_unchanged():
    legacy, legacy_map = ReportAgent._protect_translation_tokens(_LINE)
    assert "December" in legacy and not any(p.startswith("⟦D") for p, _raw in legacy_map)


def test_dates_inside_urls_and_code_stay_byte_identical():
    text = "See `March 2025 build` and https://example.com/news/March 2025 now."
    hidden, mapping = ReportAgent._protect_translation_tokens(text, date_target="zh")
    raws = [raw for _p, raw in mapping]
    assert "`March 2025 build`" in raws
    assert "https://example.com/news/March" in raws
    restored, issues = ReportAgent._restore_translation_tokens(hidden, mapping)
    assert issues == [] and "`March 2025 build`" in restored


def test_restore_drops_a_unit_the_model_appended_to_a_complete_date():
    hidden, mapping = ReportAgent._protect_translation_tokens(
        "released in December 2024.", date_target="zh"
    )
    placeholder = next(p for p, _raw in mapping if p.startswith("⟦D"))
    restored, issues = ReportAgent._restore_translation_tokens(
        f"于{placeholder}年发布。", mapping
    )
    assert issues == []
    assert restored == "于2024年12月发布。"


def test_fact_multiset_matches_across_languages_but_still_catches_real_drift():
    source = "in December 2024 and by December 31, 2033, with 45% odds [S1]"
    faithful = "于2024年12月，并在2033年12月31日前，概率为45% [S1]"
    wrong_day = "于2024年12月，并在2033年12月30日前，概率为45% [S1]"
    dropped_month = "于2024年，并在2033年12月31日前，概率为45% [S1]"
    assert ReportAgent._translation_fact_multiset(source) == (
        ReportAgent._translation_fact_multiset(faithful)
    )
    assert ReportAgent._translation_fact_multiset(source) != (
        ReportAgent._translation_fact_multiset(wrong_day)
    )
    assert ReportAgent._translation_fact_multiset(source) != (
        ReportAgent._translation_fact_multiset(dropped_month)
    )
    # Same-language checks (PDF text extraction) keep the plain numeral multiset.
    assert ReportAgent._translation_number_multiset(faithful)["12"] == 2


# ───────────────── end-to-end: the user's failing sentence ─────────────────
_MONTHS = {name: index for index, name in enumerate(td.MONTH_NAMES, 1)}


def _cjk_word(word: str) -> str:
    return "".join(chr(0x4E00 + (ord(ch.lower()) - 97) % 40) for ch in word[:3]) or "词"


def _zhify(value: str) -> str:
    parts = re.split(r"(⟦[^⟧]*⟧)", value)
    return "".join(
        part if part.startswith("⟦") else re.sub(
            r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z'’-]*",
            lambda m: _cjk_word(re.sub(r"[^A-Za-z]", "", m.group(0))),
            part,
        )
        for part in parts
    )


def _glm_like(value: str) -> str:
    """Translate the way GLM-5.3 did live: "December ⟦year⟧" → "⟦year⟧年12月"."""
    value = re.sub(
        r"\b(" + "|".join(td.MONTH_NAMES) + r")\s+(⟦P[A-Z]+:[A-Za-z0-9_-]+⟧)",
        lambda m: f"{m.group(2)}年{_MONTHS[m.group(1)]}月",
        value,
    )
    return _zhify(value)


class GlmLikeTranslator:
    """Speaks every translation protocol and renders dates like the live model."""

    model = "glm-like-stub"
    provider = "fake"

    def __init__(self):
        self.temperatures = []

    def chat(self, messages=None, temperature=0.0, max_tokens=4096, tier="strong", **_kw):
        self.temperatures.append(temperature)
        system, user = messages[0]["content"], messages[-1]["content"]
        if "same alphabetic keys" in system:
            return json.dumps(
                {key: _glm_like(core) for key, core in json.loads(user).items()},
                ensure_ascii=False,
            )
        return _glm_like(user)

    def chat_json(self, messages=None, temperature=0.0, max_tokens=4096, tier="fast", **_kw):
        self.temperatures.append(temperature)
        out = {}
        for line in messages[-1]["content"].splitlines():
            match = re.match(r"^(\d+)\.\s+(.*)$", line)
            if match:
                out[match.group(1)] = _glm_like(match.group(2))
        return out


_SOURCE = (
    "# Quantum 2040\n\n"
    "## Executive Forecast\n\n"
    f"{_LINE}\n\n"
    "By December 31, 2033, at least one vendor runs 100 logical qubits (45%).\n"
)


def _worker(llm):
    worker = ReportAgent.__new__(ReportAgent)
    worker.llm = llm
    worker.output_language = "English"
    worker._forecast_spine = None
    return worker


def test_user_sentence_translates_and_passes_the_publication_audit():
    result = _worker(GlmLikeTranslator()).translate_research_markdown(_SOURCE)
    audit = result["audit"]
    assert result["available"] is True, audit["issues"]
    assert audit["number_parity"]["passed"] is True
    assert audit["language_lint"]["language_contamination"]["lines"] == 0
    translated = result["translated_md"]
    assert "2024年12月" in translated and "2025年10月" in translated
    assert "2033年12月31日" in translated
    assert "December" not in translated and "demonstrated" not in translated


def test_pre_fix_pipeline_reproduces_the_contamination_failure(monkeypatch):
    """Guard the guard: with date protection and date-aware parity switched off, the
    same GLM-like model leaves the sentence English and the audit withholds it."""
    monkeypatch.setattr(td, "target_code_for_language", lambda _name: None)
    monkeypatch.setattr(
        ReportAgent, "_translation_fact_multiset",
        classmethod(lambda cls, md: cls._translation_number_multiset(md)),
    )
    monkeypatch.setattr(
        ReportAgent, "_folded_fact_multiset",
        classmethod(lambda cls, md: cls._folded_number_multiset(md)),
    )
    result = _worker(GlmLikeTranslator()).translate_research_markdown(_SOURCE)
    assert result["available"] is False
    assert any(
        "target-language contamination" in issue for issue in result["audit"]["issues"]
    )


def test_repair_rounds_sample_warmer_instead_of_replaying_the_same_request():
    class Refuses(GlmLikeTranslator):
        def chat(self, messages=None, temperature=0.0, max_tokens=4096, tier="strong", **_kw):
            self.temperatures.append(temperature)
            return messages[-1]["content"]  # echo → rejected → next round

        def chat_json(self, messages=None, temperature=0.0, max_tokens=4096, tier="fast", **_kw):
            self.temperatures.append(temperature)
            return {}

    llm = Refuses()
    english = "# 标题\n\n" + _LINE + "\n"
    _worker(llm)._repair_variant_contamination(english, True, "简体中文（Simplified Chinese）")
    # The segment rounds ramp 0 → 0.3 → 0.6 (the whole-line last resort that follows
    # uses the unit translator's own temperature).
    assert {0.0, 0.3, 0.6} <= set(llm.temperatures)


def test_english_target_prompts_carry_the_numeral_word_rule_only_when_needed():
    assert td.translation_prompt_rules("en", "欧盟量子旗舰二期") == td.NUMERAL_WORD_RULE_EN
    assert td.translation_prompt_rules("zh", "EU Quantum Flagship phase two") == ""
    assert td.translation_prompt_rules("en", "no numerals here") == ""
    both = td.translation_prompt_rules("en", "⟦DA⟧ 十四五")
    assert td.DATE_TOKEN_RULE in both and td.NUMERAL_WORD_RULE_EN in both

    seen = []

    class Recorder:
        model = "recorder"
        provider = "fake"

        def chat(self, messages=None, temperature=0.0, max_tokens=4096, tier="strong", **_kw):
            seen.append(messages[0]["content"])
            return json.dumps({"A": "Phase Two of the EU Quantum Flagship"})

    agent = ReportAgent.__new__(ReportAgent)
    agent.llm = Recorder()
    resolved = agent._resolve_prose_slots(
        {"A": "欧盟量子旗舰二期"}, "professional analyst-grade English"
    )
    assert resolved == {"A": "Phase Two of the EU Quantum Flagship"}
    assert seen and td.NUMERAL_WORD_RULE_EN in seen[0]
