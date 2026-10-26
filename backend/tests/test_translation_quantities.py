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
        from model_translation_fakes import model_protocol, preserve_carriers
        def faithful(value):
            value = value.replace("8,200亿美元", "$820 billion").replace("60万颗", "600,000 units").replace("250亿元", "RMB 25 billion")
            return preserve_carriers(value, self._englishify)
        native = model_protocol(messages, faithful)
        if native is not None:
            return native
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


# ───────────── FRED unit labels: "25000 Millions of Dollars" (report_0f2e07d62a34) ─────────────
# The live Chinese re-run of 2026-10-17 was withheld by three residual English lines: the
# binary-forecast rows F4, F11 and F13 quote FRED thresholds as "<number> Millions of
# Dollars".  The phrase was not an amount, so only the numeral was frozen and every
# faithful "250亿美元" changed the numeric multiset; the rows stayed English.
FRED_ROW = "(fred:IMPCH) are below 25000 Millions of Dollars in June 2027."
FRED_ROW_ZH = "(fred:IMPCH) 在2027年6月低于250亿美元。"


@pytest.mark.parametrize(
    "source, rendered, facts",
    [
        ("are below 25000 Millions of Dollars in June 2027", ["250亿美元"], ["qty:25000000000"]),
        ("fall below 30,000 millions of dollars", ["300亿美元"], ["qty:30000000000"]),
        ("fall below 20,000 millions of dollars", ["200亿美元"], ["qty:20000000000"]),
        ("27133.8159 Millions of Dollars (2026-08)", ["271.338159亿美元"], ["qty:27133815900"]),
        ("306.398 Billions of Dollars", ["3063.98亿美元"], ["qty:306398000000"]),
        ("1.2 Billions of U.S. Dollars", ["12亿美元"], ["qty:1200000000"]),
        ("450 Millions of US Dollars", ["4.5亿美元"], ["qty:450000000"]),
        ("2.5 Trillions of Dollars", ["2.5万亿美元"], ["qty:2500000000000"]),
        ("20,000 Thousands of Dollars", ["2000万美元"], ["qty:20000000"]),
        ("500 Thousands of Dollars", ["50万美元"], ["500,000"]),
        ("$25,000 Millions of Dollars", ["250亿美元"], ["qty:25000000000"]),
        ("25,000–30,000 MILLIONS OF DOLLARS", ["250–300亿美元"],
         ["qty:25000000000", "qty:30000000000"]),
    ],
)
def test_fred_unit_phrases_are_one_amount_worth_number_times_magnitude(source, rendered, facts):
    assert _render(source, "zh") == rendered
    assert [fact for q in tq.find_quantities(source) for fact in tq.quantity_facts(q)] == facts


def test_fred_unit_phrase_is_matched_whole_with_a_fixed_dollar_currency():
    [found] = tq.find_quantities(FRED_ROW)
    assert FRED_ROW[found.start:found.end] == "25000 Millions of Dollars"
    assert [str(value) for value in found.values] == ["25000000000"]
    assert found.currency == "USD" and found.lang == "en"
    masked, facts = tq.mask_quantities(FRED_ROW)
    assert facts == ["qty:25000000000"]
    assert "Millions" not in masked and "25000" not in masked and "June 2027" in masked


def test_fred_amounts_round_trip_through_the_english_rendering():
    assert _render("25000 Millions of Dollars", "en") == ["$25 billion"]
    assert _render("250亿美元", "en") == ["$25 billion"]  # the Chinese → English direction
    assert _render("20,000 Thousands of Dollars", "en") == ["$20 million"]
    assert _render("500 Thousands of Dollars", "en") == ["$500,000"]


@pytest.mark.parametrize(
    "text",
    [
        "Millions of Dollars; Monthly; NSA",            # a bare unit label
        "| Billions of Dollars | 306.398 |",            # unit and value in separate cells
        "hundreds of millions of dollars",
        "tens of billions of dollars",
        "150 Thousands of Persons",                     # not a dollar amount
        "306 Billions of Chained 2017 Dollars",         # real terms: left frozen, fails closed
    ],
)
def test_fred_unit_labels_without_a_dollar_amount_are_left_alone(text):
    assert tq.find_quantities(text) == []


@pytest.mark.parametrize(
    "text, span",
    [
        ("25000 Million of Dollars", "25000 Million"),
        ("$3.7 billion dollars", "$3.7 billion dollars"),
        ("5bn of dollars", "5bn"),
        ("USD 150 billion", "USD 150 billion"),
    ],
)
def test_existing_english_forms_never_reach_the_fred_branch(text, span):
    """The FRED alternative is tried only after the English one fails, so every match
    the English alternative made before this branch existed is byte-identical."""
    [found] = tq.find_quantities(text)
    assert text[found.start:found.end] == span
    assert tq.QUANTITY_RE.search(text).group("qf_n1") is None


def test_fred_facts_compare_values_not_numerals():
    facts = ReportAgent._translation_fact_multiset
    assert facts(FRED_ROW) == facts(FRED_ROW_ZH)
    assert facts(FRED_ROW) != facts("(fred:IMPCH) 在2027年6月低于25亿美元。")     # ten times too small
    assert facts(FRED_ROW) != facts("(fred:IMPCH) 在2027年6月低于25000亿美元。")  # the frozen numeral
    assert ReportAgent._folded_fact_multiset("500 Thousands of Dollars") == (
        ReportAgent._folded_fact_multiset("50万美元")
    )


def test_pre_fix_guard_rejected_every_faithful_rendering_of_a_fred_row(monkeypatch):
    """Guard the guard: without the FRED branch the numeral is frozen alone and the
    faithful Chinese row fails the number guard, exactly as the live rows did."""
    monkeypatch.setattr(tq, "_FRED_SCALE", {})
    assert tq.find_quantities(FRED_ROW) == []
    facts = ReportAgent._translation_fact_multiset
    assert facts(FRED_ROW) != facts(FRED_ROW_ZH)
    protected, mapping = ReportAgent._protect_translation_tokens(FRED_ROW, date_target="zh")
    assert "Millions of Dollars" in protected
    assert not any(placeholder.startswith("⟦Q") for placeholder, _raw in mapping)


def test_fred_row_is_protected_as_one_rendered_token_and_restores_in_chinese():
    protected, mapping = ReportAgent._protect_translation_tokens(FRED_ROW, date_target="zh")
    tokens = dict(mapping)
    amount = next(key for key in tokens if key.startswith("⟦Q"))
    date = next(key for key in tokens if key.startswith("⟦D"))
    assert tokens[amount] == "250亿美元" and tokens[date] == "2027年6月"
    assert "Millions" not in protected and "25000" not in protected
    restored, issues = ReportAgent._restore_translation_tokens(
        f"(fred:IMPCH) 在{date}低于{amount}。", mapping
    )
    assert issues == [] and restored == FRED_ROW_ZH
    assert ReportAgent._translation_fact_multiset(restored) == (
        ReportAgent._translation_fact_multiset(FRED_ROW)
    )
    # A magnitude or currency the model copies from the label is dropped next to the token.
    restored, issues = ReportAgent._restore_translation_tokens(
        f"(fred:IMPCH) 在{date}低于{amount}百万美元。", mapping
    )
    assert issues == [] and restored == FRED_ROW_ZH


def test_fred_amount_translates_back_to_the_english_rendering():
    protected, mapping = ReportAgent._protect_translation_tokens(FRED_ROW_ZH, date_target="en")
    tokens = dict(mapping)
    amount = next(key for key in tokens if key.startswith("⟦Q"))
    date = next(key for key in tokens if key.startswith("⟦D"))
    assert tokens[amount] == "$25 billion" and tokens[date] == "June 2027"
    restored, issues = ReportAgent._restore_translation_tokens(
        f"(fred:IMPCH) are below {amount} in {date}.", mapping
    )
    assert issues == [] and restored == "(fred:IMPCH) are below $25 billion in June 2027."
    assert ReportAgent._translation_fact_multiset(restored) == (
        ReportAgent._translation_fact_multiset(FRED_ROW)
    )


def test_fred_phrase_keeps_its_bytes_when_the_target_is_english():
    """The primary report's purity pass protects with the English target: the phrase is
    one token whose restored bytes are the source bytes, so English output is unchanged;
    without a date target the historical grammar still sees only the numeral."""
    protected, mapping = ReportAgent._protect_translation_tokens(FRED_ROW, date_target="en")
    amount = next(key for key, _raw in mapping if key.startswith("⟦Q"))
    assert dict(mapping)[amount] == "25000 Millions of Dollars"
    restored, issues = ReportAgent._restore_translation_tokens(protected, mapping)
    assert issues == [] and restored == FRED_ROW
    legacy, legacy_map = ReportAgent._protect_translation_tokens(FRED_ROW)
    assert "Millions of Dollars" in legacy
    assert not any(placeholder.startswith("⟦Q") for placeholder, _raw in legacy_map)


def test_english_report_translates_fred_unit_phrases_with_the_right_magnitude():
    source = (
        "# Trade 2027\n\n## Binary Forecasts\n\n"
        "U.S. imports of goods from China (fred:IMPCH) are below 25000 Millions of Dollars "
        "in June 2027 [S11], after 27133.8159 Millions of Dollars in August 2026.\n"
    )
    result = _worker(GlmLikeTranslator()).translate_research_markdown(source)
    assert result["available"] is True, result["audit"]["issues"]
    translated = result["translated_md"]
    assert "250亿美元" in translated and "271.338159亿美元" in translated
    assert "Millions" not in translated and "25000" not in translated


@pytest.mark.parametrize("source,zh", [
    ("-3.7 billion", "-37亿"), ("−3.7 billion", "-37亿"),
    ("-$3.7 billion", "-37亿美元"), ("$-3.7 billion", "-37亿美元"),
    ("-0.4 million", "-40万"), ("-0.0000005 million", "-0.5"),
    ("-3.7–-2 billion", "-37–-20亿"),
])
def test_signed_quantity_is_atomic_and_round_trips(source, zh):
    protected, mapping = ReportAgent._protect_translation_tokens(source, date_target="zh")
    restored, issues = ReportAgent._restore_translation_tokens(protected, mapping)
    assert not issues and restored == zh
    assert ReportAgent._translation_fact_multiset(source) == ReportAgent._translation_fact_multiset(zh)
    assert not ReportAgent._forecast_text_facts_preserved(source, zh.replace("-", ""))
