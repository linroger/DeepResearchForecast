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
``confidence_rationale`` and each scenario ``summary``.  It keys on the old value
itself, so it needs no alias grammar ("基准情景", "Base") to find a number.

Precision first.  The sync is on by default, so a false rewrite corrupts published
text; missing a stale number only leaves it as it was.  The rule is therefore an
allowlist that fails closed — a number is rewritten only when

* its value (integer percent, or a two-decimal fraction right after a probability
  word) equals the old probability of exactly one scenario whose value changed,
  and no row the text may also cite (the input forecast a critic saw) holds it
  under another scenario's name;
* that value is not one an earlier sync of the same field already had to leave
  unattributed (see below);
* it sits in a recognised probability slot, and that slot names a scenario.  A
  scenario is named by a label of the scenario whose old value the number is (its
  "owner": "Recession" for "B. Recession"; see ``_name_aliases``) or by a scenario
  word (情景 / 上行 / 下行 / 基准 / 乐观 / 悲观 / case / scenario / path / base /
  bull / bear / upside / downside …); a residual word alone ("Other", "其它",
  "Mixed") is no label, because every breakdown has an "Other: 20%" row:
  - in brackets right after an owner label or a scenario word: "基准情景（40%）",
    "Recession (~25%)", "Base (~52% share, 55%)", "B. Recession (p=0.25)".  What
    precedes the bracket is the label ("Section 301 tariffs (25%)", "AP-NORC
    (37%)", "美国（约40%）", "not robust (p=0.40)" are no slots), and a word label
    inside the bracket must itself be an owner label or a probability word: "(A:
    40%, B: 25%)", "（概率：40%）" are slots, "(US: 40%, EU: 25%)", "Bull case
    (revenue growth: 40%)", "(2030: 40%)" are not;
  - right before a probability word, with a scenario named in the same clause
    (for Chinese, also right after the probability word): "The soft landing is
    40% likely", "仅10%概率超预期上行", "基准情景有40%的可能性".  An English
    probability word with an object ("a 40% chance of X", "… that X plays out",
    "… to the base case") counts only when the object IS the scenario: "of the base
    case", "of Recession", "that the downside scenario plays out" — never "that the
    court case is dismissed" or "of an early rate cut";
  - after 概率 / 几率 / 可能性 / probability / likelihood / chance with only
    linking words in between, a clause end after it and a scenario named earlier
    in the clause: "基准情景概率降至40%，", "Recession probability is 25%.",
    "基准情景概率约0.40" (a decimal is a token only here or after a bracketed "p=");
    "JPMorgan puts the probability at 40%" names none;
  - after the name of the very scenario whose old value it is, with only linking
    words in between and a clause end after it: "Base: 40%;", "Bear cut to 20%,",
    "Path A leads at 45%," (a label that names another scenario, or none, is
    no slot: "China 40%, US 5.8%", "Bear's 30%" when 30% was Bull's);
* no market or outside forecaster (Polymarket, consensus, analysts, futures,
  Goldman, the IMF, the IEA, 高盛, 一致预期 …) is cited earlier in its sentence,
  within 40 characters before it, or directly after it ("Polymarket prices this at
  40%", "市场隐含概率40%", "40% on Kalshi", 'The Polymarket snapshot … "D sweep"
  (44%)', "Goldman's base case puts the recession probability at 25%");
* it is not a range endpoint or one end of a stated move ("30–40%",
  "from 55% to 50%", "由40%下调至35%", "–40% to –55%");
* it is not a quantity ("52% share", "增长40%", "占约40%", "基率仅13%",
  "13%兑现率", "EV share above 40%", "40% of respondents", "成本减少了约40%",
  "a 40% decline", "40% smaller", "costs have fallen 40%", "价格较2020年低40%",
  "约40%的装机", "关税40%", "WACC 13%", "<=40%") or a signed change ("+10%",
  "−5%", "–40%"); these deny-list guards still apply inside a slot, except that
  a quantity word inside an owner label is part of the name ("基准扩张40%的概率",
  "Tariff Ratchet Up at 25%");
* it does not take part in a sum statement ("合计50%" and the addends that make
  it up, "40% + 35%");
* it is not one entry of a per-scenario list of another metric: a bracket or a
  label list after a metric noun ("EV share (Base: 52%, Bull: 70%)", "EV share —
  Base: 40%, Recession: 25%", "资本开支增速（基准扩张40%，电力受限25%）").

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
from bisect import bisect_left, bisect_right
from collections import Counter
from functools import lru_cache
from typing import Any, Dict, List, NamedTuple, Optional, Pattern, Sequence, Set, Tuple

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

# ------------------------------------------------------------ probability slots
# Only a number in one of these slots is ever rewritten; everything else fails closed.
#
# LINK GAP: between a probability word and the number only linking words may stand
# — copulas, hedges and "moved to" verbs.  Anything else ("probability of reaching
# 40%", "概率较高，EPS 0.40", "probability threshold 0.40", "概率区间0.40") means the
# number is not the probability itself.  A comma or a sentence stop is never a linking
# word.  "从" / "由" / "from" are linking words only so that "概率从0.40降到0.35" is
# seen, and then skipped, by the range guard.  Matched in full against the gap.
_LINK_GAP_RE = re.compile(
    r"(?:\s|[:：=≈~～]|的|为|是|约|大约|仅|只有|有|在|达|达到|近|接近|将|已|仍|被|维持|从|由"
    r"|降至|升至|调至|下调至|上调至|降为|升为|调为|调整为|修正为|下修至|上修至"
    r"|(?<![A-Za-z])(?:of|is|was|are|were|at|to|from|now|still|about|around|roughly"
    r"|approximately|approx\.?|nearly|only|just|estimated|set|put|falls?|fell|rises?|rose"
    r"|drops?|dropped|cut|raised|lowered|trimmed|reduced|increased|revised|moved|adjusted"
    r"|down|up|back|stands?|stood|remains?|remained|stays?|stayed|sits?|holds?|held)"
    r"(?![A-Za-z]))*",
    re.I,
)
# CLAUSE END: a number in a word-anchored slot must close its clause — punctuation, a
# dash, the end, or a connective — so "probability of 40% adoption" and "Base: 40%
# renewables" (the number heads a noun phrase) stay untouched.
_SLOT_END_RE = re.compile(
    r"\s*(?:$|[,，;；。.!?！？:：、)）\]】…—–]|-(?!\d)|左右|而|但|且|并|因|领先|居首)"
    r"|\s+(?:and|or|vs\.?|versus|while|whereas|but|with|given|as|on|after|because|since"
    r"|if|when|which|that|now|still|reflect(?:s|ing)?|remains?|leads?|dominates?|amid)"
    r"(?![A-Za-z])",
    re.I,
)
# SCENARIO WORDS name a scenario whatever the forecast calls it: generic scenario
# nouns and scenario-type words ("基准情景", "the downside case", "Bear", "上行").
# "base" is no scenario word before rate / year / period / effect ("the base rate"),
# nor 基准 after 历史 ("历史基准" is a historical benchmark) or before 利率 / 汇率 / 价 /
# 年 / 期 / 线 ("基准利率" is the policy rate), nor "case" in "in case" / "in any case";
# an English word followed by a hyphen modifies the next one ("base-rate", "bull-market").
_SCENARIO_WORDS_EN = (
    r"base(?!\s+(?:rates?|years?|periods?|effects?)(?![A-Za-z]))|baseline|bull|bear|upside"
    r"|downside|tail|residual|(?<!\bin )(?<!\bany )case|scenario|path|outcome|branch"
)
_SCENARIO_WORD = (
    r"(?:情景|场景|情形|路径|上行|下行|(?<!历史)基准(?![利汇价年期线])|乐观|悲观|中性|兜底|尾部"
    r"|(?<![A-Za-z])(?i:(?:" + _SCENARIO_WORDS_EN + r")(?:e?s)?)(?![A-Za-z-]))"
)
_SCENARIO_WORD_RE = re.compile(_SCENARIO_WORD)
# A label ends right before a bracket: optional closing bracket ("(base case) (40%)"),
# then only spaces, quotes and Markdown emphasis ("**Base case** (40%)").
_LABEL_END_TAIL = r"(?:\s*[)）\]】])?[\s*_\"'“”‘’]*$"
# A clause, for "a scenario is named in the same clause": it ends at 。；;！？!? or a
# newline, or at a '.' that is neither a decimal point nor the "prob." / "approx."
# abbreviation, and reaches back at most 80 characters.
_CLAUSE_STOP_RE = re.compile(r"[。；;！？!?\n]|(?<!\d)(?<!\bprob)(?<!\bapprox)\.(?!\d)", re.I)
_CLAUSE_LOOKBACK_CHARS = 80
# A Chinese scenario may also follow the probability word ("仅10%概率超预期上行",
# "有40%的概率维持基准"): within 24 characters, before a comma or a clause stop.
_CLAUSE_AFTER_CHARS = 24
_CLAUSE_AFTER_STOP_RE = re.compile(r"[,，、。；;！？!?\n]")

# (a) Brackets: "（40%）", "(~40%)", "[40%]", or after a label that a separator ends
# ("Base (~52% share, 55%)").  The bracket closes right after, or a separator follows
# and the bracket closes within 40 characters with no range after the token ("(47% vs
# 32%)" pairs two scenarios; "兑现率口径分歧大（13% vs 40-60%）" compares rates).
_SLOT_SEPARATOR = r"(?:[,，;；、:：/]|(?<![A-Za-z])(?:vs\.?|or|and)(?![A-Za-z])|与|和|或)"
_SLOT_SEPARATOR_RE = re.compile(_SLOT_SEPARATOR, re.I)
_PAREN_LOOKBACK_CHARS = 40
_PAREN_BEFORE_RE = re.compile(
    r"[（(\[【]\s*(?:(?P<inner>[^()（）\[\]【】\n]{0,30}?)(?P<sep>" + _SLOT_SEPARATOR + r")\s*)?"
    r"(?:~|～|≈|约|approx\.?|(?<![A-Za-z])p\s*=)?\s*$",
    re.I,
)
_PAREN_AFTER_RE = re.compile(r"\s*(?:(?P<close>[)）\]】])|" + _SLOT_SEPARATOR + r")", re.I)
_PAREN_REST_RE = re.compile(r"(?P<rest>[^()（）\[\]【】\n]{0,40}?)[)）\]】]")
_RANGE_INSIDE_RE = re.compile(r"\d\s*[%％]?\s*(?:-|–|—|~|～|至|到|to)\s*[+\-−–—]?\s*\.?\d", re.I)
# The bracket's label.  A ':' before the token labels it with the word before the ':'
# ("(US: 40%)", "(2030: 40%)"); after a list separator a word item without digits
# labels it too ("(revenue growth, 40%)"), while an item with a number is a sibling
# value ("(~52% share, 55%)", "(47% vs 32%)") and leaves the label to what precedes
# the bracket.
_LABELLING_SEPARATORS = frozenset(":：")
# A bracket of scenario labels after a metric noun lists that metric per scenario, not
# their probabilities: "EV share (Base: 52%, Bull: 70%)", "Margins by scenario (Base:
# 40%, …)", "资本开支增速（基准扩张：40%，财务紧缩：20%）", "资本开支增速（基准扩张40%，
# 电力受限25%）".  The noun may stand up to 24 characters before the bracket, in the
# same clause; a noun inside a label of the owner is part of its name.
_METRIC_BEFORE_BRACKET_CHARS = 24
_METRIC_NOUN_RE = re.compile(
    r"增长|增速|占比|份额|同比|关税|(?<![概几然])率"
    r"|毛利|利润|收入|营收|价格|成本|资本开支|出货|装机|需求|产能|回撤|损失|违约|利差|通胀|失业"
    r"|(?<![A-Za-z])(?:share|growth|rate|tariff|margin|yield|return|CAGR|IRR|ROE|ROI|WACC"
    r"|penetration|utili[sz]ation|inflation|unemployment|capex|revenue|sales|price|cost|EPS"
    r"|earnings|GDP|output|capacity|demand|volume|drawdown|loss|default|spread)",
    re.I,
)
# The same list outside brackets has a header: a metric noun, then a colon or a dash
# before the labels ("EV share — Base: 40%, Recession: 25%", "Default rates in each
# case: Base 15%, …", "各情景出货增速：基准扩张40%，…").  "Weights: Base 40%" and
# "情景概率：基准扩张40%" have no metric noun; "Base 40% (steady growth), Recession 25%"
# has no header after its noun.  A header is followed by a label, not by a number
# ("Tariff Ratchet Up: 25%, Managed Fragmentation: 45%" is a label list whose first
# name holds a metric word), and reaches across ';' ("EV share — Base: 40%; Recession:
# 25%"), up to 120 characters back to the sentence start.
_METRIC_HEADER_RE = re.compile(
    "(?:" + _METRIC_NOUN_RE.pattern + r")[^。；;！？!?\n:：]{0,30}?(?:[:：]|\s[—–-]\s|—)"
    r"(?=\s*[^\s\d~～≈约<>≤≥+＋\-−–—])",
    re.I,
)
_HEADER_LOOKBACK_CHARS = 120
_HEADER_STOP_RE = re.compile(r"[。！？!?\n]|(?<!\d)(?<!\bprob)(?<!\bapprox)\.(?!\d)", re.I)
# The innermost bracket still open before a token (up to 80 characters back, so a long
# list is covered: "(Base: 40%, Recession: 25%, Stagflation: 20%)").
_OPEN_BRACKET_LOOKBACK_CHARS = 81
_OPEN_BRACKET_RE = re.compile(r"[（(\[【][^()（）\[\]【】\n]{0,80}$")
_LABEL_STRIP_CHARS = " \t*_\"'“”‘’"
_LABEL_WORD_RE = re.compile(r"[A-Za-z一-鿿]")
_DIGIT_RE = re.compile(r"\d")
# A bracket label that is a probability word ("(probability: 40%)", "（概率：40%）").
# A compound ("default probability", "违约概率", "probability-weighted") is not.
_PROB_LABEL_RE = re.compile(
    r"(?:(?:发生|实现|出现|主观|情景)\s*)?(?:概率|几率|可能性)"
    r"|(?i:(?:(?:our|est\.?|estimated|assigned|subjective|scenario)\s+)?"
    r"(?:probabilit(?:y|ies)|likelihood|chances?|prob\.?|p))"
)
# (b) A probability word right after the number: "10%概率", "40%的发生概率", "40%的可能性",
# "有40%的把握", "a 40% chance", "40% of the probability mass", "40% likely".  Never a
# modal "可能" ("约40%可能来自中国" = "may come from") or a hyphenated compound
# ("40% probability-weighted", "40% chance-weighted cost").
_PROB_AFTER_RE = re.compile(
    r"\s*(?:的\s*)?(?:(?:发生|实现|出现)\s*)?(?:概率|几率|或然率|可能性)"
    r"|\s*的\s*(?:可能|机会|把握)"
    r"|\s*(?:of\s+(?:the\s+)?)?(?P<en>probabilit(?:y|ies)|chances?|likelihood|odds|likely)"
    r"(?![\w-])",
    re.I,
)
# An English probability word's object ("a 40% chance of X", "… that X", "… for X",
# "40% likely to X") up to the clause end or a connective ("of the base case and a 20%
# chance of …").  It counts only when it IS the scenario (``_object_res``): an owner
# label or a scenario reference, optionally a verb of occurrence and a date.
_PROB_OBJECT_RE = re.compile(
    r"\s+(?P<lead>of|that|for|to)\s+(?P<object>[^,，;；。.!?！？:：()（）\[\]【】\n]{1,60})", re.I
)
_OBJECT_CUT_RE = re.compile(
    r"\s(?:and|or|vs\.?|versus|while|whereas|but|with|as|given|because|since|amid)(?![A-Za-z])",
    re.I,
)
_OBJECT_DETERMINER = r"(?:(?:the|this|that|our|a|an|its)\s+)?"
_OBJECT_NOUN = r"(?:case|scenario|path|outcome|branch)(?:e?s)?"
# A scenario reference without an owner label: a scenario-type word, optionally with
# a noun ("the base case", "upside", "the downside path"), or up to two modifiers and
# "scenario" ("the soft-landing scenario").  "the court case" / "a worst-case outcome"
# are not.
_OBJECT_SCENARIO = (
    r"(?:(?:base|baseline|bull|bear|upside|downside|tail|residual|central|modal)"
    r"(?:[\s-]+" + _OBJECT_NOUN + r")?"
    r"|(?:[A-Za-z][\w'’-]*[\s-]+){0,2}scenarios?)"
)
_OBJECT_VERB = (
    r"(?:(?:will|would|could|may|might)\s+)?"
    r"(?:materiali[sz](?:e[sd]?|ing)|occur(?:s|red|ring)?|happen(?:s|ed|ing)?"
    r"|play(?:s|ed|ing)?\s+out|unfold(?:s|ed|ing)?|prevail(?:s|ed|ing)?"
    r"|dominat(?:e[sd]?|ing)|hold(?:s|ing)?|comes?\s+true|comes?\s+to\s+pass)"
)
_OBJECT_ADJUNCT = (
    r"(?:\s+(?:by|in|through|until|before)\s+(?:end-?)?\d{4}"
    r"|\s+over\s+the\s+(?:forecast\s+)?horizon)?"
)
_OBJECT_STRIP_CHARS = " \t*_\"'“”‘’"
# (c) A probability word before the number, linked by LINK GAP only: "基准情景概率降至40%",
# "Recession probability is 25%".  ("odds" is not one: "the Fed cut odds are 40%",
# "IEA puts the odds at 40%" cite outside odds.)
_PROB_TRIGGER_RE = re.compile(r"概率|几率|可能性|probabilit(?:y|ies)|likelihood|chances?", re.I)
_PROB_GAP_MAX_CHARS = 16
_PROB_TRIGGER_MAX_CHARS = 13
# Decimals are tokens only in slot (c) and after a bracketed "p=" ("Base (p=0.40)",
# which then needs a label before the bracket like any bracket); a bare p= is a
# p-value ("regression p=0.40", "p=0.40 (n.s.)").
_DECIMAL_TRIGGER_RE = re.compile(
    r"概率|probabilit(?:y|ies)|prob\.|(?P<p_value>(?<![A-Za-z])p\s*=)", re.I
)
_P_VALUE_OPEN_RE = re.compile(r"[（(\[【]\s*$")
_P_BRACKET_LOOKBACK_CHARS = 12
_P_BRACKET_RE = re.compile(r"[（(\[【]\s*p\s*=\s*$", re.I)
_DECIMAL_CURRENCY_BEFORE_RE = re.compile(r"[$¥￥€]\s*$")
_DECIMAL_CURRENCY_AFTER_RE = re.compile(
    r"\s*(?:USD|EUR|RMB|CNY|美元|欧元|日元|人民币|元|[$¥￥€])", re.I
)
# A statistic or a scoring rule within 32 characters of the decimal: never a scenario
# probability ("Brier/probability 0.40").  Next to a "p=" the words of a significance
# test count as well ("(p=0.40, n.s.)", "(p=0.40) significant"); elsewhere they are
# ordinary narrative words ("显著放缓", "回归基准").
_DECIMAL_STATISTIC_WINDOW_CHARS = 32
_STATISTIC_WORDS = (
    r"brier|log-?loss|sharpe|coefficient|系数|correlation|相关性|p-value|p值|t-test|t检验"
)
_DECIMAL_STATISTIC_RE = re.compile(_STATISTIC_WORDS, re.I)
_P_VALUE_STATISTIC_RE = re.compile(
    _STATISTIC_WORDS + r"|significan|显著|n\.s\.|regression|回归|confidence\s+interval|置信"
    r"|(?<![A-Za-z0-9])H0(?![A-Za-z0-9])",
    re.I,
)
# (d) A scenario label: the name (or a part of it) of the scenario whose old value
# the number is, then LINK words, then the number.  Names split on separators and
# enumerators ("A：基准扩张" → "A", "基准扩张"; "Other / Status Quo" → "Status Quo";
# "Path A" → "A"; "Base Case" → "Base").  A one-word label must match its first
# letter exactly ("Recession", not "recession"), the rest ignores case.
_LABEL_LOOKBACK_CHARS = 80
_NAME_SPLIT_RE = re.compile(r"[:：/|()（）\[\]【】,，;；]|\s[-–—]\s|—")
_NAME_ENUMERATOR_RE = re.compile(r"^(?P<enum>[A-Z]|\d{1,2})\s*[.)．、]\s*(?=\S)")
_NAME_GENERIC_PREFIX_RE = re.compile(r"^(?:path|scenario|case|outcome)\s+(?=\S)", re.I)
_NAME_GENERIC_SUFFIX_RE = re.compile(
    r"(?:\s+(?:case|scenario|path|outcome)s?|\s*(?:情景|场景|路径|情形))$", re.I
)
_NAME_GENERIC_WORDS = frozenset({"case", "scenario", "path", "outcome", "情景", "场景", "路径", "情形"})
# A residual word on its own is no label: "Other / Status Quo" is the pipeline's
# leftover scenario, and "LFP 45%, NMC 35%, Other 20%" is any breakdown's last row.
_NAME_RESIDUAL_WORDS = frozenset({"other", "others", "其它", "其他", "mixed", "混合"})
_LABEL_STATE_WORDS = (
    r"is|was|are|has|had|been|now|still|currently|at|holds?|held|gets?|got|carries|carried"
    r"|leads?|led|trails?|trailed|sits?|sat|stands?|stood|remains?|remained|stays?|stayed"
    r"|settles?|settled|ends?|ended|(?:comes?|came)\s+in|set|put|assigned|most|likely"
)
_LABEL_MOVE_WORDS = (
    r"cut|raised|lowered|trimmed|reduced|increased|revised|moved|nudged|lifted|pushed|pulled"
    r"|marked|falls?|fell|rises?|rose|drops?|dropped|declines?|declined|climbs?|climbed"
    r"|slips?|slipped|edges?|edged|down|up|back"
)
# Label, optional possessive and generic noun, optional separator, then LINK words that
# end on a state word or "to" ("Bear is cut to 20%", "Path A leads at 45%"; never "Base
# falls 40%", a change), an optional hedge, and the token.
_LABEL_TAIL = (
    r"(?:['’]s)?(?:\s+(?i:case|scenario|path|outcome)s?|\s*(?:情景|场景|路径|情形))?"
    r"\s*(?:[:：=]|为|是|约为|仍为|维持在?|降至|升至|调至|下调至|上调至|降为|升为|调整为"
    r"|修正为|下修至|上修至)?\s*"
    r"(?i:(?:(?:(?:" + _LABEL_STATE_WORDS + r"|" + _LABEL_MOVE_WORDS + r")\s+)*"
    r"(?:" + _LABEL_STATE_WORDS + r"|to)\s+)?)"
    r"(?:(?:~|～|≈|约|大约|(?i:approx\.?|about|around|roughly|approximately|nearly|only"
    r"|just))\s*)?$"
)
# Market / outside-forecaster citations: never the pipeline's own scenario numbers.
# A market word vetoes every later token of its sentence ('The Polymarket snapshot
# provides three anchors: "D House" (84%), …, "D sweep" (44%)'), and any token within
# 40 characters after it or right before it.  The sentence ends at 。；;！？!?, a newline
# or a '.' before a space — not the dot of a decimal, of an initial or of a common
# abbreviation ("U.S.", "vs.", "approx."), which would cut the sentence short.
_MARKET_WINDOW_CHARS = 40
_MARKET_WORDS = (
    r"polymarket|kalshi|metaculus|manifold|predictit|good\s+judgment|hypermind|market"
    r"|市场|盘口|赔率|superforecast|consensus|analyst|futures|fedwatch|betting|bookmaker"
    r"|共识|一致预期|分析师"
    # outside forecasters whose own "base case" / probabilities a narrative cites
    r"|goldman|jpmorgan|j\.\s?p\.\s?morgan|morgan\s+stanley|citigroup|barclays|nomura"
    r"|bank\s+of\s+america|deutsche\s+bank|(?<![A-Za-z])(?:ubs|bofa|hsbc|imf|oecd)(?![A-Za-z])"
    r"|world\s+bank|bloomberg|reuters|(?<![A-Za-z])(?:iea|bnef|eia|ipcc)(?![A-Za-z])"
    r"|高盛|摩根|花旗|瑞银|野村|汇丰|彭博|路透|国际货币基金|世界银行|国际能源署"
)
_MARKET_BEFORE_RE = re.compile(_MARKET_WORDS, re.I)
_MARKET_SENTENCE_STOP_RE = re.compile(
    r"[。；;！？!?\n]"
    r"|(?<!\d)(?<![^A-Za-z][A-Za-z])(?<!^[A-Za-z])(?<!\bvs)(?<!\bprob)(?<!\bapprox)(?<!\betc)"
    r"(?<!\bInc)(?<!\bCorp)(?<!\bCo)(?<!\bNo)(?<!\bSt)(?<!\bMr)(?<!\bDr)\.(?=\s|$)",
    re.I,
)
_MARKET_AFTER_RE = re.compile(
    r"\s*(?:[,，(（]\s*)?(?:(?:on|per|at|in|from|via|by|according\s+to)\s+)?(?:the\s+)?"
    r"(?:" + _MARKET_WORDS + r")",
    re.I,
)

# Range guard: the token is joined to another number by a dash, tilde, 至/到 or "to"
# (BEFORE searched at the end of a lookback slice, AFTER matched at the token end).
# A before→after pair is joined the same way, also through an arrow or a move verb
# ("40%下调至35%", "由40%调整为35%", "40% down to 35%"), and "from 40%" / "从40%" opens
# one: both ends are history or a critic's target, never one scenario's current value.
# The other endpoint may be written in any digit script (Unicode \d) and carry a sign
# ("–40% to –55%"): a guard that over-detects a range only skips a token, it never
# rewrites one.
_MOVE_VERB = r"(?:下调|上调|调降|调升|下修|上修|调整|修正|降低|提高|下降|上升|回落|回升|降|升|增|减|改)"
_RANGE_JOINER = (
    r"(?:-|–|—|~|～|→|->|=>|⇒|(?:(?:down|up|back)\s+)?to|"
    + _MOVE_VERB + r"?(?:至|到)|" + _MOVE_VERB + r"为)"
)
_RANGE_BEFORE_RE = re.compile(
    r"(?:\d\s*[%％]?\s*" + _RANGE_JOINER + r"|(?<![A-Za-z])from|从|由)\s*$", re.I
)
_RANGE_AFTER_RE = re.compile(
    r"\s*" + _RANGE_JOINER + r"\s*[+＋\-−–—±]?\s*\.?\d", re.I
)
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
# "40% smaller", "40% below 2020 levels", "13% inflation", "40% capacity factor",
# "40% of respondents", "约40%的装机").  Only adjacency counts, so "Soft landing (40%)
# — rate cuts" keeps its probability, and "40% of the probability mass" / "40%的概率"
# / "40%的发生概率" / "40%的可能性" stay probabilities.
_QUANTITY_TAIL_RE = re.compile(
    r"\s*(?:以上|以下|以内|或以上|或以下|[一-鿿]{0,5}?" + _RATE_CJK
    + r"|的(?!\s*(?:可能|机会|把握)|[^\s\d%％，。；,;、]{0,4}?(?:概率|几率|或然))"
    r"|(?:or|and)\s+(?:more|less|higher|lower|above|below)(?![A-Za-z])"
    r"|(?:[A-Za-z-]+\s+)?(?:rates?|tariffs?|CAGR|IRR)(?![A-Za-z])"
    r"|(?:decline[sd]?|drops?|increases?|reductions?|rises?|falls?|gains?|cuts?|jumps?"
    r"|surges?|lower|higher|cheaper|faster|slower|more|less|smaller|larger|bigger|greater"
    r"|fewer|worse|better|below|above|inflation|unemployment"
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
# LEAD: the token is led by a comparator, by 占, by a quantity or change word or a
# CJK comparison ("较2020年低"), with only linking words and hedges in between ("EV
# share above 40%", "≥40%的装机", "<=40%", "不及40%", "占约40%", "占全球装机的40%", "the
# base rate is 13%", "CAGR约13%", "margin of about 13%", "通胀约13%", "涨幅达40%", "prices
# rose by 40%", "costs have fallen 40%", "capex cut 40%", "WACC 13%", "关税40%", "成本
# 下降约40%", "成本减少了约40%", "价格较2020年低40%").  Adjacency is what makes it a
# quantity: "基准情景占主导（40%）" and "高通胀情景（40%）" keep their probability.  A
# bare CJK change verb takes only the hedges of an amount (了 / 约 / 近 / 达 …), never
# 为 / 至 / 到, because "概率降为35%" / "降至35%" names a new level (a critic's target),
# not a change; the English "cut to 20%" is likewise no quantity ("to" is not a
# linker).  Searched at the end of a lookback slice.
_QUANTITY_LEAD_LOOKBACK_CHARS = 40
_LEAD_WORDS_EN = (
    r"rates?|tariffs?|CAGR|IRR|margins?|shares?|growth|yields?|inflation|discount|premium"
    r"|returns?|stake|weight(?:ing)?|increase[sd]?|decrease[sd]?|rises?|rose|falls?|fell"
    r"|fallen|drops?|dropped|decline[sd]?|gains?|gained|jump(?:s|ed)?|surge[sd]?|up|down|by"
    r"|grew|grows?|grown|shr[ai]nks?|shrunk|expand(?:s|ed)?|contract(?:s|ed)?"
    r"|climb(?:s|ed)?|plunge[sd]?|soar(?:s|ed)?|tumble[sd]?|slump(?:s|ed)?|rebound(?:s|ed)?"
    r"|slid|sank|lost|added"
    r"|cuts?|reduce[sd]?|slashe[sd]|lowered|raised|WACC|ROE|ROI|unemployment|interest"
    r"|vacancy|utili[sz]ation|efficiency|(?:capacity|load)\s+factor"
)
_LEAD_LINKERS_EN = (
    r"is|was|are|were|of|at|by|near|around|about|roughly|approximately|only|just"
    r"|stands|stood|reached|hit"
)
_LEAD_WORDS_CJK = (
    r"涨幅|跌幅|降幅|增幅|升幅|幅度|比例|比重|通胀|折扣|溢价|折价|回报|收益|权重|利润"
    r"|上涨|下跌|关税|毛利"
)
_LEAD_CHANGE_VERBS_CJK = (
    r"下降|降低|上升|提高|提升|下滑|削减|缩减|压缩|下探|回落|回升|回撤|暴跌|暴涨|降价|涨价"
    r"|增加|减少|萎缩|缩水|扩大|扩张|收窄|腰斩|下调|上调|跌去|跌掉"
    r"|跌|涨|降|升|减|增"
)
_LEAD_CHANGE_HEDGES_CJK = r"了?\s*(?:大约|约|将近|近|逾|超|仅|高达|达)?"
_COMPARATORS = (
    r"超过|超出|高于|低于|不低于|不高于|不少于|不超过|不足|不到|不及|未及|未达|至少|最多"
    r"|大于|小于|多于|少于|逾"
    r"|(?<![A-Za-z])(?:above|over|below|under|beyond|at\s+(?:least|most)"
    r"|(?:more|less|fewer|greater)\s+than|exceed(?:s|ed|ing)?)"
    r"|<=|>=|=<|=>|[≥≤⩾⩽≦≧<]|(?<![-=])>"
)
# "较2020年低40%", "比基准高40%": a comparison with a reference, then the amount.
_CJK_COMPARISON = (
    r"(?:较|比)[^，。；,;！？!?\n%％]{0,12}?(?:低|高|少|多|便宜|贵|快|慢)"
    r"\s*了?\s*(?:大约|约|将近|近|逾|超|达)?"
)
_QUANTITY_LEAD_RE = re.compile(
    r"(?:(?:(?<![A-Za-z])(?:" + _LEAD_WORDS_EN + r")(?:\s+(?:" + _LEAD_LINKERS_EN + r"))*"
    r"|" + _LEAD_WORDS_CJK
    + r"|占[^\s\d%％.,，。；;：:()（）、]{0,6}?"
    r"|" + _COMPARATORS + r")"
    r"\s*(?:约为|约|近|逾|仅|(?:可|将|已)?达|为|在|[~≈]"
    r"|(?:about|around|roughly|nearly|approximately)\s)?\s*$"
    r"|(?:" + _LEAD_CHANGE_VERBS_CJK + r")\s*" + _LEAD_CHANGE_HEDGES_CJK + r"\s*$"
    r"|" + _CJK_COMPARISON + r"\s*$)",
    re.I,
)
# A signed number ("+10%", "−5%", "±3%") is a change, never a probability.  A sign
# after a digit ("40%-45%") is a range joiner, which the range guard checks first.
# An en or em dash is a minus sign only when no word, digit or percent sign precedes
# it ("correction of –40%", "—40% YoY"); "Base–40%" or "30–40%" is not.
_SIGN_CHARS = frozenset("+＋-−±")
_DASH_SIGN_CHARS = frozenset("–—")

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
# A sum statement lists a handful of addends; a longer run is not one we can read,
# so the sentence is shielded whole (this also bounds the scan per sum word).
_SUM_MAX_ADDENDS = 12

_Token = Tuple[int, int, int, str]          # (start, end, percent value, kind)
_Span = Tuple[int, int]


class _Move(NamedTuple):
    """One probability move as seen by one field (see ``_value_mapping``)."""

    mapping: Dict[int, int]
    unresolved: Dict[int, str]
    fresh: Set[int]
    owners: Dict[int, Tuple[str, ...]]      # mapped old value -> its scenario's raw names
    names: Tuple[str, ...]                  # every raw scenario name on any side


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
) -> _Move:
    """Map old integer percents to new ones for scenarios whose value changed.

    Rows pair by ``ensemble._norm_name``; an empty name, or one that occurs twice on
    either side, never pairs.  Returns a ``_Move``: ``mapping``, ``unresolved``,
    ``fresh``, ``owners`` (each mapped old value's scenario, by its raw BEFORE and
    AFTER names, for the label slot) and ``names`` (every raw scenario name of the
    BEFORE, AFTER and context rows, for the label slot of a foreign token).

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

    raw_before = {name: row.get("name") for name, _, row in before if name in paired}
    changed: List[Tuple[str, int, int]] = []
    owners: Dict[int, Tuple[str, ...]] = {}
    for name, new_pct, row in after:
        if name not in paired or (only is not None and row is not only):
            continue
        old_pct = old_by_name[name]
        if old_pct != new_pct:
            changed.append((name, old_pct, new_pct))
            owners[old_pct] = _raw_names((raw_before[name], row.get("name")))
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
    names = _raw_names(row.get("name") for rows in (before, after, context) for _, _, row in rows)
    return _Move(mapping, unresolved, fresh,
                 {old: owners[old] for old in mapping}, names)


def _raw_names(names: Any) -> Tuple[str, ...]:
    """Distinct non-empty string names, in order."""
    return tuple(dict.fromkeys(name.strip() for name in names
                               if isinstance(name, str) and name.strip()))


def _linked(text: str, start: int, end: int) -> bool:
    """``text[start:end]`` holds only linking words (see ``_LINK_GAP_RE``)."""
    return end - start <= _PROB_GAP_MAX_CHARS and bool(_LINK_GAP_RE.fullmatch(text, start, end))


def _decimal_in_probability_context(text: str, start: int, end: int) -> bool:
    """A two-decimal fraction is a token only in slot (c) and only when it closes its
    clause (or opens a range, which the range guard then skips: "概率从0.40降到0.35")."""
    window = (max(0, start - _DECIMAL_STATISTIC_WINDOW_CHARS), end + _DECIMAL_STATISTIC_WINDOW_CHARS)
    if (_DECIMAL_CURRENCY_BEFORE_RE.search(text, max(0, start - 2), start)
            or _DECIMAL_CURRENCY_AFTER_RE.match(text, end)
            or not (_SLOT_END_RE.match(text, end) or _RANGE_AFTER_RE.match(text, end))
            or _DECIMAL_STATISTIC_RE.search(text, *window)):
        return False
    lower = max(0, start - _PROB_GAP_MAX_CHARS - _PROB_TRIGGER_MAX_CHARS)
    for trigger in _DECIMAL_TRIGGER_RE.finditer(text, lower, start):
        if not _linked(text, trigger.end(), start):
            continue
        if trigger.group("p_value") and (
                not _P_VALUE_OPEN_RE.search(text, max(0, trigger.start() - 4), trigger.start())
                or _P_VALUE_STATISTIC_RE.search(text, *window)):
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


def _is_quantity(text: str, start: int, end: int, names: Tuple[str, ...] = ()) -> bool:
    """The token is a quantity or a signed change (see the quantity guard above).

    A quantity word before the token that lies inside a label of ``names`` is part of
    a scenario name, not a quantity ("我们给基准扩张40%的概率" for "A：基准扩张",
    "Tariff Ratchet Up at 25%"), so the BEFORE and LEAD guards skip it.
    """
    if start > 0 and (text[start - 1] in _SIGN_CHARS or (
            text[start - 1] in _DASH_SIGN_CHARS
            and (start == 1 or not (text[start - 2].isalnum() or text[start - 2] in "%％")))):
        return True
    if _QUANTITY_AFTER_RE.match(text, end) or _QUANTITY_TAIL_RE.match(text, end):
        return True
    for word in _QUANTITY_BEFORE_RE.finditer(text, max(0, start - _QUANTITY_BEFORE_WINDOW), start):
        if not _inside_label(text, word.start(), start, names):
            return True
    lower = max(0, start - _QUANTITY_LEAD_LOOKBACK_CHARS)
    while True:
        lead = _QUANTITY_LEAD_RE.search(text, lower, start)
        if lead is None:
            return False
        if not _inside_label(text, lead.start(), start, names):
            return True
        lower = lead.start() + 1


def _inside_label(text: str, position: int, end: int, names: Tuple[str, ...]) -> bool:
    """A label of ``names`` that ends by ``end`` covers ``text[position]``."""
    mention = _mention_re(names)
    if mention is None:
        return False
    for label in mention.finditer(text, max(0, position - _LABEL_LOOKBACK_CHARS), end):
        if label.start() > position:
            return False
        if position < label.end():
            return True
    return False


class _MarketCitations:
    """Whether a market or an outside forecaster is cited for a token of ``text``:
    anywhere earlier in its sentence, within 40 characters before it, or right after
    it.  The first market word of each sentence is found once, so the check stays
    linear in the text."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._starts = [0] + [stop.end() for stop in _MARKET_SENTENCE_STOP_RE.finditer(text)]
        self._first: Dict[int, int] = {}

    def __call__(self, start: int, end: int) -> bool:
        text = self._text
        if (_MARKET_AFTER_RE.match(text, end)
                or _MARKET_BEFORE_RE.search(text, max(0, start - _MARKET_WINDOW_CHARS), start)):
            return True
        sentence = bisect_right(self._starts, start) - 1
        if sentence not in self._first:
            lo = self._starts[sentence]
            hi = self._starts[sentence + 1] if sentence + 1 < len(self._starts) else len(text)
            market = _MARKET_BEFORE_RE.search(text, lo, hi)
            self._first[sentence] = market.start() if market else len(text)
        return self._first[sentence] < start


@lru_cache(maxsize=1024)
def _name_aliases(name: str) -> Tuple[str, ...]:
    """Labels a text may use for the scenario called ``name``, longest first.

    The name itself, its parts between separators ("A：基准扩张" → "A", "基准扩张";
    "Other / Status Quo" → "Status Quo"), an enumerator and the rest after it ("A.
    基准" → "A", "基准"), and each of those without a generic word ("Base Case" →
    "Base", "Path A" → "A", "基准情景" → "基准").  A part is kept when it has a letter
    or a CJK character, is neither only a generic word nor only a residual word
    ("Other", "其它", "Mixed": a breakdown's "Other 20%" row is no scenario), and — if
    it is a single Latin letter — is upper-case.
    """
    parts = [" ".join(name.split())]
    parts += [part.strip() for part in _NAME_SPLIT_RE.split(parts[0])]
    for part in list(parts):
        enumerated = _NAME_ENUMERATOR_RE.match(part)
        if enumerated:
            parts += [enumerated.group("enum"), part[enumerated.end():]]
    for part in list(parts):
        parts.append(_NAME_GENERIC_SUFFIX_RE.sub("", _NAME_GENERIC_PREFIX_RE.sub("", part)))
    aliases = set()
    for part in parts:
        part = part.strip()
        if (not part or part.lower() in _NAME_GENERIC_WORDS
                or part.lower() in _NAME_RESIDUAL_WORDS
                or not re.search(r"[A-Za-z一-鿿]", part)
                or (len(part) == 1 and not part.isupper())):
            continue
        aliases.add(part)
    return tuple(sorted(aliases, key=lambda alias: (-len(alias), alias)))


def _alias_pattern(alias: str) -> str:
    """Regex for one label: first character exact, the rest case-insensitive.

    ``alias`` has single spaces (``_name_aliases`` normalises them); each matches any
    run of whitespace.
    """
    body = alias[1:]
    rest = r"\s+".join(re.escape(part) for part in body.split(" "))
    pattern = re.escape(alias[0]) + (f"(?i:{rest})" if body else "")
    if alias[0].isascii() and alias[0].isalnum():
        pattern = r"(?<![A-Za-z0-9_])" + pattern
    if alias[-1].isascii() and alias[-1].isalnum():
        pattern += r"(?![A-Za-z0-9])"
    return pattern


@lru_cache(maxsize=512)
def _mention_pattern(names: Tuple[str, ...]) -> Optional[str]:
    """Any label of ``names``: a multi-word label ignoring case ("upside surprise" for
    "D: Upside surprise"), a one-word label as ``_alias_pattern`` has it (first
    character exact: "Recession" names the scenario, "a recession" does not)."""
    aliases = sorted({alias for name in names for alias in _name_aliases(name)},
                     key=lambda alias: (-len(alias), alias))
    if not aliases:
        return None
    parts = []
    for alias in aliases:
        if " " not in alias:
            parts.append(_alias_pattern(alias))
            continue
        part = "(?i:" + r"\s+".join(re.escape(word) for word in alias.split(" ")) + ")"
        if alias[0].isascii() and alias[0].isalnum():
            part = r"(?<![A-Za-z0-9_])" + part
        if alias[-1].isascii() and alias[-1].isalnum():
            part += r"(?![A-Za-z0-9])"
        parts.append(part)
    return "(?:" + "|".join(parts) + ")"


@lru_cache(maxsize=512)
def _mention_re(names: Tuple[str, ...]) -> Optional[Pattern[str]]:
    """Any label of ``names`` anywhere (see ``_mention_pattern``)."""
    pattern = _mention_pattern(names)
    return re.compile(pattern) if pattern else None


@lru_cache(maxsize=512)
def _label_end_re(names: Tuple[str, ...]) -> Pattern[str]:
    """A label of ``names`` or a scenario word that ends the searched slice (the text
    right before a bracket: "Recession (25%)", "基准情景（40%）", "(base case) (40%)")."""
    mention = _mention_pattern(names)
    label = f"(?:{mention}|{_SCENARIO_WORD})" if mention else _SCENARIO_WORD
    return re.compile(label + _LABEL_END_TAIL)


@lru_cache(maxsize=512)
def _owner_label_re(names: Tuple[str, ...]) -> Optional[Pattern[str]]:
    """A whole bracket label that is a label of ``names``, optionally with a possessive
    and a generic noun ("A", "Base case", "Recession scenario", "基准扩张情景")."""
    mention = _mention_pattern(names)
    if mention is None:
        return None
    return re.compile(
        mention + r"(?:['’]s)?(?:\s+(?i:" + _OBJECT_NOUN + r")|\s*(?:情景|场景|路径|情形))?")


@lru_cache(maxsize=512)
def _object_res(names: Tuple[str, ...]) -> Tuple[Pattern[str], Pattern[str], Pattern[str]]:
    """Full-match patterns for an English probability word's object that IS the
    scenario: after "of" / "for" / "to" a noun phrase ("the base case", "Recession",
    "the Base scenario", "the status quo" for "Other / Status Quo"), optionally with a
    verb of occurrence; after "that" a noun phrase and such a verb ("the downside
    scenario plays out"); after "to" also the verb alone ("likely to materialise",
    which then needs the scenario earlier in the clause).  Each may end on a date
    ("by 2030") or "over the horizon"."""
    mention = _mention_pattern(names)
    reference = f"(?:{mention}(?:['’]s)?(?:[\\s-]+(?i:{_OBJECT_NOUN}))?|(?i:{_OBJECT_SCENARIO}))" \
        if mention else f"(?i:{_OBJECT_SCENARIO})"
    phrase = f"(?i:{_OBJECT_DETERMINER}){reference}"
    verb = f"(?i:{_OBJECT_VERB})"
    adjunct = f"(?i:{_OBJECT_ADJUNCT})"
    return (re.compile(f"{phrase}(?:\\s+{verb})?{adjunct}"),
            re.compile(f"{phrase}\\s+{verb}{adjunct}"),
            re.compile(f"{verb}{adjunct}"))


@lru_cache(maxsize=512)
def _label_slot_re(names: Tuple[str, ...]) -> Optional[Pattern[str]]:
    """Slot (d) for scenarios called ``names``: a label, LINK words, then the token."""
    aliases = sorted({alias for name in names for alias in _name_aliases(name)},
                     key=lambda alias: (-len(alias), alias))
    if not aliases:
        return None
    return re.compile(
        "(?:" + "|".join(_alias_pattern(alias) for alias in aliases) + ")" + _LABEL_TAIL)


def _labelled_before(text: str, position: int, names: Tuple[str, ...]) -> bool:
    """A label of ``names`` or a scenario word ends right before ``position``."""
    return bool(_label_end_re(names).search(
        text, max(0, position - _LABEL_LOOKBACK_CHARS), position))


def _names_scenario(text: str, lo: int, hi: int, names: Tuple[str, ...]) -> bool:
    """``text[lo:hi]`` holds a scenario word or a label of ``names``."""
    if _SCENARIO_WORD_RE.search(text, lo, hi):
        return True
    mention = _mention_re(names)
    return bool(mention is not None and mention.search(text, lo, hi))


def _clause_names_scenario(text: str, position: int, names: Tuple[str, ...]) -> bool:
    """The clause before ``position`` (at most 80 characters) names a scenario."""
    lo = max(0, position - _CLAUSE_LOOKBACK_CHARS)
    for stop in _CLAUSE_STOP_RE.finditer(text, lo, position):
        lo = stop.end()
    return _names_scenario(text, lo, position, names)


def _names_scenario_after(text: str, position: int, names: Tuple[str, ...]) -> bool:
    """A scenario is named right after ``position``, before a comma or a clause stop
    ("仅10%概率超预期上行")."""
    hi = min(len(text), position + _CLAUSE_AFTER_CHARS)
    stop = _CLAUSE_AFTER_STOP_RE.search(text, position, hi)
    return _names_scenario(text, position, stop.start() if stop else hi, names)


def _bracket_label(inner: Optional[str], separator: Optional[str]) -> Optional[str]:
    """The word label a bracket gives its token, or None (see ``_LABELLING_SEPARATORS``)."""
    if inner is None:
        return None
    label = _SLOT_SEPARATOR_RE.split(inner)[-1].strip(_LABEL_STRIP_CHARS)
    if not label:
        return None
    if separator in _LABELLING_SEPARATORS:
        return label
    return label if _LABEL_WORD_RE.search(label) and not _DIGIT_RE.search(label) else None


def _bracket_is_labelled(text: str, bracket: "re.Match[str]", names: Tuple[str, ...],
                         any_object: bool) -> bool:
    """Slot (a)'s label rule: a word label inside the bracket must be a label of
    ``names`` or a probability word (then a scenario must be named earlier in the
    clause); without one, a label of ``names`` or a scenario word must end right
    before the bracket."""
    opening = bracket.start()
    label = _bracket_label(bracket.group("inner"), bracket.group("sep"))
    if label is None:
        return _labelled_before(text, opening, names)
    if _metric_before_bracket(text, opening, names):
        return False
    owner = _owner_label_re(names)
    if owner is not None and owner.fullmatch(label):
        return True
    if _PROB_LABEL_RE.fullmatch(label):
        return any_object or _clause_names_scenario(text, opening, names)
    return False


def _metric_before_bracket(text: str, opening: int, names: Tuple[str, ...]) -> bool:
    """A metric noun stands in the clause shortly before the bracket at ``opening``
    (see ``_METRIC_BEFORE_BRACKET_CHARS``); one inside a label of ``names`` is part of
    a scenario name."""
    lo = max(0, opening - _METRIC_BEFORE_BRACKET_CHARS)
    for stop in _CLAUSE_STOP_RE.finditer(text, lo, opening):
        lo = stop.end()
    return any(not _inside_label(text, word.start(), opening, names)
               for word in _METRIC_NOUN_RE.finditer(text, lo, opening))


def _english_word_slot(text: str, start: int, word_end: int, names: Tuple[str, ...]) -> bool:
    """Slot (b) for an English probability word: its object must be the scenario;
    without an object, a scenario must be named earlier in the clause."""
    target = _PROB_OBJECT_RE.match(text, word_end)
    if target is None:
        return _clause_names_scenario(text, start, names)
    words = _OBJECT_CUT_RE.split(target.group("object"), maxsplit=1)[0].strip(_OBJECT_STRIP_CHARS)
    phrase_re, that_re, verb_re = _object_res(names)
    lead = target.group("lead").lower()
    if lead == "that":
        return bool(that_re.fullmatch(words))
    if lead == "to" and verb_re.fullmatch(words):
        return _clause_names_scenario(text, start, names)
    return bool(phrase_re.fullmatch(words))


def _in_slot(text: str, start: int, end: int, kind: str, names: Tuple[str, ...],
             any_object: bool = False) -> bool:
    """The token sits in a recognised probability slot that names a scenario (see
    the module docstring).

    ``names`` are the scenario names whose labels count (the owner's, or every name of
    the move for a foreign token).  ``any_object`` drops the naming requirement of the
    probability-word slots (b) and (c) and of a bracketed probability word: the
    over-inclusive reading a foreign token's record needs, since a record only blocks.
    """
    if kind == "decimal":               # slot (c), or a bracketed "p=" (slot (a))
        p_bracket = _P_BRACKET_RE.search(text, max(0, start - _P_BRACKET_LOOKBACK_CHARS), start)
        if p_bracket:
            return _labelled_before(text, p_bracket.start(), names)
        return any_object or _clause_names_scenario(text, start, names)
    after = _PAREN_AFTER_RE.match(text, end)
    bracket = after and _PAREN_BEFORE_RE.search(text, max(0, start - _PAREN_LOOKBACK_CHARS), start)
    if bracket:
        if not after.group("close"):
            rest = _PAREN_REST_RE.match(text, end)
            if not rest or _RANGE_INSIDE_RE.search(rest.group("rest")):
                return False
        return _bracket_is_labelled(text, bracket, names, any_object)
    # Any other slot inside a bracket that follows a metric noun lists the metric
    # ("资本开支增速（基准扩张40%，电力受限25%）").
    inside = _OPEN_BRACKET_RE.search(text, max(0, start - _OPEN_BRACKET_LOOKBACK_CHARS), start)
    if inside and _metric_before_bracket(text, inside.start(), names):
        return False
    word = _PROB_AFTER_RE.match(text, end)
    if word:
        if any_object:
            return True
        if word.group("en"):
            return _english_word_slot(text, start, word.end(), names)
        return (_clause_names_scenario(text, start, names)
                or _names_scenario_after(text, word.end(), names))
    if not _SLOT_END_RE.match(text, end):
        return False
    lower = max(0, start - _PROB_GAP_MAX_CHARS - _PROB_TRIGGER_MAX_CHARS)
    for trigger in _PROB_TRIGGER_RE.finditer(text, lower, start):
        if _linked(text, trigger.end(), start) and (
                any_object or _clause_names_scenario(text, trigger.start(), names)):
            return True
    label_re = _label_slot_re(names)
    label = label_re.search(text, max(0, start - _LABEL_LOOKBACK_CHARS), start) if label_re else None
    if label is None:
        return False
    sentence = max(0, label.start() - _HEADER_LOOKBACK_CHARS)
    for stop in _HEADER_STOP_RE.finditer(text, sentence, label.start()):
        sentence = stop.end()
    # The header's look-ahead reads the label's first character.
    return not _METRIC_HEADER_RE.search(text, sentence, label.start() + 1)


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
    """Contiguous neighbours of the aggregate whose values add up to it (nearest first).

    At most ``_SUM_MAX_ADDENDS`` neighbours are tried on each side.
    """
    target = values[aggregate]
    total = 0
    for index in range(aggregate - 1, max(-1, aggregate - 1 - _SUM_MAX_ADDENDS), -1):
        total += values[index]
        if abs(total - target) <= _SUM_TOLERANCE_PCT:
            return range(index, aggregate)
        if total > target + _SUM_TOLERANCE_PCT:
            break
    total = 0
    for index in range(aggregate + 1, min(len(values), aggregate + 1 + _SUM_MAX_ADDENDS)):
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
    "基准情景（40%）" earlier in the same sentence can still be synced.  Each sum
    word finds its total by bisection, so the cost is linear in the sentence.
    """
    if _ARITHMETIC_PLUS_RE.search(text, start, end):
        return None
    sum_words = list(_SUM_WORD_RE.finditer(text, start, end))
    if not sum_words:
        return set()
    percents = list(_INT_PERCENT_RE.finditer(text, start, end))
    starts = [match.start() for match in percents]
    ends = [match.end() for match in percents]
    values = [int(match.group("num")) for match in percents]
    shielded: Set[_Span] = set()
    for word in sum_words:
        # The first percent starting after the word, else the last one ending before it.
        aggregate = bisect_left(starts, word.end())
        if aggregate == len(percents) or starts[aggregate] - word.end() > _AGGREGATE_AFTER_WINDOW:
            aggregate = bisect_right(ends, word.start()) - 1
            if aggregate < 0 or word.start() - ends[aggregate] > _AGGREGATE_BEFORE_WINDOW:
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


def _rewrite(text: str, move: _Move) -> Tuple[str, List[Dict[str, str]], Dict[str, int], Set[int]]:
    """Apply ``move.mapping`` to ``text`` in one pass by span.

    Returns ``(new_text, edits, skipped, unattributed)``; ``unattributed`` holds the
    values of tokens left alone because ``move.unresolved`` names them, and of
    ``foreign`` tokens: a token whose value is in ``move.fresh`` (no scenario of this
    move held it before the move, but one holds it now: "a rate-cut scenario (25%)")
    that sits in a probability slot and that no range, quantity or market guard
    skips.  Those guards read only the words around the token, never a number's value,
    so they skip the same token again at every later step.  The slots and the
    quantity guard's exemption for a word inside a scenario label depend on the
    owner's names, so a foreign token is read with every scenario name of the move
    (the next step may attribute the value to any of them) and with the naming
    requirement of the probability-word slots dropped; the sum shield also depends
    on the values of the other numbers in the sentence, which later steps may
    rewrite, so a foreign token inside a sum statement is still recorded.
    """
    skipped: Counter = Counter()
    unattributed: Set[int] = set()
    if not move.mapping and not move.unresolved and not move.fresh:
        return text, [], {}, unattributed
    sentences = _sentence_bounds(text)
    sentence_starts = [lo for lo, _ in sentences]
    shields: Dict[int, Optional[Set[_Span]]] = {}
    is_market = _MarketCitations(text)
    replacements: List[Tuple[int, int, str]] = []
    for token in _probability_tokens(text):
        start, end, value, kind = token
        reason = move.unresolved.get(value)
        if reason is not None:
            skipped[reason] += 1
            unattributed.add(value)
            continue
        new_pct = move.mapping.get(value)
        if new_pct is None:
            if (value in move.fresh and not _is_range(text, start, end)
                    and not _is_quantity(text, start, end, move.names)
                    and not is_market(start, end)
                    and _in_slot(text, start, end, kind, move.names, any_object=True)):
                skipped["foreign"] += 1
                unattributed.add(value)
            continue
        owner = move.owners.get(value, ())
        if _is_range(text, start, end):
            skipped["range"] += 1
            continue
        if _is_quantity(text, start, end, owner):
            skipped["quantity"] += 1
            continue
        sentence = bisect_right(sentence_starts, start) - 1
        if sentence not in shields:
            shields[sentence] = _sum_shield(text, *sentences[sentence])
        shield = shields[sentence]
        if shield is None or (start, end) in shield:
            skipped["sum"] += 1
            continue
        if is_market(start, end):
            skipped["market"] += 1
            continue
        if not _in_slot(text, start, end, kind, owner):
            skipped["no_slot"] += 1
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
    foreign / range / quantity / sum / market / no_slot).  A non-string or empty
    ``text`` is returned unchanged.
    """
    if not isinstance(text, str) or not text:
        return text, [], {}
    new_text, edits, skipped, _ = _rewrite(text, _value_mapping(before_rows, after_rows))
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

    def collect(target: Dict[str, Any], field: str, label: str, key: str, move: _Move) -> None:
        text = target.get(field)
        if not isinstance(text, str) or not text:
            return
        carried = prior_blocked.get(key, set()) if key else set()
        move = move._replace(unresolved={
            **move.unresolved,
            **{value: "ambiguous" for value in carried if value in move.mapping}})
        new_text, edits, reasons, unattributed = _rewrite(text, move)
        skipped.update(reasons)
        if key and not unattributed <= carried:
            blocked[key] = blocked.get(key, carried) | unattributed
        if edits:
            pending.append((target, field, text, new_text))
            log.extend({"field": label, **edit} for edit in edits)

    for field, before in (("headline", headline_before), ("confidence_rationale", rationale_before)):
        if before is not None:
            collect(out, field, field, field,
                    _value_mapping(before, after_rows, context_rows=context_rows))
    if summary_before_by_name is not None:
        for index, row in enumerate(scenarios):
            if isinstance(row, dict):
                name_key = _scenario_key(row.get("name"))
                collect(row, "summary", f"scenario[{index}].summary",
                        f"summary:{name_key}" if name_key else "",
                        _value_mapping(summary_before_by_name, after_rows, only=row,
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
