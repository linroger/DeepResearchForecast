"""Deterministic narrative sync after scenario probability moves (REPORT-2, P08 stage 1a).

The red-team critique (with its humility clamp, residual bin and rounding
closure), the pre-mortem transfer and K>1 self-consistency pooling all move
scenario probabilities, but the forecast's free-text fields kept the numbers
written before the move.  report_ffe1ea6bf50d was published with the headline
"基准情景（40%）… 仅10%概率超预期上行" while forecast.json said A=0.35 / D=0.05,
and that stale headline is pinned into every section prompt, the outline summary,
the digest title and the dashboard.

This module maps each scenario's probability *before* a move onto its value
*after* the move and rewrites exactly those numbers in ``headline``,
``confidence_rationale`` and each scenario ``summary``.  It needs no alias
grammar ("基准情景", "Base") because it keys on the old value itself.

Precision first — a number is rewritten only when

* its value (integer percent, or a two-decimal fraction next to a probability
  word and not next to a currency, a "weighted" or a significance test) equals
  the old probability of exactly one scenario whose value changed, and no row
  the text may also cite (the input forecast a critic saw) holds it under
  another scenario's name;
* that value is not one an earlier sync of the same field already had to leave
  unattributed (see below);
* it is not a range endpoint or one end of a stated move ("30–40%",
  "from 55% to 50%", "由40%下调至35%");
* it is not a quantity ("52% share", "增长40%", "占约40%", "基率仅13%",
  "13%兑现率", "EV share above 40%", "40% of respondents", "成本下降40%",
  "a 40% decline", "40% cheaper", "约40%的装机", "关税40%", "WACC 13%") or a
  signed change ("+10%", "−5%");
* it does not take part in a sum statement ("合计50%" and the addends that make
  it up, "40% + 35%").

Everything else is left alone and counted by reason.  All replacements of one
text are applied in a single pass by span, so a value that is both one
scenario's new number and another's old number never cascades.

Moves chain (K>1 pooling, then the critique, then the pre-mortem), and each step
syncs only its own before/after.  A number one step leaves stale because it
cannot be attributed to a single scenario — its old value was shared by two
scenarios ("ambiguous"), belonged to a scenario that no longer pairs by name
("unpaired"), or was held by no scenario before the move but by one after it
("foreign": "a 25% chance of an early rate cut" once pooling makes Bear 25%) —
would look attributable to the next step, which would then write another
scenario's new value over it.  So every such value is recorded per field in
``quality.narrative_sync_blocked`` and stays unattributable in that field for all
later steps.  No LLM, no IO.
"""

from __future__ import annotations

import math
import re
from bisect import bisect_right
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

NARRATIVE_SYNC_LOG_CAP = 24
_EXCERPT_MAX_CHARS = 180
_EXCERPT_CONTEXT_CHARS = 60

# Integer percents: 1-3 ASCII digits, optional spaces, ASCII or full-width percent
# sign; never the fractional tail of a decimal ("4.40%") or a thousands group
# ("1,040%").  Only ASCII digits are tokens (a replacement is written in ASCII), while
# the look-behinds use Unicode \d so no tail of a full-width number ("４0%") is one.
_INT_PERCENT_RE = re.compile(
    r"(?<![\d.])(?<!\d,)(?P<num>[0-9]{1,3})(?P<space>\s*)(?P<sym>[%％])"
)
# Two-decimal fractions ("0.40" / ".40").  A trailing percent sign makes the value
# a percentage ("0.40%"), not a probability, so it is excluded.
_DECIMAL_RE = re.compile(r"(?<![\d.])(?P<num>0?\.[0-9]{2})(?!\d)(?!\s*[%％])")
# A decimal counts only when one of these words ends at most 12 characters before
# it, with no sentence stop in between ("概率约0.40", "probability of 0.40").
_DECIMAL_TRIGGER_RE = re.compile(
    r"概率|probabilit(?:y|ies)|prob\.|(?P<p_value>(?<![A-Za-z])p\s*=)", re.I
)
_DECIMAL_TRIGGER_WINDOW = 12
_DECIMAL_TRIGGER_MAX_LEN = 16
# A '.' between digits is a decimal point, any other '.' ends an English sentence.
_GAP_STOP_RE = re.compile(r"[。；;！？!?\n]|(?<!\d)\.(?!\d)")
# Even after a trigger, a decimal is a money or weighted figure when a currency sits
# next to it ("概率约0.40美元", "probability $0.40") or "weighted" lies in the gap
# ("概率加权成本0.40", "probability-weighted 0.40"), and a "p=" is a statistical
# p-value when significance follows ("(p=0.13) significant").
_DECIMAL_CURRENCY_BEFORE_RE = re.compile(r"[$¥￥€]\s*$")
_DECIMAL_CURRENCY_AFTER_RE = re.compile(
    r"\s*(?:USD|EUR|RMB|CNY|美元|欧元|日元|人民币|元|[$¥￥€])", re.I
)
_DECIMAL_WEIGHTED_RE = re.compile(r"加权|weighted", re.I)
_P_VALUE_SIGNIFICANCE_RE = re.compile(r"[^\n]{0,16}?(?:significan|显著|p-value|p值)", re.I)

# Range guard: the token is joined to another number by a dash, tilde, 至/到 or "to"
# (BEFORE searched at the end of a lookback slice, AFTER matched at the token end).
# A before→after pair is joined the same way, also through an arrow or a move verb
# ("40%下调至35%", "由40%调整为35%", "40% down to 35%"), and "from 40%" / "从40%" opens
# one: both ends are history or a critic's target, never one scenario's current value.
# The other endpoint may be written in any digit script (Unicode \d): a guard that
# over-detects a range only skips a token, it never rewrites one.
_MOVE_VERB = r"(?:下调|上调|调降|调升|下修|上修|调整|修正|降低|提高|下降|上升|回落|回升|降|升|增|减|改)"
_RANGE_JOINER = (
    r"(?:-|–|—|~|～|→|->|⇒|(?:(?:down|up|back)\s+)?to|"
    + _MOVE_VERB + r"?(?:至|到)|" + _MOVE_VERB + r"为)"
)
_RANGE_BEFORE_RE = re.compile(
    r"(?:\d\s*[%％]?\s*" + _RANGE_JOINER + r"|(?<![A-Za-z])from|从|由)\s*$", re.I
)
_RANGE_AFTER_RE = re.compile(r"\s*" + _RANGE_JOINER + r"\s*\.?\d", re.I)
_RANGE_LOOKBACK_CHARS = 16

# Quantity guard: a rate, share, threshold or other measured figure is never a
# scenario probability, even when its value equals one.
# A CJK word ending in 率 is a rate ("基率", "兑现率", "利润率", "渗透率", "利率") unless
# it is one of the probability words 概率 / 几率 / 或然率.
_RATE_CJK = r"(?<![概几然])率"
# AFTER: a quantity word starts within 8 characters after the token (matched from
# the token end): "52% share", "40%增长", "20%的市占", "40%关税".
_QUANTITY_AFTER_RE = re.compile(
    r"[^\n]{0,8}?(?:(?<![A-Za-z])(?:share|growth|target|CAGR|YoY|margin|penetration|"
    r"of GDP)|占比|份额|增长|增速|渗透率|同比|目标|市占|利率|税率|降幅|涨幅|增幅|增量|关税)",
    re.I,
)
# TAIL: a threshold word, a rate noun, a change or comparative word, a measured
# metric, "of <quantity>" or "的<noun>" directly after the token ("40%以上",
# "13%兑现率", "13% CAGR", "a 40% import tariff", "a 40% decline", "40% cheaper",
# "13% inflation", "40% capacity factor", "40% of respondents", "约40%的装机").
# Only adjacency counts, so "Soft landing (40%) — rate cuts" keeps its probability,
# and "40% of the probability mass" / "40%的概率" / "40%的发生概率" / "40%的可能性"
# stay probabilities.
_QUANTITY_TAIL_RE = re.compile(
    r"\s*(?:以上|以下|以内|或以上|或以下|[一-鿿]{0,5}?" + _RATE_CJK
    + r"|的(?!\s*(?:可能|机会|把握)|[^\s\d%％，。；,;、]{0,4}?(?:概率|几率|或然))"
    r"|(?:or|and)\s+(?:more|less|higher|lower|above|below)(?![A-Za-z])"
    r"|(?:[A-Za-z-]+\s+)?(?:rates?|tariffs?|CAGR|IRR)(?![A-Za-z])"
    r"|(?:decline[sd]?|drops?|increases?|reductions?|rises?|falls?|gains?|cuts?|jumps?"
    r"|surges?|lower|higher|cheaper|faster|slower|more|less|inflation|unemployment"
    r"|interest|vacancy|utili[sz]ation|efficiency|(?:capacity|load)\s+factor)(?![A-Za-z])"
    r"|of(?![A-Za-z])(?!\s+(?:the\s+)?(?:probabilit|likelihood|chance|odds)))",
    re.I,
)
# BEFORE: a quantity word lies within the 6 characters before the token
# ("同比增长20%", "利润率13%", "管道兑现基率仅13%", "按历史基率13%", "上调关税至40%").
_QUANTITY_BEFORE_WINDOW = 6
_QUANTITY_BEFORE_RE = re.compile(
    r"增长|增速|占比|份额|同比|关税|" + _RATE_CJK
    + r"|(?<![A-Za-z])(?:growth|share|rate|tariff)",
    re.I,
)
# LEAD: the token is led by a comparator, by 占, or by a quantity or change word,
# with only linking words and hedges in between ("EV share above 40%", "≥40%的装机",
# "占约40%", "占全球装机的40%", "the base rate is 13%", "CAGR约13%", "margin of about
# 13%", "通胀约13%", "涨幅达40%", "prices rose by 40%", "capex cut 40%", "WACC 13%",
# "关税40%", "成本下降约40%").  Adjacency is what makes it a quantity: "基准情景占主导
# （40%）" and "高通胀情景（40%）" keep their probability.  A bare CJK change verb takes
# only the hedges of an amount (约 / 近 / 了 / 达 …), never 为 / 至 / 到, because
# "概率降为35%" / "降至35%" names a new level (a critic's target), not a change; the
# English "cut to 20%" is likewise no quantity ("to" is not a linker).
# Searched at the end of a lookback slice.
_QUANTITY_LEAD_LOOKBACK_CHARS = 40
_LEAD_WORDS_EN = (
    r"rates?|tariffs?|CAGR|IRR|margins?|shares?|growth|yields?|inflation|discount|premium"
    r"|returns?|stake|weight(?:ing)?|increase[sd]?|decrease[sd]?|rise|rose|fall|fell"
    r"|drop(?:ped)?|decline[sd]?|gain(?:ed)?|jump(?:ed)?|surge[sd]?|up|down|by"
    r"|cuts?|reduce[sd]?|slashe[sd]|lowered|raised|WACC|ROE|ROI|unemployment|interest"
    r"|vacancy|utili[sz]ation|efficiency|(?:capacity|load)\s+factor"
)
_LEAD_LINKERS_EN = (
    r"is|was|are|were|of|at|by|near|around|about|roughly|approximately|only|just"
    r"|stands|stood|reached|hit"
)
_LEAD_WORDS_CJK = (
    r"涨幅|跌幅|降幅|增幅|升幅|幅度|比例|比重|通胀|折扣|溢价|折价|回报|收益|权重|利润"
    r"|上涨|下跌|增加|减少|关税|毛利"
)
_LEAD_CHANGE_VERBS_CJK = (
    r"下降|降低|上升|提高|下滑|削减|缩减|下探|回落|回升|暴跌|暴涨|降价|涨价"
    r"|跌|涨|降|升|减|增"
)
_LEAD_CHANGE_HEDGES_CJK = r"了?\s*(?:大约|约|将近|近|逾|超|仅|高达|达)?"
_COMPARATORS = (
    r"超过|超出|高于|低于|不低于|不高于|不少于|不足|至少|最多|大于|小于|多于|少于|逾"
    r"|(?<![A-Za-z])(?:above|over|below|under|beyond|at\s+(?:least|most)"
    r"|(?:more|less|fewer|greater)\s+than|exceed(?:s|ed|ing)?)"
    r"|[≥≤⩾⩽<]|(?<![-=])>"
)
_QUANTITY_LEAD_RE = re.compile(
    r"(?:(?<![A-Za-z])(?:" + _LEAD_WORDS_EN + r")(?:\s+(?:" + _LEAD_LINKERS_EN + r"))*"
    r"|" + _LEAD_WORDS_CJK
    + r"|占[^\s\d%％.,，。；;：:()（）、]{0,6}?"
    r"|" + _COMPARATORS + r")"
    r"\s*(?:约为|约|近|逾|仅|(?:可|将|已)?达|为|在|[~≈]"
    r"|(?:about|around|roughly|nearly|approximately)\s)?\s*$"
    r"|(?:" + _LEAD_CHANGE_VERBS_CJK + r")\s*" + _LEAD_CHANGE_HEDGES_CJK + r"\s*$",
    re.I,
)
# A signed number ("+10%", "−5%", "±3%") is a change, never a probability.  A sign
# after a digit ("40%-45%") is a range joiner, which the range guard checks first.
_SIGN_CHARS = frozenset("+＋-−±")

# Sum guard.  Sentences split on 。；;.!?！？ and newlines (a '.' between digits is a
# decimal point, not a stop).
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<!\d)\.(?!\d)|[。；;！？!?\n]")
_SUM_WORD_RE = re.compile(
    r"合计|共计|总计|之和|加总"
    r"|(?<![A-Za-z])(?:combined|together|total(?:s|ed|ing)?|sum(?:s|med)?)(?![A-Za-z])",
    re.I,
)
# An arithmetic '+' has an operand on both sides ("40% + 35%", "B+C"); a trailing
# "2027+" / "30%+" means "and later / or more" and is not a sum.
_ARITHMETIC_PLUS_RE = re.compile(r"[\w%％)）]\s*\+\s*[\w(（$]")
_AGGREGATE_AFTER_WINDOW = 16
_AGGREGATE_BEFORE_WINDOW = 8
_SUM_TOLERANCE_PCT = 1

_Token = Tuple[int, int, int, str]          # (start, end, percent value, kind)
_Span = Tuple[int, int]


def _probability_pct(row: Any) -> Optional[int]:
    """Integer percent of a scenario row's probability; None when not a finite [0, 1] number."""
    if not isinstance(row, dict):
        return None
    probability = row.get("probability")
    if type(probability) not in (int, float):
        return None
    value = float(probability)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        return None
    return round(value * 100)


def _scenario_key(name: Any) -> str:
    from .ensemble import _norm_name  # local: avoid an import cycle (as _pool_spine_draws)

    return _norm_name(name)


def _keyed_rows(rows: Any) -> List[Tuple[str, int, Dict[str, Any]]]:
    """``(normalised name, integer percent, row)`` for each row with a usable probability."""
    keyed = []
    for row in rows if isinstance(rows, (list, tuple)) else []:
        pct = _probability_pct(row)
        if pct is not None:
            keyed.append((_scenario_key(row.get("name")), pct, row))
    return keyed


def _value_mapping(
    before_rows: Any,
    after_rows: Any,
    only: Optional[Dict[str, Any]] = None,
    context_rows: Any = None,
) -> Tuple[Dict[int, int], Dict[int, str], Set[int]]:
    """Map old integer percents to new ones for scenarios whose value changed.

    Rows pair by ``ensemble._norm_name``; an empty name, or one that occurs twice on
    either side, never pairs.  Returns ``(mapping, unresolved, fresh)``.

    ``unresolved`` maps each old value whose number cannot be attributed to one
    scenario to the reason: ``ambiguous`` when a changed scenario's old value is held
    by more than one BEFORE row (paired or not), or by a ``context_rows`` row under
    another scenario's name; ``unpaired`` when a BEFORE row finds no AFTER row
    (renamed, merged or dropped, so its new value is unknown).  An unresolved value is
    never mapped.  ``context_rows`` are rows the text may cite although it was not
    written against them: a red-team critic writes its rationale and summaries
    against its own rows while looking at the input forecast, so "Bear's 30%" may be
    the input Bear while the critic's Bull is 30%.

    ``fresh`` holds the values the rows in scope carry AFTER the move but no row in
    scope carried BEFORE it.  A token with such a value was written against no
    scenario of this move, yet the next move would attribute it to whichever
    scenario now holds the value, so the caller records it as blocked.

    ``only`` restricts the scope to the pair whose AFTER row is that exact dict (a
    scenario's own summary): the mapping is that pair's move, and ``fresh`` is its
    new value unless the row kept its old one.
    """
    before = _keyed_rows(before_rows)
    after = _keyed_rows(after_rows)
    context = _keyed_rows(context_rows)
    pct_counts = Counter(pct for _, pct, _ in before)
    before_names = Counter(name for name, _, _ in before if name)
    after_names = Counter(name for name, _, _ in after if name)
    old_by_name = {name: pct for name, pct, _ in before if name and before_names[name] == 1}
    paired = {name for name, _, _ in after
              if name and after_names[name] == 1 and name in old_by_name}

    changed: List[Tuple[str, int, int]] = []
    for name, new_pct, row in after:
        if name not in paired or (only is not None and row is not only):
            continue
        old_pct = old_by_name[name]
        if old_pct != new_pct:
            changed.append((name, old_pct, new_pct))
    unresolved = {pct: "unpaired" for name, pct, _ in before if name not in paired}
    unresolved.update({old: "ambiguous" for _, old, _ in changed if pct_counts[old] > 1})
    for name, old, _ in changed:
        if old not in unresolved and any(
                pct == old and context_name != name for context_name, pct, _ in context):
            unresolved[old] = "ambiguous"
    mapping = {old: new for _, old, new in changed if old not in unresolved}

    if only is None:
        fresh = {pct for _, pct, _ in after} - {pct for _, pct, _ in before}
    else:
        fresh = {pct for name, pct, row in after
                 if row is only and (name not in paired or old_by_name[name] != pct)}
    return mapping, unresolved, fresh


def _decimal_in_probability_context(text: str, start: int, end: int) -> bool:
    if (_DECIMAL_CURRENCY_BEFORE_RE.search(text[max(0, start - 2):start])
            or _DECIMAL_CURRENCY_AFTER_RE.match(text, end)):
        return False
    lower = max(0, start - _DECIMAL_TRIGGER_WINDOW - _DECIMAL_TRIGGER_MAX_LEN)
    for trigger in _DECIMAL_TRIGGER_RE.finditer(text, lower, start):
        gap = text[trigger.end():start]
        if (len(gap) > _DECIMAL_TRIGGER_WINDOW or _GAP_STOP_RE.search(gap)
                or _DECIMAL_WEIGHTED_RE.search(gap)):
            continue
        if trigger.group("p_value") and _P_VALUE_SIGNIFICANCE_RE.match(text, end):
            continue
        return True
    return False


def _probability_tokens(text: str) -> List[_Token]:
    tokens: List[_Token] = [
        (match.start(), match.end(), int(match.group("num")), "percent")
        for match in _INT_PERCENT_RE.finditer(text)
    ]
    for match in _DECIMAL_RE.finditer(text):
        if _decimal_in_probability_context(text, match.start(), match.end()):
            value = round(float(match.group("num")) * 100)
            tokens.append((match.start(), match.end(), value, "decimal"))
    tokens.sort()
    return tokens


def _is_range(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - _RANGE_LOOKBACK_CHARS):start]
    return bool(_RANGE_BEFORE_RE.search(before) or _RANGE_AFTER_RE.match(text, end))


def _is_quantity(text: str, start: int, end: int) -> bool:
    if start > 0 and text[start - 1] in _SIGN_CHARS:
        return True
    if _QUANTITY_AFTER_RE.match(text, end) or _QUANTITY_TAIL_RE.match(text, end):
        return True
    if _QUANTITY_BEFORE_RE.search(text, max(0, start - _QUANTITY_BEFORE_WINDOW), start):
        return True
    return bool(_QUANTITY_LEAD_RE.search(
        text, max(0, start - _QUANTITY_LEAD_LOOKBACK_CHARS), start))


def _sentence_bounds(text: str) -> List[_Span]:
    bounds: List[_Span] = []
    cursor = 0
    for stop in _SENTENCE_BOUNDARY_RE.finditer(text):
        bounds.append((cursor, stop.end()))
        cursor = stop.end()
    if cursor < len(text):
        bounds.append((cursor, len(text)))
    return bounds


def _addend_indexes(values: List[int], aggregate: int) -> Optional[range]:
    """Contiguous neighbours of the aggregate whose values add up to it (nearest first)."""
    target = values[aggregate]
    total = 0
    for index in range(aggregate - 1, -1, -1):
        total += values[index]
        if abs(total - target) <= _SUM_TOLERANCE_PCT:
            return range(index, aggregate)
        if total > target + _SUM_TOLERANCE_PCT:
            break
    total = 0
    for index in range(aggregate + 1, len(values)):
        total += values[index]
        if abs(total - target) <= _SUM_TOLERANCE_PCT:
            return range(aggregate + 1, index + 1)
        if total > target + _SUM_TOLERANCE_PCT:
            break
    return None


def _sum_shield(text: str, start: int, end: int) -> Optional[Set[_Span]]:
    """Spans of percent tokens inside a sum statement of ``text[start:end]``.

    ``None`` shields the whole sentence: an arithmetic '+', or a sum word whose
    total or addends cannot be identified.  When they can ("…（30%）与…（20%）构成
    合计50%…"), only the total and its addends are shielded, so an unrelated
    "基准情景（40%）" earlier in the same sentence can still be synced.
    """
    if _ARITHMETIC_PLUS_RE.search(text[start:end]):
        return None
    sum_words = list(_SUM_WORD_RE.finditer(text, start, end))
    if not sum_words:
        return set()
    percents = list(_INT_PERCENT_RE.finditer(text, start, end))
    values = [int(match.group("num")) for match in percents]
    shielded: Set[_Span] = set()
    for word in sum_words:
        aggregate = next(
            (index for index, match in enumerate(percents)
             if 0 <= match.start() - word.end() <= _AGGREGATE_AFTER_WINDOW),
            None,
        )
        if aggregate is None:
            aggregate = next(
                (index for index in range(len(percents) - 1, -1, -1)
                 if 0 <= word.start() - percents[index].end() <= _AGGREGATE_BEFORE_WINDOW),
                None,
            )
        if aggregate is None:
            return None
        addends = _addend_indexes(values, aggregate)
        if addends is None:
            return None
        for index in (aggregate, *addends):
            shielded.add(percents[index].span())
    return shielded


def _format_replacement(text: str, token: _Token, new_pct: int) -> str:
    start, end, _, kind = token
    if kind == "decimal":
        rendered = f"{new_pct / 100:.2f}"
        if text[start] == "." and rendered.startswith("0."):
            rendered = rendered[1:]
        return rendered
    match = _INT_PERCENT_RE.match(text, start)
    return f"{new_pct}{match.group('space')}{match.group('sym')}"


def _rewrite(
    text: str,
    mapping: Dict[int, int],
    unresolved: Dict[int, str],
    fresh: Set[int],
) -> Tuple[str, List[Dict[str, str]], Dict[str, int], Set[int]]:
    """Apply ``mapping`` to ``text`` in one pass by span.

    Returns ``(new_text, edits, skipped, unattributed)``; ``unattributed`` holds the
    values of tokens left alone because ``unresolved`` names them, and of
    ``foreign`` tokens: a token whose value is in ``fresh`` (no scenario of this
    move held it before the move, but one holds it now: "a 25% chance of an early
    rate cut") and that no range or quantity guard skips.  Those two guards read
    only the words next to the token, never a number's value, so they skip the same
    token again at every later step; the sum shield also depends on the values of
    the other numbers in the sentence, which later steps may rewrite, so a foreign
    token inside a sum statement is still recorded.
    """
    skipped: Counter = Counter()
    unattributed: Set[int] = set()
    if not mapping and not unresolved and not fresh:
        return text, [], {}, unattributed
    sentences = _sentence_bounds(text)
    sentence_starts = [lo for lo, _ in sentences]
    shields: Dict[int, Optional[Set[_Span]]] = {}
    replacements: List[Tuple[int, int, str]] = []
    for token in _probability_tokens(text):
        start, end, value, _ = token
        reason = unresolved.get(value)
        if reason is not None:
            skipped[reason] += 1
            unattributed.add(value)
            continue
        new_pct = mapping.get(value)
        if new_pct is None:
            if (value in fresh and not _is_range(text, start, end)
                    and not _is_quantity(text, start, end)):
                skipped["foreign"] += 1
                unattributed.add(value)
            continue
        if _is_range(text, start, end):
            skipped["range"] += 1
            continue
        if _is_quantity(text, start, end):
            skipped["quantity"] += 1
            continue
        sentence = bisect_right(sentence_starts, start) - 1
        if sentence not in shields:
            shields[sentence] = _sum_shield(text, *sentences[sentence])
        shield = shields[sentence]
        if shield is None or (start, end) in shield:
            skipped["sum"] += 1
            continue
        replacements.append((start, end, _format_replacement(text, token, new_pct)))

    pieces: List[str] = []
    placed: List[Tuple[int, int, str, str]] = []
    cursor = 0
    length = 0
    for start, end, replacement in replacements:
        pieces.append(text[cursor:start])
        length += start - cursor
        placed.append((length, length + len(replacement), text[start:end], replacement))
        pieces.append(replacement)
        length += len(replacement)
        cursor = end
    pieces.append(text[cursor:])
    new_text = "".join(pieces)
    edits = []
    for lo, hi, original, replacement in placed:
        excerpt = new_text[max(0, lo - _EXCERPT_CONTEXT_CHARS):hi + _EXCERPT_CONTEXT_CHARS]
        edits.append({"from": original, "to": replacement, "excerpt": excerpt[:_EXCERPT_MAX_CHARS]})
    return new_text, edits, dict(skipped), unattributed


def sync_probability_numbers(
    text: Any,
    before_rows: Sequence[Dict[str, Any]],
    after_rows: Sequence[Dict[str, Any]],
) -> Tuple[Any, List[Dict[str, str]], Dict[str, int]]:
    """Rewrite stale scenario probabilities in ``text`` from BEFORE to AFTER values.

    Returns ``(new_text, edits, skipped)``: ``edits`` holds ``{from, to, excerpt}``
    per replaced token; ``skipped`` counts tokens that carried a mapped or
    unattributable value but were left alone, by reason (ambiguous / unpaired /
    foreign / range / quantity / sum).  A non-string or empty ``text`` is returned
    unchanged.
    """
    if not isinstance(text, str) or not text:
        return text, [], {}
    new_text, edits, skipped, _ = _rewrite(text, *_value_mapping(before_rows, after_rows))
    return new_text, edits, skipped


def _blocked_record(quality: Optional[Dict[str, Any]]) -> Dict[str, Set[int]]:
    """``quality.narrative_sync_blocked`` as ``{field key: values}``; malformed entries are ignored."""
    record = (quality or {}).get("narrative_sync_blocked")
    if not isinstance(record, dict):
        return {}
    return {
        str(key): {value for value in values if type(value) is int}
        for key, values in record.items() if isinstance(values, list)
    }


def synchronize_forecast_narratives(
    out: Dict[str, Any],
    *,
    headline_before: Optional[Sequence[Dict[str, Any]]] = None,
    rationale_before: Optional[Sequence[Dict[str, Any]]] = None,
    summary_before_by_name: Optional[Sequence[Dict[str, Any]]] = None,
    context_rows: Optional[Sequence[Dict[str, Any]]] = None,
) -> None:
    """Sync ``out``'s narrative fields to its current ``scenarios`` after one probability move.

    Each ``*_before`` is the scenario list the corresponding text was written
    against; ``None`` leaves that field alone.  Each scenario's ``summary`` maps
    only its own pair: its row in ``summary_before_by_name`` found by normalised
    name; other rows' moves are ignored.  ``context_rows`` are rows every field may
    also cite (the input forecast a critic saw while writing against its own rows):
    an old value that a context row holds under another scenario's name is
    ambiguous.  For a field written against the context rows themselves this adds
    nothing, since such a value is already held by two of its BEFORE rows.

    Originals are kept with ``setdefault`` in ``headline_detail`` /
    ``confidence_rationale_detail`` / per-scenario ``summary_detail`` (the first
    original wins across passes); each edit is appended to ``quality.narrative_sync``
    (capped at NARRATIVE_SYNC_LOG_CAP; ``quality.narrative_sync_dropped`` counts the
    edits the cap left out) and skip counts accumulate in
    ``quality.narrative_sync_skipped``.

    Values a pass had to leave unattributed (ambiguous / unpaired / foreign) are
    recorded per field in ``quality.narrative_sync_blocked`` (``headline``,
    ``confidence_rationale``, ``summary:<normalised scenario name>``), and every
    later pass treats a recorded value as ambiguous in that field, so a stale
    number is never mapped onto another scenario's move by a later step.  The
    record only grows: a field's text replaced by a critic that saw the stale one
    may still repeat it.

    All values are computed before ``out`` is touched, and ``out`` is left
    untouched when nothing was edited or skipped; the ``quality`` dict is copied,
    never mutated in place (it may be shared with the pre-move forecast).
    """
    if not isinstance(out, dict):
        return
    quality = out.get("quality")
    if quality is not None and not isinstance(quality, dict):
        return
    scenarios = out.get("scenarios")
    after_rows = [row for row in scenarios if isinstance(row, dict)] if isinstance(scenarios, list) else []
    if not after_rows:
        return

    prior_blocked = _blocked_record(quality)
    blocked: Dict[str, Set[int]] = {}
    pending: List[Tuple[Dict[str, Any], str, str, str]] = []
    log: List[Dict[str, str]] = []
    skipped: Counter = Counter()

    def collect(target: Dict[str, Any], field: str, label: str, key: str,
                mapping: Dict[int, int], unresolved: Dict[int, str], fresh: Set[int]) -> None:
        text = target.get(field)
        if not isinstance(text, str) or not text:
            return
        carried = prior_blocked.get(key, set()) if key else set()
        unresolved = {**unresolved, **{value: "ambiguous" for value in carried if value in mapping}}
        new_text, edits, reasons, unattributed = _rewrite(text, mapping, unresolved, fresh)
        skipped.update(reasons)
        if key and not unattributed <= carried:
            blocked[key] = blocked.get(key, carried) | unattributed
        if edits:
            pending.append((target, field, text, new_text))
            log.extend({"field": label, **edit} for edit in edits)

    for field, before in (("headline", headline_before), ("confidence_rationale", rationale_before)):
        if before is not None:
            collect(out, field, field, field,
                    *_value_mapping(before, after_rows, context_rows=context_rows))
    if summary_before_by_name is not None:
        for index, row in enumerate(scenarios):
            if isinstance(row, dict):
                name_key = _scenario_key(row.get("name"))
                collect(row, "summary", f"scenario[{index}].summary",
                        f"summary:{name_key}" if name_key else "",
                        *_value_mapping(summary_before_by_name, after_rows, only=row,
                                        context_rows=context_rows))

    if not log and not skipped:
        return
    for target, field, original, new_text in pending:
        target.setdefault(f"{field}_detail", original)
        target[field] = new_text
    quality = dict(quality or {})
    if log:
        prior = quality.get("narrative_sync")
        merged = (list(prior) if isinstance(prior, list) else []) + log
        quality["narrative_sync"] = merged[:NARRATIVE_SYNC_LOG_CAP]
        dropped = len(merged) - NARRATIVE_SYNC_LOG_CAP
        if dropped > 0:
            prior_dropped = quality.get("narrative_sync_dropped")
            quality["narrative_sync_dropped"] = dropped + (
                prior_dropped if type(prior_dropped) is int else 0)
    if skipped:
        prior = quality.get("narrative_sync_skipped")
        counts = Counter(
            {str(key): value for key, value in prior.items() if type(value) is int}
            if isinstance(prior, dict) else {}
        )
        counts.update(skipped)
        quality["narrative_sync_skipped"] = dict(counts)
    if blocked:
        quality["narrative_sync_blocked"] = {
            key: sorted(values) for key, values in {**prior_blocked, **blocked}.items()
        }
    out["quality"] = quality
