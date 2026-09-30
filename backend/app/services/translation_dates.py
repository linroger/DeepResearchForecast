"""Deterministic date localization for report translation (English ⇄ Chinese).

Why this exists
---------------
The translation pipeline guards numeric integrity: a translated report must
carry exactly the numbers of its source.  Chinese writes months as numerals
("2024年12月") while English spells them out ("December 2024"), so a faithful
English→Chinese translation *adds* the numeral 12 and every guard rejected it.
Rejected sentences either stayed English (the publication audit then withheld
the whole Chinese report as "contaminated") or were accepted only in a lossy
form that dropped the month.

The fix has two halves that share one recognizer:

* ``DATE_PATTERN`` / ``interpret_date_match`` — the translator protects each
  recognized date expression as one atomic token and renders it
  deterministically in the target language (``render_date``), so the model
  never has to convert a date format and cannot drop half of one.
* ``mask_dates`` — cross-language numeric comparisons treat each full date as
  one canonical fact (``date:2024-12``, ``date:2033-12-31``, ``date:--12-31``)
  instead of a bag of loose numerals.  A bare month ("December", "12月") has no
  year or day, so it is masked without adding a fact: its only numeral is the
  month itself, which is representation, not an extra number.

Recognition is deliberately conservative: English month names are
case-sensitive, a bare month name needs a date-like preposition in front of it
("in May", "by March", "mid-October") or a dashed range partner
("March–June 2025"), and "Long March 5" (a rocket) is never a date.
"""

from __future__ import annotations

import re
from typing import Dict, List, NamedTuple, Optional, Tuple

from .translation_quantities import QUANTITY_TOKEN_RULE

MONTH_NAMES: Tuple[str, ...] = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

_MONTH_NUMBER: Dict[str, int] = {name: index for index, name in enumerate(MONTH_NAMES, 1)}
_MONTH_NUMBER.update({
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "Jun": 6, "Jul": 7, "Aug": 8,
    "Sep": 9, "Sept": 9, "Oct": 10, "Nov": 11, "Dec": 12,
})

_FULL_MONTH = "|".join(MONTH_NAMES)
# Full names first so "June" wins over "Jun"; an abbreviation may carry a period.
_MONTH = (
    r"(?:" + _FULL_MONTH
    + r"|(?:Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?)"
)
_YEAR = r"(?:1[89]|2[01])\d{2}"
_DAY = r"(?:3[01]|[12]\d|0?[1-9])"
_ORD = r"(?:st|nd|rd|th)?"
_SP = r"[ \u00a0]+"
_ZH_MONTH = r"(?:1[0-2]|0?[1-9])"
# A bare month (no day, no year) is protected only after an unambiguous temporal
# word ("in May", "mid-October", "since March").  Leaving an ambiguous one alone is
# harmless: bare months carry no numeric fact (see ``canonical_date_fact``), so a
# model's own "12月" rendering still passes every integrity check.
_BARE_PREFIX = (
    r"(?:in|by|since|until|till|through|from|before|after|during|early|mid|late|"
    r"end|last|next|this|each|every|between)"
)
# ...unless the month is really the start of a dated expression ("in December 2024",
# matched by the Month-YYYY branch) or of a proper noun ("in March Congress").
_BARE_TAIL = rf"(?![A-Za-z])(?!,?{_SP}(?:of{_SP})?\d)(?!{_SP}[A-Z])"

# One alternation shared by the translator (inside its inline-token regex) and
# ``mask_dates``.  Every branch is case-sensitive via the scoped ``(?-i:…)`` flag
# so embedding it in an IGNORECASE regex cannot turn "may" into a month.  Named
# groups use single-letter prefixes so ``interpret_date_match`` can tell the
# branches apart; group names are unique so the pattern can be embedded.
DATE_PATTERN = (
    r"(?P<date>(?-i:"
    # English: Month D, YYYY  ("December 31, 2033", "Dec. 5th 2025")
    rf"(?<![A-Za-z])(?<!Long )(?P<a_m>{_MONTH}){_SP}(?P<a_d>{_DAY}){_ORD}(?![\dA-Za-z]),?{_SP}"
    rf"(?P<a_y>{_YEAR})(?!\d)"
    # English: D Month YYYY  ("6 November 2025", "14th of March 2026")
    rf"|(?<![\d.,])(?P<b_d>{_DAY}){_ORD}{_SP}(?:of{_SP})?(?P<b_m>{_MONTH})(?![A-Za-z]),?"
    rf"{_SP}(?P<b_y>{_YEAR})(?!\d)"
    # English: Month YYYY  ("December 2024", "Sept 2025", "March of 2026").  No comma
    # form: "by March, 2026 targets" is a clause break, not a date.
    rf"|(?<![A-Za-z])(?<!Long )(?P<c_m>{_MONTH}){_SP}(?:of{_SP})?(?P<c_y>{_YEAR})(?!\d)"
    # Chinese: YYYY年M月D日 / YYYY年M月
    rf"|(?<!\d)(?P<g_y>{_YEAR})[ ]*年[ ]*(?P<g_m>{_ZH_MONTH})[ ]*月[ ]*(?P<g_d>{_DAY})[ ]*[日号]"
    rf"|(?<!\d)(?P<h_y>{_YEAR})[ ]*年[ ]*(?P<h_m>{_ZH_MONTH})[ ]*月"
    # English: Month D  ("March 5", never "Long March 5")
    rf"|(?<![A-Za-z])(?<!Long )(?P<d_m>{_MONTH}){_SP}(?P<d_d>{_DAY}){_ORD}(?![\dA-Za-z])"
    r"(?![.,]\d)"
    # English: D Month  ("9 October", "the 14th of March")
    rf"|(?<![\d.,])(?P<e_d>{_DAY}){_ORD}{_SP}(?:of{_SP})?(?P<e_m>{_MONTH})(?![A-Za-z])"
    # Chinese: M月D日 / bare M月 ("去年3月" — a relative year is not a date year)
    rf"|(?<![\d.])(?P<i_m>{_ZH_MONTH})[ ]*月[ ]*(?P<i_d>{_DAY})[ ]*[日号]"
    rf"|(?<![\d.])(?P<j_m>{_ZH_MONTH})[ ]*月"
    # English: bare month after a temporal word ("in December", "mid-October")
    rf"|(?P<f_pre>(?<![A-Za-z]){_BARE_PREFIX}(?:{_SP}|-))(?P<f_m>{_FULL_MONTH}){_BARE_TAIL}"
    # English: bare month opening a dashed range ("March–June 2025")
    rf"|(?<![A-Za-z])(?<!Long )(?P<l_m>{_FULL_MONTH})(?=[ ]*[–—-][ ]*{_MONTH}(?![A-Za-z]))"
    r"))"
)

DATE_RE = re.compile(DATE_PATTERN)

# (branch month group, day group, year group, language)
_BRANCHES: Tuple[Tuple[str, Optional[str], Optional[str], str], ...] = (
    ("a_m", "a_d", "a_y", "en"),
    ("b_m", "b_d", "b_y", "en"),
    ("c_m", None, "c_y", "en"),
    ("g_m", "g_d", "g_y", "zh"),
    ("h_m", None, "h_y", "zh"),
    ("d_m", "d_d", None, "en"),
    ("e_m", "e_d", None, "en"),
    ("i_m", "i_d", None, "zh"),
    ("j_m", None, None, "zh"),
    ("f_m", None, None, "en"),
    ("l_m", None, None, "en"),
)


class DateExpression(NamedTuple):
    """One recognized date.  ``start``/``end`` delimit the text a translator
    replaces (for "in December" only the month word); ``year``/``day`` are None
    when the expression does not state them."""

    start: int
    end: int
    year: Optional[int]
    month: int
    day: Optional[int]
    lang: str


def _month_number(token: str, lang: str) -> Optional[int]:
    if lang == "zh":
        value = int(token)
        return value if 1 <= value <= 12 else None
    return _MONTH_NUMBER.get(token.rstrip("."))


def interpret_date_match(match: "re.Match[str]") -> Optional[DateExpression]:
    """Interpret a match of ``DATE_PATTERN`` (standalone or embedded).

    Returns None when the embedded ``date`` group did not participate or a value
    is out of range (month outside 1–12, day outside 1–31).
    """
    if match.group("date") is None:
        return None
    for month_group, day_group, year_group, lang in _BRANCHES:
        month_text = match.group(month_group)
        if month_text is None:
            continue
        month = _month_number(month_text, lang)
        if month is None:
            return None
        day = int(match.group(day_group)) if day_group and match.group(day_group) else None
        year = int(match.group(year_group)) if year_group and match.group(year_group) else None
        if day is not None and not 1 <= day <= 31:
            return None
        if month_group in ("f_m", "l_m"):
            start, end = match.span(month_group)
        else:
            start, end = match.span("date")
        return DateExpression(start, end, year, month, day, lang)
    return None


def render_date(expression: DateExpression, lang: str) -> str:
    """Render a date in the target language's standard written form."""
    year, month, day = expression.year, expression.month, expression.day
    if lang == "zh":
        text = f"{year}年" if year is not None else ""
        text += f"{month}月"
        if day is not None:
            text += f"{day}日"
        return text
    name = MONTH_NAMES[month - 1]
    if year is not None and day is not None:
        return f"{name} {day}, {year}"
    if year is not None:
        return f"{name} {year}"
    if day is not None:
        return f"{name} {day}"
    return name


def canonical_date_fact(expression: DateExpression) -> Optional[str]:
    """Language-neutral identity of a date that states a year and/or a day.

    A bare month has no fact: it carries no number beyond its own month, and a
    translator may legitimately render it with or without a numeral.
    """
    if expression.year is None and expression.day is None:
        return None
    year = f"{expression.year:04d}" if expression.year is not None else "-"
    fact = f"date:{year}-{expression.month:02d}"
    if expression.day is not None:
        fact += f"-{expression.day:02d}"
    return fact


def find_dates(text: str) -> List[DateExpression]:
    """Return every recognized date expression in ``text``, left to right."""
    found: List[DateExpression] = []
    for match in DATE_RE.finditer(text or ""):
        expression = interpret_date_match(match)
        if expression is not None:
            found.append(expression)
    return found


def mask_dates(text: str) -> Tuple[str, List[str]]:
    """Blank every recognized date and return (masked text, canonical facts).

    The masked text keeps every other number, so a caller can count loose
    numerals on it and add the date facts as whole tokens.
    """
    source = text or ""
    pieces: List[str] = []
    facts: List[str] = []
    cursor = 0
    for expression in find_dates(source):
        pieces.append(source[cursor:expression.start])
        pieces.append(" ")
        cursor = expression.end
        fact = canonical_date_fact(expression)
        if fact is not None:
            facts.append(fact)
    pieces.append(source[cursor:])
    return "".join(pieces), facts


def target_code_for_language(name: str) -> Optional[str]:
    """Map a target-language label ("简体中文（Simplified Chinese）", "English",
    "professional analyst-grade English", "zh") to 'zh' / 'en', else None."""
    text = str(name or "").strip()
    lowered = text.lower()
    if re.search(r"[\u4e00-\u9fff]", text) or "chinese" in lowered or lowered in ("zh", "zh-cn"):
        return "zh"
    if "english" in lowered or lowered == "en":
        return "en"
    return None


# Model-facing rule appended to translation prompts whenever a ⟦D…⟧ token is present.
DATE_TOKEN_RULE = (
    "Tokens shaped ⟦D…⟧ are complete dates already written in the target language: "
    "copy each exactly once where its date belongs, and never add a year, month or day "
    "word, 年/月/日, or any numeral next to one."
)

# The mirror problem for Chinese → English: "十四五" / "二期" come back as "14th" /
# "Phase 2", digits the Chinese source never had, so the same integrity guards reject
# them.  Spelled-out English keeps the facts identical; GLM follows this rule live.
_CJK_NUMERAL_RE = re.compile(r"[〇零一二两三四五六七八九十百千万亿]")
NUMERAL_WORD_RULE_EN = (
    "A number the source writes with Chinese numerals stays a word in English, never a "
    "digit: 十四五 → the Fourteenth Five-Year Plan, 二期 → Phase Two, 两会 → the Two "
    "Sessions, 第三 → third."
)


def numeral_word_rule(target_code: Optional[str], text: str) -> str:
    """Return the English-target numeral rule when ``text`` has Chinese numerals."""
    if target_code == "en" and _CJK_NUMERAL_RE.search(text or ""):
        return NUMERAL_WORD_RULE_EN
    return ""


def translation_prompt_rules(target_code: Optional[str], text: str) -> str:
    """Extra prompt rules for one translation request ("" when none apply).

    Kept empty for inputs without dates, amounts or Chinese numerals so historical
    prompts (and the fakes that fingerprint them) are unchanged.
    """
    rules = []
    if "⟦D" in (text or ""):
        rules.append(DATE_TOKEN_RULE)
    if "⟦Q" in (text or ""):
        rules.append(QUANTITY_TOKEN_RULE)
    numeral = numeral_word_rule(target_code, text)
    if numeral:
        rules.append(numeral)
    return " ".join(rules)


def strip_redundant_date_unit(candidate: str, placeholder: str, rendered: str) -> str:
    """Drop a 年/月/日/号 a model appended to an already-complete Chinese date token.

    A translator that sees "in ⟦DA⟧" sometimes writes "于⟦DA⟧年"; after the token
    is restored to "2024年12月" that would read "2024年12月年".  The rendered date
    already ends in 月 or 日, so one unit character directly after the token is
    always redundant.
    """
    if not rendered.endswith(("月", "日")):
        return candidate
    return re.sub(re.escape(placeholder) + r"[ ]*[年月日号]", placeholder, candidate)
