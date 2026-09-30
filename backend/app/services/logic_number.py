"""Alias-aware probability-slot audit and deterministic slot repair (REPORT-3, P08 stage 1b).

S11 (``ReportAgent._audit_numeric_consistency`` and
``report_lint.check_scenario_probabilities``) anchors on the first occurrence of each
scenario's full name.  A probability written against any other name of a scenario is
invisible to it: report_ffe1ea6bf50d published the summary blockquote "基准情景（40%）"
while forecast.json held A：基准扩张 = 0.35, and the final audit passed.

This module reads a scenario probability only in a strict slot that names one
scenario by an alias:

* ``ALIAS（N%）`` / ``ALIAS (N%)``, optionally with 概率 / probability / 约 / ~ / ≈ /
  about inside the brackets ("基准情景（约40%）", "Scenario A (probability ~40%)");
* ``ALIAS（概率 0.NN）`` / ``ALIAS (probability 0.NN)``;
* ``ALIAS：N% 概率`` / ``ALIAS: N% probability``;
* ``N% 的概率 / 可能性 ALIAS`` ("仅10%概率超预期上行");
* ``ALIAS at N% probability``.

Aliases (``derive_scenario_aliases``) are the full name, an enumerator label at the
start of the name ("A：" → 情景A / A情景 / Scenario A / scenario A), the core after
the label, the head of the core before its first bracket or separator, and role words
("基准情景", "baseline", "upside" …) resolved to the one scenario whose name carries
the role keyword.  The roles deliberately do not use
``forecast_extractor._is_residual_scenario_name``: it counts 基准 / baseline as
residual, so "基准情景" would never resolve on "A：基准扩张".  An alias that could
name two scenarios is dropped.  A bare role word, 维持现状 or a two-character CJK name
part is also an ordinary word ("价格上行（10%）" is a price move), so before a bracket,
colon or "at" slot it counts only when it stands free (after punctuation, a preposition
or a determiner), and after "N%的概率" only with a scenario word right after it
("有40%的概率走向基准路径"; "油价有40%的概率上行" is a price move).

A slot whose number differs from the scenario's probability by more than ``tol_pt``
points is a finding.  REPORT-2's range, quantity, sum and market guards
(``narrative_sync``), an inline quotation, a conditional opener ("若进入B情景，则有40%
的概率…") and a history context ("此前…", "…已下调至35%", "…→ 35%") make it
``unresolved``: it is reported, never rewritten.  Everything else is ``fixable``, and
``substitute_probability_slots`` rewrites exactly the number, keeping its format
("40%" → "35%", "0.40" → "0.35", "约40%" → "约35%").
``audit_markdown`` scans a report, skipping fenced blocks, the References appendix,
the deterministic Part-1 block and every blockquote except the system summary
blockquote right after the H1.  No LLM, no IO.
"""

from __future__ import annotations

import logging
import math
import re
from bisect import bisect_right
from collections import Counter
from functools import lru_cache
from typing import (
    Any, Callable, Dict, FrozenSet, List, NamedTuple, Optional, Pattern, Sequence, Set, Tuple,
)

from .forecast_extractor import (
    BINARY_FORECAST_END_MARKER,
    BINARY_FORECAST_START_MARKER,
    markdown_fence_transition,
)
from .narrative_sync import market_guard_for, quantity_guarded, range_guarded, sum_guard_for

logger = logging.getLogger(__name__)

GATE_MODES = ("off", "observe", "numeric")
DEFAULT_GATE = "observe"
LOGIC_NUMBER_FINDINGS_CAP = 24
FINDING_CODE = "stale_probability_number"
_EXCERPT_MAX_CHARS = 180
_EXCERPT_CONTEXT_CHARS = 60

# ------------------------------------------------------------------ aliases
# An enumerator label at the start of a name ("A：基准扩张", "IV. Collapse", "C) Bear",
# also after "Scenario" / "情景": "Scenario B: Recession"), then the core.
_ENUMERATOR_RE = re.compile(
    r"^(?:[Ss]cenario\s+|情景\s*)?(?P<label>IV|V|I{1,3}|[A-E])\s*[：:.、．)）]\s*(?P<core>\S.*)$",
    re.S,
)
# The head of a core ends at its first bracket or separator.
_HEAD_END_RE = re.compile(r"[（(;；—–:：/]")
_LATIN_LETTER_RE = re.compile(r"[A-Za-z]")
_CJK_CHAR_RE = re.compile(r"[\u3400-\u9fff]")
# A generic or residual word alone names no scenario: every breakdown has an "Other
# (20%)" row, and "情景（40%）" is any scenario.
_GENERIC_ALIAS_KEYS = frozenset({
    "other", "others", "其它", "其他", "mixed", "混合",
    "case", "cases", "scenario", "scenarios", "path", "outcome",
    "情景", "场景", "路径", "情形",
})
# Role words, each resolved to the unique scenario whose name holds the role keyword.
_ROLE_ALIASES: Tuple[Tuple[Tuple[str, ...], Pattern[str]], ...] = (
    (("基准情景", "基准", "主情景", "base case", "baseline scenario", "baseline"),
     re.compile(r"基准|主情景|(?<![a-z])(?:baseline|base[\s-]?case)", re.I)),
    (("上行情景", "上行", "upside", "bull case"),
     re.compile(r"上行|(?<![a-z])(?:upside|bull)", re.I)),
    (("下行情景", "下行", "downside", "bear case"),
     re.compile(r"下行|(?<![a-z])(?:downside|bear)", re.I)),
    (("维持现状", "兜底", "其他情景", "其它情景", "status quo"),
     re.compile(r"维持现状|兜底|其他|其它|(?<![a-z])(?:status[\s-]quo|other)", re.I)),
)
# Weak aliases are also ordinary words ("价格上行（10%）" is a price move, "高于基准（40%）" a
# benchmark, "租金维持现状（70%）" a rent that stays put): the bare role words, 维持现状 and
# two-character CJK name parts.  Before a bracket, colon or "at" slot one names a
# scenario only when it stands free — after punctuation, the line start, a CJK
# preposition / conjunction or an English determiner; after "N%的概率" only with a
# scenario word right after it (_SCENARIO_WORD_RE).
_WEAK_ROLE_ALIASES = frozenset({"基准", "上行", "下行", "兜底", "维持现状",
                                "baseline", "upside", "downside"})
_FREE_CJK_LEADS = frozenset("在与和及或、即为是按以对")
_FREE_LATIN_LEADS = frozenset({
    "the", "a", "an", "our", "this", "that", "its", "in", "of", "for", "under", "to",
    "and", "or", "vs", "versus", "with", "on", "at", "is", "as",
})
_TRAILING_WORD_RE = re.compile(r"[A-Za-z]+$")

# ------------------------------------------------------------------ slots
# Model text reaches every pattern below, so each must stay linear on it.  Each run of
# spaces or emphasis is possessive (``*+`` / ``{0,3}+``) and is followed by a token that
# cannot start with a space or emphasis mark: adjacent runs never trade characters on a
# failed match, so a line of 20 000 spaces costs linear time, not quadratic or cubic.
_WS = r"[ \t]*+"
# Markdown emphasis between a label and its slot ("**基准情景**（40%）").
_EMPHASIS = r"[*_]{0,3}+"
_HEDGE = r"(?:(?:约|大约|~|～|≈)" + _WS + r"|(?:about|approx\.?)[ \t]++)?"
# 1-3 digits with an optional decimal part and a percent sign; only ASCII digits, since a
# replacement is written in ASCII.
_PERCENT = r"(?P<num>[0-9]{1,3}(?:\.[0-9]+)?)" + _WS + r"(?P<sym>[%％])"
_ALIAS_TAILS: Tuple[Tuple[str, Pattern[str]], ...] = (
    ("percent", re.compile(
        _EMPHASIS + _WS + r"[（(]" + _WS + r"(?:(?:概率|probability)" + _WS + r"[:：]?" + _WS + r")?"
        + _HEDGE + _PERCENT + _WS + r"(?:的?" + _WS + r"(?:概率|可能性)|probability)?" + _WS
        + r"[)）]",
        re.I)),
    ("decimal", re.compile(
        _EMPHASIS + _WS + r"[（(]" + _WS + r"(?:概率|probability)" + _WS + r"[:：=]?" + _WS
        + _HEDGE + r"(?P<num>0?\.[0-9]{2})(?![0-9])" + _WS + r"[)）]",
        re.I)),
    ("percent", re.compile(
        _EMPHASIS + _WS + r"[:：]" + _WS + _EMPHASIS + _WS + _HEDGE + _PERCENT + _WS
        + r"(?:的" + _WS + r")?(?:概率|可能性|probability(?![A-Za-z]))",
        re.I)),
    ("percent", re.compile(
        _EMPHASIS + r"[ \t]++at[ \t]++" + _HEDGE + _PERCENT + _WS + r"probability(?![A-Za-z])",
        re.I)),
)
# "N% 的概率 / 可能性 ALIAS", optionally with an occurrence verb before the alias
# ("有40%的概率进入基准情景").
_NUMBER_FIRST_RE = re.compile(
    r"(?<![0-9.,])" + _PERCENT + _WS + r"(?:的" + _WS + r")?(?:概率|可能性)" + _WS)
_OCCURRENCE_VERB_RE = re.compile(r"(?:出现|走向|进入|落入|实现|发生|维持|处于)" + _WS)
_EMPHASIS_RE = re.compile(_EMPHASIS)
# After "N%的概率" a weak alias names a scenario only with a scenario word right after
# it ("有40%的概率走向基准路径"): "油价有40%的概率上行" is a price move, "有70%的概率维持现状"
# a rent that stays put, "有40%的概率维持基准水平" a level.
_SCENARIO_WORD_RE = re.compile(
    _EMPHASIS + _WS + r"(?:情景|场景|路径|情形|(?i:case|scenario|path)(?![A-Za-z]))")

# ------------------------------------------------------------------ guards
# Besides REPORT-2's range, quantity, sum and market guards (narrative_sync), three
# contexts make a finding unresolved — reported, never rewritten:
# * quote: the number sits inside an inline quotation (“…”, "…", 「…」, 『…』, ‘…’);
#   someone else's words are never edited;
# * conditional: a conditional opener earlier in the slot's sentence ("若进入电力受限情景，
#   则有40%的概率出现财务紧缩", "在B情景下，有60%的概率…", "given B, …") makes the number a
#   conditional probability.  An opener whose condition is the slot's own alias ("若基准
#   情景（40%）成立", "If the base case (40%) holds") keeps the slot: the bracket still
#   gives that scenario's probability.  "在…情景下" governs only its own clause (and the
#   one right after its comma): "在基准扩张（40%）路径下装机稳步兑现，仅10%概率超预期上行"
#   gives D's own probability;
# * history: the slot states an earlier value or a change ("此前基准情景（40%）", "上季度
#   基准情景（40%）", "基准情景（40%）已下调至35%", "基准情景（40%）→ 35%", "基准情景（40%）较
#   上一版下调5个百分点", "Last quarter's base case (55%)", "Base (40%), down from 45%").
_QUOTE_RE = re.compile(
    r"“[^“”\n]{0,300}”|「[^「」\n]{0,300}」|『[^『』\n]{0,300}』|‘[^‘’\n]{0,300}’"
    r"|\"[^\"\n]{0,300}\"")
_CONDITIONAL_LOOKBACK_CHARS = 60
_SENTENCE_STOP_RE = re.compile(r"[。；;！？!?\n]|(?<![0-9])\.(?![0-9])")
_CONDITIONAL_RE = re.compile(
    r"若(?!干)|如果|假如|倘若|一旦|假设|假定|条件于|以[^，,。；;！？!?\n]{1,16}?为条件"
    r"|(?P<under>在[^，,。；;！？!?\n]{0,24}?(?:情景|场景|路径|情形|条件|假设)下)"
    r"|(?<![A-Za-z])(?:if|given|assuming|conditional[ \t]+(?:on|upon)|provided[ \t]+that"
    r"|in[ \t]+the[ \t]+event)(?![A-Za-z])",
    re.I,
)
# Between an opener and an alias-first slot, only an occurrence verb or a determiner:
# the opener's condition is that slot's own scenario.
_OWN_CONDITION_RE = re.compile(
    r"[ \t*_]*+(?:(?:进入|出现|走向|落入|实现|发生|处于|the|our|a)(?![A-Za-z])[ \t*_]*+)?", re.I)
_CLAUSE_BREAK_RE = re.compile(r"[，,、：:]")
_HISTORY_LOOKBACK_CHARS = 24
_HISTORY_BEFORE_RE = re.compile(
    r"(?:此前|之前|原先|原本|原来|先前|最初|初判|初始|上一版|前一版|旧版|前版|上一?期|上一?季度?"
    r"|上次|上一轮|去年|上年|上月"
    r"|(?<![A-Za-z])(?:previously|previous|prior|earlier|initially|originally|formerly"
    r"|last[ \t]+(?:quarter|year|month|week|round|version|update|report|edition))(?![A-Za-z]))"
    r"[^。；;！？!?\n]{0,12}$",
    re.I,
)
_HISTORY_AFTER_RE = re.compile(
    r"[ \t*_]*+(?:[，,]" + _WS + r")?(?:"
    r"→|->|=>|⇒"
    r"|(?:较|相比|相较于?|对比)" + _WS
    + r"(?:上一?版|前一?版|旧版|此前|之前|先前|上一?期|上一?季度?|上次|上一轮|去年|上年|上月)"
    r"|(?:已经?|被|后|随后|再)?" + _WS
    + r"(?:下调|上调|调降|调升|下修|上修|降至|升至|降为|升为|调整|修正)"
    r"|(?:(?:was|were|is|are|(?:has|have|had)[ \t]++been)[ \t]++)?"
    r"(?:revised|cut|lowered|raised|trimmed|reduced|increased|moved)(?![A-Za-z])"
    r"|(?:down|up)[ \t]++from(?![A-Za-z]))",
    re.I,
)
# Guards that find a number which is not this report's current probability of the named
# scenario (a market's or an outside forecaster's, a quotation's, a conditional or an
# earlier one): the audit reports it, but it contradicts nothing, so it is no S11
# mismatch.  Range, quantity and sum findings may be stale claims and stay in S11.
_NOT_OWN_CLAIM_GUARDS = frozenset({"market", "quote", "conditional", "history"})

# ------------------------------------------------------------------ markdown scope
# The heading text keeps its trailing spaces (callers strip it): a lazy text before an
# optional trailing-space run would be quadratic on a heading line full of spaces.
_HEADING_RE = re.compile(r"^[ \t]{0,3}(#{1,6})(?:[ \t]+(.*))?$")
_REFERENCES_HEADING_RE = re.compile(r"^(?:references?|参考文献|参考来源)(?![A-Za-z])", re.I)
_BLOCKQUOTE_RE = re.compile(r"^[ \t]{0,3}>")
_HEADING_STRIP_CHARS = " \t*_"


class _AliasTable(NamedTuple):
    """Compiled aliases of one tuple of scenario names (see ``_alias_table``)."""

    regex: Optional[Pattern[str]]
    group_index: Dict[str, int]          # regex group name -> scenario index
    weak_groups: FrozenSet[str]          # groups of weak aliases (see _WEAK_ROLE_ALIASES)
    alias_to_index: Dict[str, int]       # alias as spelt -> scenario index
    ambiguous: int                       # distinct aliases dropped as ambiguous


_WARNED_GATE_VALUES: Set[str] = set()


def resolve_gate(value: Any) -> str:
    """The effective REPORT_LOGIC_NUMBER_GATE mode; an unknown value acts as 'observe'
    and is logged once."""
    mode = str(value if value is not None else "").strip().lower()
    if mode in GATE_MODES:
        return mode
    if mode not in _WARNED_GATE_VALUES:
        _WARNED_GATE_VALUES.add(mode)
        logger.warning("REPORT_LOGIC_NUMBER_GATE=%r is not one of %s; using '%s'",
                       value, "/".join(GATE_MODES), DEFAULT_GATE)
    return DEFAULT_GATE


def _alias_key(alias: str) -> str:
    """Case- and space-insensitive identity of an alias (ambiguity is judged on it)."""
    return "".join(alias.casefold().split())


def _is_ascii_alnum(char: str) -> bool:
    return char.isascii() and char.isalnum()


def _distinctive(alias: str) -> bool:
    """A name-derived alias is kept when it has >=4 Latin letters or >=2 CJK characters
    and is not a generic or residual word alone."""
    if _alias_key(alias) in _GENERIC_ALIAS_KEYS:
        return False
    return len(_LATIN_LETTER_RE.findall(alias)) >= 4 or len(_CJK_CHAR_RE.findall(alias)) >= 2


def _bounded(alias: str, body: str) -> str:
    """Latin ends need non-letter boundaries ("non-baseline" is no "baseline"); a CJK
    alias right after 非 is its negation ("非基准情景")."""
    if _is_ascii_alnum(alias[0]):
        body = r"(?<![A-Za-z0-9_-])" + body
    elif _CJK_CHAR_RE.match(alias[0]):
        body = r"(?<!非)" + body
    if _is_ascii_alnum(alias[-1]):
        body += r"(?![A-Za-z0-9_])"
    return body


def _words_pattern(text: str) -> str:
    return r"\s+".join(re.escape(word) for word in text.split(" "))


def _name_pattern(alias: str) -> str:
    """A name part keeps its first character exact and ignores case after it
    ("Recession" names the scenario, "a recession" does not)."""
    body = re.escape(alias[0])
    if len(alias) > 1:
        body += "(?i:" + _words_pattern(alias[1:]) + ")"
    return _bounded(alias, body)


def _role_pattern(alias: str) -> str:
    """A role word ignores case ("Baseline", "Base case")."""
    return _bounded(alias, "(?i:" + _words_pattern(alias) + ")")


def _enumerator_aliases(label: str) -> List[Tuple[str, str]]:
    """``(alias, pattern)`` for an enumerator label: spacing may vary ("情景 A"), the
    label itself is exact."""
    return [
        (f"情景{label}", r"情景\s*" + label + r"(?![A-Za-z0-9])"),
        (f"{label}情景", r"(?<![A-Za-z0-9])" + label + r"\s*情景"),
        (f"Scenario {label}", r"(?<![A-Za-z0-9_-])Scenario\s+" + label + r"(?![A-Za-z0-9])"),
        (f"scenario {label}", r"(?<![A-Za-z0-9_-])scenario\s+" + label + r"(?![A-Za-z0-9])"),
    ]


def _name_aliases(name: str) -> List[Tuple[str, str]]:
    """``(alias, pattern)`` pairs a text may use for the scenario called ``name``: the
    enumerator aliases, then the full name, the core and its head when distinctive."""
    aliases: List[Tuple[str, str]] = []
    core = name
    enumerated = _ENUMERATOR_RE.match(name)
    if enumerated:
        core = enumerated.group("core").strip()
        aliases += _enumerator_aliases(enumerated.group("label"))
    head_end = _HEAD_END_RE.search(core)
    head = core[:head_end.start()].strip() if head_end else core
    for part in dict.fromkeys((name, core, head)):
        if part and _distinctive(part):
            aliases.append((part, _name_pattern(part)))
    return aliases


@lru_cache(maxsize=64)
def _alias_table(names: Tuple[str, ...]) -> _AliasTable:
    """Compile the aliases of the scenarios called ``names`` (by position).

    A role word is offered to every scenario whose name holds its keyword.  An alias
    whose key (``_alias_key``) would then name more than one scenario is dropped and
    counted; the survivors form one alternation, longest alias first, with one named
    group per alias so a match tells its scenario.
    """
    entries: List[Tuple[str, str, int]] = []
    for index, name in enumerate(names):
        if name:
            entries += [(alias, pattern, index) for alias, pattern in _name_aliases(name)]
    for role_aliases, keyword in _ROLE_ALIASES:
        for index, name in enumerate(names):
            if name and keyword.search(name):
                entries += [(alias, _role_pattern(alias), index) for alias in role_aliases]

    owners: Dict[str, Set[int]] = {}
    for alias, _pattern, index in entries:
        owners.setdefault(_alias_key(alias), set()).add(index)
    ambiguous = sum(1 for indexes in owners.values() if len(indexes) > 1)
    kept: Dict[Tuple[str, str], int] = {}
    for alias, pattern, index in entries:
        if len(owners[_alias_key(alias)]) == 1:
            kept.setdefault((alias, pattern), index)
    if not kept:
        return _AliasTable(None, {}, frozenset(), {}, ambiguous)

    ordered = sorted(kept.items(), key=lambda item: (-len(item[0][0]), item[0]))
    group_index: Dict[str, int] = {}
    weak_groups: Set[str] = set()
    parts: List[str] = []
    for number, ((alias, pattern), index) in enumerate(ordered):
        group = f"a{number}"
        group_index[group] = index
        if _weak(alias):
            weak_groups.add(group)
        parts.append(f"(?P<{group}>{pattern})")
    alias_to_index = {alias: index for (alias, _pattern), index in ordered}
    return _AliasTable(re.compile("|".join(parts)), group_index, frozenset(weak_groups),
                       alias_to_index, ambiguous)


def _weak(alias: str) -> bool:
    """A bare role word, 维持现状 or a two-character CJK name part (see _WEAK_ROLE_ALIASES)."""
    return (alias.casefold() in _WEAK_ROLE_ALIASES
            or (len(alias) == 2 and len(_CJK_CHAR_RE.findall(alias)) == 2))


def _stands_free(text: str, start: int) -> bool:
    """Nothing but punctuation, the line start, a CJK preposition / conjunction or an
    English determiner precedes ``text[start]`` (spaces and emphasis skipped)."""
    before = text[max(0, start - 24):start].rstrip(" \t*_")
    if not before:
        return True
    last = before[-1]
    if _CJK_CHAR_RE.match(last):
        return last in _FREE_CJK_LEADS
    if last.isascii() and last.isalpha():
        return _TRAILING_WORD_RE.search(before).group(0).lower() in _FREE_LATIN_LEADS
    return not last.isdigit()


def _scenario_name(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    name = row.get("name")
    return " ".join(name.split()) if isinstance(name, str) else ""


def _rows(scenarios: Any) -> List[Any]:
    return list(scenarios) if isinstance(scenarios, (list, tuple)) else []


def _table_for(rows: List[Any]) -> _AliasTable:
    return _alias_table(tuple(_scenario_name(row) for row in rows))


def derive_scenario_aliases(scenarios: Sequence[Dict[str, Any]]) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Map each alias (as spelt) to the index of the scenario it names.

    Returns ``(alias_to_index, stats)``; ``stats`` counts the scenarios, the kept
    aliases and the distinct aliases dropped because they could name more than one
    scenario (``ambiguous_alias``).
    """
    rows = _rows(scenarios)
    table = _table_for(rows)
    stats = {"scenarios": len(rows), "aliases": len(table.alias_to_index),
             "ambiguous_alias": table.ambiguous}
    return dict(table.alias_to_index), stats


# ------------------------------------------------------------------ detection
def _probability(row: Any) -> Optional[float]:
    """The scenario's probability when it is a finite number in [0, 1], else None."""
    if not isinstance(row, dict):
        return None
    value = row.get("probability")
    if type(value) not in (int, float):
        return None
    value = float(value)
    return value if math.isfinite(value) and 0.0 <= value <= 1.0 else None


def _plain_number(value: float) -> Any:
    return int(value) if float(value).is_integer() else round(value, 3)


def _replacement(number_text: str, form: str, probability: float, expected_pct: int) -> str:
    """The expected value written like ``number_text`` (decimals, leading zero)."""
    if form == "decimal":
        rendered = f"{expected_pct / 100:.2f}"
        return rendered[1:] if number_text.startswith(".") else rendered
    decimals = len(number_text.split(".", 1)[1]) if "." in number_text else 0
    return f"{probability * 100:.{decimals}f}" if decimals else str(expected_pct)


class _Slot(NamedTuple):
    index: int              # scenario index
    alias: str              # the alias as written
    lo: int                 # slot start (alias or number, whichever comes first)
    hi: int                 # slot end (after a closing bracket, probability word or alias)
    form: str               # "percent" | "decimal"
    token_end: int          # end of the guarded token (after the percent sign)
    alias_first: bool       # the alias comes before the number


def _collect_slots(text: str, table: _AliasTable) -> Tuple[Dict[Tuple[int, int], _Slot], int]:
    """Strict slots of ``text`` keyed by number span; a number two slots attribute to
    different scenarios is dropped and counted."""
    slots: Dict[Tuple[int, int], _Slot] = {}
    conflicted: Set[Tuple[int, int]] = set()

    def record(number: "re.Match[str]", alias: "re.Match[str]", form: str) -> None:
        span = number.span("num")
        token_end = number.end("sym") if form == "percent" else number.end("num")
        slot = _Slot(table.group_index[alias.lastgroup], alias.group(0),
                     min(alias.start(), span[0]), max(alias.end(), number.end()), form, token_end,
                     alias.start() < span[0])
        previous = slots.get(span)
        if previous is None:
            slots[span] = slot
        elif previous.index != slot.index:
            conflicted.add(span)

    for alias in table.regex.finditer(text):
        if alias.lastgroup in table.weak_groups and not _stands_free(text, alias.start()):
            continue
        for form, tail_re in _ALIAS_TAILS:
            tail = tail_re.match(text, alias.end())
            if tail:
                record(tail, alias, form)
                break
    for number in _NUMBER_FIRST_RE.finditer(text):
        position = number.end()
        verb = _OCCURRENCE_VERB_RE.match(text, position)
        for start in (position, verb.end()) if verb else (position,):
            alias = table.regex.match(text, _EMPHASIS_RE.match(text, start).end())
            if alias and (alias.lastgroup not in table.weak_groups
                          or _SCENARIO_WORD_RE.match(text, alias.end())):
                record(number, alias, "percent")
                break
    for span in conflicted:
        del slots[span]
    return slots, len(conflicted)


def _conditional(text: str, slot: _Slot) -> bool:
    """A conditional opener earlier in the sentence of ``slot`` governs it (see the
    conditional guard above)."""
    lower = max(0, slot.lo - _CONDITIONAL_LOOKBACK_CHARS)
    for stop in _SENTENCE_STOP_RE.finditer(text, lower, slot.lo):
        lower = stop.end()
    for opener in _CONDITIONAL_RE.finditer(text, lower, slot.lo):
        if slot.alias_first and _OWN_CONDITION_RE.fullmatch(text, opener.end(), slot.lo):
            continue
        if opener.lastgroup == "under":
            clause = opener.end() + (text[opener.end():opener.end() + 1] in ("，", ","))
            if _CLAUSE_BREAK_RE.search(text, clause, slot.lo):
                continue
        return True
    return False


class _Guards:
    """The guards of one scanned text, in order; ``guard(start, slot, name)`` names the
    first that fires, or None.  The sum, market and quotation checks are built once, on
    first use, and answer each slot by bisection, so a scan stays linear in its text."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._sum: Optional[Callable[[int, int], bool]] = None
        self._market: Optional[Callable[[int, int], bool]] = None
        self._quotes: Optional[Tuple[List[int], List[int]]] = None

    def _quoted(self, start: int) -> bool:
        if self._quotes is None:
            spans = [match.span() for match in _QUOTE_RE.finditer(self._text)]
            self._quotes = ([lo for lo, _ in spans], [hi for _, hi in spans])
        starts, ends = self._quotes
        quote = bisect_right(starts, start) - 1
        return quote >= 0 and start < ends[quote]

    def guard(self, start: int, slot: _Slot, name: str) -> Optional[str]:
        text = self._text
        if range_guarded(text, start, slot.token_end):
            return "range"
        if quantity_guarded(text, start, slot.token_end, (name,)):
            return "quantity"
        if self._sum is None:
            self._sum = sum_guard_for(text)
        if self._sum(start, slot.token_end):
            return "sum"
        if self._market is None:
            self._market = market_guard_for(text)
        # The slot end, so a citation right after the bracket counts ("基准情景（60%）（高盛）").
        if self._market(start, slot.hi):
            return "market"
        if self._quoted(start):
            return "quote"
        if _conditional(text, slot):
            return "conditional"
        if (_HISTORY_BEFORE_RE.search(text, max(0, slot.lo - _HISTORY_LOOKBACK_CHARS), slot.lo)
                or _HISTORY_AFTER_RE.match(text, slot.hi)):
            return "history"
        return None


def _scan(text: str, rows: List[Any], table: _AliasTable, tol_pt: float) -> Tuple[List[Dict[str, Any]], int]:
    """Findings of ``text`` (offsets local to it) and the count of conflicted slots."""
    if table.regex is None or not text:
        return [], 0
    slots, conflicted = _collect_slots(text, table)
    findings: List[Dict[str, Any]] = []
    guards = _Guards(text)
    for (start, end), slot in sorted(slots.items()):
        probability = _probability(rows[slot.index])
        if probability is None:
            continue
        number_text = text[start:end]
        # Rounded so a fraction reads as its percent exactly (0.40 * 100 is 40.00000000000001).
        claimed = round(float(number_text) * (100 if slot.form == "decimal" else 1), 6)
        if claimed > 100:
            continue
        expected_pct = round(probability * 100)
        if abs(claimed - expected_pct) <= tol_pt:
            continue
        name = _scenario_name(rows[slot.index])
        guard = guards.guard(start, slot, name)
        excerpt = text[max(0, slot.lo - _EXCERPT_CONTEXT_CHARS):slot.hi + _EXCERPT_CONTEXT_CHARS]
        finding: Dict[str, Any] = {
            "code": FINDING_CODE,
            "alias": slot.alias,
            "scenario": name,
            "claimed": _plain_number(claimed),
            "expected_pct": expected_pct,
            "start": start,
            "end": end,
            "excerpt": excerpt[:_EXCERPT_MAX_CHARS],
            "status": "unresolved" if guard else "fixable",
            "number": number_text,
            "unit": "%" if slot.form == "percent" else "",
        }
        if guard:
            finding["guard"] = guard
        else:
            finding["replacement"] = _replacement(number_text, slot.form, probability, expected_pct)
        findings.append(finding)
    return findings, conflicted


def find_probability_slots(text: Any, scenarios: Sequence[Dict[str, Any]], *,
                           tol_pt: float = 1.0) -> List[Dict[str, Any]]:
    """Alias slots of ``text`` whose number differs from the scenario's probability.

    Each finding is ``{code, alias, scenario, claimed, expected_pct, start, end,
    excerpt, status, number, unit}``: ``claimed`` in percent points, ``start`` /
    ``end`` the span of the number itself, ``status`` ``fixable`` (with its
    ``replacement``) or ``unresolved`` (with the ``guard`` that fired: range /
    quantity / sum / market / quote / conditional / history).  Scenarios whose
    probability is not a number in [0, 1] yield none.
    """
    if not isinstance(text, str) or not text:
        return []
    rows = _rows(scenarios)
    findings, _ = _scan(text, rows, _table_for(rows), float(tol_pt))
    return findings


def substitute_probability_slots(text: Any, findings: Sequence[Dict[str, Any]]) -> Tuple[Any, List[Dict[str, str]]]:
    """Rewrite the number of every ``fixable`` finding; returns ``(text, applied)``.

    A finding whose span no longer holds its number (the text changed since the
    audit), or that overlaps an earlier one, is left alone.  ``applied`` holds
    ``{scenario, alias, from, to}`` per rewrite.
    """
    if not isinstance(text, str) or not text:
        return text, []
    fixable = sorted(
        (finding for finding in findings or ()
         if isinstance(finding, dict) and finding.get("status") == "fixable"
         and type(finding.get("start")) is int and type(finding.get("end")) is int
         and isinstance(finding.get("replacement"), str)),
        key=lambda finding: finding["start"],
    )
    pieces: List[str] = []
    applied: List[Dict[str, str]] = []
    cursor = 0
    for finding in fixable:
        start, end = finding["start"], finding["end"]
        if start < cursor or text[start:end] != finding.get("number"):
            continue
        pieces += [text[cursor:start], finding["replacement"]]
        cursor = end
        unit = str(finding.get("unit") or "")
        applied.append({"scenario": str(finding.get("scenario") or ""),
                        "alias": str(finding.get("alias") or ""),
                        "from": finding["number"] + unit, "to": finding["replacement"] + unit})
    if not applied:
        return text, []
    pieces.append(text[cursor:])
    return "".join(pieces), applied


# ------------------------------------------------------------------ markdown
def _binary_block_end(lines: List[str], start: int) -> Optional[int]:
    for index in range(start, len(lines)):
        if lines[index].strip() == BINARY_FORECAST_END_MARKER:
            return index
    return None


def _scannable_spans(md: str, skip_summary_blockquote: bool, skipped: Counter) -> List[Tuple[int, int]]:
    """Character spans of the lines ``audit_markdown`` scans, one per paragraph
    (contiguous non-blank lines merged), so every guard reads only its slot's paragraph.

    The summary blockquote is the first blockquote after the H1 with only blank lines
    or the Part-1 block in between (``assemble_full_report`` writes "> {summary}"
    right under the title; the Part-1 block is later inserted between them), and it
    runs to the first line that is no blockquote.
    """
    lines = md.split("\n")
    spans: List[Tuple[int, int]] = []
    offset = 0
    fence = None
    binary_end: Optional[int] = None
    references_level: Optional[int] = None
    summary: Optional[str] = None      # None → "pending" (after the H1) → "open" → "done"
    previous_scanned = False
    for index, line in enumerate(lines):
        lo, hi = offset, offset + len(line)
        offset = hi + 1
        stripped = line.strip()
        inside_fence = fence is not None
        fence, fence_line = markdown_fence_transition(line, fence)
        reason: Optional[str] = None
        if fence_line or inside_fence:
            reason = "fenced"
            summary = "done" if summary in ("pending", "open") else summary
        elif binary_end is None and stripped == BINARY_FORECAST_START_MARKER:
            # An unterminated start marker opens nothing; the line is plain text then.
            binary_end = _binary_block_end(lines, index + 1)
            reason = "binary_block" if binary_end is not None else None
            summary = "done" if summary == "open" else summary
        elif binary_end is not None:
            reason = "binary_block"
            binary_end = None if index == binary_end else binary_end
        else:
            heading = _HEADING_RE.match(line)
            quote = heading is None and _BLOCKQUOTE_RE.match(line) is not None
            if heading:
                level = len(heading.group(1))
                if references_level is not None and level <= references_level:
                    references_level = None
                if _REFERENCES_HEADING_RE.match((heading.group(2) or "").strip(_HEADING_STRIP_CHARS)):
                    references_level = level
            if heading and summary is None and len(heading.group(1)) == 1:
                summary = "pending"
            elif quote and summary in ("pending", "open"):
                summary = "open"
            elif summary == "open" or (summary == "pending" and stripped):
                summary = "done"
            if references_level is not None:
                reason = "references"
            elif quote and summary != "open":
                reason = "blockquote"
            elif quote and skip_summary_blockquote:
                reason = "summary_blockquote"
        if reason is not None:
            skipped[reason] += 1
            previous_scanned = False
            continue
        if not stripped:
            previous_scanned = False
            continue
        if previous_scanned:
            spans[-1] = (spans[-1][0], hi)
        else:
            spans.append((lo, hi))
        previous_scanned = True
    return spans


def audit_markdown(md: Any, scenarios: Sequence[Dict[str, Any]], *,
                   skip_summary_blockquote: bool = False,
                   max_findings: Optional[int] = LOGIC_NUMBER_FINDINGS_CAP,
                   tol_pt: float = 1.0) -> Dict[str, Any]:
    """Alias-slot audit of a report's Markdown.

    Returns ``{findings, count, fixable, unresolved, skipped}``: ``findings`` (at most
    ``max_findings``; None keeps all) with offsets into ``md``; ``count`` / ``fixable``
    / ``unresolved`` over all findings; ``skipped`` counts the lines left out by scope
    (fenced / references / binary_block / blockquote / summary_blockquote), the
    aliases dropped as ambiguous (ambiguous_alias) and the numbers two slots
    attributed to different scenarios (ambiguous_slot).  Only non-zero counts appear.
    """
    text = md if isinstance(md, str) else ""
    rows = _rows(scenarios)
    table = _table_for(rows)
    skipped: Counter = Counter()
    findings: List[Dict[str, Any]] = []
    tolerance = float(tol_pt)
    for lo, hi in _scannable_spans(text, skip_summary_blockquote, skipped):
        local, conflicted = _scan(text[lo:hi], rows, table, tolerance)
        skipped["ambiguous_slot"] += conflicted
        for finding in local:
            finding["start"] += lo
            finding["end"] += lo
        findings += local
    skipped["ambiguous_alias"] += table.ambiguous
    fixable = sum(1 for finding in findings if finding["status"] == "fixable")
    if max_findings is not None:
        kept = findings[:max(0, int(max_findings))]
    else:
        kept = findings
    return {
        "findings": kept,
        "count": len(findings),
        "fixable": fixable,
        "unresolved": len(findings) - fixable,
        "skipped": {reason: count for reason, count in sorted(skipped.items()) if count},
    }


def s11_mismatches(md: Any, scenarios: Sequence[Dict[str, Any]], *, reference: str) -> List[str]:
    """Every fixable or unresolved alias-slot mismatch of ``md`` as an S11 string
    ("scenario 'X': prose 40% vs forecast.json 35%"), deduplicated, in text order —
    the 'numeric' gate feeds these into the existing hard S11 paths.  A number that is
    not the report's current probability of the scenario (market, quote, conditional
    or history guard) contradicts nothing and is left out."""
    messages: List[str] = []
    for finding in audit_markdown(md, scenarios, max_findings=None)["findings"]:
        if finding.get("guard") in _NOT_OWN_CLAIM_GUARDS:
            continue
        message = (f"scenario '{finding['scenario'][:28]}': prose {finding['claimed']}% "
                   f"vs {reference} {finding['expected_pct']}%")
        if message not in messages:
            messages.append(message)
    return messages
