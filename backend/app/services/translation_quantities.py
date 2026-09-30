"""Deterministic magnitude localization for report translation (English ⇄ Chinese).

Why this exists
---------------
Numbers are protected byte-for-byte during translation, so the model only chooses
the words around them.  English groups magnitudes by thousands (million, billion,
trillion) while Chinese groups them by ten-thousands (万, 亿, 万亿): "$3.7 billion"
is "37亿美元".  With the numeral frozen the model wrote "3.7 亿美元" (ten times too
small) and "$255 million" as "255 万美元" (a hundred times too small), and no
integrity guard could notice, because every numeral was still present.

The fix mirrors ``translation_dates``:

* ``QUANTITY_PATTERN`` / ``interpret_quantity_match`` recognize an amount (an
  optional currency, a number or numeric range, a magnitude word, an optional
  currency word) and the translator protects it as one atomic ``⟦Q…⟧`` token
  rendered deterministically in the target language (``render_quantity``).
* ``mask_quantities`` makes cross-language comparisons count each amount by its
  value (``qty:3700000000``) instead of by loose numerals, so a faithful "37亿"
  matches "3.7 billion" and a ten-times-wrong "3.7亿" does not.  Values below one
  million are written without a magnitude word in English ("40万" → "400,000"), so
  their fact is that grouped numeral, which the English rendering carries as a
  plain number.

Currency is rendered but is not part of the fact: a translator may legitimately
move a currency word ("3 billion in US dollars" → "30亿美元"); the error guarded
here is magnitude.  "thousand" is left alone (Chinese 千 is the same unit, so the
frozen numeral stays right), single-letter suffixes ("$125M", "€2B") count only
after a currency symbol so a company name like 3M stays intact, a year followed
by a spaced 万-word ("2025 万科", Vanke) is not an amount, and a mixed Chinese form
("1亿5000万") is read as two amounts, which fails closed.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Dict, List, NamedTuple, Optional, Tuple

_SP = r"[  ]"
_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_EN_PREFIX = r"(?:US\$|\$|€|£|¥|(?:USD|EUR|GBP|CNY|RMB|JPY)(?=[  ]?\d))"
_EN_RANGE_PREFIX = r"(?:US\$|\$|€|£|¥)"
_EN_SCALE_WORD = r"(?i:million|billion|trillion|bn|mn|tn)"
_EN_CURRENCY_WORD = (
    r"(?:US" + _SP + r"dollars|dollars|euros|pounds|yuan|renminbi|yen"
    r"|USD|EUR|GBP|CNY|RMB|JPY)"
)
# Longest first so 万亿 wins over 万 and 千万 over 千亿's prefix.
_ZH_SCALE_WORD = r"(?:万亿|千亿|百亿|十亿|亿|千万|百万|十万|万)"
_ZH_PREFIX = r"(?:US\$|\$|€|£|¥|人民币)"
_ZH_CURRENCY_WORD = r"(?:美元|欧元|英镑|日元|元人民币|人民币|元)"
# A year never opens an amount range: "fell from $237 billion in 2024 to $200 billion"
# is two amounts, not 2024–200 billion.
_NOT_AFTER_YEAR = r"(?<!(?<![\d.,])(?:19|20)\d{2})"

# One alternation shared by the translator (inside its inline-token regex) and
# ``mask_quantities``.  Scoped case-sensitive like ``DATE_PATTERN`` so embedding it
# in an IGNORECASE regex cannot turn "usd" or "m" into a currency or a magnitude.
QUANTITY_PATTERN = (
    r"(?P<qty>(?-i:"
    # English: "$3.7 billion", "USD 150 billion", "150–165 million", "$125M", "5bn"
    rf"(?:(?<![A-Za-z0-9_])(?P<qa_p>{_EN_PREFIX}){_SP}?|(?<![A-Za-z0-9_.,]))"
    rf"(?P<qa_n1>{_NUM})"
    rf"(?:{_NOT_AFTER_YEAR}(?:{_SP}*[–—-]{_SP}*|{_SP}+to{_SP}+)"
    rf"{_EN_RANGE_PREFIX}?(?P<qa_n2>{_NUM}))?"
    rf"(?:(?:{_SP}*|-)(?P<qa_s>{_EN_SCALE_WORD})(?![A-Za-z])"
    r"|(?(qa_p)(?P<qa_l>[mMbBT])(?![A-Za-z0-9])|(?!)))"
    rf"(?:{_SP}+(?P<qa_c>{_EN_CURRENCY_WORD})(?![A-Za-z]))?"
    # Chinese: "37亿美元", "$37亿", "1.5–1.65亿美元", "8,200亿", "40万"
    rf"|(?:(?P<qz_p>{_ZH_PREFIX})[ ]?|(?<![\d.,]))"
    rf"(?P<qz_n1>{_NUM})"
    rf"(?:{_NOT_AFTER_YEAR}[ ]*(?:[–—~～-]|至|到)[ ]*(?P<qz_n2>{_NUM}))?"
    rf"[ ]*(?P<qz_s>{_ZH_SCALE_WORD})"
    rf"(?:[ ]*(?P<qz_c>{_ZH_CURRENCY_WORD}))?"
    r"))"
)

QUANTITY_RE = re.compile(QUANTITY_PATTERN)

_EN_SCALE: Dict[str, int] = {
    "million": 6, "billion": 9, "trillion": 12, "mn": 6, "bn": 9, "tn": 12,
    "m": 6, "b": 9, "t": 12,
}
_ZH_SCALE: Dict[str, int] = {
    "万": 4, "十万": 5, "百万": 6, "千万": 7, "亿": 8, "十亿": 9, "百亿": 10,
    "千亿": 11, "万亿": 12,
}
_CURRENCY: Dict[str, str] = {
    "US$": "USD", "$": "USD", "USD": "USD", "dollars": "USD", "US dollars": "USD",
    "美元": "USD",
    "€": "EUR", "EUR": "EUR", "euros": "EUR", "欧元": "EUR",
    "£": "GBP", "GBP": "GBP", "pounds": "GBP", "英镑": "GBP",
    "CNY": "CNY", "RMB": "CNY", "yuan": "CNY", "renminbi": "CNY", "人民币": "CNY",
    "元": "CNY", "元人民币": "CNY",
    "JPY": "JPY", "yen": "JPY", "日元": "JPY",
    # ¥ is both yen and yuan; it is carried as a symbol, never resolved.
    "¥": "¥",
}
# (prefix, suffix) per currency in each target language.
_ZH_CURRENCY_RENDER: Dict[str, Tuple[str, str]] = {
    "USD": ("", "美元"), "EUR": ("", "欧元"), "GBP": ("", "英镑"),
    "CNY": ("", "元"), "JPY": ("", "日元"), "¥": ("¥", ""),
}
_EN_CURRENCY_RENDER: Dict[str, str] = {
    "USD": "$", "EUR": "€", "GBP": "£", "CNY": "RMB ", "JPY": "¥", "¥": "¥",
}
_ONE_MILLION = Decimal(10) ** 6


class Quantity(NamedTuple):
    """One recognized amount; ``values`` holds one number, or two for a range."""

    start: int
    end: int
    values: Tuple[Decimal, ...]
    currency: Optional[str]
    lang: str


def _decimal(text: str) -> Optional[Decimal]:
    try:
        return Decimal(text.replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def _normalize_currency(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return _CURRENCY.get(re.sub(r"[  ]+", " ", text.strip()))


def interpret_quantity_match(match: "re.Match[str]") -> Optional[Quantity]:
    """Interpret a match of ``QUANTITY_PATTERN`` (standalone or embedded)."""
    if match.group("qty") is None:
        return None
    if match.group("qa_n1") is not None:
        lang = "en"
        scale_text = match.group("qa_s") or match.group("qa_l") or ""
        exponent = _EN_SCALE.get(scale_text.lower())
        numbers = (match.group("qa_n1"), match.group("qa_n2"))
        currency = _normalize_currency(match.group("qa_p")) or _normalize_currency(
            match.group("qa_c")
        )
    else:
        lang = "zh"
        exponent = _ZH_SCALE.get(match.group("qz_s") or "")
        numbers = (match.group("qz_n1"), match.group("qz_n2"))
        if (
            numbers[1] is None
            and re.fullmatch(r"(?:19|20)\d{2}", numbers[0])
            and match.string[match.end("qz_n1"):match.start("qz_s")].strip(" ") == ""
            and match.end("qz_n1") != match.start("qz_s")
        ):
            # "截至 2025 万科…" is a year before a name (Vanke), not 20.25 million;
            # a spaced amount is written with its magnitude attached ("2025万").
            return None
        currency = _normalize_currency(match.group("qz_p")) or _normalize_currency(
            match.group("qz_c")
        )
    if exponent is None:
        return None
    values = []
    for number in numbers:
        if number is None:
            continue
        value = _decimal(number)
        if value is None:
            return None
        values.append(value * (Decimal(10) ** exponent))
    start, end = match.span("qty")
    return Quantity(start, end, tuple(values), currency, lang)


def _plain(value: Decimal) -> str:
    """Decimal without exponent or trailing zeros ("37", "2.55", "100")."""
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _grouped(value: Decimal) -> str:
    """Plain decimal with thousands separators ("400,000", "12,345.6")."""
    integer, _dot, fraction = _plain(value).partition(".")
    grouped = f"{int(integer):,}"
    return grouped + (f".{fraction}" if fraction else "")


def _unit(value: Decimal, units: Tuple[Tuple[int, str], ...]) -> Tuple[int, str]:
    for exponent, name in units:
        if value >= Decimal(10) ** exponent:
            return exponent, name
    return 0, ""


_ZH_UNITS = ((12, "万亿"), (8, "亿"), (4, "万"))
_EN_UNITS = ((12, "trillion"), (9, "billion"), (6, "million"))


def render_quantity(quantity: Quantity, lang: str) -> str:
    """Render an amount in the target language's standard written form."""
    units = _ZH_UNITS if lang == "zh" else _EN_UNITS
    parts = [_unit(value, units) for value in quantity.values]
    amounts = [
        _grouped(value) if exponent == 0 else _plain(value / (Decimal(10) ** exponent))
        for value, (exponent, _name) in zip(quantity.values, parts, strict=True)
    ]
    shared_unit = len({name for _exponent, name in parts}) == 1
    if lang == "zh":
        prefix, suffix = _ZH_CURRENCY_RENDER.get(quantity.currency or "", ("", ""))
        if shared_unit:
            body = "–".join(amounts) + parts[0][1]
        else:
            body = "–".join(
                amount + name for amount, (_e, name) in zip(amounts, parts, strict=True)
            )
        return prefix + body + suffix
    prefix = _EN_CURRENCY_RENDER.get(quantity.currency or "", "")
    if shared_unit:
        name = parts[0][1]
        return prefix + "–".join(amounts) + (f" {name}" if name else "")
    return "–".join(
        prefix + amount + (f" {name}" if name else "")
        for amount, (_e, name) in zip(amounts, parts, strict=True)
    )


def quantity_facts(quantity: Quantity) -> List[str]:
    """Language-neutral facts of an amount: ``qty:<value>`` from one million up,
    else the grouped numeral an English rendering carries as a plain number."""
    return [
        f"qty:{_plain(value)}" if value >= _ONE_MILLION else _grouped(value)
        for value in quantity.values
    ]


def find_quantities(text: str) -> List[Quantity]:
    """Return every recognized amount in ``text``, left to right."""
    found: List[Quantity] = []
    for match in QUANTITY_RE.finditer(text or ""):
        quantity = interpret_quantity_match(match)
        if quantity is not None:
            found.append(quantity)
    return found


def mask_quantities(text: str) -> Tuple[str, List[str]]:
    """Blank every recognized amount and return (masked text, canonical facts)."""
    source = text or ""
    pieces: List[str] = []
    facts: List[str] = []
    cursor = 0
    for quantity in find_quantities(source):
        pieces.append(source[cursor:quantity.start])
        pieces.append(" ")
        cursor = quantity.end
        facts.extend(quantity_facts(quantity))
    pieces.append(source[cursor:])
    return "".join(pieces), facts


# Model-facing rule appended to translation prompts whenever a ⟦Q…⟧ token is present.
QUANTITY_TOKEN_RULE = (
    "Tokens shaped ⟦Q…⟧ are complete amounts (number, magnitude and currency) already "
    "written in the target language: copy each exactly once where the amount belongs, "
    "and never add a magnitude word (million, billion, trillion, 万, 亿, 万亿), a "
    "currency word or symbol, or a numeral next to one."
)

_ZH_REDUNDANT_SCALE = r"(?:万亿|千亿|百亿|十亿|亿|千万|百万|十万|万)"
_ZH_REDUNDANT_CURRENCY = r"(?:美元|欧元|英镑|日元|元人民币|人民币|元)"
_EN_REDUNDANT_SCALE = r"(?:million|billion|trillion)"
_EN_REDUNDANT_CURRENCY = (
    r"(?:US dollars|dollars|euros|pounds|yuan|renminbi|yen|USD|EUR|GBP|CNY|RMB|JPY)"
)


def strip_redundant_quantity_unit(candidate: str, placeholder: str, rendered: str) -> str:
    """Drop a magnitude or currency a model repeated around a complete amount token.

    A translator that sees "raised ⟦QA⟧" sometimes writes "⟦QA⟧亿美元" or
    "$⟦QA⟧ billion"; restored, that would read "37亿美元亿美元".  The rendered
    amount already carries its magnitude and currency, so a copy directly next to
    the token is always redundant.  A currency the rendering does not carry is
    the model's own (correct) addition and stays.
    """
    token = re.escape(placeholder)
    if re.search(r"[一-鿿]", rendered):
        words = [_ZH_REDUNDANT_SCALE]
        if re.search(_ZH_REDUNDANT_CURRENCY + r"$", rendered):
            words.append(_ZH_REDUNDANT_CURRENCY)
        return re.sub(token + r"(?:[ ]*(?:" + "|".join(words) + r"))+", placeholder, candidate)
    words = []
    if re.search(_EN_REDUNDANT_SCALE + r"$", rendered):
        words.append(_EN_REDUNDANT_SCALE)
    if rendered.startswith(tuple(_EN_CURRENCY_RENDER.values())):
        words.append(_EN_REDUNDANT_CURRENCY)
        candidate = re.sub(
            r"(?:US\$|\$|€|£|¥|RMB[  ]?)" + token, placeholder, candidate
        )
    if words:
        candidate = re.sub(
            token + r"(?:[  ]+(?:" + "|".join(words) + r")(?![A-Za-z]))+",
            placeholder,
            candidate,
        )
    return candidate
